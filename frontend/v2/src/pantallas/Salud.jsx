/* ============================================================================
   Salud del módulo
   ----------------------------------------------------------------------------
   Pantalla nueva: no existe en el WatchTower actual.

   PARA QUÉ SIRVE. Media docena de cosas pueden estar apagadas o caídas sin
   que ninguna pantalla lo diga: el cluster pausado, los envíos de relevo en
   OFF, la ingesta de correo detenida, la priorización automática apagada,
   `GET /flags` sin desplegar. Cada una se nota tarde y en otro lado — «no me
   llegan casos nuevos», «el reporte no corre», «le escribí al cliente y no
   le llegó».

   Acá están todas juntas, y cada una dice QUÉ PASA SI ESTÁ ASÍ. Un tablero
   de luces verdes que no explica qué significa una roja no sirve de nada.

   LO QUE NO HACE: no arregla. Cada cosa se cambia en su pantalla, y desde
   acá se enlaza. Un botón de «prender todo» sería justo lo contrario de lo
   que esta pantalla busca — entender antes de tocar.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { Kpi } from '../comun/Kpi.jsx';
import { clusterEnMovimiento, estadoCluster } from '../comun/admin.js';
import { estadoDeEnvios } from '../comun/relevo.js';
import { hace } from '../comun/alertas.js';

/* Los tres estados posibles de una comprobación. `aviso` no es un error: es
   algo apagado a propósito que igual conviene tener a la vista. */
const TONO = {
  ok:     { etiqueta: 'OK',       color: 'var(--nivel-bajo-texto)',   fondo: 'var(--nivel-bajo-tenue)' },
  aviso:  { etiqueta: 'Apagado',  color: 'var(--nivel-alto-texto)',   fondo: 'var(--nivel-alto-tenue)' },
  malo:   { etiqueta: 'Falla',    color: 'var(--estado-error-texto)', fondo: 'var(--estado-error-fondo)' },
  nose:   { etiqueta: 'Sin datos', color: 'var(--texto-mute)',        fondo: 'var(--superficie-3)' },
};

function Chequeo({ nombre, tono, detalle, consecuencia, donde, alIr }) {
  const t = TONO[tono] || TONO.nose;
  return (
    <div className="wt-chequeo">
      <span className="wt-insignia" style={{ color: t.color, background: t.fondo }}>
        {t.etiqueta}
      </span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 'var(--texto-base)', fontWeight: 'var(--peso-medio)' }}>
          {nombre}
        </div>
        <div style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-2)', whiteSpace: 'normal' }}>
          {detalle}
        </div>
        {/* Lo que de verdad importa: qué se rompe si está así. */}
        {consecuencia && (
          <div style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)',
                        whiteSpace: 'normal', marginTop: 2 }}>
            {consecuencia}
          </div>
        )}
      </div>
      {donde && (
        <button className="wt-btn" style={{ flex: 'none' }} onClick={alIr}>
          Ir
        </button>
      )}
    </div>
  );
}

