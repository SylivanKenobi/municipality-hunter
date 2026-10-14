import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def swiss_municipalities(path=ASSETS_DIR / "municipality-ch.json"):
    with open(path) as f:
        features = json.load(f)["features"]
    for feature in features:
        props = feature["properties"]
        # the file also contains Liechtenstein and shared areas (Kommunanz)
        if props["OBJEKTART"] != "Gemeindegebiet":
            continue
        yield {
            "country": "CH",
            "code": str(props["BFS_NUMMER"]),
            "name": props["NAME"],
            "canton": str(props["KANTONSNUM"]),
            "population": props.get("EINWOHNERZ"),
            "geometry": feature["geometry"],
        }


def dutch_municipalities(path=ASSETS_DIR / "municipality-nl.json"):
    with open(path) as f:
        features = json.load(f)["features"]
    for feature in features:
        props = feature["properties"]
        yield {
            "country": "NL",
            "code": props["statcode"],
            "name": props["NAME"],
            "canton": None,
            "population": None,
            "geometry": feature["geometry"],
        }


SOURCES = (swiss_municipalities, dutch_municipalities)
# releases of the files above, written by ci/update-municipalities.sh
SOURCE_VERSIONS = ASSETS_DIR / "municipality-sources.json"


def source_versions():
    try:
        return json.dumps(json.loads(SOURCE_VERSIONS.read_text()), sort_keys=True)
    except FileNotFoundError:
        return ""


UPSERT_MUNICIPALITY_SQL = """
    WITH g AS (
        SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(
            ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326))), 3)) AS geom
    )
    INSERT INTO municipalities (country, code, name, canton, population, geom, geom_simplified)
    SELECT %(country)s, %(code)s, %(name)s, %(canton)s, %(population)s, g.geom,
           ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SimplifyPreserveTopology(g.geom, 0.0003)), 3))
    FROM g
    ON CONFLICT (country, code) DO UPDATE SET
        name = EXCLUDED.name,
        canton = EXCLUDED.canton,
        population = EXCLUDED.population,
        geom = EXCLUDED.geom,
        geom_simplified = EXCLUDED.geom_simplified
    RETURNING id
"""


def municipalities_loaded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM municipalities)")
        return cur.fetchone()[0]


def load_municipalities(conn, sources=SOURCES):
    """Load (or reload) the boundary files and mark all activities for re-processing."""
    with conn.cursor() as cur:
        for source in sources:
            count = 0
            loaded = {}
            for municipality in source():
                loaded.setdefault(municipality["country"], []).append(municipality["code"])
                params = dict(municipality, geometry=json.dumps(municipality["geometry"]))
                cur.execute(UPSERT_MUNICIPALITY_SQL, params)
                municipality_id = cur.fetchone()[0]
                cur.execute("DELETE FROM municipality_parts WHERE municipality_id = %s", (municipality_id,))
                cur.execute("""
                    INSERT INTO municipality_parts (municipality_id, geom)
                    SELECT id, ST_Subdivide(geom, 255) FROM municipalities WHERE id = %s
                """, (municipality_id,))
                count += 1
            # municipalities that merged or were dissolved since the last load
            for country, codes in loaded.items():
                cur.execute("DELETE FROM municipalities WHERE country = %s AND code <> ALL(%s)", (country, codes))
                if cur.rowcount:
                    log.info("Removed %d municipalities from %s that no longer exist", cur.rowcount, country)
            log.info("Loaded %d municipalities from %s", count, source.__name__)
        cur.execute("UPDATE activities SET processed_at = NULL")
    conn.commit()
