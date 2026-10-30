import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from elblasy_api.config import get_settings
from elblasy_api.routers import (
    auth,
    catalog,
    connections,
    customers,
    loyalty,
    money,
    oversight,
    pricelists,
    production,
    purchasing,
    sales,
    scale,
    setup,
    sorders,
    stock,
)
from elblasy_api.security.middleware import install

log = logging.getLogger("elblasy")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Elblasy One API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
    )

    install(app, settings)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        cid = getattr(request.state, "correlation_id", None)
        d = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "error", "message": str(exc.detail)}
        )
        return JSONResponse(
            status_code=exc.status_code, content={"error": {**d, "correlation_id": cid}}
        )

    app.include_router(auth.router)
    app.include_router(connections.router)
    app.include_router(setup.router)
    app.include_router(catalog.router)
    app.include_router(sales.router)
    app.include_router(sorders.router)
    app.include_router(pricelists.router)
    app.include_router(scale.router)
    app.include_router(loyalty.router)
    app.include_router(purchasing.router)
    app.include_router(stock.router)
    app.include_router(money.router)
    app.include_router(oversight.router)
    app.include_router(customers.router)
    app.include_router(production.router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        cid = getattr(request.state, "correlation_id", None)
        log.exception("unhandled error cid=%s", cid)  # stack trace stays server-side
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal error",
                    "correlation_id": cid,
                }
            },
            headers={"x-correlation-id": cid or ""},
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
