/* ============================================================================
   El JSON del ROS, como formulario
   ----------------------------------------------------------------------------
   GEREO devuelve un documento con la forma exacta que espera el formulario del
   regulador. El analista tiene que poder corregir VALORES —un monto mal leído,
   un nombre con un typo— sin tocar la estructura.

   LO QUE ESTE ARCHIVO CUIDA, y es todo el punto: que un número siga siendo un
   número. Un `<input>` devuelve texto SIEMPRE. Si se guardara tal cual, el
   monto 1000 se volvería "1000" y el backend rechazaría la edición entera por
   cambio de tipo — y si el backend no la rechazara, GEREO recibiría un
   documento deforme y el reporte entraría mal al regulador.

   Por eso `escribir()` convierte de vuelta al tipo que tenía el campo, y hay
   tests de cada caso. El control del backend es la red; esto es no caerse.

   NO SE AGREGAN NI SE QUITAN CAMPOS. Tampoco elementos de una lista: agregar
   un reportado no es editar un valor, cambia lo que el regulador va a recibir.
   Para eso se pide otra generación a GEREO.
   ========================================================================= */

/** El tipo a efectos del formulario. Espeja `_tipo()` de `ros_versiones.py`. */
export function tipoDe(valor) {
  if (valor === null || valor === undefined) return 'nulo';
  if (typeof valor === 'boolean') return 'bool';
  if (typeof valor === 'number') return 'numero';
  if (typeof valor === 'string') return 'texto';
  if (Array.isArray(valor)) return 'lista';
  if (typeof valor === 'object') return 'objeto';
  return 'texto';
}

/**
 * La etiqueta legible de una clave.
 *
 * Las claves de GEREO vienen numeradas (`1_descripcion_hechos_orden_cronologico`)
 * porque el número es el orden del formulario del regulador. Se saca para
 * mostrar y se conserva para guardar: el orden ya lo da la posición.
 */
export function etiqueta(clave) {
  const limpia = String(clave || '').replace(/^\d+_/, '').replace(/_/g, ' ').trim();
  if (!limpia) return String(clave || '');
  return limpia.charAt(0).toUpperCase() + limpia.slice(1);
}

/** Un texto largo se dibuja como área y no como línea. */
export function esTextoLargo(valor) {
  return typeof valor === 'string' && (valor.length > 120 || valor.includes('\n'));
}

/**
 * Los campos de un contenido, aplanados, en orden.
 *
 * Devuelve `{ruta, clave, etiqueta, tipo, valor}` por hoja. La ruta usa la
 * misma notación que el backend (`a.b[0].c`) para que un error de estructura
 * se pueda señalar en el campo exacto.
 */
export function campos(valor, prefijo = '') {
  const tipo = tipoDe(valor);
  if (tipo === 'objeto') {
    return Object.entries(valor).flatMap(([k, v]) =>
      campos(v, prefijo ? `${prefijo}.${k}` : k));
  }
  if (tipo === 'lista') {
    if (valor.length === 0) {
      return [{ ruta: prefijo, clave: ultimaClave(prefijo), etiqueta: etiqueta(ultimaClave(prefijo)), tipo: 'lista_vacia', valor }];
    }
    return valor.flatMap((v, i) => campos(v, `${prefijo}[${i}]`));
  }
  const clave = ultimaClave(prefijo);
  return [{ ruta: prefijo, clave, etiqueta: etiqueta(clave), tipo, valor }];
}

function ultimaClave(ruta) {
  const partes = String(ruta || '').split('.');
  return partes[partes.length - 1] || ruta;
}

function trozos(ruta) {
  // `a.b[0].c` → ['a', 'b', 0, 'c']
  const fuera = [];
  for (const parte of String(ruta).split('.')) {
    const m = /^([^[\]]*)((?:\[\d+\])*)$/.exec(parte);
    if (!m) { fuera.push(parte); continue; }
    if (m[1]) fuera.push(m[1]);
    for (const i of m[2].match(/\d+/g) || []) fuera.push(Number(i));
  }
  return fuera;
}

/** El valor que hay en esa ruta. */
export function leer(obj, ruta) {
  let actual = obj;
  for (const t of trozos(ruta)) {
    if (actual === null || actual === undefined) return undefined;
    actual = actual[t];
  }
  return actual;
}

/**
 * Convierte lo que devolvió el control al tipo que tenía el campo.
 *
 * Un `<input>` devuelve texto siempre. Sin esto, el 1000 de un monto se
 * guardaría como "1000" y la edición entera se rechazaría por cambio de tipo.
 */
