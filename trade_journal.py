"""
交易日誌模組（R5 新增）

功能：
1. SQLite 記錄每筆進出場（日期、標的、進場價、出場價、理由/評分、實際報酬）
2. 月度績效報告（總報酬、勝率、平均盈虧比、最大回撤、Alpha）
3. 統計視覺化用的 DataFrame 輸出
"""
import os
import sqlite3
from datetime import datetime, date
from contextlib import contextmanager

# ── 資料庫路徑 ───────────────────────────────────────────────────────────────
_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_DB_PATH = os.path.join(_DB_DIR, "trade_journal.db")


def _ensure_db():
    """建立資料庫和資料表（如果不存在）"""
    os.makedirs(_DB_DIR, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id      TEXT    NOT NULL,
            name          TEXT    DEFAULT '',
            strategy      TEXT    DEFAULT 'balanced',
            entry_date    TEXT    NOT NULL,
            entry_price   REAL    NOT NULL,
            shares        INTEGER NOT NULL,
            entry_score   REAL    DEFAULT 0,
            entry_reason  TEXT    DEFAULT '',
            exit_date     TEXT    DEFAULT NULL,
            exit_price    REAL    DEFAULT NULL,
            exit_reason   TEXT    DEFAULT '',
            pnl           REAL    DEFAULT NULL,
            pnl_pct       REAL    DEFAULT NULL,
            is_open       INTEGER DEFAULT 1,
            created_at    TEXT    DEFAULT (datetime('now', 'localtime'))
        )
        """)
        conn.commit()


@contextmanager
def _db():
    """資料庫連線 context manager"""
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── 新增 / 更新 ──────────────────────────────────────────────────────────────

def add_entry(stock_id: str, entry_date: str, entry_price: float, shares: int,
              name: str = "", strategy: str = "balanced",
              entry_score: float = 0, entry_reason: str = "") -> int:
    """
    記錄一筆進場交易。

    參數：
      stock_id      股票代號
      entry_date    進場日期（YYYY-MM-DD）
      entry_price   進場價格
      shares        進場股數
      name          股票名稱
      strategy      策略（balanced/short/long/dividend/longterm）
      entry_score   系統評分（0-10）
      entry_reason  進場理由

    回傳：新記錄的 id
    """
    with _db() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (stock_id, name, strategy, entry_date, entry_price, shares,
                entry_score, entry_reason, is_open)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (stock_id.strip().upper(), name, strategy,
             entry_date, entry_price, shares, entry_score, entry_reason),
        )
        conn.commit()
        return cur.lastrowid


def close_trade(trade_id: int, exit_date: str, exit_price: float,
                exit_reason: str = "", is_us: bool = False) -> dict:
    """
    記錄出場，計算損益。

    台股手續費：0.1425% 買 + 0.1425% 賣 + 0.3% 證交稅（賣）
    美股：無費用（近似值）

    回傳：dict 含 pnl, pnl_pct
    """
    with _db() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            return {"error": f"找不到 id={trade_id} 的交易"}

        buy_price = row["entry_price"]
        shares = row["shares"]

        # 費用計算
        if is_us:
            fee_rate = 0.0
        else:
            fee_rate = 0.001425 * 2 + 0.003  # 買+賣手續費 + 證交稅

        gross_pnl = (exit_price - buy_price) * shares
        fee_cost = (buy_price + exit_price) * shares * fee_rate / 2  # 分攤
        net_pnl = gross_pnl - fee_cost
        pnl_pct = net_pnl / (buy_price * shares) * 100 if buy_price * shares > 0 else 0

        conn.execute(
            """UPDATE trades
               SET exit_date=?, exit_price=?, exit_reason=?,
                   pnl=?, pnl_pct=?, is_open=0
               WHERE id=?""",
            (exit_date, exit_price, exit_reason,
             round(net_pnl, 0), round(pnl_pct, 2), trade_id),
        )
        conn.commit()

    return {
        "trade_id": trade_id,
        "stock_id": row["stock_id"],
        "pnl": round(net_pnl, 0),
        "pnl_pct": round(pnl_pct, 2),
    }


def delete_trade(trade_id: int) -> bool:
    """刪除一筆記錄"""
    with _db() as conn:
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()
    return True


# ── 查詢 ─────────────────────────────────────────────────────────────────────

def get_all_trades(open_only: bool = False) -> list[dict]:
    """
    取得所有交易記錄。

    open_only=True 時只回傳持倉中的交易。
    """
    with _db() as conn:
        if open_only:
            rows = conn.execute(
                "SELECT * FROM trades WHERE is_open=1 ORDER BY entry_date DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY entry_date DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_trades_df():
    """回傳 pandas DataFrame（所有已結束交易）"""
    import pandas as pd
    trades = [t for t in get_all_trades() if not t["is_open"]]
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame(trades)


# ── 月度績效報告 ──────────────────────────────────────────────────────────────

def get_monthly_stats(year: int = None, month: int = None) -> dict:
    """
    計算指定月份的績效統計。

    若 year/month 為 None，計算所有已結束交易的整體統計。

    回傳 dict：
      trade_count     交易筆數
      win_count       獲利筆數
      loss_count      虧損筆數
      win_rate        勝率（%）
      total_pnl       總損益（元）
      total_return_pct 總報酬率（%，複利計算）
      avg_win_pct     平均獲利（%）
      avg_loss_pct    平均虧損（%，正數）
      profit_factor   盈虧比（avg_win / avg_loss）
      max_drawdown_pct 最大回撤（%，基於報酬序列）
      avg_hold_days   平均持倉天數
      best_trade      最佳交易 dict
      worst_trade     最差交易 dict
    """
    import numpy as np

    with _db() as conn:
        if year and month:
            rows = conn.execute(
                """SELECT * FROM trades
                   WHERE is_open=0
                     AND strftime('%Y', exit_date) = ?
                     AND strftime('%m', exit_date) = ?
                   ORDER BY exit_date""",
                (str(year), f"{month:02d}"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE is_open=0 ORDER BY exit_date"
            ).fetchall()

    trades = [dict(r) for r in rows]
    if not trades:
        return {
            "trade_count": 0, "win_rate": 0, "total_pnl": 0,
            "total_return_pct": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "avg_hold_days": 0,
        }

    returns = [t["pnl_pct"] for t in trades if t["pnl_pct"] is not None]
    pnls = [t["pnl"] for t in trades if t["pnl"] is not None]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    # 複利總報酬
    compound = 1.0
    for r in returns:
        compound *= (1 + r / 100)
    total_return_pct = (compound - 1) * 100

    # 盈虧比
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float("inf")

    # 最大回撤（基於報酬序列的 equity curve）
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak * 100
    max_drawdown = float(abs(np.min(drawdown)))

    # 平均持倉天數
    hold_days = []
    for t in trades:
        if t["entry_date"] and t["exit_date"]:
            try:
                ed = datetime.strptime(t["entry_date"][:10], "%Y-%m-%d")
                xd = datetime.strptime(t["exit_date"][:10], "%Y-%m-%d")
                hold_days.append((xd - ed).days)
            except Exception:
                pass
    avg_hold = sum(hold_days) / len(hold_days) if hold_days else 0

    # 最佳 / 最差交易
    best = max(trades, key=lambda x: x.get("pnl_pct") or -999)
    worst = min(trades, key=lambda x: x.get("pnl_pct") or 999)

    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(returns) * 100, 1) if returns else 0,
        "total_pnl": round(sum(pnls)),
        "total_return_pct": round(total_return_pct, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999,
        "max_drawdown_pct": round(max_drawdown, 2),
        "avg_hold_days": round(avg_hold, 1),
        "best_trade": best,
        "worst_trade": worst,
    }


def get_monthly_breakdown() -> list[dict]:
    """
    按月份分解績效，用於折線圖。

    回傳：list of dict（按月份排序）
      year_month  "2025-01"
      trade_count
      win_rate
      total_pnl
      total_return_pct
    """
    with _db() as conn:
        rows = conn.execute(
            """SELECT strftime('%Y-%m', exit_date) as ym,
                      pnl_pct, pnl
               FROM trades
               WHERE is_open=0 AND exit_date IS NOT NULL
               ORDER BY exit_date"""
        ).fetchall()

    if not rows:
        return []

    from collections import defaultdict
    monthly: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["ym"]:
            monthly[r["ym"]].append({"pnl_pct": r["pnl_pct"] or 0, "pnl": r["pnl"] or 0})

    result = []
    for ym in sorted(monthly.keys()):
        items = monthly[ym]
        returns = [i["pnl_pct"] for i in items]
        pnls = [i["pnl"] for i in items]
        wins = [r for r in returns if r > 0]
        compound = 1.0
        for r in returns:
            compound *= (1 + r / 100)
        result.append({
            "year_month": ym,
            "trade_count": len(items),
            "win_rate": round(len(wins) / len(returns) * 100, 1) if returns else 0,
            "total_pnl": round(sum(pnls)),
            "total_return_pct": round((compound - 1) * 100, 2),
        })
    return result


# ── Alpha 計算 ────────────────────────────────────────────────────────────────

def calc_alpha(benchmark_fetcher=None, benchmark_id="0050") -> dict:
    """
    計算系統 Alpha（超額報酬）對比大盤（0050 或指定標的）。

    benchmark_fetcher: function(stock_id, days) → DataFrame with 'date', 'close'
    benchmark_id: 基準標的代號（預設 0050）

    回傳 dict：
      system_total_return   系統複利總報酬（%）
      benchmark_return      同期大盤報酬（%）
      alpha                 超額報酬（%）
      has_benchmark         是否成功取得大盤資料
    """
    trades = [t for t in get_all_trades() if not t["is_open"]]
    if not trades:
        return {"alpha": 0, "system_total_return": 0, "benchmark_return": 0, "has_benchmark": False}

    # 找出最早進場日和最晚出場日
    dates_in = [t["entry_date"] for t in trades if t["entry_date"]]
    dates_out = [t["exit_date"] for t in trades if t["exit_date"]]
    if not dates_in or not dates_out:
        return {"alpha": 0, "system_total_return": 0, "benchmark_return": 0, "has_benchmark": False}

    start_date = min(dates_in)
    end_date = max(dates_out)

    # 系統總報酬（複利）
    returns = [t["pnl_pct"] for t in trades if t["pnl_pct"] is not None]
    compound = 1.0
    for r in returns:
        compound *= (1 + r / 100)
    sys_return = (compound - 1) * 100

    # 大盤報酬
    bm_return = 0.0
    has_bm = False
    if benchmark_fetcher:
        try:
            from datetime import datetime as dt
            days_span = (dt.strptime(end_date[:10], "%Y-%m-%d") -
                         dt.strptime(start_date[:10], "%Y-%m-%d")).days + 60
            bm_df = benchmark_fetcher(benchmark_id, days=days_span)
            if bm_df is not None and not bm_df.empty:
                bm_df = bm_df.sort_values("date").reset_index(drop=True)
                bm_df["close"] = bm_df["close"].astype(float)
                after = bm_df[bm_df["date"] >= start_date]
                if len(after) >= 2:
                    p0 = after.iloc[0]["close"]
                    p1 = after.iloc[-1]["close"]
                    bm_return = (p1 / p0 - 1) * 100
                    has_bm = True
        except Exception:
            pass

    return {
        "system_total_return": round(sys_return, 2),
        "benchmark_return": round(bm_return, 2),
        "alpha": round(sys_return - bm_return, 2),
        "has_benchmark": has_bm,
        "benchmark_id": benchmark_id,
        "period": f"{start_date[:10]} ~ {end_date[:10]}",
        "trade_count": len(trades),
    }
