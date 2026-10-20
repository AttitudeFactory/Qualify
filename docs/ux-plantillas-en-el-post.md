# UX — Dónde vive el motor de plantillas dentro del flujo del POST

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Fecha:** 2026-10-05 · **Estado:** `[PROPUESTA UX — sin implementar; pide una decisión del fundador y un contrato con el arquitecto]`
**Autor:** reflex-ui-engineer · **Alcance:** solo UI/UX del `Qualify/` (Reflex). No toca `packages/`.
**Contexto que asume:** [plan-mvp-plantillas-remotion.md](plan-mvp-plantillas-remotion.md) (§1, §2.1, §3, §4), [backlog-motor-plantillas-remotion.md](backlog-motor-plantillas-remotion.md) §4.1, [diseno-motor-contenido-marca.md](diseno-motor-contenido-marca.md) §6, [design-system.md](design-system.md) §4.2, §7.2 y §9.1, y el código del worktree al cierre del día 1 (`Qualify/content_generator.py`, `creative_state.py`, `catalog_page.py`, `planner_page.py`, `publishing_page.py`, `ui/layout.py`).

> **La pregunta:** hoy «Con plantilla» es un **tipo de pieza** más dentro del wizard de `/create`, a la par del guion, los avatares y la imagen publicitaria, con un paso «Receta» propio y un `/catalog` aparte bajo *Negocio*. ¿Es la colocación correcta, o el modelo del Post (producto + ángulo + libreto + brand kit + assets → paquete de salidas) pide otra cosa?
>
> **La respuesta corta:** no es la colocación correcta, y el síntoma más claro no está en el wizard sino al final del flujo: **un paquete de tres salidas no puede llegar hoy a Instagram por el Planificador** (§1.3). La recomendación (§3) es poner el Post primero — producto + ángulo como primera pantalla, la plantilla como camino por defecto, los demás tipos como recetas del router — y hacer que el paquete sea un Post con N salidas que se programan **por salida**, no un draft con una preview.

---

## 1. El flujo actual, tal cual está

### 1.1 Rutas y sidebar

| Isla del sidebar | Entrada | Ruta | Qué hace hoy |
|---|---|---|---|
| **Publicas** | Crear pieza | `/create` | El generador como wizard (`content_generator.generator_page`) |
| **Publicas** | Borradores | `/drafts`, `/drafts/{id}` | Bandeja (tabla) y revisión HITL #2 |
| **Publicas** | Planificador | `/planner` | Calendario semanal; panel «Sin programar» con los POST aprobados; «Asignar» → día, hora, cuenta |
| **Publicas** | Publicar | `/publish` | Subida manual (Publicaciones \| Stories). **No lee borradores**: es el camino «tengo el archivo en el teléfono» |
| **Negocio** (pie) | Brand Kit | `/brand/kit` | Identidad, se configura una vez |
| **Negocio** (pie) | Catálogo | `/catalog` | Productos con precio, descripción y fotos/videos reales; CRUD; sin acción «crear pieza» desde el producto |

### 1.2 El wizard de `/create` para «Con plantilla» (7 pasos + resultado)

```
 1 ¿Qué quieres crear?      5 tarjetas: Guion · Avatar humano · Avatar animado · Imagen publicitaria · Con plantilla
 2 ¿Qué anuncias?           [solo plantilla] selector de producto del catálogo (opcional) + tema libre (obligatorio) + objetivo
 3 ¿Dónde se publica?       «De qué trata» (el ángulo: promoción, combo, precio…) · destino (orgánico/anuncio) · formato
 4 Tus fotos                las del catálogo ya cuentan; subida de fotos extra
 5 Lo que debe decir y evitar   debe mencionar / debe evitar
 6 ¿Cómo la hacemos?        [solo plantilla] 3 recetas cotizadas (Remotion / HeyGen / UGC), la sugerida marcada
 7 ¿Todo listo?             recap → Generar
 ▸ Tu paquete               grid con las salidas según van saliendo (Reel 9:16 · Feed 4:5 · Historia 9:16) + texto del post
                            → «Revisar y aprobar en Borradores»
```

Observaciones de uso (teléfono, fotos recién tomadas):

