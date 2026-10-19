import time
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()
_DUMMY = _ph.hash("dummy-password-for-timing")


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str | None) -> bool:
    """Constant-ish time: always verifies against some hash to blunt user enumeration."""
    try:
        return _ph.verify(hashed or _DUMMY, pw) and hashed is not None
    except (VerificationError, InvalidHashError):
        return False


def issue_token(
    secret: str, user_id: uuid.UUID, tenant_id: uuid.UUID, ttl_s: int, version: int = 0
) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "tv": version,
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
