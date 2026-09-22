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

/* ── Los resultados de una corrida ───────────────────────────────────────── */

/* Los tres montones en los que queda partida una lista de oficios: la gente
   que es cliente, la que no, y la que se descartó por no tener un documento
   utilizable. */
export const TIPOS_RESULTADO = [
  { clave: 'clientes', etiqueta: 'Clientes', conteo: 'clientes' },
  { clave: 'no_clientes', etiqueta: 'No clientes', conteo: 'no_clientes' },
  { clave: 'descartados', etiqueta: 'Descartados', conteo: 'descartados' },
];

export function tiposConConteo(corrida) {
  const c = corrida?.conteos || {};
  return TIPOS_RESULTADO.map((t) => ({ ...t, n: Number(c[t.conteo] || 0) }));
}

/**
 * Las coincidencias en las que el número de documento coincide pero el TIPO
 * no.
 *
 * Es el error más caro de este módulo. El cruce contra la base es por número
 * solamente, así que una cédula colombiana y un DNI argentino con el mismo
 * número dan «coincidencia». Responderle a un juzgado que esa persona es
 * cliente cuando es otra con el mismo número es un problema serio, y la única
 * señal que lo delata es esta bandera.
 */
export function dudosas(filas) {
  return (filas || []).filter((f) => f?.tipo_coincide === false);
}

export function avisoDeDudosas(filas, total) {
  const n = dudosas(filas).length;
  if (n === 0) return '';
  return `${n} de ${Number(total || filas.length).toLocaleString('es-CL')} coinciden por `
       + 'número pero con un tipo de documento distinto — probablemente sean otra persona. '
       + 'Revisalas antes de responderle al juzgado.';
}

/** Cuántas filas se piden por vez. El backend recorta y lo dice en `mostrando`. */
export const LIMITE_RESULTADOS = 200;

export function avisoDeRecorteEmbargo(datos) {
  const total = Number(datos?.total || 0);
  const mostrando = Number(datos?.mostrando || 0);
  if (!total || mostrando >= total) return '';
  return `Se ven ${mostrando.toLocaleString('es-CL')} de ${total.toLocaleString('es-CL')}. `
       + 'Para el listado completo, descargá el Excel de la corrida.';
}
