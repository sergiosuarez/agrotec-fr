# Migración a servidor del cliente — Backup, transferir, restaurar

Procedimiento para mover Agrotec (todo o partes) entre servidores. Aplica para:
- Migración a un servidor del cliente final
- Réplica para staging/testing
- Backup periódico

---

## ¿Qué hay que respaldar?

| Componente | Tipo | Volumen / archivo | Frecuencia sugerida |
|---|---|---|---|
| **Catálogo GeoNode** | BD PostgreSQL | `agrotec-dbdata` | diaria |
| **Capas raster/vector** | Filesystem | `agrotec-data` + `agrotec-gsdatadir` + `agrotec-statics` | diaria |
| **Configuración GeoServer** | Filesystem | `agrotec-gsdatadir` | diaria (junto con capas) |
| **BD visor (haciendas, parcelas)** | BD PostgreSQL | `agrotec-fr-dbdata` | diaria |
| **NetCDF GFS** | Filesystem | `agrotec-fr-gfsdata` | NO (se regenera cada 6h) |
| **Mergin proyectos** | Filesystem | `mergin-projects` | diaria |
| **Mergin DB** | BD PostgreSQL | `mergin-pgdata` | diaria |
| **Archivos `.env`** | Texto | `bk/.env`, `fr/.env`, `mobile/mergin-server/.env` | una vez (manualmente al gestor de secretos) |
| **Imágenes Docker** | Docker | (cualquier registry público) | no necesario, el cliente las baja |

---

## Backup automatizado

El script `scripts/backup.sh` empaca todo en un solo `.tar.gz`:

```bash
sudo /opt/agrotec/fr/scripts/backup.sh /backup/agrotec-$(date +%F).tar.gz
```

Hace internamente:

1. `pg_dump` de las 4 bases (geonode, geonode_data, agrotecdb, mergin)
2. Snapshot de los volúmenes con `docker run --rm -v VOL:/d alpine tar`
3. Combina en un único archivo con manifiesto

**Tamaño esperado** (con set inicial 4 ortomosaicos + 1 día GFS):
- Sin capas grandes: ~50 MB
- Con 4 ortomosaicos AP_TEMP: ~120 MB

### Crontab recomendado

```bash
# Backup diario a las 3 AM, rota dejando 14 días
0 3 * * * /opt/agrotec/fr/scripts/backup.sh /backup/agrotec-$(date +\%F).tar.gz >> /var/log/agrotec-backup.log 2>&1
0 4 * * * find /backup -name "agrotec-*.tar.gz" -mtime +14 -delete
```

---

## Restaurar en el servidor del cliente

### Paso 1 — Sistema base + stacks levantados

Seguir [DESPLIEGUE.md](./DESPLIEGUE.md) hasta el **Paso 4.2**. Los stacks deben estar Up con la BD **vacía** (no hagas el Paso 7 de import de capas, vamos a restaurar el dump).

### Paso 2 — Apagar servicios (no la DB)

```bash
cd /opt/agrotec/bk && docker compose stop django celery geoserver
cd /opt/agrotec/fr && docker compose stop visor
```

### Paso 3 — Restaurar

```bash
sudo /opt/agrotec/fr/scripts/restore.sh /ruta/al/backup.tar.gz
```

El script:
1. Verifica el manifiesto
2. Restaura las 4 BDs (`psql -f`)
3. Restaura los volúmenes (`tar -xz`)
4. Pide confirmación antes de cada paso

### Paso 4 — Reiniciar

```bash
cd /opt/agrotec/bk && docker compose up -d
cd /opt/agrotec/fr && docker compose up -d
cd /opt/agrotec/fr/mobile/mergin-server && docker compose up -d
```

### Paso 5 — Verificar

```bash
curl -sk https://agrotec.dominio.com/api/v1/ortomosaicos?sync=true | python3 -m json.tool | head
# Debe listar las capas que tenías
```

---

## Migración entre servidores

Caso de uso: tienes Agrotec corriendo en server A y necesitas moverlo a server B.

```bash
# --- En server A ---
/opt/agrotec/fr/scripts/backup.sh /tmp/agrotec-bundle.tar.gz
scp /tmp/agrotec-bundle.tar.gz user@server-B:/tmp/

# --- En server B (con DESPLIEGUE.md hasta paso 4.2 hecho) ---
/opt/agrotec/fr/scripts/restore.sh /tmp/agrotec-bundle.tar.gz
```

**Lo que NO se transfiere automáticamente:**
- DNS — actualizar A record al IP de server B
- Certs TLS — re-emitir con certbot en server B
- Crontabs — replicar manualmente

---

## Backup parcial — solo capas raster

Si solo quieres mover las capas (sin migrar todo el sistema):

```bash
# En el origen
docker exec django4agrotec sh -c "tar czf /tmp/raster-capas.tar.gz /mnt/volumes/statics/uploaded/"
docker cp django4agrotec:/tmp/raster-capas.tar.gz /tmp/

# En el destino
docker cp /tmp/raster-capas.tar.gz django4agrotec:/tmp/
docker exec django4agrotec sh -c "cd / && tar xzf /tmp/raster-capas.tar.gz"
# Reiniciar GeoNode para que reconozca los archivos
docker compose restart django celery geoserver
```

> Esto **no migra los metadatos** (título, descripción, permisos). Si los necesitas, hacer dump de la BD `geonode`.

---

## Estrategia de archivado a largo plazo

Para datos históricos (ortomosaicos de años pasados que ya no necesitas servir):

1. **Mover capas a "archivado"** desde GeoNode admin
2. Backup separado:
   ```bash
   docker exec django4agrotec sh -c "tar czf /tmp/archivo-2025.tar.gz /mnt/volumes/statics/uploaded/2025/"
   docker cp django4agrotec:/tmp/archivo-2025.tar.gz /backup/historico/
   ```
3. Eliminar del catálogo activo (libera disco)
4. Si se necesita restaurar: importar de nuevo con `manage.py importlayers`

---

## Lo que NO debe respaldarse (es regenerable o sensible)

| Item | Por qué no |
|---|---|
| Imágenes Docker (`agrotec-fr-visor`, etc.) | Se reconstruyen con `docker compose build` |
| NetCDF GFS (`agrotec-fr-gfsdata`) | Se regeneran cada 6h automáticamente |
| Logs (`/var/log/`, `docker logs`) | Útil solo para debug puntual |
| `__pycache__/`, `.pytest_cache/` | Caches Python |

---

## Backup del servidor del proveedor (Contabo, etc.)

**No depender solo del backup de Agrotec.** Activar el snapshot diario del proveedor de hosting:
- Contabo: incluye 1 snapshot gratis en planes VPS
- DigitalOcean / Vultr / Hetzner: $5-10/mes adicional

Esto te protege contra:
- Borrado accidental del disco completo
- Compromiso del root (ransomware)
- Errores en restore que no detectaste

---

## Comandos rápidos útiles

```bash
# Ver tamaño actual de cada volumen
for v in $(docker volume ls -q | grep -E "agrotec|mergin"); do
    size=$(docker run --rm -v "$v":/d alpine du -sh /d 2>/dev/null | cut -f1)
    printf "  %-35s %s\n" "$v" "$size"
done

# Top 10 capas más pesadas en GeoNode
docker exec db4agrotec psql -U geonode -d geonode_data -c \
    "SELECT pg_size_pretty(pg_relation_size(c.oid)) as size, c.relname
     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r'
     ORDER BY pg_relation_size(c.oid) DESC LIMIT 10;"

# Espacio en uso de Docker
docker system df
```
