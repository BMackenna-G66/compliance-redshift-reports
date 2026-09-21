/* ============================================================================
   Ficha del cliente
   ----------------------------------------------------------------------------
   El consolidado que arma el backend leyendo Redshift: transacciones,
   productos, países, casos, documentos y correos.

   ES LENTA A PROPÓSITO Y HAY QUE DECIRLO. Medida contra producción, tarda
   unos 11 segundos: consulta Redshift en vivo, y el techo de API Gateway son
   30. Un "Cargando…" sin más, once segundos, se lee como que se colgó — y la
   gente recarga, lo que dispara otra consulta. Por eso el aviso dice cuánto
   tarda y por qué.

   Sin id de cliente no muestra un error: muestra un buscador. Es la única
   pantalla de detalle que llega desde el menú, así que entrar sin id es lo
   normal, no una equivocación.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { fecha, hace } from '../comun/alertas.js';
import { ESTADOS_CASO } from '../dominio.js';

const TONOS = {
  alerta: { color: 'var(--nivel-critico-texto)', fondo: 'var(--nivel-critico-tenue)' },
  aviso:  { color: 'var(--nivel-alto-texto)',    fondo: 'var(--nivel-alto-tenue)' },
  ok:     { color: 'var(--nivel-bajo-texto)',    fondo: 'var(--nivel-bajo-tenue)' },
};

/** Un número del backend, que llega como texto. Nunca inventa un cero. */
function cifra(v, { moneda = false } = {}) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  const t = n.toLocaleString('es-CL', { maximumFractionDigits: moneda ? 0 : 2 });
  return moneda ? `USD ${t}` : t;
}

function Cifra({ etiqueta, valor, titulo }) {
  return (
    <div className="wt-cifra" title={titulo}>
      <span className="wt-cifra-etiqueta">{etiqueta}</span>
      <span className="wt-cifra-valor">{valor}</span>
    </div>
  );
}

function Buscador({ alBuscar }) {
  const [id, setId] = useState('');
  return (
    <div className="wt-pendiente">
      <h2>Ficha del cliente</h2>
      <p>El consolidado de un cliente: transacciones, productos, casos y documentos.</p>
      <form
        style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16 }}
        onSubmit={(e) => { e.preventDefault(); if (id.trim()) alBuscar(id.trim()); }}
      >
        <input className="wt-input" value={id} onChange={(e) => setId(e.target.value)}
               placeholder="Id del cliente" aria-label="Id del cliente" style={{ width: 200 }} />
        <button className="wt-btn wt-btn-primario" type="submit" disabled={!id.trim()}>
          Buscar
        </button>
      </form>
      <p style={{ fontSize: 'var(--texto-sm)', marginTop: 16 }}>
        Consulta Redshift en vivo: tarda unos diez segundos.
      </p>
    </div>
  );
}

