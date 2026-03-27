"""
總體經濟環境模組
用 VIX、美債殖利率、台幣匯率等指標判斷大盤風險
當總體環境惡化時，個股評分應該自動降級
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from cache import get_cache, set_cache


def _fetch_with_cache(ticker_symbol, days=90, cache_key=None):
    """從 yfinance 抓資料，帶快取"""
    if cache_key:
        cached = get_cache(cache_key)
        if cached is not None:
            return pd.DataFrame(cached)

    try:
        t = yf.Ticker(ticker_symbol)
        end = datetime.now()
        start = end - timedelta(days=days)
        df = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if df.empty:
            return pd.DataFrame()

        df = df.reset_index()
        if hasattr(df["Date"].dtype, "tz") and df["Date"].dt.tz is not None:
            df["Date"] = df["Date"].dt.tz_localize(None)

        if cache_key and not df.empty:
            set_cache(cache_key, df.to_dict("records"), ttl_hours=4)

        return df
    except Exception:
        return pd.DataFrame()


def fetch_vix():
    """取得 VIX 恐慌指數"""
    return _fetch_with_cache("^VIX", days=90, cache_key="macro_vix")


def fetch_us10y():
    """取得美國 10 年期公債殖利率"""
    return _fetch_with_cache("^TNX", days=90, cache_key="macro_us10y")


def fetch_twd():
    """取得台幣/美元匯率"""
    return _fetch_with_cache("TWD=X", days=90, cache_key="macro_twd")


def fetch_sp500():
    """取得 S&P 500 指數"""
    return _fetch_with_cache("^GSPC", days=90, cache_key="macro_sp500")


def analyze():
    """
    總體經濟環境分析
    回傳：{
        "score": 1-10,
        "signal": "green/yellow/red",
        "details": list,
        "risk_multiplier": 0.7-1.0（用來調降個股評分）
    }
    """
    score = 5.0
    details = []
    details.append("— 總體經濟環境評估")

    # ===== VIX 恐慌指數 =====
    vix_df = fetch_vix()
    if not vix_df.empty and "Close" in vix_df.columns:
        current_vix = float(vix_df["Close"].iloc[-1])
        vix_ma20 = float(vix_df["Close"].tail(20).mean()) if len(vix_df) >= 20 else current_vix
        vix_trend = "上升" if current_vix > vix_ma20 * 1.1 else ("下降" if current_vix < vix_ma20 * 0.9 else "持平")

        if current_vix > 30:
            details.append(f"🚨 VIX = {current_vix:.1f}（恐慌區，市場極度不安）")
            score -= 3
        elif current_vix > 25:
            details.append(f"⚠ VIX = {current_vix:.1f}（警戒區，波動加大）")
            score -= 2
        elif current_vix > 20:
            details.append(f"⚠ VIX = {current_vix:.1f}（偏高，需謹慎，趨勢{vix_trend}）")
            score -= 1
        elif current_vix < 13:
            details.append(f"✓ VIX = {current_vix:.1f}（極低，市場平靜，但小心自滿）")
            score += 0.5
        else:
            details.append(f"✓ VIX = {current_vix:.1f}（正常範圍，趨勢{vix_trend}）")
            score += 1
    else:
        details.append("— VIX 資料暫時無法取得")

    # ===== 美國 10 年期公債殖利率 =====
    us10y_df = fetch_us10y()
    if not us10y_df.empty and "Close" in us10y_df.columns:
        current_yield = float(us10y_df["Close"].iloc[-1])
        # 殖利率變化（30 天前 vs 現在）
        if len(us10y_df) >= 20:
            yield_30d_ago = float(us10y_df["Close"].iloc[-20])
            yield_change = current_yield - yield_30d_ago

            if current_yield > 5.0:
                details.append(f"🚨 美10年債殖利率 {current_yield:.2f}%（極高，資金緊縮，對股市壓力大）")
                score -= 2
            elif current_yield > 4.5:
                details.append(f"⚠ 美10年債殖利率 {current_yield:.2f}%（偏高，成長股承壓）")
                score -= 1
            elif current_yield < 3.5:
                details.append(f"✓ 美10年債殖利率 {current_yield:.2f}%（偏低，有利股市）")
                score += 1
            else:
                details.append(f"— 美10年債殖利率 {current_yield:.2f}%（中性）")

            # 快速上升是危險訊號
            if yield_change > 0.5:
                details.append(f"⚠ 殖利率近20日上升 {yield_change:+.2f}%（快速上升，注意）")
                score -= 1
            elif yield_change < -0.3:
                details.append(f"✓ 殖利率近20日下降 {yield_change:+.2f}%（資金環境改善）")
                score += 0.5
    else:
        details.append("— 美債殖利率資料暫時無法取得")

    # ===== S&P 500 趨勢（代表全球風險偏好）=====
    sp500_df = fetch_sp500()
    if not sp500_df.empty and "Close" in sp500_df.columns:
        closes = sp500_df["Close"].astype(float)
        if len(closes) >= 50:
            current = closes.iloc[-1]
            ma20 = closes.tail(20).mean()
            ma50 = closes.tail(50).mean()

            above_ma20 = current > ma20
            above_ma50 = current > ma50

            if above_ma20 and above_ma50:
                details.append(f"✓ S&P500 多頭排列（站上 20/50 日均線）")
                score += 1
            elif not above_ma20 and not above_ma50:
                details.append(f"⚠ S&P500 偏空（跌破 20/50 日均線）")
                score -= 1.5
            else:
                details.append(f"— S&P500 震盪中")

            # 近期漲跌幅
            pct_20d = (current / closes.iloc[-20] - 1) * 100 if len(closes) >= 20 else 0
            if pct_20d < -10:
                details.append(f"🚨 S&P500 近20日跌 {pct_20d:.1f}%（系統性風險）")
                score -= 2
            elif pct_20d < -5:
                details.append(f"⚠ S&P500 近20日跌 {pct_20d:.1f}%（回檔明顯）")
                score -= 1
    else:
        details.append("— S&P500 資料暫時無法取得")

    # ===== 台幣匯率（台股專用）=====
    twd_df = fetch_twd()
    if not twd_df.empty and "Close" in twd_df.columns:
        current_twd = float(twd_df["Close"].iloc[-1])
        if len(twd_df) >= 20:
            twd_20d_ago = float(twd_df["Close"].iloc[-20])
            twd_change_pct = (current_twd / twd_20d_ago - 1) * 100

            details.append(f"— 台幣匯率 {current_twd:.2f}（近20日變化 {twd_change_pct:+.1f}%）")

            # 台幣急貶 = 外資撤離警訊
            if twd_change_pct > 3:
                details.append(f"⚠ 台幣急貶，外資可能撤出台股")
                score -= 1
            elif twd_change_pct < -2:
                details.append(f"✓ 台幣走升，有利外資回流")
                score += 0.5

    # ===== 結算 =====
    score = max(1.0, min(10.0, score))

    if score >= 7:
        signal = "green"
    elif score >= 4:
        signal = "yellow"
    else:
        signal = "red"

    # 風險乘數：macro 分數越低，個股評分應該越保守
    # score 7+ → 1.0（不調整）
    # score 4-7 → 0.9-1.0（微調）
    # score <4 → 0.7-0.9（明顯降級）
    if score >= 7:
        risk_multiplier = 1.0
    elif score >= 4:
        risk_multiplier = 0.9 + (score - 4) / 30  # 4→0.9, 7→1.0
    else:
        risk_multiplier = 0.7 + (score - 1) / 15  # 1→0.7, 4→0.9

    risk_multiplier = round(max(0.7, min(1.0, risk_multiplier)), 2)

    details.append("")
    if risk_multiplier < 0.95:
        details.append(f"⚠ 總體環境偏差，個股評分將乘以 {risk_multiplier}（自動降級）")
    else:
        details.append(f"✓ 總體環境正常，個股評分不調整")

    return {
        "score": round(score, 1),
        "signal": signal,
        "details": details,
        "risk_multiplier": risk_multiplier,
    }
