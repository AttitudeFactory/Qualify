# Qualify — UX/UI y Design System

`[v3 — 2026-10-08]` · Aplica a la app Reflex en `Qualify/` · Código: `Qualify/ui/` (`tokens.py`, `layout.py`, `primitives.py`), `assets/qualify.css` (+ una hoja por dominio: `qualify-planner.css`, `qualify-brand.css`, `qualify-publish.css`, `qualify-inbox.css`), `assets/glass-nav.js`, `rxconfig.py`, `Qualify/test_design_system_guard.py` · Guía viva: ruta `/design` · Plan de la migración: `docs/plan-migracion-liquid-glass.md`

> **Regla de la casa:** el sistema vive en el código, no en este documento. Este doc explica *por qué* y *cuándo*; `Qualify/ui/` dice *cómo*, `/design` lo demuestra renderizado con el tema real y `test_design_system_guard.py` lo hace cumplir en CI. Si algo aquí contradice a `Qualify/ui/` o a `assets/qualify.css`, gana el código y hay que corregir el doc.

> **v3 (2026-10-08):** el sistema adopta el **material** del kit Liquid Glass (LiquidOS Studio 3.0) conservando nuestra paleta, nuestra tipografía y nuestras primitivas. Lo que cambia está en §3.4 (material y diales), §4.2 (el menú de vidrio), §5 (skin de Radix, regla de espera), §9 (guard, hojas por dominio) y §10.8–10.17 (decisiones D1–D14 del plan). Lo que no se menciona sigue igual que en v2.

---

## 0. Qué es esto y para quién

Qualify es la consola con la que el operador de uno o varios negocios locales (cafetería, agencia de viajes, inmobiliaria, microcentro comercial — Cúcuta/Táchira hoy) **escucha** lo que se dice de su negocio en redes y **actúa**: conecta cuentas, publica, elige qué contenido monitorear, revisa leads, lee la salud de su web. Un login = un negocio, sin switch. El operador está ocupado, entra entre tareas, casi siempre en laptop y a veces en el móvil.

De ahí las tres preguntas que toda pantalla debe responder, en este orden y sin scroll:

1. **¿En qué negocio estoy?** (el nombre del negocio encabeza el sidebar; debajo, «Supported by Qualify» enlaza al landing)
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
  │🏪 Negocio ⇤│ │ Título de página [badge]        [acciones] [◐] │ ← page_header (vidrio, sticky)
  │Supported by│ │ subtítulo muted                                │
  │  ◎ Qualify │ │                                                │
  └────────────┘ │ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
  ┌────────────┐ │ │stat_card │ │stat_card │ │stat_card │  ← page_body (gutter PAGE_X)
  │ Tus redes  │ │ └──────────┘ └──────────┘ └──────────┘         │
  └────────────┘ │ callout (si hay error de acción)               │
  ┌────────────┐ │ ┌────────────────────────────────────────────┐ │
  │ ESCUCHAS   │ │ │ card / tabla / lista …                     │ │
  │ Menciones  │ │ └────────────────────────────────────────────┘ │
  │ Comentarios│ │                                                │
  │ Creadores ·│ │                                                │
  │ Señales   ·│ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ PUBLICAS   │ │                                                │
  │ Crear publ.│ │                                                │
  │ Por aprobar│ │                                                │
  │ Tu semana  │ │                                                │
  │ Publ. ahora│ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ Interesados│ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ NEGOCIO    │ │                                                │
  │ Tu pág. web│ │                                                │
  │ Tu marca   │ │                                                │
  │ Tus product│ │                                                │
  │ Config.   ·│ │                                                │
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
- `page_body(*children, spacing="4", align_items="start")`: aplica el gutter y el tope de ancho, y hace **entrar los bloques escalonados** al cargar (`.q-settle`, 40 ms entre hijos, tope a partir del quinto; sólo `transform`, nunca opacidad — una entrada no puede ser el único camino al contenido). Los hijos **no** llevan padding horizontal propio.
- `section(title, *children, description=None, actions=())`: h2 con descripción y acciones para dividir un cuerpo largo.

