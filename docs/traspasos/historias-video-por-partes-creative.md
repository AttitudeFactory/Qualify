# Video por partes — historias del área creative, listas para Meegle

`[PROPUESTO · creative-engineer · 2026-11-02 · main 56746531]` · Fuente: `docs/diseno-video-por-planos.md` (el diseño) y `docs/ux-video-por-planos.md` (UX). No reabre D1–D3 de m-24880680, D5–D8 de `docs/modelo-cobro-generacion.md` ni ADR 41/42/43. Nada se construye antes de VE-01 (firma de ADR 44).

## 0. Cómo leer

- **[V]** verificado en disco · **[D]** documentación de BytePlus citada en el repo, sin prueba propia · **[H]** hipótesis.
- Líneas citadas sobre **HEAD 56746531** (`git show HEAD:…`). Mientras se escribía esto, otras sesiones cambiaban sin commitear en el checkout principal `media.py`, `pipeline.py`, `service.py`, `schemas.py`, `creations.py (creative)` y `brand/render.py`: las líneas de `media.py` que cita el diseño son las del árbol de trabajo (p. ej. `_clip` 2603 ahí, **2484** en HEAD; `finalize` 1533 → **1485**; `clip_prompt` 4640 → **4450**).
- Abreviaturas: `media.py`, `service.py`, `creations.py`, `queue_dispatch.py`, `pipeline.py`, `worker/pipeline.py`, `dispatch.py`, `fsm.py`, `final_review.py`, `final_retries.py`, `draft_mode.py`, `retention.py` = `packages/api/src/qualify_api/creative/…`; `schemas.py`, `enums.py`, `creations.py (creative)`, `fit.py`, `byteplus_ark.py` = `packages/creative/src/qualify_creative/…`.
- Historias finales: **14** (las 11 del diseño; VE-10 se parte en **VE-10a/VE-10b**; nuevas **VE-20** y **VE-21**). Cambian respecto del diseño: VE-02, VE-06, VE-07, VE-08, VE-09, VE-10, VE-13, VE-17. Aparte, un bug ajeno a la épica (§2.15).

## 1. Verificación del diseño contra el código

| # | Afirmación del diseño (§) | Veredicto | Evidencia |
|---|---|---|---|
| 1 | Partes de 4–10 s enteros; el chequeo ±0,5 s de `edit` «sigue valiendo» (§4.2 a) | **Incompleto** [V]: `MediaInputs._known_duration` rechaza toda duración fuera de (5, 10, 15, 30, 45, 60); una parte de 4, 6, 7, 8 o 9 s no se puede ni construir | `schemas.py:56, 570-575`; chequeo de `edit` en `media.py:2511-2516` |
| 2 | E7: Seedance 2.5 acepta 30/10/10 referencias | Cierto en el adaptador [V]; el esquema topa en 9 imágenes y 3 videos, suficiente para una parte | `byteplus_ark.py:223-237`; `schemas.py:435-437` |
| 3 | E11: `video_job` empareja por orden de llamada; una hija = 1 trabajo | Cierto [V]. Ojo: si `_clip` cae al camino «sin referencias» hace una 2.ª llamada y `video_job` da de alta un trabajo extra sin avisar | `pipeline.py:168-205` (alta en 192-204); caída en `media.py:2626-2652` |
| 4 | `generation_jobs()` del padre = `[]` | Funciona a medias [V]: hoy nunca devuelve `[]` (todo cae en `preview`); con `[]`, `_enqueue` escribe solo la fila de `creative_pipeline_runs` y el worker la encuentra porque descubre negocios por los trabajos de las hijas. Pero si el padre **espera a sus hijas en `drafting`**, `reap_stale_drafts` lo falla a los 20 min: solo perdona piezas con trabajos `queued`, y el padre no tiene | `queue_dispatch.py:56-66, 106-162`; `worker/pipeline.py:415-441`; `dispatch.py:62, 162-216` |
| 5 | «Al asentarse una hija se sube `dirty_version` del padre» | Falta el mecanismo [V]: hoy solo suben `dirty_version` `complete_step`, los reintentos de final y la duda de envío, siempre de la misma pieza. Tampoco cubre **restaurar una versión** de una parte (no genera, no ensucia nada) | `pipeline.py:146-166`; `final_retries.py:167`; `worker/pipeline.py:151` |
| 6 | Fases `join` y `join_final` en `PipelinePreparation` | Necesarias y no triviales [V]: la rama `else` interpreta toda fase como `final:<uuid>@n`; otro nombre lanza excepción y la corrida se reintenta sin fin como `preparation_failed` | `worker/pipeline.py:449-457` |
| 7 | El final de parte termina en `part_final` | Hay que tocarlo [V]: `_final_video` escribe siempre `"status": "final_ready"` | `media.py:1686-1704` |
| 8 | El video unido es el publicable | **Riesgo grave** [V]: un video **sin** bloque `draft` es publicable (`final_confirmed` devuelve `True`, `draft_pending` `False`): la vista previa unida de 480p saldría a Instagram. Con un bloque en estado `draft`, `_waiting_drafts` le pediría a Seedance un final que no existe | `final_review.py:81-83`; `draft_mode.py:48-55`; `service.py:2969-2975` |
| 9 | `approve_parts` cobra N videos todo o nada (D6) | **No funciona cobrando en el padre** [V]: `charge_videos` es por `(draft, revision)`; el ejecutor rechaza el final de una hija cuyo cargo (el de la hija) tiene `videos = 0` y exige la hija en `approved`; la devolución de un final fallido busca el cargo de la hija | `creations.py:476-511`; `worker/pipeline.py:178-221`; `service.py:3355-3378` |
| 10 | Crear las N partes usa N vistas previas, todo o nada (UX UI-6) | Hoy no [V]: `create_draft` cobra cada pieza en su propia transacción; crear 4 hijas seguidas puede cobrar 3 y fallar la 4.ª | `service.py:1688-1727`; `creations.py:411-445` |
| 11 | Cada hija es una pieza | Cada pieza llama a Claude para su texto (3 variantes) y `clip_prompt` arma «una historia en tres planos» con ese texto: N llamadas inútiles y un prompt equivocado para una parte [V] | `service.py:2134-2136` (llamada a `_copy_stage`); `media.py:4462-4481` |
| 12 | «Crear otra versión» con cambios (descripción, modo, fotos) | Sin precedente [V]: ninguna ruta cambia el brief de una pieza y `piece_versions` no guarda qué brief usó cada versión; restaurar la versión 1 mostraría la descripción de la 2. Además `_final_video` lee el modo `edit` del brief, no de la versión | `0103_piece_versions.py:19-22`; `media.py:1640-1645` |
| 13 | §4.2 c «se guarda la salida cruda» | **Ya existe en la cola** [V]: el worker guarda el archivo del proveedor byte a byte en `t/{t}/generated/{draft}/r{rev}/queue-{job}.bin` (vistas previas y finales), y el final guarda además `raw_final`. Falta anotar la clave en la pieza; y el sufijo `.bin` lo rechaza `_reference_urls` (solo MP4/MOV/MP3/WAV) | `worker/pipeline.py:327-349`; `media.py:1609-1629, 1232, 2753` |
| 14 | E15: `PyAvVideoFitter` no concatena | Cierto [V], y tampoco corta desde un inicio (solo `max_seconds` desde 0) y copia el audio por paquetes sin decodificarlo: el fundido de 80 ms exige decodificar, remuestrear y codificar AAC. `join.py` y `cut.py` son nuevos; se reusan `_frame_rate`, `_layer_frame`, el grafo recorte/escala y el archivo temporal con `+faststart` | `fit.py:236-417` |
| 15 | E16: PyAV en producción | Cierto [V]: el grupo por defecto `backend` instala `qualify-creative[llm,media]` (`av>=14`; 19.0.1 en el lock); la imagen hace `uv sync --no-dev` y `creative-worker` usa esa imagen. `FfmpegVideoNormalizer` usa el binario, que no está: no se usa aquí | `pyproject.toml:15, 48`; `packages/creative/pyproject.toml:45-47`; `deploy/Dockerfile:62, 78`; `uv.lock:104-105` |
| 16 | Pesos v2: «1 parte = 1 video» | Cabe sin tabla nueva [V]: `video(seconds)` vale 1 para todo ≤ 10 s y una hija `clip` cae en `_generated_video_price`. El padre `shot_video` necesita su rama (hoy daría `CreationNotOffered`). `v7` ya tiene Seedance 2.5, Seed Speech, OmniHuman y Haiku 5.5: **ninguna versión de precios nueva** | `creations.py (creative):175-182, 399-416`; `pricing_data/v7.json` |
| 17 | Estado `refused_face` | No hay razón tipada [V]: `PrivacyInformation` solo cambia el texto (`REAL_PERSON_TEXT`, que habla de «fotos») y el motivo queda `provider_error`. `failure_reason` no tiene CHECK en la base: un valor nuevo no pide migración | `media.py:737, 797`; `enums.py:178-196` |
| 18 | Claves de archivo de las partes | Hueco previo [V]: `_key_problems` no revisa `slide.reference_video_key`, y la lectura de R2 confía en ese control para no leer de otro negocio | `media.py:523-549, 577-584` |
| 19 | Retención (§7) | Falta para las hijas [V]: el plazo sale de los eventos del calendario de **cada** pieza; las hijas no tienen eventos, así que caducarían antes y recibirían avisos propios | `retention.py:5-12` |
| 20 | «El plazo del padre es el de su parte más vieja» | `draft_expires_at` solo cuenta bloques `draft`/`failed` de los parámetros que recibe: hay que pasarle los de las hijas [V] | `draft_mode.py:78-93` |

