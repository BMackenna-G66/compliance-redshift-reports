/* ============================================================================
   Análisis individual
   ----------------------------------------------------------------------------
   Se le dan ids de cliente, corre las diez banderas sobre sus transacciones y
   deja un Excel.

   ES ASÍNCRONO Y ESO SE NOTA. `POST /analyze/individual` no devuelve el
   resultado: devuelve un `run_id`. Hay que preguntar por él hasta que
   termine. Una corrida de 891 clientes tardó tres minutos, y el cluster de
   Redshift está pausado de 18:30 a 04:00 — la primera consulta del día lo
   despierta y eso agrega varios minutos más, con estado `RESUMING`.

   Por eso la pantalla dice en qué va, cuánto lleva, y no se queda en un
   "Cargando…" mudo que la gente interpreta como que se colgó.
   ========================================================================= */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ESTADOS_CORRIDA, duracionTexto, enCurso, leerIds } from '../comun/analisis.js';
import { soloLectura } from '../permisos.js';

/* Cada cuánto se vuelve a preguntar. Seis segundos: lo bastante seguido para
   que se sienta vivo, lo bastante espaciado para no castigar a la API
   durante los tres minutos que puede durar una corrida grande. */
const CADA_MS = 6000;

export function Individual({ api, perfil, email }) {
  const [texto, setTexto] = useState('');
  const [dias, setDias] = useState('90');
  const [tipo, setTipo] = useState('natural');
  const [corrida, setCorrida] = useState(null);
  const [error, setError] = useState('');
  const [lanzando, setLanzando] = useState(false);
  const [desde, setDesde] = useState(null);
  const temporizador = useRef(null);

  const lectura = soloLectura(perfil);
  const ids = leerIds(texto);

  /* Se limpia al desmontar: sin esto el intervalo sigue pidiendo después de
     que el usuario se fue a otra pantalla. */
  useEffect(() => () => clearInterval(temporizador.current), []);

  const consultar = useCallback(async (runId) => {
    try {
      const d = await api.get(`/runs/${runId}`);
      setCorrida(d);
      if (!enCurso(d?.status)) {
        clearInterval(temporizador.current);
        temporizador.current = null;
      }
    } catch (e) {
      // Un tropiezo de red no cancela el seguimiento: la corrida sigue en el
      // servidor y la próxima vuelta puede contestar bien.
      setError(`No pude consultar el estado (${e?.message || 'error'}). Sigo intentando.`);
    }
  }, [api]);

  async function lanzar(e) {
    e.preventDefault();
    if (ids.length === 0) return;
    setLanzando(true); setError(''); setCorrida(null);
    clearInterval(temporizador.current);
    try {
      const d = await api.post('/analyze/individual', {
        customer_ids: ids.map((x) => (/^\d+$/.test(x) ? Number(x) : x)),
        days: Number(dias) || 90,
        entity_type: tipo,
        user_email: email,
      });
      const runId = d?.run_id;
      if (!runId) throw new Error('La API no devolvió un identificador de corrida.');
      setDesde(Date.now());
      setCorrida({ run_id: runId, status: 'QUEUED' });
      await consultar(runId);
      temporizador.current = setInterval(() => consultar(runId), CADA_MS);
    } catch (err) {
      setError(err?.message || 'No se pudo lanzar el análisis.');
    } finally {
      setLanzando(false);
    }
  }

  const estado = corrida ? ESTADOS_CORRIDA[String(corrida.status).toUpperCase()] : null;
  const corriendo = corrida && enCurso(corrida.status);
  const transcurrido = desde && corriendo ? (Date.now() - desde) / 1000 : null;

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Análisis individual
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          las diez banderas sobre las transacciones de cada cliente
        </span>
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {lectura ? (
        <p className="wt-nota">
          Tu perfil es de consulta: podés ver los resultados en el historial, pero no
          lanzar análisis nuevos.
        </p>
      ) : (
        <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Qué analizar</h2>
          </header>
          <form className="wt-cuerpo-carta" onSubmit={lanzar}>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Ids de cliente
              {/* Se aceptan comas, espacios y saltos de línea: los ids suelen
                  venir pegados de un Excel o de un mensaje de Slack, y pedir
                  un formato exacto sólo agrega un paso manual. */}
              <textarea className="wt-input"
                        style={{ display: 'block', width: '100%', marginTop: 4,
                                 minHeight: 90, resize: 'vertical' }}
                        value={texto} onChange={(e) => setTexto(e.target.value)}
                        placeholder="1234567, 2345678  —  separados por coma, espacio o salto de línea" />
            </label>
            <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)', margin: '6px 0 0' }}>
              {ids.length === 0
                ? 'Ningún id todavía.'
                : `${ids.length} cliente${ids.length === 1 ? '' : 's'} para analizar.`}
            </p>

            <div style={{ display: 'flex', gap: 'var(--e-3)', alignItems: 'flex-end',
                          marginTop: 'var(--e-3)', flexWrap: 'wrap' }}>
              <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Ventana
                <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 130 }}
                        value={dias} onChange={(e) => setDias(e.target.value)}>
                  <option value="30">30 días</option>
                  <option value="60">60 días</option>
                  <option value="90">90 días</option>
                  <option value="180">180 días</option>
                </select>
              </label>
              <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                Tipo
                <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 150 }}
                        value={tipo} onChange={(e) => setTipo(e.target.value)}>
                  <option value="natural">Persona natural</option>
                  <option value="company">Empresa</option>
                </select>
              </label>
              <button className="wt-btn wt-btn-primario" type="submit"
                      disabled={lanzando || corriendo || ids.length === 0}>
                {lanzando ? 'Lanzando…' : corriendo ? 'Hay una corriendo' : 'Analizar'}
              </button>
            </div>
          </form>
        </section>
      )}

      {corrida && (
        <section className="wt-carta">
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">La corrida</h2>
            {estado && (
              <span className="wt-insignia"
                    style={{ color: estado.color, background: estado.fondo }}>
                {estado.etiqueta}
              </span>
            )}
            <span className="mono" style={{ marginLeft: 'auto', fontSize: 'var(--texto-xs)',
                                            color: 'var(--texto-mute)' }}>
              {corrida.run_id}
            </span>
          </header>
          <div className="wt-cuerpo-carta">
            {corriendo ? (
              <>
                <p style={{ margin: 0 }}>
                  Corriendo desde hace {duracionTexto(transcurrido)}. Se consulta sola cada
                  seis segundos; podés dejar la pantalla abierta.
                </p>
                {String(corrida.status).toUpperCase() === 'RESUMING' && (
                  <p className="wt-nota" style={{ marginTop: 'var(--e-3)', marginBottom: 0 }}>
                    El cluster de Redshift estaba pausado y se está despertando. La primera
                    consulta del día tarda varios minutos más de lo normal.
                  </p>
                )}
              </>
            ) : ['ERROR', 'FAILED'].includes(String(corrida.status).toUpperCase()) ? (
              <p className="wt-estado-error" style={{ margin: 0 }}>
                La corrida falló. Revisá el historial para ver el detalle.
              </p>
            ) : (
              <>
                <p style={{ margin: 0 }}>
                  Terminó con{' '}
                  <strong>{Number(corrida.row_count || 0).toLocaleString('es-CL')} filas</strong>.
                </p>
                {corrida.download_url ? (
                  <p style={{ marginTop: 'var(--e-3)', marginBottom: 0 }}>
                    <a href={corrida.download_url} target="_blank" rel="noopener noreferrer">
                      Descargar el Excel
                    </a>
                  </p>
                ) : (
                  <p style={{ marginTop: 'var(--e-3)', marginBottom: 0,
                              color: 'var(--texto-mute)', fontSize: 'var(--texto-sm)' }}>
                    Esta corrida no dejó archivo para descargar.
                  </p>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </>
  );
}
