# UI — Brand Kit por pasos (`Qualify/creative_wizard_pages.py`)

**Estado:** `[EN CURSO]` — funcional y enrutado. El problema de layout que quedó abierto en la primera sesión está **resuelto en código y medido en navegador** (§6), pero falta la confirmación visual final por parte del fundador (§8). Todo el trabajo hasta la fecha está **commiteado en `fix/brand-kit-wizard`, bajo la PR #36 ya abierta** — sin pushear todavía, ver §9.
**Fecha:** sesiones del 2026-09-02 al 2026-09-05.
**Alcance:** solo UI Reflex. No toca `packages/api/src/qualify_api/creative/`, `packages/creative/`, ni el esquema de `brand_kits` (migración `0009_creative`). El diseño de referencia del Brand Kit como producto sigue siendo `docs/diseno-motor-contenido-marca.md` §6.2 — este documento cubre únicamente la superficie alternativa por pasos construida encima.

---

## 1. Qué es y por qué existe

`creative_pages.brand_index` (el acordeón original de `/brand`, diseño §6.2) sigue existiendo en el código, **intacto**, pero sin ruta. En su lugar, `/brand` ahora es una bifurcación hacia dos flujos guiados por pasos, estilo instalador: título grande, contador de paso pequeño, un paso a la vez, controles Atrás/Continuar al final.

Los dos flujos escriben en el **mismo registro**: los campos de `CreativeState` (posicionamiento, audiencia, tono, ejemplos, paleta, restricciones) son los mismos que edita el acordeón y los que persiste `save_kit_form`. No hay una copia paralela del Brand Kit — solo una forma distinta de rellenarlo.

## 2. Mapa de archivos y rutas

| Archivo | Rol |
|---|---|
| `Qualify/creative_wizard_pages.py` (1.563 líneas) | Todo el código nuevo: los dos flujos, sus dos `rx.State`, y los componentes que comparten. |
| `Qualify/creative_pages.py` | **Sin cambios.** `brand_index` (el acordeón) sigue aquí, sin ruta. |
| `Qualify/creative_state.py` | **Sin cambios.** Sigue siendo la única fuente de verdad para los campos persistidos y `save_kit_form`. |
| `Qualify/Qualify.py` | Registra las tres rutas nuevas (ver tabla siguiente) y ya no registra `brand_index`. |
| `Qualify/scrapecreators_client.py` | Cliente del API de terceros Scrape Creators (perfil TikTok/Instagram) + lectura/escritura del snapshot JSON genérico — ver §4. |
| `Qualify/test_scrapecreators_client.py` | Tests offline del cliente anterior (`httpx.MockTransport`, sin red). |
| `Qualify/fixtures/brand_connect_profile.json` | **Genérico y sobreescribible.** Último perfil leído por Scrape Creators para el flujo "Ya tengo redes" — ver §4. No versionado como dato real, se sobreescribe en cada análisis. |
| `Qualify/fixtures/midu.dev_prueba.json` | Fixture de demo original (ya no la lee el wizard) — se conserva como muestra de referencia. |
| `Qualify/signals_page.py` *(nuevo, 2026-09-04)* | Placeholder estático de `/signals` — destino del CTA "Mejorar tu perfil" de Resultados e insights (§4.1). Sin estado, sin backend. |
| `Qualify/ui/layout.py` | **Compartido con toda la app.** `app_shell` y `page_body` cambiaron para que el panel sea el contenedor con scroll (§6). Tocarlo afecta a todas las pantallas, no solo a este wizard. |
| `assets/qualify.css` | **Compartido.** Reset de `margin`/`padding` en `html, body` (§6). Es la única hoja de estilos propia del proyecto, cargada globalmente desde `Qualify.py`. |

| Ruta | Componente | `on_load` |
|---|---|---|
| `/brand` | `brand_choice_index` | `AuthState.require_login` |
| `/brand/manual` | `brand_manual_index` | `+ CreativeState.load_brand/load_voice + BrandWizardState.resume` |
| `/brand/connect` | `brand_connect_index` | `+ CreativeState.load_brand/load_voice` (sin `resume` — ver §4) |
| `/signals` *(nuevo, 2026-09-04)* | `signals_index` | `AuthState.require_login` — nada más que cargar |

## 3. Flujo "Empezar de cero" — `/brand/manual`, 10 pasos

Estado: `BrandWizardState`. Cursor en `step: int`, `LAST_STEP = 9`.

| # | Pantalla | Función render | Campos |
|---|---|---|---|
| 1 | Elige tu plan | `_step_subscription` | `BrandWizardState.subscription` — placeholder, lorem ipsum, 4 tarjetas (`PLANS`) |
| 2 | ¿Quién es la marca? | `_step_identity` | `CreativeState.kit_positioning` / `kit_audience` |
| 3 | ¿Tienes logo? | `_step_has_logo` | `BrandWizardState.has_logo` ("si"/"no") — al responder avanza solo |
| 4 | Tu logo | `_step_logo` (bifurca) | "si" → `_logo_upload_field` (sube archivo, preview); "no" → `_logo_brief_form` (3 campos lorem) |
| 5 | Paleta de colores | `_step_palette` | `CreativeState.kit_palette` — ver §5, rediseño completo |
| 6 | ¿Cómo suena? | `_step_voice_tone` | los 4 sliders de tono existentes |
| 7 | Enséñale a hablar | `_step_voice_examples` | ejemplos SÍ/NO + patrones de CTA |
| 8 | Lo que nunca debe decir | `_step_restrictions` | palabras vetadas + claims prohibidos |
| 9 | ¿Todo correcto? | `_step_confirm` (`_CONFIRM_STEP`) | resumen de solo lectura de todo lo anterior + Continuar |
| 10 | Resultados e insights *(nuevo, 2026-09-05)* | `_step_insights` | logo + 1-2 competidores/influencers placeholder + **Mejorar tu perfil** — ver §4.1, misma pantalla-concepto que el flujo de conectar, sin métricas |

