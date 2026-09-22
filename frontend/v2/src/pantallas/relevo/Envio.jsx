/* ============================================================================
   El panel de envío de un caso de relevo
   ----------------------------------------------------------------------------
   Sirve para los cuatro correos que se le pueden mandar a un cliente —pedido,
   recontacto, mensaje libre y devolución— porque los cuatro funcionan igual:
   el backend arma una VISTA PREVIA con un `POST` sin `enviar`, y recién con
   `enviar: true` sale de verdad.

   EL CUERPO SE MUESTRA COMPLETO ANTES. Del otro lado hay una persona real y
   un correo que no se deshace. Ver a quién le llega, con qué asunto y con qué
   texto es lo único que frena un envío al cliente equivocado — y es la razón
   de que no haya un botón de un solo paso en ninguna parte de este módulo.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

import { confirmacionDeEnvio, impedimento } from '../../comun/envios.js';

/* La ruta de cada uno va ENTERA y literal, no armada con una variable: así se
   la encuentra grepeando, y el guardián de paridad —que lee las rutas del
   código— puede ver que están cubiertas. */
const TIPOS = {
  pedido: {
    titulo: 'Pedido de documentación',
    ruta: (id) => `/relevo/casos/${id}/pedido`,
    pie: 'Le pide al cliente los documentos que faltan. El caso pasa a «pedido enviado».',
  },
  recontacto: {
    titulo: 'Recontacto',
    ruta: (id) => `/relevo/casos/${id}/recontactar`,
    pie: 'Le recuerda el pedido anterior. Suma un intento al caso.',
  },
  mensaje: {
    titulo: 'Mensaje libre',
    ruta: (id) => `/relevo/casos/${id}/mensaje`,
    pie: 'Un correo escrito a mano, con la firma y el formato del partner.',
  },
  devolucion: {
    titulo: 'Devolución de fondos',
    ruta: (id) => `/relevo/casos/${id}/devolucion`,
    pie: 'Le avisa al partner que se devuelven los fondos. CIERRA el caso.',
    cierra: true,
  },
};

