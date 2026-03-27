"""
加權評分模組（第四輪：Grid Search 校準 + 訊號衰減）

改進項目：
1. 安全閥只對基本面+籌碼生效
2. 美股法人權重歸零
3. macro_multiplier 參數
4. [R4] grid_search_weights() 用歷史資料找最佳權重
5. [R4] 新聞分數時間衰減（半衰期 3 天）
6. [R4] 分數信心度：資料來源越完整，信心越高
"""
import numpy as np

# 策略權重設定
STRATEGIES = {
    "balanced": {
        "label": "均衡",
        "description": "基本面為主，技術面降權（回測校正後）",
        "weights": {"tech": 0.10, "fund": 0.35, "inst": 0.25, "news": 0.30},
    },
    "short": {
        "label": "短線波段",
        "description": "重籌碼和消息面，技術面做風控參考",
        "weights": {"tech": 0.15, "fund": 0.15, "inst": 0.35, "news": 0.35},
    },
    "long": {
        "label": "中長線持有",
        "description": "重基本面和消息面，技術面幾乎不看",
        "weights": {"tech": 0.05, "fund": 0.40, "inst": 0.20, "news": 0.35},
    },
    "dividend": {
        "label": "存股領息",
        "description": "最重基本面，適合長期存股",
        "weights": {"tech": 0.05, "fund": 0.50, "inst": 0.15, "news": 0.30},
    },
    "longterm": {
        "label": "長線佈局",
        "description": "不看短期漲跌，只看營收成長和估值便宜度",
        "weights": {"tech": 0.0, "fund": 0.60, "inst": 0.10, "news": 0.30},
        "use_valuation": True,
    },
}


def _apply_news_decay(news_score, news_age_days=0, half_life=3.0):
    """
    [R4] 新聞分數時間衰減
    news_age_days: 新聞的平均天數（0 = 今天的新聞）
    half_life: 半衰期天數（預設 3 天）

    越舊的新聞，分數越趨近中性（5.0）
    """
    if news_age_days <= 0:
        return news_score
    decay = 0.5 ** (news_age_days / half_life)
    # 衰減後趨近 5.0（中性）
    decayed = 5.0 + (news_score - 5.0) * decay
    return round(decayed, 1)


def _calc_confidence(tech_score, fund_score, inst_score, news_score, is_us=False):
    """
    [R4] 評分信心度
    根據各項資料的完整性給出信心度

    回傳：(confidence_level, confidence_detail)
    confidence_level: "high" / "medium" / "low"
    """
    available = 0
    total = 4

    # tech: 只要有分數就算有
    if tech_score is not None and tech_score > 0:
        available += 1
    if fund_score is not None and fund_score > 0:
        available += 1
    if inst_score is not None and inst_score > 0:
        available += 1
    if news_score is not None and news_score > 0:
        available += 1

    # 美股法人資料不可靠，不算入
    if is_us:
        total = 3

    ratio = available / total if total > 0 else 0

    # 各分數差異大 = 信號矛盾 = 信心低
    scores = [s for s in [tech_score, fund_score, inst_score, news_score]
              if s is not None and s > 0]
    spread = max(scores) - min(scores) if len(scores) >= 2 else 0

    if ratio >= 0.9 and spread < 4:
        return "high", "資料完整，訊號一致"
    elif ratio >= 0.7 and spread < 6:
        return "medium", "資料大致完整"
    else:
        detail_parts = []
        if ratio < 0.7:
            detail_parts.append("部分資料缺失")
        if spread >= 6:
            detail_parts.append(f"訊號分歧大（差距 {spread:.0f}）")
        return "low", "、".join(detail_parts) if detail_parts else "資料不足"


