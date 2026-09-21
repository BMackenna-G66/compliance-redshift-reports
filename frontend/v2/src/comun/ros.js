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
