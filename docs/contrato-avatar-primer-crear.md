# Contrato y diseño: el avatar desde el primer «Crear» del Clip (opción B)

**Ticket:** m-25119867 (hijo de m-25112920, épica m-25026566). **Fase:** 2. El PR 1 («crear y esperar») está construido en la rama `feat/m-25119867-avatar-primer-crear`. El PR 2 trae «Intentar de nuevo», «Quitar avatar» y la espera de 72 h.
**Redactado por:** creative-engineer, 2026-11-25, sobre `main` en `06aed410`. Lo actualizó el mismo día con las respuestas de Deivid (§3) y lo que pidió la sesión del editor (§1.5–§1.7).

**En qué PR queda cada cosa:**

| Qué | PR |
|---|---|
| `create_clip_with_blocks` con todas las reglas de §1.1 y los errores de §1.3 | **PR 1** |
| `clip_wait` (§1.2), con `actions` vacías y `wait_until=None` | **PR 1** |
| La espera del Clip (`ClipBlocksWait`), el latido y el despertador (`mark_parent_dirty`) | **PR 1** |
| P3 (bloques sin texto propio), P5 (3 s propios) y P6 (cupo de un Clip fallido) | **PR 1** |
| Del plan a la receta real, con los tiempos corridos y `clip_too_long` | **PR 1** |
| Uniones junto a un avatar = solo «Corte», en la opción B, en `place_block` y en el armado (§1.7) | **PR 1** |
| Lecturas antes de «Crear» (§1.5): tope del día, cupo, costo, interruptores, avatar de la marca | **PR 1** |
| `retry_block`, `remove_block`, `actions` en `BlockWait`, `wait_until` y la falla a las 72 h (P1, P2) | **PR 2** |
| `recreate` de un Clip de la opción B (R6) | **PR 2** |
| Aviso activo (correo o WhatsApp) cuando el video esté listo (§1.6) | pendiente, fuera de los dos PR |
**Reglas de partida:** ADR 50 §9 (`docs/adr-50-video-efectos-por-pasos.md`, firmado por Deivid el 2026-11-25) y ADR 44 (`docs/diseno-video-por-planos.md`).
**Pantalla:** m-25112921 (carril B). Este documento es su contrato.

## 0. Qué existe hoy (leído en el código)

- **Opción A ya está en `main`** (`packages/api/src/qualify_api/creative/clip_avatar.py`). `ClipAvatarService.create_block` agrega un bloque a un Clip que ya existe y está en `generated` o `rejected`. `place_block` mete su video en la receta y arma la versión siguiente. Ninguna pantalla los llama todavía: no hay ruta HTTP. Reflex llama a los servicios de Python directamente (`Qualify/creative_provider.py`).
- **El «Crear» del editor** llama a `ContentService.create_draft(tenant_id, brand_id, brief, user_id)` con un `ContentBrief` cuya receta local va en `brief.media.segments`. Son `SourceSegment` con `key`, `start_s`, `end_s`, `speed`, `rotate` y `kind` (`video` o `photo`). El modo es `clip_reference_mode="local"`. `PartRecipe` solo es la vista del motor (`recipe_of(brief)`): el editor no la manda.
- **Cómo se arma un Clip local.** `create_draft` lo encola con `QueueDispatcher`. Su fila de `creative_jobs` queda `queued` (con `not_before=UNPREPARED`) hasta que la preparación del worker (`PipelinePreparation`, fase `generation`) lo arma. Mientras esa fila esté `queued`, el reaper (`dispatch.reap_stale_drafts`) no toca el borrador.
- **Cómo espera hoy un video local.** `LocalSourceNormalizing` y `LocalAssemblyWait` son `LocalVideoWait`, es decir, `CheckpointError`. El worker suelta la preparación sin marcarla hecha, la aparta `retry_after_s` (`heavy_video.hold`) y la retoma en otra pasada. No se lee nada, no se escribe nada y no se cobra nada.
- **Cómo espera el video por partes (ADR 44).** El padre nunca espera en `drafting` (riesgo N1, `parts.mark_parent_dirty`). Cuando una parte termina o falla, la unión del padre se abre como corrida `join` en `creative_pipeline_runs`. El worker la hace en `BackgroundJoins` con `lease_kept` (renovación cada `LEASE / 3`, y `pipeline.LEASE` dura 10 min). La única espera en `drafting` que hay dentro de ADR 44 es la de VE-13. Una parte «Sigue a la anterior» espera a la anterior con `GenerationDeferred`: su trabajo sigue `queued`, el reaper no la toca, y `release_next_extend` la despierta.
- **El reaper.** Falla un borrador `drafting` cuyo `updated_at` (latido, `record_progress`) tiene más de 20 min. No toca los que tienen una tarea de proveedor pendiente (menos de 49 h) ni los que tienen un trabajo `queued` en `creative_jobs`. Para OmniHuman espera `OMNIHUMAN_REAP_AFTER_MINUTES`.
- **Hoy un hijo hereda el texto del padre.** En `ContentService._generate_brief`, todo borrador con `parent_draft_id` lee el texto del padre (`_inherited_copy`). Si el padre todavía no tiene texto, lanza `ValueError` y el hijo falla. Esto choca con la opción B (pregunta P3).

## 1. Contrato de pantalla para m-25112921 (carril B)

> Esta sección se reenvía tal cual. Los nombres de campos, estados y códigos son los que va a tener el código. Los textos en español son los que el servidor devuelve en `owner_message` / `owner_text`: la pantalla los muestra tal cual y decide por el `code`, nunca por el texto.

### 1.1 «Crear» con avatares: qué manda la pantalla

Entrada nueva, aparte de `create_draft`, que no cambia. Así la opción A y los videos sueltos siguen igual.

```python
ClipAvatarService.create_clip_with_blocks(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    brief: ContentBrief,                       # el mismo brief local que hoy va a create_draft
    blocks: Sequence[ClipAvatarPlacement],     # 1 a 3 bloques (ver límites)
    request_key: UUID | None = None,           # el mismo de «Crear»: un doble toque devuelve lo mismo
) -> ClipWithBlocks                            # clip_id y los block_ids en orden de `slot`
```

`ClipAvatarPlacement` (nuevo, en `clip_avatar.py`):

| Campo | Tipo | Límite / regla | Qué es |
|---|---|---|---|
| `block` | `AvatarBlockRequest` | ya existe (opción A) | Lo que dice y quién lo dice. Abajo están sus campos. |
| `at` | `int` | `0 ≤ at ≤ len(brief.media.segments)` | Antes de cuál foto o video del dueño va el avatar. `0` es al principio y `len(segments)` es al final. Si dos bloques tienen el mismo `at`, van en el orden de la lista. |

