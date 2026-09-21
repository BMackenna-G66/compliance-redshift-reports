/* ============================================================================
   Banco de pruebas
   ----------------------------------------------------------------------------
   El shell y los componentes con datos inventados y sin autenticación.

   PARA QUÉ. Entrar a la app de verdad necesita Google, y eso deja el shell sin
   forma de mirarse: ni en una revisión de PR, ni en una captura, ni de manera
   automática. Acá se ve entero en dos segundos, y se puede cambiar de perfil
   con un botón para comprobar de un vistazo qué ve cada rol — que es lo que
   antes había que verificar interceptando `fetch` en producción.

   NO SE PUBLICA: el workflow lo borra del sitio antes de subirlo. Los datos
   son fabricados y alguien que cayera acá podría creer que son reales.
   ========================================================================= */

import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';

import './estilo/tokens.css';
import './estilo/base.css';
import './estilo/componentes.css';

import { PANTALLAS } from './dominio.js';
import { Sidebar } from './shell/Sidebar.jsx';
import { Topbar } from './shell/Topbar.jsx';
import { Tabla } from './comun/Tabla.jsx';

const PERFILES = {
  'Super admin': { rol: 'superadmin', modulos: ['all'] },
  Analista: { rol: 'analyst', modulos: ['dashboard', 'alertas'] },
  'CX (sólo lectura)': { rol: 'lectura', modulos: ['casos'] },
};

/* Datos inventados, a propósito reconocibles como tales. Incluyen los casos
   raros que importan: un score ausente (que NO es cero), un monto con puntos
   de miles, un estado que el front no conoce. */
const FILAS = [
  { id: 'DEMO-1', cliente: 'Ejemplo Uno SpA', score: 12, monto: '1.234.567', estado: 'Abierto' },
  { id: 'DEMO-2', cliente: 'Ejemplo Dos Ltda', score: null, monto: '89.000', estado: 'Cerrado' },
  { id: 'DEMO-3', cliente: 'Ñandú Ejemplo', score: 0, monto: '4.500.000', estado: 'En investigación' },
  { id: 'DEMO-4', cliente: 'Ejemplo Cuatro', score: 7, monto: '250', estado: 'estado_raro' },
  { id: 'DEMO-5', cliente: 'Ejemplo Cinco', score: 9, monto: '1.000.000', estado: 'Abierto' },
];

const COLUMNAS = [
  { clave: 'id', titulo: 'Caso', tipo: 'mono', ancho: '12%' },
  { clave: 'cliente', titulo: 'Cliente', ancho: '30%' },
  { clave: 'score', titulo: 'Score', tipo: 'numero', ancho: '10%' },
  { clave: 'monto', titulo: 'Monto', tipo: 'numero', ancho: '18%' },
  { clave: 'estado', titulo: 'Estado' },
];

function Banco() {
  const [nombre, setNombre] = useState('Super admin');
  const [tema, setTema] = useState('claro');
  const [ruta, setRuta] = useState('cases');
  const perfil = PERFILES[nombre];

  document.documentElement.setAttribute('data-tema', tema);

  const pantalla = PANTALLAS.find((p) => p.id === ruta);

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
        <Sidebar perfil={perfil} actual={ruta} alNavegar={setRuta} />
        <main className="wt-contenido">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
            <strong style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              BANCO DE PRUEBAS · datos inventados
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

          <Tabla
            titulo={pantalla ? pantalla.titulo : ruta}
            columnas={COLUMNAS}
            filas={FILAS}
            nombreExport="banco"
            porPagina={3}
          />
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById('raiz')).render(
  <StrictMode><Banco /></StrictMode>,
);
