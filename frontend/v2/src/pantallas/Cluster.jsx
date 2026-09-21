/* ============================================================================
   Cluster
   ----------------------------------------------------------------------------
   El Redshift que alimenta los reportes. Se apaga solo de 18:30 a 04:00 para
   no cobrar de noche, así que encontrarlo pausado es lo NORMAL fuera de
   horario — no un error, y la pantalla no lo pinta como tal.

   Importa porque explica media aplicación: si el cluster está pausado, un
   análisis individual va a quedar en «despertando» varios minutos y la ficha
   de un cliente va a tardar mucho más de lo habitual. Saberlo de antemano
   evita que alguien reporte como falla lo que es la infraestructura
   despertándose.
   ========================================================================= */

import { useCallback, useEffect, useRef, useState } from 'react';

import { Kpi } from '../comun/Kpi.jsx';
import { clusterEnMovimiento, estadoCluster } from '../comun/admin.js';
import { soloLectura } from '../permisos.js';

const CADA_MS = 10000;

export function Cluster({ api, perfil, email }) {
  const [estado, setEstado] = useState('');
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [actuando, setActuando] = useState('');
  const temporizador = useRef(null);

  const lectura = soloLectura(perfil);

  const consultar = useCallback(async ({ silencioso = false } = {}) => {
    if (!silencioso) setCargando(true);
    try {
      const d = await api.get('/cluster/status');
      setEstado(d?.status || '');
      // Mientras se mueve se vuelve a preguntar sola: despertar tarda
      // minutos y obligar a refrescar a mano haría pensar que se trabó.
      if (!clusterEnMovimiento(d?.status)) {
        clearInterval(temporizador.current);
        temporizador.current = null;
      } else if (!temporizador.current) {
        temporizador.current = setInterval(() => consultar({ silencioso: true }), CADA_MS);
      }
      setError('');
    } catch (e) {
      setError(e?.message || 'No se pudo consultar el cluster.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { consultar(); }, [consultar]);
  useEffect(() => () => clearInterval(temporizador.current), []);

  async function accion(que) {
    const texto = que === 'wake'
      ? 'Despertar el cluster tarda unos minutos y empieza a cobrar por hora. ¿Seguro?'
      : 'Pausar el cluster corta cualquier consulta en curso: los reportes que estén '
        + 'corriendo van a fallar. ¿Seguro?';
    if (!globalThis.confirm(texto)) return;
    setActuando(que); setError(''); setAviso('');
    try {
      await api.post(`/cluster/${que}`, { user_email: email });
      setAviso(que === 'wake' ? 'Se pidió despertar el cluster.' : 'Se pidió pausar el cluster.');
      await consultar({ silencioso: true });
      if (!temporizador.current) {
        temporizador.current = setInterval(() => consultar({ silencioso: true }), CADA_MS);
      }
    } catch (e) {
      setError(e?.message || 'No se pudo cambiar el estado del cluster.');
    } finally {
      setActuando('');
    }
  }

  const d = estadoCluster(estado);
  const moviendose = clusterEnMovimiento(estado);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Redshift"
             valor={cargando && !estado ? '—' : (d?.etiqueta || estado || '—')}
             pie={cargando && !estado ? 'consultando…'
               : d?.consulta ? 'se pueden correr reportes'
               : moviendose ? 'se actualiza sola'
               : 'los reportes van a esperar'} />
        <Kpi etiqueta="Horario" valor="04:00 – 18:30"
             pie="fuera de esa franja se pausa solo" />
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      <section className="wt-carta" style={{ maxWidth: 720 }}>
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">Estado del cluster</h2>
          {d && (
            <span className="wt-insignia" style={{ color: d.color, background: d.fondo }}>
              {d.etiqueta}
            </span>
          )}
          <button className="wt-btn" style={{ marginLeft: 'auto' }}
                  onClick={() => consultar()} disabled={cargando}>
            Consultar
          </button>
        </header>
        <div className="wt-cuerpo-carta">
          {!d && estado && (
            <p className="wt-nota">
              El cluster devolvió un estado que esta pantalla no conoce:{' '}
              <span className="mono">{estado}</span>.
            </p>
          )}

          <p style={{ marginTop: 0 }}>
            {d?.consulta
              ? 'Los reportes, el análisis individual y la ficha del cliente consultan sin espera adicional.'
              : moviendose
                ? 'Está cambiando de estado. Las consultas que se lancen ahora van a esperar a que termine.'
                : 'Está pausado. La primera consulta lo despierta sola, pero eso agrega varios minutos: '
                  + 'un análisis individual va a quedar en «despertando» un rato.'}
          </p>

          {lectura ? (
            <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
              Tu perfil es de consulta: podés ver el estado, pero no cambiarlo.
            </p>
          ) : (
            <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
              <button className="wt-btn wt-btn-primario"
                      disabled={Boolean(actuando) || moviendose || d?.consulta}
                      onClick={() => accion('wake')}>
                {actuando === 'wake' ? 'Pidiendo…' : 'Despertar'}
              </button>
              <button className="wt-btn"
                      disabled={Boolean(actuando) || moviendose || !d?.consulta}
                      onClick={() => accion('pause')}>
                {actuando === 'pause' ? 'Pidiendo…' : 'Pausar'}
              </button>
            </div>
          )}

          <p className="wt-nota" style={{ marginTop: 'var(--e-4)', marginBottom: 0 }}>
            Pausarlo <strong>corta cualquier consulta en curso</strong>. Antes de hacerlo,
            conviene mirar el historial: si hay una corrida en marcha, va a fallar.
          </p>
        </div>
      </section>
    </>
  );
}
