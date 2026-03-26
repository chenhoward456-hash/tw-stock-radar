"""
訊號追蹤記錄模組
每次掃描自動存檔，之後可以回頭看系統準不準
"""
import os
import json
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "signals")


def save_scan(results):
    """儲存掃描結果"""
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(DATA_DIR, f"{today}.json")

    records = []
    for r in results:
        records.append({
            "stock_id": r.get("stock_id", ""),
            "name": r.get("name", ""),
            "sector": r.get("sector", ""),
            "tech": r.get("tech", 0),
            "fund": r.get("fund", 0),
            "inst": r.get("inst", 0),
            "news": r.get("news", 5),
            "avg": r.get("avg", 0),
            "overall": r.get("overall", ""),
        })

    data = {
        "date": today,
        "timestamp": datetime.now().isoformat(),
        "count": len(records),
        "results": records,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filepath


def list_records():
    """列出所有歷史記錄"""
    if not os.path.exists(DATA_DIR):
        return []
    files = sorted(
        [f for f in os.listdir(DATA_DIR) if f.endswith(".json")],
        reverse=True,
    )
    return [f.replace(".json", "") for f in files]


def load_record(date_str):
    """載入某天的記錄"""
    filepath = os.path.join(DATA_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def review_accuracy(date_str, price_fetcher, days_after=10):
    """
    回顧某天的訊號準確度
    比較「系統給分」vs「之後 N 天的實際漲跌」
    """
    record = load_record(date_str)
    if not record:
        return None

    results = []
    for r in record["results"]:
        stock_id = r["stock_id"]
        signal_score = r["avg"]
        signal = r["overall"]

        # 抓那天之後的價格
        try:
            prices = price_fetcher(stock_id, days=days_after + 30)
            if prices.empty:
                continue

            prices = prices.sort_values("date").reset_index(drop=True)
            prices["close"] = prices["close"].astype(float)

            # 找到信號日之後的資料
            after = prices[prices["date"] > date_str]
            if len(after) < days_after:
                continue

            price_at_signal = after.iloc[0]["close"]
            price_after = after.iloc[min(days_after - 1, len(after) - 1)]["close"]
            actual_return = round((price_after / price_at_signal - 1) * 100, 1)

            # 系統判斷 vs 實際
            system_said = "buy" if signal_score >= 6.5 else ("hold" if signal_score >= 4 else "avoid")
            actual_good = actual_return > 0

            correct = (system_said == "buy" and actual_good) or \
                      (system_said == "avoid" and not actual_good) or \
                      system_said == "hold"

            results.append({
                "stock_id": stock_id,
                "name": r["name"],
                "score": signal_score,
                "signal": signal,
                "system_said": system_said,
                "actual_return": actual_return,
                "correct": correct,
            })
        except Exception:
            continue

    if not results:
        return None

    correct_count = sum(1 for r in results if r["correct"])
    total = len(results)

    return {
        "date": date_str,
        "days_after": days_after,
        "results": results,
        "accuracy": round(correct_count / total * 100, 1) if total > 0 else 0,
        "correct": correct_count,
        "total": total,
    }
