/* ============================================================================
   Bandeja de alertas — el Command desk
   ----------------------------------------------------------------------------
   Los indicadores arriba, la tabla abajo. Los indicadores son botones: leer
   "50 sin caso" y tener que ir a buscar el filtro en otro lado es hacer dos
   veces el mismo trabajo.

   Los datos se cargan al entrar y con el botón de refrescar. No hay feed en
   vivo — decisión tomada, ver PLAN.md.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Suspense, lazy } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { queryDeExportacion } from '../comun/reparto.js';
import { soloLectura } from '../permisos.js';

/* El panel de reparto se carga al abrirlo: casi nadie reparte alertas en la
   mayoría de las visitas a la bandeja. */
const Reparto = lazy(() =>
  import('./alertas/Reparto.jsx').then((m) => ({ default: m.Reparto })));
import { Kpi } from '../comun/Kpi.jsx';
import { InsigniaCaso, InsigniaPrioridad } from '../comun/Insignia.jsx';
import {
  FILTROS, aplicarFiltro, fecha, hace, indicadores, montoTexto, prepararAlerta,
} from '../comun/alertas.js';

function Cliente({ a }) {
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
      <span className="mono" style={{ color: 'var(--texto)' }}>{a.entity_value || '—'}</span>
      {a._correo && (
        <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
          {a._correo}
        </span>
      )}
    </span>
  );
}

function columnas(navegar) {
  return [
    {
      clave: 'created_at',
      titulo: 'Entró',
      ancho: '9%',
      render: (a) => (
        <span title={fecha(a.created_at)?.toLocaleString('es-CL') || a.created_at}>
          {hace(a.created_at)}
        </span>
      ),
    },
    { clave: 'entity_value', titulo: 'Cliente', ancho: '15%', render: (a) => <Cliente a={a} /> },
    {
      clave: '_reporte',
      titulo: 'Reporte',
      ancho: '20%',
      render: (a) => (
        <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 300 }}>
          {a._reporte}
        </span>
      ),
    },
    {
      clave: '_monto',
      titulo: 'Monto',
      tipo: 'numero',
      ancho: '11%',
      buscable: false,
      // El título dice de qué campo salió: cada reporte mide una cosa
      // distinta y un número sin su unidad no significa nada.
      render: (a) => (
        <span title={a._montoCampo ? `${a._montoEtiqueta} (${a._montoCampo})` : 'Este reporte no trae monto'}>
          {montoTexto(a._monto === null ? null : { valor: a._monto })}
        </span>
      ),
      exportar: (a) => (a._monto === null ? '' : a._monto),
    },
    {
      clave: '_score',
      titulo: 'Puntaje',
      tipo: 'numero',
      ancho: '8%',
      buscable: false,
      render: (a) => (a._score === null
        ? <span style={{ color: 'var(--texto-mute)' }}>—</span>
        : <span title="Puntaje del reporte, sobre 100">{a._score.toFixed(0)}</span>),
    },
    {
      clave: '_prioridad',
      titulo: 'Prioridad',
      ancho: '8%',
      render: (a) => <InsigniaPrioridad prioridad={a._prioridad} />,
      // Ordenar por el texto pondría los "sin puntaje" en medio; el número
      // los deja donde corresponde, al final.
      exportar: (a) => a._prioridad || 'sin puntaje',
    },
    { clave: '_caso', titulo: 'Caso', ancho: '10%', render: (a) => <InsigniaCaso alerta={a} /> },
    {
      clave: '_asignado',
      titulo: 'Asignada a',
      ancho: '14%',
      render: (a) => (a._asignado
        ? a._asignado.replace('@global66.com', '')
        : <span style={{ color: 'var(--nivel-alto-texto)' }}>sin asignar</span>),
    },
    {
      clave: 'alert_id',
      titulo: '',
      ancho: '5%',
      ordenable: false,
      buscable: false,
      render: (a) => (
        <button className="wt-btn" onClick={() => navegar('alert', [a.alert_id])}>
          Abrir
        </button>
      ),
      exportar: () => '',
    },
  ];
}

