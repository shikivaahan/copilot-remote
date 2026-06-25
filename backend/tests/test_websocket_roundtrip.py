"""End-to-end WebSocket terminal transport tests."""
from __future__ import annotations

import socket
import threading
import time

import httpx
import uvicorn
from sqlmodel import Session as SQLModelSession
from websockets.sync.client import connect as ws_connect

from app import database as _db_module
from app.auth import SESSION_COOKIE, hash_password
from app.config import get_settings
from app.database import get_engine, init_db
from app.main import create_app
from app.models import User
from app.session_manager import get_session_manager


CSRF = {"X-Requested-With": "copilot-remote-app"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_server(port: int) -> tuple[uvicorn.Server, threading.Thread]:
    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    return server, thread


def test_websocket_binary_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "ws_roundtrip.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("COPILOT_REMOTE_SESSION_SECRET", "x" * 64)
    get_settings.cache_clear()
    _db_module._engine = None
    init_db()
    with SQLModelSession(get_engine()) as db:
        db.add(User(username="alice", password_hash=hash_password("hunter2")))
        db.commit()

    port = _free_port()
    server, thread = _start_server(port)
    sid: str | None = None
    try:
        base_url = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "hunter2"},
            )
            assert login.status_code == 200, login.text
            repo = get_settings().repos[0]
            cmd = get_settings().commands[0]
            created = client.post(
                "/api/sessions",
                json={"name": "roundtrip", "repo": repo, "command": cmd},
                headers=CSRF,
            )
            assert created.status_code == 201, created.text
            sid = created.json()["id"]
            cookie_value = client.cookies.get(SESSION_COOKIE)
            assert cookie_value

        uri = f"ws://127.0.0.1:{port}/ws/sessions/{sid}"
        headers = {"Cookie": f"{SESSION_COOKIE}={cookie_value}"}
        with ws_connect(uri, additional_headers=headers, open_timeout=5) as ws:
            ws.send('{"type":"resize","rows":24,"cols":80}')
            first = ws.recv(timeout=5)
            assert isinstance(first, str)
            assert '"status"' in first
            ws.send(b"printf COPILOT_REMOTE_WS_OK\\r")
            deadline = time.time() + 5
            seen = b""
            while time.time() < deadline:
                frame = ws.recv(timeout=1)
                if isinstance(frame, bytes):
                    seen += frame
                    if b"COPILOT_REMOTE_WS_OK" in seen:
                        break
            assert b"COPILOT_REMOTE_WS_OK" in seen
    finally:
        if sid is not None:
            mgr = get_session_manager()
            import asyncio

            asyncio.run(mgr.kill(sid))
        server.should_exit = True
        thread.join(timeout=10)
