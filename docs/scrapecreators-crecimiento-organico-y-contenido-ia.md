# Scrape Creators: crecimiento orgánico y contenido generado con IA (TikTok / Instagram)

**Estado:** completo, 2026-10-01 (gtm-specialist). 10 llamadas reales a la API (10 créditos), documentación del vendor y de alternativas leídas el mismo día.

**Pregunta:** qué da la API de Scrape Creators (`api.scrapecreators.com`, docs en `docs.scrapecreators.com`) para, sobre un **creador** o un **vídeo** de TikTok e Instagram, (1) medir o estimar **crecimiento orgánico** y (2) saber si el contenido está **etiquetado como generado con IA**.

**Convención de evidencia.** Cada afirmación lleva una de estas marcas:

- `[DOC]` — leído en la documentación pública del vendor (URL + fecha).
- `[LIVE 2026-10-01]` — verificado en una llamada real contra la API con la clave del repo, hoy. Solo se imprimieron claves y campos relevantes, nunca payloads completos ni la clave.
- `[REPO]` — ya medido antes por este repo y documentado en código/docs (`Qualify/scrapecreators_client.py`, `Qualify/creator_discovery.py`, `docs/ui-brandkit-wizard.md`).
- `[INFERIDO]` — hipótesis razonable sin verificación directa. No construir sobre ello sin medir.

## 0. Lo que el repo ya sabe (punto de partida) `[REPO]`

- Cliente: `Qualify/scrapecreators_client.py`. Endpoints usados: `/v1/tiktok/profile`, `/v1/instagram/profile` (`GET ?handle=`, header `x-api-key`), `/v2/instagram/user/posts` (`items[]`, `taken_at`, `like_count`, `comment_count`, `play_count`; cursor `next_max_id`/`more_available`) y `/v3/tiktok/profile/videos` (`aweme_list[]`, `create_time`, `statistics.{digg_count,comment_count,play_count}`; cursor `max_cursor`/`has_more`). 1 crédito por página.
- Discovery: `Qualify/creator_discovery.py`. Endpoints: `/v1/tiktok/search/keyword` (`query=`), `/v1/tiktok/search/hashtag` (`hashtag=`), `/v1/tiktok/search/users` (vacío siempre, medido 2026-09-11), `/v2/instagram/reels/search` (indexado por Google, 404 = sin resultados), `/v1/google/search`. Ninguno filtra por nicho/ciudad/banda de seguidores.
- `cache_max_age` (p. ej. `"30d"`) lo aceptan ambos endpoints de perfil; una respuesta de caché devuelve `credits_charged: 0` (medido 2026-09-11, `creator_discovery._read_profile`).
- El propio código documenta la carencia que motiva este doc: `profile_metrics` dice explícitamente "What is NOT here, on purpose: any growth/trend figure. A follower growth needs two reads apart in time and this flow keeps exactly one snapshot with no history".
- **No hay ningún payload crudo del vendor en el repo**: `Qualify/fixtures/discovery_raw/` está vacío/gitignored, `discovery_profiles.json` guarda solo hechos normalizados (`followers`, `bio`, `total_likes`...). `grep -ri "aigc|ai_generated|made_with_ai|is_ai"` sobre fixtures y código del vendor: **0 resultados**. Los fixtures de `packages/scraper/tests/fixtures/{tiktok,instagram}/` son sintéticos (12-15 claves), no dumps reales de hydration JSON.
- Único sitio del repo donde sí aparece una etiqueta de IA: el corpus de docs de Meta (`reference/meta-instagram-platform/instagram-platform/changelog.md`, entrada **22 de junio de 2026, "AI Info Label"**): campo `is_ai_generated` en `GET /{ig_media_id}?fields=is_ai_generated` y parámetro `is_ai_generated=true` al crear contenedor en `POST /{ig_user_id}/media`. Es Graph API **first-party** (medios propios de la cuenta conectada), no earned media de terceros — ver §4.

## 1. Endpoints relevantes y campos exactos

Catálogo completo del vendor leído en `https://docs.scrapecreators.com/` el 2026-10-01 `[DOC]`. Solo se listan aquí los endpoints que tocan las dos preguntas; el catálogo entero (comentarios, transcripción, live, followers, canciones...) está en esa URL.

### 1.1 TikTok

| Endpoint | Parámetros | Créditos | Campos relevantes (nombre exacto, tipo) | Fuente |
|---|---|---|---|---|
| `GET /v1/tiktok/profile` | `handle` o `user_id`; `cache_max_age` ∈ {`1d`,`3d`,`7d`,`14d`,`30d`} | 1 (0 si responde la caché) | `stats.followerCount`, `stats.followingCount`, `stats.heart`/`heartCount` (likes totales), `stats.videoCount`, `stats.diggCount`, `stats.friendCount` (int). `user.createTime` (unix, fecha de creación de la cuenta), `user.uniqueIdModifyTime`, `user.nickNameModifyTime`, `user.verified`, `user.ttSeller`, `user.isADVirtual`, `user.isOrganization`. Top-level: `success`, `credits_remaining`, `credits_charged`, `itemList`. **Sin histórico ni series temporales** — la doc solo describe contadores actuales. | https://docs.scrapecreators.com/v1/tiktok/profile `[DOC]` + `[REPO]` (shape ya pineado en `scrapecreators_client._normalize_tiktok`) |
| `GET /v3/tiktok/profile/videos` | `handle` o `user_id`; `sort_by` ∈ {`latest`,`popular`}; `max_cursor`; `region` (por defecto GB); `trim` (bool) | 1 por página (~30 vídeos) | `aweme_list[]` con el **mismo objeto vídeo que `/v2/tiktok/video`** (abajo): `create_time`, `statistics.*`, `author.follower_count`, `aigc_info`, `c2pa_info`, `creation_info`, `is_ad`, `is_top` (fijado). Paginación `has_more` / `max_cursor` / `min_cursor`. | https://docs.scrapecreators.com/v3/tiktok/profile/videos `[DOC]`; ya usado por `fetch_recent_posts` `[REPO]` |
| `GET /v2/tiktok/video` | `url` (del vídeo); `trim` | 1 | Objeto `aweme_detail`: `aweme_id`, `create_time` (unix), `region`, `desc`, `desc_language`. **Estadísticas** `statistics.{play_count, digg_count, comment_count, share_count, download_count, collect_count, forward_count, repost_count, whatsapp_share_count}` (int). **Autor** `author.{uid, unique_id, follower_count, following_count, aweme_count, total_favorited, region, ins_id, youtube_channel_id, verification_type}`. **IA** `aigc_info.{aigc_label_type (int, 0 = sin etiqueta), created_by_ai (bool)}`; `c2pa_info.{is_tiktok, is_capcut (bool), total_src, total_vid, total_img, total_audio, total_err (int), first_src, last_src, first_aigc_src, last_aigc_src (str), upload_dur}`; `creation_info.creation_used_functions` (array, p. ej. `["select_music","high_quality_upload"]`); `video.ai_dynamic_cover` (portada dinámica generada por TikTok, NO indica que el vídeo sea IA); `content_model.standard_biz.tts_voice_info` (voz TTS); `tts_voice_ids`, `reference_tts_voice_ids`, `reference_voice_filter_ids`; `mask_infos`, `green_screen_materials`, `cc_template_info`. **Música** `music.{id, title, author, is_original_sound, is_original, is_pgc, is_commerce_music, source_platform}`, `added_sound_music_info`. **Comercial** `is_ads`, `commerce_info.branded_content_type`, `branded_content_accounts`. `video.cla_info.caption_infos[].is_auto_generated` (subtítulos automáticos, no IA de contenido). | https://docs.scrapecreators.com/v2/tiktok/video `[DOC]` |
| `GET /v1/tiktok/get-trending-feed` | `region` (sin filtro por creador, sin cursor) | 1 | Feed de tendencias de TikTok: **12 vídeos** en forma recortada (`aweme_id, author, create_time, create_time_utc, desc, statistics, music, is_ad, is_paid_partnership, region, url, video, commerce_info, poi_data...`). **Sin `aigc_info`, sin rank/score/posición, sin paginación.** Es "lo que TikTok empuja ahora", no un indicador por vídeo ni una serie. | https://docs.scrapecreators.com/ (catálogo) `[DOC]`; forma `[LIVE 2026-10-01]` llamada 10 (`region=US`, `credits_charged: 1`) |
| `GET /v1/tiktok/user/audience` | `handle` | 1 | Demografía de audiencia (país/edad/género), no crecimiento. | catálogo `[DOC]`; forma no inspeccionada |
| `GET /v1/tiktok/user/followers`, `/following` | `handle`, cursor | 1 por página | Lista de cuentas; sirve para **muestrear** seguidores, no para medir crecimiento (no hay fecha de follow). | catálogo `[DOC]` |

