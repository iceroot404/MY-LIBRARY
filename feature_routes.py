from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import func, desc

from bot.database import SessionLocal
from bot.models import (
    Book, User, BookRequest, ReadingProgress, UserShelf, ReaderBookmark,
    BookDiscussion, DiscussionLike, DiscussionReport, Review,
)

router = APIRouter()


def _user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, int(user_id))
        if not user or getattr(user, "is_blocked", False):
            return None
        return user


def _require_user(request: Request):
    user = _user(request)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт, чтобы использовать эту функцию.")
    return user


def _require_admin(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(401, "Требуется вход администратора.")


@router.get("/api/shelves")
def get_shelves(request: Request):
    user = _require_user(request)
    with SessionLocal() as db:
        rows = (
            db.query(UserShelf, Book)
            .join(Book, Book.id == UserShelf.book_id)
            .filter(UserShelf.user_id == user.id)
            .order_by(UserShelf.updated_at.desc())
            .all()
        )
        return {"items": [{"status": shelf.status, "book": book.to_dict()} for shelf, book in rows]}


@router.post("/api/shelves/{book_id}")
async def set_shelf(book_id: int, request: Request):
    user = _require_user(request)
    data = await request.json()
    status = str(data.get("status", "want"))
    if status not in {"want", "reading", "read"}:
        raise HTTPException(400, "Неизвестная книжная полка.")
    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена.")
        item = db.query(UserShelf).filter_by(user_id=user.id, book_id=book_id).first()
        if item is None:
            item = UserShelf(user_id=user.id, book_id=book_id, status=status)
            db.add(item)
        else:
            item.status = status
            item.updated_at = datetime.utcnow()
        db.commit()
    return {"ok": True, "status": status}


@router.delete("/api/shelves/{book_id}")
def remove_shelf(book_id: int, request: Request):
    user = _require_user(request)
    with SessionLocal() as db:
        item = db.query(UserShelf).filter_by(user_id=user.id, book_id=book_id).first()
        if item:
            db.delete(item)
            db.commit()
    return {"ok": True}


@router.get("/api/bookmarks/{book_id}")
def get_bookmarks(book_id: int, request: Request):
    user = _require_user(request)
    with SessionLocal() as db:
        rows = db.query(ReaderBookmark).filter_by(user_id=user.id, book_id=book_id).order_by(ReaderBookmark.created_at.desc()).all()
        return {"items": [{"id": x.id, "location": x.location, "label": x.label, "created_at": x.created_at.isoformat()} for x in rows]}


@router.post("/api/bookmarks/{book_id}")
async def add_bookmark(book_id: int, request: Request):
    user = _require_user(request)
    data = await request.json()
    location = str(data.get("location", "")).strip()[:2000]
    label = str(data.get("label", "Закладка")).strip()[:160] or "Закладка"
    if not location:
        raise HTTPException(400, "Не удалось определить место чтения.")
    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена.")
        item = ReaderBookmark(user_id=user.id, book_id=book_id, location=location, label=label)
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"ok": True, "id": item.id}


