"""In-process session registry.

Responsibilities:

* Hold live ``LiveSession`` objects (in-memory mirror of the DB row, plus
  runtime state: pty, ring buffer, active_connections).
* Spawn a tmux session on ``create()``.
* Track active PTY connections.
* Maintain a 128 KB ring buffer of recent PTY output per session for the
  dashboard preview and snapshot endpoint.
* Run a background status poller that updates DB and prunes dead sessions.

Concurrency model:

* All state mutations on a single session go through the per-session
  ``asyncio.Lock``.
* The registry's ``_lock`` guards additions/removals.
* The status poller is a single asyncio task.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Optional, Tuple

import ptyprocess
from ptyprocess import PtyProcess
from sqlmodel import Session as SQLModelSession

from . import pty_backend
from .config import get_settings, validate_command, validate_repo
from .database import get_engine
from .models import Session as SessionRow


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def _db():
    """Sync context manager around the SQLModel engine."""
    with SQLModelSession(get_engine()) as s:
        yield s


@dataclass
class LiveSession:
    """In-memory representation of a session (the tmux-backed one)."""

    id: str
    name: str
    repo: str
    command: str
    status: str = "running"  # running | exited | errored
    created_at: datetime = field(default_factory=_utcnow)
    last_activity_at: datetime = field(default_factory=_utcnow)
    pid: int = 0
    output_buffer: Deque = field(default_factory=deque)
    active_connections: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        settings = get_settings()
        if not isinstance(self.output_buffer, deque) or self.output_buffer.maxlen is None:
            self.output_buffer = deque(maxlen=settings.session.output_buffer_bytes)


class SessionManager:
    """Singleton in-process registry of live sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}
        self._lock = asyncio.Lock()
        self._poller_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Start the background status poller."""
        if self._poller_task is None or self._poller_task.done():
            self._stop_event.clear()
            self._poller_task = asyncio.create_task(self._status_loop())

    async def shutdown(self) -> None:
        """Stop the background poller (called on app shutdown)."""
        self._stop_event.set()
        if self._poller_task is not None:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except (asyncio.CancelledError, Exception):
                pass

    # --- CRUD -------------------------------------------------------------

    async def create(
        self, *, name: str, repo: str, command: str
    ) -> LiveSession:
        """Create a new session (writes DB row, starts tmux, returns the LiveSession)."""
        settings = get_settings()
        # validate_repo/command may raise ValueError -> propagates as 400
        validate_repo(repo)
        validate_command(command)

        session_id = str(uuid.uuid4())

        pid = await asyncio.to_thread(
            pty_backend.create_session, session_id, repo, command
        )

        sess = LiveSession(
            id=session_id,
            name=name,
            repo=repo,
            command=command,
            status="running",
            pid=pid,
        )
        async with self._lock:
            self._sessions[session_id] = sess

        with _db() as db:
            row = SessionRow(
                id=sess.id,
                name=sess.name,
                repo=sess.repo,
                command=sess.command,
                status=sess.status,
                created_at=sess.created_at,
                last_activity_at=sess.last_activity_at,
                pid=sess.pid,
            )
            db.add(row)
            db.commit()
        return sess

    async def get(self, session_id: str) -> Optional[LiveSession]:
        async with self._lock:
            return self._sessions.get(session_id)

    async def list(self) -> list[LiveSession]:
        async with self._lock:
            return list(self._sessions.values())

    async def stop(self, session_id: str) -> None:
        """Mark the session as stopped (DB only). Does not kill tmux."""
        async with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            return
        async with sess.lock:
            sess.status = "errored"
            sess.last_activity_at = _utcnow()
        self._update_db_status(sess)

    async def kill(self, session_id: str) -> None:
        """Irreversibly kill the tmux session and remove from registry."""
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess is not None:
                del self._sessions[session_id]
        if sess is None:
            return
        await asyncio.to_thread(pty_backend.kill_session, session_id)
        with _db() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                row.status = "errored"
                row.last_activity_at = _utcnow()
                db.add(row)
                db.commit()

    async def restart(self, session_id: str) -> LiveSession:
        """Kill the old tmux session and create a new one with the same params."""
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(session_id)
            name, repo, command = sess.name, sess.repo, sess.command
        await self.kill(session_id)
        return await self.create(name=name, repo=repo, command=command)

    # --- PTY lifecycle ----------------------------------------------------

    async def connect(
        self, session_id: str, rows: int = 24, cols: int = 80
    ) -> Tuple[LiveSession, PtyProcess]:
        """Open a fresh PTY to the session and bump active_connections.

        Honors ``session.multi_attach``: if "reject" and a connection is
        already active, raises ``MultiAttachError``.
        """
        async with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(session_id)

        settings = get_settings()
        if (
            settings.session.multi_attach == "reject"
            and sess.active_connections > 0
        ):
            raise MultiAttachError("session already attached")

        pty = await asyncio.to_thread(
            pty_backend.connect, session_id, rows, cols
        )
        async with sess.lock:
            sess.active_connections += 1
            sess.last_activity_at = _utcnow()
        return sess, pty

    async def disconnect(
        self, session_id: str, pty: PtyProcess
    ) -> None:
        """Close the PTY and decrement active_connections."""
        async with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            return
        await asyncio.to_thread(pty_backend.disconnect, pty)
        async with sess.lock:
            sess.active_connections = max(0, sess.active_connections - 1)
            sess.last_activity_at = _utcnow()

    async def append_output(self, session_id: str, data: bytes) -> None:
        """Append PTY output to the session's ring buffer."""
        async with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            return
        async with sess.lock:
            sess.output_buffer.extend(data)
            sess.last_activity_at = _utcnow()

    async def preview(
        self, session_id: str, n_bytes: int = 4096
    ) -> str:
        """Return last n_bytes of PTY output as UTF-8 (lossy)."""
        async with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            return ""
        async with sess.lock:
            data = bytes(sess.output_buffer)[-n_bytes:]
        return data.decode("utf-8", errors="replace")

    async def ping_activity(self, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            return
        async with sess.lock:
            sess.last_activity_at = _utcnow()

    # --- status poller ----------------------------------------------------

    def _update_db_status(self, sess: LiveSession) -> None:
        try:
            with _db() as db:
                row = db.get(SessionRow, sess.id)
                if row is not None:
                    row.status = sess.status
                    row.last_activity_at = sess.last_activity_at
                    db.add(row)
                    db.commit()
        except Exception:
            pass

    async def _status_loop(self) -> None:
        settings = get_settings()
        interval = max(1, settings.session.status_poll_interval_seconds)
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(interval)
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    async def _poll_once(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            try:
                alive = await asyncio.to_thread(pty_backend.is_alive, sess.id)
                proc_alive = await asyncio.to_thread(
                    pty_backend.is_process_alive, sess.id
                )
            except Exception:
                continue
            new_status = (
                "running" if (alive and proc_alive)
                else "exited" if alive
                else "errored"
            )
            async with sess.lock:
                if sess.status != new_status:
                    sess.status = new_status
                    sess.last_activity_at = _utcnow()
                    self._update_db_status(sess)


class MultiAttachError(Exception):
    """Raised when multi_attach is "reject" and a connection is already active."""


# Module-level singleton
_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
