import configparser
import psycopg2
from psycopg2 import sql
import requests
import json
from datetime import datetime
from io import BytesIO
import time
# geo imports
from shapely.geometry import Point
import geopandas as gpd
import polyline
from shapely.geometry import LineString

def get_remaining_requests(access_token):
    """Check current rate limits from Strava headers."""
    resp = requests.get(
        "https://www.strava.com/api/v3/athlete",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if "X-RateLimit-Usage" in resp.headers and "X-RateLimit-Limit" in resp.headers:
        used = list(map(int, resp.headers["X-RateLimit-Usage"].split(",")))
        limit = list(map(int, resp.headers["X-RateLimit-Limit"].split(",")))
        print("used/limit")
        print(used)
        print(limit)
        remaining = [l - u for u, l in zip(used, limit)]
        return remaining  # [15min_remaining, daily_remaining]
    return [0, 0]

def fetch_highres_polyline(activity_id, access_token):
    """Fetch one activity with detailed polyline."""
    resp = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"include_all_efforts": False}
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("map", {}).get("polyline")

def insert_highres_polylines(access_token, connection):
    with connection.cursor() as cur:
        # Find activities missing highres polyline
        cur.execute("""
            SELECT a.id
            FROM activities a
            LEFT JOIN activity_polylines p ON a.id = p.activity_id
            WHERE p.activity_id IS NULL
            AND a.polyline != ''
            ORDER BY a.time DESC
        """)
        missing_ids = [row[0] for row in cur.fetchall()]

    if not missing_ids:
        print("✅ All polylines already fetched.")
        return

    # Check API quota
    remaining_15min, remaining_day = get_remaining_requests(access_token)

    max_allowed = min(remaining_15min, remaining_day, len(missing_ids))

    if max_allowed <= 0:
        print("No quota left for Polylines")
        return False
    with connection.cursor() as cur:
        for i, activity_id in enumerate(missing_ids[:max_allowed], start=1):
            try:
                polyline = fetch_highres_polyline(activity_id, access_token)
                if polyline:
                    cur.execute(
                        """
                        INSERT INTO activity_polylines (activity_id, polyline_highres)
                        VALUES (%s, %s)
                        """,
                        (activity_id, polyline)
                    )
                    print(f"✅ Inserted polyline for activity {activity_id}")
                else:
                    print(f"⚠️ No polyline for activity {activity_id}")
            except Exception as e:
                print(f"❌ Error fetching activity {activity_id}: {e}")
                print(response.headers)
                return False

    connection.commit()
    print("🏁 Done updating high-res polylines.")

def get_connection(config):
    # Load connection details from environment variables or use defaults
    dbname = config.get('DATABASE', 'PGDATABASE')
    user = config.get('DATABASE', 'PGUSER')
    password = config.get('DATABASE', 'PGPASSWORD')
    host = config.get('DATABASE', 'PGHOST')
    port = config.get('DATABASE', 'PGPORT')

    # Connect to the PostgreSQL database
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port
    )
    return conn

def setup_database(connection):
    cur = connection.cursor()

    # cur.execute("""
    #     DROP TABLE IF EXISTS activity_polylines;
    # """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activities (
        time        TIMESTAMPTZ       NOT NULL,
        id          bigint           NOT NULL,
        type        text          NOT NULL,
        polyline    text,
        distance    decimal  ,
        duration decimal,
        avg_speed decimal,
        max_speed decimal,
        elevation decimal,
        max_watts decimal,
        average_watts decimal,
        weighted_average_watts decimal,
        year INTEGER,
        raw_data JSONB NOT NULL
      );
    """)

    cur.execute("""
       SELECT create_hypertable('activities', 'time', if_not_exists => TRUE);
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_polylines (
        activity_id BIGINT,
        polyline_highres TEXT NOT NULL
        );
    """)

    print("✅ Table activities created")

def update_activities(token, time):
    all_activities = []
    page = 1
    per_page = 200  # Max per Strava API

    while True:
        print(f"📄 {page}")
        url = f"https://www.strava.com/api/v3/athlete/activities?page={page}&per_page={per_page}&after={time}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            print(f"❌ Failed to fetch page {page}: {response.status_code} - {response.text}")
            print(response.headers)
            break

        activities = response.json()

        if not activities:
            break  # No more data

        all_activities.extend(activities)
        page += 1
    return all_activities


def get_new_activities(bearer_token, connection):
    cur = connection.cursor()
    url = f"https://www.strava.com/api/v3/athlete/activities?page=1&per_page=1"
    headers = {
        "Authorization": f"Bearer {bearer_token}"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"❌ Failed to fetch page: {response.status_code} - {response.text}")
        print(response.headers)
        return False
        
    id = response.json()[0]["id"]

    cur.execute("""
        SELECT id, time FROM activities ORDER BY ID DESC LIMIT 1;
    """)
        
    activity_db = cur.fetchall()

    activities = []
    if len(activity_db) == 0:
        activities = update_activities(bearer_token, 0)
    elif activity_db[0][0] < id:
        time = activity_db[0][1].timestamp()
        activities = update_activities(bearer_token, time)
    
    insert_activities_to_db(activities, connection)

def insert_activities_to_db(activities, connection):
    with connection.cursor() as cur:
        for activity in activities:
            try:
                value = [
                    datetime.fromisoformat(activity['start_date_local'].replace("Z", "+00:00")),
                    activity['id'],
                    activity['type'],
                    activity['map'].get('summary_polyline', 0),
                    activity['distance'],
                    activity['moving_time'],
                    activity['average_speed'] * 3.6,
                    activity['max_speed'] * 3.6,
                    activity['total_elevation_gain'],
                    activity.get('max_watts', 0),
                    activity.get('average_watts', 0),
                    activity.get('weighted_average_watts', 0),
                    datetime.fromisoformat(activity['start_date_local'].replace("Z", "+00:00")).year,
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
                    """,
                    value
                )
            except Exception as e:
                print(f"❌ Error inserting activity {activity.get('id')}: {e}")

    connection.commit()
    print(f"✅ {len(activities)} activities written to database.")

