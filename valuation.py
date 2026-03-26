"""
長線佈局評分模組
不看股價漲跌，只看：
  1. 營收成長趨勢（連續成長 vs 衰退）
  2. 估值便宜度（現在 PE 跟歷史比）
  3. 殖利率穩定度
  4. 價格位置（52 週高低點，跌越多越便宜 = 分數越高）

核心邏輯：股價下跌 + 基本面沒壞 = 分數升高（逢低佈局）
          股價上漲 + 估值偏貴 = 分數降低（追高風險）
"""
import pandas as pd
import numpy as np


def analyze_longterm(per_df, revenue_df, price_df, industry_category=""):
    """
    長線佈局評分
    回傳：{"signal": "green/yellow/red", "score": float, "details": list}
    """
    result = {"signal": "yellow", "score": 5, "details": []}
    score = 5.0
    details = []
    details.append("— 長線佈局評估（不看短期漲跌）")

    # ===== 1. 營收成長趨勢（最重要）=====
    revenue_score = _score_revenue_trend(revenue_df, details)
    score += revenue_score

    # ===== 2. 估值便宜度（PE 跟自己歷史比）=====
    valuation_score = _score_valuation(per_df, details)
    score += valuation_score

    # ===== 3. 殖利率 =====
    dividend_score = _score_dividend(per_df, details)
    score += dividend_score

    # ===== 4. 價格位置（跌越多 = 越便宜 = 分數越高）=====
    position_score = _score_price_position(price_df, details)
    score += position_score

    # ===== 結算 =====
    score = max(1.0, min(10.0, score))
    if score >= 7:
        signal = "green"
    elif score >= 4:
        signal = "yellow"
    else:
        signal = "red"

    result["signal"] = signal
    result["score"] = round(score, 1)
    result["details"] = details
    return result


def _score_revenue_trend(revenue_df, details):
    """營收趨勢：連續成長加分，連續衰退扣分"""
    if revenue_df.empty or "revenue" not in revenue_df.columns:
        details.append("— 無營收資料")
        return 0

    rdf = revenue_df.sort_values("date").reset_index(drop=True)
    rdf["revenue"] = pd.to_numeric(rdf["revenue"], errors="coerce")
    rdf = rdf[rdf["revenue"] > 0]

    if len(rdf) < 4:
        details.append("— 營收資料不足 4 期")
        return 0

    adj = 0

    # YoY 年增率（最重要）
    if len(rdf) >= 13:
        latest = rdf.iloc[-1]["revenue"]
        yoy_base = rdf.iloc[-13]["revenue"]
        yoy = (latest / yoy_base - 1) * 100 if yoy_base > 0 else 0

        if yoy > 20:
            details.append(f"✓ 營收年增 {yoy:+.1f}%（強勁成長）")
            adj += 2.5
        elif yoy > 10:
            details.append(f"✓ 營收年增 {yoy:+.1f}%（穩定成長）")
            adj += 1.5
        elif yoy > 0:
            details.append(f"✓ 營收年增 {yoy:+.1f}%（微幅成長）")
            adj += 0.5
        elif yoy > -10:
            details.append(f"⚠ 營收年增 {yoy:+.1f}%（微幅衰退）")
            adj -= 0.5
        elif yoy > -20:
            details.append(f"⚠ 營收年增 {yoy:+.1f}%（明顯衰退）")
            adj -= 1.5
        else:
            details.append(f"⚠ 營收年增 {yoy:+.1f}%（大幅衰退）")
            adj -= 2.5

    # 連續成長趨勢
    if len(rdf) >= 6:
        recent_3 = rdf.tail(3)["revenue"].mean()
        prev_3 = rdf.iloc[-6:-3]["revenue"].mean()
        trend = (recent_3 / prev_3 - 1) * 100 if prev_3 > 0 else 0

        if trend > 10:
            details.append(f"✓ 營收趨勢持續向上（近3期 vs 前3期：{trend:+.1f}%）")
            adj += 1
        elif trend < -10:
            details.append(f"⚠ 營收趨勢持續向下（{trend:+.1f}%）")
            adj -= 1

    return adj


