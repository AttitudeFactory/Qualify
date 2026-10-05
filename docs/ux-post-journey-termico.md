# UX — El recorrido del POST y su temperatura

**Fecha:** 2026-10-05 · **Estado:** `[PROPUESTA UX + PROTOTIPO — el mapeo y las animaciones están en código (/design → «Temperatura del POST»); ninguna pantalla de negocio lo usa todavía; pide decisiones del fundador (§4.3) y dos contratos con el arquitecto (§5)]`
**Autor:** reflex-ui-engineer · **Alcance:** solo UI/UX de `Qualify/` (Reflex). No toca `packages/`.
**Continúa:** [ux-plantillas-en-el-post.md](ux-plantillas-en-el-post.md) (el POST primero, sus 7 preguntas abiertas siguen abiertas). **Asume:** [plan-mvp-plantillas-remotion.md](plan-mvp-plantillas-remotion.md) §1–§4, [design-system.md](design-system.md) (tonos, `signal_pill`/`tone_badge`, `DUR`/`EASE`, §9.1), la FSM del POST (`packages/api/src/qualify_api/creative/fsm.py`), `PostCategory`/`ReuseType` (`packages/creative/src/qualify_creative/enums.py`), el Planificador (`Qualify/planner_page.py`, `planner_vm.py`) y el Brand Kit (`Qualify/brand_kit_editor.py`, [ui-brandkit-wizard.md](ui-brandkit-wizard.md)).
**Código del prototipo:** `Qualify/ui/thermal.py` (mapeo + badge), `Qualify/ui/lottie.py` (Lottie en Reflex), `Qualify/ui/lottie_shapes.py` → `assets/lottie/*.json` (seis animaciones propias), sección «Temperatura del POST» en `Qualify/styleguide_page.py`, tests `Qualify/test_thermal_vm.py` y `Qualify/test_lottie_assets.py`.

> **La preocupación del fundador, textual:** «Me sigue preocupando el UX/UI del post, el path desde el brand kit hasta que se congela el post y se publica o reúsa. Me gustaría animaciones para el post como caliente hasta que se enfría con animaciones Lottie.»
>
> **La respuesta corta.** El camino existe entero en la app, pero el usuario lo recorre con **tres vocabularios de estado distintos** (el del borrador, el del evento del calendario y el de aprobación del Planificador) y con **cinco iconos** que no se parecen entre sí. La temperatura resuelve eso si es **un solo badge** en todas las pantallas, derivado de los estados reales (no un estado nuevo en la base de datos), con tonos del design system (caliente = `warn`, frío = `info`, entregado = `ok`) y una animación sólo donde pasa algo: mientras se cocina, al congelar, al publicar. Lottie entra a costo cero con `lottie-react` (MIT) y seis archivos propios de 1,7–7 KB generados por código. Lo que la temperatura **no** puede resolver sola está en §5: un POST aprobado puede publicarse hoy varias veces por el calendario, pero el draft no sabe si es recurrente o promocional (`reuse_type` llega siempre `None`), así que «frío reutilizable» y «archivado» son hoy indistinguibles.

---

## 1. El recorrido de punta a punta, pantalla por pantalla

El usuario real: el dueño de Bianki (shawarma) o Polette (helado de yogurt), con el teléfono, al mediodía, con dos fotos recién tomadas. Cada fila dice qué ve, qué decide, dónde está hoy en la app y qué falta o sobra.

```
 Brand Kit        Productos         Crear post            Revisar               CONGELAR           Programar           Publicar            Reusar / Archivar
 (una vez)        (fotos reales)    (producto + ángulo    (paquete: Reel ·      (aprobar = deja    (Planificador:      (ejecutor QUA-111   (recurrente: vuelve
                                     → receta → generar)   feed · historia;      de cambiar)        un evento por        a su hora)          a programarse;
                                                           editar · regenerar)                      salida, MP-11)                          promocional: una vez)
 ────────────── ─────────────── ───────────────────── ───────────────────── ───────────────── ─────────────────── ─────────────────── ────────────────────
 /brand/kit      /catalog         /create               /drafts/{id}          /drafts/{id}       /planner             (sin pantalla)      (sin pantalla)
 Negocio         Negocio          Publicas              Publicas              botón Aprobar      «Sin programar»      estado del evento   —
 ENCENDIDO ←──────────────────── CALIENTE ──────────── HUMEANTE ──────────── CONGELADO ───────── PROGRAMADO ───────── PUBLICADO ────────── FRÍO REUTILIZABLE
                                                            ↑                     │                                                        ARCHIVADO
                                                            └───── descongelar ───┘
```

