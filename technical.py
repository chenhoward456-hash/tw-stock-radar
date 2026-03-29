"""
技術面分析模組
均線、RSI、MACD、KD隨機指標、布林通道
第三輪優化：多時間框架（週線確認）、RSI 背離偵測、動態指標權重
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
    rsv = (close - low_min) / (high_max - low_min).replace(0, np.nan) * 100
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


def _atr(high, low, close, period=14):
    """計算 ATR（平均真實波幅），用於動態停損"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr


def _adx(high, low, close, period=14):
    """
    [R6] 計算 ADX（Average Directional Index）趨勢強度指標

    ADX > 25: 趨勢明確，MA 交叉訊號可信
    ADX 20-25: 趨勢微弱
    ADX < 20: 盤整，MA 交叉不可靠

    回傳：(adx_value, plus_di, minus_di)
    """
    if len(high) < period + 5:
        return None, None, None

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0),
                        index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0),
                         index=high.index)

    # Smoothed averages (Wilder's smoothing)
    atr_smooth = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1/period, min_periods=period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1/period, min_periods=period).mean()

    # DI
    plus_di = (plus_dm_smooth / atr_smooth) * 100
    minus_di = (minus_dm_smooth / atr_smooth) * 100

    # DX and ADX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = (di_diff / di_sum.replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()

    adx_val = adx.iloc[-1] if not np.isnan(adx.iloc[-1]) else None
    pdi_val = plus_di.iloc[-1] if not np.isnan(plus_di.iloc[-1]) else None
    mdi_val = minus_di.iloc[-1] if not np.isnan(minus_di.iloc[-1]) else None

    return adx_val, pdi_val, mdi_val


def _resample_weekly(df):
    """將日線轉為週線（用於多時間框架分析）"""
    if df.empty or len(df) < 10:
        return pd.DataFrame()
    wdf = df.copy()
    wdf["date"] = pd.to_datetime(wdf["date"])
    wdf = wdf.set_index("date")

    agg = {
        "open": "first",
        "close": "last",
        "Trading_Volume": "sum",
    }
    if "max" in wdf.columns:
        agg["max"] = "max"
    if "min" in wdf.columns:
        agg["min"] = "min"

    weekly = wdf.resample("W").agg(agg).dropna(subset=["close"])
    weekly = weekly.reset_index()
    weekly["date"] = weekly["date"].dt.strftime("%Y-%m-%d")
    return weekly


def _weekly_trend(price_df):
    """
    週線趨勢判斷：MA5 vs MA10（週線），回傳方向和信心度
    [R6] 從 MA20 改為 MA10（週線 MA10 ≈ 日線 MA50，仍是有效的中期趨勢指標）
    這樣只需 12 週資料（≈84 天），不會因為預設抓 150 天而不夠用
    回傳：{"trend": "bullish/bearish/neutral", "strength": float, "detail": str}
    """
    wdf = _resample_weekly(price_df)
    if wdf.empty or len(wdf) < 12:
        return {"trend": "neutral", "strength": 0, "detail": "週線資料不足"}

    close = wdf["close"].astype(float)
    ma5w = close.rolling(5).mean()
    ma10w = close.rolling(10).mean()

    if pd.isna(ma5w.iloc[-1]) or pd.isna(ma10w.iloc[-1]):
        return {"trend": "neutral", "strength": 0, "detail": "週線均線資料不足"}

    curr_ma5 = ma5w.iloc[-1]
    curr_ma20 = ma10w.iloc[-1]  # 變數名保持 ma20 避免改太多下游
    curr_close = close.iloc[-1]

    # 週線 RSI
    rsi_w = _rsi(close, period=14)
    w_rsi = rsi_w.iloc[-1] if not np.isnan(rsi_w.iloc[-1]) else 50

    # 判斷趨勢
    if curr_ma5 > curr_ma20 and curr_close > curr_ma20:
        # 週線多頭
        spread = (curr_ma5 / curr_ma20 - 1) * 100
        strength = min(1.0, spread / 5)  # 5% spread = 最大信心
        trend = "bullish"
        detail = f"週線多頭（MA5w {curr_ma5:.1f} > MA20w {curr_ma20:.1f}，RSI {w_rsi:.0f}）"
    elif curr_ma5 < curr_ma20 and curr_close < curr_ma20:
        spread = (1 - curr_ma5 / curr_ma20) * 100
        strength = min(1.0, spread / 5)
        trend = "bearish"
        detail = f"週線空頭（MA5w {curr_ma5:.1f} < MA20w {curr_ma20:.1f}，RSI {w_rsi:.0f}）"
    else:
        trend = "neutral"
        strength = 0
        detail = f"週線中性（MA5w {curr_ma5:.1f} / MA20w {curr_ma20:.1f}，RSI {w_rsi:.0f}）"

    return {"trend": trend, "strength": round(strength, 2), "detail": detail, "rsi": w_rsi}


