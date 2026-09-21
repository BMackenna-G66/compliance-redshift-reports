/* ============================================================================
   Detalle del caso
   ----------------------------------------------------------------------------
   POR QUÉ SE PIDEN DOS COSAS. `GET /cases/{id}` devuelve el caso con sus
   notas y sus alertas, pero NO los campos `sla_*`: el semáforo se calcula en
   `GET /cases`, sobre la lista. Así que se piden las dos y se juntan.

   La alternativa era recalcular el plazo acá, y eso es justo lo que no se
   hace: la regla es de compliance y tener dos definiciones del mismo plazo
   termina en una pantalla que dice "en plazo" sobre un caso que el sistema
   considera vencido. Traer 76 KB de más es barato al lado de eso.

   Queda anotado como mejora de backend: que `GET /cases/{id}` devuelva los
   `sla_*` como los devuelve la lista.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { InsigniaSla } from '../comun/InsigniaSla.jsx';
import { fecha, hace } from '../comun/alertas.js';
import { diasTexto, sinContactar } from '../comun/casos.js';
import { ESTADOS_CASO } from '../dominio.js';
import { soloLectura } from '../permisos.js';

const ESTADOS_ELEGIBLES = ['open', 'in_progress', 'under_review', 'closed'];

function Dato({ etiqueta, children }) {
  return (<><dt>{etiqueta}</dt><dd>{children}</dd></>);
}

export function Caso({ api, perfil, email, id: casoId, navegar }) {
  const [caso, setCaso] = useState(null);
  const [notas, setNotas] = useState([]);
  const [alertas, setAlertas] = useState([]);
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
      const [detalle, lista] = await Promise.all([
        api.get(`/cases/${casoId}`),
        // Sólo por los campos del semáforo. Si esta falla, el caso igual se
        // muestra: se pierde el plazo, no la pantalla entera.
        api.get('/cases?status=all').catch(() => null),
      ]);
      const delListado = (lista?.cases || []).find((c) => c.case_id === casoId) || {};
      setCaso({ ...delListado, ...(detalle?.case || {}) , ...slaDe(delListado) });
      setNotas(detalle?.notes || []);
      setAlertas(detalle?.alerts || []);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el caso.');
      setCaso(null);
    } finally {
      setCargando(false);
    }
  }, [api, casoId]);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    let vivo = true;
    api.get('/crm/users').then((d) => { if (vivo) setUsuarios(d?.users || []); }).catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  const estado = useMemo(() => ESTADOS_CASO[caso?.status], [caso]);

  async function accion(nombre, fn, mensaje) {
    setGuardando(nombre); setAviso(''); setError('');
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

  function cambiarEstado(nuevo) {
    if (!nuevo || nuevo === caso.status) return;
    if (nuevo === 'closed' &&
        !globalThis.confirm('Cerrar el caso deja registrada la fecha de cierre. ¿Seguro?')) return;
    accion('estado', () => api.post(`/cases/${casoId}/status`, { status: nuevo }),
      `Estado cambiado a «${ESTADOS_CASO[nuevo]?.etiqueta || nuevo}».`);
  }

  const asignar = (a) => accion('asignar',
    () => api.post(`/cases/${casoId}/assign`, { assigned_to: a }), `Asignado a ${a}.`);

  const agregarNota = () => {
    if (!nota.trim()) return;
    accion('nota', async () => {
      await api.post(`/cases/${casoId}/notes`, { content: nota.trim(), author_email: email });
      setNota('');
    }, 'Nota agregada.');
  };

  return (
    <>
      <nav className="wt-migas">
        <button onClick={() => navegar('cases')}>Casos</button>
        <span>›</span>
        <span className="mono">{casoId}</span>
      </nav>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {cargando && !caso ? (
        <p className="wt-estado">Cargando…</p>
      ) : !caso ? null : (
        <div className="wt-triage">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--e-4)' }}>
            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">
                  {/* El nombre si lo hay; si no, el id. El `title` no va
                      acá: en 72 de 89 casos es el nombre del reporte. */}
                  {caso.entity_name || `Cliente ${caso.entity_id || ''}`.trim()}
                </h2>
                <div className="wt-carta-herramientas">
                  <span className="wt-insignia"
                        style={{ color: estado?.color || 'var(--texto-2)',
                                 background: 'var(--superficie-3)' }}>
                    {estado?.etiqueta || caso.status}
                  </span>
                  <InsigniaSla caso={caso} />
                </div>
              </header>
              <div className="wt-cuerpo-carta">
                <dl className="wt-datos">
                  <Dato etiqueta="Cliente">
                    <span className="mono">{caso.entity_id}</span>
                    {caso.entity_name && <> · {caso.entity_name}</>}
                    {caso.entity_id && (
                      <button className="wt-btn" style={{ marginLeft: 8, padding: '2px 8px' }}
                              onClick={() => navegar('ficha', [caso.entity_id])}>
                        Ver ficha
                      </button>
                    )}
                  </Dato>
                  {caso.title && caso.title !== caso.entity_name &&
                    <Dato etiqueta="Título">{caso.title}</Dato>}
                  {caso.description && <Dato etiqueta="Descripción">{caso.description}</Dato>}
                  {caso.report_name &&
                    <Dato etiqueta="Reporte de origen"><span className="mono">{caso.report_name}</span></Dato>}
                  <Dato etiqueta="Abierto hace">
                    {diasTexto(caso.sla_dias)}
                    <span style={{ color: 'var(--texto-mute)' }}>
                      {' · desde '}{fecha(caso.created_at)?.toLocaleString('es-CL') || caso.created_at}
                    </span>
                  </Dato>
                  {caso.sla_aplica && (
                    <Dato etiqueta="Contactos al cliente">
                      {sinContactar(caso)
                        ? <span style={{ color: 'var(--nivel-alto-texto)', fontWeight: 'var(--peso-medio)' }}>
                            nunca se le escribió
                          </span>
                        : <>{caso.sla_contactos}
                            {caso.sla_ultimo_contacto &&
                              <span style={{ color: 'var(--texto-mute)' }}>
                                {' · el último '}{hace(caso.sla_ultimo_contacto)}
                              </span>}
                          </>}
                      {caso.sla_respondio && (
                        <span style={{ color: 'var(--nivel-bajo-texto)', marginLeft: 8 }}>
                          el cliente respondió
                        </span>
                      )}
                    </Dato>
                  )}
                  <Dato etiqueta="Asignado a">
                    {caso.assigned_to || (
                      <span style={{ color: 'var(--nivel-alto-texto)' }}>sin asignar</span>
                    )}
                  </Dato>
                  <Dato etiqueta="Creado por">{caso.created_by || '—'}</Dato>
                  {caso.closed_at && <Dato etiqueta="Cerrado">{caso.closed_at}</Dato>}
                </dl>
              </div>
            </section>

            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">Notas</h2>
                <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                  {notas.length}
                </span>
              </header>
              <div className="wt-cuerpo-carta">
                {notas.length === 0 ? (
                  <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                    Todavía no hay notas en este caso.
                  </p>
                ) : notas.map((nt) => (
                  <article key={nt.note_id} className="wt-nota-caso">
                    <div className="wt-nota-caso-meta">
                      {/* El autor puede faltar: hubo notas guardadas sin él. */}
                      {nt.author_email || 'autor desconocido'}
                      {' · '}
                      <span title={nt.created_at}>{hace(nt.created_at)}</span>
                    </div>
                    <div className="wt-nota-caso-texto">{nt.content}</div>
                  </article>
                ))}
              </div>
            </section>

            {alertas.length > 0 && (
              <section className="wt-carta">
                <header className="wt-carta-cabecera">
                  <h2 className="wt-carta-titulo">Alertas atadas</h2>
                  <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    {alertas.length}
                  </span>
                </header>
                <div className="wt-tabla-marco">
                  <table className="wt-tabla">
                    <thead><tr><th>Motivo</th><th>Reporte</th><th>Entró</th><th /></tr></thead>
                    <tbody>
                      {alertas.map((a) => (
                        <tr key={a.alert_id}>
                          <td style={{ whiteSpace: 'normal' }}>{a.reason || '—'}</td>
                          <td className="wt-td-mono">{a.report_name}</td>
                          <td title={a.created_at}>{hace(a.created_at)}</td>
                          <td>
                            <button className="wt-btn"
                                    onClick={() => navegar('alert', [a.alert_id])}>
                              Abrir
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>

          <section className="wt-carta">
            <header className="wt-carta-cabecera">
              <h2 className="wt-carta-titulo">Qué hacer</h2>
            </header>
            <div className="wt-cuerpo-carta wt-acciones">
              {lectura ? (
                <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
                  Tu perfil es de consulta: podés ver el caso, pero no modificarlo.
                </p>
              ) : (
                <>
                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    Estado
                    <select className="wt-input" style={{ width: '100%', marginTop: 4 }}
                            value={caso.status} disabled={guardando === 'estado'}
                            onChange={(e) => cambiarEstado(e.target.value)}>
                      {ESTADOS_ELEGIBLES.map((k) => (
                        <option key={k} value={k}>{ESTADOS_CASO[k]?.etiqueta || k}</option>
                      ))}
                      {/* Un estado que el backend puso y no está en la lista
                          se muestra igual, para no cambiarlo sin querer. */}
                      {!ESTADOS_ELEGIBLES.includes(caso.status) && (
                        <option value={caso.status}>{caso.status}</option>
                      )}
                    </select>
                  </label>

                  <button className="wt-btn wt-btn-primario"
                          disabled={guardando === 'asignar' || caso.assigned_to === email}
                          onClick={() => asignar(email)}>
                    {caso.assigned_to === email ? 'Ya es tuyo' : 'Asignármelo'}
                  </button>

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    O asignar a otra persona
                    <select className="wt-input" style={{ width: '100%', marginTop: 4 }} value=""
                            disabled={guardando === 'asignar'}
                            onChange={(e) => e.target.value && asignar(e.target.value)}>
                      <option value="">Elegir…</option>
                      {usuarios.map((u) => (
                        <option key={u.email} value={u.email}>
                          {u.full_name || u.email}{u.equipo ? ` · ${u.equipo}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>

                  <hr style={{ border: 0, borderTop: '1px solid var(--borde)', margin: 'var(--e-2) 0' }} />

                  {/* El ROS nace del caso: es acá donde alguien concluye que
                      hay sospecha, y desde acá se arma con su evidencia. No
                      reporta nada — abre el borrador en el registro. */}
                  <button className="wt-btn" onClick={() => navegar('ros')}>
                    Reportar a la UAF (ROS)
                  </button>
                  <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                    Abre el registro de ROS para armar el borrador con la evidencia de
                    este caso. No envía nada al regulador.
                  </p>

                  <hr style={{ border: 0, borderTop: '1px solid var(--borde)', margin: 'var(--e-2) 0' }} />

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    Nueva nota
                    <textarea className="wt-input"
                              style={{ width: '100%', marginTop: 4, minHeight: 90, resize: 'vertical' }}
                              value={nota} onChange={(e) => setNota(e.target.value)}
                              placeholder="Qué se revisó, qué se concluyó…" />
                  </label>
                  <button className="wt-btn" disabled={guardando === 'nota' || !nota.trim()}
                          onClick={agregarNota}>
                    Agregar la nota
                  </button>
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}

/** Sólo los campos del semáforo, para que el detalle no los pise con undefined.
 *
 *  `GET /cases/{id}` no los trae; si se hiciera `{...lista, ...detalle}` sin
 *  esto, las claves que el detalle no tiene quedarían igual, pero cualquier
 *  día que el detalle empiece a mandarlas vacías borrarían las buenas. */
function slaDe(c) {
  const salida = {};
  for (const [k, v] of Object.entries(c || {})) {
    if (k.startsWith('sla_') || k === 'note_count') salida[k] = v;
  }
  return salida;
}
