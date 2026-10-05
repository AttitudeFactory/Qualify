# Qualify — UX/UI y Design System

`[v2 — 2026-08-19]` · Aplica a la app Reflex en `Qualify/` · Código: `Qualify/ui/`, `assets/qualify.css`, `rxconfig.py` · Guía viva: ruta `/design`

> **Regla de la casa:** el sistema vive en el código, no en este documento. Este doc explica *por qué* y *cuándo*; `Qualify/ui/` dice *cómo*, y `/design` lo demuestra renderizado con el tema real. Si algo aquí contradice a `Qualify/ui/`, gana el código y hay que corregir el doc.

---

## 0. Qué es esto y para quién

Qualify es la consola con la que el operador de uno o varios negocios locales (cafetería, agencia de viajes, inmobiliaria, microcentro comercial — Cúcuta/Táchira hoy) **escucha** lo que se dice de su negocio en redes y **actúa**: conecta cuentas, publica, elige qué contenido monitorear, revisa leads, lee la salud de su web. Un login = un negocio, sin switch. El operador está ocupado, entra entre tareas, casi siempre en laptop y a veces en el móvil.

De ahí las tres preguntas que toda pantalla debe responder, en este orden y sin scroll:

1. **¿En qué negocio estoy?** (el nombre del negocio encabeza el sidebar; debajo, «Supported by Qualify» enlaza al landing)
2. **¿Qué pasa?** (cifras, estados, señales)
3. **¿Qué hago ahora?** (una acción principal por pantalla)

Este documento cubre: principios (§1), auditoría del estado previo (§2), fundamentos/tokens (§3), layout (§4), componentes (§5), patrones (§6), escritura UX (§7), accesibilidad (§8), cómo extender (§9) y decisiones con su justificación (§10).

---

## 1. Principios

| # | Principio | Qué significa en la práctica |
|---|---|---|
| P1 | **Estado = color + icono/punto + palabra** | Nunca color solo. Sentimiento, salud de conexión, intento de publicación, sync: siempre `signal_pill`/`tone_badge` con la palabra escrita. El caso de tres estados ("desconocido") es la razón: color-solo lee como un "no" suave. |
| P2 | **La variante codifica la categoría** | Badge `soft` = estado · `outline` = identidad (plataforma, entidad) · `surface` = etiqueta/categoría · `solid` = solo la acción principal (botones). Ver §5.3. |
| P3 | **Una acción principal por pantalla** | Un solo botón `solid`; lo demás `soft`/`outline`/`ghost`. Si hay dos "principales", falta decidir. |
| P4 | **Islas flotantes** | Toda superficie flota sobre el fondo de la app con la elevación de reposo (`T.ELEV_ISLAND`). Los grupos se separan por **aire**, no por líneas. Y la elevación **significa** «esto responde»: sólo sube al hover lo que hace algo al pulsarlo (`card(interactive=True)`). |
| P5 | **Vacío y error dirigen** | Un estado vacío es una invitación a actuar (hecho + siguiente paso). Un error dice qué pasó y cómo se arregla; no se disculpa ni es vago. |
| P6 | **Cifras e identificadores tienen su tipografía** | Números tabulares (`q-nums`) en tablas y stat cards; `@handles`, ids y timestamps en mono (`q-mono`). El producto es señales y métricas; que se lean como tales. |
| P7 | **Tokens por rol, nunca por valor** | Una pantalla pide `T.TEXT_MUTED`, `tone="error"`, `T.PAGE_X`; no pide `"tomato"` ni `"2rem"`. Así el sistema se mueve una vez y en todos lados. |
| P8 | **Dos curvas, tres duraciones** | Muelle (`T.SPRING`) para lo que cambia de tamaño o de forma; ease (`T.EASE`) para color, opacidad y máscara. Si un movimiento pide otra curva, es que no encaja en el sistema. |
| P9 | **Español, tú, sentence case** | La UI habla al operador de tú, en español latino neutro, con verbos concretos. Ver §7. |

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

---

## 3. Fundamentos (tokens)

Fuente de verdad: `Qualify/ui/tokens.py` (Python) + `assets/qualify.css` (CSS). Radix Themes provee las escalas; Qualify decide el rol.

### 3.1 Color

**Base (fijada una vez en `rxconfig.py`):** `accent_color="teal"`, `gray_color="slate"`, `radius="medium"`, `scaling="100%"`, `panel_background="solid"`. Modo claro/oscuro: Radix, con toggle en cada header.

**Cómo se lee una escala Radix (1-12), y qué paso usar para qué:**

