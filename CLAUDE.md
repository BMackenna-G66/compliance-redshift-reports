# CLAUDE.md — Project Context

> Documento maestro de contexto del proyecto **compliance-redshift-reports**.
> Claude Code carga este archivo automáticamente al abrir el proyecto.
> Si vas a continuar este trabajo, **leer este archivo completo primero**.

---

## 1. Resumen ejecutivo

`compliance-redshift-reports` es un pipeline serverless en AWS que automatiza la
generación de reportes AML / screening de sanciones sobre datos transaccionales que
viven en un cluster Amazon Redshift.

El sistema corre en un cron (default: lunes 08:00 UTC), prende el cluster Redshift
(que está pausado por defecto para ahorrar costo), ejecuta una query parametrizada,
genera un Excel + resumen HTML, lo distribuye por email (SES) y Slack, y vuelve a
pausar el cluster. Toda la infraestructura está versionada en Terraform y el código
de la Lambda en Python 3.12.

El proyecto está en **Fase 1 / MVP**: un solo reporte (transacciones a países de alto
riesgo), una sola Lambda monolítica, schedule fijo. El roadmap contempla evolucionar
hacia un catálogo multi-reporte, un frontend estático con parámetros configurables y
una capa de Redshift ML + Amazon Bedrock (Claude) para detección de anomalías y
narrativas ejecutivas automatizadas.

---

## 2. Usuario y contexto organizacional

### Persona

- **Nombre:** Benjamin Mackenna
- **Email:** `benjamin.mackenna@global66.com`
- **Organización:** Global66 (fintech LATAM, remesas internacionales)
- **Equipo:** Compliance
- **Perfil técnico:** orientado a producto/compliance con conocimiento sólido de SQL y
  AWS pero **no es un desarrollador full-time**. Necesita soluciones que pueda operar
  y extender sin volverse experto en DevOps. **No le gusta Streamlit** — prefiere un
  frontend estático (HTML/JS) o low-code.

### Cuenta AWS

- **Account ID:** `561521480266`
- **Nombre cuenta:** Compliance
- **Email cuenta:** `compliance_aws@global66.com`
- **Role utilizado:** `compliance_admin` (vía IAM Identity Center)
- **SSO start URL:** `https://d-9067bd06cb.awsapps.com/start`
- **Región principal:** `us-east-1`

### Cluster Redshift

- **Identifier:** `compliance-redshift-cluster`
- **Database:** `dev`
- **Master user:** `awsuser`
- **Node type:** `ra3.large` (soporta pause/resume nativo)
- **Estado por defecto:** `paused` (el usuario lo prende manualmente cuando lo necesita;
  el pipeline lo automatiza)
- **Schema/tabla principal usada:** `db_prod.transaction.transaction`

### Sensibilidad de datos

El cluster maneja **PII de clientes y beneficiarios** (nombres, direcciones, emails,
teléfonos, números de cuenta bancaria) en el contexto de remesas internacionales.
El usuario aclaró que el reporte será leído únicamente por el equipo de Compliance
(autorizado), por lo que **no es necesario enmascarar PII en los entregables**, pero
el pipeline aplica buenas prácticas de seguridad por defecto:

- Cifrado at-rest en S3 (SSE-S3) y CloudWatch Logs
- Bucket S3 privado, sin acceso público
- Presigned URLs con expiración 24h en vez de archivos públicos
- IAM least-privilege en la Lambda
- Auditoría implícita vía CloudWatch Logs (retención 90 días)

Si en el futuro el alcance se amplía (recipientes externos, integración con sistemas
no controlados), endurecer: VPC para Lambda, KMS CMK propio, masking de PII en outputs.

---

## 3. Caso de uso

### Problema que resuelve

El equipo de Compliance necesita correr periódicamente una serie de queries de
screening AML (lavado de activos / financiamiento al terrorismo) sobre transacciones
outbound. Hoy:

1. Alguien prende manualmente el cluster Redshift cuando lo va a usar.
2. Pega la query desde un notebook (que no está versionada).
3. Exporta resultados a Excel a mano.
4. Manda por correo a quien corresponda.
5. Apaga el cluster.

Problemas: proceso manual, queries dispersas, sin trazabilidad, dependencia de una
persona, costo de cluster mal optimizado, no escala a más reportes.

### Solución diseñada

Pipeline serverless que:

