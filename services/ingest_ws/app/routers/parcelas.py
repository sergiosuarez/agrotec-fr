"""GET /api/v1/parcelas — parcelas por hacienda."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Parcela
from ..schemas import ParcelaOut

router = APIRouter(prefix="/api/v1/parcelas", tags=["parcelas"])


@router.get("", response_model=list[ParcelaOut])
def list_parcelas(
    hacienda_id: int | None = Query(None, description="Filtrar por hacienda"),
    db: Session = Depends(get_db),
) -> list[Parcela]:
    stmt = select(Parcela).order_by(Parcela.nombre)
    if hacienda_id is not None:
        stmt = stmt.where(Parcela.hacienda_id == hacienda_id)
    return list(db.scalars(stmt))


@router.get("/{parcela_id}", response_model=ParcelaOut)
def get_parcela(parcela_id: int, db: Session = Depends(get_db)) -> Parcela:
    row = db.get(Parcela, parcela_id)
    if not row:
        raise HTTPException(404, detail="parcela no encontrada")
    return row
