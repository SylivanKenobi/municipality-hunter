import configparser
import psycopg2
import requests
import json
from datetime import datetime
import time
from shapely.geometry import Point
import geopandas as gpd
import polyline


# ------------------------------
# Generic Strava API Request
# ------------------------------
def strava_request(url, token, params=None, method="GET", data=None):
    """Generic request wrapper for Strava API with logging."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params or {})
        else:
            response = requests.post(url, headers=headers, data=data or {})
    except requests.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

    # Log request/responseonse details
    print(f"🌐 {method} {url} -> {response.status_code}")
    if not response.ok:
        if "X-RateLimit-Usage" in response.headers and "X-RateLimit-Limit" in response.headers:
            print(f"   Usage: {response.headers['X-ReadRateLimit-Usage']} / Limit: {response.headers['X-ReadRateLimit-Limit']}")
        print(f"   ❌ {response.text}")
        return None

    return response


# ------------------------------
# Strava API helpers
# ------------------------------
def fetch_rate_limits(token):
    """Fetch current rate limit usage."""
    response = strava_request("https://www.strava.com/api/v3/athlete", token)
    if response is None:
        return [0, 0]
    used = list(map(int, response.headers["X-ReadRateLimit-Usage"].split(",")))
    limit = list(map(int, response.headers["X-ReadRateLimit-Limit"].split(",")))
    remaining = [l - u for u, l in zip(used, limit)]
    return remaining  # [15min_remaining, daily_remaining]


def fetch_activity_detail(activity_id, token):
    """Fetch a single activity with high-resolution polyline."""
    url = f"https://www.strava.com/api/v3/activities/{activity_id}"
    response = strava_request(url, token, params={"include_all_efforts": False})
    if response is None:
        return None
    return response.json().get("map", {}).get("polyline")


def fetch_activities(token, after=0, per_page=200):
    """Fetch all activities since `after` timestamp."""
    all_activities = []
    page = 1

    while True:
        print(f"📄 Page {page}")
        url = f"https://www.strava.com/api/v3/athlete/activities"
        response = strava_request(url, token, params={"page": page, "per_page": per_page, "after": after})
        if response is None:
            break

        activities = response.json()
        if not activities:
            break

        all_activities.extend(activities)
        page += 1

    return all_activities


def fetch_latest_activity_id(token):
    """Fetch the newest activity ID from Strava."""
    url = "https://www.strava.com/api/v3/athlete/activities?page=1&per_page=1"
    response = strava_request(url, token)
    if response is None:
        return None
    activities = response.json()
    return activities[0]["id"] if activities else None


# ------------------------------
# Database helpers
# ------------------------------
def get_connection(config):
    conn = psycopg2.connect(
        dbname=config.get('DATABASE', 'PGDATABASE'),
        user=config.get('DATABASE', 'PGUSER'),
        password=config.get('DATABASE', 'PGPASSWORD'),
        host=config.get('DATABASE', 'PGHOST'),
        port=config.get('DATABASE', 'PGPORT')
    )
    return conn


def setup_database(connection):
    cur = connection.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activities (
        time        TIMESTAMPTZ       NOT NULL,
        id          BIGINT            NOT NULL PRIMARY KEY,
        type        TEXT              NOT NULL,
        polyline    TEXT,
        distance    DECIMAL,
        duration    DECIMAL,
        avg_speed   DECIMAL,
        max_speed   DECIMAL,
        elevation   DECIMAL,
        max_watts   DECIMAL,
        average_watts DECIMAL,
        weighted_average_watts DECIMAL,
        year        INTEGER,
        raw_data    JSONB NOT NULL
      );
    """)

    cur.execute("""
       SELECT create_hypertable('activities', 'time', if_not_exists => TRUE);
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_polylines (
        activity_id BIGINT PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
        polyline_highres TEXT NOT NULL,
        fetched_at TIMESTAMPTZ DEFAULT now()
        );
    """)

    print("✅ Tables ensured")


