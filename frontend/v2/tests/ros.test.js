/* ============================================================================
   El registro de ROS, del lado de la pantalla
   ----------------------------------------------------------------------------
   LO QUE MÁS IMPORTA ACÁ: que no se pueda marcar «enviado» un reporte cuyo
   texto escribió una IA sin que alguien diga que lo leyó.

   El único control que tenía «enviado» era que la narrativa no estuviera
   vacía, y el botón «Usar como base» de la pantalla de GEREO la llena de una
   sentada con el texto generado. El acuse es lo que cierra eso, y no hace
   desaparecer las advertencias —vienen en todas las corridas, porque el
   reporte sale incompleto a propósito—: hace que alguien se haga cargo.

   LA SEGUNDA COSTURA: la regla de qué queda pendiente vive en
   `ros_gereo.listo_para_enviar()` y NO se reimplementa acá. Viaja en la
   respuesta. Si alguien la copia a JS, las dos versiones se separan sin que
   nada falle: el botón habilitado de este lado y el 400 del otro.
   ========================================================================= */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

import {
  destinosDe, editable, faltaParaEnviar, pendientesGereo, puedeMover,
} from '../src/comun/ros.js';

const AQUI = dirname(fileURLToPath(import.meta.url));

const CON_GEREO = {
  estado: 'revision_legal',
  narrativa: 'La escribió la IA y nadie la tocó.',
  pendientes_gereo: ["La 'Temática' queda sin seleccionar.",
                     'Textos narrativos redactados con IA (borrador — validar).'],
};
const A_MANO = { estado: 'revision_legal', narrativa: 'Escrita a mano.' };

/* ── El acuse ───────────────────────────────────────────────────────────── */

test('un ROS de GEREO no se puede enviar sin acuse', () => {
  assert.equal(puedeMover(CON_GEREO, 'enviado', false), false);
});

test('con el acuse tildado, sí', () => {
  assert.equal(puedeMover(CON_GEREO, 'enviado', true), true);
});

test('un ROS escrito a mano no pide acuse', () => {
  assert.equal(puedeMover(A_MANO, 'enviado', false), true);
});

test('el acuse no reemplaza escribir la narrativa', () => {
  assert.equal(puedeMover({ ...CON_GEREO, narrativa: '' }, 'enviado', true), false);
});

test('el acuse no se pide para los estados que no reportan nada', () => {
  for (const destino of ['revision_legal', 'descartado', 'borrador']) {
    assert.equal(puedeMover(CON_GEREO, destino, false), true, destino);
  }
});

/* ── La costura con el backend ──────────────────────────────────────────── */

test('los pendientes se leen de la respuesta, no se recalculan', () => {
  assert.deepEqual(pendientesGereo(CON_GEREO), CON_GEREO.pendientes_gereo);
  assert.deepEqual(pendientesGereo(A_MANO), []);
  assert.deepEqual(pendientesGereo(null), []);
});

test('la pantalla NO reimplementa la regla de listo_para_enviar', () => {
  // Si alguien vuelve a escribir la regla en JS, las dos versiones se separan
  // sin que nada falle. El texto de las advertencias lo redacta el backend:
  // que aparezca acá es la señal de que se copió.
  const js = readFileSync(join(AQUI, '..', 'src', 'comun', 'ros.js'), 'utf8');
  for (const rastro of ['señal automática', 'advertencias', 'generado_con_ia']) {
    assert.equal(js.includes(rastro), false,
                 `«${rastro}» en ros.js: la regla se está recalculando en el front`);
  }
});

/* ── Lo que ya había, que el acuse no tenía que romper ──────────────────── */

test('sigue faltando la narrativa cuando está vacía', () => {
  assert.deepEqual(faltaParaEnviar({ narrativa: '   ' }),
                   ['la descripción de la sospecha']);
  assert.deepEqual(faltaParaEnviar({ narrativa: 'algo' }), []);
});

test('un enviado ya no se edita', () => {
  assert.equal(editable({ estado: 'enviado' }), false);
  assert.equal(editable({ estado: 'borrador' }), true);
});

test('los destinos salen del vocabulario del backend', () => {
  const transiciones = { borrador: ['revision_legal', 'descartado'], enviado: [] };
  assert.deepEqual(destinosDe({ estado: 'borrador' }, transiciones),
                   ['revision_legal', 'descartado']);
  assert.deepEqual(destinosDe({ estado: 'enviado' }, transiciones), []);
  assert.deepEqual(destinosDe({ estado: 'borrador' }, null), []);
});
