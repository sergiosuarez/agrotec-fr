# Changelog del visor IDEPalma

> Convención: el primer item de cada bloque es el commit que disparó el cambio (cuando aplica).

---

## Pestañas superiores (modos) + modo Ortofoto — 2026-05-31

Reestructuración del visor a **barra superior de pestañas** (visión del Ing.): el mapa es compartido y cada pestaña cambia el contenido del sidebar.

- **Shell**: nuevo `#shell` (topbar + `#app`). Topbar con marca IDEPalma + 3 pestañas de modo: **🗺 Cartografía agrícola**, **🛩 Ortofoto Haciendas**, **🌈 Multiespectral**. `setMode()` muestra el `.mode-panel` activo y hace `map.resize()`.
- **Cartografía agrícola**: el visor actual completo (selector de hacienda, capas categorizadas incl. Ortomosaicos y Meteorología GFS, mapa base, estado). Sin cambios de comportamiento.
- **Ortofoto Haciendas**: selector de hacienda → muestra su ortofoto. Si la hacienda tiene **varias piezas** (p.ej. `jenny_elizabeth_s2/s3/s4`), se muestran **juntas como mosaico** (son trozos de un mismo vuelo que no se unió por tamaño, NO fechas distintas — aclaración del usuario). Una sola opacidad controla todas las piezas. El **comparador temporal** entre fechas queda pendiente para cuando haya vuelos de fechas distintas (campo Date en GeoNode).
- **Multiespectral**: placeholder con selector de índices (NDVI/NDRE/GNDVI/SAVI/OSAVI/VARI) deshabilitado; se calcularán con fórmulas de WebODM (rasterio+numexpr) cuando haya imágenes con banda NIR.
- Match de ortofotos por tokens verificado con las reales: Jenny Elizabeth→3 piezas, Darwin Andres 1 vs 2 separados, Daniela vs Daniel Alejandro sin cruce.
- **Limpieza de Cartografía**: la categoría Ortomosaicos (ortofotos) ya NO se lista en la pestaña Cartografía agrícola (`renderLayersTab` excluye `category==='ortomosaicos'`), y elegir hacienda en Cartografía carga solo capas vectoriales (no la ortofoto). Las ortofotos viven en la pestaña Ortofoto. También: `Cache-Control: no-cache` en las páginas para que el navegador tome siempre la última versión.

---

## Estilo de lotes, basemaps Google y rename "Lotes Palmar" — 2026-05-31

- **Estilo SLD de los lotes** (GeoServer): la capa `geonode:haciendas_palmar` usaba el estilo `polygon` por defecto (relleno gris) que tapaba la ortofoto. Se creó el estilo `lote_borde_verde` y se asignó como default. Iteración: primero borde verde claro `#9BE564` (no se veía bien sobre OSM) → final **línea oscura `#111418` con halo blanco** (doble PolygonSymbolizer: casing blanco 3.5px op .55 + línea 1.4px) y **sin relleno** → buen contraste sobre ortofoto y sobre OSM. SLD versionado en `bk/styles/lote_borde.sld`. Aplica también a la versión filtrada por hacienda (CQL).
- **Basemaps Google** (`static/index.html`): agregados **Satélite (Google)** (`lyrs=s`) e **Híbrido (Google)** (`lyrs=y`) a `BASEMAPS` + radios en la pestaña Mapa base. Subdominios mt0–mt3 para paralelizar tiles.
- **Rename a "Lotes Palmar"**: el recurso `haciendas_palmar` son en realidad LOTES (pronto subirán las haciendas reales). Se cambió SOLO el **título** del dataset en GeoNode a "Lotes Palmar" (el identificador/alternate `geonode:haciendas_palmar` y la tabla se mantienen — el código los referencia). GOTCHA: cambiar el título con `ResourceBase.objects.filter().update()` NO invalida la caché del API de GeoNode (el API seguía sirviendo el viejo); hay que usar `Dataset.objects.get(pk).save()` (dispara signals + invalida caché).

---

## Compresor de ortofotos a COG-JPEG — 2026-05-31

Servicio dentro del visor para comprimir ortomosaicos GeoTIFF pesados a COG-JPEG (lo que antes se hacía manual con GlobalMapper). Habilita cargar ortofotos grandes por GeoNode sin subir los 3 GB originales.

### Backend

