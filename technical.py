"""
技術面分析模組
均線、RSI、MACD、KD隨機指標、布林通道
"""
import pandas as pd
import numpy as np


def _rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(prices, fast=12, slow=26, signal=9):
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _kd(high, low, close, k_period=9, d_period=3):
    low_min = low.rolling(window=k_period).min()
    high_max = high.rolling(window=k_period).max()
    rsv = (close - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(com=d_period - 1, min_periods=d_period).mean()
    d = k.ewm(com=d_period - 1, min_periods=d_period).mean()
    return k, d


def _bollinger(prices, period=20, std_mult=2):
    middle = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return upper, middle, lower


def analyze(price_df):
    """
    技術面分析
    回傳：{"signal": "green/yellow/red", "score": float, "details": list, ...}
    """
    result = {"signal": "yellow", "score": 5, "details": []}

    if price_df.empty or len(price_df) < 60:
        result["details"].append("⚠ 股價資料不足 60 日，無法完整分析")
        return result

    df = price_df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    high = df["max"].astype(float) if "max" in df.columns else close
    low = df["min"].astype(float) if "min" in df.columns else close
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
        details.append(f"⚠ RSI = {current_rsi:.0f}（嚴重超買）")
        score -= 2
    elif current_rsi > 70:
        details.append(f"⚠ RSI = {current_rsi:.0f}（接近超買）")
        score -= 1
    elif current_rsi < 20:
        details.append(f"✓ RSI = {current_rsi:.0f}（嚴重超賣，反彈機會）")
        score += 2
    elif current_rsi < 30:
        details.append(f"✓ RSI = {current_rsi:.0f}（接近超賣）")
        score += 1
    else:
        details.append(f"— RSI = {current_rsi:.0f}（正常範圍）")

    # ===== MACD =====
    macd_line, signal_line, histogram = _macd(close)
    if len(histogram.dropna()) >= 2:
        curr_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2]

        if curr_hist > 0 and prev_hist <= 0:
            details.append("✓ MACD 黃金交叉（多頭訊號）")
            score += 1
        elif curr_hist < 0 and prev_hist >= 0:
            details.append("⚠ MACD 死亡交叉（空頭訊號）")
            score -= 1
        elif curr_hist > 0:
            details.append("— MACD 柱狀在零軸上方（多方）")
        else:
            details.append("— MACD 柱狀在零軸下方（空方）")

    # ===== KD =====
    k, d = _kd(high, low, close)
    if len(k.dropna()) >= 2:
        curr_k, curr_d = k.iloc[-1], d.iloc[-1]

        if curr_k > 80 and curr_d > 80:
            details.append(f"⚠ KD 高檔（K={curr_k:.0f} D={curr_d:.0f}），留意過熱")
            score -= 0.5
        elif curr_k < 20 and curr_d < 20:
            details.append(f"✓ KD 低檔（K={curr_k:.0f} D={curr_d:.0f}），超賣區")
            score += 0.5
        elif curr_k > curr_d and k.iloc[-2] <= d.iloc[-2]:
            details.append(f"✓ KD 黃金交叉（K={curr_k:.0f} D={curr_d:.0f}）")
            score += 0.5
        elif curr_k < curr_d and k.iloc[-2] >= d.iloc[-2]:
            details.append(f"⚠ KD 死亡交叉（K={curr_k:.0f} D={curr_d:.0f}）")
            score -= 0.5

    # ===== 布林通道 =====
    bb_upper, bb_middle, bb_lower = _bollinger(close)
    if len(bb_upper.dropna()) > 0:
        bb_width = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1] * 100
        if current_price >= bb_upper.iloc[-1]:
            details.append(f"⚠ 股價觸及布林上軌（通道寬度 {bb_width:.1f}%）")
            score -= 0.5
        elif current_price <= bb_lower.iloc[-1]:
            details.append(f"✓ 股價觸及布林下軌（通道寬度 {bb_width:.1f}%）")
            score += 0.5

    # ===== 成交量 =====
    vol_5 = volume.tail(5).mean()
    vol_20 = volume.tail(20).mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1

    if vol_ratio > 1.5:
        if close.iloc[-1] > close.iloc[-5]:
            details.append(f"✓ 價漲量增（5日均量為20日的 {vol_ratio:.1f} 倍）")
            score += 1
        else:
            details.append(f"⚠ 價跌量增（5日均量為20日的 {vol_ratio:.1f} 倍）")
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

    # 停損參考
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
