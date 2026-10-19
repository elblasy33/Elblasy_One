"""HTTP hardening: security headers, CSRF origin check, write rate limits, structured access logs."""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from elblasy_api.config import Settings
from elblasy_api.deps import COOKIE
from elblasy_api.ratelimit import RateLimiter

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
access_log = logging.getLogger("elblasy.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                               "logger": record.name, "msg": record.getMessage()}  # fmt: skip
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger("elblasy")
    if getattr(root, "_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter()
        if settings.log_json
        else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False
    root._configured = True  # type: ignore[attr-defined]


def _error(status: int, code: str, message: str, cid: str | None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "correlation_id": cid}},
    )


def _origin_ok(request: Request, settings: Settings) -> bool:
    allowed = {o.rstrip("/") for o in settings.allowed_origins}
    origin = request.headers.get("origin")
    if origin is None and (ref := request.headers.get("referer")):
        parts = urlsplit(ref)
        origin = f"{parts.scheme}://{parts.netloc}"
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    if (
        origin is None
    ):  # not a browser request; cookies from a browser always carry Origin or Referer
        return not settings.is_production
    if origin.rstrip("/") in allowed:
        return True
    if not allowed and not settings.is_production:
        return True  # development: nothing configured, nothing enforced
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return (
        not allowed and urlsplit(origin).netloc == host
    )  # same-origin deployment without an explicit list


def install(app: FastAPI, settings: Settings) -> None:
    configure_logging(settings)
    writes = (
        RateLimiter(settings.rate_limit_writes_per_min, 60.0)
        if settings.rate_limit_writes_per_min > 0
        else None
    )
    auth = (
        RateLimiter(settings.rate_limit_auth_per_5min, 300.0)
        if settings.rate_limit_auth_per_5min > 0
        else None
    )

    @app.middleware("http")
    async def hardening(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = cid
        ip = request.client.host if request.client else "?"
        response: Response | None = None
        if request.method in UNSAFE:
            if request.cookies.get(COOKIE) and not _origin_ok(request, settings):
                response = _error(403, "csrf_blocked", "Cross-site request refused", cid)
            elif writes and not writes.allow(f"w|{ip}"):
                response = _error(429, "rate_limited", "Too many requests, slow down", cid)
            elif (
                auth
                and request.url.path.startswith(("/auth/", "/users"))
                and not auth.allow(f"a|{ip}")
            ):
                response = _error(429, "rate_limited", "Too many requests, slow down", cid)
        if response is None:
            response = await call_next(request)
        h = response.headers
        h["x-correlation-id"] = cid
        h["x-content-type-options"] = "nosniff"
        h["x-frame-options"] = "DENY"
        h["referrer-policy"] = "no-referrer"
        h["cache-control"] = "no-store"
        h["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.is_production:
            h["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        access_log.info("request", extra={"fields": {"method": request.method, "path": request.url.path, "status": response.status_code,
                                                     "ms": round((time.perf_counter() - start) * 1000, 1), "cid": cid, "ip": ip}})  # fmt: skip
        return response
