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
| `extend_own_video_speed` | Con `QUALIFY_CLIP_EXTEND_OWN_VIDEO` encendido (PR 2): una parte «Sigue a la anterior» justo después de un video propio que no va a ×1 | `ai_parts[n].mode` | Ese video va rápido o lento. Déjalo a velocidad normal para continuarlo. |
| `extend_own_video_short` | Con `QUALIFY_CLIP_EXTEND_OWN_VIDEO` encendido (PR 2): una parte «Sigue a la anterior» justo después de un video propio de menos de 2 s | `ai_parts[n].mode` | Ese video dura menos de 2 segundos. Usa uno más largo o elige «Nueva». |
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

### 3.4 Pistas de referencias `[CONSTRUIDO EN PR A]` · m-25142725

Debajo del Clip, el dueño pone fotos, videos y audios en pistas, en segundos del video final. Cada parte con IA toma las que quedan debajo de ella. El PR A trae solo el contrato (forma, reglas y textos), sin migración: todo va en el JSON del brief. Crear los hijos con estas referencias es el PR B (detrás de `QUALIFY_CLIP_AI_PARTS`).

**Forma.** `MediaInputs.clip_references` (hasta 40, `CLIP_REFERENCES_MAX`) y `MediaInputs.references_version` (0 = brief de antes; 1 = usa pistas):

```json
"references_version": 1,
"clip_references": [
  {"kind": "photo", "key": "uploads/<negocio>/arepa.png", "start_s": 0, "end_s": 14, "row": 0,
   "origin": "product", "product_id": "<uuid del producto>"},
  {"kind": "video", "key": "uploads/<negocio>/mi-baile.mp4", "start_s": 4, "end_s": 9, "row": 1,
   "origin": "owner", "product_id": null}
]
```

- `kind`: `photo`, `video` o `audio`. `start_s` ≥ 0 y `end_s` > `start_s`, en segundos del video final. `row` es solo de la pantalla (y desempata el orden).
- `origin`: `owner` (lo eligió el dueño, sin `product_id`) o `product` (una foto de un producto del Catálogo que puso la pantalla, con su `product_id`). El servidor no inyecta nada: solo revisa que la clave sea del negocio.
- Una referencia es un elemento suelto, con sus propios segundos: nada la ata a una parte. **Cuando el dueño mueve una parte con IA, la pantalla mueve con ella las referencias que quedan enteras debajo** (Deivid, 2026-11-27); el contrato no lo impide ni lo hace.
- La misma clave puede estar en `segments` (como bloque propio) y en `clip_references`: no hay regla de duplicados. Copiar de un lado al otro copia la cadena, nunca el archivo.

**Qué recibe cada parte** (`ai_parts.references_for_parts(brief, model=None)`, pura; la pantalla la puede llamar antes de «Crear»):

- El tramo de la parte es el de su bloque `ai_part`, en segundos del video que sale: los bloques en orden y a su velocidad, como los pone `clip_avatar.virtual_brief` (los avatares que el Clip espera cuentan con su largo estimado), y cada bloque empieza donde termina el anterior menos lo que se come su unión. El final del Clip es el de `recipe.clip_seconds`.
- **Para el PR B:** las referencias de cada hijo se calculan en «Crear» sobre ese mismo `virtual_brief`. `clip_avatar.fit_plan` mueve los textos y efectos a los largos reales de los avatares, pero todavía no mueve `clip_references`: no hay que volver a calcular las referencias sobre el brief ya ajustado (o `fit_plan` las mueve con el mismo `_mapper`).
- Una referencia aplica si se solapa con la parte más de 0,05 s (`REFERENCE_OVERLAP_MIN_S`).
- Las fotos aplican en todos los modos. Los videos y audios, solo en «Nueva» (`reference`).
- Orden: `(start_s, row, posición en la lista)`. La misma clave del mismo tipo cuenta una sola vez.
- Devuelve un `PartReferences` por parte (`entry_at`, `block_at`, `mode`, `start_s`, `end_s`, `photos`, `videos`, `audios`, `problems`). Nunca corta a un tope: si la parte se pasa, `problems` trae su `too_many_references`, **que bloquea** («Siguiente» y «Crear» apagados con su texto).

