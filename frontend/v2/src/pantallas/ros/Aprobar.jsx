/* ============================================================================
   Revisar y aprobar un ROS
   ----------------------------------------------------------------------------
   QUIEN APRUEBA TIENE QUE PODER VER QUÉ TOCÓ UNA PERSONA. El reporte lo
   generó GEREO; lo que se manda al regulador puede estar corregido. Sin el
   diff contra la versión original, «aprobar» es firmar un documento sin saber
   en qué se diferencia del que produjo el sistema.

   LOS CAMPOS VACIADOS VAN RESALTADOS. Vaciar es la única forma de BORRAR un
   dato que GEREO sí trajo —un RUT, un monto— y el documento va a salir sin
   él. Un cambio de valor se ve; un campo que desapareció, no.

   EL ACUSE DE IA NO ES UN TECNICISMO. Si el texto es el que redactó el
   modelo, palabra por palabra, quien firma lo dice con todas las letras y
   queda registrado. Es la pregunta que va a hacer una auditoría.

   LOS PUNTOS PENDIENTES SE MUESTRAN, NO SE RESUMEN. GEREO devuelve el
   reporte incompleto A PROPÓSITO: hay campos que dependen del criterio de
   una persona. Para aprobar hay que acusarlos, y un checkbox que dice «acuso
   los puntos pendientes» sin decir cuáles es una firma en blanco.

   ENTREGAR ES LO ÚLTIMO QUE HACE WATCHTOWER CON ESTE REPORTE. Después queda
   bloqueado y la conversación sigue en Slack, fuera de acá. Se dice antes de
   apretar, no después.

   LOS CONTROLES ESTÁN EN EL BACKEND. Acá se muestran y se deshabilitan
   botones, que es cortesía. El rol y el cuatro ojos los decide la Lambda con
   el correo del token.
   ========================================================================= */

import { useEffect, useState } from 'react';

import { estadoDeEntrega } from '../../comun/ros.js';

function Cambio({ c }) {
  return (
    <li style={{ marginBottom: 4 }}>
      <code style={{ fontSize: 'var(--texto-xs)' }}>{c.ruta}</code>
      {c.agregado ? (
        <span style={{ color: 'var(--g66-azul-texto)',
                       fontWeight: 'var(--peso-medio)' }}>
          {' '}— agregado: «{c.despues}»
        </span>
      ) : c.vaciado ? (
        <span style={{ color: 'var(--nivel-alto-texto)',
                       fontWeight: 'var(--peso-medio)' }}>
          {' '}— se vació: decía «{c.antes}»
        </span>
      ) : (
        <span style={{ color: 'var(--texto-2)' }}>
          {' '}— «{c.antes || '(vacío)'}» → «{c.despues || '(vacío)'}»
        </span>
      )}
    </li>
  );
}

