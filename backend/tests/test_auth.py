"""Tests for :mod:`app.auth`."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session as SQLModelSession

from app.auth import (
    CSRF_HEADER,
    CSRF_VALUE,
    SESSION_COOKIE,
    clear_session_cookie,
    get_current_user,
    hash_password,
    require_csrf_header,
    set_session_cookie,
    sign_cookie_value,
    unsign_cookie_value,
    verify_password,
)
from app.config import Settings, get_settings
from app.models import User


# ---- password hashing ------------------------------------------------------


def test_hash_and_verify_round_trip() -> None:
    """``hash_password`` then ``verify_password`` accepts the original."""
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert verify_password("hunter2", h) is True


def test_verify_rejects_wrong_password() -> None:
    """A wrong password returns ``False`` rather than raising."""
    h = hash_password("hunter2")
    assert verify_password("hunter3", h) is False
    assert verify_password("", h) is False


def test_verify_rejects_malformed_hash() -> None:
    """A malformed hash is treated as a non-match, not an exception."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_hashes_are_unique_per_call() -> None:
    """Two hashes of the same password differ (bcrypt salt randomness)."""
    a = hash_password("hunter2")
    b = hash_password("hunter2")
    assert a != b
    assert verify_password("hunter2", a)
    assert verify_password("hunter2", b)


# ---- cookie signing --------------------------------------------------------


def test_sign_and_unsign_round_trip(settings) -> None:
    """``sign_cookie_value`` and ``unsign_cookie_value`` agree."""
    assert unsign_cookie_value(sign_cookie_value(42)) == 42


def test_unsign_returns_none_for_tampered(settings) -> None:
    """A flipped byte invalidates the signature."""
    signed = sign_cookie_value(7)
    flipped = ("A" if signed[0] != "A" else "B") + signed[1:]
    assert unsign_cookie_value(flipped) is None


def test_unsign_returns_none_for_garbage(settings) -> None:
    """Random noise yields ``None``, not an exception."""
    assert unsign_cookie_value("not-a-signed-value") is None
    assert unsign_cookie_value("") is None


# ---- cookie attributes -----------------------------------------------------


def test_set_session_cookie_attributes_dev() -> None:
    """In development, cookies are HttpOnly + SameSite=Strict but not Secure."""
    from starlette.responses import Response

    resp = Response()
    set_session_cookie(resp, user_id=1)
    set_cookie = resp.headers["set-cookie"]
    assert SESSION_COOKIE in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" not in set_cookie


def test_set_session_cookie_attributes_prod(
    tmp_path, config_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In production, cookies also carry the ``Secure`` flag."""
    from starlette.responses import Response

    db_path = tmp_path / "prod.db"
    monkeypatch.setenv("COPILOT_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        Settings(  # type: ignore[call-arg]
            database_url=f"sqlite:///{db_path}",
            environment="production",
        )
        resp = Response()
        set_session_cookie(resp, user_id=1)
        set_cookie = resp.headers["set-cookie"]
        assert "Secure" in set_cookie
        assert "SameSite=strict" in set_cookie
    finally:
        get_settings.cache_clear()


def test_clear_session_cookie_removes_cookie() -> None:
    """``clear_session_cookie`` emits a deletion header."""
    from starlette.responses import Response

    resp = Response()
    clear_session_cookie(resp)
    assert SESSION_COOKIE in resp.headers["set-cookie"]
    # Either ``Max-Age=0`` or an expired date is acceptable.
    header = resp.headers["set-cookie"].lower()
    assert "max-age=0" in header or "expires=" in header


# ---- get_current_user ------------------------------------------------------


@pytest.fixture
def user(db_session: SQLModelSession) -> User:
    """Insert a user with a known bcrypt hash and return the row."""
    u = User(username="alice", password_hash=hash_password("hunter2"))
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _build_whoami_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: User = Depends(get_current_user)) -> dict:
        return {"id": user.id, "username": user.username}

    return app


async def test_get_current_user_returns_user_for_valid_cookie(user: User) -> None:
    """With a valid cookie, the dependency yields the ``User`` row."""
    app = _build_whoami_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set(SESSION_COOKIE, sign_cookie_value(user.id))
        r = await ac.get("/whoami")
    assert r.status_code == 200
    assert r.json() == {"id": user.id, "username": "alice"}


async def test_get_current_user_401_without_cookie() -> None:
    """Missing cookie -> 401."""
    app = _build_whoami_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/whoami")
    assert r.status_code == 401


async def test_get_current_user_401_for_invalid_cookie() -> None:
    """Tampered cookie -> 401."""
    app = _build_whoami_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set(SESSION_COOKIE, "definitely-not-signed")
        r = await ac.get("/whoami")
    assert r.status_code == 401


# ---- require_csrf_header ----------------------------------------------------


@pytest.fixture
def csrf_app() -> FastAPI:
    app = FastAPI()

    @app.get("/safe")
    def safe() -> dict:
        return {"ok": True}

    @app.post("/unsafe")
    def unsafe(_: None = Depends(require_csrf_header)) -> dict:
        return {"ok": True}

    return app


async def test_csrf_rejects_post_without_header(csrf_app: FastAPI) -> None:
    """POST without the header -> 403."""
    transport = ASGITransport(app=csrf_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/unsafe")
    assert r.status_code == 403


async def test_csrf_accepts_post_with_header(csrf_app: FastAPI) -> None:
    """POST with the header -> 200."""
    transport = ASGITransport(app=csrf_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/unsafe", headers={CSRF_HEADER: CSRF_VALUE})
    assert r.status_code == 200


async def test_csrf_allows_get_without_header(csrf_app: FastAPI) -> None:
    """GET is exempt even without the header."""
    transport = ASGITransport(app=csrf_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/safe")
    assert r.status_code == 200
