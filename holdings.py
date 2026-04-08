"""
你的持倉清單
strategy: "longterm" = 長線 / "short" = 短線 / "hold" = 買進持有不動
"""

HOLDINGS = [
    {"stock_id": "TSLA", "buy_price": 459.0, "shares": 38, "buy_date": "2025-01-01", "stop_loss": 340.0, "strategy": "longterm"},
    {"stock_id": "0050", "buy_price": 76.2, "shares": 65, "buy_date": "2026-03-26", "stop_loss": 0, "strategy": "hold"},
    {"stock_id": "3231", "buy_price": 128.0, "shares": 39, "buy_date": "2026-03-26", "stop_loss": 118.0, "strategy": "longterm"},
    {"stock_id": "2548", "buy_price": 126.0, "shares": 21, "buy_date": "2026-04-08", "stop_loss": 113.0, "strategy": "short"},
]
