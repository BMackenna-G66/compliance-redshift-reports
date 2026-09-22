/* ============================================================================
   Repartir alertas entre analistas
   ----------------------------------------------------------------------------
   El reparto lo hace el backend; lo que vive acá es el CÁLCULO DE LA PREVIA,
   para poder mostrar a quién le toca cuánto antes de apretar.

   Que se vea antes importa: repartir cincuenta alertas entre cuatro personas
   es difícil de deshacer —hay que reasignarlas una por una— y el desbalance
   sólo se nota mirando los números. Con la previa, «a fulano le tocan treinta
   y a mengano dos» se ve en un renglón.
   ========================================================================= */

/**
 * Cómo queda el reparto de `cuantas` alertas entre `personas`.
 *
 * Es el reparto parejo con el resto distribuido de a uno: los primeros de la
 * lista reciben una de más. Se calcula acá para MOSTRARLO, no para decidirlo
 * —eso lo hace el backend— así que si algún día los dos difieren, manda el
 * backend y esta previa deja de ser exacta. Mientras tanto, es la única forma
 * de ver el desbalance antes de provocarlo.
 */
export function repartoEquitativo(cuantas, personas) {
  const gente = (personas || []).filter(Boolean);
  if (gente.length === 0 || !cuantas) return [];
  const base = Math.floor(cuantas / gente.length);
  const resto = cuantas % gente.length;
  return gente.map((quien, i) => ({ quien, cuantas: base + (i < resto ? 1 : 0) }));
}

/** El query de la exportación a Excel, con los filtros que están puestos. */
export function queryDeExportacion({ vista, filtro, caso, prioridad, asignado } = {}) {
  const qs = new URLSearchParams();
  qs.set('status', vista === 'revisadas' ? 'reviewed' : 'active');
  if (caso) qs.set('caso', caso);
  if (prioridad) qs.set('priority', prioridad);
  // `__sin_asignar__` es un filtro de la pantalla, no un valor que el backend
  // entienda: mandarlo devolvería cero filas sin decir por qué.
  if (asignado && asignado !== '__sin_asignar__') qs.set('assigned_to', asignado);
  if (filtro && filtro !== 'todas') qs.set('filtro', filtro);
  return qs.toString();
}