- Versiona queries en Git (auditabilidad y revisión)
- Orquesta resume/pause automático del cluster (paga solo lo que se usa)
- Genera reportes con formato consistente (Excel + HTML)
- Distribuye automáticamente (email + Slack)
- Es extensible a múltiples reportes y futuro frontend de auto-servicio

### Primer reporte implementado: High-Risk Countries Transactions

Identifica transacciones outbound a 52 jurisdicciones de alto riesgo:

- Lista FATF "Call for Action" (DPRK, Irán, Myanmar)
- Lista FATF "Increased Monitoring"
- Sanciones OFAC

El SQL extrae detalle de cada transacción más un flag derivado:

`swift_country_mismatch_flag` — `TRUE` cuando los caracteres 5-6 del SWIFT BIC del
banco beneficiario (que codifican el país del banco) **no coinciden** con el
`beneficiary_country_code` declarado en la transacción. Patrón AML clásico que puede
indicar ofuscación de jurisdicción.

---

## 4. Arquitectura

### Diagrama de alto nivel

```
┌─────────────────────────┐
│   EventBridge Schedule  │   cron(0 8 ? * MON *)  ←  configurable
│   (compliance-…schedule)│
└────────────┬────────────┘
             ▼
┌──────────────────────────────────────────────┐
│   Lambda: compliance-redshift-reports        │
│   Python 3.12 · 1024 MB · timeout 900s       │
│                                              │
│   1. describe_clusters → status              │
│   2. resume_cluster (si paused)              │
│   3. poll until 'available'                  │
│   4. redshift-data:ExecuteStatement (Sync)   │
│   5. fetch results (paginated)               │
│   6. build Excel (openpyxl)                  │
│   7. render HTML (Jinja2)                    │
│   8. put_object → S3 (SSE-S3 encrypted)      │
│   9. generate_presigned_url (24h TTL)        │
│  10. ses:SendRawEmail (HTML + .xlsx)         │
│  11. POST Slack webhook                      │
│  12. pause_cluster (finally block)           │
└────────────┬──────────────────┬──────────────┘
             │                  │
             ▼                  ▼
       ┌──────────┐       ┌──────────────┐
       │   S3     │       │ CloudWatch   │
       │  reports │       │     Logs     │
       │  bucket  │       │ (retention   │
       │ (SSE+ver)│       │   90 days)   │
       └──────────┘       └──────────────┘
```

### Decisiones arquitectónicas (ADR-style)

#### ADR-1: Una sola Lambda en vez de Step Functions para el MVP

- **Decisión:** El MVP usa una única Lambda monolítica con timeout de 15 min en
  lugar de Step Functions.
- **Razones:** Menos componentes que mantener, menos costo, ciclo total de un reporte
  (~3 min incluyendo resume) cabe holgado en 15 min, observabilidad simple via
  CloudWatch Logs.
- **Cuándo migrar a Step Functions:** cuando agreguemos reportes pesados que excedan
  15 min, cuando necesitemos paralelismo entre reportes, o cuando queramos retry logic
  más sofisticado.

#### ADR-2: Redshift Data API en lugar de psycopg2 / JDBC

- **Decisión:** Usamos `redshift-data:ExecuteStatement` API.
- **Razones:** Asincrónico, no requiere mantener conexión TCP, **no requiere meter la
  Lambda en una VPC** (lo que simplifica IAM, networking, NAT gateways), tiene
  autenticación nativa con IAM. Encaja con el patrón de "ejecutar y olvidar".
- **Trade-off:** No soporta array parameters todavía (por eso `country_codes` se
  template-substitutes en vez de pasar como parámetro).

#### ADR-3: IAM auth en lugar de password almacenado

- **Decisión:** La Lambda se autentica al cluster vía
  `redshift:GetClusterCredentials` (temporary credentials), no usa password fijo.
- **Razones:** No hay credenciales que rotar, no hay secret extra que mantener, IAM
  policy controla quién puede usar qué DbUser. Es la práctica recomendada por AWS.

#### ADR-4: Lista de países en YAML separado del SQL

- **Decisión:** `config/high_risk_countries.yaml` versionado en Git, separado del
  archivo `.sql`.
- **Razones:** La lista FATF cambia ~3-4 veces al año. Tener un archivo dedicado
  permite que un compliance officer no-técnico haga PRs solo para actualizar la lista,
  con trazabilidad clara (quién agregó qué país, cuándo, con qué justificación en el
  commit message).

