/* ============================================================================
   Usuarios y permisos
   ----------------------------------------------------------------------------
   Cruza las DOS listas: el CRM (quién existe, su equipo) y los perfiles de
   Firestore (qué ve cada uno). Alguien puede estar en una y no en la otra, y
   esas ausencias duelen distinto — por eso se marcan.

   AL GUARDAR NO SE PISAN LOS MÓDULOS DE v1. Los dos fronts escriben en la
   misma colección y manejan listas distintas; lo que esta pantalla no
   muestra, no lo toca. La lógica está en `comun/admin.js` con sus tests.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  PERFILES, cruzar, indicadores, modulosDisponibles, modulosParaGuardar,
  nombrePerfil,
} from '../comun/admin.js';
import { borrarPerfil, guardarPerfil, listarPerfiles } from '../sesion.js';
import { esAdmin } from '../permisos.js';

function Aviso({ fila }) {
  if (fila.sinPerfil) {
    return (
      <span className="wt-insignia"
            style={{ color: 'var(--estado-error-texto)', background: 'var(--estado-error-fondo)' }}
            title="Existe en el CRM pero no tiene perfil: si entra, no ve nada">
        sin perfil
      </span>
    );
  }
  if (fila.sinUsuario) {
    return (
      <span className="wt-insignia"
            style={{ color: 'var(--nivel-alto-texto)', background: 'var(--nivel-alto-tenue)' }}
            title="Tiene perfil pero no está en el CRM: nadie le puede asignar un caso">
        sin usuario
      </span>
    );
  }
  if (fila.activo === false) {
    return <span className="wt-insignia wt-insignia-sindato">inactivo</span>;
  }
  return null;
}

function Editor({ fila, perfilActual, email, alGuardar, alBorrar, alCerrar, guardando }) {
  const disponibles = modulosDisponibles();
  const [rol, setRol] = useState(fila.rol || 'analyst');
  const [modulos, setModulos] = useState(new Set(fila.modulos || []));
  const todo = modulos.has('all');

  function alternar(clave) {
    setModulos((s) => {
      const n = new Set(s);
      if (n.has(clave)) n.delete(clave); else n.add(clave);
      return n;
    });
  }

  /* Los módulos sólo importan para el perfil de lectura: los demás ven todo.
     Decirlo evita que alguien marque casillas creyendo que restringen. */
  const importanLosModulos = rol === 'lectura';

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{fila.nombre || fila.correo}</h2>
        <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
          {fila.correo}
        </span>
        <button className="wt-btn" style={{ marginLeft: 'auto' }} onClick={alCerrar}>
          Cerrar
        </button>
      </header>
      <div className="wt-cuerpo-carta">
        <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Perfil
          <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 260 }}
                  value={rol} onChange={(e) => setRol(e.target.value)}>
            {PERFILES.map((p) => <option key={p.clave} value={p.clave}>{p.etiqueta}</option>)}
          </select>
        </label>
        <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)',
                    margin: '6px 0 var(--e-4)' }}>
          {PERFILES.find((p) => p.clave === rol)?.descripcion}
        </p>

        <h3 style={{ fontSize: 'var(--texto-xs)', textTransform: 'uppercase',
                     letterSpacing: 'var(--track-ancho)', color: 'var(--texto-mute)',
                     margin: '0 0 var(--e-2)' }}>
          Módulos
        </h3>
        {!importanLosModulos && (
          <p className="wt-nota">
            Con el perfil <strong>{nombrePerfil(rol)}</strong> estos módulos no restringen
            nada: sólo se aplican al perfil de sólo lectura. Se guardan igual, por si más
            adelante se le cambia el perfil.
          </p>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 8,
                        marginBottom: 'var(--e-2)', fontSize: 'var(--texto-base)' }}>
          <input type="checkbox" checked={todo} onChange={() => alternar('all')} />
          <strong>Todos los módulos</strong>
          <span style={{ color: 'var(--texto-mute)', fontSize: 'var(--texto-sm)' }}>
            (el comodín: abre todo, incluso lo que se agregue después)
          </span>
        </label>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))',
                      gap: '4px var(--e-4)', opacity: todo ? 0.45 : 1 }}>
          {disponibles.map((m) => (
            <label key={m.clave}
                   style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                            fontSize: 'var(--texto-base)', padding: '2px 0' }}>
              <input type="checkbox" checked={modulos.has(m.clave)} disabled={todo}
                     onChange={() => alternar(m.clave)} style={{ marginTop: 3 }} />
              <span>
                <span className="mono">{m.clave}</span>
                <span style={{ display: 'block', fontSize: 'var(--texto-xs)',
                               color: 'var(--texto-mute)' }}>
                  {m.pantallas.join(' · ')}
                </span>
              </span>
            </label>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
          <button className="wt-btn wt-btn-primario" disabled={guardando}
                  onClick={() => alGuardar(fila, {
                    role: rol,
                    modules: modulosParaGuardar([...modulos], fila.modulos),
                    grantedBy: email,
                  })}>
            {guardando ? 'Guardando…' : 'Guardar el perfil'}
          </button>
          {!fila.sinPerfil && fila.rol !== 'superadmin' && (
            <button className="wt-btn" disabled={guardando} onClick={() => alBorrar(fila)}>
              Quitarle el acceso
            </button>
          )}
        </div>

        {/* Lo que no se ve en las casillas pero se va a guardar igual. */}
        {(() => {
          const conocidos = new Set(disponibles.map((m) => m.clave));
          const ajenos = (fila.modulos || []).filter((m) => !conocidos.has(m) && m !== 'all');
          if (!ajenos.length) return null;
          return (
            <p style={{ marginTop: 'var(--e-3)', marginBottom: 0,
                        fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
              Además tiene {ajenos.map((m) => <code key={m} className="mono">{m} </code>)}
              — módulos del WatchTower actual que esta pantalla no maneja. Se conservan
              tal cual al guardar.
            </p>
          );
        })()}
      </div>
    </section>
  );
}

export function Usuarios({ api, perfil, email }) {
  const [crm, setCrm] = useState([]);
  const [perfiles, setPerfiles] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [abierto, setAbierto] = useState(null);
  const [guardando, setGuardando] = useState(false);
  /* Si los perfiles no se pudieron leer, NO se puede decir quién no tiene.
     Sin esto la pantalla afirmaba «12 personas sin perfil: si entran, no ven
     nada» cuando en realidad sí lo tienen y lo que falló fue la lectura —
     una acusación falsa sobre doce personas concretas. */
  const [hayPerfiles, setHayPerfiles] = useState(false);

  const admin = esAdmin(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    const [u, p] = await Promise.allSettled([api.get('/users'), listarPerfiles()]);
    if (u.status === 'fulfilled') setCrm(u.value?.users || []);
    if (p.status === 'fulfilled') { setPerfiles(p.value || []); setHayPerfiles(true); }
    else setHayPerfiles(false);
    const fallos = [['usuarios del CRM', u], ['perfiles', p]]
      .filter(([, x]) => x.status === 'rejected')
      .map(([n, x]) => `${n} (${x.reason?.message || 'error'})`);
    setError(fallos.length ? `No se pudo cargar: ${fallos.join(' · ')}` : '');
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const filas = useMemo(() => cruzar(crm, perfiles), [crm, perfiles]);
  const ind = useMemo(() => indicadores(filas), [filas]);

  async function guardar(fila, datos) {
    setGuardando(true); setError(''); setAviso('');
    try {
      await guardarPerfil(perfil, fila.correo, datos);
      setAviso(`Perfil de ${fila.correo} guardado.`);
      setAbierto(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo guardar el perfil.');
    } finally {
      setGuardando(false);
    }
  }

  async function borrar(fila) {
    const ok = globalThis.confirm(
      `Quitarle el acceso a ${fila.correo}. Al entrar no va a ver nada. ¿Seguro?`,
    );
    if (!ok) return;
    setGuardando(true); setError(''); setAviso('');
    try {
      await borrarPerfil(perfil, fila.correo);
      setAviso(`${fila.correo} se quedó sin acceso.`);
      setAbierto(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo quitar el acceso.');
    } finally {
      setGuardando(false);
    }
  }

  const columnas = [
    {
      clave: 'correo',
      titulo: 'Persona',
      ancho: '26%',
      render: (f) => (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
          <span style={{ color: 'var(--texto)' }}>{f.nombre || '—'}</span>
          <span className="mono" style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            {f.correo}
          </span>
        </span>
      ),
    },
    { clave: 'equipo', titulo: 'Equipo', ancho: '14%',
      render: (f) => f.equipo || <span style={{ color: 'var(--texto-mute)' }}>—</span> },
    {
      clave: 'rol',
      titulo: 'Perfil',
      ancho: '13%',
      render: (f) => (f.rol
        ? <span style={{ fontWeight: 'var(--peso-medio)' }}>{nombrePerfil(f.rol)}</span>
        : <span style={{ color: 'var(--texto-mute)' }}>—</span>),
      exportar: (f) => nombrePerfil(f.rol),
    },
    {
      clave: '_modulos',
      titulo: 'Módulos',
      ancho: '22%',
      render: (f) => {
        if (f.modulos.includes('all')) return <strong>todos</strong>;
        if (!f.modulos.length) return <span style={{ color: 'var(--texto-mute)' }}>ninguno</span>;
        return (
          <span className="mono" style={{ fontSize: 'var(--texto-xs)', whiteSpace: 'normal',
                                          display: 'block', maxWidth: 300 }}>
            {f.modulos.join(' ')}
          </span>
        );
      },
      exportar: (f) => f.modulos.join(' '),
    },
    {
      clave: '_aviso',
      titulo: 'Estado',
      ancho: '12%',
      buscable: false,
      render: (f) => (hayPerfiles
        ? <Aviso fila={f} />
        : <span style={{ color: 'var(--texto-mute)' }}>—</span>),
      exportar: (f) => (f.sinPerfil ? 'sin perfil' : f.sinUsuario ? 'sin usuario' : 'ok'),
    },
  ];
  if (admin) {
    columnas.push({
      clave: 'correo_accion', titulo: '', ancho: '8%', ordenable: false, buscable: false,
      render: (f) => (
        <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => setAbierto(f)}>Editar</button>
      ),
      exportar: () => '',
    });
  }

  const preparadas = useMemo(() => filas.map((f) => ({
    ...f,
    _modulos: f.modulos.join(' '),
    _aviso: f.sinPerfil ? 'sin perfil' : f.sinUsuario ? 'sin usuario' : '',
  })), [filas]);

  const sinDatos = (cargando || Boolean(error)) && filas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="Personas" valor={n(ind.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer')
                           : `${ind.equipos} equipos`} />
        {/* Los cuatro de abajo salen de los perfiles: si no se leyeron, un
            número acá sería una afirmación inventada sobre gente real. */}
        <Kpi etiqueta="Con acceso" valor={hayPerfiles ? n(ind.conAcceso) : '—'}
             pie={hayPerfiles ? 'tienen perfil' : 'no se pudieron leer'} />
        <Kpi etiqueta="Sin perfil" valor={hayPerfiles ? n(ind.sinPerfil) : '—'}
             pie={hayPerfiles ? 'entran y no ven nada' : 'no se pudieron leer'} />
        <Kpi etiqueta="Sin usuario" valor={hayPerfiles ? n(ind.sinUsuario) : '—'}
             pie={hayPerfiles ? 'no se les puede asignar' : 'no se pudieron leer'} />
        <Kpi etiqueta="Administradores" valor={hayPerfiles ? n(ind.admins) : '—'}
             pie={hayPerfiles ? 'acceso completo' : 'no se pudieron leer'} />
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {!hayPerfiles && !cargando && (
        <p className="wt-nota wt-nota-alarma">
          <strong>No se pudieron leer los perfiles.</strong> Lo que se ve abajo es sólo el
          CRM: no se sabe quién tiene acceso ni con qué permisos, así que la columna
          «Perfil» no dice nada todavía.
        </p>
      )}

      {hayPerfiles && (ind.sinPerfil > 0 || ind.sinUsuario > 0) && !sinDatos && (
        <p className="wt-nota">
          {ind.sinPerfil > 0 && (
            <><strong>{ind.sinPerfil} persona{ind.sinPerfil === 1 ? '' : 's'} del CRM sin
            perfil</strong>: si entran, no ven nada. </>
          )}
          {ind.sinUsuario > 0 && (
            <><strong>{ind.sinUsuario} con perfil pero fuera del CRM</strong>: ven la
            aplicación, pero no aparecen para asignarles un caso.</>
          )}
        </p>
      )}

      {!admin && (
        <p className="wt-nota">
          Tu perfil no es de administrador: podés ver quién tiene qué, pero no cambiarlo.
        </p>
      )}

      {abierto && (
        <Editor fila={abierto} perfilActual={perfil} email={email} guardando={guardando}
                alGuardar={guardar} alBorrar={borrar} alCerrar={() => setAbierto(null)} />
      )}

      <Tabla
        titulo="Usuarios y permisos"
        columnas={columnas}
        filas={preparadas}
        cargando={cargando}
        error=""
        alReintentar={cargar}
        claveFila={(f) => f.correo}
        nombreExport="usuarios-watchtower"
        vacioTexto="No hay usuarios."
        herramientas={
          <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
        }
      />
    </>
  );
}
