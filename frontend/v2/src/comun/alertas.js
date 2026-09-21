/* ============================================================================
   Alertas — la lógica
   ----------------------------------------------------------------------------
   Preparar una alerta cruda de la API para mostrarla, y calcular los
   indicadores del tablero. Sin React, para poder testearlo.

   TODO LO QUE HAY ACÁ SALE DE MIRAR LAS 122 ALERTAS ACTIVAS DE PRODUCCIÓN, no
   del prototipo. El diseño dibuja columnas de monto en dólares, país destino
   y flags F1–F10 para cada alerta; de esas tres, el monto existe con otro
   nombre en cada reporte, y el país y los flags no existen en absoluto.
   Inventarlas habría quedado lindo y vacío.
   ========================================================================= */

import {
  ESCALA_ALERTA, ESCALA_ALERTA_MAXIMO, ESTADOS_CASO, MONTO_POR_REPORTE,
  prioridadDeAlerta,
} from '../dominio.js';

/**
 * La fila cruda del reporte que originó la alerta.
 *
 * Llega como texto JSON, pero no siempre: según por dónde se creó la alerta
 * puede venir ya como objeto. Y puede venir rota. Las tres se contemplan —
 * una alerta con `row_data` ilegible igual tiene que aparecer en la lista,
 * porque esconderla sería esconder trabajo pendiente.
 */
export function filaDelReporte(alerta) {
  const v = alerta?.row_data;
  if (!v) return {};
  if (typeof v === 'object') return v;
  if (typeof v !== 'string') return {};
  try {
    const d = JSON.parse(v);
    return d && typeof d === 'object' ? d : {};
  } catch {
    return {};
  }
}

/** El puntaje 0–100 de la alerta, o `null` si no lo trae. */
export function scoreDe(alerta) {
  const s = filaDelReporte(alerta).risk_score;
  if (s === null || s === undefined || s === '') return null;
  const n = Number(s);
  return Number.isNaN(n) ? null : n;
}

/**
 * La prioridad P1/P2/P3.
 *
 * Se recalcula del puntaje en vez de leer `row_data.prioridad` para que un
 * cambio de los cortes en el backend no deje la pantalla mostrando la
 * clasificación vieja de alertas viejas. Si no hay puntaje pero sí una
 * prioridad guardada, se usa esa — es mejor que nada.
 */
export function prioridadDe(alerta) {
  const calculada = prioridadDeAlerta(scoreDe(alerta));
  if (calculada) return calculada;
  const guardada = filaDelReporte(alerta).prioridad;
  return ESCALA_ALERTA[guardada] ? guardada : null;
}

/** El monto de la alerta, con el nombre de lo que mide. `null` si el reporte
 *  no tiene uno definido. */
export function montoDe(alerta) {
  const def = MONTO_POR_REPORTE[alerta?.report_name];
  if (!def) return null;
  const crudo = filaDelReporte(alerta)[def.campo];
  if (crudo === null || crudo === undefined || crudo === '') return null;
  const n = Number(crudo);
  if (Number.isNaN(n)) return null;
  return { valor: n, etiqueta: def.etiqueta, campo: def.campo };
}

/** El correo del cliente, que sólo algunos reportes traen. */
export function correoDe(alerta) {
  const f = filaDelReporte(alerta);
  return f.customer_email || f.email || '';
}

/* ── Formato ────────────────────────────────────────────────────────────── */

export function montoTexto(monto) {
  if (!monto) return '—';
  return 'USD ' + monto.valor.toLocaleString('es-CL', { maximumFractionDigits: 0 });
}

/** "hace 3 h", "hace 2 d". Para una bandeja, cuánto lleva esperando importa
 *  más que la fecha exacta — la fecha completa va en el título del elemento. */
export function hace(fechaTexto, ahora = new Date()) {
  const t = fecha(fechaTexto);
  if (!t) return '—';
  const min = Math.floor((ahora - t) / 60000);
  if (min < 0) return 'recién';           // reloj del servidor adelantado
  if (min < 1) return 'recién';
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return `hace ${d} d`;
}

/** El `created_at` viene como "2026-09-14 18:21:04" en UTC, sin zona. Sin la
 *  T y la Z, Safari lo rechaza y Chrome lo lee como hora local — dos horas
 *  distintas según el navegador. */
