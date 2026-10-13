/* ============================================================================
   El JSON del ROS, como formulario
   ----------------------------------------------------------------------------
   LO QUE MÁS IMPORTA ACÁ: que un número siga siendo un número.

   Un `<input>` devuelve texto SIEMPRE. Si se guardara tal cual, el monto 1000
   se volvería "1000", el backend rechazaría la edición entera por cambio de
   tipo — y si no la rechazara, GEREO recibiría un documento deforme y el
   reporte entraría mal al regulador.

   El segundo: no se agregan ni se quitan campos, ni elementos de una lista.
   ========================================================================= */

import assert from 'node:assert/strict';
import test, { describe, it } from 'node:test';

import {
  campos, coaccionar, cuerpoDeGuardado, escribir, esTextoLargo, etiqueta,
  leer, tipoDe,
} from '../src/comun/formulario_ros.js';

const DOC = {
  monto: 1000,
  nombre: 'Juan',
  pep: false,
  vacio: null,
  domicilio: { calle: 'Falsa', nro: 123 },
  personas: [{ nombre: 'A' }, { nombre: 'B' }],
};

describe('los tipos espejan el backend', () => {
  it('distingue bool de número', () => {
    // En Python `bool` ES `int`; acá no, pero el backend sí lo cuida y los dos
    // lados tienen que decir lo mismo.
    assert.equal(tipoDe(false), 'bool');
    assert.equal(tipoDe(0), 'numero');
  });

  it('nulo es su propio tipo, porque es comodín', () => {
    assert.equal(tipoDe(null), 'nulo');
    assert.equal(tipoDe(undefined), 'nulo');
  });

  it('reconoce lo anidado', () => {
    assert.equal(tipoDe({}), 'objeto');
    assert.equal(tipoDe([]), 'lista');
  });
});

describe('UN NÚMERO SIGUE SIENDO UN NÚMERO', () => {
  it('el texto de un input vuelve a número', () => {
    assert.strictEqual(coaccionar(1000, '2000'), 2000);
  });

  it('un decimal también', () => {
    assert.strictEqual(coaccionar(10.5, '20.25'), 20.25);
  });

  it('un número ilegible deja el anterior, no NaN ni texto', () => {
    assert.strictEqual(coaccionar(1000, 'mil'), 1000);
    assert.strictEqual(coaccionar(1000, ''), 1000);
  });

  it('un bool sigue siendo bool', () => {
    assert.strictEqual(coaccionar(false, true), true);
    assert.strictEqual(coaccionar(true, false), false);
  });

  it('un texto sigue siendo texto aunque parezca número', () => {
    // Un RUT o un número de repertorio son texto: convertirlos perdería los
    // ceros de adelante y cambiaría el tipo.
    assert.strictEqual(coaccionar('007', '008'), '008');
  });

  it('un campo vacío se puede llenar y volver a vaciar', () => {
    assert.strictEqual(coaccionar(null, 'algo'), 'algo');
    assert.strictEqual(coaccionar(null, ''), null);
  });
});

describe('escribir no muta y conserva el resto', () => {
  it('cambia sólo lo apuntado', () => {
    const nuevo = escribir(DOC, 'monto', 2000);
    assert.equal(nuevo.monto, 2000);
    assert.equal(DOC.monto, 1000, 'mutó el original');
    assert.equal(nuevo.nombre, 'Juan');
  });

  it('llega adentro de un objeto anidado', () => {
    const nuevo = escribir(DOC, 'domicilio.calle', 'Real');
    assert.equal(nuevo.domicilio.calle, 'Real');
    assert.equal(nuevo.domicilio.nro, 123);
    assert.equal(DOC.domicilio.calle, 'Falsa');
  });

  it('llega adentro de una lista sin cambiarle el largo', () => {
    const nuevo = escribir(DOC, 'personas[1].nombre', 'Z');
    assert.equal(nuevo.personas[1].nombre, 'Z');
    assert.equal(nuevo.personas.length, 2);
    assert.equal(nuevo.personas[0].nombre, 'A');
    assert.equal(DOC.personas[1].nombre, 'B');
  });

  it('leer y escribir hablan la misma ruta', () => {
    for (const ruta of ['monto', 'domicilio.nro', 'personas[0].nombre']) {
      const nuevo = escribir(DOC, ruta, 'marcado');
      assert.equal(leer(nuevo, ruta), 'marcado', ruta);
    }
  });

  it('leer una ruta que no existe no revienta', () => {
    assert.equal(leer(DOC, 'no.existe.nada'), undefined);
    assert.equal(leer(DOC, 'personas[9].nombre'), undefined);
  });
});

describe('los campos salen aplanados y en orden', () => {
  it('una hoja por campo, con su ruta', () => {
    const rutas = campos(DOC).map((c) => c.ruta);
    assert.deepEqual(rutas, [
      'monto', 'nombre', 'pep', 'vacio',
      'domicilio.calle', 'domicilio.nro',
      'personas[0].nombre', 'personas[1].nombre',
    ]);
  });

  it('la etiqueta saca el número de orden de la clave', () => {
    // El número es el orden del formulario del regulador, no parte del nombre.
    assert.equal(etiqueta('1_descripcion_hechos_orden_cronologico'),
                 'Descripcion hechos orden cronologico');
    assert.equal(etiqueta('nombre_o_razon_social'), 'Nombre o razon social');
  });

  it('un texto largo se marca para dibujarlo como área', () => {
    assert.equal(esTextoLargo('corto'), false);
    assert.equal(esTextoLargo('x'.repeat(200)), true);
    assert.equal(esTextoLargo('dos\nlíneas'), true);
    assert.equal(esTextoLargo(1000), false);
  });
});

describe('el cuerpo que se manda a guardar', () => {
  const SECCIONES = [
    { clave: 's1', contenido: { a: 1 } },
    { clave: 's2', contenido: { b: 2 } },
  ];

  it('VAN TODAS LAS SECCIONES, no sólo las tocadas', () => {
    // El backend compara la forma del documento completo: mandar media parte
    // haría que lo no enviado se lea como faltante y rechace la edición.
    const cuerpo = cuerpoDeGuardado(SECCIONES, { s1: { a: 99 } }, 3);
    assert.deepEqual(Object.keys(cuerpo.secciones), ['s1', 's2']);
    assert.deepEqual(cuerpo.secciones.s1, { a: 99 });
    assert.deepEqual(cuerpo.secciones.s2, { b: 2 });
  });

  it('dice sobre qué versión se editó', () => {
    // Para que el backend pueda frenar si otro guardó entremedio.
    assert.equal(cuerpoDeGuardado(SECCIONES, {}, 3).sobre_version, 3);
  });

  it('sin ediciones manda el contenido tal cual', () => {
    const cuerpo = cuerpoDeGuardado(SECCIONES, {}, 1);
    assert.deepEqual(cuerpo.secciones, { s1: { a: 1 }, s2: { b: 2 } });
  });
});
