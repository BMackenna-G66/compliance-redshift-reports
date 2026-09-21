/* ============================================================================
   WatchTower v2 — dominio
   ----------------------------------------------------------------------------
   Lo que el front necesita saber del negocio, extraído del prototipo
   "Watchtower Hub v5.dc.html" y contrastado contra el repo.

   LA REGLA QUE ORDENA ESTE ARCHIVO
   --------------------------------
   Sólo vive acá lo que es PRESENTACIÓN. Todo lo que es una decisión de
   negocio se pide al backend, aunque el prototipo lo traiga escrito.

   El prototipo hardcodea los 10 flags con sus pesos y los 31 reportes. Hoy
   coinciden exactamente con el repo —lo verifiqué: 10 de 10 flags, mismos
   pesos, cero diferencias— pero coincidir hoy no es estar sincronizado. El
   día que alguien cambie un peso en `aml_individual.py`, una pantalla que
   dice "Flags y pesos" estaría mintiendo, y nadie se enteraría hasta que un
   analista defienda un caso con un número que no es.

   Por eso: los colores de nivel y de categoría se quedan (son decisiones
   visuales), y los pesos y el catálogo se piden.
   ========================================================================= */

/* ═══════════════════════════════════════════════════════════════════════════
   ⚠️  HAY DOS PUNTAJES DISTINTOS Y LOS DOS SE LLAMAN `risk_score`.
   ═══════════════════════════════════════════════════════════════════════════

   1. EL DEL ANÁLISIS INDIVIDUAL — `NIVELES`, más abajo.
      Escala 0–19: la suma de los pesos de las diez banderas de
      `lambda/aml_individual.py`. Cortes ≥10 / 6 / 3.

   2. EL DE LAS ALERTAS TRANSACCIONALES — `ESCALA_ALERTA`.
      Escala 0–100, calculado por el SQL de cada reporte y guardado en
      `row_data.risk_score`. Cortes ≥75 P1 / ≥50 P2 / P3
      (`lambda/handler.py:699`).

   NO SON INTERCAMBIABLES. Medido sobre las 122 alertas activas de producción,
   los puntajes van de 0 a 87: aplicarles los cortes del análisis individual
   pintaría 109 de 110 como CRÍTICO, y el color dejaría de decir nada justo en
   la pantalla donde se decide a quién mirar primero.

   Por eso cada escala tiene su propia función y ninguna acepta el puntaje de
   la otra sin decirlo.
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── Niveles de riesgo · ANÁLISIS INDIVIDUAL (0–19) ─────────────────────────
   Los CORTES los decide el backend al calcular el score. Acá está sólo cómo
   se pintan, y el rango se muestra como referencia para el analista — si el
   backend cambia los cortes, esto se ajusta a mano y hay un test que lo
   compara. */
export const NIVELES = {
  CRITICO: { etiqueta: 'Crítico', desde: 10, color: 'var(--nivel-critico)', fondo: 'var(--nivel-critico-tenue)', claro: 'var(--nivel-critico-claro)' },
  ALTO:    { etiqueta: 'Alto',    desde: 6,  color: 'var(--nivel-alto)',    fondo: 'var(--nivel-alto-tenue)',    claro: 'var(--nivel-alto-claro)' },
  MEDIO:   { etiqueta: 'Medio',   desde: 3,  color: 'var(--nivel-medio)',   fondo: 'var(--nivel-medio-tenue)',   claro: 'var(--nivel-medio-claro)' },
  BAJO:    { etiqueta: 'Bajo',    desde: 0,  color: 'var(--nivel-bajo)',    fondo: 'var(--nivel-bajo-tenue)',    claro: 'var(--nivel-bajo-claro)' },
};

/** Máximo posible del análisis individual: la suma de los diez pesos. Se usa
 *  para mostrar "12/19", que es lo único que vuelve legible un 12. */
export const NIVELES_MAXIMO = 19;

/**
 * El nivel de un score del ANÁLISIS INDIVIDUAL (0–19).
 *
 * No le pases el `risk_score` de una alerta: está en otra escala y te va a
 * devolver CRÍTICO para casi todo. Para eso está `prioridadDeAlerta()`.
 *
 * Un score ausente no es "bajo": es desconocido, y pintarlo de verde
 * tranquiliza sobre algo que no se midió.
 */
