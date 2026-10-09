# Plan de migración al design system Liquid Glass (LiquidOS Studio 3.0)

`[v1 — 2026-10-08]` · Rama integradora: `claude/migrate-liquid-glass-design-f92e38` · Kit comprado: `reference/liquid-glass/` (vendorizado desde `new_branding/`) · Sistema actual: `Qualify/ui/`, `assets/qualify.css`, `docs/design-system.md`, ruta `/design`

> **Regla de la casa (sigue vigente):** el sistema vive en el código. Este plan dice *qué* se migra, *en qué orden* y *quién*; `Qualify/ui/` dirá *cómo* y `/design` lo demostrará. Cuando un lote termine, `docs/design-system.md` se corrige para que vuelva a describir el código.

---

## 0. Lo que pidió el fundador (2026-10-08)

1. Migrar el design system actual al kit **Liquid Glass UI Kit** (LiquidOS Studio 3.0, itch.io), **respetando nuestra paleta**.
2. Migrar **cada componente**. Si una pantalla usa algo que hoy no está en el design system, **ese algo también se migra** para tener una sola fuente de la verdad.
3. **NUNCA crear componentes nuevos.**
4. **SIEMPRE** enforzar el uso del design system; se pueden **modificar o mutar** nuestros componentes.
5. Trabajo **por lotes/dominios**, con varios equipos UX/UI + frontend **en paralelo**. Plan antes de empezar.
6. Primer encargo concreto: el efecto de `real-liquid-glass-os-effect.html` en **nuestro menú**. **Hecho** (§7).

**Cómo se interpretan 2 y 3 juntas** (regla operativa para todos los lotes): un *widget* que ya se usa en páginas pero sin regla Qualify (p. ej. `rx.button` ×184, `rx.select` ×70, `rx.table` ×92, `rx.segmented_control` ×34 llamados directamente) **pasa a tener su regla y su skin en el sistema** — eso es migración, no creación. Lo que no existe ni en nuestras pantallas ni en el kit **no se crea**. Una primitiva nueva en `Qualify/ui/primitives.py` solo se admite si (a) ya hay ≥ 2 pantallas repitiendo esa receta a mano y (b) el kit la trae; si no se cumplen ambas, se usa Radix directo con el skin global.

---

## 1. Qué es el kit (hechos, medidos en `reference/liquid-glass/`)

| Pieza | Tamaño | Qué trae | ¿Se usa? |
|---|---|---|---|
| `LiquidOS-Studio-v3.0/assets/css/liquidos.css` | 19 KB | **El design system real:** tokens `--lq-*` (bg, text, accent, accent-2, success/warning/danger, glass-rgb/alpha, blur, saturation, border-alpha, radius sm/md/lg, shadow, ease, ease-spring, duration, control-height); materiales `.lq-glass` + `--clear / --frosted / --liquid / --tint / --light`; componentes `lq-panel`, `lq-button` (`--primary/--danger/--ghost/--pill`, `lq-icon-button`, `lq-ripple`), `lq-field/select/textarea/label/field-wrap`, `lq-switch`, `lq-segmented`, `lq-check/radio`, `lq-range`, `lq-progress`, `lq-badge/tag` (`--success/--warning/--danger`), `lq-avatar(-stack)`, `lq-spinner`, `lq-skeleton`, `lq-table(-wrap)`, `lq-toast(-region)`, `lq-dialog` (+ header/body/footer), `lq-tooltip`, `lq-reveal`, `lq-tilt`; reduced-motion y 320 px | **Sí** — fuente del material y de los tokens |
| `assets/js/liquidos.js` | 18 KB | iconos SVG inline, ripple, sheen que sigue el puntero en `.lq-glass--liquid`, tilt, reveal (IntersectionObserver), tabs, `<dialog>` nativo, toast, copy | **Parcial** — solo lo delegado al documento (ripple, sheen). Tabs/dialog/toast/reveal NO: Radix, Sonner y React ya lo resuelven y mezclarlos rompería foco/estado |
| `assets/css/studio.css`, `demos/demo.css`, `demos/demo.js`, `index.html`, 17 demos | ~230 KB | el Studio (builder, catálogo) y las demos (admin, login, trading…) | **No** en código. Referencia visual para los equipos UX/UI (el *admin dashboard* y el *login* son las más cercanas a Qualify) |
| `adapters/tailwind-liquid-glass.cjs` | 2 KB | plugin Tailwind | **No** (no usamos Tailwind) |
| `real-liquid-glass-os-effect.html` | 23 KB | dock con cápsula de vidrio que se desliza entre ítems, deformación direccional, etiqueta flotante con cuello | **Sí** — migrado al sidebar (§7) |

