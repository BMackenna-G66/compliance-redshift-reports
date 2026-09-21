/* ============================================================================
   Casos — la lógica
   ----------------------------------------------------------------------------
   EL PLAZO NO SE CALCULA ACÁ. Lo calcula `lambda/sla_casos.py` y llega hecho
   en los campos `sla_*` de cada caso, junto con los umbrales en `sla_config`.
   Este archivo sólo lee esos campos y los ordena para mostrarlos.

   Es deliberado y vale la pena decir por qué: la regla —36 horas para
   recontactar, 72 para cerrar— es de compliance. Si el front la recalculara,
   habría dos definiciones del mismo plazo y un día dirían cosas distintas.
   La pantalla mostraría un caso en verde que el sistema considera vencido, y
   nadie sabría cuál de las dos tiene razón.

   LO QUE LOS DATOS REALES DICEN HOY (medido sobre los 89 casos):
   de 69 casos con el reloj corriendo, los 69 están vencidos. Ninguno en
   verde, ninguno en amarillo. El más nuevo tiene 6,8 días y el plazo es 3.
   Por eso estas funciones distinguen "cuánto falta" de "cuánto hace que
   venció": con estos datos, el único gradiente que existe es el segundo.
   ========================================================================= */

import { ESTADOS_CASO, ESTADOS_SLA, SLA_SIN_RELOJ } from '../dominio.js';
import { fecha, hace } from './alertas.js';

export { fecha, hace };

/* Los estados que significan "esto sigue sobre la mesa". Un estado nuevo del
   backend cuenta como abierto: preferimos que aparezca como pendiente y
   alguien pregunte, a que desaparezca del recuento en silencio. */
export const CERRADOS = ['closed', 'archived'];

export function estaAbierto(caso) {
  return !CERRADOS.includes(caso?.status);
}

/** La definición del semáforo para este caso, o la de "sin reloj". */
export function semaforoDe(caso) {
  return ESTADOS_SLA[caso?.sla_estado] || SLA_SIN_RELOJ;
}

/** La etiqueta a mostrar: la que manda el backend, y si no, el respaldo. */
export function etiquetaSla(caso) {
  return caso?.sla_etiqueta || semaforoDe(caso).etiqueta;
}

/**
 * Cuánto lleva abierto, o cuánto tardó si ya se cerró.
 *
 * Devuelve `null` —no cero— cuando el caso no tiene reloj. Un caso que no
 * nació de una alerta no lleva "0 días": no se le mide el tiempo.
 */
export function diasDe(caso) {
  const d = caso?.sla_dias;
  return d === null || d === undefined ? null : Number(d);
}

/**
 * Cuánto hace que venció, en días. `null` si no venció.
 *
 * `sla_horas_restantes` llega negativo cuando el plazo ya pasó. Se da vuelta
 * acá para que la pantalla hable de "9 días vencido" y no de "-216 horas
 * restantes", que obliga a hacer la cuenta mentalmente.
 */
export function diasVencido(caso) {
  const h = caso?.sla_horas_restantes;
  if (h === null || h === undefined) return null;
  const n = Number(h);
  if (Number.isNaN(n) || n >= 0) return null;
  return Math.abs(n) / 24;
}

/** "3 días", "hace 9 días vencido". Nunca un número pelado sin unidad. */
export function diasTexto(dias) {
  if (dias === null || dias === undefined) return '—';
  if (dias < 1) {
    const h = Math.round(dias * 24);
    return `${h} h`;
  }
  const d = Math.round(dias);
  return `${d} día${d === 1 ? '' : 's'}`;
}

/** Si nunca se le escribió al cliente por este caso. */
export function sinContactar(caso) {
  return Number(caso?.sla_contactos || 0) === 0;
}

/* ── Preparar para la tabla ─────────────────────────────────────────────── */

export function prepararCaso(caso) {
  const sem = semaforoDe(caso);
  const vencido = diasVencido(caso);
  return {
    ...caso,
    _estado: ESTADOS_CASO[caso?.status]?.etiqueta || caso?.status || '—',
    _sla: etiquetaSla(caso),
    // El orden de urgencia, para que la tabla ordene por gravedad y no por
    // el alfabeto de la etiqueta ("Cerrado" antes que "Vencido").
    _slaOrden: sem.orden,
    _dias: diasDe(caso),
    _vencidoDias: vencido,
    _contactos: Number(caso?.sla_contactos || 0),
    _analista: caso?.assigned_to || '',
    _notas: Number(caso?.note_count || 0),
  };
}

/* ── Indicadores ────────────────────────────────────────────────────────── */

/**
 * Los números del tablero de casos.
 *
 * `sinContactar` cuenta sólo los abiertos a propósito: un caso cerrado al que
 * nunca se contactó ya no es trabajo pendiente, es historia. Mezclarlos
 * inflaría el número que se supone que empuja a actuar.
 */
