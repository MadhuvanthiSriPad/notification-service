"""Database connection and session management."""

import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

logger = logging.getLogger(__name__)


def _ensure_sqlite_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite+aiosqlite:///"):
        return
    sqlite_path = database_url.removeprefix("sqlite+aiosqlite:///")
    if sqlite_path in {"", ":memory:"}:
        return
    db_file = Path(sqlite_path)
    if db_file.parent and str(db_file.parent) != ".":
        db_file.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(settings.database_url)

if "sqlite" in settings.database_url:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={"timeout": 30},
    )
else:
    engine = create_async_engine(settings.database_url, echo=settings.debug)

if "sqlite" in settings.database_url:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
