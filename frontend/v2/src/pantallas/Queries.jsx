/* ============================================================================
   Queries personalizadas
   ----------------------------------------------------------------------------
   Los reportes a medida: los que alguien escribió con su propio SQL, frente
   a los 31 del catálogo del sistema.

   Se leen del MISMO endpoint que el catálogo (`/reports`, filtrando
   `is_custom`) y no de uno aparte: son la misma cosa con una bandera, y
   pedirlos por separado abriría la puerta a que las dos listas discrepen.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';

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
  { clave: 'report_name', titulo: 'Clave', tipo: 'mono', ancho: '22%' },
];

export function Queries({ api, navegar }) {
  const [reportes, setReportes] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

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

      {!sinDatos && propias.length === 0 && (
        <p className="wt-nota">
          No hay queries a medida. Las que se creen aparecen acá y también en el
          catálogo de reportes.
        </p>
      )}

      <Tabla
        titulo="Queries personalizadas"
        columnas={COLUMNAS}
        filas={propias}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(r) => r.report_name}
        nombreExport="queries-watchtower"
        vacioTexto="No hay queries a medida."
        herramientas={
          <>
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