| Pasos | Rol | Ejemplo Qualify |
|---|---|---|
| 1-2 | Fondos de app / de superficie | página = gray-1, tarjeta = gray-2 (`SURFACE_BG`) |
| 3-5 | Superficies interactivas (hover/activo) | nav activo = accent-4; hover nav = gray-a3 |
| 6-8 | Bordes y separadores | borde = gray-5 (`BORDER`), fuerte = gray-7, foco = accent-8 |
| 9-10 | Sólidos (botón, punto de estado, cifra) | `status_dot` = tono-9; cifra de stat = tono-10 |
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

Regla de degradación: un tono no mapeado cae en `neutral`, nunca en `accent` ni en alarma (`tone_scale` lo garantiza).

**Identidad de plataforma** (`T.PLATFORM_SCALE`, siempre badge `outline`): Instagram `pink` · TikTok `purple` · Facebook `blue` · WhatsApp `green`. Son identidades, no estados: por eso nunca `soft` y nunca sin la palabra.

**Contraste:** texto solo en pasos 11-12 sobre fondos 1-3 (Radix garantiza ≥ 4.5:1). `TEXT_FAINT` (gray-8) es para iconos decorativos y placeholders, **no** para texto que deba leerse.

### 3.2 Tipografía

- **UI:** IBM Plex Sans (400/500/600/700). **Identificadores y cifras:** IBM Plex Mono (400/500). Cargadas desde Google Fonts en `Qualify.py`; las variables Radix `--default-font-family` / `--code-font-family` se sobreescriben en `assets/qualify.css`. Fallback: `system-ui`.
- **Escala Radix (`size` 1-9)** con estos usos fijos por página:

| Uso | Componente | Tamaño |
|---|---|---|
| Título de página (h1) | `page_header` → `rx.heading` | 6 |
| Título de sección (h2) | `section` / `empty_state` | 4 / 5 |
| Título de entidad en tarjeta | `rx.heading` | 4 |
| Cifra en stat card | `stat_card` | heading 7 |
| Cuerpo | `rx.text` | 2 (3 en nav) |
| Meta / ayuda / nota | `rx.text` + `TEXT_MUTED` | 1 |

- `.q-nums` → `font-variant-numeric: tabular-nums` (tablas, cifras). `.q-mono` → mono a 0.92em (handles, ids, fechas técnicas). `heading-letter-spacing: -0.012em`.
- No hay display face: el título de página en Plex Sans 600 a size 6 **es** el display. Restricción deliberada (P4/P6): la personalidad va en el mono y en las señales, no en un titular decorativo.

### 3.3 Espacio, forma, elevación, movimiento

| Token | Valor | Uso |
|---|---|---|
| `T.PAGE_X` = `--q-page-x` | 2rem (1rem < 900px) | gutter horizontal de toda página |
| `T.PAD_HEADER` | `1.5rem PAGE_X 1rem PAGE_X` | bloque del título |
| `T.PAD_BODY` | `0 PAGE_X 2rem PAGE_X` | todo lo demás |
| `T.PAD_EMPTY` | `4rem PAGE_X` | empty states |
| `T.SIDEBAR_W` / `T.SIDEBAR_ZEN_W` | 232px / 72px | sidebar expandida · rail zen |
| `T.GAP` | 10px (6px < 900px) | aire entre islas, panel y borde de pantalla |
| `T.CONTENT_MAX` | 1440px | tope del cuerpo en pantallas muy anchas |
| Espaciado interno | escala Radix `spacing` 1-9 (4/8/12/16/24/32…) | `spacing="3"` dentro de tarjetas, `"4"` entre bloques |
| `T.RADIUS_ISLAND` | 0.875rem (1rem en zen) | islas del sidebar, panel de página |
| `T.RADIUS_CARD` | 0.75rem | tarjetas, callouts |
| `T.RADIUS_CONTROL` | 0.5rem | nav, thumbnails, bandas |
| `T.ELEV_ISLAND` | `--shadow-2` | reposo de toda superficie flotante |
| `T.ELEV_LIFT` | `--shadow-3` | hover de una tarjeta **interactiva** |
| `T.ELEV_OVERLAY` | `--shadow-5` | diálogos, popovers |
| `T.SPRING` | `cubic-bezier(.34,1.4,.5,1)` | ancho, forma, colapso del rail |
| `T.EASE` | `cubic-bezier(.22,.8,.25,1)` | color, opacidad, máscara |
| `T.DUR_FAST` · `T.DUR` · `T.DUR_SLOW` | 140 · 240 · 380 ms | hover · elevación · colapso |
| `T.GROUND` / `T.SURFACE_BG` / `T.CARD_BG` | `--color-background` / `--color-panel-solid` / gray-2 | fondo de la app · isla · tarjeta dentro del panel |

