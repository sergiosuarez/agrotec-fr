"""Compresor de ortofotos a COG-JPEG.

Sube un GeoTIFF (p.ej. ortomosaico de drone de varios GB) y lo convierte a Cloud
Optimized GeoTIFF con compresion JPEG + overviews — tipicamente ~10-20x mas chico
(3 GB -> ~200 MB) sin perdida visual. Mismo resultado que GlobalMapper, pero como
servicio del sistema. Luego el COG resultante se sube por GeoNode.

Diseño para archivos grandes:
  - POST /api/v1/compress  -> sube el TIFF (streaming a disco) y encola un job en
                              background; devuelve {job_id} sin esperar el proceso.
  - GET  /api/v1/compress/{job_id}          -> estado del job (JSON en disco).
  - GET  /api/v1/compress/{job_id}/download -> descarga el COG cuando esta listo.

El estado vive en un archivo JSON por job (compartido entre los workers uvicorn del
mismo contenedor). rasterio/rio-cogeo se importan lazy (no pesan el arranque del visor).
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/v1/compress", tags=["compresor"])

WORK = Path("/tmp/compresor")
WORK.mkdir(parents=True, exist_ok=True)


def _dir(jid: str) -> Path:
    return WORK / jid


def _status_path(jid: str) -> Path:
    return _dir(jid) / "status.json"


def _read_status(jid: str) -> dict | None:
    p = _status_path(jid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _write_status(jid: str, **kw) -> None:
    d = _dir(jid)
    d.mkdir(parents=True, exist_ok=True)
    st = _read_status(jid) or {}
    st.update(kw)
    _status_path(jid).write_text(json.dumps(st))


def _cleanup_old(hours: int = 24) -> None:
    """Borra job dirs viejos para no acumular archivos pesados."""
    cutoff = time.time() - hours * 3600
    for d in WORK.glob("*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


def _compress(jid: str, in_path: Path, out_path: Path, quality: int) -> None:
    """Convierte el TIFF a COG-JPEG. Corre en background (thread del worker)."""
    try:
        _write_status(jid, state="running")
        import rasterio
        from rio_cogeo.cogeo import cog_translate
        from rio_cogeo.profiles import cog_profiles

        profile = cog_profiles.get("jpeg")
        profile.update(quality=int(quality), blocksize=512)

        # JPEG no soporta banda alfa: si el raster es RGBA (4 bandas), usamos solo
        # RGB y mandamos el alfa a una mascara interna (add_mask). 1 banda (gris) o
        # 3 bandas (RGB) van directo.
        with rasterio.open(str(in_path)) as src:
            count = src.count
        kwargs = dict(in_memory=False, overview_resampling="average", quiet=True)
        if count >= 4:
            kwargs.update(indexes=(1, 2, 3), add_mask=True)

        cog_translate(str(in_path), str(out_path), profile, **kwargs)

        in_size = in_path.stat().st_size
        out_size = out_path.stat().st_size
        in_path.unlink(missing_ok=True)   # liberar el original pesado
        _write_status(
            jid, state="done",
            in_bytes=in_size, out_bytes=out_size,
            ratio=round(in_size / out_size, 1) if out_size else None,
        )
    except Exception as e:
        _write_status(jid, state="error", error=str(e))
        try:
            in_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.post("")
async def start_compress(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    quality: int = Form(90),
) -> dict:
    """Recibe un GeoTIFF (streaming a disco) y encola la compresion en background."""
    _cleanup_old()
    if quality < 50 or quality > 100:
        raise HTTPException(400, "quality debe estar entre 50 y 100")

    jid = uuid.uuid4().hex[:12]
    d = _dir(jid)
    d.mkdir(parents=True, exist_ok=True)
    in_path = d / "input.tif"
    stem = Path(file.filename or "ortofoto").stem
    out_name = f"{stem}_cog.tif"
    out_path = d / out_name

    _write_status(jid, state="uploading", filename=file.filename, out_name=out_name)
    size = 0
    with in_path.open("wb") as f:
        while True:
            chunk = await file.read(4 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            size += len(chunk)
    _write_status(jid, state="queued", in_bytes=size)

    background.add_task(_compress, jid, in_path, out_path, quality)
    return {"job_id": jid}


@router.get("/{jid}")
def job_status(jid: str) -> dict:
    st = _read_status(jid)
    if st is None:
        raise HTTPException(404, "job no encontrado")
    return {"job_id": jid, **st}


@router.get("/{jid}/download")
def job_download(jid: str) -> FileResponse:
    st = _read_status(jid)
    if not st or st.get("state") != "done":
        raise HTTPException(409, "el COG aun no esta listo")
    out = _dir(jid) / st["out_name"]
    if not out.exists():
        raise HTTPException(404, "archivo no encontrado (¿job expirado?)")
    return FileResponse(str(out), filename=st["out_name"], media_type="image/tiff")
