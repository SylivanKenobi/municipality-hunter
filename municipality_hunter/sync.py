import json
import logging
import time
from datetime import datetime

from .db import apply_schema, get_connection, get_state, set_state
from .strava import RateLimitReached, StravaClient

log = logging.getLogger(__name__)

# Re-fetch one day before the newest stored activity; upserts make this safe.
SYNC_OVERLAP_SECONDS = 24 * 3600
INTERSECT_BATCH_SIZE = 100

UPSERT_ACTIVITY_SQL = """
    INSERT INTO activities (
        id, time, name, activity_type, sport_type, polyline, distance, duration,
        avg_speed, max_speed, elevation, max_watts, average_watts,
        weighted_average_watts, year, raw_data
    )
    VALUES (
        %(id)s, %(time)s, %(name)s, %(activity_type)s, %(sport_type)s, %(polyline)s,
        %(distance)s, %(duration)s, %(avg_speed)s, %(max_speed)s, %(elevation)s,
        %(max_watts)s, %(average_watts)s, %(weighted_average_watts)s, %(year)s,
        %(raw_data)s::jsonb
    )
    ON CONFLICT (id) DO UPDATE SET
        time = EXCLUDED.time,
        name = EXCLUDED.name,
        activity_type = EXCLUDED.activity_type,
        sport_type = EXCLUDED.sport_type,
        polyline = EXCLUDED.polyline,
        distance = EXCLUDED.distance,
        duration = EXCLUDED.duration,
        avg_speed = EXCLUDED.avg_speed,
        max_speed = EXCLUDED.max_speed,
        elevation = EXCLUDED.elevation,
        max_watts = EXCLUDED.max_watts,
        average_watts = EXCLUDED.average_watts,
        weighted_average_watts = EXCLUDED.weighted_average_watts,
        year = EXCLUDED.year,
        raw_data = EXCLUDED.raw_data,
        processed_at = CASE
            WHEN activities.polyline_highres IS NULL
                 AND activities.polyline IS DISTINCT FROM EXCLUDED.polyline
            THEN NULL
            ELSE activities.processed_at
        END
"""

# The route used for the intersection: every segment of the (high-res if
# available) polyline, except that segments longer than max_segment_meters
# are replaced by their two end points. A GPS jump therefore can't mark the
# municipalities it "flies" over as visited.
BUILD_ROUTES_SQL = """
    UPDATE activities a SET route = (
        SELECT ST_Collect(
            CASE WHEN ST_Length(s.geom::geography) <= %(max_segment_meters)s
                 THEN s.geom
                 ELSE ST_Points(s.geom)
            END)
        FROM ST_DumpSegments(ST_LineFromEncodedPolyline(
            COALESCE(NULLIF(a.polyline_highres, ''), NULLIF(a.polyline, ''))
        )) s
    )
    WHERE a.id = ANY(%(ids)s)
"""

INTERSECT_SQL = """
    INSERT INTO activity_municipalities (activity_id, municipality_id)
    SELECT DISTINCT a.id, p.municipality_id
    FROM activities a
    JOIN municipality_parts p ON ST_Intersects(a.route, p.geom)
    WHERE a.id = ANY(%(ids)s)
    ON CONFLICT DO NOTHING
"""


def activity_row(activity):
    start = datetime.fromisoformat(activity["start_date"].replace("Z", "+00:00"))
    return {
        "id": activity["id"],
        "time": start,
        "name": activity.get("name"),
        "activity_type": activity["type"],
        "sport_type": activity.get("sport_type") or activity["type"],
        "polyline": (activity.get("map") or {}).get("summary_polyline") or None,
        "distance": activity.get("distance"),
        "duration": activity.get("moving_time"),
        "avg_speed": activity.get("average_speed", 0) * 3.6,
        "max_speed": activity.get("max_speed", 0) * 3.6,
        "elevation": activity.get("total_elevation_gain"),
        "max_watts": activity.get("max_watts", 0),
        "average_watts": activity.get("average_watts", 0),
        "weighted_average_watts": activity.get("weighted_average_watts", 0),
        "year": start.year,
        "raw_data": json.dumps(activity),
    }