- **`rio-cogeo` + `python-multipart`** agregados a requirements (rasterio trae GDAL en el wheel; el Dockerfile suma `libexpat1` que el wheel necesita en runtime).
- **Nuevo `app/routers/compresor.py`**: diseño con job en background para soportar archivos grandes sin colgar el request.
  - `POST /api/v1/compress` (multipart, `quality` 60–100, def 90) → streaming a disco + encola compresión → `{job_id}`.
  - `GET /api/v1/compress/{job_id}` → estado (uploading/queued/running/done/error + tamaños y ratio). Estado en JSON por job (compartido entre workers).
  - `GET /api/v1/compress/{job_id}/download` → descarga el COG.
  - `cog_translate` perfil JPEG q90, blocksize 512, overviews (average). RGBA → RGB + máscara interna (JPEG no soporta alfa). Borra el original tras comprimir; limpia jobs >24h.
- **`main.py`**: registra el router + ruta `GET /compresor` (página).

### Frontend

- **Nueva página `static/compresor.html`** (servida en `/visor/compresor`): subir GeoTIFF, slider de calidad, barra de progreso de subida (XHR), polling de estado, muestra ratio y botón de descarga. Branding IDEPalma.

### Verificado

- TIFF 27 MB (RGB ruido) → COG 2.2 MB (12.3×, y el ruido comprime mal; orthos reales rinden más). Salida: YCbCr JPEG, tiled 512, 3 overviews, EPSG 32717 preservado, COG válido.
- Nota: subir varios GB por navegador depende del ancho de banda (puede tardar). El nginx de idepalma ya permite hasta 10 GB (`client_max_body_size`). Para archivos enormes, alternativa futura: dejar el TIFF en una carpeta del servidor vía SFTP y comprimir server-side.

---

## Cartografía agrícola: selector de hacienda + zoom inicial — 2026-05-31

Primera fase del rediseño hacia un visor por haciendas (visión del Ing.: pestañas Cartografía / Ortofoto / Multiespectral). Esta entrega cubre la navegación por hacienda en la capa de lotes.

Realidad de datos confirmada: la capa `haciendas_palmar` (en `geonode_data`) es **una sola** con **453 lotes**; el atributo `nombre_hcd` identifica a cuál de las **22 haciendas** pertenece cada polígono. Las tablas relacionales (`hacienda/parcela/lote/ortomosaico`) están vacías → el selector se driven por atributo (sin ETL), decisión del usuario.

### API (`services/ingest_ws/app/routers/haciendas.py`)

- Nuevo `GET /api/v1/haciendas/extents` → `[{nombre, n_lotes, area_ha, bbox[4] WGS84}]`. Consulta directa a la geodata (`ST_Extent` + `ST_Transform 32717→4326`, `ST_Area/10000` para ha) agrupando por `nombre_hcd`. Whitelist defensivo de identificadores. Conexión read-only nueva a `geonode_data` (`config.geodata_url` / `GEODATA_URL` en `.env`, fuera del repo; `database.get_geodata_engine()` lazy).

### Frontend (`services/ingest_ws/static/index.html`)

- **Zoom inicial** ajustado al extent de las 22 haciendas (antes: centro fijo de Ecuador / featured).
- **Selector de hacienda** (dropdown verde arriba de la pestaña de capas): elegir una → zoom a su bbox + filtra la capa de lotes por `CQL_FILTER nombre_hcd='…'` (vía `setTiles`, sin recrear el layer). "— Todas —" quita el filtro y reencuadra todo.
- **Carga dinámica de capas relacionadas** (visor general por hacienda): al elegir una hacienda, además del filtro de lotes, se auto-cargan las capas (vectoriales/ortofotos) que corresponden a esa hacienda. Se rastrean en `autoRelated` y se quitan al cambiar; los vectores se ponen por encima de las ortofotos raster.
  - **Emparejamiento por tokens distintivos** (actualizado al cargar las primeras ortofotos reales): se exige que TODOS los tokens distintivos de la hacienda (slug sin `agricola/hcda/...`) aparezcan como tokens del nombre de la capa. Así matchea nombres irregulares de ortofotos (`amelia_rgb_final_cog`, `hcda_sebastian_ortomosaico_cog`, `hcda_daniela_antonela_cog`) Y los vectoriales (`lotes_agricola_amelia_actual`), sin confundir homónimas (Jenny Elizabeth vs Judith; Daniela vs Daniel Alejandro). Antes exigía el slug completo `agricola_<x>` y no matcheaba las ortofotos. Verificado contra las 22 haciendas.
  - **Categorización** (`layers.py _categorize`): se agregan `cog`/`hcda` a las palabras que marcan un raster como "ortomosaicos" (las ortofotos comprimidas con el compresor terminan en `_cog` y no siempre traen `ortho/rgb`). Antes `hcda_daniela_antonela_cog` caía en "Otros rasters".
  - Para el comparador temporal: la fecha de vuelo debe venir del campo **Date** de GeoNode (no del nombre); para haciendas homónimas, un keyword `hacienda:<nombre>` servirá de override explícito.
