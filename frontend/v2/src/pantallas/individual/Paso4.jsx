/* ============================================================================
   Paso 4 · La conclusión
   ----------------------------------------------------------------------------
   Se cruzan los dos archivos que dejaron los pasos anteriores —las
   transacciones del paso 2 y el análisis del motor del paso 3— y sale la
   planilla final, con el N° de caso del paso 1 pegado por número de remesa.

   TODO PASA EN EL NAVEGADOR. Los dos archivos no se suben a ningún lado: se
   leen acá y el Excel se arma acá. Son datos de clientes y no hay motivo para
   que salgan de la máquina de quien analiza.

   SheetJS se carga a demanda: son 400 kB que sólo hacen falta en esta
   pantalla, y cargarlos siempre haría más lento entrar a cualquier otra.
   ========================================================================= */

import { useRef, useState } from 'react';

import { cruzar, resumenDelCruce } from '../../comun/individual.js';

function Soltar({ titulo, ayuda, archivo, filas, alLeer, alQuitar }) {
  const [arrastrando, setArrastrando] = useState(false);
  const entrada = useRef(null);
  return (
    <div>
      <h3 className="wt-subtitulo">{titulo}</h3>
      {archivo ? (
        <div className="wt-adjunto">
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
                         whiteSpace: 'nowrap' }} title={archivo}>
            {archivo}
          </span>
          <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            {filas.length.toLocaleString('es-CL')} filas
          </span>
          <button className="wt-btn" style={{ padding: '2px 8px' }} onClick={alQuitar}>
            Quitar
          </button>
        </div>
      ) : (
        <div
          className={`wt-soltar${arrastrando ? ' wt-soltar-activo' : ''}`}
          style={{ marginTop: 0 }}
          onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
          onDragLeave={(e) => { e.preventDefault(); setArrastrando(false); }}
          onDrop={(e) => {
            e.preventDefault(); setArrastrando(false); alLeer(e.dataTransfer?.files?.[0]);
          }}
          onClick={() => entrada.current?.click()}
        >
          <p style={{ margin: 0 }}>Arrastrá el archivo acá</p>
          <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            {ayuda}
          </p>
          <input ref={entrada} type="file" hidden accept=".xlsx,.xls,.csv"
                 onChange={(e) => { alLeer(e.target.files?.[0]); e.target.value = ''; }} />
        </div>
      )}
    </div>
  );
}

