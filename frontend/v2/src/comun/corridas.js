/* ============================================================================
   Ejecutar reportes
   ----------------------------------------------------------------------------
   Un reporte se corre en dos tiempos: `POST /execute` devuelve un `run_id` y
   se va, y hay que preguntarle a `GET /runs/{id}` hasta que termine. La
   Lambda no puede esperar a una consulta de Redshift de varios minutos.

   ACÁ VIVE LA MÁQUINA DE ESTADOS, no en la pantalla, porque su forma de
   romperse es silenciosa: un sondeo que no se apaga sigue pegándole a la API
   para siempre, y uno que se apaga de más deja la corrida colgada en
   «ejecutando» aunque ya haya terminado.
   ========================================================================= */

import { MAX_TOKENS_IA, TEMPERATURA_IA } from './ia.js';

export { MAX_TOKENS_IA, TEMPERATURA_IA };


export const ESTADOS_CORRIDA = {
  RUNNING: { etiqueta: 'Ejecutando', color: 'var(--nivel-alto-texto)', fondo: 'var(--nivel-alto-tenue)' },
  DONE: { etiqueta: 'Lista', color: 'var(--nivel-bajo-texto)', fondo: 'var(--nivel-bajo-tenue)' },
  ERROR: { etiqueta: 'Falló', color: 'var(--nivel-critico-texto)', fondo: 'var(--nivel-critico-tenue)' },
};

/* Los dos estados en los que ya no hay nada que esperar. Todo lo demás
   —RUNNING, o cualquier estado que el backend agregue— se sigue sondeando:
   dejar de preguntar por un estado desconocido dejaría la corrida colgada. */
export const TERMINADA = ['DONE', 'ERROR'];

export function termino(estado) {
  return TERMINADA.includes(String(estado || '').toUpperCase());
}

export function estadoDe(corrida) {
  const clave = String(corrida?.status || '').toUpperCase();
  return ESTADOS_CORRIDA[clave] || ESTADOS_CORRIDA.RUNNING;
}

/* ── Los parámetros ──────────────────────────────────────────────────────── */

/** El primer día del mes en curso, en el formato que espera el backend. */
export function primerDiaDelMes(hoy = new Date()) {
  const a = hoy.getFullYear();
  const m = String(hoy.getMonth() + 1).padStart(2, '0');
  return `${a}-${m}-01`;
}

/**
 * Los valores con los que se abre el formulario de un reporte.
 *
 * Las fechas arrancan en el primer día del mes: es lo que el catálogo declara
 * como `first_day_of_month`, y calcularlo acá evita mandar ese literal al
 * backend como si fuera una fecha.
 */
export function parametrosPorDefecto(reporte, hoy = new Date()) {
  const valores = {};
  for (const p of reporte?.params || []) {
    if (p.type === 'date') {
      valores[p.name] = p.default && p.default !== 'first_day_of_month'
        ? p.default : primerDiaDelMes(hoy);
    } else {
      valores[p.name] = p.default ?? false;
    }
  }
  return valores;
}

/** El cuerpo de `POST /execute`. */
export function cuerpoDeEjecucion(reporte, valores, { conservarSesion = true } = {}) {
  return {
    report_name: reporte?.report_name,
    ...valores,
    keep_session: conservarSesion,
  };
}

/* ── El resultado ────────────────────────────────────────────────────────── */

/**
 * Las columnas de un resultado. Salen de la primera fila porque el backend no
 * manda un encabezado aparte: cada reporte devuelve las columnas de su SQL.
 */
export function columnasDe(filas) {
  return filas?.length ? Object.keys(filas[0]) : [];
}

/**
 * El aviso de que lo que se ve no es todo.
 *
 * `GET /runs/{id}` guarda sólo diez filas de muestra y `/rows` trae el
 * resultado completo, pero también recortado cuando es enorme. Sin decirlo,
 * alguien cuenta las filas de la pantalla y concluye sobre un subconjunto sin
 * saber que lo es.
 */
export function avisoDeRecorte(datos) {
  if (!datos?.truncated) return '';
  const n = Number(datos.count || 0).toLocaleString('es-CL');
  const total = Number(datos.total || 0).toLocaleString('es-CL');
  return datos.reason
    ? `Mostrando ${n} de ${total} filas — ${datos.reason}.`
    : `Mostrando las primeras ${n} de ${total} filas. Para el total, descargá el Excel.`;
}

