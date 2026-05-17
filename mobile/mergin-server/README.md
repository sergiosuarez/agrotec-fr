# mergin-server — Servidor Mergin Maps auto-hosted

Stack docker para sincronizar proyectos QGIS/QField entre tecnicos en campo (offline) y la oficina. Independiente de Agrotec bk/fr: el cliente puede usar este o el SaaS oficial (`https://app.merginmaps.com`).

## Stack

| Componente | Imagen | Funcion |
|---|---|---|
| `mergin_server` | `lutraconsulting/merginmaps-backend:2025.7.3` | API Flask (puerto 5000 interno) |
| `mergin_celery` | misma | Worker async (cleanup, notificaciones) |
| `mergin_web` | `lutraconsulting/merginmaps-frontend:2025.7.3` | SPA Vue.js (puerto 8080 interno) |
| `mergin_db` | `postgis/postgis:14-3.3` | PostgreSQL propio |
| `mergin_redis` | `redis:7-alpine` | Cache / cola Celery |

Red: `mergin-net` (bridge, propio).

## Despliegue

```bash
# 1. Llenar .env con passwords reales (usa los del CREDENCIALES.md)
cp .env.example .env  # (cuando exista)

# 2. Levantar
docker compose up -d

# 3. Crear admin (primera vez)
docker compose exec server flask init-db
docker compose exec server flask user create-user \
    --username admin --email admin@example.com --password 'tu-pass' --is-admin

# 4. Acceder
# https://mergin.tudominio.com/ (frontend + API tras reverse proxy)
```

## Reverse proxy (nginx externo)

Subdominio recomendado: `mergin.tudominio.com`. Server block ejemplo:

```nginx
server {
    listen 443 ssl;
    server_name mergin.tudominio.com;

    ssl_certificate     /etc/letsencrypt/live/mergin.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mergin.tudominio.com/privkey.pem;

    client_max_body_size 200M;

    # SPA
    location / {
        proxy_pass http://mergin_web:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # API (backend Flask)
    location /v1/ {
        proxy_pass http://mergin_server:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }

    location /v2/ {
        proxy_pass http://mergin_server:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ping {
        proxy_pass http://mergin_server:5000;
    }
}
```

El nginx que termina TLS debe estar en la red `mergin-net` o se exponen puertos del host.

## Conectar QField

1. En el movil: abrir QField, *Open project* > *Mergin Maps*.
2. Server: `https://mergin.tudominio.com`
3. Login con un usuario creado en Mergin.
4. Crear proyecto en Mergin (web), agregar capas QGIS/raster/MBTiles, *clonar* en QField.
5. Los tecnicos editan offline, sincronizan cuando hay red.

## Notas

- Mergin almacena proyectos en `mergin_projects` volume (path `/data/projects`).
- Los archivos grandes (MBTiles, COG) pesan: dimensionar disco antes.
- Backup recomendado: `docker run --rm -v mergin-projects:/d -v $(pwd):/b alpine tar czf /b/mergin-bak-$(date +%F).tar.gz /d`
