"""GET /api/v1/ortomosaicos — lista de ortomosaicos (sync con GeoNode al vuelo)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..geonode_client import geonode
from ..schemas import OrtomosaicoOut

router = APIRouter(prefix="/api/v1/ortomosaicos", tags=["ortomosaicos"])


def _wms_url(alternate: str) -> str:
    return f"{settings.geonode_public_wms_url}?service=WMS&version=1.3.0&request=GetMap&layers={alternate}"


@router.get("", response_model=list[OrtomosaicoOut])
async def list_ortomosaicos(
    db: Session = Depends(get_db),
    sync: bool = Query(False, description="Si True, sincroniza desde GeoNode al vuelo"),
) -> list[OrtomosaicoOut]:
    """Lista ortomosaicos.

    Si `sync=True`, consulta GeoNode y arma la respuesta desde su API (no toca la
    BD local). Util mientras no esta llena la tabla `ortomosaico`.
    """
    if sync:
        datasets = await geonode.list_datasets()
        # Filtramos solo raster (los vectoriales tendrian subtype != raster).
        out: list[OrtomosaicoOut] = []
        for d in datasets:
            if d.get("subtype") != "raster":
                continue
            alt = d.get("alternate") or ""
            out.append(
                OrtomosaicoOut(
                    id=d.get("pk") or 0,
                    nombre=d.get("title") or alt,
                    geonode_alternate=alt,
                    wms_url=_wms_url(alt),
                    preview_url=d.get("thumbnail_url"),
                )
            )
        return out

    # TODO: query desde tabla `ortomosaico` cuando este poblada
    return []
