# Descubrir reels — los reels con más vistas de los referentes, solo del producto de la marca

`[IMPLEMENTADO 2026-10-15, sin commitear · sin prueba en vivo de punta a punta]`

En `/create`, la opción **«Descubrir reels»** muestra los reels con más vistas de los referentes de la marca en tres pestañas, **Esta semana**, **Este mes** y **90 días** (esta última, bajo demanda: ver el punto 6), con filtros por plataforma y por referente. Solo entran los reels **del producto de la marca**, los publique quien los publique: una hamburguesería que sigue a un creador de comida recibe sus hamburguesas, no su receta de pollo ni su reel de maquillaje (regla del fundador, 2026-10-15 noche: «si es hamburguesas que solo traiga hamburguesas»).

## 1. Cómo funciona

```
referentes de la marca ──► ScrapeCreators (1 lectura por cuenta, 30 días)
        │                              │
        │                              ▼
        │                    reels (solo videos)
        │                              │
        ▼                              ▼
  brief de la marca ──► Claude revisa cada reel contra el producto
                                       │
                                       ▼
                 ranking por vistas → Esta semana / Este mes
```

1. **De quién son los reels** (`reels_discovery.brand_referentes`):
   - Entran las cuentas que la marca tiene etiquetadas como **referente** (`brand_account_labels`), tanto las que encontró la búsqueda como las **añadidas a mano**.
   - Solo Instagram y TikTok, en el orden de influencia del operador, con un máximo de 12.
   - **Se excluye toda cuenta añadida a mano que la IA dijo que no encaja** (`card["fits"] == "no"`). Las de la búsqueda ya pasaron esa revisión.
   - Las etiquetadas como *competencia* o *detractor* no entran.
2. **Sus reels** (`scrapecreators_client.fetch_reels`): **una sola lectura por cuenta de los últimos 30 días** alimenta las dos pestañas, porque la semana son los días más recientes del mes.
3. **Solo el producto** (`qualify_api.referentes.reels_ai.review_reels`):
   - Que una cuenta encaje no garantiza que encaje cada video. Por eso los reels más vistos (32 por ventana, **más los 3 más vistos de cada cuenta en la ventana más amplia de la lectura** —el mes o los 90 días—, para que el filtro por referente encuentre algo aunque la cuenta no llegue al top de la marca) se revisan uno a uno con Claude: herramienta `revisar_reels`, modelo `claude-sonnet-5`, effort bajo, lotes de 20 en paralelo.
   - Claude lee el texto, el sonido y qué es la cuenta.
   - El brief de la marca es el mismo que usa la revisión de referentes: se reconstruye desde la semilla de su búsqueda (rubro en palabras del operador, nicho, hashtags y ubicación).
   - **Si no hay API key, la marca nunca hizo la búsqueda o la revisión falla:** los reels se muestran sin revisar y la pantalla avisa.
4. **Ranking:** por vistas (los likes desempatan), con 24 por pestaña **después de aplicar los filtros** (la lectura entrega todos los reels que pasaron la revisión).
5. **Memoria:**
   - El resultado se recuerda **6 horas por marca y por profundidad** (30 o 90 días), solo en memoria del proceso; «Actualizar» vuelve a leer.
   - **Los veredictos de Claude se recuerdan** por reel y brief mientras el proceso vive (`reels_discovery._verdicts`, máximo 5.000): la lectura de 90 días y «Actualizar» no vuelven a pagar por un reel ya juzgado. Si cambia lo que el modelo leería (texto, sonido, transcripción o el Brand Kit), se vuelve a preguntar.
   - Una transcripción de Instagram se descarga **una sola vez aunque las lecturas del mes y de 90 días corran a la vez**: la segunda espera a la primera.
   - Si el proceso se reinicia, la siguiente apertura vuelve a leer y a pagar.
   - Una caché en Postgres necesitaría una migración (`creator_profile_cache` solo admite `kind='snapshot'`). Queda pendiente.
