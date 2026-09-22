# WatchTower v2 — plan de trabajo

> **Estado**: las ocho fases terminadas **y la paridad con v1 cerrada**. v2
> hace todo lo que hace v1. Falta **dar el corte**, que es una línea y una
> decisión.
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
| `tests/test_tokens.py` | 112 pares de contraste medidos en los dos temas. |

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

**Lo que la extracción encontró y hubo que arreglar.** Colores del prototipo
que no llegan al mínimo de contraste de WCAG AA:

| Token | Prototipo | Contraste | Corregido |
|---|---|---|---|
| `--texto-mute` | `#A4A3A4` | 2,5:1 | `#6C6C6C` |
| `--nivel-critico-texto` | `#FF2970` | 3,6:1 | `#D80048` |
| `--nivel-alto-texto` | `#F26B43` | 3,0:1 | `#C7390E` |
| `--nivel-bajo-texto` / `--g66-teal-texto` | `#009FA2` | 3,2:1 | `#00797C` |
| `--estado-ok-texto` | `#15803D` | 4,4:1 | `#157D3C` |

El gris es el más grave: el prototipo lo usa **112 veces**, a 10 px, en la
pantalla que un analista mira ocho horas. Los colores de badge no cambian —
sólo su versión como letra.

**El test se corrigió dos veces, y la segunda importa más que la primera.**
Al principio listaba los pares a mano y medía todo contra blanco. Pero el
texto también cae sobre `--superficie-3`, el gris de las cabeceras y el fondo
de las insignias, y ahí cinco colores que pasaban raspando reprobaban. Ahora
el test **deriva sus propios pares**: todo token `-texto` contra todas las
superficies, en los dos temas. Son 112 pares, y un token nuevo queda cubierto
sin que nadie se acuerde de agregarlo.

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

## Fase 2 — Bandeja de alertas y triage ✅

`dashboard` + `alert` (nueva), como **Command desk**: indicadores arriba,
tabla abajo, triage en su propia pantalla. Los datos se cargan al entrar y con
un botón de refrescar; no hay feed en vivo (§Decisiones).

**LO MÁS IMPORTANTE QUE SALIÓ DE ESTA FASE: hay dos puntajes distintos y los
dos se llaman `risk_score`.**

| | Análisis individual | Alertas transaccionales |
|---|---|---|
| Dónde | `lambda/aml_individual.py` | `row_data.risk_score`, del SQL de cada reporte |
| Escala | 0–19 (suma de diez banderas) | 0–100 |
| Cortes | ≥10 crítico · 6 alto · 3 medio | ≥75 P1 · ≥50 P2 · P3 (`handler.py:699`) |

Medido sobre las 122 alertas activas, los puntajes van de 0 a 87. Aplicarles
los cortes del análisis individual —que es lo que habría pasado usando el
`nivelDe()` que ya existía— **pintaría 109 de 110 como CRÍTICO**, y el color
dejaría de decir nada justo en la pantalla donde se decide a quién mirar
primero. Ahora cada escala tiene su función y hay un test que las cruza.

**El diseño dibuja tres columnas que los datos no pueden llenar.** El
prototipo muestra monto en USD, país destino y las banderas F1–F10 de cada
alerta. De esas: el país y las banderas **no existen** en los datos de
alertas, y el monto existe con **un nombre distinto en cada reporte** —cuatro
campos repartidos en seis reportes, y uno sin monto. La columna de monto usa
un mapa explícito por reporte y muestra de qué campo salió; las otras dos no
se dibujaron. Inventarlas habría quedado lindo y vacío.

**Un indicador no puede mostrar cero cuando no sabe.** Se vio al probar con la
carga fallando: la fila mostraba «0 alertas activas · 0 sin caso», que dice
que no hay trabajo pendiente. En esta pantalla esa es la diferencia entre
irse tranquilo a casa y no. Ahora muestra un guión mientras carga y si falla.

**Qué se puede hacer desde el triage**: asignar (a uno mismo o a otro),
dejar una nota, y marcar como revisada —con confirmación, porque saca la
alerta de la bandeja de todos—. La fila cruda del reporte se muestra entera:
es la evidencia de por qué la alerta existe, y elegir qué campos mostrar sería
decidir por el analista qué es relevante en un reporte que todavía no existe.

