#!/usr/bin/env python3
"""
臺股決策檢查器
用法：python3 check.py 2330
      python3 check.py 2330 500000    （帶預算，會多一段資金配置建議）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TOTAL_BUDGET
import market
import technical
import fundamental
import institutional
import news
import portfolio
import report


def check(stock_id, budget=0):
    """對指定股票進行多維度檢查"""
    stock_id = str(stock_id).strip()

    print(f"\n🔍 正在分析 {stock_id}，請稍候...\n")

    # 抓取資料
    print("[1/7] 查詢股票名稱...")
    name = market.fetch_stock_name(stock_id)
    print(f"  → {name}")

    print("[2/7] 查詢產業類別...")
    industry = market.fetch_stock_industry(stock_id)
    print(f"  → {industry or '未知'}")

    print("[3/7] 抓取股價資料...")
    price_df = market.fetch_stock_price(stock_id)
    print(f"  → {len(price_df)} 筆日K資料")

    print("[4/7] 抓取法人買賣超...")
    inst_df = market.fetch_institutional(stock_id)
    print(f"  → {len(inst_df)} 筆法人資料")

    print("[5/7] 抓取本益比...")
    per_df = market.fetch_per_pbr(stock_id)
    print(f"  → {len(per_df)} 筆估值資料")

    print("[6/7] 抓取月營收...")
    rev_df = market.fetch_monthly_revenue(stock_id)
    print(f"  → {len(rev_df)} 筆營收資料")

    print("[7/7] 掃描近期新聞...")
    news_result = news.analyze(stock_id, name)
    print(f"  → 完成")

    # 分析
    print("\n⚙ 分析中...\n")
    tech = technical.analyze(price_df)
    if market.is_etf(stock_id):
        etf_info = market.fetch_etf_info(stock_id)
        fund = fundamental.analyze_etf(price_df, etf_info, per_df)
    else:
        fund = fundamental.analyze(per_df, rev_df, industry)
    inst = institutional.analyze(inst_df)

    # 資金配置
    portfolio_suggestion = None
    if budget > 0 and "current_price" in tech:
        scores = [tech["score"], fund["score"], inst["score"], news_result["score"]]
        avg_score = sum(scores) / len(scores)
        portfolio_suggestion = portfolio.suggest(
            avg_score,
            tech["current_price"],
            budget,
        )

    # 產生報告
    report.generate(
        stock_id, name, tech, fund, inst, news_result,
        budget=budget,
        portfolio_suggestion=portfolio_suggestion,
    )


def main():
    if len(sys.argv) < 2:
        print("臺股決策檢查器")
        print("=" * 30)
        print("用法：python3 check.py <股票代號> [預算]")
        print()
        print("範例：")
        print("  python3 check.py 2330          # 基本分析")
        print("  python3 check.py 2330 500000   # 附資金配置建議")
        print("  python3 check.py 0050          # ETF 也可以")
        print()
        print("💡 也可以到 config.py 設定 TOTAL_BUDGET，就不用每次打")
        sys.exit(1)

    stock_id = sys.argv[1]

    # 預算：命令列參數 > config.py 設定
    budget = 0
    if len(sys.argv) > 2:
        try:
            budget = int(sys.argv[2])
        except ValueError:
            pass
    if budget == 0:
        budget = TOTAL_BUDGET

    check(stock_id, budget)


if __name__ == "__main__":
    main()
