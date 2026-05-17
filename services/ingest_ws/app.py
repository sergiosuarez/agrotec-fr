import os, json, time, asyncio
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from projection import calculate_projection
from spatial_checks import check_spatial_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from pydantic import BaseModel, Field
import redis.asyncio as aioredis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
import httpx
from urllib.parse import quote, urlparse



def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieves env var, stripping surrounding quotes if present."""
    val = os.getenv(key, default)
    if val and val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val


# --- conexión a la DB del catálogo (Odoo) ---
EXTDB_HOST = os.getenv("EXTDB_HOST", "")
EXTDB_PORT = os.getenv("EXTDB_PORT", "5432")
EXTDB_NAME = os.getenv("EXTDB_NAME", "")
EXTDB_USER = os.getenv("EXTDB_USER", "")
EXTDB_PASSWORD = os.getenv("EXTDB_PASSWORD", "")
EXTDB_SSLMODE = os.getenv("EXTDB_SSLMODE", "disable")  # prefer/require/disable

# --- conexión a la DB interna (PostGIS local o remoto) ---
GISDB_HOST = os.getenv("GISDB_HOST", "gis_db")
GISDB_PORT = os.getenv("GISDB_PORT", "5432")
GISDB_NAME = os.getenv("GISDB_NAME", "gis")
GISDB_USER = os.getenv("GISDB_USER", "postgres")
GISDB_PASSWORD = os.getenv("GISDB_PASSWORD", "postgres")
GISDB_SSLMODE = os.getenv("GISDB_SSLMODE", "disable")

DATABASE_URL = (
    f"postgresql+psycopg2://{GISDB_USER}:{GISDB_PASSWORD}"
    f"@{GISDB_HOST}:{GISDB_PORT}/{GISDB_NAME}"
    f"?sslmode={GISDB_SSLMODE}"
)

# --- conexión a la DB del catálogo (Odoo) ---
EXT_DATABASE_URL = (
    f"postgresql+psycopg2://{EXTDB_USER}:{EXTDB_PASSWORD}"
    f"@{EXTDB_HOST}:{EXTDB_PORT}/{EXTDB_NAME}"
    f"?sslmode={EXTDB_SSLMODE}"
    if EXTDB_HOST and EXTDB_NAME else None
)

ext_engine = create_engine(EXT_DATABASE_URL, pool_pre_ping=True) if EXT_DATABASE_URL else None

REDIS_URL = get_env("REDIS_URL", "redis://redis:6379")
CORS_ORIGINS = [o.strip() for o in get_env("CORS_ORIGINS", "http://localhost:8000").split(",")]

GEONODE_BASE_URL = get_env("GEONODE_BASE_URL", "http://geonode:8082").rstrip("/")
GEONODE_PUBLIC_BASE_URL = get_env("GEONODE_PUBLIC_BASE_URL", GEONODE_BASE_URL).rstrip("/")
GEONODE_PUBLIC_WMS_URL = get_env("GEONODE_PUBLIC_WMS_URL", f"{GEONODE_PUBLIC_BASE_URL}/geoserver/ows").rstrip("?")
GEONODE_PUBLIC_WFS_URL = get_env("GEONODE_PUBLIC_WFS_URL", GEONODE_PUBLIC_WMS_URL).rstrip("?")
GEONODE_INTERNAL_WFS_URL = get_env("GEONODE_INTERNAL_WFS_URL", "http://geoserver:8080/geoserver/ows").rstrip("?")
GEONODE_OAUTH_TOKEN_URL = get_env("GEONODE_OAUTH_TOKEN_URL", f"{GEONODE_BASE_URL}/o/token/").rstrip("/") + "/"
GEONODE_OAUTH_CLIENT_ID = get_env("GEONODE_OAUTH_CLIENT_ID")
GEONODE_OAUTH_CLIENT_SECRET = get_env("GEONODE_OAUTH_CLIENT_SECRET")
GEONODE_HOST_HEADER = get_env("GEONODE_HOST_HEADER")
GEONODE_SERVICE_USERNAME = get_env("GEONODE_SERVICE_USERNAME")
GEONODE_SERVICE_PASSWORD = get_env("GEONODE_SERVICE_PASSWORD")
STATIC_LAYER_REFRESH_ZONAS = int(get_env("STATIC_LAYER_REFRESH_ZONAS", "120"))
DMS_SYNC_INTERVAL = int(get_env("DMS_SYNC_INTERVAL", "30"))
ALERTS_LIMIT_DEFAULT = int(get_env("ALERTS_LIMIT_DEFAULT", "200"))
# Copernicus (WMS externo opcional)
COPERNICUS_WMS_URL = os.getenv("COPERNICUS_WMS_URL", "")
COPERNICUS_WMS_LAYER = os.getenv("COPERNICUS_WMS_LAYER", "")
COPERNICUS_WMS_STYLE = os.getenv("COPERNICUS_WMS_STYLE", "")

# Capas base por defecto: vacías para que todo se administre desde layer-admin
STATIC_LAYER_CONFIG: list[dict] = []

layer_cache: dict[str, dict] = {}
layer_cache_meta: dict[str, dict] = {}
service_token: dict[str, float] = {"token": None, "expires": 0}
LAYER_SELECTION_KEY = "static_layers:selection"
LAYER_AVAILABLE_CACHE_KEY = "static_layers:available"
LAYER_AVAILABLE_CACHE_TTL = 600
COPERNICUS_CONFIG_KEY = "static_layers:copernicus_config"

app = FastAPI(title="GIS Realtime Prototype")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

redis: aioredis.Redis | None = None
engine: Engine | None = None
subscribers: set[WebSocket] = set()

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Dashboard GeoNode – SIGMAP</title>
  <style>
    html, body {
      height: 100%;
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      display: flex;
      flex-direction: column;
    }
    header {
      padding: 16px 24px;
      background: rgba(15, 23, 42, 0.9);
      border-bottom: 1px solid rgba(148, 163, 184, 0.25);
      box-shadow: 0 2px 12px rgba(15, 23, 42, 0.4);
    }
    header h1 {
      margin: 0;
      font-size: clamp(20px, 2.2vw, 28px);
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    header p {
      margin: 4px 0 0;
      font-size: 14px;
      color: #94a3b8;
    }
    main {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
      background: radial-gradient(circle at top, rgba(96, 165, 250, 0.12), transparent 60%);
    }
    .frame-wrapper {
      width: min(1280px, 100%);
      aspect-ratio: 16 / 9;
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 25px 60px rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(148, 163, 184, 0.25);
      background: #020617;
    }
    iframe {
      width: 100%;
      height: 100%;
      border: none;
    }
  </style>
</head>
<body>  
  <iframe allow="fullscreen" width="560" height="315" src="http://167.86.111.196:8082/apps/33/embed?allowFullscreen=true" frameborder="0" ></iframe>
</body>
</html>
"""

class Telemetry(BaseModel):
    mmsi: int
    matricula: Optional[str] = None
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    sog_knots: Optional[float] = None
    cog_deg: Optional[float] = None
    heading_deg: Optional[float] = None
    ts: Optional[float] = None
    source: Optional[str] = None
    panic: Optional[bool] = None

    def to_dict(self):
        d = self.model_dump()
        if d.get("ts") is None:
            d["ts"] = time.time()
        return d

class LayerSelectionPayload(BaseModel):
    layers: List[str]

class CopernicusConfigPayload(BaseModel):
    url: str
    layer: str
    style: Optional[str] = ""
    visible: Optional[bool] = False
    time: Optional[str] = None
    params: Optional[str] = None

class LoginPayload(BaseModel):
    username: str
    password: str


def build_wms_tile_url(layer_name: str, style: str = "", format_: str = "image/png", time: Optional[str] = None, base_url: Optional[str] = None) -> str:
    base = (base_url or GEONODE_PUBLIC_WMS_URL).rstrip("?")
    separator = "&" if "?" in base else "?"
    params = (
        f"service=WMS&version=1.1.1&request=GetMap&layers={layer_name}"
        f"&styles={style}&bbox={{bbox-epsg-3857}}&width=256&height=256"
        f"&srs=EPSG:3857&format={format_}&transparent=true"
    )
    if time:
        params += f"&time={time}"
    raw = f"{base}{separator}{params}"
    # Si la URL remota está en la lista de hosts que proxyamos, devolver la URL del proxy
    if should_proxy_url(raw):
        return f"/proxy/wms?url={quote(raw, safe='')}"
    return raw