export function Paso4({ casos }) {
  const [tx, setTx] = useState({ nombre: '', filas: [] });
  const [analisis, setAnalisis] = useState({ nombre: '', filas: [] });
  const [error, setError] = useState('');
  const [armando, setArmando] = useState(false);
  const [resultado, setResultado] = useState(null);

  async function leer(file, poner) {
    if (!file) return;
    setError(''); setResultado(null);
    try {
      const XLSX = await import('xlsx');
      const buffer = await file.arrayBuffer();
      const libro = XLSX.read(buffer, { type: 'array' });
      const hoja = libro.Sheets[libro.SheetNames[0]];
      // `defval: ''` y no `undefined`: una celda vacía tiene que llegar como
      // texto vacío, o el cruce la compara contra `undefined` y no matchea.
      poner({ nombre: file.name, filas: XLSX.utils.sheet_to_json(hoja, { defval: '' }) });
    } catch (e) {
      setError(`No se pudo leer ${file.name}: ${e?.message || 'error'}`);
    }
  }

  function armar() {
    setArmando(true); setError('');
    try {
      const r = cruzar({ transacciones: tx.filas, analisis: analisis.filas, casos });
      setResultado({ ...r, resumen: resumenDelCruce(r) });
    } catch (e) {
      setError(e?.message || 'No se pudo armar la conclusión.');
    } finally {
      setArmando(false);
    }
  }

  async function descargar() {
    setError('');
    try {
      const XLSX = await import('xlsx');
      const libro = XLSX.utils.book_new();
      // Una hoja vacía sin explicación se lee como un error del programa. Se
      // deja dicho por qué no hay nada.
      const nac = resultado.nacionales.length ? resultado.nacionales
        : [{ 'Sin datos': 'No hay transacciones nacionales en el archivo del paso 2' }];
      const inter = resultado.internacionales.length ? resultado.internacionales
        : [{ 'Sin datos': 'No hay transacciones internacionales en el archivo del paso 2' }];
      XLSX.utils.book_append_sheet(libro, XLSX.utils.json_to_sheet(nac), 'Nacionales');
      XLSX.utils.book_append_sheet(libro, XLSX.utils.json_to_sheet(inter), 'Internacionales');
      const hoy = new Date().toISOString().slice(0, 10);
      XLSX.writeFile(libro, `conclusion-analisis-individual-${hoy}.xlsx`);
    } catch (e) {
      setError(`No se pudo generar el Excel: ${e?.message || 'error'}`);
    }
  }

  const listo = tx.filas.length > 0 && analisis.filas.length > 0;
  const r = resultado?.resumen;

  return (
    <>
      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">Los dos archivos a cruzar</h2>
        </header>
        <div className="wt-cuerpo-carta wt-dos-columnas">
          <Soltar
            titulo="Transacciones (paso 2)"
            ayuda="el Excel que dejó la búsqueda de remesas"
            archivo={tx.nombre} filas={tx.filas}
            alLeer={(f) => leer(f, setTx)}
            alQuitar={() => { setTx({ nombre: '', filas: [] }); setResultado(null); }}
          />
          <Soltar
            titulo="Análisis del motor (paso 3)"
            ayuda="el Excel con la columna IDENTIDAD (DNI/RUT)"
            archivo={analisis.nombre} filas={analisis.filas}
            alLeer={(f) => leer(f, setAnalisis)}
            alQuitar={() => { setAnalisis({ nombre: '', filas: [] }); setResultado(null); }}
          />
        </div>
        <div className="wt-cuerpo-carta" style={{ paddingTop: 0 }}>
          {casos.length === 0 && (
            <p className="wt-nota">
              No hay casos del paso 1, así que la columna «N° Caso» va a salir vacía.
              Podés importar el reporte de Salesforce y volver acá.
            </p>
          )}
          <button className="wt-btn wt-btn-primario" disabled={!listo || armando} onClick={armar}>
            {armando ? 'Cruzando…' : 'Cruzar los archivos'}
          </button>
        </div>
      </section>

      {resultado && (
        <>
          <div className="wt-kpis">
            <div className="wt-kpi wt-kpi-principal">
              <span className="wt-kpi-etiqueta">Nacionales</span>
              <span className="wt-kpi-valor">{r.nacionales.toLocaleString('es-CL')}</span>
              <span className="wt-kpi-pie">las únicas que cruzan contra el motor</span>
            </div>
            <div className="wt-kpi">
              <span className="wt-kpi-etiqueta">Internacionales</span>
              <span className="wt-kpi-valor">{r.internacionales.toLocaleString('es-CL')}</span>
              <span className="wt-kpi-pie">van en su propia hoja</span>
            </div>
            <div className="wt-kpi">
              <span className="wt-kpi-etiqueta">Cruzaron</span>
              <span className="wt-kpi-valor">{r.cruzadas.toLocaleString('es-CL')}</span>
              <span className="wt-kpi-pie">{r.tasa}% de las nacionales</span>
            </div>
            <div className="wt-kpi">
              <span className="wt-kpi-etiqueta">Sin cruzar</span>
              <span className="wt-kpi-valor">{r.sinCruzar.toLocaleString('es-CL')}</span>
              <span className="wt-kpi-pie">el DNI no está en el motor</span>
            </div>
          </div>

          {/* Una tasa baja casi siempre son dos tandas distintas. Decirlo acá
              ahorra revisar la planilla fila por fila para descubrirlo. */}
          {r.sospechoso && (
            <p className="wt-nota"
               style={{ borderColor: 'var(--nivel-alto-texto)',
                        background: 'var(--nivel-alto-tenue)', color: 'var(--nivel-alto-texto)' }}>
              Sólo cruzó el {r.tasa}% de las nacionales. Suele pasar cuando los dos archivos
              son de tandas distintas: fijate que el análisis del motor corresponda a estas
              mismas transacciones antes de usar la planilla.
            </p>
          )}

          <section className="wt-carta">
            <header className="wt-carta-cabecera">
              <h2 className="wt-carta-titulo">La planilla</h2>
              <div className="wt-carta-herramientas">
                <button className="wt-btn wt-btn-primario" onClick={descargar}>
                  Descargar el Excel
                </button>
              </div>
            </header>
            <div className="wt-cuerpo-carta">
              <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
                Dos hojas: «Nacionales», con las columnas del motor pegadas por DNI, e
                «Internacionales», que no tienen DNI contra el cual cruzar. El archivo se
                arma en tu navegador: los datos no salen de acá.
              </p>
            </div>
          </section>
        </>
      )}
    </>
  );
}
