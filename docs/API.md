# API REST — Agrotec visor

Base URL pública: `https://agrotec.dominio.com/api/v1`
Documentación interactiva (Swagger): `https://agrotec.dominio.com/docs`
OpenAPI JSON: `https://agrotec.dominio.com/openapi.json`

> Todas las respuestas son JSON. Los errores siguen el formato estándar de FastAPI: `{"detail": "mensaje"}` con HTTP 4xx/5xx.

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

## Ortomosaicos

### `GET /api/v1/ortomosaicos[?sync=true]`

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
