/* ============================================================================
   Análisis individual
   ----------------------------------------------------------------------------
   Cuatro pasos encadenados, más la consulta directa de un cliente.

     1. Extracción de casos — el reporte de Salesforce, del que salen los ids
        de cliente y los números de remesa.
     2. Búsqueda de remesas — esos números contra Redshift. También el wallet.
     3. Motor AML — esos ids por las diez banderas.
     4. Conclusión — se cruzan los resultados de 2 y 3 y sale la planilla.

   EL ENCADENADO ES EL PUNTO. Lo que el paso 1 encuentra se le pasa al 2 y al
   3 con un botón; el estado vive acá, en el contenedor, justamente para que
   no haya que copiar cientos de identificadores de una planilla a otra. Cada
   paso se puede usar suelto igual: nadie está obligado a empezar por el 1.

   Los pasos se cargan a demanda. El 4 arrastra SheetJS —400 kB— y no tiene
   sentido pagarlos al entrar a la pantalla si lo que se venía a hacer era
   correr el motor.
   ========================================================================= */

import { Suspense, lazy, useState } from 'react';

import { soloLectura } from '../permisos.js';

const Paso1 = lazy(() => import('./individual/Paso1.jsx').then((m) => ({ default: m.Paso1 })));
const Paso2 = lazy(() => import('./individual/Paso2.jsx').then((m) => ({ default: m.Paso2 })));
const Paso3 = lazy(() => import('./individual/Paso3.jsx').then((m) => ({ default: m.Paso3 })));
const Paso4 = lazy(() => import('./individual/Paso4.jsx').then((m) => ({ default: m.Paso4 })));
const Cliente = lazy(() => import('./individual/Cliente.jsx').then((m) => ({ default: m.Cliente })));

const PASOS = [
  { clave: '1', titulo: 'Extracción de casos', pie: 'el reporte de Salesforce' },
  { clave: '2', titulo: 'Búsqueda de remesas', pie: 'y de wallets' },
  { clave: '3', titulo: 'Motor AML', pie: 'las diez banderas' },
  { clave: '4', titulo: 'Conclusión', pie: 'la planilla final' },
  { clave: 'cliente', titulo: 'Análisis de cliente', pie: 'la consulta directa' },
];

export function Individual({ api, perfil, email }) {
  const [paso, setPaso] = useState('3');

  /* Lo que un paso le pasa al siguiente. Vive acá para que sobreviva al
     cambio de pestaña: perderlo obligaría a volver a importar el archivo. */
  const [casos, setCasos] = useState([]);
  const [remesas, setRemesas] = useState('');
  const [ids, setIds] = useState('');

  const lectura = soloLectura(perfil);

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Análisis individual
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          de la extracción de casos a la planilla final
        </span>
      </div>

      <nav className="wt-pasos" aria-label="Pasos del análisis">
        {PASOS.map((p) => (
          <button key={p.clave}
                  className={`wt-paso-boton${paso === p.clave ? ' wt-paso-activo' : ''}`}
                  aria-current={paso === p.clave ? 'step' : undefined}
                  onClick={() => setPaso(p.clave)}>
            <span className="wt-paso-n">{p.clave === 'cliente' ? '·' : p.clave}</span>
            <span>
              <span className="wt-paso-titulo">{p.titulo}</span>
              <span className="wt-paso-pie">{p.pie}</span>
            </span>
            {/* Cuánto trae cada paso, para saber de un vistazo qué ya se
                hizo sin tener que entrar a mirar. */}
            {p.clave === '1' && casos.length > 0 && (
              <span className="wt-paso-cuenta">{casos.length}</span>
            )}
          </button>
        ))}
      </nav>

      <Suspense fallback={<p className="wt-estado">Cargando el paso…</p>}>
        {paso === '1' && (
          <Paso1
            casos={casos}
            alCambiar={setCasos}
            alMandarIds={(xs) => { setIds(xs.join('\n')); setPaso('3'); }}
            alMandarRemesas={(xs) => { setRemesas(xs.join('\n')); setPaso('2'); }}
          />
        )}
        {paso === '2' && (
          lectura ? <SoloLectura /> : (
            <Paso2 api={api} email={email} remesas={remesas} alCambiarRemesas={setRemesas} />
          )
        )}
        {paso === '3' && (
          <Paso3 api={api} perfil={perfil} email={email} texto={ids} alCambiarTexto={setIds} />
        )}
        {paso === '4' && <Paso4 casos={casos} />}
        {paso === 'cliente' && (
          lectura ? <SoloLectura /> : <Cliente api={api} />
        )}
      </Suspense>
    </>
  );
}

function SoloLectura() {
  return (
    <p className="wt-nota">
      Tu perfil es de consulta: podés ver los resultados en el historial, pero no lanzar
      consultas nuevas contra Redshift.
    </p>
  );
}
