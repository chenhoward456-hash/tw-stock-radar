"""
資金配置模組（第四輪：Kelly Criterion + 波動率調整）

改進：
1. 加入持倉相關性檢查：新買入標的若與現有持倉高度相關，自動降低倉位
2. 使用 ATR 動態停損取代固定 20MA 停損
3. 單一產業集中度上限
4. [R4] Kelly Criterion 計算最佳倉位比例
5. [R4] 波動率調整：高波動自動降倉，低波動可加碼
6. [R4] 風險預算：單筆最大虧損 ≤ 總資金 2%
"""
import math
import numpy as np


def _kelly_fraction(win_rate, avg_win, avg_loss):
    """
    Kelly Criterion 計算最佳倉位比例
    f* = (p * b - q) / b
    p = 勝率, q = 1-p, b = 盈虧比 (avg_win / avg_loss)

    使用 Half-Kelly 降低風險（實務上 Full Kelly 波動太大）
    """
    if avg_loss <= 0 or win_rate <= 0:
        return 0
    b = avg_win / avg_loss  # 盈虧比
    q = 1 - win_rate
    f = (win_rate * b - q) / b
    # Half-Kelly 比較保守
    f = f * 0.5
    return max(0, min(f, 0.25))  # 上限 25%


def _volatility_adjustment(atr, price, baseline_vol=0.02):
    """
    波動率調整因子
    用 ATR/price (日波動率) 跟基準波動率比較
    高波動 → 縮小倉位, 低波動 → 放大倉位（但不超過 1.3x）

    baseline_vol: 基準日波動率 2%（一般個股）
    """
    if not atr or not price or price <= 0:
        return 1.0
    daily_vol = atr / price
    if daily_vol <= 0:
        return 1.0
    factor = baseline_vol / daily_vol
    return max(0.4, min(1.3, factor))  # 最多放大 30%，最多縮小到 40%


def _risk_budget_cap(price, stop_price, budget, max_loss_pct=0.02):
    """
    風險預算：單筆最大虧損 ≤ 總資金的 max_loss_pct（預設 2%）
    回傳：最多能買幾股（整數）
    """
    if not stop_price or stop_price <= 0 or price <= 0:
        return None
    risk_per_share = price - stop_price
    if risk_per_share <= 0:
        return None
    max_loss = budget * max_loss_pct
    max_shares = int(max_loss / risk_per_share)
    return max(0, max_shares)


def suggest(score, stock_price, budget, existing_holdings=None,
            correlation_with_holdings=None, atr=None,
            win_rate=None, avg_win=None, avg_loss=None,
            stop_price=None):
    """
    根據綜合評分和預算建議配置

    參數（R4 新增）：
    - win_rate: 歷史勝率（0-1），用於 Kelly 計算
    - avg_win: 平均獲利 %
    - avg_loss: 平均虧損 %（正數）
    - stop_price: 預計停損價，用於風險預算

    回傳：dict 或 None（如果不建議買）
    """
    if budget <= 0 or stock_price <= 0:
        return None

    # === 基礎倉位（信念度分級）===
    if score >= 8:
        base_pct = 0.15
        conviction = "高"
    elif score >= 6.5:
        base_pct = 0.10
        conviction = "中高"
    elif score >= 5.5:
        base_pct = 0.05
        conviction = "中"
    elif score >= 4.5:
        base_pct = 0.03
        conviction = "低"
    else:
        return None

    # === [R4] Kelly Criterion 建議 ===
    kelly_info = None
    kelly_pct = None
    if win_rate and avg_win and avg_loss and win_rate > 0:
        kelly_f = _kelly_fraction(win_rate, avg_win, avg_loss)
        kelly_pct = kelly_f
        if kelly_f <= 0:
            kelly_info = "⚠ Kelly 建議不進場（期望值為負）"
            # Kelly 說不要買但分數還行 → 降到最低
            base_pct = min(base_pct, 0.03)
        else:
            kelly_info = f"Kelly 建議倉位 {kelly_f*100:.1f}%（Half-Kelly）"
            # 取評分建議和 Kelly 的較小值（保守原則）
            base_pct = min(base_pct, kelly_f)

    pct = base_pct

    # === [R4] 波動率調整 ===
    vol_adj = 1.0
    vol_info = None
    if atr and stock_price > 0:
        vol_adj = _volatility_adjustment(atr, stock_price)
        pct *= vol_adj
        if vol_adj < 0.8:
            vol_info = f"⚠ 波動偏高（ATR/價格={atr/stock_price*100:.1f}%），倉位 ×{vol_adj:.2f}"
        elif vol_adj > 1.1:
            vol_info = f"✓ 波動偏低，倉位可放大 ×{vol_adj:.2f}"

    # === 相關性降倉 ===
    correlation_warning = None
    if correlation_with_holdings is not None and correlation_with_holdings > 0.5:
        if correlation_with_holdings > 0.8:
            pct *= 0.5
            correlation_warning = f"⚠ 與現有持倉高度相關（{correlation_with_holdings:.2f}），倉位自動減半"
        elif correlation_with_holdings > 0.7:
            pct *= 0.7
            correlation_warning = f"⚠ 與現有持倉相關性偏高（{correlation_with_holdings:.2f}），倉位自動打七折"

    # === 持倉數量上限 ===
    position_warning = None
    if existing_holdings and len(existing_holdings) >= 10:
        pct = min(pct, 0.05)
        position_warning = "⚠ 已持有 10 檔以上，建議單檔不超過 5%"

    # 上限：單一個股不超過 20%
    pct = min(pct, 0.20)

    amount = budget * pct
    price_per_lot = stock_price * 1000  # 1張 = 1000股
    lots = math.floor(amount / price_per_lot) if price_per_lot > 0 else 0

    # 如果買不起一張，算零股
    odd_shares = 0
    if lots == 0 and amount >= stock_price:
        odd_shares = math.floor(amount / stock_price)

    # === [R4] 風險預算限制 ===
    risk_budget_warning = None
    if stop_price and stop_price > 0 and stock_price > stop_price:
        max_shares = _risk_budget_cap(stock_price, stop_price, budget)
        if max_shares is not None:
            total_shares = lots * 1000 + odd_shares
            if total_shares > max_shares:
                # 需要降低部位
                risk_budget_warning = (
                    f"⚠ 風險預算限制：最多 {max_shares} 股"
                    f"（單筆虧損不超過總資金 2%）"
                )
                if max_shares >= 1000:
                    lots = max_shares // 1000
                    odd_shares = 0
                else:
                    lots = 0
                    odd_shares = max_shares

    actual_amount = lots * price_per_lot if lots > 0 else odd_shares * stock_price
    actual_pct = actual_amount / budget * 100 if budget > 0 else 0

    return {
        "conviction": conviction,
        "target_pct": pct * 100,
        "amount": actual_amount,
        "actual_pct": actual_pct,
        "lots": lots,
        "odd_shares": odd_shares,
        "price_per_lot": price_per_lot,
        "correlation_warning": correlation_warning,
        "position_warning": position_warning,
        # R4 新增
        "kelly_info": kelly_info,
        "kelly_pct": round(kelly_pct * 100, 1) if kelly_pct else None,
        "vol_adjustment": round(vol_adj, 2),
        "vol_info": vol_info,
        "risk_budget_warning": risk_budget_warning,
    }


