# UI — Brand Kit por pasos (`Qualify/creative_wizard_pages.py`)

**Estado:** `[EN CURSO]` — funcional y enrutado. El problema de layout que quedó abierto en la primera sesión está **resuelto en código y medido en navegador** (§6), pero falta la confirmación visual final por parte del fundador (§8).
**Fecha:** sesiones del 2026-09-02 al 2026-09-03.
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
| `Qualify/fixtures/midu.dev_prueba.json` | Fixture de perfil para el flujo "Ya tengo redes" — ver §4. |
| `Qualify/ui/layout.py` | **Compartido con toda la app.** `app_shell` y `page_body` cambiaron para que el panel sea el contenedor con scroll (§6). Tocarlo afecta a todas las pantallas, no solo a este wizard. |
| `assets/qualify.css` | **Compartido.** Reset de `margin`/`padding` en `html, body` (§6). Es la única hoja de estilos propia del proyecto, cargada globalmente desde `Qualify.py`. |

| Ruta | Componente | `on_load` |
|---|---|---|
| `/brand` | `brand_choice_index` | `AuthState.require_login` |
| `/brand/manual` | `brand_manual_index` | `+ CreativeState.load_brand/load_voice + BrandWizardState.resume` |
| `/brand/connect` | `brand_connect_index` | `+ CreativeState.load_brand/load_voice` (sin `resume` — ver §4) |

## 3. Flujo "Empezar de cero" — `/brand/manual`, 9 pasos

Estado: `BrandWizardState`. Cursor en `step: int`, `LAST_STEP = 8`.

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
| 9 | ¿Todo correcto? | `_step_confirm` | resumen de solo lectura de todo lo anterior |

**`BrandWizardState.resume`** (evento en `on_load`, corre último a propósito): recorre los pasos en orden y abre el flujo en el **primer** paso con datos faltantes, no en el último visitado. Dos pasos nunca cuentan como hueco: los sliders de tono (arrancan en 50) y las restricciones (opcionales). Si no queda ningún hueco, abre en la confirmación.

## 4. Flujo "Ya tengo redes" — `/brand/connect`, 11 pasos

Estado: `BrandConnectState`, **separado** de `BrandWizardState` a propósito — dos cursores, para que los dos puntos de entrada no compitan por el mismo `step`. Los pasos 5-11 de este flujo **son literalmente las mismas funciones** que los pasos 1-9 del manual (`_step_subscription`, `_step_identity`, `_step_palette`, `_step_voice_tone`, `_step_voice_examples`, `_step_restrictions`, `_step_confirm`), reutilizadas sin copiar — es la garantía de que los dos caminos no puedan divergir.

| # | Pantalla | Específico de este flujo |
|---|---|---|
| 1 | ¿Qué red usas? | Instagram / TikTok |
| 2 | ¿Cuál es tu usuario? | input; el botón dice "Analizar" |
| — | *(pantalla de carga)* | `_connect_loading` — spinner, `analyzing: bool` |
| 3 | Esto es lo que vemos | perfil leído: foto, usuario, nombre, seguidores, bio |
| 4 | Lo que te proponemos | 4 recomendaciones placeholder + Cancelar/Continuar |
| 5-11 | *(compartidos, ver arriba)* | — |

**El origen de los datos del perfil es un fixture, no un scraper real:** `PROFILE_FIXTURE = Qualify/fixtures/midu.dev_prueba.json`, leído por `BrandConnectState.analyze` vía `asyncio.to_thread`. El handler es `background=True` con un `yield` temprano para que el spinner pinte antes de leer el archivo; lleva un `sleep(1.2)` deliberado que **hay que quitar** cuando se conecte el análisis real. **No existe todavía ninguna conexión con `packages/scraper` ni con la ingesta first-party de Meta** — es puramente una demo de flujo.

`BrandConnectState.restart` (botón "Cancelar" en el paso 4) limpia todo lo leído y redirige a `/brand`.

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
6. **"Finalizar" redirige** — en ambos flujos, `on_click=[CreativeState.save_kit_form, rx.redirect("/brand")]`. Nota: redirige **incluso si el guardado falla** — condicionar el redirect al éxito exigiría tocar `creative_state.py`, que se dejó intacto a propósito.

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

## 9. Estado en git al cerrar la sesión

Todo **sin commitear**, en el worktree `claude/hola-9922e7` y copiado a mano al checkout principal `work/Qualify` (rama `feature/brand-kit-wizard`), que es el que corre el servidor. Ambas copias están sincronizadas y verificadas idénticas.

El commit `bdb19dc` (empujado a `origin`) contiene una versión **anterior** de `creative_wizard_pages.py`, previa a todo lo de §5 y §6. Archivos modificados sobre él:

| Archivo | Cambio |
|---|---|
| `Qualify/creative_wizard_pages.py` | flujo por pasos evolucionado + paleta de §5 + layout de §6 |
| `Qualify/ui/layout.py` | `app_shell` (panel = contenedor con scroll) y `page_body` (`flex`, y un `align_items` opcional aditivo) |
| `assets/qualify.css` | reset de `margin`/`padding` en `html, body` |

Falta un segundo commit para poner el PR al día. **Al hacerlo, los tres archivos van juntos** — ver la advertencia al final de §6.