def _detect_rsi_divergence(close, rsi_series, lookback=30):
    """
    偵測 RSI 背離
    - 多頭背離：股價創新低但 RSI 沒有 → 底部反轉訊號
    - 空頭背離：股價創新高但 RSI 沒有 → 頂部反轉訊號
    """
    if len(close) < lookback + 5 or len(rsi_series) < lookback + 5:
        return None

    recent_close = close.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]

    # 清除 NaN
    valid = ~(recent_rsi.isna())
    if valid.sum() < lookback // 2:
        return None

    # 找局部極值（簡化：分前後半段比較）
    mid = lookback // 2
    first_half_close = recent_close.iloc[:mid]
    second_half_close = recent_close.iloc[mid:]
    first_half_rsi = recent_rsi.iloc[:mid]
    second_half_rsi = recent_rsi.iloc[mid:]

    # 空頭背離：股價創新高但 RSI 沒有
    if (second_half_close.max() > first_half_close.max() and
            second_half_rsi.max() < first_half_rsi.max() and
            second_half_rsi.max() > 60):
        return "bearish_divergence"

    # 多頭背離：股價創新低但 RSI 沒有
    if (second_half_close.min() < first_half_close.min() and
            second_half_rsi.min() > first_half_rsi.min() and
            second_half_rsi.min() < 40):
        return "bullish_divergence"

    return None


