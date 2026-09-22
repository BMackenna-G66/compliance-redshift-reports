/* ============================================================================
   El análisis individual, de punta a punta
   ----------------------------------------------------------------------------
   Cuatro pasos encadenados, y el encadenado es el punto: cada uno le pasa al
   siguiente los identificadores que encontró, para no tener que copiarlos a
   mano de una planilla a otra.

     1. Extracción de casos — se importa el reporte de Salesforce y se sacan
        los IDs de cliente y los números de remesa.
     2. Búsqueda de remesas — esos números se buscan en Redshift.
     3. Análisis AML — esos IDs pasan por el motor de puntaje.
     4. Conclusión — se cruzan los dos resultados y sale la planilla final.

   ACÁ VIVE LO QUE SE PUEDE PROBAR: el parseo del archivo, el reparto de
   identificadores y el cruce del paso 4. Todo eso hoy en v1 vive dentro de la
   pantalla, y su forma de fallar es devolver una planilla con columnas vacías
   sin decir por qué.
   ========================================================================= */

/* ── Paso 1: el reporte de Salesforce ────────────────────────────────────── */

/* Salesforce exporta un .xls que en realidad es HTML, y lo escribe en
   ISO-8859-1. Leerlo como UTF-8 convierte cada acento en un rombo, y los
   nombres de cuenta terminan en la planilla final así. */
export const CODIFICACION_SALESFORCE = 'iso-8859-1';

/* Las columnas del reporte, por posición. Salesforce no manda encabezados
   fiables, así que se cuenta: 0 propietario · 1 nombre de cuenta · 2 asunto ·
   3 fecha/hora · 4 antigüedad · 5 cerrado · 6 N° de caso · 7 ID interno. */
const COL = { cuenta: 1, asunto: 2, fecha: 3, caso: 6, id: 7 };
const MINIMO_CELDAS = 8;

/* El número de remesa viene incrustado en el asunto: «TX  12345678  POR …»,
   con una cantidad variable de espacios. */
const REMESA_EN_ASUNTO = /TX\s+(\d+)\s+POR/i;

/**
 * Saca las filas del reporte de Salesforce.
 *
 * `documento` es un `Document` ya parseado: el parseo de HTML lo hace el
 * navegador y este módulo se queda con la interpretación, que es la parte que
 * se puede probar.
 */
export function filasDeSalesforce(documento) {
  const filas = Array.from(documento?.querySelectorAll('table tr') || []).slice(1);
  const salida = [];
  for (const fila of filas) {
    const celdas = fila.querySelectorAll('td');
    if (celdas.length < MINIMO_CELDAS) continue;
    const texto = (i) => (celdas[i]?.textContent || '').trim();
    const idInterno = texto(COL.id);
    // Una fila sin ID interno no sirve para nada aguas abajo: no se puede
    // buscar ni cruzar. Se descarta en vez de arrastrar una fila fantasma.
    if (!idInterno) continue;
    const asunto = texto(COL.asunto);
    salida.push({
      nombre_cuenta: texto(COL.cuenta),
      asunto,
      fecha_hora: texto(COL.fecha),
      numero_caso: texto(COL.caso),
      id_interno: idInterno,
      remesa: (asunto.match(REMESA_EN_ASUNTO) || [])[1] || '',
    });
  }
  return salida;
}

/** Los identificadores únicos que el paso 1 le pasa al 3. */
export function idsDeCasos(filas) {
  return [...new Set((filas || []).map((f) => f.id_interno).filter(Boolean))];
}

/** Las remesas únicas que el paso 1 le pasa al 2. */
export function remesasDeCasos(filas) {
  return [...new Set((filas || []).map((f) => f.remesa).filter(Boolean))];
}

/* ── Los identificadores pegados a mano ──────────────────────────────────── */

/* El tope del backend. Más que esto y la consulta no entra en los 30 segundos
   de API Gateway. */
