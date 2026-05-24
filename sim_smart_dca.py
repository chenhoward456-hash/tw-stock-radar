#!/usr/bin/env python3
"""
智慧 DCA vs 純 DCA 回測（0050）

對照三組策略（每月 20,000 現金流入）：
  A. 純 DCA     — 每月無腦全買
  B. 智慧 DCA   — 依 MA200 拉伸度分 5 檔調整月扣
  C. 等回檔     — 全部存現金，只在跌破 MA200 時分 6 期梭哈

回測資產 = 持股市值 + 戰備金（現金不計息）
"""
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

MONTHLY_INFLOW = 20000
YEARS = 10
BUY_FEE = 0.001425  # 簡化用標準費率（兩邊都同樣費率，不影響比較）


def fetch():
    t = yf.Ticker("0050.TW")
    df = t.history(period=f"{YEARS + 1}y")
    df = df[["Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df["ma200"] = df["Close"].rolling(200).mean()
    df["stretch"] = (df["Close"] / df["ma200"] - 1) * 100
    return df.dropna()


def tier_amounts(stretch):
    if stretch > 40:
        return 5000, 15000
    if stretch > 30:
        return 10000, 10000
    if stretch > 15:
        return 15000, 5000
    if stretch > 0:
        return 20000, 0
    return 20000, 0


def first_trading_day_per_month(df):
    return df.groupby([df.index.year, df.index.month]).head(1)


def run_pure_dca(monthly):
    shares = 0.0
    invested = 0
    for date, row in monthly.iterrows():
        price = row["Close"]
        shares += MONTHLY_INFLOW * (1 - BUY_FEE) / price
        invested += MONTHLY_INFLOW
    return shares, 0, invested


def run_smart_dca(monthly):
    shares = 0.0
    reserve = 0.0
    fire_remaining = 0
    invested = 0
    for date, row in monthly.iterrows():
        price = row["Close"]
        stretch = row["stretch"]
        invest_amt, save_amt = tier_amounts(stretch)
        invested += MONTHLY_INFLOW

        fire_amount = 0
        if stretch < 0:
            if fire_remaining == 0 and reserve > 0:
                fire_remaining = 6
            if fire_remaining > 0 and reserve > 0:
                fire_amount = reserve / fire_remaining
                reserve -= fire_amount
                fire_remaining -= 1

        total_buy = invest_amt + fire_amount
        shares += total_buy * (1 - BUY_FEE) / price
        reserve += save_amt
    return shares, reserve, invested


def run_wait_dip(monthly):
    """等回檔策略：平時全部現金，跌破 MA200 才分 6 期出手"""
    shares = 0.0
    reserve = 0.0
    fire_remaining = 0
    invested = 0
    for date, row in monthly.iterrows():
        price = row["Close"]
        stretch = row["stretch"]
        invested += MONTHLY_INFLOW
        reserve += MONTHLY_INFLOW

        if stretch < 0:
            if fire_remaining == 0:
                fire_remaining = 6
        if fire_remaining > 0 and reserve > 0:
            buy = reserve / fire_remaining
            shares += buy * (1 - BUY_FEE) / price
            reserve -= buy
            fire_remaining -= 1
    return shares, reserve, invested


def stats(name, shares, reserve, invested, final_price):
    market = shares * final_price
    total = market + reserve
    pnl = total - invested
    ret = pnl / invested * 100
    years = YEARS
    cagr = ((total / invested) ** (1 / years) - 1) * 100 if total > 0 else 0
    return {
        "name": name,
        "shares": shares,
        "reserve": reserve,
        "market": market,
        "total": total,
        "invested": invested,
        "pnl": pnl,
        "ret": ret,
        "cagr": cagr,
    }


def simulate_drawdown(df, shares_per_strategy):
    """模擬未來 -30% 立刻發生 → 各策略剩多少（看抗跌性）"""
    final = df["Close"].iloc[-1]
    crashed = final * 0.7
    out = {}
    for name, (shares, reserve) in shares_per_strategy.items():
        out[name] = shares * crashed + reserve
    return out


def print_row(s):
    print(f"  {s['name']:<14} {s['invested']:>10,.0f} "
          f"{s['market']:>11,.0f} {s['reserve']:>9,.0f} "
          f"{s['total']:>11,.0f} {s['pnl']:>+11,.0f} "
          f"{s['ret']:>+7.1f}% {s['cagr']:>+6.2f}%")


def main():
    print(f"抓 0050.TW 近 {YEARS + 1} 年資料...")
    df = fetch()
    monthly = first_trading_day_per_month(df)
    start = monthly.index[0].strftime("%Y-%m-%d")
    end = monthly.index[-1].strftime("%Y-%m-%d")
    months = len(monthly)
    final_price = df["Close"].iloc[-1]
    start_price = monthly["Close"].iloc[0]

    print(f"\n回測區間：{start} → {end}（{months} 個月）")
    print(f"0050 起始 {start_price:.2f} → 最終 {final_price:.2f}")
    print(f"期間漲幅 {(final_price/start_price-1)*100:+.1f}%")
    print(f"每月現金流入：{MONTHLY_INFLOW:,}")
    print(f"預計總投入：{MONTHLY_INFLOW * months:,}")

    results = {}
    for name, fn in [
        ("純 DCA", run_pure_dca),
        ("智慧 DCA", run_smart_dca),
        ("等回檔", run_wait_dip),
    ]:
        shares, reserve, invested = fn(monthly)
        results[name] = stats(name, shares, reserve, invested, final_price)
        results[name]["_shares"] = shares
        results[name]["_reserve"] = reserve

    print("\n" + "=" * 95)
    print(f"  {'策略':<14} {'總投入':>10} {'市值':>11} {'戰備金':>9} "
          f"{'總資產':>11} {'盈虧':>11} {'報酬':>8} {'年化':>7}")
    print("-" * 95)
    for name in ["純 DCA", "智慧 DCA", "等回檔"]:
        print_row(results[name])
    print("=" * 95)

    base = results["純 DCA"]["total"]
    print("\n📊 vs 純 DCA：")
    for name in ["智慧 DCA", "等回檔"]:
        diff = results[name]["total"] - base
        print(f"  {name:<14} 差距 {diff:>+12,.0f} 元 ({diff/base*100:+.2f}%)")

    # 抗跌性測試：立刻 -30%
    print("\n⚠️  抗跌測試（假設此刻 0050 立刻 -30%）：")
    print(f"  0050 從 {final_price:.2f} → {final_price*0.7:.2f}")
    sp = {n: (r["_shares"], r["_reserve"]) for n, r in results.items()}
    crashed = simulate_drawdown(df, sp)
    for name in ["純 DCA", "智慧 DCA", "等回檔"]:
        loss = crashed[name] - results[name]["invested"]
        print(f"  {name:<14} 總資產剩 {crashed[name]:>11,.0f} 元，相對成本 {loss:>+12,.0f}")

    # 結論
    print("\n💡 結論：")
    winner = max(results.values(), key=lambda x: x["total"])
    print(f"  區間最終贏家：{winner['name']}（{winner['total']:,.0f}）")
    smart_vs_pure = results["智慧 DCA"]["total"] - results["純 DCA"]["total"]
    if smart_vs_pure > 0:
        print(f"  智慧 DCA 比純 DCA 多賺 {smart_vs_pure:,.0f}（{smart_vs_pure/base*100:+.2f}%）")
    else:
        print(f"  智慧 DCA 比純 DCA 少賺 {abs(smart_vs_pure):,.0f}（{smart_vs_pure/base*100:+.2f}%）")
        print(f"  → 在這段（明顯牛市）等回檔的部位拖累了報酬，這是預期內的代價")


if __name__ == "__main__":
    main()
