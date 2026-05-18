"""Configuracion centralizada via Pydantic Settings (lee de env)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # FastAPI
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_workers: int = 4
    cors_origins: str = "*"

    # Base de datos
    database_url: str = "postgresql+psycopg://agrotecuser:changeme@agrotec_db:5432/agrotecdb"

    # Redis
    redis_url: str = "redis://agrotec_redis:6379/0"

    # GeoNode (red interna)
    geonode_base_url: str = "http://nginx4agrotec:80"
    geonode_public_base_url: str = "https://idepalma.desarrollowebsite.com"
    geonode_public_wms_url: str = "https://idepalma.desarrollowebsite.com/geoserver/ows"
    geonode_public_wfs_url: str = "https://idepalma.desarrollowebsite.com/geoserver/ows"
    geonode_internal_wfs_url: str = "http://geoserver4agrotec:8080/geoserver/ows"
    geonode_host_header: str = "idepalma.desarrollowebsite.com"

    # THREDDS / GFS
    thredds_url: str = "http://agrotec_thredds:8080"
    gfs_dir: str = "/data/actual"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
