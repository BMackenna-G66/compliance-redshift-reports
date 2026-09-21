/* ============================================================================
   Relevo · partners
   ----------------------------------------------------------------------------
   El circuito de pedirle documentación a un cliente porque un corresponsal la
   pidió.

   LO PRIMERO QUE SE VE ES SI LOS ENVÍOS ESTÁN PRENDIDOS, y eso no es un
   detalle de configuración: hoy los ocho interruptores de salida están
   apagados. Una bandeja con 230 casos «listos para pedir» que en realidad no
   puede pedir nada es una trampa — el analista trabaja, no pasa nada, y
   ningún error lo explica. Por eso el aviso va arriba de todo y en rojo.

   PRENDER UN ENVÍO MANDA CORREOS A CLIENTES REALES. Por eso ese interruptor
   —y sólo ese— pide confirmación escrita con lo que va a pasar.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  ESTADOS_MANUALES, FILTROS_RELEVO, aplicarFiltro, estadoDeEnvios, etapaDe,
  faltantesTexto, hace, indicadores, nombreEstado, porEtapa, porTipo,
} from '../comun/relevo.js';
import { soloLectura } from '../permisos.js';

/* ── El aviso de envíos ─────────────────────────────────────────────────── */

function AvisoEnvios({ estado, alVerInterruptores }) {
  if (estado.activo) {
    return (
      <p className="wt-nota">
        <strong>Los envíos están activos.</strong> Los pedidos que se disparen desde acá
        llegan a clientes reales.
        {estado.partnersEncendidos < estado.partnersTotal && (
          <> {estado.partnersTotal - estado.partnersEncendidos} partner
            {estado.partnersTotal - estado.partnersEncendidos === 1 ? '' : 's'} sigue
            {estado.partnersTotal - estado.partnersEncendidos === 1 ? '' : 'n'} apagado
            {estado.partnersTotal - estado.partnersEncendidos === 1 ? '' : 's'}.</>
        )}
        <button className="wt-btn" style={{ marginLeft: 8, padding: '2px 8px' }}
                onClick={alVerInterruptores}>Ver interruptores</button>
      </p>
    );
  }
  return (
    <p className="wt-nota wt-nota-alarma">
      <strong>Los envíos están apagados.</strong> Ningún pedido sale, ni a mano ni por
      lote. Se puede trabajar la bandeja y registrar estados, pero al cliente no le
      llega nada.
      <button className="wt-btn" style={{ marginLeft: 8, padding: '2px 8px' }}
              onClick={alVerInterruptores}>Ver interruptores</button>
    </p>
  );
}

/* ── El circuito ────────────────────────────────────────────────────────── */

function Circuito({ etapas, total }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Dónde están los casos</h2>
      </header>
      <div className="wt-cuerpo-carta">
        <div className="wt-circuito">
          {etapas.map((e) => (
            <div key={e.n} className="wt-paso" title={e.descripcion}>
              <span className="wt-paso-n" style={{ color: e.color }}>{e.n_casos}</span>
              <span className="wt-paso-etiqueta">{e.etiqueta}</span>
              <span className="wt-paso-barra"
                    style={{ background: e.color,
                             width: total ? `${(e.n_casos / total) * 100}%` : '0%' }} />
            </div>
          ))}
        </div>
        <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)',
                    color: 'var(--texto-mute)' }}>
          «Falta un dato» no es un caso atrasado: es uno que no se puede trabajar hasta
          arreglar el dato (cliente no ubicado, sin correo, o pedido que no se entendió).
        </p>
      </div>
    </section>
  );
}

/* ── Los interruptores ──────────────────────────────────────────────────── */

