"""POST/PUT /api/v1/visor/config — admin del visor (marcar destacadas, ordenar)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import VisorLayerConfig

router = APIRouter(prefix="/api/v1/visor", tags=["visor-config"])


class LayerConfigIn(BaseModel):
    alternate: str
    visible: bool | None = None
    featured: bool | None = None
    order: int | None = None
    default_opacity: float | None = None
    color: str | None = None


@router.put("/config", status_code=200)
def upsert_layer_config(payload: LayerConfigIn, db: Session = Depends(get_db)) -> dict:
    """Crea o actualiza la configuracion de una capa.

    No requiere todos los campos: solo actualiza lo que se envia.
    Idempotente.
    """
    cfg = db.query(VisorLayerConfig).filter_by(alternate=payload.alternate).first()
    if not cfg:
        cfg = VisorLayerConfig(
            alternate=payload.alternate,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(cfg)

    if payload.visible is not None:
        cfg.visible = payload.visible
    if payload.featured is not None:
        cfg.featured = payload.featured
    if payload.order is not None:
        cfg.order = payload.order
    if payload.default_opacity is not None:
        cfg.default_opacity = payload.default_opacity
    if payload.color is not None:
        cfg.color = payload.color

    cfg.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cfg)

    return {
        "alternate": cfg.alternate,
        "visible": cfg.visible,
        "featured": cfg.featured,
        "order": cfg.order,
        "default_opacity": float(cfg.default_opacity),
        "color": cfg.color,
    }


@router.delete("/config/{alternate:path}", status_code=204)
def delete_layer_config(alternate: str, db: Session = Depends(get_db)) -> None:
    cfg = db.query(VisorLayerConfig).filter_by(alternate=alternate).first()
    if not cfg:
        raise HTTPException(404, "config no encontrada")
    db.delete(cfg)
    db.commit()
