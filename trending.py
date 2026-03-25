#!/usr/bin/env python3
"""
題材趨勢雷達 — 偵測當前臺股熱門題材
用法：python3 trending.py

你可以在下方 THEMES 字典裡自由新增題材和相關個股
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from news import count_news_heat, fetch_news
import market
import technical
import fundamental
import institutional

SIGNAL_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

# ===== 題材清單（歡迎自己新增）=====
THEMES = {
    "AI / 人工智慧": {
        "keywords": ["AI", "人工智慧", "ChatGPT", "GPU", "輝達", "NVIDIA"],
        "stocks": ["2330", "2454", "2382", "3231", "2357"],
    },
    "低軌衛星": {
        "keywords": ["低軌衛星", "Starlink", "衛星通訊", "LEO衛星"],
        "stocks": ["6285", "3704", "2345", "4977"],
    },
    "電動車 / EV": {
        "keywords": ["電動車", "EV", "特斯拉", "Tesla", "充電樁"],
        "stocks": ["2317", "3481", "6446", "2327"],
    },
    "半導體先進封裝": {
        "keywords": ["先進封裝", "CoWoS", "HBM", "封裝測試"],
        "stocks": ["2330", "3711", "2303", "6770"],
    },
    "綠能 / ESG": {
        "keywords": ["綠能", "太陽能", "風電", "ESG", "碳權"],
        "stocks": ["6244", "2374", "6464"],
    },
    "生技醫療": {
        "keywords": ["生技", "新藥", "醫療", "FDA"],
        "stocks": ["6547", "4743", "1760"],
    },
    "機器人": {
        "keywords": ["機器人", "人形機器人", "自動化"],
        "stocks": ["2317", "4506", "2049"],
    },
    "軍工 / 國防": {
        "keywords": ["軍工", "國防", "國機國造", "無人機"],
        "stocks": ["2208", "2634"],
    },
}


def scan_theme(name, config):
    """掃描一個題材的新聞熱度"""
    total_heat = 0
    for kw in config["keywords"]:
        heat = count_news_heat(kw)
        total_heat += heat
        time.sleep(0.3)
    return total_heat


def quick_score(stock_id, token=None):
    """快速取得單一股票綜合分數"""
    try:
        price_df = market.fetch_stock_price(stock_id)
        per_df = market.fetch_per_pbr(stock_id)
        inst_df = market.fetch_institutional(stock_id)
        rev_df = market.fetch_monthly_revenue(stock_id)
        ind = market.fetch_stock_industry(stock_id)

        tech = technical.analyze(price_df)
        if market.is_etf(stock_id):
            etf_info = market.fetch_etf_info(stock_id)
            fund = fundamental.analyze_etf(price_df, etf_info, per_df)
        else:
            fund = fundamental.analyze(per_df, rev_df, ind)
        inst = institutional.analyze(inst_df)

        avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)
        if avg >= 7:
            signal = "green"
        elif avg >= 4:
            signal = "yellow"
        else:
            signal = "red"
        return avg, signal
    except Exception:
        return None, "yellow"


def main():
    token = FINMIND_TOKEN or None

    print()
    print("=" * 60)
    print(" 題材趨勢雷達 ".center(60))
    print("=" * 60)
    print("\n 掃描熱門題材中，需要 1-2 分鐘...\n")

    # 1. 掃描每個題材的新聞熱度
    theme_scores = []
    for name, config in THEMES.items():
        print(f"  掃描「{name}」...", end="", flush=True)
        heat = scan_theme(name, config)
        print(f" 熱度 {heat}")
        theme_scores.append((name, config, heat))
        time.sleep(0.2)

    # 排序
    theme_scores.sort(key=lambda x: x[2], reverse=True)

    # 2. 顯示題材排名
    print()
    print("=" * 60)
    print()
    print(" 🔥 題材熱度排名：")
    print(" " + "─" * 50)

    max_heat = max(t[2] for t in theme_scores) if theme_scores else 1
    for rank, (name, config, heat) in enumerate(theme_scores, 1):
        bar_len = int(heat / max(max_heat, 1) * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        fire = "🔥" if heat >= max_heat * 0.7 else ("📈" if heat >= max_heat * 0.3 else "💤")
        print(f"  {rank}. {fire} {name:<16} {bar} ({heat} 則新聞)")

    # 3. 對最熱門的題材做個股分析
    top_themes = [t for t in theme_scores if t[2] > 0][:3]

    if top_themes:
        print()
        print(" " + "─" * 50)
        print()
        print(" 📊 熱門題材個股掃描：")

        # 收集所有需要掃描的股票（去重）
        all_stocks = set()
        for name, config, heat in top_themes:
            for sid in config["stocks"]:
                all_stocks.add((sid, name))

        # 批次查詢名稱
        stock_ids = [s[0] for s in all_stocks]
        names = fetch_stock_names(stock_ids, token)

        # 逐一分析
        for theme_name, config, heat in top_themes:
            print(f"\n  【{theme_name}】（熱度 {heat}）")

            for sid in config["stocks"]:
                sname = names.get(sid, sid)
                print(f"    {sid} {sname}...", end="", flush=True)
                score, signal = quick_score(sid, token)
                if score is not None:
                    icon = SIGNAL_ICON[signal]
                    print(f" {icon} {score}/10")
                else:
                    print(" ⚠ 失敗")
                time.sleep(0.3)
    else:
        print("\n  沒有偵測到明顯的熱門題材。")

    print()
    print("=" * 60)
    print(" ⚠ 以上僅供參考，題材熱度不等於投資價值。")
    print(" 💡 對有興趣的個股，用 python3 check.py <代號> 做完整檢查")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
