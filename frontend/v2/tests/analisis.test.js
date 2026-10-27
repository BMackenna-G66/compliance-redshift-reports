/* Historial, lista blanca e institucional.
 *
 * Los casos salen de los datos reales: 50 corridas (49 listas, 1 despertando
 * el cluster), 9 entradas de lista blanca todas vigentes, 127 empresas y 10
 * alertas institucionales — una de ellas pasada 45 veces del umbral. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  COLOR_VIGENCIA, ESTADOS_CORRIDA, RIESGO_EMPRESA, duracion, duracionTexto,
  enCurso, estadoWhitelist, excesoDe, excesoTexto, leerIds, parametros,
  puedeAprobarWhitelist, resumenListaBlanca,
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
    assert.deepEqual(leerIds('11.111.111-K, 111'), ['11.111.111-K', '111']);
  });
});

describe('la aprobación de la lista blanca', () => {
  const pendiente = {
    entity_value: '9000001', estado: 'pendiente', duration_days: 90,
    solicitado_por: 'analista@global66.com', expires_at: '',
  };

  it('UNA PENDIENTE NO SE MUESTRA COMO PERMANENTE', () => {
    /* No tiene `expires_at` porque el reloj arranca al aprobarla. Sin la
       regla nueva caía en «Permanente», en azul, como si silenciara para
       siempre — justo lo contrario de lo que hace. */
    assert.equal(vigenciaDe(pendiente).estado, 'pendiente');
    assert.equal(vigenciaDe(pendiente).etiqueta, 'Sin aprobar');
    assert.ok(COLOR_VIGENCIA.pendiente);
  });

  it('una entrada vieja sin estado se marca «Sin aprobación»', () => {
    /* Las 49 que ya estaban al 27-10-2026. Siguen aplicando hasta vencer,
       pero la pantalla no las presenta como firmadas. */
    assert.equal(estadoWhitelist({ entity_value: '9' }).clave, 'heredada');
    assert.equal(estadoWhitelist({ entity_value: '9' }).etiqueta, 'Sin aprobación');
  });

  it('un estado inventado no se dibuja como si fuera bueno', () => {
    assert.equal(estadoWhitelist({ estado: 'aprobadisima' }).clave, 'heredada');
  });

  it('UN OFICIAL DISTINTO DEL QUE PIDIÓ PUEDE FIRMAR', () => {
    const r = puedeAprobarWhitelist(pendiente, 'oficial@global66.com', true);
    assert.equal(r.puede, true);
  });

  it('EL QUE LA PIDIÓ NO PUEDE FIRMARLA', () => {
    /* Cuatro ojos: si el que pide puede firmar, el paso se completa solo. */
    const r = puedeAprobarWhitelist(pendiente, 'analista@global66.com', true);
    assert.equal(r.puede, false);
    assert.match(r.motivo, /pediste vos/);
  });

  it('el cuatro ojos mira también created_by, que es lo que manda la v1', () => {
    const e = { ...pendiente, solicitado_por: '', created_by: 'Analista@Global66.com' };
    assert.equal(puedeAprobarWhitelist(e, 'analista@global66.com', true).puede, false);
  });

  it('quien no es Oficial no firma, y el botón dice por qué', () => {
    const r = puedeAprobarWhitelist(pendiente, 'otro@global66.com', false);
    assert.equal(r.puede, false);
    assert.match(r.motivo, /Oficial de Cumplimiento/);
  });

  it('una ya aprobada no se vuelve a firmar', () => {
    const e = { ...pendiente, estado: 'aprobada' };
    assert.equal(puedeAprobarWhitelist(e, 'oficial@global66.com', true).puede, false);
  });

  it('EL MOTIVO NUNCA VIENE VACÍO CUANDO NO SE PUEDE', () => {
    /* Va al `title` del botón apagado. Uno gris y mudo hace que la gente
       apriete tres veces y después pregunte por chat. */
    for (const caso of [
      [pendiente, 'analista@global66.com', true],
      [pendiente, 'otro@global66.com', false],
      [{ ...pendiente, estado: 'aprobada' }, 'oficial@global66.com', true],
    ]) {
      const r = puedeAprobarWhitelist(caso[0], caso[1], caso[2]);
      assert.equal(r.puede, false);
      assert.ok(r.motivo.length > 10);
    }
  });

  it('el resumen cuenta las pendientes aparte', () => {
    const r = resumenListaBlanca([pendiente, { expires_at: '2099-01-01 00:00:00' }]);
    assert.equal(r.pendiente, 1);
    assert.equal(r.total, 2);
  });
});