export function Salud({ api, navegar }) {
  const [datos, setDatos] = useState({});
  const [cargando, setCargando] = useState(true);

  const cargar = useCallback(async () => {
    setCargando(true);
    /* Todas en paralelo y con `allSettled`: si una falla, las demás se
       muestran igual. Una pantalla de salud que se cae entera porque un
       endpoint no contestó es la ironía más inútil posible. */
    const [cluster, relevo, salud, auto, flags] = await Promise.allSettled([
      api.get('/cluster/status'),
      api.get('/relevo/interruptores'),
      api.get('/relevo/salud'),
      api.get('/alert-prioritization/settings'),
      api.crudo('GET', '/flags'),
    ]);
    setDatos({
      cluster: cluster.status === 'fulfilled' ? cluster.value : null,
      clusterError: cluster.status === 'rejected' ? cluster.reason?.message : '',
      relevo: relevo.status === 'fulfilled' ? relevo.value : null,
      relevoError: relevo.status === 'rejected' ? relevo.reason?.message : '',
      salud: salud.status === 'fulfilled' ? salud.value : null,
      saludError: salud.status === 'rejected' ? salud.reason?.message : '',
      auto: auto.status === 'fulfilled' ? auto.value : null,
      autoError: auto.status === 'rejected' ? auto.reason?.message : '',
      flags: flags.status === 'fulfilled' ? flags.value : null,
    });
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const chequeos = [];

  /* ── Cluster ── */
  {
    const e = estadoCluster(datos.cluster?.status);
    chequeos.push({
      nombre: 'Redshift',
      tono: datos.clusterError ? 'malo' : !e ? 'nose' : e.consulta ? 'ok' : 'aviso',
      detalle: datos.clusterError || (e ? e.etiqueta : datos.cluster?.status || 'sin respuesta'),
      consecuencia: e?.consulta
        ? 'Los reportes y la ficha del cliente consultan sin espera adicional.'
        : clusterEnMovimiento(datos.cluster?.status)
          ? 'Está cambiando de estado; lo que se lance ahora espera.'
          : 'Pausado. La primera consulta lo despierta, pero tarda varios minutos. '
            + 'Es lo normal fuera de 04:00–18:30.',
      donde: 'admin_cluster',
    });
  }

  /* ── Envíos de relevo ── */
  {
    const env = estadoDeEnvios(datos.relevo);
    chequeos.push({
      nombre: 'Envío de correos a clientes (relevo)',
      tono: datos.relevoError ? 'malo' : !datos.relevo ? 'nose' : env.activo ? 'ok' : 'aviso',
      detalle: datos.relevoError
        || (env.activo
          ? `Activo · ${env.partnersEncendidos} de ${env.partnersTotal} partners prendidos`
          : `Apagado · ${env.apagados} interruptores de salida en OFF`),
      consecuencia: env.activo
        ? 'Los pedidos llegan a clientes reales.'
        : 'Se puede trabajar la bandeja, pero al cliente no le llega nada. '
          + 'Es lo esperado mientras se termina el desarrollo.',
      donde: 'relevo',
    });
  }

  /* ── Procesos de relevo ── */
  {
    const s = datos.salud;
    const apagados = (datos.relevo?.procesos_apagados || []).length;
    chequeos.push({
      nombre: 'Ingesta de correo (relevo)',
      tono: datos.saludError ? 'malo' : !s ? 'nose' : s.ingesta?.arrancada ? 'ok' : 'aviso',
      detalle: datos.saludError
        || (s ? `${s.ingesta?.arrancada ? 'Arrancada' : 'Detenida'} · último snapshot ${hace(s.snapshot_generado_en)}`
              : 'sin respuesta'),
      consecuencia: s?.ingesta?.arrancada
        ? `${(s.conteos?.mensajes ?? 0).toLocaleString('es-CL')} mensajes leídos · `
          + `${s.conteos?.clientes_en_cache ?? 0} clientes resueltos`
        : 'No entran casos nuevos. El historyId de Gmail caduca en ~1 semana: '
          + 'si se apaga más que eso hay que resincronizar.',
      donde: 'relevo',
    });
    if (apagados) {
      chequeos.push({
        nombre: 'Procesos internos de relevo',
        tono: 'aviso',
        detalle: `${apagados} apagado${apagados === 1 ? '' : 's'}`,
        consecuencia: 'Alguno de los procesos del circuito está detenido.',
        donde: 'relevo',
      });
    }
  }

  /* ── Credenciales de Gmail ── */
  if (datos.salud) {
    const ok = datos.salud.gmail?.credenciales_completas;
    chequeos.push({
      nombre: 'Credenciales de la casilla',
      tono: ok ? 'ok' : 'malo',
      detalle: ok ? 'Completas' : 'Incompletas',
      consecuencia: ok
        ? 'La casilla se puede leer y responder.'
        : 'Sin credenciales no se lee la casilla ni se responde: el módulo queda ciego.',
    });
  }

  /* ── Priorización automática ── */
  chequeos.push({
    nombre: 'Priorización automática de alertas',
    tono: datos.autoError ? 'malo' : !datos.auto ? 'nose' : datos.auto.enabled ? 'ok' : 'aviso',
    detalle: datos.autoError || (datos.auto?.enabled ? 'Prendida' : 'Apagada'),
    consecuencia: datos.auto?.enabled
      ? 'Las alertas del día se puntúan y reparten solas.'
      : 'Las alertas del día hay que puntuarlas y repartirlas a mano.',
    donde: 'admin_auto',
  });

  /* ── El endpoint de flags ── */
  {
    const r = datos.flags;
    const ok = r?.ok;
    chequeos.push({
      nombre: 'GET /flags (matriz de banderas)',
      tono: cargando ? 'nose' : ok ? 'ok' : 'aviso',
      detalle: ok ? `${r.datos?.flags?.length || 0} banderas · máximo ${r.datos?.maximo}`
                  : `La API respondió ${r?.status ?? '—'}`,
      consecuencia: ok
        ? 'La pantalla de flags muestra los pesos del módulo de scoring.'
        : 'El endpoint está escrito pero no desplegado. La pantalla de flags avisa en '
          + 'vez de mostrar pesos de memoria.',
      donde: 'flags',
    });
  }

  const malos = chequeos.filter((c) => c.tono === 'malo').length;
  const avisos = chequeos.filter((c) => c.tono === 'aviso').length;
  const oks = chequeos.filter((c) => c.tono === 'ok').length;

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Comprobaciones" valor={cargando ? '—' : chequeos.length}
             pie={cargando ? 'consultando…' : 'del módulo completo'} />
        <Kpi etiqueta="En orden" valor={cargando ? '—' : oks} pie="funcionando" />
        {/* «Apagado» no se cuenta como falla: casi todo lo que está apagado
            hoy lo está a propósito. Mezclarlos daría una alarma permanente
            que se aprende a ignorar. */}
        <Kpi etiqueta="Apagados" valor={cargando ? '—' : avisos} pie="a propósito o no" />
        <Kpi etiqueta="Fallando" valor={cargando ? '—' : malos} pie="no contestan" />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-3)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Salud del módulo
        </h1>
        <button className="wt-btn" style={{ marginLeft: 'auto' }}
                onClick={cargar} disabled={cargando}>Volver a comprobar</button>
      </div>

      <p className="wt-nota">
        Lo que puede estar apagado o caído sin que ninguna otra pantalla lo diga. Cada
        línea explica <strong>qué se rompe si está así</strong> — un tablero de luces que
        no lo explica no sirve para nada. Desde acá no se arregla nada: cada cosa se
        cambia en su pantalla.
      </p>

      <section className="wt-carta">
        <div className="wt-cuerpo-carta">
          {cargando && !datos.cluster ? (
            <p className="wt-estado" style={{ margin: 0 }}>Consultando…</p>
          ) : (
            chequeos.map((c) => (
              <Chequeo key={c.nombre} {...c} alIr={() => navegar(c.donde)} />
            ))
          )}
        </div>
      </section>
    </>
  );
}