function Interruptores({ datos, lectura, alCambiar, guardando, alCerrar }) {
  const grupos = porTipo(datos?.interruptores || []);
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Interruptores</h2>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <div className="wt-cuerpo-carta">
        {grupos.map((g) => (
          <div key={g.tipo} style={{ marginBottom: 'var(--e-4)' }}>
            <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                         letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                         margin: '0 0 var(--e-2)' }}>
              {g.etiqueta}
            </h3>
            {g.items.map((i) => (
              <div key={i.clave} className="wt-interruptor">
                <span className="wt-insignia"
                      style={i.valor
                        ? { color: 'var(--nivel-bajo-texto)', background: 'var(--nivel-bajo-tenue)' }
                        : { color: 'var(--estado-error-texto)', background: 'var(--estado-error-fondo)' }}>
                  {i.valor ? 'ON' : 'OFF'}
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 'var(--texto-base)', fontWeight: 'var(--peso-medio)' }}>
                    {i.etiqueta || i.clave}
                  </div>
                  <div style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)',
                                whiteSpace: 'normal' }}>
                    {i.valor ? i.al_apagar : i.descripcion}
                  </div>
                </div>
                {!lectura && (
                  <button className="wt-btn" disabled={guardando === i.clave}
                          onClick={() => alCambiar(i)}>
                    {guardando === i.clave ? '…' : i.valor ? 'Apagar' : 'Prender'}
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── La tabla ───────────────────────────────────────────────────────────── */

function columnas(alAbrir) {
  return [
    {
      clave: 'partner',
      titulo: 'Partner',
      ancho: '11%',
    },
    {
      clave: 'cliente_id',
      titulo: 'Cliente',
      ancho: '14%',
      render: (c) => (c.cliente_id
        ? <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
            <span className="mono" style={{ color: 'var(--texto)' }}>{c.cliente_id}</span>
            {c.cliente_nombre && (
              <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                {c.cliente_nombre}
              </span>
            )}
          </span>
        : <span style={{ color: 'var(--nivel-critico-texto)' }}>sin ubicar</span>),
    },
    {
      clave: 'estado',
      titulo: 'Estado',
      ancho: '14%',
      render: (c) => {
        const e = etapaDe(c);
        return (
          <span style={{ color: e?.color || 'var(--texto-2)',
                         fontWeight: 'var(--peso-medio)' }}>
            {nombreEstado(c.estado)}
          </span>
        );
      },
      exportar: (c) => nombreEstado(c.estado),
    },
    {
      clave: '_faltantes',
      titulo: 'Qué falta',
      render: (c) => (c._faltantes
        ? <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 320,
                         fontSize: 'var(--texto-xs)' }}>
            {c._faltantes}
          </span>
        : <span style={{ color: 'var(--texto-mute)' }}>—</span>),
    },
    {
      clave: 'intentos',
      titulo: 'Intentos',
      tipo: 'numero',
      ancho: '8%',
      buscable: false,
      // La política es 3 intentos; al tercero el caso queda agotado.
      render: (c) => (c.agotado
        ? <span style={{ color: 'var(--estado-error-texto)', fontWeight: 'var(--peso-medio)' }}>
            {c.intentos} · agotado
          </span>
        : c.intentos),
    },
    {
      clave: 'proximo_contacto',
      titulo: 'Próximo contacto',
      ancho: '13%',
      buscable: false,
      render: (c) => (c.vencido
        ? <span style={{ color: 'var(--nivel-critico-texto)', fontWeight: 'var(--peso-medio)' }}>
            vencido
          </span>
        : c.proximo_contacto || <span style={{ color: 'var(--texto-mute)' }}>—</span>),
    },
    {
      clave: 'ultima',
      titulo: 'Último correo',
      ancho: '11%',
      buscable: false,
      render: (c) => <span title={c.ultima}>{hace(c.ultima)}</span>,
    },
    {
      clave: 'id',
      titulo: '',
      ancho: '7%',
      ordenable: false,
      buscable: false,
      render: (c) => (
        <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => alAbrir(c)}>Abrir</button>
      ),
      exportar: () => '',
    },
  ];
}

/* ── El detalle ─────────────────────────────────────────────────────────── */

