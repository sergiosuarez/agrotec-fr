#!/usr/bin/env sh
set -eu

OUTDIR="icons_barcos"
mkdir -p "$OUTDIR"

echo "Descargando iconos OpenMoji en $OUTDIR …"

# nombre_archivo|url
while IFS="|" read -r filename url; do
  [ -z "$filename" ] && continue
  echo " - $filename"
  curl -fsSL "$url" -o "$OUTDIR/$filename"
done << 'EOF'
barco_generico.svg|https://raw.githubusercontent.com/hfg-gmuend/openmoji/31f496f/color/svg/1F6A2.svg
lancha_rapida.svg|https://raw.githubusercontent.com/hfg-gmuend/openmoji/31f496f/color/svg/1F6A4.svg
barco_pasajeros.svg|https://raw.githubusercontent.com/hfg-gmuend/openmoji/31f496f/color/svg/1F6F3.svg
ferry.svg|https://raw.githubusercontent.com/hfg-gmuend/openmoji/31f496f/color/svg/26F4.svg
EOF

echo "Listo. Revisa la carpeta $OUTDIR/"
