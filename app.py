#!/usr/bin/env python3
"""
臺股雷達 — 網頁儀表板
啟動：python3 -m streamlit run app.py
"""
import sys
import os
import time
import logging

# Minimal logging setup - data fetching warnings go to file so silent failures are visible
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "radar.log"), encoding="utf-8"),
    ],
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np

from config import TOTAL_BUDGET
import market

# === Bug fix: TOTAL_BUDGET fallback ===
# If TOTAL_BUDGET is 0 (user hasn't set it), estimate from holdings
def _get_effective_budget():
    """Get budget: use TOTAL_BUDGET if set, otherwise estimate from holdings."""
    if TOTAL_BUDGET > 0:
        return TOTAL_BUDGET
    # Fallback: sum of holdings market value (buy_price * shares)
    try:
        _vars = {}
        _hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
        with open(_hp, "r", encoding="utf-8") as f:
            exec(f.read(), _vars)
        _h = _vars.get("HOLDINGS", [])
        if _h:
            return int(sum(h["buy_price"] * h["shares"] for h in _h))
    except Exception:
        pass
    return 0

_EFFECTIVE_BUDGET = _get_effective_budget()
import technical
import fundamental
import valuation
import institutional
import news
import portfolio
import tracker
import streak
import sector_rotation
import macro
from scoring import STRATEGIES, weighted_score, calc_consensus_score
from watchlist import WATCHLIST

st.set_page_config(page_title="投資雷達", page_icon="📊", layout="centered")

import ios_theme
ios_theme.apply()

SIGNAL_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def overall_signal(score):
    green_th = st.session_state.get("green_threshold", 7.0)
    if score >= green_th:
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
    "📊 持倉分析",
    "🔥 題材趨勢",
    "📈 歷史回測",
    "📋 訊號追蹤",
    "⭐ 自訂追蹤",
    "📒 交易日誌",
])

st.sidebar.markdown("---")

# 全域策略選擇
strategy_key = st.sidebar.selectbox(
    "投資策略",
    list(STRATEGIES.keys()),
    format_func=lambda k: f"{STRATEGIES[k]['label']} — {STRATEGIES[k]['description']}",
)

st.sidebar.markdown("---")

# ===== 進階設定 =====
with st.sidebar.expander("⚙ 進階設定"):
    if "atr_multiplier" not in st.session_state:
        st.session_state.atr_multiplier = 2.0
    if "drawdown_threshold" not in st.session_state:
        st.session_state.drawdown_threshold = 15
    if "green_threshold" not in st.session_state:
        st.session_state.green_threshold = 7.0

    st.session_state.atr_multiplier = st.slider(
        "ATR 倍數（停損距離）",
        min_value=1.0, max_value=4.0, step=0.5,
        value=st.session_state.atr_multiplier,
        help="越大 = 停損越寬鬆，預設 2.0",
    )
    st.session_state.drawdown_threshold = st.slider(
        "回撤警報門檻（%）",
        min_value=5, max_value=30, step=5,
        value=st.session_state.drawdown_threshold,
        help="持倉虧損超過此比例會警報，預設 15%",
    )
    st.session_state.green_threshold = st.slider(
        "綠燈門檻（分）",
        min_value=5.0, max_value=9.0, step=0.5,
        value=st.session_state.green_threshold,
        help="綜合分數 >= 此值 = 綠燈，預設 7",
    )

from config import FINMIND_TOKEN
if not FINMIND_TOKEN:
    st.sidebar.warning("台股資料限速中（未設 FinMind Token）。到 config.py 填入免費 Token 可提升 10 倍速度。")
st.sidebar.caption("⚠ 僅供參考，不構成投資建議")