- El paso 1 obliga a **elegir herramienta antes de decir qué comunicar**, que es exactamente lo que el fundador decidió evitar («el usuario no elige plantilla, elige qué comunicar; el router sugiere la receta»). «Con plantilla» es además la **quinta** tarjeta.
- El paso 3 pregunta **formato** a un tipo que produce los tres formatos a la vez; la pregunta no tiene respuesta correcta para la plantilla. Y el **ángulo** («De qué trata»), que es lo que cambia el prompt y por tanto el copy, está escondido en un `select` del paso 3, detrás del tema libre.
- El producto del catálogo es **opcional** y el tema libre **obligatorio**: al revés de lo que el modelo pide (el producto trae las fotos, el precio y el nombre; el tema libre es la nota que afina).
- Siete pantallas para una decisión real (qué producto, qué ángulo) y una confirmación (qué receta). El Brand Kit justifica su wizard de 9 pasos porque se hace una vez; esto se hace tres veces por semana.

### 1.3 Después de generar: dónde se rompe el paquete

| Pantalla | Qué muestra hoy de un paquete | Problema |
|---|---|---|
| `/drafts` (tabla) | Tema · Estado · Creado. **Sin miniatura, sin formato, sin producto, sin salidas** | No se distingue un paquete de un guion, ni cuál salida falló |
| `/drafts/{id}` | Columna de medios con las tres salidas etiquetadas por puerto (`Reel 9:16`, `Feed 4:5`, `Historia 9:16`), cada una con descarga; variantes de copy; barra «Rechazar · Rechazar y regenerar · Aprobar y descargar» | La aprobación es **del draft entero**; el estado por salida existe en el backend (`image_assets.output_port`, estado derivado del job) pero la pantalla no lo muestra |
| `/planner` → «Sin programar» | Una tarjeta por POST con **una** miniatura y **una** categoría (`tag(post.category_label)`); «Asignar» → un `calendar_event` con día, hora y cuenta | Un POST tiene **una** `category` (`galeria` / `story` / `reel`) y el evento publica **todos** sus medios |
| Ejecutor QUA-111 (`planner/publishable.py`) | `media_product_type_for(category, media_types)`: `reel` exige **un solo video**; `story` exige **un solo video** («el publicador no tiene story de imagen»); `galeria` 1 imagen o 2–10 mixtos | **Un paquete = `category=reel` + 1 video + 2 imágenes → `UNSUPPORTED_SHAPE`.** No es publicable. Con `category=galeria` se publicaría como **carrusel de tres** (el Reel como slide de galería), que no es lo que se quiere. Y aun separando las salidas, **la historia 9:16 del paquete es una imagen fija y el publicador solo sabe publicar stories de video** |
| `/publish` | Subida manual de archivos + caption | No conoce los borradores; el único modo de sacar hoy una salida del paquete por `/publish` es descargarla y volverla a subir a mano |

**Conclusión del estado actual:** el día 1 cableó el paquete hasta el borrador (bien), pero del borrador en adelante el producto sigue pensando en «un draft = una preview = un formato = una publicación». El cambio de colocación del feature tiene que arreglar eso o el domingo 11 la demo termina en «descargar y subir a mano».

---

## 2. Alternativas de colocación

| | **A — Como está** (plantilla = un tipo más) | **B — El Post primero** (producto + ángulo primero; plantilla por defecto; los demás tipos son recetas) | **C — El catálogo como hub** (el contenido vive dentro del producto, a lo ElevenCreative) |
|---|---|---|---|
| Primera pantalla | «¿Qué quieres crear?» (5 tipos) | «¿Qué anuncias?» (producto del catálogo + ángulo) | La ficha del producto; «Crear paquete» desde ahí; `/create` no existe como entrada propia |
| Dónde está el catálogo | *Negocio* (ajuste, junto al Brand Kit) | *Publicas*, **primer** ítem («Productos»): es el inicio del flujo de publicar | Es la página principal de *Publicas*; borradores y campañas se ven **por producto** |
| Cómo se llega a los otros tipos | Tarjetas del paso 1 | Como recetas en «¿Cómo la hacemos?» (Remotion sugerida; HeyGen / guion / UGC como alternativas con su costo). Un atajo «Otra cosa (sin producto)» para piezas sin producto: horarios, fidelidad, ubicación | Solo desde el producto; una pieza sin producto no tiene casa |
| Paquete en borrador / lista / Planificador | Un draft, una preview, una categoría (roto, §1.3) | Un Post con N salidas; lista con chips por salida; Planificador programa **por salida** | Igual que B, pero visto desde el producto («este shawarma tiene 4 paquetes, 2 programados») |
| Cotización | Paso 6 del wizard | Paso 2 de 3, antes de generar; además «Regenerar con otra receta» desde el borrador | Igual que B |
| Campaña (producto × ángulos × fechas) | No encaja: el wizard es por pieza | Encaja: la pantalla 1 acepta N productos × N ángulos (semana 2) y produce N posts con `campaign_id` | Encaja mejor aún (multi-selección en la grilla del catálogo), pero la campaña cruzada de varios productos vive mal dentro de un producto |
| Móvil con fotos recién tomadas | 7 pantallas + decidir tipo antes de ver el producto | Subir fotos al producto → «Crear post» → 3 pantallas | El camino más corto (fotos y post en la misma ficha), pero obliga a crear el producto antes de la primera pieza |
| Costo de implementación esta semana | 0 | Medio en UI (reordenar wizard, lista, detalle, sidebar); **un contrato nuevo** en el Planificador (evento por salida) | Alto: nueva IA de navegación (producto como contenedor de drafts), reescritura de `/drafts` |
| Riesgo | La demo del domingo termina en descarga manual; el feature queda como «otro generador» | Que el paso «¿Cómo la hacemos?» absorba los avatares sin perder el paso «¿Quién lo presenta?» (se resuelve mostrándolo solo si se elige HeyGen) | Rediseñar todo lo que hoy funciona (Borradores, Planificador) en la semana del MVP |

