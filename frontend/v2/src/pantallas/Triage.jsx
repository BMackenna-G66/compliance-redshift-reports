/* ============================================================================
   Triage de una alerta
   ----------------------------------------------------------------------------
   Todo lo que se sabe de la alerta, y las tres cosas que se pueden hacer con
   ella: asignarla, dejar una nota, y darla por revisada.

   LA FILA CRUDA SE MUESTRA ENTERA. Cada reporte guarda campos distintos en
   `row_data` y son la evidencia de por qué esta alerta existe. Elegir cuáles
   mostrar sería decidir por el analista qué es relevante en un reporte que
   todavía no existe; mostrarlos todos, con su nombre técnico, deja que él
   decida y no esconde nada.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { InsigniaCaso, InsigniaPrioridad } from '../comun/Insignia.jsx';
import {
  correoDe, fecha, filaDelReporte, hace, montoDe, montoTexto, nombreLegible,
  prioridadDe, scoreDe,
} from '../comun/alertas.js';
import { soloLectura } from '../permisos.js';

function Dato({ etiqueta, children }) {
  return (
    <>
      <dt>{etiqueta}</dt>
      <dd>{children}</dd>
    </>
  );
}

/** Un valor de `row_data`, formateado sin inventarle significado. */
function valorCrudo(v) {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function Triage({ api, perfil, email, alertId, navegar }) {
  const [alerta, setAlerta] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState('');
  const [nota, setNota] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      // No hay `GET /alerts/{id}`: se trae la lista y se busca. Con 122
      // alertas son 125 KB, aceptable; si la bandeja creciera mucho, esto es
      // lo primero que conviene convertir en un endpoint propio.
      const d = await api.get('/alerts');
      const encontrada = (d?.alerts || []).find((a) => a.alert_id === alertId);
      if (!encontrada) {
        setError('Esa alerta no está en la bandeja activa. Puede que ya se la haya revisado.');
        setAlerta(null);
      } else {
        setAlerta(encontrada);
        setNota(encontrada.notes || '');
      }
    } catch (e) {
      setError(e?.message || 'No se pudo cargar la alerta.');
    } finally {
      setCargando(false);
    }
  }, [api, alertId]);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    let vivo = true;
    api.get('/crm/users')
      .then((d) => { if (vivo) setUsuarios(d?.users || []); })
      .catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  const fila = useMemo(() => filaDelReporte(alerta), [alerta]);
  const monto = useMemo(() => montoDe(alerta), [alerta]);

  async function accion(nombre, fn, mensaje) {
    setGuardando(nombre);
    setAviso('');
    setError('');
    try {
      await fn();
      setAviso(mensaje);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo completar la acción.');
    } finally {
      setGuardando('');
    }
  }

  const asignar = (a) => accion('asignar',
    () => api.post(`/alerts/${alertId}/assign`, { assigned_to: a }),
    `Asignada a ${a}.`);

  const guardarNota = () => accion('nota',
    () => api.post(`/alerts/${alertId}/notes`, { notes: nota }),
    'Nota guardada.');

  const revisar = () => {
    // Marcarla revisada la saca de la bandeja activa. No es destructivo
    // —queda en "Ya revisados"— pero sí saca trabajo de la vista de todos,
    // así que se pregunta.
    const ok = globalThis.confirm(
      'Marcar esta alerta como revisada la saca de la bandeja activa. ¿Seguro?',
    );
    if (!ok) return;
    accion('revisar',
      () => api.post(`/alerts/${alertId}/review`, { reviewed_by: email, notes: nota }),
      'Alerta marcada como revisada.');
  };

  return (
    <>
      <nav className="wt-migas">
        <button onClick={() => navegar('dashboard')}>Bandeja de alertas</button>
        <span>›</span>
        <span className="mono">{alertId}</span>
      </nav>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {cargando ? (
        <p className="wt-estado">Cargando…</p>
      ) : !alerta ? null : (
        <div className="wt-triage">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--e-4)' }}>
            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">{alerta.reason || nombreLegible(alerta.report_name)}</h2>
                <div className="wt-carta-herramientas">
                  <InsigniaPrioridad prioridad={prioridadDe(alerta)} />
                  <InsigniaCaso alerta={alerta} />
                </div>
              </header>
              <div className="wt-cuerpo-carta">
                <dl className="wt-datos">
                  <Dato etiqueta="Cliente">
                    <span className="mono">{alerta.entity_value}</span>
                    <span style={{ color: 'var(--texto-mute)' }}> · {alerta.entity_field}</span>
                  </Dato>
                  {correoDe(alerta) && <Dato etiqueta="Correo">{correoDe(alerta)}</Dato>}
                  <Dato etiqueta="Reporte">
                    <span className="mono">{alerta.report_name}</span>
                  </Dato>
                  <Dato etiqueta="Puntaje">
                    {scoreDe(alerta) === null
                      ? <span style={{ color: 'var(--texto-mute)' }}>
                          El reporte no dejó puntaje: esta alerta no se evaluó
                        </span>
                      : `${scoreDe(alerta).toFixed(2)} de 100`}
                  </Dato>
                  {monto && (
                    <Dato etiqueta={monto.etiqueta}>
                      {montoTexto(monto)}
                      <span style={{ color: 'var(--texto-mute)' }}> · {monto.campo}</span>
                    </Dato>
                  )}
                  <Dato etiqueta="Entró">
                    {hace(alerta.created_at)}
                    <span style={{ color: 'var(--texto-mute)' }}>
                      {' · '}{fecha(alerta.created_at)?.toLocaleString('es-CL') || alerta.created_at}
                    </span>
                  </Dato>
                  <Dato etiqueta="Asignada a">
                    {alerta.assigned_to || (
                      <span style={{ color: 'var(--nivel-alto-texto)' }}>sin asignar</span>
                    )}
                  </Dato>
                  {alerta.tiene_caso && (
                    <Dato etiqueta="Caso">
                      <span className="mono">{alerta.caso_id}</span>
                      <span style={{ color: 'var(--texto-mute)' }}>
                        {alerta.caso_vinculo === 'vinculado'
                          ? ' · atado a esta alerta'
                          : ' · del cliente, no atado a esta alerta'}
                      </span>
                    </Dato>
                  )}
                </dl>
              </div>
            </section>

            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">La fila del reporte</h2>
                <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                  {Object.keys(fila).length} campo{Object.keys(fila).length === 1 ? '' : 's'}
                </span>
              </header>
              {Object.keys(fila).length === 0 ? (
                <p className="wt-estado">
                  Esta alerta no trae la fila del reporte, o llegó ilegible.
                </p>
              ) : (
                <div className="wt-tabla-marco">
                  <table className="wt-tabla">
                    <thead>
                      <tr><th style={{ width: '40%' }}>Campo</th><th>Valor</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(fila).map(([k, v]) => (
                        <tr key={k}>
                          <td className="wt-td-mono">{k}</td>
                          <td>{valorCrudo(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          <section className="wt-carta">
            <header className="wt-carta-cabecera">
              <h2 className="wt-carta-titulo">Qué hacer</h2>
            </header>
            <div className="wt-cuerpo-carta wt-acciones">
              {lectura ? (
                <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
                  Tu perfil es de consulta: podés ver la alerta, pero no modificarla.
                </p>
              ) : (
                <>
                  <button
                    className="wt-btn wt-btn-primario"
                    disabled={guardando === 'asignar' || alerta.assigned_to === email}
                    onClick={() => asignar(email)}
                  >
                    {alerta.assigned_to === email ? 'Ya es tuya' : 'Asignármela'}
                  </button>

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    O asignar a otra persona
                    <select
                      className="wt-input"
                      style={{ width: '100%', marginTop: 4 }}
                      value=""
                      disabled={guardando === 'asignar'}
                      onChange={(e) => e.target.value && asignar(e.target.value)}
                    >
                      <option value="">Elegir…</option>
                      {usuarios.map((u) => (
                        <option key={u.email} value={u.email}>
                          {u.full_name || u.email}{u.equipo ? ` · ${u.equipo}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    Nota
                    <textarea
                      className="wt-input"
                      style={{ width: '100%', marginTop: 4, minHeight: 80, resize: 'vertical' }}
                      value={nota}
                      onChange={(e) => setNota(e.target.value)}
                      placeholder="Qué se revisó, qué se concluyó…"
                    />
                  </label>
                  <button className="wt-btn" disabled={guardando === 'nota'} onClick={guardarNota}>
                    Guardar la nota
                  </button>

                  <hr style={{ border: 0, borderTop: '1px solid var(--borde)', margin: 'var(--e-2) 0' }} />

                  <button className="wt-btn" disabled={guardando === 'revisar'} onClick={revisar}>
                    Marcar como revisada
                  </button>
                  <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                    Sale de la bandeja activa y pasa a «Ya revisados». La nota de arriba se
                    guarda junto con la revisión.
                  </p>
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
