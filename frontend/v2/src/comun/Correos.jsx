/* ============================================================================
   La conversación de correo con el cliente
   ----------------------------------------------------------------------------
   Pedido para auditorías: «reconstruir el análisis realizado». El dato existía
   repartido entre los envíos, las notas del caso y los adjuntos; acá se lee
   como una conversación.

   La usan dos pantallas con la misma forma y un matiz: el detalle del caso
   muestra los correos de ESE caso, y la ficha del cliente los junta de TODOS
   sus casos — y ahí hace falta decir de cuál salió cada uno, o no se sabe a
   qué se refiere.
   ========================================================================= */

import { cuerpoRecortado, esFallido } from './expediente.js';

export function Correos({ correos, mostrarCaso = false, alAbrirCaso = null }) {
  return correos.map((m, i) => {
    const fallo = esFallido(m);
    const entrante = m.direccion !== 'enviado';
    const { texto, recortado } = cuerpoRecortado(m);
    return (
      <article
        key={`correo-${i}`}
        className="wt-correo"
        style={{
          borderLeftColor: fallo ? 'var(--nivel-critico-texto)'
            : entrante ? 'var(--g66-azul-texto)' : 'var(--borde)',
        }}
      >
        <div className="wt-correo-meta">
          <strong style={{ color: entrante ? 'var(--g66-azul-texto)' : 'var(--texto-2)' }}>
            {entrante ? 'Recibido' : 'Enviado'}
          </strong>
          {' · '}{entrante ? `de ${m.de || '—'}` : `a ${m.para || '—'}`}
          {mostrarCaso && m.case_title && (
            alAbrirCaso ? (
              <button className="wt-enlace" onClick={() => alAbrirCaso(m.case_id)}
                      title="Abrir el caso del que salió">
                {m.case_title}
              </button>
            ) : (
              <span className="wt-insignia"
                    style={{ color: 'var(--texto-2)', background: 'var(--superficie-3)' }}>
                {m.case_title}
              </span>
            )
          )}
          <span style={{ marginLeft: 'auto' }}>{String(m.cuando || '').slice(0, 16)}</span>
        </div>

        {/* Un envío que falló también es historia: explica un silencio. Sin
            esto, un correo que nunca llegó se lee como «el cliente no
            contestó», y eso cambia la conclusión del caso. */}
        {fallo && (
          <p style={{ margin: '0 0 4px', fontSize: 'var(--texto-sm)',
                      color: 'var(--nivel-critico-texto)' }}>
            No se envió: {m.error || 'sin detalle'}
          </p>
        )}

        {m.asunto && <p className="wt-correo-asunto">{m.asunto}</p>}
        {texto && <p className="wt-correo-cuerpo">{texto}{recortado && '…'}</p>}
        {!m.cuerpo && !entrante && (
          <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            (el cuerpo no se guardaba cuando se envió este correo)
          </p>
        )}

        {(m.documentos || []).length > 0 && (
          <div className="wt-correo-docs">
            {(m.documentos || []).map((d, j) => (
              <span key={`doc-${i}-${j}`} className="wt-insignia"
                    style={{ color: 'var(--texto-2)', background: 'var(--superficie-3)' }}>
                {d}
              </span>
            ))}
          </div>
        )}
      </article>
    );
  });
}
