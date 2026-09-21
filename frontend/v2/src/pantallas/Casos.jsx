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

function Estado({ caso }) {
  const d = ESTADOS_CASO[caso.status];
  return (
    <span style={{ color: d?.color || 'var(--texto-2)', fontWeight: 'var(--peso-medio)' }}>
      {d?.etiqueta || caso.status || '—'}
    </span>
  );
}

function columnas(navegar) {
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

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      // `status=all` porque el filtro se hace acá: cambiar de filtro no
      // debería costar un viaje a la API cuando son 89 filas.
      const d = await api.get('/cases?status=all');
      setCasos(d?.cases || []);
      setConfig(d?.sla_config || null);
      if (d?.warning) setError(`La API respondió con un aviso: ${d.warning}`);
    } catch (e) {
      setError(e?.message || 'No se pudieron cargar los casos.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const preparados = useMemo(() => casos.map(prepararCaso), [casos]);
  const ind = useMemo(() => indicadores(casos), [casos]);
  const cierre = useMemo(() => tiempoDeCierre(casos), [casos]);
  const visibles = useMemo(() => aplicarFiltro(preparados, filtro), [preparados, filtro]);

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

      <Tabla
        titulo="Casos"
        columnas={columnas(navegar)}
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