| # | Pantalla | Qué ve el usuario | Qué decide | Dónde está hoy | Qué falta / qué sobra |
|---|---|---|---|---|---|
| 0 | **Brand Kit** (una vez) | Dos flujos guiados (manual 9 pasos, «ya tengo redes»): identidad, logo, paleta, voz, ejemplos, restricciones, resultados | Quién es la marca y cómo suena | `/brand/kit` (`brand_kit_editor.py`, `creative_wizard_pages.py`), bajo *Negocio* | Nada que cambiar para este recorrido. Sobra: no tiene por qué mostrar temperatura; el kit no es un POST |
| 1 | **Productos** (fotos reales) | Tarjetas de producto con foto principal, precio, categoría; editor con zona de subida (fotos y clips, normalizados al subir) | Qué producto existe y con qué fotos | `/catalog` (`catalog_page.py`), bajo *Negocio* | Falta la acción **«Crear post»** desde la tarjeta y desde el editor tras subir fotos (ya pedido en [ux-plantillas-en-el-post.md](ux-plantillas-en-el-post.md) §3.3, pantalla 0). Sobra: estar bajo *Negocio*: cada semana empieza aquí, debería abrir *Publicas* |
| 2 | **Crear post** | Hoy: wizard de 7 pasos («¿Qué quieres crear?» primero, «Con plantilla» como quinta tarjeta, formato preguntado a un tipo que produce tres). Propuesto: 3 pantallas (producto + ángulo → receta cotizada → recap) | Producto, ángulo, receta (con su costo) | `/create` (`content_generator.py`, `creative_state.py`) | Falta reordenar según [ux-plantillas-en-el-post.md](ux-plantillas-en-el-post.md) §3.3. **Temperatura:** la pantalla de recap es el único lugar donde el POST está **Encendido** (hay brief, no hay fila); al pulsar Generar pasa a **Caliente** |
| 3 | **Tu paquete / Revisar** | Las salidas según llegan (Reel 9:16 · Feed 4:5 · Historia 9:16), variantes de copy, editor de copy, «Rechazar · Rechazar y regenerar · Aprobar y descargar» | Qué variante, si se edita, si se aprueba | `_template_result` en `/create`; `/drafts/{id}` (`creative_pages.py`) | Falta el estado **por salida** en pantalla (el backend ya lo deriva, la vista omite la que no llegó); falta «Regenerar con otra receta». **Temperatura:** **Caliente** mientras corre (con progreso por salida), **Humeante** cuando está generado. Editar en Humeante no cambia la temperatura (la FSM lo confirma: `generated --edit--> generated`) |
| 4 | **Congelar** (aprobar) | El botón «Aprobar y descargar» (hoy) → «Aprobar paquete» / **«Congelar»** | Que la pieza deje de cambiar | `_decision_bar` en `/drafts/{id}`; FSM `generated --approve--> approved` con guard `selected_variant_id` | El concepto ya existe en la FSM y en el copy («Aprobar fija la variante elegida como el texto aprobado del POST»): sólo le falta **nombre y gesto**. Es el momento de la única animación «de celebración» del flujo. Editar un POST congelado **lo descongela**: la FSM manda `approved --edit--> generated` (revisión nueva, re-aprobar). Eso ya está decidido en código (2026-09-30); la UI sólo tiene que decirlo con el verbo correcto |
| 5 | **Programar** | «Sin programar»: una tarjeta por POST aprobado (miniatura, categoría, pill de aprobación) → «Asignar» → día, hora, cuenta → un `calendar_event` | Cuándo y en qué cuenta | `/planner` (`planner_page.py`, `planner_state.py`); evento `scheduled` | Falta programar **por salida** (contrato §3.5 (1)-(2) del doc anterior; MP-11 en curso). **Temperatura:** **Programado** = Congelado con fecha; un evento vencido o cancelado devuelve el POST a Congelado |
| 6 | **Publicar** | Nada que hacer: el ejecutor QUA-111 publica a su hora; el evento pasa `scheduled → publishing → published` (o `failed`) | — | Worker embebido en el backend (`planner/embedded.py`) + `publishable.py`; `/publish` es el camino manual («tengo el archivo») y no conoce borradores | **Temperatura:** **En camino** mientras el evento está `publishing` o el draft `staged`; **Publicado** al confirmar. Un fallo del evento no es un fallo del POST, pero el usuario lo ve igual: **Fallido** con el motivo y «Reintentar» |
| 7 | **Reusar / Archivar** | Hoy: nada. El POST publicado desaparece de «Sin programar» y se queda en `/drafts` como «Publicado» | Si vuelve al calendario (recurrente) o se retira (promocional) | `ReuseType` existe en `enums.py` (`recurrente`/`promocional`) y en `PostSummary.reuse_type`, pero `draft_post_reader` devuelve siempre `None` («the draft model has no such concept — QUA-109») | **Falta el dato** (§5). Con él: recurrente → **Frío reutilizable** (vuelve a «Sin programar» con el icono de repetir); promocional → **Archivado** (sale de «Sin programar», se queda en `/drafts` bajo un filtro «Archivados», con «Duplicar» para hacer uno nuevo a partir de él) |