export function Ficha({ api, id: entityId, navegar }) {
  const [ficha, setFicha] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const [pdf, setPdf] = useState('');

  const cargar = useCallback(async () => {
    if (!entityId) return;
    setCargando(true); setError(''); setFicha(null);
    try {
      setFicha(await api.get(`/clientes/${encodeURIComponent(entityId)}/ficha`));
    } catch (e) {
      setError(e?.message || 'No se pudo cargar la ficha.');
    } finally {
      setCargando(false);
    }
  }, [api, entityId]);

  useEffect(() => { cargar(); }, [cargar]);

  async function descargar() {
    setPdf('generando'); setError('');
    try {
      const d = await api.get(`/clientes/${encodeURIComponent(entityId)}/ficha.pdf`);
      if (!d?.url) throw new Error('El backend no devolvió una dirección de descarga.');
      // La ventana se abre DESPUÉS del await, así que el navegador puede
      // tomarla por emergente. Por eso además queda el enlace a la vista.
      globalThis.open(d.url, '_blank', 'noopener');
      setPdf(d.url);
    } catch (e) {
      setError(e?.message || 'No se pudo generar el PDF.');
      setPdf('');
    }
  }

  if (!entityId) return <Buscador alBuscar={(id) => navegar('ficha', [id])} />;

  const r = ficha?.resumen || {};
  const t = ficha?.totales || {};

  return (
    <>
      <nav className="wt-migas">
        <button onClick={() => navegar('ficha')}>Ficha del cliente</button>
        <span>›</span>
        <span className="mono">{entityId}</span>
      </nav>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {cargando ? (
        <div className="wt-estado">
          <p style={{ margin: 0 }}>Armando la ficha de <span className="mono">{entityId}</span>…</p>
          <p style={{ fontSize: 'var(--texto-sm)', marginTop: 8 }}>
            Consulta Redshift en vivo y suele tardar unos diez segundos. No recargues:
            recargar dispara otra consulta y tarda lo mismo de nuevo.
          </p>
        </div>
      ) : !ficha ? null : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                        marginBottom: 'var(--e-4)' }}>
            <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
              {ficha.nombre || `Cliente ${entityId}`}
            </h1>
            <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              {ficha.periodo}
            </span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 'var(--e-2)' }}>
              <button className="wt-btn" onClick={descargar} disabled={pdf === 'generando'}>
                {pdf === 'generando' ? 'Generando…' : 'Descargar PDF'}
              </button>
              <button className="wt-btn" onClick={cargar}>Refrescar</button>
            </div>
          </div>

          {/* El navegador puede bloquear la ventana emergente. Sin este
              enlace, la descarga se perdería sin que nadie sepa por qué. */}
          {pdf && pdf !== 'generando' && (
            <p className="wt-nota">
              Si no se abrió la descarga,{' '}
              <a href={pdf} target="_blank" rel="noopener noreferrer">abrila desde acá</a>.
              El enlace vence en 15 minutos.
            </p>
          )}

          {(ficha.avisos || []).map((a, i) => {
            const tono = TONOS[a.tono] || TONOS.aviso;
            return (
              <p key={i} className="wt-nota"
                 style={{ borderColor: tono.color, background: tono.fondo, color: tono.color }}>
                {a.texto}
              </p>
            );
          })}
          {ficha.aviso_transaccional && (
            <p className="wt-nota">{ficha.aviso_transaccional}</p>
          )}

          <div className="wt-ficha-grilla">
            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">Movimiento</h2>
              </header>
              <div className="wt-cuerpo-carta">
                <div className="wt-cifras">
                  <Cifra etiqueta="Transacciones" valor={cifra(r.n_filas)} />
                  <Cifra etiqueta="Total" valor={cifra(r.total_usd, { moneda: true })} />
                  <Cifra etiqueta="Ticket promedio" valor={cifra(r.ticket_promedio_usd, { moneda: true })} />
                  <Cifra etiqueta="Ticket mayor" valor={cifra(r.ticket_mayor_usd, { moneda: true })} />
                  <Cifra etiqueta="Beneficiarios" valor={cifra(r.beneficiarios)} />
                  <Cifra etiqueta="Países destino" valor={cifra(r.paises_destino)} />
                  <Cifra etiqueta="Devueltas" valor={cifra(r.n_devueltas)}
                         titulo={`USD ${r.devuelto_usd || 0} devueltos`} />
                  <Cifra etiqueta="Retenidas" valor={cifra(r.n_retenidas)} />
                </div>
                {(r.primera || r.ultima) && (
                  <p style={{ marginTop: 'var(--e-4)', marginBottom: 0,
                              fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    Primera {fecha(r.primera)?.toLocaleDateString('es-CL') || '—'} ·
                    última {fecha(r.ultima)?.toLocaleDateString('es-CL') || '—'}
                    {r.ultima && <> ({hace(r.ultima)})</>}
                  </p>
                )}
              </div>
            </section>

            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">Gestión</h2>
              </header>
              <div className="wt-cuerpo-carta">
                <div className="wt-cifras">
                  <Cifra etiqueta="Casos" valor={cifra(t.casos)} />
                  <Cifra etiqueta="Correos" valor={cifra(t.correos)} />
                  <Cifra etiqueta="Documentos pedidos" valor={cifra(t.solicitados)} />
                  <Cifra etiqueta="Documentos recibidos" valor={cifra(t.documentos_recibidos)} />
                </div>
              </div>
            </section>

            {(ficha.productos || []).length > 0 && (
              <section className="wt-carta">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Productos</h2>
                </header>
                <div className="wt-tabla-marco">
                  <table className="wt-tabla">
                    <thead><tr><th>Producto</th><th>¿Usa?</th><th>Desde</th><th>Detalle</th></tr></thead>
                    <tbody>
                      {ficha.productos.map((p, i) => (
                        <tr key={i}>
                          <td>{p.producto}</td>
                          <td style={{ color: p.tiene ? 'var(--nivel-bajo-texto)' : 'var(--texto-mute)' }}>
                            {p.tiene ? 'sí' : 'no'}
                          </td>
                          <td>{p.desde || '—'}</td>
                          <td style={{ whiteSpace: 'normal' }}>{p.detalle || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {(ficha.por_pais || []).length > 0 && (
              <section className="wt-carta">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Por país destino</h2>
                </header>
                <div className="wt-tabla-marco">
                  <table className="wt-tabla">
                    <thead><tr><th>País</th><th className="wt-td-num">Trx</th><th className="wt-td-num">USD</th></tr></thead>
                    <tbody>
                      {ficha.por_pais.map((p, i) => (
                        <tr key={i}>
                          <td>{p.pais || '—'}</td>
                          <td className="wt-td-num">{cifra(p.n)}</td>
                          <td className="wt-td-num">{cifra(p.usd, { moneda: true })}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {(ficha.por_mes || []).length > 0 && (
              <section className="wt-carta">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Por mes</h2>
                </header>
                <div className="wt-tabla-marco">
                  <table className="wt-tabla">
                    <thead><tr><th>Mes</th><th className="wt-td-num">Trx</th><th className="wt-td-num">USD</th></tr></thead>
                    <tbody>
                      {ficha.por_mes.map((m, i) => (
                        <tr key={i}>
                          <td>{m.mes}</td>
                          <td className="wt-td-num">{cifra(m.n)}</td>
                          <td className="wt-td-num">{cifra(m.usd, { moneda: true })}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {(ficha.casos || []).length > 0 && (
              <section className="wt-carta">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Casos de este cliente</h2>
                </header>
                <div className="wt-tabla-marco">
                  <table className="wt-tabla">
                    <thead><tr><th>Caso</th><th>Estado</th><th>Abierto</th><th /></tr></thead>
                    <tbody>
                      {ficha.casos.map((c) => (
                        <tr key={c.case_id}>
                          <td style={{ whiteSpace: 'normal' }}>{c.title || c.case_id}</td>
                          <td style={{ color: ESTADOS_CASO[c.status]?.color || 'var(--texto-2)' }}>
                            {ESTADOS_CASO[c.status]?.etiqueta || c.status}
                          </td>
                          <td title={c.created_at}>{hace(c.created_at)}</td>
                          <td>
                            <button className="wt-btn" onClick={() => navegar('caso', [c.case_id])}>
                              Abrir
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        </>
      )}
    </>
  );
}