6. **Filtros y 90 días** (m-24820844, 2026-10-20):
   - **Plataforma** (Todas / Instagram / TikTok, solo si los referentes están en las dos redes) y **referente** (uno concreto o todos). Recortan las tarjetas ya leídas en el estado de la vista: **no llaman al proveedor ni a Claude**, no gastan créditos.
   - **90 días** es una lectura aparte y más profunda: hasta 12 páginas por cuenta (el triple del mes). La pestaña **no lee nada al abrirse**: primero avisa que tiene un **cargo extra** y espera al botón «Leer». Por decisión del fundador (2026-10-20), no se muestran créditos ni dólares en pantalla. Orden de magnitud con 8 referentes: unos 60 créditos, como mucho ~140 (≈0,26 USD).
   - Queda en caché aparte: «Actualizar» en Semana o Mes vuelve a leer 30 días y **no** tira la lectura de 90 que ya se pagó. Volver a la pestaña de 90 días dentro de las 6 horas no cuesta nada.

**Cada tarjeta muestra:**
- la portada 9:16 con el puesto, la red, las vistas y la duración;
- la cuenta y la antigüedad («hace 3 días»);
- el texto, recortado a 2 líneas;
- likes, comentarios, **guardados** (solo TikTok), **% de interacción** sobre vistas y **vistas por día** desde la publicación (un reel de hace 25 días siempre acumula más que uno de ayer);
- el sonido y el motivo de la IA;
- «Ver reel», y «Replicar» (desactivado, «muy pronto»).

**La tarjeta «C» (2026-10-15, revisada el mismo día).** Cuadrícula de tarjetas de ≥16 rem.
- **Imagen 4:5**, con:
  - arriba a la izquierda, cuánto rinde el reel frente a **la mediana de las vistas de su propia cuenta** en el mes leído: «x3.2 sobre su media», en verde desde x2 y neutro entre x1,1 y x2;
  - la red y la duración.
  - Se usa la mediana y no la media para que un viral no hunda al resto de la cuenta. Hacen falta ≥3 reels con vistas. No cuesta nada: sale de los reels ya leídos.
- **«@cuenta» y la fecha**, y debajo, en grande, **«2.7M vistas · 92K/día · 15%»**: vistas, vistas por día desde la publicación e interacciones sobre vistas.
- **Etiquetas:** «Tu producto» cuando el reel es del producto exacto de la marca, y el **formato** (receta, reseña, detrás de escena, tutorial, producto, testimonio, humor, tendencia). Las da la misma llamada `revisar_reels` que filtra el rubro, sin llamada extra, con listas cerradas; «otro» no se muestra. El **gancho** se sigue pidiendo al modelo (para «Replicar») pero no se muestra.
- **Barra «Detalles»:** un acordeón. Al pulsarla, la tarjeta crece hacia abajo con:
  - me gusta, comentarios, guardados, duración y fecha;
  - el texto y el sonido;
  - el motivo de la IA;
  - la transcripción (bajo demanda);
  - «Abrir en …».
  - Sustituye al panel flotante que aparecía al pasar el ratón (descartado el mismo día).
- **«Replicar con mi marca»** (desactivado, «muy pronto»).
- La barra superior solo dice cuándo se leyó: «Actualizado hace 2 minutos» (el fundador quitó los conteos de referentes, reels y descartados el 2026-10-20). La edad la calcula el navegador (`rx.moment`), sin latido al servidor.

**El filtro, y cómo cambió el 2026-10-15.** El modelo devuelve una **afinidad** con tres valores:
- `producto`: el mismo producto o servicio que vende la marca, sea de quien sea (la hamburguesa de otro local, un creador que la reseña) → se muestra con la etiqueta «Tu producto»;
- `rubro`: el mismo nicho pero no el producto (una receta de pollo o una pizzería para una hamburguesería, maquillaje para un salón de uñas);
- `otro`: otro nicho, vida personal, humor o tendencia sin el producto, un sorteo, o **publicidad o promoción de otro negocio o producto**.