## Fase 3 — Casos ✅

Cuatro pantallas: `cases` (lista con semáforo), `kanban` (tablero con
arrastre), `caso` (detalle) y `ficha` (el consolidado del cliente).

**EL PLAZO NO SE CALCULA EN EL FRONT.** Lo calcula `lambda/sla_casos.py` y
llega hecho en los campos `sla_*`, con los umbrales en `sla_config`. Si el
front lo recalculara habría dos definiciones del mismo plazo, y un día la
pantalla diría «en plazo» sobre un caso que el sistema considera vencido.

**EL SEMÁFORO ESTÁ ENTERO EN ROJO, Y ESO ES UN DATO.** Medido sobre los 89
casos: de 69 con el reloj corriendo, **los 69 están vencidos**. Ninguno verde,
ninguno amarillo — el más nuevo tiene 6,8 días y el plazo es 3. La mediana de
días abierto es 13,9 y el máximo 47. De los 15 cerrados, **1 cerró dentro del
plazo**; la mediana de cierre es 14,9 días.

Una lista donde las 69 filas son rojas se lee igual que una lista sin colores,
así que la pantalla lo dice arriba en vez de fingir un gradiente que no
existe. Lo que sí ordena hoy es *hace cuánto* venció cada uno, y por eso la
insignia muestra eso y no sólo «Vencido».

**Tres cosas que aparecieron al mirar los datos, no el diseño.**

1. **La columna «Cliente» mostraba el título del caso.** Sólo 41 de 89 casos
   traen `entity_name`, así que caía al `title` — que en 72 de 89 es
   «Caso: Alerta: \<reporte\>», 22 textos distintos para 89 casos. Se veía
   como un nombre de cliente sin identificar a nadie. Ahora manda el id, que
   está siempre, y el nombre va debajo cuando existe.

2. **`GET /cases/{id}` no devuelve los campos `sla_*`.** Los calcula
   `GET /cases`, sobre la lista. El detalle pide las dos cosas y las junta —
   76 KB de más, barato al lado de duplicar la regla del plazo. *Mejora de
   backend pendiente: que el detalle devuelva los `sla_*` como la lista.*

3. **«Triage de alerta» estaba en el menú y siempre daba error.** Las
   pantallas de detalle necesitan un id; llegar desde el menú no les da uno.
   Ahora llevan `enMenu: false`: siguen siendo rutas con su permiso, pero no
   aparecen en el menú. Un ítem que siempre lleva a un error no es un atajo.

**La ficha del cliente tarda 11 segundos** (consulta Redshift en vivo; el
techo de API Gateway son 30). Un «Cargando…» sin más se lee como que se
colgó, y la gente recarga — lo que dispara otra consulta. El aviso dice
cuánto tarda y pide no recargar.

**El arrastre del kanban mueve la tarjeta antes de que el servidor conteste,
y la devuelve si falla.** Esperar por tarjeta haría el tablero inservible
para ordenar 89 casos; dejarla movida cuando el guardado falló sería peor,
porque diría que se hizo algo que no se hizo. Cerrar pregunta: es la única
de las cuatro columnas que cambia el sentido del caso y deja `closed_at`.

## Fase 4 — Análisis ✅

Seis pantallas nuevas más `reports`, que ya estaba: `history`, `whitelist`,
`institucional`, `individual`, `informe` y `flags`.

**SE AGREGÓ `GET /flags` AL BACKEND, Y ESO DESTAPÓ ALGO.** La pantalla de
banderas necesitaba la matriz F1–F10 con sus pesos, que sólo vivía en
`aml_individual.py`. Al escribir el endpoint era tentador devolver los cortes
de nivel escritos a mano (10 / 6 / 3) — y eso habría creado el mismo problema
que el endpoint venía a resolver, porque esos cortes estaban como **literales
sueltos dentro del `if`** que clasifica el score. Ahora son
`CORTES_NIVEL` en `aml_individual.py`, el `if` los usa y el endpoint los lee:
una sola definición, con un test que comprueba que cambiarla cambia lo que ve
el front.

