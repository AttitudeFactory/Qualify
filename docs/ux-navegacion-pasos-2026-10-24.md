# Revisión de experiencia — moverse dentro de cada módulo: volver, saber en qué paso vas y seguir

`[v1 · 2026-10-24 · agente ux-designer]` · **Origen:** pedido del fundador (2026-10-24): «la navegación interna de cada módulo, ir atrás (no existen) (debería ser fixed en mi opinión); saber en qué paso estamos; y las opciones de continuar ocultas abajo del todo (debería ser fixed en mi opinión). Lanza una revisión exhaustiva, créame una épica para este UX improvement y evalúa agregar un poco de Framer para las transiciones o carga de cards».

**Método:** revisión **por lectura de código** de los 16 asistentes y vistas de detalle de la app, en tres
bloques en paralelo (marca y crear · productos, semana y quieren comprar · WhatsApp y por responder). **No** se
probó en el navegador: la app local pide iniciar sesión y la ventana de Chrome no se pudo achicar a 360 px. Lo
que dice «probable» falta medirlo en un celular. Persona: [`perfil-cliente-pyme.md`](perfil-cliente-pyme.md).
Reglas citadas: [`ux-guia-navegacion.md`](ux-guia-navegacion.md) N5, N6, N7 y N12.

**Relación con la épica anterior** ([`epica-ux-navegacion-experiencia.md`](epica-ux-navegacion-experiencia.md),
Feature m-24842956): esa épica fijó la regla N6 («Paso N de M», «Atrás» sin perder datos), pero **cada
asistente la construyó a su manera** y ninguno la fijó en pantalla. NAV-2 (m-24842960, «atrás» del celular)
queda **contenida** en esta épica, en la historia PASOS-3; no se duplica.

## 1. Lo que siente el dueño, en una frase

> «Toqué Continuar y no sé si pasó algo; para volver tengo que bajar hasta el fondo, y si toco atrás en el
> celular se me sale todo.» *(hipótesis armada con lo que muestra el código; validarla con la pregunta 6 del
> §5 del perfil)*

## 2. Hallazgos (ordenados por gravedad)

