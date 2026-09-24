/* ============================================================================
   El mantenedor de cuentas internas
   ----------------------------------------------------------------------------
   Lo que vigila este archivo es la costura con el backend. Los campos
   editables están escritos en dos lados —`CAMPOS_CUENTA` acá y
   `CUENTAS_FILTROS` en la Lambda— y el modo en que eso se rompe es mudo: el
   front manda `iban=...`, el backend no conoce esa clave, la ignora, y la
   pantalla devuelve la tabla entera como si el filtro hubiera andado.

   Lo demás es lo de siempre: que un campo vacío no viaje, porque `moneda=`
   no significa «cualquiera» sino «sin filtro», y esa diferencia es una
   consulta puntual contra un recorrido de toda la tabla de cuentas.
   ========================================================================= */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

import {
  CAMPOS_CUENTA, COLUMNAS_CUENTA, FORMULARIO_VACIO,
  consulta, hayFiltro, momento, principal, resumenFiltros,
} from '../src/comun/cuentas.js';

const AQUI = dirname(fileURLToPath(import.meta.url));
const API = join(AQUI, '..', '..', '..', 'lambda', 'api_handler.py');

test('los campos editables son los que el backend acepta', () => {
  const py = readFileSync(API, 'utf8');
  const bloque = py.match(/CUENTAS_FILTROS = \{([\s\S]*?)\}/);
  assert.ok(bloque, 'no encontré CUENTAS_FILTROS en la Lambda');
  const delBackend = [...bloque[1].matchAll(/"([a-z_]+)":/g)].map((m) => m[1]);
  const delFront = CAMPOS_CUENTA.map((c) => c.clave);
  assert.deepEqual(delFront.slice().sort(), delBackend.slice().sort(),
    'un campo que el backend no conoce se ignora en silencio');
});

test('las columnas de la tabla son las que devuelve la consulta', () => {
  const py = readFileSync(API, 'utf8');
  const sql = py.match(/CUENTAS_SQL = """([\s\S]*?)"""/)[1];
  const alias = [...sql.matchAll(/\bAS\s+([a-z_]+)\s*,?\s*$/gm)].map((m) => m[1]);
  for (const col of COLUMNAS_CUENTA) {
    assert.ok(alias.includes(col.clave),
      `la columna «${col.clave}» no existe en el SELECT; quedaría vacía`);
  }
});

test('un campo vacío no viaja', () => {
  const url = consulta({ ...FORMULARIO_VACIO, cuenta: 'GB42' });
  assert.ok(url.includes('cuenta=GB42'));
  assert.ok(!url.includes('moneda='), 'mandar moneda= vacía no es «cualquiera»');
});

test('los espacios de más no cuentan como filtro', () => {
  assert.equal(hayFiltro({ ...FORMULARIO_VACIO, moneda: '   ' }), false);
  assert.equal(hayFiltro({ ...FORMULARIO_VACIO, moneda: 'EUR' }), true);
  assert.equal(hayFiltro(FORMULARIO_VACIO), false);
  assert.equal(hayFiltro(null), false);
});

test('el valor se codifica: un & en el campo no parte la consulta', () => {
  const url = consulta({ ...FORMULARIO_VACIO, cuenta: 'a&limit=9999' });
  assert.ok(url.includes('cuenta=a%26limit%3D9999'));
  assert.equal(url.match(/limit=/g).length, 1, 'no se pudo colar un segundo limit');
});

test('los dos filtros de la consulta original viajan juntos', () => {
  const url = consulta({ ...FORMULARIO_VACIO, moneda: 'EUR',
                         cuenta: 'GB00TCCL00000000000000' });
  assert.ok(url.includes('cuenta=GB00TCCL00000000000000'));
  assert.ok(url.includes('moneda=EUR'));
});

test('principal se lee como Sí/No y no como 0/1', () => {
  assert.equal(principal('1'), 'Sí');
  assert.equal(principal('0'), 'No');
  assert.equal(principal('true'), 'Sí');
  assert.equal(principal(''), '—');
});

test('una fecha que no se entiende se muestra tal cual, no como fecha inválida', () => {
  assert.equal(momento(''), '—');
  assert.equal(momento('mañana'), 'mañana');
  assert.ok(momento('2026-05-03 15:25:11').includes('2026'));
});

test('el resumen dice sobre qué se buscó, con las etiquetas de la pantalla', () => {
  const t = resumenFiltros({ cuenta: 'GB42', moneda: 'EUR' });
  assert.ok(t.includes('Número de cuenta: GB42'));
  assert.ok(t.includes('Moneda: EUR'));
});