export function Aprobar({ api, ros, folio, version, etapa, lectura, alCambiar }) {
  const [d, setD] = useState(null);
  const [estado, setEstado] = useState('cargando');
  const [error, setError] = useState('');
  const [motivos, setMotivos] = useState([]);
  const [acuse, setAcuse] = useState(false);
  const [acuseGereo, setAcuseGereo] = useState(false);
  const [entrega, setEntrega] = useState(null);

  useEffect(() => {
    let vivo = true;
    setEstado('cargando'); setError(''); setMotivos([]);
    setAcuse(false); setAcuseGereo(false); setEntrega(null);
    api.get(`/ros/${encodeURIComponent(folio)}/diff`)
      .then((x) => { if (vivo) { setD(x); setEstado(''); } })
      .catch((e) => {
        if (vivo) { setError(e?.message || 'No pude leer el reporte.'); setEstado('error'); }
      });
    return () => { vivo = false; };
  }, [api, folio, version, etapa]);

  async function mover(accion, cuerpo) {
    setEstado(accion); setError(''); setMotivos([]);
    try {
      const res = await api.post(
        `/ros/${encodeURIComponent(folio)}/${accion}`, cuerpo);
      setEstado('');
      if (res?.entrega) setEntrega(res.entrega);
      alCambiar(res?.ros);
    } catch (e) {
      setEstado('error');
      setError(e?.message || 'No se pudo.');
      // El backend devuelve TODOS los motivos. Mostrarlos de a uno hace que
      // alguien arregle el primero y vuelva a chocar con el segundo.
      if (Array.isArray(e?.datos?.motivos)) setMotivos(e.datos.motivos);
      // UNA ENTREGA QUE NO SALIÓ NO ES UN ERROR CUALQUIERA. El reporte se
      // movió a «Error de entrega» y volvió a ser editable, y de la respuesta
      // depende si conviene reintentar o corregir. Decirlo sólo con el
      // mensaje de error dejaría a la persona sin saber cuál de las dos.
      if (e?.datos?.entrega) setEntrega(e.datos.entrega);
    }
  }

  if (estado === 'cargando') return <p className="wt-estado">Leyendo el reporte…</p>;
  if (!d) return <div className="wt-estado-error">{error || 'No pude leerlo.'}</div>;

  const cambios = d.cambios || [];
  const vaciados = d.vaciados || [];
  const pendientes = d.pendientes || [];
  const { aprobado, puedeEntregar: sePuedeEntregar } = estadoDeEntrega(ros);
  const puedeEntregar = sePuedeEntregar && !lectura;
  const puedeAprobar = etapa === 'revisado' && !lectura && !aprobado
    && (!d.narrativa_es_de_ia || acuse)
    && (pendientes.length === 0 || acuseGereo);

  // POR QUÉ NO SE PUEDE, EN EL TOOLTIP. Un botón gris sin explicación hace
  // que la persona pruebe los checkboxes a ver cuál lo despierta.
  const motivoDeBloqueo = [
    d.narrativa_es_de_ia && !acuse
      && 'Falta acusar que el texto lo redactó una IA',
    pendientes.length > 0 && !acuseGereo
      && 'Falta acusar los puntos que GEREO dejó a tu criterio',
  ].filter(Boolean).join('. ');

  return (
    <>
      {!d.hay_oficiales && (
        <p className="wt-nota wt-nota-alarma">
          <strong>No hay ningún Oficial de Cumplimiento designado.</strong>{' '}
          Hasta que un administrador cargue el padrón, nadie puede aprobar un
          ROS. No es una falla: es el control funcionando.
        </p>
      )}

      <h4 style={{ fontSize: 'var(--texto-sm)', margin: '0 0 var(--e-2)' }}>
        Qué cambió desde que lo generó GEREO
      </h4>

      {cambios.length === 0 ? (
        <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Nada: el reporte es exactamente el que devolvió GEREO.
        </p>
      ) : (
        <>
          {(cambios.filter((c) => c.agregado).length > 0) && (
            <div className="wt-nota"
                 style={{ borderColor: 'var(--g66-azul-texto)',
                          background: 'var(--g66-azul-tenue)',
                          color: 'var(--g66-azul-texto)' }}>
              <strong>
                Se agregaron {cambios.filter((c) => c.agregado).length} dato
                {cambios.filter((c) => c.agregado).length === 1 ? '' : 's'} que
                GEREO no había encontrado.
              </strong>{' '}
              No son correcciones: los puso una persona.
            </div>
          )}

          {vaciados.length > 0 && (
            <div className="wt-nota"
                 style={{ borderColor: 'var(--nivel-alto-texto)',
                          background: 'var(--nivel-alto-tenue)',
                          color: 'var(--nivel-alto-texto)' }}>
              <strong>
                {vaciados.length} campo{vaciados.length === 1 ? '' : 's'} que
                GEREO había llenado {vaciados.length === 1 ? 'quedó' : 'quedaron'} en
                blanco.
              </strong>{' '}
              El reporte va a salir sin ese dato.
            </div>
          )}
          <ul style={{ margin: 'var(--e-2) 0', paddingLeft: 18,
                       fontSize: 'var(--texto-sm)' }}>
            {cambios.map((c) => <Cambio key={c.ruta} c={c} />)}
          </ul>
        </>
      )}

      {pendientes.length > 0 && (
        <>
          {/* QUÉ SE ESTÁ ACUSANDO, ENUMERADO. GEREO devuelve el reporte
              incompleto a propósito y estos son los campos que dependen del
              criterio de una persona. Un checkbox sin la lista es una firma
              en blanco. */}
          <div className="wt-nota" style={{ marginTop: 'var(--e-3)' }}>
            <strong>
              El borrador de GEREO deja {pendientes.length} punto
              {pendientes.length === 1 ? '' : 's'} a tu criterio:
            </strong>
            <ul style={{ margin: 'var(--e-1) 0 0', paddingLeft: 18,
                         fontSize: 'var(--texto-sm)' }}>
              {pendientes.map((p) => <li key={p}>{p}</li>)}
            </ul>
          </div>
          <label className="wt-checklist-item"
                 style={{ cursor: 'pointer', marginTop: 'var(--e-2)' }}>
            <input type="checkbox" checked={acuseGereo}
                   onChange={(e) => setAcuseGereo(e.target.checked)} />
            <span style={{ fontSize: 'var(--texto-sm)' }}>
              <strong>Leí esos puntos y me hago cargo.</strong> Quedan
              registrados a tu nombre, con la hora.
            </span>
          </label>
        </>
      )}

      {d.narrativa_es_de_ia && (
        <label className="wt-checklist-item"
               style={{ cursor: 'pointer', marginTop: 'var(--e-3)' }}>
          <input type="checkbox" checked={acuse}
                 onChange={(e) => setAcuse(e.target.checked)} />
          <span style={{ fontSize: 'var(--texto-sm)' }}>
            <strong>El texto de este reporte lo redactó una IA y no se
            modificó.</strong> Lo leí, lo valido y lo firmo igual. Queda
            registrado a tu nombre.
          </span>
        </label>
      )}

      {entrega && (
        <div className="wt-nota"
             style={{ marginTop: 'var(--e-3)',
                      borderColor: entrega.entregado
                        ? 'var(--nivel-bajo-texto)' : 'var(--nivel-alto-texto)',
                      background: entrega.entregado
                        ? 'var(--nivel-bajo-tenue)' : 'var(--nivel-alto-tenue)',
                      color: entrega.entregado
                        ? 'var(--nivel-bajo-texto)' : 'var(--nivel-alto-texto)' }}>
          <strong>{entrega.entregado ? 'Entregado a GEREO.' : 'No se entregó.'}</strong>{' '}
          {entrega.mensaje}
          {entrega.entrega_id && (
            <> <br /><span style={{ fontSize: 'var(--texto-xs)' }}>
              Acuse de GEREO: <code>{entrega.entrega_id}</code>
            </span></>
          )}
          {!entrega.entregado && entrega.reintentable && (
            <> <br /><span style={{ fontSize: 'var(--texto-xs)' }}>
              Se puede reintentar con la misma versión: GEREO no duplica.
            </span></>
          )}
        </div>
      )}

      {(error || motivos.length > 0) && (
        <div className="wt-estado-error" style={{ marginTop: 'var(--e-2)' }}>
          {motivos.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {motivos.map((m) => <li key={m}>{m}</li>)}
            </ul>
          ) : error}
        </div>
      )}

      {!lectura && (
        <div style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center',
                      marginTop: 'var(--e-3)', flexWrap: 'wrap' }}>
          {etapa === 'recibido' && (
            <button className="wt-btn" type="button"
                    disabled={Boolean(estado)}
                    onClick={() => mover('revisar', {})}>
              {estado === 'revisar' ? 'Guardando…' : 'Marcar como revisado'}
            </button>
          )}
          {etapa === 'revisado' && !aprobado && (
            <button className="wt-btn wt-btn-primario" type="button"
                    disabled={!puedeAprobar || Boolean(estado)}
                    title={motivoDeBloqueo}
                    onClick={() => mover('aprobar',
                                         { version, acuse_ia: acuse,
                                           acuse_gereo: acuseGereo })}>
              {estado === 'aprobar' ? 'Aprobando…' : 'Aprobar'}
            </button>
          )}
          {/* ENTREGAR APARECE RECIÉN CON LA APROBACIÓN HECHA, y sobre esta
              misma versión: una aprobación de una versión anterior ya no vale
              y el backend la rechaza. Mostrar el botón igual sería ofrecer
              algo que no va a funcionar. */}
          {puedeEntregar && (
            <button className="wt-btn wt-btn-primario" type="button"
                    disabled={Boolean(estado)}
                    onClick={() => mover('entregar', {})}>
              {estado === 'entregar' ? 'Entregando…' : 'Entregar a GEREO'}
            </button>
          )}
          <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            {/* Se dice ANTES de apretar: enterarse después de que el botón no
                anda es peor que saber de entrada por qué. */}
            {puedeEntregar
              ? ('Entregar es lo último que hace WatchTower con este reporte: '
                 + 'después queda bloqueado y la autorización para cargarlo al '
                 + 'regulador se decide en Slack, fuera de acá.')
              : ('Aprobar está reservado al Oficial de Cumplimiento, y no puede '
                 + 'hacerlo quien revisó ni quien editó este reporte.')}
          </span>
        </div>
      )}
    </>
  );
}
