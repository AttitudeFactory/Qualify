# Video por partes: armarlo desde un reel (o sin él), parte por parte, y unirlo

**Estado:** `[PROPUESTO]` — principal-architect, 2026-11-02. Nada se construye hasta que el fundador decida el §11. Propone el **ADR 44** (el último firmado es el 43, `docs/arquitectura.md:300`).
**Pedido:** Deivid, 2026-11-02 (generador de videos, «Crear pieza»). **Tickets que toca:** m-24880680 (D1–D3), m-24888194, m-24880681, m-24820834, m-24880378 / m-24880328, m-24851828; ADR 39, 41 y 42.
**Evidencia:** lectura de `main` en `56746531`; ninguna llamada pagada. **[V]** = verificado en disco o medido en el repo · **[D]** = documentación de BytePlus citada en el repo, sin prueba propia · **[H]** = hipótesis o cálculo sobre supuestos.

## 1. Resumen

1. El video se arma con **partes** (hasta 6). Cada parte es un plano del reel de referencia que detecta el código (PyAV, sin dependencia nueva) y describe Haiku (`claude-haiku-5-5`, familias D3, rostros en la misma llamada: D2), o una parte que agrega el dueño sin reel.
2. **Cada parte es una pieza hija** (`content_drafts.parent_draft_id`) con su propio prompt, referencias, modo (`reference`, `edit` o `extend`), vista previa, versiones y final. Reutiliza el camino del Clip, la cola de ADR 41 (ya construida) y `piece_versions`: **ningún tipo de trabajo nuevo en la cola**.
3. **La unión es local y determinista** (PyAV, costo 0): cortes entre partes, como en el reel original. Unir con `edit` de Seedance queda como experimento medido (fase 3): no siempre es más caro, pero vuelve a generar cada cuadro, cambia lo aprobado, no pasa de 30 s y no acepta partes de OmniHuman.
4. Modo por defecto: `edit` para partes sin personas observadas; `reference` (fotos del producto + ficha de Haiku, **sin bytes del reel**) con personas o duda; `extend` solo para continuar la parte anterior.
5. Costo calculado: 15 s en 4 partes ≈ USD 7,9–13,7; 30 s en 6 ≈ USD 14,0–24,2 (el análisis ≈ 0,005). Con la regla firmada D5, **cada parte cuenta 1 video**: un video de 4 partes gasta el mes del plan Básico. Es la decisión principal (F1).

**Nombre en pantalla:** se adopta el de ux-designer (`docs/ux-video-por-planos.md` §2, escrito en paralelo): la opción es **«Video por partes»**, cada pedazo es una **«parte»** («Parte 2 de 5»; nunca «plano», «clip» ni «toma»), la entrada desde un reel es **«Hacer uno parecido»** (ADR 42 R14) y sin reel **«Armar mi video por partes»**. Modos: `edit` = «Igual al original, con tu producto»; `reference` = «Nueva, inspirada en el original»; `extend` = «Sigue a la anterior». Una parte se da por buena con «Me gusta así»; **«Aprobar» se reserva para el video completo**, que es lo que gasta videos del mes. En este documento, «parte» = el plano generado (pieza hija) y «plano» = el corte detectado en el reel ajeno.

## 2. Qué existe hoy (medido)

| # | Hecho | Dónde |
|---|---|---|
| E1 | «Replicar con mi marca» prepara el reel dentro del evento de Reflex (`asyncio.to_thread`), sin worker | `Qualify/discover_reels.py:314`; botón `:796` |
| E2 | Descarga solo de CDN permitidos, sin redirecciones, ≤ 80 MiB; recorta a **5 s**, H.264 sin audio, ≥ 407.696 px, 24–60 fps; rechaza < 4 s | `qualify_api/referentes/reel_reference.py:16-20, 46, 76-96` |
| E3 | El archivo preparado va al disco de subidas de Reflex (`rx.get_upload_dir()/uploads/{tenant}/…`), no a R2 | `Qualify/reel_replication.py:27-38` |
| E4 | La procedencia del reel viaja en el brief (`MediaInputs.source_reel`, `analysis_version = 1`), sin migración | `qualify_creative/schemas.py:445, 554`; `referentes/reels_ai.py:57` |
| E5 | El Clip `edit` exige 1 video + fotos, y que la referencia dure lo pedido ±0,5 s; las duraciones válidas son 5, 10, 15, 30, 45 y 60 | `schemas.py:56, 637-645`; `creative/media.py:2621-2634` |
| E6 | `edit` sale con `ratio=adaptive` y `duration=-1`; las fotos van como imágenes de referencia; el logo se pone en cada clip después de Seedance | `media.py:2675-2680, 2788`; `reel_edit_prompt` vía `clip_prompt` `media.py:4657` |
| E7 | Seedance 2.5 genera **4–30 s** con hasta 30 imágenes, 10 videos y 10 audios; `edit`/`extend` exigen video y `adaptive`; nada mide aún que un `edit` dure 4–30 s (comentario del código) | `adapters/byteplus_ark.py:66-75, 223-237, 249, 878-893` |
| E8 | El carrusel ya hace «partes»: cada diapositiva animada es un trabajo `carousel_scene` propio; la preparación las captura todas en una pasada (atrapa `GenerationDeferred` por diapositiva) y cada una tiene su final | `creative/queue_dispatch.py:56-66, 88-104`; `media.py:3049, 3093` |
| E9 | **La cola de ADR 41 está construida:** `creative_jobs` y `vendor_slots` (0096), checkpoints `creative_pipeline_runs/steps` (0098), intentos de final (0099), `creative-worker` en el compose de producción con `mem_limit: 512m` | `migrations/postgres/versions/0096…0099`; `creative/worker/`; `deploy/docker-compose.prod.yml:492-511` |
| E10 | El worker conoce dos fases, `generation` y `final:<asset>@<intento>`, y descubre negocios con `SELECT DISTINCT tenant_id FROM creative_jobs` | `creative/worker/pipeline.py:406-466` |
| E11 | `PipelineStore.video_job` une cada llamada de video con su trabajo **por orden de llamada**, no por posición | `creative/pipeline.py:168-205` |
| E12 | Clave natural de un trabajo: `(tenant, draft, kind, revision, position, final_attempt)`; `kind` ∈ {`preview`, `final`, `presenter`, `carousel_scene`} | `0096`, `0099`; `creative/job_queue.py:50-54` |
| E13 | Todo final queda en `final_ready` hasta que el dueño lo confirma; `draft_pending` impide publicar un video que no sea `final` | `creative/draft_mode.py:29, 46`; ADR 41 §3.2 |
| E14 | Versiones por pieza (`piece_versions`, `active_version_id`): regenerar conserva lo anterior | `0103_piece_versions.py` |
| E15 | `PyAvVideoFitter` recorta, superpone capa y logo, pone subtítulos y conserva audio; **no concatena** | `qualify_creative/video/fit.py:98-190` |
| E16 | La imagen `app` de producción **no instala el binario `ffmpeg`**; PyAV trae FFmpeg en sus ruedas | `deploy/Dockerfile:145-147`; `packages/creative/pyproject.toml:45-47` |
| E17 | No hay detector de planos en el repo (ni PySceneDetect ni OpenCV) | búsqueda en `packages/` |
| E18 | Las tablas de ADR 42 (`public_reels`, `brand_reel_*`) **no existen**; la lista de reels vive en la memoria de Reflex | `migrations/` sin coincidencias; `Qualify/reels_discovery.py` |
| E19 | Cupo firmado: cada video de Seedance (5 o 10 s) cuenta 1 de 4 / 8 / 16 videos al mes al aprobar; un carrusel con N diapositivas animadas usa N; cada vista previa cuenta 1 de 20 al crearse | `docs/modelo-cobro-generacion.md` D5–D7; `creations_data/pesos-creaciones-v2.json` |
| E20 | Medido: borrador `edit` 5 s con el reel = USD 0,597–0,617 (sale de 4,708 s); borrador sin video 5 s = 0,53; final 1080p sin video 5 s = 2,87, en 38 s | `docs/replicador-seedance-sin-vlm.md`; `docs/modelos-generativos/seedance-2-5.md` SD25-001/002 |

## 3. Modelo conceptual

```
Reel de referencia (URL del CDN, caduca en 24–33 h)
 └─ Análisis (versión inmutable, por negocio) ............................ qualify_api.referentes
     ├─ fuente completa normalizada en R2 del negocio (sin audio)
     ├─ transcripción con tiempos del proveedor, si hay ........ D1: audio y texto van aparte
     └─ planos: intervalo, fotogramas, ficha Haiku por familia D3,
        people_presence / visible_faces ∈ {observed, not_observed, unknown}
Video por partes (pieza padre, kind = shot_video) ........................ qualify_api.creative
 ├─ plan: partes en orden (de un plano, agregadas por el dueño o propuestas por IA)
 ├─ parte k = pieza hija (kind clip): modo, prompt, referencias, segundos, recorte
 │    └─ iteraciones = versiones de la hija (piece_versions)
 ├─ vista previa completa = unión local de las vistas previas activas (480p, costo 0)
 ├─ UNA aprobación del video completo → finales 1080p de cada parte (carril nocturno)
 └─ unión final local → final_ready → confirmación del dueño (ADR 41) → publicable
```

- **El extractor no ve la marca ni métricas** (m-24880680). La adaptación a la marca la hace el generador al escribir el prompt de cada parte.
- **Una parte es un plano por defecto.** Un plano < 4 s (mínimo de Seedance, E7) se genera a 4 s y se recorta al unir; uno > 10 s (tope por video de D5) se parte en dos partes, la segunda en `extend`. Con más de 6 planos, el plan propone fusionar planos cortos seguidos; el dueño puede separarlos.
- **La intención no cambia sola:** una persona detectada no convierte el Clip en Avatar (m-24880680).
- **Sin reel:** el dueño agrega partes (descripción + fotos, videos o audios propios) o pide «Proponer partes» (fase 2: el modelo de ángulos de ADR 32 devuelve 3–6 partes desde el brief). El resto del flujo es igual.
- **Por qué piezas hijas y no N videos dentro de una pieza:** (1) iterar una parte es regenerar la hija, con sus versiones, sin tocar las demás; (2) cada hija tiene un solo trabajo de video, así que el emparejamiento por orden de llamada (E11) no se rompe cuando una parte `extend` espera a la anterior; (3) cobro, final, caducidad y reintentos ya existen por pieza; (4) la clave natural de la cola no cambia.

