/* ============================================================================
   Análisis de cliente
   ----------------------------------------------------------------------------
   La consulta directa: un identificador, y sale todo lo que la base sabe de
   ese cliente. A diferencia del resto de la pantalla es SINCRÓNICA —devuelve
   las filas en la misma respuesta— así que corre contra los treinta segundos
   de API Gateway.

   POR ESO EL ERROR SE DIAGNOSTICA ANTES DE CULPAR A NADIE. El mensaje anterior
   mandaba a revisar el cluster ante cualquier fallo, y eso hizo perder tiempo
   buscando donde no era: la causa real fue un tiempo de espera agotado con el
   cluster perfectamente encendido. Ahora se consulta su estado real antes de
   decir nada.
   ========================================================================= */

import { useState } from 'react';

import { Tabla } from '../../comun/Tabla.jsx';
import { columnasDe } from '../../comun/corridas.js';

const TIPOS = {
  b2c: { etiqueta: 'Persona', ruta: '/analyze/customer/b2c', ayuda: 'id de cliente, RUT o correo' },
  b2b: { etiqueta: 'Empresa', ruta: '/analyze/customer/b2b', ayuda: 'id de empresa, RUT o razón social' },
};

export function Cliente({ api }) {
  const [tipo, setTipo] = useState('b2c');
  const [identificador, setIdentificador] = useState('');
  const [campo, setCampo] = useState('');
  const [filas, setFilas] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState('');

  async function buscar(e) {
    e?.preventDefault();
    const id = identificador.trim();
    if (!id) return;
    setBuscando(true); setError(''); setFilas(null);
    try {
      const cuerpo = { identifier: id };
      if (campo) cuerpo.campo = campo;
      const d = await api.post(TIPOS[tipo].ruta, cuerpo);
      if (d?.rows === undefined) throw new Error(d?.error || '');
      setFilas(d.rows || []);
    } catch (err) {
      setError(await explicar(api, err));
    } finally {
      setBuscando(false);
    }
  }

  return (
    <>
      <section className="wt-carta" style={{ marginBottom: 'var(--e-4)' }}>
        <header className="wt-carta-cabecera">
          <h2 className="wt-carta-titulo">Buscar un cliente</h2>
        </header>
        <form className="wt-cuerpo-carta" onSubmit={buscar}>
          <div style={{ display: 'flex', gap: 'var(--e-3)', alignItems: 'flex-end',
                        flexWrap: 'wrap' }}>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Tipo
              <select className="wt-input" style={{ display: 'block', marginTop: 4, width: 140 }}
                      value={tipo} onChange={(e) => { setTipo(e.target.value); setFilas(null); }}>
                {Object.entries(TIPOS).map(([k, v]) => (
                  <option key={k} value={k}>{v.etiqueta}</option>
                ))}
              </select>
            </label>
            <label style={{ flex: 1, minWidth: 220, fontSize: 'var(--texto-sm)',
                            color: 'var(--texto-mute)' }}>
              Identificador
              <input className="wt-input" style={{ display: 'block', marginTop: 4, width: '100%' }}
                     value={identificador} onChange={(e) => setIdentificador(e.target.value)}
                     placeholder={TIPOS[tipo].ayuda} />
            </label>
            <label style={{ fontSize: 'var(--texto-sm)', color: 'var(--texto-mute)' }}>
              Campo (opcional)
              <input className="wt-input" style={{ display: 'block', marginTop: 4, width: 170 }}
                     value={campo} onChange={(e) => setCampo(e.target.value)}
                     placeholder="dejalo vacío y busca solo" />
            </label>
            <button className="wt-btn wt-btn-primario" type="submit"
                    disabled={buscando || !identificador.trim()}>
              {buscando ? 'Buscando…' : 'Buscar'}
            </button>
          </div>
          <p style={{ margin: 'var(--e-3) 0 0', fontSize: 'var(--texto-sm)',
                      color: 'var(--texto-mute)' }}>
            Consulta Redshift en vivo y corta a los treinta segundos. Si no responde, un
            identificador más específico suele alcanzar.
          </p>
          {error && (
            <p className="wt-estado-error" style={{ marginTop: 'var(--e-3)', marginBottom: 0 }}>
              {error}
            </p>
          )}
        </form>
      </section>

      {filas !== null && (
        filas.length === 0 ? (
          <p className="wt-nota">Sin resultados para ese identificador.</p>
        ) : (
          <Tabla
            titulo={`Resultado · ${filas.length.toLocaleString('es-CL')} filas`}
            columnas={columnasDe(filas).map((c) => ({
              clave: c, titulo: c.replace(/_/g, ' '),
              tipo: typeof filas[0]?.[c] === 'number' ? 'numero' : undefined,
            }))}
            filas={filas}
            claveFila={(_, i) => i}
            porPagina={50}
            nombreExport={`cliente-${tipo}`}
          />
        )
      )}
    </>
  );
}

/**
 * Por qué falló, mirando antes de acusar.
 *
 * Si el backend dijo algo, manda eso. Si no, se consulta el estado del
 * cluster: puede estar pausado —lo está de 18:30 a 04:00— o puede estar
 * perfectamente bien y haber sido un tiempo de espera agotado. Las dos cosas
 * se arreglan distinto, y confundirlas cuesta una tarde.
 */
async function explicar(api, err) {
  if (err?.message) return err.message;
  try {
    const cl = await api.get('/cluster/status');
    if (cl && cl.status !== 'available') {
      return `El clúster está en estado «${cl.status}». Esperá a que quede disponible: `
           + 'si está despertando tarda unos minutos.';
    }
  } catch { /* si ni eso responde, se cae al mensaje genérico */ }
  return 'La consulta no respondió a tiempo (la API corta a los 30 segundos). '
       + 'Probá con un identificador más específico, o reintentá.';
}