export function nivelDe(score) {
  if (score === null || score === undefined || score === '') return null;
  const n = Number(score);
  if (Number.isNaN(n)) return null;
  if (n >= NIVELES.CRITICO.desde) return 'CRITICO';
  if (n >= NIVELES.ALTO.desde)    return 'ALTO';
  if (n >= NIVELES.MEDIO.desde)   return 'MEDIO';
  return 'BAJO';
}

/* ── Prioridad · ALERTAS TRANSACCIONALES (0–100) ────────────────────────────
   Los cortes son los de `lambda/handler.py:699`. Verificados contra las 122
   alertas activas: P1 86–87, P2 51–68, P3 0–50. */
export const ESCALA_ALERTA = {
  P1: { etiqueta: 'P1', desde: 75, descripcion: 'Atender primero',
        color: 'var(--nivel-critico)', texto: 'var(--nivel-critico-texto)',
        fondo: 'var(--nivel-critico-tenue)' },
  P2: { etiqueta: 'P2', desde: 50, descripcion: 'Prioridad media',
        color: 'var(--nivel-alto)', texto: 'var(--nivel-alto-texto)',
        fondo: 'var(--nivel-alto-tenue)' },
  P3: { etiqueta: 'P3', desde: 0, descripcion: 'Prioridad baja',
        color: 'var(--nivel-bajo)', texto: 'var(--nivel-bajo-texto)',
        fondo: 'var(--nivel-bajo-tenue)' },
};
export const ESCALA_ALERTA_MAXIMO = 100;

/**
 * La prioridad de una alerta a partir de su `risk_score` (0–100).
 *
 * Devuelve `null` si no hay puntaje. Doce de las 122 alertas activas no
 * traen uno, y mostrarlas como P3 diría que ya se las evaluó y salieron
 * bajas — cuando en realidad nunca se las midió.
 */
export function prioridadDeAlerta(score) {
  if (score === null || score === undefined || score === '') return null;
  const n = Number(score);
  if (Number.isNaN(n)) return null;
  if (n >= ESCALA_ALERTA.P1.desde) return 'P1';
  if (n >= ESCALA_ALERTA.P2.desde) return 'P2';
  return 'P3';
}

/* ── Categorías de reporte ──────────────────────────────────────────────────
   Las siete familias del catálogo. La etiqueta legible la manda el backend en
   `category_label`; acá está sólo el color. */
export const COLOR_CATEGORIA = {
  priorizacion:            'var(--cat-priorizacion)',
  aml_transaccional:       'var(--cat-aml-trx)',
  patrones_aml:            'var(--cat-patrones)',
  comportamiento_clientes: 'var(--cat-comportamiento)',
  kyc_jumio:               'var(--cat-kyc)',
  crypto_bridge:           'var(--cat-crypto)',
  institucional:           'var(--cat-institucional)',
};
export const COLOR_CATEGORIA_POR_DEFECTO = 'var(--texto-mute)';

/* ── El monto de una alerta ─────────────────────────────────────────────────
   Cada reporte guarda su fila cruda en `row_data`, y NO hay un campo de monto
   común: cada uno trae el suyo, con el nombre de lo que ese reporte mide.
   Medido sobre las alertas activas de producción, son cuatro campos distintos
   repartidos en seis reportes, y uno de los seis no trae monto en absoluto.

   Por eso el mapa es explícito y no una lista de candidatos que adivine: un
   "monto" que en una fila es el total girado en 7 días y en la siguiente el
   acumulado de depósitos chicos no es un monto, es una cifra sin significado.
   La columna muestra de qué campo salió.

   CUANDO SE AGREGUE UN REPORTE hay que agregarlo acá, o su columna de monto
   queda vacía. Vacía y no equivocada, que es la falla correcta. */
