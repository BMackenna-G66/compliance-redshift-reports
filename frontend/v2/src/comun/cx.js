/* ============================================================================
   La vista de CX
   ----------------------------------------------------------------------------
   La pregunta que CX tiene que poder contestar con el cliente en el teléfono:
   «¿este cliente tiene algo abierto con ustedes?». Nada más.

   POR QUÉ NO ES LA TABLA DE CASOS CON UN FILTRO. Esa tabla tiene doce
   columnas, ocho filtros y acciones que CX no puede usar. Sirve para trabajar
   una cartera; no para resolver una llamada. Acá se escribe un dato y se
   responde una cosa.

   POR QUÉ BUSCA EN MEMORIA Y NO CONTRA LA API. `GET /search/entity` busca por
   identificador, pero el correo del cliente NO está en `/cases` ni en el nivel
   de arriba de `/alerts`: vive dentro de `row_data`, que además llega como
   texto JSON. Así que se arma un índice con las dos listas —son 73 casos
   abiertos y 122 alertas— y se busca sobre eso. Instantáneo, y anda aunque
   Redshift esté pausado.
   ========================================================================= */

import { comoFila } from './alertas.js';
import { CERRADOS } from './casos.js';

/* Dónde aparece el correo del cliente dentro de la fila del reporte. Son dos
   nombres porque distintos reportes lo llaman distinto, y mirar uno solo deja
   afuera a los otros. */
const CLAVES_CORREO = ['customer_email', 'email', 'correo', 'client_email'];

/** El correo del cliente de una alerta, si la fila lo trae. */
export function correoDeAlerta(alerta) {
  const fila = comoFila(alerta?.row_data);
  for (const k of CLAVES_CORREO) {
    const v = fila[k];
    if (typeof v === 'string' && v.includes('@')) return v.trim().toLowerCase();
  }
  return '';
}

function normalizar(v) {
  return String(v ?? '').trim().toLowerCase();
}

/**
 * Arma el índice de búsqueda: por cada cliente, sus casos abiertos y los
 * correos con los que se lo puede encontrar.
 *
 * Se indexa por `entity_id` porque es lo único que está en las dos listas. Los
 * correos se cosechan de las alertas y se pegan al cliente que corresponda: un
 * cliente puede tener varios, y CX va a tener a mano cualquiera de ellos.
 */
export function indice(casos, alertas) {
  const porCliente = new Map();

  const asegurar = (id) => {
    const k = normalizar(id);
    if (!k) return null;
    if (!porCliente.has(k)) {
      porCliente.set(k, { id: String(id), nombre: '', correos: new Set(), casos: [] });
    }
    return porCliente.get(k);
  };

  for (const c of casos || []) {
    // Sólo lo abierto: a CX le preguntan si HAY algo, no qué hubo.
    if (CERRADOS.includes(c?.status)) continue;
    const e = asegurar(c?.entity_id);
    if (!e) continue;
    if (!e.nombre && c.entity_name) e.nombre = c.entity_name;
    e.casos.push(c);
  }

  for (const a of alertas || []) {
    const correo = correoDeAlerta(a);
    if (!correo) continue;
    // El correo se pega al cliente aunque no tenga caso abierto: así la
    // búsqueda por correo puede responder «no tiene nada abierto», que es una
    // respuesta, en vez de «no lo encuentro», que no lo es.
    const e = asegurar(a?.entity_value ?? a?.entity_id);
    if (e) e.correos.add(correo);
  }

  return [...porCliente.values()].map((e) => ({ ...e, correos: [...e.correos] }));
}

/**
 * Busca un cliente por id, por nombre o por correo.
 *
 * El id y el correo se comparan ENTEROS: una coincidencia parcial de «2225»
 * traería medio padrón y CX elegiría mal con el cliente esperando. El nombre
 * sí es parcial, porque nadie lo escribe igual dos veces.
 */
export function buscar(indice, texto) {
  const q = normalizar(texto);
  if (q.length < 3) return [];
  return (indice || []).filter((e) => (
    normalizar(e.id) === q
    || e.correos.some((c) => c === q)
    || (e.nombre && normalizar(e.nombre).includes(q))
  ));
}

/**
 * Qué se le contesta a CX sobre un cliente.
 *
 * Tres respuestas y no dos: «tiene N casos abiertos», «no tiene nada abierto»
 * y «no figura». La diferencia entre las dos últimas importa —una dice que lo
 * revisamos y está limpio, la otra que nunca lo vimos— y juntarlas hace que
 * CX afirme lo primero cuando sólo puede afirmar lo segundo.
 */
export function respuesta(encontrados) {
  if (!encontrados || encontrados.length === 0) {
    return {
      clave: 'sin_registro',
      texto: 'Ese cliente no figura con casos ni alertas.',
      detalle: 'No quiere decir que esté observado y limpio: quiere decir que no '
             + 'aparece en WatchTower.',
    };
  }
  const total = encontrados.reduce((a, e) => a + e.casos.length, 0);
  if (total === 0) {
    return {
      clave: 'sin_abiertos',
      texto: 'Figura en WatchTower, pero no tiene ningún caso abierto.',
      detalle: 'Puede tener alertas o casos ya cerrados.',
    };
  }
  return {
    clave: 'abiertos',
    texto: `Tiene ${total} caso${total === 1 ? '' : 's'} abierto${total === 1 ? '' : 's'}.`,
    detalle: 'Mientras esté abierto puede haber documentación pendiente de su parte.',
  };
}
