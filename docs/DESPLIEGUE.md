# Despliegue end-to-end — Agrotec en un servidor nuevo

Guía paso-a-paso para desplegar la plataforma completa en un servidor del cliente.

## Requisitos del servidor

| Recurso | Mínimo | Recomendado |
|---|---|---|
| **CPU** | 4 vCPU | 8 vCPU |
| **RAM** | 12 GB | 24 GB |
| **Disco** | 60 GB SSD | 200 GB SSD |
| **OS** | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| **Red** | IP pública + DNS controlado | + WireGuard opcional |
| **Software** | Docker + Compose v2, git, gdal-bin, certbot, openssl | + ufw, fail2ban |

Estimación de uso real con 10-50 capas raster y GFS Ecuador: **~30 GB disco, 8 GB RAM en pico**.

---

## Paso 0 — Preparar el sistema

```bash
sudo apt update && sudo apt install -y \
    docker.io docker-compose-plugin git gdal-bin \
    certbot python3-certbot-nginx \
    ufw fail2ban openssl
sudo systemctl enable --now docker
sudo usermod -aG docker $USER     # logout/login despues
```

### Hardening básico (recomendado)

```bash
# UFW: solo SSH + HTTPS
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp        # o el puerto SSH alterno que uses
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# fail2ban con jail sshd default
sudo systemctl enable --now fail2ban
```

---

## Paso 1 — Clonar los repos

```bash
sudo mkdir -p /opt/agrotec && sudo chown $USER /opt/agrotec
cd /opt/agrotec
git clone https://github.com/sergiosuarez/agrotec-bk.git bk
git clone https://github.com/sergiosuarez/agrotec-fr.git fr
# (Mergin Maps server queda en fr/mobile/mergin-server/)
```

---

## Paso 2 — Generar credenciales

Usa el script para generar todas las contraseñas y rellenar los `.env`:

```bash
cd /opt/agrotec/fr
./scripts/init-secrets.sh
```

Esto crea:
- `/opt/agrotec/bk/.env` con passwords nuevas
- `/opt/agrotec/fr/.env` con passwords nuevas
- `/opt/agrotec/fr/mobile/mergin-server/.env` con passwords nuevas
- `/opt/agrotec/CREDENCIALES.md` (chmod 600) con TODAS las claves para tu registro

**Antes de continuar:**

1. Abre `/opt/agrotec/CREDENCIALES.md`, **cópialo a tu gestor de secretos** (Bitwarden, 1Password, vault del cliente)
2. Reemplaza el dominio placeholder en los 3 `.env`:
   ```bash
   sed -i 's/agrotec.tudominio.com/agrotec.<DOMINIO-REAL>/g' bk/.env fr/.env
   sed -i 's/mergin.tudominio.com/mergin.<DOMINIO-REAL>/g' fr/mobile/mergin-server/.env
   ```

---

## Paso 3 — DNS y TLS

### 3.1 Apuntar dominios

En el panel del proveedor DNS del cliente, agregar:

```
Tipo   Nombre     Valor                TTL
A      agrotec    <IP-PUBLICA>         300
A      mergin     <IP-PUBLICA>         300
```

Esperar propagación (verificar con `dig +short agrotec.dominio.com`).

### 3.2 Emitir certificados Let's Encrypt

Con nginx **temporalmente apagado**:

```bash
sudo certbot certonly --standalone -d agrotec.dominio.com
sudo certbot certonly --standalone -d mergin.dominio.com
```

Los certs quedan en `/etc/letsencrypt/live/<dominio>/`.

Auto-renovación: certbot ya instaló un timer systemd (`systemctl status certbot.timer`).

---

## Paso 4 — Levantar los stacks

### 4.1 Backend GeoNode (más pesado, primero)

```bash
cd /opt/agrotec/bk
docker compose pull         # ~3 GB de imagenes
docker compose up -d
```

Esperar **5-10 min** (la primera vez corre migraciones de Django). Verificar:
```bash
docker compose ps
# Todos en (healthy) excepto rabbitmq sin healthcheck
```

### 4.2 Frontend visor + GFS

```bash
cd /opt/agrotec/fr
docker compose build        # build del visor y del scheduler GFS
docker compose up -d        # levanta visor, db, redis, thredds, gfs_scheduler
```

El `gfs_scheduler` empieza a descargar el último run GFS al arrancar (~3 min, NetCDF de ~300 KB).

