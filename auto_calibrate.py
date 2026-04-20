"""
自動權重校準 — 用過去 N 天掃描記錄 + 實際 10 天報酬，跑 grid search 找最佳權重。

用法：
  python3 auto_calibrate.py                  # 跑 balanced 策略
  python3 auto_calibrate.py short            # 跑 short 策略
  python3 auto_calibrate.py balanced 90      # 用過去 90 天樣本

輸出：
  data/calibration/<strategy>_<date>.json — 最佳權重 + 相關性對比
  終端印出建議（改動幅度 > 0.05 才列為「建議調整」）
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tracker
from scoring import grid_search_weights, STRATEGIES

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "data", "calibration")


def _collect_history(lookback_days=60):
    """展平歷史掃描記錄成 (stock_id, date, tech, fund, inst, news) 清單"""
    dates = tracker.list_records()[:lookback_days]
    recs = []
    for d in dates:
        rec = tracker.load_record(d)
        if not rec:
            continue
        for r in rec.get("results", []):
            recs.append({
                "stock_id": r.get("stock_id", ""),
                "date": d,
                "tech": r.get("tech", 5),
                "fund": r.get("fund", 5),
                "inst": r.get("inst", 5),
                "news": r.get("news", 5),
            })
    return recs


def run(strategy="balanced", lookback_days=60, forward_days=10):
    import market
    records = _collect_history(lookback_days)
    if len(records) < 20:
        print(f"樣本不足：{len(records)} 筆（需 ≥20），先累積幾天資料再跑")
        return None

    print(f"資料：{len(records)} 筆 / {lookback_days} 天內 / {strategy} 策略")
    print(f"正在跑 grid search（2-3 分鐘）...")

    res = grid_search_weights(
        records, market.fetch_stock_price,
        forward_days=forward_days,
        strategy=strategy,
    )

    if "error" in res:
        print(f"錯誤：{res['error']}")
        return None

    os.makedirs(OUT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(OUT_DIR, f"{strategy}_{date_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    best = res["best_weights"]
    curr = res["current_weights"]
    imp = res["improvement"]

    print(f"\n=== 結果 ===")
    print(f"當前 {strategy}: tech={curr['tech']} fund={curr['fund']} inst={curr['inst']} news={curr['news']}")
    print(f"                 相關性 {res['current_correlation']:+.3f}")
    print(f"最佳組合: tech={best['tech']} fund={best['fund']} inst={best['inst']} news={best['news']}")
    print(f"           相關性 {res['best_correlation']:+.3f}")
    print(f"改善幅度: {imp:+.3f}")

    # 顯示是否建議換
    max_diff = max(
        abs(best["tech"] - curr["tech"]),
        abs(best["fund"] - curr["fund"]),
        abs(best["inst"] - curr["inst"]),
        abs(best["news"] - curr["news"]),
    )

    if imp > 0.05 and max_diff > 0.05:
        print(f"\n✅ 建議調整！相關性提升 {imp:+.3f}")
        print(f"   將 scoring.STRATEGIES['{strategy}']['weights'] 改為：")
        print(f"   {{'tech': {best['tech']}, 'fund': {best['fund']}, 'inst': {best['inst']}, 'news': {best['news']}}}")
    else:
        print(f"\n— 改動幅度不明顯（{max_diff:.2f}），先維持現狀")

    print(f"\n完整結果已存：{out_path}")
    return res


if __name__ == "__main__":
    strategy = sys.argv[1] if len(sys.argv) > 1 else "balanced"
    lookback = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    if strategy not in STRATEGIES:
        print(f"未知策略：{strategy}，可選：{list(STRATEGIES.keys())}")
        sys.exit(1)

    run(strategy=strategy, lookback_days=lookback)
