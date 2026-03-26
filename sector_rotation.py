"""
產業輪動偵測模組
分析最近幾週掃描記錄，找出正在升溫或降溫的產業
"""
import tracker
from watchlist import WATCHLIST


def _build_sector_map():
    sector_map = {}
    for sector, stocks in WATCHLIST.items():
        for stock_id in stocks:
            sector_map[stock_id] = sector
    return sector_map


def detect_rotation(recent_weeks=4):
    """
    偵測產業輪動
    回傳：按動能排序的產業列表
    """
    dates = tracker.list_records()
    if not dates:
        return []

    dates_sorted = sorted(dates)
    max_days = recent_weeks * 5
    recent = dates_sorted[-max_days:] if len(dates_sorted) > max_days else dates_sorted

    if len(recent) < 2:
        return []

    mid = len(recent) // 2
    prev_dates = recent[:mid]
    curr_dates = recent[mid:]

    sector_map = _build_sector_map()
    prev_scores = _collect(prev_dates, sector_map)
    curr_scores = _collect(curr_dates, sector_map)

    all_sectors = set(prev_scores.keys()) | set(curr_scores.keys())
    results = []

    for sector in all_sectors:
        curr = curr_scores.get(sector, [])
        prev = prev_scores.get(sector, [])
        if not curr:
            continue

        curr_avg = round(sum(curr) / len(curr), 1)
        if prev:
            prev_avg = round(sum(prev) / len(prev), 1)
            change = round(curr_avg - prev_avg, 1)
        else:
            prev_avg = None
            change = 0.0

        if change >= 1.0:
            label = "升溫中"
        elif change >= 0.3:
            label = "微幅升溫"
        elif change <= -1.0:
            label = "降溫中"
        elif change <= -0.3:
            label = "微幅降溫"
        else:
            label = "持平"

        results.append({
            "sector": sector,
            "current_avg": curr_avg,
            "previous_avg": prev_avg,
            "change": change,
            "label": label,
            "stock_count": len([s for s, sec in sector_map.items() if sec == sector]),
        })

    results.sort(key=lambda x: x["change"], reverse=True)
    for i, r in enumerate(results):
        r["momentum_rank"] = i + 1

    return results


def _collect(dates, sector_map):
    scores = {}
    for date_str in dates:
        record = tracker.load_record(date_str)
        if not record or "results" not in record:
            continue
        for r in record["results"]:
            sector = r.get("sector", "") or sector_map.get(r.get("stock_id", ""), "")
            if not sector:
                continue
            if sector not in scores:
                scores[sector] = []
            scores[sector].append(r.get("avg", 0))
    return scores


def get_hot_sectors(top_n=5):
    return [r for r in detect_rotation() if r["change"] > 0][:top_n]


def get_cold_sectors(top_n=5):
    cold = [r for r in detect_rotation() if r["change"] < 0]
    cold.sort(key=lambda x: x["change"])
    return cold[:top_n]