**Conclusión del recorrido:** las siete pantallas existen; lo que falta no son pantallas sino (a) tres cambios de entrada ya propuestos (Productos en *Publicas*, «Crear post» desde el producto, wizard de 3 pasos), (b) el estado por salida en Revisar y Programar (MP-11), y (c) **un solo vocabulario de estado** de principio a fin, que es lo que este documento propone.

### 1.1 Los tres vocabularios que hoy conviven (el problema concreto)

| Dónde | Vocabulario | Tonos que usa | Icono |
|---|---|---|---|
| `/drafts` y `/drafts/{id}` (`creative_vm.STATUS_LABELS/TONES`, `creative_pages.status_badge`) | Generando · Listo para revisar · Aprobado · Rechazado · Preparado en Meta · Publicado · Fallido | **nombres Radix sueltos** (`blue`, `amber`, `grass`, `gray`, `iris`, `tomato`) — contra P7 del design system | `rx.spinner` / `eye` / `circle-check` / `clock` / `circle-x` / `triangle-alert` |
| `/planner` tarjeta «Sin programar» (`planner_vm._APPROVAL_LABEL`) | Aprobado · Pendiente de aprobación · Rechazado · En producción | tonos (`ok`/`warn`/`error`/`neutral`) | punto de `signal_pill` |
| `/planner` evento (`planner_vm._STATUS_LABEL`) | Programado · Cancelado · Publicando · Publicado · Falló · Venció | tonos (`info`/`neutral`/`ok`/`error`/`warn`) | punto; `triangle-alert` ámbar en el chip |

El mismo POST aprobado se llama «Aprobado» (grass) en `/drafts`, «Aprobado» (ok) en la tarjeta del Planificador y «Programado» (info) en el calendario; el mismo POST generando es «Generando» con spinner en un sitio y «En producción» neutro en otro. La temperatura no agrega un cuarto vocabulario: **reemplaza a los tres** con una función pura sobre los estados reales.

---

## 2. La metáfora térmica como sistema de estados

### 2.1 La escala (propuesta del fundador, discutida y ajustada)

Regla de diseño: la temperatura es **un badge** (`thermal_badge`) con la anatomía de `signal_pill` — tono + glifo + palabra — idéntico en lista, tarjeta y detalle. Cambia el tamaño y si el glifo se anima; nunca el icono ni el tono.

**Lectura térmica de los tonos (la decisión de color):** el lado **caliente es `warn`** (ámbar: hay algo temporal que te va a pedir atención), el lado **frío es `info`** (azul: está en el sistema, nada que hacer), **entregado es `ok`** (grass), lo apagado/encendido/archivado es `neutral`, y **Fallido es `error`** — nunca «caliente», porque tomate significa fallo en todo el producto (P1) y un POST generando no es un incendio. Dos colores para dos temperaturas; el glifo dice en qué paso del lado estás. Esto **desvía en un punto** del `design-system.md` §3.1 («`info` = en curso»): aquí «en curso» (Caliente) es `warn`, porque va a necesitar al operador en un minuto, y `info` se reserva para lo que ya no lo necesita. Propuesta de enmienda a §3.1: `warn` «atención, temporal, **en caliente**»; `info` «informativo, **en espera, en frío**».

| Temperatura | Clave | Estado real que la produce | Tono | Glifo estático (lucide) | Animación (archivo, loop) | Verbo del usuario | Qué significa |
|---|---|---|---|---|---|---|---|
| **Encendido** | `lit` | brief armado en `/create`, sin fila (`status` vacío) | `neutral` | `zap` | — | **Generar** | Está listo para cocinarse; aún no existe |
| **Caliente** | `hot` | `drafting` | `warn` | `flame` | `flame.json`, loop 1 s | Esperar | Copy y salidas en curso; progreso por salida |
| **Humeante** | `steaming` | `generated` | `warn` | `wind` | `steam.json`, loop 2 s | **Revisar y congelar** | Generado; se puede editar (sigue humeante) o regenerar (vuelve a caliente) |
| **Apagado** *(añadido)* | `off` | `rejected` | `neutral` | `circle-slash` | — | Recalentar | Rechazado; nada pasa hasta regenerar |
| **Congelado** | `frozen` | `approved` sin evento | `info` | `snowflake` | `freeze.json`, una vez 0,8 s (al entrar) · `thaw.json` (al salir editando) | **Programar** | Aprobado: inmutable. Editar = descongelar → Humeante con revisión nueva |
| **Programado** | `scheduled` | `approved` + evento `scheduled` | `info` | `clock` | `scheduled.json`, una vez 1 s | Esperar la hora · Reprogramar | Congelado con fecha; se publica solo |
| **En camino** *(añadido)* | `publishing` | `staged`, o evento `publishing` | `info` | `send` | — (spinner `sm` en línea si hace falta) | Esperar | Contenedor creado en Meta / el worker lo está publicando |
| **Publicado** | `published` | `published` (sin tipo de reúso) | `ok` | `circle-check` | `published.json`, una vez 0,8 s | Ver en Instagram | Ya está en la cuenta |
| **Frío reutilizable** | `reusable` | `published` + `recurrente`; o `approved` + `recurrente` ya publicado ≥ 1 vez | `info` | `repeat` | `freeze.json` (al volver a congelarse) | **Volver a programar** | El mismo POST frío, listo para otra fecha |
| **Archivado** | `archived` | `published` + `promocional` | `neutral` | `archive` | — | Duplicar | Se usó una vez; se retira. Duplicar crea un POST nuevo (Encendido) a partir de él |
| **Fallido** | `failed` | `failed`, o evento `failed` | `error` | `triangle-alert` | **nunca** | Reintentar (según `FailureReason`) | Un error no es un espectáculo |