def _score_valuation(per_df, details):
    """估值便宜度：PE 低於歷史中位數 = 便宜 = 加分"""
    if per_df.empty or "PER" not in per_df.columns:
        details.append("— 無本益比資料")
        return 0

    pdf = per_df.sort_values("date").reset_index(drop=True)
    per_vals = pd.to_numeric(pdf["PER"], errors="coerce")
    per_valid = per_vals[per_vals > 0]

    if len(per_valid) < 2:
        details.append("— 本益比資料不足")
        return 0

    current_pe = per_valid.iloc[-1]
    median_pe = per_valid.median()
    adj = 0

    if median_pe > 0:
        ratio = current_pe / median_pe

        if ratio < 0.7:
            details.append(f"✓ PE {current_pe:.1f}x 遠低於歷史中位數 {median_pe:.1f}x（很便宜）")
            adj += 2
        elif ratio < 0.85:
            details.append(f"✓ PE {current_pe:.1f}x 低於歷史中位數 {median_pe:.1f}x（偏便宜）")
            adj += 1
        elif ratio > 1.5:
            details.append(f"⚠ PE {current_pe:.1f}x 遠高於歷史中位數 {median_pe:.1f}x（很貴）")
            adj -= 2
        elif ratio > 1.2:
            details.append(f"⚠ PE {current_pe:.1f}x 高於歷史中位數 {median_pe:.1f}x（偏貴）")
            adj -= 1
        else:
            details.append(f"— PE {current_pe:.1f}x 接近歷史中位數 {median_pe:.1f}x（合理）")

    return adj


def _score_dividend(per_df, details):
    """殖利率：高且穩定 = 加分"""
    if per_df.empty or "dividend_yield" not in per_df.columns:
        return 0

    dy_vals = pd.to_numeric(per_df["dividend_yield"], errors="coerce")
    dy_valid = dy_vals[dy_vals > 0]

    if dy_valid.empty:
        return 0

    current_dy = dy_valid.iloc[-1]
    adj = 0

    if current_dy > 6:
        details.append(f"✓ 殖利率 {current_dy:.1f}%（高配息）")
        adj += 1.5
    elif current_dy > 4:
        details.append(f"✓ 殖利率 {current_dy:.1f}%（不錯）")
        adj += 0.5
    elif current_dy > 2:
        details.append(f"— 殖利率 {current_dy:.1f}%")
    else:
        details.append(f"— 殖利率 {current_dy:.1f}%（偏低，可能是成長股）")

    return adj


def _score_price_position(price_df, details):
    """
    價格位置：跟短線邏輯相反！
    短線：在高點 = 強勢 = 加分
    長線：在低點 = 便宜 = 加分（逢低佈局）
    """
    if price_df.empty or "close" not in price_df.columns:
        return 0

    closes = pd.to_numeric(price_df["close"], errors="coerce").dropna()
    if len(closes) < 60:
        return 0

    current = closes.iloc[-1]
    high_52 = closes.max()
    low_52 = closes.min()

    if high_52 <= low_52:
        return 0

    # 0% = 52週最低，100% = 52週最高
    position = (current - low_52) / (high_52 - low_52) * 100
    drawdown = (current / high_52 - 1) * 100

    adj = 0

    if position < 20:
        details.append(f"✓ 股價在 52 週低點附近（位置 {position:.0f}%），長線有吸引力")
        adj += 2
    elif position < 35:
        details.append(f"✓ 股價偏低（52 週位置 {position:.0f}%），可能是佈局機會")
        adj += 1
    elif position > 90:
        details.append(f"⚠ 接近 52 週高點（位置 {position:.0f}%），長線追高風險大")
        adj -= 1.5
    elif position > 75:
        details.append(f"— 股價偏高（52 週位置 {position:.0f}%），不算便宜")
        adj -= 0.5
    else:
        details.append(f"— 52 週位置 {position:.0f}%（中間區域）")

    if drawdown < -30:
        details.append(f"  從高點回落 {drawdown:.0f}%，如果基本面沒壞，可能是撿便宜的機會")

    return adj
