#!/usr/bin/env python3
"""
臺股雷達 — 網頁儀表板
啟動：python3 -m streamlit run app.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np

from config import TOTAL_BUDGET
import market
import technical
import fundamental
import valuation
import institutional
import news
import portfolio
import tracker
import streak
import sector_rotation
from scoring import STRATEGIES, weighted_score
from watchlist import WATCHLIST

st.set_page_config(page_title="投資雷達", page_icon="📊", layout="centered")

import ios_theme
ios_theme.apply()

SIGNAL_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def overall_signal(score):
    if score >= 7:
        return "green"
    elif score >= 4:
        return "yellow"
    return "red"


# ===== 側欄 =====
st.sidebar.title("📊 投資雷達")
st.sidebar.caption("臺股 + 美股")
page = st.sidebar.radio("功能", [
    "🏠 今日焦點",
    "🔍 個股分析",
    "📡 觀察清單掃描",
    "⚔ 股票 PK",
    "💼 持倉監控",
    "🔥 題材趨勢",
    "📈 歷史回測",
    "📋 訊號追蹤",
    "⭐ 自訂追蹤",
])

st.sidebar.markdown("---")

# 全域策略選擇
strategy_key = st.sidebar.selectbox(
    "投資策略",
    list(STRATEGIES.keys()),
    format_func=lambda k: f"{STRATEGIES[k]['label']} — {STRATEGIES[k]['description']}",
)

st.sidebar.markdown("---")
from config import FINMIND_TOKEN
if not FINMIND_TOKEN:
    st.sidebar.warning("台股資料限速中（未設 FinMind Token）。到 config.py 填入免費 Token 可提升 10 倍速度。")
st.sidebar.caption("⚠ 僅供參考，不構成投資建議")


# ===== 今日焦點 =====
if page == "🏠 今日焦點":
    st.title("🏠 今日焦點")
    st.caption("打開就知道今天該關注什麼 — 不用看 145 檔，系統幫你篩好了")

    # ===== 0050 多空燈號（最重要，放最上面）=====
    try:
        _0050_price = market.fetch_stock_price("0050", days=150)
        if not _0050_price.empty:
            _0050_tech = technical.analyze(_0050_price)
            _0050_score = _0050_tech["score"]
            _0050_details = _0050_tech["details"]
            _trend_up = any("趨勢向上" in d or "趨勢剛轉多" in d for d in _0050_details)
            _trend_down = any("趨勢向下" in d or "趨勢剛轉空" in d for d in _0050_details)
            _below_ma = any("跌破" in d and "均線" in d for d in _0050_details)

            if _trend_down and _below_ma and _0050_score <= 3:
                st.error(f"🚨 **0050 空頭警報** — 技術分 {_0050_score}/10，趨勢轉空。建議暫停定期定額、考慮減碼。")
            elif _trend_down and _0050_score <= 4:
                st.warning(f"⚠ **0050 多空轉換注意** — 技術分 {_0050_score}/10，趨勢偏空。留意後續。")
            elif _trend_up and _0050_score >= 7:
                st.success(f"✅ **0050 多頭確認** — 技術分 {_0050_score}/10，安心定期定額。")
            else:
                st.info(f"📊 **0050** — 技術分 {_0050_score}/10，盤整中。正常定期定額。")
    except Exception:
        pass

    st.markdown("---")

    # 讀最近的掃描記錄
    last_records = tracker.list_records()
    has_scan = bool(last_records)

    # 持倉狀況（本機讀 holdings.py，雲端讀 secrets）
    _holdings = []
    HOLDINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
    try:
        _vars = {}
        with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
            exec(f.read(), _vars)
        _holdings = _vars.get("HOLDINGS", [])
    except Exception:
        pass
    if not _holdings:
        try:
            import json as _json
            # 支援兩種格式：HOLDINGS_JSON 或 HOLDINGS.json
            raw = ""
            if "HOLDINGS_JSON" in st.secrets:
                raw = st.secrets["HOLDINGS_JSON"]
            elif "HOLDINGS" in st.secrets and "json" in st.secrets["HOLDINGS"]:
                raw = st.secrets["HOLDINGS"]["json"]
            if raw:
                _holdings = _json.loads(raw)
        except Exception:
            _holdings = []

    if _holdings:
        st.markdown("### 持倉狀況")
        from monitor import check_holding

        # 每檔持倉根據類型顯示不同評分
        for h in _holdings:
            try:
                r = check_holding(h)
                sid = r["stock_id"]
                pnl = f"{r['pnl_pct']:+.1f}%"

                # 根據 strategy 欄位決定顯示什麼
                strat = h.get("strategy", "longterm")
                stop_warnings = [w for w in r["warnings"] if "停損" in w or "觸及" in w]

                if strat == "hold":
                    # 買進持有：只看趨勢方向
                    _p = market.fetch_stock_price(sid, days=150)
                    _t = technical.analyze(_p) if not _p.empty else {"details": [], "score": 5}
                    _tu = any("趨勢向上" in d for d in _t["details"])
                    _td = any("趨勢向下" in d or "趨勢剛轉空" in d for d in _t["details"])
                    if stop_warnings:
                        st.error(f"**{sid} {r['name']}**　損益 {pnl}")
                        for w in stop_warnings:
                            st.caption(f"　　{w}")
                    elif _td:
                        st.warning(f"**{sid} {r['name']}**　損益 {pnl}　⚠ 趨勢偏空，留意")
                    elif _tu:
                        st.success(f"**{sid} {r['name']}**　損益 {pnl}　✅ 趨勢向上，安心持有")
                    else:
                        st.info(f"**{sid} {r['name']}**　損益 {pnl}　📊 盤整中")

                elif strat == "short":
                    # 短線：用短線綜合評分
                    avg_score = r["avg"]
                    if stop_warnings:
                        st.error(f"**{sid} {r['name']}**　損益 {pnl}　短線 {avg_score}/10")
                        for w in stop_warnings:
                            st.caption(f"　　{w}")
                    elif avg_score >= 7:
                        st.success(f"**{sid} {r['name']}**　損益 {pnl}　短線 {avg_score}/10 — 強勢")
                    elif avg_score >= 4:
                        st.info(f"**{sid} {r['name']}**　損益 {pnl}　短線 {avg_score}/10 — 觀望")
                    else:
                        st.warning(f"**{sid} {r['name']}**　損益 {pnl}　短線 {avg_score}/10 — 考慮出場")

                else:
                    # 長線佈局：用長線評分
                    _p = market.fetch_stock_price(sid)
                    _per = market.fetch_per_pbr(sid)
                    _rev = market.fetch_monthly_revenue(sid)
                    _ind = market.fetch_stock_industry(sid)
                    _long = valuation.analyze_longterm(_per, _rev, _p, _ind)
                    long_score = _long["score"]

                    if stop_warnings:
                        st.error(f"**{sid} {r['name']}**　損益 {pnl}　長線 {long_score}/10")
                        for w in stop_warnings:
                            st.caption(f"　　{w}")
                    elif long_score >= 7:
                        st.success(f"**{sid} {r['name']}**　損益 {pnl}　長線 {long_score}/10 — 基本面良好")
                    elif long_score >= 4:
                        st.info(f"**{sid} {r['name']}**　損益 {pnl}　長線 {long_score}/10 — 觀望中")
                    else:
                        st.warning(f"**{sid} {r['name']}**　損益 {pnl}　長線 {long_score}/10 — 基本面轉弱")
            except Exception:
                pass

    st.markdown("---")

    if has_scan:
        # 從最近一次掃描找亮點
        record = tracker.load_record(last_records[0])
        if record:
            results = record["results"]
            scan_date = record["date"]

            greens = [r for r in results if r["avg"] >= 7]
            watch = [r for r in results if 6 <= r["avg"] < 7]
            reds = [r for r in results if r["avg"] < 4]

            st.markdown(f"### 📡 最近掃描（{scan_date}）")

            if greens:
                st.markdown("**🟢 短線綠燈：**")
                for r in sorted(greens, key=lambda x: x["avg"], reverse=True):
                    st.markdown(f"- **{r['stock_id']} {r['name']}**（短線 {r['avg']}/10）— {r.get('sector', '')}")
                st.caption("→ 點左邊「個股分析」輸入代號看完整報告")
            else:
                st.info("目前沒有短線 7 分以上的綠燈股，建議耐心等待。")

            # 長線佈局機會（從掃描資料中找短線低但基本面可能好的）
            # 這裡只有短線分數，用 tech < 4 但 fund >= 6 來近似
            long_candidates = [r for r in results if r.get("avg", 0) < 5 and r.get("fund", 0) >= 7]
            if long_candidates:
                with st.expander(f"📉 可能的長線佈局機會（{len(long_candidates)} 檔）— 短線弱但基本面好"):
                    for r in sorted(long_candidates, key=lambda x: x.get("fund", 0), reverse=True):
                        st.markdown(f"- {r['stock_id']} {r['name']}（短線 {r['avg']}/10，基本面 {r.get('fund', '?')}/10）")
                    st.caption("到「個股分析」切換「長線佈局」策略看完整評估")

            if watch:
                with st.expander(f"🟡 值得留意（{len(watch)} 檔）"):
                    for r in sorted(watch, key=lambda x: x["avg"], reverse=True):
                        st.markdown(f"- {r['stock_id']} {r['name']}（{r['avg']}/10）")

            if reds:
                with st.expander(f"🔴 偏空（{len(reds)} 檔）— 短線不要碰"):
                    for r in sorted(reds, key=lambda x: x["avg"]):
                        st.markdown(f"- {r['stock_id']} {r['name']}（{r['avg']}/10）")

            # 板塊快覽
            st.markdown("### 📊 板塊強弱")
            import pandas as _pd
            sector_scores = {}
            for r in results:
                s = r.get("sector", "未分類")
                if s not in sector_scores:
                    sector_scores[s] = []
                sector_scores[s].append(r["avg"])

            sector_avg = {s: round(sum(v) / len(v), 1) for s, v in sector_scores.items()}
            sector_df = _pd.Series(sector_avg).sort_values(ascending=False)
            st.bar_chart(sector_df)

    else:
        st.warning("還沒有掃描記錄。先到「📡 觀察清單掃描」跑一次，或等每天 15:30 自動排程。")

    # 準確率快覽（如果有歷史記錄的話）
    if has_scan and len(last_records) >= 2:
        st.markdown("---")
        st.markdown("### 🎯 系統準不準？")
        older_date = last_records[1] if len(last_records) >= 2 else None
        if older_date:
            try:
                review = tracker.review_accuracy(older_date, market.fetch_stock_price, 10)
                if review and review["total"] > 0:
                    acc = review["accuracy"]
                    if acc >= 70:
                        st.success(f"{older_date} 的掃描，10 天後驗證準確率 **{acc}%**（{review['correct']}/{review['total']}）")
                    elif acc >= 50:
                        st.warning(f"{older_date} 的掃描，10 天後驗證準確率 **{acc}%**（{review['correct']}/{review['total']}）")
                    else:
                        st.error(f"{older_date} 的掃描，10 天後驗證準確率 **{acc}%**（{review['correct']}/{review['total']}）")
                    st.caption("→ 到「訊號追蹤」看逐筆驗證明細")
            except Exception:
                pass

    # ===== 連續訊號 =====
    try:
        streaks = streak.detect_streaks(min_streak=2)
        if streaks:
            st.markdown("---")
            st.markdown("### 🔥 連續訊號")
            greens = {k: v for k, v in streaks.items() if v["type"] == "green"}
            reds = {k: v for k, v in streaks.items() if v["type"] == "red"}

            if greens:
                for sid, info in sorted(greens.items(), key=lambda x: x[1]["streak"], reverse=True):
                    st.success(f"🟢 **{sid} {info['name']}** 連續 {info['streak']} 天綠燈（平均 {info['avg_score']}/10）")
                st.caption("連續 3 天以上綠燈 → 短線進場訊號")

            if reds:
                for sid, info in sorted(reds.items(), key=lambda x: x[1]["streak"], reverse=True):
                    st.error(f"🔴 **{sid} {info['name']}** 連續 {info['streak']} 天紅燈（平均 {info['avg_score']}/10）")
    except Exception:
        pass

    # ===== 產業輪動 =====
    try:
        rotation = sector_rotation.detect_rotation()
        if rotation:
            st.markdown("---")
            st.markdown("### 🔄 產業輪動")
            hot = [r for r in rotation if r["change"] > 0][:3]
            cold = [r for r in rotation if r["change"] < 0][:3]

            if hot:
                for r in hot:
                    st.success(f"📈 **{r['sector']}** {r['label']}（{r['previous_avg']} → {r['current_avg']}，{r['change']:+.1f}）")
            if cold:
                for r in cold:
                    st.error(f"📉 **{r['sector']}** {r['label']}（{r['previous_avg']} → {r['current_avg']}，{r['change']:+.1f}）")

            if not hot and not cold:
                st.info("目前各產業分數變化不大，沒有明顯輪動。")
    except Exception:
        pass

    st.markdown("---")
    st.markdown("### 💡 今天該做什麼？")
    st.markdown("""