#### ADR-5: Frontend planificado como sitio estático, no Streamlit

- **Decisión (futura):** En la Fase 3, el frontend será HTML/JS en AWS Amplify (o S3
  + CloudFront), no Streamlit.
- **Razones:** El usuario explícitamente no se siente cómodo con Streamlit. Para un
  caso de uso de "formulario + botón" un sitio estático es más simple, más barato y
  más fácil de mantener.

#### ADR-6: SQL parametrizado mezcla Data API params + template substitution

- **Decisión:** `:since_date` viaja como parámetro Data API (parametrizado, anti-SQL-
  injection). `{country_codes}` y `{only_successful}` se sustituyen como template
  porque provienen de config trusted, no de input externo.
- **Razones:** Cuando agreguemos un frontend, los valores que vienen de input de
  usuario (fechas, tx IDs, etc.) seguirán como parámetros Data API. La lista de
  países nunca debería venir del frontend.

---

## 5. Stack tecnológico

| Capa             | Tecnología                       | Versión       | Por qué                                             |
|------------------|----------------------------------|---------------|-----------------------------------------------------|
| Compute          | AWS Lambda                       | Python 3.12   | Serverless, pay-per-run, 15 min timeout suficiente  |
| Data access      | Redshift Data API                | latest        | Async, sin VPC, IAM-auth                            |
| Database         | Amazon Redshift                  | RA3.large     | Ya provisionado, soporta pause/resume               |
| Storage          | S3                               | —             | Outputs cifrados con SSE-S3, lifecycle 90 días      |
| Secrets          | AWS Secrets Manager              | —             | Slack webhook (no en código)                        |
| Scheduling       | EventBridge Rules                | —             | Cron nativo, integración con Lambda                 |
| Email            | Amazon SES                       | —             | HTML + adjunto, sandbox-friendly para empezar       |
| Notifications    | Slack Incoming Webhook           | —             | Simple, sin auth compleja                           |
| Logs             | CloudWatch Logs                  | —             | Retención 90 días, búsqueda nativa                  |
| IaC              | Terraform                        | ≥ 1.5         | Estándar, gran ecosistema, HCL declarativo          |
| Python deps      | boto3, openpyxl, PyYAML, Jinja2  | ver `requirements.txt` | Mínimo viable, todas pure-Python o con manylinux wheels |
| Build tooling    | Bash script + pip target install | —             | Sin Docker, simple, reproducible                    |

### Versiones objetivo

```
terraform     >= 1.5.0
aws_provider  ~> 5.0
python        3.12
boto3         >= 1.34.0
openpyxl      >= 3.1.2
PyYAML        >= 6.0.1
jinja2        >= 3.1.3
```

---

## 6. Estructura del repositorio

```
compliance-redshift-reports/
├── CLAUDE.md                                # ← este archivo (contexto para Claude Code)
├── README.md                                # Arquitectura + roadmap + costos
├── DEPLOY.md                                # Guía paso a paso de deployment (9 pasos)
├── .gitignore                               # Excluye tfstate, tfvars, build artifacts
├── build_lambda.sh                          # Empaqueta la Lambda (deps + código)
│
├── queries/                                 # SQL files (uno por reporte)
│   └── high_risk_countries_transactions.sql # Query AML actual, parametrizada
│
├── config/                                  # Configuración versionada (no secretos)
│   └── high_risk_countries.yaml             # Lista FATF + OFAC de jurisdicciones
│
├── lambda/                                  # Código fuente Lambda
│   ├── handler.py                           # Orquestador completo del flow
│   ├── email_template.html                  # Template Jinja2 del correo HTML
│   └── requirements.txt                     # Dependencias Python
│
├── infra/                                   # Terraform
│   ├── main.tf                              # Recursos AWS (S3, Lambda, IAM, etc.)
│   ├── variables.tf                         # Inputs configurables
│   ├── outputs.tf                           # Outputs útiles (Lambda ARN, bucket, etc.)
│   └── terraform.tfvars.example             # Plantilla con valores ya pre-rellenados
│
└── lambda_build/                            # Generado por build_lambda.sh (gitignored)
    └── …                                    # Código + deps listos para zippear
```

### Archivos clave y qué hacen

#### `lambda/handler.py`

Función `handler(event, context)` es el entry point. Flow:

1. Resuelve parámetros: `since_date` (default primer día del mes), `only_successful`.
2. Carga lista de países desde `config/high_risk_countries.yaml`.
3. `ensure_cluster_available()` — describe + resume + poll.
4. `render_query()` — lee el `.sql`, sustituye `{country_codes}` y `{only_successful}`.
5. `execute_query()` — Data API con `:since_date` como parámetro.
6. `build_summary()` — agregados por país, top 10 USD, count de mismatches SWIFT.
7. `build_excel()` — openpyxl con header estilizado, freeze panes, columnas anchas.
8. `upload_to_s3()` + `generate_presigned_url()`.
9. `render_email_html()` — Jinja2.
10. `send_email()` — SES `send_raw_email` con multipart (HTML + .xlsx).
11. `post_slack()` — `urllib.request` POST al webhook.
12. `finally:` `pause_cluster()` — siempre se ejecuta, no falla el run si pause falla.

**Variables de entorno esperadas** (todas seteadas por Terraform):

```
CLUSTER_IDENTIFIER       — compliance-redshift-cluster
DATABASE_NAME            — dev
DB_USER                  — awsuser
S3_BUCKET                — <project>-<account>-<region>
SES_FROM_ADDRESS         — verified sender
SES_TO_ADDRESSES         — comma-separated recipients
SLACK_WEBHOOK_SECRET_ARN — Secrets Manager ARN
REPORT_NAME              — high_risk_countries
AUTO_PAUSE               — "true" / "false"
```

#### `queries/high_risk_countries_transactions.sql`

SQL con encabezado de metadata YAML en comentarios (para futuro parser que arme el
catálogo dinámico):

```sql
-- meta:
--   name: High-Risk Countries Transactions
--   schedule: "cron(0 8 ? * MON-FRI *)"
--   params:
--     - name: since_date
--       type: date
--       default: first_day_of_current_month
--     - name: only_successful
--       type: bool
--       default: false
```

La query SELECT extrae ~40 columnas de `db_prod.transaction.transaction` filtrando por
`beneficiary_country_code` en la lista, fecha `>= :since_date`, y opcionalmente
`payment_status = 'transferencia exitosa'`. Incluye un campo derivado
`swift_country_mismatch_flag` que es la base del análisis AML.

#### `infra/main.tf`

15-20 recursos AWS organizados en bloques comentados:

- S3 bucket + public access block + encryption + versioning + lifecycle 90d
- Secrets Manager secret + version (Slack webhook)
- IAM role + inline policy (least-privilege)
- CloudWatch Log Group (retention 90d)
- Lambda function + archive_file
- EventBridge rule + target + lambda permission

La IAM policy permite:

```
redshift:DescribeClusters, PauseCluster, ResumeCluster, GetClusterCredentials
   → solo sobre el cluster y dbuser específicos

redshift-data:ExecuteStatement, DescribeStatement, GetStatementResult, …
   → resource: "*" (Data API no es resource-scoped)

s3:PutObject, GetObject, ListBucket
   → solo el bucket de reportes

ses:SendEmail, SendRawEmail
   → resource: "*" (configuration sets opcionales para scoping mayor)

secretsmanager:GetSecretValue
   → solo el secret del Slack webhook
```

#### `build_lambda.sh`

Empaqueta la Lambda:

1. Limpia `lambda_build/`.
2. Copia `handler.py`, `email_template.html`, `queries/*.sql`, `config/*.yaml`.
3. `pip install --target lambda_build --platform manylinux2014_x86_64
   --implementation cp --python-version 3.12 --only-binary=:all:`
   → fuerza wheels compatibles con runtime Lambda (crítico si estás en Apple Silicon).
4. Limpia `__pycache__`, `tests/`, `*.pyc`.
5. Terraform's `archive_file` se encarga del zip final en el `apply`.

---

## 7. Configuración por defecto y dónde cambiarla

