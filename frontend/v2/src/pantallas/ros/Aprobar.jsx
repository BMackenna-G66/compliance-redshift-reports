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

   LOS CONTROLES ESTÁN EN EL BACKEND. Acá se muestran y se deshabilitan
   botones, que es cortesía. El rol y el cuatro ojos los decide la Lambda con
   el correo del token.
   ========================================================================= */

import { useEffect, useState } from 'react';

function Cambio({ c }) {
  return (
    <li style={{ marginBottom: 4 }}>
      <code style={{ fontSize: 'var(--texto-xs)' }}>{c.ruta}</code>
      {c.vaciado ? (
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

export function Aprobar({ api, folio, version, etapa, lectura, alCambiar }) {
  const [d, setD] = useState(null);
  const [estado, setEstado] = useState('cargando');
  const [error, setError] = useState('');
  const [motivos, setMotivos] = useState([]);
  const [acuse, setAcuse] = useState(false);

  useEffect(() => {
    let vivo = true;
    setEstado('cargando'); setError(''); setMotivos([]); setAcuse(false);
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
      alCambiar(res?.ros);
    } catch (e) {
      setEstado('error');
      setError(e?.message || 'No se pudo.');
      // El backend devuelve TODOS los motivos. Mostrarlos de a uno hace que
      // alguien arregle el primero y vuelva a chocar con el segundo.
      if (Array.isArray(e?.datos?.motivos)) setMotivos(e.datos.motivos);
    }
  }

  if (estado === 'cargando') return <p className="wt-estado">Leyendo el reporte…</p>;
  if (!d) return <div className="wt-estado-error">{error || 'No pude leerlo.'}</div>;

  const cambios = d.cambios || [];
  const vaciados = d.vaciados || [];
  const puedeAprobar = etapa === 'revisado' && !lectura
    && (!d.narrativa_es_de_ia || acuse);

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
          {etapa === 'revisado' && (
            <button className="wt-btn wt-btn-primario" type="button"
                    disabled={!puedeAprobar || Boolean(estado)}
                    title={d.narrativa_es_de_ia && !acuse
                      ? 'Falta acusar que el texto lo redactó una IA' : ''}
                    onClick={() => mover('aprobar',
                                         { version, acuse_ia: acuse })}>
              {estado === 'aprobar' ? 'Aprobando…' : 'Aprobar'}
            </button>
          )}
          <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
            {/* Se dice ANTES de apretar: enterarse después de que el botón no
                anda es peor que saber de entrada por qué. */}
            Aprobar está reservado al Oficial de Cumplimiento, y no puede
            hacerlo quien revisó ni quien editó este reporte.
          </span>
        </div>
      )}
    </>
  );
}
