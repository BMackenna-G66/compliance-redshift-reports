/* ============================================================================
   Búsqueda de entidad
   ----------------------------------------------------------------------------
   Un id de cliente, un nombre o el valor de una alerta, y devuelve todo lo
   que el sistema tiene sobre esa entidad: alertas, casos y eventos.

   PIDE TRES CARACTERES ANTES DE BUSCAR. No es capricho: la búsqueda recorre
   alertas y casos, y un solo dígito devuelve medio sistema con un costo que
   no le sirve a nadie.
   ========================================================================= */

import { useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { fecha, hace } from '../comun/alertas.js';

const MINIMO = 3;

const COLUMNAS = (navegar) => [
  {
    clave: 'source_type',
    titulo: 'Qué es',
    ancho: '11%',
    render: (r) => ({ alert: 'Alerta', case: 'Caso' }[r.source_type] || r.source_type || '—'),
  },
  { clave: 'entity_value', titulo: 'Entidad', tipo: 'mono', ancho: '14%' },
  {
    clave: 'detail',
    titulo: 'Detalle',
    render: (r) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 400 }}>
        {r.detail || '—'}
      </span>
    ),
  },
  { clave: 'report_name', titulo: 'Reporte', tipo: 'mono', ancho: '18%' },
  { clave: 'status', titulo: 'Estado', ancho: '10%' },
  {
    clave: 'event_date',
    titulo: 'Cuándo',
    ancho: '11%',
    buscable: false,
    render: (r) => (
      <span title={fecha(r.event_date)?.toLocaleString('es-CL') || r.event_date}>
        {hace(r.event_date)}
      </span>
    ),
  },
  {
    clave: 'source_id',
    titulo: '',
    ancho: '8%',
    ordenable: false,
    buscable: false,
    render: (r) => (r.source_type === 'case'
      ? <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => navegar('caso', [r.source_id])}>Abrir</button>
      : r.source_type === 'alert'
        ? <button className="wt-btn" style={{ padding: '2px 8px' }}
                  onClick={() => navegar('alert', [r.source_id])}>Abrir</button>
        : null),
    exportar: () => '',
  },
];

export function Busqueda({ api, navegar }) {
  const [q, setQ] = useState('');
  const [datos, setDatos] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState('');

  async function buscar(e) {
    e.preventDefault();
    const texto = q.trim();
    if (texto.length < MINIMO) return;
    setBuscando(true); setError(''); setDatos(null);
    try {
      setDatos(await api.get(`/search/entity?q=${encodeURIComponent(texto)}`));
    } catch (err) {
      setError(err?.message || 'No se pudo buscar.');
    } finally {
      setBuscando(false);
    }
  }

  const r = datos?.results || [];

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Búsqueda
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          alertas y casos de una entidad
        </span>
      </div>

      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)', maxWidth: 720 }}>
        <form className="wt-cuerpo-carta" onSubmit={buscar}
              style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center' }}>
          <input className="wt-input" style={{ flex: 1 }} value={q}
                 onChange={(e) => setQ(e.target.value)}
                 placeholder="Id de cliente, nombre o valor de la alerta"
                 aria-label="Qué buscar" />
          <button className="wt-btn wt-btn-primario" type="submit"
                  disabled={buscando || q.trim().length < MINIMO}>
            {buscando ? 'Buscando…' : 'Buscar'}
          </button>
        </form>
        {q.trim().length > 0 && q.trim().length < MINIMO && (
          <p style={{ margin: '0 var(--e-4) var(--e-3)', fontSize: 'var(--texto-sm)',
                      color: 'var(--texto-mute)' }}>
            Escribí al menos {MINIMO} caracteres: con menos, la búsqueda devuelve medio
            sistema.
          </p>
        )}
      </section>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {datos && (
        <>
          <p className="wt-nota">
            <strong>{r.length}</strong> resultado{r.length === 1 ? '' : 's'} para{' '}
            <span className="mono">{datos.query}</span>
            {' · '}{datos.alert_count ?? 0} alerta{datos.alert_count === 1 ? '' : 's'}
            {' y '}{datos.case_count ?? 0} caso{datos.case_count === 1 ? '' : 's'}
          </p>
          <Tabla
            titulo="Resultados"
            columnas={COLUMNAS(navegar)}
            filas={r}
            claveFila={(x, i) => `${x.source_type}-${x.source_id}-${i}`}
            nombreExport={`busqueda-${datos.query}`}
            buscable={false}
            vacioTexto="No se encontró nada con ese texto."
          />
        </>
      )}
    </>
  );
}
