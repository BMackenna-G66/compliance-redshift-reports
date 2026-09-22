/* ============================================================================
   Relevo · partners
   ----------------------------------------------------------------------------
   El circuito de pedirle documentación a un cliente porque un corresponsal la
   pidió.

   LO PRIMERO QUE SE VE ES SI LOS ENVÍOS ESTÁN PRENDIDOS, y eso no es un
   detalle de configuración: hoy los ocho interruptores de salida están
   apagados. Una bandeja con 230 casos «listos para pedir» que en realidad no
   puede pedir nada es una trampa — el analista trabaja, no pasa nada, y
   ningún error lo explica. Por eso el aviso va arriba de todo y en rojo.

   PRENDER UN ENVÍO MANDA CORREOS A CLIENTES REALES. Por eso ese interruptor
   —y sólo ese— pide confirmación escrita con lo que va a pasar.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Suspense, lazy } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import { estadoDocumento, ESTADOS_DOCUMENTO } from '../comun/expediente.js';
import {
  ESTADOS_MANUALES, FILTROS_RELEVO, aplicarFiltro, estadoDeEnvios, etapaDe,
  faltantesTexto, hace, indicadores, nombreEstado, porEtapa, porTipo,
} from '../comun/relevo.js';
import { soloLectura } from '../permisos.js';

/* Los paneles pesados se cargan cuando se abren: la mayoría de las visitas a
   esta pantalla son para mirar en qué estado está el circuito, no para
   mandarle un correo a alguien. */
const Envio = lazy(() => import('./relevo/Envio.jsx').then((m) => ({ default: m.Envio })));
const Operacion = lazy(() =>
  import('./relevo/Operacion.jsx').then((m) => ({ default: m.Operacion })));

/* ── El aviso de envíos ─────────────────────────────────────────────────── */

function AvisoEnvios({ estado, alVerInterruptores }) {
  if (estado.activo) {
    return (
      <p className="wt-nota">
        <strong>Los envíos están activos.</strong> Los pedidos que se disparen desde acá
        llegan a clientes reales.
        {estado.partnersEncendidos < estado.partnersTotal && (
          <> {estado.partnersTotal - estado.partnersEncendidos} partner
            {estado.partnersTotal - estado.partnersEncendidos === 1 ? '' : 's'} sigue
            {estado.partnersTotal - estado.partnersEncendidos === 1 ? '' : 'n'} apagado
            {estado.partnersTotal - estado.partnersEncendidos === 1 ? '' : 's'}.</>
        )}
        <button className="wt-btn" style={{ marginLeft: 8, padding: '2px 8px' }}
                onClick={alVerInterruptores}>Ver interruptores</button>
      </p>
    );
  }
  return (
    <p className="wt-nota wt-nota-alarma">
      <strong>Los envíos están apagados.</strong> Ningún pedido sale, ni a mano ni por
      lote. Se puede trabajar la bandeja y registrar estados, pero al cliente no le
      llega nada.
      <button className="wt-btn" style={{ marginLeft: 8, padding: '2px 8px' }}
              onClick={alVerInterruptores}>Ver interruptores</button>
    </p>
  );
}

/* ── El circuito ────────────────────────────────────────────────────────── */

function Circuito({ etapas, total }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Dónde están los casos</h2>
      </header>
      <div className="wt-cuerpo-carta">
        <div className="wt-circuito">
          {etapas.map((e) => (
            <div key={e.n} className="wt-paso" title={e.descripcion}>
              <span className="wt-paso-n" style={{ color: e.color }}>{e.n_casos}</span>
              <span className="wt-paso-etiqueta">{e.etiqueta}</span>
              <span className="wt-paso-barra"
                    style={{ background: e.color,
                             width: total ? `${(e.n_casos / total) * 100}%` : '0%' }} />
            </div>
          ))}
        </div>
        <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)',
                    color: 'var(--texto-mute)' }}>
          «Falta un dato» no es un caso atrasado: es uno que no se puede trabajar hasta
          arreglar el dato (cliente no ubicado, sin correo, o pedido que no se entendió).
        </p>
      </div>
    </section>
  );
}

