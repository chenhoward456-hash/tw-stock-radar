"""
資金配置模組
根據評分和預算，建議該投入多少錢
"""
import math


def suggest(score, stock_price, budget):
    """
    根據綜合評分和預算建議配置
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
    }


def format_report(suggestion, stock_price, ma20, budget):
    """格式化資金配置建議"""
    lines = []

    if suggestion is None:
        lines.append("  ⚠ 目前評分偏低，不建議進場配置")
        return lines

    s = suggestion
    lines.append(f"  投資信心：{s['conviction']}（建議配置 {s['target_pct']:.0f}% 以內）")
    lines.append(f"  你的總預算：{budget:,.0f} 元")

    if s["lots"] > 0:
        lines.append(f"  建議買入：{s['lots']} 張（每張 {s['price_per_lot']:,.0f} 元）")
        lines.append(f"  投入金額：{s['amount']:,.0f} 元（佔總預算 {s['actual_pct']:.1f}%）")
    elif s["odd_shares"] > 0:
        lines.append(f"  買不起整張，建議買零股：{s['odd_shares']} 股")
        lines.append(f"  投入金額：{s['amount']:,.0f} 元（佔總預算 {s['actual_pct']:.1f}%）")
    else:
        lines.append(f"  ⚠ 預算不足以買入此股票")
        return lines

    # 停損試算
    if ma20 and ma20 > 0 and stock_price > 0:
        stop_loss_per_share = stock_price - ma20
        if stop_loss_per_share > 0:
            total_shares = s["lots"] * 1000 if s["lots"] > 0 else s["odd_shares"]
            max_loss = stop_loss_per_share * total_shares
            max_loss_pct = max_loss / s["amount"] * 100 if s["amount"] > 0 else 0
            lines.append(
                f"  停損試算：若跌到 20日均線 {ma20:.0f} 元，"
                f"虧損約 {max_loss:,.0f} 元（-{max_loss_pct:.1f}%）"
            )

    return lines