### 4.3 Mergin Maps (móvil)

```bash
cd /opt/agrotec/fr/mobile/mergin-server
docker compose up -d
# Inicializar BD y crear admin
docker exec mergin_server flask init-db
docker exec mergin_server flask user create \
    --email admin@dominio.com admin '<password-del-CREDENCIALES>'
```

---

## Paso 5 — Reverse proxy nginx público

Configuración propia de Agrotec (no depende de StreamTrack):

```bash
cd /opt/agrotec/fr/nginx
# Editar nginx.conf y reemplazar 'agrotec.desarrollowebsite.com' por tu dominio
sed -i 's/agrotec\.desarrollowebsite\.com/agrotec.dominio.com/g' nginx.conf
sed -i 's/mergin\.desarrollowebsite\.com/mergin.dominio.com/g' nginx.conf
docker compose up -d
```

Esto levanta `agrotec_nginx` que se conecta a las redes `agrotec-net` y `mergin-net` y termina TLS en `:80/:443`.

---

## Paso 6 — Verificación

```bash
# Test de cada endpoint público
for url in / /visor/ /api/v1/cultivos /api/v1/gfs/status \
           /geoserver/web/ /thredds/catalog.html; do
    code=$(curl -sk -o /dev/null -w "%{http_code}" \
        "https://agrotec.dominio.com$url")
    printf "  %-35s -> %s\n" "$url" "$code"
done

curl -sk -o /dev/null -w "  mergin / -> %{http_code}\n" \
    https://mergin.dominio.com/
```

Salida esperada:

```
  /                                   -> 200
  /visor/                             -> 200
  /api/v1/cultivos                    -> 200
  /api/v1/gfs/status                  -> 200
  /geoserver/web/                     -> 302
  /thredds/catalog.html               -> 302
  mergin /                            -> 200
```

---

## Paso 7 — Carga inicial de capas

Si tienes ortomosaicos del cliente (`.tif` UTM), subirlos:

```bash
# Copiarlos al servidor primero (ej. /home/$USER/ortos/)
cd /opt/agrotec/bk
./scripts/import_orthomosaics.sh /home/$USER/ortos/
```

Cada GeoTIFF se convierte a COG-JPEG (~10% del tamaño) y se sube como capa WMS.

---

## Paso 8 — Backup automatizado

Agregar al cron del usuario:

```bash
crontab -e
# Backup diario a las 3 AM
0 3 * * * /opt/agrotec/fr/scripts/backup.sh /backup/agrotec/$(date +\%F).tar.gz
```

Ver [MIGRACION_CLIENTE.md](./MIGRACION_CLIENTE.md) para el detalle del backup/restore.

---

## Troubleshooting común

### `nginx4agrotec` arranca pero responde 444 al subdominio

El `HTTP_HOST` del `.env` no coincide con el `Host` que llega. Verifica:
```bash
grep -E "^HTTP_HOST|^SITEURL" /opt/agrotec/bk/.env
# Debe ser: HTTP_HOST=agrotec.dominio.com (no IP, no localhost)
```

### Geovisor da 502

El upstream `agrotec_visor` está down o el nginx no lo encuentra. Reiniciar:
```bash
docker exec agrotec_nginx nginx -s reload
```

### GFS scheduler con "AssertionError"

Versiones de xarray/pandas incompatibles. Rebuild forzado:
```bash
cd /opt/agrotec/fr
docker compose build --no-cache gfs_scheduler
docker compose up -d --force-recreate gfs_scheduler
```

### Mergin server en restart loop

Falta el `GUNICORN_CMD_ARGS=--bind=0.0.0.0:5000` en el compose. Ya viene en la versión actual del compose.

### Capa subida a GeoNode pero no aparece en `/api/v2/datasets`

Bajo carga, el Celery puede tardar minutos en procesar. Ver logs:
```bash
docker logs celery4agrotec --tail 30
```

---

## Apagado limpio

```bash
cd /opt/agrotec/fr/mobile/mergin-server && docker compose stop
cd /opt/agrotec/fr && docker compose stop
cd /opt/agrotec/bk && docker compose stop
cd /opt/agrotec/fr/nginx && docker compose stop
```

Para borrar **todo** (cuidado: incluye datos):

```bash
docker compose down -v   # en cada directorio. -v borra volumenes.
```
