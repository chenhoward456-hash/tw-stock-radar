"""
長線佈局評分模組
不看股價漲跌，只看：
  1. 營收成長趨勢（連續成長 vs 衰退）
  2. 估值便宜度（現在 PE 跟歷史比）
  3. 殖利率穩定度
  4. 價格位置（52 週高低點，跌越多越便宜 = 分數越高）

核心邏輯：股價下跌 + 基本面沒壞 = 分數升高（逢低佈局）
          股價上漲 + 估值偏貴 = 分數降低（追高風險）

第三輪優化：
5. PEG ratio（成長調整後的估值，避免高成長股被誤判為貴）
6. 殖利率可持續性（配發率趨勢檢查）
7. PE 百分位排名（用 3 年分位數，不只看中位數）
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
    revenue_score, yoy_growth = _score_revenue_trend(revenue_df, details)
    score += revenue_score

    # ===== 2. 估值便宜度（PE 跟自己歷史比 + PEG）=====
    valuation_score = _score_valuation(per_df, details, yoy_growth)
    score += valuation_score

    # ===== 3. 殖利率（含可持續性檢查）=====
    dividend_score = _score_dividend(per_df, revenue_df, details)
    score += dividend_score

    # ===== 4. 價格位置（跌越多 = 越便宜 = 分數越高）=====
    position_score = _score_price_position(price_df, details)
    score += position_score

    # ===== [R6] 資料完整度懲罰 =====
    # 如果營收、PE、價格資料不足，不該給高分
    data_sources = 0
    if not revenue_df.empty and "revenue" in revenue_df.columns and len(revenue_df) >= 4:
        data_sources += 1
    if not per_df.empty and "PER" in per_df.columns:
        data_sources += 1
    if not price_df.empty and "close" in price_df.columns and len(price_df) >= 60:
        data_sources += 1

    if data_sources < 2:
        score = min(score, 6.0)  # 資料不足不給綠燈
        details.append(f"⚠ 資料來源不足（{data_sources}/3），長線評分受限")

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
    """營收趨勢：連續成長加分，連續衰退扣分。回傳 (score_adj, yoy_growth)"""
    yoy_growth = None

    if revenue_df.empty or "revenue" not in revenue_df.columns:
        details.append("— 無營收資料")
        return 0, yoy_growth

    rdf = revenue_df.sort_values("date").reset_index(drop=True)
    rdf["revenue"] = pd.to_numeric(rdf["revenue"], errors="coerce")
    rdf = rdf[rdf["revenue"] > 0]

    if len(rdf) < 4:
        details.append("— 營收資料不足 4 期")
        return 0, yoy_growth

    adj = 0

    # YoY 年增率（最重要）
    if len(rdf) >= 13:
        latest = rdf.iloc[-1]["revenue"]
        yoy_base = rdf.iloc[-13]["revenue"]
        yoy = (latest / yoy_base - 1) * 100 if yoy_base > 0 else 0
        yoy_growth = yoy

        if yoy > 20:
            details.append(f"✓ 營收年增 {yoy:+.1f}%（強勁成長）")
            adj += 2.0
        elif yoy > 10:
            details.append(f"✓ 營收年增 {yoy:+.1f}%（穩定成長）")
            adj += 1.0
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

    # ===== 營收動能偵測（加速 / 見頂 / 衰退）=====
    if len(rdf) >= 9:
        g1 = rdf.iloc[-9:-6]["revenue"].mean()
        g2 = rdf.iloc[-6:-3]["revenue"].mean()
        g3 = rdf.tail(3)["revenue"].mean()

        if g1 > 0 and g2 > 0:
            growth_early = (g2 / g1 - 1) * 100
            growth_late = (g3 / g2 - 1) * 100

            recent_6 = rdf.tail(6)["revenue"]
            peak = recent_6.max()
            latest = rdf.iloc[-1]["revenue"]
            drop_from_peak = (latest / peak - 1) * 100 if peak > 0 else 0

            if growth_early > 20 and growth_late < -30:
                details.append(f"⚠ 營收動能見頂（早期 {growth_early:+.0f}% → 近期 {growth_late:+.0f}%，高峰已過）")
                adj -= 2
            elif growth_late > 20 and growth_early > 0:
                details.append(f"✓ 營收動能加速中（{growth_early:+.0f}% → {growth_late:+.0f}%）")
                adj += 1
            elif growth_late < -20:
                details.append(f"⚠ 營收動能減速（{growth_early:+.0f}% → {growth_late:+.0f}%）")
                adj -= 1

            if drop_from_peak < -50:
                details.append(f"⚠ 最新營收從近6月高峰回落 {drop_from_peak:.0f}%（交屋/出貨潮可能結束）")
                adj -= 1.5
            elif drop_from_peak < -30:
                details.append(f"⚠ 最新營收從近6月高峰回落 {drop_from_peak:.0f}%")
                adj -= 0.5

    return adj, yoy_growth


def _score_valuation(per_df, details, yoy_growth=None):
    """估值便宜度：PE 百分位 + PEG ratio（第三輪升級）"""
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

    # === PE 百分位排名（第三輪新增）===
    percentile = (per_valid < current_pe).sum() / len(per_valid) * 100

    if percentile < 20:
        details.append(f"✓ PE {current_pe:.1f}x 處於歷史 {percentile:.0f}% 分位（非常便宜）")
        adj += 2
    elif percentile < 35:
        details.append(f"✓ PE {current_pe:.1f}x 處於歷史 {percentile:.0f}% 分位（偏便宜）")
        adj += 1
    elif percentile > 85:
        details.append(f"⚠ PE {current_pe:.1f}x 處於歷史 {percentile:.0f}% 分位（非常貴）")
        adj -= 2
    elif percentile > 70:
        details.append(f"⚠ PE {current_pe:.1f}x 處於歷史 {percentile:.0f}% 分位（偏貴）")
        adj -= 1
    else:
        details.append(f"— PE {current_pe:.1f}x 處於歷史 {percentile:.0f}% 分位（中位數 {median_pe:.1f}x）")

    # === PEG Ratio（第三輪新增）===
    if yoy_growth is not None and yoy_growth > 0 and current_pe > 0:
        peg = current_pe / yoy_growth
        if peg < 0.5:
            details.append(f"✓ PEG {peg:.2f}（成長便宜，PE {current_pe:.0f}x / 成長 {yoy_growth:.0f}%）")
            adj += 1
        elif peg < 1.0:
            details.append(f"✓ PEG {peg:.2f}（合理偏低）")
            adj += 0.5
        elif peg > 2.0:
            details.append(f"⚠ PEG {peg:.2f}（成長不足以支撐估值）")
            adj -= 0.5
        else:
            details.append(f"— PEG {peg:.2f}（合理範圍）")
    elif yoy_growth is not None and yoy_growth <= 0 and current_pe > 20:
        details.append(f"⚠ 營收負成長但 PE 仍 {current_pe:.0f}x，估值偏貴")
        adj -= 0.5

    return adj


def _score_dividend(per_df, revenue_df, details):
    """殖利率 + 可持續性檢查（第三輪升級）"""
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

    # === 殖利率可持續性（第三輪新增）===
    # 如果殖利率很高但營收在衰退，配息可能不可持續
    if current_dy > 5 and not revenue_df.empty and "revenue" in revenue_df.columns:
        rdf = revenue_df.sort_values("date").reset_index(drop=True)
        rdf["revenue"] = pd.to_numeric(rdf["revenue"], errors="coerce")
        rdf = rdf[rdf["revenue"] > 0]

        if len(rdf) >= 6:
            recent = rdf.tail(3)["revenue"].mean()
            prev = rdf.iloc[-6:-3]["revenue"].mean()
            if prev > 0:
                rev_trend = (recent / prev - 1) * 100
                if rev_trend < -15:
                    details.append(f"⚠ 殖利率可持續性存疑：營收趨勢 {rev_trend:+.1f}%，高配息可能難以維持")
                    adj -= 1
                elif rev_trend < -5:
                    details.append(f"— 營收微降 {rev_trend:+.1f}%，留意配息能力")

    # 殖利率穩定度（多期有 > 0 的比例）
    if len(dy_valid) >= 3:
        stability = len(dy_valid) / len(dy_vals.dropna()) * 100 if len(dy_vals.dropna()) > 0 else 0
        if stability < 50:
            details.append("⚠ 配息不穩定（歷史配息率偏低），存股需謹慎")
            adj -= 0.5

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
        adj += 1.5
    elif position < 35:
        details.append(f"✓ 股價偏低（52 週位置 {position:.0f}%），可能是佈局機會")
        adj += 0.5
    elif position > 90:
        details.append(f"⚠ 接近 52 週高點（位置 {position:.0f}%），長線追高風險大")
        adj -= 1.5
    elif position > 75:
        details.append(f"— 股價偏高（52 週位置 {position:.0f}%），不算便宜")
        adj -= 0.5
    else:
        details.append(f"— 52 週位置 {position:.0f}%（中間區域）")

    # 均值回歸強度（第三輪新增）：從低點回升且 20MA 上穿 = 底部確認
    if position < 35 and len(closes) >= 25:
        ma20 = closes.rolling(20).mean()
        if current > ma20.iloc[-1] and closes.iloc[-5] < ma20.iloc[-5]:
            details.append("✓ 股價從低點回升並突破 20MA（底部確認訊號）")
            adj += 0.5

    if drawdown < -30:
        details.append(f"  從高點回落 {drawdown:.0f}%，如果基本面沒壞，可能是撿便宜的機會")

    return adj
