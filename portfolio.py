"""
資金配置模組（改進版）
根據評分和預算，建議該投入多少錢

改進：
1. 加入持倉相關性檢查：新買入標的若與現有持倉高度相關，自動降低倉位
2. 使用 ATR 動態停損取代固定 20MA 停損
3. 單一產業集中度上限
"""
import math


def suggest(score, stock_price, budget, existing_holdings=None,
            correlation_with_holdings=None, atr=None):
    """
    根據綜合評分和預算建議配置

    新增參數：
    - existing_holdings: list of dict，現有持倉（用來檢查集中度）
    - correlation_with_holdings: float，新標的與現有持倉的最大相關係數
    - atr: float，ATR 值（用於動態停損計算）

    回傳：dict 或 None（如果不建議買）
    """
    if budget <= 0 or stock_price <= 0:
        return None

    # 根據評分決定配置比例
    if score >= 8:
        pct = 0.15       # 最多 15%
        conviction = "高"
    elif score >= 6.5:
        pct = 0.10       # 最多 10%
        conviction = "中高"
    elif score >= 5.5:
        pct = 0.05       # 最多 5%
        conviction = "中"
    elif score >= 4.5:
        pct = 0.03       # 最多 3%
        conviction = "低"
    else:
        return None       # 不建議買

    # === 相關性降倉 ===
    correlation_warning = None
    if correlation_with_holdings is not None and correlation_with_holdings > 0.5:
        if correlation_with_holdings > 0.8:
            # 高度相關：倉位減半
            pct *= 0.5
            correlation_warning = f"⚠ 與現有持倉高度相關（{correlation_with_holdings:.2f}），倉位自動減半"
        elif correlation_with_holdings > 0.7:
            # 中度相關：倉位打七折
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
    }


def format_report(suggestion, stock_price, ma20, budget, atr=None, stop_loss=None):
    """格式化資金配置建議（改進版：支援 ATR 停損）"""
    lines = []

    if suggestion is None:
        lines.append("  ⚠ 目前評分偏低，不建議進場配置")
        return lines

    s = suggestion
    lines.append(f"  投資信心：{s['conviction']}（建議配置 {s['target_pct']:.0f}% 以內）")
    lines.append(f"  你的總預算：{budget:,.0f} 元")

    # 相關性 / 集中度警告
    if s.get("correlation_warning"):
        lines.append(f"  {s['correlation_warning']}")
    if s.get("position_warning"):
        lines.append(f"  {s['position_warning']}")

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
