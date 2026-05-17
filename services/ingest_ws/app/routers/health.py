"""GET /health — estado del visor y servicios upstream."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..geonode_client import geonode
from ..schemas import HealthOut

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthOut)
async def health(db: Session = Depends(get_db)) -> HealthOut:
    # DB
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {type(e).__name__}"

    # GeoNode
    geonode_status = "ok" if await geonode.ping() else "down"

    # THREDDS
    thredds_status = "down"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.thredds_url}/thredds/catalog.html")
            if r.status_code < 500:
                thredds_status = "ok"
    except httpx.HTTPError:
        pass

    return HealthOut(
        status="ok",
        version=VERSION,
        db=db_status,
        geonode=geonode_status,
        thredds=thredds_status,
    )
