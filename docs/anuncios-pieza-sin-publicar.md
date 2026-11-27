# Anuncios desde imágenes o videos de una pieza sin publicar

Entrega backend de m-24828982. Implementa el recorrido para **dos imágenes o dos videos
finales ya existentes**, uno de 4:5 y otro de 9:16, de una pieza aprobada que todavía no se
publicó. No se mezclan imagen y video en el mismo anuncio. Los videos llegaron en una segunda
entrega (migración 0161); ver «Videos» más abajo.
No modifica el generador, `CopyPayload`, las opciones de botón ni el trabajo de m-24828975.
El texto, título y enlace se reciben explícitamente en la solicitud de anuncios. No se
escriben de regreso en la pieza.

## Entrada para la integración

`UnpublishedImageService(ObjectGate(...))`, en `qualify_api.ads.unpublished_service`,
expone `prepare` y `confirm`. Las dependencias por defecto son los repositorios reales
de PostgreSQL y el cliente de Marketing autenticado por el resolvedor existente. No hay
un cliente simulado de reserva ni una variable que salte comprobaciones.

La integración debe proporcionar negocio, pieza, cuenta seleccionada y los identificadores
de las dos imágenes existentes. Nunca admite una URL, clave de R2 ni identificador de
imagen publicitaria suministrados por el cliente. Requiere la sesión real y el usuario
interno que aprueba. La selección tiene que pertenecer a la versión activa y aprobada
de esa misma pieza y marca. Rechaza mezclas de imagen y video, carruseles hechos con
una pieza, piezas purgadas y partes de video. El carrusel de productos del Catálogo es otra
entrada (ver «Carrusel de productos del Catálogo»).

La solicitud `ImageAdForm` lleva mensaje, título, enlace HTTPS, presupuesto total interno,
fechas y país. En esta primera entrega admite COP, visitas al sitio web, «Más información»,
Instagram y un país explícito. No selecciona un país por defecto. Los límites locales de
Qualify son 8 MiB por imagen, 2.200 caracteres de mensaje y 100 de título. No son una
afirmación sobre los límites de Meta. Meta debe aceptar la validación exacta de la solicitud.

## Qué cuenta como «publicada» (m-25130283)

Una pieza está publicada cuando Qualify tiene, para esa pieza, un evento del calendario con un
intento en `publish_attempts` en estado `published` hecho por una conexión de Instagram. No
se exige el id de Meta (`published_media_id`): cuando Meta confirma la publicación pero falla
la lectura del id, el intento queda publicado sin id (QUA-111) y la publicación ya está en
Instagram. Vale para cualquier formato, historias incluidas. Una
pieza publicada solo en Facebook sigue disponible. La columna
`content_drafts.published_media_id` no se usa: ningún código la escribe, y por eso antes se
ofrecía «Anunciar sin publicar» en piezas que ya estaban en Instagram.

La condición vive en un solo lugar, `NOT_PUBLISHED_BY_QUALIFY` en
`qualify_api.ads.unpublished_repository`, y la usan la lectura que propone la pieza
(`Qualify/promotion_unpublished_provider.py`) y la que la valida otra vez antes de preparar y
de confirmar (`load_image_source`, `guard_source`). Si la pieza se publica entre la
preparación y la confirmación, la confirmación se niega. La lectura va por `tenant_session`
y compara el negocio en cada unión: el intento de otro negocio nunca cuenta (prueba con base
de datos y dos negocios).

La condición solo se aplica a la pareja 4:5 + 9:16. El anuncio de historia con botón de
enlace (`feed_asset_id=None`, «formato historia») siempre crea un creativo 9:16 nuevo
(decisión D1 de la épica), así que una pieza ya publicada por Qualify se sigue ofreciendo ahí.

**Límite conocido:** una historia que el dueño sube a mano con «Abrir en Instagram» no deja
ningún rastro en Qualify (no hay intento ni id de Meta). Por eso esa pieza se sigue tratando
como no publicada y se le ofrece «Anunciar sin publicar». Registrar esas historias queda
fuera de esta entrega.

## Preparación y confirmación

1. La preparación exige `confirm_preparation=True`, comprueba cuenta, acceso y pagos, y
   conserva una solicitud inmutable con pieza, versión, revisión, cuenta y credencial.
2. Abre los archivos mediante `ObjectGate`, mide bytes, MIME y dimensiones, y calcula su
   resumen SHA-256. No cambia los archivos ni fabrica recortes.
3. Guarda y confirma en PostgreSQL la intención de cada carga **antes** del POST a
   `/act_<id>/adimages`. La carga queda ligada a negocio, cuenta, versión de credencial,
   imagen y contenido. Una carga incierta o interrumpida no se vuelve a enviar.
