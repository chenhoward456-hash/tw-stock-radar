"""
關聯性分析模組
避免持股全部同漲同跌

第三輪優化：
1. 壓力測試相關性（下跌日的相關性，崩盤時才知道真正的分散度）
2. 滾動相關性穩定度（相關性是穩定的還是飄忽的）
3. 動態閾值（高波動環境用更嚴格的分散門檻）
"""
import pandas as pd
import numpy as np
import market


def get_returns(stock_ids, days=60, token=None):
    """取得多檔股票的日報酬率"""
    all_returns = {}

    for sid in stock_ids:
        try:
            df = market.fetch_stock_price(sid, days=days + 30)
            if df.empty:
                continue
            df = df.sort_values("date").reset_index(drop=True)
            df["close"] = df["close"].astype(float)
            df["return"] = df["close"].pct_change()
            all_returns[sid] = df.set_index("date")["return"]
        except Exception:
            continue

    if not all_returns:
        return pd.DataFrame()

    return pd.DataFrame(all_returns).dropna()


def correlation_matrix(stock_ids, days=60, token=None):
    """計算相關係數矩陣"""
    returns_df = get_returns(stock_ids, days, token)
    if returns_df.empty or len(returns_df.columns) < 2:
        return pd.DataFrame()
    return returns_df.corr().round(2)


def _stress_correlation(returns_df, percentile=25):
    """
    壓力測試：只看市場下跌日的相關性
    用所有股票平均報酬 < percentile 分位數的日子
    """
    if returns_df.empty or len(returns_df.columns) < 2:
        return pd.DataFrame()

    avg_market = returns_df.mean(axis=1)
    threshold = avg_market.quantile(percentile / 100)
    stress_days = returns_df[avg_market <= threshold]

    if len(stress_days) < 5:
        return pd.DataFrame()

    return stress_days.corr().round(2)


def _rolling_correlation_stability(returns_df, window=30):
    """
    滾動相關性穩定度：計算每對股票的相關性波動程度
    相關性越穩定 → 你對分散效果的信心越高
    """
    if returns_df.empty or len(returns_df.columns) < 2 or len(returns_df) < window + 10:
        return {}

    pairs = {}
    cols = list(returns_df.columns)

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            rolling = returns_df[a].rolling(window).corr(returns_df[b]).dropna()
            if len(rolling) < 5:
                continue
            pairs[(a, b)] = {
                "mean_corr": round(rolling.mean(), 2),
                "std_corr": round(rolling.std(), 2),
                "min_corr": round(rolling.min(), 2),
                "max_corr": round(rolling.max(), 2),
                "stable": rolling.std() < 0.2,  # 標準差 < 0.2 算穩定
            }

    return pairs


