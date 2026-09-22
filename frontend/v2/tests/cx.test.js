/* La vista de CX.
 *
 * Quien la usa tiene al cliente en el teléfono, así que lo que se prueba es
 * que no conteste de más: la diferencia entre «no tiene nada abierto» y «no
 * figura» es la diferencia entre afirmar que lo revisamos y admitir que no lo
 * vimos nunca. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { buscar, correoDeAlerta, indice, respuesta } from '../src/comun/cx.js';

const caso = (id, status = 'open', extra = {}) => ({
  case_id: `c-${id}-${status}`, entity_id: id, status, ...extra,
});
const alerta = (id, correo, clave = 'customer_email') => ({
  alert_id: `a-${id}`, entity_value: id,
  row_data: JSON.stringify(correo ? { [clave]: correo, monto: 1 } : { monto: 1 }),
});

describe('el correo del cliente', () => {
  it('sale de la fila del reporte, que llega como texto JSON', () => {
    // Las 122 alertas de producción traen `row_data` como texto. El correo no
    // está en el nivel de arriba de la alerta ni en el caso.
    assert.equal(correoDeAlerta(alerta(1, 'Ana@Correo.com')), 'ana@correo.com');
  });

  it('se busca bajo los distintos nombres que usan los reportes', () => {
    for (const k of ['customer_email', 'email', 'correo', 'client_email']) {
      assert.equal(correoDeAlerta(alerta(1, 'a@b.com', k)), 'a@b.com', k);
    }
  });

  it('sin correo devuelve vacío, no «undefined»', () => {
    assert.equal(correoDeAlerta(alerta(1, null)), '');
    assert.equal(correoDeAlerta({}), '');
    assert.equal(correoDeAlerta({ row_data: 'roto' }), '');
  });

  it('lo que no parece un correo no se toma por tal', () => {
    assert.equal(correoDeAlerta({ row_data: '{"email":"sin arroba"}' }), '');
  });
});

describe('el índice', () => {
  it('junta los casos abiertos de cada cliente', () => {
    const i = indice([caso('100'), caso('100'), caso('200')], []);
    const uno = i.find((e) => e.id === '100');
    assert.equal(uno.casos.length, 2);
    assert.equal(i.length, 2);
  });

  it('los cerrados no entran: a CX le preguntan si HAY algo, no qué hubo', () => {
    const i = indice([caso('100', 'closed'), caso('100', 'archived')], []);
    assert.equal(i.length, 0);
  });

  it('pega los correos de las alertas al cliente', () => {
    const i = indice([caso('100')], [alerta('100', 'a@b.com'), alerta('100', 'c@d.com')]);
    assert.deepEqual(i[0].correos.sort(), ['a@b.com', 'c@d.com']);
  });

  it('un cliente con alerta y sin caso abierto igual entra al índice', () => {
    // Para poder contestar «no tiene nada abierto», que es una respuesta,
    // en vez de «no lo encuentro», que no lo es.
    const i = indice([], [alerta('300', 'x@y.com')]);
    assert.equal(i.length, 1);
    assert.equal(i[0].casos.length, 0);
  });

  it('toma el nombre del primer caso que lo traiga', () => {
    const i = indice([caso('100'), caso('100', 'open', { entity_name: 'Ada L.' })], []);
    assert.equal(i[0].nombre, 'Ada L.');
  });

  it('sin id no se indexa nada', () => {
    assert.deepEqual(indice([{ status: 'open' }], []), []);
    assert.deepEqual(indice(null, null), []);
  });
});

describe('la búsqueda', () => {
  const i = indice(
    [caso('2225191', 'open', { entity_name: 'Ada Lovelace' }), caso('999')],
    [alerta('2225191', 'ada@correo.com')],
  );

  it('encuentra por id exacto', () => {
    assert.equal(buscar(i, '2225191').length, 1);
  });

  it('encuentra por correo exacto, sin importar mayúsculas', () => {
    assert.equal(buscar(i, 'ADA@Correo.com').length, 1);
  });

  it('encuentra por parte del nombre', () => {
    // Nadie escribe un nombre igual dos veces.
    assert.equal(buscar(i, 'lovelace').length, 1);
  });

  it('NO encuentra por parte del id', () => {
    // «2225» traería medio padrón y CX elegiría mal con el cliente esperando.
    assert.equal(buscar(i, '2225').length, 0);
  });

  it('NO encuentra por parte del correo', () => {
    assert.equal(buscar(i, 'correo.com').length, 0);
  });

  it('con menos de tres caracteres no busca', () => {
    // Evita que la pantalla liste todo mientras se escribe.
    assert.deepEqual(buscar(i, '22'), []);
    assert.deepEqual(buscar(i, ''), []);
  });

  it('el espacio de los costados no cuenta', () => {
    assert.equal(buscar(i, '  2225191  ').length, 1);
  });
});

describe('qué se le contesta a CX', () => {
  it('con casos abiertos, dice cuántos', () => {
    const r = respuesta([{ casos: [1, 2] }]);
    assert.equal(r.clave, 'abiertos');
    assert.match(r.texto, /2 casos abiertos/);
  });

  it('con uno solo, lo dice en singular', () => {
    assert.match(respuesta([{ casos: [1] }]).texto, /1 caso abierto\./);
  });

  it('figura pero sin nada abierto', () => {
    const r = respuesta([{ casos: [] }]);
    assert.equal(r.clave, 'sin_abiertos');
    assert.match(r.texto, /no tiene ningún caso abierto/);
  });

  it('no figurar NO es lo mismo que estar limpio, y el texto lo aclara', () => {
    // Es la distinción que evita que CX le afirme a un cliente que lo
    // revisamos cuando lo único cierto es que no aparece.
    const r = respuesta([]);
    assert.equal(r.clave, 'sin_registro');
    assert.match(r.detalle, /no quiere decir que esté observado y limpio/i);
  });

  it('sin lista tampoco rompe', () => {
    assert.equal(respuesta(null).clave, 'sin_registro');
  });
});
