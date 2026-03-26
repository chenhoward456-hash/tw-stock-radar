"""
設定檔
Repo 已改為 private，key 直接寫在這裡
"""
import os


def _get_secret(key, default=""):
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    val = os.environ.get(key, "")
    if val:
        return val
    return default


FINMIND_TOKEN = _get_secret("FINMIND_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0yNiAwMDoyNjoxMiIsInVzZXJfaWQiOiJjaGVuaG93YXJkNDU2IiwiZW1haWwiOiJjaGVuaG93YXJkNDU2QGdtYWlsLmNvbSIsImlwIjoiMTgwLjE3Ny41OS43MCJ9.Bmmu9fCWfU9OZ84tbfVMgfRWtdBK7ZMY_Ety1hZAQ-g")
TOTAL_BUDGET = 0
LINE_CHANNEL_ACCESS_TOKEN = _get_secret("LINE_CHANNEL_ACCESS_TOKEN", "JSrN2ecWj84PsrNhYwCXHhI6N7ck3GBhrXYuRczXmCV1HGDdbqvVPA3vK9yIcHkwrIW++tuJBdMmCSHVVLxb/UFcRlJ3oBHUoGjpVomE4c0IDAfCOioSpe8HDlz93HXAbpEhncb5quFN2AouguR9TgdB04t89/1O/w1cDnyilFU=")
LINE_USER_ID = _get_secret("LINE_USER_ID", "U3b425b2d1572d197d0992945323881e5")
TELEGRAM_BOT_TOKEN = _get_secret("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _get_secret("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY", "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")
LINE_CHANNEL_SECRET = _get_secret("LINE_CHANNEL_SECRET", "507140950973f944af055500e5b814a5")
