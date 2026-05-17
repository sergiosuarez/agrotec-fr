
CREATE TABLE IF NOT EXISTS vessels (
  mmsi         BIGINT PRIMARY KEY,
  matricula    TEXT,
  name         TEXT,
  imo          TEXT,
  type         TEXT,
  flag         TEXT,
  dms_enabled  BOOLEAN DEFAULT false,
  photos       JSONB
);

CREATE TABLE IF NOT EXISTS positions (
  mmsi          BIGINT REFERENCES vessels(mmsi) ON DELETE CASCADE,
  ts            TIMESTAMPTZ NOT NULL,
  geom          GEOGRAPHY(POINT, 4326) NOT NULL,
  sog_knots     DOUBLE PRECISION,
  cog_deg       DOUBLE PRECISION,
  heading_deg   DOUBLE PRECISION,
  source        TEXT,
  voyage_id     BIGINT,
  extra         JSONB,
  PRIMARY KEY (mmsi, ts)
);
CREATE INDEX IF NOT EXISTS idx_positions_geom ON positions USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts ON positions (mmsi, ts DESC);

CREATE TABLE IF NOT EXISTS alerts (
  id        BIGSERIAL PRIMARY KEY,
  mmsi      BIGINT REFERENCES vessels(mmsi) ON DELETE SET NULL,
  ts        TIMESTAMPTZ NOT NULL,
  type      TEXT,
  severity  TEXT,
  geom      GEOGRAPHY(POINT, 4326),
  details   JSONB
);
CREATE INDEX IF NOT EXISTS idx_alerts_mmsi_ts ON alerts (mmsi, ts DESC);

CREATE TABLE IF NOT EXISTS voyages (
  id            BIGSERIAL PRIMARY KEY,
  mmsi          BIGINT REFERENCES vessels(mmsi) ON DELETE CASCADE,
  dep_port      TEXT,
  dep_time      TIMESTAMPTZ,
  arr_port      TEXT,
  arr_time      TIMESTAMPTZ,
  planned_route GEOGRAPHY(LINESTRING, 4326),
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS geofences (
  id        BIGSERIAL PRIMARY KEY,
  name      TEXT UNIQUE,
  category  TEXT,
  geom      GEOGRAPHY(POLYGON, 4326),
  active    BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_geofences_geom ON geofences USING GIST(geom);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    PERFORM create_hypertable('positions', by_range('ts'), if_not_exists => TRUE);
  END IF;
END$$;
