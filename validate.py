"""
訊號驗證模組 — 統計歷史掃描後 N 天的實際報酬，推算勝率與平均報酬。

設計：
- `validate_scan(date)` 針對單一掃描日，計算 N 天後報酬，存進 data/validation/。
- `get_accuracy_summary()` 聚合最近 30 天驗證結果，產出一行摘要（給 notify 推播尾部用）。
- 分層報告：全體綠燈 / 短線精選（RS≥50 且 avg≥7.5）/ 黃燈。
"""
import os
import json
from datetime import datetime

import tracker

BASE = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = os.path.join(BASE, "data", "validation")


def _price_fetcher(stock_id, days=40):
    import market
    return market.fetch_stock_price(stock_id, days=days)


def validate_scan(date_str, days_after=10):
    """
    回頭看某日掃描後 N 天的實際報酬，存檔。

    回傳 dict 摘要；如資料不足回傳 None。
    """
    record = tracker.load_record(date_str)
    if not record:
        return None

    os.makedirs(VALIDATION_DIR, exist_ok=True)
    out_path = os.path.join(VALIDATION_DIR, f"{date_str}.json")

    rows = []
    for r in record.get("results", []):
        sid = r.get("stock_id", "")
        if not sid:
            continue
        try:
            prices = _price_fetcher(sid, days=days_after + 30)
            if prices is None or prices.empty:
                continue
            prices = prices.sort_values("date").reset_index(drop=True)
            prices["close"] = prices["close"].astype(float)
            after = prices[prices["date"] > date_str]
            if len(after) < 1:
                continue

            p0 = after.iloc[0]["close"]
            idx = min(days_after - 1, len(after) - 1)
            p1 = after.iloc[idx]["close"]
            ret = round((p1 / p0 - 1) * 100, 2)

            rows.append({
                "stock_id": sid,
                "name": r.get("name", ""),
                "avg": r.get("avg", 0),
                "overall": r.get("overall", ""),
                "forward_return": ret,
                "days_realized": idx + 1,
            })
        except Exception:
            continue

    if not rows:
        return None

    greens = [x for x in rows if x["avg"] >= 7]
    precision_greens = [x for x in rows if x["avg"] >= 7.5]
    yellows = [x for x in rows if 4 <= x["avg"] < 7]
    reds = [x for x in rows if x["avg"] < 4]

    def _stats(bucket):
        if not bucket:
            return None
        wins = sum(1 for x in bucket if x["forward_return"] > 0)
        avg_ret = sum(x["forward_return"] for x in bucket) / len(bucket)
        return {
            "n": len(bucket),
            "win_rate": round(wins / len(bucket) * 100, 1),
            "avg_return": round(avg_ret, 2),
        }

    summary = {
        "date": date_str,
        "days_after": days_after,
        "generated_at": datetime.now().isoformat(),
        "total": len(rows),
        "green_stats": _stats(greens),
        "precision_green_stats": _stats(precision_greens),
        "yellow_stats": _stats(yellows),
        "red_stats": _stats(reds),
        "green_accuracy": _stats(greens)["win_rate"] if _stats(greens) else None,
        "results": rows,
    }

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return summary


def load_validation(date_str):
    path = os.path.join(VALIDATION_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_validations():
    if not os.path.exists(VALIDATION_DIR):
        return []
    files = sorted(
        [f for f in os.listdir(VALIDATION_DIR) if f.endswith(".json")],
        reverse=True,
    )
    return [f.replace(".json", "") for f in files]


def get_accuracy_summary(lookback=30):
    """
    聚合最近 lookback 天驗證結果，回傳一行摘要。

    摘要格式：
      過去 N 筆 10 日驗證｜綠燈勝率 62% 均 +4.2%｜精選(≥7.5) 勝率 71% 均 +6.8%
    """
    dates = list_validations()
    if not dates:
        return ""

    dates = dates[:lookback]

    agg = {
        "green": [],
        "precision_green": [],
        "yellow": [],
    }

    for d in dates:
        v = load_validation(d)
        if not v:
            continue
        gs = v.get("green_stats")
        ps = v.get("precision_green_stats")
        ys = v.get("yellow_stats")
        if gs:
            agg["green"].append(gs)
        if ps:
            agg["precision_green"].append(ps)
        if ys:
            agg["yellow"].append(ys)

    def _combine(stats_list):
        if not stats_list:
            return None
        total_n = sum(s["n"] for s in stats_list)
        if total_n == 0:
            return None
        weighted_win = sum(s["win_rate"] * s["n"] for s in stats_list) / total_n
        weighted_ret = sum(s["avg_return"] * s["n"] for s in stats_list) / total_n
        return {
            "n": total_n,
            "win_rate": round(weighted_win, 1),
            "avg_return": round(weighted_ret, 2),
        }

    g = _combine(agg["green"])
    p = _combine(agg["precision_green"])
    y = _combine(agg["yellow"])

    parts = []
    if g:
        parts.append(f"綠燈勝率 {g['win_rate']}% 均 {g['avg_return']:+.1f}%")
    if p and p["n"] >= 5:
        parts.append(f"精選(≥7.5) 勝率 {p['win_rate']}% 均 {p['avg_return']:+.1f}%")
    if y and y["n"] >= 5:
        parts.append(f"黃燈勝率 {y['win_rate']}% 均 {y['avg_return']:+.1f}%")

    if not parts:
        return ""

    n_scans = len(dates)
    return f"{n_scans} 日驗證｜" + "｜".join(parts)


if __name__ == "__main__":
    # CLI: python3 validate.py [date]
    import sys
    if len(sys.argv) > 1:
        d = sys.argv[1]
        r = validate_scan(d)
        if r:
            print(json.dumps({k: v for k, v in r.items() if k != "results"},
                             ensure_ascii=False, indent=2))
    else:
        print(get_accuracy_summary())
