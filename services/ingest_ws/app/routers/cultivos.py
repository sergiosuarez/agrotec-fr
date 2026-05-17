"""GET /api/v1/cultivos — catalogo de cultivos."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cultivo
from ..schemas import CultivoOut

router = APIRouter(prefix="/api/v1/cultivos", tags=["cultivos"])


@router.get("", response_model=list[CultivoOut])
def list_cultivos(db: Session = Depends(get_db)) -> list[Cultivo]:
    return list(db.scalars(select(Cultivo).order_by(Cultivo.nombre)))