export const TOPE_IDS = 5000;

/**
 * Parte una lista pegada a mano en identificadores.
 *
 * Se acepta cualquier separador —coma, punto y coma, salto de línea, espacio—
 * porque lo que se pega viene de un Excel, de un Slack o de un correo, y
 * obligar a un formato hace que la gente lo arregle a mano y se equivoque.
 */
export function partirIds(texto, { soloNumeros = false } = {}) {
  const crudos = String(texto || '').split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
  const ids = soloNumeros ? crudos.filter((s) => /^\d+$/.test(s)) : crudos;
  const descartados = crudos.length - ids.length;
  return { ids: [...new Set(ids)], descartados, crudos: crudos.length };
}

/**
 * Qué impide lanzar la búsqueda. Devuelve el mensaje, o cadena vacía si va.
 */
export function problemaConLosIds({ ids, crudos, descartados }, que = 'identificadores') {
  if (crudos === 0) return `Pegá los ${que} que querés buscar.`;
  if (ids.length === 0) {
    return `Ninguno de los ${crudos} valores pegados parece un ${que.replace(/e?s$/, '')} válido.`;
  }
  if (ids.length > TOPE_IDS) {
    return `Son ${ids.length.toLocaleString('es-CL')} ${que}: el máximo por búsqueda es `
         + `${TOPE_IDS.toLocaleString('es-CL')}. Partilo en tandas.`;
  }
  // No es un impedimento, pero hay que decirlo: descartar en silencio hace
  // que alguien busque 300 y reciba 280 sin enterarse.
  if (descartados > 0) {
    return '';
  }
  return '';
}

/** El aviso de lo que se descartó, que no impide buscar pero hay que decir. */
export function avisoDeDescartes({ ids, crudos, descartados }) {
  if (!descartados) {
    return crudos > ids.length ? `${crudos - ids.length} repetido(s) se unificaron.` : '';
  }
  return `${descartados} de ${crudos} valores no tienen forma de identificador y quedaron afuera.`;
}

/* ── Paso 4: el cruce ────────────────────────────────────────────────────── */

/* Los nombres de columna del archivo del motor de análisis. Son literales con
   acentos y espacios porque así los escribe el motor; cambiarlos acá rompe el
   cruce en silencio y la planilla sale con las columnas vacías. */
const COL_MOTOR = {
  dni: 'IDENTIDAD (DNI/RUT)',
  accion: 'Acción Manual',
  sugerencia: 'Sugerencia Motor',
  pep: 'Es PEP',
  score: 'Score Acumulado',
  nombre: 'Nombre Completo',
  gravedad: 'Gravedad Máx',
  delitos: 'Cant. Delitos',
};

/* Los dos valores que emite el backend: el CASE de `_SQL_REMESA_SEARCH` en
   `api_handler.py` devuelve «Envío nacional» o «Envío internacional». */
export const ENVIO_NACIONAL = 'Envío nacional';
export const ENVIO_INTERNACIONAL = 'Envío internacional';

/**
 * Si la transacción es nacional.
 *
 * SE DESCARTA «internacional» PRIMERO, y ese orden es todo el asunto: v1 hacía
 * `tipo_envio.toLowerCase().includes('nacional')`, y «envío internacional»
 * CONTIENE «nacional». El resultado es que todas las internacionales se
 * clasificaban como nacionales: la hoja «Internacionales» salía siempre vacía
 * y las internacionales terminaban en la otra con las columnas del motor en
 * blanco, indistinguibles de una nacional que no cruzó.
 *
 * Se compara por contenido y no por igualdad exacta para que un cambio de
 * mayúsculas o un espacio de más en el SQL no rompa la clasificación en
 * silencio; el test de sincronía vigila que los literales sigan siendo esos.
 */
export function esNacional(tx) {
  const t = String(tx?.tipo_envio || '').toLowerCase();
  if (t.includes('internacional')) return false;
  return t.includes('nacional');
}

