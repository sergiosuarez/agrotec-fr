"""Gating del visor por sesión de GeoNode (SSO).

El visor y GeoNode comparten dominio (idepalma.desarrollowebsite.com), así que la
cookie `sessionid` de GeoNode también llega a /visor/. Validamos esa sesión contra
una vista de GeoNode protegida con login (`/messages/inbox/` → 200 si autenticado,
302 al login si anónimo). Sirve para CUALQUIER usuario logueado, incluidos analistas
no-staff. Si no hay sesión válida: navegador → redirige al login; XHR/API → 401.
(Nota: `/api/v2/users/me` no sirve aquí — da 403/404 incluso autenticado.)

Roles:
  - Administrador  = staff/superusuario de GeoNode → entra a GeoNode y edita capas.
  - Analista       = cualquier usuario autenticado (p. ej. grupo "Analistas") → ve el visor.

Se activa con la env VISOR_AUTH_REQUIRED=true (apagado por defecto para no bloquear).
"""
from __future__ import annotations

import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import settings

# Rutas que NO requieren sesión: healthcheck, estáticos, y el endpoint /auth/check
# (lo usa nginx via auth_request para gatear GeoServer; hace su propia validación).
_PUBLIC_PREFIXES = ("/health", "/static", "/favicon", "/auth")

# Caché de validación por sessionid (evita consultar a GeoNode en cada request).
# {sessionid: (es_valido, expira_en_epoch)}
_cache: dict[str, tuple[bool, float]] = {}
_TTL = 60.0  # segundos


async def _session_is_valid(sessionid: str) -> bool:
    now = time.time()
    cached = _cache.get(sessionid)
    if cached and cached[1] > now:
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{settings.geonode_base_url.rstrip('/')}/messages/inbox/",
                headers={
                    "Host": settings.geonode_host_header,
                    "Cookie": f"sessionid={sessionid}",
                },
            )
        # 200 = sesión válida (vista login_required render). 302 = anónimo → al login.
        valid = r.status_code == 200
    except httpx.HTTPError:
        # Si GeoNode no responde (hipo de red), NO bloqueamos: evita tumbar el visor
        # por una caída transitoria de GeoNode. Un 4xx/5xx sí bloquea (valid=False).
        valid = True
    _cache[sessionid] = (valid, now + _TTL)
    return valid


async def auth_middleware(request: Request, call_next):
    if not settings.visor_auth_required:
        return await call_next(request)

    path = request.url.path
    if request.method == "OPTIONS" or path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)

    sessionid = request.cookies.get("sessionid")
    if sessionid and await _session_is_valid(sessionid):
        return await call_next(request)

    if "text/html" in request.headers.get("accept", ""):
        login = f"{settings.geonode_public_base_url.rstrip('/')}/account/login/?next=/visor/"
        return RedirectResponse(login, status_code=302)
    return JSONResponse(
        {"detail": "No autenticado. Inicie sesión en el geoportal."}, status_code=401
    )
