/* ============================================================================
   Catálogo de reportes, y correrlos
   ----------------------------------------------------------------------------
   Un reporte se corre en dos tiempos: `POST /execute` devuelve un `run_id` y
   se va; hay que preguntarle a `GET /runs/{id}` hasta que termine. La Lambda
   no puede quedarse esperando una consulta de Redshift de varios minutos.

   LA MÁQUINA DEL SONDEO NO ESTÁ ACÁ sino en `comun/corridas.js`, para poder
   probarla: sus dos fallas son silenciosas —uno que no se apaga le pega a la
   API para siempre, uno que se apaga de más deja la corrida colgada— y
   ninguna tira un error.

   EL RESULTADO SE MUESTRA ACÁ MISMO. En v1 la corrida terminaba y había que
   ir a buscarla al tablero; acá la tabla aparece debajo, con el Excel al
   lado. Las diez filas de muestra se pintan enseguida y el resultado completo
   se pide aparte con `/rows`, que es lo que permite paginarlo entero.
   ========================================================================= */

import { useCallback, useEffect, useRef, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import {
  avisoDeRecorte, columnasDe, cuerpoDeEjecucion, estadoDe, parametrosPorDefecto,
  seguirCorrida,
} from '../comun/corridas.js';
import { COLOR_CATEGORIA, COLOR_CATEGORIA_POR_DEFECTO } from '../dominio.js';
import { soloLectura } from '../permisos.js';

function Categoria({ reporte }) {
  const color = COLOR_CATEGORIA[reporte.category] || COLOR_CATEGORIA_POR_DEFECTO;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span
        aria-hidden="true"
        style={{
          width: 8, height: 8, borderRadius: '50%',
          background: color, flex: 'none',
        }}
      />
      {/* La etiqueta legible la manda el backend; si faltara, mejor la clave
          cruda que una celda vacía que parece un bug. */}
      {reporte.category_label || reporte.category || '—'}
    </span>
  );
}

function columnas({ lectura, alCorrer }) {
  return [
    {
      clave: 'display_name',
      titulo: 'Reporte',
      ancho: '24%',
      render: (r) => r.display_name || r.report_name,
    },
    {
      clave: 'category_label',
      titulo: 'Categoría',
      ancho: '15%',
      render: (r) => <Categoria reporte={r} />,
    },
    {
      clave: 'description',
      titulo: 'Qué hace',
      // Lo único que se deja romper en varias líneas: es prosa, y truncarla
      // dejaría la columna inútil.
      render: (r) => (
        <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 480 }}>
          {r.description || '—'}
        </span>
      ),
    },
    {
      clave: 'n_params',
      titulo: 'Parámetros',
      tipo: 'numero',
      ancho: '8%',
      buscable: false,
      render: (r) => (r.params?.length ?? 0),
    },
    {
      clave: 'origen',
      titulo: 'Origen',
      ancho: '8%',
      render: (r) => (r.is_custom ? 'A medida' : 'Del sistema'),
      exportar: (r) => (r.is_custom ? 'A medida' : 'Del sistema'),
    },
    { clave: 'report_name', titulo: 'Clave', tipo: 'mono', ancho: '15%' },
    {
      clave: 'correr',
      titulo: '',
      ancho: '7%',
      buscable: false,
      ordenable: false,
      exportar: () => '',
      render: (r) => (
        <button className="wt-btn" disabled={lectura} onClick={() => alCorrer(r)}
                title={lectura ? 'Tu perfil es de consulta' : 'Correr este reporte'}>
          Correr
        </button>
      ),
    },
  ];
}

/* El formulario de parámetros. Aparece sobre la tabla y no en una ventana
   aparte: son uno o dos campos, y una ventana modal para eso obliga a un
   clic de cierre que no aporta nada. */
