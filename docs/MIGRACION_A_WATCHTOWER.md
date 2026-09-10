# Migración de Relevo a WatchTower — especificación de implementación

**Objetivo:** que el ciclo RFI de corresponsales quede **operativo en la web**, dentro de
WatchTower, corriendo en Lambda + EventBridge. Hoy corre en el Mac de Benjamín con `launchd`
y un túnel de `ngrok`. Al terminar esto, **el Mac deja de ser parte del sistema**.

Ciclo completo a dejar funcionando:

```
correo del partner → identificar partner → clasificar → extraer ID → validar
   → resolver el cliente en Redshift → agrupar en caso → pedirle los documentos al cliente
   → recibir su respuesta y los adjuntos → recontactar por lo que falta → devolver al partner
```

Repo destino: `github.com/BMackenna-G66/compliance-redshift-reports` (WatchTower).
Repo origen: `~/relevo` (motor de extracción, 3.114 líneas, 104 tests que corren).

---

## 1. Regla de oro: réplica adaptada, no reuso

Relevo entra como **módulo nuevo**. No se reutiliza ninguna función ni ningún objeto de
WatchTower, y **no se toca ninguna ruta AML existente**. El ciclo RFI y la investigación AML
son procesos distintos y mezclarlos ensucia las dos bandejas.

Por qué la réplica y no el reuso: WatchTower tiene **cero tests** y un `api_handler.py` de
6.226 líneas. Una réplica cubierta por los 104 tests de Relevo es más segura que compartir
código con eso.

**Qué NO se toca, explícitamente:**

- `crm.cases`, `crm.case_notes`, `compliance.alerts` — los casos RFI no viven ahí.
- `poll_document_replies()` y su criterio IMAP.
- `send_manual_document_request()`, `_register_email_ref()`, `EMAIL_TEMPLATE_CATALOG`.
- Cualquier ruta existente de `api_handler.py`.

**Qué se replica adaptado** (se copia la *lógica*, se escribe código nuevo en el módulo):
el correo de solicitud de documentos, el token de correlación, el poller de respuestas, el
checklist de documentos, y el aviso a Slack.

---

## 2. Arquitectura: qué corre dónde

| Pieza | Dónde | Cómo se dispara |
|---|---|---|
| Motor de extracción | `lambda/relevo/` (paquete) | importado |
| Ingesta de correo | Lambda | EventBridge, cada 5 min |
| Resolución del cliente | Lambda → Redshift Data API | dentro de la ingesta |
| Poller de respuestas del cliente | Lambda | EventBridge, cada 10 min |
| Snapshot de la vista | Lambda | EventBridge, cada 5 min |
| API del módulo | rutas nuevas en `api_handler.py` | API Gateway + Cognito |
| Front del módulo | pestaña nueva en `frontend/index.html` | CloudFront |
| Datos operativos | **S3**, un objeto por registro — ver el desvío abajo | — |
| Espejo analítico | esquema `relevo` en Redshift (§18) | EventBridge, 12:45 UTC |

**Desvío respecto de §4, dicho acá para que no sorprenda:** los datos operativos quedaron en
**S3**, no en DynamoDB. El rol de esta cuenta tiene `dynamodb:CreateTable` en implicitDeny
—con cualquier nombre de tabla, verificado con `simulate-principal-policy`— así que las siete
tablas de §4 no se pueden crear sin pedir permisos nuevos. Los dos argumentos con los que §4
eligió Dynamo se sostienen igual en S3 (un objeto por registro es append-only de verdad, y S3
no depende del cluster); lo que se pierde es la consulta por clave de ordenamiento, que se
compensa con la jerarquía de la clave. El razonamiento completo está en el encabezado de
`lambda/relevo/deposito.py`. Migrar es reescribir sólo ese archivo.

**No hay proceso de larga duración.** Todo son invocaciones. La ingesta de Relevo hoy es un
demonio de 60 s; pasa a ser una invocación cada 5 min, que para el volumen de RFI sobra.

---

## 3. Lo que se copia tal cual

El motor es **stdlib pura de Python 3.10+**: no toca red ni disco salvo por el almacén, y no
tiene dependencias. Se copia sin cambios a `lambda/relevo/`:

| Archivo | Qué hace |
|---|---|
| `reglas.py`, `reglas.json` | **la fuente única de verdad**: partners, remitentes, pistas de asunto con peso, formatos, rangos, catálogo de 15 ítems, 8 campos de datos |
| `partner.py` | identifica al partner por `X-Original-Sender` |
| `clasificar.py` | accionable vs informativo, mirando asunto **y cuerpo** |
| `extraer.py` | extrae identificadores por regex declarativa |
| `validar.py` | rango, formato, normalización |
| `pipeline.py` | orquesta los pasos 1 a 4 |
| `html.py` | HTML → texto preservando tablas |
| `requerimiento.py` | qué pide el partner, en español, desde el catálogo con lista blanca |
| `transacciones.py` | una fila por identificador |
| `casos.py` | el caso, su estado derivado y el recontacto |
| `redshift.py` | Data API, guarda de sólo lectura, diagnóstico |
| `cliente.py` | los seis estados de resolución y la verificación cruzada |
| `gmail.py` | Gmail API: `history.list`, `messages.get` |

**No se copian:** `servicio.py` (el demonio de launchd) ni `vista.py`. Su función la
cumple la Lambda.

**Sí se copian, aunque no los use el ciclo:** `evaluar.py` y `fuentes.py`. Los importa
`tests/test_extraccion.py` (el golden set); si se dejan fuera, ese test se cae.

Los tests (`tests/test_extraccion.py`, `test_redshift.py`, `test_casos.py`) se copian a
`lambda/relevo/tests/` y **tienen que seguir pasando**. Corren sin dependencias.

`test_auth.py` **no se copia**: verifica el ID token del SSO propio de Relevo, y acá esa
función la cumple Cognito en el API Gateway (§10). Sus 21 pruebas necesitan `pyjwt[crypto]`
y en el origen quedaban saltadas, así que el total real siempre fue 104:

```bash
python3 -m unittest discover -s lambda/relevo/tests -q
# 104 tests, ~0,1 s
```

