# API de casos del WatchTower — guía de integración

Para gestionar casos de Compliance desde otro sistema: filtrarlos, crearlos,
moverles el estado, dejar notas y comunicarse con el cliente.

**Base:** `https://qwvd2t33uc.execute-api.us-east-1.amazonaws.com`
**Formato:** JSON en todo. Mandá `Content-Type: application/json` en POST y PATCH.

---

## 1. Acceso

No hay login, usuario ni token que expire. Se autentica con una **clave fija**
en el header `x-api-key`, en **todas** las llamadas:

```bash
curl -H "x-api-key: wt_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
     "https://qwvd2t33uc.execute-api.us-east-1.amazonaws.com/v1/casos?por_pagina=1"
```

La clave la entrega Compliance y es **de tu sistema, no tuya**: identifica al
sistema que llama, no a la persona.

### Probá que funciona antes de escribir código

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "x-api-key: $WATCHTOWER_API_KEY" \
  "https://qwvd2t33uc.execute-api.us-east-1.amazonaws.com/v1/casos?por_pagina=1"
```

`200` y estás adentro.

### Qué te puede decir que no

| Código | Qué pasó | Qué hacer |
|---|---|---|
| `401` | falta la clave, está mal copiada o fue revocada | revisá el header; si está bien, pedí a Compliance que la verifique |
| `403` | la clave es válida pero le falta **ese** permiso | el cuerpo trae los permisos que sí tenés; pedí el que falta |
| `400` | la clave está bien, el cuerpo no | leé el mensaje, dice qué campo |
| `404` | ese caso no existe (o la ruta está mal escrita) | |
| `503` | la base analítica está pausada — sólo afecta a `/v1/alertas` | reintentá después de las 04:00 |

`401` y `403` son cosas distintas a propósito: "no sé quién sos" te manda a
revisar la clave, "no podés" te manda a pedir un permiso. No los trates igual.

### Tus permisos

| Permiso | Te habilita a |
|---|---|
| `casos:leer` | listar, ver detalle, ver comunicaciones, consultar alertas |
| `casos:escribir` | crear casos, cambiar estado/prioridad/asignación, notas |
| `casos:comunicar` | **enviarle correo al cliente** |

Si tu clave no tiene los tres, los endpoints del resto te devuelven `403` con
la lista de lo que sí tenés.

---

## 2. Cómo queda registrado lo que hacés

Todo lo que hace tu sistema queda firmado como `api:<nombre-de-tu-sistema>`
(por ejemplo `api:sistema-casos`) y aparece así en la pantalla que usan los
analistas.

**No podés declarar otro autor.** Si mandás `created_by` o `actor_email` en el
cuerpo, se ignoran. Es a propósito: en una auditoría hay que poder separar lo
que hizo una persona de lo que hizo un sistema.

Práctica: si el caso lo originó una persona de tu lado, poné su nombre **en la
nota**, no intentes firmar en su nombre.

```json
{"texto": "Escalado por María González (turno noche): el cliente llamó."}
```

---

## 3. Qué podés hacer

### Listar y filtrar — `GET /v1/casos`

| Parámetro | Ejemplo | Qué filtra |
|---|---|---|
| `estado` | `open` | `open`, `in_progress`, `under_review`, `closed`, `archived`, `all` |
| `prioridad` | `high` | `high`, `medium`, `low` |
| `asignado_a` | `ana@global66.com` | analista dueño |
| `plazo` | `vencido` | `en_plazo`, `por_contactar`, `por_recontactar`, `vencido`, `cerrado`, `sin_plazo` |
| `dias_min` / `dias_max` | `1.5` | días que lleva abierto |
| `reporte` | `operation-alert_-_psp_sum_30` | alerta que lo originó |
| `cliente_id` | `4171334` | id del cliente |
| `desde` / `hasta` | `2026-09-01` | rango de **creación** (`YYYY-MM-DD`) |
| `actualizado_desde` | `2026-09-20 14:00:00` | lo que **cambió** desde ese momento — para sincronizar |
| `pagina` / `por_pagina` | `1` / `50` | paginación, máximo **200** |

```json
{
  "casos": [{
    "id": "abc-123",
    "titulo": "Caso: 4171334",
    "estado": "open",
    "prioridad": "high",
    "cliente": {"tipo": "customer", "id": "4171334", "nombre": "…"},
    "origen": {"reporte": "operation-alert_-_psp_sum_30", "prioridad_alerta": "P2"},
    "asignado_a": "ana@global66.com",
    "creado_at": "2026-09-08 13:00:13",
    "notas": 2,
    "plazo": {"aplica": true, "estado": "vencido", "dias_abierto": 12.0,
              "horas_restantes": -216.0, "cierre_at": "2026-09-11 13:00:13",
              "accion": "cerrar"}
  }],
  "total": 89, "pagina": 1, "por_pagina": 50,
  "resumen_plazo": {"vencido": 69, "cerrado": 15}
}
```

**El listado no trae datos personales del cliente** (correo, documento). Están
en el detalle. Es deliberado: una página de 200 casos no debería mover el
documento de 200 personas.

#### El plazo

Los casos nacidos de una alerta transaccional tienen reloj: **3 días** desde
que se crearon, con recontacto a la mitad (1,5 días). `horas_restantes` en
negativo significa vencido. Los casos que no vienen de una alerta traen
`{"aplica": false}` y no hay que medirlos contra ese plazo.

### Ver un caso — `GET /v1/casos/{id}`

Lo mismo que una fila del listado, más:

- `alerta` — los datos crudos que dispararon el caso: correo, documento, país,
  motivo del bloqueo.
- `notas_detalle` — texto, autor y fecha de cada nota.
- `adjuntos` — qué mandó el cliente.

### Crear — `POST /v1/casos`

```json
{
  "titulo": "Revisión por regla PSP-C-AMT-J9H7",
  "descripcion": "Bloqueo automático del motor de fraude.",
  "prioridad": "high",
  "cliente": {"tipo": "customer", "id": "4171334", "nombre": "Nombre Apellido"},
  "origen": {"reporte": "operation-alert_-_psp_sum_30", "prioridad_alerta": "P2"},
  "alerta": {"agent_comment": "operation-alert - FRAUD - PSP-C-AMT-J9H7",
             "pais_cliente": "AR", "email": "cliente@ejemplo.com",
             "dni": "38699180", "tipo_dni": "DNI"}
}
```

Sólo `titulo` es obligatorio. Devuelve `201` con `{"id": "..."}`.

**Mandá el contexto completo en `alerta`.** Eso es lo que ve el analista cuando
abre el caso; si va vacío, tiene que ir a buscar los datos a otro sistema. Y sin
`email` ahí, después no vas a poder usar `/comunicaciones` sin pasarle el correo
a mano.

### Cambiar estado, prioridad o responsable — `PATCH /v1/casos/{id}`

```json
{"estado": "in_progress", "prioridad": "high", "asignado_a": "ana@global66.com"}
```

Los tres campos son opcionales: mandá sólo lo que cambia. Devuelve el caso ya
actualizado, así que no hace falta un `GET` después.

Cerrar (`"estado": "closed"`) sella la fecha de cierre igual que si se hiciera
desde la pantalla.

### Notas — `POST /v1/casos/{id}/notas`

```json
{"texto": "Contactado por teléfono, envía documentos mañana."}
```

Las notas **no se borran ni se editan**: el histórico sólo agrega. Si algo
quedó mal, escribí otra nota corrigiendo.

### Comunicaciones

`GET /v1/casos/{id}/comunicaciones` — el historial de correos del caso,
enviados y recibidos, en orden. Incluye los intentos fallidos: que un correo no
saliera también es historia, y explica un silencio del cliente.

`POST /v1/casos/{id}/comunicaciones` — **le manda un correo real al cliente.**

```json
{
  "plantilla": "general_b2c",
  "documentos": ["Domicilio", "Origen de fondo"],
  "correo": "cliente@ejemplo.com",
  "texto": ""
}
```

| Campo | |
|---|---|
| `plantilla` | opcional — si no la mandás, se elige sola según el país del cliente (Argentina tiene la suya). Valores: `general_b2c`, `argentina_b2c`, `b2b_generico`, `general_b2c_blanco`, `texto_libre` |
| `documentos` | qué se le pide. Los puntos que no pidas se sacan del correo y los que quedan se renumeran solos |
| `correo` | opcional — por defecto el del caso |
| `texto` | sólo para `texto_libre` y `general_b2c_blanco` |

Categorías válidas de `documentos`, exactamente así:

```
"Domicilio"
"Identidad/Datos personales"
"Origen de fondo"
"Comprobantes/Soporte"
"Relación/Beneficiario"
```

El asunto lleva un token que ata la respuesta del cliente al caso: si responde
conservando el asunto, sus documentos entran solos. Por eso el correo le pide
que no lo edite.

### Alertas de una regla — `GET /v1/alertas?regla=PSP-C-AMT-J9H7&pais=AR`

Los clientes que una regla del motor de fraude dejó bloqueados, listos para
convertirse en caso.

```json
{
  "regla": "PSP-C-AMT-J9H7", "total": 12,
  "alertas": [{
    "cliente_id": 4171334, "nombre": "Nombre Apellido",
    "email": "…", "pais": "AR",
    "documento": {"tipo": "DNI", "numero": "38699180"},
    "estado_compliance": "BLOCKED",
    "regla": "operation-alert - FRAUD - PSP-C-AMT-J9H7",
    "motor": "operation-alert", "score": "59.07",
    "bloqueado_at": "2026-08-01 12:50:55"
  }]
}
```

> **Horario.** Este endpoint —y **sólo** este— va contra la base analítica, que
> se pausa todos los días **entre las 18:30 y las 04:00 (hora de Chile)**. En
> esa ventana devuelve `503` con `{"error": "redshift_pausado"}`. Si tu proceso
> corre de noche, programalo después de las 04:00. El resto de los endpoints
> responde siempre.

---

## 4. El flujo típico (Argentina)

```
GET  /v1/alertas?regla=PSP-C-AMT-J9H7&pais=AR
      ↓  elegís cuáles accionar
