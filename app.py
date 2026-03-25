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

from config import FINMIND_TOKEN, TOTAL_BUDGET
from data_fetcher import (
    fetch_stock_name,
    fetch_stock_industry,
    fetch_stock_names,
    fetch_stock_price,
    fetch_institutional,
    fetch_per_pbr,
    fetch_monthly_revenue,
)
import technical
import fundamental
import institutional
import news
import portfolio
import tracker
from scoring import STRATEGIES, weighted_score
from watchlist import WATCHLIST

TOKEN = FINMIND_TOKEN or None

st.set_page_config(page_title="臺股雷達", page_icon="📊", layout="wide")

SIGNAL_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def overall_signal(score):
    if score >= 7:
        return "green"
    elif score >= 4:
        return "yellow"
    return "red"


# ===== 側欄 =====
st.sidebar.title("📊 臺股雷達")
page = st.sidebar.radio("功能", [
    "🔍 個股分析",
    "📡 觀察清單掃描",
    "⚔ 股票 PK",
    "💼 持倉監控",
    "🔥 題材趨勢",
    "📈 歷史回測",
    "📋 訊號追蹤",
])

st.sidebar.markdown("---")

# 全域策略選擇
strategy_key = st.sidebar.selectbox(
    "投資策略",
    list(STRATEGIES.keys()),
    format_func=lambda k: f"{STRATEGIES[k]['label']} — {STRATEGIES[k]['description']}",
)

st.sidebar.markdown("---")
st.sidebar.caption("⚠ 僅供參考，不構成投資建議")


