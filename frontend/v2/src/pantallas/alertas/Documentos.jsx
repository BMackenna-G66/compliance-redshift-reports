/* ============================================================================
   Qué documentos se le piden a cada alerta
   ----------------------------------------------------------------------------
   El catálogo que decide, cuando se le escribe a un cliente por una alerta,
   qué documentación se le pide. Cada entrada tiene dos listas —una para
   personas y otra para empresas— porque a una sociedad no se le pide un
   comprobante de domicilio personal.

   ES EL ÚNICO LUGAR DONDE SE DEFINE. Si una alerta no está acá, el correo sale
   con la lista genérica: no falla, pero pide de más y de menos. Por eso la
   pantalla muestra cuántas alertas hay configuradas y no esconde las vacías.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { soloLectura } from '../../permisos.js';

/* Las categorías que el backend sabe pedir. Están acá porque no hay endpoint
   que las liste: son las que usan las plantillas de correo. */
export const CATEGORIAS = [
  'Identidad/Datos personales',
  'Domicilio',
  'Origen de fondo',
  'Comprobantes/Soporte',
  'Relación/Beneficiario',
  'Actividad económica',
];

const VACIA = { tipo_alerta: '', alerta: '', documentos_b2c: [], documentos_b2b: [] };

function Lista({ titulo, elegidos, alCambiar }) {
  return (
    <div>
      <h3 className="wt-subtitulo">{titulo}</h3>
      <div className="wt-checklist">
        {CATEGORIAS.map((c) => (
          <label key={c} className="wt-checklist-item" style={{ cursor: 'pointer' }}>
            <input type="checkbox" checked={elegidos.includes(c)}
                   onChange={(e) => alCambiar(
                     e.target.checked ? [...elegidos, c] : elegidos.filter((x) => x !== c))} />
            <span>{c}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

export function Documentos({ api, perfil }) {
  const [config, setConfig] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [editando, setEditando] = useState(null);
  const [guardando, setGuardando] = useState(false);

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/alert-document-config');
      setConfig(d?.config || []);
    } catch (e) {
      setError(e?.message || 'No se pudo leer la configuración.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  async function guardar() {
    if (!editando.alerta.trim()) { setError('Falta el nombre de la alerta.'); return; }
    setGuardando(true); setError(''); setAviso('');
    try {
      const cuerpo = {
        tipo_alerta: editando.tipo_alerta,
        alerta: editando.alerta.trim(),
        documentos_b2c: editando.documentos_b2c,
        documentos_b2b: editando.documentos_b2b,
      };
      // Crear y editar se distinguen por la RUTA, no por el método: el
      // backend acepta POST en las dos, y v2 no usa PUT en ninguna parte.
      if (editando.config_id) {
        await api.post(`/alert-document-config/${editando.config_id}`, cuerpo);
      } else {
        await api.post('/alert-document-config', cuerpo);
      }
      setAviso(`Configuración de «${cuerpo.alerta}» guardada.`);
      setEditando(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo guardar.');
    } finally {
      setGuardando(false);
    }
  }

  async function borrar(c) {
    if (!globalThis.confirm(`¿Borrar la configuración de «${c.alerta}»?\n\n`
      + 'Los correos de esa alerta van a pasar a pedir la lista genérica.')) return;
    setError(''); setAviso('');
    try {
      await api.del(`/alert-document-config/${c.config_id}`);
      setAviso(`Configuración de «${c.alerta}» borrada.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo borrar.');
    }
  }

  return (
    <>
      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {editando && (
        <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">
              {editando.config_id ? 'Editar' : 'Nueva configuración'}
            </h2>
          </header>
          <div className="wt-cuerpo-carta">
            <div className="wt-parametros">
              <label className="wt-parametro">
                <span>Tipo de alerta</span>
                <input className="wt-input" value={editando.tipo_alerta}
                       placeholder="AML Transaccional"
                       onChange={(e) => setEditando((x) => ({ ...x, tipo_alerta: e.target.value }))} />
              </label>
              <label className="wt-parametro">
                <span>Alerta</span>
                <input className="wt-input" value={editando.alerta}
                       placeholder="Transacciones a Países Alto Riesgo"
                       onChange={(e) => setEditando((x) => ({ ...x, alerta: e.target.value }))} />
              </label>
            </div>
            <div className="wt-dos-columnas" style={{ marginTop: 'var(--e-4)' }}>
              <Lista titulo="A una persona" elegidos={editando.documentos_b2c}
                     alCambiar={(v) => setEditando((x) => ({ ...x, documentos_b2c: v }))} />
              <Lista titulo="A una empresa" elegidos={editando.documentos_b2b}
                     alCambiar={(v) => setEditando((x) => ({ ...x, documentos_b2b: v }))} />
            </div>
            <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
              <button className="wt-btn wt-btn-primario" disabled={guardando} onClick={guardar}>
                {guardando ? 'Guardando…' : 'Guardar'}
              </button>
              <button className="wt-btn" onClick={() => setEditando(null)}>Cancelar</button>
            </div>
          </div>
        </section>
      )}

      <section className="wt-carta">
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">Documentos por alerta · {config.length}</h2>
          <div className="wt-carta-herramientas">
            {!lectura && !editando && (
              <button className="wt-btn wt-btn-primario"
                      onClick={() => setEditando({ ...VACIA })}>
                Nueva
              </button>
            )}
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </div>
        </header>
        <div className="wt-tabla-marco">
          <table className="wt-tabla">
            <thead>
              <tr><th>Tipo</th><th>Alerta</th><th>A personas</th><th>A empresas</th><th /></tr>
            </thead>
            <tbody>
              {cargando ? (
                <tr><td colSpan={5}>Cargando…</td></tr>
              ) : config.length === 0 ? (
                <tr><td colSpan={5}>Todavía no hay ninguna configurada.</td></tr>
              ) : config.map((c) => (
                <tr key={c.config_id}>
                  <td>{c.tipo_alerta || '—'}</td>
                  <td style={{ whiteSpace: 'normal' }}>{c.alerta}</td>
                  <td className="wt-td-num">{(c.documentos_b2c || []).length}</td>
                  <td className="wt-td-num">{(c.documentos_b2b || []).length}</td>
                  <td>
                    {!lectura && (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => setEditando({
                                  ...c,
                                  documentos_b2c: c.documentos_b2c || [],
                                  documentos_b2b: c.documentos_b2b || [],
                                })}>
                          Editar
                        </button>
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => borrar(c)}>
                          Borrar
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
