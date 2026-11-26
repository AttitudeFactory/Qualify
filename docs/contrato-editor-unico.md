# Contrato del editor único: el bloque «parte con IA»

`[CONSTRUIDO EN PR 1]` · m-25129405 · ADR 50 §13.2 y §13.6 (firmados por Deivid el 2026-11-26) · plan: `docs/plan-editor-unico-clip-partes.md`.

Este documento es el contrato contra el que la sesión del editor hace los PR 6 a 8 (§13.7). El PR 1 solo trae **funciones puras**: no escribe filas, no paga nada y no tiene migración. Crear el Clip con sus partes (PR 2), cambiarlas después de crear (PR 3), aprobar y pedir los finales (PR 4) y pasar del plan a los bloques (PR 5) vienen después.

## 1. El interruptor

| Variable | Valor | Qué hace |
|---|---|---|
| `QUALIFY_CLIP_AI_PARTS` | `off` (por defecto, en `.env.example` y `deploy/.env.prod.example`) | Cualquier bloque `ai_part`, o cualquier entrada de `media.ai_parts`, se rechaza con `switched_off` **antes de leer nada** (ni la biblioteca de efectos). Un Clip sin partes con IA se lee igual que antes. |
| | `on` | Corren las reglas del §3. Hasta el PR 2, `create_draft` igual rechaza el bloque (`recipe_unavailable` en `segments[i]`): el Clip con partes con IA lo crea su propio servicio. |

- Cualquier valor que no sea `on`, `off` o vacío se lee como apagado y queda en el registro.
- La pantalla necesita además `QUALIFY_CLIP_EDITOR` encendido. El servidor solo lee `QUALIFY_CLIP_AI_PARTS`.
- Se enciende con las condiciones del §13.8 y el OK de Deivid.

Código: `qualify_api.creative.video_pipeline.ai_parts` (`CLIP_AI_PARTS_SWITCH`, `clip_ai_parts_on()`).

## 2. La forma del bloque

Un bloque «parte con IA» es un `SourceSegment` más en `media.segments` del Clip, en su lugar de la línea de tiempo:

```json
{
  "kind": "ai_part",
  "key": "ai_part:0",
  "start_s": 0,
  "end_s": 5,
  "speed": 1,
  "rotate": 0,
  "transition_in": {"effect_id": "fundido", "version": 2, "params": {"duration_s": 0.5}}
}
```

- **`key`**: no es un archivo. Es `ai_part:<n>`, donde `n` es la posición (desde 0) de su entrada en `media.ai_parts`. Para armarla: `qualify_creative.schemas.ai_part_key(n)`. Para leerla: `SourceSegment.ai_part_at` (None en una foto o un video propio).
- **`start_s`** es siempre 0 y **`rotate`** siempre 0: el tipo rechaza otra cosa (`ValidationError`; la pantalla nunca los escribe).
- **`end_s`** es lo que dura el bloque en el video: los `seconds` de su entrada (1 a 10, enteros).
- **`speed`** es 1: un bloque con IA va siempre a ×1 (`ai_part_with_speed`).
- **`transition_in`** es su unión con el bloque anterior, igual que la de cualquier bloque (§10 del ADR 50). Sin unión (`None`) es «Corte».

Cada bloque apunta a **una** entrada de `media.ai_parts`, y cada entrada tiene **un** bloque:

```json
"ai_parts": [
  {
    "mode": "reference",
    "seconds": 5,
    "description": "Una arepa recién salida de la plancha",
    "analysis_id": null,
    "shot_indexes": [],
    "trim_start_s": null,
    "trim_end_s": null,
    "clip_image_keys": null,
    "mode_rule_version": 1,
    "mode_reason": "no_source"
  }
]
```

