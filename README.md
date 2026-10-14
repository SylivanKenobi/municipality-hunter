# Municipality Hunter

Pulls your activities from Strava, works out which municipalities (Gemeinden / gemeenten) you have visited in **Switzerland** and the **Netherlands**, and shows the routes and visited municipalities on a Leaflet map. A Grafana dashboard with general ride stats comes with it.

## How it works

```
                 Strava API ◄──────── "Connect with Strava" (OAuth, via web)
                     │  refresh token from app_state → access token
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

### Cantons

The panel at the bottom left shows visited / total per country, plus a **Cantons** list with visited / total for each Swiss canton, sorted by share visited. Click a canton to zoom to it. Hovering a municipality also shows its canton's progress. Once every municipality of a canton is visited, the whole canton turns **gold** on the map and gets a ✓ in the list. The counts follow the activity-type filter, so a canton can be complete for rides but not for runs.

### Strava quota

Strava limits how many requests an API application may make per 15 minutes and per day; the current limits are shown on your [API settings page](https://www.strava.com/settings/api). The client reads the remaining quota from the `X-ReadRateLimit-*` headers on every response and stops cleanly when it runs out or gets a 429. The next run continues from there. A first sync of ~1300 activities needs about 7 list requests plus one detail request per activity for the high-res polylines, so the backfill takes a day or two. The map works from the start with the summary polylines.

## Getting started

### 1. Create a Strava API application (once)

Strava only gives API access through an "API application" registered to your account. Create one as described in [Setting up your own Strava API application](#setting-up-your-own-strava-api-application). For running locally, that comes down to: create the app at <https://www.strava.com/settings/api> with **Authorization Callback Domain** `localhost`, and copy its **Client ID** and **Client Secret**.

### 2. Run with Docker Compose

```bash
cp .env.example .env      # fill in DB_PASSWORD, CLIENT_ID, CLIENT_SECRET
docker compose up -d --build
```

- Map: <http://localhost:5001>
- Grafana: <http://localhost:3000> (admin / `GRAFANA_ADMIN_PASSWORD`)

Services: `db` (PostGIS, data in the `db-data` volume), `init` (creates the schema and loads the boundaries on first start, then exits), `collector` (syncs every `SYNC_INTERVAL_SECONDS`), `web`, and `grafana`.

### 3. Connect with Strava

Open the map and click **Connect with Strava** (top left), then approve on Strava. Keep "View data about your private activities" ticked, because the app needs the `activity:read_all` scope. Strava sends you back to the map, the refresh token is stored in the database, and the collector starts syncing within about 30 seconds instead of waiting for its hourly run. Reload the map after a minute to see your rides. The detailed routes keep filling in over the next day or two (see [Strava quota](#strava-quota)).

The panel then shows "Connected to Strava as …". Use **Reconnect** if the connection was revoked or the collector log says the token refresh failed. Follow progress with `docker compose logs -f collector`.

One installation is meant for one Strava account. Connecting a different account replaces the token, and that account's activities are then added to the same map.

<details>
<summary>Without the button: getting a refresh token by hand</summary>

1. Open `https://www.strava.com/oauth/authorize?client_id=<CLIENT_ID>&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read_all`
2. Copy `code=` from the URL you are redirected to (the page itself fails to load), then:
   ```bash
   curl -X POST https://www.strava.com/oauth/token \
     -d client_id=<CLIENT_ID> -d client_secret=<CLIENT_SECRET> \
     -d code=<CODE> -d grant_type=authorization_code
   ```
3. Put the `refresh_token` from the response into `.env` as `REFRESH_TOKEN` and restart the collector. A changed `REFRESH_TOKEN` takes precedence over the token stored in the database.

</details>

### Run locally without Docker for the app

You need a PostgreSQL with PostGIS ≥ 3.2 (e.g. `docker compose up -d db`).

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
set -a; . ./.env; set +a

python -m municipality_hunter init         # schema + boundaries (reloads after a data update)
python -m municipality_hunter sync         # one sync run (--loop to keep going)
python -m municipality_hunter web          # http://localhost:5001, then "Connect with Strava"
pytest                                     # DB tests are skipped if no DB is reachable
```

## Configuration

All settings come from environment variables (`.env` with compose).

| Variable | Default | |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `localhost`, `5432`, `postgres`, `postgres`, – | Compose sets `DB_HOST=db` itself |
| `CLIENT_ID`, `CLIENT_SECRET` | – | Your Strava API application |
| `PUBLIC_URL` | – | Public base URL of the map, e.g. `https://hunter.example.org`. Only needed when the web app can't tell it from the request (behind a reverse proxy); Strava redirects to `<PUBLIC_URL>/auth/strava/callback` |
| `REFRESH_TOKEN` | – | Optional, a hand-made refresh token instead of the button |
| `SYNC_INTERVAL_SECONDS` | `3600` | Pause between syncs with `--loop` |
| `MAX_SEGMENT_METERS` | `500` | Longer segments count as GPS jumps (only their end points count) |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | |

The refresh token from "Connect with Strava" is kept in the `app_state` table. Strava may hand out a new one when it is used, and the newest one is always stored there. If you set or change `REFRESH_TOKEN` in the environment, that value takes precedence until the next connect.

## Setting up your own Strava API application

You need this whether you run the app on your laptop or deploy it somewhere. Each installation uses its own API application, and the client secret must never be shared.

1. **Prerequisites.** A Strava account. According to [Strava's getting-started guide](https://developers.strava.com/docs/getting-started/), creating API applications requires a Strava subscription.
2. **Create the application** at <https://www.strava.com/settings/api>:
   - **Application Name**: anything, but Strava's [brand guidelines](https://developers.strava.com/guidelines/) don't allow "Strava" in the name. Something like "Municipality Hunter (yourname)" works.
   - **Category**: e.g. "Visualizer".
   - **Website**: your deployment's URL, or any URL you own (e.g. your GitHub repo) for local use.
   - **Authorization Callback Domain**: the *host name only*, without `https://`, port or path.
     - local: `localhost`
     - deployed: the domain the map runs under, e.g. `hunter.example.org`
   - Upload an icon if asked; it's shown on Strava's approval page.
3. **Copy the Client ID and Client Secret** from the same page into `.env` as `CLIENT_ID` and `CLIENT_SECRET`, then run `docker compose up -d` again so the containers pick them up. Don't copy the "Your Access Token" / "Your Refresh Token" values shown there: they only have the `read` scope and can't see activities. Use the button instead.
4. Open the map and click **Connect with Strava**.

**Athlete capacity.** New applications start in single-player mode: only the account that owns the application can connect. That is all this app needs. Strava lets you upgrade to 10 athletes from the API settings page, and beyond that only after a review. In June 2026 apps that upgraded briefly got `500 {"message":"error"}` on every API call ([community thread](https://communityhub.strava.com/developers-api-7/all-api-requests-return-http-500-after-upgrade-to-standard-tier-13436)), so don't upgrade unless you need to.

**Rate limits** apply per application, not per athlete (see [Strava quota](#strava-quota)).

### Deploying beyond your own machine

The web app has **no login**. It assumes it runs locally and only you can reach it. Anyone who can open the map can see your rides and can click "Connect with Strava" to replace your token with theirs. If you deploy it on a server:

- Put it behind a reverse proxy that handles HTTPS **and** authentication (e.g. Caddy or nginx with basic auth, or an SSO proxy like oauth2-proxy). Protect the whole site, including `/auth/strava/callback`. The redirect comes from your own browser, so it passes the same login.
- Set `PUBLIC_URL` to the external URL (e.g. `https://hunter.example.org`). Otherwise the app builds the callback URL from the request it sees behind the proxy. That is usually the internal address (`http://web:5001`), or `http://` instead of `https://`, and Strava rejects it or the redirect fails.
- Set the application's **Authorization Callback Domain** to that domain.
- Change `DB_PASSWORD` and `GRAFANA_ADMIN_PASSWORD`, and don't publish the database port (`5432`) to the internet. Remove it from `compose.yaml` if you don't need it.
- If the page is publicly visible, Strava's [brand guidelines](https://developers.strava.com/guidelines/) ask you to use the official "Connect with Strava" button graphic instead of the plain orange link.

## Web API

| Endpoint | Returns |
|---|---|
| `GET /` | the map |
| `GET /auth/strava` | redirects to Strava's approval page ("Connect with Strava") |
| `GET /auth/strava/callback` | Strava redirects back here; stores the token and requests a sync |
| `GET /api/strava` | `{configured, connected, athlete}` |
| `GET /api/activity-types` | `[{sport_type, count}]` |
| `GET /api/municipalities` | GeoJSON of all municipalities with `name`, `country`, `code`, `canton` (name, CH only) and `population`, simplified to ~30 m (~4 MB, cached for 1 h) |
| `GET /api/visits?types=Ride,GravelRide` | `{municipality_id: {visits, first_visit}}` |
| `GET /api/activities?types=Ride` | `[{id, name, sport_type, date, polyline}]`, polylines simplified to ~5 m |

Leave out `types` to get all activity types. Send `types=` (empty) to get none.

## Database

| Table | Content |
|---|---|
| `activities` | one row per Strava activity (PK `id`): stats used by Grafana, `sport_type`, `polyline`, `polyline_highres`, full `raw_data` JSON, `route` geometry, `processed_at` |
| `municipalities` | `country`, `code` (`BFS_NUMMER` / CBS `statcode`), `name`, `canton` (CH), `population` (CH), `geom`, `geom_simplified` |
| `cantons` | the 26 Swiss cantons by BFS number (`code`, `abbreviation`, `name`), filled by `schema.sql` |
| `municipality_parts` | subdivided boundaries used for the intersection |
| `activity_municipalities` | which activity visited which municipality |
| `app_state` | key/value: Strava refresh token, connected athlete name, pending OAuth `state`, `sync_requested` flag |

`schema.sql` runs on every start and is idempotent. A database from the old `collector.py` version (TimescaleDB hypertable keyed on `(id, time)`) isn't migrated: `init` stops with a message. Use a fresh database. Everything gets re-downloaded from Strava.

## Municipality boundary data

| Country | File | Source |
|---|---|---|
| CH | `assets/municipality-ch.json`. Layer `HOHEITSGEBIET`; besides the Swiss municipalities it contains the municipalities of Liechtenstein, the German and Italian exclaves Büsingen and Campione, and shared areas. The loader skips all of these. | swisstopo [swissBOUNDARIES3D](https://www.swisstopo.admin.ch/en/landscape-model-swissboundaries3d), latest release from the [STAC API](https://data.geo.admin.ch/api/stac/v1/collections/ch.swisstopo.swissboundaries3d/items), reprojected from LV95 to WGS84 |
| NL | `assets/municipality-nl.json`. `statnaam` is renamed to `NAME`. | CBS gebiedsindelingen via PDOK WFS, layer `gemeente_gegeneraliseerd` of the newest year |

`assets/municipality-sources.json` records which release is in the repository, e.g. `{"ch": "swissboundaries3d_2026-01", "nl": "2026"}`.

### Automatic updates

The GitHub workflow [`update-municipalities`](.github/workflows/update-municipalities.yml) runs on the 1st of every month (GitHub's cron can't express "every 30 days") and can also be started by hand under *Actions → Update municipality data → Run workflow*. It:

1. runs `ci/update-municipalities.sh`, which only downloads a dataset when its release differs from `municipality-sources.json`;
2. if anything changed, loads the new files into a PostGIS service container with `municipality_hunter init --force`, checks the counts and runs the tests;
3. opens a pull request from the branch `update/municipality-data`, or updates the open one.

Most months nothing changes and no PR is created. swisstopo publishes about once or twice a year and CBS once a year.

**One-time repository setting:** under *Settings → Actions → General → Workflow permissions*, enable **"Allow GitHub Actions to create and approve pull requests"**. Without it, the last step fails with "GitHub Actions is not permitted to create or approve pull requests". PRs created by the workflow don't trigger other workflows, which is why the checks run inside the update job.

After merging the PR, restart the stack (`docker compose up -d --build`). `init` sees that `municipality-sources.json` changed and reloads the boundaries. Merged municipalities are removed, and all activities are re-intersected on the next sync.

### Updating by hand

```bash
sudo apt-get install gdal-bin jq          # or: brew install gdal jq
ci/update-municipalities.sh               # --force to regenerate even without a new release
python -m municipality_hunter init        # reloads because the release changed
```

## Repository layout

| Path | Purpose |
|---|---|
| `municipality_hunter/` | Python package: `config`, `db` + `schema.sql`, `strava` (API client), `auth` (OAuth and token storage), `sync`, `municipalities` (boundary loader), `web`, `__main__` (CLI) |
| `templates/leaflet.html`, `static/js/map.js` | map front end |
| `tests/` | Strava client tests (mocked HTTP), the connect flow, and PostGIS intersection tests |
| `assets/municipality-*.json` | boundary GeoJSON |
| `assets/total-dashboard.json`, `dashboards.yaml`, `datasources.yaml` | Grafana provisioning |
| `ci/update-municipalities.sh` | downloads new boundary releases (used by the workflow) |
| `.github/workflows/update-municipalities.yml` | monthly boundary update PR |
| `Dockerfile` | app image (init, collector and web); `grafana.Dockerfile` is the Grafana image |

## Known limitations

- Deleted or edited activities on Strava aren't picked up for anything older than one day before the newest activity.

## TODO

- [x] fix issue where gps errors count as riding
- [x] Download high res polylines
- [x] Add municipality stats to database
- [x] Store municipality geometries in the database (PostGIS)
- [x] filter map for activity type
- [x] Count how many municipalities per canton; if all have been ridden, change color of whole canton
- [x] create pipeline for geojson files
- [ ] create deployment
- [ ] Belgium
