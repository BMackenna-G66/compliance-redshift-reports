/* ============================================================================
   Detalle del caso
   ----------------------------------------------------------------------------
   POR QUÉ SE PIDEN DOS COSAS AL CARGAR. `GET /cases/{id}` devuelve el caso con
   sus notas, sus alertas y sus adjuntos, pero NO los campos `sla_*`: el
   semáforo se calcula en `GET /cases`, sobre la lista. Así que se piden las
   dos y se juntan.

   La alternativa era recalcular el plazo acá, y eso es justo lo que no se
   hace: la regla es de compliance y tener dos definiciones del mismo plazo
   termina en una pantalla que dice «en plazo» sobre un caso que el sistema
   considera vencido.

   LO QUE SE PIDE SOLO Y LO QUE NO. Los correos y la ficha KYC se traen a
   pedido. El correo es una consulta pesada y la ficha le pega al cluster de
   Redshift —que está apagado de 18:30 a 04:00—, así que cargarlas al abrir
   haría lento cada caso para algo que no siempre se mira.
   ========================================================================= */

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Campos } from '../comun/Campos.jsx';
import { Correos } from '../comun/Correos.jsx';
import { InsigniaSla } from '../comun/InsigniaSla.jsx';
import { comoFila, fecha, hace } from '../comun/alertas.js';
import { diasTexto, sinContactar } from '../comun/casos.js';
import {
  DURACIONES_WHITELIST, ESTADOS_DOCUMENTO, MAX_TOKENS_IA, TEMPERATURA_IA,
  altaDeWhitelist, campos, contextoDelCliente, estadoDocumento, notaDeWhitelist,
  promptDelCaso, repartirAdjuntos, resumenChecklist, resumenCorreos,
  siguienteEstadoDocumento, vinoPorCorreo,
} from '../comun/expediente.js';
import { ESTADOS_CASO } from '../dominio.js';
import { esAdmin, soloLectura } from '../permisos.js';

/* El panel del correo se carga al abrirlo: trae el catálogo de plantillas y
   la previsualización, y la mayoría de las visitas al caso no lo usan. */
const PedirDocumentos = lazy(() =>
  import('./caso/PedirDocumentos.jsx').then((m) => ({ default: m.PedirDocumentos })));

const ESTADOS_ELEGIBLES = ['open', 'in_progress', 'under_review', 'closed'];

function Dato({ etiqueta, children }) {
  return (<><dt>{etiqueta}</dt><dd>{children}</dd></>);
}

function Carta({ titulo, cuenta, herramientas, children }) {
  return (
    <section className="wt-carta">
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{titulo}</h2>
        {cuenta !== undefined && (
          <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>{cuenta}</span>
        )}
        {herramientas && <div className="wt-carta-herramientas">{herramientas}</div>}
      </header>
      <div className="wt-cuerpo-carta">{children}</div>
    </section>
  );
}