### 1.2 Instagram

| Endpoint | Parámetros | Créditos | Campos relevantes | Fuente |
|---|---|---|---|---|
| `GET /v1/instagram/profile` | `handle`; `cache_max_age` ∈ {`1d`..`30d`}; `trim` | 1 (0 si caché) | `data.user.edge_followed_by.count`, `edge_follow.count`, `edge_owner_to_timeline_media.count` (int). `edge_owner_to_timeline_media.edges[].node.{taken_at_timestamp, video_view_count, edge_liked_by.count, edge_media_to_comment.count, is_video, shortcode}` (~12 posts recientes). `edge_related_profiles.edges[]`. `is_business_account`, `is_professional_account`, `category_name`, `bio_links[]`. **Sin histórico.** | https://docs.scrapecreators.com/v1/instagram/profile `[DOC]` + `[REPO]` |
| `GET /v2/instagram/user/posts` | `handle`; `next_max_id`; `trim` | 1 por página (~12) | `items[].{taken_at, like_count, comment_count, play_count / ig_play_count, caption.text, code, media_type, product_type}`; `more_available`, `next_max_id`. | ya usado por `fetch_recent_posts` `[REPO]`; https://docs.scrapecreators.com/v2/instagram/user/posts `[DOC]` |
| `GET /v1/instagram/user/reels` | `handle`; cursor; `trim` | 1 por página | Solo reels del usuario; mismo objeto `items[]` que arriba `[INFERIDO]`. | catálogo `[DOC]` |
| `GET /v1/instagram/post` | `url`; `region`; `trim`; `include_play_count` (default true); `download_media` (+10 créditos si hay media); `cache_max_age` | 1 (+10 con descarga) | `data.xdt_shortcode_media.{id, shortcode, is_video, created_at (ISO), taken_at_timestamp (unix), video_play_count, video_view_count, video_duration}`; `edge_media_preview_like.count`, `edge_media_to_parent_comment.count`; `owner.{id, username, is_verified, edge_followed_by.count, edge_owner_to_timeline_media.count}`; `clips_music_attribution_info.{artist_name, song_name, uses_original_audio, audio_id}`; `has_audio`; `product_type`; `accessibility_caption` (texto alt generado por Meta); `is_ad`, `is_affiliate`, `is_paid_partnership`, `like_and_view_counts_disabled`. **La doc NO lista ningún campo `is_ai_generated` / `ai_label` / `gen_ai`.** | https://docs.scrapecreators.com/v1/instagram/post `[DOC]` |
| `GET /v1/instagram/reels/trending` | — | 1 | Lista de reels en tendencia ahora; no por creador ni serie. | catálogo `[DOC]`; forma no inspeccionada |
| `GET /v1/instagram/profile/post-count` | `handle` | 1 `[INFERIDO]` | Solo el número de posts — lectura barata para detectar "¿publicó algo nuevo?" sin traer el perfil entero. | catálogo `[DOC]` |

### 1.3 Transversal

- **Rate limits:** la doc declara "No Rate Limits" `[DOC]`; el repo ya corre 6 llamadas en paralelo sin incidencias (`creator_discovery.PARALLEL_CALLS`) `[REPO]`.
- **Caché del vendor:** `cache_max_age` ∈ {`1d`,`3d`,`7d`,`14d`,`30d`}; una respuesta servida de caché devuelve `credits_charged: 0`. Documentado en los endpoints de perfil (ambas redes) y en `/v1/instagram/post`. **Para `/v3/tiktok/profile/videos` y `/v2/instagram/user/posts` la doc NO lista `cache_max_age`** `[DOC]` — ver §1.4 para la medida en vivo.
- **Uso:** `GET /v1/account/get-api-usage` devuelve el histórico de peticiones de la cuenta (no datos de plataformas) `[DOC]`.

## 2. Crecimiento orgánico: directo, construible, inexistente

### 2.1 Veredicto

**Scrape Creators no vende histórico.** Ninguno de los endpoints de perfil o de vídeo devuelve series temporales de seguidores, views, likes o comentarios; la doc lo dice implícitamente (solo contadores) y las llamadas reales lo confirman: `/v1/tiktok/profile` devuelve `stats` y `statsV2` (misma foto, una en int y otra en str), `/v1/instagram/profile` devuelve `edge_followed_by.count`. Tampoco hay ningún endpoint "growth", "history" o "trend" por creador en el catálogo `[DOC]`; los dos endpoints "trending" (`/v1/tiktok/get-trending-feed`, `/v1/instagram/reels/trending`) son **feeds** de lo que la plataforma empuja ahora, no un indicador por vídeo ni por creador.

