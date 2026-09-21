/* Historial, lista blanca e institucional.
 *
 * Los casos salen de los datos reales: 50 corridas (49 listas, 1 despertando
 * el cluster), 9 entradas de lista blanca todas vigentes, 127 empresas y 10
 * alertas institucionales — una de ellas pasada 45 veces del umbral. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  COLOR_VIGENCIA, ESTADOS_CORRIDA, RIESGO_EMPRESA, duracion, duracionTexto,
  enCurso, excesoDe, excesoTexto, leerIds, parametros, resumenListaBlanca,
  riesgoDe,
  vigenciaDe,
} from '../src/comun/analisis.js';

describe('el estado de una corrida', () => {
  it('sabe cuáles siguen en curso', () => {
    assert.equal(enCurso('RUNNING'), true);
    assert.equal(enCurso('QUEUED'), true);
    assert.equal(enCurso('RESUMING'), true);   // el cluster despertando
    assert.equal(enCurso('DONE'), false);
    assert.equal(enCurso('ERROR'), false);
  });

  it('un estado desconocido cuenta como en curso', () => {
    // Si el backend agrega un estado, seguir preguntando es lo correcto:
    // darlo por terminado dejaría la pantalla congelada para siempre.
    assert.equal(enCurso('LO_QUE_SEA'), true);
    assert.equal(enCurso(''), true);
    assert.equal(enCurso(undefined), true);
  });

  it('no le importan las mayúsculas', () => {
    assert.equal(enCurso('done'), false);
  });

  it('tiene nombre y color para cada estado que el backend usa', () => {
    for (const e of ['DONE', 'RUNNING', 'RESUMING', 'ERROR']) {
      assert.ok(ESTADOS_CORRIDA[e]?.etiqueta, e);
      assert.ok(ESTADOS_CORRIDA[e]?.color, e);
    }
  });
});

describe('la duración de una corrida', () => {
  const corrida = {
    started_at: '2026-09-21T01:41:26.381403',
    completed_at: '2026-09-21T01:44:35.697685',
  };

  it('la calcula de las dos marcas', () => {
    assert.ok(Math.abs(duracion(corrida) - 189.3) < 1);
  });

  it('una corrida sin terminar no tiene duración', () => {
    assert.equal(duracion({ started_at: corrida.started_at }), null);
  });

  it('si los relojes quedaron cruzados, no inventa un negativo', () => {
    assert.equal(duracion({ started_at: corrida.completed_at,
                            completed_at: corrida.started_at }), null);
  });

  it('se lee en segundos o en minutos según cuánto sea', () => {
    assert.equal(duracionTexto(45), '45 s');
    assert.equal(duracionTexto(189), '3 min 9 s');
    assert.equal(duracionTexto(120), '2 min');
    assert.equal(duracionTexto(null), '—');
  });
});

describe('los parámetros de una corrida', () => {
  it('resume las listas largas en vez de reventar la fila', () => {
    // Una corrida del análisis individual trae 891 ids en un solo campo.
    const p = parametros({ params: JSON.stringify({ customer_ids: Array(891).fill(1) }) });
    assert.deepEqual(p, [{ clave: 'customer_ids', valor: '891 valores' }]);
  });

  it('las listas cortas se muestran enteras', () => {
    const p = parametros({ params: JSON.stringify({ ids: [1, 2, 3] }) });
    assert.equal(p[0].valor, '1, 2, 3');
  });

  it('acepta el objeto ya parseado', () => {
    assert.equal(parametros({ params: { days: 30 } })[0].valor, '30');
  });

  it('un JSON roto se muestra crudo en vez de desaparecer', () => {
    const p = parametros({ params: '{roto' });
    assert.equal(p[0].clave, 'params');
    assert.equal(p[0].valor, '{roto');
  });

  it('sin parámetros, lista vacía', () => {
    assert.deepEqual(parametros({}), []);
    assert.deepEqual(parametros(null), []);
  });
});

describe('la vigencia en la lista blanca', () => {
  const ahora = new Date('2026-09-21T12:00:00Z');

  it('una entrada futura está vigente', () => {
    const v = vigenciaDe({ expires_at: '2026-12-18 01:01:49' }, ahora);
    assert.equal(v.estado, 'vigente');
  });

  it('una entrada pasada está vencida', () => {
    // Importa: una entrada en lista blanca apaga las alertas de ese cliente.
    // Mostrar una vencida como activa haría creer que no se lo está mirando.
    const v = vigenciaDe({ expires_at: '2026-08-01 00:00:00' }, ahora);
    assert.equal(v.estado, 'vencida');
    assert.ok(v.dias < 0);
  });

  it('avisa la semana antes de que venza', () => {
    // Para que nadie se sorprenda cuando el cliente reaparece de golpe.
    assert.equal(vigenciaDe({ expires_at: '2026-09-25 12:00:00' }, ahora).estado, 'por_vencer');
    assert.equal(vigenciaDe({ expires_at: '2026-10-25 12:00:00' }, ahora).estado, 'vigente');
  });

  it('sin fecha de vencimiento es permanente, no un dato faltante', () => {
    assert.equal(vigenciaDe({ expires_at: '' }, ahora).estado, 'permanente');
    assert.equal(vigenciaDe({}, ahora).estado, 'permanente');
  });

  it('una fecha ilegible se dice, no se asume vigente', () => {
    assert.equal(vigenciaDe({ expires_at: 'el mes que viene' }, ahora).estado, 'desconocida');
  });

  it('el borde exacto cuenta como vigente y no como vencida', () => {
    const v = vigenciaDe({ expires_at: '2026-09-21 12:00:00' }, ahora);
    assert.notEqual(v.estado, 'vencida');
  });

  it('todos los estados tienen color', () => {
    for (const e of ['vigente', 'por_vencer', 'vencida', 'permanente', 'desconocida']) {
      assert.ok(COLOR_VIGENCIA[e], e);
    }
  });
});

describe('el resumen de la lista blanca', () => {
  const ahora = new Date('2026-09-21T12:00:00Z');

  it('cuenta por vigencia y los totales cierran', () => {
    const l = [
      { expires_at: '2026-12-18 00:00:00' },
      { expires_at: '2026-09-24 00:00:00' },
      { expires_at: '2026-01-01 00:00:00' },
      { expires_at: '' },
    ];
    const r = resumenListaBlanca(l, ahora);
    assert.equal(r.total, 4);
    assert.equal(r.vigente, 1);
    assert.equal(r.por_vencer, 1);
    assert.equal(r.vencida, 1);
    assert.equal(r.permanente, 1);
    assert.equal(r.vigente + r.por_vencer + r.vencida + r.permanente + r.desconocida, r.total);
  });

  it('una lista vacía da ceros', () => {
    assert.equal(resumenListaBlanca([]).total, 0);
    assert.equal(resumenListaBlanca(null).total, 0);
  });
});

describe('el riesgo de una empresa', () => {
  it('traduce los tres niveles del backend', () => {
    assert.equal(riesgoDe({ risk_level: 'High' }).etiqueta, 'Alto');
    assert.equal(riesgoDe({ risk_level: 'Medium' }).etiqueta, 'Medio');
    assert.equal(riesgoDe({ risk_level: 'Low' }).etiqueta, 'Bajo');
  });

  it('un nivel desconocido devuelve null, no "bajo"', () => {
    // Que la pantalla lo muestre crudo es correcto; pintarlo de verde no.
    assert.equal(riesgoDe({ risk_level: 'Critical' }), null);
    assert.equal(riesgoDe({}), null);
  });

  it('el orden va de más grave a menos', () => {
    assert.ok(RIESGO_EMPRESA.High.orden < RIESGO_EMPRESA.Medium.orden);
    assert.ok(RIESGO_EMPRESA.Medium.orden < RIESGO_EMPRESA.Low.orden);
  });
});

describe('el exceso sobre el umbral', () => {
  it('dice cuántas veces se pasó', () => {
    // Una alerta real: USD 4.525.150 contra un umbral de 100.000.
    assert.ok(Math.abs(excesoDe({ valor: 4525150.41, umbral: 100000 }) - 45.25) < 0.01);
    assert.equal(excesoTexto(45.25), '45×');
    assert.equal(excesoTexto(1.3), '1.3×');
  });

  it('un umbral de cero no divide por cero', () => {
    assert.equal(excesoDe({ valor: 100, umbral: 0 }), null);
    assert.equal(excesoTexto(null), '—');
  });

  it('valores que no son números devuelven null', () => {
    assert.equal(excesoDe({ valor: 'mucho', umbral: 100 }), null);
    assert.equal(excesoDe({}), null);
  });
});

describe('los ids del análisis individual', () => {
  it('acepta cualquier separador que la gente use', () => {
    // Llegan pegados de un Excel, de Slack o de una consulta. Pedir un
    // formato exacto sólo agrega un paso manual que se hace mal.
    assert.deepEqual(leerIds('111, 222\n333  444;555'),
      ['111', '222', '333', '444', '555']);
  });
  it('no deja entradas vacías por separadores repetidos', () => {
    assert.deepEqual(leerIds(',,111,,  ,222,'), ['111', '222']);
  });
  it('un texto vacío da lista vacía, no [""]', () => {
    for (const v of ['', '   ', null, undefined]) {
      assert.deepEqual(leerIds(v), [], String(v));
    }
  });
  it('no descarta ids que no son numéricos', () => {
    // El backend acepta otros identificadores; filtrarlos acá los perdería
    // en silencio.
    assert.deepEqual(leerIds('76.543.210-K, 111'), ['76.543.210-K', '111']);
  });
});
