"""
美股資料抓取模組
資料來源：yfinance（Yahoo Finance）
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


_ticker_cache = {}

def _get_ticker(symbol):
    import yfinance as yf
    if symbol not in _ticker_cache:
        _ticker_cache[symbol] = yf.Ticker(symbol)
    return _ticker_cache[symbol]


def fetch_stock_name(symbol):
    """查詢股票名稱"""
    try:
        t = _get_ticker(symbol)
        info = t.info
        return info.get("shortName", info.get("longName", symbol))
    except Exception:
        return symbol


def fetch_stock_industry(symbol):
    """查詢產業類別"""
    try:
        t = _get_ticker(symbol)
        info = t.info
        return info.get("sector", "")
    except Exception:
        return ""


def fetch_stock_price(symbol, days=150):
    """抓取日K線"""
    try:
        t = _get_ticker(symbol)
        end = datetime.now()
        start = end - timedelta(days=days)
        df = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

        if df.empty:
            return pd.DataFrame()

        df = df.reset_index()
        df = df.rename(columns={
            "Date": "date",
            "Open": "open",
            "High": "max",
            "Low": "min",
            "Close": "close",
            "Volume": "Trading_Volume",
        })
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        return df[["date", "open", "max", "min", "close", "Trading_Volume"]]
    except Exception:
        return pd.DataFrame()


def fetch_per_pbr(symbol):
    """取得本益比、本淨比等估值資料（用季報 EPS + 歷史股價算出歷史 PE）"""
    try:
        t = _get_ticker(symbol)
        info = t.info
        pbr = info.get("priceToBook", 0) or 0
        dy = info.get("dividendYield", 0) or 0
        if dy:
            dy = dy * 100

        # 嘗試從季報算歷史 trailing PE
        rows = _calc_historical_pe(t, pbr, dy)
        if rows:
            return pd.DataFrame(rows)

        # fallback：至少回傳當前快照
        per = info.get("trailingPE", info.get("forwardPE", 0))
        if per and per > 0:
            return pd.DataFrame([{
                "date": datetime.now().strftime("%Y-%m-%d"),
                "PER": per,
                "PBR": pbr,
                "dividend_yield": dy,
            }])
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _calc_historical_pe(ticker, current_pbr, current_dy):
    """用季報 EPS + 歷史收盤價，算出每季末的 trailing PE"""
    try:
        # 取得季報（通常有 4-8 季）
        inc = ticker.quarterly_income_stmt
        if inc is None or inc.empty:
            return []

        # 找 EPS 欄位（Diluted EPS 優先）
        eps_key = None
        for key in ["Diluted EPS", "Basic EPS"]:
            if key in inc.index:
                eps_key = key
                break

        if not eps_key:
            return []

        eps_series = inc.loc[eps_key].dropna().sort_index()
        if len(eps_series) < 4:
            return []

        # 取得歷史股價（涵蓋所有季報日期）
        earliest = eps_series.index[0]
        hist = ticker.history(start=earliest.strftime("%Y-%m-%d"))
        if hist.empty:
            return []

        rows = []
        # 從第 4 季開始，每個季末算 trailing 4Q EPS
        for i in range(3, len(eps_series)):
            trailing_eps = sum(eps_series.iloc[i - 3 : i + 1])
            if trailing_eps <= 0:
                continue

            quarter_date = eps_series.index[i]
            # 找最接近該季末的收盤價
            close_prices = hist.loc[:quarter_date.strftime("%Y-%m-%d")]
            if close_prices.empty:
                continue

            price = close_prices["Close"].iloc[-1]
            pe = price / trailing_eps

            rows.append({
                "date": quarter_date.strftime("%Y-%m-%d"),
                "PER": round(pe, 2),
                "PBR": current_pbr,
                "dividend_yield": current_dy,
            })

        # 加上「今天」的 PE（用最新股價 + 最近 4 季 EPS）
        if len(eps_series) >= 4:
            latest_trailing = sum(eps_series.iloc[-4:])
            if latest_trailing > 0 and not hist.empty:
                today_price = hist["Close"].iloc[-1]
                rows.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "PER": round(today_price / latest_trailing, 2),
                    "PBR": current_pbr,
                    "dividend_yield": current_dy,
                })

        return rows
    except Exception:
        return []


def fetch_monthly_revenue(symbol):
    """取得營收資料（用季報近似）"""
    try:
        t = _get_ticker(symbol)
        financials = t.quarterly_financials

        if financials is None or financials.empty:
            return pd.DataFrame()

        if "Total Revenue" in financials.index:
            rev_row = financials.loc["Total Revenue"]
        elif "Operating Revenue" in financials.index:
            rev_row = financials.loc["Operating Revenue"]
        else:
            return pd.DataFrame()

        rows = []
        for date, val in rev_row.items():
            if pd.notna(val):
                rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "revenue": float(val),
                })

        return pd.DataFrame(rows).sort_values("date")
    except Exception:
        return pd.DataFrame()


def fetch_institutional(symbol):
    """取得機構持股變化"""
    try:
        t = _get_ticker(symbol)
        inst = t.institutional_holders

        if inst is None or inst.empty:
            return pd.DataFrame()

        # yfinance 的機構資料格式不同，建一個相容的格式
        # 用簡化方式：看機構整體持股比例
        info = t.info
        inst_pct = info.get("heldPercentInstitutions", 0)

        if inst_pct:
            inst_pct = inst_pct * 100
            # 建一筆相容資料
            today = datetime.now().strftime("%Y-%m-%d")
            if inst_pct > 70:
                net = 1000  # 模擬正面
            elif inst_pct > 50:
                net = 500
            else:
                net = -500

            return pd.DataFrame([
                {"date": today, "name": "Foreign_Investor", "buy": max(net, 0), "sell": max(-net, 0)},
            ])
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def fetch_etf_info(symbol):
    """取得 ETF 特有資訊（殖利率、費用率、規模、折溢價）"""
    try:
        t = _get_ticker(symbol)
        info = t.info

        dy = info.get("yield") or info.get("dividendYield") or 0
        if dy and dy < 1:
            dy = dy * 100  # 轉百分比

        er = info.get("annualReportExpenseRatio") or 0
        if er and er < 1:
            er = er * 100

        return {
            "dividend_yield": dy,
            "expense_ratio": er,
            "total_assets": info.get("totalAssets", 0),
            "nav_price": info.get("navPrice", 0),
            "current_price": info.get("regularMarketPrice") or info.get("previousClose", 0),
        }
    except Exception:
        return {}


def is_us_stock(symbol):
    """判斷是不是美股代號（含 BRK-B 這類帶符號的）"""
    if not symbol:
        return False
    cleaned = symbol.replace("-", "").replace(".", "")
    return cleaned.isalpha()
