# Plan — Un solo editor: «Video por partes» dentro de la línea de tiempo del Clip

`[PROPUESTO]` · principal-architect, 2026-11-26 · leído contra `origin/main` en `f9e784b7` (cabeza de migraciones `0186`) y la rama `docs/m-25128784-adr50-personaje` (§12 del ADR 50, sin firmar).

**Decisión de Deivid (2026-11-26):** «Video por partes» (ADR 44, épica m-24921048) y el editor del Clip «Arma tu video» (ADR 50, épica m-25026566) pasan a ser **un solo editor con línea de tiempo**. Aclaración del mismo día: «que sea una combinación de las dos; ese es el objetivo desde el día cero». **No se pierde nada de ninguno de los dos.** Cada parte hecha con IA es un bloque más de la línea de tiempo del Clip. Va en la misma dirección que la escena del personaje (§12 del ADR 50, m-25128784).

**Encaje con lo firmado.** No reabre nada; lo completa. El ADR 50 §1.1 ya decía «una sola pantalla […] que reemplaza las pantallas del Clip y de la hoja de parte». El §4 ya descartó «el Clip como `SHOT_VIDEO` de una sola parte». Por eso el contenedor es **el Clip**, no el padre `SHOT_VIDEO`. Lo que sí **enmienda** es el modelo del ADR 44 («cada parte es hija de un padre `SHOT_VIDEO`»): para las piezas nuevas, el padre pasa a ser el Clip. Se registra como **§13 del ADR 50** (después del §12, en el mismo archivo, para no chocar con la rama de m-25128784) y como una nota en la fila 44 de `arquitectura.md` §6.

## 1. Cómo funciona hoy cada flujo

### 1.1 Video por partes (ADR 44)

| Aspecto | Cómo es | Dónde |
|---|---|---|
| Contenedor | Borrador padre de tipo `SHOT_VIDEO`. Su brief guarda el plan: `media.parts` (`VideoPartPlan`, hasta 6) y `media.parts_removed` | `schemas.py:1807`, `:1814`; `PARTS_MAX` `:120` |
| Parte | Borrador hijo `CLIP` (`parent_draft_id` + `part_index` 1–6, revisión `0119`) con `media.part` (`PartRef`). Lleva su modo (`reference`/`edit`/`extend`/`local`), sus segundos (1–10), recorte, descripción, fotos y, desde ADR 50, su propia receta (`segments`, `text_layers`, `effects`) | `schemas.py:1180` (`PartMode`), `:1199` (`_PartSource`), `:1323`, `:1435`; `0119_…py:379` |
| Plan | Lo arma la IA desde el análisis del reel (`plan_from_analysis`) o sin reel con Claude (`propose_parts`). El dueño lo edita antes de «Crear»: orden, quitar, juntar, modo, descripción y fotos (`save_parts_plan`, `check_edited_plan`, `merge_short_part`) | `parts.py:722`; `parts_ai.py:687`; `parts_plan.py:139`, `:205`, `:319` |
| Modo con motivo | Regla en código, sin LLM (`choose_part_mode`, `mode_reason`) | `video_pipeline/mode_choice.py` |
| Crear | `create_parts`: crea las hijas que faltan (todas, una o la 1), todo o nada en una transacción. Cobra **1 vista previa por parte** (`charge_many`, D7) | `parts.py:1499`; `creations.py:362` |
| Después de crear | `regenerate_part`: solo cambia la **descripción y las fotos** (`PartChanges`, nunca el modo) y cobra 1 vista previa. `retry_part`, `make_part_new` (de «Igual» a «Nueva») y `remove_part` | `parts.py:935`, `:1700`; `part_actions.py:330`, `:359`, `:405` |
| Textos y efectos | Por parte, y el servidor solo los dibuja en partes `local` o `reference` 9:16 (`recompose.py`, m-25103284) | `video_pipeline/recompose.py` |
| Unión | El worker une las vistas previas de las partes (`join_preview`, `run_join`), con las transiciones por parte de EF-16 (`VideoPartPlan.transition_in`) | `part_join.py:676`, `:838`; `schemas.py:1332` |
| Aprobar y cobrar | Una sola aprobación del video entero (`_approve_parts`): cobra los **segundos pedidos** de todas las hijas, todo o nada (`charge_videos_many`). Después pide los finales 1080p de cada parte (`part_final`) y hace la unión final | `service.py:4444` (que rechaza aprobar una hija suelta), `:4570`, `:4624`; `creations.py:386`; `part_final.py:204`, `:296` |
| Pantallas | `reel_parts_vm` (lista «Tu video, parte por parte»), `part_editor_*` (hoja de la parte, UI-4), `parts_start_*` (sin reel), `part_progress_*` (UI-7), `part_review_*` (UI-8) | `Qualify/` |