- Cada entrada es un `VideoPartPlan` **sin cambios**: modo (`reference` = «Nueva», `edit` = «Igual al original», `extend` = «Sigue a la anterior»), segundos, recorte, descripción, fotos, análisis del reel, avisos y motivo del modo.
- Una entrada **no** lleva receta propia: sin `effects`, `text_layers`, `segments` ni `transition_in`. Los textos y los efectos van en las pistas del Clip, en segundos del video final; la unión va en el bloque (`ai_part_own_recipe`).
- La guía «Video o audio tuyo» de la parte viaja en la entrada, en `clip_video_keys` y `clip_audio_keys` (§3.1).
- Una entrada nunca es `local` (`ai_part_local`): lo que se hace con fotos y videos del dueño va como bloques propios.
- `SEGMENT_KINDS` sigue siendo `("video", "photo")`: son los tipos que el editor escribe hoy. El editor agrega `ai_part` a su copia del contrato (`Qualify/editor_preview_contract.py`) en el PR 6; la prueba de paridad se ajusta en ese mismo PR.

## 3. Las reglas, sus códigos y sus textos

Todas viven en `validate_recipe` y en `validate_brief_recipe` (la que llama el servidor en cada pedido nuevo, por medio de `refuse_unbuilt_recipe`). Cada problema llega como `RecipeProblem(code, part, field, duration_s)`. En un Clip, `part` es `None` y `field` dice dónde está: `segments[i]` es el bloque `i + 1` que ve el dueño y `ai_parts[n]`, la entrada `n`. Los textos están en `AI_PART_TEXTS` y se piden con `ai_part_text(code)`.

| Código | Cuándo | `field` | Texto para el dueño |
|---|---|---|---|
| `switched_off` | Hay un bloque con IA o una entrada en `ai_parts` y el interruptor está apagado. Sale solo, antes de leer nada | `segments[i]` (o `ai_parts`) | Las partes con IA todavía no están disponibles. Quítalas para crear tu video. |
| `too_many_blocks` | Más de 8 bloques entre propios y con IA (`SEGMENTS_MAX`). **Es defensa:** con 9 bloques el tipo (`MediaInputs.segments`, `max_length=8`) responde antes con `ValidationError`; solo llega aquí una receta armada sin validar. La pantalla nunca debe mandar más de 8 | `segments` | Tu video puede tener hasta 8 fotos, videos o partes con IA. Quita una para seguir. |
| `too_many_ai_children` | Más de 6 hijos de IA: partes con IA + escenas del personaje (+ avatares que el Clip espera). Comparten `part_index` 1 a 6 | `ai_parts` | Entre partes con IA y escenas del personaje puedes tener hasta 6 en un video. Quita una para seguir. |
| `extend_needs_block_before` | Una parte «Sigue a la anterior» al principio del video, sin nada antes (§3.2) | `ai_parts[n].mode` | «Sigue a la anterior» necesita una parte con IA justo antes. Pon esta parte después de una, o elige «Nueva». |
| `extend_after_own_media` | Una parte «Sigue a la anterior» justo después de una foto o un video del dueño: hoy no se puede continuar material propio (§3.2) | `ai_parts[n].mode` | «Sigue a la anterior» solo continúa una parte con IA, no una foto o un video tuyo. Pon una parte con IA justo antes o elige «Nueva». |
| `extend_not_same_moment` | Una parte «Sigue a la anterior» que el plan no partió del mismo momento del reel que la parte con IA de antes (§3.2). Solo se ofrece «Nueva»: «Igual al original» no es una salida segura aquí (§3.2) | `ai_parts[n].mode` | «Sigue a la anterior» solo sirve si esta parte y la anterior salen del mismo momento del video de inspiración. Elige «Nueva». |
| `edit_needs_reel_window` | Una parte «Igual al original» sin el análisis del reel y sus cortes (`analysis_id` y `shot_indexes`) | `ai_parts[n].shot_indexes` | «Igual al original» solo sirve con partes que vienen de un video de inspiración. Elige «Nueva». |
| `ai_part_with_speed` | Un bloque con IA a otra velocidad que ×1 | `segments[i].speed` | Las partes con IA siempre van a velocidad normal. Quita la cámara rápida de esta parte. |
| `own_media_too_short` | El Clip lleva partes con IA **y** escenas o avatares, y menos de 3 s de fotos y videos propios. Un Clip hecho solo de partes con IA es válido | `segments` (con `duration_s`) | Con un personaje en tu video necesitas al menos 3 segundos de tus fotos o videos. Agrega más o alarga los que ya tienes. |
| `ai_parts_mismatch` | Un bloque apunta a una entrada que no existe o que ya usa otro bloque, o una entrada no tiene bloque | `segments[i]` o `ai_parts[n]` | Tuvimos un problema con una de tus partes con IA. Quítala y agrégala de nuevo. |
| `ai_part_length_mismatch` | El bloque no dura los `seconds` de su entrada | `segments[i].end_s` (con `duration_s`) | Una parte con IA no dura lo que marcaste. Cambia sus segundos para que coincidan. |
| `ai_part_outside_clip` | Un bloque con IA o `ai_parts` fuera de un Clip normal armado con bloques (`clip_reference_mode="local"`): en una parte de un video por partes, en un Clip hecho por Seedance o en otro tipo de pieza | `segments[i]` o `ai_parts` | Las partes con IA solo se pueden usar en un video que armas con tus fotos y videos. Quita esta parte para seguir. |
| `ai_part_local` | Exactamente cuando una entrada de `ai_parts` está en modo `local` (hecha con fotos y videos del dueño); ningún otro caso da este código | `ai_parts[n].mode` | Para usar tus fotos y videos no necesitas una parte con IA. Agrégalos directo en tu video. |
| `ai_part_own_recipe` | Una entrada con efectos, textos, tramos o unión propios | `ai_parts[n]` | Los textos, efectos y uniones van en tu video, no dentro de la parte con IA. Quítalos de esta parte y agrégalos al video. |
| `ai_part_guide_type` | «Video o audio tuyo» que no es un video `.mp4`/`.mov` ni un audio `.mp3`/`.wav` (§3.1) | `ai_parts[n].clip_video_keys[i]` o `ai_parts[n].clip_audio_keys[i]` | No podemos usar ese archivo como guía. Sube un video MP4 o MOV, o un audio MP3 o WAV. |
| `malformed_key` / `foreign_key` (de siempre) | Un archivo de guía o una foto de la entrada que no es una ruta del negocio, o que es de otro negocio (§3.1) | `ai_parts[n].clip_video_keys[i]`, `…clip_audio_keys[i]` o `…clip_image_keys[i]` | Los textos de siempre de esos códigos. |

