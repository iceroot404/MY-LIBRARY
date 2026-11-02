import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-this-admin-password")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-session-secret")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'library.db'}")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

UPLOADS_DIR = BASE_DIR / "web" / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
