"""GET /api/v1/layers — TODAS las capas (vector + raster) categorizadas para el geovisor.

Distinto a /api/v1/ortomosaicos que es solo rasters drone. Este endpoint:
  - Lista TODAS las capas publicadas en GeoNode
  - Las categoriza por subtype (raster, vector)
  - Devuelve WMS URL + bbox + bbox_crs para el visor
  - Hace merge con VisorLayerConfig (orden, destacada, color, etc)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..geonode_client import geonode
from ..models import VisorLayerConfig

router = APIRouter(prefix="/api/v1/layers", tags=["layers"])


class LayerOut(BaseModel):
    """Capa lista para consumir desde el geovisor."""

    model_config = ConfigDict(from_attributes=True)

    alternate: str                          # "geonode:ap_temp_1_1"
    title: str
    abstract: str | None = None
    subtype: str                            # "raster" | "vector"
    category: str                           # "ortomosaicos" | "vectoriales" | "otros"
    wms_url: str
    legend_url: str | None = None
    thumbnail_url: str | None = None
    bbox: list[float] | None = None         # [minx, miny, maxx, maxy] en WGS84
    # Config local del visor (puede ser None si no esta configurada)
    featured: bool = False                  # si default-on en el visor
    order: int = 999                        # orden de display
    default_opacity: float = 1.0
    color: str | None = None                # color override para vector


def _wms_base(alternate: str) -> str:
    return (
        f"{settings.geonode_public_wms_url}"
        f"?service=WMS&version=1.1.0&request=GetMap"
        f"&layers={alternate}&styles=&format=image/png&transparent=true"
        f"&srs=EPSG:3857&bbox={{bbox-epsg-3857}}&width=512&height=512"
    )


def _legend_url(alternate: str) -> str:
    return (
        f"{settings.geonode_public_wms_url}"
        f"?service=WMS&version=1.1.0&request=GetLegendGraphic"
        f"&format=image/png&layer={alternate}"
    )


def _categorize(alternate: str, subtype: str) -> str:
    """Heuristica simple por prefijo de nombre o subtype."""
    name = alternate.split(":", 1)[-1].lower()
    if subtype == "raster":
        if any(p in name for p in ("ortho", "ortomos", "ap_temp", "drone", "rgb")):
            return "ortomosaicos"
        return "raster_otros"
    # vector
    if any(p in name for p in ("parcela", "lote", "haciend")):
        return "haciendas"
    if any(p in name for p in ("via", "carret", "camin")):
        return "infraestructura"
    if any(p in name for p in ("limite", "provinc", "canton", "parroq")):
        return "limites"
    return "vectoriales"


def _bbox_from_dataset(ds: dict[str, Any]) -> list[float] | None:
    """Extrae bbox [minx, miny, maxx, maxy] en WGS84 desde la respuesta de GeoNode."""
    bbox_poly = ds.get("bbox_polygon")
    if bbox_poly and isinstance(bbox_poly, dict):
        coords = bbox_poly.get("coordinates", [[]])
        if coords and coords[0]:
            lons = [p[0] for p in coords[0]]
            lats = [p[1] for p in coords[0]]
            return [min(lons), min(lats), max(lons), max(lats)]
    return None


@router.get("", response_model=list[LayerOut])
async def list_layers(db: Session = Depends(get_db)) -> list[LayerOut]:
    """Lista TODAS las capas publicadas (raster + vector) con metadata para visor."""
    datasets = await geonode.list_datasets(page_size=200)
    # Indice de config local por alternate
    config_idx = {c.alternate: c for c in db.query(VisorLayerConfig).all()}

    out: list[LayerOut] = []
    for d in datasets:
        alt = d.get("alternate") or ""
        if not alt:
            continue
        subtype = d.get("subtype") or "vector"
        cfg = config_idx.get(alt)

        out.append(LayerOut(
            alternate=alt,
            title=d.get("title") or alt,
            abstract=d.get("abstract"),
            subtype=subtype,
            category=_categorize(alt, subtype),
            wms_url=_wms_base(alt),
            legend_url=_legend_url(alt),
            thumbnail_url=d.get("thumbnail_url"),
            bbox=_bbox_from_dataset(d),
            featured=bool(cfg.featured) if cfg else False,
            order=cfg.order if cfg else 999,
            default_opacity=float(cfg.default_opacity) if cfg else 1.0,
            color=cfg.color if cfg else None,
        ))

    # Ordenar: destacadas primero, luego por orden custom, luego por title
    out.sort(key=lambda x: (not x.featured, x.order, x.title.lower()))
    return out