| # | Problema | Dónde (archivo:línea) | Lo que siente el dueño |
|---|---|---|---|
| H1 | **En el primer paso de «Tu marca», quien ya inició sesión no tiene salida.** Allí falta el botón «Atrás», y sin barra lateral ni barra inferior (`rail=False`) no hay otra forma de salir. «Seguir después» solo muestra un aviso, no lleva a ningún lado. | `brand_minimal.py:809-811`, `:309-320`; `creative_wizard_pages.py:2852`, `:3070`, `:7649`; `:2821-2826` | «¿Cómo salgo de aquí?» |
| H2 | **«Continuar» y «Atrás» quedan al final de lo que se desplaza.** Ningún asistente de página los fija. En los pasos largos quedan bajo el borde de la pantalla: colores, voz, «¿Todo correcto?» y ordenar referentes en la marca; la lista de productos y los pasos de Crear; las variaciones; el paso 1 de Publicar (más de 6 fotos); el menú automático de WhatsApp. El código de Crear dice a propósito «never sticky». | `brand_minimal.py:805-869`, `:929-936`; `creative_wizard_pages.py:2840-2864`, `:7654-7689`; `content_generator.py:1722-1735`, `:4460-4494`; `qualify-creative.css:415-419`; `variations_view.py:300-307`; `publishing_page.py:494-516`; `whatsapp_tab_menu.py:2025-2056` | «¿Y ahora qué toco?» |
| H3 | **Al cambiar de paso no se vuelve arriba.** Tras «Continuar» el dueño aparece a mitad del paso siguiente. `new_generation` mueve la ventana, pero lo que se desplaza es el panel, así que probablemente no hace nada. | `creative_wizard_pages.py:416-427`; `creative_state.py:3452-3466`, `:4497`; `whatsapp_menu_state.py:875-880`; `ui/layout.py:880-886` | «Esto se ve raro, ¿me salté algo?» |
| H4 | **El «atrás» del celular saca del módulo.** Ningún paso de ningún asistente tiene dirección propia. Tampoco la tienen el detalle de un chat, el de una conversación, el panel de una publicación en Tu semana ni los cajones de WhatsApp. Solo tus productos (`?producto=`) y comentarios lo hacen bien. | `planner_state.py:796-801`; `whatsapp_chats_state.py:540-555`; `conversations_state.py:909-926`; bien hecho en `catalog_state.py:743-768` y `inbox_state.py:1054` | «Toqué atrás y perdí todo» (incumple N5) |
| H5 | **El paso en que vas no se ve, o no dice la verdad.** En Crear, el contador vive dentro de la tarjeta y no en la parte fija de arriba. En los cajones (agregar producto, programar publicación, promoción, mensaje aprobado) se va al desplazar, y en el celular se esconde el nombre de los demás pasos. En el menú automático de WhatsApp el «Paso N de 4» queda debajo de otras dos tarjetas. En la marca con redes, a quien es influencer el contador le salta de «5 de 12» a «10 de 12». Al reprogramar en Tu semana dice «de 2» pero dibuja 3 pasos. | `content_generator.py:4220-4240`; `catalog_page.py:518-531`; `planner_drawer.py:1040`, `:1476-1483` vs `planner_state.py:665-672`; `whatsapp_tab_campaigns.py:699-712`; `whatsapp_tab_templates.py:694-707`; `whatsapp_tab_menu.py:2148-2178`; `creative_wizard_pages.py:7708` vs `:3969-3997` | «¿Cuánto me falta?» (incumple N6) |
| H6 | **«Volver» no dice a dónde, o no aparece.** El detalle de una conversación dice «‹ Conversaciones», pero la pestaña se llama «Mensajes». «‹ Chats», «‹ Tu semana», «Volver a los grupos» y «Volver a los 4 pasos» se van al desplazar. En «Revisar publicación», si falla la carga no hay forma de volver. El enlace «Por aprobar» es muy chico para el dedo (`size="1"`, menos de 44 px). | `conversations_page.py:608-620` vs `responder_vm.py:34`; `whatsapp_tab_chats.py:286-298`; `planner_drawer.py:2003-2015`; `variations_view.py:779-786`; `whatsapp_tab_menu.py:2127-2135`; `creative_pages.py:2688-2699`, `:2739` | «¿Esto me lleva adonde estaba?» (incumple N7, N12) |
| H7 | **Cerrar la promoción de WhatsApp borra lo que llevabas.** La hermana, el mensaje aprobado, sí lo guarda. | `whatsapp_campaigns_state.py:579-591` vs `whatsapp_templates_state.py:406-431` | «Lo escribí y se borró» (incumple N6) |
| H8 | **Las tarjetas aparecen de golpe, o con un vacío falso.** Variaciones muestra «Aún no tienes productos» mientras carga (`products_loading` nunca se lee). La marca usa una barra de progreso en vez de tarjetas fantasma. Cambiar de pestaña o de paso no tiene entrada suave, salvo en la marca. Al saltar a una sección, esta queda debajo del encabezado fijo (`scroll_margin_top` de 1rem o nada). | `variations_view.py:150-185`, `variations_state.py:141`; `brand_kit_editor.py:599`; `brand_minimal.py:911`; `brand_kit_editor.py:398`, `:554`; `followups_page.py:461`; `whatsapp_tab_menu.py:421`, `:556` | «Dice que no tengo productos… ¡si sí tengo!» |
| H9 | **El menú no se queda encendido en el módulo donde estás** (reportado por el fundador, 2026-10-24: «es Menciones que no se queda active»). **Causa 0, comprobada en el navegador y en el código de Reflex:** en la portada `/`, `router.page.path` no vale `/` sino `/index`. Reflex guarda ahí la ruta registrada, y la raíz se registra como `index` (`reflex/app.py:2381`, `reflex/route.py:225`). En la app local (puerto 3100, versión anterior del menú) ninguna entrada tiene `aria-current` en `/` y el texto de Menciones queda en peso 400. En `/drafts` sí se enciende. Con el código actual le pasa lo mismo a **Inicio**, en el menú lateral y también en la barra inferior, porque las dos comparan contra `/`. Arreglo: comparar contra `router.url.path`, la dirección que se ve en el navegador, y no contra `page.path`. **Recorrido en el navegador (2026-10-24, sesión del fundador, 17 rutas):** todas las entradas se encienden, menos la portada `/` y `/drafts/<id>`, donde «Por aprobar» queda en peso 400 y sin `aria-current`. Al moverse tocando el menú, sin recargar, la cápsula sí sigue a la entrada activa: la causa 2 **no se reprodujo**. Causa 1, segura en el código: el menú lateral compara la ruta exacta (`path == route`). En las pantallas que cuelgan de un módulo, como `/drafts/[draft_id]` («Revisar publicación»), ninguna entrada se enciende. La barra inferior sí acepta subrutas (`_route_is_current`), así que las dos navegaciones no coinciden. Causa 2, probable, sin probar en navegador: la cápsula de vidrio solo se recoloca cuando el menú se vuelve a montar, porque `glass-nav.js` observa nodos y no atributos. Si React reusa el menú y solo cambia `aria-current`, la cápsula queda en la entrada anterior o desaparece, y el respaldo CSS está apagado mientras corre el script (`.q-sidebar:not([data-glass])`). | `ui/layout.py:332` vs `:668-675`; `assets/glass-nav.js:207-219`, `:325-327`; `assets/qualify.css:166` | «¿En qué parte estoy?» (incumple N1 y N7) |

