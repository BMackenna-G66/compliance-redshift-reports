import { GRUPOS, PANTALLAS } from '../dominio.js';
import { menuPara } from '../permisos.js';

export function Sidebar({ perfil, actual, alNavegar }) {
  const menu = menuPara(perfil, PANTALLAS, GRUPOS);

  return (
    <nav className="wt-sidebar" aria-label="Secciones">
      {menu.map(({ grupo, pantallas }) => (
        <div key={grupo}>
          <div className="wt-grupo">{grupo}</div>
          <div className="wt-nav">
            {pantallas.map((p) => (
              <button
                key={p.id}
                className="wt-nav-item"
                aria-current={p.id === actual ? 'page' : undefined}
                onClick={() => alNavegar(p.id)}
              >
                {p.titulo}
                {/* Marcar lo que todavía no existe evita que alguien lo
                    reporte como roto — y recuerda qué falta construir. */}
                {p.nuevo && <span className="wt-nav-nuevo">NUEVO</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}
