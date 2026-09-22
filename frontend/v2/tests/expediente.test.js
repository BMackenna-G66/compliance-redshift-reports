/* El expediente del caso.
 *
 * Lo que se prueba acá son las decisiones que se ven en pantalla: qué campo
 * se esconde, en qué orden gira el checklist, qué correo se pinta como
 * fallido. Todas tienen una forma de romperse que NO da error: la grilla
 * muestra un campo de más, el documento queda en el estado equivocado, el
 * correo que nunca salió se lee como enviado. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  EXTENSIONES_ADJUNTO, adjuntoAceptado, altaDeWhitelist, campos, contextoDelCliente,
  cuerpoRecortado, esFallido, estadoDocumento, notaDeWhitelist, promptDelCaso,
  repartirAdjuntos, resumenChecklist, resumenCorreos, siguienteEstadoDocumento,
  vinoPorCorreo,
} from '../src/comun/expediente.js';

describe('los campos de una ficha', () => {
  it('esconde lo vacío, incluido el guión que manda el backend', () => {
    // «—» no es un dato: es el backend diciendo que no lo tiene. Mostrarlo
    // llena la grilla de filas mudas y esconde las que sí dicen algo.
    const f = campos({ a: 1, b: '', c: null, d: '—', e: undefined, f: '-', g: 'ok' });
    assert.deepEqual(f.map((x) => x.clave), ['a', 'g']);
  });

  it('los números salen con separador de miles', () => {
    const [f] = campos({ monto_usd: 1234567 });
    assert.equal(f.valor, (1234567).toLocaleString('es-CL'));
  });

  it('los booleanos salen en palabras, no en «false»', () => {
    // «false» dentro de una ficha de compliance se lee como un dato del
    // cliente, no como un «no».
    assert.equal(campos({ pep: false })[0].valor, 'No');
    assert.equal(campos({ pep: true })[0].valor, 'Sí');
  });

  it('un cero es un dato y se muestra', () => {
    // El caso que se rompe con un `if (!valor) continue`: cero devuelto
    // significa «no movió plata», que es justo lo que hay que ver.
    assert.equal(campos({ operaciones: 0 })[0].valor, '0');
  });

  it('un objeto anidado se serializa en vez de quedar en [object Object]', () => {
    assert.equal(campos({ x: { a: 1 } })[0].valor, '{"a":1}');
  });

  it('la etiqueta cambia los guiones bajos por espacios', () => {
    assert.equal(campos({ total_payout_usd_7d: 5 })[0].etiqueta, 'total payout usd 7d');
  });

  it('lo que no es un objeto no rompe', () => {
    for (const v of [null, undefined, 'texto', 42, [1, 2]]) {
      assert.deepEqual(campos(v), []);
    }
  });
});

describe('el checklist de documentos', () => {
  it('gira pendiente → recibido → entregado → pendiente', () => {
    assert.equal(siguienteEstadoDocumento('pendiente'), 'recibido');
    assert.equal(siguienteEstadoDocumento('recibido'), 'entregado');
    assert.equal(siguienteEstadoDocumento('entregado'), 'pendiente');
  });

  it('un estado desconocido arranca el ciclo en vez de trabarse', () => {
    assert.equal(siguienteEstadoDocumento('cualquiera'), 'recibido');
    assert.equal(siguienteEstadoDocumento(undefined), 'recibido');
  });

  it('sin estado, el documento está pendiente', () => {
    assert.equal(estadoDocumento({}), 'pendiente');
    assert.equal(estadoDocumento({ estado: 'inventado' }), 'pendiente');
    assert.equal(estadoDocumento({ estado: 'entregado' }), 'entregado');
  });

  it('el resumen cuenta cada estado y el total cierra', () => {
    const r = resumenChecklist([
      { categoria: 'a' }, { categoria: 'b', estado: 'recibido' },
      { categoria: 'c', estado: 'entregado' }, { categoria: 'd', estado: 'entregado' },
    ]);
    assert.deepEqual(r, { pendiente: 1, recibido: 1, entregado: 2, total: 4 });
  });

  it('sin documentos da ceros y no rompe', () => {
    assert.equal(resumenChecklist(null).total, 0);
  });
});

describe('el historial de correos', () => {
  it('un envío que no salió se marca fallido', () => {
    // Un correo que nunca llegó y se dibuja como enviado hace creer que el
    // cliente no contestó. Eso cambia la conclusión del caso.
    assert.equal(esFallido({ direccion: 'enviado', salio: false }), true);
    assert.equal(esFallido({ direccion: 'enviado', salio: true }), false);
  });

  it('lo recibido nunca es un fallo, aunque venga sin `salio`', () => {
    assert.equal(esFallido({ direccion: 'recibido' }), false);
  });

  it('un envío sin el campo `salio` no se acusa de fallido', () => {
    // Los correos viejos no lo guardaban. Pintarlos en rojo inventaría
    // fallas que nunca ocurrieron.
    assert.equal(esFallido({ direccion: 'enviado' }), false);
  });

  it('el cuerpo largo se recorta y se avisa', () => {
    const largo = 'x'.repeat(500);
    const r = cuerpoRecortado({ cuerpo: largo });
    assert.equal(r.texto.length, 400);
    assert.equal(r.recortado, true);
  });

  it('el cuerpo corto llega entero y sin marca', () => {
    assert.deepEqual(cuerpoRecortado({ cuerpo: 'hola' }), { texto: 'hola', recortado: false });
    assert.deepEqual(cuerpoRecortado({}), { texto: '', recortado: false });
  });

  it('el resumen no rompe cuando el backend no manda nada', () => {
    assert.deepEqual(resumenCorreos(null),
      { enviados: 0, recibidos: 0, fallidos: 0, correos: [] });
    assert.deepEqual(resumenCorreos({ correos: 'no es una lista' }).correos, []);
  });
});

describe('los adjuntos', () => {
  it('distingue lo que mandó el cliente de lo que subió un analista', () => {
    // En una auditoría no es lo mismo «el cliente mandó el contrato» que
    // «alguien de compliance lo adjuntó».
    assert.equal(vinoPorCorreo({ source: 'email_reply' }), true);
    assert.equal(vinoPorCorreo({ source: 'upload' }), false);
  });

  it('acepta las extensiones del backend, sin importar la caja', () => {
    assert.equal(adjuntoAceptado('contrato.PDF'), true);
    assert.equal(adjuntoAceptado('foto.HEIC'), true);
    assert.equal(adjuntoAceptado('planilla.xlsx'), true);
  });

  it('rechaza lo que el backend rechaza', () => {
    for (const n of ['virus.exe', 'notas.txt', 'paquete.zip', 'sin_extension']) {
      assert.equal(adjuntoAceptado(n), false, n);
    }
  });

  it('un punto en el nombre no confunde a la extensión', () => {
    assert.equal(adjuntoAceptado('acta.2026.01.pdf'), true);
    assert.equal(adjuntoAceptado('acta.pdf.exe'), false);
  });

  it('sube los buenos y deja afuera los malos, en vez de cortar en el primero', () => {
    // Si alguien arrastra ocho documentos y uno tiene extensión rara, lo
    // razonable es subir los siete y decir cuál quedó afuera.
    const { suben, rechazados } = repartirAdjuntos([
      { name: 'a.pdf' }, { name: 'b.exe' }, { name: 'c.png' },
    ]);
    assert.deepEqual(suben.map((a) => a.name), ['a.pdf', 'c.png']);
    assert.deepEqual(rechazados.map((a) => a.name), ['b.exe']);
  });

  it('sin archivos no rompe', () => {
    assert.deepEqual(repartirAdjuntos(null), { suben: [], rechazados: [] });
  });

  it('la lista de extensiones no está vacía', () => {
    // Si el extractor del test de sincronía dejara de encontrarla, este
    // módulo rechazaría todo en silencio.
    assert.ok(EXTENSIONES_ADJUNTO.length >= 8);
  });
});

describe('la whitelist que nace del caso', () => {
  const caso = { entity_id: 12345, entity_type: 'customer', report_name: 'payin_payout' };

  it('una persona va por customer_id y una empresa por company_id', () => {
    // Equivocar el campo crea una entrada que no va a coincidir con nada:
    // el cruce de la whitelist es exacto.
    assert.equal(altaDeWhitelist(caso, {}).entity_field, 'customer_id');
    assert.equal(
      altaDeWhitelist({ ...caso, entity_type: 'company' }, {}).entity_field, 'company_id');
  });

  it('el id viaja como texto', () => {
    assert.strictEqual(altaDeWhitelist(caso, {}).entity_value, '12345');
  });

  it('«sólo este reporte» arrastra cuál es', () => {
    const c = altaDeWhitelist(caso, { alcance: 'report', dias: 30, motivo: 'x', quien: 'a@b' });
    assert.equal(c.report_name, 'payin_payout');
  });

  it('«todas las alertas» no manda reporte', () => {
    const c = altaDeWhitelist(caso, { alcance: 'global', dias: 30, motivo: 'x' });
    assert.equal('report_name' in c, false);
  });

  it('los días viajan como número', () => {
    assert.strictEqual(altaDeWhitelist(caso, { dias: '60' }).duration_days, 60);
  });

  it('la nota dice el plazo, el alcance y el motivo', () => {
    const cuerpo = altaDeWhitelist(caso, {
      alcance: 'report', dias: 90, motivo: 'cliente conocido', quien: 'a@b',
    });
    const nota = notaDeWhitelist(cuerpo);
    assert.match(nota, /90 días/);
    assert.match(nota, /payin_payout/);
    assert.match(nota, /cliente conocido/);
  });
});

describe('el prompt del análisis con IA', () => {
  const caso = { title: 'Caso X', entity_id: 42, report_name: 'r1', priority: 'high' };

  it('lleva el caso, las alertas y las notas', () => {
    const p = promptDelCaso({
      caso,
      alertas: [{ entity_value: '42', reason: 'monto alto', report_name: 'r1' }],
      notas: [{ author_email: 'a@b', created_at: '2026-01-01', content: 'revisado' }],
      etiquetaEstado: 'Abierto',
    });
    assert.match(p, /Caso X/);
    assert.match(p, /monto alto/);
    assert.match(p, /revisado/);
    assert.match(p, /Abierto/);
  });

  it('sin alertas ni notas lo dice, en vez de dejar el hueco', () => {
    // Un bloque vacío hace que el modelo suponga; uno que dice «sin notas»
    // le pide que lo aclare.
    const p = promptDelCaso({ caso, alertas: [], notas: [] });
    assert.match(p, /Sin alertas vinculadas/);
    assert.match(p, /Sin notas aún/);
  });

  it('mantiene las dos reglas que frenan la invención', () => {
    // Sin ellas el modelo rellena con patrones plausibles que nadie observó,
    // y eso termina copiado en la conclusión de un caso real.
    const p = promptDelCaso({ caso, alertas: [], notas: [] });
    assert.match(p, /Apoyate SOLO en los datos provistos/);
    assert.match(p, /no estimadas/);
  });

  it('el contexto del cliente dice cuando no se consultó', () => {
    assert.match(contextoDelCliente(null), /No se consultó/);
    assert.match(contextoDelCliente({}), /No se consultó/);
  });

  it('el contexto lista los campos de la ficha traída', () => {
    const c = contextoDelCliente({ nombre_completo: 'Ada', pep: false });
    assert.match(c, /nombre completo: Ada/);
    assert.match(c, /pep: No/);
  });
});
