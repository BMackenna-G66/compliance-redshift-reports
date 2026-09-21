import { PANTALLAS } from '../dominio.js';

/* El relleno de las pantallas que todavía no se construyeron.
   Dice cuál es y en qué fase entra, para que navegar por v2 mientras se
   arma no parezca una aplicación rota sino una a medio hacer. */
export function Pendiente({ id, fase }) {
  const p = PANTALLAS.find((x) => x.id === id);
  return (
    <div className="wt-pendiente">
      <h2>{p?.titulo || id}</h2>
      <p>
        Todavía no está construida. Entra en la <strong>{fase || 'próxima fase'}</strong> del
        plan.
      </p>
      <p>
        Permiso: <code>{p?.modulo || '—'}</code>
        {p?.nuevo && ' · pantalla nueva, sin equivalente en el WatchTower actual'}
      </p>
    </div>
  );
}
