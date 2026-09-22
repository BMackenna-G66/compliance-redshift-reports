/* ============================================================================
   Analítica
   ----------------------------------------------------------------------------
   Los tres analíticos que v1 calculaba en el tablero: gestión, plazos y
   transaccional. Están acá y no en Inicio a propósito — Inicio se arma con lo
   que ya está en memoria y abre en el acto; esto consulta Redshift en vivo y
   tarda entre tres y veinte segundos.

   Mezclarlos haría lenta la pantalla de entrada, que es la que más se abre.

   SE PIDEN DE A UNO Y A PEDIDO. Disparar los tres al entrar son nueve
   consultas simultáneas contra un cluster que puede estar pausado. Se abre en
   el de gestión, que es el que casi siempre se mira, y los otros dos se
   traen cuando alguien los pide.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { Barras, BarrasHorizontales, Linea, Panel } from '../comun/Grafico.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  ANALITICOS, cierrePorPrioridad, puntos, serie, total, traerAnalitico, vencidos,
} from '../comun/analitica.js';
import { ESTADOS_CASO } from '../dominio.js';
import { useVivo } from '../comun/vivo.js';

/* Los gráficos reciben el formateador, no la etiqueta ya formateada: así el
   dato crudo sigue estando para el `title` al pasar el mouse, que es lo que
   dice la fecha completa. */
function unDia(iso) {
  const s = String(iso || '');
  return s.length >= 10 ? `${s.slice(8, 10)}/${s.slice(5, 7)}` : s;
}

/* ── Gestión ─────────────────────────────────────────────────────────────── */

