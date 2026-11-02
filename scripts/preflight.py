#!/usr/bin/env python3
"""Read-only deployment preflight for My Library. Does not print secret values."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

errors = []
warnings = []
checks = []

def check(label, ok, detail=""):
    checks.append((label, bool(ok), detail))
    if not ok:
        errors.append(label)

admin_login = os.getenv("ADMIN_LOGIN", "").strip()
admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
session_secret = os.getenv("SESSION_SECRET", "").strip()
secure_cookie = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
bot_token = os.getenv("BOT_TOKEN", "").strip()
admin_id = os.getenv("ADMIN_ID", "0").strip()

check("ADMIN_LOGIN задан", bool(admin_login), "Добавьте ADMIN_LOGIN в .env")
check("ADMIN_PASSWORD изменён", bool(admin_password) and admin_password != "change-this-admin-password", "Задайте уникальный пароль администратора")
check("SESSION_SECRET достаточно длинный", len(session_secret) >= 32 and session_secret != "change-this-session-secret", "Задайте случайный SESSION_SECRET длиной не менее 32 символов")
if secure_cookie:
    check("COOKIE_SECURE включён", True, "Secure cookies включены")
else:
    warnings.append("COOKIE_SECURE=false: допустимо только для локального HTTP. Для HTTPS установите true.")
if bool(bot_token) != (admin_id not in {"", "0"}):
    warnings.append("BOT_TOKEN и ADMIN_ID заданы не одновременно: Telegram-бот не запустится.")
else:
    checks.append(("Настройки Telegram согласованы", True, "Бот включён" if bot_token and admin_id not in {"", "0"} else "Бот выключен — сайт может работать без него"))

uploads = ROOT / "web" / "static" / "uploads"
check("Папка загрузок существует", uploads.is_dir(), str(uploads))
check("Папка загрузок доступна для записи", uploads.is_dir() and os.access(uploads, os.W_OK), "Проверьте права каталога uploads")
check("Главный модуль присутствует", (ROOT / "main.py").is_file())
check("Каталог шаблонов присутствует", (ROOT / "web" / "templates").is_dir())
check("Файл требований присутствует", (ROOT / "requirements.txt").is_file())

for label, ok, detail in checks:
    print(("OK  " if ok else "FAIL") + label + (f" — {detail}" if detail else ""))
for item in warnings:
    print("WARN " + item)

if errors:
    print(f"\nНайдено обязательных проблем: {len(errors)}")
    sys.exit(1)
print(f"\nPreflight завершён: {len(checks)} проверок пройдено; предупреждений: {len(warnings)}.")
