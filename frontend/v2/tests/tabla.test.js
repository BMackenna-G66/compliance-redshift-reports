/* La lógica de la tabla.
 *
 * Catorce pantallas van a usar esto, así que un error acá se multiplica por
 * catorce. El invariante que más importa es el de los valores ausentes: en
 * una herramienta de compliance, un cliente sin score ordenado junto a los de
 * riesgo cero parece revisado y limpio cuando en realidad no se lo midió. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  aCSV, comoNumero, comparar, filtrar, normalizar, ordenar, paginar,
  totalPaginas, vacio,
} from '../src/comun/tabla.js';

describe('vacío', () => {
  it('el cero y el false NO están vacíos', () => {
    assert.equal(vacio(0), false);
    assert.equal(vacio(false), false);
  });
  it('null, undefined, "" y NaN sí', () => {
    for (const v of [null, undefined, '', NaN]) assert.equal(vacio(v), true);
  });
});

describe('comoNumero', () => {
  it('lee números de verdad', () => {
    assert.equal(comoNumero(42), 42);
    assert.equal(comoNumero('42'), 42);
    assert.equal(comoNumero('-7.5'), -7.5);
  });
  it('lee el formato de acá: 1.234,56', () => {
    assert.equal(comoNumero('1.234,56'), 1234.56);
    assert.equal(comoNumero('$ 1.234.567'), 1234567);
  });
  it('y el otro: 1,234.56', () => {
    assert.equal(comoNumero('1,234.56'), 1234.56);
  });
  it('los miles repetidos son miles, con cualquiera de los dos separadores', () => {
    assert.equal(comoNumero('1.234.567'), 1234567);
    assert.equal(comoNumero('1,234,567'), 1234567);
  });
  it('un separador solo con menos de tres dígitos detrás es decimal', () => {
    assert.equal(comoNumero('7.5'), 7.5);
    assert.equal(comoNumero('7,5'), 7.5);
    assert.equal(comoNumero('12.25'), 12.25);
  });
  it('AMBIGUO Y DOCUMENTADO: "1.234" se lee como mil doscientos treinta y cuatro', () => {
    // No se puede resolver mirando el texto. Se elige la lectura correcta
    // para los montos, que es lo que esta aplicación muestra. Sólo afecta al
    // orden, nunca a lo que se ve en pantalla.
    assert.equal(comoNumero('1.234'), 1234);
    assert.equal(comoNumero('0.500'), 500);
  });
  it('lo que no es número, no lo es', () => {
    for (const v of ['abierto', '', null, undefined, {}, 'c-2026-01']) {
      assert.equal(comoNumero(v), null, String(v));
    }
  });
});

describe('ordenar', () => {
  const filas = [
    { id: 'a', score: 9 }, { id: 'b', score: 10 },
    { id: 'c', score: null }, { id: 'd', score: 2 },
  ];

  it('los números van como números, no como texto', () => {
    // El bug clásico: ordenados como texto, "10" viene antes que "9".
    const r = ordenar(filas, 'score', 'asc').map((f) => f.id);
    assert.deepEqual(r.slice(0, 3), ['d', 'a', 'b']);
  });

  it('un valor ausente va al final, ordene como ordene', () => {
    // El invariante que importa: un score que no se calculó no es un cero.
    assert.equal(ordenar(filas, 'score', 'asc').at(-1).id, 'c');
    assert.equal(ordenar(filas, 'score', 'desc').at(-1).id, 'c');
  });

  it('no toca el arreglo original', () => {
    const copia = [...filas];
    ordenar(filas, 'score', 'desc');
    assert.deepEqual(filas, copia);
  });

  it('sin clave no hace nada', () => {
    assert.equal(ordenar(filas, ''), filas);
  });

  it('el texto se ordena como en castellano', () => {
    const f = [{ n: 'Zúñiga' }, { n: 'Álvarez' }, { n: 'Núñez' }];
    assert.deepEqual(ordenar(f, 'n', 'asc').map((x) => x.n),
      ['Álvarez', 'Núñez', 'Zúñiga']);
  });

  it('el cero ordena como cero y no como vacío', () => {
    const f = [{ s: null }, { s: 0 }, { s: 5 }];
    assert.deepEqual(ordenar(f, 's', 'asc').map((x) => x.s), [0, 5, null]);
  });
});

describe('comparar', () => {
  it('mezcla texto y número sin romperse', () => {
    assert.doesNotThrow(() => comparar('abierto', 5));
  });
});

describe('filtrar', () => {
  const filas = [
    { analista: 'Diego Armesto', estado: 'Abierto' },
    { analista: 'Diego Armesto', estado: 'Cerrado' },
    { analista: 'Ana Pérez', estado: 'Abierto' },
  ];
  const claves = ['analista', 'estado'];

  it('busca todas las palabras, en cualquier campo y en cualquier orden', () => {
    assert.equal(filtrar(filas, 'diego abierto', claves).length, 1);
    assert.equal(filtrar(filas, 'abierto diego', claves).length, 1);
  });

  it('ignora acentos y mayúsculas', () => {
    assert.equal(filtrar(filas, 'perez', claves).length, 1);
    assert.equal(filtrar(filas, 'PÉREZ', claves).length, 1);
  });

  it('sin texto devuelve todo', () => {
    assert.equal(filtrar(filas, '', claves).length, 3);
    assert.equal(filtrar(filas, '   ', claves).length, 3);
  });

  it('no cruza el límite entre columnas', () => {
    // "Armesto Abierto" son dos columnas distintas, pero pegadas formarían
    // texto que no existe en ninguna. El separador evita falsos positivos.
    assert.equal(filtrar(filas, 'armestoabierto', claves).length, 0);
  });

  it('sólo mira las columnas indicadas', () => {
    assert.equal(filtrar(filas, 'diego', ['estado']).length, 0);
  });
});

describe('paginar', () => {
  const filas = Array.from({ length: 25 }, (_, i) => ({ i }));

  it('corta la página pedida', () => {
    assert.deepEqual(paginar(filas, 2, 10).map((f) => f.i)[0], 10);
    assert.equal(paginar(filas, 3, 10).length, 5);
  });

  it('porPagina 0 significa todas', () => {
    assert.equal(paginar(filas, 1, 0).length, 25);
    assert.equal(totalPaginas(25, 0), 1);
  });

  it('cuenta bien las páginas', () => {
    assert.equal(totalPaginas(25, 10), 3);
    assert.equal(totalPaginas(20, 10), 2);
    assert.equal(totalPaginas(0, 10), 1);   // nunca "página 1 de 0"
  });
});

describe('exportar a CSV', () => {
  const columnas = [
    { clave: 'nombre', titulo: 'Nombre' },
    { clave: 'estado', titulo: 'Estado', exportar: (f) => f.estado.toUpperCase() },
  ];

  it('pone la cabecera y las filas', () => {
    const csv = aCSV([{ nombre: 'Ana', estado: 'abierto' }], columnas);
    const lineas = csv.split('\r\n');
    assert.equal(lineas[0], '\uFEFFNombre;Estado');
    assert.equal(lineas[1], 'Ana;ABIERTO');
  });

  it('arranca con BOM para que Excel no rompa los acentos', () => {
    assert.ok(aCSV([], columnas).startsWith('\uFEFF'));
  });

  it('escapa el separador, las comillas y los saltos de línea', () => {
    const csv = aCSV([{ nombre: 'Pérez; Ana "la jefa"\nsegunda', estado: 'x' }], columnas);
    assert.ok(csv.includes('"Pérez; Ana ""la jefa""\nsegunda"'));
  });

  it('un valor ausente sale vacío y no como "undefined"', () => {
    const csv = aCSV([{ estado: 'x' }], columnas);
    assert.ok(csv.includes('\r\n;X'));
    assert.ok(!csv.includes('undefined'));
  });
});

describe('normalizar', () => {
  it('saca acentos y baja a minúsculas', () => {
    assert.equal(normalizar('ÁÉÍÓÚñÑ'), 'aeiounn');
  });
  it('un valor ausente es texto vacío', () => {
    assert.equal(normalizar(null), '');
    assert.equal(normalizar(undefined), '');
  });
});
