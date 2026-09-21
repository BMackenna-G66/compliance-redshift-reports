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

import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

import './estilo/tokens.css';
import './estilo/base.css';
import './estilo/componentes.css';

import { cargarConfig } from './config.js';
import { crearApi } from './api.js';
import { PANTALLAS } from './dominio.js';
import { Sidebar } from './shell/Sidebar.jsx';
import { Topbar } from './shell/Topbar.jsx';
import { Bandeja } from './pantallas/Bandeja.jsx';
import { Caso } from './pantallas/Caso.jsx';
import { Casos } from './pantallas/Casos.jsx';
import { Flags } from './pantallas/Flags.jsx';
import { Ficha } from './pantallas/Ficha.jsx';
import { Historial } from './pantallas/Historial.jsx';
import { Individual } from './pantallas/Individual.jsx';
import { Informe } from './pantallas/Informe.jsx';
import { Institucional } from './pantallas/Institucional.jsx';
import { Kanban } from './pantallas/Kanban.jsx';
import { ListaBlanca } from './pantallas/ListaBlanca.jsx';
import { Pendiente } from './pantallas/Pendiente.jsx';
import { Reportes } from './pantallas/Reportes.jsx';
import { Triage } from './pantallas/Triage.jsx';

const PERFILES = {
  'Super admin': { rol: 'superadmin', modulos: ['all'] },
  Analista: { rol: 'analyst', modulos: ['dashboard', 'alertas'] },
  'CX (sólo lectura)': { rol: 'lectura', modulos: ['casos'] },
};

const CONSTRUIDAS = {
  dashboard: Bandeja, alert: Triage, cases: Casos, kanban: Kanban,
  caso: Caso, ficha: Ficha, reports: Reportes,
  history: Historial,
  whitelist: ListaBlanca,
  institucional: Institucional,
  individual: Individual,
  informe: Informe,
  flags: Flags,
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
            <Pantalla api={api} perfil={perfil} email="banco-de-pruebas@global66.com"
                      navegar={navegar} id={resto[0] || ''} />
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
