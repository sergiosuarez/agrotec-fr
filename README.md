# agrotec-fr — IDEPalma Geovisor + APIs + GFS

Stack frontend de la plataforma **IDEPalma** (Infraestructura de Datos Espaciales de Corporación PALMAR — bananera en Ecuador). Consume capas WMS/WFS de [agrotec-bk](https://github.com/sergiosuarez/agrotec-bk) (GeoNode + GeoServer) y expone:

- **Geovisor web** MapLibre GL JS con admin de capas, popups vectoriales y panel meteorológico GFS.
- **API REST** (FastAPI) con catálogo unificado de capas + endpoints de meteorología puntual.
- **Pipeline GFS**: scheduler cron interno descarga NOAA GFS cada 6 h y lo expone vía THREDDS (WMS/OPeNDAP) y endpoints REST de punto/perfil.

> Vivo en: `https://idepalma.desarrollowebsite.com/visor/`
> API: `https://idepalma.desarrollowebsite.com/docs`

## Stack

| Componente | Imagen | Función |
|---|---|---|
| `agrotec_visor` | build local (`python:3.11-slim`) | FastAPI + Uvicorn — sirve `static/index.html` y `/api/v1/*` |
| `agrotec_db` | `postgis/postgis:16-3.4` | BD propia del visor (`visor_layer_config`, haciendas, parcelas, ortomosaicos) |
| `agrotec_redis` | `redis:7` | Cache de tiles, sesiones, pub/sub |
| `agrotec_thredds` | `unidata/thredds-docker:5.5` | Sirve los NetCDF GFS como WMS / OPeNDAP / WCS |
| `agrotec_gfs_scheduler` | build local | Cron interno cada 6 h: descarga GFS de NOAA NOMADS y genera dos NetCDFs (superficie + perfil vertical) |

Red Docker: `agrotec-net` (external) — compartida con `agrotec-bk`.

## Estructura

```
agrotec-fr/
├── docker-compose.yml
├── .env (no commiteado)
├── db/init/                        # schema PostGIS + seed
├── docs/                           # documentacion tecnica
│   ├── API.md                      # endpoints REST
│   ├── ARQUITECTURA.md
│   ├── CHANGELOG.md
│   ├── DESPLIEGUE.md
│   ├── FLUJO_QFIELD.md
│   ├── GFS_PIPELINE.md
│   ├── MIGRACION_CLIENTE.md
│   └── VISOR_GUIA.md               # guia usuario final del visor
└── services/
    ├── ingest_ws/                  # FastAPI app
    │   ├── app/
    │   │   ├── main.py
    │   │   ├── config.py
    │   │   ├── models.py
    │   │   ├── geonode_client.py
    │   │   └── routers/
    │   │       ├── layers.py        # GET /api/v1/layers (catalogo unificado)
    │   │       ├── visor_config.py  # admin de visible/featured/orden
    │   │       ├── feature_info.py  # proxy GetFeatureInfo
    │   │       ├── gfs.py           # /gfs/point /gfs/profile /gfs/status
    │   │       ├── ortomosaicos.py  # legacy
    │   │       ├── haciendas.py / parcelas.py / cultivos.py
    │   │       └── health.py
    │   ├── static/index.html        # geovisor v2 (MapLibre + ECharts)
    │   ├── requirements.txt
    │   └── Dockerfile
    ├── gfs_scheduler/               # download_gfs.py + cron
    └── thredds/                     # config THREDDS
```

## Despliegue

### Requisitos
- `agrotec-bk` ya desplegado y la red `agrotec-net` creada.
- Reverse proxy externo (nginx) con HTTPS termination apuntando a `agrotec_visor:8000`.
- Docker + Docker Compose v2.

### Pasos

```bash
git clone git@github.com:sergiosuarez/agrotec-fr.git /opt/agrotec/fr
cd /opt/agrotec/fr

# 1. .env (NO commitear)
cp .env.example .env  # ajustar passwords y URL publica del GeoNode

# 2. Levantar
docker compose up -d --build

# 3. Verificar
docker compose ps
curl http://localhost:8000/health

# 4. Acceder via reverse proxy externo
# https://idepalma.desarrollowebsite.com/visor/
```

Detalle paso a paso en [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md).

## Variables de entorno clave

- `GEONODE_INTERNAL_WFS_URL` — endpoint WFS de GeoServer dentro de la red Docker (ej. `http://nginx4agrotec:80/geoserver/wfs`)
- `GEONODE_PUBLIC_BASE_URL` — URL pública (ej. `https://idepalma.desarrollowebsite.com`)
- `GEONODE_PUBLIC_WMS_URL` — derivada de la anterior (`…/geoserver/ows`)
- `POSTGRES_*` — credenciales BD del visor (no del de GeoNode)
- `GFS_DIR` — directorio compartido con `gfs_scheduler` donde caen los NetCDFs
- `CORS_ORIGINS` — lista CSV de orígenes permitidos

## App móvil offline

QField + Mergin Maps server (community edition) corre en `mobile/mergin-server/`. Detalle en [docs/FLUJO_QFIELD.md](docs/FLUJO_QFIELD.md).

## Features destacados del visor v2

- **Catálogo unificado** raster + vector, categorizado por heurística de nombre.
- **Admin** de visibilidad / destacada / orden por capa (modal ⚙).
- **Popups vectoriales** con tabla de atributos vía proxy de GetFeatureInfo.
- **URL compartible** con estado del mapa (`?l=alt1,alt2&z=…&lat=…&lng=…`).
- **Panel meteorológico GFS** interactivo: pronóstico horario (T, HR, lluvia, solar, viento) + perfil vertical (T/HR en 6 niveles de presión). Powered by ECharts 5.5.
- **Sidebar y categorías colapsables** para trabajar cómodamente con muchas capas.
- **Coords overlay dinámico** que se reubica para no tapar el panel meteo.

Ver [docs/VISOR_GUIA.md](docs/VISOR_GUIA.md) y [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Limitaciones conocidas

- Solo viento a 10 m de superficie. Para viento por altura (perfil vertical) hay que extender `services/gfs_scheduler/download_gfs.py` con `UGRD/VGRD` en `isobaricInhPa`.
- Perfil vertical es snapshot fijo a +24 h (no sigue cursor temporal).
- API sin autenticación — restringir a nivel reverse proxy si los datos lo requieren.

## Licencia

Privado. Corporación PALMAR — Ing. Juan Carlos Pindo M. Implementación: Sergio Suárez Cruz <suarez.cruz.sergio@gmail.com>.
