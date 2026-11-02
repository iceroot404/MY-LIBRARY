"""Mass book import for the MY LIBRARY Telegram admin bot.

Admin flow:
  /bulk -> choose one of three modes -> send files -> /finish

Modes:
  covers: send all covers first, then /books, then book files.
  alternating: send cover, then its book file, repeat. /skipcover skips a cover.
  auto: send book files only; Open Library is queried for missing covers.
"""

import asyncio
import html
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy import func

from .config import ADMIN_ID, UPLOADS_DIR
from .database import SessionLocal
from .models import Book

router = Router(name="bulk_book_import")
router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)

BOOK_EXTENSIONS = {".pdf", ".epub", ".fb2", ".djvu", ".txt"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# Telegram's hosted Bot API currently allows bots to download files up to 20 MB.
MAX_FILE_BYTES = 20 * 1024 * 1024
OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org/b/id/{}-L.jpg?default=false"


class BulkImport(StatesGroup):
    receiving = State()


def mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Сначала все обложки, потом книги", callback_data="bulk:mode:covers")],
        [InlineKeyboardButton(text="2️⃣ Обложка → книга → обложка → книга", callback_data="bulk:mode:alternating")],
        [InlineKeyboardButton(text="3️⃣ Только книги — бот ищет обложки", callback_data="bulk:mode:auto")],
    ])