### 1.2 Clip «Arma tu video» (ADR 50)

| Aspecto | Cómo es | Dónde |
|---|---|---|
| Contenedor | Un borrador `CLIP` sin padre. Su receta `local` vive en el brief: `media.segments` (hasta 8 bloques de foto o video propio, en orden), `text_layers` (hasta 3), `effects` (hasta 8) y `SourceSegment.transition_in` para cada unión (§10) | `schemas.py:1054`, `:1734`; `SEGMENTS_MAX` `:744`; `TEXT_LAYERS_MAX` `:748` |
| Largo | De 3 a 60 s (`LOCAL_TOTAL_MIN_S` y `LOCAL_TOTAL_MAX_S`) | `schemas.py:838–839` |
| Armado | Local en el `creative-worker` (`produce_local`): prepara, aplica la velocidad, une los bloques con sus transiciones (`block_join`) y compone las capas y los textos. Cuesta US$0 y lo limita un tope de 10 armados al día | `video_pipeline/local.py:887`; `block_join.py:137`; `local_cap.py` |
| Hijos con IA | El bloque de avatar (§9 y §11) es un borrador hijo del Clip (`clip_avatar_block`, `part_index` como lugar, sin `media.part`). El Clip y sus hijos se crean juntos (`create_clip_with_blocks`); el Clip espera en `drafting` (`ClipBlocksWait`) y el armado mete cada hijo como `SourceSegment` de video a ×1 | `clip_avatar.py:1109`, `:1358`, `:1917`, `:2697`; `service.py:917` (`check_part_link`) |
| Cobro | El armado local va en cero. Los segundos de los hijos se cobran **al aprobar el Clip**, en la fila de cada hijo (`clip_block_charges`) | `clip_avatar.py:2867`; `service.py:~4815–4840` |
| Pantallas | `clip_editor_vm` y `clip_editor_view`, `ui/timeline*` (regla, cabezal y tres pistas), `clip_joins_vm` (uniones), `clip_texts_vm`, `clip_photos_vm`, `clip_gallery_vm`, `ui/edit_preview` (vista previa en el navegador) | `Qualify/`; interruptor `QUALIFY_CLIP_EDITOR` (`clip_editor_vm.py:39`), **apagado en producción** |

La escena del personaje (§12, en borrador) sigue el patrón del avatar: un hijo `CHARACTER_SCENE` que **reemplaza** una ventana de tiempo. Su borrador sale en 480p al «Crear» y cobra 1 vista previa; el final de 1080p se pide al aprobar. Ese **«final de un hijo y volver a armar el Clip»** es justo lo que necesitan las partes con IA.

## 2. Modelo propuesto: una sola línea de tiempo

**Una idea:** el Clip es el único contenedor. Un bloque de la pista «Fotos y videos» puede ser **material propio** o **una parte con IA**. Las escenas del personaje siguen siendo ventanas (§12) y los textos y efectos son del Clip entero.

```
Clip (CLIP, sin padre) ── media.segments: [propio | parte IA | propio | parte IA …]  ≤ 8 bloques, 3–60 s
   │                       text_layers / effects ─ sobre el video entero (segundos del final)
   │                       character_scenes ────── ventanas que reemplazan segundos (§12)
   ├── hijo CLIP «parte IA» (media.part, modo reference|edit|extend, part_index = lugar)
   └── hijo CHARACTER_SCENE (§12)
```

