# agrotec-fr — Visor y API de Agrotec

Frontend / visor web + API (FastAPI) de la plataforma **Agrotec** (gestión agrícola con imágenes de drone, ortomosaicos y monitoreo de haciendas).

Consume capas WMS/WFS de [agrotec-bk](https://github.com/sergiosuarez/agrotec-bk) (GeoNode + GeoServer) y expone:

- Geovisor web (MapLibre/OpenLayers, capas drone + mapas base + capas vectoriales).
- API REST/WebSocket para integraciones.
- Endpoint de generación de paquetes offline (MBTiles/PMTiles) para QField / Mergin Maps.

## Stack

| Componente | Imagen | Función |
|---|---|---|
| `agrotec_visor` | build local | FastAPI + Uvicorn (puerto 8000 interno) |
| `agrotec_db` | `postgis/postgis:16-3.4` | PostGIS propia del visor (configuración, capas, usuarios) |
| `agrotec_redis` | `redis:7` | Cache de tiles, sesiones, pub/sub |

Red Docker: `agrotec-net` (external) — compartida con `agrotec-bk`.

## Estructura

```
agrotec-fr/
├── docker-compose.yml
├── .env (no commiteado)
├── create_offline_bundle.sh    # genera paquetes QField / MBTiles
├── db/init/                    # extensiones PostGIS + schema inicial
├── docs/                       # documentación técnica
└── services/
    └── ingest_ws/              # FastAPI app
        ├── app.py
        ├── projection.py
        ├── spatial_checks.py
        ├── requirements.txt
        └── Dockerfile
```

> **Nota:** este repo parte de una base SIGMAP (visor marítimo) y será refactorizado al dominio agrícola. Lo que queda por adaptar está marcado en `docs/REFACTOR_AGRO.md` (pendiente).

## Despliegue

### Requisitos
- `agrotec-bk` ya desplegado y la red `agrotec-net` creada.
- Docker + Docker Compose v2.

### Pasos

```bash
git clone git@github.com:sergiosuarez/agrotec-fr.git
cd agrotec-fr

# 1. Generar .env (NO commitear)
cp .env.example .env  # ajustar passwords y URL pública del GeoNode

# 2. Levantar
docker compose up -d --build

# 3. Verificar
docker compose ps
curl http://localhost:8000/health  # (cuando el endpoint exista)

# 4. Acceder (vía reverse proxy externo)
# https://<tu-dominio>/agrotec/
```

## Variables de entorno clave

- `GEONODE_BASE_URL=http://nginx4agrotec:80` (red Docker interna)
- `GEONODE_PUBLIC_BASE_URL=https://<dominio>/agrotec-geonode`
- `GEONODE_OAUTH_CLIENT_ID` / `..._SECRET` — se generan en GeoNode tras primer arranque (`Admin → Django OAuth Toolkit → Applications`).
- `POSTGRES_PASSWORD` — único para esta instancia.

## App móvil offline (proyecto hermano)

Los técnicos en campo no tienen internet. Estrategia recomendada:

- **QField** (Android) + **Mergin Maps** como servidor de sync.
- `create_offline_bundle.sh` genera un proyecto QGIS con la(s) capa(s) seleccionada(s) en MBTiles, listo para descargar y trabajar sin conexión.
- Repo separado: `agrotec-mobile` (cuando se necesite app branded).

## Roadmap

- [ ] Refactor app.py: quitar lógica náutica, modelar entidades agrícolas (Hacienda, Parcela, Lote, Cultivo, Ortomosaico)
- [ ] Endpoint `/api/v1/orthomosaics` con listado y metadata
- [ ] Endpoint `/api/v1/offline/bundle/<parcela_id>` que devuelve MBTiles + proyecto QGIS
- [ ] Geovisor web con capas activables
- [ ] Capa meteorológica GFS (Fase 2, reusando THREDDS de StreamTrack)

## Licencia

Privado. Sergio Suárez Cruz <suarez.cruz.sergio@gmail.com>.