### 3.1 Estados de una parte (pieza hija)

| Estado | Qué significa | Sale por |
|---|---|---|
| `planned` | En el plan, sin generar | «Generar partes» |
| `queued` / `generating` | Trabajo `preview` en `creative_jobs` | respuesta del proveedor |
| `waiting_previous` | `extend` esperando la vista previa de la parte anterior | se libera sola |
| `preview` | Vista previa activa (480p; el borrador del proveedor vive 7 días) | «Crear otra versión» (de una parte) (versión nueva) o aprobación del padre |
| `failed` | Error del proveedor o local, con su motivo | «Probar otra vez» |
| `refused_face` | BytePlus rechazó el video de entrada (`PrivacyInformation`, `media.py:749, 809`) | «Hacerla sin el video original» (pasa a `reference`); la vista previa se devuelve (D7: el proveedor no entregó nada) |
| `expired` | Pasaron 7 días (`draft_expired`, `draft_mode.py:65`) | solo regenerar |
| `final_scheduled` / `rendering` | Final 1080p en la cola (carriles de ADR 41) | respuesta del proveedor |
| `part_final` | **Nuevo.** Final de parte listo. **No es publicable ni se confirma:** no entra en `final_ready`, ni en el correo de la mañana, ni en «Tu semana» | unión final |
| `cancelled` | Cancelada antes de enviarse | — (lo ya enviado se cobra y se guarda) |

### 3.2 Estados del video completo (pieza padre)

`analyzing` → `planning` → `generating` → `previewing` (todas las partes en `preview` y la vista previa unida lista) → `approved` (se piden N finales y se cobran N videos, D6) → `joining` → `final_ready` (ADR 41) → `final` (confirmado) → publicable.

- Una parte `failed`, `refused_face` o `expired` devuelve el padre a `generating`, con aviso de cuál.
- **El plazo del padre es el de su parte más vieja** (borrador + 7 d − 15 min, ADR 41 §3.1); la pantalla dice «Aprueba antes del …». Pasado el plazo, se regenera esa parte.
- Si la unión final falla, los finales pagados quedan guardados (`raw_final`) y reintentar cuesta 0.
- «Pedir otra versión» en `final_ready` vuelve a `previewing`; solo cuestan las partes que se regeneran (1 vista previa + 1 video cada una, como ADR 41 §3.5).
- Cancelar el padre cancela los trabajos `queued` de sus hijas (`job_queue`); los ya enviados terminan y se guardan.

## 4. Ruta de generación por modo

### 4.1 El análisis del reel (recomendaciones; deciden F3 y F4)

- **Cuándo:** al pulsar «Hacer uno parecido» o «Replicar», **no al listar**. Se analizan los reels que alguien elige, no las 6–8 ideas de cada semana, y abrir sigue sin gastar (ADR 42). Se reutiliza si ya existe para el mismo `(red, post_id, sha256 de la fuente, versión)`.
- **Dónde corre:** tarea en segundo plano de Reflex que llama a `qualify_api.referentes.reel_analysis.run_analysis`; la fila es el estado durable (concesión de 2 min, idempotente: si un despliegue la corta, la siguiente apertura la retoma). No usa `creative-worker`: su puerta solo tiene GRANT sobre `creative_jobs` y `vendor_slots`, y darle otra tabla es cambiar ADR 41 (docstring de 0096). Costo ≈ USD 0,005, sin cobro al dueño; guardián: 20 análisis por negocio y día.
- **Alcance:** **el reel completo hasta 60 s**, no 5 s. La fuente completa normalizada (la de E2 sin el recorte) va a R2 del negocio y sirve para cortar las partes `edit`. Se registra el intervalo cubierto: nunca se afirma haber visto lo que no se analizó.
- **Planos:** detector propio en PyAV (diferencia de luminancia entre cuadros seguidos a baja resolución, con umbral adaptativo); `detector_version` y umbral van en la procedencia. Sin PySceneDetect (trae OpenCV) ni el binario `ffmpeg` (no está en producción, E16). Se reabre si el F1 de cortes queda < 0,85 a ±0,25 s en la medición VE-05.
- **Muestreo:** por plano, 2 fotogramas (al 15 % y al 85 % del intervalo) si dura ≥ 1 s y 1 si dura menos: el movimiento de cámara solo se afirma con dos momentos (contrato D3). Más 3 anclas del gancho (0,0 s, 1,0 s y 3,0 s). Tope de 32 imágenes; si se pasa, 1 por plano. Resolución 720×1280 (1.196 tokens por imagen, legible para el texto en pantalla). [H] 32 × 1.196 + 2.000 de instrucciones ≈ 40.300 tokens de entrada + ≈ 3.000 de salida ≈ **USD 0,0055** por reel (tarifa `v7` de Haiku 5.5: 0,10 / 0,50 por millón), lejos del umbral de 100.000 tokens.
- **Una sola llamada a Haiku** con herramienta estricta (`claude_tools.strict_tool`): por plano, las familias D3 con `observed | not_observed | unknown`, el fotograma que sostiene cada dato, y `people_presence` / `visible_faces`; para el reel, gancho, estructura narrativa, cierre y llamado a la acción, estilo y tono. **Audio y voz:** solo la transcripción con tiempos del proveedor (`transcript_with_timestamp` de Instagram, m-24888194), asignada a cada plano por tiempo; música y voz = `unknown` (Haiku no oye, D1). La transcripción **nunca** se vuelve el guion de la marca.

### 4.2 Qué significa cada modo para una parte del reel

| Modo | Qué hace | Entradas a BytePlus | Restricciones (fuente) | Por defecto cuando |
|---|---|---|---|---|
| `edit` | Rehace **ese plano** con el producto y la marca: conserva encuadre, cámara y acción | corte del plano desde la fuente (≥ 4 s) + fotos del producto | video de 4–30 s, `adaptive`, `duration=-1`; sale hasta 0,4 s más corto; el prompt debe pedir «edit / replace…» o falla con `TaskTypeMismatch`; un rostro real da `PrivacyInformation`, sin interruptor [D] | `people_presence` y `visible_faces` = `not_observed` |
| `reference` | Crea un plano nuevo que **sigue la ficha de Haiku** (encuadre, cámara, acción, ambiente) con el producto | fotos del producto y referencias propias que agregue el dueño; **ningún byte del reel** | sin video de entrada, tarifa sin video [V]; se pide 4–10 s y se recorta al unir | personas o rostros `observed`, o `unknown`; partes sin reel |
| `extend` | **Continúa la parte anterior** ya generada (una toma continua) | la salida cruda de Seedance de la parte anterior | `adaptive`, 4–30 s [D]. **No verificado:** si devuelve solo el tramo nuevo o el video entero, y si admite borrador (lo mide m-24880328). Las salidas propias de los últimos 30 días se aceptan aunque tengan rostro, **solo si no se editaron ni recomprimieron** [D] | plano > 10 s partido en dos; o elección del dueño |

**Plano corto en `edit`** (uno de 1,5 s no cabe en el mínimo de 4 s): se corta una **ventana de 4 s** de la fuente que contiene el plano, extendida hacia el vecino sin rostros (si los dos vecinos tienen rostros, la parte pasa a `reference`); Seedance edita la ventana y la unión se queda con el intervalo del plano. Se pagan 4 s para usar 1,5: por eso el plan propone fusionar planos cortos. En `reference` se piden 4 s y se recorta igual.

**Cambios al código existente:** (a) las partes aceptan **4–10 s enteros** (`PART_SECONDS`) y el corte de `edit` se hace a segundos enteros, así el chequeo ±0,5 s de `media.py:2632` sigue valiendo; (b) `clip_reference_mode` gana `"extend"`, que construye m-24880328 y esta épica consume; (c) las partes se generan **sin logo** (va una vez en la unión) y **se guarda la salida cruda** de Seedance de cada parte, necesaria para `extend` y para el experimento de unión; (d) sonido: cada parte con `generate_audio` como hoy (no suma tokens, revisión v2 de `seedance-2-5.md`); (e) el prompt de cada parte lo escribe el generador desde la ficha + Brand Kit + producto (`part_reference_prompt`, `part_edit_prompt`, `part_extend_prompt`), con su versión en la procedencia de la hija.

## 5. La unión

| | A. Concatenación local (recomendada) | B. `edit` de Seedance sobre las N partes (lo pedido) |
|---|---|---|
| Qué es | PyAV recorta cada parte a su intervalo, iguala tamaño y fps, concatena, funde el audio 80 ms en cada corte y pone el logo y, si hay, subtítulos | Mandar las partes como `reference_videos` con `omni_reference_task_type=edit` y un prompt de unión |
| Costo de la unión | **0** | vista previa: entrada + salida a 6,40/M; final 1080p a 7,00/M sobre la salida (y quizá la entrada: no medido) |
| Costo total | §9 | **Puede salir más barato que A**: las partes solo necesitan vista previa y hay un único final (§9). No se descarta por precio |
| Determinismo | Total: lo aprobado es lo que se publica | Vuelve a generar todos los cuadros, sin máscara [D]: puede cambiar el producto o una parte aprobada; hay que aprobar de nuevo |
| Límites | Ninguno práctico | ≤ 10 videos y **30 s de entrada en total** [D]: no existe una unión de 45 o 60 s |
| Partes de presentador (OmniHuman) | Sí | No: OmniHuman no es salida de ModelArk y se rechazaría por rostro [D] |
| Partes propias con rostro | Sí | Solo con la salida cruda sin editar [D]; reenviarla por `/public/media` no está probado [H] |
| ¿Une de verdad? | Cortes duros, igual que el reel: **cada parte es un plano y el corte entre planos es lo natural** | Que `edit` con varios videos los encadene **no está documentado para 2.5** [H]; en 2.0, `extend` con 2–3 clips «rellena la transición» [D] |
| Encaje con la cola | Fase local `join` del padre en el worker, sin trabajo en `creative_jobs` | Un trabajo `preview` y luego `final` del padre (tipos que ya existen) |

