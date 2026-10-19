from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elblasy_api import audit
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import COOKIE, api_error, current_user, require
from elblasy_api.models import Tenant, User
from elblasy_api.ratelimit import login_limiter
from elblasy_api.security.auth import hash_password, issue_token, verify_password
from elblasy_api.security.rbac import P_USERS, PERMISSIONS, Role

router = APIRouter(tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class BootstrapIn(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class CreateUserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    role: Role


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    tenant_id: str
    permissions: list[str]


def _out(u: User) -> UserOut:
    perms = sorted(PERMISSIONS.get(Role(u.role), frozenset()))
    return UserOut(
        id=str(u.id), email=u.email, role=u.role, tenant_id=str(u.tenant_id), permissions=perms
    )


def _set_cookie(resp: Response, token: str, s: Settings) -> None:
    resp.set_cookie(
        COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="strict",
        max_age=s.session_ttl_minutes * 60, path="/",
    )  # fmt: skip


@router.post("/auth/bootstrap", status_code=201)
def bootstrap(
    body: BootstrapIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
) -> UserOut:
    """Creates a tenant and its Business Owner. Disabled via ELBLASY_ALLOW_BOOTSTRAP=false."""
    if not s.allow_bootstrap:
        raise api_error(403, "bootstrap_disabled", "Self-registration is disabled")
    tenant = Tenant(name=body.business_name)
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id, email=body.email.lower(), role=Role.OWNER,
        password_hash=hash_password(body.password),
    )  # fmt: skip
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(409, "email_taken", "Email already registered") from exc
    audit.record(db, request, action="tenant.bootstrap", outcome="success", actor=user,
                 target_type="tenant", target_id=tenant.id)  # fmt: skip
    db.commit()
    _set_cookie(
        response, issue_token(s.jwt_secret, user.id, tenant.id, s.session_ttl_minutes * 60), s
    )
    return _out(user)


@router.post("/auth/login")
def login(
    body: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
) -> UserOut:
    email = body.email.lower()
    ip = request.client.host if request.client else "?"
    if not login_limiter.allow(f"{ip}|{email}"):
        raise api_error(429, "rate_limited", "Too many attempts, try again later")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not (ok and user and user.active):
        audit.record(db, request, action="auth.login", outcome="denied",
                     tenant_id=user.tenant_id if user else None, after={"email": email})  # fmt: skip
        db.commit()
        raise api_error(401, "invalid_credentials", "Invalid email or password")
    audit.record(db, request, action="auth.login", outcome="success", actor=user)
    db.commit()
    token = issue_token(s.jwt_secret, user.id, user.tenant_id, s.session_ttl_minutes * 60)
    _set_cookie(response, token, s)
    return _out(user)


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> UserOut:
    return _out(user)


@router.post("/users", status_code=201)
def create_user(
    body: CreateUserIn,
    request: Request,
    actor: User = Depends(require(P_USERS)),
    db: Session = Depends(get_session),
) -> UserOut:
    if body.role == Role.PLATFORM_ADMIN and actor.role != Role.OWNER:
        raise api_error(403, "forbidden", "Only the owner can create administrators")
    user = User(
        tenant_id=actor.tenant_id, email=body.email.lower(), role=body.role,
        password_hash=hash_password(body.password),
    )  # fmt: skip
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(409, "email_taken", "Email already registered") from exc
    audit.record(db, request, action="user.create", outcome="success", actor=actor,
                 target_type="user", target_id=user.id, after={"role": body.role.value})  # fmt: skip
    db.commit()
    return _out(user)