def should_proxy_url(url: str) -> bool:
    """Decide si una URL remota debe ser accedida vía proxy interno.
    Usa la variable de entorno `WMS_PROXY_ALLOW` para listar hosts permitidos.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return False
    allow_env = os.getenv("WMS_PROXY_ALLOW", "thredds.ucar.edu,wmts.marine.copernicus.eu")
    allowed = [h.strip().lower() for h in allow_env.split(",") if h.strip()]
    for a in allowed:
        if a and a in hostname:
            return True
    return False


def normalize_typename(raw: str | None, workspace: Optional[str] = None) -> Optional[str]:
    """
    Devuelve workspace:name evitando duplicados como geonode:geonode:puertos.
    """
    if not raw:
        return None
    ws = (workspace or "geonode").strip() if workspace is not None else None
    txt = raw.strip()
    if not txt:
        return None
    parts = [p for p in txt.split(":") if p]
    if len(parts) >= 3 and parts[0] == parts[1]:
        # ejemplo: geonode:geonode:puertos -> geonode:puertos
        parts = [parts[0], parts[-1]]
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    if ws:
        return f"{ws}:{parts[0]}"
    return parts[0]


def normalize_copernicus_cfg(cfg: dict) -> dict:
    """
    Limpia campos opcionales y elimina valores vacíos.
    """
    cleaned = {
        "url": (cfg.get("url") or "").strip(),
        "layer": (cfg.get("layer") or "").strip(),
        "style": (cfg.get("style") or "").strip(),
        "visible": bool(cfg.get("visible", False)),
    }
    for key in ("time", "params"):
        val = (cfg.get(key) or "").strip()
        cleaned[key] = val or None
    # Evitar que params empiece con ? o &
    if cleaned["params"]:
        cleaned["params"] = cleaned["params"].lstrip("?&")
    return cleaned


def build_copernicus_tile_url(cfg: dict) -> Optional[str]:
    """
    Construye la URL de teselas para Copernicus.
    - Soporta WMTS de marine.copernicus.eu (GetTile con x/y/z).
    - Si no es WMTS, cae a WMS estándar.
    """
    url = cfg.get("url") or ""
    layer = cfg.get("layer")
    if not url or not layer:
        return None

    style = cfg.get("style", "")
    time_val = cfg.get("time")
    extra = cfg.get("params")

    is_copernicus_wmts = "wmts.marine.copernicus.eu" in url or "teroWmts" in url
    if is_copernicus_wmts:
        # Algunos config guardan solo el nombre de variable; si falta el prefijo del dataset, se concatena el último segmento de la URL.
        from urllib.parse import urlparse
        parsed = urlparse(url)
        segments = [s for s in parsed.path.split("/") if s]
        dataset = segments[-1] if segments else None
        if dataset and "/" not in layer:
            layer = f"{dataset}/{layer}"
        sep = "&" if "?" in url else "?"
        parts = [
            "SERVICE=WMTS",
            "REQUEST=GetTile",
            "VERSION=1.0.0",
            f"LAYER={layer}",
            f"STYLE={style}",
            "FORMAT=image/png",
            "TILEMATRIXSET=EPSG:3857",
            "TILEMATRIX={z}",
            "TILEROW={y}",
            "TILECOL={x}",
        ]
        if time_val:
            parts.append(f"time={time_val}")
        if extra:
            parts.append(extra)
        return f"{url.rstrip('?')}{sep}{'&'.join(parts)}"

    tile_url = build_wms_tile_url(layer, style, base_url=url, time=time_val)
    if extra:
        sep = "&" if "?" in tile_url else "?"
        tile_url = f"{tile_url}{sep}{extra}"
    return tile_url


async def get_service_token() -> Optional[str]:
    if not (GEONODE_OAUTH_CLIENT_ID and GEONODE_OAUTH_CLIENT_SECRET and GEONODE_SERVICE_USERNAME and GEONODE_SERVICE_PASSWORD):
        return None
    now = time.time()
    token = service_token.get("token")
    expires = service_token.get("expires", 0)
    if token and expires - 60 > now:
        return token
    async with httpx.AsyncClient(timeout=30) as client:
        data = {
            "grant_type": "password",
            "username": GEONODE_SERVICE_USERNAME,
            "password": GEONODE_SERVICE_PASSWORD,
            "client_id": GEONODE_OAUTH_CLIENT_ID,
            "client_secret": GEONODE_OAUTH_CLIENT_SECRET,
        }
        headers = {"Host": GEONODE_HOST_HEADER} if GEONODE_HOST_HEADER else None
        resp = await client.post(GEONODE_OAUTH_TOKEN_URL, data=data, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        service_token["token"] = payload.get("access_token")
        service_token["expires"] = now + payload.get("expires_in", 3600)
        return service_token["token"]

async def get_cached_geonode_layers(refresh: bool = False) -> List[dict]:
    """
    Devuelve la lista de capas de GeoNode (API v2) y la cachea unos minutos en Redis.
    """
    cached = None
    if redis and not refresh:
        cached = await redis.get(LAYER_AVAILABLE_CACHE_KEY)
    if cached:
        try:
            data = json.loads(cached)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    token = await get_service_token()
    headers = {}
    if GEONODE_HOST_HEADER:
        headers["Host"] = GEONODE_HOST_HEADER
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Usamos la URL base interna (nginx geonode) para API v2
    url = f"{GEONODE_BASE_URL}/api/v2/datasets?page_size=500"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    layers = []
    for item in payload.get("datasets", []):
        name = item.get("alternate") or item.get("name")
        workspace = item.get("workspace") or "geonode"
        typename = normalize_typename(name, workspace)
        if not typename:
            continue
        sourcetype = item.get("sourcetype")
        remote_wms_url = None
        if sourcetype == "REMOTE":
            for ln in item.get("links", []):
                if ln.get("link_type") == "OGC:WMS" and ln.get("url"):
                    remote_wms_url = (ln["url"] or "").strip()
                    # limpiar dobles ?? y trailing ?
                    remote_wms_url = remote_wms_url.replace("??", "?").rstrip("?")
                    break
        layers.append({
            "id": item.get("id"),
            "title": item.get("title") or name,
            "name": name,
            "workspace": workspace,
            "typename": typename,
            "sourcetype": sourcetype,
            "remote_wms_url": remote_wms_url,
            "remote_layer_name": item.get("alternate") or item.get("name"),
        })
    if redis:
        await redis.set(LAYER_AVAILABLE_CACHE_KEY, json.dumps(layers), ex=LAYER_AVAILABLE_CACHE_TTL)
    return layers

async def get_selected_layer_typenames() -> List[str]:
    if not redis:
        return []
    raw = await redis.get(LAYER_SELECTION_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        cleaned = []
        seen = set()
        for t in data:
            norm = normalize_typename(t)
            if not norm:
                continue
            if norm in seen:
                continue
            seen.add(norm)
            cleaned.append(norm)
        return cleaned
    except Exception:
        return []

async def save_selected_layer_typenames(layers: List[str]) -> None:
    if redis:
        await redis.set(LAYER_SELECTION_KEY, json.dumps(layers))


async def get_copernicus_config() -> Optional[dict]:
    """
    Lee config Copernicus desde Redis; si no hay, usa variables de entorno.
    """
    cfg = None
    if redis:
        raw = await redis.get(COPERNICUS_CONFIG_KEY)
        if raw:
            try:
                cfg = json.loads(raw)
            except Exception:
                cfg = None
    if not cfg and COPERNICUS_WMS_URL and COPERNICUS_WMS_LAYER:
        cfg = {
            "url": COPERNICUS_WMS_URL,
            "layer": COPERNICUS_WMS_LAYER,
            "style": COPERNICUS_WMS_STYLE,
            "visible": False,
            "time": None,
            "params": None,
        }
    return normalize_copernicus_cfg(cfg) if cfg else None

async def save_copernicus_config(cfg: dict) -> None:
    if redis:
        await redis.set(COPERNICUS_CONFIG_KEY, json.dumps(normalize_copernicus_cfg(cfg)))


async def fetch_geojson_layer(client: httpx.AsyncClient, layer_cfg: dict) -> None:
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": layer_cfg["layer"],
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
    }
    headers = {}
    token = await get_service_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = await client.get(GEONODE_INTERNAL_WFS_URL, params=params, headers=headers)
    resp.raise_for_status()
    layer_cache[layer_cfg["id"]] = resp.json()
    layer_cache_meta[layer_cfg["id"]] = {"fetched_at": time.time()}


async def layer_cache_worker():
    if not any(l.get("type") == "geojson" for l in STATIC_LAYER_CONFIG):
        return
    await asyncio.sleep(2)
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            now = time.time()
            for layer_cfg in STATIC_LAYER_CONFIG:
                if layer_cfg.get("type") != "geojson":
                    continue
                refresh = layer_cfg.get("refresh", 3600)
                next_run = layer_cfg.get("_next_run", 0)
                if now >= next_run or layer_cfg["id"] not in layer_cache:
                    try:
                        await fetch_geojson_layer(client, layer_cfg)
                    except Exception as exc:
                        print(f"[layer-cache] error updating {layer_cfg['id']}: {exc}")
                    layer_cfg["_next_run"] = now + refresh
            await asyncio.sleep(30)


def _fetch_dms_rows() -> list[dict]:
    if not ext_engine:
        return []
    sql = text("""
        SELECT
            ndn.id                      AS dms_id,
            ndn.nave_id                 AS nave_id,
            nn.mmsi                     AS mmsi,
            nn.matricula                AS matricula,
            nn.name                     AS name,
            nn.trb                      AS trb,
            ng.name                     AS nave_grupo,
            ndn.ultima_latitud          AS lat,
            ndn.ultima_longitud         AS lon,
            ndn.ultima_velocidad        AS sog_knots,
            ndn.ultimo_rumbo            AS cog_deg,
            ndn.fecha_ultimo_qth        AS fecha_qth,
            ndn.write_date              AS write_date,
            ndn.estado_operativo        AS estado_operativo
        FROM nave_dms_nave ndn
        LEFT JOIN nave_nave nn ON nn.id = ndn.nave_id
        LEFT JOIN nave_nave_tipo nt ON nn.nave_tipo_id = nt.id
        LEFT JOIN nave_nave_grupo ng ON nt.grupo_nave_id = ng.id
        WHERE ndn.estado_operativo = 'OPE'
          AND ndn.ultima_latitud IS NOT NULL
          AND ndn.ultima_longitud IS NOT NULL
    """)
    with ext_engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql)]


def _normalize_dms_row(r: dict, now: float) -> dict:
    ts_source = r.get("fecha_qth") or r.get("write_date")
    ts = None
    if isinstance(ts_source, datetime):
        ts = ts_source.timestamp()
    elif isinstance(ts_source, str) and ts_source:
        try:
            ts = datetime.fromisoformat(ts_source.replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                ts = float(ts_source)
            except Exception:
                ts = None
    elif ts_source is not None:
        try:
            ts = float(ts_source)
        except Exception:
            ts = None

    # status_color: gray = sin telemetría reciente; verde/amarillo/rojo por edad
    age = now - ts if ts else None
    if age is None:
        status = "gray"
    elif age > 4 * 3600:
        status = "red"
    elif age > 3600:
        status = "yellow"
    else:
        status = "green"

    try:
        lat = float(r["lat"]) if r.get("lat") is not None else None
        lon = float(r["lon"]) if r.get("lon") is not None else None
    except (TypeError, ValueError):
        lat = lon = None
    
    # Normalize TRB safely
    try:
        trb = float(r.get("trb") or 0)
    except:
        trb = 0.0

    return {
        "nave_id": r.get("nave_id"),
        "mmsi": r.get("mmsi"),
        "matricula": r.get("matricula"),
        "name": r.get("name"),
        "trb": trb,
        "nave_grupo": r.get("nave_grupo"),
        "lat": lat,
        "lon": lon,
        "sog_knots": float(r["sog_knots"]) if r.get("sog_knots") is not None else None,
        "cog_deg": float(r["cog_deg"]) if r.get("cog_deg") is not None else None,
        "ts": ts,
        "estado_operativo": r.get("estado_operativo"),
        "status_color": status,
        "source": "dms_sync",
    }


async def dms_sync_worker():
    """Polling periódico a nave_dms_nave para poblar Redis y WebSocket."""
    if not ext_engine:
        return
    await asyncio.sleep(2)
    while True:
        try:
            rows = _fetch_dms_rows()
            now = time.time()
            for r in rows:
                norm = _normalize_dms_row(r, now)
                if norm["lat"] is None or norm["lon"] is None:
                    continue
                key = None
                if norm.get("mmsi"):
                    key = f"vessel:last:{norm['mmsi']}"
                elif norm.get("nave_id"):
                    key = f"vessel:last:nave:{norm['nave_id']}"
                if not key:
                    continue
                await redis.set(key, json.dumps(norm))
                await broadcast({"type": "position", "data": norm})
        except Exception as exc:
            print(f"[dms-sync] error: {exc}")
        await asyncio.sleep(DMS_SYNC_INTERVAL)

@app.on_event("startup")
async def startup():
    global redis, engine
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    app.state.layer_task = asyncio.create_task(layer_cache_worker())
    app.state.dms_task = asyncio.create_task(dms_sync_worker())

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)

@app.post("/ingest")
async def ingest(t: Telemetry):
    # 1. Fetch existing data to get traffic_type and other static info
    # Use consistent key: vessel:last:{mmsi}
    key = f"vessel:last:{t.mmsi}"
    existing_data_str = await redis.get(key)
    existing_data = json.loads(existing_data_str) if existing_data_str else {}
    
    # 2. Perform Spatial Checks
    traffic_type = existing_data.get("tipo_trafico")
    spatial_status = check_spatial_status(t.lat, t.lon, t.mmsi, traffic_type)
    
    # 3. Update Status Color
    status_color = "green"
    if t.panic:
        status_color = "red"
    elif spatial_status["alert"]:
        status_color = spatial_status["color"] # orange
        
    # Merge new data with existing
    new_data = t.model_dump()
    new_data["status_color"] = status_color
    new_data["spatial_alert"] = spatial_status["reason"]
    
    final_data = {**existing_data, **{k: v for k, v in new_data.items() if v is not None}}
    final_data["status_color"] = status_color
    final_data["spatial_alert"] = spatial_status["reason"]
    
    print(f"DEBUG: spatial_status: {spatial_status}")
    print(f"DEBUG: final_data: {final_data}")

    await redis.set(key, json.dumps(final_data))

    # Store historical position in Postgres
    # We use raw SQL to match existing style (or use SQLAlchemy if preferred, but raw is faster/simpler here)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO vessels (mmsi, matricula)
            VALUES (:mmsi, :matricula)
            ON CONFLICT (mmsi) DO UPDATE SET matricula = COALESCE(EXCLUDED.matricula, vessels.matricula);
        """), dict(mmsi=t.mmsi, matricula=t.matricula))
        
        conn.execute(text("""
            INSERT INTO positions (mmsi, ts, geom, sog_knots, cog_deg, heading_deg, source, extra)
            VALUES (:mmsi, to_timestamp(:ts), ST_SetSRID(ST_MakePoint(:lon, :lat),4326)::geography,
                    :sog, :cog, :hdg, :src, CAST(:extra AS JSONB))
            ON CONFLICT DO NOTHING;
        """), dict(
            mmsi=t.mmsi,
            ts=t.ts,
            lon=t.lon,
            lat=t.lat,
            sog=t.sog_knots,
            cog=t.cog_deg,
            hdg=t.heading_deg,
            src=t.source,
            extra=json.dumps({"panic": t.panic, "spatial_alert": spatial_status["reason"]} if (t.panic or spatial_status["alert"]) else None)
        ))

    await broadcast({"type":"position","data":final_data})
    if t.panic:
        await create_alert(t.model_dump(), "PANIC", "CRIT")
    elif spatial_status["alert"]:
        # Optional: Log spatial alert?
        pass
        
    return {"status":"ok"}

