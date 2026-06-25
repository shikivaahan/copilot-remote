"""Tests for the WebSocket terminal transport (Phase 4).

The end-to-end binary round-trip and ping/pong are timing-sensitive
and require a real ASGI server; the TestClient's WebSocketTestSession
blocks indefinitely on receive() and offers no timeout. We cover the
auth/missing-session paths here (where the server closes immediately)
and the control-plane logic directly via unit tests in
``test_websocket_control.py``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session as SQLModelSession

from app import database as _db_module
from app.auth import hash_password
from app.auth import SESSION_COOKIE, sign_cookie_value
from app.config import get_settings
from app.database import get_engine, init_db
from app.main import create_app
from app.models import User


@pytest.fixture
def client_and_session(tmp_path, monkeypatch):
    """Set up a TestClient with a seeded user and one running session."""
    db_path = tmp_path / "ws_test.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_SESSION_SECRET", "x" * 64)
    get_settings.cache_clear()
    _db_module._engine = None
    init_db()
    app = create_app()
    with TestClient(app) as c:
        with SQLModelSession(get_engine()) as db:
            db.add(
                User(username="alice", password_hash=hash_password("hunter2"))
            )
            db.commit()
        c.post(
            "/api/auth/login",
            json={"username": "alice", "password": "hunter2"},
        )
        repo = get_settings().repos[0]
        cmd = get_settings().commands[0]
        sid = c.post(
            "/api/sessions",
            json={"name": "ws-test", "repo": repo, "command": cmd},
            headers={"X-Requested-With": "copilot-remote-app"},
        ).json()["id"]
        try:
            yield c, sid
        finally:
            c.delete(
                f"/api/sessions/{sid}",
                headers={"X-Requested-With": "copilot-remote-app"},
            )


def test_websocket_rejects_unauthenticated(tmp_path, monkeypatch):
    """Without a cookie, the WS is closed before upgrade."""
    db_path = tmp_path / "ws_unauth.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_SESSION_SECRET", "x" * 64)
    get_settings.cache_clear()
    _db_module._engine = None
    init_db()
    app = create_app()
    with TestClient(app) as c:
        with c.websocket_connect(
            "/ws/sessions/00000000-0000-0000-0000-000000000000"
        ) as ws:
            msg = ws.receive()
            assert msg["type"] == "websocket.close"
            assert msg["code"] == 1008


def test_websocket_rejects_missing_session(client_and_session):
    c, _sid = client_and_session
    with c.websocket_connect(
        "/ws/sessions/00000000-0000-0000-0000-000000000000"
    ) as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 1008


def test_websocket_rejects_signed_cookie_for_missing_user(tmp_path, monkeypatch):
    """A valid signature is not enough; the user id must exist in the DB."""
    db_path = tmp_path / "ws_missing_user.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_SESSION_SECRET", "x" * 64)
    get_settings.cache_clear()
    _db_module._engine = None
    init_db()
    app = create_app()
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE, sign_cookie_value(9999))
        with c.websocket_connect(
            "/ws/sessions/00000000-0000-0000-0000-000000000000"
        ) as ws:
            msg = ws.receive()
            assert msg["type"] == "websocket.close"
            assert msg["code"] == 1008


def test_websocket_status_frame_on_connect(client_and_session):
    """Right after accept, the server sends a status text frame.

    The first thing we receive should be the status text frame sent
    immediately after accept (before any pumps start).
    """
    c, sid = client_and_session
    with c.websocket_connect(f"/ws/sessions/{sid}") as ws:
        # The very first frame should be the status text frame.
        frame = ws.receive()
        # In the TestClient frame envelope, server->client frames have
        # type "websocket.send" (the action the server took).
        assert frame["type"] in ("websocket.send", "websocket.receive")
        text = frame.get("text") or ""
        assert '"status"' in text
        assert '"rows"' in text
        assert '"cols"' in text