Lo que sí hay es la materia prima de una serie: **cada vídeo lleva su fecha de publicación y sus contadores actuales**, y el perfil lleva la fecha de creación de la cuenta. Con eso se construyen dos cosas distintas, y conviene no confundirlas:

| Señal | ¿Directa? | Cómo | Evidencia |
|---|---|---|---|
| **Foto actual** de seguidores / likes totales / nº vídeos | Sí | `/v1/tiktok/profile` → `stats.{followerCount, heartCount, videoCount}`; `/v1/instagram/profile` → `edge_followed_by.count`, `edge_owner_to_timeline_media.count` | `[LIVE]` llamada 8: `followerCount 6903`, `heartCount 150100`, `videoCount 409` |
| **Antigüedad de la cuenta** (TikTok) | Sí | `/v1/tiktok/profile` → `user.createTime` (unix) | `[LIVE]` llamada 8: `1760293707` = 2025-10-12 → cuenta de ~1 año |
| **Antigüedad de la cuenta** (Instagram) | No | El perfil no trae fecha de creación. Proxy: `taken_at` del post más antiguo (paginar hasta `more_available=false`, 1 crédito/página de 12) `[INFERIDO]` | — |
| **Ritmo de publicación** (vídeos/semana, cadencia) | Sí, por lectura de lista | `/v3/tiktok/profile/videos` → `create_time`/`create_time_utc`; `/v2/instagram/user/posts` → `taken_at`. Ya implementado en `fetch_recent_posts` | `[REPO]` + `[LIVE]` llamadas 3/7 |
| **Rendimiento por vídeo a fecha de lectura** (views/likes/comments/shares/saves) | Sí (foto) | TikTok `statistics.{play_count, digg_count, comment_count, share_count, collect_count, repost_count, download_count}`; IG `items[].{play_count, like_count, comment_count}` (IG no expone shares/saves de terceros) | `[LIVE]` |
| **Velocidad de un vídeo** (views por hora desde publicación) | Construible en una sola lectura | `statistics.play_count / (now - create_time)`. Es la métrica "más barata" de velocidad: 1 crédito por 10-30 vídeos, sin histórico. Sesgo: los fijados (`is_top=1`) son viejos y van primero | `[LIVE]` llamada 3: los 3 fijados tenían 576K/831K views de 2025 delante de un vídeo de 2026-09-28 con 863 |
| **Crecimiento de seguidores** (Δ/semana, Δ/mes) | **No existe. Hay que construirlo** | Polling del perfil y persistir `(handle, fetched_at, followerCount)`. Ver §2.2 | `[REPO]` `profile_metrics` ya declara que no lo inventa |
| **Curva de views de un vídeo** (24h/48h/7d) | **No existe. Hay que construirlo** | Polling de la lista de vídeos y persistir `(aweme_id, fetched_at, play_count, ...)`. Ver §2.2 | `[LIVE]` llamada 4: lecturas en vivo, sin caché, 1 crédito/página |
| **"Trending" por vídeo o creador** | No | Los feeds trending no son consultables por handle/vídeo. Alternativa: cruzar los ids del feed con los vídeos de los creadores seguidos (`[INFERIDO]`, no medido) | `[DOC]` |
| **Crecimiento orgánico vs pagado** | No directo | TikTok: `is_ads`, `commerce_info.branded_content_type`, `branded_content_accounts`, `is_paid_partnership`; IG: `is_ad`, `is_paid_partnership`. Permiten **excluir** contenido pagado de la serie, no detectar seguidores comprados ni promoción de posts (TikTok "Promote" no deja rastro público) | `[LIVE]` campos observados; interpretación `[INFERIDO]` |

### 2.2 Cómo se construye la serie temporal (lo que Qualify tendría que hacer)

Dos series, con costes y cadencias distintas:

**A. Serie de perfil (seguidores, likes totales, nº posts).** 1 lectura de perfil por creador y por tick. `cache_max_age` SÍ se honra en los dos endpoints de perfil (`credits_charged: 0`, medido 2026-09-11 `[REPO]`), lo que tiene dos consecuencias opuestas:

- Si otro cliente del vendor (o el propio Qualify en otro flujo, p. ej. discovery con `30d`) ya leyó ese handle dentro de la ventana, la lectura es gratis **pero la foto es vieja** (hasta 30 días). Para una serie hay que pedir con `cache_max_age=1d` (el mínimo documentado) o sin el parámetro, y entonces casi siempre cuesta 1 crédito.
- Cadencia realista: **diaria** = 30 créditos/creador/mes; **semanal** = 4-5 créditos/creador/mes. Para 1.000 creadores seguidos: 30K créditos/mes diario (~$30 al precio Business de $0,99/1K, ~$56 al Freelance de $1,88/1K, §5) o 5K semanal.

Campos a persistir por tick: TikTok `stats.followerCount, followingCount, heartCount, videoCount` + `user.createTime` (una vez); IG `edge_followed_by.count, edge_follow.count, edge_owner_to_timeline_media.count`. Clave natural `(platform, handle_or_id, fetched_at)`. Derivadas: Δ absoluto y relativo por 7/30 días, seguidores ganados por vídeo publicado en la ventana, y seguidores/antigüedad como tasa media de vida (TikTok).

**B. Serie de vídeo (curva de views/likes/comments).** 1 lectura de la lista de vídeos por creador y por tick (1 crédito por página; **sin caché**, §3.3). Cada tick da la foto de los 10-30 vídeos más recientes a la vez, así que la serie de *todos* los vídeos recientes de un creador cuesta lo mismo que la de uno.

- Cadencia realista para curvas útiles: cada 6-12 h durante las primeras 72 h de cada vídeo nuevo, luego diaria una semana, luego parar. Un creador que publica a diario y se lee 2×/día = 60 créditos/mes; 1.000 creadores = 60K créditos/mes (~$60 Business).
- `sort_by=latest` pone los fijados primero (3 en la muestra) — hay que leer `is_top` y no usar `trim` (lo elimina, §3.3).
- Campos a persistir por `(platform, post_id, fetched_at)`: TikTok `statistics.{play_count, digg_count, comment_count, share_count, collect_count, repost_count}`; IG `{play_count, like_count, comment_count}` + `like_and_view_counts_disabled` (si es `true`, el `like_count` no es real).

**C. Detección barata de "hay vídeo nuevo"** (para no pagar B cuando no hace falta): TikTok `stats.videoCount` del perfil (gratis si cacheado, pero entonces viejo) o IG `/v1/instagram/profile/post-count` (1 crédito `[INFERIDO]`). En la práctica no ahorra: la lectura de detección cuesta lo mismo que una página de B.

