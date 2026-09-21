/* Relevo y embargos.
 *
 * Los casos salen de los datos reales: 383 casos de relevo repartidos en
 * cinco estados y cuatro partners, 112 trabados por falta de un dato, y los
 * OCHO interruptores de envío apagados. Y 13 corridas de embargos, todas
 * listas, una de ellas con 1 cliente de 6 personas y 1 descartado. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  ESTADOS_MANUALES, ETAPAS, ETAPAS_CARRIL, FILTROS_RELEVO, aplicarFiltro,
  estadoDeEnvios, etapaDe, faltantesTexto, indicadores, nombreEstado,
  porEtapa, porPartner, porTipo,
} from '../src/comun/relevo.js';
import * as E from '../src/comun/embargos.js';

function caso(extra = {}) {
  return {
    id: 'dlocal:rmt:1',
    partner: 'dLocal',
    estado: 'listo_para_pedir',
    etapa: 0,
    accionable: true,
    vencido: false,
    agotado: false,
    intentos: 0,
    faltantes: [{ item: 'documento_identidad', es: 'Documento de identidad' }],
    ...extra,
  };
}

describe('las etapas del circuito', () => {
  it('las negativas no son pasos atrás, son otra cosa', () => {
    // −1 es "falta un dato" y −2 es "no hay nada que hacer". Mezclarlas con
    // el carril feliz haría que 112 de 383 casos parezcan atrasados cuando
    // están trabados por otra razón.
    assert.equal(etapaDe({ etapa: -1 }).clave, 'trabado');
    assert.equal(etapaDe({ etapa: -2 }).clave, 'terminal');
    assert.ok(!ETAPAS_CARRIL.some((e) => e.n < 0));
  });

  it('el carril feliz va de por-pedir a cerrado', () => {
    assert.deepEqual(ETAPAS_CARRIL.map((e) => e.n), [0, 1, 2, 3, 4]);
  });

  it('cada etapa explica qué significa', () => {
    for (const e of ETAPAS) {
      assert.ok(e.descripcion && e.etiqueta && e.color, String(e.n));
    }
  });

  it('una etapa que el front no conoce devuelve null', () => {
    assert.equal(etapaDe({ etapa: 9 }), null);
    assert.equal(etapaDe({}), null);
  });
});

describe('el reparto por etapa', () => {
  it('cuenta cada etapa y deja las vacías en cero', () => {
    const r = porEtapa([caso(), caso({ etapa: -1 }), caso({ etapa: -1 })]);
    const m = Object.fromEntries(r.map((x) => [x.n, x.n_casos]));
    assert.equal(m[0], 1);
    assert.equal(m[-1], 2);
    assert.equal(m[4], 0);   // la etapa existe aunque no tenga casos
  });

  it('una etapa desconocida no hace desaparecer el caso', () => {
    // Descartarlo sería perder trabajo de vista sin que nadie se entere.
    const r = porEtapa([caso({ etapa: 42 })]);
    const rara = r.find((x) => x.clave === 'desconocida');
    assert.ok(rara);
    assert.equal(rara.n_casos, 1);
  });

  it('sin etapas raras no aparece la fila extra', () => {
    assert.ok(!porEtapa([caso()]).some((x) => x.clave === 'desconocida'));
  });

  it('los totales cierran', () => {
    const l = [caso(), caso({ etapa: -1 }), caso({ etapa: 42 })];
    assert.equal(porEtapa(l).reduce((a, x) => a + x.n_casos, 0), l.length);
  });
});

describe('los indicadores', () => {
  const lote = [
    caso(),
    caso({ estado: 'sin_cliente', etapa: -1, accionable: true }),
    caso({ estado: 'informativo', etapa: -2, accionable: false }),
    caso({ vencido: true }),
    caso({ agotado: true, partner: 'Nium' }),
  ];

  it('separa "por pedir" de "trabado"', () => {
    // Uno se resuelve escribiéndole al cliente y el otro arreglando un dato:
    // juntarlos daría un número grande que no dice qué hacer.
    const i = indicadores(lote);
    assert.equal(i.porPedir, 3);
    assert.equal(i.trabados, 1);
  });

  it('cuenta accionables, vencidos, agotados y partners', () => {
    const i = indicadores(lote);
    assert.equal(i.total, 5);
    assert.equal(i.accionables, 4);
    assert.equal(i.vencidos, 1);
    assert.equal(i.agotados, 1);
    assert.equal(i.partners, 2);
  });

  it('una lista vacía da ceros', () => {
    assert.equal(indicadores([]).total, 0);
    assert.equal(indicadores(null).total, 0);
  });
});

describe('los estados que se fijan a mano', () => {
  it('son los nueve del backend, sin los diagnósticos', () => {
    // `casos.py` los deja afuera a propósito: no son etapas del trabajo sino
    // datos que faltan, y ponerlos a mano tapa el diagnóstico.
    assert.equal(ESTADOS_MANUALES.length, 9);
    for (const d of ['sin_cliente', 'sin_correo', 'sin_requerimiento', 'informativo']) {
      assert.ok(!ESTADOS_MANUALES.includes(d), d);
    }
  });

  it('todos tienen nombre legible', () => {
    for (const e of ESTADOS_MANUALES) {
      assert.notEqual(nombreEstado(e), e, e);
    }
  });

  it('un estado que el front no conoce se muestra crudo', () => {
    assert.equal(nombreEstado('inventado'), 'inventado');
    assert.equal(nombreEstado(''), '—');
  });
});

describe('el estado de los envíos', () => {
  /* Lo más importante de la pantalla: con los envíos apagados, una bandeja
     con 230 casos "listos para pedir" no puede pedir nada. */
  const datos = {
    envio_activo: false,
    apagados: ['envio_general', 'envio_dlocal'],
    procesos_apagados: [],
    interruptores: [
      { clave: 'modulo', tipo: 'maestro', valor: true },
      { clave: 'ingesta', tipo: 'proceso', valor: true },
      { clave: 'envio_general', tipo: 'salida', valor: false },
      { clave: 'envio_dlocal', tipo: 'salida', valor: false },
      { clave: 'envio_nium', tipo: 'salida', valor: true },
    ],
  };

  it('lee que el envío está apagado', () => {
    const e = estadoDeEnvios(datos);
    assert.equal(e.activo, false);
    assert.equal(e.generalEncendido, false);
  });

  it('cuenta los partners aparte del general', () => {
    // El general manda: con él apagado no sale nada aunque un partner esté
    // encendido, y mostrar "1 encendido" sin esa distinción confundiría.
    const e = estadoDeEnvios(datos);
    assert.equal(e.partnersTotal, 2);
    assert.equal(e.partnersEncendidos, 1);
  });

  it('sin datos no dice que el envío está activo', () => {
    // El default seguro: ante la duda, apagado.
    assert.equal(estadoDeEnvios(null).activo, false);
    assert.equal(estadoDeEnvios({}).generalEncendido, false);
  });

  it('agrupa por tipo en orden de importancia', () => {
    const g = porTipo(datos.interruptores);
    assert.deepEqual(g.map((x) => x.tipo), ['maestro', 'salida', 'proceso']);
    assert.equal(g[1].items.length, 3);
  });

  it('un tipo nuevo del backend no se pierde', () => {
    const g = porTipo([{ clave: 'x', tipo: 'inventado', valor: true }]);
    assert.equal(g.length, 1);
    assert.equal(g[0].tipo, 'inventado');
  });
});

