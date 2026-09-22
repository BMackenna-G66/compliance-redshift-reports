/* ============================================================================
   Los analíticos del tablero
   ----------------------------------------------------------------------------
   Tres consultas pesadas contra Redshift —el resumen de gestión, el analítico
   de plazos y las estadísticas transaccionales— que funcionan todas igual y
   NO como el resto de la aplicación:

     1. `GET /analytics/summary` no devuelve datos: devuelve `{stmt_ids: [...]}`
     2. `GET /analytics/result?stmt_ids=a,b,c` devuelve lo que haya, con
        `all_done` diciendo si ya terminaron todas

   Es el Data API de Redshift: las consultas se disparan y se cosechan después.
   Sin eso, tres consultas de varios segundos no entran en los treinta que da
   API Gateway.

   LO QUE SE PUEDE MOSTRAR A MEDIO CAMINO, SE MUESTRA. `all_done: false` no
   significa vacío: significa que algunas series ya llegaron y otras no. Dejar
   la pantalla en blanco hasta que estén todas hace esperar de más por la
   consulta más lenta.
   ========================================================================= */

/* Cada cuánto se cosecha. Dos segundos: las consultas tardan entre tres y
   veinte, y preguntar más seguido sólo suma invocaciones. */
export const ESPERA_COSECHA = 2000;

/* El techo. El cluster puede estar pausado y tardar minutos en despertar,
   pero si a los dos minutos no terminó, algo pasa y hay que decirlo en vez de
   dejar la pantalla girando. */
export const VUELTAS_COSECHA = 60;

/** Las tres consultas, con su par disparo/cosecha. */
export const ANALITICOS = {
  gestion: {
    titulo: 'Gestión',
    disparo: '/analytics/summary',
    cosecha: '/analytics/result',
    pie: 'casos y alertas: cómo se reparten y cómo evolucionan',
  },
  plazos: {
    titulo: 'Plazos',
    disparo: '/analytics/sla',
    cosecha: '/analytics/sla/result',
    pie: 'cuánto se tarda en cerrar y cuánto está vencido',
  },
  transaccional: {
    titulo: 'Transaccional',
    disparo: '/dashboard/stats',
    cosecha: '/dashboard/stats/result',
    pie: 'volumen diario, operaciones grandes y países',
  },
};

/**
 * Dispara un analítico y cosecha su resultado hasta que termine.
 *
 * `alAvanzar` recibe cada resultado parcial: es lo que permite pintar las
 * series que ya llegaron mientras las otras siguen corriendo.
 */
export async function traerAnalitico(pedir, clave, {
  alAvanzar = () => {},
  cancelado = () => false,
  espera = ESPERA_COSECHA,
  vueltas = VUELTAS_COSECHA,
  dormir = (ms) => new Promise((r) => setTimeout(r, ms)),
} = {}) {
  const cfg = ANALITICOS[clave];
  if (!cfg) throw new Error(`analítico desconocido: ${clave}`);

  const disparo = await pedir(cfg.disparo);
  const ids = disparo?.stmt_ids || [];
  if (ids.length === 0) {
    // Sin identificadores no hay nada que cosechar. Puede pasar si el cluster
    // está apagado: el backend no dispara y devuelve la lista vacía.
    return { datos: {}, completo: false, motivo: 'El backend no disparó ninguna consulta. '
                                              + 'Suele ser el cluster de Redshift apagado.' };
  }

  const ruta = `${cfg.cosecha}?stmt_ids=${encodeURIComponent(ids.join(','))}`;
  let ultimo = {};
  for (let i = 0; i < vueltas; i += 1) {
    if (cancelado()) return { datos: ultimo, completo: false, motivo: 'Cancelado.' };
    await dormir(espera);
    if (cancelado()) return { datos: ultimo, completo: false, motivo: 'Cancelado.' };
    try {
      ultimo = await pedir(ruta);
    } catch {
      // Un tropiezo de red no cancela la cosecha: las consultas siguen
      // corriendo en Redshift y la próxima vuelta puede traerlas.
      continue;
    }
    alAvanzar(ultimo);
    if (ultimo?.all_done) return { datos: ultimo, completo: true, motivo: '' };
  }
  return {
    datos: ultimo,
    completo: false,
    motivo: 'Las consultas siguen corriendo después de dos minutos. Lo que se ve es '
          + 'parcial: refrescá en un rato.',
  };
}

/* ── Leer las series ─────────────────────────────────────────────────────── */

/** Una serie del backend, siempre como lista. */
export function serie(datos, clave) {
  const v = datos?.[clave];
  return Array.isArray(v) ? v : [];
}

/**
 * Convierte una serie `[{clave, n}]` en puntos para un gráfico.
 *
 * Los ceros se conservan: una semana sin casos es un dato, y saltearla
 * dibujaría una línea que une dos semanas lejanas con una pendiente suave que
 * no existió.
 */
export function puntos(filas, campoEtiqueta, campoValor = 'n') {
  return filas.map((f) => ({
    etiqueta: String(f?.[campoEtiqueta] ?? ''),
    valor: Number(f?.[campoValor] ?? 0),
  }));
}

/** El total de una serie. */
export function total(filas, campo = 'n') {
  return filas.reduce((a, f) => a + (Number(f?.[campo]) || 0), 0);
}

/**
 * El resumen de vencidos, que el backend manda como una lista de una fila.
 *
 * Se devuelve siempre el objeto completo, con ceros cuando no vino: si
 * faltara una clave, la tarjeta mostraría «undefined» en vez de un número.
 */
export function vencidos(datos) {
  const f = serie(datos, 'overdue')[0] || {};
  const num = (k) => Number(f[k] || 0);
  return {
    abiertos: num('total_open'),
    critico: num('critical_overdue'),
    alto: num('high_overdue'),
    medio: num('medium_overdue'),
    bajo: num('low_overdue'),
    get vencidos() { return this.critico + this.alto + this.medio + this.bajo; },
  };
}

/**
 * El tiempo de cierre por prioridad, en días.
 *
 * El backend lo manda en horas. Se pasa a días porque el plazo de compliance
 * está escrito en días, y comparar «73,4 horas» contra «3 días» obliga a
 * hacer la cuenta mentalmente cada vez.
 */
export function cierrePorPrioridad(datos) {
  return serie(datos, 'avg_resolution').map((f) => ({
    prioridad: f.priority || '—',
    dias: Number(f.avg_hours || 0) / 24,
    cerrados: Number(f.total_closed || 0),
  }));
}