def format_report(suggestion, stock_price, ma20, budget, atr=None, stop_loss=None):
    """格式化資金配置建議（改進版：支援 ATR 停損 + Kelly + 波動率）"""
    lines = []

    if suggestion is None:
        lines.append("  ⚠ 目前評分偏低，不建議進場配置")
        return lines

    s = suggestion
    lines.append(f"  投資信心：{s['conviction']}（建議配置 {s['target_pct']:.1f}% 以內）")
    lines.append(f"  你的總預算：{budget:,.0f} 元")

    # Kelly 資訊
    if s.get("kelly_info"):
        lines.append(f"  📊 {s['kelly_info']}")

    # 波動率調整
    if s.get("vol_info"):
        lines.append(f"  {s['vol_info']}")

    # 相關性 / 集中度警告
    if s.get("correlation_warning"):
        lines.append(f"  {s['correlation_warning']}")
    if s.get("position_warning"):
        lines.append(f"  {s['position_warning']}")
    if s.get("risk_budget_warning"):
        lines.append(f"  {s['risk_budget_warning']}")

    if s["lots"] > 0:
        lines.append(f"  建議買入：{s['lots']} 張（每張 {s['price_per_lot']:,.0f} 元）")
        lines.append(f"  投入金額：{s['amount']:,.0f} 元（佔總預算 {s['actual_pct']:.1f}%）")
    elif s["odd_shares"] > 0:
        lines.append(f"  買不起整張，建議買零股：{s['odd_shares']} 股")
        lines.append(f"  投入金額：{s['amount']:,.0f} 元（佔總預算 {s['actual_pct']:.1f}%）")
    else:
        lines.append(f"  ⚠ 預算不足以買入此股票")
        return lines

    # 停損試算（優先用 ATR 動態停損）
    effective_stop = stop_loss or ma20
    if effective_stop and effective_stop > 0 and stock_price > 0:
        stop_loss_per_share = stock_price - effective_stop
        if stop_loss_per_share > 0:
            total_shares = s["lots"] * 1000 if s["lots"] > 0 else s["odd_shares"]
            max_loss = stop_loss_per_share * total_shares
            max_loss_pct = max_loss / s["amount"] * 100 if s["amount"] > 0 else 0

            if atr and atr > 0:
                lines.append(
                    f"  停損試算：若跌到 {effective_stop:.0f} 元（ATR 動態停損），"
                    f"虧損約 {max_loss:,.0f} 元（-{max_loss_pct:.1f}%）"
                )
            else:
                lines.append(
                    f"  停損試算：若跌到 20日均線 {effective_stop:.0f} 元，"
                    f"虧損約 {max_loss:,.0f} 元（-{max_loss_pct:.1f}%）"
                )

    return lines