### Lo único que hay que reescribir del motor

Tres módulos leen archivos. Se les cambia el fondo por DynamoDB **manteniendo la interfaz**:

- `almacen.py` → `guardar(mensajes)` / `leer()`
- `cliente.py` → `leer_cache()` / `guardar_cache(resultados)`
- `casos.py` → `registrar(caso, accion, ...)` / `leer_acciones()`

Todos apuntan hoy a `RELEVO_DATOS`, así que el cambio está acotado a esas seis funciones.

---

## 4. Persistencia: DynamoDB

**No Redshift para datos operativos.** WatchTower ya intentó eso y se volvió atrás: ver
`migrate_redshift_to_dynamo.py`, cuyo docstring dice el motivo — *"para que sigan visibles
aunque el cluster esté pausado"* — y `AUTO_PAUSE` está en `true` por defecto en
`handler.py:114`. Además Redshift no tiene `UPSERT`, no exige claves primarias, sus `UPDATE`
son marcar-y-reescribir (piden `VACUUM`) y cada consulta cuesta 2-6 segundos.

Relevo encaja perfecto en Dynamo porque **su almacén sólo agrega y el estado se deriva**.

### Tablas

```
relevo_mensajes
  PK: message_id (S)
  attrs: thread_id, asunto, fecha, headers (M), cuerpo (S), recibido_en
  Nota: sólo agrega. La deduplicación es por la PK.

relevo_acciones
  PK: caso_id (S)   SK: cuando (S, ISO-8601 con offset)
  attrs: accion, quien, detalle (M)
  Nota: SÓLO AGREGA, nunca se actualiza ni se borra. Es el histórico auditable
        y de acá se deriva el estado del caso.

relevo_clientes
  PK: llave_valor (S)   -- "rmt|28172225"
  attrs: estado, motivo, cliente (M), verificacion (M), filas, ms, cuando
  Nota: caché de la resolución en Redshift. Se sobreescribe al re-resolver.

relevo_estado
  PK: clave (S)   -- "gmail_history_id", "watermark_poller", ...
  attrs: valor (S), actualizado_en

relevo_solicitudes
  PK: request_id (S)
  attrs: caso_id, correo, nombre, documentos (L), asunto, thread_id, ref,
         enviado (BOOL), error, cuando

relevo_procesados
  PK: message_id (S)
  attrs: caso_id, resultado, cuando
  Nota: ledger de deduplicación del poller de respuestas. Ver §7.

relevo_config
  PK: clave (S)   -- "politica_general", "politica_<partner>", "interruptores"
  attrs: valor (M)
```

`relevo_acciones` con clave compuesta permite traer el histórico de un caso en una sola
consulta. Los estados **no se guardan en ninguna parte**: se calculan.

---

## 5. Gmail

### Lectura — Gmail API, no IMAP

WatchTower usa IMAP y le funciona porque **filtra por su propio token en el asunto**. Relevo
no puede: los correos del partner no traen ningún token nuestro, hay que leerlos todos, y la
casilla tiene ~1.500 mensajes. `history.list` es lo único que da sincronización incremental.

```
GET /gmail/v1/users/me/history
    ?startHistoryId=<guardado>&historyTypes=messageAdded&maxResults=500
```

- **`historyTypes=messageAdded` es obligatorio.** Sin ese filtro, cualquier cambio de
  etiqueta —incluidos los que hace el poller de WatchTower— reaparece como mensaje nuevo.
- Si Gmail responde **404**, el `historyId` venció (los retiene ~una semana): resincronizar
  pidiendo el `historyId` del perfil.
- El `historyId` se persiste en `relevo_estado` **después** de guardar los mensajes, nunca
  antes: si la Lambda muere en medio, la próxima vuelta repite en vez de perder.

**`X-Original-Sender` es la pieza que sostiene todo.** El grupo de Google reescribe el `From`
(devuelve `compliance@global66.com` en el 100%), así que el remitente real sólo está en ese
header. Hay que pedirlo explícitamente:

```
GET /gmail/v1/users/me/messages/{id}?format=metadata
    &metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=X-Original-Sender
    &metadataHeaders=X-Original-From&metadataHeaders=Reply-To&metadataHeaders=Message-ID
```

El cuerpo (`format=full`) se baja **sólo** cuando las reglas del partner declaran ámbito
`cuerpo`. dLocal, Currencycloud, Nium y OZ lo declaran.

### Envío — Gmail API, no SMTP

Se manda por API y no por SMTP para poder **guardar el `threadId`**, así la respuesta del
cliente se correlaciona por hilo, que sobrevive a que el cliente edite el asunto. El token
en el asunto queda como segundo camino.

```
POST /gmail/v1/users/me/messages/send
Body: { "raw": "<MIME en base64url>" }
Respuesta: { "id": ..., "threadId": ... }   ← guardar threadId en relevo_solicitudes
```

### Credenciales

| Secreto | Qué es |
|---|---|
| `GMAIL_CLIENT_ID` | cliente OAuth de escritorio |
| `GMAIL_CLIENT_SECRET` | idem |
| `GMAIL_REFRESH_TOKEN` | token de la casilla `compliance.masivo@global66.com` |

Van a **Secrets Manager**, un secreto JSON, leído con el mismo patrón que
`_get_imap_password()` en WatchTower.

> **PASO HUMANO Y ÚNICO PRERREQUISITO.** El refresh token actual tiene scope
> `gmail.readonly`. Para enviar hace falta re-consentir con
> `https://www.googleapis.com/auth/gmail.send` (o `gmail.modify`, que cubre las dos).
> Se hace con `obtener_token.py` del repo de Relevo, cambiando la constante `SCOPE`.
> Son dos minutos y **hasta que esté, la fase de envío no funciona** — la lectura y la
> resolución sí.

El access token se obtiene con el refresh token:

```
POST https://oauth2.googleapis.com/token
grant_type=refresh_token&refresh_token=...&client_id=...&client_secret=...
```

Dura una hora. Cachearlo en memoria del contenedor de Lambda.

### Cuota

