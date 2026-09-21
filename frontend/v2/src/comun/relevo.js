/* ============================================================================
   Relevo — la lógica
   ----------------------------------------------------------------------------
   El circuito de pedirle documentación a un cliente porque un partner la
   pidió: entra un correo del corresponsal, se ubica al cliente, se le pide,
   se recontacta, se devuelve al partner.

   LOS ESTADOS Y LAS ETAPAS SON DEL BACKEND. Están en `lambda/relevo/casos.py`
   con su descripción, su etapa numérica y la lista de cuáles se pueden fijar
   a mano. Acá está el color y el orden de lectura, nada más.

   LA DISTINCIÓN QUE ORDENA LA PANTALLA: las etapas negativas no son "pasos
   atrás", son OTRA COSA. Una etapa −1 es un problema de datos —no se ubicó al
   cliente, no tiene correo, no se entendió qué pide el partner— y no se
   arregla trabajando el caso sino arreglando el dato. Mezclarlas con el
   carril feliz haría que 112 de 383 casos parezcan atrasados cuando en
   realidad están trabados por otra razón.
   ========================================================================= */

import { fecha, hace } from './alertas.js';

export { fecha, hace };

/* Las etapas, tal como las numera `casos.py`. */
export const ETAPAS = [
  { n: -2, clave: 'terminal',  etiqueta: 'Sin acción',     color: 'var(--texto-mute)',
    descripcion: 'Informativos, descartados o sin respuesta. No hay nada que hacer.' },
  { n: -1, clave: 'trabado',   etiqueta: 'Falta un dato',  color: 'var(--nivel-critico-texto)',
    descripcion: 'No se ubicó al cliente, no tiene correo, o no se entendió el pedido. Se arregla el dato, no el caso.' },
  { n: 0,  clave: 'por_pedir', etiqueta: 'Por pedir',      color: 'var(--nivel-alto-texto)',
    descripcion: 'Cliente ubicado con correo. Falta pedirle la documentación.' },
  { n: 1,  clave: 'pedido',    etiqueta: 'Pedido',         color: 'var(--g66-azul-texto)',
    descripcion: 'Se le pidió. Esperando respuesta.' },
  { n: 2,  clave: 'respondio', etiqueta: 'Respondió',      color: 'var(--violeta-texto)',
    descripcion: 'El cliente contestó. Falta armar la devolución.' },
  { n: 3,  clave: 'devuelto',  etiqueta: 'Devuelto',       color: 'var(--g66-teal-texto)',
    descripcion: 'Se le devolvió al partner. Esperando cierre.' },
  { n: 4,  clave: 'cerrado',   etiqueta: 'Cerrado',        color: 'var(--nivel-bajo-texto)',
    descripcion: 'Caso cerrado.' },
];

export function etapaDe(caso) {
  const n = Number(caso?.etapa);
  return ETAPAS.find((e) => e.n === n) || null;
}

/** El carril feliz: de "por pedir" a "cerrado". Las negativas quedan afuera. */
export const ETAPAS_CARRIL = ETAPAS.filter((e) => e.n >= 0);

/**
 * Los estados que se pueden fijar a mano.
 *
 * Es la MISMA lista que `ESTADOS_MANUALES` en `casos.py`, y tiene que serlo:
 * el backend rechaza cualquier otro. Se repite acá sólo para armar el
 * desplegable, y hay un test que compara las dos listas — si el backend
 * agrega uno, el test avisa en vez de que la opción falte en silencio.
 *
 * Los cuatro diagnósticos (`sin_cliente`, `sin_correo`, `sin_requerimiento`,
 * `informativo`) quedan afuera a propósito: no son etapas del trabajo sino
 * datos que faltan, y ponerlos a mano tapa el diagnóstico en vez de
 * arreglarlo.
 */
export const ESTADOS_MANUALES = [
  'listo_para_pedir', 'pedido_enviado', 'recontactado', 'respuesta_parcial',
  'respuesta_recibida', 'devuelto', 'sin_respuesta', 'cerrado', 'descartado',
];

/* El nombre legible de cada estado. El backend manda la clave cruda. */
export const NOMBRE_ESTADO = {
  informativo: 'Informativo',
  sin_cliente: 'Sin cliente',
  sin_correo: 'Sin correo',
  sin_requerimiento: 'Sin requerimiento',
  listo_para_pedir: 'Listo para pedir',
  pedido_enviado: 'Pedido enviado',
  recontactado: 'Recontactado',
  respuesta_parcial: 'Respuesta parcial',
  respuesta_recibida: 'Respuesta recibida',
  sin_respuesta: 'Sin respuesta',
  devuelto: 'Devuelto',
  cerrado: 'Cerrado',
  descartado: 'Descartado',
};

export function nombreEstado(clave) {
  return NOMBRE_ESTADO[clave] || clave || '—';
}

/* ── Indicadores ────────────────────────────────────────────────────────── */

/**
 * Los números del tablero de relevo.
 *
 * `trabados` se cuenta aparte de `porPedir` justamente porque son problemas
 * distintos: uno se resuelve escribiéndole al cliente y el otro arreglando un
 * dato. Juntarlos daría un número grande que no dice qué hacer.
 */
