"""Platform tests run against a real PostgreSQL (infrastructure/docker/compose.platform.yml).
The schema is built by running the Alembic migrations, so migrations are tested too."""

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

ADMIN_URL = os.getenv(
    "TEST_PG_ADMIN_URL", "postgresql+psycopg://elblasy:elblasy@localhost:5433/postgres"
)
JWT = "test-jwt-secret-0123456789-0123456789"
KEY = Fernet.generate_key().decode()


@pytest.fixture(scope="session")
def pg_url():
    name = f"elblasy_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception:
        pytest.skip("platform PostgreSQL not reachable")
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    os.environ.update(
        ELBLASY_DATABASE_URL=url, ELBLASY_JWT_SECRET=JWT, ELBLASY_SECRET_KEYS=KEY,
        ELBLASY_ENVIRONMENT="test", ELBLASY_COOKIE_SECURE="false", ELBLASY_RATE_LIMIT_WRITES_PER_MIN="0",
        ELBLASY_RATE_LIMIT_AUTH_PER_5MIN="0", ELBLASY_LOG_JSON="false",
        ELBLASY_ALLOW_PRIVATE_ODOO_HOSTS="true", ELBLASY_ALLOW_INSECURE_ODOO_HTTP="true",
    )  # fmt: skip
    from elblasy_api.config import get_settings
    from elblasy_api.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    yield url
    get_engine().dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.fixture
def client(pg_url):
    from fastapi.testclient import TestClient

    from elblasy_api.main import create_app
    from elblasy_api.ratelimit import login_limiter

    login_limiter.reset()
    return TestClient(create_app())


def make_owner(client, email, business="Biz"):
    r = client.post(
        "/auth/bootstrap",
        json={"business_name": business, "email": email, "password": "correct-horse-battery"},
    )
    assert r.status_code == 201, r.text
    return r.json()
