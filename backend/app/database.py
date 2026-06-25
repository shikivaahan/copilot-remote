"""Database engine and session lifecycle.

A single SQLModel ``Engine`` is created at module import time from
``settings.database_url``. SQLite needs ``check_same_thread=False`` so
the connection can be shared across FastAPI's threadpool workers; for
other backends we pass no extra kwargs.

``get_session`` is a FastAPI dependency that yields a session and
ensures it is closed when the request finishes.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.engine import Engine
from sqlmodel import Session as SQLModelSession
from sqlmodel import SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the lazily-initialised SQLModel ``Engine``."""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args: dict[str, object] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args)
    return _engine


def init_db() -> None:
    """Create all tables defined on ``SQLModel.metadata``."""
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[SQLModelSession]:
    """FastAPI dependency that yields a SQLModel session and closes it.

    The session is closed via the context manager, so even on exception
    it is released back to the pool.
    """
    engine = get_engine()
    with SQLModelSession(engine) as session:
        yield session