### 4.2 El sidebar: vidrio líquido, zonas y modo zen

El menú está ordenado por el flujo de trabajo, y las dos zonas teñidas son los dos ejes del producto (`docs/index.md`): lo que dice el mercado y lo que dice el negocio.

| Isla | Contiene | Tinte (lavado bajo el vidrio) |
|---|---|---|
| Negocio (arriba) | nombre del tenant, «Supported by ◎ Qualify» → `LANDING_URL`, control de zen | neutra |
| Base | Tus redes — habilita las dos zonas, así que no pertenece a ninguna | neutra |
| **Escuchas** (inbound) | Menciones · Comentarios · Conversaciones · Creadores · Señales | `accent` alfa 3, línea alfa 6 |
| **Publicas** (outbound) | Crear publicación · Por aprobar · Tu semana · Publicar ahora | `iris` alfa 3, línea alfa 6 |
| Suelta | Interesados (página «Clientes interesados») | neutra |
| **Negocio** (pie) | Tu página web · Tu marca · Tus productos · Configuración · Salir | neutra |

**El menú es vidrio líquido** (`assets/qualify.css` «Liquid glass menu» + `assets/glass-nav.js`; adaptado de `real-liquid-glass-os-effect.html`, un dock horizontal, a nuestras islas verticales):

- **Islas** (`.q-island`, `_island` en `layout.py`): material *island* de §3.4 — relleno `--q-glass-fill`, borde al dial de edge, highlight interior, capa de profundidad refractada, `backdrop-filter` con los diales. El tinte de zona es un **lavado alfa debajo del vidrio** (`--q-zone-tint` → alfa 3, `--q-zone-line` → alfa 6, puestos por `T.zone_tint`/`T.zone_line` como custom properties): un paso opaco taparía el suelo que el vidrio debe refractar. `flex-shrink: 0`: una isla nunca se encoge para caber (con `overflow: hidden` recortaría sus filas); el nav scrollea.
- **Luz del puntero**: el relleno «liquid» tiene una luz suave que sigue al cursor (`--q-pointer-x/y`, escritas por el script en la isla bajo el puntero). Apagada con puntero grueso (táctil) y con `prefers-reduced-motion`.
- **La cápsula** (`.q-glass-blob`, una por isla, **dentro** de la isla — obligado: `backdrop-filter` hace de cada isla un stacking context, y una cápsula fuera sólo podría pintar sobre toda la isla o debajo, nunca entre su relleno y sus filas). Es el único resalte del menú: **su estado de reposo es la fila activa** (`aria-current="page"` en el link de la fila), sin palabra. Vuela a la fila bajo el puntero con la coreografía del dock (la palabra sale primero, el vidrio arranca a los ~40 ms, la palabra nueva crece a los ~235 ms), se deforma en la dirección del viaje (`skewY` ±2,5°, estirón y asentamiento; menos que los 7° del dock porque nuestras filas son anchas), y el icono de la fila se levanta 1 px. Al cambiar de isla, la anterior se apaga y la nueva entra deslizándose por el borde por el que llega. **Teclado igual que puntero** (`focusin`/`focusout`). Al salir, vuelve a reposo tras 120 ms.
- **La etiqueta zen** (`.q-glass-label`): con el rail contraído, el nombre aparece al lado del rail como una segunda pieza de vidrio con **cuello** apuntando a su fila, creciendo desde un desenfoque (`blur(5px)` → 0). Fija en el viewport (el nav recorta su overflow), sólo con puntero fino. Sustituye al tooltip `::after` de v2, que el `overflow: hidden` de la fila recortaba y nunca se veía.
- **Sin script = fallback plano**: hasta que `glass-nav.js` marca el nav con `data-glass`, la fila activa lleva `accent-a4` y el hover `gray-a3` (`.q-sidebar:not([data-glass])`). Un documento sin JS sigue diciendo dónde estás.
- **Carga del script**: `rx.el.script(src="/glass-nav.js", async_=True)` **dentro de `sidebar()`**, no en `rx.App(head_components=…)` — medido 2026-10-08, `head_components` pasa por react-helmet y no inyecta nada en el build de desarrollo (§10.14). El script se guarda de correr dos veces (`window.__qGlassNav`), delega todo al documento y se re-asienta con un `MutationObserver` filtrado (sólo mutaciones que tocan un sidebar; nunca las de sus propios nodos) y un `ResizeObserver`, así sobrevive a que Reflex remonte el sidebar en cada cambio de ruta y a la transición de ancho del zen.

