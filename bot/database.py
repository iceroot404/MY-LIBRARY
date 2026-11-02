
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL
from .models import Base


connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    # create_all не добавляет новые колонки в уже существующую таблицу.
    # Поэтому проверяем и безопасно добавляем счётчики.
    if DATABASE_URL.startswith("sqlite"):
        inspector = inspect(engine)
        columns = {
            column["name"]
            for column in inspector.get_columns("books")
        }

        with engine.begin() as connection:
            if "view_count" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE books "
                        "ADD COLUMN view_count INTEGER NOT NULL DEFAULT 0"
                    )
                )

            if "download_count" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE books "
                        "ADD COLUMN download_count INTEGER NOT NULL DEFAULT 0"
                    )
                )


    # MIGRATE_BOOK_REQUEST_FIELDS
    if DATABASE_URL.startswith("sqlite"):
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        if "book_requests" in tables:
            columns = {
                column["name"]
                for column in inspector.get_columns("book_requests")
            }

            with engine.begin() as connection:
                if "user_id" not in columns:
                    connection.execute(text(
                        "ALTER TABLE book_requests "
                        "ADD COLUMN user_id INTEGER REFERENCES users(id)"
                    ))

                if "status" not in columns:
                    connection.execute(text(
                        "ALTER TABLE book_requests "
                        "ADD COLUMN status VARCHAR(20) "
                        "NOT NULL DEFAULT 'pending'"
                    ))

                if "book_id" not in columns:
                    connection.execute(text(
                        "ALTER TABLE book_requests "
                        "ADD COLUMN book_id INTEGER REFERENCES books(id)"
                    ))


    # MIGRATE_LIBRARY_FEATURES_V1: добавляем новые колонки старым SQLite базам.
    if DATABASE_URL.startswith("sqlite"):
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        with engine.begin() as connection:
            if "users" in tables:
                user_columns = {c["name"] for c in inspector.get_columns("users")}
                if "is_blocked" not in user_columns:
                    connection.execute(text(
                        "ALTER TABLE users ADD COLUMN is_blocked BOOLEAN NOT NULL DEFAULT 0"
                    ))
            if "reading_progress" in tables:
                progress_columns = {c["name"] for c in inspector.get_columns("reading_progress")}
                if "minutes_read" not in progress_columns:
                    connection.execute(text(
                        "ALTER TABLE reading_progress ADD COLUMN minutes_read INTEGER NOT NULL DEFAULT 0"
                    ))


    # MIGRATE_EXTENDED_LIBRARY_V2: add nullable Telegram fields and soft-delete flag.
    if DATABASE_URL.startswith("sqlite"):
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        with engine.begin() as connection:
            if "users" in tables:
                user_columns = {c["name"] for c in inspector.get_columns("users")}
                if "telegram_id" not in user_columns:
                    connection.execute(text("ALTER TABLE users ADD COLUMN telegram_id INTEGER"))
                if "telegram_link_code" not in user_columns:
                    connection.execute(text("ALTER TABLE users ADD COLUMN telegram_link_code VARCHAR(32)"))
            if "books" in tables:
                book_columns = {c["name"] for c in inspector.get_columns("books")}
                if "is_deleted" not in book_columns:
                    connection.execute(text("ALTER TABLE books ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))


    # MIGRATE_PERSONAL_APPEARANCE_V1: per-user line spacing and reading width.
    if DATABASE_URL.startswith("sqlite"):
        inspector = inspect(engine)
        if "user_appearances" in set(inspector.get_table_names()):
            appearance_columns = {c["name"] for c in inspector.get_columns("user_appearances")}
            with engine.begin() as connection:
                if "line_height" not in appearance_columns:
                    connection.execute(text(
                        "ALTER TABLE user_appearances ADD COLUMN line_height FLOAT NOT NULL DEFAULT 1.8"
                    ))
                if "reading_width" not in appearance_columns:
                    connection.execute(text(
                        "ALTER TABLE user_appearances ADD COLUMN reading_width VARCHAR(16) NOT NULL DEFAULT 'normal'"
                    ))
