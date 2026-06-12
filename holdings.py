"""
你的持倉清單
strategy: "longterm" = 長線 / "short" = 短線 / "hold" = 買進持有不動

2026-06-12 清倉更新：TSLA、緯創(3231)、華固(2548) 全部出清。
現行策略 = 0050 月扣 DCA + 一點正2，就這兩個。
"""

HOLDINGS = [
    {"stock_id": "0050", "buy_price": 76.2, "shares": 65, "buy_date": "2026-03-26", "stop_loss": 0, "strategy": "hold"},
    # 00631L 正2：買價/股數補在這裡（或丟給 LINE 助手記）
    # {"stock_id": "00631L", "buy_price": 0.0, "shares": 0, "buy_date": "", "stop_loss": 0, "strategy": "hold"},
]