Gmail devuelve **403 con "Quota exceeded"**, no 429. Hay que tratar ese 403 como reintentable
con espera creciente; si no, se confunde con un problema de permisos.

---

## 6. Redshift: resolver el cliente

Se conecta por la **Data API** con IAM (`boto3`, cliente `redshift-data`). No hay host ni
contraseña: el cluster tiene `PubliclyAccessible: false`.

```
ClusterIdentifier = compliance-redshift-cluster
Database          = dev
DbUser            = awsuser
Región            = us-east-1
```

**Nombre de tres partes obligatorio**: los datos están en el datashare `db_prod`, no en `dev`.
Sin eso da `Relation ... does not exist`.

### Las cuatro consultas verificadas

Medido el 2026-09-06 con valores reales de la casilla: **110 de 110 resolvieron a cliente con
correo.** El valor viaja **siempre** como parámetro con nombre `:valor`.

**`rmt` (dLocal) — 38 de 38.** El RMT **es** el `cash_call_id`: `RMT028020236` es el cash
call `28020236` relleno a 9 dígitos; el prefijo y el cero son formato de impresión, no dato.
Y `cash_call.external_reference_number` es **nuestro** `transaction_id`.

```sql
SELECT COALESCE(c.customer_id, t.customer_id) AS cliente_id,
       NULLIF(TRIM(COALESCE(c.company_name,'') || ' ' || COALESCE(c.name,'') || ' ' ||
              COALESCE(c.last_name,'')), '') AS cliente_nombre,
       COALESCE(c.email, t.customer_email) AS cliente_correo,
       c.country AS cliente_pais,
       t.destiny_amount AS tx_monto, t.destiny_currency AS tx_moneda,
       t.start_date AS tx_fecha, t.tx_status AS tx_estado,
       t.beneficiary_name AS tx_beneficiario, t.remitter_name AS tx_remitente,
       t.transaction_id AS tx_id, t.payment_id AS ref_partner,
       cc.cash_call_id, cc.status AS estado_cash_call,
       cc.product_reference_number AS ref_nuestra
FROM "db_prod"."treasury"."cash_call" cc
LEFT JOIN "db_prod"."transaction"."transaction" t
       ON t.transaction_id = cc.external_reference_number
LEFT JOIN "db_prod"."customer"."customer" c ON c.customer_id = t.customer_id
WHERE cc.cash_call_id = :valor::bigint
LIMIT 2
```

**`nium_payout_id` (Nium) — 18 de 18.** Se guarda con prefijo `PY`. La comparación va
anclada al prefijo **a propósito**: dLocal usa la misma columna con ids numéricos de 9
dígitos, y comparar sin prefijo abriría un cruce entre partners.

```sql
SELECT <mismas columnas de cliente y tx que arriba>
FROM "db_prod"."transaction"."transaction" t
LEFT JOIN "db_prod"."customer"."customer" c ON c.customer_id = t.customer_id
WHERE t.payment_id = 'PY' || :valor
LIMIT 2
```

**`transfer_no` (OZ Câmbio) — 10 de 10.** El "transfer number" de OZ **es nuestro
`transaction_id`**, no un id del partner.

```sql
SELECT <mismas columnas>, t.payment_reference_number AS ref_nuestra
FROM "db_prod"."transaction"."transaction" t
LEFT JOIN "db_prod"."customer"."customer" c ON c.customer_id = t.customer_id
WHERE t.transaction_id = :valor::bigint
LIMIT 2
```

**`cc_transaction_id` (Currencycloud) — 44 de 44.** El `IF-` **no tiene columna propia**:
vive dentro del payload del webhook, en `message_json -> $.related_entity_short_reference`
(1.440.364 de 1.804.618 filas). Del mismo payload sale `account_id`, que ata con
`customer_bind` y de ahí al `global66_customer_id` y al correo. **Declara timeout de 180 s**:
escanea 1,8 M de filas con función JSON, tarda 13-18 s.

```sql
SELECT c.global66_customer_id AS cliente_id,
       NULLIF(TRIM(COALESCE(cu.company_name,'') || ' ' || COALESCE(cu.name,'') || ' ' ||
              COALESCE(cu.last_name,'')), '') AS cliente_nombre,
       JSON_EXTRACT_PATH_TEXT(c.customer_data, 'customer_email', TRUE) AS cliente_correo,
       cu.country AS cliente_pais,
       MAX(n.amount_generated) AS tx_monto, MAX(n.currency_generated) AS tx_moneda,
       MAX(n.arrival_time) AS tx_fecha,
       LISTAGG(DISTINCT n.notification_type, ' + ') AS tx_estado,
       MAX(n.sender_name_generated) AS tx_remitente,
       c.short_reference AS ref_cc, COUNT(*) AS notificaciones
FROM "db_prod"."currency_cloud"."notification" n
LEFT JOIN "db_prod"."currency_cloud"."customer_bind" c
       ON c.currency_cloud_customer_id = JSON_EXTRACT_PATH_TEXT(n.message_json, 'account_id', TRUE)
LEFT JOIN "db_prod"."customer"."customer" cu ON cu.customer_id = c.global66_customer_id
WHERE JSON_EXTRACT_PATH_TEXT(n.message_json, 'related_entity_short_reference', TRUE) = :valor
GROUP BY 1, 2, 3, 4, 10
LIMIT 2
```

**`cc_external_id` (Currencycloud) — SIN RESOLVER, 9 casos.** Queda inactiva. El segmento del
medio de `20260903_1031036096458_...` no es un `account_number` de
`currency_cloud.funding_account`. Hay que preguntarle a quien genera ese External ID cómo se
compone. Callejones ya recorridos, para no repetirlos: `partner.partner_transaction` guarda
para `CCLOUD` un UUID en `payment_id` y su última fila es de mayo de 2026; y tampoco está en
`transaction.transaction` (`payment_id`, `payment_reference_number`, `request_id`,
`authorization_code`, `beneficiary_generated_id`).

### Reglas que no se pueden romper

1. **`LIMIT 2` en toda consulta.** Dos filas significa `ambiguo` y un caso ambiguo **no
   dispara ningún correo**. Mandarle a un cliente el requerimiento de otro es peor que no
   mandar nada.
