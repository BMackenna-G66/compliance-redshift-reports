/* Administración.
 *
 * El test que más importa acá es el de `modulosParaGuardar`: v1 y v2 escriben
 * en la MISMA colección de permisos y manejan listas de módulos distintas. Si
 * v2 guardara sólo lo que conoce, editar a alguien desde acá le sacaría en
 * silencio accesos que usa en v1.
 *
 * Los datos de referencia son los reales: 12 usuarios de CRM en seis equipos,
 * 200 entradas de auditoría de las que 22 son consultas y no cambios. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  PERFILES, accionEs, clusterEnMovimiento, cruzar, entidadEs, esCambio,
  estadoCluster, indicadores, modulosDisponibles, modulosParaGuardar,
  nombrePerfil, resumenAuditoria,
} from '../src/comun/admin.js';
import { PANTALLAS } from '../src/dominio.js';

describe('los módulos que se pueden habilitar', () => {
  it('salen de las pantallas, no de una lista aparte', () => {
    // v1 mantiene su propio ALL_MODULES y ya se desfasó: tiene cuatro claves
    // de pantallas que no existen. Derivarlo evita repetir ese error.
    const claves = modulosDisponibles().map((m) => m.clave);
    const dePantallas = new Set(PANTALLAS.map((p) => p.modulo));
    assert.deepEqual(new Set(claves), dePantallas);
  });

  it('cada módulo dice qué pantallas abre', () => {
    for (const m of modulosDisponibles()) {
      assert.ok(m.pantallas.length > 0, m.clave);
    }
  });

  it('no repite un módulo que usan varias pantallas', () => {
    const claves = modulosDisponibles().map((m) => m.clave);
    assert.equal(new Set(claves).size, claves.length);
    // `casos` lo usan varias pantallas y tiene que aparecer una sola vez.
    const casos = modulosDisponibles().find((m) => m.clave === 'casos');
    assert.ok(casos.pantallas.length > 1);
  });
});

describe('guardar los módulos sin pisar a v1', () => {
  /* LA REGLA: lo que esta pantalla no muestra, no lo toca. */

  it('conserva las claves que v2 no conoce', () => {
    // Hoy v2 cubre todos los módulos de v1 (hay un test de sincronía que lo
    // vigila), así que la clave ajena de este caso es inventada. La regla
    // sigue importando: protege de que v1 agregue un módulo, o de una clave
    // vieja que quedó en el documento de alguien.
    const antes = ['casos', 'modulo_viejo', 'algo_de_v1'];
    const guardado = modulosParaGuardar(['casos', 'relevo'], antes);
    for (const m of ['modulo_viejo', 'algo_de_v1']) {
      assert.ok(guardado.includes(m), `se perdió ${m}`);
    }
  });

  it('respeta lo que se marcó y lo que se desmarcó de lo conocido', () => {
    const guardado = modulosParaGuardar(['relevo'], ['casos', 'relevo']);
    assert.ok(guardado.includes('relevo'));
    assert.ok(!guardado.includes('casos'), 'desmarcar casos no tuvo efecto');
  });

  it('no duplica si una clave está en los dos lados', () => {
    const g = modulosParaGuardar(['casos'], ['casos', 'modulo_viejo']);
    assert.equal(g.filter((x) => x === 'casos').length, 1);
  });

  it('un módulo que v2 SÍ maneja se puede desmarcar de verdad', () => {
    // El complemento del test de arriba: conservar lo desconocido no puede
    // volverse "conservar todo", o quitar un permiso no tendría efecto.
    assert.ok(!modulosParaGuardar(['casos'], ['casos', 'pendientes']).includes('pendientes'));
  });

  it('`all` no se arrastra solo: si se desmarca, se va', () => {
    // `all` es el comodín que abre todo. Conservarlo "por las dudas" dejaría
    // a alguien con acceso total después de que se lo quitaron.
    assert.ok(!modulosParaGuardar(['casos'], ['all']).includes('all'));
    assert.ok(modulosParaGuardar(['all'], ['all']).includes('all'));
  });

  it('sin nada anterior guarda sólo lo marcado', () => {
    assert.deepEqual(modulosParaGuardar(['casos'], []), ['casos']);
    assert.deepEqual(modulosParaGuardar(['casos'], null), ['casos']);
  });

  it('sin nada marcado y con claves ajenas, deja las ajenas', () => {
    assert.deepEqual(modulosParaGuardar([], ['modulo_viejo']), ['modulo_viejo']);
  });
});

