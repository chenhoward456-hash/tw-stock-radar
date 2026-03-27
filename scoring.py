"""
加權評分模組
根據操作策略（短線/中長線）調整各面向權重

改進項目：
1. 安全閥只對基本面+籌碼生效，技術面不再觸發封頂（避免錯殺基本面好的股票）
2. 美股法人權重歸零（yfinance 資料不可靠，0% 比 5% 噪音好）
3. 新增 macro_multiplier 參數：總體經濟環境差時自動降級
4. 所有策略都能受益於 valuation 分數（非僅 longterm）
"""

# 策略權重設定
# 權重依據：
# - 回測證明技術面選股沒用（10 檔 0 勝），只適合做風控
# - 基本面（營收、PE）和消息面才是真正的驅動力
# - 籌碼面（法人買賣超）有一定參考價值
# - 兩週後用 calibration.py 自動校準驗證

STRATEGIES = {
    "balanced": {
        "label": "均衡",
        "description": "基本面為主，技術面降權（回測校正後）",
        "weights": {"tech": 0.10, "fund": 0.35, "inst": 0.25, "news": 0.30},
    },
    "short": {
        "label": "短線波段",
        "description": "重籌碼和消息面，技術面做風控參考",
        "weights": {"tech": 0.15, "fund": 0.15, "inst": 0.35, "news": 0.35},
    },
    "long": {
        "label": "中長線持有",
        "description": "重基本面和消息面，技術面幾乎不看",
        "weights": {"tech": 0.05, "fund": 0.40, "inst": 0.20, "news": 0.35},
    },
    "dividend": {
        "label": "存股領息",
        "description": "最重基本面，適合長期存股",
        "weights": {"tech": 0.05, "fund": 0.50, "inst": 0.15, "news": 0.30},
    },
    "longterm": {
        "label": "長線佈局",
        "description": "不看短期漲跌，只看營收成長和估值便宜度",
        "weights": {"tech": 0.0, "fund": 0.60, "inst": 0.10, "news": 0.30},
        "use_valuation": True,
    },
}


def weighted_score(tech_score, fund_score, inst_score, news_score,
                   strategy="balanced", is_us=False, macro_multiplier=1.0):
    """
    根據策略計算加權綜合分數

    參數：
    - is_us: True 時美股法人權重歸零
    - macro_multiplier: 0.7-1.0，由 macro.analyze() 提供
    回傳：(加權分數, 策略資訊 dict)
    """
    config = STRATEGIES.get(strategy, STRATEGIES["balanced"])
    w = dict(config["weights"])  # 複製一份，避免改到原始設定

    if is_us:
        # 美股籌碼資料不可靠 → 權重歸零，分配給基本面和消息面
        inst_bonus = w["inst"]
        w["inst"] = 0.0
        w["fund"] += inst_bonus * 0.6
        w["news"] += inst_bonus * 0.4

    score = (
        tech_score * w["tech"]
        + fund_score * w["fund"]
        + inst_score * w["inst"]
        + news_score * w["news"]
    )

    # === 安全閘門（改進版）===
    # 只看基本面和籌碼面，技術面不參與封頂判斷
    # 原因：技術面經常在好股票回檔時給低分，導致錯殺
    core_worst = min(fund_score, inst_score) if w["inst"] > 0 else fund_score

    if core_worst <= 2:
        score = min(score, 5.0)
    elif core_worst <= 3:
        score = min(score, 6.0)

    # 新聞面極差也要注意（可能有重大利空）
    if news_score <= 2:
        score = min(score, 5.5)

    # === 總體經濟調整 ===
    if macro_multiplier < 1.0:
        score = score * macro_multiplier

    return round(score, 1), config
