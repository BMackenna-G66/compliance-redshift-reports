#!/usr/bin/env bash
# =============================================================================
# horario_informe_alertas.sh — El informe de alertas sale solo, los lunes a
# las 09:00 de Chile.
#
# -----------------------------------------------------------------------------
# POR QUÉ EVENTBRIDGE SCHEDULER Y NO UNA REGLA CRON COMO LAS OTRAS
# -----------------------------------------------------------------------------
# Las reglas de `events` que ya tiene el proyecto (amount_ranges, top_customers)
# usan `cron(...)` y **sólo entienden UTC**. Chile cambia de huso dos veces al
# año, así que un `cron(12 0 ? * MON *)` llega a las 09:00 la mitad del año y a
# las 08:00 la otra mitad. Scheduler acepta `--schedule-expression-timezone`, se
# ocupa él del cambio de hora, y entonces "los lunes a las nueve" significa los
# lunes a las nueve todo el año.
#
# El precio es que Scheduler invoca con un ROL (las reglas viejas usan permiso
# en la Lambda), así que este script crea también el rol. Está acotado a invocar
# esa única función.
#
# -----------------------------------------------------------------------------
# A QUIÉN LE LLEGA — Y POR QUÉ NO ESTÁ ESCRITO ACÁ
# -----------------------------------------------------------------------------
# **Este repositorio es público y la lista es de personas.** Así que la lista no
# vive en el código: vive en `config/informe_alertas.json`, en el bucket, que es
# privado. El script la lee de ahí para armar el horario.
#
# La primera vez hay que pasarla:
#
#     ./horario_informe_alertas.sh --para "uno@global66.com,otro@global66.com"
#
# Eso la guarda en S3 y crea (o actualiza) el horario con ella. Después, para
# cambiarla no hace falta volver a correr esto ni redesplegar nada: la Lambda
# lee el mismo objeto en cada corrida y lo que diga ahí es lo que manda.
#
# Y para pararlo sin borrar el horario: `{"activo": false}` en ese objeto.
#
# -----------------------------------------------------------------------------
# USO
# -----------------------------------------------------------------------------
#   ./horario_informe_alertas.sh --para "a@g66.com,b@g66.com"
#                                                guarda la lista y crea/actualiza
#                                                el horario
#   ./horario_informe_alertas.sh                 crea/actualiza el horario con la
#                                                lista que ya está en S3
#   ./horario_informe_alertas.sh --prueba [correo]
#                                                NO toca el horario: manda el
#                                                informe una vez, ahora, a UNA
#                                                dirección
#   ./horario_informe_alertas.sh --apagar        deja el horario pero DISABLED
#   ./horario_informe_alertas.sh --estado        qué hay y cuándo corre
#
# Idempotente: si el rol o el horario ya existen, los actualiza.
# =============================================================================
set -euo pipefail

PROFILE="${AWS_PROFILE:-compliance-admin}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="561521480266"
BUCKET="compliance-redshift-reports-561521480266-us-east-1"
CLAVE="config/informe_alertas.json"
FUNCION="compliance-redshift-reports"
HORARIO="watchtower-informe-alertas-lunes"
ROL="watchtower-scheduler-informe-alertas"

# Los lunes a las 09:00, hora de Chile. El `?` del día del mes es obligatorio
# cuando se especifica el día de la semana.
CRON="cron(0 9 ? * MON *)"
ZONA="America/Santiago"

# A quién va la corrida de prueba, si no se pasa una dirección. UNA sola a
# propósito: una prueba que le llega a tres personas es un informe que nadie
# pidió.
PARA_PRUEBA_DEFECTO="benjamin.mackenna@global66.com"

FN_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCION}"
ROL_ARN="arn:aws:iam::${ACCOUNT}:role/${ROL}"

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }

# Convierte "a@x,b@y" en el JSON `["a@x","b@y"]`, sin confiar en que venga
# prolijo: espacios, comas de más y repetidos se limpian acá.
lista_json () {
  python3 - "$1" <<'PY'
import json, re, sys
vistos, fuera = set(), []
for x in re.split(r"[,;\s]+", sys.argv[1] or ""):
    c = x.strip().lower()
    if c and c not in vistos:
        vistos.add(c); fuera.append(c)
print(json.dumps(fuera))
PY
}