async def create_alert(p: dict, type_: str, severity: str = "WARN"):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO alerts (mmsi, ts, type, severity, geom, details)
            VALUES (:mmsi, to_timestamp(:ts), :type, :severity,
                    ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,
                    CAST(:details AS JSONB))
        """), dict(
            mmsi=p["mmsi"],
            ts=p["ts"],
            type=type_,
            severity=severity,
            lon=p["lon"],
            lat=p["lat"],
            details=json.dumps({"source": p.get("source")})
        ))
    await broadcast({"type":"alert","data":{"mmsi":p["mmsi"],"type":type_,"severity":severity,"ts":p["ts"]}})

async def broadcast(message: dict):
    dead = []
    textmsg = json.dumps(message)
    for ws in list(subscribers):
        try:
            await ws.send_text(textmsg)
        except:
            dead.append(ws)
    for ws in dead:
        subscribers.discard(ws)


@app.get("/api/v1/static-layers/config")
async def get_static_layer_config():
    def entry_from_cfg(cfg: dict) -> dict:
        # Validaciones mínimas
        if cfg["type"] == "wms" and not cfg.get("layer"):
            return None
        entry = {
            "id": cfg["id"],
            "title": cfg["title"],
            "type": cfg["type"],
            "visible": cfg.get("visible", True),
        }
        if cfg.get("cache_strategy"):
            entry["cache_strategy"] = cfg["cache_strategy"]
        if cfg.get("min_zoom") is not None:
            entry["min_zoom"] = cfg["min_zoom"]
        if cfg.get("max_zoom") is not None:
            entry["max_zoom"] = cfg["max_zoom"]
        if cfg["type"] == "wms":
            entry["tile_url"] = build_wms_tile_url(cfg["layer"], cfg.get("style", ""), base_url=cfg.get("custom_wms_url"))
            if not entry["tile_url"]:
                return None
            entry["layer"] = cfg["layer"]
        elif cfg["type"] == "geojson":
            entry["data_url"] = f"/api/v1/static-layers/{cfg['id']}"
            entry["refresh"] = cfg.get("refresh", 3600)
        return entry

    layers = [entry for cfg in STATIC_LAYER_CONFIG if (entry := entry_from_cfg(cfg))]

    # Capas extra seleccionadas desde GeoNode
    selected = await get_selected_layer_typenames()
    if selected:
        available = await get_cached_geonode_layers()
        by_typename = {l["typename"]: l for l in available}
        for typename in selected:
            info = by_typename.get(typename)
            if not info:
                # intenta normalizar duplicados tipo geonode:geonode:xxx
                norm = normalize_typename(typename)
                info = by_typename.get(norm) if norm else None
                if not info:
                    continue
            # para capas remotas, usar la URL original y el nombre sin workspace
            custom_wms_url = info.get("remote_wms_url")
            layer_name = info.get("remote_layer_name") if custom_wms_url else info["typename"]
            layers.append({
                "id": typename.replace(":", "_"),
                "title": info["title"],
                "type": "wms",
                "visible": True,
                "cache_strategy": "live",
                "tile_url": build_wms_tile_url(layer_name, base_url=custom_wms_url),
                "layer": layer_name,
                "min_zoom": 0,
                "max_zoom": 22,
            })

    # Añadir capa Copernicus si hay config
    cop_cfg = await get_copernicus_config()
    if cop_cfg and cop_cfg.get("url") and cop_cfg.get("layer"):
        cop_cfg = normalize_copernicus_cfg(cop_cfg)
        tile_url = build_copernicus_tile_url(cop_cfg)
        if tile_url:
            layers.append({
                "id": "copernicus_wms",
                "title": "Copernicus Pronóstico Viento/Olas (diario)",
                "type": "wms",
                "visible": bool(cop_cfg.get("visible", False)),
                "cache_strategy": "live",
                "tile_url": tile_url,
                "layer": cop_cfg["layer"],
                "min_zoom": 0,
                "max_zoom": 22,
            })

    return {"layers": layers, "geonode_base": GEONODE_PUBLIC_BASE_URL}

@app.get("/api/v1/layers/available")
async def list_available_layers(refresh: bool = False):
    """
    Devuelve las capas publicadas en GeoNode y la selección actual (Redis).
    """
    available = await get_cached_geonode_layers(refresh=refresh)
    selected = await get_selected_layer_typenames()
    return {"available": available, "selected": selected}

@app.get("/api/v1/analysis/history")
async def get_analysis_history(ids: str = Query(...), start: float = Query(...), end: float = Query(...)):
    if not ext_engine:
        return {"type": "FeatureCollection", "features": []}
    
    nave_ids = [n.strip() for n in ids.split(",") if n.strip()]
    if not nave_ids:
        return {"type": "FeatureCollection", "features": []}

    # Convert timestamps to datetime strings if needed by DB, or keep as float if DB accepts to_timestamp
    # The provided query snippet implies existing tables. Let's adapt the user's query.
    # USER QUERY:
    # SELECT ... FROM nave_dms_qth ndqth ... 
    # WHERE ndqth.fecha_qth BETWEEN ... AND ...
    # AND ndn.nave_id IN (...)
    
    # We'll fetch rows and build GeoJSON in Python.
    
    sql = text("""
        SELECT 
            nn.id AS x_nave_id,
            nn.name AS x_nombre_nave,
            ndqth.latitud AS x_latitud,
            ndqth.longitud AS x_longitud,
            ndqth.fecha_qth AS x_fecha_qth
        FROM nave_dms_qth ndqth
        LEFT JOIN nave_dms_nave ndn ON ndn.id = ndqth.dms_nave_id
        LEFT JOIN nave_nave nn ON ndn.nave_id = nn.id
        WHERE nn.id IN :nids
          AND ndqth.fecha_qth >= to_timestamp(:start)
          AND ndqth.fecha_qth <= to_timestamp(:end)
        ORDER BY ndqth.fecha_qth ASC
    """)
    
    try:
        with ext_engine.connect() as conn:
            # SQLAlchemy text needs tuple for IN clause usually, or expanded list. 
            # Passing list directly usually works in modern SQLAlchemy with text().
            rows = conn.execute(sql, {"nids": tuple(nave_ids), "start": start, "end": end}).fetchall()
    except Exception as e:
        print(f"Error querying analysis history: {e}")
        return {"type": "FeatureCollection", "features": []}

    # Group by vessel
    tracks = {}
    for r in rows:
        # r is a Row object/tuple. Access by index or name
        # x_nave_id, x_nombre_nave, x_latitud, x_longitud, x_fecha_qth
        nid = str(r[0]) # x_nave_id
        name = r[1]
        lat = r[2]
        lon = r[3]
        ts = r[4]  # fecha_qth timestamp
        
        if nid not in tracks:
            tracks[nid] = {"name": name, "coords": [], "points": []}
        
        if lat is not None and lon is not None:
             tracks[nid]["coords"].append([float(lon), float(lat)])
             tracks[nid]["points"].append({
                 "lon": float(lon),
                 "lat": float(lat),
                 "ts": str(ts) if ts else None
             })

    features = []
    # Palette for up to 4 vessels
    colors = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b"]
    idx = 0
    
    for nid, data in tracks.items():
        if not data["coords"]:
            continue
        
        color = colors[idx % len(colors)]
        idx += 1
        
        # Add LineString for the track
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": data["coords"]
            },
            "properties": {
                "nave_id": nid,
                "name": data["name"],
                "color": color,
                "feature_type": "track_line"
            }
        })
        
        # Add Point features for interactive tooltips
        for point in data["points"]:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [point["lon"], point["lat"]]
                },
                "properties": {
                    "nave_id": nid,
                    "name": data["name"],
                    "color": color,
                    "timestamp": point["ts"],
                    "feature_type": "track_point"
                }
            })

    return {"type": "FeatureCollection", "features": features}

@app.post("/api/v1/layers/selection")
async def set_layer_selection(payload: LayerSelectionPayload):
    """
    Guarda los typenames de las capas que deben aparecer en 'capas disponibles'.
    """
    cleaned = []
    seen = set()
    for t in payload.layers:
        norm = normalize_typename(t)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(norm)
    await save_selected_layer_typenames(cleaned)
    return {"selected": cleaned}

@app.get("/api/v1/layers/copernicus-config")
async def get_copernicus_cfg():
    cfg = await get_copernicus_config()
    return cfg or {}


@app.get("/proxy/wms")
async def proxy_wms(url: str = Query(...)):
    """
    Proxy simple for WMS/WMTS GetMap/GetTile requests to avoid CORS issues.
    - `url` must be a full URL (including query string).
    - Only allowed hostnames (env `WMS_PROXY_ALLOW`, comma-separated) are permitted.

    NOTE: This is a minimal proxy. Do not expose to the open internet without
    further access controls. The response content-type from the remote server
    is preserved.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    allow_env = os.getenv("WMS_PROXY_ALLOW", "thredds.ucar.edu,wmts.marine.copernicus.eu")
    allowed = [h.strip().lower() for h in allow_env.split(",") if h.strip()]
    if not any(h in hostname for h in allowed):
        raise HTTPException(status_code=403, detail=f"Host not allowed: {hostname}")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    content_type = resp.headers.get("content-type", "application/octet-stream")
    # Return raw content, preserve media type. CORS middleware will add headers.
    return Response(content=resp.content, media_type=content_type)

@app.post("/api/v1/layers/copernicus-config")
async def set_copernicus_cfg(payload: CopernicusConfigPayload):
    cfg = normalize_copernicus_cfg(payload.model_dump())
    await save_copernicus_config(cfg)
    return {"saved": True, "config": cfg}

@app.get("/layer-admin", response_class=HTMLResponse)
async def layer_admin_page():
    return FileResponse(os.path.join(static_dir, "layer-admin.html"))


@app.get("/api/v1/static-layers/{layer_id}")
async def get_static_layer(layer_id: str, refresh: bool = False):
    cfg = next((c for c in STATIC_LAYER_CONFIG if c["id"] == layer_id and c.get("type") == "geojson"), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="Capa no disponible como GeoJSON")
    if refresh or layer_id not in layer_cache:
        async with httpx.AsyncClient(timeout=60) as client:
            await fetch_geojson_layer(client, cfg)
    data = layer_cache.get(layer_id)
    if not data:
        raise HTTPException(status_code=503, detail="Cache no disponible")
    return data


@app.websocket("/ws")
async def ws_positions(ws: WebSocket):
    await ws.accept()
    subscribers.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        subscribers.discard(ws)

@app.get("/api/v1/vessels/last")
async def get_last_positions():
    keys = await redis.keys("vessel:last:*")
    vals = await redis.mget(keys) if keys else []
    data = [json.loads(v) for v in vals if v]
    now = time.time()
    
    # Obtener MMSIs con alertas críticas recientes
    alert_mmsis = set()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT mmsi FROM alerts
            WHERE severity = 'CRIT' AND ts >= NOW() - INTERVAL '24 hours'
        """)).fetchall()
        alert_mmsis = {row[0] for row in rows}

    for d in data:
        ts_val = d.get("ts")
        has_critical_alert = d.get("mmsi") in alert_mmsis

        if d.get("panic"):
            d["status_color"] = "blink-red"
        elif has_critical_alert:
            d["status_color"] = "blink-red"
        elif ts_val is None:
            d["status_color"] = "gray"
        else:
            age = now - ts_val
            if age > 4*3600:
                d["status_color"] = "red"
            elif age > 3600:
                d["status_color"] = "yellow"
            else:
                d["status_color"] = "green"
    return {"data": data}


@app.get("/api/v1/vessels/dms-last")
async def get_dms_last():
    """Últimas posiciones desde nave_dms_nave; lee cache Redis si está poblada."""
    # Preferimos Redis con source=dms_sync
    if redis:
        try:
            keys = await redis.keys("vessel:last:*")
        except Exception:
            keys = []
        if keys:
            vals = await redis.mget(keys)
            data = []
            for v in vals:
                if not v:
                    continue
                try:
                    d = json.loads(v)
                except Exception:
                    continue
                if d.get("source") == "dms_sync":
                    data.append(d)
            if data:
                return {"data": data}

    # Fallback directo a DB
    rows = _fetch_dms_rows()
    now = time.time()
    data = []
    for r in rows:
        norm = _normalize_dms_row(r, now)
        if norm.get("lat") is None or norm.get("lon") is None:
            continue
        data.append(norm)
    return {"data": data}

@app.get("/api/v1/vessels/{mmsi}/track")
async def get_track(mmsi: int, hours: int = 6):
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT EXTRACT(EPOCH FROM ts) as ts, ST_X(geom::geometry) as lon, ST_Y(geom::geometry) as lat,
                   sog_knots, cog_deg
            FROM positions
            WHERE mmsi = :mmsi AND ts >= NOW() - (:hours || ' hours')::interval
            ORDER BY ts ASC
        """), dict(mmsi=mmsi, hours=hours)).mappings().all()
    return {"mmsi": mmsi, "points": list(rows)}

