/* ============================================================================
   Consulta de cliente (CX)
   ----------------------------------------------------------------------------
   Una caja de búsqueda y una respuesta. Es la pantalla para atender una
   llamada: el cliente pregunta por qué le pidieron papeles, y de este lado hay
   que saber si tiene algo abierto sin leer una tabla de doce columnas.

   ES DE SÓLO LECTURA POR CONSTRUCCIÓN, no por permisos: no hay un solo botón
   que escriba. El perfil de CX igual está limitado, pero esta pantalla no
   depende de eso para ser segura.

   LO QUE NO MUESTRA, A PROPÓSITO: el motivo de la alerta, el puntaje de
   riesgo, el reporte que la disparó, el analista asignado. Nada de eso se le
   dice a un cliente, y tenerlo en pantalla mientras se habla con él es cómo
   se filtra sin querer. Se muestra el estado, hace cuánto, y si hay
   documentación pendiente.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { hace } from '../comun/alertas.js';
import { buscar, indice, respuesta } from '../comun/cx.js';
import { diasTexto } from '../comun/casos.js';
import { ESTADOS_CASO } from '../dominio.js';

const TONO = {
  abiertos: { color: 'var(--nivel-alto-texto)', fondo: 'var(--nivel-alto-tenue)' },
  sin_abiertos: { color: 'var(--nivel-bajo-texto)', fondo: 'var(--nivel-bajo-tenue)' },
  sin_registro: { color: 'var(--texto-2)', fondo: 'var(--superficie-3)' },
};

export function Cx({ api }) {
  const [casos, setCasos] = useState([]);
  const [alertas, setAlertas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [texto, setTexto] = useState('');
  const [buscado, setBuscado] = useState('');

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    // Las dos en paralelo. Si fallan las alertas, la búsqueda por correo deja
    // de andar pero la del id sigue: se avisa en vez de romper la pantalla.
    const [c, a] = await Promise.allSettled([
      api.get('/cases?status=all'),
      api.get('/alerts'),
    ]);
    if (c.status === 'fulfilled') setCasos(c.value?.cases || []);
    if (a.status === 'fulfilled') setAlertas(a.value?.alerts || []);
    if (c.status === 'rejected') {
      setError('No se pudieron leer los casos. Sin eso esta pantalla no puede responder.');
    } else if (a.status === 'rejected') {
      setError('No se pudieron leer las alertas: la búsqueda por correo puede no encontrar '
             + 'a todos. Por id de cliente anda igual.');
    }
    setCargando(false);
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const idx = useMemo(() => indice(casos, alertas), [casos, alertas]);

  /* MIENTRAS CARGA NO SE CONTESTA. Buscar sobre un padrón a medio leer
     devuelve «no figura», y de este lado hay alguien por decirle a un cliente
     que no aparece en el sistema cuando la verdad es que no terminamos de
     leerlo. Es la peor forma de equivocarse que tiene esta pantalla, y es
     silenciosa: la respuesta se ve igual de segura que una buena. */
  const listo = !cargando && casos.length > 0;
  const encontrados = useMemo(
    () => (buscado && listo ? buscar(idx, buscado) : null), [idx, buscado, listo],
  );
  const r = encontrados === null ? null : respuesta(encontrados);
  const tono = r ? TONO[r.clave] : null;

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Consulta de cliente
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          ¿tiene algo abierto con nosotros?
        </span>
      </div>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
        <div className="wt-cuerpo-carta">
          <form
            style={{ display: 'flex', gap: 'var(--e-2)', flexWrap: 'wrap' }}
            onSubmit={(e) => { e.preventDefault(); setBuscado(texto.trim()); }}
          >
            <input
              className="wt-input" style={{ flex: 1, minWidth: 240 }}
              value={texto} onChange={(e) => setTexto(e.target.value)}
              placeholder="Id de cliente, correo, o parte del nombre"
              aria-label="Buscar un cliente"
            />
            <button className="wt-btn wt-btn-primario" type="submit"
                    disabled={cargando || texto.trim().length < 3}>
              Buscar
            </button>
            {buscado && (
              <button className="wt-btn" type="button"
                      onClick={() => { setTexto(''); setBuscado(''); }}>
                Limpiar
              </button>
            )}
          </form>
          <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)',
                      color: 'var(--texto-mute)' }}>
            {cargando
              ? 'Cargando el padrón…'
              : `${idx.length.toLocaleString('es-CL')} clientes en el padrón. `
                + 'El id y el correo se buscan enteros; el nombre, por partes.'}
          </p>
        </div>
      </section>

      {buscado && !listo && (
        <p className="wt-nota">
          Todavía se está leyendo el padrón. La respuesta aparece cuando termine: no se
          contesta sobre datos a medio cargar.
        </p>
      )}

      {r && (
        <>
          <p className="wt-nota"
             style={{ borderColor: tono.color, background: tono.fondo, color: tono.color }}>
            <strong>{r.texto}</strong> {r.detalle}
          </p>

          {encontrados.map((e) => (
            <section key={e.id} className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">{e.nombre || `Cliente ${e.id}`}</h2>
                <span className="mono" style={{ fontSize: 'var(--texto-sm)',
                                                color: 'var(--texto-mute)' }}>
                  {e.id}
                </span>
              </header>
              <div className="wt-cuerpo-carta">
                {e.correos.length > 0 && (
                  <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)',
                              color: 'var(--texto-2)' }}>
                    Correo registrado: {e.correos.join(' · ')}
                  </p>
                )}

                {e.casos.length === 0 ? (
                  <p className="wt-vacio">Sin casos abiertos.</p>
                ) : (
                  <div className="wt-tabla-marco">
                    <table className="wt-tabla">
                      <thead>
                        <tr><th>Estado</th><th>Abierto hace</th>
                          <th>Documentación</th></tr>
                      </thead>
                      <tbody>
                        {e.casos.map((c) => {
                          const pendientes = (c.documentos_checklist || [])
                            .filter((d) => (d.estado || 'pendiente') !== 'entregado').length;
                          return (
                            <tr key={c.case_id}>
                              <td style={{ color: ESTADOS_CASO[c.status]?.color || 'var(--texto-2)' }}>
                                {ESTADOS_CASO[c.status]?.etiqueta || c.status}
                              </td>
                              <td title={c.created_at}>
                                {diasTexto(c.sla_dias) || hace(c.created_at)}
                              </td>
                              {/* Esto es lo único accionable para CX: si hay
                                  papeles pendientes, es lo que el cliente
                                  tiene que mandar. */}
                              <td>
                                {pendientes > 0
                                  ? <span style={{ color: 'var(--nivel-alto-texto)' }}>
                                      {pendientes} documento(s) pendiente(s)
                                    </span>
                                  : <span style={{ color: 'var(--texto-mute)' }}>
                                      nada pendiente de su parte
                                    </span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          ))}

          {/* Lo que CX puede y no puede decir. Está escrito en la pantalla
              porque es donde hace falta: cuando alguien está por contestar. */}
          <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)',
                      maxWidth: 640 }}>
            Al cliente se le puede decir que hay una revisión en curso y qué documentación
            falta. No se le dice por qué se lo está revisando, ni qué alerta lo detectó, ni
            quién lo está mirando.
          </p>
        </>
      )}
    </>
  );
}
