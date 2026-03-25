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
import institutional
import news
import portfolio
import tracker
from scoring import STRATEGIES, weighted_score
from watchlist import WATCHLIST

st.set_page_config(page_title="投資雷達", page_icon="📊", layout="wide")

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


# ===== 今日焦點 =====
if page == "🏠 今日焦點":
    st.title("🏠 今日焦點")
    st.caption("打開就知道今天該關注什麼 — 不用看 145 檔，系統幫你篩好了")

    # 讀最近的掃描記錄
    last_records = tracker.list_records()
    has_scan = bool(last_records)

    # 持倉狀況
    import holdings as _h
    HOLDINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
    try:
        _vars = {}
        with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
            exec(f.read(), _vars)
        _holdings = _vars.get("HOLDINGS", [])
    except Exception:
        _holdings = []

    if _holdings:
        st.markdown("### 🚨 持倉狀況")
        from monitor import check_holding
        for h in _holdings:
            try:
                r = check_holding(h)
                pnl = f"{r['pnl_pct']:+.1f}%"
                if r["warnings"]:
                    st.error(f"**{r['stock_id']} {r['name']}**　損益 {pnl}　評分 {r['avg']}/10")
                    for w in r["warnings"][:2]:
                        st.caption(f"　　{w}")
                else:
                    st.success(f"**{r['stock_id']} {r['name']}**　損益 {pnl}　評分 {r['avg']}/10 — 正常")
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
                st.markdown("**🟢 系統推薦關注這幾檔：**")
                for r in sorted(greens, key=lambda x: x["avg"], reverse=True):
                    st.markdown(f"- **{r['stock_id']} {r['name']}**（{r['avg']}/10）— {r.get('sector', '')}")
                st.caption("→ 點左邊「個股分析」輸入代號看完整報告")
            else:
                st.info("目前沒有 7 分以上的綠燈股，建議耐心等待。")

            if watch:
                with st.expander(f"🟡 值得留意（{len(watch)} 檔）"):
                    for r in sorted(watch, key=lambda x: x["avg"], reverse=True):
                        st.markdown(f"- {r['stock_id']} {r['name']}（{r['avg']}/10）")

            if reds:
                with st.expander(f"🔴 偏空（{len(reds)} 檔）— 不要碰"):
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

    st.markdown("---")
    st.markdown("### 💡 今天該做什麼？")
    st.markdown("""
1. 看上面有沒有 🟢 綠燈股 → 有的話點「個股分析」深入看
2. 持倉有 🚨 警告 → 認真評估要不要處理
3. 都沒事 → 關掉，明天再來看
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

        with st.spinner("抓取資料中..."):
            name = market.fetch_stock_name(stock_id)
            ind = market.fetch_stock_industry(stock_id)
            price_df = market.fetch_stock_price(stock_id)
            inst_df = market.fetch_institutional(stock_id)
            per_df = market.fetch_per_pbr(stock_id)
            rev_df = market.fetch_monthly_revenue(stock_id)
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

        names = market.fetch_stock_names(all_stocks)
        total = len(all_stocks)
        progress = st.progress(0, text="載入中...")
        results = []

        for i, stock_id in enumerate(all_stocks):
            sname = names.get(stock_id, stock_id)
            progress.progress((i + 1) / total, text=f"掃描 {stock_id} {sname}...")

            try:
                price_df = market.fetch_stock_price(stock_id)
                per_df = market.fetch_per_pbr(stock_id)
                inst_df = market.fetch_institutional(stock_id)
                rev_df = market.fetch_monthly_revenue(stock_id)
                ind = market.fetch_stock_industry(stock_id)

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
            nm = market.fetch_stock_name(sid)
            ind = market.fetch_stock_industry(sid)
            price_df = market.fetch_stock_price(sid)
            per_df = market.fetch_per_pbr(sid)
            inst_df = market.fetch_institutional(sid)
            rev_df = market.fetch_monthly_revenue(sid)
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

            new_stop = st.number_input("停損價（選填，0=不設）", min_value=0.0, step=1.0, format="%.1f")
            submitted = st.form_submit_button("新增", use_container_width=True)

            if submitted and new_id and new_price > 0 and new_shares > 0:
                HOLDINGS.append({
                    "stock_id": new_id.strip(),
                    "buy_price": new_price,
                    "shares": new_shares,
                    "buy_date": new_date.strftime("%Y-%m-%d"),
                    "stop_loss": new_stop,
                })
                _save_holdings(HOLDINGS)
                st.success(f"已新增 {new_id}！重新整理頁面即可看到。")
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
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
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
        from backtest import generate_signals, calculate_trades

        with st.spinner("抓取歷史資料..."):
            nm = market.fetch_stock_name(bt_stock)
            price_df = market.fetch_stock_price(bt_stock, days=bt_days)

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