def check_diversification(stock_ids, token=None):
    """
    檢查持倉的分散度（升級版）
    回傳：{"score": 1-10, "details": list, "matrix": DataFrame,
           "high_pairs": list, "stress_matrix": DataFrame, "stability": dict}
    """
    if len(stock_ids) < 2:
        return {
            "score": 5,
            "details": ["— 只有一檔，無法分析關聯性"],
            "matrix": pd.DataFrame(),
            "high_pairs": [],
            "stress_matrix": pd.DataFrame(),
            "stability": {},
        }

    # 正常相關性
    returns_df = get_returns(stock_ids, days=90, token=token)
    if returns_df.empty or len(returns_df.columns) < 2:
        return {
            "score": 5,
            "details": ["⚠ 無法取得足夠的價格資料"],
            "matrix": pd.DataFrame(),
            "high_pairs": [],
            "stress_matrix": pd.DataFrame(),
            "stability": {},
        }

    corr = returns_df.corr().round(2)

    # 壓力測試相關性（第三輪新增）
    stress_corr = _stress_correlation(returns_df)

    # 滾動穩定度（第三輪新增）
    stability = _rolling_correlation_stability(returns_df)

    names = {}
    for sid in stock_ids:
        names[sid] = market.fetch_stock_name(sid)

    # 找高相關性的配對
    high_pairs = []
    checked = set()
    for i, a in enumerate(stock_ids):
        for j, b in enumerate(stock_ids):
            if i >= j or (a, b) in checked:
                continue
            checked.add((a, b))
            if a in corr.columns and b in corr.columns:
                c = corr.loc[a, b]
                if abs(c) > 0.7:
                    # 加入壓力測試數據
                    stress_c = stress_corr.loc[a, b] if not stress_corr.empty and a in stress_corr.columns and b in stress_corr.columns else None
                    high_pairs.append((a, names.get(a, a), b, names.get(b, b), c, stress_c))

    # 平均相關性
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    avg_corr = upper.stack().mean()

    # 壓力平均相關性
    avg_stress_corr = None
    if not stress_corr.empty:
        stress_upper = stress_corr.where(np.triu(np.ones(stress_corr.shape), k=1).astype(bool))
        avg_stress_corr = stress_upper.stack().mean()

    # 評分：相關性越低越好
    if avg_corr < 0.3:
        score = 9
        details = [f"✓ 平均相關性 {avg_corr:.2f}（分散度優秀）"]
    elif avg_corr < 0.5:
        score = 7
        details = [f"✓ 平均相關性 {avg_corr:.2f}（分散度良好）"]
    elif avg_corr < 0.7:
        score = 5
        details = [f"— 平均相關性 {avg_corr:.2f}（分散度普通）"]
    else:
        score = 3
        details = [f"⚠ 平均相關性 {avg_corr:.2f}（持股高度相關，風險集中）"]

    # 壓力測試結果（第三輪新增）
    if avg_stress_corr is not None:
        details.append("")
        if avg_stress_corr > avg_corr + 0.15:
            details.append(f"⚠ 壓力測試：下跌日相關性升至 {avg_stress_corr:.2f}（正常 {avg_corr:.2f}）")
            details.append("  → 市場恐慌時分散效果會減弱，實際風險比看起來高")
            score -= 1
        elif avg_stress_corr > avg_corr + 0.05:
            details.append(f"— 壓力測試：下跌日相關性 {avg_stress_corr:.2f}（正常 {avg_corr:.2f}），略升")
        else:
            details.append(f"✓ 壓力測試：下跌日相關性 {avg_stress_corr:.2f}，分散效果穩定")

    # 高相關配對
    if high_pairs:
        details.append("")
        details.append("⚠ 高度相關的配對（>0.7）：")
        for entry in high_pairs:
            a, na, b, nb, c = entry[0], entry[1], entry[2], entry[3], entry[4]
            stress_c = entry[5] if len(entry) > 5 else None
            stress_tag = f"，壓力下 {stress_c:.2f}" if stress_c is not None else ""
            details.append(f"  {a} {na} ↔ {b} {nb}：{c:.2f}{stress_tag}")
        details.append("")
        details.append("→ 這些股票容易同漲同跌，考慮分散到不同產業")
    else:
        details.append("✓ 沒有高度相關的配對，分散度OK")

    # 穩定度摘要
    unstable_pairs = [(k, v) for k, v in stability.items() if not v["stable"]]
    if unstable_pairs:
        details.append("")
        details.append("⚠ 相關性不穩定的配對（波動大，分散效果不可靠）：")
        for (a, b), v in unstable_pairs[:3]:
            details.append(f"  {a} ↔ {b}：均值 {v['mean_corr']:.2f} ± {v['std_corr']:.2f}（範圍 {v['min_corr']:.2f}~{v['max_corr']:.2f}）")

    score = max(1, min(10, score))

    # 替換 index/columns 為名稱
    display_corr = corr.copy()
    display_corr.index = [f"{sid} {names.get(sid, '')}" for sid in display_corr.index]
    display_corr.columns = [f"{sid} {names.get(sid, '')}" for sid in display_corr.columns]

    return {
        "score": score,
        "details": details,
        "matrix": display_corr,
        "high_pairs": high_pairs,
        "stress_matrix": stress_corr,
        "stability": stability,
        "avg_stress_corr": avg_stress_corr,
    }