Las sombras salen de la rampa propia de Radix (`--shadow-1..6`), ya calibrada para claro y oscuro: por eso la elevación no necesita una definición por tema. Lo mismo con el par fondo/isla (`--color-background` / `--color-panel-solid`), que Radix garantiza que se lean como «isla sobre fondo» en ambos. `prefers-reduced-motion` apaga todo el movimiento de golpe, elevación al hover incluida.

Iconos: lucide, tres tamaños (`ICON_SM`=14 dentro de badges/botones size 1, `ICON_MD`=18 en nav y botones size 2, `ICON_LG`=40 en empty states). Nada intermedio.

---

## 4. Layout

### 4.1 El shell: islas sobre el fondo

```
  ┌────────────┐ ┌────────────────────────────────────────────────┐
  │🏪 Negocio ⇤│ │ Título de página [badge]        [acciones] [◐] │ ← page_header
  │Supported by│ │ subtítulo muted                                │
  │  ◎ Qualify │ │                                                │
  └────────────┘ │ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
  ┌────────────┐ │ │stat_card │ │stat_card │ │stat_card │  ← page_body (gutter PAGE_X)
  │ Conexiones │ │ └──────────┘ └──────────┘ └──────────┘         │
  └────────────┘ │ callout (si hay error de acción)               │
  ┌────────────┐ │ ┌────────────────────────────────────────────┐ │
  │ ESCUCHAS   │ │ │ card / tabla / lista …                     │ │
  │ Menciones  │ │ └────────────────────────────────────────────┘ │
  │ Contenido  │ │                                                │
  │ Creadores ·│ │                                                │
  │ Señales   ·│ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ PUBLICAS   │ │                                                │
  │ Marca      │ │                                                │
  │ Crear pieza│ │                                                │
  │ Borradores │ │                                                │
  │ Publicar   │ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ Leads      │ │                                                │
  └────────────┘ │                                                │
  ┌────────────┐ │                                                │
  │ NEGOCIO    │ │                                                │
  │ Clarity    │ │                                                │
  │ Vitrina    │ │                                                │
  │ Config.   ·│ │                                                │
  │ ───────────│ │                                                │
  │ ⇥ Salir    │ │                                                │
  └────────────┘ └────────────────────────────────────────────────┘
```

```python
from .ui import app_shell, page_header, page_body

def leads_index() -> rx.Component:
    return app_shell(
        page_header("Leads", "Personas captadas por tu funnel", badge=rx.badge("12 leads", ...)),
        page_body(_body()),
    )
```

- `app_shell(*children)`: el fondo de la app (`T.GROUND`) con dos cosas flotando encima — el sidebar (`nav` sticky) y el panel de página (`main`), ambos con `T.RADIUS_ISLAND` y `T.ELEV_ISLAND`. El ítem activo se deriva de la ruta.
- `page_header(title, subtitle=None, *actions, badge=None)`: h1 + subtítulo; a la derecha, `actions` (selectores, botones de la página) y el toggle de modo. `badge` va **junto al título** y describe la página ("demo", un conteo), nunca es una acción.
- `page_body(*children, spacing="4")`: aplica el gutter y el tope de ancho, y hace **entrar los bloques escalonados** al cargar (`.q-settle`, 40 ms entre hijos, tope a partir del quinto). Los hijos **no** llevan padding horizontal propio.
- `section(title, *children, description=None, actions=())`: h2 con descripción y acciones para dividir un cuerpo largo.

### 4.2 El sidebar: zonas y modo zen

El menú está ordenado por el flujo de trabajo, y las dos zonas teñidas son los dos ejes del producto (`docs/index.md`): lo que dice el mercado y lo que dice el negocio.

| Isla | Contiene | Tinte |
|---|---|---|
| Negocio (arriba) | nombre del tenant, «Supported by ◎ Qualify» → `LANDING_URL`, control de zen | neutra |
| Base | Conexiones — habilita las dos zonas, así que no pertenece a ninguna | neutra |
| **Escuchas** (inbound) | Menciones · Contenido · Creadores · Señales | `accent` paso 2 |
| **Publicas** (outbound) | Marca · Crear pieza · Borradores · Publicar | `iris` paso 2 |
| Suelta | Leads | neutra |
| **Negocio** (pie) | Clarity · Vitrina · Configuración · Salir | neutra |

Tres reglas que sostienen esto:

1. **El tinte es superficie, no señal.** Se queda en el paso 2 de la escala: agrupa, pero no puede confundirse con un estado (P1/P2). Subirlo es una decisión consciente, no un ajuste.
2. **Vitrina y Clarity viven fuera de las zonas de color**, en el pie: miden ventas y comportamiento web, no conversación.
3. **Salir es el único control de sesión** (`1 login = 1 negocio`, sin switch). Sin sesión (`/design`) el nombre cae a «Qualify».