1. 看上面有沒有 🟢 綠燈股 → 有的話點「個股分析」深入看
2. 🔥 連續訊號 → 連續 3 天綠燈 = 短線進場訊號
3. 🔄 產業輪動 → 升溫的產業裡找機會
4. 持倉有 🚨 警告 → 認真評估要不要處理
5. 都沒事 → 關掉，明天再來看
    """)


# ===== 個股分析 =====
elif page == "🔍 個股分析":
    st.title("🔍 個股分析")

    col1, col2 = st.columns([2, 1])
    with col1:
        stock_id = st.text_input("股票代號", value="2330", placeholder="臺股：2330 ｜ 美股：TSLA, AAPL, NVDA")
    with col2:
        budget = st.number_input("投資預算（選填）", value=TOTAL_BUDGET, step=100000, format="%d")

    if st.button("開始分析", type="primary", use_container_width=True):
        stock_id = stock_id.strip().upper()
        is_us = market.is_us(stock_id)
        etf = market.is_etf(stock_id)

        with st.spinner("抓取資料中..."):
            name = market.fetch_stock_name(stock_id)
            ind = market.fetch_stock_industry(stock_id)
            price_df = market.fetch_stock_price(stock_id)
            inst_df = market.fetch_institutional(stock_id)
            per_df = market.fetch_per_pbr(stock_id)
            rev_df = market.fetch_monthly_revenue(stock_id)
            news_result = news.analyze(stock_id, name)
            etf_info = market.fetch_etf_info(stock_id) if etf else None

        with st.spinner("分析中..."):
            tech = technical.analyze(price_df)
            if etf:
                fund = fundamental.analyze_etf(price_df, etf_info, per_df)
            elif strategy_key == "longterm":
                # 長線佈局：用專用評估，不看短期漲跌
                fund = valuation.analyze_longterm(per_df, rev_df, price_df, ind)
            else:
                fund = fundamental.analyze(per_df, rev_df, ind)
            inst = institutional.analyze(inst_df)

        avg, strategy_info = weighted_score(
            tech["score"], fund["score"], inst["score"], news_result["score"], strategy_key,
            is_us=is_us,
        )
        signal = overall_signal(avg)

        st.markdown(f"## {stock_id} {name}")
        if ind:
            st.caption(f"產業：{ind} ｜ 策略：{strategy_info['label']}")

        # 評分區 — 一目了然的結論
        st.markdown(f"## {SIGNAL_EMOJI[signal]} {avg}/10")

        if avg >= 7:
            st.success("各面向條件良好，可以考慮開始建倉（先買一部分就好）。")
        elif avg >= 5.5:
            st.warning("條件還行但不算突出。已持有可以繼續抱，還沒買建議等分數更高再進。")
        elif avg >= 4:
            st.info("目前條件普通偏弱。建議放觀察清單就好，不急著進場。")
        else:
            st.error("目前條件偏差。持有中考慮減碼，還沒買不建議現在進場。")

        w = strategy_info["weights"]
        st.caption(
            f"策略：{strategy_info['label']} ｜ "
            f"權重：技術{w['tech']:.0%} 基本{w['fund']:.0%} "
            f"籌碼{w['inst']:.0%} 消息{w['news']:.0%}"
        )

        with st.expander("這些分數怎麼看？"):
            st.markdown("""
