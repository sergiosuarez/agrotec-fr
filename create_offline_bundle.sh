#!/bin/bash
# create_offline_bundle.sh
# Empaqueta el código fuente e imágenes Docker para despliegue sin internet (Offline)

# Use relative paths or safe writable tmp
OUTPUT_DIR="/tmp/sigmap_deploy_bundle"
DATE=$(date +%Y%m%d)
BUNDLE_NAME="sigmap_full_bundle_${DATE}.tar.gz"

echo "=== Iniciando empaquetado Offline SIGMAP ==="
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/images"
mkdir -p "$OUTPUT_DIR/code"

# 1. Empaquetar Código Fuente (GIS-RT y GIS-BK)
echo "[1/4] Archivando repositorios..."
# Assuming script is run from /opt/sigmap/gis-rt/
# Paths hardcoded based on user environment
rsync -av --exclude '.git' --exclude '__pycache__' --exclude 'venv' --exclude 'node_modules' --exclude 'backups' /opt/sigmap/gis-rt "$OUTPUT_DIR/code/"
rsync -av --exclude '.git' --exclude '__pycache__' --exclude 'venv' --exclude 'backups' --exclude 'geoserver-data' /opt/sigmap/gis-bk "$OUTPUT_DIR/code/"

# 2. Identificar Imágenes Docker requeridas
echo "[2/4] Identificando imágenes Docker..."
IMAGES_RT=$(grep "image:" /opt/sigmap/gis-rt/docker-compose.yml | awk '{print $2}' | sort | uniq)
IMAGES_BK=$(grep "image:" /opt/sigmap/gis-bk/docker-compose.yml | awk '{print $2}' | sort | uniq)
ALL_IMAGES=$(echo -e "$IMAGES_RT\n$IMAGES_BK" | sort | uniq | grep -v "build:") 

echo "Imágenes a exportar:"
echo "$ALL_IMAGES"

# 3. Exportar Imágenes (Docker Save)
echo "[3/4] Guardando imágenes Docker (esto puede tardar)..."
for img in $ALL_IMAGES; do
    if [[ "$img" == *"\$"* ]]; then
        echo "⚠️  Saltando imagen con variables: $img"
        continue
    fi
    safe_name=$(echo "$img" | tr '/:' '_')
    echo "   -> Guardando $img ..."
    # Check if image exists locally first
    if [[ "$(docker images -q $img 2> /dev/null)" == "" ]]; then
      echo "      (Pulling $img first...)"
      docker pull $img
    fi
    docker save "$img" | gzip > "$OUTPUT_DIR/images/${safe_name}.tar.gz"
done

# Crear script de instalación automática
cat <<EOF > "$OUTPUT_DIR/install_offline.sh"
#!/bin/bash
# Script de instalación en servidor destino
echo "Cargando imágenes Docker..."
for img in images/*.tar.gz; do
    echo "Cargando \$img ..."
    docker load -i "\$img"
done

echo "Restaurando código..."
mkdir -p /opt/sigmap
cp -r code/gis-rt /opt/sigmap/
cp -r code/gis-bk /opt/sigmap/

echo "Listo. Ahora puedes ir a /opt/sigmap/gis-bk y /opt/sigmap/gis-rt y levantar los servicios con docker-compose up -d"
EOF
chmod +x "$OUTPUT_DIR/install_offline.sh"

# 4. Comprimir todo el bundle
echo "[4/4] Creando archivo final: $BUNDLE_NAME ..."
tar -czf "/tmp/$BUNDLE_NAME" -C "$OUTPUT_DIR" .

echo "=== PROCESO COMPLETADO ==="
echo "Archivo listo en: /tmp/$BUNDLE_NAME"
echo "--------------------------------------------------------"
echo "Ejecuta este comando para enviarlo al servidor:"
echo "scp /tmp/$BUNDLE_NAME desarrollo@10.141.49.41:/var/lib/docker/"