**Zen** (`NavState.zen`, botón en la isla del negocio o `⌘ .`): el rail se contrae a 72 px con muelle, cada isla redondea un poco más, las etiquetas se **revelan con máscara** (`clip-path`) en vez de fundirse y el nombre aparece en un tooltip al pasar el ratón. Todo el colapso es **una clase** (`q-zen`) en el `nav`: las reglas viven en `assets/qualify.css`, no en condicionales de Python — así el navegador puede animarlo y no hay dos árboles que mantener. El estado vive en la sesión del servidor, nunca en el navegador: persistir en el cliente exigiría clave namespaced por tenant y purga en logout (regla firmada), y para un modo de vista no compensa.

### 4.3 Reglas de página

1. Toda página de negocio lleva el sidebar completo y el toggle de modo en el header. Solo `/login` y `/signup` no llevan sidebar.
2. El header no scrollea con contenido pesado: lo que "vive" arriba son controles de página (selector de cuenta, botón de actualizar), no contenido.
3. Densidad: tablas para listas homogéneas y comparables (leads, menciones); tarjetas para entidades con estados y acciones propias (conexiones, reels). No mezclar en la misma lista.
4. Responsive: el gutter baja a 1rem y el aire entre islas a 6px por debajo de 900px; grids usan `rx.breakpoints(…)`; tablas envuelven en `overflow_x="auto"`. El colapso automático del rail en móvil sigue pendiente (§9.3).
5. **Toda fila del sidebar usa la misma geometría** (`_nav_row`): el envoltorio — link o botón — no lleva padding. Es lo que garantiza que en zen todos los iconos caigan en la misma columna.

---

## 5. Componentes

Todo en `Qualify/ui/primitives.py` salvo lo indicado. Radix (`rx.button`, `rx.input`, `rx.select`, `rx.table`, `rx.dialog`, `rx.alert_dialog`, `rx.tooltip`, `rx.switch`, `rx.accordion`, `rx.skeleton`, `rx.callout`) se usa **directamente** cuando no hay regla Qualify que encapsular; las primitivas existen solo donde hay una regla.

### 5.1 Superficies

| Primitiva | Cuándo | Notas |
|---|---|---|
| `card(*children, padding="1.25rem", interactive=False, **props)` | cualquier bloque delimitado | fondo `CARD_BG`, hairline y `ELEV_ISLAND`. `interactive=True` añade el ascenso al hover — sólo si al pulsarla pasa algo |
| `stat_card(label, value, tone="accent", hint=None)` | una cifra con su etiqueta | tono solo en la cifra; `q-nums` |
| `kv(label, value, mono=False)` | par etiqueta/valor en un panel de detalle | `mono=True` para ids |
| `mono(text)` | identificador inline | handles, ids, timestamps |

### 5.2 Estado (la señal)

| Primitiva | Cuándo | Anatomía |
|---|---|---|
| `signal_pill(label, tone)` | **default** para cualquier cosa con ciclo de vida: sentimiento, sync, intento de publicación | punto tono-9 + palabra, badge `soft` `radius=full` |
| `tone_badge(label, tone, icon=None, size="1")` | verdicto a nivel tarjeta o celda que debe escanearse | icono 12px + palabra, `soft` |
| `status_dot(tone)` | solo como parte de otra composición | nunca solo (P1) |
| `sentiment_badge(var)` | sentimiento | `positive`/`POS→ok`, `negative`/`NEG→error`, `NEU→neutral`, `""→"Sin analizar"` (QUA-92: pendiente de análisis, nunca se confunde con NEU), resto `neutral` |

### 5.3 Identidad y etiquetas

| Primitiva | Variante | Cuándo |
|---|---|---|
| `platform_badge(platform)` | `outline` + color de plataforma | plataforma de una cuenta/mención. Acepta `str` o `Var` |
| `tag(label)` | `surface` gris | interés, fuente, scope, tema — metadata, no estado |
| `removable_pill(label, on_remove, icon=None, leading=None, suggested=False)` | `surface` gris con ✕; `suggested=True` → `soft` acento | un valor que el operador cura y puede quitar: un hashtag, una palabra vetada, un archivo subido. `suggested` marca lo que propuso el producto y el operador aún no escribió. Nunca un tono: una pill quitable no es un veredicto |
| `pill_editor(items, draft=, on_draft_change=, on_add=, on_remove=, placeholder=)` | pills + input con Enter / "+" | una lista que se arma de a un valor (listas del Brand Kit: ejemplos, CTAs, palabras vetadas, claims). `on_remove` recibe el índice. Sustituye a los textarea "uno por línea" |
| badge de conteo (`rx.badge(..., variant="soft", color_scheme="gray")`) | `soft` gris | "12 leads" junto a un título |

