/* El tablero.
 *
 * Agrupar por día suena trivial hasta que aparecen las zonas horarias. El
 * backend manda UTC sin marcarlo; si se agrupara con la fecha local del
 * navegador, todo lo que pasa después de las 21:00 en Chile caería en el día
 * siguiente. La mitad de este archivo prueba eso. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  diaCorto, diaDe, indicadores, porClave, semanaDe, serieDiaria, serieSemanal,
  ultimos, ultimosDias,
} from '../src/comun/tablero.js';

const HOY = new Date('2026-09-21T12:00:00Z');

describe('el día de una marca de tiempo', () => {
  it('agrupa en UTC, no en la hora local', () => {
    // 2026-09-21 23:30 UTC es todavía el 21 en UTC, aunque en algunos husos
    // ya sea el 22. Agrupar por la fecha local movería la alerta de día.
    assert.equal(diaDe('2026-09-21 23:30:00'), '2026-09-21');
    assert.equal(diaDe('2026-09-21 00:30:00'), '2026-09-21');
  });

  it('acepta el formato con T de las corridas', () => {
    assert.equal(diaDe('2026-09-21T01:41:26.381403'), '2026-09-21');
  });

  it('una fecha ilegible devuelve null y no el día de hoy', () => {
    // Caer a hoy metería en el gráfico de hoy cosas que pasaron vaya a saber
    // cuándo, y el pico se vería real.
    for (const v of ['', null, undefined, 'ayer']) assert.equal(diaDe(v), null);
  });
});

describe('la serie diaria', () => {
  it('devuelve un punto por día, incluso los vacíos', () => {
    // Una línea que une el lunes con el jueves dibuja una pendiente suave
    // donde hubo dos días en blanco.
    const s = serieDiaria([], 'created_at', 7, HOY);
    assert.equal(s.length, 7);
    assert.ok(s.every((p) => p.valor === 0));
  });

  it('cuenta en el día que corresponde', () => {
    const e = [
      { created_at: '2026-09-21 10:00:00' },
      { created_at: '2026-09-21 23:00:00' },
      { created_at: '2026-09-20 10:00:00' },
    ];
    const s = serieDiaria(e, 'created_at', 3, HOY);
    assert.deepEqual(s.map((p) => [p.etiqueta, p.valor]),
      [['2026-09-19', 0], ['2026-09-20', 1], ['2026-09-21', 2]]);
  });

  it('lo que cae fuera de la ventana no se cuenta en el borde', () => {
    // Un elemento viejo NO debe sumarse al primer día de la serie: eso
    // pondría un pico falso al inicio de todos los gráficos.
    const s = serieDiaria([{ created_at: '2020-01-01 10:00:00' }], 'created_at', 3, HOY);
    assert.ok(s.every((p) => p.valor === 0));
  });

  it('el último punto es hoy', () => {
    assert.equal(serieDiaria([], 'created_at', 30, HOY).at(-1).etiqueta, '2026-09-21');
  });

  it('los días vienen en orden', () => {
    const d = ultimosDias(5, HOY);
    assert.deepEqual(d, [...d].sort());
  });
});

describe('la serie semanal', () => {
  it('agrupa por el lunes de cada semana', () => {
    // 2026-09-21 es lunes; 2026-09-20, domingo, es de la semana anterior.
    assert.equal(semanaDe('2026-09-21 10:00:00'), '2026-09-21');
    assert.equal(semanaDe('2026-09-20 10:00:00'), '2026-09-14');
    assert.equal(semanaDe('2026-09-22 10:00:00'), '2026-09-21');
  });

  it('el domingo va con la semana que termina, no con la que empieza', () => {
    // El caso que se rompe si se usa getUTCDay() sin corregir: el domingo es
    // 0 y quedaría como inicio de semana.
    assert.equal(semanaDe('2026-09-27 23:59:00'), '2026-09-21');
  });

  it('devuelve una barra por semana, incluso las vacías', () => {
    const s = serieSemanal([], 'created_at', 8, HOY);
    assert.equal(s.length, 8);
    assert.equal(s.at(-1).etiqueta, '2026-09-21');
  });

  it('cuenta en la semana correcta', () => {
    const e = [
      { created_at: '2026-09-21 10:00:00' },
      { created_at: '2026-09-16 10:00:00' },
      { created_at: '2026-09-14 00:00:00' },
    ];
    const s = serieSemanal(e, 'created_at', 3, HOY);
    const m = Object.fromEntries(s.map((x) => [x.etiqueta, x.valor]));
    assert.equal(m['2026-09-21'], 1);
    assert.equal(m['2026-09-14'], 2);
  });

  it('una fecha ilegible no rompe la serie', () => {
    assert.equal(semanaDe('cualquier cosa'), null);
    assert.equal(serieSemanal([{ created_at: 'x' }], 'created_at', 3, HOY).length, 3);
  });
});

describe('contar por clave', () => {
  const e = [
    { r: 'a' }, { r: 'a' }, { r: 'a' }, { r: 'b' }, { r: 'b' }, { r: 'c' }, { r: 'd' },
  ];

  it('ordena de mayor a menor', () => {
    assert.deepEqual(porClave(e, 'r').map((x) => x.etiqueta), ['a', 'b', 'c', 'd']);
  });

  it('lo que no entra en el tope se junta en «otros», no desaparece', () => {
    // Un «top 2» que esconde el resto hace creer que esos dos son casi todo.
    const r = porClave(e, 'r', 2);
    assert.equal(r.length, 3);
    assert.equal(r.at(-1).etiqueta, 'otros');
    assert.equal(r.at(-1).valor, 2);
    assert.equal(r.reduce((a, x) => a + x.valor, 0), e.length);
  });

  it('sin tope devuelve todo', () => {
    assert.equal(porClave(e, 'r').length, 4);
    assert.equal(porClave(e, 'r', 10).length, 4);
  });

  it('un valor ausente se cuenta como "(sin dato)" y no se pierde', () => {
    const r = porClave([{ r: '' }, { r: 'a' }], 'r');
    assert.equal(r.reduce((a, x) => a + x.valor, 0), 2);
    assert.ok(r.some((x) => x.etiqueta === '(sin dato)'));
  });

  it('a igual cuenta, ordena alfabéticamente para que no baile', () => {
    const r = porClave([{ r: 'z' }, { r: 'a' }], 'r');
    assert.deepEqual(r.map((x) => x.etiqueta), ['a', 'z']);
  });
});

describe('recortar a los últimos días', () => {
  it('deja lo que entra en la ventana', () => {
    const e = [
      { created_at: '2026-09-20 10:00:00' },
      { created_at: '2026-09-01 10:00:00' },
    ];
    assert.equal(ultimos(e, 'created_at', 7, HOY).length, 1);
  });
  it('lo ilegible queda fuera, no adentro', () => {
    assert.equal(ultimos([{ created_at: 'x' }], 'created_at', 7, HOY).length, 0);
  });
});

describe('los indicadores del tablero', () => {
  it('cuenta lo que hace falta de un vistazo', () => {
    const i = indicadores({
      alertas: [{ created_at: '2026-09-20 10:00:00' }, { created_at: '2026-01-01 10:00:00' }],
      casos: [
        { status: 'open', sla_estado: 'vencido' },
        { status: 'open', sla_estado: 'en_plazo' },
        { status: 'closed' },
      ],
      listaBlanca: [{}, {}],
      corridas: [{ started_at: '2026-09-20T10:00:00' }],
    }, HOY);
    assert.equal(i.alertas, 2);
    assert.equal(i.alertas7d, 1);
    assert.equal(i.casosAbiertos, 2);
    assert.equal(i.casosVencidos, 1);
    assert.equal(i.listaBlanca, 2);
    assert.equal(i.corridas7d, 1);
  });

  it('sin datos da ceros y no rompe', () => {
    assert.equal(indicadores({}).alertas, 0);
    assert.equal(indicadores({ alertas: null, casos: null }).casosAbiertos, 0);
  });
});

describe('las etiquetas', () => {
  it('el día se muestra corto: el año no aporta en una serie de 30 días', () => {
    assert.equal(diaCorto('2026-09-21'), '21/09');
    assert.equal(diaCorto(''), '');
  });
});