**Topes por modelo** (Deivid, 2026-11-27). Cada modelo declara los suyos en `qualify_creative.reference_caps.REFERENCE_CAPS_BY_MODEL`. Hoy, Seedance 2.x (todas sus familias): 9 fotos, 3 videos y 3 audios por parte. Magi-2 tendrá 10/5/5 cuando llegue (todavía no está en la tabla). Son topes del producto, no los del proveedor (la API de Seedance 2.5 acepta 30/10/10). Sin `model`, se usa el modelo de video activo (`QUALIFY_SEEDANCE_REFERENCE_MODEL`, o su valor por defecto). Un modelo sin fila da `ValueError`: no se adivina. Cuando entre un modelo con más de 9 fotos, el PR que lo active sube también `CLIP_MAX_IMAGES` del hijo.

**Rechazos** (`RecipeProblem`, `part=None`). Los revisa `validate_brief_recipe` y, por lo tanto, `refuse_unbuilt_recipe` en cada pedido nuevo; desde `validate_recipe` hay que pasar `media=`.

| Código | Cuándo | `field` | ¿Bloquea? | Texto para el dueño |
|---|---|---|---|---|
|  `too_many_references` | Una parte con más fotos, videos o audios que el tope de su modelo | `ai_parts[n].references.<photo\|video\|audio>` | Sí | Esta parte con IA tiene más de {tope} fotos de referencia. Quita o acorta alguna para seguir. (Con videos y audios: «…más de {tope} videos/audios de referencia. Quita o acorta alguno para seguir.»)  |
|  `reference_type` | Una foto que no es JPG/PNG, un video que no es MP4/MOV o un audio que no es MP3/WAV | `clip_references[i].key` | Sí | No podemos usar ese archivo como referencia. Usa una foto JPG o PNG, un video MP4 o MOV, o un audio MP3 o WAV.  |
|  `reference_out_of_clip` | Una referencia que termina después del final del Clip (`clip_seconds`, ya sin lo que se comen las uniones; con 0,05 s de margen) | `clip_references[i]` | Sí | Esta referencia queda fuera del video. Muévela o acórtala para seguir.  |
|  `references_and_old_fields` | Pistas en un brief sin `references_version` 1, o un brief v1 que todavía trae `clip_image_keys`, `clip_video_keys` o `clip_audio_keys` del Clip, o `ai_parts[n].clip_*_keys` | `references_version`, `clip_*_keys` o `ai_parts[n].clip_*_keys` | Sí | Vuelve a abrir el editor para seguir.  |
|  `malformed_key` / `foreign_key` (de siempre) | Una clave que no es ruta del negocio, o que es de otro | `clip_references[i].key` | Sí | Los textos de siempre. `media._key_problems` también las revisa antes de leer.  |
|  `ai_part_outside_clip` (de siempre) | Pistas en algo que no es un Clip normal `local` | `clip_references` | Sí | El de siempre.  |
|  `switched_off` (de siempre) | Pistas con `QUALIFY_CLIP_AI_PARTS` apagado | `clip_references` | Sí | El de siempre.  |

**Avisos que no bloquean** (`ai_parts.reference_notices(brief)` → `ReferenceNote(code, field, entry_at, scene_at)`; nunca salen de `validate_recipe`):

| Código | Cuándo | Texto |
|---|---|---|
| `reference_mode_ignored` | Un video o audio debajo de una parte que no es «Nueva»: esa parte no lo usa (`entry_at` dice cuál) | Esta parte no usa videos ni audios de referencia. |
| `reference_unused` | Una referencia que no queda debajo de ninguna parte con IA | Esta referencia no está debajo de ninguna parte con IA. |
| `reference_over_scene` | Una referencia sobre una escena del personaje (`scene_at`) | Se decide en el PR 4 (m-25129408); hasta entonces `reference_text` da `None`. |

Para que un aviso bloquee, se agrega su código al final de `RecipeRefusal` y a `REFERENCE_NOTICES_THAT_BLOCK` (hoy vacío).

**Qué llama la pantalla:**

