"""FastAPI app entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import cultivos, gfs, haciendas, health, ortomosaicos, parcelas

app = FastAPI(
    title="Agrotec API",
    description=(
        "API REST del visor Agrotec. Consume capas de GeoNode/GeoServer y NetCDF GFS "
        "de THREDDS; expone modelo agricola (Hacienda > Parcela > Lote, Cultivo, Ortomosaico)."
    ),
    version="0.1.0",
)

# CORS — el visor web se sirve del mismo dominio normalmente, pero permitimos
# orígenes adicionales en desarrollo.
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router)
app.include_router(cultivos.router)
app.include_router(haciendas.router)
app.include_router(parcelas.router)
app.include_router(ortomosaicos.router)
app.include_router(gfs.router)

# Geovisor web (static) — sirve /static/* y / (index.html)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse("static/index.html")