export function Bandeja({ api, perfil, navegar }) {
  const [alertas, setAlertas] = useState([]);
  const [catalogo, setCatalogo] = useState({});
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [filtro, setFiltro] = useState('todas');
  /* La bandeja muestra las ACTIVAS. «Ya revisadas» es el mismo listado con
     otro endpoint; sin esta vista, lo que se revisó desaparece y no hay
     forma de comprobar qué se hizo ni de deshacer una revisión apurada. */
  const [vista, setVista] = useState('activas');

  const [seleccion, setSeleccion] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [repartiendo, setRepartiendo] = useState(false);
  const [aviso, setAviso] = useState('');
  const [bajando, setBajando] = useState(false);

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const d = await api.get(vista === 'revisadas' ? '/alerts/reviewed' : '/alerts');
      setAlertas(d?.alerts || []);
      // El aviso que el backend manda cuando la lectura falló parcialmente.
      // Sin esto la pantalla mostraría una bandeja vacía como si no hubiera
      // trabajo, que es la peor forma de fallar acá.
      if (d?.warning) setError(`La API respondió con un aviso: ${d.warning}`);
    } catch (e) {
      setError(e?.message || 'No se pudieron cargar las alertas.');
    } finally {
      setCargando(false);
    }
  }, [api, vista]);

  useEffect(() => { cargar(); }, [cargar]);

  // El nombre legible de cada reporte lo sabe el catálogo, no el front. Si
  // esta llamada falla no pasa nada grave: se muestra el nombre técnico.
  useEffect(() => {
    let vivo = true;
    api.get('/crm/users').then((d) => setUsuarios(d?.users || [])).catch(() => {});
    api.get('/reports')
      .then((d) => {
        if (!vivo) return;
        const m = {};
        for (const r of d?.reports || []) m[r.report_name] = r.display_name || r.report_name;
        setCatalogo(m);
      })
      .catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  const preparadas = useMemo(
    () => alertas.map((a) => prepararAlerta(a, catalogo)),
    [alertas, catalogo],
  );
  const ind = useMemo(() => indicadores(alertas), [alertas]);
  const visibles = useMemo(() => aplicarFiltro(preparadas, filtro), [preparadas, filtro]);

  const alternar = (clave) => setFiltro((f) => (f === clave ? 'todas' : clave));

  /* Mientras no haya datos —porque todavía carga o porque falló— los
     indicadores NO muestran cero. Una fila de ceros dice que no hay trabajo
     pendiente, y en esta pantalla esa es la diferencia entre irse tranquilo a
     casa y no. Un guión no afirma nada, que es lo correcto cuando no se sabe.

     Incluye el caso "cargando" y no sólo el error: el parpadeo de ceros dura
     poco, pero es igual de falso mientras dura. */
  async function exportar() {
    setBajando(true); setAviso('');
    try {
      const d = await api.get(`/alerts/export.xlsx?${queryDeExportacion({ vista, filtro })}`);
      if (d?.error) throw new Error(d.error);
      if (!d?.url) throw new Error('El backend no generó el archivo.');
      globalThis.open(d.url, '_blank', 'noopener');
      setAviso('Excel generado. Si no se abrió, revisá el bloqueo de ventanas emergentes.');
    } catch (e) {
      setAviso(`No se pudo generar el Excel: ${e?.message || 'error'}`);
    } finally {
      setBajando(false);
    }
  }

  const elegidas = visibles.filter((a) => seleccion.includes(a.alert_id));
  const sinDatos = (cargando || Boolean(error)) && alertas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta={vista === 'revisadas' ? 'Ya revisadas' : 'Alertas activas'}
             valor={n(ind.total)}
             pie={!sinDatos
               ? `${ind.reportes} reporte${ind.reportes === 1 ? '' : 's'}`
               : cargando ? 'leyendo…' : 'no se pudieron leer'} />
        <Kpi etiqueta="Prioridad 1" valor={n(ind.p1)} pie="puntaje ≥ 75 de 100"
             alPulsar={sinDatos ? undefined : () => alternar('p1')} activo={filtro === 'p1'} />
        <Kpi etiqueta="Sin caso" valor={n(ind.sinCaso)} pie="nadie las empezó"
             alPulsar={sinDatos ? undefined : () => alternar('sin_caso')} activo={filtro === 'sin_caso'} />
        <Kpi etiqueta="Sin asignar" valor={n(ind.sinAsignar)} pie="nadie las tomó"
             alPulsar={sinDatos ? undefined : () => alternar('sin_asignar')} activo={filtro === 'sin_asignar'} />
        {/* Se muestra siempre, incluso en cero: que el número esté a la vista
            es lo que hace que alguien note el día que deja de estarlo. */}
        <Kpi etiqueta="Sin puntaje" valor={n(ind.sinPuntaje)} pie="no se las evaluó"
             alPulsar={sinDatos ? undefined : () => alternar('sin_puntaje')} activo={filtro === 'sin_puntaje'} />
      </div>

      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {repartiendo && elegidas.length > 0 && (
        <Suspense fallback={<p className="wt-estado">Cargando…</p>}>
          <Reparto api={api} alertas={elegidas} usuarios={usuarios}
                   alCerrar={() => setRepartiendo(false)}
                   alTerminar={async (msg) => {
                     setRepartiendo(false); setSeleccion([]); setAviso(msg);
                     await cargar();
                   }} />
        </Suspense>
      )}

      <Tabla
        titulo={vista === 'revisadas' ? 'Alertas ya revisadas' : 'Bandeja de alertas'}
        columnas={[
          ...(lectura ? [] : [{
            clave: '_sel',
            titulo: '',
            ancho: '3%',
            buscable: false,
            ordenable: false,
            exportar: () => '',
            render: (a) => (
              <input type="checkbox" checked={seleccion.includes(a.alert_id)}
                     aria-label={`Elegir la alerta ${a.alert_id}`}
                     onChange={(e) => setSeleccion((s) => (
                       e.target.checked ? [...s, a.alert_id]
                                        : s.filter((x) => x !== a.alert_id)))} />
            ),
          }]),
          ...columnas(navegar),
        ]}
        filas={visibles}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(a) => a.alert_id}
        nombreExport="alertas-watchtower"
        porPagina={40}
        vacioTexto={filtro === 'todas'
          ? 'No hay alertas activas.'
          : `Ninguna alerta con el filtro «${FILTROS[filtro]?.etiqueta}».`}
        herramientas={
          <>
            <div className="wt-filtros">
              <button className="wt-filtro" aria-pressed={vista === 'activas'}
                      onClick={() => { setVista('activas'); setFiltro('todas'); }}>
                Activas
              </button>
              <button className="wt-filtro" aria-pressed={vista === 'revisadas'}
                      onClick={() => { setVista('revisadas'); setFiltro('todas'); }}>
                Ya revisadas
              </button>
              <span style={{ width: 1, alignSelf: 'stretch', background: 'var(--borde)' }} />
              {Object.entries(FILTROS).map(([clave, f]) => (
                <button
                  key={clave}
                  className="wt-filtro"
                  aria-pressed={filtro === clave}
                  onClick={() => setFiltro(clave)}
                >
                  {f.etiqueta}
                  {clave !== 'todas' && !sinDatos && (
                    <span className="wt-filtro-n">
                      {aplicarFiltro(preparadas, clave).length}
                    </span>
                  )}
                </button>
              ))}
            </div>
            {!lectura && seleccion.length > 0 && (
              <button className="wt-btn wt-btn-primario" onClick={() => setRepartiendo(true)}>
                Repartir {seleccion.length}
              </button>
            )}
            {seleccion.length > 0 && (
              <button className="wt-btn" onClick={() => setSeleccion([])}>Deseleccionar</button>
            )}
            {/* El Excel lo arma el backend con los filtros puestos, no el CSV
                de la tabla: trae todas las columnas del reporte de origen,
                que es lo que se manda afuera. */}
            <button className="wt-btn" onClick={exportar} disabled={bajando}>
              {bajando ? 'Generando…' : 'Excel'}
            </button>
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </>
        }
      />
    </>
  );
}
