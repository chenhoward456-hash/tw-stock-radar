"""
總體經濟環境模組（第四輪：殖利率曲線倒掛 + 信用利差 + 連續指標）

改進：
1. [R4] 殖利率曲線倒掛偵測（10Y vs 3M spread）
2. [R4] 信用利差（HYG/TLT 比值變化）
3. [R4] 恐慌/貪婪連續指標（0-100）
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import cache


def _fetch_with_cache(ticker_symbol, days=90, cache_key=None):
    """從 yfinance 抓資料，帶快取"""
    if cache_key:
        cached, hit = cache.get(cache_key)
        if hit and cached is not None:
            return pd.DataFrame(cached) if not isinstance(cached, pd.DataFrame) else cached

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
            cache.put(cache_key, df, cache.TTL_REALTIME)

        return df
    except Exception:
        return pd.DataFrame()


def fetch_vix():
    return _fetch_with_cache("^VIX", days=90, cache_key="macro_vix")


def fetch_us10y():
    return _fetch_with_cache("^TNX", days=90, cache_key="macro_us10y")


def fetch_us3m():
    """[R4] 取得美國 3 個月期國庫券利率"""
    return _fetch_with_cache("^IRX", days=90, cache_key="macro_us3m")


def fetch_twd():
    return _fetch_with_cache("TWD=X", days=90, cache_key="macro_twd")


def fetch_sp500():
    return _fetch_with_cache("^GSPC", days=90, cache_key="macro_sp500")


def fetch_hyg():
    """[R4] 高收益債 ETF"""
    return _fetch_with_cache("HYG", days=90, cache_key="macro_hyg")


def fetch_tlt():
    """[R4] 長期國債 ETF"""
    return _fetch_with_cache("TLT", days=90, cache_key="macro_tlt")


def _yield_curve_signal(us10y_df, us3m_df):
    """[R4] 殖利率曲線倒掛偵測"""
    if us10y_df.empty or us3m_df.empty:
        return 0, None
    if "Close" not in us10y_df.columns or "Close" not in us3m_df.columns:
        return 0, None

    try:
        y10 = float(us10y_df["Close"].iloc[-1])
        y3m = float(us3m_df["Close"].iloc[-1]) / 10  # ^IRX 單位是 bp/10
        spread = y10 - y3m

        if spread < -0.5:
            return -2, f"🚨 殖利率曲線深度倒掛（10Y-3M={spread:+.2f}%），衰退風險高"
        elif spread < 0:
            return -1, f"⚠ 殖利率曲線倒掛（10Y-3M={spread:+.2f}%），留意衰退訊號"
        elif spread < 0.5:
            return 0, f"— 殖利率曲線接近平坦（10Y-3M={spread:+.2f}%）"
        else:
            return 0.5, f"✓ 殖利率曲線正常（10Y-3M={spread:+.2f}%）"
    except Exception:
        return 0, None


def _credit_spread_signal(hyg_df, tlt_df):
    """[R4] 信用利差近似指標（HYG/TLT 比值變化）"""
    if hyg_df.empty or tlt_df.empty:
        return 0, None
    if "Close" not in hyg_df.columns or "Close" not in tlt_df.columns:
        return 0, None

    try:
        hyg = hyg_df["Close"].astype(float)
        tlt = tlt_df["Close"].astype(float)

        if len(hyg) < 20 or len(tlt) < 20:
            return 0, None

        ratio_now = float(hyg.iloc[-1] / tlt.iloc[-1])
        ratio_20d = float(hyg.iloc[-20] / tlt.iloc[-20])
        change = (ratio_now / ratio_20d - 1) * 100

        if change < -5:
            return -2, f"🚨 信用利差急擴（HYG/TLT 20日 {change:+.1f}%），資金逃離風險資產"
        elif change < -2:
            return -1, f"⚠ 信用利差擴大（HYG/TLT 20日 {change:+.1f}%）"
        elif change > 3:
            return 0.5, f"✓ 信用利差收窄（HYG/TLT 20日 {change:+.1f}%），風險偏好改善"
        else:
            return 0, f"— 信用利差穩定（HYG/TLT 20日 {change:+.1f}%）"
    except Exception:
        return 0, None


def _fear_greed_index(vix_val, sp500_df, yield_change=0):
    """
    [R4] 連續恐慌/貪婪指數 (0-100)
    0 = 極度恐慌, 50 = 中性, 100 = 極度貪婪
    """
    components = []

    # VIX 成分
    if vix_val is not None:
        if vix_val < 12:
            components.append(90)
        elif vix_val < 15:
            components.append(75)
        elif vix_val < 20:
            components.append(55)
        elif vix_val < 25:
            components.append(35)
        elif vix_val < 30:
            components.append(20)
        else:
            components.append(5)

    # S&P500 動能
    if sp500_df is not None and not sp500_df.empty and "Close" in sp500_df.columns:
        closes = sp500_df["Close"].astype(float)
        if len(closes) >= 20:
            current = float(closes.iloc[-1])
            ma20 = float(closes.tail(20).mean())
            ma50 = float(closes.tail(50).mean()) if len(closes) >= 50 else ma20
            pct_20d = (current / float(closes.iloc[-20]) - 1) * 100

            if current > ma20 and current > ma50 and pct_20d > 5:
                components.append(85)
            elif current > ma20 and current > ma50:
                components.append(70)
            elif current > ma20:
                components.append(55)
            elif current > ma50:
                components.append(40)
            elif pct_20d < -10:
                components.append(10)
            elif pct_20d < -5:
                components.append(25)
            else:
                components.append(35)

    # 殖利率變化
    if yield_change is not None:
        if yield_change < -0.3:
            components.append(70)
        elif yield_change > 0.5:
            components.append(25)
        else:
            components.append(50)

    return max(0, min(100, round(np.mean(components)))) if components else 50


def analyze():
    """總體經濟環境分析（R4 升級版）"""
    score = 5.0
    details = []
    details.append("— 總體經濟環境評估")

    # ===== VIX =====
    current_vix = None
    vix_df = fetch_vix()
    if not vix_df.empty and "Close" in vix_df.columns:
        current_vix = float(vix_df["Close"].iloc[-1])
        vix_ma20 = float(vix_df["Close"].tail(20).mean()) if len(vix_df) >= 20 else current_vix
        vix_trend = "上升" if current_vix > vix_ma20 * 1.1 else ("下降" if current_vix < vix_ma20 * 0.9 else "持平")

        if current_vix > 30:
            details.append(f"🚨 VIX = {current_vix:.1f}（恐慌區）")
            score -= 3
        elif current_vix > 25:
            details.append(f"⚠ VIX = {current_vix:.1f}（警戒區）")
            score -= 2
        elif current_vix > 20:
            details.append(f"⚠ VIX = {current_vix:.1f}（偏高，趨勢{vix_trend}）")
            score -= 1
        elif current_vix < 13:
            details.append(f"✓ VIX = {current_vix:.1f}（極低，小心自滿）")
            score += 0.5
        else:
            details.append(f"✓ VIX = {current_vix:.1f}（正常，趨勢{vix_trend}）")
            score += 1
    else:
        details.append("— VIX 資料暫時無法取得")

    # ===== 美10Y殖利率 =====
    yield_change = 0
    us10y_df = fetch_us10y()
    if not us10y_df.empty and "Close" in us10y_df.columns:
        current_yield = float(us10y_df["Close"].iloc[-1])
        if len(us10y_df) >= 20:
            yield_30d_ago = float(us10y_df["Close"].iloc[-20])
            yield_change = current_yield - yield_30d_ago

            if current_yield > 5.0:
                details.append(f"🚨 美10Y殖利率 {current_yield:.2f}%（極高，資金緊縮）")
                score -= 2
            elif current_yield > 4.5:
                details.append(f"⚠ 美10Y殖利率 {current_yield:.2f}%（偏高）")
                score -= 1
            elif current_yield < 3.5:
                details.append(f"✓ 美10Y殖利率 {current_yield:.2f}%（偏低，有利股市）")
                score += 1
            else:
                details.append(f"— 美10Y殖利率 {current_yield:.2f}%（中性）")

            if yield_change > 0.5:
                details.append(f"⚠ 殖利率近20日上升 {yield_change:+.2f}%")
                score -= 1
            elif yield_change < -0.3:
                details.append(f"✓ 殖利率近20日下降 {yield_change:+.2f}%")
                score += 0.5
    else:
        details.append("— 美債殖利率資料暫時無法取得")

    # ===== [R4] 殖利率曲線 =====
    us3m_df = fetch_us3m()
    yc_adj, yc_detail = _yield_curve_signal(us10y_df, us3m_df)
    if yc_detail:
        details.append(yc_detail)
        score += yc_adj

    # ===== [R4] 信用利差 =====
    hyg_df = fetch_hyg()
    tlt_df = fetch_tlt()
    cs_adj, cs_detail = _credit_spread_signal(hyg_df, tlt_df)
    if cs_detail:
        details.append(cs_detail)
        score += cs_adj

    # ===== S&P 500 =====
    sp500_df = fetch_sp500()
    if not sp500_df.empty and "Close" in sp500_df.columns:
        closes = sp500_df["Close"].astype(float)
        if len(closes) >= 50:
            current = closes.iloc[-1]
            ma20 = closes.tail(20).mean()
            ma50 = closes.tail(50).mean()

            if current > ma20 and current > ma50:
                details.append(f"✓ S&P500 多頭排列（站上 20/50MA）")
                score += 1
            elif current < ma20 and current < ma50:
                details.append(f"⚠ S&P500 偏空（跌破 20/50MA）")
                score -= 1.5
            else:
                details.append(f"— S&P500 震盪中")

            pct_20d = (current / closes.iloc[-20] - 1) * 100 if len(closes) >= 20 else 0
            if pct_20d < -10:
                details.append(f"🚨 S&P500 近20日跌 {pct_20d:.1f}%（系統性風險）")
                score -= 2
            elif pct_20d < -5:
                details.append(f"⚠ S&P500 近20日跌 {pct_20d:.1f}%")
                score -= 1
    else:
        details.append("— S&P500 資料暫時無法取得")

    # ===== 台幣匯率 =====
    twd_df = fetch_twd()
    if not twd_df.empty and "Close" in twd_df.columns:
        current_twd = float(twd_df["Close"].iloc[-1])
        if len(twd_df) >= 20:
            twd_20d_ago = float(twd_df["Close"].iloc[-20])
            twd_change_pct = (current_twd / twd_20d_ago - 1) * 100
            details.append(f"— 台幣匯率 {current_twd:.2f}（近20日 {twd_change_pct:+.1f}%）")
            if twd_change_pct > 3:
                details.append(f"⚠ 台幣急貶，外資可能撤出")
                score -= 1
            elif twd_change_pct < -2:
                details.append(f"✓ 台幣走升，有利外資回流")
                score += 0.5

    # ===== [R4] 恐慌/貪婪指數 =====
    fg_index = _fear_greed_index(current_vix, sp500_df, yield_change)
    if fg_index <= 20:
        fg_label = "極度恐慌"
    elif fg_index <= 35:
        fg_label = "恐慌"
    elif fg_index <= 55:
        fg_label = "中性"
    elif fg_index <= 75:
        fg_label = "貪婪"
    else:
        fg_label = "極度貪婪"
    details.append(f"\n恐慌/貪婪指數：{fg_index}/100（{fg_label}）")

    # ===== 結算 =====
    score = max(1.0, min(10.0, score))

    if score >= 7:
        signal = "green"
    elif score >= 4:
        signal = "yellow"
    else:
        signal = "red"

    if score >= 7:
        risk_multiplier = 1.0
    elif score >= 4:
        risk_multiplier = 0.9 + (score - 4) / 30
    else:
        risk_multiplier = 0.7 + (score - 1) / 15

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
        "fear_greed_index": fg_index,
        "fear_greed_label": fg_label,
    }