✅ **Desplegado el 2026-09-21.** `GET /flags` responde en producción con las
10 banderas, máximo 19 y los cortes leídos del módulo de scoring.

Antes de desplegar se comprobó que producción era **idéntica a `main` byte
por byte**, que el paquete nuevo cambiaba **sólo dos de sus 5.053 archivos**,
y que esos dos diffs eran los revisados. Después: los 13 endpoints que ya
andaban siguen respondiendo igual, el código desplegado coincide con el
construido, y no hay errores en los logs de ninguna de las dos Lambdas.

La pantalla igual conserva su degradación —si el endpoint dejara de estar,
avisa en vez de mostrar pesos de memoria—, porque el problema que evita no
desaparece por estar desplegado hoy.

**Qué hace cada pantalla y qué decidió.**

| Pantalla | Qué resuelve |
|---|---|
| `history` | Las últimas 50 corridas con estado, duración y descarga. Los parámetros se resumen: una corrida del análisis individual trae **891 ids en un solo campo** y mostrarlos crudos revienta la fila. |
| `whitelist` | La vigencia es el dato, no un adorno: una entrada vencida significa que el cliente volvió a la bandeja sin que nadie lo anuncie. Se calcula contra la hora real y avisa la semana antes. |
| `institucional` | Empresas, reglas y alertas en pestañas, las tres cargadas en paralelo. Si una falla se dice **cuál**: con tres llamadas, «hubo un error» no dice qué pestaña muestra datos viejos. |
| `individual` | Es asíncrono y se nota: lanza una corrida y pregunta cada 6 s. Avisa cuando el estado es `RESUMING`, que es el cluster de Redshift despertando. |
| `informe` | Filtros y PDF. **No calcula nada**: el informe se imprime y se manda, y dos versiones del mismo número —una en pantalla, otra en el PDF— es lo que no puede pasar. |
| `flags` | La matriz, los cortes, y el aviso de que esta escala (0–19) no es la de las alertas (0–100). |

**Un defecto propio que salió al mirar la pantalla**: el endpoint ordenaba
las banderas por código como texto, y `"F10" < "F6"`. F10 quedaba en el medio
de la lista y hacía dudar de si faltaba alguna. Se ordena por el número.

## Fase 5 — Relevo y embargos ✅

Los dos módulos con más lógica propia, y los que menos se parecen a una tabla.

**LO PRIMERO QUE SE VE EN RELEVO ES SI LOS ENVÍOS ESTÁN PRENDIDOS.** Hoy los
ocho interruptores de salida están apagados. Una bandeja con 237 casos
«listos para pedir» que en realidad no puede pedir nada es una trampa: el
analista trabaja, no pasa nada, y ningún error lo explica. El aviso va arriba
de todo y en rojo.

Prender un envío manda correos a clientes reales, así que ese interruptor —y
sólo ese— pide confirmación escrita con lo que va a pasar. Verificado: al
cancelar no sale ninguna petición.

**LAS ETAPAS NEGATIVAS NO SON PASOS ATRÁS.** El circuito va de −2 a 4, y los
negativos son otra cosa: −1 es «falta un dato» (no se ubicó al cliente, no
tiene correo, no se entendió el pedido) y −2 es «no hay nada que hacer».
Medido: **113 de 392 casos están en −1**. Mezclarlos con el carril feliz los
haría parecer atrasados cuando en realidad están trabados por una razón que
no se arregla trabajando el caso, sino arreglando el dato. Por eso tienen su
propio indicador y su propio filtro.

**Los estados que se fijan a mano son nueve, no trece.** `casos.py` deja
afuera los cuatro diagnósticos a propósito: ponerlos a mano tapa el
diagnóstico en vez de arreglarlo. El front repite esa lista para armar el
desplegable — y por eso existe el test de sincronía (abajo).

**En embargos, la previsualización no es un adorno.** Un oficio mal leído
—columnas corridas, un PDF sin capa de texto— produce una respuesta al
juzgado con los documentos equivocados. Ver qué se entendió antes de ejecutar
es el único control entre el archivo y la respuesta.

