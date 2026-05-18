# Guía del geovisor IDEPalma — Usuario final

Cómo usar el visor web `https://agrotec.desarrollowebsite.com/visor/`.

> Versión v2: capas categorizadas, popups vectoriales, panel meteorológico GFS interactivo, admin de visibilidad/orden, URL compartible.

---

## Layout

```
┌─────────────────────┬─────────────────────────────────────────┐
│ 🌱 IDEPalma         │ [⊕ Fit] [↻ Reset] [🌦 GFS]              │
│ Geovisor PALMAR     │                                         │
│ ─────────────       │                                         │
│ [🔍 Buscar…]        │                                         │
│ [Capas|Base|Estado] │                MAPA (MapLibre)          │
│                     │                                         │
│ ▼ 🛩 Ortomosaicos(7)│   Click vector  → popup con atributos   │
│   ☑ vuelo1_placa27  │   Shift+click   → panel meteo GFS       │
│   ☐ vuelo2_placa27  │                                         │
│                     │                                         │
│ ▼ 🌾 Haciendas (1)  │                                         │
│   ☑ haciendas_palmar│                                         │
│                     │                                         │
│ ▶ 🗺 Límites (3)    │ ◄── (categoría colapsada)               │
│                     │                                         │
│ [🔗 Compartir] [⚙]  │ -2.7° -79.7° — zoom 14.2                │
└─────────────────────┴─────────────────────────────────────────┘
```

El botón `‹` flotante en el borde del sidebar lo colapsa por completo. Click en `›` lo vuelve a desplegar.

---

## Capas

### Activar/desactivar
Click en el checkbox a la izquierda del nombre de la capa. Las **destacadas** (marca verde a la izquierda) salen activadas automáticamente al cargar el visor.

### Cambiar opacidad y z-order
Al activarse, debajo aparece un slider de opacidad. Para capas activas también aparecen flechas **▲ / ▼** que suben/bajan el orden de superposición (útil cuando un polígono grande tapa otra capa).

### Centrar el mapa en una capa
Botón **⊕** al lado de cada capa → el mapa hace zoom al bbox de la capa.

### Categorías colapsables
Click en el header de cualquier categoría (`🛩 Ortomosaicos drone`, `🌾 Haciendas y lotes`, etc.) para colapsar/expandir. Útil cuando hay muchas capas.

### Buscar
Caja de búsqueda en el tope del sidebar — filtra por nombre o alternate.

---

## Popups (capas vectoriales)

Click sobre un polígono/línea/punto vectorial → aparece un popup con todos los atributos de ese feature. Los rasters no responden a click (no tienen atributos por feature).

El popup usa `GET /api/v1/feature-info?layer=…&lat=…&lng=…` con una tolerancia de ~50 m alrededor del clic.

---

## Mapa base

Tab **Mapa base** → tres opciones:
- **OpenStreetMap** (default)
- **Satélite (Esri World Imagery)** — imagen aérea de alta resolución
- **Mapa claro (Carto)** — sobrio, ideal para impresión

Cambiar el base no afecta las capas activas.

---

## Panel meteorológico GFS

Dos formas de abrirlo:
- Botón **🌦 GFS** en la toolbar → centro actual del mapa
- **Shift + click** en cualquier punto del mapa → ese punto

El panel se desliza desde abajo y ocupa el 75% / 25% del ancho:

### 75% — Pronóstico horario (5 días)

Gráfico con cinco series:
- **Temperatura** (°C, línea roja)
- **Humedad relativa** (%, línea azul)
- **Lluvia** (mm/h, barras celestes)
- **Solar** (W/m², área amarilla)
- **Viento a 10 m** (flechas verdes en la barra inferior — la rotación indica dirección, el tamaño indica velocidad)

Hover sobre cualquier instante → tooltip unificado con los 5 valores y la hora exacta. Click en la leyenda para apagar/prender series.

### 25% — Perfil vertical (snapshot +24 h)

