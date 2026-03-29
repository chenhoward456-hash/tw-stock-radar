"""
基本面分析模組
分產業評估本益比、殖利率、月營收趨勢
"""
import pandas as pd
import numpy as np

# 各產業合理本益比範圍 (偏低, 中位數, 偏高)
INDUSTRY_PE = {
    "半導體":     (15, 22, 30),
    "電子":       (10, 15, 22),
    "金融":       (8, 11, 15),
    "傳產":       (8, 12, 18),
    "食品":       (15, 20, 28),
    "電信":       (15, 20, 25),
    "航運":       (5, 8, 15),
    "生技":       (25, 40, 60),
    "營建":       (6, 10, 15),
}

# 美股 Sector PE 基準（yfinance 回傳的英文 sector 名稱）
US_SECTOR_PE = {
    "Technology":           (20, 28, 38),
    "Consumer Cyclical":    (15, 22, 30),
    "Communication Services": (15, 20, 28),
    "Healthcare":           (18, 25, 40),
    "Financial Services":   (8, 13, 18),
    "Industrials":          (12, 18, 25),
    "Consumer Defensive":   (15, 20, 28),
    "Energy":               (8, 12, 20),
    "Utilities":            (12, 17, 22),
    "Real Estate":          (20, 30, 45),
    "Basic Materials":      (8, 14, 20),
}

# FinMind 產業名稱 → 大分類
_INDUSTRY_MAP = {
    "半導體": "半導體",
    "電子零組件": "電子",
    "電腦及週邊設備": "電子",
    "光電": "電子",
    "通信網路": "電子",
    "電子通路": "電子",
    "資訊服務": "電子",
    "其他電子": "電子",
    "金融保險": "金融",
    "食品": "食品",
    "電信": "電信",
    "航運": "航運",
    "生技醫療": "生技",
    "塑膠": "傳產",
    "鋼鐵": "傳產",
    "紡織纖維": "傳產",
    "水泥": "傳產",
    "汽車": "傳產",
    "油電燃氣": "傳產",
    "化學": "傳產",
    "橡膠": "傳產",
    "造紙": "傳產",
    "貿易百貨": "傳產",
    "建材營造": "營建",
    "觀光餐旅": "傳產",
    "電機機械": "傳產",
}