`AvatarBlockRequest` (ya existe, sin cambios):

| Campo | Tipo | Límite / regla |
|---|---|---|
| `kind` | `"presenter"` \| `"animated"` | El interruptor de ese tipo tiene que estar encendido (`QUALIFY_CLIP_AVATAR_PRESENTER` / `QUALIFY_CLIP_AVATAR_ANIMATED`). |
| `script` | `str` | De 1 a `SCRIPT_MAX` (2000) caracteres, sin quedar vacío al quitar espacios, y **30 s como máximo leídos en voz alta**. La estimación es `script_seconds`: unos 15 caracteres por segundo, o sea unos 450 caracteres. |
| `voice_id` | `str \| None` | `"brand"` (la voz de la marca), un id público de Seed Speech o `None` (la voz por defecto). |
| `avatar_prompt` | `str` | Obligatorio con `presenter`, porque el presentador siempre se describe. |
| `avatar_image_key` | `str \| None` | Solo con `animated`: la imagen del dueño, con `avatar_rights_confirmed=True`. |
| `avatar_rights_confirmed` | `bool` | Obligatorio con una imagen propia. |
| `use_brand_avatar` | `bool` | Solo con `animated`: el avatar de la marca. Va solo, sin `avatar_image_key`. |
| `background_key`, `product_keys` | opcionales | Lo mismo que en un video de avatar suelto. |

Reglas de la receta completa en el primer «Crear» (el servidor las revisa todas antes de escribir nada):

| Regla | Límite |
|---|---|
| Cuántos bloques | De 1 a 3 por «Crear». El techo de la tabla es `AVATAR_BLOCK_SLOTS` = 6, pero el tope diario de 3 manda. |
| Tipo de Clip | Solo un Clip local («tus fotos y videos», `clip_reference_mode="local"`). |
| Fotos y videos del dueño | Al menos uno, y **sin los avatares tienen que durar 3 s o más**. Así, quitar un avatar nunca deja un video imposible de armar (pregunta P5). |
| Tramos en total | Las fotos y videos del dueño más los bloques: como máximo `SEGMENTS_MAX` = 8. |
| Largo del Clip | Las fotos y videos a su velocidad, más el largo estimado de cada guion: de 3 a 60 s. |
| Textos y efectos sobre el Clip | Sus tiempos se cuentan sobre la línea de tiempo que la pantalla dibuja con cada avatar a su **largo estimado** (`script_seconds`). Al armar, el servidor los corre según el largo real (§2.4). |
| Velocidad del avatar | Siempre ×1. El avatar no tiene «Velocidad» ni «Recortar» en el editor. |

La pantalla puede pedir el largo estimado al servidor con `clip_avatar.script_seconds(script)`, sin red ni costo, para dibujar el bloque en la línea de tiempo mientras el dueño escribe.

### 1.2 Lo que la pantalla lee mientras el Clip espera

Lectura nueva, sin costo, por `tenant_session` (RLS):

```python
ClipAvatarService.clip_wait(*, tenant_id: UUID, clip_id: UUID) -> ClipWait | None
```

`None` quiere decir que no es un Clip de este negocio o que no tiene avatares de la opción B.

`ClipWait`:

| Campo | Tipo | Qué es |
|---|---|---|
| `clip_id` | `UUID` | |
| `clip_status` | `str` | El estado del borrador: `drafting`, `generated`, `rejected`, `approved`, `failed`… |
| `state` | `"waiting_blocks"` \| `"block_failed"` \| `"assembling"` \| `"ready"` \| `"failed"` | Lo que la pantalla muestra (tabla de abajo). |
| `owner_text` | `str` | La frase de ese estado, en español. |
| `wait_until` | `datetime \| None` | Solo con `block_failed`: hasta cuándo espera el Clip a que el dueño elija. Son 72 h (P2, decidido). **En el PR 1 siempre es `None`**: llega con el PR 2. |
| `blocks` | `tuple[BlockWait, ...]` | Cada avatar, en orden de `slot`. |

`BlockWait`:

| Campo | Tipo | Qué es |
|---|---|---|
| `block_id` | `UUID` | El borrador hijo `avatar_video` o `animated_avatar_video`. |
| `slot` | `int` (1–6) | Su lugar bajo el Clip. No cambia. |
| `at` | `int` | Antes de cuál foto o video del dueño va (lo que mandó la pantalla). |
| `kind` | `"presenter"` \| `"animated"` | |
| `state` | `"creating"` \| `"ready"` \| `"failed"` \| `"removed"` | `creating` es el borrador en `drafting`, `ready` es `generated`, `failed` es `failed` y `removed` es un bloque que el dueño quitó (`part_removed_at`). |
| `seconds_estimate` | `int` | Lo que se estimó del guion. |
| `seconds` | `float \| None` | El largo real, cuando ya está `ready`. |
| `failure_code` | `str \| None` | Con `failed`: el `failure_reason` del bloque (`timeout`, `provider_error`, `invalid_parameters`, `budget_exceeded`…). |
| `owner_text` | `str \| None` | Con `failed`: el `failure_detail` del bloque, ya en español. Si no tiene uno, el texto de §1.3 según el código. |
| `actions` | `tuple["retry" \| "remove", ...]` | Lo que la pantalla puede ofrecer. Con `failed` son las dos, y con cualquier otro estado ninguna. **En el PR 1 siempre viene vacío**, porque las acciones llegan con el PR 2. Mientras tanto, la pantalla muestra el bloque fallido con su texto y sin botones. |

Cómo se calcula `state` (se deriva de las filas cada vez que se consulta; no se guarda):

| `clip_status` | Avatares (sin contar los `removed`) | `state` | `owner_text` |
|---|---|---|---|
| `drafting` | alguno `creating` y ninguno `failed` | `waiting_blocks` | «Estamos creando tu avatar. Tu video se arma cuando esté listo.» Con dos o más: «Estamos creando tus avatares. Tu video se arma cuando estén listos.» |
| `drafting` | alguno `failed` | `block_failed` | «Uno de tus avatares no salió. Inténtalo de nuevo o quítalo, y armamos tu video con lo demás.» |
| `drafting` | todos `ready`, o no queda ninguno | `assembling` | «Tus avatares están listos. Estamos armando tu video.» Si no queda ninguno: «Estamos armando tu video.» |
| `generated`, `rejected`, `approved`, `staged`, `published` | — | `ready` | «Tu video está listo.» |
| `failed` | — | `failed` | El `failure_detail` del Clip, como en cualquier pieza que falla. |