**Recomendación:** A por defecto. B se ofrece solo como **«Suavizar las uniones con IA»** en la fase 3, después de una prueba medida (VE-18: 3 uniones de 15 s — ¿encadena?, ¿cambia el producto?, ¿el final cobra la entrada?) y solo si todas las partes son de Seedance y suman ≤ 30 s. En la misma prueba se mide una variante barata: `extend` sobre un solo corte (final de una parte + inicio de la siguiente, 4 s) para un puente, pegado localmente.

**Audio:** nunca el del reel (E2 lo quita y el análisis no lo guarda). Fase 1: el sonido que genera Seedance en cada parte, con fundido corto en los cortes. Fase 2: **«Voz de tu marca»**, locución de Seed Speech con la voz de la marca sobre el video unido (bajando el sonido de las partes) y subtítulos con `PyAvVideoFitter.subtitle` + `voice_spans` (`video/speech.py:21`). Sin biblioteca de música: no hay licencia y la API de Meta no agrega música al publicar.

**Texto y logo:** el logo una sola vez en la unión (hoy se pone por clip, E6); los textos del reel ajeno nunca se copian; gancho y llamado a la acción propios como capa (`text_layer`) en la primera y la última parte.

**Memoria:** `creative-worker` tiene 512 MB (E9). La unión decodifica y codifica parte por parte, sin cargar todos los cuadros a la vez.

## 6. Avatares

Propuesta mínima (fase 3): un tipo de parte **«Presentador»** = pieza hija `avatar_video` con OmniHuman (foto + voz de Seed Speech, `media.py:3757`), intercalada con partes de producto de Seedance y unida localmente (A). El audio del presentador se conserva en su intervalo; las partes de producto llevan su sonido o la locución.

- **Máximo 2 partes de presentador por video:** OmniHuman admite 1 tarea a la vez y dos ya hacen fila de ~12 min (ADR 41 §1.1).
- La misma foto y la misma voz en todas las partes del presentador, para que sea la misma persona.
- Se cobran como hoy, en creaciones por segundos (`presenter_by_seconds`), no como videos.
- **Fuera:** `edit` o `extend` de Seedance sobre el presentador (no es salida de ModelArk; exige la biblioteca de personas reales, solo por invitación: `docs/omnihuman-caras-reales-y-edicion-seedance.md` §2.2–2.3); sincronía de labios a través de un corte; un presentador que sostenga el producto que hace Seedance.
- Una persona detectada en el reel **no** crea una parte de presentador: la elige el dueño.

## 7. Modelo de datos (migración de VE-03, siguiente número libre después de R3 — ver §13; backend-engineer, `qualify-migration`)

Una sola revisión sobre la cabeza de `origin/main` (hoy 0108; se renumera si otra llega antes).

| Tabla o cambio | Columnas clave | Aislamiento e idempotencia |
|---|---|---|
| `reel_analyses` (nueva) | `id`, `tenant_id`, `brand_id`, `network`, `post_id`, `source_sha256`, `source_key` (R2 del negocio), `source_seconds`, `width`, `height`, `fps`, `covered_from_s`, `covered_to_s`, `status` (`queued`/`running`/`ok`/`failed`), `lease_until`, `error_code`, `analysis_version`, `detector_version`, `sampling_version`, `model_id`, `model_revision`, `prompt_version`, `schema_version`, `input_tokens`, `output_tokens`, `cost_usd`, `transcript_source`, `reel_sheet` JSONB (familias D3 del reel), `created_at`, `finished_at`, `source_purge_after` | RLS completa (ENABLE + FORCE + política `NULLIF`). UNIQUE `(tenant_id, network, post_id, source_sha256, analysis_version)`: pedir dos veces no paga dos; una versión nueva es otra fila y nunca se reescribe. FK `brand_id → brands.id`, como las tablas creativas (0009). Índice `(tenant_id, network, post_id)` |
| `reel_analysis_shots` (nueva) | `tenant_id`, `analysis_id`, `shot_index`, `start_s`, `end_s`, `frame_keys` text[], `frame_times_s` real[], `people_presence`, `visible_faces` (CHECK `observed` / `not_observed` / `unknown`), `families` JSONB (cada familia: `status`, `value`, `evidence_frames`) | RLS completa. PK `(tenant_id, analysis_id, shot_index)`; FK compuesta `(tenant_id, analysis_id)` ON DELETE CASCADE |
| `content_drafts` (+2 columnas) | `parent_draft_id uuid NULL`, `part_index smallint NULL` | CHECK: las dos nulas o las dos con valor. FK `(tenant_id, parent_draft_id) → content_drafts (tenant_id, id)` ON DELETE CASCADE (usa `uq_content_drafts_tenant_id` de 0096). UNIQUE `(tenant_id, parent_draft_id, part_index)`. Índice parcial `WHERE parent_draft_id IS NOT NULL` |
| `content_briefs.kind` | el CHECK admite `'shot_video'` | Lección de 0068: sin esto, todo brief nuevo falla al insertarse |
| JSON del brief (sin migración) | padre: `media.parts` (el plan) y `media.source_reel.analysis_id`; hija: `media.part = {analysis_id, shot_index, trim_start_s, trim_end_s, mode}` | Cadena `inspiración → análisis → brief → pieza → publicación` (m-24880680), igual que `source_reel` hoy (E4) |

Sin cambios en `creative_jobs`, `vendor_slots`, los roles ni los GRANT: cada hija usa los tipos `preview` y `final` que ya existen. Las hijas tienen su `tenant_id` como toda pieza.

**¿Análisis global o por negocio? Por negocio.** El precedente de 0036 y ADR 42 hace globales los datos públicos que se leen para todos (el reel y sus métricas). Este análisis es otra cosa:

1. lo dispara la elección de un negocio, así que una fila global diría que alguien eligió ese reel, justo lo que prohíbe el punto 2 del §2 de ADR 42;
2. compartirlo ahorra ≈ USD 0,005 por reel, no créditos caros como en ADR 42;
3. guarda una copia del MP4 ajeno, que debe vivir con la retención y el uso interno de un negocio.

Queda **reutilizable**: el extractor no ve la marca y la fila lleva `source_sha256`, así que pasar a una tabla global `public_reel_analyses` es copiar filas. **Se reabre** si el fundador decide analizar al listar: entonces el análisis va junto a `public_reels` y lo hace `reels-worker`.

**Retención:** la fuente ajena completa a los **30 días** (solo sirve para cortar partes `edit` mientras vive el borrador de 7 días); fotogramas y ficha a los 90 días (ADR 39). **Nada del reel ajeno se publica:** una parte `edit` se publica como salida de Seedance, nunca el corte.

**Filas por año [H]:** 100 negocios × 8 análisis al mes ≈ 9.600 análisis y ≈ 58.000 planos; ≈ 4 hijas por video. Lejos del umbral de ADR 31.

## 8. Límites de módulo y contratos

| Módulo (dueño) | Hace | Contrato |
|---|---|---|
| `qualify_creative.video` (creative-engineer) | Detectar planos, sacar fotogramas, cortar, unir — funciones puras sobre bytes | `shots.detect_shots(data: bytes, *, max_seconds: float) -> list[ShotSpan]`; `shots.sample_frames(data, spans, *, plan: SamplingPlan) -> list[SampledFrame]`; `cut.cut_window(data, start_s, end_s, *, min_seconds: int = 4) -> FittedVideo`; `join.join_clips(clips: Sequence[JoinClip], *, size, overlay: bytes \| None, crossfade_audio_s: float = 0.08) -> FittedVideo` |
| `qualify_creative.schemas` / `enums` (creative-engineer) | Tipos del plan | `ContentKind.SHOT_VIDEO`; `VideoPartPlan`; `PartRef`; `MediaInputs.parts`, `MediaInputs.part`; `PART_SECONDS = range(4, 11)`; `PARTS_MAX = 6`; `clip_reference_mode: Literal["motion", "edit", "extend"]`; validadores en `ContentBrief._kind_has_its_inputs` |
| `qualify_api.referentes.reel_analysis` (backend-engineer) | Descargar, guardar la fuente, analizar con Haiku, leer | `request_analysis(tenant_id, brand_id, source: ReelSource) -> AnalysisRef`; `run_analysis(tenant_id, analysis_id) -> None` (idempotente, guardián y concesión); `get_analysis(tenant_id, analysis_id) -> ReelAnalysis \| None`; `source_window(tenant_id, analysis_id, start_s, end_s) -> str` (clave R2 del corte); `REEL_ANALYSIS_PROMPT_VERSION`. Reutiliza `reel_reference.source_allowed` y la descarga acotada |
| `qualify_api.creative.parts` (creative-engineer) | Plan, hijas, aprobación, unión | `plan_from_analysis(analysis, *, products) -> tuple[VideoPartPlan, ...]`; `create_parts(tenant_id, parent_id) -> list[UUID]` (hijas + briefs en un `tenant_unit_of_work`, encola cada una con `QueueDispatcher.dispatch_generation`); `regenerate_part(tenant_id, parent_id, part_index, changes) -> UUID`; `approve_parts(tenant_id, parent_id) -> None` (cobra N videos todo o nada y llama `dispatch_finalize` por hija); `MediaProducer._shot_video` (la unión) |
| Cola y worker (creative-engineer + platform-engineer) | Sin tipo de trabajo nuevo | `generation_jobs()` del padre = `[]` (la unión es local); cada hija, 1 `preview`; `PipelinePreparation` gana las fases `join` y `join_final` (`worker/pipeline.py:450`); al asentarse una hija se sube `dirty_version` del padre; el final de una hija termina en `part_final`, no en `final_ready` |
| `Qualify/` (reflex-ui-engineer) | Pantalla «Video por partes» | `ShotVideoState` y su vista; solo llama a los servicios de arriba; el análisis corre como tarea en segundo plano con el negocio sellado (ADR 43) |

Ninguna capa nueva llama a BytePlus fuera de `MediaProducer`, a Anthropic fuera de `claude_tools`, ni a la BD fuera de `tenant_session`. Hoy el «Replicar con mi marca» de 5 s sigue igual hasta que VE-11 lo convierte en un plan de 1 parte `edit` (sin regresión).

## 9. Costos