# Has to be done as a batch job to not stress api limits
def get_high_res_polyline(bearer_token, id):
    url = f"https://www.strava.com/api/v3/activities/{id}"
    headers = {
        "Authorization": f"Bearer {bearer_token}"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"❌ Failed to fetch page {id}: {response.status_code} - {response.text}")



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
        
def get_token(config):
    url = f"https://www.strava.com/api/v3/oauth/token"
    form_data = {
            "client_id": config.get('STRAVA', 'CLIENT_ID'),
            "client_secret": config.get('STRAVA', 'CLIENT_SECRET'),
            "grant_type": "refresh_token",
            "refresh_token": config.get('STRAVA', 'REFRESH_TOKEN')
    }

    response = requests.post(url, data=form_data)
    return response.json().get("access_token")

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

    # Load once
    geo_df = gpd.GeoDataFrame.from_features(municipalities["features"])
    sindex = geo_df.sindex  # spatial index

    for line in polylines:
        decoded_coords = polyline.decode(line[0])  # (lat, lon)

        for lat, lon in decoded_coords:
            point = Point(lon, lat)

            # Use spatial index for candidates (fast bounding box check)
            candidate_idx = list(sindex.intersection(point.bounds))
            if not candidate_idx:
                continue

            # Now check actual geometry containment only on candidates
            intersections = geo_df.iloc[candidate_idx][geo_df.iloc[candidate_idx].geometry.contains(point)]

            municipalities_intersections.update(intersections["NAME"].tolist())

    return municipalities_intersections

def append_geojson(intersected_municipalities, municipalities):
    new_features = []
    for municipality in municipalities["features"]:
        if municipality["properties"]["NAME"] in intersected_municipalities:
            municipality["properties"]["visited"] = 1
            new_features.append(municipality)
        else:
            municipality["properties"]["visited"] = 0
            new_features.append(municipality)
    
    updated = {
        "type": "FeatureCollection",
        "features": new_features
    }
    with open("assets/municipality-merged-updated.json", "w") as f:
        json.dump(updated, f, indent=4)

def get_municipalities():
    chMun = read_json_file("assets/municipality-ch.json")
    nlMun = read_json_file("assets/municipality-nl.json")
    merged = {
        "type": "FeatureCollection",
        "features": chMun["features"] + nlMun["features"]
    }
    return merged

def main():
    config = configparser.ConfigParser()
    config.read('config.ini')
    try:
        connection = get_connection(config)
        print("✅ Connected to PostgreSQL!")

        cur = connection.cursor()
        
        # Example query: Get all table names
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        
        tables = cur.fetchall()
        # if not tables:
        setup_database(connection)

    except Exception as e:
        print("❌ Error connecting to PostgreSQL:", e)
    
    bearer_token = get_token(config)
    get_new_activities(bearer_token, connection)

    insert_highres_polylines(bearer_token, connection)

    municipalities = get_municipalities()
    intersected_municipalities = municipality_intersection(connection, municipalities)
    append_geojson(intersected_municipalities, municipalities)

    # print(activities)
    # cur.close()
    # connection.close()
    print("🔒 Connection closed.")

if __name__ == "__main__":
    main()
