from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
BOT_DIR = ROOT / "bot"
ADMIN_FILE = BOT_DIR / "admin_bot.py"
MODULE_FILE = BOT_DIR / "bulk_import.py"

if not ADMIN_FILE.is_file() or not MODULE_FILE.is_file():
    raise SystemExit("Не найдены bot/admin_bot.py или bot/bulk_import.py. Запусти установщик из папки проекта.")

text = ADMIN_FILE.read_text(encoding="utf-8")

if "bulk_import_router" in text:
    print("Массовая загрузка уже подключена. Повторное изменение не требуется.")
    raise SystemExit(0)

# Insert the button immediately before the existing panel refresh button.
refresh_row = '''            [
                InlineKeyboardButton(
                    text="🔄 Обновить панель",
                    callback_data="admin:panel"
                )
            ]'''
new_row = '''            [
                InlineKeyboardButton(
                    text="📦 Массовая загрузка (до 100+ книг)",
                    callback_data="bulk:start"
                )
            ],
'''
if refresh_row not in text:
    raise SystemExit("Не найден ожидаемый блок кнопки «Обновить панель» в panel_keyboard(). Файл не изменён.")
text = text.replace(refresh_row, new_row + refresh_row, 1)

# Include the separate router inside build_bot(), after the main admin router.
include_line = "    dp.include_router(router)"
if text.count(include_line) != 1:
    raise SystemExit("Не удалось однозначно найти dp.include_router(router). Файл не изменён.")
text = text.replace(
    include_line,
    include_line + "\n\n    from .bulk_import import router as bulk_import_router\n    dp.include_router(bulk_import_router)",
    1,
)

backup = ADMIN_FILE.with_name("admin_bot.py.before_bulk_import")
if not backup.exists():
    shutil.copy2(ADMIN_FILE, backup)
ADMIN_FILE.write_text(text, encoding="utf-8")
print("Готово: добавлена кнопка массовой загрузки и подключён обработчик bot/bulk_import.py")
print(f"Резервная копия: {backup.name}")