export function coaccionar(valorOriginal, crudo) {
  const tipo = tipoDe(valorOriginal);
  if (tipo === 'bool') return Boolean(crudo);
  if (tipo === 'numero') {
    // Devuelve NaN si no se puede leer, y el llamador MARCA EL CAMPO EN ERROR
    // y bloquea el guardado. No se vuelve al valor anterior en silencio: eso
    // le haría creer a alguien que guardó una corrección que no se guardó.
    return parsearNumero(crudo);
  }
  // `nulo` se puede llenar con texto, y vaciarlo lo devuelve a nulo: los dos
  // lados lo aceptan, por eso el backend lo trata como comodín.
  if (tipo === 'nulo') return crudo === '' ? null : crudo;
  return crudo === null || crudo === undefined ? '' : String(crudo);
}

/**
 * Una copia con esa ruta cambiada. NO muta el original.
 *
 * Copia sólo el camino tocado: el resto se comparte, que es lo que hace que
 * editar un campo en un documento grande no reconstruya todo el árbol.
 */
export function escribir(obj, ruta, valor) {
  const camino = trozos(ruta);
  if (camino.length === 0) return valor;

  const copiar = (actual, i) => {
    const t = camino[i];
    const ultimo = i === camino.length - 1;
    if (Array.isArray(actual)) {
      const salida = actual.slice();
      salida[t] = ultimo ? valor : copiar(actual[t], i + 1);
      return salida;
    }
    const salida = { ...(actual || {}) };
    salida[t] = ultimo ? valor : copiar((actual || {})[t], i + 1);
    return salida;
  };
  return copiar(obj, 0);
}

/**
 * Lo que se le manda al backend: `{clave_de_seccion: contenido}`.
 *
 * Van TODAS las secciones y no sólo las tocadas. El backend compara la forma
 * del documento completo contra la versión anterior, y mandar media parte
 * haría que lo no enviado se lea como faltante.
 */
export function cuerpoDeGuardado(secciones, borradores, versionActual) {
  const fuera = {};
  for (const s of secciones || []) {
    fuera[s.clave] = Object.prototype.hasOwnProperty.call(borradores, s.clave)
      ? borradores[s.clave]
      : s.contenido;
  }
  return { secciones: fuera, sobre_version: versionActual };
}


/* ── Los números, en castellano ───────────────────────────────────────────
   LOS TRES PAÍSES ESCRIBEN CON PUNTO DE MILES Y COMA DECIMAL. `Number()` lee
   el punto como decimal, y eso ya corrompió montos: «12.500» se guardaba como
   12,5 — un monto dividido por mil entrando a un reporte al regulador— y
   «1.234.567» se descartaba sin aviso. Tipeando tecla por tecla el punto se
   come solo y por casualidad daba bien; pegando, no. Y los montos se pegan.

   Por eso el valor se MUESTRA con el mismo formato con el que se lee: si
   GEREO devuelve 1000.5 y la pantalla escribe «1000.5», al tocar ese campo se
   volvería 10005.                                                          */

const SIN_PUNTOS = /^-?\d+(,\d+)?$/;
const CON_MILES = /^-?\d{1,3}(\.\d{3})+(,\d+)?$/;

/** Un número escrito en castellano → número. `NaN` si no se puede leer. */
export function parsearNumero(texto) {
  if (typeof texto === 'number') return Number.isFinite(texto) ? texto : NaN;
  // El espacio duro entra pegando desde Excel o desde un PDF.
  const limpio = String(texto ?? '').trim().replace(/[$\s\u00a0]/g, '');
  if (limpio === '') return NaN;
  // Un punto que NO forma grupos de miles —«1.23»— es ambiguo: puede ser un
  // decimal mal escrito o un miles mal escrito. Se marca error y lo resuelve
  // una persona, en vez de que el sistema elija por ella.
  const valido = limpio.includes('.') ? CON_MILES.test(limpio)
                                      : SIN_PUNTOS.test(limpio);
  if (!valido) return NaN;
  const n = Number(limpio.replace(/\./g, '').replace(',', '.'));
  return Number.isFinite(n) ? n : NaN;
}

/** Número → como se escribe acá. Es la vuelta exacta de `parsearNumero`. */
export function formatearNumero(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '';
  return new Intl.NumberFormat('es-CL', { maximumFractionDigits: 20 }).format(n);
}

/** Cómo se muestra un valor en su campo. */
export function paraMostrar(valor) {
  if (tipoDe(valor) === 'numero') return formatearNumero(valor);
  return valor ?? '';
}
