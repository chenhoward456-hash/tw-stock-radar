#!/usr/bin/env python3
"""
持倉監控 — 檢查持倉狀況，條件惡化就推 LINE 警告
用法：python3 monitor.py
也可以加到 GitHub Actions 每日自動跑

第三輪優化：
1. 移動停利（漲幅達標後自動收緊停損）
2. 動態停損（高 VIX 時收緊、低 VIX 時放寬）
3. 再進場訊號偵測
4. 持倉規模加權警告（大倉位優先）
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from holdings import HOLDINGS
import market
import technical
import fundamental
import institutional
from scoring import weighted_score
from notify import send_discord


def _trailing_take_profit(current_price, buy_price, atr, peak_price=None):
    """
    移動停利邏輯：
    - 漲幅 < 10%：不動，用原始停損
    - 漲幅 10-20%：停利線 = 高點 - 2.5 × ATR
    - 漲幅 20-40%：停利線 = 高點 - 2.0 × ATR（收緊）
    - 漲幅 > 40%：停利線 = 高點 - 1.5 × ATR（更緊）

    回傳：(trailing_stop_price, level_label) or (None, None)
    """
    if buy_price <= 0 or current_price <= 0 or atr <= 0:
        return None, None

    gain_pct = (current_price / buy_price - 1) * 100
    high = peak_price if peak_price and peak_price > current_price else current_price

    if gain_pct >= 40:
        trail = high - 1.5 * atr
        return trail, f"漲幅 {gain_pct:.0f}%，停利收緊至 1.5×ATR"
    elif gain_pct >= 20:
        trail = high - 2.0 * atr
        return trail, f"漲幅 {gain_pct:.0f}%，停利收至 2.0×ATR"
    elif gain_pct >= 10:
        trail = high - 2.5 * atr
        return trail, f"漲幅 {gain_pct:.0f}%，啟動停利 2.5×ATR"
    return None, None


def _check_reentry_signal(tech_result, fund_result):
    """
    再進場訊號偵測（出場後的股票如果條件恢復）
    條件：週線轉多 + 基本面 ≥ 6 + RSI 從超賣回升
    """
    signals = []

    weekly_trend = tech_result.get("weekly_trend", "neutral")
    rsi = tech_result.get("rsi", 50)
    fund_score = fund_result.get("score", 5)

    if weekly_trend == "bullish" and fund_score >= 6:
        if 35 <= rsi <= 55:
            signals.append("✓ 再進場條件浮現：週線轉多 + 基本面穩健 + RSI 回中性區")
        elif rsi < 35:
            signals.append("— 週線轉多但 RSI 仍低，等 RSI 回升再確認")

    if tech_result.get("divergence") == "bullish_divergence" and fund_score >= 5:
        signals.append("✓ RSI 多頭背離 + 基本面 OK，可能築底反轉")

    return signals


def check_holding(h):
    """
    檢查單一持倉，回傳警告列表

    改進：
    1. 用 weighted_score 取代簡單平均（跟掃描邏輯一致）
    2. 用 ATR 動態停損取代固定停損
    3. 新增基本面轉弱警告
    4. 第三輪：移動停利 + 再進場訊號 + 倉位加權
    """
    sid = h["stock_id"]
    buy_price = h["buy_price"]
    shares = h["shares"]
    strategy = h.get("strategy", "longterm")

    name = market.fetch_stock_name(sid)
    industry = market.fetch_stock_industry(sid)
    price_df = market.fetch_stock_price(sid)
    per_df = market.fetch_per_pbr(sid)
    inst_df = market.fetch_institutional(sid)
    rev_df = market.fetch_monthly_revenue(sid)

    tech = technical.analyze(price_df)
    if market.is_etf(sid):
        etf_info = market.fetch_etf_info(sid)
        fund = fundamental.analyze_etf(price_df, etf_info, per_df)
    else:
        fund = fundamental.analyze(per_df, rev_df, industry)
    inst = institutional.analyze(inst_df)

    # 改用 weighted_score 計算（跟主系統一致）
    is_us = market.is_us(sid)
    avg, _ = weighted_score(
        tech["score"], fund["score"], inst["score"], 5.0,
        strategy=strategy, is_us=is_us,
    )

    current_price = tech.get("current_price", 0)
    ma20 = tech.get("ma20", 0)
    atr = tech.get("atr", 0)
    atr_stop = tech.get("stop_loss", 0)  # ATR 動態停損價

    # 損益計算
    if current_price > 0 and buy_price > 0:
        pnl_pct = (current_price / buy_price - 1) * 100
        pnl_amount = (current_price - buy_price) * shares
        position_value = current_price * shares
    else:
        pnl_pct = 0
        pnl_amount = 0
        position_value = 0

    # 停損價：優先用 holdings 設定，沒設就用 ATR 動態計算
    stop_loss = h.get("stop_loss", 0)
    effective_stop = stop_loss if stop_loss > 0 else atr_stop

    # === 移動停利（第三輪新增）===
    peak_price = h.get("peak_price", None)  # 持倉期間最高價（可選）
    trailing_stop, trailing_label = _trailing_take_profit(current_price, buy_price, atr, peak_price)
    if trailing_stop and trailing_stop > effective_stop:
        effective_stop = trailing_stop  # 停利線高於停損線時，用停利線

    warnings = []
    info = []  # 非警告的補充資訊

    # 0. 停損/停利價警告（最優先）
    if effective_stop > 0 and current_price > 0 and current_price <= effective_stop:
        if trailing_stop and trailing_stop >= (stop_loss or 0) and trailing_stop >= atr_stop:
            warnings.append(f"🚨 已觸及移動停利價 {effective_stop:.0f} 元！現價 {current_price:.0f} 元，建議獲利了結")
        else:
            stop_type = "手動" if stop_loss > 0 else "ATR動態"
            warnings.append(f"🚨 已觸及{stop_type}停損價 {effective_stop:.0f} 元！現價 {current_price:.0f} 元，請立即處理")
    elif effective_stop > 0 and current_price > 0 and current_price <= effective_stop * 1.03:
        gap_pct = (current_price / effective_stop - 1) * 100
        stop_type = "手動" if stop_loss > 0 else ("停利" if trailing_stop and trailing_stop >= atr_stop else "ATR動態")
        warnings.append(f"⚠ 接近{stop_type}停損價 {effective_stop:.0f} 元（距離僅 {gap_pct:.1f}%），請留意")

    # 停利狀態資訊
    if trailing_label:
        info.append(f"📈 {trailing_label}（停利線 {trailing_stop:.0f} 元）")

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

    # 6. 基本面轉弱
    if fund["score"] <= 3:
        warnings.append(f"⚠ 基本面偏弱（{fund['score']}/10），營收或估值可能出問題")

    # 7. 週線空頭警告（第三輪新增）
    weekly_trend = tech.get("weekly_trend", "neutral")
    if weekly_trend == "bearish" and pnl_pct < 0:
        warnings.append("⚠ 週線趨勢轉空 + 帳面虧損，留意中期風險")

    # 8. RSI 空頭背離（第三輪新增）
    if tech.get("divergence") == "bearish_divergence" and pnl_pct > 15:
        warnings.append("⚠ RSI 空頭背離，漲勢可能見頂，考慮分批減碼")

    # === 再進場訊號（第三輪新增）===
    reentry = _check_reentry_signal(tech, fund)

    return {
        "stock_id": sid,
        "name": name,
        "current_price": current_price,
        "buy_price": buy_price,
        "shares": shares,
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_amount,
        "position_value": position_value,
        "avg": avg,
        "warnings": warnings,
        "info": info,
        "atr_stop": atr_stop,
        "trailing_stop": trailing_stop,
        "reentry_signals": reentry,
        "weekly_trend": weekly_trend,
    }


def format_monitor_message(results):
    """格式化持倉監控報告"""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"📋 持倉監控報告 ({now})", ""]

    # 先列出有警告的（按倉位大小排序）
    alerts = sorted([r for r in results if r["warnings"]],
                    key=lambda x: x.get("position_value", 0), reverse=True)
    safe = [r for r in results if not r["warnings"]]

    if alerts:
        lines.append("🚨 需要注意：")
        for r in alerts:
            pnl = f"{r['pnl_pct']:+.1f}%"
            val = f"（市值 {r['position_value']:,.0f}）" if r.get("position_value") else ""
            lines.append(f"\n  {r['stock_id']} {r['name']}（{r['avg']}/10）損益 {pnl}{val}")
            for w in r["warnings"]:
                lines.append(f"    {w}")
            for info in r.get("info", []):
                lines.append(f"    {info}")
        lines.append("")

    if safe:
        lines.append("✅ 狀況正常：")
        for r in safe:
            pnl = f"{r['pnl_pct']:+.1f}%"
            trailing = ""
            if r.get("trailing_stop"):
                trailing = f" 停利 {r['trailing_stop']:.0f}"
            lines.append(f"  {r['stock_id']} {r['name']}（{r['avg']}/10）損益 {pnl}{trailing}")

    # 再進場訊號
    reentries = [r for r in results if r.get("reentry_signals")]
    if reentries:
        lines.append("")
        lines.append("🔄 再進場訊號：")
        for r in reentries:
            for sig in r["reentry_signals"]:
                lines.append(f"  {r['stock_id']} {r['name']}：{sig}")

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

    # 有警告才推 Discord（不要每天都推正常的）
    alerts = [r for r in results if r["warnings"]]
    if alerts:
        print("\n🚨 有警告，推送 Discord...", end="", flush=True)
        if send_discord(message):
            print(" ✅ 已發送")
        else:
            print(" ⚠ 發送失敗")
    else:
        print("\n✅ 全部正常，不推送通知。")

    print()


if __name__ == "__main__":
    main()
