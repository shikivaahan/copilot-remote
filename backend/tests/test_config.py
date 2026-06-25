"""Tests for :mod:`app.config`."""

from __future__ import annotations

import pytest

from app.config import (
    PLACEHOLDER_SECRET,
    UUID_RE,
    Settings,
    get_settings,
    validate_command,
    validate_repo,
)


def test_defaults_when_only_secret_set(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Defaults are correct when only ``session_secret`` is configured."""
    # Build a fresh Settings with no env overrides and no YAML file.
    monkeypatch.delenv("COPILOT_REMOTE_CONFIG", raising=False)
    monkeypatch.delenv("COPILOT_REMOTE_BIND", raising=False)
    monkeypatch.delenv("COPILOT_REMOTE_PORT", raising=False)
    monkeypatch.delenv("COPILOT_REMOTE_DATABASE_URL", raising=False)
    get_settings.cache_clear()

    s = Settings(session_secret="x" * 64)  # type: ignore[call-arg]
    assert s.bind == "127.0.0.1"
    assert s.port == 8000
    assert s.database_url == "sqlite:///./copilot_remote.db"
    assert s.repos == []
    assert s.commands == []
    assert s.session.output_buffer_bytes == 131072
    assert s.session.status_poll_interval_seconds == 5
    assert s.session.idle_timeout_seconds == 0
    assert s.session.multi_attach == "shared"


def test_env_var_overrides_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """``COPILOT_REMOTE_PORT`` wins over the YAML value."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "session_secret: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "port: 8000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COPILOT_REMOTE_CONFIG", str(cfg))
    monkeypatch.setenv("COPILOT_REMOTE_PORT", "9000")
    get_settings.cache_clear()
    s = Settings()  # type: ignore[call-arg]
    assert s.port == 9000
    # Clean up so other tests start fresh.
    get_settings.cache_clear()


def test_validate_repo_rejects_unknown(tmp_path, settings: Settings) -> None:
    """``validate_repo`` rejects paths not in the allowlist."""
    # The fixture's allowlist is ``["/tmp/repo1", "/tmp/repo2"]``; make
    # sure neither exists (realpath doesn't have to resolve).
    assert validate_repo("/tmp/repo1")  # canonical form returned
    with pytest.raises(ValueError, match="allowlist"):
        validate_repo("/tmp/not-allowed")
    get_settings.cache_clear()


def test_validate_repo_resolves_symlinks(tmp_path, settings: Settings) -> None:
    """``validate_repo`` follows symlinks on both sides of the comparison."""
    real = tmp_path / "real_repo"
    real.mkdir()
    link = tmp_path / "link_repo"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):  # pragma: no cover - fs dep
        pytest.skip("symlinks not supported on this filesystem")
    # Write a config whose allowlist matches the symlink target so the
    # cached ``Settings`` picks it up after ``cache_clear``.
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "session_secret: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        f"repos:\n  - {real}\n",
        encoding="utf-8",
    )
    import os
    os.environ["COPILOT_REMOTE_CONFIG"] = str(cfg)
    get_settings.cache_clear()
    canonical = validate_repo(str(link))
    assert canonical == str(real.resolve())


def test_validate_command_rejects_unknown(settings: Settings) -> None:
    """``validate_command`` rejects commands not in the allowlist."""
    assert validate_command("bash")
    with pytest.raises(ValueError, match="allowlist"):
        validate_command("rm")
    get_settings.cache_clear()


def test_placeholder_secret_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Startup raises a clear error when the placeholder is still set."""
    monkeypatch.delenv("COPILOT_REMOTE_CONFIG", raising=False)
    monkeypatch.delenv("COPILOT_REMOTE_SESSION_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="placeholder"):
        Settings(session_secret=PLACEHOLDER_SECRET)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "value",
    [
        "01234567-89ab-cdef-0123-456789abcdef",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_uuid_re_accepts_valid(value: str) -> None:
    """``UUID_RE`` matches canonical lowercase UUIDs."""
    assert UUID_RE.match(value) is not None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-uuid",
        "01234567-89ab-cdef-0123-456789abcde",   # 11 hex digits at end
        "01234567-89ab-cdef-0123-456789abcdef0",  # 13 hex digits at end
        "012345678-9ab-cdef-0123-456789abcdef",  # 9 hex digits at start
        "ZZ234567-89ab-cdef-0123-456789abcdef",  # non-hex char
        "01234567-89ab-cdef-0123-456789ABCDEF",  # uppercase not allowed
    ],
)
def test_uuid_re_rejects_invalid(value: str) -> None:
    """``UUID_RE`` rejects anything that isn't the exact shape."""
    assert UUID_RE.match(value) is None
