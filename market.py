"""
市場統一入口
自動判斷臺股或美股，呼叫對應的資料來源
"""
import data_fetcher as tw
import data_fetcher_us as us
from config import FINMIND_TOKEN
from watchlist import WATCHLIST

TOKEN = FINMIND_TOKEN or None

# 從觀察清單建立 ETF 集合（啟動時算一次）
_ETF_SET = set()
for _sector, _stocks in WATCHLIST.items():
    if "ETF" in _sector:
        _ETF_SET.update(_stocks)


def is_us(symbol):
    """判斷是不是美股"""
    return us.is_us_stock(symbol)


def is_etf(symbol):
    """判斷是不是 ETF"""
    if symbol in _ETF_SET:
        return True
    # 台股：代號以 0 開頭的數字碼通常是 ETF
    if not is_us(symbol) and symbol.startswith("0") and symbol.isdigit():
        return True
    return False


def fetch_stock_name(symbol):
    if is_us(symbol):
        return us.fetch_stock_name(symbol)
    return tw.fetch_stock_name(symbol, TOKEN)


def fetch_stock_names(symbols):
    """批次查名稱，混合臺股美股都行"""
    result = {}
    tw_ids = [s for s in symbols if not is_us(s)]
    us_ids = [s for s in symbols if is_us(s)]

    if tw_ids:
        result.update(tw.fetch_stock_names(tw_ids, TOKEN))
    for s in us_ids:
        result[s] = us.fetch_stock_name(s)

    return result


def fetch_stock_industry(symbol):
    if is_us(symbol):
        return us.fetch_stock_industry(symbol)
    return tw.fetch_stock_industry(symbol, TOKEN)


def fetch_stock_price(symbol, days=150):
    if is_us(symbol):
        return us.fetch_stock_price(symbol, days)
    return tw.fetch_stock_price(symbol, days, TOKEN)


def fetch_per_pbr(symbol):
    if is_us(symbol):
        return us.fetch_per_pbr(symbol)
    return tw.fetch_per_pbr(symbol, token=TOKEN)


def fetch_monthly_revenue(symbol):
    if is_us(symbol):
        return us.fetch_monthly_revenue(symbol)
    return tw.fetch_monthly_revenue(symbol, token=TOKEN)


def fetch_institutional(symbol):
    if is_us(symbol):
        return us.fetch_institutional(symbol)
    return tw.fetch_institutional(symbol, token=TOKEN)


def fetch_stock_price_adjusted(symbol, days=500):
    """取得還原權息價格（回測用，避免除息除權跳空產生假訊號）"""
    import yfinance as yf
    from datetime import datetime, timedelta

    # 台股加 .TW 後綴，美股直接用
    yf_symbol = f"{symbol}.TW" if not is_us(symbol) else symbol

    try:
        t = yf.Ticker(yf_symbol)
        end = datetime.now()
        start = end - timedelta(days=days)
        df = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

        if df.empty:
            # fallback 到一般抓法
            return fetch_stock_price(symbol, days)

        df = df.reset_index()
        df = df.rename(columns={
            "Date": "date",
            "Open": "open",
            "High": "max",
            "Low": "min",
            "Close": "close",
            "Volume": "Trading_Volume",
        })
        # 處理 timezone-aware dates
        if hasattr(df["date"].dtype, "tz") and df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_localize(None)
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        return df[["date", "open", "max", "min", "close", "Trading_Volume"]]
    except Exception:
        return fetch_stock_price(symbol, days)


def fetch_etf_info(symbol):
    """取得 ETF 特有資訊"""
    if is_us(symbol):
        return us.fetch_etf_info(symbol)
    return tw.fetch_etf_info(symbol, token=TOKEN)
