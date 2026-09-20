# API externa de casos — guía de administración

Cómo dar de alta un consumidor, cambiarle los permisos y revocarlo.
Guía interna: **no se comparte con quien integra.**

---

## Dónde vive todo

| Qué | Dónde |
|---|---|
| Las claves | Secrets Manager: `compliance-redshift-reports/api-externa-keys` |
| Quién puede tocarlas | Perfil `compliance-admin`, región `us-east-1` |
| El código | `lambda/api_externa.py` (permisos y contrato), `lambda/api_handler.py` (rutas `/v1`) |

Una clave por consumidor, nunca una compartida. Es lo que permite saber quién
hizo cada cosa y cortarle el acceso a uno sin romperle el servicio al resto.

## La forma del secreto

```json
{
  "sistema-casos": {
    "clave": "wt_…",
    "permisos": ["casos:leer", "casos:escribir", "casos:comunicar"],
    "activo": true
  },
  "tablero-fraude": {
    "clave": "wt_…",
    "permisos": ["casos:leer"],
    "activo": true
  }
}
```

El nombre de la entrada es lo que queda firmado en el histórico como
`api:sistema-casos`. Poné nombres que digan **qué sistema es**, no quién lo
pidió: la persona cambia de equipo, el sistema queda.

### Los tres permisos

| Permiso | Habilita |
|---|---|
| `casos:leer` | listar, ver detalle, ver comunicaciones, consultar alertas |
| `casos:escribir` | crear casos, cambiar estado/prioridad/asignación, notas |
| `casos:comunicar` | **enviarle correo al cliente** |

`casos:comunicar` está separado a propósito. Es el único que le escribe a una
persona real: se puede dar gestión completa del caso sin dar esa capacidad.
Si dudás, no lo des — se agrega después en un minuto.

> **Forma corta.** `{"nombre": "clave"}` (un string en vez del objeto) da
> **sólo lectura**. Está pensado para un tablero: escribir tiene que ser una
> decisión explícita, no un descuido de tipeo.

---

## Dar de alta un consumidor

```bash
SEC=compliance-redshift-reports/api-externa-keys
NOMBRE=tablero-fraude          # cambiá esto
PERMISOS='["casos:leer"]'      # y esto

aws secretsmanager get-secret-value --secret-id $SEC \
  --profile compliance-admin --region us-east-1 \
  --query SecretString --output text > /tmp/keys.json

python3 - <<PY
import json, secrets
d = json.load(open("/tmp/keys.json"))
if "$NOMBRE" in d:
    raise SystemExit("Ya existe ese consumidor: usá otro nombre o rotá la clave.")
d["$NOMBRE"] = {"clave": "wt_" + secrets.token_hex(24),
                "permisos": json.loads('$PERMISOS'), "activo": True}
json.dump(d, open("/tmp/keys.json", "w"), indent=2)
print("creado:", "$NOMBRE")
PY

aws secretsmanager put-secret-value --secret-id $SEC \
  --secret-string file:///tmp/keys.json \
  --profile compliance-admin --region us-east-1 --query Name --output text

rm -f /tmp/keys.json
```

Después **hay que refrescar la caché** (ver abajo) y recién ahí entregar la
clave.

### Cómo entregar la clave

Sacala sola, sin mostrar el resto del secreto:

```bash
aws secretsmanager get-secret-value --secret-id compliance-redshift-reports/api-externa-keys \
  --profile compliance-admin --region us-east-1 --query SecretString --output text \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['tablero-fraude']['clave'])"
```

Mandala por un canal donde el mensaje no quede para siempre: un DM de Slack se
borra, un ticket de Jira no. **Nunca por correo ni en un documento compartido.**

---

## Cambiar permisos

```bash
SEC=compliance-redshift-reports/api-externa-keys
aws secretsmanager get-secret-value --secret-id $SEC --profile compliance-admin \
  --region us-east-1 --query SecretString --output text > /tmp/keys.json

python3 - <<'PY'
import json
d = json.load(open("/tmp/keys.json"))
# Agregar un permiso:
d["sistema-casos"]["permisos"] = ["casos:leer", "casos:escribir", "casos:comunicar"]
# Quitar uno: sacalo de la lista.
json.dump(d, open("/tmp/keys.json", "w"), indent=2)
PY

aws secretsmanager put-secret-value --secret-id $SEC \
  --secret-string file:///tmp/keys.json --profile compliance-admin --region us-east-1
rm -f /tmp/keys.json
```

Un permiso que no exista se ignora en silencio al leer el secreto: si escribís
`casos:escrivir`, la clave queda **sin** ese permiso. Por eso hay que verificar
después de cada cambio (más abajo).

## Revocar

```bash
# Suave: deja el registro de que existió.
d["sistema-casos"]["activo"] = False

# Definitiva: lo borra del secreto.
del d["sistema-casos"]
```

