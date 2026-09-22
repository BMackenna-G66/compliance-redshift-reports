/* El análisis individual.
 *
 * Lo que se prueba es lo que falla sin dar error: el parseo que descarta una
 * fila de más, el cruce que deja las columnas del motor vacías, el tope de
 * identificadores que el backend rechaza recién a los treinta segundos. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  ENVIO_INTERNACIONAL, ENVIO_NACIONAL, TOPE_IDS, avisoDeDescartes, cruzar,
  esNacional, filasDeSalesforce, idsDeCasos, partirIds, problemaConLosIds,
  remesasDeCasos, resumenDelCruce,
} from '../src/comun/individual.js';

/* Un `Document` de mentira: sólo lo que el parser usa. Evita depender de un
   DOM entero para probar la interpretación, que es lo que importa. */
function documentoCon(filas) {
  const celda = (t) => ({ textContent: t });
  const tr = (cs) => ({ querySelectorAll: () => cs.map(celda) });
  return { querySelectorAll: () => filas.map(tr) };
}

const CABECERA = ['h', 'h', 'h', 'h', 'h', 'h', 'h', 'h'];

describe('el reporte de Salesforce', () => {
  it('saca las columnas por posición', () => {
    const doc = documentoCon([
      CABECERA,
      ['ana', 'Cuenta SA', 'TX  9988776  POR revisión', '2026-09-01 10:00',
       '3', 'no', '00012345', '778899'],
    ]);
    assert.deepEqual(filasDeSalesforce(doc), [{
      nombre_cuenta: 'Cuenta SA',
      asunto: 'TX  9988776  POR revisión',
      fecha_hora: '2026-09-01 10:00',
      numero_caso: '00012345',
      id_interno: '778899',
      remesa: '9988776',
    }]);
  });

  it('saca el número de remesa con espacios variables', () => {
    const con = (asunto) => filasDeSalesforce(documentoCon([
      CABECERA, ['a', 'b', asunto, 'd', 'e', 'f', 'g', '999'],
    ]))[0].remesa;
    assert.equal(con('TX 123 POR algo'), '123');
    assert.equal(con('TX    456    POR algo'), '456');
    assert.equal(con('tx  789  por algo'), '789');
  });

  it('un asunto sin remesa deja el campo vacío y no rompe', () => {
    const f = filasDeSalesforce(documentoCon([
      CABECERA, ['a', 'b', 'Revisión manual', 'd', 'e', 'f', 'g', '999'],
    ]));
    assert.equal(f[0].remesa, '');
    assert.equal(f[0].id_interno, '999');
  });

  it('descarta la fila sin ID interno', () => {
    // Aguas abajo no se puede ni buscar ni cruzar: arrastrarla llenaría la
    // planilla final de filas fantasma.
    const f = filasDeSalesforce(documentoCon([
      CABECERA, ['a', 'b', 'c', 'd', 'e', 'f', 'g', '   '],
    ]));
    assert.deepEqual(f, []);
  });

  it('descarta la fila con menos columnas de las esperadas', () => {
    const f = filasDeSalesforce(documentoCon([CABECERA, ['a', 'b', 'c']]));
    assert.deepEqual(f, []);
  });

  it('omite la cabecera', () => {
    const f = filasDeSalesforce(documentoCon([
      ['Propietario', 'Cuenta', 'Asunto', 'Fecha', 'Ant', 'Cerrado', 'Caso', 'ID'],
    ]));
    assert.deepEqual(f, []);
  });

  it('un documento vacío devuelve una lista vacía', () => {
    assert.deepEqual(filasDeSalesforce(documentoCon([])), []);
    assert.deepEqual(filasDeSalesforce(null), []);
  });

  it('los IDs y las remesas salen únicos', () => {
    const filas = [
      { id_interno: '1', remesa: 'a' }, { id_interno: '1', remesa: 'b' },
      { id_interno: '2', remesa: 'a' }, { id_interno: '3', remesa: '' },
    ];
    assert.deepEqual(idsDeCasos(filas), ['1', '2', '3']);
    assert.deepEqual(remesasDeCasos(filas), ['a', 'b']);
  });
});

