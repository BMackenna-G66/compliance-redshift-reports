/* Casos y el semáforo del plazo.
 *
 * Los casos de prueba salen de los 89 casos reales: 69 vencidos y ninguno en
 * plazo, 49 sin un solo contacto al cliente, uno cerrado que tardó 61 días.
 * Esas son las formas que la pantalla tiene que aguantar hoy — no las del
 * prototipo, donde todo está prolijo. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  COLUMNAS_KANBAN, FILTROS_CASO, aplicarFiltro, diasDe, diasTexto,
  diasVencido, estaAbierto, etiquetaSla, indicadores, porAnalista, porColumna,
  prepararCaso, semaforoDe, sinContactar, tiempoDeCierre,
} from '../src/comun/casos.js';

/* Un caso con la forma que devuelve `GET /cases`. Identificadores
   inventados: el repo es público. */
function caso(extra = {}) {
  return {
    case_id: 'c-1',
    status: 'open',
    priority: 'high',
    entity_id: '9000001',
    assigned_to: 'analista@global66.com',
    created_at: '2026-09-14 18:30:50',
    updated_at: '2026-09-14 18:30:51',
    closed_at: '',
    note_count: 0,
    sla_aplica: true,
    sla_estado: 'vencido',
    sla_etiqueta: 'Vencido',
    sla_dias: 6.75,
    sla_horas: 161.9,
    sla_horas_restantes: -89.9,
    sla_contactos: 0,
    sla_respondio: false,
    ...extra,
  };
}

describe('abierto o cerrado', () => {
  it('cerrado y archivado no están abiertos', () => {
    assert.equal(estaAbierto(caso({ status: 'closed' })), false);
    assert.equal(estaAbierto(caso({ status: 'archived' })), false);
  });
  it('un estado nuevo del backend cuenta como abierto', () => {
    // Que aparezca como pendiente y alguien pregunte es mejor que
    // desaparecer del recuento sin que nadie se entere.
    assert.equal(estaAbierto(caso({ status: 'esperando_partner' })), true);
  });
});

describe('el semáforo', () => {
  it('ordena por urgencia y no por alfabeto', () => {
    // "Cerrado" antes que "Vencido" alfabéticamente es exactamente lo que no
    // se quiere en una lista que se mira para decidir qué atender.
    const orden = ['vencido', 'por_contactar', 'por_recontactar', 'en_plazo', 'cerrado']
      .map((e) => semaforoDe(caso({ sla_estado: e })).orden);
    assert.deepEqual(orden, [...orden].sort((a, b) => a - b));
  });

  it('un caso sin reloj no es "en plazo"', () => {
    // No tiene plazo, que no es lo mismo que ir bien de tiempo.
    const c = caso({ sla_aplica: false, sla_estado: '', sla_etiqueta: 'Sin plazo' });
    assert.equal(etiquetaSla(c), 'Sin plazo');
    assert.notEqual(semaforoDe(c).orden, semaforoDe(caso({ sla_estado: 'en_plazo' })).orden);
  });

  it('usa la etiqueta del backend, no una propia', () => {
    // El plazo lo define sla_casos.py; si el backend renombra un estado, la
    // pantalla lo sigue sin que haya que tocarla.
    assert.equal(etiquetaSla(caso({ sla_etiqueta: 'Vencido hace rato' })), 'Vencido hace rato');
  });

  it('si el backend no manda etiqueta, hay un respaldo', () => {
    assert.equal(etiquetaSla(caso({ sla_etiqueta: '', sla_estado: 'vencido' })), 'Vencido');
  });

  it('un estado que el front no conoce no deja la celda vacía', () => {
    const c = caso({ sla_estado: 'inventado', sla_etiqueta: 'Inventado' });
    assert.equal(etiquetaSla(c), 'Inventado');
  });
});

