
import asyncio
import uuid
import html
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from .config import ADMIN_ID, BOT_TOKEN, UPLOADS_DIR
from .database import SessionLocal
from .models import Book, BookRequest, UserNotification


router = Router()

router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)

ALLOWED_BOOK_EXTENSIONS = {
    ".pdf", ".epub", ".fb2", ".djvu", ".txt"
}

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp"
}

MAX_UPLOAD_SIZE = 50 * 1024 * 1024


# =========================
# СОСТОЯНИЯ ДОБАВЛЕНИЯ КНИГИ
# =========================

class AddBook(StatesGroup):
    title = State()
    author = State()
    category = State()
    description = State()
    cover = State()
    file = State()


# =========================
# ГЛАВНАЯ КНОПКА
# =========================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📚 Панель управления"
                )
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Откройте панель управления"
    )


# =========================
# INLINE АДМИН-ПАНЕЛЬ
# =========================

def panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить книгу",
                    callback_data="admin:add"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Список книг",
                    callback_data="admin:list"
                ),
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin:stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить панель",
                    callback_data="admin:panel"
                )
            ]
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в панель",
                    callback_data="admin:panel"
                )
            ]
        ]
    )


# =========================
# ПОКАЗ ПАНЕЛИ
# =========================

async def show_panel(message: Message):
    text = (
        "📚 <b>MY LIBRARY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Добро пожаловать в панель управления!\n\n"
        "Выберите нужное действие ниже 👇"
    )

    await message.answer(
        text,
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

    await message.answer(
        "⚙️ <b>Управление библиотекой</b>",
        reply_markup=panel_keyboard(),
        parse_mode="HTML"
    )


@router.message(CommandStart())
async def start(message: Message):
    await show_panel(message)


@router.message(Command("panel"))
async def open_panel_command(message: Message):
    await show_panel(message)


@router.message(F.text == "📚 Панель управления")
async def open_panel_button(message: Message):
    await show_panel(message)


# =========================
# ОТМЕНА ДЕЙСТВИЯ
# =========================

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "❌ Действие отменено.\n"
        "Нажмите кнопку «📚 Панель управления».",
        reply_markup=main_keyboard()
    )


# =========================
# ДОБАВИТЬ КНИГУ
# =========================

