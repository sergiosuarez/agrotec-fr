-- ============================================================================
-- Agrotec - Schema base PostGIS
-- ============================================================================
-- Modela: Hacienda > Parcela > Lote, Cultivo, Ortomosaico
-- SRID 4326 (WGS84) para consistencia con WMS publicos de GeoNode/GeoServer.

-- ---------------- Catalogo de cultivos -------------------------------------
CREATE TABLE IF NOT EXISTS cultivo (
    id              BIGSERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL UNIQUE,
    nombre_cientifico TEXT,
    ciclo_dias      INTEGER,
    perenne         BOOLEAN DEFAULT FALSE,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------- Hacienda --------------------------------------------------
CREATE TABLE IF NOT EXISTS hacienda (
    id              BIGSERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL,
    propietario     TEXT,
    codigo          TEXT UNIQUE,
    ubicacion       GEOGRAPHY(POINT, 4326),
    area_ha         NUMERIC(12, 4),
    contacto        JSONB DEFAULT '{}'::jsonb,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hacienda_ubicacion ON hacienda USING GIST(ubicacion);

-- ---------------- Parcela (lote grande dentro de una hacienda) --------------
CREATE TABLE IF NOT EXISTS parcela (
    id              BIGSERIAL PRIMARY KEY,
    hacienda_id     BIGINT NOT NULL REFERENCES hacienda(id) ON DELETE CASCADE,
    nombre          TEXT NOT NULL,
    codigo          TEXT,
    geom            GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    area_ha         NUMERIC(12, 4) GENERATED ALWAYS AS (
                        ST_Area(geom::geography) / 10000.0
                    ) STORED,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (hacienda_id, codigo)
);
CREATE INDEX IF NOT EXISTS idx_parcela_geom ON parcela USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_parcela_hacienda ON parcela (hacienda_id);

-- ---------------- Lote (subdivision de parcela, opcional) -------------------
CREATE TABLE IF NOT EXISTS lote (
    id              BIGSERIAL PRIMARY KEY,
    parcela_id      BIGINT NOT NULL REFERENCES parcela(id) ON DELETE CASCADE,
    nombre          TEXT NOT NULL,
    cultivo_id      BIGINT REFERENCES cultivo(id) ON DELETE SET NULL,
    fecha_siembra   DATE,
    geom            GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    area_ha         NUMERIC(12, 4) GENERATED ALWAYS AS (
                        ST_Area(geom::geography) / 10000.0
                    ) STORED,
    estado          TEXT DEFAULT 'activo',
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lote_geom ON lote USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_lote_parcela ON lote (parcela_id);

-- ---------------- Ortomosaico (referencia a capa de GeoNode/GeoServer) ------
CREATE TABLE IF NOT EXISTS ortomosaico (
    id                  BIGSERIAL PRIMARY KEY,
    parcela_id          BIGINT REFERENCES parcela(id) ON DELETE SET NULL,
    hacienda_id         BIGINT REFERENCES hacienda(id) ON DELETE CASCADE,
    nombre              TEXT NOT NULL,
    geonode_alternate   TEXT NOT NULL UNIQUE,
    geonode_uuid        UUID,
    fecha_vuelo         DATE,
    resolucion_m        NUMERIC(6, 4),
    geom_bbox           GEOMETRY(POLYGON, 4326),
    srid_origen         INTEGER,
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ortomosaico_bbox ON ortomosaico USING GIST(geom_bbox);
CREATE INDEX IF NOT EXISTS idx_ortomosaico_parcela ON ortomosaico (parcela_id);
CREATE INDEX IF NOT EXISTS idx_ortomosaico_hacienda ON ortomosaico (hacienda_id);

-- ---------------- Trigger updated_at ----------------------------------------
CREATE OR REPLACE FUNCTION agrotec_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['hacienda', 'parcela', 'lote']::TEXT[] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%I_updated ON %I;
             CREATE TRIGGER trg_%I_updated BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION agrotec_set_updated_at();',
            t, t, t, t
        );
    END LOOP;
END $$;

-- ---------------- Config por capa para el geovisor -------------------------
CREATE TABLE IF NOT EXISTS visor_layer_config (
    id              BIGSERIAL PRIMARY KEY,
    alternate       TEXT NOT NULL UNIQUE,
    visible         BOOLEAN DEFAULT TRUE,    -- si false, la capa NO aparece en el sidebar del visor
    featured        BOOLEAN DEFAULT FALSE,   -- si true, se auto-activa al cargar el visor
    "order"         INTEGER DEFAULT 999,
    default_opacity NUMERIC(3, 2) DEFAULT 1.0,
    color           TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE visor_layer_config ADD COLUMN IF NOT EXISTS visible BOOLEAN DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS idx_visor_layer_featured ON visor_layer_config (featured, "order") WHERE featured;
