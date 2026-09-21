/* ============================================================================
   Tablero — la agregación
   ----------------------------------------------------------------------------
   Los números y las series del dashboard, calculados de las alertas, los
   casos y las corridas que la aplicación ya tiene cargados.

   POR QUÉ SE AGREGA EN EL FRONT Y NO SE PIDE. Son las mismas listas que ya
   se bajan para la bandeja y para casos: pedir un endpoint de resumen sería
   una segunda fuente de verdad para los mismos números, y el día que las dos
   no coincidan nadie va a saber cuál mirar. Lo único que sí se pide son los
   tres gráficos de transacciones, porque esos salen de Redshift y no de una
   lista que el front ya tenga.

   LAS FECHAS SON LA PARTE QUE SE ROMPE. Agrupar por día suena trivial hasta
   que aparecen las zonas horarias: el backend manda UTC sin marcarlo, y si
   se agrupa con la fecha local del navegador, todo lo que pasó después de
   las 21:00 en Chile cae en el día siguiente. Acá se agrupa en UTC, que es
   como está guardado.
   ========================================================================= */

import { fecha } from './alertas.js';

export { fecha };

/** El día de una marca de tiempo, en UTC y como `2026-09-21`. */
export function diaDe(texto) {
  const f = fecha(texto);
  return f ? f.toISOString().slice(0, 10) : null;
}

/** Los últimos `n` días, terminando hoy, como `2026-09-21`. */
export function ultimosDias(n, hasta = new Date()) {
  const dias = [];
  for (let i = n - 1; i >= 0; i -= 1) {
    const d = new Date(hasta.getTime() - i * 86400000);
    dias.push(d.toISOString().slice(0, 10));
  }
  return dias;
}

/**
 * Una serie diaria: cuántos elementos cayeron en cada uno de los últimos
 * `n` días.
 *
 * Los días SIN datos se devuelven en cero y no se saltean. Una línea que
 * une el lunes con el jueves porque martes y miércoles no tuvieron alertas
 * dibuja una pendiente suave donde en realidad hubo dos días en blanco.
 */
export function serieDiaria(elementos, campoFecha, n = 30, hasta = new Date()) {
  const cuenta = new Map(ultimosDias(n, hasta).map((d) => [d, 0]));
  for (const e of elementos || []) {
    const d = diaDe(e?.[campoFecha]);
    if (d !== null && cuenta.has(d)) cuenta.set(d, cuenta.get(d) + 1);
  }
  return [...cuenta.entries()].map(([dia, n_]) => ({ etiqueta: dia, valor: n_ }));
}

/** El lunes de la semana de una fecha, en UTC. */
export function semanaDe(texto) {
  const f = fecha(texto);
  if (!f) return null;
  const d = new Date(Date.UTC(f.getUTCFullYear(), f.getUTCMonth(), f.getUTCDate()));
  // getUTCDay: 0 es domingo. Se corre al lunes anterior.
  const desplazamiento = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - desplazamiento);
  return d.toISOString().slice(0, 10);
}

/** Una serie semanal de las últimas `n` semanas. */
export function serieSemanal(elementos, campoFecha, n = 8, hasta = new Date()) {
  const lunes = semanaDe(hasta.toISOString());
  const base = new Date(lunes + 'T00:00:00Z');
  const semanas = [];
  for (let i = n - 1; i >= 0; i -= 1) {
    semanas.push(new Date(base.getTime() - i * 7 * 86400000).toISOString().slice(0, 10));
  }
  const cuenta = new Map(semanas.map((s) => [s, 0]));
  for (const e of elementos || []) {
    const s = semanaDe(e?.[campoFecha]);
    if (s !== null && cuenta.has(s)) cuenta.set(s, cuenta.get(s) + 1);
  }
  return [...cuenta.entries()].map(([etiqueta, valor]) => ({ etiqueta, valor }));
}

/**
 * Cuenta por una clave, de mayor a menor, con un tope.
 *
 * Lo que no entra en el tope se junta en «otros» en vez de desaparecer: un
 * gráfico de «top 5» que esconde el 60% restante hace creer que esos cinco
 * son casi todo.
 */
export function porClave(elementos, campo, tope = 0, etiquetaOtros = 'otros') {
  const cuenta = new Map();
  for (const e of elementos || []) {
    const k = e?.[campo] || '(sin dato)';
    cuenta.set(k, (cuenta.get(k) || 0) + 1);
  }
  const todas = [...cuenta.entries()]
    .map(([etiqueta, valor]) => ({ etiqueta, valor }))
    .sort((a, b) => b.valor - a.valor || a.etiqueta.localeCompare(b.etiqueta));
  if (!tope || todas.length <= tope) return todas;
  const visibles = todas.slice(0, tope);
  const resto = todas.slice(tope).reduce((a, x) => a + x.valor, 0);
  return [...visibles, { etiqueta: etiquetaOtros, valor: resto, esOtros: true }];
}

/** Recorta los elementos a los últimos `n` días. */
export function ultimos(elementos, campoFecha, n, hasta = new Date()) {
  const corte = hasta.getTime() - n * 86400000;
  return (elementos || []).filter((e) => {
    const f = fecha(e?.[campoFecha]);
    return f !== null && f.getTime() >= corte;
  });
}

/* ── Los números de arriba ──────────────────────────────────────────────── */

export function indicadores({ alertas, casos, listaBlanca, corridas }, hasta = new Date()) {
  const a = alertas || [];
  const c = casos || [];
  const abiertos = c.filter((x) => !['closed', 'archived'].includes(x.status));
  return {
    alertas: a.length,
    alertas7d: ultimos(a, 'created_at', 7, hasta).length,
    casosAbiertos: abiertos.length,
    casosVencidos: abiertos.filter((x) => x.sla_estado === 'vencido').length,
    listaBlanca: (listaBlanca || []).length,
    corridas7d: ultimos(corridas || [], 'started_at', 7, hasta).length,
  };
}

/* ── Formato de etiquetas ───────────────────────────────────────────────── */

/** `2026-09-21` → `21/09`. Las series diarias no necesitan el año. */
export function diaCorto(iso) {
  if (!iso || iso.length < 10) return iso || '';
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
}