def analyze_etf(price_df, etf_info=None, per_df=None):
    """
    ETF 專用基本面分析
    用殖利率 + 費用率 + 52週位置 + 折溢價取代本益比和月營收
    """
    result = {"signal": "yellow", "score": 5, "details": []}
    score = 5.0
    details = []
    details.append("— ETF 專用評估（不看本益比和月營收）")

    # ===== 殖利率 =====
    dy = 0
    if etf_info and etf_info.get("dividend_yield"):
        dy = etf_info["dividend_yield"]
    elif per_df is not None and not per_df.empty and "dividend_yield" in per_df.columns:
        dy_vals = pd.to_numeric(per_df["dividend_yield"], errors="coerce")
        dy_valid = dy_vals[dy_vals > 0]
        if not dy_valid.empty:
            dy = float(dy_valid.iloc[-1])

    # [R6] 異常值保護：殖利率超過 15% 極罕見，cap 住並標記
    if dy > 15:
        details.append(f"⚠ 殖利率 {dy:.1f}% 異常偏高（可能因分割），以 15% 計算")
        dy = 15.0

    if dy > 0:
        if dy > 6:
            details.append(f"✓ 殖利率 {dy:.1f}%（高配息）")
            score += 2
        elif dy > 4:
            details.append(f"✓ 殖利率 {dy:.1f}%（不錯）")
            score += 1
        elif dy > 2:
            details.append(f"— 殖利率 {dy:.1f}%（一般）")
        else:
            details.append(f"— 殖利率 {dy:.1f}%（偏低，可能是成長型 ETF）")
    else:
        details.append("— 無殖利率資料（成長型 ETF 或資料缺失）")

    # ===== 費用率（美股 ETF 才有）=====
    if etf_info and etf_info.get("expense_ratio"):
        er = etf_info["expense_ratio"]
        if er < 0.1:
            details.append(f"✓ 內扣費用 {er:.2f}%（極低）")
            score += 1
        elif er < 0.3:
            details.append(f"✓ 內扣費用 {er:.2f}%（合理）")
            score += 0.5
        elif er < 0.75:
            details.append(f"— 內扣費用 {er:.2f}%（中等）")
        else:
            details.append(f"⚠ 內扣費用 {er:.2f}%（偏高）")
            score -= 1

    # ===== 52 週價格位置 =====
    if not price_df.empty and "close" in price_df.columns:
        closes = pd.to_numeric(price_df["close"], errors="coerce").dropna()
        if len(closes) >= 20:
            current = closes.iloc[-1]
            high_52 = closes.max()
            low_52 = closes.min()
            if high_52 > low_52:
                position = (current - low_52) / (high_52 - low_52) * 100
                if position < 25:
                    details.append(f"✓ 在 52 週低點附近（位置 {position:.0f}%），可能是好買點")
                    score += 1.5
                elif position < 40:
                    details.append(f"✓ 在 52 週偏低區（位置 {position:.0f}%）")
                    score += 0.5
                elif position > 90:
                    details.append(f"⚠ 接近 52 週高點（位置 {position:.0f}%），追高風險")
                    score -= 1.5
                elif position > 75:
                    details.append(f"— 在 52 週偏高區（位置 {position:.0f}%）")
                    score -= 0.5
                else:
                    details.append(f"— 52 週價格位置 {position:.0f}%（中間區域）")

    # ===== [R6] ETF 趨勢健康度 =====
    if not price_df.empty and "close" in price_df.columns:
        closes = pd.to_numeric(price_df["close"], errors="coerce").dropna()

        # 近期報酬
        if len(closes) >= 21:
            ret_20d = (closes.iloc[-1] / closes.iloc[-21] - 1) * 100
            details.append(f"— 近 20 日報酬：{ret_20d:+.1f}%")
            if ret_20d < -10:
                details.append(f"⚠ 短期跌幅較大，若長期趨勢仍在可視為加碼機會")
                score += 0.5  # 逆向：ETF 跌多可以加碼
            elif ret_20d > 10:
                details.append(f"⚠ 短期漲幅較大，追高注意")
                score -= 0.5

        if len(closes) >= 61:
            ret_60d = (closes.iloc[-1] / closes.iloc[-61] - 1) * 100
            details.append(f"— 近 60 日報酬：{ret_60d:+.1f}%")

        # 均線相對位置（判斷長期趨勢）
        if len(closes) >= 60:
            ma20 = closes.rolling(20).mean().iloc[-1]
            ma60 = closes.rolling(60).mean().iloc[-1]
            current = closes.iloc[-1]

            if current > ma20 > ma60:
                details.append(f"✓ 價格在均線之上，長期趨勢健康")
                score += 1
            elif current > ma60 and current <= ma20:
                details.append(f"— 拉回到 20 日均線，長期趨勢仍在")
                score += 0.5
            elif current < ma60:
                details.append(f"⚠ 跌破 60 日均線，長期趨勢轉弱")
                score -= 1.5

        # 波動度
        if len(closes) >= 20:
            daily_ret = closes.pct_change().tail(20)
            vol = daily_ret.std() * (252 ** 0.5) * 100  # 年化波動率
            if vol > 25:
                details.append(f"⚠ 波動率偏高（年化 {vol:.0f}%），短期震盪大")
            elif vol < 10:
                details.append(f"✓ 波動率低（年化 {vol:.0f}%），走勢穩定")
            else:
                details.append(f"— 波動率正常（年化 {vol:.0f}%）")

    # ===== 折溢價（如果有 NAV）=====
    if etf_info and etf_info.get("nav_price") and etf_info.get("current_price"):
        nav = etf_info["nav_price"]
        price = etf_info["current_price"]
        if nav > 0:
            premium = (price / nav - 1) * 100
            if premium > 2:
                details.append(f"⚠ 溢價 {premium:.1f}%（買貴了）")
                score -= 1
            elif premium < -2:
                details.append(f"✓ 折價 {abs(premium):.1f}%（相對便宜）")
                score += 1
            else:
                details.append(f"— 折溢價 {premium:+.1f}%（接近淨值）")

    # ===== 規模（美股 ETF 才有）=====
    if etf_info and etf_info.get("total_assets"):
        assets = etf_info["total_assets"]
        if assets > 10e9:
            details.append(f"✓ 基金規模 {assets / 1e9:.0f}B USD（大型，流動性佳）")
        elif assets > 1e9:
            details.append(f"— 基金規模 {assets / 1e9:.1f}B USD（中型）")
        elif assets > 100e6:
            details.append(f"— 基金規模 {assets / 1e6:.0f}M USD（小型）")
        else:
            details.append(f"⚠ 基金規模偏小（{assets / 1e6:.0f}M USD），流動性風險")
            score -= 1

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


def _get_industry_group(industry_category):
    """把 FinMind 的產業細分對應到大類"""
    if not industry_category:
        return None
    for keyword, group in _INDUSTRY_MAP.items():
        if keyword in industry_category:
            return group
    return None


