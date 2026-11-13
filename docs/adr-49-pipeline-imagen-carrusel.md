# ADR 49 — Pipeline de imagen y carrusel: foto base de Seedream, capa de texto de Claude, composición en Remotion

**Estado:** `[PROPUESTO — pendiente de firma del fundador]` · propuesto por principal-architect el 2026-11-13.
**Épica:** m-25017272 (`docs/epica-refactor-imagen-carrusel.md`) · **Historias de la Fase 1:** m-25017278, m-25017279, m-25017283, m-25017285, m-25017286, m-25017287, m-25017288, m-25017292, m-25017293.
**Evidencia:** revisión de arquitectura de la Fase 1 del 2026-11-13 (un comentario por ticket en Meegle) y el código en `main` a esa fecha (migración head `0151`).
**Numeración:** el 48 lo ocupa `docs/adr-48-catalogo-whatsapp-carga-por-api.md` en el PR #618 (abierto). Esta decisión es la **49**. Si el #618 se fusiona primero, su fila 48 va antes que esta en `docs/arquitectura.md` §6; si se fusiona después, hay que resolver el conflicto de orden en la tabla.

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
| Precios (tabla v8) | Seedream 5.0 pro US$0,045 (+0,003 por referencia extra), lite 0,035, flash 0,018; Remotion propio US$0 |

### 1.3 Decisiones del fundador que dan forma a este ADR