### 3.1 «Video o audio tuyo»: la guía de cada parte con IA

Deivid pidió en el diseño firmado (m-25026602) mantener «Video o audio tuyo» como guía **por cada parte con IA**; en la pantalla va en «Más opciones» del panel del bloque. **Ya existe** en el flujo de partes de hoy y viaja igual en la entrada de `media.ai_parts`, sin cambiar `VideoPartPlan`:

```json
{
  "mode": "reference",
  "seconds": 5,
  "description": "Alguien baila con la arepa en la mano",
  "clip_video_keys": ["uploads/<negocio>/mi-baile.mp4"],
  "clip_audio_keys": ["uploads/<negocio>/mi-cancion.mp3"]
}
```

Respuestas para el carril B, comprobadas en el código de `main` (2026-11-26):

1. **¿Se aceptan `clip_video_keys` y `clip_audio_keys` en una entrada `ai_part`, y el PR 2 los pasa a Seedance igual que hoy?** Sí. Son campos de `VideoPartPlan` (`_PartSource`, hasta 3 videos y 3 audios, `CLIP_MAX_VIDEOS` / `CLIP_MAX_AUDIOS`) y la entrada los guarda sin cambios. Hoy `parts._child_brief` los copia al brief del hijo y el productor los manda como `reference_videos` y `reference_audios` (`media.MediaProducer`: los videos van preparados a 720p y recortados al límite del modelo; con guía, el prompt de la parte es el de «referencias», `PART_REFERENCE_MEDIA_PROMPT_VERSION*`). El PR 2 reusa ese hijo y ese productor sin tocarlos (§13.2), así que la guía llega a Seedance igual que hoy.
2. **¿En qué modos valen?** Solo en **«Nueva» (`reference`)**, confirmado:
   - «Sigue a la anterior» (`extend`): el tipo rechaza cualquier video o audio propio (`ValidationError`, «an extend part cannot use its own reference video or audio»; también `parts_plan` con `PLAN_MODE_FORBIDDEN`). Seedance continúa el bloque anterior.
   - «Igual al original» (`edit`): el tipo acepta **un** video y **ningún** audio, pero ese video es **la ventana del reel** que se copia (cortada antes, VE-09), no una guía del dueño. Un `edit` con audio o con más de un video no se puede ni leer (`ValidationError`).
   - Por eso **la pantalla ofrece «Video o audio tuyo» solo en «Nueva»**. Estos rechazos son del tipo (estructurales, sin `code`): la pantalla nunca debe escribirlos. Si el dueño cambia una parte con guía a otro modo, la pantalla quita la guía antes de guardar.
