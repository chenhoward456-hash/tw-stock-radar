"""
你的持倉清單
stop_loss = 停損價，跌到這個價格系統會推 LINE 提醒你
"""

HOLDINGS = [
    {
        "stock_id": "2317",
        "buy_price": 235,
        "shares": 200,
        "buy_date": "2025-12-09",
        "stop_loss": 180,  # 跌到 180 元提醒你
    },
]
