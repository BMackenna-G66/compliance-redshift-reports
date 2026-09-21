/* ============================================================================
   Flags y pesos
   ----------------------------------------------------------------------------
   Las diez banderas del análisis individual, con su peso y los cortes de
   nivel. Es la pantalla que explica de dónde sale un score.

   TODO ESTO SE PIDE AL BACKEND. El prototipo traía las diez banderas escritas
   con sus pesos, y hoy coinciden exactamente con `aml_individual.py` — lo
   verifiqué: 10 de 10, mismos pesos. Pero coincidir hoy no es estar
   sincronizado: el día que alguien cambie un peso, esta pantalla estaría
   mintiendo y nadie se enteraría hasta que un analista defienda un caso con
   un número que no es.

   Por eso se agregó `GET /flags`, que lee las constantes del módulo de
   scoring. Si ese endpoint no está desplegado, la pantalla lo dice en vez de
   caer a una copia — una copia silenciosa es justo el problema que evita.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { NIVELES } from '../dominio.js';

const COLOR_PESO = {
  3: { color: 'var(--nivel-critico-texto)', fondo: 'var(--nivel-critico-tenue)' },
  2: { color: 'var(--nivel-alto-texto)', fondo: 'var(--nivel-alto-tenue)' },
  1: { color: 'var(--g66-azul-texto)', fondo: 'var(--azul-tenue)' },
};

/** La barra que muestra el peso relativo de cada bandera. */
function Barra({ peso, maximoPeso }) {
  const c = COLOR_PESO[peso] || COLOR_PESO[1];
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 90, height: 8, background: 'var(--superficie-3)',
                     borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
        <span style={{ display: 'block', height: '100%', borderRadius: 'var(--r-pill)',
                       width: `${(peso / maximoPeso) * 100}%`, background: c.color }} />
      </span>
      <span style={{ fontWeight: 'var(--peso-fuerte)', color: c.color,
                     fontVariantNumeric: 'tabular-nums' }}>
        {peso}
      </span>
    </span>
  );
}

export function Flags({ api }) {
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState(0);

  const cargar = useCallback(async () => {
    setCargando(true); setError(''); setStatus(0);
    try {
      const r = await api.crudo('GET', '/flags');
      if (!r.ok) {
        setStatus(r.status);
        throw new Error(r.datos?.error || `La API respondió ${r.status}.`);
      }
      setDatos(r.datos);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar la matriz de banderas.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  if (cargando) return <p className="wt-estado">Cargando…</p>;

  if (error) {
    return (
      <div className="wt-pendiente">
        <h2>Flags y pesos</h2>
        {status === 404 ? (
          <>
            <p>
              Esta pantalla lee la matriz de <code>GET /flags</code>, que
              <strong> todavía no está desplegado</strong> en la API.
            </p>
            <p style={{ fontSize: 'var(--texto-sm)' }}>
              El endpoint ya está escrito en <code>lambda/api_handler.py</code>;
              falta actualizar la Lambda. No se muestran los pesos de memoria a
              propósito: una copia que se desincroniza en silencio es
              exactamente lo que esta pantalla tiene que evitar.
            </p>
          </>
        ) : (
          <p>{error}</p>
        )}
        <button className="wt-btn" style={{ marginTop: 16 }} onClick={cargar}>Reintentar</button>
      </div>
    );
  }

  const flags = datos?.flags || [];
  const maximo = datos?.maximo ?? 0;
  const maximoPeso = Math.max(1, ...flags.map((f) => f.peso));
  const cortes = datos?.cortes || {};

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Flags y pesos
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          {flags.length} banderas · máximo {maximo} puntos
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={cargar}>
          Refrescar
        </button>
      </div>

      <p className="wt-nota">
        El score de un cliente es la <strong>suma de los pesos</strong> de las banderas que se
        le activaron. Va de 0 a {maximo}. Estos números salen del módulo de scoring, no
        están escritos en la pantalla.
      </p>

      <div className="wt-ficha-grilla">
        <section className="wt-carta">
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Las banderas</h2>
          </header>
          <div className="wt-tabla-marco">
            <table className="wt-tabla">
              <thead>
                <tr>
                  <th style={{ width: '12%' }}>Código</th>
                  <th>Qué detecta</th>
                  <th style={{ width: '30%' }}>Peso</th>
                </tr>
              </thead>
              <tbody>
                {flags.map((f) => (
                  <tr key={f.clave}>
                    <td className="wt-td-mono" style={{ fontWeight: 'var(--peso-fuerte)' }}>
                      {f.codigo}
                    </td>
                    <td>
                      {f.nombre}
                      <span className="mono"
                            style={{ display: 'block', fontSize: 'var(--texto-xs)',
                                     color: 'var(--texto-mute)' }}>
                        {f.clave}
                      </span>
                    </td>
                    <td><Barra peso={f.peso} maximoPeso={maximoPeso} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="wt-carta">
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Los cortes de nivel</h2>
          </header>
          <div className="wt-cuerpo-carta">
            <table className="wt-tabla">
              <thead><tr><th>Nivel</th><th>Desde</th><th>Qué significa</th></tr></thead>
              <tbody>
                <tr>
                  <td style={{ color: NIVELES.CRITICO.color, fontWeight: 'var(--peso-fuerte)' }}>
                    Crítico
                  </td>
                  <td className="wt-td-num">{cortes.critico ?? '—'}</td>
                  <td style={{ whiteSpace: 'normal' }}>Varias banderas graves a la vez</td>
                </tr>
                <tr>
                  <td style={{ color: NIVELES.ALTO.color, fontWeight: 'var(--peso-fuerte)' }}>Alto</td>
                  <td className="wt-td-num">{cortes.alto ?? '—'}</td>
                  <td style={{ whiteSpace: 'normal' }}>Dos o más indicadores combinados</td>
                </tr>
                <tr>
                  <td style={{ color: NIVELES.MEDIO.color, fontWeight: 'var(--peso-fuerte)' }}>Medio</td>
                  <td className="wt-td-num">{cortes.medio ?? '—'}</td>
                  <td style={{ whiteSpace: 'normal' }}>Un indicador significativo</td>
                </tr>
                <tr>
                  <td style={{ color: NIVELES.BAJO.color, fontWeight: 'var(--peso-fuerte)' }}>Bajo</td>
                  <td className="wt-td-num">0</td>
                  <td style={{ whiteSpace: 'normal' }}>Comportamiento rutinario</td>
                </tr>
              </tbody>
            </table>

            {/* El aviso que evita el error más fácil de cometer con esta app. */}
            <p className="wt-nota" style={{ marginTop: 'var(--e-4)', marginBottom: 0 }}>
              <strong>Ojo:</strong> esta escala es la del <em>análisis individual</em>, de 0 a{' '}
              {maximo}. El puntaje de las alertas transaccionales es otro, va de 0 a 100 y
              usa sus propios cortes (P1 ≥ 75, P2 ≥ 50). Los dos se llaman{' '}
              <span className="mono">risk_score</span> y no son comparables.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
