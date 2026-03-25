"""
報告生成模組
"""
import portfolio

SIGNAL_ICON = {
    "green": "🟢 綠燈",
    "yellow": "🟡 黃燈",
    "red": "🔴 紅燈",
}


def generate(stock_id, stock_name, technical, fundamental, institutional_result,
             news_result=None, budget=0, portfolio_suggestion=None):
    """產生決策檢查報告"""

    w = 55

    print()
    print("=" * w)
    print(f" {stock_id} {stock_name} — 決策檢查報告 ".center(w))
    print("=" * w)

    sections = [
        ("技術面", technical),
        ("基本面", fundamental),
        ("籌碼面", institutional_result),
    ]
    if news_result:
        sections.append(("消息面", news_result))

    for name, data in sections:
        icon = SIGNAL_ICON[data["signal"]]
        print()
        print(f"【{name}】{icon}（{data['score']}/10）")
        for line in data["details"]:
            print(f"  {line}")

    # 綜合評分
    scores = [technical["score"], fundamental["score"], institutional_result["score"]]
    if news_result:
        scores.append(news_result["score"])
    avg = round(sum(scores) / len(scores), 1)

    if avg >= 7:
        overall = "green"
        advice = "各面向條件良好，可以考慮佈局。"
    elif avg >= 5.5:
        overall = "yellow"
        advice = "條件尚可，建議分批進場，不要一次重壓。"
    elif avg >= 4:
        overall = "yellow"
        advice = "條件普通，建議觀望或僅小量試水。"
    else:
        overall = "red"
        advice = "多項指標偏空，目前不建議進場。"

    print()
    print("-" * w)
    print(f"【綜合評分】{SIGNAL_ICON[overall]}  {avg} / 10")
    print(f"【建議】{advice}")

    if "current_price" in technical and "ma20" in technical:
        price = technical["current_price"]
        ma20 = technical["ma20"]
        gap = (ma20 / price - 1) * 100
        print(f"【停損參考】20日均線 {ma20:.1f} 元（距現價 {gap:+.1f}%）")

    # 資金配置
    if budget > 0:
        print()
        print("-" * w)
        print("【資金配置建議】")
        ma20 = technical.get("ma20", 0)
        price = technical.get("current_price", 0)
        lines = portfolio.format_report(portfolio_suggestion, price, ma20, budget)
        for line in lines:
            print(line)

    print()
    print("=" * w)
    print("⚠ 以上僅供參考，不構成投資建議。投資有風險，請謹慎評估。")
    print("=" * w)
    print()
