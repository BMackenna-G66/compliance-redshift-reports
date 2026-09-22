/* ============================================================================
   Administración
   ----------------------------------------------------------------------------
   Lo que configura el sistema y no un caso: las reglas que abren casos solas,
   a quién le llegan los avisos de Slack, quiénes son los analistas del CRM y
   qué reportes corren programados.

   POR QUÉ ESTÁ SEPARADO DE «USUARIOS Y PERMISOS». Son dos padrones distintos
   y confundirlos es un clásico: `wt_roles` en Firestore decide QUÉ VE cada
   persona en esta aplicación, y `/users` es el padrón del CRM que decide A
   QUIÉN SE LE ASIGNAN casos y alertas. Alguien puede estar en uno y no en el
   otro, y las dos situaciones son legítimas.

   LA PROGRAMACIÓN ES DE SÓLO LECTURA acá. Las expresiones de EventBridge se
   cambian en la infraestructura, no desde el navegador: un reporte pesado con
   un asterisco de más corre cada minuto contra Redshift.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { esAdmin, soloLectura } from '../permisos.js';

const VISTAS = [
  { clave: 'reglas', titulo: 'Reglas', pie: 'abren casos solas' },
  { clave: 'slack', titulo: 'Slack', pie: 'a quién le llegan los avisos' },
  { clave: 'analistas', titulo: 'Analistas del CRM', pie: 'a quién se le asigna' },
  { clave: 'programacion', titulo: 'Programación', pie: 'qué corre solo y cuándo' },
];

function Carta({ titulo, cuenta, herramientas, children }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{titulo}</h2>
        {cuenta !== undefined && (
          <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>{cuenta}</span>
        )}
        {herramientas && <div className="wt-carta-herramientas">{herramientas}</div>}
      </header>
      <div className="wt-cuerpo-carta">{children}</div>
    </section>
  );
}

/* ── Reglas ──────────────────────────────────────────────────────────────── */

const REGLA_VACIA = {
  name: '', report_name: '', field_name: '', field_value: '', row_threshold: 1,
  priority: 'medium', assigned_to: '', case_title_template: '', enabled: true,
};