Supuestos: 9:16; 480p = 9.607,5 tokens/s y 1080p = 48.600 tokens/s (`byteplus_ark.py:262-288`); tarifas `v7`: 480p 10,70/M sin video y 6,40/M con video; 1080p 11,70/M y 7,00/M. Un plano corto se genera a 4 s. Que el final **vuelva a cobrar el video de entrada no está medido** (pendiente de SD25-001): se dan los dos extremos. 15 s = planos de 3, 4, 5 y 3 s (se generan 17 s); 30 s = planos de 6, 5, 4, 5, 6 y 4 s (se generan 30 s).

| Concepto (USD) | 15 s, 4 partes | 30 s, 6 partes | Nivel |
|---|---|---|---|
| Análisis con Haiku | 0,005 | 0,006 | [H] |
| Copy con Claude (como un Clip) | ≈ 0,06 | ≈ 0,06 | [H] |
| Vistas previas, todo `reference` (0,1028/s) | 1,75 | 3,08 | [V] base 0,53 por 5 s |
| Vistas previas, todo `edit` (0,0615/s de entrada + salida) | 2,09 | 3,69 | [V] base 0,60 por 5 s |
| Finales, todo `reference` (0,5686/s) | 9,67 | 17,06 | [V] base 2,87 por 5 s |
| Finales, todo `edit` (0,3402/s; sin o con la entrada) | 5,78–11,57 | 10,21–20,41 | [H] |
| Unión local | 0 | 0 | [V] |
| **Total A, todo `reference`** | **≈ 11,5** | **≈ 20,2** | [H] |
| **Total A, todo `edit`** | **≈ 7,9–13,7** | **≈ 14,0–24,2** | [H] |
| Total B (vistas previas `reference` + unión `edit` + un final) | ≈ 8,8–13,9 | ≈ 17,0–27,3 (al límite de 30 s) | [H] |
| Cada «Crear otra versión» (de una parte) | + 0,41–0,62 | igual | [V] |

**Cupo del dueño (D5–D7):** cada parte es 1 video al aprobar y 1 vista previa al crearse. 15 s en 4 partes = **los 4 videos del mes del Básico** y 4 de sus 20 vistas previas; 30 s en 6 partes **no cabe en el Básico** (Plus, con 8, o un paquete de +2). El costo queda dentro del peor caso ya aceptado (4 videos de 10 s = USD 27,3, D5). Para los dueños de los planes, la pregunta no es el costo sino el cupo: F1.

**BytePlus:** 4–6 tareas por video. Con el reparto justo de ADR 41 (2 a la vez por negocio y modelo), las vistas previas salen en 2–3 tandas de ~66 s; las partes `extend` van en serie por naturaleza; los finales van al carril nocturno. No cambia el tope de 10 de la cuenta.

## 10. Dependencias y riesgos

| # | Dependencia o riesgo | Efecto | Qué se hace |
|---|---|---|---|
| R1 | Cola de ADR 41: `QUALIFY_CREATIVE_DISPATCHER` vale `inline` por defecto (`queue_dispatch.py:19, 37`) y no verifiqué si producción ya usa `queue` [H] | Con hilos, 6 partes = 6 hilos sin tope ni reparto | La fase 1 exige `queue` en producción |
| R2 | ADR 42 R1/R3/R6 sin construir (E18) | No hay `public_reels` al que apuntar; la URL del MP4 sale de la tarjeta en memoria | El análisis se identifica por `(red, post_id, sha256)`; cuando exista `public_reels` se agrega la referencia sin tocar el análisis |
| R3 | m-24880328 (Extender video) | `extend` por parte depende de lo que mida: ¿tramo nuevo o video entero?, ¿admite borrador? | `extend` va en la fase 2 y consume ese código; no se duplica |
| R4 | Rechazo por rostro en una parte `edit` | Falla tarde, tras el copy y la espera | Modo por defecto según Haiku; estado `refused_face` con un botón a `reference`; la vista previa se devuelve |
| R5 | Haiku no ve todo: un rostro breve entre dos fotogramas | `not_observed` no es ausencia (D2) | La pantalla avisa «puede ser rechazada»; R4 cubre el resto; VE-05 mide el acierto |
| R6 | Deriva de duración: `edit` sale hasta 0,4 s más corto (4,708 s por 5 s, medido) | El video unido dura algo menos que el original | La unión usa la duración real y no rellena |
| R7 | URLs que caducan: la del reel en 24–33 h, la de Seedance en 24 h | Sin fuente no hay `edit` | La fuente se copia a R2 al analizar; la salida de Seedance se guarda al terminar (ya lo hace la preparación) |
| R8 | Retención (ADR 39) | Una parte borrada no se puede volver a unir | Fuente ajena 30 d; piezas 90 d; el video unido es un archivo propio |
| R9 | Derechos sobre el MP4 ajeno | Riesgo si se publica o se guarda sin fin | Solo referencia interna: nunca se publica, nunca su audio, borrado a los 30 d |
| R10 | Continuidad de `extend` en 1080p: cada final sale de su propio borrador [H] | El paso entre dos finales puede saltar | Se mide en VE-16; si salta, queda como corte de plano, igual que en el reel |
| R11 | Confianza en salidas propias con rostro: solo sin edición ni recompresión [D] | `extend` (o la unión B) con rostro necesita los bytes crudos | Se guarda la salida cruda de cada parte (§4.2 c) |
| R12 | Memoria del worker: 512 MB | Unir 6 finales 1080p | Unión por flujo; VE-07 mide el pico |
| R13 | Cupo de BytePlus: 10 a la vez para todos | Un video de 6 partes ocupa 2 cupos durante 3 tandas | Reparto justo de ADR 41; tope de 6 partes |
| R14 | Cupo del plan (D5) | El Básico solo hace un video de 4 partes al mes | F1 |

## 11. Decisiones para el fundador

> **Reemplazado por §13 (decisiones de Deivid, 2026-11-02).** Esta tabla y la fila propuesta de abajo son las recomendaciones previas: por ejemplo F1 quedó en «segundos de video al mes» y el ADR 44 está APROBADO. Lo vigente está en §13 y en `docs/arquitectura.md` §6.

| # | Pregunta | Recomendación | Puerta |
|---|---|---|---|
| F1 | ¿Cómo cuenta un video por partes en el plan? | **Cada parte = 1 video** (D5 tal cual: es lo que cuesta) con tope de 6 partes. Reabrir hacia «segundos de video al mes» si más del 30 % de estos videos chocan con el cupo en el primer mes | Dos vías en código (versión de pesos), pero lo ve el cliente: una vez anunciada, cuesta cambiarla |
| F2 | ¿Unión local o con `edit` de Seedance? | **Local por defecto**; `edit` como opción tras la prueba VE-18 | Dos vías |
| F3 | ¿Cuándo analizar el reel? | **Al elegirlo**, no al listar | Dos vías |
| F4 | ¿Alcance y muestreo? | Reel completo hasta 60 s; 2 fotogramas por plano + 3 anclas del gancho; 720×1280; tope 32 | Dos vías (`sampling_version`) |
| F5 | ¿Análisis global o por negocio? | **Por negocio**, reutilizable por hash | Global sería de una vía (filas compartidas); por negocio se revierte copiando |
| F6 | ¿Modo por defecto según personas? | `edit` sin personas observadas; `reference` con personas o duda; nunca pasar solo a Avatar | Dos vías |
| F7 | ¿Partes sin reel en la fase 1? | Sí, a mano; «Proponer partes» con IA en la fase 2 | Dos vías |
| F8 | ¿Una aprobación del video completo o una por parte? | **Una**, del video completo, más la confirmación del final de ADR 41 | Dos vías |
| F9 | ¿Retención de la fuente ajena? | 30 días | Dos vías |
| F10 | ¿Se firma como ADR 44? | Sí, con la fila siguiente | — |

**Fila propuesta para `docs/arquitectura.md` §6:**

| 44 | **[PROPUESTO — principal-architect, 2026-11-02; detalle en `docs/diseno-video-por-planos.md`]** **«Video por partes»: un video se arma con hasta 6 partes; cada parte es una pieza hija (`content_drafts.parent_draft_id`) con modo `reference`, `edit` o `extend`, su prompt, sus referencias y sus versiones, generada por la cola de ADR 41 sin tipos nuevos; se unen localmente con PyAV y el video unido pasa por la confirmación de ADR 41.** El reel de referencia se analiza al elegirlo (planos con PyAV, ficha D3 y rostros con Haiku, por negocio, con procedencia por versión). Los finales de parte quedan en `part_final`, nunca publicables | (i) N videos dentro de una sola pieza; (ii) unir con `edit` de Seedance; (iii) análisis global; (iv) PySceneDetect | (i) iterar una parte regeneraría toda la pieza y el emparejamiento por orden de llamada se rompe con `extend`; (ii) cambia lo aprobado, tope de 30 s, sin OmniHuman, no probado en 2.5; (iii) la fila revelaría la elección de un negocio y ahorra USD 0,005; (iv) agrega OpenCV sin medición que lo pida | F1 de cortes < 0,85; la prueba de unión con `edit` sale fiel y más barata; se decide analizar al listar; > 30 % de los videos por partes chocan con el cupo |

**Conflictos con tickets existentes:**

- **m-24880681** (VLM → texto) queda **absorbido** por VE-09: una parte `reference` desde la ficha de Haiku es su objetivo, por parte. Su enfoque híbrido «intentar `edit` y caer al texto tras el rechazo» choca con D2 (el rechazo no es el clasificador): se reescribe con el modo elegido antes de enviar y el botón manual de `refused_face`.
- **m-24820834** (`reel_blueprint.v1`) queda **reemplazado**: el modelo (Gemini 3.8 Flash) choca con D2 (Haiku); el esquema, con el contrato D3; PySceneDetect, con el detector en PyAV. Su set de 40 reels se reduce a 20 en VE-05. Se cierra como sustituido; la investigación se conserva.
- **m-24880680:** este documento responde sus pendientes (momento, alcance, muestreo, ruta) como recomendaciones F3, F4 y F6; no reabre D1–D3.
- **ADR 42 R14** («Hacer uno parecido» abre Crear en 4 pasos) pasa a abrir «Video por partes»; hay que ajustar R14 al firmar.
- **ADR 41 §3.2** («todo final pasa por `final_ready`») se precisa: aplica al archivo que se publica, el unido; los finales de parte quedan en `part_final`.
- **D5** («videos de hasta 10 s; 15 s no se ofrece»): un video de 15–30 s hecho de partes de ≤ 10 s no estaba previsto. F1.

