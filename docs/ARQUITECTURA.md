# Arquitectura — Agrotec

Plataforma geoespacial agrícola con 3 frentes:

1. **Web** (geovisor + administración) para oficina
2. **API REST** para integraciones y la app móvil
3. **App móvil offline** (QField) para técnicos en campo (solo visualización por ahora)

## Diagrama general

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          USUARIOS                                        │
├────────────────────────────────────────────────┬─────────────────────────┤
│  Oficina (navegador)                           │  Campo (QField Android) │
│  - Geovisor agrotec.dominio.com/visor/         │  - Mergin Maps client   │
│  - GeoNode admin agrotec.dominio.com/          │  - Descarga proyecto    │
│  - API REST agrotec.dominio.com/api/           │  - Visualiza offline    │
└────────────────────────────────────────────────┴─────────────────────────┘
                            │                                   │
                            │ HTTPS (TLS, fail2ban, UFW)        │
                            ▼                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  REVERSE PROXY (nginx)                                                   │
│  - Termina TLS (Let's Encrypt)                                           │
│  - Reglas por subdominio y subpath                                       │
└────┬────────────┬──────────────┬────────────────┬─────────────────┬──────┘
     │            │              │                │                 │
     │ /visor/    │ /api/        │ /geoserver/    │ /thredds/       │ mergin.*
     │ /docs      │              │ /              │                 │
     ▼            ▼              ▼                ▼                 ▼
┌─────────┐ ┌──────────┐ ┌────────────────────────┐ ┌───────────┐ ┌─────────────┐
│ STATIC  │ │ FastAPI  │ │  GeoNode 4.4.3         │ │ THREDDS   │ │ Mergin Maps │
│ MapLibre│ │ visor    │ │  + GeoServer 2.24      │ │  5.5      │ │ server      │
│ vanilla │ │ uvicorn  │ │  + PostGIS 15          │ │           │ │ (Flask+Vue) │
└─────────┘ └──┬───────┘ │  + Celery+RabbitMQ     │ └────┬──────┘ └──────┬──────┘
               │         └─────┬──────────────────┘      │               │
               │               │                         │               │
               ▼               ▼                         ▼               ▼
        ┌──────────────┐  ┌──────────────┐         ┌───────────┐  ┌───────────┐
        │ PostGIS 16   │  │ PostGIS 15   │         │ NetCDF    │  │ PostGIS   │
        │ (agrotec_db) │  │ (geonode_*)  │         │ /data/    │  │ (mergin_db│
        │ haciendas,   │  │ catalogo de  │         │ actual/   │  │ + files)  │
        │ parcelas,    │  │ capas        │         │ modelos/  │  └───────────┘
        │ ortomosaicos │  └──────────────┘         └─────▲─────┘
        │ cultivos     │                                 │
        └──────────────┘                                 │ cada 6h
                                                         │
                                              ┌──────────┴──────────┐
                                              │ gfs_scheduler       │
                                              │ Descarga GRIB2 de   │
                                              │ NOAA NOMADS, genera │
                                              │ NetCDF (40 pasos + │
                                              │ perfil vertical)    │
                                              └─────────────────────┘
```

## Componentes

### `agrotec-bk` (repo: `sergiosuarez/agrotec-bk`)

Stack de **GeoNode 4.4.3** — backend geoespacial completo:

| Servicio | Imagen | Función |
|---|---|---|
| `django4agrotec` | `geonode/geonode:4.4.3` | App Django (UI admin, API v2, OAuth) |
| `celery4agrotec` | misma | Workers async (procesado de capas) |
| `nginx4agrotec` | `geonode/nginx:1.26.3` | Proxy interno del stack GeoNode |
| `geoserver4agrotec` | `geonode/geoserver:2.24.4` | OGC WMS/WFS/WCS — sirve los rasters |
| `db4agrotec` | `geonode/postgis:15-3.5` | Catálogo + datos de capas |
| `rabbitmq4agrotec` | `rabbitmq:3-alpine` | Broker Celery |
| `memcached4agrotec` | `memcached:alpine` | Cache de Django |

### `agrotec-fr` (repo: `sergiosuarez/agrotec-fr`)

Stack del **visor + APIs + GFS**:

| Servicio | Imagen | Función |
|---|---|---|
| `agrotec_visor` | build local (`python:3.11-slim`) | FastAPI: geovisor estático + API REST |
| `agrotec_db` | `postgis/postgis:16-3.4` | BD de negocio (haciendas, parcelas, ortomosaicos) |
| `agrotec_redis` | `redis:7` | Cache y sesiones del visor |
| `agrotec_thredds` | `unidata/thredds-docker:5.5` | Sirve los NetCDF como WMS/OPeNDAP/HTTP |
| `agrotec_gfs_scheduler` | build local | Cron interno cada 6h: descarga GFS de NOAA |

### `mergin-server` (en `agrotec-fr/mobile/mergin-server/`)

Stack de **Mergin Maps server** auto-hosted para sincronizar proyectos QGIS/QField:

| Servicio | Imagen | Función |
|---|---|---|
| `mergin_server` | `lutraconsulting/merginmaps-backend:2025.7.3` | API Flask |
| `mergin_celery_*` | misma | Workers async + scheduler |
| `mergin_web` | `lutraconsulting/merginmaps-frontend:2025.7.3` | SPA Vue.js |
| `mergin_proxy` | `nginxinc/nginx-unprivileged` | Combina API + SPA en un solo puerto |
| `mergin_db` | `postgres:14` | Catálogo de proyectos y usuarios |
| `mergin_redis` | `redis:6.2.17` | Cola Celery |

## Redes Docker

- `streamtrack_default` — red original del proxy nginx externo
- `agrotec-net` — el `agrotec-bk` y `agrotec-fr` se hablan por nombre de contenedor
- `mergin-net` — aislada para Mergin
- El `streamtrack-nginx-1` (reverse proxy externo) está conectado a las **3** para alcanzar todo

## Flujos de datos clave

### 1. Subir un ortomosaico al sistema

```
.tif del drone
   │
   │ scripts/import_orthomosaics.sh
   ▼
gdal_translate → COG-JPEG (8-12% del tamaño original)
   │
   │ docker exec django4agrotec python manage.py importlayers
   ▼
GeoNode (catálogo) + GeoServer (WMS) + PostGIS (metadatos)
   │
   │ La capa queda accesible en:
   │   - GeoNode UI:  /catalogue/#/dataset/<id>
   │   - WMS:          /geoserver/ows?service=WMS&layers=geonode:<name>
   │   - API REST:     /api/v1/ortomosaicos?sync=true
   ▼
Visible en geovisor MapLibre y descargable para QField
```

### 2. Pipeline meteorológico GFS

```
NOAA NOMADS (cada 6h: 00/06/12/18 UTC)
   │
   │ requests GET (subregión Costa+Sierra Ecuador)
   ▼
agrotec_gfs_scheduler (Python loop)
   │
   │ cfgrib parse → xarray merge → to_netcdf
   ▼
Volumen agrotec-fr-gfsdata (NetCDF reemplazo atómico)
   │
   │ THREDDS lee el volumen (modo lectura)
   ▼
Disponible vía:
   - WMS:        /thredds/wms/...
   - OPeNDAP:    /thredds/dodsC/...
   - HTTP file:  /thredds/fileServer/...
   - API REST:   /api/v1/gfs/status
```

### 3. Visualización offline en campo (alcance MVP)

```
Admin (oficina)
   │
   │ 1. Abre QGIS, agrega capas WMS de agrotec.dominio.com/geoserver/ows
   │ 2. (Opcional) Convierte capas a MBTiles para offline
   │ 3. Guarda proyecto .qgz, lo sube a Mergin Maps
   ▼
mergin.dominio.com (servidor)
   │
   │ Técnico abre QField en su Android
   │ Mergin login → ve lista de proyectos → "clone"
   ▼
QField (offline)
   │
   │ Visualiza ortomosaicos + capas vectoriales
   │ Sin internet en campo
   │ NO captura datos (alcance MVP por decisión del Ing. Pindo)
   ▼
Fin: solo lectura. Cuando vuelve a tener red, no necesita sincronizar nada.
```

Ver [FLUJO_QFIELD.md](./FLUJO_QFIELD.md) para la guía paso a paso.

## Seguridad

- TLS Let's Encrypt en todos los dominios públicos
- SSH solo por puerto alterno (8194) con clave, sin password
- UFW restrictivo (solo 22 alterno + 80 + 443 + 38725/udp WireGuard)
- fail2ban en jail SSH
- PostgreSQL del host bindeado solo a localhost + WireGuard
- Detalle: ver [SEGURIDAD.md](./SEGURIDAD.md) (pendiente) y memoria `server_contabo_hardening`

## URLs públicas finales (cuando DNS propague)

| URL | Componente |
|---|---|
| `https://agrotec.dominio.com/` | GeoNode admin |
| `https://agrotec.dominio.com/visor/` | Geovisor MapLibre |
| `https://agrotec.dominio.com/api/v1/*` | API REST FastAPI |
| `https://agrotec.dominio.com/docs` | Swagger UI |
| `https://agrotec.dominio.com/geoserver/web/` | GeoServer admin |
| `https://agrotec.dominio.com/thredds/` | THREDDS catalog |
| `https://mergin.dominio.com/` | Mergin Maps (QField sync) |
