# ADR 49 — Pipeline de imagen y carrusel: foto base de Seedream, capa de texto de Claude, composición en Remotion

**Estado:** `[FIRMADO — por Herwin Rey (fundador) el 2026-11-13]` · propuesto por principal-architect el mismo día. El fundador respondió una por una las siete elecciones; quedan registradas en §8 y rigen sobre el resto del documento.
**Épica:** m-25017272 (`docs/epica-refactor-imagen-carrusel.md`) · **Historias de la Fase 1:** m-25017278, m-25017279, m-25017283, m-25017285, m-25017286, m-25017287, m-25017288, m-25017292, m-25017293.
**Evidencia:** revisión de arquitectura de la Fase 1 del 2026-11-13 (un comentario por ticket en Meegle) y el código en `main` a esa fecha.
**Numeración:** el 48 es `docs/adr-48-catalogo-whatsapp-carga-por-api.md` (PR #618, ya en `main`). Esta decisión es la **49**.

Las cifras marcadas **[H]** son estimaciones y las mide m-25017292. Ninguna sale de una factura ni de una medición.

## 1. Contexto

### 1.1 Lo que vio el fundador (2026-11-12)

- Las piezas traen «botones innecesarios y textos horribles». En dos historias de Bianki, Seedream dibujó píldoras y letras sin sentido («BERIRN NON»); nuestro título va en blanco con borde negro sobre la zona más cargada y tapa el logo de la escena; una pieza «Ubicación» muestra una calle europea inventada; el logo sale dos veces.
- «Nada de pillow, todo con remotion y la IA orquestando con remotion» (2026-11-12): Seedream solo hace la foto base, Claude escribe la capa de texto y Remotion compone, sin respaldo en Pillow.

### 1.2 Lo que hace hoy el código

| Tema | Hecho (ruta) |
|---|---|
| Dónde vive | `static_flyer` → `_ad_image` (`creative/media.py` 4382-4529); carrusel → `_carousel` (5408-5697); las dos cosas mezcladas en un archivo de ~10 mil líneas |
| Prompt de la escena | `ad_scene_prompt` (7509-7661) y `_carousel_scene_v3` (7923) le piden a Seedream la escena **y** le hablan de títulos y franjas para texto → induce letras y botones |
| Composición | Pillow (`qualify_creative/compose.py`: `render_ad_slides` :647, `render_carousel_slide` :683, `text_layer` :734), un solo diseño |
| Foto base | **No se guarda**: solo queda la imagen compuesta. `edit_variant` (`service.py:3733`) no puede recomponer |
| Procedencia del carrusel | `rendered_prompt` de las diapositivas no se guarda |
| Copy | `CopyPayload` (`schemas.py:326`) solo tiene `hook` y `cta`; nada por diapositiva |
| Remotion | `PromoStill.tsx` (feed, cuadrado, historia) y `sticker` v1; ninguna composición de carrusel. El flujo `_template` (`media.py:6146`) ya hace escena de Seedream → Remotion y escribe `template_runs` |
| Clave del render | `_template_job_id` (`media.py:9711`) = `uuid5(draft_id:manifest.key)`, **sin revisión ni contenido**; el servicio devuelve el trabajo existente si el `jobId` se repite (`packages/render/CONTRACT.md:103`) |
| Despachador | `QUALIFY_CREATIVE_DISPATCHER` vale `inline` por defecto (`queue_dispatch.py:37`): hilos que mueren con el proceso. La cola de ADR 41 (`creative-worker`) existe; m-25017277 dice si producción la usa para imagen y carrusel |
| Servicio de render | Un trabajo = una plantilla + un juego de props + puertos fijos del manifiesto; perfil `render`, 1536m, concurrencia 1; un limpiador borra los trabajos terminados |
| Contrato de publicación | `slide-N.jpg`, JPEG, dimensiones exactas del formato, posiciones 0..N-1, 2–10 elementos (`planner/publishable.py`, `publishing/service.py:90`) |
| «Quitar» en la Galería | `BusinessMediaStore.remove_business_media` (`catalog/business_media.py:645`): lápida (`deleted_at`) en una transacción con la fila bloqueada → borrar la carpeta `gallery/{tenant}/{media_id}/` en R2 → borrar la fila; ya rechaza el borrado mientras hay un corte activo (`CUTTING_TEXT`). Un conciliador diario termina lo que quedó con lápida. Las fotos de producto se quitan por `CatalogService.remove_media` (`catalog/service.py:568`) |
| Piezas de la Galería que ya existen | `creative/gallery_piece.py` ya arma piezas con medios de la Galería (`n:<uuid>` de `business_media`, `p:<uuid>` de `product_media`), sin ningún candado que impida borrarlos después |
| Bloqueo de R2 | El bucket de producción rechaza borrar y sobrescribir bajo `t/` (la Galería vive en `gallery/`, fuera de `t/`, desde m-24971181); la duración de ese bloqueo sigue abierta (#491), así que la purga de piezas de ADR 39 bajo `t/{tenant}/generated/` puede no poder borrar los bytes |
| Precios (tabla v8) | Seedream 5.0 pro US$0,045 (+0,003 por referencia extra); Remotion propio US$0 |

### 1.3 Decisiones del fundador que dan forma a este ADR

| Fecha | Decisión |
|---|---|
| 2026-11-12 | Composición: nada de Pillow, todo en Remotion con la IA orquestando; sin respaldo en Pillow |
| 2026-11-13 (#8 de la épica) | Pillow se queda **solo** como conversor y reductor de archivos (HEIC con `pillow-heif`, JPEG para Meta, reducción a 4096 px) |
| 2026-11-13 (#10) | Por ahora no se dibujan ni el botón ni la pastilla de precio en imagen y carrusel; el botón propio de los anuncios de Meta se conserva |
| 2026-11-13 (#12) | «Usar mi foto» no consume creación |
| 2026-11-13 (#14) | Tope de 10 diapositivas, sujeto a la medición del render |
| 2026-11-13 (firma de este ADR) | Las siete elecciones de §8 |

## 2. Decisión

**La imagen y el carrusel se producen en cuatro etapas con contratos tipados entre ellas, en un módulo propio. Seedream 5.0 pro solo hace la foto base, que se guarda. Una llamada de Claude con la foto escribe la capa de texto, elige un diseño de un conjunto cerrado y avisa si la base trae letras inventadas. Remotion compone. Otra llamada de Claude revisa la imagen compuesta y la corrige una vez. Ningún píxel de la pieza lo dibuja Pillow.**

1. **Foto base solo de Seedream 5.0 pro, guardada** (§8.7: no se comparan modelos). El prompt de la escena no menciona texto, títulos, botones ni franjas. La base se guarda en `t/{tenant}/generated/{draft_id}/base/…` con su fila en `image_assets`: sha256, `vendor_task_id`, modelo, `rendered_prompt`, versión de prompt. Una fila con `vendor_task_id` nunca se vuelve a enviar (ADR 41 §8). Si la llamada de la capa informa letras o botones inventados, la base se regenera **una sola vez**, y ese tope lo impone una clave única sobre el intento, no un `if`. *(Enmienda 2026-11-14, en producción desde la migración `0165`, PR #664: la fila de la base va en una tabla propia `piece_base_photos`, no en `image_assets`; ver el bloque «Foto base» de la enmienda de §2.1.)*
2. **La capa de texto es de Claude, sobre un esquema cerrado.** `LayerSpec` (pydantic) con título, subtítulo, frase de llamado opcional, bloques de información y un campo `base_has_invented_text` (§8.2). `layout_id` sale de un enum versionado que comparten Python y `packages/render/src/props.ts`, con largo máximo por campo según el diseño. El precio entra **por referencia** (`product_id` → precio del catálogo al componer), nunca como texto escrito por el modelo; hoy no se dibuja (decisión #10), pero el esquema ya no permite inventarlo.
3. **Remotion compone.** Las props de Remotion se derivan de la capa, no al revés: cambiar de diseño no vuelve a llamar a Claude. Una pieza de imagen es una foto fija; un carrusel son N fotos fijas con contador de diapositiva. Cada foto se convierte a JPEG con las dimensiones exactas y se guarda en R2 como `slide-N.jpg` en cuanto termina, antes de que el limpiador del render la borre.
4. **Revisión de la imagen compuesta, activa desde el inicio** (§8.3). Una llamada de Claude mira lo compuesto; si encuentra un defecto, escribe una capa corregida (fila hija, `source='model'`) y se recompone **una vez**, sin volver a llamar a Seedream.
5. **Sin composición en Pillow y sin respaldo en Pillow.** `render_ad_slides`, `render_carousel_slide` y `text_layer` se borran en m-25017293, que también pasa a Remotion el camino viejo de carrusel dentro de `STATIC_FLYER` (§8.1). Pillow sigue solo para convertir y reducir archivos.

### 2.1 Dónde vive la capa: tabla nueva `piece_layers`

La crea la migración de m-25017278 (número tomado contra `origin/main` al abrir el PR), según `qualify-migration`:

| Columna | Para qué |
|---|---|
| `id`, `tenant_id` + RLS (`ENABLE` + `FORCE` + política con `NULLIF`) en la misma revisión | Aislamiento por negocio |
| `brand_id` con FK compuesta a `brands (id, tenant_id)` | Que la capa no cruce negocios ni por error de código |
| `draft_id`, `version_id` → `piece_versions`, `position` | Una capa por diapositiva y por revisión |
| `layout_id`, `layout_version`, `spec` JSONB, `spec_sha256` | El contenido y su huella para la clave del render |
| `base_asset_id` → `image_assets` (foto de Seedream) o la referencia al medio de la Galería (§2.6) | La foto que vio Claude y sobre la que se compone |
| `source` (`model` · `owner_edit` · `owner_photo`), `parent_layer_id`, `created_by` | Quién la escribió y de qué capa sale |
| `model_id`, `prompt_version`, `pipeline_version` | Procedencia |
| `UNIQUE (tenant_id, version_id, position)` | Idempotencia: un reintento no crea otra capa — **reemplazada por la Enmienda 2026-11-14, abajo** |

**Recomponer** es una revisión nueva en `piece_versions` (`UNIQUE (tenant_id, draft_id, revision)` ya existe) que reusa la misma base, más una fila nueva en `piece_layers` con `parent_layer_id`. La acción lleva una clave de petición: el doble clic no crea otra versión. *(Enmienda 2026-11-14, decisión del fundador: un cambio del dueño sobre la misma base **no** abre versión; esta regla queda solo para «rehacer», ver §2.3.)*

**La edición de texto del dueño** cuenta como entrada manual (excepción del 2026-11-04, `docs/arquitectura.md` §1.6) **solo en los campos que él tecleó**: la fila lleva `source='owner_edit'` y `created_by`, y por `parent_layer_id` conserva la procedencia del modelo para los campos que no tocó. No se apoya solo en Langfuse, porque la capa alimenta una publicación y «Repetir este diseño» (m-25017310) la va a reusar.

**Volumen [H]:** ~30 piezas de imagen o carrusel por negocio al mes × ~3 capas (diapositivas, ediciones y la corrección de §2.4) ≈ 1 100–1 400 filas por negocio al año → ~110 000–140 000 al año con 100 negocios. Lejos de los umbrales de ADR 31.

> **Enmienda 2026-11-14 — el esquema tal como quedó en producción** (migración `0163_piece_layers`, PR #651, desplegada; modelo `PieceLayer` en `creative/models.py`). La revisión del código obligó a cambiar tres cosas de la tabla de arriba. Lo de arriba queda como se firmó; esto rige.
>
> 1. **Unicidad.** `UNIQUE (tenant_id, version_id, position)` no servía: la capa corregida por la revisión de lo compuesto (§2 punto 4, activa desde el inicio por §8.3) vive en la **misma** versión y posición que la capa que corrige, y un recomponer es una versión nueva que deriva de la misma capa anterior, quizá varias veces. Quedaron dos claves:
>    - **una sola capa raíz por versión y posición:** índice único parcial `uq_piece_layers_root_position` sobre `(tenant_id, version_id, position) WHERE parent_layer_id IS NULL`. Un reintento no crea una segunda raíz;
>    - **a lo sumo una capa derivada del mismo padre dentro de una versión:** `uq_piece_layers_parent UNIQUE (tenant_id, parent_layer_id, version_id)`. Un reintento de la corrección, o del primer paso de una versión nueva, no crea una segunda hija; un cambio más dentro de esa versión deriva de la hija.
>
>    La capa vigente de una versión y posición es la última de su cadena: la que no tiene hija en esa versión. Una versión nueva puede no tener raíz, porque su primera capa deriva de una capa de otra versión.
> 2. **Aislamiento también en las referencias.** `base_asset_id` → `image_assets (id, tenant_id)` y `parent_layer_id` → `piece_layers (id, tenant_id)` son FK compuestas con `tenant_id`, como `brand_id`, `draft_id`, `version_id` y `created_by`. Postgres revisa las FK sin RLS, así que una FK de una sola columna dejaba que un negocio apuntara a una fila de otro, y averiguara si existe. Para eso la migración agregó `UNIQUE (id, tenant_id)` a `image_assets` y a `piece_versions`. Las dos FK usan `ON DELETE SET NULL` solo sobre su columna: purgar la foto o la capa padre conserva la historia sin tocar `tenant_id`.
> 3. **Dos columnas para la base, nunca las dos:** `base_asset_id` para la foto de Seedream guardada, o `base_media_ref` para un medio de la Galería, en el formato de `gallery_piece.py` (`n:<uuid>` de `business_media`, `p:<uuid>` de `product_media`), **sin FK** (`ck_piece_layers_one_base`). El candado de borrado de §2.6 no vive en esta tabla: es `piece_media_refs`, que todavía no existe y crea m-25017286.
>
> **Lo que el esquema no impone y tiene que cumplir quien escribe** (m-25017283, y m-25017287/m-25017288 cuando escriban):
> - que el padre de una capa derivada sea del mismo borrador y la misma posición;
> - qué cambio abre una versión nueva y cuál queda en la misma: lo decidió el fundador el 2026-11-14, ver §2.3;
> - que una capa nueva derive siempre de la **hoja** vigente de su versión y posición, nunca de una capa intermedia (§2.3).
>
> Además: `qualify_app` solo tiene `SELECT` e `INSERT` (una capa nunca se edita en su lugar); `source='model'` exige `model_id` y `prompt_version`; `source='owner_edit'` exige `created_by` y `parent_layer_id`; `position` va de 0 a 9. La tabla salió vacía, sin relleno de piezas anteriores (§8.5).
>
> **Foto base en su propia tabla — fusionada y desplegada el 2026-11-14** (m-25017279, PR #664, migración `0165_piece_base_photos`; reemplazó a la primera versión de esa historia, nunca fusionada, que guardaba la base como fila `role='base'` de `image_assets` y la ocultaba con una condición en la política `tenant_isolation`). Rige sobre §2 punto 1 y sobre el punto 2 de esta enmienda en lo que toca a `base_asset_id`. El prompt de la foto base es el compilador 6 (el 5 de #662 menos los «Datos clave» y el nombre de la tipografía):
> - **La foto base cruda vive en `piece_base_photos`**, con `tenant_id` y la política de aislamiento de siempre (RLS con `NULLIF`, `ENABLE` + `FORCE`), una fila por versión y posición; no es una fila de `image_assets`.
> - **Por qué:** una base no es una salida de la pieza. En `image_assets` habría que esconderla de unos cuarenta lectores que tratan cada fila como algo publicable (portada, carrusel, Planificador, exportación, WhatsApp). En su propia tabla, ningún lector existente puede verla, por construcción. Además, la política de aislamiento por negocio no se mezcla con una regla de visibilidad, y los lectores que saltan RLS no ven bases por casualidad.
> - **`piece_layers.base_asset_id` apunta a `piece_base_photos (id, tenant_id)`** con FK compuesta. La migración que lo cambia mueve `fk_piece_layers_base_asset` de `0163`; las dos tablas están vacías.
> - **Guardar en R2:** el bucket rechaza sobrescribir bajo `t/`. Si el objeto de la base ya existe con el **mismo sha256**, cuenta como guardado con éxito; así un reintento de la misma revisión no deja la pieza sin base.
> - **Base que no se pudo guardar:** la pieza se termina igual, pero queda **marcada** como sin base, con una métrica o aviso además del log. Esa pieza no se recompone: solo se puede rehacer con «Crear otra» (como las piezas viejas, §8.5).

### 2.2 Un trabajo de render por diapositiva

Un carrusel de N diapositivas son **N trabajos de render**, cada uno con `jobId = uuid5(version_id, position, spec_sha256, layout_version, sha256 de la base)`.

- Reanudar queda como hoy: las diapositivas terminadas se conservan y un reintento solo vuelve a renderizar la que falló.
- Con concurrencia 1, varios trabajos cortos dejan que se intercalen los de otros negocios; uno de 10 puertos acapararía el render.
- La memoria por trabajo queda acotada dentro de los 1536m.
- La clave incluye el contenido: recomponer con texto nuevo nunca devuelve la imagen vieja (corrige el defecto de `_template_job_id`).

### 2.3 Frontera del módulo: `qualify_api/creative/image_pipeline/`

| Etapa | Entra | Sale | Qué se mueve de `media.py` |
|---|---|---|---|
| `base` | Brief, producto, formato | `BaseImage` (clave R2, sha256, `vendor_task_id`, modelo, versión de prompt) | `_scene_image`, `ad_scene_prompt`, `_carousel_scene_v3` |
| `layer` | `BaseImage`(s) o medios de la Galería, brief, catálogo | `LayerSpec` por diapositiva + `base_has_invented_text` | — (nuevo) |
| `compose` | `LayerSpec` + base | Fotos fijas en R2, filas en `image_assets` y `template_runs` | Partes de `_ad_image` y `_carousel`, y el camino viejo de carrusel de `STATIC_FLYER` |
| `check` | Fotos compuestas | Aprobada o una capa corregida | — (nuevo) |

> **Enmienda 2026-11-14 (ver §2.1) — decisión del fundador del mismo día sobre la edición del dueño.** Reemplaza la nota que dejaba esto abierto.
>
> **Lo que decidió** (en dos pasos, el segundo contra la recomendación del primero de abrir una versión):
> 1. Un cambio de texto del dueño queda en la **misma versión**: una fila nueva de `piece_layers` en la misma versión y posición, hija de la capa que edita.
> 2. **Pero anula la aprobación:** editar el texto de una publicación aprobada o programada la devuelve a «Por aprobar» y la saca de la programación; el dueño vuelve a aprobar mirando la imagen recompuesta. Nunca se publica algo distinto de lo aprobado.
>
> **Definiciones (rigen sobre §2.1 «Recomponer»):**
> - **Editar** = cambiar la capa sobre la **misma foto base**, sea el dueño (textos o diseño, `layout_id`) o la revisión de lo compuesto: fila nueva en la **misma** versión y posición, hija de la hoja vigente, y se vuelve a componer con un `jobId` nuevo.
> - **Rehacer** = todo lo que cambia la foto base o el juego de diapositivas (regenerar la base con Seedream, la regeneración única de §2 punto 1, elegir otra foto en «Usar mi foto», generar la pieza de nuevo, y quitar o agregar diapositivas en la Fase 2): **revisión nueva** en `piece_versions`. Coincide con el esquema: `piece_base_photos` admite una sola base por versión y posición (`0165`).
>
> Por eso, en §2.1, «recomponer = revisión nueva» deja de valer para el cambio de texto. Recomponer después de editar **no** abre versión; solo «rehacer» la abre.
>
> **Cadena de capas y cuál vale.** `uq_piece_layers_parent UNIQUE (tenant_id, parent_layer_id, version_id)` permite una sola hija por padre dentro de una versión, así que las ediciones sucesivas **encadenan**: la edición 2 es hija de la 1, y la corrección de la revisión de lo compuesto también es un eslabón. La capa vigente de una versión y posición es la **hoja**: la que no tiene hija en esa versión. Quien escribe siempre deriva de la hoja; si dos escrituras compiten (el dueño edita mientras la revisión todavía corrige), la segunda choca con la clave única y se reintenta sobre la hoja nueva. La pantalla no deja editar mientras la pieza está en `composing`/`compose_waiting`.
>
> **«Deshacer» e historial.** Como una capa nunca se edita en su lugar y la vigente es la hoja, «Deshacer» **no** vuelve a una capa anterior: crea una hija nueva de la hoja con el `spec` de la capa a la que se vuelve. La cadena completa queda como historial.
>
> **Lo que la clave prohíbe:** dos ramas dentro de una versión. No se puede derivar una segunda hija de la original después de deshacer. El producto no lo necesita, porque el «volver al original» se resuelve copiando, como arriba. Si algún día se quisiera un historial con ramas, haría falta otra migración.
>
> **Anular la aprobación dentro de una versión (ADR 32/41), en una sola transacción con la edición:**
> - insertar la capa nueva;
> - borrar la confirmación (`confirmed_sha256` y su clave de R2) y devolver la pieza a «Por aprobar»;
> - sacar de la programación sus eventos `scheduled` (y los futuros de una recurrente), conservando la fecha elegida como sugerencia para cuando el dueño vuelva a aprobar;
> - encolar la composición.
>
> Si un evento está en `publishing` en ese momento, la edición se rechaza («Se está publicando ahora; espera un momento»). El guardián de publicación (ADR 41 §3.4), que compara el sha256 del objeto con el confirmado, sigue siendo la última barrera aunque algo falle.
>
> **Idempotencia y claves:**
> - la acción de editar lleva una clave de petición; un reintento con la misma hoja y el mismo `spec_sha256` devuelve la capa ya creada;
> - el `jobId` del render ya incluye `spec_sha256` (§2.2), así que cada edición es un trabajo nuevo y «Deshacer» a un texto ya compuesto puede reusar el trabajo anterior;
> - la clave de la composición en `creative_jobs` **ya no puede ser** `(tenant_id, draft_id, kind, revision, position)` (§2.4): dos ediciones en la misma revisión chocarían. Lleva el id de la capa (o su `spec_sha256`);
> - la clave del objeto compuesto en R2 tampoco puede depender solo de la revisión, porque el bucket rechaza sobrescribir bajo `t/`. Lleva el id de la capa o su `spec_sha256`. Si ya existe un objeto con el mismo sha256, cuenta como guardado (la misma regla que la base). La fila de salida en `image_assets` de esa versión y posición pasa a apuntar al objeto nuevo.
>
> **Procedencia:** la edición del dueño cuenta como entrada manual (`docs/arquitectura.md` §1.6) solo en los campos que él tecleó (`source='owner_edit'`, `created_by`); el padre conserva la procedencia del modelo. Una corrección de la revisión es `source='model'`, con su modelo y versión de prompt.
>
> **Docstrings:** el del modelo `PieceLayer` ya describe la edición en la misma versión y coincide con esta decisión. El de la migración `0163` (la idea de que «una versión nueva vuelve a derivar de la misma capa vieja: el dueño edita, vuelve, edita de nuevo») queda superado para la edición del dueño: vale solo para «rehacer». Alinear el código es tarea de m-25017283/m-25017288.
>
> **Queda abierto para el fundador:**
> - **(i)** Después de una edición del dueño, ¿la revisión automática de lo compuesto (§8.3) puede cambiar los textos que él tecleó, o solo el acomodo? Propuesta: no toca los campos del dueño; solo puede pedirle que revise.
> - **(ii)** Al volver a aprobar, ¿la publicación vuelve sola a la fecha que tenía, o el dueño la programa de nuevo? Propuesta: se le ofrece la misma fecha con un toque.
> - **(iii)** ¿Se puede editar una publicación **ya publicada**? Lo publicado en Meta no cambia. Propuesta: no se edita; se ofrece «Crear otra» a partir de ella.

En `media.py` queda solo el despacho por `ContentKind`. La etapa `compose` habla con `RemotionRenderClient`; no reusa `_template` tal cual. Cada etapa se puede probar sin red con dobles de los clientes.

### 2.4 Composición en cola: estados y reintento

- **Estados de la pieza:** `base_ready` → `composing` → `compose_waiting` (con `next_attempt_at` y espera creciente) → `ready` · `failed`.
- **Trabajo en `creative_jobs`** (ADR 41) con `kind='compose'` y la clave natural `(tenant_id, draft_id, kind, revision, position)` *(enmienda 2026-11-14: más el id de la capa, porque una revisión admite varias ediciones; ver §2.3)*. El `jobId` del render sale de §2.2. Seedream no se vuelve a llamar: la base está guardada con su `vendor_task_id`.
- **Tope de 10 minutos** (§8.4). Se cuenta desde el primer intento fallido porque el render no respondía, es decir, desde que la pieza entra en `compose_waiting`, no desde que entró a la cola: una pieza que solo espera turno detrás de otras no falla por eso. Pasados los 10 minutos, la pieza queda `failed`, **sin descontar otra creación**, con un botón para reintentar que reusa la base y la capa.
- **Lo que ve el dueño:** «La estamos terminando» mientras espera; si falla, «No pudimos terminar tu publicación. Inténtalo de nuevo; no se te descuenta otra creación.» El chequeo de salud del render con alerta lo hace m-25017289.
- **Precondición:** la cola de ADR 41 activa para imagen y carrusel en producción, y el despachador `inline` retirado para esos tipos, **antes** de borrar Pillow. Los hilos de `InlineDispatcher` mueren al reiniciar y no dejan reintento durable.

### 2.5 Claude con las fotos del cliente

- **Transporte:** imágenes en base64 o con URL firmada de vida corta; nunca una URL pública.
- **Trazas:** Langfuse corre en la máquina de Deivid (riesgo ya registrado). Los bloques de imagen se **enmascaran** en la traza; queda solo el sha256 y la clave de R2. Sin esto, fotos de clientes terminan en un equipo personal.
- **Dos llamadas con imagen por pieza, como base** (§8.2 y §8.3): la de la capa (que además informa si la base trae letras inventadas) y la revisión de lo compuesto. En el carrusel, una sola llamada con las N fotos devuelve las N capas, y una sola llamada revisa las N compuestas. Si la revisión corrige, hay una recomposición, sin otra llamada de revisión.
- **Costo y latencia [H]:** una imagen de ~1080×1350 son ~1 500–1 700 tokens de entrada; ~US$0,01–0,02 y 3–8 s por llamada con Sonnet. Dos llamadas ≈ US$0,02–0,04 y 6–16 s por pieza, contra US$0,045 de la foto base con pro. Todo va detrás del medidor por turno y fuera de la petición web.
- **«Usar mi foto»:** no consume creación (decisión #12), pero sus dos llamadas a Claude se registran en el libro de consumo con su costo en dólares y 0 creaciones. La pieza **referencia** la foto de la Galería, sin copiarla (§8.6, §2.6).
- **BytePlus:** solo Seedream 5.0 pro, cuyo preset no cede datos (confirmado el 2026-11-12). Usar lite o flash con fotos o referencias de clientes queda fuera de esta decisión.

### 2.6 «Usar mi foto» referencia la Galería, y la Galería no deja borrar lo que una pieza usa

Decisión del fundador (§8.6): *«referencia a la galería, pero no debería dejar eliminar algo de galería si se está usando de referencia para una pieza»*.

**Tabla de referencias `piece_media_refs`** (misma migración que `piece_layers`, o la de m-25017286; **enmienda 2026-11-14:** no entró en `0163`, la crea la migración de m-25017286):

| Columna | Para qué |
|---|---|
| `tenant_id` + RLS con `NULLIF`, `brand_id` | Aislamiento |
| `draft_id` → `content_drafts` `ON DELETE CASCADE` | Borrar la pieza libera la foto sin código extra |
| `business_media_id` → `business_media` `ON DELETE RESTRICT`, o `product_media_id` → `product_media` `ON DELETE RESTRICT` (`CHECK`: exactamente uno) | La base de datos no deja borrar la fila del medio mientras alguien la usa |
| `UNIQUE (tenant_id, draft_id, business_media_id, product_media_id)` | Idempotencia al crear y al recomponer |

Las FK van con `tenant_id` (FK compuesta `(id, tenant_id)`); si `business_media` o `product_media` no tienen esa `UNIQUE`, la migración la agrega. La procedencia de la capa (`piece_layers.base_media_ref`, enmienda 2026-11-14) guarda el id del medio aparte, sin FK, para que liberar la referencia no borre la historia.

**Por qué la FK sola no alcanza:** «Quitar» pone la lápida, después borra la carpeta de R2 y **al final** borra la fila. Una FK `RESTRICT` solo saltaría en el último paso, con el archivo ya borrado. Por eso el candado tiene dos capas en la base de datos:
1. Un disparador `BEFORE UPDATE OF deleted_at` en `business_media` (y el equivalente en `product_media`) que rechaza poner la lápida si existe una fila en `piece_media_refs`. La regla vive en la base de datos, no solo en la pantalla.
2. La FK `RESTRICT` como última línea, para cualquier borrado directo de la fila.

Concurrencia: crear la referencia toma el bloqueo `FOR KEY SHARE` de la FK sobre la fila del medio, y «Quitar» ya la toma `FOR UPDATE` (`business_media.py:652`), así que una pieza que se crea al mismo tiempo que se quita la foto no puede ganar las dos cosas. La creación de la pieza, además, rechaza un medio con lápida (ya lo hace `gallery_piece.py` por «vivo»).

**Todos los caminos de borrado que tienen que respetarlo:**
- «Quitar» de la Galería (`remove_business_media`), uno por uno.
- Quitar varios a la vez, si existe o cuando exista: quita los libres y dice cuáles se quedaron.
- El conciliador diario: solo termina medios que ya tienen lápida, así que no salta el candado; no hace falta cambiarlo, pero un test lo fija.
- El corte de un video (deja la lápida en el original): queda rechazado si el original está en uso.
- Quitar o reemplazar una foto de producto en Catálogo (`remove_media`), cuando la referencia es a esa fila de `product_media`.
- La purga de piezas de ADR 39 y el borrado de un negocio: no borran medios de la Galería; el borrado de un negocio borra primero sus piezas y con ellas las referencias.

**Lo que ve el dueño cuando se rechaza** (español llano, `qualify-copy-es`):
> No puedes quitar esta foto todavía: la usa tu publicación «{título}». Cuando borres esa publicación o le cambies la foto, podrás quitarla.

Con varias publicaciones: «…la usan 3 de tus publicaciones: «{título 1}», «{título 2}» y otra más.» Cada título lleva a su publicación. El mensaje no dice «referencia», «pieza» ni «borrador».

**Cómo se libera:**
1. **La pieza se borra:** `ON DELETE CASCADE`.
2. **La pieza deja de usar la foto:** al recomponer o cambiar la foto, las referencias se reescriben para la revisión vigente. Las revisiones viejas no retienen nada, porque no se recomponen.
3. **La purga de ADR 39:** cuando la pieza queda marcada `media_purged_at`, se borran sus referencias en la misma transacción. Se libera por la marca en la base de datos, no por el éxito del borrado en R2: con el bloqueo del bucket sobre `t/` (#491) los bytes de la pieza pueden quedar, y eso no debe dejar la foto de la Galería bloqueada para siempre.

**Cruce con ADR 39 y ADR 47:**
- Los medios de la Galería no caducan (ADR 47); la pieza sí. Una pieza publicada retiene su foto hasta **90 días después de su último uso**. Una pieza con evento `scheduled` o recurrente la retiene mientras siga programada.
- El candado protege **poder recomponer**, no la publicación: el publicador lee la imagen compuesta de `generated/`, no la foto de la Galería.
- La foto de la Galería vive en `gallery/` (fuera de `t/`); el bloqueo de R2 no le afecta.

**Alcance:** el mismo candado aplica a las piezas que ya arma `gallery_piece.py` con medios de la Galería; hoy esas piezas no tienen candado. Ver la subpregunta 6b de §8.

## 3. Condiciones que tienen que cumplirse (bloqueantes)

1. **m-25017293 pasa el camino viejo de carrusel de `STATIC_FLYER` a Remotion** antes de borrar `render_carousel_slide` (§8.1). m-25017299 queda para quitar código ya sin uso y deja de ser una dependencia para borrar Pillow.
2. **Clave del render con contenido.** Ningún trabajo nuevo usa `_template_job_id`; la clave es la de §2.2.
3. **Cola en producción.** m-25017293 no empieza hasta que m-25017277 confirme `QUALIFY_CREATIVE_DISPATCHER=queue` (o equivalente) para imagen y carrusel en producción.
4. **Recomponer anula la aprobación y tiene fecha de vencimiento.** *(Enmienda 2026-11-14: vale igual para la edición del dueño dentro de la misma versión, que además saca la pieza de la programación; ver §2.3.)* Recomponer invalida `confirmed_sha256` (ADR 32 doble aprobación, ADR 41 §3.3) y la pieza vuelve a «por aprobar». Después de la purga de ADR 39, o para piezas anteriores a este pipeline (no tienen base guardada), no hay recomposición: la pantalla ofrece solo «Crear otra» (§8.5).
5. **El candado de la Galería existe en la base de datos antes de que «Usar mi foto» salga** (m-25017286): disparador, FK `RESTRICT`, el mensaje para el dueño y tests `-m db` que prueben que la lápida se rechaza y que otro negocio no ve ni bloquea nada.

## 4. Opciones consideradas

| Tema | Opción | Veredicto | Por qué |
|---|---|---|---|
| Dónde vive la capa | **A. Tabla nueva `piece_layers`** | **Elegida** | Sobrevive a los reintentos del render, se versiona con `piece_versions`, lleva procedencia y RLS propias |
| | B. `template_runs.props` | Descartada | Es el registro de un trabajo de render (su id ES el `jobId`); se repite por reintento y mezcla la entrada con la ejecución |
| | C. `image_assets.params` | Descartada | Es por archivo de salida: al recomponer nace otro archivo y la capa quedaría repartida |
| | D. Ampliar `CopyPayload` | Descartada | Es el copy de la publicación, no la capa de una diapositiva; no tiene posición ni base |
| Render de un carrusel | **A. N trabajos, uno por diapositiva** | **Elegida** | Reanudación por diapositiva, reparto entre negocios a concurrencia 1, memoria acotada |
| | B. Un trabajo con N puertos | Descartada (se reabre si la medición lo pide) | El manifiesto tiene puertos fijos y el carrusel va de 2 a 10; acapara el render; no está verificado qué hace el servicio con un `jobId` repetido cuyo trabajo falló a medias |
| Composición | **A. Remotion** | **Elegida** (decisión del fundador) | Ya corre en producción; diseños versionados; misma herramienta que video y stickers |
| | B. Pillow con diseños nuevos | Descartada por el fundador (2026-11-12) | Es lo que produjo «textos horribles»; dos motores de diseño que mantener |
| | C. Remotion con respaldo en Pillow | Descartada por el fundador (2026-11-12) | Dos caminos que divergen; la cola con reintento cubre la caída del render |
| | D. Canva | Descartada | Proveedor por pieza, sin diseño cerrado bajo nuestro control, más latencia |
| Revisión de la base | **A. Campo dentro de la llamada de la capa** | **Elegida** (§8.2) | Claude ya está viendo la foto: ahorra una llamada con imagen |
| | B. Llamada aparte (Haiku) | Descartada | Una llamada más por pieza |
| Revisión de lo compuesto | A. Apagada hasta medir | Recomendada, no elegida | Cuidaba el costo hasta tener la medición |
| | **B. Activa desde el inicio** | **Elegida por el fundador** (§8.3) | Prefiere la calidad desde el primer día; la medición decide si se queda |
| Foto del dueño | A. Copia propia en la pieza | Recomendada, no elegida | Recomponer no dependía de la Galería y no hacía falta candado |
| | **B. Referencia a la Galería con candado de borrado** | **Elegida por el fundador** (§8.6) | Un solo archivo por foto; el dueño ve qué publicación la usa |
| | C. Referencia sin candado | Descartada | El dueño borra la foto y la pieza ya no se puede recomponer, sin aviso |
| Modelo de la base | **A. Seedream 5.0 pro** | **Elegida por el fundador** (§8.7) | Calidad conocida y preset que no cede datos |
| | B. Comparar pro, lite y flash | Descartada por el fundador | No se mide; flash no tenía confirmado el manejo de datos |
| Piezas viejas | **A. No se recomponen; «Crear otra» con el pipeline nuevo** | **Elegida** (§8.5) | No hay base guardada; la imagen publicada y su procedencia siguen en R2 y en la fila |
| | B. Conservar Pillow para reproducirlas | Descartada | Contradice la decisión del fundador y deja un motor vivo solo para el pasado |

## 5. Encaje con las reglas y los ADR firmados

- **ADR 31:** ningún almacén nuevo; dos tablas más en el Postgres que ya corre.
- **Sin runtime nuevo:** Remotion es el único runtime de Node del repo y ya está en producción.
- **ADR 32:** la doble aprobación se mantiene; recomponer, y desde la enmienda 2026-11-14 también editar dentro de la misma versión, vuelve a pedir aprobación.
- **ADR 39:** la base de Seedream vive bajo `generated/{draft_id}/` y se purga con la pieza; «recomponer gratis» vale mientras exista. La purga libera las referencias a la Galería (§2.6).
- **ADR 41:** la composición es un trabajo más de `creative_jobs`; el reintento no cobra dos veces.
- **ADR 47:** la Galería no caduca; su «Quitar» gana un motivo de rechazo más, junto al del corte activo.
- **Asistido, nunca autónomo:** nada se publica sin que el dueño apruebe la imagen final.
- **Procedencia e idempotencia:** §2.1, §2.2 y §2.6.

## 6. Consecuencias

- **Positivas.** Ningún texto inventado dentro de la foto; la capa se puede editar y recomponer gratis sin otra llamada a Seedream; un solo motor de diseño; procedencia completa por diapositiva; `media.py` adelgaza; «Usar mi foto» no duplica archivos y el dueño sabe qué publicación usa cada foto.
- **Negativas.**
  - Dos tablas y un estado más.
  - Dos llamadas a Claude con imagen en **toda** pieza, también en «Usar mi foto», que no cobra creación: ~US$0,02–0,04 [H] por pieza que no se recuperan con el cupo.
  - Si el render cae más de 10 minutos, las piezas fallan (sin cobro) y el dueño tiene que reintentar; antes Pillow las terminaba.
  - Las piezas viejas dejan de poder editarse.
  - El dueño puede encontrarse con que no puede quitar una foto de su Galería durante hasta 90 días después del último uso de una publicación, o mientras esté programada.
  - El candado toca código que ya está en producción (`remove_business_media`, `remove_media`, el corte) y un tipo de pieza que ya existe (`gallery_piece.py`).
- **Operación.** El perfil `render` (1536m, concurrencia 1) pasa a estar en el camino de toda imagen. Si un carrusel de 10 tarda demasiado, el tope de diapositivas se ajusta (decisión #14).

## 7. Qué queda abierto para la medición (m-25017292)

Sin comparación de modelos de Seedream (§8.7). Se mide:
- Tiempo por foto fija, sobrecosto por trabajo y memoria máxima en el perfil `render`; tiempo de un carrusel de 10 a concurrencia 1 → tope de diapositivas.
- Tokens, costo y latencia reales de las dos llamadas de Claude con imagen; si el campo `base_has_invented_text` detecta las letras inventadas tan bien como una llamada aparte.
- La revisión de lo compuesto (m-25017287): costo y latencia por pieza, y **qué parte de las imágenes corrige de verdad**.

## 8. Decisiones del fundador al firmar (2026-11-13)

| # | Elección | Decisión | ¿Coincide con la recomendación? |
|---|---|---|---|
| 1 | Orden de m-25017293 y m-25017299 | (a) Un solo ticket: m-25017293 pasa el camino viejo de carrusel de `STATIC_FLYER` a Remotion | Sí |
| 2 | Revisión de la foto base | (a) Un campo dentro de la llamada de la capa: una sola llamada con imagen escribe las capas e informa letras inventadas | Sí |
| 3 | Revisión de lo compuesto (m-25017287) | **(b) Activa desde el inicio** | **No** (se recomendaba apagada hasta medir). Se reabre con la medición: ver §9 |
| 4 | Tope de espera de la composición | **10 minutos**, sin descontar otra creación | **No** (se proponían 30). Ver la forma de contarlo en §2.4 |
| 5 | Piezas viejas | (a) No se recomponen; solo «Crear otra» | Sí |
| 6 | Foto del dueño en «Usar mi foto» | **Variante propia:** *«referencia a la galería, pero no debería dejar eliminar algo de galería si se está usando de referencia para una pieza»*. La pieza referencia la foto, sin copia, y la Galería rechaza borrarla mientras una pieza la use (§2.6) | **No** (se recomendaba una copia por pieza) |
| 7 | Modelo de la foto base | **Seedream 5.0 pro**, sin comparar modelos; m-25017292 deja fuera la comparación pro/lite/flash | **No** (se proponía elegir con la medición) |

**Subpreguntas que deja abiertas la decisión 6** (las responde el fundador; mientras tanto, se construye con la opción marcada):
- **6a. ¿Una pieza sin aprobar también bloquea el borrado?** Propuesta: sí, cualquier pieza que exista (por aprobar, aprobada, programada o publicada), con un enlace para borrarla desde el mismo aviso. Alternativa: solo las aprobadas o programadas, y que una pieza por aprobar pierda la foto (y la posibilidad de recomponer) si el dueño la borra.
- **6b. ¿El candado aplica también a las piezas que ya arma la Galería (`gallery_piece.py`) y a las fotos de producto del Catálogo?** Propuesta: sí, la misma tabla para las dos. Las piezas ya existentes ganan el candado cuando se carguen sus referencias; hace falta decidir si se cargan hacia atrás (relleno en la migración) o solo para las piezas nuevas.
- **6c. ¿Una publicación ya publicada debe retener la foto hasta 90 días?** La foto solo sirve para recomponer, y una pieza publicada rara vez se recompone. Alternativa: liberar la foto al publicar, y que esa pieza ya no se pueda recomponer.
- **6d. Videos de la Galería:** el corte de un video usado por una pieza queda rechazado. ¿Se acepta, o el corte debe crear partes nuevas sin poner la lápida en el original mientras esté en uso?

## 9. Qué lo reabriría

- **Revisión de lo compuesto (§8.3):** si en la medición corrige menos del ~5 % de las imágenes en ≥ 200 piezas, o sube el costo por pieza por encima de US$0,05, o suma más de ~10 s al tiempo hasta «por aprobar», se lleva al fundador apagarla o pasarla a Haiku.
- **Tope de 10 minutos (§8.4):** si en un mes más del 1 % de las piezas falla por el tope mientras el render se recupera solo en menos de 30 minutos, se vuelve a proponer un tope más largo.
- **Seedream 5.0 pro (§8.7):** si su precio sube, si el fundador o un cliente reportan caídas de calidad, o si BytePlus cambia el manejo de datos del preset.
- **Candado de la Galería (§8.6):** si los dueños reportan más de una vez al mes que no pueden quitar fotos, o si el soporte tiene que liberar referencias a mano: se revisa la variante de copia por pieza.
- Un trabajo con varios puertos ahorra más de ~2 s por diapositiva sin perder la reanudación.
- El render, con concurrencia 1, deja piezas en «La estamos terminando» más de 5 min en el p95 durante una semana: subir la memoria o la concurrencia con su tabla de opciones.
- Un cliente pide editar piezas anteriores a este pipeline más de una vez.
- `piece_layers` pasa de 5 M filas.