| Setting                  | Default                          | Dónde cambiar                                    |
|--------------------------|----------------------------------|--------------------------------------------------|
| Schedule                 | `cron(0 8 ? * MON *)` UTC        | `terraform.tfvars` → `schedule_expression`       |
| Auto-pause cluster       | `true`                           | `terraform.tfvars` → `auto_pause_cluster`        |
| Lambda memory            | 1024 MB                          | `terraform.tfvars` → `lambda_memory_mb`          |
| Lambda timeout           | 900 s                            | `terraform.tfvars` → `lambda_timeout_seconds`    |
| S3 lifecycle             | 90 días                          | `infra/main.tf` → `aws_s3_bucket_lifecycle_configuration` |
| Log retention            | 90 días                          | `infra/main.tf` → `aws_cloudwatch_log_group`     |
| Presigned URL TTL        | 24 h                             | `lambda/handler.py` → `ExpiresIn=24*60*60`       |
| `since_date` default     | Primer día del mes actual        | `lambda/handler.py` → `default_since`            |
| Cluster resume timeout   | 600 s (10 min)                   | `lambda/handler.py` → `MAX_WAIT_RESUME_SECONDS`  |
| Query timeout            | 600 s (10 min)                   | `lambda/handler.py` → `MAX_WAIT_QUERY_SECONDS`   |

---

## 8. Convenciones del proyecto

- **Naming AWS:** todos los recursos prefijados con `${project_name}` =
  `compliance-redshift-reports`.
- **Naming S3 bucket:** `compliance-redshift-reports-<account_id>-<region>`.
- **Naming S3 keys:** `<report_name>/<YYYYMMDDTHHMMSSZ>_since-<date>.xlsx`.
- **Naming Secrets Manager:** `compliance-redshift-reports/<purpose>`.
- **Tags:** `Project`, `Environment`, `ManagedBy=terraform`, `Owner=compliance`
  aplicadas vía `default_tags` del provider AWS.
- **SQL files:** snake_case, terminados en `.sql`, header YAML obligatorio (para Fase 2).
- **Python style:** type hints donde aporten, `logging` con nivel INFO en producción,
  `__future__ annotations` para forward refs, sin dependencias innecesarias.
- **Terraform style:** un bloque comentado por agrupación lógica, recursos en orden
  topológico (dependencias arriba), `description` en todas las variables.
- **Idioma de docs:** español para narrativa/decisiones, inglés para identificadores
  de código, comments y nombres de archivos.

---

## 9. Estado actual del proyecto

### Fase 1 / MVP — COMPLETADO (scaffold)

- [x] Estructura de repo
- [x] Query SQL parametrizada + lista de países separada
- [x] Lambda handler completa (Python 3.12)
- [x] Template HTML del email
- [x] Terraform completo (main, variables, outputs)
- [x] Build script
- [x] DEPLOY.md con 9 pasos
- [x] README.md y .gitignore

### Pendiente del MVP — POR HACER (acciones del usuario)

- [ ] Crear repo en GitHub (`gh repo create compliance-redshift-reports --private --source=. --push`)
- [ ] Configurar AWS SSO local (`aws configure sso` con la URL del SSO)
- [ ] Verificar email sender en SES (`aws ses verify-email-identity --email-address …`)
- [ ] Crear Slack webhook en `https://api.slack.com/apps` (canal sugerido `#compliance-reports`)
- [ ] Llenar `infra/terraform.tfvars` con webhook URL y recipientes
- [ ] Correr `./build_lambda.sh && cd infra && terraform apply`
- [ ] Test manual: `aws lambda invoke --function-name compliance-redshift-reports …`
- [ ] Verificar entrega de email + Slack + archivo en S3

### Decisiones del usuario ya capturadas

- Stack: Python + AWS nativo ✓
- IaC: Terraform ✓
- Hosting: AWS misma cuenta del Redshift ✓
- Tipo de Redshift: provisioned RA3.large con pause manual ✓
- Outputs: Slack webhook + Email Global66 + reporte HTML/PDF ✓
- Repo: nuevo en cuenta personal del usuario ✓
- Permisos AWS: admin (rol `compliance_admin`) ✓
- PII en outputs: no enmascarar (recipiente es Compliance) ✓

---

## 10. Roadmap — Fases siguientes

### Fase 2 — Catálogo multi-reporte

- Parser que lee la metadata YAML del header de cada `.sql` y la registra en DynamoDB
  como catálogo.
- Una sola Lambda con `report_name` como parámetro de evento.
- 3-5 reportes adicionales del backlog de Compliance.
- EventBridge schedule por reporte (definido en el header del SQL).

**Cambios técnicos:** introducir DynamoDB table `reports`, refactor del handler para
ser report-agnostic, posiblemente split en varias Lambdas pequeñas (query_runner,
report_builder, notifier) si la lógica común crece.

