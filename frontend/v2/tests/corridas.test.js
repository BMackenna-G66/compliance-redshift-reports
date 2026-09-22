/* Ejecutar reportes.
 *
 * Lo que se prueba es la máquina de estados del sondeo, porque sus dos fallas
 * son invisibles: uno que no se apaga le pega a la API para siempre, y uno
 * que se apaga de más deja la corrida colgada en «ejecutando» aunque haya
 * terminado. Ninguna de las dos tira un error. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  avisoDeRecorte, columnasDe, cuerpoDeEjecucion, estadoDe, faltaParaGuardarConsulta,
  nombreDeConsultaValido, parametrosPorDefecto, pareceEscritura, primerDiaDelMes,
  seguirCorrida, termino,
} from '../src/comun/corridas.js';

/* Un sondeo sin esperas reales: el test no puede tardar dos segundos por
   vuelta. `dormir` y `ahora` son inyectables justo para esto. */
function sondeoInstantaneo(extra = {}) {
  let reloj = 0;
  return {
    dormir: async () => { reloj += 2000; },
    ahora: () => reloj,
    espera: 0,
    ...extra,
  };
}

describe('cuándo terminó una corrida', () => {
  it('DONE y ERROR terminan', () => {
    assert.equal(termino('DONE'), true);
    assert.equal(termino('ERROR'), true);
  });

  it('RUNNING no', () => {
    assert.equal(termino('RUNNING'), false);
  });

  it('un estado desconocido NO termina: se sigue preguntando', () => {
    // Al revés —dar por terminado lo que no se reconoce— dejaría la corrida
    // colgada en la pantalla aunque en el backend siguiera avanzando.
    assert.equal(termino('QUEUED'), false);
    assert.equal(termino(''), false);
    assert.equal(termino(undefined), false);
  });

  it('el estado se lee sin importar la caja', () => {
    assert.equal(termino('done'), true);
  });

  it('un estado que no está en el mapa se pinta como ejecutando', () => {
    assert.equal(estadoDe({ status: 'QUEUED' }).etiqueta, 'Ejecutando');
    assert.equal(estadoDe({ status: 'DONE' }).etiqueta, 'Lista');
  });
});

describe('los parámetros de un reporte', () => {
  const hoy = new Date('2026-09-22T12:00:00Z');

  it('una fecha arranca el primer día del mes', () => {
    assert.equal(primerDiaDelMes(hoy), '2026-09-01');
  });

  it('el mes se rellena con cero', () => {
    assert.equal(primerDiaDelMes(new Date('2026-03-15T12:00:00Z')), '2026-03-01');
  });

  it('`first_day_of_month` se resuelve, no se manda como texto', () => {
    // El catálogo declara ese literal; mandarlo tal cual haría que el backend
    // reciba una fecha que no es una fecha.
    const r = { params: [{ name: 'since_date', type: 'date', default: 'first_day_of_month' }] };
    assert.equal(parametrosPorDefecto(r, hoy).since_date, '2026-09-01');
  });

  it('una fecha con default propio lo respeta', () => {
    const r = { params: [{ name: 'd', type: 'date', default: '2020-01-01' }] };
    assert.equal(parametrosPorDefecto(r, hoy).d, '2020-01-01');
  });

  it('un booleano sin default arranca en false, no en undefined', () => {
    // `undefined` se cae del JSON y el backend recibe el parámetro ausente,
    // que no es lo mismo que «no».
    const r = { params: [{ name: 'only_successful', type: 'bool' }] };
    assert.strictEqual(parametrosPorDefecto(r, hoy).only_successful, false);
  });

  it('un booleano con default en true lo conserva', () => {
    const r = { params: [{ name: 'x', type: 'bool', default: true }] };
    assert.strictEqual(parametrosPorDefecto(r, hoy).x, true);
  });

  it('un reporte sin parámetros no rompe', () => {
    assert.deepEqual(parametrosPorDefecto({}, hoy), {});
    assert.deepEqual(parametrosPorDefecto(null, hoy), {});
  });

  it('el cuerpo lleva el nombre del reporte y los valores', () => {
    const c = cuerpoDeEjecucion({ report_name: 'r1' }, { since_date: '2026-09-01' });
    assert.equal(c.report_name, 'r1');
    assert.equal(c.since_date, '2026-09-01');
    assert.equal(c.keep_session, true);
  });
});