Dos ajustes a la propuesta de partida, y por qué:

1. **Apagado** (rechazado) y **En camino** (`staged`/`publishing`) no estaban en la lista y **son estados reales de la FSM y del evento**: no se pueden esconder sin mentir. Apagado es honesto con la metáfora (se apagó el fuego; regenerar lo recalienta). En camino es el único tramo donde el usuario no puede hacer nada y conviene decírselo.
2. **Frío reutilizable es Congelado con un marcador**, no un estado aparte en la base de datos: un POST recurrente nunca «se gasta»; lo que se publica es su **evento**. Por eso la tarjeta del Planificador de un recurrente dice «Publicado 3 veces · próxima lun 12:00» y el POST sigue azul. Eso exige que el ejecutor **no** mueva el draft a `published` cuando el POST es recurrente, o que lo mueva y el reúso lo devuelva a `approved` — §5 (2).

Lo que **no** se añade: una temperatura para «venció sin aprobación» o «evento cancelado»: ambos devuelven al POST a Congelado y la nota (`EXPIRED_NOTE`, tono `warn`) va **debajo** del badge, no dentro.

### 2.2 Transiciones permitidas y qué animación las acompaña

Derivadas de las aristas reales de `fsm._TRANSITIONS` + el ciclo del evento + la regla de reúso. `Qualify/test_thermal_vm.py` pina que **cada arista de la FSM cae en una transición permitida de la tabla** (así la tabla no puede desviarse del backend); una transición no listada es un bug de UI, no una animación que falta (`transition()` lanza `KeyError`).

| De → A | Disparador real | Animación | Cómo se ve |
|---|---|---|---|
| Encendido → Caliente | Generar | **ignite** | La llama se enciende (`flame.json` desde el fotograma 0, luego loop) |
| Caliente → Humeante | `generate_ok` | **cool** | Fundido llama → vapor (CSS, `DUR`); el badge pasa a «Humeante» sin cambiar de tono |
| Caliente → Fallido | `generate_fail` / `reap` | — | Cambio de badge (ámbar → tomate con `.q-thermal`, `DUR`) + callout con el motivo |
| Humeante → Humeante | `edit` | — | Nada: editar no cambia la temperatura |
| Humeante → **Congelado** | `approve` (**Congelar**) | **freeze** | `freeze.json` una vez en el badge del detalle: el copo cristaliza desde el centro; el tono pasa ámbar → azul con `EASE`. El único momento «de celebración» del flujo antes de publicar |
| Humeante → Apagado | `reject` | — | Cambio de badge a gris |
| Apagado → Caliente | `regenerate` (Recalentar) | **ignite** | Como Encendido → Caliente |
| **Congelado → Humeante** | `edit` (**Descongelar**) | **thaw** | `thaw.json` (el copo se derrite) y el vapor entra con un fundido retrasado 0,7 s (`.q-thermal-after`); el tono vuelve a ámbar |
| Congelado → Programado | Asignar en el Planificador | **tick** | `scheduled.json` una vez: el minutero da la vuelta |
| Congelado → En camino | `stage` / Publicar ahora | — | Cambio de badge |
| Congelado → Publicado | `publish_ok` directo (sin `stage`) | **deliver** | `published.json` una vez (anillo y check se dibujan) |
| Programado → Congelado | evento cancelado / vencido | — | Cambio de badge; nota «Venció…» debajo |
| Programado → En camino / Publicado / Fallido | el worker (QUA-111) | — / **deliver** / — | Publicado dibuja el check; Fallido nunca se anima |
| En camino → Publicado | `publish_ok` | **deliver** | Igual |
| En camino → Congelado | `stage_expired` | — | Cambio de badge |
| Publicado → Frío reutilizable / Archivado | automático por `reuse_type` | — | Al recargar: el badge ya es el otro |
| Frío reutilizable → Programado | Asignar de nuevo | **tick** | Igual que Congelado → Programado |
| Frío reutilizable → Humeante | `edit` | **thaw** | Igual que Congelado → Humeante (revisión nueva, re-aprobar) |
| Archivado → Encendido | Duplicar | — | Es una fila nueva en `/create` |
| Fallido → Caliente | Reintentar / regenerar | **ignite** | Igual |