- **技術面**：股價走勢和成交量，判斷現在是漲勢還是跌勢
- **基本面**：公司賺不賺錢、股價貴不貴（本益比、營收）
- **籌碼面**：法人（外資、投信）最近在買還是賣
- **消息面**：近期新聞是正面還是負面
- **7 分以上** = 條件好，可以考慮 ｜ **4 分以下** = 條件差，先不碰
            """)

        # K 線圖
        if not price_df.empty:
            chart_df = price_df.sort_values("date").tail(60).copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"])
            chart_df["close"] = chart_df["close"].astype(float)
            chart_df = chart_df.set_index("date")
            st.markdown("### 近 60 日走勢")
            st.line_chart(chart_df["close"])

        # 四面向
        st.markdown("### 四面向分析")
        sections = [
            ("技術面", tech),
            ("基本面", fund),
            ("籌碼面", inst),
            ("消息面", news_result),
        ]
        cols = st.columns(4)
        for i, (label, data) in enumerate(sections):
            with cols[i]:
                emoji = SIGNAL_EMOJI[data["signal"]]
                st.markdown(f"**{emoji} {label}**")
                st.markdown(f"### {data['score']}/10")
                for d in data["details"]:
                    if d.strip():
                        st.caption(d)

        # ===== 白話結論（自動生成，取代問 Claude）=====
        st.markdown("### 📝 白話結論")

        # 算長線分數
        if not etf and strategy_key != "longterm":
            _long_r = valuation.analyze_longterm(per_df, rev_df, price_df, ind)
            _long_s = _long_r["score"]
        elif strategy_key == "longterm":
            _long_s = fund["score"]
        else:
            _long_s = 5

        # 矛盾偵測
        _short_good = avg >= 7
        _long_good = _long_s >= 7
        _short_bad = avg < 4
        _long_bad = _long_s < 4

        conclusions = []

        if _short_good and _long_good:
            conclusions.append(f"短線 {avg} + 長線 {_long_s} 都好，**各方面條件都到位**。如果你有閒錢，這檔值得認真研究。")
        elif _short_good and not _long_good:
            conclusions.append(f"短線 {avg} 好但長線只有 {_long_s}，**短線在漲但基本面撐不久**。要買就短打快跑，不適合長抱。")
        elif not _short_good and _long_good:
            conclusions.append(f"短線 {avg} 弱但長線 {_long_s} 好，**基本面好但股價還在跌**。適合逢低佈局，但要有耐心等回升。")
        elif _short_bad and _long_bad:
            conclusions.append(f"短線 {avg} + 長線 {_long_s} 都差，**現在不適合碰**。")
        else:
            conclusions.append(f"短線 {avg} + 長線 {_long_s}，**沒有明確訊號**，建議觀望。")

        # 營收動能
        for d in (fund["details"] if strategy_key != "longterm" else []):
            pass
        if strategy_key == "longterm" or not etf:
            _lr = valuation.analyze_longterm(per_df, rev_df, price_df, ind) if strategy_key != "longterm" else {"details": fund.get("details", [])}
            for d in _lr.get("details", []):
                if "見頂" in d:
                    conclusions.append("⚠ **營收動能見頂**，高峰可能已過，小心追高。")
                    break
                elif "加速" in d:
                    conclusions.append("✓ **營收正在加速**，成長力道還在。")
                    break

        # 52 週位置
        if not price_df.empty:
            _closes = price_df["close"].astype(float)
            _pos = (_closes.iloc[-1] - _closes.min()) / (_closes.max() - _closes.min()) * 100 if _closes.max() > _closes.min() else 50
            if _pos > 85:
                conclusions.append(f"⚠ 股價在 52 週高點附近（{_pos:.0f}%），**追高風險大**。")
            elif _pos < 20:
                conclusions.append(f"✓ 股價在 52 週低點（{_pos:.0f}%），**如果基本面沒壞，可能是好買點**。")

        # 跟持倉的關聯
        try:
            _vars2 = {}
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py"), "r") as _f:
                exec(_f.read(), _vars2)
            _my_holdings = _vars2.get("HOLDINGS", [])
            _my_sectors = set()
            for _h in _my_holdings:
                _my_sectors.add(market.fetch_stock_industry(_h["stock_id"]))
            if ind and ind in _my_sectors:
                conclusions.append(f"⚠ 你已經持有同產業的股票，買這檔等於**加碼同一個方向**，風險集中。")
        except Exception:
            pass

        for c in conclusions:
            st.markdown(c)

        # 資金配置
        if budget > 0 and "current_price" in tech:
            suggestion = portfolio.suggest(avg, tech["current_price"], budget)
            st.markdown("### 💰 資金配置建議")
            if suggestion:
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("投資信心", suggestion["conviction"])
                with c2:
                    if suggestion["lots"] > 0:
                        st.metric("建議買入", f"{suggestion['lots']} 張")
                    elif suggestion["odd_shares"] > 0:
                        st.metric("建議買入", f"{suggestion['odd_shares']} 股（零股）")
                with c3:
                    st.metric("投入金額", f"{suggestion['amount']:,.0f} 元")
            else:
                st.info("目前評分偏低，不建議進場配置。")


# ===== 觀察清單掃描 =====
elif page == "📡 觀察清單掃描":
    st.title("📡 觀察清單掃描")

    if st.button("開始掃描", type="primary", use_container_width=True):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_stocks = []
        stock_sectors = {}
        for sector, codes in WATCHLIST.items():
            for code in codes:
                all_stocks.append(code)
                stock_sectors[code] = sector

        names = market.fetch_stock_names(all_stocks)
        total = len(all_stocks)
        progress = st.progress(0, text="載入中...")
        results = []

        def _scan_one(stock_id):
            """單一股票掃描（在線程中執行）"""
            sname = names.get(stock_id, stock_id)
            price_df = market.fetch_stock_price(stock_id)
            per_df = market.fetch_per_pbr(stock_id)
            inst_df = market.fetch_institutional(stock_id)
            rev_df = market.fetch_monthly_revenue(stock_id)
            ind = market.fetch_stock_industry(stock_id)
            etf = market.is_etf(stock_id)

            tech = technical.analyze(price_df)
            if etf:
                etf_info = market.fetch_etf_info(stock_id)
                fund = fundamental.analyze_etf(price_df, etf_info, per_df)
            else:
                fund = fundamental.analyze(per_df, rev_df, ind)
            inst_result = institutional.analyze(inst_df)

            avg, _ = weighted_score(
                tech["score"], fund["score"], inst_result["score"], 5.0, strategy_key,
                is_us=market.is_us(stock_id),
            )
            signal = overall_signal(avg)

            # 長線分數
            if etf:
                long_score = fund["score"]  # ETF 已經是專用評估
            else:
                long_result = valuation.analyze_longterm(per_df, rev_df, price_df, ind)
                long_score = long_result["score"]

            return {
                "代號": stock_id,
                "名稱": sname,
                "板塊": stock_sectors[stock_id],
                "技術": tech["score"],
                "基本": fund["score"],
                "籌碼": inst_result["score"],
                "短線": avg,
                "長線": long_score,
                "訊號": SIGNAL_EMOJI[signal],
            }

        done_count = 0
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_scan_one, sid): sid for sid in all_stocks}
            for future in as_completed(futures):
                done_count += 1
                progress.progress(done_count / total, text=f"已完成 {done_count}/{total}...")
                try:
                    results.append(future.result())
                except Exception:
                    pass

        progress.empty()

        if results:
            df = pd.DataFrame(results).sort_values("短線", ascending=False)

            # 短線綠燈
            greens = df[df["短線"] >= 7]
            watch = df[(df["短線"] >= 6) & (df["短線"] < 7)]
            reds = df[df["短線"] < 4]

            # 長線佈局機會（短線低但長線高 = 逢低佈局）
            long_opps = df[(df["長線"] >= 7) & (df["短線"] < 7)].sort_values("長線", ascending=False)

            # 短線綠燈但長線低 = 矛盾警告
            contradictions = df[(df["短線"] >= 7) & (df["長線"] <= 5)]

            if not greens.empty:
                st.success(f"🟢 短線綠燈（{len(greens)} 檔）")
                st.dataframe(greens, use_container_width=True, hide_index=True, height=400)

                if not contradictions.empty:
                    st.warning(f"⚠ 其中 {len(contradictions)} 檔短線強但長線弱（基本面撐不久）：{', '.join(contradictions['代號'].tolist())}")

            if not long_opps.empty:
                st.info(f"📉 長線佈局機會（{len(long_opps)} 檔）— 短線弱但基本面好，逢低佈局")
                st.dataframe(long_opps, use_container_width=True, hide_index=True, height=400)

            if not watch.empty:
                st.warning(f"🟡 短線值得關注（{len(watch)} 檔）")
                st.dataframe(watch, use_container_width=True, hide_index=True, height=400)
            if not reds.empty:
                st.error(f"🔴 偏空警示（{len(reds)} 檔）")
                st.dataframe(reds, use_container_width=True, hide_index=True, height=min(400, len(reds) * 38 + 40))

            st.markdown("### 完整排名")
            st.dataframe(df, use_container_width=True, hide_index=True, height=400)

            st.markdown("### 板塊強弱")
            sector_df = df.groupby("板塊")["短線"].mean().round(1).sort_values(ascending=False)
            st.bar_chart(sector_df)

            # 儲存訊號
            try:
                scan_results = [
                    {"stock_id": r["代號"], "name": r["名稱"], "sector": r["板塊"],
                     "tech": r["技術"], "fund": r["基本"], "inst": r["籌碼"],
                     "avg": r["短線"], "overall": overall_signal(r["短線"])}
                    for r in results
                ]
                filepath = tracker.save_scan(scan_results)
                st.caption(f"📝 訊號已記錄：{filepath}")
            except Exception:
                pass


# ===== 股票 PK =====
elif page == "⚔ 股票 PK":
    st.title("⚔ 股票 PK")

    col1, col2 = st.columns(2)
    with col1:
        id_a = st.text_input("股票 A", value="2330")
    with col2:
        id_b = st.text_input("股票 B", value="2454")

    if st.button("開始比較", type="primary", use_container_width=True):
        def analyze_one(sid):
            nm = market.fetch_stock_name(sid)
            ind = market.fetch_stock_industry(sid)
            price_df = market.fetch_stock_price(sid)
            per_df = market.fetch_per_pbr(sid)
            inst_df = market.fetch_institutional(sid)
            rev_df = market.fetch_monthly_revenue(sid)
            t = technical.analyze(price_df)
            if market.is_etf(sid):
                etf_info = market.fetch_etf_info(sid)
                f = fundamental.analyze_etf(price_df, etf_info, per_df)
            else:
                f = fundamental.analyze(per_df, rev_df, ind)
            ins = institutional.analyze(inst_df)
            avg, _ = weighted_score(t["score"], f["score"], ins["score"], 5.0, strategy_key,
                                   is_us=market.is_us(sid))
            return nm, t["score"], f["score"], ins["score"], avg

        with st.spinner("分析中..."):
            na, ta, fa, ia, avg_a = analyze_one(id_a)
            nb, tb, fb, ib, avg_b = analyze_one(id_b)

        compare_df = pd.DataFrame({
            "面向": ["技術面", "基本面", "籌碼面", "綜合（加權）"],
            f"{id_a} {na}": [ta, fa, ia, avg_a],
            f"{id_b} {nb}": [tb, fb, ib, avg_b],
        })
        st.dataframe(compare_df, use_container_width=True, hide_index=True, height=400)

        chart_data = pd.DataFrame({
            na: [ta, fa, ia], nb: [tb, fb, ib],
        }, index=["技術面", "基本面", "籌碼面"])
        st.bar_chart(chart_data)

        if avg_a > avg_b + 1:
            st.success(f"📊 {na} 條件明顯較優（{avg_a} vs {avg_b}）")
        elif avg_b > avg_a + 1:
            st.success(f"📊 {nb} 條件明顯較優（{avg_b} vs {avg_a}）")
        else:
            st.info(f"📊 兩檔條件相近（{avg_a} vs {avg_b}）")


# ===== 持倉監控 =====
elif page == "💼 持倉監控":
    st.title("💼 持倉監控")

    import correlation
    import json as _json

    HOLDINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")

    def _load_holdings():
        """從 holdings.py 讀取持倉"""
        try:
            # 重新讀取檔案（避免 import cache）
            _vars = {}
            with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
                exec(f.read(), _vars)
            return _vars.get("HOLDINGS", [])
        except Exception:
            return []

    def _save_holdings(holdings):
        """儲存持倉到 holdings.py"""
        lines = ['"""', '你的持倉清單', '"""', '', 'HOLDINGS = [']
        for h in holdings:
            parts = []
            parts.append(f'"stock_id": "{h["stock_id"]}"')
            parts.append(f'"buy_price": {h["buy_price"]}')
            parts.append(f'"shares": {h["shares"]}')
            parts.append(f'"buy_date": "{h["buy_date"]}"')
            parts.append(f'"stop_loss": {h.get("stop_loss", 0)}')
            lines.append("    {" + ", ".join(parts) + "},")
        lines.append("]")
        lines.append("")
        with open(HOLDINGS_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    HOLDINGS = _load_holdings()

    # ===== 新增持倉表單 =====
    with st.expander("➕ 新增 / 修改持倉", expanded=not HOLDINGS):
        with st.form("add_holding"):
            st.markdown("**新增一筆持倉**")
            fc1, fc2 = st.columns(2)
            with fc1:
                new_id = st.text_input("股票代號", placeholder="例：2330")
                new_price = st.number_input("買入價（元）", min_value=0.0, step=1.0, format="%.1f")
            with fc2:
                new_shares = st.number_input("股數", min_value=0, step=100, value=1000)
                new_date = st.date_input("買入日期")

            # 自動建議停損價
            suggested_stop = round(new_price * 0.92, 1) if new_price > 0 else 0.0
            st.caption(f"建議停損：{suggested_stop}（買入價 -8%）")
            new_stop = st.number_input("停損價", min_value=0.0, step=1.0, format="%.1f", value=suggested_stop)
            submitted = st.form_submit_button("新增", use_container_width=True)

            if submitted and new_id and new_price > 0 and new_shares > 0:
                if new_stop == 0:
                    new_stop = suggested_stop
                HOLDINGS.append({
                    "stock_id": new_id.strip(),
                    "buy_price": new_price,
                    "shares": new_shares,
                    "buy_date": new_date.strftime("%Y-%m-%d"),
                    "stop_loss": new_stop,
                })
                _save_holdings(HOLDINGS)
                st.success(f"已新增 {new_id}！停損設在 {new_stop}（-{(1 - new_stop/new_price)*100:.0f}%）")
                st.rerun()

    # 顯示現有持倉 + 刪除按鈕
    if HOLDINGS:
        st.markdown("### 目前持倉（可直接編輯）")
        changed = False
        for idx, h in enumerate(HOLDINGS):
            with st.expander(f"📌 {h['stock_id']}　買 {h['buy_price']}　{h['shares']} 股　停損 {h.get('stop_loss', 0)}"):
                ec1, ec2 = st.columns(2)
                with ec1:
                    new_bp = st.number_input("買入價", value=float(h["buy_price"]), step=1.0, key=f"bp_{idx}", format="%.1f")
                    new_sh = st.number_input("股數", value=int(h["shares"]), step=100, key=f"sh_{idx}")
                with ec2:
                    new_sl = st.number_input("停損價（0=不設）", value=float(h.get("stop_loss", 0)), step=1.0, key=f"sl_{idx}", format="%.1f")
                    new_dt = st.text_input("買入日期", value=h["buy_date"], key=f"dt_{idx}")

                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("💾 儲存修改", key=f"save_{idx}", use_container_width=True):
                        HOLDINGS[idx]["buy_price"] = new_bp
                        HOLDINGS[idx]["shares"] = new_sh
                        HOLDINGS[idx]["stop_loss"] = new_sl
                        HOLDINGS[idx]["buy_date"] = new_dt
                        _save_holdings(HOLDINGS)
                        st.success("已儲存！")
                        changed = True
                with bc2:
                    if st.button("🗑 刪除", key=f"del_{idx}", use_container_width=True):
                        HOLDINGS.pop(idx)
                        _save_holdings(HOLDINGS)
                        st.rerun()

            if changed:
                st.rerun()

        st.markdown("---")

    if not HOLDINGS:
        st.info("還沒有持倉，用上面的表單新增吧。")
    else:
        if st.button("檢查持倉", type="primary", use_container_width=True):
            from monitor import check_holding

            progress = st.progress(0, text="檢查中...")
            results = []

            for i, h in enumerate(HOLDINGS):
                progress.progress((i + 1) / len(HOLDINGS), text=f"檢查 {h['stock_id']}...")
                try:
                    r = check_holding(h)
                    results.append(r)
                except Exception:
                    pass
                time.sleep(0.3)

            progress.empty()

            if results:
                # 總覽
                total_cost = sum(r["buy_price"] * r["shares"] for r in results)
                total_value = sum(r["current_price"] * r["shares"] for r in results if r["current_price"] > 0)
                total_pnl = total_value - total_cost
                total_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("持倉總值", f"{total_value:,.0f} 元")
                with c2:
                    st.metric("總損益", f"{total_pnl:+,.0f} 元", f"{total_pct:+.1f}%")
                with c3:
                    alerts_count = sum(1 for r in results if r["warnings"])
                    if alerts_count > 0:
                        st.metric("需注意", f"{alerts_count} 檔", delta=f"-{alerts_count}", delta_color="inverse")
                    else:
                        st.metric("狀態", "✅ 全部正常")

                # 各持倉狀況
                for r in results:
                    emoji = "🚨" if r["warnings"] else "✅"
                    with st.expander(f"{emoji} {r['stock_id']} {r['name']}（{r['avg']}/10）損益 {r['pnl_pct']:+.1f}%"):
                        hc1, hc2, hc3, hc4 = st.columns(4)
                        with hc1:
                            st.metric("現價", f"{r['current_price']:.0f}")
                        with hc2:
                            st.metric("買入價", f"{r['buy_price']:.0f}")
                        with hc3:
                            st.metric("損益", f"{r['pnl_pct']:+.1f}%")
                        with hc4:
                            st.metric("評分", f"{r['avg']}/10")

                        if r["warnings"]:
                            for w in r["warnings"]:
                                st.warning(w)

                # 關聯性分析
                if len(results) >= 2:
                    st.markdown("### 🔗 持倉關聯性分析")
                    stock_ids = [r["stock_id"] for r in results]

                    with st.spinner("計算關聯性..."):
                        div = correlation.check_diversification(stock_ids)

                    for d in div["details"]:
                        if d.strip():
                            st.caption(d)

                    if not div["matrix"].empty:
                        st.markdown("**相關係數矩陣**（越接近 1 = 越容易同漲同跌）")
                        st.dataframe(div["matrix"], use_container_width=True)


# ===== 題材趨勢 =====
elif page == "🔥 題材趨勢":
    st.title("🔥 題材趨勢雷達")
    st.caption("掃描熱門題材，告訴你「什麼題材熱 + 裡面哪檔可以關注」")

    from trending import THEMES

    if st.button("開始掃描", type="primary", use_container_width=True):
        # Step 1: 掃描各題材熱度
        progress = st.progress(0, text="掃描題材熱度中...")
        theme_results = []
        theme_list = list(THEMES.items())

        for i, (tname, config) in enumerate(theme_list):
            progress.progress((i + 1) / len(theme_list), text=f"掃描「{tname}」...")
            total_heat = 0
            for kw in config["keywords"]:
                total_heat += news.count_news_heat(kw)
                time.sleep(0.3)
            theme_results.append({
                "name": tname,
                "config": config,
                "heat": total_heat,
            })

        theme_results.sort(key=lambda x: x["heat"], reverse=True)

        # 顯示熱度排名
        heat_df = pd.DataFrame([{"題材": t["name"], "熱度": t["heat"]} for t in theme_results])
        st.markdown("### 題材熱度排名")
        st.bar_chart(heat_df.set_index("題材"))

        # Step 2: 對前 3 名熱門題材掃描個股
        top_themes = [t for t in theme_results if t["heat"] > 0][:3]

        if not top_themes:
            st.info("目前沒有偵測到明顯熱門題材。")
        else:
            progress.progress(0, text="分析熱門題材個股...")
            st.markdown("### 🎯 熱門題材推薦個股")

            all_stock_ids = set()
            for t in top_themes:
                for sid in t["config"]["stocks"]:
                    all_stock_ids.add(sid)

            names = market.fetch_stock_names(list(all_stock_ids))
            total_stocks = sum(len(t["config"]["stocks"]) for t in top_themes)
            done = 0

            for t in top_themes:
                st.markdown(f"#### 🔥 {t['name']}（{t['heat']} 則新聞）")

                stock_results = []
                for sid in t["config"]["stocks"]:
                    done += 1
                    progress.progress(done / total_stocks, text=f"分析 {sid}...")
                    try:
                        price_df = market.fetch_stock_price(sid)
                        per_df = market.fetch_per_pbr(sid)
                        inst_df = market.fetch_institutional(sid)
                        rev_df = market.fetch_monthly_revenue(sid)
                        ind = market.fetch_stock_industry(sid)

                        tech = technical.analyze(price_df)
                        if market.is_etf(sid):
                            etf_info = market.fetch_etf_info(sid)
                            fund = fundamental.analyze_etf(price_df, etf_info, per_df)
                        else:
                            fund = fundamental.analyze(per_df, rev_df, ind)
                        inst_r = institutional.analyze(inst_df)

                        avg = round((tech["score"] + fund["score"] + inst_r["score"]) / 3, 1)
                        sig = overall_signal(avg)

                        stock_results.append({
                            "代號": sid,
                            "名稱": names.get(sid, sid),
                            "技術": tech["score"],
                            "基本": fund["score"],
                            "籌碼": inst_r["score"],
                            "綜合": avg,
                            "訊號": SIGNAL_EMOJI[sig],
                            "_avg": avg,
                        })
                    except Exception:
                        pass
                    time.sleep(0.2)

                if stock_results:
                    stock_results.sort(key=lambda x: x["_avg"], reverse=True)

                    # 推薦
                    best = stock_results[0]
                    if best["_avg"] >= 6:
                        st.success(f"👉 推薦關注：**{best['代號']} {best['名稱']}**（{best['綜合']}/10）— 這個題材裡條件最好的")
                    elif best["_avg"] >= 4:
                        st.warning(f"👉 {best['代號']} {best['名稱']}（{best['綜合']}/10）— 題材熱但個股條件普通，建議觀望")
                    else:
                        st.error(f"⚠ 這個題材裡的股票目前條件都不好，不建議追")

                    display_df = pd.DataFrame(stock_results).drop(columns=["_avg"])
                    st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)
                else:
                    st.caption("無法取得個股資料")

            progress.empty()


# ===== 歷史回測 =====
elif page == "📈 歷史回測":
    st.title("📈 歷史回測")

    col1, col2 = st.columns([2, 1])
    with col1:
        bt_stock = st.text_input("股票代號", value="2330", key="bt")
    with col2:
        bt_days = st.number_input("回測天數", value=500, min_value=100, max_value=1000, step=100)

    if st.button("開始回測", type="primary", use_container_width=True):
        from backtest import generate_signals, generate_signals_trend, calculate_trades

        bt_stock = bt_stock.strip().upper()
        is_us = market.is_us(bt_stock)

        with st.spinner("抓取歷史資料（還原權息價）..."):
            nm = market.fetch_stock_name(bt_stock)
            price_df = market.fetch_stock_price_adjusted(bt_stock, days=bt_days)

        if price_df.empty or len(price_df) < 60:
            st.error("資料不足，至少需要 60 天")
        else:
            price_df = price_df.sort_values("date").reset_index(drop=True)
            close = price_df["close"].astype(float)
            buy_hold = (close.iloc[-1] / close.iloc[60] - 1) * 100

            # 兩個策略都跑
            sig_a, hold_a = generate_signals(price_df)
            trades_a = calculate_trades(sig_a, is_us=is_us)

            sig_b, hold_b = generate_signals_trend(price_df)
            trades_b = calculate_trades(sig_b, is_us=is_us)

            st.markdown(f"### {bt_stock} {nm}")
            cost_note = "美股零佣金" if is_us else "含手續費和證交稅"
            st.caption(f"{cost_note} ｜ 使用還原權息價格回測")

            # 股價走勢圖
            chart_df = price_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"])
            chart_df["close"] = chart_df["close"].astype(float)
            chart_df = chart_df.set_index("date")
            st.line_chart(chart_df["close"])

            def _calc_stats(trades):
                if not trades:
                    return 0, 0, 0.0
                returns = [t["return_pct"] for t in trades]
                wins = [r for r in returns if r > 0]
                total = 1
                for r in returns:
                    total *= (1 + r / 100)
                total = (total - 1) * 100
                win_rate = len(wins) / len(trades) * 100 if trades else 0
                return len(trades), win_rate, total

            n_a, wr_a, ret_a = _calc_stats(trades_a)
            n_b, wr_b, ret_b = _calc_stats(trades_b)

            # ===== 三方對比 =====
            st.markdown("#### 策略對比")
            compare = pd.DataFrame({
                "指標": ["交易次數", "勝率", "累計報酬", "vs 買進持有"],
                "波段（均線交叉+RSI+停損）": [
                    f"{n_a}",
                    f"{wr_a:.0f}%",
                    f"{ret_a:+.1f}%",
                    f"{ret_a - buy_hold:+.1f}%",
                ],
                "趨勢跟蹤（20/60MA+移動停利）": [
                    f"{n_b}",
                    f"{wr_b:.0f}%",
                    f"{ret_b:+.1f}%",
                    f"{ret_b - buy_hold:+.1f}%",
                ],
                "買進持有": [
                    "—",
                    "—",
                    f"{buy_hold:+.1f}%",
                    "基準",
                ],
            })
            st.dataframe(compare, use_container_width=True, hide_index=True, height=400)

            # 勝負判定
            best = max(ret_a, ret_b, buy_hold)
            if best == ret_b:
                st.success(f"趨勢跟蹤勝出（{ret_b:+.1f}%）— 適合有明確趨勢的股票")
            elif best == ret_a:
                st.success(f"波段策略勝出（{ret_a:+.1f}%）— 適合震盪盤的股票")
            else:
                st.info(f"買進持有勝出（{buy_hold:+.1f}%）— 這段期間不做比較好")

            # 兩個策略的交易明細（用 tab 切換）
            tab_a, tab_b = st.tabs(["波段策略明細", "趨勢跟蹤明細"])

            with tab_a:
                if trades_a:
                    st.dataframe(pd.DataFrame([{
                        "#": i + 1,
                        "買入日": t["buy_date"],
                        "買入價": round(t["buy_price"], 1),
                        "賣出日": t["sell_date"],
                        "賣出價": round(t["sell_price"], 1),
                        "報酬": f"{t['return_pct']:+.1f}%",
                        "原因": t.get("sell_reason", ""),
                    } for i, t in enumerate(trades_a)]), use_container_width=True, hide_index=True, height=400)
                else:
                    st.info("無交易訊號")

            with tab_b:
                if trades_b:
                    st.dataframe(pd.DataFrame([{
                        "#": i + 1,
                        "買入日": t["buy_date"],
                        "買入價": round(t["buy_price"], 1),
                        "賣出日": t["sell_date"],
                        "賣出價": round(t["sell_price"], 1),
                        "報酬": f"{t['return_pct']:+.1f}%",
                        "原因": t.get("sell_reason", ""),
                    } for i, t in enumerate(trades_b)]), use_container_width=True, hide_index=True, height=400)
                    if hold_b:
                        st.caption(f"目前仍持有中（最新價 {close.iloc[-1]:.1f}）")
                else:
                    st.info("無交易訊號")

            # 提醒
            st.markdown("---")
            st.markdown("""
