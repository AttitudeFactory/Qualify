# Qualify — UX/UI y Design System

`[v3 — 2026-10-08]` · Aplica a la app Reflex en `Qualify/` · Código: `Qualify/ui/` (`tokens.py`, `layout.py`, `primitives.py`), `assets/qualify.css` (+ una hoja por dominio: `qualify-planner.css`, `qualify-brand.css`, `qualify-publish.css`, `qualify-inbox.css`), `assets/glass-nav.js`, `rxconfig.py`, `Qualify/test_design_system_guard.py` · Guía viva: ruta `/design` · Plan de la migración: `docs/plan-migracion-liquid-glass.md`

> **Regla de la casa:** el sistema vive en el código, no en este documento. Este doc explica *por qué* y *cuándo*; `Qualify/ui/` dice *cómo*, `/design` lo demuestra renderizado con el tema real y `test_design_system_guard.py` lo hace cumplir en CI. Si algo aquí contradice a `Qualify/ui/` o a `assets/qualify.css`, gana el código y hay que corregir el doc.

> **v3 (2026-10-08):** el sistema adopta el **material** del kit Liquid Glass (LiquidOS Studio 3.0) conservando nuestra paleta, nuestra tipografía y nuestras primitivas. Lo que cambia está en §3.4 (material y diales), §4.2 (el menú de vidrio), §5 (skin de Radix, regla de espera), §9 (guard, hojas por dominio) y §10.8–10.17 (decisiones D1–D14 del plan). Lo que no se menciona sigue igual que en v2.

---

## 0. Qué es esto y para quién

Qualify es la consola con la que el operador de uno o varios negocios locales (cafetería, agencia de viajes, inmobiliaria, microcentro comercial — Cúcuta/Táchira hoy) **escucha** lo que se dice de su negocio en redes y **actúa**: conecta cuentas, publica, elige qué contenido monitorear, revisa leads, lee la salud de su web. Un login = un negocio, sin switch. El operador está ocupado, entra entre tareas, casi siempre en laptop y a veces en el móvil.

De ahí las tres preguntas que toda pantalla debe responder, en este orden y sin scroll:

1. **¿En qué negocio estoy?** (el logo y el nombre del negocio encabezan el sidebar; debajo, «Con el respaldo de ◎ Qualify» enlaza al landing; en el teléfono, donde el sidebar es el cajón «Más», una etiqueta «Estás en {negocio}» sobre el título)
2. **¿Qué pasa?** (cifras, estados, señales)
3. **¿Qué hago ahora?** (una acción principal por pantalla)

**La premisa Liquid Glass (fundador, 2026-10-08).** El kit comprado (`reference/liquid-glass/`, vendorizado, no se edita) aporta **el material**: vidrio con refracción, relieve translúcido, brillo en el borde, su movimiento. Todo lo demás es nuestro y no se negocia: la **paleta** (acento teal, gris slate, tonos grass/amber/tomato — `rxconfig.py` sigue siendo el único sitio donde se cambia un color), la **tipografía** (IBM Plex Sans + Plex Mono, no la Inter del kit), las **primitivas** (`Qualify/ui/`) y el comportamiento (Radix). El tema arranca **en oscuro** (`appearance="dark"`), porque el material se definió en el Glass Lab del kit, que es dark-first; el claro sigue a un toggle de distancia con su propio material. Y una regla operativa que gobierna toda la migración: **no se crean componentes nuevos** — lo que una pantalla ya usa sin regla se trae al sistema (eso es migrar), lo que no existe ni en nuestras pantallas ni en el kit no se inventa (§9.1).

Este documento cubre: principios (§1), auditoría (§2), fundamentos/tokens y material (§3), layout (§4), componentes (§5), patrones (§6), escritura UX (§7), accesibilidad (§8), cómo extender (§9) y decisiones con su justificación (§10).

---

## 1. Principios

| # | Principio | Qué significa en la práctica |
|---|---|---|
| P1 | **Estado = color + icono/punto + palabra** | Nunca color solo. Sentimiento, salud de conexión, intento de publicación, sync: siempre `signal_pill`/`tone_badge` con la palabra escrita. El caso de tres estados ("desconocido") es la razón: color-solo lee como un "no" suave. |
| P2 | **La variante codifica la categoría** | Badge `soft` = estado · `outline` = identidad (plataforma, entidad) · `surface` = etiqueta/categoría · `solid` = solo la acción principal (botones). Ver §5.3. |
| P3 | **Una acción principal por pantalla** | Un solo botón `solid`; lo demás `soft`/`outline`/`ghost`. Si hay dos "principales", falta decidir. |
| P4 | **Islas flotantes, material por rol** | Toda superficie flota sobre el suelo de la app con la elevación de reposo (`T.ELEV_ISLAND`). Los grupos se separan por **aire**, no por líneas. El material depende del rol (§3.4): *island* = vidrio con blur, *card* = relieve translúcido sin blur, *control* = relieve. Y la elevación **significa** «esto responde»: sólo sube al hover lo que hace algo al pulsarlo (`card(interactive=True)`). |
| P5 | **Vacío y error dirigen** | Un estado vacío es una invitación a actuar (hecho + siguiente paso). Un error dice qué pasó y cómo se arregla; no se disculpa ni es vago. |
| P6 | **Cifras e identificadores tienen su tipografía** | Números tabulares (`q-nums`) en tablas y stat cards; `@handles`, ids y timestamps en mono (`q-mono`). El producto es señales y métricas; que se lean como tales. |
| P7 | **Tokens por rol, nunca por valor** | Una pantalla pide `T.TEXT_MUTED`, `tone="error"`, `T.PAGE_X`; no pide `"tomato"`, `"#0f172a"` ni `"2rem"`. Así el sistema se mueve una vez y en todos lados. Desde v3 lo comprueba un test (§9.1). |
| P8 | **Dos curvas, tres duraciones** | Muelle (`T.SPRING`) para lo que cambia de tamaño o de forma; ease (`T.EASE`) para color, opacidad y máscara. Desde v3 las dos curvas son las del kit (§3.4). Si un movimiento pide otra curva, es que no encaja en el sistema. |
| P9 | **Español, tú, sentence case** | La UI habla al operador de tú, en español latino neutro, con verbos concretos. Ver §7. |
| P10 | **El material es del kit; la paleta es nuestra** | Vidrio, relieve, brillo y curvas vienen de `liquidos.css` a través del puente `--lq-*` (§3.4). Ningún color del kit entra: cada tinte es una variable Radix. Un color escrito a mano es un fallo del guard. |
| P11 | **Skeleton = carga de contenido; spinner = trabajo en curso** | Lo que se está *leyendo* y va a aparecer se espera con la forma de lo que viene (`skeleton_*`); lo que se está *haciendo* (scraping, generar, publicar) se espera con un anillo junto a la frase que lo dice (`loading_spinner`). Siempre, sin excepciones; el guard prohíbe `rx.skeleton`/`rx.spinner` en páginas (§5.4). |

---

## 2. Auditoría del estado previo (2026-08-18) y qué cambió

