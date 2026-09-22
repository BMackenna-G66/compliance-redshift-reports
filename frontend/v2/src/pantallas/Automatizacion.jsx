/* ============================================================================
   Automatización
   ----------------------------------------------------------------------------
   La priorización automática de alertas: corre sola, puntúa las alertas del
   día y —si está prendida— le manda el pedido de documentación al cliente.

   ESTÁ APAGADA, Y LA PANTALLA LO DICE FUERTE. Es el mismo criterio que la de
   relevo: un proceso automático apagado no se nota hasta que alguien espera
   resultados que nunca llegan. Prenderla es la acción con más alcance de
   toda la aplicación —corre sin que nadie la mire— así que pregunta.
   ========================================================================= */

import { Suspense, lazy, useCallback, useEffect, useState } from 'react';

import { Kpi } from '../comun/Kpi.jsx';
import { fecha, hace } from '../comun/alertas.js';
import { soloLectura } from '../permisos.js';

const Documentos = lazy(() =>
  import('./alertas/Documentos.jsx').then((m) => ({ default: m.Documentos })));

function Pestanas({ vista, alCambiar }) {
  return (
    <nav className="wt-pasos" aria-label="Vistas de automatización">
      {[['cola', 'La cola priorizada', 'prender, probar y enviar'],
        ['documentos', 'Documentos por alerta', 'qué se le pide a cada una']]
        .map(([k, titulo, pie]) => (
          <button key={k} className={`wt-paso-boton${vista === k ? ' wt-paso-activo' : ''}`}
                  onClick={() => alCambiar(k)}>
            <span>
              <span className="wt-paso-titulo">{titulo}</span>
              <span className="wt-paso-pie">{pie}</span>
            </span>
          </button>
      ))}
    </nav>
  );
}

