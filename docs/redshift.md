# Paso 5 — conectar Redshift

De una transacción a un cliente. Es el paso que cierra la primera mitad del
ciclo: sin él tenemos 119 requerimientos identificados y a nadie a quién
pedirle la documentación.

Todo lo de arriba (leer el correo, identificar el partner, extraer el ID,
validarlo) sigue corriendo sin red y sin credenciales. Este paso es el único
que cruza la frontera, y está aislado en dos archivos: `relevo/redshift.py`
(la conexión) y `relevo/cliente.py` (lo que se decide con la respuesta).

---

## 1. Cómo se conecta — y por qué no hay host ni contraseña

Por la **Data API** de AWS, con credenciales IAM. El cluster tiene
`PubliclyAccessible: false` y su security group sólo acepta tráfico interno: una
conexión TCP clásica (psycopg2, DBeaver) no se establece nunca desde afuera. La
Data API habla con un endpoint HTTPS de AWS y el cluster nunca se expone.

| | |
|---|---|
| Cluster | `compliance-redshift-cluster` |
| Base | `dev` (pero los datos están en `db_prod`, ver abajo) |
| DbUser | `awsuser` |
| Región | `us-east-1` |

Nada de eso hay que configurarlo: son los defaults de `relevo/redshift.py`. Lo
único que va en `~/relevo/.env` es qué credenciales usar:

```
AWS_PROFILE=compliance-admin
AWS_REGION=us-east-1
```

Si la sesión venció: `aws sso login --profile compliance-admin`

**Para el 24/7 esto no alcanza.** Una sesión SSO dura horas y después el
servicio empieza a devolver `error` en cada resolución (la ingesta de correo
sigue igual: son independientes). Cuando el proyecto viva en infra, hay que
crear el usuario IAM de servicio con `redshift-data:*` y
`redshift:GetClusterCredentials`, y poner `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` en vez de `AWS_PROFILE`.

**`awsuser` es superusuario del cluster**: puede borrar tablas de producción.
Mientras se use, la única barrera es `_solo_lectura()` en el código, que rechaza
cualquier sentencia que no empiece en SELECT o WITH. Lo correcto para dejarlo
corriendo permanente es un usuario de base acotado:

```sql
CREATE USER relevo_ro PASSWORD DISABLE;
GRANT USAGE ON SCHEMA "transaction", "customer" TO relevo_ro;
GRANT SELECT ON "db_prod"."transaction"."transaction" TO relevo_ro;
GRANT SELECT ON "db_prod"."customer"."customer" TO relevo_ro;
```

y después `REDSHIFT_DBUSER=relevo_ro` en el `.env`.

Comprobar:

```bash
~/relevo/.venv/bin/python ~/relevo/servicio/explorar-redshift.py
```

---

## 2. Dónde vive cada identificador — resuelto el 2026-09-06

Todo sale de **una** tabla, `db_prod.transaction.transaction`, con LEFT JOIN a
`db_prod.customer.customer`:

| Llave | Partner | Dónde vive | Verificado |
|---|---|---|---|
| `rmt` | dLocal | `treasury.cash_call.cash_call_id` | 38 de 38 |
| `nium_payout_id` | Nium | `transaction.payment_id` (prefijo `PY`) | 18 de 18 |
| `transfer_no` | OZ Câmbio | `transaction.transaction_id` — es **nuestro** id | 10 de 10 |
| `cc_transaction_id` | Currencycloud | `currency_cloud.notification.message_json` → `$.related_entity_short_reference` | 44 |
| `cc_external_id` | Currencycloud | **sin encontrar** | 0 de 9 |

**El `RMT` es el `cash_call_id`.** `RMT028020236` es el cash call `28020236` con el número
relleno a 9 dígitos: el prefijo y el cero son formato de impresión, no parte del dato. Y
`cash_call.external_reference_number` es **nuestro `transaction_id`**. Buscar así es una igualdad
de entero contra la clave — 38 de 38 en ~3 s, contra 37 de 38 en ~6 s cuando se buscaba con
`REGEXP_REPLACE` sobre `transaction.payment_reference_number`. El que fallaba lo hacía porque una
transacción puede tener **varios cash calls** (vimos una con un `PAID` y un `RELEASED`) y la fila
de `transaction` arrastra sólo uno; el RMT dice cuál. De regalo viene `cc.status`
(PAID / RELEASED / REJECTED), que es el estado real de la plata.

