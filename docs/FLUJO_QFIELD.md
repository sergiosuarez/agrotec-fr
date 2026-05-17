# Flujo QField — Visualización offline en campo

**Alcance MVP** (decisión del Ing. Juan Carlos Pindo M., 2026-05-17):
> "Por ahora solamente carga de archivos y visualización. No se considera levantamiento de datos con dispositivos en campo en tiempo real."

Es decir: los técnicos en campo **descargan** un paquete con los ortomosaicos y capas, los **visualizan** offline, y **no capturan datos** (eso queda para una fase posterior).

---

## Componentes del flujo

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  ADMIN (oficina)    │     │  Mergin Maps      │     │  TECNICO (campo) │
│                     │     │  server           │     │                  │
│  • QGIS Desktop     │ ──► │  mergin.dominio   │ ──► │  • QField        │
│  • Crea proyecto    │     │  .com             │     │    (Android/iOS) │
│    QGIS con capas   │     │                   │     │  • Clona proyecto│
│    Agrotec          │     │  Almacena         │     │  • Visualiza sin │
│  • Empaqueta para   │     │  proyectos +      │     │    internet      │
│    offline          │     │  versiones        │     │                  │
│  • Sube a Mergin    │     │                   │     │                  │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
```

---

## Paso 1 — Crear el proyecto QGIS (oficina, una vez)

### 1.1 Instalar plugin Mergin Maps

En QGIS (>= 3.22):

`Complementos > Administrar e instalar > Buscar "Mergin Maps" > Instalar`

### 1.2 Conectar el plugin a tu servidor

En la barra Mergin (panel lateral):
- **Server URL**: `https://mergin.dominio.com`
- **Username** / **Password**: las credenciales que el admin te dio (ver `CREDENCIALES.md`)

Click en **Login**.

### 1.3 Crear proyecto QGIS con capas Agrotec

Nuevo proyecto QGIS (`Proyecto > Nuevo`). Agregar capas:

**A) Ortomosaicos como WMS** (en línea, no offline):

`Capa > Agregar capa > Agregar capa WMS/WMTS`
- New connection:
  - Nombre: `Agrotec WMS`
  - URL: `https://agrotec.dominio.com/geoserver/ows`
- Connect → ves la lista de capas → seleccionar `geonode:ap_temp_1_1`, etc. → Add.

**B) Ortomosaicos como GeoTIFF (para offline real)**:

Descargar primero los `.tif` desde el servidor:
```bash
# En el servidor:
docker exec django4agrotec sh -c "cd /tmp && tar czf /tmp/orthos.tar.gz import_batch/"
docker cp django4agrotec:/tmp/orthos.tar.gz /tmp/
```

O usando la API:
```
GET https://agrotec.dominio.com/api/v1/ortomosaicos?sync=true
# La respuesta tiene 'wms_url'; para descargar el raster original
# usar el GeoServer endpoint /geoserver/ows con request=GetMap (no recomendado para tamaños grandes)
```

> **Mejor**: usar `MBTiles` (siguiente sección).

**C) Capa de parcelas** (cuando se hayan creado):

`Capa > Agregar capa > Agregar capa PostGIS`
- Host: `agrotec.dominio.com` (o IP del servidor)
- Database: `agrotecdb`
- User / Password: del `CREDENCIALES.md`
- Tabla: `parcela` (o `lote`, `hacienda`)

> **OJO**: el puerto 5432 del PostGIS del visor **no está expuesto al exterior** por seguridad. Para acceso desde QGIS desktop, opciones:
> 1. Acceso via WireGuard (recomendado)
> 2. Abrir temporal 55433 en UFW solo desde la IP del cliente
> 3. Crear un servicio WFS en GeoServer que exponga las tablas

### 1.4 Convertir ortomosaicos a MBTiles (para offline)

QField **no soporta WMS offline**. Hay que pre-generar tiles raster en formato MBTiles:

```bash
# En el servidor (o en tu laptop con gdal-bin):
mkdir -p /tmp/mbtiles
for f in /root/DATA/AP_TEMP_*.tif; do
    base=$(basename "$f" .tif)
    gdal_translate -of MBTILES \
        -co BLOCKSIZE=512 -co QUALITY=85 -co TILE_FORMAT=JPEG \
        "$f" "/tmp/mbtiles/${base}.mbtiles"
    # Pyramids (zoom levels) - acelera el rendering en QField
    gdaladdo "/tmp/mbtiles/${base}.mbtiles" 2 4 8 16 32
done
ls -lh /tmp/mbtiles/
# Aprox 4-6 MB por ortomosaico de 100MP. Bajan ~95% del original.
```

Cada `.mbtiles` es un único archivo SQLite portable.

En QGIS desktop:

`Capa > Agregar capa > Agregar capa Raster` → seleccionar `*.mbtiles`.

### 1.5 Guardar el proyecto en el servidor Mergin

`Proyecto > Guardar como` → guarda como `.qgz` (proyecto comprimido).

**Crear proyecto Mergin** (panel Mergin):
1. Click en `+ Create new project`
2. Workspace: `admin` (o el username)
3. Project name: `agrotec-temp-haciendas-2026Q2` (convención: cliente-proyecto-fecha)
4. Visibility: `Private`
5. Path local: la carpeta donde tienes el `.qgz` + los `.mbtiles`

