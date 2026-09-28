/* ============================================================================
   El borrador del ROS que trae GEREO
   ----------------------------------------------------------------------------
   Acá vive lo que se puede probar sin navegador: qué admite cada país, qué
   falta en el formulario y cómo se lee lo que vuelve. El dibujo está en la
   pantalla, y el sondeo de la corrida lo hace `seguirCorrida`, que ya existe.

   LO QUE ESTA PANTALLA NO HACE, y es a propósito: no escribe la narrativa del
   ROS. GEREO devuelve un texto redactado, pero pasarlo al campo que firma el
   oficial de cumplimiento es un clic explícito de una persona. El backend
   guarda ese texto en un campo aparte justamente para que no se confundan.

   LA MATRIZ ESTÁ EN DOS LADOS —acá y en `gereo.py`— y eso es una costura que
   se puede separar sin que nada falle: el formulario dejaría elegir algo que
   el backend rechaza, o al revés, bloquearía algo permitido. Hay un test que
   compara las dos listas.
   ========================================================================= */

/* Qué admite cada país. Es la tabla del documento de integración. */
export const PAISES = {
  Argentina: { tipos: ['B2C'], asociados: 0, regulador: 'UIF-AR' },
  Chile: { tipos: ['B2C', 'B2B'], asociados: 15, regulador: 'UAF-CL' },
  Colombia: { tipos: ['B2C', 'B2B'], asociados: 0, regulador: 'UIAF-CO' },
};

/* `ros.js` trabaja con reguladores; GEREO, con países. */
export const PAIS_POR_REGULADOR = Object.fromEntries(
  Object.entries(PAISES).map(([pais, d]) => [d.regulador, pais]),
);

export function paisDe(regulador) {
  return PAIS_POR_REGULADOR[regulador] || '';
}

export function reglasDe(pais) {
  return PAISES[pais] || null;
}

/** Los IDs asociados, de un texto o una lista, sin vacíos ni repetidos. */
export function asociadosDe(valor) {
  const crudos = Array.isArray(valor) ? valor : String(valor || '').split(/[,;\s]+/);
  return [...new Set(crudos.map((x) => String(x).trim()).filter(Boolean))];
}

/** ¿mm/aaaa? */
export function mesValido(v) {
  const m = /^(\d{1,2})\/(\d{4})$/.exec(String(v || '').trim());
  return !!m && Number(m[1]) >= 1 && Number(m[1]) <= 12;
}

/**
 * Qué falta o está mal en el formulario. Lista vacía = se puede pedir.
 *
 * Se valida acá además del backend para no gastar una corrida —y un viaje a
 * la base de GEREO, la misma que atiende a sus analistas— en algo que ya se
 * sabe que va a rebotar.
 */
export function faltaParaGenerar(form) {
  const pais = String(form?.pais || '').trim();
  const reglas = reglasDe(pais);
  if (!reglas) return [`Elegí un país: ${Object.keys(PAISES).join(', ')}.`];

  const faltan = [];
  if (!String(form.customer_id || '').trim()) {
    faltan.push('Falta el id del cliente reportado.');
  }
  const tipo = String(form.tipo_cliente || '').trim().toUpperCase();
  if (!tipo) {
    faltan.push('Elegí si es B2C o B2B.');
  } else if (!reglas.tipos.includes(tipo)) {
    faltan.push(`El ROS de ${pais} sólo cubre ${reglas.tipos.join(' y ')}.`);
  }

  const asociados = asociadosDe(form.clientes_asociados);
  if (asociados.length && reglas.asociados === 0) {
    faltan.push(`El ROS de ${pais} se emite por un único cliente: no admite `
      + 'clientes asociados.');
  } else if (asociados.length > reglas.asociados) {
    faltan.push(`${pais} admite hasta ${reglas.asociados} clientes asociados `
      + `y pusiste ${asociados.length}.`);
  }

  if (!mesValido(form.fecha_inicio)) {
    faltan.push('La fecha de inicio va como mm/aaaa (por ejemplo 01/2025).');
  }
  if (String(form.fecha_fin || '').trim() && !mesValido(form.fecha_fin)) {
    faltan.push('La fecha de fin va como mm/aaaa, o vacía para llegar hasta hoy.');
  }
  return faltan;
}

/** El cuerpo que espera el backend. Los opcionales vacíos no viajan. */
export function cuerpoDeGeneracion(form, email = '') {
  const cuerpo = {
    pais: String(form.pais || '').trim(),
    customer_id: String(form.customer_id || '').trim(),
    tipo_cliente: String(form.tipo_cliente || '').trim().toUpperCase(),
    fecha_inicio: String(form.fecha_inicio || '').trim(),
    actor_email: email,
  };
  const fin = String(form.fecha_fin || '').trim();
  if (fin) cuerpo.fecha_fin = fin;
  const asociados = asociadosDe(form.clientes_asociados);
  if (asociados.length) cuerpo.clientes_asociados = asociados;
  // El PDF sólo si se va a usar: armarlo le suma segundos a cada llamada.
  if (form.incluir_pdf) cuerpo.incluir_pdf = true;
  return cuerpo;
}

/**
 * Cómo se lee lo que vino, para dibujarlo sin repetir lógica en la pantalla.
 *
 * UNA DETENCIÓN NO ES UN ERROR: si el cliente es de otro país, GEREO responde
 * que no hay reporte y eso es la regla de negocio funcionando. Se muestra
 * distinto de una falla, porque reintentar da exactamente lo mismo.
 */
export function resumenDelBorrador(b) {
  if (!b) return null;
  if (b.detenido) {
    return {
      detenido: true,
      titulo: 'No se generó reporte',
      mensaje: b.mensaje || 'El cliente no corresponde al país del reporte.',
    };
  }
  const reglas = b.reglas || {};
  return {
    detenido: false,
    advertencias: b.advertencias || [],
    senales: b.senales || [],
    gatilladas: (reglas.gatilladas || []).length,
    descartadas: (reglas.descartadas || []).length,
    evaluadas: reglas.total_evaluadas || 0,
    secciones: b.secciones || [],
    narrativa: b.narrativa_borrador || [],
    generadoEn: b.generado_en || '',
    conIA: !!b.generado_con_ia,
  };
}

/**
 * El texto de GEREO, listo para copiar al campo que firma el oficial.
 *
 * Devuelve las dos partes con su título: son respuestas a dos preguntas
 * distintas del formulario, y un analista que las copia tiene que ver cuál
 * es cuál dentro del texto que va a firmar.
 */
export function narrativaComoTexto(borrador) {
  return (borrador?.narrativa_borrador || [])
    .map((n) => `${n.titulo}\n${n.texto}`)
    .join('\n\n')
    .trim();
}