function Gestion({ datos }) {
  const porEstado = serie(datos, 'cases_by_status');
  const porSemana = serie(datos, 'cases_by_week');
  const porReporte = serie(datos, 'alerts_by_report');
  const porDia = serie(datos, 'alerts_daily_30d');
  const entidades = serie(datos, 'top_entities');

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Casos" valor={total(porEstado).toLocaleString('es-CL')}
             pie="en todos los estados" />
        <Kpi etiqueta="Alertas de 30 días" valor={total(porDia).toLocaleString('es-CL')}
             pie="las que entraron" />
        <Kpi etiqueta="Reportes que alertaron" valor={porReporte.length}
             pie="de los del catálogo" />
      </div>

      <div className="wt-ficha-grilla">
        <Panel titulo="Casos por estado" pie="cómo se reparte lo abierto">
          <BarrasHorizontales
            datos={porEstado.map((f) => ({
              etiqueta: ESTADOS_CASO[f.status]?.etiqueta || f.status || '(sin estado)',
              valor: Number(f.n || 0),
            }))}
          />
        </Panel>

        <Panel titulo="Casos abiertos por semana" pie="el lunes de cada semana">
          <Barras datos={puntos(porSemana, 'week_start')} etiqueta={unDia} />
        </Panel>

        <Panel titulo="Alertas por día" pie="los últimos 30 días">
          <Linea datos={puntos(porDia, 'day')} etiqueta={unDia} />
        </Panel>

        <Panel titulo="Alertas por reporte" pie="qué reporte dispara más">
          <BarrasHorizontales datos={puntos(porReporte, 'report_name')} />
        </Panel>

        <Panel titulo="Quiénes más aparecen" pie="clientes y empresas con más alertas">
          {entidades.length === 0 ? (
            <p className="wt-vacio">Sin datos en el período.</p>
          ) : (
            <div className="wt-tabla-marco">
              <table className="wt-tabla">
                <thead><tr><th>Entidad</th><th>Tipo</th><th className="wt-td-num">Alertas</th></tr></thead>
                <tbody>
                  {entidades.map((e, i) => (
                    <tr key={i}>
                      <td className="wt-td-mono">{e.entity_value}</td>
                      <td>{e.entity_type === 'company' ? 'empresa' : 'cliente'}</td>
                      <td className="wt-td-num">{Number(e.n || 0).toLocaleString('es-CL')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

/* ── Plazos ──────────────────────────────────────────────────────────────── */

function Plazos({ datos }) {
  const v = vencidos(datos);
  const cierre = cierrePorPrioridad(datos);
  const porPrioridad = serie(datos, 'by_priority');

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Casos abiertos" valor={v.abiertos.toLocaleString('es-CL')} />
        <Kpi etiqueta="Vencidos" valor={v.vencidos.toLocaleString('es-CL')}
             pie={v.abiertos ? `${Math.round(v.vencidos * 100 / v.abiertos)}% de los abiertos` : ''} />
        <Kpi etiqueta="Vencidos críticos" valor={v.critico.toLocaleString('es-CL')}
             pie="los que más urgen" />
      </div>

      {/* La proporción vencida es el número que decide si el equipo está al
          día. Se dice con palabras además del porcentaje: un 113% de un
          gráfico no significa nada, «69 de 69» sí. */}
      {v.abiertos > 0 && v.vencidos > 0 && (
        <p className="wt-nota wt-nota-alarma">
          <strong>{v.vencidos} de {v.abiertos} casos abiertos están vencidos.</strong>{' '}
          El plazo lo define compliance y se calcula en el backend: esta pantalla lo
          muestra, no lo decide.
        </p>
      )}

      <div className="wt-ficha-grilla">
        <Panel titulo="Vencidos por prioridad" pie="dónde está el atraso">
          <BarrasHorizontales datos={[
            { etiqueta: 'Crítico', valor: v.critico },
            { etiqueta: 'Alto', valor: v.alto },
            { etiqueta: 'Medio', valor: v.medio },
            { etiqueta: 'Bajo', valor: v.bajo },
          ]} />
        </Panel>

        <Panel titulo="Días hasta el cierre" pie="promedio de los casos ya cerrados">
          {cierre.length === 0 ? (
            <p className="wt-vacio">Todavía no se cerró ningún caso.</p>
          ) : (
            <div className="wt-tabla-marco">
              <table className="wt-tabla">
                <thead>
                  <tr><th>Prioridad</th><th className="wt-td-num">Días</th>
                    <th className="wt-td-num">Cerrados</th></tr>
                </thead>
                <tbody>
                  {cierre.map((c, i) => (
                    <tr key={i}>
                      <td>{c.prioridad}</td>
                      <td className="wt-td-num">{c.dias.toFixed(1)}</td>
                      <td className="wt-td-num">{c.cerrados.toLocaleString('es-CL')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel titulo="Estado por prioridad" pie="la matriz completa">
          {porPrioridad.length === 0 ? (
            <p className="wt-vacio">Sin datos.</p>
          ) : (
            <div className="wt-tabla-marco">
              <table className="wt-tabla">
                <thead>
                  <tr><th>Prioridad</th><th>Estado</th><th className="wt-td-num">Casos</th></tr>
                </thead>
                <tbody>
                  {porPrioridad.map((f, i) => (
                    <tr key={i}>
                      <td>{f.priority || '—'}</td>
                      <td>{ESTADOS_CASO[f.status]?.etiqueta || f.status || '—'}</td>
                      <td className="wt-td-num">{Number(f.n || 0).toLocaleString('es-CL')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

/* ── Transaccional ───────────────────────────────────────────────────────── */

function Transaccional({ datos }) {
  const diario = serie(datos, 'daily_evolution');
  const grandes = serie(datos, 'over_300k');
  const paises = serie(datos, 'by_country');

  /* Estas tres series salen del cluster de Redshift, que está pausado de
     18:30 a 04:00. Vacías no significa «no pasó nada»: significa que no se
     pudo mirar, y confundir las dos cosas es lo que hace que alguien concluya
     que el día estuvo tranquilo. */
  if (diario.length === 0 && grandes.length === 0 && paises.length === 0) {
    return (
      <p className="wt-nota">
        Las tres series vinieron vacías. Casi siempre es el cluster de Redshift pausado
        —lo está de 18:30 a 04:00— y no que no haya habido movimiento. Revisá el estado
        del cluster antes de sacar conclusiones.
      </p>
    );
  }

  return (
    <div className="wt-ficha-grilla">
      <Panel titulo="Volumen por día" pie="operaciones diarias">
        <Linea datos={puntos(diario, 'day', 'total')} etiqueta={unDia} />
      </Panel>
      <Panel titulo="Operaciones sobre USD 300.000" pie="las grandes">
        <BarrasHorizontales datos={puntos(grandes, 'entity_value', 'total')} />
      </Panel>
      <Panel titulo="Por país" pie="a dónde va la plata">
        <BarrasHorizontales datos={puntos(paises, 'country', 'total')} />
      </Panel>
    </div>
  );
}

/* ── La pantalla ─────────────────────────────────────────────────────────── */

const CUERPOS = { gestion: Gestion, plazos: Plazos, transaccional: Transaccional };

export function Analitica({ api }) {
  const [cual, setCual] = useState('gestion');
  /* Cada analítico guarda lo suyo: volver a una pestaña ya traída no la
     vuelve a pedir, y el cluster lo agradece. */
  const [datos, setDatos] = useState({});
  const [estado, setEstado] = useState({});

  const vivo = useVivo();

  const traer = useCallback(async (clave) => {
    setEstado((e) => ({ ...e, [clave]: { cargando: true, error: '', aviso: '' } }));
    try {
      const r = await traerAnalitico((ruta) => api.get(ruta), clave, {
        alAvanzar: (d) => { if (vivo.current) setDatos((x) => ({ ...x, [clave]: d })); },
        cancelado: () => !vivo.current,
      });
      if (!vivo.current) return;
      setDatos((x) => ({ ...x, [clave]: r.datos }));
      setEstado((e) => ({ ...e, [clave]: { cargando: false, error: '', aviso: r.motivo } }));
    } catch (e) {
      if (!vivo.current) return;
      setEstado((x) => ({
        ...x, [clave]: { cargando: false, aviso: '', error: e?.message || 'No se pudo traer.' },
      }));
    }
  }, [api]);

  /* Sólo el que se está mirando, y sólo la primera vez. */
  useEffect(() => {
    if (datos[cual] === undefined && !estado[cual]?.cargando) traer(cual);
  // `datos` y `estado` quedan afuera: incluirlos re-dispararía en cada vuelta
  // de la cosecha, que es justo lo que hay que evitar.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cual, traer]);

  const est = estado[cual] || {};
  const Cuerpo = CUERPOS[cual];

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Analítica
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          consulta Redshift en vivo
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }}
                disabled={est.cargando} onClick={() => traer(cual)}>
          {est.cargando ? 'Consultando…' : 'Volver a consultar'}
        </button>
      </div>

      <nav className="wt-pasos" aria-label="Analíticos">
        {Object.entries(ANALITICOS).map(([k, v]) => (
          <button key={k} className={`wt-paso-boton${cual === k ? ' wt-paso-activo' : ''}`}
                  onClick={() => setCual(k)}>
            <span>
              <span className="wt-paso-titulo">{v.titulo}</span>
              <span className="wt-paso-pie">{v.pie}</span>
            </span>
          </button>
        ))}
      </nav>

      {est.error && (
        <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{est.error}</div>
      )}
      {est.aviso && <p className="wt-nota">{est.aviso}</p>}

      {est.cargando && datos[cual] === undefined ? (
        <div className="wt-estado">
          <p style={{ margin: 0 }}>Consultando Redshift…</p>
          <p style={{ fontSize: 'var(--texto-sm)', marginTop: 8 }}>
            Son varias consultas a la vez y tardan entre tres y veinte segundos. Si el
            cluster estaba pausado, la primera del día tarda unos minutos más.
          </p>
        </div>
      ) : datos[cual] !== undefined ? (
        <Cuerpo datos={datos[cual]} />
      ) : null}
    </>
  );
}