3. **¿Se revisa que las claves sean del negocio?** Sí. `validate_recipe(…, tenant_id=…)` (y por lo tanto `refuse_unbuilt_recipe` en cada pedido nuevo) revisa cada clave de `clip_video_keys`, `clip_audio_keys` y `clip_image_keys` de cada entrada con `owned_by`: `malformed_key` si no es una ruta del negocio y `foreign_key` si es de otro, en `ai_parts[n].clip_*_keys[i]`. Es la misma regla que hoy aplica `media` a las partes (`media._key_problems`, que también revisa el brief del hijo cuando se crea; esa lista todavía no recorre `media.ai_parts` del Clip, y el PR 2 la amplía).

**Qué más se valida:**

- **Tipo de archivo** (puro, en `ai_parts.guide_problems`): video `.mp4` o `.mov`, audio `.mp3` o `.wav` — los tipos que el productor manda (`media._REFERENCE_TYPES`). Otro: `ai_part_guide_type`.
- **Cantidad y modo:** los del tipo, de siempre (arriba).
- **Largo:** no se puede revisar sin leer el archivo, así que, como hoy, se mide al hacer la parte: el productor recorta cada video de guía al límite del modelo (Seedance 2.0: 2 a 15 s cada uno y 15 s en total; 2.5: 2 a 30 s y 30 s en total) y lo que dura entra en el cálculo del precio. Nada de esto cambia en el PR 1.

Nada de la v1 queda fuera: la guía va en «Nueva» y la pantalla puede ofrecerla desde el PR 6.

### 3.2 «Sigue a la anterior» en la v1

Se revisó el productor de hoy (VE-13: `MediaProducer._extend_brief` y `_new_extend_source` en `qualify_api/creative/media.py`). Seedance continúa **el archivo que el proveedor entregó para la parte anterior**, copiado byte a byte (BytePlus solo acepta una cara en sus propias salidas sin editar), y lo busca entre las partes hermanas (`_previous_parts`). **No sabe continuar un video ni una foto del dueño.** Además, `parts_plan` (`_editable_match`, m-24984421) y `parts.check_extend_parts` solo dejan «Sigue a la anterior» en una parte que el plan partió de una misma toma larga del reel y que empieza en el último corte de la parte de antes. La pantalla de hoy lo dice con `EXTEND_SPLIT_ONLY_REASON`.

Por eso, en la v1, una entrada `extend` vale solo si:

- tiene algo antes en la línea de tiempo (`extend_needs_block_before`);
- lo de antes es **una parte con IA**, no una foto ni un video del dueño (`extend_after_own_media`);
- nació «Sigue a la anterior» en el plan (`original_mode="extend"`), es del mismo reel que la parte de antes y empieza en su último corte (`extend_not_same_moment`).

**Por qué `extend_not_same_moment` solo ofrece «Nueva».** Se revisó si «Igual al original» sería una salida válida en ese caso, y no lo es:

- Una parte sin reel no puede ser «Igual al original» (`edit_needs_reel_window`).
- Una parte que el plan partió de una toma (`original_mode="extend"`) y pasa a «Igual al original» necesita una ventana del reel cortada de antemano en `clip_video_keys`. Sin ella, el tipo la rechaza («a converted split part cannot edit the public source without offsets», `_PartSource`).
- Aunque tenga reel, `parts_plan._can_edit_source` exige además que el reel se pueda editar (vertical, con fuente disponible y cortes aptos).

«Nueva» siempre se puede.

**`extend_after_own_media` es temporal.** Deivid eligió «Construirlo ya en el PR2» (2026-11-26, en la sesión del coordinador):

- En la v1 (este PR) se mantiene el rechazo, porque hoy el productor no sabe continuar un video propio.
- El PR 2 (m-25129406) construye «Sigue a la anterior» después de un video propio, tras una medición pagada que Deivid aprueba aparte, y levanta este código.
- Mientras tanto, la pantalla no ofrece «Sigue a la anterior» después de una foto o un video del dueño. Con `QUALIFY_PARTS_EXTEND` apagado, «Sigue a la anterior» sigue sin ofrecerse, como hoy (`EXTEND_REASON`).

### 3.3 La palabra «bloque» se queda en pantalla

**Deivid decidió (2026-11-26, en la sesión del coordinador) que «bloque» se queda en pantalla**, como había dicho el 2026-11-24. La regla D1 de las maquetas, que la prohibía, queda retirada. Por eso este PR no cambia ningún texto que ya existía solo para quitar «bloque»: los avisos de las uniones (`recipe.py`), el de «Cada bloque puede tomar hasta 1 minuto…» (`local.py` y su copia en `Qualify/clip_editor_vm.py`), `TOO_SHORT`, `FIND_HINT`, `HELP` y `NO_ROOM` quedan con las palabras de `main`. Este PR no toca `Qualify/`.

- Los textos nuevos de `AI_PART_TEXTS` no necesitan «bloque» y no lo usan.
- Tampoco dicen «línea de tiempo» (revisión de UX); lo fija `test_every_code_has_its_spanish_words`.
- El único texto que ya existía y que cambia es `local.LOCAL_TRANSITION_FAILED_TEXT`: «…las transiciones de tu video…» pasa a «…las uniones de tu video…», por la revisión de UX y no por «bloque».
- `{block}`, en `transitions_longer_than_block_text`, es la posición del elemento en la pista desde 1, la misma que muestra la pantalla. Ahora cuenta también las partes con IA.

**Reglas que ya existían y ahora también cuentan los bloques con IA** (mismos códigos y textos de siempre):

- El Clip dura de 3 a 60 s contando los bloques con IA a ×1, menos lo que se comen sus uniones (`local_length_out_of_range`, con `duration_s`).
- Las uniones de un bloque con IA son las de cualquier bloque: `transition_on_first_block`, `transitions_longer_than_block` (con `transitions_longer_than_block_text(bloque)`), y `recipe_unavailable` en `segments[i].transition_in` con `QUALIFY_CLIP_BLOCK_TRANSITIONS` apagado. La pantalla puede ofrecer solo lo que cabe con `block_transition_room_s(part, bloque)`.
- La clave de un bloque con IA nunca se revisa como archivo del negocio (`malformed_key`, `foreign_key` solo miran fotos y videos propios).

Los códigos se agregaron al final de `RecipeRefusal` (`qualify_creative.schemas.RECIPE_REFUSALS`) y no se reordenan.

## 4. Qué llama la pantalla

### Hoy (PR 1)

