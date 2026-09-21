/* ============================================================================
   Embargos
   ----------------------------------------------------------------------------
   Llega un oficio de un juzgado con una lista de personas y hay que decir
   cuáles son clientes.

   EL ARCHIVO SUBE DIRECTO A S3, no pasa por la API: un oficio escaneado pesa
   varios MB y API Gateway corta el cuerpo en ~6 MB. El backend da una URL
   prefirmada, el navegador sube ahí, y recién entonces se avisa.

   LA PREVISUALIZACIÓN NO ES UN ADORNO. Un oficio mal leído —columnas
   corridas, un PDF sin capa de texto— produce una respuesta al juzgado con
   los documentos equivocados. Ver qué se entendió antes de ejecutar es el
   único control que hay entre el archivo y la respuesta.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  FORMATOS, descargasDe, duracion, enCurso, etapaDe, fecha, formatoAceptado,
  hace, hayDescartados, indicadores, progresoDe, resumenDe,
} from '../comun/embargos.js';
import { duracionTexto } from '../comun/analisis.js';
import { soloLectura } from '../permisos.js';

const CADA_MS = 4000;

function Etapa({ corrida }) {
  const e = etapaDe(corrida);
  if (!e) {
    return <span className="wt-insignia wt-insignia-sindato">{corrida.estado || '—'}</span>;
  }
  return (
    <span className="wt-insignia"
          style={{ color: e.color, background: 'var(--superficie-3)' }}>
      {e.etiqueta}
    </span>
  );
}

/* ── La carga de un oficio ──────────────────────────────────────────────── */

