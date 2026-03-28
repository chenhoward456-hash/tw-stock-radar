"""
風險管理模組（R5 新增）

功能：
1. ATR 移動停損 — 動態追蹤，停損線只上不下
2. 分批停利 — 到 1R 出一半，到 2R 出剩下的
3. 整體資金回撤限制 — 總回撤超過閾值，發出全面減倉警告
4. 單一持倉風險指標 — 倉位比例、風險金額、R 倍數

設計原則：
- 本模組只做計算，不依賴 market/technical 等資料模組
- 所有函數接受純量輸入，回傳 dict
- 可被 monitor.py 和 app.py 直接引用
"""


# ─── Phase 1-A: ATR 移動停損 ─────────────────────────────────────────────────

def get_dynamic_atr_multiplier(macro_score=None):
    """
    [R6] 根據 macro 環境動態調整 ATR 乘數

    牛市（macro ≥ 7）：2.0x — 給波動空間，讓贏家跑
    中性（macro 4-7）：1.8x — 稍微收緊
    熊市（macro < 4）：1.5x — 收緊停損，保護資金

    回傳：atr_multiplier (float)
    """
    if macro_score is None:
        return 2.0
    if macro_score >= 7:
        return 2.0
    elif macro_score >= 4:
        return 1.8
    else:
        return 1.5


def calc_atr_trailing_stop(current_price, buy_price, peak_price, atr,
                            atr_multiplier=2.0, min_stop_pct=0.08):
    """
    計算 ATR 移動停損（trailing stop），停損線只跟漲、不跟跌。

    邏輯：
      initial_stop  = max(buy_price - mult×ATR, buy_price×(1-min_pct))
      trailing_stop = max(peak_price - mult×ATR, initial_stop)

    參數：
      current_price   當前股價
      buy_price       買入價
      peak_price      持倉期間最高點（可傳 None，此時以 current_price 代替）
      atr             ATR（平均真實波幅）
      atr_multiplier  ATR 倍數（預設 2.0）
      min_stop_pct    最小停損距離（預設 8%）

    回傳 dict：
      initial_stop    初始停損價
      trailing_stop   當前移動停損價（= max(以高點計算, initial_stop)）
      stop_type       "ATR移動停損" / "固定百分比（ATR偏小）"
      stop_pct        停損距離佔買入價的百分比
      peak_used       實際用於計算的最高點
      atr_distance    ATR 倍數距離（mult × ATR）
      should_exit     是否已觸及停損（current_price <= trailing_stop）
    """
    if buy_price <= 0 or atr <= 0:
        return {
            "initial_stop": 0,
            "trailing_stop": 0,
            "stop_type": "資料不足",
            "stop_pct": 0,
            "peak_used": current_price,
            "atr_distance": 0,
            "should_exit": False,
        }

    atr_dist = atr_multiplier * atr
    initial_stop_atr = buy_price - atr_dist
    initial_stop_pct_val = buy_price * (1 - min_stop_pct)
    initial_stop = max(initial_stop_atr, initial_stop_pct_val)

    peak = peak_price if (peak_price and peak_price > buy_price) else max(current_price, buy_price)
    trailing_from_peak = peak - atr_dist
    trailing_stop = max(trailing_from_peak, initial_stop)

    # 判斷是 ATR 停損還是百分比停損在作用
    if initial_stop >= initial_stop_atr:
        stop_type = "固定百分比（ATR偏小）"
    else:
        stop_type = "ATR移動停損"

    stop_pct = (buy_price - initial_stop) / buy_price * 100

    return {
        "initial_stop": round(initial_stop, 2),
        "trailing_stop": round(trailing_stop, 2),
        "stop_type": stop_type,
        "stop_pct": round(stop_pct, 1),
        "peak_used": round(peak, 2),
        "atr_distance": round(atr_dist, 2),
        "should_exit": current_price > 0 and current_price <= trailing_stop,
    }


# ─── Phase 1-B: 分批停利 ────────────────────────────────────────────────────