| Función | Para qué |
|---|---|
| `ai_parts.reference_caps(model=None)` | `{"photo": 9, "video": 3, "audio": 3}` del modelo (el activo por defecto), para mostrar el tope. |
| `ai_parts.references_for_parts(brief, model=None)` | Qué toma cada parte y si se pasa del tope (`PartReferences.problems`). |
| `ai_parts.reference_notices(brief, model=None)` | Los avisos. |
| `ai_parts.reference_text(code, kind=None, model=None)` | Las palabras de cada código; `too_many_references` necesita `kind` (el final de su `field`) y dice el tope real. |
| `ai_parts.plan_references(media, segments=None, model=None)` | Lo mismo desde un `MediaInputs`, con partes, rechazos y avisos juntos. |
| `video_pipeline.validate_recipe(..., media=media, reference_model=None)` | Avisar en cada cambio, como el resto del §3. |

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

### PR 2 (m-25129406) · crear `[CONSTRUIDO]`

Código: `qualify_api.creative.clip_ai_parts`. Sin migración; el interruptor sigue apagado.

**Crear.** La pantalla llama:

```python
ClipAiPartsService(content).create_clip_with_ai_parts(
    tenant_id=..., brand_id=..., user_id=..., brief=clip_brief, request_key=uuid,
) -> ClipWithAiParts(clip_id, part_ids)
```

- `brief` es el Clip tal como lo armó el dueño: bloques propios y bloques `ai_part` en `media.segments`, sus entradas en `media.ai_parts` (§2). Nada más: el servidor escribe el resto.
- Crea el Clip (`drafting`) y **un hijo `CLIP` por bloque con IA**, el mismo hijo de hoy de «Video por partes» (`media.part`, hecho por el productor de Seedance sin cambios). Todo en una transacción, bajo el candado del negocio. Se despacha después de confirmar: primero los hijos y al final el Clip.
- **El lugar del hijo** (`part_index`, de 1 a 6) es el orden de su bloque entre los bloques con IA de la línea de tiempo (`ai_part_slots`). Así, la parte que continúa «Sigue a la anterior» es siempre el hijo de lugar anterior, como la busca hoy el productor. `part_ids` va en ese orden.
- **Cobro:** el precio del Clip (un armado local, 0 creaciones) más **1 vista previa por hijo**, todo o nada (`charge_many`). Si no alcanzan las vistas previas para todos, no se escribe nada (`NotEnoughCreations`). Los segundos se cobran al aprobar: PR 4.
- **Una parte sin foto propia** (`clip_image_keys=None`) usa las fotos del Clip (`parts._child_brief`, el padre ahora es el Clip).
- `request_key`: el mismo «Crear» otra vez devuelve lo que ya hizo y no despacha nada.
- `create_draft` sigue rechazando un Clip con bloques con IA (`recipe_unavailable`): solo este servicio lo crea.

**Rechazos, todos antes de escribir y de pagar:**

| Qué | Excepción · código | Texto para el dueño |
|---|---|---|
| Interruptor apagado y todas las reglas del §3 | `RecipeRefused` (`problems`, con los códigos del §3) | Los del §3 |
| Una parte sin descripción y sin video de inspiración (o con el aviso `describe_it` sin descripción) | `ClipAiPartsRefused` · `ai_part_needs_description` (`block` = lugar del bloque en la pista, desde 0) | Cuéntanos qué se ve en cada parte con IA antes de crear tu video. Escríbelo en la parte que está vacía. |
| Un Clip que no es vertical 9:16 | `ClipAiPartsRefused` · `ai_part_outside_clip` | Las partes con IA solo funcionan en videos verticales. Cambia el formato a vertical para usarlas. |
| Partes con IA y escenas del personaje en el mismo video (hasta el PR 4, que junta los dos caminos) | `ClipAiPartsRefused` · `ai_parts_with_scenes` | Por ahora un video no puede tener partes con IA y escenas de tu personaje a la vez. Quita una de las dos para crearlo. |
| «Sigue a la anterior» con `QUALIFY_PARTS_EXTEND` apagado | `PartsExtendUnavailable` | El de siempre |
| Una toma del reel dividida que no se puede comprobar | `PartsSourceInvalid` | El de siempre |
| El tope de dólares del negocio | `PartsOverBudget` | El de siempre |
| El tope de 10 armados al día | `LocalDailyCapReached` | El de siempre |
| Sin creaciones o vistas previas | `NotEnoughCreations` | El de siempre |