function Reglas({ api, lectura, reglas, reportes, alRecargar, alError, alAviso }) {
  const [editando, setEditando] = useState(null);
  const [guardando, setGuardando] = useState(false);

  async function guardar() {
    if (!editando.name.trim()) { alError('La regla necesita un nombre.'); return; }
    setGuardando(true);
    try {
      await (editando.id
        ? api.post(`/rules/${editando.id}`, editando)
        : api.post('/rules', editando));
      alAviso(`Regla «${editando.name}» guardada.`);
      setEditando(null);
      await alRecargar();
    } catch (e) {
      alError(e?.message || 'No se pudo guardar la regla.');
    } finally {
      setGuardando(false);
    }
  }

  async function borrar(r) {
    if (!globalThis.confirm(`¿Eliminar la regla «${r.name}»?\n\n`
      + 'Deja de abrir casos sola. Los casos que ya abrió no se tocan.')) return;
    try {
      await api.del(`/rules/${r.id}`);
      alAviso(`Regla «${r.name}» eliminada.`);
      await alRecargar();
    } catch (e) {
      alError(e?.message || 'No se pudo eliminar la regla.');
    }
  }

  return (
    <>
      {editando && (
        <Carta titulo={editando.id ? 'Editar la regla' : 'Nueva regla'}>
          <div className="wt-parametros">
            <label className="wt-parametro">
              <span>Nombre</span>
              <input className="wt-input" value={editando.name}
                     onChange={(e) => setEditando((x) => ({ ...x, name: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Sobre qué reporte</span>
              <select className="wt-input" value={editando.report_name}
                      onChange={(e) => setEditando((x) => ({ ...x, report_name: e.target.value }))}>
                <option value="">Cualquiera</option>
                {reportes.map((r) => (
                  <option key={r.report_name} value={r.report_name}>
                    {r.display_name || r.report_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="wt-parametro">
              <span>Campo</span>
              <input className="wt-input" value={editando.field_name} placeholder="country"
                     onChange={(e) => setEditando((x) => ({ ...x, field_name: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Valor</span>
              <input className="wt-input" value={editando.field_value} placeholder="VE"
                     onChange={(e) => setEditando((x) => ({ ...x, field_value: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Desde cuántas filas</span>
              <input className="wt-input" type="number" min="1" value={editando.row_threshold}
                     onChange={(e) => setEditando((x) => ({
                       ...x, row_threshold: Number(e.target.value) || 1 }))} />
            </label>
            <label className="wt-parametro">
              <span>Prioridad del caso</span>
              <select className="wt-input" value={editando.priority}
                      onChange={(e) => setEditando((x) => ({ ...x, priority: e.target.value }))}>
                <option value="high">Alta</option><option value="medium">Media</option>
                <option value="low">Baja</option>
              </select>
            </label>
            <label className="wt-parametro">
              <span>Se lo asigna a</span>
              <input className="wt-input" value={editando.assigned_to} placeholder="correo@global66.com"
                     onChange={(e) => setEditando((x) => ({ ...x, assigned_to: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Título del caso</span>
              <input className="wt-input" value={editando.case_title_template}
                     placeholder="Caso: {entity}"
                     onChange={(e) => setEditando((x) => ({
                       ...x, case_title_template: e.target.value }))} />
            </label>
          </div>
          <label className="wt-checklist-item" style={{ marginTop: 'var(--e-3)', cursor: 'pointer' }}>
            <input type="checkbox" checked={Boolean(editando.enabled)}
                   onChange={(e) => setEditando((x) => ({ ...x, enabled: e.target.checked }))} />
            <span>Activa</span>
          </label>
          <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
            <button className="wt-btn wt-btn-primario" disabled={guardando} onClick={guardar}>
              {guardando ? 'Guardando…' : 'Guardar'}
            </button>
            <button className="wt-btn" onClick={() => setEditando(null)}>Cancelar</button>
          </div>
        </Carta>
      )}

      <Carta
        titulo="Reglas de alertamiento" cuenta={reglas.length}
        herramientas={!lectura && !editando && (
          <button className="wt-btn wt-btn-primario"
                  onClick={() => setEditando({ ...REGLA_VACIA })}>Nueva</button>
        )}
      >
        <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
          Cuando una corrida deja filas que cumplen la condición, la regla abre el caso
          sola y se lo asigna a quien diga.
        </p>
        <div className="wt-tabla-marco">
          <table className="wt-tabla">
            <thead>
              <tr><th>Regla</th><th>Reporte</th><th>Condición</th><th>Desde</th>
                <th>Asignada a</th><th>Estado</th><th /></tr>
            </thead>
            <tbody>
              {reglas.length === 0 ? (
                <tr><td colSpan={7}>Ninguna regla configurada.</td></tr>
              ) : reglas.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="wt-td-mono">{r.report_name || 'cualquiera'}</td>
                  <td>{r.field_name ? `${r.field_name} = ${r.field_value}` : '—'}</td>
                  <td className="wt-td-num">{r.row_threshold ?? 1}</td>
                  <td>{r.assigned_to || '—'}</td>
                  <td style={{ color: r.enabled ? 'var(--nivel-bajo-texto)' : 'var(--texto-mute)' }}>
                    {r.enabled ? 'activa' : 'apagada'}
                  </td>
                  <td>
                    {!lectura && (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => setEditando({ ...REGLA_VACIA, ...r })}>Editar</button>
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => borrar(r)}>Borrar</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Carta>
    </>
  );
}

/* ── Slack ───────────────────────────────────────────────────────────────── */

function Slack({ api, lectura, datos, alRecargar, alError, alAviso }) {
  const [borrador, setBorrador] = useState({});
  const [guardando, setGuardando] = useState('');

  async function guardar(u) {
    const id = (borrador[u.email] ?? u.slack_user_id ?? '').trim();
    setGuardando(u.email);
    try {
      await api.post('/slack-users', { email: u.email, slack_user_id: id });
      alAviso(`Guardado: ${u.full_name || u.email}`);
      await alRecargar();
    } catch (e) {
      alError(e?.message || 'No se pudo guardar.');
    } finally {
      setGuardando('');
    }
  }

  async function quitar(u) {
    if (!globalThis.confirm(`¿Quitar el mapeo de ${u.email}?\n\n`
      + 'Deja de recibir los avisos por Slack; los del correo no se tocan.')) return;
    try {
      await api.del(`/slack-users/${encodeURIComponent(u.email)}`);
      alAviso(`Mapeo de ${u.email} quitado.`);
      await alRecargar();
    } catch (e) {
      alError(e?.message || 'No se pudo quitar el mapeo.');
    }
  }

  const analistas = datos?.analistas || [];
  const sinMapear = analistas.filter((a) => !a.slack_user_id).length;

  return (
    <Carta titulo="Destinatarios de Slack" cuenta={`${datos?.total_con_id ?? 0} con id`}>
      {/* Que falten mapeos no es un error, pero sí una explicación: alguien
          que no recibe avisos y no sabe por qué los busca acá. */}
      {sinMapear > 0 && (
        <p className="wt-nota">
          {sinMapear} analista(s) sin id de Slack: los avisos de sus alertas no les
          llegan por ahí.
        </p>
      )}
      <div className="wt-tabla-marco">
        <table className="wt-tabla">
          <thead><tr><th>Analista</th><th>Correo</th><th>Id de Slack</th><th /></tr></thead>
          <tbody>
            {analistas.length === 0 ? (
              <tr><td colSpan={4}>No se pudo leer la lista.</td></tr>
            ) : analistas.map((u) => (
              <tr key={u.email}>
                <td>{u.full_name || '—'}</td>
                <td className="wt-td-mono">{u.email}</td>
                <td>
                  {lectura ? (u.slack_user_id || '—') : (
                    <input className="wt-input" style={{ width: 160 }}
                           value={borrador[u.email] ?? u.slack_user_id ?? ''}
                           placeholder="U01ABC…"
                           onChange={(e) => setBorrador((b) => ({ ...b, [u.email]: e.target.value }))} />
                  )}
                </td>
                <td>
                  {!lectura && (
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button className="wt-btn" style={{ padding: '2px 8px' }}
                              disabled={guardando === u.email} onClick={() => guardar(u)}>
                        Guardar
                      </button>
                      {u.slack_user_id && (
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => quitar(u)}>Quitar</button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Carta>
  );
}

/* ── Analistas del CRM ───────────────────────────────────────────────────── */

const ANALISTA_VACIO = { email: '', full_name: '', role_id: '', equipo: '', is_active: true };

function Analistas({ api, administra, usuarios, alRecargar, alError, alAviso }) {
  const [editando, setEditando] = useState(null);
  const [guardando, setGuardando] = useState(false);

  async function guardar() {
    if (!editando.id && !editando.email.trim()) { alError('Falta el correo.'); return; }
    setGuardando(true);
    try {
      if (editando.id) {
        await api.post(`/users/${editando.id}`, {
          full_name: editando.full_name, role_id: editando.role_id,
          is_active: editando.is_active, equipo: editando.equipo || '',
        });
      } else {
        await api.post('/users', {
          email: editando.email.trim(), full_name: editando.full_name,
          role_id: editando.role_id, equipo: editando.equipo || '',
        });
      }
      alAviso(`Analista ${editando.full_name || editando.email} guardado.`);
      setEditando(null);
      await alRecargar();
    } catch (e) {
      alError(e?.message || 'No se pudo guardar.');
    } finally {
      setGuardando(false);
    }
  }

  async function desactivar(u) {
    if (!globalThis.confirm(`¿Desactivar a ${u.full_name || u.email}?\n\n`
      + 'Deja de aparecer para asignarle casos. Los que ya tiene NO se reasignan solos: '
      + 'hay que moverlos a mano.')) return;
    try {
      await api.del(`/users/${u.id}`);
      alAviso(`${u.full_name || u.email} desactivado.`);
      await alRecargar();
    } catch (e) {
      alError(e?.message || 'No se pudo desactivar.');
    }
  }

  return (
    <>
      {/* El malentendido clásico: dos padrones distintos. */}
      <p className="wt-nota">
        Éste es el padrón del CRM: decide <strong>a quién se le asignan</strong> casos y
        alertas. Quién puede <strong>entrar y qué ve</strong> se maneja en «Usuarios y
        permisos», que es otra lista. Alguien puede estar en una y no en la otra.
      </p>

      {editando && (
        <Carta titulo={editando.id ? 'Editar analista' : 'Nuevo analista'}>
          <div className="wt-parametros">
            <label className="wt-parametro">
              <span>Correo</span>
              <input className="wt-input" value={editando.email} disabled={Boolean(editando.id)}
                     onChange={(e) => setEditando((x) => ({ ...x, email: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Nombre</span>
              <input className="wt-input" value={editando.full_name}
                     onChange={(e) => setEditando((x) => ({ ...x, full_name: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Equipo</span>
              <input className="wt-input" value={editando.equipo}
                     onChange={(e) => setEditando((x) => ({ ...x, equipo: e.target.value }))} />
            </label>
            <label className="wt-parametro">
              <span>Rol</span>
              <input className="wt-input" value={editando.role_id}
                     onChange={(e) => setEditando((x) => ({ ...x, role_id: e.target.value }))} />
            </label>
          </div>
          {editando.id && (
            <label className="wt-checklist-item" style={{ marginTop: 'var(--e-3)', cursor: 'pointer' }}>
              <input type="checkbox" checked={Boolean(editando.is_active)}
                     onChange={(e) => setEditando((x) => ({ ...x, is_active: e.target.checked }))} />
              <span>Activo</span>
            </label>
          )}
          <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
            <button className="wt-btn wt-btn-primario" disabled={guardando} onClick={guardar}>
              {guardando ? 'Guardando…' : 'Guardar'}
            </button>
            <button className="wt-btn" onClick={() => setEditando(null)}>Cancelar</button>
          </div>
        </Carta>
      )}

      <Carta
        titulo="Analistas del CRM" cuenta={usuarios.length}
        herramientas={administra && !editando && (
          <button className="wt-btn wt-btn-primario"
                  onClick={() => setEditando({ ...ANALISTA_VACIO })}>Nuevo</button>
        )}
      >
        <div className="wt-tabla-marco">
          <table className="wt-tabla">
            <thead>
              <tr><th>Nombre</th><th>Correo</th><th>Equipo</th><th>Rol</th>
                <th>Estado</th><th>Último ingreso</th><th /></tr>
            </thead>
            <tbody>
              {usuarios.length === 0 ? (
                <tr><td colSpan={7}>No se pudo leer el padrón.</td></tr>
              ) : usuarios.map((u) => (
                <tr key={u.id || u.email}>
                  <td>{u.full_name || '—'}</td>
                  <td className="wt-td-mono">{u.email}</td>
                  <td>{u.equipo || '—'}</td>
                  <td>{u.role_name || u.role_id || '—'}</td>
                  <td style={{ color: u.is_active ? 'var(--nivel-bajo-texto)' : 'var(--texto-mute)' }}>
                    {u.is_active ? 'activo' : 'inactivo'}
                  </td>
                  <td>{(u.last_login_at || '').slice(0, 10) || '—'}</td>
                  <td>
                    {administra && (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => setEditando({ ...ANALISTA_VACIO, ...u })}>
                          Editar
                        </button>
                        {u.is_active && (
                          <button className="wt-btn" style={{ padding: '2px 8px' }}
                                  onClick={() => desactivar(u)}>Desactivar</button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Carta>
    </>
  );
}

/* ── Programación ────────────────────────────────────────────────────────── */

function Programacion({ programadas }) {
  return (
    <Carta titulo="Reportes programados" cuenta={programadas.length}>
      {/* Se muestra pero no se toca: un asterisco de más en una expresión de
          EventBridge hace que un reporte pesado corra cada minuto contra
          Redshift, y eso se paga. Se cambia en la infraestructura. */}
      <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
        Sólo lectura: las expresiones se cambian en la infraestructura, no desde acá. Un
        asterisco de más hace que un reporte pesado corra cada minuto contra Redshift.
      </p>
      <div className="wt-tabla-marco">
        <table className="wt-tabla">
          <thead><tr><th>Nombre</th><th>Cuándo</th><th>Estado</th><th>Qué hace</th></tr></thead>
          <tbody>
            {programadas.length === 0 ? (
              <tr><td colSpan={4}>No hay nada programado.</td></tr>
            ) : programadas.map((s) => (
              <tr key={s.name}>
                <td className="wt-td-mono">{s.name}</td>
                <td className="wt-td-mono">{s.schedule || '—'}</td>
                <td style={{ color: s.state === 'ENABLED'
                  ? 'var(--nivel-bajo-texto)' : 'var(--texto-mute)' }}>
                  {s.state === 'ENABLED' ? 'activo' : 'apagado'}
                </td>
                <td style={{ whiteSpace: 'normal' }}>{s.description || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Carta>
  );
}

/* ── La pantalla ─────────────────────────────────────────────────────────── */

export function Administracion({ api, perfil }) {
  const [vista, setVista] = useState('reglas');
  const [reglas, setReglas] = useState([]);
  const [reportes, setReportes] = useState([]);
  const [slack, setSlack] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [programadas, setProgramadas] = useState([]);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [cargando, setCargando] = useState(true);

  const lectura = soloLectura(perfil);
  const administra = esAdmin(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    // `allSettled`: que falle una lista no puede dejar la pantalla en blanco.
    // Cada pestaña es independiente de las otras.
    const [r, s, u, p, rep] = await Promise.allSettled([
      api.get('/rules'), api.get('/slack-users'), api.get('/users'),
      api.get('/schedules'), api.get('/reports'),
    ]);
    if (r.status === 'fulfilled') setReglas(r.value?.rules || []);
    if (s.status === 'fulfilled') setSlack(s.value || null);
    if (u.status === 'fulfilled') setUsuarios(u.value?.users || []);
    if (p.status === 'fulfilled') setProgramadas(p.value?.schedules || []);
    if (rep.status === 'fulfilled') setReportes(rep.value?.reports || []);
    const fallas = [r, s, u, p, rep].filter((x) => x.status === 'rejected');
    if (fallas.length) {
      setError(`${fallas.length} de 5 consultas no respondieron: `
             + `${fallas[0].reason?.message || 'error'}`);
    }
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const comun = {
    api, lectura, administra, alRecargar: cargar, alError: setError,
    alAviso: (m) => { setAviso(m); setError(''); },
  };

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Administración
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          lo que configura el sistema, no un caso
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }}
                onClick={cargar} disabled={cargando}>Refrescar</button>
      </div>

      <nav className="wt-pasos" aria-label="Áreas de administración">
        {VISTAS.map((v) => (
          <button key={v.clave} className={`wt-paso-boton${vista === v.clave ? ' wt-paso-activo' : ''}`}
                  onClick={() => setVista(v.clave)}>
            <span>
              <span className="wt-paso-titulo">{v.titulo}</span>
              <span className="wt-paso-pie">{v.pie}</span>
            </span>
          </button>
        ))}
      </nav>

      {error && (
        <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>
      )}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {cargando ? <p className="wt-estado">Cargando…</p> : (
        <>
          {vista === 'reglas' && <Reglas {...comun} reglas={reglas} reportes={reportes} />}
          {vista === 'slack' && <Slack {...comun} datos={slack} />}
          {vista === 'analistas' && <Analistas {...comun} usuarios={usuarios} />}
          {vista === 'programacion' && <Programacion programadas={programadas} />}
        </>
      )}
    </>
  );
}