Se revisaron los 8 módulos de página + `components.py` antes de tocar nada. Tras el merge de `main` (PR #15, motor de contenido) se migraron también las 4 rutas de `creative_pages.py` (`/brand`, `/create`, `/drafts`, `/drafts/[draft_id]`): su `_screen`/`_padded`/`_card`/`_error_callout` locales son ahora envolturas finas sobre `app_shell`/`page_body`/`card`/`callout`, y sus tres entradas de nav viven en `ui.NAV_ITEMS`. El acordeón de rutas de imagen (orden por `rank`, rutas bloqueadas visibles + deshabilitadas, `GENERATE` última con «NO RECOMENDADA») se conservó tal cual: es semántica de producto, no estilo.

| Hallazgo | Evidencia | Resolución |
|---|---|---|
| Shell duplicado 7 veces (8 con `creative_pages._screen`) | Cada `*_index()` repetía `rx.hstack(sidebar(), rx.vstack(topbar…))`; cada página tenía su `_topbar()` con la misma estructura y `padding="1.5rem 2rem 1rem 2rem"` (6×) | `ui.app_shell` + `ui.page_header` + `ui.page_body`. Las 8 páginas migradas. |
| Gutter hardcodeado | `padding="0 2rem 2rem 2rem"` ×14 y variantes; sin respuesta a móvil | Token CSS `--q-page-x` (2rem / 1rem < 900px), expuesto como `T.PAGE_X`. |
| Receta de tarjeta repetida | `_CARD` dict en vitrina; el mismo trío borde/radio/fondo inline en components, connections, inbox, auth | `ui.card` + tokens `BORDER`/`RADIUS_CARD`/`SURFACE_BG`. |
| 47 usos de `rx.color("gray", 10)` y 13 de `gray 8` sin nombre de rol | grep sobre `Qualify/*.py` | `T.TEXT_MUTED` / `T.TEXT_FAINT`, con la regla de que `FAINT` no es para texto que deba leerse. |
| Colisión de acento | Acento `violet`; TikTok `purple`; interés de lead `violet`; el acento se confundía con identidad y con etiqueta | Acento `teal` (§10.1); TikTok sigue `purple` pero ahora es distinguible; etiqueta → `tag()` gris `surface`. |
| `orange` para "TEMPORAL" y `amber` para "demo"/warning conviven | inbox `_sync_section` vs vitrina `_disclaimer` | Un solo tono `warn` (`amber`). `demo_notice` para el patrón "banda punteada". |
| Empty states y skeletons re-escritos 5 veces | connections, leads, clarity, inbox (×2) | `ui.empty_state`, `ui.skeleton_card`, `ui.skeleton_rows`. |
| Callouts de error con `rx.box(padding=…)` alrededor | connections, leads, inbox, publishing, clarity | `ui.callout(msg, "error"|"warn"|…)` dentro de `page_body`, sin wrapper. |
| Sin fuente definida (system-ui) | `rx.App()` sin `stylesheets`, tema sin `gray_color` | Plex Sans/Mono vía `assets/qualify.css`; `gray_color="slate"`. |
| Sin foco visible propio, sin `prefers-reduced-motion` | — | Ambos en `assets/qualify.css`. |
| Buenas prácticas ya presentes que se conservan | "estado nunca color-solo" en connections y vitrina; toggle de modo oscuro en toda página; copy en tú | Formalizadas como P1, §4.2 y §7. |

Lo que **no** se tocó a propósito: la lógica de estados, los VMs/providers y los tests puros; los internos de vitrina/clarity más allá del shell y los tokens.

### 2.1 Inventario previo a la migración Liquid Glass (2026-10-08)

Medido en `docs/plan-migracion-liquid-glass.md` §2 y resumido aquí porque explica el alcance de v3: 22 primitivas propias con uso real en páginas (`callout` 93, `card` 72, `tone_badge` 27, `page_header` 19…), pero **Radix llamado directo desde páginas en volumen** (`rx.button` 184, `rx.table` 92, `rx.select` 70, `rx.toast` 50, `rx.input` 48, `rx.badge` 48, `rx.segmented_control` 34…) y **estilo inline fuera del sistema** concentrado en el creativo (`creative_wizard_pages` 60 usos + 32 colores hex, `planner_page` 40…; `vitrina_page`, con 18, se retiró en m-24848515). La respuesta de v3 no es envolver esos 184 botones en una primitiva nueva: es un **skin global de Radix** (§5) que les da el material sin tocar su API, más un **guard** (§9.1) que impide que vuelvan los hex y los `rx.color(` sueltos, lote a lote.

---

## 3. Fundamentos (tokens)

Fuente de verdad: `Qualify/ui/tokens.py` (Python) + `assets/qualify.css` (CSS: tokens `--q-*`, puente `--lq-*`, diales `--q-lab-*`). Radix Themes provee las escalas; el kit provee el material; Qualify decide el rol.

### 3.1 Color

**Base (fijada una vez en `rxconfig.py`):** `appearance="dark"` (por defecto oscuro desde 2026-10-08, §10.10), `accent_color="teal"`, `gray_color="slate"`, `radius="medium"`, `scaling="100%"`, `panel_background="solid"`. Modo claro/oscuro: Radix, con toggle en cada header.

**Cómo se lee una escala Radix (1-12), y qué paso usar para qué:**

| Pasos | Rol | Ejemplo Qualify |
|---|---|---|
| 1-2 | Fondos de app / de superficie | panel de página = `--color-panel-solid` (opaco); el suelo (`T.GROUND`) y la tarjeta ya no son pasos planos sino material (§3.4) |
| 3-5 | Superficies interactivas (hover/activo) | lavado de zona del sidebar = `accent-a3`/`iris-a3`; hover de fila de tabla = `gray-a2`; fallback plano del nav activo = `accent-a4` |
| 6-8 | Bordes y separadores | borde = gray-5 (`BORDER`), fuerte = gray-7, foco = accent-8, línea de zona = `accent-a6` |
| 9-10 | Sólidos (botón, punto de estado, cifra) | `status_dot` = tono-9; cifra de stat = tono-10; tinte del material = `accent-9` |
| 11-12 | Texto | texto normal = gray-12; secundario = gray-10 (`TEXT_MUTED`); accent-11 para nav activo |

**Tonos semánticos** (`T.TONE_SCALE`, se piden por rol):

| Tono | Escala | Significa | Ejemplos |
|---|---|---|---|
| `accent` | teal | acción principal, marca, "lo que importa" | botón principal, nav activo, total de menciones |
| `ok` | grass | sano, positivo, entregado | conexión activa, sentimiento positivo, publicado |
| `warn` | amber | atención, degradado, temporal/demo | conexión degradada, "por verificar", banda demo |
| `error` | tomato | fallo, revocado, negativo | error de carga, conexión revocada, sentimiento negativo |
| `info` | blue | informativo, en curso | avisos de cuota, "sincronizando" |
| `neutral` | gray | desconocido, pendiente, neutro | sentimiento neutro, estado no mapeado |

Regla de degradación: un tono no mapeado cae en `neutral`, nunca en `accent` ni en alarma (`tone_scale` lo garantiza). El puente del kit respeta el mapa: `--lq-success`/`--lq-warning`/`--lq-danger` **son** `grass-9`/`amber-9`/`tomato-9` (§3.4).

**Identidad de plataforma** (`T.PLATFORM_SCALE`, siempre badge `outline`): Instagram `pink` · TikTok `purple` · Facebook `blue` · WhatsApp `green`. Son identidades, no estados: por eso nunca `soft` y nunca sin la palabra.

**Rol «hecho con IA»** (`T.AI_SCALE`, tokens `--q-ai-*`; m-25026602): lo que hace la IA en la
línea de tiempo usa la escala **iris**, la misma del lavado de la zona «Publica». Es un rol, no
un estado (el estado conserva su tono) y nunca va solo: siempre con el ✦ y una palabra. Detalle
en §5.10.1.

**Contraste:** texto solo en pasos 11-12 sobre fondos 1-3 (Radix garantiza ≥ 4.5:1). `TEXT_FAINT` (gray-8) es para iconos decorativos y placeholders, **no** para texto que deba leerse. Sobre vidrio claro el ratio no lo garantiza Radix sino el relleno del material — ver §8.

### 3.2 Tipografía

- **UI:** IBM Plex Sans (400/500/600/700). **Identificadores y cifras:** IBM Plex Mono (400/500). Cargadas desde Google Fonts en `Qualify.py`; las variables Radix `--default-font-family` / `--code-font-family` se sobreescriben en `assets/qualify.css`. Fallback: `system-ui`. El kit trae Inter; **no se adopta** (§10.11).
- **Escala Radix (`size` 1-9)** con estos usos fijos por página:

| Uso | Componente | Tamaño |
|---|---|---|
| Título de página (h1) | `page_header` → `rx.heading` | 6 |
| Título de sección (h2) | `section` / `empty_state` | 4 / 5 |
| Título de entidad en tarjeta | `rx.heading` | 4 |
| Cifra en stat card | `stat_card` | text 7 bold (no es heading) |
| Cuerpo | `rx.text` | 2 (3 en nav) |
| Meta / ayuda / nota | `rx.text` + `TEXT_MUTED` | 1 |

- `.q-nums` → `font-variant-numeric: tabular-nums` (tablas, cifras). `.q-mono` → mono a 0.92em (handles, ids, fechas técnicas). `heading-letter-spacing: -0.012em`.
- El skin del kit añade peso y tracking a tres piezas y nada más: botones (700, −0.01em), badges (650, +0.03em) y cabeceras de tabla (750, +0.08em, mayúsculas, 0.7rem).
- No hay display face: el título de página en Plex Sans 600 a size 6 **es** el display. Restricción deliberada (P4/P6): la personalidad va en el material, en el mono y en las señales, no en un titular decorativo.

### 3.3 Espacio, forma, elevación, movimiento

Valores vigentes en `assets/qualify.css` (los de v2 que cambiaron se indican):

| Token | Valor | Uso |
|---|---|---|
| `T.PAGE_X` = `--q-page-x` | 2rem (1rem < 900px) | gutter horizontal de toda página |
| `T.PAD_HEADER` | `1.5rem PAGE_X 1rem PAGE_X` | bloque del título |
| `T.PAD_BODY` | `1.25rem PAGE_X 2rem PAGE_X` | todo lo demás; el `1.25rem` de arriba separa el primer bloque de la línea del header (antes `0`: quedaba pegado; QUA-146) |
| `T.PAD_EMPTY` | `4rem PAGE_X` | empty states |
| `T.SIDEBAR_W` / `T.SIDEBAR_ZEN_W` | 232px / 72px | sidebar expandida · rail zen |
| `T.GAP` | 10px (6px < 900px) | aire entre islas, panel y borde de pantalla |
| `T.CONTENT_MAX` | 1440px | tope del cuerpo en pantallas muy anchas |
| Espaciado interno | escala Radix `spacing` 1-9 (4/8/12/16/24/32…) | `spacing="3"` dentro de tarjetas, `"4"` entre bloques |
| `T.RADIUS_ISLAND` = `--q-lab-radius` | **32px** (antes 0.875rem; en zen también 32px) | islas del sidebar, panel de página |
| `T.RADIUS_CARD` = `--lq-radius` | **20px** (antes 0.75rem) | `card`, overlays (popover, dropdown) |
| `T.RADIUS_CONTROL` = `--lq-radius-sm` | **12px** (antes 0.5rem) | campos, nav, thumbnails, skeleton, cápsula |
| `T.ELEV_ISLAND` = `--lq-shadow-soft` | `0 14px 36px` · claro `rgba(15,23,42,.08)` / oscuro `rgba(0,0,0,.18)` | reposo de toda superficie flotante |
| `T.ELEV_LIFT` = `--lq-shadow` | `0 24px 64px` · claro `.14` / oscuro `.28` | hover de una tarjeta **interactiva**; overlays |
| `T.ELEV_OVERLAY` = `--lq-shadow-overlay` | `0 40px 120px` · claro `.28` / oscuro `.55` | diálogos, drawer, sidebar móvil |
| `T.SPRING` = `--lq-ease-spring` | `cubic-bezier(.16, 1.18, .3, 1)` (antes `.34,1.4,.5,1`) | ancho, forma, colapso del rail, ascenso de tarjeta |
| `T.EASE` = `--lq-ease` | `cubic-bezier(.22, 1, .36, 1)` (antes `.22,.8,.25,1`) | color, opacidad, máscara, sombra |
| `T.DUR_FAST` · `T.DUR` · `T.DUR_SLOW` | 140 · 240 · 380 ms (sin cambio) | hover · elevación · colapso |
| `T.GROUND` / `T.SURFACE_BG` / `T.CARD_BG` | `--color-background` / `--color-panel-solid` / gray-2 | fondo bajo el suelo · panel de página · **legado**: la tarjeta ya no lo usa (`card` lleva `.q-card`, §3.4) |

Las sombras ya **no** salen de la rampa Radix (`--shadow-1..6`) sino de las dos del kit (`--lq-shadow-soft` reposo, `--lq-shadow` elevado) más una de overlay propia, cada una con su fuerza por tema en el puente. El par fondo/panel sigue siendo el de Radix (`--color-background` / `--color-panel-solid`): el panel de página es **opaco** a propósito (§10.12). Radios y curvas se leen de los tokens del kit: cambiar un dial o un `--lq-*` mueve todo el sistema.

Iconos: lucide, tres tamaños (`ICON_SM`=14 dentro de badges/botones size 1, `ICON_MD`=18 en nav y botones size 2, `ICON_LG`=40 en empty states). Nada intermedio.

### 3.3.1 Movimiento: el mismo de la landing (m-24840374, 2026-11-16)

Pasar de qualify.la a la app tiene que sentirse como un solo producto. La landing
(`qualify-landing`, `origin/main`) y la app ya compartían las dos curvas y las tres
duraciones (`--q-ease`, `--q-spring`, 140/240/380 ms: los mismos valores en
`src/styles/tokens.css` y en `assets/qualify.css`), así que no hay tokens nuevos. Lo que se
trae son las **entradas** de la landing (`src/styles/scenes.css`, `sc-*`, y la cascada
`.q-reveal--stagger` de `global.css`), su **cargador** (`LiquidLoading`, variante «trace») y
su **apagado global** con `prefers-reduced-motion`. Sólo CSS, sin dependencias nuevas.

**El vocabulario** (todo en `assets/qualify.css`, bloque «Motion vocabulary»). Cada
keyframe dice sólo **de dónde viene** el elemento; la regla del elemento elige duración,
curva y distancia con propiedades registradas que **no se heredan** (`--q-from-x` 0,
`--q-from-y` 18 px, `--q-from-scale` 1, `--q-from-opacity` 0, `--q-pop-from` 0,3), así un
bloque anidado nunca toma la distancia de su padre.

| Keyframe | Viene de (landing) | Qué hace |
|---|---|---|
| `q-enter` | `sc-in`, `sc-from-left`, `sc-from-right`, `.q-reveal` | desde un desplazamiento y una escala. **Sólo `transform`**: la regla de la app se mantiene — una entrada congelada deja el bloque un poco corrido, nunca invisible |
| `q-fade` | `sc-fade` | desde una opacidad (0 por defecto; 0,55 en `.q-content-ready`) |
| `q-pop` | `sc-pop` | desde una escala, sobre la propiedad `scale` (no pelea con el `transform` de Sonner ni de los scripts de arrastre) |
| `q-pulse` | `sc-pulse` | sube a 1,12; siempre un número par de veces y `alternate`, para terminar en reposo |
| `q-ping` | el «ping» del cargador de scraping | un anillo que sale y se apaga (`box-shadow`) |
| `q-trace` | `LiquidLoading` «trace» (`lq-trace`) | un trazo se dibuja, se queda y se vacía por el otro extremo |

**Emparejamiento** (lo viejo de la app → lo de la landing):

| Antes (app) | Dónde | Ahora | Par en la landing |
|---|---|---|---|
| `q-settle` (8 px, 40 ms entre bloques, tope 160 ms) | entrada de toda página (`page_body`), auth, listas | `q-enter`: 18 px, **70 ms** entre bloques, desde el 6.º todos a 350 ms | `.q-reveal--stagger` |
| `q-step-in-next` / `q-step-in-back` (8 px) | cuerpo del paso a paso (§4.5) | `q-enter` con `--q-from-x` ±18 px | `sc-from-right` / `sc-from-left` |
| `q-conv-pop` (6 px abajo, 97 %) | burbujas de Conversaciones y WhatsApp (`.q-chat-msg`) | `q-enter`: el cliente entra por la izquierda, tú por la derecha, desde 90 %, con muelle; **sólo la burbuja más nueva** (la última fila del hilo): abrir un chat no repite el historial. El contenedor (`.q-wa-scroll`) recorta en horizontal | `si-in-left` / `si-in-right` (StepInbox) |
| `q-progress-in` | `progress_panel` y su comentario de etapa | `q-enter` + `q-fade` (sube 18 px y aparece) | `.q-reveal` |
| `q-content-in` (0,55 → 1) | `.q-content-ready` | `q-fade` con `--q-from-opacity: 0.55` | `sc-fade` |
| `q-orbit-rise` / `q-orbit-fade` | píldoras del «+» (`orbit_menu`) | `q-enter` (12 px) + `q-fade`; con movimiento reducido sólo `q-fade` | `sc-in` / `sc-fade` |
| `q-deck-enter` | la tarjeta de la baraja del Brand Kit | `q-enter` (14 px, 96 %) + `q-fade` | `sc-in` |
| `q-toast-pop` | toasts | `q-pop` desde 0,82 | `sc-pop` |
| `q-cr-slide-land` | una diapositiva soltada (Generador) | `q-pop` desde 1,07 | `sc-pop` |
| `q-spin` (anillo del kit) | `loading_spinner` en toda la app, también dentro de botones ocupados | `q-trace` + `q-pulse` sobre la marca Q (`MARK_Q`/`MARK_WAVES`); en `sm` (botones ocupados) `q-trace-run`, 1,6 s sin pausa, para que se lea «trabajando» | `LiquidLoading` «trace» |
| `q-conv-breathe` (infinito) | punto de no leído (Chats) · punto de grabación | `q-pulse`: el de no leído late 4 veces y para; el de grabación late mientras graba (dice «grabando») | `sc-pulse` |
| `q-flicker` (infinito) | llama de «Por probar» (Planificador, tarjetas) | `q-pulse` 6 veces y para | `sc-pulse` |
| `q-pulse` del Planificador (anillo) · `q-clip-wait` | punto «en vivo» · botón de un clip que carga | `q-ping` (con `--q-ping-color`) | ping del cargador |
| `q-cr-sheen` · `q-progress-sweep` | tarjeta fantasma del Generador · barra de progreso | `q-shimmer` (eran el mismo barrido, duplicado) | — (barrido del kit) |
| — (nuevo) | icono de `empty_state` | `q-pop` con muelle (sólo escala: nunca parte de invisible) | `sc-pop` del final de cada escena |
| apagado global con `transition-duration: 0.01ms` y sin tocar retardos | toda la app | como la landing: animaciones a 0,01 ms, **retardos a 0**, transiciones a 0,01 ms (no los 0 s de la landing: así `transitionend` sigue llegando a vaul y Sonner); botones y `choice_card` no suben ni se hunden | `global.css` (KIT:869-879), `LinkButton` |
| `q-embers` / `q-frost` (infinitos) | chips de temperatura del Planificador | brasas 2 × 2,4 s, escarcha 2 × 2 s (menos de 5 s); cada vuelta empieza y termina en el aspecto de reposo, así nada salta al parar | regla de la landing: lo que se mueve solo para antes de 5 s |
| `q-step-in-*` en JS (±8 px) | paso a paso del menú de WhatsApp (`whatsapp_menu_state._guided_settle`) | ±18 px, igual que `.q-step-body` (que además recorta en horizontal: el desliz no saca barra en 360 px) | `sc-from-*` |
| — (la 404 de Reflex, en inglés y sin salida) | página no encontrada (`not_found_page.py`, ruta 404 de Reflex) | «Esta página no existe» con la escena líquida, variante «charco» (`q-nf-*`: nivel y vaivén del líquido, la Q que se mece, dos ondas; 4,8 s y para en reposo); la página entra con `.q-settle`; «Ir al inicio» lleva siempre a `/`, que ya envía a cada quien a su sitio (Inicio con sesión, la marca sin ella) | `NotFoundLiquid` «puddle» + `404.astro` |

**Se quedan como están** (la landing no tiene nada equivalente; son de una interacción
propia de la app): `q-shimmer` (skeleton, del kit), `q-progress-creep` (avance de una
espera sin progreso real), `q-drawer-in` (panel lateral), la cápsula y la etiqueta zen del
sidebar (`q-glass-shimmer`, `q-glass-travel-*`, `q-glass-label-shimmer`, del kit), la
baraja y el ordenar del Brand Kit (`q-deck-nudge`, `q-deck-float`, `q-zone-*-pop`,
`q-fly-*`, `q-rank-flash`, `q-rank-pulse`), `q-conv-pulse` (fila con mensaje nuevo),
y `q-slow-hint-show`, que no
es movimiento sino un aviso a los 12 s (por eso conserva su retardo aun con movimiento
reducido). Los botones ya se movían como los de la landing (suben 2 px, `scale(0.975)` al
pulsar): sin cambios.

**No aplica** (de la landing, no se porta):

| Landing | Por qué |
|---|---|
| `HeroDevice` (`hero-orbit`, `hero-device-float`, `hero-wave`) | es la escena de marketing del teléfono; la app no tiene hero |
| Escenas de las secciones (`FeatBrand`, `FeatCapture`, `FeatCreate`, `FeatInbox`, `FeatPublish`, `FeatTrends`, `StepBrand`, `StepInbox`, `StepSchedule`: `fb-*`, `fk-*`, `fc-*`, `fi-*`, `fp-*`, `sb-*`, `si-typing`, `ss-*`) | coreografías de demostración con tiempos fijos de varios segundos; de ellas se toman sólo las piezas sueltas (`sc-*`, `si-in-*`) de arriba |
| Revelado al hacer scroll (`.js-reveal`, `src/scripts/liquid.ts`) | depende de JS (IntersectionObserver); en la app la cascada corre al montar la página |
| `ScrapeLoader` / `ScrapeLoaderV2` | lo maneja un script (saltos al azar, progreso por `data-progress`) |
| `LiquidLoading` «charge» y «drops» | variantes alternativas de la landing; la app usa «trace», la de por defecto |
| `NotFoundLiquid` «pour» | variante alternativa; la 404 de la app usa «puddle», como la landing (tabla de arriba) |

Demo en vivo: `/design` → «Movimiento y elevación» (botón «Repetir»).

### 3.4 Material (Glass Lab)

**El material lo definen los diales del Glass Lab del kit, uno por token** (`--q-lab-*` en `assets/qualify.css`, bloque «Glass Lab dials»; refracción y frecuencia también en `LAB_REFRACTION`/`LAB_FREQUENCY` de `ui/layout.py`, que renderiza el filtro SVG `#q-refraction` una vez por `app_shell`). Son los valores del fundador del 2026-10-08. Para probar otro material: mover los diales en el Lab (`reference/liquid-glass/LiquidOS-Studio-v3.0/index.html#builder`) y copiar los números aquí — **no** se aproxima a mano.

| Dial del Lab | Token | Valor |
|---|---|---|
| Material | fórmula de `--q-glass-fill` | **Liquid** (luz que sigue al puntero + degradado a 145°) |
| Backdrop scene | `.q-ground` | **Noir** (sobre la escala de gris, §4.1) |
| Backdrop blur | `--q-lab-blur` | **0 px** |
| Surface opacity | `--q-lab-opacity` | **0.09** (9 %) |
| Saturation | `--q-lab-saturation` | **120 %** |
| Corner radius | `--q-lab-radius` | **32 px** |
| Edge highlight | `--q-lab-border` | **0.34** (34 %) |
| Refraction | `--q-lab-refraction` / `LAB_REFRACTION` | **21** (escala del `feDisplacementMap`) |
| Surface frequency | `--q-lab-frequency` / `LAB_FREQUENCY` | **9** → `baseFrequency` 0.009 (dial / 1000) |
| Optical depth | `--q-lab-depth` · `--q-lab-depth-blur` | **100 %** → opacidad 1, blur de la capa 6 px (`max(1, round(depth / 18))`, fórmula del Lab) |
| Material tint | `--q-lab-tint` · `--q-lab-tint-mix` | **el acento** (`--accent-9`, teal), nunca un hex; mezcla = opacidad × 100 % / 2.2 ≈ 4,1 % |

El Lab es dark-only: el oscuro es su material «liquid» al pie de la letra (blanco a opacidad + 0.035 → tinte a opacidad / 2.2, borde al dial de edge, highlight interior y sombra del Lab). El **claro** conserva la misma estructura (mismo tinte, mismo edge, misma saturación, misma capa de profundidad) con un blanco más lechoso: el degradado arranca en blanco al **64 %** (`opacidad + 0.55`) y cae a tinte sobre blanco al 40 %, con la luz del puntero al 60 %. Todo esto son variables `--q-glass-*` por tema, no dos árboles.

**Material por rol (D5/D6).** `backdrop-filter` se paga por elemento y por píxel; por eso no todo es vidrio:

| Rol | Dónde | Receta (`assets/qualify.css`) | ¿Blur? |
|---|---|---|---|
| **island** | islas del sidebar (`.q-island`); popover, dropdown, hover card, lista de select; diálogo, alert dialog y `drawer`; toast; `page_header` sticky | `--q-glass-fill` + borde `--q-glass-edge` + highlight `--q-glass-hi`/`--q-glass-lo` + `--q-glass-shadow`; en las islas, además, la capa de profundidad (`::before`, un conic highlight refractado por `#q-refraction` y desenfocado 6 px) | sí — islas: dial (0 px) + saturate 120 %; overlays 28 px / 150 %; diálogo 30 px / 160 % (y el fondo oscurecido a 8 px); header 18 px / 140 %; cápsula 18 px / 160 %, etiqueta zen 18 px / 155 % |
| **card** | `ui.card` (`.q-card`), tabla `surface`, callout `surface`, banda del stepper | `--q-card-fill` (claro: blanco 78 → 52 %; oscuro: 7,5 → 3 %), hairline `--q-card-edge`, highlight `--q-card-hi`, `T.ELEV_ISLAND`; al hover (solo `interactive`) borde `--q-card-edge-hover` + `T.ELEV_LIFT` | **no** |
| **control** | botón `soft`/`outline`/`surface`, icon button, campo, text area, select, segmented, badge, barra de progreso | `--q-control-fill/-edge/-hi/-shadow`; los campos, `--q-field-fill` (pozo hundido) y `--q-field-fill-focus` | **no** |
| **panel** | el panel de página (`.q-panel`) | `--color-panel-solid`, opaco, radio 32 px, borde `T.BORDER` | no |
| **suelo** | `.q-ground` (`app_shell`) | escena Noir: degradado a 140° de `--color-background` → gray-3 → gray-5, una luz blanca arriba a la derecha, dos resplandores de zona (`accent-a4`/`iris-a4`, en oscuro a6) y rayas diagonales casi invisibles | no |

**Nunca blur en grids** (tiles del planificador, galería de borradores, catálogo) y **tope de 8 superficies con `backdrop-filter` por pantalla**; el lote 6 lo mide.

**El puente `--lq-*` (D2).** Los tokens del kit existen en `.radix-themes` con sus propios nombres, **mapeados a Radix** para que la paleta siga siendo nuestra y claro/oscuro salgan gratis:

| Token del kit | En Qualify |
|---|---|
| `--lq-bg` / `--lq-bg-elevated` | `--color-background` / `--color-panel-solid` |
| `--lq-text` / `-soft` / `-faint` | `gray-12` / `gray-11` / `gray-9` |
| `--lq-accent` / `--lq-accent-2` | `accent-9` / `accent-8` (el «cian» del kit es nuestro paso claro del acento) |
| `--lq-success` / `--lq-warning` / `--lq-danger` | `grass-9` / `amber-9` / `tomato-9` |
| `--lq-glass-alpha` / `-hover` · `--lq-blur` · `--lq-saturation` · `--lq-border-alpha` | los diales (`--q-lab-opacity` (+0.04 al hover), `--q-lab-blur`, `--q-lab-saturation`, `--q-lab-border`) |
| `--lq-radius-sm` / `--lq-radius` / `--lq-radius-lg` | 12px / 20px / `--q-lab-radius` (32px) |
| `--lq-shadow-soft` / `--lq-shadow` / `--lq-shadow-overlay` | por tema (tabla §3.3) |
| `--lq-ease` / `--lq-ease-spring` | las dos curvas (§3.3); `--q-ease`/`--q-spring` las leen |
| `--lq-duration` · `--lq-control-height` | 420 ms · 46 px — **solo registro**: las duraciones siguen siendo 140/240/380 ms y los controles conservan la escala de tamaños de Radix |

**`liquidos.css` NO se carga en runtime.** Cargarlo tal cual era dañino: sus resets de `:root`/`body`/`button`/`a` son dark-only (fondo `#070a12`, Inter, foco cian) y pelearían con Radix, y sus reglas `.lq-*` apuntan a marcado que Reflex nunca emite. En su lugar, **cada componente del kit se redibuja sobre el selector Radix que lo renderiza** (bloque «Liquid Glass: Radix skin», §5) con los valores del kit escritos en estos tokens. El kit vendorizado es contra lo que se hace diff cuando una regla del skin se pone en duda.

---

## 4. Layout

### 4.1 El shell: islas de vidrio sobre el suelo

```
  ┌────────────┐ ┌────────────────────────────────────────────────┐
  │▣ Negocio ▾⇤│ │ Título de página [badge]        [acciones] [◐] │ ← page_header (vidrio, sticky)
  │Respaldo de │ │ subtítulo muted                                │
  │  ◎ Qualify │ │                                                │
  └────────────┘ │ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
  ┌────────────┐ │ │stat_card │ │stat_card │ │stat_card │  ← page_body (gutter PAGE_X)
  │ Inicio     │ │ └──────────┘ └──────────┘ └──────────┘         │
  └────────────┘ │ callout (si hay error de acción)               │
  ┌────────────┐ │ ┌────────────────────────────────────────────┐ │
  │ ATIENDE    │ │ │ card / tabla / lista …                     │ │
  │ Por respond│ │ └────────────────────────────────────────────┘ │
  │ WhatsApp   │ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ PUBLICA    │ │                                                │
  │ Crear publ.│ │                                                │
  │ Por aprobar│ │                                                │
  │ Tu semana  │ │                                                │
  │ Publ. ahora│ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ Resultados │ │                                                │
  │ Creadores ·│ │  (· = «Pronto», en texto)                      │
  │ Oportunid.·│ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ TU NEGOCIO │ │                                                │
  │ Tu marca   │ │                                                │
  │ Tus product│ │                                                │
  │ Tus redes  │ │                                                │
  │ Config.    │ │                                                │
  │ ───────────│ │                                                │
  │ ⇥ Salir    │ │                                                │
  └────────────┘ └────────────────────────────────────────────────┘
```

```python
from .ui import app_shell, page_header, page_body

def leads_index() -> rx.Component:
    return app_shell(
        page_header("Clientes interesados", "Personas que te dejaron sus datos para que las contactes", badge=rx.badge("12", ...)),
        page_body(_body()),
    )
```

- `app_shell(*children, rail=True)`: el **suelo** de la app (`.q-ground`, la escena Noir de §3.4) con dos cosas flotando encima — el sidebar (`nav` sticky, islas de vidrio) y el panel de página (`main`, **opaco**, `--color-panel-solid`, radio 32 px, `T.ELEV_ISLAND`). Renderiza una vez el filtro SVG `#q-refraction` del que todas las islas refractan. **El panel es el contenedor de scroll, no el documento**: mide exactamente `calc(100vh - 2 * gap)` y una página lo llena con `flex`/`height`, nunca con su propio `100vh`. `rail=False` deja el panel solo (el wizard del Brand Kit). El ítem activo se deriva de la ruta.
- `page_header(title, subtitle=None, *actions, badge=None, kicker=None, title_size="6")`: h1 + subtítulo; a la derecha, `actions` y el toggle de modo. Desde v3 es **una lámina de vidrio pegada arriba del panel** (`.q-page-header`: `position: sticky`, `--q-header-fill`, blur 18 px): el título y las acciones siguen al alcance mientras el cuerpo pasa por debajo. `badge` va **junto al título** y describe la página ("demo", un conteo), nunca es una acción.
  - **Encabezado de página en el teléfono (≤ 640 px, m-25142793): se recoge al bajar.** Arriba de la página se ve todo: «Estás en {negocio}», el `kicker` si lo hay, el título y el subtítulo. Al bajar, el chip, el `kicker` y el subtítulo se van con el contenido y **solo queda fija una línea**: título (+ `badge`), las `actions` y el toggle de modo **en la esquina superior derecha**, con el mismo vidrio del header (fija ≈ 60 px, antes ≈ 210 px). El título termina en «…» antes de empujar el toggle a otra fila; si las `actions` no caben junto al título bajan a una segunda fila **dentro** de la línea fija. Cómo: un solo DOM (arriba → barra → subtítulo); en el teléfono la lámina `.q-page-header` pasa a `display: contents` y la que es `sticky` es `.q-page-head-bar` (un `sticky` sólo se pega dentro de su padre: la barra tiene que ser hija de la columna del panel, no de un envoltorio que se va). Sigue habiendo **una** superficie con `backdrop-filter` en el header (la barra); arriba y subtítulo llevan el mismo relleno sin blur. La barra respeta `env(safe-area-inset-top)`. `--q-sticky-header-height` (`glass-nav.js`) mide lo que de verdad queda fijo (la barra en el teléfono) y quien necesite el borde del header desde JS usa `T.pinned_header_js(...)`, no `.q-page-header` a secas. Desde 641 px la lámina entera sigue fija como siempre (una rejilla que coloca título, subtítulo, acciones y toggle donde los ponía la fila anterior). Fuera de alcance: la cabeza del asistente (`step_head`).
- `page_body(*children, spacing="4", align_items="start")`: aplica el gutter y el tope de ancho, y hace **entrar los bloques escalonados** al cargar (`.q-settle`, 40 ms entre hijos, tope a partir del quinto; sólo `transform`, nunca opacidad — una entrada no puede ser el único camino al contenido). Los hijos **no** llevan padding horizontal propio.
- `section(title, *children, description=None, actions=())`: h2 con descripción y acciones para dividir un cuerpo largo.

### 4.2 El sidebar: vidrio líquido, zonas y modo zen

El menú sigue el mapa de `docs/ux-guia-navegacion.md` §3 (NAV-1, m-24842957): está ordenado por los **trabajos del dueño** —qué me toca hoy, atender, publicar, cómo me va— y al pie lo que se toca poco. Las dos zonas teñidas son las mismas dos de antes, con nombre nuevo y el mismo tinte («Escuchas» → **Atiende**, «Publicas» → **Publica**).

| Isla | Contiene | Tinte (lavado bajo el vidrio) |
|---|---|---|
| Negocio (arriba) | una fila: logo de Tu marca (ficha neutra, `contain`; sin logo, la tienda) · nombre ▾ (abre «Cambiar de negocio» con 2+ negocios; con uno no es botón) · «Contraer el menú» 44×44 (⌘ .). Contraído, el logo **es** «Expandir el menú», arriba, y al pasar el puntero muestra el icono de panel. En el cajón del teléfono, «Cerrar el menú» (×) ocupa el lugar de Contraer. Debajo, «Con el respaldo de ◎ Qualify» → `LANDING_URL` (m-24976899) | neutra |
| Inicio | Inicio (`/`) | neutra |
| **Atiende** (`listen`) | Por responder · WhatsApp | `accent` alfa 3, línea alfa 6 |
| **Publica** (`publish`) | Galería · Crear publicación · Por aprobar · Tu semana · Publicar ahora · Anuncios | `iris` alfa 3, línea alfa 6 |
| Resultados | Resultados · Creadores «Pronto» · Oportunidades «Pronto» | neutra |
| **Tu negocio** (pie) | Tu marca · Tus redes · Configuración · Salir | neutra |

**Entradas «Pronto» (N10):** llevan la palabra «Pronto» en texto (`tone_badge("Pronto", "neutral")`, que el modo zen oculta junto con la etiqueta) y **siempre son un enlace**: abren su propia pantalla, que dice qué viene y ofrece un botón a algo que funciona hoy (`empty_state(action=)`). Nunca una fila muerta ni una pantalla vacía. Ninguna demo ni herramienta del equipo (`/design`) entra al menú del cliente.

**El menú es vidrio líquido** (`assets/qualify.css` «Liquid glass menu» + `assets/glass-nav.js`; adaptado de `real-liquid-glass-os-effect.html`, un dock horizontal, a nuestras islas verticales):

- **Islas** (`.q-island`, `_island` en `layout.py`): material *island* de §3.4 — relleno `--q-glass-fill`, borde al dial de edge, highlight interior, capa de profundidad refractada, `backdrop-filter` con los diales. El tinte de zona es un **lavado alfa debajo del vidrio** (`--q-zone-tint` → alfa 3, `--q-zone-line` → alfa 6, puestos por `T.zone_tint`/`T.zone_line` como custom properties): un paso opaco taparía el suelo que el vidrio debe refractar. `flex-shrink: 0`: una isla nunca se encoge para caber (con `overflow: hidden` recortaría sus filas); el nav scrollea.
- **Luz del puntero**: el relleno «liquid» tiene una luz suave que sigue al cursor (`--q-pointer-x/y`, escritas por el script en la isla bajo el puntero). Apagada con puntero grueso (táctil) y con `prefers-reduced-motion`.
- **La cápsula** (`.q-glass-blob`, una por isla, **dentro** de la isla — obligado: `backdrop-filter` hace de cada isla un stacking context, y una cápsula fuera sólo podría pintar sobre toda la isla o debajo, nunca entre su relleno y sus filas). Es el único resalte del menú: **su estado de reposo es la fila activa** (`aria-current="page"` en el link de la fila), sin palabra. Vuela a la fila bajo el puntero con la coreografía del dock (la palabra sale primero, el vidrio arranca a los ~40 ms, la palabra nueva crece a los ~235 ms), se deforma en la dirección del viaje (`skewY` ±2,5°, estirón y asentamiento; menos que los 7° del dock porque nuestras filas son anchas), y el icono de la fila se levanta 1 px. Al cambiar de isla, la anterior se apaga y la nueva entra deslizándose por el borde por el que llega. **Teclado igual que puntero** (`focusin`/`focusout`). Al salir, vuelve a reposo tras 120 ms.
- **La etiqueta zen** (`.q-glass-label`): con el rail contraído, el nombre aparece al lado del rail como una segunda pieza de vidrio con **cuello** apuntando a su fila, creciendo desde un desenfoque (`blur(5px)` → 0). Fija en el viewport (el nav recorta su overflow), sólo con puntero fino. Sustituye al tooltip `::after` de v2, que el `overflow: hidden` de la fila recortaba y nunca se veía.
- **Sin script = fallback plano**: hasta que `glass-nav.js` marca el nav con `data-glass`, la fila activa lleva `accent-a4` y el hover `gray-a3` (`.q-sidebar:not([data-glass])`). Un documento sin JS sigue diciendo dónde estás.
- **Carga del script**: `rx.el.script(src="/glass-nav.js", async_=True)` **dentro de `sidebar()`**, no en `rx.App(head_components=…)` — medido 2026-10-08, `head_components` pasa por react-helmet y no inyecta nada en el build de desarrollo (§10.14). El script se guarda de correr dos veces (`window.__qGlassNav`), delega todo al documento y se re-asienta con un `MutationObserver` filtrado (sólo mutaciones que tocan un sidebar; nunca las de sus propios nodos) y un `ResizeObserver`, así sobrevive a que Reflex remonte el sidebar en cada cambio de ruta y a la transición de ancho del zen. **Sólo después de la hidratación** (`rx.cond(_after_hydration(), …)`, 2026-11-14): desde m-24993451 la fila activa ya viene en el HTML prerenderizado, y si el script pone la cápsula antes de que React hidrate, React descarta el documento entero (error #418), vuelve a añadir `__reflex_global_styles` detrás de los estilos de emotion y los controles del teléfono aparecen en escritorio. Ningún script que toque el DOM de React debe correr antes de la hidratación: envuélvelo en `rx.cond(_after_hydration(), …)` (`Qualify/ui/layout.py`) como `glass-nav.js`, nunca en `head_components` ni en el `<head>`. El mismo archivo mide `--q-sticky-header-height` (PASOS-10), que ahora también se calcula después de la hidratación; hasta entonces vale el respaldo de 8rem.

Tres reglas que sostienen esto:

1. **El tinte es superficie, no señal.** Se queda en alfa 3 (lavado) y alfa 6 (línea): agrupa, pero no puede confundirse con un estado (P1/P2). Subirlo es una decisión consciente, no un ajuste.
2. **Resultados y Tu negocio viven fuera de las zonas de color**: miden cómo le va al negocio o son lo que el negocio *es*, no conversación ni publicación.
3. **Salir es el único control de sesión** (`1 login = 1 negocio`, sin switch). Sin sesión (`/design`) el nombre cae a «Qualify».

**Zen** (`NavState.zen`, botón en la isla del negocio o `⌘ .`): el rail se contrae a 72 px con muelle, las etiquetas se **revelan con máscara** (`clip-path`) en vez de fundirse, y el nombre aparece en la etiqueta de vidrio de arriba. Todo el colapso es **una clase** (`q-zen`) en el `nav`: las reglas viven en `assets/qualify.css`, no en condicionales de Python — así el navegador puede animarlo y no hay dos árboles que mantener. El estado vive en la sesión del servidor, nunca en el navegador: persistir en el cliente exigiría clave namespaced por tenant y purga en logout (regla firmada), y para un modo de vista no compensa.

**Móvil (< 640 px):** el sidebar es un overlay fijo cerrado por defecto, abierto por el botón hamburguesa (`_mobile_nav_toggle`, fuera del sidebar porque el drawer empieza cerrado) con un fondo que lo cierra al tocar fuera; elegir una página también lo cierra. **Decidido (decisión 5, 2026-10-23):** el botón ☰ se sustituye por la barra inferior de §4.4, cuyo «Más» abre este mismo cajón; con el PR de código de NAV-7 el ☰ desaparece.

### 4.3 Reglas de página

1. Toda página de negocio lleva el sidebar completo y el toggle de modo en el header. Solo `/login`, `/registro` y el wizard del Brand Kit (`rail=False`) no llevan sidebar.
2. El header no scrollea con contenido pesado — y ahora literalmente: es sticky. Lo que "vive" arriba son controles de página (selector de cuenta, botón de actualizar), no contenido. En el teléfono sólo queda fija su línea de título, acciones y toggle (m-25142793, §4 `page_header`).
3. Densidad: tablas para listas homogéneas y comparables (leads, menciones); tarjetas para entidades con estados y acciones propias (conexiones, reels). No mezclar en la misma lista.
4. Responsive: el gutter baja a 1rem y el aire entre islas a 6px por debajo de 900px; grids usan `rx.breakpoints(…)`; tablas envuelven en `overflow_x="auto"`; por debajo de 640px el sidebar es drawer (§4.2) y, con NAV-7, aparece la barra inferior (§4.4).
5. **Toda fila del sidebar usa la misma geometría** (`_nav_row`): el envoltorio — link o botón — no lleva padding ni fondo propio (el fondo es la cápsula). Es lo que garantiza que en zen todos los iconos caigan en la misma columna y que la cápsula mida lo mismo en todas las filas.
6. **Presupuesto de vidrio:** ≤ 8 superficies con `backdrop-filter` por pantalla (el shell gasta: islas del sidebar + header sticky; un overlay abierto, una más). Nada de vidrio dentro de grids.

### 4.4 Barra inferior del celular (patrón nuevo · NAV-7, m-24842964)

> **Estado:** patrón **construido** en `feat/m-24842964-barra-inferior` (`_bottom_bar()` en `Qualify/ui/layout.py`, bloque «Bottom bar» de `assets/qualify.css`, muestra en `/design`, `Qualify/test_bottom_bar.py`), pendiente de que el fundador apruebe esta sección y haga merge. Decisión 5 del fundador (2026-10-23, `docs/ux-guia-navegacion.md` §6 y §7): «Sí, barra inferior de 4 accesos (Inicio · Por responder · Crear · Tu semana) + «Más». Se documenta primero en `docs/design-system.md` como patrón nuevo y luego se construye.» Es el **único componente nuevo** que admite la épica de UX (`docs/epica-ux-navegacion-experiencia.md`); no abre la puerta a otros (§9.1-8). El PR de código de NAV-7 se abre **después** de que el fundador apruebe esta sección, y la implementa tal cual o la corrige aquí primero.

**Para qué.** El dueño usa Qualify con una mano, entre cliente y cliente. Hoy, en el celular, todo el menú está detrás de ☰: llegar a lo de todos los días cuesta dos toques y estirar el pulgar hasta la esquina de arriba. La barra deja **lo que más usa a un toque y al alcance del pulgar**; lo demás sigue en el cajón de siempre, detrás de «Más».

```
  ┌──────────────────────────────────────┐  360 px
  │ Título de página           [acción]  │ ← page_header (sin ☰ encima)
  │                                      │
  │  … cuerpo de la página …             │
  │                                      │
  │  (relleno inferior = alto de barra)  │
  │ ╭──────────────────────────────────╮ │
  │ │ [casa] [chat]3 [vara] [cal]1 [≡]2│ │ ← barra: isla opaca, radio 32 px
  │ │Inicio  Por   Crear  Tu     Más   │ │
  │ │      responder      semana       │ │
  │ ╰──────────────────────────────────╯ │
  │          ▔▔▔ (zona segura) ▔▔▔        │
  └──────────────────────────────────────┘
```

**Cuándo aparece.** Exactamente donde el sidebar deja de verse y pasa a cajón: **≤ 640 px** (el mismo `@media (max-width: 640px)` de §4.2). Por encima de 640 px **no existe** (`display: none`, fuera del orden de tabulación): el sidebar ya da esos accesos y una segunda navegación los duplicaría. Un solo punto de corte para «modo celular»: si algún día sube (la ficha del ticket habla de «< 768 px»), suben juntos el cajón y la barra, nunca uno solo — ver «Pendiente de confirmar» abajo. Solo con sesión y `rail=True`: no hay barra en `/login`, `/registro` ni en el asistente de la marca, igual que no hay sidebar.

**Los cinco accesos** (en este orden, de izquierda a derecha; nada más, nunca configurable):

| # | Texto | Icono (lucide, `ICON_MD`) | Destino | Contador (N11) |
|---|---|---|---|---|
| 1 | Inicio | `house` | `HOME_ROUTE` | — |
| 2 | Por responder | `messages-square` | `RESPOND_ROUTE` | el de «Por responder», tono `warn` |
| 3 | Crear | `wand-sparkles` | `/create` | — |
| 4 | Tu semana | `calendar-days` | `/planner` | el de «Tu semana», tono `neutral` |
| 5 | Más | `menu` | abre el cajón (`NavState.toggle_mobile_nav`) | publicaciones por aprobar (lo único con contador que no está ya en la barra: los chats de WhatsApp van dentro de «Por responder»); tono `neutral` |

- **Mismos nombres, mismos iconos, mismas rutas que el sidebar (N1).** La barra no define rutas propias: lee las constantes de `layout.py` (`HOME_ROUTE`, `RESPOND_ROUTE`, …), así cuando Inicio, «Por responder» o «Resultados» cambien de ruta (NAV-4, ATENDER-1, RESULTADOS-5), la barra los sigue sola. «Crear» es la **forma corta aprobada** de «Crear publicación» (la decisión 5 la nombra así); es la única forma corta de la barra.
- **Los contadores son los del menú** (`NAV_COUNTERS` y `PendingState`, NAV-6 · m-24842963): mismo `tone_badge`, mismo `badge_text` (nada en 0, «99+» pasado el tope), mismo latido. La barra no consulta nada por su cuenta. «Más» cuenta solo lo que **no** está ya a la vista en la barra, para que ningún pendiente se cuente dos veces.
- **«Más» reemplaza al botón ☰ flotante** (`_mobile_nav_toggle`), que hoy tapa la esquina del título. El cajón, su fondo y su comportamiento no cambian (fuera de alcance de NAV-7); solo cambia el botón que lo abre. Al abrirse, el cajón queda **por encima** de la barra.

**Anatomía y tokens** (todo existente; ningún token, color ni sombra nuevos):

| Parte | Regla |
|---|---|
| Contenedor | `<nav>` fijo abajo: `left`/`right` = `T.GAP` (6 px en celular), `bottom` = `calc(T.GAP + env(safe-area-inset-bottom))`. Es una **isla**: radio `T.RADIUS_ISLAND` (32 px), sombra `T.ELEV_ISLAND`, borde `T.BORDER` |
| Material | **opaco**, `--color-panel-solid` — el mismo del botón ☰ de hoy y del panel de página (§10.12). Sin `backdrop-filter`: el contenido pasa por debajo al desplazarse y el texto de la barra tiene que leerse igual sobre cualquier foto; además no gasta presupuesto de vidrio (§4.3-6) |
| Celdas | cinco del **mismo ancho** (`flex: 1`), icono arriba y texto debajo, centrados. A 360 px: (360 − 2 × 6) / 5 ≈ **69 px de ancho**; alto mínimo **56 px** (60 px si algún texto parte en dos líneas). Toda la celda es el objetivo, nunca solo el icono: **≥ 44 × 44 px siempre** (N12) |
| Texto | `rx.text` size 1, peso 500, `gray-11`; **puede partir en dos líneas** («Por / responder», «Tu / semana»), interlineado 1.1, **nunca** puntos suspensivos ni recorte |
| Icono | `ICON_MD` (18 px), `gray-11` |
| Activo | la celda de la página actual: icono y texto `accent-11`, peso 600, y una cápsula `accent-a4` detrás del icono, radio `T.RADIUS_CONTROL` (el mismo resalte plano del menú sin script, §4.2). Tres señales a la vez — color, peso y forma — nunca solo el color (P1). Se deriva de la ruta igual que en el sidebar: `/planner/…` marca «Tu semana». Si la página actual no es ninguna de las cuatro (Tu marca, WhatsApp, Por aprobar…), el resalte va a **«Más»**: siempre hay una celda que dice «estás por aquí» |
| Contador | `tone_badge(texto, tono)` en la esquina superior derecha del icono (`position: absolute`, como `.q-menu-count` de hoy): no agranda la celda ni empuja el texto. Nada se dibuja en 0 |
| Capas | `z-index: 50`: por encima del panel; por debajo del fondo del cajón (55), del cajón (60), de los diálogos, `drawer` y toasts de Radix. Un diálogo o un `drawer` abierto tapa la barra; la barra nunca tapa un diálogo |
| Movimiento | solo cambio de color/peso con `T.DUR_FAST` y `T.EASE`; la cápsula de vidrio del sidebar **no** se porta a la barra. Nada se mueve con `prefers-reduced-motion` |

**No tapa contenido ni botones principales.** El panel de página reserva abajo el alto de la barra: en ≤ 640 px, `page_body` lleva un relleno inferior de `alto de la barra + 2 × T.GAP + env(safe-area-inset-bottom)` (una variable CSS del shell, p. ej. `--q-bottom-bar-h`, en `assets/qualify.css`; ninguna página la escribe a mano). Lo que hoy se pega al pie de una pantalla (barras de acción de un asistente, pie de un formulario largo) se pega **encima** de la barra, no detrás. El pie del `drawer` no cambia: el `drawer` es pantalla completa en el celular y queda por encima de la barra.

**Zona segura.** En teléfonos con barra de gestos el borde inferior lo ocupa el sistema; `env(safe-area-inset-bottom)` solo vale algo si la página declara `viewport-fit=cover` en su `<meta name="viewport">`. El PR de código lo añade (hoy la app no lo declara) y comprueba que el header y los bordes no se metan bajo la muesca.

**Teclado del celular.** Mientras un campo de texto tiene el foco, la barra se oculta (el teclado ya ocupa media pantalla y la barra quedaría flotando sobre él); vuelve al soltar el foco. Si en el PR de código esto no se logra solo con CSS (`:has(:focus)` sobre el shell), se mide y se documenta aquí antes de añadir script.

**Accesibilidad.**

- Es un `<nav aria-label="Accesos rápidos">`, distinto del `<nav aria-label="Secciones">` del sidebar, y va en el documento **después** del `<main>` (el lector de pantalla y el teclado llegan primero al contenido).
- Las cuatro primeras celdas son **enlaces** reales (`<a href>`), con `aria-current="page"` en la activa; «Más» es un **`<button>`** con `aria-expanded` (abierto/cerrado) y `aria-controls` apuntando al sidebar — no navega, abre.
- El texto se ve siempre: ninguna celda es solo un icono. Con contador, el nombre hablado es el del menú (`entry_aria_label`: «Por responder: 3 personas esperan tu respuesta»); «Más» usa el de hoy del botón ☰ (`menu_button_aria_label`) ajustado a lo que cuenta.
- Foco visible: el `:focus-visible` de siempre (outline 2 px `accent-8`), dibujado **dentro** de la celda para que el borde redondo de la isla no lo recorte.
- Nada solo al pasar el mouse (N12): cualquier estilo de `:hover` va dentro de `@media (hover: hover)`.
- Contraste: texto `gray-11`/`accent-11` sobre `--color-panel-solid` = pasos 11 sobre fondo opaco, dentro de lo que Radix garantiza (§8), en claro y en oscuro.

**Textos** (cliente, `qualify-copy-es`): «Inicio» · «Por responder» · «Crear» · «Tu semana» · «Más» y «Accesos rápidos» (solo lectores de pantalla). Ninguno insinúa que Qualify actúa solo (N13): son lugares, no acciones automáticas.

**Dónde vive en el código** (para el PR de código; carril NAV):

- `Qualify/ui/layout.py`: una lista `NAV_BOTTOM` con los cuatro accesos tomados de las mismas tuplas `Item` del sidebar, y `_bottom_bar()` renderizada por `app_shell` en lugar de `_mobile_nav_toggle()`. El estado sigue en `NavState` (servidor, sin `LocalStorage`: la barra no guarda nada en el navegador).
- `assets/qualify.css`, bloque del shell (es pieza compartida, no de un dominio, §9.1-9): la barra, el relleno inferior del panel y el `@media (max-width: 640px)`.
- `/design` (`styleguide_page.py`): un ejemplo a 360 px con un contador en «Por responder» y el resalte en «Tu semana».
- Un test offline (junto a `test_nav_one_name.py`) que falle si la barra usa un texto, icono o ruta distintos del sidebar (salvo «Crear»), si tiene más o menos de cinco celdas, o si un contador no sale de `NAV_COUNTERS`.

**Hecho cuando** (criterios del ticket m-24842964): a 360 px se ven los 4 accesos + «Más», cada objetivo ≥ 44 px, y la barra no tapa contenido ni botones principales; por encima de 640 px no aparece; revisión local `ux-designer` (`qualify-ux` §6) antes de abrir el PR; prueba a 360 px de cada ruta tocada (N12); `just ci-lint` y `just ci-test` en verde; capturas claro / oscuro / 360 px en el PR.

**Pendiente de confirmar por el fundador** (no bloquea esta documentación; se resuelve al aprobarla):

1. **Punto de corte: 640 px o 768 px.** La ficha del ticket dice «< 768 px»; la app pasa a cajón a 640 px. Este patrón elige **640 px** para que nunca convivan sidebar y barra (entre 641 y 767 px se verían las dos). Si se prefiere 768 px, el cajón sube con ella en el mismo PR.
2. **«Por responder» en dos líneas.** Cabe en dos líneas a 360 px sin recorte. La alternativa sería una forma corta («Responder»), que rompería N1 con el sidebar; por eso no se propone.


### 4.5 Marco de paso a paso (patrón nuevo · PASOS-1, m-24852240)

> **Estado:** **aprobado por el fundador el 2026-10-25** («Sí, tal cual»,
> `docs/epica-ux-pasos-navegacion-interna.md` §4); falta construirlo (PASOS-2, m-24852241). La
> evidencia está en `docs/ux-navegacion-pasos-2026-10-24.md` (H1–H8): 10 asistentes arman a mano su
> «Paso N de M» y su fila «Atrás · Siguiente», y en ninguno quedan a la vista.

**Para qué.** Que el dueño sepa siempre **dónde está, cuánto le falta, cómo vuelve y cómo sigue**,
sin tener que desplazarse. Es la **anatomía del `drawer`** (§5.8: cabeza fija, cuerpo que se
desplaza, pie fijo) llevada también a los asistentes de página completa, con la misma cabeza en
todos.

```
  ┌──────────────────────────────────────┐  360 px
  │ ‹ Tus publicaciones    Paso 2 de 4   │ ← CABEZA (fija): volver con destino + paso real
  │ ▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░ │   + barra de avance
  │ ¿Qué quieres decir?                  │   + nombre del paso (el h1)
  ├──────────────────────────────────────┤
  │  … contenido del paso (se desplaza)… │ ← CUERPO
  ├──────────────────────────────────────┤
  │ [ Atrás ]        [   Siguiente   ]   │ ← PIE (fijo): en el celular ocupa el lugar
  │        Seguir después                │   de la barra inferior (§4.4)
  └──────────────────────────────────────┘
```

**Cuándo se usa.** En todo flujo de **más de un paso**. Si es de página completa (Tu marca, Crear
publicación, Publicar ahora, el menú automático de WhatsApp), lleva el marco entero. Si va dentro
de un `drawer` (agregar producto, programar, promoción, mensaje aprobado), solo pasa la **cabeza**
al encabezado fijo del cajón; el pie del cajón ya es este pie. Un formulario de un solo paso no
lleva marco.

**La cabeza** reemplaza a `page_header` mientras dura el asistente; no se suma a él, así el título
de la página no ocupa media pantalla.

1. **«‹ destino»** arriba a la izquierda: el nombre del lugar al que vuelve (N7), por ejemplo
   «‹ Tus publicaciones», «‹ Tu semana» o «‹ Inicio». Toma `?volver=` (N4) y, si no lo hay, el
   módulo del menú. Está en **todos** los pasos, también en el primero, porque es la salida
   (arregla H1). Dentro de un cajón, la salida es el ✕ «Cerrar», que ya existe.
2. **«Paso N de M»** a la derecha, en texto, con **M real**: los pasos que se saltan no cuentan.
   Debajo va una **barra de avance** de 4 px en acento: es texto y forma a la vez, nunca solo color (P1).
3. **El nombre del paso**, en palabras del dueño, es el único `h1` de la pantalla (§8).
   `stepper()` se queda como **opción** debajo del título en escritorio cuando los pasos se pueden
   recorrer de a saltos (Tu semana). En el celular no se muestra: la barra lo reemplaza.

**El pie** es la isla opaca de la barra inferior (§4.4): mismo material, mismo radio, misma altura
reservada (`--q-bottom-bar-h`) y la misma zona segura.

1. A la izquierda va **«Atrás»** (soft, gris): retrocede un paso y conserva lo escrito. No aparece
   en el paso 1, donde la salida está en la cabeza.
2. A la derecha va el **botón principal** (sólido, ancho, ≥ 44 px): «Siguiente», y en el último
   paso un verbo que dice quién actúa y qué pasa (N13): «Crear», «Programar para el jueves»,
   «Publicar en Instagram». Si el paso todavía no es válido, el motivo se lee **junto** al botón
   (regla de §5.8). En escritorio el motivo va **en su propia fila**, encima de los botones y a
   todo el ancho del pie (m-24993023): en una sola fila, un panel estrecho dejaba su columna en
   nada y el texto tapaba «Atrás». Sin motivo, el pie sigue siendo una sola fila.
3. Debajo, **«Seguir después»** (ghost): guarda lo que lleva el dueño y lleva a **Inicio** en todos
   los asistentes (N2, decisión del fundador 2026-10-25). Inicio muestra lo que quedó a medias con
   «Seguir».
4. **En el celular (≤ 640 px) la barra inferior de accesos se esconde** mientras el marco está
   montado, y el pie ocupa su lugar. Abajo nunca hay dos islas. Se hace con una clase en
   `.q-ground`, igual que hoy con el teclado (`qualify.css` «Bottom bar»), no con estado de Python.
   Con el teclado abierto, el pie también se aparta.
5. **En escritorio** el pie se pega al borde inferior del panel (`position: sticky; bottom`), como
   `.q-rv-savebar--editing`. No suma superficies de vidrio (§4.3-6).
6. **Con un contenedor de 480 px o menos** (un panel lateral o una ventana partida en una pantalla
   ancha) el pie **se apila como en el celular**: motivo, luego «Atrás» y el botón principal a lo
   ancho, y «Seguir después» debajo. Lo mide el propio pie (`.q-step-slot` es el contenedor de una
   *container query*), no el ancho de la ventana.

**Comportamiento al cambiar de paso.**

- El cuerpo **vuelve arriba**: se desplaza `main.q-panel`, nunca `window`. El foco pasa al `h1` del
  paso nuevo, para que el lector de pantalla anuncie dónde está.
- **Cada paso tiene dirección** (`?paso=N`, escrita con `pushState` y leída en `on_load` y en
  `popstate`). El «atrás» del celular o del navegador retrocede un paso; en el paso 1 sale al
  destino de la cabeza. Nunca saca del módulo (N5).
- **Salir nunca borra.** Lo escrito se conserva en el estado y se retoma al volver (N6).
- **Movimiento:** el cuerpo del paso entra con `q-enter` (§3.3.1), desplazándose 18 px en la dirección del
  avance: desde la derecha al ir adelante, desde la izquierda al volver (`data-dir`). La barra
  avanza con `--q-dur` y `--q-ease`. Con `prefers-reduced-motion` no hay desplazamiento, solo el
  cambio.

**Implementación sugerida (PASOS-2).**

- `step_frame(head, *body, foot)` en `Qualify/ui/layout.py`, junto a `app_shell`; `step_head(...)` y
  `step_foot(...)` en `Qualify/ui/primitives.py`.
- Una muestra en `/design` → «Flujo por pasos».
- La regla en `test_design_system_guard.py`: ningún asistente arma a mano su «Paso N de M» ni su
  fila «Atrás · Siguiente».
- Los nombres de las funciones los fija `reflex-ui-engineer`; lo que no cambia es la anatomía.
---

## 5. Componentes

Todo en `Qualify/ui/primitives.py` salvo lo indicado. Radix (`rx.button`, `rx.input`, `rx.select`, `rx.table`, `rx.dialog`, `rx.alert_dialog`, `rx.tooltip`, `rx.switch`, `rx.accordion`, `rx.callout`, `rx.segmented_control`, `rx.popover`, `rx.dropdown_menu`, `rx.toast`) se usa **directamente** cuando no hay regla Qualify que encapsular; las primitivas existen solo donde hay una regla. Desde v3, **Radix directo no significa Radix crudo**: el bloque «Liquid Glass: Radix skin» de `assets/qualify.css` redibuja cada componente del kit sobre el selector `.rt-*` que lo renderiza (`.lq-button` → `.rt-Button`, `.lq-field` → `.rt-TextFieldRoot`, `.lq-dialog` → `.rt-BaseDialogContent`…), con los valores del kit y los tokens del puente. **Las semánticas siguen siendo las de Radix** — variantes, `color_scheme`, `size`, foco, Esc, focus trap — sólo cambia el material (§10.9). Las dos excepciones del kit que **no** se adoptan: `rx.skeleton` y `rx.spinner` directos (§5.4).

### 5.1 Superficies

| Primitiva | Cuándo | Notas |
|---|---|---|
| `card(*children, padding="1.25rem", interactive=False, **props)` | cualquier bloque delimitado | **material card** (`.q-card`, §3.4): relieve translúcido dentro del panel opaco, hairline `--q-card-edge`, highlight interior, radio 20 px, `ELEV_ISLAND`, **sin blur**. `interactive=True` añade `.q-lift` (sube 2 px, borde `--q-card-edge-hover`, `ELEV_LIFT`) — sólo si al pulsarla pasa algo. Los `props` inline siguen ganando a la clase (`skeleton_card` pasa `background="transparent"`) |
| `stat_card(label, value, tone="accent", hint=None)` | una cifra con su etiqueta | tono solo en la cifra; `q-nums`; es una `card` |
| `kv(label, value, mono=False)` | par etiqueta/valor en un panel de detalle | `mono=True` para ids |
| `mono(text)` | identificador inline | handles, ids, timestamps |

### 5.2 Estado (la señal)

| Primitiva | Cuándo | Anatomía |
|---|---|---|
| `signal_pill(label, tone)` | **default** para cualquier cosa con ciclo de vida: sentimiento, sync, intento de publicación | punto tono-9 + palabra, badge `soft` `radius=full` |
| `tone_badge(label, tone, icon=None, size="1")` | verdicto a nivel tarjeta o celda que debe escanearse | icono 12px + palabra, `soft` |
| `status_dot(tone)` | solo como parte de otra composición | nunca solo (P1) |
| `sentiment_badge(var)` | sentimiento | `positive`/`POS→ok`, `negative`/`NEG→error`, `NEU→neutral`, `""→"Sin analizar"` (QUA-92: pendiente de análisis, nunca se confunde con NEU), resto `neutral` |

Skin del kit (`.lq-badge`): todo `rx.badge` es píldora (radio 999px), peso 650, tracking 0.03em, con el hairline de su propio tono (`soft` → `accent-a5`, `surface` → `accent-a6`; Radix re-mapea `--accent-*` al `color_scheme` del badge, así que el hairline es siempre del tono correcto).

### 5.3 Identidad y etiquetas

| Primitiva | Variante | Cuándo |
|---|---|---|
| `platform_badge(platform)` | `outline` + color de plataforma | plataforma de una cuenta/mención. Acepta `str` o `Var` |
| `tag(label)` | `surface` gris | interés, fuente, scope, tema — metadata, no estado |
| `removable_pill(label, on_remove, icon=None, leading=None, suggested=False)` | `surface` gris con ✕; `suggested=True` → `soft` acento | un valor que el operador cura y puede quitar: un hashtag, una palabra vetada, un archivo subido. `suggested` marca lo que propuso el producto y el operador aún no escribió. Nunca un tono: una pill quitable no es un veredicto |
| `pill_editor(items, draft=, on_draft_change=, on_add=, on_remove=, placeholder=)` | pills + input con Enter / "+" | una lista que se arma de a un valor (listas del Brand Kit: ejemplos, CTAs, palabras vetadas, claims). `on_remove` recibe el índice. Sustituye a los textarea "uno por línea" |
| badge de conteo (`rx.badge(..., variant="soft", color_scheme="gray")`) | `soft` gris | "12" junto al título «Clientes interesados» |

**Tabla de decisión — ¿qué badge?**

| Es… | Usa | Nunca |
|---|---|---|
| un estado que cambia | `signal_pill` / `tone_badge` | `outline`, `solid` |
| quién/qué es (plataforma, entidad) | `platform_badge` (`outline`) | `soft` con tono |
| una categoría/etiqueta libre | `tag` (`surface`) | color de tono |
| la acción principal | `rx.button` `solid` | un badge |

### 5.4 Feedback y espera

**La regla de espera (fundador, 2026-10-08; D12):** hay dos formas de esperar y no son intercambiables. **Skeleton = carga de contenido, SIEMPRE**: algo se está *leyendo* y va a aparecer en ese sitio — el placeholder tiene la forma de lo que viene. **Spinner = trabajo en curso**: algo se está *haciendo* — scraping, generación, sync, publicación, subida, clonado de voz — y no hay «forma» todavía, hay trabajo; el cargador va junto a la frase que dice qué pasa. Un spinner sobre una lista vacía no dice nada; un skeleton sobre un scraping mentiría. Las dos puertas son `ui.skeleton_card`/`ui.skeleton_rows` y `ui.loading_spinner`; `test_design_system_guard.py` falla el build ante un `rx.skeleton(` o un `rx.spinner(` en una página (§9.1). Un `rx.button(loading=…)` es un prop, no una llamada, y sigue permitido.

| Primitiva / Radix | Cuándo | Cuándo no |
|---|---|---|
| `callout(message, tone="info", icon=None)` | feedback **persistente y ubicado**: error de carga en lugar de la lista, error de acción **encima** de la lista (la lista sigue siendo válida), aviso de cuota. Material card en su tono (`.rt-CalloutRoot.rt-variant-surface`: radio 16 px, hairline `accent-a6` del tono) | confirmaciones transitorias → `rx.toast` |
| `demo_notice(message)` | contenido de demo/temporal (banda punteada `warn`) | errores |
| `rx.alert_dialog` | confirmar acciones destructivas o irreversibles (desconectar, borrar). Lámina `lq-dialog` (§5.8) | acciones reversibles |
| `rx.tooltip` | aclarar un marcador ("por verificar"). Vidrio **oscuro en los dos temas**, como lo dibuja el kit (`--q-tooltip-fill`) | contenido esencial |
| `empty_state(icon, title, description, action=None)` | lista vacía / sin configuración | como error |
| `skeleton_card(lines=3)` / `skeleton_rows(n, height, width, radius)` | **carga de contenido, SIEMPRE**: una lista, un detalle, un catálogo, un calendario, una vista previa. Shimmer del kit (`.lq-skeleton` → `.rt-Skeleton`: bloque `gray-a3` con una banda de luz que lo cruza cada 1,7 s, radio control) | trabajo en curso → spinner; `rx.skeleton` directo desde una página (guard) |
| `loading_spinner(size="sm"\|"md"\|"lg")` | **trabajo en curso**, junto a la frase que dice qué pasa. También dentro de un botón ocupado (`rx.cond(busy, loading_spinner("sm"), rx.icon(…))`) | contenido que solo está cargando → skeleton; `rx.spinner` crudo (guard) |
| `progress_panel(title, detail, value=None, steps=None, creep_seconds=30)` | espera que **bloquea** el paso (no se puede seguir hasta que termine): análisis de voz, búsqueda de referentes, sugerencia de hashtags. Con `value` (0-100) muestra progreso real; sin él, avanza con el tiempo hasta ~90 % y desaparece al terminar. `steps` son las etapas: la que está en curso es el comentario **encima** de la barra, sin spinner al lado (`progress_step_row`, 2026-10-02). Barra con el skin `lq-progress`: pista hundida `--q-field-fill`, relleno degradado del acento con resplandor. **Es el único loader del Brand Kit** (2026-10-02) | fuera del Brand Kit, una espera corta sin etapas → `loading_spinner`; carga de una lista → skeleton; dentro de un botón o una línea de estado → `loading_spinner("sm")` |

Iconos por defecto del callout: `error`/`warn` → `triangle-alert`, `ok` → `check`, `info` → `info`. Un callout de error lleva `role="alert"`; los demás `role="status"`.

`loading_spinner` (`.q-spinner`) es el cargador de la landing (`LiquidLoading` «trace», §3.3.1; antes el anillo del kit): la marca Q dos veces, tenue (`accent-a5`) y en acento (`accent-11`), y el acento corre por los trazos — la Q parte por parte, luego las ondas —, se queda y se vacía; 2,8 s por vuelta. Dentro del botón ocupado del paso a paso los dos tonos pasan a blanco translúcido y `accent-contrast`. Con movimiento reducido, quieto y dibujado entero. Su color sale de las escalas del tema, así que **se adapta solo a claro/oscuro: no existe una variante de tema que elegir**. La única variante real es `size` — `sm` (1.25rem) en línea junto a texto, `md` (2.25rem, por defecto) una espera aislada, `lg` (3.5rem) una espera de panel completo. Demo en vivo: `/design` → «Estados de pantalla».

**Toasts** (`rx.toast`, Sonner): la misma lámina de vidrio que los overlays (`lq-toast`: `--q-overlay-fill`, radio 16 px, blur 28 px, `ELEV_LIFT`) entrando por la esquina inferior derecha con el pop de muelle (`q-pop` desde 0,82, sobre `scale`, que no pelea con el `transform` de Sonner).

### 5.5 Botones (Radix directo, con el skin del kit)

El skin es el `lq-button` del kit sobre `.rt-Button`/`.rt-IconButton`: radio 14 px (10 px en size 1), peso 700, y:

- `solid` (por defecto, acento) = `lq-button--primary`: **degradado del acento** (accent-9 → 10 → 8 a 135°), highlight interior y sombra teñida `accent-a5`; al hover sube 2 px y la sombra crece. **Una** por pantalla — la acción que responde "¿qué hago ahora?".
- `soft` / `outline` / `surface` = el botón de **vidrio** (material control: `--q-control-edge` + `--q-control-hi` + `--q-control-shadow`; al hover, borde más marcado y 2 px arriba). `soft`: secundarias (Desconectar, Cancelar). `outline`: terciarias.
- `ghost` = `lq-button--ghost`: sin relieve; dentro de tablas/filas y para el toggle de modo.
- Pulsado: `scale(0.975)`. Deshabilitado: sin sombra ni movimiento.
- No disponible pero enfocable: `q-button-off`. Es un `soft`/`outline`/`surface` con `aria-disabled` (nunca el `disabled` nativo, para que el lector de pantalla llegue a su motivo). Lleva los mismos grises que el principal deshabilitado: fondo `gray-a3`, texto `gray-a8`, borde `gray-a5`, sin elevarse al pasar el ratón y con `cursor: not-allowed`. Nunca un acento atenuado con opacidad, que parece activo (m-24993023, «Probar solo la parte 1»).
- Destructiva: `soft` + `color_scheme=T.tone_scale("error")`; en el diálogo de confirmación, `solid` tomato (el degradado toma la escala del `color_scheme`).
- Tamaños: `2` por defecto; `1` dentro de badges de sesión/filas; `3` solo en empty states.
- Icono + texto: icono a la izquierda, `size=16` (o `ICON_SM` en size 1). Nunca icono solo sin `aria-label`.
- Estados: `loading=Var` en cualquier botón que dispare I/O; `disabled` cuando la precondición no se cumple **y** el motivo está visible cerca.

### 5.6 Formularios (Radix directo, con el skin del kit)

- Campos, text areas y el trigger del select tienen el look `lq-field`: un **pozo de vidrio hundido** (`--q-field-fill`, radio 12 px, hairline interior) que se aclara al foco con el anillo del acento (`accent-a8` + halo `accent-a3` de 4 px). El switch encendido es un degradado del acento con el pulgar flotando (`lq-switch`); el segmented control, una pista hundida con una pestaña de vidrio (`lq-segmented`, radio 15/11 px) — sustituye a cualquier `q-flow-switch` casero.
- **Menú de fuentes del generador (`.q-source-seg`, m-24985141):** el mismo `lq-segmented` con ícono lucide y nombre («Tus productos · Tu Galería · Subir · Publicaciones · Inspiración»). Regla de ancho: nunca scroll lateral ni texto cortado. La pista toma el ancho de su fila y cada opción el de su contenido (nunca `min-width: max-content`); la opción elegida muestra ícono y nombre y las demás solo el ícono, con su nombre en `aria-label` y `title`. Así caben las cinco en un celular de 375 px y en el drawer de 512 px. Como el indicador deslizante de Radix supone columnas iguales, se oculta y la opción elegida lleva la misma pestaña de vidrio. 44 px de alto; flechas, `aria-checked` y foco de Radix.
- **Fotos por categoría en el generador (m-24985141):** Producto · Fondo · Estilo, la lista única del Clip, el Avatar y la Imagen, y el Carrusel diapositiva por diapositiva — ver [ux-fotos-por-categoria.md](ux-fotos-por-categoria.md).
- **Avatar y fila de avatares (`.q-avatar-stack` sobre `rx.avatar`, m-24985141):** el `lq-avatar`/`lq-avatar-stack` del kit traído al skin (regla §9.1-8): 38 px, redondo, borde claro de 2 px, degradado del acento detrás de una foto que falta, iniciales en negrita de 0.8rem; en la fila cada uno se monta un tercio del diámetro (13 px) sobre el anterior, más que los 10 px del kit, que casi no se notaban; el borde de 2 px separa una burbuja de la otra. Uso: la fila «Producto» del panel del generador. Las burbujas muestran todas las referencias elegidas (fotos del producto, inspiración, videos con su póster o «▶», audios con «♪», lo subido, la Galería y las publicaciones) y solo caen a las fotos del producto elegido si no hay ninguna: hasta 4, o 3 y una «+N» que se lee «y N referencias más»; el grupo se lee «N referencias elegidas». Modo angosto (`.q-cr-product-chip` es un contenedor; ≤ 300 px, la columna izquierda de escritorio, unos 214 px): 2 burbujas de 24 px y su «+N», que cuenta todo lo oculto; el nombre en una línea con «…» y el nombre completo en `title`; el botón solo con su ícono, de 44×44, con `aria-label` y `title`. La fila nunca baja de línea ni se monta: el nombre se encoge (`flex: 1 1 0`, `min-width: 0`) y las burbujas y el botón no.
- Etiqueta visible encima (`rx.text size=2 weight=medium`), ayuda debajo en `size=1 TEXT_MUTED`. Placeholder = ejemplo, no etiqueta (excepción documentada: `/login` y `/registro`, donde interferir con el autocompletado del navegador está prohibido por el fallo firmado §6.1 — allí el placeholder es la etiqueta y así se queda).
- `name`, `type` y `required` nativos: el navegador valida y autocompleta.
- Error de envío en `callout("error")` **encima del formulario**, no como toast.
- Selects para elegir entre entidades del tenant (cuentas conectadas); switches para monitorear/activar; búsquedas con `rx.input.slot(rx.icon("search"))`.

### 5.7 Tablas y listas

- `rx.table.root(variant="surface")` lleva el look `lq-table`: el marco es **material card** (radio 16 px, `--q-card-fill`, hairline y highlight), las cabeceras van en mayúsculas pequeñas y tenues (0.7rem, 750, tracking 0.08em, `gray-10`) y cada fila tiene un susurro de hover (`gray-a2`). Cabeceras en sentence case en el código — el skin las pone en mayúsculas.
- Numéricas alineadas a la derecha y con `q-nums`. Identidad en la primera o segunda columna (`platform_badge`, `mono` para handles); estado con `signal_pill`.
- Texto largo (captions) truncado con `text_overflow="ellipsis"` a un `max_width` fijo.
- Envolver en `rx.box(overflow_x="auto")`.

### 5.8 Overlays y flujos por pasos: `drawer`, `stepper`, diálogos (QUA-118)

Todo lo que flota sobre la página es material **island** (§3.4) y lleva el skin del kit: popover, dropdown, hover card y la lista del select son `lq-glass` (radio 20 px, `--q-overlay-fill`, blur 28 px, `ELEV_LIFT`); diálogo y alert dialog son la **lámina `lq-dialog`** (radio 24 px, `--q-dialog-fill`, blur 30 px, `ELEV_OVERLAY`) sobre un fondo oscurecido y desenfocado 8 px (`.rt-BaseDialogOverlay`).

| Primitiva | Cuándo | Notas |
|---|---|---|
| `drawer(*children, open=, on_open_change=, title=, description=None, footer=None, width="32rem", icon=None, side="right")` | un flujo más largo que un diálogo, que el operador recorre sin perder la pantalla de fondo: la asignación del Planificador | **la misma lámina `lq-dialog`** pegada al **borde derecho** (`.q-drawer`: `--q-dialog-fill`, hairline a la izquierda, `ELEV_OVERLAY`), ancho fijo en escritorio y **pantalla completa en móvil**; construido sobre `rx.dialog`, así Esc, el clic en el fondo, el focus trap y el ARIA vienen de Radix; el cuerpo se desplaza, título y pie quedan fijos (el pie es transparente: la lámina ya es el fondo). Uno a la vez, nunca anidado. Con `icon`, la cabecera lleva un glifo de acento antes del título. `side="bottom"`: la hoja desde abajo (variante descrita bajo esta tabla) |
| `stepper(labels, current=, completed=, on_select=None, icons=None)` | la cabecera de ese flujo: los pasos en orden | check lleno = completado (clicable con `on_select`, para volver a corregir); anillo = actual; número = aún no alcanzado (nunca clicable, así nada se confirma con un paso incompleto). El check y el paso actual con glifo llevan el degradado del acento. Etiquetas estáticas, estado dinámico. En móvil (y dentro del drawer) solo se lee la etiqueta del paso actual. Con `icons` (un glifo por paso) el paso no alcanzado muestra su glifo en lugar del número — el Planificador lo usa así |

**Variante `drawer(..., side="bottom")` — la hoja desde abajo (RF-02 m-25119460, RF-13 m-25120327).** La misma lámina `lq-dialog` del `drawer`, que sube desde el borde inferior: ancho completo, tan alta como su contenido (85 % de la pantalla como máximo), redondeada arriba (`.q-drawer--bottom`). Es una **variante**, no un componente nuevo: el comportamiento (Esc, fondo, focus trap, ARIA) es el del `drawer`; solo cambia el borde. Se justifica por la regla §9.1-8: el kit no trae una hoja, pero sí el diálogo que la hace, y la usan dos piezas de «Ideas para tus reels» (la hoja «Filtros» del teléfono y «Tus competidores» en el teléfono). Uso: una elección corta que se abre desde un chip en el teléfono. Al cerrarse (Esc, fondo, «Cerrar», «Listo» o una elección), el foco vuelve al botón que la abrió (`on_close_auto_focus` con un script que lo enfoca). Demo: `/design` → «Hoja desde abajo».

**La barra de filtros de «Ideas para tus reels» (RF-13).** Una sola regla propia, de layout: la *container query* de abajo. Se retiraron los `.q-rf-*`, y el precedente de un contenedor con modo angosto es `.q-cr-product-chip` (§5.6): todo es Radix con el skin y las primitivas de arriba.

- **Cada filtro es un chip de una palabra** (`rx.button` del skin, `size="2"`, 44 px de alto; `surface` sin filtrar y `soft`, con lavado de acento, cuando filtra). Sin filtro muestra el nombre corto (`CHIP_LABELS`: «Canal», «Tipo», «Cuenta», «Duración»). Con filtro muestra su valor: «Instagram», «2 cuentas», y los valores cortos de `CHIP_VALUES`: «Te inspiran» o «Compiten contigo» para Tipo, y «< 15 s», «15–30 s», «30–60 s» o «> 60 s» para Duración. El nombre accesible y `title` llevan las palabras largas y **siempre contienen la palabra visible** (WCAG 2.5.3, `phone_chip`): «Duración: < 15 s (menos de 15 segundos)». Los popovers y la hoja conservan los textos largos.
- **Qué fila se ve depende del ancho de la BARRA, no de la ventana** (una *container query*): `.q-reels-bar` (`container-type: inline-size`, en `assets/qualify-creative.css`) muestra la fila de chips (`.q-reels-bar__wide`) desde 760 px de barra, y por debajo la barra de dos botones (`.q-reels-bar__narrow`). Es la única regla propia de la barra, sin colores. Hizo falta porque a 768 y a 1024 px la barra lateral y la columna «¿Qué creamos?» dejan la barra en unos 376 px, y con un corte por ventana «Competidores» quedaba solo (Deivid, 2026-11-26).
- **Barra ancha (760 px o más): una sola línea que ocupa todo el ancho de la barra** y nunca pasa de línea, así que ningún chip queda solo. Los cuatro filtros se reparten el ancho que sobra (`flex: 1 1 auto`, mínimo 5,5 rem): el que tiene el valor más largo recibe más, así un valor elegido no se corta si hay lugar y, como un select, llevan la palabra a la izquierda y la flecha a la derecha (`justify-content: space-between`). Después van «Competidores» y «Quitar filtros» (este, con un filtro activo) con su ancho natural. El gap es `spacing="3"` (12 px). Deivid, 2026-11-26: los cinco chips quedaban apiñados en el centro. A 760 px cada filtro todavía tiene unos 107 px para su palabra corta. Cada chip abre un `rx.popover` (vidrio `lq-glass`; Esc devuelve el foco al chip).
- **Barra angosta (menos de 760 px: teléfonos, tablets y paneles angostos): una sola línea con dos botones del mismo ancho** (`flex: 1 1 0`). «Filtros» (`sliders-horizontal`) muestra « · N» con N filtros activos y su nombre accesible lo dice («Filtros: 2 activos»). «Competidores» abre su panel. Si la marca no tiene competidores, «Filtros» ocupa toda la línea. Queda lugar para un tercer botón con ícono (RF-14). «Filtros» abre **una sola hoja desde abajo** con los cuatro grupos (Canal, Tipo de cuenta, Cuenta —varias— y Duración), cada uno con su título y con las mismas filas de opción. Cada elección aplica al momento y la hoja sigue abierta; si es larga, se desplaza por dentro. En el pie van «Quitar filtros» (solo con algún filtro activo) y «Listo». Al cerrarse, el foco vuelve a «Filtros». Ningún texto se parte y no hay desplazamiento lateral (Deivid, 2026-11-26; reemplaza a los chips en varias líneas).
- **Fila de opción:** un `rx.button` `ghost` gris de 44 px con `role="radio"` o `role="checkbox"` y `aria-checked`. Su marca siempre se dibuja con un ícono lucide y los tokens: anillo vacío (`circle`) o lleno (`circle-dot`) en las opciones de una sola elección, y casilla vacía (`square`) o marcada (`square-check`) en las de varias («Cuenta», «Tus competidores»). Elegida, la marca va en `accent-11` y el texto en `medium`; sin elegir, la marca va en `TEXT_MUTED`. Es la receta `lq-check` / `lq-radio` del kit, sin `<input>` nativo, para no anidar un control dentro de otro. No es una primitiva: la usa una sola pantalla.
- Detrás de los filtros, un panel suave del sistema: `T.CARD_BG` (gris 2, funciona en claro y en oscuro), con el radio de tarjeta y 0,5 rem de padding. Nunca el recuadro oscuro que se quitó, y sin posición fija.
- Los textos que no caben terminan en «…» con `white-space: nowrap`, `overflow: hidden` y `text-overflow: ellipsis` escritos uno por uno: el prop `truncate` de Radix llega a Reflex 0.10 como CSS inválido y dejaba el valor partido letra por letra.

Reglas del flujo (Planificador, referencia): un paso solo se abandona cuando es válido y el motivo se lee junto a «Siguiente»; el paso de confirmación es donde aterriza la respuesta del servicio (`callout("error")` encima del botón); un rechazo no deja nada a medias. Demo en vivo: `/design` → «Flujo por pasos».

### 5.9 Elegir, subir, mostrar, conversar (2026-10-09)

Cuatro recetas que los lotes de la migración Liquid Glass repetían en dos o más pantallas y que el kit también trae — las dos condiciones del plan (§0) para admitir una primitiva. El fundador las aprobó el 2026-10-09; desde entonces son la única puerta a su material (`assets/qualify.css`, «Shared primitives») y las hojas de dominio ya no llevan sus propias versiones (`q-cr-option`, `q-choice` de tarjeta, `q-pick-card`, `q-inbox-thumb`, `q-catalog-thumb`, `q-trend-thumb`, `q-brand-avatar`, `q-cr-dropzone`, `q-inbox-reply`).

| Primitiva | Cuándo | Anatomía y reglas |
|---|---|---|
| `choice_card(*children, selected=, on_select=, role="radio"\|"checkbox", disabled=False, padding=…)` | una opción que se elige entre varias (tipo de pieza, producto del catálogo, look del avatar, receta, plan del Brand Kit) | **un `<button>` real** con la tarjeta como cuerpo (§8: nunca `rx.box` + `on_click`); material card; elegida = anillo de 2 px del acento + lavado + halo (`.q-choice-card--on`, gana al hover); `disabled` = punteada y quieta, con el motivo en los hijos; el estado también va en `aria-checked`. `choice_card_check()` pone el check sólido del kit en la esquina de la elegida cuando el anillo solo sería poco (P1). `choice_card_number(label)` pone, en su lugar, el puesto de la elegida en un orden (1, 2, 3…; el carrusel de productos de los anuncios): disco sólido `--accent-12` con texto `--accent-1` y halo, legible sobre fotos claras y oscuras; `aria-hidden`, porque el `aria_label` de la tarjeta dice el puesto (m-25114606). Los chips-píldora del Planificador (`.q-choice`, `qualify-planner.css`) son otra cosa y siguen allí |
| `dropzone(*children, upload_id=, on_drop=, accept=, max_files=, multiple=, variant="zone"\|"compact"\|"tile"\|"bare", tile_size=…)` | **toda** subida de archivos | `rx.upload.root` vestido con el campo hundido y punteado del kit (`.q-dropzone`), acento al pasar un archivo o llegar con teclado. `zone` = el prompt grande del estado vacío; `compact` = pozo pequeño en un formulario; `tile` = cuadrado en una grilla de medios (`tile_size`); `bare` = sin material, los hijos son el look (un botón, una loseta entera). **El guard prohíbe `rx.upload`/`rx.upload.root` en las páginas**: el `rx.upload` estilizado pinta un borde punteado inline que ninguna clase puede sobreescribir — esa es la trampa que esconde |
| `media_thumb(src, size="72px", width=, height=, round=False, icon="image", icon_size=, alt="", fit="cover", has=…)` | la foto de un Reel, un producto, un video trending, un referente; el avatar de una cuenta | la imagen en el marco del sistema (`.q-thumb`: material control, hairline, radio control) o, si no hay, el mismo marco con `icon` — una lista nunca muestra un hueco ni el glifo de imagen rota. `round=True` es el avatar (`lq-avatar`). `size` cuadra; `width`/`height` lo sobreescriben (`height` solo + `width="100%"` = la foto arriba de una tarjeta). `has` sustituye la prueba `src != ""` cuando el VM ya lo sabe. `alt=""` por defecto (decorativa junto a su propio título) |
| `chat_bubble(*children, direction="out"\|"in", meta=None)` | un mensaje de una conversación: el borrador de respuesta del inbox hoy; los DMs de 4-B mañana | la burbuja del kit: `out` = lo que decimos (lavado del acento, cola abajo a la izquierda), `in` = lo que dijeron (material control, cola abajo a la derecha); `meta` (hora, estado) va dentro, debajo del texto |
| `sort_handle(label, on_key, *, key=, lifted=False)` (+ `DragCard`) — fundador 2026-11-06 | el asa de una fila que el dueño ordena: categorías y productos en «Ordenar tu menú» (m-24955643), las respuestas del menú de WhatsApp (m-24955644) | la fila es un `DragCard` (`class_name="q-rank-card"`, `data-rank-key`, `data-rank-group` = lo que intercambia lugares) movido por `assets/rank-drag.js`; el asa (`.q-sort-handle`, `grip-vertical` 44 × 44, `SortHandle`: un `<button>` con `on_key_down`) levanta la fila al instante con el dedo o el ratón, y desde el teclado: **Espacio** levanta y suelta, **↑/↓** mueven, **Escape** la deja donde estaba (`aria-pressed` mientras está levantada; un `aria-live` dice la posición). `label` = «Mover «Shawarmas», posición 3 de 5»; `key` (`data-sort-key`) devuelve el foco al asa tras cada movimiento. **Nunca solo el asa:** la fila lleva también el «⋯» con «Primero · Subir uno · Bajar uno · Último · Mover a la posición…» (§8) |
| `orbit_menu(label, items, *, disabled=False, icon="plus", direction="up", described_by="")` con `OrbitItem(key, icon, text, on_select, disabled=False)` — fundador 2026-11-06 (m-24955785) | el «+» del cuadro de respuesta de Chats de WhatsApp: «Enviar algo al cliente» → Tus productos · Tu menú · Formas de pago · Tus piezas · Foto del celular | el gesto Orbit del kit **redibujado** sobre nuestros tokens (`liquidos.css` no se carga): botón redondo de 44 px cuyo «+» gira 45° a «×» (`T.SPRING`, `--q-dur`; pulsado `scale(0.92)`) y una **columna** de píldoras (círculo de icono de 44 px + texto, 8 px de separación) con el material flotante, que suben 12 px una tras otra cada 30 ms. `rx.menu` (Radix DropdownMenu): `side="top"`, `align="start"`, sin dar vuelta, a 8 px del botón — nunca tapa lo de abajo; teclado y `aria-*` de Radix. `prefers-reduced-motion`: el «×» sin giro y las píldoras solo aparecen. **Reglas:** (1) en el cuadro de respuesta de Chats de WhatsApp y en «Agregar» de la línea de tiempo del editor (Deivid, 2026-11-14, ED-00b; otra pantalla, visto bueno del fundador); (2) 2 a 6 opciones; (3) icono **y** texto de 16 caracteres como máximo (la primitiva lo exige); (4) una opción abre un flujo, nunca envía ni publica; (5) fuera de sus condiciones no se dibuja (no se deshabilita); única excepción, «Foto o video» de «Agregar» con 8 fotos o videos en la línea de tiempo (ED-12, m-25029107): se ve apagada (`OrbitItem(..., disabled=...)`: píldora de fondo sólido `--gray-3`, borde `--gray-a6`, texto `--gray-11`, sin transparencia, cursor «no permitido») y el motivo, «Tu video ya tiene 8 fotos o videos. Quita una para agregar otra.», va en su propia línea encima del «+», nunca al lado (las opciones se abren encima), con un `id` que el «+» nombra en `aria-describedby` mientras lo dice (`described_by=`, opcional). `data-orbit-key` en cada opción; al cerrar el flujo, el foco vuelve al «+» (`ORBIT_FOCUS_SCRIPT`) |
| `expandable_text(text, *, expanded, on_toggle, lines=2, min_chars=60, id=None, size="1", color=T.TEXT_STRONG)` — Deivid 2026-11-10 (m-24921079) | un texto que se corta a `lines` líneas y el dueño despliega cuando quiere: la descripción de cada parte en «Orden del clip» | `Qualify/ui/expandable_text.py`; recorte CSS `.q-expandable--cut`; «Ver más»/«Ver menos» es un `<button>` de ≥ 44 px con `aria-expanded` (+ `aria-controls` con `id`), sin hover ni `title`, y su toque no inicia un arrastre; el botón solo aparece si el texto pasa de `min_chars` caracteres (Reflex no mide el recorte); el estado lo guarda quien lo usa, por una clave estable del ítem, nunca su posición |
| `clip_player(poster, *, src=, label=, pause_label=, start="", end="", broken_text="", key=None, framed=False, small=False, renew=False)` + `clip_player_script()`, `clip_player_notice()`, `clip_player_renew(evento)` (`Qualify/ui/clip_player.py`, `assets/clip-player.js`) — m-24992893 / m-24992894, 2026-11-10 | ver un pedazo de video **en el mismo cuadro** de su imagen, sin salir del paso: la escena de cada parte del reel en «Orden del clip» (paso 2) y la vista previa de las partes «Para revisar» / «Lista» en «Creando tus partes» | la imagen (componente o URL; sin URL, el glifo de película) con un ▶ redondo al centro (3rem; `small` = 2rem con blanco de 44 px). Tocar ▶ reproduce **mudo** en el mismo marco, que nunca crece ni se mueve; mientras carga, la imagen sigue y el ▶ se atenúa y late (otro toque cancela): el video solo la tapa cuando de verdad reproduce. Video e imagen llenan el marco igual (`object-fit: cover`), así el video aparece donde estaba la escena; la marca de pausa se ve el primer segundo (en el teléfono no hay puntero); abajo a la derecha, el sonido (`aria-pressed`, «Activar sonido»); tocar el video lo pausa y vuelve la imagen con ▶. Con `start`/`end` (y `#t=start,end` en `src`) reproduce solo ese tramo y se detiene al final, sin bucle: **un solo archivo**, saltos por tramo. El `<video>` no descarga nada hasta ▶ (`preload="none"`, la dirección viaja en `data-clip-src`): un sondeo del servidor que vuelve a pintar la fila no reinicia lo que se ve; `key` = el id estable de la fila. Un solo video sonando en la página (también «Tu video completo»); se detiene si su imagen se oculta (filas plegadas) o empieza un arrastre (`slide-drag.js` nunca levanta una tarjeta desde un botón); ←/→ sobre sus botones no mueven la tarjeta. Si el archivo ya no está: vuelve la imagen **sin** ▶ en todos los cuadros de ese archivo y, con `broken_text`, se escribe una vez por archivo en el `clip_player_notice()` más cercano (texto visible bajo la lista, `role="status"`); sin aviso en la pantalla, solo lo oye el lector de pantalla. Con `renew` (rutas `/r2media` de vida corta) el primer error no rompe: pulsa el `clip_player_renew(evento)` más cercano, la pantalla relee sus rutas y el clip vuelve a reproducir cuando cambia su `data-clip-src`; un segundo error sí lo rompe. Nada solo-hover: ▶ y el sonido siempre visibles cuando aplican; la marca de pausa aparece con el puntero o el foco. Monta `clip_player_script()` una vez por pantalla. `framed` = el marco `.q-thumb`. **Demo en `/design`: pendiente** (necesita un video de muestra servido por la app) |
| `edit_preview(*, src, video_key, poster, start, end, speed, rate, rotate, text, place, text_long, text_layout, effect_srcs, focus, play_nonce, known, remote, pending, on_duration, on_resolve, undo, undo_on, …)` + `edit_preview_script()` (`Qualify/ui/edit_preview.py`, `assets/edit-preview.js`) — ED-01 m-25026605, 2026-11-14. **Patrón nuevo, pendiente de firma (ED-00)**; la línea de tiempo que va debajo y comparte su reloj: §5.10 (ED-00b), y la secuencia de varios tramos y fotos: ED-01b | la vista previa en vivo y gratis del editor «Arma tu video» (paso 1 del Clip): cómo va quedando el video antes de crear | un cuadro 9:16 con el `<video>` del dueño que repite **solo su tramo** (vuelve al inicio, en bucle), girado con `rotate()` (a 90/270 el video se acomoda con los lados cambiados para seguir llenando el 9:16), recortado con `object-fit: cover` centrado y a `playbackRate` = velocidad (tope ×16; más arriba la pantalla dice que se ve más lento). Encima, el texto del dueño con el diseño `scrim` del catálogo de #674 (`layer_spec/catalog_v1.json`: blanco, sin contorno ni sombra de letra, sobre degradado negro, dentro de la zona segura 9:16 y 270–1536) y los efectos como `<video>` mudos en bucle con `mix-blend-mode: screen` (solo si su archivo existe). Un solo sonido; ▶/❚❚ y el sonido (`aria-pressed`) del kit del `clip_player`. Debajo, en la zona fija, «{t} de {total} · Así va quedando» (el tiempo lo escribe el script) o, mientras hay un cambio, la línea con «Deshacer» (sin temporizador, WCAG 2.2.1); un video de R2 se reproduce por `/r2media/{token}`, que la pantalla emite cuando el script pulsa un botón oculto (`pending` → `on_resolve`); si no se puede, lo dice con su texto, y «No pudimos mostrar…» queda solo para un error real (`role="status"`). El script informa largo y tamaño en cada `loadedmetadata` por un botón oculto, y un error (o 15 s sin largo) como largo negativo: es lo único que el servidor sabe del navegador. Nada se decodifica en Reflex ni en el servidor. Dónde va en la pantalla lo decide quien lo monta («Arma tu video», ED-02, detrás de `QUALIFY_CLIP_EDITOR`). **Demo en `/design`: pendiente** |

Demo en vivo: `/design` → «Elegir, subir, mostrar, conversar».

### 5.10 Línea de tiempo (ED-00b, patrón firmado con el ADR 50)

> **Estado:** **firmado.** Deivid firmó el ADR 50 el 2026-11-20
> (`docs/adr-50-video-efectos-por-pasos.md` §1.7, §2.2 D-E3 y D-E6, §2.3 D-T1…D-T6 y D9), y con
> él este patrón tal como quedó en `main`. Lo propuso ux-designer el 2026-11-14 a pedido de
> Deivid (m-25029104; «Escritorio y celular adaptado (Recomendado)») y se construyó en ED-10
> (#739), ED-03 (#743), ED-04 (#759) y el cuadro por bloque de m-25026650 (#761). Reemplaza la
> D-E3 firmada el 2026-11-13 («solo en escritorio y solo para mirar»). Código:
> `Qualify/ui/timeline.py` y `Qualify/ui/timeline_vm.py` (el componente), y
> `Qualify/clip_editor_view.py` y `Qualify/clip_editor_vm.py` (la pantalla que lo monta).

**Para qué.** Que el dueño arme su video **tocando el video mismo**: ve las partes en orden, toca
una y la cambia ahí, sin elegir herramientas. Es el corazón de **«Arma tu video»**, el paso 1 del
Clip, dentro del marco de §4.5. La pantalla está detrás de `QUALIFY_CLIP_EDITOR`, que está
apagado en producción (ADR 50 §6.1 #13).

**Anatomía** (de arriba abajo, ADR 50 §1.7):

```
 ┌───────── vista previa en secuencia (edit_preview, §5.9) ─────────┐
 0:03   0:04   0:05 │ 0:06   0:07      ← regla de segundos
 ▣▣ Video 1 ▣▣▣◀▌╔══│══ Video 2 ══╗▐▶  ← «Fotos y videos» (56 px); elegido: borde + 2 tiradores
 Aa «2×1 hoy» ══════│═════╗            ← «Textos» (44 px)
 ░░░░ Vapor ░░░░░░░░│░░░░░░░░░░░░     ← «Efectos 1» (44 px por fila; suma filas sola)
       ░░ Humo ░░░░░│░░░               ← «Efectos 2» (solo mientras dos efectos se encimarían)
                    ▲ cabezal
 [+ Agregar]  o, con un bloque elegido, [Quitar]   ← barra de acciones
 Video 2 · Cortar · Velocidad · Girar    [Listo]   ← panel del bloque elegido
```

1. **Vista previa en secuencia** arriba (`edit_sequence_preview`, ED-01b): el video entero en
   orden, gratis y en el navegador, con **un solo reloj** compartido con la línea
   (`[data-edit-sync]`). Debajo del cuadro no va la hora: la única es la de la regla.
2. **Regla de segundos**, con la hora en texto.
3. **Tres pistas**, siempre visibles y en este orden: «Fotos y videos», «Textos», «Efectos». Una
   pista vacía no desaparece: queda como una fila en blanco de la misma altura, sin texto de
   ayuda, y su nombre accesible dice que está vacía («Pista de textos vacía»,
   `EMPTY_TRACK_NAMES`).
4. **Filas de «Efectos»** (Deivid, 2026-11-20, #759): la pista suma una fila sola cuando dos
   efectos se encimarían y la quita cuando ya no hace falta. Con una sola fila se llama
   «Efectos»; con dos o más, «Efectos 1», «Efectos 2»… (`lane_name`). Un efecto pasa de una
   fila a otra arrastrándolo hacia arriba o hacia abajo. **No hay «+ Pista»**: el dueño nunca
   crea pistas a mano.
5. **Bloques:** cada foto, video, texto o efecto es un bloque con ícono **y** nombre (nunca solo
   color, P1). Cada bloque de foto o video lleva su propio cuadro (m-25026650, #761). La pista de
   video **nunca tiene huecos**: recortar, quitar o mover corre los bloques de después; textos y
   efectos se quedan en su hora.
6. **Cabezal:** una línea vertical de acento que marca el momento que muestra la vista previa.
   Es un `<input type="range">` nativo («Momento del video»).
7. **Tiradores:** solo en el bloque elegido, uno al inicio y otro al final, **por fuera** del
   bloque para que el dedo no tape lo que recorta. En un texto o un efecto lo recortan en el
   tiempo; en el video propio lo recortan o lo alargan **dentro de su archivo** (ED-03, #743).
8. **Barra de acciones**, en la cápsula flotante `.q-island`, debajo de las pistas. Sin nada
   elegido: un solo **«Agregar»**, el `orbit_menu` de §5.9: el «+» gira a «×» y abre, hacia la
   derecha (Deivid, 2026-11-16), «Foto o video · Texto · Efecto · Pedir una idea». Cada opción
   abre **un solo panel lateral con pestañas** («Agregar a tu video»: «¿Con qué lo armamos? ·
   Texto · Efecto · Pedir una idea», Deivid 2026-11-17); nunca agrega sola. Con un bloque
   elegido, la barra de «Arma tu video» muestra hoy solo **«Quitar»**: lo demás vive en el panel,
   un solo lugar por acción (`EDITOR_ACTIONS`).
9. **Panel del bloque elegido**, debajo de la barra; habla de **un solo bloque a la vez** y
   siempre termina en «Listo», que quita la selección:
   - **video propio:** «Cortar» (corta donde está el cabezal; Deivid 2026-11-17: sin
     «Desde/Hasta»), «Velocidad» y «Girar»;
   - **texto y efecto:** «Empieza / Termina» con «− ½ s / + ½ s», y el lugar del texto
     «Arriba · En el medio · Abajo»;
   - **foto:** dura 2 s; cambiar su duración (1–5 s, D-T1) llega con ED-14.

**Tamaños y reglas fijas.**

- **1 s = 44 px en el celular** (`PX_PER_SECOND`), así el bloque más corto (1 s) ya mide 44 px
  de toque.
- **Toques de 44 px como mínimo:** botones de la barra de 44 px de alto; tiradores por fuera del
  bloque (44 × 56 px en la pista de video, 44 × 44 px en las otras).
- **Imán de ½ s siempre** (`STEP_S`), al arrastrar y con «− ½ s / + ½ s». Mientras se arrastra, un
  globo dice la hora.
- **Sin zoom** (D-T5): ni botones ni pellizco.
- **«Velocidad»** es una acción del bloque de video, no un efecto (D-T3): Normal · ×2 · ×3 · ×5 ·
  ×10 · ×20, cada una disponible solo si el resultado dura 3–60 s (Deivid, 2026-11-17); la que no
  cabe queda no disponible con su motivo.
- **Límites dichos antes del choque:** 8 fotos o videos (`SEGMENTS_MAX`), 1 s por tramo como
  mínimo, 8 efectos (`EFFECTS_MAX`) y un video final de 3 a 60 s. Al llegar al límite, el botón
  queda no disponible (`q-button-off`, §5.5) con su motivo.
- **Textos:** el contrato admite hasta 3 (D-T2, `TEXT_LAYERS_MAX`); la pantalla de hoy maneja
  **uno** (`texto-1`) y los otros dos llegan con ED-13.
- **Efectos:** solo las capas que la biblioteca ofrece (`effects_data/v3.json`: humo, brasas y
  vapor), primero las del rubro del negocio; el mismo efecto puede repetirse sin pisarse a sí
  mismo (D-T2).

**En el celular** (cuando el componente mide menos de 52rem, medido en su propio contenedor
`q-tl`, nunca en la ventana):

- El cabezal queda **fijo al centro** y las pistas se deslizan debajo, **dentro de su caja**:
  la página nunca se desplaza de lado. Deslizar las pistas mueve el cabezal y la vista previa.
- Nombres de pista en `aria-label`, no visibles.
- **Mover:** se mantiene apretado el bloque un momento (300 ms, `LONG_PRESS_MS`), se levanta y se
  arrastra; los demás hacen lugar. Al levantarlo, la línea viva dice «Suelta donde quieras
  ponerlo.». No hay botones para mover (D-T6).
- La dirección guarda el bloque elegido (`?bloque=video-2`).

**En escritorio** (componente de 52rem o más):

- Las pistas ocupan todo el ancho y **se ajustan al largo del video** (uno de 12 s cabe entero);
  los nombres de pista se ven a la izquierda. La vista previa va centrada sobre la línea.
- Un clic en la regla mueve el cabezal.
- Tiradores, imán, arrastre con el ratón y panel funcionan igual que en el celular. Lo nuevo se
  agrega por «Agregar» y su panel lateral (no hay un panel aparte de medios para arrastrar a la
  pista).

**Accesibilidad** (§8):

- La línea es un grupo con `aria-label` «Línea de tiempo de tu video» y tres listas: «Fotos y
  videos», «Textos» y «Efectos». Cada bloque es un `<button>` alcanzable con Tab, con nombre
  completo y `aria-pressed` cuando está elegido.
- **Enter** elige el bloque y lleva el foco a su panel; **Escape** dentro del panel lo cierra y
  suelta el bloque.
- **←/→ sobre un bloque de video o foto lo cambian de lugar** («Usa las flechas para cambiarlo de
  lugar.»); sobre un texto o un efecto lo corren ½ s («Usa las flechas para cambiar cuándo
  sale.»). **↑/↓ sobre un efecto** lo pasan a otra fila. Cada ayuda vive una vez, en un `span`
  oculto, y el bloque la señala con `aria-describedby`.
- **El cabezal es un control deslizante** («Momento del video», `aria-valuetext` «0:05 de 0:12»).
  **Los tiradores también son `role="slider"`** con su `aria-valuetext`, con el mismo paso de ½ s.
- El panel repite con botones lo que hacen los tiradores de un texto o un efecto: «− ½ s /
  + ½ s». Mover no tiene botón (D-T6).
- **Se guarda al momento y no hay «Deshacer»** (D-E6; Deivid quitó «Deshacer» el 2026-11-19,
  #743). Cada cambio se anuncia **una vez** en la línea viva `role="status"` de la línea de
  tiempo («Moviste el video 2.», «Pusiste el video 2 ×10.»…). No hay botón «Guardar».
- `prefers-reduced-motion`: la lente del bloque elegido salta sin deslizarse, la pantalla lleva
  al panel sin desplazamiento suave y los bucles de efectos de la vista previa se detienen.

**Lo que NO hace** (ADR 50 §1.7). Tiene el estilo de un editor con línea de tiempo, pero **no es
un editor de video:** sin zoom, sin fotogramas clave, sin recorte cuadro a cuadro, sin capas
libres, sin pistas de audio aparte, sin huecos ni bloques encimados en la pista de video, y sin
pistas que el dueño cree a mano (no hay «+ Pista»). **Transiciones:** el Clip no tiene; entre
partes llegan con el editor de Video por partes (ED-07). Deivid decidió (D9) ofrecer solo
«corte» hasta EF-16; el cambio va en un PR aparte (ADR 50 §6.1 #2a). No genera nada:
todo lo que está en la pista se ve gratis en la vista previa antes de crear; lo que cuesta pasa
al tocar «Crear». En la pantalla nunca se escriben «timeline», «track», «clip», «capa», «frame»,
«render», «split» ni «trim»; «Cortar» es la palabra del dueño.

**Reglas del editor** (m-25026602). Son las reglas E1–E6 que ux-designer propuso el 2026-11-13
en el ticket ED-00 (m-25026602), a pedido de Deivid. No son las decisiones D-E1…D-E6 del ADR 50
§2.2, aunque nacieron el mismo día. La línea de tiempo editable que Deivid firmó el 2026-11-14
(D-T1…D-T6, «Escritorio y celular adaptado») cambió algunas. Deivid firmó esta versión el
2026-11-26. Así quedan:

| Regla | Qué dice hoy | Firmada |
|---|---|---|
| E1 | El editor es **un paso, no el flujo**: vive dentro del marco de pasos de §4.5 («‹ destino · Paso N de M», pie «Atrás · Siguiente»). | Propuesta el 2026-11-13; sigue el 2026-11-14 |
| E2 | **Un bloque elegido a la vez:** el panel trabaja siempre sobre una sola cosa. Antes era «una herramienta abierta a la vez». Absorbe la antigua E4: las fichas «Todo · 1 · 2…» ya no hacen falta. | Forma nueva, 2026-11-14 |
| E3 | **Todo viene armado:** lo que eligió el dueño llega en su orden y «Siguiente» funciona sin tocar nada. Lo único obligatorio es tener algo que mostrar. | Propuesta el 2026-11-13; sigue el 2026-11-14 |
| ~~E4~~ | *Absorbida por E2:* «se elige qué editar antes de editarlo» («Todo el video» o «Parte 2»). | 2026-11-14 |
| E5 | **Lo que se ve es lo que sale.** Cuando no es así, la pantalla lo dice. | Propuesta el 2026-11-13; sigue el 2026-11-14 |
| ~~E6~~ | *Retirada:* «nada de precisión de mouse: sin arrastrar bordes en la línea, sin zoom». Ahora los bordes se arrastran con tiradores de 44 px (D-T1…D-T6). El zoom sigue fuera (ver «Lo que NO hace»). | Retirada el 2026-11-14 |

**Decisiones de Deivid (2026-11-14), textuales, y cómo quedaron.**

| Decisión | Respuesta de Deivid | Qué fija hoy |
|---|---|---|
| D-T1 · ¿Qué es una foto en la línea? | «Foto quieta de N s (Recomendado)» | Una foto es un bloque quieto de 1 a 5 s, gratis y visible en la vista previa. Hoy entra con 2 s; cambiar su duración llega con ED-14. «Darle movimiento con IA» queda fuera (ED-14). |
| D-T2 · ¿Varios textos y el mismo efecto dos veces? | «Sí, hasta 3 textos (Recomendado)». El mismo efecto se puede repetir, cada uno con su inicio y su fin. | El contrato v2 (ED-15) admite hasta 3 textos y efectos repetidos sin pisarse a sí mismos. La pantalla maneja hoy un texto; los otros dos llegan con ED-13. |
| D-T3 · ¿Dónde va «Cámara rápida»? | «Velocidad del bloque (Recomendado)» | «Velocidad» es una acción del bloque de video, no un efecto: Normal · ×2 · ×3 · ×5 · ×10 · ×20, cada una solo si el resultado dura 3–60 s (Deivid, 2026-11-17). |
| D-T4 · Miniaturas en la pista de video | «Un cuadro ya, tira después (Recomendado)» | Un cuadro por bloque ya (#761); la tira de cuadros del servidor después (ED-11, m-25026650). |
| D-T5 · ¿Zoom? | «Sin zoom (Recomendado)» | 1 s = 44 px en el celular; ajustada al ancho en escritorio. |
| D-T6 · ¿Cómo se ordena en el celular? | «Solo arrastrar» | En el celular solo se mantiene y arrastra, sin botones; en escritorio, además, ←/→ con el teclado, sin botones visibles. ux-designer recomendaba sumar «‹ Antes / Después ›». |

**Riesgo aceptado (D-T6):** en el celular, quien no puede arrastrar no puede reordenar (WCAG 2.5.7).

**Tokens y primitivas que usa** (ningún color nuevo):

| Parte | Con qué se dibuja |
|---|---|
| Bloque | borde y fondo por tipo: video con el lavado del acento (`--accent-a4`), foto y texto en gris, efecto con borde punteado del acento; `--q-radius-control`; cuadro con `media_thumb` (§5.9) |
| Bloque elegido | borde de 2 px `accent-9`; foco `accent-8`; `aria-pressed` |
| Pista vacía | fila en blanco de la misma altura; mientras se arrastra un efecto hacia una fila nueva, su lugar se marca con borde punteado del acento |
| Regla y horas | la hora en texto; los valores del panel con `.q-nums` |
| Cabezal y tiradores | `accent-9` (sólido del acento, §3.1) |
| Globo con la hora | el globo de arrastre de `.q-tl` (la hora mientras se arrastra) |
| Barra de acciones | `rx.button` `surface` con ícono, en `.q-island`; «Agregar» = `orbit_menu`; no disponible = `q-button-off` |
| Panel del bloque | `.q-tl-panel`; «Velocidad» y lugar del texto con el menú segmentado del kit (`.q-source-seg`); «Listo» = `rx.button` |
| Panel lateral de «Agregar» | `drawer` (§5.8) con pestañas |
| Línea viva | `role="status"` bajo la línea de tiempo |
| Movimiento | la lente `.q-glass-blob` bajo el bloque elegido; sin transiciones con `prefers-reduced-motion` |
| Arrastre | `assets/timeline-drag-core.js` (la cuenta, probada con node) y `assets/timeline-drag.js` (el DOM) |

Demo en `/design`: sección "Línea de tiempo".

### 5.10.1 Parte con IA en la línea de tiempo (m-25026602, patrón firmado)

> **Estado:** **firmado.** Deivid firmó los mockups el 2026-11-26 y respondió las 9 preguntas
> el mismo día (abajo). Lo propuso ux-designer el 2026-11-26 a partir del plan
> `docs/plan-editor-unico-clip-partes.md` y del ADR 50 §13 (el editor único). Mockups:
> `docs/mockups/editor-unico/` (copia fiel de los firmados; se abren con doble clic) —
> `index.html`, `01-pista.html` (la pista y el muestrario de
> estados), `02-panel-bloque-ia.html` (el panel), `03-agregar.html` («Agregar» y los topes),
> `04-crear.html` («Revisa y crea» y «Probar esta parte»), `05-resultado.html` (progreso,
> aprobar y finales) y `06-hacer-uno-parecido.html`; notas y decisiones D1–D22 en `notas.md`.
> Código del patrón: los tokens `--q-ai-*` en `assets/qualify.css`, las clases en
> `assets/qualify-creative.css` («The AI part on the timeline»), `T.AI_SCALE` / `T.AI_ICON`
> en `Qualify/ui/tokens.py` y `ui.ai_mode_tag` en `Qualify/ui/primitives.py`. La pantalla
> que lo monta llega con ED-07 (m-25026638, PR 6 del ADR 50 §13.7), detrás de
> `QUALIFY_CLIP_AI_PARTS`.

**Para qué.** En el editor único (ADR 50 §13), una parte que hace la IA es **un bloque más de
«Fotos y videos»**, junto a las fotos y los videos del dueño. El dueño tiene que ver de un
vistazo **qué hace la IA, qué falta crear y qué ya se pagó**, sin un cartel encima de cada
parte. No es un componente nuevo: es una variante de `.q-tl__block` (§5.10).

**Rol de color «hecho con IA».** Ningún color nuevo en el sentido de §9.2: se usa la escala
**iris** de Radix, que el sistema ya carga para el lavado de la zona «Publica» del sidebar
(§3.1, `iris-a3`). Lo nuevo es el **rol** (Deivid, respuesta 4), como una zona y no como un
estado: el estado de la parte conserva su tono de siempre.

| Token | Paso iris | Para qué |
|---|---|---|
| `--q-ai-fill` | `iris-a4` | fondo del bloque y velo sobre su póster |
| `--q-ai-edge` | `iris-a7` | borde del bloque creado |
| `--q-ai-edge-plan` | `iris-a8` | borde punteado del bloque sin crear |
| `--q-ai-ring` | `iris-a9` | anillo de la insignia del modo y de la marca de la vista previa |
| `--q-ai-ink` | `iris-12` | color de texto del bloque mismo (≥ 4.5:1 sobre `iris-a4`): lo heredan los íconos que no van en una cápsula, como el «Aa» o el ícono de respaldo cuando no hay póster |
| `--q-ai-icon` | `iris-11` | el ícono «i» del motivo del modo, en el panel. Lo usa ED-07: hoy ninguna clase lo lee |

En Python: `T.AI_SCALE = "iris"` (para `color_scheme` de una insignia) y `T.AI_ICON =
"sparkles"` (el ✦). **Nunca solo el color** (P1): el bloque IA siempre lleva el ✦, la palabra de
su modo y, después de crear, la palabra de su estado. No hay un color por modo: el ícono y la
palabra bastan.

**Anatomía** (56 px de alto, la altura de la pista de medios; `01-pista.html`):

```
┌──────────────────────────────┐   borde: punteado 2 px (sin crear) · lleno 1 px (creada)
│ (✦ ↳ Sigue a la anterior)    │   línea 1: ✦ + insignia corta del modo (.q-tl__mode, una categoría)
│ [Parte con IA 2 · 3 s]       │   línea 2: nombre y segundos (sin crear) · o su estado (creada)
└──────────────────────────────┘   fondo: póster (corte del reel o foto del producto) atenuado · o su propio cuadro
```

- **Nombre:** «Parte con IA n», con su propia cuenta, como «Foto n» y «Video n» (D1). La
  palabra «bloque» no aparece en ningún texto de pantalla.
- **Póster** (`.q-tl__pic`, sin cambio): antes de crear, el corte del reel o la foto del
  producto, atenuado (`opacity .45`, `saturate(.4)`); después, el cuadro de su propio video (la
  tira de cuadros de ED-11b cuando exista). Encima va un velo iris para que se lean las letras.
- **Insignia corta del modo** (`.q-tl__mode`, respuesta 8): ✦ + ícono del modo + palabra
  (`.q-tl__mode-word`). Es una **categoría** (como `tag`, §5.3), no un estado.

  | Modo | Ícono (lucide) | En la pista | Nombre completo, en el panel |
  |---|---|---|---|
  | `reference` | `wand-sparkles` | «Nueva» | «Nueva, inspirada en el original» · «Nueva, con tu producto» · «Nueva, con tu marca» |
  | `edit` | `copy` | «Igual al original» | «Igual al original, con tu producto» |
  | `extend` | `corner-down-right` | «Sigue a la anterior» | «Sigue a la anterior» |

  La insignia de `extend` usa `FORM_EXTEND` («Sigue a la anterior») y **no** `FORM_EXTEND_OF`
  («↳ Sigue a la anterior»): la flecha ya la dibuja el ícono `corner-down-right` y no se repite.
- **Estado** (`.q-tl__state`, después de crear): una marca en su tono + la palabra
  (`.q-tl__state-word`), como `signal_pill` (§5.2). La marca es el punto, salvo donde la columna
  «Marca» de la tabla dice otra cosa: los errores y avisos llevan un ícono con forma para que una
  parte de 1–2 s, que esconde la palabra, no lo diga solo con el color. Las palabras y los tonos
  son los de `part_progress_vm.STATE_WORDS` y `STATE_TONES`, sin reescribirlos.
- **Letras sobre la imagen:** las tres cápsulas (modo, nombre, estado) son negras
  (`black-a10`) con letra blanca (`white-a12`), como el nombre de un bloque con cuadro (ED-11),
  para que se lean en el tema oscuro y en el claro. El iris queda en el fondo, el borde y el
  anillo de la insignia (`--q-ai-ring`). El velo sobre el póster va de `black-a6` a
  transparente encima del iris, para que el iris se siga viendo también en el tema claro.
  *Ajuste al pasar los mockups al repo:* los mockups (solo tema oscuro) usaban letra `iris-12`
  y la palabra del estado en su tono-11; en el tema claro esas letras quedaban oscuras sobre
  negro.
- **Marcado:** `<button class="q-tl__block" data-tl-block="ai" data-ai-state="…">`, con
  `aria-pressed` cuando está elegido y su nombre completo en `aria-label`.

**Estados** (`data-ai-state`: los de `PartState` más `plan`):

| `data-ai-state` | Palabra | Marca | Tono | Borde | Fondo | Tiradores |
|---|---|---|---|---|---|---|
| `plan` (sin crear) | (nombre y segundos: «Parte con IA n · 5 s») | — | — | punteado 2 px `--q-ai-edge-plan` | póster atenuado | segundos, de 1 en 1 s (1–10) |
| `queued` | «En fila» | reloj (`clock`) | `neutral` | 1 px `--q-ai-edge` | póster atenuado | no (se está haciendo) |
| `creating` | «Creando» | cargador del sistema, chico | `info` | 1 px `--q-ai-edge` | póster atenuado | no |
| `review` | «Para revisar» | punto | `warn` | 1 px `--q-ai-edge` | su cuadro | recorte dentro del video hecho, ½ s, gratis |
| `ready` | «Lista» | ✓ (`check`) | `ok` | 1 px `--q-ai-edge` | su cuadro | recorte dentro del video hecho, ½ s, gratis |
| `failed` | «No salió» | cruz (`circle-x`) | `error` | 2 px `tomato-9` | póster | no |
| `refused` | «No se pudo con el original» | aviso (`triangle-alert`) | `warn` | 2 px `amber-9` | póster | no |
| `redo` | «Hay que rehacerla» | aviso (`triangle-alert`) | `warn` | 2 px `amber-9` | su cuadro | no |
| `expired` | «Venció» | aviso (`triangle-alert`) | `warn` | 2 px `amber-9` | póster | no |

La parte **elegida** lleva, como cualquier bloque, borde de 2 px `accent-9`; si está sin crear,
el borde sigue punteado (elegida y todavía libre de cambiar). **También si está en error o en
aviso:** el borde pasa a `accent-9` y se pierde el rojo o el ámbar mientras esté elegida, pero
la palabra y la marca del estado siguen ahí y el panel dice el motivo. Al **levantarla** para
arrastrarla (`.q-tl__item--lifted`) toma el mismo borde de acento y conserva el punteado. Lo que necesita una decisión («No
salió», «No se pudo con el original», «Hay que rehacerla», «Venció») baja a una tarjeta a lo
ancho debajo de la pista, con el motivo y los botones («Intentar de nuevo», «Hacerla nueva»,
«Quitar parte»): en una parte de 4 s no caben un motivo ni dos botones de 44 px (D15).

**Anchos angostos.** `@container q-tl-block` mide la **caja de contenido** del bloque, no el
bloque: el ancho menos el relleno y el borde. Por eso el bloque IA lleva un relleno de 4 px (los
otros bloques, 8 px). 1 s = 44 px en el celular:

- **5 s (220 px):** todo: ✦, ícono, palabra del modo, nombre y segundos o estado.
- **Contenido de hasta 7.5rem (120 px):** se ocultan la palabra del modo y los segundos. Quedan
  los íconos y sigue visible el nombre o el estado, con «…» si no cabe. Esto alcanza a las
  partes de 2 s (88 px, ~78 px de contenido) y también a una de 3 s sin crear (132 px; con su
  borde punteado de 2 px le quedan 120 px). Una de 3 s ya creada muestra la palabra del modo,
  cortada con «…», **solo mientras su borde es de 1 px** (`queued`, `creating`, `review`,
  `ready`). En `failed`, `refused`, `redo` y `expired`, y al elegirla o levantarla, el borde es
  de 2 px y la palabra se oculta.
- **Contenido de hasta 3.25rem (~52 px; un bloque de unos 64 px o menos, como una parte de
  1 s):** se ocultan también la palabra del estado y el nombre, y la cápsula pierde su relleno
  para que quepan el ✦ y el ícono del modo. Queda la marca del estado: el punto o, en un error o
  un aviso, su ícono con forma. *Cambio sobre la nota firmada (D4, «con 70 px o menos se oculta
  la palabra del estado»):* a 1 s también se esconde el nombre, porque «Parte con IA 1» no cabe
  ni cortado.
- **Contenido de hasta 1.5rem:** solo el ✦.
- **Con cuadro (`data-tl-pic="1"`):** la pista pone ese atributo en todo bloque con imagen, y la
  regla de ED-11 que esconde el nombre bajo 4.5rem **no** aplica dentro de la cápsula de la parte
  con IA: su nombre solo se esconde en el corte de 3.25rem, nunca deja una cápsula vacía.
- **Con transición de entrada (`data-tl-in="1"`):** como cualquier bloque, su contenido empieza
  después de la franja de la unión, con los 4 px del bloque IA.
- El nombre completo siempre está en `aria-label` y en el panel: «Parte con IA 1, Nueva, de
  0:06 a 0:11, sin crear».

**Reglas.**

1. **Una parte con IA va siempre a ×1:** en su panel no hay «Velocidad», «Girar» ni «Cortar»
   (ADR 50 §13.2). La velocidad solo aplica a los bloques propios.
2. Las uniones, los textos y los efectos funcionan igual a su lado y encima (ADR 50 §13.10,
   respuesta 2).
3. Nunca se dibuja solo el color: siempre ✦ + insignia + palabra.
4. En el celular la insignia se acorta a íconos; el nombre completo siempre está en
   `aria-label` y en el panel.
5. La insignia del modo es una categoría; el estado es una señal (§5.3, «¿qué badge?»).
6. **Excepción al imán de ½ s** (respuesta 5): antes de crear, los segundos de una parte con IA
   son **enteros, de 1 a 10** («− 1 s / + 1 s» y tiradores con imán de 1 s), porque
   `VideoPartPlan.seconds` es entero. Después de crear, los tiradores recortan dentro del video
   hecho con el imán de ½ s de siempre, gratis.
7. No hay botones sobre la parte en la pista: las acciones van en el panel o en la tarjeta de
   decisiones.
8. **«Sigue a la anterior» solo continúa una parte con IA que esté justo antes** (versión 1),
   nunca un video propio ni una foto. Si el bloque de antes no es una parte con IA, la opción
   queda no disponible en «¿Cómo la hacemos?», con su razón (D8).

**Insignia completa en el panel** (respuesta 8, `02-panel-bloque-ia.html`): en el panel de la
parte, el modo se muestra con su nombre completo en `ui.ai_mode_tag(label, icon)` (`rx.badge`
`surface` en `T.AI_SCALE`, con ✦ + ícono del modo). Debajo de «¿Cómo la hacemos?» va el motivo
(`MODE_REASON_TEXTS`) con el ícono «i» en `--q-ai-icon`; si el dueño cambió el modo, la misma
línea dice «Lo cambiaste tú.» (ícono lápiz) con «Volver a lo que te propusimos» al lado (D7).
Las opciones de «¿Cómo la hacemos?» son `choice_card` con `role="radio"`; la que no se puede
elegir queda enfocable (`aria-disabled`) con su razón en ámbar, como `q-button-off` (D8).

**Marca en la vista previa** (`.q-ai-mark`): mientras el cabezal está sobre una parte con IA sin
crear, la vista previa muestra su póster con «✦ Parte con IA 1 · se crea al tocar «Crear»».

**«Revisa y crea» con dos gastos** (D12, `04-crear.html`). El paso 3 separa **cuándo** se gasta
cada cosa, porque la confusión más probable es entre vistas previas y segundos (las cifras son
las del ejemplo del mockup: 2 partes con IA, una de 3 s):

- **«Ahora, al crear»:** «2 vistas previas, una por cada parte con IA. Te quedan 12. Tus fotos
  y tu video no gastan nada.»
- **«Después, al aprobar»:** «9 s de video, solo los de las partes con IA (la de 3 s cuenta como
  4). Este mes te quedan 40 s.»
- Debajo: «Si una parte no sale, no se descuenta su vista previa.»
- La línea corta se repite junto a «Crear» (§4.5): «Usa 2 vistas previas. Te quedan 12.»
- **Sin vistas previas** (D13): «Crear» queda apagado con su motivo, y se dice la salida gratis:
  «Si lo quieres hoy, quita las 2 partes con IA: con tus fotos y tu video se crea gratis.»
- **«Probar esta parte»** (respuesta 7) va en el panel de la parte, sin diálogo, con su línea
  de costo pegada: «Usa 1 vista previa. Te quedan {n}. Las demás las creas con «Crear».».
- **Aprobar** es un diálogo (`rx.alert_dialog`, §5.4): «¿Aprobamos tu video?», con «Aprobar y
  usar {n} s» / «Todavía no»; solo cuentan los segundos de las partes con IA (D18).

**Textos firmados nuevos** (todo lo demás sale de `part_editor_vm`, `reel_parts_vm`,
`mode_choice.MODE_REASON_TEXTS`, `parts.NOTICE_TEXTS`, `part_progress_vm`, `part_review_vm`,
`parts_start_vm`, `clip_editor_vm` y `clip_joins_vm`; en las palabras que se reusan, «la parte
n» pasa a «la parte con IA n», D16):

- «Parte con IA n»
- «Nueva» · «Igual al original» · «Sigue a la anterior» (insignia corta)
- «Sin crear · gratis hasta «Crear»»
- «Cuánto dura en tu video»
- «Se crea de 4 s y usa 4 s de tu mes. Cuando esté lista, eliges qué {n} s usar arrastrando sus
  barras.»
- «Lo cambiaste tú.» / «Volver a lo que te propusimos»
- «Probar esta parte»
- «Esto guía el texto y el tono de todo el video. Lo que escribas abajo dice qué se ve en esta
  parte.» (la caja «Todo el video»)
- «Tu video ya tiene 6 partes con IA, el máximo. Quita una para agregar otra.» (con escenas: «Las
  escenas con personaje también cuentan.»)
- «Tu video ya dura 60 s, el máximo. Acorta o quita una parte para agregar otra.» · «Solo
  quedaban 3 s: la parte nueva dura 3 s.» · «Tu video pasaría de 60 s.»
- «La siguiente es una foto tuya: solo se juntan dos partes con IA seguidas.»
- «Ahora, al crear» / «Después, al aprobar»
- «✦ Parte con IA 1 · se crea al tocar «Crear»»
- «¿Aprobamos tu video?» / «Aprobar y usar {n} s» / «Todavía no»
- «Pidiendo tus partes en alta calidad: van {k} de {n}» / «Preparando tu video final»
- «Mientras se prepara, tu video no se puede cambiar.»
- «Te armamos tu video como el reel…» (`06-hacer-uno-parecido.html`)

**Las 9 decisiones de Deivid (2026-11-26), y cómo quedaron.**

| # | Pregunta | Respuesta de Deivid | Qué fija |
|---|---|---|---|
| 1 | «Agregar → Parte con IA»: ¿la pone ya o abre el panel lateral? | La pone ya en la pista y abre su panel. | Entra en el cabezal con 5 s (o lo que quepa hasta 60 s), la foto del producto y el modo de la regla; el foco va a «¿Qué pasa en esta parte?» (D10). Excepción firmada a «nunca agrega sola» (§5.10, punto 8). |
| 2 | «Pedir una idea» con la pista ya armada | Agrega al final sin borrar nada. | Las partes propuestas van al final hasta los topes; la línea viva dice cuántas cupieron. |
| 3 | ¿Dónde vive el resultado? | En «Por aprobar», con el mismo editor. | La página del video (`/drafts/<id>`), cabeza «‹ Por aprobar», h1 «Tu video», sin «Paso N de M» (D14). |
| 4 | Color del bloque IA | La escala iris del sistema, con el rol nuevo «hecho con IA». | Tokens `--q-ai-*` y `T.AI_SCALE` (arriba). |
| 5 | Segundos antes de crear | Enteros, de 1 a 10. | Regla 6: única excepción al imán de ½ s. |
| 6 | ¿Se puede cambiar el video mientras se hacen los finales? | No: el video queda quieto. | «Mientras se prepara, tu video no se puede cambiar.», con `progress_panel` (§5.4) y la lista de partes (D19). |
| 7 | ¿«Probar esta parte» o «Probar este bloque»? | «Probar esta parte». | El botón del panel, con su línea de costo y sin diálogo (D11). |
| 8 | Insignia del modo | Corta en la pista, completa en el panel. | `.q-tl__mode` en la pista y `ui.ai_mode_tag` en el panel. |
| 9 | «Video o audio tuyo» de la hoja de la parte | En «Más opciones» del panel. | **Confirmado con el servidor (2026-11-26):** va en «Más opciones» del panel y **solo aparece en «Nueva»** (`reference`). El contrato lo acepta solo en ese modo, con un video mp4/mov o un audio mp3/wav del negocio. En «Igual al original» y «Sigue a la anterior» no se dibuja. |

**Lo que queda para ED-07.** El arrastre (`assets/timeline-drag.js`) todavía no trata un bloque
`ai` como una foto o un video: hoy solo cambia de lugar los bloques `video` y `photo`, y un `ai`
caería en el modo de un texto o un efecto (correrlo en el tiempo). ED-07 lo
suma al montar el bloque en la pista, junto con el ícono «i» del motivo (`--q-ai-icon`).

**Lo que NO hace.** No muestra el modo con colores distintos por modo. No pone botones sobre la
parte en la pista. No crea nada al agregarla: todo es gratis hasta «Crear» o «Probar esta
parte». No le da «Velocidad», «Girar» ni «Cortar» a una parte con IA.

**Accesibilidad.** Lo de §5.10 más: el nombre accesible del bloque dice todo («Parte con IA 1,
Nueva, de 0:06 a 0:11, sin crear»); las cápsulas son `aria-hidden` porque ese nombre ya las
lee; en alto contraste (`forced-colors`) se ocultan el póster y su velo y el punto del estado
toma el color del texto.

Demo en `/design`: sección «Parte con IA en la línea de tiempo» (`#parte-con-ia`), estática:
todos los estados, los anchos de 3, 2 y 1 s, un video y una foto propios para comparar, la
insignia completa del panel y la marca de la vista previa.

---

## 6. Patrones de pantalla

### 6.1 Ciclo de vida de una lista (el patrón de todas las páginas de datos)

```
load_error != ""      → callout(load_error, "error")          (reemplaza la lista)
is_loading            → skeleton_card()/skeleton_rows()        (forma del contenido — nunca un spinner)
show_empty_state      → empty_state(...)                        (con la acción que lo resuelve)
else                  → la lista/tabla
action_error != ""    → callout(action_error, "warn")           (ENCIMA de la lista, no la reemplaza)
is_working            → loading_spinner("sm") + la frase        (sync/scraping/publicación en curso)
```

La distinción `load_error` (tomato, reemplaza) vs `action_error` (amber, encima) es de producto: si la lista en pantalla sigue siendo verdad, no se la quita. Y la de `is_loading` (skeleton) vs `is_working` (spinner) es la regla de espera de §5.4.

### 6.2 Acción destructiva
Botón `soft` gris con icono → `rx.alert_dialog` con título en infinitivo ("Desconectar cuenta"), descripción con la entidad en negrita y la consecuencia, `Cancelar` (soft) + verbo (solid tomato). El verbo del botón, del título del diálogo y del toast posterior es **el mismo** (§7.3).

### 6.3 Estado degradado accionable
Un estado que el usuario puede arreglar lleva **el botón que lo arregla dentro del mismo callout** (`degraded_banner`: "Volver a conectar"). Un icono de alerta sin acción es decoración.

### 6.4 Provisionalidad honesta
Lo que depende de una fuente no verificada se marca (`tone_badge("por verificar", "warn", icon="circle-help")` + tooltip con el motivo). Lo temporal se enmarca en `demo_notice`. Nunca se hace pasar por definitivo.

### 6.5 Página con configuración previa
Si el tenant no configuró (Clarity sin proyecto), la configuración sube arriba del cuerpo; una vez configurada, se pliega en un `rx.accordion` al final. La página siempre muestra el último snapshot guardado y dice cuánto cuesta refrescar.

---

## 7. Escritura UX

### 7.1 Voz
- **Español latino neutro, de tú.** "Conecta tu primera cuenta", no "Conecte su cuenta" ni "Conectá tu cuenta". Sin excepciones: el voseo no se usa en ninguna pantalla.
- **Sentence case** en títulos, botones y cabeceras: "Cuentas conectadas", no "Cuentas Conectadas". (Las cabeceras de tabla las pone en mayúsculas el skin, §5.7; el código sigue en sentence case.)
- Verbos concretos en botones: "Conectar cuenta", "Desconectar", "Publicar", "Sincronizar comentarios". Nunca "Enviar", "OK", "Aceptar" para acciones con consecuencia.
- Sin relleno ni disculpas: "No se pudo cargar la lista. Recarga la página o vuelve más tarde." — no "Lo sentimos, ha ocurrido un error inesperado".
- Nombrar por lo que el operador controla, no por cómo está construido: "cuenta conectada", no "social_connection"; "permiso de comentarios", no "instagram_manage_comments" (el scope técnico va en un `tag` como detalle, no como nombre).

### 7.2 Glosario (usar siempre la misma palabra)

| Concepto | Palabra en UI | No usar |
|---|---|---|
| tenant | **negocio** | tenant, cuenta, workspace, empresa |
| social_connection | **cuenta conectada** (la pantalla se llama «Tus redes») | conexión |
| earned mention | **mención** | post, publicación ajena |
| own media a monitorear | **contenido** / **Reel** | inbox, media |
| DM/comentario recibido | **mensaje** / **comentario** | thread |
| lead | **cliente interesado** (pestaña «Interesados» de Por responder) | lead, prospecto, contacto |
| creator | **creador** | influencer (salvo copy de marketing) |
| señal derivada | **señal** | evento, alerta (alerta = una señal que exige acción) |
| Fecha de verificación | "Verificada: …" | "Last verified" |

### 7.3 Consistencia verbo → resultado
El botón dice "Publicar" → el estado dice "Publicando…" (con `loading_spinner("sm")`) → el toast dice "Publicado". El botón dice "Desconectar" → el diálogo se titula "Desconectar cuenta" → el estado queda "Desconectada".

#### Cuentas de redes y WhatsApp (m-24854866)

| Situación comprobada | Estado visible | Acción |
|---|---|---|
| Cuenta activa | Conectada | Sin acción de recuperación |
| Cuenta que necesita reconexión o fue desconectada | Desconectada | Volver a conectar |
| Falta un permiso necesario para una función | Sin acceso | Volver a conectar y aceptar el permiso |

Estos son estados de presentación. `active` se muestra como «Conectada»;
`degraded` y `revoked`, como «Desconectada». `revoked` también puede resultar de
una desconexión voluntaria: no basta para afirmar que se quitó un permiso.
«Sin acceso» exige evidencia de permiso faltante, como `permission_missing` o
la evaluación de capacidades. No se inventa un motivo a partir de un error de red.
Durante la conexión se permite «Conectando…»; ante un valor desconocido,
«Sin verificar», sin mostrar el valor interno.

- Un solo verbo de recuperación: **Volver a conectar**.
- Aviso `warn` dentro de la pantalla, encima de lo guardado; conservar el contenido.
- Explicar el permiso faltante con un texto propio. Ayuda: «¿No tienes acceso a ese Facebook? Pide ayuda».
- WhatsApp: «Este arreglo lo hace el equipo de Qualify» y «Avisar al equipo de Qualify».
- En estos mensajes no se muestran «Meta», «token», estados técnicos ni códigos de error.
- Al confirmar la reconexión: «Listo: {cuenta} está conectada otra vez.». Solo se
  muestra tras confirmar el resultado; iniciar o cancelar el flujo no es éxito.

### 7.4 Empty states
Título = el hecho, en presente ("Aún no conectas ninguna cuenta", "Todavía no tienes clientes interesados"). Cuerpo = por qué importa + qué hacer, ≤ 2 frases. Si hay una acción que lo resuelve, es **el** botón `solid` de la página.

### 7.5 Errores
Qué pasó (en términos del operador) + qué hacer. Nunca el stack trace, nunca el código HTTP como único texto. Un mismo mensaje para todas las causas cuando la distinción no le sirve al operador (login: "Email o contraseña incorrectos." para todo — regla firmada, se conserva).

---

## 8. Accesibilidad (piso, no aspiración)

- **Contraste:** texto en pasos 11-12 sobre 1-3; `TEXT_FAINT` prohibido para texto informativo. Radix garantiza el ratio dentro de esas bandas en claro y oscuro **sobre fondos opacos**. **Sobre vidrio, el ratio lo garantiza el relleno, no Radix:** por eso el material claro no es el del Lab (dark-only) sino uno más lechoso — islas con blanco al 64 % (`--q-glass-fill`, `opacidad + 0.55`), tarjetas al 78 → 52 % (`--q-card-fill`), campos al 66 %, header al 62 %, diálogo al 88 % — y por eso el panel de página es opaco (§10.12): una tabla de 50 filas sobre vidrio es ruido. La verificación ≥ 4,5:1 en vidrio claro en todas las rutas es tarea del lote 6 (§9.3).
- **No color-solo:** P1. Sentimiento, salud, plataforma: siempre palabra.
- **Foco visible:** `:focus-visible` outline 2px accent-8 en todo (`assets/qualify.css`); los campos cambian el outline por el anillo del acento (§5.6), igual de visible.
- **Teclado:** todo lo interactivo es un botón/link/control Radix nativo (los diálogos atrapan foco y cierran con Esc). Un `rx.box` con `on_click` está prohibido: usa `rx.button variant="ghost"`. La cápsula del menú sigue al foco igual que al puntero (§4.2).
- **Semántica:** un solo `h1` por página (`page_header`); `section`/`empty_state` emiten `h2`, títulos de entidad en tarjeta `h3`; las cifras y el wordmark son `rx.text`, no headings (Radix `Heading` es `h1` por defecto — pasar siempre `as_=`). El sidebar es `<nav aria-label="Secciones">` con `aria-current="page"` (que además es lo que la cápsula lee para reposar), el cuerpo es `<main>`; callouts de error `role="alert"`; skeletons `aria-busy`; el spinner `role="status"` con `aria-label="Cargando"`; la cápsula, la etiqueta zen y el filtro SVG son `aria-hidden`. Verificado en `/design`: 1 h1, `nav` y `main` presentes.
- **Tamaño de toque:** controles ≥ 32px de alto (Radix size 2); size 1 solo en contextos densos y secundarios. El kit pide 46 px (`--lq-control-height`); se registra pero **no** se adopta: la escala de Radix se queda.
- **Movimiento:** `prefers-reduced-motion` cubre, pieza a pieza, lo que el vidrio añadió: la **cápsula** no viaja ni se deforma (el script la coloca en seco), la **luz del puntero** se apaga, el **brillo** de cápsula y etiqueta zen (`::after`) no barre, el **shimmer** del skeleton y el **sweep** de la barra de progreso se detienen, el drawer no desliza y el panel de progreso no funde. Y desde m-24840374 hay **apagado global**, el de la landing (§3.3.1): toda animación a 0,01 ms y sin retardo, toda transición a 0 s, y ni `.q-lift`, ni los botones, ni `choice_card` suben o se hunden. La única excepción es el aviso `.q-slow-hint`, que conserva sus 12 s porque no es movimiento.
- **Táctil:** la etiqueta zen y la luz del puntero no existen con puntero grueso — bajo un dedo no dicen nada.
- **Celular (N12):** en ≤ 640 px todo objetivo mide ≥ 44 × 44 px (filas del menú, botón del cajón, celdas de la barra inferior) y nada depende de `:hover`. La barra inferior (§4.4) es un segundo `<nav>` («Accesos rápidos») con texto siempre visible, `aria-current` en la celda activa y «Más» como botón con `aria-expanded`.
- **Idioma:** `rx.App(html_lang="es")` — verificado en el `<html>` emitido.

---

## 9. Cómo extender

### 9.1 Checklist para una pantalla nueva (o para migrar una)

1. `app_shell(page_header(...), page_body(...))`. Sin `sidebar()` ni padding propio.
2. Ciclo de vida §6.1 con `callout`/`skeleton_*`/`empty_state`; espera según §5.4 (skeleton = carga, `loading_spinner` = trabajo).
3. Colores solo vía `T.*` y tonos. Si necesitas un color que no existe, primero pregúntate si es un tono nuevo (raro) o un uso nuevo de uno existente (casi siempre). **Cero hex, cero `rx.color(` en la página.**
4. Estados con `signal_pill`/`tone_badge`; identidad con `platform_badge`; etiquetas con `tag`.
5. Una sola acción `solid`. Verbos del glosario §7.2.
6. Cifras con `q-nums`; ids con `mono`.
7. Movimiento sólo con `T.SPRING`/`T.EASE` y las tres duraciones; elevación sólo `ELEV_*`, y sólo a través del sistema (`card`, clases `.q-*`): **ninguna página escribe `box_shadow=`, `backdrop_filter=` ni `text_shadow=`**. Si una tarjeta no hace nada al pulsarla, no se levanta. Vidrio ≤ 8 por pantalla, nunca en grids.
8. **No inventes un componente.** Regla del plan (§0): un *widget* que una pantalla ya usa sin regla (un `rx.select`, un `rx.table`, un chip casero) **se trae al sistema** — regla en §5, skin en `qualify.css`, ejemplo en `/design` — eso es migrar. Lo que no existe ni en nuestras pantallas ni en el kit **no se crea**. Una primitiva nueva en `Qualify/ui/primitives.py` sólo se admite si (a) ≥ 2 pantallas ya repiten esa receta a mano **y** (b) el kit la trae; si no se cumplen ambas, se usa Radix directo con el skin global. Si falta un widget, la respuesta es «¿qué primitiva existente o qué Radix con skin lo resuelve?», no un archivo nuevo.
9. **Tu CSS va a la hoja de tu dominio (D10)**, no a `qualify.css`: `qualify-planner.css` (Planificador), `qualify-brand.css` (Brand Kit y creativo), `qualify-publish.css` (Publicar y catálogo), `qualify-inbox.css` (Contenido / inbox). `qualify.css` queda para tokens, puente, skin de Radix, shell y primitivas compartidas. Las hojas se registran en ese orden en `rx.App(stylesheets=…)` (`Qualify/Qualify.py`) y heredan todos los tokens. Se mueven bloques enteros, no se editan reglas al moverlas.
10. **Pasa el guard.** `Qualify/test_design_system_guard.py` (AST puro, corre en el gate offline de `just test`) recorre todo módulo `Qualify/*.py` fuera de `ui/` y de `styleguide_page.py` (la guía renderiza las escalas crudas a propósito; es el único archivo con permiso para `rx.color`) y falla ante: un literal hex como valor de un prop o dentro de `style={…}` (los hex que son *datos* — una paleta leída de un logo, el color de una campaña — no son estilo y pasan); `rx.color(` fuera de `ui/`; `rx.skeleton(`/`rx.spinner(`; `box_shadow=`/`backdrop_filter=`/`text_shadow=`. Los módulos que los lotes A–E aún no migraron están en `_PENDING`: **un lote saca sus archivos de la lista como parte de su definición de hecho, nunca se vuelve a añadir uno**, y `test_pending_list_is_honest` expulsa de la lista a cualquier archivo que ya esté limpio (y rechaza nombres que no existen). Un módulo nuevo nace fuera de `_PENDING` — es decir, nace limpio.
11. Ábrela en `/design` mentalmente: si tuviste que tocar una primitiva, muéstrala en `styleguide_page.py` y documéntala en §5.
12. `just lint` + `just test` (los tests puros no importan páginas; el compilador de Reflex es la prueba de que renderiza). Capturas claro / oscuro / 375 px en el PR.

### 9.2 Cómo cambiar el sistema
- **Acento/gris/radio Radix/modo por defecto:** `rxconfig.py`. Un cambio. El tinte del material sigue al acento solo.
- **El material (blur, opacidad, saturación, radio de isla, edge, refracción, frecuencia, profundidad):** los diales `--q-lab-*` en `assets/qualify.css` (y `LAB_REFRACTION`/`LAB_FREQUENCY` en `ui/layout.py` para los dos que viven en el filtro SVG). Se mueven en el Glass Lab del kit y se copian; no se aproximan.
- **Radios de card/control, curvas, sombras, rellenos por rol y tema:** el puente «Liquid Glass: token bridge» en `assets/qualify.css`.
- **El aspecto de un componente Radix:** su bloque en «Liquid Glass: Radix skin», con diff contra `reference/liquid-glass/…/liquidos.css`. Nunca se edita el kit.
- **Fuentes, gutter, foco:** `assets/qualify.css`. Un cambio.
- **Mapeo tono → escala, plataforma → color, zona → tinte:** `Qualify/ui/tokens.py`.
- **Una regla nueva de componente:** regla en §5 + skin o primitiva mutada + ejemplo en `/design` (+ el guard, si la regla es prohibitiva).
- Después de cualquier cambio: abrir `/design` en claro y oscuro.

### 9.3 Deuda conocida (ordenada)

Cerrado por el lote 0 (2026-10-08): el tooltip zen que nunca se veía (ahora etiqueta de vidrio, §4.2); la receta de tarjeta plana de v2 (`card` es material); el `_CARD` dict de vitrina y el `rx.card` de clarity pasan a los lotes A (están en `_PENDING` del guard, que los expulsa cuando queden limpios); la ausencia de un enforcement (guard).

Abierto:

1. **`liquidos.css` no se carga, por diseño** (D2, §3.4). Consecuencia: cada componente del kit que se quiera usar hay que redibujarlo en el skin; lo que el kit tiene y el skin aún no cubre (range/slider, check/radio, accordion, tabs, separator, `lq-tilt`/`lq-reveal`) **se ve Radix crudo** hasta que un lote lo necesite y lo traiga (regla §9.1-8). El JS del kit (ripple, sheen) tampoco: sólo la luz del puntero está portada, en `glass-nav.js`.
2. **Presupuesto de `backdrop-filter`.** El shell con sesión ya gasta 7 (6 islas + header). Un overlay abierto son 8; una página con vidrio propio se pasa. Medición por ruta pendiente (lote 6); la regla «nunca en grids» hay que comprobarla en planificador, borradores y catálogo (`.q-kind-chip--glass` ya lleva un blur de 6 px por tile).
3. ~~**`prefers-reduced-motion` no es global**~~ — cerrado por m-24840374 (2026-11-16): apagado global como el de la landing (§3.3.1, §8).
4. **Venv compartido con reflex 0.9.7 mientras `uv.lock` pide 0.9.12.** El skin se verificó en 0.9.7; las clases `.rt-*` de Radix Themes que el skin selecciona pueden cambiar entre versiones. No se sincroniza en worktrees (trampa documentada en `CLAUDE.md`); el upgrade se decide fuera de esta migración y obliga a repasar `/design`.
5. **Contraste sobre vidrio claro** sin verificar ruta a ruta (lote 6).
6. **Duraciones:** `--lq-duration` (420 ms) está en el puente como registro, pero `--q-dur*` siguen en 140/240/380 ms. El plan (D7) hablaba de escalarlas; hoy no se hace. Decidir si se adopta o se retira del puente.
7. **`head_components` muertos** (react-helmet no inyecta en dev, D11): `deck-drag.js`, `rank-drag.js` y el atajo `⌘ .` siguen declarados allí; `glass-nav.js` ya se carga desde `sidebar()`. Tarea aparte.
8. **Verificación visual de páginas de negocio con sesión real**: `/design` y `/login` se verifican sin sesión; las páginas tras `require_login` se verifican por render de componentes (misma `app_shell`), no con una sesión viva.
9. Toasts (`rx.toast`) adoptados en `/inbox` (2026-08-25); el resto de confirmaciones transitorias siguen como callouts persistentes. Migrarlas según §5.4 cuando se toquen.
10. Fuentes desde Google Fonts: mover a `assets/fonts/` (self-host) si se quiere evitar la dependencia externa en producción.

---

## 10. Decisiones y su porqué

### 10.1 Acento `teal`, gris `slate` (antes: `violet`, gris por defecto)
- Violeta era el acento por defecto del scaffold y hoy es el color genérico del "SaaS con IA"; además chocaba con `purple` (TikTok) y con `violet` (interés de lead), de modo que el acento no significaba nada.
- Teal está lejos de los tres tonos semánticos (grass/amber/tomato), del info (blue) y de las plataformas (pink/purple/blue), así que "acento = acción/marca" no compite con ningún otro significado.
- Slate es un gris frío que mantiene el verde semántico inequívoco (sage habría teñido de verde los neutros).
- Es un token: si el fundador decide otro color de marca, es una línea en `rxconfig.py`. **Confirmado el 2026-10-08 al adoptar el kit:** teal/slate se quedan; el tinte del vidrio es el acento.

### 10.2 IBM Plex Sans + Plex Mono
- Necesitábamos una familia con mono hermano y buenos numerales tabulares: la UI está llena de `@handles`, ids, cifras y timestamps, y el producto es "señales y métricas". Plex resuelve las tres cosas con una sola familia y una sola decisión.
- Se descartó Inter (default de todo el mundo, sin mono hermano) y una display serif (no aporta a una consola operativa; sería decoración, P4).
- Coste: una dependencia externa a Google Fonts (§9.3-10). Reafirmada en 10.11.

### 10.3 Sin sombras (v1 — superada)
- En v1 las tarjetas se distinguían por borde + fondo gray-2 y la sombra era exclusiva de lo que flota sobre la página. v2 la convirtió en «una sola sombra de reposo + ascenso reservado» (10.7); v3 pone las dos sombras del kit en ese mismo par (10.12). La idea que sobrevive: **la elevación significa algo**; lo que cambió es el valor, no la regla.

### 10.4 Primitivas mínimas, Radix directo para el resto
- Solo se envolvió lo que porta una regla Qualify (tono, variante-por-categoría, gutter, forma de estados). Envolver `rx.button` o `rx.input` sin regla habría creado una API paralela sin valor. v3 lo lleva más lejos: Radix directo **recibe el material por skin global**, así que la primitiva sigue sin hacer falta (10.9), y la regla «no se crean componentes» de §9.1-8 la fija.

### 10.5 `/design` sin login y sin enlace en el sidebar
- No contiene datos de tenant y sirve a quien construye pantallas, no al operador. Estar fuera del sidebar evita confundirlo con producto. Es también el único archivo que puede llamar `rx.color` (muestra las escalas crudas).

### 10.6 Migración en el mismo cambio
- Un design system que solo existe en un doc y en una carpeta nueva no cambia nada. Se migraron las 8 páginas para que la próxima pantalla copie del código vigente, no del viejo. La migración Liquid Glass sigue el mismo principio, por lotes de dominio (plan §4).

### 10.7 Islas flotantes y muelle (propuesta C, elegida 2026-08-19)

Se prototiparon tres menús — dos planos con tinte, un ciclo numerado en tres etapas, e islas flotantes — y se eligió el tercero. Lo que se compró con esa elección, y por qué:

- **La separación la hace el aire, no una línea.** Un sidebar con reglas horizontales pide una jerarquía que este menú no tiene (ninguna zona manda sobre otra). Bloques separados por hueco agrupan igual de bien sin inventar orden.
- **El muelle es la firma.** El colapso del rail es el movimiento más frecuente de la app, así que es el que define cómo se siente. En v3 la curva es la del kit (10.13), la regla no cambia: se extiende a todo lo que cambia de tamaño o forma; lo demás se queda en `ease`.
- **La etiqueta se revela con máscara.** Un fundido dice «apareció»; una máscara dice «estaba ahí detrás del icono».
- **La elevación gana significado al restringirla.** El reposo es una sola sombra baja y el ascenso al hover está reservado a `card(interactive=True)`.
- **Lo que se descartó:** la numeración de etapas de la propuesta B y su panel flotante al hover en zen — que v3 acabó recuperando como etiqueta de vidrio (§4.2), una vez que el drawer móvil quedó decidido.

### 10.8 Liquid Glass: el kit pone el material, la paleta es nuestra (D1/D2, fundador 2026-10-08)
- El encargo fue «migrar al kit respetando nuestra paleta». El kit vale por el **material** (vidrio, relieve, brillo, movimiento); sus colores (violeta `#8b7cff`, cian `#51d7ff`, Inter) no son parte de su valor y chocarían con todo lo decidido en 10.1 (el violeta volvería a confundirse con TikTok). Resultado: el puente `--lq-*` (§3.4) escribe los tokens del kit **mapeados a Radix** y `rxconfig.py` sigue siendo el único sitio donde se cambia un color.
- **`liquidos.css` no se carga** (enmienda al ejecutar el lote 0): sus resets son dark-only y pelearían con Radix, y sus clases apuntan a HTML que Reflex no emite. Se vendoriza como fuente para diffs y cada componente se redibuja sobre Radix. Un design system con dos hojas que se pisan no es un sistema.

### 10.9 Radix sigue dando el comportamiento; el kit, el material (D1)
- Reescribir 184 botones / 70 selects / 19 diálogos con el HTML del kit rompería eventos y estado de Reflex, el focus trap, Esc, el autocompletado del login (fallo firmado §6.1) y la a11y que ya tenemos. Se re-skinea vía CSS sobre `.rt-*`; las primitivas `ui.*` emiten las clases `q-*`. El propio kit documenta que su valor es `lq-glass`, no sus controles.
- Por lo mismo, de `liquidos.js` no entra nada: tabs, dialog, toast y reveal del kit duplicarían Radix, Sonner y React y romperían foco y estado (D8). Sólo se porta lo que es puro DOM delegado (la luz del puntero, en `glass-nav.js`).

### 10.10 Oscuro por defecto; claro sigue (D3)
- El kit es dark-first y el material se definió en su Glass Lab, que es dark-only: el oscuro es el material «de fábrica». Por eso `appearance="dark"` en `rxconfig.py` (fundador, 2026-10-08).
- El claro **no se abandona**: el operador entra entre tareas a plena luz. Tiene su propio material (mismos diales, blanco más lechoso, §3.4) definido como variables por tema, no como un tema aparte. Forzar sólo oscuro habría sido renunciar a la mitad de los usos.

### 10.11 IBM Plex se queda; Inter no entra (D4)
- 10.2 sigue vigente: el producto es cifras y `@handles`, y Plex da mono hermano y numerales tabulares. Inter es el default del kit, no parte de su valor.

### 10.12 Material por rol y panel opaco (D5/D6)
- `backdrop-filter` se paga por elemento y por píxel. 72 `card` y las grids de tiles en vidrio pleno se arrastrarían en portátiles y móviles. De ahí tres materiales: *island* (vidrio con blur: sidebar, overlays, header sticky), *card* (relieve translúcido **sin** blur) y *control* (relieve). Nunca blur en grids; ≤ 8 por pantalla.
- **El panel principal es opaco** (`--color-panel-solid`), con el suelo asomando por los bordes y vidrio sólo en el header sticky — patrón macOS (sidebar translúcido, contenido opaco). La alternativa (panel frosted, más fiel al kit) perdía legibilidad con tablas y formularios: una tabla de 50 filas sobre vidrio es ruido.

### 10.13 Movimiento: las dos curvas del kit (D7)
- `--q-spring := --lq-ease-spring`, `--q-ease := --lq-ease`. Un cambio en dos tokens y todo el sistema (zen, lift, drawer, stepper) adopta la firma del kit. Dos curvas siguen siendo dos curvas (P8); las tres duraciones no cambiaron (§9.3-6). La cápsula del menú es la única pieza con curvas propias: son la coreografía del dock, medida, y no se generalizan.

### 10.14 Scripts: dentro del componente, no en `head_components` (D8/D11)
- Medido 2026-10-08: `head_components` pasa por react-helmet y no inyecta nada en el build de desarrollo. Un script del navegador se carga con `rx.el.script(src=…, async_=True)` dentro del componente que lo necesita (`glass-nav.js` en `sidebar()`), con guard `window.__q*` para no correr dos veces, delegado al documento y re-asentado ante mutaciones, porque Reflex remonta el sidebar en cada ruta.

### 10.15 Enforcement = test estático (D9) y la regla de espera (D12)
- «SIEMPRE enforzar»: una regla que no falla en CI no es una regla. `Qualify/test_design_system_guard.py` (mismo patrón que `test_object_store_sanctity.py`) prohíbe en las páginas hex, `rx.color(`, sombras/vidrio a mano y `rx.skeleton`/`rx.spinner`. `_PENDING` sólo encoge, y un archivo limpio es expulsado de ella automáticamente: la lista no puede pudrirse.
- **Skeleton = carga de contenido; spinner = trabajo en curso** (fundador, 2026-10-08): un spinner sobre una lista vacía no dice nada; un skeleton con la forma del contenido sí. Y un skeleton sobre un scraping engañaría: ahí no hay forma todavía, hay trabajo. Enforzado por el mismo guard.

### 10.16 Una hoja CSS por dominio (D10)
- Cinco equipos en paralelo no pueden compartir un archivo de 2.000 líneas sin conflictos. `qualify.css` conserva lo compartido (tokens, puente, skin, shell, primitivas); planificador, brand, publish e inbox tienen la suya, registradas en orden tras la base. Se movieron bloques enteros sin editar reglas, para que el diff de la partición fuera verificable.

### 10.17 Los diales del Glass Lab son el contrato (D14)
- Un design system con un «builder» pero sin registro de qué se eligió no es reproducible. Cada dial del Lab es un token `--q-lab-*` (y dos constantes en `layout.py` para el filtro SVG); las fórmulas son las del Lab (`builderCss`), no una aproximación. Para cambiar el material: mover los diales en el Lab, copiar los números. Los diales son el contrato entre UX y código.
- Y una decisión de alcance que vino con el kit (D13): **el calendario del planificador se conserva** (semanal por horas); el del kit es un selector de mes de un solo día. Lo que migra es la piel — cuadrícula, celdas y chips sobre el material *card* (lote C).

### 10.18 Barra inferior en el celular: un patrón nuevo, opaco y con los mismos nombres (decisión 5, 2026-10-23)
- **Por qué existe:** el dueño usa Qualify con una mano entre clientes (`perfil-cliente-pyme.md` §5); detrás de ☰, lo de todos los días cuesta dos toques y un estirón del pulgar. El fundador decidió la barra (decisión 5) y que se documentara aquí antes de construirla (§4.4). Es la excepción explícita a «no inventes un componente» (§9.1-8): la abre una decisión del fundador, no la repetición en pantallas, y no sienta precedente.
- **Por qué opaca y no de vidrio:** el contenido se desplaza por debajo y los textos de la barra tienen que leerse igual sobre cualquier foto; el presupuesto de `backdrop-filter` ya está casi lleno en el shell (§9.3-2). Misma razón que el panel opaco (§10.12).
- **Por qué los mismos nombres, iconos, rutas y contadores que el sidebar:** N1 (un nombre por lugar) y N11 (lo pendiente se cuenta donde se resuelve). Una segunda fuente de rutas o de cifras se desincronizaría con la primera; la barra solo lee las de `layout.py` y `PendingState`.
- **Por qué 640 px:** es el punto donde el sidebar ya es cajón; con otro corte convivirían dos navegaciones.

### 10.19 Marco de paso a paso: la anatomía del cajón para todo asistente (PASOS-1, fundador 2026-10-25)
- **Por qué existe:** el fundador lo pidió así (2026-10-24): «ir atrás (no existen)», «saber en qué paso estamos», «las opciones de continuar ocultas abajo del todo». La revisión encontró que diez flujos repiten a mano la misma receta, el contador y la fila Atrás · Siguiente, y que ninguno la deja a la vista. Cumple la condición (a) de §9.1-8, que la receta se repita en dos pantallas o más, y lo aprobó el fundador.
- **Por qué no es un componente inventado:** reusa la anatomía del `drawer` (cabeza y pie fijos), la isla opaca de la barra inferior y `.q-page-header`. No trae colores, curvas ni materiales nuevos.
- **Por qué el pie reemplaza la barra inferior en el celular, en vez de apilarse:** dos islas abajo le quitan alto al contenido justo en el celular y ponen dos botones grandes al alcance del pulgar que hacen cosas distintas. Mientras dura un asistente, lo que importa es seguir o salir, y la salida está en la cabeza.
- **Por qué «Seguir después» lleva a Inicio:** una sola regla en todos los asistentes (N2). Inicio es donde aparece lo que quedó a medias.