export function fecha(texto) {
  if (!texto || typeof texto !== 'string') return null;
  const iso = texto.trim().replace(' ', 'T');
  const t = new Date(/[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z');
  return Number.isNaN(t.getTime()) ? null : t;
}

/* ── Preparar para la tabla ─────────────────────────────────────────────── */

/** Aplana una alerta a los campos que la tabla ordena y busca. */
export function prepararAlerta(alerta, catalogo = {}) {
  const monto = montoDe(alerta);
  const prioridad = prioridadDe(alerta);
  return {
    ...alerta,
    _score: scoreDe(alerta),
    _prioridad: prioridad,
    // Para ordenar por prioridad hace falta un número; el texto "P1" ordena
    // antes que "P2" por casualidad, y con `null` esa casualidad se rompe.
    _prioridadOrden: prioridad ? { P1: 1, P2: 2, P3: 3 }[prioridad] : null,
    _monto: monto ? monto.valor : null,
    _montoEtiqueta: monto ? monto.etiqueta : '',
    _montoCampo: monto ? monto.campo : '',
    _correo: correoDe(alerta),
    _reporte: catalogo[alerta?.report_name] || nombreLegible(alerta?.report_name),
    _asignado: alerta?.assigned_to || '',
    _caso: alerta?.caso_estado_es || 'Sin caso',
  };
}

/** Un nombre de reporte que el catálogo no conoce, al menos legible. */
export function nombreLegible(nombre) {
  if (!nombre) return '—';
  return String(nombre)
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
}

/* ── Los indicadores del tablero ────────────────────────────────────────── */

/**
 * Lo que va arriba del Command desk.
 *
 * Elegidos por lo que deciden, no por lo que suman: "sin caso" es trabajo que
 * nadie empezó y "sin asignar" es trabajo que nadie tomó. Un total de alertas
 * no le dice a nadie qué hacer a continuación.
 */
export function indicadores(alertas) {
  const a = alertas || [];
  const prioridades = a.map(prioridadDe);
  return {
    total: a.length,
    p1: prioridades.filter((p) => p === 'P1').length,
    p2: prioridades.filter((p) => p === 'P2').length,
    p3: prioridades.filter((p) => p === 'P3').length,
    sinPuntaje: prioridades.filter((p) => p === null).length,
    sinCaso: a.filter((x) => !x.tiene_caso).length,
    conCasoAbierto: a.filter((x) => x.tiene_caso && esCasoAbierto(x.caso_estado)).length,
    sinAsignar: a.filter((x) => !x.assigned_to).length,
    reportes: new Set(a.map((x) => x.report_name).filter(Boolean)).size,
  };
}

/** Cerrado y archivado no son "abierto"; cualquier otro estado sí lo es. Un
 *  estado nuevo del backend cuenta como abierto: preferimos que aparezca
 *  como pendiente y alguien pregunte, a que desaparezca en silencio. */
export function esCasoAbierto(estado) {
  return estado !== 'closed' && estado !== 'archived' && Boolean(estado);
}

/** Cuenta por reporte, de mayor a menor. */
export function porReporte(alertas, catalogo = {}) {
  const cuenta = new Map();
  for (const a of alertas || []) {
    const k = a.report_name || '';
    cuenta.set(k, (cuenta.get(k) || 0) + 1);
  }
  return [...cuenta.entries()]
    .map(([clave, n]) => ({ clave, n, nombre: catalogo[clave] || nombreLegible(clave) }))
    .sort((x, y) => y.n - x.n);
}

/* ── Filtros de la bandeja ──────────────────────────────────────────────── */

export const FILTROS = {
  todas: { etiqueta: 'Todas', prueba: () => true },
  p1: { etiqueta: 'P1', prueba: (a) => prioridadDe(a) === 'P1' },
  sin_caso: { etiqueta: 'Sin caso', prueba: (a) => !a.tiene_caso },
  sin_asignar: { etiqueta: 'Sin asignar', prueba: (a) => !a.assigned_to },
  sin_puntaje: { etiqueta: 'Sin puntaje', prueba: (a) => prioridadDe(a) === null },
};

export function aplicarFiltro(alertas, clave) {
  const f = FILTROS[clave];
  if (!f) return alertas || [];
  return (alertas || []).filter(f.prueba);
}

export { ESCALA_ALERTA, ESCALA_ALERTA_MAXIMO, ESTADOS_CASO };
