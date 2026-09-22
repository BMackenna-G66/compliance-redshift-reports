/* Los envíos del relevo.
 *
 * Del otro lado de cada uno de estos botones hay una persona real y un correo
 * que no se deshace. Lo que se prueba acá es lo que frena un envío que no
 * correspondía: que el interruptor apagado se vea ANTES de escribir, que la
 * confirmación nombre al destinatario en vez de contarlo, y que el lote no se
 * pase del tope. */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  TOPE_LOTE, confirmacionDelLote, confirmacionDeEnvio, esCorridaNueva, impedimento,
  problemaConElLote, puedeEnviar, resumenDelLote,
} from '../src/comun/envios.js';

describe('si se puede enviar', () => {
  const listo = { para: 'cliente@correo.com', asunto: 'Documentación', puede_enviar: true };

  it('con vista previa lista y el interruptor encendido, se puede', () => {
    assert.equal(puedeEnviar(listo), true);
    assert.equal(impedimento(listo), '');
  });

  it('el interruptor apagado lo frena, y lo dice', () => {
    // Se dice ANTES de que alguien escriba un correo entero creyendo que va
    // a salir.
    const m = impedimento({ ...listo, puede_enviar: false });
    assert.match(m, /interruptor|apagado/i);
  });

  it('el motivo del backend manda por sobre el genérico', () => {
    const m = impedimento({ ...listo, puede_enviar: false, motivo: 'el partner no responde' });
    assert.equal(m, 'el partner no responde');
  });

  it('sin destinatario no se manda nada', () => {
    // Mandarlo igual sería un correo al vacío que queda registrado como
    // enviado, y el caso avanza de etapa sin que nadie haya recibido nada.
    assert.match(impedimento({ ...listo, para: '' }), /dirección/i);
  });

  it('un error de la vista previa se muestra tal cual', () => {
    assert.equal(impedimento({ error: 'no hay plantilla para ese partner' }),
                 'no hay plantilla para ese partner');
  });

  it('sin vista previa todavía, no se puede', () => {
    assert.equal(puedeEnviar(null), false);
    assert.equal(puedeEnviar(undefined), false);
  });

  it('`puede_enviar` ausente no se toma como apagado', () => {
    // El backend no lo manda en todas las respuestas; tratarlo como `false`
    // bloquearía envíos legítimos y nadie entendería por qué.
    assert.equal(puedeEnviar({ para: 'x@y.com' }), true);
  });
});

describe('la confirmación de un envío', () => {
  const vista = { para: 'cliente@correo.com', asunto: 'Documentación pendiente' };

  it('nombra al destinatario, no lo cuenta', () => {
    // «Se enviará 1 correo» no frena un envío al cliente equivocado; ver la
    // dirección sí.
    assert.match(confirmacionDeEnvio(vista), /cliente@correo\.com/);
  });

  it('muestra el asunto', () => {
    assert.match(confirmacionDeEnvio(vista), /Documentación pendiente/);
  });

  it('avisa cuando además cierra el caso', () => {
    // La devolución cierra el caso: es una consecuencia distinta de mandar un
    // recordatorio, y tiene que verse antes de apretar.
    assert.match(confirmacionDeEnvio(vista, { cierra: true }), /CIERRA/);
    assert.doesNotMatch(confirmacionDeEnvio(vista), /CIERRA/);
  });

  it('sin destinatario lo dice en vez de mostrar «undefined»', () => {
    assert.match(confirmacionDeEnvio({}), /sin destinatario/);
  });
});

describe('el lote de pedidos', () => {
  const caso = (i) => ({
    id: `c${i}`, cliente_nombre: `Cliente ${i}`, cliente_correo: `c${i}@correo.com`,
  });
  const lote = (n) => Array.from({ length: n }, (_, i) => caso(i + 1));

  it('un lote normal pasa', () => {
    assert.equal(problemaConElLote(lote(5)), '');
  });

  it('sin selección no hay lote', () => {
    assert.match(problemaConElLote([]), /ningún caso/i);
    assert.match(problemaConElLote(null), /ningún caso/i);
  });

  it('se frena arriba del tope, antes de armar veinte correos', () => {
    const m = problemaConElLote(lote(TOPE_LOTE + 1));
    assert.match(m, new RegExp(String(TOPE_LOTE)));
    assert.match(m, /Achicá/);
  });

  it('justo en el tope, pasa', () => {
    assert.equal(problemaConElLote(lote(TOPE_LOTE)), '');
  });

  it('un caso sin correo frena el lote entero', () => {
    // El backend lo saltearía y devolvería un fallido; frenarlo acá evita
    // mandar diecinueve correos y descubrir el veinteavo al final.
    const casos = [...lote(3), { id: 'x', cliente_nombre: 'Sin correo' }];
    assert.match(problemaConElLote(casos), /no tienen correo/);
  });

  it('la confirmación nombra a los clientes', () => {
    const t = confirmacionDelLote(lote(3));
    assert.match(t, /Cliente 1/);
    assert.match(t, /c3@correo\.com/);
    assert.match(t, /REALES/);
  });

  it('con muchos, nombra a ocho y resume el resto', () => {
    const t = confirmacionDelLote(lote(15));
    assert.match(t, /Cliente 8/);
    assert.doesNotMatch(t, /Cliente 9\b/);
    assert.match(t, /y 7 más/);
  });

  it('el resultado nombra cada fallo con su motivo', () => {
    // «3 fallidos» obliga a ir a buscar cuáles, y el motivo de cada uno suele
    // ser distinto: uno sin correo, otro con el interruptor apagado.
    const r = resumenDelLote({
      enviados: 2, fallidos: 2,
      resultados: [
        { caso_id: 'a', enviado: true },
        { caso_id: 'b', enviado: false, error: 'sin correo' },
        { caso_id: 'c', enviado: false },
      ],
    });
    assert.equal(r.enviados, 2);
    assert.equal(r.detalle.length, 2);
    assert.deepEqual(r.detalle[0], { caso: 'b', motivo: 'sin correo' });
    assert.equal(r.detalle[1].motivo, 'sin detalle');
  });

  it('un lote sin respuesta no rompe', () => {
    assert.deepEqual(resumenDelLote(null), { enviados: 0, fallidos: 0, detalle: [] });
  });
});

describe('el espejo de Redshift', () => {
  it('una corrida con arranque distinto es nueva', () => {
    assert.equal(esCorridaNueva({ arrancado_en: '2026-09-22T10:00' }, '2026-09-21T10:00'), true);
  });

  it('la misma corrida no es nueva', () => {
    // Sin esta comparación se muestra la corrida de ayer como si fuera la que
    // se acaba de disparar.
    assert.equal(esCorridaNueva({ arrancado_en: '2026-09-21T10:00' }, '2026-09-21T10:00'), false);
  });

  it('sin corrida todavía, no es nueva', () => {
    assert.equal(esCorridaNueva(null, ''), false);
    assert.equal(esCorridaNueva({}, ''), false);
  });

  it('la primera corrida de la historia sí es nueva', () => {
    assert.equal(esCorridaNueva({ arrancado_en: '2026-09-22T10:00' }, ''), true);
  });
});
