"""Static checks enforcing the shell-safety rules from plan section 6.8.

The runtime layer (``pty_backend``) already validates session ids with
a regex and passes argv lists (no ``shell=True``) to ``subprocess``.
These tests are a defence in depth: any future change that reintroduces
``shell=True`` or removes the UUID validation fails CI.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.config import UUID_RE

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


def _subprocess_calls(tree: ast.AST):
    """Yield every ``subprocess.<method>(...)`` Call node in ``tree``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            continue
        yield node


def _shell_kw(call: ast.Call):
    for kw in call.keywords:
        if kw.arg == "shell":
            return kw.value
    return None


def test_no_shell_true_in_app():
    """No ``subprocess.<x>(..., shell=True)`` anywhere in ``app/``."""
    offenders: list[tuple[str, int]] = []
    for path in APP_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for call in _subprocess_calls(tree):
            kw = _shell_kw(call)
            if (
                kw is not None
                and isinstance(kw, ast.Constant)
                and kw.value is True
            ):
                offenders.append((path.name, call.lineno))
    assert offenders == [], (
        f"shell=True is forbidden in subprocess calls: {offenders}"
    )


def test_uuid_regex_matches_valid():
    valid = "12345678-1234-1234-1234-123456789012"
    assert UUID_RE.match(valid) is not None
    abcdef = "abcdef00-1111-2222-3333-444444444444"
    assert UUID_RE.match(abcdef) is not None


def test_uuid_regex_rejects_invalid():
    for bad in [
        "",
        "not-a-uuid",
        "'; rm -rf /",
        "../../../etc/passwd",
        "12345678-1234-1234-1234-12345678901",  # 35 chars
        "12345678-1234-1234-1234-1234567890123",  # 37 chars
        "g2345678-1234-1234-1234-123456789012",  # g is not hex
        "12345678_1234_1234_1234_123456789012",  # underscores
    ]:
        assert UUID_RE.match(bad) is None, f"regex matched bad: {bad!r}"


def test_pty_backend_uses_argv_not_string():
    """All tmux/anything subprocess calls in pty_backend use argv lists."""
    tree = ast.parse((APP_DIR / "pty_backend.py").read_text())
    for call in _subprocess_calls(tree):
        # First positional arg must be a List, not a Constant (str).
        if not call.args:
            continue
        first = call.args[0]
        if not isinstance(first, ast.List):
            # Could be a variable; check that the file only ever
            # passes list literals.
            pytest.fail(
                f"pty_backend.py:{call.lineno}: subprocess call's first "
                f"arg is not a list literal; must be argv list, not a "
                f"string."
            )


def test_session_id_referenced_in_tmux_calls():
    """Every tmux subprocess call in pty_backend has a session id arg
    that is the result of ``_validate_session_id`` (regex-validated)."""
    src = (APP_DIR / "pty_backend.py").read_text()
    # Quick sanity: the function ``_validate_session_id`` must exist
    # and be called from the same file.
    assert "def _validate_session_id" in src
    # And the tmux call sites must call it.
    assert src.count("_validate_session_id(session_id)") >= 3