Reglas de movimiento (extienden P8 y §8 del design system):

- **Loop sólo donde algo está pasando ahora** (Caliente, Humeante) y **a lo sumo un loop por pantalla**. Los demás archivos se reproducen **una vez** en el momento del cambio y quedan en su último fotograma (el copo entero, el check dibujado).
- **Un error nunca se anima.** Fallido es el único estado sin archivo.
- **El cambio de tono se funde** (`.q-thermal`: `background-color`/`color` con `DUR` y `EASE`): el ojo lee *un* badge cambiando, no un badge reemplazado por otro.
- `prefers-reduced-motion`: cada animación va acompañada en el DOM de su gemelo estático (el icono lucide del tono); el CSS muestra uno u otro. Sin JS, sin parpadeo, y la palabra no cambia.

### 2.3 Dónde se ve cada cosa (lista, tarjeta del Planificador, detalle)

| Superficie | Qué muestra | Animado |
|---|---|---|
| `/drafts` (tabla) | `thermal_badge(state)` en la columna Estado, en vez de `status_badge` | **No** (glifo estático). Una tabla con veinte llamas es una estufa, no una lista |
| `/drafts/{id}` cabecera | `thermal_badge(state, animate=True, size="2")` junto al título | **Sí**: loop en Caliente/Humeante; una vez al entrar a Congelado/Publicado |
| `/drafts/{id}` momento de Congelar/Descongelar | `thermal_glyph(FROZEN)` grande (4 rem) encima de la barra de decisión durante la transición, luego desaparece | **Sí**, una vez |
| «Tu paquete» (resultado de `/create`) | badge animado Caliente con **progreso por salida** debajo (`signal_pill` «Renderizando…/Lista/Falló» por salida); al terminar, badge Humeante | **Sí** (es la espera) |
| `/planner` «Sin programar» | `thermal_badge(state)` reemplaza la pill de aprobación; en recurrentes, «Publicado N veces» como meta | **No** |
| `/planner` chip del calendario | sin badge (el chip es mínimo); el icono térmico pequeño reemplaza al `triangle-alert` suelto sólo cuando el estado lo pide | **No** |
| `/planner` diálogo de detalle del evento | `thermal_badge(state, size="2")` | **No** |

---

## 3. Lottie en Reflex, a costo cero

### 3.1 La librería (verificado 2026-10-05)

| | `lottie-react` 3.1.2 | `@lottiefiles/dotlottie-react` 0.19.16 |
|---|---|---|
| Licencia | MIT (verificado en el `package.json` instalado) | MIT |
| Motor | `lottie-web` 5.13.0 (MIT, JS puro, render SVG/canvas/html) | `@lottiefiles/dotlottie-web` 0.80.0 — **WebAssembly** (el `.wasm` se carga aparte; `unpackedSize` 7,4 MB) |
| Formato | JSON (`src` = ruta, URL u objeto) | `.lottie` (zip) y JSON |
| Peso de lo que el navegador carga | wrapper ~1,4 KB + motor **light** `lottie_light.min.js` 168 KB raw / **46,7 KB gzip** (sin expresiones, sólo SVG — basta para formas simples); el motor completo serían 306 KB / 76,7 KB gzip | wrapper + ~1 MB de `.wasm` |
| Exportaciones (del `build/index.d.ts` instalado) | `Lottie` (motor completo), `LottieSvg`, **`LottieLight`**, hooks `useLottie*`, `LottieControls`, `lottieInView` | `DotLottieReact` |
| Props que usamos | `src`, `loop` (bool o nº de repeticiones), `autoplay`, `speed`, `direction`, `segment`, `className`/`style` en el `div` que dibuja | `src`, `loop`, `autoplay`, `dotLottieRefCallback` |
| React | peer `^18.2 \|\| ^19` — Reflex 0.9.7 trae React 19.2.6 | `^17 \|\| ^18 \|\| ^19` |

