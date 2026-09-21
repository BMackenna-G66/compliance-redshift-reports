/* Permisos: la misma semántica que v1.
 *
 * Esto es lo que le estamos dando a CX, así que tiene que estar probado y no
 * sólo leído. El caso que más importa es el del final: qué pasa cuando
 * Firestore no contesta. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  PERFIL_MINIMO, SUPER_ADMIN, esAdmin, menuPara, perfilRecordado,
  recordarPerfil, soloLectura, tieneModulo, verModulo,
} from '../src/permisos.js';

const lectura = { rol: 'lectura', modulos: ['casos'] };
const analista = { rol: 'analyst', modulos: ['dashboard'] };
const superadmin = { rol: 'superadmin', modulos: [] };

describe('roles', () => {
  it('reconoce al perfil de consulta', () => {
    assert.equal(soloLectura(lectura), true);
    assert.equal(soloLectura(analista), false);
    assert.equal(soloLectura(superadmin), false);
  });

  it('admin y superadmin administran', () => {
    assert.equal(esAdmin({ rol: 'admin' }), true);
    assert.equal(esAdmin(superadmin), true);
    assert.equal(esAdmin(analista), false);
  });

  it('no se cae con un perfil ausente', () => {
    for (const f of [soloLectura, esAdmin, (p) => verModulo(p, 'casos')]) {
      assert.doesNotThrow(() => f(null));
      assert.doesNotThrow(() => f(undefined));
    }
  });
});

describe('verModulo', () => {
  it('al perfil de lectura sólo le muestra lo que tiene habilitado', () => {
    assert.equal(verModulo(lectura, 'casos'), true);
    assert.equal(verModulo(lectura, 'admin'), false);
    assert.equal(verModulo(lectura, 'embargos'), false);
  });

  it('"all" le abre todo al perfil de lectura', () => {
    const cx = { rol: 'lectura', modulos: ['all'] };
    assert.equal(verModulo(cx, 'admin'), true);
  });

  it('al analista NO le restringe nada', () => {
    // Deliberado, y es la parte contraintuitiva: en v1 trece de catorce
    // pestañas nunca miraron los módulos, así que los perfiles existentes
    // tienen listas incompletas. Apretar esto hoy les sacaría accesos que
    // usan a diario. Se aprieta cuando la auth sea real.
    assert.equal(verModulo(analista, 'embargos'), true);
    assert.equal(verModulo(analista, 'admin'), true);
  });

  it('el superadmin ve todo', () => {
    assert.equal(verModulo(superadmin, 'lo-que-sea'), true);
    assert.equal(tieneModulo(superadmin, 'lo-que-sea'), true);
  });

  it('tieneModulo sí mira la lista, sin la excepción del analista', () => {
    assert.equal(tieneModulo(analista, 'dashboard'), true);
    assert.equal(tieneModulo(analista, 'embargos'), false);
  });
});

describe('el menú', () => {
  const pantallas = [
    { id: 'a', grupo: 'Uno', modulo: 'casos' },
    { id: 'b', grupo: 'Uno', modulo: 'admin' },
    { id: 'c', grupo: 'Dos', modulo: 'admin' },
  ];
  const grupos = ['Uno', 'Dos'];

  it('esconde lo que el perfil de lectura no ve', () => {
    const m = menuPara(lectura, pantallas, grupos);
    assert.deepEqual(m.map((g) => g.grupo), ['Uno']);
    assert.deepEqual(m[0].pantallas.map((p) => p.id), ['a']);
  });

  it('un grupo que queda sin pantallas no se dibuja vacío', () => {
    const m = menuPara(lectura, pantallas, grupos);
    assert.equal(m.find((g) => g.grupo === 'Dos'), undefined);
  });

  it('respeta el orden de los grupos', () => {
    const m = menuPara(superadmin, pantallas, grupos);
    assert.deepEqual(m.map((g) => g.grupo), ['Uno', 'Dos']);
  });
});

describe('el perfil recordado', () => {
  function almacenFalso(valor) {
    return { getItem: () => valor, setItem() {} };
  }

  it('sin nada guardado cae al perfil MÍNIMO, no al máximo', () => {
    // El caso que importa: en v1 esto llegó a ser acceso total "para que nada
    // se rompa", y un hipo de Firestore le abría el sistema entero a quien
    // sólo puede consultar.
    assert.deepEqual(perfilRecordado(almacenFalso(null)), PERFIL_MINIMO);
  });

  it('un JSON roto no revienta ni abre nada', () => {
    assert.deepEqual(perfilRecordado(almacenFalso('{no es json')), PERFIL_MINIMO);
  });

  it('un objeto sin rol no vale', () => {
    assert.deepEqual(perfilRecordado(almacenFalso('{"modulos":["all"]}')), PERFIL_MINIMO);
  });

  it('recupera lo que se guardó', () => {
    const guardado = JSON.stringify({ rol: 'analyst', modulos: ['casos', 'relevo'] });
    assert.deepEqual(perfilRecordado(almacenFalso(guardado)),
      { rol: 'analyst', modulos: ['casos', 'relevo'] });
  });

  it('si el almacenamiento está bloqueado, no rompe', () => {
    const roto = {
      getItem() { throw new Error('bloqueado'); },
      setItem() { throw new Error('bloqueado'); },
    };
    assert.deepEqual(perfilRecordado(roto), PERFIL_MINIMO);
    assert.doesNotThrow(() => recordarPerfil(analista, roto));
  });
});

describe('el super admin', () => {
  it('es una dirección de global66', () => {
    assert.match(SUPER_ADMIN, /@global66\.com$/);
  });
});