describe('los identificadores pegados a mano', () => {
  it('acepta cualquier separador', () => {
    // Lo que se pega viene de un Excel, de un Slack o de un correo; obligar a
    // un formato hace que la gente lo arregle a mano y se equivoque.
    for (const t of ['1,2,3', '1 2 3', '1;2;3', '1\n2\n3', '1, 2;\n3']) {
      assert.deepEqual(partirIds(t).ids, ['1', '2', '3'], t);
    }
  });

  it('unifica repetidos', () => {
    assert.deepEqual(partirIds('7 7 7').ids, ['7']);
  });

  it('con `soloNumeros` descarta lo que no lo es, y lo cuenta', () => {
    const r = partirIds('1, dos, 3', { soloNumeros: true });
    assert.deepEqual(r.ids, ['1', '3']);
    assert.equal(r.descartados, 1);
    assert.equal(r.crudos, 3);
  });

  it('sin `soloNumeros` deja pasar los alfanuméricos de wallet', () => {
    assert.deepEqual(partirIds('ACC-1, ACC-2').ids, ['ACC-1', 'ACC-2']);
  });

  it('pide que se peguen los identificadores cuando no hay nada', () => {
    assert.match(problemaConLosIds(partirIds('')), /Pegá/);
  });

  it('avisa cuando ninguno sirve, con el número', () => {
    const p = problemaConLosIds(partirIds('a, b, c', { soloNumeros: true }));
    assert.match(p, /3/);
  });

  it('corta arriba del tope antes de mandar la consulta', () => {
    // El backend la rechaza, pero recién a los treinta segundos de espera.
    const muchos = Array.from({ length: TOPE_IDS + 1 }, (_, i) => i + 1).join(',');
    const p = problemaConLosIds(partirIds(muchos, { soloNumeros: true }));
    assert.match(p, /máximo/i);
    assert.match(p, /tandas/);
  });

  it('justo en el tope, deja pasar', () => {
    const justos = Array.from({ length: TOPE_IDS }, (_, i) => i + 1).join(',');
    assert.equal(problemaConLosIds(partirIds(justos, { soloNumeros: true })), '');
  });

  it('el descarte se avisa: buscar 280 creyendo que son 300 cambia la conclusión', () => {
    const a = avisoDeDescartes(partirIds('1, dos, 3', { soloNumeros: true }));
    assert.match(a, /1 de 3/);
  });

  it('los repetidos también se avisan', () => {
    assert.match(avisoDeDescartes(partirIds('7 7 8')), /repetido/);
  });

  it('sin descartes ni repetidos no hay aviso', () => {
    assert.equal(avisoDeDescartes(partirIds('1 2 3')), '');
  });
});

describe('nacional o internacional', () => {
  it('«Envío internacional» NO es nacional', () => {
    // El defecto que tiene v1 en producción: `.includes('nacional')` da
    // verdadero sobre «envío internacional», así que TODAS las
    // internacionales caían en la hoja de nacionales y la otra salía vacía.
    assert.equal(esNacional({ tipo_envio: ENVIO_INTERNACIONAL }), false);
    assert.equal(esNacional({ tipo_envio: 'Envío Internacional' }), false);
    assert.equal(esNacional({ tipo_envio: 'internacional' }), false);
  });

  it('«Envío nacional» sí lo es', () => {
    assert.equal(esNacional({ tipo_envio: ENVIO_NACIONAL }), true);
    assert.equal(esNacional({ tipo_envio: 'ENVÍO NACIONAL' }), true);
  });

  it('sin tipo de envío, no es nacional: no se le inventa un DNI para cruzar', () => {
    assert.equal(esNacional({}), false);
    assert.equal(esNacional(null), false);
    assert.equal(esNacional({ tipo_envio: '' }), false);
  });
});

