# WatchTower AML — Documentación del Proyecto

**Equipo:** Compliance Global66  
**Versión:** Mayo 2026  
**Acceso:** https://bmackenna-g66.github.io/compliance-redshift-reports/

---

## ¿Qué es WatchTower AML?

WatchTower AML es la plataforma de monitoreo de transacciones y screening de riesgo del equipo de Compliance de Global66. Permite ejecutar análisis sobre la base de datos transaccional de la compañía para detectar patrones asociados a lavado de activos, financiamiento al terrorismo y otras conductas de riesgo LA/FT/FPADM.

Todo el proceso corre de forma automática sobre los datos reales de Global66, sin necesidad de exportar ni mover información manualmente. Los resultados se entregan en formato Excel descargable directamente desde la plataforma.

---

## ¿Cómo funciona en la práctica?

1. El analista de Compliance abre la plataforma e inicia sesión con su cuenta corporativa.
2. Selecciona el análisis que quiere correr (por ejemplo, "Estructuración / Fraccionamiento").
3. Hace clic en **Ejecutar**. La plataforma enciende automáticamente la base de datos, corre el análisis y la apaga cuando termina.
4. En pocos minutos aparece el resultado con el número de registros encontrados y un botón para descargar el Excel.
5. El analista puede revisar los resultados, pedir al asistente de IA que los explique o genere un resumen ejecutivo, y marcar clientes en la **Lista Blanca** o en **Alertados** según corresponda.

---

## Módulos de la plataforma

### 📊 Dashboard

Pantalla de inicio con indicadores del estado actual del sistema:

- **Estado del cluster:** muestra si la base de datos está encendida o apagada, con botón para prender/apagar manualmente.
- **Entradas activas en Lista Blanca:** total de clientes/beneficiarios actualmente excluidos de los análisis.
- **Alertas activas:** total de casos marcados como alertados pendientes de revisión.
- **Evolución diaria de transacciones (últimos 7 días):** gráfico con el volumen total y número de transacciones exitosas por día.
- **Transacciones mayores a USD 300.000 (últimos 7 días):** listado de operaciones de alto monto para seguimiento inmediato.
- **Volumen por país de destino (últimos 7 días):** ranking de los principales países receptores de remesas.

---

### 🔍 Análisis (Reportes)

Catálogo de todos los análisis AML disponibles. Cada uno puede ejecutarse de forma independiente. Los resultados se guardan con fecha y hora, y el Excel puede descargarse en cualquier momento.

#### Análisis disponibles

---

**1. Transacciones a Países de Alto Riesgo**
Identifica todas las transacciones enviadas hacia jurisdicciones clasificadas como de alto riesgo según las listas FATF (Call for Action y Increased Monitoring) y sanciones OFAC. Incluye un indicador especial que detecta cuando el código de país del banco beneficiario en el SWIFT no coincide con el país de destino declarado — una señal clásica de ocultamiento de jurisdicción.

---

**2. Transacciones a Régimen Fiscal Preferencial (90 días)**
Detecta envíos hacia países considerados paraísos fiscales o regímenes de tributación preferencial. Útil para identificar posibles casos de evasión fiscal o triangulación financiera.

---

**3. Fondeos desde Régimen Fiscal Preferencial (7 días)**
Complemento del análisis anterior: identifica clientes que reciben fondos (pay-ins) provenientes de países con régimen fiscal preferencial antes de realizar envíos.

---

**4. Estructuración / Fraccionamiento**
Detecta clientes que realizan múltiples transacciones de montos similares en ventanas de tiempo cortas, lo que podría indicar un intento de mantenerse por debajo de los umbrales de reporte (smurfing). Incluye análisis de patrones de monto y frecuencia.

---

**5. Acumulación Pay In → Pay Out (7 días)**
Identifica clientes que acumulan fondos mediante múltiples ingresos (pay-ins) y luego los envían en pocas transacciones salientes (pay-outs), un patrón típico de layering en lavado de activos.

---

**6. Pay In Pequeños → Pay Out (Smurfing)**
Variante del análisis de smurfing enfocada en ingresos de montos pequeños que se consolidan en envíos más grandes. Particularmente relevante para detectar cuentas "mula" o intermediarias.

---

**7. Velocity Pay In ↔ Pay Out < 24 horas**
Detecta casos donde el tiempo entre el ingreso de fondos y su envío es menor a 24 horas, lo que sugiere que el cliente no está usando los fondos para necesidades propias sino que los está transfiriendo de forma inmediata (pass-through).

---

**8. Tercero que Fondea Una Sola Cuenta**
Identifica casos donde un mismo tercero (por nombre o RUT/DNI) aparece fondeando únicamente la cuenta de un cliente específico. Puede indicar que el cliente está recibiendo fondos de un financista externo.

---

