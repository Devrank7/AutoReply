import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# When packaged with PyInstaller, files are next to the executable.
# In dev mode, files are in the script's directory.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

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

# Client Lookup
CLIENT_API_BASE_URL = os.getenv("CLIENT_API_BASE_URL", "https://winbix-ai.pp.ua")

# Google Service Account (for Sheets filter)
SERVICE_ACCOUNT_PATH = BASE_DIR / os.getenv("SERVICE_ACCOUNT_PATH", "service_account.json")
