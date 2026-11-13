# Video por partes — historias de backend listas para Meegle (VE-03, VE-04a–d, VE-12)

**Estado:** `[REESCRITO TRAS ADR 44]` — backend-engineer, 2026-11-02, sobre `main` en `56746531` (cabeza de migraciones **0108**, igual en `origin/main`). Sin llamadas pagadas, sin código, sin commit. Aplica lo que Deivid firmó hoy (ADR 44, `docs/arquitectura.md:301`): **F1 = (b)** cupo de video en segundos; **F3** el reel se analiza **al listar**, en la corrida semanal de ADR 42; **F5** análisis **global**, sin tenant ni RLS, junto a `public_reels`, ejecutado solo por `reels-worker`; **F9** fuente y fotogramas a 30 días, ficha a 90. Tablas y columnas con los nombres de `docs/diseno-video-por-planos.md` §13 (principal-architect, en paralelo).
**Tickets:** VE-03 m-24921055 · VE-04a m-24921056 · VE-04b m-24921057 · VE-04c m-24921058 · VE-04d m-24921059 · VE-12 m-24921060 (épica m-24921048, `docs/epica-video-por-partes.md:57-74`). ADR 42: R1 m-24854844, R3 m-24854845, R8 m-24854855, en Backlog y sin PR; los ids de R2, R4 y R5 no los verifiqué (el CLI de Meegle no tiene sesión aquí). **[V]** verificado en disco · **[D]** documentación o ticket · **[H]** hipótesis.

## 0. En una pantalla

1. **La pantalla ya no analiza.** Dos tablas globales (`public_reel_analyses`, `public_reel_analysis_shots`), sin `tenant_id` ni RLS, como 0036. Solo `reels-worker` las escribe, con su rol `qualify_reels_worker`. La pantalla encola (`request_analysis`) y consulta (`get_analysis_status`). Se retira RN1: el video ya no pasa por el único proceso de Reflex.
2. **Dos entradas, una función.** La corrida semanal (R4) analiza sus ideas al final de `run()`, con la URL del MP4 recién leída (≤ 10 por negocio y corrida). El bucle del worker drena la cola bajo demanda. Las dos llaman a `run_analysis(analysis_id, charge=…)`.
3. **R2 no tiene puerta pública [V].** `require_tenant_prefix` rechaza toda clave fuera de `t/{tenant}/` (`qualify_shared/objects/keys.py:46-61`) y `delete_prefix` pasa por él (`gate.py:281-292`). Sumar `public/reel-analyses/` a `PURGEABLE_ROOTS` **no funciona**: hace falta una puerta pública aparte (VE-04a), que R12 y R13 reutilizarán.
4. **Costo [V].** `consumption_scope` exige un tenant y `record_consumption` sin tenant no escribe nada (`consumption/__init__.py:192-226, 260-263`). La fila global es el registro del costo; el registro de consumo recibe copia solo cuando un negocio disparó la corrida (como ADR 42 §2.4).
5. **Cadena mínima de ADR 42 (§4):** R1 → R2 → R4 (con R3) y R5 → R8. **Corte mínimo para que creative pruebe `plan_from_analysis` con un análisis real:** VE-03 + VE-04a + VE-04c + VE-02 (creative), en local con `just reel-analysis-tick --once`: **no pasa por ninguna R**. En producción pasa por **R8** (el servicio `reels-worker`) y, por sus dependencias, por toda la cadena, salvo que se parta R8 (§6).
6. **Necesita decisión (§6):** partir R8; la columna `lane` y el DELETE a los 90 días, que no están en la lista del arquitecto; un cupo bajo demanda global y no por negocio.

## 1. Qué dice el diseño y qué hay en el código

| # | El diseño dice | Código | Veredicto y corrección |
|---|---|---|---|
| V1 | Haiku recibe fotogramas por `claude_tools` | `create_turn` acepta cualquier `messages` (`claude_tools.py:541-600`); `brief_ai.py:162-183` ya manda bloques `image` en base64; Langfuse cambia cada imagen por un marcador (`claude_tools.py:444-462`) **[V]** | **Sí se puede, sin tocar `claude_tools`.** Pero el tope por dólares (`DollarMeter` → `turn_input_ceiling`, `:360-389`) cuenta los **bytes** del pedido como tokens: con 32 fotogramas en base64 (~6 MB) acotaría ~6 M tokens (≈ USD 0,60) y un tope razonable rechazaría la llamada. No se usa `budget`; el costo se acota por estructura (≤ 32 imágenes, `max_tokens` fijo) y un test lo comprueba |
| V2 | La transcripción con tiempos sale de `transcript_with_timestamp` | `fetch_instagram_transcript` solo lee `transcripts[].text` (`scrapecreators_client.py:735-756`); el mismo endpoint trae `transcript_with_timestamp[].start/end/text` (m-24888194) **[D]**. TikTok: `captionUrl` (WEBVTT gratis, ~30 d); `vtt_text` tira los tiempos (`:759-775`) **[V]**. La caché es la memoria de Reflex, solo texto (`Qualify/reels_discovery.py:350`) **[V]** | Guardar los tramos al listar (VE-04b) y persistirlos en R3 (§4). El análisis no llama a ScrapeCreators. Nunca la transcripción con IA de TikTok, que cobra créditos |
| V3 | Analizar hasta 60 s cabe en los 80 MiB | `prepare_reference` ya baja el archivo entero hasta 80 MiB y solo decodifica 5 s (`reel_reference.py:16, 46-73`) **[V]** | Crece la decodificación (~12 veces), no la descarga. Un reel de 3 min a ~4 Mbps pasa de 80 MiB y se rechaza **[H]**. Se registra el intervalo cubierto |
| V4 | Tarea en segundo plano de Reflex | Reflex de producción: `GRANIAN_WORKERS: "1"`, `mem_limit: 512m`, 183 MiB en reposo (`deploy/docker-compose.prod.yml:236-252`); descarga en dos copias (`reel_reference.py:58-73`) y PyAV sobre `io.BytesIO` (`qualify_creative/video/fit.py:280`) **[V]** | **Resuelto por F5:** corre en `reels-worker`. Las tres condiciones pasan al worker: archivo temporal, uno a la vez por proceso y pico medido, el dato con el que R8 fija su `mem_limit` |
| V5 | No usa `creative-worker` | «A new GRANT to this role is a change to ADR 41» (`0096_creative_jobs_vendor_slots.py:62-70`) **[V]** | Confirmado por F5. `qualify_creative_worker` no recibe nada; VE-04d lee por `tenant_session` |
| V6 | `UNIQUE (…, source_sha256, …)` | El hash se conoce después de bajar el video y la fila nace antes | **`UNIQUE (network, post_id, analysis_version)`**, global; `source_sha256` es procedencia. Un `ok` no se reescribe nunca |
| V7 | Fuente y fotogramas en R2 | `require_tenant_prefix` (`keys.py:46-61`); `_purgeable_prefix` llama primero a `require_tenant_prefix` (`gate.py:281-292`); `PURGEABLE_ROOTS = ("generated/",)`, y sumar una raíz «es una decisión revisada» (`gate.py:75-79`); ninguna clave `public/` en el código (`grep`, sin resultados) **[V]** | Claves `public/reel-analyses/{network}/{post_id}/{analysis_id}/source/source.mp4` y `…/frames/{shot:02d}-{n}.jpg`. Puerta pública nueva con raíces cerradas, forma exacta de la clave y su propio test (VE-04a) |
| V8 | Purga con el job de ADR 39 | `daily_chore` corre en `calendar-worker` y va por negocio (`retention_job.py:116-137`; `docker-compose.prod.yml:400-420`) **[V]** | La purga global la hace `reels-worker` (VE-12, razones allí) |
| V9 | Idempotente con concesión | `acquire` / `renew` / `release` con `lease_token` + `lease_until` (`creative/pipeline.py:58-108` en `HEAD`) **[V]** | Se copia sobre la tabla global, con el rol del worker y `FOR UPDATE SKIP LOCKED` |
| V10 | `content_briefs.kind` admite `shot_video` | Última ampliación: 0068 (`0068_clip_kind.py:26-42`); su `downgrade` se niega con filas (`:45-61`) **[V]** | Mismo patrón, solo si VE-01 mantiene `shot_video` (la épica dice «un Clip con más de una parte», `epica-video-por-partes.md:31`) |
| V11 | Costo y procedencia por ejecución | `claude_tools` registra cada llamada (`:164-197`) dentro de `consumption_scope`, que exige `tenant_id` y escribe por `tenant_session` (`consumption/__init__.py:192-226`); sin tenant no escribe (`:260-263`); FK a `tenants` (`0105_consumption_ledger.py:53-58`) **[V]** | Tokens y `cost_usd` siempre en la fila global; copia `operation="reel_analysis"` al negocio que disparó la corrida |
| V12 | «El extractor no ve métricas» (m-24880680) | La tarjeta lleva vistas, me gusta, `lift`, `affinity`, `format`, `hook` y `reason` (`Qualify/reels_discovery.py:771-795`) **[V]** | `ReelSource` no tiene esos campos (test). El `handle` tampoco va al análisis: se lee de `public_reels` |
| V13 | La fuente sirve para cortar partes `edit` | `normalize_reference` exige 24–60 fps (`reel_reference.py:84-85`): límite de Seedance **[V]** | Un reel a 15 fps se analiza igual; `edit_eligible = false` y la parte va en `reference` |
| V14 | Negocio sellado (ADR 43 §2.4) | `replicate` relee `auth.session_tenant_id` antes de escribir (`Qualify/discover_reels.py:313-357`) **[V]** | Sigue siendo el patrón de la pantalla. El análisis no tiene negocio: `tenant_mismatch` sale de la lista de errores; `tenant_id` solo abre `tenant_session` por su rol (precedente `creators/repository.py:1-4`) |
| V15 | (nuevo) Tablas globales y `test_rls_policy_shape` | El test solo enumera tablas con columna `tenant_id` (`test_rls_policy_shape.py:39-48`); 0036 no lo tocó (`0036_creator_pool.py:12-14`) **[V]** | No hay que «ajustarlo como 0036»: basta con no tener `tenant_id`. Se suman las dos tablas a `_GLOBAL_TABLES` (`:30`) para fijar que no lleven políticas, más un test de que no tengan `tenant_id` ni `brand_id` (riesgo de ADR 42 §6) |
| V16 | (nuevo) La corrida conoce la URL del MP4 | `public_reels` no tiene columna de video (`adr-42-ideas-reels-costo.md:114`); la URL vive solo en la tarjeta (`reels_discovery.py:789`) y dura ~24 h en TikTok y ~33 h en Instagram (`scrapecreators_client.py:550-554`) **[V]** | La corrida analiza en el acto, con la URL recién leída. R3 suma `video_url` + `video_url_at`, que también necesita el reproductor de R7 (ADR 42 §2.14) |
| V17 | (nuevo) Precedentes para el rol | `qualify_creative_worker`: NOBYPASSRLS, contraseña de desarrollo, NOLOGIN en producción sin contraseña (`0096_…:62-80`); su puerta solo la importa su worker (`test_creative_job_queue.py:150`). 0108 usa una función SECURITY DEFINER acotada; 0044 la evitó porque bastaba un GRANT (`0044_social_account_claims.py:14-20`) **[V]** | `qualify_reels_worker` sigue a 0096. La pantalla encola con un GRANT de INSERT por columnas, sin función (VE-03) |

