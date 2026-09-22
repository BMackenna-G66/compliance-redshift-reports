/* ============================================================================
   El pedido de documentación al cliente
   ----------------------------------------------------------------------------
   El correo que se le manda a alguien desde un caso, pidiéndole papeles. Es el
   único lugar de WatchTower donde un analista le escribe directamente a un
   cliente, así que acá vive todo lo que decide si ese correo puede salir.

   LAS DOS REGLAS QUE NO SON OBVIAS:

   · La plantilla de TEXTO LIBRE no pide documentos. Sirve para aclarar algo de
     un pedido anterior. Exigirle un documento obligaba a marcar uno, y ese
     documento después aparecía pedido en el correo y en el checklist del caso
     — se le terminaba pidiendo al cliente algo que nadie quería pedirle.

   · Si ya se le pidió lo mismo hace poco y no contestó, hay que decirlo ANTES.
     Dos correos iguales con tres días de diferencia es lo que hace que un
     cliente deje de leerlos.
   ========================================================================= */

/** Cuántos días atrás se buscan pedidos previos. */
export const DIAS_PEDIDOS_PREVIOS = 30;

/**
 * Qué le falta al pedido para poder mandarse.
 *
 * Devuelve la lista de faltantes en vez de cortar en el primero: quien está
 * escribiendo el correo quiere saber todo lo que le falta de una, no
 * descubrirlo de a uno cada vez que aprieta.
 */
export function faltaParaPedir({ correo, documentos, textoLibre }, plantilla) {
  const falta = [];
  if (!String(correo || '').trim()) falta.push('el correo del cliente');
  // La plantilla de texto libre es la excepción: no pide documentos.
  if (!plantilla?.requires_custom_text && (documentos || []).length === 0) {
    falta.push('al menos un documento');
  }
  if (plantilla?.requires_custom_text && !String(textoLibre || '').trim()) {
    falta.push('el texto del correo (esta plantilla es de texto libre)');
  }
  return falta;
}

/**
 * La plantilla que corresponde cuando la elegida no existe.
 *
 * Una plantilla desconocida no puede dejar el panel mudo: se cae a la
 * genérica del tipo de entidad, que siempre está, y se dice cuál se usó.
 */
export function plantillaPorDefecto(tipoEntidad) {
  return tipoEntidad === 'company' ? 'b2b_generico' : 'general_b2c';
}

export function resolverPlantilla(clave, catalogo, tipoEntidad) {
  const existe = (catalogo || []).some((t) => t.key === clave);
  if (existe) return { clave, aviso: '' };
  const respaldo = plantillaPorDefecto(tipoEntidad);
  return {
    clave: respaldo,
    aviso: `La plantilla «${clave || '(vacía)'}» no está en el catálogo; se usa «${respaldo}».`,
  };
}

/**
 * Los pedidos previos que todavía esperan respuesta.
 *
 * Se descartan los respondidos —ya cumplieron— y el de este mismo caso, que
 * obviamente aparece y no es un duplicado.
 */
export function pedidosSinResponder(solicitudes) {
  return (solicitudes || []).filter((s) => !s.respondida && !s.es_este_caso);
}

export function avisoDePedidosPrevios(pendientes) {
  if (!pendientes || pendientes.length === 0) return '';
  const n = pendientes.length;
  return `A este cliente ya se le pidió documentación ${n} vez(ces) en los últimos `
       + `${DIAS_PEDIDOS_PREVIOS} días y todavía no respondió. Dos correos iguales con `
       + 'pocos días de diferencia hacen que deje de leerlos.';
}

/** La prioridad del correo, derivada de la del caso. */
export function prioridadDelCaso(caso) {
  return { high: 'P1', medium: 'P2' }[caso?.priority] || 'P3';
}

/**
 * Con qué datos se abre el formulario.
 *
 * El nombre y el correo salían SÓLO del último pedido, así que la primera vez
 * que se redactaba un correo —justo cuando hacen falta— aparecían vacíos.
 * Ahora el pedido anterior manda si existe, y si no se cae a lo que ya se sabe
 * del caso y de la ficha KYC que el analista haya traído.
 */
export function borradorDelPedido({ caso, ultimoPedido, perfil, checklist } = {}) {
  const p = perfil || {};
  // El checklist sale del caso salvo que se pase otro: que el llamador tenga
  // que acordarse de pasarlo es cómo se termina abriendo el correo sin ningún
  // documento marcado.
  const docs = checklist || caso?.documentos_checklist || [];
  const esEmpresa = caso?.entity_type === 'company';
  return {
    entity_type: caso?.entity_type || 'customer',
    entity_id: caso?.entity_id ? String(caso.entity_id) : '',
    nombre: ultimoPedido?.nombre_completo || caso?.entity_name
            || p.nombre_completo || p.razon_social || '',
    correo: ultimoPedido?.correo || p.email || p.correo || p.customer_email || '',
    prioridad: prioridadDelCaso(caso),
    alerta: caso?.report_name || '',
    documentos: docs.map((x) => x.categoria).filter(Boolean),
    case_id: caso?.case_id || '',
    template_key: ultimoPedido?.template_key || plantillaPorDefecto(caso?.entity_type),
    texto_libre: '',
    alert_data: caso?.alert_data || {},
    esEmpresa,
  };
}
