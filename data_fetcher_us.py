"""
美股資料抓取模組
資料來源：yfinance（Yahoo Finance）
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _get_ticker(symbol):
    import yfinance as yf
    return yf.Ticker(symbol)


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
    """取得本益比、本淨比等估值資料"""
    try:
        t = _get_ticker(symbol)
        info = t.info

        per = info.get("trailingPE", info.get("forwardPE", 0))
        pbr = info.get("priceToBook", 0)
        dy = info.get("dividendYield", 0)
        if dy:
            dy = dy * 100  # 轉成百分比

        # 建一筆假的 DataFrame 來相容臺股分析模組
        if per and per > 0:
            return pd.DataFrame([{
                "date": datetime.now().strftime("%Y-%m-%d"),
                "PER": per,
                "PBR": pbr or 0,
                "dividend_yield": dy or 0,
            }])
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


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


def is_us_stock(symbol):
    """判斷是不是美股代號"""
    return bool(symbol) and symbol.isalpha()