**Elegida: `lottie-react` → `LottieLight`.** Razones: sin WASM ni carga externa, 47 KB gzip, SVG (los trazos se ven nítidos a 12 px en un badge y se escalan a 4 rem sin cambiar de archivo), y expone exactamente los controles que el sistema necesita (`loop`, `autoplay`, `speed`). `dotLottie` gana cuando hay decenas de animaciones pesadas de LottieFiles (el `.lottie` comprime ~10×); aquí los seis archivos pesan 22 KB en total, 1,4 KB gzip. Nota de honestidad: en modo desarrollo Vite pre-empaqueta el paquete entero (1,4 MB sin minificar, 284 KB gzip, con los tres motores) — eso es el *dev server*, no lo que se despliega; en `reflex export` el *tree-shaking* deja `LottieLight` + `lottie_light`.

### 3.2 Cómo se envuelve en Reflex (`Qualify/ui/lottie.py`)

```python
class LottieLight(rx.NoSSRComponent):
    library = "lottie-react@3.1.2"          # pin, como pide la guía de wrapping de Reflex
    lib_dependencies: list[str] = ["lottie-web@5.13.0"]
    tag = "LottieLight"                      # named export → is_default = False
    src: rx.Var[str]; loop: rx.Var[bool]; autoplay: rx.Var[bool]
    speed: rx.Var[float]; direction: rx.Var[str]
```

- `NoSSRComponent` (verificado en `reflex_base.components.component`): el motor entra como `ClientSide(() => import("lottie-react").then(mod => mod.LottieLight))`, es decir **carga diferida**: la página que no muestra ninguna animación no descarga el motor; `/design` sí lo hace (`GET /node_modules/.vite/deps/lottie-react.js` aparece sólo al montar el primer badge animado).
- La dependencia npm se declara **en el componente** (`library` + `lib_dependencies`); nadie corre `bun add`. `reflex run` la instaló sola al compilar.
- Los archivos viven en `assets/lottie/` y Reflex los sirve en `/lottie/<nombre>.json` (igual que `/qualify.css`).
- `lottie(src, *, loop, autoplay, size, reduced_motion_fallback, tone)` devuelve **dos nodos**: la animación (`.q-lottie`, `aria-hidden`) y su gemelo estático (`.q-lottie-static`, un icono lucide del tono). `assets/qualify.css` muestra uno u otro según `prefers-reduced-motion`.
- **Hallazgo que vale el precio del prototipo:** una reproducción **en reversa** por `autoplay` no funciona en este motor: `lottie-react` carga la animación en el fotograma 0 y sólo después llama `setDirection(-1)`, así que ya «terminó» antes de dibujar; y `initialSegment` con rango descendente no dibuja nada (medido en el DOM: `d=""` en todos los paths). Por eso **el deshielo es un archivo propio** (`thaw.json`), que el generador produce invirtiendo en el tiempo las keyframes de `freeze.json`. Regla: lo que deba verse al revés se entrega como archivo, no como truco del motor.

### 3.3 De dónde salen los assets

**Propios, generados por código** (`Qualify/ui/lottie_shapes.py` → `python -m Qualify.ui.lottie_shapes`). Un Lottie de formas es un JSON con capas `ty: 4`, grupos de formas (`el`, `rc`, `sh`), relleno/trazo (`fl`/`st`), *trim paths* (`tm`, lo que «dibuja» un trazo) y keyframes `{"t","s","i","o"}`. El generador es legible (qué se mueve, cuánto dura, en qué tono); el JSON no. `test_lottie_assets.py` pina que lo commiteado es byte a byte la salida del generador, que cada archivo ≤ 50 KB, que sólo hay capas de formas, sin assets externos ni expresiones, y que **cada color es el paso 9 de la escala de un tono** (`#ffc53d` amber, `#0090ff` blue, `#46a758` grass — idénticos en claro y oscuro en `@radix-ui/colors`, verificado; `slate` no lo es, por eso los estados neutros no se animan).

| Archivo | Qué es | Peso |
|---|---|---|
| `flame.json` | Caliente — una gota que respira (escala 100→91/108→100, ±4° de vaivén) con una lengua interior desfasada; loop 1 s sin costura | 1,7 KB |
| `steam.json` | Humeante — tres hilos en S que suben y se desvanecen, desfasados un tercio de ciclo (rotación de keyframes con costura invisible a opacidad 0); loop 2 s | 3,1 KB |
| `freeze.json` | Congelar — tres brazos trazados desde el centro (trim 50→0 / 50→100), seis ticks, núcleo, escala 60→106→100 con sobrepaso y rotación −30→0; una vez, 0,8 s | 6,7 KB |
| `thaw.json` | Descongelar — `freeze` invertido en el tiempo por el generador; una vez, 0,8 s | 7,0 KB |
| `scheduled.json` | Programado — esfera, minutero que da una vuelta, horario que avanza 30°; una vez, 1 s | 2,0 KB |
| `published.json` | Publicado — anillo trazado 0→100, luego el check, y un pop 100→108→100; una vez, 0,8 s | 1,8 KB |

