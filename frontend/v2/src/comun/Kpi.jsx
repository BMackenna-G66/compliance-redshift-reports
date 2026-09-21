/* Un indicador del tablero.
 *
 * Si recibe `alPulsar` se comporta como botón y filtra la tabla de abajo. Que
 * el número sea el filtro es el punto: leer "50 sin caso" y tener que ir a
 * buscar el filtro en otro lado es hacer dos veces el mismo trabajo. */

export function Kpi({ etiqueta, valor, pie, principal = false, alPulsar, activo = false }) {
  const contenido = (
    <>
      <span className="wt-kpi-etiqueta">{etiqueta}</span>
      <span className="wt-kpi-valor">{valor}</span>
      {pie && <span className="wt-kpi-pie">{pie}</span>}
    </>
  );

  const clase = 'wt-kpi' + (principal ? ' wt-kpi-principal' : '');

  if (!alPulsar) return <div className={clase}>{contenido}</div>;

  return (
    <button className={clase} onClick={alPulsar} aria-pressed={activo}
            title={activo ? 'Quitar el filtro' : `Filtrar por ${etiqueta.toLowerCase()}`}>
      {contenido}
    </button>
  );
}