Tres reglas que sostienen esto:

1. **El tinte es superficie, no señal.** Se queda en alfa 3 (lavado) y alfa 6 (línea): agrupa, pero no puede confundirse con un estado (P1/P2). Subirlo es una decisión consciente, no un ajuste.
2. **Tu página web, Tu marca y Tus productos viven fuera de las zonas de color**, en el pie: miden ventas y comportamiento web, o son lo que la marca *es*, no conversación.
3. **Salir es el único control de sesión** (`1 login = 1 negocio`, sin switch). Sin sesión (`/design`) el nombre cae a «Qualify».

**Zen** (`NavState.zen`, botón en la isla del negocio o `⌘ .`): el rail se contrae a 72 px con muelle, las etiquetas se **revelan con máscara** (`clip-path`) en vez de fundirse, y el nombre aparece en la etiqueta de vidrio de arriba. Todo el colapso es **una clase** (`q-zen`) en el `nav`: las reglas viven en `assets/qualify.css`, no en condicionales de Python — así el navegador puede animarlo y no hay dos árboles que mantener. El estado vive en la sesión del servidor, nunca en el navegador: persistir en el cliente exigiría clave namespaced por tenant y purga en logout (regla firmada), y para un modo de vista no compensa.

**Móvil (< 640 px):** el sidebar es un overlay fijo cerrado por defecto, abierto por el botón hamburguesa (`_mobile_nav_toggle`, fuera del sidebar porque el drawer empieza cerrado) con un fondo que lo cierra al tocar fuera; elegir una página también lo cierra.

### 4.3 Reglas de página

1. Toda página de negocio lleva el sidebar completo y el toggle de modo en el header. Solo `/login`, `/registro` y el wizard del Brand Kit (`rail=False`) no llevan sidebar.
2. El header no scrollea con contenido pesado — y ahora literalmente: es sticky. Lo que "vive" arriba son controles de página (selector de cuenta, botón de actualizar), no contenido.
3. Densidad: tablas para listas homogéneas y comparables (leads, menciones); tarjetas para entidades con estados y acciones propias (conexiones, reels). No mezclar en la misma lista.
4. Responsive: el gutter baja a 1rem y el aire entre islas a 6px por debajo de 900px; grids usan `rx.breakpoints(…)`; tablas envuelven en `overflow_x="auto"`; por debajo de 640px el sidebar es drawer (§4.2).
5. **Toda fila del sidebar usa la misma geometría** (`_nav_row`): el envoltorio — link o botón — no lleva padding ni fondo propio (el fondo es la cápsula). Es lo que garantiza que en zen todos los iconos caigan en la misma columna y que la cápsula mida lo mismo en todas las filas.
6. **Presupuesto de vidrio:** ≤ 8 superficies con `backdrop-filter` por pantalla (el shell gasta: islas del sidebar + header sticky; un overlay abierto, una más). Nada de vidrio dentro de grids.

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