POST /v1/casos                              (uno por cliente)
      ↓
POST /v1/casos/{id}/comunicaciones          (le pedís los documentos)
      ↓  el cliente responde y sus documentos entran solos al caso
GET  /v1/casos/{id}                         (mirás adjuntos y notas)
      ↓
PATCH /v1/casos/{id}  {"estado": "closed"}
```

---

## 5. Buenas prácticas

### La clave

- **En la configuración, nunca en el código.** Variable de entorno o gestor de
  secretos. Si termina en un repo, hay que rotarla y tu integración se corta.
- **No la compartas ni la reuses** en otro sistema. Si hay dos sistemas, van
  dos claves: así se revoca a uno sin afectar al otro y la auditoría distingue.
- **No la pongas en la URL** ni la loguees. Va en el header y nada más.
- Si sospechás que se filtró, avisá a Compliance **ese día**. Rotarla toma un
  minuto.

### Al escribir

- **Verificá antes de crear.** No hay deduplicación automática: si mandás el
  mismo `POST /v1/casos` dos veces, quedan dos casos y un analista va a trabajar
  los dos. Buscá primero por `cliente_id` y `reporte`.
- **Guardá el `id` que devuelve** el `201`. Es cómo vas a volver al caso.
- **No reintentes a ciegas** un `POST` que dio timeout: puede haberse creado.
  Consultá primero, creá después.
- **Un `PATCH` con sólo lo que cambia.** Mandar el objeto entero pisa campos
  que quizás movió un analista desde la pantalla mientras tanto.

### Al leer

- **Paginá** con `por_pagina` (máximo 200) en vez de pedir todo y filtrar de tu
  lado. Filtrá con los parámetros: es más rápido y mueve menos datos personales.
- **Cachéa poco.** Los analistas trabajan los mismos casos desde la pantalla al
  mismo tiempo; un caché de más de unos minutos te va a mostrar estados viejos.
- **Sincronizá con `actualizado_desde`**, no releyendo todo: pasale el
  `actualizado_at` más alto que viste en tu corrida anterior. Ojo que `desde`
  es otra cosa — filtra por fecha de **creación**, así que un caso viejo que un
  analista movió hoy no entra por ahí.

### Volumen y ritmo

- No hay cuota todavía, y eso es confianza, no permiso. Si vas a hacer una
  carga grande, avisá antes.
- Poné una pausa entre llamadas en los procesos masivos. Un loop sin freno
  contra `/v1/casos` degrada la pantalla de los analistas, que es el mismo
  backend.
- Manejá `503` con reintento espaciado, no inmediato.

### Datos personales

- Lo que devuelve el detalle —correo, documento, nombre— **son datos personales
  de clientes reales**. Guardá sólo lo que tu sistema necesita y no lo repliques
  a lugares que no estén en el mismo estándar.
- **No los loguees.** Un `print` del response completo termina en un log que
  vive años.
- El listado está diseñado para no traerlos: usalo para navegar y pedí el
  detalle sólo de los casos que vas a trabajar.

### Comunicaciones

Es el endpoint de más riesgo: **le escribe a una persona real y no se puede
deshacer.**

- Probá el armado con un caso propio y tu correo antes de apuntarle a un
  cliente.
- Nunca lo pongas en un loop automático sin un tope y sin que alguien revise.
- Revisá `GET /comunicaciones` antes de mandar: si ya se le escribió hace una
  hora, no le escribas de nuevo.
- Si el envío falla, **no reintentes en el momento**. Queda registrado el
  intento; mirá el error primero.

---

## 6. Qué no puede hacer esta API

- **Borrar casos.** A propósito: el histórico de compliance no se borra desde
  afuera. Para descartar un caso, cerralo (`"estado": "closed"`).
- **Editar o borrar notas.** Sólo agregar.
- **Subir adjuntos.** Los documentos del cliente entran por su respuesta al
  correo. Si tenés que adjuntar algo a mano, se hace desde la pantalla.
- **Ver o administrar usuarios, reportes, embargos o el módulo de
  corresponsales.** Esta clave sólo abre `/v1/casos` y `/v1/alertas`.

Si necesitás algo de esto, hablalo con Compliance antes de buscar una vuelta.