@router.delete("/api/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: int, request: Request):
    user = _require_user(request)
    with SessionLocal() as db:
        item = db.query(ReaderBookmark).filter_by(id=bookmark_id, user_id=user.id).first()
        if item:
            db.delete(item)
            db.commit()
    return {"ok": True}


@router.post("/api/reading-session/{book_id}")
async def add_reading_minute(book_id: int, request: Request):
    user = _require_user(request)
    data = await request.json()
    # A client can credit at most one minute per heartbeat.
    seconds = int(data.get("seconds", 60))
    if seconds < 45 or seconds > 90:
        raise HTTPException(400, "Некорректная длительность сессии.")
    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена.")
        progress = db.query(ReadingProgress).filter_by(user_id=user.id, book_id=book_id).first()
        if progress is None:
            progress = ReadingProgress(user_id=user.id, book_id=book_id, minutes_read=1)
            db.add(progress)
        else:
            progress.minutes_read = (progress.minutes_read or 0) + 1
        db.commit()
    return {"ok": True}


@router.get("/api/reading-summary")
def reading_summary(request: Request):
    user = _require_user(request)
    with SessionLocal() as db:
        minutes = db.query(func.coalesce(func.sum(ReadingProgress.minutes_read), 0)).filter(ReadingProgress.user_id == user.id).scalar()
        started = db.query(ReadingProgress).filter(ReadingProgress.user_id == user.id).count()
        finished = db.query(UserShelf).filter(UserShelf.user_id == user.id, UserShelf.status == "read").count()
        shelf_counts = {status: db.query(UserShelf).filter_by(user_id=user.id, status=status).count() for status in ("want", "reading", "read")}
    return {"minutes_read": int(minutes or 0), "started_books": started, "finished_books": finished, "shelves": shelf_counts}


@router.get("/api/discussions/{book_id}")
def get_discussion(book_id: int, request: Request):
    user = _user(request)
    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена.")
        rows = (
            db.query(BookDiscussion, User)
            .join(User, User.id == BookDiscussion.user_id)
            .filter(BookDiscussion.book_id == book_id, BookDiscussion.is_hidden.is_(False))
            .order_by(BookDiscussion.created_at.asc())
            .limit(200).all()
        )
        post_ids = [post.id for post, _ in rows]
        likes = {}
        liked = set()
        if post_ids:
            counts = db.query(DiscussionLike.post_id, func.count(DiscussionLike.id)).filter(DiscussionLike.post_id.in_(post_ids)).group_by(DiscussionLike.post_id).all()
            likes = {post_id: count for post_id, count in counts}
            if user:
                liked = {post_id for (post_id,) in db.query(DiscussionLike.post_id).filter(DiscussionLike.user_id == user.id, DiscussionLike.post_id.in_(post_ids)).all()}
        return {"items": [{
            "id": post.id, "parent_id": post.parent_id, "content": post.content,
            "username": author.username, "created_at": post.created_at.isoformat(),
            "likes": likes.get(post.id, 0), "liked": post.id in liked,
            "can_report": bool(user and user.id != post.user_id),
        } for post, author in rows]}


@router.post("/api/discussions/{book_id}")
async def create_discussion(book_id: int, request: Request):
    user = _require_user(request)
    data = await request.json()
    content = str(data.get("content", "")).strip()[:3000]
    parent_id = data.get("parent_id")
    if len(content) < 2:
        raise HTTPException(400, "Сообщение слишком короткое.")
    with SessionLocal() as db:
        if not db.get(Book, book_id):
            raise HTTPException(404, "Книга не найдена.")
        parent = None
        if parent_id is not None:
            parent = db.get(BookDiscussion, int(parent_id))
            if not parent or parent.book_id != book_id or parent.is_hidden:
                raise HTTPException(400, "Комментарий для ответа не найден.")
        post = BookDiscussion(book_id=book_id, user_id=user.id, parent_id=parent.id if parent else None, content=content)
        db.add(post)
        db.flush()
        if parent and parent.user_id != user.id:
            from bot.models import UserNotification
            db.add(UserNotification(user_id=parent.user_id, title="Ответ на ваш комментарий", message=f"{user.username} ответил: {content[:180]}"))
        db.commit()
        return {"ok": True, "id": post.id}


@router.post("/api/discussions/{post_id}/like")
def toggle_discussion_like(post_id: int, request: Request):
    user = _require_user(request)
    with SessionLocal() as db:
        post = db.get(BookDiscussion, post_id)
        if not post or post.is_hidden:
            raise HTTPException(404, "Комментарий не найден.")
        like = db.query(DiscussionLike).filter_by(post_id=post_id, user_id=user.id).first()
        if like:
            db.delete(like)
            liked = False
        else:
            db.add(DiscussionLike(post_id=post_id, user_id=user.id))
            liked = True
        db.commit()
        count = db.query(DiscussionLike).filter_by(post_id=post_id).count()
        return {"ok": True, "liked": liked, "likes": count}


@router.post("/api/discussions/{post_id}/report")
async def report_discussion(post_id: int, request: Request):
    user = _require_user(request)
    data = await request.json()
    reason = str(data.get("reason", "Жалоба пользователя")).strip()[:500] or "Жалоба пользователя"
    with SessionLocal() as db:
        post = db.get(BookDiscussion, post_id)
        if not post or post.is_hidden:
            raise HTTPException(404, "Комментарий не найден.")
        if post.user_id == user.id:
            raise HTTPException(400, "Нельзя пожаловаться на своё сообщение.")
        existing = db.query(DiscussionReport).filter_by(post_id=post_id, reporter_id=user.id, status="pending").first()
        if existing:
            return {"ok": True, "already_reported": True}
        db.add(DiscussionReport(post_id=post_id, reporter_id=user.id, reason=reason))
        db.commit()
    return {"ok": True}


@router.get("/api/admin/overview")
def admin_overview(request: Request):
    _require_admin(request)
    with SessionLocal() as db:
        total_books = db.query(Book).count()
        total_users = db.query(User).count()
        blocked_users = db.query(User).filter(User.is_blocked.is_(True)).count()
        total_views = db.query(func.coalesce(func.sum(Book.view_count), 0)).scalar()
        total_downloads = db.query(func.coalesce(func.sum(Book.download_count), 0)).scalar()
        pending_orders = db.query(BookRequest).filter_by(status="pending").count()
        pending_reports = db.query(DiscussionReport).filter_by(status="pending").count()
        top_books = db.query(Book).order_by(Book.view_count.desc(), Book.id.desc()).limit(5).all()
        return {
            "total_books": total_books, "total_users": total_users,
            "blocked_users": blocked_users, "total_views": int(total_views or 0),
            "total_downloads": int(total_downloads or 0),
            "pending_orders": pending_orders, "pending_reports": pending_reports,
            "top_books": [{"id": b.id, "title": b.title, "author": b.author, "views": b.view_count, "downloads": b.download_count} for b in top_books],
        }


@router.get("/api/admin/users")
def admin_users(request: Request):
    _require_admin(request)
    with SessionLocal() as db:
        users = db.query(User).order_by(User.created_at.desc()).limit(500).all()
        return {"users": [{"id": u.id, "username": u.username, "email": u.email, "blocked": bool(u.is_blocked), "created_at": u.created_at.isoformat()} for u in users]}


@router.post("/api/admin/users/{user_id}/block")
async def admin_toggle_user_block(user_id: int, request: Request):
    _require_admin(request)
    data = await request.json()
    blocked = bool(data.get("blocked"))
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Пользователь не найден.")
        user.is_blocked = blocked
        db.commit()
    return {"ok": True, "blocked": blocked}


@router.get("/api/admin/moderation")
def admin_moderation(request: Request):
    _require_admin(request)
    with SessionLocal() as db:
        rows = (
            db.query(DiscussionReport, BookDiscussion, User, Book)
            .join(BookDiscussion, BookDiscussion.id == DiscussionReport.post_id)
            .join(User, User.id == BookDiscussion.user_id)
            .join(Book, Book.id == BookDiscussion.book_id)
            .filter(DiscussionReport.status == "pending")
            .order_by(DiscussionReport.created_at.desc()).limit(100).all()
        )
        reviews = db.query(Review, User, Book).join(User, User.id == Review.user_id).join(Book, Book.id == Review.book_id).order_by(Review.created_at.desc()).limit(100).all()
        hidden = db.query(BookDiscussion, User, Book).join(User, User.id == BookDiscussion.user_id).join(Book, Book.id == BookDiscussion.book_id).filter(BookDiscussion.is_hidden.is_(True)).order_by(BookDiscussion.created_at.desc()).limit(100).all()
        return {
            "reports": [{"id": r.id, "post_id": p.id, "reason": r.reason, "content": p.content, "author": author.username, "book": book.title, "created_at": r.created_at.isoformat()} for r, p, author, book in rows],
            "reviews": [{"id": review.id, "username": author.username, "book": book.title, "rating": review.rating, "text": review.text, "created_at": review.created_at.isoformat()} for review, author, book in reviews],
            "hidden": [{"id": post.id, "username": author.username, "book": book.title, "content": post.content} for post, author, book in hidden],
        }


@router.post("/api/admin/discussions/{post_id}/moderate")
async def moderate_discussion(post_id: int, request: Request):
    _require_admin(request)
    data = await request.json()
    action = data.get("action")
    with SessionLocal() as db:
        post = db.get(BookDiscussion, post_id)
        if not post:
            raise HTTPException(404, "Сообщение не найдено.")
        if action == "hide":
            post.is_hidden = True
        elif action == "restore":
            post.is_hidden = False
        elif action == "delete":
            child_ids = [row[0] for row in db.query(BookDiscussion.id).filter_by(parent_id=post_id).all()]
            all_ids = [post_id, *child_ids]
            db.query(DiscussionLike).filter(DiscussionLike.post_id.in_(all_ids)).delete(synchronize_session=False)
            db.query(DiscussionReport).filter(DiscussionReport.post_id.in_(all_ids)).delete(synchronize_session=False)
            if child_ids:
                db.query(BookDiscussion).filter(BookDiscussion.id.in_(child_ids)).delete(synchronize_session=False)
            db.delete(post)
        else:
            raise HTTPException(400, "Неизвестное действие.")
        db.commit()
    return {"ok": True}


@router.post("/api/admin/reviews/{review_id}/delete")
def admin_delete_review(review_id: int, request: Request):
    _require_admin(request)
    with SessionLocal() as db:
        review = db.get(Review, review_id)
        if review:
            db.delete(review)
            db.commit()
    return {"ok": True}


@router.post("/api/admin/reports/{report_id}/resolve")
def resolve_report(report_id: int, request: Request):
    _require_admin(request)
    with SessionLocal() as db:
        report = db.get(DiscussionReport, report_id)
        if report:
            report.status = "resolved"
            db.commit()
    return {"ok": True}
