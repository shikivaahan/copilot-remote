"""REST API routes for Copilot Remote.

Route table:

* ``GET  /health``                  (liveness; in main.py)
* ``POST /api/auth/login``          (no CSRF, no auth)
* ``POST /api/auth/logout``         (CSRF, auth)
* ``GET  /api/auth/me``             (auth, no CSRF)
* ``GET  /api/sessions``            (auth, no CSRF)
* ``POST /api/sessions``            (auth, CSRF)
* ``GET  /api/sessions/{id}``       (auth, no CSRF)
* ``DELETE /api/sessions/{id}``     (auth, CSRF)
* ``POST /api/sessions/{id}/stop``  (auth, CSRF)
* ``POST /api/sessions/{id}/restart`` (auth, CSRF)
* ``GET  /api/sessions/{id}/preview``  (auth, no CSRF)
* ``GET  /api/sessions/{id}/health``   (auth, no CSRF)
* ``GET  /api/repos``               (auth, no CSRF)
* ``GET  /api/commands``            (auth, no CSRF)
"""
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from . import pty_backend
from .auth import (
    clear_session_cookie,
    get_current_user,
    require_csrf_header,
    set_session_cookie,
    verify_password,
)
from .config import get_settings
from .database import get_session
from .models import Session as SessionRow, User
from .schemas import (
    LoginRequest,
    SessionCreate,
    SessionHealth,
    SessionOut,
    SessionPreview,
    UserOut,
)
from .session_manager import get_session_manager

router = APIRouter(prefix="/api")


# --- auth -----------------------------------------------------------------


@router.post("/auth/login", response_model=UserOut, tags=["auth"])
def login(
    payload: LoginRequest,
    response: Response,
    session: Annotated[SQLModelSession, Depends(get_session)],
) -> UserOut:
    """Authenticate, set the session cookie, return the user."""
    user = session.exec(
        select(User).where(User.username == payload.username)
    ).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    set_session_cookie(response, int(user.id))  # type: ignore[arg-type]
    return UserOut.model_validate(user)


@router.post(
    "/auth/logout",
    status_code=204,
    tags=["auth"],
    dependencies=[Depends(require_csrf_header)],
)
def logout(response: Response) -> Response:
    """Clear the session cookie. Always succeeds."""
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut.model_validate(current_user)


# --- sessions -------------------------------------------------------------


def _to_out(sess) -> SessionOut:
    return SessionOut(
        id=sess.id,
        name=sess.name,
        repo=sess.repo,
        command=sess.command,
        status=sess.status,
        created_at=sess.created_at,
        last_activity_at=sess.last_activity_at,
    )


@router.get("/sessions", response_model=list[SessionOut], tags=["sessions"])
async def list_sessions(
    _user: Annotated[User, Depends(get_current_user)],
) -> list[SessionOut]:
    mgr = get_session_manager()
    sessions = await mgr.list()
    return [_to_out(s) for s in sessions]


@router.post(
    "/sessions",
    response_model=SessionOut,
    status_code=201,
    tags=["sessions"],
    dependencies=[Depends(require_csrf_header)],
)
async def create_session(
    payload: SessionCreate,
    _user: Annotated[User, Depends(get_current_user)],
) -> SessionOut:
    mgr = get_session_manager()
    try:
        sess = await mgr.create(
            name=payload.name, repo=payload.repo, command=payload.command
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except pty_backend.PtyError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _to_out(sess)


@router.get("/sessions/{session_id}", response_model=SessionOut, tags=["sessions"])
async def get_session_by_id(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
) -> SessionOut:
    mgr = get_session_manager()
    sess = await mgr.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return _to_out(sess)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    tags=["sessions"],
    dependencies=[Depends(require_csrf_header)],
)
async def delete_session(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
) -> Response:
    mgr = get_session_manager()
    sess = await mgr.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    await mgr.kill(session_id)
    return Response(status_code=204)


@router.post(
    "/sessions/{session_id}/stop",
    status_code=204,
    tags=["sessions"],
    dependencies=[Depends(require_csrf_header)],
)
async def stop_session(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
) -> Response:
    mgr = get_session_manager()
    sess = await mgr.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    await mgr.stop(session_id)
    return Response(status_code=204)


@router.post(
    "/sessions/{session_id}/restart",
    response_model=SessionOut,
    tags=["sessions"],
    dependencies=[Depends(require_csrf_header)],
)
async def restart_session(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
) -> SessionOut:
    mgr = get_session_manager()
    try:
        sess = await mgr.restart(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    return _to_out(sess)


@router.get(
    "/sessions/{session_id}/preview",
    response_model=SessionPreview,
    tags=["sessions"],
)
async def get_session_preview(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
) -> SessionPreview:
    mgr = get_session_manager()
    sess = await mgr.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    text = await mgr.preview(session_id, n_bytes=4096)
    return SessionPreview(id=session_id, text=text, bytes=len(text.encode("utf-8")))


@router.get(
    "/sessions/{session_id}/health",
    response_model=SessionHealth,
    tags=["sessions"],
)
async def get_session_health(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
) -> SessionHealth:
    settings = get_settings()
    mgr = get_session_manager()
    sess = await mgr.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    tmux_alive = await asyncio.to_thread(pty_backend.is_alive, sess.id)
    proc_alive = await asyncio.to_thread(pty_backend.is_process_alive, sess.id)
    return SessionHealth(
        id=sess.id,
        status=sess.status,
        tmux_session_exists=tmux_alive,
        process_alive=proc_alive,
        active_connections=sess.active_connections,
        last_activity_at=sess.last_activity_at,
        output_buffer_bytes=settings.session.output_buffer_bytes,
    )


# --- allowlists (for the dashboard) ---------------------------------------


@router.get("/repos", response_model=list[str], tags=["config"])
def list_repos(
    _user: Annotated[User, Depends(get_current_user)],
) -> list[str]:
    return list(get_settings().repos)


@router.get("/commands", response_model=list[str], tags=["config"])
def list_commands(
    _user: Annotated[User, Depends(get_current_user)],
) -> list[str]:
    return list(get_settings().commands)