- **Bloque «parte con IA»:** un `SourceSegment` de `kind="ai_part"` que apunta a una entrada de `media.ai_parts` (un `VideoPartPlan` sin cambios: modo, segundos, recorte, descripción, fotos, análisis, `mode_reason`). Su `transition_in` es el del bloque (el campo del §10). **No necesita migración**, porque todo vive en el JSON del brief.
- **El hijo** es el mismo hijo `CLIP` con `media.part` de hoy, así que el productor de Seedance (`reference`/`edit`/`extend`, ventanas del reel, `extend` desde la parte anterior) se reusa **sin tocarlo**. Lo que cambia es que el padre puede ser un `CLIP` (`check_part_link`, `service.py:917`).
- **El armado** busca el video que guardó cada hijo (como `generated_sources` y `place_block`), a ×1 y con su recorte, y lo une con los bloques propios usando el `block_join` de siempre. Ya no hay unión de partes aparte (`join_preview`).
- **Una parte `local` deja de ser hija:** pasa a ser directamente bloques propios en `segments`.
- **Los textos y efectos que tenía cada parte** pasan a las pistas del Clip, en segundos del video final, con la misma lógica de colocación de `merged_recipe` (`parts_plan.py:319`). Así se levanta la restricción de hoy («solo en `local` o `reference` 9:16»): el texto se compone una sola vez sobre el video armado.
- **Del plan de la IA a los bloques:** una función pura nueva, `blocks_from_plan(plan, analysis)`, convierte lo que devuelven `plan_from_analysis` o `propose_parts` en bloques. Las partes `local` se vuelven bloques propios, las demás bloques `ai_part`. Las transiciones del plan pasan al `transition_in` de cada bloque. La pantalla lo muestra en la línea de tiempo **antes de «Crear»**, sin costo (lo que eligió Deivid).
- **Topes de la versión 1:** ≤ 8 bloques (`SEGMENTS_MAX`), ≤ 60 s y ≤ 6 hijos en total entre partes con IA y escenas, porque `part_index` va de 1 a 6 (`0119`). La regla de §11 «3 s propios como mínimo» aplica solo cuando hay escenas o avatares (pregunta 3).
- **Interruptor nuevo:** `QUALIFY_CLIP_AI_PARTS`, apagado en todos los entornos (`.env.example` y `deploy/.env.prod.example`). Apagado, el servidor rechaza `ai_part` con `switched_off` antes de leer nada.

### 2.1 Inventario: dónde queda cada característica en el editor único

| Viene de | Característica | En el editor único |
|---|---|---|
| Partes | Plan desde un reel analizado («Hacer uno parecido») | Abre el editor con los bloques ya puestos (`blocks_from_plan`) |
| Partes | «Proponerme las partes» sin reel · «Prefiero armarlas yo» | «Agregar → Pedir una idea» propone bloques · «Agregar → Parte con IA» vacía |
| Partes | Modo con motivo (Nueva, Igual al original, Sigue a la anterior) | Panel del bloque IA: «¿Cómo la hacemos?» con su motivo (`mode_choice`) |
| Partes | Descripción, fotos, segundos (1–10), avisos (`people_unclear`, `describe_it`) | Panel del bloque IA |
| Partes | Reordenar, quitar, juntar partes cortas | Arrastrar en la pista; «Quitar»; «Juntar con la siguiente» (`merge_short_part`) |
| Partes | «Probar solo la parte 1» · «Crear las n partes» | «Crear» con todo, o «Probar este bloque» (`create_parts` con `part_indexes`) |
| Partes | Progreso y fallos por parte; Intentar de nuevo, Hacerla nueva, Quitar | Estado sobre cada bloque IA en el resultado (palabras de `part_progress_vm`) |
| Partes | «Crear otra versión», «Me gusta así», ver la versión anterior | Panel del bloque IA después de crear: «Rehacer esta parte» (D-E5) |
| Partes | Una aprobación del video entero, finales 1080p, segundos al aprobar | Aprobar el Clip (§3) |
| Partes | Texto del padre con Opus · voz y subtítulos (VE-15) | El copy del Clip · fase 2, igual que hoy |
| Partes | Tarjeta «Video de inspiración» | Encima del editor cuando el Clip nace de un reel |
| Clip | Fotos de 1–5 s, videos con recorte, «Cortar», girar, velocidad ×2–×20 | Sin cambio (solo bloques propios; un bloque IA va siempre a ×1) |
| Clip | Textos (4 fondos, animaciones, tamaño, color) y capas (humo, brasas, vapor) con filas | Sin cambio, ahora también sobre las partes con IA |
| Clip | Uniones Corte / Fundido / Barrido con duración | En cada unión, también junto a un bloque IA (la salida de una escena, solo Corte, §12.6) |
| Clip | Vista previa en el navegador; cuadro real y tira de cuadros (ED-11/11b) | El bloque IA muestra su póster antes de crearse y su video después |
| Clip | Galería y Publicaciones como fuente; guardado al momento, sin «Deshacer» | Sin cambio |
| Clip | Personaje en escena (§12) · «Objeto en una zona» (EF-13) | Pista «Personajes» · pista «Efectos» |

