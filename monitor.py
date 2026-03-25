#!/usr/bin/env python3
"""
持倉監控 — 檢查持倉狀況，條件惡化就推 LINE 警告
用法：python3 monitor.py
也可以加到 GitHub Actions 每日自動跑
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import FINMIND_TOKEN
from holdings import HOLDINGS
from data_fetcher import (
    fetch_stock_name,
    fetch_stock_industry,
    fetch_stock_price,
    fetch_institutional,
    fetch_per_pbr,
    fetch_monthly_revenue,
)
import technical
import fundamental
import institutional
from notify import send_line

TOKEN = FINMIND_TOKEN or None


def check_holding(h):
    """檢查單一持倉，回傳警告列表"""
    sid = h["stock_id"]
    buy_price = h["buy_price"]
    shares = h["shares"]

    name = fetch_stock_name(sid, TOKEN)
    industry = fetch_stock_industry(sid, TOKEN)
    price_df = fetch_stock_price(sid, token=TOKEN)
    per_df = fetch_per_pbr(sid, token=TOKEN)
    inst_df = fetch_institutional(sid, token=TOKEN)
    rev_df = fetch_monthly_revenue(sid, token=TOKEN)

    tech = technical.analyze(price_df)
    fund = fundamental.analyze(per_df, rev_df, industry)
    inst = institutional.analyze(inst_df)

    avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)
    current_price = tech.get("current_price", 0)
    ma20 = tech.get("ma20", 0)

    # 損益計算
    if current_price > 0 and buy_price > 0:
        pnl_pct = (current_price / buy_price - 1) * 100
        pnl_amount = (current_price - buy_price) * shares
    else:
        pnl_pct = 0
        pnl_amount = 0

    warnings = []

    # 1. 綜合評分跌到紅燈
    if avg < 4:
        warnings.append(f"🔴 綜合評分只剩 {avg}/10，多項指標偏空")

    # 2. 跌破 20 日均線
    if current_price > 0 and ma20 > 0 and current_price < ma20:
        gap = (current_price / ma20 - 1) * 100
        warnings.append(f"⚠ 已跌破 20日均線（{ma20:.0f}元），目前在均線下方 {gap:.1f}%")

    # 3. 帳面虧損超過 10%
    if pnl_pct < -10:
        warnings.append(f"⚠ 帳面虧損 {pnl_pct:.1f}%（{pnl_amount:+,.0f} 元），考慮是否停損")

    # 4. 外資連續賣超
    for d in inst.get("details", []):
        if "外資" in d and "賣超" in d and "連續" in d:
            warnings.append(f"⚠ {d.strip()}")

    # 5. 技術面紅燈
    if tech["signal"] == "red":
        warnings.append(f"⚠ 技術面轉紅（{tech['score']}/10）")

    return {
        "stock_id": sid,
        "name": name,
        "current_price": current_price,
        "buy_price": buy_price,
        "shares": shares,
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_amount,
        "avg": avg,
        "warnings": warnings,
    }


def format_monitor_message(results):
    """格式化持倉監控報告"""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"📋 持倉監控報告 ({now})", ""]

    # 先列出有警告的
    alerts = [r for r in results if r["warnings"]]
    safe = [r for r in results if not r["warnings"]]

    if alerts:
        lines.append("🚨 需要注意：")
        for r in alerts:
            pnl = f"{r['pnl_pct']:+.1f}%"
            lines.append(f"\n  {r['stock_id']} {r['name']}（{r['avg']}/10）損益 {pnl}")
            for w in r["warnings"]:
                lines.append(f"    {w}")
        lines.append("")

    if safe:
        lines.append("✅ 狀況正常：")
        for r in safe:
            pnl = f"{r['pnl_pct']:+.1f}%"
            lines.append(f"  {r['stock_id']} {r['name']}（{r['avg']}/10）損益 {pnl}")

    # 總損益
    total_cost = sum(r["buy_price"] * r["shares"] for r in results)
    total_value = sum(r["current_price"] * r["shares"] for r in results if r["current_price"] > 0)
    total_pnl = total_value - total_cost
    total_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

    lines.append("")
    lines.append(f"💰 持倉總值：{total_value:,.0f} 元（損益 {total_pnl:+,.0f} 元 / {total_pct:+.1f}%）")
    lines.append("")
    lines.append("⚠ 僅供參考，不構成投資建議")

    return "\n".join(lines)


def main():
    if not HOLDINGS:
        print("\n⚠ 你還沒有設定持倉！")
        print("請到 holdings.py 加入你的持股。\n")
        return

    print(f"\n📋 持倉監控 — 檢查 {len(HOLDINGS)} 檔持股\n")

    results = []
    for i, h in enumerate(HOLDINGS):
        sid = h["stock_id"]
        print(f"  [{i+1}/{len(HOLDINGS)}] {sid}...", end="", flush=True)
        try:
            r = check_holding(h)
            results.append(r)
            status = f"🚨 {len(r['warnings'])} 項警告" if r["warnings"] else "✅ 正常"
            print(f" {status}")
        except Exception as e:
            print(f" ⚠ 失敗：{e}")
        time.sleep(0.3)

    if not results:
        print("\n⚠ 沒有取得任何結果")
        return

    message = format_monitor_message(results)
    print(f"\n{message}")

    # 有警告才推 LINE（不要每天都推正常的）
    alerts = [r for r in results if r["warnings"]]
    if alerts:
        print("\n🚨 有警告，推送 LINE...", end="", flush=True)
        if send_line(message):
            print(" ✅ 已發送")
        else:
            print(" ⚠ 發送失敗")
    else:
        print("\n✅ 全部正常，不推送通知。")

    print()


if __name__ == "__main__":
    main()
