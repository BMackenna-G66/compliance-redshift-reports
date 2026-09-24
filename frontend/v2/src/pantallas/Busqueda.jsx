/* ============================================================================
   Búsqueda de entidad
   ----------------------------------------------------------------------------
   Un id de cliente, un nombre o el valor de una alerta, y devuelve todo lo
   que el sistema tiene sobre esa entidad: alertas, casos y eventos.

   PIDE TRES CARACTERES ANTES DE BUSCAR. No es capricho: la búsqueda recorre
   alertas y casos, y un solo dígito devuelve medio sistema con un costo que
   no le sirve a nadie.

   ABAJO, EL MANTENEDOR DE CUENTAS INTERNAS. Es otra pregunta y otra fuente:
   la de arriba mira lo que WatchTower guarda (alertas y casos); la de abajo
   va a Redshift a resolver de quién es una cuenta. Van juntas porque quien
   entra acá con un IBAN en la mano no sabe de antemano en cuál de las dos
   está la respuesta, y separarlas en dos pantallas obliga a adivinar.
   ========================================================================= */

import { useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { fecha, hace } from '../comun/alertas.js';
import {
  CAMPOS_CUENTA, COLUMNAS_CUENTA, FORMULARIO_VACIO,
  consulta, hayFiltro, resumenFiltros,
} from '../comun/cuentas.js';

const MINIMO = 3;

const COLUMNAS = (navegar) => [
  {
    clave: 'source_type',
    titulo: 'Qué es',
    ancho: '11%',
    render: (r) => ({ alert: 'Alerta', case: 'Caso' }[r.source_type] || r.source_type || '—'),
  },
  { clave: 'entity_value', titulo: 'Entidad', tipo: 'mono', ancho: '14%' },
  {
    clave: 'detail',
    titulo: 'Detalle',
    render: (r) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 400 }}>
        {r.detail || '—'}
      </span>
    ),
  },
  { clave: 'report_name', titulo: 'Reporte', tipo: 'mono', ancho: '18%' },
  { clave: 'status', titulo: 'Estado', ancho: '10%' },
  {
    clave: 'event_date',
    titulo: 'Cuándo',
    ancho: '11%',
    buscable: false,
    render: (r) => (
      <span title={fecha(r.event_date)?.toLocaleString('es-CL') || r.event_date}>
        {hace(r.event_date)}
      </span>
    ),
  },
  {
    clave: 'source_id',
    titulo: '',
    ancho: '8%',
    ordenable: false,
    buscable: false,
    render: (r) => (r.source_type === 'case'
      ? <button className="wt-btn" style={{ padding: '2px 8px' }}
                onClick={() => navegar('caso', [r.source_id])}>Abrir</button>
      : r.source_type === 'alert'
        ? <button className="wt-btn" style={{ padding: '2px 8px' }}
                  onClick={() => navegar('alert', [r.source_id])}>Abrir</button>
        : null),
    exportar: () => '',
  },
];

/* ── El mantenedor de cuentas internas ─────────────────────────────────── */

