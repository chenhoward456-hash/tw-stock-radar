#!/usr/bin/env python3
"""
簡易回測 — 用歷史資料驗證訊號有沒有用
用法：python3 backtest.py 2330
      python3 backtest.py 2330 365    (回測天數，預設 500)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from config import FINMIND_TOKEN
from data_fetcher import fetch_stock_name, fetch_stock_price


def generate_signals(df):
    """
    產生買賣訊號（均線交叉策略）
    5日均線突破20日均線 → 買進
    5日均線跌破20日均線 → 賣出
    """
    close = df["close"].astype(float)
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()

    signals = []
    position = False  # 是否持有

    for i in range(21, len(df)):
        prev_diff = ma5.iloc[i - 1] - ma20.iloc[i - 1]
        curr_diff = ma5.iloc[i] - ma20.iloc[i]

        if not position and prev_diff <= 0 and curr_diff > 0:
            # 黃金交叉 → 買進
            signals.append({
                "type": "BUY",
                "date": df.iloc[i]["date"],
                "price": close.iloc[i],
                "index": i,
            })
            position = True

        elif position and prev_diff >= 0 and curr_diff < 0:
            # 死亡交叉 → 賣出
            signals.append({
                "type": "SELL",
                "date": df.iloc[i]["date"],
                "price": close.iloc[i],
                "index": i,
            })
            position = False

    return signals, position


def calculate_trades(signals):
    """從訊號列表計算每筆交易的損益（含手續費和證交稅）"""
    # 臺股交易成本
    BUY_FEE = 0.001425    # 買入手續費 0.1425%
    SELL_FEE = 0.001425   # 賣出手續費 0.1425%
    TAX = 0.003           # 證交稅 0.3%（賣出時收）

    trades = []
    i = 0
    while i < len(signals) - 1:
        if signals[i]["type"] == "BUY" and signals[i + 1]["type"] == "SELL":
            buy_price = signals[i]["price"]
            sell_price = signals[i + 1]["price"]

            # 扣除交易成本
            actual_buy = buy_price * (1 + BUY_FEE)
            actual_sell = sell_price * (1 - SELL_FEE - TAX)
            ret = (actual_sell / actual_buy - 1) * 100

            trades.append({
                "buy_date": signals[i]["date"],
                "buy_price": buy_price,
                "sell_date": signals[i + 1]["date"],
                "sell_price": sell_price,
                "return_pct": ret,
            })
            i += 2
        else:
            i += 1

    return trades


def print_report(stock_id, stock_name, df, trades, still_holding):
    """印出回測報告"""
    close = df["close"].astype(float)
    start_price = close.iloc[20]  # 策略開始時的價格
    end_price = close.iloc[-1]
    buy_hold_return = (end_price / start_price - 1) * 100
    period_start = df.iloc[20]["date"]
    period_end = df.iloc[-1]["date"]

    w = 55
    print()
    print("=" * w)
    print(f" {stock_id} {stock_name} — 歷史回測報告 ".center(w))
    print("=" * w)

    print(f"\n 策略：均線交叉（5日均線突破20日買，跌破賣）")
    print(f" 期間：{period_start} ~ {period_end}")
    print(f" 資料筆數：{len(df)} 日")

    # 交易紀錄
    print(f"\n 交易紀錄：")
    print(" " + "─" * (w - 2))

    if not trades:
        print("  沒有產生任何交易訊號。")
    else:
        for i, t in enumerate(trades, 1):
            ret = t["return_pct"]
            icon = "✓" if ret > 0 else "✗"
            print(
                f"  #{i:>2} {icon} 買 {t['buy_date']} @ {t['buy_price']:.1f}"
                f"  → 賣 {t['sell_date']} @ {t['sell_price']:.1f}"
                f"  {ret:+.1f}%"
            )

        if still_holding:
            print(f"\n  ⚠ 目前仍持有中（最新價 {end_price:.1f}）")

    # 統計
    if trades:
        returns = [t["return_pct"] for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        total_return = 1
        for r in returns:
            total_return *= (1 + r / 100)
        total_return = (total_return - 1) * 100

        print(f"\n 績效統計：")
        print(" " + "─" * (w - 2))
        print(f"  交易次數：{len(trades)}")
        print(f"  勝率：{len(wins)}/{len(trades)}（{len(wins)/len(trades)*100:.0f}%）")

        if wins:
            print(f"  平均獲利：{np.mean(wins):+.1f}%")
        if losses:
            print(f"  平均虧損：{np.mean(losses):+.1f}%")

        print(f"  最大單次獲利：{max(returns):+.1f}%")
        print(f"  最大單次虧損：{min(returns):+.1f}%")

        print(f"\n  📊 策略累計報酬：{total_return:+.1f}%")
        print(f"  📊 同期買進持有：{buy_hold_return:+.1f}%")

        diff = total_return - buy_hold_return
        if diff > 5:
            print(f"  → 策略勝過買進持有 {diff:+.1f}%")
        elif diff < -5:
            print(f"  → 策略落後買進持有 {diff:.1f}%")
        else:
            print(f"  → 策略與買進持有相近（差距 {diff:+.1f}%）")

    # 注意事項
    print(f"\n ⚠ 重要提醒：")
    print(f"  • 回測不代表未來績效，過去表現不保證未來結果")
    print(f"  • 已計算手續費（買賣各 0.1425%）和證交稅（賣 0.3%）")
    print(f"  • 均線交叉只是最基礎的策略，實際系統會結合多個面向")
    if len(trades) < 5:
        print(f"  • 交易次數偏少（{len(trades)} 次），統計意義有限")

    print()
    print("=" * w)
    print()


def main():
    if len(sys.argv) < 2:
        print("簡易回測工具")
        print("=" * 30)
        print("用法：python3 backtest.py <股票代號> [回測天數]")
        print("範例：python3 backtest.py 2330")
        print("      python3 backtest.py 2330 365")
        sys.exit(1)

    stock_id = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    token = FINMIND_TOKEN or None

    print(f"\n⏳ 回測 {stock_id}（{days} 天）...\n")

    name = fetch_stock_name(stock_id, token)
    print(f"  股票：{stock_id} {name}")

    print(f"  抓取歷史資料...")
    price_df = fetch_stock_price(stock_id, days=days, token=token)

    if price_df.empty or len(price_df) < 60:
        print("  ⚠ 資料不足，至少需要 60 天以上的資料")
        sys.exit(1)

    price_df = price_df.sort_values("date").reset_index(drop=True)
    print(f"  → 取得 {len(price_df)} 筆日K資料")

    print(f"  計算訊號...")
    signals, still_holding = generate_signals(price_df)
    trades = calculate_trades(signals)
    print(f"  → 產生 {len(trades)} 筆完整交易")

    print_report(stock_id, name, price_df, trades, still_holding)


if __name__ == "__main__":
    main()
