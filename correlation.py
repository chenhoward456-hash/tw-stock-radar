"""
關聯性分析模組
避免持股全部同漲同跌
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


def check_diversification(stock_ids, token=None):
    """
    檢查持倉的分散度
    回傳：{"score": 1-10, "details": list, "matrix": DataFrame}
    """
    if len(stock_ids) < 2:
        return {
            "score": 5,
            "details": ["— 只有一檔，無法分析關聯性"],
            "matrix": pd.DataFrame(),
            "high_pairs": [],
        }

    corr = correlation_matrix(stock_ids, token=token)
    if corr.empty:
        return {
            "score": 5,
            "details": ["⚠ 無法取得足夠的價格資料"],
            "matrix": pd.DataFrame(),
            "high_pairs": [],
        }

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
                    high_pairs.append((a, names.get(a, a), b, names.get(b, b), c))

    # 平均相關性
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    avg_corr = upper.stack().mean()

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

    if high_pairs:
        details.append("")
        details.append("⚠ 高度相關的配對（>0.7）：")
        for a, na, b, nb, c in high_pairs:
            details.append(f"  {a} {na} ↔ {b} {nb}：{c:.2f}")
        details.append("")
        details.append("→ 這些股票容易同漲同跌，考慮分散到不同產業")
    else:
        details.append("✓ 沒有高度相關的配對，分散度OK")

    # 替換 index/columns 為名稱
    display_corr = corr.copy()
    display_corr.index = [f"{sid} {names.get(sid, '')}" for sid in display_corr.index]
    display_corr.columns = [f"{sid} {names.get(sid, '')}" for sid in display_corr.columns]

    return {
        "score": score,
        "details": details,
        "matrix": display_corr,
        "high_pairs": high_pairs,
    }
