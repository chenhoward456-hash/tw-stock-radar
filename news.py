"""
消息面分析模組
優先使用 Claude AI 分析新聞（需要 ANTHROPIC_API_KEY）
沒有 API Key 時退回關鍵字比對
"""
import re
import xml.etree.ElementTree as ET
import requests
from urllib.parse import quote

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


def fetch_news(query, max_items=20, lang="zh"):
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
    except Exception:
        return []


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


def _ai_score(stock_id, stock_name, articles):
    """用 Claude AI 分析新聞情緒"""
    try:
        from anthropic import Anthropic
        from config import ANTHROPIC_API_KEY

        if not ANTHROPIC_API_KEY:
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
        return None
    except Exception:
        return None


def _is_us_symbol(symbol):
    """簡易判斷是否為美股"""
    if not symbol:
        return False
    cleaned = symbol.replace("-", "").replace(".", "")
    return cleaned.isalpha()


def analyze(stock_id, stock_name):
    """
    消息面分析
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

    # 優先用 AI 分析
    ai_result = _ai_score(stock_id, stock_name, articles)

    if ai_result is not None:
        score, summary = ai_result
        details.append("— 分析方式：AI 語意分析")
        if summary:
            details.append(f"— AI 判斷：{summary}")
    else:
        score, pos, neg, _ = _keyword_score(articles, is_us=is_us)
        details.append("— 分析方式：關鍵字比對")
        details.append(f"— 正面關鍵字 {pos} 次 / 負面關鍵字 {neg} 次")

    if score >= 7:
        details.append("✓ 新聞情緒偏正面")
    elif score <= 3:
        details.append("⚠ 新聞情緒偏負面")
    else:
        details.append("— 新聞情緒中性")

    # 顯示前 3 則新聞
    details.append("")
    details.append("近期新聞：")
    for a in articles[:3]:
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