**Tabla de decisión — ¿qué badge?**

| Es… | Usa | Nunca |
|---|---|---|
| un estado que cambia | `signal_pill` / `tone_badge` | `outline`, `solid` |
| quién/qué es (plataforma, entidad) | `platform_badge` (`outline`) | `soft` con tono |
| una categoría/etiqueta libre | `tag` (`surface`) | color de tono |
| la acción principal | `rx.button` `solid` | un badge |

### 5.4 Feedback

| Primitiva / Radix | Cuándo | Cuándo no |
|---|---|---|
| `callout(message, tone="info", icon=None)` | feedback **persistente y ubicado**: error de carga en lugar de la lista, error de acción **encima** de la lista (la lista sigue siendo válida), aviso de cuota | confirmaciones transitorias → `rx.toast` |
| `demo_notice(message)` | contenido de demo/temporal (banda punteada `warn`) | errores |
| `rx.alert_dialog` | confirmar acciones destructivas o irreversibles (desconectar, borrar) | acciones reversibles |
| `rx.tooltip` | aclarar un marcador ("por verificar") | contenido esencial |
| `empty_state(icon, title, description, action=None)` | lista vacía / sin configuración | como error |
| `skeleton_card(lines=3)` / `skeleton_rows(n)` | carga inicial, con la forma del contenido esperado | espera de página/panel completo |
| `loading_spinner(size="sm"\|"md"\|"lg")` | espera de página/panel completo — todo el contenido se reemplaza, no hay "forma esperada" que dibujar | carga inicial de una lista/tabla → skeleton; el spinner propio de un botón (`loading=Var`, §5.5) ya lo resuelve Radix solo |
| `progress_panel(title, detail, value=None, steps=None, creep_seconds=30)` | espera que **bloquea** el paso (no se puede seguir hasta que termine): análisis de voz, búsqueda de referentes, sugerencia de hashtags. Con `value` (0-100) muestra progreso real; sin él, avanza con el tiempo hasta ~90 % y desaparece al terminar. `steps` son las etapas: la que está en curso es el comentario **encima** de la barra, sin spinner al lado (`progress_step_row`, 2026-10-02). Entra con un fundido corto al cambiar la vista. **Es el único loader del Brand Kit** (2026-10-02): carga de la marca, análisis del perfil, referentes, generador | fuera del Brand Kit, una espera corta sin etapas → `loading_spinner`; carga de una lista → skeleton; dentro de un botón o una línea de estado → `loading_spinner("sm")` |

Iconos por defecto del callout: `error`/`warn` → `triangle-alert`, `ok` → `check`, `info` → `info`. Un callout de error lleva `role="alert"`; los demás `role="status"`.

`loading_spinner` (2026-09-05, `Qualify/ui/primitives.py` + `.q-spinner` en `assets/qualify.css`) es un anillo con degradado cónico — no el `rx.spinner` de rayas de Radix. Su color sale de la escala de gris del tema (`--gray-12` sobre transparente), así que **se adapta solo a claro/oscuro: no existe una variante de tema que elegir**. La única variante real es `size` — `sm` en línea junto a texto, `md` (por defecto) una espera aislada, `lg` una espera de panel completo (el que usa el wizard del Brand Kit, `_loading_view`). Demo en vivo: `/design` → sección "Cargando".

### 5.5 Botones (Radix directo, con reglas)

- `solid` (por defecto, acento): **una** por pantalla — la acción que responde "¿qué hago ahora?".
- `soft`: secundarias (Desconectar, Cancelar). `outline`: terciarias. `ghost`: dentro de tablas/filas.
- Destructiva: `soft` + `color_scheme=T.tone_scale("error")`; en el diálogo de confirmación, `solid` tomato.
- Tamaños: `2` por defecto; `1` dentro de badges de sesión/filas; `3` solo en empty states.
- Icono + texto: icono a la izquierda, `size=16` (o `ICON_SM` en size 1). Nunca icono solo sin `aria-label`.
- Estados: `loading=Var` en cualquier botón que dispare I/O; `disabled` cuando la precondición no se cumple **y** el motivo está visible cerca.

### 5.6 Formularios (Radix directo, con reglas)

- Etiqueta visible encima (`rx.text size=2 weight=medium`), ayuda debajo en `size=1 TEXT_MUTED`. Placeholder = ejemplo, no etiqueta (excepción documentada: `/login` y `/signup`, donde interferir con el autocompletado del navegador está prohibido por el fallo firmado §6.1 — allí el placeholder es la etiqueta y así se queda).
- `name`, `type` y `required` nativos: el navegador valida y autocompleta.
- Error de envío en `callout("error")` **encima del formulario**, no como toast.
- Selects para elegir entre entidades del tenant (cuentas conectadas); switches para monitorear/activar; búsquedas con `rx.input.slot(rx.icon("search"))`.