def analyze(per_df, revenue_df, industry_category=""):
    """
    基本面分析
    回傳：{"signal": "green/yellow/red", "score": float, "details": list}
    """
    result = {"signal": "yellow", "score": 5, "details": []}
    score = 5.0
    details = []

    # 取得產業基準（台股用中文對照，美股直接查英文 sector）
    industry_group = _get_industry_group(industry_category)
    pe_range = INDUSTRY_PE.get(industry_group) if industry_group else None

    # 美股：如果台股對照表找不到，用英文 sector 查
    if not pe_range and industry_category:
        pe_range = US_SECTOR_PE.get(industry_category)
        if pe_range:
            industry_group = industry_category  # 直接用英文 sector 名

    if industry_group:
        details.append(f"— 產業：{industry_category}（{industry_group}類）")

    # ===== 本益比（改進：產業基準 + 歷史中位數雙重比較）=====
    if not per_df.empty and "PER" in per_df.columns:
        pdf = per_df.sort_values("date").reset_index(drop=True)
        per_vals = pd.to_numeric(pdf["PER"], errors="coerce")
        per_valid = per_vals[per_vals > 0]

        if not per_valid.empty:
            current_per = per_valid.iloc[-1]
            # 動態基準：用自身歷史中位數作為主要參考
            median_per = per_valid.median()
            hist_ratio = current_per / median_per if median_per > 0 else 1

            if pe_range:
                # 有產業基準 → 產業 + 歷史雙重比較
                low, mid, high = pe_range

                # 主要看歷史相對位置（更貼近個股實際估值區間）
                if hist_ratio > 1.5:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，遠高於自身中位數 {median_per:.1f}x（偏貴）")
                    score -= 2
                elif hist_ratio > 1.2:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，高於自身中位數 {median_per:.1f}x（稍貴）")
                    score -= 1
                elif hist_ratio < 0.7:
                    details.append(f"✓ 本益比 {current_per:.1f}x，遠低於自身中位數 {median_per:.1f}x（很便宜）")
                    score += 2
                elif hist_ratio < 0.85:
                    details.append(f"✓ 本益比 {current_per:.1f}x，低於自身中位數 {median_per:.1f}x（偏便宜）")
                    score += 1
                else:
                    details.append(f"— 本益比 {current_per:.1f}x，接近自身中位數 {median_per:.1f}x（合理）")

                # 額外參考產業範圍（輔助判斷）
                if current_per > high * 1.3:
                    details.append(f"  ⚠ 也遠超{industry_group}類合理上限 {high}x")
                    score -= 0.5
                elif current_per < low * 0.8:
                    details.append(f"  ✓ 也低於{industry_group}類下限 {low}x")
                    score += 0.5
                else:
                    details.append(f"  — 產業參考範圍：{low}-{high}x")
            else:
                # 無產業基準 → 純粹跟自己的歷史比
                if hist_ratio > 1.5:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，遠高於一年中位數 {median_per:.1f}x（偏貴）")
                    score -= 2
                elif hist_ratio > 1.2:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，高於中位數 {median_per:.1f}x（稍貴）")
                    score -= 1
                elif hist_ratio < 0.7:
                    details.append(f"✓ 本益比 {current_per:.1f}x，低於中位數 {median_per:.1f}x（便宜）")
                    score += 2
                elif hist_ratio < 0.85:
                    details.append(f"✓ 本益比 {current_per:.1f}x，略低於中位數 {median_per:.1f}x")
                    score += 1
                else:
                    details.append(f"— 本益比 {current_per:.1f}x，接近中位數 {median_per:.1f}x（合理）")
        else:
            details.append("⚠ 本益比為負或無資料（可能虧損中）")
            score -= 2

        # 殖利率
        if "dividend_yield" in pdf.columns:
            dy = pd.to_numeric(pdf["dividend_yield"], errors="coerce")
            dy_valid = dy[dy > 0]
            if not dy_valid.empty:
                current_dy = dy_valid.iloc[-1]
                if current_dy > 5:
                    details.append(f"✓ 殖利率 {current_dy:.1f}%（高）")
                    score += 1
                elif current_dy > 3:
                    details.append(f"— 殖利率 {current_dy:.1f}%（尚可）")
                else:
                    details.append(f"— 殖利率 {current_dy:.1f}%（偏低）")

        # 本淨比
        if "PBR" in pdf.columns:
            pbr = pd.to_numeric(pdf["PBR"], errors="coerce")
            pbr_valid = pbr[pbr > 0]
            if not pbr_valid.empty:
                details.append(f"— 股價淨值比 {pbr_valid.iloc[-1]:.1f}x")
    else:
        details.append("⚠ 無法取得本益比資料")

    # ===== 月營收 =====
    if not revenue_df.empty and "revenue" in revenue_df.columns:
        rdf = revenue_df.sort_values("date").reset_index(drop=True)
        rdf["revenue"] = pd.to_numeric(rdf["revenue"], errors="coerce")
        rdf = rdf[rdf["revenue"] > 0]

        if len(rdf) >= 2:
            latest = rdf.iloc[-1]["revenue"]
            prev = rdf.iloc[-2]["revenue"]
            mom = (latest / prev - 1) * 100 if prev > 0 else 0
            details.append(f"— 最新月營收月增率：{mom:+.1f}%")

        if len(rdf) >= 13:
            latest = rdf.iloc[-1]["revenue"]
            yoy_base = rdf.iloc[-13]["revenue"]
            yoy = (latest / yoy_base - 1) * 100 if yoy_base > 0 else 0

            if yoy > 20:
                details.append(f"✓ 月營收年增率 {yoy:+.1f}%（強勁成長）")
                score += 2
            elif yoy > 5:
                details.append(f"✓ 月營收年增率 {yoy:+.1f}%（穩定成長）")
                score += 1
            elif yoy > -5:
                details.append(f"— 月營收年增率 {yoy:+.1f}%（持平）")
            elif yoy > -20:
                details.append(f"⚠ 月營收年增率 {yoy:+.1f}%（衰退）")
                score -= 1
            else:
                details.append(f"⚠ 月營收年增率 {yoy:+.1f}%（大幅衰退）")
                score -= 2

        if len(rdf) >= 6:
            recent_3 = rdf.tail(3)["revenue"].mean()
            prev_3 = rdf.iloc[-6:-3]["revenue"].mean()
            trend = (recent_3 / prev_3 - 1) * 100 if prev_3 > 0 else 0

            if trend > 10:
                details.append(f"✓ 營收趨勢向上（近3月vs前3月：{trend:+.1f}%）")
                score += 1
            elif trend < -10:
                details.append(f"⚠ 營收趨勢向下（近3月vs前3月：{trend:+.1f}%）")
                score -= 1

        # [R6] 營收加速度因子 — 連續 3 月 YoY 加速 = 轉機股
        if len(rdf) >= 15:
            # 計算最近 3 個月各自的 YoY
            yoy_list = []
            for i in range(3):
                idx = -(i + 1)
                base_idx = idx - 12
                if abs(base_idx) <= len(rdf):
                    curr_rev = rdf.iloc[idx]["revenue"]
                    base_rev = rdf.iloc[base_idx]["revenue"]
                    if base_rev > 0:
                        yoy_list.append((curr_rev / base_rev - 1) * 100)

            if len(yoy_list) == 3:
                # yoy_list[0] = 最近月, yoy_list[2] = 3個月前
                # 加速 = 每月 YoY 都比上月高
                accelerating = yoy_list[0] > yoy_list[1] > yoy_list[2]
                decelerating = yoy_list[0] < yoy_list[1] < yoy_list[2]
                accel_delta = yoy_list[0] - yoy_list[2]

                if accelerating and accel_delta > 5:
                    details.append(f"🚀 營收 YoY 連續加速（{yoy_list[2]:+.1f}% → {yoy_list[1]:+.1f}% → {yoy_list[0]:+.1f}%）")
                    score += 1.0
                elif accelerating:
                    details.append(f"✓ 營收 YoY 緩步加速（{yoy_list[2]:+.1f}% → {yoy_list[0]:+.1f}%）")
                    score += 0.5
                elif decelerating and accel_delta < -10:
                    details.append(f"⚠ 營收 YoY 連續減速（{yoy_list[2]:+.1f}% → {yoy_list[0]:+.1f}%）")
                    score -= 1.0
                elif decelerating:
                    details.append(f"— 營收 YoY 略為減速（{yoy_list[2]:+.1f}% → {yoy_list[0]:+.1f}%）")
                    score -= 0.5
    else:
        details.append("⚠ 無法取得營收資料")

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


def analyze_with_health(per_df, revenue_df, industry_category="", health_data=None):
    """
    [R4] 含財務健康指標的基本面分析（美股用）
    health_data: data_fetcher_us.fetch_financial_health() 回傳的 dict
    """
    result = analyze(per_df, revenue_df, industry_category)

    if health_data and isinstance(health_data, dict):
        adj = health_data.get("score_adj", 0)
        details_extra = health_data.get("details", [])

        if details_extra:
            result["details"].append("")
            result["details"].append("— 財務健康檢查：")
            result["details"].extend([f"  {d}" for d in details_extra])

        if adj != 0:
            result["score"] = round(max(1.0, min(10.0, result["score"] + adj)), 1)
            if result["score"] >= 7:
                result["signal"] = "green"
            elif result["score"] >= 4:
                result["signal"] = "yellow"
            else:
                result["signal"] = "red"

        result["health"] = health_data

    return result