**Lectura:** A no sostiene la decisión del fundador ni la demo. C es el destino natural de «un producto → su contenido», pero exige rehacer la navegación en la peor semana para hacerlo. **B** cambia el orden de las preguntas y el modelo del paquete sin mover de sitio Borradores ni Planificador, y deja C como una vista adicional (pestaña «Contenido» en la ficha del producto) para cuando haya campañas.

---

## 3. Recomendación: el Post primero (B), con el catálogo como entrada

### 3.1 Tres principios que ordenan todo lo demás

1. **Qué comunicar antes que con qué.** La primera pregunta es el producto y el ángulo. La herramienta (plantilla, avatar, guion) es una **receta** que el router propone con su costo; el operador la confirma o la cambia.
2. **El Post es la unidad; la salida es lo que se publica.** Un Post tiene un copy aprobado, un producto, un ángulo, una receta y **N salidas** (hoy: Reel 9:16, feed 4:5, historia 9:16). Se aprueba el Post; se programa y publica cada salida por separado, cada una con su categoría derivada del puerto (`reel` → REEL, `feed` → GALERIA/IMAGE, `story` → STORIES). Es lo que la regla «un Post aprobado sigue el flujo de publicación existente sin pasos manuales» (plan §6) necesita para ser verdad.
3. **El catálogo abre el flujo, no lo configura.** Subir fotos del producto es el primer paso de publicar, no un ajuste del negocio. Va a la isla *Publicas* como primer ítem, y cada producto tiene un botón «Crear post».

### 3.2 Glosario (extiende design-system §7.2)

| Concepto | Palabra en UI | No usar |
|---|---|---|
| `content_drafts` row: producto + ángulo + copy + receta + salidas | **post** | pieza (legado), encargo, draft |
| cada archivo renderizado de un post (`image_assets` con `output_port`) | **salida** (Reel · Feed · Historia) | formato, medio, asset |
| el conjunto de salidas de un post | **paquete** | kit, bundle |
| producto + ángulos + fechas → N posts | **campaña** | lote |
| qué se dice (`ContentType`) | **ángulo** | tipo de contenido, «de qué trata» |
| cómo se produce (motor + plantilla, o avatar, o guion) | **receta** | tipo de pieza, motor |

El sidebar diría «Crear post» en vez de «Crear pieza». Es un cambio de glosario y lo decide el fundador (§5, P1); hasta entonces se mantiene «Crear pieza».

### 3.3 El flujo propuesto, pantalla por pantalla

```
 Catálogo (Publicas → Productos)          /create?product=…              Borrador               Planificador
 ┌──────────────────────────┐    ┌──────────────────────────┐    ┌──────────────────┐    ┌────────────────────┐
 │ [foto] Shawarma mixto    │    │ 1 ¿Qué anuncias?         │    │ Tu paquete       │    │ Sin programar      │
 │  $ 9.500 · 3 fotos       │ ─► │   producto ✓ · ángulo    │ ─► │ ▣ Reel  ▣ Feed   │ ─► │ ▣ Shawarma mixto   │
 │  [Crear post]            │    │   nota (opcional)        │    │ ▣ Historia       │    │  Reel ○ Feed ○ Hist○│
 │                          │    │ 2 ¿Cómo la hacemos?      │    │ copy (variantes) │    │  [Asignar ▾]       │
 │ [foto] Combo dúo         │    │   3 recetas con costo    │    │ [Aprobar paquete]│    │   → Reel  lun 12:00│
 │  …                       │    │ 3 Generar (recap)        │    │                  │    │   → Feed  lun 12:00│
 └──────────────────────────┘    └──────────────────────────┘    └──────────────────┘    │   → Hist  lun 19:00│
                                                                                         └────────────────────┘
```