4. Compila `object_story_spec` y `asset_feed_spec` con reglas de 4:5 para publicaciones y
   9:16 para historias y reels. Los cuatro cambios creativos de marca deben estar apagados.
   Valida campaña, conjunto, creatividad y anuncio con `validate_only`.
5. Reutiliza `PromotionService` y su registro de creación para crear los objetos en pausa.
   Obtiene vistas previas de publicación e historia y guarda una revisión de cinco minutos.
6. La activación requiere `confirm_charge=True` en otra llamada, misma persona, revisión
   vigente y contenido idéntico. Comprueba otra vez cuenta, fuente, permisos y objetos
   remotos. Confirma el reclamo de activación antes de las escrituras y activa primero los
   hijos y al final la campaña. No permite reintentar una activación incierta.

Las comprobaciones finales vuelven a leer la pieza y los resúmenes del archivo. Las lecturas
remotas dentro del control previo de escritura usan otro cliente autenticado para no
reentrar en el bloqueo del cliente que va a escribir. No se mantiene una transacción de
fuente abierta mientras espera a Meta; no se promete atomicidad frente a otro operador.

La propiedad de resultados y pausa tiene una ruta específica que une promoción, receta,
negocio, pieza, marca, cuenta, conexión y credencial. No afloja las uniones del recorrido de
publicación existente. Una edición posterior de la pieza no impide consultar o pausar el
anuncio que ya se autorizó. Cambiar presupuesto, fecha o reanudar por el gestor anterior
queda expresamente fuera de esta entrega: ese gestor todavía requiere una publicación.

Las vistas previas son contenido remoto sin confianza. La futura interfaz debe usar el
saneamiento de vistas previas existente; no debe insertar ese HTML directamente.

## Evidencia y límites reales

Se consultó el SDK oficial de Meta fijado en 26.0.0 el 12 de noviembre de 2026:

- [Cuenta publicitaria](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adaccount.py): carga `adimages` con `bytes` y solicitudes de validación.
- [Historia de creatividad](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativeobjectstoryspec.py): `page_id` e `instagram_user_id`.
- [Contenido por ubicación](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adassetfeedspec.py): imágenes, textos, enlaces y botones.
- [Reglas por ubicación](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adassetfeedspecassetcustomizationrule.py) y [posiciones](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adassetcustomizationrulecustomizationspec.py): etiquetas y selección de plataformas y posiciones.
- [Vistas previas](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adpreview.py): formatos de Instagram.

Estos archivos acreditan nombres y tipos, **no compatibilidad ni permisos de una cuenta
real**. Cada preparación debe superar las validaciones reales antes de crear los objetos;
la confirmación exige identidad y contenido remotos iguales a los aprobados. Si Meta
normaliza o enriquece el contenido de una forma que no coincide, se rechaza la confirmación
en vez de asumir equivalencia. Debe medirse esa respuesta antes de anunciar disponibilidad.

No se hicieron cargas, campañas, activaciones ni gasto reales durante el desarrollo.
Las pruebas de transporte y servicio usan datos sintéticos y clientes explícitos sin red.

## Videos

Mismo `prepare` y `confirm`. Para videos, `feed_asset_id` y `vertical_asset_id` son dos
`image_assets` con `media_type='video'` de la versión activa, y además se pasan
`feed_thumbnail_asset_id` y `vertical_thumbnail_asset_id`: la **portada** de cada video, una
imagen de la misma versión con el mismo formato. Sin portada se bloquea con el motivo
(«Falta la portada de cada video…»); nunca se inventa una URL o un hash de miniatura. La
portada se sube como cualquier imagen (`adimages`) y va como `thumbnail_hash`.

1. **Límites antes de la red.** Primero se pide el tamaño a R2 (HEAD, sin leer el archivo);
   luego se leen por rangos (`ObjectGate.open_range`, nunca `open_object`, que en R2 descarga
   el objeto entero) solo las cabeceras y `moov` (como máximo 8 MiB de metadatos): un solo
   video, duración, ancho y alto; y en la misma pasada el SHA-256 en lecturas de 8 MiB. Las
   lecturas bloqueantes corren fuera del bucle de eventos (`asyncio.to_thread`). Políticas locales, no límites de Meta: MP4,
   hasta 100 MiB y de 1 a 60 segundos. Las dimensiones reales deben coincidir con las de la
   fila. Las portadas se miden igual que las imágenes. Todo esto ocurre antes de la primera
   llamada a Meta.