**Cómo se consulta.** Mientras `state` sea `waiting_blocks` o `assembling`, cada 3 s con la pantalla abierta, igual que el estado del análisis de reels (ADR 44 §13.3). Con `block_failed` la pantalla deja de consultar, porque solo cambia con una acción del dueño o al vencer `wait_until`. Con `ready` o `failed` también deja de consultar. Si el dueño sale y vuelve, la fila guarda el estado: la Galería ve el Clip como una pieza en `drafting` y puede llamar a `clip_wait` para la etiqueta de la tarjeta.

### 1.3 Errores del servidor y sus textos

Se lanzan **antes de escribir nada y antes de cualquier llamada de pago**. Todos traen `code` (estable) y `owner_message` (español). Los que se refieren a un bloque traen además `block: int`, su posición en la lista `blocks` (desde 0), para que la pantalla marque cuál es.

| `code` | Clase | Texto | De dónde sale |
|---|---|---|---|
| `switched_off` | `ClipAvatarRefused` | «Este tipo de avatar todavía no está disponible. Quítalo para crear tu video.» | **Nuevo**. El de la opción A termina en «Tu video queda como está.», pero en la opción B todavía no hay video. |
| `too_long` | `ClipAvatarRefused` | «Lo que dice el avatar dura más de 30 segundos. Déjalo en unas 7 frases cortas y vuelve a intentarlo.» | El de §9, ya en el código (`TOO_LONG_TEXT`). |
| `avatar_daily_cap_reached` | `AvatarDailyCapReached` | Si ya se crearon 3 hoy: «Ya creaste 3 avatares hoy. Mañana puedes crear más.» | Texto exacto de §9. El código de la opción A le agrega «Tu video queda guardado como está.», que en B no aplica. |
| `avatar_daily_cap_reached` | `AvatarDailyCapReached` | Si quedan menos de los que se piden: «Hoy puedes crear 1 avatar más. Quita los demás para crear tu video.» / «Hoy puedes crear 2 avatares más. Quita uno para crear tu video.» | **Nuevo**. El texto de §9 diría algo falso, por ejemplo «Ya creaste 3» cuando el dueño lleva 1 y pide 3. Trae `used`, `cap` y `asking`. |
| `clip_not_local` | `ClipAvatarRefused` | «Solo puedes agregar un avatar a un video armado con tus fotos y videos.» | Ya existe (`CLIP_NOT_LOCAL_TEXT`). |
| `avatar_needs_own_media` | `ClipAvatarRefused` | «Agrega al menos 3 segundos de tus fotos o videos para acompañar al avatar.» | **Nuevo** (pregunta P5). |
| `too_many_blocks` | `ClipAvatarRefused` | «Puedes poner hasta 3 avatares en un video.» | **Nuevo**. |
| `no_brand_avatar` | `ClipAvatarRefused` | «Tu marca todavía no tiene su avatar. Créalo en Tu marca, o describe aquí cómo quieres que se vea.» | Ya existe (`NO_BRAND_AVATAR_TEXT`). |
| `avatar_file_not_owned` | `ClipAvatarRefused` | «No pudimos usar esa imagen. Súbela de nuevo.» | **Nuevo** (§1.5). Pasa cuando la imagen, el fondo o un producto del bloque no son del negocio. |
| `avatar_join_cut_only` | `ClipAvatarRefused` | «Junto a un avatar, la unión solo puede ser «Corte», para que su voz se escuche completa. Cámbiala y vuelve a intentarlo.» | **Nuevo** (§1.7). |
| `local_length_out_of_range`, `too_many_segments`, `texts_overlap`… | `RecipeRefused` | Los textos que la pantalla ya usa para esos códigos (`Qualify/clip_editor_vm.py`). | Ya existen. El largo cuenta los avatares por su largo estimado. |
| `local_daily_cap_reached` | el de EF-15 | El de hoy. | Ya existe. |
| — | `NotEnoughCreations` | Los textos de cupo que la pantalla ya usa. | Ya existe. Se revisan juntos los segundos de todos los avatares nuevos y los de todos los bloques de la marca que todavía no se cobraron (§9). |
| — | `BrandNotReady`, `RouteBlockedByPolicy` | Los de hoy. | Ya existen. |

Textos del estado de un bloque (`BlockWait.owner_text`) cuando el bloque no trae `failure_detail` propio:

| `failure_code` | Texto |
|---|---|
| `timeout` | «Tu avatar tardó demasiado y no salió. Puedes intentarlo de nuevo o quitarlo.» (**nuevo**) |
| cualquier otro sin detalle | «Tu avatar no salió. Puedes intentarlo de nuevo o quitarlo.» (**nuevo**) |

Los detalles que ya escribe el productor siguen igual. Por ejemplo `BLOCK_TOO_LONG_TEXT` («Al leerlo en voz alta, lo que dice el avatar pasó de 30 segundos…») y los de `avatar_failure_text`.

Errores de las acciones (§1.4):

| `code` | Texto | |
|---|---|---|
| `block_not_failed` | «Este avatar no falló, así que no hace falta intentarlo de nuevo.» | **Nuevo** |
| `block_not_removable` | «Solo puedes quitar un avatar que no salió.» | **Nuevo** |
| `clip_not_waiting` | «Tu video ya no está esperando a este avatar.» | **Nuevo** |
| `switched_off`, `too_long`, `avatar_daily_cap_reached` y `NotEnoughCreations` | Los de la tabla de arriba. | Al intentar de nuevo se revisan otra vez, antes de pagar. |

Botones (verbos, `qualify-copy-es`): «Intentar de nuevo», «Quitar avatar».

### 1.4 Si un bloque falla: intentar de nuevo o quitarlo

- **El Clip no se queda colgado ni lo falla el reaper.** Sigue en `drafting` con su trabajo `queued` y con latido (§2.3). `clip_wait` dice `block_failed` y trae las acciones. Los demás avatares siguen y no se pierden.
- **«Intentar de nuevo» (PR 2):**

  ```python
  ClipAvatarService.retry_block(*, tenant_id, user_id, clip_id, block_id,
                                request: AvatarBlockRequest | None = None) -> UUID
  ```

  Sin `request`, el mismo bloque se hace otra vez tal como estaba. Con `request`, se cambia antes lo que dice, la voz o quién lo dice, pero no el tipo. El bloque pasa a una revisión nueva en `drafting` (borde `PART_RETRY`, como `part_actions.retry_part`) y su fila de cobro de esa revisión se escribe en cero. Antes de escribir nada se revisan el interruptor, los 30 s, el tope diario (pregunta P1) y el cupo de §9. Devuelve el `block_id`. El Clip vuelve a `waiting_blocks`.
