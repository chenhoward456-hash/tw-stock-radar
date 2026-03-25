#!/usr/bin/env python3
"""
臺股雷達 — 網頁儀表板
啟動：streamlit run app.py
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
from watchlist import WATCHLIST

TOKEN = FINMIND_TOKEN or None

# ===== 頁面設定 =====
st.set_page_config(
    page_title="臺股雷達",
    page_icon="📊",
    layout="wide",
)

SIGNAL_COLORS = {
    "green": "#22c55e",
    "yellow": "#eab308",
    "red": "#ef4444",
}
SIGNAL_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
SIGNAL_TEXT = {"green": "綠燈", "yellow": "黃燈", "red": "紅燈"}


def signal_badge(signal, score):
    color = SIGNAL_COLORS[signal]
    label = SIGNAL_TEXT[signal]
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:12px;font-weight:bold">{label} {score}/10</span>'


# ===== 側欄 =====
st.sidebar.title("📊 臺股雷達")
page = st.sidebar.radio("功能", [
    "🔍 個股分析",
    "📡 觀察清單掃描",
    "⚔ 股票 PK",
    "🔥 題材趨勢",
    "📈 歷史回測",
])

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
            industry = fetch_stock_industry(stock_id, TOKEN)
            price_df = fetch_stock_price(stock_id, token=TOKEN)
            inst_df = fetch_institutional(stock_id, token=TOKEN)
            per_df = fetch_per_pbr(stock_id, token=TOKEN)
            rev_df = fetch_monthly_revenue(stock_id, token=TOKEN)
            news_result = news.analyze(stock_id, name)

        with st.spinner("分析中..."):
            tech = technical.analyze(price_df)
            fund = fundamental.analyze(per_df, rev_df, industry)
            inst = institutional.analyze(inst_df)

        # 綜合評分
        scores = [tech["score"], fund["score"], inst["score"], news_result["score"]]
        avg = round(sum(scores) / len(scores), 1)
        if avg >= 7:
            overall = "green"
        elif avg >= 4:
            overall = "yellow"
        else:
            overall = "red"

        # 標題
        st.markdown(f"## {stock_id} {name}")
        if industry:
            st.caption(f"產業：{industry}")

        # 綜合評分大字
        col_score, col_advice = st.columns([1, 2])
        with col_score:
            st.metric("綜合評分", f"{avg} / 10")
            st.markdown(signal_badge(overall, avg), unsafe_allow_html=True)
        with col_advice:
            if avg >= 7:
                st.success("各面向條件良好，可以考慮佈局。")
            elif avg >= 5.5:
                st.warning("條件尚可，建議分批進場，不要一次重壓。")
            elif avg >= 4:
                st.warning("條件普通，建議觀望或僅小量試水。")
            else:
                st.error("多項指標偏空，目前不建議進場。")

            if "current_price" in tech and "ma20" in tech:
                st.caption(f"📍 停損參考：20日均線 {tech['ma20']:.0f} 元")

        # K線圖
        if not price_df.empty:
            chart_df = price_df.sort_values("date").tail(60).copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"])
            chart_df["close"] = chart_df["close"].astype(float)
            chart_df = chart_df.set_index("date")

            st.markdown("### 近 60 日走勢")
            st.line_chart(chart_df["close"])

        # 四面向詳細
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
                industry = fetch_stock_industry(stock_id, TOKEN)

                tech = technical.analyze(price_df)
                fund = fundamental.analyze(per_df, rev_df, industry)
                inst = institutional.analyze(inst_df)

                avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)
                overall = "green" if avg >= 7 else ("yellow" if avg >= 4 else "red")

                results.append({
                    "代號": stock_id,
                    "名稱": sname,
                    "板塊": stock_sectors[stock_id],
                    "技術": tech["score"],
                    "基本": fund["score"],
                    "籌碼": inst["score"],
                    "綜合": avg,
                    "訊號": SIGNAL_EMOJI[overall],
                })
            except Exception:
                pass
            time.sleep(0.2)

        progress.empty()

        if results:
            df = pd.DataFrame(results).sort_values("綜合", ascending=False)

            # 綠燈 / 值得關注 / 紅燈
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

            # 完整排名
            st.markdown("### 完整排名")
            st.dataframe(df, use_container_width=True, hide_index=True)

            # 板塊分析
            st.markdown("### 板塊強弱")
            sector_df = df.groupby("板塊")["綜合"].mean().round(1).sort_values(ascending=False)
            st.bar_chart(sector_df)


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
            name = fetch_stock_name(sid, TOKEN)
            industry = fetch_stock_industry(sid, TOKEN)
            price_df = fetch_stock_price(sid, token=TOKEN)
            per_df = fetch_per_pbr(sid, token=TOKEN)
            inst_df = fetch_institutional(sid, token=TOKEN)
            rev_df = fetch_monthly_revenue(sid, token=TOKEN)
            tech = technical.analyze(price_df)
            fund = fundamental.analyze(per_df, rev_df, industry)
            inst = institutional.analyze(inst_df)
            avg = round((tech["score"] + fund["score"] + inst["score"]) / 3, 1)
            return name, tech, fund, inst, avg

        with st.spinner("分析中..."):
            name_a, tech_a, fund_a, inst_a, avg_a = analyze_one(id_a)
            name_b, tech_b, fund_b, inst_b, avg_b = analyze_one(id_b)

        # 對比表
        compare_data = {
            "面向": ["技術面", "基本面", "籌碼面", "綜合"],
            f"{id_a} {name_a}": [tech_a["score"], fund_a["score"], inst_a["score"], avg_a],
            f"{id_b} {name_b}": [tech_b["score"], fund_b["score"], inst_b["score"], avg_b],
        }
        compare_df = pd.DataFrame(compare_data)
        st.dataframe(compare_df, use_container_width=True, hide_index=True)

        # 視覺化比較
        chart_data = pd.DataFrame({
            name_a: [tech_a["score"], fund_a["score"], inst_a["score"]],
            name_b: [tech_b["score"], fund_b["score"], inst_b["score"]],
        }, index=["技術面", "基本面", "籌碼面"])
        st.bar_chart(chart_data)

        # 結論
        if avg_a > avg_b + 1:
            st.success(f"📊 {id_a} {name_a} 目前各面向條件明顯較優（{avg_a} vs {avg_b}）")
        elif avg_b > avg_a + 1:
            st.success(f"📊 {id_b} {name_b} 目前各面向條件明顯較優（{avg_b} vs {avg_a}）")
        else:
            st.info(f"📊 兩檔條件相近（{avg_a} vs {avg_b}）")


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
            theme_results.append({"題材": name, "熱度（新聞數）": total_heat})

        progress.empty()

        df = pd.DataFrame(theme_results).sort_values("熱度（新聞數）", ascending=False)
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
            name = fetch_stock_name(bt_stock, TOKEN)
            price_df = fetch_stock_price(bt_stock, days=bt_days, token=TOKEN)

        if price_df.empty or len(price_df) < 60:
            st.error("資料不足，至少需要 60 天")
        else:
            price_df = price_df.sort_values("date").reset_index(drop=True)
            signals, still_holding = generate_signals(price_df)
            trades = calculate_trades(signals)

            st.markdown(f"### {bt_stock} {name}")
            st.caption(f"策略：均線交叉（5日突破20日買，跌破賣） | 資料：{len(price_df)} 日")

            # 走勢圖
            chart_df = price_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"])
            chart_df["close"] = chart_df["close"].astype(float)
            chart_df = chart_df.set_index("date")
            st.line_chart(chart_df["close"])

            if trades:
                # 交易紀錄
                trade_data = []
                for i, t in enumerate(trades, 1):
                    trade_data.append({
                        "#": i,
                        "買入日期": t["buy_date"],
                        "買入價": t["buy_price"],
                        "賣出日期": t["sell_date"],
                        "賣出價": t["sell_price"],
                        "報酬": f"{t['return_pct']:+.1f}%",
                    })
                st.dataframe(pd.DataFrame(trade_data), use_container_width=True, hide_index=True)

                # 統計
                returns = [t["return_pct"] for t in trades]
                wins = [r for r in returns if r > 0]
                losses = [r for r in returns if r <= 0]

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