#### Pantalla 0 — `/catalog` como entrada («Productos»)

- **Sidebar:** `Catálogo` sale del pie *Negocio* y entra en *Publicas* como primer ítem, con el nombre **Productos**: `Productos · Crear pieza · Borradores · Planificador · Publicar` se lee como el flujo (§4.2 del design system: «el menú está ordenado por el flujo de trabajo»). El Brand Kit se queda en *Negocio*: se configura una vez; el catálogo se toca cada semana.
- **Tarjeta de producto:** gana una acción `soft` **«Crear post»** (`/create?product={id}`), además del toque para editar. En el editor, después de subir fotos, la acción `solid` pasa a ser **«Crear post con estas fotos»**: es el momento real del dueño de Bianki al mediodía con el teléfono.
- **Empty state:** ya dice lo correcto («Crea el primero y súbele dos o más fotos reales: con eso una plantilla ya produce Reel, feed e historia»). Se mantiene.
- **Ficha del producto, pestaña «Contenido»** (semana 2+): los posts hechos con este producto, con sus salidas y estado. Es la vista C sin rehacer la navegación.

#### Pantalla 1 — `/create` paso 1: «¿Qué anuncias?»

Qué ve: una sola tarjeta (el marco del wizard actual), con:

- **Producto** — la grilla del catálogo (2 columnas en móvil, miniatura grande; la que hoy existe como `_product_picker`), **preseleccionado** si se llegó con `?product=`. Debajo, un enlace discreto «Sin producto (horarios, fidelidad, ubicación…)» que deja el campo vacío y pasa el tema a obligatorio.
- **Ángulo** — las opciones de `ContentType` como **chips** (`_choice`, el control de «Objetivo» hoy): Producto · Promoción · Combo · Precio · Menú · Temporada · Fidelidad · Agotado… Es la decisión que cambia el prompt; va a la vista, no a un `select`.
- **Nota** (opcional) — «solo este fin de semana», «con papas»: el antiguo «Tema o producto» degradado a afinación.
- **Más opciones** (`rx.accordion` cerrado) — destino (orgánico/anuncio/ambos), objetivo, debe mencionar / debe evitar. Hoy son tres pasos; ninguno cambia la decisión del dueño en el 90 % de los casos.

Qué decide: qué producto y qué ángulo. **Formato no se pregunta**: la plantilla produce los tres; las recetas que no (HeyGen, guion) lo declaran en su tarjeta.

Qué guarda el estado: `selected_product_id` (ya existe), `brief_content_type` (ya existe), `brief_topic` (ya existe, deja de ser obligatorio si hay producto). El hueco «el brief lleva el nombre del producto, no su id» (backlog §4.1) se cierra aquí mandando `product_id` — contrato con pipeline, pequeño.

#### Pantalla 2 — «¿Cómo la hacemos?»

Es el paso «Receta» actual, con dos cambios:

- **Las recetas absorben los tipos.** El router ya devuelve Remotion / HeyGen / UGC. Se añaden a la misma grilla las que hoy son «tipos»: **«Lo grabo yo»** (guion para creador real, costo: solo texto) y, mientras exista, «Imagen publicitaria» (a retirar con MP-13). El **kind** del brief pasa a ser una consecuencia de la receta elegida (`recipe_notice` ya avisa «esta receta cambia la pieza a video con avatar»). La tarjeta sugerida va primera y preseleccionada; en móvil las tarjetas se apilan (ya ocurre: `columns initial="1"`).
- **Fotos extra, aquí y no en un paso aparte.** Si la receta sugerida exige más fotos de las que el producto tiene («Promo de producto» pide 2–4), la tarjeta lo dice y ofrece la zona de subida **debajo de la grilla**, en la misma pantalla. Una foto subida aquí **también se guarda en el producto** (P6 para el fundador): el dueño no va a subirla dos veces.
- **Si se elige HeyGen**, aparece un paso intermedio «¿Quién lo presenta?» (el `_step_presenter` actual, sin cambios). Para plantilla y guion no hay paso intermedio.

