"""GET /api/v1/gfs/status — estado del NetCDF generado por agrotec_gfs_scheduler."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from ..config import settings
from ..schemas import GFSStatusOut

router = APIRouter(prefix="/api/v1/gfs", tags=["gfs"])


@router.get("/status", response_model=GFSStatusOut)
def gfs_status() -> GFSStatusOut:
    """Lista los NetCDF en el volumen compartido con el scheduler."""
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
