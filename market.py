"""
市場統一入口
自動判斷臺股或美股，呼叫對應的資料來源
"""
import data_fetcher as tw
import data_fetcher_us as us
from config import FINMIND_TOKEN

TOKEN = FINMIND_TOKEN or None


def is_us(symbol):
    """判斷是不是美股"""
    return us.is_us_stock(symbol)


def fetch_stock_name(symbol):
    if is_us(symbol):
        return us.fetch_stock_name(symbol)
    return tw.fetch_stock_name(symbol, TOKEN)


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
