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

try:
    from config import DISCORD_WEBHOOK_URL
except ImportError:
    DISCORD_WEBHOOK_URL = ""

from watchlist import WATCHLIST
import market
import technical
import fundamental
import institutional
import news as news_module
from scoring import weighted_score, suggest_regime_strategy
import streak
import risk_management


SIGNAL_TEXT = {"green": "[綠燈]", "yellow": "[黃燈]", "red": "[紅燈]"}


def _split_message(text, limit=4900):
    """將超長訊息切段，盡量在換行處切割"""
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        idx = text.rfind("\n", 0, limit)
        if idx == -1:
            idx = limit
        parts.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return parts


def send_line(message):
    """透過 LINE Messaging API 推送訊息（自動分段）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print(f"  ⚠ LINE token 或 user ID 未設定")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    parts = _split_message(message)
    for i, part in enumerate(parts):
        try:
            resp = requests.post(url, headers=headers, json={
                "to": LINE_USER_ID,
                "messages": [{"type": "text", "text": part}],
            }, timeout=10)
            if resp.status_code != 200:
                print(f"  ⚠ LINE API 回傳 {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            print(f"  ⚠ LINE 發送失敗：{e}")
            return False
    return True


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


def send_discord(message):
    """透過 Discord Webhook 推送訊息（自動分段，Discord 上限 2000 字）"""
    if not DISCORD_WEBHOOK_URL:
        print("  ⚠ DISCORD_WEBHOOK_URL 未設定")
        return False

    parts = _split_message(message, limit=1900)
    for part in parts:
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json={
                "content": part,
            }, timeout=10)
            if resp.status_code not in (200, 204):
                print(f"  ⚠ Discord API 回傳 {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            print(f"  ⚠ Discord 發送失敗：{e}")
            return False
    return True


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

        # 新聞：先用快速關鍵字，AI 分析留給候選股（省時間）
        try:
            news_result = news_module.analyze(stock_id, name)
            news_score = news_result["score"]
        except Exception:
            news_score = 5.0

        # 改用 weighted_score（跟主系統一致）
        _is_us = market.is_us(stock_id)
        # 美股用專屬動量策略（scoring.py R7 新增）
        main_strategy = "us_momentum" if _is_us else "balanced"
        short_strategy = "us_momentum" if _is_us else "short"

        avg, _ = weighted_score(
            tech["score"], fund["score"], inst["score"], news_score,
            strategy=main_strategy, is_us=_is_us,
            macro_multiplier=_macro_mult,
        )
        overall = "green" if avg >= 7 else ("yellow" if avg >= 4 else "red")

        # 桶2 用：短線權重（重籌碼/動量）；美股走 us_momentum
        short_avg, _ = weighted_score(
            tech["score"], fund["score"], inst["score"], news_score,
            strategy=short_strategy, is_us=_is_us,
            macro_multiplier=_macro_mult,
        )

        return {
            "stock_id": stock_id,
            "name": name,
            "sector": stock_sectors[stock_id],
            "tech": tech["score"],
            "fund": fund["score"],
            "inst": inst["score"],
            "news": news_score,
            "avg": avg,
            "short_avg": short_avg,
            "overall": overall,
            "current_price": tech.get("current_price", 0),
            "atr": tech.get("atr", 0),
            "ma5": tech.get("ma5"),
            "ma20": tech.get("ma20", 0),
            "ma60": tech.get("ma60", 0),
            "rsi": tech.get("rsi"),
            "adx": tech.get("adx"),
            "weekly_trend": tech.get("weekly_trend", "neutral"),
            "is_us": _is_us,
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


def _load_yesterday_results():
    """載入昨天的掃描結果，用來比對變化"""
    try:
        import tracker
        dates = tracker.list_records()
        if len(dates) < 2:
            return {}
        # 倒數第二個是昨天（最新的是今天剛存的）
        yesterday = dates[-2] if len(dates) >= 2 else dates[-1]
        data = tracker.load_record(yesterday)
        if data and "results" in data:
            return {r["stock_id"]: r for r in data["results"]}
    except Exception:
        pass
    return {}


def _build_tag(r, streak_info=None):
    """
    為單一候選股產生 1 行辨識 tag（R8）
    規則（優先序）：
      1. 首日由黃轉綠 + 量爆 → 「突破首日」
      2. 52週新高附近 → 「接近52週高」
      3. 週線+日線雙多 + RS≥80 → 「RS頂尖+雙時框」
      4. 連續 N 天綠燈 → 「連N天綠」
      5. fund ≥ 8 + 估值便宜 → 「基本面旗艦」
      6. inst ≥ 8 → 「法人大買」
    """
    tags = []
    tech = r.get("tech", 0)
    fund = r.get("fund", 0)
    inst = r.get("inst", 0)
    rs = r.get("rs_score", 0)
    weekly = r.get("weekly_trend", "neutral")

    # 連續天數
    if streak_info:
        sk = streak_info.get(r["stock_id"], {})
        days = sk.get("streak", 0) if sk.get("type") == "green" else 0
        if days == 1:
            tags.append("首日綠")
        elif days >= 5:
            tags.append(f"連{days}天綠")
        elif days >= 2:
            tags.append(f"連{days}天")

    # 雙時框共振
    if weekly == "bullish" and tech >= 7:
        if rs >= 80:
            tags.append("RS頂尖+雙時框")
        else:
            tags.append("週線+日線雙多")

    # 基本面/籌碼
    if fund >= 8:
        tags.append("基本面強")
    if inst >= 8:
        tags.append("法人大買")

    return "｜".join(tags[:3]) if tags else ""


def _entry_timing(r):
    """
    呼叫 scoring.assess_entry_timing 判斷進場時機
    回傳 (icon, 建議進場價 or None, 簡短說明)
    """
    from scoring import assess_entry_timing
    try:
        res = assess_entry_timing(
            score=r.get("avg", 5),
            rsi=r.get("rsi"),
            price=r.get("current_price", 0),
            ma20=r.get("ma20", 0),
            ma5=r.get("ma5"),
        )
        timing = res.get("timing", "not_recommended")
        ideal = res.get("ideal_entry")
        if timing == "now":
            return "🟢立即", None, "未過熱"
        elif timing == "wait_pullback":
            return "🟡等拉回", ideal, res.get("reason", "")
        elif timing == "watch":
            return "👀觀察", ideal, res.get("reason", "")
        else:
            return "🔴暫不", None, res.get("reason", "")
    except Exception:
        return "", None, ""


def _short_stop(cp, atr, ma20, ma60):
    """
    桶2 短線停損：min(MA20, cp − 2×ATR)
    R8：修正原本 max(ma60, ...) 的邏輯，改用較近的停損讓短線做短。
    MA20 距離太近（<3%）時退用 2×ATR 作為底線；MA60 僅作為絕對底線避免過緊。
    """
    if cp <= 0:
        return 0
    atr_stop = cp - 2 * atr if atr > 0 else cp * 0.95
    if ma20 and ma20 > 0:
        # 取 MA20 與 2×ATR 較靠近的那個（較高價），但距離不能 <3%
        tight = max(ma20, atr_stop)
        if cp > 0 and (cp - tight) / cp < 0.03:
            tight = min(ma20, atr_stop)  # 太緊 → 退到較遠者
        return tight
    return atr_stop


def _long_stop(cp, atr, ma60):
    """
    桶3 長線停損：max(MA60, cp × 0.92)，給足長線空間。
    """
    if cp <= 0:
        return 0
    pct_stop = cp * 0.92
    return max(ma60, pct_stop) if ma60 else pct_stop


def format_message(results):
    """格式化通知訊息（R8：進場時機+三欄+tag+時間停損+空頭強制空倉）"""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"投資雷達掃描 ({now})", ""]

    # ===== Step 1: 先算完所有資料 =====

    # 總體經濟
    _macro_score = 5
    _macro_mult = 1.0
    _fg = 50
    try:
        import macro as _macro
        _macro_data = _macro.analyze()
        _macro_score = _macro_data["score"]
        _macro_mult = _macro_data["risk_multiplier"]
        _fg = _macro_data.get("fear_greed_index", 50)
    except Exception:
        pass

    # 0050 技術面
    _0050_price, _0050_ma20, _0050_ma60 = 0, 0, 0
    try:
        _0050_df = market.fetch_stock_price("0050", days=150)
        _0050_tech = technical.analyze(_0050_df)
        _0050_price = _0050_tech.get("current_price", 0)
        _0050_ma20 = _0050_tech.get("ma20", 0)
        _0050_ma60 = _0050_tech.get("ma60", 0)
    except Exception:
        pass

    # 長線分數
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
                    long_r = valuation.analyze_longterm(
                        per_df, rev_df, price_df, ind,
                        macro_multiplier=_macro_mult,
                    )
                    r["long_score"] = long_r["score"]
            except Exception:
                r["long_score"] = 0
    except Exception:
        pass

    # RS 排名
    try:
        from ranking import rank_by_relative_strength
        rank_by_relative_strength(results)
    except Exception:
        pass

    # ===== Step 2: 建立統一清單 =====

    greens = [r for r in results if r["avg"] >= 7]
    watchlist = [r for r in results if 6 <= r["avg"] < 7]
    reds = [r for r in results if r["avg"] < 4]

    # 連續訊號（桶2 用；R8 改抓 min_streak=1 做優先級判斷）
    try:
        streaks = streak.detect_streaks(min_streak=1)
    except Exception:
        streaks = {}

    # 桶2 候選：台股用短線分（重籌碼），美股用均衡分（沒法人資料，短線權重沒意義）
    def _b2_score(r):
        sid = r["stock_id"]
        is_us = sid.replace("-", "").replace(".", "").isalpha()
        return r["avg"] if is_us else r.get("short_avg", r["avg"])

    def _priority(r):
        """
        R8：桶2 優先級（越高越先推）
          P3 首日綠燈 + 量/突破  → 抓最早訊號
          P2 連 2 天綠           → 次優
          P1 RS ≥ 80             → 強勢
          P0 其他（連 3+ 天綠降級到這裡）
        """
        sid = r["stock_id"]
        sk = streaks.get(sid, {})
        days = sk.get("streak", 0) if sk.get("type") == "green" else 0
        rs = r.get("rs_score", 0)

        if days == 1 and r.get("tech", 0) >= 7:
            return 3
        if days == 2:
            return 2
        if rs >= 80:
            return 1
        return 0

    b2_pool = [r for r in results if _b2_score(r) >= 7]
    b2_picks = sorted(
        [r for r in b2_pool
         if r.get("rs_score", 0) >= 50
         or _priority(r) >= 2
         or _b2_score(r) >= 8.0],
        key=lambda x: (_priority(x), _b2_score(x)), reverse=True
    )

    # 持倉股票 ID（桶3 排除用）
    _holding_ids = set()
    try:
        _vars = {}
        _hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
        with open(_hp, "r", encoding="utf-8") as _f:
            exec(_f.read(), _vars)
        _holding_ids = {h["stock_id"] for h in _vars.get("HOLDINGS", [])}
    except Exception:
        pass

    # 桶3 候選 = 長線分高 + 短線低（排除已持倉）
    # R8：加價值陷阱過濾 — 必須 RS >= 30 + MA60 斜率 >= 0（不在自由落體中）
    def _ma60_slope_ok(r):
        """長線要在底部橫盤或翻揚，不是自由落體中"""
        cp = r.get("current_price", 0)
        ma60 = r.get("ma60", 0)
        if not ma60 or ma60 <= 0 or cp <= 0:
            return True  # 資料不足時不擋
        # 簡化：現價距 MA60 偏離 <20% 即視為未崩盤；真正斜率在 technical 層算
        return (cp / ma60) >= 0.80

    b3_picks = sorted(
        [r for r in results
         if r.get("long_score", 0) >= 7 and r["avg"] < 7
         and r["stock_id"] not in _holding_ids
         and r.get("rs_score", 0) >= 30
         and _ma60_slope_ok(r)],
        key=lambda x: x.get("long_score", 0), reverse=True
    )

    # ===== Step 2.5: 變化偵測（跟昨天比）=====
    yesterday = _load_yesterday_results()
    new_greens = []  # 今天新變綠燈
    lost_greens = []  # 昨天綠燈今天掉了
    if yesterday:
        today_ids = {r["stock_id"]: r for r in results}
        for r in results:
            sid = r["stock_id"]
            y = yesterday.get(sid)
            if r["avg"] >= 7 and (not y or y.get("avg", 0) < 7):
                new_greens.append(r)
            elif r["avg"] < 7 and y and y.get("avg", 0) >= 7:
                lost_greens.append({"stock_id": sid, "name": r["name"],
                                    "old": y.get("avg", 0), "new": r["avg"]})

    # ===== Step 2.6: 桶2 空倉偵測 =====
    _has_short_holding = any(
        h.get("strategy") == "short"
        for h in _vars.get("HOLDINGS", [])
    ) if '_vars' in dir() else False
    # 重新讀一次確保有值
    try:
        _vars2 = {}
        _hp2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
        with open(_hp2, "r", encoding="utf-8") as _f2:
            exec(_f2.read(), _vars2)
        _has_short_holding = any(
            h.get("strategy") == "short" for h in _vars2.get("HOLDINGS", [])
        )
    except Exception:
        _has_short_holding = False

    # ===== Step 3: 組裝訊息 =====

    # ━━━ 30 秒摘要（最重要的放最前面）━━━
    lines.append("━━━ 今日重點 ━━━")

    # 持倉需要動嗎
    _holding_alerts = []
    try:
        for h in _vars2.get("HOLDINGS", []):
            sid = h["stock_id"]
            strategy = h.get("strategy", "longterm")
            if strategy == "hold":
                continue
            stop_loss = h.get("stop_loss", 0)
            buy_price = h.get("buy_price", 0)
            _hr = next((r for r in results if r["stock_id"] == sid), None)
            if _hr:
                cp = _hr.get("current_price", 0)
                if stop_loss and cp and cp <= stop_loss:
                    _holding_alerts.append(f"🚨 {sid}：已破停損！")
                elif stop_loss and cp and cp <= stop_loss * 1.03:
                    _holding_alerts.append(f"⚠ {sid}：接近停損")
                elif buy_price and cp:
                    pnl = (cp / buy_price - 1) * 100
                    if pnl >= 20:
                        _holding_alerts.append(f"💰 {sid}：+{pnl:.0f}% 考慮止贏")
    except Exception:
        pass

    if _holding_alerts:
        for a in _holding_alerts:
            lines.append(a)
    else:
        lines.append("持倉：不用動")

    # 桶2 空倉提醒
    if not _has_short_holding and b2_picks:
        top = b2_picks[0]
        lines.append(f"桶2 空倉！候選：{top['stock_id']} {top['name']}")
    elif not _has_short_holding:
        lines.append("桶2 空倉，目前無候選")

    # 今日變化
    if new_greens:
        names_str = " ".join(f"{r['stock_id']}" for r in new_greens[:3])
        lines.append(f"🆕 新綠燈：{names_str}")
    if lost_greens:
        names_str = " ".join(f"{r['stock_id']}" for r in lost_greens[:3])
        lines.append(f"📉 掉出綠燈：{names_str}")
    if not new_greens and not lost_greens and yesterday:
        lines.append("訊號無變化")

    lines.append("")

    # 環境警報
    if _macro_score <= 3:
        lines.append(f"🚨 環境分 {_macro_score}/10 — 防禦模式")
    elif _macro_mult < 0.95:
        lines.append(f"⚠ 環境偏弱（{_macro_score}/10）")

    # 0050 狀態
    regime, regime_msg = check_0050_regime()
    if regime == "bear":
        lines.append("🚨 0050 空頭 — 桶1 縮減")
    elif regime == "warning":
        lines.append("⚠ 0050 轉弱中")
    lines.append("")

    # ━━━ 三桶操作建議 ━━━
    lines.append("━━━ 三桶操作建議 ━━━")
    lines.append("")

    # 桶1（環境分連動）
    _defensive = _macro_score <= 3
    if _0050_ma20 and _0050_ma60 and _0050_price:
        if _0050_price < _0050_ma60:
            lines.append("桶1 0050：⚠ 跌破 MA60，縮到 5,000 存戰備金")
        elif _defensive:
            lines.append("桶1 0050：⚠ 環境差，縮到 5,000 存戰備金")
        elif _0050_price <= _0050_ma20 * 1.02 and _0050_price > _0050_ma60:
            lines.append("桶1 0050：✓ 拉回 MA20，正常 7,000（可用戰備金加碼）")
        elif _0050_ma20 > _0050_ma60:
            lines.append("桶1 0050：✓ 趨勢正常，照買 7,000")
        else:
            lines.append("桶1 0050：⚠ 趨勢轉弱（MA20 < MA60），照買 7,000 但留意")
    else:
        lines.append("桶1 0050：照買 7,000")

    # 桶2（= 精選清單，環境差時強制空倉；R8 改：macro≤3 完全不推候選）
    if _defensive:
        lines.append("桶2 短線：🚨 環境分≤3 強制空倉，4,000 繼續存，不進場")
    elif b2_picks:
        top = b2_picks[:3]
        names = " / ".join(f"{r['stock_id']} {r['name']}" for r in top)
        lines.append(f"桶2 短線：✓ {names}")
        lines.append(f"  → 選最強的一檔，一次投入")
    else:
        lines.append("桶2 短線：— 沒有精選候選，4,000 繼續存")

    # 桶3（= 長線佈局清單，環境差時改觀察）
    if b3_picks:
        top = b3_picks[:3]
        names = " / ".join(f"{r['stock_id']} {r['name']}（長{r.get('long_score',0)}）" for r in top)
        if _defensive:
            lines.append(f"桶3 逢低：👀 {names}")
            lines.append(f"  → 基本面好但環境差，先觀察不急進")
        else:
            lines.append(f"桶3 逢低：✓ {names}")
            lines.append(f"  → 基本面好+股價低，可以進場")
    else:
        lines.append("桶3 逢低：— 沒有佈局機會，4,000 繼續存")

    lines.append("")

    # ━━━ 展開清單（跟上面三桶是同一批資料）━━━

    # 桶2 展開：精選 + 其他綠燈（R8 新格式：進場時機 + 三欄價位 + tag）
    # streaks 用於 tag；前面已算好 streaks（min_streak=1）
    streaks_all = streaks

    if b2_picks and not _defensive:
        lines.append(f"🏆 桶2 精選（{len(b2_picks)} 檔）：")
        for r in b2_picks:
            cp = r.get("current_price", 0)
            atr = r.get("atr", 0)
            ma20 = r.get("ma20", 0)
            ma60 = r.get("ma60", 0)
            # R8：短線用 min(MA20, 2×ATR)，不再被 MA60 拉遠
            sl = _short_stop(cp, atr, ma20, ma60)
            icon, ideal_entry, _ = _entry_timing(r)
            tag = _build_tag(r, streaks_all)
            sc = _b2_score(r)

            # 三欄主行：代號 名稱 短分 時機
            line1 = f"  {r['stock_id']} {r['name']} 短{sc} {icon}"
            if tag:
                line1 += f" [{tag}]"
            lines.append(line1)

            # 子行：進場 / 停損 / 分批止贏
            if sl and cp and sl < cp:
                r_val = cp - sl
                tp1 = cp + r_val
                tp2 = cp + 2 * r_val
                entry_desc = f"進 {cp:.0f}" if icon != "🟡等拉回" else \
                    (f"等拉回 {ideal_entry:.0f}" if ideal_entry else "等拉回")
                sl_pct = (cp - sl) / cp * 100
                lines.append(
                    f"     {entry_desc} / 停損 {sl:.0f} (-{sl_pct:.1f}%) / 止贏 {tp1:.0f}→{tp2:.0f}→追蹤"
                )
        lines.append("")
    elif b2_picks and _defensive:
        # 空頭環境不展開名單，只給提醒
        lines.append(f"🏆 桶2 候選 {len(b2_picks)} 檔（環境空頭強制暫停，待轉正再動）")
        lines.append("")

    other_greens = [r for r in greens if r not in b2_picks]
    if other_greens and not _defensive:
        lines.append(f"🟢 其他綠燈（{len(other_greens)} 檔，動量偏弱等拉回）：")
        for r in other_greens[:5]:
            sk = streaks_all.get(r["stock_id"], {})
            days = sk.get("streak", 0) if sk.get("type") == "green" else 0
            streak_tag = f" 連{days}天" if days > 0 else ""
            icon, _, _ = _entry_timing(r)
            lines.append(f"  {r['stock_id']} {r['name']} 短{r['avg']}{streak_tag} {icon}")
        lines.append("")

    if not b2_picks and not greens:
        lines.append("💡 桶2 短線沒有候選（需短線綠燈+動量強），繼續存現金。")
        lines.append("")

    # 桶3 展開：長線佈局（R8：進場時機 + tag + 分批止贏文案）
    if b3_picks:
        lines.append(f"📉 桶3 佈局（{len(b3_picks)} 檔）：")
        for r in b3_picks[:5]:
            cp = r.get("current_price", 0)
            atr = r.get("atr", 0)
            ma60 = r.get("ma60", 0)
            sl = _long_stop(cp, atr, ma60)
            icon, ideal_entry, _ = _entry_timing(r)
            tag = _build_tag(r, streaks_all)

            line1 = f"  {r['stock_id']} {r['name']} 長{r.get('long_score',0)} {icon}"
            if tag:
                line1 += f" [{tag}]"
            lines.append(line1)

            if sl and cp and sl < cp:
                r_val = cp - sl
                tp1 = cp + r_val
                tp2 = cp + 2 * r_val
                entry_desc = f"進 {cp:.0f}" if icon != "🟡等拉回" else \
                    (f"等拉回 {ideal_entry:.0f}" if ideal_entry else "等拉回")
                sl_pct = (cp - sl) / cp * 100
                lines.append(
                    f"     {entry_desc} / 停損 {sl:.0f} (-{sl_pct:.1f}%) / 止贏 {tp1:.0f}→{tp2:.0f}→追蹤"
                )
        if len(b3_picks) > 5:
            lines.append(f"  ...還有 {len(b3_picks) - 5} 檔")
        lines.append("")

    # 觀察 + 偏空
    if watchlist:
        lines.append(f"🟡 觀察（{len(watchlist)} 檔）：")
        for r in watchlist[:3]:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        if len(watchlist) > 3:
            lines.append(f"  ...還有 {len(watchlist) - 3} 檔")
        lines.append("")

    if reds:
        lines.append(f"🔴 偏空（{len(reds)} 檔）— 不要碰")
        for r in reds[:3]:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        lines.append("")

    # ===== [R6] 持倉狀態（每天告訴你手上的股票要不要動）=====
    try:
        _vars = {}
        _hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
        with open(_hp, "r", encoding="utf-8") as _f:
            exec(_f.read(), _vars)
        _holdings = _vars.get("HOLDINGS", [])

        if _holdings:
            lines.append("━━━ 你的持倉 ━━━")
            lines.append("")
            for h in _holdings:
                sid = h["stock_id"]
                buy_price = h.get("buy_price", 0)
                stop_loss = h.get("stop_loss", 0)
                strategy = h.get("strategy", "longterm")
                try:
                    name = market.fetch_stock_name(sid)
                    price_df = market.fetch_stock_price(sid, days=150)
                    tech_r = technical.analyze(price_df)
                    cp = tech_r.get("current_price", 0)
                    ma60 = tech_r.get("ma60", 0)
                    ma20 = tech_r.get("ma20", 0)

                    pnl_pct = (cp / buy_price - 1) * 100 if buy_price > 0 else 0
                    # 停損距離
                    _sl_tag = ""
                    if stop_loss and cp:
                        sl_dist = (cp / stop_loss - 1) * 100
                        if sl_dist <= 0:
                            _sl_tag = f"｜🚨 已破停損 {stop_loss}"
                        elif sl_dist <= 5:
                            _sl_tag = f"｜⚠ 離停損 {sl_dist:.1f}%（{stop_loss}）"
                        else:
                            _sl_tag = f"｜停損 {stop_loss}"

                    # 止贏目標（R 倍數系統）— 賠錢時不顯示，專心看停損
                    _tp_tag = ""
                    if pnl_pct >= 0 and strategy != "hold":
                        _tp = risk_management.calc_partial_tp(
                            cp, buy_price, h.get("shares", 0),
                            entry_stop=stop_loss if stop_loss else None,
                        )
                        if _tp and "error" not in _tp:
                            tp1 = _tp["tp1_price"]
                            tp2 = _tp["tp2_price"]
                            if _tp["tp2_reached"]:
                                _tp_tag = f"｜🎯 已過止贏2（{tp2:.0f}）"
                            elif _tp["tp1_reached"]:
                                _tp_tag = f"｜🎯 已過止贏1（{tp1:.0f}），下一個={tp2:.0f}"
                            elif strategy == "short":
                                _tp_tag = f"｜止贏 {tp1:.0f}"
                            else:
                                _tp_tag = f"｜止贏 {tp1:.0f}/{tp2:.0f}"

                    # 判斷動作（依策略不同給不同建議）
                    below_ma60 = ma60 and cp and cp < ma60
                    above_ma20 = ma20 and cp and cp > ma20
                    above_ma60 = ma60 and cp and cp > ma60

                    if strategy == "hold":
                        # 桶1 0050：永遠不賣
                        lines.append(f"  {sid} {name}：{pnl_pct:+.1f}% — 桶1 持續定額，不動")

                    elif strategy == "short":
                        # 桶2 短線：止盈 + MA60 出場 + R8 時間停損
                        below_ma20 = ma20 and cp and cp < ma20

                        # R8：時間停損檢查（短線 10 天未達 +1R → 警告）
                        _time_tag = ""
                        try:
                            _buy_date = h.get("buy_date", "")
                            _eff_stop = stop_loss if stop_loss else cp * 0.92
                            _r_val = buy_price - _eff_stop
                            _cur_r = (cp - buy_price) / _r_val if _r_val > 0 else 0
                            _ts = risk_management.check_time_stop(
                                _buy_date, _cur_r, days_limit=10, min_r=1.0
                            )
                            if _ts["triggered"]:
                                _time_tag = f"｜⏰ {_ts['message']}"
                        except Exception:
                            pass

                        if below_ma60:
                            lines.append(f"  🚨 {sid} {name}：{pnl_pct:+.1f}% — 跌破 MA60，短線出場{_sl_tag}{_time_tag}")
                        elif pnl_pct >= 20:
                            lines.append(f"  💰 {sid} {name}：{pnl_pct:+.1f}% — 獲利 ≥20%，分批止盈：1/3 出、1/3 等 2R、1/3 追蹤停利{_sl_tag}{_tp_tag}")
                        elif pnl_pct >= 10 and below_ma20:
                            lines.append(f"  💰 {sid} {name}：{pnl_pct:+.1f}% — 獲利回吐跌破 MA20，建議止盈{_sl_tag}{_tp_tag}")
                        elif _time_tag:
                            lines.append(f"  ⏰ {sid} {name}：{pnl_pct:+.1f}%{_sl_tag}{_tp_tag}{_time_tag}")
                        elif above_ma20 and above_ma60:
                            lines.append(f"  ✅ {sid} {name}：{pnl_pct:+.1f}% — 趨勢正常，繼續抱{_sl_tag}{_tp_tag}")
                        elif above_ma60:
                            lines.append(f"  — {sid} {name}：{pnl_pct:+.1f}% — MA60 之上，持有{_sl_tag}{_tp_tag}")
                        else:
                            lines.append(f"  — {sid} {name}：{pnl_pct:+.1f}%{_sl_tag}{_tp_tag}")

                    else:
                        # 桶3 長線 / longterm：直接查基本面給結論
                        _fund_score = 5
                        try:
                            _h_per = market.fetch_per_pbr(sid)
                            _h_rev = market.fetch_monthly_revenue(sid)
                            _h_ind = market.fetch_stock_industry(sid)
                            if market.is_etf(sid):
                                _fund_score = fundamental.analyze_etf(price_df, None, _h_per).get("score", 5)
                            else:
                                _fund_score = fundamental.analyze(_h_per, _h_rev, _h_ind).get("score", 5)
                        except Exception:
                            pass

                        # R8：長線獲利 ≥2R 時改用 Chandelier Exit 追蹤
                        _chand_tag = ""
                        try:
                            _atr = tech_r.get("atr", 0)
                            _eff_stop = stop_loss if stop_loss else buy_price * 0.92
                            _r_val = buy_price - _eff_stop
                            _cur_r = (cp - buy_price) / _r_val if _r_val > 0 else 0
                            if _cur_r >= 2.0 and _atr > 0:
                                # 用現價當 peak 的近似（真實 peak 要另存）
                                _ch = risk_management.calc_chandelier_exit(cp, _atr, multiplier=3.0)
                                if _ch["chandelier_stop"] > 0:
                                    _chand_tag = f"｜🎯 追蹤停利 {_ch['chandelier_stop']:.0f}（Chandelier 3×ATR）"
                        except Exception:
                            pass

                        if below_ma60 and _fund_score < 5 and pnl_pct < -20:
                            lines.append(f"  🚨 {sid} {name}：{pnl_pct:+.1f}% — MA60 下 + 基本面轉弱（{_fund_score}分），考慮停損{_sl_tag}")
                        elif below_ma60 and _fund_score >= 5:
                            lines.append(f"  — {sid} {name}：{pnl_pct:+.1f}% — MA60 下但基本面還行（{_fund_score}分），繼續觀察{_sl_tag}{_tp_tag}")
                        elif below_ma60:
                            lines.append(f"  ⚠ {sid} {name}：{pnl_pct:+.1f}% — MA60 下，基本面 {_fund_score} 分{_sl_tag}{_tp_tag}")
                        elif above_ma20 and above_ma60:
                            lines.append(f"  ✅ {sid} {name}：{pnl_pct:+.1f}% — 趨勢正常{_sl_tag}{_tp_tag}{_chand_tag}")
                        elif above_ma60:
                            lines.append(f"  — {sid} {name}：{pnl_pct:+.1f}% — MA60 之上，持有{_sl_tag}{_tp_tag}{_chand_tag}")
                        else:
                            lines.append(f"  — {sid} {name}：{pnl_pct:+.1f}%（MA60 資料不足，無法判斷趨勢）{_sl_tag}{_tp_tag}")
                except Exception:
                    lines.append(f"  — {sid}：無法取得資料")
            lines.append("")
    except Exception:
        pass

    lines.append("📈 今日 Top 5：")
    for r in results[:5]:
        sig = SIGNAL_TEXT[r["overall"]]
        lines.append(f"  {r['stock_id']} {r['name']} {sig} {r['avg']}/10")

    lines.append("")
    lines.append(f"共掃描 {len(results)} 檔 ｜ 僅供參考")

    # ===== 系統驗證摘要（有資料才顯示）=====
    try:
        from validate import get_accuracy_summary
        accuracy_line = get_accuracy_summary()
        if accuracy_line:
            lines.append("")
            lines.append(f"📊 {accuracy_line}")
    except Exception:
        pass

    return "\n".join(lines)


def main():
    has_line = bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID)
    has_telegram = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    has_discord = bool(DISCORD_WEBHOOK_URL)

    if not has_line and not has_telegram and not has_discord:
        print()
        print("⚠ 尚未設定通知管道！")
        print()
        print("請到 config.py / 環境變數設定至少一種：")
        print("  DISCORD_WEBHOOK_URL（推薦，免費無上限）")
        print("  LINE_CHANNEL_ACCESS_TOKEN + LINE_USER_ID")
        print("  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
        print()
        sys.exit(1)

    print()
    print("=" * 50)

    channels = []
    if has_discord:
        channels.append("Discord")
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

    # 順便驗證過去的掃描記錄（靜默，有資料才會顯示在推播裡）
    try:
        from validate import validate_scan, load_validation
        import tracker as _tracker
        from datetime import datetime as _dt, timedelta as _td
        _today = _dt.now()
        for _d in _tracker.list_records():
            try:
                _scan_date = _dt.strptime(_d, "%Y-%m-%d")
                if (_today - _scan_date).days >= 10 and not load_validation(_d):
                    print(f"  📊 自動驗證 {_d} 的掃描記錄...", end="", flush=True)
                    _v = validate_scan(_d)
                    if _v:
                        print(f" ✓ 綠燈準度 {_v.get('green_accuracy', '—')}%")
                    else:
                        print(" —")
            except Exception:
                continue
    except Exception:
        pass

    message = format_message(results)

    print(f"\n📨 發送通知...\n")

    if has_discord:
        print("  Discord...", end="", flush=True)
        if send_discord(message):
            print(" ✅ 已發送")
        else:
            print(" ⚠ 失敗，請檢查 DISCORD_WEBHOOK_URL")

    if has_telegram:
        print("  Telegram...", end="", flush=True)
        if send_telegram(message):
            print(" ✅ 已發送")
        else:
            print(" ⚠ 失敗，請檢查 Token 和 Chat ID")

    print()


if __name__ == "__main__":
    main()
