#!/usr/bin/env python3
"""
0050 每月進場訊號儀表板（純 DCA 版）

策略：每月固定扣 20,000，不擇時、不分檔、不留戰備金。
（自家回測：純 DCA 年化 +16.03% > 智慧分檔 DCA +15.96%，sim_dca.py / sim_smart_dca.py）

MA200 拉伸度只當「市場溫度計」顯示，不影響扣款金額。
狀態（累計持股、執行紀錄）存在 entry_signal_state.json。
"""
import json
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
    """市場溫度標籤，純參考 — 不改變扣款金額"""
    if stretch_pct > 40:
        return ("極熱", "🔥 山頂區（參考用，紀律照扣）")
    if stretch_pct > 30:
        return ("熱", "⚠️ 拉伸偏高（參考用，紀律照扣）")
    if stretch_pct > 15:
        return ("偏熱", "📈 仍偏多")
    if stretch_pct > 0:
        return ("正常", "✅ 正常區間")
    return ("折價/恐慌", "🎯 跌破年線，歷史上是好價格")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_run_month": "", "shares_owned": 0.0, "history": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def main(execute=False):
    info = fetch_0050()
    stretch = (info["price"] / info["ma200"] - 1) * 100
    discount = (info["price"] / info["high_52w"] - 1) * 100
    tier, comment = decide_tier(stretch)
    total_buy = MONTHLY_INFLOW  # 固定 DCA，永不擇時

    state = load_state()

    print("=" * 60)
    print(f"  0050 月扣儀表板  ({info['date']} 收盤)")
    print("=" * 60)
    print(f"  現價            {info['price']:>8.2f}")
    print(f"  MA200          {info['ma200']:>8.2f}   拉伸 {stretch:+.1f}%")
    print(f"  52 週高         {info['high_52w']:>8.2f}   距高 {discount:+.1f}%")
    print(f"  MA20 / MA60    {info['ma20']:.2f} / {info['ma60']:.2f}")
    print()
    print(f"  🌡️ 市場溫度：{tier}  —  {comment}")
    print(f"  ━━━━━━━━━━━━━━━━━━━━")
    print(f"  ✅ 本月扣款：{total_buy:>7,} 元（固定 DCA 不擇時，約 {total_buy/info['price']:.1f} 股）")
    print()
    print(f"  📦 累計持股：  {state['shares_owned']:>7.1f} 股（市值約 {state['shares_owned']*info['price']:,.0f}）")
    print("=" * 60)

    if not execute:
        print("\n  （只看訊號，不更新狀態。要記錄本月扣款請加 --execute）")
        return

    cur_month = datetime.now().strftime("%Y-%m")
    if state["last_run_month"] == cur_month:
        print(f"\n  ⚠️  本月 ({cur_month}) 已執行過，跳過狀態更新")
        return

    state["shares_owned"] += total_buy / info["price"]
    state["last_run_month"] = cur_month
    state["history"].append({
        "month": cur_month,
        "date": info["date"],
        "price": round(info["price"], 2),
        "stretch_pct": round(stretch, 1),
        "tier": tier,
        "invest": total_buy,
        "shares_after": round(state["shares_owned"], 2),
    })
    save_state(state)
    print(f"\n  ✅ 已記錄到 {STATE_FILE.name}")


if __name__ == "__main__":
    main(execute="--execute" in sys.argv)