- **«Quitar avatar» (PR 2):**

  ```python
  ClipAvatarService.remove_block(*, tenant_id, user_id, clip_id, block_id) -> bool
  ```

  Solo sirve con un bloque `failed`. Marca `part_removed_at`, como «Quitar parte»: no se borra nada y no se cobra nada. El bloque sale del plan del Clip. Devuelve `True` si lo quitó y `False` si ya estaba quitado (se puede llamar dos veces). Si los demás avatares ya están listos, o no queda ninguno, el Clip pasa a `assembling` y se arma con lo que hay.
- **Si el dueño no elige.** Pasado `wait_until`, el Clip falla con `failure_reason="avatar_block_failed"`. Se devuelve lo que se cobró por el Clip, nada de los bloques se cobra, y el `failure_detail` dice: «Tu video no se armó porque uno de tus avatares no salió y no elegiste qué hacer. Créalo de nuevo cuando quieras.» (**nuevo**). La espera dura 72 h (P2, decidido) y queda en el **PR 2**. Hasta entonces, un Clip con un avatar fallido sigue esperando, con latido. Los dos interruptores están apagados en todos los entornos, así que no le pasa a ningún cliente.
- **Un bloque que salió pero no cabe** (con su largo real el Clip pasa de 60 s) se muestra como fallido con `failure_code="clip_too_long"` y el texto «Con tu avatar, el video pasa de 60 segundos. Acorta lo que dice el avatar o quítalo.» (**nuevo**). También se muestra fallido un bloque cuyo tipo se apagó mientras el Clip esperaba (`switched_off`).

### 1.5 Lo que la pantalla puede leer antes de «Crear» (todo en el PR 1, gratis y sin red)

Todo es de `qualify_api.creative.clip_avatar`, salvo donde se indica otro módulo.

| Qué | Cómo se lee | Qué devuelve |
|---|---|---|
| **Uniones junto a un avatar** | No hay lectura: la regla está en §1.7. | Con la regla, la pantalla ofrece solo «Corte» en las uniones que tocan un avatar. |
| **Avatares que quedan hoy** | `ClipAvatarService.avatar_daily_left(tenant_id=…)` | `(used, cap)`: los avatares creados hoy (el día del negocio) y el tope del servidor (`AVATAR_DAILY_CAP` = 3). Lo que queda es `cap − used`. |
| **Segundos reservados y libres** | `ClipAvatarService.avatar_quota(tenant_id=…, brand_id=…)` → `AvatarQuota \| None` | `pending_blocks` y `pending_seconds` son los bloques de la marca hechos y todavía sin cobrar, en cualquier Clip. `video_in_seconds` dice si el plan cuenta segundos o videos. `left` es lo que queda del mes y `free` es lo que un «Crear» nuevo todavía puede pedir: `left` menos lo reservado. Con `None` no hay cupo mensual, y con `left=None` el mes no pone límite. |
| **Costo antes de «Crear»** | `plan_seconds(blocks)`, una función pura que recibe una lista de `AvatarBlockRequest` o de `ClipAvatarPlacement`. | Los segundos que esos avatares descuentan al aprobar el Clip. Es **la misma suma** con la que el servidor revisa el cupo: el «Crear» pasa si `plan_seconds(...) ≤ avatar_quota().free`, o si el número de bloques es `≤ free` cuando el plan cuenta videos. |
| **Interruptores por tipo** | `avatar_kind_enabled(kind)`, con `kind` en `"presenter"` / `"animated"` | `True` si el servidor acepta ese tipo. Con `False` la pantalla pinta «Próximamente». |
| **Si la marca ya tiene avatar** | `ClipAvatarService.brand_avatar_ready(tenant_id=…, brand_id=…)` | `True` si el avatar de la marca está listo (`brand_avatar`, estado READY). Solo así sirve `use_brand_avatar=True`. |
| **Voz de la marca** | Ya existe: `Qualify/creative_provider.brand_clone_voice(tenant_id, brand_id)` | La voz clonada de la marca como opción `{"id": "brand", "name": "Tu voz · …"}` cuando está lista, y si no, `None`. El servidor la resuelve con `voice_access.BRAND_VOICE`. |
| **Voces públicas de Seed Speech** | Ya existe: `Qualify/creative_provider.public_voices()` y `voice_options(...)` | La lista cerrada `qualify_creative.adapters.byteplus_speech.PUBLIC_SPANISH_VOICES`, con `id`, nombre para mostrar («Nombre · estilo») y género. Sale del código y no llama a la red ni a ningún servicio pagado. El servidor solo acepta esos ids (`PUBLIC_VOICE_IDS`). |
| **Imagen propia del avatar animado** | Ya existe: `CreativeState.handle_avatar_upload` → `_save_uploads` → `save_upload` (CM-9) | La imagen se guarda en R2 bajo `t/<negocio>/uploads/…` y su clave va en `avatar_image_key`. El servidor revisa en el «Crear», antes de escribir nada, que la clave sea del negocio (`media.owned_by`). Si no lo es, rechaza con `avatar_file_not_owned` y el texto «No pudimos usar esa imagen. Súbela de nuevo.» (**nuevo**, revisar con ux-designer). El productor la revisa otra vez antes de leerla (`_key_problems`). |
| **Casilla de derechos** (`avatar_rights_confirmed`) | Ya existe, en `Qualify/content_generator.py` | «Tengo derecho a animar esta imagen (no es la foto de una persona real sin su permiso).» Si falta: «Confirma que tienes derecho a animar esa imagen.» (`creative_state`). Se reusa tal cual y no es texto nuevo. |

### 1.6 Aviso cuando el video esté listo (punto 9, decidido por Deivid)

Después de «Crear», el dueño va a «Por aprobar». La tarjeta del Clip muestra el estado con `clip_wait`.

- **Lo que ya existe y sirve tal cual.** Cuando el Clip pasa a `generated`, entra solo en la cuenta «Para aprobar» de Inicio (`qualify_api.home.summary`, `drafts_to_approve`: borradores `generated` sin padre) y en la lista «Por aprobar». Es el mismo aviso que tiene hoy un video por partes cuando terminan sus partes: no hay correo, WhatsApp ni notificación activa para eso. El correo de la mañana (`mail/final_summary`) es de los **finales** aprobados, no de los borradores.
- **Lo que no existe.** Un aviso activo de «Tu video está listo», por correo o por WhatsApp, sería un módulo nuevo (otro canal, otra plantilla y su baja). **Queda pendiente** y fuera de los dos PR. Si Deivid lo quiere, tendría esta forma:
  - lo dispara el paso de `drafting` a `generated` de un Clip de la opción B;
  - sale por correo, con la misma baja que el resumen de la mañana;
  - el texto sería «Tu video con avatar está listo. Ábrelo en Por aprobar para revisarlo.», que va por `qualify-copy-es` y hay que pasarlo por ux-designer.