function Cargar({ api, email, alTerminar }) {
  const [archivo, setArchivo] = useState(null);
  const [ciudad, setCiudad] = useState('');
  const [paso, setPaso] = useState('');
  const [error, setError] = useState('');
  const [previa, setPrevia] = useState(null);
  const entrada = useRef(null);

  function elegir(f) {
    setError(''); setPrevia(null);
    if (!f) return setArchivo(null);
    if (!formatoAceptado(f.name)) {
      setError(`Formato no soportado. Se aceptan ${FORMATOS.join(', ')}.`);
      return setArchivo(null);
    }
    setArchivo(f);
  }

  async function subirYPrevisualizar(e) {
    e.preventDefault();
    if (!archivo) return;
    setError(''); setPrevia(null);
    try {
      setPaso('pidiendo');
      const url = await api.post('/embargos/subir-url', { archivo_nombre: archivo.name });
      if (!url?.url) throw new Error('El backend no devolvió una URL para subir.');

      setPaso('subiendo');
      // Va directo a S3 con `fetch` y no por la capa de API: es un PUT a otro
      // origen, sin `actor_email` ni las cabeceras de la API.
      const r = await fetch(url.url, {
        method: 'PUT',
        body: archivo,
        headers: url.content_type ? { 'Content-Type': url.content_type } : undefined,
      });
      if (!r.ok) throw new Error(`S3 rechazó la subida (${r.status}).`);

      setPaso('leyendo');
      const p = await api.post('/embargos/previsualizar', {
        run_id: url.run_id,
        archivo_nombre: archivo.name,
        archivo_clave: url.clave || url.archivo_clave,
        ciudad: ciudad.trim(),
      });
      setPrevia({ ...p, run_id: url.run_id });
    } catch (err) {
      setError(err?.message || 'No se pudo preparar el oficio.');
    } finally {
      setPaso('');
    }
  }

  async function ejecutar() {
    setError(''); setPaso('ejecutando');
    try {
      await api.post('/embargos/ejecutar', {
        run_id: previa.run_id, ciudad: ciudad.trim(), solicitado_por: email,
      });
      setArchivo(null); setPrevia(null); setCiudad('');
      if (entrada.current) entrada.current.value = '';
      alTerminar(previa.run_id);
    } catch (err) {
      setError(err?.message || 'No se pudo ejecutar.');
    } finally {
      setPaso('');
    }
  }

  const r = previa ? resumenDe(previa) : null;

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Cargar un oficio</h2>
        <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          {FORMATOS.join(' · ')}
        </span>
      </header>
      <form className="wt-cuerpo-carta" onSubmit={subirYPrevisualizar}>
        <div style={{ display: 'flex', gap: 'var(--e-3)', alignItems: 'flex-end',
                      flexWrap: 'wrap' }}>
          <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            Archivo del juzgado
            <input ref={entrada} type="file" className="wt-input"
                   style={{ display: 'block', marginTop: 4 }}
                   accept={FORMATOS.join(',')}
                   onChange={(e) => elegir(e.target.files?.[0] || null)} />
          </label>
          <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            Ciudad
            <input className="wt-input" style={{ display: 'block', marginTop: 4, width: 180 }}
                   value={ciudad} onChange={(e) => setCiudad(e.target.value)}
                   placeholder="Bogotá D.C." />
          </label>
          <button className="wt-btn wt-btn-primario" type="submit"
                  disabled={!archivo || Boolean(paso)}>
            {paso === 'pidiendo' ? 'Preparando…'
              : paso === 'subiendo' ? 'Subiendo…'
              : paso === 'leyendo' ? 'Leyendo el oficio…'
              : 'Subir y previsualizar'}
          </button>
        </div>

        {error && (
          <div className="wt-estado-error" style={{ marginTop: 'var(--e-3)' }}>{error}</div>
        )}

        {previa && (
          <div className="wt-nota" style={{ marginTop: 'var(--e-4)', marginBottom: 0 }}>
            <strong>Esto es lo que se entendió del archivo.</strong> Revisalo antes de
            ejecutar: un oficio mal leído produce una respuesta al juzgado con los
            documentos equivocados.
            <div className="wt-cifras" style={{ marginTop: 'var(--e-3)' }}>
              <div className="wt-cifra">
                <span className="wt-cifra-etiqueta">Personas leídas</span>
                <span className="wt-cifra-valor">{r.personas ?? '—'}</span>
              </div>
              {r.descartados !== null && (
                <div className="wt-cifra">
                  <span className="wt-cifra-etiqueta">Filas descartadas</span>
                  <span className="wt-cifra-valor"
                        style={{ color: r.descartados ? 'var(--nivel-alto-texto)' : undefined }}>
                    {r.descartados}
                  </span>
                </div>
              )}
            </div>
            {/* Un descartado no es un "no cliente": es una fila que no se pudo
                leer. Si son muchos, conviene revisar el archivo antes. */}
            {hayDescartados(previa) && (
              <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)' }}>
                {r.descartados === 1 ? 'Hay una fila que no se pudo leer.' :
                  `Hay ${r.descartados} filas que no se pudieron leer.`}{' '}
                No son «no clientes»: son personas a las que no se va a buscar. Si son
                muchas, revisá el archivo.
              </p>
            )}
            <button className="wt-btn wt-btn-primario" type="button"
                    style={{ marginTop: 'var(--e-3)' }}
                    disabled={paso === 'ejecutando'} onClick={ejecutar}>
              {paso === 'ejecutando' ? 'Ejecutando…' : 'Ejecutar la validación'}
            </button>
          </div>
        )}
      </form>
    </section>
  );
}

/* ── El detalle de una corrida ──────────────────────────────────────────── */

