"""GFS endpoints: status, punto de pronostico, perfil vertical.

Lee directamente los NetCDF montados desde el volumen agrotec-fr-gfsdata
(generados por agrotec_gfs_scheduler cada 6h).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..schemas import GFSStatusOut

router = APIRouter(prefix="/api/v1/gfs", tags=["gfs"])


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

    ds = xr.open_dataset(str(nc_path))
    lon_360 = lng % 360
    pt = ds.sel(latitude=lat, longitude=lon_360, method="nearest")

    times = [int(pd.Timestamp(t).value // 1_000_000) for t in pt.valid_time.values]

    def series(var: str, transform=lambda v: v):
        if var not in pt: return []
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

    return {
        "lat": round(float(pt.latitude.values), 4),
        "lng": round(float(pt.longitude.values) - 360 if float(pt.longitude.values) > 180 else float(pt.longitude.values), 4),
        "times": times,
        "t":     series("t2m", lambda v: v - 273.15),       # K -> °C
        "rh":    series("r2"),                              # %
        "precip": series("prate", lambda v: v * 3600),      # kg/m²/s -> mm/h
        "solar": series("sdswrf"),                          # W/m²
        "wind":  wind,                                      # [[ts, m/s, dir°]]
    }


@router.get("/profile")
def gfs_profile(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> dict:
    """Perfil vertical GFS para un punto: T y RH en 6 niveles de presion."""
    import xarray as xr

    _, vert_path = _gfs_paths()
    if not vert_path.exists():
        raise HTTPException(503, "Perfil vertical GFS no disponible.")

    ds = xr.open_dataset(str(vert_path))
    lon_360 = lng % 360
    pt = ds.sel(latitude=lat, longitude=lon_360, method="nearest")
    # Colapsar dimension temporal (perfil es snapshot f024)
    if "valid_time" in pt.dims:
        pt = pt.isel(valid_time=0)

    levels = [int(p) for p in pt.isobaricInhPa.values]   # [1000, 925, 850, 700, 500, 300]

    # .flatten() porque a veces queda [1, 6] aunque isel(valid_time=0)
    temp = [round(float(v) - 273.15, 2) for v in pt["t"].values.flatten()]
    rh = [round(float(v), 1) for v in pt["r"].values.flatten()] if "r" in pt else []

    return {
        "lat": round(float(pt.latitude.values), 4),
        "lng": round(float(pt.longitude.values) - 360 if float(pt.longitude.values) > 180 else float(pt.longitude.values), 4),
        "levels_hpa": levels,
        "t_celsius": temp,
        "rh_pct": rh,
    }
