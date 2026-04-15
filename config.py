"""
設定檔
優先讀取：.env → 環境變數 → Streamlit secrets
不要在這裡寫真實 key
"""
import os

# 先載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_secret(key, default=""):
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


FINMIND_TOKEN = _get_secret("FINMIND_TOKEN")
TOTAL_BUDGET = int(_get_secret("TOTAL_BUDGET", "0"))
LINE_CHANNEL_ACCESS_TOKEN = _get_secret("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = _get_secret("LINE_USER_ID")
TELEGRAM_BOT_TOKEN = _get_secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get_secret("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
LINE_CHANNEL_SECRET = _get_secret("LINE_CHANNEL_SECRET")
DISCORD_WEBHOOK_URL = _get_secret("DISCORD_WEBHOOK_URL")