### 1.7 Uniones junto a un avatar: solo «Corte» (decidido por Deivid, PR 1)

- **La regla.** La unión de un avatar con el tramo anterior, y la del tramo que sigue al avatar, solo pueden ser «Corte». Si no, el servidor rechaza con `code="avatar_join_cut_only"` y el texto «Junto a un avatar, la unión solo puede ser «Corte», para que su voz se escuche completa. Cámbiala y vuelve a intentarlo.» (**nuevo**, revisar con ux-designer). Un fundido mezclaría hasta 0,8 s del final de la voz con el tramo siguiente.
- **Dónde se revisa (los tres caminos):**
  - en el primer «Crear» (opción B), antes de escribir nada;
  - en `place_block` (opción A): el tramo delante del que entra el avatar no puede traer una unión que no sea corte;
  - en el armado local, para cualquier camino que llegue ahí. El Clip falla sin leer nada, con el mismo texto.
- **Sobre qué campo.** La regla lee la unión real que trajo #804 (`main` en 1d7b2beb, ADR 50 §10): `SourceSegment.transition_in`, que es la unión de un tramo con el anterior. La función es `clip_avatar.avatar_join_problems`, y revisa la unión del avatar y la del tramo que sigue. `None` y un `corte` explícito cuentan como corte. `ClipAvatarPlacement` no trae `transition_in`: un avatar del primer «Crear» siempre entra con corte.
- **Con el interruptor apagado o encendido.** La regla no depende de `QUALIFY_CLIP_BLOCK_TRANSITIONS`. Responde antes que la regla del interruptor (`recipe_unavailable`), así que el dueño lee siempre `avatar_join_cut_only`. Es la condición para encenderlo. Las pruebas corren con los dos valores: `test_the_first_create_refuses_a_blend_next_to_an_avatar` (avatar antes de un tramo con fundido, y avatar primero), `test_the_first_create_takes_a_cut_next_to_an_avatar` y `test_place_block_refuses_a_blend_into_an_avatar`. Con el interruptor encendido, `test_the_assembly_refuses_a_blend_next_to_an_avatar_whatever_path_put_it_there` prueba el armado: apagado, la receta ya la rechaza antes.
- **Al convertir el plan en tramos (§2.4)** las uniones de los tramos del dueño quedan como él las dejó. El tramo del avatar entra sin `transition_in`, es decir con corte. Las uniones que tocan un avatar ya son corte, porque lo demás se rechazó en el «Crear».
- **Si un bloque sigue creándose mucho tiempo**, no hace falta hacer nada. El bloque mismo termina siempre: sale, falla, o el reaper lo falla con `timeout` después de la espera de OmniHuman o de las 49 h de la tarea. Entonces el Clip pasa a `block_failed`.

## 2. Diseño de backend

### 2.1 Orden de creación (`create_clip_with_blocks`)

Todo lo que puede rechazar va antes de escribir. Todo lo que escribe va en **una sola transacción**. Las llamadas de pago solo empiezan en el worker, después del commit.

1. **Reglas puras, sin leer nada:**
   - el interruptor de **cada** tipo pedido (`refuse_if_off`) → `switched_off`;
   - cada guion estimado en 30 s o menos → `too_long` con `block`;
   - de 1 a 3 bloques → `too_many_blocks`;
   - cada `at` dentro de los límites, y el brief es local (`is_local_recipe`) → `clip_not_local`;
   - las fotos y videos del dueño suman 3 s o más → `avatar_needs_own_media`;
   - los tramos con los bloques son 8 o menos, el largo estimado está entre 3 y 60 s, y los textos y efectos caben en él (`validate_recipe` sobre la receta con los bloques puestos con su largo estimado) → `RecipeRefused`;
   - el brief no trae `clip_avatar_plan` ni `clip_avatar_block`, que solo los pone el servidor.
2. **Lecturas sin escribir** (las de `create_draft`, en su mismo orden): Brand Kit y voz (`BrandNotReady`), la política de imagen (`RouteBlockedByPolicy`), `refuse_unbuilt_recipe`, `refuse_local_without_queue` (la opción B solo existe con la cola, como todo Clip local), el avatar de la marca si se pide (`no_brand_avatar`). Después se arma el brief de cada bloque con `block_brief(clip_brief, request)`, que ya existe, y se pasa por `prepare_new_generation`, que sella el brief sin llamar a ningún proveedor.
3. **Una transacción `tenant_unit_of_work`**, con el candado del negocio (`pg_advisory_xact_lock(hashtext('clip_avatar_cap'), …)`, el mismo de la opción A):
   1. `request_key` ya usado → se devuelve el mismo Clip con sus bloques y no se despacha nada;
   2. el tope local de EF-15 (`check_local_daily_cap`);
   3. el tope diario de avatares con `asking=N` (`check_avatar_daily_cap`, que ya acepta `asking`);
   4. el cupo de §9: los segundos de los N bloques más los de todos los bloques de la marca sin cobrar (`pending_block_seconds`), o N + los pendientes cuando el plan cuenta videos y no segundos;
   5. el cupo del propio Clip (`balance.shortfall(weight_for(clip))`, como `create_draft`);
   6. se inserta el Clip en `drafting` con `media.clip_avatar_plan` y su fila de cobro de la revisión 1;
   7. se insertan los N bloques bajo el Clip (`parent_draft_id`, `part_index` = slot 1..N), cada uno con su fila de cobro en cero (`weight_for` → 0).
4. **Después del commit** (`after_tenant_commit`): se despachan los bloques y después el Clip. El Clip entra a la cola con su trabajo `queued`. Su primera pasada ve los bloques en `creating` y espera (§2.3).

Por qué no se reusa `create_block` N veces: ese método exige un Clip ya `generated` (`_CLIP_READY`), cobra el tope por bloque en transacciones separadas y no crea el Clip. Lo que sí se reusa son sus piezas: `block_brief`, `_insert`, `_refuse_without_quota`, `check_avatar_daily_cap`, `_lock` y `_savepoint`. `create_draft` no cambia. Su única novedad es rechazar un brief que traiga `clip_avatar_plan`.

