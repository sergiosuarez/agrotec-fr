"""GET /api/v1/haciendas — lista y detalle de haciendas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..database import get_db, get_geodata_engine
from ..models import Hacienda
from ..schemas import HaciendaOut

router = APIRouter(prefix="/api/v1/haciendas", tags=["haciendas"])

# Capa GeoNode (geonode_data) que contiene los lotes de todas las haciendas, con el
# atributo `nombre_hcd` identificando a cual hacienda pertenece cada poligono.
_HACIENDAS_TABLE = "haciendas_palmar"
_HACIENDA_ATTR = "nombre_hcd"


class HaciendaExtentOut(BaseModel):
    nombre: str
    n_lotes: int
    area_ha: float | None = None
    bbox: list[float]                 # [minx, miny, maxx, maxy] WGS84


@router.get("/extents", response_model=list[HaciendaExtentOut])
def haciendas_extents(
    layer: str = Query(_HACIENDAS_TABLE, description="tabla de lotes en geonode_data"),
    attr: str = Query(_HACIENDA_ATTR, description="atributo que identifica la hacienda"),
) -> list[HaciendaExtentOut]:
    """Lista de haciendas con su bbox (WGS84), nro de lotes y area, derivada de la
    capa vectorial publicada en GeoNode (atributo `nombre_hcd`).

    No depende de la tabla relacional `hacienda` (que puede estar vacia); arma el
    catalogo directo de la geodata para el selector de hacienda del visor.
    """
    # Whitelist defensivo: solo identificadores simples (no inyeccion en el SQL armado).
    if not layer.replace("_", "").isalnum() or not attr.replace("_", "").isalnum():
        raise HTTPException(400, "layer/attr invalidos")

    sql = text(f"""
        SELECT {attr} AS nombre,
               count(*) AS n_lotes,
               round((sum(ST_Area(geometry)) / 10000.0)::numeric, 2) AS area_ha,
               ST_XMin(ST_Extent(ST_Transform(ST_Force2D(geometry), 4326))) AS minx,
               ST_YMin(ST_Extent(ST_Transform(ST_Force2D(geometry), 4326))) AS miny,
               ST_XMax(ST_Extent(ST_Transform(ST_Force2D(geometry), 4326))) AS maxx,
               ST_YMax(ST_Extent(ST_Transform(ST_Force2D(geometry), 4326))) AS maxy
        FROM {layer}
        WHERE {attr} IS NOT NULL AND {attr} <> ''
        GROUP BY {attr}
        ORDER BY {attr}
    """)
    try:
        with get_geodata_engine().connect() as conn:
            rows = conn.execute(sql).mappings().all()
    except Exception as e:
        raise HTTPException(503, f"geodata no disponible: {e}")

    return [
        HaciendaExtentOut(
            nombre=r["nombre"],
            n_lotes=r["n_lotes"],
            area_ha=float(r["area_ha"]) if r["area_ha"] is not None else None,
            bbox=[r["minx"], r["miny"], r["maxx"], r["maxy"]],
        )
        for r in rows
    ]


@router.get("", response_model=list[HaciendaOut])
def list_haciendas(db: Session = Depends(get_db)) -> list[Hacienda]:
    return list(db.scalars(select(Hacienda).order_by(Hacienda.nombre)))


@router.get("/{hacienda_id}", response_model=HaciendaOut)
def get_hacienda(hacienda_id: int, db: Session = Depends(get_db)) -> Hacienda:
    row = db.get(Hacienda, hacienda_id)
    if not row:
        raise HTTPException(404, detail="hacienda no encontrada")
    return row
