/* ============================================================================
   Banco de pruebas
   ----------------------------------------------------------------------------
   El shell y las pantallas reales, sin pasar por el login de Google.

   PARA QUÉ. Entrar a la app necesita Google, y eso deja las pantallas sin
   forma de mirarse: ni en una revisión, ni en una captura, ni de manera
   automática. Acá se ven en dos segundos, y el selector de perfil muestra de
   un vistazo qué ve cada rol — lo que antes había que comprobar
   interceptando `fetch` en producción.

   DE DÓNDE SALEN LOS DATOS. De la API de verdad, leyendo `./config.json`
   igual que la app. No hay ningún archivo de datos guardado en el repo, y no
   puede haberlo: el repo es público y las alertas traen correos e
   identificadores de clientes.

   EL PERFIL ES SIEMPRE DE SÓLO LECTURA, incluso cuando el selector dice otra
   cosa. El selector cambia lo que se VE —que es lo que se quiere revisar—
   pero el cliente de API se arma con perfil de consulta, así que ninguna
   escritura puede salir de acá hacia producción por un clic distraído.

   NO SE PUBLICA: el workflow lo borra del sitio antes de subirlo.
   ========================================================================= */

import { StrictMode, Suspense, lazy, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

import './estilo/tokens.css';
import './estilo/base.css';
import './estilo/componentes.css';

import { cargarConfig } from './config.js';
import { crearApi } from './api.js';
import { PANTALLAS } from './dominio.js';
import { Sidebar } from './shell/Sidebar.jsx';
import { Topbar } from './shell/Topbar.jsx';
import { Pendiente } from './pantallas/Pendiente.jsx';

const PERFILES = {
  'Super admin': { rol: 'superadmin', modulos: ['all'] },
  Analista: { rol: 'analyst', modulos: ['dashboard', 'alertas'] },
  'CX (sólo lectura)': { rol: 'lectura', modulos: ['casos'] },
};

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
  admin_cluster: lazy(() => import('./pantallas/Cluster.jsx').then((m) => ({ default: m.Cluster }))),
  audit: lazy(() => import('./pantallas/Auditoria.jsx').then((m) => ({ default: m.Auditoria }))),
  salud: lazy(() => import('./pantallas/Salud.jsx').then((m) => ({ default: m.Salud }))),
  ros: lazy(() => import('./pantallas/Ros.jsx').then((m) => ({ default: m.Ros }))),
  inicio: lazy(() => import('./pantallas/Inicio.jsx').then((m) => ({ default: m.Inicio }))),
  pendientes: lazy(() => import('./pantallas/Pendientes.jsx').then((m) => ({ default: m.Pendientes }))),
  busqueda: lazy(() => import('./pantallas/Busqueda.jsx').then((m) => ({ default: m.Busqueda }))),
  queries: lazy(() => import('./pantallas/Queries.jsx').then((m) => ({ default: m.Queries }))),
};

function Banco() {
  const [nombre, setNombre] = useState('Super admin');
  const [tema, setTema] = useState('claro');
  const [ruta, setRuta] = useState('dashboard');
  const [resto, setResto] = useState([]);
  const [api, setApi] = useState(null);
  const [error, setError] = useState('');

  const perfil = PERFILES[nombre];
  document.documentElement.setAttribute('data-tema', tema);

  useEffect(() => {
    cargarConfig()
      .then((cfg) => setApi(crearApi({
        base: cfg.apiUrl,
        // A propósito, y pase lo que pase con el selector de arriba.
        perfil: () => ({ rol: 'lectura', modulos: ['all'] }),
        email: () => 'banco-de-pruebas@global66.com',
      })))
      .catch((e) => setError(
        `Sin config.json no hay datos. Poné uno con {"apiUrl": "..."} junto al index. (${e.message})`,
      ));
  }, []);

  function navegar(id, siguiente = []) {
    setRuta(id);
    setResto(siguiente);
  }

  const Pantalla = CONSTRUIDAS[ruta];
  const def = PANTALLAS.find((p) => p.id === ruta);

  return (
    <div className="wt-app">
      <Topbar
        email="banco-de-pruebas@global66.com"
        perfil={perfil}
        tema={tema}
        alCambiarTema={() => setTema((t) => (t === 'oscuro' ? 'claro' : 'oscuro'))}
        alSalir={() => {}}
      />
      <div className="wt-cuerpo">
        <Sidebar perfil={perfil} actual={ruta} alNavegar={navegar} />
        <main className="wt-contenido">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
            <strong style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              BANCO · datos reales, escritura bloqueada
            </strong>
            {Object.keys(PERFILES).map((n) => (
              <button
                key={n}
                className={'wt-btn' + (n === nombre ? ' wt-btn-primario' : '')}
                onClick={() => setNombre(n)}
              >
                {n}
              </button>
            ))}
          </div>

          {error ? (
            <div className="wt-estado-error">{error}</div>
          ) : !api ? (
            <p className="wt-estado">Conectando…</p>
          ) : Pantalla ? (
            <Suspense fallback={<p className="wt-estado">Cargando…</p>}>
              <Pantalla api={api} perfil={perfil} email="banco-de-pruebas@global66.com"
                        navegar={navegar} id={resto[0] || ''} />
            </Suspense>
          ) : (
            <Pendiente id={ruta} fase={def ? 'una fase posterior' : ''} />
          )}
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById('raiz')).render(
  <StrictMode><Banco /></StrictMode>,
);
