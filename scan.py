#!/usr/bin/env python3
"""
臺股機會雷達 — 批次掃描觀察清單，找出綠燈候選
用法：python3 scan.py
"""
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from watchlist import WATCHLIST
import market
import technical
import fundamental
import institutional


SIGNAL_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def scan_one(stock_id):
    """掃描單一股票，回傳各面向分數"""
    try:
        price_df = market.fetch_stock_price(stock_id)
        per_df = market.fetch_per_pbr(stock_id)
        inst_df = market.fetch_institutional(stock_id)
        rev_df = market.fetch_monthly_revenue(stock_id)
        industry = market.fetch_stock_industry(stock_id)

        tech = technical.analyze(price_df)
        if market.is_etf(stock_id):
            etf_info = market.fetch_etf_info(stock_id)
            fund = fundamental.analyze_etf(price_df, etf_info, per_df)
        else:
            fund = fundamental.analyze(per_df, rev_df, industry)
        inst = institutional.analyze(inst_df)

        avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)

        # 產生一句話摘要
        highlights = []
        if tech["signal"] == "green":
            highlights.append("技術面強")
        if tech["signal"] == "red":
            highlights.append("技術面弱")
        if fund["signal"] == "green":
            highlights.append("基本面佳")
        if fund["signal"] == "red":
            highlights.append("基本面差")
        if inst["signal"] == "green":
            highlights.append("法人買超")
        if inst["signal"] == "red":
            highlights.append("法人賣超")

        if avg >= 7:
            overall = "green"
        elif avg >= 4:
            overall = "yellow"
        else:
            overall = "red"

        return {
            "tech": tech["score"],
            "fund": fund["score"],
            "inst": inst["score"],
            "avg": avg,
            "overall": overall,
            "highlights": "、".join(highlights) if highlights else "條件中性",
        }
    except Exception as e:
        return None


def print_table(results):
    """印出排名表格"""
    print()
    print(f" {'排名':>2}  {'代號':<6} {'名稱':<6} {'板塊':<8} {'技術':>4} {'基本':>4} {'籌碼':>4} {'綜合':>4}  訊號")
    print(" " + "─" * 72)

    for i, r in enumerate(results, 1):
        icon = SIGNAL_ICON[r["overall"]]
        print(
            f" {i:>2}.  {r['stock_id']:<6} {r['name']:<6} {r['sector']:<8}"
            f" {r['tech']:>4} {r['fund']:>4} {r['inst']:>4} {r['avg']:>4}  {icon}"
        )


def print_sector_summary(results):
    """印出板塊強弱分析"""
    sectors = {}
    for r in results:
        s = r["sector"]
        if s not in sectors:
            sectors[s] = []
        sectors[s].append(r["avg"])

    sector_avg = []
    for s, scores in sectors.items():
        avg = round(sum(scores) / len(scores), 1)
        sector_avg.append((s, avg, len(scores)))

    sector_avg.sort(key=lambda x: x[1], reverse=True)

    print()
    print(" 板塊強弱排名：")
    print(" " + "─" * 40)
    for s, avg, count in sector_avg:
        bar_len = int(avg)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        icon = "🟢" if avg >= 7 else ("🟡" if avg >= 4 else "🔴")
        print(f"  {icon} {s:<10} {bar} {avg}/10  ({count}檔)")


def print_green_picks(results):
    """印出綠燈候選人和值得關注"""
    greens = [r for r in results if r["avg"] >= 7]
    watchlist = [r for r in results if 6 <= r["avg"] < 7]

    print()
    if greens:
        print(f" 🟢 綠燈候選（{len(greens)} 檔）：")
        for r in greens:
            print(f"  🟢 {r['stock_id']} {r['name']}（{r['avg']}/10）— {r['highlights']}")
    else:
        print(" 💡 目前沒有綠燈候選人（需 7 分以上），建議耐心等待。")

    if watchlist:
        print()
        print(f" 🟡 值得關注（{len(watchlist)} 檔）：")
        for r in watchlist:
            print(f"  🟡 {r['stock_id']} {r['name']}（{r['avg']}/10）— {r['highlights']}")

    if greens or watchlist:
        print()
        print(" → 用 python3 check.py <代號> 看完整報告")

    # 也提示風險最高的
    reds = [r for r in results if r["avg"] < 4]
    if reds:
        print()
        print(f" ⚠ 目前偏空（{len(reds)} 檔）：")
        for r in reds:
            print(f"  🔴 {r['stock_id']} {r['name']}（{r['avg']}/10）— {r['highlights']}")


def main():
    # 收集所有股票代號
    all_stocks = []
    stock_sectors = {}
    for sector, codes in WATCHLIST.items():
        for code in codes:
            all_stocks.append(code)
            stock_sectors[code] = sector

    total = len(all_stocks)
    print()
    print("=" * 60)
    print(" 臺股機會雷達 ".center(60))
    print("=" * 60)
    print(f"\n 掃描 {total} 檔股票，預計需要 2-3 分鐘...\n")

    # 一次查詢所有名稱（只呼叫一次 API）
    print(" 載入股票資訊...")
    names = market.fetch_stock_names(all_stocks)
    print(f" → 完成\n")

    # 多線程並行掃描（5 條線程同時跑）
    results = []
    done_count = 0

    def _scan_with_info(stock_id):
        data = scan_one(stock_id)
        if data:
            data["stock_id"] = stock_id
            data["name"] = names.get(stock_id, stock_id)
            data["sector"] = stock_sectors[stock_id]
        return stock_id, data

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_scan_with_info, sid): sid for sid in all_stocks}
        for future in as_completed(futures):
            done_count += 1
            stock_id, data = future.result()
            name = names.get(stock_id, stock_id)
            if data:
                results.append(data)
                icon = SIGNAL_ICON[data["overall"]]
                print(f" [{done_count:>2}/{total}] {stock_id} {name} {icon} {data['avg']}")
            else:
                print(f" [{done_count:>2}/{total}] {stock_id} {name} ⚠ 失敗")

    if not results:
        print("\n ⚠ 沒有取得任何資料，請檢查網路或 FinMind Token 設定")
        return

    # 排序：綜合分數由高到低
    results.sort(key=lambda x: x["avg"], reverse=True)

    # 印出結果
    print()
    print("=" * 60)
    print(" 掃描結果 ".center(60))
    print("=" * 60)

    print_table(results)
    print_sector_summary(results)
    print_green_picks(results)

    print()
    print("=" * 60)
    print(" ⚠ 以上僅供參考，不構成投資建議。")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