describe('el cruce del paso 4', () => {
  const casos = [{ remesa: '100', numero_caso: 'C-1' }];
  const analisis = [{
    'IDENTIDAD (DNI/RUT)': '12345678',
    'Acción Manual': 'revisar',
    'Es PEP': 'Sí',
    'Score Acumulado': '42',
    'Nombre Completo': 'A. Pérez',
    'Gravedad Máx': 'alta',
    'Cant. Delitos': '2',
    'Sugerencia Motor': 'escalar',
  }];

  it('separa nacionales de internacionales', () => {
    // Sólo las nacionales tienen DNI de beneficiario, que es la única llave
    // contra el motor. Mezclarlas daría una planilla donde media tabla tiene
    // las columnas vacías sin que se sepa por qué.
    const r = cruzar({
      transacciones: [
        { tipo_envio: ENVIO_NACIONAL, beneficiary_dni: '12345678' },
        { tipo_envio: ENVIO_INTERNACIONAL, beneficiary_dni: '999' },
      ],
      analisis, casos,
    });
    assert.equal(r.nacionales.length, 1);
    assert.equal(r.internacionales.length, 1);
  });

  it('pega las columnas del motor por DNI', () => {
    const r = cruzar({
      transacciones: [{ tipo_envio: ENVIO_NACIONAL, beneficiary_dni: '12345678' }],
      analisis, casos,
    });
    assert.equal(r.nacionales[0]['Es PEP'], 'Sí');
    assert.equal(r.nacionales[0]['Score Acumulado'], '42');
    assert.equal(r.nacionales[0]['Nombre Completo Motor'], 'A. Pérez');
    assert.equal(r.cruzadas, 1);
  });

  it('un DNI que no está en el motor deja las columnas vacías y se cuenta', () => {
    const r = cruzar({
      transacciones: [{ tipo_envio: ENVIO_NACIONAL, beneficiary_dni: '000' }],
      analisis, casos,
    });
    assert.equal(r.nacionales[0]['Es PEP'], '');
    assert.equal(r.sinCruzar, 1);
    assert.equal(r.cruzadas, 0);
  });

  it('el DNI cruza aunque venga con espacios', () => {
    const r = cruzar({
      transacciones: [{ tipo_envio: ENVIO_NACIONAL, beneficiary_dni: '  12345678  ' }],
      analisis, casos,
    });
    assert.equal(r.cruzadas, 1);
  });

  it('pega el N° de caso por número de remesa', () => {
    const r = cruzar({
      transacciones: [{ tipo_envio: ENVIO_NACIONAL, transaction_id: '100', beneficiary_dni: '12345678' }],
      analisis, casos,
    });
    assert.equal(r.nacionales[0]['N° Caso'], 'C-1');
  });

  it('sin caso asociado el número queda vacío, no «undefined»', () => {
    const r = cruzar({
      transacciones: [{ tipo_envio: ENVIO_NACIONAL, transaction_id: '999', beneficiary_dni: '12345678' }],
      analisis, casos,
    });
    assert.strictEqual(r.nacionales[0]['N° Caso'], '');
  });

  it('sin transacciones no rompe', () => {
    const r = cruzar({ transacciones: null, analisis: null, casos: null });
    assert.deepEqual(r, { nacionales: [], internacionales: [], cruzadas: 0, sinCruzar: 0 });
  });

  it('una tasa de cruce baja se marca antes de descargar', () => {
    // Casi siempre significa que los dos archivos son de tandas distintas, y
    // sin el aviso eso se descubre leyendo la planilla fila por fila.
    const r = resumenDelCruce({
      nacionales: [1, 2, 3, 4], internacionales: [], cruzadas: 1, sinCruzar: 3,
    });
    assert.equal(r.tasa, 25);
    assert.equal(r.sospechoso, true);
  });

  it('una tasa alta no se marca', () => {
    const r = resumenDelCruce({
      nacionales: [1, 2, 3, 4], internacionales: [], cruzadas: 4, sinCruzar: 0,
    });
    assert.equal(r.tasa, 100);
    assert.equal(r.sospechoso, false);
  });

  it('sin nacionales no se marca nada: no hay nada que cruzar', () => {
    const r = resumenDelCruce({ nacionales: [], internacionales: [1], cruzadas: 0, sinCruzar: 0 });
    assert.equal(r.sospechoso, false);
  });
});
