"""Intersection tests against a real PostGIS database (see conftest.py)."""
from municipality_hunter.municipalities import load_municipalities
from municipality_hunter.sync import compute_visited_municipalities, upsert_activities


def encode(coords):
    """Google polyline encoding of (lat, lon) pairs."""
    result, prev_lat, prev_lon = [], 0, 0
    for lat, lon in coords:
        for value, prev in ((round(lat * 1e5), prev_lat), (round(lon * 1e5), prev_lon)):
            delta = value - prev
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                result.append(chr((0x20 | (delta & 0x1f)) + 63))
                delta >>= 5
            result.append(chr(delta + 63))
        prev_lat, prev_lon = round(lat * 1e5), round(lon * 1e5)
    return "".join(result)


def square(lon, lat, size):
    return {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat],
    ]]}


def activity(activity_id, coords):
    return {
        "id": activity_id, "name": "Test", "type": "Ride", "sport_type": "Ride",
        "start_date": "2025-06-01T08:00:00Z", "distance": 1000.0, "moving_time": 600,
        "average_speed": 5.0, "max_speed": 10.0, "total_elevation_gain": 10.0,
        "map": {"summary_polyline": encode(coords)},
    }


def visited(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT am.activity_id, m.code FROM activity_municipalities am
            JOIN municipalities m ON m.id = am.municipality_id ORDER BY 1, 2
        """)
        return cur.fetchall()


def test_segments_count_but_gps_jumps_do_not(conn):
    # A: ~1 km square at (8.0, 47.0). B: a small square ~5 km east of A.
    # C: a tiny municipality between two GPS points that are 200 m apart.
    def source():
        yield {"country": "CH", "code": "A", "name": "A", "canton": "1", "population": 1,
               "geometry": square(8.0, 47.0, 0.01)}
        yield {"country": "CH", "code": "B", "name": "B", "canton": "1", "population": 1,
               "geometry": square(8.03, 46.995, 0.02)}
        yield {"country": "CH", "code": "C", "name": "C", "canton": "1", "population": 1,
               "geometry": square(8.0005, 46.9905, 0.0005)}
    load_municipalities(conn, sources=(source,))

    upsert_activities(conn, [
        # rides inside A, then jumps ~5 km straight across B and back:
        # the jump segments must not mark B as visited
        activity(1, [(47.005, 8.002), (47.005, 8.006), (47.005, 8.07), (47.005, 8.008)]),
        # two points south of A, 200 m apart, the segment crosses C
        activity(2, [(46.9907, 7.9998), (46.9907, 8.0024)]),
    ])
    compute_visited_municipalities(conn, max_segment_meters=500)

    assert visited(conn) == [(1, "A"), (2, "C")]


def test_reloading_municipalities_marks_activities_for_reprocessing(conn):
    def source():
        yield {"country": "NL", "code": "GM1", "name": "X", "canton": None, "population": None,
               "geometry": square(5.0, 52.0, 0.01)}
    load_municipalities(conn, sources=(source,))
    upsert_activities(conn, [activity(1, [(52.005, 5.002), (52.005, 5.004)])])
    compute_visited_municipalities(conn, max_segment_meters=500)
    assert visited(conn) == [(1, "GM1")]

    load_municipalities(conn, sources=(source,))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM activities WHERE processed_at IS NULL")
        assert cur.fetchone()[0] == 1


def test_reloading_removes_merged_municipalities(conn):
    def before():
        yield {"country": "CH", "code": "1", "name": "Old", "canton": "1", "population": 1,
               "geometry": square(8.0, 47.0, 0.01)}
        yield {"country": "CH", "code": "2", "name": "Kept", "canton": "1", "population": 1,
               "geometry": square(8.1, 47.0, 0.01)}
        yield {"country": "NL", "code": "GM1", "name": "Other country", "canton": None,
               "population": None, "geometry": square(5.0, 52.0, 0.01)}

    def after():
        yield {"country": "CH", "code": "2", "name": "Kept", "canton": "1", "population": 1,
               "geometry": square(8.1, 47.0, 0.01)}

    load_municipalities(conn, sources=(before,))
    load_municipalities(conn, sources=(after,))
    with conn.cursor() as cur:
        cur.execute("SELECT country, code FROM municipalities ORDER BY 1, 2")
        assert cur.fetchall() == [("CH", "2"), ("NL", "GM1")]