Tres propiedades del kit que condicionan todo lo demás:

- **Es dark-first.** `:root { color-scheme: dark; --lq-bg: #070a12 }`; el modo claro es un modificador (`.lq-glass--light`), no un tema. Nosotros tenemos claro y oscuro (Radix) y los dos siguen.
- **Su paleta no es la nuestra.** Acento violeta `#8b7cff` + cian `#51d7ff`, Inter. Se sustituye por teal/slate (§3 D2) y se mantiene Plex (D4). El kit vale por el **material** (vidrio, relieve, brillo, movimiento), no por sus colores.
- **No tiene build.** CSS + JS planos: se vendoriza tal cual en `assets/` y **no se edita**; todo ajuste va en nuestro puente (`assets/qualify.css`). Sin licencia dentro del zip: guardar el recibo de itch.io; repo privado.

---

## 2. Qué tenemos (inventario medido el 2026-10-08)

**Sistema:** `Qualify/ui/tokens.py` (194 líneas), `layout.py` (594), `primitives.py` (668, 22 primitivas), `assets/qualify.css` (2.000 líneas; ~60 % son bloques por dominio: planner, drafts, contenido, deck, ranking), `rxconfig.py` (tema teal/slate/medium), `styleguide_page.py` (877, ruta `/design`).

**Uso de primitivas propias en páginas:** `callout` 93 · `card` 72 · `tone_badge` 27 · `page_header` 19 · `tag` 18 · `page_body` 18 · `app_shell` 17 · `section` 16 · `empty_state` 14 · `stat_card` 13 · `mono` 13 · `progress_panel` 11 · `signal_pill` 8 · `kv` 8 · `sentiment_badge` 7 · `removable_pill` 7 · `platform_badge` 6 · `loading_spinner` 6 · `skeleton_card` 5 · `skeleton_rows` 4 · `stepper` 3 · `drawer` 3 · `pill_editor` 1 · `demo_notice` 1.

**Radix llamado directo desde páginas (lo que §0 obliga a traer al sistema):** `rx.button` 184 · `rx.table` 92 · `rx.select` 70 · `rx.toast` 50 · `rx.input` 48 · `rx.badge` 48 · `rx.segmented_control` 34 · `rx.divider` 27 · `rx.callout` 19 · `rx.alert_dialog` 19 · `rx.spinner` 17 · `rx.text_area` 15 · `rx.popover` 13 · `rx.icon_button` 13 · `rx.dropdown_menu` 13 · `rx.skeleton` 10 · `rx.accordion` 9 · `rx.tooltip` 8 · `rx.switch` 5 · `rx.card` 5 · `rx.checkbox` 4 · `rx.hover_card` 3 · `rx.slider` 2 · `rx.progress` 2 · `rx.tabs` 1 · `rx.scroll_area` 1.

**Estilo inline fuera del sistema (`rx.color(` / `background=` / `border=` / `box_shadow=` por módulo):** `creative_wizard_pages` 60 (+32 colores hex) · `planner_page` 40 · `vitrina_page` 18 · `creative_pages` 16 · `content_generator` 15 · `post_card` 11 · `publishing_page` 8 · `stories_page` 8 · `inbox_page` 7 · `brand_kit_editor` 7 · `planner_drawer` 6 · `trending_panel` 6 · `catalog_page` 6 · `voice_lab` 5 · `brand_documents` 3 · `connections_page` 1. Los `*_state.py` con `background=` son datos de estado (colores de campaña, etc.), no estilo: fuera del alcance.

**Pruebas:** 1.193 tests offline en `Qualify/` (verdes tras el lote 0 parcial), lint `ruff` limpio en 918 archivos.

---

## 3. Decisiones de diseño

Las marcadas ⚑ necesitan OK del fundador antes del lote 0 completo; el resto son recomendaciones del equipo y se aplican salvo objeción.

