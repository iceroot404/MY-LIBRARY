from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import func, desc

from bot.database import SessionLocal
from bot.models import (
    Book, User, Favorite, UserShelf, ReadingProgress, BookNote, ReadingGoal,
    UserCollection, CollectionBook, BookClub, ClubMember, ClubPost, BookReport,
    AdminAction,
)

router = APIRouter()


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, int(user_id))
        if not user or user.is_blocked:
            return None
        # Returning a detached object is safe: the session factory uses expire_on_commit=False.
        return user


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт.")
    return user


def require_admin(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(401, "Требуется вход администратора.")


def _book_payload(book: Book) -> dict[str, Any]:
    return book.to_dict()


def _audit(db, action: str, details: str = ""):
    db.add(AdminAction(action=action[:120], details=details[:2000]))


@router.get("/api/recommendations")
def recommendations(request: Request, limit: int = 12):
    user = current_user(request)
    limit = max(1, min(limit, 30))
    with SessionLocal() as db:
        query = db.query(Book).filter(Book.is_deleted.is_(False))
        seen_ids: set[int] = set()
        categories: list[str] = []
        if user:
            seen_ids.update(row[0] for row in db.query(Favorite.book_id).filter_by(user_id=user.id).all())
            shelves = db.query(UserShelf).filter_by(user_id=user.id).all()
            seen_ids.update(item.book_id for item in shelves)
            preferred = [item.book_id for item in shelves if item.status in {"reading", "read"}]
            if preferred:
                categories = [row[0] for row in db.query(Book.category).filter(Book.id.in_(preferred)).distinct().all() if row[0]]
        if categories:
            query = query.filter(Book.category.in_(categories))
        if seen_ids:
            query = query.filter(~Book.id.in_(seen_ids))
        books = query.order_by(Book.view_count.desc(), Book.id.desc()).limit(limit).all()
        if len(books) < limit:
            extra_query = db.query(Book).filter(Book.is_deleted.is_(False))
            if seen_ids:
                extra_query = extra_query.filter(~Book.id.in_(seen_ids))
            existing = {book.id for book in books}
            books += [b for b in extra_query.order_by(Book.id.desc()).limit(limit * 2).all() if b.id not in existing][:limit-len(books)]
        return {"items": [_book_payload(book) for book in books]}


@router.get("/api/book-of-day")
def book_of_day():
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.is_deleted.is_(False)).order_by(Book.id.asc()).all()
        if not books:
            return {"book": None, "date": datetime.utcnow().date().isoformat()}
        day_number = datetime.utcnow().date().toordinal()
        book = books[day_number % len(books)]
        return {"book": _book_payload(book), "date": datetime.utcnow().date().isoformat()}


@router.get("/api/books/compare")
def compare_books(ids: str):
    try:
        book_ids = list(dict.fromkeys(int(value) for value in ids.split(",") if value.strip()))
    except ValueError:
        raise HTTPException(400, "ID книг должны быть числами.")
    if not 2 <= len(book_ids) <= 4:
        raise HTTPException(400, "Для сравнения выберите от 2 до 4 книг.")
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.id.in_(book_ids), Book.is_deleted.is_(False)).all()
        return {"items": [_book_payload(book) for book in books]}


@router.get("/api/authors/{author}")
def author_books(author: str):
    from fastapi import Request
    from fastapi.responses import JSONResponse
    name = author.strip()[:255]
    with SessionLocal() as db:
        candidates = db.query(Book).filter(Book.is_deleted.is_(False)).order_by(Book.title.asc()).all()
        books = [book for book in candidates if book.author.casefold() == name.casefold()]
        if not books:
            raise HTTPException(404, "Книги этого автора не найдены.")
        return {"author": name, "books": [_book_payload(book) for book in books]}


