/* ============================================================================
   Auditoría
   ----------------------------------------------------------------------------
   Quién hizo qué. Las últimas 200 acciones registradas.

   SE SEPARAN LOS CAMBIOS DE LAS CONSULTAS. «Descargó la ficha de un cliente»
   y «borró un caso» llegan en la misma lista y con el mismo aspecto; cuando
   hay que reconstruir qué pasó un día, lo primero que se busca son los
   cambios. El filtro está arriba y por defecto muestra todo, que es lo
   honesto — esconder consultas por defecto sería decidir por el auditor.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import { accionEs, entidadEs, esCambio, resumenAuditoria } from '../comun/admin.js';
import { fecha, hace } from '../comun/alertas.js';

const COLUMNAS = [
  {
    clave: 'created_at',
    titulo: 'Cuándo',
    ancho: '13%',
    buscable: false,
    render: (e) => (
      <span title={fecha(e.created_at)?.toLocaleString('es-CL') || e.created_at}>
        {hace(e.created_at)}
      </span>
    ),
  },
  {
    clave: '_quien',
    titulo: 'Quién',
    ancho: '17%',
    render: (e) => e._quien || <span style={{ color: 'var(--texto-mute)' }}>—</span>,
  },
  {
    clave: '_accion',
    titulo: 'Qué hizo',
    ancho: '28%',
    render: (e) => (
      <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
        <span style={{ color: e._cambio ? 'var(--texto)' : 'var(--texto-mute)' }}>
          {e._accion}
        </span>
        <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
          {e.action}
        </span>
      </span>
    ),
  },
  { clave: '_entidad', titulo: 'Sobre', ancho: '10%' },
  {
    clave: 'entity_id',
    titulo: 'Cuál',
    tipo: 'mono',
    ancho: '24%',
    render: (e) => (
      <span className="mono" style={{ fontSize: 'var(--texto-xs)', wordBreak: 'break-all' }}>
        {e.entity_id || '—'}
      </span>
    ),
  },
  {
    clave: '_cambio',
    titulo: 'Tipo',
    ancho: '8%',
    buscable: false,
    render: (e) => (e._cambio
      ? <span className="wt-insignia"
              style={{ color: 'var(--g66-azul-texto)', background: 'var(--azul-tenue)' }}>
          cambio
        </span>
      : <span className="wt-insignia wt-insignia-sindato">consulta</span>),
    exportar: (e) => (e._cambio ? 'cambio' : 'consulta'),
  },
];

const FILTROS = {
  todo: { etiqueta: 'Todo', prueba: () => true },
  cambios: { etiqueta: 'Sólo cambios', prueba: esCambio },
  consultas: { etiqueta: 'Sólo consultas', prueba: (e) => !esCambio(e) },
};

export function Auditoria({ api }) {
  const [entradas, setEntradas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [filtro, setFiltro] = useState('todo');

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/audit');
      setEntradas(d?.entries || []);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar la auditoría.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const preparadas = useMemo(() => entradas.map((e) => ({
    ...e,
    _quien: (e.user_email || '').replace('@global66.com', ''),
    _accion: accionEs(e.action),
    _entidad: entidadEs(e.entity_type),
    _cambio: esCambio(e),
  })), [entradas]);

  const visibles = useMemo(
    () => preparadas.filter(FILTROS[filtro]?.prueba || (() => true)),
    [preparadas, filtro],
  );
  const r = useMemo(() => resumenAuditoria(entradas), [entradas]);

  const sinDatos = (cargando || Boolean(error)) && entradas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Acciones" valor={n(r.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer')
                           : 'las últimas registradas'} />
        <Kpi etiqueta="Cambios" valor={n(r.cambios)} pie="modificaron algo" />
        <Kpi etiqueta="Consultas" valor={n(r.total - r.cambios)} pie="sólo miraron" />
        <Kpi etiqueta="Personas" valor={n(r.personas)} pie="distintas" />
      </div>

      {/* La auditoría tarda unos ocho segundos: conviene decirlo antes de que
          alguien piense que se colgó y recargue. */}
      {cargando && entradas.length === 0 && (
        <p className="wt-nota">Leyendo el registro… suele tardar unos segundos.</p>
      )}

      <Tabla
        titulo="Registro de auditoría"
        columnas={COLUMNAS}
        filas={visibles}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(e) => e.log_id}
        nombreExport="auditoria-watchtower"
        porPagina={50}
        vacioTexto="No hay acciones registradas."
        herramientas={
          <>
            <div className="wt-filtros">
              {Object.entries(FILTROS).map(([clave, f]) => (
                <button key={clave} className="wt-filtro" aria-pressed={filtro === clave}
                        onClick={() => setFiltro(clave)}>
                  {f.etiqueta}
                  {!sinDatos && (
                    <span className="wt-filtro-n">
                      {preparadas.filter(f.prueba).length}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </>
        }
      />
    </>
  );
}