**Cómo quedó en el PR 1.** El orden es este, con tres diferencias:

- Los pasos 2 y 3.2 a 3.5 viven en `ContentService.new_draft_inputs`, que se sacó de `create_draft` sin cambiar su comportamiento. Recibe `recipe_brief`: la receta con los bloques puestos con su largo estimado (`clip_avatar.virtual_brief`).
- El cupo del Clip se revisa fuera del candado, como en `create_draft`. Si otro pedido gasta el cupo en medio, `charge` lanza `NotEnoughCreations` dentro de la transacción y no queda nada escrito.
- Se agregó la regla de uniones (§1.7) entre los pasos 1 y 2.

### 2.2 Dónde se valida cada regla del §9

| Regla del §9 | Al crear (antes de escribir y de pagar) | Al intentar de nuevo | En el worker (antes de pagar OmniHuman) | Al armar el Clip |
|---|---|---|---|---|
| Interruptor por tipo | §2.1 paso 1, para cada bloque | sí | — (el bloque ya existe; apagar el interruptor no corta un pago en curso, igual que en A) | En el portón de espera (`plan_states`): si un interruptor se apagó mientras el Clip esperaba, el bloque de ese tipo se trata como `failed` con `switched_off` (no se guarda; se lee del interruptor del worker) y el dueño lo quita. Nunca se pega en silencio. |
| 30 s como máximo | paso 1, con la estimación del guion | sí | sí, con la voz real (`block_max_seconds`, ya existe) → el bloque falla con `BLOCK_TOO_LONG_TEXT` | — |
| Tope de 3 al día | paso 3.3, `asking=N`, con el candado | sí (pregunta P1) | — | — |
| Cupo de todos los bloques sin cobrar | paso 3.4 | sí | la reserva de la cola (`_validate_reservation`) | — |
| Cobro al aprobar | — | — | — | Sin cambios: al aprobar el Clip, `clip_block_charges` lee los bloques en `segments`, por eso el plan se convierte en tramos reales al armar (§2.4). |
| `ai_generated=True` | — | — | — | Sin cambios: el armado local ve los bloques como `GeneratedSource` con `block=True` (`ai_stretches`). |
| OmniHuman 1.5 | — | — | sí (`block_model_problem`, ya existe) | — |
| Solo ×1 y solo de este Clip | el bloque se pone a ×1 por construcción | — | — | `stretch_problem`, ya existe |

### 2.3 Cómo espera el Clip: latido e idempotencia

Es el patrón de espera que ya usa el armado local (`LocalVideoWait`) más el despertador de VE-13 (`release_next_extend`):

- **El portón** (en el PR 1 es `ContentService._clip_plan_ready`, que llama a `clip_avatar.plan_gate`). En `_generate`, antes del texto, de la traza y del armado, si el brief del Clip trae plan se leen sus bloques una vez (más el video de cada bloque hecho):
  - si algún bloque está en `drafting`, o alguno falló y `wait_until` todavía no venció: se escribe el latido (`record_progress`) y se lanza `ClipBlocksWait(LocalVideoWait)` con `retry_after_s = 30`. El worker suelta la corrida sin marcarla hecha y la aparta 30 s (`hold`). No se lee nada más, no se escribe nada más y no se cobra nada;
  - si alguno falló y `wait_until` ya venció: el Clip falla con `avatar_block_failed` (§1.4) y se devuelve lo cobrado. **Esto queda en el PR 2.** En el PR 1 un bloque fallido deja al Clip esperando, con latido;
  - si todos están `generated` (o no queda ninguno): se pasa al texto y al armado local de siempre (§2.4).
- **Latido cada 60 s o menos.** El worker da una vuelta cada 2 s (`DEFAULT_INTERVAL_SECONDS`) y el Clip queda apartado 30 s, así que `updated_at` se escribe más o menos cada 32 s. Además, el reaper no lo toca porque su trabajo sigue `queued`, igual que un Clip que espera la normalización de sus videos o una parte VE-13. El latido es una segunda protección y es lo que se lee para saber que está vivo.
- **El despertador.** `mark_parent_dirty` hoy solo abre la unión de un `shot_video`. Se extiende: si el que termina, falla o se quita es un bloque cuyo Clip está en `drafting` con un plan, se marca sucia la corrida `generation` del Clip a su revisión. No hace falta para que funcione, porque la consulta cada 30 s basta, pero así el Clip arranca apenas termina el último bloque y no hasta 30 s después.
- **Reinicio del worker.** La espera no guarda nada: se deriva de las filas de los bloques en cada pasada. Lo único que vive en memoria es el `hold`, y perderlo solo adelanta un intento. Convertir el plan en tramos se escribe en **su propia transacción con valla** (`ContentService._replace_clip_brief`): `PipelineStore.fence` sobre la concesión de la corrida, y `SELECT … FOR UPDATE` del Clip, que tiene que seguir en `drafting` y en la misma revisión. Si algo de eso cambió, se lanza `CheckpointError` y no se escribe nada. Después, el armado escribe el video en la suya (`pipeline_assembly`). Si el proceso muere entre las dos, la próxima pasada encuentra el brief nuevo, ya sin plan, y arma como un Clip de la opción A: no hay nada que deshacer. Esto se apartó de lo que proponía este documento (una sola transacción con el video), porque así el texto y el armado no cambian. Lo que el armado ya guardó en R2 se encuentra por su clave y no se duplica. El texto de Claude se repite desde su paso guardado (`CheckpointRouter`) y no se paga dos veces.
- **Dos pestañas o dos pasadas.** `PipelineStore.acquire` da la corrida a un solo worker. «Intentar de nuevo» y «Quitar avatar» bloquean el Clip (`SELECT … FOR UPDATE`) y luego el bloque, en ese orden, igual que `part_changing`. Así nunca se cruzan con el armado, que también bloquea el Clip con `FOR UPDATE` en `pipeline_assembly`.

### 2.4 Del plan a la receta real (al armar)