export function Automatizacion({ api, perfil, email }) {
  const [vista, setVista] = useState('cola');
  const [ajustes, setAjustes] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [actuando, setActuando] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      setAjustes(await api.get('/alert-prioritization/settings'));
    } catch (e) {
      setError(e?.message || 'No se pudieron leer los ajustes.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  async function cambiar(prender) {
    if (prender && !globalThis.confirm(
      'Prender la priorización automática hace que el proceso corra solo y, con los '
      + 'envíos habilitados, LE ESCRIBA A CLIENTES REALES sin que nadie lo mire.\n\n'
      + '¿Seguro?')) return;
    setActuando('interruptor'); setError(''); setAviso('');
    try {
      await api.post('/alert-prioritization/settings', {
        enabled: prender, updated_by: email,
      });
      setAviso(prender ? 'La priorización automática quedó prendida.'
                       : 'La priorización automática quedó apagada.');
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo cambiar el ajuste.');
    } finally {
      setActuando('');
    }
  }

  async function probar() {
    setActuando('prueba'); setError(''); setAviso('');
    try {
      const d = await api.post('/alert-prioritization/test-run', { user_email: email });
      // Una prueba no manda nada: sirve para ver qué HARÍA el proceso. Por eso
      // no pregunta antes, y por eso conviene decir que no envió.
      setAviso(`Prueba corrida: ${d?.mensaje || 'mirá el resultado en el historial'}. `
               + 'No se le escribió a ningún cliente.');
    } catch (e) {
      setError(e?.message || 'No se pudo correr la prueba.');
    } finally {
      setActuando('');
    }
  }

  /**
   * Manda la cola priorizada AHORA, sin esperar al horario.
   *
   * Esto SÍ le escribe a clientes reales, a diferencia de la prueba. Por eso
   * pregunta y por eso el texto lo dice con todas las letras: es la misma
   * acción que hace el proceso automático, adelantada a mano.
   */
  async function enviarAhora() {
    const ok = globalThis.confirm(
      'Esto manda la cola priorizada AHORA y les escribe a CLIENTES REALES.\n\n'
      + 'No es la prueba: los correos salen de verdad.\n\n¿Confirmás?');
    if (!ok) return;
    setActuando('manual'); setError(''); setAviso('');
    try {
      const d = await api.post('/alert-prioritization/send-manual', { user_email: email });
      setAviso(`Envío manual hecho: ${d?.enviados ?? d?.mensaje ?? 'mirá el historial'}.`);
    } catch (e) {
      setError(e?.message || 'No se pudo hacer el envío manual.');
    } finally {
      setActuando('');
    }
  }

  const prendida = Boolean(ajustes?.enabled);

  if (vista === 'documentos') {
    return (
      <>
        <Pestanas vista={vista} alCambiar={setVista} />
        <Suspense fallback={<p className="wt-estado">Cargando…</p>}>
          <Documentos api={api} perfil={perfil} />
        </Suspense>
      </>
    );
  }

  return (
    <>
      <Pestanas vista={vista} alCambiar={setVista} />

      <div className="wt-kpis">
        <Kpi principal etiqueta="Priorización automática"
             valor={cargando && !ajustes ? '—' : prendida ? 'Prendida' : 'Apagada'}
             pie={cargando && !ajustes ? 'leyendo…'
               : prendida ? 'corre sola' : 'no corre'} />
        <Kpi etiqueta="Último cambio"
             valor={ajustes?.updated_at ? hace(ajustes.updated_at) : '—'}
             pie={ajustes?.updated_by || 'sin registro'} />
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {ajustes && !prendida && (
        <p className="wt-nota wt-nota-alarma">
          <strong>La priorización automática está apagada.</strong> Las alertas del día no
          se puntúan ni se reparten solas: hay que hacerlo a mano desde la bandeja.
        </p>
      )}
      {prendida && (
        <p className="wt-nota">
          <strong>La priorización automática está prendida.</strong> El proceso corre solo.
          Si además los envíos de relevo están habilitados, le escribe a clientes reales
          sin intervención.
        </p>
      )}

      <section className="wt-carta" style={{ maxWidth: 720 }}>
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">Priorización de alertas</h2>
          <button className="wt-btn" style={{ marginLeft: 'auto' }}
                  onClick={cargar} disabled={cargando}>Refrescar</button>
        </header>
        <div className="wt-cuerpo-carta">
          <p style={{ marginTop: 0 }}>
            Puntúa las alertas del día, las ordena por prioridad y las reparte entre los
            analistas. Con los envíos habilitados, además le pide la documentación al
            cliente.
          </p>

          {ajustes?.updated_at && (
            <dl className="wt-datos" style={{ marginBottom: 'var(--e-4)' }}>
              <dt>Último cambio</dt>
              <dd title={ajustes.updated_at}>
                {fecha(ajustes.updated_at)?.toLocaleString('es-CL') || ajustes.updated_at}
                {ajustes.updated_by && ` · ${ajustes.updated_by}`}
              </dd>
            </dl>
          )}

          {lectura ? (
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
              Tu perfil es de consulta: podés ver el estado, pero no cambiarlo.
            </p>
          ) : (
            <div style={{ display: 'flex', gap: 'var(--e-2)', flexWrap: 'wrap' }}>
              <button className={'wt-btn' + (prendida ? '' : ' wt-btn-primario')}
                      disabled={Boolean(actuando) || cargando}
                      onClick={() => cambiar(!prendida)}>
                {actuando === 'interruptor' ? 'Guardando…'
                  : prendida ? 'Apagar la automatización' : 'Prender la automatización'}
              </button>
              {/* Una prueba no manda nada: por eso no pregunta. */}
              <button className="wt-btn" disabled={Boolean(actuando)} onClick={probar}>
                {actuando === 'prueba' ? 'Corriendo…' : 'Correr una prueba (no envía)'}
              </button>
              {/* Éste SÍ manda. Va separado del de prueba y con el color de
                  peligro para que no se confundan de botón. */}
              <button className="wt-btn wt-btn-peligro" disabled={Boolean(actuando)}
                      onClick={enviarAhora}>
                {actuando === 'manual' ? 'Enviando…' : 'Mandar la cola ahora (sí envía)'}
              </button>
            </div>
          )}
          {!lectura && (
            <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-xs)',
                        color: 'var(--texto-mute)' }}>
              «Correr una prueba» muestra qué HARÍA el proceso sin escribirle a nadie.
              «Mandar la cola ahora» hace lo mismo que el proceso automático, adelantado a
              mano: los correos salen de verdad.
            </p>
          )}
        </div>
      </section>
    </>
  );
}
