# Guía del geovisor — Usuario final

Cómo usar el visor web `https://agrotec.dominio.com/visor/`.

## Pantalla principal

El visor tiene 2 zonas:

- **Izquierda (panel lateral)**: controles de capas, mapas base, meteorología y estado del sistema
- **Derecha (mapa)**: visualización geográfica con MapLibre GL

```
┌─────────────────────────────────┬──────────────────────────────────┐
│  🌱 Agrotec                     │                                  │
│  Geovisor agricola              │                                  │
│  ─────────────                  │                                  │
│  MAPA BASE                      │              MAPA                │
│  ⦿ OpenStreetMap                │            (interactivo)         │
│  ⦾ Satélite (Esri)              │                                  │
│  ─────────────                  │     Pan: arrastrar               │
│  ORTOMOSAICOS DRONE             │     Zoom: scroll o + / -         │
│  ☐ ap_temp_1_1   [⊕]            │     Rotar: ctrl+arrastrar        │
│  ☐ ap_temp_1_2   [⊕]            │                                  │
│  ☐ ap_temp_2_1   [⊕]            │                                  │
│  ☐ ap_temp_2_2   [⊕]            │                                  │
│                                 │                                  │
│  METEOROLOGIA (GFS)             │                                  │
│  [disponible]                   │                                  │
│  actualizado: hace 6h           │                                  │
│  gfspgrb20p25.nc (263 KB)       │                                  │
│                                 │                                  │
│  ESTADO SERVICIOS               │                                  │
│  db: [ok]                       │                                  │
│  geonode: [ok]                  │                                  │
│  thredds: [ok]                  │  ─────────────────────────────── │
│                                 │  -3.16752, -79.86541 — zoom 17.0 │
│  API docs · GeoNode admin       │                                  │
└─────────────────────────────────┴──────────────────────────────────┘
```

## Operaciones básicas

### 1. Cambiar el mapa base

Click en **OpenStreetMap** o **Satélite (Esri)**. El cambio es inmediato y conserva las capas activas.

### 2. Activar/desactivar un ortomosaico

Click en el checkbox `☐ ap_temp_1_1` → se carga la capa raster encima del mapa base.

Al activar:
- Se muestra el slider **opacidad** debajo (0-100%)
- El botón **⊕** lleva al área de la capa

### 3. Ajustar opacidad

Mover el slider para ver el ortomosaico semi-transparente sobre el mapa base. Útil para comparar el ortomosaico con la imagen satelital de fondo.

### 4. Centrar el mapa en una capa

Click en **⊕** al lado de la capa → el mapa hace zoom al bbox de las capas AP_TEMP (sur de Ecuador, ~3.17°S 79.86°W).

### 5. Ver coordenadas y zoom actual

Esquina inferior izquierda del mapa muestra `lat, lon — zoom` en tiempo real al mover el cursor.

### 6. Navegar el mapa

- **Pan**: clic y arrastra
- **Zoom in/out**: scroll del mouse, o `+` / `-` del teclado, o doble-clic
- **Rotar**: Ctrl + arrastrar
- **Tilt (3D)**: Ctrl + arrastrar con click derecho

## Información meteorológica (GFS)

El panel **METEOROLOGIA (GFS)** muestra:

- **Badge `disponible`** (verde) o **`no disponible`** (rojo)
- **Última actualización** del NetCDF (cada 6h aprox)
- **Lista de archivos** descargables — clic abre el `.nc` para descarga

Para visualizar la temperatura GFS como capa WMS sobre el mapa (avanzado):
1. Copia la URL del archivo (ej. `https://agrotec.dominio.com/thredds/wms/.../gfspgrb20p25.nc`)
2. Reemplaza `fileServer` por `wms` en la URL
3. Úsala desde QGIS o cualquier cliente WMS con `LAYERS=t2m`

## Estado de servicios

El panel **ESTADO SERVICIOS** monitorea en vivo:

| Servicio | Verde si... |
|---|---|
| `db` | Base de datos del visor responde |
| `geonode` | GeoNode upstream está vivo |
| `thredds` | THREDDS upstream está vivo |

Si alguno aparece **rojo**, contactar al administrador (`admin@dominio.com`).

## Atajos de teclado

- `+` / `-` — zoom in/out
- `←` `→` `↑` `↓` — pan
- `Shift + arrastrar` — selección rectangular (zoom box)

## Limitaciones actuales (MVP)

- **No hay autenticación** — el visor es público (configurable a nivel reverse proxy)
- **No hay edición** — solo visualización (la edición se hace desde GeoNode admin)
- **No hay búsqueda** de capas por nombre/atributo (próxima versión)
- **No hay panel de leyenda** — agregar manualmente desde GeoServer (`/geoserver/web/`)
- **No hay timeline** para variables GFS (próxima versión)

## Para administradores

Para agregar/quitar capas que aparecen en el visor, usar **GeoNode admin** (`https://agrotec.dominio.com/`):

- Subir capa → automáticamente aparece en `/api/v1/ortomosaicos?sync=true` y el visor la lista
- Borrar capa → desaparece del visor en el siguiente reload
- Cambiar permisos → el visor consume capas públicas; las privadas no aparecen sin OAuth (no implementado aún)

Detalle en [GEONODE_ADMIN.md](../../bk/docs/GEONODE_ADMIN.md).

## Reportar problemas

Si el visor no carga las capas:

1. Refrescar página (`F5` o `Ctrl+Shift+R`)
2. Ver consola del navegador (`F12`) por errores
3. Revisar `https://agrotec.dominio.com/health` — debe responder `200`
4. Reportar al admin con captura de la consola
