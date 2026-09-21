/* ============================================================================
   Institucional
   ----------------------------------------------------------------------------
   Las empresas clientes, las reglas de umbral que se les aplican y las
   alertas que esas reglas dispararon. Tres cosas distintas que se miran
   juntas, por eso van en pestañas y no en tres pantallas.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  RIESGO_EMPRESA, excesoDe, excesoTexto, fecha, hace, riesgoDe,
} from '../comun/analisis.js';

const USD = (v) => (v === null || v === undefined || v === ''
  ? '—'
  : `USD ${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`);

function Riesgo({ empresa }) {
  const r = riesgoDe(empresa);
  if (!r) {
    // Un nivel que el front no conoce se muestra crudo. Pintarlo de verde
    // sería decir "bajo" sobre algo que no se sabe.
    return (
      <span className="wt-insignia wt-insignia-sindato">
        {empresa.risk_level || 'sin nivel'}
      </span>
    );
  }
  return (
    <span className="wt-insignia" style={{ color: r.color, background: r.fondo }}>
      {r.etiqueta}
    </span>
  );
}

const COLUMNAS_EMPRESAS = [
  {
    clave: 'company_name',
    titulo: 'Empresa',
    ancho: '26%',
    render: (e) => (
      <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
        <span style={{ color: 'var(--texto)', whiteSpace: 'normal' }}>{e.company_name || '—'}</span>
        <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
          {e.identification_type} {e.identification_number}
        </span>
      </span>
    ),
  },
  {
    clave: '_riesgoOrden',
    titulo: 'Riesgo',
    ancho: '9%',
    buscable: false,
    render: (e) => <Riesgo empresa={e} />,
    exportar: (e) => e.risk_level || '',
  },
  { clave: 'compliance_status', titulo: 'Compliance', ancho: '11%' },
  { clave: 'industry', titulo: 'Industria', ancho: '13%' },
  {
    clave: 'economic_activity',
    titulo: 'Actividad',
    ancho: '16%',
    render: (e) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 240 }}>
        {e.economic_activity || '—'}
      </span>
    ),
  },
  { clave: 'n_transacciones', titulo: 'Trx', tipo: 'numero', ancho: '7%', buscable: false },
  {
    clave: 'monto_total_usd',
    titulo: 'Monto total',
    tipo: 'numero',
    ancho: '10%',
    buscable: false,
    render: (e) => USD(e.monto_total_usd),
  },
  {
    clave: 'monto_30d_usd',
    titulo: 'Últimos 30d',
    tipo: 'numero',
    ancho: '10%',
    buscable: false,
    render: (e) => USD(e.monto_30d_usd),
  },
];

const COLUMNAS_REGLAS = [
  {
    clave: 'company_name',
    titulo: 'Se aplica a',
    ancho: '26%',
    // `company_id` nulo significa que la regla vale para todas las empresas.
    // El backend lo llama "Default", que no dice eso.
    render: (r) => (r.company_id === null || r.company_id === undefined
      ? <strong>Todas las empresas</strong>
      : <>{r.company_name} <span className="mono"
            style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            {r.company_id}</span></>),
    exportar: (r) => (r.company_id == null ? 'Todas las empresas' : r.company_name),
  },
  { clave: 'metric', titulo: 'Métrica', tipo: 'mono', ancho: '14%' },
  {
    clave: 'window',
    titulo: 'Ventana',
    ancho: '14%',
    render: (r) => (r.window_days ? `${r.window_days} días` : r.window || '—'),
  },
  {
    clave: 'umbral',
    titulo: 'Umbral',
    tipo: 'numero',
    ancho: '16%',
    buscable: false,
    render: (r) => USD(r.umbral),
  },
  {
    clave: 'enabled',
    titulo: 'Estado',
    ancho: '12%',
    // Una regla apagada no dispara nada. Que se vea de un vistazo importa:
    // una alerta que no llega puede ser que no haya nada, o que la regla
    // esté apagada, y son cosas muy distintas.
    render: (r) => (r.enabled
      ? <span style={{ color: 'var(--nivel-bajo-texto)' }}>Activa</span>
      : <span style={{ color: 'var(--nivel-alto-texto)', fontWeight: 'var(--peso-medio)' }}>
          Apagada
        </span>),
    exportar: (r) => (r.enabled ? 'Activa' : 'Apagada'),
  },
];

const COLUMNAS_ALERTAS = [
  { clave: 'company_name', titulo: 'Empresa', ancho: '26%' },
  { clave: 'metric', titulo: 'Métrica', tipo: 'mono', ancho: '13%' },
  {
    clave: 'valor',
    titulo: 'Valor',
    tipo: 'numero',
    ancho: '14%',
    buscable: false,
    render: (a) => USD(a.valor),
  },
  {
    clave: 'umbral',
    titulo: 'Umbral',
    tipo: 'numero',
    ancho: '13%',
    buscable: false,
    render: (a) => USD(a.umbral),
  },
  {
    clave: '_exceso',
    titulo: 'Se pasó',
    tipo: 'numero',
    ancho: '10%',
    buscable: false,
    // Con el valor y el umbral en dos columnas hay que dividir mentalmente
    // en cada fila para saber si esto es grave o si rozó el límite.
    render: (a) => (
      <strong style={{ color: a._exceso >= 2 ? 'var(--nivel-critico-texto)' : 'var(--texto-2)' }}>
        {excesoTexto(a._exceso)}
      </strong>
    ),
  },
  {
    clave: 'fecha',
    titulo: 'Fecha',
    ancho: '12%',
    buscable: false,
    render: (a) => fecha(a.fecha)?.toLocaleDateString('es-CL') || a.fecha || '—',
  },
  {
    clave: 'revisado',
    titulo: 'Revisada',
    ancho: '12%',
    render: (a) => (a.revisado
      ? <span style={{ color: 'var(--texto-mute)' }}>sí</span>
      : <span style={{ color: 'var(--nivel-alto-texto)', fontWeight: 'var(--peso-medio)' }}>
          pendiente
        </span>),
    exportar: (a) => (a.revisado ? 'sí' : 'pendiente'),
  },
];

const PESTANAS = [
  { id: 'empresas', etiqueta: 'Empresas' },
  { id: 'reglas', etiqueta: 'Reglas' },
  { id: 'alertas', etiqueta: 'Alertas' },
];

export function Institucional({ api }) {
  const [pestana, setPestana] = useState('empresas');
  const [empresas, setEmpresas] = useState([]);
  const [reglas, setReglas] = useState([]);
  const [alertas, setAlertas] = useState([]);
  const [calculado, setCalculado] = useState('');
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    // Las tres en paralelo: son independientes y esperar en serie
    // triplicaría el tiempo de la pantalla sin ganar nada.
    const [e, r, a] = await Promise.allSettled([
      api.get('/institutional/clients'),
      api.get('/institutional/rules'),
      api.get('/institutional/alerts'),
    ]);
    if (e.status === 'fulfilled') {
      setEmpresas(e.value?.clients || []);
      setCalculado(e.value?.computed_at || '');
    }
    if (r.status === 'fulfilled') setReglas(r.value?.rules || []);
    if (a.status === 'fulfilled') setAlertas(a.value?.alerts || []);

    // Se informa cuál falló, no un error genérico: con tres llamadas, "hubo
    // un error" no dice qué pestaña está mostrando datos viejos.
    const fallos = [['empresas', e], ['reglas', r], ['alertas', a]]
      .filter(([, x]) => x.status === 'rejected')
      .map(([n, x]) => `${n} (${x.reason?.message || 'error'})`);
    setError(fallos.length ? `No se pudo cargar: ${fallos.join(' · ')}` : '');
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const empresasPrep = useMemo(() => empresas.map((e) => ({
    ...e,
    _riesgoOrden: riesgoDe(e)?.orden ?? 99,
  })), [empresas]);

  const alertasPrep = useMemo(() => alertas.map((a) => ({
    ...a, _exceso: excesoDe(a),
  })), [alertas]);

  const ind = useMemo(() => ({
    empresas: empresas.length,
    altoRiesgo: empresas.filter((e) => e.risk_level === 'High').length,
    reglasActivas: reglas.filter((r) => r.enabled).length,
    reglasTotal: reglas.length,
    alertasPendientes: alertas.filter((a) => !a.revisado).length,
  }), [empresas, reglas, alertas]);

  const sinDatos = cargando && empresas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  const comun = {
    cargando,
    alReintentar: cargar,
    herramientas: <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>,
  };

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Empresas" valor={n(ind.empresas)}
             pie={calculado ? `calculado ${hace(calculado)}` : 'clientes institucionales'} />
        <Kpi etiqueta="Riesgo alto" valor={n(ind.altoRiesgo)} pie="según el modelo" />
        <Kpi etiqueta="Reglas activas" valor={n(ind.reglasActivas)}
             pie={`de ${ind.reglasTotal} configuradas`} />
        <Kpi etiqueta="Alertas pendientes" valor={n(ind.alertasPendientes)} pie="sin revisar" />
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      <div className="wt-filtros" style={{ marginBottom: 'var(--e-3)' }}>
        {PESTANAS.map((p) => (
          <button key={p.id} className="wt-filtro" aria-pressed={pestana === p.id}
                  onClick={() => setPestana(p.id)}>
            {p.etiqueta}
            <span className="wt-filtro-n">
              {p.id === 'empresas' ? empresas.length
                : p.id === 'reglas' ? reglas.length : alertas.length}
            </span>
          </button>
        ))}
      </div>

      {pestana === 'empresas' && (
        <Tabla {...comun} titulo="Empresas clientes" columnas={COLUMNAS_EMPRESAS}
               filas={empresasPrep} claveFila={(e) => e.company_id}
               nombreExport="empresas-watchtower" porPagina={40}
               vacioTexto="No hay empresas cargadas." />
      )}
      {pestana === 'reglas' && (
        <Tabla {...comun} titulo="Reglas de umbral" columnas={COLUMNAS_REGLAS}
               filas={reglas} claveFila={(r) => r.rule_id}
               nombreExport="reglas-institucionales"
               vacioTexto="No hay reglas configuradas: no se va a disparar ninguna alerta institucional." />
      )}
      {pestana === 'alertas' && (
        <Tabla {...comun} titulo="Alertas institucionales" columnas={COLUMNAS_ALERTAS}
               filas={alertasPrep} claveFila={(a) => a.alert_id}
               nombreExport="alertas-institucionales"
               vacioTexto="Ninguna regla se disparó." />
      )}
    </>
  );
}

export { RIESGO_EMPRESA };
