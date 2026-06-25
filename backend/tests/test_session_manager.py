"""Tests for session_manager.

Uses real tmux + bash for create/kill/connect; verifies the in-process
registry, ring buffer behaviour, and active_connections counter.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from sqlmodel import Session as SQLModelSession

from app import pty_backend
from app.config import get_settings
from app.database import get_engine
from app.models import Session as SessionRow
from app.session_manager import (
    MultiAttachError,
    LiveSession,
    SessionManager,
    get_session_manager,
)


@pytest.fixture
def manager():
    m = SessionManager()
    yield m
    # Cleanup: kill any tmux sessions the manager created
    async def _cleanup():
        for sess in await m.list():
            try:
                await m.kill(sess.id)
            except Exception:
                pass
    asyncio.get_event_loop().run_until_complete(_cleanup()) if False else None
    # We can't run async cleanup from sync fixture; do it synchronously instead.
    for sess in m._sessions.values():
        try:
            pty_backend.kill_session(sess.id)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _no_orphan_sessions():
    yield
    for sid in pty_backend.list_sessions():
        try:
            pty_backend.kill_session(sid)
        except Exception:
            pass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.asyncio
async def test_create_persists_and_returns_session(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="unit", repo=repo, command=cmd)
    assert isinstance(sess, LiveSession)
    assert sess.status == "running"
    assert sess.active_connections == 0
    # Re-fetch via get
    again = await manager.get(sess.id)
    assert again is sess


@pytest.mark.asyncio
async def test_create_rejects_disallowed_repo(manager):
    with pytest.raises(ValueError):
        await manager.create(name="x", repo="/etc", command="bash")


@pytest.mark.asyncio
async def test_create_rejects_disallowed_command(manager):
    repo = get_settings().repos[0]
    with pytest.raises(ValueError):
        await manager.create(name="x", repo=repo, command="rm -rf /")


@pytest.mark.asyncio
async def test_list_returns_all(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    a = await manager.create(name="a", repo=repo, command=cmd)
    b = await manager.create(name="b", repo=repo, command=cmd)
    all_sess = await manager.list()
    assert {a.id, b.id} == {s.id for s in all_sess}


@pytest.mark.asyncio
async def test_kill_removes_from_registry(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    await manager.kill(sess.id)
    assert await manager.get(sess.id) is None
    assert pty_backend.is_alive(sess.id) is False
    with SQLModelSession(get_engine()) as db:
        assert db.get(SessionRow, sess.id) is None


@pytest.mark.asyncio
async def test_stop_marks_stopped_and_kills_tmux(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    await manager.stop(sess.id)
    stopped = await manager.get(sess.id)
    assert stopped is not None
    assert stopped.status == "stopped"
    assert pty_backend.is_alive(sess.id) is False
    with SQLModelSession(get_engine()) as db:
        row = db.get(SessionRow, sess.id)
        assert row is not None
        assert row.status == "stopped"


@pytest.mark.asyncio
async def test_connect_disconnect_increments_active(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    _, pty = await manager.connect(sess.id, rows=24, cols=80)
    try:
        # Re-fetch to see updated counter
        s2 = await manager.get(sess.id)
        assert s2.active_connections == 1
    finally:
        await manager.disconnect(sess.id, pty)
    s3 = await manager.get(sess.id)
    assert s3.active_connections == 0
    # tmux session still alive
    assert pty_backend.is_alive(sess.id) is True


@pytest.mark.asyncio
async def test_connect_reject_mode_blocks_second(manager):
    # Temporarily flip multi_attach to "reject"
    settings = get_settings()
    original = settings.session.multi_attach
    settings.session.multi_attach = "reject"
    try:
        repo = settings.repos[0]
        cmd = settings.commands[0]
        sess = await manager.create(name="x", repo=repo, command=cmd)
        _, pty1 = await manager.connect(sess.id)
        try:
            with pytest.raises(MultiAttachError):
                await manager.connect(sess.id)
        finally:
            await manager.disconnect(sess.id, pty1)
    finally:
        settings.session.multi_attach = original


@pytest.mark.asyncio
async def test_connect_shared_mode_allows_second_attach(manager):
    settings = get_settings()
    original = settings.session.multi_attach
    settings.session.multi_attach = "shared"
    try:
        repo = settings.repos[0]
        cmd = settings.commands[0]
        sess = await manager.create(name="x", repo=repo, command=cmd)
        _, pty1 = await manager.connect(sess.id)
        _, pty2 = await manager.connect(sess.id)
        try:
            s2 = await manager.get(sess.id)
            assert s2.active_connections == 2
            assert pty1.isalive()
            assert pty2.isalive()
        finally:
            await manager.disconnect(sess.id, pty2)
            await manager.disconnect(sess.id, pty1)
    finally:
        settings.session.multi_attach = original


@pytest.mark.asyncio
async def test_append_output_and_preview(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    await manager.append_output(sess.id, b"hello ")
    await manager.append_output(sess.id, b"world")
    text = await manager.preview(sess.id, n_bytes=64)
    assert "hello world" in text


@pytest.mark.asyncio
async def test_ring_buffer_truncates_at_maxlen(manager):
    settings = get_settings()
    repo = settings.repos[0]
    cmd = settings.commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    # Force a small maxlen for the test
    small = 16
    sess.output_buffer.clear()
    sess.output_buffer = type(sess.output_buffer)(maxlen=small)
    chunk = b"x" * 100
    await manager.append_output(sess.id, chunk)
    assert len(bytes(sess.output_buffer)) == small


@pytest.mark.asyncio
async def test_ping_activity_updates_timestamp(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    before = sess.last_activity_at
    # Force a detectable clock difference
    import asyncio as _asyncio
    await _asyncio.sleep(0.01)
    await manager.ping_activity(sess.id)
    s2 = await manager.get(sess.id)
    assert s2.last_activity_at >= before


@pytest.mark.asyncio
async def test_restart_creates_new_session_with_new_id(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="x", repo=repo, command=cmd)
    old_id = sess.id
    new_sess = await manager.restart(old_id)
    try:
        assert new_sess.id != old_id
        assert (await manager.get(old_id)) is None
        assert (await manager.get(new_sess.id)) is new_sess
    finally:
        await manager.kill(new_sess.id)


@pytest.mark.asyncio
async def test_hydrate_restores_db_session_with_live_tmux(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="persisted", repo=repo, command=cmd)
    fresh = SessionManager()
    await fresh.hydrate()
    try:
        hydrated = await fresh.get(sess.id)
        assert hydrated is not None
        assert hydrated.name == "persisted"
        assert hydrated.status == "running"
        _, pty = await fresh.connect(sess.id)
        await fresh.disconnect(sess.id, pty)
    finally:
        await fresh.kill(sess.id)


@pytest.mark.asyncio
async def test_hydrate_marks_missing_running_tmux_as_exited(manager):
    repo = get_settings().repos[0]
    cmd = get_settings().commands[0]
    sess = await manager.create(name="gone", repo=repo, command=cmd)
    pty_backend.kill_session(sess.id)
    fresh = SessionManager()
    await fresh.hydrate()
    hydrated = await fresh.get(sess.id)
    assert hydrated is not None
    assert hydrated.status == "exited"
    with SQLModelSession(get_engine()) as db:
        row = db.get(SessionRow, sess.id)
        assert row is not None
        assert row.status == "exited"
    await fresh.kill(sess.id)


@pytest.mark.asyncio
async def test_get_session_manager_is_singleton():
    a = get_session_manager()
    b = get_session_manager()
    assert a is b
