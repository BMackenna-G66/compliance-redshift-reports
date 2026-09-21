/* ============================================================================
   ROS / UAF
   ----------------------------------------------------------------------------
   El registro de Reportes de Operación Sospechosa: qué se decidió reportar,
   sobre quién, con qué evidencia y en qué estado está.

   ESTA PANTALLA NO REPORTA. El envío al regulador es manual, por sus
   canales. Acá se lleva el registro — y decirlo en la pantalla importa, o
   alguien va a marcar «enviado» creyendo que el sistema lo mandó.

   LO QUE ARMA EL SISTEMA Y LO QUE ESCRIBE UNA PERSONA. Los hechos —sujeto,
   alertas vinculadas, período, montos— los junta el backend del caso. La
   descripción de la sospecha la escribe el oficial de cumplimiento: un ROS
   es una afirmación legal firmada, y un texto generado que alguien firma sin
   leer es el accidente que hay que evitar.

   EL SERVICIO EXTERNO todavía no existe. Cuando exista, los reportes que
   vengan de allá se distinguen por `origen`, y el envío pasará por él. El
   modelo ya tiene el lugar; la pantalla no finge que está.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  alertasDe, colorDe, destinosDe, editable, faltaParaEnviar, fecha, hace,
  montosDe, nombreEstado, nombreRegulador, periodoTexto,
} from '../comun/ros.js';
import { soloLectura } from '../permisos.js';

function Estado({ r }) {
  const c = colorDe(r.estado);
  return (
    <span className="wt-insignia" style={{ color: c.color, background: c.fondo }}>
      {nombreEstado(r.estado)}
    </span>
  );
}

/* ── Crear uno nuevo ────────────────────────────────────────────────────── */

function Crear({ api, reguladores, email, alCrear, alCerrar }) {
  const [casos, setCasos] = useState([]);
  const [caseId, setCaseId] = useState('');
  const [regulador, setRegulador] = useState('');
  const [tipologia, setTipologia] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let vivo = true;
    api.get('/cases?status=all')
      .then((d) => { if (vivo) setCasos(d?.cases || []); })
      .catch((e) => setError(`No se pudieron cargar los casos (${e?.message || 'error'}).`));
    return () => { vivo = false; };
  }, [api]);

  async function enviar(e) {
    e.preventDefault();
    if (!caseId || !regulador) return;
    setGuardando(true); setError('');
    try {
      await alCrear({ case_id: caseId, regulador, tipologia: tipologia.trim(),
                      creado_por: email });
    } catch (err) {
      setError(err?.message || 'No se pudo crear el reporte.');
    } finally {
      setGuardando(false);
    }
  }

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Nuevo reporte</h2>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <form className="wt-cuerpo-carta" onSubmit={enviar}>
        {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-3)' }}>{error}</div>}
        <div style={{ display: 'flex', gap: 'var(--e-3)', flexWrap: 'wrap',
                      alignItems: 'flex-end' }}>
          <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)', flex: 1,
                          minWidth: 280 }}>
            Caso del que sale el reporte
            <select className="wt-input" style={{ display: 'block', width: '100%', marginTop: 4 }}
                    value={caseId} onChange={(e) => setCaseId(e.target.value)} required>
              <option value="">Elegir…</option>
              {casos.map((c) => (
                <option key={c.case_id} value={c.case_id}>
                  {c.entity_id}{c.entity_name ? ` · ${c.entity_name}` : ''}
                  {c.report_name ? ` · ${c.report_name}` : ''}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            A qué regulador
            <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 200 }}
                    value={regulador} onChange={(e) => setRegulador(e.target.value)} required>
              <option value="">Elegir…</option>
              {Object.entries(reguladores || {}).map(([k, d]) => (
                <option key={k} value={k}>{d.nombre} · {d.pais}</option>
              ))}
            </select>
          </label>
        </div>
        <label style={{ display: 'block', marginTop: 'var(--e-3)',
                        fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Tipología <span style={{ opacity: .7 }}>(opcional)</span>
          <input className="wt-input" style={{ display: 'block', width: '100%', marginTop: 4 }}
                 value={tipologia} onChange={(e) => setTipologia(e.target.value)}
                 placeholder="Estructuración, pitufeo, uso de terceros…" />
        </label>

        {/* Se dice ANTES de crear, no después: la evidencia la junta el
            backend y la narrativa la escribe una persona. */}
        <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)',
                    color: 'var(--texto-mute)' }}>
          El reporte nace en <strong>borrador</strong> con la evidencia del caso ya
          adjunta: el sujeto, las alertas vinculadas, el período y los montos. La
          descripción de la sospecha la escribís vos después.
        </p>
        <button className="wt-btn wt-btn-primario" type="submit"
                style={{ marginTop: 'var(--e-3)' }}
                disabled={guardando || !caseId || !regulador}>
          {guardando ? 'Creando…' : 'Crear el borrador'}
        </button>
      </form>
    </section>
  );
}