| Fecha | Decisión |
|---|---|
| 2026-11-12 | Composición: nada de Pillow, todo en Remotion con la IA orquestando; sin respaldo en Pillow |
| 2026-11-13 (#8) | Pillow se queda **solo** como conversor y reductor de archivos (HEIC con `pillow-heif`, JPEG para Meta, reducción a 4096 px) |
| 2026-11-13 (#10) | Por ahora no se dibujan ni el botón ni la pastilla de precio en imagen y carrusel; el botón propio de los anuncios de Meta se conserva |
| 2026-11-13 (#12) | «Usar mi foto» no consume creación |
| 2026-11-13 (#14) | Tope de 10 diapositivas, sujeto a la medición del render |

## 2. Decisión

**La imagen y el carrusel se producen en cuatro etapas con contratos tipados entre ellas, en un módulo propio. Seedream solo hace la foto base, que se guarda. Claude escribe la capa de texto y elige un diseño de un conjunto cerrado. Remotion compone. Ningún píxel de la pieza lo dibuja Pillow.**

1. **Foto base solo de Seedream, guardada.** El prompt de la escena no menciona texto, títulos, botones ni franjas. La base se guarda en `t/{tenant}/generated/{draft_id}/base/…` con su fila en `image_assets`: sha256, `vendor_task_id`, modelo, `rendered_prompt`, versión de prompt. Una fila con `vendor_task_id` nunca se vuelve a enviar (ADR 41 §8). Si la base trae letras o botones inventados, se regenera **una sola vez**, y ese tope lo impone una clave única sobre el intento, no un `if`.
2. **La capa de texto es de Claude, sobre un esquema cerrado.** `LayerSpec` (pydantic) con título, subtítulo, frase de llamado opcional y bloques de información; `layout_id` sale de un enum versionado que comparten Python y `packages/render/src/props.ts`, con largo máximo por campo según el diseño. Claude ve la foto base. El precio entra **por referencia** (`product_id` → precio del catálogo al componer), nunca como texto escrito por el modelo; hoy no se dibuja (decisión #10), pero el esquema ya no permite inventarlo.
3. **Remotion compone.** Las props de Remotion se derivan de la capa, no al revés: cambiar de diseño no vuelve a llamar a Claude. Una pieza de imagen es una foto fija; un carrusel son N fotos fijas con contador de diapositiva. Cada foto se convierte a JPEG con las dimensiones exactas y se guarda en R2 como `slide-N.jpg` en cuanto termina, antes de que el limpiador del render la borre.
4. **Sin composición en Pillow y sin respaldo en Pillow.** `render_ad_slides`, `render_carousel_slide` y `text_layer` se borran (m-25017293). Pillow sigue solo para convertir y reducir archivos.

### 2.1 Dónde vive la capa: tabla nueva `piece_layers`

La crea la migración de m-25017278 (número tomado contra `origin/main` al abrir el PR; hoy el head es 0151), según `qualify-migration`:

| Columna | Para qué |
|---|---|
| `id`, `tenant_id` + RLS (`ENABLE` + `FORCE` + política con `NULLIF`) en la misma revisión | Aislamiento por negocio |
| `brand_id` con FK compuesta a `brands (id, tenant_id)` | Que la capa no cruce negocios ni por error de código |
| `draft_id`, `version_id` → `piece_versions`, `position` | Una capa por diapositiva y por revisión |
| `layout_id`, `layout_version`, `spec` JSONB, `spec_sha256` | El contenido y su huella para la clave del render |
| `base_asset_id` → `image_assets` | La foto que vio Claude y sobre la que se compone |
| `source` (`model` · `owner_edit` · `owner_photo`), `parent_layer_id`, `created_by` | Quién la escribió y de qué capa sale |
| `model_id`, `prompt_version`, `pipeline_version` | Procedencia |
| `UNIQUE (tenant_id, version_id, position)` | Idempotencia: un reintento no crea otra capa |

**Recomponer** es una revisión nueva en `piece_versions` (`UNIQUE (tenant_id, draft_id, revision)` ya existe) que reusa la misma base, más una fila nueva en `piece_layers` con `parent_layer_id`. La acción lleva una clave de petición: el doble clic no crea otra versión.

**La edición de texto del dueño** cuenta como entrada manual (excepción del 2026-11-04, `docs/arquitectura.md` §1.6) **solo en los campos que él tecleó**: la fila lleva `source='owner_edit'` y `created_by`, y por `parent_layer_id` conserva la procedencia del modelo para los campos que no tocó. No se apoya solo en Langfuse, porque la capa alimenta una publicación y «Repetir este diseño» (m-25017310) la va a reusar.

**Volumen [H]:** ~30 piezas de imagen o carrusel por negocio al mes × ~3 capas (diapositivas y ediciones) ≈ 1 100 filas por negocio al año → ~110 000 al año con 100 negocios. Lejos de los umbrales de ADR 31.

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
| `layer` | `BaseImage`(s), brief, catálogo | `LayerSpec` por diapositiva + revisión de la base | — (nuevo) |
| `compose` | `LayerSpec` + `BaseImage` | Fotos fijas en R2, filas en `image_assets` y `template_runs` | Partes de `_ad_image` y `_carousel` |
| `check` | Fotos compuestas | Aprobada o una capa corregida | — (nuevo) |

En `media.py` queda solo el despacho por `ContentKind`. La etapa `compose` habla con `RemotionRenderClient`; no reusa `_template` tal cual. Cada etapa se puede probar sin red con dobles de los clientes.

### 2.4 Composición en cola: estados y reintento

- **Estados de la pieza:** `base_ready` → `composing` → `compose_waiting` (con `next_attempt_at` y espera creciente) → `ready` · `failed`.
- **Trabajo en `creative_jobs`** (ADR 41) con `kind='compose'` y la clave natural `(tenant_id, draft_id, kind, revision, position)`. El `jobId` del render sale de §2.2. Seedream no se vuelve a llamar: la base está guardada con su `vendor_task_id`.
- **Lo que ve el dueño:** «La estamos terminando». Si se pasa de un tope (se propone 30 min), la pieza queda fallida, **sin descontar otra vez del cupo**, con un botón para reintentar. El chequeo de salud del render con alerta lo hace m-25017289.
- **Precondición:** la cola de ADR 41 activa para imagen y carrusel en producción, y el despachador `inline` retirado para esos tipos, **antes** de borrar Pillow. Los hilos de `InlineDispatcher` mueren al reiniciar y no dejan reintento durable.

### 2.5 Claude con las fotos del cliente

- **Transporte:** imágenes en base64 o con URL firmada de vida corta; nunca una URL pública.
- **Trazas:** Langfuse corre en la máquina de Deivid (riesgo ya registrado). Los bloques de imagen se **enmascaran** en la traza; queda solo el sha256 y la clave de R2. Sin esto, fotos de clientes terminan en un equipo personal.
- **Menos llamadas:** la revisión «¿tiene letras o botones inventados?» de la base (m-25017279) es un campo de la misma llamada que escribe la capa (m-25017283). Quedan **dos** llamadas con imagen por pieza: capa y revisión de la imagen compuesta (m-25017287). En el carrusel, una sola llamada con las N fotos devuelve las N capas, y una sola llamada revisa las N compuestas.
- **Costo y latencia [H]:** una imagen de ~1080×1350 son ~1 500–1 700 tokens de entrada; ~US$0,01–0,02 y 3–8 s por llamada con Sonnet; menos con Haiku. Dos llamadas ≈ US$0,02–0,04 por pieza, contra US$0,035–0,045 de la foto base. Todo va detrás del medidor por turno y fuera de la petición web.
- **«Usar mi foto»:** no consume creación (decisión #12), pero las llamadas a Claude se registran en el libro de consumo con su costo en dólares y 0 creaciones. La pieza guarda su propia copia normalizada de la foto del dueño en `generated/{draft_id}/base/`, para que recomponer no dependa de que la foto siga en la Galería (ADR 47).
- **BytePlus:** las fotos de clientes solo van a presets que no ceden datos (pro y lite confirmados el 2026-11-12). Flash no está verificado: no se usa con fotos ni referencias de clientes hasta confirmarlo.

## 3. Condiciones que tienen que cumplirse (bloqueantes)

1. **Orden m-25017293 / m-25017299.** `render_carousel_slide` (Pillow) lo usa el camino viejo de carrusel dentro de `STATIC_FLYER` (`media.py:5564`), que se retira en m-25017299 (Fase 2), y m-25017299 depende de m-25017293. Hay que elegir: m-25017293 pasa ese camino a Remotion, o m-25017299 va antes. Tal como está, las dependencias se contradicen.
2. **Clave del render con contenido.** Ningún trabajo nuevo usa `_template_job_id`; la clave es la de §2.2.
3. **Cola en producción.** m-25017293 no empieza hasta que m-25017277 confirme `QUALIFY_CREATIVE_DISPATCHER=queue` (o equivalente) para imagen y carrusel en producción.
4. **Recomponer anula la aprobación y tiene fecha de vencimiento.** Recomponer invalida `confirmed_sha256` (ADR 32 doble aprobación, ADR 41 §3.3) y la pieza vuelve a «por aprobar». Después de la purga de ADR 39 (90 días desde el último uso), o para piezas anteriores a este pipeline (no tienen base guardada), no hay recomposición: la pantalla ofrece «Crear otra».

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
| Revisión de la base | **A. Campo dentro de la llamada de la capa** | **Recomendada** | Claude ya está viendo la foto: ahorra una llamada con imagen |
| | B. Llamada aparte (Haiku) | Alternativa | Más precisa quizá, una llamada más; la decide m-25017292 |
| Piezas viejas | **A. No se recomponen; «Crear otra» con el pipeline nuevo** | **Elegida** | No hay base guardada; la imagen publicada y su procedencia siguen en R2 y en la fila |
| | B. Conservar Pillow para reproducirlas | Descartada | Contradice la decisión del fundador y deja un motor vivo solo para el pasado |

## 5. Encaje con las reglas y los ADR firmados

- **ADR 31:** ningún almacén nuevo; una tabla más en el Postgres que ya corre.
- **Sin runtime nuevo:** Remotion es el único runtime de Node del repo y ya está en producción.
- **ADR 32:** la doble aprobación se mantiene; recomponer vuelve a pedir aprobación.
- **ADR 39:** la base vive bajo `generated/{draft_id}/` y se purga con la pieza; «recomponer gratis» vale mientras exista.
- **ADR 41:** la composición es un trabajo más de `creative_jobs`; el reintento no cobra dos veces.
- **Asistido, nunca autónomo:** nada se publica sin que el dueño apruebe la imagen final.
- **Procedencia e idempotencia:** §2.1 y §2.2.

## 6. Consecuencias

- **Positivas.** Ningún texto inventado dentro de la foto; la capa se puede editar y recomponer gratis sin otra llamada a Seedream; un solo motor de diseño; procedencia completa por diapositiva; `media.py` adelgaza.
- **Negativas.** Una tabla y un estado más; dos llamadas a Claude con imagen por pieza (~US$0,02–0,04 [H]); la pieza depende del servicio de render: si cae, espera en la cola en lugar de salir con Pillow; las piezas viejas dejan de poder editarse.
- **Operación.** El perfil `render` (1536m, concurrencia 1) pasa a estar en el camino de toda imagen. Si un carrusel de 10 tarda demasiado, el tope de diapositivas se ajusta (decisión #14).

## 7. Qué queda abierto para la medición (m-25017292)

- Tiempo por foto fija, sobrecosto por trabajo y memoria máxima en el perfil `render`; tiempo de un carrusel de 10 a concurrencia 1 → tope de diapositivas.
- Tokens, costo y latencia reales de cada llamada de Claude con imagen; si juntar la revisión de la base con la capa pierde precisión.
- Seedream pro, lite o flash por calidad y costo, con la verificación previa de que flash no cede datos.
- Si la revisión de la imagen compuesta (m-25017287) sube el costo por pieza: el fundador decide si se activa.

## 8. Lo que el fundador tiene que elegir para firmar

1. **Orden de m-25017293 y m-25017299:** (a) m-25017293 pasa el camino viejo de carrusel a Remotion — *recomendado*; o (b) m-25017299 va antes.
2. **Revisión de la foto base:** (a) campo dentro de la llamada de la capa — *recomendado*; o (b) llamada aparte con Haiku.
3. **Revisión de la imagen compuesta (m-25017287):** (a) apagada por defecto hasta ver la medición — *recomendado*; o (b) activa desde el inicio.
4. **Tope de espera de la composición en cola** antes de dar la pieza por fallida: 30 min propuesto, o otro valor.
5. **Piezas viejas:** (a) no se recomponen, solo «Crear otra» — *recomendado*; o (b) se le pide al equipo un camino especial.
6. **Foto del dueño en «Usar mi foto»:** (a) la pieza guarda su propia copia — *recomendado*; o (b) referencia la foto de la Galería, aceptando que si el dueño la borra ya no se puede recomponer.
7. **Modelo de la foto base** (pregunta 2 de la épica): se elige con la medición; flash solo si se confirma que no cede datos.

## 9. Qué lo reabriría

- La medición muestra que un trabajo con varios puertos ahorra más de ~2 s por diapositiva sin perder la reanudación.
- El render, con concurrencia 1, deja piezas en «La estamos terminando» más de 5 min en el p95 durante una semana: subir la memoria o la concurrencia con su tabla de opciones.
- El costo de Claude con imagen pasa de US$0,05 por pieza en la medición.
- Un cliente pide editar piezas anteriores a este pipeline más de una vez.
- `piece_layers` pasa de 5 M filas.
