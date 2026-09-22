/* El pedido de documentación al cliente.
 *
 * Es el único lugar donde un analista le escribe directamente a un cliente,
 * así que lo que se prueba es lo que decide si ese correo puede salir — y las
 * dos reglas que no son obvias: la plantilla de texto libre no pide
 * documentos, y un pedido repetido se avisa antes de mandarlo. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  avisoDePedidosPrevios, borradorDelPedido, faltaParaPedir, pedidosSinResponder,
  plantillaPorDefecto, prioridadDelCaso, resolverPlantilla,
} from '../src/comun/pedido.js';

const NORMAL = { key: 'general_b2c', requires_custom_text: false };
const LIBRE = { key: 'texto_libre', requires_custom_text: true };

describe('qué falta para poder mandar el correo', () => {
  it('con correo y documentos, no falta nada', () => {
    assert.deepEqual(
      faltaParaPedir({ correo: 'a@b.com', documentos: ['Domicilio'] }, NORMAL), []);
  });

  it('sin correo no se manda', () => {
    assert.match(faltaParaPedir({ documentos: ['Domicilio'] }, NORMAL)[0], /correo/);
  });

  it('la plantilla normal exige al menos un documento', () => {
    assert.match(faltaParaPedir({ correo: 'a@b.com', documentos: [] }, NORMAL)[0], /documento/);
  });

  it('la plantilla de TEXTO LIBRE no exige documentos', () => {
    // Exigirle uno obligaba a marcar cualquiera, y ese documento después
    // aparecía pedido en el correo y en el checklist: se le terminaba
    // pidiendo al cliente algo que nadie quería pedirle.
    assert.deepEqual(
      faltaParaPedir({ correo: 'a@b.com', documentos: [], textoLibre: 'Hola' }, LIBRE), []);
  });

  it('la plantilla de texto libre sí exige el texto', () => {
    const f = faltaParaPedir({ correo: 'a@b.com', documentos: [] }, LIBRE);
    assert.equal(f.length, 1);
    assert.match(f[0], /texto/);
  });

  it('dice todo lo que falta de una, no de a uno', () => {
    // Quien está escribiendo el correo quiere saberlo todo junto, no
    // descubrirlo cada vez que aprieta.
    assert.equal(faltaParaPedir({}, NORMAL).length, 2);
  });

  it('sin plantilla todavía, se comporta como la normal', () => {
    assert.match(faltaParaPedir({ correo: 'a@b.com', documentos: [] }, null)[0], /documento/);
  });
});

describe('la plantilla', () => {
  it('una empresa y una persona tienen distinta genérica', () => {
    assert.equal(plantillaPorDefecto('company'), 'b2b_generico');
    assert.equal(plantillaPorDefecto('customer'), 'general_b2c');
    assert.equal(plantillaPorDefecto(undefined), 'general_b2c');
  });

  it('una plantilla del catálogo se respeta y no avisa nada', () => {
    const r = resolverPlantilla('general_b2c', [NORMAL, LIBRE], 'customer');
    assert.deepEqual(r, { clave: 'general_b2c', aviso: '' });
  });

  it('una desconocida cae en la genérica Y lo dice', () => {
    // Sin el aviso, el analista escribe con una plantilla distinta de la que
    // eligió y no se entera.
    const r = resolverPlantilla('inventada', [NORMAL], 'company');
    assert.equal(r.clave, 'b2b_generico');
    assert.match(r.aviso, /inventada/);
    assert.match(r.aviso, /b2b_generico/);
  });

  it('sin plantilla elegida, también cae y avisa', () => {
    const r = resolverPlantilla('', [NORMAL], 'customer');
    assert.equal(r.clave, 'general_b2c');
    assert.match(r.aviso, /vacía/);
  });
});

describe('los pedidos previos', () => {
  it('deja los que no respondieron', () => {
    const p = pedidosSinResponder([
      { id: 1, respondida: false },
      { id: 2, respondida: true },
      { id: 3, respondida: false, es_este_caso: true },
    ]);
    assert.deepEqual(p.map((x) => x.id), [1]);
  });

  it('el de este mismo caso no cuenta como duplicado', () => {
    // Obviamente aparece: es el caso desde el que se está escribiendo.
    assert.deepEqual(pedidosSinResponder([{ respondida: false, es_este_caso: true }]), []);
  });

  it('el aviso dice cuántas veces y por qué importa', () => {
    // Dos correos iguales con pocos días de diferencia hacen que el cliente
    // deje de leerlos: el aviso existe para frenar eso ANTES de mandarlo.
    const a = avisoDePedidosPrevios([{}, {}]);
    assert.match(a, /2 vez/);
    assert.match(a, /30 días/);
  });

  it('sin pedidos previos no hay aviso', () => {
    assert.equal(avisoDePedidosPrevios([]), '');
    assert.equal(avisoDePedidosPrevios(null), '');
  });
});

describe('el borrador del pedido', () => {
  const caso = {
    case_id: 'c1', entity_id: 12345, entity_type: 'customer', entity_name: 'Ada L.',
    priority: 'high', report_name: 'estructuracion',
    documentos_checklist: [{ categoria: 'Domicilio' }, { categoria: 'Origen de fondo' }],
  };

  it('la prioridad del correo sale de la del caso', () => {
    assert.equal(prioridadDelCaso({ priority: 'high' }), 'P1');
    assert.equal(prioridadDelCaso({ priority: 'medium' }), 'P2');
    assert.equal(prioridadDelCaso({ priority: 'low' }), 'P3');
    assert.equal(prioridadDelCaso({}), 'P3');
  });

  it('el último pedido manda sobre todo lo demás', () => {
    const b = borradorDelPedido({
      caso, ultimoPedido: { nombre_completo: 'Ada Lovelace', correo: 'ada@correo.com' },
      perfil: { email: 'otro@correo.com' },
    });
    assert.equal(b.nombre, 'Ada Lovelace');
    assert.equal(b.correo, 'ada@correo.com');
  });

  it('sin pedido previo, se cae al caso y a la ficha KYC', () => {
    // El caso que se rompía en v1: el nombre y el correo salían SÓLO del
    // último pedido, así que la primera vez —justo cuando hacen falta—
    // aparecían vacíos.
    const b = borradorDelPedido({ caso, perfil: { email: 'ada@kyc.com' } });
    assert.equal(b.nombre, 'Ada L.');
    assert.equal(b.correo, 'ada@kyc.com');
  });

  it('una empresa toma la razón social del perfil', () => {
    const b = borradorDelPedido({
      caso: { entity_type: 'company' }, perfil: { razon_social: 'Acme SA' },
    });
    assert.equal(b.nombre, 'Acme SA');
    assert.equal(b.template_key, 'b2b_generico');
  });

  it('los documentos arrancan con los del checklist del caso', () => {
    assert.deepEqual(borradorDelPedido({ caso }).documentos,
                     ['Domicilio', 'Origen de fondo']);
  });

  it('el id viaja como texto', () => {
    assert.strictEqual(borradorDelPedido({ caso }).entity_id, '12345');
  });

  it('sin caso no rompe', () => {
    const b = borradorDelPedido({});
    assert.equal(b.correo, '');
    assert.deepEqual(b.documentos, []);
  });
});
