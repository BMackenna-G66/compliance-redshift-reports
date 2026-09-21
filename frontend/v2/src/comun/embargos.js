/* ============================================================================
   Embargos — la lógica
   ----------------------------------------------------------------------------
   Llega un oficio de un juzgado con una lista de personas; hay que decir
   cuáles son clientes de Global66 y responderle al juzgado.

   El circuito es: subir el archivo → previsualizar lo que se leyó → ejecutar
   → descargar el resultado. Cada corrida queda con su historial.
   ========================================================================= */

import { fecha, hace } from './alertas.js';

export { fecha, hace };

/* Las etapas de una corrida, en orden. El backend las llama igual en `estado`
   y en `etapa`; se lee `estado`, que es el que trae el historial. */
export const ETAPAS_EMBARGO = {
  recibido:     { etiqueta: 'Recibido',     orden: 1, color: 'var(--texto-mute)' },
  leyendo:      { etiqueta: 'Leyendo',      orden: 2, color: 'var(--g66-azul-texto)' },
  previsualizado: { etiqueta: 'Previsualizado', orden: 3, color: 'var(--g66-azul-texto)' },
  procesando:   { etiqueta: 'Procesando',   orden: 4, color: 'var(--g66-azul-texto)' },
  listo:        { etiqueta: 'Listo',        orden: 5, color: 'var(--nivel-bajo-texto)' },
  error:        { etiqueta: 'Falló',        orden: 6, color: 'var(--estado-error-texto)' },
};

export function etapaDe(corrida) {
  return ETAPAS_EMBARGO[String(corrida?.estado || '').toLowerCase()] || null;
}

/** Si la corrida sigue moviéndose y hay que volver a preguntar. */
export function enCurso(corrida) {
  const e = String(corrida?.estado || '').toLowerCase();
  return Boolean(e) && e !== 'listo' && e !== 'error';
}

/* Los formatos que el backend acepta. El PDF entró después del Excel: ~90%
   de los oficios llegan en Excel, pero los que llegan escaneados son
   justamente los que más trabajo manual daban. */
export const FORMATOS = ['.xlsx', '.xls', '.csv', '.pdf'];

export function formatoAceptado(nombre) {
  const n = String(nombre || '').toLowerCase();
  return FORMATOS.some((e) => n.endsWith(e));
}

/**
 * Cuántas de las personas del oficio resultaron clientes.
 *
 * Es el número que responde el oficio: el juzgado pregunta si estas personas
 * tienen cuenta. Se devuelve también el total para que la pantalla muestre
 * "1 de 6" y no un 1 suelto, que no dice nada.
 */
export function resumenDe(corrida) {
  const c = corrida?.conteos || corrida || {};
  const num = (v) => {
    const n = Number(v);
    return Number.isNaN(n) ? null : n;
  };
  const personas = num(c.personas);
  const clientes = num(c.clientes);
  return {
    personas,
    clientes,
    noClientes: num(c.no_clientes),
    descartados: num(c.descartados),
    // `null` y no 0 cuando no se puede calcular: un 0% diría que no hubo
    // ninguna coincidencia, que es una afirmación distinta de "no se sabe".
    porcentaje: personas && clientes !== null ? (clientes / personas) * 100 : null,
  };
}

/**
 * Por qué se descartó gente.
 *
 * Un descartado no es un "no cliente": es una fila que no se pudo leer —sin
 * documento, con un formato imposible—. Contarlos juntos haría creer que se
 * revisó a alguien a quien en realidad nunca se buscó.
 */
export function hayDescartados(corrida) {
  return Number(resumenDe(corrida).descartados || 0) > 0;
}

/** Las descargas de una corrida, con un nombre legible por tipo. */
export function descargasDe(corrida) {
  return (corrida?.descargas || []).map((d) => ({
    ...d,
    etiqueta: d.nombre || NOMBRE_DESCARGA[d.tipo] || d.tipo || 'Archivo',
  }));
}

export const NOMBRE_DESCARGA = {
  excel: 'Excel de validación',
  oficio: 'Oficio de respuesta',
  zip: 'Todo en un ZIP',
};

/** El progreso 0–100, o `null` si el backend no lo informa. */
export function progresoDe(corrida) {
  const p = corrida?.progreso;
  if (p === null || p === undefined || p === '') return null;
  const n = Number(p);
  if (Number.isNaN(n)) return null;
  return Math.max(0, Math.min(100, n));
}

/** Cuánto tardó una corrida, en segundos. */
export function duracion(corrida) {
  const a = fecha(corrida?.creado_at);
  const b = fecha(corrida?.terminado_at);
  if (!a || !b) return null;
  const s = (b - a) / 1000;
  return s < 0 ? null : s;
}

/* ── Indicadores ────────────────────────────────────────────────────────── */

export function indicadores(corridas) {
  const c = corridas || [];
  const listas = c.filter((x) => String(x.estado).toLowerCase() === 'listo');
  const personas = listas.reduce((a, x) => a + (Number(x.personas) || 0), 0);
  const clientes = listas.reduce((a, x) => a + (Number(x.clientes) || 0), 0);
  return {
    total: c.length,
    enCurso: c.filter(enCurso).length,
    fallidas: c.filter((x) => String(x.estado).toLowerCase() === 'error' || x.error).length,
    personas,
    clientes,
  };
}