2. **Devolver al menos** `cliente_id`, `cliente_nombre`, `cliente_correo`. Lo que venga con
   otro nombre va a `extra` y se muestra igual.
3. **Sólo lectura, verificado en código.** `awsuser` es **superusuario del cluster**. La
   guarda de `redshift.py` rechaza toda sentencia que no empiece en `SELECT` o `WITH` y
   rechaza el `;` que permitiría encadenar una segunda. **No sacarla.** Lo correcto es además
   crear un DbUser acotado:

   ```sql
   CREATE USER relevo_ro PASSWORD DISABLE;
   GRANT USAGE ON SCHEMA "transaction", "customer", "treasury", "currency_cloud" TO relevo_ro;
   GRANT SELECT ON "db_prod"."transaction"."transaction" TO relevo_ro;
   GRANT SELECT ON "db_prod"."customer"."customer" TO relevo_ro;
   GRANT SELECT ON "db_prod"."treasury"."cash_call" TO relevo_ro;
   GRANT SELECT ON "db_prod"."currency_cloud"."notification" TO relevo_ro;
   GRANT SELECT ON "db_prod"."currency_cloud"."customer_bind" TO relevo_ro;
   ```
   y poner `REDSHIFT_DBUSER=relevo_ro`.

### Cluster pausado

`AUTO_PAUSE` queda **configurable igual que en WatchTower**. El cluster hoy se mantiene
prendido 24/7, pero el módulo tiene que tolerar que no lo esté:

- **Nunca despertar el cluster desde la ingesta.** Un correo no lo justifica.
- Si la consulta falla porque el cluster está dormido, o queda en `STARTED` más allá del
  timeout, la resolución **se encola y se reintenta en la próxima vuelta**. El caso queda en
  `sin_cliente` y se resuelve solo cuando haya disponibilidad.
- La lectura de correo **no se ve afectada**: son independientes y eso es lo que no se puede
  perder.

---

## 7. El caso

### Grano

El grano es el que **el partner ya usa**:

- si el correo trae número de caso del partner → `(partner, caso_partner)`
- si no → `(partner, llave, valor)`

Currencycloud manda número de caso en 62 de 62, Nium en 14 de 25, dLocal y OZ nunca. Eso
colapsa las 6 transacciones del cliente 3950037 en **un** caso de Nium: se le escribe una
vez, no seis. Medido: 131 transacciones → 122 casos → 97 clientes.

El id es **estable** —se deriva de esos campos y de nada que cambie al llegar un correo— y es
la clave de `relevo_acciones`:

```
nium:caso:1088170
dlocal:rmt:28172225
```

### El estado se deriva, no se guarda

Lo que se guarda son las **acciones**. El estado sale de ahí. Un estado mutable se
desincroniza en silencio; un registro que sólo agrega se puede auditar.

```
ACCIONES = [pedido_enviado, recontactado, respuesta_parcial, respuesta_recibida,
            devuelto, cerrado, sin_respuesta, descartado]
TERMINALES = [devuelto, cerrado, sin_respuesta, descartado]
CONTACTOS  = [pedido_enviado, recontactado]     # suman intento
```

Dos reglas, en este orden:

1. **Las terminales son pegajosas.** Un caso cerrado no vuelve al ruedo porque alguien
   registre otra cosa.
2. **Entre las no terminales manda la última en el tiempo**, no "la más avanzada". El ciclo
   **no es lineal**: pedido → parcial → recontacto significa *esperando de nuevo*. Un `max()`
   por posición diría "el cliente ya respondió", que es falso.

Si no hay acciones, el estado se deriva del caso: `informativo` (no accionable) →
`sin_cliente` → `sin_correo` → `listo_para_pedir`.

### Recontacto

Todo derivado de contar acciones: `intentos`, `ultimo_contacto`, `proximo_contacto`,
`vencido`, `agotado`, y **`faltantes` = lo pedido menos lo recibido**, que es lo que permite
recontactar sólo por el resto. Verificado con un caso real de dLocal: pidió 6 documentos, el
cliente mandó 1, el sistema sabe los 5 que faltan.

**Dos mantenedores, con esta precedencia:**

```
plazo escrito en el correo del partner       ← lo más específico (14 casos lo traen)
        ↓  si no hay
mantenedor del partner  (relevo_config: politica_<partner>)
        ↓  si no hay
mantenedor general      (relevo_config: politica_general)
                         por defecto: 3 días hábiles, 3 intentos
```

Los días son **hábiles** y sin calendario de feriados: errar por un día no rompe nada y un
calendario chileno no vale la pena acá.

### El eje cliente — el 360

Un cliente, todos sus casos, **un solo pedido**. Es lo que evita el pedido repetido: 14
clientes tienen más de un caso abierto, 32 de las 110 transacciones caen ahí. La etapa del
cliente es la **del caso menos avanzado** que siga vivo: lo que hay que mirar es si al
cliente le falta algo, no si algo avanzó.

---

## 8. El correo al cliente

**No hay plantilla fija de RFI.** El contenido se adapta a lo que pide cada partner, que es
justamente lo que Relevo extrae y traduce. Se replica el **formato/layout** HTML de
WatchTower y se carga con la información extraída:

- los ítems que pidió el partner, en español, desde el catálogo de 15 con **lista blanca**;
- los datos de la operación —monto, moneda, fecha, beneficiario, remitente— para que el
  cliente sepa de qué le hablan;
- el plazo, cuando el partner lo dio.

**Sin formulario PDF adjunto**: no es una solicitud KYC.

> **La lista blanca no se negocia.** El resumen se compone de estructura extraída, nunca de
> texto libre generado. Un requerimiento inventado que el partner no pidió es un incidente
> de compliance, no un typo. Lo que no está en el catálogo se muestra **textual** para
> redacción manual: hoy 60 de 89 casos accionables tienen lista concreta; los otros 27 se
> redactan a mano y son el bucle de mejora del catálogo.

### Token de correlación

```
Asunto: Solicitud de información — Global66 [rfi: xxxxxxxx]
```