## 3. Qué puede hacer el dueño con cada bloque

| Bloque | Antes de «Crear» (gratis) | Después de crear |
|---|---|---|
| Propio | Todo lo del Clip de hoy | Lo mismo. Cada cambio vuelve a armar el Clip sin costo (cuenta en el tope de 10) |
| Parte con IA | Modo, descripción, fotos, segundos, recorte, orden, quitar, juntar, unión | «Rehacer esta parte» (descripción y fotos: 1 vista previa, `regenerate_part`). Cambiar el modo = una versión nueva del bloque (1 vista previa; ya existe un precedente, `make_part_new`). Orden, quitar, recorte y unión: se vuelve a armar gratis, reusando el video del hijo |
| Escena del personaje | Lo que define el §12.2 | Lo que define el §12. Una escena sin cambios no se vuelve a pedir |
| Textos, capas, uniones | Todo | Todo, gratis: son del Clip, no de la parte. Esto cierra el hueco de hoy, en que no hay forma de cambiar el texto, el efecto o la unión de una parte ya creada |

**Cobro (una sola regla para todos los hijos).** Al crear cada bloque con IA se cobra 1 vista previa, todo o nada (`charge_many`); si falla, se devuelve. Al aprobar el Clip se cobran, todo o nada, **los segundos pedidos** de cada hijo con IA que aún no se cobró, en la fila de ese hijo (se juntan `clip_block_charges` y `charge_videos_many`). Después se piden los finales de 1080p de esos hijos (`part_final`) y el Clip se vuelve a armar con ellos. Es el mismo mecanismo del §12.4; se construye **una sola vez** para escenas y partes. El Clip queda «listo» y el dueño lo ve antes de programarlo. Los bloques propios cuestan 0. Un hijo reusado sin cambios no se cobra de nuevo (su clave es el resumen de lo que se le pidió).

## 4. Camino de migración: PR chicos, primero el servidor

Ninguna migración es obligatoria. Lo nuevo vive en el JSON del brief y el tipo del hijo sigue siendo `CLIP`. Los números **0187** y **0188** ya los tienen m-25129385 y m-25128784. El **0189** queda reservado **solo** si Deivid pide más de 6 hijos por Clip: ampliar `ck_content_drafts_part_index` es reversible.

| PR | Qué | Reusa | Depende de |
|---|---|---|---|
| 0 · docs | §13 del ADR 50 (este plan), nota en la fila 44 y `qualify-context` | — | §12 en `main` |
| 1 · contrato | `SourceSegment.kind="ai_part"`, `media.ai_parts`, reglas en `validate_recipe` y en `unbuilt_recipe_problems` (topes, `extend` con un bloque IA o un video propio antes, `edit` con ventana del reel), interruptor. Funciones puras, sin escrituras | `VideoPartPlan`, `transition_room_problems` | 0 |
| 2 · crear | `create_clip_with_ai_parts`: el Clip y sus hijos en una transacción, 1 vista previa por hijo, `check_part_link` con padre `CLIP`, el armado resuelve cada bloque a su video, `ai_generated` | `create_clip_with_blocks`, `ClipBlocksWait`, `create_parts`, `produce_local` | 1 |
| 3 · después de crear | «Rehacer esta parte», intentar de nuevo, hacerla nueva, quitar y cambiar el modo con padre `CLIP`. Volver a armar al cambiar textos, uniones u orden, reusando los hijos | `regenerate_part`, `part_actions` | 2 |
| 4 · aprobar y finales | Cobro único de segundos de los hijos, finales de 1080p y volver a armar con ellos. **Se hace junto con el §12.4** (m-25128784): un solo camino | `charge_videos_many`, `part_final`, `recompose` | 2, §12 |
| 5 · del plan a los bloques | `blocks_from_plan` para el análisis y para `propose_parts`; los textos y efectos de cada parte pasan al Clip | `plan_from_analysis`, `merged_recipe` | 1 |
| 6 · pantalla: bloque IA | Bloque IA en la pista (aspecto propio, insignia del modo con su motivo), su panel, «Agregar → Parte con IA» | `part_editor_vm` (palabras), `timeline_vm` | 1, 2, diseño firmado |
| 7 · pantalla: entradas | «Hacer uno parecido» y «Pedir una idea» abren el editor con los bloques | `reel_parts_vm` (palabras de uso), `parts_start_vm` | 5, 6 |
| 8 · pantalla: resultado | Progreso por bloque, «Rehacer esta parte», aprobar, espera de los finales | `part_progress_vm`, `part_review_vm` | 3, 4, 6 |
| 9 · limpieza | Ya no se crean padres `SHOT_VIDEO` nuevos. Se retiran la lista, la hoja, la tarjeta sin reel y `join_preview` para piezas nuevas | — | interruptores encendidos con OK de Deivid |