describe('el cruce de las dos listas de usuarios', () => {
  const crm = [
    { email: 'a@global66.com', full_name: 'Ana', equipo: 'KYT', is_active: true },
    { email: 'b@global66.com', full_name: 'Beto', equipo: 'KYX', is_active: false },
  ];
  const perfiles = [
    { email: 'a@global66.com', role: 'analyst', modules: ['casos'] },
    { email: 'c@global66.com', role: 'lectura', modules: ['casos'] },
  ];

  it('marca a quien está en el CRM y no tiene perfil', () => {
    // Entra y no ve nada: el síntoma es raro y la causa no es obvia.
    const f = cruzar(crm, perfiles);
    const beto = f.find((x) => x.correo === 'b@global66.com');
    assert.equal(beto.sinPerfil, true);
    assert.equal(beto.sinUsuario, false);
  });

  it('marca a quien tiene perfil y no está en el CRM', () => {
    // Ve la aplicación, pero nadie le puede asignar un caso.
    const f = cruzar(crm, perfiles);
    const ce = f.find((x) => x.correo === 'c@global66.com');
    assert.equal(ce.sinUsuario, true);
    assert.equal(ce.sinPerfil, false);
  });

  it('junta los dos lados cuando existen', () => {
    const ana = cruzar(crm, perfiles).find((x) => x.correo === 'a@global66.com');
    assert.equal(ana.nombre, 'Ana');
    assert.equal(ana.equipo, 'KYT');
    assert.equal(ana.rol, 'analyst');
    assert.deepEqual(ana.modulos, ['casos']);
  });

  it('el correo se compara sin mayúsculas ni espacios', () => {
    const f = cruzar([{ email: '  A@Global66.com ' }], [{ email: 'a@global66.com', role: 'admin' }]);
    assert.equal(f.length, 1);
    assert.equal(f[0].rol, 'admin');
  });

  it('acepta `id` cuando no hay `email`', () => {
    // El endpoint de usuarios devuelve el correo en `id`.
    const f = cruzar([{ id: 'x@global66.com' }], []);
    assert.equal(f[0].correo, 'x@global66.com');
  });

  it('una fila sin correo no entra: no se la puede cruzar con nada', () => {
    assert.equal(cruzar([{ full_name: 'Sin correo' }], []).length, 0);
  });

  it('el inactivo del CRM se distingue del que no está', () => {
    const f = cruzar(crm, perfiles);
    assert.equal(f.find((x) => x.correo === 'b@global66.com').activo, false);
    // Quien no está en el CRM no es "inactivo": no se sabe.
    assert.equal(f.find((x) => x.correo === 'c@global66.com').activo, null);
  });

  it('listas vacías no rompen', () => {
    assert.deepEqual(cruzar([], []), []);
    assert.deepEqual(cruzar(null, null), []);
  });
});

describe('los indicadores de usuarios', () => {
  it('cuenta lo que hace falta revisar', () => {
    const f = cruzar(
      [{ email: 'a@x.cl', equipo: 'KYT' }, { email: 'b@x.cl', equipo: 'KYX' }],
      [{ email: 'a@x.cl', role: 'lectura' }, { email: 'c@x.cl', role: 'admin' }],
    );
    const i = indicadores(f);
    assert.equal(i.total, 3);
    assert.equal(i.conAcceso, 2);
    assert.equal(i.sinPerfil, 1);
    assert.equal(i.sinUsuario, 1);
    assert.equal(i.soloLectura, 1);
    assert.equal(i.admins, 1);
    assert.equal(i.equipos, 2);
  });

  it('el superadmin cuenta como admin', () => {
    const f = cruzar([], [{ email: 'a@x.cl', role: 'superadmin' }]);
    assert.equal(indicadores(f).admins, 1);
  });
});

