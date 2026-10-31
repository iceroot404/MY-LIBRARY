# My Library — Telegram bot + animated admin panel

## Требования
- Python 3.10+
- Telegram bot token от [@BotFather](https://t.me/BotFather)
- Ваш Telegram numeric ID

## Установка

```bash
# 1. Распакуйте архив и перейдите в папку my_library
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

Скопируйте `.env.example` в `.env` и заполните:
- `BOT_TOKEN` — токен Telegram-бота
- `ADMIN_ID` — ваш числовой Telegram ID
- `ADMIN_PASSWORD` — пароль входа в веб-админку
- `SESSION_SECRET` — длинная случайная строка (не менее 32 символов)

Запуск:

```bash
python main.py
```

Откройте:
- Сайт: http://127.0.0.1:8000
- Админ-панель: http://127.0.0.1:8000/admin/login
- Проверка сервера: http://127.0.0.1:8000/health

## Команды Telegram
- `/start` — меню администратора
- `/add` — пошаговое добавление книги
- `/list` — последние 50 книг
- `/stats` — статистика
- `/delete 5` — удалить книгу с ID 5
- `/cancel` — отменить текущий ввод

Бот принимает фото обложки и документы PDF, EPUB, FB2, DJVU, TXT (до 50 МБ).
Веб-панель позволяет добавлять книги и удалять записи. Все данные хранятся в SQLite в `library.db`, загруженные файлы — в `web/static/uploads/`.

## Важно для публикации в интернете
1. Измените `ADMIN_PASSWORD` и `SESSION_SECRET`.
2. Используйте HTTPS и установите `https_only=True` для SessionMiddleware при работе за HTTPS.
3. Не публикуйте `.env`, токен бота и базу данных в Git.
4. Для production запускайте приложение через ASGI-сервер за reverse proxy.