/**
 * Cruza las transacciones del paso 2 con el análisis del paso 3.
 *
 * NACIONALES E INTERNACIONALES VAN SEPARADAS porque sólo las nacionales
 * tienen DNI de beneficiario, que es la única llave contra el motor. Mezclarlas
 * daría una planilla donde la mitad de las filas tiene las columnas del motor
 * vacías y no se sabe si es porque no se encontró o porque no aplica.
 *
 * Se devuelve además cuántas cruzaron y cuántas no: una tasa de cruce baja
 * casi siempre significa que los dos archivos son de tandas distintas, y sin
 * el número eso se descubre leyendo la planilla fila por fila.
 */
export function cruzar({ transacciones, analisis, casos }) {
  const porDni = new Map();
  for (const fila of analisis || []) {
    const dni = String(fila?.[COL_MOTOR.dni] ?? '').trim();
    if (dni) porDni.set(dni, fila);
  }

  const casoPorRemesa = new Map();
  for (const c of casos || []) {
    if (c?.remesa) casoPorRemesa.set(String(c.remesa).trim(), c.numero_caso);
  }

  const nacionales = [];
  const internacionales = [];
  let cruzadas = 0;
  let sinCruzar = 0;

  for (const tx of transacciones || []) {
    const noCaso = casoPorRemesa.get(String(tx?.transaction_id ?? '').trim()) || '';
    const comun = {
      'N° Caso': noCaso,
      transaction_id: tx?.transaction_id,
      customer_id: tx?.customer_id,
      tipo_envio: tx?.tipo_envio,
      beneficiary_country: tx?.beneficiary_country_name,
      beneficiary_dni: tx?.beneficiary_dni,
      beneficiary_name: tx?.beneficiary_name,
      beneficiary_firstname: tx?.beneficiary_first_name,
      beneficiary_lastname: tx?.beneficiary_last_name,
      beneficiary_email: tx?.beneficiary_email,
      destiny_country: tx?.destiny_country,
      destiny_amount_usd: tx?.destiny_amount_usd,
      tx_status: tx?.tx_status,
      start_date: tx?.start_date,
    };

    if (esNacional(tx)) {
      const m = porDni.get(String(tx?.beneficiary_dni ?? '').trim());
      if (m) cruzadas += 1; else sinCruzar += 1;
      nacionales.push({
        ...comun,
        'Acción Manual': m?.[COL_MOTOR.accion] ?? '',
        'Sugerencia Motor': m?.[COL_MOTOR.sugerencia] ?? '',
        'Es PEP': m?.[COL_MOTOR.pep] ?? '',
        'Score Acumulado': m?.[COL_MOTOR.score] ?? '',
        'Nombre Completo Motor': m?.[COL_MOTOR.nombre] ?? '',
        'Gravedad Máx': m?.[COL_MOTOR.gravedad] ?? '',
        'Cant. Delitos': m?.[COL_MOTOR.delitos] ?? '',
      });
    } else {
      internacionales.push({
        ...comun,
        beneficiary_id: tx?.beneficiary_id,
        origin_country: tx?.origin_country,
      });
    }
  }

  return { nacionales, internacionales, cruzadas, sinCruzar };
}

/** Lo que el paso 4 cuenta de sí mismo, para mostrarlo antes de descargar. */
export function resumenDelCruce(r) {
  const nac = r.nacionales.length;
  const tasa = nac ? Math.round((r.cruzadas * 100) / nac) : 0;
  return {
    nacionales: nac,
    internacionales: r.internacionales.length,
    cruzadas: r.cruzadas,
    sinCruzar: r.sinCruzar,
    tasa,
    // Debajo de la mitad casi siempre son dos tandas distintas. Decirlo antes
    // de descargar ahorra revisar la planilla fila por fila.
    sospechoso: nac > 0 && tasa < 50,
  };
}