function Detalle({ caso, lectura, alFijarEstado, guardando, alCerrar }) {
  const [estado, setEstado] = useState('');
  const e = etapaDe(caso);

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">
          {caso.cliente_nombre || `Cliente ${caso.cliente_id || '(sin ubicar)'}`}
        </h2>
        <span className="wt-insignia"
              style={{ color: e?.color || 'var(--texto-2)', background: 'var(--superficie-3)' }}>
          {nombreEstado(caso.estado)}
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <div className="wt-cuerpo-carta"
           style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 'var(--e-4)' }}>
        <dl className="wt-datos">
          <dt>Caso</dt><dd className="mono" style={{ wordBreak: 'break-all' }}>{caso.id}</dd>
          <dt>Partner</dt><dd>{caso.partner}{caso.caso_partner && ` · ${caso.caso_partner}`}</dd>
          {caso.cliente_correo && <><dt>Correo</dt><dd>{caso.cliente_correo}</dd></>}
          <dt>Transacciones</dt><dd>{caso.n_transacciones}</dd>
          <dt>Correos</dt><dd>{caso.n_correos}</dd>
          <dt>Intentos</dt>
          <dd>
            {caso.intentos}
            {caso.agotado && (
              <span style={{ color: 'var(--estado-error-texto)' }}> · agotado</span>
            )}
          </dd>
          {caso.plazo && <><dt>Plazo del partner</dt><dd>{caso.plazo}</dd></>}
          <dt>Primer correo</dt><dd>{caso.primera || '—'}</dd>
          <dt>Último correo</dt><dd>{caso.ultima || '—'}</dd>
          {(caso.faltantes || []).length > 0 && (
            <>
              <dt>Qué falta</dt>
              <dd>
                <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
                  {caso.faltantes.map((f) => (
                    <li key={f.item}>
                      {f.es || f.item}
                      <span className="mono" style={{ fontSize: 'var(--texto-xs)',
                                                      color: 'var(--texto-mute)' }}>
                        {' '}{f.item}
                      </span>
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>

        <div className="wt-acciones">
          {lectura ? (
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
              Tu perfil es de consulta: podés ver el caso, pero no cambiarle el estado.
            </p>
          ) : (
            <>
              <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Fijar el estado a mano
                <select className="wt-input" style={{ display: 'block', width: '100%', marginTop: 4 }}
                        value={estado} onChange={(ev) => setEstado(ev.target.value)}>
                  <option value="">Elegir…</option>
                  {ESTADOS_MANUALES.map((s) => (
                    <option key={s} value={s}>{nombreEstado(s)}</option>
                  ))}
                </select>
              </label>
              <button className="wt-btn wt-btn-primario"
                      disabled={!estado || guardando}
                      onClick={() => alFijarEstado(caso, estado)}>
                {guardando ? 'Guardando…' : 'Fijar el estado'}
              </button>
              {/* Los cuatro diagnósticos no están en la lista a propósito.
                  Decirlo evita que alguien los busque y crea que faltan. */}
              <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                «Sin cliente», «sin correo» y «sin requerimiento» no se pueden fijar a mano:
                no son etapas del trabajo sino datos que faltan, y ponerlos tapa el
                diagnóstico en vez de arreglarlo.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/* ── La pantalla ────────────────────────────────────────────────────────── */

export function Relevo({ api, perfil, email }) {
  const [casos, setCasos] = useState([]);
  const [interruptores, setInterruptores] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [filtro, setFiltro] = useState('accionables');
  const [abierto, setAbierto] = useState(null);
  const [verInterruptores, setVerInterruptores] = useState(false);
  const [guardando, setGuardando] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    const [c, i] = await Promise.allSettled([
      api.get('/relevo/casos'),
      api.get('/relevo/interruptores'),
    ]);
    if (c.status === 'fulfilled') setCasos(c.value?.casos || []);
    if (i.status === 'fulfilled') setInterruptores(i.value);
    const fallos = [['casos', c], ['interruptores', i]]
      .filter(([, x]) => x.status === 'rejected')
      .map(([n, x]) => `${n} (${x.reason?.message || 'error'})`);
    setError(fallos.length ? `No se pudo cargar: ${fallos.join(' · ')}` : '');
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const preparados = useMemo(
    () => casos.map((c) => ({ ...c, _faltantes: faltantesTexto(c) })),
    [casos],
  );
  const ind = useMemo(() => indicadores(casos), [casos]);
  const etapas = useMemo(() => porEtapa(casos), [casos]);
  const envios = useMemo(() => estadoDeEnvios(interruptores), [interruptores]);
  const visibles = useMemo(() => aplicarFiltro(preparados, filtro), [preparados, filtro]);

  async function fijarEstado(caso, estado) {
    setGuardando('estado'); setError(''); setAviso('');
    try {
      await api.post(`/relevo/casos/${encodeURIComponent(caso.id)}/accion`, {
        accion: 'estado_manual', estado, quien: email,
      });
      setAviso(`Estado fijado en «${nombreEstado(estado)}».`);
      setAbierto(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo fijar el estado.');
    } finally {
      setGuardando('');
    }
  }

  async function cambiarInterruptor(i) {
    const prendiendo = !i.valor;
    // Prender un envío manda correos a clientes reales. Es la única acción de
    // esta pantalla que sale del sistema, así que es la única que pregunta.
    if (prendiendo && i.tipo === 'salida') {
      const ok = globalThis.confirm(
        `Prender «${i.etiqueta || i.clave}» hace que los pedidos LLEGUEN A CLIENTES REALES.\n\n` +
        '¿Seguro que el desarrollo ya está terminado?',
      );
      if (!ok) return;
    }
    setGuardando(i.clave); setError(''); setAviso('');
    try {
      await api.post('/relevo/interruptores', {
        clave: i.clave, valor: prendiendo, quien: email,
      });
      setAviso(`«${i.etiqueta || i.clave}» quedó ${prendiendo ? 'prendido' : 'apagado'}.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo cambiar el interruptor.');
    } finally {
      setGuardando('');
    }
  }

  const sinDatos = (cargando || Boolean(error)) && casos.length === 0;
  const n = (v) => (sinDatos ? '—' : v);
  const alternar = (c) => setFiltro((f) => (f === c ? 'todos' : c));

  return (
    <>
      {interruptores && (
        <AvisoEnvios estado={envios} alVerInterruptores={() => setVerInterruptores((v) => !v)} />
      )}

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {verInterruptores && interruptores && (
        <Interruptores datos={interruptores} lectura={lectura} guardando={guardando}
                       alCambiar={cambiarInterruptor}
                       alCerrar={() => setVerInterruptores(false)} />
      )}

      <div className="wt-kpis">
        <Kpi principal etiqueta="Casos" valor={n(ind.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer')
                           : `${ind.partners} partners`} />
        <Kpi etiqueta="Por pedir" valor={n(ind.porPedir)} pie="cliente ubicado, falta pedirle"
             alPulsar={sinDatos ? undefined : () => alternar('por_pedir')}
             activo={filtro === 'por_pedir'} />
        <Kpi etiqueta="Falta un dato" valor={n(ind.trabados)} pie="no se pueden trabajar"
             alPulsar={sinDatos ? undefined : () => alternar('trabados')}
             activo={filtro === 'trabados'} />
        <Kpi etiqueta="Vencidos" valor={n(ind.vencidos)} pie="toca recontactar"
             alPulsar={sinDatos ? undefined : () => alternar('vencidos')}
             activo={filtro === 'vencidos'} />
        <Kpi etiqueta="Agotados" valor={n(ind.agotados)} pie="3 intentos sin respuesta" />
      </div>

      {!sinDatos && <Circuito etapas={etapas} total={ind.total} />}

      {abierto && (
        <Detalle caso={abierto} lectura={lectura} guardando={guardando === 'estado'}
                 alFijarEstado={fijarEstado} alCerrar={() => setAbierto(null)} />
      )}

      <Tabla
        titulo="Casos de relevo"
        columnas={columnas(setAbierto)}
        filas={visibles}
        cargando={cargando}
        error=""
        alReintentar={cargar}
        claveFila={(c) => c.id}
        nombreExport="relevo-watchtower"
        porPagina={40}
        vacioTexto={`Ningún caso con el filtro «${FILTROS_RELEVO[filtro]?.etiqueta || filtro}».`}
        herramientas={
          <>
            <div className="wt-filtros">
              {Object.entries(FILTROS_RELEVO).map(([clave, f]) => (
                <button key={clave} className="wt-filtro" aria-pressed={filtro === clave}
                        onClick={() => setFiltro(clave)}>
                  {f.etiqueta}
                  {!sinDatos && (
                    <span className="wt-filtro-n">{aplicarFiltro(preparados, clave).length}</span>
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
