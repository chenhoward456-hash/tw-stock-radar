"""
評分校準模組
回測歷史訊號，看哪個面向最準，自動調整權重

第三輪優化：
1. 多時間窗口（5/10/20/30 天報酬同時測試）
2. Spearman 等級相關性（抓非線性關係）
3. 時間衰減（近期資料權重更高）
4. 分數分段準確率（不只看整體相關性）
"""
import numpy as np
import tracker
from scipy import stats as scipy_stats


def calibrate(price_fetcher, days_after=10, min_samples=10):
    """
    校準各面向評分的權重
    回傳：{"correlations": dict, "recommended_weights": dict, "sample_count": int, "status": str,
           "multi_window": dict, "band_accuracy": dict}
    """
    dates = tracker.list_records()
    if not dates:
        return {"status": "no_data", "message": "沒有歷史掃描記錄", "correlations": {}, "recommended_weights": {}, "sample_count": 0}

    dates = sorted(dates)
    dimensions = ["tech", "fund", "inst", "news"]

    # 收集所有分數和對應的多時間窗口報酬
    windows = [5, 10, 20, 30]
    samples = []  # [{dim_scores: {}, returns: {window: float}}]

    for date_str in dates:
        record = tracker.load_record(date_str)
        if not record or "results" not in record:
            continue
        for r in record["results"]:
            stock_id = r.get("stock_id", "")
            if not stock_id:
                continue

            # 多時間窗口報酬
            rets = {}
            for w in windows:
                ret = _get_return(stock_id, date_str, price_fetcher, w)
                if ret is not None:
                    rets[w] = ret

            if not rets:
                continue

            sample = {"scores": {}, "returns": rets, "date": date_str, "avg": r.get("avg", 5)}
            for dim in dimensions:
                sample["scores"][dim] = r.get(dim, 5)
            samples.append(sample)

    if len(samples) < min_samples:
        return {"status": "insufficient_data", "message": f"有效樣本 {len(samples)} 筆，不足 {min_samples} 筆",
                "correlations": {}, "recommended_weights": {}, "sample_count": len(samples)}

    # === 多時間窗口相關性分析 ===
    multi_window = {}
    best_window = days_after
    best_total_corr = -1

    for w in windows:
        w_samples = [s for s in samples if w in s["returns"]]
        if len(w_samples) < min_samples:
            continue

        returns_arr = np.array([s["returns"][w] for s in w_samples])
        w_corrs = {}

        for dim in dimensions:
            scores_arr = np.array([s["scores"][dim] for s in w_samples])
            # Pearson
            pearson = _safe_corr(scores_arr, returns_arr)
            # Spearman（等級相關，捕捉非線性）
            if len(scores_arr) >= 5:
                try:
                    spearman, _ = scipy_stats.spearmanr(scores_arr, returns_arr)
                    spearman = round(spearman if not np.isnan(spearman) else 0, 4)
                except Exception:
                    spearman = pearson
            else:
                spearman = pearson

            # 取兩者平均作為綜合相關性
            w_corrs[dim] = {
                "pearson": pearson,
                "spearman": spearman,
                "combined": round((pearson + spearman) / 2, 4),
            }

        total = sum(c["combined"] for c in w_corrs.values())
        multi_window[w] = {"correlations": w_corrs, "sample_count": len(w_samples), "total_corr": round(total, 4)}

        if total > best_total_corr:
            best_total_corr = total
            best_window = w

    # === 用最佳窗口計算主要權重 ===
    if best_window in multi_window:
        best_corrs = {dim: multi_window[best_window]["correlations"][dim]["combined"]
                      for dim in dimensions}
    else:
        # Fallback 到原始方法
        target_samples = [s for s in samples if days_after in s["returns"]]
        returns_arr = np.array([s["returns"][days_after] for s in target_samples])
        best_corrs = {}
        for dim in dimensions:
            scores_arr = np.array([s["scores"][dim] for s in target_samples])
            best_corrs[dim] = _safe_corr(scores_arr, returns_arr)

    # === 時間衰減加權 ===
    # 近期樣本給更高權重計算相關性
    decay_corrs = _time_decay_correlations(samples, dimensions, best_window, half_life=30)

    # 綜合：50% 全期相關性 + 50% 近期衰減相關性
    final_corrs = {}
    for dim in dimensions:
        base = best_corrs.get(dim, 0)
        decay = decay_corrs.get(dim, 0)
        final_corrs[dim] = round(base * 0.5 + decay * 0.5, 4)

    # 相關性轉權重
    weights = _corr_to_weights(final_corrs, dimensions)

    # === 分數分段準確率 ===
    band_accuracy = _calc_band_accuracy(samples, best_window)

    return {
        "status": "ok",
        "correlations": final_corrs,
        "recommended_weights": weights,
        "sample_count": len(samples),
        "best_window": best_window,
        "multi_window": multi_window,
        "band_accuracy": band_accuracy,
        "decay_correlations": decay_corrs,
    }