**Tiene que ser `rfi:` y no `ref:`.** El poller de WatchTower busca `SUBJECT "ref:"`; si
Relevo usara el mismo formato, ese poller encontraría respuestas de RFI, no las matchearía
con ningún caso AML y **las marcaría leídas**. Verificado: `"ref:"` no matchea como substring
dentro de `[rfi: ...]`, así que los dos pollers quedan mutuamente excluyentes.

### Salvaguardas obligatorias antes de enviar

- **Previsualización**: se puede leer el correo completo antes de que exista la posibilidad
  de mandarlo.
- **Bloqueo de doble envío**: un caso ya pedido no se vuelve a pedir por accidente.
- **Interruptor general y por partner** en `relevo_config`, y **apagados por defecto**, igual
  que el disparo automático de WatchTower.
- **Tope por lote y confirmación explícita** en el flujo masivo. Nada sale sin que alguien lo
  mire.
- Registro en `relevo_solicitudes` **salga o no** el correo.

---

## 9. La recepción

Poller propio en Lambda, EventBridge cada 10 min, con las lecciones de WatchTower
incorporadas y sin tocar su código.

**Correlación, en este orden:**

1. por **`threadId`** — la respuesta del cliente cae en el hilo que abrimos. Robusto: sobrevive
   a que edite el asunto.
2. por el token **`[rfi: xxxxxxxx]`** del asunto, como respaldo.
3. si no matchea nada, **no se toca el mensaje**.

**Deduplicación por ledger de Message-ID en `relevo_procesados`, NO por el flag `\Seen`.**
Es la lección explícita de WatchTower: si se depende de `\Seen`, una respuesta que alguien
abrió a mano antes del poller no se procesa nunca y el documento no llega al caso.

**Qué hace con cada respuesta:**

- si trae archivos → los sube a S3, los cuelga del caso y pasa el checklist a **recibido**;
- si no trae archivos → deja el texto como nota en el caso;
- **nunca** pasa a `entregado`: eso lo confirma una persona después de revisar el contenido.

```
pendiente  ← lo pone el sistema al enviar
recibido   ← lo pone el sistema al detectar la respuesta
entregado  ← SIEMPRE una persona
```

Nunca se crea un caso nuevo desde una respuesta: siempre se actualiza el que originó la
solicitud.

**Topes por corrida.** Recorrer toda la casilla en una invocación cuelga la Lambda. Se
procesa de a tandas con un `deadline` interno muy por debajo del límite de la función, y lo
que sobra queda para la corrida siguiente.

---

## 10. Rutas nuevas de la API

Todas bajo `/relevo/*` para que no se cruce con nada existente. Auth: la misma de WatchTower
(Cognito JWT validado por API Gateway).

```
GET    /relevo/mensajes                 bandeja de correos de partners, con filtros
GET    /relevo/casos                    ?partner= &estado= &cliente_id= &vencidos=
GET    /relevo/casos/{id}               detalle: transacciones, correos, acciones, cliente
GET    /relevo/clientes                 el 360  ?solo_pendientes=
POST   /relevo/casos/{id}/accion        { accion, detalle }  → append en relevo_acciones
POST   /relevo/casos/{id}/pedido        previsualizar / enviar el correo al cliente
POST   /relevo/pedidos/lote             flujo masivo: previsualizar y enviar con tope
GET    /relevo/config                   mantenedores e interruptores
PUT    /relevo/config                   actualizarlos
GET    /relevo/reglas                   reglas.json, para el probador
POST   /relevo/probar                   corre el motor sobre un asunto/cuerpo de prueba
GET    /relevo/salud                    estado de ingesta, poller, Redshift y Gmail
POST   /relevo/resolver                 dispara la resolución a pedido
GET    /relevo/casos/{id}/checklist      estado tri-estado de los documentos (§9)
POST   /relevo/casos/{id}/checklist      cambio manual; `entregado` exige autor
GET    /relevo/vencidos                  la cola de recontacto (§7)
POST   /relevo/casos/{id}/recontactar    previsualiza / manda el recontacto
POST   /relevo/interruptores             prende o apaga el envío, con autor
POST   /relevo/casos/{id}/devolucion     compone la respuesta al partner / la registra
GET    /relevo/espejo                    resultado de la última corrida del lote
POST   /relevo/espejo                    dispara el lote (Event, no corre en la API)
```

`POST /relevo/espejo` **no corre el lote**: lo dispara en `InvocationType=Event` a la Lambda
de reportes. Medido en producción: la corrida completa tarda ~26 s y el **API Gateway corta a
los 30**, así que hacerlo síncrono daba 503. El runner tiene 900 s. `correr()` guarda su
resultado en el depósito y el GET lo devuelve — sin eso, la única forma de saber si el espejo
se actualizó sería leer CloudWatch, y entonces nadie lo mira.

`POST /relevo/casos/{id}/accion` debe **registrar quién** la ejecutó, tomándolo del JWT. En
una herramienta que mueve documentos de clientes, "quién hizo esto" tiene que tener respuesta.

---

## 11. El front

Pestaña **Relevo** en `frontend/index.html`, en el mismo Alpine + Tailwind, con cuatro
secciones:

1. **Clientes** — el 360. Una fila por cliente: partners, casos, transacciones, el pedido
   consolidado, plazo, etapa y cuántos casos tiene vencidos.
2. **Casos** — una fila por requerimiento del partner: identificador, qué pide, cliente,
   plazo, etapa, intentos, y aviso de recontacto vencido. En el detalle: los ítems, las
   acciones disponibles según el estado, las transacciones que abarca, los correos con enlace
   a Gmail y la ficha del cliente con la verificación cruzada.
3. **Bandeja de partners** — los correos crudos con lo que el motor extrajo de cada uno, para
   depurar reglas.
4. **Probador de reglas** — corre el motor del servidor sobre un asunto y cuerpo pegados a
   mano. No guarda nada.

Los botones de acción ofrecen **sólo las salidas reales de cada estado**, y no hay botón para
volver atrás porque las terminales son fijas:

