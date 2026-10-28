/* ============================================================================
   Lista blanca
   ----------------------------------------------------------------------------
   Los clientes que dejan de generar alertas, por cuánto tiempo y por qué.

   LO PIDE UNO Y LO FIRMA OTRO. Una entrada nace pendiente y NO silencia
   nada hasta que un Oficial de Cumplimiento la aprueba. Antes no era así:
   apretar el botón apagaba las alertas del cliente en el acto, y había
   clientes silenciados en todos los reportes sin que nadie lo hubiera
   firmado.

   LA VIGENCIA ES EL DATO, NO UN ADORNO. Una entrada en lista blanca apaga las
   alertas de ese cliente: si está vencida, el cliente volvió a la bandeja sin
   que nadie lo anuncie. Por eso la vigencia se calcula contra la hora real,
   se muestra en su propia columna y hay un aviso cuando falta menos de una
   semana — para que nadie se sorprenda de verlo reaparecer.
   ========================================================================= */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Tabla } from '../comun/Tabla.jsx';
import { Kpi } from '../comun/Kpi.jsx';
import {
  COLOR_VIGENCIA, estadoWhitelist, fecha, puedeAprobarWhitelist, quienPidio,
  resumenListaBlanca, vigenciaDe,
} from '../comun/analisis.js';
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

function Estado({ entrada }) {
  const e = estadoWhitelist(entrada);
  const quien = entrada?.aprobada_por || entrada?.solicitado_por || '';
  return (
    <span className="wt-insignia" style={{ color: e.color, background: e.fondo }}
          title={entrada?.estado === 'aprobada' && entrada?.aprobada_por
            ? `Aprobada por ${entrada.aprobada_por} el ${entrada.aprobada_en || '—'}`
            : entrada?.estado === 'pendiente'
            ? `Pedida por ${quien || 'alguien'}. El cliente SIGUE alertando hasta que se apruebe.`
            : entrada?.estado === 'heredada'
              ? 'Anterior al control de aprobación: sigue vigente hasta que venza.'
              : 'Llegó por un camino que no pasó por el control. NO silencia nada: hay que averiguar de dónde salió.'}>
      {e.etiqueta}
    </span>
  );
}

function columnas(alQuitar, lectura, quitando, alAprobar, alRechazar, email, soyOficial, firmando) {
  const cols = [
    { clave: 'entity_value', titulo: 'Cliente', tipo: 'mono', ancho: '14%' },
    {
      clave: 'estado',
      titulo: 'Estado',
      ancho: '13%',
      render: (w) => <Estado entrada={w} />,
      exportar: (w) => estadoWhitelist(w).etiqueta,
    },
    { clave: 'entity_field', titulo: 'Campo', ancho: '12%' },
    {
      clave: 'created_by',
      titulo: 'Quién la pidió',
      ancho: '16%',
      // Las entradas anteriores a octubre de 2026 no tienen autor: el backend
      // recibía el dato y lo descartaba. Se muestra el hueco en vez de
      // esconderlo — «—» dice que no se sabe, que es la verdad.
      //
      // Y desde dónde: un alta por API la pide una persona pero la manda un
      // sistema. Sin la insignia, la columna diría el correo de la analista y
      // nadie sabría que no pasó por la pantalla.
      render: (w) => {
        const q = quienPidio(w);
        if (!q.correo && !q.origen) return <span style={{ color: 'var(--texto-mute)' }}>—</span>;
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span title={q.correo}>{q.nombre || '—'}</span>
            {q.porApi && (
              <span className="wt-insignia"
                    title={`Pedida desde ${q.sistema} por la API, no desde la pantalla`}
                    style={{ color: 'var(--g66-azul-texto)', background: 'var(--azul-tenue)' }}>
                {q.sistema}
              </span>
            )}
          </span>
        );
      },
      exportar: (w) => {
        const q = quienPidio(w);
        return q.origen ? `${q.correo} (${q.origen})` : q.correo;
      },
    },
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
      ancho: '14%',
      ordenable: false,
      buscable: false,
      render: (w) => {
        const ocupado = firmando === w.whitelist_id;
        if (w.estado === 'pendiente') {
          // El botón apagado lleva el motivo en el `title`: uno gris y mudo
          // hace que la gente apriete tres veces y después pregunte por chat.
          const { puede, motivo } = puedeAprobarWhitelist(w, email, soyOficial);
          return (
            <span style={{ display: 'inline-flex', gap: 4 }}>
              <button className="wt-btn wt-btn-primario" style={{ padding: '2px 8px' }}
                      disabled={!puede || ocupado} title={motivo}
                      onClick={() => alAprobar(w)}>
                {ocupado ? '…' : 'Aprobar'}
              </button>
              <button className="wt-btn" style={{ padding: '2px 8px' }}
                      disabled={!puede || ocupado} title={motivo}
                      onClick={() => alRechazar(w)}>
                Rechazar
              </button>
            </span>
          );
        }
        return (
          <button className="wt-btn" style={{ padding: '2px 8px' }}
                  disabled={quitando === w.whitelist_id}
                  onClick={() => alQuitar(w)}>
            {quitando === w.whitelist_id ? '…' : 'Quitar'}
          </button>
        );
      },
      exportar: () => '',
    });
  }
  return cols;
}

