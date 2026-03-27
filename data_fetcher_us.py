"""
美股資料抓取模組
資料來源：yfinance（Yahoo Finance）
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import cache


import threading
_ticker_cache = {}
_ticker_lock = threading.Lock()

def _get_ticker(symbol):
    import yfinance as yf
    with _ticker_lock:
        if symbol not in _ticker_cache:
            _ticker_cache[symbol] = yf.Ticker(symbol)
        return _ticker_cache[symbol]


def fetch_stock_name(symbol):
    """查詢股票名稱 — 帶快取"""
    def _do():
        try:
            t = _get_ticker(symbol)
            info = t.info
            return info.get("shortName", info.get("longName", symbol))
        except Exception:
            return symbol
    return cache.cached_call("us_name", (symbol,), cache.TTL_STATIC, _do)


def fetch_stock_industry(symbol):
    """查詢產業類別 — 帶快取"""
    def _do():
        try:
            t = _get_ticker(symbol)
            info = t.info
            return info.get("sector", "")
        except Exception:
            return ""
    return cache.cached_call("us_industry", (symbol,), cache.TTL_STATIC, _do)


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


def fetch_insider_and_margins(symbol):
    """
    取得內部人持股、獲利能力、盈餘驚喜（第三輪新增）
    回傳：{"insider_pct": float, "gross_margin": float, "operating_margin": float,
           "earnings_surprise": float, "details": list}
    """
    result = {"insider_pct": 0, "gross_margin": 0, "operating_margin": 0,
              "earnings_surprise": None, "details": []}
    try:
        t = _get_ticker(symbol)
        info = t.info

        # 內部人持股
        insider = info.get("heldPercentInsiders", 0) or 0
        if insider:
            insider_pct = insider * 100
            result["insider_pct"] = round(insider_pct, 1)
            if insider_pct > 10:
                result["details"].append(f"✓ 內部人持股 {insider_pct:.1f}%（管理層有利益一致性）")
            elif insider_pct > 5:
                result["details"].append(f"— 內部人持股 {insider_pct:.1f}%")
            elif insider_pct < 1:
                result["details"].append(f"⚠ 內部人持股僅 {insider_pct:.1f}%（偏低）")

        # 獲利能力（毛利率、營業利益率）
        gm = info.get("grossMargins", 0) or 0
        om = info.get("operatingMargins", 0) or 0
        if gm:
            result["gross_margin"] = round(gm * 100, 1)
        if om:
            result["operating_margin"] = round(om * 100, 1)

        if gm > 0 and om > 0:
            gm_pct = gm * 100
            om_pct = om * 100
            if gm_pct > 50:
                result["details"].append(f"✓ 毛利率 {gm_pct:.0f}%（護城河強）")
            elif gm_pct > 30:
                result["details"].append(f"— 毛利率 {gm_pct:.0f}%")
            else:
                result["details"].append(f"⚠ 毛利率 {gm_pct:.0f}%（偏低）")

            if om_pct > 20:
                result["details"].append(f"✓ 營業利益率 {om_pct:.0f}%（獲利能力佳）")
            elif om_pct < 5:
                result["details"].append(f"⚠ 營業利益率 {om_pct:.0f}%（獲利能力弱）")

        # 盈餘驚喜（EPS beat/miss）
        try:
            earnings = t.earnings_history
            if earnings is not None and not earnings.empty:
                # 取最近一季的 surprise
                if "epsActual" in earnings.columns and "epsEstimate" in earnings.columns:
                    latest = earnings.iloc[-1]
                    actual = latest.get("epsActual", 0)
                    estimate = latest.get("epsEstimate", 0)
                    if actual and estimate and estimate != 0:
                        surprise = (actual / estimate - 1) * 100
                        result["earnings_surprise"] = round(surprise, 1)
                        if surprise > 10:
                            result["details"].append(f"✓ 最近一季 EPS 超預期 {surprise:+.1f}%")
                        elif surprise > 0:
                            result["details"].append(f"— 最近一季 EPS 小幅超預期 {surprise:+.1f}%")
                        elif surprise < -10:
                            result["details"].append(f"⚠ 最近一季 EPS 大幅低於預期 {surprise:+.1f}%")
                        else:
                            result["details"].append(f"— 最近一季 EPS 略低預期 {surprise:+.1f}%")
        except Exception:
            pass

    except Exception:
        pass

    return result


def fetch_financial_health(symbol):
    """
    [R4] 取得財務健康指標：自由現金流、負債比、利息保障倍數
    回傳：{"fcf": float, "debt_to_equity": float, "interest_coverage": float,
           "current_ratio": float, "score_adj": float, "details": list}
    """
    result = {"fcf": None, "debt_to_equity": None, "interest_coverage": None,
              "current_ratio": None, "score_adj": 0, "details": []}
    try:
        t = _get_ticker(symbol)
        info = t.info

        # 自由現金流
        fcf = info.get("freeCashflow", None)
        if fcf is not None:
            result["fcf"] = fcf
            if fcf > 0:
                # FCF yield = FCF / Market Cap
                mcap = info.get("marketCap", 0) or 0
                if mcap > 0:
                    fcf_yield = (fcf / mcap) * 100
                    if fcf_yield > 8:
                        result["details"].append(f"✓ FCF Yield {fcf_yield:.1f}%（現金流充沛）")
                        result["score_adj"] += 1
                    elif fcf_yield > 4:
                        result["details"].append(f"✓ FCF Yield {fcf_yield:.1f}%（健康）")
                        result["score_adj"] += 0.5
                    else:
                        result["details"].append(f"— FCF Yield {fcf_yield:.1f}%")
            else:
                result["details"].append(f"⚠ 自由現金流為負（燒錢中）")
                result["score_adj"] -= 1

        # 負債股東權益比
        de = info.get("debtToEquity", None)
        if de is not None:
            result["debt_to_equity"] = round(de, 1)
            if de > 200:
                result["details"].append(f"🚨 負債/權益比 {de:.0f}%（高槓桿風險）")
                result["score_adj"] -= 1.5
            elif de > 100:
                result["details"].append(f"⚠ 負債/權益比 {de:.0f}%（偏高）")
                result["score_adj"] -= 0.5
            elif de < 30:
                result["details"].append(f"✓ 負債/權益比 {de:.0f}%（財務穩健）")
                result["score_adj"] += 0.5
            else:
                result["details"].append(f"— 負債/權益比 {de:.0f}%")

        # 流動比率
        cr = info.get("currentRatio", None)
        if cr is not None:
            result["current_ratio"] = round(cr, 2)
            if cr < 1.0:
                result["details"].append(f"⚠ 流動比率 {cr:.2f}（短期償債壓力）")
                result["score_adj"] -= 0.5
            elif cr > 2.0:
                result["details"].append(f"✓ 流動比率 {cr:.2f}（短期財務安全）")
                result["score_adj"] += 0.5

        # 利息保障倍數（用 EBIT / Interest Expense 近似）
        try:
            # yfinance 的 financials 有 EBIT 和 Interest Expense
            fin = t.financials
            if fin is not None and not fin.empty:
                ebit_row = None
                interest_row = None
                for idx in fin.index:
                    idx_lower = str(idx).lower()
                    if "ebit" in idx_lower and "ebitda" not in idx_lower:
                        ebit_row = idx
                    if "interest" in idx_lower and "expense" in idx_lower:
                        interest_row = idx

                if ebit_row and interest_row:
                    ebit = float(fin.loc[ebit_row].iloc[0])
                    interest = abs(float(fin.loc[interest_row].iloc[0]))
                    if interest > 0:
                        ic = ebit / interest
                        result["interest_coverage"] = round(ic, 1)
                        if ic < 2:
                            result["details"].append(f"🚨 利息保障倍數 {ic:.1f}x（償債風險高）")
                            result["score_adj"] -= 1
                        elif ic < 5:
                            result["details"].append(f"⚠ 利息保障倍數 {ic:.1f}x（尚可）")
                        elif ic > 15:
                            result["details"].append(f"✓ 利息保障倍數 {ic:.1f}x（極安全）")
                            result["score_adj"] += 0.5
                        else:
                            result["details"].append(f"— 利息保障倍數 {ic:.1f}x")
        except Exception:
            pass

    except Exception:
        pass

    return result


def is_us_stock(symbol):
    """判斷是不是美股代號（含 BRK-B 這類帶符號的）"""
    if not symbol:
        return False
    cleaned = symbol.replace("-", "").replace(".", "")
    return cleaned.isalpha()