**Lo que ya funciona bien y se toma como modelo:** el **cajón** (`drawer()`, `ui/primitives.py:745-818`). Su
cabeza (título y ✕) y su pie (acciones) quedan fijos y solo el medio se desplaza. Por eso «Siguiente» y «Atrás»
siempre se ven en agregar producto, programar publicación, promoción y mensaje aprobado. Lo que le falta al
cajón es mostrar el paso en la cabeza.

## 3. La propuesta: un solo «marco de paso a paso» para todos los asistentes

No es un componente nuevo desde cero: es **la anatomía del cajón** (cabeza fija, medio que se desplaza, pie
fijo) llevada también a los asistentes de página completa, con la misma cabeza en todos. Igual es un **patrón
nuevo**: va primero a `docs/design-system.md` (historia PASOS-1) y lo aprueba el fundador.

### 3.1 Celular (360 px), asistente de página

```
┌──────────────────────────────────────┐
│ ‹ Tus publicaciones    Paso 2 de 4   │ ← CABEZA FIJA: volver con destino (N7)
│ ▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░ │   + paso real + barra de avance
│ ¿Qué quieres decir?                  │   + nombre del paso (h1)
├──────────────────────────────────────┤
│                                      │
│  … contenido del paso (se desplaza)… │
│                                      │
│                                      │
├──────────────────────────────────────┤
│ [ Atrás ]        [   Siguiente   ]   │ ← PIE FIJO: ocupa el lugar de la barra
│        Seguir después                │   inferior mientras dura el asistente
└──────────────────────────────────────┘
```

- **La barra inferior de accesos se esconde** mientras el asistente está abierto, y el pie de acciones ocupa su
  lugar. Es la misma isla opaca, con la misma altura reservada (`--q-bottom-bar-h`): en la parte de abajo nunca
  hay dos barras ni dos islas. Sale el dueño del asistente y vuelve la barra de accesos.
- **«‹ destino»** arriba a la izquierda, siempre visible: vuelve al lugar de donde vino (`?volver=`, N4).
  **«Atrás»** abajo: retrocede un paso. En el paso 1 no hay «Atrás», pero la cabeza siempre da la salida
  (arregla H1).
- **«Paso N de M» con M real**, sin contar los pasos que se saltan, más el nombre del paso en palabras del
  dueño. Arregla H5.
- **El botón principal va a la derecha, sólido y ancho, al alcance del pulgar.** «Seguir después» lleva a
  Inicio (N2) y guarda lo que lleva el dueño. *Hipótesis: el dueño usa el celular con una mano; validarla con la
  pregunta 3 del §5.*
- **Con el teclado abierto** el pie se esconde, igual que hoy la barra inferior (`qualify.css:756-765`), para
  no tapar lo que escribe.

### 3.2 Computador

