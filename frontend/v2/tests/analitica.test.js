/* Los analíticos del tablero.
 *
 * Estas tres consultas no funcionan como el resto: se disparan y se cosechan
 * después. Lo que se prueba es la cosecha —que no se rinda antes de tiempo, y
 * que muestre lo parcial en vez de dejar la pantalla en blanco— y las
 * lecturas que convierten lo que manda el backend en algo mostrable. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  ANALITICOS, cierrePorPrioridad, puntos, serie, total, traerAnalitico, vencidos,
} from '../src/comun/analitica.js';

function sinEsperas(extra = {}) {
  return { dormir: async () => {}, espera: 0, ...extra };
}

describe('la cosecha de un analítico', () => {
  it('dispara, cosecha y devuelve cuando todas terminaron', async () => {
    const respuestas = {
      '/analytics/summary': { stmt_ids: ['a', 'b'] },
    };
    const cosechas = [
      { all_done: false, cases_by_status: [{ status: 'open', n: 3 }] },
      { all_done: true, cases_by_status: [{ status: 'open', n: 3 }], top_entities: [] },
    ];
    let i = 0;
    const r = await traerAnalitico(async (ruta) => (
      respuestas[ruta] !== undefined ? respuestas[ruta] : cosechas[i++]
    ), 'gestion', sinEsperas());
    assert.equal(r.completo, true);
    assert.equal(r.datos.all_done, true);
  });

  it('los ids se mandan separados por coma', async () => {
    let rutaCosecha = '';
    await traerAnalitico(async (ruta) => {
      if (ruta === '/analytics/summary') return { stmt_ids: ['s1', 's2', 's3'] };
      rutaCosecha = ruta;
      return { all_done: true };
    }, 'gestion', sinEsperas());
    assert.match(rutaCosecha, /stmt_ids=s1%2Cs2%2Cs3/);
  });

  it('muestra lo parcial en cada vuelta', async () => {
    // `all_done: false` no significa vacío: algunas series ya llegaron.
    // Esperar a que estén todas hace esperar por la más lenta.
    const vistos = [];
    const cosechas = [
      { all_done: false, cases_by_status: [{ status: 'open', n: 1 }] },
      { all_done: true, cases_by_status: [{ status: 'open', n: 1 }] },
    ];
    let i = 0;
    await traerAnalitico(async (ruta) => (
      ruta === '/analytics/summary' ? { stmt_ids: ['a'] } : cosechas[i++]
    ), 'gestion', sinEsperas({ alAvanzar: (d) => vistos.push(d.all_done) }));
    assert.deepEqual(vistos, [false, true]);
  });

  it('sin stmt_ids no cosecha, y dice por qué', async () => {
    // Pasa con el cluster apagado: el backend no dispara nada.
    const r = await traerAnalitico(async () => ({ stmt_ids: [] }), 'gestion', sinEsperas());
    assert.equal(r.completo, false);
    assert.match(r.motivo, /cluster/i);
  });

  it('un error de red no cancela: reintenta', async () => {
    // Las consultas siguen corriendo en Redshift; darlas por muertas obliga a
    // dispararlas de nuevo y a pagarlas dos veces.
    const cosechas = [null, { all_done: true }];
    let i = 0;
    const r = await traerAnalitico(async (ruta) => {
      if (ruta === '/analytics/summary') return { stmt_ids: ['a'] };
      const v = cosechas[i++];
      if (v === null) throw new Error('red');
      return v;
    }, 'gestion', sinEsperas());
    assert.equal(r.completo, true);
  });

  it('se rinde con lo que tenga, en vez de girar para siempre', async () => {
    const r = await traerAnalitico(async (ruta) => (
      ruta === '/analytics/summary' ? { stmt_ids: ['a'] }
        : { all_done: false, cases_by_status: [{ status: 'open', n: 9 }] }
    ), 'gestion', sinEsperas());
    assert.equal(r.completo, false);
    assert.match(r.motivo, /parcial/);
    // Lo que llegó no se tira.
    assert.equal(serie(r.datos, 'cases_by_status')[0].n, 9);
  });

  it('se corta cuando la pantalla se fue', async () => {
    let vueltas = 0;
    const r = await traerAnalitico(async (ruta) => {
      if (ruta === '/analytics/summary') return { stmt_ids: ['a'] };
      vueltas += 1;
      return { all_done: false };
    }, 'gestion', sinEsperas({ cancelado: () => true }));
    assert.equal(vueltas, 0);
    assert.equal(r.completo, false);
  });

  it('un analítico que no existe se avisa, no se ignora', async () => {
    await assert.rejects(() => traerAnalitico(async () => ({}), 'inventado', sinEsperas()),
                         /desconocido/);
  });

  it('los tres analíticos tienen disparo y cosecha', () => {
    for (const [k, v] of Object.entries(ANALITICOS)) {
      assert.ok(v.disparo.startsWith('/'), k);
      assert.ok(v.cosecha.startsWith('/'), k);
      assert.ok(v.titulo && v.pie, k);
    }
  });
});

describe('leer las series', () => {
  it('lo que no es lista se lee como lista vacía', () => {
    // El backend manda `null` para una consulta que todavía no terminó;
    // recorrerlo directamente rompería la pantalla.
    assert.deepEqual(serie({ x: null }, 'x'), []);
    assert.deepEqual(serie(null, 'x'), []);
    assert.deepEqual(serie({}, 'x'), []);
  });

  it('los puntos conservan los ceros', () => {
    // Una semana sin casos es un dato. Saltearla dibuja una línea que une dos
    // semanas lejanas con una pendiente que no existió.
    const p = puntos([{ week_start: 'a', n: 3 }, { week_start: 'b', n: 0 }], 'week_start');
    assert.deepEqual(p, [{ etiqueta: 'a', valor: 3 }, { etiqueta: 'b', valor: 0 }]);
  });

  it('el total suma y no rompe con valores raros', () => {
    assert.equal(total([{ n: 3 }, { n: '4' }, { n: null }, {}]), 7);
    assert.equal(total([]), 0);
  });
});

describe('los vencidos', () => {
  const datos = {
    overdue: [{
      total_open: 61, critical_overdue: 2, high_overdue: 40,
      medium_overdue: 20, low_overdue: 7,
    }],
  };

  it('suma los cuatro niveles', () => {
    assert.equal(vencidos(datos).vencidos, 69);
  });

  it('sin datos da ceros, no «undefined»', () => {
    const v = vencidos({});
    assert.equal(v.abiertos, 0);
    assert.equal(v.vencidos, 0);
  });

  it('una clave que falte cuenta como cero', () => {
    const v = vencidos({ overdue: [{ total_open: 5, high_overdue: 2 }] });
    assert.equal(v.abiertos, 5);
    assert.equal(v.vencidos, 2);
  });
});

describe('el tiempo de cierre', () => {
  it('pasa las horas a días', () => {
    // El plazo de compliance está escrito en días; dejarlo en horas obliga a
    // hacer la cuenta mentalmente cada vez que se mira.
    const c = cierrePorPrioridad({
      avg_resolution: [{ priority: 'high', avg_hours: 72, total_closed: 10 }],
    });
    assert.equal(c[0].dias, 3);
    assert.equal(c[0].cerrados, 10);
  });

  it('sin prioridad no muestra «undefined»', () => {
    const c = cierrePorPrioridad({ avg_resolution: [{ avg_hours: 24 }] });
    assert.equal(c[0].prioridad, '—');
  });

  it('sin datos devuelve una lista vacía', () => {
    assert.deepEqual(cierrePorPrioridad({}), []);
  });
});