def receiving_keyboard(stage: str) -> InlineKeyboardMarkup:
    buttons = []
    if stage == "covers":
        buttons.append([InlineKeyboardButton(text="📚 Начать отправку книг", callback_data="bulk:books")])
    buttons.append([InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="bulk:finish")])
    buttons.append([InlineKeyboardButton(text="❌ Отменить", callback_data="bulk:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _safe_name(name: str) -> str:
    return Path(name or "book").name


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _metadata_from_epub(path: Path) -> tuple[str | None, str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            opf_path = None
            for node in container.iter():
                if _local(node.tag) == "rootfile":
                    opf_path = node.attrib.get("full-path")
                    break
            if not opf_path:
                return None, None
            package = ET.fromstring(archive.read(opf_path))
            title = author = None
            for node in package.iter():
                name = _local(node.tag)
                value = (node.text or "").strip()
                if name == "title" and value and not title:
                    title = value
                elif name == "creator" and value and not author:
                    author = value
            return title, author
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None, None


def _metadata_from_fb2(path: Path) -> tuple[str | None, str | None]:
    try:
        root = ET.parse(path).getroot()
        title = author = None
        for node in root.iter():
            if _local(node.tag) == "book-title" and (node.text or "").strip() and not title:
                title = (node.text or "").strip()
            if _local(node.tag) == "author" and not author:
                parts = []
                for child in node.iter():
                    if _local(child.tag) in {"first-name", "middle-name", "last-name", "nickname"}:
                        text = (child.text or "").strip()
                        if text:
                            parts.append(text)
                if parts:
                    author = " ".join(parts)
        return title, author
    except (OSError, ET.ParseError):
        return None, None


def _caption_metadata(caption: str | None) -> tuple[str | None, str | None]:
    if not caption:
        return None, None
    pieces = re.split(r"\s+[—–]\s+|\s+-\s+", caption.strip(), maxsplit=1)
    if len(pieces) == 2 and all(p.strip() for p in pieces):
        return pieces[0].strip(), pieces[1].strip()
    return None, None


def extract_metadata(path: Path, original_name: str, caption: str | None = None) -> tuple[str, str]:
    caption_title, caption_author = _caption_metadata(caption)
    ext = Path(original_name).suffix.lower()
    title = author = None
    if ext == ".epub":
        title, author = _metadata_from_epub(path)
    elif ext == ".fb2":
        title, author = _metadata_from_fb2(path)

    # An explicit Telegram caption in "Название — Автор" format takes priority.
    title = caption_title or title
    author = caption_author or author

    if not title:
        title = Path(original_name).stem
        title = re.sub(r"^\s*\d{1,4}[._ -]+", "", title).strip(" _-.")
        filename_parts = re.split(r"\s+[—–]\s+|\s+-\s+", title, maxsplit=1)
        if len(filename_parts) == 2 and all(part.strip() for part in filename_parts):
            title, filename_author = filename_parts[0].strip(), filename_parts[1].strip()
            if not author:
                author = filename_author
    if not author:
        author = "Неизвестен"
    return (title or "Без названия")[:255], author[:255]


def _normalise(value: str) -> str:
    value = value.lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", value)


async def _download_cover_from_open_library(
    session: aiohttp.ClientSession,
    title: str,
    author: str,
) -> str | None:
    params = {
        "title": title[:180],
        "limit": "8",
        "fields": "title,author_name,cover_i",
    }
    if author and author != "Неизвестен":
        params["author"] = author[:120]

    try:
        async with session.get(OPEN_LIBRARY_SEARCH, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                return None
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None

    target_title = _normalise(title)
    target_author = _normalise(author) if author != "Неизвестен" else ""
    best_cover = None
    best_score = 0.0

    for item in payload.get("docs", []):
        cover_id = item.get("cover_i")
        candidate_title = str(item.get("title") or "")
        if not cover_id or not candidate_title:
            continue
        title_score = SequenceMatcher(None, target_title, _normalise(candidate_title)).ratio()
        authors = item.get("author_name") or []
        author_score = 0.0
        if target_author and authors:
            author_score = max(
                SequenceMatcher(None, target_author, _normalise(str(name))).ratio()
                for name in authors
            )
        score = title_score if not target_author else title_score * 0.8 + author_score * 0.2
        if score > best_score:
            best_score = score
            best_cover = cover_id

    # Avoid attaching a cover when the catalogue match is too uncertain.
    threshold = 0.76 if target_author else 0.86
    if not best_cover or best_score < threshold:
        return None

    filename = f"cover_{uuid.uuid4().hex}.jpg"
    destination = UPLOADS_DIR / filename
    try:
        async with session.get(OPEN_LIBRARY_COVERS.format(best_cover), timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                return None
            content_type = response.headers.get("Content-Type", "").lower()
            if "image" not in content_type:
                return None
            body = await response.read()
            if not body or len(body) > 8 * 1024 * 1024:
                return None
            destination.write_bytes(body)
            return filename
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        destination.unlink(missing_ok=True)
        return None


async def _save_message_file(message: Message, bot, *, is_image: bool) -> tuple[str, str] | None:
    if message.photo:
        file_id = message.photo[-1].file_id
        original_name = f"telegram_photo_{uuid.uuid4().hex}.jpg"
        suffix = ".jpg"
        size = message.photo[-1].file_size or 0
    elif message.document:
        doc = message.document
        original_name = _safe_name(doc.file_name or "upload")
        suffix = Path(original_name).suffix.lower()
        file_id = doc.file_id
        size = doc.file_size or 0
    else:
        return None

    allowed = IMAGE_EXTENSIONS if is_image else BOOK_EXTENSIONS
    if suffix not in allowed:
        return None
    if size and size > MAX_FILE_BYTES:
        await message.answer("❌ Файл больше 20 МБ. Через обычного Telegram-бота такой файл скачать нельзя.")
        return None

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = UPLOADS_DIR / stored_name
    try:
        await bot.download(file_id, destination=destination)
    except Exception:
        destination.unlink(missing_ok=True)
        await message.answer("❌ Не удалось скачать файл из Telegram. Попробуй отправить его ещё раз.")
        return None
    return stored_name, original_name


async def _get_data(state: FSMContext) -> dict:
    return await state.get_data()


@router.message(Command("bulk"))
async def bulk_command(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BulkImport.receiving)
    await state.update_data(mode=None, stage=None, covers=[], books=[], pending_cover=None, owned_files=[])
    await message.answer(
        "📦 <b>Массовая загрузка книг</b>\n\n"
        "Выбери способ отправки. Можно загрузить 100 книг и больше, отправляя файлы несколькими сообщениями или альбомами.",
        reply_markup=mode_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bulk:start")
async def bulk_start_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(BulkImport.receiving)
    await state.update_data(mode=None, stage=None, covers=[], books=[], pending_cover=None, owned_files=[])
    if callback.message:
        await callback.message.answer(
            "📦 <b>Массовая загрузка книг</b>\nВыбери способ отправки:",
            reply_markup=mode_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("bulk:mode:"))
async def choose_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.rsplit(":", 1)[-1]
    if mode not in {"covers", "alternating", "auto"}:
        return await callback.answer("Неизвестный режим", show_alert=True)
    stage = "covers" if mode == "covers" else ("need_cover" if mode == "alternating" else "books")
    await state.set_state(BulkImport.receiving)
    await state.update_data(mode=mode, stage=stage, covers=[], books=[], pending_cover=None, owned_files=[])
    await callback.answer()

    messages = {
        "covers": (
            "🖼 <b>Режим 1: обложки сначала</b>\n\n"
            "1. Отправь все обложки по порядку.\n"
            "2. Нажми «Начать отправку книг» или отправь /books.\n"
            "3. Отправь файлы книг в том же порядке.\n"
            "4. Нажми «Завершить загрузку» или отправь /finish.\n\n"
            "Если обложки для книги не окажется, бот попробует найти её сам."
        ),
        "alternating": (
            "🔁 <b>Режим 2: обложка и книга по очереди</b>\n\n"
            "Отправляй: обложка → файл книги → следующая обложка → следующая книга.\n"
            "Если обложки нет, отправь /skipcover, затем файл книги.\n"
            "Когда закончишь, отправь /finish."
        ),
        "auto": (
            "🔎 <b>Режим 3: только книги</b>\n\n"
            "Отправляй PDF, EPUB, FB2, DJVU или TXT.\n"
            "Бот извлечёт название и автора из EPUB/FB2, а если обложки нет — попробует найти её в каталоге Open Library.\n"
            "Когда закончишь, отправь /finish."
        ),
    }
    if callback.message:
        await callback.message.answer(messages[mode], parse_mode="HTML", reply_markup=receiving_keyboard(stage))


@router.message(Command("books"))
async def begin_books_stage(message: Message, state: FSMContext):
    data = await _get_data(state)
    if not await state.get_state() or data.get("mode") != "covers" or data.get("stage") != "covers":
        return await message.answer("Сначала выбери режим 1 «Обложки сначала» через /bulk.")
    await state.update_data(stage="books")
    await message.answer(
        f"📚 Обложек принято: {len(data.get('covers', []))}. Теперь отправляй файлы книг в том же порядке.",
        reply_markup=receiving_keyboard("books"),
    )


@router.callback_query(F.data == "bulk:books")
async def begin_books_stage_callback(callback: CallbackQuery, state: FSMContext):
    data = await _get_data(state)
    if data.get("mode") != "covers" or data.get("stage") != "covers":
        return await callback.answer("Сначала выбери режим 1", show_alert=True)
    await state.update_data(stage="books")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"📚 Обложек принято: {len(data.get('covers', []))}. Теперь отправляй файлы книг в том же порядке.",
            reply_markup=receiving_keyboard("books"),
        )


@router.message(Command("skipcover"))
async def skip_alternating_cover(message: Message, state: FSMContext):
    data = await _get_data(state)
    if data.get("mode") != "alternating" or data.get("stage") != "need_cover":
        return await message.answer("Команда /skipcover доступна в режиме 2 перед отправкой книги.")
    await state.update_data(stage="need_book", pending_cover=None)
    await message.answer("Хорошо. Теперь отправь файл книги — бот попробует найти обложку сам.")


@router.message(BulkImport.receiving, F.photo)
async def receive_photo(message: Message, state: FSMContext, bot):
    data = await _get_data(state)
    mode, stage = data.get("mode"), data.get("stage")
    if not mode:
        return await message.answer("Сначала выбери один из трёх режимов на кнопках выше.")
    if mode == "auto" or stage == "books":
        return await message.answer("Сейчас нужны файлы книг, а не обложки.")
    saved = await _save_message_file(message, bot, is_image=True)
    if not saved:
        return
    stored_name, _ = saved
    owned = data.get("owned_files", []) + [stored_name]
    if mode == "covers":
        covers = data.get("covers", []) + [stored_name]
        await state.update_data(covers=covers, owned_files=owned)
        if len(covers) % 10 == 0:
            await message.answer(f"🖼 Принято обложек: {len(covers)}")
    else:
        await state.update_data(pending_cover=stored_name, stage="need_book", owned_files=owned)
        await message.answer("✅ Обложка принята. Теперь отправь соответствующий файл книги.")


@router.message(BulkImport.receiving, F.document)
async def receive_document(message: Message, state: FSMContext, bot):
    data = await _get_data(state)
    mode, stage = data.get("mode"), data.get("stage")
    if not mode:
        return await message.answer("Сначала выбери один из трёх режимов на кнопках выше.")

    suffix = Path(_safe_name(message.document.file_name or "upload")).suffix.lower()
    if mode == "covers" and stage == "covers":
        saved = await _save_message_file(message, bot, is_image=True)
        if not saved:
            return await message.answer("Отправь обложку JPG, JPEG, PNG или WEBP.")
        stored_name, _ = saved
        covers = data.get("covers", []) + [stored_name]
        await state.update_data(covers=covers, owned_files=data.get("owned_files", []) + [stored_name])
        if len(covers) % 10 == 0:
            await message.answer(f"🖼 Принято обложек: {len(covers)}")
        return

    if suffix in IMAGE_EXTENSIONS:
        if mode == "alternating" and stage == "need_cover":
            saved = await _save_message_file(message, bot, is_image=True)
            if saved:
                stored_name, _ = saved
                await state.update_data(pending_cover=stored_name, stage="need_book", owned_files=data.get("owned_files", []) + [stored_name])
                await message.answer("✅ Обложка принята. Теперь отправь соответствующий файл книги.")
            return
        return await message.answer("Сейчас бот ждёт файл книги, а не изображение.")

    if suffix not in BOOK_EXTENSIONS:
        return await message.answer("❌ Формат не поддерживается. Разрешены PDF, EPUB, FB2, DJVU и TXT.")
    if mode == "alternating" and stage == "need_cover":
        return await message.answer("Сначала отправь обложку или команду /skipcover, затем книгу.")

    saved = await _save_message_file(message, bot, is_image=False)
    if not saved:
        return
    stored_name, original_name = saved
    title, author = extract_metadata(UPLOADS_DIR / stored_name, original_name, message.caption)
    item = {
        "file": stored_name,
        "title": title,
        "author": author,
        "cover": data.get("pending_cover") if mode == "alternating" else None,
    }
    books = data.get("books", []) + [item]
    updates = {"books": books, "owned_files": data.get("owned_files", []) + [stored_name]}
    if mode == "alternating":
        updates.update({"pending_cover": None, "stage": "need_cover"})
    await state.update_data(**updates)
    if len(books) % 10 == 0:
        await message.answer(f"📚 Принято файлов книг: {len(books)}")
    elif len(books) == 1:
        await message.answer(
            f"✅ Принята книга №1: <b>{html.escape(title)}</b> — {html.escape(author)}",
            parse_mode="HTML",
        )


async def finish_import(message: Message, state: FSMContext):
    data = await _get_data(state)
    mode = data.get("mode")
    books = data.get("books", [])
    covers = data.get("covers", [])
    if not mode:
        return await message.answer("Сначала выбери режим через /bulk.")
    if mode == "covers" and data.get("stage") == "covers":
        return await message.answer("Сначала нажми «Начать отправку книг» или отправь /books.")
    if not books:
        return await message.answer("Пока не получено ни одного файла книги. Отправь книги или используй /cancel.")

    if mode == "covers":
        for index, item in enumerate(books):
            if index < len(covers):
                item["cover"] = covers[index]

    await message.answer(
        f"⏳ Начинаю добавление {len(books)} книг. Для отсутствующих обложек выполню поиск."
    )
    created = 0
    skipped = 0
    no_cover = 0
    used_covers = set()
    headers = {"User-Agent": "MY-LIBRARY-Telegram-Bot/1.0 (book cover matching)"}

    async with aiohttp.ClientSession(headers=headers) as session:
        last_search_at = 0.0
        loop = asyncio.get_running_loop()
        for index, item in enumerate(books, start=1):
            cover = item.get("cover")
            if cover:
                used_covers.add(cover)
            else:
                # Open Library asks unauthenticated clients to keep requests to ~1/sec.
                elapsed = loop.time() - last_search_at
                if elapsed < 1.05:
                    await asyncio.sleep(1.05 - elapsed)
                cover = await _download_cover_from_open_library(session, item["title"], item["author"])
                last_search_at = loop.time()
                if cover:
                    used_covers.add(cover)
                else:
                    no_cover += 1

            with SessionLocal() as db:
                duplicate = db.query(Book).filter(
                    func.lower(Book.title) == item["title"].lower(),
                    func.lower(Book.author) == item["author"].lower(),
                    Book.is_deleted.is_(False),
                ).first()
                if duplicate:
                    skipped += 1
                    continue
                book = Book(
                    title=item["title"],
                    author=item["author"],
                    category="Разное",
                    description="",
                    cover=cover,
                    file=item["file"],
                )
                db.add(book)
                db.commit()
                created += 1

            if index % 10 == 0 or index == len(books):
                await message.answer(f"⏳ Обработано {index}/{len(books)} книг… Добавлено: {created}.")

    # Remove unused images (for example, extra covers that had no matching book).
    for filename in data.get("owned_files", []):
        if filename in used_covers:
            continue
        if filename not in {item.get("file") for item in books}:
            (UPLOADS_DIR / filename).unlink(missing_ok=True)

    await state.clear()
    await message.answer(
        "✅ <b>Массовая загрузка завершена</b>\n\n"
        f"📚 Добавлено: <b>{created}</b>\n"
        f"⏭ Дубликатов пропущено: <b>{skipped}</b>\n"
        f"🖼 Без найденной обложки: <b>{no_cover}</b>\n\n"
        "Книги уже находятся в каталоге сайта.",
        parse_mode="HTML",
    )


@router.message(Command("finish"))
async def finish_command(message: Message, state: FSMContext):
    await finish_import(message, state)


@router.callback_query(F.data == "bulk:finish")
async def finish_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.message:
        await finish_import(callback.message, state)


@router.message(Command("bulkcancel"))
async def cancel_bulk(message: Message, state: FSMContext):
    data = await _get_data(state)
    if data.get("mode"):
        for filename in data.get("owned_files", []):
            (UPLOADS_DIR / filename).unlink(missing_ok=True)
        await state.clear()
        await message.answer("❌ Массовая загрузка отменена. Временные файлы удалены.")


@router.callback_query(F.data == "bulk:cancel")
async def cancel_bulk_callback(callback: CallbackQuery, state: FSMContext):
    data = await _get_data(state)
    for filename in data.get("owned_files", []):
        (UPLOADS_DIR / filename).unlink(missing_ok=True)
    await state.clear()
    await callback.answer("Загрузка отменена")
    if callback.message:
        await callback.message.answer("❌ Массовая загрузка отменена. Временные файлы удалены.")
