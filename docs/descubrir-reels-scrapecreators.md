# Descubrir reels — los reels con más vistas de los referentes, solo del producto de la marca

`[IMPLEMENTADO 2026-10-15 · en main · rediseño firmado el 2026-10-25 en ADR 42]`

> **Este documento describe la versión actual, que se reemplaza.** El costo no está controlado: abrir la pantalla lee y paga; la memoria es del proceso y cada merge despliega (15–54 por día), así que casi toda apertura es en frío; sin brief se paga y no se muestra nada; si Claude falla, cada reintento vuelve a pagar la lectura entera; nadie lee `credits_remaining`. El diseño firmado — «Ideas para tus reels», corrida semanal, reels públicos compartidos entre tenants, una sola puerta medida con topes — está en [ADR 42](adr-42-ideas-reels-costo.md).
>
> **Medición del 2026-11-04 ([§5](#5-medición-del-consumo-antes-del-cambio-r17-2026-11-04)):** con el uso real (unas 2 lecturas por semana en toda la flota), la pantalla gasta ≈ USD 0,2 por semana entre créditos y Claude, y la corrida semanal costará lo mismo. El cambio acota el gasto; con el uso actual no lo baja.

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
   - La caché en Postgres no va sobre `creator_profile_cache` sino sobre el patrón compartido de 0036 (`vendor_payloads`) con tablas nuevas: ver [ADR 42](adr-42-ideas-reels-costo.md) §3.
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
  - Es el speech-to-text del proveedor, **1 crédito** por reel de hasta 120 s.
  - **Con tiempos (VE-04b, m-24921057).** La misma respuesta trae el texto (`transcripts[].text`) y, **anidados en cada entrada de `transcripts[]`**, los tramos con inicio y fin en segundos (`transcripts[].transcript_with_timestamp[].start/end/text`). Se guardan los dos sin otra llamada: la corrida (`reel_runs._transcribe`) usa `reels.transcribe_one` → `fetch_instagram_transcript_timed`. `fetch_instagram_transcript` (solo texto) sigue igual.
    - Los tramos se guardan tal cual en `public_reels.transcript_segments`, con `transcript_reader_version` (hoy 1) como procedencia. Un tramo de solo música puede ser «ah»: se guarda igual, no se descarta ni se convierte en guion.
    - El análisis compartido (ADR 44) los recibe en `ReelSource.transcript_segments`, leídos de `public_reels` del lado del servidor, sin llamar al proveedor (ADR 42 R14).
    - **Verificado en vivo** el 2026-11-05 y otra vez el 2026-11-06 con `just sc instagram media-transcript --url https://www.instagram.com/reel/DeZIKSUNIea/ --cache-max-age 30d` (respuesta de caché: `cached: true`, `credits_charged: 0`, 0 créditos). Las claves de `transcripts[0]` son `id`, `shortcode`, `text` y `transcript_with_timestamp`. Cada tramo es `{"start": 5.426, "end": 9.496, "text": "..."}`, en segundos con decimales. La respuesta trae además `duration_seconds`, `cached_at` y `credits_remaining`. El lector también acepta la lista en el nivel superior, por si el proveedor la mueve.
  - **Registro de consumo.** Cada transcripción pagada deja una fila en `consumption_ledger`: `provider = "scrapecreators"`, `operation = "reels_transcript"`, `metadata.credits` con lo que cobró. Su `idempotency_key` es el `request_key` que el portón reservó en `vendor_usage_events`, así cada fila se puede cruzar con su reserva.
    - **Las dos tablas no cuadran 1 a 1 (conocido, fuera de alcance).** El portón reserva 1 crédito en `vendor_usage_events` antes de cada llamada, también cuando la respuesta sale de la caché del proveedor (`cached: true`, 0 créditos). En ese caso `consumption_ledger` no escribe fila. Sumar `vendor_usage_events` da más créditos que sumar el registro de consumo.
    - Desde 0136, `consumption_ledger.idempotency_key` es único (índice parcial `WHERE idempotency_key IS NOT NULL`). Las filas se insertan con `ON CONFLICT … DO NOTHING`: una clave repetida se descarta y no hace perder el resto del `consumption_scope`. Las filas de Claude no llevan clave y nunca chocan.
    - Los créditos salen de `credits_charged`. Si la respuesta no lo dice, se cuenta 1, salvo que traiga `cached: true` (entonces 0).
    - Una respuesta gratis (caché, sin voz) no deja fila. Una transcripción guardada no se vuelve a pedir.
  - **Un solo pago aunque dos negocios la pidan a la vez (0136, 2026-11-06).** `public_reels` es compartida por todos los negocios. Antes, dos negocios que transcribían el mismo reel al mismo tiempo pagaban los dos y la segunda escritura se descartaba.
    - Antes de pagar, la corrida **reclama** el reel: `reel_store.claim_transcript` hace un solo `UPDATE public_reels SET transcript_lock_until = :until WHERE transcript_at IS NULL AND (transcript_lock_until IS NULL OR transcript_lock_until <= :now) RETURNING id`. El bloqueo de fila hace que solo uno lo consiga; solo ese llama al proveedor. Es la misma forma que `reel_accounts.refresh_lock_until`.
    - El reclamo dura `reel_runs.TRANSCRIPT_CLAIM_SECONDS` (3 min): una transcripción es una sola petición con 45 s de espera por fase (dos fases en el peor caso, 90 s) más la reserva del portón y el guardado; 3 min es el doble. Si un worker se cae, su reclamo vence solo y otra corrida puede volver a intentarlo.
    - `save_transcript` borra el reclamo al guardar. Si la llamada falla (error del proveedor, de red, rechazo del portón o una excepción cualquiera), la corrida lo libera (`release_transcript`, solo si sigue siendo el suyo), así otra corrida reintenta enseguida.
    - Un reel que otro negocio está transcribiendo no se paga aquí y **no cuenta como pagado**. Sí ocupa su lugar entre los `reels.MAX_PAID_TRANSCRIPTS` (40) más vistos, como siempre: un reintento nunca baja más en la lista. Al terminar sus llamadas, la corrida lee del almacén las transcripciones que el otro negocio ya guardó; las que todavía no estén las lee la corrida siguiente.
    - Las de TikTok son gratis y no se reclaman.
    - Límite conocido: una respuesta que tarda más de 3 min puede pagarse dos veces. La transcripción se guarda una sola vez igual.
  - **Respuesta cruda guardada (0136).** Regla de la casa: las respuestas crudas se guardan para poder volver a leerlas. La respuesta pagada se guarda entera en `vendor_payloads` (clave: `path` `/v2/instagram/media/transcript` + `url` y `cache_max_age`), en la misma transacción que la transcripción. El reel la apunta con `transcript_payload_id` y `transcript_payload_fetched_at` (la misma pareja que `source_payload_id`). Así, un `transcript_reader_version` nuevo puede volver a leer los tramos sin pagar otra vez.
    - Se guarda solo cuando esa escritura es la que quedó. Un duplicado tardío no guarda nada y no mueve el apuntador. `expires_at` es de un año: se guarda para volver a leerla, no como caché, y hoy nada borra las vencidas.
    - Los subtítulos de TikTok no se guardan: son gratis y se pueden volver a descargar.
    - Si la fila no se puede escribir, se registra en el log y la transcripción pagada no se pierde.
  - **0 créditos** si lo responde la caché del proveedor o si el video no tiene voz.
  - Los videos de más de 120 s no se transcriben, porque costarían 10 créditos por minuto.
- **TikTok:** los **subtítulos nativos** del video (`video.cla_info.caption_infos[].url`, WEBVTT en el CDN de TikTok). Vienen en la misma lista de reels y **no cuestan nada**. Solo existen si el video tiene voz. Se elige el español primero.
  - **Con tiempos (VE-04b).** De la misma descarga salen el texto (`vtt_text`, igual que antes) y un tramo por cue con su inicio y fin (`vtt_cues`). En los tramos se quitan las etiquetas internas del formato (`<v Ana>`, `<c.x>…</c>`, `<00:00:01.000>`) y se convierten `&amp;`, `&lt;`, `&gt;`. El texto de la tarjeta no cambia. Lo que se oye («ah» incluido) se guarda tal cual. No cuesta créditos ni deja fila de consumo.
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
- [packages/api/src/qualify_api/referentes/reels.py](../packages/api/src/qualify_api/referentes/reels.py): el pipeline (servicio). Se mudó desde `Qualify/reels_discovery.py` sin cambiar el comportamiento (ADR 42 R1, m-24854844).
- [Qualify/reels_discovery.py](../Qualify/reels_discovery.py): adaptador de Reflex. Arma el brief de la marca (semilla de la búsqueda, Brand Kit y catálogo) y firma la ruta de la portada; no llama al proveedor.
- [Qualify/discover_reels.py](../Qualify/discover_reels.py): estado y vista.
- [packages/api/src/qualify_api/referentes/reels_ai.py](../packages/api/src/qualify_api/referentes/reels_ai.py): la revisión de rubro.
- `fetch_reels` en [packages/api/src/qualify_api/vendors/scrapecreators.py](../packages/api/src/qualify_api/vendors/scrapecreators.py) (antes `qualify_api.referentes.scrapecreators_client`).

**Tests:** `packages/api/tests/test_referentes_reels.py` (el pipeline), `Qualify/test_reels_discovery.py` (brief, portada, estado y vista) y `packages/api/tests/test_referentes_reels_ai.py`. Además, el lector se probó contra 6 respuestas reales: 12/12 reels de IG y 9/10 videos de TikTok (el que falta es un carrusel de fotos, descartado a propósito).

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
  - **Corrección 2026-10-25 (ADR 42 §1.3):** esa cifra suponía una lectura diaria y dejaba fuera dos cosas. (1) Las **transcripciones de Instagram** (hasta 40 créditos por lectura) y (2) **Claude**, que cuesta lo mismo que el proveedor en cada apertura en frío (≈ USD 0,001 por reel revisado). Con la memoria real (15–90 min por los despliegues), una marca con 3 aperturas al día gasta **≈ USD 6,5 al mes**, no 0,45–2.
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

## 5. Medición del consumo antes del cambio (R17, 2026-11-04)

Mitad «antes» de R17 (m-24854861), para fijar los parámetros de R5 y R8 (m-24854855). No se hizo ninguna llamada de pago: ni a ScrapeCreators ni a Claude. En producción solo hubo lecturas agregadas, con la sesión de Postgres en solo lectura (`default_transaction_read_only=on`). Las marcas van sin nombre (A–D).

**Etiquetas:** **[V]** leído en producción, en el código o en una medición guardada. **calculado** es aritmética sobre [V] y hereda la etiqueta más débil de sus entradas. **[H]** es un supuesto.

### 5.1 De dónde salen los datos, y lo que no existe

- **No hay registro por función de los últimos 14 días.**
  - Los logs de la app duran hasta el siguiente deploy, porque cada deploy recrea el contenedor. Entre el 21-10 y el 03-11 hubo 160 deploys.
  - La puerta medida (R2), que anota la `feature` de cada llamada, entró en producción el 04-11 a las 18:22 UTC. Desde entonces no hubo ninguna llamada: `vendor_balance` sigue vacío.
  - `vendor_usage_events` y las tablas de R3/R4 (`public_reels`, `reel_accounts`, `brand_reel_*`) están vacías.
- **Claude en producción no deja rastro.** Producción no manda trazas a Langfuse: las claves `LANGFUSE_*` no están en el contenedor `reflex`. La base tampoco guarda el costo de la revisión de reels. Por eso el costo por reel sale de la eval `reels_ai`: 102 llamadas reales del 2026-10-20.
- **Lo que sí hay:**
  1. **El saldo.** Cada respuesta de ScrapeCreators que la búsqueda de referentes guarda en `vendor_payloads` trae `credits_remaining` y `credits_charged`. Juntas forman una serie del saldo de la cuenta.
  2. **El uso de la pantalla.** El proxy de entrada (`edge`, sin reinicios desde el 16-10) registra cada portada de reel que pide el navegador (`/avatar/reel/…`).
     - La URL lleva la dirección firmada del CDN, que cambia en cada lectura del proveedor.
     - El navegador guarda la portada 24 h (`max-age=86400`).
     - Por eso, si un reel ya visto vuelve con otra dirección, hubo otra lectura pagada.
     - Solo se extrajeron la hora, la red, el id del reel y un hash de la dirección: ni IP ni navegador.
  3. **Referentes y ritmo de publicación.** Salen de `brand_account_labels` y `brand_discovery_phases`, y del perfil público guardado de cada referente de Instagram, que trae sus 12 publicaciones más recientes.

### 5.2 Hoy: lo que gasta la pantalla

| Qué | Cifra | Fuente | Etiqueta |
|---|---|---|---|
| Saldo de la cuenta | 6.995 (20-10, 18:02) → 6.890 (21-10, 11:39) → 6.734 (03-11, 18:33) → 6.686 (03-11, 19:17), hora de Bogotá | `credits_remaining` en `vendor_payloads` | [V] |
| Consumo de **toda** la cuenta del 21-10 al 03-11 (producción, dev y CLI juntos) | **156 créditos en 13,3 días: 11,7 por día, ≈ 82 por semana, ≈ USD 0,15 por semana.** El saldo solo bajó, así que no hubo recarga | idem | [V] calculado |
| Búsqueda de referentes | 94 créditos (20-10), 8 (21-10) y 44 (03-11). Es un mínimo: la tabla guarda solo la última respuesta de cada consulta | `credits_charged` en `vendor_payloads` | [V] |
| Días con lecturas de Descubrir reels | **2 de 19** (del 16-10 al 04-11): **1 lectura** el 28-10 y **4** el 04-11, entre las 08:34 y las 08:57 (hora de Bogotá) | log del proxy | [V] |
| Lecturas que se pagaron otra vez por un deploy | 1 de las 4 del 04-11. Un deploy terminó a las 08:38 y la apertura de las 08:41 volvió a leer: 15 de sus 18 reels ya se habían visto, con otra dirección | log del proxy + ejecuciones de `deploy` | [V] |
| Marcas que pueden gastar | **4 de 9.** Tienen referentes de Instagram o TikTok: 12, 12, 2 y 2 cuentas leídas (28), y 2 cuentas las comparten dos marcas. Las 4 tienen brief | Postgres de producción | [V] |
| Páginas por cuenta de Instagram | **1 en las 11 cuentas.** Todas publican menos de 12 reels en 30 días (de 0 a 9) | perfil público guardado | [V] calculado |
| Páginas por cuenta de TikTok (18 cuentas) | De 1 a 4. Valor central: 2, con ~19 reels cada 30 días, como en la medición de dev del 15-10 (8 referentes, 153 reels) | sin perfil guardado | [H] |
| Claude por reel revisado | **USD 0,00098** en lotes de 20 (0,00518 por llamada más 0,00072 por reel) | eval `reels_ai`, Sonnet 5 @ low | [V] |
| Crédito | USD 0,00188 (plan Freelance) | `docs/costos-comparativos-herramientas-ia.md` | [V] |

**Una apertura en frío** (calculado, con TikTok en su valor central):

- Lee las listas otra vez y vuelve a revisar con Claude a todos los candidatos, porque la memoria de veredictos murió con el proceso.
- Una transcripción de Instagram leída en los últimos 30 días sale gratis, de la caché del proveedor (`cache_max_age=30`). Solo la primera lectura de un reel paga transcripción.

| Marca | Cuentas (IG + TikTok) | Páginas | Candidatos | Apertura en frío repetida | Primera lectura |
|---|---|---|---|---|---|
| A | 12 (4 + 8) | 20 | 59 | 20 créditos + USD 0,058 de Claude = **USD 0,096** | 29 créditos, USD 0,11 |
| B | 2 (1 + 1) | 3 | 24 | USD 0,033 | USD 0,043 |
| C | 12 (6 + 6) | 18 | 55 | 18 créditos + USD 0,055 = **USD 0,089** | 41 créditos, USD 0,13 |
| D | 2 (0 + 2) | 4 | 38 | USD 0,045 | USD 0,045 |

- **Rango para A y C**, con TikTok entre 5 y 35 reels al mes: de 12 a 36 créditos, de USD 0,07 a 0,15 por apertura.
- **Candidatos:** salen de la regla de `_candidates` (32 por ventana más 3 por cuenta), ajustada a la medición de dev del 15-10 (153 reels → 58 candidatos).
- **El costo por apertura del ADR 42 §1.3 se confirma** (USD 0,11; aquí, USD 0,09–0,10 para las dos marcas grandes).
- **La frecuencia que suponía el ADR, no.** Suponía 3 aperturas al día por marca, unos USD 50 al mes de flota y 13.000 lecturas. Lo medido:
  - toda la cuenta gastó 156 créditos en 13 días;
  - la pantalla se leyó unas 5 veces en 19 días (calculado: entre 120 y 200 créditos más ≈ USD 0,2 de Claude);
  - eso es **≈ USD 0,2 por semana, ≈ USD 0,8 al mes**.

### 5.3 Con la corrida semanal (R4 + R8)

Cómo cuesta una corrida, con las reglas de R4:

- **Listas:** una corrida cada 168 h siempre supera el TTL de 72 h, así que cada corrida semanal hace el recorrido completo de 30 días de cada cuenta.
- **Transcripciones:** solo se pagan las de los reels nuevos de Instagram de la semana. Una transcripción guardada no se vuelve a pagar.
- **Claude:** solo revisa los candidatos nuevos. `input_hash` no incluye las métricas, así que un reel ya juzgado conserva su veredicto aunque cambien sus vistas.

| Marca | Créditos por semana | Claude por semana | USD por semana | USD por mes |
|---|---|---|---|---|
| A | 22 | 0,037 | 0,079 | 0,34 |
| B | 4 | 0,009 | 0,017 | 0,07 |
| C | 23 | 0,033 | 0,077 | 0,33 |
| D | 4 | 0,011 | 0,019 | 0,08 |
| **Las 4, activas** | **54** | **0,09** | **0,19** | **0,83** (0,48–1,37 según TikTok) |

- **Primera corrida de una marca:** 29 créditos (A) y 41 (C), más ≈ USD 0,06 de Claude.
- **«Buscar reels nuevos» entre 24 y 72 h después de la corrida:** lee la página 1 de cada cuenta. Son 12 o 13 créditos en A y C, y 2 en B y D.
- **Marcas activas hoy:**
  - 4 cumplen las condiciones (referentes y brief);
  - 1 o 2 abrieron la pantalla en los últimos 14 días, según el log del proxy, que no dice qué marca era;
  - **0 tienen una apertura registrada:** hoy nada guarda las aperturas.
- **Con 1 o 2 marcas activas:** USD 0,08–0,16 por semana, USD 0,34–0,67 al mes.
- **Frente a hoy:** cuesta lo mismo, ≈ USD 0,2 por semana en los dos casos. **Con el uso actual el cambio no ahorra dinero.**
  - Lo que compra es un gasto acotado: topes, piso, ninguna lectura repetida por un deploy y una pantalla que abre sin esperar.
  - Empieza a ahorrar cuando una marca pasa de ~1 apertura en frío por semana: la corrida semanal cuesta USD 0,077 y cada apertura en frío, USD 0,09–0,10.
- **Frente al ADR §2.1:**
  - El ADR esperaba USD 0,43 al mes por marca en la parte semanal, con 8 referentes. Las marcas grandes de producción quedan en USD 0,33–0,34: sus cuentas de Instagram caben en una página, y cada semana se pagan 2–5 transcripciones, no 10–15.
  - El ADR esperaba USD 4–8 al mes para una flota de 8 marcas. La flota real son 4 marcas que pueden gastar: ≈ USD 0,8 al mes (0,5–1,4), y ≈ USD 0,1 más por marca si usa el botón una vez por semana.

### 5.4 Parámetros de R5 y R8

**TTL de 24 h y 72 h: se quedan.**
- La corrida semanal siempre hace el recorrido completo, y nada se paga dos veces en la semana.
- «Buscar reels nuevos» cuesta 0 créditos de listas en las 24 h siguientes a la corrida, la página 1 entre 24 y 72 h, y el recorrido completo después.
- En las 11 cuentas de Instagram de producción, la página 1 ya es el recorrido completo: cuesta el mismo crédito.
- Los 9 tenants tienen `America/Caracas`, así que todas las corridas salen el lunes a las 06:00 de Caracas (10:00 UTC). Las 2 cuentas compartidas se leen una sola vez, por el candado. No hace falta escalonar con 4 marcas.

**Topes de R5 (150 créditos al día, 600 al mes): sirven, con dos cambios.**
- El peor caso de una corrida de 30 días es 12 cuentas × 4 páginas + 40 transcripciones = **88 créditos**. Una corrida semanal y un botón el mismo día caben en 150.
- Una marca grande gasta ≈ 150 créditos al mes: 4,33 corridas de 22–23 créditos más ~4 botones de 13. El tope de 600 deja 4 veces de margen.
- **Cambio 1:** la lectura de 90 días del operador cuesta hasta 12 × 12 + 40 = **184 créditos** en el peor caso. Pasa el tope diario y quedaría en `budget_stopped` a mitad de camino. No debe contar contra el tope diario del negocio.
- **Cambio 2, el importante:** el tope debe sumar el `credits_charged` de la respuesta, no 1 por respuesta.
  - Hoy R4 cuenta 1 crédito por respuesta (`_counting_client`) y su comentario dice que el proveedor no informa qué respuestas fueron gratis. Sí lo informa: 394 de las 402 respuestas guardadas traen `credits_charged` (las otras 8 son 404), y las 168 que llegaron con `cached: true` cobraron 0.
  - Al lanzar, las transcripciones que la pantalla actual ya pidió en los últimos 30 días llegan gratis de la caché del proveedor y contarían como pagadas: hasta 40 créditos de más por corrida.
  - La medición «después» de R17 saldría inflada.

**Inactividad de 14 días: se queda, pero hay que registrar la apertura.**
- Entre las dos lecturas observadas pasaron 7 días (28-10 → 04-11). Con 7 días de ventana, una marca que abre cada semana entraría y saldría. Con 14, aguanta una semana sin abrir.
- Una marca que deja de abrir cuesta como mucho 2 corridas: ≈ USD 0,16 en las grandes.
- **Riesgo:** hoy nada registra una apertura. Si «activa» se lee de `brand_reel_ideas.seen_at`, una marca que abre la pantalla vacía (todavía sin ideas) no registra nada y nunca se activa.
- R7/R8 deben guardar cada apertura desde el primer día, como hace `mark_opened` (`brand_reel_activity.last_opened_at`) en el trabajo de R8 en curso, y la regla de los 14 días debe leer eso, no `seen_at`. Al lanzar no habrá ninguna marca activa hasta que alguien abra la pantalla.

### 5.5 La memoria de 6 h

**No controla el gasto y casi no ahorra.**
- **Pocas veces dura 6 h:** de 08:00 a 22:00 (hora de Bogotá), una lectura llegó a las 6 h solo el 45 % de las veces en los últimos 14 días (mediana: 252 min). Del 20 al 24-10 fue el 30 % (mediana: 106 min).
- **Casi nunca tiene una segunda apertura que atender:** la flota lee la pantalla unas 2 veces por semana.
- **La única repetición observada (04-11) la cortó un deploy** a los 4 minutos, y se volvió a pagar: ≈ 20 créditos y USD 0,06 de Claude.
- **No conviene alargarla ni llevarla a Redis:** la reemplaza la corrida persistente.
- **Quitarla ahorra las lecturas repetidas por un deploy:** 1 de cada 5 lecturas observadas, ≈ USD 0,10 cada una. Son centavos con el uso actual.

### 5.6 Lo que no se pudo medir

- **El consumo por función de los 14 días.** No queda log y la puerta solo anota la `feature` desde el 04-11 a las 18:22 UTC. Los 156 créditos del 21-10 al 03-11 mezclan cosas que no se pueden separar: la lectura del 28-10, avatares, el asistente del Brand Kit, la CLI y dev.
- **El saldo de hoy.** El último dato es 6.686 (03-11, 19:17).
  - `vendor_balance` se llenará con la próxima llamada en producción.
  - `just sc balance` no se corrió: el skill `qualify-scrapecreators` no confirma que cueste 0 créditos, aunque el código y el ADR dicen que la ruta es gratuita. Si el fundador lo confirma, el saldo sale al instante.
- **Las lecturas que fallaron sin mostrar tarjetas**, por ejemplo con Claude caído. No piden portadas y el log del proxy no las ve. Aun así, el saldo las acota: ≤ 156 créditos en esos 13 días.
- **El ritmo de las 18 cuentas de TikTok.** No hay perfil guardado: por eso el rango de 5 a 35 reels al mes.
- **Qué marca leyó.** La URL de la portada no dice el negocio: por eso «1 o 2 marcas activas».
- **Las recargas.** El saldo pasó de 0 (09-10) a 6.995 (20-10). La cifra de 3.681 del 15-10 (§2) supone otra recarga o una lectura de otra cuenta. El historial está en el panel de ScrapeCreators, y para verlo hace falta el fundador.

### 5.7 Cómo repetirlo (R17 «después», una semana con R5 en producción)

Desde el servidor, con el alias `dc` de `docs/despliegue-hetzner.md` §7 y en solo lectura:
`dc exec -T -e PGOPTIONS="-c default_transaction_read_only=on" postgres psql -U qualify_owner qualify`.

```sql
-- Consumo semanal por negocio y función (cuando R5 escriba vendor_usage_events)
SELECT date_trunc('week', created_at AT TIME ZONE 'America/Caracas') AS semana,
       tenant_id, vendor, feature, sum(credits) AS creditos, round(sum(usd_estimate), 4) AS usd
FROM vendor_usage_events
WHERE created_at >= now() - interval '14 days'
GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

-- Claude y créditos por corrida (R4/R8)
SELECT date_trunc('week', finished_at AT TIME ZONE 'America/Caracas') AS semana, trigger, status,
       count(*) AS corridas, sum(credits) AS creditos, round(sum(cost_usd), 4) AS claude_usd
FROM brand_reel_runs WHERE finished_at >= now() - interval '14 days'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- Serie del saldo, de las respuestas guardadas (la usada aquí)
SELECT fetched_at, path, payload->>'credits_remaining' AS saldo, payload->>'credits_charged' AS cobrado,
       payload->>'cached' AS cache
FROM vendor_payloads WHERE payload ? 'credits_remaining' ORDER BY fetched_at;

-- Marcas que pueden gastar: referentes de IG/TikTok y brief
WITH r AS (SELECT brand_id, count(*) n FROM brand_account_labels
           WHERE label = 'referente' AND network IN ('instagram', 'tiktok') GROUP BY 1),
     b AS (SELECT DISTINCT brand_id FROM brand_discovery_phases
           WHERE seed IS NOT NULL AND seed::text NOT IN ('{}', 'null'))
SELECT count(*) AS marcas, sum(least(n, 12)) AS cuentas_leidas FROM r JOIN b USING (brand_id);
```

Las lecturas de la pantalla salen del log del proxy, en el servidor. Así se cuentan sin guardar IP:

```bash
docker logs edge-edge-1 2>&1 | grep "avatar/reel" \
  | sed -nE 's/^([0-9\/]+ [0-9:]+)\.[0-9]+.*"uri": "\/avatar\/reel\/([a-z]+)\/([0-9A-Za-z_-]+)\?u=([^&"]*)[&"].*/\1 \2 \3 \4/p' \
  | while read d t n i u; do echo "$d $t $n $i $(printf %s "$u" | md5sum | cut -c1-8)"; done
```

Un par (reel, hash) nuevo de un reel ya visto marca una lectura pagada. Después de R7, abrir la pantalla ya no lee, así que este conteo pierde sentido y lo reemplaza `brand_reel_runs`.
