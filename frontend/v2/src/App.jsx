/* ============================================================================
   El armazón
   ----------------------------------------------------------------------------
   Login, tema, ruteo y el control de acceso por pantalla. Nada de negocio.
   ========================================================================= */

import { Suspense, lazy, useEffect, useMemo, useState } from 'react';

import { cargarConfig } from './config.js';
import { crearApi } from './api.js';
import { PANTALLAS } from './dominio.js';
import { soloLectura, verModulo } from './permisos.js';
import { entrar, salir, useSesion } from './sesion.js';
import { useRuta } from './ruta.js';

import { Sidebar } from './shell/Sidebar.jsx';
import { Topbar } from './shell/Topbar.jsx';
import { Pendiente } from './pantallas/Pendiente.jsx';

/* Ya no queda ninguna pantalla sin construir. `Pendiente` sigue en el código
   para la que venga: una ruta que existe en `PANTALLAS` pero todavía no
   tiene componente cae ahí en vez de en un error. */
const FASE = {};

/* Las pantallas se cargan a demanda.
 *
 * Son veinte y cada persona usa tres o cuatro. Importándolas todas por
 * adelantado, entrar a ver una alerta descargaba también el tablero de
 * embargos, la ficha del cliente y la auditoría: 907 kB en un solo trozo.
 * Con `lazy`, cada una viaja cuando se abre y queda en caché.
 *
 * La lista sigue siendo el inventario de lo construido — lo que no está acá
 * cae en `Pendiente`. */
const CONSTRUIDAS = {
  dashboard: lazy(() => import('./pantallas/Bandeja.jsx').then((m) => ({ default: m.Bandeja }))),
  alert: lazy(() => import('./pantallas/Triage.jsx').then((m) => ({ default: m.Triage }))),
  cases: lazy(() => import('./pantallas/Casos.jsx').then((m) => ({ default: m.Casos }))),
  kanban: lazy(() => import('./pantallas/Kanban.jsx').then((m) => ({ default: m.Kanban }))),
  caso: lazy(() => import('./pantallas/Caso.jsx').then((m) => ({ default: m.Caso }))),
  ficha: lazy(() => import('./pantallas/Ficha.jsx').then((m) => ({ default: m.Ficha }))),
  reports: lazy(() => import('./pantallas/Reportes.jsx').then((m) => ({ default: m.Reportes }))),
  history: lazy(() => import('./pantallas/Historial.jsx').then((m) => ({ default: m.Historial }))),
  whitelist: lazy(() => import('./pantallas/ListaBlanca.jsx').then((m) => ({ default: m.ListaBlanca }))),
  institucional: lazy(() => import('./pantallas/Institucional.jsx').then((m) => ({ default: m.Institucional }))),
  individual: lazy(() => import('./pantallas/Individual.jsx').then((m) => ({ default: m.Individual }))),
  informe: lazy(() => import('./pantallas/Informe.jsx').then((m) => ({ default: m.Informe }))),
  flags: lazy(() => import('./pantallas/Flags.jsx').then((m) => ({ default: m.Flags }))),
  relevo: lazy(() => import('./pantallas/Relevo.jsx').then((m) => ({ default: m.Relevo }))),
  embargos: lazy(() => import('./pantallas/Embargos.jsx').then((m) => ({ default: m.Embargos }))),
  admin_users: lazy(() => import('./pantallas/Usuarios.jsx').then((m) => ({ default: m.Usuarios }))),
  admin_auto: lazy(() => import('./pantallas/Automatizacion.jsx').then((m) => ({ default: m.Automatizacion }))),
  cx: lazy(() => import('./pantallas/Cx.jsx').then((m) => ({ default: m.Cx }))),
  analitica: lazy(() =>
    import('./pantallas/Analitica.jsx').then((m) => ({ default: m.Analitica }))),
  admin_config: lazy(() =>
    import('./pantallas/Administracion.jsx').then((m) => ({ default: m.Administracion }))),
  admin_cluster: lazy(() => import('./pantallas/Cluster.jsx').then((m) => ({ default: m.Cluster }))),
  audit: lazy(() => import('./pantallas/Auditoria.jsx').then((m) => ({ default: m.Auditoria }))),
  salud: lazy(() => import('./pantallas/Salud.jsx').then((m) => ({ default: m.Salud }))),
  ros: lazy(() => import('./pantallas/Ros.jsx').then((m) => ({ default: m.Ros }))),
  inicio: lazy(() => import('./pantallas/Inicio.jsx').then((m) => ({ default: m.Inicio }))),
  pendientes: lazy(() => import('./pantallas/Pendientes.jsx').then((m) => ({ default: m.Pendientes }))),
  busqueda: lazy(() => import('./pantallas/Busqueda.jsx').then((m) => ({ default: m.Busqueda }))),
  queries: lazy(() => import('./pantallas/Queries.jsx').then((m) => ({ default: m.Queries }))),
};

/* ── Tema ───────────────────────────────────────────────────────────────── */

