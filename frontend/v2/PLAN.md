# WatchTower v2 — plan de trabajo

> **Estado**: Fases 0 y 1 terminadas. Las tres decisiones que las bloqueaban
> están tomadas (§Decisiones). Sigue la Fase 2.
> **Regla que manda sobre todo lo demás**: v1 sigue en producción y no se toca.
> v2 se construye en paralelo, en su propia URL, hasta que esté completo.

---

## El orden, y por qué es este

El plan original empezaba por la vista de CX: una pantalla chica, de sólo
lectura, para probar el stack de punta a punta con poco riesgo. Benjamín pidió
darlo vuelta — **primero extraer todo lo que le da vida al front nuevo, después
diseñar todo, y CX al final**.

Tiene sentido y cambia el modo de fallar del proyecto. El piloto servía para
descubrir temprano que el stack no cierra; extrayendo primero, eso se descubre
igual pero contra el vocabulario completo en vez de contra una pantalla. Lo que
se pierde es tener usuarios reales sobre v2 en la semana uno. Lo que se gana es
no cristalizar decisiones de arquitectura mirando la pantalla más simple de las
veinte — la vista de CX no tiene tablas densas, ni kanban, ni feed en vivo, y
es exactamente el caso que NO representa a esta aplicación.

CX queda última también por una razón práctica: **el perfil de sólo lectura ya
está en producción en v1** (PR #65) y el equipo ya tiene acceso. No hay nadie
esperando esa pantalla.

---

## Fase 0 — Extracción del vocabulario ✅

Sacar del prototipo `Watchtower Hub v5.dc.html` todo lo que es decisión, y
dejar afuera todo lo que es andamio.

**Lo que se hizo.**

| Archivo | Qué contiene |
|---|---|
| `src/estilo/tokens.css` | 33 tokens semánticos, de los 89 colores sueltos del prototipo. Tema claro y oscuro. |
| `src/estilo/base.css` | Reset, tipografía, animaciones y el shell. Cero colores literales. |
| `src/dominio.js` | Niveles de riesgo, categorías, estados de caso, las 20 pantallas con su llave de permiso. |
| `tests/test_tokens.py` | 38 pares de contraste medidos en los dos temas. |

**Lo que se verificó contra el repo, no contra el diseño.**

- Los 10 flags del prototipo y sus pesos: **idénticos** a `lambda/aml_individual.py`.
  Cero diferencias.
- El catálogo de reportes: 1 a 1 con los 31 de `handler.py`.
- Los cortes de nivel de riesgo (≥10 / 6-9 / 3-5 / <3): salen del backend.

**Lo que se decidió NO copiar.**

- `support.js` es el runtime de Claude Design (React + `<x-dc>` + `{{ }}`), con
  **cero llamadas de red**. Es una maqueta, no código de partida.
- El tema oscuro del prototipo reescribe el DOM en caliente con dos tablas de
  sustitución. Acá son variables CSS.
- Los pesos de los flags y el catálogo **no se hardcodean**, aunque hoy
  coincidan. Coincidir hoy no es estar sincronizado: el día que alguien cambie
  un peso, una pantalla titulada "Flags y pesos" estaría mintiendo y nadie se
  enteraría hasta que un analista defienda un caso con un número que no es.

**Lo que la extracción encontró y hubo que arreglar.** Cuatro colores del
prototipo no llegan al mínimo de contraste de WCAG AA sobre su propio fondo:

| Token | Prototipo | Contraste | Corregido |
|---|---|---|---|
| `--texto-mute` | `#A4A3A4` | 2,5:1 | `#6F6F6F` |
| `--nivel-critico-texto` | `#FF2970` | 3,6:1 | `#E8004D` |
| `--nivel-alto-texto` | `#F26B43` | 3,0:1 | `#D73D0F` |
| `--nivel-bajo-texto` / `--g66-teal-texto` | `#009FA2` | 3,2:1 | `#008285` |

El gris es el más grave: el prototipo lo usa **112 veces**, a 10 px, en la
pantalla que un analista mira ocho horas. Los colores de badge no cambian —
sólo su versión como letra.

---

## Fase 1 — El armazón ✅

Nada visible para el usuario; todo lo que las 20 pantallas van a dar por hecho.

| Pieza | Dónde | Qué resuelve |
|---|---|---|
| Shell | `src/shell/`, `src/App.jsx` | Topbar, sidebar con los tres grupos, contenido, tema claro/oscuro. |
| Ruteo | `src/ruta.js` | Por hash. GitHub Pages no sabe devolver `index.html` para una ruta que no existe como archivo: con rutas de verdad, recargar en cualquier pantalla daría 404. |
| Sesión | `src/sesion.js` | Firebase Auth + `wt_roles`, el mismo backend de identidad que v1. |
| Permisos | `src/permisos.js` | `verModulo()` con la semántica exacta de v1, para que un perfil signifique lo mismo en los dos fronts mientras convivan. |
| API | `src/api.js` | Un punto de entrada. El corte de sólo lectura y el `actor_email` en un lugar y no en 75. |
| Tabla densa | `src/comun/` | Orden, filtro, paginado y export. Catorce de las veinte pantallas son esto. |
| Banco de pruebas | `src/banco.jsx` | El shell con datos inventados y sin login, para ver qué ve cada perfil sin entrar a producción. No se publica. |

**Criterio de salida**: cumplido. `#/reports` trae el catálogo real de la API,
navega, y respeta permisos.

**Tres cosas que salieron de construirlo, no de planificarlo.**

1. **El perfil no puede viajar como valor al cliente de API.** Llega de
   Firestore *después* del primer render; congelándolo, el cliente se queda
   con el perfil mínimo —que es de lectura— y bloquea todo lo que el usuario
   escriba en el resto de la sesión. Va como función. Hay un test que lo fija.
2. **`comoNumero('$ 1.234.567')` devolvía `null`**, o sea que una columna de
   montos se habría ordenado como texto sin que nadie lo notara. Lo cazó un
   test. De paso quedó documentada una ambigüedad que no se puede resolver
   mirando el texto: `"1.234"` puede ser mil doscientos o uno coma doscientos.
3. **El build de v2 no puede hacer fallar el despliegue de v1.** Va en su
   propio paso con `continue-on-error`: un error en una pantalla a medio
   hacer no puede dejar al equipo sin poder publicar lo que está en
   producción. Si no hay build, v2 publica una página que lo dice.

## Fase 2 — Bandeja de alertas y triage

`dashboard` + `alert` (nueva). La pantalla donde el equipo vive.

Se construye como **Command desk**: la fila de indicadores arriba —abiertos,
vencidos de SLA, por analista— y la tabla de alertas abajo, con el triage en
su propia pantalla. Los datos se cargan al entrar y con un botón de refrescar;
no hay feed en vivo (§Decisiones).

## Fase 3 — Casos

`cases`, `kanban`, `ficha`, y el semáforo de SLA que ya existe en v1
(`lambda/sla_casos.py`: 36 h para recontactar, 72 h para cerrar). Los plazos se
piden en `sla_config`, no se escriben en el front.

## Fase 4 — Análisis

`reports`, `individual`, `institucional`, `history`, `whitelist`, `informe`,
y `flags` (nueva). **`flags` depende de `GET /flags`, que no existe** — ver
Pendientes.

## Fase 5 — Relevo y embargos

`relevo`, `embargos`. Son los dos módulos con más lógica propia y los que menos
se parecen a una tabla.

## Fase 6 — Administración

`admin_users`, `admin_auto`, `admin_cluster`, `audit`, y `salud` (nueva).

## Fase 7 — ROS / UAF

Pantalla nueva sin equivalente en v1. Antes de construirla hay que definir con
compliance qué es exactamente un ROS acá: el diseño muestra una pantalla, no un
proceso.

## Fase 8 — El corte

v2 pasa a ser el front. Big bang, en su propia URL hasta ese momento. v1 queda
accesible un tiempo por si algo falta.

## Fase 9 — Vista CX *(la que era Fase 1)*

Sólo casos abiertos, buscables por email o customer id, nada más.

Hoy existe en v1 como perfil de sólo lectura, así que esto es portarla — y para
cuando llegue el turno, el armazón de permisos de la Fase 1 ya la hace casi
gratis.

---

## Decisiones tomadas

**1. El stack: React con build.** v1 es un `index.html` de 13.606 líneas y
751 KB con 324 funciones en un solo archivo, y ese archivo produjo dos bugs
este mes — cinco pestañas en blanco por un `<div>` de más, y un selector de
equipo vacío. Veinte pantallas no entran ahí. Vite + React 19, sin TypeScript
por ahora.

**2. El tablero: Command desk.** Indicadores arriba, tabla abajo. De las tres
variantes del diseño es la que supone que lo primero que hace falta es el
estado general y después bajar al detalle.

**3. El feed se refresca al entrar, no solo.** Sin polling y sin websocket. Se
sacó la animación `wt-pulso` del prototipo, que era el punto de "en vivo"
latiendo: sobre datos de hace veinte minutos no es decoración inofensiva sino
una afirmación falsa sobre su frescura, justo en la pantalla donde se decide
a quién investigar. Está en el historial de git por si el feed se vuelve real.

---

## Pendientes que no son de v2 pero lo bloquean

**`GET /flags`** — no existe. Los pesos F1–F10 viven sólo en
`lambda/aml_individual.py` (`FLAG_WEIGHTS` / `FLAG_LABELS`). Sin el endpoint,
la pantalla "Flags y pesos" de la Fase 4 los tendría que hardcodear. Es una
tarea chica de backend: exponer esas dos constantes.

**La línea de CORS** — la API sólo permite el header `content-type` y los
métodos GET/POST/DELETE/OPTIONS. Sin `authorization` no hay auth real en v2, y
`compliance-admin` **no puede cambiarlo**: `AccessDenied` en
`apigateway:PATCH`. Necesita a alguien con ese permiso.
