#!/usr/bin/env bash
# =============================================================================
# deploy_embargos.sh — Publica la Lambda de oficios de embargo.
#
# Es una Lambda aparte de las dos del portal (ver build_embargos.sh para el
# porqué). Reutiliza el rol `compliance-redshift-reports-lambda-role`, que ya
# tiene S3, Redshift Data API y self-invoke — no hace falta crear uno nuevo, y
# el perfil compliance-admin no puede tocar IAM de todos modos.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${AWS_PROFILE:-compliance-admin}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="compliance-redshift-reports-561521480266-us-east-1"
FN="compliance-embargos"
ZIP="embargos_package.zip"

[ -f "$ZIP" ] || { echo "✗ Falta $ZIP — corré ./build_embargos.sh primero" >&2; exit 1; }

echo "→ Subiendo $ZIP ($(du -h "$ZIP" | cut -f1))"
aws s3 cp "$ZIP" "s3://$BUCKET/$ZIP" --region "$REGION" --profile "$PROFILE" --quiet

echo "→ Actualizando $FN"
aws lambda update-function-code --function-name "$FN" \
  --s3-bucket "$BUCKET" --s3-key "$ZIP" \
  --region "$REGION" --profile "$PROFILE" --query 'LastUpdateStatus' --output text

for i in $(seq 1 20); do
  s=$(aws lambda get-function-configuration --function-name "$FN" \
        --region "$REGION" --profile "$PROFILE" --query 'LastUpdateStatus' --output text)
  [ "$s" = "Successful" ] && { echo "✓ $FN actualizada"; exit 0; }
  [ "$s" = "Failed" ] && { echo "✗ falló la actualización" >&2; exit 1; }
  sleep 5
done
echo "✗ no terminó a tiempo" >&2; exit 1
