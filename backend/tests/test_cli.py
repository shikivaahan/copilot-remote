"""Tests for the ``copilot-remote`` CLI (``app.cli``)."""
from __future__ import annotations

import io
import os
import pathlib
import sys
import tempfile
from unittest import mock

import pytest

from app import cli
from app.config import get_settings
from app.database import init_db, get_engine
from app.models import User
from sqlmodel import Session as SQLModelSession


@pytest.fixture
def tmp_config_path(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"session_secret: '{'x' * 64}'\n"
        "repos:\n  - /tmp/repo1\n"
        "commands:\n  - bash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COPILOT_REMOTE_CONFIG", str(cfg))
    monkeypatch.setenv("COPILOT_REMOTE_SESSION_SECRET", "x" * 64)
    get_settings.cache_clear()
    return cfg


def test_init_config_copies_example(tmp_path, tmp_config_path, monkeypatch, capsys):
    target = tmp_path / "out.yaml"
    monkeypatch.setattr(sys, "argv", ["copilot-remote", "init-config", "--config", str(target)])
    rc = cli.main()
    assert rc == 0
    assert target.exists()
    captured = capsys.readouterr()
    assert "Created" in captured.out or "config" in captured.out.lower()


def test_init_config_refuses_overwrite(tmp_path, tmp_config_path, monkeypatch, capsys):
    target = tmp_path / "out.yaml"
    target.write_text("existing: true\n")
    monkeypatch.setattr(sys, "argv", ["copilot-remote", "init-config", "--config", str(target)])
    rc = cli.main()
    assert rc == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "exists" in combined or "force" in combined
    assert target.read_text() == "existing: true\n"


def test_init_config_force_overwrites(tmp_path, tmp_config_path, monkeypatch):
    target = tmp_path / "out.yaml"
    target.write_text("existing: true\n")
    monkeypatch.setattr(
        sys, "argv",
        ["copilot-remote", "init-config", "--config", str(target), "--force"],
    )
    rc = cli.main()
    assert rc == 0
    assert "existing" not in target.read_text()


def test_create_user_inserts_row(tmp_path, monkeypatch, tmp_config_path):
    db_path = tmp_path / "cli_test.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    from app import database as _db_module
    _db_module._engine = None
    init_db()
    # Clear any cached app.database state
    get_settings.cache_clear()

    monkeypatch.setattr(
        sys, "argv",
        [
            "copilot-remote", "create-user",
            "--username", "alice", "--password", "hunter2",
        ],
    )
    rc = cli.main()
    assert rc == 0
    with SQLModelSession(get_engine()) as db:
        u = db.get(User, 1)  # first user id
        # username uniqueness so first user is id=1
        assert u is not None
        assert u.username == "alice"


def test_create_user_interactive_prompts(monkeypatch, tmp_path, tmp_config_path):
    db_path = tmp_path / "cli_int.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    from app import database as _db_module
    _db_module._engine = None
    init_db()
    get_settings.cache_clear()

    monkeypatch.setattr(sys, "argv", ["copilot-remote", "create-user"])
    monkeypatch.setattr("sys.stdin", io.StringIO("bob\nsecretpw\nsecretpw\n"))
    monkeypatch.setattr("getpass.getpass", lambda prompt: "secretpw")
    rc = cli.main()
    assert rc == 0
    with SQLModelSession(get_engine()) as db:
        from sqlmodel import select
        u = db.exec(select(User).where(User.username == "bob")).first()
        assert u is not None


def test_create_user_password_mismatch(tmp_path, monkeypatch, tmp_config_path, capsys):
    db_path = tmp_path / "cli_mis.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    from app import database as _db_module
    _db_module._engine = None
    init_db()
    get_settings.cache_clear()

    monkeypatch.setattr(sys, "argv", ["copilot-remote", "create-user"])
    monkeypatch.setattr("sys.stdin", io.StringIO("carol\nfirst\nsecond\n"))
    passwords = iter(["first", "second"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(passwords))
    rc = cli.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "match" in captured.out.lower() or "match" in captured.err.lower()


def test_reset_password_updates_existing(tmp_path, monkeypatch, tmp_config_path):
    db_path = tmp_path / "cli_reset.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    from app import database as _db_module
    _db_module._engine = None
    init_db()
    get_settings.cache_clear()
    from app.auth import hash_password
    with SQLModelSession(get_engine()) as db:
        db.add(User(username="dave", password_hash=hash_password("old")))
        db.commit()

    monkeypatch.setattr(
        sys, "argv",
        [
            "copilot-remote", "reset-password",
            "--username", "dave", "--password", "newpass",
        ],
    )
    rc = cli.main()
    assert rc == 0
    from app.auth import verify_password
    with SQLModelSession(get_engine()) as db:
        from sqlmodel import select
        u = db.exec(select(User).where(User.username == "dave")).first()
        assert verify_password("newpass", u.password_hash)
        assert not verify_password("old", u.password_hash)


def test_reset_password_user_not_found(tmp_path, monkeypatch, tmp_config_path, capsys):
    db_path = tmp_path / "cli_nf.db"
    monkeypatch.setenv("COPILOT_REMOTE_DATABASE_URL", f"sqlite:///{db_path}")
    from app import database as _db_module
    _db_module._engine = None
    init_db()
    get_settings.cache_clear()

    monkeypatch.setattr(
        sys, "argv",
        [
            "copilot-remote", "reset-password",
            "--username", "ghost", "--password", "newpass",
        ],
    )
    rc = cli.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.out.lower() or "not found" in captured.err.lower()


def test_no_args_prints_help(capsys):
    import sys as _sys
    _sys.argv = ["copilot-remote"]
    # argparse calls sys.exit(2) when a subcommand is required.
    with pytest.raises(SystemExit):
        cli.main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "usage" in combined.lower() or "create-user" in combined