def analyze(price_df):
    """
    技術面分析
    回傳：{"signal": "green/yellow/red", "score": float, "details": list, ...}
    """
    result = {"signal": "yellow", "score": 5, "details": []}

    if price_df.empty or len(price_df) < 20:
        result["details"].append("⚠ 股價資料不足 20 日，無法分析")
        result["confidence"] = "none"
        return result

    if len(price_df) < 60:
        result["details"].append("⚠ 股價資料不足 60 日，僅做基礎分析（MACD/KD 可能不準）")
        result["confidence"] = "low"
        # 繼續分析但標記信心度低，下面各指標會自己處理 NaN

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

    # ===== [R6] ADX 趨勢強度（必須在 MA 評分之前，因為 adx_discount 會用到）=====
    adx_val, plus_di, minus_di = _adx(high, low, close)
    adx_discount = 1.0  # MA 訊號折扣因子

    if adx_val is not None:
        if adx_val >= 30:
            details.append(f"✓ ADX = {adx_val:.0f}（趨勢強勁，MA 訊號可信）")
        elif adx_val >= 25:
            details.append(f"— ADX = {adx_val:.0f}（趨勢存在）")
        elif adx_val >= 20:
            details.append(f"— ADX = {adx_val:.0f}（趨勢微弱，MA 訊號打折）")
            adx_discount = 0.6
        else:
            details.append(f"⚠ ADX = {adx_val:.0f}（盤整中，MA 交叉不可靠）")
            adx_discount = 0.3

        # DI 交叉方向
        if plus_di is not None and minus_di is not None:
            if plus_di > minus_di and adx_val >= 25:
                details.append(f"  +DI({plus_di:.0f}) > -DI({minus_di:.0f})，多方主導")
            elif minus_di > plus_di and adx_val >= 25:
                details.append(f"  -DI({minus_di:.0f}) > +DI({plus_di:.0f})，空方主導")

    above_ma5 = current_price > ma5.iloc[-1]
    above_ma20 = current_price > ma20.iloc[-1]
    above_ma60 = current_price > ma60.iloc[-1] if not np.isnan(ma60.iloc[-1]) else True  # assume neutral if no data

    # [R6] MA 訊號乘以 ADX 折扣（盤整時不信任 MA 排列）
    if above_ma5 and above_ma20 and above_ma60:
        _ma_pts = 2 * adx_discount
        details.append(f"✓ 股價站上所有均線（5/20/60日），多頭排列{' [ADX 打折]' if adx_discount < 1 else ''}")
        score += _ma_pts
    elif above_ma20 and above_ma60:
        score += 1 * adx_discount
        details.append("✓ 股價在 20 日和 60 日均線之上")
    elif not above_ma20 and not above_ma60:
        score -= 2 * adx_discount
        details.append(f"✗ 股價跌破 20 日和 60 日均線，偏空{' [ADX 打折]' if adx_discount < 1 else ''}")
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
        if bb_middle.iloc[-1] > 0:
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

    # ===== 趨勢方向（20MA vs 60MA）[R6: ADX 折扣] =====
    if len(ma20.dropna()) > 0 and len(ma60.dropna()) > 0:
        trend_diff = ma20.iloc[-1] - ma60.iloc[-1]
        if ma20.iloc[-1] > ma60.iloc[-1]:
            if len(ma20.dropna()) >= 10 and ma20.iloc[-10] <= ma60.iloc[-10]:
                details.append(f"✓ 中期趨勢剛轉多（20MA 突破 60MA），動能啟動{' [ADX 打折]' if adx_discount < 1 else ''}")
                score += 1.5 * adx_discount
            else:
                details.append("✓ 中期趨勢向上（20MA > 60MA）")
                score += 1 * adx_discount
        else:
            if len(ma20.dropna()) >= 10 and ma20.iloc[-10] >= ma60.iloc[-10]:
                details.append(f"⚠ 中期趨勢剛轉空（20MA 跌破 60MA），小心{' [ADX 打折]' if adx_discount < 1 else ''}")
                score -= 1.5 * adx_discount
            else:
                details.append("⚠ 中期趨勢向下（20MA < 60MA）")
                score -= 1 * adx_discount

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

    # ===== [R6] 52 週新高突破 + 量能確認 =====
    if len(close) >= 240:
        high_52w = close.tail(240).max()
        near_high = current_price >= high_52w * 0.97  # 距離 52 週高點 3% 以內

        if near_high:
            if vol_ratio > 1.5:
                details.append(f"🔥 52 週新高突破 + 量能放大（{vol_ratio:.1f}x），強勢突破訊號")
                score += 1.5
            else:
                details.append(f"— 接近 52 週新高但量能不足（{vol_ratio:.1f}x），突破可能虛假")
                score -= 0.5

    # ===== 多時間框架分析（第三輪新增）=====
    weekly = _weekly_trend(price_df)
    weekly_trend = weekly["trend"]
    weekly_detail = weekly["detail"]
    details.append(f"📊 {weekly_detail}")

    # 日線 vs 週線交叉驗證
    daily_bullish = above_ma20 and above_ma60
    daily_bearish = not above_ma20 and not above_ma60

    if daily_bullish and weekly_trend == "bullish":
        details.append("✓ 日線+週線同步多頭（高信心進場）")
        score += 1.5
    elif daily_bullish and weekly_trend == "bearish":
        details.append("⚠ 日線偏多但週線仍空，可能只是反彈")
        score -= 1
    elif daily_bearish and weekly_trend == "bullish":
        details.append("— 日線偏空但週線仍多，可能只是回檔")
        score += 0.5
    elif daily_bearish and weekly_trend == "bearish":
        details.append("⚠ 日線+週線同步空頭（避開）")
        score -= 1.5

    # ===== RSI 背離偵測（第三輪新增）=====
    divergence = _detect_rsi_divergence(close, rsi_series)
    if divergence == "bullish_divergence":
        details.append("✓ RSI 多頭背離（股價新低但 RSI 未新低，可能築底）")
        score += 1
    elif divergence == "bearish_divergence":
        details.append("⚠ RSI 空頭背離（股價新高但 RSI 未新高，動能衰竭）")
        score -= 1

    # ===== ATR 動態停損（適應不同波動度的股票）=====
    atr_series = _atr(high, low, close)
    current_atr = atr_series.iloc[-1] if not np.isnan(atr_series.iloc[-1]) else 0
    atr_pct = current_atr / current_price * 100 if current_price > 0 else 0

    # 停損建議：2 倍 ATR，同時參考 20MA
    atr_stop = current_price - 2 * current_atr if current_atr > 0 else 0
    ma20_val = ma20.iloc[-1]
    # 取兩者中較保守的（較高的價位）
    stop_loss = max(atr_stop, ma20_val) if atr_stop > 0 else ma20_val
    stop_loss_pct = (current_price - stop_loss) / current_price * 100 if current_price > 0 else 0

    details.append(f"📍 ATR(14) = {current_atr:.1f}（日均波幅 {atr_pct:.1f}%）")
    details.append(f"📍 停損參考：{stop_loss:.1f} 元（距現價 -{stop_loss_pct:.1f}%）")
    if atr_stop > 0 and atr_stop != ma20_val:
        details.append(f"  　ATR 停損 {atr_stop:.1f} / 20MA 停損 {ma20_val:.1f}（取較高者）")

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
    result["atr"] = current_atr
    result["stop_loss"] = stop_loss
    result["weekly_trend"] = weekly_trend
    result["divergence"] = divergence
    result["adx"] = adx_val
    result["ma5"] = ma5.iloc[-1] if len(ma5.dropna()) > 0 else None
    if "confidence" not in result:
        result["confidence"] = "high"

    return result