## 2. Historias (formato `docs/formato-tickets-meegle.md`, tarea técnica o mejora)

Siguen seis: **VE-03, VE-04a, VE-04b, VE-04c, VE-04d, VE-12**. VE-04b no cambia. Las otras cinco se reescriben para F3, F5 y F9.

### VE-03 · m-24921055 · `Migración: análisis global de reels y partes de un video`
**P1 · M · Depende de:** VE-01 (m-24921049, firmado). De ADR 42, ninguna: no hay FK a `public_reels` · **Etiqueta:** `Infraestructura` · **Área:** BE

**Contexto**
F5: el análisis es dato de un reel público; se hace una vez por reel, no por negocio, y solo `reels-worker` lo escribe (ADR 44). Lo que sí es de cada negocio (las partes de un video y el brief de cada versión) sigue con RLS. Hoy nada de esto existe: la memoria de Reflex se pierde en cada despliegue (`Qualify/reels_discovery.py:350`).

**Qué hay que hacer**
- Número: el siguiente a la cabeza de `origin/main` (el siguiente libre después de R3, que toma 0117; hoy `main` llega a 0116). Si cambia la cabeza, se renumera en la rama; nunca se edita lo que está en `main`.
- Rol `qualify_reels_worker`: IF NOT EXISTS, NOBYPASSRLS, contraseña de desarrollo; en producción NOLOGIN hasta `QUALIFY_DB_REELS_WORKER_PASSWORD` (`deploy/bootstrap_db_roles.py`), como 0096 (`:62-80`). Lo crea esta revisión porque es la primera que lo usa; R8 solo suma sus GRANT.
- `public_reel_analyses` con las columnas de §13. Además: CHECK de `network IN ('tiktok','instagram')` (como `0036_creator_pool.py:58`), `post_id <> ''`, `status`, `stage`, `transcript_source`, `error_code` (lista cerrada, §3), `covered_to_s <= 60`, `model_calls <= 2`; UNIQUE `(network, post_id, analysis_version)`; índice de la cola `(lane, created_at) WHERE status IN ('queued','running')` e índice de la purga `(source_purge_after) WHERE source_purged_at IS NULL`. **Propuesta fuera de §13:** `lane` (`immediate` / `weekly`, por defecto `immediate`) para que la cola bajo demanda no espere detrás de la corrida del lunes (§6). Docstring: excepción firmada (ADR 44, F5), con el argumento de 0036 y la regla que la sostiene: **ninguna columna dice qué negocio pidió, eligió o usó un reel** (ADR 42 §2.2).
- `public_reel_analysis_shots` con las columnas de §13: PK `(analysis_id, shot_index)`, FK ON DELETE CASCADE, CHECK `end_s > start_s` y de `people_presence` / `visible_faces`.
- GRANT. `qualify_reels_worker`: SELECT, INSERT, UPDATE en las dos (y DELETE si se aprueba la purga de 90 días, §6). `qualify_app`: SELECT en las dos e **INSERT solo de las columnas** `(network, post_id, analysis_version, post_url, pending_video_url)`; las demás toman su valor por defecto. `qualify_admin`: SELECT (informes). Nada a `qualify_creative_worker`, a los roles de webhook ni a `qualify_connection_purge`. **Por qué un GRANT por columnas y no una función:** encolar es «crear si no existe» (`INSERT … ON CONFLICT DO NOTHING`, que solo pide INSERT, y SELECT sobre la clave). Postgres lo controla sin código propio, como prefirió 0044. Así `qualify_app` nunca puede escribir un `ok`, una ficha, una clave de R2 ni un costo en una fila que leen todos los negocios. Una función SECURITY DEFINER (0108) solo haría falta para reencolar, y reencolar lo decide el worker (VE-04a).
- Por negocio, con RLS como hasta hoy: `content_drafts.parent_draft_id` y `part_index` (las dos nulas o las dos con valor, `parent_draft_id <> id`, `part_index BETWEEN 1 AND 6`, FK compuesta ON DELETE CASCADE sobre `uq_content_drafts_tenant_id` de 0096, UNIQUE `(tenant_id, parent_draft_id, part_index)`, índice parcial); `piece_versions.brief_id` NULL, el brief que usó cada versión (pedido de creative, `traspasos/historias-video-por-partes-creative.md:27, 245`; forma exacta con VE-08); `content_briefs.kind` + `'shot_video'` solo si VE-01 lo mantiene.
- Tests: `_GLOBAL_TABLES` gana las dos tablas (`test_rls_policy_shape.py:30`); test nuevo de columnas prohibidas (`tenant_id`, `brand_id`) en las dos. ORM `PublicReelAnalysis` y `PublicReelAnalysisShot` en `qualify_api/referentes/models.py`; `ContentDraft` y `PieceVersion` los mapea creative (VE-08).

**Cómo verificarlo**
`just up && just migrate && just migrate-down && just migrate && just test-db`; `packages/api/tests/test_reel_analyses_schema_db.py` (`-m db`).

**Criterios de aceptación**
- [ ] Como `qualify_app`, insertar las cinco columnas crea una fila `queued`; fijar `status`, `reel_sheet`, `source_key` o `cost_usd` falla por permiso, y UPDATE y DELETE también.
- [ ] Un segundo `INSERT … ON CONFLICT DO NOTHING RETURNING id` con el mismo `(red, post_id, versión)` no devuelve nada.
- [ ] `has_table_privilege('qualify_creative_worker', 'public_reel_analyses', 'SELECT')` es falso; `qualify_reels_worker` no tiene BYPASSRLS.
- [ ] Ninguna de las dos tablas tiene `tenant_id`, `brand_id` ni políticas; `test_rls_policy_shape` pasa.
- [ ] Una hija sin padre, un `part_index` repetido o igual a 7 se rechazan; borrar el padre borra las hijas; por `tenant_session(B)` no se ven las hijas de A.
- [ ] CI: upgrade → downgrade base → upgrade limpio (el `downgrade` borra el rol, con NOTICE si otra base lo usa, como 0096); `just ci-lint` y `just ci-test` en verde.

**Fuera de alcance:** las tablas de ADR 42 (R3); `creation_charges.video_seconds` (VE-21, «Lo que falta de tu lado»); el ORM de `content_drafts`.
**Referencias:** diseño §7 y §13; `0036_creator_pool.py`; `0096_creative_jobs_vendor_slots.py`; `0103_piece_versions.py`; skill `qualify-migration`.

### VE-04a · m-24921056 · `Referentes: encolar y ejecutar el análisis de un reel en reels-worker`
**P1 · M · Depende de:** VE-03 · en producción, R8 (m-24854855) · **Etiqueta:** `Feature` · **Área:** BE (+ `packages/shared`)

**Contexto**
F3 y F5: el reel se analiza al listar, una vez para todos, en `reels-worker`. La pantalla solo pide y consulta. Esta historia hace la cola, la descarga, la puerta pública de R2 y el guardián de costo; la llamada a Haiku es VE-04c.