- En una transacción con valla (§2.3), el Clip pasa a un **brief nuevo** (`replace_brief`, como «Crear otra versión»). En ese brief, cada bloque del plan es un `SourceSegment` de su video (`block_segment`: de 0 a su largo real, a ×1), en su `at`, y `clip_avatar_plan` queda vacío. El brief que mandó el dueño se conserva como registro de lo que pidió. Desde ese momento el Clip es igual a uno de la opción A: el cobro al aprobar, «Pedir otra versión», `place_block` y el editor funcionan sin cambios.
- **Uniones** (ADR 50 §10, en `main` desde 1d7b2beb). Cada tramo del dueño conserva su `transition_in`. El tramo de cada avatar entra sin unión (corte), y el tramo que le sigue ya es corte por la regla de §1.7, revisada en el «Crear». Por eso la conversión nunca crea ni cambia una unión, y la regla de espacio de §10 (`transitions_longer_than_block`) la vuelve a revisar el armado con los largos reales.
- **Textos y efectos** (`clip_avatar.fit_plan`, una función pura). El dueño los ubicó sobre la línea de tiempo con el largo estimado de cada avatar. Al pasar al largo real, la línea de tiempo se convierte por tramos:
  - un tiempo que cae sobre una foto o un video del dueño se corre lo que los avatares anteriores duran de más o de menos;
  - un tiempo que cae dentro de un avatar conserva su lugar proporcional en él;
  - lo que queda pasado el final se recorta a él, y lo que empezaría en el final o después se quita;
  - un efecto sin tramo (todo el video) no cambia.
- **Si con el largo real el Clip pasa de 60 s.** La voz real salió más larga que la estimación, pero cada bloque ya está limitado a 30 s. El Clip no se arma con un recorte silencioso. La entrada del plan de ese bloque queda con `refused="clip_too_long"`, en un brief nuevo y con valla. El bloque se muestra fallido con el texto «Con tu avatar, el video pasa de 60 segundos. Acorta lo que dice el avatar o quítalo.» (**nuevo**) y el Clip espera al dueño. El bloque mismo sigue en `generated`, porque la FSM no tiene un paso de `generated` a `failed`. Es raro: la estimación usa 15 caracteres por segundo y la voz real casi siempre lee más rápido. Si el bloque salió `generated` sin video guardado, pasa lo mismo con `refused="block_not_ready"`.
- **Procedencia (regla 6).** El brief que mandó el dueño, con los tiempos estimados, queda como fila propia. El brief nuevo trae los tiempos reales y el registro dice cuántos textos o efectos se movieron o se quitaron. El asset del Clip guarda en `params.local.avatar_blocks` lo mismo que en la opción A (bloque, revisión, asset, proveedor, modelo y largo). No se agregó un `params.local.recipe_shift`: comparar los dos briefs da lo mismo sin tocar el armado.

### 2.5 Tablas y campos

| Qué | Dónde | Cambio |
|---|---|---|
| El plan del Clip | `content_briefs.media.clip_avatar_plan` (JSON): `[{slot, at, seconds_estimate, refused}]` (`ClipAvatarSlot`) | Campo nuevo de `MediaInputs` en `packages/creative`, vacío por defecto: los briefs guardados se leen igual. Solo lo pone el servidor, como `clip_avatar_block`. |
| Los bloques | `content_drafts` (`parent_draft_id`, `part_index`, `part_removed_at`), `content_briefs.media.clip_avatar_block` | Ya existen (0119, m-24985192, §9). |
| Cobro y tope | `creation_charges`, `creative_usage_events` | Ya existen. |
| Espera y despertador | `creative_pipeline_runs`, `creative_jobs` | Ya existen. |
| Razón de falla | `content_drafts.failure_reason` (texto) | Valor nuevo `avatar_block_failed` en `FailureReason` (`qualify_creative.enums`), en el **PR 2**. La columna no tiene restricción de valores. |
| P6 | `PostgresClipAvatarStore.pending_block_seconds` | Un bloque cuyo Clip está `failed` no cuenta. Se lee del estado: no se marca nada. Esto vale también para la opción A, porque un Clip `failed` no se aprueba. |

**Migración: no hizo falta en el PR 1.** Todo cabe en columnas que ya existen y en el JSON del brief. La consulta nueva, por hijos de un Clip, usa el índice único `(tenant_id, parent_draft_id, part_index)` de la 0119. Si al implementar apareciera un índice necesario, sería la **0183** (la 0182 está reservada por otra sesión; en `main` la última es la `0181_ad_carousel_sources`) y la escribiría backend-engineer.

### 2.6 Riesgos

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Un bloque hereda el texto del Clip (`_inherited_copy`), pero en la opción B el Clip no tiene texto cuando sus bloques se generan, así que el bloque fallaría siempre. | Resuelto en el PR 1 (P3): si el Clip todavía no tiene texto, el bloque lleva una variante vacía, con costo 0 y `inherited_from: null`. Su guion son las palabras del dueño. Enmienda §14 del ADR 44, `[PROPUESTO]`. |
| R2 | Un Clip en `drafting` no tiene video que mostrar. Si el dueño nunca elige, el Clip quedaría esperando para siempre. | `wait_until` (P2) y después `avatar_block_failed`, con devolución. La espera mientras los bloques se crean tiene fin porque cada bloque termina (reaper de OmniHuman, 49 h de la tarea). |
| R3 | Los bloques de un Clip que falló antes de armarse siguen contando en el cupo según §9 («deja de contar al aprobarse su Clip o con la retención»). Un Clip que falló no se aprueba nunca. | Resuelto en el PR 1 (P6): un bloque cuyo Clip está `failed` deja de contar. Se lee del estado del Clip, sin marcar nada. Enmienda §11 del ADR 50, `[PROPUESTO]`. |
| R4 | La voz real dura distinto de lo estimado: los textos se corren y el Clip podría pasar de 60 s. | §2.4: se corren y se recortan con registro, y lo que pasa de 60 s se vuelve una falla del bloque que el dueño resuelve. Pruebas de la función pura con largos más cortos y más largos. |
| R5 | La cola de OmniHuman es de 1 tarea a la vez (ADR 44 §6): 3 bloques hacen fila de unos 12 min o más, y el Clip espera todo ese tiempo. | Lo dice la pantalla («Estamos creando tus avatares…»). El tope de 3 al día lo acota. No cuesta más, solo tiempo. |
| R6 | «Crearla otra vez» (`recreate`) sobre un Clip de la opción B que falló copiaría `clip_avatar_plan` por `create_draft`. | `create_draft` rechaza un brief con plan (§2.1). `recreate` de un Clip de la opción B se rechaza con «Vuelve a crear este video desde el editor.» (**nuevo**). |
| R7 | Que la espera se rompa sin que nadie lo vea. | Registro `creative.pipeline.local_waits reason=ClipBlocksWait` (ya existe para las otras esperas), y una prueba que simula el reinicio: se pierde el `hold` y el resultado es el mismo. |
| R8 | Si un interruptor se apaga mientras el Clip espera, sus bloques de ese tipo ya están pagados o en curso. | §2.2: el bloque se trata como fallido con `switched_off` y el dueño lo quita. Nunca se pega un bloque de un tipo apagado. |