**La regla de espera (fundador, 2026-10-08; D12):** hay dos formas de esperar y no son intercambiables. **Skeleton = carga de contenido, SIEMPRE**: algo se está *leyendo* y va a aparecer en ese sitio — el placeholder tiene la forma de lo que viene. **Spinner = trabajo en curso**: algo se está *haciendo* — scraping, generación, sync, publicación, subida, clonado de voz — y no hay «forma» todavía, hay trabajo; el anillo va junto a la frase que dice qué pasa. Un spinner sobre una lista vacía no dice nada; un skeleton sobre un scraping mentiría. Las dos puertas son `ui.skeleton_card`/`ui.skeleton_rows` y `ui.loading_spinner`; `test_design_system_guard.py` falla el build ante un `rx.skeleton(` o un `rx.spinner(` en una página (§9.1). Un `rx.button(loading=…)` es un prop, no una llamada, y sigue permitido.

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

`loading_spinner` (`.q-spinner`) es el anillo del kit (`.lq-spinner`): pista `gray-a4`, acento encima, 0,85 s por vuelta. Su color sale de las escalas del tema, así que **se adapta solo a claro/oscuro: no existe una variante de tema que elegir**. La única variante real es `size` — `sm` (1.25rem) en línea junto a texto, `md` (2.25rem, por defecto) una espera aislada, `lg` (3.5rem) una espera de panel completo. Demo en vivo: `/design` → «Estados de pantalla».

**Toasts** (`rx.toast`, Sonner): la misma lámina de vidrio que los overlays (`lq-toast`: `--q-overlay-fill`, radio 16 px, blur 28 px, `ELEV_LIFT`) entrando por la esquina inferior derecha con el pop de muelle (`q-toast-pop`, sobre `scale`, que no pelea con el `transform` de Sonner).

### 5.5 Botones (Radix directo, con el skin del kit)

El skin es el `lq-button` del kit sobre `.rt-Button`/`.rt-IconButton`: radio 14 px (10 px en size 1), peso 700, y:

- `solid` (por defecto, acento) = `lq-button--primary`: **degradado del acento** (accent-9 → 10 → 8 a 135°), highlight interior y sombra teñida `accent-a5`; al hover sube 2 px y la sombra crece. **Una** por pantalla — la acción que responde "¿qué hago ahora?".
- `soft` / `outline` / `surface` = el botón de **vidrio** (material control: `--q-control-edge` + `--q-control-hi` + `--q-control-shadow`; al hover, borde más marcado y 2 px arriba). `soft`: secundarias (Desconectar, Cancelar). `outline`: terciarias.
- `ghost` = `lq-button--ghost`: sin relieve; dentro de tablas/filas y para el toggle de modo.
- Pulsado: `scale(0.975)`. Deshabilitado: sin sombra ni movimiento.
- Destructiva: `soft` + `color_scheme=T.tone_scale("error")`; en el diálogo de confirmación, `solid` tomato (el degradado toma la escala del `color_scheme`).
- Tamaños: `2` por defecto; `1` dentro de badges de sesión/filas; `3` solo en empty states.
- Icono + texto: icono a la izquierda, `size=16` (o `ICON_SM` en size 1). Nunca icono solo sin `aria-label`.
- Estados: `loading=Var` en cualquier botón que dispare I/O; `disabled` cuando la precondición no se cumple **y** el motivo está visible cerca.

### 5.6 Formularios (Radix directo, con el skin del kit)

