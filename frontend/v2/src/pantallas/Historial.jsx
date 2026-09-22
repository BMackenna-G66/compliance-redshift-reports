/* ============================================================================
   Historial de corridas
   ----------------------------------------------------------------------------
   Todo lo que se ejecutó: reportes, análisis individuales, refrescos
   institucionales. Cada corrida deja un Excel en S3 y un enlace de descarga.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  MAX_TOKENS_IA, TEMPERATURA_IA, avisoDeRecorte, columnasDe, promptDelResultado,
} from '../comun/corridas.js';
import {
  ESTADOS_CORRIDA, duracion, duracionTexto, enCurso, fecha, hace, parametros,
} from '../comun/analisis.js';
import { nombreLegible } from '../comun/alertas.js';

function EstadoCorrida({ corrida }) {
  const d = ESTADOS_CORRIDA[String(corrida.status || '').toUpperCase()];
  if (!d) {
    // Un estado que el front no conoce se muestra crudo: mejor un valor raro
    // que una celda vacía que parece un bug.
    return <span className="wt-insignia wt-insignia-sindato">{corrida.status || '—'}</span>;
  }
  return (
    <span className="wt-insignia" style={{ color: d.color, background: d.fondo }}>
      {d.etiqueta}
    </span>
  );
}

function columnas(alVerParams, alDescargar, bajando) {
  return [
    {
      clave: '_reporte',
      titulo: 'Qué se corrió',
      ancho: '26%',
      render: (r) => (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
          <span style={{ color: 'var(--texto)' }}>{r._reporte}</span>
          <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            {r.report_name}
          </span>
        </span>
      ),
    },
    { clave: 'status', titulo: 'Estado', ancho: '12%', render: (r) => <EstadoCorrida corrida={r} /> },
    {
      clave: 'row_count',
      titulo: 'Filas',
      tipo: 'numero',
      ancho: '9%',
      buscable: false,
      render: (r) => (r.row_count === null || r.row_count === undefined
        ? '—'
        : Number(r.row_count).toLocaleString('es-CL')),
    },
    {
      clave: '_duracion',
      titulo: 'Tardó',
      tipo: 'numero',
      ancho: '9%',
      buscable: false,
      render: (r) => duracionTexto(r._duracion),
    },
    {
      clave: '_quien',
      titulo: 'Quién',
      ancho: '15%',
      render: (r) => r._quien || <span style={{ color: 'var(--texto-mute)' }}>—</span>,
    },
    {
      clave: 'started_at',
      titulo: 'Cuándo',
      ancho: '11%',
      buscable: false,
      render: (r) => (
        <span title={fecha(r.started_at)?.toLocaleString('es-CL') || r.started_at}>
          {hace(r.started_at)}
        </span>
      ),
    },
    {
      clave: '_nParams',
      titulo: 'Parámetros',
      ancho: '10%',
      ordenable: false,
      buscable: false,
      render: (r) => (r._nParams === 0
        ? <span style={{ color: 'var(--texto-mute)' }}>ninguno</span>
        : <button className="wt-btn" style={{ padding: '2px 8px' }}
                  onClick={() => alVerParams(r)}>
            ver {r._nParams}
          </button>),
      exportar: () => '',
    },
    {
      clave: 'run_id',
      titulo: '',
      ancho: '8%',
      ordenable: false,
      buscable: false,
      // La descarga necesita un viaje a la API: el enlace prefirmado sólo
      // viene en el detalle de la corrida, no en el listado.
      render: (r) => (r.status === 'DONE'
        ? <button className="wt-btn" style={{ padding: '2px 8px' }}
                  disabled={bajando === r.run_id}
                  onClick={() => alDescargar(r.run_id)}>
            {bajando === r.run_id ? '…' : 'Descargar'}
          </button>
        : <span style={{ color: 'var(--texto-mute)', fontSize: 'var(--texto-xs)' }}>—</span>),
      exportar: () => '',
    },
  ];
}

export function Historial({ api, perfil }) {
  const [corridas, setCorridas] = useState([]);
  const [catalogo, setCatalogo] = useState({});
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [detalle, setDetalle] = useState(null);
  const [bajando, setBajando] = useState('');
  /* El resultado de la corrida abierta. `GET /runs/{id}` guarda sólo diez
     filas de muestra; `/rows` trae el resultado completo, que es lo que
     permite paginarlo y buscarlo entero. */
  const [filas, setFilas] = useState([]);
  const [recorte, setRecorte] = useState('');
  const [trayendo, setTrayendo] = useState(false);
  const [ia, setIa] = useState({ texto: '', cargando: false });

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const d = await api.get('/runs');
      setCorridas(d?.runs || []);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el historial.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  /**
   * Abre una corrida: sus parámetros y su resultado.
   *
   * La muestra se pinta enseguida y el completo se pide aparte, así la tabla
   * aparece en el acto aunque el resultado pese.
   */
  async function abrir(corrida) {
    if (detalle?.run_id === corrida.run_id) { cerrar(); return; }
    setDetalle(corrida); setFilas([]); setRecorte(''); setIa({ texto: '', cargando: false });
    setTrayendo(true); setError('');
    try {
      const d = await api.get(`/runs/${corrida.run_id}`);
      setDetalle({ ...corrida, ...(d || {}) });
      setFilas(d?.result_preview || []);
      try {
        const todo = await api.get(`/runs/${corrida.run_id}/rows`);
        if (todo?.rows?.length) { setFilas(todo.rows); setRecorte(avisoDeRecorte(todo)); }
      } catch { /* se queda con la muestra */ }
    } catch (e) {
      setError(e?.message || 'No se pudo abrir la corrida.');
    } finally {
      setTrayendo(false);
    }
  }

  function cerrar() {
    setDetalle(null); setFilas([]); setRecorte(''); setIa({ texto: '', cargando: false });
  }

  async function analizar() {
    setIa({ texto: '', cargando: true }); setError('');
    try {
      const d = await api.post('/ai/generate', {
        prompt: promptDelResultado({
          reporte: detalle?._reporte || detalle?.report_name,
          descripcion: detalle?.description || '',
          columnas: columnasDe(filas),
          filas,
          total: detalle?.row_count,
          resumenBackend: detalle?.ai_summary || null,
        }),
        temperature: TEMPERATURA_IA,
        max_tokens: MAX_TOKENS_IA,
      });
      setIa({ texto: d?.text || 'Sin respuesta de la IA.', cargando: false });
    } catch (e) {
      setIa({ texto: '', cargando: false });
      setError(e?.message || 'No se pudo analizar el resultado.');
    }
  }

  useEffect(() => {
    let vivo = true;
    api.get('/reports').then((d) => {
      if (!vivo) return;
      const m = {};
      for (const r of d?.reports || []) m[r.report_name] = r.display_name || r.report_name;
      setCatalogo(m);
    }).catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  const preparadas = useMemo(() => corridas.map((r) => ({
    ...r,
    _reporte: catalogo[r.report_name] || nombreLegible(r.report_name),
    _duracion: duracion(r),
    _quien: (r.user_email || '').replace('@global66.com', ''),
    _nParams: parametros(r).length,
  })), [corridas, catalogo]);

  const ind = useMemo(() => {
    const total = corridas.length;
    const enMarcha = corridas.filter((r) => enCurso(r.status)).length;
    const fallidas = corridas.filter((r) => ['ERROR', 'FAILED'].includes(r.status)).length;
    const filas = corridas.reduce((a, r) => a + (Number(r.row_count) || 0), 0);
    return { total, enMarcha, fallidas, filas };
  }, [corridas]);

  async function descargar(runId) {
    setBajando(runId);
    setError('');
    try {
      const d = await api.get(`/runs/${runId}`);
      if (!d?.download_url) throw new Error('Esa corrida no dejó un archivo para descargar.');
      globalThis.open(d.download_url, '_blank', 'noopener');
    } catch (e) {
      setError(e?.message || 'No se pudo preparar la descarga.');
    } finally {
      setBajando('');
    }
  }

  const sinDatos = (cargando || Boolean(error)) && corridas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Corridas" valor={n(ind.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer') : 'las últimas 50'} />
        <Kpi etiqueta="En marcha" valor={n(ind.enMarcha)} pie="todavía corriendo" />
        <Kpi etiqueta="Fallidas" valor={n(ind.fallidas)} pie="terminaron con error" />
        <Kpi etiqueta="Filas generadas" valor={sinDatos ? '—' : ind.filas.toLocaleString('es-CL')}
             pie="sumando todas" />
      </div>

      {detalle && (
        <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Parámetros de la corrida</h2>
            <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
              {detalle.run_id}
            </span>
            <button className="wt-btn" style={{ marginLeft: 'auto' }}
                    onClick={cerrar}>Cerrar</button>
          </header>
          <div className="wt-cuerpo-carta">
            <dl className="wt-datos">
              {parametros(detalle).map((p) => (
                <div key={p.clave} style={{ display: 'contents' }}>
                  <dt>{p.clave}</dt>
                  <dd className="mono" style={{ wordBreak: 'break-word' }}>{p.valor}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>
      )}

      {detalle && (
        <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Análisis con IA</h2>
            <div className="wt-carta-herramientas">
              <button className="wt-btn" disabled={ia.cargando || filas.length === 0}
                      onClick={analizar}>
                {ia.cargando ? 'Analizando…' : 'Analizar el resultado'}
              </button>
            </div>
          </header>
          <div className="wt-cuerpo-carta">
            {ia.texto ? <div className="wt-ia">{ia.texto}</div> : (
              <p className="wt-vacio">
                Lee las filas de esta corrida y dice qué patrones aparecen. No guarda
                nada: la conclusión la escribe quien investiga.
              </p>
            )}
          </div>
        </section>
      )}

      {detalle && (trayendo || filas.length > 0) && (
        <>
          {recorte && <p className="wt-nota">{recorte}</p>}
          <Tabla
            titulo={trayendo ? 'Trayendo el resultado…'
                    : `Resultado · ${filas.length.toLocaleString('es-CL')} filas`}
            columnas={columnasDe(filas).map((c) => ({
              clave: c, titulo: c.replace(/_/g, ' '),
              tipo: typeof filas[0]?.[c] === 'number' ? 'numero' : undefined,
            }))}
            filas={filas}
            cargando={trayendo}
            claveFila={(_, i) => i}
            porPagina={50}
            nombreExport={`resultado-${detalle.report_name || detalle.run_id}`}
          />
          <div style={{ height: 'var(--e-4)' }} />
        </>
      )}

      <Tabla
        titulo="Historial de corridas"
        columnas={columnas(abrir, descargar, bajando)}
        filas={preparadas}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(r) => r.run_id}
        nombreExport="corridas-watchtower"
        porPagina={30}
        vacioTexto="Todavía no se corrió nada."
        herramientas={
          <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
        }
      />
    </>
  );
}
