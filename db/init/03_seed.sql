
INSERT INTO vessels (mmsi, matricula, name, type, flag, dms_enabled)
VALUES (735057000, 'EC-1234', 'PANGAEA', 'FISHING', 'ECU', true)
ON CONFLICT (mmsi) DO NOTHING;

INSERT INTO geofences (name, category, geom, active)
VALUES (
  'Zona Restringida Demo',
  'restringida',
  ST_GeogFromText('POLYGON((-79.92 -2.18, -79.86 -2.18, -79.86 -2.14, -79.92 -2.14, -79.92 -2.18))'),
  true
)
ON CONFLICT (name) DO NOTHING;