def calc_partial_tp(current_price, buy_price, shares, entry_stop=None, atr=None):
    """
    計算分批停利目標（R 倍數系統）。

    R = buy_price - entry_stop  （每股風險 = 1R）
    TP1 = buy_price + 1R  →  到達時出一半倉
    TP2 = buy_price + 2R  →  到達時出剩餘倉
    TP3 = buy_price + 3R  →  延伸目標（可選擇繼續持有）

    若無 entry_stop，使用 buy_price - 2×ATR 或 buy_price × 8%。

    參數：
      current_price   當前股價
      buy_price       買入價
      shares          持有股數
      entry_stop      進場停損價（可為 None）
      atr             ATR（entry_stop 為 None 時使用）

    回傳 dict：
      r_value         每股 1R 風險
      entry_stop      有效停損價
      tp1_price       1R 目標價
      tp2_price       2R 目標價
      tp3_price       3R 目標價（延伸目標）
      tp1_reached     是否已到 1R
      tp2_reached     是否已到 2R
      tp1_shares      1R 時建議出場股數（一半）
      tp2_shares      2R 時建議出場股數（剩下）
      current_r       當前盈虧是幾個 R（可為負）
      unrealized_r    未實現損益 in R
      status          狀態描述
      action          建議行動
    """
    if buy_price <= 0:
        return {"error": "buy_price 無效"}

    # 決定有效停損
    if entry_stop and entry_stop > 0 and entry_stop < buy_price:
        eff_stop = entry_stop
    elif atr and atr > 0:
        eff_stop = buy_price - 2 * atr
    else:
        eff_stop = buy_price * 0.92  # 預設 -8%

    r_value = buy_price - eff_stop
    if r_value <= 0:
        r_value = buy_price * 0.08

    tp1 = buy_price + 1.0 * r_value
    tp2 = buy_price + 2.0 * r_value
    tp3 = buy_price + 3.0 * r_value

    current_r = (current_price - buy_price) / r_value if r_value > 0 else 0
    tp1_reached = current_price >= tp1
    tp2_reached = current_price >= tp2

    tp1_shares = shares // 2
    tp2_shares = shares - tp1_shares

    # 狀態與建議
    if tp2_reached:
        status = f"已到 2R 目標（{tp2:.1f} 元）"
        action = f"建議出清剩餘 {tp2_shares} 股，若趨勢強可持有至 3R（{tp3:.1f} 元）"
    elif tp1_reached:
        status = f"已到 1R 目標（{tp1:.1f} 元）"
        action = f"建議減倉 {tp1_shares} 股，剩 {tp2_shares} 股等 2R（{tp2:.1f} 元）"
    elif current_r >= 0.5:
        status = f"接近 1R 目標（當前 {current_r:.1f}R）"
        action = f"繼續持有，1R 目標 {tp1:.1f} 元"
    elif current_r >= 0:
        status = f"持有中（{current_r:.1f}R）"
        action = f"持有，1R={tp1:.1f} 元，2R={tp2:.1f} 元"
    else:
        status = f"帳面虧損（{current_r:.1f}R）"
        action = f"停損在 {eff_stop:.1f} 元"

    return {
        "r_value": round(r_value, 2),
        "entry_stop": round(eff_stop, 2),
        "tp1_price": round(tp1, 1),
        "tp2_price": round(tp2, 1),
        "tp3_price": round(tp3, 1),
        "tp1_reached": tp1_reached,
        "tp2_reached": tp2_reached,
        "tp1_shares": tp1_shares,
        "tp2_shares": tp2_shares,
        "current_r": round(current_r, 2),
        "status": status,
        "action": action,
    }


