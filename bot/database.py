
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