Y una distinción que la pantalla insiste en marcar: **una fila descartada no
es un «no cliente»**. Es una fila que no se pudo leer, así que a esa persona
nunca se la buscó. Contarlas juntas haría creer que se revisó a alguien a
quien no se revisó.

El archivo sube **directo a S3** con una URL prefirmada: un oficio escaneado
pesa varios MB y API Gateway corta el cuerpo en ~6 MB.

### El test de sincronía entre los dos idiomas

Hay tres cosas que el front repite del backend porque no hay endpoint que las
dé: los estados manuales de relevo, los cortes de nivel y el plazo de
respaldo. `tests/test_sincronia.py` lee los archivos de Python y los de
JavaScript y los compara.

No es un test de estilo. Si el backend agrega un estado y el front no lo
tiene, la opción no aparece y nadie se entera; si el front tiene uno que el
backend rechaza, el usuario lo elige y recibe un error que no entiende. Las
dos fallas son silenciosas para quien las sufre.

Se comprobó que puede fallar: **siete mutaciones, siete cazadas**.

## Fase 6 — Administración ✅

Cinco pantallas: usuarios y permisos, automatización, cluster, auditoría y
salud del módulo (nueva).

**HAY DOS LISTAS DE USUARIOS Y NO SON LA MISMA.** `GET /users` es el CRM
—quién existe, su equipo— y Firestore `wt_roles` es el perfil —rol y
módulos—. Alguien puede estar en una y no en la otra, y las dos ausencias
duelen distinto: sin perfil entra y no ve nada; sin usuario de CRM nadie le
puede asignar un caso. La pantalla las cruza y marca las dos.

**AL GUARDAR UN PERFIL NO SE PISAN LOS MÓDULOS DE v1.** Los dos fronts
escriben en la MISMA colección y manejan listas distintas: v1 tiene
`pendientes`, `queries`, `busqueda` y `dashboard`, que en v2 no existen como
pantallas. Si v2 guardara sólo lo que conoce, editarle el equipo a alguien
desde acá le sacaría en silencio accesos que usa a diario. Se conservan las
claves desconocidas, y hay tests que lo fijan.

De paso, la lista de módulos de v2 **se deriva de `PANTALLAS`** en vez de ser
una lista aparte. v1 mantiene su propio `ALL_MODULES` y ya se desfasó.

**La pantalla de salud es nueva y responde a un problema concreto.** Media
docena de cosas pueden estar apagadas o caídas sin que ninguna pantalla lo
diga —el cluster pausado, los envíos de relevo en OFF, la ingesta detenida,
la priorización automática apagada, `GET /flags` sin desplegar— y cada una se
nota tarde y en otro lado: «no me llegan casos nuevos», «el reporte no
corre», «le escribí al cliente y no le llegó».

Están todas juntas y **cada una dice qué se rompe si está así**. Un tablero
de luces que no lo explica no sirve. Y no arregla nada: cada cosa se cambia
en su pantalla, porque el objetivo es entender antes de tocar.

**Un defecto que salió al verificar, y del mismo tipo que el de la bandeja.**
Con Firestore caído, la pantalla de usuarios afirmaba «12 personas del CRM
sin perfil: si entran, no ven nada». Era falso —sí tienen perfil, lo que
falló fue la lectura— y era una acusación sobre doce personas concretas.
Ahora dice que no pudo leerlos y no afirma nada.

### Las pantallas se cargan a demanda

Son veinte y cada persona usa tres o cuatro. Importándolas todas por
adelantado, entrar a ver una alerta descargaba también el tablero de
embargos y la auditoría: **907 kB en un solo trozo**, y el build avisaba en
cada corrida. Con `lazy` cada pantalla viaja cuando se abre.

La carga inicial bajó de 263 a **228 kB comprimidos**, y ahí se queda: las
fases que vienen ya no la engordan. El piso son los 152 kB de Firebase, que
hace falta para el login.

## Fase 7 — ROS / UAF ✅

El registro de Reportes de Operación Sospechosa. Todo nuevo: no existía nada
en el backend —ROS sólo aparecía como una *recomendación* en el informe de
análisis individual— así que entra el módulo, los endpoints y la pantalla.