describe('los días', () => {
  it('un caso sin reloj no lleva "0 días"', () => {
    // Cero diría que se abrió hoy. No se le mide el tiempo, es distinto.
    assert.equal(diasDe(caso({ sla_dias: null })), null);
    assert.equal(diasTexto(null), '—');
  });

  it('da vuelta las horas restantes negativas', () => {
    // El backend manda -89,9 horas; la pantalla tiene que decir "4 días
    // vencido" y no obligar a hacer la cuenta mentalmente.
    assert.ok(Math.abs(diasVencido(caso({ sla_horas_restantes: -89.9 })) - 3.746) < 0.01);
  });

  it('un caso que todavía está en plazo no está vencido', () => {
    assert.equal(diasVencido(caso({ sla_horas_restantes: 12 })), null);
    assert.equal(diasVencido(caso({ sla_horas_restantes: 0 })), null);
  });

  it('un caso cerrado no tiene horas restantes', () => {
    assert.equal(diasVencido(caso({ sla_horas_restantes: null })), null);
  });

  it('menos de un día se dice en horas', () => {
    assert.equal(diasTexto(0.5), '12 h');
    assert.equal(diasTexto(3), '3 días');
    assert.equal(diasTexto(1), '1 día');
  });
});

describe('los indicadores', () => {
  const lote = [
    caso({ case_id: '1' }),                                              // abierto, vencido, sin contactar
    caso({ case_id: '2', sla_contactos: 2 }),                            // abierto, vencido, contactado
    caso({ case_id: '3', status: 'closed', sla_estado: 'cerrado' }),     // cerrado
    caso({ case_id: '4', assigned_to: '' }),                             // sin asignar
    caso({ case_id: '5', sla_aplica: false, sla_estado: '' }),           // sin reloj
    caso({ case_id: '6', sla_respondio: true, sla_contactos: 1 }),       // respondió
  ];

  it('cuenta lo que hace falta decidir', () => {
    const i = indicadores(lote);
    assert.equal(i.total, 6);
    assert.equal(i.abiertos, 5);
    assert.equal(i.vencidos, 4);        // los abiertos con sla_estado vencido
    assert.equal(i.sinAsignar, 1);
    assert.equal(i.respondieron, 1);
    assert.equal(i.sinReloj, 1);
  });

  it('"sin contactar" cuenta sólo los abiertos', () => {
    // Un caso cerrado al que nunca se contactó ya no es trabajo pendiente.
    // Mezclarlos inflaría el número que se supone que empuja a actuar.
    const conCerradoSinContacto = [...lote,
      caso({ case_id: '7', status: 'closed', sla_contactos: 0 })];
    assert.equal(indicadores(conCerradoSinContacto).porContactar,
                 indicadores(lote).porContactar);
  });

  it('"sin contactar" no cuenta los casos sin reloj', () => {
    // Un caso que no vino de una alerta no tiene a quién recontactar por
    // plazo: no le corresponde ese pendiente.
    assert.equal(indicadores([caso({ sla_aplica: false, sla_contactos: 0 })]).porContactar, 0);
  });

  it('una lista vacía da ceros y no rompe', () => {
    assert.equal(indicadores([]).abiertos, 0);
    assert.equal(indicadores(null).total, 0);
  });
});

describe('el tiempo de cierre', () => {
  it('la mediana no la decide el caso extremo', () => {
    // Con 15 cerrados reales y uno de 61 días, el promedio lo decide ese solo.
    const l = [1, 2, 3, 61].map((d) => caso({ status: 'closed', sla_dias: d }));
    const t = tiempoDeCierre(l);
    assert.equal(t.mediana, 2.5);
    assert.ok(t.promedio > 16);
  });

  it('cuenta cuántos cerraron dentro del plazo de 3 días', () => {
    const l = [1, 2, 4, 61].map((d) => caso({ status: 'closed', sla_dias: d }));
    assert.equal(tiempoDeCierre(l).enPlazo, 2);
  });

  it('ignora los que siguen abiertos', () => {
    assert.equal(tiempoDeCierre([caso({ status: 'open', sla_dias: 9 })]).n, 0);
  });

  it('sin casos cerrados devuelve null, no cero', () => {
    // Cero días de cierre promedio diría que se cierran al instante.
    const t = tiempoDeCierre([]);
    assert.equal(t.mediana, null);
    assert.equal(t.promedio, null);
  });
});