### 5.7 Tablas y listas

- `rx.table.root(variant="surface")`, cabeceras en sentence case, numéricas alineadas a la derecha y con `q-nums`.
- Identidad en la primera o segunda columna (`platform_badge`, `mono` para handles); estado con `signal_pill`.
- Texto largo (captions) truncado con `text_overflow="ellipsis"` a un `max_width` fijo.
- Envolver en `rx.box(overflow_x="auto")`.

### 5.8 Temperatura del POST (`thermal_badge`, `thermal_glyph`, `lottie`) — 2026-10-05

| Primitiva | Cuándo | Anatomía |
|---|---|---|
| `thermal_badge(state, animate=False, size="1")` | **el** estado de un POST en cualquier pantalla (lista, tarjeta del Planificador, detalle) | `signal_pill`-like: tono + glifo + palabra. `animate=True` sólo en el detalle y en el momento del cambio; en listas y tablas el glifo estático |
| `thermal_glyph(state, size="4rem", melting=False)` | el héroe de una transición (congelar al aprobar, el check al publicar) | la animación sola, grande; `melting=True` es el deshielo de Congelado |
| `lottie(src, loop=, autoplay=, size=, reduced_motion_fallback=, tone=)` | cualquier animación Lottie | `LottieLight` de `lottie-react` (MIT, carga diferida) + su gemelo estático; `prefers-reduced-motion` muestra el icono, nunca un fotograma congelado |

El mapeo estado real → temperatura vive en `Qualify/ui/thermal.py` (`thermal_for`) y se prueba contra la FSM real (`Qualify/test_thermal_vm.py`). La lectura térmica de los tonos: **lado caliente = `warn`** (Caliente, Humeante: hay algo temporal que te va a pedir atención), **lado frío = `info`** (Congelado, Programado, En camino, Frío reutilizable: está en el sistema, nada que hacer), **entregado = `ok`**, Encendido/Apagado/Archivado `neutral`, Fallido `error`. Los archivos (`assets/lottie/`) son propios, generados por `Qualify/ui/lottie_shapes.py`, ≤ 7 KB cada uno, con el paso 9 de la escala del tono (idéntico en claro y oscuro). Regla de movimiento: a lo sumo **una** animación en bucle por pantalla; un error nunca se anima. Doc: [ux-post-journey-termico.md](ux-post-journey-termico.md).

---

## 6. Patrones de pantalla

### 6.1 Ciclo de vida de una lista (el patrón de todas las páginas de datos)

```
load_error != ""      → callout(load_error, "error")          (reemplaza la lista)
is_loading            → skeleton_card()/skeleton_rows()        (forma del contenido)
show_empty_state      → empty_state(...)                        (con la acción que lo resuelve)
else                  → la lista/tabla
action_error != ""    → callout(action_error, "warn")           (ENCIMA de la lista, no la reemplaza)
```

La distinción `load_error` (tomato, reemplaza) vs `action_error` (amber, encima) es de producto: si la lista en pantalla sigue siendo verdad, no se la quita.

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
- **Español latino neutro, de tú.** "Conecta tu primera cuenta", no "Conecte su cuenta" ni "Conectá tu cuenta" (excepción: `vitrina_page` habla en voseo porque imita el registro del microcentro demo; se mantiene mientras sea demo).
- **Sentence case** en títulos, botones y cabeceras: "Cuentas conectadas", no "Cuentas Conectadas".
- Verbos concretos en botones: "Conectar cuenta", "Desconectar", "Publicar", "Sincronizar comentarios". Nunca "Enviar", "OK", "Aceptar" para acciones con consecuencia.
- Sin relleno ni disculpas: "No se pudo cargar la lista. Recarga la página o vuelve más tarde." — no "Lo sentimos, ha ocurrido un error inesperado".
- Nombrar por lo que el operador controla, no por cómo está construido: "cuenta conectada", no "social_connection"; "permiso de comentarios", no "instagram_manage_comments" (el scope técnico va en un `tag` como detalle, no como nombre).

### 7.2 Glosario (usar siempre la misma palabra)

| Concepto | Palabra en UI | No usar |
|---|---|---|
| tenant | **negocio** | tenant, cuenta, workspace, empresa |
| social_connection | **cuenta conectada** | conexión (salvo el título de la sección "Conexiones") |
| earned mention | **mención** | post, publicación ajena |
| own media a monitorear | **contenido** / **Reel** | inbox, media |
| DM/comentario recibido | **mensaje** / **comentario** | thread |
| lead | **lead** | prospecto, contacto |
| creator | **creador** | influencer (salvo copy de marketing) |
| señal derivada | **señal** | evento, alerta (alerta = una señal que exige acción) |
| Fecha de verificación | "Verificada: …" | "Last verified" |

