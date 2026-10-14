# Municipality Hunter

Pulls your activities from Strava, works out which municipalities (Gemeinden / gemeenten) you have visited in **Switzerland** and the **Netherlands**, and shows the routes and visited municipalities on a Leaflet map. A Grafana dashboard with general ride stats comes with it.

## How it works

```
                 Strava API
                     │  refresh token → access token (rotated token is stored in the DB)
                     ▼
  collector  (python -m municipality_hunter sync --loop)
     1. upsert new activities (summary polyline)
     2. backfill high-res polylines, newest first, within the read quota
     3. intersect unprocessed activities with the municipalities in PostGIS
                     │
                     ▼
  PostgreSQL + PostGIS ── activities, municipalities, municipality_parts,
                     │    activity_municipalities, app_state
          ┌──────────┴───────────┐
          ▼                      ▼
  web (Flask/gunicorn :5001)   Grafana (:3000)
  Leaflet map + JSON API       Strava Dashboard + "Municipalities visited"
```

### Visited municipalities

For each activity, the high-res polyline (or the summary polyline if there's no high-res one yet) is split into segments in PostGIS. Segments up to `MAX_SEGMENT_METERS` (default 500 m) count in full. For longer segments only the two end points count. This way a municipality between two GPS points is still detected, but a **GPS jump** (a straight line over many kilometres) doesn't mark everything it crosses as visited. The resulting geometry is stored in `activities.route` and intersected with `municipality_parts` (the boundaries cut into ≤255-vertex pieces by `ST_Subdivide`, which keeps the intersection fast).

The work is incremental. Only activities with `processed_at IS NULL` are processed, which means new ones, ones whose polyline changed, and ones that just got a high-res polyline. Reloading the boundaries resets all of them.

All activity types are stored and intersected. The map filters by `sport_type` and starts with outdoor rides selected (everything ending in `Ride` except `VirtualRide`).

### Strava quota

Strava allows 100 read requests per 15 minutes and 1000 per day. The client reads the remaining quota from the `X-ReadRateLimit-*` headers on every response and stops cleanly when it runs out or gets a 429. The next run continues from there. A first sync of ~1300 activities needs about 7 list requests plus one detail request per activity for the high-res polylines, so the backfill takes a day or two. The map works from the start with the summary polylines.

## Getting started

### 1. Strava API credentials

1. Create an app at <https://www.strava.com/settings/api>. That gives you the client ID and secret. Set "Authorization Callback Domain" to `localhost`.
2. Get a refresh token with the **`activity:read_all`** scope. The token shown on the settings page only has `read` scope and can't see your activities.
   - Open `https://www.strava.com/oauth/authorize?client_id=<CLIENT_ID>&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read_all`
   - Copy `code=` from the URL you are redirected to, then:
     ```bash
     curl -X POST https://www.strava.com/oauth/token \
       -d client_id=<CLIENT_ID> -d client_secret=<CLIENT_SECRET> \
       -d code=<CODE> -d grant_type=authorization_code
     ```
   - Use the `refresh_token` from the response.

### 2. Run with Docker Compose

```bash
cp .env.example .env      # fill in DB_PASSWORD, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
docker compose up -d --build
docker compose logs -f collector
```

- Map: <http://localhost:5001>
- Grafana: <http://localhost:3000> (admin / `GRAFANA_ADMIN_PASSWORD`)

Services: `db` (PostGIS, data in the `db-data` volume), `init` (creates the schema and loads the boundaries on first start, then exits), `collector` (syncs every `SYNC_INTERVAL_SECONDS`), `web`, and `grafana`.

### Run locally without Docker for the app

You need a PostgreSQL with PostGIS ≥ 3.2 (e.g. `docker compose up -d db`).

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
set -a; . ./.env; set +a

python -m municipality_hunter init         # schema + boundaries (--force to reload)
python -m municipality_hunter sync         # one sync run (--loop to keep going)
python -m municipality_hunter web          # http://localhost:5001
pytest                                     # DB tests are skipped if no DB is reachable
```

## Configuration

All settings come from environment variables (`.env` with compose).

| Variable | Default | |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `localhost`, `5432`, `postgres`, `postgres`, – | Compose sets `DB_HOST=db` itself |
| `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN` | – | Strava app and refresh token |
| `SYNC_INTERVAL_SECONDS` | `3600` | Pause between syncs with `--loop` |
| `MAX_SEGMENT_METERS` | `500` | Longer segments count as GPS jumps (only their end points count) |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | |

Strava may hand out a new refresh token when the old one is used. The newest one is kept in the `app_state` table. If you change `REFRESH_TOKEN` in the environment, for example to get a different scope, the new value takes precedence.

## Web API

| Endpoint | Returns |
|---|---|
| `GET /` | the map |
| `GET /api/activity-types` | `[{sport_type, count}]` |
| `GET /api/municipalities` | GeoJSON of all municipalities, simplified to ~30 m (~4 MB, cached for 1 h) |
| `GET /api/visits?types=Ride,GravelRide` | `{municipality_id: {visits, first_visit}}` |
| `GET /api/activities?types=Ride` | `[{id, name, sport_type, date, polyline}]`, polylines simplified to ~5 m |

Leave out `types` to get all activity types. Send `types=` (empty) to get none.

## Database

| Table | Content |
|---|---|
| `activities` | one row per Strava activity (PK `id`): stats used by Grafana, `sport_type`, `polyline`, `polyline_highres`, full `raw_data` JSON, `route` geometry, `processed_at` |
| `municipalities` | `country`, `code` (`BFS_NUMMER` / CBS `statcode`), `name`, `canton` (CH), `population` (CH), `geom`, `geom_simplified` |
| `municipality_parts` | subdivided boundaries used for the intersection |
| `activity_municipalities` | which activity visited which municipality |
| `app_state` | key/value, holds the current Strava refresh token |

`schema.sql` runs on every start and is idempotent. A database from the old `collector.py` version (TimescaleDB hypertable keyed on `(id, time)`) isn't migrated: `init` stops with a message. Use a fresh database. Everything gets re-downloaded from Strava.

## Municipality boundary data

| Country | File | Source | Regenerate with |
|---|---|---|---|
| CH | `assets/municipality-ch.json` (2128 municipalities; the file also contains Liechtenstein and two shared areas, which are skipped) | swisstopo swissBOUNDARIES3D 2025-04 | `ci/swiss-municipality.js` (adapted from [rkaravia/swiss-boundaries-geojson](https://github.com/rkaravia/swiss-boundaries-geojson)): `cd ci && npm install && node swiss-municipality.js`, then copy the municipality layer from `ci/data/geojson/2025/` to `assets/municipality-ch.json` |
| NL | `assets/municipality-nl.json` (342) | CBS gebiedsindelingen via PDOK WFS | `cd ci && ./dutch-municipality.bash 2025` (adapted from [cartomap/nl](https://github.com/cartomap/nl)), which writes `assets/municipality-nl.json` |

After updating a file, run `python -m municipality_hunter init --force` (or `docker compose run --rm init python -m municipality_hunter init --force`). All activities are re-intersected on the next sync.

## Repository layout

| Path | Purpose |
|---|---|
| `municipality_hunter/` | Python package: `config`, `db` + `schema.sql`, `strava` (API client), `sync`, `municipalities` (boundary loader), `web`, `__main__` (CLI) |
| `templates/leaflet.html`, `static/js/map.js` | map front end |
| `tests/` | Strava client tests (mocked HTTP) and PostGIS intersection tests |
| `assets/municipality-*.json` | boundary GeoJSON |
| `assets/total-dashboard.json`, `dashboards.yaml`, `datasources.yaml` | Grafana provisioning |
| `ci/` | scripts that regenerate the boundary data |
| `Dockerfile` | app image (init, collector and web); `grafana.Dockerfile` is the Grafana image |

## Known limitations

- Deleted or edited activities on Strava aren't picked up for anything older than one day before the newest activity.
- Grafana's `$type` filter uses the coarse Strava `activity_type`; the map uses `sport_type`.
- The "Segments" panel in the Grafana dashboard queries a `segments` table that doesn't exist.

## TODO

- [x] fix issue where gps errors count as riding
- [x] Download high res polylines
- [x] Add municipality stats to database
- [x] Store municipality geometries in the database (PostGIS)
- [x] filter map for activity type
- [ ] Count how many municipalities per canton; if all have been ridden, change color of whole canton
- [ ] create pipeline for geojson files
- [ ] create deployment
- [ ] Belgium