Tres versiones en el día:
1. **Mañana:** solo `encaja`, sin afinidad. Con una hamburguesería real (8 referentes, 153 reels del mes, 58 candidatos) descartó **47 de 58** reels, entre ellos recetas de pollo, pizzas o churros de sus referentes de comida.
2. **Tarde:** se añadió la afinidad y se decidió que `producto` y `rubro` encajan (el rubro como **nicho**). Pasaron 40 de 58. La eval de abajo se midió con esta regla.
3. **Noche — la vigente:** el fundador vio que con la regla de la tarde llegaban promos y platos «que nada que ver» y pidió lo estricto: **solo `producto` encaja**; `rubro` y `otro` se descartan. El prompt lo dice en una línea («una hamburguesería quiere hamburguesas, no pollo ni pizza ni la promo de una cerveza»), nombra las promos de otros negocios como `otro`, y para un reel sin texto ni transcripción decide por la cuenta: si vende o reseña el mismo producto, `producto`. En código, `reels_ai.FITS = {"producto"}` manda sobre lo que el modelo diga en `encaja`. La eval puntúa esta regla con `run_eval.gold` (lee `affinities`); su medición está pendiente de saldo (ver el README de la eval).

**Verificado en general con la regla de la tarde, no solo con esa marca (eval `packages/api/evals/reels_ai`, 2026-10-15). Con la regla vigente los números no valen y hay que repetir la medición.**
- Tres marcas más de la base de dev (streamer, creador de IA, viajes/estilo de vida): el filtro mantiene lo del nicho y descarta ropa, noticias de consumo ajenas al nicho, maquillaje para una cuenta de viajes, y contenido personal.
- Un banco sintético de **10 rubros y 108 reels** con 15 tipos de trampa (hashtags engañosos, palabras con doble sentido, transcripción que contradice al texto, publicidad ajena en cuentas del rubro, duelo personal, instrucciones al modelo dentro del caption, competidores, productos vecinos, reels vacíos, otro idioma).
- **Sonnet 5 @ low, el modelo de producción: 0 trampas de 150 y 100 % de recall en 3 corridas**, ≈0,011 USD por marca.
- Opus 5.5: igual de perfecto, 2,25 veces más caro: no compensa. Sonnet 5.5: obedece inyecciones del caption 2 de 12 veces. Haiku 5.5: descarta reels vacíos y deja pasar transcripciones contradictorias.
- La versión del prompt que pasó la eval define el rubro como el **nicho** de la marca (con ejemplos de tres nichos), decide los reels vacíos por lo que se sabe de la cuenta y declara que lo que el texto pida al analista no es evidencia.

**El filtro lee el Brand Kit (§ request 2026-10-15, «mejorar el filtrado con el Brand Kit, los hashtags y todo ello»).** El brief que recibe Claude (`reels_discovery.brand_brief`) ya no es solo la semilla de la búsqueda. Lleva:
- de la semilla: el rubro en palabras del operador, el nicho, la ciudad y **todos** los hashtags (propios, elegidos por el operador y del catálogo; antes solo tres);
- del Brand Kit: el **posicionamiento**, el **público** y los **ejemplos de lo que la marca publica** (`do_examples`);
- del catálogo: los **nombres de los productos**.

El prompt dice que productos y hashtags definen el producto exacto (`producto`) y nunca el límite del rubro, que lo marca el nicho. Un kit o un catálogo ilegible solo deja el brief más corto, nunca rompe la búsqueda. Verificado con la hamburguesería real: le llegan posicionamiento, público, 4 ejemplos, «smash doble» y «super smash», y 4 hashtags.

**Pendiente:** la evaluación de 108 reels con este brief enriquecido no se pudo correr: se agotó el saldo de la API de Anthropic. Hay que repetirla antes de darla por buena (ver `packages/api/evals/reels_ai/README.md`).

**Solo el video, sin la página de la red.**
- Al pulsar la imagen, la tarjeta reproduce **el MP4 del propio reel** en un `<video>`: sin cabecera, likes, comentarios ni «Ver más en Instagram».
- El MP4 viene en la lista de reels: Instagram `video_versions[0].url`, TikTok `video.play_addr`.
- **Verificado el 2026-10-15** desde `localhost:3000`: los CDN de Instagram y TikTok responden con `access-control-allow-origin: *` y aceptan rangos de bytes. Los dos videos se reprodujeron a 720×1280.
- El video se transmite desde el CDN de la red. **Qualify no lo descarga ni lo guarda.**
- **Caducidad:** la URL está firmada y caduca en ~24 h (TikTok) o ~33 h (Instagram).
  - La lectura se recuerda 6 h, así que normalmente sigue viva.
  - Si falla, el `<video>` dispara `error` y la tarjeta pasa sola al reproductor oficial de la red (abajo).