async def start_add_book(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddBook.title)

    await message.answer(
        "➕ <b>Добавление книги</b>\n\n"
        "Введите название книги:",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


@router.callback_query(F.data == "admin:add")
async def add_button(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if callback.message:
        await start_add_book(callback.message, state)


@router.message(Command("add"))
async def add_command(message: Message, state: FSMContext):
    await start_add_book(message, state)


@router.message(AddBook.title, F.text)
async def add_title(message: Message, state: FSMContext):
    title = message.text.strip()

    if not title:
        return await message.answer("Введите название книги.")

    await state.update_data(title=title[:255])
    await state.set_state(AddBook.author)

    await message.answer("✍️ Теперь введите автора книги:")


@router.message(AddBook.author, F.text)
async def add_author(message: Message, state: FSMContext):
    author = message.text.strip()

    if not author:
        return await message.answer("Введите автора книги.")

    await state.update_data(author=author[:255])
    await state.set_state(AddBook.category)

    await message.answer(
        "🏷 Введите категорию книги:\n"
        "Например: Фантастика, Наука, Классика."
    )


@router.message(AddBook.category, F.text)
async def add_category(message: Message, state: FSMContext):
    category = message.text.strip() or "Разное"

    await state.update_data(category=category[:100])
    await state.set_state(AddBook.description)

    await message.answer(
        "📝 Введите описание книги.\n\n"
        "Отправьте - чтобы пропустить."
    )


@router.message(AddBook.description, F.text)
async def add_description(message: Message, state: FSMContext):
    description = message.text.strip()

    if description == "-":
        description = ""

    await state.update_data(description=description)

    await state.set_state(AddBook.cover)

    await message.answer(
        "🖼 Отправьте обложку книги фотографией.\n\n"
        "Или отправьте - чтобы пропустить."
    )


# =========================
# СОХРАНЕНИЕ ФАЙЛОВ
# =========================

async def save_telegram_file(
    bot: Bot,
    file_id: str,
    suffix: str
) -> str:

    filename = f"{uuid.uuid4().hex}{suffix.lower()}"

    destination = UPLOADS_DIR / filename

    await bot.download(
        file_id,
        destination=destination
    )

    return filename


@router.message(AddBook.cover, F.photo)
async def add_cover(message: Message, state: FSMContext, bot: Bot):
    filename = await save_telegram_file(
        bot,
        message.photo[-1].file_id,
        ".jpg"
    )

    await state.update_data(cover=filename)
    await state.set_state(AddBook.file)

    await message.answer(
        "✅ Обложка сохранена!\n\n"
        "Теперь отправьте файл книги:\n"
        "PDF, EPUB, FB2, DJVU или TXT.\n\n"
        "Отправьте - чтобы пропустить."
    )


@router.message(AddBook.cover, F.text == "-")
async def skip_cover(message: Message, state: FSMContext):
    await state.update_data(cover=None)
    await state.set_state(AddBook.file)

    await message.answer(
        "Отправьте файл книги или - чтобы пропустить."
    )


# =========================
# СОХРАНЕНИЕ КНИГИ В БАЗУ
# =========================

async def finish_book(
    message: Message,
    state: FSMContext,
    filename: str | None
):
    data = await state.get_data()

    with SessionLocal() as db:
        book = Book(
            title=data["title"],
            author=data["author"],
            category=data.get("category", "Разное"),
            description=data.get("description", ""),
            cover=data.get("cover"),
            file=filename
        )

        db.add(book)
        db.commit()
        db.refresh(book)

        book_id = book.id

    await state.clear()

    await message.answer(
        "✅ <b>Книга успешно добавлена!</b>\n\n"
        f"📖 Название: {html.escape(data['title'])}\n"
        f"✍️ Автор: {html.escape(data['author'])}\n"
        f"🆔 ID: <code>{book_id}</code>",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

    await message.answer(
        "Что делаем дальше?",
        reply_markup=panel_keyboard()
    )


@router.message(AddBook.file, F.document)
async def add_file(
    message: Message,
    state: FSMContext,
    bot: Bot
):
    document = message.document

    suffix = Path(document.file_name or "").suffix.lower()

    if suffix not in ALLOWED_BOOK_EXTENSIONS:
        return await message.answer(
            "❌ Формат не поддерживается.\n"
            "Разрешены PDF, EPUB, FB2, DJVU, TXT."
        )

    if document.file_size and document.file_size > MAX_UPLOAD_SIZE:
        return await message.answer(
            "❌ Максимальный размер файла — 50 МБ."
        )

    filename = await save_telegram_file(
        bot,
        document.file_id,
        suffix
    )

    await finish_book(message, state, filename)


@router.message(AddBook.file, F.text == "-")
async def skip_book_file(
    message: Message,
    state: FSMContext
):
    await finish_book(message, state, None)


# =========================
# СПИСОК КНИГ
# =========================

async def send_books(message: Message):
    with SessionLocal() as db:
        books = (
            db.query(Book)
            .order_by(Book.id.desc())
            .limit(50)
            .all()
        )

        book_data = [
            (book.id, book.title, book.author)
            for book in books
        ]

    if not book_data:
        await message.answer(
            "📚 Библиотека пока пуста.",
            reply_markup=back_keyboard()
        )
        return

    text = "📚 <b>ПОСЛЕДНИЕ КНИГИ</b>\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    keyboard = []

    for book_id, title, author in book_data:
        text += (
            f"🆔 <code>{book_id}</code> — "
            f"{html.escape(title)}\n"
            f"✍️ {html.escape(author)}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить #{book_id}",
                callback_data=f"book:delete:{book_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="admin:panel"
        )
    ])

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@router.callback_query(F.data == "admin:list")
async def list_button(callback: CallbackQuery):
    await callback.answer()

    if callback.message:
        await send_books(callback.message)


@router.message(Command("list"))
async def list_command(message: Message):
    await send_books(message)


# =========================
# СТАТИСТИКА
# =========================

async def send_stats(message: Message):
    with SessionLocal() as db:
        total = db.query(Book).count()

        categories = (
            db.query(Book.category)
            .distinct()
            .count()
        )

        with_files = (
            db.query(Book)
            .filter(Book.file.is_not(None))
            .count()
        )

        with_covers = (
            db.query(Book)
            .filter(Book.cover.is_not(None))
            .count()
        )

    text = (
        "📊 <b>СТАТИСТИКА БИБЛИОТЕКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📚 Всего книг: <b>{total}</b>\n"
        f"🏷 Категорий: <b>{categories}</b>\n"
        f"📎 С файлами: <b>{with_files}</b>\n"
        f"🖼 С обложками: <b>{with_covers}</b>\n\n"
        "✅ База данных работает."
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


@router.callback_query(F.data == "admin:stats")
async def stats_button(callback: CallbackQuery):
    await callback.answer()

    if callback.message:
        await send_stats(callback.message)


@router.message(Command("stats"))
async def stats_command(message: Message):
    await send_stats(message)


# =========================
# УДАЛЕНИЕ КНИГ
# =========================

@router.callback_query(F.data.startswith("book:delete:"))
async def delete_confirm(callback: CallbackQuery):
    await callback.answer()

    try:
        book_id = int(callback.data.split(":")[-1])
    except (ValueError, AttributeError):
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"book:confirm:{book_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="book:cancel"
                )
            ]
        ]
    )

    if callback.message:
        await callback.message.answer(
            f"⚠️ Удалить книгу с ID <code>{book_id}</code>?",
            parse_mode="HTML",
            reply_markup=keyboard
        )


@router.callback_query(F.data.startswith("book:confirm:"))
async def delete_book(callback: CallbackQuery):
    try:
        book_id = int(callback.data.split(":")[-1])
    except (ValueError, AttributeError):
        return await callback.answer("Неверный ID.")

    with SessionLocal() as db:
        book = db.get(Book, book_id)

        if not book:
            await callback.answer("Книга не найдена.", show_alert=True)
            return

        for filename in (book.cover, book.file):
            if filename and Path(filename).name == filename:
                (UPLOADS_DIR / filename).unlink(missing_ok=True)

        db.delete(book)
        db.commit()

    await callback.answer("Книга удалена!")

    if callback.message:
        await callback.message.edit_text(
            f"🗑 Книга #{book_id} успешно удалена."
        )


