"""
連續訊號追蹤模組
讀取歷史掃描記錄，找出連續多天出現綠燈或紅燈的股票

第三輪優化：
1. 分數加權（連續綠 [9,9,9] 比 [7,7,7] 更有意義）
2. 動量方向（分數是在上升、持平、還是衰退中）
3. 均值回歸情境偵測（長期紅燈 + 分數開始回升 = 可能的反轉買點）
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
    偵測所有股票的連續訊號（升級版）
    回傳：{stock_id: {"streak": N, "type": "green/red", "avg_score": float,
           "name": str, "sector": str, "momentum": str, "conviction": str}}
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
            # 檢查是否從紅燈回升（均值回歸偵測）
            reversion = _detect_reversion(history)
            if reversion:
                result[stock_id] = reversion
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
            avg = round(sum(scores) / len(scores), 1)

            # 動量方向：最近幾天的分數是上升還是下降
            if len(scores) >= 3:
                recent_half = scores[:len(scores)//2]
                older_half = scores[len(scores)//2:]
                r_avg = sum(recent_half) / len(recent_half)
                o_avg = sum(older_half) / len(older_half)
                if r_avg > o_avg + 0.3:
                    momentum = "加速"  # 分數越來越高
                elif r_avg < o_avg - 0.3:
                    momentum = "減速"  # 分數在衰退
                else:
                    momentum = "穩定"
            else:
                momentum = "穩定"

            # 信心度（基於平均分數和連續天數）
            if latest_type == "green":
                if avg >= 8 and streak >= 3:
                    conviction = "高"
                elif avg >= 7:
                    conviction = "中"
                else:
                    conviction = "低"
            else:
                if avg <= 2.5 and streak >= 3:
                    conviction = "高"
                elif avg <= 3.5:
                    conviction = "中"
                else:
                    conviction = "低"

            result[stock_id] = {
                "streak": streak,
                "type": latest_type,
                "avg_score": avg,
                "name": latest["name"],
                "sector": latest["sector"],
                "momentum": momentum,
                "conviction": conviction,
            }

    return result


def _detect_reversion(history):
    """
    偵測均值回歸（從紅燈開始回升到中性）
    條件：之前至少 2 天紅燈，最新跳回中性且分數比紅燈期間高
    """
    if len(history) < 3:
        return None

    latest = history[-1]
    if _classify(latest["score"]) != "neutral":
        return None

    # 往前看有沒有連續紅燈
    red_streak = 0
    red_scores = []
    for entry in reversed(history[:-1]):
        if _classify(entry["score"]) == "red":
            red_streak += 1
            red_scores.append(entry["score"])
        else:
            break

    if red_streak < 2:
        return None

    red_avg = sum(red_scores) / len(red_scores)

    # 確認是回升（最新分數 > 紅燈平均）
    if latest["score"] > red_avg + 0.5:
        return {
            "streak": red_streak,
            "type": "reversion",
            "avg_score": round(latest["score"], 1),
            "name": latest["name"],
            "sector": latest["sector"],
            "momentum": "回升",
            "conviction": "觀察中",
            "prev_red_avg": round(red_avg, 1),
        }

    return None