# ── --estado ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--estado" ]]; then
  aws_ scheduler get-schedule --name "$HORARIO" \
    --query '{nombre:Name,estado:State,cuando:ScheduleExpression,zona:ScheduleExpressionTimezone,destino:Target.Arn}' \
    --output table
  echo
  echo "Próximas corridas (hora de Chile), según el cron:"
  python3 <<'PY'
import datetime as dt, zoneinfo
# Pronóstico de cortesía para el lunes 09:00 de Chile. La verdad la tiene
# Scheduler; esto sólo evita tener que contar días en la cabeza.
tz = zoneinfo.ZoneInfo("America/Santiago")
ahora = dt.datetime.now(tz)
d = ahora.replace(hour=9, minute=0, second=0, microsecond=0)
while d <= ahora or d.weekday() != 0:
    d += dt.timedelta(days=1)
for i in range(3):
    print("   ", (d + dt.timedelta(weeks=i)).strftime("%A %d-%m-%Y %H:%M %Z"))
PY
  exit 0
fi

# ── --prueba ────────────────────────────────────────────────────────────────
# Corre EXACTAMENTE el mismo camino que correrá el lunes —mismo `report_name`,
# misma Lambda, misma función de envío— y por eso sirve de prueba. Lo único
# distinto es a quién le llega.
if [[ "${1:-}" == "--prueba" ]]; then
  PARA_PRUEBA="$(lista_json "${2:-$PARA_PRUEBA_DEFECTO}")"
  echo "▶ Corrida de prueba del informe de alertas → ${PARA_PRUEBA}"
  SALIDA="$(mktemp)"
  aws_ lambda invoke \
    --function-name "$FUNCION" \
    --cli-binary-format raw-in-base64-out \
    --payload "{\"report_name\":\"informe_alertas\",\"para\":${PARA_PRUEBA}}" \
    --cli-read-timeout 900 \
    "$SALIDA" >/dev/null
  echo "Respuesta de la Lambda:"
  python3 -m json.tool < "$SALIDA" || cat "$SALIDA"
  rm -f "$SALIDA"
  echo
  echo "Si dice \"enviado\": true, el camino programado funciona de punta a punta."
  exit 0
fi

# ── --apagar ────────────────────────────────────────────────────────────────
# Apagar no puede cambiar nada más que el estado. Por eso el destino se REUSA
# tal cual está en el horario en vez de reconstruirlo: reconstruirlo pisaría la
# lista con la que quedó creado, y apagar algo no es el momento de cambiarle
# los destinatarios sin avisar.
if [[ "${1:-}" == "--apagar" ]]; then
  VIVO="$(aws_ scheduler get-schedule --name "$HORARIO")"
  TARGET=$(python3 - "$VIVO" <<'PY'
import json, sys
t = json.loads(sys.argv[1])["Target"]
print(json.dumps({k: t[k] for k in ("Arn", "RoleArn", "Input", "RetryPolicy")
                  if k in t}))
PY
)
  aws_ scheduler update-schedule --name "$HORARIO" --state DISABLED \
    --schedule-expression "$CRON" \
    --schedule-expression-timezone "$ZONA" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "$TARGET" >/dev/null
  echo "✅ Horario apagado (sigue existiendo; --estado lo muestra DISABLED)."
  exit 0
fi

# ── La lista de destinatarios: de `--para`, o la que ya está en S3 ──────────
# No hay lista por defecto en el código a propósito: este repo es público y la
# lista es de personas. Si no está en S3 y no se pasa, el script se planta.
NUEVA=""
if [[ "${1:-}" == "--para" ]]; then
  NUEVA="${2:-}"
  if [[ -z "$NUEVA" ]]; then
    echo "✗ --para necesita la lista: --para \"uno@global66.com,otro@global66.com\"" >&2
    exit 1
  fi
fi

ACTUAL="$(aws_ s3 cp "s3://${BUCKET}/${CLAVE}" - 2>/dev/null || echo '{}')"