Igual, dentro del panel: la cabeza va pegada arriba (ya existe `.q-page-header` sticky) y el pie se pega abajo
del panel (`position: sticky; bottom`), como ya hace `.q-rv-savebar--editing`. No se agregan superficies de
vidrio, así que el presupuesto de vidrio (§4.3-6) no cambia.

### 3.3 Cajones con pasos

La cabeza del cajón muestra «‹ Cerrar · Paso N de M · nombre» con la barra de avance, y el indicador sale del
medio que se desplaza. El pie se queda como está.

### 3.4 Reglas del marco (para la guía, como N6b)

1. Ningún paso sin salida visible: cabeza «‹ destino» o «Cerrar».
2. El paso en que vas, el «Atrás» y el botón principal **nunca** se desplazan.
3. Al cambiar de paso, el contenido vuelve arriba y el foco va al título del paso (lector de pantalla).
4. Cada paso tiene dirección (`?paso=2`). El «atrás» del celular retrocede un paso; en el paso 1 cierra el
   asistente; nunca saca del módulo.
5. Cerrar o salir nunca borra lo escrito; volver a entrar retoma desde ahí.
6. `scroll_margin_top` = alto del encabezado fijo (un token), en todo `scroll_to`.

## 4. Transiciones y carga de tarjetas — ¿agregamos Framer (Motion)?

**Lo que ya hay:** un sistema de movimiento propio en CSS. Tiene dos curvas (`--q-ease`, `--q-spring`), tres
duraciones (140/240/380 ms), entrada escalonada `q-settle`, cajón que entra deslizándose, tarjetas fantasma con
brillo y respeto a `prefers-reduced-motion` en todos los bloques (`assets/qualify.css:47-51`, `:782-797`,
`:972-1112`; `docs/design-system.md` §3.3 y §10.13). **Ninguna** librería de animación está instalada.

| Opción | Qué resuelve | Costo | Riesgo |
|---|---|---|---|
| **A · Ampliar el CSS que ya existe** (recomendada) | El paso entra deslizándose según la dirección: ‹ si retrocede, › si avanza (`data-dir` + `key=paso`). Las tarjetas fantasma se convierten en tarjeta real con un fundido. Pestañas y listas entran con `q-settle`. La barra de avance se mueve sola. | 0 KB, sin dependencia nueva. ~1 historia S. | Bajo. No anima la **salida** (una tarjeta que se va al «Aprobar»). |
| **B · View Transitions del navegador** (`document.startViewTransition`) | Transiciones entre pantallas y pasos, incluida la salida. | 0 KB; un script chico como `glass-nav.js`. | Medio. Reflex actualiza la pantalla cuando llega la respuesta del servidor y no hay un buen momento donde envolver el cambio. En navegadores viejos de Android no hay animación (no se rompe nada). |
| **C · Motion (antes Framer Motion)**, envuelto como componente de Reflex | Salida animada (`AnimatePresence`): la tarjeta aprobada se va y las demás se acomodan (animación de *layout*). También gestos como deslizar para descartar. | Dependencia nueva de npm, que es la decisión del fundador (regla «sin vendor nuevo sin tabla de opciones»). Peso medido en PASOS-12: **+50,34 KiB gzip** del cliente completo; desglose inicial/diferido en §4.1. Requiere un wrapper local de Reflex. | Medio. Más JS en celulares de gama baja (*hipótesis*: el parque de equipos de los clientes en VE y CO no se conoce; validarlo con la pregunta 3 del §5). Pide `key` estable en cada tarjeta. |

**Recomendación:** **A dentro de esta épica** (PASOS-11): da lo que el fundador pidió («un poco» de movimiento
en pasos y carga de tarjetas) sin costo ni dependencia. **C solo como spike con tiempo acotado** (PASOS-12), y
solo para lo que el CSS no hace bien: la **salida** de tarjetas en «Por aprobar», «Quieren comprar» y «Por
responder», donde ver que la tarjeta se va confirma «listo» (N3). La medición de PASOS-12 (§4.1) recomienda conservar CSS. Se usó CPU 6x en Chromium, como aprobó el fundador; **no se probó un Android físico**. **B se descarta por ahora.**

Regla para cualquier opción: el movimiento **explica** (de dónde vino, a dónde se fue). Nunca decora, nunca dura
más de 380 ms y se apaga con `prefers-reduced-motion`.