def _safe_corr(x, y):
    """安全計算 Pearson 相關係數"""
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    corr = np.corrcoef(x, y)[0, 1]
    return round(corr if not np.isnan(corr) else 0.0, 4)


def _time_decay_correlations(samples, dimensions, window, half_life=30):
    """用指數衰減加權的相關性（近期資料更重要）"""
    target = [s for s in samples if window in s["returns"]]
    if len(target) < 5:
        return {dim: 0 for dim in dimensions}

    # 按日期排序，最新的在後面
    target.sort(key=lambda s: s["date"])
    n = len(target)

    # 指數衰減權重：最新 = 1.0，half_life 天前 = 0.5
    weights = np.array([np.exp(-0.693 * (n - 1 - i) / max(half_life, 1)) for i in range(n)])
    weights /= weights.sum()

    returns_arr = np.array([s["returns"][window] for s in target])

    result = {}
    for dim in dimensions:
        scores_arr = np.array([s["scores"][dim] for s in target])
        # 加權相關性
        mean_s = np.average(scores_arr, weights=weights)
        mean_r = np.average(returns_arr, weights=weights)
        cov = np.average((scores_arr - mean_s) * (returns_arr - mean_r), weights=weights)
        std_s = np.sqrt(np.average((scores_arr - mean_s) ** 2, weights=weights))
        std_r = np.sqrt(np.average((returns_arr - mean_r) ** 2, weights=weights))
        if std_s > 0 and std_r > 0:
            result[dim] = round(cov / (std_s * std_r), 4)
        else:
            result[dim] = 0.0

    return result


def _corr_to_weights(correlations, dimensions):
    """相關性轉權重（正相關越高 → 權重越大）"""
    pos = {d: max(c, 0) for d, c in correlations.items()}
    total = sum(pos.values())
    if total == 0:
        weights = {d: round(1.0 / len(dimensions), 2) for d in dimensions}
    else:
        # 最低保底 5%
        remaining = 1.0 - 0.05 * len(dimensions)
        weights = {d: round(0.05 + remaining * pos[d] / total, 2) for d in dimensions}
        # 修正四捨五入
        diff = 1.0 - sum(weights.values())
        max_d = max(weights, key=weights.get)
        weights[max_d] = round(weights[max_d] + diff, 2)
    return weights


def _calc_band_accuracy(samples, window):
    """
    分數分段準確率：
    高分段（≥7）→ 後續正報酬比例
    中分段（4-7）→ 後續正報酬比例
    低分段（<4）→ 後續負報酬比例
    """
    bands = {"high": [], "mid": [], "low": []}

    for s in samples:
        if window not in s["returns"]:
            continue
        avg = s["avg"]
        ret = s["returns"][window]

        if avg >= 7:
            bands["high"].append(ret)
        elif avg >= 4:
            bands["mid"].append(ret)
        else:
            bands["low"].append(ret)

    result = {}
    for band, rets in bands.items():
        if not rets:
            result[band] = {"count": 0, "accuracy": None, "avg_return": None}
            continue

        if band == "low":
            # 低分段：跌的比例越高越好
            correct = sum(1 for r in rets if r < 0)
        else:
            # 高/中分段：漲的比例越高越好
            correct = sum(1 for r in rets if r > 0)

        result[band] = {
            "count": len(rets),
            "accuracy": round(correct / len(rets) * 100, 1),
            "avg_return": round(np.mean(rets), 2),
        }

    return result


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