export const MONTO_POR_REPORTE = {
  payin_payout_accumulation:     { campo: 'total_payout_usd_7d',     etiqueta: 'Girado 7d' },
  small_payin_structuring:       { campo: 'small_payin_total_usd_7d', etiqueta: 'Depósitos chicos 7d' },
  structuring_detection:         { campo: 'total_usd_7d',            etiqueta: 'Total 7d' },
  beneficiary_dispersion:        { campo: 'total_usd_7d',            etiqueta: 'Total 7d' },
  top_customers_by_range_country:{ campo: 'total_amount_usd',        etiqueta: 'Total' },
  // `operation-alert_-_psp_sum_30` no trae ningún campo de monto: es una
  // alerta de estado de compliance, no transaccional.
};

/* ── Estados del caso ───────────────────────────────────────────────────────
   Los valores internos vienen del backend; acá su nombre en español y su
   color. Un estado que el backend agregue y acá no esté se muestra crudo en
   vez de vacío: mejor un valor raro que una celda en blanco que parece un bug.

   Los colores son las variantes `-texto`, no las de superficie: estos
   estados se dibujan SIEMPRE como letra. Con `--nivel-alto` a secas, "En
   investigación" daba 3,0:1 y no llegaba al mínimo — se vio recién al mirar
   la bandeja con datos reales, porque en el diseño ese estado no aparecía. */
export const ESTADOS_CASO = {
  open:         { etiqueta: 'Abierto',          color: 'var(--g66-azul-texto)' },
  in_progress:  { etiqueta: 'En investigación', color: 'var(--nivel-alto-texto)' },
  under_review: { etiqueta: 'Bajo revisión',    color: 'var(--violeta-texto)' },
  closed:       { etiqueta: 'Cerrado',          color: 'var(--texto-mute)' },
  archived:     { etiqueta: 'Archivado',        color: 'var(--texto-mute)' },
};

/* ── El semáforo del plazo ──────────────────────────────────────────────────
   Los estados los decide `lambda/sla_casos.py` y vienen en `sla_estado`; la
   etiqueta legible viene en `sla_etiqueta`. Acá está sólo el color y el
   orden de urgencia — la etiqueta de abajo es un respaldo por si el backend
   mandara un estado sin texto.

   `por_contactar` y `por_recontactar` son el mismo amarillo a propósito:
   los dos significan "hay algo pendiente con este cliente". Lo que cambia es
   el texto, y ese lo pone el backend. */
export const ESTADOS_SLA = {
  vencido:         { etiqueta: 'Vencido',      orden: 1, color: 'var(--nivel-critico-texto)', fondo: 'var(--nivel-critico-tenue)' },
  por_contactar:   { etiqueta: 'Sin contactar', orden: 2, color: 'var(--nivel-alto-texto)',   fondo: 'var(--nivel-alto-tenue)' },
  por_recontactar: { etiqueta: 'Recontactar',  orden: 3, color: 'var(--nivel-alto-texto)',    fondo: 'var(--nivel-alto-tenue)' },
  en_plazo:        { etiqueta: 'En plazo',     orden: 4, color: 'var(--nivel-bajo-texto)',    fondo: 'var(--nivel-bajo-tenue)' },
  cerrado:         { etiqueta: 'Cerrado',      orden: 5, color: 'var(--texto-mute)',          fondo: 'var(--superficie-3)' },
};

/** El estado sin reloj: el caso no nació de una alerta transaccional. Se
 *  distingue del resto porque no es un punto del plazo, es la ausencia de
 *  plazo — y pintarlo de verde diría que va bien de tiempo. */
export const SLA_SIN_RELOJ = { etiqueta: 'Sin plazo', orden: 6 };

/* ── El plazo de los casos de alerta ────────────────────────────────────────
   Estos números son de compliance, no de diseño: los define `sla_casos.py` y
   los devuelve `GET /cases` en `sla_config`. NO se escriben acá — estas
   constantes son sólo el respaldo para el primer render, antes de que llegue
   la respuesta. Si las dos definiciones se separan, la pantalla muestra un
   plazo que el sistema no aplica. */
export const PLAZO_RESPALDO = { horas_recontacto: 36, horas_cierre: 72 };

/* ── Lo que se le pide al backend ───────────────────────────────────────────
   Inventario explícito de lo que NO se hardcodea, con el endpoint del que
   sale. Sirve de contrato y de recordatorio. */
