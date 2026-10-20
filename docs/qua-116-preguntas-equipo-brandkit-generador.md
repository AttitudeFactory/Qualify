# QUA-116 — Preguntas para el equipo, vistas desde el Brand Kit y el generador de contenido

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Fecha:** 2026-10-05 · **Estado:** análisis, sin código · **Pedido:** «revisa el ticket 106 e investiga las preguntas al equipo solo desde la perspectiva del Brand Kit y del generador de contenido».

> **Aclaración de ticket.** QUA-106 (Discovery de Stories con tendencias) está en Done desde el 2026-09-21 y no tiene sección de preguntas al equipo; sus «preguntas de investigación» quedaron cerradas en su comentario final. Las **«Preguntas para el equipo»** están en **QUA-116** (Motor de Plantillas con Remotion, In Progress, actualizado hoy) y en `docs/ux-plantillas-en-el-post.md` §5. Este doc responde a esas siete. El único cruce con QUA-106 es su pregunta 8 («generar contenido propio para la Story en vez de reutilizar terceros»): la salida `story` del motor de plantillas es exactamente ese contenido propio.

**Fuentes verificadas en disco:** `origin/main` @ `86382cd` (docs de PR #64, `publishing/`, `planner/publishable.py`, `creative/`), rama `origin/feat/motor-plantillas-remotion` (PR #65: `qualify_creative/render/*`, `catalog/*`, `packages/render/*`, `creative/media.py`), y este worktree (`feat/brand-kit-before-login`: `brand_kit_store.py`, `brand_context.py`, `brand_finish.py`, `brief_ai.py`, `creative_wizard_pages.py`).

---

## 1. Hallazgos que condicionan las respuestas

Ninguno está en el ticket tal cual; los tres primeros afectan la demo del domingo 11.

### H1. Las salidas fijas salen en PNG y el publicador solo acepta JPEG

- `packages/render/server/jobs.mjs:10-11` → `still: '.png'`, `image/png`; `renderStill(... imageFormat: 'png')` en la línea 230.
- `publishing/staging.py:94-109` (main) → cualquier imagen, incluida la Story de imagen de QUA-113, se rechaza si no es `image/jpeg` con bytes JPEG, ≤ 8 MB. Es regla de Meta, no nuestra.

Consecuencia: **feed 4:5 e historia 9:16 del paquete no se pueden publicar hoy por ningún camino de Qualify**, ni por el Planificador ni por `/publish` manual, aunque el contrato por salida llegara mañana. Cierre barato, dos opciones: (a) `renderStill` con `imageFormat: 'jpeg'` + `jpegQuality` en el servicio de render, o (b) del lado Python, `qualify_creative.photo.normalize.export_for_instagram` (ya existe, ya exporta JPEG limpio) al recibir la salida. (b) no toca Node y reutiliza lo que el catálogo ya usa.

### H2. Los pilotos son «un tenant con dos marcas» y la app resuelve siempre la marca más antigua

- `Qualify/creative_provider.py:116-121` → `default_brand_id` = `ORDER BY created_at` y toma la primera. El docstring lo dice: «One brand per tenant is the signed model».
- No existe selector de marca en el shell ni en `CreativeState` (`_brand_id` solo se cachea desde `default_brand_id`).

Consecuencia: Brand Kit, catálogo, `/create`, borradores y Planificador verán **solo Bianki o solo Polette** (la que se creó primero). «Refrescar el brand kit y el catálogo de las dos marcas» (plan §1 y §7) no es posible desde la UI sin un selector de marca o dos tenants. Es una decisión de modelo (`diseno-motor-contenido-marca.md` §7.7, «la contrapartida de 1 tenant = 1 brand»), pero para la semana la salida pragmática es **dos tenants** (uno por marca) y dejar el selector para después.

### H3. El Brand Kit no tiene tipografía; las plantillas caen a Noto Sans

- `brand_kits` (modelo en `creative/models.py:42-86`) no tiene ninguna columna de fuentes; el wizard tampoco la pregunta (cero ocurrencias de «tipograf» en `creative_wizard_pages.py`).
- `render/props.py` → `BrandProps.fonts = dict(fonts or {})` y `media.py` llama a `build_props` sin `fonts`. `packages/render/src/fonts.ts` → `FALLBACK_HEADING = FALLBACK_BODY = 'Noto Sans'`.

El plan §2.3 asumía «el brand kit dice Poppins». Hoy nadie lo dice. Para el domingo basta un par de fuentes por marca en algún sitio (columna `fonts` JSONB en `brand_kits`, o un valor en `brand_kit_details.profile` sin migración) y pasarlo a `build_props`. A medio plazo es un paso del wizard («¿Tienes tipografía?», con Google Fonts por nombre), igual que la paleta sale del logo.

### H4. El nicho existe en el Brand Kit pero no llega al router

- El wizard guarda el rubro en `brand_kit_details.connect.rubro_text` / `sector` y la categoría del perfil en `profile.category` (`brand_finish.py:254-255`). `brand_context.py` ya lo lee para el prompt de copy (`BrandContext.sector`).
- `creative/media.py:652-658` construye `PostFacts` **sin** `niche`, `has_avatar` ni `wants_presenter`. `manifest.fits_niche(None)` devuelve `True`, así que hoy toda plantilla encaja con todo.

El hueco «la marca no tiene campo de nicho» del ticket es más chico de lo que suena: el dato está, falta normalizarlo a la clave que usan los manifiestos (`"shawarma"`, `"helado"`) y pasarlo. Sin migración. Lo que sí hay que decidir es quién mapea «rubro libre» → clave de nicho (una tabla pequeña en `qualify_creative`, o la misma IA que ya selecciona hashtags).

### H5. «Avatar del negocio» no existe como dato de marca

- Lo único persistido por marca es la voz clonada (`brand_voice_clones`, migración 0032). El look de HeyGen se elige en cada pieza (`CreativeState.avatar_look_id`, en sesión).
- Por eso la regla 1 del router nunca dispara (`PostFacts.has_avatar` queda en `False`).

Desde el Brand Kit, el «presentador» (look + voz clonada + consentimiento) es un atributo de la marca, no de un post. Vive naturalmente al lado de «Tu voz». No es de esta semana, pero es la respuesta de fondo al hueco del ticket.

### H6. El copy no conoce los puertos de la plantilla

- `CopyPayload.hook` tiene `HOOK_MAX = 60`, que coincide con el puerto `hook` de `promo_producto` (`max: 60`) por casualidad. `cta` no tiene límite en `CopyPayload` y el puerto pide ≤ 40. `price_line` (≤ 24) sale del catálogo, no del copy.
- `brand/render.py` arma el prompt por tipo de contenido y lee `kit.length_targets`, pero no recibe el manifiesto. `validate_props` corre **después** del copy (`media.py:_template`), así que un CTA largo falla el draft con `INVALID_PARAMETERS` cuando el copy ya se pagó.

Cierre: pasar los `max` de los puertos al prompt (el mismo mecanismo que `length_targets`), o recortar en `build_props` con aviso. Los «prompts por nicho × ángulo» del plan (jueves 8) son el sitio natural.

### H7. Las fotos del generador no se normalizan; las del catálogo sí

- `CreativeState._save_uploads` guarda el archivo crudo en disco (`uploads/<tenant>/…`).
- `CatalogService.add_media` normaliza siempre (EXIF, HEIC, P3 → sRGB, export JPEG) y marca `normalized=True`.

Relevante para la pregunta 5: una foto subida desde el post que «también se guarda en el producto» debe entrar por `add_media`, no copiando la clave cruda.

### H8. Lo que no bloquea, para no confundirlo con un hueco

- **Nombre de marca.** La composición imprime `brands.name` (`brand_names.py`). En el flujo antes del login la marca se llama «Mi marca» hasta `register_business`; no importa porque catálogo y `/create` exigen sesión.
- **Logo y paleta.** `brand_finish.py` sube el logo a R2 y `replace_assets` escribe `brand_kits.logo_asset_key`; `palette_rgb` sale del logo. `build_props` ya los usa. (El §7 de `ui-brandkit-wizard.md`, «ningún camino escribe la clave», quedó viejo.)
- **Tono.** `_tone_word` traduce los 4 ejes del kit a palabras para la composición. Funciona.
- **Producto por nombre.** `DbProductCatalog.products_for` empareja `product_ref` por texto; el ticket ya lo lista. `product_id` en el brief lo cierra.

---

## 2. Las siete preguntas

### P1. ¿Se aprueba el paquete entero con exclusión por salida, o salida por salida?

**Qué hay.** La aprobación es del `ContentDraft` (FSM `DraftStatus`, `approved_revision`), una sola puerta humana (diseño §2.1, HITL #2). El estado por salida ya existe en backend: `image_assets.output_port` y `template_runs.outputs[port].status` (migración 0038).

**Desde el generador:** paquete entero + exclusión. Tres aprobaciones por post rompen la economía del generador: el copy es uno, la receta es una, `template_run` es una. Lo que sí debe hacer el generador solo: una salida con `status = failed` en `template_runs` queda **excluida por defecto** (no espera a que el humano la quite) y «Reintentar» por salida es un evento de servicio nuevo (reutiliza las props guardadas en `template_runs.props`).

**Desde el Brand Kit:** sin impacto.

### P2. Si el contrato por salida no llega al domingo, ¿plan B = Reel por el Planificador y feed/historia a mano?

**Qué hay.** El Reel es MP4 H.264 → publicable como `category=reel` hoy. Feed e historia son **PNG** (H1) → no los publica ni el Planificador ni `/publish`.

**Desde el generador:** el plan B del ticket, tal cual, termina en «bajar PNG y subir desde el teléfono a Instagram», no en `/publish`. Con la exportación JPEG (H1, trabajo de horas) el plan B honesto pasa a ser: Reel por el Planificador; feed e historia descargadas en JPEG y publicadas por `/publish` (feed de imagen e **historia de imagen** ya funcionan ahí desde QUA-113). Es decir: **el JPEG hace falta en el plan A y en el plan B**; conviene hacerlo el lunes, antes que cualquier otra cosa del lado Python.

**Desde el Brand Kit:** H2. Si las dos marcas comparten tenant, el domingo solo se demuestra una.

### P3. ¿«post» en lugar de «pieza» en el sidebar y el glosario?

**Qué hay.** `design-system.md` §7.2 no define «pieza»; para «mención» dice *no usar «post»*, o sea que «post» ya está reservado, por omisión, para **lo propio**. QUA-109/110/111 ya llaman «POST» a la entidad. En el generador «pieza» vive en `_HEADINGS` de `content_generator.py`, en «Crear pieza» (`ui/layout.py:64`) y en `creative_pages.py`.

**Desde el generador:** sí, «post», y para todo, no solo para los paquetes. Un guion para creador es un post sin salidas renderizadas; dos palabras para la misma fila de `content_drafts` es lo que el glosario prohíbe. Costo: strings en cuatro pantallas y los tests que afirman sobre `NAV_ITEMS`.

**Desde el Brand Kit:** el wizard no usa «pieza» ni «post» (habla de «publicaciones» del perfil leído); no cambia.

### P4. ¿Catálogo como «Productos» dentro de Publicas, o bajo Negocio?

**Qué hay.** El Brand Kit **no pregunta por productos** (cero ocurrencias en el wizard; `brand_kit_details` no los guarda). El kit es voz y look; el catálogo es lo que se vende. Además viven en momentos distintos: el kit se hace antes del login (invitado, `/brand/start`), el catálogo exige sesión. El comentario de `ui/layout.py:79-80` («ambos son lo que la marca es») es la única atadura, y es de layout.

**Desde el Brand Kit:** Publicas, como «Productos». No le quita nada al kit y evita que el dueño busque las fotos del shawarma en «Negocio». Lo que sí importa más que la isla es H2: con dos marcas, tanto Brand Kit como Productos necesitan saber **de qué marca** están hablando; hoy ninguno lo muestra.

### P5. ¿Las fotos subidas desde el post se guardan en el producto?

**Qué hay.** `build_props` ya mezcla las subidas del brief (`media.product_keys`) con las del catálogo, deduplicadas, con tope del puerto. H7: las del brief van crudas; las del catálogo normalizadas.

**Desde el generador:** sí, sin preguntar, **pero por `CatalogService.add_media`** (normaliza, asigna principal si es la primera, calcula dimensiones). El brief guarda entonces la clave que devuelve el catálogo, no la local. Dos reglas: si el post no tiene producto («Sin producto: horarios, fidelidad…»), las fotos quedan en el post; y la subida desde el post no reordena la foto principal del producto. Efecto lateral bueno: la validación del manifiesto (`min: 2` fotos) deja de fallar por fotos HEIC que Remotion no abre.

**Desde el Brand Kit:** sin impacto. (Los elementos de marca —logo, versiones, extras— siguen en `brand_kit_assets`, separados de los productos. Correcto: no mezclar el brandboard con el catálogo.)

### P6. Historia en la demo: ¿imagen fija «solo descarga», o historia en video desde la composición?

**Qué hay.** `promo_producto.story` es un still (`kind: still`, 1080×1920) → PNG (H1). La historia de **imagen** sí la publica `PublishService` desde QUA-113 (JPEG, 8 MB, en local exige `QUALIFY_PUBLIC_MEDIA_BASE_URL` + túnel al 8010), pero el mapa del Planificador la rechaza (`planner/publishable.py:126-128`, «the publisher has no image story» — comentario viejo). La historia de **video** se publica hoy de punta a punta (Planificador incluido) sin tocar nada.

**Desde el generador:** historia **en video desde la misma composición** para la demo. Razones: (1) es la única salida que llega a Instagram por el Planificador sin tocar publicador ni mapa; (2) un render más cuesta ~1 s de still menos y ~8 s de video más, a costo cero en self-host; (3) el guion, la paleta y el tono del kit ya están en la composición del Reel, solo cambia el encuadre. La historia de imagen queda como segunda salida del mismo puerto cuando entre el JPEG (H1) y se actualice el mapa (dos líneas). «Solo descarga» en PNG es la peor de las tres: ni se publica ni se puede subir por `/publish`.

**Desde el Brand Kit:** sin impacto; la tipografía (H3) se ve igual de ausente en las tres salidas.

### P7. ¿Se adelanta el contrato por salida al lunes, antes del rediseño de `/create`?

**Qué hay.** El rediseño a tres pantallas (`docs/ux-plantillas-en-el-post.md` §3.3) es UI sobre estado que ya existe (`selected_product_id`, `brief_content_type`, `recipe_items`, `generator_steps`). El único punto compartido con el backend es `product_id` en el brief (pequeño). El contrato por salida (`calendar_events.output_port`, `PostSummary.outputs`) es de arquitecto + pipeline y no toca `/create`.

**Desde el generador:** sí al contrato el lunes, **sin** que `/create` espere: son equipos y archivos distintos. Lo que el lado generador/Brand Kit necesita el lunes, en este orden, porque sin ello el domingo no hay paquete publicable:

| # | Qué | Dónde | Tamaño |
|---|---|---|---|
| 1 | Stills en JPEG (H1) | `jobs.mjs` o `export_for_instagram` al recibir la salida | horas |
| 2 | Una marca por tenant para los pilotos, o selector de marca (H2) | seed / `default_brand_id` / shell | decisión + horas |
| 3 | `product_id` en el brief (ticket §4.1) | `ContentBrief`, `products_for` | S |
| 4 | Nicho desde `brand_kit_details` → `PostFacts.niche` (H4) | `media.py:_pick_template` + mapa rubro→nicho | S |
| 5 | Fuentes por marca → `build_props(fonts=…)` (H3) | `brand_kits` o `profile`; editor del kit | S–M |
| 6 | Límites de los puertos en el prompt de copy (H6) | `brand/render.py` | S |

Los puntos 4–6 son los que hacen verdad «la marca entra por el brand kit» (plan §1): hoy entran el logo, la paleta y el tono; faltan la tipografía y el nicho.

---

## 3. Lo que este doc no decide

- El contrato por salida en Planificador/publicación (§3.5 del doc UX): es de arquitecto + pipeline.
- Si dos marcas por tenant se resuelven con selector o con dos tenants: es del fundador; aquí solo se mide que hoy no funciona.
- Cómo se pregunta la tipografía en el wizard del Brand Kit (es un paso nuevo; conviene después del domingo).