- **Riesgo:** mostrar el MP4 de un tercero sin su interfaz oficial se aleja más de las condiciones de las plataformas que su embed. Es aceptable como referencia interna; no para una superficie pública.

**Ver el reel dentro de Qualify con el reproductor oficial (respaldo).**
- Pulsar la portada la **sustituye, dentro de la misma tarjeta**, por el **reproductor oficial** de la red, en un iframe del mismo tamaño 9:16. No hay diálogo. Las URLs son:
  - Instagram: `https://www.instagram.com/reel/<code>/embed/`
  - TikTok: `https://www.tiktok.com/player/v1/<id>`
- El video lo transmite Instagram o TikTok; Qualify no descarga ni guarda nada.
- Solo se reproduce uno a la vez: abrir otro desmonta el anterior.
- «Cerrar video» vuelve a mostrar la portada.

**Transcripción: antes del filtro, con tope (decisión final del 2026-10-15).**
- Cada lectura transcribe **los candidatos** (los 32 más vistos de cada pestaña, los únicos que pueden salir en pantalla) **antes** de la revisión de rubro (`reels_discovery.transcribe`).
  - TikTok: los subtítulos del propio video, **gratis**; solo si el video los tiene (si tiene voz).
  - Instagram: el speech-to-text del proveedor, **1 crédito** por reel (0 desde su caché o sin voz), con un **tope de 40 por lectura**, en orden de vistas.
- Una transcripción no cambia: se recuerda por reel mientras el proceso vive, y «Actualizar» no la vuelve a pagar. El botón **«Ver transcripción»** de la tarjeta usa la misma memoria (`transcript_for`).
- Costo típico de la primera lectura de una marca: 15–40 créditos (≈0,02–0,08 USD); las siguientes, casi cero.
- **Historia del mismo día:** a media tarde se cambió a «solo bajo demanda» para ahorrar créditos, y el filtro empeoró de inmediato: sin oír el reel, juzga por el texto, y el texto de un reel suele ser flojo o engañoso (la evaluación mide justo eso en las trampas `transcript_wins` y `transcript_rescues`). Se restauró el mismo día. Ahorrar ~0,05 USD por marca no compensa un filtro peor.

Lo que sigue describe cómo se obtiene cada transcripción:
- **Instagram:** `/v2/instagram/media/transcript?url=<reel>&cache_max_age=30`.
  - Es el speech-to-text del proveedor: texto sin tiempos, **1 crédito** por reel de hasta 120 s.
  - **0 créditos** si lo responde la caché del proveedor o si el video no tiene voz.
  - Los videos de más de 120 s no se transcriben, porque costarían 10 créditos por minuto.
- **TikTok:** los **subtítulos nativos** del video (`video.cla_info.caption_infos[].url`, WEBVTT en el CDN de TikTok). Vienen en la misma lista de reels y **no cuestan nada**. Solo existen si el video tiene voz. Se elige el español primero.
- **El filtro y la transcripción:** cuando un reel ya tiene transcripción, Claude recibe además «lo que se dice» (hasta 700 caracteres), con la instrucción de que es la prueba más fuerte. Si lo que se habla es de otro producto o nicho, no encaja aunque el texto o los hashtags lo parezcan; si es del producto, encaja aunque el texto sea un chiste. Los subtítulos de TikTok pueden empezar con un BOM; se quita antes de leerlos.
- **Verificado el 2026-10-15** desde `localhost:3000`, con dos reels reales: los dos reproductores cargan dentro de la página.
  - Instagram solo manda `X-Frame-Options: DENY` a una petición que no es un iframe (por ejemplo, curl). A un iframe de navegador (`Sec-Fetch-Dest: iframe`) le responde sin restricción.
  - TikTok no manda ninguna cabecera que impida el iframe.
  - En producción, Caddy no añade ninguna CSP que lo bloquee.