**`BrandWizardState.resume`** (evento en `on_load`, corre último a propósito): recorre los pasos en orden y abre el flujo en el **primer** paso con datos faltantes, no en el último visitado. Dos pasos nunca cuentan como hueco: los sliders de tono (arrancan en 50) y las restricciones (opcionales). Si no queda ningún hueco, abre en `_CONFIRM_STEP` (¿Todo correcto?) — **no** en `LAST_STEP`: reentrar al wizard debe ofrecer una revisión, no saltarse derecho a la pantalla de "ya terminaste".

## 4. Flujo "Ya tengo redes" — `/brand/connect`, 12 pasos

Estado: `BrandConnectState`, **separado** de `BrandWizardState` a propósito — dos cursores, para que los dos puntos de entrada no compitan por el mismo `step`. Los pasos 5-11 de este flujo **son literalmente las mismas funciones** que los pasos 1-7 del manual (`_step_subscription`, `_step_identity`, `_step_palette`, `_step_voice_tone`, `_step_voice_examples`, `_step_restrictions`, `_step_confirm`), reutilizadas sin copiar — es la garantía de que los dos caminos no puedan divergir.

| # | Pantalla | Específico de este flujo |
|---|---|---|
| 1 | ¿Qué red usas? | Instagram / TikTok |
| 2 | ¿Cuál es tu usuario? | input; el botón dice "Analizar" |
| — | *(pantalla de carga)* | `_connect_loading` — spinner, `analyzing: bool` |
| 3 | Esto es lo que vemos | perfil leído: foto, usuario, nombre, seguidores, bio |
| 4 | Lo que te proponemos | 4 recomendaciones placeholder + **Cancelar**/Continuar |
| 5-11 | *(compartidos, ver arriba)* | Continuar en ¿Todo correcto? dispara `advance_to_insights`, no `next_step` — ver §4.1 |
| 12 | Resultados e insights | recap del perfil + métricas animadas + 1-2 competidores/influencers placeholder + **Mejorar tu perfil** — ver §4.1 |

### 4.1 Resultados e insights (paso 10 manual / paso 12 conectar) — la vista final real de AMBOS flujos

**Movida el 2026-09-04 para ir DESPUÉS de "¿Todo correcto?", no antes** (en el flujo de conectar) — es literalmente `CONNECT_LAST` (`len(CONNECT_STEPS) - 1`). "¿Todo correcto?" pasó a mostrar "Continuar" como cualquier paso intermedio; el botón "Cancelar" volvió a "Lo que te proponemos" (`_LAST_PREVIEW_STEP = 3`) — el verdadero último paso antes de que empiece el tramo compartido de configuración del kit.

**Ahora TAMBIÉN existe en el flujo manual (nuevo, 2026-09-05)** — `_step_insights`, paso `LAST_STEP` de `BrandWizardState`. Building blocks compartidos entre los dos (`_section_label`, `_competitor_card`, `COMPETITOR_SUGGESTIONS`, `_competitors_section`, `_finish_button`, `_SIGNALS_ROUTE`) viven en una sección propia cerca del inicio del archivo (junto a `_step_body`/`_choice_card`), no duplicados en cada flujo — misma garantía de "no pueden divergir" que ya usan los pasos 5-11.

**Métricas: solo en el flujo de conectar, con animación de conteo (2026-09-05)** — el pedido original de "sin métricas" era para el flujo manual, no para este; se restauraron aquí. Por qué la diferencia: el flujo manual no tiene ninguna cuenta social escaneada de la que reportar una tasa o un promedio — mostrar métricas ahí serían números sin nada real detrás, así que esa pantalla se queda solo con logo + competidores. El flujo de conectar SÍ leyó un perfil real, así que muestra:

- **Recap de identidad**: en conectar, avatar + usuario + seguidores del perfil escaneado, dentro de una tarjeta. En manual, **solo el logo** subido en el paso 4 (o un ícono placeholder si no se subió ninguno) — sin nombre, sin `card()` alrededor: nada de chrome de tarjeta, solo la imagen, más grande (`height="6rem"`) que el avatar de 3rem del recap de conectar (ajustado 2026-09-05, a petición).
- **Métricas (solo conectar) — REALES y sobre una ventana de tiempo desde 2026-09-10** (antes: `METRIC_INSIGHTS`, tres números placeholder hardcodeados, incluido un "Crecimiento mensual 4.8%" inventado). **Ventana: los últimos 7 días** (`scrapecreators_client.METRICS_WINDOW_DAYS`, pedido "por ahora semana"; una sola constante para moverla a 14/30 después). `analyze()` hace ahora **dos lecturas** por perfil nuevo vía `fetch_profile_and_posts`: el perfil (`/v1/<red>/profile`) **y la lista de publicaciones propias del usuario** — `/v2/instagram/user/posts` (`items[]`: `taken_at`, `like_count`, `comment_count`, `play_count`) o `/v3/tiktok/profile/videos` (`aweme_list[]`: `create_time`, `statistics.digg_count/comment_count/play_count`), 1 crédito por página, paginando (`next_max_id` / `max_cursor`) hasta cubrir la ventana o hasta `_MAX_POST_PAGES` (3) — con la regla "parar cuando el ÚLTIMO ítem de la página es más viejo que la ventana" para que un post fijado antiguo al principio no corte el recorrido. Ninguno de los dos endpoints de perfil sirve para esto (TikTok no trae vídeos; Instagram trae ~12 sin garantía de cubrir la semana). `profile_metrics(network, profile)` calcula sobre las publicaciones dentro de la ventana, **anclada en `fetchedAt`** (el momento de la lectura, no el de render — un snapshot cacheado sigue describiendo la semana en que se leyó): *Publicaciones* (cuántas en la ventana; 0 es una respuesta real), *Interacción* = media(likes + comentarios) / seguidores, *Likes por publicación* (IG) / *por vídeo* (TikTok). Si la lectura de posts falla (`recentPosts = None`) no hay métricas — desconocido no es cero — y la sección entera se oculta (`has_metrics`), igual que para una cuenta recién creada (`is_new_account`). El estado las guarda en listas paralelas (`metric_labels/hints/suffixes/decimals/targets`), `metric_cards` las formatea (`12.4K`, `3.2%`, `3`) y `_metric_grid()` las pinta con `rx.foreach` + `stat_card` bajo el rótulo "Métricas · últimos 7 días". **Lo que se quitó a propósito: el crecimiento mensual** — un crecimiento necesita dos lecturas separadas en el tiempo y este flujo guarda un solo snapshot sin historial, así que no hay nada real que poner detrás; la versión definitiva sobre `search.content_index`/`signals.events` (Fase 2/3) podrá recuperarlo. **Animación de conteo** (2026-09-05, sin cambios de mecanismo): `advance_to_insights` (evento `background=True`, disparado por "Continuar" de ¿Todo correcto?) sube `metric_values` de 0 a cada `metric_targets[i]` en `_METRIC_ANIMATION_STEPS` (24) pasos repartidos en `_METRIC_ANIMATION_SECONDS` (0.9s), mismo mecanismo que `CreativeState.poll_draft`. **Pendiente de verificar en vivo**: los shapes de los dos endpoints de posts están tomados de docs.scrapecreators.com (2026-09-10), no de una respuesta real — mismo marcador `[UNVERIFIED LIVE]` que los de perfil.
- **Cuentas parecidas** (`_competitors_section`, ambos flujos): `_competitor_card()` sobre `COMPETITOR_SUGGESTIONS` — 1-2 tarjetas placeholder (competidor + influencer). **Placeholder explícito**: es una tupla hardcodeada, no una consulta — sin conexión con `search.content_index` / `signals.events` (Fase 2/3) ni con nada real.
- **`_finish_button` — "Mejorar tu perfil"** (ambos flujos): reemplaza **Finalizar por completo**, no convive con él — vive en la barra de controles fija (`_controls`/`_connect_controls`), no en el contenido de la pantalla. `on_click=[CreativeState.save_kit_form, <flow>.finish_to_signals]` → `rx.redirect("/signals")`. `/signals` (`signals_page.py`, ruta registrada en `Qualify.py`) es también un placeholder — una pantalla `empty_state` estática explicando que la capa de Señales (Fase 3) todavía no existe. El botón necesitaba un destino honesto, no un link muerto ni uno inventado.