### 7.3 Consistencia verbo → resultado
El botón dice "Publicar" → el estado dice "Publicando…" → el toast dice "Publicado". El botón dice "Desconectar" → el diálogo se titula "Desconectar cuenta" → el estado queda "Revocada" (nombre del estado, no del verbo — está bien que difieran ahí, porque describe la fila, no la acción).

### 7.4 Empty states
Título = el hecho, en presente ("Aún no conectas ninguna cuenta", "Todavía no hay leads"). Cuerpo = por qué importa + qué hacer, ≤ 2 frases. Si hay una acción que lo resuelve, es **el** botón `solid` de la página.

### 7.5 Errores
Qué pasó (en términos del operador) + qué hacer. Nunca el stack trace, nunca el código HTTP como único texto. Un mismo mensaje para todas las causas cuando la distinción no le sirve al operador (login: "Email o contraseña incorrectos." para todo — regla firmada, se conserva).

---

## 8. Accesibilidad (piso, no aspiración)

- **Contraste:** texto en pasos 11-12 sobre 1-3; `TEXT_FAINT` prohibido para texto informativo. Radix garantiza el ratio dentro de esas bandas en claro y oscuro.
- **No color-solo:** P1. Sentimiento, salud, plataforma: siempre palabra.
- **Foco visible:** `:focus-visible` outline 2px accent-8 en todo (`assets/qualify.css`).
- **Teclado:** todo lo interactivo es un botón/link/control Radix nativo (los diálogos atrapan foco y cierran con Esc). Un `rx.box` con `on_click` está prohibido: usa `rx.button variant="ghost"`.
- **Semántica:** un solo `h1` por página (`page_header`); `section`/`empty_state` emiten `h2`, títulos de entidad en tarjeta `h3`; las cifras y el wordmark son `rx.text`, no headings (Radix `Heading` es `h1` por defecto — pasar siempre `as_=`). El sidebar es `<nav aria-label="Secciones">` con `aria-current="page"`, el cuerpo es `<main>`; callouts de error `role="alert"`; skeletons `aria-busy`. Verificado en `/design`: 1 h1, 5 h2, `nav` y `main` presentes.
- **Tamaño de toque:** controles ≥ 32px de alto (Radix size 2); size 1 solo en contextos densos y secundarios.
- **Movimiento:** `prefers-reduced-motion` respetado.
- **Idioma:** `rx.App(html_lang="es")` — verificado en el `<html>` emitido.

---

## 9. Cómo extender

### 9.1 Checklist para una pantalla nueva
1. `app_shell(page_header(...), page_body(...))`. Sin `sidebar()` ni padding propio.
2. Ciclo de vida §6.1 con `callout`/`skeleton_*`/`empty_state`.
3. Colores solo vía `T.*` y tonos. Si necesitas un color que no existe, primero pregúntate si es un tono nuevo (raro) o un uso nuevo de uno existente (casi siempre).
4. Estados con `signal_pill`/`tone_badge`; identidad con `platform_badge`; etiquetas con `tag`.
5. Una sola acción `solid`. Verbos del glosario §7.2.
6. Cifras con `q-nums`; ids con `mono`.
6.b Movimiento sólo con `T.SPRING`/`T.EASE` y las tres duraciones; elevación sólo `ELEV_*`. Si una tarjeta no hace nada al pulsarla, no se levanta.
7. Ábrela en `/design` mentalmente: si tuviste que inventar una primitiva, añádela a `Qualify/ui/primitives.py`, muéstrala en `styleguide_page.py` y documéntala en §5.
8. `just lint` + `just test` (los tests puros no importan páginas; el compilador de Reflex es la prueba de que renderiza).

### 9.2 Cómo cambiar el sistema
- **Acento/gris/radio:** `rxconfig.py`. Un cambio.
- **Fuentes, gutter, radios en px, foco:** `assets/qualify.css`. Un cambio.
- **Mapeo tono → escala, plataforma → color:** `Qualify/ui/tokens.py`.
- **Una regla nueva de componente:** primitiva en `ui/primitives.py` + ejemplo en `/design` + fila en §5.
- Después de cualquier cambio: abrir `/design` en claro y oscuro.

