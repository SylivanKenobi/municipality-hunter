from pathlib import Path

import psycopg2

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def get_connection(settings):
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


def apply_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = 'activities'
        """)
        activities_exists = cur.fetchone() is not None
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'activities' AND column_name = 'processed_at'
        """)
        if activities_exists and cur.fetchone() is None:
            raise RuntimeError(
                "Found an 'activities' table from the old collector.py schema. "
                "Drop it (or use a fresh database) and run sync again; "
                "all activities are re-downloaded from Strava."
            )
        cur.execute(SCHEMA_FILE.read_text())
    conn.commit()


def get_state(conn, key):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM app_state WHERE key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def set_state(conn, key, value):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO app_state (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """, (key, value))
    conn.commit()
