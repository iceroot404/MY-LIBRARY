"""Команды читателя и привязка личного кабинета к Telegram."""
from __future__ import annotations

import html
import random

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import func

from .config import SITE_URL
from .database import SessionLocal
from .models import Book, User, UserShelf, ReadingProgress, BookRequest, UserNotification

router = Router(name="library_reader_commands")


def _site_book_url(book_id: int) -> str | None:
    base = SITE_URL.rstrip("/")
    if not base or "127.0.0.1" in base or "localhost" in base:
        return None
    return f"{base}/read/{book_id}"


def _books_message(books: list[Book], heading: str) -> tuple[str, InlineKeyboardMarkup | None]:
    if not books:
        return f"{heading}\n\nПока книг нет.", None
    lines = [f"<b>{heading}</b>"]
    buttons = []
    for book in books:
        lines.append(f"\n📘 <b>{html.escape(book.title)}</b>\n✍️ {html.escape(book.author)}")
        link = _site_book_url(book.id)
        if link:
            buttons.append([InlineKeyboardButton(text=f"Открыть: {book.title[:45]}", url=link)])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons[:10]) if buttons else None
    return "\n".join(lines), markup


@router.message(CommandStart())
async def reader_start(message: Message):
    text = (
        "📚 <b>Добро пожаловать в My Library!</b>\n\n"
        "Команды:\n"
        "/catalog — последние книги\n"
        "/search название — поиск\n"
        "/popular — популярные книги\n"
        "/new — новинки\n"
        "/random — случайная книга\n"
        "/profile — ваш профиль\n"
        "/history — история чтения\n"
        "/requests — ваши заявки\n"
        "/link КОД — связать Telegram с сайтом\n"
        "/help — помощь"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("help"))
async def reader_help(message: Message):
    await reader_start(message)


@router.message(Command("link"))
async def link_account(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or len(parts[1].strip()) < 6:
        return await message.answer("Использование: <code>/link ВАШ_КОД</code>", parse_mode="HTML")
    code = parts[1].strip()
    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_link_code == code).first()
        if not user:
            return await message.answer("Код не найден или уже использован. Создайте новый код в личном кабинете сайта.")
        other = db.query(User).filter(User.telegram_id == message.from_user.id, User.id != user.id).first()
        if other:
            return await message.answer("Этот Telegram уже связан с другим аккаунтом My Library.")
        user.telegram_id = message.from_user.id
        user.telegram_link_code = None
        db.commit()
        username = user.username
    await message.answer(f"✅ Telegram успешно связан с аккаунтом <b>{html.escape(username)}</b>. Теперь вы сможете получать уведомления.", parse_mode="HTML")


@router.message(Command("catalog"))
async def catalog(message: Message):
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.is_deleted.is_(False)).order_by(Book.created_at.desc(), Book.id.desc()).limit(10).all()
        text, markup = _books_message(books, "Последние книги каталога")
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("new"))
async def new_books(message: Message):
    await catalog(message)


@router.message(Command("popular"))
async def popular(message: Message):
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.is_deleted.is_(False)).order_by(Book.view_count.desc(), Book.download_count.desc()).limit(10).all()
        text, markup = _books_message(books, "Популярные книги")
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("random"))
async def random_book(message: Message):
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.is_deleted.is_(False), Book.file.isnot(None)).all()
        if not books:
            return await message.answer("Пока нет доступных книг.")
        book = random.choice(books)
        text, markup = _books_message([book], "Случайная книга для вас")
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("search"))
async def search_books(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or len(parts[1].strip()) < 2:
        return await message.answer("Напишите запрос: <code>/search название или автор</code>", parse_mode="HTML")
    term = f"%{parts[1].strip()[:100]}%"
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.is_deleted.is_(False), (Book.title.ilike(term) | Book.author.ilike(term))).order_by(Book.view_count.desc()).limit(10).all()
        text, markup = _books_message(books, "Результаты поиска")
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("profile"))
async def profile(message: Message):
    with SessionLocal() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            return await message.answer("Сначала свяжите аккаунт сайта командой /link КОД.")
        favorites = db.query(UserShelf).filter_by(user_id=user.id).count()
        unread = db.query(UserNotification).filter_by(user_id=user.id, is_read=0).count()
        total_requests = db.query(BookRequest).filter_by(user_id=user.id).count()
        text = (
            f"👤 <b>{html.escape(user.username)}</b>\n"
            f"📚 Книг на полках: {favorites}\n"
            f"🔔 Непрочитанных уведомлений: {unread}\n"
            f"📨 Заявок: {total_requests}"
        )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("history"))
async def history(message: Message):
    with SessionLocal() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            return await message.answer("Сначала свяжите аккаунт сайта командой /link КОД.")
        rows = db.query(ReadingProgress, Book).join(Book, Book.id == ReadingProgress.book_id).filter(ReadingProgress.user_id == user.id, Book.is_deleted.is_(False)).order_by(ReadingProgress.updated_at.desc()).limit(10).all()
        if not rows:
            return await message.answer("История чтения пока пуста.")
        lines = ["<b>Недавно читали</b>"]
        for progress, book in rows:
            lines.append(f"\n📖 {html.escape(book.title)} — {html.escape(book.author)} ({round(progress.percent or 0)}%)")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("requests"))
async def requests(message: Message):
    with SessionLocal() as db:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            return await message.answer("Сначала свяжите аккаунт сайта командой /link КОД.")
        orders = db.query(BookRequest).filter_by(user_id=user.id).order_by(BookRequest.created_at.desc()).limit(10).all()
        if not orders:
            return await message.answer("У вас пока нет заявок на книги.")
        labels = {"pending": "ожидает", "accepted": "принята", "completed": "книга добавлена", "rejected": "отклонена"}
        lines = ["<b>Ваши заявки</b>"]
        for order in orders:
            lines.append(f"\n#{order.id} · {html.escape(order.book_title)} — {labels.get(order.status, order.status)}")
    await message.answer("\n".join(lines), parse_mode="HTML")