export function indicadores(casos) {
  const c = casos || [];
  return {
    total: c.length,
    accionables: c.filter((x) => x.accionable).length,
    porPedir: c.filter((x) => x.estado === 'listo_para_pedir').length,
    trabados: c.filter((x) => Number(x.etapa) === -1).length,
    vencidos: c.filter((x) => x.vencido).length,
    agotados: c.filter((x) => x.agotado).length,
    partners: new Set(c.map((x) => x.partner).filter(Boolean)).size,
  };
}

/** Cuántos casos hay en cada etapa, en el orden del circuito. */
export function porEtapa(casos) {
  const cuenta = new Map(ETAPAS.map((e) => [e.n, 0]));
  let fuera = 0;
  for (const c of casos || []) {
    const n = Number(c?.etapa);
    if (cuenta.has(n)) cuenta.set(n, cuenta.get(n) + 1);
    else fuera += 1;   // una etapa que el front no conoce: no se descarta
  }
  const filas = ETAPAS.map((e) => ({ ...e, n_casos: cuenta.get(e.n) }));
  if (fuera) {
    filas.push({ n: 99, clave: 'desconocida', etiqueta: 'Etapa desconocida',
                 color: 'var(--texto-mute)', n_casos: fuera,
                 descripcion: 'El backend devolvió una etapa que esta pantalla no conoce.' });
  }
  return filas;
}

/** Cuenta por partner, de mayor a menor. */
export function porPartner(casos) {
  const cuenta = new Map();
  for (const c of casos || []) {
    const k = c.partner || 'sin partner';
    cuenta.set(k, (cuenta.get(k) || 0) + 1);
  }
  return [...cuenta.entries()].map(([partner, n]) => ({ partner, n }))
    .sort((a, b) => b.n - a.n);
}

/* ── Interruptores ──────────────────────────────────────────────────────── */

/**
 * Lee el estado de los envíos.
 *
 * ES LA INFORMACIÓN MÁS IMPORTANTE DE LA PANTALLA. Si los envíos están
 * apagados, ningún pedido sale — y una bandeja con 230 casos "listos para
 * pedir" que en realidad no puede pedir nada es una trampa: el analista
 * trabaja y no pasa nada, sin ningún error que lo explique.
 *
 * Hoy los ocho interruptores de salida están apagados a propósito, mientras
 * se termina el desarrollo.
 */
export function estadoDeEnvios(datos) {
  const todos = datos?.interruptores || [];
  const salidas = todos.filter((i) => i.tipo === 'salida');
  const general = salidas.find((i) => i.clave === 'envio_general');
  const porPartner = salidas.filter((i) => i.clave !== 'envio_general');
  return {
    activo: Boolean(datos?.envio_activo),
    generalEncendido: Boolean(general?.valor),
    // El general manda: con él apagado no sale nada aunque un partner esté
    // encendido. Por eso se cuentan aparte.
    partnersEncendidos: porPartner.filter((i) => i.valor).length,
    partnersTotal: porPartner.length,
    apagados: (datos?.apagados || []).length,
    procesosApagados: (datos?.procesos_apagados || []).length,
  };
}

/** Los interruptores agrupados por tipo, en orden de importancia. */
export const ORDEN_TIPO = ['maestro', 'salida', 'proceso'];

export const NOMBRE_TIPO = {
  maestro: 'Maestro',
  salida: 'Envío de correos',
  proceso: 'Procesos internos',
};

export function porTipo(interruptores) {
  const grupos = new Map(ORDEN_TIPO.map((t) => [t, []]));
  for (const i of interruptores || []) {
    const t = i.tipo || 'otro';
    if (!grupos.has(t)) grupos.set(t, []);
    grupos.get(t).push(i);
  }
  return [...grupos.entries()]
    .filter(([, l]) => l.length > 0)
    .map(([tipo, items]) => ({ tipo, etiqueta: NOMBRE_TIPO[tipo] || tipo, items }));
}

/* ── Filtros ────────────────────────────────────────────────────────────── */

export const FILTROS_RELEVO = {
  accionables: { etiqueta: 'Accionables', prueba: (c) => c.accionable },
  por_pedir: { etiqueta: 'Por pedir', prueba: (c) => c.estado === 'listo_para_pedir' },
  trabados: { etiqueta: 'Falta un dato', prueba: (c) => Number(c.etapa) === -1 },
  vencidos: { etiqueta: 'Vencidos', prueba: (c) => c.vencido },
  todos: { etiqueta: 'Todos', prueba: () => true },
};

export function aplicarFiltro(casos, clave) {
  const f = FILTROS_RELEVO[clave];
  if (!f) return casos || [];
  return (casos || []).filter(f.prueba);
}

/** El texto de los documentos que faltan, para la tabla y la búsqueda. */
export function faltantesTexto(caso) {
  const l = caso?.faltantes || [];
  return l.map((x) => x.es || x.item).join(', ');
}
