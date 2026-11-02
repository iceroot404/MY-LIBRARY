
import asyncio
import hashlib
import hmac
import html
import re
import secrets

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy import func

from aiogram.exceptions import TelegramAPIError
from fastapi import (
    FastAPI,
    Request,
    Form,
    UploadFile,
    File,
    HTTPException,
    Depends,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    FileResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from bot.admin_bot import build_bot, order_keyboard
from bot.config import (
    BOT_TOKEN,
    ADMIN_ID,
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    SESSION_SECRET,
    COOKIE_SECURE,
    UPLOADS_DIR,
    HOST,
    PORT,
)
from bot.database import SessionLocal, init_db
from feature_routes import router as feature_router
from extended_routes import router as extended_feature_router
from bot.models import (
    Book,
    User,
    Favorite,
    ReadingProgress,
    Review,
    BookRequest,
    UserNotification,
    AdminAction,
    UserAppearance,
    SiteSetting,
)


BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=BASE_DIR / "web" / "templates"
)

ALLOWED_BOOK_EXTENSIONS = {
    ".pdf", ".epub", ".fb2", ".djvu", ".txt"
}

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp"
}

MAX_FILE_SIZE = 50 * 1024 * 1024


# =========================
# ПАРОЛИ
# =========================

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        260_000,
    ).hex()

    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, expected = stored_hash.split("$", 1)

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            260_000,
        ).hex()

        return hmac.compare_digest(actual, expected)

    except (ValueError, TypeError):
        return False


def get_current_user(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    with SessionLocal() as db:
        user = db.get(User, int(user_id))
        if not user or getattr(user, "is_blocked", False):
            return None
        return user


def require_user(request: Request):
    user = get_current_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Требуется авторизация",
        )

    return user


def require_admin(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(
            status_code=401,
            detail="Требуется вход администратора",
        )

    return True


# =========================
# ЗАГРУЗКА ФАЙЛОВ
# =========================

async def store_upload(
    upload: UploadFile,
    allowed_extensions: set[str],
):
    if not upload or not upload.filename:
        return None

    suffix = Path(upload.filename).suffix.lower()

    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Недопустимый формат файла",
        )

    content = await upload.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Файл больше 50 МБ",
        )

    filename = f"{uuid4().hex}{suffix}"
    destination = UPLOADS_DIR / filename
    destination.write_bytes(content)

    return filename


def safe_upload_path(filename: str):
    if not filename or Path(filename).name != filename:
        raise HTTPException(404, "Файл не найден")

    path = UPLOADS_DIR / filename

    if not path.is_file():
        raise HTTPException(404, "Файл не найден")

    return path


# =========================
# ПЕРСОНАЛИЗАЦИЯ И ФИРМЕННЫЙ СТИЛЬ
# =========================

