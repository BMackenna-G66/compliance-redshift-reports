/* ============================================================================
   ROS — la lógica del front
   ----------------------------------------------------------------------------
   EL VOCABULARIO LO MANDA EL BACKEND. `GET /ros` devuelve los reguladores,
   los estados y las transiciones junto con los datos. Acá no se repite
   ninguno: si mañana se agrega un cuarto regulador o cambia el circuito, la
   pantalla lo sigue sin que nadie la toque.

   Lo único que vive acá es el COLOR de cada estado, que es una decisión
   visual, y las funciones que leen lo que el backend mandó.
   ========================================================================= */

import { fecha, hace } from './alertas.js';

export { fecha, hace };

/* El color de cada estado. Si el backend agrega uno, se muestra en gris con
   su nombre crudo: mejor un estado sin color que una pantalla que lo
   esconde. */
export const COLOR_ESTADO = {
  borrador:       { color: 'var(--texto-2)',            fondo: 'var(--superficie-3)' },
  revision_legal: { color: 'var(--nivel-alto-texto)',   fondo: 'var(--nivel-alto-tenue)' },
  enviado:        { color: 'var(--nivel-bajo-texto)',   fondo: 'var(--nivel-bajo-tenue)' },
  descartado:     { color: 'var(--texto-mute)',         fondo: 'var(--superficie-3)' },
};

export function colorDe(estado) {
  return COLOR_ESTADO[estado] || { color: 'var(--texto-mute)', fondo: 'var(--superficie-3)' };
}

/* Los nombres legibles. El backend manda la clave y su descripción; el
   nombre corto para la insignia es cosa de la pantalla. */
export const NOMBRE_ESTADO = {
  borrador: 'Borrador',
  revision_legal: 'Revisión legal',
  enviado: 'Enviado',
  descartado: 'Descartado',
};

export function nombreEstado(clave) {
  return NOMBRE_ESTADO[clave] || clave || '—';
}

/** A qué estados puede pasar este reporte, según lo que dijo el backend. */
export function destinosDe(reporte, transiciones) {
  return (transiciones || {})[reporte?.estado] || [];
}

/** Si el reporte todavía se puede editar. Un enviado ya salió. */
export function editable(reporte) {
  return reporte?.estado !== 'enviado';
}

/**
 * Qué le falta a un borrador para poder enviarse.
 *
 * Se calcula acá además de en el backend —que es quien de verdad lo
 * impide— para poder decirlo ANTES de que alguien apriete: un botón que
 * falla al pulsarlo con un error rojo es peor que uno que explica desde el
 * principio qué falta.
 */
export function faltaParaEnviar(reporte) {
  const falta = [];
  if (!String(reporte?.narrativa || '').trim()) {
    falta.push('la descripción de la sospecha');
  }
  return falta;
}

/**
 * Los puntos del borrador de GEREO que esperan criterio humano.
 *
 * NO SE CALCULAN ACÁ: vienen en la respuesta. La regla vive en
 * `ros_gereo.listo_para_enviar()` y reimplementarla en JS dejaría dos
 * versiones que se separan sin que nada falle — el botón habilitado de este
 * lado y el 400 del otro. Es la misma razón por la que el vocabulario de
 * reguladores y estados viaja con la respuesta en vez de estar copiado.
 */
export function pendientesGereo(reporte) {
  return reporte?.pendientes_gereo || [];
}

/**
 * Si el reporte se puede mover a `destino` con lo que hay.
 *
 * Enviar pide dos cosas distintas: que la narrativa exista —eso lo mira
 * `faltaParaEnviar`— y que, si el texto vino de GEREO, alguien acuse haber
 * leído lo que quedó pendiente. Lo segundo no es un dato que falte: es una
 * firma, y por eso depende del `acuse` y no del reporte.
 */
export function puedeMover(reporte, destino, acuse = false) {
  if (destino !== 'enviado') return true;
  if (faltaParaEnviar(reporte).length > 0) return false;
  return pendientesGereo(reporte).length === 0 || Boolean(acuse);
}

/** El nombre del regulador para mostrar: «UAF · Chile». */
export function nombreRegulador(clave, reguladores) {
  const d = (reguladores || {})[clave];
  return d ? `${d.nombre} · ${d.pais}` : clave || '—';
}

/* ── La evidencia ───────────────────────────────────────────────────────── */

/**
 * Los montos, tal como vienen: uno por alerta y por campo, sin sumar.
 *
 * El backend ya los deja así a propósito —cada reporte mide una cosa
 * distinta— y la pantalla no los totaliza por la misma razón. Un total que
 * mezcla «lo girado en 7 días» con «el acumulado de depósitos chicos» no
 * significa nada, y acá terminaría dentro de un documento legal.
 */
export function montosDe(reporte) {
  return reporte?.evidencia?.montos || [];
}

export function alertasDe(reporte) {
  return reporte?.evidencia?.alertas || [];
}

export function periodoTexto(reporte) {
  const p = reporte?.evidencia?.periodo || {};
  if (!p.desde && !p.hasta) return 'sin alertas vinculadas';
  const f = (t) => fecha(t)?.toLocaleDateString('es-CL') || t;
  return p.desde === p.hasta ? f(p.desde) : `${f(p.desde)} – ${f(p.hasta)}`;
}

/* ── La etapa del ROS, en la lista de casos ───────────────────────────────
   El caso y el ROS son dos registros distintos: la etapa vive en el ROS y la
   lista muestra casos. Se cruzan por `case_id` acá, del lado del front,
   porque `/cases` lo usan varias pantallas y sumarle una lectura de ROS por
   caso lo encarecería para todas — y los ROS son pocos.                    */

