"""Authentication primitives: password hashing, cookie signing, deps.

* Passwords are hashed with bcrypt via ``passlib`` (cost factor 12).
* Session state lives in a signed ``cr_session`` cookie. We use
  ``itsdangerous.TimestampSigner`` so an old cookie can be detected as
  expired and dropped.
* ``require_csrf_header`` enforces the ``X-Requested-With`` header on
  state-changing methods (defence in depth on top of ``SameSite=Strict``).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from passlib.context import CryptContext
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from app.config import Settings, get_settings
from app.database import get_session
from app.models import User

# Cookie and CSRF constants.
SESSION_COOKIE = "cr_session"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "copilot-remote-app"
# Salt name for the itsdangerous signer. Versioning this string is how
# we invalidate every outstanding cookie (e.g. after a secret rotation).
COOKIE_SALT = "copilot-remote-session"
# 30 days, matching the original cookie max-age.
COOKIE_MAX_AGE = timedelta(days=30)

# Bcrypt with cost factor 12 (see plan §9).
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


def hash_password(plain: str) -> str:
    """Hash ``plain`` with bcrypt and return the encoded digest."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` iff ``plain`` matches the bcrypt ``hashed`` digest."""
    try:
        return _pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        # Malformed hashes, library bugs, etc. - treat as a non-match.
        return False


def _signer(settings: Settings):
    """Build a :class:`TimestampSigner` keyed by the session secret."""
    from itsdangerous import TimestampSigner

    return TimestampSigner(settings.session_secret, salt=COOKIE_SALT)


def sign_cookie_value(user_id: int) -> str:
    """Return a signed, timestamped cookie value for ``user_id``."""
    settings = get_settings()
    return _signer(settings).sign(str(user_id)).decode("ascii")


def unsign_cookie_value(signed: str) -> int | None:
    """Return the ``user_id`` encoded in ``signed`` or ``None`` if invalid.

    Cookies older than :data:`COOKIE_MAX_AGE` are treated as invalid.
    """
    from itsdangerous import BadSignature, SignatureExpired

    settings = get_settings()
    try:
        raw = _signer(settings).unsign(signed, max_age=int(COOKIE_MAX_AGE.total_seconds()))
    except (BadSignature, SignatureExpired):
        return None
    try:
        return int(raw.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None


def set_session_cookie(response: Response, user_id: int) -> None:
    """Attach the signed session cookie to ``response``."""
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=sign_cookie_value(user_id),
        max_age=int(COOKIE_MAX_AGE.total_seconds()),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from ``response``."""
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def get_current_user(
    request: Request,
    session: Annotated[SQLModelSession, Depends(get_session)],
) -> User:
    """FastAPI dependency: resolve the cookie to a :class:`User` row.

    Raises ``401`` if the cookie is missing, tampered with, expired, or
    references a user that no longer exists.
    """
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user_id = unsign_cookie_value(raw)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session cookie",
        )
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


# Methods exempt from the CSRF check - GET-style requests can't mutate
# state, and OPTIONS is the CORS preflight.
_CSRF_EXEMPT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_csrf_header(request: Request) -> None:
    """FastAPI dependency: reject requests that lack the CSRF header.

    Defence in depth on top of ``SameSite=Strict`` cookies - browsers
    cannot set custom headers on cross-origin simple requests, so the
    presence of ``X-Requested-With: copilot-remote-app`` proves the
    request originated from our SPA.
    """
    if request.method in _CSRF_EXEMPT_METHODS:
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF header missing or invalid",
        )
