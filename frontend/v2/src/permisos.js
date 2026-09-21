/* ============================================================================
   Permisos
   ----------------------------------------------------------------------------
   La misma semántica que v1, a propósito. Los dos fronts van a convivir
   mientras v2 se construye, y un perfil tiene que significar exactamente lo
   mismo en los dos: si acá un `lectura` viera una pestaña que en v1 no ve,
   nadie sabría cuál de los dos está bien.

   Este archivo no importa React ni Firebase. Es lógica pura para que se pueda
   testear sin navegador — y para que el control de sólo lectura, que es lo que
   le estamos dando a CX, tenga tests de verdad.
   ========================================================================= */

export const SUPER_ADMIN = 'benjamin.mackenna@global66.com';

/* El perfil de quien nunca se pudo consultar. Es el MÁS restrictivo a
   propósito: en v1 esto llegó a ser acceso total "para que nada se rompa", y
   con un perfil de sólo lectura eso es justo lo contrario — un hipo de
   Firestore le abría el sistema entero a quien sólo puede consultar. */
export const PERFIL_MINIMO = { rol: 'lectura', modulos: ['dashboard'] };

/* Lo que recibe un usuario nuevo la primera vez. Igual que v1. */
export const PERFIL_NUEVO = {
  rol: 'analyst',
  modulos: ['dashboard', 'alertas', 'historial', 'alertados', 'aml_individual'],
};

export function esAdmin(perfil) {
  return perfil?.rol === 'superadmin' || perfil?.rol === 'admin';
}

/** El perfil de consulta: ve, no toca. */
export function soloLectura(perfil) {
  return perfil?.rol === 'lectura';
}

/**
 * Si este perfil ve esta pantalla.
 *
 * OJO CON ESTO, QUE NO ES OBVIO: sólo restringe al perfil de lectura.
 *
 * En v1, 13 de las 14 pestañas nunca miraron los permisos de módulo, así que
 * los perfiles que ya existen tienen listas de módulos que no las nombran.
 * Aplicarles la restricción de golpe les sacaría accesos que usan todos los
 * días. Se aprieta cuando la autenticación sea real y se pueda revisar perfil
 * por perfil; hoy sería romperle el trabajo al equipo para habilitar a CX.
 */
export function verModulo(perfil, modulo) {
  if (perfil?.rol === 'superadmin') return true;
  if (soloLectura(perfil)) return tieneModulo(perfil, modulo);
  return true;
}

/** Si el módulo está en la lista del perfil, sin la excepción de arriba. */
export function tieneModulo(perfil, modulo) {
  if (perfil?.rol === 'superadmin') return true;
  const m = perfil?.modulos || [];
  return m.includes('all') || m.includes(modulo);
}

/* ── El perfil recordado ─────────────────────────────────────────────────────
   Por si Firestore no contesta. Es una comodidad para no dejar a nadie afuera
   por una caída, NO un control: el control de verdad va del lado del servidor.
   Cualquiera puede editar su localStorage; lo único que gana es ver pantallas
   vacías, porque los datos igual los sirve la API. */

const LLAVE = 'wt_perfil_v2';

export function perfilRecordado(almacen = globalThis.localStorage) {
  try {
    const crudo = almacen?.getItem(LLAVE);
    if (!crudo) return PERFIL_MINIMO;
    const d = JSON.parse(crudo);
    if (!d || typeof d.rol !== 'string' || !d.rol) return PERFIL_MINIMO;
    return { rol: d.rol, modulos: Array.isArray(d.modulos) ? d.modulos : ['dashboard'] };
  } catch {
    return PERFIL_MINIMO;
  }
}

export function recordarPerfil(perfil, almacen = globalThis.localStorage) {
  try {
    almacen?.setItem(LLAVE, JSON.stringify({ rol: perfil.rol, modulos: perfil.modulos }));
  } catch {
    /* Navegador con el almacenamiento bloqueado. No es motivo para romper. */
  }
}

/** Las pantallas que este perfil ve, agrupadas para el menú.
 *
 *  Deja fuera las de detalle (`enMenu: false`): existen como ruta y tienen su
 *  permiso, pero sin un id no tienen nada que mostrar. */
export function menuPara(perfil, pantallas, grupos) {
  return grupos
    .map((grupo) => ({
      grupo,
      pantallas: pantallas.filter(
        (p) => p.grupo === grupo && p.enMenu !== false && verModulo(perfil, p.modulo),
      ),
    }))
    .filter((g) => g.pantallas.length > 0);
}
