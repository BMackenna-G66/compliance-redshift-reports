/* ============================================================================
   Inicio · Dashboard AML
   ----------------------------------------------------------------------------
   La pantalla de entrada. Los números salen de las MISMAS listas que usan la
   bandeja y casos —no de un endpoint de resumen aparte— para que no haya dos
   versiones del mismo número según por dónde se mire.

   LOS TRES GRÁFICOS DE TRANSACCIONES SÍ SE PIDEN, porque salen de Redshift y
   no de una lista que el front ya tenga. Van aparte y bajo demanda: son tres
   consultas al cluster y, si está pausado, tardan minutos. Cargarlas al
   entrar haría que la pantalla de inicio fuera la más lenta de todas.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Kpi } from '../comun/Kpi.jsx';
import { Barras, BarrasHorizontales, Linea, Panel } from '../comun/Grafico.jsx';
import {
  diaCorto, indicadores, porClave, serieDiaria, serieSemanal, ultimos,
} from '../comun/tablero.js';
import { nombreLegible } from '../comun/alertas.js';
import { ESTADOS_CASO } from '../dominio.js';

export function Inicio({ api, navegar }) {
  const [alertas, setAlertas] = useState([]);
  const [casos, setCasos] = useState([]);
  const [listaBlanca, setListaBlanca] = useState([]);
  const [corridas, setCorridas] = useState([]);
  const [catalogo, setCatalogo] = useState({});
  const [cargando, setCargando] = useState(true);
  const [fallaron, setFallaron] = useState([]);

  const cargar = useCallback(async () => {
    setCargando(true);
    const [a, c, w, r, rep] = await Promise.allSettled([
      api.get('/alerts'),
      api.get('/cases?status=all'),
      api.get('/whitelist'),
      api.get('/runs'),
      api.get('/reports'),
    ]);
    if (a.status === 'fulfilled') setAlertas(a.value?.alerts || []);
    if (c.status === 'fulfilled') setCasos(c.value?.cases || []);
    if (w.status === 'fulfilled') setListaBlanca(w.value?.whitelist || []);
    if (r.status === 'fulfilled') setCorridas(r.value?.runs || []);
    if (rep.status === 'fulfilled') {
      const m = {};
      for (const x of rep.value?.reports || []) m[x.report_name] = x.display_name || x.report_name;
      setCatalogo(m);
    }
    /* Se dice QUÉ faltó, no «hubo un error»: con cinco llamadas, un error
       genérico deja sin saber cuál de los ocho gráficos está incompleto. */
    setFallaron([['alertas', a], ['casos', c], ['lista blanca', w], ['corridas', r]]
      .filter(([, x]) => x.status === 'rejected').map(([n]) => n));
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const ind = useMemo(
    () => indicadores({ alertas, casos, listaBlanca, corridas }),
    [alertas, casos, listaBlanca, corridas],
  );

  const nombreRep = useCallback(
    (clave) => catalogo[clave] || nombreLegible(clave),
    [catalogo],
  );

  const porReporte30 = useMemo(
    () => porClave(ultimos(alertas, 'created_at', 30), 'report_name', 6)
      .map((x) => ({ ...x, etiqueta: x.esOtros ? x.etiqueta : nombreRep(x.etiqueta) })),
    [alertas, nombreRep],
  );
  const porReporte90 = useMemo(
    () => porClave(ultimos(alertas, 'created_at', 90), 'report_name', 6)
      .map((x) => ({ ...x, etiqueta: x.esOtros ? x.etiqueta : nombreRep(x.etiqueta) })),
    [alertas, nombreRep],
  );
  const tendencia = useMemo(() => serieDiaria(alertas, 'created_at', 30), [alertas]);
  const casosPorEstado = useMemo(
    () => porClave(casos, 'status').map((x) => ({
      ...x, etiqueta: ESTADOS_CASO[x.etiqueta]?.etiqueta || x.etiqueta,
    })),
    [casos],
  );
  const casosPorSemana = useMemo(() => serieSemanal(casos, 'created_at', 8), [casos]);
  const topEntidades = useMemo(() => porClave(alertas, 'entity_value', 5), [alertas]);
  const porAnalista = useMemo(
    () => porClave(casos.filter((c) => !['closed', 'archived'].includes(c.status)),
                   'assigned_to', 6)
      .map((x) => ({ ...x, etiqueta: x.etiqueta.replace('@global66.com', '') || 'sin asignar' })),
    [casos],
  );

  const sinDatos = cargando && alertas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Alertas activas" valor={n(ind.alertas)}
             pie={sinDatos ? 'leyendo…' : `${ind.alertas7d} en los últimos 7 días`}
             alPulsar={sinDatos ? undefined : () => navegar('dashboard')} />
        <Kpi etiqueta="Casos abiertos" valor={n(ind.casosAbiertos)}
             pie={sinDatos ? '' : `${ind.casosVencidos} vencidos`}
             alPulsar={sinDatos ? undefined : () => navegar('cases')} />
        <Kpi etiqueta="En lista blanca" valor={n(ind.listaBlanca)} pie="no generan alertas"
             alPulsar={sinDatos ? undefined : () => navegar('whitelist')} />
        <Kpi etiqueta="Corridas (7d)" valor={n(ind.corridas7d)} pie="reportes ejecutados"
             alPulsar={sinDatos ? undefined : () => navegar('history')} />
      </div>

      {fallaron.length > 0 && (
        <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>
          No se pudieron leer: {fallaron.join(', ')}. Los gráficos que dependen de eso
          están incompletos.
          <button className="wt-btn" onClick={cargar}>Reintentar</button>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-3)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Dashboard AML
        </h1>
        <button className="wt-btn" style={{ marginLeft: 'auto' }}
                onClick={cargar} disabled={cargando}>Refrescar</button>
      </div>

      {cargando && alertas.length === 0 ? (
        <p className="wt-estado">Cargando…</p>
      ) : (
        <div className="wt-ficha-grilla">
          <Panel titulo="Alertas por reporte" pie="últimos 30 días">
            <BarrasHorizontales datos={porReporte30} />
          </Panel>

          <Panel titulo="Tendencia de alertas" pie="últimos 30 días">
            <Linea datos={tendencia} etiqueta={diaCorto} />
          </Panel>

          <Panel titulo="Casos por estado" pie={`${casos.length} en total`}>
            <BarrasHorizontales datos={casosPorEstado} color="var(--violeta)" />
          </Panel>

          <Panel titulo="Casos creados por semana" pie="últimas 8 semanas">
            <Barras datos={casosPorSemana} color="var(--g66-teal)" etiqueta={diaCorto} />
          </Panel>

          <Panel titulo="Alertas por reporte" pie="últimos 90 días">
            <BarrasHorizontales datos={porReporte90} color="var(--g66-navy-2)" />
          </Panel>

          <Panel titulo="Carga por analista" pie="casos abiertos">
            <BarrasHorizontales datos={porAnalista} color="var(--nivel-alto)" />
          </Panel>

          <Panel titulo="Clientes con más alertas" pie="top 5">
            {topEntidades.length === 0 ? (
              <p style={{ color: 'var(--texto-mute)', fontSize: 'var(--texto-sm)', margin: 0 }}>
                Sin alertas.
              </p>
            ) : (
              <table className="wt-tabla">
                <thead><tr><th>Cliente</th><th className="wt-td-num">Alertas</th><th /></tr></thead>
                <tbody>
                  {topEntidades.map((e) => (
                    <tr key={e.etiqueta}>
                      <td className="wt-td-mono">{e.etiqueta}</td>
                      <td className="wt-td-num">{e.valor}</td>
                      <td>
                        {!e.esOtros && (
                          <button className="wt-btn" style={{ padding: '2px 8px' }}
                                  onClick={() => navegar('ficha', [e.etiqueta])}>
                            Ficha
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          {/* Las tres consultas a Redshift van en su propia pantalla y no
              acá: cargarlas al entrar haría que el inicio fuera lo más lento
              de la aplicación, y con el cluster pausado tardan minutos. */}
          <Panel titulo="Transacciones" pie="consulta a Redshift">
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
              La evolución diaria, las operaciones sobre USD 300K y el volumen por país
              salen de tres consultas a Redshift. No se cargan al entrar: con el cluster
              pausado tardan varios minutos y harían de esta la pantalla más lenta.
            </p>
            <button className="wt-btn" style={{ marginTop: 'var(--e-3)' }}
                    onClick={() => navegar('reports')}>
              Ir a los reportes
            </button>
          </Panel>
        </div>
      )}
    </>
  );
}
