"""E2E fixture: fresh platform DB (migrated) + a throwaway copy of the Odoo CE template DB."""

import json
import subprocess
import sys
import uuid
import xmlrpc.client as x
from pathlib import Path

from sqlalchemy import create_engine, text

ADMIN = "postgresql+psycopg://elblasy:elblasy@localhost:5433/postgres"
STATE = Path(__file__).parent / ".state.json"
URL, TEMPLATE, MASTER = "http://localhost:8118", "ce18", "dev-master"


def up() -> None:
    eng = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS elblasy_e2e WITH (FORCE)"))
        c.execute(text("CREATE DATABASE elblasy_e2e"))
    env = {"ELBLASY_DATABASE_URL": "postgresql+psycopg://elblasy:elblasy@localhost:5433/elblasy_e2e"}
    import os

    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env={**os.environ, **env}, capture_output=True)
    name = f"e2e_{uuid.uuid4().hex[:8]}"
    x.ServerProxy(URL + "/xmlrpc/2/db").duplicate_database(MASTER, TEMPLATE, name)
    STATE.write_text(json.dumps({"odoo_url": URL, "odoo_db": name}))


def down() -> None:
    if STATE.exists():
        st = json.loads(STATE.read_text())
        x.ServerProxy(st["odoo_url"] + "/xmlrpc/2/db").drop(MASTER, st["odoo_db"])
        STATE.unlink()
    eng = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS elblasy_e2e WITH (FORCE)"))


if __name__ == "__main__":
    {"up": up, "down": down}[sys.argv[1]]()
