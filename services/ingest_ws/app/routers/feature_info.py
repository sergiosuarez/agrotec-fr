"""GET /api/v1/feature-info — proxy a GeoServer WMS GetFeatureInfo para popups.

El navegador no puede hacer GetFeatureInfo cross-origin directo a /geoserver/
por restricciones CORS de algunas configuraciones. Este endpoint hace el
request server-side y devuelve el JSON.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..config import settings

router = APIRouter(prefix="/api/v1/feature-info", tags=["feature-info"])


@router.get("")
async def get_feature_info(
    layer: str = Query(..., description="alternate de la capa, ej: geonode:lotes_amelia"),
    bbox: str = Query(..., description="minx,miny,maxx,maxy en EPSG:3857"),
    x: int = Query(..., description="pixel x en la tile"),
    y: int = Query(..., description="pixel y en la tile"),
    width: int = Query(256),
    height: int = Query(256),
) -> dict:
    """Hace GetFeatureInfo a GeoServer y devuelve el JSON con los atributos."""
    # Usamos la URL interna de GeoServer (a traves del nginx interno)
    url = (
        f"{settings.geonode_internal_wfs_url.replace('/wfs', '/ows')}"
        f"?service=WMS&version=1.1.1&request=GetFeatureInfo"
        f"&layers={layer}&query_layers={layer}&srs=EPSG:3857&bbox={bbox}"
        f"&width={width}&height={height}&x={x}&y={y}"
        f"&info_format=application/json&feature_count=10"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"upstream error: {e}")
    except ValueError:
        # GeoServer puede responder XML cuando no hay features
        return {"type": "FeatureCollection", "features": [], "totalFeatures": 0}
