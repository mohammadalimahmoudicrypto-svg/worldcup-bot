import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
TIMEZONE = os.getenv("TIMEZONE", "UTC")

FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")
COMPETITION_CODE = os.getenv("COMPETITION_CODE", "WC")
GROUP_CHAT_ID = -abs(int(os.getenv("GROUP_CHAT_ID"))) if os.getenv("GROUP_CHAT_ID") else None
RESULT_CHECK_INTERVAL = int(os.getenv("RESULT_CHECK_INTERVAL", "300"))
