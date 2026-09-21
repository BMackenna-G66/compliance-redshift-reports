/* El dominio: que los colores digan la verdad y las escalas no se crucen.
 *
 * El test de abajo sobre ESTADOS_CASO existe porque esto ya falló: los
 * estados se pintaron con `--nivel-alto`, que es el naranja de SUPERFICIE, y
 * "En investigación" quedó en 3,0:1 de contraste. No se vio en el diseño
 * —ese estado no aparecía en el prototipo— sino al abrir la bandeja con
 * datos de verdad. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  COLOR_CATEGORIA, ESCALA_ALERTA, ESTADOS_CASO, MONTO_POR_REPORTE, NIVELES,
  NIVELES_MAXIMO, PANTALLAS, GRUPOS, nivelDe, prioridadDeAlerta,
} from '../src/dominio.js';

/** Los tokens que se pueden usar como LETRA: las variantes `-texto`, los
 *  neutros de texto, y el blanco sobre oscuro. */
function sirveComoTexto(valor) {
  const m = /^var\((--[\w-]+)\)$/.exec(String(valor).trim());
  if (!m) return false;
  const t = m[1];
  return t.endsWith('-texto') || ['--texto', '--texto-2', '--texto-mute',
    '--texto-sobre-oscuro'].includes(t);
}

describe('los colores que se dibujan como letra', () => {
  it('los estados del caso usan variantes de texto', () => {
    for (const [clave, d] of Object.entries(ESTADOS_CASO)) {
      assert.ok(sirveComoTexto(d.color),
        `ESTADOS_CASO.${clave} usa ${d.color}, que es un color de superficie`);
    }
  });

  it('la prioridad de alerta separa el color de letra del de fondo', () => {
    for (const [clave, d] of Object.entries(ESCALA_ALERTA)) {
      assert.ok(sirveComoTexto(d.texto), `ESCALA_ALERTA.${clave}.texto = ${d.texto}`);
      assert.ok(d.fondo && d.color, `ESCALA_ALERTA.${clave} sin fondo o color`);
    }
  });

  it('todo color del dominio es un token, nunca un hex suelto', () => {
    const valores = [
      ...Object.values(NIVELES).flatMap((n) => [n.color, n.fondo, n.claro]),
      ...Object.values(COLOR_CATEGORIA),
      ...Object.values(ESTADOS_CASO).map((e) => e.color),
      ...Object.values(ESCALA_ALERTA).flatMap((e) => [e.color, e.texto, e.fondo]),
    ];
    for (const v of valores) {
      assert.match(String(v), /^var\(--[\w-]+\)$/, `"${v}" no es un token`);
    }
  });
});

describe('las dos escalas', () => {
  it('el máximo del análisis individual es la suma de los diez pesos', () => {
    assert.equal(NIVELES_MAXIMO, 19);
  });

  it('los cortes del individual son los de aml_individual.py', () => {
    assert.equal(NIVELES.CRITICO.desde, 10);
    assert.equal(NIVELES.ALTO.desde, 6);
    assert.equal(NIVELES.MEDIO.desde, 3);
    assert.equal(nivelDe(19), 'CRITICO');
    assert.equal(nivelDe(2), 'BAJO');
  });

  it('un puntaje mayor a 19 en el individual es imposible pero no rompe', () => {
    assert.equal(nivelDe(100), 'CRITICO');
  });

  it('las dos escalas dan cosas distintas para el mismo número, a propósito', () => {
    assert.notEqual(String(nivelDe(59)), String(prioridadDeAlerta(59)));
  });
});

describe('el mapa de montos', () => {
  it('cada entrada dice el campo y qué mide', () => {
    for (const [rep, d] of Object.entries(MONTO_POR_REPORTE)) {
      assert.ok(d.campo, `${rep} sin campo`);
      assert.ok(d.etiqueta, `${rep} sin etiqueta`);
    }
  });
  it('cubre los reportes que hoy generan alertas con monto', () => {
    // Medido sobre las 122 activas: seis reportes, cinco con monto.
    for (const r of ['payin_payout_accumulation', 'small_payin_structuring',
                     'structuring_detection', 'beneficiary_dispersion',
                     'top_customers_by_range_country']) {
      assert.ok(MONTO_POR_REPORTE[r], `falta ${r}`);
    }
  });
});

describe('las pantallas', () => {
  it('cada una tiene un grupo conocido y una llave de permiso', () => {
    for (const p of PANTALLAS) {
      assert.ok(GRUPOS.includes(p.grupo), `${p.id} en el grupo "${p.grupo}"`);
      assert.ok(p.modulo, `${p.id} sin módulo`);
      assert.ok(p.titulo, `${p.id} sin título`);
    }
  });
  it('no hay ids repetidos', () => {
    const ids = PANTALLAS.map((p) => p.id);
    assert.equal(new Set(ids).size, ids.length);
  });
});
