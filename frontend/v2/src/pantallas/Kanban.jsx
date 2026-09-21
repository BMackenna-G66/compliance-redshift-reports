/* ============================================================================
   Tablero de casos
   ----------------------------------------------------------------------------
   Las mismas columnas que los estados del backend. Arrastrar una tarjeta
   cambia el estado del caso — es una escritura de verdad, así que:

   · El perfil de sólo lectura no puede arrastrar (y la capa de API lo corta
     igual, aunque el atributo se lo salte alguien con las herramientas del
     navegador).
   · Mover a «Cerrado» pregunta. Cerrar es la única de las cuatro que cambia
     el sentido del caso y deja `closed_at`; las otras tres son etapas.
   · La tarjeta se mueve en pantalla ANTES de que el servidor conteste, y
     vuelve a su lugar si falla. Esperar un segundo por tarjeta haría el
     tablero inservible para ordenar 89 casos, pero dejarla movida cuando el
     guardado falló sería peor: diría que se hizo algo que no se hizo.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { InsigniaSla } from '../comun/InsigniaSla.jsx';
import { diasTexto, indicadores, porColumna } from '../comun/casos.js';
import { soloLectura } from '../permisos.js';

function Tarjeta({ caso, arrastrable, alAbrir, alArrastrar, arrastrando }) {
  return (
    <div
      className="wt-tarjeta"
      role="button"
      tabIndex={0}
      draggable={arrastrable}
      aria-grabbed={arrastrando ? 'true' : undefined}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', caso.case_id);
        alArrastrar(caso.case_id);
      }}
      onDragEnd={() => alArrastrar(null)}
      onClick={alAbrir}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alAbrir(); } }}
    >
      {/* El id manda: sólo 41 de 89 casos traen nombre, y el `title` es
          "Caso: Alerta: <reporte>" en 72 de ellos — se leería como el nombre
          del cliente sin identificar a nadie. */}
      <span className="wt-tarjeta-titulo mono">{caso.entity_id || caso.case_id}</span>
      {caso.entity_name && (
        <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-2)' }}>
          {caso.entity_name}
        </span>
      )}
      <InsigniaSla caso={caso} conDetalle={false} />
      <span className="wt-tarjeta-pie">
        <span>{diasTexto(caso.sla_dias)}</span>
        <span style={{ marginLeft: 'auto' }}>
          {caso.assigned_to
            ? caso.assigned_to.replace('@global66.com', '')
            : <span style={{ color: 'var(--nivel-alto-texto)' }}>sin asignar</span>}
        </span>
      </span>
    </div>
  );
}

export function Kanban({ api, perfil, navegar }) {
  const [casos, setCasos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [arrastrando, setArrastrando] = useState(null);
  const [sobre, setSobre] = useState(null);

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const d = await api.get('/cases?status=all');
      setCasos(d?.cases || []);
      if (d?.warning) setError(`La API respondió con un aviso: ${d.warning}`);
    } catch (e) {
      setError(e?.message || 'No se pudieron cargar los casos.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const columnas = useMemo(() => porColumna(casos), [casos]);
  const ind = useMemo(() => indicadores(casos), [casos]);

  async function mover(caseId, nuevoEstado) {
    const caso = casos.find((c) => c.case_id === caseId);
    if (!caso || caso.status === nuevoEstado) return;

    if (nuevoEstado === 'closed') {
      const ok = globalThis.confirm(
        `Cerrar el caso de ${caso.entity_name || caso.entity_id}. Queda registrada la fecha de cierre. ¿Seguro?`,
      );
      if (!ok) return;
    }

    const antes = casos;
    setCasos((l) => l.map((c) => (c.case_id === caseId ? { ...c, status: nuevoEstado } : c)));
    setError('');
    try {
      await api.post(`/cases/${caseId}/status`, { status: nuevoEstado });
      // Se recarga para traer el semáforo recalculado: cerrar un caso detiene
      // su reloj, y dejar el "Vencido" viejo en la tarjeta sería mentir.
      await cargar();
    } catch (e) {
      setCasos(antes);   // vuelve a su columna: no se guardó
      setError(e?.message || 'No se pudo cambiar el estado. La tarjeta volvió a su lugar.');
    }
  }

  return (
    <>
      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)', marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Tablero de casos
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          {cargando ? 'leyendo…' : `${ind.abiertos} abiertos · ${ind.vencidos} vencidos`}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 'var(--e-2)' }}>
          <button className="wt-btn" onClick={() => navegar('cases')}>Ver lista</button>
          <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
        </div>
      </div>

      {lectura && (
        <p className="wt-nota">
          Tu perfil es de consulta: podés ver el tablero, pero no mover tarjetas.
        </p>
      )}

      {cargando && casos.length === 0 ? (
        <p className="wt-estado">Cargando…</p>
      ) : (
        <div className="wt-kanban">
          {columnas.map((col) => (
            <section key={col.clave} className="wt-columna" style={{ borderTopColor: col.color }}>
              <header className="wt-columna-cabecera">
                {col.etiqueta}
                <span className="wt-columna-n">{col.items.length}</span>
              </header>
              <div
                className={'wt-columna-lista' + (sobre === col.clave ? ' wt-recibe' : '')}
                onDragOver={(e) => {
                  if (lectura || !arrastrando) return;
                  e.preventDefault();          // sin esto el navegador no deja soltar
                  e.dataTransfer.dropEffect = 'move';
                  setSobre(col.clave);
                }}
                onDragLeave={() => setSobre((s) => (s === col.clave ? null : s))}
                onDrop={(e) => {
                  e.preventDefault();
                  setSobre(null);
                  const id = e.dataTransfer.getData('text/plain');
                  setArrastrando(null);
                  if (!lectura && id) mover(id, col.clave);
                }}
              >
                {col.items.length === 0 && (
                  <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)',
                              textAlign: 'center', padding: 'var(--e-3) 0', margin: 0 }}>
                    vacía
                  </p>
                )}
                {col.items.map((c) => (
                  <Tarjeta
                    key={c.case_id}
                    caso={c}
                    arrastrable={!lectura}
                    arrastrando={arrastrando === c.case_id}
                    alArrastrar={setArrastrando}
                    alAbrir={() => navegar('caso', [c.case_id])}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
