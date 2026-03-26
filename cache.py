"""
檔案快取模組
把 API 回傳的資料存成 JSON 檔，在 TTL 內直接讀檔，不重複呼叫 API。
"""
import os
import json
import time
import hashlib
import pandas as pd

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_PROJECT_DIR, "data", "cache")

TTL_REALTIME = 4 * 60 * 60       # 4 小時（股價等即時資料）
TTL_DAILY = 24 * 60 * 60         # 24 小時（營收、PER）
TTL_STATIC = 7 * 24 * 60 * 60    # 7 天（股票名稱等幾乎不變的）


def _make_key(prefix, *args):
    raw = f"{prefix}__{'__'.join(str(a) for a in args)}"
    short_hash = hashlib.md5(raw.encode()).hexdigest()[:8]
    first_arg = str(args[0]) if args else ""
    return f"{prefix}_{first_arg}_{short_hash}"


def get(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, f"{key}.json")
    if not os.path.exists(filepath):
        return None, False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry.get("saved_at", 0) > entry.get("ttl", 0):
            try:
                os.remove(filepath)
            except OSError:
                pass
            return None, False
        data = entry.get("data")
        if entry.get("type") == "dataframe":
            return pd.DataFrame(data) if data else pd.DataFrame(), True
        return data, True
    except Exception:
        return None, False


def put(key, data, ttl):
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, f"{key}.json")
    if isinstance(data, pd.DataFrame):
        data_type = "dataframe"
        serialized = json.loads(data.to_json(orient="records")) if not data.empty else []
    elif isinstance(data, dict):
        data_type = "dict"
        serialized = data
    else:
        data_type = "raw"
        serialized = data
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "ttl": ttl, "type": data_type, "data": serialized}, f, ensure_ascii=False)
    except Exception:
        pass


def cached_call(prefix, args, ttl, fetch_fn):
    """先查快取，沒有就呼叫 fetch_fn()，存快取後回傳。"""
    key = _make_key(prefix, *args)
    data, hit = get(key)
    if hit:
        return data
    data = fetch_fn()
    # 空結果不快取（下次重試）
    if isinstance(data, pd.DataFrame) and data.empty:
        return data
    if data is None or (isinstance(data, dict) and not data):
        return data
    put(key, data, ttl)
    return data


def clear_all():
    os.makedirs(CACHE_DIR, exist_ok=True)
    count = 0
    for f in os.listdir(CACHE_DIR):
        if f.endswith(".json"):
            try:
                os.remove(os.path.join(CACHE_DIR, f))
                count += 1
            except OSError:
                pass
    return count
