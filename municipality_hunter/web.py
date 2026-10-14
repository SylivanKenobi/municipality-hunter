import logging
import secrets
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from . import auth
from .config import Settings
from .db import clear_state, get_connection, get_state, set_state

log = logging.getLogger(__name__)

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


def back_to_map(error=None):
    return redirect("/" + (f"?{urlencode({'strava_error': error})}" if error else ""))


def callback_url():
    path = url_for("strava_callback")
    return f"{settings.public_url}{path}" if settings.public_url else url_for("strava_callback", _external=True)


@app.route("/api/strava")
def strava_status():
    with closing(get_connection(settings)) as conn:
        return jsonify({
            "configured": bool(settings.client_id and settings.client_secret),
            "connected": auth.current_refresh_token(conn, settings) is not None,
            "athlete": get_state(conn, "strava_athlete"),
        })


@app.route("/auth/strava")
def strava_connect():
    if not (settings.client_id and settings.client_secret):
        return back_to_map("CLIENT_ID and CLIENT_SECRET are not configured, see README")
    # stored in the database rather than a cookie session so it works across gunicorn workers
    state = secrets.token_urlsafe(16)
    with closing(get_connection(settings)) as conn:
        set_state(conn, "oauth_state", state)
    return redirect(auth.authorize_url(settings.client_id, callback_url(), state))


@app.route("/auth/strava/callback")
def strava_callback():
    with closing(get_connection(settings)) as conn:
        expected_state = get_state(conn, "oauth_state")
        clear_state(conn, "oauth_state")
        if not expected_state or request.args.get("state") != expected_state:
            return back_to_map("The Strava login expired, please try again")
        if request.args.get("error"):
            return back_to_map("Access was denied on Strava")
        if auth.REQUIRED_SCOPE not in request.args.get("scope", "").split(","):
            return back_to_map("Please allow access to your activities, including private ones")

        try:
            token = auth.exchange_code(settings.client_id, settings.client_secret, request.args.get("code", ""))
        except Exception:
            log.exception("Strava code exchange failed")
            return back_to_map("Strava rejected the login, check CLIENT_ID and CLIENT_SECRET")

        athlete = token.get("athlete") or {}
        auth.store_refresh_token(conn, settings, token["refresh_token"])
        name = " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")]))
        set_state(conn, "strava_athlete", name or str(athlete.get("id", "")))
        auth.request_sync(conn)
    return back_to_map()


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
                'id', m.id,
                'geometry', ST_AsGeoJSON(m.geom_simplified, 5)::json,
                'properties', json_build_object(
                    'name', m.name, 'country', m.country, 'code', m.code,
                    'canton', c.name, 'population', m.population)
            )), '[]'::json)
        )::text
        FROM municipalities m
        LEFT JOIN cantons c ON c.code = m.canton
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