/* ── Los interruptores ──────────────────────────────────────────────────── */

function Interruptores({ datos, lectura, alCambiar, guardando, alCerrar }) {
  const grupos = porTipo(datos?.interruptores || []);
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Interruptores</h2>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <div className="wt-cuerpo-carta">
        {grupos.map((g) => (
          <div key={g.tipo} style={{ marginBottom: 'var(--e-4)' }}>
            <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                         letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                         margin: '0 0 var(--e-2)' }}>
              {g.etiqueta}
            </h3>
            {g.items.map((i) => (
              <div key={i.clave} className="wt-interruptor">
                <span className="wt-insignia"
                      style={i.valor
                        ? { color: 'var(--nivel-bajo-texto)', background: 'var(--nivel-bajo-tenue)' }
                        : { color: 'var(--estado-error-texto)', background: 'var(--estado-error-fondo)' }}>
                  {i.valor ? 'ON' : 'OFF'}
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 'var(--texto-base)', fontWeight: 'var(--peso-medio)' }}>
                    {i.etiqueta || i.clave}
                  </div>
                  <div style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)',
                                whiteSpace: 'normal' }}>
                    {i.valor ? i.al_apagar : i.descripcion}
                  </div>
                </div>
                {!lectura && (
                  <button className="wt-btn" disabled={guardando === i.clave}
                          onClick={() => alCambiar(i)}>
                    {guardando === i.clave ? '…' : i.valor ? 'Apagar' : 'Prender'}
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── La tabla ───────────────────────────────────────────────────────────── */

function columnas(alAbrir) {
  return [
    {
      clave: 'partner',
      titulo: 'Partner',
      ancho: '11%',
    },
    {
      clave: 'cliente_id',
      titulo: 'Cliente',
      ancho: '14%',
      render: (c) => (c.cliente_id
        ? <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
            <span className="mono" style={{ color: 'var(--texto)' }}>{c.cliente_id}</span>
            {c.cliente_nombre && (
              <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                {c.cliente_nombre}
              </span>
            )}
          </span>
        : <span style={{ color: 'var(--nivel-critico-texto)' }}>sin ubicar</span>),
    },
    {
      clave: 'estado',
      titulo: 'Estado',
      ancho: '14%',
      render: (c) => {
        const e = etapaDe(c);
        return (
          <span style={{ color: e?.color || 'var(--texto-2)',
                         fontWeight: 'var(--peso-medio)' }}>
            {nombreEstado(c.estado)}
          </span>
        );
      },
      exportar: (c) => nombreEstado(c.estado),
    },
    {
      clave: '_faltantes',
      titulo: 'Qué falta',
      render: (c) => (c._faltantes
        ? <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 320,
                         fontSize: 'var(--texto-xs)' }}>
            {c._faltantes}
          </span>
        : <span style={{ color: 'var(--texto-mute)' }}>—</span>),
    },
    {
      clave: 'intentos',
      titulo: 'Intentos',
      tipo: 'numero',
      ancho: '8%',
      buscable: false,
      // La política es 3 intentos; al tercero el caso queda agotado.
      render: (c) => (c.agotado
        ? <span style={{ color: 'var(--estado-error-texto)', fontWeight: 'var(--peso-medio)' }}>
            {c.intentos} · agotado
          </span>
        : c.intentos),
    },
    {
      clave: 'proximo_contacto',
      titulo: 'Próximo contacto',
      ancho: '13%',
      buscable: false,
      render: (c) => (c.vencido
        ? <span style={{ color: 'var(--nivel-critico-texto)', fontWeight: 'var(--peso-medio)' }}>
            vencido
          </span>
        : c.proximo_contacto || <span style={{ color: 'var(--texto-mute)' }}>—</span>),
    },
    {
      clave: 'ultima',
      titulo: 'Último correo',
      ancho: '11%',
      buscable: false,
      render: (c) => <span title={c.ultima}>{hace(c.ultima)}</span>,
    },
    {
      clave: 'id',
      titulo: '',
      ancho: '7%',
      ordenable: false,
      buscable: false,
      render: (c) => (
        <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => alAbrir(c)}>Abrir</button>
      ),
      exportar: () => '',
    },
  ];
}

