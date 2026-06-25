"""Tests for the REST API (Phase 4)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from app import database as _db_module
from app.auth import hash_password
from app.config import get_settings
from app.database import get_engine, init_db
from app.main import create_app
from app.models import Session, User


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with a fresh in-memory-ish DB and a single user."""
    db_path = tmp_path / "api_test.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_SESSION_SECRET", "x" * 64)
    monkeypatch.setenv("COPILOT_REMOTE_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    # Reset the cached engine so the new env var takes effect.
    _db_module._engine = None
    init_db()
    app = create_app()
    with TestClient(app) as c:
        # Seed a user
        with SQLModelSession(get_engine()) as db:
            db.add(
                User(
                    username="alice",
                    password_hash=hash_password("hunter2"),
                )
            )
            db.commit()
        yield c


CSRF = {"X-Requested-With": "copilot-remote-app"}


def _login(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "hunter2"}
    )
    assert r.status_code == 200, r.text


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0"}


def test_login_success_and_me(client):
    _login(client)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_login_bad_password(client):
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong"}
    )
    assert r.status_code == 401


def test_logout_clears_cookie(client):
    _login(client)
    r = client.post("/api/auth/logout", headers=CSRF)
    assert r.status_code == 204
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_requires_auth(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_logout_requires_csrf(client):
    _login(client)
    r = client.post("/api/auth/logout")
    assert r.status_code == 403


def test_login_does_not_require_csrf(client):
    # Login is exempt because it's how the cookie is established.
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "hunter2"}
    )
    assert r.status_code == 200


def test_repos_returns_allowlist(client):
    _login(client)
    r = client.get("/api/repos")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_commands_returns_allowlist(client):
    _login(client)
    r = client.get("/api/commands")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_session_requires_csrf(client):
    _login(client)
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    r = client.post(
        "/api/sessions",
        json={"name": "test", "repo": repo, "command": cmd},
    )
    assert r.status_code == 403


def test_create_session_success_and_get(client):
    _login(client)
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    r = client.post(
        "/api/sessions",
        json={"name": "test", "repo": repo, "command": cmd},
        headers=CSRF,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    try:
        r2 = client.get(f"/api/sessions/{sid}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "test"
    finally:
        client.delete(f"/api/sessions/{sid}", headers=CSRF)


def test_create_session_rejects_bad_repo(client):
    _login(client)
    cmd = get_settings().commands[0]
    r = client.post(
        "/api/sessions",
        json={"name": "test", "repo": "/etc", "command": cmd},
        headers=CSRF,
    )
    assert r.status_code == 400


def test_create_session_rejects_bad_command(client):
    _login(client)
    repo = get_settings().repos[0]
    r = client.post(
        "/api/sessions",
        json={"name": "test", "repo": repo, "command": "rm -rf /"},
        headers=CSRF,
    )
    assert r.status_code == 400


def test_list_sessions_empty(client):
    _login(client)
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_get_session_not_found(client):
    _login(client)
    fake = "00000000-0000-0000-0000-000000000000"
    r = client.get(f"/api/sessions/{fake}")
    assert r.status_code == 404


def test_delete_session(client):
    _login(client)
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sid = client.post(
        "/api/sessions",
        json={"name": "t", "repo": repo, "command": cmd},
        headers=CSRF,
    ).json()["id"]
    r = client.delete(f"/api/sessions/{sid}", headers=CSRF)
    assert r.status_code == 204
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 404
    with SQLModelSession(get_engine()) as db:
        assert db.get(Session, sid) is None


def test_stop_session_kills_tmux_and_preserves_row(client):
    _login(client)
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sid = client.post(
        "/api/sessions",
        json={"name": "t", "repo": repo, "command": cmd},
        headers=CSRF,
    ).json()["id"]
    r = client.post(f"/api/sessions/{sid}/stop", headers=CSRF)
    assert r.status_code == 204
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
    r = client.get(f"/api/sessions/{sid}/health")
    assert r.status_code == 200
    assert r.json()["tmux_session_exists"] is False
    assert r.json()["process_alive"] is False
    with SQLModelSession(get_engine()) as db:
        row = db.get(Session, sid)
        assert row is not None
        assert row.status == "stopped"
    client.delete(f"/api/sessions/{sid}", headers=CSRF)


def test_preview_returns_text(client):
    _login(client)
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sid = client.post(
        "/api/sessions",
        json={"name": "t", "repo": repo, "command": cmd},
        headers=CSRF,
    ).json()["id"]
    try:
        r = client.get(f"/api/sessions/{sid}/preview")
        assert r.status_code == 200
        assert r.json()["id"] == sid
        assert "text" in r.json()
    finally:
        client.delete(f"/api/sessions/{sid}", headers=CSRF)


def test_health_endpoint_shape(client):
    _login(client)
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sid = client.post(
        "/api/sessions",
        json={"name": "t", "repo": repo, "command": cmd},
        headers=CSRF,
    ).json()["id"]
    try:
        r = client.get(f"/api/sessions/{sid}/health")
        assert r.status_code == 200
        body = r.json()
        for k in (
            "id",
            "status",
            "tmux_session_exists",
            "process_alive",
            "active_connections",
            "last_activity_at",
            "output_buffer_bytes",
        ):
            assert k in body
        assert body["tmux_session_exists"] is True
        assert body["process_alive"] is True
        assert body["active_connections"] == 0
    finally:
        client.delete(f"/api/sessions/{sid}", headers=CSRF)
