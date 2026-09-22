/* ============================================================================
   Repartir alertas y avisar
   ----------------------------------------------------------------------------
   Tres acciones de la bandeja que trabajan sobre VARIAS alertas a la vez:
   repartirlas entre analistas, asignarlas todas a una persona, y avisar por
   correo o Slack.

   LAS TRES PIDEN CONFIRMACIÓN NOMBRANDO. Repartir 50 alertas entre 4 personas
   es difícil de deshacer —hay que reasignarlas una por una— y avisar manda
   correos de verdad. Ver a quiénes les toca antes de apretar es lo único que
   frena un reparto entre el equipo equivocado.
   ========================================================================= */

import { useState } from 'react';

import { repartoEquitativo } from '../../comun/reparto.js';

function Analistas({ usuarios, elegidos, alCambiar }) {
  return (
    <div className="wt-checklist" style={{ maxHeight: 220, overflowY: 'auto' }}>
      {usuarios.length === 0 ? (
        <p className="wt-vacio">No se pudo leer la lista de analistas.</p>
      ) : usuarios.map((u) => (
        <label key={u.email} className="wt-checklist-item" style={{ cursor: 'pointer' }}>
          <input type="checkbox" checked={elegidos.includes(u.email)}
                 onChange={(e) => alCambiar(
                   e.target.checked ? [...elegidos, u.email]
                                    : elegidos.filter((x) => x !== u.email))} />
          <span>{u.full_name || u.email}</span>
          {u.equipo && (
            <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-xs)',
                           color: 'var(--texto-mute)' }}>
              {u.equipo}
            </span>
          )}
        </label>
      ))}
    </div>
  );
}

export function Reparto({ api, alertas, usuarios, alCerrar, alTerminar }) {
  const [modo, setModo] = useState('repartir');
  const [elegidos, setElegidos] = useState([]);
  const [prioridad, setPrioridad] = useState('medium');
  const [motivo, setMotivo] = useState('');
  const [canal, setCanal] = useState('email');
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState('');

  const previa = repartoEquitativo(alertas.length, elegidos);

  async function ejecutar() {
    setError('');
    const texto = modo === 'repartir'
      ? `Se van a repartir ${alertas.length} alertas entre ${elegidos.length} analista(s):\n\n`
        + previa.map((p) => `  · ${p.quien}: ${p.cuantas}`).join('\n')
        + '\n\nDeshacerlo es reasignar una por una. ¿Confirmás?'
      : modo === 'asignar'
        ? `Se le van a asignar las ${alertas.length} alertas a ${elegidos[0]}.\n\n¿Confirmás?`
        : `Se va a avisar por ${canal === 'slack' ? 'Slack' : 'correo'} sobre `
          + `${alertas.length} alerta(s) a ${elegidos.length} destinatario(s).\n\n¿Confirmás?`;
    if (!globalThis.confirm(texto)) return;

    setOcupado(true);
    try {
      if (modo === 'repartir') {
        const d = await api.post('/alerts/bulk-distribute', {
          alert_ids: alertas.map((a) => a.alert_id),
          rows: alertas.map((a) => a.row_data || {}),
          report_name: alertas[0]?.report_name || '',
          assignees: elegidos,
          priority: prioridad,
          reason: motivo,
        });
        if (d?.error) throw new Error(d.error);
        alTerminar(`Repartidas: ${d?.created ?? alertas.length} alerta(s).`);
      } else if (modo === 'asignar') {
        const d = await api.post('/cases/bulk-assign', {
          alert_ids: alertas.map((a) => a.alert_id),
          case_ids: alertas.map((a) => a.case_id).filter(Boolean),
          assigned_to: elegidos[0],
        });
        if (d?.error) throw new Error(d.error);
        alTerminar(`Asignadas ${d?.updated ?? alertas.length} a ${elegidos[0]}.`);
      } else {
        const d = await api.post('/alerts/notify', {
          alert_ids: alertas.map((a) => a.alert_id),
          destinatarios: elegidos,
          canal,
        });
        if (d?.error) throw new Error(d.error);
        alTerminar(`Aviso enviado por ${canal}.`);
      }
    } catch (e) {
      setError(e?.message || 'No se pudo completar la acción.');
    } finally {
      setOcupado(false);
    }
  }

  const listo = modo === 'asignar' ? elegidos.length === 1 : elegidos.length > 0;

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{alertas.length} alerta(s) seleccionada(s)</h2>
        <div className="wt-carta-herramientas">
          <button className="wt-btn" onClick={alCerrar}>Cerrar</button>
        </div>
      </header>
      <div className="wt-cuerpo-carta">
        <div className="wt-filtros" style={{ marginBottom: 'var(--e-3)' }}>
          {[['repartir', 'Repartir entre varios'],
            ['asignar', 'Asignar todas a uno'],
            ['avisar', 'Avisar']].map(([k, t]) => (
              <button key={k} className="wt-filtro" aria-pressed={modo === k}
                      onClick={() => { setModo(k); setElegidos([]); }}>
                {t}
              </button>
          ))}
        </div>

        <Analistas usuarios={usuarios} elegidos={elegidos} alCambiar={setElegidos} />

        {modo === 'repartir' && (
          <>
            <div className="wt-parametros" style={{ marginTop: 'var(--e-3)' }}>
              <label className="wt-parametro">
                <span>Prioridad</span>
                <select className="wt-input" value={prioridad}
                        onChange={(e) => setPrioridad(e.target.value)}>
                  <option value="high">Alta</option>
                  <option value="medium">Media</option>
                  <option value="low">Baja</option>
                </select>
              </label>
              <label className="wt-parametro">
                <span>Motivo</span>
                <input className="wt-input" value={motivo} onChange={(e) => setMotivo(e.target.value)}
                       placeholder="Queda en cada alerta" />
              </label>
            </div>
            {/* El reparto se muestra antes de hacerlo: es la única forma de
                ver que a alguien le tocan treinta y a otro dos. */}
            {previa.length > 0 && (
              <p className="wt-nota">
                Le va a tocar: {previa.map((p) => `${p.quien.split('@')[0]} ${p.cuantas}`).join(' · ')}
              </p>
            )}
          </>
        )}

        {modo === 'avisar' && (
          <label className="wt-parametro" style={{ marginTop: 'var(--e-3)' }}>
            <span>Por dónde</span>
            <select className="wt-input" style={{ width: 200 }} value={canal}
                    onChange={(e) => setCanal(e.target.value)}>
              <option value="email">Correo</option>
              <option value="slack">Slack</option>
            </select>
          </label>
        )}

        {error && <p className="wt-estado-error" style={{ marginTop: 'var(--e-3)' }}>{error}</p>}

        <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
          <button className="wt-btn wt-btn-primario" disabled={!listo || ocupado} onClick={ejecutar}>
            {ocupado ? 'Trabajando…' : modo === 'repartir' ? 'Repartir'
              : modo === 'asignar' ? 'Asignar' : 'Avisar'}
          </button>
          <button className="wt-btn" onClick={alCerrar}>Cancelar</button>
        </div>
      </div>
    </section>
  );
}
