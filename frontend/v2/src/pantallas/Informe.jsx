/* ============================================================================
   Informe de gestión
   ----------------------------------------------------------------------------
   El PDF de gestión de casos: cuántos se manejaron, cuántos no, por equipo y
   por analista. Lo arma el backend reusando `get_cases`, así que los números
   del informe son exactamente los mismos que muestra la pantalla de Casos.

   ACÁ NO SE CALCULA NADA. Sería fácil armar los mismos indicadores en el
   front con los casos que ya están cargados, y sería un error: el informe se
   imprime y se manda, y dos versiones del mismo número —una en pantalla y
   otra en el PDF— es exactamente lo que no puede pasar en un documento que
   alguien va a defender.
   ========================================================================= */

import { useEffect, useState } from 'react';

/** El primer día del mes en curso, en el formato que espera la API. */
function primerDiaDelMes() {
  const h = new Date();
  return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}-01`;
}

function hoyTexto() {
  return new Date().toISOString().slice(0, 10);
}

export function Informe({ api, email }) {
  const [desde, setDesde] = useState(primerDiaDelMes());
  const [hasta, setHasta] = useState(hoyTexto());
  const [analista, setAnalista] = useState('');
  const [equipo, setEquipo] = useState('');
  const [usuarios, setUsuarios] = useState([]);
  const [generando, setGenerando] = useState(false);
  const [error, setError] = useState('');
  const [listo, setListo] = useState(null);

  useEffect(() => {
    let vivo = true;
    api.get('/crm/users')
      .then((d) => { if (vivo) setUsuarios(d?.users || []); })
      .catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  /* Los equipos salen de los usuarios, no de una lista escrita acá: si
     alguien crea un equipo nuevo en administración, aparece solo. */
  const equipos = [...new Set(usuarios.map((u) => u.equipo).filter(Boolean))].sort();

  async function generar(e) {
    e.preventDefault();
    if (desde && hasta && desde > hasta) {
      setError('La fecha de inicio es posterior a la de fin.');
      return;
    }
    setGenerando(true); setError(''); setListo(null);
    try {
      const q = new URLSearchParams();
      if (desde) q.set('desde', desde);
      if (hasta) q.set('hasta', hasta);
      if (analista) q.set('analista', analista);
      if (equipo) q.set('equipo', equipo);
      if (email) q.set('pedido_por', email);
      const d = await api.get(`/informes/gestion.pdf?${q.toString()}`);
      if (!d?.url) throw new Error('El backend no devolvió una dirección de descarga.');
      // Se abre después del await, así que el navegador puede tomarlo por
      // emergente: por eso además queda el enlace a la vista.
      globalThis.open(d.url, '_blank', 'noopener');
      setListo(d);
    } catch (err) {
      setError(err?.message || 'No se pudo generar el informe.');
    } finally {
      setGenerando(false);
    }
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Informe de gestión
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          casos gestionados y no gestionados, por equipo y por analista
        </span>
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      <section className="wt-carta" style={{ maxWidth: 720 }}>
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">Qué incluir</h2>
        </header>
        <form className="wt-cuerpo-carta" onSubmit={generar}>
          <div style={{ display: 'flex', gap: 'var(--e-3)', flexWrap: 'wrap',
                        alignItems: 'flex-end' }}>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Desde
              <input type="date" className="wt-input"
                     style={{ display: 'block', marginTop: 4 }}
                     value={desde} onChange={(e) => setDesde(e.target.value)} />
            </label>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Hasta
              <input type="date" className="wt-input"
                     style={{ display: 'block', marginTop: 4 }}
                     value={hasta} onChange={(e) => setHasta(e.target.value)} />
            </label>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Equipo
              <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 180 }}
                      value={equipo} onChange={(e) => setEquipo(e.target.value)}>
                <option value="">Todos</option>
                {equipos.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Analista
              <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 220 }}
                      value={analista} onChange={(e) => setAnalista(e.target.value)}>
                <option value="">Todos</option>
                {usuarios.map((u) => (
                  <option key={u.email} value={u.email}>{u.full_name || u.email}</option>
                ))}
              </select>
            </label>
          </div>

          <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)',
                      margin: 'var(--e-3) 0 0' }}>
            Las fechas filtran por <strong>creación del caso</strong>. Sin filtros de equipo ni
            analista, el informe sale dividido por equipo y dentro de cada uno por analista.
          </p>

          <button className="wt-btn wt-btn-primario" type="submit"
                  style={{ marginTop: 'var(--e-4)' }} disabled={generando}>
            {generando ? 'Generando el PDF…' : 'Generar el informe'}
          </button>
        </form>
      </section>

      {/* El navegador puede bloquear la ventana emergente. Sin este enlace la
          descarga se perdería sin que nadie sepa por qué. */}
      {listo?.url && (
        <p className="wt-nota" style={{ marginTop: 'var(--e-4)', maxWidth: 720 }}>
          Informe generado{listo.nombre ? <> · <span className="mono">{listo.nombre}</span></> : null}.
          Si no se abrió la descarga,{' '}
          <a href={listo.url} target="_blank" rel="noopener noreferrer">abrila desde acá</a>.
          {listo.expira_en_segundos && (
            <> El enlace vence en {Math.round(listo.expira_en_segundos / 60)} minutos.</>
          )}
        </p>
      )}
    </>
  );
}
