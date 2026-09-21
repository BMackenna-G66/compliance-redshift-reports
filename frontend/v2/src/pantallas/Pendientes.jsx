/* ============================================================================
   Pendientes
   ----------------------------------------------------------------------------
   Las alertas que alguien te asignó a mano y todavía no resolviste, y el
   formulario para asignarle una a otra persona.

   NO SON LAS ALERTAS DE LA BANDEJA. La bandeja es la cola del sistema; esto
   es una nota entre personas: «mirá esto». Se guardan dentro del documento
   de perfil de quien las recibe, que es como lo hace el WatchTower actual.

   Resolver no borra: marca. Quién asignó qué y cuándo es parte del registro.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { Kpi } from '../comun/Kpi.jsx';
import { fecha, hace } from '../comun/alertas.js';
import { asignarPendiente, listarPendientes, resolverPendiente } from '../sesion.js';
import { soloLectura } from '../permisos.js';

export function Pendientes({ api, perfil, email }) {
  const [mios, setMios] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState('');
  const [para, setPara] = useState('');
  const [texto, setTexto] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      setMios(await listarPendientes(email));
    } catch (e) {
      setError(`No se pudieron leer tus pendientes (${e?.message || 'error'}).`);
    } finally {
      setCargando(false);
    }
  }, [email]);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    let vivo = true;
    api.get('/crm/users').then((d) => { if (vivo) setUsuarios(d?.users || []); }).catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  async function resolver(p) {
    if (!globalThis.confirm('¿Marcar como resuelto?')) return;
    setGuardando(p.id); setError(''); setAviso('');
    try {
      await resolverPendiente(email, p.id);
      setAviso('Marcado como resuelto.');
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo marcar.');
    } finally {
      setGuardando('');
    }
  }

  async function asignar(e) {
    e.preventDefault();
    if (!para || !texto.trim()) return;
    setGuardando('asignar'); setError(''); setAviso('');
    try {
      await asignarPendiente(para, { nota: texto.trim(), asignadoPor: email });
      setAviso(`Se le asignó a ${para}.`);
      setPara(''); setTexto('');
    } catch (err) {
      setError(err?.message || 'No se pudo asignar.');
    } finally {
      setGuardando('');
    }
  }

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Tus pendientes" valor={cargando ? '—' : mios.length}
             pie={cargando ? 'leyendo…' : mios.length ? 'sin resolver' : 'nada pendiente'} />
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      <div className="wt-ficha-grilla">
        <section className="wt-carta">
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Asignadas a vos</h2>
            <button className="wt-btn" style={{ marginLeft: 'auto' }}
                    onClick={cargar} disabled={cargando}>Refrescar</button>
          </header>
          <div className="wt-cuerpo-carta">
            {cargando ? (
              <p style={{ margin: 0, color: 'var(--texto-mute)' }}>Cargando…</p>
            ) : mios.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                No tenés nada pendiente.
              </p>
            ) : mios.map((p) => (
              <article key={p.id} className="wt-nota-caso">
                <div className="wt-nota-caso-meta">
                  {p.asignadoPor || 'alguien'}
                  {' · '}
                  <span title={fecha(p.createdAt)?.toLocaleString('es-CL')}>
                    {hace(p.createdAt)}
                  </span>
                </div>
                <div className="wt-nota-caso-texto">{p.nota || p.detalle || '(sin nota)'}</div>
                <button className="wt-btn" style={{ marginTop: 6, padding: '2px 8px' }}
                        disabled={guardando === p.id} onClick={() => resolver(p)}>
                  {guardando === p.id ? '…' : 'Marcar resuelto'}
                </button>
              </article>
            ))}
          </div>
        </section>

        <section className="wt-carta">
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Asignarle algo a alguien</h2>
          </header>
          <div className="wt-cuerpo-carta">
            {lectura ? (
              <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
                Tu perfil es de consulta: podés ver tus pendientes, pero no asignar.
              </p>
            ) : (
              <form onSubmit={asignar} className="wt-acciones">
                <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                  A quién
                  <select className="wt-input" style={{ display: 'block', width: '100%', marginTop: 4 }}
                          value={para} onChange={(e) => setPara(e.target.value)} required>
                    <option value="">Elegir…</option>
                    {usuarios.map((u) => (
                      <option key={u.email} value={u.email}>
                        {u.full_name || u.email}{u.equipo ? ` · ${u.equipo}` : ''}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                  Qué tiene que mirar
                  <textarea className="wt-input"
                            style={{ display: 'block', width: '100%', marginTop: 4,
                                     minHeight: 90, resize: 'vertical' }}
                            value={texto} onChange={(e) => setTexto(e.target.value)}
                            placeholder="El caso de X, la alerta de Y…" required />
                </label>
                <button className="wt-btn wt-btn-primario" type="submit"
                        disabled={guardando === 'asignar' || !para || !texto.trim()}>
                  {guardando === 'asignar' ? 'Asignando…' : 'Asignar'}
                </button>
                <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                  Le aparece en su pantalla de Pendientes. No le llega un correo.
                </p>
              </form>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