| # | Decisión | Por qué |
|---|---|---|
| D1 | **Radix sigue dando el comportamiento; el kit da el material.** No se sustituyen componentes React por el HTML del kit. Se re-skinea vía CSS (selectores `.rt-*` de Radix + nuestras clases `q-*`) y las primitivas `ui.*` emiten las clases. | Reescribir 184 botones / 70 selects / 19 diálogos con HTML plano rompería eventos y estado de Reflex, el focus trap, Esc, el autocompletado del login (fallo firmado §6.1) y la a11y que ya tenemos. El kit mismo documenta que su valor es el material (`lq-glass`), no sus controles. |
| D2 | **Puente de tokens, no edición del kit — y `liquidos.css` NO se carga en runtime** (enmienda 2026-10-08 al ejecutar el lote 0). El kit queda vendorizado en `reference/liquid-glass/` como fuente para diffs; `assets/qualify.css` declara sus tokens con sus propios nombres (`--lq-*` → Radix: `--lq-accent → var(--accent-9)`, `--lq-accent-2 → var(--accent-8)`, `--lq-success/warning/danger → grass/amber/tomato-9`, `--lq-text* → gray-12/11/9`, `--lq-bg → var(--color-background)`, radios 12/20/dial, curvas, sombras por tema) y los `--q-*` leen de ellos (radios, elevación, movimiento). Cada componente del kit se redibuja sobre el selector Radix que lo renderiza («Liquid Glass: Radix skin»). Paleta confirmada por el fundador: **teal / slate**, tinte = acento. | Cargar `liquidos.css` tal cual era dañino: sus resets de `:root`/`body`/`button`/`a` son dark-only (fondo `#070a12`, Inter, foco cian) y pelearían con Radix, y sus reglas `.lq-*` apuntan a marcado que Reflex nunca emite. «Respetando la paleta»: un solo lugar para cambiar de color sigue siendo `rxconfig.py`. |
| D10 | **CSS por dominio — hecho:** `qualify.css` (tokens, puente, skin, shell, primitivas, chips compartidos) + `qualify-planner.css` + `qualify-brand.css` + `qualify-publish.css` + `qualify-inbox.css` (vacío hasta el lote D), registrados en ese orden en `rx.App(stylesheets=…)`. Movimiento de bloques enteros, sin editar reglas. | Cinco equipos en paralelo no pueden compartir un archivo de 2.000 líneas sin conflictos. Cada equipo es dueño de su archivo. |
| D3 | **Claro y oscuro siguen los dos.** El material claro se define con nuestras variables (ya hecho para el menú: `--q-glass-*` por tema en `qualify.css`). ⚑ ¿Oscuro como modo por defecto? Hoy es «sistema». Recomendación: dejar «sistema» — el kit luce mejor en oscuro, pero el operador entra entre tareas a plena luz. | El kit es dark-first; forzar oscuro sería renunciar a la mitad de los usos. |
| D4 | ⚑ **Tipografía: mantener IBM Plex Sans + Plex Mono** (decisión 10.2 del DS). El kit trae Inter por defecto, pero no es parte de su valor. | Plex da mono hermano y numerales tabulares; el producto es cifras y `@handles`. |
| D5 | **Material por rol, por rendimiento.** `island` (sidebar, drawer, dialog, popover/dropdown, toast, header sticky) = vidrio con `backdrop-filter`; `card` (tarjetas dentro del panel) = translúcido con relieve, **sin blur** (o ≤ 8 px); `control` (botón, campo, badge) = sin blur, solo relieve/inset del kit. **Nunca blur en grids** (tiles del planificador, galería de borradores, catálogo). Tope: ≤ 8 superficies con `backdrop-filter` por pantalla. | `backdrop-filter` se paga por elemento y por píxel; 72 `card` y las grids de tiles en vidrio pleno se arrastrarían en portátiles y móviles. |
| D6 | ⚑ **El panel principal queda opaco** (`--color-panel-solid`), con el suelo *mesh* asomando por los bordes; vidrio solo en el header sticky de la página. Patrón macOS: sidebar translúcido, contenido opaco. Alternativa: panel de vidrio frosted (más fiel al kit, menos legible con tablas y texto denso). | Legibilidad de tablas y formularios; una tabla de 50 filas sobre vidrio es ruido. |
| D7 | **Movimiento:** `--q-spring := --lq-ease-spring`, `--q-ease := --lq-ease`, `--q-dur := --lq-duration` escalado. Dos curvas siguen siendo dos curvas (P8). | Un cambio en tokens y todo el sistema (zen, lift, drawer, stepper) adopta la firma del kit. |
| D8 | **JS del kit:** se carga `liquidos.js` **no**. Se portan a `assets/` solo ripple y sheen por puntero (delegados al documento, como `glass-nav.js`), con guard `window.__q*`. Tabs/dialog/toast/reveal del kit quedan fuera (D1). | Dos sistemas de diálogos y de toasts en la misma app = foco y a11y rotos. |
| D9 | **Enforcement = test estático.** `Qualify/test_design_system_guard.py` (mismo patrón que `packages/shared/tests/test_object_store_sanctity.py`): en `Qualify/*.py` fuera de `ui/` prohíbe colores hex, `rx.color(` (solo `T.*`), `box_shadow=` / `backdrop_filter=` / `background=` con valores que no sean `T.*`, y `color_scheme="<escala>"` crudo (solo `T.tone_scheme`/`T.platform_scale`). Lista de archivos cubiertos que crece lote a lote; CI lo corre (`just test`). | «SIEMPRE enforzar»: una regla que no falla en CI no es una regla. |
| D11 | **Scripts del navegador** se cargan con `rx.el.script(src=…, async_=True)` dentro del componente que los necesita, no con `head_components`. | Medido 2026-10-08: `head_components` pasa por react-helmet y **no inyecta nada** en el build de desarrollo (afecta a `deck-drag.js`, `rank-drag.js` y al atajo ⌘.). Tarea abierta aparte. |
| D12 | **Skeleton = carga de contenido, SIEMPRE; spinner = trabajo en curso** (fundador, 2026-10-08). Skeleton para lo que se está *leyendo* y va a aparecer (listas, detalles, catálogo, calendario); spinner (`loading_spinner`, nunca `rx.spinner`) para lo que se está *haciendo* (scraping, generación, sync, publicación). Enforzado por `Qualify/test_design_system_guard.py`. **Hecho.** | Un spinner sobre una lista vacía no dice nada; un skeleton con la forma del contenido sí. Y un skeleton sobre un scraping engañaría: ahí no hay "forma" todavía, hay trabajo. |
| D14 | **El material lo definen los diales del Glass Lab, uno por token** (`--q-lab-*` en `assets/qualify.css`; refracción y frecuencia en el filtro SVG `#q-refraction` que renderiza `app_shell`). Valores del fundador (2026-10-08): Liquid · Noir · blur 0 px · opacidad 9 % · saturación 120 % · radio 32 px · edge 34 % · refracción 21 · frecuencia 9 · profundidad 100 % · tinte = acento (teal). Las fórmulas son las del Lab (`app.js` → `builderCss`), no una aproximación; el tema claro conserva la estructura con un blanco más lechoso. Para probar otro material: mover los diales en el Lab y copiar los números. **Hecho.** | Un design system con un «builder» pero sin registro de qué se eligió no es reproducible. Los diales son el contrato entre UX y código. |
| D13 | **El calendario del planificador se conserva** (semanal por horas, estilo Google Calendar); el del kit es un selector de mes de un solo día y no sirve. Lo que migra es la **piel**: cuadrícula, celdas y chips sobre el material *card* del sistema (lote C). | Fundador, 2026-10-08: «nuestro calendario debe seguir el glass card de fondo, guiarse del design system». |

