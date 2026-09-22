/* ============================================================================
   Paso 2 · Búsqueda de remesas y de wallets
   ----------------------------------------------------------------------------
   Dos búsquedas que funcionan igual: se pegan identificadores, se lanzan
   contra Redshift y se espera. Las dos son asincrónicas —`run_id` y sondeo—
   por la misma razón que el resto: la consulta puede tardar minutos y la
   Lambda corta a los treinta segundos.

   SE VALIDA ANTES DE MANDAR. El backend rechaza más de 5.000 identificadores,
   pero lo dice recién después de la espera. Decirlo al pegar ahorra ese
   minuto, y avisar de lo que se descartó evita que alguien busque 280
   creyendo que buscó 300.
   ========================================================================= */

import { useRef, useState } from 'react';

import { Tabla } from '../../comun/Tabla.jsx';
import { avisoDeRecorte, columnasDe, estadoDe, seguirCorrida } from '../../comun/corridas.js';
import { avisoDeDescartes, partirIds, problemaConLosIds } from '../../comun/individual.js';
import { useVivo } from '../../comun/vivo.js';

function Busqueda({
  api, titulo, explicacion, etiqueta, soloNumeros, ruta, cuerpoDe, texto, alCambiarTexto,
  extra = null,
}) {
  const [corrida, setCorrida] = useState(null);
  const [filas, setFilas] = useState([]);
  const [recorte, setRecorte] = useState('');
  const [error, setError] = useState('');
  const [corriendo, setCorriendo] = useState(false);
  const vivo = useVivo();

  const lectura = partirIds(texto, { soloNumeros });
  const problema = problemaConLosIds(lectura, etiqueta);
  const aviso = avisoDeDescartes(lectura);

  async function lanzar() {
    if (problema) { setError(problema); return; }
    setCorriendo(true); setError(''); setFilas([]); setRecorte(''); setCorrida(null);
    try {
      const d = await api.post(ruta, cuerpoDe(lectura.ids));
      if (!d?.run_id) throw new Error(d?.error || 'No se pudo iniciar la búsqueda.');
      setCorrida({ run_id: d.run_id, status: 'RUNNING' });

      const fin = await seguirCorrida((r) => api.get(r), d.run_id, {
        alAvanzar: (x) => { if (vivo.current && x) setCorrida(x); },
        cancelado: () => !vivo.current,
      });
      if (!vivo.current) return;
      setCorrida(fin);
      if (fin.status !== 'DONE') {
        setError(fin.error_message || 'La búsqueda terminó con error.');
        return;
      }
      setFilas(fin.result_preview || []);
      try {
        const todo = await api.get(`/runs/${d.run_id}/rows`);
        if (vivo.current && todo?.rows?.length) {
          setFilas(todo.rows);
          setRecorte(avisoDeRecorte(todo));
        }
      } catch { /* se queda con la muestra */ }
    } catch (e) {
      setError(e?.message || 'No se pudo lanzar la búsqueda.');
    } finally {
      if (vivo.current) setCorriendo(false);
    }
  }

  return (
    <>
      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">{titulo}</h2>
          {corrida && (
            <div className="wt-carta-herramientas">
              <span className="wt-insignia"
                    style={{ color: estadoDe(corrida).color, background: estadoDe(corrida).fondo }}>
                {estadoDe(corrida).etiqueta}
              </span>
              {corrida.download_url && (
                <a className="wt-btn" href={corrida.download_url}
                   target="_blank" rel="noopener noreferrer">Excel</a>
              )}
            </div>
          )}
        </header>
        <div className="wt-cuerpo-carta">
          <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
            {explicacion}
          </p>
          <textarea className="wt-input"
                    style={{ width: '100%', minHeight: 90, resize: 'vertical' }}
                    value={texto} onChange={(e) => alCambiarTexto(e.target.value)}
                    placeholder={`Pegá los ${etiqueta} — coma, espacio o salto de línea`} />
          <p style={{ margin: '6px 0 0', fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            {lectura.ids.length === 0
              ? `Ningún ${etiqueta.replace(/e?s$/, '')} todavía.`
              : `${lectura.ids.length.toLocaleString('es-CL')} para buscar.`}
            {aviso && <> · {aviso}</>}
          </p>
          {extra}
          <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-3)' }}>
            <button className="wt-btn wt-btn-primario"
                    disabled={corriendo || lectura.ids.length === 0} onClick={lanzar}>
              {corriendo ? 'Buscando…' : 'Buscar'}
            </button>
            {texto && (
              <button className="wt-btn" onClick={() => alCambiarTexto('')}>Limpiar</button>
            )}
          </div>
          {error && (
            <p className="wt-estado-error" style={{ marginTop: 'var(--e-3)', marginBottom: 0 }}>
              {error}
            </p>
          )}
          {recorte && <p className="wt-nota">{recorte}</p>}
        </div>
      </section>

      {filas.length > 0 && (
        <Tabla
          titulo={`Resultado · ${filas.length.toLocaleString('es-CL')} filas`}
          columnas={columnasDe(filas).map((c) => ({
            clave: c, titulo: c.replace(/_/g, ' '),
            tipo: typeof filas[0]?.[c] === 'number' ? 'numero' : undefined,
          }))}
          filas={filas}
          claveFila={(_, i) => i}
          porPagina={50}
          nombreExport="busqueda"
        />
      )}
    </>
  );
}

export function Paso2({ api, email, remesas, alCambiarRemesas }) {
  const [wallets, setWallets] = useState('');
  const [tipoWallet, setTipoWallet] = useState('natural');

  return (
    <>
      <Busqueda
        api={api}
        titulo="Búsqueda de remesas"
        explicacion="Busca en Redshift los datos completos de cada transacción: beneficiario,
                     país, monto y estado. El resultado alimenta el paso 4."
        etiqueta="números de remesa"
        soloNumeros
        ruta="/search/transactions"
        cuerpoDe={(ids) => ({ transaction_ids: ids.map(Number), user_email: email })}
        texto={remesas}
        alCambiarTexto={alCambiarRemesas}
      />

      <Busqueda
        api={api}
        titulo="Análisis de wallet"
        explicacion="Lo mismo para cuentas de wallet: movimientos de cada partner account."
        etiqueta="ids de cuenta"
        soloNumeros={false}
        ruta="/search/wallet"
        cuerpoDe={(ids) => ({
          partner_account_ids: ids, entity_type: tipoWallet, user_email: email,
        })}
        texto={wallets}
        alCambiarTexto={setWallets}
        extra={
          <label style={{ display: 'block', marginTop: 'var(--e-3)',
                          fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            Tipo de titular
            <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 180 }}
                    value={tipoWallet} onChange={(e) => setTipoWallet(e.target.value)}>
              <option value="natural">Persona natural</option>
              <option value="company">Empresa</option>
            </select>
          </label>
        }
      />
    </>
  );
}