/* ── El sondeo ───────────────────────────────────────────────────────────── */

/* Cada dos segundos. Más seguido no acelera nada —la consulta tarda lo que
   tarda— y multiplica las invocaciones de la Lambda. */
export const ESPERA_SONDEO = 2000;

/* El techo. Una corrida que nunca responde no puede dejar el navegador
   preguntando toda la tarde: a los quince minutos se corta y se dice, en vez
   de mostrar «ejecutando» para siempre. */
export const LIMITE_SONDEO_MS = 15 * 60 * 1000;

/**
 * Pregunta por una corrida hasta que termine.
 *
 * `alAvanzar` recibe cada respuesta intermedia para que la pantalla muestre
 * que sigue viva. `cancelado()` se consulta antes de cada vuelta: sin eso,
 * salir de la pantalla deja el sondeo corriendo contra un componente que ya
 * no existe.
 */
export async function seguirCorrida(pedir, runId, {
  alAvanzar = () => {},
  cancelado = () => false,
  espera = ESPERA_SONDEO,
  limite = LIMITE_SONDEO_MS,
  dormir = (ms) => new Promise((r) => setTimeout(r, ms)),
  ahora = () => Date.now(),
} = {}) {
  const arranque = ahora();
  for (;;) {
    if (cancelado()) return { status: 'ERROR', error_message: 'Cancelado.' };
    if (ahora() - arranque > limite) {
      return {
        status: 'ERROR',
        error_message: 'La corrida sigue sin responder después de 15 minutos. '
                     + 'Quedó lanzada: buscala en el Historial más tarde.',
        run_id: runId,
      };
    }
    await dormir(espera);
    if (cancelado()) return { status: 'ERROR', error_message: 'Cancelado.' };
    let d;
    try {
      d = await pedir(`/runs/${runId}`);
    } catch {
      // Un error de red en una vuelta no cancela la corrida: sigue andando en
      // el backend. Se reintenta en la siguiente.
      continue;
    }
    alAvanzar(d);
    if (termino(d?.status)) return d;
  }
}

/* ── Las consultas guardadas ─────────────────────────────────────────────── */

/* El backend usa `report_name` como identificador, así que tiene que ser un
   nombre de código: si alguien escribe «Clientes de Perú», la ruta de borrado
   queda con espacios y acentos. Se valida acá para decirlo al escribir y no
   después de guardar. */
export const FORMA_NOMBRE_CONSULTA = /^[a-z][a-z0-9_]{2,59}$/;

export function nombreDeConsultaValido(nombre) {
  return FORMA_NOMBRE_CONSULTA.test(String(nombre || ''));
}

/**
 * Qué le falta a una consulta para poder guardarse.
 *
 * Se revisa acá y no sólo en el backend para poder decirlo antes de apretar:
 * el error del backend llega como «Error 400» sin explicar cuál de los cuatro
 * campos está mal.
 */
export function faltaParaGuardarConsulta({ report_name, display_name, sql } = {}) {
  const falta = [];
  if (!String(report_name || '').trim()) falta.push('el nombre de código');
  else if (!nombreDeConsultaValido(report_name)) {
    falta.push('un nombre de código válido (minúsculas, números y guión bajo, '
             + 'empezando por letra)');
  }
  if (!String(display_name || '').trim()) falta.push('el nombre visible');
  if (!String(sql || '').trim()) falta.push('el SQL');
  return falta;
}

/* Una consulta guardada que escribe es una consulta que no debería existir:
   este módulo es de lectura sobre Redshift. El backend también lo valida; acá
   se avisa antes de mandarla. */
const ESCRIBEN = /\b(insert|update|delete|drop|truncate|alter|create|grant|revoke)\b/i;

export function pareceEscritura(sql) {
  return ESCRIBEN.test(String(sql || ''));
}

/* ── El análisis del resultado con IA ────────────────────────────────────── */

/* Cuántas filas se le mandan al modelo cuando hay que calcular en el
   navegador. Cincuenta alcanzan para que reconozca la forma del resultado sin
   que el prompt se vuelva impagable. */
export const MUESTRA_IA = 50;

/**
 * Estadísticas de las columnas numéricas de una muestra.
 *
 * Una columna cuenta como numérica si más de la mitad de sus valores lo son:
 * los identificadores que vienen como texto y las columnas mixtas quedan
 * afuera, que es lo que evita que el modelo sume números de cuenta.
 */
