"""
評分校準模組
回測歷史訊號，看哪個面向最準，自動調整權重
"""
import numpy as np
import tracker


def calibrate(price_fetcher, days_after=10, min_samples=10):
    """
    校準各面向評分的權重
    回傳：{"correlations": dict, "recommended_weights": dict, "sample_count": int, "status": str}
    """
    dates = tracker.list_records()
    if not dates:
        return {"status": "no_data", "message": "沒有歷史掃描記錄", "correlations": {}, "recommended_weights": {}, "sample_count": 0}

    dates = sorted(dates)
    dimensions = ["tech", "fund", "inst", "news"]
    all_scores = {dim: [] for dim in dimensions}
    all_returns = []

    for date_str in dates:
        record = tracker.load_record(date_str)
        if not record or "results" not in record:
            continue
        for r in record["results"]:
            stock_id = r.get("stock_id", "")
            if not stock_id:
                continue
            ret = _get_return(stock_id, date_str, price_fetcher, days_after)
            if ret is None:
                continue
            for dim in dimensions:
                all_scores[dim].append(r.get(dim, 5))
            all_returns.append(ret)

    if len(all_returns) < min_samples:
        return {"status": "insufficient_data", "message": f"有效樣本 {len(all_returns)} 筆，不足 {min_samples} 筆",
                "correlations": {}, "recommended_weights": {}, "sample_count": len(all_returns)}

    returns_arr = np.array(all_returns)
    correlations = {}
    for dim in dimensions:
        scores_arr = np.array(all_scores[dim])
        std_s, std_r = np.std(scores_arr), np.std(returns_arr)
        if std_s == 0 or std_r == 0:
            correlations[dim] = 0.0
        else:
            corr = np.corrcoef(scores_arr, returns_arr)[0, 1]
            correlations[dim] = round(corr if not np.isnan(corr) else 0.0, 4)

    # 相關性轉權重
    pos = {d: max(c, 0) for d, c in correlations.items()}
    total = sum(pos.values())
    if total == 0:
        weights = {d: 0.25 for d in dimensions}
    else:
        remaining = 1.0 - 0.05 * len(dimensions)
        weights = {d: round(0.05 + remaining * pos[d] / total, 2) for d in dimensions}
        # 修正四捨五入
        diff = 1.0 - sum(weights.values())
        max_d = max(weights, key=weights.get)
        weights[max_d] = round(weights[max_d] + diff, 2)

    return {"status": "ok", "correlations": correlations, "recommended_weights": weights, "sample_count": len(all_returns)}


def _get_return(stock_id, scan_date, price_fetcher, days_after):
    try:
        prices = price_fetcher(stock_id, days=days_after + 60)
        if prices is None or prices.empty:
            return None
        prices = prices.sort_values("date").reset_index(drop=True)
        prices["close"] = prices["close"].astype(float)
        after = prices[prices["date"] > scan_date]
        if len(after) < days_after:
            return None
        p0 = after.iloc[0]["close"]
        p1 = after.iloc[min(days_after - 1, len(after) - 1)]["close"]
        if p0 <= 0:
            return None
        return round((p1 / p0 - 1) * 100, 2)
    except Exception:
        return None