## 12. Corte en historias

Áreas: **BE** backend-engineer · **CR** creative-engineer · **UI** reflex-ui-engineer (con revisión de **UX** ux-designer) · **PL** platform-engineer · **DS** data-scientist-fde. Tamaño S/M/L. Ids provisionales; creative-engineer y backend-engineer las refinan antes de crear los tickets.

### Fase 1 — análisis por planos, partes `reference` y `edit` de un plano, unión local

| Id | Título | Área | P | T | Depende de | Criterios de aceptación |
|---|---|---|---|---|---|---|
| VE-01 | Arquitectura: firmar ADR 44 «Video por partes» | architect → fundador | P0 | S | — | F1–F10 decididas y la fila en `docs/arquitectura.md` §6; m-24880681 y m-24820834 reescritos o cerrados con enlace aquí |
| VE-02 | Video: detectar planos y sacar fotogramas con PyAV | CR | P1 | M | VE-01 | `qualify_creative/video/shots.py` con `detect_shots` y `sample_frames`; test offline con un MP4 sintético de 3 cortes conocidos (error ≤ 1 cuadro); ninguna dependencia nueva en `uv.lock` |
| VE-03 | Migración (siguiente número libre; ver §13): `reel_analyses`, `reel_analysis_shots`, `content_drafts.parent_draft_id/part_index`, kind `shot_video` | BE | P1 | M | VE-01 | `just test-db`: el negocio A no lee filas de B en las dos tablas nuevas; upgrade → downgrade → upgrade limpio en CI; insertar un brief `shot_video` funciona |
| VE-04 | Referentes: análisis del reel con Haiku (`reel_analysis`) | BE | P1 | L | VE-02, VE-03 | Con Claude simulado: dos pedidos del mismo `sha256` hacen 1 llamada; el pedido 21 del día se rechaza sin llamar; la fila guarda modelo, versiones de prompt, esquema, muestreo y detector, tokens y costo; cada familia D3 trae `observed/not_observed/unknown`; la transcripción se reparte por tiempo; fuente en R2 con clave del negocio |
| VE-05 | Medición: cortes y rostros en 20 reels reales (10 con personas) | DS | P1 | M | VE-04 | En `docs/modelos-generativos/` (`qualify-measure`): F1 de cortes a ±0,25 s, aciertos de `visible_faces` frente a anotación manual, costo y latencia reales por reel; si F1 < 0,85, propuesta de detector |
| VE-06 | Generador: tipos del plan y validadores | CR | P1 | M | VE-01 | `ContentKind.SHOT_VIDEO`, `VideoPartPlan`, `MediaInputs.parts/part`, `PART_SECONDS`, `PARTS_MAX` en `schemas.py`/`enums.py`; tests: padre con 1–6 partes; hija `edit` de 4–10 s enteros; hija sin padre rechazada; un Clip normal no cambia |
| VE-07 | Video: cortar ventana y unir partes con PyAV | CR | P1 | M | VE-06 | `video/cut.py` y `video/join.py`; la unión de 3 clips sintéticos dura la suma de recortes ±1 cuadro, con una pista de audio, H.264 `yuv420p` y `+faststart`; pico de memoria < 300 MB uniendo 6 partes 1080p de 5 s (medido en el test) |
| VE-08 | Generador: plan desde el análisis, piezas hijas y «Crear otra versión» (de una parte) | CR | P1 | L | VE-03, VE-06 | `qualify_api/creative/parts.py`: `plan_from_analysis` (modo por rostros, fusiona planos cortos hasta 6, parte > 10 s), `create_parts` (hijas + briefs en una transacción, 1 trabajo `preview` por hija), `regenerate_part` (versión nueva solo de esa hija); cada vista previa cuenta 1 de 20 (D7) |
| VE-09 | Generador: parte `reference` desde la ficha y parte `edit` desde el corte | CR | P1 | L | VE-07, VE-08 | Test de parámetros: una parte `reference` no lleva `reference_videos`; una `edit` lleva una ventana ≥ 4 s, `adaptive` y `-1`; las dos sin logo y con la salida cruda guardada; `PrivacyInformation` → `refused_face` y la vista previa se devuelve; procedencia (análisis, plano, versión del prompt) en la hija |
| VE-10 | Cola: unión en el worker, aprobación única y finales de parte | CR + PL | P1 | L | VE-07, VE-09 | Fases `join` y `join_final` en `worker/pipeline.py`; con 3 hijas listas, 1 sola vista previa unida; `approve_parts` cobra 3 videos todo o nada (D6) y encola 3 finales nocturnos; los finales de parte quedan en `part_final` y no aparecen en `final_ready`, el correo de la mañana, «Tu semana», la galería ni el Planificador (tests); el unido final queda en `final_ready` |
| VE-11 | Pantalla: «Video por partes» | UI + UX | P1 | L | VE-04, VE-10 | Desde «Hacer uno parecido» (hoy «Replicar con mi marca») se ve el progreso del análisis y la lista de partes (fotograma, descripción editable, modo en palabras del dueño, referencias), «Generar partes», estado por parte, «Crear otra versión» (de una parte), video completo y «Aprobar el video» con el aviso de videos del mes; abrir la pantalla no hace llamadas pagadas (test); 375 px; sin anglicismos; el replicador de 5 s sigue funcionando como plan de 1 parte |
| VE-12 | Retención: fuente ajena a 30 d y análisis a 90 d | BE | P2 | S | VE-04 | El job de purga borra la fuente vencida de R2 y deja la ficha; test con reloj falso |

### Fase 2 — `extend` por parte, partes propuestas y voz

| Id | Título | Área | P | T | Depende de | Criterios de aceptación |
|---|---|---|---|---|---|---|
| VE-13 | Generador: parte `extend` que continúa la anterior | CR | P2 | M | m-24880328, VE-10 | Estado `waiting_previous`; el pedido usa la salida cruda de la parte anterior; la unión respeta lo que mida m-24880328 (tramo nuevo o video entero) sin duplicar cuadros; un plano > 10 s se parte en `reference` + `extend` |
| VE-14 | Generador: «Proponer partes» sin reel | CR | P2 | M | VE-08 | Claude devuelve 3–6 `VideoPartPlan` desde el brief y el ángulo con herramienta estricta; el dueño puede editarlas antes de generar; sin llamada pagada de video hasta «Generar partes» |
| VE-15 | Generador: «Voz de tu marca» y subtítulos en la unión | CR | P2 | M | VE-10 | Locución de Seed Speech sobre el video unido, sonido de partes atenuado, subtítulos con `PyAvVideoFitter.subtitle`; el audio del reel nunca entra (test) |
| VE-16 | Medición: continuidad de `extend` en 1080p y final con video de entrada | DS | P2 | S | VE-13 | Cierra R10 y el pendiente de SD25-001 (¿el final recobra la entrada?) en `seedance-2-5.md`, con ids de tarea |

### Fase 3 — avatares por partes y unión con IA

| Id | Título | Área | P | T | Depende de | Criterios de aceptación |
|---|---|---|---|---|---|---|
| VE-17 | Generador: parte «Presentador» con OmniHuman | CR + UI | P3 | L | VE-10 | Hija `avatar_video` intercalada, máximo 2 por video, misma foto y voz; su audio se conserva en su tramo; se cobra en creaciones por segundos |
| VE-18 | Prueba: unir con `edit` de Seedance | DS + CR | P3 | M | VE-10, VE-16 | 3 uniones de 15 s medidas: ¿encadena?, ¿cambia el producto?, costo real; resultado y recomendación en `seedance-2-5.md` |
| VE-19 | Generador: «Suavizar las uniones con IA» (solo si VE-18 sale bien) | CR + UI | P3 | M | VE-18 | Solo con partes de Seedance que sumen ≤ 30 s; pide una vista previa nueva y la aprobación del dueño; nunca reemplaza la unión local aprobada sin confirmar |

## 13. Decisiones del 2026-11-02 y sus consecuencias

**Estado:** `[APROBADO — decidido por Deivid Vargas el 2026-11-02, una a una: F1–F10 del §11 y P2/P3/P5/P6 de docs/ux-video-por-planos.md §7]`. La fila del ADR 44 ya está en `docs/arquitectura.md` §6 (la escribió el hilo principal). **Esta sección manda sobre §1–§12 donde se contradicen**; lo que no cita sigue igual. Las cifras de cupo en segundos (13.5) quedan `[PROPUESTO]` hasta que el fundador (Herwin) las confirme, porque reemplazan D5 y D15, que firmó él. Evidencia nueva: `main` en `56746531`, `origin/main` en `b5d5b524` y los tickets de Meegle leídos con la CLI (solo lectura). Mismas marcas [V]/[D]/[H].

### 13.1 Qué cambia en este documento

