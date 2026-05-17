#!/usr/bin/env bash
# restore.sh — Restaura un backup hecho con backup.sh.
#
# IMPORTANTE: antes de correr este script, asegurate de:
#   1. Haber clonado y levantado los stacks (DESPLIEGUE.md hasta el Paso 4.2)
#   2. Las BD estan VACIAS (sin tablas de Agrotec aun)
#   3. Los servicios consumidores estan detenidos (django, celery, visor, mergin_server)
#
# Uso:
#   ./scripts/restore.sh /ruta/al/backup.tar.gz

set -euo pipefail

IN="${1:?Uso: $0 /ruta/archivo.tar.gz}"
[ -f "$IN" ] || { echo "ERROR: $IN no existe" >&2; exit 1; }

WORK=$(mktemp -d)
trap "rm -rf '$WORK'" EXIT

log() { echo "[restore] $*"; }

# --- 1. Extraer ---

log "Extrayendo $IN ..."
tar xzf "$IN" -C "$WORK"

if [ -f "$WORK/MANIFEST.txt" ]; then
    log "Contenido del backup:"
    sed 's/^/   /' "$WORK/MANIFEST.txt"
fi

read -r -p "Continuar con la restauracion? (escribe 'si'): " ANS
[ "$ANS" = "si" ] || { log "cancelado"; exit 0; }

# --- 2. Restaurar bases ---

restore_db() {
    local container="$1" user="$2" dbname="$3" dump_file="$4"
    if [ ! -f "$dump_file" ]; then
        log "  WARN: $dump_file no existe en el backup, salto"
        return
    fi
    if ! docker ps --format '{{.Names}}' | grep -q "^$container\$"; then
        log "  ERROR: $container no esta corriendo. Levantalo y reintenta."
        exit 1
    fi
    log "  restaurar $container::$dbname"
    docker exec "$container" psql -U "$user" -d postgres \
        -c "DROP DATABASE IF EXISTS \"$dbname\";"
    docker exec "$container" psql -U "$user" -d postgres \
        -c "CREATE DATABASE \"$dbname\";"
    docker exec -i "$container" pg_restore -U "$user" -d "$dbname" \
        < "$dump_file"
}

log "Restaurando bases..."
restore_db "db4agrotec"  "postgres"    "geonode"      "$WORK/dbs/geonode.dump"
restore_db "db4agrotec"  "postgres"    "geonode_data" "$WORK/dbs/geonode_data.dump"
restore_db "agrotec_db"  "agrotecuser" "agrotecdb"    "$WORK/dbs/agrotecdb.dump"
restore_db "mergin_db"   "mergin"      "mergin"       "$WORK/dbs/mergin.dump"

# --- 3. Restaurar volúmenes ---

restore_vol() {
    local vol="$1" tarball="$2"
    if [ ! -f "$tarball" ]; then
        log "  WARN: $tarball no existe, salto"
        return
    fi
    if ! docker volume ls --format '{{.Name}}' | grep -q "^$vol\$"; then
        log "  creando volumen $vol"
        docker volume create "$vol" >/dev/null
    fi
    log "  restaurar volumen $vol"
    docker run --rm -v "$vol":/d -v "$(dirname "$tarball")":/in alpine \
        sh -c "cd / && tar xzf /in/$(basename "$tarball")"
}

log "Restaurando volúmenes..."
restore_vol "agrotec-statics"   "$WORK/volumes/agrotec-statics.tar.gz"
restore_vol "agrotec-gsdatadir" "$WORK/volumes/agrotec-gsdatadir.tar.gz"
restore_vol "agrotec-data"      "$WORK/volumes/agrotec-data.tar.gz"
restore_vol "agrotec-fr-dbdata" "$WORK/volumes/agrotec-fr-dbdata.tar.gz"
restore_vol "mergin-projects"   "$WORK/volumes/mergin-projects.tar.gz"
restore_vol "mergin-pgdata"     "$WORK/volumes/mergin-pgdata.tar.gz"

log "OK. Ahora arranca los servicios:"
log "  cd /opt/agrotec/bk && docker compose up -d"
log "  cd /opt/agrotec/fr && docker compose up -d"
log "  cd /opt/agrotec/fr/mobile/mergin-server && docker compose up -d"
log ""
log "Verifica con: curl https://<dominio>/api/v1/ortomosaicos?sync=true"