/* Lo que se muestra por etapa. El texto sale de `ros_etapas.ETAPAS` del
   backend; acá va sólo cómo se ve. */
export const ETAPAS_ROS = {
  sin_ros: { texto: 'Sin ROS', color: 'neutro' },
  recibido: { texto: 'Recibido', color: 'info' },
  revisado: { texto: 'Revisado', color: 'medio' },
  enviando: { texto: 'Enviando…', color: 'medio' },
  enviado: { texto: 'Enviado', color: 'ok' },
  error_envio: { texto: 'Error de envío', color: 'alto' },
  /* NO es «Sin ROS». El reporte existe: lo que falló fue guardar su versión,
     y mostrarlo como si no existiera esconde la falla detrás de un estado
     normal — que es justo lo que no puede pasar con un registro regulatorio. */
  sin_version: { texto: 'Sin versión guardada', color: 'alto' },
};

/**
 * Qué ROS tiene cada caso. `{case_id: {etapa, folio, pais, estado}}`.
 *
 * Si un caso tiene más de un ROS —se puede: un caso puede reportarse dos
 * veces— gana el más avanzado, que es el que describe dónde está el trabajo.
 */
export function rosPorCaso(listaRos) {
  const orden = ['sin_ros', 'sin_version', 'error_envio', 'recibido',
                 'revisado', 'enviando', 'enviado'];
  const fuera = {};
  for (const r of listaRos || []) {
    const caso = r?.case_id;
    if (!caso) continue;
    const etapa = etapaDeRos(r);
    const previo = fuera[caso];
    if (!previo || orden.indexOf(etapa) > orden.indexOf(previo.etapa)) {
      fuera[caso] = {
        etapa, folio: r.folio, estado: r.estado,
        regulador: r.regulador, version: r.version_actual || 0,
        // Para el indicador de plazo: cuánto lleva abierto este reporte.
        creado_at: r.creado_at,
      };
    }
  }
  return fuera;
}

/** La etapa de UN ros, con la falla de versión por delante. */
export function etapaDeRos(r) {
  if (r?.version_error && !(r?.version_actual > 0)) return 'sin_version';
  const e = String(r?.etapa_gereo || '').trim();
  return Object.prototype.hasOwnProperty.call(ETAPAS_ROS, e) ? e : 'sin_ros';
}

/** Cómo se dibuja la etapa de un caso que puede no tener ROS. */
export function etiquetaEtapa(ros) {
  const etapa = ros?.etapa || 'sin_ros';
  return ETAPAS_ROS[etapa] || ETAPAS_ROS.sin_ros;
}

/**
 * Los casos que pasan el filtro de etapa y de país.
 *
 * `''` en cualquiera de los dos significa «todos»: es lo que hace que los dos
 * filtros se puedan combinar sin escribir las cuatro combinaciones.
 */
export function filtrarPorRos(casos, mapa, { etapa = '', regulador = '' } = {}) {
  if (!etapa && !regulador) return casos;
  return (casos || []).filter((c) => {
    const r = mapa[c.case_id];
    const suEtapa = r?.etapa || 'sin_ros';
    if (etapa && suEtapa !== etapa) return false;
    // Un caso sin ROS no tiene país de reporte: filtrar por país lo saca,
    // que es lo que espera quien filtró «Chile».
    if (regulador && r?.regulador !== regulador) return false;
    return true;
  });
}

/* ── El plazo legal ───────────────────────────────────────────────────────
   LOS DÍAS NO ESTÁN DEFINIDOS, y no se inventan. Cada regulador tiene su
   plazo y ninguno está confirmado por Compliance; poner un número supuesto
   sería peor que no mostrar nada, porque alguien lo tomaría por bueno y
   podría dejar pasar un plazo real creyendo que le sobra tiempo.

   Mientras tanto se muestran los DÍAS TRANSCURRIDOS, sin semáforo. Eso ya
   sirve —ordena y deja ver cuál lleva más— y no afirma nada que no sepamos.
   El día que Compliance defina los plazos, se llenan acá y el semáforo
   aparece solo.                                                            */

export const PLAZO_LEGAL_DIAS = {
  'UAF-CL': null,
  'UIF-AR': null,
  'UIAF-CO': null,
};

/** Los días desde que se creó el ROS. `null` si no se puede saber. */
export function diasDesde(fechaIso, ahora = new Date()) {
  if (!fechaIso) return null;
  const d = new Date(String(fechaIso).replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor((ahora - d) / 86400000));
}

/**
 * El indicador de plazo: cuántos días van y, si el plazo está definido,
 * cuánto queda.
 *
 * `semaforo` es `''` mientras no haya plazo: la pantalla no pinta nada en vez
 * de pintar verde, que afirmaría que hay tiempo de sobra sin saberlo.
 */
export function plazoDe(ros, ahora = new Date()) {
  const dias = diasDesde(ros?.creado_at, ahora);
  if (dias === null) return null;
  const limite = PLAZO_LEGAL_DIAS[ros?.regulador];
  if (!limite) {
    return { dias, limite: null, restantes: null, semaforo: '',
             texto: `${dias} día${dias === 1 ? '' : 's'}` };
  }
  const restantes = limite - dias;
  const semaforo = restantes < 0 ? 'alto' : restantes <= 2 ? 'medio' : 'ok';
  return {
    dias, limite, restantes, semaforo,
    texto: restantes < 0
      ? `vencido hace ${-restantes} día${restantes === -1 ? '' : 's'}`
      : `quedan ${restantes} de ${limite}`,
  };
}