Qué decide: la receta (y, con ella, el costo). El texto «El costo es el estimado por salida; el real queda en el borrador» se mantiene.

#### Pantalla 3 — «¿Todo listo?» → Generar

El recap actual (`gen_recap`), con una línea por: producto · ángulo · receta · salidas · costo estimado. Botón `solid` **Generar**. Tres pantallas en vez de siete; las decisiones reales siguen siendo dos.

#### Resultado — «Tu paquete»

Lo que hoy existe (`_template_result`), con tres ajustes:

- Cada salida muestra **su estado** mientras el job corre: `signal_pill` «Renderizando…» / «Lista» / «Falló» por salida (el backend ya deriva estado por salida; hoy la pantalla solo omite la que no llegó). Una imagen lista se ve antes que el video, como pide el plan §2.2.
- Una línea de **costo estimado vs real** cuando el job termina (MP-10 lo pide; hoy solo se ve la receta).
- La acción `solid` sigue siendo **«Revisar y aprobar en Borradores»**; se añade un `soft` «Crear otro con este producto» que vuelve al paso 1 con el producto y el ángulo listos para cambiar solo el ángulo (es el bucle de pulido de prompts del plan §3.3 hecho a mano).

#### `/drafts` — la bandeja

La tabla pasa de `Tema · Estado · Creado` a:

```
 ┌───────┬───────────────────────────────────┬──────────────────────┬────────────┬───────────┐
 │ [img] │ Shawarma mixto · Promoción        │ Reel ● Feed ● Hist ● │ Generado   │ hoy 12:40 │
 │ [img] │ Combo dúo · Precio                │ Reel ◐ Feed ● Hist ● │ Renderizando│ hoy 12:10│
 │  ▣    │ Horario de feriado (sin producto) │ Feed ● Hist ●        │ Aprobado   │ ayer      │
 │  ✎    │ Helado de yogurt · Sabor del mes  │ Guion                │ Generado   │ ayer      │
 └───────┴───────────────────────────────────┴──────────────────────┴────────────┴───────────┘
```

- **Miniatura** (la salida `feed` si existe, si no la primera imagen; el icono del tipo para un guion).
- **Título** = producto · ángulo (el tema libre como subtítulo si lo hay).
- **Salidas** como chips con un punto de estado por salida (tono `ok` / `info` animado / `error`), nunca solo color (§8: la palabra está en el chip).
- Estado del post y fecha, como hoy.
- En móvil la fila colapsa a tarjeta (miniatura a la izquierda, dos líneas, chips debajo). Tabla para la lista homogénea sigue siendo la regla (§4.3 r3); la tarjeta es solo el colapso responsive.
- Semana 2+: **agrupar por campaña** cuando `campaign_id` no sea nulo (un encabezado de grupo con el nombre de la campaña y «4 de 5 aprobados»).

#### `/drafts/{id}` — revisión del paquete

```
 ┌─ Shawarma mixto · Promoción ─────────────────────────── GENERADO ─┐
 │  Tu paquete                                                       │
 │  ┌ Reel 9:16 ─ Lista ┐ ┌ Feed 4:5 ─ Lista ┐ ┌ Historia ─ Falló ┐  │
 │  │   ▶ video        │ │   imagen         │ │  ⚠ render_error  │  │
 │  │  [Descargar]     │ │  [Descargar]     │ │  [Reintentar]    │  │
 │  └──────────────────┘ └──────────────────┘ └──────────────────┘  │
 │  Receta: Promo de producto v1 · Remotion · est. USD 0,00 · real USD 0,00 │
 │                                                                   │
 │  ○ Variante 1  ● Variante 2  ○ 3      [gancho / caption / CTA]    │
 │                                                                   │
 │  [Rechazar]  [Regenerar con otra receta]        [Aprobar paquete] │
 └───────────────────────────────────────────────────────────────────┘
```

- Las salidas van **en fila** (en móvil, en columna con scroll), cada una con su estado, su descarga y, si falló, **Reintentar** (solo esa salida; el backend ya conserva lo que salió).
- **«Aprobar paquete»** aprueba el Post (una decisión humana, como hoy). Semana 2: un checkbox por salida «No publicar esta» para excluir, por ejemplo, la historia; la salida excluida no aparece en el Planificador.
- **«Regenerar con otra receta»** reemplaza a «Rechazar y regenerar» en los posts con plantilla: abre las tres recetas cotizadas **sobre el mismo brief** (mismo producto, mismo ángulo, mismo copy aprobado si ya lo había) y genera una revisión nueva. Es la segunda puerta de la cotización: la primera queda **antes de generar** (como hoy), porque el costo se decide antes de gastar; la segunda está en el borrador, porque es ahí donde el dueño ve que «con avatar quedaría mejor».
- La barra de decisión y el contador de caducidad se mantienen como están.

