#!/usr/bin/env python3
"""
互動式 LINE Bot 伺服器
啟動：python3 server.py
然後用 ngrok 公開：ngrok http 5000

使用方式（在 LINE 傳訊息給 Bot）：
  2330         → 個股分析報告
  掃描          → 觀察清單掃描
  比較 2330 2454 → 兩檔 PK
  趨勢          → 熱門題材
  說明          → 顯示使用方式
"""
import sys
import os
import hashlib
import hmac
import base64
import json
import re
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, abort
import requests

from config import (
    LINE_CHANNEL_ACCESS_TOKEN,
    LINE_CHANNEL_SECRET,
    LINE_USER_ID,
    TOTAL_BUDGET,
)
import market
import technical
import fundamental
import institutional
import news
import portfolio

app = Flask(__name__)

# 你原本的 webhook，不認識的訊息會轉發過去
ORIGINAL_WEBHOOK = "https://howard456.vercel.app/api/line/webhook"


# ===== LINE API =====

def verify_signature(body, signature):
    """驗證 LINE webhook 簽章"""
    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return signature == base64.b64encode(digest).decode("utf-8")


def reply_line(reply_token, text):
    """回覆 LINE 訊息"""
    # LINE 單則訊息上限 5000 字
    if len(text) > 5000:
        text = text[:4950] + "\n\n...（訊息過長，已截斷）"

    url = "https://api.line.me/v2/bot/message/reply"
    requests.post(url, headers={
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }, json={
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }, timeout=10)


def push_line(user_id, text):
    """主動推送 LINE 訊息"""
    if len(text) > 5000:
        text = text[:4950] + "\n\n...（訊息過長，已截斷）"

    url = "https://api.line.me/v2/bot/message/push"
    requests.post(url, headers={
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }, json={
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }, timeout=10)


# ===== 分析功能 =====

def do_check(stock_id):
    """執行個股分析，回傳文字報告"""
    name = market.fetch_stock_name(stock_id)
    industry = market.fetch_stock_industry(stock_id)
    price_df = market.fetch_stock_price(stock_id)
    inst_df = market.fetch_institutional(stock_id)
    per_df = market.fetch_per_pbr(stock_id)
    rev_df = market.fetch_monthly_revenue(stock_id)
    news_result = news.analyze(stock_id, name)

    tech = technical.analyze(price_df)
    fund = fundamental.analyze(per_df, rev_df, industry)
    inst = institutional.analyze(inst_df)

    scores = [tech["score"], fund["score"], inst["score"], news_result["score"]]
    avg = round(sum(scores) / len(scores), 1)

    if avg >= 7:
        overall = "🟢 綠燈"
    elif avg >= 4:
        overall = "🟡 黃燈"
    else:
        overall = "🔴 紅燈"

    # 組裝文字報告
    lines = [f"📊 {stock_id} {name} 分析報告", ""]

    sections = [
        ("技術面", tech),
        ("基本面", fund),
        ("籌碼面", inst),
        ("消息面", news_result),
    ]

    signal_map = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

    for label, data in sections:
        icon = signal_map[data["signal"]]
        lines.append(f"【{label}】{icon} {data['score']}/10")
        # 只放重點，不放所有細節（LINE 訊息不能太長）
        for d in data["details"]:
            if d.startswith(("✓", "✗", "⚠")):
                lines.append(f"  {d}")
        # AI 新聞總結
        if label == "消息面":
            for d in data["details"]:
                if "AI 判斷" in d:
                    lines.append(f"  {d}")

    lines.append("")
    lines.append(f"【綜合】{overall} {avg}/10")

    if avg >= 7:
        lines.append("→ 條件良好，可考慮佈局")
    elif avg >= 5.5:
        lines.append("→ 條件尚可，建議分批進場")
    elif avg >= 4:
        lines.append("→ 條件普通，建議觀望")
    else:
        lines.append("→ 偏空，不建議進場")

    if "current_price" in tech and "ma20" in tech:
        lines.append(f"📍 停損參考：20日均線 {tech['ma20']:.0f} 元")

    # 資金配置
    budget = TOTAL_BUDGET
    if budget > 0 and "current_price" in tech:
        suggestion = portfolio.suggest(avg, tech["current_price"], budget)
        if suggestion:
            lines.append("")
            if suggestion["lots"] > 0:
                lines.append(f"💰 建議買 {suggestion['lots']} 張（{suggestion['amount']:,.0f} 元）")
            elif suggestion["odd_shares"] > 0:
                lines.append(f"💰 建議買零股 {suggestion['odd_shares']} 股（{suggestion['amount']:,.0f} 元）")

    lines.append("")
    lines.append("⚠ 僅供參考，不構成投資建議")

    return "\n".join(lines)