@app.on_event("shutdown")
async def shutdown():
    await redis.close()
    if engine: engine.dispose()
    if ext_engine: ext_engine.dispose()
    task = getattr(app.state, "layer_task", None)
    if task:
        task.cancel()
    dms_task = getattr(app.state, "dms_task", None)
    if dms_task:
        dms_task.cancel()

@app.get("/api/v1/alerts/active")
async def get_active_alerts():
    """
    Fetch active alerts from incidencia_evento table in external database.
    """
    if not ext_engine:
        return {"alerts": []}
    
    sql = text("""
        SELECT
            e.description,
            e.create_date,
            e.reparto_id,
            r.name as reparto
        FROM incidencia_evento e
        JOIN sigmap_reparto r ON r.id = e.reparto_id
        ORDER BY e.create_date DESC
    """)

    
    try:
        with ext_engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()
            print(rows)
            alerts = [dict(row) for row in rows]
            return {"alerts": alerts}
    except Exception as e:
        print(f"Error fetching alerts: {e}")
        return {"alerts": [], "error": str(e)}

def row_to_dict(row):
    return dict(row._mapping) if row is not None else None

def table_exists(conn, table_name: str) -> bool:
    q = text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :t
        LIMIT 1
    """)
    return conn.execute(q, {"t": table_name}).scalar() is not None

def cols(conn, table_name: str) -> set[str]:
    q = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t
    """)
    return {r[0] for r in conn.execute(q, {"t": table_name})}

def _parse_mmsi(mmsi: str) -> Optional[int]:
    try:
        return int(mmsi)
    except (TypeError, ValueError):
        return None


def _mmsi_from_nave_id(nave_id: int) -> str:
    if not ext_engine:
        raise HTTPException(status_code=503, detail="Base externa no configurada")
    row = ext_engine.connect().execute(
        text("SELECT mmsi FROM nave_nave WHERE id = :nid"),
        {"nid": nave_id},
    ).fetchone()
    if not row or row.mmsi in (None, ""):
        raise HTTPException(status_code=404, detail=f"Nave con id {nave_id} no encontrada")
    return str(row.mmsi)

def _local_vessel_row(mmsi: str) -> Optional[dict]:
    mm = _parse_mmsi(mmsi)
    if mm is None or engine is None:
        return None
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT mmsi, matricula, name, imo, type, flag, dms_enabled
            FROM vessels
            WHERE mmsi = :m
            LIMIT 1
        """), {"m": mm}).mappings().first()
    return dict(row) if row else None

def _local_alerts(mmsi: str) -> list[dict]:
    mm = _parse_mmsi(mmsi)
    if mm is None or engine is None:
        return []
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, type, severity, details, EXTRACT(EPOCH FROM ts) AS ts
            FROM alerts
            WHERE mmsi = :m
            ORDER BY ts DESC
            LIMIT 10
        """), {"m": mm}).mappings().all()
    return [dict(r) for r in rows]

def _fallback_basic(mmsi: str) -> dict:
    local = _local_vessel_row(mmsi)
    if not local:
        raise HTTPException(status_code=503, detail="Catálogo externo no disponible")
    return {
        "data": {
            "nave_id": None,
            "nombre": local.get("name"),
            "matricula": local.get("matricula"),
            "omi": local.get("imo"),
            "mmsi": str(local.get("mmsi")) if local.get("mmsi") is not None else mmsi,
            "tipo_nave": local.get("type"),
            "estado_operativo": None,
            "tipo_trafico": None,
            "lugar_construccion": None,
            "bandera": local.get("flag"),
            "en_lista": False,
            "dms_habilitado": bool(local.get("dms_enabled")),
            "reparto": None,
            "puerto": None,
            "caleta": None,
        }
    }

def _fallback_features(mmsi: str) -> dict:
    local = _local_vessel_row(mmsi)
    if not local:
        return {"data": {}}
    return {
        "data": {
            "mmsi": str(local.get("mmsi")) if local.get("mmsi") is not None else mmsi,
            "senial_llamada": local.get("matricula"),
            "tipo_propulsion": None,
            "uso": None,
            "dms_habilitado": bool(local.get("dms_enabled")),
            "trb": None,
            "trn": None,
            "eslora": None,
            "manga": None,
            "puntal": None,
            "cap_pasajeros": None,
            "cap_tripulantes": None,
            "cap_carga": None,
        }
    }

@app.get("/api/v1/catalog/vessel/{mmsi}")
def get_catalog_vessel(mmsi: str):
    """
    Trae la ficha de la nave desde la BD externa (Odoo).
    - Busca por nave_nave.mmsi (VARCHAR).
    - Devuelve campos clave y hasta 10 alertas recientes si existe tabla nave_alerta.
    """
    if not ext_engine:
        local = _fallback_basic(mmsi)
        return {"data": local["data"], "alerts": _local_alerts(mmsi)}

    sql_vessel = text("""
        SELECT
            n.id,
            n.mmsi,
            n.matricula,
            n.name                              AS nombre,
            n.omi_number                        AS omi,
            n.senial_llamada                    AS senial_llamada,
            n.tipo                              AS tipo_embarcacion,
            n.uso                               AS uso,
            n.lista_autorizada                  AS lista_autorizada,
            n.dms                               AS dms_habilitado,
            n.bandera_pais_id                   AS bandera_pais_id,
            n.trb, n.trn,
            n.eslora, n.manga, n.puntal,
            n.fecha_registro,
            n.estado_navegacion
        FROM public.nave_nave n
        WHERE n.mmsi = :mmsi
        LIMIT 1
    """)

    try:
        with ext_engine.connect() as conn:
            vessel = conn.execute(sql_vessel, {"mmsi": mmsi}).fetchone()
            if not vessel:
                raise HTTPException(status_code=404, detail=f"Nave con MMSI {mmsi} no encontrada en catálogo")

            data = row_to_dict(vessel)

            alerts = []
            try:
                sql_alerts = text("""
                    SELECT
                        a.id,
                        a.tipo        AS type,
                        a.severidad   AS severity,
                        a.estado      AS status,
                        a.create_date AS ts,
                        a.descripcion AS description
                    FROM public.nave_alerta a
                    WHERE a.nave_id = :nave_id
                    ORDER BY a.create_date DESC
                    LIMIT 10
                """)
                alerts = [row_to_dict(r) for r in conn.execute(sql_alerts, {"nave_id": data["id"]}).fetchall()]
            except Exception:
                alerts = []
    except OperationalError as exc:
        print(f"[catalog] externo no disponible ({mmsi}): {exc}")
        local = _fallback_basic(mmsi)
        return {"data": local["data"], "alerts": _local_alerts(mmsi)}

    return {"data": data, "alerts": alerts}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}")
def get_catalog_vessel_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_vessel(mmsi)

def _row(r): 
    return dict(r._mapping) if r is not None else None

@app.get("/api/v1/catalog/vessel/{mmsi}/basic")
def get_catalog_vessel_basic(mmsi: str):
    """
    Ficha básica de la nave (para el panel del visor).
    Busca por nave_nave.mmsi (VARCHAR) en la BD externa (Odoo).
    """
    if not ext_engine:
        return _fallback_basic(mmsi)

    # id de 'construcción' si se maneja por código 'cons' (según documento)
    sql_constr_id = text("""
        SELECT id FROM sigmap_tipo_construccion WHERE codigo = 'cons' LIMIT 1
    """)

    # Consulta principal (info básica). Usa LEFT JOIN y COALESCE para valores legibles.
    sql_basic = text("""
        WITH constr AS (
            SELECT nc.nave_id, nc.lugar
            FROM nave_nave_construccion nc
            WHERE nc.active IS TRUE
        ),
        constr_pref AS (
            SELECT c.nave_id, c.lugar
            FROM constr c
            JOIN sigmap_tipo_construccion t ON t.id = c.nave_id -- (ajuste si FK real es otra)
            WHERE t.codigo = 'cons'
        )
        SELECT
            n.id                               AS nave_id,
            n.name                             AS nombre,
            n.matricula                        AS matricula,
            n.omi_number                       AS omi,
            n.mmsi                             AS mmsi,
            nt.name                            AS tipo_nave,
            ne.name                            AS estado_operativo,
            tt.name                            AS tipo_trafico,
            /* lugar de construcción preferido si existe */
            COALESCE(cp.lugar, NULL)           AS lugar_construccion,
            rc.name                            AS bandera,
            n.cumple_lista_autorizada          AS en_lista,
            /* DMS habilitado (de tu tabla nave_nave: campo 'dms' o booleano) */
            CASE
              WHEN lower(coalesce(n.dms,'')) IN ('1','si','sí','true','t') THEN TRUE
              ELSE FALSE
            END                                AS dms_habilitado,
            sr.name                            AS reparto,
            sp.name                            AS puerto,
            scn.name                           AS caleta
        FROM nave_nave n
        /* Estado operativo */
        LEFT JOIN nave_datos_estado de      ON n.datos_estado_id = de.id AND (de.active IS TRUE OR de.active IS NULL)
        LEFT JOIN nave_nave_estado ne       ON de.nave_estado_id = ne.id
        /* Tipo nave y tráfico */
        LEFT JOIN nave_nave_tipo nt         ON n.nave_tipo_id = nt.id
        LEFT JOIN tipo_trafico tt           ON n.tipo_trafico_id = tt.id
        /* Registro / Bandera / Reparto / Puerto */
        LEFT JOIN nave_datos_registro_puerto drp ON n.datos_registro_id = drp.id AND (drp.active IS TRUE OR drp.active IS NULL)
        LEFT JOIN res_country rc            ON drp.bandera_pais_id = rc.id
        LEFT JOIN sigmap_reparto sr         ON drp.reparto_id = sr.id
        LEFT JOIN sigmap_puerto  sp         ON drp.puerto_id  = sp.id
        /* Caleta */
        LEFT JOIN sigmap_caleta scn         ON n.caleta_id = scn.id
        /* Construcción */
        LEFT JOIN constr_pref cp            ON cp.nave_id = n.id
        WHERE n.active IS TRUE AND n.mmsi = :mmsi
        LIMIT 1
    """)

    try:
        with ext_engine.connect() as conn:
            # First, check if nave_nave exists at all.
            q_check = text("SELECT 1 FROM information_schema.tables WHERE table_name = 'nave_nave' LIMIT 1")
            if not conn.execute(q_check).scalar():
                 return _fallback_basic(mmsi)

            # Complex query with joins that might fail if modules are missing
            try:
                row = conn.execute(sql_basic, {"mmsi": mmsi}).fetchone()
            except Exception as e:
                print(f"[catalog-basic] fallo join complejo, intentando query simple: {e}")
                # Fallback to simple query on nave_nave only
                sql_simple = text("""
                    SELECT 
                        n.id as nave_id, n.name as nombre, n.matricula, n.mmsi, n.omi_number as omi,
                        NULL as tipo_nave, NULL as estado_operativo, NULL as tipo_trafico,
                        NULL as lugar_construccion, NULL as bandera, 
                        n.cumple_lista_autorizada as en_lista,
                        FALSE as dms_habilitado, NULL as reparto, NULL as puerto, NULL as caleta
                    FROM nave_nave n
                    WHERE n.active IS TRUE AND n.mmsi = :mmsi
                    LIMIT 1
                """)
                row = conn.execute(sql_simple, {"mmsi": mmsi}).fetchone()

            if not row:
                raise HTTPException(status_code=404, detail=f"Nave MMSI {mmsi} no encontrada")
            data = _row(row)

        # Normalización booleana y strings
        data["en_lista"] = bool(data.get("en_lista"))
        data["dms_habilitado"] = bool(data.get("dms_habilitado"))
        # Algunos catálogos devuelven rc.name como objeto JSON (traducciones); lo aplanamos a texto.
        bandera = data.get("bandera")
        if isinstance(bandera, dict):
            data["bandera"] = (
                bandera.get("name")
                or bandera.get("nombre")
                or bandera.get("es")
                or bandera.get("es_EC")
                or next(iter(bandera.values()), None)
            )

        return {"data": data}
    except Exception as exc:
        print(f"[catalog-basic] Error resiliente ({mmsi}): {exc}")
        return _fallback_basic(mmsi)


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/basic")
def get_catalog_vessel_basic_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_vessel_basic(mmsi)


