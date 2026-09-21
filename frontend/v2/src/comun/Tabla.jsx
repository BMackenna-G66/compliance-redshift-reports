/* ============================================================================
   La tabla densa
   ----------------------------------------------------------------------------
   Catorce de las veinte pantallas son una tabla. Vale la pena que esta esté
   bien una vez, en vez de repetirla catorce veces con variaciones.

   La lógica (ordenar, filtrar, paginar, exportar) vive en `tabla.js` y tiene
   sus propios tests; acá está sólo el dibujo.

   Las columnas se describen así:
     { clave, titulo, ancho?, tipo?: 'texto'|'numero'|'mono',
       render?: (fila) => nodo, exportar?: (fila) => string, ordenable?: bool }
   ========================================================================= */

import { useMemo, useState } from 'react';
import { aCSV, filtrar, ordenar, paginar, totalPaginas } from './tabla.js';

function claseDeCelda(col) {
  if (col.tipo === 'numero') return 'wt-td-num';
  if (col.tipo === 'mono') return 'wt-td-mono';
  return '';
}

function descargarCSV(texto, nombre) {
  const url = URL.createObjectURL(new Blob([texto], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Sin esto el blob queda en memoria hasta que se cierra la pestaña, y en
  // esta app se exporta muchas veces por sesión.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Tabla({
  titulo,
  columnas,
  filas,
  cargando = false,
  error = '',
  alReintentar,
  buscable = true,
  exportable = true,
  nombreExport = 'watchtower',
  porPagina = 50,
  claveFila = (f, i) => f?.id ?? i,
  herramientas = null,
  vacioTexto = 'No hay nada para mostrar.',
}) {
  const [busqueda, setBusqueda] = useState('');
  const [orden, setOrden] = useState({ clave: '', direccion: 'asc' });
  const [pagina, setPagina] = useState(1);

  const clavesBuscables = useMemo(
    () => columnas.filter((c) => c.buscable !== false).map((c) => c.clave),
    [columnas],
  );

  const filtradas = useMemo(
    () => filtrar(filas || [], busqueda, clavesBuscables),
    [filas, busqueda, clavesBuscables],
  );
  const ordenadas = useMemo(
    () => ordenar(filtradas, orden.clave, orden.direccion),
    [filtradas, orden],
  );

  const paginas = totalPaginas(ordenadas.length, porPagina);
  // Filtrar puede dejar menos páginas de las que había: si el usuario estaba
  // en la 7 y quedan 2, mostrarle una tabla vacía parecería que no hay datos.
  const paginaSegura = Math.min(pagina, paginas);
  const visibles = paginar(ordenadas, paginaSegura, porPagina);

  function alternarOrden(clave) {
    setOrden((o) =>
      o.clave === clave
        ? { clave, direccion: o.direccion === 'asc' ? 'desc' : 'asc' }
        : { clave, direccion: 'asc' },
    );
    setPagina(1);
  }

  function exportar() {
    // Lo que se baja es lo que se está mirando, filtros incluidos — pero
    // TODAS las páginas, no sólo la que está en pantalla: nadie quiere un
    // archivo con 50 de 300 filas.
    descargarCSV(aCSV(ordenadas, columnas), `${nombreExport}.csv`);
  }

  return (
    <section className="wt-carta">
      <header className="wt-carta-cabecera">
        {titulo && <h2 className="wt-carta-titulo">{titulo}</h2>}
        <div className="wt-carta-herramientas">
          {herramientas}
          {buscable && (
            <input
              className="wt-input"
              type="search"
              placeholder="Buscar…"
              aria-label="Buscar en la tabla"
              value={busqueda}
              onChange={(e) => { setBusqueda(e.target.value); setPagina(1); }}
            />
          )}
          {exportable && (
            <button
              className="wt-btn"
              onClick={exportar}
              disabled={ordenadas.length === 0}
              title="Descarga lo que estás viendo, con los filtros aplicados"
            >
              Exportar CSV
            </button>
          )}
        </div>
      </header>

      {error ? (
        <div className="wt-estado">
          <div className="wt-estado-error">
            <span>{error}</span>
            {alReintentar && (
              <button className="wt-btn" onClick={alReintentar}>Reintentar</button>
            )}
          </div>
        </div>
      ) : cargando ? (
        <p className="wt-estado">Cargando…</p>
      ) : ordenadas.length === 0 ? (
        <p className="wt-estado">
          {busqueda ? `Ningún resultado para «${busqueda}».` : vacioTexto}
        </p>
      ) : (
        <>
          <div className="wt-tabla-marco">
            <table className="wt-tabla">
              <thead>
                <tr>
                  {columnas.map((col) => {
                    const activa = orden.clave === col.clave;
                    return (
                      <th
                        key={col.clave}
                        style={col.ancho ? { width: col.ancho } : undefined}
                        className={claseDeCelda(col)}
                        aria-sort={activa ? (orden.direccion === 'asc' ? 'ascending' : 'descending') : 'none'}
                      >
                        {col.ordenable === false ? (
                          col.titulo
                        ) : (
                          <button
                            className="wt-th-orden"
                            onClick={() => alternarOrden(col.clave)}
                            title={`Ordenar por ${col.titulo}`}
                          >
                            {col.titulo}
                            <span className="wt-flecha" aria-hidden="true">
                              {activa ? (orden.direccion === 'asc' ? '▲' : '▼') : '⇅'}
                            </span>
                          </button>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {visibles.map((fila, i) => (
                  <tr key={claveFila(fila, i)}>
                    {columnas.map((col) => (
                      <td key={col.clave} className={claseDeCelda(col)}>
                        {col.render ? col.render(fila) : fila?.[col.clave] ?? '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {paginas > 1 && (
            <footer className="wt-paginado">
              <span>
                {ordenadas.length.toLocaleString('es-CL')} fila
                {ordenadas.length === 1 ? '' : 's'}
                {filtradas.length !== (filas?.length || 0) &&
                  ` (de ${(filas?.length || 0).toLocaleString('es-CL')})`}
                {' · página '}{paginaSegura} de {paginas}
              </span>
              <div className="wt-paginado-botones">
                <button
                  className="wt-btn"
                  onClick={() => setPagina(paginaSegura - 1)}
                  disabled={paginaSegura <= 1}
                >
                  Anterior
                </button>
                <button
                  className="wt-btn"
                  onClick={() => setPagina(paginaSegura + 1)}
                  disabled={paginaSegura >= paginas}
                >
                  Siguiente
                </button>
              </div>
            </footer>
          )}
        </>
      )}
    </section>
  );
}
