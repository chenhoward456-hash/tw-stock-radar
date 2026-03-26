"""
連續訊號追蹤模組
讀取歷史掃描記錄，找出連續多天出現綠燈或紅燈的股票
"""
import tracker


def _classify(score):
    if score >= 7:
        return "green"
    elif score < 4:
        return "red"
    return "neutral"


def detect_streaks(min_streak=2):
    """
    偵測所有股票的連續訊號
    回傳：{stock_id: {"streak": N, "type": "green/red", "avg_score": float, "name": str, "sector": str}}
    """
    dates = tracker.list_records()
    if not dates:
        return {}

    dates = sorted(dates)

    stock_history = {}
    for date_str in dates:
        record = tracker.load_record(date_str)
        if not record or "results" not in record:
            continue
        for r in record["results"]:
            stock_id = r.get("stock_id", "")
            if stock_id not in stock_history:
                stock_history[stock_id] = []
            stock_history[stock_id].append({
                "date": date_str,
                "score": r.get("avg", 0),
                "name": r.get("name", ""),
                "sector": r.get("sector", ""),
            })

    result = {}
    for stock_id, history in stock_history.items():
        if not history:
            continue
        history = sorted(history, key=lambda x: x["date"])
        latest = history[-1]
        latest_type = _classify(latest["score"])
        if latest_type == "neutral":
            continue

        streak = 0
        scores = []
        for entry in reversed(history):
            if _classify(entry["score"]) == latest_type:
                streak += 1
                scores.append(entry["score"])
            else:
                break

        if streak >= min_streak:
            result[stock_id] = {
                "streak": streak,
                "type": latest_type,
                "avg_score": round(sum(scores) / len(scores), 1),
                "name": latest["name"],
                "sector": latest["sector"],
            }

    return result