**El `IF-` de Currencycloud no tiene columna propia**: vive dentro del payload del webhook, en
`message_json -> related_entity_short_reference` — 1.440.364 de las 1.804.618 filas de
`notification`. Del mismo payload sale `account_id`, que ata con `customer_bind` y de ahí al
`global66_customer_id` y al correo. El `GROUP BY` de esa consulta no es cosmético: un mismo `IF-`
genera varias notificaciones (`PENDING`, `REJECT`, …) del **mismo** cliente, y sin agrupar el
`LIMIT 2` las leería como `ambiguo` y frenaría el caso por una razón falsa.

Ojo con dos cosas al escribir consultas nuevas contra estas tablas:
`transaction.transaction` **no tiene** `external_reference_number` —sólo
`payment_reference_number`— y el join correcto a `cash_call` es contra `transaction_id`.
Redshift tampoco tiene `JSON_EXTRACT` / `JSON_UNQUOTE`: se escribe
`JSON_EXTRACT_PATH_TEXT(col, 'clave', TRUE)`, con ese último `TRUE` que devuelve NULL en vez de
reventar cuando la fila no es JSON válido.

Cuatro cosas que costaron y que conviene no volver a descubrir:

1. **La base guarda `RMT028172225`** —con prefijo y con el cero de relleno— y
   nosotros normalizamos a `28172225`. Era la «pregunta 2 de fase 0» de
   `validar.py`, y la respuesta invalida el supuesto que estaba escrito ahí. La
   consulta normaliza del lado de la base con
   `REGEXP_REPLACE(col, '^[A-Za-z]*0*', '')`.
2. **No castear la columna a `bigint`**: hay filas con referencias de 27 dígitos
   y revienta con `Overflow`. La comparación es de texto.
3. **El join a `customer` va con LEFT.** Hay clientes —los B2B entre otros— sin
   fila ahí, y un inner join convertía «encontré la transacción pero no al
   cliente» en `sin_match`, que se lee como «el identificador está mal». Con
   LEFT sale `incompleto`, que es la verdad. El correo se toma con `COALESCE`:
   `transaction.transaction` ya trae `customer_email`.
4. **No filtrar por `partner`.** Probarlo contra `partner.partner_transaction`
   con `partner = 'DLocal'` daba falsos negativos.

### Lo que falta: `cc_external_id`

Son 9 casos: los correos de Currencycloud que **no** traen el `IF-`. El segmento del medio de
`20260903_1031036096458_...` no es un `account_number` de `currency_cloud.funding_account`, así
que hay que preguntarle a quien genera ese External ID cómo se compone.

Callejones ya recorridos, para no repetirlos: `partner.partner_transaction` guarda para `CCLOUD`
un **UUID** en `payment_id` y su última fila es de mayo de 2026 —el volumen actual de
Currencycloud no pasa por ahí—; y tampoco está en `transaction.transaction`
(`payment_id`, `payment_reference_number`, `request_id`, `authorization_code`,
`beneficiary_generated_id`).

### Cómo se descubrió (para la próxima llave)

Primero por nombre de columna, que es gratis:

```bash
~/relevo/.venv/bin/python ~/relevo/servicio/explorar-redshift.py --columnas --base db_prod
```

Después probando **valores reales de la casilla** contra las candidatas. Esto sí
toca datos y es lo único que puede salir caro (un `WHERE` sobre una columna que
no es sort key escanea la tabla), así que va acotado y con timeout:

```bash
~/relevo/.venv/bin/python ~/relevo/servicio/explorar-redshift.py --sondear --base db_prod --esquema transaction --max-sondeos 50
```

Y cuando el valor **no** calza, la pregunta que sigue es en qué formato lo
guarda la base. Para eso:

```bash
~/relevo/.venv/bin/python ~/relevo/servicio/explorar-redshift.py \
  --tabla db_prod.partner.partner_transaction --muestra 3 \
  --ver transaction_id,partner,payment_id,payment_reference_number \
  --donde partner=DLocal --orden created_date
```

Eso fue lo que destrabó todo: mostró `RMT028190738` donde nosotros buscábamos
`28190738`.

Sale algo así:

```
── transfer_no ───────────────────────────────────
  7 columnas candidatas por nombre
  sondeando con ['14915109', '14820051']
    ✔ ENCONTRADO  "db_prod"."transaction"."transaction"."transaction_id"  =  14915109   (1752 ms)
```