**Espera y armado.**

- Mientras un hijo se hace, el Clip **espera** en `drafting` (`ClipBlocksWait`, con latido cada pasada, sin leer, escribir ni pagar nada propio). Cuando termina un hijo, el Clip se despierta (`mark_parent_dirty`); además se reintenta solo cada 30 s.
- Con todos los hijos hechos, el Clip recibe **un brief nuevo** (el que mandó el dueño queda guardado, `derived_from_brief_id`): cada bloque con IA pasa a ser un tramo de video del hijo, a ×1, con el intervalo que guarda la unión de «Video por partes» (`part_span`: el recorte, la ventana de «Igual al original», lo que repite «Sigue a la anterior»), nunca más largo que sus `seconds`, con su unión. Los textos y efectos se mueven al largo real. Se arma **una sola vez** con `produce_local` y `block_join` de siempre.
- **El armado automático no cuenta en los 10 armados del día** (§13.5): no escribe fila de cobro. Solo cuenta el «Crear».
- El video sale `ai_generated=True`. `params.local.ai_parts` guarda, por cada parte que se ve: borrador, revisión y asset del hijo, proveedor, modelo y versión del prompt, modo y `mode_reason`, reel y cortes, segundos pedidos, hechos y vistos, tarea y costo. `ai_sources` la marca con `ai_part: true`.
- **Cambiado por el PR 3 (m-25129407):** un hijo que falla ya no hace fallar el Clip de inmediato; el Clip espera la elección del dueño 72 h (ver «PR 3» más abajo). Lo que sigue describe lo que construyó el PR 2. **Un hijo que falla hace fallar el Clip de inmediato** (decidido el 2026-11-26), con `ai_part_failed` («Tu video no se pudo armar porque una de sus partes con IA falló. No se descontó nada de tu plan. Vuelve a crear el video cuando quieras.»). En la misma escritura vuelven **las vistas previas de todas sus partes** (hechas, fallidas o sin empezar) y, con la devolución de siempre, las creaciones del Clip: el dueño no recibió ningún video. Devolver dos veces no devuelve nada más. La espera de 72 h del §11 vuelve con el PR 3 (m-25129407), junto con «Intentar de nuevo», «Hacerla nueva» y «Quitar». La falla se lee **antes** que la espera: una «Sigue a la anterior» que espera a una parte fallida nunca deja el Clip esperando para siempre.
- `produce_local` nunca recibe un bloque con IA sin resolver: si llega uno, falla cerrado. Por eso los dos `validate_recipe` que nombraba el review-agent (`clip_avatar.place_block` y `produce_local`) no cambian: después de resolver, el brief ya no tiene bloques con IA ni `ai_parts`.
- `media._key_problems` ya recorre los archivos de `media.ai_parts` y salta las claves `ai_part:<n>`.

**Aprobar: todavía no.** Hasta el PR 4, un Clip con partes con IA **no se aprueba** (`ClipAiPartsRefused` · `ai_parts_approve_unavailable`: «Por ahora no se puede aprobar un video con partes con IA. Tu video queda guardado como está.»). Así no se regala ningún segundo de video.

**Texto de cada hijo.** Un hijo de un Clip se hace antes de que el Clip tenga texto: lleva uno vacío, sin llamar a Claude y a costo 0 (`clip_ai_part_without_text`). El Clip lleva el texto.

**«Sigue a la anterior» después de un video propio** (decisión de Deivid, 2026-11-26: «Construirlo ya en el PR2»). Construido detrás de un interruptor nuevo, `QUALIFY_CLIP_EXTEND_OWN_VIDEO`, **apagado** en `.env.example` y `deploy/.env.prod.example`:

