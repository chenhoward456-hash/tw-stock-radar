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


def _detect_regime(close, lookback=60):
    """偵測動能 vs 均值回歸模式（用日報酬自相關 + Hurst 指數近似）"""
    returns = close.pct_change().dropna().tail(lookback)
    if len(returns) < 20:
        return "neutral", 0.0

    autocorr = returns.autocorr(lag=1)
    n = len(returns)
    mean_r = returns.mean()
    deviate = (returns - mean_r).cumsum()
    R = deviate.max() - deviate.min()
    S = returns.std()
    hurst = np.log(R / S) / np.log(n) if S > 0 and R > 0 else 0.5

    if hurst > 0.55 and autocorr > 0.05:
        return "momentum", round(min(1.0, (hurst - 0.5) * 4), 2)
    elif hurst < 0.45 and autocorr < -0.05:
        return "mean_reversion", round(min(1.0, (0.5 - hurst) * 4), 2)
    return "neutral", 0.0


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

    # ===== 市場狀態偵測 =====
    regime, regime_str = _detect_regime(close)
    regime_labels = {"momentum": "動能趨勢", "mean_reversion": "震盪回歸", "neutral": "中性"}
    details.append(f"— 市場狀態：{regime_labels[regime]}（強度 {regime_str}）")

    # ===== RSI（根據市場狀態調整解讀）=====
    rsi_series = _rsi(close)
    current_rsi = rsi_series.iloc[-1]

    if np.isnan(current_rsi):
        details.append("— RSI 資料不足")
    elif regime == "momentum":
        # 動能模式：超賣不是買點（還會繼續跌），超買是強勢
        if current_rsi > 80:
            details.append(f"— RSI = {current_rsi:.0f}（動能強勁，暫不視為超買）")
            score -= 0.5
        elif current_rsi > 70:
            details.append(f"— RSI = {current_rsi:.0f}（動能延續中）")
        elif current_rsi < 20:
            details.append(f"⚠ RSI = {current_rsi:.0f}（超賣但處於下跌動能，不急著撿）")
            score -= 1
        elif current_rsi < 30:
            details.append(f"⚠ RSI = {current_rsi:.0f}（超賣 + 下跌動能，小心接刀）")
            score -= 0.5
        else:
            details.append(f"— RSI = {current_rsi:.0f}（正常範圍）")
    else:
        # 震盪/中性模式：傳統 RSI 解讀
        if current_rsi > 80:
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

    # ===== 趨勢方向（20MA vs 60MA）=====
    if len(ma20.dropna()) > 0 and len(ma60.dropna()) > 0:
        trend_diff = ma20.iloc[-1] - ma60.iloc[-1]
        if ma20.iloc[-1] > ma60.iloc[-1]:
            if len(ma20.dropna()) >= 10 and ma20.iloc[-10] <= ma60.iloc[-10]:
                details.append("✓ 中期趨勢剛轉多（20MA 突破 60MA），動能啟動")
                score += 1.5
            else:
                details.append("✓ 中期趨勢向上（20MA > 60MA）")
                score += 1
        else:
            if len(ma20.dropna()) >= 10 and ma20.iloc[-10] >= ma60.iloc[-10]:
                details.append("⚠ 中期趨勢剛轉空（20MA 跌破 60MA），小心")
                score -= 1.5
            else:
                details.append("⚠ 中期趨勢向下（20MA < 60MA）")
                score -= 1

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
