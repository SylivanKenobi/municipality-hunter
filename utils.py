import psycopg2
import os
import configparser

# ------------------------------
# Database helpers
# ------------------------------
def get_db_connection():
    load_config()
    conn = psycopg2.connect(
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", 5432)
    )
    return conn

_CONFIG_LOADED = False

def load_config(path="config.ini"):
    """
    Load config.ini values into environment variables.
    Safe to call multiple times.
    """
    global _CONFIG_LOADED
    if _CONFIG_LOADED:
        return

    config = configparser.ConfigParser()
    config.read(path)

    if "DATABASE" in config:
        db = config["DATABASE"]
        print(db)
        os.environ.setdefault("DB_HOST", db.get("PGHOST"))
        os.environ.setdefault("DB_NAME", db.get("PGDATABASE"))
        os.environ.setdefault("DB_USER", db.get("PGUSER"))
        os.environ.setdefault("DB_PASSWORD", db.get("PGPASSWORD"))
        os.environ.setdefault("DB_PORT", db.get("PGPORT", "5432"))
    if "STRAVA" in config:
        strava = config["STRAVA"]
        os.environ.setdefault("CLIENT_ID", strava.get("CLIENT_ID"))
        os.environ.setdefault("CLIENT_SECRET", strava.get("CLIENT_SECRET"))
        os.environ.setdefault("REFRESH_TOKEN", strava.get("REFRESH_TOKEN"))

    _CONFIG_LOADED = True

# TODO only example code
def ingest_geojson(path, country_code, name_key, id_key):
    with open(path) as f:
        data = json.load(f)

    conn = psycopg.connect("postgresql://user:password@localhost:5432/dbname")

    with conn.cursor() as cur:
        for feature in data["features"]:
            props = feature["properties"]
            geom_json = json.dumps(feature["geometry"])

            cur.execute("""
                INSERT INTO municipalities (country_code, name, external_id, geom)
                VALUES (
                    %s,
                    %s,
                    %s,
                    ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                );
            """, (
                country_code,
                props[name_key],
                str(props[id_key]),
                geom_json
            ))

        conn.commit()


# Netherlands
ingest_geojson(
    path="municipality-nl.json",
    country_code="NL",
    name_key="NAME",
    id_key="statcode"
)

# Switzerland
ingest_geojson(
    path="municipality-ch.json",
    country_code="CH",
    name_key="NAME",
    id_key="BFS_NUMMER"
)

# TODO only example code
import psycopg

conn = psycopg.connect("postgresql://user:password@localhost:5432/dbname")

with conn.cursor() as cur:
    cur.execute("""
        CREATE EXTENSION IF NOT EXISTS postgis;

        CREATE TABLE IF NOT EXISTS municipalities (
            id SERIAL PRIMARY KEY,
            country_code TEXT,
            name TEXT,
            external_id TEXT,
            geom GEOMETRY(MULTIPOLYGON, 4326)
        );

        CREATE INDEX IF NOT EXISTS municipalities_geom_idx
        ON municipalities
        USING GIST (geom);
    """)
    conn.commit()