| Estado | Botones |
|---|---|
| `listo_para_pedir` | Marcar como pedido · Descartar |
| `pedido_enviado` / `recontactado` | Recontactar · Respondió a medias · Respondió todo · Dar por sin respuesta |
| `respuesta_parcial` | Recontactar por lo que falta · Respondió todo · Dar por sin respuesta |
| `respuesta_recibida` | Marcar devuelto al partner |
| `devuelto` | Cerrar caso |

---

## 12. Variables de entorno, secretos y permisos

### Variables

```
RELEVO_TABLA_MENSAJES      = relevo_mensajes
RELEVO_TABLA_ACCIONES      = relevo_acciones
RELEVO_TABLA_CLIENTES      = relevo_clientes
RELEVO_TABLA_ESTADO        = relevo_estado
RELEVO_TABLA_SOLICITUDES   = relevo_solicitudes
RELEVO_TABLA_PROCESADOS    = relevo_procesados
RELEVO_TABLA_CONFIG        = relevo_config
RELEVO_BUCKET_ADJUNTOS     = <bucket>            # prefijo relevo/adjuntos/
RELEVO_GMAIL_SECRET_ARN    = arn:aws:secretsmanager:...
RELEVO_GMAIL_USUARIO       = compliance.masivo@global66.com
RELEVO_FROM_ADDR           = compliance@global66.com
RELEVO_TOKEN_PREFIJO       = rfi
RELEVO_SLACK_CANAL         = <canal>              # replicar el aviso, no reusar
REDSHIFT_CLUSTER           = compliance-redshift-cluster
REDSHIFT_BASE              = dev
REDSHIFT_DBUSER            = relevo_ro            # o awsuser mientras no exista
REDSHIFT_TIMEOUT           = 60
AWS_REGION                 = us-east-1
```

### Secreto de Gmail (uno, JSON)

```json
{ "client_id": "...", "client_secret": "...", "refresh_token": "..." }
```

### IAM de la Lambda

```
redshift-data:ExecuteStatement, DescribeStatement, GetStatementResult, CancelStatement
redshift:GetClusterCredentials          ← obligatorio al usar DbUser; sin esto falla
secretsmanager:GetSecretValue            ← sobre el secreto de Gmail
dynamodb:GetItem, PutItem, UpdateItem, Query, Scan, BatchWriteItem  ← tablas relevo_*
s3:PutObject, GetObject                  ← prefijo relevo/ del bucket
```

### Infra — estado real

| Pieza | Estado |
|---|---|
| Persistencia operativa | ✅ S3, prefijo `relevo/` del bucket de reportes (no Dynamo: ver §2) |
| `...-relevo-ingesta` | ✅ `rate(5 minutes)` |
| `...-relevo-vista` | ✅ `rate(5 minutes)` |
| `...-relevo-recepcion` | ✅ `rate(10 minutes)` |
| `...-relevo-resolver` | ✅ `rate(15 minutes)` |
| `...-relevo-espejo` | ✅ `cron(45 12 * * ? *)` |
| Secreto de Gmail | ✅ `compliance-redshift-reports/relevo-gmail` |
| Esquema `relevo` en Redshift | ✅ se crea solo: el lote corre su DDL idempotente en cada corrida |

**El scope `gmail.send` sigue faltando.** El token está en `gmail.readonly`, así que el paso 6
no puede mandar el pedido al cliente. Al re-consentir, pedir **`gmail.modify`**: cubre eso y
además habilita el borrador de la devolución (decisión 10 de §16).

El DDL del espejo se corre en cada corrida a propósito: es barato, y hace que el esquema se
instale solo en un ambiente nuevo en vez de ser un paso manual que alguien va a olvidar.

---

## 13. Las trampas, todas juntas

Cada una costó encontrarla. Están acá para que no haya que redescubrirlas.

**Gmail**

1. El grupo reescribe el `From`; el remitente real está en `X-Original-Sender` y hay que
   pedirlo explícitamente.
2. `historyTypes=messageAdded` es obligatorio, o los cambios de etiqueta de WatchTower
   disparan reingesta.
3. La cuota devuelve **403**, no 429.
4. El `historyId` se persiste **después** de guardar, no antes.

**Redshift**

5. Nombre de **tres partes** con `db_prod`, o `Relation ... does not exist`.
6. Redshift **no tiene** `JSON_EXTRACT` ni `JSON_UNQUOTE` (eso es MySQL). Es
   `JSON_EXTRACT_PATH_TEXT(col, 'clave', TRUE)`, y ese último `TRUE` devuelve NULL en vez de
   reventar cuando la fila no es JSON válido.
7. **No castear referencias a entero**: hay filas con 27 dígitos y da `Overflow`.
8. El join a `customer.customer` va con **LEFT**. Hay clientes —los B2B entre ellos— sin fila
   ahí, y un inner join convierte "encontré la transacción pero no al cliente" en "no
   encontré nada", que se lee como identificador equivocado. Con LEFT queda `sin_correo`,
   que es la verdad y dice dónde arreglarlo.
9. **No filtrar por `partner`** en `partner_transaction`: daba falsos negativos.
10. `transaction.transaction` **no tiene** `external_reference_number`, sólo
    `payment_reference_number`. El join a `cash_call` es contra `transaction_id`.
11. Una transacción puede tener **varios cash calls** (vimos una con un `PAID` y un
    `RELEASED`); el RMT dice cuál.
12. La consulta de Currencycloud **necesita el `GROUP BY`**: un mismo `IF-` genera varias
    notificaciones del **mismo** cliente y sin agrupar el `LIMIT 2` las lee como `ambiguo` y
    frena el caso por una razón falsa.

**Extracción**

13. Los prefijos de identificadores **nuestros** nunca son pista de partner: tomar `RMT` como
    señal de dLocal atribuyó mal 33 correos de Nium.
14. Las pistas de asunto van **con peso**, y gana el mayor, no el orden de la lista:
    `[Currencycloud]` entre corchetes vale más que la marca suelta.
15. Currencycloud manda el **cierre de ticket con el mismo asunto** que la apertura; la
    diferencia está en el cuerpo (`has been Solved` vs `has been updated`). Fueron 15 de 31
    correos en un día. Por eso la clasificación mira el cuerpo.
