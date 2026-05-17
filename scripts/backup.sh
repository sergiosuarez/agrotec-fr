#!/usr/bin/env bash
# backup.sh — Snapshot completo de Agrotec en un solo .tar.gz
#
# Respalda:
#   - 4 bases PostgreSQL (geonode, geonode_data, agrotecdb, mergin)
#   - 7 volúmenes Docker (statics, gsdatadir, data, dbbackups, fr-dbdata, mergin-projects, mergin-pgdata)
#   - Manifest con timestamp y versiones
#
# NO respalda: imágenes Docker, NetCDF GFS (se regenera), .env (deben estar en gestor de secretos)
#
# Uso:
#   ./scripts/backup.sh /backup/agrotec-$(date +%F).tar.gz
#
# Restaurar con: scripts/restore.sh /ruta/al/backup.tar.gz

set -euo pipefail

OUT="${1:?Uso: $0 /ruta/archivo.tar.gz}"
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
WORK=$(mktemp -d)
trap "rm -rf '$WORK'" EXIT

err() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[backup] $*"; }

mkdir -p "$WORK/dbs" "$WORK/volumes"

# --- 1. Dumps de PostgreSQL ---

dump_db() {
    local container="$1" user="$2" dbname="$3" out_file="$4"
    if ! docker ps --format '{{.Names}}' | grep -q "^$container\$"; then
        log "  WARN: $container no esta corriendo, salto $dbname"
        return
    fi
    log "  pg_dump $container::$dbname"
    docker exec "$container" pg_dump -U "$user" -Fc "$dbname" > "$out_file"
}

log "Dumps PostgreSQL..."
dump_db "db4agrotec"  "postgres"    "geonode"      "$WORK/dbs/geonode.dump"
dump_db "db4agrotec"  "postgres"    "geonode_data" "$WORK/dbs/geonode_data.dump"
dump_db "agrotec_db"  "agrotecuser" "agrotecdb"    "$WORK/dbs/agrotecdb.dump"
dump_db "mergin_db"   "mergin"      "mergin"       "$WORK/dbs/mergin.dump"

# --- 2. Snapshots de volúmenes ---

snapshot_vol() {
    local vol="$1" out_file="$2"
    if ! docker volume ls --format '{{.Name}}' | grep -q "^$vol\$"; then
        log "  WARN: volumen $vol no existe, salto"
        return
    fi
    log "  tar volumen $vol"
    docker run --rm -v "$vol":/d -v "$WORK/volumes":/out alpine \
        sh -c "cd / && tar czf /out/$out_file -C / d 2>/dev/null"
}

log "Snapshots de volúmenes..."
snapshot_vol "agrotec-statics"        "agrotec-statics.tar.gz"
snapshot_vol "agrotec-gsdatadir"      "agrotec-gsdatadir.tar.gz"
snapshot_vol "agrotec-data"           "agrotec-data.tar.gz"
snapshot_vol "agrotec-fr-dbdata"      "agrotec-fr-dbdata.tar.gz"
snapshot_vol "mergin-projects"        "mergin-projects.tar.gz"
snapshot_vol "mergin-pgdata"          "mergin-pgdata.tar.gz"

# --- 3. Manifest ---

cat > "$WORK/MANIFEST.txt" <<EOF
Agrotec backup
==============
generated_at:   $TS
host:           $(hostname)
script_version: 1.0

Contenido:
EOF
(cd "$WORK" && find dbs volumes -type f -exec ls -la {} \; | awk '{print "  "$5"  "$9}') >> "$WORK/MANIFEST.txt"

# --- 4. Empaquetar ---

log "Empaquetando -> $OUT"
mkdir -p "$(dirname "$OUT")"
tar czf "$OUT" -C "$WORK" .

SIZE=$(du -h "$OUT" | cut -f1)
log "OK: $OUT ($SIZE)"
