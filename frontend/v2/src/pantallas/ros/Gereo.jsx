/* ============================================================================
   Traer el borrador del ROS desde GEREO
   ----------------------------------------------------------------------------
   Un paso opcional dentro de «Nuevo reporte»: le pedís a GEREO el análisis de
   un cliente y un período, y trae los datos, las señales que dispararon y un
   texto redactado.

   ESE TEXTO NO ES LA NARRATIVA DEL ROS. Es un borrador, y así se muestra:
   en su propio bloque, con su propio botón para copiarlo al campo que firma
   el oficial de cumplimiento. Ese clic es de una persona y queda registrado.
   La pantalla no lo copia sola, por la misma razón por la que este módulo
   nunca redactó una narrativa: un texto generado que alguien firma sin leer
   es el accidente que hay que evitar.

   LAS ADVERTENCIAS VAN PRIMERO, arriba de los datos. GEREO devuelve el
   reporte incompleto A PROPÓSITO —el tipo de reporte, el delito fuente y la
   tipificación dependen del criterio de un analista— y si eso queda al pie,
   se lee un documento que parece terminado.

   TARDA. Decenas de segundos, así que la generación va por una corrida que
   se sondea, igual que un reporte de analítica. La pantalla lo dice antes de
   arrancar para que nadie piense que se colgó.
   ========================================================================= */

import { useEffect, useState } from 'react';

import { seguirCorrida } from '../../comun/corridas.js';
import {
  PAISES, cuerpoDeGeneracion, faltaParaGenerar, narrativaComoTexto,
  paisDe, reglasDe, resumenDelBorrador,
} from '../../comun/gereo.js';
import { useVivo } from '../../comun/vivo.js';

const VACIO = {
  customer_id: '', tipo_cliente: 'B2C', fecha_inicio: '', fecha_fin: '',
  clientes_asociados: '', incluir_pdf: false,
};

function Aviso({ tono, children }) {
  const colores = {
    alerta: { color: 'var(--nivel-alto-texto)', fondo: 'var(--nivel-alto-tenue)' },
    info: { color: 'var(--g66-azul-texto)', fondo: 'var(--g66-azul-tenue)' },
  }[tono] || {};
  return (
    <p className="wt-nota" style={{ borderColor: colores.color,
                                    background: colores.fondo, color: colores.color }}>
      {children}
    </p>
  );
}