@router.callback_query(F.data == "book:cancel")
async def cancel_delete(callback: CallbackQuery):
    await callback.answer("Удаление отменено.")

    if callback.message:
        await callback.message.edit_text(
            "❌ Удаление отменено."
        )


# =========================
# ВОЗВРАТ В ПАНЕЛЬ
# =========================

@router.callback_query(F.data == "admin:panel")
async def back_to_panel(callback: CallbackQuery):
    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "📚 <b>Панель управления библиотекой</b>",
            reply_markup=panel_keyboard(),
            parse_mode="HTML"
        )



# =========================
# УПРАВЛЕНИЕ ЗАКАЗАМИ КНИГ
# =========================

def order_keyboard(order_id: int, status: str = "pending"):
    if status == "pending":
        buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Принять заказ",
                    callback_data=f"order:accept:{order_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"order:reject:{order_id}",
                ),
            ]
        ]
    elif status == "accepted":
        buttons = [
            [
                InlineKeyboardButton(
                    text="📚 Выполнен заказ",
                    callback_data=f"order:done:{order_id}",
                )
            ]
        ]
    else:
        buttons = []

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def save_order_notification(db, order, title, message, book_id=None):
    if not order.user_id:
        return

    db.add(UserNotification(
        user_id=order.user_id,
        title=title,
        message=message,
        book_id=book_id,
    ))


@router.callback_query(F.data.startswith("order:accept:"))
async def order_accept_callback(callback: CallbackQuery):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        return await callback.answer("Неверный номер заказа", show_alert=True)

    with SessionLocal() as db:
        order = db.get(BookRequest, order_id)

        if not order:
            return await callback.answer("Заказ не найден", show_alert=True)

        if order.status != "pending":
            return await callback.answer(
                "Этот заказ уже обработан", show_alert=True
            )

        order.status = "accepted"

        save_order_notification(
            db,
            order,
            "✅ Ваш заказ принят!",
            (
                f"Заказ «{order.book_title}» принят. "
                "Мы сообщим вам, когда книга появится в библиотеке."
            ),
        )
        db.commit()

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=order_keyboard(order_id, "accepted")
        )

    await callback.answer("Заказ принят!")

    if callback.message:
        await callback.message.answer(
            f"✅ Заказ №{order_id} принят. "
            "После добавления книги нажмите «Выполнен заказ»."
        )


@router.callback_query(F.data.startswith("order:reject:"))
async def order_reject_callback(callback: CallbackQuery):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        return await callback.answer("Неверный номер заказа", show_alert=True)

    with SessionLocal() as db:
        order = db.get(BookRequest, order_id)

        if not order:
            return await callback.answer("Заказ не найден", show_alert=True)

        if order.status != "pending":
            return await callback.answer(
                "Этот заказ уже обработан", show_alert=True
            )

        order.status = "rejected"

        save_order_notification(
            db,
            order,
            "Заказ отклонён",
            f"К сожалению, заказ «{order.book_title}» не может быть выполнен.",
        )
        db.commit()

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"❌ Заказ №{order_id} отклонён."
        )

    await callback.answer("Заказ отклонён")


@router.callback_query(F.data.startswith("order:done:"))
async def order_done_callback(callback: CallbackQuery):
    try:
        order_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        return await callback.answer("Неверный номер заказа", show_alert=True)

    with SessionLocal() as db:
        order = db.get(BookRequest, order_id)

        if not order:
            return await callback.answer("Заказ не найден", show_alert=True)

        if order.status == "completed":
            return await callback.answer(
                "Этот заказ уже выполнен", show_alert=True
            )

        if order.status != "accepted":
            return await callback.answer(
                "Сначала прими заказ", show_alert=True
            )

        if not order.book_id:
            return await callback.answer(
                "Сначала добавь книгу на сайте и свяжи её с этим заказом.",
                show_alert=True,
            )

        book = db.get(Book, order.book_id)

        if not book:
            return await callback.answer(
                "Связанная книга не найдена", show_alert=True
            )

        order.status = "completed"

        save_order_notification(
            db,
            order,
            "📚 Ваша заказанная книга добавлена!",
            (
                f"Книга «{book.title}» появилась в My Library. "
                "Теперь вы можете начать чтение."
            ),
            book_id=book.id,
        )
        db.commit()

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"🎉 Заказ №{order_id} выполнен! "
            "Читателю отправлено уведомление."
        )

    await callback.answer("Заказ выполнен!")


# =========================
# ЗАПУСК БОТА
# =========================

def build_bot():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не указан в .env")

    if not ADMIN_ID:
        raise ValueError("ADMIN_ID не указан в .env")

    bot = Bot(token=BOT_TOKEN)

    dp = Dispatcher(
        storage=MemoryStorage()
    )

    dp.include_router(router)

    return bot, dp
