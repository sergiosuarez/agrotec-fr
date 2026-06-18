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

# Capa autoritativa de límites de hacienda en geonode_data: 1 polígono por hacienda,
# `nombre` (display) + `nombre_hcd` (código, ej. HCDA_AMELIA). El visor la filtra por
# `nombre_hcd` para mostrar/encuadrar la hacienda elegida.
_HACIENDAS_TABLE = "haciendas_totales"


class HaciendaExtentOut(BaseModel):
    nombre: str                       # nombre legible (ej. "Amelia", "Jenny Elizabeth-1")
    codigo: str                       # nombre_hcd (ej. "HCDA_AMELIA") — para filtrar la capa
    area_ha: float | None = None
    bbox: list[float]                 # [minx, miny, maxx, maxy] WGS84


@router.get("/extents", response_model=list[HaciendaExtentOut])
def haciendas_extents() -> list[HaciendaExtentOut]:
    """Las 26 haciendas (límites reales) con su bbox WGS84, código y área.

    Fuente: `haciendas_totales` (geonode_data). Arma el catálogo para el selector de
    hacienda global del visor.
    """
    sql = text(f"""
        SELECT nombre,
               nombre_hcd AS codigo,
               round((ST_Area(ST_Force2D(geometry)) / 10000.0)::numeric, 2) AS area_ha,
               ST_XMin(g) AS minx, ST_YMin(g) AS miny,
               ST_XMax(g) AS maxx, ST_YMax(g) AS maxy
        FROM (
            SELECT nombre, nombre_hcd, geometry,
                   ST_Transform(ST_Force2D(geometry), 4326) AS g
            FROM {_HACIENDAS_TABLE}
            WHERE nombre IS NOT NULL AND nombre <> ''
        ) t
        ORDER BY nombre
    """)
    try:
        with get_geodata_engine().connect() as conn:
            rows = conn.execute(sql).mappings().all()
    except Exception as e:
        raise HTTPException(503, f"geodata no disponible: {e}")

    return [
        HaciendaExtentOut(
            nombre=r["nombre"],
            codigo=r["codigo"],
            area_ha=float(r["area_ha"]) if r["area_ha"] is not None else None,
            bbox=[r["minx"], r["miny"], r["maxx"], r["maxy"]],
        )
        for r in rows
    ]


class LoteAreaOut(BaseModel):
    lote: str
    area_ha: float


@router.get("/lotes", response_model=list[LoteAreaOut])
def hacienda_lotes(
    nombre: str = Query(..., description="nombre legible de la hacienda (sin sufijo de pieza)"),
) -> list[LoteAreaOut]:
    """Área (ha) por lote de una hacienda — para el resumen/pie chart del visor.

    Fuente: `haciendas_palmar`. Empareja por nombre (los lotes guardan
    'Agricola <Nombre>' en nombre_hcd) con ILIKE. El área se calcula desde la
    geometría porque la columna area_ha es texto.
    """
    sql = text("""
        SELECT lotes AS lote,
               round((SUM(ST_Area(ST_Force2D(geometry))) / 10000.0)::numeric, 2) AS area_ha
        FROM haciendas_palmar
        WHERE nombre_hcd ILIKE '%' || :nombre || '%' AND lotes IS NOT NULL
        GROUP BY lotes
        ORDER BY area_ha DESC NULLS LAST
    """)
    try:
        with get_geodata_engine().connect() as conn:
            rows = conn.execute(sql, {"nombre": nombre}).mappings().all()
    except Exception as e:
        raise HTTPException(503, f"geodata no disponible: {e}")
    return [LoteAreaOut(lote=str(r["lote"]), area_ha=float(r["area_ha"] or 0)) for r in rows]


@router.get("", response_model=list[HaciendaOut])
def list_haciendas(db: Session = Depends(get_db)) -> list[Hacienda]:
    return list(db.scalars(select(Hacienda).order_by(Hacienda.nombre)))


@router.get("/{hacienda_id}", response_model=HaciendaOut)
def get_hacienda(hacienda_id: int, db: Session = Depends(get_db)) -> Hacienda:
    row = db.get(Hacienda, hacienda_id)
    if not row:
        raise HTTPException(404, detail="hacienda no encontrada")
    return row
