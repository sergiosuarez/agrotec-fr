# nginx — Reverse proxy publico Agrotec

Stack standalone que termina TLS y enruta los subdominios `agrotec.*` y `mergin.*` a los contenedores internos de Agrotec.

**Pensado para "deploy llave en mano" al servidor del cliente** — no depende de ningun otro proyecto.

## Despliegue

### 1. Preparar dominios y certificados

Asegurate que el DNS apunta al servidor:

```
A   agrotec   <IP-PUBLICA>
A   mergin    <IP-PUBLICA>
```

Emitir certificados (con nginx aun apagado):

```bash
sudo certbot certonly --standalone -d agrotec.tudominio.com
sudo certbot certonly --standalone -d mergin.tudominio.com
```

### 2. Configurar dominios en `nginx.conf`

```bash
cd /opt/agrotec/fr/nginx
sed -i 's/agrotec.tudominio.com/agrotec.dominio-real.com/g' nginx.conf
sed -i 's/mergin.tudominio.com/mergin.dominio-real.com/g'   nginx.conf
```

### 3. Levantar

```bash
docker compose up -d
```

> Requiere que `agrotec-bk`, `agrotec-fr` (visor + thredds) y `mobile/mergin-server` ya esten levantados, porque las redes `agrotec-net` y `mergin-net` se crean alli.

### 4. Verificar

```bash
for url in / /visor/ /api/v1/cultivos /geoserver/web/ /thredds/catalog.html; do
    code=$(curl -sk -o /dev/null -w "%{http_code}" \
        "https://agrotec.dominio-real.com$url")
    printf "  %-35s -> %s\n" "$url" "$code"
done
curl -sk -o /dev/null -w "  mergin / -> %{http_code}\n" \
    https://mergin.dominio-real.com/
```

## Renovacion automatica del cert

Certbot crea un timer systemd. Verificar:

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run   # simula renovacion
```

Despues de cada renovacion, recargar nginx para tomar el nuevo cert:

```bash
docker exec agrotec_nginx nginx -s reload
```

O agregar a `/etc/letsencrypt/renewal-hooks/post/`:

```bash
cat > /etc/letsencrypt/renewal-hooks/post/reload-agrotec-nginx.sh <<'EOF'
#!/bin/bash
docker exec agrotec_nginx nginx -s reload
EOF
chmod +x /etc/letsencrypt/renewal-hooks/post/reload-agrotec-nginx.sh
```

## Troubleshooting

### `502 Bad Gateway`

Un upstream esta down. Verificar:
```bash
docker ps | grep -E "nginx4agrotec|agrotec_visor|agrotec_thredds|mergin_proxy"
```

Reload del nginx:
```bash
docker exec agrotec_nginx nginx -s reload
```

### `cannot resolve nginx4agrotec` en logs

El nginx no ve la red `agrotec-net`. Recrear:
```bash
docker compose down
docker compose up -d
```

### Cert TLS no carga (502 + log "no such file")

`/etc/letsencrypt/live/<dominio>/fullchain.pem` no existe. Emitir:
```bash
docker compose stop nginx
sudo certbot certonly --standalone -d <dominio>
docker compose start nginx
```
