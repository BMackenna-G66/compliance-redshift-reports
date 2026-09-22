/* ============================================================================
   Pedirle documentación al cliente
   ----------------------------------------------------------------------------
   El único lugar de WatchTower donde un analista le escribe directamente a un
   cliente. Por eso muestra el correo COMPLETO, renderizado como le va a
   llegar, antes de que haya un botón de enviar apretable.

   LA PREVISUALIZACIÓN LLEVA NÚMERO DE TURNO. Cada cambio dispara un pedido, y
   las respuestas no vuelven en orden: sin el turno, una respuesta atrasada
   pisa la actual y se manda un correo distinto del que se estaba viendo.

   EL HTML SE MUESTRA EN UN `iframe` AISLADO y no inyectado en la página. Lo
   arma el backend a partir de plantillas propias, pero igual: el día que una
   plantilla incluya algo que un cliente escribió, inyectarlo en el documento
   lo ejecuta dentro de la sesión de quien lo mira.
   ========================================================================= */

import { useCallback, useEffect, useRef, useState } from 'react';

import { CATEGORIAS } from '../alertas/Documentos.jsx';
import {
  DIAS_PEDIDOS_PREVIOS, avisoDePedidosPrevios, borradorDelPedido, faltaParaPedir,
  pedidosSinResponder, resolverPlantilla,
} from '../../comun/pedido.js';

const CORTE_MS = 12000;