def si_no(val):
    if val is None:
        return "-"
    return "Sí" if (str(val).lower() in ("1", "true", "t", "si", "sí", "y")) else "No"

def num_or_dash(v):
    return None if v is None else float(v)

from fastapi import Path

@app.get("/api/v1/catalog/vessel/{mmsi}/features")
def get_catalog_vessel_features(mmsi: str = Path(..., description="MMSI como string")):
    """
    Características técnicas de la nave (sin fotos).
    - Une nave_nave con tablas técnicas según tu documento.
    - Busca nave por mmsi (VARCHAR).
    """
    if not ext_engine:
        return _fallback_features(mmsi)

    sql_find = text("""
        SELECT n.id
        FROM public.nave_nave n
        WHERE n.mmsi = :mmsi
        LIMIT 1
    """)
    sql = text("""
        SELECT
            n.trb                              AS trb,
            n.trn                              AS trn,
            ntp.name                           AS tipo_propulsion,
            n.uso                              AS uso,
            dcmb.autonomia_dias               AS autonomia_dias,
            ns.name                            AS servicio,
            ssa.name                           AS servicio_autorizado,
            dt.desplazamiento                  AS desplaz_lastre,
            ds.capacidad_pasajeros             AS cap_pasajeros,
            da.capacidad_carga                 AS cap_carga,
            n.eslora                           AS eslora,
            n.manga                            AS manga,
            n.puntal                           AS puntal,
            dt.calado_aereo                    AS calado_aereo,
            dt.calado_aereo_definitivo         AS calado_aereo_definitivo,
            n.senial_llamada                   AS senial_llamada,
            n.mmsi                             AS mmsi,
            dt.peso_muerto                     AS peso_muerto,
            ds.capacidad_tripulantes           AS cap_tripulantes,
            da.capacidad_bodegas               AS cap_bodegas
        FROM public.nave_nave n
        LEFT JOIN public.nave_tipo_propulsion        ntp  ON n.nave_tipo_propulsion_id = ntp.id
        LEFT JOIN public.nave_nave_servicio          ns   ON n.nave_servicio_id        = ns.id
        LEFT JOIN public.nave_datos_combustible      dcmb ON n.datos_combustible_id    = dcmb.id AND dcmb.active = TRUE
        LEFT JOIN public.nave_datos_clasificacion    dcls ON n.datos_clasificacion_id  = dcls.id AND dcls.active = TRUE
        LEFT JOIN public.sigmap_servicio_autorizado  ssa  ON dcls.servicio_autorizado_id = ssa.id
        LEFT JOIN public.nave_datos_tecnicos         dt   ON n.datos_tecnicos_id       = dt.id AND dt.active = TRUE
        LEFT JOIN public.nave_datos_seguridad        ds   ON n.datos_seguridad_id      = ds.id AND ds.active = TRUE
        LEFT JOIN public.nave_datos_arqueo           da   ON n.datos_arqueo_id         = da.id AND da.active = TRUE
        WHERE n.id = :nid
        LIMIT 1
    """)

    try:
        with ext_engine.connect() as conn:
            # Basic existence check
            row_id = conn.execute(sql_find, {"mmsi": mmsi}).fetchone()
            if not row_id:
                raise HTTPException(status_code=404, detail=f"Nave con MMSI {mmsi} no encontrada")
            nid = row_id[0]
            
            try:
                r = conn.execute(sql, {"nid": nid}).mappings().first()
            except Exception as e:
                print(f"[catalog-features] fallo join complejo, intentando query simple: {e}")
                sql_simple = text("""
                    SELECT 
                        n.trb, n.trn, NULL as tipo_propulsion, n.uso, NULL as autonomia_dias,
                        NULL as servicio, NULL as servicio_autorizado, NULL as desplaz_lastre,
                        NULL as cap_pasajeros, NULL as cap_carga, n.eslora, n.manga, n.puntal,
                        NULL as calado_aereo, NULL as calado_aereo_definitivo, n.senial_llamada,
                        n.mmsi, NULL as peso_muerto, NULL as cap_tripulantes, NULL as cap_bodegas
                    FROM nave_nave n
                    WHERE n.id = :nid
                """)
                r = conn.execute(sql_simple, {"nid": nid}).mappings().first()

        if not r:
            return {"data": {}}

        data = dict(r)
        # Normalización básica (números o "-")
        for k in ("trb","trn","eslora","manga","puntal","autonomia_dias",
                  "desplaz_lastre","cap_pasajeros","cap_carga","calado_aereo",
                  "calado_aereo_definitivo","peso_muerto","cap_tripulantes","cap_bodegas"):
            v = data.get(k)
            try:
                data[k] = None if v in (None, "") else float(v)
            except:
                data[k] = None

        data["dms_habilitado"] = bool(data.get("dms_habilitado"))
        return {"data": data}
    except Exception as exc:
        print(f"[catalog-features] Error resiliente ({mmsi}): {exc}")
        return _fallback_features(mmsi)


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/features")
def get_catalog_vessel_features_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_vessel_features(mmsi)


@app.get("/api/v1/catalog/vessel/{mmsi}/areas")
def get_catalog_areas(mmsi: str):
    sql = text("""
      SELECT nan.name AS area_navegacion, nan.descripcion
      FROM nave_nave n
      LEFT JOIN nave_datos_clasificacion dcls ON n.datos_clasificacion_id=dcls.id AND dcls.active=True
      LEFT JOIN nave_clasif_area_rel dcar ON dcls.id=dcar.nave_clasificacion_id
      LEFT JOIN nave_nave_area_nav nan ON dcar.area_id=nan.id
      WHERE n.active=True AND n.mmsi=:mmsi
    """)
    rows = [dict(r._mapping) for r in ext_engine.connect().execute(sql, {"mmsi": mmsi})]
    return {"data": rows}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/areas")
def get_catalog_areas_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_areas(mmsi)


@app.get("/api/v1/catalog/vessel/{mmsi}/certs")
def get_catalog_certs(mmsi: str):
    """
    Certificados emitidos para la nave, según tabla real `nave_documento_certificado`.
    Filtramos por `nave_mmsi` cuando existe; si no, caemos a join por `nave_id`.
    Campos útiles detectados en tu esquema:
      - numero, state, fecha_emision, fecha_caducidad, titulo/name, tipo_certificado, tipo_certificado_name(jsonb)
    """
    if not ext_engine:
        raise HTTPException(status_code=500, detail="Catálogo externo no configurado")

    with ext_engine.connect() as conn:
        if not table_exists(conn, "nave_documento_certificado"):
            return {"data": []}

        cset = cols(conn, "nave_documento_certificado")
        # columnas presentes (según tu dump)
        f_num   = "numero"               if "numero"               in cset else None
        f_state = "state"                if "state"                in cset else None
        f_emis  = "fecha_emision"        if "fecha_emision"        in cset else None
        f_vence = "fecha_caducidad"      if "fecha_caducidad"      in cset else None
        f_tit   = "titulo"               if "titulo"               in cset else ("name" if "name" in cset else None)
        f_tipo  = "tipo_certificado"     if "tipo_certificado"     in cset else None
        f_tipoj = "tipo_certificado_name"if "tipo_certificado_name"in cset else None
        f_active= "active"               if "active"               in cset else None

        # FK / vínculo a la nave:
        f_mmsi  = "nave_mmsi"            if "nave_mmsi"            in cset else None
        f_nave  = "nave_id"              if "nave_id"              in cset else None

        # Construimos el "nombre del certificado"
        # 1) si existe jsonb, priorizamos español -> inglés -> tipo plano -> título
        nombre_expr = None
        if f_tipoj:
            nombre_expr = f"COALESCE({f_tipoj}->>'es_EC', {f_tipoj}->>'es_ES', {f_tipoj}->>'en_US')"
        if not nombre_expr and f_tipo:
            nombre_expr = f"{f_tipo}"
        if not nombre_expr and f_tit:
            nombre_expr = f"{f_tit}"
        if not nombre_expr:
            nombre_expr = "CAST(id AS text)"  # fallback

        # SELECT dinámico
        sel = [f"{nombre_expr} AS nombre"]
        if f_num:   sel.append(f"{f_num} AS numero")
        if f_state: sel.append(f"{f_state} AS estado")
        if f_emis:  sel.append(f"{f_emis} AS fecha_emision")
        if f_vence: sel.append(f"{f_vence} AS fecha_vencimiento")

        # WHERE + ORDER
        where = []
        params = {"mmsi": mmsi}
        if f_mmsi:
            where.append(f"{f_mmsi} = :mmsi")
        elif f_nave:
            # si no hay `nave_mmsi`, nos apoyamos en join con nave_nave
            where.append("n.mmsi = :mmsi")
        else:
            # no hay forma fiable de filtrar por nave -> vacío
            return {"data": []}

        order = f_vence or f_emis or "id"

        if f_mmsi:
            sql = text(f"""
                SELECT {', '.join(sel)}
                FROM nave_documento_certificado c
                WHERE {" AND ".join(where)}
                {"AND c.active IS TRUE" if f_active else ""}
                ORDER BY {order} NULLS LAST
            """)
        else:
            sql = text(f"""
                SELECT {', '.join(sel)}
                FROM nave_documento_certificado c
                JOIN nave_nave n ON n.id = c.{f_nave}
                WHERE {" AND ".join(where)}
                {"AND c.active IS TRUE" if f_active else ""}
                ORDER BY {order} NULLS LAST
            """)

        rows = [dict(r._mapping) for r in conn.execute(sql, params)]
        return {"data": rows}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/certs")
