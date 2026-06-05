"""Async SQLAlchemy engine, session factory, and declarative Base."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models. Alembic autogenerate reads
    ``Base.metadata`` to diff models against the live schema."""


engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with async_session_factory() as session:
        yield session