**9. Tercero que Fondea Múltiples Cuentas**
Variante del análisis anterior: detecta cuando un mismo tercero fondea a varios clientes distintos. Patrón de alta alerta para redes de intermediación o distribución coordinada de fondos.

---

**10. Circularidad DNI Cliente ↔ Beneficiario**
Detecta casos donde el RUT/DNI del cliente remitente coincide con el RUT/DNI de un beneficiario de otro cliente. Permite identificar flujos circulares o retorno de fondos que podrían ocultar el origen real del dinero.

---

**11. Beneficiario Compartido por Múltiples Remitentes**
Identifica beneficiarios que reciben fondos de varios clientes distintos sin relación aparente entre sí. Un mismo beneficiario siendo fondeado por muchos remitentes puede ser señal de concentración en un destino con propósito ilícito.

---

**12. Concentración de Beneficiarios**
Para cada cliente, calcula qué porcentaje de sus envíos van hacia un mismo beneficiario. Una concentración muy alta puede indicar dependencia de un único canal de destino.

---

**13. Dispersión de Beneficiarios**
Contrario al análisis anterior: detecta clientes que envían a un número inusualmente alto de beneficiarios distintos en poco tiempo, lo que puede indicar uso de la plataforma como mecanismo de distribución masiva de fondos.

---

**14. Alto Volumen vs. Histórico**
Compara el volumen transaccional de los últimos 7 días de cada cliente con su promedio histórico de los últimos 90 días. Alerta cuando el volumen reciente es significativamente superior al esperado según el perfil del cliente.

---

**15. Cambio de Banco Outbound**
Detecta clientes que en los últimos 7 días enviaron a un banco destino distinto al que usaron habitualmente en los 30 días anteriores. Un cambio brusco de banco beneficiario puede indicar que el cliente está usando una cuenta diferente para evadir controles.

---

**16. Corredor Nuevo para el Cliente**
Identifica cuando un cliente realiza una transacción hacia un país o corredor que nunca había usado en los últimos 90 días. Activar un corredor nuevo, especialmente hacia países de riesgo, es una señal de alerta temprana.

---

**17. Mismatch SWIFT vs. País Beneficiario**
Analiza el código BIC (SWIFT) del banco beneficiario y verifica si el código de país embebido en ese código coincide con el país de destino declarado en la transacción. Una discrepancia puede indicar ocultamiento del destino real de los fondos.

---

**18. Tasas de Aprobación / Rechazo KYC por Flujo**
Muestra las tasas de aprobación y rechazo del proceso de verificación de identidad (KYC via Jumio) desglosadas por tipo de flujo y país. Útil para detectar flujos con tasas de aprobación anómalas o intentos masivos de registro fallido.

---

**19. Documentos Jumio Duplicados / Flujos Múltiples**
Detecta documentos de identidad que han sido utilizados en más de un proceso de verificación KYC, lo que puede indicar uso de documentos compartidos o intentos de crear múltiples cuentas con el mismo documento.

---

**20. Clientes B2C como Representantes Legales**
Identifica personas naturales (clientes B2C) que aparecen como representantes legales de empresas registradas en la plataforma. Permite detectar vínculos entre personas y empresas que podrían ser relevantes en investigaciones de estructuras societarias complejas.

---

**21. Top 15 Empresas con Más Representantes Legales**
Lista las empresas con mayor número de representantes legales registrados, lo que puede indicar estructuras societarias inusualmente complejas o fragmentación deliberada del control.

---

**22. Clientes con Anomalía de Edad**
Detecta clientes cuya edad calculada según su fecha de nacimiento es menor a 18 años o mayor a 90 años. Puede indicar uso de datos falsos en el registro o suplantación de identidad.

---

**23–26. Análisis de Actividad Crypto / Bridge**

- **Transacciones Bridge/Crypto (30d):** Mapeo completo de transacciones que pasan por puentes blockchain o activos virtuales.
- **Cash Calls Bridge/Crypto (30d):** Fondeos relacionados con operaciones de activos virtuales.
- **Crypto hacia Países de Riesgo (30d):** Transacciones de activos virtuales con destino en jurisdicciones de alto riesgo.
- **Actividad Completa Bridge (30d):** Vista consolidada de toda la actividad de bridge, incluyendo balances de billeteras y flujos completos.

---

### 📋 Historial de Ejecuciones

Registro de todos los análisis ejecutados con fecha, hora, número de resultados encontrados y enlace para descargar el Excel. Los reportes se conservan por 90 días.

---

### 🛡️ Lista Blanca

Registro de clientes, beneficiarios o cualquier entidad que el equipo de Compliance ha decidido **excluir temporalmente** de los análisis. Útil cuando un cliente tiene actividad inusual por razones legítimas ya investigadas y documentadas (por ejemplo, un cliente corporativo con volúmenes naturalmente altos).