export function Gereo({ api, regulador, customerId, email, alUsarNarrativa,
                        alGenerar = () => {} }) {
  const pais = paisDe(regulador);
  const reglas = reglasDe(pais);
  const [form, setForm] = useState({ ...VACIO, customer_id: customerId || '' });
  // El id sigue al caso elegido MIENTRAS nadie lo haya escrito a mano. El
  // componente se monta antes de que haya caso —el bloque existe plegado—
  // así que sin esto el campo quedaba vacío para siempre. Y una vez que
  // alguien lo escribe, cambiar de caso no le pisa lo que puso.
  const [tocado, setTocado] = useState(false);
  const [estado, setEstado] = useState('');      // '', 'corriendo', 'listo', 'error'
  const [error, setError] = useState('');
  const [borrador, setBorrador] = useState(null);
  const vivo = useVivo();

  useEffect(() => {
    if (!tocado) setForm((f) => ({ ...f, customer_id: customerId || '' }));
  }, [customerId, tocado]);

  const campo = (k) => (e) => setForm((f) => ({
    ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value,
  }));

  const faltan = pais ? faltaParaGenerar({ ...form, pais }) : [];
  const listo = pais && faltan.length === 0;

  async function generar() {
    if (!listo) return;
    setEstado('corriendo'); setError(''); setBorrador(null);
    alGenerar('');   // el anterior deja de valer apenas se pide otro
    try {
      const d = await api.post('/ros/generar', cuerpoDeGeneracion({ ...form, pais }, email));
      const fin = await seguirCorrida((ruta) => api.get(ruta), d.run_id,
                                      { cancelado: () => !vivo.current });
      if (fin.status !== 'DONE') {
        setEstado('error');
        setError(fin.error_message || 'La generación no terminó bien.');
        return;
      }
      const b = await api.get(`/ros/borrador/${d.run_id}`);
      setBorrador({ ...b, run_id: d.run_id });
      setEstado('listo');
      // Se avisa hacia arriba SÓLO si hay reporte: una detención no deja
      // borrador que adjuntar, y mandar su run_id haría que crear el ROS
      // fallara con «esa corrida no generó reporte».
      if (!b.detenido) alGenerar(d.run_id);
    } catch (e) {
      setEstado('error');
      setError(e?.message || 'No se pudo generar el borrador.');
    }
  }

  const r = resumenDelBorrador(borrador);

  if (!pais) {
    return (
      <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
        Elegí el regulador y acá vas a poder traer el borrador desde GEREO.
      </p>
    );
  }

  return (
    <>
      <div className="wt-parametros">
        <label className="wt-parametro">
          <span>Id del cliente reportado</span>
          <input className="wt-input" value={form.customer_id}
                 onChange={(e) => { setTocado(true); campo('customer_id')(e); }}
                 placeholder="2402916" />
        </label>
        <label className="wt-parametro">
          <span>Tipo</span>
          <select className="wt-input" value={form.tipo_cliente}
                  onChange={campo('tipo_cliente')}>
            {reglas.tipos.map((t) => (
              <option key={t} value={t}>
                {t === 'B2C' ? 'B2C · persona natural' : 'B2B · persona jurídica'}
              </option>
            ))}
          </select>
        </label>
        <label className="wt-parametro">
          <span>Desde (mm/aaaa)</span>
          <input className="wt-input" value={form.fecha_inicio}
                 onChange={campo('fecha_inicio')} placeholder="01/2025" />
        </label>
        <label className="wt-parametro">
          <span>Hasta <span style={{ opacity: .7 }}>(opcional)</span></span>
          <input className="wt-input" value={form.fecha_fin}
                 onChange={campo('fecha_fin')} placeholder="06/2025" />
        </label>
      </div>

      {/* El campo sólo aparece donde el país lo admite. Mostrarlo deshabilitado
          en Argentina y Colombia invita a preguntarse qué hay que hacer para
          habilitarlo, y la respuesta es «nada»: ese ROS se emite por un
          único cliente. */}
      {reglas.asociados > 0 && (
        <label className="wt-parametro" style={{ marginTop: 'var(--e-3)' }}>
          <span>Clientes asociados <span style={{ opacity: .7 }}>
            (hasta {reglas.asociados}, separados por coma)</span></span>
          <input className="wt-input" value={form.clientes_asociados}
                 onChange={campo('clientes_asociados')} placeholder="3105060, 4200311" />
          <span style={{ fontSize: 'var(--texto-xs)', color: 'var(--texto-mute)' }}>
            De ellos entra la identidad: sus transacciones no se analizan. Para
            eso, pedí su propio ROS.
          </span>
        </label>
      )}

      <label className="wt-checklist-item" style={{ marginTop: 'var(--e-3)', cursor: 'pointer' }}>
        <input type="checkbox" checked={form.incluir_pdf} onChange={campo('incluir_pdf')} />
        <span style={{ fontSize: 'var(--texto-sm)' }}>
          Traer también el PDF <span style={{ color: 'var(--texto-mute)' }}>
            — le suma segundos a la generación</span>
        </span>
      </label>

      {faltan.length > 0 && form.customer_id && (
        <ul style={{ margin: 'var(--e-3) 0 0', paddingLeft: 18,
                     fontSize: 'var(--texto-sm)', color: 'var(--nivel-alto-texto)' }}>
          {faltan.map((f) => <li key={f}>{f}</li>)}
        </ul>
      )}

      <div style={{ display: 'flex', gap: 'var(--e-2)', alignItems: 'center',
                    marginTop: 'var(--e-3)' }}>
        <button className="wt-btn" type="button" onClick={generar}
                disabled={!listo || estado === 'corriendo'}>
          {estado === 'corriendo' ? 'Generando…' : 'Traer el borrador de GEREO'}
        </button>
        <span style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
          Tarda decenas de segundos: consulta la base, evalúa las reglas y redacta.
        </span>
      </div>

      {estado === 'error' && (
        <div className="wt-estado-error" style={{ marginTop: 'var(--e-3)' }}>{error}</div>
      )}

      {r?.detenido && (
        <Aviso tono="info">
          <strong>{r.titulo}.</strong> {r.mensaje} No es una falla y reintentar
          da lo mismo: un cliente de otro país no se reporta a este regulador.
        </Aviso>
      )}

      {r && !r.detenido && (
        <div style={{ marginTop: 'var(--e-4)' }}>
          {/* Primero lo que falta. GEREO devuelve el reporte incompleto a
              propósito, y si esto va al pie se lee como terminado. */}
          {r.advertencias.length > 0 && (
            <Aviso tono="alerta">
              <strong>Queda pendiente de tu criterio:</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {r.advertencias.map((a) => <li key={a}>{a}</li>)}
              </ul>
            </Aviso>
          )}

          <p style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-2)' }}>
            {r.gatilladas} señal{r.gatilladas === 1 ? '' : 'es'} gatillada
            {r.gatilladas === 1 ? '' : 's'} de {r.evaluadas} evaluada
            {r.evaluadas === 1 ? '' : 's'} · {r.secciones.length} sección
            {r.secciones.length === 1 ? '' : 'es'} del formulario
            {r.generadoEn && <> · generado {r.generadoEn}</>}
          </p>

          {r.senales.length > 0 && (
            <ul style={{ margin: '0 0 var(--e-3)', paddingLeft: 18,
                         fontSize: 'var(--texto-sm)' }}>
              {r.senales.map((s, i) => (
                <li key={s.id || i}>{s.titulo || s.id || 'Señal'}
                  {s.detalle ? ` — ${s.detalle}` : ''}</li>
              ))}
            </ul>
          )}

          {r.narrativa.length > 0 && (
            <section className="wt-carta" style={{ marginBottom: 'var(--e-3)' }}>
              <header className="wt-carta-cabecera">
                <h3 className="wt-carta-titulo" style={{ fontSize: 'var(--texto-base)' }}>
                  Borrador de GEREO
                </h3>
                <button className="wt-btn" type="button" style={{ marginLeft: 'auto' }}
                        onClick={() => alUsarNarrativa(narrativaComoTexto(borrador))}>
                  Usar como base
                </button>
              </header>
              <div className="wt-cuerpo-carta">
                {/* Se dice acá y no en una ayuda: es el punto entero. */}
                <p style={{ margin: '0 0 var(--e-3)', fontSize: 'var(--texto-sm)',
                            color: 'var(--texto-mute)' }}>
                  Esto <strong>no es</strong> la narrativa del reporte. Es un texto
                  redactado por GEREO para ahorrarte el arranque. «Usar como base» lo
                  copia al campo que vas a firmar — leelo y corregilo antes.
                </p>
                {r.narrativa.map((n) => (
                  <div key={n.titulo} style={{ marginBottom: 'var(--e-3)' }}>
                    <strong style={{ fontSize: 'var(--texto-sm)' }}>{n.titulo}</strong>
                    <p style={{ margin: '2px 0 0', fontSize: 'var(--texto-sm)',
                                color: 'var(--texto-2)', whiteSpace: 'pre-wrap' }}>
                      {n.texto}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}

export { PAISES };
