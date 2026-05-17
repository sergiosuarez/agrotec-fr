"""ORM SQLAlchemy mapeando el schema PostGIS de db/init/02_schema.sql."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Cultivo(Base):
    __tablename__ = "cultivo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String, unique=True)
    nombre_cientifico: Mapped[str | None] = mapped_column(String)
    ciclo_dias: Mapped[int | None] = mapped_column(Integer)
    perenne: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Hacienda(Base):
    __tablename__ = "hacienda"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String)
    propietario: Mapped[str | None] = mapped_column(String)
    codigo: Mapped[str | None] = mapped_column(String, unique=True)
    ubicacion = mapped_column(Geography("POINT", srid=4326), nullable=True)
    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    contacto: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    parcelas: Mapped[list["Parcela"]] = relationship(back_populates="hacienda", cascade="all, delete-orphan")


class Parcela(Base):
    __tablename__ = "parcela"

    id: Mapped[int] = mapped_column(primary_key=True)
    hacienda_id: Mapped[int] = mapped_column(ForeignKey("hacienda.id", ondelete="CASCADE"))
    nombre: Mapped[str] = mapped_column(String)
    codigo: Mapped[str | None] = mapped_column(String)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    hacienda: Mapped[Hacienda] = relationship(back_populates="parcelas")
    lotes: Mapped[list["Lote"]] = relationship(back_populates="parcela", cascade="all, delete-orphan")


class Lote(Base):
    __tablename__ = "lote"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcela_id: Mapped[int] = mapped_column(ForeignKey("parcela.id", ondelete="CASCADE"))
    nombre: Mapped[str] = mapped_column(String)
    cultivo_id: Mapped[int | None] = mapped_column(ForeignKey("cultivo.id", ondelete="SET NULL"))
    fecha_siembra: Mapped[date | None] = mapped_column(Date)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    estado: Mapped[str] = mapped_column(String, default="activo")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    parcela: Mapped[Parcela] = relationship(back_populates="lotes")
    cultivo: Mapped[Cultivo | None] = relationship()


class Ortomosaico(Base):
    __tablename__ = "ortomosaico"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcela_id: Mapped[int | None] = mapped_column(ForeignKey("parcela.id", ondelete="SET NULL"))
    hacienda_id: Mapped[int | None] = mapped_column(ForeignKey("hacienda.id", ondelete="CASCADE"))
    nombre: Mapped[str] = mapped_column(String)
    geonode_alternate: Mapped[str] = mapped_column(String, unique=True)
    geonode_uuid = mapped_column(Uuid, nullable=True)
    fecha_vuelo: Mapped[date | None] = mapped_column(Date)
    resolucion_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    geom_bbox = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    srid_origen: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
