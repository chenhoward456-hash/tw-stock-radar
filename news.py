"""
消息面分析模組
優先使用 Claude AI 分析新聞（需要 ANTHROPIC_API_KEY）
沒有 API Key 時退回關鍵字比對
"""
import logging
import re
import xml.etree.ElementTree as ET
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ===== 關鍵字（AI 不可用時的備案）=====
POSITIVE = [
    "上漲", "大漲", "飆漲", "看好", "利多", "突破", "創新高", "成長",
    "獲利", "營收增", "買超", "加碼", "調升", "強勢", "多頭", "回升",
    "反彈", "復甦", "擴大", "亮眼", "超預期", "訂單", "需求增", "新高",
    "長紅", "漲停", "噴出", "搶進", "受惠", "題材", "商機",
]
NEGATIVE = [
    "下跌", "大跌", "暴跌", "看壞", "利空", "跌破", "創新低", "衰退",
    "虧損", "營收減", "賣超", "減碼", "調降", "弱勢", "空頭", "崩盤",
    "重挫", "萎縮", "警示", "風險", "低迷", "裁員", "庫存", "下滑",
    "長黑", "跌停", "恐慌", "套牢", "出貨", "砍單",
]


def _fetch_google_news(query, max_items=20, lang="zh"):
    """從 Google News RSS 抓取新聞標題"""
    if lang == "en":
        url = (
            f"https://news.google.com/rss/search?"
            f"q={quote(query)}+when:7d&hl=en-US&gl=US&ceid=US:en"
        )
    else:
        url = (
            f"https://news.google.com/rss/search?"
            f"q={quote(query)}+when:7d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        )
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        items = []
        for item in root.iter("item"):
            title_el = item.find("title")
            source_el = item.find("source")
            if title_el is not None and title_el.text:
                items.append({
                    "title": title_el.text,
                    "source": source_el.text if source_el is not None else "",
                })
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        logger.warning(f"Google News RSS failed for '{query}': {e}")
        return []


def _fetch_yahoo_news(query, max_items=20):
    """從 Yahoo News RSS 抓取新聞標題（Google 結果不足時的備案）"""
    url = f"https://news.yahoo.com/rss/search?p={quote(query)}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        items = []
        for item in root.iter("item"):
            title_el = item.find("title")
            source_el = item.find("source")
            if title_el is not None and title_el.text:
                items.append({
                    "title": title_el.text,
                    "source": (source_el.text if source_el is not None else "Yahoo"),
                })
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        logger.warning(f"Yahoo News RSS failed for '{query}': {e}")
        return []


def fetch_news(query, max_items=20, lang="zh"):
    """從 Google News RSS 抓取新聞標題，結果不足 5 則時嘗試 Yahoo News 補充"""
    items = _fetch_google_news(query, max_items, lang)

    # 如果 Google 結果不足 5 則，嘗試 Yahoo News 補充
    if len(items) < 5:
        yahoo_items = _fetch_yahoo_news(query, max_items - len(items))
        if yahoo_items:
            # 用 set 去重（避免同一則新聞重複）
            existing_titles = {a["title"].lower() for a in items}
            for ya in yahoo_items:
                if ya["title"].lower() not in existing_titles:
                    items.append(ya)
                    existing_titles.add(ya["title"].lower())
                if len(items) >= max_items:
                    break

    return items


POSITIVE_EN = [
    "surge", "rally", "soar", "bullish", "upbeat", "beat", "growth",
    "profit", "revenue up", "buy", "upgrade", "strong", "recovery",
    "rebound", "record high", "outperform", "exceed", "boost", "gain",
]
NEGATIVE_EN = [
    "drop", "fall", "plunge", "bearish", "downbeat", "miss", "decline",
    "loss", "revenue down", "sell", "downgrade", "weak", "recession",
    "crash", "record low", "underperform", "warning", "risk", "layoff",
    "cut", "slump", "fear",
]


def _keyword_score(articles, is_us=False):
    """關鍵字比對情緒分析（備案）"""
    pos_words = POSITIVE_EN if is_us else POSITIVE
    neg_words = NEGATIVE_EN if is_us else NEGATIVE

    pos, neg = 0, 0
    for a in articles:
        t = a["title"].lower()
        pos += sum(1 for w in pos_words if w in t)
        neg += sum(1 for w in neg_words if w in t)

    total = pos + neg
    if total == 0:
        return 5.0, pos, neg, ""
    ratio = pos / total
    score = round(1 + ratio * 9, 1)
    return score, pos, neg, ""


_ai_disabled = False  # key 失敗後整個 session 不再重試


def _ai_score(stock_id, stock_name, articles):
    """用 Claude AI 分析新聞情緒（key 失敗後自動停用，不浪費時間）"""
    global _ai_disabled
    if _ai_disabled:
        return None

    try:
        from anthropic import Anthropic
        from config import ANTHROPIC_API_KEY

        if not ANTHROPIC_API_KEY:
            _ai_disabled = True
            return None

        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        headlines = "\n".join([f"- {a['title']}" for a in articles[:10]])

        # 美股用英文新聞但回答用中文
        if _is_us_symbol(stock_id):
            prompt = (
                f"你是股市分析師。以下是近7天關於 {stock_name}（{stock_id}）的英文新聞標題：\n\n"
                f"{headlines}\n\n"
                "請分析整體情緒並用中文回答（只回答這兩行，不要多說）：\n"
                "評分：[1-10的數字，1=極負面 5=中性 10=極正面]\n"
                "總結：[一句話中文總結消息面狀況，20字以內]"
            )
        else:
            prompt = (
                f"你是臺股分析師。以下是近7天關於「{stock_name}」({stock_id}) 的新聞標題：\n\n"
                f"{headlines}\n\n"
                "請分析整體情緒並回答（只回答這兩行，不要多說）：\n"
                "評分：[1-10的數字，1=極負面 5=中性 10=極正面]\n"
                "總結：[一句話總結消息面狀況，20字以內]"
            )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        score = 5.0
        summary = ""

        for line in text.split("\n"):
            if "評分" in line:
                nums = re.findall(r"[\d.]+", line)
                if nums:
                    score = max(1.0, min(10.0, float(nums[0])))
            if "總結" in line:
                summary = line.split("：", 1)[-1].strip() if "：" in line else ""

        return score, summary

    except ImportError:
        _ai_disabled = True
        return None
    except Exception as e:
        logger.warning(f"AI news scoring failed for {stock_id}: {e}")
        # 401/403 = key 壞了，整個 session 不再嘗試
        if "401" in str(e) or "authentication" in str(e).lower():
            logger.warning("API key 無效，本次掃描停用 AI 新聞分析")
            _ai_disabled = True
        return None


def _is_us_symbol(symbol):
    """簡易判斷是否為美股"""
    if not symbol:
        return False
    cleaned = symbol.replace("-", "").replace(".", "")
    return cleaned.isalpha()


def _news_volume_signal(stock_id, stock_name, is_us):
    """
    新聞量異常偵測：突然大量新聞可能代表重大事件
    回傳：(volume_adj, detail_str)
    """
    try:
        if is_us:
            recent = fetch_news(f"{stock_id} stock", max_items=30, lang="en")
        else:
            recent = fetch_news(stock_name, max_items=30, lang="zh")

        count = len(recent)
        if count >= 25:
            return -0.5, f"⚠ 新聞量異常多（{count} 則），可能有重大事件，需留意"
        elif count <= 3:
            return 0, f"— 新聞量很少（{count} 則），市場關注度低"
        return 0, None
    except Exception as e:
        logger.warning(f"News volume signal failed for {stock_id}: {e}")
        return 0, None


def analyze(stock_id, stock_name):
    """
    消息面分析（改進版：加入新聞量異常偵測 + 多來源交叉驗證）
    回傳：{"signal": str, "score": float, "details": list}
    """
    result = {"signal": "yellow", "score": 5.0, "details": []}

    # 美股用英文搜股票代號，台股用中文搜股票名稱
    is_us = _is_us_symbol(stock_id)
    if is_us:
        # 美股：用代號搜英文新聞（例如 "NVDA stock"）
        articles = fetch_news(f"{stock_id} stock", lang="en")
    else:
        articles = fetch_news(stock_name, lang="zh")

    if not articles:
        result["details"].append("⚠ 無法取得近期新聞（可能被暫時限制）")
        return result

    details = []
    details.append(f"— 近 7 日找到 {len(articles)} 則相關新聞")

    # 優先用 AI 分析（送更多標題提升判斷品質）
    ai_result = _ai_score(stock_id, stock_name, articles)

    if ai_result is not None:
        score, summary = ai_result
        details.append("— 分析方式：AI 語意分析")
        if summary:
            details.append(f"— AI 判斷：{summary}")

        # 用關鍵字做交叉驗證（改進：AI + 關鍵字取平均，降低單一方法的偏差）
        kw_score, pos, neg, _ = _keyword_score(articles, is_us=is_us)
        if abs(score - kw_score) > 3:
            details.append(f"— ⚠ AI 與關鍵字判斷差異大（AI={score:.0f} vs 關鍵字={kw_score:.0f}），取平均")
            score = (score * 0.7 + kw_score * 0.3)  # 仍以 AI 為主
    else:
        score, pos, neg, _ = _keyword_score(articles, is_us=is_us)
        details.append("— 分析方式：關鍵字比對")
        details.append(f"— 正面關鍵字 {pos} 次 / 負面關鍵字 {neg} 次")

    # 新聞量異常偵測
    vol_adj, vol_detail = _news_volume_signal(stock_id, stock_name, is_us)
    if vol_detail:
        details.append(vol_detail)
        score += vol_adj

    score = max(1.0, min(10.0, score))

    if score >= 7:
        details.append("✓ 新聞情緒偏正面")
    elif score <= 3:
        details.append("⚠ 新聞情緒偏負面")
    else:
        details.append("— 新聞情緒中性")

    # 顯示前 5 則新聞（原本 3 則太少）
    details.append("")
    details.append("近期新聞：")
    for a in articles[:5]:
        src = f" [{a['source']}]" if a["source"] else ""
        title = a["title"][:60]
        details.append(f"  • {title}{src}")

    if score >= 7:
        signal = "green"
    elif score >= 4:
        signal = "yellow"
    else:
        signal = "red"

    result["signal"] = signal
    result["score"] = round(score, 1)
    result["details"] = details
    return result


def count_news_heat(query):
    """計算某個關鍵字的新聞熱度"""
    return len(fetch_news(query, max_items=30))
