/* ============================================================================
   Administración — la lógica
   ----------------------------------------------------------------------------
   HAY DOS LISTAS DE USUARIOS Y NO SON LA MISMA.

   · `GET /users` — el CRM. Quién existe, su equipo, si está activo. Es la
     lista que llena los desplegables de «asignar a».
   · Firestore `wt_roles` — el PERFIL. Rol y módulos. Es lo que decide qué
     ve cada uno.

   Alguien puede estar en una y no en la otra, y las dos ausencias duelen
   distinto: sin perfil, la persona entra y no ve nada; sin usuario de CRM,
   nadie le puede asignar un caso. Por eso la pantalla las cruza y marca las
   dos, en vez de mostrar una sola lista que parezca completa.

   ────────────────────────────────────────────────────────────────────────
   LA REGLA QUE NO SE PUEDE ROMPER AL GUARDAR UN PERFIL
   ────────────────────────────────────────────────────────────────────────
   v1 y v2 leen y escriben la MISMA colección `wt_roles`, y manejan listas de
   módulos distintas: v1 tiene `pendientes`, `queries`, `busqueda` y
   `dashboard`, que en v2 no existen como pantallas.

   Si v2 guardara sólo las claves que conoce, editarle el equipo a alguien
   desde acá le sacaría en silencio accesos que usa en v1. Por eso al guardar
   se CONSERVAN las claves desconocidas: se tocan las que esta pantalla
   muestra y el resto viaja intacto.
   ========================================================================= */

import { GRUPOS, PANTALLAS } from '../dominio.js';

/* Los perfiles, con lo que significan. Son los mismos de v1: los dos fronts
   escriben en la misma colección y un rol tiene que querer decir lo mismo. */
export const PERFILES = [
  { clave: 'lectura', etiqueta: 'Sólo lectura',
    descripcion: 'Consulta. No puede modificar nada, y sólo ve los módulos que se le habiliten.' },
  { clave: 'analyst', etiqueta: 'Analista',
    descripcion: 'Trabaja los casos que se le asignen. Ve todos los módulos.' },
  { clave: 'admin', etiqueta: 'Administrador',
    descripcion: 'Acceso completo, incluida la configuración.' },
];

export const PERFIL_POR_CLAVE = Object.fromEntries(PERFILES.map((p) => [p.clave, p]));

export function nombrePerfil(clave) {
  if (clave === 'superadmin') return 'Super admin';
  return PERFIL_POR_CLAVE[clave]?.etiqueta || clave || '—';
}

/**
 * Los módulos que esta pantalla puede habilitar, derivados de las pantallas.
 *
 * NO es una lista aparte a propósito. v1 mantiene su propio `ALL_MODULES` y
 * eso ya se desfasó: tiene cuatro claves de pantallas que no existen. Acá se
 * calcula de `PANTALLAS`, así que una pantalla nueva trae su permiso sola.
 */
export function modulosDisponibles() {
  const vistos = new Map();
  for (const p of PANTALLAS) {
    if (!vistos.has(p.modulo)) vistos.set(p.modulo, { clave: p.modulo, pantallas: [], grupo: p.grupo });
    vistos.get(p.modulo).pantallas.push(p.titulo);
  }
  return [...vistos.values()].sort(
    (a, b) => GRUPOS.indexOf(a.grupo) - GRUPOS.indexOf(b.grupo) || a.clave.localeCompare(b.clave),
  );
}

/**
 * Prepara los módulos para guardar, conservando los que no se conocen.
 *
 * `elegidos` son las claves que la pantalla marcó; `anteriores` es lo que
 * había guardado. Todo lo que estaba y esta pantalla no muestra sigue
 * estando — es acceso que la persona usa en v1 y que acá no se ve.
 */
export function modulosParaGuardar(elegidos, anteriores) {
  const conocidos = new Set(modulosDisponibles().map((m) => m.clave));
  const ajenos = (anteriores || []).filter((m) => !conocidos.has(m) && m !== 'all');
  // `all` se respeta si estaba y sigue marcado; si no, se cae a la lista.
  const salida = [...new Set([...(elegidos || []), ...ajenos])];
  return salida;
}

/* ── El cruce de las dos listas ─────────────────────────────────────────── */

/**
 * Junta el CRM con los perfiles y marca las ausencias.
 *
 * `sinPerfil` — está en el CRM pero no tiene perfil: entra y no ve nada.
 * `sinUsuario` — tiene perfil pero no está en el CRM: ve la aplicación pero
 *   nadie le puede asignar un caso, porque no aparece en los desplegables.
 */
export function cruzar(usuariosCrm, perfiles) {
  const porCorreo = new Map();
  for (const u of usuariosCrm || []) {
    const c = (u.email || u.id || '').trim().toLowerCase();
    if (c) porCorreo.set(c, { correo: c, crm: u, perfil: null });
  }
  for (const p of perfiles || []) {
    const c = (p.email || p.id || '').trim().toLowerCase();
    if (!c) continue;
    if (porCorreo.has(c)) porCorreo.get(c).perfil = p;
    else porCorreo.set(c, { correo: c, crm: null, perfil: p });
  }
  return [...porCorreo.values()]
    .map((x) => ({
      ...x,
      nombre: x.crm?.full_name || x.perfil?.full_name || '',
      equipo: x.crm?.equipo || '',
      activo: x.crm ? x.crm.is_active !== false : null,
      rol: x.perfil?.role || '',
      modulos: x.perfil?.modules || [],
      sinPerfil: !x.perfil,
      sinUsuario: !x.crm,
    }))
    .sort((a, b) => a.correo.localeCompare(b.correo));
}

