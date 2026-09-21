/* ============================================================================
   Lista blanca
   ----------------------------------------------------------------------------
   Los clientes que dejan de generar alertas, por cuánto tiempo y por qué.

   LA VIGENCIA ES EL DATO, NO UN ADORNO. Una entrada en lista blanca apaga las
   alertas de ese cliente: si está vencida, el cliente volvió a la bandeja sin
   que nadie lo anuncie. Por eso la vigencia se calcula contra la hora real,
   se muestra en su propia columna y hay un aviso cuando falta menos de una
   semana — para que nadie se sorprenda de verlo reaparecer.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import { COLOR_VIGENCIA, fecha, resumenListaBlanca, vigenciaDe } from '../comun/analisis.js';
import { soloLectura } from '../permisos.js';

function Vigencia({ entrada }) {
  const v = vigenciaDe(entrada);
  const c = COLOR_VIGENCIA[v.estado];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="wt-insignia" style={{ color: c.color, background: c.fondo }}>
        {v.etiqueta}
      </span>
      {v.vence && (
        <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}
              title={v.vence.toLocaleString('es-CL')}>
          {v.dias >= 0 ? `en ${Math.ceil(v.dias)} d` : `hace ${Math.ceil(-v.dias)} d`}
        </span>
      )}
    </span>
  );
}

function columnas(alQuitar, lectura, quitando) {
  const cols = [
    { clave: 'entity_value', titulo: 'Cliente', tipo: 'mono', ancho: '14%' },
    { clave: 'entity_field', titulo: 'Campo', ancho: '12%' },
    {
      clave: '_vigencia',
      titulo: 'Vigencia',
      ancho: '16%',
      buscable: false,
      render: (w) => <Vigencia entrada={w} />,
    },
    {
      clave: 'scope',
      titulo: 'Alcance',
      ancho: '14%',
      // `global` apaga las alertas de todos los reportes; `report` sólo las de
      // uno. La diferencia es grande y el nombre crudo no la dice.
      render: (w) => (w.scope === 'global'
        ? <span title="No genera alertas en ningún reporte">Todos los reportes</span>
        : <span title={`Sólo el reporte ${w.report_name || '(sin especificar)'}`}>
            Sólo <span className="mono">{w.report_name || '—'}</span>
          </span>),
      exportar: (w) => (w.scope === 'global' ? 'Todos los reportes' : `Sólo ${w.report_name}`),
    },
    { clave: 'reason', titulo: 'Motivo', render: (w) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 320 }}>
        {w.reason || <span style={{ color: 'var(--texto-mute)' }}>sin motivo anotado</span>}
      </span>
    ) },
    {
      clave: 'created_at',
      titulo: 'Agregada',
      ancho: '11%',
      buscable: false,
      render: (w) => fecha(w.created_at)?.toLocaleDateString('es-CL') || '—',
    },
  ];
  if (!lectura) {
    cols.push({
      clave: 'whitelist_id',
      titulo: '',
      ancho: '8%',
      ordenable: false,
      buscable: false,
      render: (w) => (
        <button className="wt-btn" style={{ padding: '2px 8px' }}
                disabled={quitando === w.whitelist_id}
                onClick={() => alQuitar(w)}>
          {quitando === w.whitelist_id ? '…' : 'Quitar'}
        </button>
      ),
      exportar: () => '',
    });
  }
  return cols;
}

function Agregar({ onAgregar, guardando }) {
  const [valor, setValor] = useState('');
  const [dias, setDias] = useState('90');
  const [motivo, setMotivo] = useState('');

  function enviar(e) {
    e.preventDefault();
    if (!valor.trim() || !motivo.trim()) return;
    onAgregar({
      entity_field: 'customer_id',
      entity_value: valor.trim(),
      duration_days: Number(dias) || 90,
      reason: motivo.trim(),
      scope: 'global',
    });
    setValor(''); setMotivo('');
  }

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Agregar un cliente</h2>
      </header>
      <form className="wt-cuerpo-carta"
            style={{ display: 'flex', gap: 'var(--e-3)', alignItems: 'flex-end', flexWrap: 'wrap' }}
            onSubmit={enviar}>
        <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Id del cliente
          <input className="wt-input" style={{ display: 'block', marginTop: 4, width: 150 }}
                 value={valor} onChange={(e) => setValor(e.target.value)} required />
        </label>
        <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Por cuántos días
          <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 120 }}
                  value={dias} onChange={(e) => setDias(e.target.value)}>
            <option value="30">30</option>
            <option value="60">60</option>
            <option value="90">90</option>
            <option value="180">180</option>
          </select>
        </label>
        <label style={{ flex: 1, minWidth: 220, fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Motivo
          {/* Obligatorio a propósito: dentro de tres meses, cuando la entrada
              esté por vencer, esta línea es lo único que explica por qué se
              dejó de mirar a este cliente. */}
          <input className="wt-input" style={{ display: 'block', marginTop: 4, width: '100%' }}
                 value={motivo} onChange={(e) => setMotivo(e.target.value)}
                 placeholder="Por qué deja de generar alertas" required />
        </label>
        <button className="wt-btn wt-btn-primario" type="submit" disabled={guardando}>
          {guardando ? 'Agregando…' : 'Agregar'}
        </button>
      </form>
    </section>
  );
}