| Función | Para qué |
|---|---|
| `qualify_creative.schemas.ai_part_key(n)` | Armar la `key` del bloque que apunta a `ai_parts[n]`. |
| `SourceSegment.ai_part_at` | Leer a qué entrada apunta un bloque. |
| `video_pipeline.validate_recipe((part,), video_by_parts=False, ai_parts=media.ai_parts, other_ai_children=n)` | Avisar en cada cambio, antes de «Crear» y gratis. `other_ai_children` = escenas del personaje + avatares (`ai_parts.ai_children_of(media)` lo cuenta desde un `MediaInputs`). |
| `video_pipeline.validate_brief_recipe(brief)` | Lo mismo desde el brief entero; es lo que revisa el servidor. |
| `ai_parts.ai_part_text(code)` / `AI_PART_TEXTS` | Las palabras de cada código de este contrato. |
| `ai_parts.guide_problems(entry, n, tenant_id)` | Revisar solo la guía «Video o audio tuyo» de una entrada al elegir el archivo (§3.1). |
| `ai_parts.own_seconds(segments)` | Cuánto dura el material propio (sin los bloques con IA), para avisar la regla de 3 s. |
| `ai_parts.clip_ai_parts_on()` | Si mostrar «Agregar → Parte con IA». |
| `recipe.clip_seconds(part)` | Cuánto dura el video armado, ya con los bloques con IA y sus uniones. |

### PR 2 (m-25129406) · crear

- `create_clip_with_ai_parts(...)`: crea el Clip y un hijo `CLIP` por cada bloque con IA en una transacción. Descuenta 1 vista previa por hijo, todo o nada. Desde ahí, `refuse_unbuilt_recipe` deja de devolver `recipe_unavailable` para los bloques con IA de ese camino.
- `produce_local` resuelve cada bloque con IA al video que guardó su hijo, a ×1 y con su recorte.
- Los dos llamados de hoy a `validate_recipe` deben pasar `ai_parts=media.ai_parts` y `other_ai_children=ai_children_of(media)` (hallazgo del review-agent): `clip_avatar.py:2764` (`ClipAvatarService`) y `video_pipeline/local.py:930` (`produce_local`). Sin eso, un Clip con partes con IA sale `ai_parts_mismatch` en el armado (falla cerrado, nunca se arma en silencio).
- `media._key_problems` debe recorrer también `media.ai_parts` del Clip (§3.1).
- **«Sigue a la anterior» después de un video propio** (decisión de Deivid: «Construirlo ya en el PR2»): se construye tras una medición pagada que Deivid aprueba aparte, y se levanta `extend_after_own_media` (§3.2).
- Firmas exactas: las fija el PR 2. Este contrato no las adelanta.

### PR 3 (m-25129407) · después de crear

- «Rehacer esta parte» (`regenerate_part`, con padre `CLIP`), intentar de nuevo, hacerla nueva, quitar y cambiar el modo.
- Volver a armar el Clip cuando cambian los textos, las uniones o el orden, reusando el video de los hijos.

### PR 4 (m-25129408) · aprobar y finales

- **Mientras se hacen los finales al aprobar, el Clip queda bloqueado para edición** (decidido en el diseño firmado, m-25026602). La pantalla no deja cambiar bloques, textos, efectos ni uniones hasta que estén los finales (o hasta que uno falle y el dueño elija qué hacer). Lo construye el PR 4; este contrato no trae todavía el estado ni el código de rechazo.

### PR 5 (m-25129409) · del plan a los bloques `[CONSTRUIDO]`

Código: `qualify_api.creative.plan_blocks`. Funciones puras: no escriben, no pagan y no llaman a ningún proveedor.

| Función | Para qué |
|---|---|
| `blocks_from_analysis(analysis, products=…, extend_on=…)` | «Hacer uno parecido»: `plan_from_analysis` y luego `blocks_from_plan`. |
| `blocks_from_proposal(proposal, after=…, other_ai_children=…)` | «Pedir una idea»: lo que devolvió `propose_parts` (ya cobrado y trazado allí), con su `PartsProvenance`. |
| `blocks_from_plan(plan, analysis, after=…, other_ai_children=…)` | Cualquier plan de partes → `ClipBlocks` (`segments`, `ai_parts`, `text_layers`, `effects`, `provenance`). |
| `ClipBlocks.of_media(media)` | La pista que el Clip ya tiene, para pasarla en `after`. |
| `ClipBlocks.problems(other_ai_children=…, tenant_id=…)` | Lo que dice el contrato del §3 (`validate_recipe`); con el interruptor apagado, solo `switched_off`. |
| `ClipBlocks.seconds` | Cuánto dura el video armado (`clip_seconds`). |

