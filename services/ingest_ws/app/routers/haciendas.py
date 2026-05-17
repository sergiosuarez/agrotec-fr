"""GET /api/v1/haciendas — lista y detalle de haciendas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Hacienda
from ..schemas import HaciendaOut

router = APIRouter(prefix="/api/v1/haciendas", tags=["haciendas"])


@router.get("", response_model=list[HaciendaOut])
def list_haciendas(db: Session = Depends(get_db)) -> list[Hacienda]:
    return list(db.scalars(select(Hacienda).order_by(Hacienda.nombre)))


@router.get("/{hacienda_id}", response_model=HaciendaOut)
def get_hacienda(hacienda_id: int, db: Session = Depends(get_db)) -> Hacienda:
    row = db.get(Hacienda, hacienda_id)
    if not row:
        raise HTTPException(404, detail="hacienda no encontrada")
    return row