/* ── El detalle ─────────────────────────────────────────────────────────── */

function Detalle({
  caso, detalle, checklist, cargando, lectura, alFijarEstado, guardando, alCerrar,
  alEnviar, alDescargar,
}) {
  const [estado, setEstado] = useState('');
  const e = etapaDe(caso);
  /* El detalle trae más de lo que viene en la lista —notas, comunicaciones,
     el requerimiento del partner—; mientras no llegó se muestra lo que ya se
     tenía en vez de dejar la carta en blanco. */
  const c = { ...caso, ...(detalle || {}) };

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">
          {caso.cliente_nombre || `Cliente ${caso.cliente_id || '(sin ubicar)'}`}
        </h2>
        <span className="wt-insignia"
              style={{ color: e?.color || 'var(--texto-2)', background: 'var(--superficie-3)' }}>
          {nombreEstado(caso.estado)}
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <div className="wt-cuerpo-carta"
           style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 'var(--e-4)' }}>
        <div>
          <dl className="wt-datos">
            <dt>Caso</dt><dd className="mono" style={{ wordBreak: 'break-all' }}>{c.id}</dd>
            <dt>Partner</dt><dd>{c.partner}{c.caso_partner && ` · ${c.caso_partner}`}</dd>
            {c.cliente_correo && <><dt>Correo</dt><dd>{c.cliente_correo}</dd></>}
            <dt>Transacciones</dt><dd>{c.n_transacciones}</dd>
            <dt>Correos</dt><dd>{c.n_correos}</dd>
            <dt>Intentos</dt>
            <dd>
              {c.intentos}
              {c.agotado && (
                <span style={{ color: 'var(--estado-error-texto)' }}> · agotado</span>
              )}
            </dd>
            {c.plazo && <><dt>Plazo del partner</dt><dd>{c.plazo}</dd></>}
            <dt>Primer correo</dt><dd>{c.primera || '—'}</dd>
            <dt>Último correo</dt><dd>{c.ultima || '—'}</dd>
            {(c.faltantes || []).length > 0 && (
              <>
                <dt>Qué falta</dt>
                <dd>
                  <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
                    {c.faltantes.map((f) => (
                      <li key={f.item}>
                        {f.es || f.item}
                        <span className="mono" style={{ fontSize: 'var(--texto-xs)',
                                                        color: 'var(--texto-mute)' }}>
                          {' '}{f.item}
                        </span>
                      </li>
                    ))}
                  </ul>
                </dd>
              </>
            )}
          </dl>

          {/* El checklist de lo que el cliente mandó. Es lo que decide si la
              devolución sale completa o parcial, así que se muestra con el
              caso y no escondido detrás de otro clic. */}
          {cargando ? (
            <p className="wt-estado" style={{ marginTop: 'var(--e-3)' }}>Trayendo el detalle…</p>
          ) : (checklist || []).length > 0 && (
            <div style={{ marginTop: 'var(--e-4)' }}>
              <h3 className="wt-subtitulo">Documentación</h3>
              <div className="wt-checklist">
                {checklist.map((it, i) => {
                  const clave = estadoDocumento(it);
                  const est = ESTADOS_DOCUMENTO[clave];
                  return (
                    <div key={it.item || i} className="wt-checklist-item" style={{ cursor: 'default' }}>
                      <span>{it.es || it.item || it.categoria}</span>
                      <span className="wt-insignia" style={{ color: est.color, background: est.fondo }}>
                        {est.etiqueta}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {(c.comunicaciones || []).length > 0 && (
            <div style={{ marginTop: 'var(--e-4)' }}>
              <h3 className="wt-subtitulo">Comunicaciones · {c.comunicaciones.length}</h3>
              {c.comunicaciones.slice(0, 8).map((m, i) => (
                <div key={i} className="wt-correo">
                  <div className="wt-correo-meta">
                    <strong>{m.direccion === 'enviado' ? 'Enviado' : 'Recibido'}</strong>
                    {' · '}{m.para || m.de || '—'}
                    <span style={{ marginLeft: 'auto' }}>{String(m.cuando || '').slice(0, 16)}</span>
                  </div>
                  {m.asunto && <p className="wt-correo-asunto">{m.asunto}</p>}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="wt-acciones">
          {lectura ? (
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
              Tu perfil es de consulta: podés ver el caso, pero no cambiarle el estado.
            </p>
          ) : (
            <>
              <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Fijar el estado a mano
                <select className="wt-input" style={{ display: 'block', width: '100%', marginTop: 4 }}
                        value={estado} onChange={(ev) => setEstado(ev.target.value)}>
                  <option value="">Elegir…</option>
                  {ESTADOS_MANUALES.map((s) => (
                    <option key={s} value={s}>{nombreEstado(s)}</option>
                  ))}
                </select>
              </label>
              <button className="wt-btn wt-btn-primario"
                      disabled={!estado || guardando}
                      onClick={() => alFijarEstado(caso, estado)}>
                {guardando ? 'Guardando…' : 'Fijar el estado'}
              </button>
              {/* Los cuatro diagnósticos no están en la lista a propósito.
                  Decirlo evita que alguien los busque y crea que faltan. */}
              <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                «Sin cliente», «sin correo» y «sin requerimiento» no se pueden fijar a mano:
                no son etapas del trabajo sino datos que faltan, y ponerlos tapa el
                diagnóstico en vez de arreglarlo.
              </p>

              <hr className="wt-separador" />

              {/* Los cuatro correos. Ninguno manda nada al apretarlo: abren la
                  vista previa, que muestra a quién le llega y con qué texto. */}
              <button className="wt-btn" disabled={!c.cliente_correo}
                      onClick={() => alEnviar('pedido')}>
                Pedir la documentación
              </button>
              <button className="wt-btn" disabled={!c.cliente_correo}
                      onClick={() => alEnviar('recontacto')}>
                Recontactar
              </button>
              <button className="wt-btn" disabled={!c.cliente_correo}
                      onClick={() => alEnviar('mensaje')}>
                Mandarle un mensaje
              </button>
              <button className="wt-btn" onClick={() => alEnviar('devolucion')}>
                Devolución de fondos
              </button>
              <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                Ninguno envía al apretarlo: abren la vista previa con el correo completo.
              </p>

              <hr className="wt-separador" />

              <button className="wt-btn" onClick={alDescargar}>
                Bajar lo que mandó el cliente
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/* ── La pantalla ────────────────────────────────────────────────────────── */

export function Relevo({ api, perfil, email }) {
  const [casos, setCasos] = useState([]);
  const [interruptores, setInterruptores] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [filtro, setFiltro] = useState('accionables');
  const [abierto, setAbierto] = useState(null);
  const [verInterruptores, setVerInterruptores] = useState(false);
  const [guardando, setGuardando] = useState('');
  const [vista, setVista] = useState('casos');
  /* El detalle y el checklist se traen al abrir un caso y se recuerdan: son
     dos llamadas por caso, y volver a abrir el mismo no tiene por qué
     pagarlas de nuevo. */
  const [detalles, setDetalles] = useState({});
  const [trayendo, setTrayendo] = useState(false);
  const [envio, setEnvio] = useState(null);

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    const [c, i] = await Promise.allSettled([
      api.get('/relevo/casos'),
      api.get('/relevo/interruptores'),
    ]);
    if (c.status === 'fulfilled') setCasos(c.value?.casos || []);
    if (i.status === 'fulfilled') setInterruptores(i.value);
    const fallos = [['casos', c], ['interruptores', i]]
      .filter(([, x]) => x.status === 'rejected')
      .map(([n, x]) => `${n} (${x.reason?.message || 'error'})`);
    setError(fallos.length ? `No se pudo cargar: ${fallos.join(' · ')}` : '');
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  /**
   * Abre un caso: su detalle completo y su checklist de documentación.
   *
   * Son dos llamadas en paralelo y no encadenadas: ninguna depende de la
   * otra, y en serie se nota — el checklist tarda tanto como el detalle.
   */
  async function abrir(caso) {
    if (abierto?.id === caso.id) { setAbierto(null); return; }
    setAbierto(caso);
    setEnvio(null);
    if (detalles[caso.id]) return;
    setTrayendo(true);
    const [d, ck] = await Promise.allSettled([
      api.get(`/relevo/casos/${encodeURIComponent(caso.id)}`),
      api.get(`/relevo/casos/${encodeURIComponent(caso.id)}/checklist`),
    ]);
    setDetalles((m) => ({
      ...m,
      [caso.id]: {
        caso: d.status === 'fulfilled' ? (d.value?.caso || null) : null,
        checklist: ck.status === 'fulfilled'
          ? (ck.value?.checklist || ck.value?.items || []) : [],
      },
    }));
    setTrayendo(false);
  }

  /** Baja lo que el cliente mandó: el backend devuelve una URL prefirmada. */
  async function descargar(caso) {
    setError(''); setAviso('');
    try {
      const d = await api.get(`/relevo/casos/${encodeURIComponent(caso.id)}/descarga`);
      const url = d?.url || d?.download_url;
      if (!url) throw new Error('Este caso no tiene documentos para bajar.');
      globalThis.open(url, '_blank', 'noopener');
    } catch (e) {
      setError(e?.message || 'No se pudo preparar la descarga.');
    }
  }

  const preparados = useMemo(
    () => casos.map((c) => ({ ...c, _faltantes: faltantesTexto(c) })),
    [casos],
  );
  const ind = useMemo(() => indicadores(casos), [casos]);
  const etapas = useMemo(() => porEtapa(casos), [casos]);
  const envios = useMemo(() => estadoDeEnvios(interruptores), [interruptores]);
  const visibles = useMemo(() => aplicarFiltro(preparados, filtro), [preparados, filtro]);

  async function fijarEstado(caso, estado) {
    setGuardando('estado'); setError(''); setAviso('');
    try {
      await api.post(`/relevo/casos/${encodeURIComponent(caso.id)}/accion`, {
        accion: 'estado_manual', estado, quien: email,
      });
      setAviso(`Estado fijado en «${nombreEstado(estado)}».`);
      setAbierto(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo fijar el estado.');
    } finally {
      setGuardando('');
    }
  }

  async function cambiarInterruptor(i) {
    const prendiendo = !i.valor;
    // Prender un envío manda correos a clientes reales. Es la única acción de
    // esta pantalla que sale del sistema, así que es la única que pregunta.
    if (prendiendo && i.tipo === 'salida') {
      const ok = globalThis.confirm(
        `Prender «${i.etiqueta || i.clave}» hace que los pedidos LLEGUEN A CLIENTES REALES.\n\n` +
        '¿Seguro que el desarrollo ya está terminado?',
      );
      if (!ok) return;
    }
    setGuardando(i.clave); setError(''); setAviso('');
    try {
      await api.post('/relevo/interruptores', {
        clave: i.clave, valor: prendiendo, quien: email,
      });
      setAviso(`«${i.etiqueta || i.clave}» quedó ${prendiendo ? 'prendido' : 'apagado'}.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo cambiar el interruptor.');
    } finally {
      setGuardando('');
    }
  }

  const sinDatos = (cargando || Boolean(error)) && casos.length === 0;
  const n = (v) => (sinDatos ? '—' : v);
  const alternar = (c) => setFiltro((f) => (f === c ? 'todos' : c));

  return (
    <>
      {interruptores && (
        <AvisoEnvios estado={envios} alVerInterruptores={() => setVerInterruptores((v) => !v)} />
      )}

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {verInterruptores && interruptores && (
        <Interruptores datos={interruptores} lectura={lectura} guardando={guardando}
                       alCambiar={cambiarInterruptor}
                       alCerrar={() => setVerInterruptores(false)} />
      )}

      <div className="wt-kpis">
        <Kpi principal etiqueta="Casos" valor={n(ind.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer')
                           : `${ind.partners} partners`} />
        <Kpi etiqueta="Por pedir" valor={n(ind.porPedir)} pie="cliente ubicado, falta pedirle"
             alPulsar={sinDatos ? undefined : () => alternar('por_pedir')}
             activo={filtro === 'por_pedir'} />
        <Kpi etiqueta="Falta un dato" valor={n(ind.trabados)} pie="no se pueden trabajar"
             alPulsar={sinDatos ? undefined : () => alternar('trabados')}
             activo={filtro === 'trabados'} />
        <Kpi etiqueta="Vencidos" valor={n(ind.vencidos)} pie="toca recontactar"
             alPulsar={sinDatos ? undefined : () => alternar('vencidos')}
             activo={filtro === 'vencidos'} />
        <Kpi etiqueta="Agotados" valor={n(ind.agotados)} pie="3 intentos sin respuesta" />
      </div>

      {!sinDatos && <Circuito etapas={etapas} total={ind.total} />}

      <nav className="wt-pasos" aria-label="Vistas del relevo">
        {[['casos', 'Casos', 'el circuito'], ['operacion', 'Operación', 'lote, espejo y vencidos']]
          .map(([k, titulo, pie]) => (
            <button key={k} className={`wt-paso-boton${vista === k ? ' wt-paso-activo' : ''}`}
                    onClick={() => setVista(k)}>
              <span>
                <span className="wt-paso-titulo">{titulo}</span>
                <span className="wt-paso-pie">{pie}</span>
              </span>
            </button>
          ))}
      </nav>

      {vista === 'operacion' ? (
        <Suspense fallback={<p className="wt-estado">Cargando…</p>}>
          <Operacion api={api} email={email} lectura={lectura} casos={casos}
                     alRecargar={cargar}
                     alRecontactar={(v) => {
                       const c = casos.find((x) => x.id === (v.caso_id || v.id))
                                 || { id: v.caso_id || v.id, cliente_correo: v.cliente_correo };
                       setVista('casos'); setAbierto(c); setEnvio('recontacto');
                     }} />
        </Suspense>
      ) : (
        <>

      {abierto && (
        <Detalle caso={abierto} lectura={lectura} guardando={guardando === 'estado'}
                 detalle={detalles[abierto.id]?.caso}
                 checklist={detalles[abierto.id]?.checklist}
                 cargando={trayendo}
                 alFijarEstado={fijarEstado}
                 alEnviar={setEnvio}
                 alDescargar={() => descargar(abierto)}
                 alCerrar={() => { setAbierto(null); setEnvio(null); }} />
      )}

      {abierto && envio && (
        <Suspense fallback={<p className="wt-estado">Armando el correo…</p>}>
          <Envio api={api} caso={abierto} tipo={envio} email={email}
                 alCerrar={() => setEnvio(null)}
                 alTerminar={async (msg) => {
                   setEnvio(null); setAbierto(null); setAviso(msg);
                   setDetalles({});
                   await cargar();
                 }} />
        </Suspense>
      )}

      <Tabla
        titulo="Casos de relevo"
        columnas={columnas(abrir)}
        filas={visibles}
        cargando={cargando}
        error=""
        alReintentar={cargar}
        claveFila={(c) => c.id}
        nombreExport="relevo-watchtower"
        porPagina={40}
        vacioTexto={`Ningún caso con el filtro «${FILTROS_RELEVO[filtro]?.etiqueta || filtro}».`}
        herramientas={
          <>
            <div className="wt-filtros">
              {Object.entries(FILTROS_RELEVO).map(([clave, f]) => (
                <button key={clave} className="wt-filtro" aria-pressed={filtro === clave}
                        onClick={() => setFiltro(clave)}>
                  {f.etiqueta}
                  {!sinDatos && (
                    <span className="wt-filtro-n">{aplicarFiltro(preparados, clave).length}</span>
                  )}
                </button>
              ))}
            </div>
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </>
        }
      />
        </>
      )}
    </>
  );
}