**Qué hay que hacer** — `referentes/reel_analysis.py` (servicio), `reel_analysis_store.py` (Protocol con versión en memoria y versión Postgres) y `reel_analysis_worker.py` (`drain_once`; CLI `--once` / `--interval`):
- **Tipos del contrato, primero**, con el ejemplo `tests/fixtures/reel_analysis_sample.json`, para que creative empiece VE-08 con la versión en memoria: `ReelSource(network, post_id, post_url, video_url, caption, transcript)`, sin métricas, veredictos ni `handle` (V12); `AnalysisRef(id, status, reused)`; `AnalysisStatus` (§3); `ReelAnalysis` y `ShotAnalysis` inmutables; `RunCharge(tenant_id, brand_id, run_id)`.
- **Lado de la pantalla** (`qualify_app` por `tenant_session`, solo por su rol): `request_analysis(tenant_id, source) -> AnalysisRef`: `source_allowed` (`reel_reference.py:31-43`); si hay un `ok` de la versión vigente, `reused`; si no hay fila, `INSERT … ON CONFLICT DO NOTHING` y relee; sin `video_url` devuelve `no_video`; con el cupo bajo demanda de la plataforma agotado (`QUALIFY_REEL_ANALYSIS_ON_DEMAND_DAILY`, 50 por día) devuelve `daily_limit` sin insertar. Más `get_analysis_status`, `get_analysis` (solo `ok`) y `analysis_badges(tenant_id, keys)`, una consulta para toda la lista de ideas (§3).
- **Lado del worker** — puerta nueva `qualify_shared/db/reels_worker.py` (`reels_worker_session()`), importada solo por el worker, como `creative_worker.py:41-60`:
  - `drain_once()`: toma una fila `queued`, o `running` con la concesión vencida; `immediate` antes que `weekly`; `FOR UPDATE SKIP LOCKED`, `lease_token` nuevo y `attempts += 1` (patrón V9). `just reel-analysis-tick [--once]` es una pasada: el mismo código que llamará el bucle de R8.
  - `analyze_run_ideas(charge, sources) -> list[AnalysisRef]`: la llama R4 al final de `run()`, después de guardar las ideas. Crea filas `weekly` (o reencola una `failed` por URL vencida, con la URL nueva) y analiza en el acto hasta `QUALIFY_REEL_ANALYSIS_PER_RUN` (10) nuevas; reutilizar no cuenta.
  - `run_analysis(analysis_id, *, charge: RunCharge | None)`: (1) concesión de 2 min renovada cada 40 s; (2) `downloading`: si `pending_video_url` tiene más de 20 h, `source_expired` sin red; si no, baja a un **archivo temporal** por trozos con el tope de 80 MiB, sin redirecciones, calcula el sha256 al vuelo (patrón `stream_to_tempfile`, `creative/worker/downloads.py:102`) y borra `pending_video_url`; (3) normaliza hasta 60 s sin audio, sin exigir 24–60 fps (`edit_eligible`, V13); (4) sube por la puerta pública, registra ancho, alto, fps, segundos e intervalo cubierto, y fija `source_purge_after = now() + 30 d`; (5) llama al paso `describe` inyectado (VE-04c; aquí, un doble de prueba). Con `charge`, todo corre dentro de `consumption_scope(charge.tenant_id, brand_id=charge.brand_id, operation="reel_analysis")`; sin `charge`, el costo queda solo en la fila.
  - **Guardián**, contado **antes** de llamar: `model_calls` ≤ 2 por fila; tope de la flota por día (`QUALIFY_REEL_ANALYSIS_FLEET_DAILY`, 1.000 llamadas ≈ USD 5,5 **[H]**); reintento solo con un código reintentable y `attempts < 3`. Un análisis a la vez por proceso (`QUALIFY_REEL_ANALYSIS_CONCURRENCY`, 1 hasta medir).
- **Puerta pública en `packages/shared/objects`:** `PUBLIC_ROOTS = ("reel-analyses/",)`; `require_public_key(key)` exige la forma `public/reel-analyses/(instagram|tiktok)/<post_id>/<uuid>/(source/source.mp4|frames/NN-N.jpg)` y rechaza `..`; métodos `put_public`, `open_public`, `public_size` / `open_public_range` (para mostrar fotogramas) y `delete_public_prefix(prefix, execute)`, solo sobre `…/<uuid>/source/` y `…/<uuid>/frames/`. `PURGEABLE_ROOTS` no cambia. Test estático: solo `referentes.reel_analysis*` (y R12/R13 cuando lleguen) usan la puerta pública.
**Cómo verificarlo**
`uv run --no-sync pytest packages/api/tests/test_reel_analysis_request.py packages/api/tests/test_reel_analysis_worker.py packages/shared/tests/test_public_objects.py -q` (offline: `httpx.MockTransport` y un MP4 sintético hecho con PyAV); `just test-db` para el almacén y los GRANT. Pico de memoria con un reel real de 60 s y `describe` simulado (bajar del CDN no gasta créditos), con un script como `deploy/measure/creative-worker-memory.sh`, anotado en el PR.

**Criterios de aceptación**
- [ ] Dos negocios piden el mismo reel: queda una fila y ninguna columna dice quién pidió; con un `ok` existente, `reused = True` sin red.
- [ ] El pedido 51 del día termina en `daily_limit` sin insertar; la idea 11 de una corrida no se analiza.
- [ ] Una fila `immediate` sale antes que diez `weekly` más viejas.
- [ ] Una URL de más de 20 h termina en `source_expired` sin llamada HTTP; una redirección, un host fuera de `_SUFFIXES` o más de 80 MiB, en `source_unavailable` / `source_too_large`, sin archivos temporales ni objetos en R2.
- [ ] Con la concesión viva de otro proceso, no hace nada; vencida, la retoma y `attempts` sube; con `model_calls = 2`, no llama.
- [ ] La puerta pública rechaza `public/reel-analyses/instagram/`, `t/<x>/…`, `public/reel-covers/…` y `..`; `delete_prefix` sigue rechazando `public/`.
- [ ] Con `charge`, una fila de consumo `reel_analysis` en el negocio que disparó; sin `charge`, ninguna, y la fila global guarda tokens y costo.
- [ ] Pico ≤ 150 MiB sobre el reposo (si no, PyAV corre en un proceso hijo); `just ci-test` en verde.

**Fuera de alcance:** Haiku (VE-04c); detección de planos (VE-02); el servicio de producción y el programador (R8); la pantalla (UI-2, m-24921076).
**Referencias:** diseño §4.1, §8 y §13; `reel_reference.py`; `creative/worker/downloads.py`; `qualify_shared/objects/gate.py`; ADR 42 §2.4.

**Implementado (2026-11-04, rama `feat/m-24921056-pedir-analisis-reel`) — en qué se aparta de lo de arriba, y por qué** [V]:
- **Sin `lane`:** 0119 trae `wanted_at`. El orden es el de §13.3 del diseño: URL pendiente de bajar → `wanted_at` (la más vieja) → el resto.
- **Sin `RunCharge` ni `consumption_scope`:** decisión #10 de la épica. El costo queda en la fila (`cost_usd`, tokens) y en Langfuse; `analyze_run_ideas` devuelve el costo a R4, que lo suma a `brand_reel_runs.cost_usd`, y no escribe nada del negocio. Firma = `IdeaAnalyzer` de R4; `reel_runs.IdeaSource` pasa a ser `ReelSource`.
- **Tope de flota 1.500 llamadas/día** (§13.3), contado antes de llamar. La fila espera `queued` 15 min y `get_analysis_status` lo dice con `fleet_paused`. El cupo bajo demanda de 50/día de la plataforma **sigue** (`daily_limit`), porque todavía no hay comprobación de que el reel sea una idea del negocio (§13.3 la pide y la apoya en R7).
- **`describe` inyectado:** sin él (hoy), una pasada solo baja y guarda la fuente: «bajar primero y analizar después». No hay un `describe` de mentira: un `ok` falso lo leerían todos los negocios y nunca se reescribiría.
- **Edad de la URL:** no hay columna con la hora de la URL. Se usa `created_at` (o la hora conocida, si la corrida analiza en el acto) y además la caducidad firmada por el CDN (`oe` en Instagram, `x-expires`/`expire` en TikTok).
- **La fuente se guarda remuxada, sin recodificar** (§13.2): solo el video, hasta 60 s, sin audio.
- **Memoria medida** (Windows, en local, sin red: reel sintético de 60 s, 720×1280, 29,2 MiB, descarga + remux + subida): reposo 71,5 MiB, pico 89,5 MiB, **+16,4 MiB**. La descarga va a un archivo por trozos de 1 MiB, y la lectura desde R2 va por rangos de 8 MiB. Falta medirlo con un reel real en la imagen de Linux (R8).

### VE-04b · m-24921057 · `Referentes: guardar con sus tiempos la transcripción que ya se paga`
**P2 · S · Depende de:** — (en paralelo) · **Etiqueta:** `Improvement` · **Área:** BE (coordina con UI el cambio en `Qualify/reels_discovery.py`)

**Contexto**
Al listar ya se paga 1 crédito por cada transcripción de Instagram, y los tiempos se tiran (V2). El análisis los necesita para repartir el habla por plano (D1), y ADR 42 R14 prohíbe llamar a ScrapeCreators al pulsar «Hacer uno parecido».

**Qué hay que hacer**
- Antes de escribir código, comprobar la forma con `just sc instagram media-transcript --url <reel> --cache-max-age 30d --pretty` y `just sc balance` antes y después (skill `qualify-scrapecreators`).
- En `scrapecreators_client.py`: `Transcript(text, segments, source)` y `Segment(start_s, end_s, text)`; `fetch_instagram_transcript_timed` lee `transcript_with_timestamp` en la **misma** llamada; `fetch_instagram_transcript` sigue devolviendo el texto (sin cambio para quien la usa); `vtt_cues(vtt)` junto a `vtt_text`, con los tiempos de cada cue. Corregir el comentario de `:719-724`.
- `_transcripts` (`Qualify/reels_discovery.py:350`) guarda `Transcript`; `ReelSource.transcript` se arma desde allí, del lado del servidor (no viaja a un var de estado).
- Registrar los créditos en el registro de consumo: `record_consumption(provider="scrapecreators", …)` con `credits_charged` de la respuesta (V11).

