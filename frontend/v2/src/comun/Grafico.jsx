/* ============================================================================
   Gráficos
   ----------------------------------------------------------------------------
   SVG a mano, sin librería. v1 usa Chart.js, que pesa ~200 kB para dibujar
   ocho barras y dos líneas — más que todas las pantallas de v2 juntas. Acá
   son unas cien líneas y quedan con los tokens del tema, se ven bien en
   oscuro y no hay que sincronizar una paleta aparte.

   LO QUE ESTOS GRÁFICOS NO HACEN, a propósito: no truncan el eje. Una barra
   que arranca en 90 en vez de en 0 hace que una diferencia del 2% parezca
   del 200%, y en una pantalla de compliance eso no es un detalle estético.
   ========================================================================= */

/** El máximo de una serie, con piso 1 para que una serie en cero no divida
 *  por cero ni dibuje barras de altura infinita. */
function techo(datos) {
  return Math.max(1, ...datos.map((d) => Number(d.valor) || 0));
}

function Vacio({ alto = 120, texto = 'Sin datos en el período' }) {
  return (
    <div style={{ height: alto, display: 'grid', placeItems: 'center',
                  color: 'var(--texto-mute)', fontSize: 'var(--texto-sm)' }}>
      {texto}
    </div>
  );
}

/* ── Barras horizontales ────────────────────────────────────────────────
   Para categorías con nombre largo —un reporte se llama
   `payin_payout_accumulation`—, que en vertical quedan ilegibles o
   rotadas. */
export function BarrasHorizontales({ datos, color = 'var(--g66-azul)', maxFilas = 8 }) {
  const d = (datos || []).slice(0, maxFilas);
  if (!d.length) return <Vacio />;
  const max = techo(d);
  const total = d.reduce((a, x) => a + (Number(x.valor) || 0), 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {d.map((f) => {
        const v = Number(f.valor) || 0;
        const pct = total ? Math.round((v / total) * 100) : 0;
        return (
          <div key={f.etiqueta} style={{ display: 'grid',
                                         gridTemplateColumns: '1fr 42px', gap: 8,
                                         alignItems: 'center' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-2)',
                            whiteSpace: 'nowrap', overflow: 'hidden',
                            textOverflow: 'ellipsis', marginBottom: 2 }}
                   title={`${f.etiqueta} · ${v} (${pct}%)`}>
                {f.etiqueta}
              </div>
              <div style={{ height: 7, background: 'var(--superficie-3)',
                            borderRadius: 'var(--r-pill)' }}>
                <div style={{ height: '100%', width: `${(v / max) * 100}%`,
                              background: f.esOtros ? 'var(--texto-mute)' : color,
                              borderRadius: 'var(--r-pill)' }} />
              </div>
            </div>
            <span style={{ fontSize: 'var(--texto-sm)', fontWeight: 'var(--peso-medio)',
                           textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                           color: 'var(--texto)' }}>
              {v.toLocaleString('es-CL')}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ── Barras verticales ──────────────────────────────────────────────────
   Para series temporales cortas: 8 semanas, 12 meses. */
export function Barras({ datos, color = 'var(--g66-azul)', alto = 130, etiqueta }) {
  const d = datos || [];
  if (!d.length) return <Vacio alto={alto} />;
  const max = techo(d);

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: alto }}>
      {d.map((p, i) => {
        const v = Number(p.valor) || 0;
        return (
          <div key={p.etiqueta} style={{ flex: 1, display: 'flex',
                                         flexDirection: 'column', alignItems: 'center',
                                         justifyContent: 'flex-end', height: '100%',
                                         minWidth: 0 }}
               title={`${p.etiqueta}: ${v}`}>
            <span style={{ fontSize: 9, color: 'var(--texto-mute)',
                           fontVariantNumeric: 'tabular-nums' }}>
              {v || ''}
            </span>
            {/* El eje arranca en cero SIEMPRE. */}
            <div style={{ width: '100%', height: `${(v / max) * 100}%`,
                          minHeight: v ? 2 : 0, background: color,
                          borderRadius: '3px 3px 0 0' }} />
            <span style={{ fontSize: 9, color: 'var(--texto-mute)', marginTop: 3,
                           whiteSpace: 'nowrap', overflow: 'hidden' }}>
              {/* Con muchas barras sólo se rotula una de cada tres: todas
                  juntas se pisan y no se lee ninguna. */}
              {d.length <= 10 || i % 3 === 0 ? (etiqueta ? etiqueta(p.etiqueta) : p.etiqueta) : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ── Línea ──────────────────────────────────────────────────────────────
   Para series de 30 días, donde una barra por día no entra. */
export function Linea({ datos, color = 'var(--g66-azul)', alto = 130, etiqueta }) {
  const d = datos || [];
  if (d.length < 2) return <Vacio alto={alto} />;
  const max = techo(d);
  const ancho = 100;   // viewBox relativo: el SVG escala al contenedor
  const paso = ancho / (d.length - 1);
  const y = (v) => alto - (Number(v) || 0) / max * (alto - 14) - 7;

  const puntos = d.map((p, i) => `${i * paso},${y(p.valor)}`).join(' ');
  const area = `0,${alto} ${puntos} ${ancho},${alto}`;

  return (
    <>
      <svg viewBox={`0 0 ${ancho} ${alto}`} preserveAspectRatio="none"
           style={{ width: '100%', height: alto, display: 'block' }}
           role="img" aria-label="Serie diaria">
        <polygon points={area} fill={color} opacity="0.12" />
        <polyline points={puntos} fill="none" stroke={color} strokeWidth="1.5"
                  vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 9, color: 'var(--texto-mute)', marginTop: 2 }}>
        <span>{etiqueta ? etiqueta(d[0].etiqueta) : d[0].etiqueta}</span>
        <span>
          máx {max.toLocaleString('es-CL')} · total{' '}
          {d.reduce((a, x) => a + (Number(x.valor) || 0), 0).toLocaleString('es-CL')}
        </span>
        <span>{etiqueta ? etiqueta(d.at(-1).etiqueta) : d.at(-1).etiqueta}</span>
      </div>
    </>
  );
}

/* ── Una tarjeta con título ─────────────────────────────────────────────── */
export function Panel({ titulo, pie, children }) {
  return (
    <section className="wt-carta">
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{titulo}</h2>
        {pie && (
          <span style={{ marginLeft: 'auto', fontSize: 'var(--texto-xs)',
                         color: 'var(--texto-mute)' }}>
            {pie}
          </span>
        )}
      </header>
      <div className="wt-cuerpo-carta">{children}</div>
    </section>
  );
}
