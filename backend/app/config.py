"""Application configuration.

Loads settings from a YAML file (``./config.yaml`` by default, overridable
via the ``COPILOT_REMOTE_CONFIG`` env var) and then overlays environment
variables prefixed with ``COPILOT_REMOTE_``. ``session_secret`` is
required and must not be the placeholder value shipped in the example
config.

The order of precedence (highest first):

1. Environment variables (``COPILOT_REMOTE_*``)
2. YAML file contents
3. Field defaults declared on ``Settings``
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel string used by the example config that must be replaced
# before the application can start.
PLACEHOLDER_SECRET = "change-me-to-a-long-random-string"

# Canonical regex for tmux session names. Must match the value used in
# ``session_manager`` / ``pty_backend``; kept here so other modules can
# import it without importing the registry.
UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


class SessionSettings(BaseSettings):
    """Session-level tunables (see ``config.example.yaml``)."""

    output_buffer_bytes: int = 131072
    status_poll_interval_seconds: int = 5
    idle_timeout_seconds: int = 0
    multi_attach: Literal["shared", "reject"] = "shared"


class Settings(BaseSettings):
    """Top-level settings object."""

    model_config = SettingsConfigDict(
        env_prefix="COPILOT_REMOTE_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    bind: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "sqlite:///./copilot_remote.db"
    session_secret: str
    secure_cookies: bool = True
    repos: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    session: SessionSettings = Field(default_factory=SessionSettings)
    environment: Literal["development", "production"] = "development"

    @field_validator("session_secret")
    @classmethod
    def _no_placeholder(cls, value: str) -> str:
        if value == PLACEHOLDER_SECRET:
            raise ValueError(
                "session_secret is still the placeholder value from "
                "config.example.yaml. Generate a long random string with "
                "`openssl rand -hex 32` and set it in config.yaml or "
                "via COPILOT_REMOTE_SESSION_SECRET."
            )
        if len(value) < 16:
            raise ValueError(
                "session_secret must be at least 16 characters long."
            )
        return value

    @field_validator("bind")
    @classmethod
    def _validate_bind(cls, value: str) -> str:
        if not value:
            raise ValueError("bind must be a non-empty host or IP")
        return value

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value:
            raise ValueError("database_url must be a non-empty SQLAlchemy URL")
        return value

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, data: Any) -> Any:
        """Overlay YAML file contents onto the input dict.

        Reads ``COPILOT_REMOTE_CONFIG`` (or ``./config.yaml``) once and
        merges its keys under whatever the caller (env vars / defaults)
        provided. YAML keys never override explicit inputs.
        """
        if not isinstance(data, dict):
            return data
        config_path = Path(os.environ.get("COPILOT_REMOTE_CONFIG", "./config.yaml"))
        if not config_path.is_file():
            return data
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse YAML config at {config_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(
                f"Top-level YAML in {config_path} must be a mapping, "
                f"got {type(raw).__name__}"
            )
        merged: dict[str, Any] = dict(raw)
        for key, value in data.items():
            if value is None:
                continue
            merged[key] = value
        return merged


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached :class:`Settings` instance.

    The cache is cleared by tests via ``get_settings.cache_clear()``
    after mutating ``COPILOT_REMOTE_CONFIG`` or other env vars.
    """
    return Settings()  # type: ignore[call-arg]


def _canonical(path: str) -> str:
    """Resolve to an absolute, symlink-free path."""
    return os.path.realpath(path)


def validate_repo(path: str) -> str:
    """Return the canonical form of ``path`` if it is in the allowlist.

    ``os.path.realpath`` is applied to both the input and each entry in
    ``settings.repos`` before comparison. Raises ``ValueError`` with a
    clear message otherwise.
    """
    settings = get_settings()
    target = _canonical(path)
    for allowed in settings.repos:
        if _canonical(allowed) == target:
            return target
    raise ValueError(
        f"repo {path!r} is not in the configured allowlist "
        f"({settings.repos!r})"
    )


def validate_command(cmd: str) -> str:
    """Return ``cmd`` if it is in the configured command allowlist.

    Comparison is exact, byte-for-byte. We deliberately do NOT
    ``realpath`` here: commands are typically looked up via ``$PATH`` at
    exec time, and ``realpath`` of a bare name like ``bash`` would
    resolve to a relative path that depends on the current working
    directory. For absolute paths, the comparison is direct; for bare
    names, it is also direct.
    """
    settings = get_settings()
    for allowed in settings.commands:
        if cmd == allowed:
            return cmd
    # Also accept absolute paths that realpath to an allowlisted absolute.
    if cmd.startswith("/"):
        target = _canonical(cmd)
        for allowed in settings.commands:
            if allowed.startswith("/") and _canonical(allowed) == target:
                return target
    raise ValueError(
        f"command {cmd!r} is not in the configured allowlist "
        f"({settings.commands!r})"
    )
