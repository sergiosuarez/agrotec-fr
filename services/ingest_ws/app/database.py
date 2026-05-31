"""Sesion SQLAlchemy compartida."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Engine read-only hacia la geodata de GeoNode (geonode_data). Lazy: solo se crea
# al primer uso para no fallar el arranque si la BD aun no esta disponible.
_geodata_engine = None


def get_geodata_engine():
    global _geodata_engine
    if _geodata_engine is None:
        _geodata_engine = create_engine(
            settings.geodata_url, pool_pre_ping=True, pool_size=2, max_overflow=3
        )
    return _geodata_engine


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