### 9.3 Deuda conocida (ordenada)
1. **Sidebar en móvil**: el rail zen existe pero no se activa solo; falta colapsarlo automáticamente por debajo de 900px (y decidir si allí debe ser drawer en vez de rail).
2. **Verificación visual de páginas de negocio con sesión real**: `/design` y `/login` se verificaron en claro/oscuro y a 820px; las páginas tras `require_login` se verificaron por render de componentes (misma `app_shell`), no con una sesión Supabase viva.
3. `vitrina_page` conserva su `_CARD` dict y voseo (demo); si deja de ser demo, migrar a `card` y a la voz §7.1.
4. `clarity_page` usa `rx.card` de Radix en algunos bloques y `card` de Qualify en otros; unificar cuando se toque.
5. Toasts (`rx.toast`) — adoptados en `/inbox` (sincronizar comentarios, analizar sentimiento: un callout persistente se quedaba en pantalla indefinidamente) 2026-08-25; el resto de confirmaciones transitorias de la app (p. ej. "Publicado" en `/publish`, ver §7.3) siguen como callouts persistentes. Migrarlas según §5.4 cuando se toquen.
6. Fuentes desde Google Fonts: mover a `assets/fonts/` (self-host) antes del despliegue en `qualify.attitudefactory.co` si se quiere evitar la dependencia externa.

---

## 10. Decisiones y su porqué

### 10.1 Acento `teal`, gris `slate` (antes: `violet`, gris por defecto)
- Violeta era el acento por defecto del scaffold y hoy es el color genérico del "SaaS con IA"; además chocaba con `purple` (TikTok) y con `violet` (interés de lead), de modo que el acento no significaba nada.
- Teal está lejos de los tres tonos semánticos (grass/amber/tomato), del info (blue) y de las plataformas (pink/purple/blue), así que "acento = acción/marca" no compite con ningún otro significado.
- Slate es un gris frío que mantiene el verde semántico inequívoco (sage habría teñido de verde los neutros).
- Es un token: si el fundador decide otro color de marca (ver `docs/naming-dominios-exploracion.md`, sin identidad visual firmada), es una línea en `rxconfig.py`.

### 10.2 IBM Plex Sans + Plex Mono
- Necesitábamos una familia con mono hermano y buenos numerales tabulares: la UI está llena de `@handles`, ids, cifras y timestamps, y el producto es "señales y métricas". Plex resuelve las tres cosas con una sola familia y una sola decisión.
- Se descartó Inter (default de todo el mundo, sin mono hermano) y una display serif (no aporta a una consola operativa; sería decoración, P4).
- Coste: una dependencia externa a Google Fonts (§9.3-6).

### 10.3 Sin sombras
- Las tarjetas se distinguen por borde + fondo gray-2. La elevación (sombra) queda como señal exclusiva de "está flotando sobre la página" (diálogos, popovers, menús), lo que la hace informativa.

### 10.4 Primitivas mínimas, Radix directo para el resto
- Solo se envolvió lo que porta una regla Qualify (tono, variante-por-categoría, gutter, forma de estados). Envolver `rx.button` o `rx.input` sin regla habría creado una API paralela sin valor.

### 10.5 `/design` sin login y sin enlace en el sidebar
- No contiene datos de tenant y sirve a quien construye pantallas, no al operador. Estar fuera del sidebar evita confundirlo con producto.

### 10.7 Islas flotantes y muelle (propuesta C, elegida 2026-08-19)

Se prototiparon tres menús — dos planos con tinte, un ciclo numerado en tres etapas, e islas flotantes — y se eligió el tercero. Lo que se compró con esa elección, y por qué:

- **La separación la hace el aire, no una línea.** Un sidebar con reglas horizontales pide una jerarquía que este menú no tiene (ninguna zona manda sobre otra). Bloques separados por hueco agrupan igual de bien sin inventar orden.
- **El muelle es la firma.** El colapso del rail es el movimiento más frecuente de la app, así que es el que define cómo se siente: `cubic-bezier(.34,1.4,.5,1)` sobrepasa ligeramente y asienta. Se extiende a todo lo que cambia de tamaño o forma; lo demás se queda en `ease`.
- **La etiqueta se revela con máscara.** Un fundido dice «apareció»; una máscara dice «estaba ahí detrás del icono». Es más caro de percibir y más barato de ejecutar (`clip-path` sobre una sola propiedad).
- **La elevación gana significado al restringirla.** Al pasar de «superficies planas» (v1) a islas, la sombra dejaría de decir nada si todo la tuviera: por eso el reposo es una sola sombra baja y el ascenso al hover está reservado a `card(interactive=True)`.
- **Lo que se descartó:** la numeración de etapas de la propuesta B (enseña el método el primer día, estorba los demás) y su panel flotante al hover en zen — buena idea, pero pendiente hasta que el rail automático en móvil esté decidido, para no diseñar dos veces el mismo hueco.

### 10.6 Migración en el mismo cambio
- Un design system que solo existe en un doc y en una carpeta nueva no cambia nada. Se migraron las 8 páginas para que la próxima pantalla copie del código vigente, no del viejo.
