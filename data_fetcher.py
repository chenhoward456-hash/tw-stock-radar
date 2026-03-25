"""
臺股資料抓取模組
資料來源：FinMind API
"""
import requests
import pandas as pd
from datetime import datetime, timedelta

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


def _fetch(dataset, stock_id=None, start_date=None, end_date=None, token=None):
    """從 FinMind API 抓取資料"""
    params = {"dataset": dataset}
    if stock_id:
        params["data_id"] = str(stock_id)
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if token:
        params["token"] = token

    try:
        resp = requests.get(FINMIND_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != 200:
            msg = data.get("msg", "未知錯誤")
            if "token" in msg.lower() or "limit" in msg.lower():
                print("  ⚠ 需要 FinMind Token，請到 config.py 設定（免費註冊即可）")
            else:
                print(f"  ⚠ API 回傳：{msg}")
            return pd.DataFrame()

        return pd.DataFrame(data.get("data", []))

    except requests.exceptions.Timeout:
        print("  ⚠ 連線逾時，請檢查網路")
        return pd.DataFrame()
    except requests.exceptions.ConnectionError:
        print("  ⚠ 無法連線到 FinMind，請檢查網路")
        return pd.DataFrame()
    except Exception as e:
        print(f"  ⚠ 資料抓取失敗：{e}")
        return pd.DataFrame()


_stock_info_cache = None


def _get_stock_info(token=None):
    """取得全部股票資訊（帶快取，只抓一次）"""
    global _stock_info_cache
    if _stock_info_cache is not None:
        return _stock_info_cache
    df = _fetch("TaiwanStockInfo", token=token)
    if not df.empty:
        _stock_info_cache = df
    return df


def fetch_stock_name(stock_id, token=None):
    """查詢股票名稱"""
    try:
        df = _get_stock_info(token)
        if df is not None and not df.empty:
            match = df[df["stock_id"] == str(stock_id)]
            if not match.empty:
                return match.iloc[0].get("stock_name", str(stock_id))
    except Exception:
        pass
    return str(stock_id)


def fetch_stock_industry(stock_id, token=None):
    """查詢股票所屬產業類別"""
    try:
        df = _get_stock_info(token)
        if df is not None and not df.empty:
            match = df[df["stock_id"] == str(stock_id)]
            if not match.empty:
                return match.iloc[0].get("industry_category", "")
    except Exception:
        pass
    return ""


def fetch_stock_names(stock_ids, token=None):
    """批次查詢多檔股票名稱，回傳 {stock_id: name}"""
    result = {}
    try:
        df = _get_stock_info(token)
        if df is not None and not df.empty:
            for sid in stock_ids:
                match = df[df["stock_id"] == str(sid)]
                if not match.empty:
                    result[str(sid)] = match.iloc[0].get("stock_name", str(sid))
                else:
                    result[str(sid)] = str(sid)
        else:
            result = {str(sid): str(sid) for sid in stock_ids}
    except Exception:
        result = {str(sid): str(sid) for sid in stock_ids}
    return result


def fetch_stock_price(stock_id, days=150, token=None):
    """抓取日K線（股價/成交量）"""
    end = datetime.now()
    start = end - timedelta(days=days)
    return _fetch(
        "TaiwanStockPrice",
        stock_id,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        token,
    )


def fetch_institutional(stock_id, days=30, token=None):
    """抓取三大法人買賣超"""
    end = datetime.now()
    start = end - timedelta(days=days)
    return _fetch(
        "TaiwanStockInstitutionalInvestorsBuySell",
        stock_id,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        token,
    )


def fetch_per_pbr(stock_id, days=365, token=None):
    """抓取本益比 / 本淨比 / 殖利率"""
    end = datetime.now()
    start = end - timedelta(days=days)
    return _fetch(
        "TaiwanStockPER",
        stock_id,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        token,
    )


def fetch_monthly_revenue(stock_id, months=15, token=None):
    """抓取月營收"""
    end = datetime.now()
    start = end - timedelta(days=months * 35)
    return _fetch(
        "TaiwanStockMonthRevenue",
        stock_id,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        token,
    )
