/* ============================================================================
   Casos
   ----------------------------------------------------------------------------
   La lista con el semáforo del plazo. Los umbrales vienen del backend en
   `sla_config` y se muestran; no se escriben acá.

   SOBRE EL AVISO DE ARRIBA. Cuando todos los casos con reloj están vencidos,
   el semáforo deja de ordenar: una lista donde las 69 filas son rojas se lee
   igual que una lista sin colores. En vez de fingir un gradiente que no
   existe, se dice el número. Es la situación real hoy —medido: 69 de 69— y
   es información, no un adorno: significa que el plazo de 3 días no se está
   cumpliendo en ningún caso, que es un dato de gestión, no un detalle de la
   pantalla.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import { InsigniaSla } from '../comun/InsigniaSla.jsx';
import { hace } from '../comun/alertas.js';
import {
  FILTROS_CASO, aplicarFiltro, diasTexto, estaAbierto, indicadores,
  prepararCaso, tiempoDeCierre,
} from '../comun/casos.js';
import { ESTADOS_CASO } from '../dominio.js';
import {
  ETAPAS_ROS, avisoDelPlazo, correPlazo, etiquetaEtapa, filtrarPorRos, plazoDe,
  rosPorCaso,
} from '../comun/ros.js';

function Estado({ caso }) {
  const d = ESTADOS_CASO[caso.status];
  return (
    <span style={{ color: d?.color || 'var(--texto-2)', fontWeight: 'var(--peso-medio)' }}>
      {d?.etiqueta || caso.status || '—'}
    </span>
  );
}

const COLOR_ETAPA = {
  neutro: 'var(--texto-mute)',
  info: 'var(--g66-azul-texto)',
  medio: 'var(--nivel-medio-texto)',
  ok: 'var(--nivel-bajo-texto)',
  alto: 'var(--nivel-alto-texto)',
};

function EtapaRos({ ros, disponible }) {
  // CON EL REGISTRO CAÍDO NO SE DICE «SIN ROS». Eso afirmaría, fila por fila,
  // que ningún caso tiene reporte.
  const efectivo = disponible ? ros : { etapa: 'no_disponible' };
  const d = etiquetaEtapa(efectivo);
  const apagado = !efectivo || ['sin_ros', 'no_disponible'].includes(efectivo.etapa);
  const plazo = correPlazo(efectivo) ? plazoDe(efectivo) : null;
  // EL RELOJ PARADO NECESITA UNA EXPLICACIÓN. «Entregado a GEREO» para el
  // plazo, pero entregado no es reportado: la carga al regulador se decide en
  // Slack y no vuelve. Sin esto, una columna en silencio se lee como «llegó a
  // tiempo», que es justo lo que WatchTower ya no puede afirmar.
  const aviso = avisoDelPlazo(efectivo);
  const titulo = [
    efectivo?.folio && `${efectivo.folio}${efectivo.version ? ` · v${efectivo.version}` : ''}`,
    plazo?.desde && `cuenta desde ${plazo.desde}`,
    aviso,
  ].filter(Boolean).join(' · ');
  return (
    <>
      <span style={{ color: COLOR_ETAPA[d.color] || 'var(--texto-2)',
                     fontWeight: apagado ? 'inherit' : 'var(--peso-medio)' }}
            title={titulo}>
        {d.texto}
        {efectivo?.cuantos > 1 && (
          <span style={{ color: 'var(--texto-mute)',
                         fontWeight: 'inherit' }}>
            {' '}+{efectivo.cuantos - 1}
          </span>
        )}
      </span>
      {plazo && (
        <span style={{ display: 'block', fontSize: 'var(--texto-xs)',
                       /* Sin plazo definido no se pinta: el verde afirmaría
                          que hay tiempo de sobra sin que nadie lo sepa. */
                       color: COLOR_ETAPA[plazo.semaforo] || 'var(--texto-mute)' }}>
          {plazo.texto}
        </span>
      )}
      {aviso && (
        <span style={{ display: 'block', fontSize: 'var(--texto-xs)',
                       color: 'var(--texto-mute)' }}
              title={aviso}>
          sin acuse del regulador
        </span>
      )}
    </>
  );
}