describe('los filtros y el resto', () => {
  const lote = [caso(), caso({ etapa: -1, estado: 'sin_cliente' }), caso({ vencido: true })];

  it('cada filtro mira una cosa distinta', () => {
    assert.equal(aplicarFiltro(lote, 'por_pedir').length, 2);
    assert.equal(aplicarFiltro(lote, 'trabados').length, 1);
    assert.equal(aplicarFiltro(lote, 'vencidos').length, 1);
    assert.equal(aplicarFiltro(lote, 'todos').length, 3);
  });

  it('un filtro inexistente no esconde nada', () => {
    assert.equal(aplicarFiltro(lote, 'nada').length, 3);
  });

  it('todos los filtros tienen etiqueta', () => {
    for (const [k, f] of Object.entries(FILTROS_RELEVO)) assert.ok(f.etiqueta, k);
  });

  it('cuenta por partner de mayor a menor', () => {
    const l = [caso(), caso(), caso({ partner: 'Nium' })];
    assert.deepEqual(porPartner(l).map((x) => [x.partner, x.n]), [['dLocal', 2], ['Nium', 1]]);
  });

  it('los faltantes se leen en castellano, no por su clave', () => {
    assert.equal(faltantesTexto(caso()), 'Documento de identidad');
    assert.equal(faltantesTexto({ faltantes: [] }), '');
    assert.equal(faltantesTexto({}), '');
  });

  it('un faltante sin traducción muestra la clave', () => {
    assert.equal(faltantesTexto({ faltantes: [{ item: 'algo_nuevo' }] }), 'algo_nuevo');
  });
});

