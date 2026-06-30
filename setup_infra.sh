#!/usr/bin/env bash
# =============================================================================
# setup_infra.sh — Crea las tablas DynamoDB del CRM y otorga el permiso IAM a
# las Lambdas. Necesario porque estas tablas estaban en Terraform pero nunca se
# aplicaron (el estado de TF es local y no está en este entorno).
#
# Idempotente: si una tabla ya existe, la saltea. El permiso IAM se agrega como
# política inline NUEVA (no pisa las existentes) y usa un comodín que cubre
# todas las tablas del proyecto (whitelist, alerts, cases, users, audit...).
#
# Uso:  ./setup_infra.sh        (requiere AWS SSO activo, rol admin)
# =============================================================================
set -euo pipefail

PROFILE="${AWS_PROFILE:-compliance-admin}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="561521480266"
PREFIX="compliance-redshift-reports"

create_table () {
  local name="$1" pk="$2"
  if aws dynamodb describe-table --table-name "$name" \
        --region "$REGION" --profile "$PROFILE" >/dev/null 2>&1; then
    echo "   = $name (ya existe, ok)"
  else
    aws dynamodb create-table --table-name "$name" \
      --attribute-definitions AttributeName="$pk",AttributeType=S \
      --key-schema AttributeName="$pk",KeyType=HASH \
      --billing-mode PAY_PER_REQUEST \
      --region "$REGION" --profile "$PROFILE" >/dev/null
    aws dynamodb wait table-exists --table-name "$name" --region "$REGION" --profile "$PROFILE"
    echo "   ✓ $name creada"
  fi
}

echo "→ 1/3 Creando tablas DynamoDB del CRM"
create_table "$PREFIX-whitelist" whitelist_id
create_table "$PREFIX-alerts"    alert_id

echo "→ 2/3 Activando TTL (auto-expiración) en whitelist.expires_at"
aws dynamodb update-time-to-live --table-name "$PREFIX-whitelist" \
  --time-to-live-specification "Enabled=true,AttributeName=expires_at" \
  --region "$REGION" --profile "$PROFILE" >/dev/null 2>&1 \
  && echo "   ✓ TTL activado" || echo "   = TTL ya estaba activo (ok)"

echo "→ 3/3 Otorgando permiso DynamoDB a las Lambdas (IAM inline policy)"
POLICY='{"Version":"2012-10-17","Statement":[{"Sid":"WatchTowerCRMDynamo","Effect":"Allow","Action":["dynamodb:PutItem","dynamodb:GetItem","dynamodb:UpdateItem","dynamodb:DeleteItem","dynamodb:Scan","dynamodb:Query","dynamodb:BatchWriteItem"],"Resource":["arn:aws:dynamodb:'"$REGION"':'"$ACCOUNT"':table/'"$PREFIX"'-*","arn:aws:dynamodb:'"$REGION"':'"$ACCOUNT"':table/'"$PREFIX"'-*/index/*"]}]}'
for FN in "$PREFIX-api" "$PREFIX"; do
  ROLE=$(aws lambda get-function-configuration --function-name "$FN" \
           --query 'Role' --output text --region "$REGION" --profile "$PROFILE" | sed 's#.*/##')
  aws iam put-role-policy --role-name "$ROLE" \
    --policy-name watchtower-crm-dynamodb \
    --policy-document "$POLICY" --profile "$PROFILE"
  echo "   ✓ permiso agregado al rol de $FN ($ROLE)"
done

echo ""
echo "✅ Infra DynamoDB lista (tablas + permisos)."
echo "   Nota: IAM tarda unos segundos en propagar. Si la migración falla justo"
echo "   ahora, esperá ~15s y volvé a correrla."