async def get_catalog_certs_by_id(nave_id: int):
    """
    Retrieve certificates for a vessel.
    Prioritizes Odoo RPC (Authorized Documents) as requested by USER.
    Falls back to existing SQL logic if RPC fails or returns no data.
    """
    t_start = time.time()
    odoo = _get_odoo_client()
    if odoo:
        try:
            NaveModel = odoo.env['nave.nave']
            vessel = NaveModel.browse(nave_id)
            
            # Access documento_ids relation (Authorized Documents)
            # Also fetch "Authorized List" compliance fields from the vessel itself
            v_data = vessel.read(['cumple_lista_autorizada', 'lista_autorizada_id'])[0]
            
            doc_ids = vessel.documento_ids.ids
            if doc_ids:
                AuthDocModel = odoo.env['nave.nave.autorizada.documento']
                fields = ['servicio_id', 'documento_ref', 'fecha_inicio', 'fecha_endoso_caducidad']
                docs_data = AuthDocModel.read(doc_ids, fields)
                
                # Group references to dereference them in bulk
                model_to_ids = {}
                for d in docs_data:
                    ref = d.get('documento_ref')
                    if ref and isinstance(ref, str) and ',' in ref:
                        try:
                            m, rid = ref.split(',')
                            model_to_ids.setdefault(m, []).append(int(rid))
                        except Exception: continue
                
                # Fetch names in bulk for each model
                id_to_name = {}
                for m, rids in model_to_ids.items():
                    try:
                        # Use read to get names efficiently
                        objs = odoo.env[m].read(rids, ['name'])
                        for o in objs:
                            id_to_name[f"{m},{o['id']}"] = o.get('name')
                    except Exception as e:
                        print(f"[certs-odoo] Failed to read model {m}: {e}")

                # Map to frontend format
                res = []
                for d in docs_data:
                    srv = d.get('servicio_id')
                    ref = d.get('documento_ref')
                    doc_reg_val = id_to_name.get(ref) if ref else None
                    
                    res.append({
                        "documento": srv[1] if (isinstance(srv, (list, tuple)) and len(srv) > 1) else "Certificado",
                        "numero": doc_reg_val or "-",
                        "fecha_emision": str(d.get('fecha_inicio')) if d.get('fecha_inicio') else None,
                        "fecha_caducidad": str(d.get('fecha_endoso_caducidad')) if d.get('fecha_endoso_caducidad') else None
                    })
                
                print(f"[certs-odoo] RPC Fetch SUCCESS for nave_id {nave_id} in {time.time() - t_start:.2f}s")
                
                # Extract Authorized List info
                cumple = v_data.get('cumple_lista_autorizada')
                lista_data = v_data.get('lista_autorizada_id') # [id, name] or False
                
                auth_list_name = lista_data[1] if (isinstance(lista_data, (list, tuple)) and len(lista_data) > 1) else None

                return {
                    "data": res,
                    "cumple_lista_autorizada": cumple,
                    "lista_autorizada_nombre": auth_list_name
                }
        except Exception as e:
            print(f"[certs-odoo] RPC Fetch Error for nave_id {nave_id}: {e}")

    # 2. Fallback to SQL logic if RPC failed or returned nothing
    try:
        mmsi = _mmsi_from_nave_id(nave_id)
        raw_data = get_catalog_certs(mmsi)
    except Exception:
        # Graceful fallback if MMSI is missing or SQL fails
        raw_data = {"data": []}
    
    if raw_data and "data" in raw_data:
        adapted = []
        for c in raw_data["data"]:
            adapted.append({
                "documento": c.get("nombre") or "Certificado",
                "numero": c.get("numero") or "-",
                "fecha_emision": c.get("fecha_emision"),
                "fecha_caducidad": c.get("fecha_vencimiento") 
            })
        return {"data": adapted}
        
    return {"data": []}

@app.get("/api/v1/catalog/vessel/{mmsi}/engines")
def get_catalog_engines(mmsi: str):
    """
    Motores: hoy sólo retornamos los vínculos desde `nave_motor_nave`
    (id de relación, motor_id, fecha_inicio/fin, obs…).
    Cuando confirmes la tabla maestra (p.ej. `nave_motor`), haremos JOIN para marca/modelo/HP.
    """
    if not ext_engine:
        raise HTTPException(status_code=500, detail="Catálogo externo no configurado")

    with ext_engine.connect() as conn:
        if not table_exists(conn, "nave_motor_nave"):
            return {"data": []}

        rcols = cols(conn, "nave_motor_nave")
        # columnas que vimos
        fk_motor = "motor_id"           if "motor_id"           in rcols else None
        fk_nave  = "nave_id"            if "nave_id"            in rcols else None
        f_ini    = "fecha_inicio"       if "fecha_inicio"       in rcols else None
        f_fin    = "fecha_fin"          if "fecha_fin"          in rcols else None
        f_sobs   = "subida_obs"         if "subida_obs"         in rcols else None
        f_bobs   = "bajada_obs"         if "bajada_obs"         in rcols else None
        f_active = "active"             if "active"             in rcols else None

        if not (fk_motor and fk_nave):
            return {"data": []}

        sel = [f"rel.id AS relacion_id", f"rel.{fk_motor} AS motor_id"]
        if f_ini:  sel.append(f"rel.{f_ini} AS fecha_inicio")
        if f_fin:  sel.append(f"rel.{f_fin} AS fecha_fin")
        if f_sobs: sel.append(f"rel.{f_sobs} AS subida_obs")
        if f_bobs: sel.append(f"rel.{f_bobs} AS bajada_obs")

        sql = text(f"""
            SELECT {", ".join(sel)}
            FROM nave_motor_nave rel
            JOIN nave_nave n ON n.id = rel.{fk_nave}
            WHERE n.mmsi = :mmsi
            {"AND rel.active IS TRUE" if f_active else ""}
            ORDER BY rel.id
        """)

        rows = [dict(r._mapping) for r in conn.execute(sql, {"mmsi": mmsi})]
        return {"data": rows}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/engines")
async def get_catalog_engines_by_id(nave_id: int):
    """Fetch vessel engines from Odoo RPC with fallback to SQL."""
    odoo = _get_odoo_client()
    if odoo:
        try:
            Vessel = odoo.env['nave.nave']
            v = Vessel.browse(nave_id)
            if hasattr(v, 'motor_ids') and v.motor_ids:
                res = []
                for rel in v.motor_ids:
                    m = getattr(rel, 'motor_id', None)
                    if m:
                        res.append({
                            "marca": getattr(m.marca_id, 'name', '-') if hasattr(m, 'marca_id') and m.marca_id else "-",
                            "modelo": getattr(m.modelo_id, 'name', '-') if hasattr(m, 'modelo_id') and m.modelo_id else getattr(m, 'modelo', '-'),
                            "serie": getattr(m, 'serie', '-'),
                            "potencia": getattr(m, 'potencia', '-'),
                            "rpm": getattr(m, 'rpm', '-')
                        })
                if res:
                    return {"data": res}
        except Exception as e:
            print(f"[engines-odoo] RPC Error for nave_id {nave_id}: {e}")

    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_engines(mmsi)


@app.get("/api/v1/catalog/vessel/{mmsi}/owner")
def get_catalog_owner(mmsi: str):
    sql = text("""
      SELECT rp.id, rp.name, rp.vat, rp.phone, rp.mobile, rp.email, rp.street, rp.city
      FROM nave_nave n
      LEFT JOIN res_partner rp ON rp.id = n.propietario_principal_id
      WHERE n.mmsi=:mmsi
    """)
    row = ext_engine.connect().execute(sql, {"mmsi":mmsi}).fetchone()
    return {"data": dict(row._mapping) if row else None}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/owner")
async def get_catalog_owner_by_id(nave_id: int):
    """Fetch vessel owner from Odoo RPC with fallback to SQL."""
    odoo = _get_odoo_client()
    if odoo:
        try:
            Vessel = odoo.env['nave.nave']
            v = Vessel.browse(nave_id)
            owner = v.propietario_principal_id
            if owner:
                return {"data": {
                    "id": owner.id,
                    "nombre": owner.name,
                    "identificacion": owner.vat,
                    "telefono": getattr(owner, 'phone', None),
                    "celular": getattr(owner, 'mobile', None),
                    "email": getattr(owner, 'email', None),
                    "direccion": getattr(owner, 'street', None),
                    "ciudad": getattr(owner, 'city', None)
                }}
        except Exception as e:
            print(f"[owner-odoo] RPC Error for nave_id {nave_id}: {e}")
            
    mmsi = _mmsi_from_nave_id(nave_id)
    raw = get_catalog_owner(mmsi)
    # Map SQL fields to frontend names if needed
    if raw and raw.get("data"):
        d = raw["data"]
        return {"data": {
            "nombre": d.get("name"),
            "identificacion": d.get("vat"),
            "telefono": d.get("phone"),
            "celular": d.get("mobile"),
            "email": d.get("email"),
            "direccion": d.get("street")
        }}
    return raw

@app.get("/api/v1/catalog/vessel/{mmsi}/manning")
def get_catalog_manning(mmsi: str):
    if not ext_engine:
        raise HTTPException(status_code=500, detail="Catálogo externo no configurado")

    with ext_engine.connect() as conn:
        if not table_exists(conn, "nave_dotacion_minima"):
            return {"data": []}

        dcols = cols(conn, "nave_dotacion_minima")
        # campos típicos
        f_cargo = "cargo" if "cargo" in dcols else None
        f_cant  = "cantidad_min" if "cantidad_min" in dcols else None

        sql = text(f"""
          SELECT {f_cargo or "'Cargo'"} AS cargo,
                 {f_cant or "0"}        AS cantidad_min
          FROM nave_nave n
          JOIN nave_dotacion_minima dm ON dm.id = n.dotacion_minima_id
          WHERE n.mmsi=:mmsi
        """)
        rows = [dict(r._mapping) for r in conn.execute(sql, {"mmsi": mmsi})]
        return {"data": rows}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/manning")
async def get_catalog_manning_by_id(nave_id: int):
    """Fetch vessel manning (dotación) from Odoo RPC with fallback to SQL."""
    odoo = _get_odoo_client()
    if odoo:
        try:
            Vessel = odoo.env['nave.nave']
            v = Vessel.browse(nave_id)
            dm = v.dotacion_minima_id
            if dm and hasattr(dm, 'dotacion_ids'):
                res = []
                for line in dm.dotacion_ids:
                    res.append({
                        "cargo": getattr(line.cargo_id, 'name', '-') if hasattr(line, 'cargo_id') and line.cargo_id else getattr(line, 'cargo', '-'),
                        "cantidad_min": getattr(line, 'cantidad_min', 0)
                    })
                if res:
                    return {"data": res}
        except Exception as e:
            print(f"[manning-odoo] RPC Error for nave_id {nave_id}: {e}")

    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_manning(mmsi)

@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/crew")
async def get_catalog_crew_by_id(nave_id: int):
    """Fetch current/last voyage crew from Odoo RPC."""
    odoo = _get_odoo_client()
    if odoo:
        try:
            # 1. Find the latest zarpe for the vessel
            Zarpe = odoo.env['nave.zarpe']
            zarpe_ids = Zarpe.search([('nave_id', '=', nave_id)], order='fecha_zarpe desc', limit=1)
            if zarpe_ids:
                z = Zarpe.browse(zarpe_ids[0])
                # 2. Extract crew from tripulacion_ids relation
                res = []
                # Guessing relation field name based on standard Odoo naming or existing SQL
                trip_ids = getattr(z, 'tripulacion_ids', [])
                if not trip_ids and hasattr(z, 'tripula_ids'): # fallback to common variations
                    trip_ids = z.tripula_ids
                
                for line in trip_ids:
                    res.append({
                        "Cargo": getattr(line.cargo_id, 'name', '-') if hasattr(line, 'cargo_id') and line.cargo_id else getattr(line, 'cargo', '-'),
                        "Tripulante": line.partner_id.name if line.partner_id else "-",
                        "Identificación": line.partner_id.vat if line.partner_id else "-",
                        "Licencia": getattr(line, 'licencia', '-')
                    })
                if res:
                    return {"data": res}
        except Exception as e:
            print(f"[crew-odoo] RPC Error for nave_id {nave_id}: {e}")

    # Fallback to local SQL if needed (not implemented yet in this session)
    return {"data": []}

@app.get("/api/v1/catalog/vessel/{mmsi}/armador")
def get_catalog_armador(mmsi: str):
    sql = text("""
      SELECT rp.id, rp.name, rp.vat, rp.phone, rp.mobile, rp.email
      FROM nave_nave n
      LEFT JOIN res_partner rp ON rp.id = n.enabled_armador_id
      WHERE n.mmsi=:mmsi
    """)
    row = ext_engine.connect().execute(sql, {"mmsi": mmsi}).fetchone()
    return {"data": dict(row._mapping) if row else None}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/armador")
