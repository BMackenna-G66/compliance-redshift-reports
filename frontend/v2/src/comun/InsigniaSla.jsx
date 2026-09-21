/* La insignia del semáforo del plazo.
 *
 * El texto lo manda el backend (`sla_etiqueta`); acá está el color y, cuando
 * el caso está vencido, hace cuánto. "Vencido" a secas no distingue el que
 * venció anoche del que lleva 44 días — y en los datos de hoy esa diferencia
 * es todo lo que hay, porque están vencidos todos. */

import { diasTexto, diasVencido, etiquetaSla, semaforoDe } from './casos.js';
import { SLA_SIN_RELOJ } from '../dominio.js';

export function InsigniaSla({ caso, conDetalle = true }) {
  const sem = semaforoDe(caso);

  if (sem === SLA_SIN_RELOJ) {
    return (
      <span className="wt-insignia wt-insignia-sindato"
            title="Este caso no nació de una alerta transaccional: no tiene plazo que medir">
        {etiquetaSla(caso)}
      </span>
    );
  }

  const vencido = diasVencido(caso);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="wt-insignia" style={{ color: sem.color, background: sem.fondo }}>
        {etiquetaSla(caso)}
      </span>
      {conDetalle && vencido !== null && (
        <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}
              title={`El plazo venció el ${caso.sla_cierre_at || '—'}`}>
          hace {diasTexto(vencido)}
        </span>
      )}
    </span>
  );
}