**ESTE MÓDULO NO REPORTA, LLEVA EL REGISTRO.** El envío al regulador es
manual, por sus canales. Decirlo en la pantalla no es una formalidad: sin
eso, alguien marca «enviado» creyendo que el sistema lo mandó.

**LA DISTINCIÓN QUE ORDENA TODO EL MÓDULO.** El sistema arma los **hechos**
—sujeto, alertas vinculadas, período, montos— porque ya están en el caso y
copiarlos a mano es como se cometen errores. La **narrativa** la escribe una
persona: un ROS es una afirmación legal firmada por el oficial de
cumplimiento, y un texto generado que alguien firma sin leer es exactamente
el accidente que hay que evitar. El sistema no la redacta ni la sugiere.

**Lo que se decidió con vos**, frente a lo que proponía el prototipo:

| | Prototipo | Lo que se hizo |
|---|---|---|
| Reguladores | cinco (sumaba MX y BR) | **tres**: UIF-AR, UAF-CL, UIAF-CO |
| Plazos | cuenta regresiva por reporte | **ninguno** — el campo `vence_at` queda vacío para que agregarlos después no obligue a rehacer el modelo |
| Servicio externo | — | registro propio ahora; `origen` y `externo_id` son la costura para cuando exista |

**El ciclo de vida es lo que se probó de verdad.** Borrador → revisión legal
→ enviado, más «descartado» —decidir que algo NO se reporta es tan
registrable como decidir que sí—. Cuatro propiedades que no se negocian, con
test cada una:

- un ROS **enviado no vuelve atrás**: fingir que no salió es falsear el
  registro, y para corregirlo se emite otro, que es como funciona con las UIF;
- **no se envía sin narrativa**: lo reportado sería un documento vacío;
- **no se salta la revisión**;
- **todo cambio deja rastro con autor**: un registro sin autor no prueba nada.

**Dos cosas que salieron de mirar y no de escribir.**

1. `build_lambda.sh` copia los archivos **uno por uno**, así que `ros.py` se
   habría quedado fuera del paquete y los endpoints darían un 503 con cara de
   problema de infraestructura. Ahora hay un test que compara lo que la API
   importa con lo que el script copia — siete líneas, y caza el próximo
   olvido.
2. En la pantalla, entre los montos aparecía `avg_ticket_usd_7d` con USD 9,15
   al lado de un total de USD 704. Un promedio **no es un monto movido**, y
   los dos juntos en una lista titulada «montos», dentro de un documento que
   lee un regulador, invitan a leerlos como cosas del mismo orden. Se excluyen
   los promedios, máximos y ratios.

## Fase 8 — El corte ✅ *(el mecanismo; falta apretar el botón)*

**LO PRIMERO FUE MEDIR QUÉ SE PERDÍA.** Un corte a lo grande sin saberlo es la
forma más rápida de romperle el día al equipo. v1 tiene 14 pestañas y v2 tenía
19 pantallas, pero no eran las mismas: al cruzarlas aparecieron **cinco cosas
de v1 sin equivalente**.

| Faltaba | Qué era | Estado |
|---|---|---|
| Dashboard AML | 559 líneas · 8 gráficos · la pantalla de entrada | ✅ construida |
| Ya revisadas | Las alertas resueltas; sin esto, lo revisado desaparece | ✅ conmutador en la bandeja |
| Pendientes | Lo que alguien te asignó a mano | ✅ construida |
| Búsqueda | Alertas y casos de una entidad | ✅ construida |
| Queries | Los reportes a medida | ✅ construida |

Ahora hay **un test que vigila la cobertura**: compara los módulos de permisos
que v1 puede otorgar con los que v2 tiene como pantalla. Si alguien agrega uno
en v1, avisa. Es el test que responde «¿v2 ya reemplaza a v1?».

**Los gráficos se dibujan en SVG a mano.** v1 usa Chart.js, ~200 kB para ocho
barras y dos líneas — más que todas las pantallas de v2 juntas. Son cien
líneas, salen con los tokens del tema y funcionan en oscuro sin una paleta
aparte. Y **el eje siempre arranca en cero**: una barra que empieza en 90 hace
que una diferencia del 2% parezca del 200%.

### Cómo se da el corte

Una variable en el workflow:

```yaml
env:
  FRENTE_PRINCIPAL: v1    # ← cambiar a v2 y listo
```

| | `v1` (hoy) | `v2` |
|---|---|---|
| `/` | WatchTower actual | Front nuevo |
| `/v1/` | redirige a `/` | WatchTower actual |
| `/v2/` | Front nuevo | redirige a `/` |

**Los dos se publican siempre.** Lo único que cambia es cuál atiende la
dirección que la gente tiene en el marcador, y la carpeta del que quedó
principal redirige a la raíz — así ningún enlace se rompe en ninguna
dirección. La redirección **conserva el hash**, que es lo que se pierde en
silencio: v2 rutea con `#/casos` y perderlo dejaría a todos en el inicio.

Volver atrás es cambiar esa línea. No hay migración ni datos que mover: los
dos fronts hablan con la misma API y leen la misma identidad.

Dos guardas más: con `FRENTE_PRINCIPAL=v2` el despliegue **se corta** si v2 no
compiló —publicar la raíz sin el front principal es peor que no publicar—, y
la config de la raíz pasa a ser la de v2, sin la clave de Gemini que v2 no usa.

### ⚠️ Lo que falta antes de apretar

Nada de v2 se probó **con una sesión real**. El banco de pruebas entra sin
Google y con la escritura bloqueada a propósito, así que no se ejercitó:

- el login con Google y la lectura del perfil de Firestore;
- **ninguna escritura** contra producción —asignar, cambiar estados, notas,
  interruptores, embargos—;
- la pantalla de flags, que necesita desplegar `GET /flags`.

Eso no se puede hacer desde acá sin tocar datos reales del equipo. Lo sensato
es entrar a `/v2/` con una cuenta de verdad, trabajar un rato, y recién
entonces cambiar la línea.

## Fase 8.5 — La paridad ✅

No estaba en el plan y tuvo que estar. Al mirar v2 terminado apareció lo
obvio: las ocho fases construyeron las veintitantas pantallas, pero cada una
se escribió mirando a v1 y quedándose con lo principal. **Lo secundario se
perdió en silencio.** Medido: v1 usaba 103 rutas de la API y v2 usaba 47.

El detalle del caso tenía 5 de las 17 acciones de v1. La ficha del cliente
había perdido cuatro secciones enteras —cuyos datos ya llegaban en la misma
respuesta y no se dibujaban—. Y v2 no podía ejecutar un solo reporte.

### El guardián

Lo que hace que esto no vuelva a pasar es `tests/test_paridad.py`. Lee las
rutas que v1 usa **de su propio HTML** —no de una lista escrita a mano, que se
desactualiza al primer commit— y las que usa v2, y exige que la diferencia
esté declarada con su motivo.

Falla en las dos direcciones, y la segunda es la que importa: si se declara
algo que ya está portado, también falla. Sin eso la lista se pudre en vez de
vaciarse. Se vació.

Hoy `PENDIENTES` tiene dos entradas y ninguna es una función que falte:
`/roles` (v2 lee Firestore) y `/cluster/wake` (v2 lo llama como
`/cluster/{accion}`).

**A partir de acá el test cambia de oficio**: medía cuánto faltaba, ahora mide
que no se pierda nada. Si alguien toca una pantalla y se lleva puesta una
llamada, lo dice en el acto.

### Cuatro defectos que aparecieron en el camino

Ninguno se veía compilando. Los cuatro salieron de mirar el código contra el
backend o la pantalla contra producción:

**`'Envío internacional'.includes('nacional')` es verdadero.** El paso 4 del
análisis individual clasifica cada transacción con eso, así que **en v1 todas
las internacionales se clasifican como nacionales**: la hoja «Internacionales»
sale siempre vacía y las internacionales terminan en la otra con las columnas
del motor en blanco, indistinguibles de una nacional que no cruzó. v2 descarta
«internacional» primero, y hay un test de sincronía contra el CASE del SQL.

**Los avisos de la ficha se pintaban todos iguales.** El mapa de tonos tenía
`alerta`/`aviso`/`ok`, nombres que el backend nunca emitió —manda `alto` y
`medio`— así que los dos caían en el respaldo. Un cliente con plata devuelta se
veía como uno con una nota cualquiera, que es justo la distinción que el aviso
existe para hacer.

