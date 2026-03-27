#!/usr/bin/env python3
"""
通知模組 — 掃描結果推送到 LINE Bot 或 Telegram
用法：python3 notify.py

支援兩種通知管道（可以同時用）：
  1. LINE Bot（Messaging API）— 填 LINE_CHANNEL_ACCESS_TOKEN + LINE_USER_ID
  2. Telegram Bot — 填 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
"""
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
# 讀取通知設定
try:
    from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID
except ImportError:
    LINE_CHANNEL_ACCESS_TOKEN = ""
    LINE_USER_ID = ""

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

from watchlist import WATCHLIST
import market
import technical
import fundamental
import institutional
import news as news_module
from scoring import weighted_score


SIGNAL_TEXT = {"green": "[綠燈]", "yellow": "[黃燈]", "red": "[紅燈]"}


def send_line(message):
    """透過 LINE Messaging API 推送訊息"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        return False

    url = "https://api.line.me/v2/bot/message/push"
    try:
        resp = requests.post(url, headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }, json={
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": message}],
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"  ⚠ LINE 發送失敗：{e}")
        return False


def send_telegram(message):
    """透過 Telegram Bot 發送訊息"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"  ⚠ Telegram 發送失敗：{e}")
        return False


def run_scan():
    """執行掃描，回傳結果列表"""
    all_stocks = []
    stock_sectors = {}
    for sector, codes in WATCHLIST.items():
        for code in codes:
            all_stocks.append(code)
            stock_sectors[code] = sector

    names = market.fetch_stock_names(all_stocks)
    total = len(all_stocks)

    # 掃描前取得一次總體經濟環境
    try:
        import macro as _macro
        _macro_data = _macro.analyze()
        _macro_mult = _macro_data["risk_multiplier"]
    except Exception:
        _macro_mult = 1.0

    def _scan_one(stock_id):
        name = names.get(stock_id, stock_id)
        price_df = market.fetch_stock_price(stock_id)
        per_df = market.fetch_per_pbr(stock_id)
        inst_df = market.fetch_institutional(stock_id)
        rev_df = market.fetch_monthly_revenue(stock_id)
        industry = market.fetch_stock_industry(stock_id)

        tech = technical.analyze(price_df)
        if market.is_etf(stock_id):
            etf_info = market.fetch_etf_info(stock_id)
            fund = fundamental.analyze_etf(price_df, etf_info, per_df)
        else:
            fund = fundamental.analyze(per_df, rev_df, industry)
        inst = institutional.analyze(inst_df)

        # 抓新聞（失敗給中性 5 分）
        try:
            news_result = news_module.analyze(stock_id, name)
            news_score = news_result["score"]
        except Exception:
            news_score = 5.0

        # 改用 weighted_score（跟主系統一致）
        avg, _ = weighted_score(
            tech["score"], fund["score"], inst["score"], news_score,
            strategy="balanced", is_us=market.is_us(stock_id),
            macro_multiplier=_macro_mult,
        )
        overall = "green" if avg >= 7 else ("yellow" if avg >= 4 else "red")

        return {
            "stock_id": stock_id,
            "name": name,
            "sector": stock_sectors[stock_id],
            "tech": tech["score"],
            "fund": fund["score"],
            "inst": inst["score"],
            "news": news_score,
            "avg": avg,
            "overall": overall,
        }

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_scan_one, sid): sid for sid in all_stocks}
        for future in as_completed(futures):
            done += 1
            sid = futures[future]
            name = names.get(sid, sid)
            try:
                r = future.result()
                results.append(r)
                print(f"  [{done}/{total}] {sid} {name} {r['avg']}")
            except Exception:
                print(f"  [{done}/{total}] {sid} {name} 失敗")

    results.sort(key=lambda x: x["avg"], reverse=True)

    # 自動儲存訊號記錄
    try:
        import tracker
        filepath = tracker.save_scan(results)
        print(f"\n  📝 訊號已記錄：{filepath}")
    except Exception:
        pass

    return results


def check_0050_regime():
    """
    0050 多空轉換偵測
    多頭：20MA > 60MA + 股價在均線上
    空頭：20MA < 60MA + 股價在均線下
    回傳：("bull"/"bear"/"neutral", 說明文字)
    """
    try:
        import market
        import technical
        price_df = market.fetch_stock_price("0050", days=150)
        if price_df.empty:
            return "neutral", ""

        tech = technical.analyze(price_df)
        score = tech["score"]
        details = tech["details"]

        # 找趨勢方向
        trend_up = any("趨勢向上" in d or "趨勢剛轉多" in d for d in details)
        trend_down = any("趨勢向下" in d or "趨勢剛轉空" in d for d in details)
        below_ma = any("跌破" in d and "均線" in d for d in details)
        above_ma = any("站上所有均線" in d for d in details)

        if trend_down and below_ma and score <= 3:
            return "bear", f"0050 技術分 {score}/10，趨勢轉空 + 跌破均線"
        elif trend_down and score <= 4:
            return "warning", f"0050 技術分 {score}/10，趨勢偏空，注意風險"
        elif trend_up and above_ma and score >= 7:
            return "bull", f"0050 技術分 {score}/10，多頭排列，安心持有"
        elif trend_up:
            return "bull_mild", f"0050 技術分 {score}/10，趨勢向上"
        else:
            return "neutral", f"0050 技術分 {score}/10，盤整中"
    except Exception:
        return "neutral", ""