# ===== 今日焦點 =====
if page == "🏠 今日焦點":
    st.title("🏠 今日焦點")
    st.caption("打開就知道今天該關注什麼 — 不用看 145 檔，系統幫你篩好了")

    # ===== 總體經濟環境（新增）=====
    _macro_data = None
    _macro_multiplier = 1.0
    try:
        _macro_data = macro.analyze()
        _macro_multiplier = _macro_data["risk_multiplier"]
        macro_signal = _macro_data["signal"]
        macro_score = _macro_data["score"]

        if macro_signal == "red":
            st.error(f"🚨 **總體經濟警報** — 環境分 {macro_score}/10，個股評分自動降級（×{_macro_multiplier}）")
        elif macro_signal == "yellow" and _macro_multiplier < 0.95:
            st.warning(f"⚠ **總體環境偏弱** — 環境分 {macro_score}/10，個股評分微調（×{_macro_multiplier}）")
        elif macro_signal == "green":
            st.success(f"✅ **總體環境良好** — 環境分 {macro_score}/10，放心操作")
        else:
            st.info(f"📊 **總體環境** — 環境分 {macro_score}/10，正常")

        # [R4] 恐慌/貪婪指數
        fg = _macro_data.get("fear_greed_index")
        fg_label = _macro_data.get("fear_greed_label", "")
        if fg is not None:
            st.caption(f"恐慌/貪婪指數：**{fg}/100**（{fg_label}）")

        with st.expander("總體經濟細節"):
            for d in _macro_data["details"]:
                st.caption(d)
    except Exception:
        pass

    # ===== 0050 多空燈號 =====
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

        # 總損益摘要
        _total_invested = 0
        _total_current = 0
        for _h_summary in _holdings:
            _cost = _h_summary["buy_price"] * _h_summary["shares"]
            _total_invested += _cost
            try:
                _cur_price = market.fetch_stock_price(_h_summary["stock_id"], days=5)
                if _cur_price is not None and not _cur_price.empty:
                    _cur_val = float(_cur_price["close"].iloc[-1]) * _h_summary["shares"]
                    _total_current += _cur_val
                else:
                    _total_current += _cost  # 抓不到就用成本
            except Exception:
                _total_current += _cost

        _total_pnl = _total_current - _total_invested
        _total_pnl_pct = (_total_current / _total_invested - 1) * 100 if _total_invested > 0 else 0

        _sc1, _sc2, _sc3, _sc4 = st.columns(4)
        with _sc1:
            st.metric("投入成本", f"{_total_invested:,.0f}")
        with _sc2:
            st.metric("目前市值", f"{_total_current:,.0f}")
        with _sc3:
            st.metric("總損益", f"{_total_pnl:+,.0f}", f"{_total_pnl_pct:+.1f}%")
        with _sc4:
            st.metric("持倉數", f"{len(_holdings)} 檔")

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

    # ===== 連續訊號（第三輪升級：動量+信心+回歸偵測）=====
    try:
        streaks = streak.detect_streaks(min_streak=2)
        if streaks:
            st.markdown("---")
            st.markdown("### 🔥 連續訊號")
            greens = {k: v for k, v in streaks.items() if v["type"] == "green"}
            reds = {k: v for k, v in streaks.items() if v["type"] == "red"}
            reversions = {k: v for k, v in streaks.items() if v["type"] == "reversion"}

            if greens:
                for sid, info in sorted(greens.items(), key=lambda x: x[1]["streak"], reverse=True):
                    mom = info.get("momentum", "")
                    conv = info.get("conviction", "")
                    mom_tag = f" [{mom}]" if mom else ""
                    conv_tag = f" 信心{conv}" if conv else ""
                    st.success(f"🟢 **{sid} {info['name']}** 連續 {info['streak']} 天綠燈（平均 {info['avg_score']}/10{mom_tag}{conv_tag}）")
                st.caption("連續 3 天以上綠燈 → 短線進場訊號")

            if reds:
                for sid, info in sorted(reds.items(), key=lambda x: x[1]["streak"], reverse=True):
                    mom = info.get("momentum", "")
                    mom_tag = f" [{mom}]" if mom else ""
                    st.error(f"🔴 **{sid} {info['name']}** 連續 {info['streak']} 天紅燈（平均 {info['avg_score']}/10{mom_tag}）")

            if reversions:
                for sid, info in reversions.items():
                    st.warning(f"🔄 **{sid} {info['name']}** 從紅燈回升（前紅燈均分 {info.get('prev_red_avg', '?')} → 現在 {info['avg_score']}），可能反轉")
    except Exception:
        pass

    # ===== 產業輪動（第三輪升級：相對強弱+波動率調整）=====
    try:
        rotation = sector_rotation.detect_rotation()
        if rotation:
            st.markdown("---")
            st.markdown("### 🔄 產業輪動")
            hot = [r for r in rotation if r["change"] > 0][:3]
            cold = [r for r in rotation if r["change"] < 0][:3]

            if hot:
                for r in hot:
                    rs_tag = f"（{r.get('rs_label', '')}）" if r.get('rs_label') else ""
                    st.success(f"📈 **{r['sector']}** {r['label']}{rs_tag}（{r['previous_avg']} → {r['current_avg']}，{r['change']:+.1f}）")
            if cold:
                for r in cold:
                    rs_tag = f"（{r.get('rs_label', '')}）" if r.get('rs_label') else ""
                    st.error(f"📉 **{r['sector']}** {r['label']}{rs_tag}（{r['previous_avg']} → {r['current_avg']}，{r['change']:+.1f}）")

            if rotation and rotation[0].get("market_avg"):
                st.caption(f"全市場平均分數：{rotation[0]['market_avg']}/10")

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
        budget = st.number_input("投資預算（選填）", value=_EFFECTIVE_BUDGET, step=100000, format="%d")

    if TOTAL_BUDGET == 0 and _EFFECTIVE_BUDGET > 0:
        st.caption(f"💡 TOTAL_BUDGET 未設定，暫用持倉成本估算（{_EFFECTIVE_BUDGET:,} 元）。建議到 .env 設定 TOTAL_BUDGET。")

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

        # 取得總體經濟環境（快取避免重複呼叫）
        try:
            if '_macro_data' not in dir() or _macro_data is None:
                _macro_data = macro.analyze()
                _macro_multiplier = _macro_data["risk_multiplier"]
        except Exception:
            _macro_multiplier = 1.0

        avg, strategy_info = weighted_score(
            tech["score"], fund["score"], inst["score"], news_result["score"], strategy_key,
            is_us=is_us, macro_multiplier=_macro_multiplier,
        )
        signal = overall_signal(avg)

        st.markdown(f"## {stock_id} {name}")
        if ind:
            st.caption(f"產業：{ind} ｜ 策略：{strategy_info['label']}")

        # 評分區 — 一目了然的結論
        st.markdown(f"## {SIGNAL_EMOJI[signal]} {avg}/10")
        if _macro_multiplier < 0.95:
            st.caption(f"⚠ 總體環境偏差，評分已乘以 {_macro_multiplier}（原始 {round(avg / _macro_multiplier, 1)}）")

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

        # [R4] Plotly 互動式 K 線圖
        if not price_df.empty:
            try:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots

                chart_df = price_df.sort_values("date").tail(120).copy()
                chart_df["date"] = pd.to_datetime(chart_df["date"])
                for col in ["open", "close", "max", "min"]:
                    if col in chart_df.columns:
                        chart_df[col] = chart_df[col].astype(float)

                has_ohlc = all(c in chart_df.columns for c in ["open", "max", "min", "close"])

                if has_ohlc:
                    fig = make_subplots(
                        rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03,
                        row_heights=[0.7, 0.3],
                    )

                    # K 線
                    fig.add_trace(go.Candlestick(
                        x=chart_df["date"],
                        open=chart_df["open"], high=chart_df["max"],
                        low=chart_df["min"], close=chart_df["close"],
                        name="K線",
                        increasing_line_color="#EF5350",  # 台股紅漲
                        decreasing_line_color="#26A69A",
                    ), row=1, col=1)

                    # MA5 / MA20
                    close = chart_df["close"]
                    ma5 = close.rolling(5).mean()
                    ma20 = close.rolling(20).mean()
                    fig.add_trace(go.Scatter(
                        x=chart_df["date"], y=ma5,
                        name="MA5", line=dict(color="orange", width=1),
                    ), row=1, col=1)
                    fig.add_trace(go.Scatter(
                        x=chart_df["date"], y=ma20,
                        name="MA20", line=dict(color="blue", width=1),
                    ), row=1, col=1)

                    # 成交量
                    if "Trading_Volume" in chart_df.columns:
                        colors = ["#EF5350" if c >= o else "#26A69A"
                                  for c, o in zip(chart_df["close"], chart_df["open"])]
                        fig.add_trace(go.Bar(
                            x=chart_df["date"],
                            y=chart_df["Trading_Volume"].astype(float),
                            name="成交量", marker_color=colors, opacity=0.5,
                        ), row=2, col=1)

                    fig.update_layout(
                        title=f"{stock_id} {name} — 近 120 日 K 線",
                        xaxis_rangeslider_visible=False,
                        height=500,
                        showlegend=True,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    )
                    fig.update_yaxes(title_text="價格", row=1, col=1)
                    fig.update_yaxes(title_text="量", row=2, col=1)

                    st.plotly_chart(fig, use_container_width=True)
                else:
                    chart_df = chart_df.set_index("date")
                    st.markdown("### 近 120 日走勢")
                    st.line_chart(chart_df["close"])
            except ImportError:
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

        # [R5] Consensus Score — 訊號一致性
        _consensus = calc_consensus_score(
            tech["score"], fund["score"], inst["score"], news_result["score"],
        )
        _cs_dir_map = {"bullish": "多頭", "bearish": "空頭", "mixed": "分歧"}
        _cs_str_map = {"strong": "強", "moderate": "中等", "weak": "弱"}
        _cs_dir_label = _cs_dir_map.get(_consensus["direction"], "分歧")
        _cs_str_label = _cs_str_map.get(_consensus["signal_strength"], "弱")

        if _consensus["signal_strength"] == "strong":
            if _consensus["direction"] == "bullish":
                st.success(f"🔥 訊號一致性 **{_consensus['consensus_score']}/100**（{_cs_str_label}{_cs_dir_label}）— {_consensus['description']}")
            else:
                st.error(f"🔥 訊號一致性 **{_consensus['consensus_score']}/100**（{_cs_str_label}{_cs_dir_label}）— {_consensus['description']}")
        elif _consensus["signal_strength"] == "moderate":
            st.info(f"📊 訊號一致性 **{_consensus['consensus_score']}/100**（{_cs_str_label}{_cs_dir_label}）— {_consensus['description']}")
        else:
            st.warning(f"⚡ 訊號一致性 **{_consensus['consensus_score']}/100**（{_cs_dir_label}）— {_consensus['description']}")

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

        # 資金配置（改進：傳入 ATR 停損 + 相關性資訊）
        if budget > 0 and "current_price" in tech:
            _suggest_stop = tech.get("stop_loss", tech.get("ma20"))
            suggestion = portfolio.suggest(
                avg, tech["current_price"], budget,
                atr=tech.get("atr"),
                stop_price=_suggest_stop if _suggest_stop and _suggest_stop > 0 else None,
            )
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

                # 停損資訊
                _stop = tech.get("stop_loss", tech.get("ma20"))
                if _stop:
                    _stop_pct = (tech["current_price"] - _stop) / tech["current_price"] * 100
                    st.caption(f"📍 建議停損：{_stop:.0f} 元（距現價 -{_stop_pct:.1f}%，ATR 動態計算）")

                # 相關性 / 集中度警告
                if suggestion.get("correlation_warning"):
                    st.warning(suggestion["correlation_warning"])
                if suggestion.get("position_warning"):
                    st.warning(suggestion["position_warning"])

                # [R5] R 系統目標價 — 進場前就知道停損和停利在哪
                import risk_management as _rm_ind
                _ind_atr = tech.get("atr", 0) or tech["current_price"] * 0.02
                _ind_stop = tech.get("stop_loss", tech.get("ma20", 0))
                _ind_tp = _rm_ind.calc_partial_tp(
                    tech["current_price"], tech["current_price"], 1000,
                    entry_stop=_ind_stop if _ind_stop and _ind_stop > 0 else None,
                    atr=_ind_atr,
                )
                if "error" not in _ind_tp:
                    st.markdown("### 🎯 進場目標價（R 系統）")
                    tc1, tc2, tc3, tc4 = st.columns(4)
                    tc1.metric("停損", f"{_ind_tp['entry_stop']:.1f}")
                    tc2.metric("1R 目標（減半倉）", f"{_ind_tp['tp1_price']:.1f}")
                    tc3.metric("2R 目標（出清）", f"{_ind_tp['tp2_price']:.1f}")
                    tc4.metric("3R 延伸", f"{_ind_tp['tp3_price']:.1f}")
                    st.caption(f"1R = {_ind_tp['r_value']:.1f} 元　以現價進場，停損在 {_ind_tp['entry_stop']:.1f}")
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

        # 掃描時取得一次總體經濟環境
        try:
            _scan_macro = macro.analyze()
            _scan_macro_mult = _scan_macro["risk_multiplier"]
        except Exception:
            _scan_macro_mult = 1.0

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

            # 掃描時也抓新聞（用 try 包裝，失敗就給 5 分中性）
            try:
                news_result = news.analyze(stock_id, sname)
                news_score = news_result["score"]
            except Exception:
                news_score = 5.0

            avg, _ = weighted_score(
                tech["score"], fund["score"], inst_result["score"], news_score, strategy_key,
                is_us=market.is_us(stock_id),
                macro_multiplier=_scan_macro_mult,
            )
            signal = overall_signal(avg)

            # 長線分數
            if etf:
                long_score = fund["score"]  # ETF 已經是專用評估
            else:
                long_result = valuation.analyze_longterm(per_df, rev_df, price_df, ind)
                long_score = long_result["score"]

            # [R5] Consensus Score
            _cs = calc_consensus_score(
                tech["score"], fund["score"], inst_result["score"], news_score,
            )
            _cs_icon = "🔥" if _cs["signal_strength"] == "strong" else ("📊" if _cs["signal_strength"] == "moderate" else "⚡")

            return {
                "代號": stock_id,
                "名稱": sname,
                "板塊": stock_sectors[stock_id],
                "技術": tech["score"],
                "基本": fund["score"],
                "籌碼": inst_result["score"],
                "短線": avg,
                "長線": long_score,
                "一致性": f"{_cs_icon}{_cs['consensus_score']}",
                "訊號": SIGNAL_EMOJI[signal],
            }

        done_count = 0
        scan_start_time = time.time()
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_scan_one, sid): sid for sid in all_stocks}
            for future in as_completed(futures):
                done_count += 1
                # Estimate remaining time based on average time per stock so far
                elapsed = time.time() - scan_start_time
                avg_per_stock = elapsed / done_count
                remaining = int(avg_per_stock * (total - done_count))
                if remaining > 60:
                    eta_text = f"，預估剩餘 {remaining // 60} 分 {remaining % 60} 秒"
                elif remaining > 0:
                    eta_text = f"，預估剩餘 {remaining} 秒"
                else:
                    eta_text = "，即將完成"
                progress.progress(
                    done_count / total,
                    text=f"已完成 {done_count}/{total}{eta_text}",
                )
                try:
                    results.append(future.result())
                except Exception:
                    pass

        progress.empty()

        if results:
            df = pd.DataFrame(results).sort_values("短線", ascending=False)

            _green_th = st.session_state.get("green_threshold", 7.0)
            # 短線綠燈
            greens = df[df["短線"] >= _green_th]
            watch = df[(df["短線"] >= _green_th - 1) & (df["短線"] < _green_th)]
            reds = df[df["短線"] < 4]

            # 長線佈局機會（短線低但長線高 = 逢低佈局）
            long_opps = df[(df["長線"] >= _green_th) & (df["短線"] < _green_th)].sort_values("長線", ascending=False)

            # 短線綠燈但長線低 = 矛盾警告
            contradictions = df[(df["短線"] >= _green_th) & (df["長線"] <= 5)]

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

            st.download_button(
                "📥 匯出 CSV",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name="scan_results.csv",
                mime="text/csv",
            )

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
            try:
                _pk_macro_mult = macro.analyze()["risk_multiplier"]
            except Exception:
                _pk_macro_mult = 1.0
            avg, _ = weighted_score(t["score"], f["score"], ins["score"], 5.0, strategy_key,
                                   is_us=market.is_us(sid), macro_multiplier=_pk_macro_mult)
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

                # ===== [R5] 整體資金回撤檢查 =====
                import risk_management as _rm
                _dd_budget = _EFFECTIVE_BUDGET if _EFFECTIVE_BUDGET > 0 else total_cost
                _dd = _rm.check_portfolio_drawdown(
                    [{"buy_price": r["buy_price"], "current_price": r["current_price"],
                      "shares": r["shares"]} for r in results],
                    _dd_budget,
                    drawdown_threshold=st.session_state.get("drawdown_threshold", 15) / 100,
                )
                if _dd["risk_level"] == "critical":
                    st.error(_dd["action"])
                elif _dd["risk_level"] == "warning":
                    st.warning(_dd["action"])
                else:
                    st.info(_dd["action"])
                st.caption(
                    f"持倉成本 {_dd['total_cost']:,.0f} 元　"
                    f"回撤上限 {_dd['threshold_pct']:.0f}%（{_dd_budget * _dd['threshold_pct'] / 100:,.0f} 元）"
                )

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

                        # 停利/停損資訊（第三輪新增）
                        for info_msg in r.get("info", []):
                            st.info(info_msg)

                        # 再進場訊號（第三輪新增）
                        for sig in r.get("reentry_signals", []):
                            st.success(sig)

                        # 週線趨勢
                        wt = r.get("weekly_trend", "")
                        if wt == "bullish":
                            st.caption("📊 週線趨勢：多頭")
                        elif wt == "bearish":
                            st.caption("📊 週線趨勢：空頭")

                        # ===== [R5] 風險管理：ATR 移動停損 + 分批停利 =====
                        _h_data = next((h for h in HOLDINGS if h["stock_id"] == r["stock_id"]), {})
                        _entry_stop = _h_data.get("stop_loss", 0) or 0
                        _peak = _h_data.get("peak_price", None)
                        # 從 atr_stop 反推 ATR（atr_stop = buy_price - 2×ATR）
                        _atr_stop_price = r.get("atr_stop", 0) or 0
                        _buy_p = r["buy_price"]
                        _atr_mult = st.session_state.get("atr_multiplier", 2.0)
                        _atr_est = (_buy_p - _atr_stop_price) / _atr_mult if _atr_stop_price > 0 and _buy_p > _atr_stop_price else _buy_p * 0.02

                        with st.expander("🛡 風險管理詳情"):
                            _rm_c1, _rm_c2 = st.columns(2)
                            _trail = _rm.calc_atr_trailing_stop(
                                r["current_price"], _buy_p, _peak, _atr_est,
                            )
                            with _rm_c1:
                                st.markdown("**ATR 移動停損**")
                                st.metric("移動停損價", f"{_trail['trailing_stop']:.1f} 元",
                                          delta=f"距現價 {(r['current_price'] - _trail['trailing_stop']):.1f}" if r['current_price'] > 0 else None)
                                st.caption(f"類型：{_trail['stop_type']}")
                                st.caption(f"ATR 距離：{_trail['atr_distance']:.1f} 元（停損幅 {_trail['stop_pct']:.1f}%）")
                                if _trail["should_exit"]:
                                    st.error("🚨 已觸及移動停損！建議立即執行")

                            _eff_stop = _entry_stop if _entry_stop > 0 else _trail["initial_stop"]
                            _tp = _rm.calc_partial_tp(
                                r["current_price"], _buy_p, r["shares"],
                                entry_stop=_eff_stop,
                            )
                            with _rm_c2:
                                st.markdown("**分批停利（R 系統）**")
                                r_color = "normal" if _tp["current_r"] >= 0 else "inverse"
                                st.metric("當前 R 倍數", f"{_tp['current_r']:+.2f} R", delta_color=r_color)
                                st.caption(f"1R 目標：{_tp['tp1_price']:.1f} 元 → 減 {_tp['tp1_shares']} 股")
                                st.caption(f"2R 目標：{_tp['tp2_price']:.1f} 元 → 減 {_tp['tp2_shares']} 股")
                                if _tp["tp2_reached"]:
                                    st.success(_tp["action"])
                                elif _tp["tp1_reached"]:
                                    st.info(_tp["action"])
                                else:
                                    st.caption(_tp["action"])

                            _metrics = _rm.get_position_risk_metrics(
                                {"buy_price": _buy_p, "shares": r["shares"],
                                 "current_price": r["current_price"], "stop_loss": _eff_stop},
                                _EFFECTIVE_BUDGET if _EFFECTIVE_BUDGET > 0 else total_cost,
                                trailing_stop_price=_trail["trailing_stop"],
                            )
                            st.caption(
                                f"倉位佔總資金 **{_metrics['position_pct']:.1f}%**　"
                                f"停損風險 **{_metrics['risk_pct']:.2f}%** 總資金　"
                                f"最大虧損額 **{_metrics['risk_amount']:,.0f} 元**"
                            )

                # 關聯性分析（第三輪升級：壓力測試 + 穩定度）
                if len(results) >= 2:
                    st.markdown("### 🔗 持倉關聯性分析")
                    stock_ids = [r["stock_id"] for r in results]

                    with st.spinner("計算關聯性（含壓力測試）..."):
                        div = correlation.check_diversification(stock_ids)

                    for d in div["details"]:
                        if d.strip():
                            st.caption(d)

                    if not div["matrix"].empty:
                        st.markdown("**相關係數矩陣**（越接近 1 = 越容易同漲同跌）")
                        st.dataframe(div["matrix"], use_container_width=True)

                    # 壓力測試矩陣
                    if not div.get("stress_matrix", pd.DataFrame()).empty:
                        with st.expander("壓力測試矩陣（下跌日的相關性）"):
                            st.caption("市場下跌時的相關性 — 數字越高表示崩盤時越容易一起跌")
                            st.dataframe(div["stress_matrix"], use_container_width=True)


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

            # ===== [R5] 訊號一致性分析 =====
            st.markdown("---")
            st.markdown("### 🔄 訊號一致性分析（Consensus Score）")
            st.caption("統計多少個指標同方向，分歧大的訊號信心度自動降低")

            from scoring import calc_consensus_score as _calc_cs
            _cs_df_rows = []
            for _, row in df.iterrows():
                cs = _calc_cs(row.get("tech", 5), row.get("fund", 5),
                              row.get("inst", 5), row.get("news", 5) if "news" in row else 5)
                _cs_df_rows.append({
                    "代號": row.get("stock_id", ""),
                    "名稱": row.get("name", ""),
                    "綜合": row.get("avg", 0),
                    "一致性": cs["consensus_score"],
                    "方向": "多頭" if cs["direction"] == "bullish" else ("空頭" if cs["direction"] == "bearish" else "分歧"),
                    "強度": cs["signal_strength"],
                    "說明": cs["description"],
                })
            if _cs_df_rows:
                _cs_df = pd.DataFrame(_cs_df_rows).sort_values("一致性", ascending=False)
                # 強訊號
                _strong = _cs_df[(_cs_df["強度"] == "strong") & (_cs_df["方向"] == "多頭")]
                if not _strong.empty:
                    st.success(f"⭐ 強多頭訊號（{len(_strong)} 檔）：{', '.join(_strong['名稱'].tolist()[:5])}")
                _weak_conflict = _cs_df[(_cs_df["一致性"] < 50) & (_cs_df["綜合"] >= 6)]
                if not _weak_conflict.empty:
                    st.warning(f"⚠ 高分但訊號分歧（{len(_weak_conflict)} 檔）：{', '.join(_weak_conflict['名稱'].tolist()[:5])}")
                with st.expander("查看完整一致性分析"):
                    st.dataframe(_cs_df[["代號", "名稱", "綜合", "一致性", "方向", "強度", "說明"]],
                                 use_container_width=True, hide_index=True)

            # ===== [R5] 校準結果（儲存 + 顯示）=====
            st.markdown("---")
            st.markdown("### ⚙ 權重校準")
            st.caption("分析歷史訊號與實際報酬的相關性，找出最有效的權重組合")

            import calibration as _calib

            _saved = _calib.load_calibration_results()
            if _saved:
                _sr = _saved.get("results", {})
                st.success(f"上次校準：{_saved.get('saved_at', '')[:10]}　樣本 {_sr.get('sample_count', 0)} 筆　最佳窗口 {_sr.get('best_window', '?')} 天")
                if _sr.get("recommended_weights"):
                    _rw = _sr["recommended_weights"]
                    st.markdown("**校準推薦權重：**")
                    wc1, wc2, wc3, wc4 = st.columns(4)
                    wc1.metric("技術面", f"{_rw.get('tech', 0)*100:.0f}%")
                    wc2.metric("基本面", f"{_rw.get('fund', 0)*100:.0f}%")
                    wc3.metric("籌碼面", f"{_rw.get('inst', 0)*100:.0f}%")
                    wc4.metric("消息面", f"{_rw.get('news', 0)*100:.0f}%")

                if _sr.get("multi_window"):
                    with st.expander("各持有週期相關性"):
                        _mw = _sr["multi_window"]
                        _rows = []
                        for w, info in sorted(_mw.items()):
                            _rows.append({
                                "持有天數": f"{w}天",
                                "樣本數": info.get("sample_count", 0),
                                "技術相關": info.get("correlations", {}).get("tech", {}).get("combined", 0),
                                "基本相關": info.get("correlations", {}).get("fund", {}).get("combined", 0),
                                "籌碼相關": info.get("correlations", {}).get("inst", {}).get("combined", 0),
                                "消息相關": info.get("correlations", {}).get("news", {}).get("combined", 0),
                            })
                        if _rows:
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

                if _sr.get("band_accuracy"):
                    with st.expander("分數分段準確率"):
                        _ba = _sr["band_accuracy"]
                        _ba_rows = []
                        for band, info in _ba.items():
                            if info.get("count", 0) > 0:
                                _ba_rows.append({
                                    "分段": {"high": "高分（≥7）", "mid": "中分（4-7）", "low": "低分（<4）"}.get(band, band),
                                    "樣本數": info["count"],
                                    "準確率": f"{info['accuracy']:.1f}%",
                                    "平均報酬": f"{info['avg_return']:+.2f}%",
                                })
                        if _ba_rows:
                            st.dataframe(pd.DataFrame(_ba_rows), use_container_width=True, hide_index=True)

            if st.button("執行權重校準（需要歷史資料）", use_container_width=True):
                with st.spinner("計算中（分析多個時間窗口，需要幾分鐘）..."):
                    try:
                        _calib_result = _calib.calibrate(market.fetch_stock_price)
                        if _calib_result.get("status") == "ok":
                            _calib.save_calibration_results(_calib_result)
                            st.success(f"校準完成！樣本 {_calib_result['sample_count']} 筆，最佳窗口 {_calib_result['best_window']} 天")
                            st.rerun()
                        else:
                            st.warning(_calib_result.get("message", "校準失敗"))
                    except Exception as _e:
                        st.error(f"校準失敗：{_e}")


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

                        try:
                            _cw_macro_mult = macro.analyze()["risk_multiplier"]
                        except Exception:
                            _cw_macro_mult = 1.0
                        avg, _ = weighted_score(
                            tech["score"], fund["score"], inst_result["score"], 5.0, strategy_key,
                            is_us=market.is_us(sid),
                            macro_multiplier=_cw_macro_mult,
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

# ===== [R4] 持倉分析 =====
elif page == "📊 持倉分析":
    st.title("📊 持倉分析")
    st.caption("持倉的風險分析、相關性矩陣、配置建議")

    # 讀持倉
    _pa_holdings = []
    try:
        _vars = {}
        _hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.py")
        with open(_hp, "r", encoding="utf-8") as f:
            exec(f.read(), _vars)
        _pa_holdings = _vars.get("HOLDINGS", [])
    except Exception:
        pass
    if not _pa_holdings:
        try:
            import json as _json
            raw = ""
            if "HOLDINGS_JSON" in st.secrets:
                raw = st.secrets["HOLDINGS_JSON"]
            elif "HOLDINGS" in st.secrets and "json" in st.secrets["HOLDINGS"]:
                raw = st.secrets["HOLDINGS"]["json"]
            if raw:
                _pa_holdings = _json.loads(raw)
        except Exception:
            pass

    if not _pa_holdings:
        st.warning("沒有持倉資料。請先到 holdings.py 或 Streamlit Secrets 設定持倉。")
    else:
        stock_ids = [h["stock_id"] for h in _pa_holdings]
        st.markdown(f"**持有 {len(stock_ids)} 檔：** {', '.join(stock_ids)}")

        with st.spinner("計算持倉分析..."):
            # 1. 抓各持倉價格
            price_dict = {}
            returns_dict = {}
            for sid in stock_ids:
                try:
                    pdf = market.fetch_stock_price(sid, days=120)
                    if pdf is not None and not pdf.empty:
                        pdf = pdf.sort_values("date").reset_index(drop=True)
                        pdf["close"] = pdf["close"].astype(float)
                        price_dict[sid] = pdf
                        ret = pdf["close"].pct_change().dropna()
                        returns_dict[sid] = ret.values[-60:] if len(ret) >= 60 else ret.values
                except Exception:
                    pass

            # 2. 相關性矩陣
            if len(returns_dict) >= 2:
                st.markdown("### 相關性矩陣")
                st.caption("數值越高，兩檔股票走勢越同步（分散度越低）")

                # 對齊長度
                min_len = min(len(v) for v in returns_dict.values())
                aligned = {k: v[:min_len] for k, v in returns_dict.items()}
                corr_df = pd.DataFrame(aligned).corr()

                try:
                    import plotly.express as px
                    fig_corr = px.imshow(
                        corr_df, text_auto=".2f",
                        color_continuous_scale="RdYlGn_r",
                        zmin=-1, zmax=1,
                        title="持倉相關性矩陣",
                    )
                    fig_corr.update_layout(height=400)
                    st.plotly_chart(fig_corr, use_container_width=True)
                except ImportError:
                    st.dataframe(corr_df.style.format("{:.2f}"))

                # 高相關警告
                high_corr_pairs = []
                cols = list(corr_df.columns)
                for i in range(len(cols)):
                    for j in range(i + 1, len(cols)):
                        c = corr_df.iloc[i, j]
                        if c > 0.7:
                            high_corr_pairs.append((cols[i], cols[j], c))
                if high_corr_pairs:
                    st.warning("⚠ 高相關持倉（> 0.7）：")
                    for a, b, c in sorted(high_corr_pairs, key=lambda x: -x[2]):
                        st.caption(f"　{a} ↔ {b}：{c:.2f}（分散效果差）")

            # 3. 持倉配置比例
            st.markdown("### 配置比例")
            position_values = {}
            total_value = 0
            for h in _pa_holdings:
                sid = h["stock_id"]
                qty = h.get("shares", 0)
                if sid in price_dict and qty > 0:
                    current_price = float(price_dict[sid]["close"].iloc[-1])
                    val = current_price * qty
                    position_values[sid] = val
                    total_value += val

            if total_value > 0:
                pct_data = {k: round(v / total_value * 100, 1) for k, v in position_values.items()}

                try:
                    import plotly.express as px
                    fig_pie = px.pie(
                        names=list(pct_data.keys()),
                        values=list(pct_data.values()),
                        title="持倉佔比",
                    )
                    fig_pie.update_traces(textposition="inside", textinfo="label+percent")
                    fig_pie.update_layout(height=400)
                    st.plotly_chart(fig_pie, use_container_width=True)
                except ImportError:
                    for sid, pct in sorted(pct_data.items(), key=lambda x: -x[1]):
                        st.caption(f"　{sid}：{pct}%")

                # 集中度警告
                max_pct = max(pct_data.values()) if pct_data else 0
                if max_pct > 30:
                    st.error(f"🚨 最大單一持倉佔 {max_pct:.0f}%，建議不超過 30%")
                elif max_pct > 20:
                    st.warning(f"⚠ 最大單一持倉佔 {max_pct:.0f}%，偏高")

                st.caption(f"持倉總市值：{total_value:,.0f} 元")

            # 4. 波動率分析
            st.markdown("### 個股波動率（年化）")
            vol_data = {}
            for sid, rets in returns_dict.items():
                if len(rets) >= 10:
                    daily_vol = np.std(rets)
                    annual_vol = daily_vol * np.sqrt(252) * 100
                    vol_data[sid] = round(annual_vol, 1)

            if vol_data:
                vol_df = pd.DataFrame({"年化波動率(%)": vol_data}).sort_values("年化波動率(%)", ascending=False)
                st.bar_chart(vol_df)

                high_vol = {k: v for k, v in vol_data.items() if v > 40}
                if high_vol:
                    st.warning(f"⚠ 高波動持倉（年化 > 40%）：{', '.join(f'{k}({v}%)' for k, v in high_vol.items())}")

            # 5. Kelly 建議（如果有回測資料）
            st.markdown("### Kelly Criterion 建議")
            st.caption("基於歷史勝率和盈虧比的最佳倉位比例")
            from portfolio import _kelly_fraction
            for sid in stock_ids:
                if sid in returns_dict and len(returns_dict[sid]) >= 20:
                    rets = returns_dict[sid]
                    wins = [r for r in rets if r > 0]
                    losses = [r for r in rets if r < 0]
                    if wins and losses:
                        wr = len(wins) / len(rets)
                        avg_w = np.mean(wins) * 100
                        avg_l = abs(np.mean(losses)) * 100
                        kelly = _kelly_fraction(wr, avg_w, avg_l)
                        st.caption(
                            f"　{sid}：勝率 {wr:.0%}　盈虧比 {avg_w/avg_l:.2f}　"
                            f"→ Half-Kelly 建議 {kelly*100:.1f}%"
                        )

            # 匯出持倉分析 CSV
            st.markdown("---")
            _pa_rows = []
            for h in _pa_holdings:
                sid = h["stock_id"]
                row = {"代號": sid, "股數": h["shares"], "買入價": h["buy_price"]}
                if sid in position_values:
                    row["市值"] = round(position_values[sid], 0)
                    row["佔比(%)"] = pct_data.get(sid, 0) if total_value > 0 else 0
                if sid in vol_data:
                    row["年化波動率(%)"] = vol_data[sid]
                _pa_rows.append(row)
            if _pa_rows:
                _pa_df = pd.DataFrame(_pa_rows)
                st.download_button(
                    "📥 匯出持倉分析 CSV",
                    data=_pa_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="portfolio_analysis.csv",
                    mime="text/csv",
                )


# ===== [R5] 交易日誌 =====
elif page == "📒 交易日誌":
    st.title("📒 交易日誌")
    st.caption("記錄每筆進出場，追蹤真實績效，計算 Alpha")

    import trade_journal as tj

    tab_open, tab_closed, tab_stats, tab_add = st.tabs(
        ["📌 持倉中", "📜 歷史交易", "📊 績效報告", "➕ 新增記錄"]
    )

    # ── Tab 1: 持倉中的交易 ──────────────────────────────────────────────────
    with tab_open:
        st.markdown("### 目前持倉中的交易")
        open_trades = tj.get_all_trades(open_only=True)
        if not open_trades:
            st.info("目前沒有持倉中的交易記錄。到「新增記錄」tab 輸入進場資訊。")
        else:
            for t in open_trades:
                with st.expander(f"#{t['id']} {t['stock_id']} {t['name']}　進場 {t['entry_date']}　@{t['entry_price']:.1f}　{t['shares']} 股"):
                    oc1, oc2, oc3 = st.columns(3)
                    oc1.metric("進場價", f"{t['entry_price']:.1f}")
                    oc2.metric("進場分數", f"{t['entry_score']:.1f}/10" if t['entry_score'] else "—")
                    oc3.metric("策略", t.get("strategy", "—"))
                    if t.get("entry_reason"):
                        st.caption(f"進場理由：{t['entry_reason']}")

                    st.markdown("**記錄出場**")
                    xc1, xc2 = st.columns(2)
                    with xc1:
                        _xdate = st.date_input("出場日期", key=f"xd_{t['id']}")
                        _xprice = st.number_input("出場價", min_value=0.0, step=0.1, key=f"xp_{t['id']}", format="%.1f")
                    with xc2:
                        _xreason = st.text_input("出場理由", placeholder="停損/停利/訊號轉空…", key=f"xr_{t['id']}")
                        _xus = st.checkbox("美股（免稅費）", key=f"xu_{t['id']}")
                    if st.button("確認出場", key=f"close_{t['id']}", type="primary"):
                        if _xprice > 0:
                            res = tj.close_trade(t["id"], str(_xdate), _xprice, _xreason, _xus)
                            if "error" not in res:
                                pnl_color = "✅" if res["pnl"] >= 0 else "🔴"
                                st.success(f"{pnl_color} 已結算：損益 {res['pnl']:+,.0f} 元（{res['pnl_pct']:+.2f}%）")
                                st.rerun()
                            else:
                                st.error(res["error"])
                    if st.button("🗑 刪除", key=f"del_open_{t['id']}"):
                        tj.delete_trade(t["id"])
                        st.rerun()

    # ── Tab 2: 歷史已結算交易 ────────────────────────────────────────────────
    with tab_closed:
        st.markdown("### 歷史交易記錄")
        closed_df = tj.get_trades_df()
        if closed_df.empty:
            st.info("還沒有已結算的交易記錄。")
        else:
            # 格式化顯示
            disp = closed_df[[
                "id", "stock_id", "name", "strategy",
                "entry_date", "entry_price", "exit_date", "exit_price",
                "shares", "pnl", "pnl_pct", "entry_reason", "exit_reason",
            ]].copy()
            disp.columns = [
                "ID", "代號", "名稱", "策略",
                "進場日", "進場價", "出場日", "出場價",
                "股數", "損益(元)", "損益(%)", "進場理由", "出場理由",
            ]
            st.dataframe(disp, use_container_width=True, hide_index=True, height=500)

            # 刪除功能
            del_id = st.number_input("輸入 ID 刪除記錄", min_value=1, step=1, value=1, key="del_id")
            if st.button("刪除此筆", key="del_closed"):
                tj.delete_trade(int(del_id))
                st.rerun()

    # ── Tab 3: 績效報告 ──────────────────────────────────────────────────────
    with tab_stats:
        st.markdown("### 整體績效")
        _all_stats = tj.get_monthly_stats()

        if _all_stats["trade_count"] == 0:
            st.info("尚無已結算交易，無法計算績效。")
        else:
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("總交易筆數", _all_stats["trade_count"])
            sc2.metric("勝率", f"{_all_stats['win_rate']:.1f}%")
            sc3.metric("複利總報酬", f"{_all_stats['total_return_pct']:+.2f}%")
            sc4.metric("盈虧比", f"{_all_stats['profit_factor']:.2f}")

            sc5, sc6, sc7, sc8 = st.columns(4)
            sc5.metric("總損益", f"{_all_stats['total_pnl']:+,.0f} 元")
            sc6.metric("最大回撤", f"{_all_stats['max_drawdown_pct']:.2f}%", delta_color="inverse")
            sc7.metric("平均獲利", f"{_all_stats['avg_win_pct']:+.2f}%")
            sc8.metric("平均虧損", f"-{_all_stats['avg_loss_pct']:.2f}%")

            # Alpha 計算
            st.markdown("---")
            st.markdown("### Alpha（超額報酬）")
            _alpha = tj.calc_alpha(market.fetch_stock_price, "0050")
            if _alpha["has_benchmark"]:
                ac1, ac2, ac3 = st.columns(3)
                ac1.metric("系統報酬", f"{_alpha['system_total_return']:+.2f}%")
                ac2.metric("0050 報酬", f"{_alpha['benchmark_return']:+.2f}%")
                delta_val = _alpha['alpha']
                ac3.metric("Alpha", f"{delta_val:+.2f}%",
                           delta=f"{'跑贏' if delta_val >= 0 else '跑輸'}大盤 {abs(delta_val):.2f}%")
                st.caption(f"計算期間：{_alpha['period']}　共 {_alpha['trade_count']} 筆交易")
            else:
                st.info(f"系統總報酬 {_alpha['system_total_return']:+.2f}%（無法取得大盤資料做比較）")

            # 月度報酬折線圖
            st.markdown("---")
            st.markdown("### 月度績效")
            _monthly = tj.get_monthly_breakdown()
            if _monthly:
                _mdf = pd.DataFrame(_monthly)
                _mdf = _mdf.set_index("year_month")

                _mret_col, _mwin_col = st.columns(2)
                with _mret_col:
                    st.markdown("**月報酬率（%）**")
                    st.bar_chart(_mdf["total_return_pct"])
                with _mwin_col:
                    st.markdown("**月勝率（%）**")
                    st.line_chart(_mdf["win_rate"])

                with st.expander("月度明細表"):
                    _mdf_disp = _mdf.reset_index().rename(columns={
                        "year_month": "月份", "trade_count": "交易數",
                        "win_rate": "勝率(%)", "total_pnl": "損益(元)",
                        "total_return_pct": "月報酬(%)",
                    })
                    st.dataframe(_mdf_disp, use_container_width=True, hide_index=True)

            # 最佳 / 最差
            st.markdown("---")
            _best = _all_stats.get("best_trade", {})
            _worst = _all_stats.get("worst_trade", {})
            if _best and _worst:
                bwc1, bwc2 = st.columns(2)
                with bwc1:
                    st.success(
                        f"🏆 最佳交易：{_best.get('stock_id','')} {_best.get('name','')}　"
                        f"{_best.get('pnl_pct',0):+.2f}%"
                    )
                with bwc2:
                    st.error(
                        f"💔 最差交易：{_worst.get('stock_id','')} {_worst.get('name','')}　"
                        f"{_worst.get('pnl_pct',0):+.2f}%"
                    )

    # ── Tab 4: 新增記錄 ──────────────────────────────────────────────────────
    with tab_add:
        st.markdown("### 新增交易記錄")
        with st.form("add_trade_form"):
            fc1, fc2 = st.columns(2)
            with fc1:
                _new_sid = st.text_input("股票代號", placeholder="例：2330 / NVDA")
                _new_name = st.text_input("股票名稱（選填）", placeholder="例：台積電")
                _new_edate = st.date_input("進場日期")
                _new_eprice = st.number_input("進場價格", min_value=0.0, step=0.1, format="%.2f")
            with fc2:
                _new_shares = st.number_input("股數", min_value=1, step=100, value=1000)
                _new_score = st.number_input("系統評分", min_value=0.0, max_value=10.0, step=0.1, value=6.0)
                _new_strat = st.selectbox("策略", list(STRATEGIES.keys()),
                                          format_func=lambda k: STRATEGIES[k]["label"])
                _new_reason = st.text_area("進場理由", placeholder="例：技術面突破 + 籌碼買超，評分 7.2/10")
            _submitted = st.form_submit_button("記錄進場", type="primary", use_container_width=True)
            if _submitted and _new_sid and _new_eprice > 0 and _new_shares > 0:
                _new_id = tj.add_entry(
                    stock_id=_new_sid.strip().upper(),
                    entry_date=str(_new_edate),
                    entry_price=_new_eprice,
                    shares=int(_new_shares),
                    name=_new_name.strip(),
                    strategy=_new_strat,
                    entry_score=_new_score,
                    entry_reason=_new_reason.strip(),
                )
                st.success(f"已記錄進場！ID={_new_id}，到「持倉中」tab 管理出場。")
                st.rerun()
