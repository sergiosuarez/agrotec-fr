"""FastAPI app entrypoint."""
from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import _session_is_valid, auth_middleware
from .config import settings
from .routers import (
    compresor,
    cultivos,
    feature_info,
    gfs,
    haciendas,
    health,
    layers,
    ortomosaicos,
    parcelas,
    visor_config,
)

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

# Gating por sesión de GeoNode (SSO). Solo actúa si VISOR_AUTH_REQUIRED=true.
app.middleware("http")(auth_middleware)


@app.on_event("startup")
async def _prewarm_datasets_cache() -> None:
    """Pre-carga la caché de capas de GeoNode al arrancar (en segundo plano),
    para que el primer usuario no espere los ~35s de la API de GeoNode."""
    import asyncio

    from .routers.layers import refresh_datasets_cache

    asyncio.create_task(refresh_datasets_cache())

# Routers
app.include_router(health.router)
app.include_router(cultivos.router)
app.include_router(haciendas.router)
app.include_router(parcelas.router)
app.include_router(ortomosaicos.router)
app.include_router(gfs.router)
app.include_router(layers.router)
app.include_router(visor_config.router)
app.include_router(feature_info.router)
app.include_router(compresor.router)

# Geovisor web (static) — sirve /static/* y / (index.html)
app.mount("/static", StaticFiles(directory="static"), name="static")


# no-cache: el navegador revalida siempre (con ETag) y toma la última versión del
# visor tras cada deploy, sin quedarse con un index.html viejo cacheado.
_NOCACHE = {"Cache-Control": "no-cache"}


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse("static/index.html", headers=_NOCACHE)


@app.get("/compresor", include_in_schema=False)
def compresor_page() -> FileResponse:
    return FileResponse("static/compresor.html", headers=_NOCACHE)


@app.get("/auth/check", include_in_schema=False)
async def auth_check(request: Request) -> Response:
    """Validación de sesión para nginx auth_request (gating de GeoServer).

    200 si la cookie `sessionid` corresponde a un usuario logueado en GeoNode; 401 si no.
    """
    sid = request.cookies.get("sessionid")
    if sid and await _session_is_valid(sid):
        return Response(status_code=200)
    return Response(status_code=401)