- Campos, text areas y el trigger del select tienen el look `lq-field`: un **pozo de vidrio hundido** (`--q-field-fill`, radio 12 px, hairline interior) que se aclara al foco con el anillo del acento (`accent-a8` + halo `accent-a3` de 4 px). El switch encendido es un degradado del acento con el pulgar flotando (`lq-switch`); el segmented control, una pista hundida con una pestaña de vidrio (`lq-segmented`, radio 15/11 px) — sustituye a cualquier `q-flow-switch` casero.
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
| `drawer(*children, open=, on_open_change=, title=, description=None, footer=None, width="32rem", icon=None)` | un flujo más largo que un diálogo, que el operador recorre sin perder la pantalla de fondo: la asignación del Planificador | **la misma lámina `lq-dialog`** pegada al **borde derecho** (`.q-drawer`: `--q-dialog-fill`, hairline a la izquierda, `ELEV_OVERLAY`), ancho fijo en escritorio y **pantalla completa en móvil**; construido sobre `rx.dialog`, así Esc, el clic en el fondo, el focus trap y el ARIA vienen de Radix; el cuerpo se desplaza, título y pie quedan fijos (el pie es transparente: la lámina ya es el fondo). Uno a la vez, nunca anidado. Con `icon`, la cabecera lleva un glifo de acento antes del título |
| `stepper(labels, current=, completed=, on_select=None, icons=None)` | la cabecera de ese flujo: los pasos en orden | check lleno = completado (clicable con `on_select`, para volver a corregir); anillo = actual; número = aún no alcanzado (nunca clicable, así nada se confirma con un paso incompleto). El check y el paso actual con glifo llevan el degradado del acento. Etiquetas estáticas, estado dinámico. En móvil (y dentro del drawer) solo se lee la etiqueta del paso actual. Con `icons` (un glifo por paso) el paso no alcanzado muestra su glifo en lugar del número — el Planificador lo usa así |

Reglas del flujo (Planificador, referencia): un paso solo se abandona cuando es válido y el motivo se lee junto a «Siguiente»; el paso de confirmación es donde aterriza la respuesta del servicio (`callout("error")` encima del botón); un rechazo no deja nada a medias. Demo en vivo: `/design` → «Flujo por pasos».

### 5.9 Elegir, subir, mostrar, conversar (2026-10-09)

Cuatro recetas que los lotes de la migración Liquid Glass repetían en dos o más pantallas y que el kit también trae — las dos condiciones del plan (§0) para admitir una primitiva. El fundador las aprobó el 2026-10-09; desde entonces son la única puerta a su material (`assets/qualify.css`, «Shared primitives») y las hojas de dominio ya no llevan sus propias versiones (`q-cr-option`, `q-choice` de tarjeta, `q-pick-card`, `q-inbox-thumb`, `q-catalog-thumb`, `q-trend-thumb`, `q-brand-avatar`, `q-cr-dropzone`, `q-inbox-reply`).

| Primitiva | Cuándo | Anatomía y reglas |
|---|---|---|
| `choice_card(*children, selected=, on_select=, role="radio"\|"checkbox", disabled=False, padding=…)` | una opción que se elige entre varias (tipo de pieza, producto del catálogo, look del avatar, receta, plan del Brand Kit) | **un `<button>` real** con la tarjeta como cuerpo (§8: nunca `rx.box` + `on_click`); material card; elegida = anillo de 2 px del acento + lavado + halo (`.q-choice-card--on`, gana al hover); `disabled` = punteada y quieta, con el motivo en los hijos; el estado también va en `aria-checked`. `choice_card_check()` pone el check sólido del kit en la esquina de la elegida cuando el anillo solo sería poco (P1). Los chips-píldora del Planificador (`.q-choice`, `qualify-planner.css`) son otra cosa y siguen allí |
| `dropzone(*children, upload_id=, on_drop=, accept=, max_files=, multiple=, variant="zone"\|"compact"\|"tile"\|"bare", tile_size=…)` | **toda** subida de archivos | `rx.upload.root` vestido con el campo hundido y punteado del kit (`.q-dropzone`), acento al pasar un archivo o llegar con teclado. `zone` = el prompt grande del estado vacío; `compact` = pozo pequeño en un formulario; `tile` = cuadrado en una grilla de medios (`tile_size`); `bare` = sin material, los hijos son el look (un botón, una loseta entera). **El guard prohíbe `rx.upload`/`rx.upload.root` en las páginas**: el `rx.upload` estilizado pinta un borde punteado inline que ninguna clase puede sobreescribir — esa es la trampa que esconde |
| `media_thumb(src, size="72px", width=, height=, round=False, icon="image", icon_size=, alt="", fit="cover", has=…)` | la foto de un Reel, un producto, un video trending, un referente; el avatar de una cuenta | la imagen en el marco del sistema (`.q-thumb`: material control, hairline, radio control) o, si no hay, el mismo marco con `icon` — una lista nunca muestra un hueco ni el glifo de imagen rota. `round=True` es el avatar (`lq-avatar`). `size` cuadra; `width`/`height` lo sobreescriben (`height` solo + `width="100%"` = la foto arriba de una tarjeta). `has` sustituye la prueba `src != ""` cuando el VM ya lo sabe. `alt=""` por defecto (decorativa junto a su propio título) |
| `chat_bubble(*children, direction="out"\|"in", meta=None)` | un mensaje de una conversación: el borrador de respuesta del inbox hoy; los DMs de 4-B mañana | la burbuja del kit: `out` = lo que decimos (lavado del acento, cola abajo a la izquierda), `in` = lo que dijeron (material control, cola abajo a la derecha); `meta` (hora, estado) va dentro, debajo del texto |

