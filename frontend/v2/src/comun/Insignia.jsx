/* Insignias de prioridad y de estado del caso.
 *
 * La regla que comparten: lo que no se sabe se pinta de "no se sabe", nunca
 * del color más tranquilizador. Una alerta sin puntaje con la insignia verde
 * de P3 diría que ya se la evaluó y salió baja. */

import { ESCALA_ALERTA, ESTADOS_CASO } from '../dominio.js';

export function InsigniaPrioridad({ prioridad }) {
  if (!prioridad) {
    return (
      <span className="wt-insignia wt-insignia-sindato"
            title="El reporte no dejó puntaje para esta alerta: no se la evaluó">
        sin puntaje
      </span>
    );
  }
  const d = ESCALA_ALERTA[prioridad];
  if (!d) return <span className="wt-insignia wt-insignia-sindato">{prioridad}</span>;
  return (
    <span className="wt-insignia"
          style={{ color: d.texto, background: d.fondo }}
          title={`${d.descripcion} · puntaje ≥ ${d.desde} de 100`}>
      {d.etiqueta}
    </span>
  );
}

export function InsigniaCaso({ alerta }) {
  if (!alerta?.tiene_caso) {
    return <span className="wt-insignia wt-insignia-sindato">Sin caso</span>;
  }
  const d = ESTADOS_CASO[alerta.caso_estado];
  // Un estado que el backend agregue y acá no esté se muestra crudo: mejor un
  // valor raro que una celda en blanco que parece un bug.
  const etiqueta = d?.etiqueta || alerta.caso_estado_es || alerta.caso_estado;
  return (
    <span className="wt-insignia"
          style={{ color: d?.color || 'var(--texto-2)', background: 'var(--superficie-3)' }}
          title={alerta.caso_vinculo === 'vinculado'
            ? 'Esta alerta está atada a ese caso'
            : 'El cliente tiene ese caso, pero nadie ató esta alerta a él'}>
      {etiqueta}
      {alerta.caso_vinculo === 'del_cliente' && ' ·'}
    </span>
  );
}