**Lo que se retira, y cuándo.** Las piezas `SHOT_VIDEO` ya creadas se siguen abriendo con sus pantallas de hoy (progreso, revisar, aprobar) hasta que la retención las purgue; después se borra su código. No hay conversión de datos.

## 5. Tickets abiertos

| Ticket | Qué hacer |
|---|---|
| m-25026638 ED-07 «El editor en Video por partes» | **Reescribir** como el PR 6 (bloque IA en la línea de tiempo). Se conserva el id; la copia del editor ya no se hace |
| m-25026640 ED-08 «Cambiar esta» | **Reescribir** como PR 3 + PR 8, con «Rehacer esta parte» dentro del editor |
| m-25026636 ED-06 «Idea» y 3 pasos | **Mantener y ajustar:** «Idea» propone bloques (PR 5 y 7). Los 3 pasos no cambian |
| m-25026602 firma del diseño | **Ampliar:** incluir el bloque IA, su panel y el resultado. Es condición del PR 6 |
| m-25112921 «+ Avatar», ahora escena del personaje | **Sin cambio de alcance.** Comparte con las partes los lugares de hijo (≤ 6) y el PR 4 |
| Épica m-24921048: UI-5, UI-8, UI-9, UI-10, UI-11 y VE-13…VE-19 todavía abiertos | Revisar en Meegle (no se leyó en esta sesión). Las pantallas (UI-*) se **cierran** si las reemplazan los PR 6–8. VE-17 (presentador por parte) se **cierra**, reemplazado por la escena. VE-13, VE-15, VE-18 y VE-19 **siguen** y ahora aplican a los bloques |
| Nuevos | Un ticket por cada PR 0–5 y 9 en la épica m-25026566, creados con `meegle-ticket` |

## 6. Riesgos y preguntas para Deivid

**Riesgos.**

- **(a)** Dos series de PR tocan el mismo archivo (`clip_avatar.py`, el §12 y este plan). Por eso el PR 4 se hace junto con el §12.4.
- **(b)** El armado de un Clip de 60 s con 8 bloques tarda unos 29 min con 1 CPU (ADR 50 §10.4), y el paso `speed` pasa 14,5 min sin dar señal de vida. Con bloques IA el armado se repite más veces: hay que medirlo de nuevo antes de encender.
- **(c)** Mientras dure la transición conviven dos caminos (`SHOT_VIDEO` viejo y Clip). El PR 9 tiene fecha cuando se enciendan los interruptores.

**Preguntas.**

1. **Videos por partes ya creados:** ¿se siguen abriendo en sus pantallas actuales hasta que venzan, o se convierten al editor nuevo? → **Recomiendo** dejarlos como están, sin convertirlos. Convertirlos cuesta una migración de datos por piezas que la retención va a borrar igual.
2. **Textos y capas sobre partes con IA:** ¿se permiten textos y capas (humo, brasas, vapor) sobre cualquier parte con IA, también «Igual al original» y «Sigue a la anterior»? → **Recomiendo** sí, porque se componen sobre el video armado a costo 0. La única excepción sería la regla del §12, «textos sí, efectos no» sobre una escena.
3. **Clip hecho solo de partes con IA:** ¿puede existir, como un video por partes de hoy hecho solo de partes «Nueva»? → **Recomiendo** sí. La regla «3 s propios como mínimo» (P5 del §11) aplicaría solo a escenas y avatares.
4. **Hijos por Clip:** ¿alcanza con 6 hijos en total entre partes con IA y escenas? → **Recomiendo** 6 en la versión 1, sin migración. Si hace falta más, el 0189 lo amplía.
5. **Tope de 10 armados al día:** ¿cuentan los armados automáticos (cuando termina un hijo, o con los finales)? → **Recomiendo** que solo cuente lo que el dueño pide («Crear», un cambio o «Rehacer»). Los armados automáticos no cuentan; si contaran, un Clip con 6 partes gastaría el tope solo.