Mergin sincronizará el proyecto: subirá el `.qgz` + todos los archivos asociados (incluyendo los MBTiles).

> **Importante**: archivos grandes pueden tardar. MBTiles de 5 MB suben en segundos; un proyecto con GeoTIFF originales (cientos de MB) puede tardar varios minutos.

---

## Paso 2 — Compartir el proyecto con los técnicos

En la web de Mergin (`https://mergin.dominio.com`):

1. Login con tu cuenta admin
2. Ir al proyecto → **Permissions** → Add usuario → permisos: `Reader` (solo lectura, suficiente para visualización)
3. Crear cuentas para los técnicos si no existen:
   ```bash
   docker exec mergin_server flask user create \
       --email tecnico1@cliente.com tecnico1 'PasswordTecnico1!'
   ```

---

## Paso 3 — Instalar y conectar QField (técnico, una vez)

En el celular Android del técnico:

1. **Play Store**: instalar **QField for QGIS** (oficial, gratis, `org.qgis.qfield`)
2. Abrir QField
3. `Open project` → tab **Mergin Maps**
4. Click en **Sign in**:
   - Server URL: `https://mergin.dominio.com`
   - Username / Password: lo que le diste
5. Aparecerá la lista de proyectos a los que tiene acceso

---

## Paso 4 — Clonar proyecto a campo (técnico)

1. En QField, lista de proyectos Mergin → tap en `agrotec-temp-haciendas-2026Q2`
2. Botón **Clone project** → descarga el `.qgz` + todos los MBTiles + capas
3. Espera (5-30 min según tamaño, **una vez con WiFi recomendado**)
4. Cuando termina: tap en el proyecto → se abre el mapa

> A partir de aquí, **el celular puede estar sin internet**: el proyecto vive localmente.

---

## Paso 5 — Visualización en campo (técnico, repetido)

En QField, ya con el proyecto abierto:

- **GPS**: si el celular tiene GPS habilitado, QField muestra el cursor donde estás
- **Pan / Zoom**: gestos táctiles estándar (1 dedo arrastra, 2 dedos zoom)
- **Toggle capas**: ícono de capas (esquina superior) → activar/desactivar
- **Identificar feature** (en capas vectoriales): tap largo → ver atributos
- **Medir**: herramientas de medida (regla, polígono)

### Lo que **NO** se puede en este MVP

- ❌ Editar geometrías
- ❌ Agregar puntos / fotos georeferenciadas
- ❌ Sincronizar de vuelta al servidor

Si en el futuro se agrega captura de datos, hay que:
1. Habilitar capas editables en el proyecto QGIS (.qgz)
2. Subir el proyecto actualizado a Mergin
3. Re-clonar en QField (o sincronizar desde el técnico → servidor)

---

## Mantenimiento

### Actualizar el proyecto cuando hay capas nuevas

**Admin** (oficina):

1. Abre el `.qgz` en QGIS
2. Agrega/quita capas
3. `Mergin > Sync project` → sube cambios

**Técnico** (campo):

1. Abre QField
2. Tab Mergin → el proyecto aparece con badge **Sync available**
3. Tap → **Sync** (requiere internet) → descarga los cambios

### Backup del servidor Mergin

```bash
# Backup del volumen de proyectos
docker run --rm -v mergin-projects:/d -v $(pwd):/b alpine \
    tar czf /b/mergin-projects-$(date +%F).tar.gz /d

# Backup de la BD
docker exec mergin_db pg_dump -U mergin mergin > /tmp/mergin-db-$(date +%F).sql
```

Ver [MIGRACION_CLIENTE.md](./MIGRACION_CLIENTE.md) para el backup completo.

---

## Troubleshooting

### "Cannot connect to server" en QField

- Verifica que el técnico tiene **internet** (necesario solo para login y clone/sync)
- Verifica que la URL es exactamente `https://mergin.dominio.com` (sin trailing slash)
- Probar desde un navegador `https://mergin.dominio.com/ping` → debe responder JSON

### Tiles del ortomosaico no se ven en QField (cuadros vacíos)

Casi siempre: las capas son WMS (online) y el celular no tiene internet. Solución:

1. **Admin**: regenerar el proyecto QGIS con capas **MBTiles** en lugar de WMS
2. **Técnico**: re-clonar el proyecto

### "Out of memory" al clonar proyecto grande

- Liberar espacio en el celular (necesario ~3x el tamaño del proyecto)
- Reducir resolución de MBTiles regenerando con menos zoom levels:
  ```bash
  gdal_translate -of MBTILES -outsize 50% 50% ...
  ```

### El admin agregó una capa pero el técnico no la ve

Falta que el admin haya hecho `Mergin > Sync project` Y que el técnico haga `Sync` en QField.

---

## Referencias

- [QField docs oficial](https://docs.qfield.org/)
- [Mergin Maps docs](https://merginmaps.com/docs)
- [Sample QGIS projects para QField](https://docs.qfield.org/get-started/sample-projects/)
