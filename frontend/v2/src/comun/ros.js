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
  /* El registro de ROS no se pudo leer. NO es «Sin ROS»: con `/ros` caído, la
     lista entera afirmaría que ningún caso tiene reporte. */
  no_disponible: { texto: 'No disponible', color: 'neutro' },
  /* Se evaluó y se decidió no reportar. Sin reloj: no falta trabajo. */
  descartado: { texto: 'Descartado', color: 'neutro' },
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
/* QUÉ ROS DEFINE LA COLUMNA cuando un caso tiene varios.
   NO es el más avanzado. Un caso con un ROS enviado y otro en `error_envio`
   se vería «Enviado» y la falla del segundo desaparecería — y el trabajo está
   justamente en el que NO terminó. Se ordena por cuánta atención pide: lo
   roto primero, lo terminado último. */
const ATENCION = ['sin_version', 'error_envio', 'enviando', 'revisado',
                  'recibido', 'enviado', 'descartado', 'sin_ros'];

export function rosPorCaso(listaRos) {
  const fuera = {};
  for (const r of listaRos || []) {
    const caso = r?.case_id;
    if (!caso) continue;
    const etapa = etapaDeRos(r);
    const previo = fuera[caso];
    const gana = !previo
      || ATENCION.indexOf(etapa) < ATENCION.indexOf(previo.etapa);
    const antes = previo ? previo.cuantos : 0;
    if (gana) {
      fuera[caso] = {
        etapa, folio: r.folio, estado: r.estado,
        regulador: r.regulador, version: r.version_actual || 0,
        // Los hechos del caso: de ahí sale desde cuándo corre el plazo.
        evidencia: r.evidencia,
        cuantos: antes + 1,
      };
    } else {
      fuera[caso] = { ...previo, cuantos: antes + 1 };
    }
  }
  return fuera;
}

/** La etapa de UN ros, con la falla de versión por delante. */
export function etapaDeRos(r) {
  // Un ROS que se descartó no sigue camino: mostrar «Recibido» con el reloj
  // corriendo diría que falta trabajo sobre algo ya decidido.
  if (String(r?.estado || '').trim() === 'descartado') return 'descartado';
  if (r?.version_error && !(r?.version_actual > 0)) return 'sin_version';
  const e = String(r?.etapa_gereo || '').trim();
  return Object.prototype.hasOwnProperty.call(ETAPAS_ROS, e) ? e : 'sin_ros';
}

/** Si en esta etapa todavía corre el plazo. */
export function correPlazo(ros) {
  return Boolean(ros) && !['sin_ros', 'enviado', 'descartado', 'no_disponible']
    .includes(ros.etapa);
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
   Definido por Compliance el 23-10-2026: aviso a los 15 días y vencido a los
   30 días CORRIDOS, igual para los tres reguladores.

   EL VALOR VIVE EN UN SOLO LUGAR. Si mañana un regulador pide otro plazo, es
   reemplazar su entrada por `{ aviso: X, vencido: Y }` — una línea, y las
   otras dos no se tocan. Repetir los números por país invita a que se
   actualice uno y se olvide otro, y el que se olvide no falla: muestra verde
   sobre un plazo vencido.                                                   */

const PLAZO_POR_DEFECTO = { aviso: 15, vencido: 30 };

export const PLAZO_LEGAL_DIAS = {
  'UAF-CL': PLAZO_POR_DEFECTO,
  'UIF-AR': PLAZO_POR_DEFECTO,
  'UIAF-CO': PLAZO_POR_DEFECTO,
};

/* QUÉ EVENTO DISPARA EL PLAZO tampoco está confirmado. Acá se cuenta desde la
   primera alerta del caso, que es lo más cercano a «cuando se detectó la
   operación». Puede que el regulador lo cuente desde otra cosa —la operación
   en sí, la conclusión del análisis—. Lo confirma Compliance junto con los
   días; hasta entonces sólo se muestran días transcurridos, que no afirman
   nada sobre el plazo. */

/**
 * Desde cuándo se cuenta el plazo, y por qué.
 *
 * NUNCA desde que se creó el ROS. Esa es la fecha en que un analista abrió el
 * reporte, no en la que se detectó la operación: si el ROS se abre veinte días
 * después de la alerta, contar desde ahí diría «2 días» con el plazo legal ya
 * casi consumido — y el día que se carguen los plazos, el semáforo estaría en
 * verde sobre un plazo vencido.
 */
export function origenDelPlazo(ros) {
  const ev = ros?.evidencia || {};
  const primera = ev.periodo?.desde;
  if (primera) return { fecha: primera, desde: 'la primera alerta' };
  const caso = ev.caso?.creado_at;
  if (caso) return { fecha: caso, desde: 'la apertura del caso' };
  return null;
}

/** Los días desde una fecha. `null` si no se puede saber. */
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
  const origen = origenDelPlazo(ros);
  const dias = origen ? diasDesde(origen.fecha, ahora) : null;
  if (dias === null) return null;
  const plazo = PLAZO_LEGAL_DIAS[ros?.regulador];
  // Un regulador sin plazo definido muestra los días y NO pinta semáforo:
  // el verde afirmaría que hay tiempo de sobra sin que nadie lo sepa.
  if (!plazo) {
    return { dias, limite: null, aviso: null, restantes: null, semaforo: '',
             desde: origen.desde,
             texto: `${dias} día${dias === 1 ? '' : 's'}` };
  }
  const { aviso, vencido: limite } = plazo;
  const restantes = limite - dias;
  // El amarillo arranca EL DÍA DEL AVISO, no faltando dos: lo que importa es
  // cuánto lleva abierto, no cuánto queda. Con 30 días de plazo, avisar
  // recién el día 28 no le da a nadie tiempo de hacer nada.
  const semaforo = dias >= limite ? 'alto' : dias >= aviso ? 'medio' : 'ok';
  return {
    dias, limite, aviso, restantes, semaforo, desde: origen.desde,
    // «quedan 0 de 30» en rojo se lee como si todavía hubiera margen.
    texto: restantes < 0
      ? `vencido hace ${-restantes} día${restantes === -1 ? '' : 's'}`
      : restantes === 0
        ? 'vence hoy'
        : `quedan ${restantes} de ${limite}`,
  };
}