async def get_catalog_armador_by_id(nave_id: int):
    """Fetch vessel armador from Odoo RPC with fallback to SQL."""
    odoo = _get_odoo_client()
    if odoo:
        try:
            Vessel = odoo.env['nave.nave']
            v = Vessel.browse(nave_id)
            arm = v.armador_id
            if arm:
                return {"data": {
                    "id": arm.id,
                    "nombre": arm.name,
                    "identificacion": arm.vat,
                    "telefono": getattr(arm, 'phone', None),
                    "celular": getattr(arm, 'mobile', None),
                    "email": getattr(arm, 'email', None),
                    "direccion": getattr(arm, 'street', None),
                    "ciudad": getattr(arm, 'city', None)
                }}
        except Exception as e:
            print(f"[armador-odoo] RPC Error for nave_id {nave_id}: {e}")

    mmsi = _mmsi_from_nave_id(nave_id)
    raw = get_catalog_armador(mmsi)
    if raw and raw.get("data"):
        d = raw["data"]
        return {"data": {
            "nombre": d.get("name"),
            "identificacion": d.get("vat"),
            "telefono": d.get("phone"),
            "celular": d.get("mobile"),
            "email": d.get("email"),
            "direccion": d.get("street")
        }}
    return raw

@app.get("/api/v1/catalog/vessel/{mmsi}/crew")
def get_catalog_crew(mmsi: str):
    # EXPERIMENTAL: Query activada para pruebas
    sql = text("""
      WITH ult AS (
        SELECT z.id
        FROM nave_zarpe z
        JOIN nave_nave n ON n.id=z.nave_id
        WHERE n.mmsi=:mmsi AND z.estado IN ('en_curso','finalizado')
        ORDER BY z.fecha_zarpe DESC
        LIMIT 1
      )
      SELECT c.cargo, p.name AS tripulante, p.vat AS id_doc, c.licencia
      FROM nave_zarpe_tripulacion c
      JOIN ult ON c.zarpe_id = ult.id
      JOIN res_partner p ON p.id = c.partner_id
      ORDER BY c.cargo
    """)
    try:
        rows = [dict(r._mapping) for r in ext_engine.connect().execute(sql, {"mmsi": mmsi})]
        return {"data": rows}
    except Exception as e:
        print(f"[crew] error experimental: {e}")
        return {"data": []}

@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/crew")
def get_catalog_crew_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_crew(mmsi)

@app.get("/api/v1/catalog/vessel/{mmsi}/armador/license")
def get_catalog_armador_license(mmsi: str):
    # EXPERIMENTAL: Query activada para pruebas
    sql = text("""
      SELECT lic.numero, lic.fecha_emision, lic.fecha_vencimiento, lic.estado
      FROM nave_nave n
      JOIN res_partner rp ON rp.id = n.enabled_armador_id
      JOIN armador_licencia lic ON lic.partner_id = rp.id AND lic.activa=True
      WHERE n.mmsi=:mmsi
      ORDER BY lic.fecha_vencimiento DESC
      LIMIT 1
    """)
    try:
        row = ext_engine.connect().execute(sql, {"mmsi": mmsi}).fetchone()
        return {"data": dict(row._mapping) if row else None}
    except Exception as e:
        print(f"[armador_license] error experimental: {e}")
        return {"data": None}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/armador/license")
def get_catalog_armador_license_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_armador_license(mmsi)

@app.get("/api/v1/catalog/vessel/{mmsi}/voyages")
def get_catalog_voyages(mmsi: str, limit: int = 10, default_nave_id: int = 8):
    """
    Zarpes vigentes:
    - rows: tabla de zarpes vigentes (sin ruta).
    - route_points: puntos de la ruta vigente (planificada).
    - real_points: puntos recientes del DMS (ruta real).
    """
    if not ext_engine:
        return {"rows": [], "route_points": [], "real_points": [], "nave_id": None}

    sql_find_nave = text("SELECT id FROM nave_nave WHERE mmsi = :mmsi LIMIT 1")
    sql_table = text("""
        SELECT 
            tz.id AS zarpe_id,
            tde.name AS documento_nombre,
            tde.state AS estado_documento,
            tmn.id AS navegacion_id,
            nn.id AS nave_id,
            nn.name AS nave
        FROM trafico_maritimo_zarpe tz
        LEFT JOIN tramite_documento_emitido tde
            ON tde.id = tz.documento_emitido_id
        LEFT JOIN trafico_maritimo_navegacion tmn
            ON tmn.id = tz.trafico_maritimo_navegacion_id
        LEFT JOIN nave_nave nn
            ON nn.id = tmn.nave_id
        WHERE tde.state = 'vigente' AND nn.id = :nave_id
        ORDER BY tz.id DESC
        LIMIT :lim
    """)
    sql_route = text("""
        SELECT 
            tmr.orden,
            tmr.latitud,
            tmr.longitud
        FROM trafico_maritimo_zarpe tz
        LEFT JOIN tramite_documento_emitido tde
            ON tde.id = tz.documento_emitido_id
        LEFT JOIN trafico_maritimo_navegacion tmn
            ON tmn.id = tz.trafico_maritimo_navegacion_id
        LEFT JOIN trafico_maritimo_navegacion_ruta tmr
            ON tmr.trafico_maritimo_navegacion_id = tmn.id
        LEFT JOIN nave_nave nn
            ON nn.id = tmn.nave_id
        WHERE tde.state = 'vigente' AND nn.id = :nave_id
        ORDER BY tz.id, tmr.orden
        LIMIT :lim
    """)
    sql_real = text("""
        SELECT 
            nn.id AS x_nave_id,
            nn.name AS x_nombre_nave,
            ndqth.latitud AS x_latitud,
            ndqth.longitud AS x_longitud,
            ndqth.rumbo AS x_rumbo,
            ndqth.velocidad AS x_velocidad,
            ndqth.fecha_qth AS x_fecha_qth
        FROM nave_dms_qth ndqth
        LEFT JOIN nave_dms_nave ndn ON ndn.id = ndqth.dms_nave_id
        LEFT JOIN nave_nave nn ON ndn.nave_id = nn.id
        WHERE nn.id = :nave_id
        ORDER BY ndqth.fecha_qth DESC
        LIMIT :lim
    """)
    try:
        with ext_engine.connect() as conn:
            nave_row = conn.execute(sql_find_nave, {"mmsi": mmsi}).fetchone()
            nave_id = nave_row[0] if nave_row else default_nave_id
            table_rows = [dict(r._mapping) for r in conn.execute(sql_table, {"nave_id": nave_id, "lim": limit}).fetchall()]
            route_rows = [dict(r._mapping) for r in conn.execute(sql_route, {"nave_id": nave_id, "lim": limit}).fetchall()]
            real_rows = [dict(r._mapping) for r in conn.execute(sql_real, {"nave_id": nave_id, "lim": limit}).fetchall()]
    except Exception as exc:
        print(f"[voyages] error consultando rutas ({mmsi}): {exc}")
        return {"rows": [], "route_points": [], "real_points": [], "nave_id": None}

    points = []
    for r in route_rows:
        lat = r.get("latitud")
        lon = r.get("longitud")
        if lat is None or lon is None:
            continue
        try:
            points.append({"order": r.get("orden") or 0, "lat": float(lat), "lon": float(lon)})
        except Exception:
            continue
    points.sort(key=lambda p: p.get("order", 0))
    real_points = []
    for r in real_rows:
        lat = r.get("x_latitud")
        lon = r.get("x_longitud")
        if lat is None or lon is None:
            continue
        try:
            real_points.append({
                "lat": float(lat),
                "lon": float(lon),
                "heading": r.get("x_rumbo"),
                "speed": r.get("x_velocidad"),
                "ts": r.get("x_fecha_qth").timestamp() if r.get("x_fecha_qth") else None
            })
        except Exception:
            continue
    # ordenar por fecha si está disponible
    real_points.sort(key=lambda p: p.get("ts") or 0)

    return {"rows": table_rows, "route_points": points, "real_points": real_points, "nave_id": nave_id}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/voyages")
def get_catalog_voyages_by_id(nave_id: int, limit: int = 10, default_nave_id: int = 8):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_voyages(mmsi, limit=limit, default_nave_id=default_nave_id)

# @app.get("/api/v1/catalog/vessel/{mmsi}/armador/license")
# def get_catalog_armador_license(mmsi: str):
#     sql = text("""
#       SELECT lic.numero, lic.fecha_emision, lic.fecha_vencimiento, lic.estado
#       FROM nave_nave n
#       JOIN res_partner rp ON rp.id = n.enabled_armador_id
#       JOIN armador_licencia lic ON lic.partner_id = rp.id AND lic.activa=True    # TODO tablas reales
#       WHERE n.mmsi=:mmsi
#       ORDER BY lic.fecha_vencimiento DESC
#       LIMIT 1
#     """)
#     row = ext_engine.connect().execute(sql, {"mmsi": mmsi}).fetchone()
#     return {"data": dict(row._mapping) if row else None}

@app.get("/api/v1/catalog/vessel/{mmsi}/passengers")
def get_catalog_passengers(mmsi: str):
    sql = text("""
      SELECT ds.capacidad_pasajeros
      FROM nave_nave n
      JOIN nave_datos_seguridad ds ON ds.id = n.datos_seguridad_id
      WHERE n.mmsi=:mmsi
    """)
    row = ext_engine.connect().execute(sql, {"mmsi": mmsi}).fetchone()
    return {"data": dict(row._mapping) if row else None}


@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/passengers")
def get_catalog_passengers_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return get_catalog_passengers(mmsi)


