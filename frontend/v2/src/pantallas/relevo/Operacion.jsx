/* ============================================================================
   La operación del relevo
   ----------------------------------------------------------------------------
   Lo que no es un caso en particular: el padrón de clientes, las plantillas de
   mensaje, la configuración, los vencidos, el espejo de Redshift, la
   resolución automática y el envío en lote.

   TODO LO QUE MANDA CORREOS PIDE CONFIRMACIÓN NOMBRANDO A QUIÉN. El lote es el
   más peligroso de la pantalla: veinte correos a veinte clientes reales con un
   clic. Por eso la confirmación lista los destinatarios en vez de contarlos.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { Tabla } from '../../comun/Tabla.jsx';
import {
  AVISO_FORZAR_ESPEJO, ESPERA_ESPEJO, VUELTAS_ESPEJO, confirmacionDelLote,
  esCorridaNueva, problemaConElLote, resumenDelLote,
} from '../../comun/envios.js';

function Carta({ titulo, herramientas, children }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{titulo}</h2>
        {herramientas && <div className="wt-carta-herramientas">{herramientas}</div>}
      </header>
      <div className="wt-cuerpo-carta">{children}</div>
    </section>
  );
}

export function Operacion({ api, email, lectura, casos, alRecargar, alRecontactar }) {
  const [vencidos, setVencidos] = useState([]);
  const [clientes, setClientes] = useState([]);
  const [mensajes, setMensajes] = useState([]);
  const [config, setConfig] = useState(null);
  const [espejo, setEspejo] = useState(null);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [ocupado, setOcupado] = useState('');
  const [seleccion, setSeleccion] = useState([]);

  const cargar = useCallback(async () => {
    setError('');
    // `allSettled`: que falte el padrón no puede tapar los vencidos, que son
    // lo accionable de esta pantalla.
    const [v, c, m, cf, e] = await Promise.allSettled([
      api.get('/relevo/vencidos'),
      api.get('/relevo/clientes'),
      api.get('/relevo/mensajes'),
      api.get('/relevo/config'),
      api.get('/relevo/espejo'),
    ]);
    if (v.status === 'fulfilled') setVencidos(v.value?.vencidos || v.value?.casos || []);
    if (c.status === 'fulfilled') setClientes(c.value?.clientes || []);
    if (m.status === 'fulfilled') setMensajes(m.value?.mensajes || []);
    if (cf.status === 'fulfilled') setConfig(cf.value || null);
    if (e.status === 'fulfilled') setEspejo(e.value?.ultima || null);
    const fallas = [v, c, m, cf, e].filter((r) => r.status === 'rejected');
    if (fallas.length) {
      setError(`${fallas.length} de 5 consultas no respondieron: ${fallas[0].reason?.message || ''}`);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  async function conAviso(nombre, fn) {
    setOcupado(nombre); setError(''); setAviso('');
    try { await fn(); } catch (e) {
      setError(e?.message || 'No se pudo completar la acción.');
    } finally { setOcupado(''); }
  }

  const resolver = () => conAviso('resolver', async () => {
    const d = await api.post('/relevo/resolver', {});
    setAviso(`Resolución: ${d?.resueltos ?? 0} resueltos de ${d?.pendientes ?? 0} pendientes.`
           + (d?.nota ? ` ${d.nota}` : ''));
    await alRecargar();
  });

  const probar = () => conAviso('probar', async () => {
    const d = await api.post('/relevo/probar', {});
    // Probar NO le escribe al cliente: arma el correo y lo manda a la casilla
    // de pruebas. Decirlo evita el susto de creer que salió de verdad.
    setAviso(d?.detalle || d?.mensaje
      || 'Prueba hecha: el correo salió a la casilla de pruebas, no al cliente.');
  });

  function correrEspejo(forzar) {
    if (forzar && !globalThis.confirm(AVISO_FORZAR_ESPEJO)) return;
    conAviso('espejo', async () => {
      const antes = (await api.get('/relevo/espejo'))?.ultima?.arrancado_en || '';
      await api.post('/relevo/espejo', { forzar: !!forzar });
      setAviso('Disparado. Corre en la Lambda de reportes; se avisa al terminar.');
      // El espejo corre en otra Lambda, así que no devuelve el resultado: hay
      // que esperar a que aparezca una corrida NUEVA.
      for (let i = 0; i < VUELTAS_ESPEJO; i += 1) {
        await new Promise((r) => setTimeout(r, ESPERA_ESPEJO));
        const u = (await api.get('/relevo/espejo').catch(() => null))?.ultima;
        if (esCorridaNueva(u, antes)) {
          setEspejo(u);
          setAviso(`Espejo terminado: ${u.filas ?? u.n_filas ?? '—'} filas.`);
          return;
        }
      }
      setAviso('El espejo sigue corriendo después de dos minutos. Quedó lanzado: '
             + 'volvé a entrar más tarde para ver el resultado.');
    });
  }

  function enviarLote() {
    const elegidos = casos.filter((c) => seleccion.includes(c.id));
    const problema = problemaConElLote(elegidos);
    if (problema) { setError(problema); return; }
    if (!globalThis.confirm(confirmacionDelLote(elegidos))) return;
    conAviso('lote', async () => {
      const d = await api.post('/relevo/pedidos/lote', {
        caso_ids: elegidos.map((c) => c.id), confirmado: true, quien: email || '',
      });
      if (d?.error) throw new Error(d.error);
      const r = resumenDelLote(d);
      setAviso(`Enviados ${r.enviados} · fallidos ${r.fallidos}.`);
      // Los fallos se nombran uno por uno: el motivo de cada uno suele ser
      // distinto y «3 fallidos» obliga a ir a buscar cuáles.
      if (r.detalle.length) {
        setError('No salieron:\n' + r.detalle.map((x) => `  · ${x.caso}: ${x.motivo}`).join('\n'));
      }
      setSeleccion([]);
      await alRecargar();
    });
  }

  const enviables = casos.filter((c) => c.cliente_correo);

  return (
    <>
      {error && (
        <div className="wt-estado-error"
             style={{ marginBottom: 'var(--e-4)', whiteSpace: 'pre-wrap' }}>{error}</div>
      )}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {/* ── Vencidos ──────────────────────────────────────────────────── */}
      <Carta titulo={`Vencidos · ${vencidos.length}`}
             herramientas={<button className="wt-btn" onClick={cargar}>Refrescar</button>}>
        {vencidos.length === 0 ? (
          <p className="wt-vacio">Ningún caso pasado de plazo.</p>
        ) : (
          <div className="wt-tabla-marco">
            <table className="wt-tabla">
              <thead>
                <tr><th>Cliente</th><th>Partner</th><th>Vence</th><th>Intentos</th><th /></tr>
              </thead>
              <tbody>
                {vencidos.map((v) => (
                  <tr key={v.caso_id || v.id}>
                    <td>{v.cliente_nombre || v.cliente_correo || '—'}</td>
                    <td>{v.partner || '—'}</td>
                    <td>{v.vence || v.plazo || '—'}</td>
                    <td className="wt-td-num">{v.intentos ?? '—'}</td>
                    <td>
                      {!lectura && (
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => alRecontactar(v)}>
                          Recontactar
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Carta>

      {/* ── El lote ──────────────────────────────────────────────────── */}
      {!lectura && (
        <Carta titulo="Pedido en lote">
          <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
            Le manda el pedido de documentación a varios clientes de una vez. Cada uno
            recibe su propio correo. El tope es 20 por lote, y la confirmación lista a
            quiénes les va a llegar antes de mandar nada.
          </p>
          <div className="wt-checklist" style={{ maxHeight: 260, overflowY: 'auto' }}>
            {enviables.length === 0 ? (
              <p className="wt-vacio">Ningún caso con correo de cliente.</p>
            ) : enviables.map((c) => (
              <label key={c.id} className="wt-checklist-item" style={{ cursor: 'pointer' }}>
                <input type="checkbox" checked={seleccion.includes(c.id)}
                       onChange={(e) => setSeleccion((s) => (
                         e.target.checked ? [...s, c.id] : s.filter((x) => x !== c.id)))} />
                <span>{c.cliente_nombre || '(sin nombre)'}</span>
                <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-xs)',
                               color: 'var(--texto-mute)' }}>
                  {c.cliente_correo}
                </span>
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-3)' }}>
            <button className="wt-btn wt-btn-primario"
                    disabled={seleccion.length === 0 || ocupado === 'lote'}
                    onClick={enviarLote}>
              {ocupado === 'lote' ? 'Enviando…' : `Enviar a ${seleccion.length}`}
            </button>
            {seleccion.length > 0 && (
              <button className="wt-btn" onClick={() => setSeleccion([])}>Deseleccionar</button>
            )}
          </div>
        </Carta>
      )}

      {/* ── Mantenimiento ────────────────────────────────────────────── */}
      <Carta titulo="Mantenimiento">
        <div style={{ display: 'flex', gap: 'var(--e-2)', flexWrap: 'wrap' }}>
          <button className="wt-btn" disabled={lectura || ocupado === 'resolver'} onClick={resolver}>
            {ocupado === 'resolver' ? 'Resolviendo…' : 'Resolver pendientes'}
          </button>
          <button className="wt-btn" disabled={lectura || ocupado === 'probar'} onClick={probar}>
            {ocupado === 'probar' ? 'Probando…' : 'Probar el envío'}
          </button>
          <button className="wt-btn" disabled={lectura || ocupado === 'espejo'}
                  onClick={() => correrEspejo(false)}>
            {ocupado === 'espejo' ? 'Corriendo…' : 'Correr el espejo'}
          </button>
          <button className="wt-btn" disabled={lectura || ocupado === 'espejo'}
                  onClick={() => correrEspejo(true)}>
            Forzar el espejo
          </button>
        </div>
        <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          «Probar» arma el correo y lo manda a la casilla de pruebas, no al cliente.
          «Forzar» enciende el clúster de Redshift si está pausado, y eso cuesta.
        </p>
        {espejo && (
          <dl className="wt-datos" style={{ marginTop: 'var(--e-3)' }}>
            <dt>Última corrida del espejo</dt><dd>{espejo.arrancado_en || '—'}</dd>
            {espejo.estado && <><dt>Estado</dt><dd>{espejo.estado}</dd></>}
            {(espejo.filas ?? espejo.n_filas) !== undefined && (
              <><dt>Filas</dt><dd>{Number(espejo.filas ?? espejo.n_filas).toLocaleString('es-CL')}</dd></>
            )}
          </dl>
        )}
      </Carta>

      {/* ── Referencia ───────────────────────────────────────────────── */}
      {mensajes.length > 0 && (
        <Carta titulo={`Plantillas de mensaje · ${mensajes.length}`}>
          <div className="wt-checklist">
            {mensajes.map((m, i) => (
              <div key={m.clave || i} className="wt-checklist-item" style={{ cursor: 'default' }}>
                <span>{m.nombre || m.clave}</span>
                <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-xs)',
                               color: 'var(--texto-mute)' }}>
                  {m.idioma || ''} {m.partner || ''}
                </span>
              </div>
            ))}
          </div>
        </Carta>
      )}

      {config && (
        <Carta titulo="Configuración del relevo">
          <dl className="wt-datos">
            {Object.entries(config).filter(([, v]) => typeof v !== 'object').map(([k, v]) => (
              <div key={k} style={{ display: 'contents' }}>
                <dt>{k.replace(/_/g, ' ')}</dt>
                <dd className="mono">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </Carta>
      )}

      {clientes.length > 0 && (
        <Tabla
          titulo={`Padrón de clientes · ${clientes.length}`}
          columnas={[
            { clave: 'cliente_id', titulo: 'Id', tipo: 'mono', ancho: '14%' },
            { clave: 'nombre', titulo: 'Nombre', ancho: '30%' },
            { clave: 'correo', titulo: 'Correo' },
            { clave: 'partner', titulo: 'Partner', ancho: '18%' },
          ]}
          filas={clientes}
          claveFila={(c, i) => c.cliente_id ?? i}
          porPagina={25}
          nombreExport="clientes-relevo"
        />
      )}
    </>
  );
}
