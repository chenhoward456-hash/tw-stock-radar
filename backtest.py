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
import market


def _calc_rsi(close, period=14):
    """計算 RSI"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def generate_signals(df, stop_loss_pct=-8.0):
    """
    產生買賣訊號（均線交叉 + RSI 過濾 + 量能確認 + 停損）
    買進條件：黃金交叉 + RSI < 70 + 當日成交量 > 20日均量
    賣出條件：死亡交叉（RSI > 30 才賣）或觸發停損線
    """
    close = df["close"].astype(float)
    volume = df["Trading_Volume"].astype(float)
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    rsi = _calc_rsi(close)
    vol_ma20 = volume.rolling(20).mean()

    signals = []
    position = False
    buy_price = 0

    for i in range(21, len(df)):
        prev_diff = ma5.iloc[i - 1] - ma20.iloc[i - 1]
        curr_diff = ma5.iloc[i] - ma20.iloc[i]
        curr_rsi = rsi.iloc[i] if not np.isnan(rsi.iloc[i]) else 50

        # === 停損檢查（持有中才看）===
        if position and buy_price > 0:
            drawdown = (close.iloc[i] / buy_price - 1) * 100
            if drawdown <= stop_loss_pct:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"停損（{drawdown:.1f}%）",
                })
                position = False
                buy_price = 0
                continue

        # === 買進：黃金交叉 + RSI 未超買 + 量能放大 ===
        if not position and prev_diff <= 0 and curr_diff > 0:
            vol_ok = volume.iloc[i] > vol_ma20.iloc[i] if not np.isnan(vol_ma20.iloc[i]) else True
            if curr_rsi < 70 and vol_ok:
                signals.append({
                    "type": "BUY",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"黃金交叉（RSI {curr_rsi:.0f}）",
                })
                position = True
                buy_price = close.iloc[i]

        # === 賣出：死亡交叉（RSI 未超賣才賣，避免恐慌殺低）===
        elif position and prev_diff >= 0 and curr_diff < 0:
            if curr_rsi > 30:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"死亡交叉（RSI {curr_rsi:.0f}）",
                })
                position = False
                buy_price = 0

    return signals, position


def generate_signals_trend(df, trailing_stop_pct=-10.0):
    """
    趨勢跟蹤策略（多頭也能贏）
    進場：20MA 突破 60MA（大趨勢確認）
    出場：從最高點回落 trailing_stop_pct，或 20MA 跌破 60MA
    """
    close = df["close"].astype(float)
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    signals = []
    position = False
    buy_price = 0
    peak_price = 0

    for i in range(61, len(df)):
        prev_diff = ma20.iloc[i - 1] - ma60.iloc[i - 1]
        curr_diff = ma20.iloc[i] - ma60.iloc[i]

        if position:
            # 追蹤最高價
            if close.iloc[i] > peak_price:
                peak_price = close.iloc[i]

            # 出場條件 1：從最高點回落超過門檻
            drawdown_from_peak = (close.iloc[i] / peak_price - 1) * 100
            if drawdown_from_peak <= trailing_stop_pct:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"移動停利（從高點 {peak_price:.1f} 回落 {drawdown_from_peak:.1f}%）",
                })
                position = False
                buy_price = 0
                peak_price = 0
                continue

            # 出場條件 2：20MA 跌破 60MA（大趨勢反轉）
            if prev_diff >= 0 and curr_diff < 0:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"趨勢反轉（20MA 跌破 60MA）",
                })
                position = False
                buy_price = 0
                peak_price = 0
                continue

        # 進場：20MA 突破 60MA
        if not position and prev_diff <= 0 and curr_diff > 0:
            signals.append({
                "type": "BUY",
                "date": df.iloc[i]["date"],
                "price": close.iloc[i],
                "index": i,
                "reason": "趨勢確認（20MA 突破 60MA）",
            })
            position = True
            buy_price = close.iloc[i]
            peak_price = close.iloc[i]

    return signals, position


def calculate_trades(signals, is_us=False):
    """從訊號列表計算每筆交易的損益（含交易成本）"""
    if is_us:
        # 美股：多數券商零佣金，SEC fee 極小可忽略
        BUY_FEE = 0.0
        SELL_FEE = 0.0
        TAX = 0.0
    else:
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
                "buy_reason": signals[i].get("reason", ""),
                "sell_reason": signals[i + 1].get("reason", ""),
            })
            i += 2
        else:
            i += 1

    return trades


def print_report(stock_id, stock_name, df, trades, still_holding, is_us=False, strategy_name="均線交叉 + RSI 過濾 + 量能確認 + 停損 -8%"):
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

    print(f"\n 策略：{strategy_name}")
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
            sell_reason = t.get("sell_reason", "")
            reason_tag = f" [{sell_reason}]" if sell_reason else ""
            print(
                f"  #{i:>2} {icon} 買 {t['buy_date']} @ {t['buy_price']:.1f}"
                f"  → 賣 {t['sell_date']} @ {t['sell_price']:.1f}"
                f"  {ret:+.1f}%{reason_tag}"
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
    if is_us:
        print(f"  • 美股零佣金計算（未計入匯率波動）")
    else:
        print(f"  • 已計算手續費（買賣各 0.1425%）和證交稅（賣 0.3%）")
    print(f"  • 這只是「均線交叉」單一策略的壓力測試，不是系統的完整評分")
    print(f"  • 大盤 ETF 長期向上，買進持有本來就會贏，回測重點是看風控和最大虧損")
    print(f"  • 系統的價值在「選股＋風控」：幫你判斷該不該買、何時該跑")
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

    print(f"\n⏳ 回測 {stock_id}（{days} 天）...\n")

    name = market.fetch_stock_name(stock_id)
    print(f"  股票：{stock_id} {name}")

    print(f"  抓取歷史資料（還原權息價）...")
    price_df = market.fetch_stock_price_adjusted(stock_id, days=days)

    if price_df.empty or len(price_df) < 60:
        print("  ⚠ 資料不足，至少需要 60 天以上的資料")
        sys.exit(1)

    price_df = price_df.sort_values("date").reset_index(drop=True)
    print(f"  → 取得 {len(price_df)} 筆日K資料")

    is_us = market.is_us(stock_id)

    # 策略 A：均線交叉（波段）
    print(f"  [策略A] 均線交叉...")
    signals_a, hold_a = generate_signals(price_df)
    trades_a = calculate_trades(signals_a, is_us=is_us)
    print(f"  → {len(trades_a)} 筆交易")

    # 策略 B：趨勢跟蹤（多頭友善）
    print(f"  [策略B] 趨勢跟蹤...")
    signals_b, hold_b = generate_signals_trend(price_df)
    trades_b = calculate_trades(signals_b, is_us=is_us)
    print(f"  → {len(trades_b)} 筆交易")

    print_report(stock_id, name, price_df, trades_a, hold_a, is_us=is_us,
                 strategy_name="均線交叉 + RSI + 量能 + 停損 -8%（波段）")
    print_report(stock_id, name, price_df, trades_b, hold_b, is_us=is_us,
                 strategy_name="趨勢跟蹤 — 20/60MA + 移動停利 -10%（順勢）")


if __name__ == "__main__":
    main()
