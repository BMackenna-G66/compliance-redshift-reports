# Prompt inicial sugerido para Claude Code

Copia/pega este texto como tu primer mensaje en el nuevo proyecto de Claude Code,
después de haber colocado el repo `compliance-redshift-reports/` como working directory
de Claude Code.

---

```
Hola. Acabo de clonar este proyecto desde un scaffold inicial. Antes de hacer cualquier
cambio quiero que:

1. Leas CLAUDE.md completo — tiene el contexto, las decisiones de arquitectura y el
   estado actual. Es la fuente de verdad.

2. Revises la estructura del repo (`tree -L 3` o `ls -la` por carpeta) y confirma que
   todos los archivos listados en CLAUDE.md sección 6 están presentes.

3. Hagas un health check pasivo (sin ejecutar nada) de:
   - `infra/main.tf` — busca referencias rotas, variables no declaradas, recursos
     huérfanos.
   - `lambda/handler.py` — busca imports faltantes, env vars usadas pero no
     declaradas en Terraform, errores de tipo obvios.
   - `queries/high_risk_countries_transactions.sql` — valida que los placeholders
     `{country_codes}`, `{only_successful}` y `:since_date` estén consistentes con
     `render_query()` en `handler.py`.
   - `build_lambda.sh` — verifica que las rutas existan y que la lista de archivos
     copiados sea exhaustiva.

4. Me reportes en formato:
   - "✓ All clear" si todo cuadra
   - O una lista numerada de hallazgos accionables (sin proponer soluciones todavía,
     solo el diagnóstico)

5. Esperes mi confirmación antes de tocar archivos.

Mi siguiente paso después de tu reporte va a ser ejecutar el deployment (DEPLOY.md).
Si encuentras algo bloqueante para eso, márcalo como [CRÍTICO].

Contexto adicional sobre mí:
- Trabajo en Compliance en Global66 (fintech LATAM, remesas)
- Mi cuenta AWS es 561521480266 (us-east-1), rol compliance_admin
- El cluster Redshift es compliance-redshift-cluster (RA3.large, ya provisionado)
- Prefiero respuestas concisas en español; código y nombres técnicos en inglés
- No soy desarrollador full-time, así que prefiero soluciones simples y bien
  documentadas sobre soluciones elegantes pero crípticas
```

---

## Por qué este prompt funciona bien

- **Establece la jerarquía:** CLAUDE.md es la fuente de verdad, no la memoria de
  Claude ni asunciones genéricas.
- **Pide diagnóstico antes que acción:** evita que Claude empiece a "arreglar"
  cosas que no están rotas o que se justifican por las decisiones del proyecto.
- **Limita el alcance del primer turno:** solo verificación, no cambios. Te da
  oportunidad de calibrar la calidad antes de delegar.
- **Da contexto sobre el usuario:** Claude adapta el tono y la profundidad técnica.
- **Define formato de output:** evita respuestas vagas o demasiado largas.

## Prompts útiles para turnos siguientes

Después del health check, según hacia dónde quieras ir:

**Para deployar el MVP:**

```
Health check OK. Ahora ayudame a ejecutar DEPLOY.md paso a paso. Vamos uno por uno
— no avances al siguiente hasta que yo confirme que el anterior funcionó. Empezamos
por el paso 1.
```

**Para agregar un reporte nuevo (Fase 2):**

```
Quiero agregar un segundo reporte: <descripción del reporte y SQL>. Antes de
implementarlo, proponime cómo lo encajamos en la estructura actual sin romper el
flujo del reporte existente. Considera la transición hacia el catálogo dinámico
descrito en CLAUDE.md sección 10.
```

**Para empezar Fase 4 (Redshift ML + Bedrock):**

```
Quiero arrancar la Fase 4 descrita en CLAUDE.md sección 10. Específicamente, quiero
empezar por un modelo de anomaly detection sobre la query de high-risk countries.
Proponé un plan en 4-5 pasos, con la query SQL del CREATE MODEL y los cambios al
handler. No escribas código todavía.
```

**Para revisar/auditar lo existente:**

```
Hace <X tiempo> que esto está corriendo. Hacé una auditoría: revisá los últimos
20 runs en CloudWatch Logs (vía aws logs filter-log-events), reportá errores
recurrentes, costo aproximado, y posibles optimizaciones. Output: bullet points
priorizados.
```

**Para troubleshooting:**

```
Falló el run de hoy. El response.json dice <pegar error>. Diagnosticá la causa,
proponé fix mínimo, y decime si necesito hacer redeploy completo o solo
terraform apply (sin rebuild).
```