def format_message(results):
    """格式化通知訊息"""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"投資雷達掃描 ({now})", ""]

    # ===== 總體經濟環境（新增）=====
    try:
        import macro as _macro
        _macro_data = _macro.analyze()
        _macro_score = _macro_data["score"]
        _macro_mult = _macro_data["risk_multiplier"]
        if _macro_data["signal"] == "red":
            lines.append(f"🚨 總體環境警報 — 環境分 {_macro_score}/10")
            lines.append(f"  個股評分自動降級（×{_macro_mult}）")
            lines.append("")
        elif _macro_mult < 0.95:
            lines.append(f"⚠ 總體環境偏弱 — 環境分 {_macro_score}/10（×{_macro_mult}）")
            lines.append("")
    except Exception:
        pass

    # ===== 0050 多空燈號（最重要，放最上面）=====
    regime, regime_msg = check_0050_regime()
    if regime == "bear":
        lines.append("🚨🚨🚨 0050 空頭警報 🚨🚨🚨")
        lines.append(regime_msg)
        lines.append("→ 建議暫停定期定額，考慮減碼")
        lines.append("")
    elif regime == "warning":
        lines.append("⚠ 0050 多空轉換注意")
        lines.append(regime_msg)
        lines.append("→ 留意後續發展，準備應變")
        lines.append("")
    elif regime == "bull":
        lines.append("✅ 0050 多頭確認")
        lines.append(regime_msg)
        lines.append("→ 安心定期定額，不用動")
        lines.append("")
    # bull_mild 和 neutral 不特別提示，減少噪音

    # 幫每檔算長線分數
    try:
        import valuation
        for r in results:
            try:
                sid = r["stock_id"]
                price_df = market.fetch_stock_price(sid)
                per_df = market.fetch_per_pbr(sid)
                rev_df = market.fetch_monthly_revenue(sid)
                ind = market.fetch_stock_industry(sid)
                if market.is_etf(sid):
                    r["long_score"] = r.get("fund", 5)
                else:
                    long_r = valuation.analyze_longterm(per_df, rev_df, price_df, ind)
                    r["long_score"] = long_r["score"]
            except Exception:
                r["long_score"] = 0
    except Exception:
        pass

    greens = [r for r in results if r["avg"] >= 7]
    watchlist = [r for r in results if 6 <= r["avg"] < 7]
    reds = [r for r in results if r["avg"] < 4]

    if greens:
        lines.append(f"🟢 短線綠燈（{len(greens)} 檔）：")
        for r in greens:
            ls = r.get("long_score", 0)
            if ls <= 5:
                lines.append(f"  ⚠ {r['stock_id']} {r['name']} 短{r['avg']}/長{ls} ← 長線弱，別追")
            else:
                lines.append(f"  {r['stock_id']} {r['name']} 短{r['avg']}/長{ls}")
        lines.append("")
    else:
        lines.append("💡 今天沒有綠燈股，耐心等待。")
        lines.append("")

    if watchlist:
        lines.append(f"🟡 值得關注（{len(watchlist)} 檔）：")
        for r in watchlist[:5]:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        if len(watchlist) > 5:
            lines.append(f"  ...還有 {len(watchlist) - 5} 檔")
        lines.append("")

    # 長線佈局機會
    long_opps = [r for r in results if r.get("long_score", 0) >= 7 and r["avg"] < 7]
    if long_opps:
        long_opps.sort(key=lambda x: x.get("long_score", 0), reverse=True)
        lines.append(f"📉 長線佈局機會（{len(long_opps)} 檔）：")
        for r in long_opps[:5]:
            lines.append(f"  {r['stock_id']} {r['name']} 短{r['avg']}/長{r.get('long_score',0)}")
        if len(long_opps) > 5:
            lines.append(f"  ...還有 {len(long_opps) - 5} 檔")
        lines.append("")

    if reds:
        lines.append(f"🔴 偏空（{len(reds)} 檔）— 不要碰")
        for r in reds[:3]:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        lines.append("")

    lines.append("📈 今日 Top 5：")
    for r in results[:5]:
        sig = SIGNAL_TEXT[r["overall"]]
        lines.append(f"  {r['stock_id']} {r['name']} {sig} {r['avg']}/10")

    lines.append("")
    lines.append(f"共掃描 {len(results)} 檔 ｜ 僅供參考")

    return "\n".join(lines)


def main():
    has_line = bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID)
    has_telegram = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

    if not has_line and not has_telegram:
        print()
        print("⚠ 尚未設定通知管道！")
        print()
        print("請到 config.py 設定至少一種：")
        print()
        print("方法一：LINE Bot（你已經有的話最快）")
        print("  LINE_CHANNEL_ACCESS_TOKEN = '你的 Channel Access Token'")
        print("  LINE_USER_ID = '你的 User ID'")
        print()
        print("方法二：Telegram Bot")
        print("  TELEGRAM_BOT_TOKEN = '你的 Bot Token'")
        print("  TELEGRAM_CHAT_ID = '你的 Chat ID'")
        print()
        sys.exit(1)

    print()
    print("=" * 50)

    channels = []
    if has_line:
        channels.append("LINE")
    if has_telegram:
        channels.append("Telegram")
    print(f" 臺股雷達 — 掃描並推送 {' + '.join(channels)} ".center(50))

    print("=" * 50)
    print()
    print("開始掃描...\n")

    results = run_scan()

    if not results:
        print("\n⚠ 沒有取得任何結果")
        return

    message = format_message(results)

    print(f"\n📨 發送通知...\n")

    if has_line:
        print("  LINE...", end="", flush=True)
        if send_line(message):
            print(" ✅ 已發送")
        else:
            print(" ⚠ 失敗，請檢查 Token 和 User ID")

    if has_telegram:
        print("  Telegram...", end="", flush=True)
        if send_telegram(message):
            print(" ✅ 已發送")
        else:
            print(" ⚠ 失敗，請檢查 Token 和 Chat ID")

    print()


if __name__ == "__main__":
    main()
