# API REST — IDEPalma visor

Base URL pública: `https://idepalma.desarrollowebsite.com/api/v1`
Documentación interactiva (Swagger): `https://idepalma.desarrollowebsite.com/docs`
OpenAPI JSON: `https://idepalma.desarrollowebsite.com/openapi.json`

> Todas las respuestas son JSON. Los errores siguen el formato estándar de FastAPI: `{"detail": "mensaje"}` con HTTP 4xx/5xx.

## Mapa rápido de endpoints

| Endpoint | Uso |
|---|---|
| `GET /health` | healthcheck |
| `GET /api/v1/layers` | **catálogo unificado** para el visor (raster + vector + featured + visible) |
| `GET /api/v1/layers?include_hidden=true` | misma lista pero incluye las marcadas como ocultas (admin) |
| `PUT /api/v1/visor/config` | admin: marcar visible/destacada/orden/opacidad/color de una capa |
| `DELETE /api/v1/visor/config/{alternate}` | borrar config local de una capa (vuelve a defaults) |
| `GET /api/v1/feature-info` | popup vectorial: proxy de WMS GetFeatureInfo |
| `GET /api/v1/gfs/point` | pronóstico GFS para un punto (T/HR/lluvia/solar/viento 10 m) |
| `GET /api/v1/gfs/profile` | perfil vertical GFS (T/HR en 6 niveles de presión, snapshot +24 h) |
| `GET /api/v1/gfs/status` | NetCDFs disponibles en el volumen GFS |
| `GET /api/v1/ortomosaicos[?sync=true]` | (legacy) solo ortomosaicos — usar `/layers` en su lugar |
| `GET /api/v1/cultivos`, `/haciendas`, `/parcelas` | CRUDs internos de negocio |

---

## Health

### `GET /health`

Estado del visor y servicios upstream. Útil para healthchecks de Docker / k8s / monitoring.