export function Envio({ api, caso, tipo, email, alCerrar, alTerminar }) {
  const cfg = TIPOS[tipo];
  const [vista, setVista] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const [texto, setTexto] = useState('');
  const [nota, setNota] = useState('');
  const [idioma, setIdioma] = useState('');

  const previsualizar = useCallback(async () => {
    setCargando(true); setError('');
    try {
      const cuerpo = {};
      if (tipo === 'mensaje') cuerpo.texto = texto;
      if (tipo === 'devolucion') { cuerpo.idioma = idioma; cuerpo.nota = nota; }
      setVista(await api.post(cfg.ruta(encodeURIComponent(caso.id)), cuerpo));
    } catch (e) {
      setError(e?.message || 'No se pudo armar la vista previa.');
      setVista(null);
    } finally {
      setCargando(false);
    }
  // `texto`, `nota` e `idioma` quedan afuera a propósito: se previsualiza al
  // abrir y cuando quien escribe lo pide, no en cada tecla — cada vuelta es
  // una llamada a la API.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, caso.id, cfg, tipo]);

  useEffect(() => { previsualizar(); }, [previsualizar]);

  const frena = impedimento(vista);

  async function enviar() {
    if (frena) return;
    if (!globalThis.confirm(confirmacionDeEnvio(vista, { cierra: cfg.cierra }))) return;
    setEnviando(true); setError('');
    try {
      const cuerpo = { enviar: true, quien: email || '', actor_email: email || '' };
      if (tipo === 'mensaje') cuerpo.texto = texto;
      if (tipo === 'devolucion') {
        cuerpo.idioma = vista?.idioma || idioma;
        cuerpo.nota = nota;
      }
      const d = await api.post(cfg.ruta(encodeURIComponent(caso.id)), cuerpo);
      if (!d?.enviado) throw new Error(d?.error || 'El backend no confirmó el envío.');
      alTerminar(`Enviado a ${d.para}${d.ref ? ` · ref ${d.ref}` : ''}.`);
    } catch (e) {
      setError(e?.message || 'No se pudo enviar.');
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
      <header className="wt-carta-cabecera">
        <h2 className="wt-carta-titulo">{cfg.titulo}</h2>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          {caso.cliente_nombre || caso.cliente_id || caso.id}
        </span>
        <div className="wt-carta-herramientas">
          <button className="wt-btn" onClick={alCerrar}>Cerrar</button>
        </div>
      </header>
      <div className="wt-cuerpo-carta">
        <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-base)', color: 'var(--texto-2)' }}>
          {cfg.pie}
        </p>

        {tipo === 'mensaje' && (
          <label className="wt-parametro" style={{ marginBottom: 'var(--e-3)' }}>
            <span>Qué decirle</span>
            <textarea className="wt-input" style={{ width: '100%', minHeight: 110, resize: 'vertical' }}
                      value={texto} onChange={(e) => setTexto(e.target.value)}
                      placeholder="El texto va dentro de la plantilla del partner." />
          </label>
        )}

        {tipo === 'devolucion' && (
          <div className="wt-parametros" style={{ marginBottom: 'var(--e-3)' }}>
            <label className="wt-parametro">
              <span>Idioma</span>
              <select className="wt-input" value={idioma} onChange={(e) => setIdioma(e.target.value)}>
                <option value="">El que sugiere el backend</option>
                <option value="es">Español</option>
                <option value="en">Inglés</option>
              </select>
            </label>
            <label className="wt-parametro">
              <span>Nota (opcional)</span>
              <input className="wt-input" value={nota} onChange={(e) => setNota(e.target.value)}
                     placeholder="Va dentro del correo" />
            </label>
          </div>
        )}

        {(tipo === 'mensaje' || tipo === 'devolucion') && (
          <button className="wt-btn" style={{ marginBottom: 'var(--e-3)' }}
                  disabled={cargando} onClick={previsualizar}>
            {cargando ? 'Armando…' : 'Actualizar la vista previa'}
          </button>
        )}

        {cargando ? (
          <p className="wt-estado">Armando la vista previa…</p>
        ) : (
          <>
            <dl className="wt-datos">
              <dt>Para</dt><dd>{vista?.para || <span style={{ color: 'var(--nivel-critico-texto)' }}>sin destinatario</span>}</dd>
              {vista?.partner && <><dt>Partner</dt><dd>{vista.partner}</dd></>}
              {vista?.asunto && <><dt>Asunto</dt><dd>{vista.asunto}</dd></>}
              {/* Una devolución parcial es distinta de una completa y el
                  cliente lo ve en el correo: tiene que verse acá también. */}
              {(vista?.pendientes || []).length > 0 && (
                <>
                  <dt>Sin entregar</dt>
                  <dd style={{ color: 'var(--nivel-alto-texto)' }}>
                    {vista.pendientes.length} ítem(s) — la devolución sale como PARCIAL
                  </dd>
                </>
              )}
            </dl>

            {(vista?.cuerpo || vista?.texto_plano) && (
              <div className="wt-ia" style={{ marginTop: 'var(--e-3)' }}>
                {vista.texto_plano || vista.cuerpo}
              </div>
            )}

            {frena && (
              <p className="wt-nota"
                 style={{ borderColor: 'var(--nivel-alto-texto)',
                          background: 'var(--nivel-alto-tenue)', color: 'var(--nivel-alto-texto)' }}>
                {frena}
              </p>
            )}
            {error && (
              <p className="wt-estado-error" style={{ marginTop: 'var(--e-3)' }}>{error}</p>
            )}

            <div style={{ display: 'flex', gap: 'var(--e-2)', marginTop: 'var(--e-4)' }}>
              <button className="wt-btn wt-btn-primario"
                      disabled={Boolean(frena) || enviando
                                || (tipo === 'mensaje' && !texto.trim())}
                      onClick={enviar}>
                {enviando ? 'Enviando…' : 'Enviar de verdad'}
              </button>
              <button className="wt-btn" onClick={alCerrar}>Cancelar</button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
