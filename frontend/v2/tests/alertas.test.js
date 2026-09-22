/* Alertas.
 *
 * Los casos de acá no son inventados: salen de mirar las 122 alertas activas
 * de producción. Las formas raras que se prueban —12 alertas sin puntaje, seis
 * reportes con cuatro campos de monto distintos, uno sin monto— son las que
 * realmente hay, no las que el prototipo dibuja. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  aplicarFiltro, comoFila, correoDe, esCasoAbierto, fecha, filaDelReporte, hace,
  indicadores, montoDe, montoTexto, nombreLegible, porReporte, prepararAlerta,
  prioridadDe, scoreDe,
} from '../src/comun/alertas.js';
import { nivelDe, prioridadDeAlerta } from '../src/dominio.js';

/* Una alerta con la forma que devuelve la API. Los identificadores son
   inventados a propósito: el repo es público, y un id de cliente real junto a
   "alerta de AML" dice que a esa persona se la marcó. */
function alerta(fila = {}, extra = {}) {
  return {
    alert_id: 'a1',
    entity_field: 'customer_id',
    entity_value: '9000001',
    report_name: 'beneficiary_dispersion',
    created_at: '2026-09-14 18:21:04',
    status: 'active',
    priority: 'high',
    assigned_to: 'analista@global66.com',
    tiene_caso: true,
    caso_estado: 'open',
    caso_estado_es: 'Abierto',
    row_data: JSON.stringify({ customer_id: 9000001, ...fila }),
    ...extra,
  };
}

describe('las dos escalas no se mezclan', () => {
  it('un puntaje de alerta NO se interpreta con los cortes del individual', () => {
    // Es el error que este módulo existe para impedir. 59 es un P2 corriente
    // —35 de las 122 alertas activas tienen exactamente ese puntaje— y con
    // los cortes del análisis individual sería "CRÍTICO".
    assert.equal(prioridadDeAlerta(59), 'P2');
    assert.equal(nivelDe(59), 'CRITICO');
  });

  it('los cortes de alerta son los de handler.py', () => {
    assert.equal(prioridadDeAlerta(87.07), 'P1');   // el máximo observado
    assert.equal(prioridadDeAlerta(75), 'P1');
    assert.equal(prioridadDeAlerta(74.99), 'P2');
    assert.equal(prioridadDeAlerta(50), 'P2');
    assert.equal(prioridadDeAlerta(49.57), 'P3');   // el máximo P3 observado
    assert.equal(prioridadDeAlerta(0), 'P3');
  });

  it('sin puntaje no hay prioridad, y eso NO es P3', () => {
    // Doce de las 122 no traen puntaje. Mostrarlas como P3 diría que se las
    // evaluó y salieron bajas, cuando nunca se las midió.
    for (const v of [null, undefined, '', 'abc', NaN]) {
      assert.equal(prioridadDeAlerta(v), null, String(v));
    }
  });
});

describe('leer row_data', () => {
  it('lo lee cuando viene como texto JSON', () => {
    assert.equal(filaDelReporte(alerta({ risk_score: '47.34' })).risk_score, '47.34');
  });

  it('también cuando ya viene como objeto', () => {
    const a = { row_data: { risk_score: 12 } };
    assert.equal(filaDelReporte(a).risk_score, 12);
  });

  it('un JSON roto no hace desaparecer la alerta', () => {
    // Esconderla sería esconder trabajo pendiente.
    assert.deepEqual(filaDelReporte({ row_data: '{roto' }), {});
    assert.deepEqual(filaDelReporte({ row_data: '' }), {});
    assert.deepEqual(filaDelReporte({}), {});
    assert.deepEqual(filaDelReporte(null), {});
  });

  it('un row_data que es un arreglo o un número tampoco rompe', () => {
    assert.deepEqual(filaDelReporte({ row_data: '42' }), {});
    assert.deepEqual(filaDelReporte({ row_data: 42 }), {});
  });
});

describe('el puntaje', () => {
  it('lo lee aunque venga como texto', () => {
    assert.equal(scoreDe(alerta({ risk_score: '47.34' })), 47.34);
    assert.equal(scoreDe(alerta({ risk_score: 59 })), 59);
  });
  it('un cero es un cero, no un ausente', () => {
    // Hay exactamente una alerta con puntaje 0 en producción.
    assert.equal(scoreDe(alerta({ risk_score: '0.00' })), 0);
    assert.equal(prioridadDe(alerta({ risk_score: '0.00' })), 'P3');
  });
  it('sin el campo, null', () => {
    assert.equal(scoreDe(alerta()), null);
  });
});

describe('la prioridad', () => {
  it('se recalcula del puntaje, no se lee del guardado', () => {
    // Si el backend cambia los cortes, las alertas viejas no deben seguir
    // mostrando la clasificación con la que se guardaron.
    const a = alerta({ risk_score: '80', prioridad: 'P3' });
    assert.equal(prioridadDe(a), 'P1');
  });

  it('sin puntaje, cae a la prioridad guardada', () => {
    assert.equal(prioridadDe(alerta({ prioridad: 'P2' })), 'P2');
  });

  it('una prioridad guardada que no existe no se inventa', () => {
    assert.equal(prioridadDe(alerta({ prioridad: 'P9' })), null);
  });
});