export function ListaBlanca({ api, perfil }) {
  const [entradas, setEntradas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [quitando, setQuitando] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/whitelist');
      setEntradas(d?.whitelist || []);
    } catch (e) {
      setError(e?.message || 'No se pudo cargar la lista blanca.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  const resumen = useMemo(() => resumenListaBlanca(entradas), [entradas]);
  const preparadas = useMemo(
    () => entradas.map((w) => ({ ...w, _vigencia: vigenciaDe(w).etiqueta })),
    [entradas],
  );

  async function agregar(datos) {
    setGuardando(true); setError(''); setAviso('');
    try {
      await api.post('/whitelist', datos);
      setAviso(`Cliente ${datos.entity_value} agregado por ${datos.duration_days} días.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo agregar.');
    } finally {
      setGuardando(false);
    }
  }

  async function quitar(w) {
    // Quitarlo lo devuelve a la bandeja: puede reaparecer con alertas de golpe.
    const ok = globalThis.confirm(
      `Quitar a ${w.entity_value} de la lista blanca. Vuelve a generar alertas. ¿Seguro?`,
    );
    if (!ok) return;
    setQuitando(w.whitelist_id); setError(''); setAviso('');
    try {
      await api.del(`/whitelist/${w.whitelist_id}`);
      setAviso(`Cliente ${w.entity_value} quitado de la lista.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo quitar.');
    } finally {
      setQuitando('');
    }
  }

  const sinDatos = (cargando || Boolean(error)) && entradas.length === 0;
  const n = (v) => (sinDatos ? '—' : v);

  return (
    <>
      <div className="wt-kpis">
        <Kpi principal etiqueta="En lista blanca" valor={n(resumen.total)}
             pie={sinDatos ? (cargando ? 'leyendo…' : 'no se pudieron leer') : 'no generan alertas'} />
        <Kpi etiqueta="Vigentes" valor={n(resumen.vigente)} pie="con plazo por delante" />
        <Kpi etiqueta="Por vencer" valor={n(resumen.por_vencer)} pie="en menos de 7 días" />
        <Kpi etiqueta="Vencidas" valor={n(resumen.vencida)} pie="ya volvieron a la bandeja" />
        <Kpi etiqueta="Permanentes" valor={n(resumen.permanente)} pie="sin fecha de fin" />
      </div>

      {resumen.por_vencer > 0 && (
        <p className="wt-nota">
          <strong>{resumen.por_vencer} entrada{resumen.por_vencer === 1 ? '' : 's'} vence
          {resumen.por_vencer === 1 ? '' : 'n'} esta semana.</strong>{' '}
          Cuando venzan, esos clientes vuelven a generar alertas.
        </p>
      )}

      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {!lectura && <Agregar onAgregar={agregar} guardando={guardando} />}

      <Tabla
        titulo="Lista blanca"
        columnas={columnas(quitar, lectura, quitando)}
        filas={preparadas}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(w) => w.whitelist_id}
        nombreExport="lista-blanca-watchtower"
        vacioTexto="No hay nadie en la lista blanca."
        herramientas={
          <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
        }
      />
    </>
  );
}