2. **Reclamo antes de enviar.** `ad_unpublished_videos` (0161, RLS forzado) guarda la
   transferencia por negocio, cuenta, versión de credencial, archivo y contenido. Estados:
   `ready` (medido, nada enviado) → `submitting` (reclamo confirmado con `claim_token` antes
   del primer POST) → `processing` → `ready_remote`; o `unknown` / `failed`. Si el control
   previo falla antes de enviar, o Meta rechaza con certeza el `start` (límite de uso,
   token vencido) sin nombrar un video, vuelve a `ready`; si ya se envió algo y no hay
   respuesta, queda `unknown` y **nunca se vuelve a subir solo**. Un `submitting` sin cambios
   durante 30 minutos (el proceso murió entre el reclamo y el cierre) pasa a `unknown` y se
   pide ayuda. Un disparador impide cualquier otro
   cambio y que cambie el `video_id`.
3. **Carga por partes.** `MarketingClient.upload_video` usa `act_<id>/advideos` en
   `graph-video.facebook.com` con `upload_phase` `start` → `transfer` → `finish`. Meta nombra
   el video en `start` y ese `video_id` se guarda antes de enviar bytes. Cada parte se lee de
   R2 con una lectura por rango (como máximo 16 MiB por parte, límite local); el archivo nunca
   está entero en memoria y no se guarda ninguna URL firmada. Al terminar se comprueba que los bytes enviados
   tienen el mismo SHA-256 medido; si no, queda `failed`.
4. **Procesamiento.** Un video aceptado queda `processing`. Cada `prepare` hace **una** lectura
   `GET /{video_id}?fields=id,status` por video en proceso (`ready` → `ready_remote`, `error`
   o `expired` → `failed`). Mientras alguno no esté listo, `prepare` responde «Meta todavía
   está preparando el video…» y no crea creatividad, campaña ni anuncio. **El contrato de
   reconciliación es repetir el mismo `prepare` con la misma `request_key`**: no reenvía nada
   y no hay hilos ni procesos en segundo plano. Una transferencia `unknown` necesita
   revisión manual.
5. **Creatividad.** `asset_feed_spec` con `ad_formats=["SINGLE_VIDEO"]`, `videos` con
   `video_id`, `thumbnail_hash` y etiqueta, y las mismas dos reglas por ubicación con
   `video_label`. Un hash de imagen nunca se acepta como `video_id` ni al revés.
6. **Confirmación.** Igual que con imágenes. Al empezar se vuelven a medir los dos videos y
   las portadas; los controles previos a cada activación vuelven a medir solo las portadas
   (releer hasta 200 MiB por escritura no es razonable), y los videos ya están ligados por su
   resumen y su `video_id` en la revisión.

Sin verificar en vivo (no se hicieron llamadas reales): el anfitrión `graph-video`, la forma
exacta de las respuestas por partes (desplazamientos como texto) y `status.video_status`
salen del SDK oficial 26.0 (`video_uploader.py`, `advideo.py`). Deben medirse en el ensayo
real autorizado antes de anunciar el video, junto con `validate_only` de la creatividad.

## Historia con botón de enlace (m-25026350)

La API de publicación de Instagram no publica stickers en una historia, así que una historia
orgánica no puede llevar enlace. Esta variante crea **solo el anuncio** (no se publica ninguna
historia orgánica) con **un único archivo 9:16** (imagen, o video MP4 con su portada) y lo
muestra **solo en las historias de Instagram**. Se pide con `feed_asset_id=None` en
`UnpublishedImageService.prepare`; todo lo demás (cargas con reclamo previo, estado
desconocido, espera de procesamiento del video, `validate_only`, lectura de vuelta, vistas
previas, revisión y consentimiento de gasto en `confirm`) es el mismo camino de las parejas.

- **Ubicación:** `targeting.publisher_platforms=["instagram"]`,
  `instagram_positions=["story"]`; sin `asset_customization_rules`, sin feed ni reels. Una sola
  vista previa (`INSTAGRAM_STORY`); `feed_html` queda vacío.
- **Objetivo:** `OUTCOME_TRAFFIC`, `optimization_goal=LINK_CLICKS`, `destination_type=WEBSITE`,
  `billing_event=IMPRESSIONS` (constantes de `AdSet` en el SDK oficial 26.0.0, `adset.py`).