describe('el monto', () => {
  it('cada reporte trae el suyo, con el nombre de lo que mide', () => {
    const a = { report_name: 'payin_payout_accumulation',
                row_data: JSON.stringify({ total_payout_usd_7d: '12500.50' }) };
    assert.deepEqual(montoDe(a),
      { valor: 12500.5, etiqueta: 'Girado 7d', campo: 'total_payout_usd_7d' });
  });

  it('un reporte sin monto definido devuelve null, no un cero', () => {
    // `operation-alert_-_psp_sum_30` es de estado de compliance, no
    // transaccional: no tiene monto. Un 0 diría que movió cero dólares.
    const a = { report_name: 'operation-alert_-_psp_sum_30', row_data: '{}' };
    assert.equal(montoDe(a), null);
    assert.equal(montoTexto(montoDe(a)), '—');
  });

  it('un reporte desconocido no adivina un campo', () => {
    const a = { report_name: 'reporte_nuevo',
                row_data: JSON.stringify({ total_usd_7d: '999' }) };
    assert.equal(montoDe(a), null);
  });

  it('el campo presente pero vacío es null', () => {
    const a = { report_name: 'structuring_detection',
                row_data: JSON.stringify({ total_usd_7d: '' }) };
    assert.equal(montoDe(a), null);
  });

  it('se muestra con separador de miles', () => {
    const a = { report_name: 'structuring_detection',
                row_data: JSON.stringify({ total_usd_7d: '3290.00' }) };
    assert.equal(montoTexto(montoDe(a)), 'USD 3.290');
  });
});

describe('el correo del cliente', () => {
  it('lo toma de customer_email o de email, según el reporte', () => {
    assert.equal(correoDe(alerta({ customer_email: 'a@b.cl' })), 'a@b.cl');
    assert.equal(correoDe(alerta({ email: 'c@d.cl' })), 'c@d.cl');
  });
  it('si no está, texto vacío', () => {
    assert.equal(correoDe(alerta()), '');
  });
});

describe('las fechas', () => {
  it('"2026-09-14 18:21:04" se lee como UTC', () => {
    // Sin la T y la Z, Safari lo rechaza y Chrome lo lee como hora local:
    // dos horas distintas según el navegador.
    assert.equal(fecha('2026-09-14 18:21:04').toISOString(), '2026-09-14T18:21:04.000Z');
  });
  it('no rompe con basura', () => {
    for (const v of ['', null, undefined, 'ayer', 123]) assert.equal(fecha(v), null);
  });
  it('cuenta el tiempo transcurrido', () => {
    const ahora = new Date('2026-09-14T21:21:04Z');
    assert.equal(hace('2026-09-14 18:21:04', ahora), 'hace 3 h');
    assert.equal(hace('2026-09-14 21:20:04', ahora), 'hace 1 min');
    assert.equal(hace('2026-09-12 18:21:04', ahora), 'hace 2 d');
  });
  it('un reloj adelantado no muestra "hace -5 min"', () => {
    const ahora = new Date('2026-09-14T18:00:00Z');
    assert.equal(hace('2026-09-14 18:21:04', ahora), 'recién');
  });
});

describe('los indicadores', () => {
  const lote = [
    alerta({ risk_score: '87' }),                                        // P1
    alerta({ risk_score: '59' }),                                        // P2
    alerta({ risk_score: '10' }),                                        // P3
    alerta({}, { tiene_caso: false, caso_estado: '', assigned_to: '' }), // sin nada
    alerta({ risk_score: '60' }, { caso_estado: 'closed' }),
  ];

  it('cuenta lo que hace falta decidir', () => {
    const i = indicadores(lote);
    assert.equal(i.total, 5);
    assert.equal(i.p1, 1);
    assert.equal(i.p2, 2);
    assert.equal(i.p3, 1);
    assert.equal(i.sinPuntaje, 1);
    assert.equal(i.sinCaso, 1);
    assert.equal(i.sinAsignar, 1);
    assert.equal(i.conCasoAbierto, 3);   // los 4 con caso menos el cerrado
  });

  it('las prioridades más los sin puntaje suman el total', () => {
    const i = indicadores(lote);
    assert.equal(i.p1 + i.p2 + i.p3 + i.sinPuntaje, i.total);
  });

  it('una lista vacía da ceros y no rompe', () => {
    const i = indicadores([]);
    assert.equal(i.total, 0);
    assert.equal(i.p1, 0);
    assert.deepEqual(indicadores(null).total, 0);
  });
});

