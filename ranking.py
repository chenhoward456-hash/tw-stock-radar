"""
相對強度排名模組（Relative Strength Ranking）

核心邏輯：
1. 計算每檔股票的 N 日漲幅
2. 在全掃描池中算百分位排名（0-100）
3. 只有「分數高 + RS 也高」的股票才是真正的精選

學術依據：Jegadeesh & Titman (1993) 動量因子，
過去 3-12 個月的相對強度是少數長期有效的 alpha 因子。
"""
import numpy as np
import market


def calc_returns(stock_id, periods=(20, 60)):
    """
    計算股票的多週期漲幅

    periods: tuple of int，計算幾日的漲幅
    回傳：dict  e.g. {"return_20d": 5.2, "return_60d": 12.3}
           失敗回傳 None
    """
    try:
        max_period = max(periods) + 10  # 多抓幾天避免邊界
        price_df = market.fetch_stock_price(stock_id, days=max_period)
        if price_df is None or price_df.empty:
            return None

        price_df = price_df.sort_values("date").reset_index(drop=True)
        closes = price_df["close"].astype(float).values

        if len(closes) < min(periods) + 1:
            return None

        result = {}
        current = closes[-1]
        for p in periods:
            if len(closes) > p:
                past = closes[-(p + 1)]
                ret = (current / past - 1) * 100
                result[f"return_{p}d"] = round(ret, 2)
            else:
                result[f"return_{p}d"] = None

        return result
    except Exception:
        return None


def rank_by_relative_strength(scan_results, periods=(20, 60)):
    """
    對掃描結果計算相對強度排名

    scan_results: list of dict，每個 dict 至少含 "stock_id"
    periods: 計算哪些週期的漲幅

    回傳：scan_results 原地更新，每個 dict 新增：
      - return_20d, return_60d: 各週期漲幅 (%)
      - rs_score: 綜合相對強度分數 (0-100)
      - rs_rank: 排名（1 = 最強）
      - rs_label: "強勢" / "中性" / "弱勢"

    設計原則：
    - 20d 漲幅權重 40%（近期動量）
    - 60d 漲幅權重 60%（中期趨勢，更穩定）
    - 百分位排名避免絕對值偏差（牛市全漲、熊市全跌都能區分）
    """
    # Step 1: 收集每檔股票的漲幅
    returns_data = {}
    for r in scan_results:
        sid = r.get("stock_id", r.get("代號", ""))
        if not sid:
            continue
        ret = calc_returns(sid, periods)
        if ret:
            returns_data[sid] = ret

    if len(returns_data) < 3:
        # 樣本太少，排名沒意義
        for r in scan_results:
            r["rs_score"] = 50
            r["rs_rank"] = 0
            r["rs_label"] = "樣本不足"
            for p in periods:
                r[f"return_{p}d"] = None
        return scan_results

    # Step 2: 計算各週期的百分位排名
    period_weights = {20: 0.4, 60: 0.6}

    # 收集各週期的有效漲幅
    period_values = {}
    for p in periods:
        key = f"return_{p}d"
        vals = []
        for sid, ret in returns_data.items():
            v = ret.get(key)
            if v is not None:
                vals.append((sid, v))
        period_values[p] = vals

    # 計算百分位
    percentiles = {}  # {stock_id: weighted_percentile}
    for p in periods:
        vals = period_values[p]
        if not vals:
            continue

        # 排序算百分位
        sorted_vals = sorted(vals, key=lambda x: x[1])
        n = len(sorted_vals)
        for rank_idx, (sid, _) in enumerate(sorted_vals):
            pct = rank_idx / max(n - 1, 1) * 100  # 0-100
            w = period_weights.get(p, 0.5)
            if sid not in percentiles:
                percentiles[sid] = 0
            percentiles[sid] += pct * w

    # Step 3: 寫回 scan_results
    # 先算排名
    ranked = sorted(percentiles.items(), key=lambda x: x[1], reverse=True)
    rank_map = {}
    for i, (sid, _) in enumerate(ranked):
        rank_map[sid] = i + 1

    for r in scan_results:
        sid = r.get("stock_id", r.get("代號", ""))
        ret = returns_data.get(sid, {})

        for p in periods:
            r[f"return_{p}d"] = ret.get(f"return_{p}d")

        rs = percentiles.get(sid, 50)
        r["rs_score"] = round(rs, 1)
        r["rs_rank"] = rank_map.get(sid, 0)

        if rs >= 80:
            r["rs_label"] = "強勢"
        elif rs >= 60:
            r["rs_label"] = "偏強"
        elif rs >= 40:
            r["rs_label"] = "中性"
        elif rs >= 20:
            r["rs_label"] = "偏弱"
        else:
            r["rs_label"] = "弱勢"

    return scan_results


def rs_filter(scan_results, min_rs=50):
    """
    篩選相對強度達標的股票

    用途：在綠燈候選中，只留 RS 也夠強的
    min_rs: 最低 RS 百分位（預設 50 = 前半段）
    """
    return [r for r in scan_results if r.get("rs_score", 0) >= min_rs]


def get_rs_bonus(rs_score):
    """
    根據 RS 分數給予評分 bonus（整合進 weighted_score 用）

    RS >= 80: +0.3（強勢股加分）
    RS >= 60: +0.15
    RS 40-60: 0（中性）
    RS < 40:  -0.15（弱勢股扣分）
    RS < 20:  -0.3（極弱勢扣分）

    設計思路：bonus 幅度故意壓小（±0.3），
    避免讓動量因子過度主導。RS 的主要功能是「篩選」而非「加分」。
    """
    if rs_score >= 80:
        return 0.3
    elif rs_score >= 60:
        return 0.15
    elif rs_score >= 40:
        return 0.0
    elif rs_score >= 20:
        return -0.15
    else:
        return -0.3