**Ojo con el costo.** Cada sondeo es un `WHERE` sobre una columna que no es
sort key, o sea un escaneo. Va con tope (`--max-sondeos`), con timeout, y de a
un valor por columna.

---

## 3. Escribir las consultas

En `consultas.json`, una por tipo de llave. El SQL puede leer de donde sea,
pero tiene que cumplir tres cosas —y hay un test que las verifica:

1. **Alias del contrato.** Como mínimo `cliente_id`, `cliente_nombre` y
   `cliente_correo`. Lo demás (`cliente_documento`, `tx_monto`,
   `tx_beneficiario`, …) es opcional y se usa para verificar el match. Lo que
   venga con otro nombre se guarda en `extra` y se muestra igual.
2. **El valor va como parámetro con nombre `:valor`**, nunca pegado al SQL.
   Viene de un correo escrito por un tercero. La Data API manda los parámetros
   como texto, así que una columna numérica necesita cast: `:valor::bigint`.
3. **Termina en `LIMIT 2`.** No es un detalle: dos filas significa `ambiguo`, y
   un caso ambiguo no dispara ningún correo.
4. **Nombre de tres partes**: `"db_prod"."esquema"."tabla"`. Los datos están en
   el datashare `db_prod`, no en la base a la que se conecta la Data API
   (`dev`). Sin eso da `Relation ... does not exist`.

Después `"activa": true` y listo.

```bash
~/relevo/.venv/bin/python -m unittest discover -s ~/relevo/tests -q   # valida consultas.json
```

---

## 4. Los seis estados

| Estado | Qué pasó | Qué hacer |
|---|---|---|
| `encontrado` | una fila, con correo de cliente | pedirle la documentación |
| `incompleto` | está la transacción, no el correo del cliente | se arregla en la base, no acá |
| `ambiguo` | volvieron 2 filas | desempatar a mano; **no se envía nada** |
| `sin_match` | el ID no está en la base | o no lo guardamos, o vino corrupto |
| `sin_consulta` | no hay SQL activo para esa llave | falta configurar |
| `error` | la consulta falló | casi siempre red o permisos |

Además, cuando el correo del partner trae beneficiario o monto, se cruzan contra
la fila que volvió. Si no coinciden aparece **no coincide** en la tabla: el
identificador calzó pero el match es sospechoso. No lo descarta solo — lo marca.

---

## 5. Cómo corre

- **Solo, cada vuelta de la ingesta** (60 s), sobre lo que todavía no está
  resuelto. En régimen son cero o dos consultas por vuelta. Si Redshift está
  caído, la ingesta sigue leyendo correo: eso es lo que no se puede perder.
- **A pedido**, con el botón *Buscar clientes* del front, o
  `POST /api/resolver?limite=200` (`&forzar=true` para rehacer lo cacheado).

El resultado vive en `datos/clientes.jsonl`, una línea por `(llave, valor)`. El
front lo lee de ahí: una consulta lenta nunca cuelga el pintado de la tabla.

---

## 6. Ver la pantalla antes de tener credenciales

```bash
~/relevo/.venv/bin/python ~/relevo/servicio/ensayo-redshift.py            # sólo reporta
~/relevo/.venv/bin/python ~/relevo/servicio/ensayo-redshift.py --sembrar  # llena el caché con datos FALSOS
~/relevo/.venv/bin/python ~/relevo/servicio/ensayo-redshift.py --limpiar  # borrarlos
```

Arma una base de mentira a partir de los correos reales y reparte los cinco
estados, para ver cómo queda la tabla. **Acordate de `--limpiar` antes de
conectar la base de verdad.**

---

## 7. Si algo falla

| Mensaje | Causa |
|---|---|
| `sin acceso · la sesión venció` | `aws sso login --profile compliance-admin` |
| `AccessDeniedException` mencionando `GetClusterCredentials` | falta ese permiso puntual en la política |
| `AccessDeniedException` a secas | faltan los permisos `redshift-data:*` |
| `Relation ... does not exist` | faltó el nombre de tres partes con `db_prod` |
| `Overflow (Long valid range ...)` | se está casteando a `bigint` una columna con basura larga |
| la consulta queda en `STARTED` para siempre | el cluster está pausado |

Los tiempos normales: **2-6 segundos por consulta**. Son escaneos sobre 14,9
millones de filas sin sort key que ayude. Para nuestro volumen (un puñado de
transacciones nuevas por hora) alcanza de sobra; si algún día no alcanza, la
salida es materializar una tabla chica de `(referencia, customer_id, email)`.