function Agregar({ onAgregar, guardando, email }) {
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
      // Quién lo agregó. El alta desde el caso ya lo manda y ésta no, así
      // que las entradas de esta pantalla quedaban sin autor y no se
      // podía saber quién silenció a ese cliente.
      created_by: email || '',
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

export function ListaBlanca({ api, perfil, email }) {
  const [entradas, setEntradas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [quitando, setQuitando] = useState('');
  const [masiva, setMasiva] = useState(null);
  const [soyOficial, setSoyOficial] = useState(false);
  const [firmando, setFirmando] = useState('');

  const lectura = soloLectura(perfil);

  const cargar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const d = await api.get('/whitelist');
      setEntradas(d?.whitelist || []);
      // El padrón no llega al navegador: llega la respuesta a «¿éste que
      // mira puede firmar?». Ver get_whitelist en el backend.
      setSoyOficial(Boolean(d?.soy_oficial));
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
      // NO dice «agregado»: no silencia nada todavía. Decir que ya está sería
      // el error caro — alguien cierra el caso creyendo que el cliente dejó
      // de alertar y nadie firma nunca.
      setAviso(`Pedido para ${datos.entity_value}, por ${datos.duration_days} días. `
        + 'Queda PENDIENTE: el cliente sigue alertando hasta que lo apruebe un '
        + 'Oficial de Cumplimiento.');
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo agregar.');
    } finally {
      setGuardando(false);
    }
  }

  /**
   * Alta masiva: se pegan los identificadores y entran todos juntos.
   *
   * Es la acción más silenciosa de la aplicación: cada línea acá deja de
   * generar alertas para siempre —la whitelist perdona TODO, sanciones y
   * delitos sensibles incluidos— y no hay nada en pantalla que lo recuerde
   * después. Por eso la confirmación dice cuántos son, y el motivo es
   * obligatorio: es lo único que va a quedar escrito.
   */
  async function agregarMasiva() {
    const ids = String(masiva.ids || '').split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    if (ids.length === 0) { setError('Pegá al menos un identificador.'); return; }
    if (!masiva.reason.trim()) { setError('El motivo es obligatorio: es lo único que queda escrito.'); return; }
    const ok = globalThis.confirm(
      `Se van a PEDIR ${ids.length} cliente(s) para la lista blanca, por `
      + `${masiva.duration_days} días.\n\n`
      + 'Todavía no silencian nada: cada uno lo tiene que aprobar un Oficial de '
      + 'Cumplimiento. Una vez aprobados, NO generan ninguna alerta — ni de '
      + 'sanciones ni de delitos sensibles.\n\n¿Confirmás?');
    if (!ok) return;
    setGuardando(true); setError(''); setAviso('');
    try {
      const d = await api.post('/whitelist/bulk', {
        rows: ids.map((v) => ({ entity_field: masiva.entity_field, entity_value: v })),
        entity_field: masiva.entity_field,
        duration_days: Number(masiva.duration_days),
        reason: masiva.reason.trim(),
        scope: masiva.scope,
      });
      if (d?.error) throw new Error(d.error);
      setAviso(`Pedidos ${d?.added ?? ids.length} de ${ids.length}. Quedan PENDIENTES: `
        + 'estos clientes siguen alertando hasta que un Oficial de Cumplimiento '
        + 'los apruebe uno por uno.');
      setMasiva(null);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo hacer el alta masiva.');
    } finally {
      setGuardando(false);
    }
  }

  async function firmar(w, accion) {
    // La confirmación dice qué cambia en el mundo, no qué botón se apretó.
    const texto = accion === 'aprobar'
      ? `Aprobar que ${w.entity_value} deje de alertar por ${w.duration_days} días.\n\n`
        + 'Desde ahora no aparece en los reportes: ni sanciones ni delitos '
        + 'sensibles.\n\n¿Confirmás?'
      : `Rechazar el pedido para ${w.entity_value}.\n\nEl cliente sigue alertando.`;
    let motivo = '';
    if (accion === 'rechazar') {
      motivo = globalThis.prompt(`${texto}\n\n¿Por qué? (lo lee quien lo pidió)`) || '';
      if (!motivo.trim()) return;
    } else if (!globalThis.confirm(texto)) {
      return;
    }
    setFirmando(w.whitelist_id); setError(''); setAviso('');
    try {
      const d = await api.post(`/whitelist/${w.whitelist_id}/${accion}`,
        accion === 'rechazar' ? { motivo: motivo.trim() } : {});
      if (d?.error) throw new Error([d.error, ...(d.motivos || [])].join(' '));
      setAviso(accion === 'aprobar'
        ? `${w.entity_value} aprobado: deja de alertar hasta el ${d?.expires_at || '—'}.`
        : `Pedido para ${w.entity_value} rechazado. El cliente sigue alertando.`);
      await cargar();
    } catch (e) {
      setError(e?.message || 'No se pudo firmar.');
    } finally {
      setFirmando('');
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

      {!lectura && <Agregar onAgregar={agregar} guardando={guardando} email={email} />}

      {masiva && (
        <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
          <header className="wt-carta-cabecera">
            <h2 className="wt-carta-titulo">Alta masiva</h2>
            <div className="wt-carta-herramientas">
              <button className="wt-btn" onClick={() => setMasiva(null)}>Cerrar</button>
            </div>
          </header>
          <div className="wt-cuerpo-carta">
            <p className="wt-nota wt-nota-alarma">
              Mientras un cliente esté en la lista blanca <strong>no genera ninguna
              alerta</strong>: tampoco las de sanciones ni las de delitos sensibles. El
              motivo que escribas es lo único que va a quedar explicando por qué.
            </p>
            <label className="wt-parametro">
              <span>Identificadores</span>
              <textarea className="wt-input" style={{ width: '100%', minHeight: 100, resize: 'vertical' }}
                        value={masiva.ids}
                        onChange={(e) => setMasiva((m) => ({ ...m, ids: e.target.value }))}
                        placeholder="Coma, espacio o salto de línea" />
            </label>
            <div className="wt-parametros" style={{ marginTop: 'var(--e-3)' }}>
              <label className="wt-parametro">
                <span>Tipo</span>
                <select className="wt-input" value={masiva.entity_field}
                        onChange={(e) => setMasiva((m) => ({ ...m, entity_field: e.target.value }))}>
                  <option value="customer_id">Personas</option>
                  <option value="company_id">Empresas</option>
                </select>
              </label>
              <label className="wt-parametro">
                <span>Por cuánto</span>
                <select className="wt-input" value={masiva.duration_days}
                        onChange={(e) => setMasiva((m) => ({
                          ...m, duration_days: Number(e.target.value) }))}>
                  <option value={30}>30 días</option><option value={60}>60 días</option>
                  <option value={90}>90 días</option>
                </select>
              </label>
              <label className="wt-parametro">
                <span>Alcance</span>
                <select className="wt-input" value={masiva.scope}
                        onChange={(e) => setMasiva((m) => ({ ...m, scope: e.target.value }))}>
                  <option value="global">Todas las alertas</option>
                  <option value="report">Sólo un reporte</option>
                </select>
              </label>
            </div>
            <label className="wt-parametro" style={{ marginTop: 'var(--e-3)' }}>
              <span>Motivo (obligatorio)</span>
              <input className="wt-input" value={masiva.reason}
                     onChange={(e) => setMasiva((m) => ({ ...m, reason: e.target.value }))}
                     placeholder="Por qué se les perdona el alertamiento" />
            </label>
            <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
              <button className="wt-btn wt-btn-primario" disabled={guardando}
                      onClick={agregarMasiva}>
                {guardando ? 'Pidiendo…' : 'Pedir para todos'}
              </button>
              <button className="wt-btn" onClick={() => setMasiva(null)}>Cancelar</button>
            </div>
          </div>
        </section>
      )}

      <Tabla
        titulo="Lista blanca"
        columnas={columnas(quitar, lectura, quitando,
          (w) => firmar(w, 'aprobar'), (w) => firmar(w, 'rechazar'),
          email, soyOficial, firmando)}
        filas={preparadas}
        cargando={cargando}
        error={error}
        alReintentar={cargar}
        claveFila={(w) => w.whitelist_id}
        nombreExport="lista-blanca-watchtower"
        vacioTexto="No hay nadie en la lista blanca."
        herramientas={
          <>
            {!lectura && !masiva && (
              <button className="wt-btn" onClick={() => setMasiva({
                ids: '', entity_field: 'customer_id', duration_days: 90,
                reason: '', scope: 'global',
              })}>
                Alta masiva
              </button>
            )}
            <button className="wt-btn" onClick={cargar} disabled={cargando}>Refrescar</button>
          </>
        }
      />
    </>
  );
}