Total: 22,3 KB raw, 1,4 KB gzip. Licencias: `assets/lottie/LICENSES.md` (todo propio; si un día entra un asset de LottieFiles, va a esa tabla con autor, enlace y la Lottie Simple License — verificada: uso comercial y modificación permitidos, atribución opcional pero recomendada, prohibido compilar archivos para un servicio competidor).

### 3.4 Accesibilidad y presupuesto

- `prefers-reduced-motion` → icono estático, no un fotograma congelado (que puede ser el frame 0 vacío). El `@media` global del design system ya corta transiciones; esto añade el *swap* de nodo.
- `aria-hidden` en animación y gemelo; la palabra del badge es lo que leen los lectores.
- Una animación ≤ 50 KB (las nuestras ≤ 7); carga diferida del motor; a lo sumo **un loop por pantalla**; nada que compita con la lectura (las animaciones viven en el badge o en el momento del cambio, nunca al lado de un texto largo).
- Pendiente («después»): pausar el loop cuando el badge sale del viewport (`lottieInView` de la propia librería) — hoy un loop fuera de pantalla sigue consumiendo un `requestAnimationFrame`.

### 3.5 Dónde SÍ y dónde NO

| Sí | No |
|---|---|
| El cambio de estado en el detalle (congelar, descongelar, publicar) | Listas largas y tablas (`/drafts`, calendario): glifo estático |
| La espera que bloquea (Caliente en «Tu paquete», con progreso por salida) | Tarjetas de «Sin programar» (veinte tarjetas, veinte loops) |
| La cabecera de `/drafts/{id}` (un loop como mucho) | Toasts, callouts, botones |
| `/design` (la escala completa, para quien construye pantallas) | Fallido — jamás |

---

## 4. Cambios de UI y preguntas

### 4.1 Esta semana (antes de la demo del domingo 11)

| Archivo / pantalla | Cambio | Depende de |
|---|---|---|
| `Qualify/ui/thermal.py`, `ui/lottie.py`, `ui/lottie_shapes.py`, `assets/lottie/`, `/design` | **Hecho en este PR**: mapeo, badge, glifo, seis animaciones, demo Congelar/Descongelar, tests | — |
| `Qualify/creative_vm.py` | `DraftSummaryVM`/`DraftVM` ganan `thermal: str` (= `thermal_for(status, reuse_type=…, event_status=…)`); **retirar `STATUS_TONES` con nombres Radix sueltos** (viola P7) | lectura del evento del POST (`planner_provider` ya sabe qué POST tiene evento; exponerlo al draft es una consulta, sin migración) |
| `Qualify/creative_pages.py` | `status_badge` → `thermal_badge(draft.thermal)` en la tabla; cabecera del detalle con `animate=True`; «Aprobar y descargar» → **«Congelar»** (en POST con plantilla: «Congelar paquete»); al editar un congelado, el texto de ayuda dice «Editar lo descongela: vuelve a revisión y hay que congelarlo de nuevo» (la FSM ya lo hace; hoy la UI no lo dice) | fundador P1 (§4.3) |
| `Qualify/planner_page.py` + `planner_vm.py` | La pill de aprobación de «Sin programar» → `thermal_badge`; el diálogo de detalle también. `_APPROVAL_LABEL` y `_STATUS_LABEL` se quedan como fuente de **notas** (venció, cancelado), no de badge | — |
| `Qualify/content_generator.py` («Tu paquete») | Badge Caliente animado + `signal_pill` por salida; al terminar, Humeante y el botón «Revisar y congelar» | estado por salida en `DraftVM.outputs` (ya propuesto; pipeline S) |
| `docs/design-system.md` §3.1 | Enmienda de la lectura térmica de `warn`/`info` (§2.1) | fundador P3 |

### 4.2 Después (semana 2+)

| Pantalla | Cambio |
|---|---|
| `/drafts` | Filtro por temperatura (Humeantes = «por revisar», Congelados = «por programar», Archivados); el filtro **es** la bandeja de trabajo del dueño |
| `/planner` «Sin programar» | Los recurrentes vuelven solos tras publicarse, con «Publicado N veces · última …»; los promocionales desaparecen. Un atajo «Repetir la semana que viene» en un recurrente publicado |
| `/drafts/{id}` | «Duplicar» en Archivado → `/create` con producto, ángulo y receta precargados (Encendido) |
| `/catalog` pestaña «Contenido» | Los POST del producto con su temperatura (vista C del doc anterior) |
| Movimiento | `lottieInView` para pausar loops fuera de pantalla; `thermal_glyph` en el toast de «Publicado» |
| Campañas | La temperatura por POST se agrega al grupo: «4 congelados · 1 humeante» |

### 4.3 Preguntas para el fundador