---

## 4. Lotes y equipos

Cada equipo de lote = **1 UX/UI** (revisa contra el kit y contra `docs/design-system.md`, aprueba capturas claro/oscuro/móvil) + **1 frontend Reflex** (el lote E lleva 2). Archivos **disjuntos** por lote; la fundación es el único punto de contacto y por eso va primero y sola.

### Lote 0 — Fundación (1 equipo, secuencial; bloquea a todos) — EN CURSO

Hecho: el menú (§7). Pendiente, en este orden:

1. Vendorizar `liquidos.css` en `assets/liquidos.css` y registrarlo en `rx.App(stylesheets=[…])` antes de `qualify.css`; puente de tokens (D2, D7); material claro/oscuro por rol (D3, D5) como variables `--q-glass-*` / `--q-card-*` / `--q-control-*`.
2. Mutar primitivas para que emitan el material (nunca APIs nuevas): `card` (rol *card*, `interactive` = lift del kit), `stat_card`, `signal_pill` / `tone_badge` / `tag` / `platform_badge` / `removable_pill` (relieve `lq-badge`, tono por `T.*`), `callout`, `empty_state`, `skeleton_card` / `skeleton_rows` (shimmer `lq-skeleton`), `loading_spinner` (anillo `lq-spinner` con nuestro gris), `progress_panel` (`lq-progress`), `drawer` (material *island* + `lq-dialog` header/body/footer), `stepper`, `demo_notice`, `kv`, `mono`.
3. Layout: `page_header` sticky con material *island*; `page_body` y `section` sin cambio de API; `app_shell` ya lleva el suelo.
4. Re-skin global de Radix (CSS sobre `.rt-*`): `Button` (solid = `lq-button--primary` con gradiente teal 9→8; soft/outline/ghost = `lq-button` base/ghost), `IconButton`, `TextField` / `Select` / `TextArea` (`lq-field`), `Switch`, `SegmentedControl` (`lq-segmented`; sustituye a `.q-flow-switch`), `Checkbox` / `Radio`, `Table` (`lq-table`), `Tooltip`, `Popover` / `DropdownMenu` / `HoverCard` (*island*), `Dialog` / `AlertDialog` (`lq-dialog`), Sonner toast (`lq-toast`), `Accordion`, `Tabs`, `Badge`, `Callout`, `Skeleton`, `Progress`, `Slider` (`lq-range`), `Separator`.
5. D8: portar ripple + sheen a `assets/glass-fx.js`.
6. D10: partir `qualify.css` por dominio (mover bloques, sin cambiar reglas).
7. D9: `test_design_system_guard.py` con la lista inicial = `Qualify/ui/*` + `styleguide_page.py` + `auth_pages.py` + `components.py`.
8. `/design` actualizado (cada primitiva y cada skin visible, claro y oscuro) y `docs/design-system.md` v3 (§3 tokens, §5 componentes, §10 decisiones D1–D11).

