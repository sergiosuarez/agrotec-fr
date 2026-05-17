CREATE EXTENSION IF NOT EXISTS postgis;
DO $$
BEGIN
  PERFORM 1 FROM pg_available_extensions WHERE name='timescaledb';
  IF FOUND THEN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
  END IF;
END$$;