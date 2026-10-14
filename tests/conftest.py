import uuid

import psycopg2
import pytest

from municipality_hunter.config import Settings
from municipality_hunter.db import apply_schema, get_connection


@pytest.fixture
def conn(monkeypatch):
    """Connection to a throwaway schema in the DB from the DB_* variables.

    Tests using it are skipped if no database is reachable. PGOPTIONS makes
    every other connection opened during the test (e.g. by the web app) use
    the same schema.
    """
    schema = f"test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema},public")
    try:
        conn = get_connection(Settings.from_env())
    except psycopg2.OperationalError as e:
        pytest.skip(f"no database: {e}")
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {schema}")
    conn.commit()
    apply_schema(conn)
    yield conn
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA {schema} CASCADE")
    conn.commit()
    conn.close()