### 2.3 Lo que NO se puede obtener de este vendor, a ningún precio

- Histórico de seguidores anterior al primer tick de Qualify (no hay backfill; sólo la antigüedad de cuenta en TikTok).
- Curva de views de un vídeo anterior al primer tick (la lectura inicial de un vídeo de 2025 da solo su total actual).
- Quién sigue a quién con fecha (`/v1/tiktok/user/followers` lista cuentas sin timestamp de follow `[DOC]`).
- Impresiones, alcance, retención, tráfico por fuente (For You vs perfil), seguidores netos por vídeo — todo eso es **analytics de primera parte** (TikTok Creator Center, IG Insights) y solo entra por cuentas conectadas (Parte 4 / Meta Graph API `insights`), nunca por scraping de terceros.
- Si un post se promocionó (TikTok Promote / IG Boost) sin marca de partnership: no deja rastro público.

## 3. Contenido con IA: qué expone el vendor

### 3.1 TikTok — SÍ, y es la etiqueta oficial de la plataforma `[LIVE 2026-10-01]`

Llamada real: `GET /v1/tiktok/search/keyword?query=ai generated video sora&region=US` → HTTP 200, `credits_charged: 1`, 30 vídeos (`search_item_list[].aweme_info`), 1.072 rutas de hoja distintas por vídeo. Los campos de IA viajan **dentro del objeto vídeo de TikTok** (el mismo `aweme` que devuelven `/v2/tiktok/video` y `/v3/tiktok/profile/videos` según la doc, §1.1), es decir, el vendor no los fabrica: son el payload de la app de TikTok pasado tal cual.

| Campo (ruta exacta en el objeto vídeo) | Tipo | Valores observados en 30 vídeos | Lectura |
|---|---|---|---|
| `aigc_info.aigc_label_type` | int | `2` ×26, `1` ×1, `0` ×3 | **La etiqueta "AI-generated content" de TikTok.** `0` = sin etiqueta. `1` y `2` = etiquetado. La semántica exacta de 1 vs 2 NO está documentada por el vendor ni por TikTok; `[INFERIDO]` por consistencia con `moderation_aigc_info`: `2` = etiqueta aplicada por el creador o por detección de TikTok y confirmada; `1` = etiqueta presente sin paso de moderación. Tratar como booleano `!= 0` hasta tener más muestras. |
| `aigc_info.created_by_ai` | bool | `true` en los 27 con `label_type != 0`, `false` en los 3 con `0` | Booleano redundante con el anterior, correlación 100% en la muestra. **Es el campo a leer.** |
| `moderation_aigc_info.moderation_aigc_label_type` | int | `1` ×25 (todos con `aigc_label_type = 2`), ausente/`None` en los demás | Etiqueta del lado de moderación de TikTok (detección propia). Presente solo cuando `aigc_label_type = 2`. |
| `moderation_aigc_info.{moderation_user_label_status, creator_guidance_status, moderation_overlabel_warning}` | int | todos `0` | Estado del flujo de etiquetado del creador; sin variación en la muestra. |
| `c2pa_info.first_aigc_src` / `first_src` / `dedup_src` / `last_aigc_src` | str | `"Sora"` ×2, `"TikTok"` ×1, `""` resto | **Procedencia C2PA (Content Credentials)**: nombre de la herramienta generadora leído de los metadatos C2PA del fichero. Cuando existe, es la evidencia más fuerte (dice *qué* modelo). Vacío en la mayoría: los creadores re-codifican y pierden la firma. |
| `c2pa_info.aigc_src` | str | `"unknown, meta_contain_c2pa"` en el vídeo Sora | Resumen textual de la fuente C2PA. |
| `c2pa_info.c2pa_extra_data` | str (JSON) | `{"aigc_percentage_type":0|1|2, "has_invisible_watermark":2, "generate_server_task_id":[]}` | `aigc_percentage_type` (`2` en los dos vídeos Sora, `1` en tres, `0` resto) — proporción de contenido IA según TikTok `[INFERIDO]`; `has_invisible_watermark` = marca de agua invisible detectada. |
| `c2pa_info.{is_capcut, is_tiktok, total_src, total_vid, total_img, total_audio, total_err}` | bool/int | `is_capcut`/`is_tiktok` `false`; `total_src` `1` en los 3 con `first_src` | Conteo de fuentes C2PA. |
| `creation_info.creation_used_functions` | list[str] | p. ej. `["high_quality_upload","text","select_music"]`, `["editor_pro",...]`, `["effect",...]`, `[]` | Herramientas de edición de TikTok usadas. **No** indica IA por sí mismo (ningún valor `ai_*` en la muestra). |
| `video.ai_dynamic_cover`, `video.ai_dynamic_cover_bak` | obj | presente en todos | Portada dinámica generada por TikTok para cualquier vídeo. **Falso positivo si se usa como señal de IA.** |
| `item_allow_ai_remix`, `ai_remix_info.has_entrance`, `creator_ai_comment.*` | int/bool | `2`, `false`, `false` | Funciones de producto de TikTok (remix con IA, comentarios IA); no son etiqueta de contenido. |
| `label_top` | obj (imagen) | presente en los 30, mismo `uri` | Es el logo/marca de agua de TikTok, no la insignia de IA. |
| `music.is_original_sound`, `music.title` | bool/str | `"original sound - sora.ai.hub"` etc. | Sin señal de "música IA" como tal; TikTok no expone un flag de audio generado. |

Vídeos de referencia para re-verificar (ids reales): `7599140663636053279` (`@aibizarrely`, `aigc_label_type=2`, `first_aigc_src="Sora"`, 3,39M reproducciones), `7690702161633660182` (`@sora.ai.hub`, `=2`, sin C2PA), `7691760393160641822` (`@x_man677`, `=0`, vídeo que *habla* de IA pero no está etiquetado — útil como negativo).

Conclusiones verificadas:

1. **La etiqueta oficial de TikTok se obtiene con 0 trabajo extra**: viaja en los mismos endpoints que ya paga el repo (`/v3/tiktok/profile/videos` para el histórico de un creador, búsquedas por keyword/hashtag para discovery). No hace falta `/v2/tiktok/video` salvo para un vídeo suelto por URL.
2. **Tres niveles de confianza, de más a menos:** `c2pa_info.first_aigc_src` no vacío (herramienta identificada) > `aigc_info.created_by_ai = true` (etiqueta de TikTok, sea del creador o por detección) > inferencia por hashtags/descripción (`#aigenerated`, `#sora2`) — esta última es la que el repo ya podría hacer con `text_extra`, pero es ruidosa (el negativo `@x_man677` lleva "ai" en el texto).
3. El campo **no distingue "creador declaró" de "TikTok detectó"** de forma documentada; `moderation_aigc_info.moderation_aigc_label_type = 1` acompaña a los `aigc_label_type = 2` y `[INFERIDO]` apunta a detección/confirmación de moderación.
4. `trim=true` en `/v3/tiktok/profile/videos` **elimina** `aigc_info`, `c2pa_info`, `creation_info` y `moderation_aigc_info` (medido, §3.3). Para leer la etiqueta hay que pedir la respuesta completa.

