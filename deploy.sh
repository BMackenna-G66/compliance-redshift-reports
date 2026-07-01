#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Despliega el backend (las 2 Lambdas) a AWS con un solo comando.
#
# Uso:
#   aws sso login --profile compliance-admin   # si tu sesión SSO expiró
#   ./deploy.sh
#
# Qué hace:
#   1. Empaqueta el código (build_lambda.sh → lambda_package.zip)
#   2. Sube el zip a S3
#   3. Actualiza la API Lambda  (api_handler.py)
#   4. Actualiza el Report Runner (handler.py)
#
# NO migra datos: eso se hace una sola vez con el cluster encendido (ver abajo).
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${AWS_PROFILE:-compliance-admin}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="compliance-redshift-reports-561521480266-us-east-1"
KEY="lambda_package.zip"
API_FN="compliance-redshift-reports-api"
RUNNER_FN="compliance-redshift-reports"

echo "→ 1/4 Empaquetando código"
./build_lambda.sh

echo "→ 2/4 Subiendo paquete a S3"
aws s3 cp lambda_package.zip "s3://$BUCKET/$KEY" --profile "$PROFILE" --region "$REGION"

echo "→ 3/4 Actualizando API Lambda ($API_FN)"
aws lambda update-function-code --function-name "$API_FN" \
  --s3-bucket "$BUCKET" --s3-key "$KEY" \
  --profile "$PROFILE" --region "$REGION" >/dev/null
echo "   ✓ API actualizada"

echo "→ 4/4 Actualizando Report Runner ($RUNNER_FN)"
aws lambda update-function-code --function-name "$RUNNER_FN" \
  --s3-bucket "$BUCKET" --s3-key "$KEY" \
  --profile "$PROFILE" --region "$REGION" >/dev/null
echo "   ✓ Report Runner actualizado"

# Esperar a que el código nuevo quede ACTIVO antes de devolver el control
# (update-function-code es asíncrono: sin esto, una invocación inmediata puede
#  pegarle todavía a la versión vieja).
echo "→ Esperando a que las Lambdas terminen de actualizar..."
aws lambda wait function-updated --function-name "$API_FN" --profile "$PROFILE" --region "$REGION"
aws lambda wait function-updated --function-name "$RUNNER_FN" --profile "$PROFILE" --region "$REGION"
echo "   ✓ código nuevo activo"

echo ""
echo "✅ Despliegue completo."
echo ""