**Salida:** `/design` verde en claro y oscuro a 1440 / 820 / 375 px; 1.193+ tests; `just ci-lint`; capturas en el PR. Hasta aquí **ninguna página de negocio cambia de código** — solo cambia de aspecto por el skin global.

### Lotes 1–5 — Dominios (en paralelo, cada uno su rama `claude/lg-<letra>` desde la rama integradora)

| Lote | Dominio | Archivos (dueño exclusivo) | CSS propio | Tamaño |
|---|---|---|---|---|
| **A** | Shell, auth y escucha | `auth_pages.py`, `components.py` (menciones), `connections_page.py`, `leads_page.py`, `signals_page.py`, `clarity_page.py` (unificar `rx.card` → `card`, deuda 9.3-4), `vitrina_page.py` (retirar `_CARD` dict, deuda 9.3-3), `canva_pages.py` | ninguno | M |
| **B** | Publicar y catálogo | `publishing_page.py`, `stories_page.py`, `trending_panel.py`, `post_card.py`, `publish_tips.py`, `catalog_page.py` | `qualify-publish.css` | M |
| **C** | Planificador | `planner_page.py`, `planner_drawer.py` + bloques QUA-108/118 v2 de `qualify.css` | `qualify-planner.css` | L |
| **D** | Contenido / inbox | `inbox_page.py` + bloque «Contenido» (filtros, tiles) | `qualify-inbox.css` | M |
| **E** | Brand Kit y creativo (2 frontends) | `creative_pages.py`, `creative_wizard_pages.py` (7.771 líneas, 60 inline + 32 hex), `brand_kit_editor.py`, `brand_finish.py`, `brand_documents.py`, `voice_lab.py`, `content_generator.py`, `creator_discovery.py`, `referentes_review.py`, `hashtag_catalog.py` + bloques deck/ranking de `qualify.css` | `qualify-brand.css` | XL |

**Trabajo de cada lote (igual para todos):**

1. Sustituir todo estilo inline por `ui.*` / `T.*` / clases del sistema; cero hex, cero `rx.color(` directo.
2. Lo que repita una receta a mano se resuelve con la primitiva existente (mutada en lote 0), nunca con una nueva (§0).
3. Aplicar D5: inventario de `backdrop-filter` por pantalla ≤ 8.
4. Añadir sus archivos al guard (D9) y dejarlo verde.
5. Capturas claro / oscuro / 375 px de cada ruta en el PR; revisión UX/UI contra el kit.
6. Tests del dominio verdes (`just test`), `just ci-lint`.

### Lote 6 — QA transversal (1 equipo, al final)

Recorrido de **todas** las rutas (`Qualify/Qualify.py` registra 24) en claro/oscuro/móvil; a11y (contraste ≥ 4,5:1 sobre vidrio claro, foco visible, un `h1`); rendimiento (conteo de `backdrop-filter`, FPS del drawer y del zen); guard en todo `Qualify/`; `docs/design-system.md` final; PR a `main` con `just merge`.

