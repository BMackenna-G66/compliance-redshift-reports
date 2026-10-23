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
  agregadosVacios, campos, coaccionar, conUnoMas, cuerpoDeGuardado, escribir,
  esTextoLargo, leer, listasDe, paraMostrar, plantillaDeLista, sePuedeAgregar,
} from '../../comun/formulario_ros.js';

function Campo({ campo, alCambiar, crudo, enError }) {
  const { ruta, etiqueta: titulo, tipo, valor } = campo;
  // Se muestra lo que la persona está escribiendo mientras escribe, y el
  // valor formateado cuando no. Si se mostrara siempre el valor, al escribir
  // «1.2» el campo saltaría a otra cosa en mitad de la tecla.
  const mostrado = crudo !== undefined ? crudo : paraMostrar(valor);

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
                  value={mostrado}
                  onChange={(e) => alCambiar(ruta, e.target.value)} />
      ) : (
        <input className="wt-input"
               style={{ display: 'block', width: '100%', marginTop: 4,
                        borderColor: enError ? 'var(--nivel-alto-texto)' : undefined }}
               /* `text` incluso para los números: un `number` nativo rechaza
                  pegar «1.234.567» y los montos llegan así. La lectura la
                  hace `parsearNumero`, con punto de miles y coma decimal. */
               type="text"
               value={mostrado}
               onChange={(e) => alCambiar(ruta, e.target.value)} />
      )}
      {enError && (
        <span style={{ display: 'block', marginTop: 2,
                       fontSize: 'var(--texto-xs)',
                       color: 'var(--nivel-alto-texto)' }}>
          No se entiende como número. Usá punto para los miles y coma para los
          decimales: 1.234.567 o 1.234,5.
        </span>
      )}
    </label>
  );
}