- Apagado, nada cambia: `extend_after_own_media` como en el PR 1.
- Encendido, una parte «Sigue a la anterior» justo después de un **video** propio vale si ese video va a ×1 y dura al menos 2 s; si no, `extend_own_video_speed` («Ese video va rápido o lento. Déjalo a velocidad normal para continuarlo.») o `extend_own_video_short` («Ese video dura menos de 2 segundos. Usa uno más largo o elige «Nueva».»). Después de una **foto**, sigue `extend_after_own_media`, con el texto «"Sigue a la anterior" no puede continuar una foto. Pon una parte con IA o un video tuyo justo antes, o elige «Nueva».» (`ai_part_text` lo elige con el interruptor encendido).
- El hijo guarda ese tramo en `media.part.extend_own`. El productor corta **los últimos segundos** de ese video (hasta 10 s, segundos enteros, derecho y sin audio, con `cut_window`), los guarda en la carpeta del hijo y Seedance los continúa (`extend`). La procedencia queda en `extend-source.json` y en `params.part.extend` con `source_kind="own_video"`.
- **No se enciende** hasta la medición pagada que Deivid apruebe: BytePlus puede rechazar una cara real que no salió de sus propios videos. Medición preparada, sin correr: `just eval-extender-propio` (`packages/api/evals/extender_video_propio/`). Tres videos del negocio (con una persona, solo el producto, solo el local), una tarea `extend` de 5 s a 480p (borrador de Seedance 2.5) cada uno. Cotización con la guarda de precios y la tabla `v10`: US$0,92 por tarea con 10 s de entrada, **US$2,77 en total** (reserva con 10 % de margen: US$3,04; tope propuesto: US$3,10).

### PR 3 (m-25129407) · después de crear `[CONSTRUIDO]`

Código: `qualify_api.creative.clip_ai_part_actions` (`ClipAiPartActions`, sobre `ClipAiPartsService`) y la espera en `clip_ai_parts.ai_parts_gate`. Interruptor: el mismo `QUALIFY_CLIP_AI_PARTS`, apagado. Sin migración.

**La espera del §11 vuelve.** Si una parte con IA falla mientras el Clip espera su primer armado, el Clip **sigue esperando** la elección del dueño (`AiPartsWait("part_failed")`, con `wait_until`). El plazo es de **72 h desde la última falla** que vio el servidor (`CLIP_AI_PART_OWNER_WAIT`; la hora es la más reciente entre la última escritura de la fila de la parte, la devolución de su vista previa en esa revisión y el fin de su trabajo en la cola, porque una falla no siempre escribe la fila). Si se vence, el Clip falla con `ai_part_expired` («Tu video no se armó porque una de sus partes con IA no salió y pasaron 3 días sin una elección. No se descontó nada de tu plan. Créalo de nuevo cuando quieras.») y vuelven las vistas previas de todas sus partes, en su revisión actual, como en el PR 2. Una parte que nunca se creó, o hecha sin su video, sigue haciendo fallar el Clip de inmediato (`ai_part_failed`): no hay nada que el dueño pueda elegir. Por ahora no sale correo de falla (el de los avatares, m-25120319, no se extendió a las partes).

| Acción | Cuándo | Qué hace | Cobro | Tope de 10 armados |
|---|---|---|---|---|
| `retry_part` «Intentar de nuevo» | Clip esperando, parte fallida | La misma parte otra vez | 1 vista previa | No cuenta: el «Crear» ya contó ese armado |
| `retry_part(changes=…)` «Cambiar» | Igual | Primero su descripción o fotos | 1 vista previa | No cuenta |
| `make_part_new` «Hacerla nueva» | Igual, solo «Igual al original» donde la regla de partes lo ofrece | Pasa a «Nueva» | 1 vista previa | No cuenta |
| `change_part_mode` | Clip esperando (parte fallida) o Clip armado (parte hecha) | Otro modo; ver reglas abajo | 1 vista previa | Cuenta solo con el Clip armado |
| `remove_part` «Quitar» | Clip esperando, parte fallida | Se marca quitada (`part_removed_at`), el Clip se arma sin su bloque | 0 | No cuenta |
| `redo_part` «Rehacer esta parte» | Clip armado, parte hecha (o una versión rehecha que quedó fallida) y en el video | Otra versión de la parte (descripción o fotos; nunca el modo) y otra versión del Clip que la espera | 1 vista previa | Cuenta 1 |
| `rearrange` | Clip armado | Orden, recortes, uniones, quitar un bloque, textos y efectos | 0 | Cuenta 1 |
| `parts_view` | Siempre | Lo que la pantalla muestra de cada parte y qué botones ofrece | Gratis | — |