| Decisión | Sección | Qué cambia |
|---|---|---|
| F3 (al listar) + F5 (global) | §3, §4.1 | El análisis deja de ser «por negocio, al elegir»: lo hace el `reels-worker` en la corrida semanal de ADR 42 sobre las ideas, y lo comparten todos los negocios. Reflex no baja ni decodifica ningún reel (se cae RN1 del traspaso de backend) |
| F5 | §7 | Reemplazado por 13.2: `public_reel_analyses` y `public_reel_analysis_shots` globales en lugar de `reel_analyses` / `reel_analysis_shots` con RLS |
| F3, F5 | §8 | Contratos de 13.3: `run_analysis(analysis_id)` sin negocio y solo en el `reels-worker`; `source_window(...)` corre en `creative-worker` por `tenant_session` |
| F1 = (b) | §9, §11, §12 | Cupo en segundos (13.5). VE-21 pasa a la fase 1 (P1, L): la pantalla necesita la cifra antes de «Crear» y de «Aprobar» |
| F2, F4, F6, F8 | §4.1, §4.2, §5 | Sin cambio: unión local, muestreo de §4.1, modo según personas, una sola aprobación |
| F7 | §12 | La mitad «Prefiero armarlas yo» de UI-5 sube a la fase 1; «Proponerme las partes» (VE-14) sigue en la 2 |
| F9 | §7 «Retención», §10 R8–R9 | Fuente y fotogramas a 30 d, ficha a 90 d, purga global del `reels-worker` (13.2, 13.8) |
| P2 | §3, §4.2 | «Una parte es un plano» pasa a «una parte junta cortes seguidos hasta 4–10 s, tope 6». Lo hace `plan_from_analysis` (código, sin otra llamada) y nunca junta en una parte `edit` un corte con personas `observed`. Baja el desperdicio del «plano corto» de §4.2 |
| P3 | §6 | La voz del presentador suena solo en sus partes. La parte de presentador no tiene vista previa: nace como final, entra en `part_final` y se cobra en creaciones por segundos al crearse (traspaso creative §2.12) |
| P5 | §3, §4.2, §12 | «Extender video» es la entrada C del flujo (13.6) |
| P6 | §12 (UI-9) | Sin aviso en la fase 1; decide la pregunta 5 de la prueba con 3 dueños (UX §7) |
| Orden | §10 R2, §12 | ADR 42 R1, R2, R3, R4, R5, R7 y R8 entran en esta épica (13.4): **la ruta crítica de la fase 1 pasa a ser la de ADR 42**, no la de creative |

### 13.2 Modelo de datos definitivo (reemplaza §7)

Dos tablas **globales, sin `tenant_id` ni RLS**, con el precedente de 0036 y ADR 42 §3.1: el docstring de la revisión declara la excepción y un test estático comprueba que ninguna columna nombre un negocio, una marca ni un usuario. Van en una revisión propia (VE-03), **sin FK a `public_reels`**: se cruzan por `(network, post_id) = public_reels (network, reel_id)`, así VE-03 y R3 no se esperan. **Numeración [V]:** al 2026-11-04 `origin/main` llega a `0116_gallery_resume` y R3 toma la 0117; VE-03 y R3 toman el siguiente número libre al abrir su rama y la que llegue segunda re-encadena (`qualify-migration`).

| Tabla | Columnas | Claves y reglas |
|---|---|---|
| `public_reel_analyses` | `id`; `network`, `post_id`, `analysis_version`; estado: `status` (`queued`/`running`/`ok`/`failed`), `stage`, `lease_token`, `lease_until`, `attempts`, `model_calls`, `error_code`; origen: `post_url`, `pending_video_url` (firmada; se borra al bajar y nunca va a los registros); fuente: `source_key`, `source_sha256` (solo procedencia), `source_seconds`, `width`, `height`, `fps`, `covered_from_s`, `covered_to_s`, `edit_eligible`; habla: `transcript` JSONB, `transcript_source`; procedencia: `detector_version`, `sampling_version`, `sampling_params`, `model_id`, `model_revision`, `prompt_version`, `schema_version`, `input_tokens`, `output_tokens`, `cost_usd`; `reel_sheet` JSONB; `created_at`, `finished_at`, `source_purge_after`, `source_purged_at`, `frames_purged_at`. **Propongo una columna más: `wanted_at`** (13.3) | `UNIQUE (network, post_id, analysis_version)` → `INSERT … ON CONFLICT DO NOTHING`. Un `ok` nunca se reescribe; un `failed` reintentable lo vuelve a `queued` el worker (≤ 3 intentos) |
| `public_reel_analysis_shots` | `analysis_id`, `shot_index`, `start_s`, `end_s`, `frame_keys`, `frame_times_s`, `people_presence`, `visible_faces` (CHECK `observed`/`not_observed`/`unknown`), `families` JSONB, `spoken_text` | PK `(analysis_id, shot_index)`; FK ON DELETE CASCADE; CHECK `end_s > start_s`; se escriben en la misma transacción que `status = ok` |

**Lo que sigue por negocio (RLS, como §7 y el traspaso de backend):** `content_drafts.parent_draft_id/part_index` con sus CHECK, FK compuesta, UNIQUE e índice parcial; `content_briefs.kind` si VE-01 conserva `shot_video`; el plan en el brief del padre; las hijas y su brief por versión; el corte de ventana en la carpeta de la hija (13.3). **Nuevo:** al crear el plan, el brief del padre copia la procedencia del análisis (`analysis_id`, `analysis_version`, `model_id`, `prompt_version`, `detector_version`, `sampling_version`); así la cadena `inspiración → análisis → brief → pieza → publicación` de m-24880680 sobrevive al borrado de la fila global a los 90 días.

**R2:** `public/reel-analyses/{network}/{post_id}/{analysis_id}/source/source.mp4` y `…/frames/{shot:02d}-{n}.jpg`. La fuente se guarda **remuxada sin audio y sin recodificar**: la ventana de `edit` se recodifica igual en `cut_window`, así que normalizar los 60 s enteros era CPU de más. «Público» quiere decir «sin negocio en la clave», no «servido sin sesión». Hoy la puerta de R2 solo escribe bajo `t/{tenant}/` y solo borra bajo `generated/` (`PURGEABLE_ROOTS`, `qualify_shared/objects/gate.py:79`) [V]: hace falta un método nuevo acotado a `public/reel-analyses/`, que solo llama `qualify_api.referentes.reel_analysis` (test estático); R12 (`public/reel-covers/`) usará el mismo. **Se descarta** agregar `reel-analyses/` a `PURGEABLE_ROOTS` por negocio (traspaso de backend V7 y VE-12): ya no hay copia por negocio.

**GRANT por rol:**

| Rol | `public_reel_analyses` | `public_reel_analysis_shots` | Para qué |
|---|---|---|---|
| `qualify_app` | SELECT; INSERT solo de `(network, post_id, analysis_version, post_url, wanted_at)`; UPDATE solo de `wanted_at` | SELECT | La pantalla lee y encola; `creative-worker` lee la fila al preparar una parte `edit`, porque trabaja por `tenant_session` (`creative/worker/pipeline.py:44-275`) [V] |
| rol del `reels-worker` (lo crea R8; p. ej. `qualify_reels_worker`) | SELECT, INSERT, UPDATE, DELETE | SELECT, INSERT, UPDATE, DELETE | Único que analiza, escribe resultados y purga, por una puerta propia en `qualify_shared.db` que entra en el test de puertas |
| `qualify_admin` | SELECT | SELECT | Informe de la purga en modo de prueba y auditoría del operador; nunca escribe |
| `qualify_creative_worker`, roles de webhook | nada | nada | ADR 41 no cambia (docstring de 0096) |

Precisión al contrato «`qualify_app` lectura»: sin ese INSERT y ese UPDATE acotados, la pantalla no podría encolar, como dice la fila del ADR 44. Las columnas que puede escribir no le permiten falsear un resultado.

**Por qué compartir el análisis no filtra nada de ningún negocio:**

1. Ninguna columna ni clave de R2 nombra un negocio, una marca o un usuario (test estático, como pide ADR 42 §6).
2. El extractor no ve la marca, ni métricas, ni veredictos (m-24880680; V12 del traspaso de backend): su entrada son los bytes y el texto de un reel público, y su salida es la misma para cualquier negocio con las mismas versiones.
3. Que exista una fila solo dice que al menos un negocio recibió ese reel como idea o lo eligió, nunca cuál: la misma clase de dato que `reel_accounts` (ADR 42 §2.2). Con F3 casi todas las filas nacen en la corrida, así que una fila ni siquiera implica una elección; `wanted_at` dice «alguien lo pidió a tal hora», tampoco quién. Esto deja sin efecto el argumento 1 del §7.
4. Lo que es del negocio —qué reel eligió, sus partes, textos y fotos— vive en `content_drafts` y los briefs, con RLS.

### 13.3 Flujo de ejecución definitivo (reemplaza §4.1 «Cuándo» y «Dónde»)

Solo el `reels-worker` corre `run_analysis(analysis_id)`, en dos carriles del mismo bucle (ADR 42 §4, «cada pocos segundos»). `creative-worker` nunca lo corre: su GRANT es cosa de ADR 41.

1. **Corrida semanal (lunes 06:00 hora local, R8).** Al cerrar las 6–8 ideas de la marca, la corrida inserta `queued` para cada idea sin análisis, con `post_url` y `pending_video_url` del payload que acaba de pagar, hasta **10 por negocio y corrida** (≈ USD 0,055). La URL del CDN vive 24–33 h (traspaso de backend RN3), así que el bucle **baja primero y analiza después**: toda fila con URL pendiente pasa antes por `downloading` (archivo temporal ≤ 80 MiB, sha256, remux sin audio, subida a R2: segundos), y las etapas lentas (`detecting`, `describing`) se vacían después desde R2, sin prisa. Los reels compartidos a mano (m-24855161, épica sin refinar [V]) se encolan al guardarse: su lectura por la puerta medida trae una URL fresca.
2. **Cola bajo demanda.** «Hacer uno parecido» sobre un reel sin `ok` llama a `request_analysis`: comprueba por RLS que el reel es una idea o un reel guardado de ese negocio, inserta `queued` con `ON CONFLICT DO NOTHING` y pone `wanted_at = now()`. El bucle atiende en este orden: filas con URL pendiente → filas con `wanted_at` (la más vieja primero) → el resto. Un análisis a la vez (memoria), así que quien espera tiene delante como mucho el que está en curso.

**Contratos (reemplazan la fila de `reel_analysis` del §8):** `request_analysis(tenant_id, brand_id, network, post_id) -> AnalysisRef` (pantalla, `tenant_session`); `run_analysis(analysis_id) -> None` (solo `reels-worker`); `get_analysis_status(analysis_id)` y `get_analysis(analysis_id)` (cualquier sesión: es dato global); `source_window(tenant_id, draft_id, analysis_id, start_s, end_s) -> str` (`creative-worker`, `tenant_session`: lee la fuente pública y escribe `t/{tenant}/generated/{draft_id}/source-window-{start}-{end}.mp4`; con `source_purged` o `not_edit_eligible` la parte va a `reference`). Cambiar `REEL_ANALYSIS_PROMPT_VERSION` o `REEL_ANALYSIS_SCHEMA_VERSION` sube `analysis_version`.

