"""PTY + tmux backend.

Two strictly-separated layers:

* tmux layer (persistent): ``create_session()``, ``kill_session()``,
  ``is_alive()``, ``is_process_alive()``, ``list_sessions()``.
* PTY layer (transient):   ``connect()``, ``resize()``, ``disconnect()``.

The tmux layer is called once per logical session (when a session is
created). The PTY layer is called once per WebSocket connection - i.e.
once per browser connect/disconnect.

Shell-safety rules (see plan section 6.8):

* No ``shell=True`` anywhere in this file.
* tmux session names are server-generated UUIDs; regex-validated before
  every tmux call.
* Repo paths and commands are passed as argv elements, never interpolated
  into strings.
"""
from __future__ import annotations

import os
import subprocess
from typing import List

from ptyprocess import PtyProcess

from .config import UUID_RE, get_settings, validate_command, validate_repo


class PtyError(Exception):
    """Raised when tmux or PTY operations fail."""


# --- helpers --------------------------------------------------------------


def _validate_session_id(session_id: str) -> str:
    """Validate a tmux session name. Must be a server-generated UUID."""
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        raise PtyError(f"invalid session id: {session_id!r}")
    return session_id


def _check_tmux_available() -> None:
    """Verify tmux is installed."""
    try:
        subprocess.run(
            ["tmux", "-V"],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise PtyError("tmux is not installed") from e
    except subprocess.CalledProcessError as e:
        raise PtyError(f"tmux failed: {e.stderr}") from e


def _get_pane_pid(session_id: str) -> int:
    """Return the PID of the command running in the session's pane (0 if unknown).

    Retries a few times with a short delay; the tmux server occasionally
    hasn't fully populated the pane metadata immediately after a
    ``new-session -d`` returns.
    """
    import time
    for _ in range(5):
        result = subprocess.run(
            ["tmux", "list-panes", "-t", session_id, "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return int(result.stdout.strip().splitlines()[0])
            except (ValueError, IndexError):
                pass
        time.sleep(0.05)
    return 0


# --- tmux layer (persistent) ----------------------------------------------


def create_session(session_id: str, repo: str, command: str) -> int:
    """Create a detached tmux session running ``command`` in ``repo``.

    Returns the PID of the spawned command (best effort; 0 if unknown).
    Raises ``PtyError`` on failure.
    """
    settings = get_settings()
    _check_tmux_available()
    _validate_session_id(session_id)

    # Validate and canonicalize via settings allowlists (raises ValueError).
    canonical_repo = validate_repo(repo)
    canonical_command = validate_command(command)

    # Belt-and-braces: the command is a single argv element, but reject
    # anything with surrounding whitespace, NUL, or newlines just in case.
    if not canonical_command or canonical_command != canonical_command.strip():
        raise PtyError(f"invalid command: {command!r}")
    if "\x00" in canonical_command or "\n" in canonical_command:
        raise PtyError(f"command contains forbidden bytes: {command!r}")

    # If a tmux session with this UUID already exists (e.g. from a previous
    # unclean shutdown), kill it first. We always own sessions with our UUIDs.
    subprocess.run(
        ["tmux", "kill-session", "-t", session_id],
        capture_output=True,
        check=False,
    )

    # Spawn the tmux session detached. The command is one argv element.
    result = subprocess.run(
        [
            "tmux", "new-session", "-d", "-s", session_id,
            "-c", canonical_repo, canonical_command,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PtyError(f"tmux new-session failed: {result.stderr.strip()}")

    return _get_pane_pid(session_id)


def kill_session(session_id: str) -> None:
    """Irreversibly kill the tmux session (and its child process).

    Tolerant of:

    * Session already gone (``can't find session``)
    * No tmux server running (``no server running on ...``) - this can
      happen in tests that previously killed the server via the CLI.
    """
    _validate_session_id(session_id)
    result = subprocess.run(
        ["tmux", "kill-session", "-t", session_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if "can't find session" in result.stderr:
            return
        if "no server running" in result.stderr:
            return
        raise PtyError(f"tmux kill-session failed: {result.stderr.strip()}")


def is_alive(session_id: str) -> bool:
    """True if the tmux session exists."""
    _validate_session_id(session_id)
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_id],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_process_alive(session_id: str) -> bool:
    """True if the spawned command's PID is still running."""
    pid = _get_pane_pid(session_id)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but we can't signal it
    return True


def list_sessions() -> List[str]:
    """List all our session IDs (those matching the UUID format)."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [s for s in result.stdout.splitlines() if UUID_RE.match(s)]


# --- PTY layer (transient) ------------------------------------------------


def connect(
    session_id: str, rows: int = 24, cols: int = 80
) -> PtyProcess:
    """Spawn a fresh PTY connected to ``tmux attach-session -t <sid>``.

    The PTY is a *transient* view of the persistent tmux session. When
    the caller closes the PTY, the tmux session (and the command it owns)
    keep running.
    """
    _check_tmux_available()
    _validate_session_id(session_id)
    if not is_alive(session_id):
        raise PtyError(f"tmux session not found: {session_id}")

    argv = [
        "tmux",
        "attach-session",
        "-t", session_id,
        # Detach other clients first so we become the sole viewer
        # when multi_attach is "reject". With "shared" this is also
        # fine; multiple attachers are allowed.
        "-d",
    ]
    pty = PtyProcess.spawn(argv, dimensions=(rows, cols))
    return pty


def resize(pty: PtyProcess, rows: int, cols: int) -> None:
    """Send SIGWINCH to the PTY."""
    pty.setwinsize(rows, cols)


def disconnect(pty: PtyProcess) -> None:
    """Close the PTY. The tmux session keeps running."""
    try:
        if pty.isalive():
            pty.close(force=True)
    except Exception:
        pass
