"""
download_gfs.py — Descarga del modelo GFS de NOAA NOMADS y conversión a NetCDF.

Portado de StreamTrack (estaciones/tasks.py) a script standalone (sin Django/Celery).
Pensado para correr dentro del contenedor `agrotec_gfs_scheduler` y persistir los
NetCDF resultantes en un volumen compartido con `agrotec_thredds`.

Salida:
  ${GFS_DIR}/modelos/gfspgrb20p25.nc       — superficie (t2m, r2, u10, v10, prate, sdswrf)
                                              f003..f120 cada 3h (40 pasos)
  ${GFS_DIR}/modelos/gfspgrb20p25_vert.nc  — perfil vertical (t, r, u, v) en 6 niveles de
                                              presion, f003..f120 cada 3h (40 pasos), para
                                              poder sincronizar el perfil con el cursor temporal
                                              del pronostico y mostrar viento por altura.
"""
from __future__ import annotations

import datetime
import logging
import os
import tempfile
from pathlib import Path

import requests

log = logging.getLogger("gfs")

# --- Configuracion via variables de entorno -----------------------------------
GFS_DIR    = Path(os.getenv("GFS_DIR", "/data/actual"))
GFS_MODELS = GFS_DIR / "modelos"

# Subregion agricola Ecuador (Costa + Sierra)
# GRIB2 usa longitudes 0-360, oeste = 360 + lon_negativo
LAT_MIN = float(os.getenv("GFS_LAT_MIN", "-5"))
LAT_MAX = float(os.getenv("GFS_LAT_MAX", "1"))
LON_MIN = float(os.getenv("GFS_LON_MIN", "280"))   # equiv. -80 W
LON_MAX = float(os.getenv("GFS_LON_MAX", "282"))   # equiv. -78 W

NOMADS_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
HTTP_TIMEOUT  = 120

# Variables que conservamos al filtrar los datasets cfgrib
SURF_KEEP = {"u10", "v10", "t2m", "r2", "prate", "sdswrf"}
VERT_KEEP = {"t", "r", "u", "v"}


