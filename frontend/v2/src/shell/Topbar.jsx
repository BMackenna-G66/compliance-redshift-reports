import { esAdmin, soloLectura } from '../permisos.js';

const NOMBRE_ROL = {
  superadmin: 'Super admin',
  admin: 'Administrador',
  analyst: 'Analista',
  lectura: 'Sólo lectura',
};

export function Topbar({ email, perfil, tema, alCambiarTema, alSalir }) {
  return (
    <header className="wt-topbar">
      <span className="wt-marca">WatchTower</span>

      <div className="wt-topbar-derecha">
        <div style={{ textAlign: 'right', lineHeight: 1.3 }}>
          <div className="wt-usuario">{email}</div>
          <div className="wt-usuario-rol">
            {NOMBRE_ROL[perfil?.rol] || perfil?.rol || '—'}
            {soloLectura(perfil) && ' · no modifica'}
            {esAdmin(perfil) && ' · administra'}
          </div>
        </div>
        <button
          className="wt-btn"
          onClick={alCambiarTema}
          title={tema === 'oscuro' ? 'Pasar a tema claro' : 'Pasar a tema oscuro'}
          aria-label={tema === 'oscuro' ? 'Pasar a tema claro' : 'Pasar a tema oscuro'}
        >
          {tema === 'oscuro' ? '☀' : '☾'}
        </button>
        <button className="wt-btn" onClick={alSalir}>Salir</button>
      </div>
    </header>
  );
}
