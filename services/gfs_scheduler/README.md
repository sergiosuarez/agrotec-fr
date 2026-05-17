# agrotec-fr / services / gfs_scheduler

Descarga automatica del modelo **GFS 0.25°** de NOAA NOMADS y genera dos NetCDF servidos por THREDDS:

| Archivo | Contenido | Cobertura temporal |
|---|---|---|
| `gfspgrb20p25.nc` | Superficie: `t2m, r2, u10, v10, prate, sdswrf` | f003..f120 cada 3h |
| `gfspgrb20p25_vert.nc` | Perfil vertical `t, r` en 6 niveles de presion | snapshot f024 |

Portado de **StreamTrack** (`estaciones/tasks.py:descargar_gfs`), adaptado a script standalone (sin Django ni Celery).

## Subregion (configurable por env)

| Variable | Default Agrotec | Equivalente |
|---|---|---|
| `GFS_LAT_MIN` | -5 | Sur de Ecuador |
| `GFS_LAT_MAX` | 1 | Norte de Ecuador |
| `GFS_LON_MIN` | 280 | -80W (Costa) |
| `GFS_LON_MAX` | 282 | -78W (Sierra) |

## Cadencia

- `GFS_INTERVAL_HOURS` (default 6) — coincide con runs GFS 00/06/12/18Z
- `GFS_RETRY_MINUTES` (default 30) — si la descarga falla, reintenta antes del proximo ciclo

## Ejecucion manual (debug)

```bash
docker compose exec gfs_scheduler python download_gfs.py
```

## Notas

- NOMADS publica cada run aprox. 4h despues del horario inicial; por eso buscamos hacia atras desde `lag=5h`.
- Los NetCDF se sirven via THREDDS en `https://desarrollowebsite.com/agrotec-thredds/`.
- Si solo necesitas el GFS sin levantar todo Agrotec: este contenedor + un volumen son suficientes.