function columnas(navegar, hayRos) {
  return [
    {
      clave: 'entity_id',
      titulo: 'Cliente',
      ancho: '15%',
      /* El id arriba y el nombre debajo, y NO al revés.
         Sólo 41 de los 89 casos traen `entity_name`; el id lo traen todos.
         Poniendo el nombre primero, casi la mitad de las filas encabezarían
         con un guión. Y el `title` no sirve de reemplazo: 72 de 89 son
         "Caso: Alerta: <reporte>", 22 textos distintos para 89 casos — se
         vería como un nombre de cliente sin identificar a nadie. */
      render: (c) => (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
          <span className="mono" style={{ color: 'var(--texto)' }}>{c.entity_id || '—'}</span>
          {c.entity_name && (
            <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
              {c.entity_name}
            </span>
          )}
        </span>
      ),
    },
    {
      clave: 'report_name',
      titulo: 'Origen',
      ancho: '15%',
      render: (c) => (c.report_name
        ? <span className="mono" style={{ fontSize: 'var(--texto-xs)' }}>{c.report_name}</span>
        : <span style={{ color: 'var(--texto-mute)' }}>manual</span>),
    },
    { clave: '_estado', titulo: 'Estado', ancho: '9%', render: (c) => <Estado caso={c} /> },
    {
      clave: '_etapaRos',
      titulo: 'Etapa ROS',
      ancho: '10%',
      render: (c) => <EtapaRos ros={c._ros} disponible={hayRos} />,
    },
    {
      clave: '_slaOrden',
      titulo: 'Plazo',
      ancho: '15%',
      buscable: false,
      render: (c) => <InsigniaSla caso={c} />,
      exportar: (c) => c._sla,
    },
    {
      clave: '_dias',
      titulo: 'Abierto',
      tipo: 'numero',
      ancho: '8%',
      buscable: false,
      render: (c) => (
        <span title={c.created_at ? `Creado ${c.created_at} UTC` : ''}>
          {diasTexto(c._dias)}
        </span>
      ),
    },
    {
      clave: '_contactos',
      titulo: 'Contactos',
      tipo: 'numero',
      ancho: '9%',
      buscable: false,
      // Cero contactos en un caso abierto no es un dato neutro: es el
      // pendiente más concreto que tiene esa fila.
      render: (c) => (c._contactos === 0 && estaAbierto(c) && c.sla_aplica
        ? <span style={{ color: 'var(--nivel-alto-texto)', fontWeight: 'var(--peso-medio)' }}>
            sin contactar
          </span>
        : c._contactos),
    },
    {
      clave: '_notas',
      titulo: 'Notas',
      tipo: 'numero',
      ancho: '6%',
      buscable: false,
    },
    {
      clave: '_analista',
      titulo: 'Analista',
      ancho: '12%',
      render: (c) => (c._analista
        ? c._analista.replace('@global66.com', '')
        : <span style={{ color: 'var(--nivel-alto-texto)' }}>sin asignar</span>),
    },
    {
      clave: 'updated_at',
      titulo: 'Movido',
      ancho: '9%',
      buscable: false,
      render: (c) => <span title={c.updated_at}>{hace(c.updated_at)}</span>,
    },
    {
      clave: 'case_id',
      titulo: '',
      ancho: '5%',
      ordenable: false,
      buscable: false,
      render: (c) => (
        <button className="wt-btn" onClick={() => navegar('caso', [c.case_id])}>Abrir</button>
      ),
      exportar: () => '',
    },
  ];
}