DEFAULT_APPEARANCE = {
    "theme": "light", "accent_color": "#416d58", "background_mode": "plain",
    "background_image": None, "background_image_url": None,
    "font_family": "sans", "font_size": 16, "line_height": 1.8, "reading_width": "normal", "card_style": "classic",
    "avatar": None, "avatar_url": None, "profile_cover": None, "profile_cover_url": None,
}
DEFAULT_SITE_CONFIG = {
    "site_name": "MY LIBRARY",
    "hero_eyebrow": "ВАША КОЛЛЕКЦИЯ ЗНАНИЙ",
    "hero_title": "Истории, которые остаются с вами.",
    "hero_subtitle": "Откройте для себя следующую любимую книгу.",
    "accent_color": "#416d58",
    "logo_file": None, "logo_url": None,
    "favicon_file": None, "favicon_url": None,
    "hero_background_file": None, "hero_background_url": None,
}
ALLOWED_THEMES = {"light", "dark", "sepia"}
ALLOWED_BACKGROUNDS = {"plain", "paper", "gradient", "image"}
ALLOWED_FONTS = {"sans", "serif", "rounded"}
ALLOWED_CARD_STYLES = {"classic", "minimal", "glass"}
ALLOWED_READING_WIDTHS = {"narrow", "normal", "wide"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _upload_url(filename: str | None) -> str | None:
    return f"/static/uploads/{filename}" if filename else None


def get_site_config() -> dict:
    result = dict(DEFAULT_SITE_CONFIG)
    with SessionLocal() as db:
        for row in db.query(SiteSetting).all():
            if row.key in result:
                result[row.key] = row.value or None
    for file_key, url_key in (("logo_file", "logo_url"), ("favicon_file", "favicon_url"), ("hero_background_file", "hero_background_url")):
        result[url_key] = _upload_url(result.get(file_key))
    return result


def get_user_appearance(user_id: int | None) -> dict:
    result = dict(DEFAULT_APPEARANCE)
    result["accent_color"] = get_site_config().get("accent_color") or result["accent_color"]
    if user_id:
        with SessionLocal() as db:
            pref = db.query(UserAppearance).filter(UserAppearance.user_id == user_id).first()
            if pref:
                for key in ("theme", "accent_color", "background_mode", "background_image", "font_family", "font_size", "line_height", "reading_width", "card_style", "avatar", "profile_cover"):
                    result[key] = getattr(pref, key)
    result["background_image_url"] = _upload_url(result.get("background_image"))
    result["avatar_url"] = _upload_url(result.get("avatar"))
    result["profile_cover_url"] = _upload_url(result.get("profile_cover"))
    return result


def render_page(request: Request, template_name: str, context: dict | None = None, **kwargs):
    current_user = get_current_user(request)
    base_context = {
        "site_config": get_site_config(),
        "appearance": get_user_appearance(current_user.id if current_user else None),
        "current_user": current_user,
        "logged_in": current_user is not None,
    }
    if context:
        base_context.update(context)
    return templates.TemplateResponse(request, template_name, base_context, **kwargs)


def save_site_values(values: dict[str, str]) -> None:
    with SessionLocal() as db:
        for key, value in values.items():
            row = db.get(SiteSetting, key)
            if row is None:
                db.add(SiteSetting(key=key, value=value or ""))
            else:
                row.value = value or ""
        db.commit()


async def store_small_image(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(400, "Изображение должно быть JPG, PNG или WEBP")
    content = await upload.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Изображение больше 5 МБ")
    if not content:
        raise HTTPException(400, "Пустое изображение")
    filename = f"{uuid4().hex}{suffix}"
    (UPLOADS_DIR / filename).write_bytes(content)
    return filename


# =========================
# ЗАПУСК САЙТА И TELEGRAM
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    bot = None
    bot_task = None
    app.state.telegram_bot = None

    if BOT_TOKEN and ADMIN_ID:
        bot, dp = build_bot()
        app.state.telegram_bot = bot
        bot_task = asyncio.create_task(dp.start_polling(bot))
    else:
        print(
            "Telegram-бот не запущен: проверьте BOT_TOKEN и ADMIN_ID в .env"
        )

    yield

    if bot_task:
        bot_task.cancel()

        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        except TelegramAPIError:
            pass

    if bot:
        await bot.session.close()


app = FastAPI(
    title="My Library",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=COOKIE_SECURE,
    max_age=60 * 60 * 24 * 14,
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "web" / "static"),
    name="static",
)


@app.get("/sw.js")
def service_worker():
    return FileResponse(
        BASE_DIR / "web" / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )

app.include_router(feature_router)
app.include_router(extended_feature_router)


# =========================
# ГЛАВНАЯ СТРАНИЦА
# =========================

@app.get("/orders", response_class=HTMLResponse)
def orders_page(request: Request):
    return render_page(request, "orders.html")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = get_current_user(request)

    return render_page(
        request,
        "index.html",
        {
            "user": user,
            "logged_in": user is not None,
        },
    )



# =========================
# ЗАКАЗ КНИГИ
# =========================


@app.post("/api/book-requests")
async def create_book_request(
    request: Request,
    book_title: str = Form(...),
    author: str = Form(""),
    comment: str = Form(""),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Сначала войдите в личный кабинет.")

    book_title = book_title.strip()[:255]
    author = author.strip()[:255]
    comment = comment.strip()[:2000]

    if len(book_title) < 2:
        raise HTTPException(400, "Введите название книги")

    with SessionLocal() as db:
        order = BookRequest(
            user_id=user.id,
            book_title=book_title,
            author=author,
            customer_name=user.username,
            contact="",
            comment=comment,
            status="pending",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        order_id = order.id

    bot = getattr(request.app.state, "telegram_bot", None)
    notified = False

    if bot and ADMIN_ID:
        message = (
            f"📚 <b>Новый заказ №{order_id}</b>\n\n"
            f"<b>Книга:</b> {html.escape(book_title)}\n"
            f"<b>Автор:</b> {html.escape(author or 'Не указан')}\n"
            f"<b>Читатель:</b> {html.escape(user.username)}\n"
            f"<b>Email:</b> {html.escape(user.email)}\n"
            f"<b>Комментарий:</b> {html.escape(comment or 'Нет')}"
        )
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=message,
                parse_mode="HTML",
                reply_markup=order_keyboard(order_id),
            )
            notified = True
        except Exception as error:
            print("Ошибка Telegram:", error)

    return {"ok": True, "id": order_id, "notified": notified}

@app.get("/api/books")
def api_books(
    request: Request,
    q: str = "",
    category: str = "",
    sort: str = "newest",
):
    with SessionLocal() as db:
        query = db.query(Book).filter(Book.is_deleted.is_(False))

        if category:
            query = query.filter(Book.category == category)

        if sort == "popular":
            query = query.order_by(Book.view_count.desc(), Book.id.desc())
        elif sort == "title":
            query = query.order_by(Book.title.asc())
        elif sort == "author":
            query = query.order_by(Book.author.asc(), Book.title.asc())
        else:
            query = query.order_by(Book.created_at.desc(), Book.id.desc())
        books = query.all()

        categories = sorted({
            item[0]
            for item in db.query(Book.category).distinct().all()
            if item[0]
        })

        search = q.strip().lower()

        if search:
            books = [
                book for book in books
                if search in book.title.lower()
                or search in book.author.lower()
                or search in book.category.lower()
            ]

        user_id = request.session.get("user_id")

        favorite_ids = set()

        if user_id:
            favorite_ids = {
                row[0]
                for row in db.query(Favorite.book_id)
                .filter(Favorite.user_id == int(user_id))
                .all()
            }

        result = []

        for book in books:
            item = book.to_dict()
            item["is_favorite"] = book.id in favorite_ids
            result.append(item)

        return {
            "books": result,
            "categories": categories,
        }


@app.get("/api/popular")
def popular_books():
    with SessionLocal() as db:
        books = (
            db.query(Book)
            .filter(Book.is_deleted.is_(False))
            .order_by(Book.view_count.desc(), Book.id.desc())
            .limit(12)
            .all()
        )

        return {
            "books": [book.to_dict() for book in books]
        }


# =========================
# РЕГИСТРАЦИЯ
# =========================

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render_page(
        request,
        "register.html",
        {"error": ""},
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    username = username.strip()
    email = email.strip().lower()

    # ADMIN_LOGIN_RESERVED
    if ADMIN_LOGIN and (
        username.casefold() == ADMIN_LOGIN.casefold()
        or email.casefold() == ADMIN_LOGIN.casefold()
    ):
        return render_page(
            request,
            "register.html",
            {"error": "Это имя зарезервировано."},
            status_code=409,
        )

    if len(username) < 3 or len(username) > 40:
        return render_page(
            request,
            "register.html",
            {"error": "Имя должно содержать от 3 до 40 символов"},
            status_code=400,
        )

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return render_page(
            request,
            "register.html",
            {"error": "Введите корректный email"},
            status_code=400,
        )

    if len(password) < 8:
        return render_page(
            request,
            "register.html",
            {"error": "Пароль должен содержать минимум 8 символов"},
            status_code=400,
        )

    with SessionLocal() as db:
        exists = (
            db.query(User)
            .filter(
                (User.username == username)
                | (User.email == email)
            )
            .first()
        )

        if exists:
            return render_page(
                request,
                "register.html",
                {"error": "Такой пользователь или email уже существует"},
                status_code=409,
            )

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        request.session.clear()
        request.session["user_id"] = user.id

    return RedirectResponse("/profile", status_code=303)


# =========================
# ВХОД ЧИТАТЕЛЯ
# =========================

@app.get("/login", response_class=HTMLResponse)
def user_login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/admin", status_code=303)

    if get_current_user(request):
        return RedirectResponse("/profile", status_code=303)

    return render_page(
        request,
        "user_login.html",
        {"error": ""},
    )


@app.post("/login")
def user_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    login_value = email.strip()

    # Вход администратора
    if (
        ADMIN_LOGIN
        and ADMIN_PASSWORD
        and ADMIN_PASSWORD != "change-this-admin-password"
        and hmac.compare_digest(
            login_value.casefold(),
            ADMIN_LOGIN.casefold(),
        )
        and hmac.compare_digest(password, ADMIN_PASSWORD)
    ):
        request.session.clear()
        request.session["admin"] = True
        request.session["admin_login"] = ADMIN_LOGIN
        return RedirectResponse("/admin", status_code=303)

    # Вход обычного читателя
    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter(User.email == login_value.lower())
            .first()
        )

        if user and getattr(user, "is_blocked", False):
            return render_page(
                request, "user_login.html",
                {"error": "Ваш аккаунт временно заблокирован. Обратитесь к администрации."},
                status_code=403,
            )

        if not user or not verify_password(
            password,
            user.password_hash,
        ):
            return render_page(
                request,
                "user_login.html",
                {"error": "Неверный логин или пароль"},
                status_code=401,
            )

        request.session.clear()
        request.session["user_id"] = user.id

    return RedirectResponse("/profile", status_code=303)


@app.get("/logout")
def user_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# =========================
# ЛИЧНЫЙ КАБИНЕТ
# =========================


@app.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        item = db.query(UserNotification).filter(
            UserNotification.id == notification_id,
            UserNotification.user_id == user.id,
        ).first()
        if item:
            item.is_read = 1
            db.commit()

    return RedirectResponse("/profile", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        favorite_rows = (
            db.query(Book)
            .join(Favorite, Favorite.book_id == Book.id)
            .filter(Favorite.user_id == user.id, Book.is_deleted.is_(False))
            .order_by(Favorite.id.desc()).all()
        )
        progress_rows = (
            db.query(ReadingProgress, Book)
            .join(Book, Book.id == ReadingProgress.book_id)
            .filter(ReadingProgress.user_id == user.id, Book.is_deleted.is_(False))
            .order_by(ReadingProgress.updated_at.desc()).all()
        )
        review_rows = (
            db.query(Review, Book)
            .join(Book, Book.id == Review.book_id)
            .filter(Review.user_id == user.id, Book.is_deleted.is_(False))
            .order_by(Review.updated_at.desc()).all()
        )

        favorites = [book.to_dict() for book in favorite_rows]
        progress = [
            {
                "book": book.to_dict(),
                "percent": round(item.percent, 1),
                "location": item.location,
            }
            for item, book in progress_rows
        ]
        reviews = [
            {
                "book_title": book.title,
                "rating": item.rating,
                "text": item.text,
            }
            for item, book in review_rows
        ]
        notifications = (
            db.query(UserNotification)
            .filter(UserNotification.user_id == user.id)
            .order_by(UserNotification.created_at.desc())
            .limit(50).all()
        )
        unread_notifications = (
            db.query(UserNotification)
            .filter(
                UserNotification.user_id == user.id,
                UserNotification.is_read == 0,
            ).count()
        )

    return render_page(
        request,
        "profile.html",
        {
            "user": user,
            "favorites": favorites,
            "progress": progress,
            "reviews": reviews,
            "notifications": notifications,
            "unread_notifications": unread_notifications,
        },
    )

@app.get("/api/favorites")
def get_favorites(user: User = Depends(require_user)):
    with SessionLocal() as db:
        books = (
            db.query(Book)
            .join(Favorite, Favorite.book_id == Book.id)
            .filter(Favorite.user_id == user.id)
            .order_by(Favorite.id.desc())
            .all()
        )

        return {
            "books": [book.to_dict() for book in books]
        }


@app.post("/api/favorites/{book_id}")
def add_favorite(
    book_id: int,
    user: User = Depends(require_user),
):
    with SessionLocal() as db:
        book = db.get(Book, book_id)

        if not book:
            raise HTTPException(404, "Книга не найдена")

        favorite = (
            db.query(Favorite)
            .filter(
                Favorite.user_id == user.id,
                Favorite.book_id == book_id,
            )
            .first()
        )

        if not favorite:
            db.add(
                Favorite(
                    user_id=user.id,
                    book_id=book_id,
                )
            )
            db.commit()

    return {"ok": True, "is_favorite": True}


@app.delete("/api/favorites/{book_id}")
def remove_favorite(
    book_id: int,
    user: User = Depends(require_user),
):
    with SessionLocal() as db:
        favorite = (
            db.query(Favorite)
            .filter(
                Favorite.user_id == user.id,
                Favorite.book_id == book_id,
            )
            .first()
        )

        if favorite:
            db.delete(favorite)
            db.commit()

    return {"ok": True, "is_favorite": False}


@app.get("/authors/{author}", response_class=HTMLResponse)
def author_page(author: str, request: Request):
    name = author.strip()[:255]
    with SessionLocal() as db:
        candidates = db.query(Book).filter(
            Book.is_deleted.is_(False),
        ).order_by(Book.title.asc()).all()
        books = [book for book in candidates if book.author.casefold() == name.casefold()]
        if not books:
            raise HTTPException(404, "Книги этого автора не найдены")
        return render_page(
            request, "author.html",
            {"author": name, "books": [book.to_dict() for book in books]},
        )


# =========================
# ОНЛАЙН-ЧТЕНИЕ
# =========================

@app.get("/read/{book_id}", response_class=HTMLResponse)
def read_book(book_id: int, request: Request):
    with SessionLocal() as db:
        book = db.get(Book, book_id)

        if not book or book.is_deleted or not book.file:
            raise HTTPException(404, "Файл книги не найден")

        extension = Path(book.file).suffix.lower().lstrip(".")

        if extension not in {"pdf", "epub", "txt"}:
            raise HTTPException(
                415,
                "Этот формат можно скачать, но браузер не поддерживает его чтение",
            )

        safe_upload_path(book.file)

        book.view_count += 1
        db.commit()

        return render_page(
            request,
            "reader.html",
            {
                "book": book,
                "file_format": extension,
                "file_url": f"/static/uploads/{book.file}",
                "logged_in": bool(request.session.get("user_id")),
            },
        )


@app.get("/download/{book_id}")
def download_book(book_id: int):
    with SessionLocal() as db:
        book = db.get(Book, book_id)

        if not book or book.is_deleted or not book.file:
            raise HTTPException(404, "Файл книги не найден")

        path = safe_upload_path(book.file)
        book.download_count += 1
        db.commit()

        return FileResponse(
            path,
            filename=path.name,
            media_type="application/octet-stream",
        )


# =========================
# ПРОГРЕСС ЧТЕНИЯ
# =========================

@app.get("/api/reading-progress/{book_id}")
def get_progress(
    book_id: int,
    user: User = Depends(require_user),
):
    with SessionLocal() as db:
        item = (
            db.query(ReadingProgress)
            .filter(
                ReadingProgress.user_id == user.id,
                ReadingProgress.book_id == book_id,
            )
            .first()
        )

        if not item:
            return {
                "location": "",
                "percent": 0,
            }

        return {
            "location": item.location,
            "percent": item.percent,
        }


@app.post("/api/reading-progress/{book_id}")
async def save_progress(
    book_id: int,
    request: Request,
    user: User = Depends(require_user),
):
    data = await request.json()

    location = str(data.get("location", ""))[:2000]

    try:
        percent = float(data.get("percent", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Некорректный процент")

    percent = max(0, min(100, percent))

    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена")

        item = (
            db.query(ReadingProgress)
            .filter(
                ReadingProgress.user_id == user.id,
                ReadingProgress.book_id == book_id,
            )
            .first()
        )

        if not item:
            item = ReadingProgress(
                user_id=user.id,
                book_id=book_id,
            )
            db.add(item)

        item.location = location
        item.percent = percent
        db.commit()

    return {"ok": True}


# =========================
# ОЦЕНКИ И ОТЗЫВЫ
# =========================

@app.get("/api/reviews/{book_id}")
def get_reviews(book_id: int):
    with SessionLocal() as db:
        rows = (
            db.query(Review, User)
            .join(User, User.id == Review.user_id)
            .filter(Review.book_id == book_id)
            .order_by(Review.created_at.desc())
            .limit(50)
            .all()
        )

        return {
            "reviews": [
                {
                    "username": user.username,
                    "rating": review.rating,
                    "text": review.text,
                    "created_at": review.created_at.isoformat(),
                }
                for review, user in rows
            ]
        }


@app.post("/api/reviews/{book_id}")
async def create_review(
    book_id: int,
    request: Request,
    user: User = Depends(require_user),
):
    data = await request.json()

    try:
        rating = int(data.get("rating"))
    except (ValueError, TypeError):
        raise HTTPException(400, "Оценка должна быть от 1 до 5")

    if rating < 1 or rating > 5:
        raise HTTPException(400, "Оценка должна быть от 1 до 5")

    review_text = str(data.get("text", "")).strip()[:3000]

    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена")

        review = (
            db.query(Review)
            .filter(
                Review.user_id == user.id,
                Review.book_id == book_id,
            )
            .first()
        )

        if not review:
            review = Review(
                user_id=user.id,
                book_id=book_id,
            )
            db.add(review)

        review.rating = rating
        review.text = review_text
        db.commit()

    return {"ok": True}


# =========================
# АДМИН-ПАНЕЛЬ
# =========================

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return RedirectResponse("/login", status_code=303)


@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)):
    return RedirectResponse("/login", status_code=303)


@app.post("/admin/logout")
def admin_logout(
    request: Request,
    _: bool = Depends(require_admin),
):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)



@app.post("/admin/orders/{order_id}/status")
async def change_order_status(
    order_id: int,
    request: Request,
    status: str = Form(...),
    _: bool = Depends(require_admin),
):
    if status not in ("accepted", "rejected"):
        raise HTTPException(400, "Неверный статус")

    with SessionLocal() as db:
        order = db.get(BookRequest, order_id)
        if not order:
            raise HTTPException(404, "Заказ не найден")
        if order.status != "pending":
            raise HTTPException(400, "Заказ уже обработан")

        order.status = status
        telegram_id = None
        if order.user_id:
            linked_user = db.get(User, order.user_id)
            telegram_id = linked_user.telegram_id if linked_user else None
            if status == "accepted":
                title = "Ваш заказ принят!"
                message = (
                    f"Заказ «{order.book_title}» принят. "
                    "Мы сообщим, когда книга появится в библиотеке."
                )
            else:
                title = "Заказ отклонён"
                message = f"К сожалению, заказ «{order.book_title}» отклонён."

            db.add(UserNotification(
                user_id=order.user_id,
                title=title,
                message=message,
            ))
        db.add(AdminAction(action="order_status", details=f"order_id={order_id}; status={status}"))
        db.commit()

    bot = getattr(request.app.state, "telegram_bot", None)
    if bot and telegram_id:
        try:
            await bot.send_message(telegram_id, message)
        except Exception as error:
            print("Не удалось отправить уведомление читателю в Telegram:", error)

    return RedirectResponse("/admin#orders", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)

    with SessionLocal() as db:
        total = db.query(Book).filter(Book.is_deleted.is_(False)).count()
        categories = db.query(Book.category).distinct().count()
        total_users = db.query(User).count()
        blocked_users = db.query(User).filter(User.is_blocked.is_(True)).count()
        total_views = db.query(func.coalesce(func.sum(Book.view_count), 0)).filter(Book.is_deleted.is_(False)).scalar()
        total_downloads = db.query(func.coalesce(func.sum(Book.download_count), 0)).filter(Book.is_deleted.is_(False)).scalar()
        books = (
            db.query(Book).filter(Book.is_deleted.is_(False)).order_by(Book.id.desc()).limit(100).all()
        )
        rows = (
            db.query(BookRequest, User)
            .outerjoin(User, BookRequest.user_id == User.id)
            .order_by(BookRequest.id.desc()).limit(100).all()
        )
        orders = [
            {
                "id": o.id,
                "book_title": o.book_title,
                "author": o.author,
                "customer_name": o.customer_name,
                "username": u.username if u else "Старый заказ",
                "email": u.email if u else "",
                "comment": o.comment,
                "status": o.status,
                "created_at": o.created_at,
            }
            for o, u in rows
        ]
        available_orders = (
            db.query(BookRequest)
            .filter(
                BookRequest.status == "accepted",
                BookRequest.user_id.isnot(None),
                BookRequest.book_id.is_(None),
            )
            .order_by(BookRequest.id.desc()).all()
        )

    return render_page(
        request,
        "admin.html",
        {
            "total": total,
            "categories": categories,
            "books": books,
            "orders": orders,
            "available_orders": available_orders,
            "total_users": total_users,
            "blocked_users": blocked_users,
            "total_views": total_views,
            "total_downloads": total_downloads,
        },
    )


@app.post("/admin/books")
async def admin_create_book(
    request: Request,
    _: bool = Depends(require_admin),
    title: str = Form(...),
    author: str = Form(...),
    category: str = Form("Разное"),
    description: str = Form(""),
    cover: UploadFile | None = File(None),
    book_file: UploadFile | None = File(None),
    order_id: str = Form(""),
):
    title = title.strip()
    author = author.strip()
    if not title or not author:
        raise HTTPException(400, "Название и автор обязательны")

    cover_name = (
        await store_upload(cover, ALLOWED_IMAGE_EXTENSIONS)
        if cover and cover.filename else None
    )
    book_name = (
        await store_upload(book_file, ALLOWED_BOOK_EXTENSIONS)
        if book_file and book_file.filename else None
    )

    telegram_notice = None
    telegram_user_id = None
    with SessionLocal() as db:
        linked_order = None
        if order_id.strip():
            try:
                selected_id = int(order_id)
            except ValueError:
                raise HTTPException(400, "Неверный номер заказа")

            linked_order = db.query(BookRequest).filter(
                BookRequest.id == selected_id,
                BookRequest.status == "accepted",
                BookRequest.user_id.isnot(None),
            ).first()
            if not linked_order:
                raise HTTPException(400, "Принятый заказ не найден")

        book = Book(
            title=title[:255],
            author=author[:255],
            category=category.strip()[:100] or "Разное",
            description=description.strip(),
            cover=cover_name,
            file=book_name,
        )
        db.add(book)
        db.flush()

        if linked_order:
            linked_order.book_id = book.id
            linked_order.status = "completed"
            if linked_order.user_id:
                db.add(UserNotification(
                    user_id=linked_order.user_id,
                    title="Запрошенная книга добавлена",
                    message=f"Книга «{book.title}» теперь доступна в My Library.",
                    book_id=book.id,
                ))
                linked_user = db.get(User, linked_order.user_id)
                telegram_user_id = linked_user.telegram_id if linked_user else None
                telegram_notice = f"📚 Книга «{book.title}» добавлена в My Library!"

        db.add(AdminAction(action="book_created", details=f"book_id={book.id}; title={book.title}"))
        db.commit()

    bot = getattr(request.app.state, "telegram_bot", None)
    if bot and telegram_user_id and telegram_notice:
        try:
            await bot.send_message(telegram_user_id, telegram_notice)
        except Exception as error:
            print("Не удалось отправить Telegram-уведомление о добавлении книги:", error)

    return RedirectResponse("/admin?created=1#orders", status_code=303)

@app.post("/admin/books/{book_id}/delete")
def admin_delete_book(
    book_id: int,
    request: Request,
    _: bool = Depends(require_admin),
):
    with SessionLocal() as db:
        book = db.get(Book, book_id)

        if book:
            book.is_deleted = True
            db.add(AdminAction(action="book_to_trash", details=f"book_id={book_id}; title={book.title}"))
            db.commit()

    return RedirectResponse("/admin?deleted=1", status_code=303)


# =========================
# НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# =========================

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render_page(request, "settings.html", {"user": user})


@app.post("/settings/appearance")
async def save_appearance(
    request: Request,
    theme: str = Form("light"),
    accent_color: str = Form("#416d58"),
    background_mode: str = Form("plain"),
    font_family: str = Form("sans"),
    font_size: int = Form(16),
    line_height: float = Form(1.8),
    reading_width: str = Form("normal"),
    card_style: str = Form("classic"),
    background_image: UploadFile | None = File(None),
    remove_background: str = Form(""),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт")
    if theme not in ALLOWED_THEMES or background_mode not in ALLOWED_BACKGROUNDS or font_family not in ALLOWED_FONTS or card_style not in ALLOWED_CARD_STYLES or reading_width not in ALLOWED_READING_WIDTHS:
        raise HTTPException(400, "Некорректная настройка оформления")
    if not COLOR_RE.fullmatch(accent_color):
        raise HTTPException(400, "Некорректный цвет акцента")
    font_size = max(14, min(22, int(font_size)))
    line_height = max(1.3, min(2.2, float(line_height)))
    new_image = await store_small_image(background_image)
    with SessionLocal() as db:
        pref = db.query(UserAppearance).filter_by(user_id=user.id).first()
        if pref is None:
            pref = UserAppearance(user_id=user.id)
            db.add(pref)
        old_image = pref.background_image
        if background_mode == "image" and not new_image and not old_image and remove_background != "1":
            raise HTTPException(400, "Сначала загрузите фоновую картинку")
        pref.theme = theme
        pref.accent_color = accent_color.lower()
        pref.background_mode = background_mode
        pref.font_family = font_family
        pref.font_size = font_size
        pref.line_height = line_height
        pref.reading_width = reading_width
        pref.card_style = card_style
        if new_image:
            pref.background_image = new_image
        if remove_background == "1":
            pref.background_image = None
            if background_mode == "image":
                pref.background_mode = "plain"
        db.commit()
    if old_image and (new_image or remove_background == "1"):
        (UPLOADS_DIR / old_image).unlink(missing_ok=True)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/profile")
async def save_profile_visuals(
    request: Request,
    avatar: UploadFile | None = File(None),
    profile_cover: UploadFile | None = File(None),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт")
    avatar_name = await store_small_image(avatar)
    cover_name = await store_small_image(profile_cover)
    with SessionLocal() as db:
        pref = db.query(UserAppearance).filter_by(user_id=user.id).first()
        if pref is None:
            pref = UserAppearance(user_id=user.id)
            db.add(pref)
        old_avatar, old_cover = pref.avatar, pref.profile_cover
        if avatar_name:
            pref.avatar = avatar_name
        if cover_name:
            pref.profile_cover = cover_name
        db.commit()
    if avatar_name and old_avatar:
        (UPLOADS_DIR / old_avatar).unlink(missing_ok=True)
    if cover_name and old_cover:
        (UPLOADS_DIR / old_cover).unlink(missing_ok=True)
    return RedirectResponse("/settings?saved=1#profile-visuals", status_code=303)


@app.post("/api/preferences/appearance")
async def update_appearance_api(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(400, "Ожидался объект настроек")
    updates = {}
    if "theme" in data:
        if not isinstance(data["theme"], str) or data["theme"] not in ALLOWED_THEMES:
            raise HTTPException(400, "Неизвестная тема")
        updates["theme"] = data["theme"]
    if "accent_color" in data:
        if not isinstance(data["accent_color"], str) or not COLOR_RE.fullmatch(data["accent_color"]):
            raise HTTPException(400, "Некорректный цвет")
        updates["accent_color"] = data["accent_color"].lower()
    if "background_mode" in data:
        if not isinstance(data["background_mode"], str) or data["background_mode"] not in ALLOWED_BACKGROUNDS:
            raise HTTPException(400, "Неизвестный тип фона")
        updates["background_mode"] = data["background_mode"]
    if "font_family" in data:
        if not isinstance(data["font_family"], str) or data["font_family"] not in ALLOWED_FONTS:
            raise HTTPException(400, "Неизвестный шрифт")
        updates["font_family"] = data["font_family"]
    if "font_size" in data:
        try:
            updates["font_size"] = max(14, min(22, int(data["font_size"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный размер текста")
    if "line_height" in data:
        try:
            updates["line_height"] = max(1.3, min(2.2, float(data["line_height"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный межстрочный интервал")
    if "reading_width" in data:
        if not isinstance(data["reading_width"], str) or data["reading_width"] not in ALLOWED_READING_WIDTHS:
            raise HTTPException(400, "Некорректная ширина текста")
        updates["reading_width"] = data["reading_width"]
    if "card_style" in data:
        if not isinstance(data["card_style"], str) or data["card_style"] not in ALLOWED_CARD_STYLES:
            raise HTTPException(400, "Неизвестный стиль карточек")
        updates["card_style"] = data["card_style"]
    with SessionLocal() as db:
        pref = db.query(UserAppearance).filter_by(user_id=user.id).first()
        if pref is None:
            pref = UserAppearance(user_id=user.id)
            db.add(pref)
        for key, value in updates.items():
            setattr(pref, key, value)
        db.commit()
    return {"ok": True}


# =========================
# ГЛОБАЛЬНЫЙ ДИЗАЙН (АДМИНИСТРАТОР)
# =========================

@app.post("/admin/design")
async def save_admin_design(
    _: bool = Depends(require_admin),
    site_name: str = Form("MY LIBRARY"),
    hero_eyebrow: str = Form("ВАША КОЛЛЕКЦИЯ ЗНАНИЙ"),
    hero_title: str = Form("Истории, которые остаются с вами."),
    hero_subtitle: str = Form("Откройте для себя следующую любимую книгу."),
    accent_color: str = Form("#416d58"),
    logo: UploadFile | None = File(None),
    favicon: UploadFile | None = File(None),
    hero_background: UploadFile | None = File(None),
    remove_logo: str = Form(""),
    remove_favicon: str = Form(""),
    remove_hero_background: str = Form(""),
):
    if not COLOR_RE.fullmatch(accent_color):
        raise HTTPException(400, "Некорректный фирменный цвет")
    uploads = {
        "logo_file": await store_small_image(logo),
        "favicon_file": await store_small_image(favicon),
        "hero_background_file": await store_small_image(hero_background),
    }
    values = {
        "site_name": site_name.strip()[:80] or "MY LIBRARY",
        "hero_eyebrow": hero_eyebrow.strip()[:120],
        "hero_title": hero_title.strip()[:180],
        "hero_subtitle": hero_subtitle.strip()[:240],
        "accent_color": accent_color.lower(),
    }
    values.update({key: value for key, value in uploads.items() if value})
    for flag, key in ((remove_logo, "logo_file"), (remove_favicon, "favicon_file"), (remove_hero_background, "hero_background_file")):
        if flag == "1":
            values[key] = ""
    previous = get_site_config()
    save_site_values(values)
    for flag, key in ((remove_logo, "logo_file"), (remove_favicon, "favicon_file"), (remove_hero_background, "hero_background_file")):
        if flag == "1" and previous.get(key):
            (UPLOADS_DIR / Path(previous[key]).name).unlink(missing_ok=True)
    return RedirectResponse("/admin?design_saved=1#design", status_code=303)


# Информационные страницы для публичного запуска. Контактные данные и юридические реквизиты
# владельцу нужно заполнить перед публикацией.
@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return render_page(request, "info.html", {"page_title": "Помощь", "page_eyebrow": "ПОДДЕРЖКА", "content": [
        ("Как читать книги?", "Откройте каталог, выберите книгу и нажмите «Читать». Для поддерживаемых форматов откроется читалка."),
        ("Как настроить сайт под себя?", "Войдите в аккаунт и откройте раздел «Моё оформление»: там можно выбрать тему, цвет, фон, шрифт, размер текста и вид карточек."),
        ("Как заказать книгу?", "Если нужной книги нет, отправьте заявку через раздел «Стол заказов»."),
    ]})

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return render_page(request, "info.html", {"page_title": "Политика конфиденциальности", "page_eyebrow": "ВАШИ ДАННЫЕ", "content": [
        ("Какие данные сохраняются?", "Для аккаунта сохраняются имя пользователя, email, хеш пароля, избранное, прогресс чтения и действия, необходимые для работы функций сайта."),
        ("Для чего используются данные?", "Данные используются для входа, персонализации, сохранения прогресса и работы функций, которые выбрал пользователь."),
        ("Запросы на удаление данных", "Перед публичным запуском владелец должен указать рабочий контакт для запросов об удалении аккаунта и персональных данных."),
    ]})

@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return render_page(request, "info.html", {"page_title": "Пользовательское соглашение", "page_eyebrow": "ПРАВИЛА БИБЛИОТЕКИ", "content": [
        ("Использование сервиса", "Пользователь обязуется соблюдать законодательство и не пытаться получить несанкционированный доступ к сайту."),
        ("Авторские права", "Администратор должен размещать только книги и материалы, распространение которых разрешено правообладателем или законом."),
        ("Аккаунт и модерация", "Пользователь отвечает за сохранность пароля. Администрация вправе ограничивать доступ при нарушении правил."),
    ]})

@app.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request):
    return render_page(request, "info.html", {"page_title": "Контакты", "page_eyebrow": "СВЯЗАТЬСЯ С НАМИ", "content": [
        ("Заказ книг", "Воспользуйтесь разделом «Стол заказов», чтобы запросить книгу."),
        ("Поддержка и правообладатели", "До публикации укажите здесь настоящий email или почтовый адрес поддержки и контакт для вопросов авторских прав."),
    ]})


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
    )