**Todo se revisa antes de escribir o pagar** (criterio 1): el interruptor, las reglas de la parte (las de «Video por partes», `part_actions._refusal`: una «Nueva» rechazada por sus fotos no se vuelve a pedir con las mismas), el interruptor de «Sigue a la anterior», que las fotos nuevas sean del negocio, el tope de dólares, el tope de 10 armados y el mes (`NotEnoughCreations`). El cobro es la primera escritura y es todo o nada (`charge_many`: la parte y, con el Clip armado, la fila de armado local del Clip). Todo pasa en una transacción con el candado del negocio, después de la valla del Clip (sus eventos del calendario y su fila: una publicación en curso, programada o un Clip purgado rechazan) y de la fila de la parte; si algo cambió entretanto, se rechaza con `clip_moved` sin escribir nada. Se despacha después del commit, primero la parte y luego el Clip. Un doble toque hace un solo intento.

**Reusar los hijos** (criterio 2). Después de armado, el brief del Clip toca cada parte como un tramo del archivo de su hijo. `rearrange` cambia solo ese brief: ningún hijo se vuelve a pedir, ni se cobra, ni cambia de revisión. Al armar de nuevo, `refresh_gate` revisa que cada tramo de una parte sea de su **versión activa**: si el dueño rehízo la parte, el tramo viejo se cambia por el archivo nuevo (el mismo corte donde cabe, a ×1, con su unión), y el Clip espera mientras la parte se hace. Si la versión nueva no sale, la parte conserva la anterior (la regla de siempre de la generación) y el Clip sale como antes, nunca sin su parte.

**El tope** (criterio 3). Cuentan el «Crear», «Rehacer esta parte», otro modo con el Clip armado y `rearrange` (una fila `local_video` del Clip por revisión). No cuentan los armados automáticos: cuando termina un hijo, ni el que espera una parte rehecha.

**Reglas de otro modo** (`mode_change_problem`): el mismo modo no (`mode_unchanged`); «Igual al original» solo para una parte que el plan hizo así desde el reel (`original_mode == "edit"`, `edit_needs_reel_window`); «Sigue a la anterior» solo si el bloque justo antes en la línea de tiempo es la parte con IA anterior (`extend_needs_block_before`; un video o foto propios en medio no se continúan) y salida de la misma toma (`extend_not_same_moment`, la regla del contrato), con los cortes del reel comprobados como en el «Crear» y su interruptor; «Nueva» siempre.

**«Quitar».** No se quita lo último que queda (`last_block`), y la receta que queda se revisa como en el «Crear». Una «Sigue a la anterior» justo después pasa a «Nueva»; mientras esa parte se está haciendo, «Quitar» se rechaza (el texto de siempre de «Video por partes»).

**Rechazos** (`ClipAiPartsRefused`, con `code` y `owner_message`):

