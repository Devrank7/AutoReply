import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_MANAGER_CHAT_ID = os.getenv("TELEGRAM_MANAGER_CHAT_ID")

# Gmail
GMAIL_CREDENTIALS_PATH = BASE_DIR / os.getenv("GMAIL_CREDENTIALS_PATH", "credentials/credentials.json")
GMAIL_TOKEN_PATH = BASE_DIR / os.getenv("GMAIL_TOKEN_PATH", "credentials/token.json")

# Polling
GMAIL_POLL_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL", "30"))

# System prompt
SYSTEM_PROMPT_PATH = BASE_DIR / os.getenv("SYSTEM_PROMPT_PATH", "sales_agent_system_prompt.md")

# Database
DB_PATH = BASE_DIR / "data.db"

# Desktop App
import platform as _platform
import tempfile as _tempfile

if _platform.system() == "Windows":
    SCREENSHOT_PATH = os.path.join(_tempfile.gettempdir(), "autoreply_screenshot.png")
else:
    SCREENSHOT_PATH = "/tmp/autoreply_screenshot.png"

SCREENSHOT_METHOD = os.getenv("SCREENSHOT_METHOD", "window")
