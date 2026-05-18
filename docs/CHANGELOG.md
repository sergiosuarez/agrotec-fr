# Changelog del visor IDEPalma

> Convención: el primer item de cada bloque es el commit que disparó el cambio (cuando aplica).

---

## Rebrand dominio — 2026-05-18 (tarde)

- Dominio del sistema migrado de `agrotec.desarrollowebsite.com` → `idepalma.desarrollowebsite.com` (rename limpio, sin redirect).
- Cert LE nuevo emitido vía `certbot --standalone` (downtime ~30 s del proxy). Cert viejo `agrotec.*` borrado.
- nginx StreamTrack (`/opt/streamtrack/nginx/nginx.conf`) actualizado: server blocks 80+443 con el nuevo `server_name` y rutas de cert.
- `.env` de ambos stacks (`bk/` GeoNode y `fr/` visor) actualizados: `SITEURL`, `ALLOWED_HOSTS`, `NGINX_BASE_URL`, `HTTP_HOST`, `GEOSERVER_WEB_UI_LOCATION`, `GEONODE_PUBLIC_*`, `GEONODE_HOST_HEADER`. Containers afectados recreados con `--force-recreate`.
- Código: defaults de `services/ingest_ws/app/config.py` + URLs en `bk/scripts/{fix-nginx-proxy.sh,import_vectors.sh}` + todos los docs (README, VISOR_GUIA, API, DESPLIEGUE, CHANGELOG, INSTRUCTIVO_SUBIR_CAPAS) actualizados al nuevo dominio.
- **Fix bug colateral en `visor_config.py`**: rows nuevas en `visor_layer_config` quedaban con `visible=False` porque el `default=True` de SQLAlchemy `mapped_column` no se aplicaba confiable en INSERT cuando el atributo no se seteaba antes del flush. Ahora se pasan defaults explícitos al constructor (`visible=True, featured=False, order=999, default_opacity=1.0`). Rows existentes que quedaron mal se corrigieron con `UPDATE visor_layer_config SET visible=TRUE WHERE visible IS NOT TRUE`.

---

## v2 — 2026-05-18

Reescritura del geovisor de Leaflet básico a MapLibre GL JS con panel meteorológico interactivo, admin de capas y workflow de carga de ortomosaicos drone optimizado.

### Frontend (`services/ingest_ws/static/index.html`)

- **`bcffc8d`** — admin con 3 columnas (Visible / Destacada / Orden) con bloque de ayuda explicando cada una. Categorías del sidebar colapsables (click en el header). Sidebar completo colapsable vía botón flotante. Coords overlay sube cuando se abre el panel meteo. Perfil vertical con más margen superior (no encimar leyenda con eje X-top).
- **`7442c6e`** — viento incluido en el tooltip principal del pronóstico (antes vivía en otro grid/eje y no aparecía al hacer hover en el grid superior). Respeta toggle de la leyenda.
- **`6ce6f64`** — fix tooltip que mostraba los 12 instantes de viento simultáneamente (era un bug del `category` axis con un solo valor).
- **`35c8813`** — panel meteo reorganizado en grid 75% pronóstico / 25% perfil vertical (antes era pestañas). Flechas de viento en una fila inferior, rotadas por dirección y escaladas por velocidad.
- **`4c585e9`** — popup vectorial restaurado (click en polígono → tabla con atributos). Panel meteorológico GFS con ECharts: pronóstico horario (T, HR, lluvia, solar, viento) + perfil vertical (T y HR en 6 niveles de presión).
- **`40fd382`** — v2 inicial: capas categorizadas (ortomosaicos, haciendas, vectoriales, límites, infraestructura), búsqueda, URL state compartible (`?l=alt1,alt2&z=…&lat=…&lng=…`), admin modal con featured/order, mapa base intercambiable (OSM / Esri Sat / Carto Light), opacity slider por capa, z-order ▲▼ por capa activa.

### Backend (`services/ingest_ws/app/`)

- **`bcffc8d`** — nueva columna `visor_layer_config.visible` (default `true`). Si `false`, la capa NO aparece en el sidebar público. El modal admin la lee vía `/api/v1/layers?include_hidden=true`. Migración idempotente (`ALTER … ADD IF NOT EXISTS`).
- **`40fd382`** — nuevo endpoint `/api/v1/layers` que unifica raster + vector con merge contra `visor_layer_config` (featured, order, opacity, color). Nuevo `/api/v1/visor/config` (PUT upsert + DELETE) para admin. Nuevo `/api/v1/feature-info` que proxea GetFeatureInfo de GeoServer evitando CORS/ORB del navegador. Nuevos `/api/v1/gfs/point` y `/api/v1/gfs/profile` que leen los NetCDF y devuelven series listas para ECharts.

### Datos cargados

- **2026-05-18** — 7 ortomosaicos drone PALMAR convertidos a COG-JPEG e importados como dataset GeoNode (`vuelo1_placa27` a `vuelo7_placa22`). Compresión 10× respecto a los TIFFs originales (~9.9 GB → ~700 MB) manteniendo calidad visual.
- **2026-05-18** — los 7 TIFFs originales (subidos por error como Documents) fueron borrados tras importar (liberó ~10 GB del volumen `agrotec-statics`).

### Limitaciones conocidas

- Viento por altura: solo está disponible el viento a 10 m. El perfil vertical solo trae T y RH. Para tener flechas de viento por nivel de presión hay que extender `download_gfs.py` con `UGRD/VGRD` en `isobaricInhPa`.
- Perfil vertical es un snapshot fijo a +24 h. No sigue el cursor temporal del pronóstico. Mismo origen: el NetCDF vertical solo descarga 1 timestep.
- Capas con `bbox` solo en CRS nativo (UTM, etc.) sin `ll_bbox_polygon` se descartan (no aparecen en el listado).

---

## v1 (MVP) — 2026-05-17

Despliegue inicial:
- Stack GeoNode 4.4.3 + GeoServer 2.24.4 + PostGIS 15 (`agrotec-bk`)
- Stack FastAPI + PostGIS 16 + THREDDS + GFS scheduler (`agrotec-fr`)
- Stack Mergin Maps community edition para sync QField (`agrotec-fr/mobile/`)
- HTTPS por subdominio `idepalma.desarrollowebsite.com` con LE
- Wildcard DNS `*.desarrollowebsite.com → 167.86.111.196`
- Visor MVP: 4 capas AP_TEMP cargadas, listado simple sin admin