### Fase 3 — Frontend estático

- Sitio HTML/JS hospedado en AWS Amplify (alternativa: S3+CloudFront).
- Autenticación vía Cognito.
- Pantalla "Catálogo" lee `/reports` de un endpoint API Gateway.
- Pantalla "Ejecutar" muestra inputs autogenerados desde el YAML del SQL.
- Pantalla "Historial" lista runs desde DynamoDB con link a outputs en S3.
- POST → API Gateway → Lambda dispatcher que invoca al handler con params.

**Cambios técnicos:** introducir API Gateway, Cognito User Pool, DynamoDB table `runs`,
nueva Lambda dispatcher.

### Fase 4 — Inteligencia artificial

Dos capas combinables:

**A) Redshift ML** para detección de anomalías y clustering directamente en SQL:

```sql
CREATE MODEL fraud_detector
FROM (SELECT monto, hora, freq_dia, distancia_geo, ...
      FROM features_transacciones)
TARGET NULL
MODEL_TYPE KMEANS  -- o RANDOM_CUT_FOREST para anomaly detection
FUNCTION fn_anomaly_score
IAM_ROLE 'arn:aws:iam::561521480266:role/RedshiftML'
SETTINGS (S3_BUCKET 'compliance-redshift-ml-561521480266');
```

Luego en las queries del catálogo:

```sql
SELECT t.*, fn_anomaly_score(...) AS score
FROM transacciones t
WHERE fn_anomaly_score(...) > 0.85
ORDER BY score DESC;
```

**B) Amazon Bedrock (Claude)** para narrativa ejecutiva post-query:

```python
# después de ejecutar la query y obtener filas/agregados
prompt = f"""Estas son las {len(rows)} transacciones flagged por
fn_anomaly_score > 0.85 en los últimos 7 días: {summarize(rows)}

Analiza:
1. ¿Hay patrones de fraude (estructuración, geographic layering, etc.)?
2. ¿Qué clientes muestran cambios bruscos vs su histórico?
3. Devuelve JSON: {{nivel, cliente_id, razón, evidencia}}"""

response = bedrock.invoke_model(
    modelId="anthropic.claude-sonnet-4-6-20260101-v1:0",
    body=json.dumps({"messages": [...]}),
)
```

El output de Bedrock se incrusta en el email HTML como sección "Hallazgos del análisis".

### Fase 5 — Step Functions y endurecimiento

- Migración del handler monolítico a Step Functions con estados separados:
  `ResumeCluster → WaitForAvailable → RunQuery → BuildReport → Notify → PauseCluster`.
- VPC para Lambdas si auditoría lo exige.
- KMS Customer-Managed Key para todos los recursos.
- Multi-environment (dev/prod) con workspaces o módulos.
- CI/CD via GitHub Actions: `terraform plan` en PR, `apply` en merge a main.

---

## 11. Cómo extender el proyecto

### Agregar un nuevo reporte (Fase 1/2)

1. Crear `queries/<nuevo_reporte>.sql` con header YAML.
2. Si necesita config separada, agregarla a `config/`.
3. Si el reporte necesita un campo nuevo del template HTML, agregarlo a `email_template.html`.
4. (Fase 2 cuando exista) Agregar entry a DynamoDB catálogo.
5. (Fase 1 mientras tanto) Duplicar la Lambda o agregar dispatch por `report_name` en
   `handler.handler` y un nuevo EventBridge rule en Terraform.
6. `./build_lambda.sh && terraform apply`.

### Modificar la lista de países high-risk

1. Editar `config/high_risk_countries.yaml`.
2. Commit con mensaje descriptivo (ej. "Agregar Sudán por update FATF 2026-06").
3. `./build_lambda.sh && terraform apply`.
4. Próxima corrida automática usa la nueva lista.

### Cambiar el schedule

1. Editar `schedule_expression` en `infra/terraform.tfvars`.
2. `terraform apply` (no requiere rebuild de Lambda).

### Agregar un destinatario al email

1. Agregar a `ses_to_addresses` en `infra/terraform.tfvars` (comma-separated).
2. Si está en SES sandbox, primero `aws ses verify-email-identity --email-address …`.
3. `terraform apply`.

---

## 12. Operación y debugging

### Invocación manual