**Correcciones de forma que siguen de la tabla** (se aplican en las historias):

- **El padre no espera a sus hijas en `drafting`.** Su fase `generation` hace solo el texto (Claude, como el de un Clip) y termina en `generated` sin video, como ya admite una pieza solo de texto (`service.py:1854-1866`). La unión es la fase `join`, que corre aunque el padre esté `generated`. Los estados de §3.2 del diseño (`generating`, `previewing`, `joining`) son **calculados** para la pantalla, no estados nuevos de la máquina (`fsm.py`).
- **Los videos se cobran en las hijas, no en el padre**: un método nuevo `charge_videos_many` cobra 1 video por hija en **una** transacción con el candado de la marca (todo o nada, D6). Así el ejecutor, la devolución por final fallido y `_videos_of` no cambian.
- **El video unido lleva siempre un bloque `draft` propio** (`finish: "join"`, estados `join_preview` → `final_ready` → `final`), fuera de `draft`/`failed`: no es publicable antes de la confirmación y nadie pide a Seedance su final.
- **Las hijas no llaman a Claude**: heredan una variante del padre (costo 0), que además satisface la guarda `approve requires a selected_variant_id` (`fsm.py:129-130`) cuando el padre se aprueba.

## 2. Historias

Todas: épica «Video por partes» (Feature de Meegle a crear con VE-01), asignadas a creative-engineer salvo que se diga otra cosa; `P1` = bloquea a las siguientes de la fase 1 una vez firmado VE-01 (`docs/formato-tickets-meegle.md` §3).