export function estadisticas(filas, columnas) {
  const muestra = (filas || []).slice(0, MUESTRA_IA);
  const salida = {};
  for (const c of columnas || []) {
    const nums = muestra.map((f) => Number.parseFloat(f?.[c])).filter((v) => !Number.isNaN(v));
    if (nums.length <= muestra.length / 2 || nums.length === 0) continue;
    const suma = nums.reduce((a, b) => a + b, 0);
    salida[c] = {
      suma, promedio: suma / nums.length,
      min: Math.min(...nums), max: Math.max(...nums),
    };
  }
  return salida;
}

/**
 * El prompt del análisis AML de un resultado.
 *
 * SI EL BACKEND MANDÓ `ai_summary`, MANDA ESE. Lo calcula sobre el dataset
 * COMPLETO; lo que se puede calcular acá es sobre las filas que llegaron, que
 * son como mucho unas miles de un resultado que puede tener cientos de miles.
 * Un promedio de la muestra presentado como el promedio del reporte es un
 * dato falso dentro de un análisis de compliance, así que el alcance se dice
 * en la primera línea del prompt en los dos casos.
 */
export function promptDelResultado({ reporte, columnas, filas, total, resumenBackend = null }) {
  const cols = columnas || [];
  let bloqueStats;
  let bloqueMuestra;
  let alcance;

  if (resumenBackend?.numeric_stats && Object.keys(resumenBackend.numeric_stats).length) {
    bloqueStats = Object.entries(resumenBackend.numeric_stats)
      .map(([c, v]) => `${c}: suma=${v.sum}, promedio=${v.avg}, mín=${v.min}, máx=${v.max}`)
      .join('\n');
    const top = resumenBackend.top_rows || [];
    bloqueMuestra = `LAS ${top.length} FILAS MÁS EXTREMAS (por ${resumenBackend.top_rows_metric || 'la métrica principal'}, `
                  + `de ${resumenBackend.total_rows} en total):\n${JSON.stringify(top, null, 1)}`;
    alcance = `${resumenBackend.total_rows} filas TOTALES — las estadísticas están calculadas `
            + 'sobre el conjunto COMPLETO, no sobre una muestra';
  } else {
    const muestra = (filas || []).slice(0, MUESTRA_IA);
    const stats = estadisticas(filas, cols);
    bloqueStats = Object.entries(stats)
      .map(([c, v]) => `${c}: suma=${v.suma.toFixed(2)}, promedio=${v.promedio.toFixed(2)}, máx=${v.max.toFixed(2)}`)
      .join('\n');
    bloqueMuestra = `MUESTRA (${muestra.length} de ${total ?? (filas || []).length} filas):\n`
                  + JSON.stringify(muestra, null, 1);
    alcance = `${total ?? (filas || []).length} filas en total — las estadísticas salen de una `
            + `MUESTRA de ${muestra.length}, así que son indicativas y no el valor del reporte`;
  }

  return `Eres un analista AML experto. Analizá el reporte "${reporte}" — ${alcance}.

COLUMNAS: ${cols.join(', ')}
MÉTRICAS NUMÉRICAS:
${bloqueStats || 'N/A'}
${bloqueMuestra}

Entregá un análisis AML estructurado con estas secciones:

## 1. VOLUMEN Y MAGNITUD
Total de operaciones, montos USD, distribución temporal y geográfica si aplica.

## 2. PATRONES AML DETECTADOS
Estructuración/smurfing, layering, concentración de beneficiarios, mismatch SWIFT,
velocidad inusual, dispersión sospechosa. Si un patrón NO aparece en los datos, no lo menciones.

## 3. CASOS BORDE Y ALERTAS PRIORITARIAS
Los 3 a 5 casos más sospechosos, con su identificador y el motivo de la alerta.

## 4. COMPORTAMIENTO POR SEGMENTO
Diferencias por país de origen y destino, tipo de cliente, canal de pago.

## 5. RECOMENDACIONES ACCIONABLES
Qué escalar, qué monitorear, si amerita un ROS, y sugerencias de umbral.

Reglas:
- Apoyate SOLO en los datos de arriba. Si algo no está, decí "no hay datos de X".
- Las cifras que uses tienen que salir de los datos, no estimadas.`;
}