describe('el kanban', () => {
  it('arma las cuatro columnas aunque estén vacías', () => {
    const cols = porColumna([]);
    assert.deepEqual(cols.map((c) => c.clave), COLUMNAS_KANBAN);
  });

  it('un estado desconocido se lleva su propia columna, no se descarta', () => {
    // Tirar casos porque el backend agregó un estado sería perder trabajo de
    // vista sin que nadie se entere.
    const cols = porColumna([caso({ status: 'esperando_partner' })]);
    const extra = cols.find((c) => c.clave === 'esperando_partner');
    assert.ok(extra);
    assert.equal(extra.items.length, 1);
    assert.equal(cols.length, COLUMNAS_KANBAN.length + 1);
  });

  it('un caso sin estado no desaparece', () => {
    const cols = porColumna([caso({ status: '' })]);
    assert.equal(cols.find((c) => c.clave === 'sin_estado').items.length, 1);
  });

  it('dentro de la columna, lo más urgente arriba', () => {
    const cols = porColumna([
      caso({ case_id: 'plazo', sla_estado: 'en_plazo' }),
      caso({ case_id: 'venc', sla_estado: 'vencido' }),
      caso({ case_id: 'recon', sla_estado: 'por_recontactar' }),
    ]);
    const abiertos = cols.find((c) => c.clave === 'open').items.map((c) => c.case_id);
    assert.deepEqual(abiertos, ['venc', 'recon', 'plazo']);
  });

  it('a igual urgencia, primero el que lleva más tiempo', () => {
    const cols = porColumna([
      caso({ case_id: 'nuevo', sla_dias: 4 }),
      caso({ case_id: 'viejo', sla_dias: 47 }),
    ]);
    assert.deepEqual(cols[0].items.map((c) => c.case_id), ['viejo', 'nuevo']);
  });
});

describe('los filtros', () => {
  const lote = [
    caso({ case_id: '1' }),
    caso({ case_id: '2', status: 'closed' }),
    caso({ case_id: '3', assigned_to: '' }),
    caso({ case_id: '4', sla_respondio: true }),
  ];
  it('todos los filtros salvo "todos" dejan fuera los cerrados', () => {
    for (const clave of Object.keys(FILTROS_CASO)) {
      if (clave === 'todos') continue;
      const r = aplicarFiltro(lote, clave);
      assert.ok(!r.some((c) => c.status === 'closed'), clave);
    }
  });
  it('"todos" no esconde nada', () => {
    assert.equal(aplicarFiltro(lote, 'todos').length, 4);
    assert.equal(aplicarFiltro(lote, 'no_existe').length, 4);
  });
  it('sin asignar y respondieron filtran cosas distintas', () => {
    assert.equal(aplicarFiltro(lote, 'sin_asignar').length, 1);
    assert.equal(aplicarFiltro(lote, 'respondieron').length, 1);
  });
});

describe('la carga por analista', () => {
  it('cuenta sólo los abiertos', () => {
    // La carga es lo que cada uno tiene encima ahora, no lo que despachó.
    const l = [
      caso({ assigned_to: 'a@global66.com' }),
      caso({ assigned_to: 'a@global66.com', status: 'closed' }),
      caso({ assigned_to: 'b@global66.com' }),
    ];
    const r = porAnalista(l);
    assert.deepEqual(r.map((x) => [x.nombre, x.n]), [['a', 1], ['b', 1]]);
  });
  it('los sin asignar tienen su propia fila y se nombran', () => {
    assert.equal(porAnalista([caso({ assigned_to: '' })])[0].nombre, 'sin asignar');
  });
  it('ordena de mayor carga a menor', () => {
    const l = [
      caso({ assigned_to: 'poco@global66.com' }),
      caso({ assigned_to: 'mucho@global66.com' }),
      caso({ assigned_to: 'mucho@global66.com' }),
    ];
    assert.deepEqual(porAnalista(l).map((x) => x.n), [2, 1]);
  });
});

describe('preparar para la tabla', () => {
  it('aplana lo que la tabla ordena', () => {
    const p = prepararCaso(caso({ note_count: 3, sla_contactos: 2 }));
    assert.equal(p._estado, 'Abierto');
    assert.equal(p._sla, 'Vencido');
    assert.equal(p._notas, 3);
    assert.equal(p._contactos, 2);
    assert.equal(p._analista, 'analista@global66.com');
  });
  it('conserva los campos originales', () => {
    assert.equal(prepararCaso(caso()).case_id, 'c-1');
  });
  it('el orden de urgencia es un número, no la etiqueta', () => {
    assert.equal(typeof prepararCaso(caso())._slaOrden, 'number');
  });
});

describe('sin contactar', () => {
  it('cero contactos es sin contactar', () => {
    assert.equal(sinContactar(caso({ sla_contactos: 0 })), true);
    assert.equal(sinContactar(caso({ sla_contactos: 1 })), false);
  });
  it('un campo ausente cuenta como sin contactar', () => {
    assert.equal(sinContactar({}), true);
  });
});
