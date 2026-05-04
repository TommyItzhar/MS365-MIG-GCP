"""Authentication endpoints — admin password gate for the GUI.

Simple shared-secret auth for local/dev: admin enters a password,
backend validates against ADMIN_PASSWORD env var (default "admin"),
returns a session token. The token is opaque random bytes — kept
in a server-side set so it can be revoked on logout.

For production deployments behind Cloud Run, replace this with
IAP, Cloud Identity, or Workload Identity Federation.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Default password for local dev — override via ADMIN_PASSWORD env var.
_DEFAULT_PASSWORD = "admin"
_TOKEN_TTL_SECONDS = 60 * 60 * 8  # 8 hours

# In-memory token store: {token: (user, expires_at)}
# Tokens are lost on restart — that's intentional for a stateless backend.
_active_tokens: dict[str, tuple[str, float]] = {}


def _admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", _DEFAULT_PASSWORD)


def _purge_expired() -> None:
    now = time.time()
    expired = [t for t, (_, exp) in _active_tokens.items() if exp < now]
    for t in expired:
        _active_tokens.pop(t, None)


class LoginRequest(BaseModel):
    password: str
    user: Optional[str] = "admin"


class LoginResponse(BaseModel):
    token: str
    user: str
    expires_in: int


@auth_router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """Validate admin password and return a session token.

    The default password for local dev is "admin". Set the ADMIN_PASSWORD
    environment variable to change it.
    """
    expected = _admin_password()
    # Constant-time compare to avoid timing attacks
    if not secrets.compare_digest(request.password, expected):
        logger.warning("auth_login_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    _purge_expired()
    token = secrets.token_urlsafe(32)
    user = request.user or "admin"
    _active_tokens[token] = (user, time.time() + _TOKEN_TTL_SECONDS)

    logger.info("auth_login_ok", extra={"user": user})
    return LoginResponse(
        token=token,
        user=user,
        expires_in=_TOKEN_TTL_SECONDS,
    )


@auth_router.post("/logout")
async def logout(authorization: Optional[str] = Header(default=None)) -> dict:
    """Invalidate the supplied bearer token."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        _active_tokens.pop(token, None)
    return {"ok": True}


@auth_router.get("/whoami")
async def whoami(authorization: Optional[str] = Header(default=None)) -> dict:
    """Return the current user if the bearer token is valid; 401 otherwise."""
    user = _verify_token(authorization)
    return {"user": user}


def _verify_token(authorization: Optional[str]) -> str:
    """Verify the Authorization header and return the username, or raise 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.split(" ", 1)[1].strip()
    entry = _active_tokens.get(token)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user, expires_at = entry
    if expires_at < time.time():
        _active_tokens.pop(token, None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    return user


def require_auth(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency that gates a route behind auth.

    Usage::

        @router.get("/protected")
        async def protected(user: str = Depends(require_auth)):
            ...
    """
    return _verify_token(authorization)
