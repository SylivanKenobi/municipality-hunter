-- Idempotent schema, applied on every start (see db.apply_schema).

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS activities (
    id                      BIGINT       PRIMARY KEY,
    time                    TIMESTAMPTZ  NOT NULL,
    name                    TEXT,
    activity_type           TEXT         NOT NULL,
    sport_type              TEXT,
    polyline                TEXT,
    polyline_highres        TEXT,
    -- set once the detail endpoint was asked for a high-res polyline,
    -- so activities without one are not requested again
    highres_checked_at      TIMESTAMPTZ,
    distance                DECIMAL,
    duration                DECIMAL,
    avg_speed               DECIMAL,
    max_speed               DECIMAL,
    elevation               DECIMAL,
    max_watts               DECIMAL,
    average_watts           DECIMAL,
    weighted_average_watts  DECIMAL,
    year                    INTEGER,
    raw_data                JSONB        NOT NULL,
    -- route used for the municipality intersection, GPS jumps removed
    route                   geometry(Geometry, 4326),
    -- NULL = municipalities for this activity still have to be computed
    processed_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS activities_time_idx ON activities (time);
CREATE INDEX IF NOT EXISTS activities_pending_idx ON activities (id) WHERE processed_at IS NULL;

CREATE TABLE IF NOT EXISTS municipalities (
    id               SERIAL       PRIMARY KEY,
    country          CHAR(2)      NOT NULL,
    code             TEXT         NOT NULL,
    name             TEXT         NOT NULL,
    canton           TEXT,
    population       INTEGER,
    geom             geometry(MultiPolygon, 4326) NOT NULL,
    -- lighter geometry for the web map
    geom_simplified  geometry(MultiPolygon, 4326) NOT NULL,
    UNIQUE (country, code)
);

CREATE INDEX IF NOT EXISTS municipalities_geom_idx ON municipalities USING GIST (geom);

-- Swiss cantons by BFS number (municipalities.canton)
CREATE TABLE IF NOT EXISTS cantons (
    code          TEXT PRIMARY KEY,
    abbreviation  TEXT NOT NULL,
    name          TEXT NOT NULL
);

INSERT INTO cantons (code, abbreviation, name) VALUES
    ('1', 'ZH', 'Zürich'), ('2', 'BE', 'Bern'), ('3', 'LU', 'Luzern'), ('4', 'UR', 'Uri'),
    ('5', 'SZ', 'Schwyz'), ('6', 'OW', 'Obwalden'), ('7', 'NW', 'Nidwalden'), ('8', 'GL', 'Glarus'),
    ('9', 'ZG', 'Zug'), ('10', 'FR', 'Fribourg'), ('11', 'SO', 'Solothurn'), ('12', 'BS', 'Basel-Stadt'),
    ('13', 'BL', 'Basel-Landschaft'), ('14', 'SH', 'Schaffhausen'), ('15', 'AR', 'Appenzell Ausserrhoden'),
    ('16', 'AI', 'Appenzell Innerrhoden'), ('17', 'SG', 'St. Gallen'), ('18', 'GR', 'Graubünden'),
    ('19', 'AG', 'Aargau'), ('20', 'TG', 'Thurgau'), ('21', 'TI', 'Ticino'), ('22', 'VD', 'Vaud'),
    ('23', 'VS', 'Valais'), ('24', 'NE', 'Neuchâtel'), ('25', 'GE', 'Genève'), ('26', 'JU', 'Jura')
ON CONFLICT (code) DO UPDATE SET abbreviation = EXCLUDED.abbreviation, name = EXCLUDED.name;

-- municipalities cut into small pieces, which makes ST_Intersects much faster
CREATE TABLE IF NOT EXISTS municipality_parts (
    municipality_id  INTEGER NOT NULL REFERENCES municipalities (id) ON DELETE CASCADE,
    geom             geometry(Polygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS municipality_parts_geom_idx ON municipality_parts USING GIST (geom);

CREATE TABLE IF NOT EXISTS activity_municipalities (
    activity_id      BIGINT  NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    municipality_id  INTEGER NOT NULL REFERENCES municipalities (id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, municipality_id)
);

CREATE INDEX IF NOT EXISTS activity_municipalities_municipality_idx
    ON activity_municipalities (municipality_id);

-- small key/value store, e.g. for the rotating Strava refresh token
CREATE TABLE IF NOT EXISTS app_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
