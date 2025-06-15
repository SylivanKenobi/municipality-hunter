import configparser
import psycopg2
from psycopg2 import sql
import requests
import json
from datetime import datetime
# geo imports
import geopandas as gpd
import polyline
from shapely.geometry import LineString

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

    cur.execute("""
        DROP TABLE IF EXISTS activities;
    """)

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
        year INTEGER
      );
    """)

    cur.execute("""
       SELECT create_hypertable('activities', 'time', if_not_exists => TRUE);
    """)

    print("✅ Table activities created")

def get_all_strava_activities(token):
    all_activities = []
    page = 1
    per_page = 200  # Max per Strava API

    while True:
        print(page)
        url = f"https://www.strava.com/api/v3/athlete/activities?page={page}&per_page={per_page}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            print(f"❌ Failed to fetch page {page}: {response.status_code} - {response.text}")
            break

        activities = response.json()

        if not activities:
            break  # No more data

        all_activities.extend(activities)
        page += 1

    return all_activities


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
                    datetime.fromisoformat(activity['start_date_local'].replace("Z", "+00:00")).year
                ]

                cur.execute(
                    """
                    INSERT INTO activities (
                        time, id, type, distance, duration,
                        avg_speed, max_speed, elevation,
                        max_watts, average_watts, weighted_average_watts, year
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    value
                )
            except Exception as e:
                print(f"❌ Error inserting activity {activity.get('id')}: {e}")

    connection.commit()
    print("✅ All activities written to database.")

def write_activities_to_file(activities, filename="activities.json"):
    with open(filename, "w") as f:
        json.dump(activities, f, indent=2)
    print(f"✅ Saved {len(activities)} activities to '{filename}'")

def read_activities_from_file(filename="activities.json"):
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

def uptodate(token):
    url = f"https://www.strava.com/api/v3/athlete/activities"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    json = JSON.parse(response.body)
    # query database for newest activity

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

def municipality_intersection(activities):
    for activity in activities:
        if activity["map"]["summary_polyline"] == "":
            continue
        decoded_coords = polyline.decode(activity["map"]["summary_polyline"])  # returns list of (lat, lon)

        # Flip to (lon, lat) for Shapely
        line = LineString([(lon, lat) for lat, lon in decoded_coords])

        # Step 2: Load the municipality boundaries from the URL
        geo_df = gpd.read_file("municipality.json")

        # Step 3: Check intersection with each municipality
        intersections = geo_df[geo_df.geometry.intersects(line)]

        if not intersections.empty:
            print("Polyline intersects the following municipalities:")
            print(intersections[["NAME", "geometry"]])
        else:
            print("Polyline does not intersect any municipality.")

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
        if not tables:
            setup_database(connection)

    except Exception as e:
        print("❌ Error connecting to PostgreSQL:", e)
    
    # bearer_token = get_token(config)
    # activities = get_all_strava_activities(bearer_token)
    # write_activities_to_file(activities)
    activities = read_activities_from_file()
    municipality_intersection(activities)
    # insert_activities_to_db(activities, connection)
    # print(activities)
    cur.close()
    connection.close()
    print("🔒 Connection closed.")

if __name__ == "__main__":
    main()