**Cómo verificarlo**
`uv run --no-sync pytest packages/api/tests/test_referentes_scrapecreators_client.py Qualify/test_reels_discovery.py -q`, con una respuesta sintética que imita la forma real.

**Criterios de aceptación**
- [ ] Listar reels hace el mismo número de llamadas que antes (test que cuenta las llamadas) y `transcript_for` devuelve el mismo texto.
- [ ] Una respuesta con `transcript_with_timestamp` da tramos con inicio y fin en segundos; un VTT con tres cues da tres tramos.
- [ ] Un tramo de solo música («ah») se guarda tal cual: el análisis no lo convierte en guion.
- [ ] Cada transcripción pagada deja una fila de consumo con sus créditos; `just ci-test` en verde.

**Fuera de alcance:** la transcripción con IA de TikTok (cobra créditos); mover el pipeline a `packages/api` (ADR 42 R1).
**Referencias:** m-24888194 (inventario CLI 2026-10-29); `scrapecreators_client.py:701-775`.

**Estado (2026-11-06, rama `feat/m-24921057-transcripcion-tiempos`, sobre `main` en `1d794d83`, sin commit).** Construido. Los tramos usan `public_reels.transcript_segments` y `transcript_reader_version` de 0117. El candado contra el doble pago y la respuesta cruda van en la migración nueva `0136_transcript_claim` (pedido del fundador del 2026-11-06). 0136 sigue a `0135_brand_payment_methods` (cabeza de `main`). Forma verificada en vivo con el CLI, desde la caché, con 0 créditos (ver `docs/descubrir-reels-scrapecreators.md`).
- **Dónde quedó.** Desde #469 (R7/R8) la ruta que paga es `reel_runs.run` en el `reels-worker`. Ya no existen `Qualify/reels_discovery.py` (§VE-04b «`_transcripts`») ni `reels.transcript_for` / `_transcripts`. `Qualify/test_reels_discovery.py` sigue existiendo como test de la pantalla y no se tocó.
  - Cadena actual: `reels.transcribe_one` → `fetch_instagram_transcript_timed` / `fetch_tiktok_captions_timed` → `reel_runs._transcribe` → `ReelRunStore.save_transcript(segments=, reader_version=)` → `public_reels`.
  - De vuelta: `PublicReel.transcript_segments` → `_reel_dict` → `_analyze` → `ReelSource.transcript_segments`, del lado del servidor y sin llamar al proveedor.
  - El cliente vive en `qualify_api/vendors/scrapecreators.py`: `Segment`, `Transcript`, `vtt_cues` y `configure_consumption_ledger`.
- **Desvíos.**
  - `vtt_text` no cambia (las etiquetas WebVTT solo se quitan en los tramos de `vtt_cues`), para que el texto de la tarjeta sea el de antes (criterio 1).
  - El criterio 1 dice «`transcript_for` devuelve el mismo texto». Como `transcript_for` ya no existe, se prueba que la corrida guarda el mismo texto que el lector sin tiempos.
  - La fila de consumo usa como clave el `request_key` del portón, uno por llamada. 0136 hace único `consumption_ledger.idempotency_key` (índice parcial `WHERE idempotency_key IS NOT NULL`). Antes de crearlo se revisó que fuera seguro: el único escritor con clave es esta fila; `claude_tools` no pone clave; la base local tenía 0 filas el 2026-11-06. Las escrituras (`record_consumption`, `consumption_scope`) usan `ON CONFLICT … DO NOTHING`.
  - **No cuadra 1 a 1 con `vendor_usage_events` (conocido, fuera de alcance).** Si la respuesta sale de la caché del proveedor, el portón igual reserva 1 crédito y el registro de consumo no escribe fila.
  - **Candado contra el doble pago (0136).** `public_reels.transcript_lock_until`: `claim_transcript` antes de pagar (un `UPDATE … WHERE transcript_at IS NULL AND (claim libre o vencido) RETURNING`), `release_transcript` si la llamada falla, `save_transcript` lo borra. Dura `TRANSCRIPT_CLAIM_SECONDS` = 180 s. Un reel reclamado por otro negocio no se paga ni cuenta como pagado, pero ocupa su lugar entre los 40. Al final se lee del almacén (`stored_transcripts`). Solo se reclama Instagram. Detalle en `docs/descubrir-reels-scrapecreators.md`.
  - **Respuesta cruda (0136).** La respuesta pagada se guarda en `vendor_payloads` y el reel la apunta con `transcript_payload_id` y `transcript_payload_fetched_at`. Es para volver a leerla con otro `transcript_reader_version`.
  - En los dicts de la corrida, `transcriptSegments` va como lista de `{start, end, text}` y no como `TranscriptSegment`, para que se pueda pasar a JSON. Se convierte a `TranscriptSegment` solo al armar `IdeaSource` en `_analyze`.
- **Pruebas por criterio.**
  1. `test_a_run_makes_the_same_calls_and_stores_the_same_text_as_before` y `test_listing_transcripts_makes_one_call_per_reel_as_before`.
  2. `test_transcript_with_timestamp_gives_stretches_in_seconds`, `test_the_live_answer_shape_gives_its_text_and_stretches`, `test_a_vtt_with_three_cues_gives_three_stretches` y `test_the_timed_stretches_are_stored_and_reach_the_analysis`.
  3. `test_a_music_only_stretch_is_kept_as_given` y la fila «ah» de las pruebas de la corrida.
  4. `test_a_paid_transcript_leaves_one_consumption_row`, `test_each_paid_transcript_leaves_one_ledger_row_and_a_rerun_none` y, en Postgres, `test_a_paid_transcript_writes_one_row_in_the_real_consumption_ledger`.
  - Candado y respuesta cruda, sin base de datos (`test_referentes_reel_transcript_claim.py`): `test_a_fresh_claim_is_taken_once_a_stale_one_again_and_a_save_clears_it`, `test_the_owner_releases_its_own_claim_only`, `test_two_businesses_at_once_pay_one_transcript_and_the_other_reads_it_later`, `test_a_reel_claimed_elsewhere_is_not_paid_and_is_read_back_once_written`, `test_a_reel_claimed_elsewhere_keeps_its_slot_under_the_paid_ceiling`, `test_a_failed_call_releases_the_claim` (4 casos), `test_tiktok_subtitles_are_free_and_never_claimed` y `test_a_paid_transcript_keeps_its_raw_answer_once`.
  - En Postgres (`test_referentes_reel_transcript_claim_db.py`): `test_two_businesses_transcribing_one_reel_at_once_pay_once` (dos hilos, dos negocios: 1 llamada, 1 fila de consumo, 1 respuesta cruda), `test_a_stale_claim_is_reclaimable_a_fresh_one_is_not`, `test_a_failed_vendor_call_releases_the_claim` y `test_a_repeated_ledger_key_is_dropped_never_fatal`.

### VE-04c · m-24921058 · `Referentes: ficha del reel por planos con Haiku (familias D3 y rostros), en reels-worker`
**P1 · L · Depende de:** VE-04a, VE-02 (m-24921062: `detect_shots`, `sample_frames`) · **Etiqueta:** `Feature` · **Área:** BE

**Contexto**
D1–D3 de m-24880680: Haiku describe lo que se ve, con presencia de personas y rostros en la misma llamada, en familias cerradas y con `observed / not_observed / unknown`. Es el paso `describe` de `run_analysis`: corre en `reels-worker` y escribe en las tablas globales, una vez por reel para todos los negocios.

**Qué hay que hacer** — `referentes/reel_analysis_ai.py`:
- Etapa `detecting`: `detect_shots(fuente, max_seconds=60)` sobre el archivo temporal (pedir a creative que `detect_shots` y `sample_frames` acepten `Path` además de `bytes`: el diseño §8 solo dice `bytes` y `fit.py:280` abre `io.BytesIO`). Muestreo F4: 2 fotogramas al 15 % y al 85 % si el plano dura ≥ 1 s, si no 1; anclas en 0, 1 y 3 s; tope 32; si se pasa, 1 por plano; si aun así se pasa, se cubren los primeros planos y `covered_to_s` lo dice. JPEG de 720×1280 por la puerta pública en `…/frames/{shot:02d}-{n}.jpg`; `detector_version`, `sampling_version` y `sampling_params` en la fila.
- Etapa `describing`: `model_calls += 1` **antes** de llamar; una llamada `create_turn` con `ModelConfig("claude-haiku-5-5", "low")` y la herramienta `describir_reel` (pensada como `strict_tool`; **desvío medido en vivo el 2026-11-05:** con `strict: true` la API responde 400 «The compiled grammar is too large», porque nueve objetos anidados por plano dentro de una lista superan el límite de la gramática; la herramienta va sin `strict` y el código valida la respuesta: forma, planos, fotogramas de evidencia y familias faltantes → `unknown`). Por plano, las 11 familias de m-24880680, cada una `{status, value, evidence_frames}`, más `people_presence` y `visible_faces`; por reel, gancho, estructura, cierre y llamado a la acción, estilo y tono. Música y voz siempre `unknown` (D1): el habla la asigna el **código** por tiempo desde la transcripción de la fila (VE-04b), no el modelo.
- Instrucciones: sin identidad, sin atributos sensibles, sin métricas; el texto en pantalla y la transcripción van marcados como material ajeno, nunca como instrucciones. El análisis no conoce ninguna marca: es global.
- Validación: se descartan fotogramas de evidencia no enviados y planos que no existen; una familia que falta queda `unknown`. Planos, `reel_sheet`, procedencia (`model_id`, `model_revision` de la respuesta, versiones de prompt, esquema, muestreo y detector, tokens y `cost_usd`), `status = ok`, `stage = done` y `finished_at` se escriben **en la misma transacción, con el `lease_token` vigente**: si otro proceso tomó la fila, no se escribe nada.
- `REEL_ANALYSIS_PROMPT_VERSION` y `REEL_ANALYSIS_SCHEMA_VERSION`; `analysis_version` sube si cambia cualquiera de las cuatro versiones.