export function Caso({ api, perfil, email, id: casoId, navegar }) {
  const [caso, setCaso] = useState(null);
  const [notas, setNotas] = useState([]);
  const [alertas, setAlertas] = useState([]);
  const [adjuntos, setAdjuntos] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState('');
  const [nota, setNota] = useState('');

  /* Lo que se trae a pedido. */
  const [perfilCliente, setPerfilCliente] = useState(null);
  const [perfilCuando, setPerfilCuando] = useState('');
  const [perfilAbierto, setPerfilAbierto] = useState(false);
  const [correos, setCorreos] = useState(null);
  const [ia, setIa] = useState('');
  const [pidiendo, setPidiendo] = useState(false);

  /* La whitelist que nace al cerrar el caso. */
  const [wl, setWl] = useState({ abierta: false, dias: 30, alcance: 'global', motivo: '' });

  /* Los adjuntos. */
  const [subida, setSubida] = useState({ activa: false, hecho: 0, total: 0 });
  const [arrastrando, setArrastrando] = useState(false);
  const archivoRef = useRef(null);

  const lectura = soloLectura(perfil);
  const administra = esAdmin(perfil);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const [detalle, lista] = await Promise.all([
        api.get(`/cases/${casoId}`),
        // Sólo por los campos del semáforo. Si esta falla, el caso igual se
        // muestra: se pierde el plazo, no la pantalla entera.
        api.get('/cases?status=all').catch(() => null),
      ]);
      const delListado = (lista?.cases || []).find((c) => c.case_id === casoId) || {};
      const completo = { ...delListado, ...(detalle?.case || {}), ...slaDe(delListado) };
      setCaso(completo);
      setNotas(detalle?.notes || []);
      setAlertas(detalle?.alerts || []);
      setAdjuntos(detalle?.case?.attachments || []);
      // La ficha KYC la cuelga el backend del propio caso cuando ya se pidió
      // alguna vez: se consulta una sola vez y queda guardada.
      if (completo.client_profile) {
        setPerfilCliente(completo.client_profile);
        setPerfilCuando(completo.client_profile_at || '');
      }
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el caso.');
      setCaso(null);
    } finally {
      setCargando(false);
    }
  }, [api, casoId]);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    let vivo = true;
    api.get('/crm/users').then((d) => { if (vivo) setUsuarios(d?.users || []); }).catch(() => {});
    return () => { vivo = false; };
  }, [api]);

  const estado = useMemo(() => ESTADOS_CASO[caso?.status], [caso]);
  const camposPerfil = useMemo(() => campos(perfilCliente), [perfilCliente]);
  /* `alert_data` puede estar guardado como texto JSON: así lo manda el
     backend en las alertas, y así quedó en los casos que v2 creó antes de
     normalizarlo. Se parsea al leer para que esos casos también muestren su
     evidencia. */
  const camposAlerta = useMemo(() => campos(comoFila(caso?.alert_data)), [caso]);
  const checklist = caso?.documentos_checklist || [];
  const resumenDocs = useMemo(() => resumenChecklist(checklist), [checklist]);
  const bandeja = useMemo(() => resumenCorreos(correos), [correos]);

  async function accion(nombre, fn, mensaje) {
    setGuardando(nombre); setAviso(''); setError('');
    try {
      const r = await fn();
      if (mensaje) setAviso(mensaje);
      return r;
    } catch (e) {
      setError(e?.message || 'No se pudo completar la acción.');
      return null;
    } finally {
      setGuardando('');
    }
  }

  /* ── Estado, asignación y notas ──────────────────────────────────────── */

  function cambiarEstado(nuevo) {
    if (!nuevo || nuevo === caso.status) return;
    if (nuevo === 'closed' &&
        !globalThis.confirm('Cerrar el caso deja registrada la fecha de cierre. ¿Seguro?')) return;
    accion('estado', async () => {
      await api.post(`/cases/${casoId}/status`, { status: nuevo });
      await cargar();
    }, `Estado cambiado a «${ESTADOS_CASO[nuevo]?.etiqueta || nuevo}».`);
  }

  const asignar = (a) => accion('asignar', async () => {
    await api.post(`/cases/${casoId}/assign`, { assigned_to: a });
    await cargar();
  }, `Asignado a ${a}.`);

  /**
   * Tomar el caso. Distinto de asignárselo: el backend responde 409 si ya lo
   * tiene otra persona, y entonces se pregunta antes de quitárselo. Sin ese
   * paso, dos analistas se pisan el trabajo sin enterarse.
   */
  async function tomar(forzar = false) {
    setGuardando('tomar'); setAviso(''); setError('');
    try {
      const r = await api.crudo('POST', `/cases/${casoId}/take`, { force: forzar });
      if (r.ok && r.datos?.assigned_to) {
        setAviso('El caso es tuyo.');
        await cargar();
        return;
      }
      if (r.status === 409) {
        const quien = r.datos?.error || 'El caso ya está asignado.';
        if (globalThis.confirm(`${quien}\n\n¿Tomarlo igual?`)) {
          setGuardando('');
          await tomar(true);
        }
        return;
      }
      setError(r.datos?.error || 'No se pudo tomar el caso.');
    } finally {
      setGuardando('');
    }
  }

  const agregarNota = () => {
    if (!nota.trim()) return;
    accion('nota', async () => {
      await api.post(`/cases/${casoId}/notes`, { content: nota.trim(), author_email: email });
      setNota('');
      await cargar();
    }, 'Nota agregada.');
  };

  /* ── La ficha KYC del cliente ────────────────────────────────────────── */

  /**
   * Trae la misma información del Análisis Individual para este cliente.
   * Le pega al cluster de Redshift, así que se consulta una vez y queda
   * guardada en el caso; `refrescar` la vuelve a pedir a propósito.
   */
  const traerPerfil = (refrescar = false) => accion('perfil', async () => {
    const d = await api.post(`/cases/${casoId}/client-profile`, { refresh: !!refrescar });
    if (!d?.profile) throw new Error(d?.error || 'No se pudo traer la ficha del cliente.');
    setPerfilCliente(d.profile);
    setPerfilCuando(d.consultado_at || '');
    setPerfilAbierto(true);
    if (d.entity_name) setCaso((c) => ({ ...c, entity_name: d.entity_name }));
  }, refrescar ? 'Ficha del cliente actualizada.' : 'Ficha del cliente traída.');

  /* ── El checklist de documentos ──────────────────────────────────────── */

  const girarDocumento = (item) => accion('checklist', async () => {
    const d = await api.post(`/cases/${casoId}/documentos-checklist`, {
      categoria: item.categoria,
      estado: siguienteEstadoDocumento(estadoDocumento(item)),
    });
    if (d?.documentos_checklist) {
      setCaso((c) => ({ ...c, documentos_checklist: d.documentos_checklist }));
    }
  });

  /* ── Los adjuntos ────────────────────────────────────────────────────── */

  async function subirUno(archivo) {
    const paso1 = await api.post(`/cases/${casoId}/attachments/upload-url`, {
      filename: archivo.name,
      content_type: archivo.type || 'application/octet-stream',
    });
    if (!paso1?.upload_url) throw new Error('no se pudo generar la URL de subida');
    // El PUT va directo a S3 con la URL prefirmada, no por la API: un
    // archivo de 20 MB no entra en el cuerpo de una request a la Lambda.
    const puesto = await fetch(paso1.upload_url, {
      method: 'PUT', body: archivo, headers: { 'Content-Type': paso1.content_type },
    });
    if (!puesto.ok) throw new Error(`la subida a S3 falló (${puesto.status})`);
    await api.post(`/cases/${casoId}/attachments`, {
      filename: archivo.name, s3_key: paso1.s3_key, size: archivo.size,
      content_type: paso1.content_type, uploaded_by: email || '',
    });
  }

  async function subir(archivos) {
    const { suben, rechazados } = repartirAdjuntos(archivos);
    const problemas = rechazados.map((a) => `${a.name}: extensión no permitida`);
    if (suben.length === 0) {
      setError(problemas.join('\n') || 'No hay archivos para subir.');
      return;
    }
    setError(''); setAviso('');
    setSubida({ activa: true, hecho: 0, total: suben.length });
    // Uno por uno y no en paralelo: cada archivo son dos llamadas a la API
    // más un PUT a S3, y quince en simultáneo desde el navegador es la forma
    // más rápida de que la Lambda empiece a devolver errores.
    for (const archivo of suben) {
      try {
        await subirUno(archivo);
      } catch (e) {
        // Un archivo que falla no puede cortar los catorce siguientes.
        problemas.push(`${archivo.name}: ${e?.message || 'error'}`);
      }
      setSubida((s) => ({ ...s, hecho: s.hecho + 1 }));
    }
    setSubida({ activa: false, hecho: 0, total: 0 });
    await cargar();
    if (problemas.length) {
      // Se nombran: «3 fallaron» obliga a adivinar cuáles hay que reintentar.
      setError(`No se subieron ${problemas.length} de ${archivos.length}:\n${problemas.join('\n')}`);
    } else {
      setAviso(`${suben.length} documento(s) adjuntado(s).`);
    }
  }

  const bajarAdjunto = (id) => accion('bajar', async () => {
    const d = await api.get(`/cases/${casoId}/attachments/${id}/download-url`);
    if (d?.download_url) globalThis.open(d.download_url, '_blank', 'noopener');
  });

  const borrarAdjunto = (a) => {
    if (!globalThis.confirm(`¿Eliminar «${a.filename}»? Esta acción no se puede deshacer.`)) return;
    accion('adjunto', async () => {
      await api.del(`/cases/${casoId}/attachments/${a.attachment_id}`);
      setAdjuntos((xs) => xs.filter((x) => x.attachment_id !== a.attachment_id));
    }, 'Adjunto eliminado.');
  };

  /* ── Correos, exportación, borrado, whitelist e IA ───────────────────── */

  const traerCorreos = () => accion('correos', async () => {
    setCorreos(await api.get(`/cases/${casoId}/correos`));
  });

  const exportar = () => accion('exportar', async () => {
    const d = await api.get(`/cases/${casoId}/export`);
    if (!d?.download_url) throw new Error('El backend no devolvió la exportación.');
    // Una descarga en una pestaña nueva y no un <a download>: la URL es de
    // S3, de otro origen, y el atributo `download` se ignora ahí.
    globalThis.open(d.download_url, '_blank', 'noopener');
  }, 'Exportación lista.');

  const borrarCaso = () => {
    const ok = globalThis.confirm(
      `¿Eliminar definitivamente el caso «${caso.title || casoId}»?\n\n`
      + 'Se borran también sus documentos adjuntos. Las alertas vinculadas NO se '
      + 'borran: vuelven a quedar sin caso.\n\nEsta acción no se puede deshacer.');
    if (!ok) return;
    accion('borrar', async () => {
      await api.del(`/cases/${casoId}`);
      navegar('cases');
    });
  };

  const guardarWhitelist = () => {
    const cuerpo = altaDeWhitelist(caso, {
      dias: wl.dias, alcance: wl.alcance, motivo: wl.motivo, quien: email,
    });
    if (!cuerpo.entity_value || !cuerpo.reason) return;
    accion('whitelist', async () => {
      await api.post('/whitelist', cuerpo);
      // La nota es secundaria al alta: si falla, la whitelist ya quedó.
      try {
        await api.post(`/cases/${casoId}/notes`, {
          content: notaDeWhitelist(cuerpo), author_email: email,
        });
      } catch { /* la whitelist ya se creó; la nota se puede escribir a mano */ }
      setWl({ abierta: false, dias: 30, alcance: 'global', motivo: '' });
      await cargar();
    }, 'Cliente agregado a la whitelist.');
  };

  const analizarConIa = () => accion('ia', async () => {
    setIa('');
    const prompt = promptDelCaso({
      caso, alertas, notas,
      contexto: contextoDelCliente(perfilCliente),
      etiquetaEstado: estado?.etiqueta,
    });
    const d = await api.post('/ai/generate', {
      prompt, temperature: TEMPERATURA_IA, max_tokens: MAX_TOKENS_IA,
    });
    setIa(d?.text || 'Sin respuesta de la IA.');
  });

  /* ── El dibujo ───────────────────────────────────────────────────────── */

  return (
    <>
      <nav className="wt-migas">
        <button onClick={() => navegar('cases')}>Casos</button>
        <span>›</span>
        <span className="mono">{casoId}</span>
      </nav>

      {error && (
        <div className="wt-estado-error" style={{ marginBottom: 'var(--e-4)', whiteSpace: 'pre-wrap' }}>
          {error}
        </div>
      )}
      {aviso && (
        <p className="wt-aviso-lectura"
           style={{ background: 'var(--nivel-bajo-tenue)', color: 'var(--nivel-bajo-texto)' }}>
          {aviso}
        </p>
      )}

      {cargando && !caso ? (
        <p className="wt-estado">Cargando…</p>
      ) : !caso ? null : (
        <div className="wt-triage">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--e-4)' }}>
            <section className="wt-carta">
              <header className="wt-carta-cabecera">
                <h2 className="wt-carta-titulo">
                  {/* El nombre si lo hay; si no, el id. El `title` no va acá:
                      en 72 de 89 casos es el nombre del reporte. */}
                  {caso.entity_name || `Cliente ${caso.entity_id || ''}`.trim()}
                </h2>
                <div className="wt-carta-herramientas">
                  <span className="wt-insignia"
                        style={{ color: estado?.color || 'var(--texto-2)',
                                 background: 'var(--superficie-3)' }}>
                    {estado?.etiqueta || caso.status}
                  </span>
                  <InsigniaSla caso={caso} />
                </div>
              </header>
              <div className="wt-cuerpo-carta">
                <dl className="wt-datos">
                  <Dato etiqueta="Cliente">
                    <span className="mono">{caso.entity_id}</span>
                    {caso.entity_name && <> · {caso.entity_name}</>}
                    {caso.entity_id && (
                      <button className="wt-btn" style={{ marginLeft: 8, padding: '2px 8px' }}
                              onClick={() => navegar('ficha', [caso.entity_id])}>
                        Ver ficha
                      </button>
                    )}
                  </Dato>
                  {caso.title && caso.title !== caso.entity_name &&
                    <Dato etiqueta="Título">{caso.title}</Dato>}
                  {caso.description && <Dato etiqueta="Descripción">{caso.description}</Dato>}
                  {caso.report_name &&
                    <Dato etiqueta="Reporte de origen"><span className="mono">{caso.report_name}</span></Dato>}
                  <Dato etiqueta="Abierto hace">
                    {diasTexto(caso.sla_dias)}
                    <span style={{ color: 'var(--texto-mute)' }}>
                      {' · desde '}{fecha(caso.created_at)?.toLocaleString('es-CL') || caso.created_at}
                    </span>
                  </Dato>
                  {caso.updated_at && (
                    <Dato etiqueta="Última actualización">
                      {fecha(caso.updated_at)?.toLocaleString('es-CL') || caso.updated_at}
                    </Dato>
                  )}
                  {caso.sla_aplica && (
                    <Dato etiqueta="Contactos al cliente">
                      {sinContactar(caso)
                        ? <span style={{ color: 'var(--nivel-alto-texto)', fontWeight: 'var(--peso-medio)' }}>
                            nunca se le escribió
                          </span>
                        : <>{caso.sla_contactos}
                            {caso.sla_ultimo_contacto &&
                              <span style={{ color: 'var(--texto-mute)' }}>
                                {' · el último '}{hace(caso.sla_ultimo_contacto)}
                              </span>}
                          </>}
                      {caso.sla_respondio && (
                        <span style={{ color: 'var(--nivel-bajo-texto)', marginLeft: 8 }}>
                          el cliente respondió
                        </span>
                      )}
                    </Dato>
                  )}
                  <Dato etiqueta="Asignado a">
                    {caso.assigned_to || (
                      <span style={{ color: 'var(--nivel-alto-texto)' }}>sin asignar</span>
                    )}
                  </Dato>
                  <Dato etiqueta="Creado por">{caso.created_by || '—'}</Dato>
                  {caso.closed_at && <Dato etiqueta="Cerrado">{caso.closed_at}</Dato>}
                </dl>
              </div>
            </section>

            {/* ── La ficha KYC del cliente ───────────────────────────────── */}
            {caso.entity_id && (
              <Carta
                titulo="Ficha del cliente"
                herramientas={
                  <>
                    {perfilCuando && (
                      <span className="wt-insignia"
                            style={{ color: 'var(--texto-mute)', background: 'var(--superficie-3)' }}>
                        consultada {perfilCuando}
                      </span>
                    )}
                    {perfilCliente && (
                      <button className="wt-btn" onClick={() => setPerfilAbierto((v) => !v)}>
                        {perfilAbierto ? 'Ocultar' : 'Ver'}
                      </button>
                    )}
                    {!lectura && (
                      <button className="wt-btn" disabled={guardando === 'perfil'}
                              title={perfilCliente ? 'Volver a consultar el cluster' : ''}
                              onClick={() => traerPerfil(!!perfilCliente)}>
                        {guardando === 'perfil' ? 'Consultando…'
                          : perfilCliente ? 'Volver a consultar' : 'Traer datos KYC / compliance'}
                      </button>
                    )}
                  </>
                }
              >
                {!perfilCliente ? (
                  <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
                    Trae la misma información del Análisis Individual para{' '}
                    <span className="mono">{caso.entity_id}</span>. Se consulta una vez y
                    queda guardada en el caso.
                  </p>
                ) : perfilAbierto ? (
                  <Campos datos={perfilCliente} />
                ) : (
                  <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
                    {camposPerfil.length} campos guardados.
                  </p>
                )}
              </Carta>
            )}

            {/* ── La fila que originó la alerta ──────────────────────────── */}
            {camposAlerta.length > 0 && (
              <Carta
                titulo="Alerta que originó el caso"
                herramientas={
                  <>
                    {caso.alert_priority && (
                      <span className="wt-insignia"
                            style={{ color: 'var(--nivel-critico-texto)',
                                     background: 'var(--nivel-critico-tenue)' }}>
                        {caso.alert_priority}
                      </span>
                    )}
                    {caso.report_name && (
                      <span className="mono" style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                        {caso.report_name}
                      </span>
                    )}
                  </>
                }
              >
                <Campos datos={comoFila(caso.alert_data)} />
                <p style={{ marginTop: 'var(--e-2)', marginBottom: 0,
                            fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                  Son los valores de la fila del reporte que gatilló esta alerta, tal como
                  estaban al detectarla.
                </p>
              </Carta>
            )}

            {pidiendo && (
              <Suspense fallback={<p className="wt-estado">Armando el correo…</p>}>
                <PedirDocumentos api={api} caso={caso} perfil={perfilCliente} email={email}
                                 alCerrar={() => setPidiendo(false)}
                                 alTerminar={async (msg) => {
                                   setPidiendo(false); setAviso(msg);
                                   setCorreos(null);
                                   await cargar();
                                 }} />
              </Suspense>
            )}

            {/* ── El checklist de documentos ─────────────────────────────── */}
            {checklist.length > 0 && (
              <Carta
                titulo="Documentos solicitados"
                cuenta={`${resumenDocs.entregado} de ${resumenDocs.total} entregados`}
                herramientas={!lectura && (
                  <button className="wt-btn" onClick={() => setPidiendo(true)}>
                    {correos ? 'Reenviar el correo' : 'Escribirle al cliente'}
                  </button>
                )}
              >
                <div className="wt-checklist">
                  {checklist.map((item) => {
                    const clave = estadoDocumento(item);
                    const e = ESTADOS_DOCUMENTO[clave];
                    return (
                      <button key={item.categoria} className="wt-checklist-item"
                              disabled={lectura || guardando === 'checklist'}
                              title={lectura ? 'Tu perfil es de consulta' : 'Cambiar el estado'}
                              onClick={() => girarDocumento(item)}>
                        <span style={{ textDecoration: clave === 'entregado' ? 'line-through' : 'none' }}>
                          {item.categoria}
                        </span>
                        <span className="wt-insignia" style={{ color: e.color, background: e.fondo }}>
                          {e.etiqueta}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </Carta>
            )}

            {/* ── Los adjuntos ──────────────────────────────────────────── */}
            <Carta titulo="Documentos adjuntos" cuenta={adjuntos.length}>
              {adjuntos.length === 0 ? (
                <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                  Sin adjuntos todavía.
                </p>
              ) : (
                <div className="wt-adjuntos">
                  {adjuntos.map((a) => (
                    <div key={a.attachment_id} className="wt-adjunto">
                      <button className="wt-adjunto-nombre" onClick={() => bajarAdjunto(a.attachment_id)}>
                        {a.filename}
                      </button>
                      {vinoPorCorreo(a) && (
                        <span className="wt-insignia"
                              style={{ color: 'var(--g66-azul-texto)', background: 'var(--superficie-3)' }}>
                          por correo
                        </span>
                      )}
                      <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                        {a.uploaded_by || '—'}
                        {a.uploaded_at && ` · ${fecha(a.uploaded_at)?.toLocaleDateString('es-CL') || ''}`}
                      </span>
                      {!lectura && (
                        <button className="wt-btn" style={{ padding: '2px 8px' }}
                                onClick={() => borrarAdjunto(a)}>Eliminar</button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {!lectura && (
                <div
                  className={`wt-soltar${arrastrando ? ' wt-soltar-activo' : ''}`}
                  onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
                  onDragLeave={(e) => { e.preventDefault(); setArrastrando(false); }}
                  onDrop={(e) => {
                    e.preventDefault(); setArrastrando(false);
                    subir(Array.from(e.dataTransfer?.files || []));
                  }}
                  onClick={() => !subida.activa && archivoRef.current?.click()}
                >
                  {subida.activa ? (
                    <>
                      <p style={{ margin: 0 }}>Subiendo {subida.hecho} de {subida.total}…</p>
                      <div className="wt-progreso">
                        <div className="wt-progreso-barra"
                             style={{ width: `${Math.round(subida.hecho * 100 / (subida.total || 1))}%` }} />
                      </div>
                    </>
                  ) : (
                    <>
                      <p style={{ margin: 0 }}>Arrastrá los documentos acá</p>
                      <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                        o hacé clic para elegirlos — podés seleccionar varios
                      </p>
                    </>
                  )}
                  <input ref={archivoRef} type="file" multiple hidden disabled={subida.activa}
                         onChange={(e) => { subir(Array.from(e.target.files || [])); e.target.value = ''; }} />
                </div>
              )}
            </Carta>

            {/* ── El historial de correos ────────────────────────────────── */}
            <Carta
              titulo="Historial de correos"
              herramientas={
                <>
                  {bandeja.correos.length > 0 && (
                    <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                      {bandeja.enviados} enviado(s) · {bandeja.recibidos} recibido(s)
                    </span>
                  )}
                  {bandeja.fallidos > 0 && (
                    <span className="wt-insignia"
                          style={{ color: 'var(--nivel-critico-texto)',
                                   background: 'var(--nivel-critico-tenue)' }}>
                      {bandeja.fallidos} no salió(eron)
                    </span>
                  )}
                  <button className="wt-btn" disabled={guardando === 'correos'} onClick={traerCorreos}>
                    {guardando === 'correos' ? 'Cargando…' : correos ? 'Actualizar' : 'Cargar'}
                  </button>
                </>
              }
            >
              {!correos ? (
                <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                  Los correos se traen a pedido. Muestran la conversación con el cliente:
                  qué se le pidió, qué contestó y qué envío no llegó a salir.
                </p>
              ) : bandeja.correos.length === 0 ? (
                <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                  Sin correos registrados en este caso.
                </p>
              ) : (
                <Correos correos={bandeja.correos} />
              )}
            </Carta>

            {/* ── Las notas ─────────────────────────────────────────────── */}
            <Carta titulo="Notas de investigación" cuenta={notas.length}>
              {notas.length === 0 ? (
                <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                  Todavía no hay notas en este caso.
                </p>
              ) : notas.map((nt) => (
                <article key={nt.note_id} className="wt-nota-caso">
                  <div className="wt-nota-caso-meta">
                    {/* El autor puede faltar: hubo notas guardadas sin él. */}
                    {nt.author_email || 'autor desconocido'}
                    {' · '}
                    <span title={nt.created_at}>{hace(nt.created_at)}</span>
                  </div>
                  <div className="wt-nota-caso-texto">{nt.content}</div>
                </article>
              ))}
            </Carta>

            {/* ── El análisis con IA ────────────────────────────────────── */}
            <Carta
              titulo="Análisis con IA"
              herramientas={!lectura && (
                <button className="wt-btn" disabled={guardando === 'ia'} onClick={analizarConIa}>
                  {guardando === 'ia' ? 'Analizando…' : 'Analizar'}
                </button>
              )}
            >
              {ia ? (
                <div className="wt-ia">{ia}</div>
              ) : (
                <p style={{ margin: 0, color: 'var(--texto-mute)', fontSize: 'var(--texto-base)' }}>
                  Arma un análisis con el caso, sus alertas, sus notas y la ficha del cliente
                  si ya se trajo. No guarda nada: es una lectura, y la conclusión la escribe
                  quien investiga.
                </p>
              )}
            </Carta>
          </div>

          {/* ── La columna de acciones ───────────────────────────────────── */}
          <section className="wt-carta">
            <header className="wt-carta-cabecera">
              <h2 className="wt-carta-titulo">Qué hacer</h2>
            </header>
            <div className="wt-cuerpo-carta wt-acciones">
              <button className="wt-btn" disabled={guardando === 'exportar'} onClick={exportar}>
                {guardando === 'exportar' ? 'Exportando…' : 'Exportar el caso'}
              </button>
              {caso.entity_id && (
                <button className="wt-btn" onClick={() => navegar('ficha', [caso.entity_id])}>
                  Ver la ficha del cliente
                </button>
              )}

              {lectura ? (
                <p style={{ margin: 0, fontSize: 'var(--texto-base)', color: 'var(--texto-mute)' }}>
                  Tu perfil es de consulta: podés ver el caso y exportarlo, pero no
                  modificarlo.
                </p>
              ) : (
                <>
                  <hr className="wt-separador" />

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    Estado
                    <select className="wt-input" style={{ width: '100%', marginTop: 4 }}
                            value={caso.status} disabled={guardando === 'estado'}
                            onChange={(e) => cambiarEstado(e.target.value)}>
                      {ESTADOS_ELEGIBLES.map((k) => (
                        <option key={k} value={k}>{ESTADOS_CASO[k]?.etiqueta || k}</option>
                      ))}
                      {/* Un estado que el backend puso y no está en la lista se
                          muestra igual, para no cambiarlo sin querer. */}
                      {!ESTADOS_ELEGIBLES.includes(caso.status) && (
                        <option value={caso.status}>{caso.status}</option>
                      )}
                    </select>
                  </label>

                  <button className="wt-btn wt-btn-primario"
                          disabled={guardando === 'tomar' || caso.assigned_to === email}
                          onClick={() => tomar()}>
                    {caso.assigned_to === email ? 'Ya es tuyo' : 'Tomar el caso'}
                  </button>

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    O asignar a otra persona
                    <select className="wt-input" style={{ width: '100%', marginTop: 4 }} value=""
                            disabled={guardando === 'asignar'}
                            onChange={(e) => e.target.value && asignar(e.target.value)}>
                      <option value="">Elegir…</option>
                      {usuarios.map((u) => (
                        <option key={u.email} value={u.email}>
                          {u.full_name || u.email}{u.equipo ? ` · ${u.equipo}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>

                  {/* La whitelist sin salir del caso. Antes había que cerrar,
                      ir a la tabla y volver a tipear el ID: tres pasos para
                      algo que se decide justo acá, al cerrar. */}
                  {caso.status === 'closed' && caso.entity_id && (
                    <>
                      <hr className="wt-separador" />
                      {!wl.abierta ? (
                        <>
                          <button className="wt-btn" onClick={() => setWl((w) => ({ ...w, abierta: true }))}>
                            Pasar este cliente a whitelist
                          </button>
                          <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                            Silencia sus alertas por el período que elijas. Queda registrado
                            con tu nombre y como nota del caso.
                          </p>
                        </>
                      ) : (
                        <>
                          <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                            Por cuánto tiempo
                            <select className="wt-input" style={{ width: '100%', marginTop: 4 }}
                                    value={wl.dias}
                                    onChange={(e) => setWl((w) => ({ ...w, dias: e.target.value }))}>
                              {DURACIONES_WHITELIST.map((d) => (
                                <option key={d} value={d}>{d} días</option>
                              ))}
                            </select>
                          </label>
                          <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                            Alcance
                            <select className="wt-input" style={{ width: '100%', marginTop: 4 }}
                                    value={wl.alcance}
                                    onChange={(e) => setWl((w) => ({ ...w, alcance: e.target.value }))}>
                              <option value="global">Todas las alertas</option>
                              <option value="report">Sólo {caso.report_name || 'este reporte'}</option>
                            </select>
                          </label>
                          <input className="wt-input" style={{ width: '100%' }} value={wl.motivo}
                                 placeholder="Motivo (queda en la auditoría)"
                                 onChange={(e) => setWl((w) => ({ ...w, motivo: e.target.value }))} />
                          <div style={{ display: 'flex', gap: 'var(--e-2)' }}>
                            <button className="wt-btn"
                                    onClick={() => setWl((w) => ({ ...w, abierta: false }))}>
                              Cancelar
                            </button>
                            <button className="wt-btn wt-btn-primario"
                                    disabled={!wl.motivo.trim() || guardando === 'whitelist'}
                                    onClick={guardarWhitelist}>
                              Confirmar
                            </button>
                          </div>
                        </>
                      )}
                    </>
                  )}

                  <hr className="wt-separador" />

                  <button className="wt-btn" disabled={!caso.entity_id}
                          onClick={() => setPidiendo(true)}>
                    Pedirle documentación al cliente
                  </button>
                  <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                    Muestra el correo completo antes de mandarlo, y avisa si ya se le pidió
                    lo mismo hace poco.
                  </p>

                  <hr className="wt-separador" />

                  {/* El ROS nace del caso: es acá donde alguien concluye que hay
                      sospecha, y desde acá se arma con su evidencia. No reporta
                      nada — abre el borrador en el registro. */}
                  <button className="wt-btn" onClick={() => navegar('ros')}>
                    Reportar a la UAF (ROS)
                  </button>
                  <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                    Abre el registro de ROS para armar el borrador con la evidencia de
                    este caso. No envía nada al regulador.
                  </p>

                  <hr className="wt-separador" />

                  <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
                    Nueva nota
                    <textarea className="wt-input"
                              style={{ width: '100%', marginTop: 4, minHeight: 90, resize: 'vertical' }}
                              value={nota} onChange={(e) => setNota(e.target.value)}
                              placeholder="Qué se revisó, qué se concluyó…" />
                  </label>
                  <button className="wt-btn" disabled={guardando === 'nota' || !nota.trim()}
                          onClick={agregarNota}>
                    Agregar la nota
                  </button>

                  {administra && (
                    <>
                      <hr className="wt-separador" />
                      <button className="wt-btn wt-btn-peligro"
                              disabled={guardando === 'borrar'} onClick={borrarCaso}>
                        Eliminar el caso
                      </button>
                      <p style={{ margin: 0, fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
                        Se borran también sus adjuntos. Las alertas vinculadas vuelven a
                        quedar sin caso.
                      </p>
                    </>
                  )}
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}

/** Sólo los campos del semáforo, para que el detalle no los pise con undefined.
 *
 *  `GET /cases/{id}` no los trae; si se hiciera `{...lista, ...detalle}` sin
 *  esto, las claves que el detalle no tiene quedarían igual, pero cualquier
 *  día que el detalle empiece a mandarlas vacías borrarían las buenas. */
function slaDe(c) {
  const salida = {};
  for (const [k, v] of Object.entries(c || {})) {
    if (k.startsWith('sla_') || k === 'note_count') salida[k] = v;
  }
  return salida;
}
