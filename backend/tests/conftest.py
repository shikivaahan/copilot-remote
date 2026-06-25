"""Shared pytest fixtures.

The fixtures deliberately bypass ``Settings``'s default caching: every
test that needs a ``Settings`` instance gets a fresh one built from
``COPILOT_REMOTE_CONFIG``, so suites can run in parallel without
poisoning each other's env state.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session as SQLModelSession

from app import database as _db_module
from app.config import Settings, get_settings
from app.database import get_engine, init_db
from app.main import create_app

# Long random string that isn't the placeholder from
# ``config.example.yaml`` so the placeholder-rejection validator passes.
TEST_SECRET = "x" * 64


@pytest.fixture(autouse=True)
def _ensure_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Autouse: every test gets a fresh Settings with a valid secret and tmp DB.

    Tests that don't otherwise need a ``Settings`` instance still benefit
    from this because it clears the ``@lru_cache`` on ``get_settings``
    and resets the cached engine, preventing cross-test pollution.
    Also creates the DB schema so tests that talk to the DB just work.
    """
    db_path = tmp_path / "test.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "bind: 127.0.0.1\n"
        "port: 8765\n"
        f"session_secret: '{TEST_SECRET}'\n"
        "secure_cookies: false\n"
        "repos:\n"
        "  - /tmp/repo1\n"
        "  - /tmp/repo2\n"
        "commands:\n"
        "  - bash\n"
        "session:\n"
        "  output_buffer_bytes: 131072\n"
        "  status_poll_interval_seconds: 2\n"
        "  idle_timeout_seconds: 0\n"
        "  multi_attach: shared\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COPILOT_REMOTE_CONFIG", str(cfg))
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_ENVIRONMENT", "development")
    monkeypatch.setenv("COPILOT_REMOTE_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    _db_module._engine = None
    init_db()
    return Settings(  # type: ignore[call-arg]
        database_url=f"sqlite:///{db_path}",
        environment="development",
        secure_cookies=False,
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Write a minimal ``config.yaml`` to ``tmp_path`` and return the path."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "bind: 127.0.0.1\n"
        "port: 8765\n"
        f"session_secret: '{TEST_SECRET}'\n"
        "secure_cookies: false\n"
        "repos:\n"
        "  - /tmp/repo1\n"
        "  - /tmp/repo2\n"
        "commands:\n"
        "  - bash\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def settings(_ensure_settings: Settings) -> Settings:
    """Alias for the autouse :func:`_ensure_settings` fixture."""
    return _ensure_settings


@pytest.fixture
def db_session(tmp_path: Path, _ensure_settings: Settings) -> Iterator[SQLModelSession]:
    """Create the schema on a tmp SQLite file and yield a session."""
    init_db()
    with SQLModelSession(get_engine()) as session:
        yield session


@pytest.fixture
def client(tmp_path: Path, _ensure_settings: Settings) -> Iterator[httpx.AsyncClient]:
    """An ``httpx.AsyncClient`` bound to a fresh ``create_app()`` instance."""
    init_db()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