def do_scan():
    """執行批次掃描，回傳文字摘要"""
    from watchlist import WATCHLIST
    import time

    all_stocks = []
    stock_sectors = {}
    for sector, codes in WATCHLIST.items():
        for code in codes:
            all_stocks.append(code)
            stock_sectors[code] = sector

    names = market.fetch_stock_names(all_stocks)

    results = []
    for stock_id in all_stocks:
        try:
            price_df = market.fetch_stock_price(stock_id)
            per_df = market.fetch_per_pbr(stock_id)
            inst_df = market.fetch_institutional(stock_id)
            rev_df = market.fetch_monthly_revenue(stock_id)
            industry = market.fetch_stock_industry(stock_id)

            tech = technical.analyze(price_df)
            fund = fundamental.analyze(per_df, rev_df, industry)
            inst = institutional.analyze(inst_df)

            avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)
            overall = "green" if avg >= 7 else ("yellow" if avg >= 4 else "red")

            results.append({
                "stock_id": stock_id,
                "name": names.get(stock_id, stock_id),
                "avg": avg,
                "overall": overall,
            })
        except Exception:
            pass
        time.sleep(0.2)

    results.sort(key=lambda x: x["avg"], reverse=True)

    signal_map = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    lines = ["📡 臺股雷達掃描結果", ""]

    greens = [r for r in results if r["avg"] >= 7]
    watch = [r for r in results if 6 <= r["avg"] < 7]
    reds = [r for r in results if r["avg"] < 4]

    if greens:
        lines.append("🟢 綠燈候選：")
        for r in greens:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        lines.append("")

    if watch:
        lines.append("🟡 值得關注：")
        for r in watch:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        lines.append("")

    if reds:
        lines.append("🔴 偏空：")
        for r in reds:
            lines.append(f"  {r['stock_id']} {r['name']} ({r['avg']}/10)")
        lines.append("")

    lines.append("📈 前 5 名：")
    for r in results[:5]:
        icon = signal_map[r["overall"]]
        lines.append(f"  {icon} {r['stock_id']} {r['name']} {r['avg']}/10")

    lines.append("")
    lines.append("⚠ 僅供參考，不構成投資建議")
    return "\n".join(lines)


def do_compare(id_a, id_b):
    """比較兩檔股票"""
    name_a = market.fetch_stock_name(id_a)
    name_b = market.fetch_stock_name(id_b)

    def score_stock(sid):
        industry = market.fetch_stock_industry(sid)
        price_df = market.fetch_stock_price(sid)
        per_df = market.fetch_per_pbr(sid)
        inst_df = market.fetch_institutional(sid)
        rev_df = market.fetch_monthly_revenue(sid)
        tech = technical.analyze(price_df)
        fund = fundamental.analyze(per_df, rev_df, industry)
        inst = institutional.analyze(inst_df)
        avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)
        return {"tech": tech["score"], "fund": fund["score"], "inst": inst["score"], "avg": avg}

    a = score_stock(id_a)
    b = score_stock(id_b)

    signal = lambda s: "🟢" if s >= 7 else ("🟡" if s >= 4 else "🔴")

    lines = [
        f"⚔ {id_a} {name_a} vs {id_b} {name_b}",
        "",
        f"{'面向':<6} {name_a:<6} {name_b}",
        "─" * 28,
        f"技術面  {signal(a['tech'])} {a['tech']:<6} {signal(b['tech'])} {b['tech']}",
        f"基本面  {signal(a['fund'])} {a['fund']:<6} {signal(b['fund'])} {b['fund']}",
        f"籌碼面  {signal(a['inst'])} {a['inst']:<6} {signal(b['inst'])} {b['inst']}",
        "─" * 28,
        f"綜合    {signal(a['avg'])} {a['avg']:<6} {signal(b['avg'])} {b['avg']}",
        "",
    ]

    if a["avg"] > b["avg"] + 1:
        lines.append(f"📊 {name_a} 目前條件明顯較優")
    elif b["avg"] > a["avg"] + 1:
        lines.append(f"📊 {name_b} 目前條件明顯較優")
    else:
        lines.append("📊 兩檔條件相近")

    lines.append("")
    lines.append("⚠ 僅供參考，不構成投資建議")
    return "\n".join(lines)


