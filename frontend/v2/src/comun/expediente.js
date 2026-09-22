/* ============================================================================
   El expediente del caso
   ----------------------------------------------------------------------------
   Todo lo que el detalle del caso sabe hacer además de cambiar el estado y
   dejar notas: la ficha KYC que se trae del cluster, los datos de la alerta
   que lo originó, el checklist de documentos, los adjuntos y el historial de
   correos.

   ESTÁ ACÁ Y NO EN LA PANTALLA porque son las reglas que hay que poder
   probar: qué campos se muestran y cuáles se esconden, en qué orden gira el
   checklist, qué cuenta como «el correo no salió». La pantalla dibuja.
   ========================================================================= */

import { fecha, hace } from './alertas.js';
import { MAX_TOKENS_IA, TEMPERATURA_IA } from './ia.js';

export { fecha, hace, MAX_TOKENS_IA, TEMPERATURA_IA };

/* ── Los campos de un objeto plano ───────────────────────────────────────── */

/* Vacío es vacío, y «—» también: el backend manda ese guión cuando no tiene
   el dato, y mostrarlo como si fuera un valor llena la grilla de campos que
   no dicen nada y esconde los que sí. */
const SIN_DATO = new Set(['', '—', '-', 'null', 'undefined', 'None']);

function esVacio(v) {
  return v === null || v === undefined || SIN_DATO.has(String(v).trim());
}

/**
 * Convierte un diccionario del backend en filas para mostrar.
 *
 * Los números van con separador de miles en castellano —un `1234567` crudo
 * es ilegible en una grilla— y los booleanos en palabras, porque «false»
 * dentro de una ficha de compliance se lee como un dato, no como un «no».
 *
 * Los objetos y las listas se serializan en vez de quedar en `[object
 * Object]`: el backend cuelga estructuras anidadas en algunas fichas y ese
 * texto es lo único que las delata.
 */
export function campos(objeto) {
  if (!objeto || typeof objeto !== 'object' || Array.isArray(objeto)) return [];
  const filas = [];
  for (const [clave, valor] of Object.entries(objeto)) {
    if (esVacio(valor)) continue;
    let texto;
    if (typeof valor === 'number') texto = valor.toLocaleString('es-CL');
    else if (typeof valor === 'boolean') texto = valor ? 'Sí' : 'No';
    else if (typeof valor === 'object') texto = JSON.stringify(valor);
    else texto = String(valor);
    filas.push({ clave, etiqueta: clave.replace(/_/g, ' '), valor: texto });
  }
  return filas;
}

/* ── El checklist de documentos ──────────────────────────────────────────── */

/* Gira en círculo con un clic. Tres estados y no dos porque «recibido» y
   «entregado» son cosas distintas: el cliente mandó algo, y ese algo sirve.
   Confundirlos cierra casos con documentación que nadie miró. */
export const ESTADOS_DOCUMENTO = {
  pendiente: { etiqueta: 'Pendiente', color: 'var(--texto-mute)', fondo: 'var(--superficie-3)' },
  recibido: { etiqueta: 'Recibido · sin validar', color: 'var(--nivel-alto-texto)', fondo: 'var(--nivel-alto-tenue)' },
  entregado: { etiqueta: 'Entregado', color: 'var(--nivel-bajo-texto)', fondo: 'var(--nivel-bajo-tenue)' },
};

const CICLO = { pendiente: 'recibido', recibido: 'entregado', entregado: 'pendiente' };

export function siguienteEstadoDocumento(actual) {
  return CICLO[actual] || 'recibido';
}

export function estadoDocumento(item) {
  const clave = item?.estado || 'pendiente';
  return ESTADOS_DOCUMENTO[clave] ? clave : 'pendiente';
}

/** Cuántos documentos hay en cada estado, para el resumen del encabezado. */
export function resumenChecklist(items) {
  const cuenta = { pendiente: 0, recibido: 0, entregado: 0 };
  for (const it of items || []) cuenta[estadoDocumento(it)] += 1;
  return { ...cuenta, total: (items || []).length };
}

/* ── El historial de correos ─────────────────────────────────────────────── */

/**
 * Un envío que falló también es historia: explica un silencio.
 *
 * El backend manda `salio: false` con el motivo. Un correo que no salió y se
 * dibuja como enviado hace creer que el cliente no contestó, cuando en
 * realidad nunca le llegó nada — y eso cambia la conclusión del caso.
 */
export function esFallido(correo) {
  return correo?.direccion === 'enviado' && correo?.salio === false;
}

export function esEntrante(correo) {
  return correo?.direccion !== 'enviado';
}