| Código | Texto para el dueño |
|---|---|
| `switched_off` | Las partes con IA no están disponibles por ahora. Tu video queda como está. |
| `clip_not_waiting` | Ya no hace falta elegir nada para esta parte. Abre tu video de nuevo para ver cómo va. |
| `clip_busy` / `clip_not_made` | Tu video se está armando. Cuando termine, podrás cambiarlo. |
| `clip_failed` | Este video no se pudo armar. Créalo de nuevo cuando quieras. |
| `clip_moved` | Tu video cambió mientras tanto. Vuelve a abrirlo y elige otra vez. |
| `part_not_failed` | Esta parte ya salió bien. No hace falta intentarla de nuevo. |
| `part_not_ready` | Esta parte todavía se está creando. Cuando termine, podrás rehacerla. |
| `part_being_made` | Esta parte se está creando. Cuando termine, podrás quitarla. |
| `part_not_in_video` | Esta parte ya no está en tu video. |
| `last_block` | Si quitas esta parte, tu video se queda sin nada que mostrar. Intenta de nuevo o cámbiala. |
| `mode_unchanged` | Esta parte ya está así. Elige otra opción. |
| `edit_needs_reel_window` | «Igual al original» solo funciona en partes que salen de un momento del video de inspiración. Elige «Nueva». |
| `extend_needs_block_before` | «Sigue a la anterior» necesita una parte con IA justo antes. Elige «Nueva». |
| `extend_not_same_moment` | «Sigue a la anterior» solo funciona si esta parte y la anterior salen del mismo momento del video de inspiración. Elige «Nueva». |
| `ai_part_file_not_owned` | No pudimos usar una de esas fotos. Elige otra de tus fotos o súbela de nuevo. |
| `ai_part_added` | Por ahora no puedes agregar partes con IA a un video ya armado. Crea un video nuevo para usarlas. |
| `stretch_not_of_clip` | Uno de los bloques de tu video ya no está disponible. Vuelve a abrir tu video e inténtalo de nuevo. |
| `part_action_refused` | El texto de «Video por partes» (`part_actions`) |

**«Sigue a la anterior» después de rehacer la parte anterior** (Deivid, 2026-11-27): la parte no se rehace sola. `parts_view` la marca con `follows_old_version: true`, el aviso `follows_old_version` y el texto «Esta parte sigue a una versión anterior. Rehazla para que continúe la nueva.». El dueño elige qué hacer. La marca se calcula cada vez con la regla de «Video por partes» (`part_extend.extend_is_stale`: el archivo que continuó ya no es el de la parte anterior), así que desaparece cuando el dueño la rehace o le cambia el modo.

El texto de una parte fallida sin palabras propias (`PART_FAILED_TEXT`, en `parts_view`): «Esta parte no salió. Puedes intentarla de nuevo, cambiarla o quitarla. Tu video te espera 3 días.»

Además, con sus textos de siempre: `PartChangeRefused` (programado, publicándose, purgado, la parte que sigue se está haciendo), `PartsExtendUnavailable`, `PartsSourceInvalid`, `PartsOverBudget`, `LocalDailyCapReached`, `NotEnoughCreations` y `RecipeRefused`.

**Pendiente para otros PR:** agregar una parte con IA nueva a un Clip ya armado (hoy `ai_part_added`), el correo de falla de una parte, y la pantalla (PR 8).

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
| `ClipBlocks.media_fields()` | Los campos del `MediaInputs` del Clip `local`, con `parts_provenance` (modelo, versión del prompt y `proposal_id` de la idea; m-25026636): el Clip la guarda, una parte hija o un Clip que no es `local` la rechazan. |
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
| `span_lost` | Un texto o un efecto que empieza donde termina la ventana de su parte | Un texto o un efecto queda justo en el cambio a la parte siguiente y no se vería. Muévelo un poco antes o quítalo. |

- Al agregar, los textos y efectos que ya tenía la pista terminan donde empieza la primera parte nueva: si esa parte entra con una unión, la unión es suya, y «hasta el final» era el final de antes. Una parte agregada no puede ser «Sigue a la anterior» (`extend_order`; `propose_parts` nunca la propone). Queda la procedencia de la última idea pedida (`parts_provenance` guarda una); el costo de cada llamada sigue en su propio registro.
- Los 60 s y el resto de las reglas del §3 los dice `ClipBlocks.problems`, con sus códigos de siempre.

## 5. Lo que este PR no hace

- No crea hijos, no cobra, no arma videos y no cambia `clip_avatar.py`. La regla de 3 s propios del avatar (`avatar_needs_own_media` en `clip_avatar.py`) sigue sumando todos los tramos. Cuando un Clip tenga avatares o escenas y partes con IA, debe usar `own_seconds`: queda para el PR que junte esos caminos (PR 4 con el §12.4).
- `character_scenes` (§12, m-25128784) todavía no está en `main`. `ai_children_of` la cuenta cuando exista; mientras tanto cuenta 0 escenas.
- `PartRecipe.has_own_video` sigue siendo «tiene bloques». Un Clip hecho solo de partes con IA lo pasa, como decidió Deivid (§13.10, respuesta 3).
