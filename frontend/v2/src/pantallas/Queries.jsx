/* ============================================================================
   Queries personalizadas
   ----------------------------------------------------------------------------
   Los reportes a medida: los que alguien escribió con su propio SQL, frente
   a los 31 del catálogo del sistema.

   Se leen del MISMO endpoint que el catálogo (`/reports`, filtrando
   `is_custom`) y no de uno aparte: son la misma cosa con una bandera, y
   pedirlos por separado abriría la puerta a que las dos listas discrepen.

   EL SQL SE VALIDA ANTES DE MANDARLO. No por desconfianza del backend —que
   también lo valida— sino porque su error llega como «Error 400» sin decir
   cuál de los cuatro campos está mal, y porque una consulta que ESCRIBE es un
   incidente de compliance, no un error de sintaxis: este módulo lee Redshift
   y nada más.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import { faltaParaGuardarConsulta, pareceEscritura } from '../comun/corridas.js';
import { soloLectura } from '../permisos.js';

const COLUMNAS = [
  {
    clave: 'display_name',
    titulo: 'Query',
    ancho: '28%',
    render: (r) => r.display_name || r.report_name,
  },
  {
    clave: 'description',
    titulo: 'Qué hace',
    render: (r) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 520 }}>
        {r.description || <span style={{ color: 'var(--texto-mute)' }}>sin descripción</span>}
      </span>
    ),
  },
  {
    clave: 'n_params',
    titulo: 'Parámetros',
    tipo: 'numero',
    ancho: '10%',
    buscable: false,
    render: (r) => r.params?.length ?? 0,
  },
  { clave: 'report_name', titulo: 'Clave', tipo: 'mono', ancho: '18%' },
];

const VACIA = { report_name: '', display_name: '', description: '', sql: '' };

/* El formulario de una consulta nueva. */
function Formulario({ valores, alCambiar, alGuardar, alCancelar, guardando, falta, escribe }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Nueva query</h2>
      </header>
      <div className="wt-cuerpo-carta">
        <div className="wt-parametros">
          <label className="wt-parametro">
            <span>Nombre de código</span>
            <input className="wt-input" value={valores.report_name} placeholder="clientes_peru"
                   onChange={(e) => alCambiar('report_name', e.target.value)} />
          </label>
          <label className="wt-parametro">
            <span>Nombre visible</span>
            <input className="wt-input" value={valores.display_name} placeholder="Clientes de Perú"
                   onChange={(e) => alCambiar('display_name', e.target.value)} />
          </label>
        </div>
        <label className="wt-parametro" style={{ marginTop: 'var(--e-3)' }}>
          <span>Qué hace</span>
          <input className="wt-input" value={valores.description}
                 placeholder="Para qué sirve, en una línea"
                 onChange={(e) => alCambiar('description', e.target.value)} />
        </label>
        <label className="wt-parametro" style={{ marginTop: 'var(--e-3)' }}>
          <span>SQL</span>
          <textarea className="wt-input mono"
                    style={{ minHeight: 160, resize: 'vertical', width: '100%' }}
                    value={valores.sql} placeholder="select ..."
                    onChange={(e) => alCambiar('sql', e.target.value)} />
        </label>

        {/* Se dice al escribir y no al apretar: el error del backend no
            distingue cuál de los campos está mal. */}
        {falta.length > 0 && (
          <p className="wt-nota">Falta {falta.join(', ')}.</p>
        )}
        {escribe && (
          <p className="wt-nota"
             style={{ borderColor: 'var(--nivel-critico-texto)',
                      background: 'var(--nivel-critico-tenue)',
                      color: 'var(--nivel-critico-texto)' }}>
            Ese SQL parece modificar datos. Las queries de WatchTower sólo leen
            Redshift: revisá la consulta antes de guardarla.
          </p>
        )}

        <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
          <button className="wt-btn wt-btn-primario"
                  disabled={guardando || falta.length > 0 || escribe} onClick={alGuardar}>
            {guardando ? 'Guardando…' : 'Guardar la query'}
          </button>
          <button className="wt-btn" onClick={alCancelar}>Cancelar</button>
        </div>
      </div>
    </section>
  );
}

export function Queries({ api, perfil, navegar }) {
  const [reportes, setReportes] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [nueva, setNueva] = useState(null);
  const [guardando, setGuardando] = useState(false);

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/reports');
      setReportes(d?.reports || []);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el catálogo.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  async function guardar() {
    setGuardando(true); setError(''); setAviso('');
    try {
      const d = await api.post('/queries', nueva);
      if (!d?.report_name) throw new Error(d?.error || 'No se pudo guardar la query.');
      setAviso(`Query «${d.report_name}» guardada.`);
      setNueva(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo guardar la query.');
    } finally {
      setGuardando(false);
    }
  }

  async function borrar(r) {
    const nombre = r.display_name || r.report_name;
    if (!globalThis.confirm(`¿Eliminar la query «${nombre}»?\n\nDeja de estar en el catálogo. `
                          + 'Las corridas que ya se hicieron con ella no se tocan.')) return;
    setError(''); setAviso('');
    try {
      await api.del(`/queries/${encodeURIComponent(r.report_name)}`);
      setAviso(`Query «${nombre}» eliminada.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo eliminar la query.');
    }
  }

  const columnas = useMemo(() => [...COLUMNAS, {
    clave: 'acciones', titulo: '', ancho: '9%', buscable: false, ordenable: false,
    exportar: () => '',
    render: (r) => (
      <div style={{ display: 'flex', gap: 4 }}>
        <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => navegar('reports')}>Correr</button>
        {!lectura && (
          <button className="wt-btn" style={{ padding: '2px 8px' }}
                  onClick={() => borrar(r)}>Borrar</button>
        )}
      </div>
    ),
  }], [lectura]);   // eslint-disable-line react-hooks/exhaustive-deps

  const propias = useMemo(
    () => reportes.filter((r) => r.is_custom)
      .map((r) => ({ ...r, n_params: r.params?.length ?? 0 })),
    [reportes],
  );
  const sinDatos = (cargando || Boolean(error)) && reportes.length === 0;

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Queries a medida" valor={sinDatos ? '—' : propias.length}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer')
                           : `de ${reportes.length} reportes en total`} />
        <Kpi etiqueta="Del sistema" valor={sinDatos ? '—' : reportes.length - propias.length}
             pie="vienen en el catálogo" />
      </div>

      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {nueva && (
        <Formulario
          valores={nueva} guardando={guardando}
          falta={faltaParaGuardarConsulta(nueva)}
          escribe={pareceEscritura(nueva.sql)}
          alCambiar={(k, v) => setNueva((x) => ({ ...x, [k]: v }))}
          alGuardar={guardar}
          alCancelar={() => setNueva(null)}
        />
      )}

      {!sinDatos && propias.length === 0 && (
        <p className="wt-nota">
          No hay queries a medida. Las que se creen aparecen acá y también en el
          catálogo de reportes.
        </p>
      )}

      <Tabla
        titulo="Queries personalizadas"
        columnas={columnas}
        filas={propias}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(r) => r.report_name}
        nombreExport="queries-watchtower"
        vacioTexto="No hay queries a medida."
        herramientas={
          <>
            {!lectura && !nueva && (
              <button className="wt-btn wt-btn-primario" onClick={() => setNueva({ ...VACIA })}>
                Nueva query
              </button>
            )}
            <button className="wt-btn" onClick={() => navegar('reports')}>
              Ver todo el catálogo
            </button>
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </>
        }
      />
    </>
  );
}
