#!/usr/bin/env bash
# init-secrets.sh — Genera todas las contraseñas del despliegue Agrotec.
#
# Crea/sobrescribe los 3 archivos .env (bk, fr, mobile/mergin-server) y deja
# un CREDENCIALES.md (chmod 600) con todas las credenciales para que el operador
# lo copie a su gestor de secretos.
#
# Uso:
#   ./scripts/init-secrets.sh [/path/al/dir/agrotec]
#
# Idempotente: si los .env ya existen, NO los sobrescribe sin confirmar.

set -euo pipefail

AGROTEC_ROOT="${1:-/opt/agrotec}"
BK="$AGROTEC_ROOT/bk"
FR="$AGROTEC_ROOT/fr"
MERGIN="$AGROTEC_ROOT/fr/mobile/mergin-server"
CRED="$AGROTEC_ROOT/CREDENCIALES.md"

err() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[init-secrets] $*"; }

[ -d "$BK" ]     || err "no existe $BK (clona agrotec-bk primero)"
[ -d "$FR" ]     || err "no existe $FR (clona agrotec-fr primero)"
[ -d "$MERGIN" ] || err "no existe $MERGIN (verifica fr/mobile/mergin-server)"

# Confirmar si los .env ya existen
existing=()
for f in "$BK/.env" "$FR/.env" "$MERGIN/.env"; do
    [ -f "$f" ] && existing+=("$f")
done
if [ ${#existing[@]} -gt 0 ]; then
    echo "Los siguientes archivos ya existen:"
    printf '  %s\n' "${existing[@]}"
    read -r -p "¿Sobrescribir todos? (escribe 'si' para continuar): " ANS
    [ "$ANS" = "si" ] || err "cancelado"
fi

# --- Generar passwords ---
log "Generando passwords..."
PG_ADMIN=$(openssl rand -hex 16)
GN_DB=$(openssl rand -hex 16)
GN_GEODB=$(openssl rand -hex 16)
GS_ADMIN=$(openssl rand -hex 12)
GN_SECRET=$(openssl rand -hex 32)
GN_ADMIN=$(openssl rand -hex 12)
RMQ_PASS=$(openssl rand -hex 12)

FR_PG=$(openssl rand -hex 12)

MERGIN_PG=$(openssl rand -hex 16)
MERGIN_SECRET=$(openssl rand -hex 32)
MERGIN_ADMIN=$(openssl rand -hex 12)

# --- bk/.env ---
log "Escribiendo $BK/.env ..."
if [ -f "$BK/.env.example" ]; then
    cp "$BK/.env.example" "$BK/.env"
    sed -i \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PG_ADMIN|" \
        -e "s|^GEONODE_DATABASE_PASSWORD=.*|GEONODE_DATABASE_PASSWORD=$GN_DB|" \
        -e "s|^GEONODE_GEODATABASE_PASSWORD=.*|GEONODE_GEODATABASE_PASSWORD=$GN_GEODB|" \
        -e "s|^GEOSERVER_ADMIN_PASSWORD=.*|GEOSERVER_ADMIN_PASSWORD=$GS_ADMIN|" \
        -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$GN_ADMIN|" \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=$GN_SECRET|" \
        -e "s|postgis://geonode:[^@]*@|postgis://geonode:$GN_DB@|" \
        -e "s|postgis://geonode_data:[^@]*@|postgis://geonode_data:$GN_GEODB@|" \
        "$BK/.env"
    chmod 600 "$BK/.env"
else
    err "$BK/.env.example no existe"
fi

# --- fr/.env ---
log "Escribiendo $FR/.env ..."
if [ -f "$FR/.env.example" ]; then
    cp "$FR/.env.example" "$FR/.env"
    sed -i \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$FR_PG|" \
        -e "s|^GISDB_PASSWORD=.*|GISDB_PASSWORD=$FR_PG|" \
        "$FR/.env"
    chmod 600 "$FR/.env"
else
    err "$FR/.env.example no existe"
fi

# --- mobile/mergin-server/.env ---
log "Escribiendo $MERGIN/.env ..."
if [ -f "$MERGIN/.env.example" ]; then
    cp "$MERGIN/.env.example" "$MERGIN/.env"
    sed -i \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$MERGIN_PG|" \
        -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$MERGIN_PG|" \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=$MERGIN_SECRET|" \
        -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$MERGIN_ADMIN|" \
        "$MERGIN/.env"
    chmod 600 "$MERGIN/.env"
else
    err "$MERGIN/.env.example no existe"
fi

# --- CREDENCIALES.md ---
log "Escribiendo $CRED ..."
cat > "$CRED" <<EOF
# Credenciales Agrotec — NO COMMITEAR — NO COMPARTIR POR CHAT

Generado: $(date)
Host: $(hostname)

## Backend GeoNode (agrotec-bk)

| Variable | Valor |
|---|---|
| POSTGRES_PASSWORD (postgres admin) | \`$PG_ADMIN\` |
| GEONODE_DATABASE_PASSWORD | \`$GN_DB\` |
| GEONODE_GEODATABASE_PASSWORD | \`$GN_GEODB\` |
| GEOSERVER_ADMIN_PASSWORD | \`$GS_ADMIN\` |
| DJANGO_SECRET_KEY | \`$GN_SECRET\` |
| **ADMIN_PASSWORD (superuser Django)** | \`$GN_ADMIN\` |
| RABBITMQ_DEFAULT_PASS | \`$RMQ_PASS\` |

Acceso:
- GeoNode UI: \`https://<DOMINIO>/\`  usuario \`admin\` / \`$GN_ADMIN\`
- GeoServer: \`https://<DOMINIO>/geoserver/web/\`  usuario \`admin\` / \`$GS_ADMIN\`

## Frontend visor (agrotec-fr)

| Variable | Valor |
|---|---|
| POSTGRES_PASSWORD (agrotecuser) | \`$FR_PG\` |

## Mergin Maps (mobile/mergin-server)

| Variable | Valor |
|---|---|
| POSTGRES_PASSWORD (mergin) | \`$MERGIN_PG\` |
| SECRET_KEY | \`$MERGIN_SECRET\` |
| **ADMIN_PASSWORD** | \`$MERGIN_ADMIN\` |

Acceso:
- Web: \`https://mergin.<DOMINIO>/\`  usuario \`admin\` / \`$MERGIN_ADMIN\`
- Crear admin (despues del primer arranque):
  \`\`\`bash
  docker exec mergin_server flask init-db
  docker exec mergin_server flask user create \\
      --email admin@<dominio> admin '$MERGIN_ADMIN'
  \`\`\`

---

## Pasos siguientes

1. **Copia este archivo a tu gestor de secretos** (Bitwarden, 1Password, Vault).
2. **Borra el plaintext** despues:  \`shred -u $CRED\`
3. Reemplaza el dominio placeholder en los 3 \`.env\`:
   \`\`\`bash
   sed -i 's/agrotec\\.tudominio\\.com/agrotec.<DOMINIO-REAL>/g' \\
       bk/.env fr/.env nginx/nginx.conf
   sed -i 's/mergin\\.tudominio\\.com/mergin.<DOMINIO-REAL>/g' \\
       fr/mobile/mergin-server/.env nginx/nginx.conf
   \`\`\`
4. Sigue [DESPLIEGUE.md](fr/docs/DESPLIEGUE.md) desde el Paso 3.
EOF
chmod 600 "$CRED"

log "OK. Credenciales en: $CRED"
log "MUY IMPORTANTE: copia ese archivo a tu gestor de secretos y borralo del disco."