#### `/planner` — programar por salida

- **Tarjeta en «Sin programar»:** miniatura (feed), título producto · ángulo, y **un chip por salida con su estado de programación**: «Reel · sin programar», «Feed · lun 12:00 @bianki», «Historia · publicada». Una sola tarjeta por Post: el paquete no se desarma en la lista, se desarma al asignar.
- **«Asignar»** en un Post con varias salidas abre el diálogo actual con un control más, arriba: **Salida** (`segmented_control`: Reel · Feed · Historia, preseleccionada la primera sin programar). Día, hora y cuenta, como hoy. Resultado: **un `calendar_event` por salida**. Un atajo `soft` «Programar las tres» crea tres eventos con la misma hora y cuenta, editables después (la historia típica sale a otra hora; se edita el evento como hoy).
- **Chip en el calendario:** `Shawarma mixto · Reel` — el nombre de la salida va en el chip, porque el mismo Post aparece hasta tres veces en la semana.
- **Ejecutor:** publica la salida del evento, no el Post entero; la categoría sale del puerto (`reel` → REEL · `feed` → IMAGE · `story` → STORIES). Es el contrato que hay que acordar (§3.5).

#### `/publish` — sin cambios esta semana

`/publish` sigue siendo el camino manual («tengo el archivo»). El paquete llega a Instagram por el Planificador. Semana 2: un botón «Publicar ahora» por salida en el borrador aprobado que reutiliza `PublishService` con la salida ya en R2 — para el día que el dueño quiere la historia **ya**, sin pasar por el calendario.

### 3.4 Cómo encaja la campaña después (sin rediseñar)

Una campaña es **la pantalla 1 con multi-selección**: N productos × N ángulos × un rango de fechas × una cuenta.

```
 /campaigns/new
 1 ¿Qué anuncias?      productos [☑ Shawarma mixto ☑ Combo dúo ☐ …]  ángulos [☑ Producto ☑ Precio ☑ Combo ☐ …]
 2 ¿Cuándo?            lun 6 → vie 10 · 1 post/día · @bianki · hora 12:00 (Reel y feed) · 19:00 (historia)
 3 ¿Cómo?              una receta para todos (sugerida) o «decidir por post» · costo total estimado
 → N posts en Borradores, agrupados por campaña, con campaign_id; cada uno se aprueba (o «aprobar todos» cuando el prompt esté estable)
 → los aprobados caen al Planificador con sus eventos por salida ya creados en las fechas de la campaña
```

Lo que la recomendación deja preparado para que esto no exija rediseño: (a) la pantalla 1 ya es «producto + ángulo», solo cambia de radio a checkbox; (b) `/drafts` ya agrupa por `campaign_id`; (c) el Planificador ya programa por salida, así que «la historia a otra hora» es una regla de la campaña, no una excepción; (d) la ficha del producto con pestaña «Contenido» muestra lo mismo visto desde el producto. Nada de esto se construye esta semana; se evita construir algo que lo contradiga.

### 3.5 El contrato que esto pide (no lo decide la UI)

**La UI no puede inventarlo**; va al arquitecto antes de tocar el Planificador:

1. **`calendar_events.output_port`** (nullable; `NULL` = «todo el Post», el comportamiento actual para posts de una sola salida). El ejecutor filtra `image_assets` por el puerto del evento y deriva `media_product_type` del puerto, no de `content_drafts.category`.
2. **`PostSummary.outputs`**: `(port, label, media_type, state, scheduled_label)` por salida, para la tarjeta de «Sin programar» y los chips de `/drafts`. Hoy `PostSummary` expone una miniatura y un `asset_count`.
3. **`product_id` en el brief** (hueco ya detectado en backlog §4.1) y **`campaign_id`** ya existe en `content_drafts` (migración 0038).
4. **Exclusión por salida** al aprobar (semana 2): un flag por `image_asset` o un estado `excluded` del puerto.
5. **La historia como imagen.** `PublishService` solo publica stories de **video** (`publishable.py`: «the publisher has no image story»), y el puerto `story` de `promo_producto` es una **imagen fija**. Dos salidas posibles, ninguna de UI: (a) el publicador aprende la story de imagen (la API de Meta la admite: `media_type=STORIES` con `image_url`), o (b) la plantilla emite la historia como video corto desde la misma composición (unos segundos del Reel reencuadrados). (a) sirve también a `/publish` manual; (b) añade un render por corrida. Decisión de arquitecto + pipeline; hasta entonces la UI marca la salida «Historia» como «solo descarga» (patrón §6.4 del design system, provisionalidad honesta).

