#!/usr/bin/env python3
"""
智慧 DCA vs 純 DCA 回測（0050）— FinMind 真實資料版

修正 yfinance 拆股調整的偏誤：
  - 用 FinMind TaiwanStockPrice 抓 nominal 原始價（未拆股調整）
  - 用 TaiwanStockDividend 抓真實配息
  - 手動處理 2025-06-13 的 1:4 拆股
  - 配息一律當現金加入 reserve，下次扣款時優先使用（自動再投入）

三策略（每月 20,000 現金流入）：
  A. 純 DCA   — 每月把 (現金流入 + reserve) 全部買掉
  B. 智慧 DCA — 依 MA200 拉伸度分 5 檔，高檔留現金
  C. 等回檔   — 平時全留現金，跌破 MA200 才分 6 期出手
"""
import sys
from datetime import datetime

import pandas as pd
import requests

sys.path.insert(0, ".")
import config

MONTHLY_INFLOW = 20000
BUY_FEE = 0.001425
FINMIND = "https://api.finmindtrade.com/api/v4/data"

# 已知拆股：0050 在 2025-06-13 進行 1:4 拆股，6/11-17 停牌，6/18 為第一個拆股後交易日
SPLITS = [("2025-06-18", 4)]


def fmget(dataset, sid, start, end):
    r = requests.get(FINMIND, params={
        "dataset": dataset, "data_id": sid,
        "start_date": start, "end_date": end,
        "token": config.FINMIND_TOKEN,
    }, timeout=30)
    return pd.DataFrame(r.json().get("data", []))


