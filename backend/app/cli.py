"""``copilot-remote`` command-line entrypoint.

Subcommands:

* ``init-config``     - copy ``config.example.yaml`` to a working path.
* ``create-user``     - create a new local account.
* ``reset-password``  - rotate the password on an existing account.

Uses only the standard library so it has no extra runtime dependencies
beyond the project itself.
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import sys
from pathlib import Path

from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from app.auth import hash_password
from app.config import get_settings
from app.database import get_engine, init_db
from app.models import User


# ---- helpers ----------------------------------------------------------------


def _read_password(args_password: str | None, *, confirm: bool) -> str:
    """Resolve a password from ``--password`` or the TTY.

    ``confirm`` prompts twice to catch typos on user creation.
    """
    if args_password is not None:
        if not args_password:
            raise ValueError("--password must not be empty")
        return args_password
    pw = getpass.getpass("Password: ")
    if not pw:
        raise ValueError("password must not be empty")
    if confirm:
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            raise ValueError("passwords do not match")
    return pw


def _read_username(args_username: str | None) -> str:
    if args_username is not None:
        return args_username
    return input("Username: ").strip()


def _config_example_path() -> Path:
    """Locate ``config.example.yaml`` next to the installed package."""
    # The file lives at the repo root, two levels above this module.
    return Path(__file__).resolve().parent.parent.parent / "config.example.yaml"


# ---- subcommands ------------------------------------------------------------


def cmd_init_config(args: argparse.Namespace) -> int:
    """Copy the example config to the destination, refusing to overwrite."""
    src = _config_example_path()
    if not src.is_file():
        print(f"error: example config not found at {src}", file=sys.stderr)
        return 1
    dst = Path(args.config).expanduser().resolve()
    if dst.exists() and not args.force:
        print(
            f"error: {dst} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"wrote {dst}")
    print("edit it before starting the server (set session_secret!)")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    """Create a new user; errors if the username is already taken."""
    username = _read_username(args.username)
    if not username:
        print("error: username must not be empty", file=sys.stderr)
        return 1
    password = _read_password(args.password, confirm=True)
    init_db()
    with SQLModelSession(get_engine()) as session:
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing is not None:
            print(f"error: user {username!r} already exists", file=sys.stderr)
            return 1
        user = User(username=username, password_hash=hash_password(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        print(f"created user {username!r} (id={user.id})")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    """Update the password on an existing user."""
    username = _read_username(args.username)
    if not username:
        print("error: username must not be empty", file=sys.stderr)
        return 1
    password = _read_password(args.password, confirm=True)
    init_db()
    with SQLModelSession(get_engine()) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user is None:
            print(f"error: user {username!r} not found", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        session.add(user)
        session.commit()
        print(f"password updated for {username!r}")
    return 0


# ---- parser -----------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copilot-remote",
        description="Copilot Remote backend management commands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-config", help="Copy the example config to a working path.")
    p_init.add_argument(
        "--config",
        default="./config.yaml",
        help="Destination path (default: ./config.yaml)",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the destination if it exists.",
    )
    p_init.set_defaults(func=cmd_init_config)

    p_create = sub.add_parser("create-user", help="Create a new login account.")
    p_create.add_argument("--username", default=None)
    p_create.add_argument("--password", default=None)
    p_create.set_defaults(func=cmd_create_user)

    p_reset = sub.add_parser("reset-password", help="Rotate a login account's password.")
    p_reset.add_argument("--username", default=None)
    p_reset.add_argument("--password", default=None)
    p_reset.set_defaults(func=cmd_reset_password)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point referenced by the ``copilot-remote`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    # ``get_settings`` may raise on placeholder secrets; surface a
    # friendly message instead of a stack trace.
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 1
    finally:
        # CLI invocations shouldn't share the cached settings instance
        # with a subsequent server process.
        get_settings.cache_clear()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