La alternativa de **partir el paquete en tres Posts al aprobar** funciona con las reglas actuales sin tocar `publishable.py`, pero triplica la aprobación y el copy, rompe la identidad del paquete («plantilla × métricas» cruza por `template_run`, que quedaría repartida en tres posts) y contradice «el Post como columna vertebral». Se menciona por honestidad; no se recomienda.

---

## 4. Cambios de UI que implica (archivo → cambio)

### Esta semana (antes de la demo del domingo 11)

| Archivo / pantalla | Cambio | Depende de |
|---|---|---|
| `Qualify/ui/layout.py` | `("Catálogo", "package", "/catalog")` sale de `NAV_BUSINESS` y entra **primero** en la zona `publish` como `("Productos", "package", "/catalog")`. Ajustar los tests que afirman sobre `NAV_ITEMS`/`NAV_BUSINESS` (`test_catalog_state.py`, `test_planner_ui.py`, `test_publish_hub_state.py`, `test_brand_kit_editor.py`) | — |
| `Qualify/catalog_page.py` | `_product_card`: acción `soft` «Crear post» → `/create?product={id}`. `_editor`: tras subir fotos, `solid` «Crear post con estas fotos» (misma ruta) | — |
| `Qualify/creative_state.py` | `load_create` lee `product` de la query (`self.router.url.query_parameters`, como `PublishHubState` lee `flow`), preselecciona `kind="template"`, llama `choose_product`, arranca en el paso 1 nuevo. `generator_steps("template")` → `("topic", "recipe", "review")`; `("topic", "recipe", "presenter", "review")` cuando la receta elegida es HeyGen. Para los tipos sin producto (atajo «Sin producto») el orden actual se conserva. `_gen_step_problem("topic")`: válido con producto **o** tema. Enviar `product_id` además de `product_ref` cuando el servicio lo acepte | pipeline (`product_id` en brief, opcional esta semana) |
| `Qualify/content_generator.py` | `_step_topic` → «¿Qué anuncias?»: grilla de producto (ya existe), **ángulo como chips** (`_choice` sobre `content_type_choices`), nota opcional, acordeón «Más opciones» con destino/objetivo/reglas. `_step_kind` deja de ser el primer paso: se convierte en el atajo «Otra cosa» del paso 1 (el picker actual dentro de un `rx.dialog`). `_step_recipe`: añade la zona de fotos extra debajo de la grilla cuando la receta sugerida pide más fotos; añade la tarjeta «Lo grabo yo» (guion) como receta local. `_HEADINGS` y `_DETAILS_HEADINGS` acordes. `_template_result`: `signal_pill` de estado por salida + línea estimado/real | `RecipeOptionVM` ya tiene `outputs_label`, `reason`; falta `requires_more_photos` (pipeline, S) |
| `Qualify/creative_vm.py` | `DraftSummaryVM` gana `thumbnail_key`, `product_label`, `angle_label`, `outputs: tuple[OutputChipVM, ...]` (`port`, `label`, `state`, `tone`). `DraftVM` gana `outputs` con estado y `cost_estimated_label` / `cost_actual_label` | `creative_provider.drafts_for` lee `image_assets` + `template_runs` (lectura, sin migración) |
| `Qualify/creative_pages.py` (`/drafts`) | `_draft_row`: miniatura, título producto · ángulo, chips de salida con punto de estado. Colapso a tarjeta bajo 640 px. Migrar `drafts_index` y `draft_detail_index` de `_screen`/topbar a `app_shell(page_header, page_body)` (§9.1; es la deuda que estas dos pantallas arrastran) | — |
| `Qualify/creative_pages.py` (`/drafts/{id}`) | `_media_column` → «Tu paquete» en fila (columna en móvil) con estado por salida, descarga y «Reintentar» en la fallida. Botón «Aprobar y descargar» → **«Aprobar paquete»** en posts con plantilla (en los demás, como hoy). «Rechazar y regenerar» → «Regenerar con otra receta» en posts con plantilla: reabre `_step_recipe` sobre el brief del draft | «Reintentar por salida» y «regenerar con otra receta» necesitan dos eventos de servicio (pipeline, M) |
| `Qualify/planner_page.py` + `planner_state.py` | `_post_option`: chips por salida con estado de programación. `_assign_dialog`: control «Salida» cuando el Post tiene más de una; «Programar las tres». `_calendar_chip` / `_list_item`: `título · salida` | **Bloqueado por §3.5 (1)-(2)** — se diseña ahora, se cablea cuando el contrato exista. Si no llega para el domingo, la demo programa el Reel como `category=reel` tras excluir las stills (ver §5, P3) |
| `docs/design-system.md` §7.2 | Añadir las filas del glosario de §3.2 | fundador (P1) |

