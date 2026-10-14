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
import test, { describe, it } from 'node:test';

import {
  ETAPAS_ROS, PLAZO_LEGAL_DIAS, destinosDe, diasDesde, editable, etapaDeRos,
  etiquetaEtapa, faltaParaEnviar, filtrarPorRos, pendientesGereo, plazoDe,
  puedeMover, rosPorCaso,
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

/* ── La etapa del ROS en la lista de casos ──────────────────────────────── */

const hace = (dias) => new Date(Date.now() - dias * 86400000).toISOString();

test('UN ROS QUE NO SE PUDO GUARDAR NO ES «SIN ROS»', () => {
  // El reporte existe: lo que falló fue guardar su versión. Mostrarlo como si
  // no existiera esconde la falla detrás de un estado normal, que es lo que
  // no puede pasar con un registro regulatorio.
  assert.equal(etapaDeRos({ version_error: { motivo: 'ClientError' } }),
               'sin_version');
  assert.equal(ETAPAS_ROS.sin_version.color, 'alto');
  assert.notEqual(ETAPAS_ROS.sin_version.texto, ETAPAS_ROS.sin_ros.texto);
});

test('con versión guardada, un error viejo no tapa la etapa real', () => {
  // Falló una vez, se reintentó y salió: la etapa es la de verdad.
  assert.equal(etapaDeRos({ version_error: { motivo: 'x' }, version_actual: 1,
                            etapa_gereo: 'revisado' }), 'revisado');
});

test('una etapa que el front no conoce no deja la celda rota', () => {
  for (const raro of [undefined, '', 'magia', null, 7]) {
    assert.equal(etapaDeRos({ etapa_gereo: raro }), 'sin_ros', String(raro));
  }
  assert.equal(etiquetaEtapa(undefined).texto, 'Sin ROS');
});

test('si un caso tiene dos ROS, gana el más avanzado', () => {
  // Un caso se puede reportar dos veces; lo que importa mostrar es dónde está
  // el trabajo.
  const m = rosPorCaso([
    { case_id: 'c1', folio: 'A', etapa_gereo: 'recibido' },
    { case_id: 'c1', folio: 'B', etapa_gereo: 'enviado' },
  ]);
  assert.equal(m.c1.etapa, 'enviado');
  assert.equal(m.c1.folio, 'B');
});

test('un ROS sin caso no entra al cruce', () => {
  assert.deepEqual(rosPorCaso([{ folio: 'A', etapa_gereo: 'recibido' }]), {});
  assert.deepEqual(rosPorCaso(null), {});
});

describe('los filtros de etapa y de país', () => {
  const MAPA = rosPorCaso([
    { case_id: 'c1', etapa_gereo: 'enviado', regulador: 'UAF-CL' },
    { case_id: 'c2', etapa_gereo: 'recibido', regulador: 'UIF-AR' },
  ]);
  const CASOS = [{ case_id: 'c1' }, { case_id: 'c2' }, { case_id: 'c3' }];

  it('sin filtro devuelve todo, incluidos los casos sin ROS', () => {
    assert.equal(filtrarPorRos(CASOS, MAPA, {}).length, 3);
  });

  it('filtra por etapa', () => {
    assert.deepEqual(filtrarPorRos(CASOS, MAPA, { etapa: 'enviado' })
      .map((c) => c.case_id), ['c1']);
  });

  it('«Sin ROS» es una etapa como cualquier otra', () => {
    assert.deepEqual(filtrarPorRos(CASOS, MAPA, { etapa: 'sin_ros' })
      .map((c) => c.case_id), ['c3']);
  });

  it('filtrar por regulador saca a los que no tienen ROS', () => {
    // Un caso sin ROS no tiene país de reporte: es lo que espera quien
    // filtró «Chile».
    assert.deepEqual(filtrarPorRos(CASOS, MAPA, { regulador: 'UAF-CL' })
      .map((c) => c.case_id), ['c1']);
  });

  it('los dos filtros se combinan', () => {
    assert.equal(filtrarPorRos(CASOS, MAPA,
      { etapa: 'enviado', regulador: 'UIF-AR' }).length, 0);
  });
});

describe('el plazo legal', () => {
  it('NO SE INVENTAN LOS DÍAS: ninguno está definido todavía', () => {
    // Poner un número supuesto sería peor que no mostrar nada: alguien lo
    // tomaría por bueno y podría dejar pasar un plazo real.
    for (const v of Object.values(PLAZO_LEGAL_DIAS)) assert.equal(v, null);
  });

  it('mientras tanto muestra los días, sin semáforo', () => {
    const p = plazoDe({ creado_at: hace(10), regulador: 'UAF-CL' });
    assert.equal(p.dias, 10);
    assert.equal(p.limite, null);
    assert.equal(p.semaforo, '', 'pintó un semáforo sin saber el plazo');
    assert.equal(p.texto, '10 días');
  });

  it('EL SEMÁFORO APARECE SOLO cuando se defina el plazo', () => {
    // El día que Compliance los defina, se llenan y esto funciona sin tocar
    // una línea más.
    const original = PLAZO_LEGAL_DIAS['UAF-CL'];
    try {
      PLAZO_LEGAL_DIAS['UAF-CL'] = 15;
      assert.equal(plazoDe({ creado_at: hace(10), regulador: 'UAF-CL' }).semaforo, 'ok');
      assert.equal(plazoDe({ creado_at: hace(14), regulador: 'UAF-CL' }).semaforo, 'medio');
      const vencido = plazoDe({ creado_at: hace(20), regulador: 'UAF-CL' });
      assert.equal(vencido.semaforo, 'alto');
      assert.equal(vencido.texto, 'vencido hace 5 días');
    } finally {
      PLAZO_LEGAL_DIAS['UAF-CL'] = original;
    }
  });

  it('una fecha ilegible no inventa días', () => {
    for (const mala of [undefined, '', 'ayer', null]) {
      assert.equal(diasDesde(mala), null, String(mala));
      assert.equal(plazoDe({ creado_at: mala, regulador: 'UAF-CL' }), null);
    }
  });

  it('una fecha futura no da días negativos', () => {
    assert.equal(diasDesde(hace(-5)), 0);
  });
});