### 3.2 Instagram — SÍ, pero solo en los endpoints con forma de API móvil `[LIVE 2026-10-01]`

Tres llamadas:

| Llamada | Endpoint | `credits_charged` | ¿Campo de IA? |
|---|---|---|---|
| 5 | `GET /v2/instagram/reels/search?query=ai generated sora video` | 1 (8 reels) | **No.** Objeto reel plano: `caption, clips_music_attribution_info, comment_count, like_count, taken_at, owner{id,username,full_name,is_verified,profile_pic_url}, shortcode, url, video_url, is_ad, is_paid_partnership, product_type`. Ninguna clave con `ai`/`label`. |
| 6 | `GET /v1/instagram/post?url=https://www.instagram.com/reel/DPTp8UPESUN/` (reel de `@longliveai` cuyo caption dice "100% AI-generated") | 1 | **No.** Forma web-GraphQL `data.xdt_shortcode_media` con 29 claves: `clips_metadata.{audio_type, original_sound_info, originality_info}`, `clips_music_attribution_info`, `created_at`, `taken_at_timestamp`, `video_play_count` (124.075), `edge_media_preview_like.count`, `edge_media_to_parent_comment.count`, `owner`, `is_ad`, `is_paid_partnership`, `like_and_view_counts_disabled`, `coauthor_producers`... **Cero claves de IA.** Además, `owner` trae solo `{id, username, is_verified, full_name, profile_pic_url}` — el `owner.edge_followed_by.count` que la doc promete (§1.2) **no vino**; y `video_view_count` vino `null` (el dato está en `video_play_count`). |
| 7 | `GET /v2/instagram/user/posts?handle=longliveai` | 1 (12 ítems) | **SÍ: `items[].ai_label_info`**, presente solo en los ítems etiquetados (3 de 12). |

Forma exacta de `items[].ai_label_info` (observada en 3 ítems; ausente, no `null`, en los otros 9):

```json
{
  "subtitle_text": "AI content",
  "gen_ai_detection_method": "SELF_DISCLOSURE_FLOW",   // o "AI_EDITED"
  "attribution_label_text": null,
  "is_self_disclosed": false,
  "can_edit_self_disclosure": false,
  "should_read_attribution_label": false,
  "content_sheet_sections": []
}
```

| Campo | Tipo | Observado | Lectura |
|---|---|---|---|
| `ai_label_info` (presencia) | obj | 3/12 | **La etiqueta "AI info" de Instagram.** Ausente = sin etiqueta. Leer con `"ai_label_info" in item`, no `item["ai_label_info"] is None`. |
| `ai_label_info.gen_ai_detection_method` | str enum | `SELF_DISCLOSURE_FLOW` ×2 (reels `Dd4PG4CiY6S`, `Dd16ujDCZIt`), `AI_EDITED` ×1 (carrusel `Dd3_DykFmGK`) | **Distingue origen de la etiqueta**: `SELF_DISCLOSURE_FLOW` = el creador la marcó al publicar; `AI_EDITED` = Meta la detectó como editada con IA `[INFERIDO]` por el nombre; Meta documenta públicamente que etiqueta por autodeclaración y por "industry-standard indicators" (C2PA/IPTC) — ver §4. |
| `ai_label_info.subtitle_text` | str | `"AI content"` | Texto de la etiqueta visible. |
| `ai_label_info.is_self_disclosed` | bool | `false` incluso con `SELF_DISCLOSURE_FLOW` | Contradictorio a primera vista; `[INFERIDO]` es un flag relativo al viewer (si *yo* la autodeclaré), no al autor. No usar. |
| `items[].media_type` / `product_type` | int / str | `2`/`clips` (reel), `8`/`carousel_container` | La etiqueta aparece en ambos tipos. |
| `items[].play_count`, `ig_play_count` | int | iguales entre sí | Reproducciones del reel; `null` en carruseles. |
| `items[].like_and_view_counts_disabled` | bool | `true` en 1 ítem | Cuando es `true`, `like_count` es `3` (ocultado), no real — filtrar antes de agregar. |
| `items[].is_meta_ai_invocation_blocked_by_author`, `meta_ai_suggested_prompts` | bool/list | `false`, `[]` | Funciones de producto de Meta AI; no es etiqueta de contenido. |
| `items[].clips_metadata.originality_info`, `mashup_info.original_media` | obj | `null` | Originalidad/remix, no IA. |
| `items[].media_overlay_info` | obj | `null` | Overlays de aviso (contenido sensible); no IA en la muestra. |

**Llamada 9 — `GET /v1/instagram/user/reels?handle=longliveai`** (1 crédito, 12 reels, envoltorio `items[].media`, paginación `paging_info.{max_id, more_available}`): lleva la señal en **otra ruta y en todos los ítems**, con negativo explícito:

```
items[].media.gen_ai_detection_method = {"detection_method": "NONE"}                  // 6 de 12
items[].media.gen_ai_detection_method = {"detection_method": "SELF_DISCLOSURE_FLOW"}  // 6 de 12
```

Consistencia cruzada: los reels `Dd4PG4CiY6S` y `Dd16ujDCZIt` salen `SELF_DISCLOSURE_FLOW` en ambos endpoints (`/user/posts` vía `ai_label_info`, `/user/reels` vía `media.gen_ai_detection_method`). El objeto `ai_label_info` **no** viene en `/user/reels` (grep: 0 ocurrencias), y `gen_ai_detection_method` como clave propia **no** viene en `/user/posts` (solo dentro de `ai_label_info`). Son dos serializaciones de Instagram de la misma etiqueta.

Conclusiones verificadas:

1. **En Instagram la etiqueta de IA se lee en dos endpoints, ambos con forma "móvil"**: `/v2/instagram/user/posts` → `items[].ai_label_info` (presente solo si etiquetado; `gen_ai_detection_method` dentro) y `/v1/instagram/user/reels` → `items[].media.gen_ai_detection_method.detection_method` (siempre presente; `NONE` = sin etiqueta). **No** se lee por URL de post (`/v1/instagram/post`, forma web-GraphQL, 0 ocurrencias), ni en la búsqueda de reels (0), ni `[INFERIDO]` en `/v1/instagram/profile` (forma web `edge_*`). Para saber si *un* reel concreto lleva etiqueta hay que listar los posts/reels del autor y buscarlo por `code`.
2. **Instagram sí distingue autodeclaración de detección** (`SELF_DISCLOSURE_FLOW` vs `AI_EDITED`; cabe esperar más valores del enum para la detección por C2PA/IPTC que Meta documenta públicamente — no observados en 24 ítems); TikTok no lo distingue de forma documentada (§3.1).
3. El repo ya paga exactamente `/v2/instagram/user/posts` en `fetch_recent_posts` → leer `ai_label_info` cuesta **0 créditos extra**. Si en el futuro se cambia a `/user/reels`, leer `media.gen_ai_detection_method.detection_method != "NONE"`.

### 3.3 Medidas sobre `/v3/tiktok/profile/videos` `[LIVE 2026-10-01]`

Tres llamadas sobre `handle=sora.ai.hub&sort_by=latest` (cuenta de 409 vídeos, 6.910 seguidores, casi todo IA):

| Llamada | Parámetros | `credits_charged` | Ítems | Observación |
|---|---|---|---|---|
| 2 | `trim=true&cache_max_age=7d` | 1 | 10 | **`trim=true` ELIMINA `aigc_info`, `c2pa_info`, `creation_info`, `moderation_aigc_info` e `is_top`.** El ítem recortado solo conserva `author, aweme_id, create_time, create_time_utc, desc, desc_language, is_ad, is_eligible_for_commission, is_paid_partnership, region, shop_product_url, statistics, url, video`. **No usar `trim` si se quiere la etiqueta de IA.** |
| 3 | `cache_max_age=7d` (sin trim) | 1 | 10 | 9/10 con `aigc_label_type=2, created_by_ai=true`; 1/10 con `0`. Ningún `first_aigc_src` en esta cuenta (re-codifica). `is_top=1` en los 3 primeros (fijados, fechas 2025-10/2026-05 delante de 2026-09) — confirma la regla del repo "la página 1 lleva fijados primero". |
| 4 | idéntica a la 3, ~30 s después | **1** | 10 | **`cache_max_age` NO se honra en este endpoint** (la doc tampoco lo lista; §1.1). Cada lectura de la lista de vídeos es en vivo y cuesta 1 crédito por página, siempre. `play_count` idéntico entre 3 y 4; entre 2 y 3 (unos segundos) un vídeo pasó de 147.458 a 147.459 → lecturas en vivo, no caché. |

Nota de tamaño de página: el repo asume "~30 vídeos por página" (`scrapecreators_client._MAX_POST_PAGES`); para esta cuenta fueron **10** por página con y sin `trim`. `[INFERIDO]` el tamaño depende de la cuenta/región; presupuestar con 10, no con 30, para la ventana de 7 días.

Campos de autor que viajan en cada ítem (foto del momento, no serie): `author.{follower_count, following_count, aweme_count, total_favorited}` — `author.create_time` vino `0` (no usable; la fecha de creación de cuenta está en `/v1/tiktok/profile` → `user.createTime`, §1.1).

## 4. Alternativas si Scrape Creators no cubre algo

Scrape Creators cubre la etiqueta de IA en ambas redes (§3) y la materia prima de las series (§2). Lo que **no** cubre es el histórico, y ahí la alternativa no es "otro scraper" sino o bien un vendor que ya lleva años acumulando fotos diarias, o bien construirlo.

### 4.1 Para la etiqueta de IA

| Fuente | TikTok | Instagram | Evidencia |
|---|---|---|---|
| **Scrape Creators** | `aigc_info.created_by_ai`, `aigc_label_type`, `c2pa_info.first_aigc_src` (en búsquedas, lista de vídeos y vídeo por URL) | `ai_label_info.gen_ai_detection_method` (`/v2/instagram/user/posts`), `media.gen_ai_detection_method.detection_method` (`/v1/instagram/user/reels`) | `[LIVE 2026-10-01]` §3 |
| **EnsembleData** | `[INFERIDO]` sí: sus endpoints TikTok devuelven el objeto `aweme` crudo de la app, y un resultado de búsqueda muestra `aigc_info.{aigc_label_type, created_by_ai}` en su respuesta de ejemplo; el actor de Apify (`apify.com/ensembledata/tiktok-api`) no lo muestra en su muestra `POST_INFO`. **Sin verificar en llamada real** (sin clave). | Desconocido | https://ensembledata.com/apis/docs (2026-10-01; las páginas por endpoint responden 422 sin sesión) |
| **Data365** | Desconocido — docs tras registro; su modelo de datos es normalizado (no el `aweme` crudo), así que es probable que la etiqueta se pierda `[INFERIDO]` | Desconocido | https://data365.co (2026-10-01, `/docs` responde 404) |
| **JSON crudo de la plataforma vía `packages/scraper` (Zyte)** | El hydration JSON web de TikTok (`__UNIVERSAL_DATA_FOR_REHYDRATION__` → `webapp.video-detail.itemInfo.itemStruct`) es la serialización **web**, distinta de la de app. `[INFERIDO]` lleva `aigcLabelType` en camelCase (la web muestra la insignia "AI-generated", así que el dato llega al cliente), pero el parser actual (`parsers/tiktok.py`) no lo lee y los fixtures del repo son sintéticos sin ese campo. Verificable gratis con una página real. | La web de Instagram (`xdt_shortcode_media`, la misma forma que `/v1/instagram/post`) **no** lo lleva (§3.2, 0 ocurrencias). La forma móvil sí. Con Zyte habría que simular el cliente móvil, que no es lo que hace `parsers/instagram.py`. | `[REPO]` + `[LIVE]` |
| **Meta Graph API (cuentas conectadas, Parte 4)** | — | `GET /{ig_media_id}?fields=is_ai_generated` y `is_ai_generated=true` al publicar (changelog 2026-06-22). **Solo medios propios** de la cuenta conectada, no earned media. | `reference/meta-instagram-platform/instagram-platform/changelog.md` `[REPO]` |
| **Inferencia propia (cascada multimodal, Fase 1/3)** | Hashtags (`#aigenerated`, `#sora2`), descripción, nombre del sonido ("original sound - sora.ai.hub"), y a futuro un detector visual. Ruidoso: el negativo `@x_man677` habla de IA sin estar etiquetado. Útil como **complemento** cuando la etiqueta falta (TikTok obliga a etiquetar solo lo "realista"; mucho contenido IA no realista no lleva etiqueta). | Igual | `[LIVE]` §3.1 |

