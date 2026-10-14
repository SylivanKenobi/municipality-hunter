from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from .config import Settings
from .db import get_connection

ROOT = Path(__file__).resolve().parent.parent

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
settings = Settings.from_env()


def query(sql, params=None):
    conn = get_connection(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def requested_types():
    """`?types=Ride,GravelRide` → list, or None for all activity types."""
    types = request.args.get("types")
    if types is None:
        return None
    return [t for t in types.split(",") if t]


@app.route("/")
def index():
    return render_template("leaflet.html")


@app.route("/api/activity-types")
def activity_types():
    rows = query("""
        SELECT sport_type, count(*) FROM activities
        GROUP BY sport_type ORDER BY count(*) DESC
    """)
    return jsonify([{"sport_type": t, "count": c} for t, c in rows])


@app.route("/api/municipalities")
def municipalities():
    # Static boundaries; visits come from /api/visits so filtering is cheap.
    [(geojson,)] = query("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(json_build_object(
                'type', 'Feature',
                'id', id,
                'geometry', ST_AsGeoJSON(geom_simplified, 5)::json,
                'properties', json_build_object(
                    'name', name, 'country', country, 'code', code,
                    'canton', canton, 'population', population)
            )), '[]'::json)
        )::text
        FROM municipalities
    """)
    response = Response(geojson, mimetype="application/geo+json")
    response.cache_control.max_age = 3600
    return response


@app.route("/api/visits")
def visits():
    rows = query("""
        SELECT am.municipality_id, count(*), min(a.time)
        FROM activity_municipalities am
        JOIN activities a ON a.id = am.activity_id
        WHERE %(types)s::text[] IS NULL OR a.sport_type = ANY(%(types)s::text[])
        GROUP BY am.municipality_id
    """, {"types": requested_types()})
    return jsonify({
        str(mid): {"visits": n, "first_visit": first.date().isoformat()}
        for mid, n, first in rows
    })


@app.route("/api/activities")
def activities():
    # Simplified to ~5 m, which looks the same on the map at a fraction of the size.
    rows = query("""
        SELECT id, name, sport_type, time,
               ST_AsEncodedPolyline(ST_Simplify(ST_LineFromEncodedPolyline(encoded), 0.00005))
        FROM (
            SELECT id, name, sport_type, time,
                   COALESCE(NULLIF(polyline_highres, ''), NULLIF(polyline, '')) AS encoded
            FROM activities
            WHERE %(types)s::text[] IS NULL OR sport_type = ANY(%(types)s::text[])
        ) a
        WHERE encoded IS NOT NULL
        ORDER BY time
    """, {"types": requested_types()})
    return jsonify([
        {"id": i, "name": n, "sport_type": t, "date": d.date().isoformat(), "polyline": p}
        for i, n, t, d, p in rows
    ])