function Detalle({ corrida, alCerrar }) {
  const r = resumenDe(corrida);
  const p = progresoDe(corrida);
  const descargas = descargasDe(corrida);

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{corrida.archivo_nombre || corrida.archivo}</h2>
        <Etapa corrida={corrida} />
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <div className="wt-cuerpo-carta">
        {enCurso(corrida) && p !== null && (
          <div style={{ marginBottom: 'var(--e-4)' }}>
            <div style={{ height: 8, background: 'var(--superficie-3)',
                          borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${p}%`, background: 'var(--g66-azul)',
                            borderRadius: 'var(--r-pill)' }} />
            </div>
            <p style={{ margin: '6px 0 0', fontSize: 'var(--texto-sm)',
                        color: 'var(--texto-mute)' }}>
              {p}% · se actualiza sola
            </p>
          </div>
        )}

        <div className="wt-cifras">
          <div className="wt-cifra">
            <span className="wt-cifra-etiqueta">Personas en el oficio</span>
            <span className="wt-cifra-valor">{r.personas ?? '—'}</span>
          </div>
          <div className="wt-cifra">
            <span className="wt-cifra-etiqueta">Son clientes</span>
            <span className="wt-cifra-valor" style={{ color: 'var(--nivel-critico-texto)' }}>
              {r.clientes ?? '—'}
              {r.porcentaje !== null && (
                <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)',
                               fontWeight: 'var(--peso-normal)' }}>
                  {' '}({r.porcentaje.toFixed(0)}%)
                </span>
              )}
            </span>
          </div>
          <div className="wt-cifra">
            <span className="wt-cifra-etiqueta">No son clientes</span>
            <span className="wt-cifra-valor">{r.noClientes ?? '—'}</span>
          </div>
          <div className="wt-cifra">
            <span className="wt-cifra-etiqueta">Descartadas</span>
            <span className="wt-cifra-valor"
                  style={{ color: r.descartados ? 'var(--nivel-alto-texto)' : undefined }}>
              {r.descartados ?? '—'}
            </span>
          </div>
        </div>

        {hayDescartados(corrida) && (
          <p className="wt-nota" style={{ marginTop: 'var(--e-4)' }}>
            {r.descartados === 1
              ? <>La fila descartada <strong>no es un «no cliente»</strong>: es una fila que
                  no se pudo leer, así que a esa persona nunca se la buscó.</>
              : <>Las {r.descartados} filas descartadas <strong>no son «no clientes»</strong>:
                  son filas que no se pudieron leer, así que a esas personas nunca se las
                  buscó.</>}
          </p>
        )}

        {corrida.error && (
          <div className="wt-estado-error" style={{ marginTop: 'var(--e-4)' }}>
            {corrida.error}
          </div>
        )}

        <dl className="wt-datos" style={{ marginTop: 'var(--e-4)' }}>
          <dt>Corrida</dt><dd className="mono">{corrida.run_id}</dd>
          {corrida.ciudad && <><dt>Ciudad</dt><dd>{corrida.ciudad}</dd></>}
          <dt>Pedida por</dt><dd>{corrida.solicitado_por || '—'}</dd>
          <dt>Cuándo</dt>
          <dd title={corrida.creado_at}>
            {hace(corrida.creado_at)}
            {duracion(corrida) !== null && ` · tardó ${duracionTexto(duracion(corrida))}`}
          </dd>
        </dl>

        {descargas.length > 0 && (
          <div style={{ marginTop: 'var(--e-4)', display: 'flex', gap: 'var(--e-2)',
                        flexWrap: 'wrap' }}>
            {descargas.map((d) => (
              <a key={d.url} className="wt-btn" href={d.url}
                 target="_blank" rel="noopener noreferrer">
                {d.etiqueta}
              </a>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/* ── La pantalla ────────────────────────────────────────────────────────── */

const COLUMNAS = (alAbrir) => [
  {
    clave: 'archivo',
    titulo: 'Oficio',
    ancho: '30%',
    render: (c) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 320 }}>
        {c.archivo || c.run_id}
      </span>
    ),
  },
  { clave: 'estado', titulo: 'Estado', ancho: '11%', render: (c) => <Etapa corrida={c} /> },
  { clave: 'personas', titulo: 'Personas', tipo: 'numero', ancho: '9%', buscable: false },
  {
    clave: 'clientes',
    titulo: 'Clientes',
    tipo: 'numero',
    ancho: '9%',
    buscable: false,
    render: (c) => (
      <strong style={{ color: Number(c.clientes) ? 'var(--nivel-critico-texto)' : 'var(--texto-2)' }}>
        {c.clientes ?? '—'}
      </strong>
    ),
  },
  {
    clave: 'descartados',
    titulo: 'Descartadas',
    tipo: 'numero',
    ancho: '10%',
    buscable: false,
    render: (c) => (Number(c.descartados)
      ? <span style={{ color: 'var(--nivel-alto-texto)' }}>{c.descartados}</span>
      : (c.descartados ?? '—')),
  },
  { clave: 'solicitado_por', titulo: 'Pedida por', ancho: '16%',
    render: (c) => (c.solicitado_por || '').replace('@global66.com', '') || '—' },
  {
    clave: 'creado_at',
    titulo: 'Cuándo',
    ancho: '10%',
    buscable: false,
    render: (c) => <span title={fecha(c.creado_at)?.toLocaleString('es-CL')}>{hace(c.creado_at)}</span>,
  },
  {
    clave: 'run_id',
    titulo: '',
    ancho: '7%',
    ordenable: false,
    buscable: false,
    render: (c) => (
      <button className="wt-btn" style={{ padding: '2px 8px' }}
              onClick={() => alAbrir(c.run_id)}>Abrir</button>
    ),
    exportar: () => '',
  },
];

export function Embargos({ api, perfil, email }) {
  const [corridas, setCorridas] = useState([]);
  const [detalle, setDetalle] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const temporizador = useRef(null);

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/embargos');
      setCorridas(d?.corridas || []);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el historial de embargos.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => () => clearInterval(temporizador.current), []);

  const abrir = useCallback(async (runId) => {
    clearInterval(temporizador.current);
    setError('');
    const traer = async () => {
      try {
        const d = await api.get(`/embargos/${encodeURIComponent(runId)}`);
        setDetalle(d);
        // Mientras la corrida se mueve se vuelve a preguntar sola: una
        // validación tarda segundos y obligar a refrescar a mano haría
        // pensar que se colgó.
        if (!enCurso(d)) {
          clearInterval(temporizador.current);
          temporizador.current = null;
          cargar();
        }
      } catch (e) {
        setError(e?.message || 'No se pudo leer la corrida.');
        clearInterval(temporizador.current);
      }
    };
    await traer();
    temporizador.current = setInterval(traer, CADA_MS);
  }, [api, cargar]);

  const ind = useMemo(() => indicadores(corridas), [corridas]);
  const sinDatos = (cargando || Boolean(error)) && corridas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Oficios procesados" valor={n(ind.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer') : 'en total'} />
        <Kpi etiqueta="En curso" valor={n(ind.enCurso)} pie="todavía corriendo" />
        <Kpi etiqueta="Fallidas" valor={n(ind.fallidas)} pie="terminaron con error" />
        <Kpi etiqueta="Personas revisadas" valor={sinDatos ? '—' : ind.personas.toLocaleString('es-CL')}
             pie="en las corridas listas" />
        <Kpi etiqueta="Resultaron clientes" valor={n(ind.clientes)} pie="de esas personas" />
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {lectura ? (
        <p className="wt-nota">
          Tu perfil es de consulta: podés ver las corridas, pero no cargar oficios.
        </p>
      ) : (
        <Cargar api={api} email={email} alTerminar={abrir} />
      )}

      {detalle && <Detalle corrida={detalle} alCerrar={() => {
        clearInterval(temporizador.current);
        setDetalle(null);
      }} />}

      <Tabla
        titulo="Oficios procesados"
        columnas={COLUMNAS(abrir)}
        filas={corridas}
        cargando={cargando}
        error=""
        alReintentar={cargar}
        claveFila={(c) => c.run_id}
        nombreExport="embargos-watchtower"
        vacioTexto="Todavía no se procesó ningún oficio."
        herramientas={
          <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
        }
      />
    </>
  );
}
