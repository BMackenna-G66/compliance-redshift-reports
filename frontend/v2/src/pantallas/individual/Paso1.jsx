/* ============================================================================
   Paso 1 · Extracción de casos
   ----------------------------------------------------------------------------
   Se importa el reporte que Salesforce exporta como .xls —que en realidad es
   HTML— y se sacan los IDs de cliente y los números de remesa. De ahí salen
   las entradas de los pasos 2 y 3, que es el punto de todo: sin esto hay que
   copiar cientos de identificadores a mano de una planilla a otra.

   SE LEE EN ISO-8859-1. Salesforce exporta así; leerlo como UTF-8 convierte
   cada acento en un rombo y esos nombres terminan en la planilla final.
   ========================================================================= */

import { useRef, useState } from 'react';

import { Tabla } from '../../comun/Tabla.jsx';
import {
  CODIFICACION_SALESFORCE, filasDeSalesforce, idsDeCasos, remesasDeCasos,
} from '../../comun/individual.js';

const COLUMNAS = [
  { clave: 'numero_caso', titulo: 'N° de caso', tipo: 'mono', ancho: '13%' },
  { clave: 'id_interno', titulo: 'Id de cliente', tipo: 'mono', ancho: '12%' },
  { clave: 'remesa', titulo: 'Remesa', tipo: 'mono', ancho: '12%' },
  { clave: 'nombre_cuenta', titulo: 'Cuenta', ancho: '22%' },
  {
    clave: 'asunto',
    titulo: 'Asunto',
    render: (r) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 420 }}>{r.asunto}</span>
    ),
  },
  { clave: 'fecha_hora', titulo: 'Fecha', ancho: '14%' },
];

export function Paso1({ casos, alCambiar, alMandarIds, alMandarRemesas }) {
  const [error, setError] = useState('');
  const [procesando, setProcesando] = useState(false);
  const [archivo, setArchivo] = useState('');
  const [arrastrando, setArrastrando] = useState(false);
  const entrada = useRef(null);

  function leer(file) {
    if (!file) return;
    setError(''); setProcesando(true); setArchivo(file.name); alCambiar([]);
    const lector = new FileReader();
    lector.onload = (ev) => {
      try {
        const doc = new DOMParser().parseFromString(String(ev.target.result), 'text/html');
        const filas = filasDeSalesforce(doc);
        alCambiar(filas);
        if (filas.length === 0) {
          setError('No se encontraron filas válidas. Fijate que sea el reporte de casos '
                 + 'exportado de Salesforce y no otro archivo.');
        }
      } catch (e) {
        setError(`No se pudo procesar el archivo: ${e?.message || 'error'}`);
      } finally {
        setProcesando(false);
      }
    };
    lector.onerror = () => { setError('No se pudo leer el archivo.'); setProcesando(false); };
    lector.readAsText(file, CODIFICACION_SALESFORCE);
  }

  const ids = idsDeCasos(casos);
  const remesas = remesasDeCasos(casos);

  return (
    <>
      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {casos.length === 0 ? (
        <section className="wt-carta">
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Importar el reporte de Salesforce</h2>
          </header>
          <div className="wt-cuerpo-carta">
            <div
              className={`wt-soltar${arrastrando ? ' wt-soltar-activo' : ''}`}
              style={{ marginTop: 0 }}
              onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
              onDragLeave={(e) => { e.preventDefault(); setArrastrando(false); }}
              onDrop={(e) => {
                e.preventDefault(); setArrastrando(false);
                leer(e.dataTransfer?.files?.[0]);
              }}
              onClick={() => !procesando && entrada.current?.click()}
            >
              {procesando ? (
                <p style={{ margin: 0 }}>Procesando {archivo}…</p>
              ) : (
                <>
                  <p style={{ margin: 0 }}>Arrastrá acá el .xls de Salesforce</p>
                  <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                    o hacé clic para elegirlo — es el reporte de casos, tal como lo exporta
                  </p>
                </>
              )}
              <input ref={entrada} type="file" hidden accept=".xls,.html,.htm"
                     onChange={(e) => { leer(e.target.files?.[0]); e.target.value = ''; }} />
            </div>
            <p style={{ marginTop: 'var(--e-3)', marginBottom: 0,
                        fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              El archivo no sale de tu navegador: se lee acá mismo. De él salen los ids de
              cliente para el paso 3 y los números de remesa para el paso 2.
            </p>
          </div>
        </section>
      ) : (
        <>
          <div className="wt-kpis">
            <div className="wt-kpi wt-kpi-principal">
              <span className="wt-kpi-etiqueta">Casos leídos</span>
              <span className="wt-kpi-valor">{casos.length}</span>
              <span className="wt-kpi-pie">de {archivo}</span>
            </div>
            <div className="wt-kpi">
              <span className="wt-kpi-etiqueta">Ids de cliente</span>
              <span className="wt-kpi-valor">{ids.length}</span>
              <span className="wt-kpi-pie">únicos, para el paso 3</span>
            </div>
            <div className="wt-kpi">
              <span className="wt-kpi-etiqueta">Remesas</span>
              <span className="wt-kpi-valor">{remesas.length}</span>
              <span className="wt-kpi-pie">únicas, para el paso 2</span>
            </div>
          </div>

          <Tabla
            titulo="Casos del reporte"
            columnas={COLUMNAS}
            filas={casos}
            claveFila={(_, i) => i}
            porPagina={25}
            nombreExport="casos-salesforce"
            herramientas={
              <>
                <button className="wt-btn wt-btn-primario" disabled={ids.length === 0}
                        onClick={() => alMandarIds(ids)}>
                  Mandar {ids.length} ids al paso 3
                </button>
                <button className="wt-btn" disabled={remesas.length === 0}
                        onClick={() => alMandarRemesas(remesas)}>
                  Mandar {remesas.length} remesas al paso 2
                </button>
                <button className="wt-btn" onClick={() => { alCambiar([]); setArchivo(''); }}>
                  Quitar el archivo
                </button>
              </>
            }
          />
        </>
      )}
    </>
  );
}