16. El HTML de dLocal hay que convertirlo **preservando la tabla** con tabulaciones;
    aplastarlo con un strip de tags deja etiquetas y valores pegados. Y el emparejado
    posicional va **antes** que el de pares.

**Casos y fechas**

17. Toda marca de tiempo del registro se normaliza a zona horaria antes de comparar. Una
    fecha sin zona contra una con zona levanta `TypeError` y se lleva puesta **la lista de
    casos completa** por una sola línea mala.
18. `5.000` son cinco mil, no cinco. Los partners escriben en las dos convenciones: si hay un
    solo separador seguido de exactamente tres dígitos, es de miles.

**Convivencia con WatchTower**

19. Token `rfi:`, nunca `ref:`.
20. Las dos leen la misma casilla y hoy no se pisan sólo porque WatchTower filtra por su
    token y Relevo filtra por `messageAdded`. **Si alguien toca uno de esos dos filtros, hay
    que revisar el otro.**

---

## 14. Orden de ejecución

Sin estimaciones: el orden es lo que importa, porque cada paso se apoya en el anterior.

1. **Andamio.** Copiar el paquete `relevo/` y sus tests a `lambda/relevo/`. Verificar que los
   104 tests pasan dentro del repo de WatchTower. Nada más.
   **Ojo con el empaquetado:** `build_lambda.sh` copia archivo por archivo y no incluye
   subdirectorios, así que hay que agregarle `cp -R lambda/relevo "$BUILD_DIR/"` (ya
   agregado). Sin eso los tests pasan igual y la Lambda falla con `ModuleNotFoundError`:
   es un verde engañoso.
2. **Persistencia.** Crear las tablas y cambiar el fondo de las seis funciones de almacén.
   Los tests siguen pasando: los de almacén usan directorios temporales y hay que
   reescribirlos contra Dynamo local o con dobles.
3. **Ingesta.** Secreto de Gmail, `historyId` en Dynamo, regla de EventBridge. Al terminar
   esto, la casilla se lee desde la web y **se puede apagar el `launchd` del Mac**.
4. **Resolución.** Las cuatro consultas, la tolerancia al cluster pausado y el caché en
   `relevo_clientes`. Al terminar, los casos llegan a cliente con correo sin el Mac.
5. **API y front.** Las rutas `/relevo/*` y la pestaña. Al terminar, **el túnel de ngrok se
   apaga** y se entra por Cognito con cuenta corporativa. *Acá el proceso ya está migrado.*
6. **Envío al cliente.** Requiere el re-consentimiento con `gmail.send`. Con previsualización
   e interruptores apagados por defecto; primero un envío a mano, después el lote.
7. **Recepción.** El poller, los adjuntos, el checklist.
8. **Recontacto.** Los dos mantenedores y la cola de vencidos.
9. **Devolución al partner y espejo analítico.** ✅ **Hecho.** El borrador se resolvió como
   texto en pantalla para copiar (decisión 10, abajo) y el espejo entró como esquema `relevo`
   cargado por `COPY` desde S3 (§18). Regla `...-relevo-espejo`, `cron(45 12 * * ? *)`.

Los pasos 1 a 5 **no dependen de nada externo** y son los que sacan el proceso del Mac. El 6
espera el scope de Gmail.

---

## 15. Verificación

Cada uno tiene que dar exactamente esto, medido sobre la casilla real.
**Estado al 2026-09-10: 8 de 12 verificados, y los 4 que faltan dependen del mismo
scope de Gmail.**

```
[x] Los tests pasan dentro del repo de WatchTower       → 146 (eran 104)
[x] La ingesta lee la casilla desde Lambda y el historyId avanza sin huecos
[x] 4 partners identificados por X-Original-Sender      → Currencycloud 88, dLocal 50,
                                                            Nium 16, OZ Câmbio 16
[x] El cliente 3950037 es UN caso de Nium con 6 transacciones
                                                        → nium:caso:1088170, n=6 ✔
[x] La resolución da con correo de cliente              → 116 de 117 resolubles.
      Los 17 casos `sin_cliente` son 16 de `cc_external_id` (llave que no sabemos
      componer, decisión abierta) + 1 `cc_transaction_id`. Está en su techo.
[x] La verificación cruzada da CERO desacuerdos         → 73 casos comparables
      (el plan esperaba ~41), 146 comparaciones de campo, 0 desacuerdos
[x] Con el cluster pausado: la ingesta sigue leyendo y las resoluciones se encolan
[ ] El correo de prueba llega con el token [rfi: ...] y su threadId queda guardado
[ ] El poller de WatchTower NO toca ese correo ni su respuesta
[ ] La respuesta con adjunto pasa el checklist a "recibido" y NO a "entregado"
[ ] Una respuesta parcial deja bien calculado lo que falta
[x] El launchd del Mac está apagado y el túnel de ngrok cerrado
      → descargados con `launchctl unload -w` el 2026-09-10; ngrok ya no corría.
        Antes de apagarlo se comparó id por id: 912 correos en el Mac, 912 en S3,
        cero de un solo lado. Para revertir: `launchctl load -w <plist>`.
```

**Los cuatro que faltan son el mismo bloqueo.** El token está en `gmail.readonly`, así que
el paso 6 no puede escribirle a un cliente; y como los pasos 7 y 8 reaccionan a esa
respuesta, están construidos pero nunca se ejercitaron de punta a punta. Se destraban los
cuatro juntos con un re-consentimiento — pidiendo **`gmail.modify`** (§16, decisión 10).

---

## 16. Lo que queda sin definir

Ninguna bloquea el arranque. Se deciden cuando se llegue al paso correspondiente.

