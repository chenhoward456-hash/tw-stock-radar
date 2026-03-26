"""
設定檔

Streamlit Cloud 部署時會從 st.secrets 讀取
本機開發時從下方預設值讀取
"""
import os


def _get_secret(key, default=""):
    """優先從 Streamlit Cloud secrets 讀，沒有就用環境變數或預設值"""
    # Streamlit Cloud secrets
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    # 環境變數
    val = os.environ.get(key, "")
    if val:
        return val
    # 預設值
    return default


# ===== 資料來源 =====
FINMIND_TOKEN = _get_secret("FINMIND_TOKEN")

# ===== 投資預算 =====
TOTAL_BUDGET = 0

# ===== LINE Bot =====
LINE_CHANNEL_ACCESS_TOKEN = _get_secret("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = _get_secret("LINE_USER_ID")

# ===== Telegram =====
TELEGRAM_BOT_TOKEN = _get_secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get_secret("TELEGRAM_CHAT_ID")

# ===== AI 新聞分析 =====
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")

# ===== LINE Channel Secret =====
LINE_CHANNEL_SECRET = _get_secret("LINE_CHANNEL_SECRET")