export const SE_PIDE_AL_BACKEND = {
  reportes:    'GET /reports',          // 33 hoy, con category y category_label
  casos:       'GET /cases',            // incluye sla_* y sla_config
  alertas:     'GET /alerts',           // incluye tiene_caso / caso_estado
  usuarios:    'GET /crm/users',        // incluye equipo
  // PENDIENTE: la matriz F1–F10 con sus pesos no tiene endpoint. Hoy vive
  // sólo en `lambda/aml_individual.py` (FLAG_WEIGHTS / FLAG_LABELS). La
  // pantalla "Flags y pesos" del diseño la necesita, y hardcodearla acá la
  // condena a desincronizarse. Tarea de Fase 0 del backend: exponer
  // `GET /flags` leyendo esas dos constantes.
  flags:       'GET /flags  ← NO EXISTE TODAVÍA',
};

/* ── Las 20 pantallas del diseño ────────────────────────────────────────────
   El `modulo` es la llave de permisos: la misma que usa `verModulo()` en el
   front actual, para que un perfil de sólo lectura signifique lo mismo en los
   dos. `nuevo: true` marca lo que no existe hoy en el sistema.

   `enMenu: false` son las pantallas de DETALLE: existen como ruta y tienen su
   permiso, pero no van en el menú porque sin un id no tienen nada que
   mostrar. Un ítem de menú que siempre lleva a un error no es un atajo, es
   una trampa. */
export const PANTALLAS = [
  { grupo: 'Operación', id: 'dashboard',     titulo: 'Bandeja de Alertas',  modulo: 'alertados' },
  { grupo: 'Operación', id: 'alert',         titulo: 'Triage de alerta',    modulo: 'alertados', nuevo: true, enMenu: false },
  { grupo: 'Operación', id: 'cases',         titulo: 'Casos',               modulo: 'casos' },
  { grupo: 'Operación', id: 'kanban',        titulo: 'Kanban',              modulo: 'casos' },
  { grupo: 'Operación', id: 'caso',          titulo: 'Detalle del caso',    modulo: 'casos', enMenu: false },
  { grupo: 'Operación', id: 'ficha',         titulo: 'Ficha del cliente',   modulo: 'casos' },
  { grupo: 'Operación', id: 'relevo',        titulo: 'Relevo · partners',   modulo: 'relevo' },

  { grupo: 'Análisis',  id: 'informe',       titulo: 'Informe de gestión',  modulo: 'casos' },
  { grupo: 'Análisis',  id: 'reports',       titulo: 'Reportes AML',        modulo: 'alertas' },
  { grupo: 'Análisis',  id: 'individual',    titulo: 'Análisis Individual', modulo: 'aml_individual' },
  { grupo: 'Análisis',  id: 'institucional', titulo: 'Institucional',       modulo: 'institucional' },
  { grupo: 'Análisis',  id: 'history',       titulo: 'Historial',           modulo: 'historial' },
  { grupo: 'Análisis',  id: 'whitelist',     titulo: 'Lista Blanca',        modulo: 'whitelist' },
  { grupo: 'Análisis',  id: 'flags',         titulo: 'Flags y pesos',       modulo: 'aml_individual', nuevo: true },
  { grupo: 'Análisis',  id: 'embargos',      titulo: 'Embargos',            modulo: 'embargos' },
  { grupo: 'Análisis',  id: 'ros',           titulo: 'ROS / UAF',           modulo: 'casos', nuevo: true },

  { grupo: 'Administración', id: 'admin_users',   titulo: 'Usuarios y permisos', modulo: 'admin' },
  { grupo: 'Administración', id: 'admin_auto',    titulo: 'Automatización',      modulo: 'admin' },
  { grupo: 'Administración', id: 'admin_cluster', titulo: 'Cluster',             modulo: 'admin' },
  { grupo: 'Administración', id: 'audit',         titulo: 'Auditoría',           modulo: 'admin' },
  { grupo: 'Administración', id: 'salud',         titulo: 'Salud del módulo',    modulo: 'admin', nuevo: true },
];

export const GRUPOS = ['Operación', 'Análisis', 'Administración'];
