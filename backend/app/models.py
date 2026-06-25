"""SQLModel table definitions.

Two tables today:

* ``User`` - one row per login account. ``password_hash`` is a bcrypt
  digest produced by :mod:`app.auth`.
* ``Session_`` - a Copilot Remote logical session. ``Session`` shadows
  ``fastapi.Request.session`` (and starlette's session middleware), so
  the table is named with a trailing underscore and re-exported under
  the public name ``Session`` for callers that don't care about the
  FastAPI clash.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """A login account for the Copilot Remote web app."""

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, nullable=False, max_length=64)
    password_hash: str = Field(nullable=False, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Session_(SQLModel, table=True):
    """A logical Copilot Remote session.

    ``id`` is a server-generated UUID string (validated by
    ``app.config.UUID_RE``); it is the *only* identifier ever passed to
    tmux. ``name`` is a user-supplied display label and must never reach
    a shell.

    ``status`` is one of:

    * ``running`` - tmux session exists and the child process is alive.
    * ``exited``  - tmux session exists but the pane is dead.
    * ``errored`` - tmux could not be reached or the process never
      started.

    ``pid`` is recorded for diagnostics only; the canonical source of
    process liveness is the tmux server.
    """

    __tablename__ = "session"  # type: ignore[assignment]

    id: str = Field(primary_key=True, max_length=36)
    name: str = Field(nullable=False, max_length=128)
    repo: str = Field(nullable=False, max_length=512)
    command: str = Field(nullable=False, max_length=128)
    status: str = Field(default="running", nullable=False, max_length=16)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_activity_at: datetime = Field(
        default_factory=datetime.utcnow, nullable=False
    )
    pid: int | None = Field(default=None, nullable=True)


# Public alias that drops the trailing underscore.
Session = Session_