describe('¿el caso está abierto?', () => {
  it('cerrado y archivado no lo están', () => {
    assert.equal(esCasoAbierto('closed'), false);
    assert.equal(esCasoAbierto('archived'), false);
  });
  it('un estado que el front no conoce cuenta como abierto', () => {
    // Mejor que aparezca como pendiente y alguien pregunte, a que
    // desaparezca del contador en silencio.
    assert.equal(esCasoAbierto('en_espera_partner'), true);
  });
  it('sin estado, no hay caso abierto', () => {
    assert.equal(esCasoAbierto(''), false);
    assert.equal(esCasoAbierto(undefined), false);
  });
});

describe('por reporte', () => {
  it('cuenta y ordena de mayor a menor', () => {
    const l = [
      { report_name: 'a' }, { report_name: 'b' }, { report_name: 'a' },
    ];
    assert.deepEqual(porReporte(l).map((x) => [x.clave, x.n]), [['a', 2], ['b', 1]]);
  });
  it('usa el nombre del catálogo cuando lo hay', () => {
    const l = [{ report_name: 'small_payin_structuring' }];
    const cat = { small_payin_structuring: 'Estructuración por depósitos chicos' };
    assert.equal(porReporte(l, cat)[0].nombre, 'Estructuración por depósitos chicos');
  });
  it('y si no, al menos algo legible', () => {
    assert.equal(nombreLegible('operation-alert_-_psp_sum_30'),
      'Operation alert psp sum 30');
    assert.equal(nombreLegible(''), '—');
  });
});

describe('los filtros', () => {
  const lote = [
    alerta({ risk_score: '87' }),
    alerta({}, { tiene_caso: false }),
    alerta({}, { assigned_to: '' }),
  ];
  it('P1 deja sólo las P1', () => {
    assert.equal(aplicarFiltro(lote, 'p1').length, 1);
  });
  it('sin caso y sin asignar filtran cosas distintas', () => {
    assert.equal(aplicarFiltro(lote, 'sin_caso').length, 1);
    assert.equal(aplicarFiltro(lote, 'sin_asignar').length, 1);
  });
  it('sin puntaje encuentra las que nunca se midieron', () => {
    assert.equal(aplicarFiltro(lote, 'sin_puntaje').length, 2);
  });
  it('un filtro que no existe no esconde nada', () => {
    assert.equal(aplicarFiltro(lote, 'inventado').length, 3);
    assert.equal(aplicarFiltro(lote, 'todas').length, 3);
  });
});

describe('preparar para la tabla', () => {
  it('aplana lo que la tabla ordena', () => {
    const p = prepararAlerta(alerta({ risk_score: '59', customer_email: 'x@y.cl' }));
    assert.equal(p._score, 59);
    assert.equal(p._prioridad, 'P2');
    assert.equal(p._correo, 'x@y.cl');
    assert.equal(p._caso, 'Abierto');
  });

  it('la prioridad ordena P1 antes que P2, y los sin puntaje al final', () => {
    // Ordenar por el texto "P1"/"P2" funciona por casualidad y se rompe con
    // el null. Por eso va un número aparte.
    assert.equal(prepararAlerta(alerta({ risk_score: '87' }))._prioridadOrden, 1);
    assert.equal(prepararAlerta(alerta({ risk_score: '59' }))._prioridadOrden, 2);
    assert.equal(prepararAlerta(alerta())._prioridadOrden, null);
  });

  it('no pierde los campos originales', () => {
    const p = prepararAlerta(alerta());
    assert.equal(p.alert_id, 'a1');
    assert.equal(p.entity_value, '9000001');
  });
});

describe('normalizar la fila cruda', () => {
  it('parsea el texto JSON que manda el backend', () => {
    // Las 122 alertas de producción traen `row_data` como texto, sin
    // excepción. Tratarlo como objeto devuelve vacío en silencio.
    assert.deepEqual(comoFila('{"customer_email":"a@b.com","monto":5}'),
                     { customer_email: 'a@b.com', monto: 5 });
  });

  it('un objeto pasa tal cual', () => {
    const o = { a: 1 };
    assert.equal(comoFila(o), o);
  });

  it('una lista no es una fila', () => {
    // `[]` pasaría el `typeof === 'object'` y después `Object.entries` daría
    // índices numéricos como si fueran nombres de columna.
    assert.deepEqual(comoFila([1, 2]), {});
    assert.deepEqual(comoFila('[1,2]'), {});
  });

  it('un texto roto no rompe: devuelve vacío', () => {
    assert.deepEqual(comoFila('{esto no es json'), {});
    assert.deepEqual(comoFila('null'), {});
  });

  it('vacío, nulo o de otro tipo dan vacío', () => {
    for (const v of ['', null, undefined, 0, false, 42]) {
      assert.deepEqual(comoFila(v), {}, String(v));
    }
  });

  it('es lo mismo que usa filaDelReporte', () => {
    const a = { row_data: '{"x":1}' };
    assert.deepEqual(filaDelReporte(a), comoFila(a.row_data));
  });
});
