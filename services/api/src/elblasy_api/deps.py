import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from elblasy_api import audit
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.models import User
from elblasy_api.security.auth import decode_token
from elblasy_api.security.rbac import has_permission
from elblasy_api.security.vault import SecretVault

COOKIE = "elblasy_session"


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def get_vault(settings: Settings = Depends(get_settings)) -> SecretVault:
    return SecretVault(settings.secret_keys)


def current_user(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        raise api_error(401, "unauthenticated", "Sign in required")
    try:
        claims = decode_token(settings.jwt_secret, token)
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise api_error(401, "unauthenticated", "Invalid or expired session") from exc
    if user is None or not user.active or str(user.tenant_id) != claims.get("tid"):
        raise api_error(401, "unauthenticated", "Invalid or expired session")
    return user


def require(permission: str) -> Callable[..., User]:
    def dep(
        request: Request, user: User = Depends(current_user), db: Session = Depends(get_session)
    ) -> User:
        if not has_permission(user.role, permission):
            audit.record(
                db, request, action="authz.denied", outcome="denied", actor=user,
                after={"permission": permission},
            )  # fmt: skip
            db.commit()
            raise api_error(403, "forbidden", "You do not have permission for this action")
        return user

    return dep


def require_any(*permissions: str) -> Callable[..., User]:
    """Allow a user holding at least one of the permissions (checked on the server, audited on denial)."""

    def dep(
        request: Request, user: User = Depends(current_user), db: Session = Depends(get_session)
    ) -> User:
        if not any(has_permission(user.role, p) for p in permissions):
            audit.record(
                db, request, action="authz.denied", outcome="denied", actor=user,
                after={"permission": "|".join(permissions)},
            )  # fmt: skip
            db.commit()
            raise api_error(403, "forbidden", "You do not have permission for this action")
        return user

    return dep
