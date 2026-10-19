from fastapi.testclient import TestClient

from elblasy_api.main import create_app


def test_health_and_correlation_id():
    c = TestClient(create_app())
    r = c.get("/healthz", headers={"x-correlation-id": "abc"})
    assert r.status_code == 200 and r.headers["x-correlation-id"] == "abc"


def test_unhandled_error_hides_stack():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret detail")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and "secret detail" not in r.text
    assert r.json()["error"]["correlation_id"]