1. **Descongelar.** Editar un POST congelado crea una revisión nueva y exige volver a congelar (re-aprobar) — así está en la FSM desde el 2026-09-30 (`approved --edit--> generated`). ¿Confirmas que ese es el comportamiento que quieres, o un cambio «menor» (una tilde en el copy) debería poder hacerse sin descongelar? Recomendación: **siempre descongela**; lo que se publicó fue lo aprobado, y una tilde también es un cambio.
2. **Dónde vive el frío reutilizable.** ¿En el Planificador («Sin programar», con el marcador de repetir, es lo que el dueño programa cada semana) o en Productos (ficha del producto → pestaña Contenido)? Recomendación: **en el Planificador**, y en Productos como vista secundaria en semana 2. Lo que no conviene es un tercer sitio («Biblioteca»).
3. **Lado caliente = ámbar.** Un POST generando se ve ámbar (`warn`), no azul (`info`), aunque el design system dice «en curso = info». ¿De acuerdo con la lectura térmica (§2.1)? Alternativa: Caliente azul («llama de gas») y Humeante ámbar — más fiel al libro, menos legible como temperatura.
4. **Recurrente: ¿cuántas veces y hasta cuándo?** `ReuseType.RECURRENTE` dice «varias veces, el mismo día de la semana». ¿El POST se reprograma a mano cada semana (recomendado para empezar) o lleva una regla («todos los viernes 12:00 hasta el 30/11») que el Planificador expande en eventos? Lo segundo es una campaña de un solo POST; conviene decidirlo con el lote de la semana 2.
5. **Archivado.** ¿Un promocional publicado se archiva solo (recomendado) o el dueño lo archiva? Y ¿«Duplicar» copia también la receta y las fotos, o sólo producto + ángulo?
6. **Nombre del botón.** «Congelar» en vez de «Aprobar» en toda la UI, o «Aprobar» con el badge que dice «Congelado». Recomendación: **«Congelar»** (verbo del glosario, §7.3 del design system: el botón dice Congelar → el estado dice Congelado), con «aprobar» sólo en el texto de ayuda la primera vez.
7. **¿Animación al publicar en el toast?** Hoy «Publicado» en `/publish` es un callout. Si entra el check animado, es en el toast (semana 2), no en la lista.

---

## 5. Lo que este doc no decide (contratos para el arquitecto)

1. **`reuse_type` en el draft.** `PostSummary.reuse_type` existe pero `draft_post_reader` lo devuelve `None`: el draft no tiene la columna. Sin ella no hay Frío reutilizable ni Archivado. Pide una columna `reuse_type` en `content_drafts` (enum `recurrente`/`promocional`, nullable = «sin decidir» → Publicado a secas) y una pregunta en «¿Todo listo?» del generador (dos chips: «Se repite» / «Una vez»), con `recurrente` por defecto para producto/precio/menú y `promocional` para promoción/temporada/agotado (derivado de `ContentType`, cambiable).
2. **Qué hace el ejecutor con el draft de un recurrente.** Hoy `publish_ok` lleva el draft a `published` (terminal). Un recurrente publicado tres veces no puede ser `published` tres veces. Dos salidas: (a) el ejecutor **no** aplica `PUBLISH_OK` al draft cuando el POST es recurrente — el draft queda `approved` y la publicación vive en el evento (recomendada: el POST «es» un activo frío, el evento es lo que se publica); (b) el draft va a `published` y el reúso lo devuelve a `approved` con una arista nueva `published --reuse--> approved`. `thermal_for` acepta las dos (`approved` + `recurrente` + `publish_count ≥ 1` y `published` + `recurrente` dan ambos Frío reutilizable), así que la UI no bloquea la decisión.
3. **El evento en el draft.** Para pintar Programado/En camino/Fallido en `/drafts` el VM del draft necesita el estado de su evento más próximo (`calendar_events` por `post_id`). Es una lectura; conviene exponerla en el mismo provider que hoy sirve a `/planner`.
4. **Estado por salida** (MP-11): sigue siendo el contrato de [ux-plantillas-en-el-post.md](ux-plantillas-en-el-post.md) §3.5. La temperatura es del POST; el progreso por salida va debajo, no sustituye al badge.

**Qué está medido y qué no.** Lo verificado: el componente compila (`reflex compile --dry`), `/design` carga las seis animaciones sin errores de consola propios (el único error es el `UNSAFE_componentWillMount` de `react-helmet` que Reflex ya tenía), el motor entra como chunk diferido, Congelar y Descongelar reproducen `freeze.json`/`thaw.json` y el vapor vuelve con el fundido; 1.072 tests de `Qualify/` en verde con los 54 nuevos. Lo no verificado: cómo se ve en un teléfono real a 60 fps (el panel de pruebas limita `requestAnimationFrame` a 1 Hz, así que las capturas muestran fotogramas, no movimiento) y el peso real del bundle tras `reflex export`.
