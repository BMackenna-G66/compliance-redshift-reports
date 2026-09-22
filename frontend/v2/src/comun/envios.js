/* ============================================================================
   Los envíos del relevo
   ----------------------------------------------------------------------------
   Todo lo que le manda un correo a un cliente pasa por acá, y todo funciona
   igual: se pide una VISTA PREVIA primero (`POST` sin `enviar`) y recién
   después se manda (`POST` con `enviar: true`).

   ESE DOS TIEMPOS NO ES UN LUJO. Del otro lado hay una persona real. La vista
   previa muestra a quién le va a llegar, con qué asunto y con qué cuerpo, y el
   backend además dice en `puede_enviar` si el interruptor de ese partner está
   encendido. Un botón de un solo paso acá manda correo a clientes por un clic
   distraído, y eso no se deshace.

   EL INTERRUPTOR MANDA. Los ocho interruptores de envío están APAGADOS: el
   flujo está construido pero no contacta a nadie hasta que se enciendan a
   propósito. Esta capa no los puede saltear — sólo el backend decide— pero sí
   se encarga de DECIRLO antes, para que nadie escriba un correo entero
   creyendo que va a salir.
   ========================================================================= */

/** Qué impide mandar, según lo que dijo la vista previa. */
export function impedimento(vista) {
  if (!vista) return 'Todavía no se pudo armar la vista previa.';
  if (vista.error) return vista.error;
  if (vista.puede_enviar === false) {
    return vista.motivo
      || 'El envío está apagado para este partner. Se enciende en los interruptores.';
  }
  if (!vista.para) return 'No hay dirección de correo a la cual mandarlo.';
  return '';
}

export function puedeEnviar(vista) {
  return impedimento(vista) === '';
}

/**
 * El texto que se le muestra a quien va a apretar «enviar».
 *
 * Nombra al destinatario en vez de contarlo. «Se enviará 1 correo» no le dice
 * nada a nadie; «se le va a escribir a fulano@correo.com» sí, y es lo único
 * que frena un envío al cliente equivocado.
 */
export function confirmacionDeEnvio(vista, { cierra = false } = {}) {
  const partes = [`Le va a llegar un correo a ${vista?.para || '(sin destinatario)'}.`];
  if (vista?.asunto) partes.push(`Asunto: «${vista.asunto}»`);
  partes.push('Queda registrado en el caso.');
  if (cierra) partes.push('Esto CIERRA el caso.');
  partes.push('¿Confirmás?');
  return partes.join('\n\n');
}

/* ── El lote ─────────────────────────────────────────────────────────────── */

/* El tope del backend. Se repite acá para poder frenarlo antes de armar
   veinte correos y que el lote entero falle. */
export const TOPE_LOTE = 20;

/* Cuántos destinatarios se nombran en la confirmación antes de resumir. Ocho
   entran en un diálogo sin que haya que desplazarlo. */
const NOMBRADOS = 8;

export function problemaConElLote(casos) {
  if (!casos || casos.length === 0) return 'No hay ningún caso seleccionado.';
  if (casos.length > TOPE_LOTE) {
    return `El lote admite hasta ${TOPE_LOTE} casos y seleccionaste ${casos.length}. `
         + 'Achicá la selección.';
  }
  const sinCorreo = casos.filter((c) => !c.cliente_correo);
  if (sinCorreo.length) {
    return `${sinCorreo.length} de los casos seleccionados no tienen correo del cliente.`;
  }
  return '';
}

/**
 * La confirmación del lote: se NOMBRAN los clientes, no se cuentan.
 *
 * «20 correos» no dice nada; «estos 20 clientes» sí, y es la última
 * oportunidad de ver que se coló uno que no correspondía.
 */
export function confirmacionDelLote(casos) {
  const lista = casos.slice(0, NOMBRADOS)
    .map((c) => `  · ${c.cliente_nombre || '(sin nombre)'} <${c.cliente_correo}>`)
    .join('\n');
  const resto = casos.length > NOMBRADOS
    ? `\n  · …y ${casos.length - NOMBRADOS} más` : '';
  return `Se le va a enviar el pedido a ${casos.length} cliente(s) REALES:\n\n`
       + `${lista}${resto}\n\nCada uno recibe su correo por separado. ¿Confirmás?`;
}

/**
 * El resultado del lote, contado y con los fallos nombrados.
 *
 * «3 fallidos» obliga a ir a buscar cuáles, y el motivo de cada uno suele ser
 * distinto: uno sin correo, otro con el interruptor apagado, otro rebotado.
 */
export function resumenDelLote(datos) {
  const resultados = datos?.resultados || [];
  const fallidos = resultados.filter((r) => !r.enviado);
  return {
    enviados: Number(datos?.enviados || 0),
    fallidos: Number(datos?.fallidos || fallidos.length),
    detalle: fallidos.map((r) => ({
      caso: r.caso_id, motivo: r.error || 'sin detalle',
    })),
  };
}

/* ── El espejo de Redshift ───────────────────────────────────────────────── */

/* El espejo corre en la Lambda de reportes, no en la de la API, así que no
   devuelve el resultado: hay que preguntar por la última corrida hasta que
   aparezca una NUEVA. */
export const ESPERA_ESPEJO = 3000;
export const VUELTAS_ESPEJO = 40;

/**
 * Si la corrida que devuelve el backend es una distinta de la que había.
 *
 * Comparar contra la anterior es lo que evita mostrar la corrida de ayer como
 * si fuera ésta — que es exactamente lo que pasa si sólo se mira que haya
 * «una última corrida».
 */
export function esCorridaNueva(ultima, antes) {
  return Boolean(ultima?.arrancado_en) && ultima.arrancado_en !== antes;
}

/** El aviso de que forzar el espejo enciende el clúster, y eso cuesta plata. */
export const AVISO_FORZAR_ESPEJO =
  'Forzar enciende el clúster de Redshift si está pausado, y eso cuesta. '
  + '¿Seguimos?';
