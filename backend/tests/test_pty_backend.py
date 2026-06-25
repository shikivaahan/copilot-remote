"""Tests for pty_backend.

These tests spawn real tmux sessions with unique UUIDs. Each test cleans
up its own sessions in the finally block; no test relies on prior state.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import ptyprocess
from ptyprocess import PtyProcess
import pytest

from app import pty_backend
from app.config import get_settings


def _unique_id() -> str:
    """Generate a fresh server-side UUID for a tmux session name."""
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _cleanup_sessions():
    """Ensure no orphan tmux sessions leak between tests."""
    yield
    for sid in pty_backend.list_sessions():
        try:
            pty_backend.kill_session(sid)
        except Exception:
            pass


def test_validate_session_id_accepts_uuid():
    sid = _unique_id()
    assert pty_backend._validate_session_id(sid) == sid


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-uuid",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # 36 chars but not UUID-shaped
        "'; rm -rf /",
        "../etc/passwd",
        "12345678-1234-1234-1234-12345678901",  # 35 chars, not 36
        "12345678-1234-1234-1234-1234567890123",  # 37 chars, not 36
    ],
)
def test_validate_session_id_rejects_bad(bad):
    with pytest.raises(pty_backend.PtyError):
        pty_backend._validate_session_id(bad)


def test_validate_session_id_accepts_numeric_uuid():
    """Digits 0-9 are valid hex; pure-numeric UUIDs should be accepted."""
    sid = "12345678-1234-1234-1234-123456789012"
    assert pty_backend._validate_session_id(sid) == sid


def test_create_session_marks_tmux_alive(tmp_path):
    settings = get_settings()
    # Ensure bash is in the allowlist for this test
    if str(tmp_path) not in settings.repos and "/tmp" not in settings.repos:
        # We can't modify settings at runtime easily, so use a path we know
        # is allowlisted OR add /tmp to the test fixture. Simplest: skip
        # the per-test repo, rely on the conftest's /tmp/repo1 allowlist.
        pass

    repo = settings.repos[0]
    sid = _unique_id()
    pid = pty_backend.create_session(sid, repo, settings.commands[0])
    assert pid > 0
    try:
        assert pty_backend.is_alive(sid) is True
        assert pty_backend.is_process_alive(sid) is True
    finally:
        pty_backend.kill_session(sid)
    assert pty_backend.is_alive(sid) is False


def test_create_session_rejects_disallowed_repo():
    sid = _unique_id()
    with pytest.raises(ValueError):
        pty_backend.create_session(sid, "/etc", "bash")
    # And it should not have created a tmux session
    assert pty_backend.is_alive(sid) is False


def test_create_session_rejects_disallowed_command():
    sid = _unique_id()
    repo = get_settings().repos[0]
    with pytest.raises(ValueError):
        pty_backend.create_session(sid, repo, "rm -rf /")
    assert pty_backend.is_alive(sid) is False


def test_kill_session_idempotent():
    sid = _unique_id()
    repo = get_settings().repos[0]
    pty_backend.create_session(sid, repo, "bash")
    pty_backend.kill_session(sid)
    # Second kill is a no-op, not an error
    pty_backend.kill_session(sid)
    assert pty_backend.is_alive(sid) is False


def test_list_sessions_filters_to_uuids():
    # Create two valid sessions and one bogus one (manually).
    sids = [_unique_id() for _ in range(2)]
    repo = get_settings().repos[0]
    for sid in sids:
        pty_backend.create_session(sid, repo, "bash")
    # Add a non-UUID tmux session
    import subprocess
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", "not-a-uuid", "-c", repo, "bash"],
        capture_output=True,
    )
    try:
        listed = set(pty_backend.list_sessions())
        assert set(sids).issubset(listed)
        assert "not-a-uuid" not in listed
    finally:
        for sid in sids:
            pty_backend.kill_session(sid)
        subprocess.run(
            ["tmux", "kill-session", "-t", "not-a-uuid"],
            capture_output=True,
        )


def test_connect_returns_live_pty_with_io():
    sid = _unique_id()
    repo = get_settings().repos[0]
    pty_backend.create_session(sid, repo, "bash")
    try:
        pty = pty_backend.connect(sid, rows=24, cols=80)
        try:
            assert isinstance(pty, PtyProcess)
            assert pty.isalive()
            # Write a command and read the echo back.
            pty.write(b"echo COPROBE\r")
            time.sleep(0.3)
            data = pty.read(8192)
            assert b"COPROBE" in data
        finally:
            pty_backend.disconnect(pty)
        # tmux session is still alive after disconnect
        assert pty_backend.is_alive(sid) is True
    finally:
        pty_backend.kill_session(sid)


def test_connect_fails_if_session_missing():
    sid = _unique_id()
    with pytest.raises(pty_backend.PtyError):
        pty_backend.connect(sid)


def test_resize_does_not_error():
    sid = _unique_id()
    repo = get_settings().repos[0]
    pty_backend.create_session(sid, repo, "bash")
    try:
        pty = pty_backend.connect(sid, rows=24, cols=80)
        try:
            pty_backend.resize(pty, 40, 120)
            pty_backend.resize(pty, 24, 80)
        finally:
            pty_backend.disconnect(pty)
    finally:
        pty_backend.kill_session(sid)


def test_no_shell_true_in_subprocess_calls():
    """AST scan: no ``subprocess.run(..., shell=True)`` anywhere."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "app" / "pty_backend.py"
    tree = ast.parse(src.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # subprocess.run / subprocess.Popen / subprocess.call / .check_*
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                for kw in node.keywords:
                    if kw.arg == "shell":
                        if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            pytest.fail(f"shell=True found in pty_backend.py at line {node.lineno}")