def calc_smart_exit(current_price, buy_price, shares, current_score,
                    entry_stop=None, atr=None):
    """
    [R6] 智慧出場 — 到 R 目標時根據當前評分決定出多少

    傳統 R 系統：到 2R 就全出。
    智慧出場：
      - 到 2R + score ≥ 7 → 只出 25%，trailing stop 拉到 1R（讓贏家繼續跑）
      - 到 2R + score 5-7 → 出 50%
      - 到 2R + score < 5 → 全出
      - 到 1R + score ≥ 7 → 出 30%（而非 50%）
      - 到 1R + score < 5 → 出 60%

    參數：
      current_score: 當前加權綜合分數（重新評分後的）
    """
    if buy_price <= 0:
        return {"error": "buy_price invalid"}

    # 算 R
    if entry_stop and entry_stop > 0 and entry_stop < buy_price:
        eff_stop = entry_stop
    elif atr and atr > 0:
        eff_stop = buy_price - 2 * atr
    else:
        eff_stop = buy_price * 0.92

    r_value = buy_price - eff_stop
    if r_value <= 0:
        r_value = buy_price * 0.08

    current_r = (current_price - buy_price) / r_value if r_value > 0 else 0

    tp1 = buy_price + 1.0 * r_value
    tp2 = buy_price + 2.0 * r_value
    tp3 = buy_price + 3.0 * r_value

    # 智慧出場邏輯
    if current_r >= 2.0:
        if current_score >= 7:
            sell_pct = 0.25
            new_stop = tp1
            reason = f"到 2R 但評分仍強（{current_score}），只出 25%，停損拉到 1R（{tp1:.1f}）讓贏家跑"
        elif current_score >= 5:
            sell_pct = 0.50
            new_stop = buy_price + 0.5 * r_value
            reason = f"到 2R，評分中性（{current_score}），出 50%，停損拉到 0.5R"
        else:
            sell_pct = 1.0
            new_stop = None
            reason = f"到 2R 且評分轉弱（{current_score}），建議全部出場"
    elif current_r >= 1.0:
        if current_score >= 7:
            sell_pct = 0.30
            new_stop = eff_stop  # 維持原停損
            reason = f"到 1R，評分強（{current_score}），只出 30%，持續追蹤"
        elif current_score >= 5:
            sell_pct = 0.50
            new_stop = eff_stop
            reason = f"到 1R，評分中性（{current_score}），出 50%"
        else:
            sell_pct = 0.60
            new_stop = eff_stop
            reason = f"到 1R 但評分轉弱（{current_score}），出 60%，剩餘設緊停損"
    else:
        sell_pct = 0.0
        new_stop = eff_stop
        if current_r < 0:
            reason = f"虧損中（{current_r:.1f}R），持有或停損在 {eff_stop:.1f}"
        else:
            reason = f"未到 1R（當前 {current_r:.1f}R），繼續持有"

    sell_shares = int(shares * sell_pct)

    return {
        "current_r": round(current_r, 2),
        "current_score": current_score,
        "sell_pct": sell_pct,
        "sell_shares": sell_shares,
        "remain_shares": shares - sell_shares,
        "new_stop": round(new_stop, 2) if new_stop else None,
        "tp1": round(tp1, 1),
        "tp2": round(tp2, 1),
        "tp3": round(tp3, 1),
        "reason": reason,
    }


# ─── Phase 1-C: 整體資金回撤限制 ────────────────────────────────────────────

