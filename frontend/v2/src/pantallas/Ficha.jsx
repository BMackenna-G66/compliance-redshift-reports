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

import { Campos } from '../comun/Campos.jsx';
import { Correos } from '../comun/Correos.jsx';
import { fecha, hace } from '../comun/alertas.js';
import { SIN_TRANSACCIONAL, campos, contextoDeCliente } from '../comun/expediente.js';
import { ESTADOS_CASO } from '../dominio.js';

/* Los tonos que manda el backend, y sólo esos: `alertas_del_resumen()` en
   `ficha_cliente.py` emite `alto` y `medio`, nada más.

   Acá decía `alerta` / `aviso` / `ok`, que son nombres que el backend nunca
   usó: los dos tonos caían en el respaldo y TODOS los avisos se pintaban
   igual. Un cliente con plata devuelta se veía como uno con una nota
   cualquiera. `test_sincronia.py` compara las dos listas para que no vuelva
   a pasar en silencio. */
const TONOS = {
  alto:  { color: 'var(--nivel-critico-texto)', fondo: 'var(--nivel-critico-tenue)' },
  medio: { color: 'var(--nivel-alto-texto)',    fondo: 'var(--nivel-alto-tenue)' },
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
  /* El perfil KYC empieza cerrado: son treinta y pico de campos y desplazan
     todo lo demás de la pantalla. Quien lo necesita, lo abre. */
  const [perfilAbierto, setPerfilAbierto] = useState(false);
  /* El contexto de compliance va aparte de la ficha: sale de otro endpoint,
     es rápido, y sirve aunque la ficha grande falle. */
  const [contexto, setContexto] = useState(null);

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

  useEffect(() => {
    if (!entityId) return undefined;
    let vivo = true;
    setContexto(null);
    api.get(`/customer/context?customer_id=${encodeURIComponent(entityId)}&days=90`)
      .then((d) => { if (vivo && d && !d.error) setContexto(contextoDeCliente(d)); })
      .catch(() => {});
    return () => { vivo = false; };
  }, [api, entityId]);

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
  const docs = {
    solicitados: ficha?.documentos?.solicitados || [],
    recibidos: ficha?.documentos?.recibidos || [],
  };
  const correos = ficha?.correos || [];
  const camposPerfil = campos(ficha?.perfil).length;

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
            // Un tono nuevo se pinta como el más grave a propósito: es peor
            // esconder una advertencia que mostrarla más fuerte de la cuenta.
            const tono = TONOS[a.tono] || TONOS.alto;
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

          {/* Las dos banderas del CRM suben el riesgo más que el volumen:
              «recurrente» quiere decir que el cliente volvió a aparecer, y
              «combina tipologías» que aparece por motivos distintos. */}
          {contexto && (contexto.recurrente || contexto.combinaTipologias) && (
            <p className="wt-nota wt-nota-alarma">
              <strong>
                {contexto.recurrente && 'Cliente recurrente'}
                {contexto.recurrente && contexto.combinaTipologias && ' · '}
                {contexto.combinaTipologias && 'Combina tipologías'}
              </strong>
              {' '}— {contexto.alertas} alerta(s) en {contexto.reportes} reporte(s)
              distinto(s) y {contexto.casos} caso(s).
            </p>
          )}
          {contexto && !contexto.transaccionalDisponible && (
            <p className="wt-nota">{SIN_TRANSACCIONAL}</p>
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

            {/* ── DOCUMENTACIÓN ────────────────────────────────────────────
                Pedida y recibida, una al lado de la otra y SIN cruzarlas: el
                nombre del archivo que manda el cliente no se parece al ítem
                del catálogo que se le pidió, y emparejarlos a ojo inventaría
                una correspondencia que nadie verificó. Ese juicio lo hace el
                analista mirando las dos columnas. */}
            {((docs.solicitados.length + docs.recibidos.length) > 0) && (
              <section className="wt-carta">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Documentación</h2>
                </header>
                <div className="wt-cuerpo-carta wt-dos-columnas">
                  <div>
                    <h3 className="wt-subtitulo">Pedida ({docs.solicitados.length})</h3>
                    {docs.solicitados.length === 0 ? (
                      <p className="wt-vacio">Nada pedido todavía.</p>
                    ) : docs.solicitados.map((d, i) => (
                      <div key={`ds${i}`} className="wt-documento">
                        <span style={{ flex: 1 }}>{d.documento}</span>
                        {/* Un pedido que no salió explica por qué el cliente
                            no mandó nada. Sin esta marca se lee como que no
                            contestó. */}
                        {d.salio === false && (
                          <span style={{ color: 'var(--nivel-critico-texto)',
                                         fontSize: 'var(--texto-xs)' }}>
                            no salió
                          </span>
                        )}
                        <span className="wt-documento-fecha">{String(d.cuando || '').slice(0, 10)}</span>
                      </div>
                    ))}
                  </div>
                  <div>
                    <h3 className="wt-subtitulo">Recibida ({docs.recibidos.length})</h3>
                    {docs.recibidos.length === 0 ? (
                      <p className="wt-vacio">Nada recibido todavía.</p>
                    ) : docs.recibidos.map((d, i) => (
                      <div key={`dr${i}`} className="wt-documento">
                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
                                       whiteSpace: 'nowrap' }} title={d.filename}>
                          {d.filename}
                        </span>
                        <span style={{ fontSize: 'var(--texto-xs)',
                                       color: d.origen === 'email_reply'
                                         ? 'var(--g66-azul-texto)' : 'var(--texto-mute)' }}>
                          {d.origen === 'email_reply' ? 'del cliente' : 'subido'}
                        </span>
                        <span className="wt-documento-fecha">{String(d.cuando || '').slice(0, 10)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {/* ── HISTORIAL DE CORREOS, de todos sus casos juntos ──────────
                Acá cada correo dice de qué caso salió: en una ficha que junta
                varios, sin eso no se sabe a cuál pertenece. */}
            <section className="wt-carta wt-carta-ancha">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">Historial de correos</h2>
                {correos.length > 0 && (
                  <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    {t.enviados || 0} enviado(s) · {t.recibidos || 0} recibido(s)
                  </span>
                )}
              </header>
              <div className="wt-cuerpo-carta">
                {correos.length === 0 ? (
                  <p className="wt-vacio">Sin correos registrados.</p>
                ) : (
                  <Correos correos={correos} mostrarCaso
                           alAbrirCaso={(id) => id && navegar('caso', [id])} />
                )}
              </div>
            </section>

            {/* ── PERFIL KYC ─────────────────────────────────────────────── */}
            {camposPerfil > 0 && (
              <section className="wt-carta wt-carta-ancha">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Perfil KYC / compliance</h2>
                  {ficha.perfil_origen && (
                    <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                      {ficha.perfil_origen}
                    </span>
                  )}
                  <div className="wt-carta-herramientas">
                    <button className="wt-btn" onClick={() => setPerfilAbierto((v) => !v)}>
                      {perfilAbierto ? 'Ocultar' : `Ver los ${camposPerfil} campos`}
                    </button>
                  </div>
                </header>
                {perfilAbierto && (
                  <div className="wt-cuerpo-carta">
                    <Campos datos={ficha.perfil} />
                  </div>
                )}
              </section>
            )}
          </div>
        </>
      )}
    </>
  );
}