def upsert_activities(conn, activities):
    with conn.cursor() as cur:
        for activity in activities:
            cur.execute(UPSERT_ACTIVITY_SQL, activity_row(activity))
    conn.commit()


def sync_activities(conn, client):
    with conn.cursor() as cur:
        cur.execute("SELECT extract(epoch FROM max(time))::bigint FROM activities")
        newest = cur.fetchone()[0]
    after = max(0, newest - SYNC_OVERLAP_SECONDS) if newest else 0

    total = 0
    for page in client.iter_activity_pages(after=after):
        upsert_activities(conn, page)
        total += len(page)
    log.info("Synced %d activities from Strava", total)


def backfill_highres_polylines(conn, client):
    """Fetch the detailed polyline for activities that only have the summary one."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM activities
            WHERE highres_checked_at IS NULL AND polyline IS NOT NULL
            ORDER BY time DESC
        """)
        missing = [row[0] for row in cur.fetchall()]
    if not missing:
        return
    log.info("%d activities without high-res polyline", len(missing))

    fetched = 0
    for activity_id in missing:
        detail = client.get_activity(activity_id)
        polyline_hr = (detail.get("map") or {}).get("polyline") or None
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE activities SET
                    polyline_highres = %(polyline)s,
                    highres_checked_at = now(),
                    processed_at = CASE WHEN %(polyline)s IS NULL THEN processed_at END
                WHERE id = %(id)s
            """, {"id": activity_id, "polyline": polyline_hr})
        conn.commit()
        fetched += 1
    log.info("Fetched %d high-res polylines", fetched)


def compute_visited_municipalities(conn, max_segment_meters):
    """Intersect all unprocessed activities with the municipalities."""
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM municipalities)")
        if not cur.fetchone()[0]:
            log.warning("No municipalities loaded, skipping intersection (run `init` first)")
            return
        cur.execute("SELECT id FROM activities WHERE processed_at IS NULL ORDER BY id")
        pending = [row[0] for row in cur.fetchall()]

    for start in range(0, len(pending), INTERSECT_BATCH_SIZE):
        ids = pending[start:start + INTERSECT_BATCH_SIZE]
        params = {"ids": ids, "max_segment_meters": max_segment_meters}
        with conn.cursor() as cur:
            cur.execute(BUILD_ROUTES_SQL, params)
            cur.execute("DELETE FROM activity_municipalities WHERE activity_id = ANY(%(ids)s)", params)
            cur.execute(INTERSECT_SQL, params)
            cur.execute("UPDATE activities SET processed_at = now() WHERE id = ANY(%(ids)s)", params)
        conn.commit()
        log.info("Computed municipalities for %d/%d activities", start + len(ids), len(pending))


def strava_client(conn, settings):
    # Strava may rotate the refresh token, so the latest one is kept in the
    # database. A changed REFRESH_TOKEN in the environment takes precedence.
    stored = get_state(conn, "strava_refresh_token")
    stored_source = get_state(conn, "strava_refresh_token_source")
    refresh_token = stored if stored and stored_source == settings.refresh_token else settings.refresh_token

    client = StravaClient(settings.client_id, settings.client_secret, refresh_token)
    new_token = client.refresh_access_token()
    if new_token != stored:
        set_state(conn, "strava_refresh_token", new_token)
        set_state(conn, "strava_refresh_token_source", settings.refresh_token)
    return client


def run_sync(settings):
    conn = get_connection(settings)
    try:
        apply_schema(conn)
        client = strava_client(conn, settings)
        try:
            sync_activities(conn, client)
            backfill_highres_polylines(conn, client)
        except RateLimitReached as e:
            log.info("Stopping Strava sync: %s", e)
        compute_visited_municipalities(conn, settings.max_segment_meters)
    finally:
        conn.close()


def run_sync_loop(settings):
    while True:
        try:
            run_sync(settings)
        except Exception:
            log.exception("Sync failed")
        log.info("Next sync in %d s", settings.sync_interval_seconds)
        time.sleep(settings.sync_interval_seconds)
