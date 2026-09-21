/* ============================================================================
   La capa de API
   ----------------------------------------------------------------------------
   UN SOLO PUNTO DE ENTRADA. En v1 hay ~75 llamadas repartidas por un archivo
   de 13.600 líneas, y cada vez que hubo que cambiar algo transversal —el
   manejo de error, el corte de sólo lectura— hubo que confiar en haberlas
   encontrado todas. Acá pasa todo por `pedir()`.

   POR QUÉ NO VA EL HEADER `Authorization`. No es un olvido. La API Gateway
   tiene `AllowHeaders: ["content-type"]` y nada más; mandar `Authorization`
   hace fallar el preflight y la llamada nunca sale. Cambiarlo necesita
   `apigateway:PATCH`, que el rol `compliance-admin` no tiene. Hasta que
   alguien con ese permiso lo agregue, la autenticación la hace Firebase del
   lado del navegador y la API confía en `actor_email` — que es falsificable.
   Está anotado como pendiente en PLAN.md; no lo arregla este archivo.
   ========================================================================= */

import { soloLectura } from './permisos.js';

export class ErrorApi extends Error {
  constructor(mensaje, { status = 0, codigo = '' } = {}) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.status = status;
    this.codigo = codigo;
  }
}

/* El mensaje del corte de sólo lectura, en un solo lugar para que diga lo
   mismo en la consola y en la pantalla. */
export const MENSAJE_SOLO_LECTURA =
  'Tu perfil es de sólo lectura: no podés modificar información.';

function esLectura(metodo) {
  return String(metodo).toUpperCase() === 'GET';
}

/**
 * Crea el cliente. Se arma una vez, cuando ya se sabe la URL y quién entró.
 *
 * `perfil` se pasa como función y no como valor porque el perfil llega
 * después del primer render (Firestore tarda) y cambia si el usuario se
 * vuelve a loguear. Guardando el valor, el cliente se quedaría con el perfil
 * mínimo para siempre — y con ese, todo lo que escribe queda bloqueado.
 */
export function crearApi({ base, perfil, email }) {
  const raiz = String(base || '').replace(/\/$/, '');

  async function pedir(metodo, ruta, cuerpo = null, { crudo = false } = {}) {
    // El corte. Acá y no botón por botón: son 72 endpoints que escriben, y
    // esconder los controles de a uno garantiza que tarde o temprano se
    // escape alguno. Esconder el botón es cortesía; el control está acá.
    if (!esLectura(metodo) && soloLectura(perfil())) {
      console.warn('[solo-lectura] bloqueado', metodo, ruta);
      const err = new ErrorApi(MENSAJE_SOLO_LECTURA, { status: 403, codigo: 'solo_lectura' });
      if (crudo) return { ok: false, status: 403, datos: { error: 'solo_lectura' }, error: err };
      throw err;
    }

    let r;
    try {
      const opts = {
        method: metodo,
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json' },
      };
      if (cuerpo) {
        // La API identifica a quien actúa por este campo. Ponerlo acá y no en
        // cada llamada es la única forma de que no se olvide en una — que ya
        // pasó: una nota quedó guardada sin autor porque el campo viajaba con
        // otro nombre.
        opts.body = JSON.stringify({ actor_email: email() || '', ...cuerpo });
      }
      r = await fetch(raiz + ruta, opts);
    } catch {
      const err = new ErrorApi('Error de red al conectar con la API.', { status: 0, codigo: 'red' });
      if (crudo) return { ok: false, status: 0, datos: { error: err.message }, error: err };
      throw err;
    }

    const datos = await r.json().catch(() => ({}));

    if (crudo) return { ok: r.ok, status: r.status, datos };

    if (r.status === 401) {
      throw new ErrorApi('Sesión expirada — volvé a iniciar sesión.', { status: 401, codigo: 'sesion' });
    }
    if (!r.ok) {
      throw new ErrorApi(datos?.error || `Error ${r.status}`, { status: r.status });
    }
    return datos;
  }

  return {
    get: (ruta) => pedir('GET', ruta),
    post: (ruta, cuerpo) => pedir('POST', ruta, cuerpo),
    del: (ruta, cuerpo) => pedir('DELETE', ruta, cuerpo),

    /* Igual que los de arriba pero devuelve `{ok, status, datos}` sin lanzar.
       Hace falta cuando quien llama tiene que reaccionar a un status puntual
       —el 409 de "ese caso ya lo tomó otro", por ejemplo— en vez de sólo
       mostrar el error. */
    crudo: (metodo, ruta, cuerpo) => pedir(metodo, ruta, cuerpo, { crudo: true }),
  };
}
