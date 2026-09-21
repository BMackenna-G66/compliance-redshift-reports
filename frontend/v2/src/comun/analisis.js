/* ============================================================================
   Análisis — la lógica compartida de la Fase 4
   ----------------------------------------------------------------------------
   Corridas (el historial), lista blanca y alertas institucionales. Tres cosas
   distintas que comparten una idea: todas tienen un estado que el backend
   informa y una lectura que el front tiene que hacer sin inventar nada.
   ========================================================================= */

import { fecha, hace } from './alertas.js';

export { fecha, hace };

/* ── Corridas ───────────────────────────────────────────────────────────── */

/* Los estados que devuelve el runner. `RESUMING` es el cluster de Redshift
   despertando: está pausado de 18:30 a 04:00 y la primera consulta del día
   lo levanta, lo que puede tardar minutos. */
export const ESTADOS_CORRIDA = {
  DONE:     { etiqueta: 'Lista',      color: 'var(--nivel-bajo-texto)',    fondo: 'var(--nivel-bajo-tenue)' },
  RUNNING:  { etiqueta: 'Corriendo',  color: 'var(--g66-azul-texto)',      fondo: 'var(--azul-tenue)' },
  RESUMING: { etiqueta: 'Despertando el cluster', color: 'var(--nivel-alto-texto)', fondo: 'var(--nivel-alto-tenue)' },
  QUEUED:   { etiqueta: 'En cola',    color: 'var(--texto-mute)',          fondo: 'var(--superficie-3)' },
  ERROR:    { etiqueta: 'Falló',      color: 'var(--estado-error-texto)',  fondo: 'var(--estado-error-fondo)' },
  FAILED:   { etiqueta: 'Falló',      color: 'var(--estado-error-texto)',  fondo: 'var(--estado-error-fondo)' },
};

/** Si la corrida sigue en curso y hay que volver a preguntar. */
export function enCurso(estado) {
  return !['DONE', 'ERROR', 'FAILED'].includes(String(estado || '').toUpperCase());
}

/** Cuánto tardó, en segundos. `null` si no terminó o si falta alguna fecha. */
export function duracion(corrida) {
  const a = fecha(corrida?.started_at);
  const b = fecha(corrida?.completed_at);
  if (!a || !b) return null;
  const s = (b - a) / 1000;
  return s < 0 ? null : s;   // relojes cruzados: mejor no decir nada
}

export function duracionTexto(seg) {
  if (seg === null || seg === undefined) return '—';
  if (seg < 60) return `${Math.round(seg)} s`;
  const m = Math.floor(seg / 60);
  const r = Math.round(seg % 60);
  return r ? `${m} min ${r} s` : `${m} min`;
}

/**
 * Los parámetros de la corrida, legibles.
 *
 * Llegan como texto JSON y pueden ser enormes: una corrida del análisis
 * individual trae 891 ids de cliente en un solo campo. Mostrarlos crudos
 * revienta la fila, así que las listas largas se resumen — pero se dice
 * cuántas son, que es el dato útil.
 */
export function parametros(corrida) {
  const crudo = corrida?.params;
  if (!crudo) return [];
  let d = crudo;
  if (typeof crudo === 'string') {
    try { d = JSON.parse(crudo); } catch { return [{ clave: 'params', valor: crudo }]; }
  }
  if (!d || typeof d !== 'object') return [];
  return Object.entries(d).map(([clave, v]) => ({
    clave,
    valor: Array.isArray(v)
      ? (v.length > 4 ? `${v.length} valores` : v.join(', '))
      : String(v ?? ''),
  }));
}

/* ── Lista blanca ───────────────────────────────────────────────────────── */

/**
 * Si una entrada de la lista blanca sigue vigente.
 *
 * ESTO IMPORTA MÁS DE LO QUE PARECE: una entrada en lista blanca hace que el
 * cliente deje de generar alertas. Mostrar una vencida como si estuviera
 * activa haría creer que a ese cliente no se lo está mirando cuando sí, y al
 * revés — mostrar una activa como vencida haría que alguien la renueve sin
 * necesidad. Por eso se compara contra la hora real y no se asume nada.
 *
 * Sin `expires_at` la entrada es permanente. Eso es una decisión del backend,
 * no un dato faltante.
 */
