/* ============================================================================
   El ROS de GEREO, editable como formulario
   ----------------------------------------------------------------------------
   EL JSON NO SE MUESTRA COMO JSON. Un analista no tiene por qué pelear con
   llaves y comas para corregir un monto, y un documento que se edita como
   texto crudo se rompe sola: una coma de menos y el reporte deja de ser
   válido sin que nadie lo note hasta el otro lado.

   LO QUE NO SE PUEDE HACER ACÁ, y es a propósito: agregar campos, sacarlos, o
   agregar un elemento a una lista. GEREO usa el documento tal cual para
   completar el formulario del regulador. Cambiar la estructura lo rompe del
   otro lado. Si falta un reportado, se pide otra generación.

   CADA GUARDADO CREA UNA VERSIÓN NUEVA, y la anterior queda intacta: lo que
   se aprueba y se manda es una versión específica, y si una edición pisara a
   la anterior, «se aprobó esto» dejaría de poder probarse.

   Y EDITAR ANULA LA REVISIÓN. Lo revisado era el contenido de antes.
   ========================================================================= */

import { useEffect, useState } from 'react';

import {
  campos, coaccionar, cuerpoDeGuardado, escribir, esTextoLargo, leer,
} from '../../comun/formulario_ros.js';

function Campo({ campo, alCambiar }) {
  const { ruta, etiqueta: titulo, tipo, valor } = campo;

  if (tipo === 'lista_vacia') {
    return (
      <p style={{ margin: 0, fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
        {titulo}: <em>vacío</em>
      </p>
    );
  }

  if (tipo === 'bool') {
    return (
      <label className="wt-checklist-item" style={{ cursor: 'pointer' }}>
        <input type="checkbox" checked={Boolean(valor)}
               onChange={(e) => alCambiar(ruta, e.target.checked)} />
        <span style={{ fontSize: 'var(--texto-sm)' }}>{titulo}</span>
      </label>
    );
  }

  const largo = esTextoLargo(valor);
  return (
    <label style={{ display: 'block', fontSize: 'var(--texto-sm)',
                    color: 'var(--texto-mute)' }}>
      {titulo}
      {tipo === 'nulo' && (
        <span style={{ opacity: .7 }}> — GEREO lo dejó a tu criterio</span>
      )}
      {largo ? (
        <textarea className="wt-input"
                  style={{ display: 'block', width: '100%', marginTop: 4,
                           minHeight: 140, resize: 'vertical' }}
                  value={valor ?? ''}
                  onChange={(e) => alCambiar(ruta, e.target.value)} />
      ) : (
        <input className="wt-input"
               style={{ display: 'block', width: '100%', marginTop: 4 }}
               /* `text` incluso para los números: un `number` nativo rechaza
                  pegar «1.234.567» y los montos llegan así. La conversión al
                  tipo original la hace `coaccionar`. */
               type="text"
               value={valor ?? ''}
               onChange={(e) => alCambiar(ruta, e.target.value)} />
      )}
    </label>
  );
}

function Seccion({ seccion, contenido, alCambiar }) {
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-3)' }}>
      <header className="wt-carta-cabecera">
        <h3 className="wt-carta-titulo" style={{ fontSize: 'var(--texto-base)' }}>
          {seccion.titulo}
        </h3>
      </header>
      <div className="wt-cuerpo-carta"
           style={{ display: 'grid', gap: 'var(--e-3)' }}>
        {campos(contenido).map((c) => (
          <Campo key={c.ruta} campo={c}
                 alCambiar={(ruta, crudo) => alCambiar(seccion.clave, ruta, crudo)} />
        ))}
      </div>
    </section>
  );
}

export function Formulario({ api, folio, version, alGuardar, lectura }) {
  const [datos, setDatos] = useState(null);
  const [borradores, setBorradores] = useState({});
  const [estado, setEstado] = useState('cargando');
  const [error, setError] = useState('');
  const [diferencias, setDiferencias] = useState([]);

  useEffect(() => {
    let vivo = true;
    setEstado('cargando'); setError(''); setBorradores({}); setDiferencias([]);
    api.get(`/ros/${encodeURIComponent(folio)}/versiones/${version}`)
      .then((d) => { if (vivo) { setDatos(d); setEstado(''); } })
      .catch((e) => { if (vivo) { setError(e?.message || 'No pude leer la versión.'); setEstado('error'); } });
    return () => { vivo = false; };
  }, [api, folio, version]);

  function cambiar(claveSeccion, ruta, crudo) {
    setBorradores((b) => {
      const base = Object.prototype.hasOwnProperty.call(b, claveSeccion)
        ? b[claveSeccion]
        : (datos.secciones.find((s) => s.clave === claveSeccion) || {}).contenido;
      // El valor ORIGINAL manda el tipo: `coaccionar` lo usa para devolver un
      // número donde había un número. Sale del contenido base y no del
      // borrador, que ya podría estar a medio escribir.
      const original = leer(base, ruta);
      return { ...b, [claveSeccion]: escribir(base, ruta, coaccionar(original, crudo)) };
    });
  }

  async function guardar() {
    setEstado('guardando'); setError(''); setDiferencias([]);
    try {
      const d = await api.post(
        `/ros/${encodeURIComponent(folio)}/versiones`,
        cuerpoDeGuardado(datos.secciones, borradores, version));
      setBorradores({});
      setEstado('');
      alGuardar(d?.ros);
    } catch (e) {
      setEstado('error');
      setError(e?.message || 'No pude guardar.');
      // El backend dice QUÉ cambió de estructura. Mostrarlo es la diferencia
      // entre «no se pudo» y saber qué campo revisar.
      if (Array.isArray(e?.datos?.diferencias)) setDiferencias(e.datos.diferencias);
    }
  }

  if (estado === 'cargando') {
    return <p className="wt-estado">Cargando el reporte…</p>;
  }
  if (!datos) {
    return <div className="wt-estado-error">{error || 'No pude leer la versión.'}</div>;
  }

  const tocado = Object.keys(borradores).length > 0;

  return (
    <>
      <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
        Versión {datos.version} · {datos.pais}. Podés corregir los valores;
        los campos y su orden los fija el formulario del regulador y no se
        tocan. <strong>Guardar crea una versión nueva</strong> y deja la
        anterior intacta.
      </p>

      {datos.secciones.map((s) => (
        <Seccion key={s.clave} seccion={s}
                 contenido={Object.prototype.hasOwnProperty.call(borradores, s.clave)
                   ? borradores[s.clave] : s.contenido}
                 alCambiar={cambiar} />
      ))}

      {error && (
        <div className="wt-estado-error" style={{ marginBottom: 'var(--e-2)' }}>
          {error}
          {diferencias.length > 0 && (
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {diferencias.map((d) => <li key={d}>{d}</li>)}
            </ul>
          )}
        </div>
      )}

      {!lectura && (
        <div style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center' }}>
          <button className="wt-btn wt-btn-primario" type="button"
                  disabled={!tocado || estado === 'guardando'}
                  onClick={guardar}>
            {estado === 'guardando' ? 'Guardando…' : 'Guardar como versión nueva'}
          </button>
          {tocado && (
            <>
              <button className="wt-btn" type="button"
                      disabled={estado === 'guardando'}
                      onClick={() => { setBorradores({}); setError(''); setDiferencias([]); }}>
                Descartar los cambios
              </button>
              <span style={{ fontSize: 'var(--texto-sm)',
                             color: 'var(--nivel-alto-texto)' }}>
                Si el reporte estaba revisado, guardar anula esa revisión.
              </span>
            </>
          )}
        </div>
      )}
    </>
  );
}