export function indicadores(filas) {
  const f = filas || [];
  return {
    total: f.length,
    conAcceso: f.filter((x) => !x.sinPerfil).length,
    sinPerfil: f.filter((x) => x.sinPerfil).length,
    sinUsuario: f.filter((x) => x.sinUsuario).length,
    soloLectura: f.filter((x) => x.rol === 'lectura').length,
    admins: f.filter((x) => x.rol === 'admin' || x.rol === 'superadmin').length,
    equipos: new Set(f.map((x) => x.equipo).filter(Boolean)).size,
  };
}

/* ── Auditoría ──────────────────────────────────────────────────────────── */

/* Los verbos de las acciones, para leerlas sin descifrar `case.status_change`.
   Una acción que no esté acá se muestra cruda: mejor un nombre técnico que
   una celda vacía. */
export const ACCIONES_ES = {
  'case.create': 'Creó un caso',
  'case.status_change': 'Cambió el estado de un caso',
  'case.note_add': 'Agregó una nota',
  'case.delete': 'Borró un caso',
  'case.assign': 'Asignó un caso',
  'case.take': 'Tomó un caso',
  'case.client_profile': 'Consultó el perfil del cliente',
  'case.email_reply_attachments': 'Respondió un correo con adjuntos',
  'case.email_reply_no_attachment': 'Respondió un correo',
  'alert.review': 'Marcó una alerta como revisada',
  'alert.assign': 'Asignó una alerta',
  'alert.bulk_distribute': 'Repartió alertas en lote',
  'alert.link_case': 'Ató una alerta a un caso',
  'cliente.ficha_pdf': 'Descargó la ficha de un cliente',
  'embargos.ejecutar': 'Ejecutó un embargo',
  'update_user': 'Modificó un usuario',
  'create_user': 'Creó un usuario',
  'delete_user': 'Borró un usuario',
  'whitelist.add': 'Agregó a la lista blanca',
  'whitelist.remove': 'Quitó de la lista blanca',
};

export function accionEs(clave) {
  return ACCIONES_ES[clave] || clave || '—';
}

/* El tipo de entidad, en castellano. */
export const ENTIDADES_ES = {
  case: 'Caso', alert: 'Alerta', user: 'Usuario',
  customer: 'Cliente', embargo: 'Embargo', whitelist: 'Lista blanca',
};

export function entidadEs(clave) {
  return ENTIDADES_ES[clave] || clave || '—';
}

/**
 * Las acciones que MODIFICAN algo, separadas de las que sólo consultan.
 *
 * En una auditoría no pesan igual: «descargó la ficha» y «borró un caso»
 * están en la misma lista y con el mismo aspecto, y si hay que revisar qué
 * pasó un día, lo primero que se busca son los cambios.
 */
const SOLO_LECTURA = ['cliente.ficha_pdf', 'case.client_profile'];

export function esCambio(entrada) {
  return !SOLO_LECTURA.includes(entrada?.action);
}

export function resumenAuditoria(entradas) {
  const e = entradas || [];
  return {
    total: e.length,
    cambios: e.filter(esCambio).length,
    personas: new Set(e.map((x) => x.user_email).filter(Boolean)).size,
    entidades: new Set(e.map((x) => x.entity_type).filter(Boolean)).size,
  };
}

/* ── Cluster ────────────────────────────────────────────────────────────── */

/* Los estados que devuelve Redshift. `paused` es lo normal fuera de horario:
   el cluster se apaga solo de 18:30 a 04:00 para no cobrar de noche. */
export const ESTADOS_CLUSTER = {
  available: { etiqueta: 'Disponible', color: 'var(--nivel-bajo-texto)',
               fondo: 'var(--nivel-bajo-tenue)', consulta: true },
  paused:    { etiqueta: 'Pausado', color: 'var(--texto-mute)',
               fondo: 'var(--superficie-3)', consulta: false },
  resuming:  { etiqueta: 'Despertando', color: 'var(--nivel-alto-texto)',
               fondo: 'var(--nivel-alto-tenue)', consulta: false },
  pausing:   { etiqueta: 'Pausándose', color: 'var(--nivel-alto-texto)',
               fondo: 'var(--nivel-alto-tenue)', consulta: false },
  modifying: { etiqueta: 'Modificándose', color: 'var(--nivel-alto-texto)',
               fondo: 'var(--nivel-alto-tenue)', consulta: false },
};

export function estadoCluster(status) {
  return ESTADOS_CLUSTER[String(status || '').toLowerCase()] || null;
}

/** Si el cluster está en movimiento y conviene volver a preguntar. */
export function clusterEnMovimiento(status) {
  const s = String(status || '').toLowerCase();
  return s === 'resuming' || s === 'pausing' || s === 'modifying';
}
