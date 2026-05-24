#!/usr/bin/env python3
"""
0050 每日 Discord 推播
========================
策略已轉純 0050 DCA — 推播聚焦：
  1. 0050 收盤價 + 漲跌
  2. MA20/60/200 位置 + 拉伸度
  3. 52 週高/低距離
  4. 進場階級判讀（極熱/熱/正常/折價/恐慌）
  5. 根據階級給「看法」（不喊買賣）

由 GitHub Actions 每日台灣下午 3:30 後執行（cron 在 daily-scan.yml）。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import config
from notify import send_discord

FINMIND = "https://api.finmindtrade.com/api/v4/data"
STATE_FILE = Path(__file__).parent / "entry_signal_state.json"

# 0050 已知拆股：2025-06-18 起 1:4 拆股
SPLITS = [("2025-06-18", 4)]


def adjust_for_splits(data):
    """把拆股前的收盤價除以拆股倍數，讓技術指標跨拆股可比"""
    for split_date, ratio in SPLITS:
        for row in data:
            if row["date"] < split_date:
                row["close"] = row["close"] / ratio
    return data


def fetch_finmind(start, end):
    parts = []
    cur = datetime.strptime(start, "%Y-%m-%d")
    final = datetime.strptime(end, "%Y-%m-%d")
    while cur <= final:
        nxt = min(cur.replace(year=cur.year + 2), final)
        r = requests.get(FINMIND, params={
            "dataset": "TaiwanStockPrice", "data_id": "0050",
            "start_date": cur.strftime("%Y-%m-%d"),
            "end_date": nxt.strftime("%Y-%m-%d"),
            "token": config.FINMIND_TOKEN,
        }, timeout=30)
        data = r.json().get("data", [])
        parts.extend(data)
        cur = nxt.replace(day=nxt.day + 1) if nxt.day < 28 else nxt.replace(year=nxt.year + 2)
        if not data:
            break
    return parts


def fetch_yfinance():
    """FinMind 失敗時的備援"""
    import yfinance as yf
    t = yf.Ticker("0050.TW")
    h = t.history(period="2y")
    return [
        {"date": d.strftime("%Y-%m-%d"), "close": float(r["Close"])}
        for d, r in h.iterrows()
    ]


def get_price_data():
    """抓近 2 年 0050 資料，FinMind 優先，失敗用 yfinance"""
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now().replace(year=datetime.now().year - 2)).strftime("%Y-%m-%d")
    try:
        data = fetch_finmind(start, today)
        if data and len(data) > 200:
            return data, "FinMind"
    except Exception as e:
        print(f"FinMind 失敗：{e}")
    print("改用 yfinance...")
    return fetch_yfinance(), "yfinance"


def analyze(data):
    closes = [d["close"] for d in data]
    dates = [d["date"] for d in data]
    last = closes[-1]
    prev = closes[-2]
    chg = last - prev
    chg_pct = chg / prev * 100

    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    ma200 = sum(closes[-200:]) / 200

    high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    low_52w = min(closes[-252:]) if len(closes) >= 252 else min(closes)

    stretch = (last / ma200 - 1) * 100
    discount = (last / high_52w - 1) * 100
    above_low = (last / low_52w - 1) * 100

    return {
        "date": dates[-1], "price": last, "chg": chg, "chg_pct": chg_pct,
        "ma20": ma20, "ma60": ma60, "ma200": ma200,
        "high_52w": high_52w, "low_52w": low_52w,
        "stretch": stretch, "discount": discount, "above_low": above_low,
    }


def tier_view(stretch):
    """根據拉伸度給階級 + 看法"""
    if stretch > 40:
        return ("🔥 極熱", "5,000",
                "10 年首見極端位置。月扣降到 1/4，剩下 15,000 進戰備金。\n"
                "此時加碼風險最大 — 別被牛市情緒沖昏頭，紀律重於勝率。")
    if stretch > 30:
        return ("⚠️ 熱", "10,000",
                "拉伸偏高。月扣減半，10,000 留戰備金。\n"
                "技術面強但估值不便宜，續漲也好、回檔也罷，都按規則來。")
    if stretch > 15:
        return ("📈 偏熱", "15,000",
                "仍處多頭結構但偏高。月扣 3/4，留 5,000 戰備金。\n"
                "正常週期內的常態位置，繼續執行紀律。")
    if stretch > 0:
        return ("✅ 正常", "20,000",
                "標準扣款區間。月扣滿額 20,000。\n"
                "這是 DCA 最舒服的位置 — 不貴不便宜，買就對了。")
    if stretch > -10:
        return ("🎯 折價", "20,000 + 戰備金 1/6",
                "跌破年線！戰備金開始分 6 期出動。\n"
                "歷史上這種位置買進的勝率最高，恐懼最大時報酬最甜。")
    return ("💀 恐慌", "20,000 + 加速戰備金",
            "深度折價（年線下方 -10% 以上）。\n"
            "考慮加速戰備金部署。這就是 2008/2020 那種等了 10 年的機會。")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def build_message(a, src):
    arrow = "🔺" if a["chg"] > 0 else ("🔻" if a["chg"] < 0 else "➖")
    tier, action, view = tier_view(a["stretch"])

    # 均線位置
    above = []
    if a["price"] > a["ma20"]: above.append("MA20")
    if a["price"] > a["ma60"]: above.append("MA60")
    if a["price"] > a["ma200"]: above.append("MA200")
    pos = f"站上 {'/'.join(above)}" if above else "全部均線下方 ⚠️"

    msg = f"""**📊 0050 每日盤後 ({a['date']})**

**💰 收盤：{a['price']:.2f}** {arrow} {a['chg']:+.2f} ({a['chg_pct']:+.2f}%)

**📈 技術面**
• MA20  : {a['ma20']:.2f}
• MA60  : {a['ma60']:.2f}
• MA200 : {a['ma200']:.2f}  ← 拉伸 **{a['stretch']:+.1f}%**
• 52週高：{a['high_52w']:.2f}（距高 {a['discount']:+.1f}%）
• 52週低：{a['low_52w']:.2f}（距低 {a['above_low']:+.1f}%）
• 位置：{pos}

**🎯 階級：{tier}**
建議月扣：**{action}**

**💡 看法**
{view}
"""

    state = load_state()
    if state:
        sv = state["shares_owned"] * a["price"]
        msg += f"""
**📦 你的部位**
• 累計持股：{state['shares_owned']:.1f} 股（市值 {sv:,.0f}）
• 戰備金：{state['reserve']:,.0f}
"""

    msg += f"\n_資料來源：{src} ｜ DCA 紀律 > 預測_"
    return msg


def main():
    print("抓 0050 資料...")
    data, src = get_price_data()
    if not data or len(data) < 200:
        print("⚠️ 資料不足 200 筆，無法計算 MA200")
        sys.exit(1)
    print(f"  {len(data)} 筆（來源：{src}）")

    data = adjust_for_splits(data)
    a = analyze(data)
    msg = build_message(a, src)

    print("\n" + "=" * 50)
    print(msg)
    print("=" * 50)

    if "--dry-run" in sys.argv:
        print("\n(--dry-run 不送出)")
        return

    print("\n推送 Discord...", end="", flush=True)
    if send_discord(msg):
        print(" ✅")
    else:
        print(" ❌")
        sys.exit(1)


if __name__ == "__main__":
    main()