describe('el sondeo de una corrida', () => {
  it('pregunta hasta que termina y devuelve el resultado', async () => {
    const respuestas = [{ status: 'RUNNING' }, { status: 'RUNNING' }, { status: 'DONE', row_count: 7 }];
    let i = 0;
    const d = await seguirCorrida(async () => respuestas[i++], 'r1', sondeoInstantaneo());
    assert.equal(d.status, 'DONE');
    assert.equal(d.row_count, 7);
    assert.equal(i, 3, 'tiene que haber preguntado tres veces');
  });

  it('avisa de cada vuelta para que la pantalla muestre que sigue viva', async () => {
    const respuestas = [{ status: 'RUNNING' }, { status: 'DONE' }];
    let i = 0;
    const vistos = [];
    await seguirCorrida(async () => respuestas[i++], 'r1',
      sondeoInstantaneo({ alAvanzar: (d) => vistos.push(d.status) }));
    assert.deepEqual(vistos, ['RUNNING', 'DONE']);
  });

  it('se corta cuando la pantalla se fue', async () => {
    // Sin esto el sondeo sigue pegándole a la API contra un componente que ya
    // no existe, y cada navegación deja uno más andando.
    let llamadas = 0;
    const d = await seguirCorrida(async () => { llamadas++; return { status: 'RUNNING' }; },
      'r1', sondeoInstantaneo({ cancelado: () => true }));
    assert.equal(d.status, 'ERROR');
    assert.equal(llamadas, 0, 'no tenía que preguntar ni una vez');
  });

  it('un error de red no cancela la corrida: reintenta', async () => {
    // La corrida sigue andando en el backend; cortar acá la daría por muerta
    // cuando en realidad va a terminar bien.
    const respuestas = [null, { status: 'DONE' }];
    let i = 0;
    const d = await seguirCorrida(async () => {
      const r = respuestas[i++];
      if (r === null) throw new Error('red');
      return r;
    }, 'r1', sondeoInstantaneo());
    assert.equal(d.status, 'DONE');
  });

  it('se rinde a los quince minutos en vez de preguntar toda la tarde', async () => {
    let llamadas = 0;
    const d = await seguirCorrida(async () => { llamadas++; return { status: 'RUNNING' }; },
      'r1', sondeoInstantaneo());
    assert.equal(d.status, 'ERROR');
    assert.match(d.error_message, /quince minutos|15 minutos/i);
    // 15 min / 2 s = 450 vueltas. Que sea finito es el punto.
    assert.ok(llamadas > 0 && llamadas <= 460, `fueron ${llamadas} vueltas`);
  });

  it('el mensaje del plantón dice que la corrida quedó lanzada', async () => {
    // Importa: la consulta sigue en Redshift y el Excel va a aparecer en el
    // historial. Decir sólo «falló» haría que alguien la vuelva a correr.
    const d = await seguirCorrida(async () => ({ status: 'RUNNING' }), 'r1', sondeoInstantaneo());
    assert.match(d.error_message, /Historial/);
  });
});

describe('el resultado', () => {
  it('las columnas salen de la primera fila', () => {
    assert.deepEqual(columnasDe([{ a: 1, b: 2 }]), ['a', 'b']);
  });

  it('sin filas no hay columnas y no rompe', () => {
    assert.deepEqual(columnasDe([]), []);
    assert.deepEqual(columnasDe(null), []);
  });

  it('el recorte se avisa con las dos cifras', () => {
    // Sin el aviso, alguien cuenta las filas de la pantalla y concluye sobre
    // un subconjunto sin saber que lo es.
    const t = avisoDeRecorte({ truncated: true, count: 5000, total: 84210 });
    assert.match(t, /5\.000/);
    assert.match(t, /84\.210/);
    assert.match(t, /Excel/);
  });

  it('el motivo del backend manda si viene', () => {
    const t = avisoDeRecorte({ truncated: true, count: 10, total: 99, reason: 'el resultado pesa 40 MB' });
    assert.match(t, /40 MB/);
  });

  it('sin recorte no hay aviso', () => {
    assert.equal(avisoDeRecorte({ truncated: false, count: 10 }), '');
    assert.equal(avisoDeRecorte(null), '');
  });
});

describe('guardar una consulta', () => {
  const buena = { report_name: 'clientes_peru', display_name: 'Clientes de Perú', sql: 'select 1' };

  it('acepta un nombre de código', () => {
    assert.equal(nombreDeConsultaValido('clientes_peru'), true);
    assert.equal(nombreDeConsultaValido('r2d2_v2'), true);
  });

  it('rechaza lo que rompería la ruta de borrado', () => {
    // `DELETE /queries/{nombre}` va en la URL: espacios y acentos la parten.
    for (const n of ['Clientes de Perú', 'con espacio', 'MAYUS', '2empieza_con_numero', 'ab', '']) {
      assert.equal(nombreDeConsultaValido(n), false, n);
    }
  });

  it('una consulta completa no tiene faltantes', () => {
    assert.deepEqual(faltaParaGuardarConsulta(buena), []);
  });

  it('dice los tres campos que faltan, no «error 400»', () => {
    const f = faltaParaGuardarConsulta({});
    assert.equal(f.length, 3);
    assert.ok(f.some((x) => /nombre de código/.test(x)));
    assert.ok(f.some((x) => /nombre visible/.test(x)));
    assert.ok(f.some((x) => /SQL/.test(x)));
  });

  it('un nombre inválido se explica, no se reporta como ausente', () => {
    const f = faltaParaGuardarConsulta({ ...buena, report_name: 'Con Espacios' });
    assert.equal(f.length, 1);
    assert.match(f[0], /minúsculas/);
  });

  it('caza el SQL que escribe', () => {
    // Este módulo lee Redshift. Una consulta guardada que borra filas es un
    // incidente, no un error de sintaxis.
    for (const s of ['DELETE FROM x', 'drop table y', 'update a set b=1',
                     'select 1; truncate z']) {
      assert.equal(pareceEscritura(s), true, s);
    }
  });

  it('no confunde un select que menciona esas palabras en un nombre', () => {
    assert.equal(pareceEscritura('select created_at from updates_log'), false);
    assert.equal(pareceEscritura('select * from alerts'), false);
  });
});