### 2.1 VE-02 · Video: detectar planos, sacar fotogramas y cortar ventanas con PyAV
`Feature · P1 · M · Depende de: VE-01 · Bloquea: VE-04 (BE), VE-09` · **Cambio:** absorbe `cut_window` de VE-07 (corta la misma fuente que el detector lee).
**Contexto** — El análisis del reel (VE-04) necesita cortes y fotogramas, y una parte «Igual al original» necesita una ventana ≥ 4 s de la fuente. No hay detector en el repo (E17) y el binario `ffmpeg` no está en producción (§1 #15). Diseño §4.1, §8.
**Qué hay que hacer**
- `qualify_creative/video/shots.py`: `ShotSpan`, `SamplingPlan`, `SampledFrame`; `detect_shots(data: bytes, *, max_seconds: float = 60.0) -> list[ShotSpan]` (diferencia de luminancia entre cuadros a baja resolución, umbral adaptativo, `DETECTOR_VERSION`); `sample_frames(data, spans, *, plan) -> list[SampledFrame]` (2 por plano ≥ 1 s al 15 % y 85 %, 1 si dura menos, anclas 0/1/3 s, tope 32 → 1 por plano, JPEG 720×1280, `SAMPLING_VERSION`).
- `qualify_creative/video/cut.py`: `cut_window(data, start_s, end_s, *, min_seconds: int = 4) -> FittedVideo` en segundos enteros (§1 #1), extendida hacia el vecino que se le indique, sin audio, H.264 `yuv420p`, `+faststart`; error tipado si la fuente no da 4 s.
- Importación perezosa de `av` como en `fit.py`; exportar en `video/__init__.py`.
**Criterios de aceptación**
- [ ] MP4 sintético generado con PyAV dentro del test (3 cortes conocidos): error ≤ 1 cuadro por corte; un fundido lento no cuenta como corte.
- [ ] `sample_frames` respeta el tope de 32 y trae el tiempo de cada fotograma; `cut_window(1,5 s)` devuelve 4 s enteros que contienen el plano, ± 1 cuadro.
- [ ] Ninguna dependencia nueva en `uv.lock`; funciones puras (sin base ni red); `just ci-test` verde.
**Fuera de alcance** — Haiku, R2 y `reel_analyses` (VE-03/VE-04). **Referencias** — diseño §4.1, §8; `fit.py:236-417`.

### 2.2 VE-06 · Generador: tipos del plan de partes y sus validadores
`Feature · P1 · M · Depende de: VE-01, VE-03 (CHECK de `content_briefs.kind`) · Bloquea: VE-08` · **Cambio:** suma la duración de las partes y la lista de sitios que enumeran `ContentKind`.
**Contexto** — Sin estos tipos nada del plan se puede guardar ni validar antes de pagar. Hoy una parte de 4, 6–9 s no pasa `_known_duration` (§1 #1). Diseño §8.
**Qué hay que hacer**
- `enums.py`: `ContentKind.SHOT_VIDEO` con formatos `(REELS_9_16, STORY_9_16)` en `_KIND_FORMATS` (`enums.py:498`), `requires_ai_disclosure` verdadero y **no** `is_video` (abre los caminos del presentador, `enums.py:378-386`).
- `schemas.py`: `PART_SECONDS = range(4, 11)`, `PARTS_MAX = 6`, `VideoPartPlan`, `PartRef`; `MediaInputs.parts` (padre) y `MediaInputs.part` (hija); `clip_reference_mode` admite `"extend"`. `_known_duration` acepta `PART_SECONDS` solo con `part`. `_kind_has_its_inputs`: padre con 1–6 partes y sin `clip_*`; hija = `CLIP` con `part`; `edit` con 1 video; `extend` nunca en la parte 1.
- Sitios que enumeran el tipo: `_KIND_ASSIGNMENT` (`brand/render.py:272`; sin entrada, el texto del padre falla al generarse), `printed_limits`, `weight_for_request` (§3), `generation_jobs` (padre → `[]`), `MediaProducer._produce` (padre sin video).
**Criterios de aceptación**
- [ ] Tests en `packages/creative/tests/test_content_kinds.py`: padre con 0 y 7 partes rechazado; hija de 3 y 11 s rechazada, de 4–10 s aceptada; `extend` en la parte 1 rechazado; los Clips actuales validan igual.
- [ ] `packages/api/tests/test_creative_kind_check_db.py` verde con la migración de VE-03 (`just test-db`).
- [ ] El texto del padre medido con `just eval-copy` antes y después (`eval-driven-dev`), sin regresión; `just ci-test` verde.
**Fuera de alcance** — Migración (BE). El selector de «¿Qué creamos?» NO muestra `shot_video` (UX §3.0); hoy `Qualify/test_creative_kinds.py:24-35` exige que liste todos los tipos: lo ajusta UI.

### 2.3 VE-07 · Video: unir partes con PyAV
`Feature · P1 · M · Depende de: VE-01 · Bloquea: VE-10a` · **Cambio:** sin `cut_window` (pasó a VE-02); recibe rutas en disco, no bytes; la memoria se mide en el contenedor, no en un test unitario.
**Contexto** — La unión local (opción A, diseño §5) es la que conserva lo aprobado y cuesta 0. `PyAvVideoFitter` no concatena ni funde audio (§1 #14). El worker tiene 512 MiB (E9).
**Qué hay que hacer**
- `qualify_creative/video/join.py`: `JoinClip(path, start_s, end_s)`, `join_clips(clips, *, size, fps=24, overlay=None, crossfade_audio_s=0.08) -> FittedVideo`, parte por parte (un decodificador abierto a la vez): recorte al intervalo, recorte-escala a `size`, fps común, logo una vez, audio decodificado → 48 kHz estéreo → fundido en cada corte → AAC; silencio para la parte sin pista; tiempos de audio desde las muestras decodificadas, no desde los paquetes.
- Refactor mínimo de `fit.py` para compartir `_frame_rate`, `_layer_frame` y el grafo recorte/escala, sin cambiar su salida.
**Criterios de aceptación**
- [ ] 3 clips sintéticos (uno sin audio, uno a 25 fps, uno de otro tamaño): duración = suma de recortes ± 1 cuadro, una sola pista de audio, H.264 `yuv420p`, `+faststart`, desfase audio-video al final ≤ 1 cuadro.
- [ ] Entrada HEVC de 10 bits (lo que entrega el 1080p de 2.5, `media.py:1631-1633`) cubierta por un test; si el codificador local no la produce, test `integration`.
- [ ] Pico de memoria uniendo 6 partes 1080p de 5 s medido con `deploy/measure/creative-worker-memory.sh` (con PL): < 60 % de 512 MiB, cifra en el PR.
- [ ] Sin dependencias nuevas; los tests de `fit.py` siguen verdes; `just ci-test` verde.
**Fuera de alcance** — Unión con `edit` de Seedance (VE-18/19), voz (VE-15). **Referencias** — diseño §5; `fit.py:236-417`.

### 2.4 VE-08 · Generador: plan desde el análisis, piezas hijas y «Crear otra versión» de una parte
`Feature · P1 · L · Depende de: VE-03, VE-06, columna de brief por versión (BE, §5) · Bloquea: VE-09, VE-11` · **Cambio:** cobro de vistas previas todo o nada; hijas sin Claude; brief por versión; aviso al padre.
**Contexto** — Cada parte es una pieza hija para iterarla sola (diseño §3). Hoy crear N piezas no es atómico (§1 #10), cada una llama a Claude (§1 #11) y una versión no recuerda su brief (§1 #12).
**Qué se quiere** — Como dueño de un negocio quiero que mi video se arme en partes que puedo rehacer una por una para cambiar solo lo que no me gustó.
**Propuesta** — `qualify_api/creative/parts.py`:
- `plan_from_analysis(analysis, *, products) -> tuple[VideoPartPlan, ...]` (puro): modo por `people_presence`/`visible_faces` (F6), fusiona planos < 4 s seguidos hasta 6, parte > 10 s en dos, fuente no 9:16 → `reference` (§6 N5).
- `create_parts(tenant_id, parent_id) -> list[UUID]`: en un `tenant_unit_of_work` inserta briefs e hijas, cobra **todas** las vistas previas con `charge_many` (nuevo en `creations.py`: una transacción, candado de la marca) y encola cada hija con `QueueDispatcher.dispatch_generation`. Rechaza si `queue_enabled()` es falso (`queue_dispatch.py:36-40`): en modo hilos el padre nunca se vuelve a unir.
- Hija sin Claude: `_copy_stage` (`service.py:2156`) escribe 1 variante heredada del padre, costo 0.
- `regenerate_part(tenant_id, parent_id, part_index, changes) -> UUID`: brief nuevo + `reject(regenerate=True)` (1 vista previa en `revision + 1`, `service.py:3405-3416`).
- `mark_parent_dirty(session, child_id)`: al terminar, fallar o restaurar una versión de una hija, sube `dirty_version` de la fase `join` del padre en la misma transacción.
**Criterios de aceptación**
- [ ] Con 3 vistas previas libres, pedir 4 partes no crea ninguna hija ni cobra nada (libro en memoria y `-m db`).
- [ ] 4 partes = 4 filas de `creation_charges` con `previews = 1`, 4 trabajos `preview`, 0 llamadas a Claude en las hijas (proveedor falso).
- [ ] «Crear otra versión» de la parte 2 cobra 1 vista previa, no toca las otras y la versión 1 sigue mostrando su descripción.
- [ ] El negocio A no crea, lee ni regenera partes de B (`tenant_session`, `-m db`); `just ci-test` y `just test-db` verdes.
**Fuera de alcance** — Análisis (VE-04), «Proponer partes» (VE-14), pantalla (VE-11).
**Estado (2026-11-05, rama `feat/m-24921065-partes-desde-analisis`, sin PR):** construido en `qualify_api/creative/parts.py` (`plan_from_analysis`, `check_extend_parts`, `PartsService.create_parts` / `regenerate_part` / `parts`, `check_parent_text_cap`, `mark_parent_dirty`), `charge_many` en los dos libros de `creations.py`, el enlace padre–hija en `service.py` (`check_part_link`, texto heredado sin Claude, `piece_versions.brief_id`) y `versions.restore` (vuelve el brief de esa versión). Sin migración (0119 basta). Criterios del ticket: 1 ✔, 2 ✔, 3 ✔, 4 ✔, 5 ✔ (las hijas no salen en «Por aprobar», galería, Planificador, «Tu semana», correo, archivos de piezas, adjuntos de WhatsApp ni anuncios; el padre da «Parte 2 de 4» con `PartsService.parts`), 6 ✔, 7 ✔ (20 textos nuevos por negocio y día, contados en `creation_charges`), 8 ✔. Pruebas: `test_creative_parts.py` (sin red) y `test_creative_parts_db.py` (`-m db`); `just ci-test` y `just test-db` completos quedan para CI (en local, sobre OneDrive, tardaban horas: se corrieron los archivos de creative, planificador, inicio, correo y WhatsApp). Desvíos y decisiones:
- **Plan:** nunca junta en una parte un corte «Igual al original» con uno con personas (P2); pasadas 6 partes junta primero vecinos del mismo modo y, si aún sobran, se queda con las 6 primeras. Un corte de más de 20 s da 3 partes (la 2.ª y 3.ª `extend`).
- **«Crear otra versión»** cambia descripción y fotos, no el modo (decisión provisional que se mantuvo: el modo cambia el precio y la ruta, y eso es otra parte, no otra versión).
- **Parte «Igual al original»:** `create_parts` recibe la ventana cortada por parte (`windows`); quien la corta es VE-04d/VE-09. Una parte con el aviso «Cuéntanos en una frase qué quieres que muestre» sin descripción no se crea. Dos pedidos a la vez de las mismas partes: el candado de la fila del padre los ordena y el segundo recibe las partes del primero.
- **Tope de texto del padre:** cuenta los «Pedir otra versión» del padre (no la creación de un padre nuevo ni «Crearla otra vez») y depende de que el libro de creaciones esté conectado (en producción lo está).

### 2.5 VE-09 · Generador: parte «Nueva, inspirada en el original» y parte «Igual al original»
`Feature · P1 · L · Depende de: VE-02, VE-08, `source_window` de VE-04 (BE) · Bloquea: VE-10a` · **Cambio:** razón tipada `refused_face`, sin caída «sin referencias», clave cruda anotada, claves de la parte bajo control de negocio.
**Contexto** — Absorbe m-24880681 (diseño §11). Hoy `PrivacyInformation` solo cambia el texto (§1 #17) y `_clip` puede rehacer la parte sin sus referencias (§1 #3).
**Qué se quiere** — Como dueño quiero que cada parte se haga igual al original con mi producto o nueva siguiendo lo que pasa en el original, para tener un video parecido al reel sin copiar a sus personas.
**Propuesta** — En `media.py`, `_part_clip` (llamado desde `_clip` cuando hay `media.part`):
- `reference`: fotos del producto + ficha del plano, **ningún** `reference_videos`; `edit`: la ventana de VE-02 (clave R2 del negocio que da `source_window`) + fotos, `ratio="adaptive"`, `duration_seconds=-1`, `omni_reference_task_type="edit"`. Ambas sin logo y sin la caída de `media.py:2626-2652`.
- `part_reference_prompt` / `part_edit_prompt` (un solo plano; paleta, tipografía y «No text on screen» como `clip_prompt`), `PART_PROMPT_VERSION` en `params`; `raw_key` (el `checkpoint_media` del worker) en el bloque `draft`; el modo se guarda en el bloque y `_final_video` lo lee de ahí (§1 #12).
- `FailureReason.REFUSED_FACE` y el texto de UX §4 («No pudimos usar el original en esta parte…») en lugar de `REAL_PERSON_TEXT` cuando lo rechazado es un video; las claves de `part` entran en `_key_problems`.
**Criterios de aceptación**
- [ ] Test de parámetros: `reference` sin `reference_videos`; `edit` con 1 video ≥ 4 s, `adaptive`, `-1`, `edit`; ninguna con logo; un fallo `ModelNotOpen` no rehace la parte sin referencias.
- [ ] `PrivacyInformation` simulado → hija `failed` con `refused_face`, su vista previa devuelta (`creation_charges.status = refunded`) y ningún reintento automático.
- [ ] Procedencia en la hija: análisis, plano, versión del prompt, modelo, costo (`creative_usage_events`).
- [ ] Una clave de otro negocio en `part` se rechaza antes de leer nada; `just ci-test` verde.
**Fuera de alcance** — Prueba viva (si se hace, se documenta en `docs/modelos-generativos/seedance-2-5.md` en el mismo turno, en horario de `qualify-measure` §8).

### 2.6 VE-10a · Generador: unir las vistas previas de las partes en el worker
`Feature · P1 · M · Depende de: VE-07, VE-09 · Bloquea: VE-10b, VE-11` · **Cambio:** VE-10 del diseño partido en dos; el padre no espera en `drafting` (§1, correcciones).
**Contexto** — La vista previa completa (480p, costo 0) aparece sola cuando todas las partes tienen la suya (UX §3e). Hoy el worker no conoce otra fase que `generation` y `final:` (§1 #6) y un video sin bloque `draft` es publicable (§1 #8).
**Qué hay que hacer**
- Rama `join` explícita en `PipelinePreparation.__call__` (`worker/pipeline.py:449-457`); un nombre de fase desconocido se marca fallido una vez, sin bucle.
- `MediaProducer.join_preview(tenant_id, parent_id) -> MediaWrite | None`: lee la versión activa de cada hija; si alguna falta, falló o venció, no hace nada; si no, `join_clips` a 480×854 y escribe el video del padre bajo `join-<huella>.mp4` (el bucket no deja sobrescribir) con bloque `draft` `{finish: "join", status: "join_preview", parts: [(hija, versión)], fingerprint, created_at: el de la hija más vieja}`.
**Criterios de aceptación**
- [ ] 3 hijas listas → 1 unión; regenerar o restaurar una versión de una hija → unión nueva con otra huella; 2 hijas que terminan a la vez → 1 unión correcta (concesión de `PipelineStore.acquire`, `pipeline.py:59-77`).
- [ ] La vista previa unida no es publicable (`draft_pending` verdadero; test con `planner/publishable.py`) y `_waiting_drafts` no la devuelve.
- [ ] El padre no queda en `drafting` esperando: `reap_stale_drafts` no lo toca aunque las hijas tarden 1 h (test).
- [ ] `just ci-test` y `just test-db` verdes.
**Fuera de alcance** — Aprobación y finales (VE-10b).

### 2.7 VE-10b · Generador: aprobar el video completo, finales de las partes y unión final
`Feature · P1 · L · Depende de: VE-10a; platform-engineer para la medición de memoria · Bloquea: VE-11 (aprobar), fase 2` · **Cambio:** cobro por hija con `charge_videos_many`; hijas aprobadas con su variante heredada; final de parte sin recodificar.
**Contexto** — Una sola aprobación del video completo (F8) cuenta N videos, todo o nada (D6). Cobrar en el padre rompe el ejecutor y la devolución (§1 #9).
**Qué se quiere** — Como dueño quiero aprobar mi video una sola vez y recibir el video final completo, para no decidir parte por parte lo que gasta mis videos del mes.
**Propuesta**
- `approve_parts(tenant_id, parent_id, variant_id, user_id)`: rechaza si la huella de la unión no es la de las versiones activas; `charge_videos_many` (nuevo en `creations.py`, 1 por hija, una transacción) con `uncharge` si algo falla después; aprueba padre e hijas por la máquina de estados; `_order_finals` por hija (carril nocturno de ADR 41). `approve()` rechaza `shot_video`.
- `_final_video` con `media.part`: estado `part_final`, guarda `raw_final` y no hace el ajuste H.264 (`media.py:1631-1666`): la unión es la única recodificación.
- Fase `join_final` del padre: con todas las hijas en `part_final`, une desde `raw_final` a 1080×1920, pone el logo una vez y deja el bloque del padre en `final_ready` con `final_sha256` y `final_object_key`: `confirm_final` (`final_review.py:77-95`) funciona sin cambios.
- Final de parte fallido → `_refund_final_part` de esa hija (sin cambios); unión final fallida → nada se cobra y el reintento parte de lo guardado.
**Criterios de aceptación**
- [ ] 3 hijas y 2 videos libres: aprobar no cobra ni aprueba nada; con 3, cobra 3 en una transacción y encola 3 finales nocturnos.
- [ ] `part_final` no aparece en `final_ready`, correo de la mañana, «Tu semana», galería ni Planificador (tests con BE sobre `home/summary.py`, `mail/final_summary.py`, `planner/draft_post_reader.py`).
- [ ] El unido final queda en `final_ready` y `confirm_final` lo vuelve publicable; «Pedir otra versión» después solo cobra las partes regeneradas.
- [ ] `just ci-test` y `just test-db` verdes; memoria de `join_final` medida como en VE-07.
**Fuera de alcance** — Pantalla (VE-11); reglas de cobro distintas de F1 (a) (VE-21).

### 2.8 VE-20 · Generador: las partes se conservan y se avisan con su video completo
`Improvement · P2 · S · Depende de: VE-10b` · **Nueva.** **Contexto** — §1 #19: las hijas no tienen eventos de calendario y caducarían solas, con avisos propios.
**Qué hay que hacer** — En `retention.py`, el plazo y la retención de una hija son los de su padre; las hijas no generan avisos; purgar el padre purga sus hijas.
**Criterios de aceptación** — [ ] reloj falso: hija de 100 días con padre programado no se purga · [ ] ningún aviso por hija · [ ] `just ci-test` verde.
**Fuera de alcance** — La fuente ajena del reel (VE-12, BE). **Referencias** — ADR 39; `retention.py:5-12`.

### 2.9 VE-13 · Generador: parte «Sigue a la anterior»
`Feature · P2 · M · Depende de: m-24880328, VE-10b` · **Cambio:** m-24880328 no tiene código (solo el adaptador valida `extend`, `byteplus_ark.py:886-893`) y es del área creative: entrega `clip_reference_mode="extend"` en `_clip`; VE-13 hace solo el cableado por parte.
**Contexto** — Una toma continua o un plano > 10 s (D5) necesitan continuar la parte anterior.
**Propuesta** — La hija `extend` usa el `raw_key` de la anterior, copiado a una clave `.mp4` sin recodificar (§1 #13); su preparación se aplaza sin capturar el pedido mientras la anterior no tenga vista previa (`waiting_previous`; el trabajo sigue `not_before = UNPREPARED` y el reaper la perdona por tener un trabajo `queued`, `dispatch.py:190-196`); si la anterior cambia, esta queda «Hay que rehacerla» y no se regenera sola. Si m-24880328 mide que `extend` no acepta borradores [H], la alternativa es continuar desde el último fotograma de la anterior como imagen de referencia.
**Criterios de aceptación** — [ ] estado `waiting_previous` y liberación al llegar la anterior · [ ] la unión no duplica cuadros, sea el resultado el tramo nuevo o el video entero (test sintético) · [ ] plano > 10 s → `reference` + `extend` · [ ] `just ci-test` verde.
**Qué se quiere** — Como dueño quiero que una parte empiece justo donde termina la anterior, para que se vea como un solo video. **Fuera de alcance** — Continuidad entre finales 1080p (VE-16, DS). **Referencias** — diseño §4.2, R3, R10; UX §2.

### 2.10 VE-14 · Generador: «Proponer partes» sin reel
`Feature · P2 · M · Depende de: VE-08` · **Cambio:** medición del prompt antes de activarlo.
**Propuesta** — `parts_ai.propose_parts(brief, angle) -> tuple[VideoPartPlan, ...]` con `claude_tools.strict_tool`, 3–6 partes en modo `reference`, `PROPOSE_PARTS_PROMPT_VERSION` en la procedencia; ningún video hasta «Crear las n partes».
**Criterios de aceptación** — [ ] con Claude simulado la salida valida como `VideoPartPlan` y se puede editar · [ ] 0 llamadas a Seedance (test) · [ ] 20 briefs reales (Bianki, Polette, la agencia) medidos con `qualify-measure` y documentados · [ ] `just ci-test` verde.
**Contexto y qué se quiere** — Sin reel el dueño no sabe por dónde empezar (UX §3a, entrada B): como dueño quiero que me propongan las partes desde lo que quiero contar, para crear con «Siguiente» y «Crear». **Fuera de alcance** — Proponer presentadores (VE-17). **Referencias** — diseño §3; ADR 32.

### 2.11 VE-15 · Generador: «Voz de tu marca» y subtítulos en el video completo
`Feature · P2 · M · Depende de: VE-10b` · Sin cambios de fondo; precisa que la mezcla es nueva (hoy el audio solo se copia, §1 #14).
**Propuesta** — En `join_preview`/`join_final`, Seed Speech con la voz de la marca (`seed-tts-1.0` o `seed-icl-2.0`, ya en `v7`, con guarda de precio y procedencia como el presentador) → mezcla en `join_clips` con el sonido de las partes atenuado → `PyAvVideoFitter.subtitle` con `voice_spans` (`video/speech.py:21`).
**Criterios de aceptación** — [ ] ningún audio del reel entra (test: la parte `edit` llega sin pista de la fuente) · [ ] subtítulos dentro de los tramos de voz ± 0,1 s · [ ] costo de la voz en `creative_usage_events` · [ ] `just ci-test` verde.
**Qué se quiere** — Como dueño quiero que mi video completo hable con la voz de mi marca y lleve subtítulos, para que se entienda sin sonido. **Fuera de alcance** — Música (sin licencia, diseño §5). **Referencias** — diseño §5 «Audio»; m-24828920.

### 2.12 VE-17 · Generador: parte con presentador (OmniHuman)
`Feature · P3 · L · Depende de: VE-10b; UI-10 · Etiqueta: Feature` · **Cambio:** guion por parte sin Claude; sin vista previa barata.
**Propuesta** — Hija `avatar_video` con motor `omnihuman` (trabajo `presenter`, `queue_dispatch.py:65-66`), `own_script` = su tramo del guion del padre, la misma foto y voz en todas, máximo 2. OmniHuman no tiene modo borrador: su video ya es el final → entra en `part_final` al crearse y se cobra en creaciones por segundos al crearse (`creations.py (creative):401-406`), no en videos; la vista previa unida lo baja a 480p; los subtítulos van una sola vez en la unión (no en la parte).
**Criterios de aceptación** — [ ] 2 presentadores + 2 de producto: cobro = creaciones de los presentadores + 2 vistas previas + 2 videos al aprobar · [ ] su audio se conserva en su tramo · [ ] un tercer presentador se rechaza · [ ] `just ci-test` verde.
**Qué se quiere** — Como dueño quiero que mi presentador abra y cierre el video y que mi producto se vea en medio, para presentar sin grabarme. **Fuera de alcance** — `edit` o `extend` sobre el presentador y sincronía de labios a través de un corte (diseño §6). **Referencias** — diseño §6; UX §3f y P3; `docs/omnihuman-caras-reales-y-edicion-seedance.md`.

### 2.13 VE-19 · Generador: «Suavizar las uniones con IA» (solo si VE-18 sale bien)
`Feature · P3 · M · Depende de: VE-18 (DS + CR)` · **Cambio:** usa el `raw_key` de cada parte (§1 #13) y cuenta 1 vista previa más (D7).
**Criterios de aceptación** — [ ] solo con partes de Seedance que sumen ≤ 30 s (test de rechazo) · [ ] pide aprobación nueva y nunca reemplaza la unión local aprobada sin confirmar · [ ] costo en `creative_usage_events`.
**Contexto y qué se quiere** — Como dueño quiero que las uniones entre partes se noten menos, solo si la prueba VE-18 muestra que no cambia mi producto. **Fuera de alcance** — Partes de presentador (no son salida de ModelArk, diseño §5). **Referencias** — diseño §5, opción B.

### 2.14 VE-21 · Generador: cobro de un video por partes si F1 no es «1 parte = 1 video»
`Feature · P2 · M (opción c) o L (opción b) · Depende de: VE-01 (F1), VE-10b` · **Nueva.** Solo existe si el fundador elige (b) o (c) del UX §7 P1. Alcance y costo en §3.

### 2.15 Bug relacionado (fuera de la épica) · Generador: la referencia de una diapositiva animada no pasa el control de negocio
`Bug · P1 · S · Sin dependencias` · **Qué pasa** — `_key_problems` (`media.py:523-549`) no incluye `slide.reference_video_key`, y `R2ReadingMediaStore.read` toma el negocio de la propia clave confiando en ese control (`media.py:577-584`): una clave `t/<otro negocio>/…` en el estado del carrusel se leería de R2 y se enviaría a BytePlus. [V] el hueco; [H] que la pantalla deje inyectar esa clave. **Arreglo** — añadirla a la lista; test con una clave de otro negocio rechazada antes de leer. **Criterios** — [ ] test nuevo · [ ] `just ci-test` verde. Debe ir antes de VE-09, que suma claves nuevas a la misma lista.

## 3. Cobro y cupo (D6, D7; F1)

**Hoy [V].** Al crear, `create_draft` cobra `weight_for(brief)` en la fila `(draft, revision)` de `creation_charges`, con `previews = price.videos` (`service.py:1688-1727`; `creations.py:447-468`): un Clip de 5 o 10 s usa 1 vista previa y 0 creaciones (`creations.py (creative):399-416`). Al aprobar, `_charge_videos` cobra `weight_for(brief).videos` en la **misma** fila (`service.py:2875-2928`). Un final fallido devuelve su video (`refund_final`, una vez por asset).

**Con F1 = (a) «cada parte = 1 video» (recomendación del diseño):**

| Pieza | Al crear (D7) | Al aprobar el padre (D6) | Dónde |
|---|---|---|---|
| Padre `shot_video` | nada (su texto con Claude no usa creaciones, como el de un Clip) | nada en su fila | rama nueva en `weight_for_request` → `CreationPrice("shot_video", 0, videos=0)` |
| Hija `clip` (4–10 s) | 1 vista previa, en su fila | 1 video, en su fila | sin cambio en los pesos: `video(seconds)` = 1 para todo ≤ 10 s |
| N hijas juntas | `charge_many`: N vistas previas en **una** transacción, todo o nada | `charge_videos_many`: N videos en una transacción, todo o nada | nuevos en `qualify_api/creative/creations.py` (y en el libro en memoria, `creations.py:888-930`); reusan `_lock`, `_state`, `shortfall`, `video_shortfall` y `_allocate`, así los paquetes de 90 días (m-24852129) pagan igual que hoy |

- **No hace falta `pesos-creaciones-v3` ni una tabla de precios nueva** [V]: la regla «1 video de hasta 10 s = 1» ya es D5 y cada fila sigue anotando `weights_version` y `pricing_table_version`. La regla 1 del área (precio nuevo = versión nueva) no se dispara.
- Para la pantalla: «Lo que usa de tu mes» = suma de `weight_for_request` por parte antes de crear; `approval_videos(padre)` = suma de `_videos_of(hija)`. Lo absorben VE-08 y VE-10b.

**Si el fundador elige otra regla en F1 (UX §7 P1) → VE-21:**

| Opción | Qué cambia | Tamaño |
|---|---|---|
| (b) segundos de video al mes | Cambia D5 para **todos** los videos (Clip, galería, avatar de Seedance), no solo las partes: `pesos-creaciones-v3` con `videos.monthly_seconds`, `CreationPrice.video_seconds`, saldo y reparto por segundos (columna nueva en `creation_charges` → BE), cupos por plan en `qualify_api/plans/catalog.py`, y todos los textos «videos del mes» (UI) | L + migración + UI |
| (c) 1 video por video completo, 1 vista previa por parte | `weight_for(padre).videos = 1` cobrado en la fila del padre; el ejecutor debe aceptar el final de una hija cuya fila tiene `videos = 0` si la del padre tiene 1 (`worker/pipeline.py:218-221`, código de ADR 41) y hay que decidir cuándo se devuelve ese único video (¿si falla cualquier final o solo si fallan todos?). Con 30 s en 6 partes ≈ USD 14–24 por «1 video» (diseño §9) frente a los ≈ 6,82 por video que supone el techo de D5: 4 al mes podrían costar ≈ USD 97 frente a 27 | M en creative + revisión de platform-engineer |

## 4. Precio de «Crear otra versión» de una parte y del reintento tras `refused_face`

**Hoy [V].** «Pedir otra versión» es `reject(regenerate=True)`: cobra `weight_for(brief, redo=True)` en `(draft, revision + 1)` **antes** de escribir nada (`service.py:3405-3416`); el costo de proveedor de cada llamada pagada va a `creative_usage_events` (`service.py:2421-2440`, solo lo pagado: un rechazo no deja fila). Si la regeneración falla o se conserva la versión anterior, `_refund_if_not_delivered` devuelve la vista previa (`service.py:2016-2037`). BytePlus no cobra una generación fallida o moderada [D] (`byteplus_ark.py:17-18`).

| Caso | Dueño | Equipo (USD) | Registro |
|---|---|---|---|
| «Crear otra versión» de una parte | 1 vista previa en la hija; 0 videos hasta aprobar | 0,41–0,62 por parte de 4–6 s (diseño §9) + 0 la unión nueva | fila nueva `(hija, revision + 1)` en `creation_charges`; filas de Seedance en `creative_usage_events` |
| Lo mismo con el video ya aprobado (`final_ready`) | 1 vista previa + 1 video **solo** por cada parte regenerada; las demás conservan su final | + el final 1080p de esa parte | `_videos_of` da 0 a las hijas cuyo final existe (`service.py:2893-2906`): ADR 41 §3.5 se cumple sin código de cobro nuevo |
| Rechazo `refused_face` | la vista previa vuelve sola (hija `failed` o «se conservó la anterior») | 0 [D] | la fila queda `refunded` con `refund_reason`; hoy el motivo sale `provider_error` |
| «Hacerla nueva» tras el rechazo | 1 vista previa (neto: 1, como si hubiera salido a la primera) | lo de una parte `reference` | igual que «Crear otra versión» |

**Qué cambia:** solo `FailureReason.REFUSED_FACE`, para que la devolución y el estado digan por qué (VE-09), y `regenerate_part` (VE-08). `creation_charges` y `creative_usage_events` no cambian de esquema.

## 5. Orden de entrega y lo que no es del área creative

Un PR por historia (`qualify-pr`), cada uno con su `m-<id>`. Tras la firma de VE-01:

| Orden | PR | Puede ir en paralelo con | Espera a |
|---|---|---|---|
| 1 | Bug §2.15 (claves de la diapositiva) | todo | — |
| 2 | VE-02 (planos, fotogramas, ventanas) | VE-07, VE-03 (BE) | — |
| 3 | VE-07 (unión) | VE-02, VE-03 | — |
| 4 | VE-06 (tipos) | VE-04 (BE) | VE-03 en `main` (el test del CHECK) |
| 5 | VE-08 (hijas, cobro de vistas previas) | VE-11 sobre servicios falsos (UI) | VE-06 y la columna de brief por versión (BE) |
| 6 | VE-09 (las dos formas de parte) | VE-05 (DS) | VE-02, VE-08 y `source_window` (VE-04) |
| 7 | VE-10a (unión de vistas previas) | — | VE-07, VE-09 |
| 8 | VE-10b (aprobar, finales, unión final) | — | VE-10a; arnés de memoria (PL) |
| 9 | VE-20 (retención de partes) | fase 2 | VE-10b |
| fase 2 | m-24880328 → VE-13; VE-14 ∥ VE-15; VE-21 solo si F1 ≠ (a) | entre sí | VE-10b |
| fase 3 | VE-17; VE-18 (DS) → VE-19 | — | VE-10b |

**Visto en el código y fuera de esta área** (sin historias escritas aquí):

- **backend-engineer:** en la migración de VE-03 (el siguiente número libre después de R3), además de lo del diseño, guardar qué brief usó cada versión (`piece_versions.brief_id` o equivalente, §1 #12); excluir hijas (`parent_draft_id IS NOT NULL`) del Planificador (`planner/publishable.py`, `planner/draft_post_reader.py`), del correo de la mañana (`mail/final_summary.py`), de «Tu semana» (`home/summary.py`) y de las listas de piezas; `source_window` llama a `cut_window` (VE-02); progreso por parte en `queue_visibility.py` si la pantalla lo pide.
- **platform-engineer:** confirmar `QUALIFY_CREATIVE_DISPATCHER=queue` en producción (no aparece en `deploy/` salvo `deploy/measure/creative-worker-memory.sh:73`; mismo hallazgo que RN10 del traspaso de backend); escenario de unión en `deploy/measure/creative_worker_memory.py`; decidir si 512 MiB alcanzan con `QUALIFY_CREATIVE_WORKER_DOWNLOADS=2` más una unión 1080p.
- **reflex-ui-engineer:** `KIND_OPTIONS` sin `shot_video` y su test (`Qualify/test_creative_kinds.py:24-35`); dónde se guarda «Me gusta así» (ni el diseño ni la máquina de estados lo guardan); «Aprueba antes del …» con los bloques de las hijas (§1 #20); textos que reemplazan `REAL_PERSON_TEXT` en pantalla.
- **principal-architect:** enmienda de ADR 41 §3.2 con `part_final` y el bloque `join` del padre; que los estados del padre sean calculados y no estados nuevos de `fsm.py`; aprobar las hijas con la variante heredada del padre.

## 6. Riesgos técnicos que el diseño no nombró

| # | Riesgo | Efecto | Mitigación (historia) |
|---|---|---|---|
| N1 | El padre espera a sus hijas en `drafting` [V] | `reap_stale_drafts` lo falla a los 20 min y devuelve lo cobrado mientras las hijas siguen | El padre solo hace el texto y queda `generated`; la unión es la fase `join` (VE-10a) |
| N2 | Video unido sin bloque `draft` [V] | La vista previa de 480p es publicable | Bloque `finish: "join"` (VE-10a) |
| N3 | Videos cobrados en el padre [V] | Todo final de parte se rechaza («final video has no reserved plan unit», `worker/pipeline.py:218-221`) | `charge_videos_many` en las hijas (VE-10b) |
| N4 | Doble recodificación del 1080p: 2.5 entrega H.265 de 10 bits, `_final_video` lo pasa a H.264 y la unión lo recodificaría otra vez [V] | Pérdida de detalle y el doble de CPU en un worker de 512 MiB | Unir desde `raw_final`; la parte no se ajusta (VE-10b) |
| N5 | Lienzos mezclados: `edit` con `adaptive` conserva el lienzo de la fuente (`media.py:2662`); `reference` sale a 480×854 o 1080×1920 [V] | Si el reel no es 9:16, la unión recorta las partes `edit` y se pierde el encuadre que se quería conservar | El plan manda a `reference` las fuentes que no son 9:16 (VE-08); cuántos reels lo son, [H] a medir en VE-05 |
| N6 | Audio: partes sin pista (sin `generate_audio`, OmniHuman) y retardo del codificador AAC por tramo [H] | Una pista cortada o un desfase que crece en 6 cortes | Tiempos desde muestras decodificadas y silencio sintético (VE-07) |
| N7 | La caída «sin referencias» de `_clip` [V] | Una parte hecha sin sus referencias y un trabajo extra creado sin aviso (§1 #3) | Desactivada para partes (VE-09) |
| N8 | Aprobar una unión vieja mientras una parte se regenera | El final incluiría una versión que el dueño no vio | Huella de versiones en el bloque `join`; `approve_parts` la compara (VE-10b) |
| N9 | El tope en dólares del negocio (`budget_state`) se revisa llamada por llamada [V] | De 6 partes pasan 4 y 2 fallan `budget_exceeded` | `create_parts` estima el total con `generated_video_usd` (`creations.py (creative):200-222`) y lo revisa una vez (VE-08) |
| N10 | R2 no deja sobrescribir una clave (`media.py:1585-1588`) [V] | Una segunda unión con la misma clave falla | Una clave por unión, `join-<huella>.mp4` (VE-10a) |
| N11 | La salida cruda se guarda como `.bin` y `_reference_urls` la rechaza [V] | `extend` (y la unión con IA) no pueden usarla tal cual | Copia a `.mp4` sin recodificar (VE-13, VE-19) |
| N12 | Hueco de claves de la diapositiva animada [V] | Lectura de archivos de otro negocio [H] | Bug §2.15 antes de VE-09 |

## 7. Lo que necesita al fundador

- **F1 (cobro):** con (a) todo cabe en VE-08/VE-10b sin tabla nueva; con (b) o (c) se suma VE-21 (§3). La pantalla necesita una sola cifra antes de «Crear».
- **Operación:** confirmar que producción corre `QUALIFY_CREATIVE_DISPATCHER=queue` antes de la fase 1: VE-08 rechaza el modo con hilos.
- **Para el arquitecto, no para el fundador:** estados calculados del padre y aprobación de las hijas con la variante heredada (§5).