@router.get("/api/notes/{book_id}")
def get_notes(book_id: int, request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        rows = db.query(BookNote).filter_by(user_id=user.id, book_id=book_id).order_by(BookNote.created_at.desc()).all()
        return {"items": [{"id": n.id, "content": n.content, "quote": n.quote, "location": n.location, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/api/notes/{book_id}")
async def add_note(book_id: int, request: Request):
    user = require_user(request)
    data = await request.json()
    content = str(data.get("content", "")).strip()[:5000]
    quote = str(data.get("quote", "")).strip()[:4000]
    location = str(data.get("location", "")).strip()[:2000]
    if len(content) < 1 and len(quote) < 1:
        raise HTTPException(400, "Добавьте текст заметки или цитату.")
    with SessionLocal() as db:
        if not db.query(Book.id).filter_by(id=book_id, is_deleted=False).first():
            raise HTTPException(404, "Книга не найдена.")
        note = BookNote(user_id=user.id, book_id=book_id, content=content or quote, quote=quote, location=location)
        db.add(note)
        db.commit()
        db.refresh(note)
        return {"ok": True, "id": note.id}


@router.delete("/api/notes/{note_id}")
def delete_note(note_id: int, request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        note = db.query(BookNote).filter_by(id=note_id, user_id=user.id).first()
        if note:
            db.delete(note)
            db.commit()
    return {"ok": True}


@router.get("/api/reading-goal")
def get_reading_goal(request: Request, year: int | None = None):
    user = require_user(request)
    year = year or datetime.utcnow().year
    with SessionLocal() as db:
        goal = db.query(ReadingGoal).filter_by(user_id=user.id, year=year).first()
        read_books = db.query(UserShelf).filter_by(user_id=user.id, status="read").count()
        minutes = db.query(func.coalesce(func.sum(ReadingProgress.minutes_read), 0)).filter_by(user_id=user.id).scalar()
        return {"year": year, "target_books": goal.target_books if goal else 12, "target_minutes": goal.target_minutes if goal else 0, "read_books": read_books, "minutes_read": int(minutes or 0)}


@router.post("/api/reading-goal")
async def set_reading_goal(request: Request):
    user = require_user(request)
    data = await request.json()
    year = int(data.get("year", datetime.utcnow().year))
    target_books = int(data.get("target_books", 12))
    target_minutes = int(data.get("target_minutes", 0))
    if not 2000 <= year <= 2200 or not 1 <= target_books <= 1000 or not 0 <= target_minutes <= 2_000_000:
        raise HTTPException(400, "Проверьте год и цели чтения.")
    with SessionLocal() as db:
        goal = db.query(ReadingGoal).filter_by(user_id=user.id, year=year).first()
        if not goal:
            goal = ReadingGoal(user_id=user.id, year=year)
            db.add(goal)
        goal.target_books = target_books
        goal.target_minutes = target_minutes
        db.commit()
    return {"ok": True}


@router.get("/api/reading-calendar")
def reading_calendar(request: Request, year: int | None = None):
    user = require_user(request)
    year = year or datetime.utcnow().year
    if not 2000 <= year <= 2200:
        raise HTTPException(400, "Некорректный год.")
    with SessionLocal() as db:
        rows = db.query(ReadingProgress.updated_at, ReadingProgress.minutes_read).filter(ReadingProgress.user_id == user.id, ReadingProgress.updated_at >= datetime(year, 1, 1), ReadingProgress.updated_at < datetime(year + 1, 1, 1)).all()
        days: dict[str, int] = {}
        for updated_at, minutes in rows:
            key = updated_at.date().isoformat()
            days[key] = days.get(key, 0) + int(minutes or 0)
        return {"year": year, "days": days}


@router.get("/api/collections")
def list_collections(request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        collections = db.query(UserCollection).filter_by(user_id=user.id).order_by(UserCollection.created_at.desc()).all()
        output = []
        for collection in collections:
            count = db.query(CollectionBook).filter_by(collection_id=collection.id).count()
            output.append({"id": collection.id, "title": collection.title, "description": collection.description, "is_shared": collection.is_shared, "share_code": collection.share_code, "count": count})
        return {"items": output}


@router.post("/api/collections")
async def create_collection(request: Request):
    user = require_user(request)
    data = await request.json()
    title = str(data.get("title", "")).strip()[:120]
    description = str(data.get("description", "")).strip()[:1000]
    is_shared = bool(data.get("is_shared", False))
    if len(title) < 2:
        raise HTTPException(400, "Название коллекции слишком короткое.")
    with SessionLocal() as db:
        collection = UserCollection(user_id=user.id, title=title, description=description, is_shared=is_shared, share_code=secrets.token_urlsafe(10) if is_shared else None)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        return {"ok": True, "id": collection.id, "share_code": collection.share_code}


@router.post("/api/collections/{collection_id}/books/{book_id}")
def add_collection_book(collection_id: int, book_id: int, request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        collection = db.query(UserCollection).filter_by(id=collection_id, user_id=user.id).first()
        book = db.query(Book).filter_by(id=book_id, is_deleted=False).first()
        if not collection or not book:
            raise HTTPException(404, "Коллекция или книга не найдена.")
        if not db.query(CollectionBook).filter_by(collection_id=collection_id, book_id=book_id).first():
            db.add(CollectionBook(collection_id=collection_id, book_id=book_id))
            db.commit()
    return {"ok": True}


@router.get("/api/collections/shared/{share_code}")
def shared_collection(share_code: str):
    with SessionLocal() as db:
        collection = db.query(UserCollection).filter_by(share_code=share_code, is_shared=True).first()
        if not collection:
            raise HTTPException(404, "Общая полка не найдена.")
        rows = db.query(Book).join(CollectionBook, CollectionBook.book_id == Book.id).filter(CollectionBook.collection_id == collection.id, Book.is_deleted.is_(False)).all()
        return {"title": collection.title, "description": collection.description, "books": [_book_payload(book) for book in rows]}


@router.get("/api/clubs")
def list_clubs(request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        clubs = db.query(BookClub).order_by(BookClub.created_at.desc()).limit(100).all()
        output = []
        for club in clubs:
            members = db.query(ClubMember).filter_by(club_id=club.id).count()
            joined = db.query(ClubMember).filter_by(club_id=club.id, user_id=user.id).first() is not None
            output.append({"id": club.id, "title": club.title, "description": club.description, "members": members, "joined": joined})
        return {"items": output}


@router.post("/api/clubs")
async def create_club(request: Request):
    user = require_user(request)
    data = await request.json()
    title = str(data.get("title", "")).strip()[:120]
    description = str(data.get("description", "")).strip()[:2000]
    if len(title) < 3:
        raise HTTPException(400, "Название клуба должно содержать минимум 3 символа.")
    with SessionLocal() as db:
        club = BookClub(owner_id=user.id, title=title, description=description)
        db.add(club)
        db.flush()
        db.add(ClubMember(club_id=club.id, user_id=user.id))
        db.commit()
        return {"ok": True, "id": club.id}


@router.post("/api/clubs/{club_id}/join")
def join_club(club_id: int, request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        club = db.get(BookClub, club_id)
        if not club:
            raise HTTPException(404, "Клуб не найден.")
        member = db.query(ClubMember).filter_by(club_id=club_id, user_id=user.id).first()
        if not member:
            db.add(ClubMember(club_id=club_id, user_id=user.id))
            db.commit()
    return {"ok": True}


@router.get("/api/clubs/{club_id}/posts")
def club_posts(club_id: int, request: Request):
    user = require_user(request)
    with SessionLocal() as db:
        if not db.query(ClubMember).filter_by(club_id=club_id, user_id=user.id).first():
            raise HTTPException(403, "Сначала вступите в клуб.")
        rows = db.query(ClubPost, User).join(User, User.id == ClubPost.user_id).filter(ClubPost.club_id == club_id).order_by(ClubPost.created_at.asc()).limit(200).all()
        return {"items": [{"id": post.id, "username": author.username, "content": post.content, "created_at": post.created_at.isoformat()} for post, author in rows]}


@router.post("/api/clubs/{club_id}/posts")
async def create_club_post(club_id: int, request: Request):
    user = require_user(request)
    data = await request.json()
    content = str(data.get("content", "")).strip()[:3000]
    if len(content) < 2:
        raise HTTPException(400, "Сообщение слишком короткое.")
    with SessionLocal() as db:
        if not db.query(ClubMember).filter_by(club_id=club_id, user_id=user.id).first():
            raise HTTPException(403, "Сначала вступите в клуб.")
        db.add(ClubPost(club_id=club_id, user_id=user.id, content=content))
        db.commit()
    return {"ok": True}


@router.post("/api/books/{book_id}/report")
async def report_book(book_id: int, request: Request):
    user = require_user(request)
    data = await request.json()
    reason = str(data.get("reason", "")).strip()[:500]
    if len(reason) < 3:
        raise HTTPException(400, "Опишите проблему с книгой.")
    with SessionLocal() as db:
        book = db.query(Book).filter_by(id=book_id, is_deleted=False).first()
        if not book:
            raise HTTPException(404, "Книга не найдена.")
        db.add(BookReport(book_id=book_id, user_id=user.id, reason=reason))
        db.commit()
    return {"ok": True}


@router.get("/api/telegram/link-code")
def create_telegram_link_code(request: Request):
    user = require_user(request)
    code = secrets.token_urlsafe(8)
    with SessionLocal() as db:
        db_user = db.get(User, user.id)
        db_user.telegram_link_code = code
        db.commit()
    return {"code": code, "command": f"/link {code}"}


@router.get("/api/admin/actions")
def admin_actions(request: Request):
    require_admin(request)
    with SessionLocal() as db:
        rows = db.query(AdminAction).order_by(AdminAction.created_at.desc()).limit(200).all()
        return {"items": [{"id": a.id, "action": a.action, "details": a.details, "created_at": a.created_at.isoformat()} for a in rows]}


@router.get("/api/admin/books/export.csv")
def export_books_csv(request: Request):
    require_admin(request)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "author", "category", "description", "cover", "file"])
    with SessionLocal() as db:
        for book in db.query(Book).filter(Book.is_deleted.is_(False)).order_by(Book.id.asc()).all():
            writer.writerow([book.title, book.author, book.category, book.description, book.cover or "", book.file or ""])
    raw = "\ufeff" + output.getvalue()
    return StreamingResponse(iter([raw]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=my-library-books.csv"})


@router.get("/api/admin/trash")
def admin_trash(request: Request):
    require_admin(request)
    with SessionLocal() as db:
        books = db.query(Book).filter(Book.is_deleted.is_(True)).order_by(Book.id.desc()).all()
        return {"items": [_book_payload(book) for book in books]}


@router.post("/api/admin/books/{book_id}/trash")
def move_book_to_trash(book_id: int, request: Request):
    require_admin(request)
    with SessionLocal() as db:
        book = db.get(Book, book_id)
        if not book:
            raise HTTPException(404, "Книга не найдена.")
        book.is_deleted = True
        _audit(db, "book_to_trash", f"book_id={book_id}; title={book.title}")
        db.commit()
    return {"ok": True}


@router.post("/api/admin/books/{book_id}/restore")
def restore_book(book_id: int, request: Request):
    require_admin(request)
    with SessionLocal() as db:
        book = db.get(Book, book_id)
        if not book:
            raise HTTPException(404, "Книга не найдена.")
        book.is_deleted = False
        _audit(db, "book_restore", f"book_id={book_id}; title={book.title}")
        db.commit()
    return {"ok": True}


@router.post("/api/admin/books/import.csv")
async def import_books_csv(request: Request, upload: UploadFile = File(...)):
    require_admin(request)
    raw = await upload.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV-файл больше 5 МБ.")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not {"title", "author"}.issubset(set(reader.fieldnames)):
            raise ValueError("В CSV обязательны столбцы title и author.")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise HTTPException(400, f"Не удалось прочитать CSV: {exc}")
    if len(rows) > 2000:
        raise HTTPException(400, "За один импорт можно добавить не более 2000 записей.")
    created = skipped = 0
    with SessionLocal() as db:
        for row in rows:
            title = str(row.get("title", "")).strip()[:255]
            author = str(row.get("author", "")).strip()[:255]
            if not title or not author:
                skipped += 1
                continue
            exists = db.query(Book.id).filter(func.lower(Book.title) == title.lower(), func.lower(Book.author) == author.lower()).first()
            if exists:
                skipped += 1
                continue
            db.add(Book(title=title, author=author, category=str(row.get("category") or "Разное")[:100], description=str(row.get("description") or "")[:12000], cover=None, file=None))
            created += 1
        _audit(db, "csv_import", f"created={created}; skipped={skipped}")
        db.commit()
    return {"ok": True, "created": created, "skipped": skipped}


@router.get("/api/admin/book-reports")
def admin_book_reports(request: Request):
    require_admin(request)
    with SessionLocal() as db:
        rows = db.query(BookReport, Book, User).join(Book, Book.id == BookReport.book_id).join(User, User.id == BookReport.user_id).filter(BookReport.status == "pending").order_by(BookReport.created_at.desc()).limit(100).all()
        return {"items": [{"id": report.id, "book_id": book.id, "book": book.title, "author": user.username, "reason": report.reason, "created_at": report.created_at.isoformat()} for report, book, user in rows]}


@router.post("/api/admin/book-reports/{report_id}/resolve")
def resolve_book_report(report_id: int, request: Request):
    require_admin(request)
    with SessionLocal() as db:
        report = db.get(BookReport, report_id)
        if report:
            report.status = "resolved"
            _audit(db, "book_report_resolved", f"report_id={report_id}")
            db.commit()
    return {"ok": True}