- **Fix vista inicial:** antes el zoom a haciendas no aplicaba porque `updateUrlState` persistía la vista (lat/lng) en cada movimiento y al recargar `parseUrlState` restauraba ese Ecuador. Ahora `updateUrlState` persiste SOLO las capas activas (param `l`); la vista entra a la URL únicamente desde el botón Compartir, con marcador `s=1`. `parseUrlView` solo respeta la vista si hay `s=1` → URLs viejas se ignoran y el load normal siempre encuadra las 22 haciendas.

### Pendiente de las siguientes fases

- Pestañas superiores (Cartografía / Ortofoto / Multiespectral); Meteo GFS queda como categoría dentro de Cartografía.
- Ortofoto Haciendas con comparador temporal (depende de cargar ortofotos con hacienda+fecha → tabla `ortomosaico`).
- Compresor COG-JPEG (página Python subir→comprimir→descargar, JPEG visualmente sin pérdida) para habilitar la carga de ortofotos pesadas.
- Multiespectral: panel placeholder; índices (NDVI/NDRE/SAVI…) replicando fórmulas de WebODM con rasterio+numexpr cuando haya data multiespectral (requiere banda NIR).

---

## Stepper temporal para capas WMS de GFS — 2026-05-31

Las capas WMS de GFS dejaron de mostrar solo el paso por defecto: ahora se puede recorrer el pronóstico paso a paso. **Decisión de diseño:** stepper discreto (no slider en vivo). Análisis previo: un slider que re-pide WMS por tick da mal UX (lag/parpadeo); con nuestra subregión diminuta (~225 puntos, ~0.2s/tile) un stepper con prefetch del vecino es instantáneo y barato. Se descartó el slider animado por ahora (se puede montar encima reusando el cache si se quiere animación tipo Windy).

### API (`services/ingest_ws/app/routers/gfs.py`)

- Nuevo `GET /api/v1/gfs/times` → `{times:[ms], default_index}` (40 pasos; `default_index` = paso más cercano al momento actual). Lee `valid_time` del NetCDF de superficie.

### Frontend (`services/ingest_ws/static/index.html`)

- Stepper **◀ / ▶** + etiqueta de hora del pronóstico en la cabecera de la categoría 🌦 Meteorología GFS (global: mueve todas las capas GFS activas al mismo tiempo).
- Cambiar de paso re-tilea las capas vía `map.getSource().setTiles([url+time])` (sin recrear el layer) y dispara **prefetch ligero del cuadro vecino** (1 imagen al bbox actual, 256px) para que el siguiente paso sea instantáneo.
- Las capas GFS se añaden con el paso seleccionado (`withGfsTime`); compatible con el cambio de mapa base.

---

## Perfil vertical: viento por altura + sincronizado al cursor — 2026-05-31

El perfil vertical dejó de ser un snapshot fijo a +24h con solo T/HR. Ahora muestra **viento por altura** y se **sincroniza con el cursor temporal** del pronóstico de superficie.

### Pipeline GFS (`services/gfs_scheduler/download_gfs.py`)

- `gfspgrb20p25_vert.nc` ahora baja **f003..f120 cada 3h (40 pasos)** en vez de solo f024, y agrega **UGRD/VGRD** (viento) a los 6 niveles de presión además de TMP/RH. `VERT_KEEP = {t, r, u, v}`.

### API (`services/ingest_ws/app/routers/gfs.py`)

- `GET /api/v1/gfs/profile` reestructurado: devuelve `times[]` (40, alineados con `/point`) y `profiles[]`, un perfil por tiempo con `t_celsius`, `rh_pct`, `wspd`, `wdir` por nivel. Calcula velocidad/dirección desde u/v igual que en superficie. Robusto al formato viejo (snapshot único sin viento → `times=[ts]`, wspd/wdir vacíos).

### Frontend (`services/ingest_ws/static/index.html`)

- El perfil se descarga una vez (todos los tiempos) y se cachea (`profData`); al mover el cursor sobre el gráfico de pronóstico (`updateAxisPointer`) salta al perfil del tiempo más cercano (`nearestProfIdx` → `renderProfileAt`), sin refetch. El título muestra la fecha/hora del perfil mostrado.
- Viento por nivel en una **columna propia (grid separado a la derecha)**: flechas rotadas por dirección, tamaño por velocidad, etiqueta con m/s. Tooltip por nivel con T/HR/viento.

