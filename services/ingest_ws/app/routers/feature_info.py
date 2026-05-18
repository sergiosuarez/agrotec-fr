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
    lat: float = Query(..., ge=-90, le=90, description="latitud WGS84 del click"),
    lng: float = Query(..., ge=-180, le=180, description="longitud WGS84 del click"),
    tolerance: float = Query(0.0005, description="grados a buscar alrededor del punto"),
) -> dict:
    """GetFeatureInfo a GeoServer usando un bbox WGS84 alrededor del punto clickeado.

    Mas simple que pasar pixel coords + tile bbox: el caller solo envia el punto
    (lat/lng) y nosotros armamos un bbox pequeno alrededor para GeoServer.
    """
    # Bbox WGS84 alrededor del punto (tolerance grados ~50m a tropicos)
    minx, miny, maxx, maxy = lng - tolerance, lat - tolerance, lng + tolerance, lat + tolerance
    url = (
        f"{settings.geonode_internal_wfs_url.replace('/wfs', '/ows')}"
        f"?service=WMS&version=1.1.1&request=GetFeatureInfo"
        f"&layers={layer}&query_layers={layer}"
        f"&srs=EPSG:4326&bbox={minx},{miny},{maxx},{maxy}"
        f"&width=11&height=11&x=5&y=5"
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
        return {"type": "FeatureCollection", "features": [], "totalFeatures": 0}
