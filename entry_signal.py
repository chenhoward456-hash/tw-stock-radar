#!/usr/bin/env python3
"""
0050 每月進場訊號儀表板

規則（依 MA200 拉伸度決定本月扣款）：
    >40%      → 投 5,000，存 15,000 到戰備金
    30%–40%   → 投 10,000，存 10,000
    15%–30%   → 投 15,000，存 5,000
    0%–15%    → 投 20,000（正常區）
    <0%       → 投 20,000 + 戰備金分 6 個月梭哈

戰備金狀態存在 entry_signal_state.json，跨月份持續累積。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yfinance as yf

STATE_FILE = Path(__file__).parent / "entry_signal_state.json"
MONTHLY_INFLOW = 20000


def fetch_0050():
    t = yf.Ticker("0050.TW")
    h = t.history(period="2y")
    if h.empty:
        sys.exit("抓不到 0050 資料")
    close = h["Close"]
    return {
        "price": float(close.iloc[-1]),
        "date": h.index[-1].strftime("%Y-%m-%d"),
        "ma20": float(close.tail(20).mean()),
        "ma60": float(close.tail(60).mean()),
        "ma200": float(close.tail(200).mean()),
        "high_52w": float(close.tail(252).max()),
    }


def decide_tier(stretch_pct):
    if stretch_pct > 40:
        return ("極熱", 5000, 15000, "🔥 山頂區，月扣降到 1/4")
    if stretch_pct > 30:
        return ("熱", 10000, 10000, "⚠️ 拉伸偏高，月扣減半")
    if stretch_pct > 15:
        return ("偏熱", 15000, 5000, "📈 仍偏多，月扣 3/4")
    if stretch_pct > 0:
        return ("正常", 20000, 0, "✅ 正常區間，滿額月扣")
    return ("折價/恐慌", 20000, 0, "🎯 跌破年線，戰備金啟動")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "reserve": 0,
        "fire_remaining_months": 0,
        "last_run_month": "",
        "shares_owned": 0.0,
        "history": [],
    }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def main(execute=False):
    info = fetch_0050()
    stretch = (info["price"] / info["ma200"] - 1) * 100
    discount = (info["price"] / info["high_52w"] - 1) * 100
    tier, invest_amt, save_amt, comment = decide_tier(stretch)

    state = load_state()
    fire_amount = 0
    if stretch < 0:
        if state["fire_remaining_months"] == 0 and state["reserve"] > 0:
            state["fire_remaining_months"] = 6
        if state["fire_remaining_months"] > 0 and state["reserve"] > 0:
            fire_amount = state["reserve"] / state["fire_remaining_months"]

    print("=" * 60)
    print(f"  0050 進場訊號儀表板  ({info['date']} 收盤)")
    print("=" * 60)
    print(f"  現價            {info['price']:>8.2f}")
    print(f"  MA200          {info['ma200']:>8.2f}   拉伸 {stretch:+.1f}%")
    print(f"  52 週高         {info['high_52w']:>8.2f}   距高 {discount:+.1f}%")
    print(f"  MA20 / MA60    {info['ma20']:.2f} / {info['ma60']:.2f}")
    print()
    print(f"  📊 階級：{tier}  —  {comment}")
    print(f"  💰 本月投入：{invest_amt:>7,} 元")
    print(f"  🏦 留戰備金：{save_amt:>7,} 元")
    if fire_amount > 0:
        print(f"  🚀 戰備金出動：{fire_amount:>7,.0f} 元（剩 {state['fire_remaining_months']} 期）")
    total_buy = invest_amt + fire_amount
    print(f"  ━━━━━━━━━━━━━━━━━━━━")
    print(f"  ✅ 實際買入：{total_buy:>7,.0f} 元（約 {total_buy/info['price']:.1f} 股）")
    print()
    print(f"  📦 戰備金累計：{state['reserve']:>7,.0f} 元")
    print(f"  📦 累計持股：  {state['shares_owned']:>7.1f} 股（市值約 {state['shares_owned']*info['price']:,.0f}）")
    print("=" * 60)

    if not execute:
        print("\n  （只看訊號，不更新狀態。要實際扣款記錄請加 --execute）")
        return

    cur_month = datetime.now().strftime("%Y-%m")
    if state["last_run_month"] == cur_month:
        print(f"\n  ⚠️  本月 ({cur_month}) 已執行過，跳過狀態更新")
        return

    state["shares_owned"] += total_buy / info["price"]
    state["reserve"] += save_amt - fire_amount
    if fire_amount > 0:
        state["fire_remaining_months"] -= 1
    state["last_run_month"] = cur_month
    state["history"].append({
        "month": cur_month,
        "date": info["date"],
        "price": round(info["price"], 2),
        "stretch_pct": round(stretch, 1),
        "tier": tier,
        "invest": invest_amt,
        "save": save_amt,
        "fire": round(fire_amount, 2),
        "shares_after": round(state["shares_owned"], 2),
        "reserve_after": round(state["reserve"], 2),
    })
    save_state(state)
    print(f"\n  ✅ 已記錄到 {STATE_FILE.name}")


if __name__ == "__main__":
    main(execute="--execute" in sys.argv)
