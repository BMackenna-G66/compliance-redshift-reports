/* ============================================================================
   Mantenedor de cuentas internas
   ----------------------------------------------------------------------------
   «¿De quién es esta cuenta?» es de las preguntas más repetidas del área:
   llega un IBAN en un requerimiento y hay que decir a qué cliente, moneda,
   instancia y branch corresponde, y si sigue activa. Hasta hoy era abrir un
   cliente SQL y cambiar dos valores a mano.

   ACÁ SÓLO VIVE LO QUE SE PUEDE PROBAR SIN NAVEGADOR: qué campos se pueden
   editar, cómo se arma la consulta, y cómo se lee cada columna. El dibujo
   está en la pantalla.

   LOS CAMPOS VACÍOS NO VIAJAN. Mandar `moneda=` no es «cualquier moneda»
   para un backend que sólo mira si la clave está: es la diferencia entre
   buscar una cuenta y listar la tabla entera.
   ========================================================================= */

/* Los mismos cuatro que acepta el backend (`CUENTAS_FILTROS`). Si acá se
   agrega uno que allá no está, se ignora en silencio — por eso hay un test
   que compara las dos listas. */
export const CAMPOS_CUENTA = [
  { clave: 'cuenta', etiqueta: 'Número de cuenta', ejemplo: 'GB00TCCL00000000000000' },
  { clave: 'moneda', etiqueta: 'Moneda', ejemplo: 'EUR' },
  { clave: 'wallet', etiqueta: 'Wallet', ejemplo: 'CL-XXXX-0000' },
  { clave: 'customer_id', etiqueta: 'Id de cliente', ejemplo: '1234567' },
];

export const FORMULARIO_VACIO = Object.fromEntries(
  CAMPOS_CUENTA.map((c) => [c.clave, '']),
);

/** ¿Hay con qué buscar? Sin ningún filtro el backend rechaza el pedido, así
 *  que el botón se apaga antes en vez de mostrar un error evitable. */
export function hayFiltro(form) {
  return CAMPOS_CUENTA.some((c) => String(form?.[c.clave] || '').trim() !== '');
}

/* La ruta va en su propia constante y no pegada a la query string. Además de
   leerse mejor, es lo que ve el guardián de paridad: escrita como
   `` `/search/accounts?${...}` `` el literal queda escondido detrás del `?` y
   el test reporta que v2 perdió la función. */
export const RUTA_CUENTAS = '/search/accounts';

/** La query string, con los campos vacíos afuera. */
export function consulta(form, limite = 200) {
  const p = new URLSearchParams();
  for (const c of CAMPOS_CUENTA) {
    const v = String(form?.[c.clave] || '').trim();
    if (v) p.set(c.clave, v);
  }
  p.set('limit', String(limite));
  return `${RUTA_CUENTAS}?${p.toString()}`;
}

/** Un resumen de sobre qué se buscó, para que la tabla no quede huérfana:
 *  una tabla sin decir de qué consulta salió es cómo alguien pega un
 *  resultado viejo en un informe nuevo. */
export function resumenFiltros(filtros) {
  const etiqueta = Object.fromEntries(CAMPOS_CUENTA.map((c) => [c.clave, c.etiqueta]));
  return Object.entries(filtros || {})
    .map(([k, v]) => `${etiqueta[k] || k}: ${v}`)
    .join(' · ');
}

/* `is_client_main` vuelve como '0'/'1' y no como booleano. Mostrarlo crudo
   obliga a recordar cuál es cuál, y es justo la columna que decide si una
   cuenta es la principal del cliente. */
export function principal(v) {
  const s = String(v ?? '').trim().toLowerCase();
  if (s === '1' || s === 'true' || s === 't') return 'Sí';
  if (s === '0' || s === 'false' || s === 'f') return 'No';
  return s ? v : '—';
}

export function momento(v) {
  if (!v) return '—';
  const d = new Date(String(v).replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('es-CL');
}

export const COLUMNAS_CUENTA = [
  { clave: 'cuenta', titulo: 'Cuenta', tipo: 'mono', ancho: '16%' },
  { clave: 'tipo_cuenta', titulo: 'Tipo', ancho: '9%' },
  { clave: 'wallet', titulo: 'Wallet', tipo: 'mono', ancho: '10%' },
  { clave: 'moneda', titulo: 'Moneda', ancho: '6%' },
  { clave: 'customer_id', titulo: 'Cliente', tipo: 'mono', ancho: '8%' },
  { clave: 'correo', titulo: 'Correo', ancho: '15%' },
  { clave: 'instancia', titulo: 'Instancia', ancho: '9%' },
  { clave: 'branch', titulo: 'Branch', ancho: '8%' },
  { clave: 'segmento', titulo: 'B2C/B2B', ancho: '6%' },
  {
    clave: 'principal',
    titulo: 'Principal',
    ancho: '6%',
    render: (r) => principal(r.principal),
    exportar: (r) => principal(r.principal),
  },
  { clave: 'estado', titulo: 'Estado', ancho: '7%' },
  {
    clave: 'creada',
    titulo: 'Creada',
    ancho: '10%',
    render: (r) => momento(r.creada),
    exportar: (r) => momento(r.creada),
  },
  {
    clave: 'modificada',
    titulo: 'Modificada',
    ancho: '10%',
    render: (r) => momento(r.modificada),
    exportar: (r) => momento(r.modificada),
  },
];
