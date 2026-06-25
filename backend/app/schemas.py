"""Pydantic v2 request and response schemas.

These are the DTOs exchanged with the frontend over the REST API. They
are deliberately separate from the SQLModel table classes in
:mod:`app.models` so the wire format can evolve independently of the
database schema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Payload for ``POST /api/auth/login``."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=512)


class UserOut(BaseModel):
    """Public view of a :class:`app.models.User` row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime


class SessionCreate(BaseModel):
    """Payload for ``POST /api/sessions``.

    ``repo`` and ``command`` are cross-checked against the config
    allowlists in the route handler before the row is created.
    """

    name: str = Field(..., min_length=1, max_length=128)
    repo: str = Field(..., min_length=1, max_length=512)
    command: str = Field(..., min_length=1, max_length=128)


class SessionOut(BaseModel):
    """Public view of a :class:`app.models.Session_` row."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    repo: str
    command: str
    status: str
    created_at: datetime
    last_activity_at: datetime


class SessionPreview(BaseModel):
    """Output snippet returned by ``GET /api/sessions/{id}/preview``."""

    id: str
    text: str
    bytes: int


class SessionHealth(BaseModel):
    """Per-session health payload returned by ``GET /api/sessions/{id}/health``."""

    id: str
    status: str
    tmux_session_exists: bool
    process_alive: bool
    active_connections: int
    last_activity_at: datetime
    output_buffer_bytes: int


class ErrorResponse(BaseModel):
    """Uniform shape for error responses."""

    error: str