def check_portfolio_drawdown(holdings_list, total_budget, drawdown_threshold=0.15):
    """
    計算整體持倉回撤並判斷是否觸發減倉警告。

    回撤定義：持倉總虧損 / 總資金（非相對成本，是相對你的總資金）。

    參數：
      holdings_list      list of dict，每個 dict 需含 current_price, buy_price, shares
      total_budget       總資金（用於計算回撤比例）
      drawdown_threshold 最大容忍回撤比例（預設 0.15 = 15%）

    回傳 dict：
      total_cost         持倉買入成本
      total_value        持倉當前市值
      total_pnl          總損益（元）
      total_pnl_pct      持倉損益率（%）
      drawdown_from_budget  虧損佔總資金的比例（%）
      threshold_pct      閾值（%）
      threshold_reached  是否觸發
      risk_level         "normal" / "warning" / "critical"
      action             建議行動
    """
    total_cost = 0.0
    total_value = 0.0
    for h in holdings_list:
        bp = h.get("buy_price", 0) or 0
        cp = h.get("current_price", 0) or 0
        sh = h.get("shares", 0) or 0
        total_cost += bp * sh
        if cp > 0:
            total_value += cp * sh

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0.0

    # 回撤：只計虧損部分；若是獲利則回撤為 0
    loss_amount = max(-total_pnl, 0)
    drawdown_pct = loss_amount / total_budget * 100 if total_budget > 0 else 0.0

    thresh_pct = drawdown_threshold * 100
    warn_pct = thresh_pct * 0.70  # 70% 警戒

    if drawdown_pct >= thresh_pct:
        risk_level = "critical"
        action = (f"🚨 整體回撤 {drawdown_pct:.1f}%，已超過 {thresh_pct:.0f}% 閾值！"
                  f"建議全面檢視持倉，強制執行停損計畫")
    elif drawdown_pct >= warn_pct:
        risk_level = "warning"
        action = (f"⚠ 整體回撤 {drawdown_pct:.1f}%，接近 {thresh_pct:.0f}% 警戒線，"
                  f"建議預先規劃減倉")
    elif total_pnl_pct >= 0:
        risk_level = "normal"
        action = f"✅ 持倉整體獲利 {total_pnl_pct:+.1f}%，風控正常"
    else:
        risk_level = "normal"
        action = f"📊 整體回撤 {drawdown_pct:.1f}%，在安全範圍內（上限 {thresh_pct:.0f}%）"

    return {
        "total_cost": round(total_cost),
        "total_value": round(total_value),
        "total_pnl": round(total_pnl),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "drawdown_from_budget": round(drawdown_pct, 2),
        "threshold_pct": thresh_pct,
        "threshold_reached": drawdown_pct >= thresh_pct,
        "risk_level": risk_level,
        "action": action,
    }


# ─── Phase 1-D: 單一持倉風險指標 ────────────────────────────────────────────

def get_position_risk_metrics(holding, total_budget, trailing_stop_price=None):
    """
    計算單一持倉的風險指標。

    參數：
      holding           dict，含 buy_price, shares, current_price（可選）, stop_loss（可選）
      total_budget      總資金
      trailing_stop_price  ATR 移動停損價（可覆蓋 holding 的 stop_loss）

    回傳 dict：
      position_value     持倉現值
      position_pct       佔總資金比例（%）
      effective_stop     有效停損價（優先用移動停損）
      risk_per_share     每股風險（buy_price - stop）
      risk_amount        若觸停損最大虧損金額
      risk_pct           若觸停損佔總資金的比例（%）
      r_multiple         當前盈虧是幾個 R
      pnl_amount         未實現損益金額
    """
    buy_price = holding.get("buy_price", 0) or 0
    shares = holding.get("shares", 0) or 0
    current_price = holding.get("current_price", buy_price) or buy_price
    stop_loss = holding.get("stop_loss", 0) or 0

    # 有效停損優先順序：ATR 移動停損 > 手動停損 > 預設 8%
    if trailing_stop_price and trailing_stop_price > 0:
        effective_stop = trailing_stop_price
    elif stop_loss > 0:
        effective_stop = stop_loss
    else:
        effective_stop = buy_price * 0.92

    position_value = current_price * shares
    position_pct = position_value / total_budget * 100 if total_budget > 0 else 0.0

    risk_per_share = max(buy_price - effective_stop, 0)
    risk_amount = risk_per_share * shares
    risk_pct = risk_amount / total_budget * 100 if total_budget > 0 else 0.0

    pnl_amount = (current_price - buy_price) * shares
    r_multiple = (current_price - buy_price) / risk_per_share if risk_per_share > 0 else 0.0

    return {
        "position_value": round(position_value),
        "position_pct": round(position_pct, 1),
        "effective_stop": round(effective_stop, 2),
        "risk_per_share": round(risk_per_share, 2),
        "risk_amount": round(risk_amount),
        "risk_pct": round(risk_pct, 2),
        "r_multiple": round(r_multiple, 2),
        "pnl_amount": round(pnl_amount),
    }
