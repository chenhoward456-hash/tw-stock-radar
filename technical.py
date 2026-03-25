"""
技術面分析模組
分析均線、RSI、成交量、近期漲跌幅
"""
import pandas as pd
import numpy as np


def _rsi(prices, period=14):
    """計算 RSI"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze(price_df):
    """
    技術面分析
    回傳：{"signal": "green/yellow/red", "score": float, "details": list}
    """
    result = {"signal": "yellow", "score": 5, "details": []}

    if price_df.empty or len(price_df) < 60:
        result["details"].append("⚠ 股價資料不足 60 日，無法完整分析")
        return result

    df = price_df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    volume = df["Trading_Volume"].astype(float)
    current_price = close.iloc[-1]

    score = 5.0
    details = []

    # ===== 均線 =====
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    above_ma5 = current_price > ma5.iloc[-1]
    above_ma20 = current_price > ma20.iloc[-1]
    above_ma60 = current_price > ma60.iloc[-1]

    if above_ma5 and above_ma20 and above_ma60:
        details.append("✓ 股價站上所有均線（5/20/60日），多頭排列")
        score += 2
    elif above_ma20 and above_ma60:
        details.append("✓ 股價在 20 日和 60 日均線之上")
        score += 1
    elif not above_ma20 and not above_ma60:
        details.append("✗ 股價跌破 20 日和 60 日均線，偏空")
        score -= 2
    else:
        details.append("— 股價在均線附近震盪")

    # 20 日均線方向
    if len(ma20.dropna()) >= 5:
        ma20_slope = (ma20.iloc[-1] - ma20.iloc[-5]) / ma20.iloc[-5] * 100
        if ma20_slope > 0.5:
            details.append(f"✓ 20日均線上升中（{ma20_slope:+.1f}%）")
            score += 1
        elif ma20_slope < -0.5:
            details.append(f"✗ 20日均線下降中（{ma20_slope:+.1f}%）")
            score -= 1

    # ===== RSI =====
    rsi_series = _rsi(close)
    current_rsi = rsi_series.iloc[-1]

    if np.isnan(current_rsi):
        details.append("— RSI 資料不足")
    elif current_rsi > 80:
        details.append(f"⚠ RSI = {current_rsi:.0f}（嚴重超買，短線拉回風險高）")
        score -= 2
    elif current_rsi > 70:
        details.append(f"⚠ RSI = {current_rsi:.0f}（偏高，接近超買）")
        score -= 1
    elif current_rsi < 20:
        details.append(f"✓ RSI = {current_rsi:.0f}（嚴重超賣，反彈機會）")
        score += 2
    elif current_rsi < 30:
        details.append(f"✓ RSI = {current_rsi:.0f}（偏低，接近超賣）")
        score += 1
    else:
        details.append(f"— RSI = {current_rsi:.0f}（正常範圍）")

    # ===== 成交量 =====
    vol_5 = volume.tail(5).mean()
    vol_20 = volume.tail(20).mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1

    if vol_ratio > 1.5:
        if close.iloc[-1] > close.iloc[-5]:
            details.append(f"✓ 價漲量增（5日均量為20日的 {vol_ratio:.1f} 倍），買盤積極")
            score += 1
        else:
            details.append(f"⚠ 價跌量增（5日均量為20日的 {vol_ratio:.1f} 倍），賣壓沉重")
            score -= 1
    elif vol_ratio < 0.6:
        details.append(f"⚠ 近5日量能萎縮（僅20日均量的 {vol_ratio:.1f} 倍）")
    else:
        details.append(f"— 成交量正常（5日/20日均量比 {vol_ratio:.1f}）")

    # ===== 近期漲跌幅 =====
    pct_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 5 else 0
    pct_20d = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 20 else 0

    details.append(f"— 近 5 日漲跌：{pct_5d:+.1f}%")
    details.append(f"— 近 20 日漲跌：{pct_20d:+.1f}%")

    if pct_5d > 10:
        details.append("⚠ 短線漲幅過大，追高風險較高")
        score -= 1
    if pct_20d > 20:
        details.append("⚠ 中線漲幅已大，注意回檔風險")
        score -= 1
    if pct_20d < -20:
        details.append("⚠ 中線跌幅已大，留意是否為趨勢破壞")

    # ===== 停損參考 =====
    details.append(f"📍 停損參考：20日均線 {ma20.iloc[-1]:.1f} 元")

    # ===== 結算 =====
    score = max(1.0, min(10.0, score))
    if score >= 7:
        signal = "green"
    elif score >= 4:
        signal = "yellow"
    else:
        signal = "red"

    result["signal"] = signal
    result["score"] = round(score, 1)
    result["details"] = details
    result["current_price"] = current_price
    result["ma20"] = ma20.iloc[-1]
    result["ma60"] = ma60.iloc[-1]
    result["rsi"] = current_rsi

    return result