---

## Capas WMS de GFS en el sidebar — 2026-05-31

Las variables del modelo GFS (descargadas por `agrotec_gfs_scheduler` y servidas por THREDDS/ncWMS) ahora son **capas activables** en el geovisor, no solo accesibles vía clic puntual.

### Backend

- **Nuevo `services/ingest_ws/app/gfs_layers.py`** — define 5 capas meteo y construye sus URLs WMS contra el proxy `/thredds/wms/testAll/actual/modelos/gfspgrb20p25.nc`:
  - `t2m` Temperatura 2 m (raster · div-RdYlBu-inv · 288–306 K)
  - `u10:v10-group` Viento 10 m (vectores) — flechas coloreadas+dimensionadas por magnitud, fondo transparente (`colored_sized_arrows` · seq-YlGnBu · 0–15 m/s). _Nota 2026-05-31: cambiado de `vector_arrows` (que rellenaba el fondo de magnitud, 100% opaco) a `colored_sized_arrows` (solo flechas, ~2% opaco) a pedido — vectores limpios sobre el mapa._
  - `r2` Humedad relativa (raster · seq-Blues · 0–100 %)
  - `prate` Precipitación (raster · seq-PuBu · 0–~4 mm/h)
  - `sdswrf` Radiación solar (raster · seq-Heat · 0–1100 W/m²)
  - GetMap en `version=1.1.1 / SRS=EPSG:3857 / bbox={bbox-epsg-3857}` para que MapLibre las consuma como raster tiles. Bbox WGS84 leído del NetCDF (`xarray`) y cacheado (`lru_cache`), con fallback a la subregión Ecuador.
  - `legend_url` vía `GetLegendGraphic` de ncWMS (colorbar vertical con la escala).
- **`app/routers/layers.py`** — `GET /api/v1/layers` ahora **anexa** las capas GFS (categoría `meteorologia`) tras las de GeoNode, aplicando la misma lógica de `VisorLayerConfig` (visible/featured/order/opacidad). Así el admin las oculta/destaca/reordena desde el modal ⚙ igual que cualquier otra. Opacidad por defecto 0.75. Alternate sintético `gfs:<var>`.

### Frontend (`services/ingest_ws/static/index.html`)

- Nueva categoría **🌦 Meteorología GFS** en el sidebar (`CAT_LABELS`).
- **Leyenda de color inline** debajo de cada capa meteo activa (imagen `GetLegendGraphic`), con estilos `.legend-row`/`.legend-img`. Reutiliza toda la maquinaria existente (toggle, opacidad, z-order, fit, URL state compartible).

### Notas

- Las capas muestran el **paso temporal por defecto** del modelo (análisis/f000). El NetCDF tiene 40 pasos → pendiente futuro: time-slider para animar el pronóstico.
- La leyenda de temperatura va en **Kelvin** (ncWMS no convierte unidades en WMS); el valor en °C sigue disponible en el panel meteo al hacer clic.

---

## Rebrand dominio — 2026-05-18 (tarde)

- Dominio del sistema migrado de `agrotec.desarrollowebsite.com` → `idepalma.desarrollowebsite.com` (rename limpio, sin redirect).
- **Fixes post-rename necesarios** (URLs persistidas en BD del catálogo y configs internas que no se autoactualizan al cambiar SITEURL):
  - `UPDATE base_resourcebase/base_link/layers_dataset SET ... = REPLACE(..., agrotec, idepalma)` — **281 filas** con URLs absolutas hacia el dominio viejo (thumbnails, WMS/WFS links de cada dataset, ows_url).
  - `PUT /geoserver/rest/settings` con `proxyBaseUrl = https://idepalma.desarrollowebsite.com/geoserver` — antes apuntaba a un subpath legacy `/agrotec-geonode/geoserver` que ensuciaba GetCapabilities.
  - `UPDATE oauth2_provider_application SET redirect_uris = '... new domain ...'` + `DELETE FROM oauth2_provider_accesstoken/refreshtoken/grant` + `DELETE FROM django_session` — tokens y sesiones invalidadas al cambiar SITEURL, causaban 401 perpetuo en `/api/o/v4/userinfo`.
  - **`HTTP_PORT=8085 → 80` y `HTTPS_PORT=8445 → 443`** en `bk/.env` — MapStore inyectaba ese puerto en las URLs absolutas que pedía proxear (`/proxy/?url=https://idepalma...:8085/api/v2/resources`), causando timeouts (499) y dejando el catálogo "loading" para siempre. El puerto interno solo es accesible por localhost del host, no por el dominio público.
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