**Qué hace la pantalla:** si el reel ya tiene `ok` (el caso normal con F3), va directo al plan: `plan_from_analysis` es una función pura sobre filas chicas y cabe en Reflex. Si no, encola y consulta `get_analysis_status` cada 3 s mientras está abierta. Si el dueño sale, la fila es el estado y al volver se retoma por la URL (`/create?paso=2&analisis=<id>`, traspaso de backend §3).

**Estados:** `queued` → `running` (`stage`: `downloading` → `detecting` → `describing`) → `ok` o `failed` (`error_code`: `source_unavailable`, `source_too_large`, `source_unreadable`, `model_failed`; con el tope de flota, la fila espera en `queued` y la pantalla lo muestra como `fleet_paused`). `tenant_mismatch` sale del análisis, que ya no tiene negocio; sigue en la pantalla al escribir su estado (ADR 43 §2.4).

**Un reel listado antes de que exista su análisis:** (a) idea cuyo análisis sigue en cola el lunes → `wanted_at` lo adelanta; (b) idea cuyo análisis falló → el worker reintenta (≤ 3); si la URL ya venció, `source_unavailable` y la pantalla ofrece «Armar sin el reel». **No se paga para renovar la URL** (ADR 42 §2.14 y R14); (c) las tarjetas en memoria de hoy desaparecen con R7 y no se rellenan hacia atrás: sus URL ya vencieron.

**Reanudación:** concesión de 2 min renovada cada 40 s (`lease_token`, `lease_until`; patrón de `creative/pipeline.py:58-108`, traspaso de backend V9). Cada etapa persiste lo suyo antes de seguir (`source_key`, fotogramas en R2), así que un despliegue retoma desde la última etapa. `model_calls` sube **antes** de llamar a Haiku: si el proceso muere entre la respuesta y el commit, se paga otra vez (≤ USD 0,0055; se acepta, RN8).

**Guardián de costo:** el análisis no gasta créditos (bajar del CDN no es ScrapeCreators y la transcripción ya se pagó al listar), así que los topes de créditos de R5 acotan la corrida y no el análisis. Topes propios, en el mismo módulo que R5: **10 análisis por negocio y corrida** (contados en la corrida) y **1.500 por día en la flota** (suma de `model_calls` en 24 h: ≤ USD 8,3 por día). **Se retira el tope de 20 por negocio y día** de VE-04a: sin carril por negocio no hay a quién contárselo, y la cola bajo demanda está acotada por construcción (un análisis por reel, solo reels que el negocio recibió como idea o guardó pagando créditos bajo R5). El costo queda en la fila (`cost_usd`, tokens) y en Langfuse; no se carga a un negocio en `consumption_ledger`, porque un análisis compartido no es de nadie.

**Costo con 100 negocios × 8 ideas por semana [H]:**

| Concepto | Por semana | Por mes (4,33 semanas) | Por negocio y mes |
|---|---|---|---|
| Haiku: ≤ 800 análisis × USD 0,0055 (menos si varios negocios reciben el mismo reel) | ≤ USD 4,4 | ≤ USD 19 | ≤ USD 0,19 |
| R2: ~10 MB por análisis (fuente ~6 MB + 32 fotogramas ~4 MB), ~34 GB vivos a 30 d, a 0,015 USD por GB y mes | — | ≈ USD 0,5 | ≈ USD 0,005 |
| CPU del worker: 30–60 s por análisis, en serie | 7–13 h el lunes | — | — |
| Bajada del CDN y minutos de Actions (usa la imagen `app`, sin trabajo de CI nuevo) | 0 | 0 | 0 |

Frente a analizar al elegir (si 1 de cada 5 ideas se usa, ≈ USD 0,9 por semana), F3 cuesta ≈ 5 veces más en Haiku, unos USD 15 más al mes con 100 negocios, a cambio de cero espera y de sacar el análisis del único proceso de Reflex. **Filas por año:** ≤ 41.600 análisis y ≈ 250.000 planos; con el borrado a 90 d viven ≈ 10.000 y ≈ 60.000. Lejos del umbral de ADR 31.

### 13.4 Cadena mínima de ADR 42 que arrastra la fase 1

Verificado en Meegle [V]: los siete tickets están en Backlog, sin PR. Se enlazan como «Bloqueado por» de las historias de esta épica; **no se crean historias nuevas para lo mismo**.

| ADR 42 | Ticket | ¿Entra? | Por qué | Qué suma para el análisis | Qué puede quedar fuera |
|---|---|---|---|---|---|
| R1 mudar cliente y pipeline | m-24854844 | Sí | El `reels-worker` es `qualify_api`, y la lista vive en `Qualify/reels_discovery.py` (ADR 42 H10) | Los lectores con tiempos de VE-04b nacen en `packages/api`; la caché `_transcripts` en memoria desaparece | — |
| R2 puerta medida | m-24854847 | Sí, reducida | Una corrida desatendida que paga créditos necesita guardián (regla 7) | Nada: el análisis no llama al proveedor | La alerta a Lark bajo 2.000 y R16 pueden ir después; interruptor, piso de 500, parada ante 402, saldo y registro, no |
| R3 esquema | m-24854845 | Sí | R4, R5 y R7 usan sus tablas | `public_reels.transcript_segments` JSONB: los tramos con tiempos con los que el análisis reparte el habla por plano | Las tablas de análisis **no** van aquí: VE-03, en revisión aparte |
| R4 corrida persistente | m-24854848 | Sí | Es la corrida en la que engancha F3 | Escribe las 6–8 ideas (ese número de R11 se adelanta aquí), encola sus análisis con la URL fresca y guarda los tramos | R6 (crudo a R2 en gzip) queda fuera, pero R4 guarda el crudo en `vendor_payloads` (0036), como exige la regla del crudo; también el resto de R11 (visto/nuevo, aviso en Inicio, 4 semanas) |
| R5 topes | m-24854849 | Sí (chica) | R8 encola corridas de todos los negocios sin que nadie mire | Los dos topes de análisis de 13.3 | — |
| R8 `reels-worker` | m-24854855 | Sí | Es el único lugar donde corre `run_analysis` | El carril de análisis (lo cablea VE-04a), el rol y su puerta, la purga global diaria (VE-12) y el servicio en el compose | — |
| R7 la vista lee la BD | m-24854854 | **Sí; no estaba en la lista** | Sin R7 la pantalla sigue con su lista en memoria y la corrida analizaría reels que el dueño no ve | La tarjeta muestra «Aparece una persona» o «Sin analizar» (13.7) | — |

Quedan fuera de esta épica, en m-24854843: R6, R9 (recomendable, no imprescindible: sin él, una marca nueva espera al lunes o a una corrida que encola el operador desde la CLI del worker), R10, R11 salvo el 6–8, R12, R13, R16 y R17. R14 lo reemplaza UI-1 (m-24921075); R15 puede ir en paralelo.

**Orden.** Pista ADR 42: R1 → (R2 ∥ R3) → R4 → R5 → R8 → R7. Pista del análisis, en paralelo: VE-02 ∥ VE-03 → VE-04a (`run_analysis` y el carril, contra un almacén en memoria y un MP4 sintético) → VE-04c → se enchufa al bucle cuando R8 esté en `main` (lo hace el segundo que llega). VE-04b va tras R1 (lector) y R3 (columna). UI-1 pasa a depender de R7. Creative (VE-06…VE-10b) prueba con el análisis de ejemplo de VE-04a y no espera a esta pista. **No se construye dos veces:** desaparece el camino de VE-04a dentro de Reflex (tarea en segundo plano, semáforo, proceso hijo); `run_analysis` se escribe una vez, en `qualify_api.referentes.reel_analysis`, y no cambia de firma.

**Platform:** un servicio más en el VPS compartido con Pedidos; `mem_limit` a fijar con la medición de VE-04a, con objetivo ≤ 384 MiB (un análisis a la vez, archivo temporal) [H]. Hoy los workers van de 256 a 512 MiB (`deploy/docker-compose.prod.yml`) [V].

### 13.5 Cupo de video en segundos (F1 = b; reemplaza el «Cupo del dueño» del §9 y D5)

`[PROPUESTO — equivalencia por confirmar con el fundador]`

| Plan | Hoy (D5, D15) | Con F1 = (b) | Vistas previas (D7, sin cambio) | Techo de video sin video de entrada, 0,671 USD/s [H] | Techo todo `edit` si el final cobra la entrada, 0,803 USD/s [H] |
|---|---|---|---|---|---|
| Básico | 4 videos ≤ 10 s | 40 s | 20 | 26,9 (D5: 27,3) | 32,1 |
| Plus | 8 | 80 s | 40 | 53,7 | 64,3 |
| Pro | 16 | 160 s | 80 | 107,4 | 128,5 |
| Ilimitado (0110, interno) | sin tope | sin tope; el tope en USD sigue siendo alerta | — | — | — |
| Paquete de 90 días | «+2 videos» (`qualify_api/plans/catalog.py:188`) [V] | «+20 s» | «+10 vistas previas» | — | — |

- **Cómo se cobra una parte:** sus segundos **pedidos** a Seedance (4–10, enteros), no los entregados: `edit` sale hasta 0,4 s más corto y un corte de 1,5 s se genera a 4 s. El dueño paga lo que paga el equipo y la cifra se conoce antes de «Crear». Se cobran al aprobar (D6), todos o ninguno: el `charge_videos_many` del traspaso creative suma segundos por hija en una transacción. Un Clip de 5 s cuenta 5 s: el Básico hace 8 clips de 5 s en lugar de 4, al mismo costo (≈ 8 × 3,44 = USD 27,5).
- **D6 sigue** (se cuenta al aprobar). **D7 sigue por unidad:** 1 vista previa por parte al crearse; se devuelve solo si el proveedor no entregó nada (`refused_face` incluido). **D9 devuelve en segundos:** si falla el final de una parte vuelven sus segundos y los demás quedan contados, como hoy una diapositiva.
- **Lo que no cambia:** ninguna generación pasa de 10 s (`PART_SECONDS` 4–10; Clip de 5 o 10 s); un video más largo se arma por partes. Diapositiva animada = sus segundos (5 por defecto, `_SLIDE_SECONDS` en `qualify_creative/creations.py:74`) [V]; avatar de Seedance = sus segundos; el presentador de OmniHuman sigue en creaciones (P3).
- **Techo por negocio y mes [H]:** Básico 32,1 (video, peor caso `edit`) + 24,6 (20 vistas previas de 10 s en `edit`) + 4,5 (creaciones) ≈ **USD 61**, frente a ≈ 55 de D7. La diferencia sale de que el final de `edit` cobre la entrada, cosa que los pesos v2 ya suponen (`final_counts_input_video: true`) [V] y SD25-001 no midió. Plus ≈ 122 y Pro ≈ 245, bajo los topes de alerta de D18 (240 y 480).
- **Qué construye VE-21 (P1, L, fase 1):** `pesos-creaciones-v3` (`videos.monthly_seconds`; `offered_seconds` sin cambio); columna de segundos en `creation_charges` (BE, migración); segundos por plan en `qualify_api/plans/data` y el paquete «+20 s»; todos los textos «videos del mes» pasan a «segundos de video» (UI, con revisión de UX: validar que el dueño entiende «Te quedan 25 s de video este mes»). La transición ocurre al empezar un mes: lo usado en el mes en curso y los paquetes comprados en videos se convierten a 10 s por video; nadie pierde. Se reabre si el cupo en segundos frena más del 30 % de los videos del primer mes (fila del ADR 44).