export function vigenciaDe(entrada, ahora = new Date()) {
  const texto = entrada?.expires_at;
  if (!texto) return { estado: 'permanente', etiqueta: 'Permanente', vence: null, dias: null };
  const vence = fecha(texto);
  if (!vence) return { estado: 'desconocida', etiqueta: 'Fecha ilegible', vence: null, dias: null };
  const dias = (vence - ahora) / 86400000;
  if (dias < 0) {
    return { estado: 'vencida', etiqueta: 'Vencida', vence, dias };
  }
  // Menos de una semana: conviene avisar antes de que el cliente vuelva a
  // aparecer en la bandeja de golpe.
  if (dias <= 7) return { estado: 'por_vencer', etiqueta: 'Por vencer', vence, dias };
  return { estado: 'vigente', etiqueta: 'Vigente', vence, dias };
}

export const COLOR_VIGENCIA = {
  vigente:     { color: 'var(--nivel-bajo-texto)',   fondo: 'var(--nivel-bajo-tenue)' },
  por_vencer:  { color: 'var(--nivel-alto-texto)',   fondo: 'var(--nivel-alto-tenue)' },
  vencida:     { color: 'var(--estado-error-texto)', fondo: 'var(--estado-error-fondo)' },
  permanente:  { color: 'var(--g66-azul-texto)',     fondo: 'var(--azul-tenue)' },
  desconocida: { color: 'var(--texto-mute)',         fondo: 'var(--superficie-3)' },
};

/** Cuenta de la lista blanca por vigencia. */
export function resumenListaBlanca(entradas, ahora = new Date()) {
  const r = { total: 0, vigente: 0, por_vencer: 0, vencida: 0, permanente: 0, desconocida: 0 };
  for (const e of entradas || []) {
    r.total += 1;
    r[vigenciaDe(e, ahora).estado] += 1;
  }
  return r;
}

/* ── Institucional ──────────────────────────────────────────────────────── */

/* Los niveles que trae `risk_level` de las empresas. Vienen en inglés del
   backend; acá su nombre y su color. Uno desconocido se muestra crudo. */
export const RIESGO_EMPRESA = {
  High:   { etiqueta: 'Alto',  orden: 1, color: 'var(--nivel-critico-texto)', fondo: 'var(--nivel-critico-tenue)' },
  Medium: { etiqueta: 'Medio', orden: 2, color: 'var(--nivel-alto-texto)',    fondo: 'var(--nivel-alto-tenue)' },
  Low:    { etiqueta: 'Bajo',  orden: 3, color: 'var(--nivel-bajo-texto)',    fondo: 'var(--nivel-bajo-tenue)' },
};

export function riesgoDe(empresa) {
  return RIESGO_EMPRESA[empresa?.risk_level] || null;
}

/**
 * Cuánto se pasó del umbral una alerta institucional, en veces.
 *
 * Una alerta que se pasó por un 3% y otra que se pasó 45 veces no son lo
 * mismo, y con el valor y el umbral sueltos en dos columnas hay que hacer la
 * división mentalmente para cada fila.
 */
export function excesoDe(alerta) {
  const v = Number(alerta?.valor);
  const u = Number(alerta?.umbral);
  if (Number.isNaN(v) || Number.isNaN(u) || u <= 0) return null;
  return v / u;
}

export function excesoTexto(veces) {
  if (veces === null || veces === undefined) return '—';
  if (veces >= 10) return `${Math.round(veces)}×`;
  return `${veces.toFixed(1)}×`;
}

/* ── Análisis individual ────────────────────────────────────────────────── */

/**
 * Los ids de cliente que alguien pegó, sin importar cómo los separe.
 *
 * Se aceptan comas, punto y coma, espacios y saltos de línea porque los ids
 * llegan pegados de un Excel, de un mensaje de Slack o de una consulta: pedir
 * un formato exacto sólo agrega un paso manual que se hace mal.
 */
export function leerIds(texto) {
  return String(texto || '')
    .split(/[\s,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
}