def fetch_all(start_date, end_date):
    """抓價格 + 除權息"""
    # 分批抓（FinMind 單次有上限）
    parts = []
    cur = pd.Timestamp(start_date)
    final = pd.Timestamp(end_date)
    while cur < final:
        nxt = min(cur + pd.DateOffset(years=3), final)
        df = fmget("TaiwanStockPrice", "0050",
                   cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d"))
        if not df.empty:
            parts.append(df)
        cur = nxt + pd.Timedelta(days=1)
    price = pd.concat(parts, ignore_index=True).drop_duplicates(subset="date")
    price["date"] = pd.to_datetime(price["date"])
    price = price.sort_values("date").reset_index(drop=True)

    divs = fmget("TaiwanStockDividend", "0050", start_date, end_date)
    if not divs.empty:
        divs = divs[["CashExDividendTradingDate", "CashEarningsDistribution", "CashStatutorySurplus"]].copy()
        divs.columns = ["ex_date", "cash1", "cash2"]
        divs["ex_date"] = pd.to_datetime(divs["ex_date"], errors="coerce")
        divs["per_share"] = divs["cash1"].fillna(0) + divs["cash2"].fillna(0)
        divs = divs.dropna(subset=["ex_date"]).reset_index(drop=True)
    return price, divs


def add_ma200(price):
    price = price.copy()
    price["ma200"] = price["close"].rolling(200).mean()
    price["stretch"] = (price["close"] / price["ma200"] - 1) * 100
    return price.dropna(subset=["ma200"]).reset_index(drop=True)


def tier_amounts(stretch):
    if stretch > 40: return 5000, 15000
    if stretch > 30: return 10000, 10000
    if stretch > 15: return 15000, 5000
    if stretch > 0:  return 20000, 0
    return 20000, 0


def get_first_trading_days(price):
    """每月第一個交易日索引"""
    grp = price.groupby([price["date"].dt.year, price["date"].dt.month])
    return set(grp.head(1).index)


def get_split_dates(price):
    out = {}
    for d, ratio in SPLITS:
        d = pd.Timestamp(d)
        idx = price.index[price["date"] == d]
        if len(idx):
            out[int(idx[0])] = ratio
    return out


def get_div_map(price, divs):
    """ex_date → per_share dividend"""
    out = {}
    for _, row in divs.iterrows():
        idx = price.index[price["date"] == row["ex_date"]]
        if len(idx):
            out[int(idx[0])] = row["per_share"]
    return out


class Strategy:
    def __init__(self, name):
        self.name = name
        self.shares = 0.0
        self.reserve = 0.0  # 現金池（含累積配息）
        self.invested = 0
        self.fire_remaining = 0

    def on_dividend(self, per_share):
        self.reserve += self.shares * per_share

    def on_split(self, ratio):
        self.shares *= ratio

    def on_month_first(self, price, stretch):
        raise NotImplementedError

    def total(self, price):
        return self.shares * price + self.reserve


class PureDCA(Strategy):
    def on_month_first(self, price, stretch):
        self.invested += MONTHLY_INFLOW
        cash = MONTHLY_INFLOW + self.reserve
        self.shares += cash * (1 - BUY_FEE) / price
        self.reserve = 0


class SmartDCA(Strategy):
    def on_month_first(self, price, stretch):
        self.invested += MONTHLY_INFLOW
        invest_amt, save_amt = tier_amounts(stretch)
        fire = 0
        if stretch < 0:
            if self.fire_remaining == 0 and self.reserve > 0:
                self.fire_remaining = 6
            if self.fire_remaining > 0 and self.reserve > 0:
                fire = self.reserve / self.fire_remaining
                self.reserve -= fire
                self.fire_remaining -= 1
        total_buy = invest_amt + fire
        self.shares += total_buy * (1 - BUY_FEE) / price
        self.reserve += save_amt


class WaitDip(Strategy):
    def on_month_first(self, price, stretch):
        self.invested += MONTHLY_INFLOW
        self.reserve += MONTHLY_INFLOW
        if stretch < 0 and self.fire_remaining == 0:
            self.fire_remaining = 6
        if self.fire_remaining > 0 and self.reserve > 0:
            buy = self.reserve / self.fire_remaining
            self.shares += buy * (1 - BUY_FEE) / price
            self.reserve -= buy
            self.fire_remaining -= 1


def simulate(price, divs, label):
    months = get_first_trading_days(price)
    splits = get_split_dates(price)
    divmap = get_div_map(price, divs)

    strats = [PureDCA("純 DCA"), SmartDCA("智慧 DCA"), WaitDip("等回檔")]

    for idx, row in price.iterrows():
        p = row["close"]
        s = row["stretch"]
        # 拆股先
        if idx in splits:
            for st in strats:
                st.on_split(splits[idx])
        # 配息
        if idx in divmap:
            for st in strats:
                st.on_dividend(divmap[idx])
        # 月初扣款
        if idx in months:
            for st in strats:
                st.on_month_first(p, s)

    final_price = price["close"].iloc[-1]
    start = price["date"].iloc[0].strftime("%Y-%m")
    end = price["date"].iloc[-1].strftime("%Y-%m")
    yrs = (price["date"].iloc[-1] - price["date"].iloc[0]).days / 365.25
    n_months = len(months)

    # 為了反映拆股後的真實漲跌，把起始價也做拆股調整
    split_factor = 1
    for d, r in SPLITS:
        if pd.Timestamp(d) <= price["date"].iloc[-1] and pd.Timestamp(d) > price["date"].iloc[0]:
            split_factor *= r
    start_price_eq = price["close"].iloc[0] / split_factor

    print(f"\n{'='*92}")
    print(f"  {label}: {start} → {end} ({n_months} 月, {yrs:.1f} 年)")
    print(f"  0050 起 {price['close'].iloc[0]:.2f} → 終 {final_price:.2f} "
          f"(拆股還原後等於 {start_price_eq:.2f} → {final_price:.2f}, "
          f"純價格漲幅 {(final_price/start_price_eq-1)*100:+.1f}%)")
    cum_div = sum(divs.set_index("ex_date").per_share.fillna(0)
                  .loc[price["date"].iloc[0]:price["date"].iloc[-1]])
    print(f"  期間累積每股配息 {cum_div:.2f} 元")
    print(f"{'-'*92}")
    print(f"  {'策略':<14} {'總投入':>10} {'市值':>11} {'現金':>9} {'總資產':>11} {'盈虧':>11} {'報酬':>8} {'年化':>7}")
    results = {}
    for st in strats:
        market = st.shares * final_price
        total = market + st.reserve
        pnl = total - st.invested
        ret = pnl / st.invested * 100
        cagr = ((total / st.invested) ** (1 / yrs) - 1) * 100 if total > 0 else 0
        results[st.name] = total
        print(f"  {st.name:<14} {st.invested:>10,.0f} {market:>11,.0f} "
              f"{st.reserve:>9,.0f} {total:>11,.0f} {pnl:>+11,.0f} "
              f"{ret:>+7.1f}% {cagr:>+6.2f}%")

    base = results["純 DCA"]
    print(f"  → 智慧 DCA vs 純 DCA: {results['智慧 DCA']-base:+,.0f} "
          f"({(results['智慧 DCA']-base)/base*100:+.2f}%)")
    print(f"  → 等回檔 vs 純 DCA:   {results['等回檔']-base:+,.0f} "
          f"({(results['等回檔']-base)/base*100:+.2f}%)")
    return results


def main():
    print("從 FinMind 抓 0050 nominal 原始價 + 配息（2005-2026）...")
    price_full, divs = fetch_all("2005-01-01", "2026-12-31")
    print(f"  價格 {len(price_full)} 筆, 配息 {len(divs)} 筆")
    price_full = add_ma200(price_full)

    for label, s, e in [
        ("2008-2018（含金融海嘯）", "2008-01-01", "2018-12-31"),
        ("2015-2020（含 2020 疫情急跌）", "2015-01-01", "2020-12-31"),
        ("2016-2026（近 10 年牛市）", "2016-01-01", "2026-12-31"),
        ("2010-2020（中等樣本）", "2010-01-01", "2020-12-31"),
    ]:
        sub = price_full[(price_full["date"] >= s) & (price_full["date"] <= e)].reset_index(drop=True)
        if sub.empty:
            print(f"\n{label}: 無資料")
            continue
        sub_divs = divs[(divs["ex_date"] >= sub["date"].iloc[0]) &
                        (divs["ex_date"] <= sub["date"].iloc[-1])].reset_index(drop=True)
        simulate(sub, sub_divs, label)


if __name__ == "__main__":
    main()