Contexto de plataforma `[DOC]`: TikTok etiqueta automáticamente por C2PA Content Credentials desde mayo de 2024 y obliga al creador a etiquetar IA realista (https://newsroom.tiktok.com/advancing-ai-transparency-and-literacy); Meta pasó de "Made with AI" a "AI info" en julio de 2024 tras falsos positivos por ediciones menores, y etiqueta por autodeclaración y por indicadores C2PA/IPTC (`digitalSourceType = trainedAlgorithmicMedia`) (https://the-decoder.com/meta-responds-to-criticism-changes-made-with-ai-label-to-ai-info/). Implicación: **`AI_EDITED` en Instagram incluye retoques menores**; no equivale a "vídeo generado".

### 4.2 Para el histórico de crecimiento

| Fuente | Qué da | Precio (2026-10-01) | Evidencia |
|---|---|---|---|
| **CreatorDB API** — `GET /tiktok/performance-history?uniqueId=&pastDayRange=1..365` | **Un punto por día hasta 365 días atrás**: `totalFollowers`, `totalFollowing`, `totalContents`, `videosPerformanceRecent.{likes,comments,views,shares}.{all,avg,median,min,max}`, `engagement`. Es exactamente la serie que Scrape Creators no vende, ya acumulada (30M+ creadores). Instagram: perfil sí; histórico IG no confirmado en la doc leída. | Pro $79/mes = 3.160 créditos ($0,025/cr); Premium $249 = 12.450 ($0,020); Enterprise $749 = 74.900 ($0,010); PAYG $0,04/cr. Perfil 2 cr, performance TikTok 1,5 cr. Self-serve. | https://docs.creatordb.app/api-reference/tiktok/get-performance-history.md · https://creatordb.app/pricing `[DOC]` — **sin llamada real** |
| **Social Blade** | Histórico diario público de seguidores (años) por web; Business API prepago. | Personal $59,99–$1.439,99/año; API: precio opaco (prepago) | https://outlierkit.com/resources/social-blade-pricing/ `[DOC]` agregador |
| **HypeAuditor / Modash** | Gráficas de crecimiento dentro de la plataforma de influencer marketing; API sales-gated. | HypeAuditor desde $299/mes anual; Modash desde $199/mes anual | agregadores `[DOC]` (creator-hero.com, capterra) — opaco |
| **NapoleonCat, ContentStudio, Postfast** | Histórico de **cuentas conectadas** (first-party); ContentStudio documenta que la API de TikTok no da histórico y que ellos lo acumulan desde 2024-01-31. Confirma el límite: nadie tiene backfill sin haberlo acumulado. | — | https://docs.contentstudio.io/article/1016-tiktok-analytics `[DOC]` |
| **Construirlo sobre Scrape Creators** | §2.2: serie de perfil 1 cr/creador/tick; serie de vídeo 1 cr/página/tick, sin caché. Empieza en cero el día que se enciende. | §5 | `[LIVE]` |

### 4.3 Para "trending"

Ni Scrape Creators (feeds de 12 ítems sin rank, §1.1) ni EnsembleData/Data365 (no documentan trending por vídeo) dan "este vídeo está en tendencia". Lo más cercano construible: **velocidad** (views/hora desde `create_time`, una lectura) y **aceleración** (dos lecturas, §2.2 B). Es un derivado de la serie de vídeo, no un dato a comprar.

## 5. Costo estimado en créditos

Precios de Scrape Creators `[DOC]` https://scrapecreators.com/ (2026-10-01): Free 100 créditos (+ hasta 7.000 de bonus); Freelance $47 = 25.000 créditos (**$1,88/1K**); Business $497 = 500.000 (**$0,99/1K**); Enterprise 1M+ a medida. Pay-as-you-go, los créditos no caducan, sin suscripción. Caché del vendor = 0 créditos (solo donde se honra: perfiles e `/v1/instagram/post`; **no** en la lista de vídeos de TikTok, §3.3). Saldo de la clave del repo tras esta investigación: 4.374.

| Señal | Créditos por creador | Créditos por vídeo suelto | Notas |
|---|---|---|---|
| Etiqueta IA de los N vídeos recientes (TikTok) | 1 por página de 10-30 vídeos (`/v3/tiktok/profile/videos`, sin `trim`) | 1 (`/v2/tiktok/video?url=`) | Ya pagado por `fetch_recent_posts` → **+0** |
| Etiqueta IA de los N posts recientes (IG) | 1 por página de 12 (`/v2/instagram/user/posts` o `/user/reels`) | **No existe por URL**; hay que listar el autor: 1 por página hasta encontrar el `code` | Ya pagado por `fetch_recent_posts` → **+0** |
| Etiqueta IA en discovery (búsquedas TikTok) | 0 extra: viaja en `search_item_list[].aweme_info` | — | Las búsquedas IG no la llevan |
| Foto actual de seguidores + antigüedad (TikTok) / seguidores (IG) | 1 (0 si caché ≤30d) | — | Ya pagado por `fetch_profile` → **+0** |
| Ritmo de publicación y rendimiento por vídeo a fecha de lectura | 1-3 (páginas de la lista) | — | Ya pagado → **+0** |
| Velocidad de un vídeo (views/h) | 0 extra (derivado de lo anterior) | 1 | — |
| **Serie de seguidores** (construida) | **1 por tick** (pedir `cache_max_age=1d` o nada; una caché de 30d da una foto vieja) | — | Diario: 30/mes; semanal: 4-5/mes |
| **Curva de views por vídeo** (construida) | **1 por página y tick, sin caché** — una lectura cubre todos los vídeos recientes | 1 por tick | 2×/día durante 72 h + diaria 4 días ≈ 10 lecturas por vídeo nuevo; para un creador que publica a diario ≈ 60/mes |
| Alternativa comprada: histórico de 365 días de seguidores (CreatorDB) | 1,5 créditos CreatorDB (~$0,015-0,06 según plan) una vez | — | Otro vendor, otra clave; backfill instantáneo |

Escenarios (Business, $0,99/1K): 1.000 creadores con serie de perfil diaria + curva de vídeo 2×/día ≈ 30K + 60K = **90K créditos/mes ≈ $90/mes**; con serie semanal + curva solo las primeras 72 h de cada vídeo nuevo (3 vídeos/semana/creador) ≈ 5K + 1.000×3×4×6 = 77K ≈ $76/mes. Al precio Freelance ($1,88/1K) ≈ ×1,9. La etiqueta de IA y la foto actual no añaden coste sobre lo que el repo ya paga.

## 6. Recomendación para Qualify

Recomendación de vendor y de dónde cae cada pieza en el mapa de fases; el requisito de producto (qué mostrar, a quién) lo fijan `sales-consultant` / `product-owner` sobre esta evidencia.

1. **Etiqueta de IA: leerla ya, de Scrape Creators, coste cero.** Las dos redes la exponen en endpoints que `scrapecreators_client.fetch_recent_posts` ya paga. Campos a normalizar en el shape común de post (`{takenAt, likes, comments, views}` → añadir `aiLabel`):
   - TikTok: `aigc_info.created_by_ai` (bool) + `aigc_info.aigc_label_type` (int) + `c2pa_info.first_aigc_src` (str, herramienta cuando existe). **Nunca pedir `trim=true`.**
   - Instagram: `"ai_label_info" in item` → `ai_label_info.gen_ai_detection_method` (`SELF_DISCLOSURE_FLOW` | `AI_EDITED` | ...) en `/v2/instagram/user/posts`; o `media.gen_ai_detection_method.detection_method != "NONE"` si se migra a `/v1/instagram/user/reels`.
   - Persistir **con provenance** (regla transversal del repo): `ai_label_source = "tiktok:aigc_info" | "instagram:ai_label_info"`, `ai_label_method` (el enum crudo) y la fecha de lectura. La etiqueta es un hecho de plataforma, no una inferencia de Qualify — conviene que el dato lo diga.
   - Fase: cabe en la **Fase 1** actual como campo de ingesta (es un atributo del post, como `is_ad`) y alimenta la **Fase 3** (señal tipada "contenido IA" por creador: % de posts etiquetados en los últimos N) y la **Fase 4** (scoring de creadores: un creador 90% IA es otra categoría de proveedor). No requiere modelo ni GPU.
   - Qué NO hacer: tratar `AI_EDITED` como "generado" (incluye retoques), usar `video.ai_dynamic_cover` o `label_top` como señal (falsos positivos), o depender de hashtags como fuente primaria (ruido; solo complemento). **"Buy, don't build" aplica**: la etiqueta de plataforma es más fiable que cualquier detector propio y es gratis; un detector visual propio solo tiene sentido en Fase 3 para el contenido IA *no etiquetado*.

2. **Crecimiento orgánico: no se compra a Scrape Creators; se construye sobre él, o se compra el backfill a CreatorDB.**
   - **Ahora (Fase 1/2):** persistir cada lectura de perfil y de lista de vídeos que el repo ya hace, con `fetched_at`, en lugar del snapshot sobrescribible `brand_connect_profile.json`. Es la única forma de que la serie exista cuando se quiera mostrar; cada día sin persistir es un día de histórico perdido, y el propio `profile_metrics` ya declara que no inventa crecimiento. Esto es un cambio de persistencia (Parte 3 / tablas `ingestion.*`), no de vendor.
   - **Cadencia recomendada** para cuentas seguidas (referentes / brand kit): perfil **diario** sin caché (1 cr), lista de vídeos **2×/día durante 72 h tras un vídeo nuevo** y diaria después (1 cr/página, sin caché) — §2.2 y §5. Para cuentas de discovery (miles): solo perfil con `cache_max_age=30d` como hoy; sin serie.
   - **Si el producto necesita histórico desde el día uno** (p. ej. mostrar "crecimiento últimos 90 días" de un referente recién añadido), la opción es **CreatorDB `performance-history`** (365 días diarios, ~1,5 créditos ≈ $0,015-0,06/creador, self-serve) como segunda fuente — pero antes hay que verificar con una clave real la cobertura de creadores hispanohablantes pequeños y si existe el equivalente para Instagram; la doc leída solo prueba TikTok. Marcar como `[PENDIENTE DE VERIFICAR]` en `docs/alternativas-fase1.md`.
   - **Trending:** no comprar. Derivar velocidad/aceleración de la serie de vídeo (Fase 3, señal tipada con provenance `detector_version`).

3. **Correcciones al repo derivadas de las medidas** (para quien toque `scrapecreators_client.py`; este doc no modifica código):
   - `_MAX_POST_PAGES = 3` asume ~30 vídeos/página en TikTok; se midieron **10** (`sora.ai.hub`). Para la ventana de 7 días de una cuenta que publica a diario, 3 páginas pueden quedarse cortas.
   - `cache_max_age` no se honra en `/v3/tiktok/profile/videos` (medido) — la nota del módulo que dice "1 credit per page" es correcta y además es *siempre* 1; no planificar ahorros por caché ahí.
   - `/v1/instagram/post` no devuelve `owner.edge_followed_by.count` aunque la doc lo liste; `video_view_count` viene `null` (usar `video_play_count`).
   - `like_and_view_counts_disabled = true` en IG hace que `like_count` sea un placeholder (3); hay que excluir esos posts de la media de likes de `profile_metrics`.

4. **Lo que sigue sin fuente a ningún precio** (para que nadie lo prometa): seguidores netos por vídeo, impresiones/alcance/retención, origen del tráfico, si un post fue promocionado sin etiqueta — solo con cuentas conectadas (Parte 4, Insights de primera parte).

---

### Resumen de verificación (llamadas reales, 2026-10-01, 10 créditos)

| # | Endpoint | Para qué | Resultado clave |
|---|---|---|---|
| 1 | `/v1/tiktok/search/keyword` | forma del `aweme` + etiqueta IA | `aigc_info`, `moderation_aigc_info`, `c2pa_info` presentes; 27/30 etiquetados |
| 2 | `/v3/tiktok/profile/videos` `trim=true` | ¿sobrevive la etiqueta? | **No**: `trim` la elimina |
| 3 | `/v3/tiktok/profile/videos` | etiqueta en lista de creador; fijados | 9/10 etiquetados; `is_top` primero; 10/página |
| 4 | idem repetida | ¿caché? | **No se honra `cache_max_age`**: 1 crédito otra vez |
| 5 | `/v2/instagram/reels/search` | ¿etiqueta en búsqueda IG? | No |
| 6 | `/v1/instagram/post` | ¿etiqueta por URL? | No (forma web); `owner` sin seguidores |
| 7 | `/v2/instagram/user/posts` | ¿etiqueta en lista? | **Sí**: `items[].ai_label_info` (3/12) |
| 8 | `/v1/tiktok/profile` | foto + antigüedad | `stats`/`statsV2`, `user.createTime` = 2025-10-12 |
| 9 | `/v1/instagram/user/reels` | ¿etiqueta en reels? | **Sí**: `media.gen_ai_detection_method.detection_method` en todos (6 `NONE`, 6 `SELF_DISCLOSURE_FLOW`) |
| 10 | `/v1/tiktok/get-trending-feed` | ¿qué es "trending"? | 12 vídeos recortados, sin rank, sin `aigc_info`, sin cursor |

Payloads crudos guardados fuera del repo (scratchpad de sesión), no en `Qualify/fixtures/`. Si se quiere un fixture de regresión para el parser de la etiqueta, los ids de §3.1/§3.2 permiten regenerarlo por 2 créditos.
