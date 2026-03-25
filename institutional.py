"""
籌碼面分析模組
分析三大法人（外資、投信、自營商）買賣超
"""
import pandas as pd
import numpy as np


def analyze(inst_df):
    """
    籌碼面分析
    回傳：{"signal": "green/yellow/red", "score": float, "details": list}
    """
    result = {"signal": "yellow", "score": 5, "details": []}

    if inst_df.empty:
        result["details"].append("⚠ 無法取得法人買賣超資料")
        return result

    score = 5.0
    details = []

    df = inst_df.copy()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]

    # FinMind 回傳單位是「股」，臺股習慣看「張」（1張 = 1000股）
    df["net_lot"] = df["net"] / 1000

    # 三大法人分類
    # FinMind 欄位名稱可能有變動，用模糊比對
    categories = [
        ("Foreign", "外資"),
        ("Investment_Trust", "投信"),
        ("Dealer", "自營商"),
    ]

    for keyword, label in categories:
        cat_df = df[df["name"].str.contains(keyword, case=False, na=False)]
        if cat_df.empty:
            continue

        cat_df = cat_df.sort_values("date")

        # 同一天可能有多筆（例如自營商分自行買賣和避險），合併
        daily = cat_df.groupby("date")["net_lot"].sum().reset_index()

        # 近 5 日累計
        recent = daily.tail(5)
        net_5 = recent["net_lot"].sum()

        # 連續天數
        daily_vals = daily["net_lot"].values
        consecutive = 0
        if len(daily_vals) > 0:
            direction = 1 if daily_vals[-1] > 0 else -1
            for val in reversed(daily_vals):
                if (val > 0 and direction > 0) or (val < 0 and direction < 0):
                    consecutive += 1
                else:
                    break

        if net_5 > 0:
            details.append(f"✓ {label}近5日買超 {net_5:+,.0f} 張")
            weight = 1.5 if label == "外資" else (1.0 if label == "投信" else 0.5)
            score += weight
        elif net_5 < 0:
            details.append(f"✗ {label}近5日賣超 {net_5:+,.0f} 張")
            weight = 1.5 if label == "外資" else (1.0 if label == "投信" else 0.5)
            score -= weight
        else:
            details.append(f"— {label}近5日買賣持平")

        if consecutive >= 3:
            direction_str = "買超" if daily_vals[-1] > 0 else "賣超"
            details.append(f"  → 連續 {consecutive} 日{direction_str}")

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