```bash
aws lambda invoke \
  --function-name compliance-redshift-reports \
  --payload '{"since_date":"2026-04-25","only_successful":false}' \
  --cli-binary-format raw-in-base64-out \
  --region us-east-1 \
  response.json
cat response.json
```

### Tailing de logs

```bash
aws logs tail /aws/lambda/compliance-redshift-reports --follow --region us-east-1
```

### Errores típicos y solución

| Error                                                | Causa probable                                              | Solución                                                              |
|------------------------------------------------------|-------------------------------------------------------------|------------------------------------------------------------------------|
| `MessageRejected: Email is not verified`             | SES sandbox, sender no verificado                           | `aws ses verify-email-identity --email-address …`                      |
| `AccessDenied: redshift:GetClusterCredentials`       | IAM policy no incluye el dbuser ARN                         | Verificar `arn:aws:redshift:…:dbuser:cluster/user` en la policy        |
| `Cluster did not become available within 600s`       | Cluster muy frío o problemas de capacity                    | Aumentar `MAX_WAIT_RESUME_SECONDS` en `handler.py`                     |
| `Query FAILED: relation "db_prod.transaction.transaction" does not exist` | DbUser no tiene permisos en ese schema | `GRANT SELECT ON db_prod.transaction.transaction TO awsuser;`          |
| `Statement is too large` en Slack                    | Resumen excede 40k chars                                    | Trimear top_countries o usar Block Kit en vez de text plano            |
| `ResourceNotFoundException` sobre el cluster         | Cluster en otra región o nombre mal                         | Verificar `aws_region` y `redshift_cluster_identifier` en tfvars       |

---

## 13. Glosario

| Término | Definición |
|---------|------------|
| **AML** | Anti-Money Laundering — prevención de lavado de activos. |
| **FATF** | Financial Action Task Force, grupo intergubernamental que publica listas de jurisdicciones de alto riesgo. |
| **OFAC** | Office of Foreign Assets Control (US Treasury), publica listas de sanciones. |
| **KYC** | Know Your Customer — verificación de identidad de clientes. |
| **SWIFT BIC** | Bank Identifier Code; los caracteres 5-6 codifican el país ISO del banco. |
| **Beneficiario** | El destinatario de una remesa. |
| **Remitter** | El emisor de la remesa (cliente de Global66). |
| **Data API** | API HTTP/async de Redshift para ejecutar SQL sin conexión persistente. |
| **RA3** | Familia de nodos Redshift con storage desacoplado, soportan pause/resume. |
| **Presigned URL** | URL temporal con permisos firmados, expira en N segundos. |
| **SES sandbox** | Modo default de SES que solo permite enviar a addresses verificadas. |
| **EventBridge** | Servicio AWS de scheduling y event routing, sucesor de CloudWatch Events. |

---

## 14. Cómo trabajar conmigo (Claude) en este proyecto

Si vas a continuar este proyecto en una nueva sesión de Claude Code:

1. **Lee este archivo entero antes de proponer cambios.** Las decisiones aquí están
   justificadas; cámbialas explícitamente si tienes razones, no por desconocimiento.
2. **Mantén la separación SQL ↔ config ↔ código.** Las queries van en `queries/`, los
   datos de configuración en `config/`, la lógica en `lambda/` y la infra en `infra/`.
   No mezcles.
3. **Cada cambio de SQL o de lista de países debería ser un commit dedicado** con
   mensaje descriptivo — es la única auditoría que tenemos.
4. **No introduzcas Docker** salvo necesidad real. El build script funciona para
   este caso.
5. **No agregues dependencias Python a menos que se justifique.** Cada dep extra es
   peso en el package y vector de seguridad.
6. **Cualquier cambio que toque IAM:** justifícalo en el PR. Es el componente más
   crítico para postura de seguridad.
7. **Si el usuario pide algo y no está claro:** pregúntale, no asumas. Especialmente
   en compliance, las suposiciones cuestan.
8. **Si vas a tocar la query principal:** preserva el flag `swift_country_mismatch_flag`,
   es valor neto vs la query original que tenía el usuario en un notebook.

---

## 15. Contacto y propiedad

- **Owner del proyecto:** Benjamin Mackenna (`benjamin.mackenna@global66.com`)
- **Equipo:** Compliance Global66
- **Repo de GitHub:** (pendiente de creación; usar `gh repo create compliance-redshift-reports --private`)
- **Cuenta AWS:** Compliance — 561521480266 (us-east-1)