def insert_activities(connection, activities):
    with connection.cursor() as cur:
        for activity in activities:
            try:
                start_time = datetime.fromisoformat(activity['start_date_local'].replace("Z", "+00:00"))
                value = [
                    start_time,
                    activity['id'],
                    activity['type'],
                    activity['map'].get('summary_polyline', None),
                    activity['distance'],
                    activity['moving_time'],
                    activity['average_speed'] * 3.6,
                    activity['max_speed'] * 3.6,
                    activity['total_elevation_gain'],
                    activity.get('max_watts', 0),
                    activity.get('average_watts', 0),
                    activity.get('weighted_average_watts', 0),
                    start_time.year,
                    json.dumps(activity)
                ]

                cur.execute(
                    """
                    INSERT INTO activities (
                        time, id, type, polyline, distance, duration,
                        avg_speed, max_speed, elevation,
                        max_watts, average_watts, weighted_average_watts, year, raw_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    value
                )
            except Exception as e:
                print(f"❌ Error inserting activity {activity.get('id')}: {e}")

    connection.commit()
    print(f"✅ {len(activities)} activities written to database.")


def insert_highres_polylines(connection, token):
    with connection.cursor() as cur:
        cur.execute("""
            SELECT a.id
            FROM activities a
            LEFT JOIN activity_polylines p ON a.id = p.activity_id
            WHERE p.activity_id IS NULL
              AND a.polyline IS NOT NULL
            ORDER BY a.time DESC
        """)
        missing_ids = [row[0] for row in cur.fetchall()]

    if not missing_ids:
        print("✅ All polylines already fetched.")
        return

    remaining_15min, remaining_day = fetch_rate_limits(token)
    max_allowed = min(remaining_15min, remaining_day, len(missing_ids))

    if max_allowed <= 0:
        print("⏳ No quota left for polylines")
        return

    with connection.cursor() as cur:
        for activity_id in missing_ids[:max_allowed]:
            polyline_hr = fetch_activity_detail(activity_id, token)
            if not polyline_hr:
                print(f"⚠️ No polyline for {activity_id}")
                continue
            try:
                cur.execute(
                    """
                    INSERT INTO activity_polylines (activity_id, polyline_highres, fetched_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (activity_id) DO NOTHING
                    """,
                    (activity_id, polyline_hr, datetime.utcnow())
                )
                print(f"✅ Inserted high-res polyline for {activity_id}")
            except Exception as e:
                print(f"❌ Error inserting polyline for {activity_id}: {e}")
                return

    connection.commit()
    print("🏁 Done updating high-res polylines.")


def update_new_activities(token, connection):
    cur = connection.cursor()
    latest_id = fetch_latest_activity_id(token)
    if not latest_id:
        return

    cur.execute("""
        SELECT id, time FROM activities ORDER BY id DESC LIMIT 1;
    """)
    activity_db = cur.fetchall()

    activities = []
    if len(activity_db) == 0:
        activities = fetch_activities(token, after=0)
    elif activity_db[0][0] < latest_id:
        after = int(activity_db[0][1].timestamp())
        activities = fetch_activities(token, after=after)

    insert_activities(connection, activities)


# ------------------------------
# File helpers
# ------------------------------
def write_activities_to_file(activities, filename="assets/activities.json"):
    with open(filename, "w") as f:
        json.dump(activities, f, indent=2)
    print(f"✅ Saved {len(activities)} activities to '{filename}'")


def read_json_file(filename):
    try:
        with open(filename, "r") as f:
            activities = json.load(f)
        print(f"✅ Loaded {len(activities)} activities from '{filename}'")
        return activities
    except FileNotFoundError:
        print(f"❌ File '{filename}' not found.")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON: {e}")
        return []


# ------------------------------
# Token helpers
# ------------------------------
def fetch_token(config):
    url = "https://www.strava.com/api/v3/oauth/token"
    form_data = {
        "client_id": config.get('STRAVA', 'CLIENT_ID'),
        "client_secret": config.get('STRAVA', 'CLIENT_SECRET'),
        "grant_type": "refresh_token",
        "refresh_token": config.get('STRAVA', 'REFRESH_TOKEN')
    }
    response = strava_request(url, token=None, method="POST", data=form_data)
    if response is None:
        return None
    return response.json().get("access_token")


# ------------------------------
# Geospatial helpers
# ------------------------------
def municipality_intersection(connection, municipalities):
    cur = connection.cursor()
    cur.execute("""
        SELECT 
            COALESCE(p.polyline_highres, a.polyline) AS polyline
        FROM activities a
        LEFT JOIN activity_polylines p 
            ON a.id = p.activity_id
    """)
    polylines = cur.fetchall()
    municipalities_intersections = set()

    geo_df = gpd.GeoDataFrame.from_features(municipalities["features"])
    sindex = geo_df.sindex

    for line in polylines:
        decoded_coords = polyline.decode(line[0])
        for lat, lon in decoded_coords:
            point = Point(lon, lat)
            candidate_idx = list(sindex.intersection(point.bounds))
            if not candidate_idx:
                continue
            intersections = geo_df.iloc[candidate_idx][geo_df.iloc[candidate_idx].geometry.contains(point)]
            municipalities_intersections.update(intersections["NAME"].tolist())

    return municipalities_intersections


def append_geojson(intersected_municipalities, municipalities):
    new_features = []
    for municipality in municipalities["features"]:
        if municipality["properties"]["NAME"] in intersected_municipalities:
            municipality["properties"]["visited"] = 1
        else:
            municipality["properties"]["visited"] = 0
        new_features.append(municipality)

    updated = {"type": "FeatureCollection", "features": new_features}
    with open("assets/municipality-merged-updated.json", "w") as f:
        json.dump(updated, f, indent=4)


def get_municipalities():
    chMun = read_json_file("assets/municipality-ch.json")
    nlMun = read_json_file("assets/municipality-nl.json")
    merged = {"type": "FeatureCollection", "features": chMun["features"] + nlMun["features"]}
    return merged


# ------------------------------
# Main
# ------------------------------
def main():
    config = configparser.ConfigParser()
    config.read('config.ini')
    try:
        connection = get_connection(config)
        print("✅ Connected to PostgreSQL!")
        setup_database(connection)
    except Exception as e:
        print("❌ Error connecting to PostgreSQL:", e)
        return

    token = fetch_token(config)
    if not token:
        print("❌ Could not fetch token")
        return

    update_new_activities(token, connection)
    insert_highres_polylines(connection, token)

    municipalities = get_municipalities()
    intersected = municipality_intersection(connection, municipalities)
    append_geojson(intersected, municipalities)

    print("🔒 Connection closed.")


if __name__ == "__main__":
    main()