HELP_TEXT = """📊 臺股雷達 使用方式：

傳股票代號 → 個股分析
  例：2330

傳「掃描」→ 觀察清單掃描

傳「比較 代號 代號」→ PK
  例：比較 2330 2454

傳「說明」→ 顯示此訊息

⚠ 分析需要幾秒鐘，請稍候"""


# ===== Webhook =====

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    if not verify_signature(body, signature):
        abort(403)

    data = json.loads(body)

    # 檢查是不是股票相關的訊息
    is_ours = False
    for event in data.get("events", []):
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            text = event["message"]["text"].strip()
            if is_stock_command(text):
                is_ours = True
                break

    # 不是我們的指令 → 轉發給原本的 Vercel webhook
    if not is_ours:
        try:
            requests.post(
                ORIGINAL_WEBHOOK,
                data=request.get_data(),
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": request.headers.get("X-Line-Signature", ""),
                },
                timeout=10,
            )
        except Exception:
            pass
        return "OK"

    # 是我們的指令 → 處理
    for event in data.get("events", []):
        if event["type"] != "message" or event["message"]["type"] != "text":
            continue

        text = event["message"]["text"].strip()
        reply_token = event["replyToken"]
        user_id = event["source"].get("userId", "")

        def handle_async(text, user_id):
            try:
                result = process_command(text)
                if result:
                    push_line(user_id, result)
            except Exception as e:
                push_line(user_id, f"⚠ 分析時發生錯誤：{str(e)[:100]}")

        if text in ("說明", "help", "?", "？"):
            reply_line(reply_token, HELP_TEXT)
        else:
            reply_line(reply_token, "⏳ 分析中，請稍候...")
            thread = threading.Thread(target=handle_async, args=(text, user_id))
            thread.start()

    return "OK"


def is_stock_command(text):
    """判斷是不是股票相關的指令"""
    text = text.strip()
    if text in ("掃描", "scan", "雷達", "說明", "help", "?", "？"):
        return True
    if re.match(r"比較\s*\w+\s+\w+", text):
        return True
    if re.match(r"^\d{2,6}$", text):
        return True
    return False


def process_command(text):
    """解析使用者輸入，執行對應功能"""
    text = text.strip()

    # 掃描
    if text in ("掃描", "scan", "雷達"):
        return do_scan()

    # 比較
    compare_match = re.match(r"比較\s*(\w+)\s+(\w+)", text)
    if compare_match:
        return do_compare(compare_match.group(1), compare_match.group(2))

    # 股票代號（純數字，2-6 位）
    stock_match = re.match(r"^(\d{2,6})$", text)
    if stock_match:
        return do_check(stock_match.group(1))

    return None


# ===== 啟動 =====

if __name__ == "__main__":
    print()
    print("=" * 50)
    print(" 臺股雷達 LINE Bot 伺服器 ".center(50))
    print("=" * 50)
    print()
    print(" Bot 已啟動，等待 LINE 訊息...")
    print()
    print(" 下一步：")
    print("   1. 開另一個終端機視窗")
    print("   2. 執行：ngrok http 8080")
    print("   3. 複製 ngrok 給的 https 網址")
    print("   4. 到 LINE Developers Console")
    print("      → Messaging API → Webhook URL")
    print("      → 貼上：https://你的網址/webhook")
    print("      → 打開 Use webhook")
    print()
    print(" Ctrl+C 停止伺服器")
    print("=" * 50)
    print()

    app.run(port=8080, debug=False)
