# WatchTower v2 — plan de trabajo

> **Estado**: Fase 0 terminada. Las fases 1 a 8 esperan tres decisiones (§Decisiones).
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
| `estilo/tokens.css` | 33 tokens semánticos, de los 89 colores sueltos del prototipo. Tema claro y oscuro. |
| `estilo/base.css` | Reset, tipografía, las tres animaciones y el shell. Cero colores literales. |
| `dominio.js` | Niveles de riesgo, categorías, estados de caso, las 20 pantallas con su llave de permiso. |
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

## Fase 1 — El armazón

Nada visible para el usuario; todo lo que las 20 pantallas van a dar por hecho.

- Shell: topbar, sidebar con los tres grupos, área de contenido, ruteo.
- Sesión y permisos: `verModulo()` con la misma semántica que v1, para que un
  perfil signifique lo mismo en los dos fronts mientras convivan.
- Capa de API: un solo punto de entrada, con el manejo de error y el
  `actor_email` en un lugar y no en 75.
- Tabla densa como componente: orden, filtro, paginado y export. Es el 70% de
  esta aplicación; si sale bien, catorce pantallas salen casi solas.

**Criterio de salida**: una pantalla vacía que navega, respeta permisos y trae
datos reales de un endpoint.

## Fase 2 — Bandeja de alertas y triage

`dashboard` + `alert` (nueva). La pantalla donde el equipo vive.

Acá se resuelve la decisión del feed en vivo (§Decisiones) y se decide cuál de
las tres variantes de tablero del diseño se construye.

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

## Decisiones abiertas

Las tres bloquean la Fase 1. Ninguna se puede contestar desde el código.

**1. El stack.** React con build, o Alpine como v1.
Recomiendo **React**. El motivo no es preferencia: v1 es un `index.html` de
13.606 líneas y 751 KB con 324 funciones en un solo archivo, y ese archivo ya
produjo dos bugs este mes — cinco pestañas en blanco por un `<div>` de más, y
un selector de equipo vacío. Veinte pantallas no entran ahí. Alpine evita el
paso de build, pero el paso de build no es el problema que tenemos.

**2. Cuál de las tres variantes de tablero.** El diseño propone Live feed,
Command desk y Triage lanes. Son tres modelos de trabajo distintos, no tres
estéticas. Hay que elegir mirando cómo trabaja el equipo hoy.

**3. El feed en vivo: ¿es real?** Si es real hace falta polling o websocket y
el backend tiene que soportarlo. Si se refresca al entrar, la animación de
"latido" es decorativa y conviene sacarla — un punto que late diciendo "en
vivo" sobre datos de hace veinte minutos es peor que no tenerlo.

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