### Semana 2 (12–18 de octubre)

| Archivo / pantalla | Cambio |
|---|---|
| `/drafts/{id}` | Checkbox «No publicar esta» por salida al aprobar; exclusión persistida (§3.5 (4)) |
| `/drafts` | Agrupar por campaña cuando `campaign_id` no sea nulo; contador «aprobados / total» por grupo; «Aprobar todos» del grupo (lote del plan §4) |
| `/drafts/{id}` aprobado | «Publicar ahora» por salida (reutiliza `PublishService` con la salida en R2); el estado `STAGED` por salida si se usa «Preparar» |
| `/catalog` ficha del producto | Pestaña «Contenido»: posts del producto con chips de salida y estado (vista C sin cambiar la navegación) |
| `/campaigns/new` | La pantalla 1 con multi-selección + «¿Cuándo?» + receta única o por post (§3.4). Nueva entrada en *Publicas* debajo de Productos |
| `/create` | Retirar «Imagen publicitaria» del picker (MP-13); el atajo «Otra cosa» queda con Guion y los dos avatares |
| Laboratorio (plan §3.3) | Pantalla aparte bajo *Negocio* (es trabajo del fundador sobre prompts, no del dueño del local): marca → producto → ángulo → plantilla, generar, calificar 1–5 |

---

## 5. Preguntas para el fundador

1. **Glosario.** ¿«post» en la UI (sidebar «Crear post», pantalla «Tu paquete») en vez de «pieza»? Cambia el sidebar, el glosario de `design-system.md` y textos de cuatro pantallas. Recomendación: sí; «pieza» se queda solo para los tipos sin paquete hasta que se retiren.
2. **Aprobación.** ¿Se aprueba el paquete entero (una decisión) y se excluyen salidas por excepción, o se aprueba salida por salida? Recomendación: entero + exclusión (semana 2). Tres aprobaciones por post son tres toques de más en el teléfono.
3. **Si el contrato del Planificador por salida no llega para el domingo**, ¿vale para la demo programar **solo el Reel** por el Planificador (hoy publicable como `category=reel` si las stills se marcan excluidas) y bajar feed e historia a mano desde el borrador? Es el plan B honesto; sin él, el domingo se publica todo a mano por `/publish`. Y aparte: la historia **de imagen** no la publica la API hoy en ningún caso (§3.5 (5)) — ¿se acepta «solo descarga» para la historia en la demo, o se pide la historia en video?
4. **Cuenta por salida.** ¿La historia va siempre a la misma cuenta que el Reel? Si un día Bianki y Polette comparten tenant con dos cuentas de Instagram, el evento por salida ya lo resuelve (cada evento elige cuenta). Si no, se puede simplificar: una cuenta por Post, tres eventos.
5. **Catálogo en *Publicas*.** El plan lo puso junto al Brand Kit («ambos son lo que la marca es»). La recomendación lo mueve al inicio de *Publicas* porque es donde empieza cada semana. ¿De acuerdo?
6. **Fotos subidas desde el post.** Si en «¿Cómo la hacemos?» se suben fotos extra, ¿se guardan también en el producto del catálogo (recomendado: sí, sin preguntar) o quedan solo en ese post?
7. **Los otros tipos.** ¿Guion para creador y los avatares siguen siendo entradas de primera clase (tarjetas) o pasan a ser recetas del router como propone §3.3? La propuesta los deja como recetas y mantiene el atajo «Otra cosa» para piezas sin producto.

---

## 6. Lo que este doc no decide

- El contrato de datos de §3.5 (arquitecto + pipeline). Esta propuesta lo necesita; no lo define.
- Las composiciones TSX, las plantillas Menú y Corte de video, el Laboratorio y las campañas en lote (plan §5, Fase 2).
- Si `/create` sigue existiendo como ruta propia cuando haya campañas, o pasa a ser `/campaigns/new` con N = 1. Hoy sigue existiendo; la pantalla 1 es la misma en ambos casos.