export function Casos({ api, navegar }) {
  const [casos, setCasos] = useState([]);
  const [config, setConfig] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [filtro, setFiltro] = useState('abiertos');
  const [ros, setRos] = useState([]);
  // `null` mientras no se sabe; `false` si el registro no se pudo leer. La
  // diferencia importa: con `false`, la columna dice «No disponible» en vez
  // de «Sin ROS».
  const [rosDisponible, setRosDisponible] = useState(true);
  const [filtroEtapa, setFiltroEtapa] = useState('');
  const [filtroPais, setFiltroPais] = useState('');

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      // `status=all` porque el filtro se hace acá: cambiar de filtro no
      // debería costar un viaje a la API cuando son 89 filas.
      // Los dos en paralelo: la etapa del ROS vive en el ROS y la lista
      // muestra casos. Se cruzan acá y no en `/cases`, que lo usan varias
      // pantallas y encarecerlo para todas por una columna no se justifica.
      //
      // El registro de ROS es chico; si algún día deja de serlo, esto se
      // mueve al backend.
      const [d, dr] = await Promise.all([
        api.get('/cases?status=all'),
        // Que falle el ROS no puede dejar sin casos la pantalla. Pero sí hay
        // que DECIRLO: sin esto, un registro caído haría que todas las filas
        // afirmen «Sin ROS».
        api.get('/ros').then((x) => x, () => null),
      ]);
      setCasos(d?.cases || []);
      setRos(dr?.ros || []);
      // `dr !== null` sólo cubre el error de red o HTTP. `listar_ros` atrapa
      // su propia excepción y devuelve 200 con `{ros: [], warning}` — que es
      // el modo de falla MÁS probable, y leído sin el `warning` dice «hay
      // cero ROS» en vez de «no se pudo leer».
      setRosDisponible(dr !== null && !dr.warning);
      setConfig(d?.sla_config || null);
      if (d?.warning) setError(`La API respondió con un aviso: ${d.warning}`);
    } catch (e) {
      setError(e?.message || 'No se pudieron cargar los casos.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const porCaso = useMemo(() => rosPorCaso(ros), [ros]);
  const preparados = useMemo(
    () => casos.map((c) => ({ ...prepararCaso(c), _ros: porCaso[c.case_id] })),
    [casos, porCaso]);
  const ind = useMemo(() => indicadores(casos), [casos]);
  const cierre = useMemo(() => tiempoDeCierre(casos), [casos]);
  const visibles = useMemo(
    () => filtrarPorRos(aplicarFiltro(preparados, filtro), porCaso,
                        { etapa: filtroEtapa, regulador: filtroPais }),
    [preparados, filtro, porCaso, filtroEtapa, filtroPais]);

  /* Sólo los reguladores que de verdad aparecen: ofrecer «Colombia» cuando no
     hay ningún ROS colombiano manda a filtrar a la nada. */
  const reguladoresPresentes = useMemo(() => {
    const s = new Set(Object.values(porCaso).map((r) => r.regulador).filter(Boolean));
    return [...s].sort();
  }, [porCaso]);

  const sinDatos = (cargando || Boolean(error)) && casos.length === 0;
  const n = (v) => (sinDatos ? '—' : v);
  const alternar = (c) => setFiltro((f) => (f === c ? 'todos' : c));

  /* ¿Todos los que tienen reloj están vencidos? */
  const conReloj = casos.filter((c) => c.sla_aplica && estaAbierto(c));
  const todosVencidos = conReloj.length > 0 &&
    conReloj.every((c) => c.sla_estado === 'vencido');

  const plazo = config
    ? `${config.horas_recontacto} h para recontactar · ${config.horas_cierre} h para cerrar`
    : '';

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Casos abiertos" valor={n(ind.abiertos)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer')
                           : `${ind.total} en total`} />
        <Kpi etiqueta="Vencidos" valor={n(ind.vencidos)} pie={plazo || 'pasaron el plazo'}
             alPulsar={sinDatos ? undefined : () => alternar('vencidos')}
             activo={filtro === 'vencidos'} />
        <Kpi etiqueta="Sin contactar" valor={n(ind.porContactar)} pie="nunca se les escribió"
             alPulsar={sinDatos ? undefined : () => alternar('sin_contactar')}
             activo={filtro === 'sin_contactar'} />
        <Kpi etiqueta="Sin asignar" valor={n(ind.sinAsignar)} pie="nadie los tomó"
             alPulsar={sinDatos ? undefined : () => alternar('sin_asignar')}
             activo={filtro === 'sin_asignar'} />
        <Kpi etiqueta="Cierre típico" valor={sinDatos || cierre.mediana === null
               ? '—' : diasTexto(cierre.mediana)}
             pie={cierre.n ? `mediana de ${cierre.n} cerrados · ${cierre.enPlazo} en plazo` : 'ninguno cerrado'} />
      </div>

      {todosVencidos && (
        <p className="wt-nota wt-nota-alarma">
          <strong>Los {conReloj.length} casos con plazo están vencidos.</strong>{' '}
          Ninguno en verde ni en amarillo, así que el semáforo no sirve hoy para
          priorizar: lo que ordena es hace cuánto venció cada uno, de{' '}
          {diasTexto(Math.min(...conReloj.map((c) => c.sla_dias)))} a{' '}
          {diasTexto(Math.max(...conReloj.map((c) => c.sla_dias)))} abiertos.
        </p>
      )}

      {/* Los filtros de ROS SÓLO aparecen cuando hay ROS. Mostrarlos con el
          registro vacío ofrece filtrar por algo que no existe y hace pensar
          que la pantalla está rota. */}
      {!rosDisponible && !cargando && (
        <p className="wt-nota wt-nota-alarma">
          <strong>No se pudo leer el registro de ROS.</strong> La columna
          «Etapa ROS» no muestra nada en esta carga — no significa que los
          casos no tengan reporte. Lo demás de la pantalla está al día.
        </p>
      )}

      {rosDisponible && Object.keys(porCaso).length > 0 && (
        <div style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center',
                      marginBottom: 'var(--e-3)', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            ROS:
          </span>
          <select className="wt-input" style={{ width: 'auto' }}
                  value={filtroEtapa} onChange={(e) => setFiltroEtapa(e.target.value)}>
            <option value="">Todas las etapas</option>
            {Object.entries(ETAPAS_ROS).map(([clave, d]) => (
              <option key={clave} value={clave}>{d.texto}</option>
            ))}
          </select>
          {reguladoresPresentes.length > 1 && (
            <select className="wt-input" style={{ width: 'auto' }}
                    value={filtroPais} onChange={(e) => setFiltroPais(e.target.value)}>
              <option value="">Todos los reguladores</option>
              {reguladoresPresentes.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          )}
          {(filtroEtapa || filtroPais) && (
            <button className="wt-btn" type="button"
                    onClick={() => { setFiltroEtapa(''); setFiltroPais(''); }}>
              Quitar el filtro de ROS
            </button>
          )}
        </div>
      )}

      <Tabla
        titulo="Casos"
        columnas={columnas(navegar, rosDisponible)}
        filas={visibles}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(c) => c.case_id}
        nombreExport="casos-watchtower"
        porPagina={40}
        vacioTexto={`Ningún caso con el filtro «${FILTROS_CASO[filtro]?.etiqueta || filtro}».`}
        herramientas={
          <>
            <div className="wt-filtros">
              {Object.entries(FILTROS_CASO).map(([clave, f]) => (
                <button key={clave} className="wt-filtro" aria-pressed={filtro === clave}
                        onClick={() => setFiltro(clave)}>
                  {f.etiqueta}
                  {!sinDatos && (
                    <span className="wt-filtro-n">{aplicarFiltro(preparados, clave).length}</span>
                  )}
                </button>
              ))}
            </div>
            <button className="wt-btn" onClick={() => navegar('kanban')}>Ver tablero</button>
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </>
        }
      />
    </>
  );
}
