"""Direct unit tests for the WS control-plane logic.

These do not require a real WebSocket connection; they exercise the
``_handle_control`` coroutine directly with a stub WebSocket and a
real PtyProcess, so the test never blocks on a missing data source.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from app import websocket as ws_module
from app.pty_backend import PtyProcess


class StubWebSocket:
    """Minimal WebSocket substitute for control-plane tests."""

    def __init__(self) -> None:
        self.sent_text: List[str] = []
        self.sent_bytes: List[bytes] = []

    async def send_text(self, text: str) -> None:
        self.sent_text.append(text)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self, code: int = 1000) -> None:
        pass


class _MgrNoop:
    """No-op session manager for control-plane tests."""

    async def ping_activity(self, session_id: str) -> None:
        pass


@pytest.mark.asyncio
async def test_handle_control_ping_returns_pong():
    ws = StubWebSocket()
    pty = None  # type: ignore[assignment]
    mgr = _MgrNoop()
    result = await ws_module._handle_control(
        ws, pty, json.dumps({"type": "ping"}), mgr  # type: ignore[arg-type]
    )
    assert result is True
    assert any('"pong"' in t for t in ws.sent_text)


@pytest.mark.asyncio
async def test_handle_control_resize_calls_pty_resize():
    ws = StubWebSocket()
    calls: List[tuple[int, int]] = []

    class FakePty:
        pass

    fake_pty = FakePty()

    def fake_resize(pty, rows, cols):
        calls.append((rows, cols))

    original = ws_module.pty_resize
    ws_module.pty_resize = fake_resize
    try:
        result = await ws_module._handle_control(
            ws,
            fake_pty,  # type: ignore[arg-type]
            json.dumps({"type": "resize", "rows": 40, "cols": 120}),
            _MgrNoop(),
        )
        assert result is True
        assert calls == [(40, 120)]
    finally:
        ws_module.pty_resize = original


@pytest.mark.asyncio
async def test_handle_control_invalid_resize_is_ignored():
    """Bad dimensions or missing fields are ignored, not crashed."""
    ws = StubWebSocket()
    fake_pty = object()
    # Missing cols
    result = await ws_module._handle_control(
        ws,
        fake_pty,  # type: ignore[arg-type]
        json.dumps({"type": "resize", "rows": 40}),
        _MgrNoop(),
    )
    assert result is True
    # Out of range
    result = await ws_module._handle_control(
        ws,
        fake_pty,  # type: ignore[arg-type]
        json.dumps({"type": "resize", "rows": -1, "cols": 80}),
        _MgrNoop(),
    )
    assert result is True
    # Not JSON
    result = await ws_module._handle_control(
        ws,
        fake_pty,  # type: ignore[arg-type]
        "this is not json",
        _MgrNoop(),
    )
    assert result is True
    # Unknown type
    result = await ws_module._handle_control(
        ws,
        fake_pty,  # type: ignore[arg-type]
        json.dumps({"type": "unknown"}),
        _MgrNoop(),
    )
    assert result is True


@pytest.mark.asyncio
async def test_handle_control_signal_uses_killpg():
    """Signal control messages invoke os.killpg with the right signal.

    Stubs both os.getpgid and os.killpg so we can verify the call
    shape without depending on a real process group.
    """
    import os
    import signal

    class _PtyNoPid:
        pid = None

    class _PtyWithPid:
        pid = 1234

    ws = StubWebSocket()
    real_killpg = os.killpg
    real_getpgid = os.getpgid
    killpg_calls: List[tuple[int, int]] = []
    getpgid_calls: List[int] = []

    def fake_killpg(pid, sig):
        killpg_calls.append((pid, sig))

    def fake_getpgid(pid):
        getpgid_calls.append(pid)
        return pid  # pretend the pgid equals the pid

    os.killpg = fake_killpg  # type: ignore[assignment]
    os.getpgid = fake_getpgid  # type: ignore[assignment]
    try:
        # No pid: signal is silently dropped, no killpg call.
        result = await ws_module._handle_control(
            ws,
            _PtyNoPid(),  # type: ignore[arg-type]
            json.dumps({"type": "signal", "name": "SIGINT"}),
            _MgrNoop(),
        )
        assert result is True
        assert killpg_calls == []

        # With a pid: killpg is called with the resolved pgid.
        result = await ws_module._handle_control(
            ws,
            _PtyWithPid(),  # type: ignore[arg-type]
            json.dumps({"type": "signal", "name": "SIGINT"}),
            _MgrNoop(),
        )
        assert result is True
        assert getpgid_calls == [1234]
        assert killpg_calls == [(1234, signal.SIGINT)]
    finally:
        os.killpg = real_killpg  # type: ignore[assignment]
        os.getpgid = real_getpgid  # type: ignore[assignment]
