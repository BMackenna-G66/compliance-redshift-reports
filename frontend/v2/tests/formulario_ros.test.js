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
  campos, coaccionar, conUnoMas, cuerpoDeGuardado, escribir, esTextoLargo,
  agregadosVacios, etiqueta, formatearNumero, leer, listasDe, paraMostrar,
  parsearNumero, plantillaDe, plantillaDeLista, sePuedeAgregar, tipoDe,
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

describe('LOS MONTOS SE LEEN EN CASTELLANO', () => {
  /* El bug que esto cierra: `Number('12.500')` da 12.5 — un monto dividido
     por mil entrando a un reporte al regulador—, y `Number('1.234.567')` da
     NaN, que se descartaba sin aviso. Tipeando tecla por tecla el punto se
     come solo y por casualidad daba bien; pegando, no. Y los montos se pegan. */

  it('el punto es de miles, no decimal', () => {
    assert.strictEqual(parsearNumero('12.500'), 12500);
    assert.strictEqual(parsearNumero('1.234.567'), 1234567);
  });

  it('la coma es la decimal', () => {
    assert.strictEqual(parsearNumero('1.234,5'), 1234.5);
    assert.strictEqual(parsearNumero('0,75'), 0.75);
  });

  it('aguanta el símbolo de moneda y los espacios', () => {
    assert.strictEqual(parsearNumero('$ 1.234.567'), 1234567);
    assert.strictEqual(parsearNumero('1 234 567'), 1234567);
    // El espacio duro entra pegando desde Excel o desde un PDF.
    assert.strictEqual(parsearNumero('1\u00a0234'), 1234);
  });

  it('IDA Y VUELTA: lo que se muestra se vuelve a leer igual', () => {
    // Si no, un 1000.5 de GEREO se vería «1000.5» y al tocarlo sería 10005.
    for (const n of [1000.5, 12500, 1234567, 0.75, -42, 1000000.25]) {
      assert.strictEqual(parsearNumero(formatearNumero(n)), n, String(n));
    }
    assert.strictEqual(formatearNumero(1000.5), '1.000,5');
    assert.strictEqual(formatearNumero(1234567), '1.234.567');
  });

  it('UN PUNTO QUE NO AGRUPA MILES ES AMBIGUO Y SE MARCA', () => {
    // «1.23» puede ser un decimal mal escrito o un miles mal escrito. Lo
    // resuelve una persona, no el sistema eligiendo por ella.
    for (const malo of ['1.23', '1000.5', '12.3456']) {
      assert.equal(Number.isNaN(parsearNumero(malo)), true, malo);
    }
  });

  it('lo ilegible se marca, NO vuelve al valor anterior', () => {
    // Volver en silencio le haría creer a alguien que guardó una corrección
    // que no se guardó — y lo que no se guardó es un monto de un reporte.
    for (const malo of ['abc', '', '  ', '--5', '1,2,3']) {
      assert.equal(Number.isNaN(coaccionar(1000, malo)), true, JSON.stringify(malo));
    }
  });

  it('un bool sigue siendo bool', () => {
    assert.strictEqual(coaccionar(false, true), true);
  });

  it('un texto sigue siendo texto aunque parezca número', () => {
    // Un RUT o un número de repertorio son texto: convertirlos perdería los
    // ceros de adelante.
    assert.strictEqual(coaccionar('007', '008'), '008');
    assert.strictEqual(coaccionar('11.111.111-1', '22.222.222-2'), '22.222.222-2');
  });

  it('un campo vacío se puede llenar y volver a vaciar', () => {
    assert.strictEqual(coaccionar(null, 'algo'), 'algo');
    assert.strictEqual(coaccionar(null, ''), null);
  });

  it('sólo los números se muestran formateados', () => {
    assert.equal(paraMostrar(1234567), '1.234.567');
    assert.equal(paraMostrar('11.111.111-1'), '11.111.111-1');
    assert.equal(paraMostrar(null), '');
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


describe('SUMAR A UNA LISTA', () => {
  /* Compliance lo habilitó el 23-10-2026: a un reporte le puede faltar un
     reportado y el analista lo agrega. QUITAR sigue sin poder — eso lo
     rechaza el backend. */

  const MODELO = { nombre: 'Uno', rut: '1', monto: 100, pep: false,
                   direcciones: ['a'] };

  it('la plantilla tiene las mismas claves, con los valores vacíos', () => {
    assert.deepEqual(plantillaDe(MODELO), {
      nombre: null, rut: null, monto: null, pep: null, direcciones: [],
    });
  });

  it('una lista anidada se copia VACÍA', () => {
    // Su propio largo lo decide quien edita, no la plantilla.
    assert.deepEqual(plantillaDe(MODELO).direcciones, []);
  });

  it('CON LA LISTA VACÍA NO SE PUEDE AGREGAR', () => {
    // Sin plantilla no hay forma que copiar, y adivinar qué campos lleva un
    // reportado es cómo se manda al regulador un registro incompleto.
    assert.equal(sePuedeAgregar([]), false);
    assert.equal(sePuedeAgregar(undefined), false);
    assert.equal(sePuedeAgregar([MODELO]), true);
  });

  it('agregar deja la lista un elemento más larga, sin tocar los que había', () => {
    const lista = [MODELO];
    const nueva = conUnoMas(lista, lista);
    assert.equal(nueva.length, 2);
    assert.deepEqual(nueva[0], MODELO);
    assert.equal(nueva[1].nombre, null);
    assert.equal(lista.length, 1, 'mutó la original');
  });

  it('sobre una lista vacía no agrega nada', () => {
    assert.deepEqual(conUnoMas([], []), []);
  });

  it('encuentra las listas para dibujarles el botón', () => {
    const contenido = { reportados: [MODELO], nota: 'x',
                        anidado: { motivos: ['uno'] } };
    const rutas = listasDe(contenido).map((l) => l.ruta).sort();
    assert.deepEqual(rutas, ['anidado.motivos', 'reportados',
                             'reportados[0].direcciones']);
  });

  it('un contenido sin listas no da ningún botón', () => {
    assert.deepEqual(listasDe({ a: 1, b: { c: 'x' } }), []);
  });
});

describe('LAS LISTAS DENTRO DE UN ELEMENTO AGREGADO', () => {
  /* El caso típico: un reportado de GEREO trae `telefonos`. Al agregar una
     persona, su lista de teléfonos nace vacía y hay que poder llenarla — y
     la plantilla no puede salir de ella misma, que está vacía. */

  const V1 = { rep: [{ nombre: 'Uno', telefonos: ['+56 1'] }] };

  it('la plantilla sale del elemento 0, no del recién agregado', () => {
    const conDos = { rep: [V1.rep[0], { nombre: null, telefonos: [] }] };
    assert.deepEqual(plantillaDeLista(conDos, 'rep[1].telefonos'), ['+56 1']);
  });

  it('así el botón de la lista anidada queda habilitado', () => {
    const conDos = { rep: [V1.rep[0], { nombre: null, telefonos: [] }] };
    const l = listasDe(conDos).find((x) => x.ruta === 'rep[1].telefonos');
    assert.equal(sePuedeAgregar(l.plantilla), true);
    assert.equal(sePuedeAgregar(l.lista), false, 'la suya está vacía');
  });

  it('la etiqueta no arrastra el índice', () => {
    const conDos = { rep: [V1.rep[0], { nombre: null, telefonos: [] }] };
    const l = listasDe(conDos).find((x) => x.ruta === 'rep[1].telefonos');
    assert.equal(l.etiqueta, 'Telefonos');
  });
});

describe('UN AGREGADO VACÍO SE AVISA ANTES DE GUARDAR', () => {
  /* El backend lo rechaza. Enterarse al apretar «Guardar» es el mismo
     rechazo tardío que ya nos pasó con los montos. */

  const ORIGINAL = { rep: [{ nombre: 'Uno', rut: '1' }] };

  it('detecta el agregado en blanco', () => {
    const actual = { rep: [ORIGINAL.rep[0], { nombre: null, rut: null }] };
    assert.deepEqual(agregadosVacios(actual, ORIGINAL), ['rep[1]']);
  });

  it('con un dato ya no avisa', () => {
    const actual = { rep: [ORIGINAL.rep[0], { nombre: 'Dos', rut: null }] };
    assert.deepEqual(agregadosVacios(actual, ORIGINAL), []);
  });

  it('NO avisa por los que ya estaban, aunque se vacíen', () => {
    // Vaciar un campo que GEREO llenó es otra decisión, con su propio
    // control: se resalta en la aprobación.
    const actual = { rep: [{ nombre: null, rut: null }] };
    assert.deepEqual(agregadosVacios(actual, ORIGINAL), []);
  });

  it('un cero o un false son datos, no vacíos', () => {
    const orig = { rep: [{ monto: 1, pep: true }] };
    const actual = { rep: [orig.rep[0], { monto: 0, pep: false }] };
    assert.deepEqual(agregadosVacios(actual, orig), []);
  });

  it('los espacios en blanco no cuentan como dato', () => {
    const actual = { rep: [ORIGINAL.rep[0], { nombre: '   ', rut: '' }] };
    assert.deepEqual(agregadosVacios(actual, ORIGINAL), ['rep[1]']);
  });
});
