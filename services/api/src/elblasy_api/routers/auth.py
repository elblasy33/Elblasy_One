import uuid
from datetime import UTC, datetime, timedelta

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
from elblasy_api.security.passwords import check_password_policy
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
    display_name: str | None = Field(default=None, max_length=120)
    temporary: bool = False  # True: the user must choose their own password at first sign-in


class UpdateUserIn(BaseModel):
    role: Role | None = None
    active: bool | None = None
    display_name: str | None = Field(default=None, max_length=120)


class ResetPasswordIn(BaseModel):
    password: str = Field(min_length=12, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    tenant_id: str
    permissions: list[str]
    display_name: str | None = None
    active: bool = True
    must_change_password: bool = False
    last_login_at: datetime | None = None


def _out(u: User) -> UserOut:
    perms = sorted(PERMISSIONS.get(Role(u.role), frozenset()))
    return UserOut(
        id=str(u.id),
        email=u.email,
        role=u.role,
        tenant_id=str(u.tenant_id),
        permissions=perms,
        display_name=u.display_name,
        active=u.active,
        must_change_password=u.must_change_password,
        last_login_at=u.last_login_at,
    )


def _set_cookie(resp: Response, token: str, s: Settings) -> None:
    resp.set_cookie(
        COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="strict",
        max_age=s.session_ttl_minutes * 60, path="/",
    )  # fmt: skip


LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)
PRIVILEGED = (Role.OWNER.value, Role.PLATFORM_ADMIN.value)


def _issue(response: Response, user: User, s: Settings) -> None:
    _set_cookie(
        response,
        issue_token(
            s.jwt_secret, user.id, user.tenant_id, s.session_ttl_minutes * 60, user.token_version
        ),
        s,
    )


def _policy(password: str, email: str) -> None:
    reason = check_password_policy(password, email)
    if reason:
        raise api_error(422, f"weak_password_{reason}", "Choose a stronger password")


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
    _policy(body.password, body.email)
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
    _issue(response, user, s)
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
    now = datetime.now(UTC)
    if user and user.locked_until and user.locked_until > now:
        audit.record(db, request, action="auth.login", outcome="denied", tenant_id=user.tenant_id,
                     after={"email": email, "reason": "locked"})  # fmt: skip
        db.commit()
        raise api_error(
            429, "account_locked", "Too many failed attempts. Try again later or ask the owner"
        )
    ok = verify_password(body.password, user.password_hash if user else None)
    if not (ok and user and user.active):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= LOCK_AFTER:
                user.failed_logins, user.locked_until = 0, now + LOCK_FOR
                audit.record(db, request, action="auth.locked", outcome="denied", actor=user)
        audit.record(db, request, action="auth.login", outcome="denied",
                     tenant_id=user.tenant_id if user else None, after={"email": email})  # fmt: skip
        db.commit()
        raise api_error(401, "invalid_credentials", "Invalid email or password")
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    audit.record(db, request, action="auth.login", outcome="success", actor=user)
    db.commit()
    _issue(response, user, s)
    return _out(user)


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/logout-everywhere", status_code=204)
def logout_everywhere(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> None:
    """Invalidates every session of the caller (e.g. a lost laptop), including this one."""
    user.token_version += 1
    audit.record(db, request, action="auth.logout_everywhere", outcome="success", actor=user)
    db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> UserOut:
    return _out(user)


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
) -> UserOut:
    if not verify_password(body.current_password, user.password_hash):
        audit.record(db, request, action="auth.password_change", outcome="denied", actor=user)
        db.commit()
        raise api_error(403, "wrong_password", "The current password is wrong")
    if body.new_password == body.current_password:
        raise api_error(422, "weak_password_same", "Choose a different password")
    _policy(body.new_password, user.email)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1  # other sessions end; this one continues with a fresh token
    audit.record(db, request, action="auth.password_change", outcome="success", actor=user)
    db.commit()
    _issue(response, user, s)
    return _out(user)