def latest_gfs_run() -> tuple[str, str] | None:
    """Encuentra el run GFS mas reciente disponible (sondea f003).

    Prueba hasta 5 runs hacia atras (cada 6h).
    Retorna (yyyymmdd, hh) o None.
    """
    now = datetime.datetime.utcnow()
    for lag in range(5, 30, 6):
        candidate = now - datetime.timedelta(hours=lag)
        run_hour = (candidate.hour // 6) * 6
        run_dt   = candidate.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        date_str = run_dt.strftime("%Y%m%d")
        hour_str = f"{run_hour:02d}"
        probe = (
            f"{NOMADS_FILTER}"
            f"?file=gfs.t{hour_str}z.pgrb2.0p25.f003"
            f"&var_TMP=on&lev_2_m_above_ground=on"
            f"&subregion=&toplat={LAT_MAX}&leftlon={LON_MIN}"
            f"&rightlon={LON_MAX}&bottomlat={LAT_MIN}"
            f"&dir=%2Fgfs.{date_str}%2F{hour_str}%2Fatmos"
        )
        try:
            r = requests.head(probe, timeout=15, allow_redirects=True)
            if r.status_code == 200:
                log.info("Run GFS disponible: %s/%sZ", date_str, hour_str)
                return date_str, hour_str
        except requests.RequestException:
            continue
    return None


def _download_one_fhr(
    date_str: str, hour_str: str, fhr: int,
    variables: list[str], levels: list[str], keep_vars: set[str],
):
    """Descarga UN forecast hour, abre con cfgrib, filtra variables y devuelve xr.Dataset."""
    import cfgrib  # noqa: F401 (engine para xarray)
    import xarray as xr

    var_params = "".join(f"&var_{v}=on" for v in variables)
    lev_params = "".join(f"&lev_{lv}=on" for lv in levels)
    url = (
        f"{NOMADS_FILTER}"
        f"?file=gfs.t{hour_str}z.pgrb2.0p25.f{fhr:03d}"
        f"{var_params}{lev_params}"
        f"&subregion=&toplat={LAT_MAX}&leftlon={LON_MIN}"
        f"&rightlon={LON_MAX}&bottomlat={LAT_MIN}"
        f"&dir=%2Fgfs.{date_str}%2F{hour_str}%2Fatmos"
    )

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".grib2")
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT, stream=True)
        r.raise_for_status()
        with os.fdopen(tmp_fd, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                fh.write(chunk)
            tmp_fd = None

        grib_datasets = cfgrib.open_datasets(tmp_path)
        if not grib_datasets:
            return None

        wanted = [ds.load() for ds in grib_datasets if set(ds.data_vars) & keep_vars]
        if not wanted:
            return None

        filtered = [ds[list(set(ds.data_vars) & keep_vars)] for ds in wanted]
        merged = xr.merge(filtered, compat="override", join="outer")

        if "valid_time" not in merged.dims:
            merged = merged.expand_dims("valid_time")
        return merged

    except Exception as e:
        log.warning("fhr=%03d descarga fallida: %s", fhr, e)
        return None
    finally:
        if tmp_fd is not None:
            try: os.close(tmp_fd)
            except OSError: pass
        try: os.unlink(tmp_path)
        except OSError: pass


def _build_netcdf(
    date_str: str, hour_str: str,
    forecast_hours: list[int],
    variables: list[str], levels: list[str], keep_vars: set[str],
    output_path: Path,
) -> bool:
    """Descarga todos los forecast hours, concatena por valid_time y guarda NetCDF (rename atomico)."""
    import xarray as xr

    datasets = []
    total = len(forecast_hours)
    for i, fhr in enumerate(forecast_hours, 1):
        ds = _download_one_fhr(date_str, hour_str, fhr, variables, levels, keep_vars)
        if ds is not None:
            datasets.append(ds)
        if i % 10 == 0:
            log.info("Progreso: %d/%d horas descargadas", i, total)

    if not datasets:
        log.error("Sin datasets descargados para %s/%sZ", date_str, hour_str)
        return False

    try:
        combined = xr.concat(datasets, dim="valid_time")
        for drop in ("time", "step", "heightAboveGround", "surface"):
            if drop in combined.coords and drop not in combined.dims:
                combined = combined.drop_vars(drop, errors="ignore")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = output_path.with_suffix(".tmp.nc")
        combined.to_netcdf(str(tmp_out))
        tmp_out.rename(output_path)
        log.info("NetCDF guardado: %s (%d pasos)", output_path, len(datasets))
        return True
    except Exception as e:
        log.exception("Error guardando NetCDF: %s", e)
        return False


def descargar_gfs() -> str:
    """Orquesta la descarga completa del run mas reciente.

    Devuelve string con resumen ej. "run=20260517/12Z surf=ok vert=ok".
    Lanza RuntimeError si falla el archivo principal (para que el scheduler reintente).
    """
    run = latest_gfs_run()
    if not run:
        log.warning("Sin run disponible en NOMADS")
        return "no run available"

    date_str, hour_str = run
    log.info("Iniciando descarga run %s/%sZ", date_str, hour_str)

    # Superficie: f003..f120 cada 3h (40 pasos)
    ok_surf = _build_netcdf(
        date_str, hour_str,
        forecast_hours=list(range(3, 121, 3)),
        variables=["PRATE", "TMP", "RH", "UGRD", "VGRD", "DSWRF"],
        levels=["2_m_above_ground", "10_m_above_ground", "surface"],
        keep_vars=SURF_KEEP,
        output_path=GFS_MODELS / "gfspgrb20p25.nc",
    )

    # Perfil vertical: f003..f120 cada 3h (40 pasos) a 6 niveles de presion,
    # con viento (UGRD/VGRD) ademas de T y RH. Multi-tiempo para sincronizar el
    # perfil con el cursor del pronostico de superficie.
    ok_vert = _build_netcdf(
        date_str, hour_str,
        forecast_hours=list(range(3, 121, 3)),
        variables=["TMP", "RH", "UGRD", "VGRD"],
        levels=["1000_mb", "925_mb", "850_mb", "700_mb", "500_mb", "300_mb"],
        keep_vars=VERT_KEEP,
        output_path=GFS_MODELS / "gfspgrb20p25_vert.nc",
    )

    summary = (
        f"run={date_str}/{hour_str}Z "
        f"surf={'ok' if ok_surf else 'err'} "
        f"vert={'ok' if ok_vert else 'err'}"
    )
    log.info("Finalizado: %s", summary)
    if not ok_surf:
        raise RuntimeError(summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print(descargar_gfs())