Las dos bloquean el acceso igual. Preferí `activo: false` salvo que quieras
reusar el nombre: deja rastro de que ese consumidor existió, y el histórico de
los casos sigue teniendo acciones firmadas a su nombre.

## Rotar una clave

Misma operación que dar de alta, pero pisando `clave`. **No hay período de
gracia**: apenas se refresca la caché, la clave vieja deja de servir. Coordiná
el momento con quien integra.

---

## Refrescar la caché — el paso que se olvida

Las claves se cachean **por contenedor de Lambda**. Un cambio en el secreto no
tiene efecto inmediato: entra cuando AWS recicla los contenedores, que puede
tardar minutos u horas.

Para forzarlo:

```bash
aws lambda update-function-configuration \
  --function-name compliance-redshift-reports-api \
  --environment "Variables={$(aws lambda get-function-configuration \
      --function-name compliance-redshift-reports-api --profile compliance-admin \
      --region us-east-1 --query 'Environment.Variables' --output json \
    | python3 -c "
import json,sys,time
v=json.load(sys.stdin); v['FORZAR_RELOAD']=str(int(time.time()))
print(','.join(f'{k}={j}' for k,j in v.items()))")}" \
  --profile compliance-admin --region us-east-1 --query LastUpdateStatus --output text

aws lambda wait function-updated --function-name compliance-redshift-reports-api \
  --profile compliance-admin --region us-east-1
```

Cambiar cualquier variable de entorno obliga a Lambda a levantar contenedores
nuevos. Un `./deploy.sh` hace lo mismo, pero esto es más rápido y no toca
código.

**Esto corta en los dos sentidos:** una clave revocada puede seguir
funcionando unos minutos si no refrescás. Si estás revocando por un incidente,
refrescá sí o sí y verificá.

---

## Verificar después de cada cambio

```bash
API=https://qwvd2t33uc.execute-api.us-east-1.amazonaws.com
K='wt_…'   # la clave a probar

curl -s -o /dev/null -w "leer     → %{http_code}\n" -H "x-api-key: $K" "$API/v1/casos?por_pagina=1"
curl -s -o /dev/null -w "escribir → %{http_code}\n" -X POST -H "x-api-key: $K" \
     -H 'Content-Type: application/json' -d '{}' "$API/v1/casos"
```

Cómo leer los códigos:

| Código | Qué significa |
|---|---|
| `200` / `201` | tiene el permiso |
| `400` | tiene el permiso, faltaron datos en el cuerpo — **cuenta como que puede** |
| `401` | la clave no existe, está mal escrita o está revocada |
| `403` | la clave es válida pero le falta ese permiso |

Un `400` en la prueba de escritura es **éxito**: pasó la autorización y se
quedó en la validación del cuerpo. No crea ningún caso.

---

## Qué mirar si algo falla

**Todos reciben 401, incluso claves buenas.** Casi siempre es que la Lambda no
puede leer el secreto. Se ve en CloudWatch:

```
[api-externa] no pude leer las claves (compliance-redshift-reports/api-externa-keys): ...
```

Es deliberado que falle así: **sin el secreto legible no se autoriza a nadie.**
Preferible que la integración se caiga a que quede abierta por un error de
permisos que nadie mira.

**Un consumidor recibe 401 y otros no.** Su clave no está en el secreto, está
mal copiada o quedó `activo: false`.

**Devuelve 403 en algo que debería poder.** Revisá que el permiso esté bien
escrito en el secreto (un typo lo hace desaparecer) y que hayas refrescado.

**Las rutas `/v1` devuelven 404 en todo.** El módulo `api_externa.py` no viajó
en el paquete. En CloudWatch: `[api] api_externa no disponible`. Se arregla con
un `./deploy.sh`. También es deliberado: si el módulo falta, las rutas no
existen — **no** se degradan a "sin autenticación".

---

## Lo que esta clave NO resuelve

La ruta `$default` del API Gateway está en `Auth: NONE` y el authorizer de
Cognito existe pero no está conectado a ninguna ruta. **Los endpoints internos
responden sin credenciales**: alguien con la URL puede hacer por `/cases/...`
lo mismo que `/v1` pide clave para hacer.

O sea: la clave **identifica, audita y versiona el contrato**, pero no impide
el acceso. Cada acción por `/v1` queda firmada como `api:<consumidor>` y no
como un correo que cualquiera puede escribir en el cuerpo, que ya es bastante
más de lo que había. Pero no es una frontera.

Cerrarlo de verdad es conectar el authorizer de Cognito a las rutas internas, y
está bloqueado por dos cosas:

1. El rol `compliance-admin` no tiene `apigateway:POST` ni `apigateway:PATCH`.
2. El frontend omite el header `Authorization` a propósito por la
   configuración de CORS, así que conectarlo lo rompe hasta ajustar esa parte.

Es el momento natural para hacerlo cuando se arme el frontend nuevo: que nazca
con el login adentro.