describe('los perfiles', () => {
  it('son los tres de v1, para que un rol signifique lo mismo', () => {
    assert.deepEqual(PERFILES.map((p) => p.clave), ['lectura', 'analyst', 'admin']);
  });
  it('cada uno explica qué puede hacer', () => {
    for (const p of PERFILES) assert.ok(p.descripcion.length > 20, p.clave);
  });
  it('el superadmin tiene nombre aunque no se pueda asignar', () => {
    assert.equal(nombrePerfil('superadmin'), 'Super admin');
    assert.equal(nombrePerfil('inventado'), 'inventado');
    assert.equal(nombrePerfil(''), '—');
  });
});

describe('la auditoría', () => {
  it('traduce las acciones que se usan de verdad', () => {
    // Las diez más frecuentes de las 200 entradas reales.
    for (const a of ['case.note_add', 'case.create', 'case.status_change',
                     'embargos.ejecutar', 'cliente.ficha_pdf', 'update_user',
                     'case.delete', 'alert.bulk_distribute', 'alert.review']) {
      assert.notEqual(accionEs(a), a, a);
    }
  });

  it('una acción nueva se muestra cruda y no vacía', () => {
    assert.equal(accionEs('algo.nuevo'), 'algo.nuevo');
    assert.equal(accionEs(''), '—');
    assert.equal(entidadEs('cosa'), 'cosa');
  });

  it('separa los cambios de las consultas', () => {
    // «Descargó la ficha» y «borró un caso» no pesan igual cuando hay que
    // revisar qué pasó un día.
    assert.equal(esCambio({ action: 'case.delete' }), true);
    assert.equal(esCambio({ action: 'cliente.ficha_pdf' }), false);
    assert.equal(esCambio({ action: 'case.client_profile' }), false);
  });

  it('una acción desconocida cuenta como cambio', () => {
    // Ante la duda, que aparezca en la lista de cambios: esconderla sería
    // peor que mostrarla de más.
    assert.equal(esCambio({ action: 'algo.nuevo' }), true);
  });

  it('resume el total, los cambios y cuánta gente', () => {
    const e = [
      { action: 'case.create', user_email: 'a@x.cl', entity_type: 'case' },
      { action: 'cliente.ficha_pdf', user_email: 'a@x.cl', entity_type: 'customer' },
      { action: 'case.delete', user_email: 'b@x.cl', entity_type: 'case' },
    ];
    const r = resumenAuditoria(e);
    assert.equal(r.total, 3);
    assert.equal(r.cambios, 2);
    assert.equal(r.personas, 2);
    assert.equal(r.entidades, 2);
  });

  it('sin entradas da ceros', () => {
    assert.equal(resumenAuditoria([]).total, 0);
    assert.equal(resumenAuditoria(null).total, 0);
  });
});

describe('el cluster', () => {
  it('sabe cuándo se puede consultar', () => {
    assert.equal(estadoCluster('available').consulta, true);
    assert.equal(estadoCluster('paused').consulta, false);
    assert.equal(estadoCluster('resuming').consulta, false);
  });

  it('pausado no es un error: se apaga solo de noche', () => {
    assert.notEqual(estadoCluster('paused').color, 'var(--estado-error-texto)');
  });

  it('sabe cuándo está en movimiento y hay que volver a preguntar', () => {
    assert.equal(clusterEnMovimiento('resuming'), true);
    assert.equal(clusterEnMovimiento('pausing'), true);
    assert.equal(clusterEnMovimiento('available'), false);
    assert.equal(clusterEnMovimiento('paused'), false);
  });

  it('un estado desconocido no se inventa', () => {
    assert.equal(estadoCluster('lo_que_sea'), null);
    assert.equal(estadoCluster(''), null);
  });

  it('no le importan las mayúsculas', () => {
    assert.equal(estadoCluster('AVAILABLE').etiqueta, 'Disponible');
  });
});