**La lista de extensiones de adjunto no coincidía con la del backend.** El
front dejaba subir cuatro que el backend rechaza: el analista esperaba una
subida de 40 MB para recibir el error.

**La bandera de «¿sigue montada la pantalla?»**, escrita a mano en cuatro
pantallas, estaba mal de las dos formas posibles: tres la apagaban al
desmontar sin encenderla al montar —React remonta en desarrollo, así que
quedaba apagada para siempre y el sondeo se cancelaba antes de la primera
vuelta—, y la cuarta no la apagaba nunca. Ahora es `useVivo()`, una vez y
bien. Este no se veía en la consola: no tira ningún error. Se vio en la red,
porque el disparo salía y la cosecha no.

### Y uno de producción, encontrado al pasar

Cinco correos de un caso no salían con un `UnicodeEncodeError` en la posición
56. La causa: en el campo del correo había quedado guardado un motivo de
bloqueo en vez de una dirección, `smtplib` lo escribe crudo en `RCPT TO:<...>`
y codifica ese comando en ASCII. La `ú` de «según» cae justo ahí.

Se repitió cinco veces porque «Reenviar» prellena con el correo del pedido
anterior: una vez que el valor malo entró, se alimentaba solo. Arreglado en el
backend (`_send_email`, el único lugar por donde sale todo correo), en v1 y en
v2. Está en `main` y desplegado.

---

## Fase 9 — Vista CX ✅

Una caja de búsqueda y una respuesta. Es la pantalla para atender una llamada:
el cliente pregunta por qué le pidieron papeles, y de este lado hay que saber
si tiene algo abierto sin leer una tabla de doce columnas.

En v1 «CX» no es una pantalla: es el rol `lectura` mirando la tabla de casos
completa. Esto es una pantalla propia, y las decisiones que la hacen distinta
son tres.

**Busca en memoria, no contra la API.** `GET /search/entity` busca por
identificador, pero el correo del cliente **no está** en `/cases` ni en el
nivel de arriba de `/alerts`: vive dentro de `row_data`, que además llega como
texto JSON. Se arma un índice con las dos listas —73 casos abiertos y 122
alertas— y se busca sobre eso. Instantáneo, y anda con Redshift pausado.

**Contesta tres cosas, no dos.** «Tiene N casos abiertos», «figura pero no
tiene nada abierto» y «no figura». Las dos últimas parecen lo mismo y no lo
son: una dice que lo miramos y está limpio, la otra que nunca lo vimos.
Juntarlas hace que CX afirme lo primero cuando sólo puede afirmar lo segundo.

**No contesta mientras carga.** Buscar sobre un padrón a medio leer devuelve
«no figura», y de este lado hay alguien por decirle a un cliente que no aparece
en el sistema. Es la peor forma de equivocarse que tiene esta pantalla y es
silenciosa: la respuesta se ve igual de segura que una buena. Se descubrió
probándola contra producción — contestó «no figura» sobre un cliente que sí
tenía un caso abierto.

**Lo que no muestra, a propósito**: el motivo de la alerta, el puntaje, el
reporte que la disparó, el analista asignado. Nada de eso se le dice a un
cliente, y tenerlo en pantalla mientras se habla con él es cómo se filtra sin
querer. La pantalla lleva escrito qué se puede decir y qué no.

El id y el correo se buscan **enteros**; el nombre, por partes. Buscar «370» y
que aparezca medio padrón es cómo CX elige mal con el cliente esperando.

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

*(El de `GET /cases/{id}` sin los `sla_*` se resolvió: el detalle ahora los
devuelve, calculados en la misma pasada que ya hacía por el último pedido de
documentos. Abrir un caso pasó de 79 KB a 1,5 KB.)*


**La línea de CORS** — la API sólo permite el header `content-type` y los
métodos GET/POST/DELETE/OPTIONS. Sin `authorization` no hay auth real en v2, y
`compliance-admin` **no puede cambiarlo**: `AccessDenied` en
`apigateway:PATCH`. Necesita a alguien con ese permiso.
