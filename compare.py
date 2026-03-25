#!/usr/bin/env python3
"""
股票 PK — 比較兩檔股票的多維度評分
用法：python3 compare.py 2330 2454
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import market
import technical
import fundamental
import institutional


SIGNAL_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def analyze_stock(stock_id):
    """完整分析一檔股票"""
    price_df = market.fetch_stock_price(stock_id)
    per_df = market.fetch_per_pbr(stock_id)
    inst_df = market.fetch_institutional(stock_id)
    rev_df = market.fetch_monthly_revenue(stock_id)

    tech = technical.analyze(price_df)
    fund = fundamental.analyze(per_df, rev_df)
    inst = institutional.analyze(inst_df)

    avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)

    return {
        "tech": tech,
        "fund": fund,
        "inst": inst,
        "avg": avg,
    }


def main():
    if len(sys.argv) < 3:
        print("股票 PK — 比較兩檔股票")
        print("=" * 30)
        print("用法：python3 compare.py <代號A> <代號B>")
        print("範例：python3 compare.py 2330 2454")
        sys.exit(1)

    id_a, id_b = sys.argv[1], sys.argv[2]

    print(f"\n⚔ 股票 PK：{id_a} vs {id_b}\n")

    print(f"分析 {id_a}...")
    name_a = market.fetch_stock_name(id_a)
    data_a = analyze_stock(id_a)

    print(f"分析 {id_b}...")
    name_b = market.fetch_stock_name(id_b)
    data_b = analyze_stock(id_b)

    # 表頭
    label_a = f"{id_a} {name_a}"
    label_b = f"{id_b} {name_b}"

    w = 55
    print()
    print("=" * w)
    print(f" {label_a}  vs  {label_b} ".center(w))
    print("=" * w)
    print()

    header = f" {'面向':<8} {label_a:>14} {label_b:>14}  比較"
    print(header)
    print(" " + "─" * (w - 2))

    rows = [
        ("技術面", data_a["tech"], data_b["tech"]),
        ("基本面", data_a["fund"], data_b["fund"]),
        ("籌碼面", data_a["inst"], data_b["inst"]),
    ]

    wins_a, wins_b = 0, 0

    for label, da, db in rows:
        sa, sb = da["score"], db["score"]
        ia, ib = SIGNAL_ICON[da["signal"]], SIGNAL_ICON[db["signal"]]

        if sa > sb + 0.5:
            arrow = f"← {label_a.split()[1]}較優"
            wins_a += 1
        elif sb > sa + 0.5:
            arrow = f"→ {label_b.split()[1]}較優"
            wins_b += 1
        else:
            arrow = "  相近"

        print(f" {label:<8} {ia} {sa:>5}       {ib} {sb:>5}  {arrow}")

    print(" " + "─" * (w - 2))

    avg_a, avg_b = data_a["avg"], data_b["avg"]
    oa = "🟢" if avg_a >= 7 else ("🟡" if avg_a >= 4 else "🔴")
    ob = "🟢" if avg_b >= 7 else ("🟡" if avg_b >= 4 else "🔴")

    print(f" {'綜合':<8} {oa} {avg_a:>5}       {ob} {avg_b:>5}")

    # 結論
    print()
    if avg_a > avg_b + 1:
        print(f" 📊 結論：{label_a} 目前各面向條件明顯較優（{wins_a}:{wins_b}）")
    elif avg_b > avg_a + 1:
        print(f" 📊 結論：{label_b} 目前各面向條件明顯較優（{wins_b}:{wins_a}）")
    elif abs(avg_a - avg_b) <= 1:
        print(f" 📊 結論：兩檔條件相近，可依個人偏好或產業前景做決定")
    else:
        better = label_a if avg_a > avg_b else label_b
        print(f" 📊 結論：{better} 稍微佔優，但差距不大")

    print()
    print("=" * w)
    print(" ⚠ 以上僅供參考，不構成投資建議。")
    print("=" * w)
    print()


if __name__ == "__main__":
    main()
