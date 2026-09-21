/* La capa de API.
 *
 * Lo que más importa acá es el corte de sólo lectura: es el control que
 * habilita el acceso de CX, y en v1 es lo único que separa a un perfil de
 * consulta de los 72 endpoints que escriben. Si esto se rompe, se rompe en
 * silencio — la llamada simplemente sale. */

import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { ErrorApi, MENSAJE_SOLO_LECTURA, crearApi } from '../src/api.js';

let llamadas;

function fetchFalso(respuesta = {}) {
  const { status = 200, cuerpo = { ok: true }, explota = false } = respuesta;
  return async (url, opts) => {
    llamadas.push({ url, opts });
    if (explota) throw new TypeError('Failed to fetch');
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => cuerpo,
    };
  };
}

function api(rol = 'analyst', respuesta) {
  globalThis.fetch = fetchFalso(respuesta);
  return crearApi({
    base: 'https://api.ejemplo/',
    perfil: () => ({ rol, modulos: ['all'] }),
    email: () => 'quien@global66.com',
  });
}

beforeEach(() => { llamadas = []; });

describe('el corte de sólo lectura', () => {
  it('deja pasar los GET', async () => {
    const a = api('lectura', { cuerpo: { casos: [] } });
    await a.get('/cases');
    assert.equal(llamadas.length, 1);
  });

  for (const [nombre, hacer] of [
    ['POST', (a) => a.post('/cases', { x: 1 })],
    ['DELETE', (a) => a.del('/cases/1')],
  ]) {
    it(`bloquea ${nombre} y NO sale del navegador`, async () => {
      const a = api('lectura');
      await assert.rejects(hacer(a), (e) => {
        assert.ok(e instanceof ErrorApi);
        assert.equal(e.codigo, 'solo_lectura');
        assert.equal(e.status, 403);
        assert.equal(e.message, MENSAJE_SOLO_LECTURA);
        return true;
      });
      // Lo importante no es el error: es que no haya salido la petición.
      assert.equal(llamadas.length, 0);
    });
  }

  it('también corta la vía cruda, que no lanza', async () => {
    const a = api('lectura');
    const r = await a.crudo('POST', '/cases', { x: 1 });
    assert.equal(r.ok, false);
    assert.equal(r.status, 403);
    assert.equal(llamadas.length, 0);
  });

  it('al analista no le corta nada', async () => {
    const a = api('analyst');
    await a.post('/cases', { x: 1 });
    assert.equal(llamadas.length, 1);
    assert.equal(llamadas[0].opts.method, 'POST');
  });

  it('el perfil se lee en cada llamada, no al construir el cliente', async () => {
    // Por qué importa: el perfil llega de Firestore DESPUÉS del primer
    // render. Si el cliente se quedara con el que había al armarse —el
    // mínimo, que es de lectura— bloquearía todo lo que el usuario escriba
    // en el resto de la sesión.
    let rol = 'lectura';
    globalThis.fetch = fetchFalso();
    const a = crearApi({
      base: 'https://api.ejemplo',
      perfil: () => ({ rol, modulos: ['all'] }),
      email: () => 'quien@global66.com',
    });
    await assert.rejects(a.post('/x', {}));
    rol = 'analyst';
    await a.post('/x', {});
    assert.equal(llamadas.length, 1);
  });
});

describe('las peticiones', () => {
  it('no manda el header Authorization', async () => {
    // No es un olvido: la API Gateway sólo permite `content-type`, y mandar
    // Authorization hace fallar el preflight y la llamada nunca sale.
    const a = api('analyst');
    await a.get('/reports');
    assert.deepEqual(Object.keys(llamadas[0].opts.headers), ['Content-Type']);
  });

  it('agrega actor_email a todo lo que lleva cuerpo', async () => {
    // Una nota quedó guardada sin autor en v1 porque el campo viajaba con
    // otro nombre. Poniéndolo acá no se puede olvidar en una llamada.
    const a = api('analyst');
    await a.post('/cases/1/notes', { texto: 'hola' });
    const enviado = JSON.parse(llamadas[0].opts.body);
    assert.equal(enviado.actor_email, 'quien@global66.com');
    assert.equal(enviado.texto, 'hola');
  });

  it('quien llama puede pisar el actor_email si de verdad lo necesita', async () => {
    const a = api('analyst');
    await a.post('/x', { actor_email: 'otro@global66.com' });
    assert.equal(JSON.parse(llamadas[0].opts.body).actor_email, 'otro@global66.com');
  });

  it('no duplica la barra de la base', async () => {
    const a = api('analyst');
    await a.get('/reports');
    assert.equal(llamadas[0].url, 'https://api.ejemplo/reports');
  });
});

describe('los errores', () => {
  it('el 401 dice que la sesión venció', async () => {
    const a = api('analyst', { status: 401, cuerpo: {} });
    await assert.rejects(a.get('/x'), (e) => e.status === 401 && e.codigo === 'sesion');
  });

  it('usa el mensaje del backend cuando lo hay', async () => {
    const a = api('analyst', { status: 400, cuerpo: { error: 'falta el campo rut' } });
    await assert.rejects(a.get('/x'), (e) => e.message === 'falta el campo rut');
  });

  it('sin mensaje del backend, al menos dice el código', async () => {
    const a = api('analyst', { status: 500, cuerpo: {} });
    await assert.rejects(a.get('/x'), (e) => e.message === 'Error 500');
  });

  it('una caída de red no queda como un error cualquiera', async () => {
    const a = api('analyst', { explota: true });
    await assert.rejects(a.get('/x'), (e) => e.codigo === 'red' && e.status === 0);
  });

  it('un cuerpo que no es JSON no rompe la vía cruda', async () => {
    globalThis.fetch = async () => ({
      ok: false, status: 502, json: async () => { throw new Error('no es json'); },
    });
    const a = crearApi({ base: 'x', perfil: () => ({ rol: 'analyst' }), email: () => '' });
    const r = await a.crudo('GET', '/x');
    assert.equal(r.status, 502);
    assert.deepEqual(r.datos, {});
  });

  it('la vía cruda devuelve el status en vez de lanzar', async () => {
    const a = api('analyst', { status: 409, cuerpo: { error: 'ya lo tomó otro' } });
    const r = await a.crudo('POST', '/cases/1/take', {});
    assert.equal(r.ok, false);
    assert.equal(r.status, 409);
    assert.equal(r.datos.error, 'ya lo tomó otro');
  });
});