# ---------------- user management (owner / administrator) ----------------
def _tenant_user(db: Session, actor: User, user_id: uuid.UUID) -> User:
    target = db.scalar(select(User).where(User.id == user_id, User.tenant_id == actor.tenant_id))
    if target is None:  # same answer for "missing" and "another shop's user"
        raise api_error(404, "not_found", "User not found")
    return target


def _active_owners(db: Session, tenant_id: uuid.UUID) -> int:
    return int(db.scalar(select(func.count()).select_from(User).where(
        User.tenant_id == tenant_id, User.role == Role.OWNER.value, User.active.is_(True))) or 0)  # fmt: skip


@router.get("/users")
def list_users(
    actor: User = Depends(require(P_USERS)), db: Session = Depends(get_session)
) -> list[UserOut]:
    rows = db.scalars(
        select(User).where(User.tenant_id == actor.tenant_id).order_by(User.created_at)
    )
    return [_out(u) for u in rows]


@router.post("/users", status_code=201)
def create_user(
    body: CreateUserIn,
    request: Request,
    actor: User = Depends(require(P_USERS)),
    db: Session = Depends(get_session),
) -> UserOut:
    if body.role.value in PRIVILEGED and actor.role != Role.OWNER:
        raise api_error(403, "forbidden", "Only the owner can create owners or administrators")
    _policy(body.password, body.email)
    user = User(
        tenant_id=actor.tenant_id, email=body.email.lower(), role=body.role,
        password_hash=hash_password(body.password), display_name=body.display_name,
        must_change_password=body.temporary,
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


@router.patch("/users/{user_id}")
def update_user(
    user_id: uuid.UUID,
    body: UpdateUserIn,
    request: Request,
    actor: User = Depends(require(P_USERS)),
    db: Session = Depends(get_session),
) -> UserOut:
    target = _tenant_user(db, actor, user_id)
    if target.id == actor.id and (body.role is not None or body.active is not None):
        raise api_error(403, "self_change", "You cannot change your own role or status")
    touches_privileged = target.role in PRIVILEGED or (
        body.role is not None and body.role.value in PRIVILEGED
    )
    if touches_privileged and actor.role != Role.OWNER:
        raise api_error(403, "forbidden", "Only the owner can change owners or administrators")
    before = {"role": target.role, "active": target.active}
    new_role = body.role.value if body.role is not None else target.role
    new_active = target.active if body.active is None else body.active
    if (
        target.role == Role.OWNER.value
        and (new_role != Role.OWNER.value or not new_active)
        and _active_owners(db, actor.tenant_id) <= 1
    ):
        raise api_error(409, "last_owner", "The shop must keep at least one active owner")
    changed = new_role != target.role or new_active != target.active
    target.role, target.active = new_role, new_active
    if body.display_name is not None:
        target.display_name = body.display_name.strip() or None
    if changed:
        target.token_version += 1  # their open sessions end now
    audit.record(db, request, action="user.update", outcome="success", actor=actor, target_type="user",
                 target_id=target.id, before=before, after={"role": target.role, "active": target.active})  # fmt: skip
    db.commit()
    return _out(target)


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: uuid.UUID,
    body: ResetPasswordIn,
    request: Request,
    actor: User = Depends(require(P_USERS)),
    db: Session = Depends(get_session),
) -> UserOut:
    """Sets a temporary password; the user must replace it at the next sign-in. Their sessions end."""
    target = _tenant_user(db, actor, user_id)
    if target.id == actor.id:
        raise api_error(403, "self_change", "Use change-password for your own account")
    if target.role in PRIVILEGED and actor.role != Role.OWNER:
        raise api_error(403, "forbidden", "Only the owner can reset an owner or administrator")
    _policy(body.password, target.email)
    target.password_hash = hash_password(body.password)
    target.must_change_password, target.failed_logins, target.locked_until = True, 0, None
    target.token_version += 1
    audit.record(db, request, action="user.reset_password", outcome="success", actor=actor,
                 target_type="user", target_id=target.id)  # fmt: skip
    db.commit()
    return _out(target)