### 4.1 Resultado de PASOS-12 — 2026-10-26

**Recomendación técnica: conservar CSS. La decisión del fundador sobre incorporar Motion sigue
pendiente; no se añade la dependencia a producción.** Se comparó la salida de una tarjeta sintética de
«Por aprobar» y el acomodo de sus vecinas: 20 tarjetas con IDs estables, 240 ms y la curva existente
`cubic-bezier(.22,1,.36,1)`. No se aprobaron publicaciones ni se llamó a servicios de negocio.

| Medición | A · CSS | C · Motion 14.6.0 |
|---|---:|---:|
| JavaScript de **todo el cliente de la app**, gzip / Brotli | 1.901.819 / 1.584.991 B | 1.953.365 / 1.630.994 B |
| «Por aprobar» hasta hidratar el fixture, gzip | 494.282 B | 510.319 B |
| Features diferidas adicionales, gzip | 0 B | 32.031 B |
| Intervalo rAF mediano / p95, CPU 6x | 8,30 / 9,20 ms | 8,30 / 9,30 ms |
| Frames perdidos **estimados a partir de rAF** | 1 (0,10 %) | 30 (3,09 %) |
| Nodos vecinos conservados; lista final de 19 tarjetas | 20/20 pruebas | 20/20 pruebas |
| `prefers-reduced-motion: reduce` | Sin animaciones activas | Sin animaciones activas |

El delta del cliente completo es **+51.546 B gzip (+50,34 KiB)** y **+46.003 B Brotli (+44,92 KiB)**.
Se comprimió cada archivo JavaScript por separado (gzip nivel 9, Brotli calidad 11) y se sumaron sus tamaños;
no es tráfico HTTP capturado. El cierre de imports estáticos de scripts/preloads de `drafts.html`, más el
módulo local NoSSR al hidratar, determina la segunda fila. `LazyMotion` + `m` + import dinámico de `domMax`
sí separaron las features en el export Vite: esos 32.031 B se cargan automáticamente después de montar el
fixture. Ya están incluidos en el total; no sumarlos dos veces. Otros imports y hashes de chunks compartidos
pueden cambiar la compresión del resto de rutas.

| Opción | Mantenimiento | Riesgo / decisión recomendada |
|---|---|---|
| A · CSS | Clase de salida, colapso de altura y retirada diferida; mantener duración y cancelación coordinadas. | Recalcula layout durante el colapso. **Conservar para este alcance.** |
| C · Motion | Salida y layout declarativos con `AnimatePresence`, keys por ID, proveedor `LazyMotion`, features y wrapper Reflex. | Dependencia y ciclo de presencia adicionales; validar foco, hidratación y actualizaciones servidor. **No incorporar sin decisión del fundador y un caso con ganancia medida.** |

**Qué se midió.** El peso procede de tres exports de la **aplicación Reflex completa**, base `8496c66`:
A0 sin prototipo, A con fixture CSS en «Por aprobar» y C con el mismo fixture mediante wrapper local NoSSR.
Los tres terminaron frontend, SSR y prerender. Reflex 0.10.0 / bun 1.4.0 actualizaron dependencias durante la
inicialización: el lock original decía React 19.2.6, pero los exports A y C usaron **React/ReactDOM 19.3.0,
Vite 8.3.2 y React Router 8.4.0**. Sus `package.json` difieren únicamente en `motion: 14.6.0`; no se atribuye a
Motion el cambio previo de dependencias.

La fluidez procede de un **fixture React equivalente aislado**, con esas mismas versiones de React, no de
una sesión autenticada completa de Reflex. Chromium 151.0.7922.34, Apple M1 Pro de 8 núcleos, macOS 26.3.1
arm64, viewport 360×800, CPU 6x mediante CDP; tres calentamientos y **20 repeticiones por opción**, alternando
el orden. Se registraron intervalos rAF durante 400 ms por salida. Sesenta intervalos inactivos calibraron el
presupuesto en 8,30 ms (~120 Hz); perdidos = `Σ max(0, round(intervalo/presupuesto)-1)`. **No son FPS de
producción ni frames físicos del compositor.** Una máquina y sin inferencia estadística: CPU 6x no reproduce
GPU, memoria o red de un Android real. Tampoco mide websocket, foco o cancelación de una aprobación.

