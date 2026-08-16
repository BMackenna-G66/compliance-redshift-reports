# WatchTower — Plataforma de Monitoreo AML

Plataforma interna de Compliance de Global66 para detección, priorización, investigación
y cierre de alertas de lavado de activos y financiamiento del terrorismo.

Unifica en un solo lugar lo que antes vivía repartido entre consultas SQL sueltas,
planillas y correos: el catálogo de reportes de detección, la bandeja de alertas, los
casos de investigación, la solicitud de documentación al cliente y su seguimiento.

---

## Qué resuelve

| Antes | Con WatchTower |
|---|---|
| Consultas SQL corridas a mano, una por una | Catálogo de 31 reportes ejecutables desde el navegador |
| Priorización por criterio individual del analista | Puntaje de riesgo y prioridad (P1/P2/P3) calculados por el sistema |
| Reparto de alertas por planilla o mensaje | Asignación masiva con reparto equitativo entre analistas |
| Correos al cliente redactados a mano | Plantillas oficiales con el formulario adjunto automáticamente |
| Documentos recibidos rastreados por memoria | Checklist por caso, actualizado solo al recibir la respuesta |
| Sin trazabilidad de quién hizo qué | Bitácora de auditoría de toda acción relevante |

---

## Módulos

| Módulo | Para qué sirve |
|---|---|
| **Dashboard** | Vista general: volumen transaccional, alertas y casos en curso |
| **Alertas** | Catálogo de reportes de detección. Se ejecutan bajo demanda o programados |
| **Alertados** | Bandeja de alertas marcadas para revisión, con su analista asignado |
| **Casos** | Casos de investigación: estados, notas, adjuntos y checklist de documentos |
| **Pendientes** | Lo que espera acción del analista |
| **Whitelist** | Clientes cuyas alertas se silencian por un período justificado |
| **Historial** | Corridas anteriores de reportes, con su Excel descargable |
| **Análisis Individual** | Perfil AML completo de un cliente o empresa, y búsqueda de remesas |
| **Búsqueda** | Consulta puntual de clientes, empresas y transacciones |
| **Institucional** | Monitoreo dedicado de clientes institucionales y reglas de umbral |
| **Queries** | Consultas SQL propias guardadas por el equipo |
| **Admin** | Usuarios y roles, automatizaciones, mantenedores y auditoría |

---

## Catálogo de detección

31 reportes agrupados por tipo de riesgo:

| Categoría | Reportes | Ejemplos |
|---|---|---|
| **Patrones AML** | 8 | Estructuración, smurfing, circularidad, beneficiario compartido |
| **Comportamiento Clientes** | 7 | Concentración de beneficiarios, cambios de banco, volumen atípico |
| **AML Transaccional** | 5 | Países de alto riesgo, régimen fiscal preferencial, rangos por país |
| **KYC / Jumio** | 5 | Duplicidad documental, representantes cruzados, anomalías de edad |
| **Crypto / Bridge** | 4 | Operaciones y fondeos asociados a criptoactivos |
| **Institucional** | 1 | Transacciones recientes de clientes institucionales activos |
| **Priorización** | 1 | Datos de prueba para calibrar el modelo de riesgo |

---

## Cómo funciona

```
        Reporte de detección
   (bajo demanda o programado)
                │
                ▼
      Puntaje de riesgo + prioridad          ── P1 / P2 / P3
                │
                ▼
        Bandeja de Alertados  ──────────►  Whitelist
                │                          (silenciar con justificación)
                ▼
      Reparto entre analistas
   (uno por uno o equitativo)
                │
                ▼
      Caso de Investigación
                │
                ▼
   Solicitud de documentos al cliente
      (plantilla + formulario adjunto)
                │
                ▼
      El cliente responde por correo
                │
                ▼
   El adjunto se vincula solo al caso
      y el checklist pasa a "Recibido"
                │
                ▼
      El analista valida y cierra
```

### Priorización

Cada fila que identifica a un cliente o empresa recibe un puntaje de riesgo que combina
país de residencia, nacionalidad, condición de PEP, profesión o actividad, y cantidad de
beneficiarios. De ese puntaje sale la prioridad:

- **P1** — riesgo alto, atención el mismo día
- **P2** — riesgo medio
- **P3** — riesgo bajo

> Los pesos de cada componente y los umbrales están en calibración por parte de
> Compliance. Hasta su validación, la prioridad es apoyo a la revisión del analista,
> no criterio único de decisión.

### Solicitud de documentos

Cuatro plantillas oficiales, cada una con su formulario adjunto automáticamente:

| Plantilla | Uso | Adjunto |
|---|---|---|
| B2C general | Personas, cualquier país salvo Argentina | Formulario KYC Individual |
| B2C Argentina | Personas con origen Argentina | Formulario KYC Individual |
| B2B genérico | Empresas | Formulario B2B |
| Texto libre | Comunicación puntual fuera de lo estándar | — |

En el flujo automático la plantilla se elige sola según el país del cliente. En el manual
la elige el analista.

### Seguimiento de lo recibido

Cada documento solicitado tiene tres estados:

- **Pendiente** — se pidió, no llegó
- **Recibido** — el cliente respondió con un archivo (lo marca el sistema)
- **Entregado** — el analista abrió el documento y lo dio por válido

El sistema **nunca** marca "Entregado" por su cuenta: esa confirmación es siempre humana.

### Escucha de respuestas

Cada solicitud lleva un código de referencia en el asunto. Cuando el cliente responde, el
sistema lo reconoce, vincula los adjuntos al caso correcto y actualiza el checklist. Si la
respuesta no trae archivos, igual queda registrada como nota en el caso.

---

## Automatizaciones

| Automatización | Qué hace |
|---|---|
| Programación de reportes | Ejecuta reportes del catálogo de forma periódica |
| Reglas de creación de casos | Abre casos solos según volumen o umbral de un campo |
| Disparo automático para P1 | Solicita documentos y abre el caso sin intervención manual |
| Escucha de respuestas | Vincula al caso los documentos que manda el cliente |
| Alertas institucionales | Avisa cuando un cliente supera un umbral configurado |

> El disparo automático de solicitudes está **apagado por defecto** hasta que el modelo de
> priorización quede validado.

---

## Roles y trazabilidad

Acceso restringido a cuentas corporativas mediante autenticación de Google. Cada usuario
tiene un rol y un conjunto de módulos habilitados.

Las acciones de control —asignación masiva, eliminación de casos y whitelist en lote—
están reservadas a administradores y validadas del lado del servidor. Toda acción
relevante queda en la bitácora de auditoría con usuario, fecha y detalle.

---

## Documentación relacionada

| Documento | Contenido |
|---|---|
| `RESUMEN_APP.md` | Resumen funcional: módulos, qué hace cada uno y cómo |
| `DEPLOY.md` | Guía de despliegue |
| `WATCHTOWER_AML_DOCS.md` | Documentación técnica ampliada |

La metodología de negocio detrás de las alertas está en el documento corporativo
*Metodología de Perfilamiento de Clientes y Alertas Transaccionales* (MET-G81-001).

---

## Stack

Frontend estático (HTML + Alpine.js + Tailwind) sobre GitHub Pages, autenticado con
Firebase. Backend serverless en AWS Lambda (Python) contra Redshift vía Data API, con
almacenamiento operativo en S3 y notificaciones por correo y Slack.

> La configuración de infraestructura, credenciales y endpoints no se documenta en este
> repositorio público. Está en el gestor de secretos de la cuenta AWS correspondiente.