**El origen de los datos del perfil (conectar) es un scraper real (2026-09-04): la API de terceros [Scrape Creators](https://scrapecreators.com)**, no `packages/scraper` ni la ingesta first-party de Meta — sigue sin haber ninguna conexión con ninguno de los dos. `Qualify/scrapecreators_client.py` llama a `GET /v1/instagram/profile` o `GET /v1/tiktok/profile` (según `network`) con la clave `SCRAPECREATORS_API_KEY` (en `.env`, sin commitear), normaliza la respuesta al mismo shape que tenía el fixture de demo, y la escribe en el **único JSON genérico y sobreescribible** `Qualify/fixtures/brand_connect_profile.json` (`save_profile_snapshot`) — sin tabla, sin historial, sin scoping por tenant, a propósito (ver el docstring del módulo). `BrandConnectState.analyze` (`background=True`, `yield` temprano para que el spinner pinte antes del fetch) llama al cliente vía `asyncio.to_thread`, guarda el snapshot y **lo vuelve a leer desde ese mismo archivo** (`load_profile_snapshot`) — el mismo patrón de lectura que tenía el fixture estático, ahora alimentado por una lectura real. El fixture de demo original, `Qualify/fixtures/midu.dev_prueba.json`, queda intacto como muestra de referencia pero ya no lo lee el wizard. Tests offline (sin red, `httpx.MockTransport`) en `Qualify/test_scrapecreators_client.py`.

**Caché por (network, handle) sobre el mismo JSON (2026-09-04):** antes de llamar a la API, `analyze` primero llama a `scrapecreators_client.load_cached_profile(network, handle)` — si el snapshot ya guarda exactamente ese `network` + `handle` (comparación insensible a mayúsculas y a un "@" inicial), lo usa directo y **no gasta ningún crédito de la API**. Solo un handle nuevo (o red distinta) dispara `fetch_profile` de verdad, y al guardarse sobreescribe el snapshot — o sea, solo el último handle analizado queda cacheado, no hay historial. Motivo: la key de Scrape Creators usada en desarrollo se quedó sin crédito/rate-limit tras la primera lectura real, y re-analizar el mismo perfil para seguir iterando en el wizard no debía seguir gastando cuota. **Versión del snapshot (2026-09-10):** `save_profile_snapshot` escribe `schema: 3` (`SNAPSHOT_SCHEMA`) y `load_cached_profile` devuelve `None` para cualquier snapshot con otra versión o sin ella — o sea, el `midu.dev` cacheado antes de este cambio (sin `recentPosts`/`fetchedAt`) cuenta como MISS **una vez**: el primer análisis tras el cambio gasta 2 créditos (perfil + una página de posts; hasta 4 si el perfil publicó más de una página en la semana) y vuelve a quedar cacheado con el shape nuevo. **Coste por perfil nuevo desde entonces: 2-4 créditos**, no 1.

`BrandConnectState.restart` limpia todo lo leído y redirige a `/brand` — un solo disparador ahora: "Cancelar" en el paso 4 (Lo que te proponemos). `BrandConnectState.finish_to_signals` (y su equivalente `BrandWizardState.finish_to_signals`) es el reset del botón final: mismos campos, pero redirige a `/signals` en vez de `/brand`.

## 5. La paleta de colores (paso 5, compartido)

Es la parte con más iteración. Se sustituyó el campo de texto con hex manual por tres piezas, y **cada una hace exactamente un trabajo** (decisión del fundador, 2026-09-03):

| Pieza | Trabajo | Cómo |
|---|---|---|
| **Rueda** (`_colour_wheel`) | **Solo AÑADE** colores nuevos | Disco `conic-gradient` con un `input[type=color]` nativo transparente encima. `on_change` mueve el color pendiente; `on_blur` (cierre del diálogo del SO) lo **agrega** vía `commit_picked_color`. Sin círculo central. |
| **Swatch** (`_swatch`, `foreach(colour, index)`) | **Solo EDITA** el color que ya está en la paleta | Cada círculo lleva SU PROPIO `input[type=color]` transparente encima. `set_swatch_color(index, colour)` escribe directo en esa posición — sin pasar por la rueda. La × pequeña lo borra (`remove_colour`, con `.stop_propagation`). |
| **Readout** (`_colour_readout`) | **Solo MUESTRA** | Tarjeta con el color en foco: su **nombre** y su hex en mono. No tiene picker propio ni responde al clic. |

**"En foco" en el readout** significa el último color que tocaste: el pendiente de la rueda, **o el swatch que acabas de clicar**. `_swatch` lo fija en `on_click` (antes incluso de que el diálogo devuelva valor, para que un simple clic ya nombre el color) y lo mantiene al día mientras arrastras dentro de ese picker.

El nombre lo calcula `_nearest_colour_name` por distancia RGB contra `_NAMED_COLOURS` (~29 colores de referencia) — **aproximado por diseño**, no hay ningún servicio real de nombrado de color.

### Por qué esta división (dos bugs que la motivaron)

1. **Primera sesión:** editar un color existente **añadía uno nuevo** en vez de reemplazarlo — `commit_picked_color` siempre hacía `append`. Se parcheó con `BrandWizardState.editing_index` (-1 = nuevo; ≥0 = editando esa posición).
2. **Segunda sesión:** ese parche seguía siendo un **modo oculto compartido** — un solo `picker_color` + un `editing_index` gobernaban dos comportamientos distintos, y bastaba un clic previo en un swatch para que la rueda sobrescribiera la entrada equivocada en vez de agregar. Se eliminó `editing_index` y `select_swatch` por completo: ahora **no hay modo**. La rueda siempre agrega; un swatch siempre se edita a sí mismo. El readout dejó de tener picker propio, porque una tarjeta que también agregaba era el tercer comportamiento que hacía confuso el paso.

## 6. Decisiones de layout — y lo que quedó a medio resolver

Varias rondas de ajuste visual, en orden:

1. **Radio unificado** — constante `_CONTROL_RADIUS = "large"` en todos los inputs/textareas/botones reales; las tarjetas-botón usan `T.RADIUS_CARD`.
2. **Cabecera compartida** (`_flow_header`) — contador de paso + título a la izquierda, `rx.color_mode.button()` a la derecha, en las tres pantallas.
3. **Todo el div es el botón** en `/brand`: `_fork_option` envuelve `card(interactive=True)` en `rx.link(..., display="block", ...)`. **Bug real encontrado y corregido:** sin `display="block"`, el `<a>` es inline por defecto y `width="100%"` no tenía efecto — la tarjeta se encogía a su contenido en vez de ocupar el marco. Verificado contra las docs de Radix Themes: sus componentes (`.rt-Box`, `.rt-Flex`) llevan `box-sizing: border-box`.
4. **Borde a ancho completo, con los controles anclados a las esquinas dentro de él** — cada pantalla envuelve su `_window()`/`_connect_window()` en `card(...)` con `display="flex", flex_direction="column", justify_content="space-between"`: los campos quedan arriba en una columna legible de 34rem centrada, y `_controls()`/`_connect_controls()` ocupan el ancho completo de la tarjeta, con "Atrás" en la esquina inferior izquierda y "Continuar"/"Finalizar" en la inferior derecha.
5. **`_SCREEN_MIN_HEIGHT`** — constante para que la tarjeta (`flex="1"`) tuviera espacio hacia el que crecer: `calc(100vh - 2 * gap - 2rem)`. **Eliminada el 2026-09-03** — ver abajo.
6. **"Finalizar" reemplazado por "Mejorar tu perfil" (2026-09-04, reemplazo total 2026-09-05)** — en ambos flujos, `on_click=[CreativeState.save_kit_form, <flow>.finish_to_signals]`: `BrandWizardState.finish_to_signals` en el manual, `BrandConnectState.finish_to_signals` en el de conectar — cada uno construido sobre un `_reset_fields()` privado (no `@rx.event`, para no chocar con el `reset` builtin de `rx.State` — `EventHandlerShadowsBuiltInStateMethodError`) que limpia todos los campos propios del wizard (cursor, `subscription`, logo, `picker_color` / `network`, `username`, `profile_*`, `metric_values`) y luego redirige a `/signals`, no a `/brand` — ver §4.1. **Se dispara independientemente de lo que haga `save_kit_form`** — por ahora es toda la "persistencia" que hay, simulada: no hay todavía una rama de éxito/fracaso de la que depender. Nota: solo se reinicia el estado propio del wizard — los campos reales del kit (`CreativeState`: positioning, audience, paleta, tono...) no se tocan.
7. **Mobile: separación mínima Atrás/Continuar (2026-09-04)** — `justify_content="space-between"` por sí solo colapsa a ~0 en cuanto el contenido llena el alto libre de la tarjeta, algo que en desktop casi nunca pasa pero en un viewport de mobile es la norma en los pasos largos (Elige tu plan, Paleta, Enséñale a hablar, Lo que nunca debe decir, ¿Todo correcto?, Esto es lo que vemos, Lo que te proponemos). Se le agregó `gap="1.5rem"` a los dos `card(...)` (manual y conectar) — un mínimo garantizado que `space-between` sigue repartiendo por encima cuando sobra espacio, así que los pasos cortos no cambian.
8. **Mobile: animación de loading centrada en todas las vistas (2026-09-04)** — nuevo `_loading_view(title, subtitle)`, del que `_connect_loading` ahora es un envoltorio delgado. `CreativeState.kit_loading` ya no muestra un `rx.skeleton` plano junto a los controles (`brand_manual_index`) ni queda sin manejar (`brand_connect_index`, que antes solo reaccionaba a `BrandConnectState.analyzing`): en ambos flujos ahora reemplaza la tarjeta entera (contenido + controles) por una tarjeta centrada con el mismo spinner, sin controles que apunten a nada mientras carga.
9. **"¿Todo correcto?": fila de paleta que se salía con 2+ colores (2026-09-04)** — `_recap_row` mostraba el valor (ej. `"#0a3d2e,#ff6b35"`) sin punto de quiebre: al ser un string sin espacios, el navegador no tenía dónde envolverlo y la fila se salía de la tarjeta, rompiendo la alineación en tabla del resto de filas. Mismo arreglo que ya documentaba `_colour_readout` para el mismo problema: `min_width="0"` + `overflow_wrap="anywhere"` en la columna del valor.
10. **"¿Todo correcto?": se quitó la fila "Logo" (2026-09-04)** — a petición, el resumen final ya no muestra `BrandWizardState.logo_name`.
11. **`BrandConnectState.analyze()` se autocorrige ante un `network` inválido (2026-09-05)** — reportado en vivo: `unsupported network: ''` saliendo de `scrapecreators_client.fetch_profile`. El paso "¿Cuál es tu usuario?" solo debería alcanzarse con una red ya elegida (`choose_network` fija ambas cosas juntas), pero un reinicio del servidor de desarrollo (frecuentes esta sesión, uno por cambio) resetea el estado del backend a sus valores por defecto mientras el navegador conserva el `step` de antes de reconectar — se llega al paso del usuario con `network=""`. Antes eso reventaba con el error crudo de la API; ahora `analyze()` valida `self.network` contra `SUPPORTED_NETWORKS` antes de llamar a nada y, si no es válido, regresa al paso 0 en silencio en vez de tronar.

### El problema del borde y el scroll — resuelto 2026-09-03

Quedó abierto al cerrar la primera sesión: *"el borde no llega al fondo del panel y aparece un scroll no deseado"*. Se atribuía a un doble-resto de padding por `border-box`. **Medido en un navegador real (`getBoundingClientRect` sobre la página viva), esa hipótesis era falsa** y había dos causas independientes:

| Síntoma | Causa real, medida | Número |
|---|---|---|
| Scrollbar siempre presente | La cadena `shell 100vh → panel calc(100vh - 2*gap) → pantalla → padding de `page_body`` nunca restaba **el borde de 1px arriba+abajo del propio panel** | shell renderizaba **924.8px** contra un `min-height` de 923.2px → **2px** de desbordamiento, en todos los pasos, siempre |
| Borde corto del fondo | `padding-bottom: 4rem` del vstack de pantalla **+** `2rem` de `PAD_BODY`, apilados | tarjeta terminaba en `y=818`, panel en `y=914.8` → **96.8px** de espacio muerto |

Un tercer factor, previo a todo: **el navegador aplica `margin: 8px` a `body` por defecto** y nada lo reseteaba, así que el layout ya desbordaba el viewport ~16px antes de empezar. Se añadió el reset en `assets/qualify.css`.

**La corrección no fue ajustar la fórmula, sino eliminarla.** Aritmética que tiene que cancelar al píxel entre cuatro cajas anidadas se rompe en cuanto cualquiera gana un borde o un padding — ya se había roto dos veces. Ahora:

- **`ui/layout.py::app_shell`** — el **panel es el contenedor con scroll**, no el documento: altura definida (`height: calc(100vh - 2*gap)`) + `overflow: hidden auto`; el shell mide exactamente `100vh` y recorta. Es lo que el sidebar ya hacía desde siempre (`height: 100vh`, `overflow: hidden auto`).
- **`ui/layout.py::page_body`** — `flex: 1 0 auto`: crece hacia el hueco del panel, nunca se encoge por debajo de su contenido.
- **`creative_wizard_pages.py`** — sin `100vh` en ningún sitio. Cada pantalla usa `flex="1"` + `min_height="0"`, y su `padding` inferior pasó de `4rem` a `0` (el respiro lo pone `PAD_BODY`).
- **Contenido centrado en vertical**: la columna de campos (34rem) toma la altura libre con `flex="1"` + `justify_content="center"`, mientras `_controls()` sigue anclado abajo por el `space-between` de la tarjeta.

Medición del prototipo antes de escribir el cambio: **0px de desbordamiento de documento, sin scrollbar de documento ni de panel, tarjeta a 10.8px del fondo del panel** (contra 96.8px antes), columna de campos centrada en ambos ejes.

> ⚠ **`ui/layout.py` y `creative_wizard_pages.py` se mueven juntos.** El 2026-09-03 se restauró una copia antigua de `creative_wizard_pages.py` (desde otro worktree) **encima** del `layout.py` nuevo: el módulo viejo seguía calculando `calc(100vh - …)` dentro de un panel que ya tenía altura fija — es decir, midiendo el *viewport* desde dentro de una caja más pequeña que él. El contenido se desbordaba y **el layout se rompió visiblemente**. Si revierte uno, revierta el otro. La advertencia está escrita también en el docstring de ambos archivos.

## 6.1 Auditoría contra el design system (2026-09-05)

A petición: verificar que el wizard **hereda** botones, colores y animaciones de `docs/design-system.md` / `Qualify/ui/tokens.py` en vez de reinventarlos, y buscar si ya existe un componente/animación de carga en el proyecto para replicarlo aquí.

**Loading — conclusión inicial ("ya heredado, nada que cambiar") superada horas después, ver abajo.** Primera pasada: `_loading_view()` (spinner centrado + texto) es exactamente el mismo idioma que `creative_pages.py::_drafting_panel` (`rx.spinner` + mensaje) usa para su propio panel de espera de generación — el patrón "spinner centrado reemplaza toda la tarjeta mientras algo carga" ya era el idiom del proyecto. No existía ningún componente de carga bespoke (nada de shimmer, nada de CSS de progreso) en `assets/qualify.css` ni en ningún `.py` — todo el loading de la app era `rx.spinner`/`rx.skeleton` de Radix, sin excepción.

**Corregido el mismo día — sí se construyó un componente nuevo.** El fundador pidió específicamente un spinner distinto (un anillo con degradado cónico, referencia visual adjunta), más grande, con texto más chico, **y que viviera en el design system con sus variantes** — no una preferencia estética suelta dentro del wizard. Resultado: `ui.loading_spinner(size="sm"|"md"|"lg")`, nuevo en `Qualify/ui/primitives.py` (`.q-spinner` + `@keyframes q-spin` en `assets/qualify.css`, documentado en `docs/design-system.md` §5.4, demoed en `/design`). La única "variante" real es el tamaño — el color sale de la escala de gris del tema (`--gray-12` sobre transparente), así que se adapta solo a claro/oscuro, sin variante de tema que elegir (confirmado explícitamente al fundador, que preguntó). `_loading_view()` ahora usa `loading_spinner("lg")` en vez de `rx.spinner`, con el texto un tamaño más chico (`size="2"`/`"1"` en vez de `"3"`/`"2"`).

**Encontrados y corregidos — drift real contra reglas documentadas:**

1. **Botón destructivo mal clasificado** — §5.5 del design system: *"Destructive: `soft` + `color_scheme=T.tone_scale('error')`"*. "Cancelar" (`_connect_controls`) usaba `variant="ghost"` con el literal `"tomato"` en vez de `soft` + el token — corregido a `variant="soft", color_scheme=T.tone_scale("error")`, igual que ya hacía correctamente "Quitar" en el paso del logo (a ese solo le faltaba pasar por el token, no el variant).
2. **`rx.callout` crudo en vez de la primitiva `callout()`** — exactamente la misma deuda que §9.3 del design system ya señala en `clarity_page` (mezclar `rx.card`/`card()`). Tres sitios reescritos a `callout(mensaje, tono, icon=...)`: el aviso de "esto se comprueba siempre" (`color_scheme="amber"` → `tone="warn"`) y las DOS copias idénticas del aviso "kit guardado" (`color_scheme="grass"` → `tone="ok"`, una por flujo).
3. **Colores de tono referenciados sin pasar por el helper** — `rx.color("accent", N)` / `rx.color("tomato", N)` literales donde el color representa un tono semántico (ícono de acento en las tarjetas del fork y de recomendaciones, el fondo del botón "×" para borrar un color de la paleta, el anillo de selección de `_choice_card`) cambiados a `T.tone_color("accent", N)` / `T.tone_color("error", N)`. Los `rx.color("gray", N)` que quedan son bordes/fondos estructurales — igual de directos en `T.BORDER`/`T.CARD_BG` dentro de `tokens.py` mismo, no un tono, nada que corregir ahí.
4. **Curva de animación equivocada (P8)** — *"Dos curvas: `T.SPRING` para tamaño/forma, `T.EASE` para color/opacidad"*. El hover de un swatch de paleta (`scale(1.15)`) usaba `T.EASE` — es un cambio de tamaño, no de color, así que le tocaba `T.SPRING`. Corregido; el box-shadow de esa misma tarjeta (que sí es un cambio de "elevación") se queda con `T.EASE`, igual que `.q-lift` en `assets/qualify.css` separa transform (SPRING) de box-shadow (EASE) en sus propias reglas.

**Revisado y dejado tal cual, con la razón por la que no era drift:**

- **`_CONTROL_RADIUS = "large"`** — no es "sin pensar": el comentario junto a la constante explica que se eligió para que la esquina de inputs/botones (radio Radix por *keyword*) coincida visualmente con `T.RADIUS_CARD` (radio de las tarjetas del wizard, un largo CSS) a este tamaño. El tema global (`rxconfig.py`) fija `radius="medium"` y el resto de la app no lo pisa pantalla por pantalla — pero aquí hay una razón documentada, medida, para la excepción; no se tocó sin que el fundador lo pida explícitamente.

**Corregido el mismo día — la conclusión de arriba sobre `.q-settle` estaba mal.** La primera pasada de esta auditoría concluyó "el wizard ya se comporta como el resto de la app: una sola entrada al cargar la página, ninguna al cambiar de paso — inventar una re-animación por paso sería un mecanismo nuevo, lo opuesto de heredar". El fundador la corrigió: **sí quería** que cada paso tuviera su propia entrada, y confirmando en vivo que la animación no se sentía en absoluto al navegar. Dos piezas, no una:

1. **`_step_body()` gana `class_name="q-settle"`** — así los campos DE CADA PASO (no solo los bloques de la página entera) entran escalonados, mismo mecanismo que ya usa `page_body`.
2. **`key=<Estado>.step.to_string()`** — sin esto, (1) no habría bastado: al cambiar de paso, React ve el mismo `<div>` en la misma posición del árbol y solo actualiza sus hijos — nunca vuelve a montar el nodo, así que una animación CSS en él nunca se reinicia sola. `key` fuerza a React a tratar cada paso como un elemento nuevo (desmonta el viejo, monta el nuevo), que es lo que sí dispara la animación.

**Ajustado el mismo día, segunda vuelta — el `key` vivía en el lugar equivocado.** Primera versión: `key=` en el `rx.vstack` que envuelve solo `_window()`/`_connect_window()`, DENTRO del `card(...)`. Funcionaba para el contenido, pero el `card(...)` mismo (el borde, el fondo, la sombra) seguía siendo el mismo nodo reciclado entre pasos — el marco nunca se movía, solo el texto adentro. A petición ("quiero que la animación se aplique a los bordes que encierran el contenido, no solo el contenido"), el `key=` se subió al `card(...)` completo (`brand_manual_index`/`brand_connect_index`) — así la tarjeta entera (borde + contenido + `_controls()`/`_connect_controls()`) se remonta en cada cambio de paso, y como esa tarjeta es un hijo directo del `q-settle` de `page_body`, su reingreso completo sí dispara la animación sobre el marco, no solo sobre lo de adentro.

Verificado con `reflex compile --dry` (`Success: App compiled successfully`) — sin servidor vivo disponible en el momento del cambio para captura visual (ver la trampa de OneDrive, más abajo), pendiente de confirmación visual del fundador.

## 7. Lo que no se persiste todavía

Documentado también en el docstring del módulo. Campos que **sobreviven navegar entre pasos pero no un reload**, porque `save_kit_form` (en `creative_state.py`, sin tocar) no los conoce:

- `BrandWizardState.subscription` y el brief de creación de logo (`logo_brief_1/2/3`) — copy placeholder, **no existe columna** para ninguno de los dos en `brand_kits`.
- El logo subido (`logo_key`) — aquí la columna **sí existe** (`brand_kits.logo_asset_key`) y `creative_provider.save_kit` preserva a propósito lo que ya hubiera guardado (nada se pierde al guardar), pero ningún camino escribe todavía una clave nueva.

Cerrar esto significa: una migración Alembic para `subscription`/brief (si se decide persistirlos), + subida a R2 del logo + un campo `logo_asset_key` en `KitFormVM` — trabajo de backend, fuera del alcance de esta sesión (solo UI).

## 8. Verificación realizada

- `ruff check` / `ruff format` — limpios en cada ronda de cambios.
- **Medición en navegador real** (2026-09-03) sobre la app viva: cadena completa de cajas con `getBoundingClientRect` + `getComputedStyle`, que es lo que produjo los números de §6. El prototipo de la corrección se inyectó y midió en el DOM **antes** de escribir el código.
- **Código servido = código nuevo**, comprobado en dos niveles: el intérprete importa el módulo sin `_SCREEN_MIN_HEIGHT` y con el `app_shell` nuevo; y la salida compilada en `.web/app_components/Qualify/` ya no contiene `calc(100vh - 2 * var(--q-gap) - 2rem)`.
- **No hay tests para este módulo.** `Qualify/` sí está en el `testpaths` de la puerta de CI, y el resto del directorio tiene cobertura (`test_creative_vm.py`, `test_connections_state.py`…) — este es el hueco más señalado pendiente.

**Lo que NO está verificado:** la captura visual final de las pantallas con todo junto (layout nuevo + paleta nueva). El wizard exige login, y el servidor de desarrollo quedó inservible al final de la sesión: el puerto 8000 lo retiene un socket huérfano de un crash previo (PID muerto), el backend se cae a 8001 y el frontend no llega a servir en 3000. Un reinicio de la máquina libera el socket.

### Trampa de entorno encontrada (cuesta horas si no se sabe)

**El hot-reload de Reflex no se dispara de forma fiable en este proyecto** — está bajo `OneDrive`, y el propio Reflex avisa al arrancar (*"Creating project directories in OneDrive may lead to performance issues"*). Se midió un desfase de **más de 2 horas** entre el `.py` guardado y el bundle compilado: se estuvo depurando contra una app que no tenía los cambios. Antes de concluir que "el arreglo no funciona", comparar `mtime` del fuente contra el de la salida en `.web/`, y reiniciar el servidor si no coincide.

Nota relacionada: Reflex compila los componentes de página a **`.web/app_components/`**; los `.jsx` de `.web/app/routes/` son envoltorios finos que legítimamente no cambian. Buscar ahí para comprobar si un cambio entró.

**Segunda trampa encontrada el 2026-09-05, intentando verificar visualmente el spinner y la animación de entrada: `.claude/launch.json` tenía el `PYTHONPATH` roto en Windows.** Las dos configuraciones (`qualify-crm`, `qualify-crm-worktree`) unían los cinco paths de `pythonpath` con `:` — el separador POSIX. En Windows eso arma UN solo path combinado en vez de cinco reales, así que `reflex run` reventaba de inmediato con `ModuleNotFoundError: qualify_models` al importar `Qualify.py` (nunca llegaba a levantar el server, ni frontend ni backend). Corregido a `;` (el separador real de `os.pathsep` en esta plataforma) en ambos checkouts. Con el arreglo, `reflex compile --dry` y `preview_start` sí compilan — pero el `next dev` del frontend seguía sin terminar de levantar dentro del tiempo de espera disponible en varios intentos (mismo síntoma que el hot-reload de arriba: OneDrive), así que la confirmación visual del spinner/la animación de entrada sigue pendiente del fundador.

## 9. Estado en git al cerrar la sesión (actualizado 2026-09-05)

**Todo commiteado.** Rama `fix/brand-kit-wizard` — la misma que ya tiene abierta la **PR #36** (`fix(brand): brand kit wizard layout and palette control split`, `da5d364`, empujada a `origin` el 2026-09-04, checks en verde, todavía sin mergear al momento de escribir esto). El trabajo de esta sesión son 5 commits nuevos encima de `da5d364`, en orden:

| Commit | Resumen |
|---|---|
| `95d55de` | `feat(brand): scrape TikTok/Instagram profiles via Scrape Creators` — `scrapecreators_client.py` + tests, §4.1 |
| `8dfd6c0` | `feat(brand): mobile fixes + Resultados e insights final screen for both flows` — §3, §4, §4.1, §6 puntos 7-11 |
| `c80f002` | `feat(ui): loading_spinner design-system primitive, brand kit token audit` — `loading_spinner`, `docs/design-system.md`, §6.1 |
| `2e71553` | `fix(dev): correct PYTHONPATH separator in launch.json for Windows` — §8 |
| `729443d` | `docs(brand): document the Scrape Creators, insights-screen and design-system work` — esta misma actualización de este archivo |

Se hicieron primero en una rama aparte (`feature/brand-kit-connect-insights`, creada desde la punta de `fix/brand-kit-wizard`) tras dudar si este trabajo merecía una PR propia por ser un salto de alcance mucho más grande que "layout y paleta". El fundador consultó y decidió que **sí va bajo la misma PR #36**: `fix/brand-kit-wizard` se adelantó por fast-forward (`git merge --ff-only`, sin conflictos — la rama aparte no tenía ninguna historia que `fix/brand-kit-wizard` no tuviera) a los 5 commits, y la rama aparte quedó redundante (no borrada, por si acaso).

**Verificado antes y después del fast-forward:** `ruff check` limpio, 238/238 tests en verde, `reflex compile --dry` exitoso en ambos checkouts (worktree y `work/Qualify` — este último en la rama vieja `feature/brand-kit-wizard`, desincronizada de `fix/brand-kit-wizard` desde antes de esta sesión; ver la nota siguiente).

**Pendiente al momento de escribir esto:** `git push origin fix/brand-kit-wizard` — preparado, no ejecutado, a la espera de luz verde explícita del fundador antes de tocar la PR abierta.

> ⚠ **Las dos ramas del checkout principal y el worktree NO son la misma, y eso ya mordió una vez esta sesión.** `work/Qualify` (el checkout que corre el servidor de desarrollo) está en `feature/brand-kit-wizard` — la rama VIEJA, ya mergeada a `main` vía PR #34, congelada en `bdb19dc`. El worktree está en `fix/brand-kit-wizard`, que arrancó de `main` DESPUÉS de ese merge y va varios commits adelante (incluida una renombrada de `mentions_table` → `mentions_body` en `components.py`). Copiar un archivo entero del worktree al checkout principal sin revisar esto rompe el checkout principal contra su propio `components.py` — pasó una vez con `Qualify.py` (`ModuleNotFoundError` por el import de `mentions_body`), y el arreglo fue restaurar el `Qualify.py` propio del checkout principal (`git show HEAD:Qualify/Qualify.py`) y aplicarle solo el diff mínimo necesario, no una copia completa. Antes de copiar un archivo compartido entre ambos módulos verbatim, confirmar que las dos ramas no divergieron en él.
