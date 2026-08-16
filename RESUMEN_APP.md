# WatchTower — Resumen funcional

Qué es cada módulo, qué hace y cómo lo hace.

---

## 1. Qué es WatchTower

Plataforma interna de Compliance de Global66 que cubre el ciclo completo del monitoreo
AML: **detectar → priorizar → repartir → investigar → pedir documentos → cerrar**.

Reemplaza el trabajo repartido entre consultas SQL sueltas, planillas de seguimiento y
correos redactados a mano, dejando además trazabilidad de cada acción.

---

## 2. El ciclo de trabajo

```
┌─────────────────────────────────────────────────────────────────┐
│  1. DETECTAR    Se ejecuta un reporte del catálogo (31 reportes) │
│                 → tabla de resultados en pantalla + Excel        │
├─────────────────────────────────────────────────────────────────┤
│  2. PRIORIZAR   Cada fila recibe puntaje de riesgo y P1/P2/P3    │
├─────────────────────────────────────────────────────────────────┤
│  3. REPARTIR    Selección múltiple → reparto entre analistas     │
│                 (o whitelist si son falsos positivos)            │
├─────────────────────────────────────────────────────────────────┤
│  4. INVESTIGAR  Caso con notas, adjuntos y checklist             │
├─────────────────────────────────────────────────────────────────┤
│  5. DOCUMENTAR  Correo al cliente con formulario adjunto         │
│                 → su respuesta se vincula sola al caso           │
├─────────────────────────────────────────────────────────────────┤
│  6. CERRAR      El analista valida, deja conclusión y cierra     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Módulos

### 3.1 Dashboard
**Qué hace:** panorama de la operación — volumen transaccional, evolución diaria,
operaciones sobre umbral y distribución por país, más el estado de alertas y casos.

**Cómo:** consulta agregados sobre la base transaccional y los combina con el estado
operativo (alertas activas, casos por estado).

---

### 3.2 Alertas — catálogo de detección
**Qué hace:** ejecuta los reportes que detectan comportamiento sospechoso. Devuelve una
tabla en pantalla, un Excel descargable y, si corresponde, notificación al equipo.

**Cómo:** cada reporte es una consulta parametrizada sobre la base transaccional. La
whitelist vigente se aplica antes de mostrar resultados, así los clientes justificados no
reaparecen.

**Catálogo (31 reportes):**

| Categoría | N° | Qué busca |
|---|---|---|
| Patrones AML | 8 | Estructuración, smurfing, circularidad cliente-beneficiario, terceros que fondean varias cuentas, beneficiario compartido, velocity |
| Comportamiento Clientes | 7 | Concentración o dispersión de beneficiarios, cambio de banco o corredor, volumen atípico respecto del histórico |
| AML Transaccional | 5 | Países de alto riesgo, régimen fiscal preferencial, rangos de monto por país |
| KYC / Jumio | 5 | Duplicidad documental, representantes cruzados entre personas y empresas, anomalías de edad |
| Crypto / Bridge | 4 | Operaciones y fondeos asociados a criptoactivos |
| Institucional | 1 | Transacciones recientes de clientes institucionales activos |
| Priorización | 1 | Datos de prueba para calibrar el modelo |

**Acciones sobre cada fila:**

| Acción | Para qué |
|---|---|
| ⚑ Whitelist | Silenciar al cliente por un período justificado |
| ⚠ Alertar | Marcar la fila para investigación |
| 👤 Asignar | Enviar la alerta a un analista |
| 🤖 Analizar | Lectura asistida del caso puntual |
| 📄 Documentos | Pedir documentación al cliente |

**Acciones masivas (administradores):** activando el modo selección aparecen casillas por
fila y dos operaciones sobre lo seleccionado — repartir entre analistas y pasar a
whitelist.

---

### 3.3 Alertados — bandeja de revisión
**Qué hace:** reúne las alertas marcadas para investigación, con su analista asignado,
prioridad y estado (activas / ya revisadas).

**Cómo:** cada alerta guarda la fila original del reporte que la originó, así el analista
ve el contexto sin volver a correr la consulta.

---

### 3.4 Casos — investigación
**Qué hace:** el expediente de la investigación. Concentra notas, documentos adjuntos,
alertas vinculadas y el checklist de lo solicitado al cliente.

**Estados:** Abierto → En Investigación → Bajo Revisión → Cerrado

**Vistas:** tarjetas (para repartir y ver de a muchos) y kanban por estado (para seguir
el avance).

**Acciones:**

| Acción | Quién | Para qué |
|---|---|---|
| ✋ Tomar caso | Cualquier analista | Auto-asignarse trabajo |
| ✎ Asignar | Cualquier analista | Asignar a otra persona |
| ✉️ Reenviar correo | Cualquier analista | Volver a pedir documentos |
| 📥 Excel | Cualquier analista | Exportar el caso completo |
| ☑ Selección + 👥 Asignar | Administrador | Repartir varios casos de una |
| 🗑 Eliminar | Administrador | Borrar el caso y sus adjuntos |

**Cómo funciona "Tomar caso":** si el caso ya lo tiene otra persona, el sistema avisa y
pide confirmación antes de reasignarlo, para que nadie le quite trabajo a un compañero sin
darse cuenta.

---

### 3.5 Whitelist
**Qué hace:** silencia las alertas de un cliente por 30, 60 o 90 días, con motivo
obligatorio.

**Cómo:** las entradas vigentes se aplican al ejecutar cada reporte. Vencen solas — no hay
que acordarse de sacarlas. El alcance puede ser un reporte puntual o todos.

**En lote:** desde la tabla de resultados se pueden mandar varias filas juntas. Es
idempotente: los que ya están vigentes se saltan, así correrlo dos veces no duplica.

---

### 3.6 Análisis Individual
**Qué hace:** dos herramientas de profundización.

1. **Perfil AML del cliente** — informe con transacciones, corredores, beneficiarios,
   horarios, métodos de pago y señales detectadas. Sale en Excel de varias hojas.
2. **Búsqueda de remesas** — detalle de transacciones puntuales por número de operación.

**Cómo:** cruza las fuentes transaccionales del cliente (remesas, wallet, cash call, QR) y
calcula señales sobre ese conjunto.

---

### 3.7 Institucional
**Qué hace:** monitoreo dedicado de clientes institucionales, que por volumen y perfil se
siguen aparte.

**Tres sub-módulos:**

| Sub-módulo | Qué muestra |
|---|---|
| Clientes | Ficha por cliente agrupada por estado de cumplimiento, con beneficiarios, transacciones y monto operado |
| Transacciones recientes | Últimas operaciones de los clientes activos (excluye bloqueados) |
| Alertas de umbral | Reglas configurables que avisan al superar un límite |

**Reglas de umbral:** se define la métrica (monto operado o cantidad de transacciones) y
la ventana (diaria, mensual o X días). Pueden ser por cliente o generales.

**Nota de uso:** la ficha de clientes es una foto que se recalcula al presionar
"Actualizar" — no refleja el minuto a minuto. Conviene actualizarla antes de un comité.

---

### 3.8 Búsqueda, Historial, Pendientes, Queries

| Módulo | Qué hace |
|---|---|
| **Búsqueda** | Consulta puntual de clientes, empresas y transacciones |
| **Historial** | Corridas anteriores con su Excel, para no repetir trabajo |
| **Pendientes** | Lo que espera acción del analista |
| **Queries** | Consultas SQL propias guardadas por el equipo |

---

### 3.9 Admin

| Sección | Qué permite |
|---|---|
| Usuarios y roles | Alta de analistas y qué módulos ve cada uno |
| Automatización | Programación de reportes y reglas de creación de casos |
| Priorización | Interruptor maestro del disparo automático para P1 |
| Mantenedor de documentos | Qué documentos pedir según el tipo de alerta |
| Auditoría | Bitácora de acciones con usuario y fecha |

---

## 4. Priorización de alertas

Cada fila que identifica a un cliente o empresa recibe un puntaje de riesgo.

**Componentes:**

| Componente | Qué mide |
|---|---|
| País de residencia | Riesgo de la jurisdicción |
| Nacionalidad | Riesgo de la nacionalidad declarada |
| PEP | Si es persona expuesta políticamente (personas) |
| Profesión / Actividad | Riesgo del rubro declarado |
| Multiusuario | Cantidad de operadores de la cuenta (empresas) |
| Beneficiarios | Cantidad de destinatarios distintos |

**Prioridades:** P1 riesgo alto · P2 medio · P3 bajo

> **En calibración.** Los pesos y umbrales están pendientes de validación por Compliance.
> Hasta entonces la prioridad orienta la revisión, no la reemplaza.

---

## 5. Solicitud de documentos

### Plantillas

| Plantilla | Cuándo | Adjunto |
|---|---|---|
| B2C general | Personas, cualquier país salvo Argentina | Formulario KYC Individual |
| B2C Argentina | Personas con origen Argentina | Formulario KYC Individual |
| B2B genérico | Empresas | Formulario B2B |
| Texto libre | Comunicación puntual | — |

En el flujo automático la plantilla se elige sola por el país del cliente; en el manual la
elige el analista.

### Checklist

| Estado | Significa | Lo pone |
|---|---|---|
| Pendiente | Se pidió, no llegó | El sistema al enviar |
| Recibido | El cliente respondió con archivo | El sistema al detectar la respuesta |
| Entregado | El analista lo revisó y lo da por válido | **Siempre una persona** |

### Escucha de respuestas

Cada solicitud lleva un código de referencia en el asunto que el cliente conserva al
responder. El sistema revisa la casilla periódicamente y:

- Si la respuesta trae archivos → los vincula al caso y pasa el checklist a *Recibido*
- Si no trae archivos → deja el texto como nota en el caso
- Si no corresponde a ninguna solicitud → no la toca

No se crea un caso nuevo: siempre actualiza el que originó la solicitud.

---

## 6. Automatizaciones

| Automatización | Qué hace | Dónde se configura |
|---|---|---|
| Programación de reportes | Corre reportes periódicamente | Admin › Automatización |
| Reglas de creación de casos | Abre casos por volumen o umbral | Admin › Automatización |
| Disparo automático P1 | Pide documentos y abre caso sin intervención | Admin › Priorización |
| Escucha de respuestas | Vincula documentos al caso | Automático |
| Alertas institucionales | Avisa al superar un umbral | Institucional › Alertas |

> El disparo automático está **apagado por defecto**. Mientras esté así, todas las
> alertas —incluidas las P1— pasan por revisión manual.

---

## 7. Roles y trazabilidad

**Acceso:** solo cuentas corporativas, con autenticación de Google. Cada usuario tiene rol
y módulos habilitados.

**Acciones reservadas a administradores:**

- Asignación masiva de casos
- Eliminación de casos
- Whitelist en lote
- Configuración de automatizaciones y del interruptor de priorización

Estas restricciones se validan en el servidor, no solo escondiendo botones.

**Auditoría:** queda registro de creación y edición de casos, asignaciones, reparto
masivo, eliminaciones, altas de whitelist, envío de solicitudes y cambios de
configuración.

---

## 8. Buenas prácticas

1. Priorizar siempre P1, aunque haya más P2/P3 acumuladas.
2. No marcar "Entregado" sin abrir el documento, aunque figure como *Recibido*.
3. Si la respuesta llegó sin adjunto, leer la nota del caso antes de volver a pedir.
4. Revisar los casos sin respuesta con más de 5 días hábiles.
5. No cerrar un caso sin dejar una nota de conclusión.
6. Usar la prioridad como apoyo, no como criterio único.
7. Actualizar la ficha institucional antes de un comité o reporte.
8. En whitelist, escribir un motivo que se entienda dentro de seis meses.
