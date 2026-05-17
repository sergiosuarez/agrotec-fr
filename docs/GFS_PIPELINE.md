# Pipeline GFS — Documentación técnica

Descarga automática del modelo **GFS (Global Forecast System)** de NOAA, conversión a NetCDF y publicación vía THREDDS.

## Visión general

```
NOAA NOMADS (filter_gfs_0p25.pl)
   │
   │ GET HTTPS, parámetros: run + forecast hour + variables + niveles + subregión
   ▼
agrotec_gfs_scheduler  (Python loop, cada 6h)
   │
   │ requests → archivo GRIB2 temp
   │ cfgrib + xarray → filtra variables deseadas
   │ xr.concat por valid_time → NetCDF
   ▼
Volumen agrotec-fr-gfsdata  (rename atómico)
   │
   │ THREDDS lee el volumen en modo lectura
   ▼
Acceso público vía THREDDS y API REST del visor
```

## Cadencia

| Variable env | Default | Significado |
|---|---|---|
| `GFS_INTERVAL_HOURS` | 6 | Ciclo entre descargas (coincide con runs GFS 00/06/12/18Z UTC) |
| `GFS_RETRY_MINUTES` | 30 | Si una descarga falla, espera antes del próximo intento |

NOMADS publica cada run aprox. **4 horas después** de su horario nominal. El scheduler busca runs hacia atrás (`lag=5h, 11h, 17h, 23h, 29h`) hasta encontrar uno disponible.

## Subregión configurable

Por defecto **Costa + Sierra de Ecuador**:

| Variable | Default | Significado |
|---|---|---|
| `GFS_LAT_MIN` | -5 | Sur de Ecuador |
| `GFS_LAT_MAX` | 1 | Norte de Ecuador |
| `GFS_LON_MIN` | 280 | -80°W (Costa) |
| `GFS_LON_MAX` | 282 | -78°W (Sierra) |

> Las longitudes están en formato GRIB2 (0-360°). Para zonas en otro hemisferio occidental: `lon_360 = 360 + lon_negativo`.

Para cambiar la subregión (ejemplo: solo Manabí costa):
```bash
# en /opt/agrotec/fr/docker-compose.yml, servicio gfs_scheduler:
environment:
    GFS_LAT_MIN: "-1.5"
    GFS_LAT_MAX: "-0.5"
    GFS_LON_MIN: "279.5"
    GFS_LON_MAX: "280.5"
```

Luego: `docker compose up -d --force-recreate gfs_scheduler`.

## Archivos generados

| Archivo | Variables | Cobertura |
|---|---|---|
| `gfspgrb20p25.nc` | `t2m, r2, u10, v10, prate, sdswrf` (superficie) | f003 a f120 cada 3h = 40 pasos |
| `gfspgrb20p25_vert.nc` | `t, r` en 6 niveles de presión (1000, 925, 850, 700, 500, 300 hPa) | snapshot f024 |

Ambos en `${GFS_DIR}/modelos/` (montado en el contenedor como `/data/actual/modelos/`).

## Variables GFS — descripción

| Variable NetCDF | Descripción | Unidad | Fuente NOMADS |
|---|---|---|---|
| `t2m` | Temperatura del aire a 2m | K | `var_TMP` + `lev_2_m_above_ground` |
| `r2` | Humedad relativa a 2m | % | `var_RH` + `lev_2_m_above_ground` |
| `u10` | Componente U del viento a 10m | m/s | `var_UGRD` + `lev_10_m_above_ground` |
| `v10` | Componente V del viento a 10m | m/s | `var_VGRD` + `lev_10_m_above_ground` |
| `prate` | Tasa de precipitación | kg·m⁻²·s⁻¹ | `var_PRATE` + `lev_surface` |
| `sdswrf` | Radiación solar descendente | W/m² | `var_DSWRF` + `lev_surface` |

Para perfil vertical:
| Variable | Descripción | Unidad |
|---|---|---|
| `t` | Temperatura en niveles de presión | K |
| `r` | Humedad relativa en niveles de presión | % |

## Ejecución manual (debug)

```bash
docker exec agrotec_gfs_scheduler python download_gfs.py
```

Esto fuerza una descarga ahora (no espera el siguiente ciclo).

## Inspeccionar un NetCDF

```bash
docker exec agrotec_gfs_scheduler python -c "
import xarray as xr
ds = xr.open_dataset('/data/actual/modelos/gfspgrb20p25.nc')
print(ds)
print('---')
print('t2m primer paso (Kelvin):', ds.t2m.isel(valid_time=0).values)
print('Conversion a Celsius:', ds.t2m.isel(valid_time=0).values - 273.15)
"
```

## Acceso desde Python externo (cliente)

```python
import xarray as xr

# Via OPeNDAP (no requiere descargar el archivo completo)
URL = ("https://agrotec.dominio.com/thredds/dodsC/"
       "testAll/actual/modelos/gfspgrb20p25.nc")
ds = xr.open_dataset(URL)
print(ds.t2m.sel(latitude=-3, longitude=280, method='nearest'))
```

## Acceso WMS para visualizar en mapa

THREDDS expone cada variable como capa WMS:

```
https://agrotec.dominio.com/thredds/wms/testAll/actual/modelos/gfspgrb20p25.nc?
    SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap
    &LAYERS=t2m
    &TIME=2026-05-17T12:00:00Z
    &BBOX=-5,280,1,282
    &CRS=CRS:84
    &WIDTH=512&HEIGHT=512
    &FORMAT=image/png
    &STYLES=BOXFILL/rainbow
```

Para agregarlo al geovisor MapLibre, añadir como source raster apuntando a esa URL.

## Espacio en disco

Cada ciclo genera ~300 KB con subregión Ecuador. Despreciable a largo plazo. Si amplías la subregión a Sudamérica, sube a ~5 MB por ciclo (aún pequeño).

## Troubleshooting

### Scheduler en restart loop con AssertionError

Conflicto xarray < 2025 + pandas 3.x. Solución: usar versiones latest:
```bash
docker exec agrotec_gfs_scheduler pip list | grep -E "xarray|pandas"
# xarray debe ser >= 2025.0, pandas puede ser 3.x
```

Si están viejas: editar `services/gfs_scheduler/requirements.txt` para usar `xarray~=2026.4` y rebuild.

### "Sin datasets descargados"

NOMADS está caído o cambió la API. Verificar manualmente:
```bash
curl -I "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t12z.pgrb2.0p25.f003"
# Si da 404: el run aún no existe; si da 503: NOMADS está sobrecargado
```

### NetCDF aparece pero THREDDS no lo lista

THREDDS escanea el directorio al iniciar. Si se agregó después:
```bash
docker exec agrotec_thredds curl http://localhost:8080/thredds/admin/debug
# O simplemente: docker restart agrotec_thredds
```

## Origen del código

Portado de [StreamTrack](https://github.com/israelronquillo/streamtrack) (`estaciones/tasks.py:descargar_gfs`), adaptado a script standalone sin Django ni Celery. Documentación original en [streamtrack/docs/gfs-pipeline.md](https://github.com/israelronquillo/streamtrack).