def calc_consensus_score(tech_score, fund_score, inst_score, news_score,
                         threshold_bull=6.0, threshold_bear=4.0):
    """
    [R5] 訊號一致性分數（Consensus Score）

    統計多少個指標同方向，量化「訊號一致」程度。

    ≥ threshold_bull（預設 6.0）算多頭訊號
    <  threshold_bear（預設 4.0）算空頭訊號
    其餘算中性

    回傳 dict：
      consensus_score   0-100，越高越一致（多頭 or 空頭都算一致）
      direction         "bullish" / "bearish" / "mixed"
      bull_count        多頭指標數量（共 4 個指標）
      bear_count        空頭指標數量
      neutral_count     中性指標數量
      signal_strength   "strong"（≥3 同向）/ "moderate"（2 同向）/ "weak"（分歧）
      description       描述字串
    """
    scores = {
        "tech": tech_score,
        "fund": fund_score,
        "inst": inst_score,
        "news": news_score,
    }
    valid = {k: v for k, v in scores.items() if v is not None and v > 0}

    bull_count = sum(1 for v in valid.values() if v >= threshold_bull)
    bear_count = sum(1 for v in valid.values() if v < threshold_bear)
    neutral_count = len(valid) - bull_count - bear_count
    total = len(valid)

    if total == 0:
        return {
            "consensus_score": 50,
            "direction": "mixed",
            "bull_count": 0, "bear_count": 0, "neutral_count": 0,
            "signal_strength": "weak",
            "description": "資料不足",
        }

    # consensus_score：同方向指標佔比 × 100
    dominant = max(bull_count, bear_count)
    consensus_score = int(dominant / total * 100)

    if bull_count > bear_count:
        direction = "bullish"
    elif bear_count > bull_count:
        direction = "bearish"
    else:
        direction = "mixed"

    if dominant >= 3:
        signal_strength = "strong"
        desc = f"強訊號：{dominant}/{total} 個指標同方向（{direction}）"
    elif dominant == 2:
        signal_strength = "moderate"
        desc = f"中等訊號：{dominant}/{total} 個指標同方向（{direction}）"
    else:
        signal_strength = "weak"
        desc = f"訊號分歧：多頭 {bull_count} / 空頭 {bear_count} / 中性 {neutral_count}"

    return {
        "consensus_score": consensus_score,
        "direction": direction,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "neutral_count": neutral_count,
        "signal_strength": signal_strength,
        "description": desc,
    }


def weighted_score(tech_score, fund_score, inst_score, news_score,
                   strategy="balanced", is_us=False, macro_multiplier=1.0,
                   news_age_days=0):
    """
    根據策略計算加權綜合分數

    參數（R4 新增）：
    - news_age_days: 新聞平均天數，用於衰減計算
    回傳：(加權分數, 策略資訊 dict)
    """
    config = STRATEGIES.get(strategy, STRATEGIES["balanced"])
    w = dict(config["weights"])

    # [R4] 新聞分數衰減
    effective_news = _apply_news_decay(news_score, news_age_days)

    if is_us:
        inst_bonus = w["inst"]
        w["inst"] = 0.0
        w["fund"] += inst_bonus * 0.6
        w["news"] += inst_bonus * 0.4

    score = (
        tech_score * w["tech"]
        + fund_score * w["fund"]
        + inst_score * w["inst"]
        + effective_news * w["news"]
    )

    # === 安全閘門 ===
    core_worst = min(fund_score, inst_score) if w["inst"] > 0 else fund_score

    if core_worst <= 2:
        score = min(score, 5.0)
    elif core_worst <= 3:
        score = min(score, 6.0)

    if effective_news <= 2:
        score = min(score, 5.5)

    # === 總體經濟調整 ===
    if macro_multiplier < 1.0:
        score = score * macro_multiplier

    # [R4] 計算信心度
    confidence, conf_detail = _calc_confidence(
        tech_score, fund_score, inst_score, news_score, is_us
    )

    # 把 confidence 附加到 config 回傳
    result_config = dict(config)
    result_config["confidence"] = confidence
    result_config["confidence_detail"] = conf_detail
    if news_age_days > 0:
        result_config["news_decayed"] = True
        result_config["news_original"] = news_score
        result_config["news_effective"] = effective_news

    return round(score, 1), result_config