/* ── El detalle ─────────────────────────────────────────────────────────── */

function Detalle({ r, reguladores, transiciones, lectura, email,
                   alGuardar, alMover, guardando, alCerrar }) {
  const [narrativa, setNarrativa] = useState(r.narrativa || '');
  const [tipologia, setTipologia] = useState(r.tipologia || '');
  const [nota, setNota] = useState('');
  const puedeEditar = editable(r) && !lectura;
  const falta = faltaParaEnviar({ ...r, narrativa });
  const destinos = destinosDe(r, transiciones);

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo mono">{r.folio}</h2>
        <Estado r={r} />
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          {nombreRegulador(r.regulador, reguladores)}
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>

      <div className="wt-cuerpo-carta"
           style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 'var(--e-4)' }}>
        <div>
          <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                       letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                       margin: '0 0 var(--e-2)' }}>
            Lo que armó el sistema
          </h3>
          <dl className="wt-datos">
            <dt>Sujeto</dt>
            <dd>
              <span className="mono">{r.evidencia?.sujeto?.entity_id || '—'}</span>
              {r.evidencia?.sujeto?.entity_name && ` · ${r.evidencia.sujeto.entity_name}`}
            </dd>
            <dt>Caso</dt>
            <dd className="mono">{r.case_id}</dd>
            <dt>Período</dt>
            <dd>{periodoTexto(r)}</dd>
            <dt>Alertas</dt>
            <dd>
              {alertasDe(r).length === 0
                ? <span style={{ color: 'var(--texto-mute)' }}>ninguna vinculada</span>
                : (
                  <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
                    {alertasDe(r).map((a) => (
                      <li key={a.alert_id}>
                        {a.motivo || a.report_name}
                        <span className="mono" style={{ fontSize: 'var(--texto-xs)',
                                                        color: 'var(--texto-mute)' }}>
                          {' '}{a.alert_id}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
            </dd>
            <dt>Montos</dt>
            <dd>
              {montosDe(r).length === 0
                ? <span style={{ color: 'var(--texto-mute)' }}>sin montos en las alertas</span>
                : (
                  <>
                    <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
                      {montosDe(r).map((m, i) => (
                        <li key={i}>
                          USD {m.valor}
                          <span className="mono" style={{ fontSize: 'var(--texto-xs)',
                                                          color: 'var(--texto-mute)' }}>
                            {' '}{m.campo}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {/* La razón por la que no hay un total. */}
                    <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                      No se suman: cada reporte mide una cosa distinta y el total no
                      significaría nada.
                    </span>
                  </>
                )}
            </dd>
          </dl>

          <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                       letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                       margin: 'var(--e-5) 0 var(--e-2)' }}>
            Lo que escribís vos
          </h3>
          {puedeEditar ? (
            <>
              <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Tipología
                <input className="wt-input" style={{ display: 'block', width: '100%', marginTop: 4 }}
                       value={tipologia} onChange={(e) => setTipologia(e.target.value)} />
              </label>
              <label style={{ display: 'block', marginTop: 'var(--e-3)',
                              fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Descripción de la sospecha
                <textarea className="wt-input"
                          style={{ display: 'block', width: '100%', marginTop: 4,
                                   minHeight: 160, resize: 'vertical' }}
                          value={narrativa} onChange={(e) => setNarrativa(e.target.value)}
                          placeholder="Por qué esto es sospechoso: qué hizo el cliente, qué no cuadra con su perfil, qué se verificó." />
              </label>
              <button className="wt-btn" style={{ marginTop: 'var(--e-2)' }}
                      disabled={guardando === 'texto'}
                      onClick={() => alGuardar(r, { narrativa, tipologia })}>
                {guardando === 'texto' ? 'Guardando…' : 'Guardar'}
              </button>
            </>
          ) : (
            <dl className="wt-datos">
              <dt>Tipología</dt>
              <dd>{r.tipologia || <span style={{ color: 'var(--texto-mute)' }}>—</span>}</dd>
              <dt>Sospecha</dt>
              <dd style={{ whiteSpace: 'pre-wrap' }}>
                {r.narrativa || <span style={{ color: 'var(--texto-mute)' }}>sin describir</span>}
              </dd>
            </dl>
          )}
        </div>

        <div className="wt-acciones">
          <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                       letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                       margin: 0 }}>
            Mover el reporte
          </h3>

          {lectura ? (
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
              Tu perfil es de consulta: podés ver el reporte, pero no moverlo.
            </p>
          ) : destinos.length === 0 ? (
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
              Este reporte ya se envió. Para corregirlo se emite otro, que es como
              funciona con los reguladores.
            </p>
          ) : (
            <>
              <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Nota <span style={{ opacity: .7 }}>(queda en el historial)</span>
                <textarea className="wt-input"
                          style={{ display: 'block', width: '100%', marginTop: 4,
                                   minHeight: 60, resize: 'vertical' }}
                          value={nota} onChange={(e) => setNota(e.target.value)} />
              </label>
              {destinos.map((d) => {
                const bloquea = d === 'enviado' && falta.length > 0;
                return (
                  <button key={d}
                          className={'wt-btn' + (d === 'enviado' ? ' wt-btn-primario' : '')}
                          disabled={Boolean(guardando) || bloquea}
                          title={bloquea ? `Falta ${falta.join(', ')}` : ''}
                          onClick={() => alMover(r, d, nota)}>
                    {guardando === d ? '…' : `Pasar a ${nombreEstado(d)}`}
                  </button>
                );
              })}
              {falta.length > 0 && destinos.includes('enviado') && (
                <p style={{ margin: 0, fontSize: 'var(--texto-xs)',
                            color: 'var(--nivel-alto-texto)' }}>
                  Para enviarlo falta {falta.join(', ')}.
                </p>
              )}
            </>
          )}

          <hr style={{ border: 0, borderTop: '1px solid var(--borde)', margin: 'var(--e-2) 0' }} />

          <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                       letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                       margin: 0 }}>
            Historial
          </h3>
          {(r.historial || []).map((h, i) => (
            <div key={i} style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-2)' }}>
              <strong>{nombreEstado(h.estado)}</strong> · {h.quien || 'sin autor'}
              <span style={{ color: 'var(--texto-mute)' }}> · {hace(h.cuando)}</span>
              {h.nota && <div style={{ color: 'var(--texto-mute)' }}>{h.nota}</div>}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── La pantalla ────────────────────────────────────────────────────────── */

export function Ros({ api, perfil, email, navegar }) {
  const [datos, setDatos] = useState(null);
  const [abierto, setAbierto] = useState(null);
  const [creando, setCreando] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async (folioAAbrir) => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/ros');
      setDatos(d);
      if (d?.warning) setError(`La API respondió con un aviso: ${d.warning}`);
      if (folioAAbrir) {
        const detalle = await api.get(`/ros/${encodeURIComponent(folioAAbrir)}`);
        setAbierto(detalle?.ros || null);
      }
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el registro de ROS.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  async function abrir(folio) {
    setError('');
    try {
      const d = await api.get(`/ros/${encodeURIComponent(folio)}`);
      setAbierto(d?.ros || null);
    } catch (e) {
      setError(e?.message || 'No se pudo abrir el reporte.');
    }
  }

  async function crear(cuerpo) {
    const d = await api.post('/ros', cuerpo);
    setCreando(false);
    setAviso(`Reporte ${d?.ros?.folio} creado en borrador.`);
    await cargar(d?.ros?.folio);
  }

  async function guardarTexto(r, cambios) {
    setGuardando('texto'); setError(''); setAviso('');
    try {
      await api.post(`/ros/${encodeURIComponent(r.folio)}/narrativa`, cambios);
      setAviso('Guardado.');
      await cargar(r.folio);
    } catch (e) {
      setError(e?.message || 'No se pudo guardar.');
    } finally {
      setGuardando('');
    }
  }

  async function mover(r, estado, nota) {
    // Enviar es la única que no tiene vuelta atrás: el reporte sale del
    // registro como reportado y no se puede deshacer.
    if (estado === 'enviado' && !globalThis.confirm(
      `Marcar ${r.folio} como enviado al regulador.\n\n`
      + 'Esto NO lo manda: el envío es manual, por los canales del regulador. '
      + 'Y no tiene vuelta atrás — para corregirlo hay que emitir otro reporte.\n\n'
      + '¿Ya lo enviaste?')) return;

    setGuardando(estado); setError(''); setAviso('');
    try {
      await api.post(`/ros/${encodeURIComponent(r.folio)}/estado`,
                     { estado, quien: email, nota });
      setAviso(`${r.folio} pasó a ${nombreEstado(estado)}.`);
      await cargar(r.folio);
    } catch (e) {
      setError(e?.message || 'No se pudo mover el reporte.');
    } finally {
      setGuardando('');
    }
  }

  const reportes = datos?.ros || [];
  const ind = datos?.indicadores || {};
  const reguladores = datos?.reguladores || {};

  const columnas = useMemo(() => [
    { clave: 'folio', titulo: 'Folio', tipo: 'mono', ancho: '13%' },
    {
      clave: '_sujeto',
      titulo: 'Sujeto',
      ancho: '22%',
      render: (r) => (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
          <span className="mono" style={{ color: 'var(--texto)' }}>
            {r.evidencia?.sujeto?.entity_id || '—'}
          </span>
          {r.evidencia?.sujeto?.entity_name && (
            <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
              {r.evidencia.sujeto.entity_name}
            </span>
          )}
        </span>
      ),
    },
    {
      clave: 'regulador',
      titulo: 'Regulador',
      ancho: '15%',
      render: (r) => nombreRegulador(r.regulador, reguladores),
    },
    { clave: 'estado', titulo: 'Estado', ancho: '13%', render: (r) => <Estado r={r} /> },
    {
      clave: '_alertas',
      titulo: 'Alertas',
      tipo: 'numero',
      ancho: '8%',
      buscable: false,
      render: (r) => r.evidencia?.n_alertas ?? 0,
    },
    { clave: 'creado_por', titulo: 'Creado por', ancho: '14%',
      render: (r) => (r.creado_por || '').replace('@global66.com', '') || '—' },
    {
      clave: 'creado_at',
      titulo: 'Cuándo',
      ancho: '10%',
      buscable: false,
      render: (r) => <span title={fecha(r.creado_at)?.toLocaleString('es-CL')}>{hace(r.creado_at)}</span>,
    },
    {
      clave: 'case_id',
      titulo: '',
      ancho: '7%',
      ordenable: false,
      buscable: false,
      render: (r) => (
        <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => abrir(r.folio)}>Abrir</button>
      ),
      exportar: () => '',
    },
  ], [reguladores]);

  const preparados = useMemo(() => reportes.map((r) => ({
    ...r,
    _sujeto: r.evidencia?.sujeto?.entity_id || '',
    _alertas: r.evidencia?.n_alertas ?? 0,
  })), [reportes]);

  const sinDatos = (cargando || Boolean(error)) && reportes.length === 0;
  const n = (v) => (sinDatos ? '—' : (v ?? 0));

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Reportes" valor={n(ind.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer') : 'en el registro'} />
        <Kpi etiqueta="En curso" valor={n(ind.en_curso)} pie="borrador o en revisión" />
        <Kpi etiqueta="Enviados" valor={n(ind.por_estado?.enviado)} pie="reportados al regulador" />
        <Kpi etiqueta="Descartados" valor={n(ind.por_estado?.descartado)}
             pie="se evaluó y no se reporta" />
      </div>

      {/* Que la pantalla no reporta hay que decirlo, o alguien va a marcar
          «enviado» creyendo que el sistema lo mandó. */}
      <p className="wt-nota">
        <strong>Este módulo lleva el registro, no envía.</strong> El reporte al regulador
        se hace por sus canales, fuera del sistema; acá queda qué se decidió reportar,
        con qué evidencia, quién lo movió y cuándo.
      </p>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {creando && (
        <Crear api={api} reguladores={reguladores} email={email}
               alCrear={crear} alCerrar={() => setCreando(false)} />
      )}

      {abierto && (
        <Detalle r={abierto} reguladores={reguladores} transiciones={datos?.transiciones}
                 lectura={lectura} email={email} guardando={guardando}
                 alGuardar={guardarTexto} alMover={mover}
                 alCerrar={() => setAbierto(null)} />
      )}

      <Tabla
        titulo="Registro de ROS"
        columnas={columnas}
        filas={preparados}
        cargando={cargando}
        error=""
        alReintentar={() => cargar()}
        claveFila={(r) => r.folio}
        nombreExport="ros-watchtower"
        vacioTexto="Todavía no se registró ningún reporte."
        herramientas={
          <>
            {!lectura && (
              <button className="wt-btn wt-btn-primario" onClick={() => setCreando(true)}>
                Nuevo reporte
              </button>
            )}
            <button className="wt-btn" onClick={() => cargar()} disabled={cargando}>
              Refrescar
            </button>
          </>
        }
      />
    </>
  );
}
