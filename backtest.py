#!/usr/bin/env python3
"""
簡易回測 — 用歷史資料驗證訊號有沒有用
用法：python3 backtest.py 2330
      python3 backtest.py 2330 365    (回測天數，預設 500)

第四輪新增：Walk-forward 驗證 + Monte Carlo 信賴區間
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import market


# ===== 回測參數 =====
SLIPPAGE_PCT = 0.1   # 滑價假設 0.1%（每筆買賣都會比預期差一點）
MIN_DAILY_VOLUME = 500  # 最低日均成交量（張），低於此標記流動性風險


def _calc_rsi(close, period=14):
    """計算 RSI"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _calc_atr(high, low, close, period=14):
    """計算 ATR（平均真實波幅）"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def _check_liquidity(df):
    """檢查流動性，回傳警告訊息"""
    if "Trading_Volume" not in df.columns:
        return None
    vol = df["Trading_Volume"].astype(float)
    avg_vol_lots = vol.tail(20).mean() / 1000  # 轉換成「張」
    if avg_vol_lots < MIN_DAILY_VOLUME:
        return f"⚠ 流動性風險：近20日均成交量僅 {avg_vol_lots:.0f} 張（建議 > {MIN_DAILY_VOLUME} 張）"
    return None


def _calc_risk_metrics(trades, trading_days=252):
    """
    計算風險調整後績效指標（第三輪新增）
    Sharpe Ratio、Sortino Ratio、最大回撤、最大回撤天數
    """
    if not trades:
        return {}

    returns = [t["return_pct"] / 100 for t in trades]
    avg_ret = np.mean(returns)
    std_ret = np.std(returns) if len(returns) > 1 else 0

    # 年化（用每筆交易平均持有天數估算）
    total_days = 0
    for t in trades:
        try:
            from datetime import datetime
            buy_dt = datetime.strptime(str(t["buy_date"])[:10], "%Y-%m-%d")
            sell_dt = datetime.strptime(str(t["sell_date"])[:10], "%Y-%m-%d")
            total_days += (sell_dt - buy_dt).days
        except Exception:
            total_days += 20  # 預設 20 天
    avg_hold_days = total_days / len(trades) if trades else 20
    trades_per_year = trading_days / max(avg_hold_days, 1)

    # Sharpe Ratio（假設無風險利率 2%）
    risk_free = 0.02 / trades_per_year  # 每筆交易期間的無風險報酬
    sharpe = (avg_ret - risk_free) / std_ret * np.sqrt(trades_per_year) if std_ret > 0 else 0

    # Sortino Ratio（只看下行波動）
    downside = [r for r in returns if r < 0]
    downside_std = np.std(downside) if len(downside) > 1 else std_ret
    sortino = (avg_ret - risk_free) / downside_std * np.sqrt(trades_per_year) if downside_std > 0 else 0

    # 最大回撤（模擬權益曲線）
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    peak = equity[0]
    max_dd = 0
    max_dd_start = 0
    max_dd_end = 0
    dd_start = 0
    for i, e in enumerate(equity):
        if e > peak:
            peak = e
            dd_start = i
        dd = (e / peak - 1) * 100
        if dd < max_dd:
            max_dd = dd
            max_dd_start = dd_start
            max_dd_end = i

    # 最大回撤天數（用交易筆數估算）
    max_dd_trades = max_dd_end - max_dd_start

    return {
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown": round(max_dd, 1),
        "max_dd_trades": max_dd_trades,
        "avg_hold_days": round(avg_hold_days, 0),
        "trades_per_year": round(trades_per_year, 1),
    }


# =============================================================
# [R4] Walk-Forward Validation
# =============================================================
def walk_forward(df, signal_func, trade_func, is_us=False,
                 train_ratio=0.6, step_ratio=0.2, min_train=120):
    """
    滾動窗口 walk-forward 回測

    做法：
    1. 把資料切成 train(60%) + test(20%) + future(20%)
    2. 在 train 上產生訊號，只看 test 段的交易結果
    3. 窗口向前滑動，重複
    4. 彙總所有 out-of-sample 交易

    回傳：{
        "oos_trades": list,   # 所有樣本外交易
        "is_trades": list,    # 所有樣本內交易（對照用）
        "windows": list,      # 每個窗口的 is/oos 績效
        "overfitting_ratio": float  # IS Sharpe / OOS Sharpe
    }
    """
    n = len(df)
    train_size = max(min_train, int(n * train_ratio))
    step_size = max(30, int(n * step_ratio))

    all_oos_trades = []
    all_is_trades = []
    windows = []

    start = 0
    while start + train_size + step_size <= n:
        train_end = start + train_size
        test_end = min(train_end + step_size, n)

        train_df = df.iloc[start:train_end].reset_index(drop=True)
        full_df = df.iloc[start:test_end].reset_index(drop=True)

        # 在完整區間（train+test）上跑訊號
        signals_full, _ = signal_func(full_df)
        trades_full = trade_func(signals_full, is_us=is_us)

        # 分類：train 期間的交易 vs test 期間的交易
        train_end_date = str(df.iloc[train_end - 1]["date"])[:10] if train_end < n else "9999-12-31"

        is_trades = []
        oos_trades = []
        for t in trades_full:
            buy_date = str(t["buy_date"])[:10]
            if buy_date <= train_end_date:
                is_trades.append(t)
            else:
                oos_trades.append(t)

        # 也跑純 train 的結果
        signals_train, _ = signal_func(train_df)
        trades_train = trade_func(signals_train, is_us=is_us)

        is_risk = _calc_risk_metrics(trades_train)
        oos_risk = _calc_risk_metrics(oos_trades)

        windows.append({
            "train_start": str(df.iloc[start]["date"])[:10],
            "train_end": train_end_date,
            "test_end": str(df.iloc[test_end - 1]["date"])[:10],
            "is_trades": len(trades_train),
            "oos_trades": len(oos_trades),
            "is_sharpe": is_risk.get("sharpe", 0),
            "oos_sharpe": oos_risk.get("sharpe", 0),
            "is_return": sum(t["return_pct"] for t in trades_train) if trades_train else 0,
            "oos_return": sum(t["return_pct"] for t in oos_trades) if oos_trades else 0,
        })

        all_is_trades.extend(trades_train)
        all_oos_trades.extend(oos_trades)

        start += step_size

    # 計算 overfitting ratio
    is_risk_total = _calc_risk_metrics(all_is_trades)
    oos_risk_total = _calc_risk_metrics(all_oos_trades)
    is_sharpe = is_risk_total.get("sharpe", 0)
    oos_sharpe = oos_risk_total.get("sharpe", 0)

    if oos_sharpe != 0:
        overfitting_ratio = round(is_sharpe / oos_sharpe, 2) if oos_sharpe > 0 else 99.0
    else:
        overfitting_ratio = 99.0 if is_sharpe > 0 else 1.0

    return {
        "oos_trades": all_oos_trades,
        "is_trades": all_is_trades,
        "windows": windows,
        "overfitting_ratio": overfitting_ratio,
        "is_risk": is_risk_total,
        "oos_risk": oos_risk_total,
    }


# =============================================================
# [R4] Monte Carlo Simulation
# =============================================================
def monte_carlo(trades, n_simulations=1000, n_trades=None):
    """
    Bootstrap Monte Carlo：隨機重排交易順序，模擬不同運氣下的結果
    回傳信賴區間：5th / 25th / 50th / 75th / 95th percentile

    用途：知道策略「最壞情況」和「最好情況」的範圍
    """
    if not trades or len(trades) < 3:
        return None

    returns = [t["return_pct"] / 100 for t in trades]
    n = n_trades or len(returns)

    final_equities = []
    max_drawdowns = []

    for _ in range(n_simulations):
        # 隨機抽樣（放回）
        sampled = np.random.choice(returns, size=n, replace=True)

        # 模擬權益曲線
        equity = 1.0
        peak = 1.0
        max_dd = 0
        for r in sampled:
            equity *= (1 + r)
            if equity > peak:
                peak = equity
            dd = (equity / peak - 1) * 100
            if dd < max_dd:
                max_dd = dd

        final_equities.append((equity - 1) * 100)  # 百分比報酬
        max_drawdowns.append(max_dd)

    pcts = [5, 25, 50, 75, 95]
    return {
        "return_percentiles": {
            p: round(float(np.percentile(final_equities, p)), 1) for p in pcts
        },
        "drawdown_percentiles": {
            p: round(float(np.percentile(max_drawdowns, p)), 1) for p in pcts
        },
        "n_simulations": n_simulations,
        "n_trades": n,
    }


def generate_signals(df, stop_loss_pct=-8.0):
    """
    產生買賣訊號（均線交叉 + RSI 過濾 + 量能確認 + ATR 動態停損）
    """
    close = df["close"].astype(float)
    high = df["max"].astype(float) if "max" in df.columns else close
    low = df["min"].astype(float) if "min" in df.columns else close
    volume = df["Trading_Volume"].astype(float)
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    rsi = _calc_rsi(close)
    vol_ma20 = volume.rolling(20).mean()
    atr = _calc_atr(high, low, close)

    signals = []
    position = False
    buy_price = 0
    stop_price = 0

    for i in range(21, len(df)):
        prev_diff = ma5.iloc[i - 1] - ma20.iloc[i - 1]
        curr_diff = ma5.iloc[i] - ma20.iloc[i]
        curr_rsi = rsi.iloc[i] if not np.isnan(rsi.iloc[i]) else 50
        curr_atr = atr.iloc[i] if not np.isnan(atr.iloc[i]) else 0

        # === 停損檢查（改用 ATR 動態停損）===
        if position and buy_price > 0:
            if stop_price > 0 and close.iloc[i] <= stop_price:
                drawdown = (close.iloc[i] / buy_price - 1) * 100
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"ATR停損（{drawdown:.1f}%，停損價 {stop_price:.1f}）",
                })
                position = False
                buy_price = 0
                stop_price = 0
                continue

        # === 買進：黃金交叉 + RSI 未超買 + 量能放大 ===
        if not position and prev_diff <= 0 and curr_diff > 0:
            vol_ok = volume.iloc[i] > vol_ma20.iloc[i] if not np.isnan(vol_ma20.iloc[i]) else True
            if curr_rsi < 70 and vol_ok:
                signals.append({
                    "type": "BUY",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"黃金交叉（RSI {curr_rsi:.0f}）",
                })
                position = True
                buy_price = close.iloc[i]
                # ATR 停損：買入價 - 2倍ATR，最少也要 -8%
                if curr_atr > 0:
                    atr_stop = buy_price - 2 * curr_atr
                    fixed_stop = buy_price * (1 + stop_loss_pct / 100)
                    stop_price = max(atr_stop, fixed_stop)
                else:
                    stop_price = buy_price * (1 + stop_loss_pct / 100)

        # === 賣出：死亡交叉（RSI 未超賣才賣，避免恐慌殺低）===
        elif position and prev_diff >= 0 and curr_diff < 0:
            if curr_rsi > 30:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"死亡交叉（RSI {curr_rsi:.0f}）",
                })
                position = False
                buy_price = 0
                stop_price = 0

    return signals, position


def generate_signals_trend(df, trailing_stop_pct=-10.0):
    """趨勢跟蹤策略"""
    close = df["close"].astype(float)
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    signals = []
    position = False
    buy_price = 0
    peak_price = 0

    for i in range(61, len(df)):
        prev_diff = ma20.iloc[i - 1] - ma60.iloc[i - 1]
        curr_diff = ma20.iloc[i] - ma60.iloc[i]

        if position:
            if close.iloc[i] > peak_price:
                peak_price = close.iloc[i]

            drawdown_from_peak = (close.iloc[i] / peak_price - 1) * 100
            if drawdown_from_peak <= trailing_stop_pct:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"移動停利（從高點 {peak_price:.1f} 回落 {drawdown_from_peak:.1f}%）",
                })
                position = False
                buy_price = 0
                peak_price = 0
                continue

            if prev_diff >= 0 and curr_diff < 0:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"趨勢反轉（20MA 跌破 60MA）",
                })
                position = False
                buy_price = 0
                peak_price = 0
                continue

        if not position and prev_diff <= 0 and curr_diff > 0:
            signals.append({
                "type": "BUY",
                "date": df.iloc[i]["date"],
                "price": close.iloc[i],
                "index": i,
                "reason": "趨勢確認（20MA 突破 60MA）",
            })
            position = True
            buy_price = close.iloc[i]
            peak_price = close.iloc[i]

    return signals, position


def generate_signals_value(df, trailing_stop_pct=-12.0):
    """長線佈局策略"""
    close = df["close"].astype(float)
    ma20 = close.rolling(20).mean()

    signals = []
    position = False
    buy_price = 0
    peak_price = 0

    for i in range(120, len(df)):
        lookback = min(i, 240)
        window = close.iloc[i - lookback:i + 1]
        high_52 = window.max()
        low_52 = window.min()

        if high_52 <= low_52:
            continue

        position_pct = (close.iloc[i] - low_52) / (high_52 - low_52) * 100

        ma20_rising = ma20.iloc[i] > ma20.iloc[i - 5] if i >= 5 else False

        if position:
            if close.iloc[i] > peak_price:
                peak_price = close.iloc[i]

            drawdown = (close.iloc[i] / peak_price - 1) * 100
            if drawdown <= trailing_stop_pct:
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"移動停利（從高點回落 {drawdown:.1f}%）",
                })
                position = False
                buy_price = 0
                peak_price = 0
                continue

            if position_pct > 85:
                gain = (close.iloc[i] / buy_price - 1) * 100
                signals.append({
                    "type": "SELL",
                    "date": df.iloc[i]["date"],
                    "price": close.iloc[i],
                    "index": i,
                    "reason": f"到達 52 週高點區（位置 {position_pct:.0f}%，獲利 {gain:+.1f}%）",
                })
                position = False
                buy_price = 0
                peak_price = 0
                continue

        if not position and position_pct < 25 and ma20_rising:
            signals.append({
                "type": "BUY",
                "date": df.iloc[i]["date"],
                "price": close.iloc[i],
                "index": i,
                "reason": f"逢低佈局（52 週位置 {position_pct:.0f}%，均線回升）",
            })
            position = True
            buy_price = close.iloc[i]
            peak_price = close.iloc[i]

    return signals, position


def generate_signals_composite(df, stop_loss_pct=-8.0):
    """
    [R6] 複合評分策略 — 模擬 R6 的多因子評分邏輯

    進場條件（全部滿足）：
    1. MA5 > MA20 > MA60（多頭排列）
    2. ADX > 20（趨勢存在，避免盤整假訊號）
    3. RSI 40-70（不超買、不超賣）
    4. 量能放大（5日均量 > 20日均量）
    5. 非短線過熱（偏離 MA20 < 5%）

    出場條件（任一觸發）：
    1. ATR 動態停損（2x ATR）
    2. MA20 跌破 MA60（趨勢反轉）
    3. RSI > 80（嚴重超買）
    4. ADX < 15 且已獲利 > 5%（趨勢消失，先走）

    核心思路：比單一策略多了 ADX 過濾 + 過熱保護 + 趨勢消失偵測，
    犧牲一些交易頻率來換更高的勝率和盈虧比。
    """
    close = df["close"].astype(float)
    high = df["max"].astype(float) if "max" in df.columns else close
    low = df["min"].astype(float) if "min" in df.columns else close
    volume = df["Trading_Volume"].astype(float)

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    rsi = _calc_rsi(close)
    atr = _calc_atr(high, low, close)
    vol_ma5 = volume.rolling(5).mean()
    vol_ma20 = volume.rolling(20).mean()

    # ADX calculation (inline, simplified)
    tr = pd.concat([high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0),
                        index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0),
                         index=high.index)
    atr_s = tr.ewm(alpha=1/14, min_periods=14).mean()
    plus_di = (plus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr_s) * 100
    minus_di = (minus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr_s) * 100
    di_sum = plus_di + minus_di
    dx = ((plus_di - minus_di).abs() / di_sum.replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1/14, min_periods=14).mean()

    signals = []
    position = False
    buy_price = 0
    stop_price = 0

    for i in range(61, len(df)):
        curr_close = close.iloc[i]
        curr_ma5 = ma5.iloc[i]
        curr_ma20 = ma20.iloc[i]
        curr_ma60 = ma60.iloc[i]
        curr_rsi = rsi.iloc[i] if not np.isnan(rsi.iloc[i]) else 50
        curr_atr = atr.iloc[i] if not np.isnan(atr.iloc[i]) else 0
        curr_adx = adx.iloc[i] if not np.isnan(adx.iloc[i]) else 0
        curr_vol5 = vol_ma5.iloc[i] if not np.isnan(vol_ma5.iloc[i]) else 0
        curr_vol20 = vol_ma20.iloc[i] if not np.isnan(vol_ma20.iloc[i]) else 1

        if any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in [curr_ma5, curr_ma20, curr_ma60]):
            continue

        # === 持倉中的出場檢查 ===
        if position and buy_price > 0:
            # ATR 停損
            if stop_price > 0 and curr_close <= stop_price:
                dd = (curr_close / buy_price - 1) * 100
                signals.append({
                    "type": "SELL", "date": df.iloc[i]["date"],
                    "price": curr_close, "index": i,
                    "reason": f"ATR停損（{dd:.1f}%）",
                })
                position = False
                buy_price = 0
                stop_price = 0
                continue

            # 趨勢反轉
            if curr_ma20 < curr_ma60:
                dd = (curr_close / buy_price - 1) * 100
                signals.append({
                    "type": "SELL", "date": df.iloc[i]["date"],
                    "price": curr_close, "index": i,
                    "reason": f"趨勢反轉 MA20<MA60（{dd:+.1f}%）",
                })
                position = False
                buy_price = 0
                stop_price = 0
                continue

            # RSI 嚴重超買
            if curr_rsi > 80:
                gain = (curr_close / buy_price - 1) * 100
                signals.append({
                    "type": "SELL", "date": df.iloc[i]["date"],
                    "price": curr_close, "index": i,
                    "reason": f"RSI超買 {curr_rsi:.0f}（{gain:+.1f}%）",
                })
                position = False
                buy_price = 0
                stop_price = 0
                continue

            # ADX 趨勢消失 + 已有獲利
            gain_pct = (curr_close / buy_price - 1) * 100
            if curr_adx < 15 and gain_pct > 5:
                signals.append({
                    "type": "SELL", "date": df.iloc[i]["date"],
                    "price": curr_close, "index": i,
                    "reason": f"趨勢消失 ADX={curr_adx:.0f}，先保獲利（{gain_pct:+.1f}%）",
                })
                position = False
                buy_price = 0
                stop_price = 0
                continue

            # 移動停損上調
            if curr_atr > 0:
                new_stop = curr_close - 2 * curr_atr
                if new_stop > stop_price:
                    stop_price = new_stop

        # === 進場條件 ===
        if not position:
            # 1. 多頭排列
            bullish_ma = curr_ma5 > curr_ma20 > curr_ma60
            # 2. ADX 確認趨勢
            trend_exists = curr_adx > 20
            # 3. RSI 健康範圍
            rsi_ok = 40 <= curr_rsi <= 70
            # 4. 量能支撐
            vol_ok = curr_vol5 > curr_vol20 if curr_vol20 > 0 else True
            # 5. 非過熱（偏離 MA20 < 5%）
            deviation = (curr_close / curr_ma20 - 1) * 100 if curr_ma20 > 0 else 0
            not_overheated = deviation < 5

            if bullish_ma and trend_exists and rsi_ok and vol_ok and not_overheated:
                signals.append({
                    "type": "BUY", "date": df.iloc[i]["date"],
                    "price": curr_close, "index": i,
                    "reason": f"複合進場（ADX={curr_adx:.0f} RSI={curr_rsi:.0f}）",
                })
                position = True
                buy_price = curr_close
                if curr_atr > 0:
                    atr_stop = buy_price - 2 * curr_atr
                    fixed_stop = buy_price * (1 + stop_loss_pct / 100)
                    stop_price = max(atr_stop, fixed_stop)
                else:
                    stop_price = buy_price * (1 + stop_loss_pct / 100)

    return signals, position


def calculate_trades(signals, is_us=False):
    """從訊號列表計算每筆交易的損益（含交易成本 + 滑價）"""
    slippage = SLIPPAGE_PCT / 100

    if is_us:
        BUY_FEE = 0.0
        SELL_FEE = 0.0
        TAX = 0.0
    else:
        BUY_FEE = 0.001425
        SELL_FEE = 0.001425
        TAX = 0.003

    trades = []
    i = 0
    while i < len(signals) - 1:
        if signals[i]["type"] == "BUY" and signals[i + 1]["type"] == "SELL":
            buy_price = signals[i]["price"]
            sell_price = signals[i + 1]["price"]

            actual_buy = buy_price * (1 + BUY_FEE + slippage)
            actual_sell = sell_price * (1 - SELL_FEE - TAX - slippage)
            ret = (actual_sell / actual_buy - 1) * 100

            trades.append({
                "buy_date": signals[i]["date"],
                "buy_price": buy_price,
                "sell_date": signals[i + 1]["date"],
                "sell_price": sell_price,
                "return_pct": ret,
                "buy_reason": signals[i].get("reason", ""),
                "sell_reason": signals[i + 1].get("reason", ""),
            })
            i += 2
        else:
            i += 1

    return trades


def print_report(stock_id, stock_name, df, trades, still_holding, is_us=False,
                 strategy_name="均線交叉 + RSI 過濾 + 量能確認 + 停損 -8%",
                 wf_result=None, mc_result=None):
    """印出回測報告（R4：含 walk-forward 和 Monte Carlo）"""
    close = df["close"].astype(float)
    start_price = close.iloc[20]
    end_price = close.iloc[-1]
    buy_hold_return = (end_price / start_price - 1) * 100
    period_start = df.iloc[20]["date"]
    period_end = df.iloc[-1]["date"]

    w = 55
    print()
    print("=" * w)
    print(f" {stock_id} {stock_name} — 歷史回測報告 ".center(w))
    print("=" * w)

    print(f"\n 策略：{strategy_name}")
    print(f" 期間：{period_start} ~ {period_end}")
    print(f" 資料筆數：{len(df)} 日")

    # 交易紀錄
    print(f"\n 交易紀錄：")
    print(" " + "─" * (w - 2))

    if not trades:
        print("  沒有產生任何交易訊號。")
    else:
        for i, t in enumerate(trades, 1):
            ret = t["return_pct"]
            icon = "✓" if ret > 0 else "✗"
            sell_reason = t.get("sell_reason", "")
            reason_tag = f" [{sell_reason}]" if sell_reason else ""
            print(
                f"  #{i:>2} {icon} 買 {t['buy_date']} @ {t['buy_price']:.1f}"
                f"  → 賣 {t['sell_date']} @ {t['sell_price']:.1f}"
                f"  {ret:+.1f}%{reason_tag}"
            )

        if still_holding:
            print(f"\n  ⚠ 目前仍持有中（最新價 {end_price:.1f}）")

    # 統計
    if trades:
        returns = [t["return_pct"] for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        total_return = 1
        for r in returns:
            total_return *= (1 + r / 100)
        total_return = (total_return - 1) * 100

        print(f"\n 績效統計：")
        print(" " + "─" * (w - 2))
        print(f"  交易次數：{len(trades)}")
        print(f"  勝率：{len(wins)}/{len(trades)}（{len(wins)/len(trades)*100:.0f}%）")

        if wins:
            print(f"  平均獲利：{np.mean(wins):+.1f}%")
        if losses:
            print(f"  平均虧損：{np.mean(losses):+.1f}%")

        print(f"  最大單次獲利：{max(returns):+.1f}%")
        print(f"  最大單次虧損：{min(returns):+.1f}%")

        print(f"\n  📊 策略累計報酬：{total_return:+.1f}%")
        print(f"  📊 同期買進持有：{buy_hold_return:+.1f}%")

        diff = total_return - buy_hold_return
        if diff > 5:
            print(f"  → 策略勝過買進持有 {diff:+.1f}%")
        elif diff < -5:
            print(f"  → 策略落後買進持有 {diff:.1f}%")
        else:
            print(f"  → 策略與買進持有相近（差距 {diff:+.1f}%）")

        # 最大連續虧損
        max_consecutive_loss = 0
        current_streak = 0
        for r in returns:
            if r <= 0:
                current_streak += 1
                max_consecutive_loss = max(max_consecutive_loss, current_streak)
            else:
                current_streak = 0
        if max_consecutive_loss >= 3:
            print(f"  ⚠ 最大連續虧損：{max_consecutive_loss} 筆（心理壓力測試）")

        # 盈虧比
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        profit_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        print(f"  盈虧比：{profit_ratio:.2f}（> 1.5 較理想）")

        # 風險調整指標
        risk = _calc_risk_metrics(trades)
        if risk:
            print(f"\n 風險調整指標：")
            print(" " + "─" * (w - 2))
            print(f"  Sharpe Ratio：{risk['sharpe']}（> 1.0 良好，> 2.0 優秀）")
            print(f"  Sortino Ratio：{risk['sortino']}（> 1.5 良好）")
            print(f"  最大回撤：{risk['max_drawdown']}%")
            if risk['max_dd_trades'] > 0:
                print(f"  最大回撤跨度：{risk['max_dd_trades']} 筆交易")
            print(f"  平均持有天數：{risk['avg_hold_days']:.0f} 天")
            print(f"  年化交易頻率：約 {risk['trades_per_year']:.0f} 筆/年")

    # [R4] Walk-Forward 結果
    if wf_result and wf_result.get("oos_trades"):
        print(f"\n 📋 Walk-Forward 驗證（樣本外）：")
        print(" " + "─" * (w - 2))
        oos = wf_result
        oos_risk = oos.get("oos_risk", {})
        is_risk = oos.get("is_risk", {})
        print(f"  樣本內交易：{len(oos['is_trades'])} 筆，Sharpe {is_risk.get('sharpe', 'N/A')}")
        print(f"  樣本外交易：{len(oos['oos_trades'])} 筆，Sharpe {oos_risk.get('sharpe', 'N/A')}")
        print(f"  過擬合比率：{oos['overfitting_ratio']}（IS/OOS Sharpe，越接近 1.0 越好）")

        if oos["overfitting_ratio"] > 3:
            print(f"  🚨 嚴重過擬合！樣本內績效遠好於樣本外")
        elif oos["overfitting_ratio"] > 1.5:
            print(f"  ⚠ 輕微過擬合，策略穩定性需觀察")
        elif oos["overfitting_ratio"] <= 1.2 and oos_risk.get("sharpe", 0) > 0:
            print(f"  ✓ 策略在樣本外表現穩定，可信度高")

        # 每個窗口概況
        if oos.get("windows"):
            print(f"\n  窗口明細：")
            for i, win in enumerate(oos["windows"], 1):
                print(
                    f"    #{i} train→{win['train_end']} | "
                    f"IS: {win['is_trades']}筆 Sharpe={win['is_sharpe']} | "
                    f"OOS: {win['oos_trades']}筆 Sharpe={win['oos_sharpe']}"
                )

    # [R4] Monte Carlo 結果
    if mc_result:
        print(f"\n 🎲 Monte Carlo 模擬（{mc_result['n_simulations']} 次）：")
        print(" " + "─" * (w - 2))
        rp = mc_result["return_percentiles"]
        dp = mc_result["drawdown_percentiles"]
        print(f"  累計報酬信賴區間：")
        print(f"    最差 5%：{rp[5]:+.1f}%")
        print(f"    25 分位：{rp[25]:+.1f}%")
        print(f"    中位數 ：{rp[50]:+.1f}%")
        print(f"    75 分位：{rp[75]:+.1f}%")
        print(f"    最好 5%：{rp[95]:+.1f}%")
        print(f"  最大回撤信賴區間：")
        print(f"    最差 5%：{dp[5]:.1f}%")
        print(f"    中位數 ：{dp[50]:.1f}%")

    # 流動性警告
    liquidity_warn = _check_liquidity(df)
    if liquidity_warn:
        print(f"\n {liquidity_warn}")

    # 注意事項
    print(f"\n ⚠ 重要提醒：")
    print(f"  • 回測不代表未來績效，過去表現不保證未來結果")
    if is_us:
        print(f"  • 美股零佣金 + 滑價 {SLIPPAGE_PCT}%（未計入匯率波動）")
    else:
        print(f"  • 已計算手續費（買賣各 0.1425%）+ 證交稅 0.3% + 滑價 {SLIPPAGE_PCT}%")
    print(f"  • 停損改用 ATR 動態計算（2倍ATR，適應不同波動度）")
    if wf_result:
        print(f"  • Walk-Forward 驗證：只看「樣本外」績效，防止 curve-fitting")
    if mc_result:
        print(f"  • Monte Carlo：模擬 {mc_result['n_simulations']} 種交易排列，測試運氣成分")
    if len(trades) < 5:
        print(f"  • 交易次數偏少（{len(trades)} 次），統計意義有限")

    print()
    print("=" * w)
    print()


def main():
    if len(sys.argv) < 2:
        print("簡易回測工具")
        print("=" * 30)
        print("用法：python3 backtest.py <股票代號> [回測天數]")
        print("範例：python3 backtest.py 2330")
        print("      python3 backtest.py 2330 365")
        sys.exit(1)

    stock_id = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    print(f"\n⏳ 回測 {stock_id}（{days} 天）...\n")

    name = market.fetch_stock_name(stock_id)
    print(f"  股票：{stock_id} {name}")

    print(f"  抓取歷史資料（還原權息價）...")
    price_df = market.fetch_stock_price_adjusted(stock_id, days=days)

    if price_df.empty or len(price_df) < 60:
        print("  ⚠ 資料不足，至少需要 60 天以上的資料")
        sys.exit(1)

    price_df = price_df.sort_values("date").reset_index(drop=True)
    print(f"  → 取得 {len(price_df)} 筆日K資料")

    is_us = market.is_us(stock_id)

    # 策略 A：均線交叉（波段）
    print(f"  [策略A] 均線交叉...")
    signals_a, hold_a = generate_signals(price_df)
    trades_a = calculate_trades(signals_a, is_us=is_us)
    print(f"  → {len(trades_a)} 筆交易")

    # [R4] Walk-Forward + Monte Carlo（只在資料夠多時跑）
    wf_a = None
    mc_a = None
    if len(price_df) >= 200:
        print(f"  [R4] Walk-Forward 驗證...")
        wf_a = walk_forward(price_df, generate_signals, calculate_trades, is_us=is_us)
        print(f"  → {len(wf_a['oos_trades'])} 筆樣本外交易")
    if trades_a and len(trades_a) >= 5:
        print(f"  [R4] Monte Carlo 模擬...")
        mc_a = monte_carlo(trades_a)

    # 策略 B：趨勢跟蹤（多頭友善）
    print(f"  [策略B] 趨勢跟蹤...")
    signals_b, hold_b = generate_signals_trend(price_df)
    trades_b = calculate_trades(signals_b, is_us=is_us)
    print(f"  → {len(trades_b)} 筆交易")

    wf_b = None
    mc_b = None
    if len(price_df) >= 200:
        wf_b = walk_forward(price_df, generate_signals_trend, calculate_trades, is_us=is_us)
    if trades_b and len(trades_b) >= 5:
        mc_b = monte_carlo(trades_b)

    # 策略 C：長線佈局（逢低買、漲高賣）
    print(f"  [策略C] 長線佈局...")
    signals_c, hold_c = generate_signals_value(price_df)
    trades_c = calculate_trades(signals_c, is_us=is_us)
    print(f"  → {len(trades_c)} 筆交易")

    wf_c = None
    mc_c = None
    if len(price_df) >= 300:
        wf_c = walk_forward(price_df, generate_signals_value, calculate_trades,
                            is_us=is_us, min_train=180)
    if trades_c and len(trades_c) >= 5:
        mc_c = monte_carlo(trades_c)

    # 策略 D：R6 複合評分（多因子）
    print(f"  [策略D] R6 複合評分...")
    signals_d, hold_d = generate_signals_composite(price_df)
    trades_d = calculate_trades(signals_d, is_us=is_us)
    print(f"  → {len(trades_d)} 筆交易")

    wf_d = None
    mc_d = None
    if len(price_df) >= 200:
        wf_d = walk_forward(price_df, generate_signals_composite, calculate_trades, is_us=is_us)
    if trades_d and len(trades_d) >= 5:
        mc_d = monte_carlo(trades_d)

    print_report(stock_id, name, price_df, trades_a, hold_a, is_us=is_us,
                 strategy_name="均線交叉 + RSI + 量能 + 停損 -8%（波段）",
                 wf_result=wf_a, mc_result=mc_a)
    print_report(stock_id, name, price_df, trades_b, hold_b, is_us=is_us,
                 strategy_name="趨勢跟蹤 — 20/60MA + 移動停利 -10%（順勢）",
                 wf_result=wf_b, mc_result=mc_b)
    print_report(stock_id, name, price_df, trades_c, hold_c, is_us=is_us,
                 strategy_name="長線佈局 — 逢低買入 + 漲高出場 + 停利 -12%",
                 wf_result=wf_c, mc_result=mc_c)
    print_report(stock_id, name, price_df, trades_d, hold_d, is_us=is_us,
                 strategy_name="[R6] 複合評分 — ADX+MA+RSI+量能+過熱保護",
                 wf_result=wf_d, mc_result=mc_d)


if __name__ == "__main__":
    main()