### 2.7 Pruebas (sin llamadas pagadas: dobles)

- `create_clip_with_blocks`: con los interruptores apagados, más de 30 s, el tope diario y el cupo, rechaza sin filas y sin despachar nada (memoria y `-m db`). Con un `request_key` repetido devuelve lo mismo. Dos pedidos a la vez no pasan juntos el tope.
- La espera: un bloque en `drafting` lleva a `ClipBlocksWait` con latido y sin leer el armado. Un bloque `failed` da `block_failed`, y con `wait_until` vencido el Clip falla y se devuelve lo cobrado. Con todos `generated`, el armado recibe la receta con los tramos y `ai_generated=True`. Con el `hold` perdido (reinicio) el resultado es el mismo.
- El reaper: un Clip que espera más de 20 min con su trabajo `queued` no se falla.
- Las acciones: `retry_block` y `remove_block`, con sus rechazos; después de quitar el último fallido, el Clip se arma.
- La conversión de tiempos (§2.4) como función pura.
- La opción A (`test_clip_avatar*`) y los `avatar_video` sueltos, sin cambios y en verde.

### 2.8 Tamaño

| Pieza | Tamaño |
|---|---|
| `clip_avatar_plan` en `MediaInputs` y su validación | S |
| `create_clip_with_blocks` (validación, transacción, despacho) | M |
| El portón de espera, el despertador y la falla por vencimiento | M |
| Del plan a la receta real, con la conversión de tiempos | M |
| `clip_wait`, `retry_block`, `remove_block` | M |
| El texto del bloque (R1) y `recreate` (R6) | S |
| Pruebas (memoria + `-m db`) | L |

**Total: L**, unas 1.500–2.000 líneas con pruebas y 3 a 4 días de trabajo de un agente. Se puede entregar en un PR. Si se prefiere partirlo: (1) crear y esperar, sin acciones, con el Clip que falla apenas un bloque falla; (2) intentar de nuevo, quitar y `wait_until`. La pantalla (m-25112921) puede empezar con el contrato de §1 y dobles de `clip_wait`.

## 3. Preguntas para Deivid

### 3.1 Respondidas el 2026-11-25 (por «creacion de tickets»): todas siguen la recomendación

P1 cuenta para el tope. P2 son 72 h y después `avatar_block_failed` con devolución. P3 es la variante vacía. P4 es la espera en `drafting` con latido. P5 exige 3 s propios. P6 hace que el bloque deje de contar cuando su Clip falla. P3 y P4 quedan como enmienda §14 del ADR 44, y P1, P2, P5 y P6 más la regla de uniones como enmienda §11 del ADR 50. Las dos están `[PROPUESTO]` y esperan la firma de Deivid.

### 3.2 Abierta: efectos y textos sobre el tramo del avatar (punto 8 de la sesión del editor)

Ni el §9 ni el código lo resuelven hoy. El armado local dibuja los textos sobre todo el Clip, avatar incluido, y las capas de efecto (`humo_capa`, `brasas_capa`, `vapor_capa`) también se ponen encima de cualquier tramo. «Cámara rápida» no es un efecto con tramo: es la velocidad del tramo, y el avatar ya va siempre a ×1 (`avatar_block_speed`). La opción A deja hoy poner textos y capas sobre un avatar.

- **Pregunta:** ¿se permiten textos y capas de efecto encima del tramo de un avatar?
- **Recomendación:** permitir los textos, porque se dibujan encima, no tocan la voz y el aviso de lugar de m-25026599 ya advierte cuando un texto tapa algo. Rechazar las capas de efecto que se cruzan con el tramo de un avatar, con un código nuevo `avatar_block_effect`: humo o brasas sobre la cara del presentador se ven mal y no aportan.
- **Mientras tanto:** no se decidió nada. El PR 1 no agrega ninguna regla y se comporta como la opción A.

### 3.3 El texto original de las preguntas (para el registro)

Cada una traía una recomendación.

- **P1. ¿«Intentar de nuevo» cuenta para el tope de 3 avatares al día?** §9 cuenta los **bloques creados** (borradores). Un nuevo intento es otra llamada de pago a OmniHuman sobre el mismo borrador y hoy no contaría, así que con 3 bloques se podrían pagar intentos sin límite. *Recomendación:* sí cuenta, cada intento pagado es un avatar más del día. Hay que contar revisiones y no borradores, y es un cambio pequeño en `blocks_made_today`.
- **P2. ¿Cuánto espera un Clip a que el dueño elija, cuando un avatar falló?** *Recomendación:* 72 h desde la última falla. Después el Clip falla con «Tu video no se armó porque…» y se devuelve lo cobrado.
- **P3 (choca con ADR 44). ¿Los bloques de la opción B pueden no llevar el texto del Clip?** En ADR 44 todo hijo lleva el texto de su padre (`_inherited_copy`). En la opción B el Clip todavía no tiene texto cuando sus bloques se crean. *Recomendación:* sí. El bloque lleva una variante vacía de costo 0, porque nunca se publica solo y el texto lo lleva el Clip.
- **P4 (choca con ADR 44, riesgo N1). ¿Aceptas que el Clip espere en `drafting`?** El padre de un video por partes nunca espera en `drafting`: pasa a `generated` y la unión es una corrida aparte. Un Clip local sin sus avatares no tiene nada que mostrar. *Recomendación:* que espere en `drafting`, con su trabajo `queued`, latido y fin asegurado (P2), como ya espera la parte «Sigue a la anterior» de VE-13 y como espera un Clip local mientras se normalizan sus videos.
- **P5. ¿Puede haber un Clip hecho solo de avatares, sin fotos ni videos del dueño?** La opción A no lo permite, porque el Clip existe antes. *Recomendación:* no. Las fotos y videos del dueño tienen que durar 3 s o más por sí solos, para que quitar un avatar nunca deje un video imposible de armar.
- **P6 (choca con §9). Los bloques de un Clip que falló antes de armarse, ¿siguen contando en el cupo?** §9 dice que un bloque que nunca se colocó deja de contar «al aprobarse su Clip o con la retención». Un Clip que falló no se aprueba nunca, así que sus bloques ocuparían el cupo del dueño hasta la retención. *Recomendación:* que dejen de contar en cuanto el Clip falla (se marcan quitados). Es una enmienda pequeña al §9.

(Los tiempos de textos y efectos (§2.4) y el texto del tope con varios avatares (§1.3) son decisiones de diseño y de redacción que no chocan con nada firmado. Si Deivid prefiere decidirlas, están en esas secciones.)
