"""Discord Webhook 推播（從舊 notify.py 抽出的最小依賴版）"""
import requests

try:
    from config import DISCORD_WEBHOOK_URL
except ImportError:
    DISCORD_WEBHOOK_URL = ""


def _split_message(text, limit=1900):
    """將超長訊息切段，盡量在換行處切割（Discord 上限 2000 字）"""
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        idx = text.rfind("\n", 0, limit)
        if idx == -1:
            idx = limit
        parts.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return parts


def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        print("  ⚠ DISCORD_WEBHOOK_URL 未設定")
        return False
    for part in _split_message(message):
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": part}, timeout=10)
            if resp.status_code not in (200, 204):
                print(f"  ⚠ Discord API 回傳 {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            print(f"  ⚠ Discord 發送失敗：{e}")
            return False
    return True
