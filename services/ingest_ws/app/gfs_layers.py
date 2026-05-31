"""Capas WMS de GFS servidas desde THREDDS (ncWMS) para el geovisor.

THREDDS expone cada variable del NetCDF como capa WMS con estilos ncWMS2
(raster, vector_arrows, etc.) y paletas configurables via COLORSCALERANGE/PALETTE.
Estas capas se inyectan en /api/v1/layers junto a las de GeoNode para que aparezcan
como activables en el sidebar (categoria "meteorologia"), reutilizando toda la
maquinaria del frontend (opacidad, z-order, toggle, fit, URL state).

A diferencia de las capas GeoNode (GeoServer/WMS por capa), estas:
  - subtype = "raster" (sin feature-info vectorial)
  - wms_url apunta al proxy /thredds/wms/... con {bbox-epsg-3857} para MapLibre
  - legend_url usa GetLegendGraphic de ncWMS (colorbar con escala)

El bbox se lee una vez del NetCDF y se cachea (la subregion GFS es fija en runtime).
"""
from __future__ import annotations

import functools
from pathlib import Path

from .config import settings

# Dataset THREDDS (mismo path que usa gfs.py para fileServer): datasetScan "testAll"
THREDDS_DATASET_PATH = "testAll/actual/modelos/gfspgrb20p25.nc"

# Bbox de respaldo (subregion costa+sierra Ecuador) si no se puede leer el NetCDF.
_DEFAULT_BBOX = [-80.0, -5.0, -78.0, 1.0]

# Definicion de las capas meteo. order arranca en 700 para que queden al final
# del sidebar (debajo de ortomosaicos/vectoriales) salvo override del admin.
# Definicion de las capas meteo. `legend` = etiquetas que mostramos (min/mid/max + unidad),
# pueden diferir del colorscalerange WMS (ej. temp en K en el WMS pero °C en la leyenda).
# `tile_px` < 512 agranda los glifos (ncWMS dibuja al tamaño del canvas; MapLibre reescala).
GFS_LAYERS: list[dict] = [
    {
        "var": "t2m", "title": "Temperatura 2 m", "style": "raster",
        "palette": "div-RdYlBu-inv", "colorscalerange": "288,306",
        "units": "K", "order": 700,
        "legend": {"min": 15, "max": 33, "unit": "°C"},
        "abstract": "Temperatura del aire a 2 m (GFS). Escala 15–33 °C.",
    },
    {
        "var": "u10:v10-group", "title": "Viento 10 m (vectores)",
        "style": "colored_sized_arrows", "palette": "seq-YlGnBu",
        "colorscalerange": "0,15", "units": "m/s", "order": 701,
        "tile_px": 256,   # flechas ~2x mas grandes (mas visibles)
        "legend": {"min": 0, "max": 15, "unit": "m/s"},
        "abstract": "Viento a 10 m: flechas dimensionadas y coloreadas por magnitud (tamaño ∝ velocidad). Fondo transparente (GFS).",
    },
    {
        "var": "r2", "title": "Humedad relativa 2 m", "style": "raster",
        "palette": "seq-Blues", "colorscalerange": "0,100",
        "units": "%", "order": 702,
        "legend": {"min": 0, "max": 100, "unit": "%"},
        "abstract": "Humedad relativa a 2 m (GFS).",
    },
    {
        "var": "prate", "title": "Precipitacion", "style": "raster",
        "palette": "seq-PuBu", "colorscalerange": "0,0.0011",
        "units": "kg m-2 s-1", "order": 703,
        "legend": {"min": 0, "max": 4, "unit": "mm/h"},
        "abstract": "Tasa de precipitacion (GFS). Escala 0–~4 mm/h.",
    },
    {
        "var": "sdswrf", "title": "Radiacion solar", "style": "raster",
        "palette": "seq-Heat", "colorscalerange": "0,1100",
        "units": "W/m2", "order": 704,
        "legend": {"min": 0, "max": 1100, "unit": "W/m²"},
        "abstract": "Radiacion solar de onda corta en superficie (GFS).",
    },
]


def _wms_base() -> str:
    return f"{settings.geonode_public_base_url}/thredds/wms/{THREDDS_DATASET_PATH}"


def alternate_for(var: str) -> str:
    """Identificador sintetico para el visor/VisorLayerConfig (ej. 'gfs:t2m')."""
    return f"gfs:{var}"


def _getmap_url(layer: dict) -> str:
    """URL WMS GetMap con placeholder {bbox-epsg-3857} para MapLibre (raster tiles)."""
    px = layer.get("tile_px", 512)
    return (
        f"{_wms_base()}"
        f"?service=WMS&version=1.1.1&request=GetMap"
        f"&layers={layer['var']}"
        f"&styles={layer['style']}/{layer['palette']}"
        f"&colorscalerange={layer['colorscalerange']}"
        f"&numcolorbands=100&abovemaxcolor=extend&belowmincolor=extend"
        f"&format=image/png&transparent=true"
        f"&srs=EPSG:3857&bbox={{bbox-epsg-3857}}&width={px}&height={px}"
    )


def _legend_bar_url(layer: dict) -> str:
    """Colorbar HORIZONTAL solo (sin etiquetas de ncWMS); las etiquetas las pone el visor."""
    return (
        f"{_wms_base()}"
        f"?request=GetLegendGraphic"
        f"&layer={layer['var']}"
        f"&palette={layer['palette']}"
        f"&colorscalerange={layer['colorscalerange']}"
        f"&numcolorbands=100&colorbaronly=true&vertical=false&width=200&height=16"
    )


@functools.lru_cache(maxsize=1)
def _gfs_bbox() -> tuple[float, float, float, float]:
    """Lee el bbox WGS84 del NetCDF una vez; cae al default si no esta disponible."""
    nc = Path(settings.gfs_dir) / "modelos" / "gfspgrb20p25.nc"
    if not nc.exists():
        return tuple(_DEFAULT_BBOX)  # type: ignore[return-value]
    try:
        import xarray as xr

        ds = xr.open_dataset(str(nc))
        lat = ds.latitude.values
        lon = ds.longitude.values

        def to_wgs(x: float) -> float:
            return float(x - 360 if x > 180 else x)

        return (
            to_wgs(float(lon.min())), float(lat.min()),
            to_wgs(float(lon.max())), float(lat.max()),
        )
    except Exception:
        return tuple(_DEFAULT_BBOX)  # type: ignore[return-value]


def gfs_layer_entries() -> list[dict]:
    """Devuelve las capas GFS como dicts listos para construir LayerOut.

    No aplica VisorLayerConfig ni filtra por visible; eso lo hace el router de layers
    (igual que con las capas de GeoNode) para mantener una sola fuente de verdad.
    """
    bbox = list(_gfs_bbox())
    entries = []
    for lyr in GFS_LAYERS:
        entries.append({
            "alternate": alternate_for(lyr["var"]),
            "title": lyr["title"],
            "abstract": lyr.get("abstract"),
            "subtype": "raster",
            "category": "meteorologia",
            "wms_url": _getmap_url(lyr),
            "legend_url": _legend_bar_url(lyr),   # colorbar horizontal (el visor agrega etiquetas)
            "legend": lyr.get("legend"),          # {min, max, unit} para las etiquetas
            "thumbnail_url": None,
            "bbox": bbox,
            "default_order": lyr["order"],
        })
    return entries