- Cada parte `local` pasa a ser sus propios bloques, en orden; su unión con lo anterior queda en el `transition_in` de su primer bloque. Cada parte de otro modo pasa a ser **un** bloque `ai_part` (`key = ai_part_key(n)`, ×1, de 0 a sus `seconds`, con la unión de la parte) y la entrada `n` de `ai_parts`: la misma parte, sin receta propia.
- **Textos y efectos** pasan a las pistas del Clip en segundos del video final, con la colocación de `merged_recipe`: «toda la parte» se vuelve su tramo explícito, y el mismo efecto (o el mismo texto) que sigue de una parte a la siguiente queda como uno solo. La ventana de una parte en el Clip va desde el inicio de su primer bloque hasta el inicio de la parte siguiente (la última, hasta el final del Clip). Así, lo que dura una unión es de la parte que entra, y dos textos nunca se pisan en ella.
- Antes de nada se revisa el plan contra su reel, como en el flujo de partes (`check_edited_plan`): el mismo reel, cortes que existen, «Igual al original» solo donde el reel se puede editar y «Sigue a la anterior» justo después de la parte que sigue. Si falla, sale `PartsPlanRefused` o `ExtendTooShort` con sus códigos de siempre.
- **«Pedir una idea» con la pista ya armada agrega las partes al final, sin borrar nada** (diseño firmado, m-25026602): los bloques que ya existen conservan su `ai_part:<n>` y las entradas nuevas se suman al final de `ai_parts`. Lo que no cabe se rechaza con `PlanBlocksRefused` (`reason` y, cuando existe, el mismo código de receta en `problems`); nunca se corta en silencio. Los textos para el dueño están en `PLAN_BLOCKS_TEXTS`:

| `reason` | Cuándo | Texto para el dueño |
|---|---|---|
| `too_many_blocks` | Más de 8 bloques en total | El de `too_many_blocks` del §3. |
| `too_many_ai_children` | Más de 6 hijos de IA, contando escenas y avatares (`other_ai_children`) | El de `too_many_ai_children` del §3. |
| `too_many_texts` | Más de 3 textos en el Clip | Tu video puede tener hasta 3 textos y estas partes traen más. Quita alguno para seguir. |
| `too_many_effects` | Más de 8 efectos en el Clip | Tu video puede tener hasta 8 efectos y estas partes traen más. Quita alguno para seguir. |
| `span_lost` | Un texto o un efecto que empieza donde termina la ventana de su parte | Un texto o un efecto empieza justo cuando su parte se une con la siguiente y no se alcanzaría a ver. Muévelo un poco antes o quítalo. |

- Al agregar, los textos y efectos que ya tenía la pista terminan donde empieza la primera parte nueva: si esa parte entra con una unión, la unión es suya, y «hasta el final» era el final de antes. Una parte agregada no puede ser «Sigue a la anterior» (`extend_order`; `propose_parts` nunca la propone). Queda la procedencia de la última idea pedida (`parts_provenance` guarda una); el costo de cada llamada sigue en su propio registro.
- Los 60 s y el resto de las reglas del §3 los dice `ClipBlocks.problems`, con sus códigos de siempre.

## 5. Lo que este PR no hace

- No crea hijos, no cobra, no arma videos y no cambia `clip_avatar.py`. La regla de 3 s propios del avatar (`avatar_needs_own_media` en `clip_avatar.py`) sigue sumando todos los tramos. Cuando un Clip tenga avatares o escenas y partes con IA, debe usar `own_seconds`: queda para el PR que junte esos caminos (PR 4 con el §12.4).
- `character_scenes` (§12, m-25128784) todavía no está en `main`. `ai_children_of` la cuenta cuando exista; mientras tanto cuenta 0 escenas.
- `PartRecipe.has_own_video` sigue siendo «tiene bloques». Un Clip hecho solo de partes con IA lo pasa, como decidió Deivid (§13.10, respuesta 3).