if [[ -n "$NUEVA" ]]; then
  # Se escribe la lista SIN tocar el resto del objeto: si alguien había dejado
  # `activo: false`, cambiar los destinatarios no puede re-prenderlo solo.
  ACTUAL=$(python3 - "$ACTUAL" "$(lista_json "$NUEVA")" <<'PY'
import json, sys
try:
    cfg = json.loads(sys.argv[1] or "{}")
except ValueError:
    cfg = {}
cfg = cfg if isinstance(cfg, dict) else {}
cfg["para"] = json.loads(sys.argv[2])
print(json.dumps(cfg, ensure_ascii=False, indent=2))
PY
)
  printf '%s\n' "$ACTUAL" | aws_ s3 cp - "s3://${BUCKET}/${CLAVE}" >/dev/null
  echo "   ✓ lista guardada en s3://${BUCKET}/${CLAVE}"
fi

PARA=$(python3 - "$ACTUAL" <<'PY'
import json, sys
try:
    cfg = json.loads(sys.argv[1] or "{}")
except ValueError:
    cfg = {}
print(json.dumps((cfg if isinstance(cfg, dict) else {}).get("para") or []))
PY
)

if [[ "$PARA" == "[]" ]]; then
  echo "✗ No hay destinatarios. La primera vez hay que pasarlos:" >&2
  echo "    ./horario_informe_alertas.sh --para \"uno@global66.com,otro@global66.com\"" >&2
  exit 1
fi

# El destino del horario. Se arma con python y no a mano porque es JSON con un
# JSON adentro (`Input` es un string), y escapar eso en bash es la forma más
# barata de crear un horario que invoca con un payload roto.
#
# La lista viaja en el `Input` además de estar en S3: es el salvavidas. Si el
# objeto de S3 se borra o queda ilegible un lunes a las nueve, el informe sale
# igual con la lista con la que se creó el horario.
PAYLOAD="{\"report_name\":\"informe_alertas\",\"para\":${PARA}}"
TARGET=$(python3 - "$FN_ARN" "$ROL_ARN" "$PAYLOAD" <<'PY'
import json, sys
print(json.dumps({"Arn": sys.argv[1], "RoleArn": sys.argv[2], "Input": sys.argv[3],
                  # Dos reintentos: si la Lambda estaba fría o S3 tosió, el
                  # informe sale igual. Pasada una hora ya no sirve mandarlo.
                  "RetryPolicy": {"MaximumRetryAttempts": 2,
                                  "MaximumEventAgeInSeconds": 3600}}))
PY
)

# ── 1. El rol que Scheduler usa para invocar ────────────────────────────────
if aws_ iam get-role --role-name "$ROL" >/dev/null 2>&1; then
  echo "   = rol $ROL (ya existe)"
else
  echo "▶ Creando el rol $ROL"
  aws_ iam create-role --role-name "$ROL" \
    --description "EventBridge Scheduler invoca el informe de alertas de WatchTower" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "scheduler.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": "'"$ACCOUNT"'"}}
      }]
    }' >/dev/null
fi

# Una sola función, una sola acción. Un rol de scheduler con lambda:* sobre `*`
# es una llave maestra esperando que alguien la reutilice "para otra cosita".
aws_ iam put-role-policy --role-name "$ROL" \
  --policy-name invocar-informe-alertas \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": ["'"$FN_ARN"'", "'"$FN_ARN"':*"]
    }]
  }' >/dev/null
echo "   ✓ permiso del rol: invocar sólo $FUNCION"

# IAM tarda unos segundos en propagar un rol recién creado y Scheduler valida
# el rol al crear el horario. Sin esta espera el primer intento falla con
# ValidationException y parece un error de permisos que no es.
sleep 10

# ── 2. El horario ───────────────────────────────────────────────────────────
if aws_ scheduler get-schedule --name "$HORARIO" >/dev/null 2>&1; then
  ACCION="update-schedule"; VERBO="Actualizando"
else
  ACCION="create-schedule"; VERBO="Creando"
fi

echo "▶ $VERBO el horario $HORARIO"
aws_ scheduler "$ACCION" --name "$HORARIO" \
  --description "WatchTower · informe de alertas al equipo KYT, lunes 09:00 Chile" \
  --schedule-expression "$CRON" \
  --schedule-expression-timezone "$ZONA" \
  --flexible-time-window '{"Mode":"OFF"}' \
  --state ENABLED \
  --target "$TARGET" >/dev/null

echo "✅ Listo."
echo
"$0" --estado
