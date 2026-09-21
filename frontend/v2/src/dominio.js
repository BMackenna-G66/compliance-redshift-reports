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

/* ── Niveles de riesgo ──────────────────────────────────────────────────────
   Los CORTES (≥10, 6-9, 3-5, <3) los decide el backend al calcular el score.
   Acá está sólo cómo se pintan, y el rango se muestra como referencia para el
   analista — si el backend cambia los cortes, esto se ajusta a mano y hay un
   test que lo compara. */
export const NIVELES = {
  CRITICO: { etiqueta: 'Crítico', desde: 10, color: 'var(--nivel-critico)', fondo: 'var(--nivel-critico-tenue)', claro: 'var(--nivel-critico-claro)' },
  ALTO:    { etiqueta: 'Alto',    desde: 6,  color: 'var(--nivel-alto)',    fondo: 'var(--nivel-alto-tenue)',    claro: 'var(--nivel-alto-claro)' },
  MEDIO:   { etiqueta: 'Medio',   desde: 3,  color: 'var(--nivel-medio)',   fondo: 'var(--nivel-medio-tenue)',   claro: 'var(--nivel-medio-claro)' },
  BAJO:    { etiqueta: 'Bajo',    desde: 0,  color: 'var(--nivel-bajo)',    fondo: 'var(--nivel-bajo-tenue)',    claro: 'var(--nivel-bajo-claro)' },
};

/** El nivel de un score. Un score ausente no es "bajo": es desconocido, y
 *  pintarlo de verde tranquiliza sobre algo que no se midió. */
export function nivelDe(score) {
  if (score === null || score === undefined || score === '') return null;
  const n = Number(score);
  if (Number.isNaN(n)) return null;
  if (n >= NIVELES.CRITICO.desde) return 'CRITICO';
  if (n >= NIVELES.ALTO.desde)    return 'ALTO';
  if (n >= NIVELES.MEDIO.desde)   return 'MEDIO';
  return 'BAJO';
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

/* ── Estados del caso ───────────────────────────────────────────────────────
   Los valores internos vienen del backend; acá su nombre en español y su
   color. Un estado que el backend agregue y acá no esté se muestra crudo en
   vez de vacío: mejor un valor raro que una celda en blanco que parece un bug. */
export const ESTADOS_CASO = {
  open:         { etiqueta: 'Abierto',          color: 'var(--g66-azul)' },
  in_progress:  { etiqueta: 'En investigación', color: 'var(--nivel-alto)' },
  under_review: { etiqueta: 'Bajo revisión',    color: 'var(--violeta)' },
  closed:       { etiqueta: 'Cerrado',          color: 'var(--texto-mute)' },
  archived:     { etiqueta: 'Archivado',        color: 'var(--texto-mute)' },
};

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
   dos. `nuevo: true` marca lo que no existe hoy en el sistema. */
export const PANTALLAS = [
  { grupo: 'Operación', id: 'dashboard',     titulo: 'Bandeja de Alertas',  modulo: 'alertados' },
  { grupo: 'Operación', id: 'alert',         titulo: 'Triage de alerta',    modulo: 'alertados', nuevo: true },
  { grupo: 'Operación', id: 'cases',         titulo: 'Casos',               modulo: 'casos' },
  { grupo: 'Operación', id: 'kanban',        titulo: 'Kanban',              modulo: 'casos' },
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