- **Creativo:** `object_story_spec` con `page_id`, `instagram_user_id` y `link_data`
  (`image_hash`, `link`, `message`, `name`, `call_to_action`) para una imagen, o `video_data`
  (`video_id`, `image_hash` de la portada, `message`, `title`, `call_to_action`) para un video.
  `call_to_action = {type, value: {link}}`. Campos de `AdCreativeObjectStorySpec`,
  `AdCreativeLinkData`, `AdCreativeVideoData` y `AdCreativeLinkDataCallToActionValue` del
  [SDK oficial 26.0.0](https://github.com/facebook/facebook-python-business-sdk/tree/26.0.0/facebook_business/adobjects).
- **Botón:** el guardado en la pieza, dentro de `WEBSITE_CTAS`; «Llamar» (`CALL_NOW`) y los
  botones de chat se rechazan antes de llamar a Meta. v1 solo lleva a una página web (sin
  `wa.me`; WhatsApp llegará con el objetivo de clic a mensaje).
- **Antes de cualquier llamada a Meta:** proporción 9:16 exacta, tipo (JPEG/PNG o MP4 con
  portada 9:16), lectura de la imagen (8 MB) o del video (100 MB, 1 a 60 segundos). Son las
  mismas reglas locales de las parejas (los 1 a 60 segundos ya se fijaron por la tarjeta de
  historia, la ubicación más estricta). No se aplica ninguna otra regla exclusiva de
  historias: no leímos en una fuente oficial otro límite verificable (zona segura, largo del
  texto en historias), y Meta valida el resto en `validate_only` antes de crear nada.
- **Procedencia:** `pipeline_version` `ad-story-image-v1` / `ad-story-video-v1` en la fuente
  aprobada; la revisión guarda `kind` `unpublished-story-images` / `unpublished-story-videos`.
  Las parejas conservan exactamente su instantánea y su huella (test).
- **Público sugerido «Tus seguidores y quienes interactuaron contigo»:** los públicos
  personalizados de m-24828983 hoy se resuelven desde una publicación ya hecha
  (`publish_attempt_id`), que esta pieza no tiene; por eso este backend no lo agrega al
  anuncio. Queda como sugerencia de la pantalla hasta que exista un alcance por cuenta.
- **Sin verificar en vivo:** que Meta devuelva `object_story_spec.link_data`/`video_data` y
  el `targeting` sin campos normalizados de más (por ejemplo `image_url` junto a `image_hash`).
  La lectura de vuelta compara exacto y, si no coincide, se niega a activar (falla cerrada).
  **Antes de lanzar, hay que leer de vuelta un anuncio de historia real en pausa** en la prueba
  en vivo m-24828971 y ajustar la comparación solo a lo que Meta añada de verdad. En esa misma
  prueba se decide si una historia ya publicada puede promocionarse por su id.

### Un solo anuncio de historia por pieza, salvo que el dueño elija otro (N3, m-25142902)

- **Qué es «ya tiene un anuncio en historias»:** cualquier fila de `ad_unpublished_sources` de
  la pieza con `source->>'pipeline'` `ad-story-image-v1` / `ad-story-video-v1`, tenga o no ya
  campaña en pausa (`promotion_id`). Sin migración: se reutiliza la aprobación guardada.
- **Del lado del servidor y sin carreras:** `UnpublishedRepository.approve` toma
  `pg_advisory_xact_lock('ad-story:<pieza>')` en la misma transacción que guarda la aprobación,
  antes de cualquier llamada a Meta. Si hay otra aprobación de historia de la pieza (otra clave
  de pedido: recargar, otra pestaña u otro teléfono) más nueva que la que el dueño ya vio,
  responde `StoryAdExists` (motivo `story_ad_exists`) y no crea nada. Repetir la misma clave
  (video en proceso) nunca es un duplicado. Dos teléfonos a la vez: pasa uno solo (test `-m db`).
- **La elección del dueño:** el asistente avisa al abrirse y cuando el servidor lo rechaza:
  «Ver el anuncio que ya tienes» (`/promotions/<id>`, o «Anuncios» si aún no tiene campaña) o
  «Crear otro anuncio», que suma la aprobación avisada a `seen_story_ads`. Las claves de pedido
  de la propia sesión también van ahí: su intento, aunque haya fallado (video en proceso, Meta
  lo rechazó), nunca es un «duplicado», y cambiar el presupuesto y volver a preparar no avisa.
  Si la aprobación avisada aún no tiene campaña, el botón dice «Ver tus anuncios».
- **En «Anuncios»:** el anuncio de historia lleva la etiqueta «Anuncio en historias», la imagen
  9:16 (o la portada del video) mientras la pieza conserve sus archivos, y «Ver la historia».
  La tarjeta de la historia dice «Ya tiene un anuncio en historias».

## Carrusel de productos del Catálogo (m-25113484)

Un anuncio en carrusel de Instagram cuyas tarjetas son productos del Catálogo del negocio,
creado **en pausa** con la misma aprobación, cargas con intención previa, `validate_only`,
lectura de vuelta, vista previa y confirmación que el anuncio desde una pieza.

**Entrada para la pantalla.** `CarouselAdService(gate, store=None)` en
`qualify_api/ads/unpublished_service.py` (`store` lee las fotos del Catálogo; si falta usa el
mismo almacén del Catálogo, R2 más el volumen local para claves antiguas).

- `await prepare(*, tenant_id, ad_account_id, products, form, actor, request_key,
  confirm_preparation) -> UnpublishedPreview`. `products` es una tupla de
  `(id del producto, enlace de la tarjeta)` en el orden de las tarjetas; un enlace vacío usa
  `form.link_url`. `form` es el mismo `ImageAdForm`: el mensaje, el enlace «ver más», el botón,
  el presupuesto, las fechas y el país; el `headline` no se envía a Meta (cada tarjeta lleva el
  suyo), pero el formulario lo sigue exigiendo. La vista previa del feed de Instagram llega
  en `feed_html`; `vertical_html` queda vacío.
- `await confirm(*, tenant_id, recipe_id, review_id, actor, confirm_charge) -> str`, heredado
  sin cambios: `"active"` o `"unknown"`.
- Errores: `UnpublishedUnavailable` (texto en español para la persona dueña, `reason` igual
  que en las imágenes). Entre 2 y 10 productos, si no: «Elige entre 2 y 10 productos de tu
  Catálogo para el carrusel.».

**Reglas.** Cada producto se lee con `CatalogService.get_product` bajo la sesión del negocio
(RLS); tiene que estar activo, ser de la marca de la cuenta publicitaria, tener foto JPG o
PNG con medidas y nombre y precio. La tarjeta lleva la foto principal del producto, el título
«Nombre · $precio» (el precio con `price_label` del Catálogo), el precio en `description` y su
propio enlace HTTPS. El cliente solo envía ids de producto y enlaces: nunca claves, URLs de
imagen ni `image_hash`. Una clave de foto que no sea del negocio se rechaza antes de leerla.
Si el producto cambia (nombre, precio, foto) entre preparar y confirmar, no se activa.

**Carga a Meta y procedencia.** Cada foto se sube con la misma intención previa de
`ad_unpublished_uploads` (`asset_id` = id de la foto en `product_media`), así que repetir la
preparación no vuelve a subir. La aprobación queda en `ad_unpublished_sources` sin pieza
(`draft_id` nulo, solo con `pipeline_version = ad-catalog-carousel-v1`, migración 0181) y con
los productos, fotos y enlaces en `source`. La promoción guarda como procedencia
`source_media_id = catalog-carousel:<id de la aprobación>` y los enlaces de las tarjetas en
`card_links`: la regla de que todo `link` de la creatividad sea uno aprobado se mantiene.

**Carga útil (SDK 26.0.0, `adobjects/`).** `object_story_spec.link_data` con `link`, `message`,
`call_to_action`, `child_attachments` (cada una: `link`, `image_hash`, `name`, `description`,
`call_to_action`), `multi_share_optimized: false` (Meta no reordena las tarjetas que la persona
aprobó) y `multi_share_end_card: false`. Campos comprobados en
[AdCreativeLinkData](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativelinkdata.py)
y
[AdCreativeLinkDataChildAttachment](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativelinkdatachildattachment.py)
el 24 de noviembre de 2026. Ubicación: solo el feed de Instagram (`instagram_positions:
["stream"]`); vista previa `INSTAGRAM_STANDARD`.

**Sin verificar en vivo** (hace falta una cuenta real, prueba m-24828971):
- que `validate_only` acepte fotos del Catálogo que no sean cuadradas (no se recortan; Meta
  muestra el carrusel en 1:1);
- qué texto de la tarjeta muestra Instagram: por eso el precio va también en el título;
- que la lectura de vuelta de `object_story_spec` con `child_attachments` coincida exacta (si
  Meta añade campos, se niega a activar: falla cerrada).

## Pendiente del ticket completo

- Integración en una pantalla de anuncios con selección de imágenes o videos y su portada,
  revisión y confirmación.
- Prueba real autorizada, con publicación de vista previa, formatos y presupuesto concretos,
  y la medición en vivo de la carga de videos.
- Gestión posterior de cambios pagados para esta nueva clase de fuente.

Este backend no añade un botón a la pieza ni completa por sí solo m-24828982. No requiere
un token nuevo ni activa procesos periódicos al desplegarse. Las migraciones 0150 y 0161
(y 0181 para el carrusel) añaden los registros de fuente y carga con RLS forzado, procedencia e invariantes
reversibles. El lector
periódico de resultados conserva su configuración y preparación operativa existentes.
