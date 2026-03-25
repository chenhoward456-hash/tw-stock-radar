"""
加權評分模組
根據操作策略（短線/中長線）調整各面向權重
"""

# 策略權重設定
STRATEGIES = {
    "balanced": {
        "label": "均衡",
        "description": "四面向平均權重",
        "weights": {"tech": 0.25, "fund": 0.25, "inst": 0.25, "news": 0.25},
    },
    "short": {
        "label": "短線波段",
        "description": "重技術面和籌碼面，適合持有 1-4 週",
        "weights": {"tech": 0.35, "fund": 0.10, "inst": 0.35, "news": 0.20},
    },
    "long": {
        "label": "中長線持有",
        "description": "重基本面和消息面，適合持有 1 個月以上",
        "weights": {"tech": 0.15, "fund": 0.35, "inst": 0.20, "news": 0.30},
    },
    "dividend": {
        "label": "存股領息",
        "description": "最重基本面，適合長期存股",
        "weights": {"tech": 0.10, "fund": 0.50, "inst": 0.15, "news": 0.25},
    },
}


def weighted_score(tech_score, fund_score, inst_score, news_score, strategy="balanced"):
    """
    根據策略計算加權綜合分數
    回傳：(加權分數, 策略資訊 dict)
    """
    config = STRATEGIES.get(strategy, STRATEGIES["balanced"])
    w = config["weights"]

    score = (
        tech_score * w["tech"]
        + fund_score * w["fund"]
        + inst_score * w["inst"]
        + news_score * w["news"]
    )

    return round(score, 1), config