**Respuesta:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "db": "ok",
  "geonode": "ok",
  "thredds": "ok"
}
```

Valores posibles: `ok`, `down`, `error: <ExceptionName>`.

---

## Cultivos

### `GET /api/v1/cultivos`

Lista el catálogo de cultivos. Pre-poblado en `db/init/03_seed.sql` con 10 cultivos comunes (Banano, Cacao, Café, Arroz, etc.).

**Respuesta:** `[CultivoOut]`

```json
[
  {
    "id": 1,
    "nombre": "Banano",
    "nombre_cientifico": "Musa paradisiaca",
    "ciclo_dias": 365,
    "perenne": true
  },
  ...
]
```

---

## Haciendas

### `GET /api/v1/haciendas`

Lista todas las haciendas (orden alfabético por nombre).

**Respuesta:** `[HaciendaOut]`

```json
[
  {
    "id": 1,
    "nombre": "Hacienda Las Lomas",
    "propietario": "Agroindustrial XYZ S.A.",
    "codigo": "HLL-001",
    "area_ha": 245.5,
    "contacto": {"telefono": "..."},
    "created_at": "2026-05-17T15:00:00Z"
  }
]
```

### `GET /api/v1/haciendas/{hacienda_id}`

Detalle de una hacienda. `404` si no existe.

---

## Parcelas

### `GET /api/v1/parcelas[?hacienda_id=N]`

Lista parcelas. Filtrable por hacienda.

**Query params:**
- `hacienda_id` (int, opcional) — solo parcelas de esa hacienda

**Respuesta:** `[ParcelaOut]`

```json
[
  {
    "id": 12,
    "hacienda_id": 1,
    "nombre": "Parcela 03 Norte",
    "codigo": "P-003N",
    "area_ha": 18.2345,
    "created_at": "2026-05-17T15:00:00Z"
  }
]
```

> El campo `area_ha` se calcula automáticamente vía `GENERATED ALWAYS` desde la geometría (`ST_Area(geom::geography) / 10000`).

### `GET /api/v1/parcelas/{parcela_id}`

Detalle de una parcela. `404` si no existe.

---

## Capas (catálogo unificado del visor) — v2

### `GET /api/v1/layers[?include_hidden=false]`

Endpoint principal que consume el geovisor. Devuelve **todas** las capas publicadas en GeoNode (raster + vector) categorizadas, con merge de la config local (`visor_layer_config`).

**Query params:**
- `include_hidden` (bool, default `false`) — si `true`, incluye también las capas marcadas con `visible=false`. Usado por el modal admin.

**Respuesta:** `[LayerOut]`

```json
[
  {
    "alternate": "geonode:vuelo1_placa27",
    "title": "vuelo1_placa27",
    "abstract": null,
    "subtype": "raster",
    "category": "ortomosaicos",
    "wms_url": "…/wms?…&layers=geonode:vuelo1_placa27&…&bbox={bbox-epsg-3857}…",
    "legend_url": "…/wms?…&request=GetLegendGraphic&layer=geonode:vuelo1_placa27",
    "thumbnail_url": "…",
    "bbox": [-79.92, -2.72, -79.78, -2.65],
    "visible": true,
    "featured": false,
    "order": 999,
    "default_opacity": 1.0,
    "color": null
  }
]
```

**Categorización** (heurística por nombre):
- `ortomosaicos` — rasters con `ortho|ortomos|ap_temp|drone|rgb` en el nombre
- `haciendas` — vectores con `parcela|lote|haciend`
- `infraestructura` — `via|carret|camin`
- `limites` — `limite|provinc|canton|parroq`
- `vectoriales` — resto de vectores
- `raster_otros` — resto de rasters

**Ordenamiento:** destacadas primero, luego por `order` asc, luego por `title` alfabético.

El `bbox` se extrae preferentemente de `ll_bbox_polygon` (siempre WGS84). Si la capa solo tiene `bbox_polygon` en CRS nativo (UTM, etc.), se descarta para evitar errores `LngLat` en MapLibre.

---

### `PUT /api/v1/visor/config`

Crea o actualiza la configuración local de una capa. Solo se actualizan los campos enviados (parcial = ok).

**Body:**
```json
{
  "alternate": "geonode:full_prov2",
  "visible": false,
  "featured": false,
  "order": 5,
  "default_opacity": 0.6,
  "color": "#1B7A40"
}
```

**Respuesta `200`:** misma struct con todos los campos persistidos.

Idempotente. Si `alternate` no existe, lo crea.

---

### `DELETE /api/v1/visor/config/{alternate}`

Elimina la config local de una capa (vuelve a defaults: visible=true, featured=false, order=999). `404` si no existía.

> El path acepta `:` y `/` sin escapar gracias al converter `:path`.

---

## Feature info (popups vectoriales)

### `GET /api/v1/feature-info?layer=…&lat=…&lng=…[&tolerance=0.0005]`

Proxy server-side al `GetFeatureInfo` de GeoServer (evita problemas de CORS/ORB del navegador). Arma un bbox WGS84 alrededor del punto clickeado.

**Query params:**
- `layer` (str, **req**) — alternate de la capa, ej: `geonode:lotes_amelia`
- `lat`, `lng` (float, **req**) — coordenadas WGS84 del click
- `tolerance` (float, default `0.0005`) — grados alrededor del punto (~50 m a trópicos)

**Respuesta:** `GeoJSON FeatureCollection`. Si no hay features bajo el punto, `{"type":"FeatureCollection","features":[],"totalFeatures":0}`.

`502` si GeoServer falla.

---

## GFS — Pronóstico para un punto

### `GET /api/v1/gfs/point?lat=…&lng=…`

Series temporales completas (todos los forecast hours del último ciclo, típicamente +0 a +120 h cada 3 h ≈ 40 puntos) para variables de superficie.

**Respuesta:**
```json
{
  "lat": -2.7,
  "lng": -79.7,
  "times":  [1716120000000, 1716130800000, …],
  "t":      [[ts, 24.31], [ts, 23.85], …],
  "rh":     [[ts, 87.0], …],
  "precip": [[ts, 0.02], …],
  "solar":  [[ts, 312.0], …],
  "wind":   [[ts, 1.9, 300], [ts, 3.0, 303], …]
}
```

- `t` en °C (convertido de K)
- `rh` en %
- `precip` en mm/h (convertido de kg/m²/s)
- `solar` en W/m²
- `wind`: `[timestamp_ms, m/s, °]` — velocidad y dirección calculadas desde `u10 + v10` (referencia desde el norte hacia el sentido del viento)

`503` si el NetCDF aún no fue descargado por el scheduler.

---

### `GET /api/v1/gfs/profile?lat=…&lng=…`

Perfil vertical para un punto. Snapshot a +24 h (próximo paso pendiente: extender a todos los forecast hours y agregar `UGRD/VGRD` en cada nivel).

**Respuesta:**
```json
{
  "lat": -2.7,
  "lng": -79.7,
  "levels_hpa": [1000, 925, 850, 700, 500, 300],
  "t_celsius":  [25.4, 22.1, 18.9, 11.2, -3.7, -34.5],
  "rh_pct":     [88.0, 82.0, 70.5, 45.3, 30.1, 12.0]
}
```

---

## Ortomosaicos (legacy)

### `GET /api/v1/ortomosaicos[?sync=true]`

> **Deprecado** en favor de `/api/v1/layers` (que devuelve raster + vector unificado). Se mantiene por compatibilidad con scripts existentes.

Lista los ortomosaicos. **Modo `sync=true` consulta GeoNode al vuelo** y arma la respuesta desde su API (útil mientras la tabla local `ortomosaico` no está poblada).

**Query params:**
- `sync` (bool, default `false`) — si `true`, devuelve **todas las capas raster de GeoNode** sin tocar la BD local

**Respuesta:** `[OrtomosaicoOut]`

```json
[
  {
    "id": 0,
    "nombre": "ap_temp_1_1",
    "geonode_alternate": "geonode:ap_temp_1_1",
    "parcela_id": null,
    "hacienda_id": null,
    "fecha_vuelo": null,
    "resolucion_m": null,
    "wms_url": "https://agrotec.dominio.com/geoserver/ows?service=WMS&version=1.3.0&request=GetMap&layers=geonode:ap_temp_1_1",
    "preview_url": null
  }
]
```

> El campo `wms_url` es directo para consumir en MapLibre/OpenLayers/Leaflet con `bbox=...` añadido.

---

## GFS — Meteorología

### `GET /api/v1/gfs/status`

Estado del NetCDF generado por `agrotec_gfs_scheduler`. Lista los archivos disponibles en el volumen `agrotec-fr-gfsdata`.

**Respuesta:**

```json
{
  "available": true,
  "files": [
    {
      "name": "gfspgrb20p25.nc",
      "size_bytes": 269206,
      "modified": "2026-05-17T13:05:19.938060+00:00",
      "thredds_url": "https://agrotec.dominio.com/thredds/fileServer/testAll/actual/modelos/gfspgrb20p25.nc"
    },
    {
      "name": "gfspgrb20p25_vert.nc",
      "size_bytes": 41247,
      "modified": "2026-05-17T13:05:20.746048+00:00",
      "thredds_url": "..."
    }
  ],
  "last_modified": "2026-05-17T13:05:20.746048Z"
}
```

### Acceso directo a THREDDS

| Tipo de acceso | URL ejemplo |
|---|---|
| Catálogo HTML | `/thredds/catalog/testAll/actual/modelos/catalog.html` |
| OPeNDAP | `/thredds/dodsC/testAll/actual/modelos/gfspgrb20p25.nc` |
| HTTP file | `/thredds/fileServer/testAll/actual/modelos/gfspgrb20p25.nc` |
| WMS | `/thredds/wms/testAll/actual/modelos/gfspgrb20p25.nc?REQUEST=GetCapabilities` |
| WCS | `/thredds/wcs/testAll/actual/modelos/gfspgrb20p25.nc?REQUEST=GetCapabilities` |

Detalle del pipeline GFS en [GFS_PIPELINE.md](./GFS_PIPELINE.md).

---

## CORS

Configurado vía variable `CORS_ORIGINS` en `.env` del visor. Por defecto:
```
CORS_ORIGINS=https://agrotec.dominio.com,http://localhost:8089
```

Si el geovisor se sirve desde el mismo dominio (recomendado), no necesita CORS especial.

---

## Autenticación

Actualmente la API es **abierta** (sin token). Para producción con datos sensibles:
- Restringir IP a nivel nginx (reverse proxy)
- O agregar middleware FastAPI con JWT (no implementado, pendiente)

---

## Códigos de estado

| Código | Significado |
|---|---|
| 200 | OK con datos |
| 404 | Recurso no encontrado |
| 422 | Validación Pydantic falló |
| 500 | Error interno (revisa logs `docker logs agrotec_visor`) |
| 502 | El visor no responde — verifica que esté Up |
| 503 | Upstream down — probable GeoNode o DB |