function Cuentas({ api }) {
  const [form, setForm] = useState(FORMULARIO_VACIO);
  const [datos, setDatos] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState('');

  const listo = hayFiltro(form);

  async function buscar(e) {
    e.preventDefault();
    if (!listo) return;
    setBuscando(true); setError(''); setDatos(null);
    try {
      setDatos(await api.get(consulta(form)));
    } catch (err) {
      /* No se deja la tabla anterior en pantalla: una tabla vieja bajo unos
         filtros nuevos es la forma más fácil de leer mal el resultado. */
      setError(err?.message || 'No se pudo consultar. Puede que el clúster esté pausado.');
    } finally {
      setBuscando(false);
    }
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    margin: 'var(--e-5) 0 var(--e-4)' }}>
        <h2 style={{ margin: 0, fontSize: 'var(--texto-base)',
                     color: 'var(--g66-navy-texto)' }}>
          Cuentas internas
        </h2>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          de quién es una cuenta, y en qué moneda e instancia vive
        </span>
      </div>

      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
        <form className="wt-cuerpo-carta" onSubmit={buscar}>
          <div className="wt-parametros">
            {CAMPOS_CUENTA.map((c) => (
              <label className="wt-parametro" key={c.clave}>
                <span>{c.etiqueta}</span>
                <input
                  className="wt-input" value={form[c.clave]} placeholder={c.ejemplo}
                  onChange={(e) => setForm((f) => ({ ...f, [c.clave]: e.target.value }))}
                />
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center',
                        marginTop: 'var(--e-3)' }}>
            <button className="wt-btn wt-btn-primario" type="submit"
                    disabled={buscando || !listo}>
              {buscando ? 'Consultando…' : 'Consultar'}
            </button>
            <button className="wt-btn" type="button"
                    onClick={() => { setForm(FORMULARIO_VACIO); setDatos(null); setError(''); }}>
              Limpiar
            </button>
            <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              {listo
                ? 'Se combinan con Y: se devuelve lo que cumple todos los campos escritos.'
                : 'Completá al menos un campo. Sin filtros esto recorre la tabla entera.'}
            </span>
          </div>
        </form>
      </section>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {datos && (
        <>
          <p className="wt-nota">
            <strong>{datos.count ?? 0}</strong> cuenta{datos.count === 1 ? '' : 's'}
            {' · '}{resumenFiltros(datos.filters)}
            {/* Que cortó se dice acá y no en un log: alguien puede estar por
                concluir que un cliente tiene 200 cuentas y son más. */}
            {datos.truncated && (
              <> · <strong>hay más</strong>: se muestran las {datos.limit} más
                recientes por fecha de modificación.</>
            )}
          </p>
          <Tabla
            titulo="Cuentas internas"
            columnas={COLUMNAS_CUENTA}
            filas={datos.rows || []}
            claveFila={(x, i) => `${x.cuenta}-${x.moneda}-${i}`}
            nombreExport="cuentas-internas"
            vacioTexto="Ninguna cuenta cumple esos filtros."
          />
        </>
      )}
    </>
  );
}

export function Busqueda({ api, navegar }) {
  const [q, setQ] = useState('');
  const [datos, setDatos] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState('');

  async function buscar(e) {
    e.preventDefault();
    const texto = q.trim();
    if (texto.length < MINIMO) return;
    setBuscando(true); setError(''); setDatos(null);
    try {
      setDatos(await api.get(`/search/entity?q=${encodeURIComponent(texto)}`));
    } catch (err) {
      setError(err?.message || 'No se pudo buscar.');
    } finally {
      setBuscando(false);
    }
  }

  const r = datos?.results || [];

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--e-3)',
                    marginBottom: 'var(--e-4)' }}>
        <h1 style={{ margin: 0, fontSize: 'var(--texto-lg)', color: 'var(--g66-navy-texto)' }}>
          Búsqueda
        </h1>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          alertas y casos de una entidad
        </span>
      </div>

      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)', maxWidth: 720 }}>
        <form className="wt-cuerpo-carta" onSubmit={buscar}
              style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center' }}>
          <input className="wt-input" style={{ flex: 1 }} value={q}
                 onChange={(e) => setQ(e.target.value)}
                 placeholder="Id de cliente, nombre o valor de la alerta"
                 aria-label="Qué buscar" />
          <button className="wt-btn wt-btn-primario" type="submit"
                  disabled={buscando || q.trim().length < MINIMO}>
            {buscando ? 'Buscando…' : 'Buscar'}
          </button>
        </form>
        {q.trim().length > 0 && q.trim().length < MINIMO && (
          <p style={{ margin: '0 var(--e-4) var(--e-3)', fontSize: 'var(--texto-sm)',
                      color: 'var(--texto-mute)' }}>
            Escribí al menos {MINIMO} caracteres: con menos, la búsqueda devuelve medio
            sistema.
          </p>
        )}
      </section>

      {error && <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)' }}>{error}</div>}

      {datos && (
        <>
          <p className="wt-nota">
            <strong>{r.length}</strong> resultado{r.length === 1 ? '' : 's'} para{' '}
            <span className="mono">{datos.query}</span>
            {' · '}{datos.alert_count ?? 0} alerta{datos.alert_count === 1 ? '' : 's'}
            {' y '}{datos.case_count ?? 0} caso{datos.case_count === 1 ? '' : 's'}
          </p>
          <Tabla
            titulo="Resultados"
            columnas={COLUMNAS(navegar)}
            filas={r}
            claveFila={(x, i) => `${x.source_type}-${x.source_id}-${i}`}
            nombreExport={`busqueda-${datos.query}`}
            buscable={false}
            vacioTexto="No se encontró nada con ese texto."
          />
        </>
      )}

      <Cuentas api={api} />
    </>
  );
}