# =============================================================
# [R4] Grid Search Weight Calibration
# =============================================================
def grid_search_weights(history_records, price_fetcher, forward_days=10,
                        strategy="balanced"):
    """
    用歷史掃描記錄 + 之後的實際報酬，找出最佳權重組合

    history_records: list of dict, 每個 dict 含 stock_id, tech, fund, inst, news, date
    price_fetcher: function(stock_id, days) → DataFrame with 'close' and 'date'
    forward_days: 看之後幾天的報酬
    strategy: 策略名稱（決定搜尋範圍）

    回傳：{
        "best_weights": dict,
        "best_correlation": float,
        "grid_results": list,  # 所有測試過的組合
        "sample_size": int,
    }
    """
    # 先算每個股票的 forward return
    samples = []
    for rec in history_records:
        stock_id = rec.get("stock_id", "")
        rec_date = rec.get("date", "")
        if not stock_id or not rec_date:
            continue

        try:
            prices = price_fetcher(stock_id, days=forward_days + 30)
            if prices is None or prices.empty:
                continue
            prices = prices.sort_values("date").reset_index(drop=True)
            prices["close"] = prices["close"].astype(float)

            after = prices[prices["date"] > rec_date]
            if len(after) < forward_days:
                continue

            p0 = after.iloc[0]["close"]
            p1 = after.iloc[min(forward_days - 1, len(after) - 1)]["close"]
            fwd_return = (p1 / p0 - 1) * 100

            samples.append({
                "tech": rec.get("tech", 5),
                "fund": rec.get("fund", 5),
                "inst": rec.get("inst", 5),
                "news": rec.get("news", 5),
                "fwd_return": fwd_return,
            })
        except Exception:
            continue

    if len(samples) < 10:
        return {"error": f"樣本不足（{len(samples)} 筆，需要至少 10 筆）"}

    # Grid search：用 10% 步進
    tech_arr = np.array([s["tech"] for s in samples])
    fund_arr = np.array([s["fund"] for s in samples])
    inst_arr = np.array([s["inst"] for s in samples])
    news_arr = np.array([s["news"] for s in samples])
    ret_arr = np.array([s["fwd_return"] for s in samples])

    best_corr = -999
    best_weights = None
    grid_results = []

    step = 0.05  # 5% 步進
    for tw in np.arange(0, 0.31, step):
        for fw in np.arange(0.15, 0.65, step):
            for iw in np.arange(0, 0.41, step):
                nw = round(1.0 - tw - fw - iw, 2)
                if nw < 0.05 or nw > 0.50:
                    continue
                if abs(tw + fw + iw + nw - 1.0) > 0.01:
                    continue

                scores = tech_arr * tw + fund_arr * fw + inst_arr * iw + news_arr * nw

                # Pearson 相關
                if np.std(scores) > 0:
                    corr = float(np.corrcoef(scores, ret_arr)[0, 1])
                else:
                    corr = 0

                combo = {
                    "tech": round(tw, 2),
                    "fund": round(fw, 2),
                    "inst": round(iw, 2),
                    "news": round(nw, 2),
                    "correlation": round(corr, 4),
                }
                grid_results.append(combo)

                if corr > best_corr:
                    best_corr = corr
                    best_weights = combo

    # 排序
    grid_results.sort(key=lambda x: x["correlation"], reverse=True)

    # 跟目前策略的權重比較
    current = STRATEGIES.get(strategy, STRATEGIES["balanced"])["weights"]
    current_scores = (
        tech_arr * current["tech"]
        + fund_arr * current["fund"]
        + inst_arr * current["inst"]
        + news_arr * current["news"]
    )
    current_corr = float(np.corrcoef(current_scores, ret_arr)[0, 1]) if np.std(current_scores) > 0 else 0

    return {
        "best_weights": best_weights,
        "best_correlation": round(best_corr, 4),
        "current_weights": current,
        "current_correlation": round(current_corr, 4),
        "improvement": round(best_corr - current_corr, 4),
        "grid_results": grid_results[:10],  # Top 10
        "sample_size": len(samples),
        "combos_tested": len(grid_results),
    }
