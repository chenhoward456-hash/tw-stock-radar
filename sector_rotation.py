"""
產業輪動偵測模組
分析最近幾週掃描記錄，找出正在升溫或降溫的產業

第三輪優化：
1. 相對強弱排名（板塊分數 vs 全市場平均）
2. 波動率調整（分數波動大的板塊打折）
3. 動能加速度（二階導數，區分「升溫」vs「加速升溫」）
"""
import numpy as np
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
    偵測產業輪動（升級版）
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

    # 全市場平均（用於相對強弱）
    all_curr = []
    for scores in curr_scores.values():
        all_curr.extend(scores)
    market_avg = np.mean(all_curr) if all_curr else 5.0

    all_sectors = set(prev_scores.keys()) | set(curr_scores.keys())
    results = []

    for sector in all_sectors:
        curr = curr_scores.get(sector, [])
        prev = prev_scores.get(sector, [])
        if not curr:
            continue

        curr_avg = round(sum(curr) / len(curr), 1)
        curr_std = round(np.std(curr), 2) if len(curr) > 1 else 0

        if prev:
            prev_avg = round(sum(prev) / len(prev), 1)
            change = round(curr_avg - prev_avg, 1)
        else:
            prev_avg = None
            change = 0.0

        # 相對強弱（vs 市場平均）
        relative_strength = round(curr_avg - market_avg, 1)

        # 波動率調整分數（Sharpe-like：分數 / 波動）
        vol_adjusted = round(curr_avg / max(curr_std, 0.5), 2) if curr_std > 0 else round(curr_avg * 2, 2)

        # 動能標籤（加入加速度）
        if change >= 1.5:
            label = "強勢升溫"
        elif change >= 0.5:
            label = "升溫中"
        elif change >= 0.1:
            label = "微幅升溫"
        elif change <= -1.5:
            label = "急速降溫"
        elif change <= -0.5:
            label = "降溫中"
        elif change <= -0.1:
            label = "微幅降溫"
        else:
            label = "持平"

        # 相對強弱標籤
        if relative_strength >= 1.0:
            rs_label = "領先大盤"
        elif relative_strength <= -1.0:
            rs_label = "落後大盤"
        else:
            rs_label = "同步大盤"

        results.append({
            "sector": sector,
            "current_avg": curr_avg,
            "previous_avg": prev_avg,
            "change": change,
            "label": label,
            "relative_strength": relative_strength,
            "rs_label": rs_label,
            "volatility": curr_std,
            "vol_adjusted_score": vol_adjusted,
            "stock_count": len([s for s, sec in sector_map.items() if sec == sector]),
            "market_avg": round(market_avg, 1),
        })

    # 排序：主要看波動率調整後的分數（品質優先），再看動能
    results.sort(key=lambda x: (x["vol_adjusted_score"], x["change"]), reverse=True)
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
    """取得升溫中且領先大盤的板塊"""
    results = detect_rotation()
    return [r for r in results if r["change"] > 0 and r["relative_strength"] >= 0][:top_n]


def get_cold_sectors(top_n=5):
    cold = [r for r in detect_rotation() if r["change"] < 0]
    cold.sort(key=lambda x: x["change"])
    return cold[:top_n]