export function PedirDocumentos({ api, caso, perfil, email, alCerrar, alTerminar }) {
  const [form, setForm] = useState(() => borradorDelPedido({ caso, perfil }));
  const [plantillas, setPlantillas] = useState([]);
  const [vista, setVista] = useState({ html: '', adjunto: '', error: '', cargando: true });
  const [previos, setPrevios] = useState([]);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');

  /* Cada pedido de previsualización lleva número. Sólo el último que se
     disparó puede escribir en pantalla. */
  const turno = useRef(0);

  const cambiar = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  /* ── El catálogo de plantillas ────────────────────────────────────────── */
  useEffect(() => {
    let vivo = true;
    api.get('/email-templates').then((d) => {
      if (!vivo) return;
      const cat = d?.templates || [];
      setPlantillas(cat);
      const { clave, aviso } = resolverPlantilla(form.template_key, cat, form.entity_type);
      if (clave !== form.template_key) {
        setForm((f) => ({ ...f, template_key: clave }));
        setVista((v) => ({ ...v, error: aviso }));
      }
    }).catch(() => {
      if (vivo) setVista((v) => ({ ...v, error: 'No se pudo leer el catálogo de plantillas.' }));
    });
    return () => { vivo = false; };
  // Sólo al montar: el catálogo no cambia mientras el panel está abierto.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  /* ── Pedidos previos sin responder ───────────────────────────────────── */
  useEffect(() => {
    if (!form.entity_id) return undefined;
    let vivo = true;
    api.get(`/clientes/${encodeURIComponent(form.entity_id)}/solicitudes-recientes`
          + `?dias=${DIAS_PEDIDOS_PREVIOS}&excluir_caso=${encodeURIComponent(form.case_id || '')}`)
      .then((d) => { if (vivo) setPrevios(pedidosSinResponder(d?.solicitudes)); })
      .catch(() => {});
    return () => { vivo = false; };
  }, [api, form.entity_id, form.case_id]);

  /* ── Completar nombre y correo si faltan ─────────────────────────────── */
  useEffect(() => {
    if (!form.entity_id || (form.nombre && form.correo)) return undefined;
    let vivo = true;
    api.post('/analyze/entity-name', {
      entity_id: form.entity_id, entity_type: form.entity_type,
    }).then((d) => {
      if (!vivo || !d?.found) return;
      const p = d.profile || {};
      setForm((f) => ({
        ...f,
        nombre: f.nombre || d.entity_name || '',
        correo: f.correo || p.email || p.correo || p.customer_email || '',
      }));
    }).catch(() => {});
    return () => { vivo = false; };
  // Se intenta una vez al abrir; completar a mano no tiene que volver a
  // dispararlo.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, form.entity_id]);

  /* ── La previsualización ─────────────────────────────────────────────── */
  const previsualizar = useCallback(async () => {
    const mio = ++turno.current;
    const vigente = () => mio === turno.current;
    setVista((v) => ({ ...v, cargando: true }));

    /* Corte por tiempo. NO cancela el pedido —la capa de API no expone la
       señal del `fetch`— sino que deja de esperarlo: la respuesta, si llega,
       la descarta el número de turno. Sin esto, un pedido encolado detrás de
       otros lentos deja el panel sin resolver ni a contenido ni a error, y el
       botón de enviar queda desactivado para siempre. */
    let reloj;
    const seRindio = Symbol('tardó demasiado');
    const cortar = new Promise((resolver) => {
      reloj = setTimeout(() => resolver(seRindio), CORTE_MS);
    });

    try {
      const d = await Promise.race([
        api.post('/email-templates/preview', {
          template_key: form.template_key,
          nombre: form.nombre,
          texto_libre: form.texto_libre,
          documentos: form.documentos,
        }),
        cortar,
      ]);
      if (!vigente()) return;
      if (d === seRindio) {
        setVista((v) => ({ ...v, cargando: false, error: 'La previsualización tardó demasiado.' }));
        return;
      }
      if (!d?.html) throw new Error(d?.error || 'El backend no devolvió el correo.');
      setVista({ html: d.html, adjunto: d.adjunto || '', error: '', cargando: false });
    } catch (e) {
      if (!vigente()) return;
      setVista((v) => ({
        ...v, cargando: false, error: e?.message || 'No se pudo armar el correo.',
      }));
    } finally {
      clearTimeout(reloj);
    }
  }, [api, form.template_key, form.nombre, form.texto_libre, form.documentos]);

  useEffect(() => { previsualizar(); }, [previsualizar]);

  /* ── Enviar ──────────────────────────────────────────────────────────── */
  const plantilla = plantillas.find((t) => t.key === form.template_key);
  const falta = faltaParaPedir(form, plantilla);
  const avisoPrevios = avisoDePedidosPrevios(previos);

  async function enviar() {
    if (falta.length) return;
    const texto = `Le va a llegar un correo a ${form.correo}.\n\n`
      + (form.documentos.length
        ? `Se le piden ${form.documentos.length} documento(s).\n\n` : '')
      + (avisoPrevios ? `${avisoPrevios}\n\n` : '')
      + '¿Confirmás?';
    if (!globalThis.confirm(texto)) return;
    setEnviando(true); setError('');
    try {
      const d = await api.post('/alert-prioritization/send-manual', {
        entity_type: form.entity_type,
        entity_id: form.entity_id,
        nombre: form.nombre,
        correo: form.correo,
        prioridad: form.prioridad,
        alerta: form.alerta,
        documentos: form.documentos,
        case_id: form.case_id,
        template_key: form.template_key,
        texto_libre: form.texto_libre,
        alert_data: form.alert_data,
      });
      if (d?.error) throw new Error(d.error);
      alTerminar(`Correo enviado a ${form.correo}.`);
    } catch (e) {
      setError(e?.message || 'No se pudo enviar el correo.');
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">Pedirle documentación al cliente</h2>
        <div className="wt-carta-herramientas">
          <button className="wt-btn" onClick={alCerrar}>Cerrar</button>
        </div>
      </header>

      <div className="wt-cuerpo-carta">
        {/* Se dice ANTES de escribir el correo, no después de mandarlo. */}
        {avisoPrevios && (
          <p className="wt-nota"
             style={{ borderColor: 'var(--nivel-alto-texto)',
                      background: 'var(--nivel-alto-tenue)', color: 'var(--nivel-alto-texto)' }}>
            {avisoPrevios}
          </p>
        )}

        <div className="wt-parametros">
          <label className="wt-parametro">
            <span>Nombre</span>
            <input className="wt-input" value={form.nombre}
                   onChange={(e) => cambiar('nombre', e.target.value)} />
          </label>
          <label className="wt-parametro">
            <span>Correo</span>
            <input className="wt-input" type="email" value={form.correo}
                   onChange={(e) => cambiar('correo', e.target.value)} />
          </label>
          <label className="wt-parametro">
            <span>Plantilla</span>
            <select className="wt-input" value={form.template_key}
                    onChange={(e) => cambiar('template_key', e.target.value)}>
              {plantillas.map((t) => (
                <option key={t.key} value={t.key}>{t.label || t.key}</option>
              ))}
            </select>
          </label>
          <label className="wt-parametro">
            <span>Prioridad</span>
            <select className="wt-input" value={form.prioridad}
                    onChange={(e) => cambiar('prioridad', e.target.value)}>
              <option value="P1">P1</option><option value="P2">P2</option>
              <option value="P3">P3</option>
            </select>
          </label>
        </div>

        {plantilla?.requires_custom_text ? (
          <label className="wt-parametro" style={{ marginTop: 'var(--e-3)' }}>
            <span>El texto del correo</span>
            <textarea className="wt-input" style={{ width: '100%', minHeight: 110, resize: 'vertical' }}
                      value={form.texto_libre}
                      onChange={(e) => cambiar('texto_libre', e.target.value)}
                      placeholder="Esta plantilla no pide documentos: sirve para aclarar algo
                                   de un pedido anterior." />
          </label>
        ) : (
          <div style={{ marginTop: 'var(--e-3)' }}>
            <h3 className="wt-subtitulo">Qué documentos pedirle</h3>
            <div className="wt-checklist">
              {CATEGORIAS.map((c) => (
                <label key={c} className="wt-checklist-item" style={{ cursor: 'pointer' }}>
                  <input type="checkbox" checked={form.documentos.includes(c)}
                         onChange={(e) => cambiar('documentos',
                           e.target.checked ? [...form.documentos, c]
                                            : form.documentos.filter((x) => x !== c))} />
                  <span>{c}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        <h3 className="wt-subtitulo" style={{ marginTop: 'var(--e-4)' }}>
          Cómo le va a llegar
        </h3>
        {vista.error && (
          <p className="wt-nota"
             style={{ borderColor: 'var(--nivel-alto-texto)', color: 'var(--nivel-alto-texto)' }}>
            {vista.error}
          </p>
        )}
        {vista.cargando ? (
          <p className="wt-estado">Armando el correo…</p>
        ) : vista.html ? (
          <>
            {/* En un marco aislado, sin permisos: el correo lo arma el
                backend, pero el día que una plantilla incluya texto escrito
                por un cliente, inyectarlo acá lo ejecutaría en la sesión de
                quien lo está mirando. */}
            <iframe title="Vista previa del correo" srcDoc={vista.html} sandbox=""
                    className="wt-vista-correo" />
            {vista.adjunto && (
              <p style={{ margin: 'var(--e-2) 0 0', fontSize: 'var(--texto-sm)',
                          color: 'var(--texto-mute)' }}>
                Va con el formulario adjunto: {vista.adjunto}
              </p>
            )}
          </>
        ) : null}

        {falta.length > 0 && (
          <p className="wt-nota">Falta {falta.join(', ')}.</p>
        )}
        {error && <p className="wt-estado-error" style={{ marginTop: 'var(--e-3)' }}>{error}</p>}

        <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
          <button className="wt-btn wt-btn-primario"
                  disabled={falta.length > 0 || enviando || vista.cargando}
                  onClick={enviar}>
            {enviando ? 'Enviando…' : 'Enviar el correo'}
          </button>
          <button className="wt-btn" onClick={alCerrar}>Cancelar</button>
        </div>
      </div>
    </section>
  );
}
