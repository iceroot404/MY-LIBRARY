
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
    UPLOADS_DIR,
    HOST,
    PORT,
)
from bot.database import SessionLocal, init_db
from bot.models import (
    Book,
    User,
    Favorite,
    ReadingProgress,
    Review,
    BookRequest,
    UserNotification,
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
        return db.get(User, int(user_id))


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
    https_only=False,
    max_age=60 * 60 * 24 * 14,
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "web" / "static"),
    name="static",
)


# =========================
# ГЛАВНАЯ СТРАНИЦА
# =========================

@app.get("/orders", response_class=HTMLResponse)
def orders_page(request: Request):
    return templates.TemplateResponse(
        "orders.html", {"request": request}
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = get_current_user(request)

    return templates.TemplateResponse(
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
):
    with SessionLocal() as db:
        query = db.query(Book)

        if category:
            query = query.filter(Book.category == category)

        books = query.order_by(Book.id.desc()).all()

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
    return templates.TemplateResponse(
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
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Это имя зарезервировано."},
            status_code=409,
        )

    if len(username) < 3 or len(username) > 40:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Имя должно содержать от 3 до 40 символов"},
            status_code=400,
        )

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Введите корректный email"},
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
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
            return templates.TemplateResponse(
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

    return templates.TemplateResponse(
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

        if not user or not verify_password(
            password,
            user.password_hash,
        ):
            return templates.TemplateResponse(
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
            .filter(Favorite.user_id == user.id)
            .order_by(Favorite.id.desc()).all()
        )
        progress_rows = (
            db.query(ReadingProgress, Book)
            .join(Book, Book.id == ReadingProgress.book_id)
            .filter(ReadingProgress.user_id == user.id)
            .order_by(ReadingProgress.updated_at.desc()).all()
        )
        review_rows = (
            db.query(Review, Book)
            .join(Book, Book.id == Review.book_id)
            .filter(Review.user_id == user.id)
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

    return templates.TemplateResponse(
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


# =========================
# ОНЛАЙН-ЧТЕНИЕ
# =========================

@app.get("/read/{book_id}", response_class=HTMLResponse)
def read_book(book_id: int, request: Request):
    with SessionLocal() as db:
        book = db.get(Book, book_id)

        if not book or not book.file:
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

        return templates.TemplateResponse(
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

        if not book or not book.file:
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
def change_order_status(
    order_id: int,
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
        if order.user_id:
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
        db.commit()

    return RedirectResponse("/admin#orders", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)

    with SessionLocal() as db:
        total = db.query(Book).count()
        categories = db.query(Book.category).distinct().count()
        books = (
            db.query(Book).order_by(Book.id.desc()).limit(100).all()
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

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "total": total,
            "categories": categories,
            "books": books,
            "orders": orders,
            "available_orders": available_orders,
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

        db.commit()

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
            for filename in (book.cover, book.file):
                if filename and Path(filename).name == filename:
                    (UPLOADS_DIR / filename).unlink(missing_ok=True)

            db.delete(book)
            db.commit()

    return RedirectResponse("/admin?deleted=1", status_code=303)


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
