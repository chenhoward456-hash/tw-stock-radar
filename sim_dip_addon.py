#!/usr/bin/env python3
"""
閒錢加碼回測：純 DCA vs DCA+回檔加碼(0050) vs DCA+回檔加碼(正2)

貼著 Howard 的真實狀況：
  - 月扣 20,000 進 0050（雷打不動）
  - 閒錢每次 3,000~5,000，每月最多觸發一次
  - 觸發條件 = LINE bot 的機會通知：單日跌3% / 距52週高 -10%/-15%/-25%（每階一次，回到-5%內重置）

對照組：同樣的閒錢不擇時，直接加到下個月月扣（檢驗「擇時」本身有沒有貢獻）
"""
import sys
import numpy as np
import pandas as pd
import yfinance as yf

ADDON = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
MONTHLY = 20000


def xirr(cashflows):
    """cashflows: list of (date, amount); negative = invest, positive = final value"""
    dates = pd.to_datetime([c[0] for c in cashflows])
    amts = np.array([c[1] for c in cashflows], dtype=float)
    t = np.array([(d - dates[0]).days / 365.25 for d in dates])
    rate = 0.1
    for _ in range(100):
        f = np.sum(amts / (1 + rate) ** t)
        df = np.sum(-t * amts / (1 + rate) ** (t + 1))
        if abs(df) < 1e-12:
            break
        step = f / df
        rate -= step
        if abs(step) < 1e-8:
            break
    return rate * 100


def load(sym):
    h = yf.Ticker(sym).history(period="13y")["Close"]
    h.index = h.index.tz_localize(None).normalize()
    return h


def find_events(c0050):
    """回傳 {date: tag}，同月只留第一個事件"""
    ret = c0050.pct_change() * 100
    high52 = c0050.rolling(252).max()
    dd = (c0050 / high52 - 1) * 100
    events = {}
    fired = 0  # 0 / -10 / -15 / -25
    for d in c0050.index[252:]:
        tags = []
        if dd[d] > -5 and fired != 0:
            fired = 0
        for lvl in (-25, -15, -10):
            if dd[d] <= lvl and fired > lvl:
                fired = lvl
                tags.append(f"階梯{lvl}%")
                break
        if ret[d] <= -3:
            tags.append("單日-3%")
        if tags:
            events[d] = "+".join(tags)
    # 同月最多一次（閒錢有限）
    seen_months, capped = set(), {}
    for d, tag in events.items():
        m = (d.year, d.month)
        if m not in seen_months:
            seen_months.add(m)
            capped[d] = tag
    return capped


def run(c0050, c2, events, mode):
    """mode: 'dca' | 'addon_0050' | 'addon_l2' | 'control'(閒錢平均加到月扣)"""
    sh50, sh2 = 0.0, 0.0
    flows = []
    months = sorted({(d.year, d.month) for d in c0050.index})
    first_days = {}
    for d in c0050.index:
        m = (d.year, d.month)
        if m not in first_days:
            first_days[m] = d

    event_months = {(d.year, d.month) for d in events}
    for m in months:
        d = first_days[m]
        amt = MONTHLY
        if mode == "control" and m in event_months:
            amt += ADDON  # 同樣的錢，不挑日子，月初就投
        sh50 += amt / c0050[d]
        flows.append((d, -amt))

    if mode in ("addon_0050", "addon_l2"):
        for d in events:
            if mode == "addon_0050":
                sh50 += ADDON / c0050[d]
            else:
                sh2 += ADDON / c2[d]
            flows.append((d, -ADDON))

    end = c0050.index[-1]
    final = sh50 * c0050[end] + sh2 * c2[end]
    invested = -sum(a for _, a in flows)
    flows.append((end, final))
    return invested, final, xirr(flows)


def main():
    c0050, c2 = load("0050.TW"), load("00631L.TW")
    common = c0050.index.intersection(c2.index)
    c0050, c2 = c0050[common], c2[common]
    print(f"回測期間：{common[0].date()} ~ {common[-1].date()}（{len(common)} 個交易日）")
    print(f"閒錢額度：每次 {ADDON:,}、每月最多一次\n")

    events = find_events(c0050)
    by_tag = {}
    for tag in events.values():
        key = tag.split("+")[0]
        by_tag[key] = by_tag.get(key, 0) + 1
    print(f"觸發事件：共 {len(events)} 次 / {dict(sorted(by_tag.items()))}")
    total_addon = len(events) * ADDON
    print(f"閒錢總投入：{total_addon:,}（對比月扣總投入約 {len({(d.year,d.month) for d in c0050.index})*MONTHLY:,}）\n")

    rows = []
    for mode, name in [
        ("dca", "A 純 DCA（基準）"),
        ("addon_0050", "B DCA+閒錢加碼 0050"),
        ("addon_l2", "C DCA+閒錢加碼 正2"),
        ("control", "D 同樣閒錢不擇時（月初投）"),
    ]:
        inv, fin, r = run(c0050, c2, events, mode)
        rows.append((name, inv, fin, fin - inv, r))

    print(f"{'策略':<26}{'總投入':>12}{'期末市值':>14}{'獲利':>14}{'年化(XIRR)':>10}")
    for name, inv, fin, pnl, r in rows:
        print(f"{name:<26}{inv:>12,.0f}{fin:>14,.0f}{pnl:>14,.0f}{r:>9.2f}%")

    # 正2 這段期間最深回檔（讓他知道坐的是什麼車）
    dd2 = (c2 / c2.cummax() - 1) * 100
    print(f"\n參考：正2 期間最深回檔 {dd2.min():.0f}%（0050 同期最深 {((c0050/c0050.cummax()-1)*100).min():.0f}%）")


if __name__ == "__main__":
    main()
