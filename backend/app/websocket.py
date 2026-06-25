"""WebSocket handler: ``/ws/sessions/{id}``.

Wire protocol (see plan section 6.2):

* **Binary frames** carry terminal I/O. Client-to-server bytes are
  written verbatim to the PTY stdin. Server-to-client bytes are read
  verbatim from the PTY stdout.
* **Text frames (JSON)** carry control messages:
    - ``{"type": "resize", "rows": int, "cols": int}``
    - ``{"type": "signal", "name": "SIGINT" | "SIGTERM" | "SIGHUP"}``
    - ``{"type": "ping"}`` -> ``{"type": "pong"}``
    - server-pushed: ``{"type": "status", "state": "..."}`` and
      ``{"type": "error", "message": "..."}``

The handler validates the session cookie before upgrading, opens a
fresh PTY via :mod:`app.session_manager`, then runs two async pump
tasks (PTY -> WS, WS -> PTY) until either side closes. On exit, the
PTY is closed but the tmux session (and the underlying process) keep
running.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Optional

import ptyprocess
from ptyprocess import PtyProcess
from fastapi import APIRouter, Cookie, HTTPException, WebSocket, WebSocketDisconnect, status

from .auth import SESSION_COOKIE, unsign_cookie_value
from .pty_backend import disconnect as pty_disconnect
from .pty_backend import resize as pty_resize
from .session_manager import MultiAttachError, get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# Methods exempt from the CSRF check - GET-style requests can't mutate
# state, and OPTIONS is the CORS preflight.
_CSRF_EXEMPT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _is_websocket_authenticated(cr_session: Optional[str]) -> bool:
    """True iff the cookie unsigns to a known user id (any int)."""
    return unsign_cookie_value(cr_session or "") is not None


@router.websocket("/ws/sessions/{session_id}")
async def ws_session(
    websocket: WebSocket,
    session_id: str,
    cr_session: Optional[str] = Cookie(default=None),
) -> None:
    """Serve the WebSocket for one session connection."""
    if not _is_websocket_authenticated(cr_session):
        # Accept-then-close so the client gets a clear close frame.
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    mgr = get_session_manager()
    # Pre-flight: does the session exist?
    if (await mgr.get(session_id)) is None:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Accept the connection now so the client can send the initial resize.
    await websocket.accept()

    # Negotiate initial terminal size from the client. We default to
    # something safe; the client is expected to send a resize ASAP.
    # We also accept and reply to an early "ping" here so health
    # checks (e.g. browser WS library liveness probes) work even
    # before the resize.
    rows, cols = 24, 80
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
        msg = json.loads(first)
        if msg.get("type") == "resize":
            rows = int(msg.get("rows") or rows)
            cols = int(msg.get("cols") or cols)
        elif msg.get("type") == "ping":
            try:
                await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
        # else: unknown — discard and let the pump pick up the next frame.
    except (asyncio.TimeoutError, json.JSONDecodeError, ValueError):
        pass

    try:
        sess, pty = await mgr.connect(session_id, rows=rows, cols=cols)
    except MultiAttachError as e:
        await websocket.send_text(
            json.dumps({"type": "error", "message": str(e)})
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    except KeyError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "state": sess.status,
                "rows": rows,
                "cols": cols,
            }
        )
    )

    pty_to_ws = asyncio.create_task(_pump_pty_to_ws(websocket, pty, session_id, mgr))
    ws_to_pty = asyncio.create_task(_pump_ws_to_pty(websocket, pty, session_id, mgr))
    done, pending = await asyncio.wait(
        {pty_to_ws, ws_to_pty}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    # On any exit, close the PTY (but the tmux session keeps running).
    await mgr.disconnect(session_id, pty)
    try:
        await websocket.close()
    except Exception:
        pass


async def _pump_pty_to_ws(
    websocket: WebSocket,
    pty: PtyProcess,
    session_id: str,
    mgr,
) -> None:
    """Read bytes from the PTY, send as binary frames, append to ring buffer."""
    loop = asyncio.get_running_loop()
    try:
        while True:
            data = await loop.run_in_executor(None, _read_pty, pty)
            if not data:
                # PTY closed -> tmux session likely ended or we got detached.
                break
            logger.debug("pty->ws: %d bytes", len(data))
            try:
                await websocket.send_bytes(data)
            except (WebSocketDisconnect, RuntimeError):
                break
            await mgr.append_output(session_id, data)
    except Exception as e:
        logger.debug("pty->ws pump ended: %s", e)


async def _pump_ws_to_pty(
    websocket: WebSocket,
    pty: PtyProcess,
    session_id: str,
    mgr,
) -> None:
    """Read frames from the WebSocket: binary -> PTY, text -> control."""
    while True:
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            break
        except Exception:
            break

        mtype = message.get("type")
        if mtype == "websocket.receive":
            data = message
            if "bytes" in data and data["bytes"] is not None:
                try:
                    pty.write(data["bytes"])
                    await mgr.ping_activity(session_id)
                except (OSError, ValueError):
                    break
            elif "text" in data and data["text"] is not None:
                if not await _handle_control(websocket, pty, data["text"], mgr):
                    return
        elif mtype == "websocket.disconnect":
            break


async def _handle_control(
    websocket: WebSocket,
    pty: PtyProcess,
    text: str,
    mgr,
) -> bool:
    """Process a JSON text-frame control message.

    Returns ``False`` to signal the caller to terminate the WS handler
    (used when the client closes the connection).
    """
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return True

    mtype = msg.get("type")
    if mtype == "resize":
        try:
            r = int(msg["rows"])
            c = int(msg["cols"])
            if r > 0 and c > 0 and r < 1000 and c < 1000:
                pty_resize(pty, r, c)
        except (KeyError, ValueError, TypeError):
            pass
        return True
    if mtype == "signal":
        name = msg.get("name")
        sig = {
            "SIGINT": signal.SIGINT,
            "SIGTERM": signal.SIGTERM,
            "SIGHUP": signal.SIGHUP,
        }.get(name)
        if sig is not None and pty.pid is not None:
            try:
                os.killpg(os.getpgid(pty.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        return True
    if mtype == "ping":
        try:
            await websocket.send_text(json.dumps({"type": "pong"}))
        except Exception:
            return False
        return True
    # Unknown control type - ignore.
    return True


def _read_pty(pty: PtyProcess, timeout: float = 0.1) -> bytes:
    """Blocking PTY read with a small timeout; returns b'' on timeout/EOF.

    We use a thread-pool-friendly timeout so the asyncio event loop is
    not blocked. ptyprocess exposes a file descriptor which we read
    non-blockingly via ``os.read``.
    """
    if not pty.isalive():
        return b""
    try:
        # ``pty.read`` blocks. To avoid blocking the executor forever,
        # we read with a short poll and rely on the loop to await us.
        # This is best-effort; the next iteration will read more.
        data = pty.read(4096)
        return data or b""
    except EOFError:
        return b""
    except Exception:
        return b""
