#!/usr/bin/env bash
# =============================================================================
# build_embargos.sh — Paquete de la Lambda de oficios de embargo.
#
# POR QUÉ TIENE SU PROPIO PAQUETE
# --------------------------------
# El resto del sistema viaja en `lambda_package.zip`, compartido por la Lambda
# del portal y la de reportes. Embargos va aparte por dos razones medidas:
#
#   1. Dependencias. pdfplumber + docxtpl + ftfy suman ~58 MB netos (arrastran
#      pdfminer, lxml, cryptography). El paquete compartido ya está en 147 MB
#      contra el límite de 250 MB de Lambda, y ese peso lo pagaría el arranque
#      en frío de TODOS los endpoints del portal por un módulo que se usa unas
#      pocas veces al mes.
#   2. Tiempo. El portal corta a los 60 s y el API Gateway a los 30. Generar
#      oficios lleva minutos, así que necesita los 900 s y su propia memoria.
#
# LO QUE NO VIAJA
# ---------------
# Las muestras (`lambda/embargos/muestras/`) son insumos judiciales con datos
# personales de decenas de miles de personas. No están en el repo y no tienen
# por qué estar en el paquete: el archivo a procesar llega por S3 en cada
# corrida.
#
# Uso:
#   ./build_embargos.sh && ./deploy_embargos.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

BUILD_DIR="build_embargos"
ZIP="embargos_package.zip"

echo "→ Limpiando build anterior"
rm -rf "$BUILD_DIR" "$ZIP"
mkdir -p "$BUILD_DIR"

echo "→ Copiando código"
# El paquete completo, menos las muestras (datos personales) y los .pyc.
cp -R lambda/embargos "$BUILD_DIR/"
rm -rf "$BUILD_DIR/embargos/muestras" "$BUILD_DIR/embargos/tests"
# `redshift.py` hace `import db_redshift`: es el cliente de Redshift que ya usa
# el resto del proyecto, con el manejo del cluster pausado incluido.
cp lambda/db_redshift.py "$BUILD_DIR/"

echo "→ Instalando dependencias para Linux/x86_64"
pip install \
  --target "$BUILD_DIR" \
  --requirement lambda/embargos/requirements.txt \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --upgrade \
  --no-warn-conflicts \
  --quiet

echo "→ Recortando lo que no hace falta en runtime"
find "$BUILD_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name "tests" -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
rm -rf "$BUILD_DIR"/*.dist-info/RECORD 2>/dev/null || true

echo "→ Tamaño descomprimido: $(du -sh "$BUILD_DIR" | cut -f1) (límite Lambda: 250 MB)"
(cd "$BUILD_DIR" && zip -qr "../$ZIP" .)
echo "→ $ZIP creado: $(du -h "$ZIP" | cut -f1)"

# Guardia: si el paquete se pasa de 250 MB descomprimido, Lambda lo rechaza con
# un error poco claro. Mejor fallar acá y con el número a la vista.
BYTES=$(du -sk "$BUILD_DIR" | cut -f1)
if [ "$BYTES" -gt 245000 ]; then
  echo "✗ El paquete descomprimido supera los 245 MB. Lambda corta en 250." >&2
  exit 1
fi