**怎麼看？**
- **趨勢跟蹤**：多頭市場待在場內跟著漲，只在趨勢反轉或從高點回落 10% 時才出場。適合大盤 ETF 和穩定成長股。
- **波段策略**：頻繁進出抓短線波段，適合震盪股（如 TSLA）。
- **買進持有**：什麼都不做。如果它贏了，代表這段期間不需要主動操作。
- 回測是壓力測試，不是預測未來。系統的真正價值在選股和風控。
""")


# ===== 訊號追蹤 =====
elif page == "📋 訊號追蹤":
    st.title("📋 訊號追蹤")
    st.caption("系統每次掃描都會自動記錄。這裡讓你驗證：系統上次說的話，到底準不準？")

    records = tracker.list_records()

    if not records:
        st.info("還沒有任何掃描記錄。先到「觀察清單掃描」跑一次，或等每日自動排程（每天 15:30）。")
    else:
        selected_date = st.selectbox("選擇日期", records)
        record = tracker.load_record(selected_date)

        if record:
            results = record["results"]
            df = pd.DataFrame(results).sort_values("avg", ascending=False)

            # 用人話摘要
            greens = df[df["avg"] >= 7]
            watch = df[(df["avg"] >= 6) & (df["avg"] < 7)]
            reds = df[df["avg"] < 4]

            st.markdown(f"### {record['date']} 的掃描記錄")

            summary_parts = []
            if len(greens) > 0:
                names_str = "、".join(f"{r['name']}" for _, r in greens.iterrows())
                summary_parts.append(f"🟢 當時系統說**{names_str}**值得買")
            if len(watch) > 0:
                names_str = "、".join(f"{r['name']}" for _, r in watch.iterrows())
                summary_parts.append(f"🟡 **{names_str}**值得關注")
            if len(reds) > 0:
                summary_parts.append(f"🔴 有 **{len(reds)} 檔**被系統標為偏空")

            if summary_parts:
                for s in summary_parts:
                    st.markdown(s)
            else:
                st.markdown("當時沒有特別突出的訊號。")

            # 簡潔的表格
            df["訊號"] = df["overall"].map(SIGNAL_EMOJI)
            display_df = df.rename(columns={
                "stock_id": "代號", "name": "名稱", "sector": "板塊",
                "tech": "技術", "fund": "基本", "inst": "籌碼", "avg": "綜合",
            })

            with st.expander("查看完整掃描結果", expanded=False):
                st.dataframe(
                    display_df[["代號", "名稱", "板塊", "技術", "基本", "籌碼", "綜合", "訊號"]],
                    use_container_width=True, hide_index=True,
                )

            # 準確度驗證 — 重點功能
            st.markdown("---")
            st.markdown("### 🎯 系統說的準不準？")
            st.caption("選一個天數，看看系統當時給的建議，在那之後股價實際怎麼走。")

            days_after = st.slider("幾天後驗證？", 5, 30, 10)

            if st.button("驗證準確度", type="primary", use_container_width=True):
                with st.spinner("比對實際股價中（需要一點時間）..."):
                    review = tracker.review_accuracy(
                        selected_date, market.fetch_stock_price, days_after
                    )

                if review:
                    # 大字標題
                    acc = review["accuracy"]
                    if acc >= 70:
                        st.success(f"### 🎯 準確率 {acc}%（{review['correct']}/{review['total']}）")
                    elif acc >= 50:
                        st.warning(f"### 🎯 準確率 {acc}%（{review['correct']}/{review['total']}）")
                    else:
                        st.error(f"### 🎯 準確率 {acc}%（{review['correct']}/{review['total']}）")

                    st.caption(f"驗證方式：{selected_date} 掃描後 {days_after} 天的實際股價漲跌")

                    # 用人話列出每筆
                    st.markdown("#### 逐筆驗證")
                    for r in review["results"]:
                        said_map = {"buy": "建議買", "hold": "觀望", "avoid": "不建議買"}
                        said = said_map.get(r["system_said"], r["system_said"])
                        ret = r["actual_return"]
                        correct = r["correct"]

                        if correct:
                            icon = "✅"
                        else:
                            icon = "❌"

                        ret_str = f"漲了 {ret:+.1f}%" if ret > 0 else f"跌了 {ret:.1f}%"

                        st.markdown(
                            f"{icon} **{r['name']}**（當時 {r['score']} 分，系統{said}）"
                            f"→ {days_after} 天後{ret_str}"
                        )

                    # 結論
                    st.markdown("---")
                    if acc >= 70:
                        st.markdown("**結論：系統判斷大致可靠，但仍需結合自己的判斷。**")
                    elif acc >= 50:
                        st.markdown("**結論：系統判斷正確率一般，建議搭配其他資訊使用。**")
                    else:
                        st.markdown("**結論：這段期間系統判斷偏差較大，可能需要調整參數。**")
                else:
                    st.warning("無法驗證 — 可能日期太近（股價還沒走出來）或資料抓取失敗。至少要等 5 個交易日才能驗證。")


# ===== 自訂追蹤 =====
elif page == "⭐ 自訂追蹤":
    st.title("⭐ 自訂追蹤")
    st.caption("追蹤觀察清單以外的股票，你加的股票會出現在這裡")

    import custom_watchlist

    # 新增股票
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        new_id = st.text_input("股票代號", placeholder="例如 2603 或 GOOGL")
    with col2:
        new_note = st.text_input("備註（選填）", placeholder="為什麼追蹤這檔")
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        add_btn = st.button("加入追蹤", type="primary")

    if add_btn and new_id:
        new_id = new_id.strip().upper()
        if custom_watchlist.add(new_id, new_note):
            st.success(f"已加入 {new_id}")
            st.rerun()
        else:
            st.warning(f"{new_id} 已經在追蹤清單中")

    st.markdown("---")

    # 顯示追蹤清單 + 即時分析
    items = custom_watchlist.load()

    if not items:
        st.info("還沒有自訂追蹤的股票。在上方輸入代號加入。")
    else:
        st.markdown(f"### 追蹤中（{len(items)} 檔）")

        if st.button("分析全部", use_container_width=True):
            for item in items:
                sid = item["stock_id"]
                note = item.get("note", "")
                with st.spinner(f"分析 {sid}..."):
                    try:
                        nm = market.fetch_stock_name(sid)
                        ind = market.fetch_stock_industry(sid)
                        price_df = market.fetch_stock_price(sid)
                        per_df = market.fetch_per_pbr(sid)
                        inst_df = market.fetch_institutional(sid)
                        rev_df = market.fetch_monthly_revenue(sid)

                        tech = technical.analyze(price_df)
                        if market.is_etf(sid):
                            etf_info = market.fetch_etf_info(sid)
                            fund = fundamental.analyze_etf(price_df, etf_info, per_df)
                        else:
                            fund = fundamental.analyze(per_df, rev_df, ind)
                        inst_result = institutional.analyze(inst_df)

                        avg, _ = weighted_score(
                            tech["score"], fund["score"], inst_result["score"], 5.0, strategy_key,
                            is_us=market.is_us(sid),
                        )
                        signal = overall_signal(avg)
                        emoji = SIGNAL_EMOJI[signal]

                        note_str = f"（{note}）" if note else ""
                        if avg >= 7:
                            st.success(f"{emoji} **{sid} {nm}** {note_str} — {avg}/10　技術 {tech['score']} 基本 {fund['score']} 籌碼 {inst_result['score']}")
                        elif avg >= 4:
                            st.warning(f"{emoji} **{sid} {nm}** {note_str} — {avg}/10　技術 {tech['score']} 基本 {fund['score']} 籌碼 {inst_result['score']}")
                        else:
                            st.error(f"{emoji} **{sid} {nm}** {note_str} — {avg}/10　技術 {tech['score']} 基本 {fund['score']} 籌碼 {inst_result['score']}")
                    except Exception as e:
                        st.error(f"**{sid}** 分析失敗：{e}")

        # 列表 + 刪除
        st.markdown("---")
        for item in items:
            col_a, col_b, col_c = st.columns([2, 3, 1])
            with col_a:
                st.markdown(f"**{item['stock_id']}**")
            with col_b:
                st.caption(item.get("note", ""))
            with col_c:
                if st.button("移除", key=f"rm_{item['stock_id']}"):
                    custom_watchlist.remove(item["stock_id"])
                    st.rerun()