Temperatura y humedad relativa en 6 niveles de presión (1000, 925, 850, 700, 500, 300 hPa). Snapshot a +24 h del último ciclo GFS. El eje Y son las hPa, eje X-bottom es Temp (rojo), eje X-top es HR (azul).

> **Nota:** el viento en altura aún **no** está disponible (solo el de 10 m). Requiere extender el descargador GFS para traer `UGRD/VGRD` en niveles isobáricos.

---

## Compartir vista

Botón **🔗 Compartir vista** → copia al portapapeles la URL con el estado actual codificado en query string (`?l=alt1,alt2&z=15&lat=…&lng=…`). Cualquier persona que abra esa URL verá exactamente el mismo mapa.

---

## Admin del visor (botón ⚙)

Solo para administradores del sistema. Modal con tabla de **todas** las capas (incluso las marcadas como ocultas):

| Columna | Qué hace |
|---|---|
| **Visible** | Si está apagado, la capa **no aparece** en el sidebar (queda oculta para los usuarios). Útil para retirar provisionalmente capas en pruebas o duplicadas. |
| **Destacada** | Si está prendida, la capa se **auto-activa** al cargar el visor (sale prendida por defecto). No afecta si aparece o no en la lista. |
| **Orden** | Número usado para ordenar el listado del sidebar (menor → más arriba). |

Cambios se guardan automáticamente al cambiar cada campo. Al cerrar el modal el sidebar se refresca.

Las filas de capas marcadas como `visible=false` aparecen atenuadas para diferenciarlas.

---

## Estado de servicios

Tab **Estado** → estado en vivo de los componentes:

| Servicio | Verde si... |
|---|---|
| `db` | Base de datos del visor responde |
| `geonode` | GeoNode upstream está vivo |
| `thredds` | THREDDS upstream está vivo |

También lista los NetCDF disponibles en el volumen GFS con su tamaño y fecha de última actualización.

---

## Navegación del mapa

- **Pan**: clic y arrastra
- **Zoom**: scroll del mouse, o `+` / `-` del teclado, o doble-clic
- **Rotar**: Ctrl + arrastrar
- **Tilt (3D)**: Ctrl + click derecho + arrastrar
- **Coordenadas en vivo**: esquina inferior izquierda (sube automáticamente al abrir el panel meteo para no taparse)

---

## Para administradores

Para **agregar** nuevas capas al sistema, usar GeoNode admin (`https://agrotec.desarrollowebsite.com/`):

1. Subir el archivo (TIFF para raster, SHP/GPKG para vector) desde `Datasets → Cargar nuevo dataset`
2. Asignar título y publicar
3. La capa aparece automáticamente en el sidebar del visor en el próximo reload

Si la capa no debe ser visible aún para los usuarios, abrir el visor → ⚙ Admin → desmarcar **Visible** en esa fila.

Para los ortomosaicos drone grandes (>500 MB), ver `bk/docs/INSTRUCTIVO_SUBIR_CAPAS.md` — explica cómo convertir a COG-JPEG primero para reducir 10× el tamaño manteniendo calidad visual.

---

## Solución de problemas

**El visor no carga**
1. Refrescar con `Ctrl + Shift + R` (bypassea cache)
2. Abrir consola del navegador (`F12 → Console`) y reportar errores al admin
3. Verificar `https://agrotec.desarrollowebsite.com/health` → debe responder JSON con `status: ok`

**Una capa nueva no aparece en el sidebar**
1. Verificar en GeoNode admin que esté publicada (no en draft)
2. Abrir ⚙ Admin del visor → confirmar que **Visible** está marcado
3. Forzar refresh del listado con `Ctrl + F5`

**El popup vectorial sale vacío**
1. Click cayó fuera del polígono (margen de tolerancia ~50 m a esa latitud)
2. La capa fue publicada como WMS pero no como WFS — pedir al admin que verifique en GeoServer