| # | Pregunta | Cae en el paso |
|---|---|---|
| 7 | B2C o B2B: define plantilla. `customer.customer` tiene `is_company` y hoy no lo traemos. Y hay que resolver qué pasa con los clientes **sin fila ahí**, que son justamente los B2B | 6 |
| 8 | Los roles: qué ve CX y qué ve sólo Compliance; y si un analista AML ve los casos RFI | 5 |
| 9 | Los 217 correos apartados, anteriores al token, sin forma automática de correlacionarlos: descartar, cola manual, o emparejar por remitente y fecha | 7 |
| 10 | ~~La devolución al partner: borrador en Gmail o en pantalla para copiar~~ **RESUELTA: en pantalla.** El borrador necesita `gmail.compose`/`gmail.modify`, que es un re-consentimiento *distinto* del `gmail.send` que el paso 6 ya espera; escribir esa rama hoy sería código que no corre ni se prueba. **Cuando se re-consienta, pedir `gmail.modify`**: cubre enviar el pedido Y dejar el borrador en un solo viaje, y agregar el borrador pasa a ser ~15 líneas contra `drafts.create` | 9 ✅ |
| — | `cc_external_id`: cómo se compone. 9 casos a revisión manual hasta entonces | — |

---

## 17. Estado de origen, para comparar

Medido el 2026-09-07 sobre `compliance.masivo@global66.com`:

| | |
|---|---|
| Correos procesados | 478 |
| Transacciones identificadas | 131 |
| Casos | 122 |
| Clientes distintos | 97 |
| Casos accionables | 89 |
| Con cliente y correo | 77 |
| Resoluciones en caché | 110 de 110 |
| Verificaciones cruzadas | 41 comparables, 0 en desacuerdo |
| Tests | 104 que corren, en ~0,1 s, sin dependencias |

Estado en WatchTower al cerrar el paso 9 (2026-09-09): **771 correos, 181 transacciones,
170 casos, 150 con cliente y correo, 4 partners, 146 tests.** Los 5 procesos programados
—ingesta 5', vista 5', recepción 10', resolución 15', espejo diario— corren sin el Mac.

---

## 18. El espejo analítico: esquema `relevo` en Redshift

Escrito por el paso 9. **No es la fuente de verdad**: la fuente es el depósito en S3, y esto
es una copia que se **rehace completa** en cada corrida. Una diferencia entre el espejo y la
pantalla es un bug del espejo, no un dato nuevo.

### Cómo se carga, y por qué así

Las filas se escriben como **JSON Lines a S3** y entran con **`COPY`**. No se interpolan en el
SQL. Tres restricciones reales lo obligan, las tres verificadas antes de escribir el código:

1. El rol de la Lambda tiene `redshift-data:ExecuteStatement` pero **no
   `BatchExecuteStatement`** — no hay forma de mandar N sentencias parametrizadas en una
   transacción por esa vía.
2. Interpolar los valores es exactamente lo que `redshift.py` prohíbe, y con razón: el texto
   viene de correos de terceros.
3. El rol del cluster (`AmazonRedshiftAllCommandsFullAccess`) tiene `s3:GetObject` sobre
   `arn:aws:s3:::*redshift*/*`, y el bucket se llama `compliance-redshift-reports-…`, así que
   **matchea**. Sin esa coincidencia habría que tocar IAM.

El `DELETE` y el `COPY` de cada tabla viajan en **una sola sentencia** con `BEGIN; … END;`:
si el `COPY` falla, el `DELETE` se va con él y la tabla queda con los datos de ayer, que es
mucho mejor que quedar vacía.

**Con el cluster pausado se salta la corrida y lo registra; no lo enciende.** Es reporting:
no justifica el costo, y como cada corrida rehace todo, la del día siguiente no pierde nada.
`{"forzar": true}` lo despierta, para correrlo a mano.

### Las siete tablas

| Tabla | Grano | Para qué sirve |
|---|---|---|
| `relevo.casos` | un caso | el tablero: estado, partner, cliente, SLA |
| `relevo.acciones` | una acción | el histórico auditable de quién hizo qué |
| `relevo.transacciones` | una transacción de un caso | volumen y montos por partner |
| `relevo.items` | un documento pedido | qué se pide más, y qué se entrega |
| `relevo.solicitudes` | un intento de envío | incluye los **fallidos**, con su error |
| `relevo.respuestas` | una respuesta del cliente | cuántos responden y con qué |
| `relevo.devoluciones` | una devolución al partner | cierre del ciclo, parcial o completa |

Columnas que valen la pena conocer en `relevo.casos`:

- `horas_pedido_a_respuesta` y `horas_respuesta_a_devolucion` — los dos tramos del SLA, ya
  calculados. Salen de las acciones, así que no pueden desincronizarse.
- `ck_total`, `ck_pendiente`, `ck_recibido`, `ck_entregado` — el checklist resumido.
- `devuelto_en`, `devuelto_por`, `devolucion_parcial`.
- `snapshot_en` — de cuándo son los datos. Está en **todas** las tablas.

### Tres cosas que hay que saber al consultarlo

1. **Los timestamps son UTC sin zona.** Conviven cuatro formatos en el módulo (el
   `internalDate` de Gmail en milisegundos, el ISO con offset del registro de acciones, el
   `gmtime` del depósito, y strings vacíos); todos se normalizan a UTC. Lo que no se pudo leer
   queda **NULL**, nunca una fecha inventada.
2. **`items.estado = 'sin_checklist'`** significa que el pedido nunca salió desde acá, así que
   nadie registró estado por ítem. No es "pendiente": es "no se sabe", y son cosas distintas.
   Con el envío apagado, **todos** los ítems están así.
3. **`solicitudes` y `respuestas` van completas, no filtradas por caso.** Una solicitud que
   falló puede apuntar a un caso que ya no aparece en la vista, y perderla sería perder justo
   el intento que hay que revisar.

### Medido en la primera corrida real (2026-09-09)

| | |
|---|---|
| Casos / transacciones / ítems | 170 / 181 / 334 |
| Ids duplicados | 0 (170 de 170 distintos) |
| Partners | 4 (dLocal, Nium, Currencycloud, OZ Câmbio) |
| Casos con cliente y correo resueltos | 150 de 170 |
| Casos con número de caso del partner | 97 de 170 |
| Casos sin fecha de correo | 4 — **fiel al dato**: la API también devuelve `''` ahí |
| Armado de las filas | 0,1 s |
| Corrida completa (DDL + 7 tablas) | 26,5 s |
| Segunda corrida | mismos conteos, `snapshot_en` nuevo: el refresh completo no duplica |