- **Alternativas descartadas:**
  - poner el MP4 del CDN en un `<video>`: la URL caduca en ~24–33 h y es contenido ajeno servido desde nuestra página;
  - pasarlo por nuestro backend: es descargarlo igual.
- Sigue el enlace «Abrir en Instagram/TikTok».

**El filtro, en concreto:**
- Es una llamada a **Claude Sonnet 5** (`claude-sonnet-5`, effort `low`) con la herramienta forzada **`revisar_reels`**, cuya salida es `{id, afinidad, encaja, razon, formato, gancho}` por reel.
- Claude lee la transcripción, el texto, el sonido y qué es la cuenta.
- Código: `qualify_api.referentes.reels_ai.review_reels`.
- Mismo modelo y esfuerzo que la revisión de referentes (`revisar_cuentas`), que se eligió con la eval de `packages/api/evals/referentes_ai`.

**Portadas:** las URLs de los CDN caducan (portada de IG ~4 días, de TikTok ~1 día). El backend las descarga una vez y sirve su copia (`avatar_proxy.resolve_reel_cover`, ruta `/avatar/reel/<red>/<id>`). Va bajo `/avatar` a propósito: Caddy en producción ya manda `/avatar/*` al backend.

**Código:**
- [Qualify/reels_discovery.py](../Qualify/reels_discovery.py): el pipeline.
- [Qualify/discover_reels.py](../Qualify/discover_reels.py): estado y vista.
- [packages/api/src/qualify_api/referentes/reels_ai.py](../packages/api/src/qualify_api/referentes/reels_ai.py): la revisión de rubro.
- `fetch_reels` en [Qualify/scrapecreators_client.py](../Qualify/scrapecreators_client.py).

**Tests:** `Qualify/test_reels_discovery.py` y `packages/api/tests/test_referentes_reels_ai.py`. Además, el lector se probó contra 6 respuestas reales: 12/12 reels de IG y 9/10 videos de TikTok (el que falta es un carrusel de fotos, descartado a propósito).

## 2. Endpoints y coste

