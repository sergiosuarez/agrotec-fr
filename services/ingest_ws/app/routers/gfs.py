"""GFS endpoints: status, punto de pronostico, perfil vertical.

Lee directamente los NetCDF montados desde el volumen agrotec-fr-gfsdata
(generados por agrotec_gfs_scheduler cada 6h).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..schemas import GFSStatusOut

router = APIRouter(prefix="/api/v1/gfs", tags=["gfs"])

# netCDF4/HDF5 NO es thread-safe. Los endpoints son sync (def) y FastAPI los corre en
# un threadpool, así que varios hilos pueden abrir el mismo NetCDF a la vez -> errores
# HDF5. Este lock serializa el acceso a los NetCDF dentro del proceso (las lecturas son
# rápidas, <0.2s). Entre procesos (workers) lo cubre HDF5_USE_FILE_LOCKING=FALSE.
_NC_LOCK = threading.Lock()


def _gfs_paths() -> tuple[Path, Path]:
    base = Path(settings.gfs_dir) / "modelos"
    return base / "gfspgrb20p25.nc", base / "gfspgrb20p25_vert.nc"


@router.get("/status", response_model=GFSStatusOut)
def gfs_status() -> GFSStatusOut:
    base = Path(settings.gfs_dir) / "modelos"
    if not base.exists():
        return GFSStatusOut(available=False, files=[])
    files = []
    last: datetime | None = None
    for p in sorted(base.glob("*.nc")):
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        files.append({
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "modified": mtime.isoformat(),
            "thredds_url": (
                f"{settings.geonode_public_base_url}/thredds/"
                f"fileServer/testAll/actual/modelos/{p.name}"
            ),
        })
        if last is None or mtime > last:
            last = mtime
    return GFSStatusOut(available=bool(files), files=files, last_modified=last)


@router.get("/times")
def gfs_times() -> dict:
    """Lista de pasos temporales (valid_time, ms epoch) del modelo de superficie.

    Lo usa el visor para el stepper temporal de las capas WMS de GFS. `default_index`
    es el paso mas cercano al momento actual.
    """
    import pandas as pd
    import xarray as xr

    nc_path, _ = _gfs_paths()
    if not nc_path.exists():
        return {"times": [], "default_index": 0}

    try:
        with _NC_LOCK, xr.open_dataset(str(nc_path)) as ds:
            vt = np.atleast_1d(ds.valid_time.values)
            times = [int(pd.Timestamp(t).value // 1_000_000) for t in vt]
    except Exception:
        return {"times": [], "default_index": 0}
    now_ms = int(pd.Timestamp.utcnow().value // 1_000_000)
    default_index = (
        min(range(len(times)), key=lambda i: abs(times[i] - now_ms)) if times else 0
    )
    return {"times": times, "default_index": default_index}


@router.get("/point")
def gfs_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> dict:
    """Pronostico GFS para un punto: series temporales de t, rh, viento, lluvia, solar."""
    import xarray as xr
    import pandas as pd

    nc_path, _ = _gfs_paths()
    if not nc_path.exists():
        raise HTTPException(503, "Pronostico GFS no disponible. El modelo aun no ha sido descargado.")

    try:
        with _NC_LOCK, xr.open_dataset(str(nc_path)) as ds:
            lon_360 = lng % 360
            pt = ds.sel(latitude=lat, longitude=lon_360, method="nearest")

            times = [int(pd.Timestamp(t).value // 1_000_000) for t in pt.valid_time.values]

            def series(var, transform=lambda v: v):
                if var not in pt:
                    return []
                return [[t, round(float(transform(v)), 2)] for t, v in zip(times, pt[var].values)]

            # Viento: combinar u10+v10 a velocidad+direccion
            wind = []
            if "u10" in pt and "v10" in pt:
                for i, ts in enumerate(times):
                    u = float(pt["u10"].values[i])
                    v = float(pt["v10"].values[i])
                    wspd = round(float(np.sqrt(u**2 + v**2)), 2)
                    wdir = round(float((270 - np.degrees(np.arctan2(v, u))) % 360), 1)
                    wind.append([ts, wspd, wdir])

            lat_out = round(float(pt.latitude.values), 4)
            lon_v = float(pt.longitude.values)
            lng_out = round(lon_v - 360 if lon_v > 180 else lon_v, 4)
            result = {
                "lat": lat_out, "lng": lng_out, "times": times,
                "t":     series("t2m", lambda v: v - 273.15),   # K -> °C
                "rh":    series("r2"),                          # %
                "precip": series("prate", lambda v: v * 3600),  # kg/m²/s -> mm/h
                "solar": series("sdswrf"),                      # W/m²
                "wind":  wind,                                  # [[ts, m/s, dir°]]
            }
    except Exception:
        raise HTTPException(503, "Pronóstico GFS no disponible momentáneamente (el modelo se está actualizando). Reintenta en unos segundos.")
    return result


@router.get("/profile")
def gfs_profile(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> dict:
    """Perfil vertical GFS para un punto, en TODOS los pasos temporales.

    Devuelve T, RH y viento (velocidad+direccion) por nivel de presion, un perfil
    por cada `valid_time`, para que el visor pueda sincronizar el perfil mostrado
    con el cursor temporal del pronostico de superficie.

    Robusto al formato antiguo (snapshot unico f024, solo t/r sin viento): en ese
    caso `times` trae un solo elemento y wspd/wdir quedan vacios.
    """
    import pandas as pd
    import xarray as xr

    _, vert_path = _gfs_paths()
    if not vert_path.exists():
        raise HTTPException(503, "Perfil vertical GFS no disponible.")

    try:
        # `with` cierra el handle (evita fugas y locks HDF5 con lecturas concurrentes /
        # mientras el scheduler reescribe el NetCDF cada 6h).
        with _NC_LOCK, xr.open_dataset(str(vert_path)) as ds:
            lon_360 = lng % 360
            pt = ds.sel(latitude=lat, longitude=lon_360, method="nearest")

            levels = [int(p) for p in pt.isobaricInhPa.values]   # [1000,925,850,700,500,300]
            nlev = len(levels)

            has_time_dim = "valid_time" in pt.dims
            if "valid_time" in pt.coords:
                vt = np.atleast_1d(pt.valid_time.values)
                times = [int(pd.Timestamp(t).value // 1_000_000) for t in vt]
            else:
                times = [None]
            ntime = len(times) if has_time_dim else 1

            def _at(var, i):
                if var not in pt:
                    return None
                arr = pt[var]
                if has_time_dim:
                    arr = arr.isel(valid_time=i)
                return np.asarray(arr.values).flatten()

            profiles = []
            for i in range(ntime):
                t = _at("t", i); r = _at("r", i); u = _at("u", i); v = _at("v", i)
                t_c = [round(float(x) - 273.15, 2) for x in t] if t is not None else []
                rh = [round(float(x), 1) for x in r] if r is not None else []
                wspd: list[float] = []
                wdir: list[float] = []
                if u is not None and v is not None:
                    for j in range(nlev):
                        uu, vv = float(u[j]), float(v[j])
                        wspd.append(round(float(np.sqrt(uu**2 + vv**2)), 2))
                        wdir.append(round(float((270 - np.degrees(np.arctan2(vv, uu))) % 360), 1))
                profiles.append({"t_celsius": t_c, "rh_pct": rh, "wspd": wspd, "wdir": wdir})

            lat_out = round(float(pt.latitude.values), 4)
            lon_v = float(pt.longitude.values)
            lng_out = round(lon_v - 360 if lon_v > 180 else lon_v, 4)
    except Exception:
        raise HTTPException(503, "Perfil vertical no disponible momentáneamente (el modelo se está actualizando). Reintenta en unos segundos.")

    return {
        "lat": lat_out,
        "lng": lng_out,
        "levels_hpa": levels,
        "times": times,        # ms epoch (alineado con /point.times); [null] si formato viejo
        "profiles": profiles,  # un perfil por time: {t_celsius, rh_pct, wspd, wdir}
    }
