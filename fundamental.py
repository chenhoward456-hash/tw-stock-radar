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

    # 取得產業基準
    industry_group = _get_industry_group(industry_category)
    pe_range = INDUSTRY_PE.get(industry_group) if industry_group else None

    if industry_group:
        details.append(f"— 產業：{industry_category}（{industry_group}類）")

    # ===== 本益比 =====
    if not per_df.empty and "PER" in per_df.columns:
        pdf = per_df.sort_values("date").reset_index(drop=True)
        per_vals = pd.to_numeric(pdf["PER"], errors="coerce")
        per_valid = per_vals[per_vals > 0]

        if not per_valid.empty:
            current_per = per_valid.iloc[-1]

            if pe_range:
                # 有產業基準 → 用產業標準評估
                low, mid, high = pe_range
                if current_per > high * 1.2:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，遠超{industry_group}類合理上限 {high}x（偏貴）")
                    score -= 2
                elif current_per > high:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，高於{industry_group}類合理範圍 {low}-{high}x（稍貴）")
                    score -= 1
                elif current_per < low:
                    details.append(f"✓ 本益比 {current_per:.1f}x，低於{industry_group}類常見範圍 {low}-{high}x（便宜）")
                    score += 2
                elif current_per < mid:
                    details.append(f"✓ 本益比 {current_per:.1f}x，在{industry_group}類合理偏低範圍（{low}-{high}x）")
                    score += 1
                else:
                    details.append(f"— 本益比 {current_per:.1f}x，在{industry_group}類合理範圍（{low}-{high}x）")
            else:
                # 無產業基準 → 跟自己的歷史比
                median_per = per_valid.median()
                ratio = current_per / median_per if median_per > 0 else 1
                if ratio > 1.5:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，遠高於一年中位數 {median_per:.1f}x（偏貴）")
                    score -= 2
                elif ratio > 1.2:
                    details.append(f"⚠ 本益比 {current_per:.1f}x，高於中位數 {median_per:.1f}x（稍貴）")
                    score -= 1
                elif ratio < 0.8:
                    details.append(f"✓ 本益比 {current_per:.1f}x，低於中位數 {median_per:.1f}x（便宜）")
                    score += 2
                elif ratio < 0.9:
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