Demo en vivo: `/design` → «Elegir, subir, mostrar, conversar».

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
Un estado que el usuario puede arreglar lleva **el botón que lo arregla dentro del mismo callout** (`degraded_banner`: "Reconectar"). Un icono de alerta sin acción es decoración.

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
| lead | **cliente interesado** (menú: «Interesados») | lead, prospecto, contacto |
| creator | **creador** | influencer (salvo copy de marketing) |
| señal derivada | **señal** | evento, alerta (alerta = una señal que exige acción) |
| Fecha de verificación | "Verificada: …" | "Last verified" |

### 7.3 Consistencia verbo → resultado
El botón dice "Publicar" → el estado dice "Publicando…" (con `loading_spinner("sm")`) → el toast dice "Publicado". El botón dice "Desconectar" → el diálogo se titula "Desconectar cuenta" → el estado queda "Revocada" (nombre del estado, no del verbo — está bien que difieran ahí, porque describe la fila, no la acción).

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
- **Movimiento:** `prefers-reduced-motion` cubre, pieza a pieza, lo que el vidrio añadió: la **cápsula** no viaja ni se deforma (el script la coloca en seco), la **luz del puntero** se apaga, el **brillo** de cápsula y etiqueta zen (`::after`) no barre, el **shimmer** del skeleton y el **sweep** de la barra de progreso se detienen, el drawer no desliza y el panel de progreso no funde. No hay un apagado global: la entrada `.q-settle`, el ascenso `.q-lift` y el pop del toast siguen (pendiente en §9.3).
- **Táctil:** la etiqueta zen y la luz del puntero no existen con puntero grueso — bajo un dedo no dicen nada.
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

1. **`liquidos.css` no se carga, por diseño** (D2, §3.4). Consecuencia: cada componente del kit que se quiera usar hay que redibujarlo en el skin; lo que el kit tiene y el skin aún no cubre (avatar/avatar-stack, range/slider, check/radio, accordion, tabs, separator, `lq-tilt`/`lq-reveal`) **se ve Radix crudo** hasta que un lote lo necesite y lo traiga (regla §9.1-8). El JS del kit (ripple, sheen) tampoco: sólo la luz del puntero está portada, en `glass-nav.js`.
2. **Presupuesto de `backdrop-filter`.** El shell con sesión ya gasta 7 (6 islas + header). Un overlay abierto son 8; una página con vidrio propio se pasa. Medición por ruta pendiente (lote 6); la regla «nunca en grids» hay que comprobarla en planificador, borradores y catálogo (`.q-kind-chip--glass` ya lleva un blur de 6 px por tile).
3. **`prefers-reduced-motion` no es global** (§8): `.q-settle`, `.q-lift` y el pop del toast siguen moviéndose. Decidir si se apagan (v2 decía que sí y no era cierto).
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