# ===== 個股分析 =====
if page == "🔍 個股分析":
    st.title("🔍 個股分析")

    col1, col2 = st.columns([2, 1])
    with col1:
        stock_id = st.text_input("股票代號", value="2330", placeholder="例：2330")
    with col2:
        budget = st.number_input("投資預算（選填）", value=TOTAL_BUDGET, step=100000, format="%d")

    if st.button("開始分析", type="primary", use_container_width=True):
        with st.spinner("抓取資料中..."):
            name = fetch_stock_name(stock_id, TOKEN)
            ind = fetch_stock_industry(stock_id, TOKEN)
            price_df = fetch_stock_price(stock_id, token=TOKEN)
            inst_df = fetch_institutional(stock_id, token=TOKEN)
            per_df = fetch_per_pbr(stock_id, token=TOKEN)
            rev_df = fetch_monthly_revenue(stock_id, token=TOKEN)
            news_result = news.analyze(stock_id, name)

        with st.spinner("分析中..."):
            tech = technical.analyze(price_df)
            fund = fundamental.analyze(per_df, rev_df, ind)
            inst = institutional.analyze(inst_df)

        avg, strategy_info = weighted_score(
            tech["score"], fund["score"], inst["score"], news_result["score"], strategy_key
        )
        signal = overall_signal(avg)

        st.markdown(f"## {stock_id} {name}")
        if ind:
            st.caption(f"產業：{ind} ｜ 策略：{strategy_info['label']}")

        # 評分區
        c1, c2 = st.columns([1, 2])
        with c1:
            st.metric("綜合評分（加權）", f"{avg} / 10")
            st.markdown(f"### {SIGNAL_EMOJI[signal]} {avg}/10")
        with c2:
            if avg >= 7:
                st.success("各面向條件良好，可以考慮佈局。")
            elif avg >= 5.5:
                st.warning("條件尚可，建議分批進場。")
            elif avg >= 4:
                st.warning("條件普通，建議觀望。")
            else:
                st.error("偏空，不建議進場。")

            w = strategy_info["weights"]
            st.caption(
                f"權重：技術{w['tech']:.0%} 基本{w['fund']:.0%} "
                f"籌碼{w['inst']:.0%} 消息{w['news']:.0%}"
            )

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
        all_stocks = []
        stock_sectors = {}
        for sector, codes in WATCHLIST.items():
            for code in codes:
                all_stocks.append(code)
                stock_sectors[code] = sector

        names = fetch_stock_names(all_stocks, TOKEN)
        total = len(all_stocks)
        progress = st.progress(0, text="載入中...")
        results = []

        for i, stock_id in enumerate(all_stocks):
            sname = names.get(stock_id, stock_id)
            progress.progress((i + 1) / total, text=f"掃描 {stock_id} {sname}...")

            try:
                price_df = fetch_stock_price(stock_id, token=TOKEN)
                per_df = fetch_per_pbr(stock_id, token=TOKEN)
                inst_df = fetch_institutional(stock_id, token=TOKEN)
                rev_df = fetch_monthly_revenue(stock_id, token=TOKEN)
                ind = fetch_stock_industry(stock_id, TOKEN)

                tech = technical.analyze(price_df)
                fund = fundamental.analyze(per_df, rev_df, ind)
                inst_result = institutional.analyze(inst_df)

                avg, _ = weighted_score(
                    tech["score"], fund["score"], inst_result["score"], 5.0, strategy_key
                )
                signal = overall_signal(avg)

                results.append({
                    "代號": stock_id,
                    "名稱": sname,
                    "板塊": stock_sectors[stock_id],
                    "技術": tech["score"],
                    "基本": fund["score"],
                    "籌碼": inst_result["score"],
                    "綜合": avg,
                    "訊號": SIGNAL_EMOJI[signal],
                })
            except Exception:
                pass
            time.sleep(0.2)

        progress.empty()

        if results:
            df = pd.DataFrame(results).sort_values("綜合", ascending=False)

            greens = df[df["綜合"] >= 7]
            watch = df[(df["綜合"] >= 6) & (df["綜合"] < 7)]
            reds = df[df["綜合"] < 4]

            if not greens.empty:
                st.success(f"🟢 綠燈候選（{len(greens)} 檔）")
                st.dataframe(greens, use_container_width=True, hide_index=True)
            if not watch.empty:
                st.warning(f"🟡 值得關注（{len(watch)} 檔）")
                st.dataframe(watch, use_container_width=True, hide_index=True)
            if not reds.empty:
                st.error(f"🔴 偏空警示（{len(reds)} 檔）")
                st.dataframe(reds, use_container_width=True, hide_index=True)

            st.markdown("### 完整排名")
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.markdown("### 板塊強弱")
            sector_df = df.groupby("板塊")["綜合"].mean().round(1).sort_values(ascending=False)
            st.bar_chart(sector_df)

            # 儲存訊號
            try:
                scan_results = [
                    {"stock_id": r["代號"], "name": r["名稱"], "sector": r["板塊"],
                     "tech": r["技術"], "fund": r["基本"], "inst": r["籌碼"],
                     "avg": r["綜合"], "overall": overall_signal(r["綜合"])}
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
            nm = fetch_stock_name(sid, TOKEN)
            ind = fetch_stock_industry(sid, TOKEN)
            price_df = fetch_stock_price(sid, token=TOKEN)
            per_df = fetch_per_pbr(sid, token=TOKEN)
            inst_df = fetch_institutional(sid, token=TOKEN)
            rev_df = fetch_monthly_revenue(sid, token=TOKEN)
            t = technical.analyze(price_df)
            f = fundamental.analyze(per_df, rev_df, ind)
            ins = institutional.analyze(inst_df)
            avg, _ = weighted_score(t["score"], f["score"], ins["score"], 5.0, strategy_key)
            return nm, t["score"], f["score"], ins["score"], avg

        with st.spinner("分析中..."):
            na, ta, fa, ia, avg_a = analyze_one(id_a)
            nb, tb, fb, ib, avg_b = analyze_one(id_b)

        compare_df = pd.DataFrame({
            "面向": ["技術面", "基本面", "籌碼面", "綜合（加權）"],
            f"{id_a} {na}": [ta, fa, ia, avg_a],
            f"{id_b} {nb}": [tb, fb, ib, avg_b],
        })
        st.dataframe(compare_df, use_container_width=True, hide_index=True)

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

    from holdings import HOLDINGS
    import correlation

    if not HOLDINGS:
        st.info("你還沒有設定持倉。請到 `holdings.py` 加入你的持股。")
        st.code('''# 範例：
HOLDINGS = [
    {"stock_id": "2330", "buy_price": 1850, "shares": 100, "buy_date": "2026-03-20"},
    {"stock_id": "2357", "buy_price": 560, "shares": 200, "buy_date": "2026-03-25"},
]''', language="python")
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
                        div = correlation.check_diversification(stock_ids, TOKEN)

                    for d in div["details"]:
                        if d.strip():
                            st.caption(d)

                    if not div["matrix"].empty:
                        st.markdown("**相關係數矩陣**（越接近 1 = 越容易同漲同跌）")
                        st.dataframe(div["matrix"], use_container_width=True)


# ===== 題材趨勢 =====
elif page == "🔥 題材趨勢":
    st.title("🔥 題材趨勢雷達")

    from trending import THEMES

    if st.button("開始掃描題材", type="primary", use_container_width=True):
        progress = st.progress(0, text="掃描中...")
        theme_results = []
        theme_list = list(THEMES.items())

        for i, (name, config) in enumerate(theme_list):
            progress.progress((i + 1) / len(theme_list), text=f"掃描「{name}」...")
            total_heat = 0
            for kw in config["keywords"]:
                total_heat += news.count_news_heat(kw)
                time.sleep(0.3)
            theme_results.append({"題材": name, "熱度": total_heat})

        progress.empty()
        df = pd.DataFrame(theme_results).sort_values("熱度", ascending=False)
        st.bar_chart(df.set_index("題材"))
        st.dataframe(df, use_container_width=True, hide_index=True)


# ===== 歷史回測 =====
elif page == "📈 歷史回測":
    st.title("📈 歷史回測")

    col1, col2 = st.columns([2, 1])
    with col1:
        bt_stock = st.text_input("股票代號", value="2330", key="bt")
    with col2:
        bt_days = st.number_input("回測天數", value=500, min_value=100, max_value=1000, step=100)

    if st.button("開始回測", type="primary", use_container_width=True):
        from backtest import generate_signals, calculate_trades

        with st.spinner("抓取歷史資料..."):
            nm = fetch_stock_name(bt_stock, TOKEN)
            price_df = fetch_stock_price(bt_stock, days=bt_days, token=TOKEN)

        if price_df.empty or len(price_df) < 60:
            st.error("資料不足，至少需要 60 天")
        else:
            price_df = price_df.sort_values("date").reset_index(drop=True)
            signals, still_holding = generate_signals(price_df)
            trades = calculate_trades(signals)

            st.markdown(f"### {bt_stock} {nm}")
            st.caption(f"策略：均線交叉（5日突破20日買，跌破賣）｜含手續費和證交稅")

            chart_df = price_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"])
            chart_df["close"] = chart_df["close"].astype(float)
            chart_df = chart_df.set_index("date")
            st.line_chart(chart_df["close"])

            if trades:
                trade_data = [{
                    "#": i + 1,
                    "買入日": t["buy_date"],
                    "買入價": t["buy_price"],
                    "賣出日": t["sell_date"],
                    "賣出價": t["sell_price"],
                    "報酬": f"{t['return_pct']:+.1f}%",
                } for i, t in enumerate(trades)]
                st.dataframe(pd.DataFrame(trade_data), use_container_width=True, hide_index=True)

                returns = [t["return_pct"] for t in trades]
                wins = [r for r in returns if r > 0]
                total_return = 1
                for r in returns:
                    total_return *= (1 + r / 100)
                total_return = (total_return - 1) * 100

                close = price_df["close"].astype(float)
                buy_hold = (close.iloc[-1] / close.iloc[20] - 1) * 100

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("交易次數", len(trades))
                with c2:
                    st.metric("勝率", f"{len(wins)/len(trades)*100:.0f}%")
                with c3:
                    st.metric("策略報酬", f"{total_return:+.1f}%")
                with c4:
                    st.metric("買進持有", f"{buy_hold:+.1f}%")
            else:
                st.info("此期間沒有產生交易訊號。")


# ===== 訊號追蹤 =====
elif page == "📋 訊號追蹤":
    st.title("📋 訊號追蹤")
    st.caption("每次掃描的結果都會自動記錄，你可以回頭看系統到底準不準。")

    records = tracker.list_records()

    if not records:
        st.info("還沒有任何掃描記錄。先到「觀察清單掃描」跑一次，或等每日自動排程。")
    else:
        selected_date = st.selectbox("選擇日期", records)
        record = tracker.load_record(selected_date)

        if record:
            st.markdown(f"### {record['date']} 掃描結果（{record['count']} 檔）")

            df = pd.DataFrame(record["results"])
            df = df.sort_values("avg", ascending=False)
            df["訊號"] = df["overall"].map(SIGNAL_EMOJI)

            display_df = df.rename(columns={
                "stock_id": "代號", "name": "名稱", "sector": "板塊",
                "tech": "技術", "fund": "基本", "inst": "籌碼", "avg": "綜合",
            })
            st.dataframe(
                display_df[["代號", "名稱", "板塊", "技術", "基本", "籌碼", "綜合", "訊號"]],
                use_container_width=True, hide_index=True,
            )

            # 準確度回顧
            st.markdown("### 📊 準確度回顧")
            days_after = st.slider("對比幾天後的表現？", 5, 30, 10)

            if st.button("分析準確度"):
                with st.spinner("比對實際價格中..."):
                    review = tracker.review_accuracy(
                        selected_date, fetch_stock_price, days_after
                    )

                if review:
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("準確率", f"{review['accuracy']}%")
                    with c2:
                        st.metric("判斷正確", f"{review['correct']}/{review['total']}")
                    with c3:
                        st.metric("回顧天數", f"{review['days_after']} 天")

                    review_df = pd.DataFrame(review["results"])
                    review_df["結果"] = review_df["correct"].map({True: "✓", False: "✗"})
                    review_df["實際漲跌"] = review_df["actual_return"].apply(lambda x: f"{x:+.1f}%")
                    st.dataframe(
                        review_df[["stock_id", "name", "score", "system_said", "實際漲跌", "結果"]].rename(columns={
                            "stock_id": "代號", "name": "名稱", "score": "當時評分", "system_said": "系統建議",
                        }),
                        use_container_width=True, hide_index=True,
                    )
                else:
                    st.warning("資料不足，無法回顧（可能日期太近或資料抓取失敗）")