export function indicadores(casos) {
  const c = casos || [];
  const abiertos = c.filter(estaAbierto);
  return {
    total: c.length,
    abiertos: abiertos.length,
    vencidos: abiertos.filter((x) => x.sla_estado === 'vencido').length,
    porContactar: abiertos.filter((x) => x.sla_aplica && sinContactar(x)).length,
    sinAsignar: abiertos.filter((x) => !x.assigned_to).length,
    respondieron: abiertos.filter((x) => x.sla_respondio).length,
    sinReloj: c.filter((x) => !x.sla_aplica).length,
  };
}

/**
 * Cuánto tardan en cerrarse los casos que ya se cerraron.
 *
 * Mediana y no promedio: con 15 casos cerrados y uno que tardó 61 días, el
 * promedio lo decide ese caso solo. Se devuelven los dos y la pantalla
 * muestra la mediana, pero tener el promedio al lado deja ver cuándo están
 * lejos — que es justo la señal de que hay un caso extremo escondido.
 */
export function tiempoDeCierre(casos) {
  const dias = (casos || [])
    .filter((c) => !estaAbierto(c) && c.sla_dias !== null && c.sla_dias !== undefined)
    .map((c) => Number(c.sla_dias))
    .filter((d) => !Number.isNaN(d))
    .sort((a, b) => a - b);
  if (dias.length === 0) return { n: 0, mediana: null, promedio: null, enPlazo: 0 };
  const medio = Math.floor(dias.length / 2);
  return {
    n: dias.length,
    mediana: dias.length % 2 ? dias[medio] : (dias[medio - 1] + dias[medio]) / 2,
    promedio: dias.reduce((a, b) => a + b, 0) / dias.length,
    enPlazo: dias.filter((d) => d <= 3).length,
  };
}

/* ── Kanban ─────────────────────────────────────────────────────────────── */

/* Las columnas del tablero, en el orden en que avanza el trabajo. */
export const COLUMNAS_KANBAN = ['open', 'in_progress', 'under_review', 'closed'];

/**
 * Agrupa los casos en las columnas del tablero.
 *
 * Un estado que no esté en `COLUMNAS_KANBAN` NO se descarta: se le arma una
 * columna propia al final. Tirar casos porque el backend agregó un estado
 * sería perder trabajo de vista sin que nadie se entere.
 */
export function porColumna(casos) {
  const grupos = new Map(COLUMNAS_KANBAN.map((k) => [k, []]));
  for (const c of casos || []) {
    const k = c?.status || 'sin_estado';
    if (!grupos.has(k)) grupos.set(k, []);
    grupos.get(k).push(c);
  }
  // Dentro de cada columna, lo más urgente arriba.
  for (const lista of grupos.values()) {
    lista.sort((a, b) => {
      const oa = semaforoDe(a).orden;
      const ob = semaforoDe(b).orden;
      if (oa !== ob) return oa - ob;
      return (diasDe(b) ?? -1) - (diasDe(a) ?? -1);
    });
  }
  return [...grupos.entries()].map(([clave, items]) => ({
    clave,
    etiqueta: ESTADOS_CASO[clave]?.etiqueta || clave,
    color: ESTADOS_CASO[clave]?.color || 'var(--texto-mute)',
    items,
  }));
}

/* ── Filtros ────────────────────────────────────────────────────────────── */

export const FILTROS_CASO = {
  abiertos: { etiqueta: 'Abiertos', prueba: estaAbierto },
  vencidos: { etiqueta: 'Vencidos', prueba: (c) => estaAbierto(c) && c.sla_estado === 'vencido' },
  sin_contactar: {
    etiqueta: 'Sin contactar',
    prueba: (c) => estaAbierto(c) && c.sla_aplica && sinContactar(c),
  },
  sin_asignar: { etiqueta: 'Sin asignar', prueba: (c) => estaAbierto(c) && !c.assigned_to },
  respondieron: { etiqueta: 'Respondieron', prueba: (c) => estaAbierto(c) && c.sla_respondio },
  todos: { etiqueta: 'Todos', prueba: () => true },
};

export function aplicarFiltro(casos, clave) {
  const f = FILTROS_CASO[clave];
  if (!f) return casos || [];
  return (casos || []).filter(f.prueba);
}

/** Cuenta por analista, de mayor a menor. Sólo los abiertos: la carga es lo
 *  que cada uno tiene encima ahora, no lo que despachó el mes pasado. */
export function porAnalista(casos) {
  const cuenta = new Map();
  for (const c of (casos || []).filter(estaAbierto)) {
    const k = c.assigned_to || '';
    cuenta.set(k, (cuenta.get(k) || 0) + 1);
  }
  return [...cuenta.entries()]
    .map(([correo, n]) => ({
      correo,
      nombre: correo ? correo.replace('@global66.com', '') : 'sin asignar',
      n,
    }))
    .sort((a, b) => b.n - a.n);
}