/* ══════════════════════════════════════════════════════════════════════════ */

describe('embargos: el estado de una corrida', () => {
  it('sabe cuáles siguen moviéndose', () => {
    assert.equal(E.enCurso({ estado: 'procesando' }), true);
    assert.equal(E.enCurso({ estado: 'listo' }), false);
    assert.equal(E.enCurso({ estado: 'error' }), false);
  });

  it('sin estado no está en curso: no hay nada que esperar', () => {
    assert.equal(E.enCurso({}), false);
    assert.equal(E.enCurso(null), false);
  });

  it('cada etapa conocida tiene nombre y color', () => {
    for (const e of ['recibido', 'procesando', 'listo', 'error']) {
      assert.ok(E.etapaDe({ estado: e })?.etiqueta, e);
    }
    assert.equal(E.etapaDe({ estado: 'inventado' }), null);
  });
});

describe('embargos: qué respondió el oficio', () => {
  const corrida = { conteos: { personas: 6, clientes: 1, no_clientes: 5, descartados: 1 } };

  it('da el clientes sobre el total, no un número suelto', () => {
    const r = E.resumenDe(corrida);
    assert.equal(r.clientes, 1);
    assert.equal(r.personas, 6);
    assert.ok(Math.abs(r.porcentaje - 16.67) < 0.1);
  });

  it('también lee los conteos desde la raíz, como el historial', () => {
    assert.equal(E.resumenDe({ personas: 6, clientes: 1 }).clientes, 1);
  });

  it('sin personas el porcentaje es null, no cero', () => {
    // Un 0% diría que no hubo ninguna coincidencia; "no se sabe" es otra cosa.
    assert.equal(E.resumenDe({ conteos: {} }).porcentaje, null);
    assert.equal(E.resumenDe({}).porcentaje, null);
  });

  it('un descartado no es un "no cliente"', () => {
    // Es una fila que no se pudo leer: contarlos juntos haría creer que se
    // revisó a alguien a quien nunca se buscó.
    assert.equal(E.hayDescartados(corrida), true);
    assert.equal(E.hayDescartados({ conteos: { descartados: 0 } }), false);
  });
});

describe('embargos: formatos y progreso', () => {
  it('acepta Excel, CSV y PDF', () => {
    for (const n of ['oficio.xlsx', 'OFICIO.XLS', 'lista.csv', 'Oficio No 4272.pdf']) {
      assert.equal(E.formatoAceptado(n), true, n);
    }
  });
  it('rechaza lo demás', () => {
    for (const n of ['oficio.docx', 'foto.png', 'sinextension', '']) {
      assert.equal(E.formatoAceptado(n), false, n);
    }
  });
  it('el progreso se acota entre 0 y 100', () => {
    assert.equal(E.progresoDe({ progreso: 150 }), 100);
    assert.equal(E.progresoDe({ progreso: -5 }), 0);
    assert.equal(E.progresoDe({ progreso: 100 }), 100);
  });
  it('sin progreso devuelve null y no cero', () => {
    assert.equal(E.progresoDe({}), null);
    assert.equal(E.progresoDe({ progreso: 'algo' }), null);
  });
});

describe('embargos: los indicadores', () => {
  it('suma personas y clientes sólo de las corridas listas', () => {
    // Una corrida a medias tiene conteos parciales: sumarlos daría un total
    // que cambia solo mientras alguien lo mira.
    const l = [
      { estado: 'listo', personas: 6, clientes: 1 },
      { estado: 'listo', personas: 10, clientes: 3 },
      { estado: 'procesando', personas: 99, clientes: 99 },
    ];
    const i = E.indicadores(l);
    assert.equal(i.personas, 16);
    assert.equal(i.clientes, 4);
    assert.equal(i.enCurso, 1);
    assert.equal(i.total, 3);
  });

  it('cuenta como fallida tanto el estado error como el campo error', () => {
    assert.equal(E.indicadores([{ estado: 'error' }]).fallidas, 1);
    assert.equal(E.indicadores([{ estado: 'listo', error: 'algo' }]).fallidas, 1);
  });

  it('una lista vacía da ceros', () => {
    assert.equal(E.indicadores([]).total, 0);
    assert.equal(E.indicadores(null).total, 0);
  });
});