---

## 5. Orden, ramas y gate

```
Lote 0 (fundación) ──► A ─┐
                     ──► B ─┤
                     ──► C ─┼──► Lote 6 (QA) ──► PR a main (just merge, CI verde)
                     ──► D ─┤
                     ──► E ─┘
```

- Rama integradora: `claude/migrate-liquid-glass-design-f92e38`. Lote 0 aterriza ahí directamente; cada dominio abre `claude/lg-<letra>` desde ella y vuelve por PR a la integradora.
- Nada va a `main` hasta el lote 6. CI red = no merge (regla del fundador, `just merge`).
- Equipos: agentes `reflex-ui-engineer` (frontend) con un revisor UX/UI por lote (skill `design:design-critique` sobre las capturas); el lote 0 lo cierra un solo equipo para que haya una sola mano en tokens y primitivas.

---

## 6. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `backdrop-filter` caro (Safari, móviles) | D5 (material por rol) + tope por pantalla medido en lote 6 |
| Contraste de texto sobre vidrio claro | relleno claro al 74 % (`--q-glass-fill`) y verificación 4,5:1 en lote 6 |
| React re-renderiza el sidebar y pisa nodos añadidos por JS | ya mitigado en `glass-nav.js` (MutationObserver filtrado, re-settle, guard) |
| `head_components` muertos (react-helmet) | D11; tarea abierta para `deck-drag.js` / `rank-drag.js` / ⌘. |
| `uv.lock` pide reflex 0.9.12 y el venv compartido tiene 0.9.7 | no sincronizar en worktrees (trampa documentada); decidir el upgrade fuera de esta migración |
| Kit sin licencia en el zip | guardar el recibo de itch.io; repo privado; no publicar las demos |
| Cinco equipos tocando `qualify.css` | D10 (un CSS por dominio) |

---

## 7. Hecho en este primer paso (lote 0 — el menú)

Efecto de `real-liquid-glass-os-effect.html` adaptado del dock horizontal a nuestras islas verticales:

- **Suelo** (`.q-ground`, `app_shell`): malla suave de los dos colores de zona (teal = Escuchas, iris = Publicas) sobre `--color-background` + rayas diagonales muy tenues, para que el vidrio tenga algo que refractar.
- **Islas** (`.q-island`, `_island`): relleno translúcido en degradado + `backdrop-filter: blur(24px) saturate(145%)` + brillo interior en el borde superior + sheen diagonal; el tinte de zona pasa a ser un lavado alfa **debajo** del vidrio (`zone_tint` → alfa 3, `zone_line` → alfa 6). Material distinto por tema (`--q-glass-*` en `.radix-themes` y en `.dark`).
- **Cápsula** (`.q-glass-blob`, `assets/glass-nav.js`): una por isla, dentro de ella (obligado por el stacking context del `backdrop-filter`). Reposa en la fila activa (`aria-current="page"`), vuela a la fila bajo el puntero con la coreografía del dock (palabra fuera → vidrio a los 40 ms → palabra nueva a los 235 ms), se deforma en la dirección del viaje (`skewY` ±2,5°, estirón y asentamiento), el icono de la fila se levanta 1 px. Al cambiar de isla, la anterior se apaga y la nueva entra deslizándose por el borde por el que llega. Teclado (focus) igual que puntero. Sin script: fallback plano (`.q-sidebar:not([data-glass])`).
- **Etiqueta zen** (`.q-glass-label`): en modo zen, el nombre aparece al lado del rail como una segunda pieza de vidrio con cuello, creciendo desde un desenfoque; sustituye al tooltip `::after` anterior, que el `overflow: hidden` de la fila recortaba y nunca se veía. Solo con puntero fino.
- **Carga del script:** `rx.el.script(src="/glass-nav.js", async_=True)` dentro de `sidebar()` (D11).
- **Verificado** en `/design` (sin login): oscuro y claro, expandido y zen, cambio de ruta (el nav se remonta y la cápsula se asienta sola), `reduced-motion`; 1.193 tests verdes; `ruff` limpio.

Archivos: `assets/qualify.css` (sección «Liquid glass menu»), `assets/glass-nav.js` (nuevo), `Qualify/ui/layout.py`, `Qualify/ui/tokens.py`, `Qualify/Qualify.py`, `.gitignore` (`.venv` como enlace), `reference/liquid-glass/` (kit vendorizado), este documento.