/* El cuerpo completo puede ser larguísimo; se corta para la vista y se avisa
   que hay más en vez de dejar creer que eso es todo. */
export const LARGO_CUERPO = 400;

export function cuerpoRecortado(correo) {
  const cuerpo = String(correo?.cuerpo || '');
  if (cuerpo.length <= LARGO_CUERPO) return { texto: cuerpo, recortado: false };
  return { texto: cuerpo.slice(0, LARGO_CUERPO), recortado: true };
}

export function resumenCorreos(datos) {
  return {
    enviados: Number(datos?.enviados || 0),
    recibidos: Number(datos?.recibidos || 0),
    fallidos: Number(datos?.fallidos || 0),
    correos: Array.isArray(datos?.correos) ? datos.correos : [],
  };
}

/* ── Los adjuntos ────────────────────────────────────────────────────────── */

/* Lo que llegó por respuesta del cliente se marca distinto de lo que subió un
   analista: en una auditoría no es lo mismo «el cliente mandó el contrato»
   que «alguien de compliance lo adjuntó». */
export function vinoPorCorreo(adjunto) {
  return adjunto?.source === 'email_reply';
}

/* Las que el backend acepta: `_ATTACHMENT_EXTS_ALLOWED` en `api_handler.py`.
   Está repetida acá para poder avisar ANTES de subir el archivo, en vez de
   que el rechazo llegue al final de una subida de 40 MB. Manda el backend: si
   las dos listas se separan gana la de allá, y esta sólo adelanta el aviso.
   `test_sincronia.py` las compara para que no se separen en silencio. */
export const EXTENSIONES_ADJUNTO = [
  '.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx', '.xls', '.xlsx',
  '.heic', '.webp',
];

export function extensionDe(nombre) {
  const punto = String(nombre || '').lastIndexOf('.');
  return punto < 0 ? '' : String(nombre).slice(punto).toLowerCase();
}

export function adjuntoAceptado(nombre) {
  return EXTENSIONES_ADJUNTO.includes(extensionDe(nombre));
}

/**
 * Separa los archivos elegidos en los que se pueden subir y los que no.
 *
 * Devuelve las dos listas en vez de cortar en el primero que falla: si
 * alguien arrastra ocho documentos y uno tiene extensión rara, lo razonable
 * es subir los siete y decir cuál quedó afuera.
 */
export function repartirAdjuntos(archivos) {
  const suben = [];
  const rechazados = [];
  for (const a of archivos || []) {
    (adjuntoAceptado(a?.name) ? suben : rechazados).push(a);
  }
  return { suben, rechazados };
}

/* ── La whitelist desde el caso ──────────────────────────────────────────── */

export const DURACIONES_WHITELIST = [30, 60, 90];

/**
 * El cuerpo del alta de whitelist que se dispara al cerrar un caso.
 *
 * El campo de la entidad depende de si es empresa o persona, y equivocarlo
 * crea una entrada que nunca va a coincidir con nada: el cruce es exacto.
 */
export function altaDeWhitelist(caso, { dias, alcance, motivo, quien }) {
  const cuerpo = {
    entity_field: caso?.entity_type === 'company' ? 'company_id' : 'customer_id',
    entity_value: String(caso?.entity_id || ''),
    duration_days: Number(dias),
    reason: String(motivo || '').trim(),
    scope: alcance,
    created_by: quien || '',
  };
  // «Sólo este reporte» necesita saber cuál: es el que originó el caso.
  if (alcance === 'report') cuerpo.report_name = caso?.report_name || '';
  return cuerpo;
}

/** La nota que queda en el caso. Una whitelist sin rastro de por qué es justo
 *  lo que una auditoría pregunta primero. */
export function notaDeWhitelist(cuerpo) {
  const alcance = cuerpo.scope === 'report'
    ? `sólo ${cuerpo.report_name || 'el reporte del caso'}`
    : 'todas las alertas';
  return `Cliente pasado a whitelist (${cuerpo.duration_days} días, ${alcance}). `
       + `Motivo: ${cuerpo.reason}`;
}

/* ── El análisis con IA ──────────────────────────────────────────────────── */


function lista(items, vacio, formato) {
  if (!items || items.length === 0) return vacio;
  return items.map(formato).join('\n');
}

/**
 * El prompt del análisis del caso.
 *
 * Las dos reglas del final no son adorno: sin ellas el modelo rellena los
 * huecos con patrones plausibles —«estructuración», «pitufeo»— que nadie
 * observó, y eso termina copiado en la conclusión de un caso real.
 */