Medido en vivo el 2026-10-15 con 6 llamadas sobre una cuenta pública de restaurante (6 créditos). [DOC] = [docs.scrapecreators.com](https://docs.scrapecreators.com) (OpenAPI en `/openapi.json`).

| Red | Endpoint | Paginación | Notas |
|---|---|---|---|
| Instagram | `/v1/instagram/user/reels` | `paging_info.max_id` + `paging_info.more_available`, **12 por página** | Solo reels; cada item va bajo `items[].media` |
| TikTok | `/v3/tiktok/profile/videos?sort_by=latest&include_pinned=false` | `max_cursor` + `has_more`, **10 por página** | **`sort_by=popular` no sirve:** devuelve toda la historia de la cuenta ordenada por **likes** |

- **Ninguno de los dos filtra por fecha.** Se pagina de más nuevo a más antiguo y se para cuando el **último** item de una página es anterior a la ventana; el primero puede ser un fijado. Máximo 4 páginas.
- **Coste:** 1 crédito por página.
  - Con ~10 referentes, **15–35 créditos por lectura completa**.
  - Con una lectura diaria, entre **0,45 y 2 USD por marca al mes**: Freelance a 1,88 USD por 1.000 créditos, Business a 0,99 USD por 1.000. Los créditos no caducan.
  - Saldo el 2026-10-15: **3.681 créditos**.
- **Rate limits:** el proveedor dice que no impone ninguno; recomienda no pasar de 500 peticiones concurrentes.

## 3. Qué da ScrapeCreators por cada reel (para análisis y para replicar)

Prefijos de ruta:
- **IG-L** = `items[].media.` de `/v1/instagram/user/reels`
- **IG-D** = `data.xdt_shortcode_media.` de `/v1/instagram/post`
- **TT** = `aweme_list[].` de `/v3/tiktok/profile/videos`; en `/v2/tiktok/video`, el mismo subárbol bajo `aweme_detail.`

| Campo | Instagram | TikTok | Uso |
|---|---|---|---|
| Vistas | IG-L `play_count` · IG-D `video_play_count` (solo IG, sin Facebook) | `statistics.play_count` | análisis |
| Likes / comentarios | `like_count`, `comment_count` | `statistics.digg_count`, `comment_count` | análisis |
| Compartidos | **No existe** | `statistics.share_count` (+ whatsapp, download, repost) | análisis |
| Guardados | **No existe** | `statistics.collect_count` | análisis |
| Contadores ocultos | `like_and_view_counts_disabled` | — | análisis |
| Fecha | `taken_at` (unix) | `create_time` (unix) | análisis |
| Duración | `video_duration` (**s**) | `video.duration` (**ms**) | análisis / réplica |
| Caption y hashtags | `caption.text` (hashtags por regex) | `desc` + `text_extra[].hashtag_name` | análisis / réplica |
| Sonido | `clips_metadata.music_info.music_asset_info` u `original_sound_info`; `is_trending_in_clips` | `music.{title,author,is_original_sound,user_count}` | análisis / réplica |
| Colaboración / pagado | `coauthor_producers`, `is_paid_partnership` | `is_paid_partnership`, `branded_content_accounts` | análisis |
| Etiqueta de IA | `gen_ai_detection_method` | `aigc_info` | análisis |
| **MP4** | IG-L `video_versions[0].url` · IG-D `video_url` | `video.download_no_watermark_addr` / `play_addr` | réplica |
| Audio aparte | `progressive_download_url` (firmada) | `music.play_url` (mp3) | réplica |
| Miniatura | `image_versions2.candidates[0].url` | `video.cover` / `origin_cover` | análisis / réplica |
| Transcripción | Endpoint aparte, 1 crédito, **texto sin tiempos** | **Gratis y con tiempos (WEBVTT)**: `video.cla_info.caption_infos` en la lista, o `/v2/tiktok/video?get_transcript=true` (solo si el video tiene voz: 6 de 10) | réplica |
| Comentarios (texto) | `/v2/instagram/post/comments` (1 crédito por página) | `/v1/tiktok/video/comments` (1 crédito por página) | análisis |
| Ubicación | casi nunca viene | no verificado | — |

**Las URLs de media caducan:**
- MP4 de IG en ~33 h y de TikTok en ~24 h;
- portadas de IG en ~4 días y de TikTok en ~23 h;
- el VTT de TikTok en 30 días.

**Para replicar un reel hay que descargarlo a R2 en cuanto se elige.**

**Lo que el proveedor no da:** planos, ritmo, texto en pantalla, ni guardados y compartidos de Instagram (no los da ninguna API pública de terceros). Planos y ritmo saldrían de nuestra cascada: ffmpeg (keyframes y escenas) + whisper (transcripción con tiempos, igual para IG y TikTok) + VLM + el spike `packages/models/hooks/` (gancho de los primeros 3 s).

**La documentación se contradice con las respuestas reales:**
- `/v1/instagram/user/reels` dice que no devuelve captions, pero sí las devuelve;
- el audio del mismo reel difiere entre la lista y el detalle.

Hace falta un parser defensivo.

## 4. Siguiente paso: «Replicar» (sin implementar)

Al abrir un reel para replicarlo, estas lecturas se harían bajo demanda:
- **IG:** detalle (1 crédito, 0 con `cache_max_age=1d`) + transcripción (1) + una página de comentarios (1).
- **TikTok:** detalle con `get_transcript=true` (1) + comentarios (1).

Luego, en los dos casos:
1. descargar el MP4 a R2;
2. pasarlo por la cascada propia (transcripción con tiempos, escenas, gancho);
3. guardar el payload crudo (ADR 18) para poder re-parsear sin volver a pagar.

**Riesgo legal:** guardar MP4 de terceros es una cuestión de derechos. Usarlos solo como referencia interna de análisis, nunca republicarlos (no es un análisis legal).

**Otros pendientes:**
- caché en Postgres de la lista por (red, handle), compartida entre tenants porque es dato público, como el pool de creadores de la migración 0036;
- guardar cada lectura de métricas con su `fetched_at`, para poder calcular la velocidad;
- prueba de punta a punta con una marca real que tenga referentes.