**Cómo verificarlo**
`uv run --no-sync pytest packages/api/tests/test_reel_analysis_ai.py -q`, con el cliente de Claude simulado (`client_factory`, como `reels_ai.review_reels`). La medición real es VE-05 (m-24921050, `qualify-measure`).

**Criterios de aceptación**
- [ ] Con Claude simulado, dos negocios con el mismo reel hacen 1 llamada; la fila guarda modelo, revisión, versiones, tokens y costo.
- [ ] Cada familia de cada plano trae `observed / not_observed / unknown`; sin `visible_faces` en la respuesta, queda `unknown`, nunca `not_observed`.
- [ ] Un tramo de 2,0–3,5 s cae en el plano que contiene ese intervalo; sin tramos, `spoken_text` queda vacío y el texto plano se guarda en la fila.
- [ ] El pedido nunca supera 32 imágenes y su peor costo, calculado con `PRICES` (`claude_tools.py:49-50`), es ≤ USD 0,01 (test). *(m-24955652 lo sube a USD 0,0115 con 9.000 tokens de salida; ver «Ajuste m-24955652».)*
- [ ] La traza de Langfuse no lleva base64 (`claude_tools.py:444-462`).
- [ ] Una respuesta cortada o sin la herramienta deja `failed / model_failed` sin planos a medias; una escritura con `lease_token` vencido no deja nada; `just ci-test` en verde.

**Fuera de alcance:** el plan de partes (`plan_from_analysis`, VE-08); medir el acierto (VE-05); analizar el audio.
**Estado (2026-11-05, rama `feat/m-24921058-ficha-por-planos`, medido en vivo con dos reels):** construido en `referentes/reel_analysis_ai.py` (`ReelDescriber`). Desvíos respecto de esta historia, y por qué:

- **Herramienta no estricta.** Con `strict: true` la API responde 400 «The compiled grammar is too large»; `describir_reel` va sin `strict` y el código valida todo: forma de la respuesta (una respuesta mal formada se reintenta, nunca queda un `ok` vacío; los JSON enviados como texto se decodifican), planos y fotogramas de evidencia inexistentes, familias faltantes → `unknown`.
- **Versiones.** Cada iteración en vivo subió la versión para que una ficha corregida sea otra fila: hoy `ANALYSIS_VERSION = 6` (prompt `reel-sheet-prompt-7`, esquema `reel-sheet-schema-3`); la tabla `ANALYSIS_VERSIONS` guarda qué representa cada una. El reclamo que lleva a una llamada al modelo solo toma filas de la versión vigente (las viejas se descargan a lo sumo).
- **Texto en pantalla.** Solo el texto diseñado (títulos, preguntas, destacados, precios, llamados a la acción); los subtítulos quemados (casi siempre automáticos y con errores) quedan fuera. Los destacados llevan `[destacado: <color real>, <tamaño>, …]`. Una limpieza conservadora quita solo etiquetas de cierre y las notas del modelo sobre el propio texto (prosa en minúscula que habla de subtítulos, fotogramas, recuadro, color, «texto en pantalla», «no cuenta», «se omite»); ante la duda se conserva, y el valor crudo queda en `raw_value`.
- **Gancho y cierre del reel** llevan `plano` (el plano donde ocurren); el código copia el texto en pantalla completo de ese plano en la ficha (el modelo cortaba sus propias citas).
- **Habla.** Cada tramo de la transcripción va entero al plano con el que más se solapa (empate → el anterior; medido: 6,547–9,477 s cae en el plano 6,8–8,8). Ese texto por plano se envía como material ajeno (sin `<`/`>`) y el modelo puede proponer `habla` corrigiendo con los subtítulos; el código solo la acepta si son sustituciones o borrados de palabras que no tocan dígitos, números en letra ni negaciones, borran a lo sumo una palabra y quedan cerca (texto corto: una palabra como mucho). La transcripción del proveedor queda intacta en la fila; `reel_sheet.spoken_text.corrected_shots` dice qué planos cambiaron.
- **Pagar es opcional y explícito:** solo con `QUALIFY_REEL_ANALYSIS_DESCRIBE=1` (o `--describe` en una corrida) y la clave de Anthropic; sin eso, o con `--download-only`, la pasada solo descarga. R8 lo recibe sin cambios de código con solo poner la variable. Un error de la cuenta (401, 403, 404, 400 de saldo) devuelve el intento y la llamada y pausa 15 min; un 400 de esquema, 413 o 422 falla la fila de una vez.
- **R2 sin sobrescrituras.** El bucket rechaza sobrescribir (ObjectLockedByBucketPolicy): fotogramas y fuente se escriben con `put_public_if_absent`; una fuente ya guardada de otro tamaño no se registra como si fuera esta descarga. Un fallo de escritura de fotograma reintenta como `source_unavailable` (no hay código de almacenamiento en el CHECK de 0119), nunca `model_failed` ni se cobra.
- **Costo.** Lo que gasta una llamada que no sirvió (cortada, sin herramienta, rechazo) queda en la fila; un rechazo falla de una vez. ≈ USD 0,0035–0,0055 por reel medido, a lo sumo 0,0099 (32 imágenes a 1.600 tokens de techo, transcripción recortada a 1.500 caracteres, 5.800 tokens de salida). **Reemplazado por el ajuste m-24955652 (abajo).**
- **Ajuste m-24955652 (2026-11-05, «salida cortada»).** VE-05 midió que con 5.800 tokens de salida 11 de 18 fichas reales se cortaban (y se cobraban): la salida crece ≈ 500–650 tokens por plano. Tres cambios, `ANALYSIS_VERSION = 7` (prompt `reel-sheet-prompt-8`, esquema `reel-sheet-schema-4`):
  - **Grupos de planos cortos** (`referentes/reel_analysis_groups.py`, `groups-min1s-max12-1`). Se parte de un grupo por plano detectado; mientras haya un grupo de menos de 1 s o más de 12 grupos, el grupo más corto (empate: el primero) se une con su vecino más corto (empate: el anterior). Haiku describe **grupos**; la fila guarda **los planos detectados** (VE-05 puntúa los cortes del detector, no los grupos). Cada plano guardado recibe la descripción de su grupo (familias, personas, rostros); los fotogramas se muestrean sobre los grupos y se guardan con el número del plano detectado donde caen (`…/frames/SS-n.jpg`), y la evidencia se traduce a esa numeración; el habla sigue por plano detectado y una corrección del grupo se reparte palabra por palabra entre sus planos. `reel_sheet.groups.members` dice qué planos forman cada grupo; gancho y cierre apuntan al primer plano del grupo. Un reel con todos sus planos de ≥ 1 s y como mucho 12 se describe igual que antes, plano por plano.
  - **Valores breves:** máximo 8 palabras por valor del plano y 12 por valor del reel, una o dos etiquetas de evidencia, `habla` vacía salvo que corrija una palabra. El texto en pantalla sigue literal y completo. Las instrucciones siguen sin palabras de ningún rubro (test).
  - **Lo heredado se marca (para VE-05 y VE-08).** Una familia `observed` cuya evidencia no incluye ningún fotograma del propio plano lleva `inherited_from_group: <grupo>`: la evidencia sigue nombrando los fotogramas de los planos hermanos que lo mostraron. Un plano sin fotograma propio nunca hereda un `not_observed`, ni en familias ni en `people_presence` / `visible_faces`, porque «no se ve» solo vale para fotogramas que el plano tiene: queda `unknown`. **VE-08:** un `visible_faces = not_observed` heredado habilitaría «Igual al original» (`docs/epica-video-por-partes.md:25`), y por eso nunca se hereda. Un `observed` heredado sí se conserva, y es el lado seguro: bloquea. Para puntuar personas y rostros por plano, VE-05 puede excluir o separar las familias con `inherited_from_group`.
  - **Habla por plano detectado.** Una corrección aceptada para el grupo se reparte entre sus planos, y cada plano vuelve a pasar el filtro de VE-04c (`correction_allowed` contra su propia transcripción). Si no lo pasa, o si la corrección lo dejaría sin habla, conserva la transcripción y no figura como corregido.
  - **Techo de salida 9.000.** Peor pedido con `PRICES`: **USD 0,011462** (12 grupos, 32 imágenes al techo de 1.600 tokens, transcripción recortada, 9.000 de salida); con 12 grupos el muestreo envía como mucho 27 imágenes → **USD 0,010628**. `MAX_REQUEST_USD = 0,0115` (test). Un `reel` que llega como texto se repara si contiene un objeto JSON (también entre ``` o tras un prefacio); si no, falla con el aviso `reel: str of N chars, not a JSON object`, sin contenido (test). Medición en vivo: `docs/modelos-generativos/pruebas.md` (REELSHEET-001).
- Familias por plano (nombres técnicos propios; D3 fija las familias, no sus nombres): `hook`, `subject`, `camera_motion`, `narrative`, `product`, `people`, `on_screen_text`, `music`, `voice`, `cta`, `style_tone` (música y voz siempre `unknown`); en `reel_sheet`: `hook`, `structure`, `closing_cta`, `style`, `tone`, `pacing` (medido del archivo) y `spoken_text`. El muestreo de VE-02 adelgaza parejo por encima de 32 (no «cubre los primeros planos»). Desde m-24955652 el muestreo se hace sobre grupos: un plano cuyo **grupo** no tiene fotograma queda todo `unknown`. Un plano que no tiene fotograma **propio** hereda de su grupo solo lo `observed`: las familias heredadas llevan `inherited_from_group`, y un `not_observed` heredado (familia, `people_presence` o `visible_faces`) pasa a `unknown`. Sin migración: usa las columnas de 0119.
**Referencias:** m-24880680; diseño §4.1; `referentes/reels_ai.py:211-328` (herramienta estricta; VE-04c no la usa estricta, ver arriba).

### VE-04d · m-24921059 · `Referentes: cortar de la fuente pública la ventana de una parte «Igual al original»`
**P1 · S · Depende de:** VE-04a, VE-02 (m-24921062: `cut.cut_window`) · **Etiqueta:** `Feature` · **Área:** BE

**Contexto**
Una parte `edit` manda a Seedance un corte de ≥ 4 s de la fuente (diseño §4.2). La fuente es global y se borra a los 30 días (F9); el corte tiene que vivir con la pieza del negocio (90 días desde el último uso, ADR 39), o una parte rehecha el día 35 ya no podría hacerse.

**Qué hay que hacer**
- `source_window(tenant_id, analysis_id, *, draft_id, start_s, end_s) -> str` (`referentes/reel_analysis_window.py`, `SourceWindows`). Lee la fila por `tenant_session` (SELECT de `qualify_app`). Corre solo en `creative-worker`: su punto de entrada (`creative/worker/__main__.py`) marca el proceso al arrancar (`creative.process.mark_worker_process`) y, sin esa marca, responde `wrong_process` sin leer nada (no sirve una variable de entorno: Reflex lee el mismo `.env.prod`); aun así abre `tenant_session`, nunca el rol `qualify_creative_worker`. Exige `status = ok`, `edit_eligible` y `source_purged_at IS NULL`, y segundos enteros de 4 a 10 (`PART_SECONDS`). Comprueba por RLS que `draft_id` es una pieza de ese negocio. Abre la fuente con `open_public` a un archivo temporal, corta con `cut_window` y guarda en `t/{tenant}/generated/{draft_id}/source-window-{analysis_id}-{start}-{end}.mp4` con `put_media`, que pasa por `require_tenant_prefix`. La misma clave se reutiliza: pedirlo dos veces no corta dos veces. El `analysis_id` va en la clave para que una parte cuyo reel de referencia cambia nunca reciba el corte del reel anterior. La copia existe solo para no cortar dos veces, no para sobrevivir a la fuente: con RA5 se purga a los 30 días como la fuente, y una parte rehecha después recibe `source_purged` y pasa a `reference`.
- Memoria: el corte de una ventana 1080x1920 sube ~295 MiB sobre la base (medido el 2026-11-05 con una fuente de 68 MiB y 60 s, 8 núcleos). Un candado de proceso con tiempo límite deja un solo corte a la vez (si vence: `window_unavailable` y la parte pasa a `reference`); nunca corre dentro de Reflex (un proceso de 512 MiB en producción).
- Errores `source_purged`, `not_edit_eligible` y `analysis_not_ready`: la parte pasa a `reference`, como con `refused_face`.
- Nota para creative: el corte no se registra como salida en `image_assets` y nunca se publica (diseño §7).

**Cómo verificarlo** — `uv run --no-sync pytest packages/api/tests/test_reel_analysis_window.py -q`.

**Criterios de aceptación**
- [ ] Una ventana 3–7 s de una fuente sintética dura 4 s ± 1 cuadro y queda bajo la carpeta de la hija.
- [ ] Una segunda llamada igual no vuelve a cortar; `start_s = 2.5` o 12 s de duración se rechazan.
- [ ] Con `source_purged_at` puesto, `source_purged` sin abrir R2; con un `draft_id` de otro negocio, error antes de leer la fuente.
- [ ] Pico de memoria del corte medido y anotado en el PR (la fuente puede pesar 80 MiB); `just ci-test` en verde.

**Fuera de alcance:** elegir la ventana alrededor de un plano corto (VE-08/VE-09); la purga (VE-12).
**Referencias:** diseño §4.2 y §8; `creative/retention.py:65` (`piece_prefix`); `qualify_shared/objects/gate.py:128-147`.

### VE-12 · m-24921060 · `Retención: borrar a los 30 días el video y los fotogramas del reel ajeno`
**P2 · S · Depende de:** VE-03, VE-04a, VE-04c (fotogramas); en producción, R8 (m-24854855) · **Etiqueta:** `Improvement` · **Área:** BE

**Contexto**
F9: la fuente y los fotogramas del reel ajeno (con rostros de terceros) se borran a los 30 días; la ficha de texto se queda 90. La purga es global, no por negocio.

**Qué hay que hacer**
- **La ejecuta `reels-worker`, no `calendar-worker`:** (1) es el único que escribe bajo `public/reel-analyses/`, así que quien guarda borra y la puerta pública no se abre a otro servicio; (2) ya tiene los GRANT de VE-03, y `calendar-worker` necesitaría UPDATE en una tabla global (`qualify_admin` solo tiene SELECT); (3) `daily_chore` va por negocio (`--tenant` / `--all-tenants`, `retention_job.py:116-137`), y una purga global dentro de un `calendar-worker --tenant X` local borraría datos de todos; (4) R11 (ideas a 4 semanas) ya es una tarea diaria del mismo worker (ADR 42, anexo R11).
- `referentes/reel_retention.py`: `purge_reel_sources(gate, now, execute) -> PurgeReport`. Toma filas con `source_purge_after <= now` y `source_purged_at IS NULL` (índice de VE-03), en lotes de 100; borra `…/source/` y `…/frames/` con `delete_public_prefix`; marca `source_purged_at` y `frames_purged_at` **después** de borrar; no toca la ficha ni los planos. Es idempotente.
- A los 90 días de `finished_at`, borra la fila (los planos caen por CASCADE) **si se aprueba el DELETE** (§6); si no, queda como deuda escrita en el PR.
- **RA5 (código nuevo, no la retención de 90 días de ADR 39):** la purga de 30 días también borra, por negocio, las copias `t/{tenant}/generated/{draft_id}/source-window-*.mp4` de VE-04d, contadas desde que se escribieron. El prefijo `generated/` es de la retención por negocio, así que esta parte corre allí y no en `reels-worker`; solo borra `source-window-*.mp4`, nunca el resto de la pieza.
- Una vez al día en el bucle del worker (`PURGE_EVERY_SECONDS`, como `retention_job.py:38`), con `QUALIFY_REEL_PURGE_EXECUTE` (prueba en local, 1 en producción); `just reel-purge [--execute]`.

**Cómo verificarlo** — `uv run --no-sync pytest packages/api/tests/test_reel_retention.py -q` (reloj y almacén falsos); `just test-db`; `just reel-purge` sin `--execute` en local.

**Criterios de aceptación**
- [ ] Día 29: no borra nada. Día 30: borra fuente y fotogramas, marca las dos fechas y deja ficha y planos; `get_analysis_status` dice `source_available = false` y VE-04d responde `source_purged`.
- [ ] Una segunda pasada no borra ni marca nada nuevo; en modo de prueba informa sin borrar.
- [ ] Un fallo de R2 en una fila no la marca y sigue con las demás.
- [ ] RA5: un `source-window-*.mp4` de 29 días sigue; uno de 30 días se borra aunque la pieza viva 90; el resto de la carpeta de la pieza no se toca; una segunda pasada no borra nada.
- [ ] `daily_chore` no la llama (test); `just ci-test` y `just test-db` en verde.

**Fuera de alcance:** la retención de las piezas hijas (ADR 39); la de las ideas (R11).

**Hueco conocido (revisión de VE-04a, 2026-11-04) [V]:** `public_reel_analyses` no tiene una columna con la hora en que se leyó la URL del CDN. El worker toma `created_at` como esa hora, salvo cuando la corrida analiza en el acto y la conoce. Una fila reencolada con una URL nueva (`refresh_url`) que no se baja en el acto queda juzgada por su `created_at` viejo y termina en `source_expired` aunque la URL esté viva. Pasa raras veces y no cuesta créditos. En la mayoría de los casos lo cubre la caducidad que firma el propio CDN (`oe` en Instagram, `x-expires`/`expire` en TikTok, `reel_analysis_source.url_expires_at`). Si hace falta cerrarlo, la solución es una columna `pending_video_url_at` en una revisión nueva (backend).
**Referencias:** ADR 39; ADR 44 F9; `creative/retention_job.py`; `qualify_shared/objects/gate.py:260-292`.

**Estado (2026-11-06, rama `feat/m-24921060-purga-fuente-reels`) [V].** La purga global (`reel_retention`) llegó con R8 (#469, 0134). VE-12 suma lo que faltaba, **sin migración**:

- **RA5:** los cortes del reel ya no van en la carpeta de la pieza: viven en `reel-windows/{tenant}/{draft_id}/source-window-{analysis_id}-{s}-{e}.mp4`, **fuera de `t/`**, porque el bucket de producción tiene un candado sobre `t/` que rechaza borrar y sobrescribir (m-24971181, el mismo motivo que movió la Galería a `gallery/`). Los escribe `ObjectGate.put_source_window`, que arma la clave con los UUID; las lecturas del negocio dueño la aceptan (`require_tenant_object`), y el enlace para Seedance apunta al corte mismo en vez de copiarlo a `t/{tenant}/creative-refs/` (esa copia habría quedado para siempre bajo el candado). `referentes/reel_window_retention.py` borra cada corte 30 días después de escrito (su `LastModified`), **sin mirar filas de borradores**: lista toda la raíz `reel-windows/{tenant}/` de cada negocio, así que también caen los cortes huérfanos (parte borrada con su padre o pieza ya purgada). Descubrimiento por `admin_session`: todos los ids de negocio y nada más. Los cortes escritos bajo `t/{tenant}/generated/` antes del 2026-11-06 no se pueden borrar y no se intentan. Sin migración: ninguna restricción de la base de datos toca estas claves. Corre en `daily_chore` después de la purga de piezas, en su propio `try` (un fallo de una no frena la otra, con test), con `QUALIFY_PIECE_PURGE_EXECUTE`; `just piece-purge` la incluye, en prueba salvo `--execute`. `daily_chore` nunca llama a `reel_retention` (test).
- **Borrado rechazado por el bucket:** `R2ObjectStore.delete_keys` lanza `DeleteRefused` (sigue siendo `RuntimeError`) con los códigos; `ObjectLockedByBucketPolicy`, `ObjectLocked`, `AccessDenied` e `InvalidObjectState` cuentan como rechazo del bucket. Las dos purgas se **detienen en el primer rechazo** con una sola línea ERROR, no marcan nada y vuelven a intentar al día siguiente; las filas vencidas sin marcar (`source_purge_after <= now AND source_purged_at IS NULL`) son el registro de lo pendiente. Un error pasajero salta esa fila o borrador y sigue. Además, `reel_retention` vuelve a listar las carpetas antes de marcar: un borrado que responde OK pero deja objetos no se marca.
- **Sigue fuera:** borrar la fila a los 90 días (necesita DELETE para `qualify_reels_worker`, §6.3, sin firmar).

**Cómo verificar en producción si el bucket deja borrar (sin riesgo, solo lectura):**
1. Cloudflare → R2 → el bucket de producción → Settings → **Bucket lock rules**: anotar cada regla (prefijo, condición: antigüedad, fecha o indefinida). Si ninguna regla cubre `public/reel-analyses/` ni `t/`, los borrados pasan. Con Wrangler: `wrangler r2 bucket lock list <bucket>` (solo lee).
2. Buscar en los registros del `calendar-worker` y del `reels-worker` las líneas `R2 refused to delete` / `STOPPED`: la limpieza de medios del Brand Kit (`run_cleanup`, en el mismo `daily_chore`) borra en R2 cuando tiene pendientes, así que un rechazo podría aparecer ahí como `prefill media cleanup failed`. Que no aparezca nada no prueba que se pueda borrar: quizá no había nada pendiente.
3. `just reel-purge` (sin `--execute`) informa cuántas filas están vencidas sin borrar nada.
Si el candado rechaza borrados, la purga no se rompe: queda parada y avisando una vez por día hasta que se ajuste la regla (por ejemplo, que el candado no cubra `public/reel-analyses/` ni las ventanas, o que su retención sea menor a 30 días).

**Regla de ciclo de vida de R2 como alternativa [H]:** una regla «borrar a los 30 días de subido» sobre `public/reel-analyses/` haría lo mismo que `reel_retention` (la fecha se escribe justo antes de subir) y la purga en código solo marcaría filas ya vacías. No sirve para las ventanas: las reglas filtran por prefijo, no por nombre, y `t/{tenant}/generated/` es la pieza entera. Según la documentación de Cloudflare el candado tiene prioridad sobre el ciclo de vida, así que no resuelve un candado que rechace borrados; verificarlo antes de depender de ella.

## 3. Contrato con la UI (reflex-ui-engineer: UI-1 m-24921075, UI-2 m-24921076)

Desde un `@rx.event(background=True)` con `asyncio.to_thread` y el negocio sellado (ADR 43 §2.4, `discover_reels.py:313-357`). El `ReelSource` sale de la tarjeta guardada en el servidor (`_card`, `discover_reels.py:309-311`) o, desde R7, de `public_reels`; nunca de los argumentos del evento. **La pantalla nunca llama a `run_analysis`, ni baja ni sube nada.**

1. **Lista de «Ideas para tus reels»:** `analysis_badges(tenant_id, [(red, post_id), …])`, una sola consulta: «Aparece una persona» si algún plano tiene `people_presence` o `visible_faces` = `observed`; sin etiqueta si todo es `not_observed` o hay `unknown`; «Sin analizar» si no hay un `ok` (falló, pasó el tope o nadie lo pidió); «Mirando…» si está `queued` o `running`. El texto final es de UX.
2. **«Hacer uno parecido»** → `request_analysis(tenant_id, source)` → `/create?paso=2&analisis=<id>`. Con F3, lo normal es un reel **ya analizado**: `get_analysis` → `plan_from_analysis`, sin espera, directo a «Armando tu propuesta». Si está `queued` o `running`: «Estamos mirando este reel…» y `get_analysis_status` cada 3 s. Si el dueño sale, la fila es el estado: al volver, el mismo id.

`AnalysisStatus`: `status`, `stage`, `error_code`, `retryable`, `queued_for_s`, `queue_ahead` (filas `immediate` más viejas), `shots_found`, `covered_to_s`, `source_seconds`, `source_available`.

| Backend | En pantalla |
|---|---|
| `queued` | «Estamos mirando este reel…»; con `queue_ahead > 0`, «Hay otros reels antes que este» |
| `downloading` / `detecting` / `describing` | «Bajando el video» / «Mirando qué pasa» / «Revisando si aparece alguien» (UX §3a) |
| `done` → plan | «Armando tu propuesta» y después «Encontramos {n} partes», con **n del plan** y no los planos detectados (sugerencia UX pendiente) |
| `queued_for_s > 300` sin concesión | «Esto está tardando más de lo normal. Puedes armar tu video por partes sin el reel.» [Armar sin el reel], sin dejar de esperar (cubre el worker caído y el lunes cargado) |
| `source_unavailable`, `source_expired`, `no_video` | No pudimos bajar el video de este reel; a veces la red lo retira. Elige otro o arma tu video por partes sin él. [Elegir otro reel] [Armar sin el reel] |
| `source_too_large`, `source_unreadable`; `model_failed` tras 3 intentos; `model_output_cut` (respuesta cortada por `max_tokens`, sin reintento — m-24993025) | **No pudimos mirar este reel.** Arma tu video por partes sin él. [Armar sin el reel]. Sin «Intentar de nuevo»: reintentar lo decide el worker, y mientras tanto la pantalla dice «Seguimos mirando este reel» |
| `daily_limit` | **Falta en UX §4.** Propuesta: «Hoy ya miramos muchos reels. Mañana puedes pedir este; mientras, arma tu video por partes sin él.» El cupo es de toda la plataforma: no decir «tu negocio». [Armar sin el reel] |
| `ok` con 1 plano | **Este reel no cambia de escena.** Lo hacemos como una sola parte; si quieres, agrega otras. [Añadir parte] [Siguiente] |
| `source_available = false` | Las partes «Igual al original» ya no se pueden hacer con este reel; las hacemos «Nueva, inspirada en el original». |

Los fotogramas se leen por la puerta pública con una ruta de `Qualify/r2_media.py` limitada a `public/reel-analyses/*/frames/` y a sesión iniciada; a los 30 días ya no están y la parte muestra su marcador sin imagen. `tenant_mismatch` ya no viene del backend: la pantalla conserva su texto (`discover_reels.py:325`). Mirar un reel no toca el cupo («No usa tus videos del mes», UX P4) y nunca se muestra dinero.

## 4. ADR 42: qué suma cada R para el análisis, y la cadena mínima

Verificado: ni `main` ni `origin/main` tienen `public_reels`, `brand_reel_runs` ni `reels_worker` (`git grep`, sin resultados) **[V]**. El cliente de ScrapeCreators ya está en `packages/api` (`referentes/scrapecreators_client.py`, importado por `Qualify/reels_discovery.py:64`); el pipeline (`Qualify/reels_discovery.py`, 1.003 líneas) no **[V]**.

| R (anexo de ADR 42) | Qué debe sumar para el análisis | Depende de |
|---|---|---|
| R1 m-24854844 | Mudar el pipeline a `qualify_api.referentes.reels` con los lectores con tiempos de VE-04b; `ReelSource` se arma en el servicio, no en `Qualify/` | — |
| R2 | El test estático de `metered_get` cubre `referentes/reel_analysis*` sin excepciones (bajar del CDN no es el proveedor); la transcripción con tiempos pasa por la puerta como `reels_transcript` | R1 |
| R3 m-24854845 | En `public_reels`: `video_url` + `video_url_at` (V16) y `transcript_segments` JSONB con la versión del lector; `reel_id` = el `post_id` del análisis (código de Instagram, id de TikTok: `scrapecreators_client.py:624-632, 666-680`) para cruzar sin FK | — |
| R4 | Al final de `run()`, con las ideas guardadas y la corrida `ok`, llamar `analyze_run_ideas`; sumar su costo a `brand_reel_runs.cost_usd`; un fallo del análisis nunca cambia el estado de la corrida (ADR 42 §2.8) | R2, R3 |
| R5 | El tope de análisis por corrida y negocio (10) junto a los de créditos; una corrida `budget_stopped` o `check_failed` no analiza; el análisis no gasta créditos ni entra en 150/600 | R2, R3 |
| R8 m-24854855 | El bucle llama a `drain_once()` entre corridas y entre los análisis de una corrida (bajo demanda primero) y a `purge_reel_sources` una vez al día; usa el rol y la puerta de VE-03/VE-04a y suma sus GRANT; `mem_limit` medido con un análisis de 60 s | R4, R5 |
| R6, R7, R9–R17 | Nada obligatorio. R7 muestra las etiquetas de §3; R12/R13 reutilizan la puerta pública; R14 abre «Video por partes» (UI-1) | — |

**Cadena mínima para analizar al listar en producción:** R1 → R2 → R4 y R5 (R3 en paralelo desde el inicio) → R8; en paralelo, VE-03 → VE-04a → VE-04c (+ VE-02). Se juntan en la llamada de R4 a `analyze_run_ideas`, que hace el ticket que llegue segundo, con su test. La cola bajo demanda en producción solo necesita el servicio de R8.

**Comentarios para pegar en cada ticket de ADR 42:**
- **R1 (m-24854844):** «ADR 44 (Video por partes, m-24921048) analiza los reels al listar. Al mudar el pipeline a `qualify_api.referentes.reels`, incluir los lectores de transcripción con tiempos de VE-04b (m-24921057). El cliente ya está en `packages/api`.»
- **R2:** «ADR 44: el análisis de reels no llama a ScrapeCreators. El test estático de `metered_get` debe cubrir `referentes/reel_analysis*` sin excepciones, y la transcripción con tiempos (VE-04b) pasa por la puerta como `reels_transcript`.»
- **R3 (m-24854845):** «ADR 44: sumar a `public_reels` `video_url` + `video_url_at` (también los necesita el reproductor de R7) y `transcript_segments` JSONB. `reel_id` debe ser el mismo `post_id` de `public_reel_analyses` (VE-03, m-24921055), que se cruza sin FK.»
- **R4:** «ADR 44: al final de `run()`, con la corrida `ok`, llamar `analyze_run_ideas` (VE-04a, m-24921056) con el negocio que dispara y sumar su costo a `cost_usd`. Un fallo del análisis no cambia el estado de la corrida.»
- **R5:** «ADR 44: sumar el tope de análisis por corrida y negocio (10, `QUALIFY_REEL_ANALYSIS_PER_RUN`). Una corrida `budget_stopped` no analiza; los análisis no consumen créditos.»
- **R8 (m-24854855):** «ADR 44: el rol `qualify_reels_worker` y su puerta llegan con VE-03/VE-04a. El bucle suma `drain_once()` (bajo demanda primero) y la purga diaria de VE-12 (m-24921060). Fijar `mem_limit` con un análisis de 60 s medido.»

## 5. Riesgos

RN1 (el análisis en el único proceso de Reflex) **se retira**: F5 lo lleva a `reels-worker` (V4).

| # | Riesgo | Mitigación |
|---|---|---|
| RN2 | Fotogramas con rostros de terceros y copia del MP4 ajeno: puede chocar con los términos de Instagram y TikTok (lectura legal, no de ingeniería) **[H]** | F9 los borra a los 30 días (VE-12); el audio nunca se guarda; la ficha es texto. La lectura legal sigue pendiente |
| RN3 | La URL firmada dura ~24–33 h (`scrapecreators_client.py:550-554`) | `pending_video_url` se borra al bajar y nunca va a los registros (solo el host, `reel_reference.py:27-28`) |
| RN4 | El CDN de TikTok puede exigir cabeceras y responder 403 al servidor **[H]** | VE-05 baja 5 reels de TikTok; si fallan, quedan «Sin analizar» hasta tener una solución medida |
| RN5 | Langfuse (en la nube, `.env.example:131-138`) recibe texto en pantalla, transcripción ajena y lo que Haiku escribe de las personas | Imágenes como marcador **[V]**; instrucciones sin identidad ni atributos sensibles; test sobre la traza (VE-04c) |
| RN6 | Inyección desde el texto en pantalla o el habla del reel | Material delimitado como dato y validación de la respuesta en código (la herramienta de VE-04c no es estricta: la API rechaza su gramática por grande, 2026-11-05); creative reescribe la ficha, nunca la pega cruda en el prompt (VE-09) |
| RN7 | El análisis no cuenta en el cupo del dueño (UX P4) | Topes por corrida (10), bajo demanda (50/día) y de la flota (1.000 llamadas/día); `model_calls` ≤ 2 por fila |
| RN8 | Si el proceso muere entre la respuesta de Haiku y el commit, la reanudación paga otra vez | Se acepta (≤ USD 0,01); `model_calls` lo cuenta y lo frena |
| RN9 | R3 y VE-03 compiten por el número | La segunda se renumera en su rama; el rol lo crea solo VE-03, con IF NOT EXISTS |
| RN10 | `QUALIFY_CREATIVE_DISPATCHER` vale `inline` por defecto (`creative/queue_dispatch.py:19, 36-40`) y no aparece en `deploy/` **[V]** | platform-engineer lo verifica en `.env.prod` antes de la fase 1 |
| RN11 | **URL del CDN vencida cuando corre el worker** (cola lenta o worker caído) | La corrida analiza en el acto; con más de 20 h, `source_expired` sin pagar renovación (ADR 42 §2.14); la corrida siguiente o «Buscar reels nuevos» reencola con URL nueva |
| RN12 | **Cola bajo demanda contra corrida semanal:** el lunes a las 06:00 hay una corrida por marca activa; con 100 marcas, ≤ 800 análisis × ~30 s ≈ 6,7 h en serie **[H]** | Carril `immediate` primero y `drain_once()` entre análisis; aviso a los 5 min (§3); medir y subir `QUALIFY_REEL_ANALYSIS_CONCURRENCY` junto con el `mem_limit` |
| RN13 | **Costo semanal por analizar reels que nadie usará** | ≈ USD 0,0055 por reel (diseño §4.1) **[H]**: 8 marcas ≈ 64 por semana ≈ USD 0,35; 100 marcas ≈ USD 4,4 por semana, menos los reels compartidos. Se reabre si menos del 10 % de los análisis llega a una pieza en un mes: analizar solo las 3 primeras ideas |
| RN14 | **Purga compartida entre workers:** dos servicios sobre el mismo prefijo, o un `calendar-worker --tenant X` borrando datos de todos | Un solo dueño (`reels-worker`, VE-12); test de que `daily_chore` no la llama; la puerta pública solo la usan `referentes.reel_analysis*` |
| RN15 | Una fila `ok` falsa la usarían todos los negocios | `qualify_app` solo crea filas `queued` (GRANT por columnas, VE-03); los resultados los escribe solo el worker |
| RN16 | La fuente cuenta 30 días desde el análisis, no desde la elección: una idea de más de ~23 días ya no admite partes `edit` | Caen a `reference` con aviso (§3). Contar desde el último uso pediría una columna que revela uso: no |

## 6. Necesita decisión y lo que falta de tu lado

**Necesita decisión** (architect o Deivid; si se acepta lo propuesto, nada bloquea VE-03):
1. **Partir R8:** R8a = rol, servicio en el compose, bucle de la cola y purga diaria (depende de VE-03 y VE-04a); R8b = programar y atender corridas (R4, R5). Así el análisis bajo demanda llega a producción sin esperar toda la cadena. Cambia el anexo de ADR 42.
2. **Columna `lane`** (`immediate` / `weekly`), que no está en §13: sin ella, la cola bajo demanda espera detrás del lunes (RN12).
3. **DELETE para `qualify_reels_worker`**, para borrar la ficha a los 90 días (F9): §13 solo da SELECT, INSERT y UPDATE.
4. **Cupo bajo demanda de la plataforma** (50 por día) y no por negocio: por negocio hace falta una tabla con RLS de pedidos (quién pidió qué), que no está en el diseño.
5. **Costo bajo demanda sin negocio en el registro de consumo:** queda en la fila global. La alternativa, un tenant de plataforma, hoy no existe en el código.
6. **Textos para UX:** `daily_limit` y «tarda más de lo normal» (§3).

**Lo que falta de tu lado (backend, sin historia nueva):**
- **VE-21 (F1 = b):** una migración con la columna `video_seconds` en `creation_charges` (hoy cuenta `videos`, `0088_creation_charges.py:115-118`) y, casi seguro, la dimensión `video_seconds` en `creation_allocations`, cuyo CHECK hoy es `('creations','videos','previews')` (`0095_creation_packs.py:60`). La forma la fija creative en VE-21; la migración la escribe backend.
- Excluir las hijas (`parent_draft_id IS NOT NULL`) del Planificador (`planner/publishable.py`, `planner/draft_post_reader.py`), del correo de la mañana (`mail/final_summary.py`) y de «Tu semana» (`home/summary.py`), como pide creative (`historias-video-por-partes-creative.md:245`), antes de VE-10b.
