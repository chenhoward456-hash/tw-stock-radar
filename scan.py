#!/usr/bin/env python3
"""
臺股機會雷達 — 批次掃描觀察清單，找出綠燈候選
用法：python3 scan.py

第四輪新增：
- 動態選股池篩選（流動性 + 市值門檻）
- 掃描歷史差異追蹤（自動 diff）
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


# =============================================================
# [R4] 動態選股池篩選
# =============================================================
def filter_universe(stock_id, min_avg_volume=200, min_days=60):
    """
    動態篩選：過濾掉流動性不足的標的

    min_avg_volume: 最低 20 日均量（張）
    min_days: 最少需要幾天資料

    回傳：(pass: bool, reason: str or None)
    """
    try:
        price_df = market.fetch_stock_price(stock_id)
        if price_df is None or price_df.empty or len(price_df) < min_days:
            return False, f"資料不足（{len(price_df) if price_df is not None and not price_df.empty else 0} 天）"

        if "Trading_Volume" in price_df.columns:
            vol = price_df["Trading_Volume"].astype(float)
            avg_vol_lots = vol.tail(20).mean() / 1000
            if avg_vol_lots < min_avg_volume:
                return False, f"均量過低（{avg_vol_lots:.0f} 張 < {min_avg_volume}）"

        return True, None
    except Exception:
        return False, "資料取得失敗"


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
    except Exception:
        return None


# =============================================================
# [R4] 掃描歷史差異追蹤
# =============================================================
def diff_with_previous(current_results, previous_record):
    """
    比較當前掃描結果與前一次記錄的差異

    回傳：{
        "upgrades": list,    # 升級的股票（分數上升 ≥1.5）
        "downgrades": list,  # 降級的股票（分數下降 ≥1.5）
        "new_greens": list,  # 新進入綠燈的
        "lost_greens": list, # 跌出綠燈的
        "biggest_changes": list,  # 變化最大的 Top 5
    }
    """
    if not previous_record or "results" not in previous_record:
        return None

    prev_map = {}
    for r in previous_record["results"]:
        prev_map[r["stock_id"]] = r

    curr_map = {}
    for r in current_results:
        curr_map[r["stock_id"]] = r

    upgrades = []
    downgrades = []
    new_greens = []
    lost_greens = []
    all_changes = []

    for sid, curr in curr_map.items():
        prev = prev_map.get(sid)
        if not prev:
            continue

        change = curr["avg"] - prev["avg"]
        all_changes.append({
            "stock_id": sid,
            "name": curr.get("name", sid),
            "prev_avg": prev["avg"],
            "curr_avg": curr["avg"],
            "change": round(change, 1),
            "prev_signal": prev.get("overall", ""),
            "curr_signal": curr.get("overall", ""),
        })

        if change >= 1.5:
            upgrades.append({
                "stock_id": sid,
                "name": curr.get("name", sid),
                "prev": prev["avg"],
                "curr": curr["avg"],
                "change": round(change, 1),
            })
        elif change <= -1.5:
            downgrades.append({
                "stock_id": sid,
                "name": curr.get("name", sid),
                "prev": prev["avg"],
                "curr": curr["avg"],
                "change": round(change, 1),
            })

        # 新進/跌出綠燈
        if curr["avg"] >= 7 and prev["avg"] < 7:
            new_greens.append({
                "stock_id": sid,
                "name": curr.get("name", sid),
                "prev": prev["avg"],
                "curr": curr["avg"],
            })
        elif curr["avg"] < 7 and prev["avg"] >= 7:
            lost_greens.append({
                "stock_id": sid,
                "name": curr.get("name", sid),
                "prev": prev["avg"],
                "curr": curr["avg"],
            })

    # 變化最大的 Top 5
    all_changes.sort(key=lambda x: abs(x["change"]), reverse=True)
    biggest = all_changes[:5]

    return {
        "upgrades": upgrades,
        "downgrades": downgrades,
        "new_greens": new_greens,
        "lost_greens": lost_greens,
        "biggest_changes": biggest,
        "prev_date": previous_record.get("date", "unknown"),
    }


def print_diff(diff_result):
    """印出差異報告"""
    if not diff_result:
        return

    print(f"\n 📊 與上次掃描（{diff_result['prev_date']}）比較：")
    print(" " + "─" * 50)

    if diff_result["new_greens"]:
        print(f"  🆕 新進綠燈：")
        for r in diff_result["new_greens"]:
            print(f"    🟢 {r['stock_id']} {r['name']}：{r['prev']} → {r['curr']}")

    if diff_result["lost_greens"]:
        print(f"  ⬇ 跌出綠燈：")
        for r in diff_result["lost_greens"]:
            print(f"    🔴 {r['stock_id']} {r['name']}：{r['prev']} → {r['curr']}")

    if diff_result["upgrades"]:
        print(f"  ⬆ 大幅升級（+1.5 以上）：")
        for r in diff_result["upgrades"]:
            print(f"    ↑ {r['stock_id']} {r['name']}：{r['prev']} → {r['curr']}（{r['change']:+.1f}）")

    if diff_result["downgrades"]:
        print(f"  ⬇ 大幅降級（-1.5 以上）：")
        for r in diff_result["downgrades"]:
            print(f"    ↓ {r['stock_id']} {r['name']}：{r['prev']} → {r['curr']}（{r['change']:+.1f}）")

    if diff_result["biggest_changes"]:
        print(f"\n  變化最大 Top 5：")
        for r in diff_result["biggest_changes"]:
            arrow = "↑" if r["change"] > 0 else "↓"
            print(f"    {arrow} {r['stock_id']} {r['name']}：{r['change']:+.1f}（{r['prev_avg']} → {r['curr_avg']}）")


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

    reds = [r for r in results if r["avg"] < 4]
    if reds:
        print()
        print(f" ⚠ 目前偏空（{len(reds)} 檔）：")
        for r in reds:
            print(f"  🔴 {r['stock_id']} {r['name']}（{r['avg']}/10）— {r['highlights']}")


def main():
    import tracker

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

    # [R4] 動態篩選（可選）
    filtered_out = []
    active_stocks = []
    for sid in all_stocks:
        # 對 WATCHLIST 中的標的做輕量篩選
        # ETF 和美股跳過流動性檢查
        if market.is_etf(sid) or market.is_us(sid):
            active_stocks.append(sid)
        else:
            passed, reason = filter_universe(sid, min_avg_volume=100)
            if passed:
                active_stocks.append(sid)
            else:
                filtered_out.append((sid, reason))

    if filtered_out:
        print(f" ⚠ 篩除 {len(filtered_out)} 檔流動性不足：")
        for sid, reason in filtered_out[:5]:
            print(f"   - {sid}：{reason}")
        if len(filtered_out) > 5:
            print(f"   ...（共 {len(filtered_out)} 檔）")
        print()

    names = market.fetch_stock_names(active_stocks)
    print(f" → 載入完成，開始掃描 {len(active_stocks)} 檔\n")

    results = []
    done_count = 0

    def _scan_with_info(stock_id):
        data = scan_one(stock_id)
        if data:
            data["stock_id"] = stock_id
            data["name"] = names.get(stock_id, stock_id)
            data["sector"] = stock_sectors.get(stock_id, "其他")
        return stock_id, data

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_scan_with_info, sid): sid for sid in active_stocks}
        for future in as_completed(futures):
            done_count += 1
            stock_id, data = future.result()
            name = names.get(stock_id, stock_id)
            if data:
                results.append(data)
                icon = SIGNAL_ICON[data["overall"]]
                print(f" [{done_count:>2}/{len(active_stocks)}] {stock_id} {name} {icon} {data['avg']}")
            else:
                print(f" [{done_count:>2}/{len(active_stocks)}] {stock_id} {name} ⚠ 失敗")

    if not results:
        print("\n ⚠ 沒有取得任何資料")
        return

    results.sort(key=lambda x: x["avg"], reverse=True)

    print()
    print("=" * 60)
    print(" 掃描結果 ".center(60))
    print("=" * 60)

    print_table(results)
    print_sector_summary(results)
    print_green_picks(results)

    # [R4] 與上次掃描做 diff
    prev_dates = tracker.list_records()
    if prev_dates:
        prev_record = tracker.load_record(prev_dates[0])
        diff = diff_with_previous(results, prev_record)
        if diff:
            print_diff(diff)

    # 儲存本次掃描
    tracker.save_scan(results)

    print()
    print("=" * 60)
    print(" ⚠ 以上僅供參考，不構成投資建議。")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
