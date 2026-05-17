-- ============================================================================
-- Agrotec - Datos semilla
-- ============================================================================
-- Cultivos comunes en Ecuador costa/sierra
INSERT INTO cultivo (nombre, nombre_cientifico, ciclo_dias, perenne) VALUES
    ('Banano',         'Musa paradisiaca',          365,  TRUE),
    ('Cacao',          'Theobroma cacao',           NULL, TRUE),
    ('Cafe',           'Coffea arabica',            NULL, TRUE),
    ('Palma africana', 'Elaeis guineensis',         NULL, TRUE),
    ('Arroz',          'Oryza sativa',              120,  FALSE),
    ('Maiz',           'Zea mays',                  110,  FALSE),
    ('Cana de azucar', 'Saccharum officinarum',     365,  TRUE),
    ('Mango',          'Mangifera indica',          NULL, TRUE),
    ('Aguacate',       'Persea americana',          NULL, TRUE),
    ('Brocoli',        'Brassica oleracea italica', 90,   FALSE)
ON CONFLICT (nombre) DO NOTHING;
