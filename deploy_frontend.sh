#!/usr/bin/env bash
# =============================================================================
# deploy_frontend.sh — Publica el frontend en el bucket S3 detrás de CloudFront.
#
# POR QUÉ EXISTE ESTE SCRIPT
# --------------------------
# WatchTower tiene DOS frontends sirviendo el mismo index.html:
#
#   1. GitHub Pages  (https://bmackenna-g66.github.io/compliance-redshift-reports/)
#      → se actualiza SOLO, con cada push a main (.github/workflows/deploy-pages.yml)
#
#   2. CloudFront    (https://di7f123v3u2y5.cloudfront.net/)
#      → sirve desde un bucket S3 que el CI NO toca. Se actualiza con ESTE script.
#
# Si solo se hace push a main, el de CloudFront queda viejo y el equipo no ve
# los cambios (ya pasó: quedó congelado ~2 meses). Correr este script después
# de cada push que toque frontend/index.html, o usar siempre la misma URL.
#
# Uso:
#   ./deploy_frontend.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${AWS_PROFILE:-compliance-admin}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="compliance-redshift-reports-frontend-561521480266"
PAGES_URL="https://bmackenna-g66.github.io/compliance-redshift-reports"
CF_URL="https://di7f123v3u2y5.cloudfront.net"

echo "→ 1/3 Subiendo index.html ($(wc -c < frontend/index.html | tr -d ' ') bytes)"
# no-cache hace que CloudFront revalide contra el origen en cada request, así
# los cambios se ven al instante. Es necesario porque el rol compliance-admin
# NO tiene permiso de cloudfront:CreateInvalidation.
aws s3 cp frontend/index.html "s3://$BUCKET/index.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "no-cache, must-revalidate" \
  --profile "$PROFILE" --region "$REGION" >/dev/null
echo "   ✓ index.html subido"

echo "→ 2/3 Sincronizando config.json desde GitHub Pages"
# config.json lo genera el CI con los secrets del repo (incluye geminiKey), así
# que la copia buena es la de Pages — no se versiona en git a propósito.
if curl -fsS "$PAGES_URL/config.json" -o /tmp/_wt_config.json; then
  aws s3 cp /tmp/_wt_config.json "s3://$BUCKET/config.json" \
    --content-type "application/json" \
    --cache-control "no-cache, must-revalidate" \
    --profile "$PROFILE" --region "$REGION" >/dev/null
  rm -f /tmp/_wt_config.json
  echo "   ✓ config.json sincronizado"
else
  echo "   ⚠ No se pudo leer config.json de Pages — se deja el que ya está en S3"
fi

echo "→ 3/3 Verificando que CloudFront sirva la versión nueva"
sleep 2
LOCAL_SIZE=$(wc -c < frontend/index.html | tr -d ' ')
LIVE_SIZE=$(curl -s -o /dev/null -w '%{size_download}' "$CF_URL/")
if [ "$LOCAL_SIZE" = "$LIVE_SIZE" ]; then
  echo "   ✓ CloudFront ya sirve la versión nueva ($LIVE_SIZE bytes)"
else
  echo "   ⚠ CloudFront sirve $LIVE_SIZE bytes y el local tiene $LOCAL_SIZE."
  echo "     Puede tardar unos segundos. Si persiste, pedir a alguien con"
  echo "     permiso de CloudFront que invalide:  /*"
fi

echo ""
echo "✅ Frontend publicado."
echo "   CloudFront:    $CF_URL"
echo "   GitHub Pages:  $PAGES_URL  (se actualiza solo con push a main)"