Ambas opciones conservaron nodos con keys estables y terminaron sin errores JavaScript. Con movimiento
reducido se comprobó cero animaciones activas y `transform: none` o matriz identidad. El prototipo Motion
apaga también el fundido explícitamente: `MotionConfig reducedMotion="user"` conserva opacity por diseño.

**Reproducir.** El [código, README y muestras crudas del spike](https://github.com/AttitudeFactory/Qualify/tree/spike/m-24852253-motion-cards/testing/spikes/m-24852253)
quedan en una rama separada, junto al wrapper local; no se fusionan sus dependencias. Comandos principales:

```sh
# En el worktree aislado, exportar A0, A-CSS y C-Motion; guardar cada build/client.
QUALIFY_AUTH_FAKE=1 QUALIFY_CALENDAR_WORKER=off uv run --no-sync reflex export --frontend-only --no-zip --env prod
# En testing/spikes/m-24852253, con los exports guardados según README:
npm ci --no-audit --no-fund
node build.mjs
PLAYWRIGHT_MODULE=/ruta/a/playwright node run.cjs
node measure-app.mjs
node route-phases.mjs
```

`app-bundle.json` conserva los tamaños por archivo; `results.json`, los intervalos crudos y controles. El
benchmark esbuild del fixture se conserva por separado y **no se rotula como delta de la app**. Las rutas de
export, variables de importación de Python y pasos completos están en el README del spike.

Fuentes primarias: [LazyMotion](https://motion.dev/docs/react-lazy-motion),
[features y tamaño de bundle](https://motion.dev/docs/react-reduce-bundle-size),
[AnimatePresence](https://motion.dev/docs/react-animate-presence),
[layout](https://motion.dev/docs/react-layout-animations),
[movimiento reducido](https://motion.dev/docs/react-accessibility),
[wrappers Reflex](https://reflex.dev/docs/wrapping-react/library-and-tags/) y
[componentes locales](https://reflex.dev/docs/wrapping-react/local-packages/).
Se verificó la versión instalada con npm y manifiestos; no se usaron KB publicitarios como medición.

## 5. Historias propuestas (para `product-owner`)

Prefijo `PASOS`. Toda historia de código lleva los criterios de siempre: revisión local de `ux-designer`,
prueba a 360 px y `ci-lint` y `ci-test` en verde. **Cargadas en Meegle (2026-10-24):** Feature
[m-24852238](https://project.larksuite.com/5h2wsx/story/detail/24852238); plan y orden en
[`epica-ux-pasos-navegacion-interna.md`](epica-ux-pasos-navegacion-interna.md).

| ID | Meegle | Historia (en palabras del dueño) | Prioridad | Tamaño | Arregla |
|---|---|---|---|---|---|
| PASOS-1 | [m-24852240](https://project.larksuite.com/5h2wsx/issue/detail/24852240) | Documentar el «marco de paso a paso» en `docs/design-system.md` y la regla N6b en la guía. Lo aprueba el fundador **antes** del código. | P0 | S | todas |
| PASOS-2 | [m-24852241](https://project.larksuite.com/5h2wsx/issue/detail/24852241) | Construir el marco en `Qualify/ui/`: cabeza fija (‹ destino, Paso N de M, barra, título), pie fijo que reemplaza la barra inferior en el celular, vuelta arriba y foco al cambiar de paso, muestra en `/design` y prueba de guardia. | P0 | M | H2, H3, H5 |
| PASOS-3 | [m-24852246](https://project.larksuite.com/5h2wsx/issue/detail/24852246) | «Toco atrás en el celular y vuelvo un paso, no me salgo»: `?paso=` en todos los asistentes y dirección propia para el detalle de chat, la conversación y el panel de Tu semana. **Absorbe NAV-2 (m-24842960).** | P1 | M | H4 |
| PASOS-4 | [m-24852243](https://project.larksuite.com/5h2wsx/issue/detail/24852243) | Tu marca (`/brand`, `/brand/manual`, `/brand/connect`): siempre puedo salir; «Seguir después» me lleva a Inicio; el contador dice la verdad. | P0 | M | H1, H2, H5 |
| PASOS-5 | [m-24852244](https://project.larksuite.com/5h2wsx/issue/detail/24852244) | Crear publicación (lista de productos, 4 pasos, variaciones): «Siguiente» siempre a la vista; el paso arriba; nada de «no tienes productos» mientras carga. | P0 | M | H2, H3, H5, H8 |
| PASOS-6 | [m-24852245](https://project.larksuite.com/5h2wsx/issue/detail/24852245) | Publicar ahora (3 pasos): mismo marco. | P1 | S | H2 |
| PASOS-7 | [m-24852247](https://project.larksuite.com/5h2wsx/issue/detail/24852247) | Cajones con pasos (agregar producto, programar o reprogramar, promoción, mensaje aprobado, mensaje dentro del chat): el paso en la cabeza, el contador coincide con los pasos, y cerrar la promoción no borra nada. | P1 | M | H5, H7 |
| PASOS-8 | [m-24852249](https://project.larksuite.com/5h2wsx/issue/detail/24852249) | Menú automático de WhatsApp (4 pasos): mismo marco y el paso arriba de todo. | P1 | S | H2, H3, H5 |
| PASOS-9 | [m-24852250](https://project.larksuite.com/5h2wsx/issue/detail/24852250) | Quieren comprar (3 pasos por consulta): «Paso N de 3» y acciones a la vista; al pasar a la siguiente consulta, su título no queda tapado. | P2 | S | H2, H8 |
| PASOS-10 | [m-24852251](https://project.larksuite.com/5h2wsx/issue/detail/24852251) | «Volver» dice a dónde y nunca se desplaza: «‹ Mensajes», «‹ Chats», «‹ Tu semana», «‹ Tus grupos», «‹ Por aprobar» (44 px); y salida también cuando falla la carga. Margen de desplazamiento con el alto del encabezado. | P1 | S | H6, H8 |
| PASOS-11 | [m-24852252](https://project.larksuite.com/5h2wsx/issue/detail/24852252) | Movimiento con el CSS que ya existe: el paso entra según la dirección, la tarjeta fantasma se funde en la real, entrada suave al cambiar de pestaña; todo con `prefers-reduced-motion`. | P1 | S | H8 |
| PASOS-12 | [m-24852253](https://project.larksuite.com/5h2wsx/issue/detail/24852253) | *Spike* (máximo 1 día): Motion solo para la salida de tarjetas en «Por aprobar». Mide peso y fluidez en un Android de gama baja; termina con una tabla para que el fundador decida. **Sin merge de dependencia sin su decisión.** | P2 | S | — |
| PASOS-13 | [m-24852260](https://project.larksuite.com/5h2wsx/issue/detail/24852260) | «El menú siempre muestra en qué módulo estás»: una sola regla de ruta actual para el menú lateral y la barra inferior, las subpantallas encienden su módulo y la cápsula de vidrio se recoloca al cambiar `aria-current` y con atrás o adelante. Es un arreglo y no espera a PASOS-1 ni a PASOS-2. | P0 | S | H9 |

**Orden:** primero PASOS-1, que necesita el visto bueno del fundador; después PASOS-2; luego PASOS-4 y
PASOS-5, que son el recorrido principal; después el resto. PASOS-3 puede ir en paralelo a PASOS-2, y PASOS-12
es independiente.

## 6. Qué necesita `reflex-ui-engineer`

- Partir de `drawer()` (cabeza y pie fijos) y de `.q-page-header` y `.q-rv-savebar--editing`, que ya son
  sticky. Sin colores nuevos: el pie es la isla opaca de `.q-bottom-bar`.
- La barra inferior se esconde con una clase en `.q-ground` mientras el marco está montado (igual que ya hace
  con el teclado), no con estado de Python.
- Volver arriba al cambiar de paso: `rx.call_script` sobre `main.q-panel`, no sobre `window` (arregla también
  `creative_state.py:4497`).
- El `?paso=` se escribe con `pushState` y se lee en `on_load` y en `popstate`, como ya hace WhatsApp con sus
  pestañas (`whatsapp_state.py:273-289`).
- Antes de abrir cada PR, medir a 360 px en el navegador: esta revisión no pudo hacerlo.
