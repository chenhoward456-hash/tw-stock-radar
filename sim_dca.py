#!/usr/bin/env python3
"""
月定額投入模擬（2020-2025）

模擬情境：
  - 每月月初投入 15,000 TWD
  - 用 R6 複合策略訊號決定「進場 or 留現金」
  - 進場時買入 0050（大盤 ETF，最穩健的基準）
  - 出場訊號觸發時賣出，資金轉現金等下一次進場
  - 現金部位不計利息（保守估計）

對照組：
  A. 純定期定額（每月無腦買 0050）
  B. 純放銀行（年利率 1.5%）
  C. R6 策略定期定額（本模擬）

用 yfinance 抓 0050.TW 的真實歷史價格。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ─── 參數 ───
MONTHLY_INVEST = 15000       # 每月投入金額
START_DATE = "2020-01-01"
END_DATE = "2025-03-28"
STOCK_ID = "0050"            # 主要投資標的
BUY_FEE = 0.001425           # 買入手續費
SELL_FEE = 0.001425          # 賣出手續費
SELL_TAX = 0.001             # ETF 證交稅 0.1%（非一般股 0.3%）


def fetch_history(symbol, start, end):
    """用 yfinance 抓歷史資料"""
    import yfinance as yf
    t = yf.Ticker(f"{symbol}.TW")
    df = t.history(start=start, end=end)
    if df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    df = df.rename(columns={
        "Date": "date", "Open": "open", "High": "max",
        "Low": "min", "Close": "close", "Volume": "Trading_Volume",
    })
    if hasattr(df["date"].dtype, "tz") and df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[["date", "open", "max", "min", "close", "Trading_Volume"]]


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(high, low, close, period=14):
    tr = pd.concat([high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_adx(high, low, close, period=14):
    tr = pd.concat([high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0), index=high.index)
    atr_s = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di = (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr_s) * 100
    minus_di = (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr_s) * 100
    di_sum = plus_di + minus_di
    dx = ((plus_di - minus_di).abs() / di_sum.replace(0, np.nan)) * 100
    return dx.ewm(alpha=1/period, min_periods=period).mean()


def run_composite_signals(df):
    """產生 R6 複合策略的每日 position signal (1=持有, 0=空手)"""
    close = df["close"].astype(float)
    high = df["max"].astype(float)
    low = df["min"].astype(float)
    volume = df["Trading_Volume"].astype(float)

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    rsi = calc_rsi(close)
    atr = calc_atr(high, low, close)
    adx = calc_adx(high, low, close)
    vol_ma5 = volume.rolling(5).mean()
    vol_ma20 = volume.rolling(20).mean()

    position = 0  # 0=空手, 1=持有
    buy_price = 0
    stop_price = 0
    signals = []

    for i in range(61, len(df)):
        c = close.iloc[i]
        m5 = ma5.iloc[i]
        m20 = ma20.iloc[i]
        m60 = ma60.iloc[i]
        r = rsi.iloc[i] if not np.isnan(rsi.iloc[i]) else 50
        a = atr.iloc[i] if not np.isnan(atr.iloc[i]) else 0
        adx_v = adx.iloc[i] if not np.isnan(adx.iloc[i]) else 0

        if any(pd.isna(v) for v in [m5, m20, m60]):
            signals.append(position)
            continue

        # 持倉出場
        if position == 1 and buy_price > 0:
            hit_stop = stop_price > 0 and c <= stop_price
            trend_break = m20 < m60
            rsi_overbought = r > 80
            adx_dead = adx_v < 15 and (c / buy_price - 1) > 0.05

            if hit_stop or trend_break or rsi_overbought or adx_dead:
                position = 0
                buy_price = 0
                stop_price = 0
            else:
                # trailing stop
                if a > 0:
                    new_stop = c - 2 * a
                    if new_stop > stop_price:
                        stop_price = new_stop

        # 空手進場
        if position == 0:
            bullish = m5 > m20 > m60
            trend_ok = adx_v > 20
            rsi_ok = 40 <= r <= 70
            v5 = vol_ma5.iloc[i] if not np.isnan(vol_ma5.iloc[i]) else 0
            v20 = vol_ma20.iloc[i] if not np.isnan(vol_ma20.iloc[i]) else 1
            vol_ok = v5 > v20 if v20 > 0 else True
            dev = (c / m20 - 1) * 100 if m20 > 0 else 0
            not_hot = dev < 5

            if bullish and trend_ok and rsi_ok and vol_ok and not_hot:
                position = 1
                buy_price = c
                if a > 0:
                    stop_price = max(c - 2 * a, c * 0.92)
                else:
                    stop_price = c * 0.92

        signals.append(position)

    # 前 61 天填 0
    return [0] * 61 + signals


def simulate():
    print()
    print("=" * 60)
    print(" 5 年月定額投入模擬（2020-01 → 2025-03）".center(60))
    print("=" * 60)
    print(f"\n 每月投入：{MONTHLY_INVEST:,} 元")
    print(f" 投資標的：{STOCK_ID}（元大台灣50）")
    print()

    # 抓資料
    print(" 抓取 0050.TW 歷史資料...")
    df = fetch_history(STOCK_ID, START_DATE, END_DATE)
    if df.empty or len(df) < 100:
        print(" ⚠ 資料不足")
        return
    print(f" → 取得 {len(df)} 筆日K")

    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    dates = df["date"].values

    # 產生策略訊號
    print(" 產生 R6 複合策略訊號...")
    position_signals = run_composite_signals(df)
    df["signal"] = position_signals

    # 找出每月第一個交易日
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    month_first = df.groupby("month").first().reset_index()

    total_months = len(month_first)
    print(f" → 共 {total_months} 個月\n")

    # ─── 模擬 A：純定期定額（每月無腦買）───
    dca_shares = 0.0
    dca_cost = 0.0
    dca_log = []

    for _, row in month_first.iterrows():
        price = row["close"]
        invest = MONTHLY_INVEST
        actual_cost = invest * (1 + BUY_FEE)  # 含手續費
        shares_bought = invest / price  # 用投入金額算股數（ETF 可零股）
        dca_shares += shares_bought
        dca_cost += actual_cost
        dca_log.append({
            "date": row["date"],
            "price": price,
            "shares_bought": shares_bought,
            "total_shares": dca_shares,
            "total_cost": dca_cost,
            "market_value": dca_shares * price,
        })

    final_price = close.iloc[-1]
    dca_final_value = dca_shares * final_price * (1 - SELL_FEE - SELL_TAX)
    dca_total_invested = MONTHLY_INVEST * total_months

    # ─── 模擬 B：純放銀行（年利率 1.5%）───
    bank_balance = 0.0
    monthly_rate = 0.015 / 12
    for _ in range(total_months):
        bank_balance = (bank_balance + MONTHLY_INVEST) * (1 + monthly_rate)

    # ─── 模擬 C：R6 策略定期定額 ───
    strat_shares = 0.0
    strat_cash = 0.0
    strat_cost = 0.0
    strat_invested = 0.0
    strat_trades = 0
    strat_log = []
    prev_signal = 0

    for _, row in month_first.iterrows():
        date = row["date"]
        price = row["close"]
        sig = row["signal"]
        invest = MONTHLY_INVEST
        strat_invested += invest

        if sig == 1:
            # 策略說進場：投入本月資金 + 累積現金
            total_to_invest = invest + strat_cash
            actual_cost = total_to_invest * (1 + BUY_FEE)
            shares_bought = total_to_invest / price
            strat_shares += shares_bought
            strat_cost += actual_cost

            if strat_cash > 0:
                strat_trades += 1  # 從現金轉進場算一次交易
            strat_cash = 0
        else:
            # 策略說空手：
            if strat_shares > 0:
                # 賣出持股轉現金
                sell_value = strat_shares * price * (1 - SELL_FEE - SELL_TAX)
                strat_cash += sell_value + invest
                strat_shares = 0
                strat_trades += 1
            else:
                # 已經是現金，累積
                strat_cash += invest

        mv = strat_shares * price + strat_cash
        strat_log.append({
            "date": date,
            "price": price,
            "signal": "持有" if sig == 1 else "現金",
            "shares": strat_shares,
            "cash": strat_cash,
            "market_value": mv,
        })

    # 最終結算（把持股賣掉）
    strat_final_shares_value = strat_shares * final_price * (1 - SELL_FEE - SELL_TAX) if strat_shares > 0 else 0
    strat_final_value = strat_final_shares_value + strat_cash

    # ─── 報告 ───
    print("=" * 60)
    print(" 模擬結果 ".center(60))
    print("=" * 60)

    print(f"\n 投入總額：{dca_total_invested:,.0f} 元（{total_months} 個月 × {MONTHLY_INVEST:,}）")
    print(f" 期間：{dates[0]} → {dates[-1]}")
    print(f" 0050 起始價：{close.iloc[0]:.1f} → 最終價：{final_price:.1f}（漲幅 {(final_price/close.iloc[0]-1)*100:+.1f}%）")

    print(f"\n {'方案':<20} {'最終資產':>12} {'報酬率':>10} {'淨賺':>12}")
    print(" " + "─" * 58)

    # A
    dca_return = (dca_final_value / dca_total_invested - 1) * 100
    dca_profit = dca_final_value - dca_total_invested
    print(f" {'A. 純定期定額 0050':<20} {dca_final_value:>12,.0f} {dca_return:>9.1f}% {dca_profit:>+12,.0f}")

    # B
    bank_return = (bank_balance / dca_total_invested - 1) * 100
    bank_profit = bank_balance - dca_total_invested
    print(f" {'B. 銀行定存 1.5%':<20} {bank_balance:>12,.0f} {bank_return:>9.1f}% {bank_profit:>+12,.0f}")

    # C
    strat_return = (strat_final_value / dca_total_invested - 1) * 100
    strat_profit = strat_final_value - dca_total_invested
    print(f" {'C. R6 策略定額':<20} {strat_final_value:>12,.0f} {strat_return:>9.1f}% {strat_profit:>+12,.0f}")

    print(f"\n R6 vs 純定額差異：{strat_final_value - dca_final_value:+,.0f} 元")
    print(f" R6 交易次數：{strat_trades} 次（進出場切換）")

    # 策略持倉比例
    holding_months = sum(1 for l in strat_log if l["signal"] == "持有")
    cash_months = total_months - holding_months
    print(f" 持倉月份：{holding_months}/{total_months}（{holding_months/total_months*100:.0f}%）")
    print(f" 現金月份：{cash_months}/{total_months}（{cash_months/total_months*100:.0f}%）")

    # 年化報酬
    years = total_months / 12
    if dca_final_value > 0 and dca_total_invested > 0:
        # 用 XIRR 近似：粗略用幾何平均
        dca_annual = ((dca_final_value / dca_total_invested) ** (1/years) - 1) * 100
        strat_annual = ((strat_final_value / dca_total_invested) ** (1/years) - 1) * 100
        print(f"\n 年化報酬（粗估）：")
        print(f"   純定額：{dca_annual:.1f}%/年")
        print(f"   R6 策略：{strat_annual:.1f}%/年")

    # 月度明細
    print(f"\n 策略月度操作摘要（節選）：")
    print(f" {'月份':<12} {'0050價格':>8} {'訊號':<6} {'持股數':>8} {'現金':>10} {'資產總值':>10}")
    print(" " + "─" * 60)
    for i, l in enumerate(strat_log):
        # 顯示每年 1 月 + 最後一筆
        month_str = l["date"][:7]
        if month_str.endswith("01") or i == len(strat_log) - 1 or i < 3:
            print(f" {l['date']:<12} {l['price']:>8.1f} {l['signal']:<6}"
                  f" {l['shares']:>8.1f} {l['cash']:>10,.0f} {l['market_value']:>10,.0f}")

    print()
    print("=" * 60)
    print(" ⚠ 注意事項：")
    print("  • 此為歷史回測，不代表未來績效")
    print("  • 已計入手續費 0.1425% + ETF 證交稅 0.1%")
    print("  • 現金部位未計利息（保守估計）")
    print("  • R6 策略用技術面訊號決定進出，非即時評分")
    print("  • 實際操作會有情緒、紀律等人為因素")
    print("=" * 60)
    print()


if __name__ == "__main__":
    simulate()