function Seccion({ seccion, contenido, alCambiar, alAgregar, crudos, errores }) {
  // Un «Agregar» por lista. Compliance lo habilitó el 23-10-2026: a un
  // reporte le puede faltar un reportado. QUITAR sigue sin poder.
  const listas = listasDe(contenido);
  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-3)' }}>
      <header className="wt-carta-cabecera">
        <h3 className="wt-carta-titulo" style={{ fontSize: 'var(--texto-base)' }}>
          {seccion.titulo}
        </h3>
      </header>
      <div className="wt-cuerpo-carta"
           style={{ display: 'grid', gap: 'var(--e-3)' }}>
        {campos(contenido).map((c) => {
          const llave = `${seccion.clave}|${c.ruta}`;
          return (
            <Campo key={c.ruta} campo={c}
                   crudo={crudos[llave]} enError={errores.has(llave)}
                   alCambiar={(ruta, crudo) => alCambiar(seccion.clave, ruta, crudo)} />
          );
        })}

        {listas.map((l) => (
          <div key={l.ruta}>
            <button className="wt-btn" type="button"
                    disabled={!sePuedeAgregar(l.plantilla)}
                    title={sePuedeAgregar(l.plantilla) ? ''
                      : 'GEREO no devolvió ningún elemento acá, así que no hay '
                        + 'de dónde copiar la forma. Pedí otra generación.'}
                    onClick={() => alAgregar(seccion.clave, l.ruta)}>
              + Agregar a «{l.etiqueta}»
            </button>
            {!sePuedeAgregar(l.plantilla) && (
              <span style={{ marginLeft: 'var(--e-2)',
                             fontSize: 'var(--texto-xs)',
                             color: 'var(--texto-mute)' }}>
                vacía en el reporte original: pedí otra generación a GEREO
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export function Formulario({ api, folio, version, alGuardar, lectura }) {
  const [datos, setDatos] = useState(null);
  const [borradores, setBorradores] = useState({});
  // Lo que la persona está escribiendo, tal cual, y qué campos no se pueden
  // leer. Separados del borrador a propósito: un «1.2» a medio escribir no
  // puede entrar al documento que se va a reportar.
  const [crudos, setCrudos] = useState({});
  const [errores, setErrores] = useState(new Set());
  const [estado, setEstado] = useState('cargando');
  const [error, setError] = useState('');
  const [diferencias, setDiferencias] = useState([]);

  useEffect(() => {
    let vivo = true;
    setEstado('cargando'); setError(''); setBorradores({}); setDiferencias([]);
    setCrudos({}); setErrores(new Set());
    api.get(`/ros/${encodeURIComponent(folio)}/versiones/${version}`)
      .then((d) => { if (vivo) { setDatos(d); setEstado(''); } })
      .catch((e) => { if (vivo) { setError(e?.message || 'No pude leer la versión.'); setEstado('error'); } });
    return () => { vivo = false; };
  }, [api, folio, version]);

  function cambiar(claveSeccion, ruta, texto) {
    const llave = `${claveSeccion}|${ruta}`;
    setCrudos((c) => ({ ...c, [llave]: texto }));

    const base = Object.prototype.hasOwnProperty.call(borradores, claveSeccion)
      ? borradores[claveSeccion]
      : (datos.secciones.find((s) => s.clave === claveSeccion) || {}).contenido;
    // El valor ORIGINAL manda el tipo: `coaccionar` lo usa para devolver un
    // número donde había un número.
    const valor = coaccionar(leer(base, ruta), texto);

    // UN NÚMERO ILEGIBLE NO VUELVE AL ANTERIOR EN SILENCIO. Eso le haría
    // creer a alguien que guardó una corrección que no se guardó, y acá lo
    // que no se guardó es un monto de un reporte al regulador. Se marca el
    // campo y se bloquea el guardado hasta que lo arregle una persona.
    const malo = typeof valor === 'number' && Number.isNaN(valor);
    setErrores((e) => {
      const n = new Set(e);
      if (malo) n.add(llave); else n.delete(llave);
      return n;
    });
    if (malo) return;

    setBorradores((b) => ({ ...b, [claveSeccion]: escribir(base, ruta, valor) }));
  }

  function agregar(claveSeccion, ruta) {
    const base = Object.prototype.hasOwnProperty.call(borradores, claveSeccion)
      ? borradores[claveSeccion]
      : (datos.secciones.find((s) => s.clave === claveSeccion) || {}).contenido;
    // La plantilla sale de la lista TAL COMO ESTÁ. El control de forma del
    // backend obliga a que cada elemento existente tenga la forma del de la
    // v1, así que el primero de acá sirve igual — y si está vacía, la v1
    // también lo estaba, porque quitar no se puede.
    const lista = leer(base, ruta) || [];
    // La plantilla sale del elemento 0, no de esta lista: una lista anidada
    // dentro de un elemento recién agregado está vacía y no tiene de dónde
    // copiarse a sí misma.
    const plantilla = plantillaDeLista(base, ruta);
    setBorradores((b) => ({
      ...b, [claveSeccion]: escribir(base, ruta, conUnoMas(lista, plantilla)),
    }));
  }

  async function guardar() {
    setEstado('guardando'); setError(''); setDiferencias([]);
    try {
      const d = await api.post(
        `/ros/${encodeURIComponent(folio)}/versiones`,
        cuerpoDeGuardado(datos.secciones, borradores, version));
      setBorradores({}); setCrudos({}); setErrores(new Set());
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
  const hayErrores = errores.size > 0;
  // Un elemento agregado y dejado en blanco termina en el reporte al
  // regulador como un reportado sin nombre ni documento. El backend lo
  // rechaza; esto lo dice ANTES de apretar «Guardar».
  const vacios = datos.secciones.flatMap((s) => {
    const actual = Object.prototype.hasOwnProperty.call(borradores, s.clave)
      ? borradores[s.clave] : s.contenido;
    return agregadosVacios(actual, s.contenido).map((r) => `${s.clave}.${r}`);
  });

  return (
    <>
      <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
        Versión {datos.version} · {datos.pais}. Podés corregir los valores;
        los campos y su orden los fija el formulario del regulador y no se
        tocan. <strong>Guardar crea una versión nueva</strong> y deja la
        anterior intacta.
      </p>

      {datos.secciones.map((s) => (
        <Seccion key={s.clave} seccion={s} crudos={crudos} errores={errores}
                 contenido={Object.prototype.hasOwnProperty.call(borradores, s.clave)
                   ? borradores[s.clave] : s.contenido}
                 alCambiar={cambiar} alAgregar={agregar} />
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
                  disabled={!tocado || hayErrores || vacios.length > 0
                    || estado === 'guardando'}
                  title={hayErrores ? 'Hay campos que no se entienden como número'
                    : vacios.length > 0 ? 'Hay elementos agregados sin ningún dato'
                      : ''}
                  onClick={guardar}>
            {estado === 'guardando' ? 'Guardando…' : 'Guardar como versión nueva'}
          </button>
          {hayErrores && (
            <span style={{ fontSize: 'var(--texto-sm)',
                           color: 'var(--nivel-alto-texto)' }}>
              {errores.size} campo{errores.size === 1 ? '' : 's'} sin resolver.
            </span>
          )}
          {vacios.length > 0 && (
            <span style={{ fontSize: 'var(--texto-sm)',
                           color: 'var(--nivel-alto-texto)' }}>
              Agregaste {vacios.length} elemento
              {vacios.length === 1 ? '' : 's'} sin ningún dato: llenalo
              {vacios.length === 1 ? '' : 's'} antes de guardar.
            </span>
          )}
          {tocado && (
            <>
              <button className="wt-btn" type="button"
                      disabled={estado === 'guardando'}
                      onClick={() => { setBorradores({}); setCrudos({});
                                       setErrores(new Set()); setError('');
                                       setDiferencias([]); }}>
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