### 13.6 P5: «Alargar un video que ya tienes» (entrada C)

- **m-24880328** (Backlog [V]) deja de tener pantalla propia: entrega `extend` en el adaptador, el esquema (`clip_reference_mode = "extend"`) y el servicio (`_clip`), y mide lo que §4.2 dejó abierto: ¿devuelve el tramo nuevo o el video entero?, ¿admite borrador? Su formulario se cae; **m-24880378** (Start [V]) se cumple con esta entrada.
- **El plan:** Parte 1 **fija** = el video del dueño (de su galería, su catálogo o subido; clave bajo su negocio, `require_tenant_prefix`), **sin generación, sin vista previa y sin cobro**. No es una hija con trabajos, sino una entrada del plan (`media.parts[0] = {source: "own", asset_key}`) que la unión lee tal cual, con su propio audio. Parte 2 = «Sigue a la anterior» (`extend`) sobre los últimos ≤ 10 s de la Parte 1, cortados con `cut_window`; se cobra como cualquier parte (1 vista previa al crear, sus segundos al aprobar).
- **Límites [D]:** un rostro real en el video propio puede hacer que BytePlus rechace el `extend` (la excepción de rostros vale solo para salidas propias de ModelArk sin editar) → `refused_face`, con la salida a «Nueva, con tu producto». Si m-24880328 mide que `extend` no admite borrador, la entrada C no sale hasta decidir cómo se cobra una parte sin vista previa.
- **Fase 2**, con VE-13: la entrada C es VE-13 más una historia de UI nueva (UI-11, id provisional) dentro de la pantalla de Video por partes.

### 13.7 Pantalla

- **UI-2 se reduce:** la espera solo aparece si el reel no tiene `ok`. `progress_panel` con la etapa que informa el worker, encima de la barra: «Estamos mirando este reel; en unos minutos tienes tu propuesta.», con las etapas del traspaso de backend §3 más «En fila» para `queued`. Se quitan el estado «Hoy ya miramos varios reels…» (ya no hay tope por negocio) y el «Intentar de nuevo» de `model_failed` (reintenta el worker). Quedan «No pudimos bajar el video de este reel…» con [Elegir otro reel] [Armar sin el reel], y para `fleet_paused`: «Ahora no podemos mirar este reel. Inténtalo más tarde o arma tu video por partes sin él.» Puede decir «No usa tus segundos de video del mes» (P4).
- **«Ideas para tus reels» (UI-1, tras R7):** cada tarjeta lee su análisis por `(network, post_id)` y muestra «Aparece una persona» (`signal_pill`, tono `info`) si algún corte tiene `people_presence` o `visible_faces` en `observed`, y «Sin analizar» (tono `neutral`; texto a confirmar por ux-designer) si no hay `ok`. **Nunca se excluye una idea en silencio.** «Hacer uno parecido» funciona en los dos casos; en el segundo encola y muestra UI-2. `unknown` no muestra nada: no se afirma lo que no se vio.
- **«Original» en UI-8:** muestra los fotogramas globales mientras existan (30 d) y después la descripción de la ficha.

### 13.8 Riesgos nuevos

| # | Riesgo | Efecto | Mitigación |
|---|---|---|---|
| RA1 | La corrida analiza reels que nadie usará | ≤ USD 19 al mes con 100 negocios (13.3) [H] | Solo las 6–8 ideas, tope de 10 por corrida, un análisis por reel para todos. Se reabre (volver a «al elegir») si menos del 5 % de los análisis llegan a un plan y el gasto pasa de USD 50 al mes |
| RA2 | La URL del CDN vence antes de que el worker la use | Sin fuente no hay `edit` | Bajar primero y analizar después; una vencida es `source_unavailable` y la parte va a `reference`; no se paga para renovar (ADR 42 R14). Se reabre si más del 20 % de los «Hacer uno parecido» caen ahí: renovar por la puerta medida cuesta 1 crédito |
| RA3 | La cola bajo demanda compite con la corrida del lunes | Un dueño espera horas detrás de 800 análisis | Orden de 13.3 (`wanted_at` justo después de las bajadas); un análisis a la vez. Capacidad en serie ≈ 1.400–2.900 por día [H]: pasados ~200 negocios, el lote del lunes tarda más de un día → dos análisis a la vez (medir memoria) o repartir las corridas en la mañana |
| RA4 | `reels-worker` y `calendar-worker` comparten la purga | Dos procesos escriben las mismas filas o borran el mismo prefijo | Un dueño por prefijo. El `reels-worker` purga `public/reel-analyses/` y sus filas: fuente y fotogramas a 30 d (`source_purged_at`, `frames_purged_at`), filas a 90 d con DELETE (los planos caen en cascada). El `calendar-worker` (ADR 39) solo toca `t/{tenant}/generated/`. Mismo interruptor, `QUALIFY_PIECE_PURGE_EXECUTE`. VE-12 se parte así |
| RA5 | La ventana de `edit` copiada a la hija vivía 90 d con la pieza (VE-04d), pero F9 dice fuente a 30 d | Un fragmento del reel ajeno guardado más de lo decidido | Lectura estricta de F9: la purga por negocio borra `source-window-*.mp4` a los 30 d de creada; regenerar después una parte `edit` la vuelve `reference` (los borradores viven 7 d: casi nunca pasa) |
| RA6 | Los 30 d se cuentan desde el análisis, no desde la elección | Un reel guardado el día 1 y elegido el día 29 pierde su fuente a mitad del plan | La ventana se copia al crear las partes; si la fuente ya no está, `source_purged` → `reference` y la pantalla lo dice. Las ideas que ve el dueño tienen ≤ 7 d |
| RA7 | Alguien agrega a una tabla global una columna de negocio | Fuga entre negocios | Test estático de columnas (13.2) y revisión de seguridad del PR (ADR 42 §6) |
| RA8 | La ruta crítica pasa por siete tickets de ADR 42 que nadie empezó | La fase 1 llega después que el resto de la épica | Pistas paralelas de 13.4; creative y UI prueban con el análisis de ejemplo de VE-04a |

### 13.9 Fila corregida del §11

Decidió: **Deivid Vargas, 2026-11-02**. La fila del ADR 44 ya está en `docs/arquitectura.md` §6 (la escribió el hilo principal); este documento no la toca.

| # | Pregunta | Decisión | Recomendación del §11 | Puerta |
|---|---|---|---|---|
| F1 | ¿Cómo cuenta un video por partes en el plan? | **(b) Segundos de video al mes para todo video de Seedance** (13.5; reemplaza D5; VE-21) | (a) cada parte = 1 video | Una vía para el cliente: las cifras se confirman con el fundador antes de escribir el texto |
| F2 | ¿Unión local o con `edit`? | Local; `edit` solo tras VE-18 | igual | Dos vías |
| F3 | ¿Cuándo analizar el reel? | **Al listar, en la corrida semanal de ADR 42** (13.3) | al elegirlo | Dos vías |
| F4 | ¿Alcance y muestreo? | Reel completo ≤ 60 s; 2 fotogramas por plano + 3 anclas; 720×1280; tope 32 | igual | Dos vías (`sampling_version`) |
| F5 | ¿Análisis global o por negocio? | **Global, sin negocio, junto a `public_reels`, hecho por el `reels-worker`** (13.2) | por negocio | Una vía (filas compartidas); se revierte copiando filas a una tabla con RLS |
| F6 | ¿Modo por defecto según personas? | `edit` sin personas observadas; `reference` con personas o duda; nunca pasar solo a Avatar | igual | Dos vías |
| F7 | ¿Partes sin reel en la fase 1? | A mano en la fase 1; «Proponer partes» con IA en la 2 | igual | Dos vías |
| F8 | ¿Una aprobación o una por parte? | Una, del video completo | igual | Dos vías |
| F9 | ¿Retención del reel ajeno? | Fuente y fotogramas a 30 d; ficha de texto a 90 d | fuente a 30 d | Dos vías |
| F10 | ¿Se firma como ADR 44? | Sí | sí | — |
| P2 | ¿Una parte es siempre un corte? | La IA junta cortes seguidos en partes de 4–10 s, tope 6 | — | Dos vías |
| P3 | ¿Voz y vista previa del presentador? | Su voz solo en sus partes; sin vista previa barata | — | Dos vías |
| P5 | ¿«Extender video» es la entrada C? | Sí (13.6) | — | Dos vías |
| P6 | ¿Avisar que «Igual al original» conserva manos y fondo de otra cuenta? | Validar con 3 dueños; sin aviso en la fase 1 | — | Dos vías |

**Lo que este documento no cierra:** el fundador confirma 40/80/160 s y «+20 s»; backend y creative alinean VE-03, VE-04a, VE-04b, VE-04d, VE-12 y VE-21 con 13.2–13.5 y 13.8 (en especial `wanted_at`, el tope de flota en lugar del diario por negocio, la purga global en el `reels-worker` y la ventana a 30 d); platform-engineer confirma `QUALIFY_CREATIVE_DISPATCHER=queue` en producción y fija el `mem_limit` del `reels-worker`.