export function promptDelCaso({ caso, alertas, notas, contexto = '', etiquetaEstado }) {
  const alertasTexto = lista(alertas, 'Sin alertas vinculadas.',
    (a) => `- ${a.entity_value || a.entity_id || '—'}: ${a.reason || '—'} (${a.report_name || '—'})`);
  const notasTexto = lista(notas, 'Sin notas aún.',
    (n) => `[${n.author_email || 'anónimo'} ${n.created_at || ''}]: ${n.content || ''}`);

  return `Eres un analista AML/Compliance senior en Global66 (fintech LATAM de remesas internacionales).

Analiza el siguiente caso y responde:
1. **Evaluación de riesgo** (Alto/Medio/Bajo) — justificada con los DATOS de abajo, citando cifras concretas.
2. **Patrones detectados** — estructuración, layering, smurfing, pitufeo, uso de terceros, corredores inusuales, concentración o dispersión de beneficiarios, mezcla de productos. Si un patrón NO aparece en los datos, no lo menciones.
3. **Qué falta para cerrar** — documentación pendiente o preguntas concretas al cliente.
4. **Próximos pasos recomendados** — acciones concretas para el analista.

Reglas:
- Apoyate SOLO en los datos provistos. Si algo no está, decí "no hay datos de X" en vez de suponerlo.
- Las cifras que uses tienen que salir de los datos, no estimadas.

--- CASO ---
Título: ${caso?.title || '—'}
Descripción: ${caso?.description || 'Sin descripción'}
Estado: ${etiquetaEstado || caso?.status || '—'}
Prioridad: ${caso?.priority || '—'}
Entidad: ${caso?.entity_type || '—'} / ${caso?.entity_id || '—'}
Reporte origen: ${caso?.report_name || '—'}

--- ALERTAS VINCULADAS ---
${alertasTexto}

${contexto}

--- NOTAS DE INVESTIGACIÓN ---
${notasTexto}

Responde en español, estructurado y conciso.`;
}

/**
 * El bloque de contexto del cliente que se le adjunta al prompt.
 *
 * Se arma con la ficha que el analista ya trajo. Si no la trajo, se dice
 * explícitamente en vez de omitir el bloque: un prompt sin la sección hace
 * que el modelo suponga que no existe el dato; uno que dice «no se consultó»
 * le pide que lo aclare en la respuesta.
 */
export function contextoDelCliente(perfil) {
  const filas = campos(perfil);
  if (filas.length === 0) {
    return '--- FICHA DEL CLIENTE ---\nNo se consultó la ficha KYC de este cliente.';
  }
  return '--- FICHA DEL CLIENTE ---\n'
       + filas.map((f) => `${f.etiqueta}: ${f.valor}`).join('\n');
}

/* ── El contexto de compliance de un cliente ─────────────────────────────── */

/**
 * Lee `GET /customer/context`, que junta en una sola respuesta lo que el CRM
 * sabe del cliente y lo que se movió en sus cuentas.
 *
 * LO IMPORTANTE ES `transactions.available`. Cuando el cluster de Redshift
 * está pausado —lo está de 18:30 a 04:00— el backend devuelve la parte del
 * CRM igual, con la transaccional vacía. Mostrar ceros ahí hace concluir que
 * el cliente no movió plata, que es lo contrario de «no se pudo mirar».
 */
export function contextoDeCliente(datos) {
  const crm = datos?.crm || {};
  const tx = datos?.transactions || {};
  const num = (v) => Number(v || 0);
  return {
    clienteId: datos?.customer_id || '',
    dias: num(datos?.days),
    alertas: num(crm.alert_count),
    casos: num(crm.case_count),
    reportes: num(crm.distinct_reports),
    /* «Recurrente» y «combina tipologías» son banderas del CRM, no cuentas:
       significan que el cliente volvió a aparecer y que aparece por motivos
       distintos. Las dos suben el riesgo más que el volumen. */
    recurrente: Boolean(crm.recurrent),
    combinaTipologias: Boolean(crm.combines_alerts),
    transaccionalDisponible: Boolean(tx.available),
    entradas: num(tx.payin?.count),
    salidas: num(tx.payout?.count),
    montoEntradas: num(tx.payin?.total_usd),
    montoSalidas: num(tx.payout?.total_usd),
  };
}

/** Por qué no hay datos transaccionales, dicho para que no se lea como cero. */
export const SIN_TRANSACCIONAL =
  'No se pudieron leer las transacciones: el cluster de Redshift está pausado '
  + '(lo está de 18:30 a 04:00). No significa que el cliente no haya movido plata.';
