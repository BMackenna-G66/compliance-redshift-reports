/* ============================================================================
   El borrador del ROS que trae GEREO
   ----------------------------------------------------------------------------
   Lo que más importa acá es la costura: la matriz de qué admite cada país
   está escrita en dos lados —este archivo y `gereo.py`— y se puede separar
   sin que nada falle. El formulario dejaría elegir algo que el backend
   rechaza, o al revés, bloquearía algo permitido y nadie sabría por qué.
   El primer test compara las dos listas.

   Lo demás es que la pantalla no gaste una corrida —ni un viaje a la base de
   GEREO, la misma que atiende a sus analistas— en un pedido que ya se sabe
   que va a rebotar.
   ========================================================================= */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

import {
  PAISES, asociadosDe, cuerpoDeGeneracion, faltaParaGenerar, mesValido,
  narrativaComoTexto, paisDe, resumenDelBorrador,
} from '../src/comun/gereo.js';

const AQUI = dirname(fileURLToPath(import.meta.url));
const PY = join(AQUI, '..', '..', '..', 'lambda', 'gereo.py');

test('la matriz por país es la misma que la del backend', () => {
  const py = readFileSync(PY, 'utf8');
  const bloque = py.slice(py.indexOf('PAISES = {'), py.indexOf('PAIS_POR_REGULADOR'));
  for (const [pais, reglas] of Object.entries(PAISES)) {
    const fila = new RegExp(`"${pais}":\\s*{([^}]*)}`, 's').exec(bloque);
    assert.ok(fila, `${pais} no está en gereo.py`);
    for (const t of reglas.tipos) {
      assert.match(fila[1], new RegExp(`"${t}"`),
        `el backend no admite ${t} para ${pais}`);
    }
    assert.match(fila[1], new RegExp(`"asociados":\\s*${reglas.asociados}\\b`),
      `el tope de asociados de ${pais} no coincide con el backend`);
  }
});

test('el regulador lleva a su país', () => {
  assert.equal(paisDe('UAF-CL'), 'Chile');
  assert.equal(paisDe('UIF-AR'), 'Argentina');
  assert.equal(paisDe('UIAF-CO'), 'Colombia');
  assert.equal(paisDe('inventado'), '');
});

const base = (extra = {}) => ({
  pais: 'Chile', customer_id: '2402916', tipo_cliente: 'B2C',
  fecha_inicio: '01/2025', ...extra,
});

test('Argentina no admite B2B', () => {
  const faltan = faltaParaGenerar(base({ pais: 'Argentina', tipo_cliente: 'B2B' }));
  assert.ok(faltan.some((f) => f.includes('sólo cubre B2C')));
});

test('Argentina y Colombia no admiten clientes asociados', () => {
  for (const pais of ['Argentina', 'Colombia']) {
    const faltan = faltaParaGenerar(base({ pais, clientes_asociados: '3105060' }));
    assert.ok(faltan.some((f) => f.includes('único cliente')), pais);
  }
});

test('Chile admite hasta quince', () => {
  const quince = Array.from({ length: 15 }, (_, i) => `${i}`).join(',');
  assert.deepEqual(faltaParaGenerar(base({ clientes_asociados: quince })), []);
  const dieciseis = Array.from({ length: 16 }, (_, i) => `${i}`).join(',');
  assert.ok(faltaParaGenerar(base({ clientes_asociados: dieciseis })).length);
});

test('los asociados se limpian: sin vacíos ni repetidos', () => {
  assert.deepEqual(asociadosDe('3105060, 3105060 , ,  4200'), ['3105060', '4200']);
  assert.deepEqual(asociadosDe(['1', '1', '2']), ['1', '2']);
  assert.deepEqual(asociadosDe(''), []);
});

test('la fecha va como mm/aaaa', () => {
  assert.ok(mesValido('01/2025'));
  assert.ok(mesValido('1/2025'));
  assert.ok(!mesValido('2025-01'));
  assert.ok(!mesValido('13/2025'));
  assert.ok(!mesValido(''));
});

test('la fecha de fin puede ir vacía: llega hasta hoy', () => {
  assert.deepEqual(faltaParaGenerar(base({ fecha_fin: '' })), []);
  assert.ok(faltaParaGenerar(base({ fecha_fin: 'marzo' })).length);
});

test('los opcionales vacíos no viajan', () => {
  const c = cuerpoDeGeneracion(base(), 'ana@global66.com');
  assert.ok(!('fecha_fin' in c));
  assert.ok(!('clientes_asociados' in c));
  assert.ok(!('incluir_pdf' in c));
  assert.equal(c.actor_email, 'ana@global66.com');
});

test('el PDF sólo si se pide: armarlo suma segundos a cada llamada', () => {
  assert.ok(!('incluir_pdf' in cuerpoDeGeneracion(base())));
  assert.equal(cuerpoDeGeneracion(base({ incluir_pdf: true })).incluir_pdf, true);
});

test('una detención se lee distinto de una falla', () => {
  // Reintentar da exactamente lo mismo: es la regla de negocio funcionando.
  const r = resumenDelBorrador({ detenido: true, mensaje: "El país de origen es 'PE'." });
  assert.equal(r.detenido, true);
  assert.ok(r.mensaje.includes('PE'));
});

test('el resumen separa lo que disparó de lo que se miró y no disparó', () => {
  const r = resumenDelBorrador({
    detenido: false,
    senales: [{ id: 'R02' }],
    reglas: { gatilladas: [{ id: 'R02' }], descartadas: [{ id: 'R01' }], total_evaluadas: 2 },
  });
  assert.equal(r.gatilladas, 1);
  assert.equal(r.descartadas, 1);
  assert.equal(r.evaluadas, 2);
});

test('la narrativa se copia con el título de cada parte', () => {
  // Son respuestas a dos preguntas distintas del formulario: quien las pega
  // en el texto que va a firmar tiene que ver cuál es cuál.
  const t = narrativaComoTexto({
    narrativa_borrador: [
      { titulo: 'Descripción de los hechos', texto: 'Durante el período…' },
      { titulo: 'Qué se consideró sospechoso', texto: 'Del análisis…' },
    ],
  });
  assert.ok(t.includes('Descripción de los hechos\nDurante el período…'));
  assert.ok(t.includes('Qué se consideró sospechoso\nDel análisis…'));
});

test('sin borrador no hay resumen', () => {
  assert.equal(resumenDelBorrador(null), null);
});