@app.get("/api/v1/debug/photo-schema")
def debug_photo_schema():
    """Find vessels with photos that have recent AIS positions"""
    if not ext_engine:
        return {"error": "External database not configured"}
    
    try:
        # Find vessels with photos that have recent AIS data
        sql = text("""
            WITH vessels_with_photos AS (
                SELECT DISTINCT
                    nf.nave_id,
                    n.name as nombre,
                    n.matricula,
                    n.mmsi,
                    COUNT(DISTINCT a.id) as num_photos
                FROM nave_nave_foto nf
                INNER JOIN ir_attachment a ON a.res_model = 'nave.nave.foto' 
                    AND a.res_id = nf.id 
                    AND a.res_field = 'foto_1920'
                    AND a.store_fname IS NOT NULL
                INNER JOIN nave_nave n ON n.id = nf.nave_id
                WHERE nf.active = true
                    AND n.mmsi IS NOT NULL
                GROUP BY nf.nave_id, n.name, n.matricula, n.mmsi
                HAVING COUNT(DISTINCT a.id) > 0
            )
            SELECT 
                v.nave_id,
                v.nombre,
                v.matricula,
                v.mmsi,
                v.num_photos
            FROM vessels_with_photos v
            ORDER BY v.num_photos DESC
            LIMIT 20
        """)
        
        with ext_engine.connect() as conn:
            vessels = [dict(row._mapping) for row in conn.execute(sql)]
        
        return {
            "vessels_with_photos": vessels,
            "total": len(vessels)
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


import time

_ODOO_CACHE = {
    "client": None,
    "last_login": 0,
    "host": None
}

def _get_odoo_client():
    """
    Central helper to get Odoo RPC client with caching to avoid redundant logins.
    """
    global _ODOO_CACHE
    ODOO_HOST = os.getenv("ODOO_RPC_HOST", "10.141.49.21")
    ODOO_PORT = int(os.getenv("ODOO_RPC_PORT", "8070"))
    ODOO_DB = os.getenv("ODOO_RPC_DB", "sigmap")
    ODOO_USER = os.getenv("ODOO_RPC_USER", "portal")
    ODOO_PASSWORD = os.getenv("ODOO_RPC_PASS", "vG]bEV]c1U#B[UIZ")

    now = time.time()
    
    # Reuse client if it's the same host and less than 20 minutes old
    if (_ODOO_CACHE["client"] and 
        _ODOO_CACHE["host"] == ODOO_HOST and 
        (now - _ODOO_CACHE["last_login"]) < 1200):
        try:
            # Light check to see if session is still valid
            _ = _ODOO_CACHE["client"].env.uid
            return _ODOO_CACHE["client"]
        except Exception:
            print("[odoo-rpc] Cached session expired or invalid, re-logging...")
            _ODOO_CACHE["client"] = None

    import odoorpc
    t0 = time.time()
    try:
        print(f"[odoo-rpc] Connecting to {ODOO_HOST}:{ODOO_PORT}...")
        odoo = odoorpc.ODOO(ODOO_HOST, protocol='jsonrpc', port=ODOO_PORT, timeout=10)
        odoo.login(ODOO_DB, ODOO_USER, ODOO_PASSWORD)
        
        _ODOO_CACHE["client"] = odoo
        _ODOO_CACHE["last_login"] = now
        _ODOO_CACHE["host"] = ODOO_HOST
        
        print(f"[odoo-rpc] Login successful in {time.time() - t0:.2f}s")
        return odoo
    except Exception as e:
        print(f"[odoo-rpc] Connection failed after {time.time() - t0:.2f}s: {e}")
        return None

@app.get("/api/v1/catalog/vessel/by-id/{nave_id}/photos")
async def get_vessel_photos(nave_id: int):
    """
    Retrieve photos for a vessel using ONLY OdooRPC (as requested by USER).
    - Connects to Odoo via RPC (.21:8070).
    - Searches for the vessel by ID or MMSI.
    - Reads binary image data from nave.nave.foto.
    """
    # Odoo configuration from .env
    ODOO_HOST = os.getenv("ODOO_RPC_HOST", "10.141.49.21")
    ODOO_PORT = int(os.getenv("ODOO_RPC_PORT", "8070"))
    ODOO_DB = os.getenv("ODOO_RPC_DB", "sigmap")
    ODOO_USER = os.getenv("ODOO_RPC_USER", "portal")
    ODOO_PASSWORD = os.getenv("ODOO_RPC_PASS", "vG]bEV]c1U#B[UIZ")
    
    try:
        # 1. Get MMSI from local DB to have an extra search key (optional but helpful)
        vessel_mmsi = None
        if ext_engine:
            with ext_engine.connect() as conn:
                try:
                    m_row = conn.execute(text("SELECT mmsi FROM nave_nave WHERE id = :nid"), {"nid": nave_id}).fetchone()
                    if m_row:
                        vessel_mmsi = m_row[0]
                except:
                    pass

        # 2. Connect to Odoo via RPC
        import odoorpc
        try:
            odoo = odoorpc.ODOO(ODOO_HOST, protocol='jsonrpc', port=ODOO_PORT, timeout=20)
            odoo.login(ODOO_DB, ODOO_USER, ODOO_PASSWORD)
        except Exception as e:
            print(f"[photos] Odoo RPC Connection Error: {e}")
            return {"photos": [], "error": f"Error de conexión Odoo: {str(e)}"}

        # 3. Search for the vessel in Odoo
        NaveModel = odoo.env['nave.nave']
        domain = ['|', ('id', '=', nave_id)]
        if vessel_mmsi:
            domain.append(('mmsi', '=', vessel_mmsi))
        
        vessel_ids = NaveModel.search(domain, limit=1)
        if not vessel_ids:
            return {"photos": [], "warning": "Nave no encontrada en Odoo por ID o MMSI"}
        
        ovid = vessel_ids[0]
        
        # 4. Search for photo records linked to this vessel
        FotoModel = odoo.env['nave.nave.foto']
        # Remove 'order' to prevent timeouts in production Odoo
        try:
            f_ids = FotoModel.search([('nave_id', '=', ovid), ('active', '=', True)], limit=10)
            if not f_ids:
                f_ids = FotoModel.search([('nave_id', '=', ovid)], limit=5)
        except Exception as e:
            print(f"[photos] error en search: {e}")
            f_ids = []

        # 5. Fetch image data
        photos = []
        # Use only verified fields for this Odoo version/model
        verified_image_fields = ['foto_1920', 'foto_128']
        
        if f_ids:
            try:
                res_list = FotoModel.read(f_ids, verified_image_fields + ['fecha_foto', 'write_date'])
                
                for res in res_list:
                    rid = res.get('id')
                    image_data = None
                    found_field = None
                    
                    for field in verified_image_fields:
                        val = res.get(field)
                        if val: # base64 string
                            image_data = val
                            found_field = field
                            break
                    
                    if image_data:
                        fecha = res.get('fecha_foto') or res.get('write_date')
                        photos.append({
                            "id": rid,
                            "name": found_field,
                            "image_data": image_data,
                            "mime_type": "image/jpeg",
                            "fecha_foto": str(fecha) if fecha else None,
                            "file_size": len(image_data)
                        })
            except Exception as e:
                print(f"[photos] error leyendo fotos {f_ids}: {e}")

        # Sort the results in Python by date (descending)
        photos.sort(key=lambda x: x.get('fecha_foto') or '', reverse=True)

        return {"photos": photos}
        
    except Exception as e:
        print(f"[photos] general error: {e}")
        import traceback
        traceback.print_exc()
        return {"photos": [], "error": str(e)}


@app.post("/auth/login")
async def auth_login(payload: LoginPayload):
    if not (GEONODE_OAUTH_CLIENT_ID and GEONODE_OAUTH_CLIENT_SECRET):
        raise HTTPException(status_code=500, detail="OAuth no configurado en el servicio")
    data = {
        "grant_type": "password",
        "username": payload.username,
        "password": payload.password,
        "client_id": GEONODE_OAUTH_CLIENT_ID,
        "client_secret": GEONODE_OAUTH_CLIENT_SECRET,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Host": GEONODE_HOST_HEADER} if GEONODE_HOST_HEADER else None
        resp = await client.post(GEONODE_OAUTH_TOKEN_URL, data=data, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Credenciales inválidas")
    return resp.json()

@app.get("/api/v1/vessels/search")
async def search_vessels(q: Optional[str] = None):
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    params = {"query": f"%{q}%"}
    
    with engine.begin() as conn:
        rows = conn.execute(text(f"""
            SELECT v.mmsi, v.matricula, v.name, v.type, v.flag
            FROM vessels v
            WHERE (v.matricula ILIKE :query OR v.name ILIKE :query OR v.mmsi::text ILIKE :query)
            ORDER BY v.name
            LIMIT 100
        """), params).mappings().all()

    return {"data": list(rows)}


@app.get("/api/v1/vessels/{mmsi}/track")
async def get_track(mmsi: int, hours: int = 6):
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT EXTRACT(EPOCH FROM ts) as ts, ST_X(geom::geometry) as lon, ST_Y(geom::geometry) as lat,
                   sog_knots, cog_deg
            FROM positions
            WHERE mmsi = :mmsi AND ts >= NOW() - (:hours || ' hours')::interval
            ORDER BY ts ASC
        """), dict(mmsi=mmsi, hours=hours)).mappings().all()
    return {"mmsi": mmsi, "points": list(rows)}


@app.get("/api/v1/vessels/by-id/{nave_id}/track")
async def get_track_by_id(nave_id: int, hours: int = 6):
    mmsi = _mmsi_from_nave_id(nave_id)
    return await get_track(mmsi, hours=hours)


@app.get("/api/v1/vessels/{mmsi}/projection")
async def get_projection(mmsi: int, minutes: int = Query(60, ge=10, le=1440)):
    """
    Get projected path for a vessel based on current SOG/COG.
    Returns multi-color projection (inside/outside maritime area).
    """
    if not redis:
        return {"error": "Redis not ready"}
        
    data = await redis.get(f"vessel:last:{mmsi}")
    if not data:
        return {"error": "Vessel not found"}
        
    vessel = json.loads(data)
    
    lat = vessel.get('lat')
    lon = vessel.get('lon')
    sog = vessel.get('sog_knots')
    cog = vessel.get('cog_deg')
    traffic_type = vessel.get('tipo_trafico', 'Nacional')
    dest_lat = vessel.get('dest_lat')
    dest_lon = vessel.get('dest_lon')
    
    if lat is None or lon is None:
        return {"error": "Invalid vessel data"}
        
    result_str = calculate_projection(lat, lon, sog, cog, minutes, traffic_type=traffic_type, dest_lat=dest_lat, dest_lon=dest_lon)
    
    if not result_str:
        return {"type": "FeatureCollection", "features": [], "properties": {"msg": "No projection (stationary or error)"}}
    
    # Parse the JSON result with inside/outside geometries
    result = json.loads(result_str)
    features = []
    
    # Inside maritime area (purple)
    if result.get('inside') and result['inside'] != 'null':
        inside_geom = json.loads(result['inside'])
        features.append({
            "type": "Feature",
            "properties": {
                "mmsi": mmsi,
                "minutes": minutes,
                "zone": "inside_maritime",
                "color": "#9333ea"  # Purple
            },
            "geometry": inside_geom
        })
    
    # Outside maritime area (red OR purple if international)
    if result.get('outside') and result['outside'] != 'null':
        outside_geom = json.loads(result['outside'])
        is_international = result.get('traffic_type', '').lower() == 'internacional'
        features.append({
            "type": "Feature",
            "properties": {
                "mmsi": mmsi,
                "minutes": minutes,
                "zone": "outside_maritime",
                "color": "#9333ea" if is_international else "#ef4444"  # Purple if international, Red otherwise
            },
            "geometry": outside_geom
        })
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


@app.get("/api/v1/vessels/by-id/{nave_id}/projection")
async def get_projection_by_id(nave_id: int, minutes: int = Query(60, ge=10, le=1440)):
    mmsi = _mmsi_from_nave_id(nave_id)
    return await get_projection(mmsi, minutes=minutes)

@app.get("/api/v1/vessels/{mmsi}/alert-status")
async def get_alert_status(mmsi: int):
    """Return alert status for a vessel."""
    if not redis:
        raise HTTPException(status_code=503, detail="Redis not ready")
    data = await redis.get(f"vessel:last:{mmsi}")
    if not data:
        raise HTTPException(status_code=404, detail="Vessel not found")
    payload = json.loads(data)
    return {
        "mmsi": mmsi,
        "status_color": payload.get("status_color", "green"),
        "spatial_alert": payload.get("spatial_alert", "")
    }


@app.get("/api/v1/vessels/by-id/{nave_id}/alert-status")
async def get_alert_status_by_id(nave_id: int):
    mmsi = _mmsi_from_nave_id(nave_id)
    return await get_alert_status(mmsi)


@app.get("/api/v1/alerts/incidents")
def get_incident_alerts(q: str | None = None, limit: int = ALERTS_LIMIT_DEFAULT):
    """
    Devuelve alertas (incidencia_evento) con join a nave y reparto.
    Soporta filtro textual simple (ILIKE) sobre varias columnas.
    """
    if not ext_engine:
        return {"data": []}

    base_sql = """
        SELECT
            e.create_date,
            e.severidad,
            e.reparto_id,
            tipo.name       AS evento_tipo,
            r.siglas        AS reparto,
            n.id            AS nave_id,
            n.name          AS nave_name,
            n.matricula     AS nave_matricula,
            n.omi_number    AS nave_omi,
            n.mmsi          AS nave_mmsi
        FROM incidencia_evento e
        JOIN sigmap_reparto r ON r.id = e.reparto_id
        JOIN nave_nave n ON n.id = e.nave_id
        LEFT JOIN incidencia_evento_tipo tipo ON tipo.id = e.tipo_id
    """

    params: dict[str, object] = {"lim": max(1, min(limit, 1000))}
    where = []
    if q:
        params["q"] = f"%{q}%"
        where.append("""
        (
            CAST(e.severidad AS TEXT) ILIKE :q OR
            CAST(e.reparto_id AS TEXT) ILIKE :q OR
            COALESCE(tipo.name,'') ILIKE :q OR
            COALESCE(r.siglas,'') ILIKE :q OR
            CAST(n.id AS TEXT) ILIKE :q OR
            COALESCE(n.name,'') ILIKE :q OR
            COALESCE(n.matricula,'') ILIKE :q OR
            COALESCE(n.omi_number,'') ILIKE :q OR
            COALESCE(n.mmsi,'') ILIKE :q
        )
        """)

    sql_parts = [base_sql]
    if where:
        sql_parts.append("WHERE " + " AND ".join(where))
    sql_parts.append("ORDER BY e.create_date DESC")
    sql_parts.append("LIMIT :lim")
    sql = text("\n".join(sql_parts))

    try:
        with ext_engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(sql, params)]
        return {"data": rows}
    except Exception as e:
        print(f"ERROR fetching alerts: {e}")
        # Return empty list if table missing or DB error, to prevent frontend crash
        return {"data": []}
