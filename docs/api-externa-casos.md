# API externa de casos — `/v1`

Para integrar la gestión de casos del WatchTower desde otro sistema: filtrar,
crear, mover el estado, dejar notas y comunicarse con el cliente.

**Base:** `https://qwvd2t33uc.execute-api.us-east-1.amazonaws.com`

## Autenticación

Header `x-api-key` en **todas** las llamadas. La clave la entrega Compliance y
es por consumidor: identifica quién hizo cada cosa y se revoca sola sin afectar
a los demás.

```
x-api-key: wt_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Cada clave tiene permisos explícitos:

| Permiso | Habilita |
|---|---|
| `casos:leer` | listar, ver detalle, ver comunicaciones, consultar alertas |
| `casos:escribir` | crear casos, cambiar estado/prioridad/asignación, notas |
| `casos:comunicar` | **enviarle correo al cliente** |

`casos:comunicar` va aparte a propósito: se puede gestionar el caso completo sin
poder escribirle a una persona real.

Respuestas de error de autenticación:

- `401 no_autorizado` — falta la clave, es inválida o está revocada.
- `403 sin_permiso` — la clave es válida pero le falta ese permiso. El cuerpo
  trae los permisos que sí tiene.

> **Sobre la clave.** No la pongas en el código ni en un repo. Va en la
> configuración del sistema que consume, como cualquier otro secreto.

## Quién queda firmado

Todo lo que hace la API queda registrado como `api:<nombre-del-consumidor>`
(ej. `api:sistema-casos`). **No se puede declarar otro autor en el cuerpo**: si
mandás un `created_by` o un `actor_email`, se ignora. En una auditoría hay que
poder separar lo que hizo una persona en la pantalla de lo que hizo un sistema.

---

## Endpoints

### `GET /v1/casos`

| Parámetro | Ejemplo | Qué hace |
|---|---|---|
| `estado` | `open` | `open`, `in_progress`, `under_review`, `closed`, `archived`, `all` |
| `prioridad` | `high` | `high`, `medium`, `low` |
| `asignado_a` | `ana@global66.com` | analista dueño |
| `plazo` | `vencido` | `en_plazo`, `por_contactar`, `por_recontactar`, `vencido`, `cerrado`, `sin_plazo` |
| `dias_min` / `dias_max` | `1.5` | días que lleva abierto |
| `reporte` | `operation-alert_-_psp_sum_30` | alerta que lo originó |
| `cliente_id` | `4171334` | id del cliente |
| `desde` / `hasta` | `2026-09-01` | rango de creación |
| `pagina` / `por_pagina` | `1` / `50` | paginación (máx. 200) |

```json
{
  "casos": [
    {
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
    }
  ],
  "total": 89, "pagina": 1, "por_pagina": 50,
  "resumen_plazo": {"vencido": 69, "cerrado": 15}
}
```

El **listado no trae datos personales del cliente** (correo, documento): están
en el detalle. Una página de 200 casos no debería mover el DNI de 200 personas.

### `GET /v1/casos/{id}`

Lo mismo que una fila del listado, más `alerta` (los datos crudos que
dispararon el caso, incluido el correo y el documento), `notas_detalle` y
`adjuntos`.

### `POST /v1/casos`

```json
{
  "titulo": "Revisión por regla PSP-C-AMT-J9H7",
  "descripcion": "…",
  "prioridad": "high",
  "cliente": {"tipo": "customer", "id": "4171334", "nombre": "Nombre Apellido"},
  "origen": {"reporte": "operation-alert_-_psp_sum_30", "prioridad_alerta": "P2"},
  "alerta": {"agent_comment": "operation-alert - FRAUD - PSP-C-AMT-J9H7",
             "pais_cliente": "AR", "email": "cliente@ejemplo.com"}
}
```

`titulo` es obligatorio. Devuelve `201` con `{"id": "..."}`.

Lo que pongas en `alerta` es lo que después ve el analista en la pantalla del
caso, así que conviene mandar el contexto completo: correo, documento, país y
el motivo del bloqueo.

### `PATCH /v1/casos/{id}`

```json
{"estado": "in_progress", "prioridad": "high", "asignado_a": "ana@global66.com"}
```

Los tres campos son opcionales; se manda sólo lo que cambia. Devuelve el caso
actualizado. Cerrar un caso (`estado: "closed"`) sella la fecha de cierre igual
que si se hiciera desde la pantalla.

### `POST /v1/casos/{id}/notas`

```json
{"texto": "Contactado por teléfono, envía documentos mañana."}
```

### `GET /v1/casos/{id}/comunicaciones`

El historial de correos del caso, enviados y recibidos, en orden. Incluye los
intentos fallidos: que un correo no saliera también es historia.

### `POST /v1/casos/{id}/comunicaciones`

**Le manda un correo real al cliente.** Requiere `casos:comunicar`.

```json
{
  "plantilla": "general_b2c",
  "documentos": ["Domicilio", "Origen de fondo"],
  "correo": "cliente@ejemplo.com",
  "texto": "…"
}
```

- `plantilla` — opcional. Si no la mandás, se elige sola según el país del
  cliente (Argentina tiene la suya). Valores: `general_b2c`, `argentina_b2c`,
  `b2b_generico`, `general_b2c_blanco`, `texto_libre`.
- `documentos` — qué se le pide. Los puntos que no correspondan se sacan del
  correo y los que quedan se renumeran solos.
- `correo` — opcional; por defecto el del caso.
- `texto` — sólo para `texto_libre` y `general_b2c_blanco`.

El asunto lleva un token que ata la respuesta del cliente al caso. Si el cliente
responde conservando el asunto, sus documentos entran solos al caso.

### `GET /v1/alertas?regla=PSP-C-AMT-J9H7[&pais=AR][&limite=200]`

Los clientes que una regla del motor de fraude dejó bloqueados, listos para
convertirse en caso. Es el insumo del flujo de Argentina.

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

El flujo típico: `GET /v1/alertas?regla=…` → elegir cuáles → `POST /v1/casos`
por cada una → `POST /v1/casos/{id}/comunicaciones` para pedirle los documentos.

> Esta consulta va contra Redshift, que **se pausa entre las 18:30 y las 04:00**
> (hora de Chile). Fuera de ese horario la primera llamada puede tardar unos
> minutos mientras el cluster despierta. El resto de los endpoints no dependen
> de Redshift y responden siempre.

---

## Límites

- 200 casos por página.
- El código de regla se valida contra `[A-Za-z0-9][A-Za-z0-9._-]{1,63}`; otra
  cosa devuelve `400`.
- No hay cuota por consumidor. Si el volumen crece, se agrega.

## Lo que esta API todavía NO es

La ruta `$default` del API Gateway está en `Auth: NONE`: hoy los endpoints
internos del WatchTower responden sin credenciales. Mientras eso siga así, la
clave **identifica y audita, pero no impide el acceso** — alguien con la URL
podría llamar los endpoints internos sin clave.

Cerrar el resto del API es un trabajo aparte: el frontend omite el header
`Authorization` a propósito por la configuración de CORS, así que conectar el
authorizer de Cognito lo rompe hasta que se ajuste esa parte.
