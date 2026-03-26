"""
自訂觀察清單 — 讓使用者在儀表板上新增/刪除追蹤的股票
存在 data/custom_watchlist.json
"""
import os
import json

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "custom_watchlist.json")


def load():
    """載入自訂清單，回傳 list of {"stock_id": str, "note": str}"""
    if not os.path.exists(DATA_PATH):
        return []
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save(items):
    """儲存自訂清單"""
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add(stock_id, note=""):
    """新增一檔到自訂清單"""
    items = load()
    # 不重複加
    if any(item["stock_id"] == stock_id for item in items):
        return False
    items.append({"stock_id": stock_id, "note": note})
    save(items)
    return True


def remove(stock_id):
    """從自訂清單移除"""
    items = load()
    new_items = [item for item in items if item["stock_id"] != stock_id]
    if len(new_items) == len(items):
        return False
    save(new_items)
    return True


def get_ids():
    """回傳所有自訂追蹤的股票代號"""
    return [item["stock_id"] for item in load()]