**Campos:**
- **Campo:** qué tipo de identificador se está excluyendo (customer_id, email, etc.)
- **Valor:** el identificador específico del cliente o entidad
- **Duración:** 30, 60 o 90 días — vence automáticamente
- **Alcance:** Global (excluye de todos los análisis) o por Reporte específico
- **Razón:** justificación del analista que generó la exclusión

Una vez vencida la duración, el cliente vuelve a aparecer en los análisis automáticamente.

---

### 🚨 Alertados

Registro de clientes o transacciones que el equipo marcó como casos de interés para seguimiento. Se divide en dos secciones:

- **Alertas activas:** casos pendientes de resolución.
- **Ya revisados:** casos que fueron investigados y cerrados, con fecha de revisión.

Desde cualquier resultado de un análisis se puede agregar directamente un cliente a Alertados con un clic, sin necesidad de copiar datos manualmente.

---

### ⚙️ Configuración

Panel donde el analista puede:
- Configurar la clave de la API de inteligencia artificial (Gemini) para usar el asistente de análisis.
- Ver el estado de conexión a los distintos servicios.

---

## Asistente de IA

Cada resultado de análisis incluye un botón **"Analizar con IA"** que envía los datos al modelo de inteligencia artificial Gemini. El asistente puede:

- Resumir los hallazgos en lenguaje natural para incluir en informes.
- Identificar los patrones más relevantes dentro de los resultados.
- Generar un párrafo ejecutivo listo para adjuntar a un reporte de Compliance.

El análisis de IA es una ayuda para el analista — la decisión final siempre la toma el equipo de Compliance.

---

## Lista Blanca y su efecto en los análisis

Cuando un cliente está en la Lista Blanca, **no aparece en los resultados de ningún análisis** durante el período vigente. Esto es automático: no es necesario filtrar manualmente los Excel. Al vencer el plazo, el cliente vuelve a ser incluido en todos los análisis.

El alcance "Global" excluye al cliente de todos los reportes. El alcance "Por Reporte" permite excluirlo solo de un análisis específico, manteniéndolo visible en los demás.

---

## Preguntas frecuentes del equipo

**¿Cuánto tarda en ejecutarse un análisis?**
Entre 1 y 5 minutos dependiendo del volumen de datos. La plataforma muestra el progreso en tiempo real.

**¿Qué pasa si el cluster está apagado?**
La plataforma lo enciende automáticamente al lanzar un análisis y lo apaga sola cuando termina. No es necesario hacer nada.

**¿Los resultados se actualizan solos?**
No. Cada análisis refleja los datos al momento en que se ejecutó. Para datos frescos hay que correr el análisis nuevamente.

**¿Puedo correr varios análisis al mismo tiempo?**
Sí. Cada ejecución es independiente y los resultados quedan guardados en el historial.

**¿Puedo agregar mis propias queries?**
Sí. En la sección de configuración existe un editor de SQL personalizado donde se pueden guardar y ejecutar análisis propios.

**¿Por cuánto tiempo están disponibles los Excel?**
Los archivos se conservan por 90 días desde la fecha de ejecución.

**¿Quién tiene acceso a la plataforma?**
Solo usuarios con cuenta corporativa Global66 autorizados por el equipo de Compliance. El acceso está protegido con autenticación de doble factor.

---

## Glosario AML

| Término | Significado en contexto |
|---|---|
| **LA/FT/FPADM** | Lavado de Activos / Financiamiento al Terrorismo / Financiamiento a la Proliferación de Armas de Destrucción Masiva |
| **FATF** | Grupo de Acción Financiera Internacional — publica las listas de jurisdicciones de alto riesgo |
| **OFAC** | Oficina de Control de Activos Extranjeros del Tesoro de EE.UU. — publica listas de sanciones |
| **Smurfing** | Técnica de fraccionamiento donde se dividen grandes sumas en múltiples transacciones pequeñas para evitar controles |
| **Layering** | Proceso de "capas" para dificultar el rastreo del origen de fondos ilícitos |
| **Pass-through** | Cuenta que recibe fondos y los transfiere rápidamente sin retenerlos, actuando como intermediaria |
| **Pay-in** | Ingreso de fondos a la plataforma (depósito del cliente) |
| **Pay-out** | Envío de fondos desde la plataforma (remesa al beneficiario) |
| **Corredor** | Combinación de país origen + país destino de una remesa |
| **KYC** | Know Your Customer — proceso de verificación de identidad del cliente |
| **SWIFT/BIC** | Código internacional de identificación de bancos |
| **Whitelist** | Lista Blanca — clientes excluidos temporalmente de los análisis |
| **Bridge** | Operación que conecta el sistema fiat con activos virtuales (crypto) |
| **Régimen Fiscal Preferencial** | Jurisdicciones con baja o nula tributación, asociadas a estructuras de evasión |