function useTema() {
  const [tema, setTema] = useState(() => {
    try {
      const guardado = localStorage.getItem('wt_tema_v2');
      if (guardado === 'claro' || guardado === 'oscuro') return guardado;
    } catch { /* almacenamiento bloqueado */ }
    return 'claro';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-tema', tema);
    try { localStorage.setItem('wt_tema_v2', tema); } catch { /* idem */ }
  }, [tema]);

  return [tema, () => setTema((t) => (t === 'oscuro' ? 'claro' : 'oscuro'))];
}

/* ── Pantallas ──────────────────────────────────────────────────────────── */

function Contenido({ ruta, resto, perfil, api, email, navegar }) {
  const pantalla = PANTALLAS.find((p) => p.id === ruta);

  if (!pantalla) {
    return (
      <div className="wt-pendiente">
        <h2>No existe esa pantalla</h2>
        <p>La dirección <code>#/{ruta}</code> no corresponde a ninguna sección.</p>
      </div>
    );
  }

  // El menú ya esconde lo que este perfil no ve, pero alguien puede escribir
  // la dirección a mano o tener un marcador viejo. Esconder no es controlar.
  if (!verModulo(perfil, pantalla.modulo)) {
    return (
      <div className="wt-pendiente">
        <h2>Sin acceso</h2>
        <p>
          Tu perfil no tiene habilitada la sección «{pantalla.titulo}».
          Si la necesitás, pedila al equipo de Compliance.
        </p>
      </div>
    );
  }

  const Construida = CONSTRUIDAS[ruta];
  if (Construida) {
    // El `Suspense` es por la carga a demanda. El texto es el mismo que usan
    // las pantallas mientras piden datos, así que el salto entre "bajando la
    // pantalla" y "pidiendo los datos" no se nota como dos esperas.
    // `id` es el segmento que sigue a la pantalla en la dirección: en
    // `#/caso/abc` es el caso, en `#/ficha/123` el cliente. Cada pantalla le
    // pone su nombre; acá no se sabe ni hace falta saber de qué es.
    return (
      <Suspense fallback={<p className="wt-estado">Cargando…</p>}>
        <Construida api={api} perfil={perfil} email={email} navegar={navegar}
                    id={resto?.[0] || ''} />
      </Suspense>
    );
  }
  return <Pendiente id={ruta} fase={FASE[ruta]} />;
}

/* ── La aplicación ──────────────────────────────────────────────────────── */

export default function App() {
  const sesion = useSesion();
  const [tema, alternarTema] = useTema();
  const { ruta, resto, navegar } = useRuta('inicio');

  const [config, setConfig] = useState(null);
  const [errorConfig, setErrorConfig] = useState('');
  const [errorLogin, setErrorLogin] = useState('');

  useEffect(() => {
    cargarConfig().then(setConfig).catch((e) =>
      setErrorConfig(e?.message || 'No se pudo leer config.json'));
  }, []);

  // El cliente se arma UNA vez y recibe el perfil como función, no como
  // valor: el perfil llega después (Firestore tarda) y si quedara congelado
  // el que había al montar —el mínimo— bloquearía como sólo-lectura todo lo
  // que el usuario escriba después. Ver api.js.
  const api = useMemo(() => {
    if (!config) return null;
    return crearApi({
      base: config.apiUrl,
      perfil: sesion.leerPerfilActual,
      email: sesion.leerEmailActual,
    });
  }, [config, sesion.leerPerfilActual, sesion.leerEmailActual]);

  if (sesion.cargando) {
    return <div className="wt-login"><p className="wt-estado">Cargando…</p></div>;
  }

  if (!sesion.autenticado) {
    return (
      <div className="wt-login">
        <div className="wt-login-caja">
          <h1 className="wt-marca" style={{ display: 'block', marginBottom: 8 }}>
            WatchTower
          </h1>
          <p style={{ color: 'var(--texto-mute)', fontSize: 'var(--texto-sm)', marginTop: 0 }}>
            Compliance · Global66
          </p>
          <button
            className="wt-btn wt-btn-primario"
            style={{ width: '100%', marginTop: 16 }}
            onClick={() => entrar().catch((e) => setErrorLogin(e?.message || 'No se pudo entrar.'))}
          >
            Entrar con Google
          </button>
          {errorLogin && (
            <p className="wt-estado-error" style={{ marginTop: 16 }}>{errorLogin}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="wt-app">
      <Topbar
        email={sesion.email}
        perfil={sesion.perfil}
        tema={tema}
        alCambiarTema={alternarTema}
        alSalir={() => salir()}
      />
      <div className="wt-cuerpo">
        <Sidebar perfil={sesion.perfil} actual={ruta} alNavegar={navegar} />
        <main className="wt-contenido">
          {soloLectura(sesion.perfil) && (
            <p className="wt-aviso-lectura">
              Tu perfil es de consulta: podés ver todo lo habilitado, pero no modificarlo.
            </p>
          )}
          {errorConfig ? (
            <div className="wt-estado-error">
              No se pudo cargar la configuración ({errorConfig}). Recargá la página.
            </div>
          ) : !api ? (
            <p className="wt-estado">Conectando…</p>
          ) : (
            <Contenido ruta={ruta} resto={resto} perfil={sesion.perfil} api={api}
                       email={sesion.email} navegar={navegar} />
          )}
        </main>
      </div>
    </div>
  );
}
