"""Pydantic schemas para respuestas API."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class CultivoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    nombre_cientifico: str | None = None
    ciclo_dias: int | None = None
    perenne: bool


class HaciendaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    propietario: str | None = None
    codigo: str | None = None
    area_ha: Decimal | None = None
    contacto: dict[str, Any] = {}
    created_at: datetime


class ParcelaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hacienda_id: int
    nombre: str
    codigo: str | None = None
    area_ha: Decimal | None = None
    created_at: datetime


class LoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parcela_id: int
    nombre: str
    cultivo_id: int | None = None
    fecha_siembra: date | None = None
    area_ha: Decimal | None = None
    estado: str


class OrtomosaicoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    geonode_alternate: str
    parcela_id: int | None = None
    hacienda_id: int | None = None
    fecha_vuelo: date | None = None
    resolucion_m: Decimal | None = None
    wms_url: str | None = None
    preview_url: str | None = None


class HealthOut(BaseModel):
    status: str
    version: str
    db: str
    geonode: str
    thredds: str


class GFSStatusOut(BaseModel):
    available: bool
    files: list[dict[str, Any]]
    last_modified: datetime | None = None
