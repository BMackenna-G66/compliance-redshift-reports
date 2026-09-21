/* ============================================================================
   El armazón
   ----------------------------------------------------------------------------
   Login, tema, ruteo y el control de acceso por pantalla. Nada de negocio.
   ========================================================================= */

import { useEffect, useMemo, useState } from 'react';

import { cargarConfig } from './config.js';
import { crearApi } from './api.js';
import { PANTALLAS } from './dominio.js';
import { soloLectura, verModulo } from './permisos.js';
import { entrar, salir, useSesion } from './sesion.js';
import { useRuta } from './ruta.js';

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
import { Embargos } from './pantallas/Embargos.jsx';
import { Institucional } from './pantallas/Institucional.jsx';
import { Relevo } from './pantallas/Relevo.jsx';
import { Kanban } from './pantallas/Kanban.jsx';
import { ListaBlanca } from './pantallas/ListaBlanca.jsx';
import { Pendiente } from './pantallas/Pendiente.jsx';
import { Reportes } from './pantallas/Reportes.jsx';
import { Triage } from './pantallas/Triage.jsx';

/* Qué pantalla construye qué fase. Sirve para que el relleno diga algo útil
   y para que esta lista sea el inventario de lo que falta. */
const FASE = {
  admin_users: 'Fase 6', admin_auto: 'Fase 6', admin_cluster: 'Fase 6',
  audit: 'Fase 6', salud: 'Fase 6',
  ros: 'Fase 7',
};

/* Las pantallas ya construidas. Todo lo demás cae en Pendiente. */
const CONSTRUIDAS = {
  dashboard: Bandeja,
  alert: Triage,
  cases: Casos,
  kanban: Kanban,
  caso: Caso,
  ficha: Ficha,
  reports: Reportes,
  history: Historial,
  whitelist: ListaBlanca,
  institucional: Institucional,
  individual: Individual,
  informe: Informe,
  flags: Flags,
  relevo: Relevo,
  embargos: Embargos,
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
    // `id` es el segmento que sigue a la pantalla en la dirección: en
    // `#/caso/abc` es el caso, en `#/ficha/123` el cliente. Cada pantalla le
    // pone su nombre; acá no se sabe ni hace falta saber de qué es.
    return (
      <Construida api={api} perfil={perfil} email={email} navegar={navegar}
                  id={resto?.[0] || ''} />
    );
  }
  return <Pendiente id={ruta} fase={FASE[ruta]} />;
}

/* ── La aplicación ──────────────────────────────────────────────────────── */

export default function App() {
  const sesion = useSesion();
  const [tema, alternarTema] = useTema();
  const { ruta, resto, navegar } = useRuta('dashboard');

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
