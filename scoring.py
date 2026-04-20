"""
加權評分模組（第六輪：因子交互 + 相對強度 + 產業輪動 + 進場時機）

改進項目：
1. 安全閥只對基本面+籌碼生效
2. 美股法人權重歸零
3. macro_multiplier 參數
4. [R4] grid_search_weights() 用歷史資料找最佳權重
5. [R4] 新聞分數時間衰減（半衰期 3 天）
6. [R4] 分數信心度：資料來源越完整，信心越高
7. [R6] 降低 news 權重、提高 fund/inst（news 噪音大，預測力低）
8. [R6] 因子交互加分（多維度共振 = 信號更強）
9. [R6] 產業輪動 bonus（熱門產業加分、冷門扣分）
10. [R6] 相對強度 bonus（動量因子整合）
11. [R6] 進場時機判斷（綠燈但過熱 → 等拉回）
12. [R6] 動態策略切換（macro regime → 自動偏向動量或防禦）
"""
import numpy as np

# 策略權重設定（R7：降低 news 噪音、強化 inst/fund 預測力；新增美股動量專用策略）
STRATEGIES = {
    "balanced": {
        "label": "均衡",
        "description": "基本面+法人為主，消息面再降權",
        "weights": {"tech": 0.10, "fund": 0.40, "inst": 0.35, "news": 0.15},
    },
    "short": {
        "label": "短線波段",
        "description": "重籌碼，消息面降權避免雜訊",
        "weights": {"tech": 0.15, "fund": 0.15, "inst": 0.50, "news": 0.20},
    },
    "long": {
        "label": "中長線持有",
        "description": "重基本面，法人追蹤，消息面降權",
        "weights": {"tech": 0.05, "fund": 0.45, "inst": 0.30, "news": 0.20},
    },
    "dividend": {
        "label": "存股領息",
        "description": "最重基本面，適合長期存股",
        "weights": {"tech": 0.05, "fund": 0.55, "inst": 0.20, "news": 0.20},
    },
    "longterm": {
        "label": "長線佈局",
        "description": "不看短期漲跌，只看營收成長和估值便宜度",
        "weights": {"tech": 0.0, "fund": 0.60, "inst": 0.15, "news": 0.25},
        "use_valuation": True,
    },
    "us_momentum": {
        "label": "美股動量",
        "description": "美股專用：技術/趨勢主導，消息面降權（news 噪音大）",
        "weights": {"tech": 0.40, "fund": 0.30, "inst": 0.0, "news": 0.30},
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


def assess_entry_timing(score, rsi, price, ma20, ma5=None):
    """
    [R6] 進場時機判斷

    綠燈（score ≥ 7）但技術面過熱 → 建議等拉回再進場
    黃燈也可以判斷是否接近好的進場點

    參數：
      score: 加權綜合分數
      rsi: 當前 RSI(14)
      price: 當前股價
      ma20: 20 日均線
      ma5: 5 日均線（可選）

    回傳 dict：
      timing: "now" / "wait_pullback" / "not_recommended"
      reason: 原因描述
      ideal_entry: 建議進場價位（等拉回時）
    """
    if score < 4:
        return {
            "timing": "not_recommended",
            "reason": "評分偏低，不建議進場",
            "ideal_entry": None,
        }

    if score < 7:
        # 黃燈：看是否接近支撐
        if price and ma20 and price <= ma20 * 1.02:
            return {
                "timing": "watch",
                "reason": f"評分中性但股價在 MA20 附近，留意能否轉強",
                "ideal_entry": round(ma20, 2),
            }
        return {
            "timing": "not_recommended",
            "reason": "評分未達綠燈，耐心等待",
            "ideal_entry": None,
        }

    # 綠燈以上：判斷是否過熱
    overheated = False
    reasons = []

    # RSI 過高
    if rsi and rsi > 70:
        overheated = True
        reasons.append(f"RSI {rsi:.0f} 偏高")

    # 偏離 MA20 太多
    if price and ma20 and ma20 > 0:
        deviation = (price / ma20 - 1) * 100
        if deviation > 5:
            overheated = True
            reasons.append(f"偏離 MA20 達 {deviation:.1f}%")

    if overheated:
        # 建議進場價：MA5 或 MA20 附近
        ideal = ma5 if (ma5 and ma5 > ma20 * 0.98) else ma20
        return {
            "timing": "wait_pullback",
            "reason": f"綠燈但短線過熱（{'、'.join(reasons)}），建議等拉回",
            "ideal_entry": round(ideal, 2) if ideal else None,
        }

    return {
        "timing": "now",
        "reason": "綠燈且技術面未過熱，可進場",
        "ideal_entry": None,
    }


def suggest_regime_strategy(fear_greed_index, macro_score, sp500_above_ma50=True):
    """
    [R6] 動態策略切換 — 根據 macro regime 建議偏好策略

    多頭環境 → 偏動量/短線（抓趨勢）
    空頭環境 → 偏防禦/存股（等低接）
    盤整環境 → 均衡

    參數：
      fear_greed_index: 0-100，恐慌/貪婪指數
      macro_score: 1-10，總體環境分數
      sp500_above_ma50: S&P500 是否在 50 日均線之上

    回傳 dict：
      suggested_strategy: 策略名稱
      regime: "bull" / "bear" / "neutral"
      reason: 原因
    """
    if fear_greed_index >= 60 and macro_score >= 6 and sp500_above_ma50:
        return {
            "suggested_strategy": "short",
            "regime": "bull",
            "reason": f"多頭環境（貪婪 {fear_greed_index}, 環境分 {macro_score}），適合動量操作",
        }
    elif fear_greed_index <= 30 or macro_score <= 4:
        return {
            "suggested_strategy": "dividend",
            "regime": "bear",
            "reason": f"空頭環境（恐慌 {fear_greed_index}, 環境分 {macro_score}），適合防禦/存股",
        }
    else:
        return {
            "suggested_strategy": "balanced",
            "regime": "neutral",
            "reason": f"盤整環境（指數 {fear_greed_index}, 環境分 {macro_score}），均衡操作",
        }


def _calc_interaction_bonus(tech_score, fund_score, inst_score, news_score):
    """
    [R6] 因子交互加分 — 多維度共振時額外加分

    邏輯：多個獨立維度同時看多（或看空），
    代表市場對該股的共識更強，信號可靠度大幅提升。

    門檻：≥6.5 算多頭訊號（比 consensus 的 6.0 更嚴格）
    """
    scores = [tech_score, fund_score, inst_score, news_score]
    bull_count = sum(1 for s in scores if s is not None and s >= 6.5)
    bear_count = sum(1 for s in scores if s is not None and s < 3.5)

    bonus = 0.0
    detail = ""

    # 多頭共振
    if bull_count >= 4:
        bonus = 0.8
        detail = "四面開花共振 +0.8"
    elif bull_count >= 3:
        bonus = 0.4
        detail = "三面共振 +0.4"

    # 空頭共振（反向懲罰）
    if bear_count >= 4:
        bonus = -0.8
        detail = "四面看空 -0.8"
    elif bear_count >= 3:
        bonus = min(bonus, -0.4)
        detail = "三面看空 -0.4"

    return bonus, detail


def _get_sector_bonus(sector_rs_label):
    """
    [R6] 產業輪動 bonus

    sector_rs_label: 來自 sector_rotation 的 rs_label
    "領先大盤" / "同步大盤" / "落後大盤"
    """
    if sector_rs_label == "領先大盤":
        return 0.3
    elif sector_rs_label == "落後大盤":
        return -0.3
    return 0.0


def weighted_score(tech_score, fund_score, inst_score, news_score,
                   strategy="balanced", is_us=False, macro_multiplier=1.0,
                   news_age_days=0, sector_rs_label=None, rs_score=None):
    """
    根據策略計算加權綜合分數

    參數：
    - news_age_days: [R4] 新聞平均天數，用於衰減計算
    - sector_rs_label: [R6] 產業相對強弱（"領先大盤"/"同步大盤"/"落後大盤"）
    - rs_score: [R6] 個股相對強度百分位 (0-100)
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

    # === [R6] 因子交互加分 ===
    interaction_bonus, interaction_detail = _calc_interaction_bonus(
        tech_score, fund_score, inst_score, effective_news
    )
    score += interaction_bonus

    # === [R6] 產業輪動 bonus ===
    sector_bonus = 0.0
    if sector_rs_label:
        sector_bonus = _get_sector_bonus(sector_rs_label)
        score += sector_bonus

    # === [R6] 相對強度 bonus ===
    rs_bonus = 0.0
    if rs_score is not None:
        from ranking import get_rs_bonus
        rs_bonus = get_rs_bonus(rs_score)
        score += rs_bonus

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

    # 硬邊界：分數不超過 10，不低於 1
    score = max(1.0, min(10.0, score))

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

    # [R6] 附加新因子資訊
    r6_bonuses = []
    if interaction_bonus != 0:
        r6_bonuses.append(interaction_detail)
    if sector_bonus != 0:
        r6_bonuses.append(f"產業{'加分' if sector_bonus > 0 else '扣分'} {sector_bonus:+.1f}")
    if rs_bonus != 0:
        r6_bonuses.append(f"動量{'加分' if rs_bonus > 0 else '扣分'} {rs_bonus:+.2f}")
    if r6_bonuses:
        result_config["r6_bonuses"] = r6_bonuses

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