function Parametros({ reporte, valores, alCambiar, alCorrer, alCancelar, corriendo }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{reporte.display_name || reporte.report_name}</h2>
        <div className="wt-carta-herramientas">
          <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            {reporte.report_name}
          </span>
        </div>
      </header>
      <div className="wt-cuerpo-carta">
        {reporte.description && (
          <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
            {reporte.description}
          </p>
        )}
        <div className="wt-parametros">
          {(reporte.params || []).length === 0 ? (
            <p className="wt-vacio">Este reporte no lleva parámetros.</p>
          ) : reporte.params.map((p) => (
            <label key={p.name} className="wt-parametro">
              <span>{p.label || p.name}</span>
              {p.type === 'bool' ? (
                <input type="checkbox" checked={!!valores[p.name]}
                       onChange={(e) => alCambiar(p.name, e.target.checked)} />
              ) : (
                <input className="wt-input" type={p.type === 'date' ? 'date' : 'text'}
                       value={valores[p.name] ?? ''}
                       onChange={(e) => alCambiar(p.name, e.target.value)} />
              )}
            </label>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
          <button className="wt-btn wt-btn-primario" disabled={corriendo} onClick={alCorrer}>
            {corriendo ? 'Ejecutando…' : 'Ejecutar'}
          </button>
          <button className="wt-btn" onClick={alCancelar}>Cancelar</button>
        </div>
      </div>
    </section>
  );
}

export function Reportes({ api, perfil }) {
  const [reportes, setReportes] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  const [elegido, setElegido] = useState(null);
  const [valores, setValores] = useState({});
  const [corrida, setCorrida] = useState(null);
  const [corriendo, setCorriendo] = useState(false);
  const [filas, setFilas] = useState([]);
  const [recorte, setRecorte] = useState('');

  const lectura = soloLectura(perfil);
  /* El sondeo consulta esto antes de cada vuelta. Sin él, salir de la
     pantalla deja el ciclo pegándole a la API contra un componente muerto. */
  const vivo = useRef(true);
  useEffect(() => () => { vivo.current = false; }, []);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const d = await api.get('/reports');
      // `n_params` se precalcula porque la tabla ordena por el valor de la
      // clave, y no puede ordenar por algo que sólo existe en el `render`.
      setReportes((d?.reports || []).map((r) => ({ ...r, n_params: r.params?.length ?? 0 })));
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el catálogo.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  function elegir(reporte) {
    setElegido(reporte);
    setValores(parametrosPorDefecto(reporte));
    setCorrida(null);
    setFilas([]);
    setRecorte('');
    setError('');
  }

  async function correr() {
    setCorriendo(true);
    setError('');
    setFilas([]);
    setRecorte('');
    try {
      const d = await api.post('/execute', cuerpoDeEjecucion(elegido, valores));
      if (!d?.run_id) throw new Error(d?.error || 'No se pudo iniciar la ejecución.');
      setCorrida({ run_id: d.run_id, status: d.status || 'RUNNING' });

      const fin = await seguirCorrida((ruta) => api.get(ruta), d.run_id, {
        alAvanzar: (x) => { if (vivo.current && x) setCorrida(x); },
        cancelado: () => !vivo.current,
      });
      if (!vivo.current) return;
      setCorrida(fin);
      if (fin.status !== 'DONE') {
        setError(fin.error_message || 'La corrida terminó con error.');
        return;
      }
      // La muestra se pinta ya; el resultado completo se pide aparte porque
      // el registro de la corrida guarda sólo diez filas.
      setFilas(fin.result_preview || []);
      try {
        const todo = await api.get(`/runs/${d.run_id}/rows`);
        if (vivo.current && todo?.rows?.length) {
          setFilas(todo.rows);
          setRecorte(avisoDeRecorte(todo));
        }
      } catch { /* se queda con la muestra */ }
    } catch (e) {
      setError(e?.message || 'No se pudo ejecutar el reporte.');
    } finally {
      if (vivo.current) setCorriendo(false);
    }
  }

  const cols = columnasDe(filas).map((c) => ({
    clave: c, titulo: c.replace(/_/g, ' '),
    tipo: typeof filas[0]?.[c] === 'number' ? 'numero' : undefined,
  }));

  return (
    <>
      {elegido && (
        <Parametros
          reporte={elegido} valores={valores} corriendo={corriendo}
          alCambiar={(k, v) => setValores((x) => ({ ...x, [k]: v }))}
          alCorrer={correr}
          alCancelar={() => { setElegido(null); setCorrida(null); setFilas([]); }}
        />
      )}

      {corrida && (
        <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">La corrida</h2>
            <div className="wt-carta-herramientas">
              <span className="wt-insignia"
                    style={{ color: estadoDe(corrida).color, background: estadoDe(corrida).fondo }}>
                {estadoDe(corrida).etiqueta}
              </span>
              {corrida.download_url && (
                <a className="wt-btn" href={corrida.download_url}
                   target="_blank" rel="noopener noreferrer">Descargar Excel</a>
              )}
            </div>
          </header>
          <div className="wt-cuerpo-carta">
            <dl className="wt-datos">
              <dt>Identificador</dt><dd className="mono">{corrida.run_id}</dd>
              {corrida.row_count !== undefined && (
                <><dt>Filas</dt><dd>{Number(corrida.row_count).toLocaleString('es-CL')}</dd></>
              )}
              {corrida.error_message && (
                <><dt>Error</dt><dd style={{ color: 'var(--nivel-critico-texto)' }}>
                  {corrida.error_message}
                </dd></>
              )}
            </dl>
            {recorte && <p className="wt-nota">{recorte}</p>}
          </div>
        </section>
      )}

      {filas.length > 0 ? (
        <Tabla
          titulo={`Resultado · ${filas.length.toLocaleString('es-CL')} filas`}
          columnas={cols}
          filas={filas}
          claveFila={(_, i) => i}
          porPagina={50}
          nombreExport={`resultado-${elegido?.report_name || 'reporte'}`}
        />
      ) : (
        <Tabla
          titulo={`Reportes AML${reportes.length ? ` · ${reportes.length}` : ''}`}
          columnas={columnas({ lectura, alCorrer: elegir })}
          filas={reportes}
          cargando={cargando}
          error={error}
          alReintentar={cargar}
          nombreExport="reportes-watchtower"
          claveFila={(r) => r.report_name}
          porPagina={40}
          herramientas={
            <button className="wt-btn" onClick={cargar} disabled={cargando}>
              Refrescar
            </button>
          }
        />
      )}

      {filas.length > 0 && (
        <p style={{ marginTop: 'var(--e-3)' }}>
          <button className="wt-btn" onClick={() => { setFilas([]); setElegido(null); setCorrida(null); }}>
            Volver al catálogo
          </button>
        </p>
      )}
    </>
  );
}
