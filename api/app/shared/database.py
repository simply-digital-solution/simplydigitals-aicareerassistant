from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    connect_args = {}
    if "sqlite" in settings.database_url:
        connect_args = {"check_same_thread": False}
    return create_async_engine(
        settings.database_url,
        connect_args=connect_args,
        echo=settings.app_env == "development",
    )


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context():
    """Async context manager version of get_db — for use outside FastAPI dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Enable WAL mode for SQLite — allows concurrent reads + one writer."""
    async with engine.begin() as conn:
        if "sqlite" in get_settings().database_url:
            await conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode=WAL"))
            await conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))
