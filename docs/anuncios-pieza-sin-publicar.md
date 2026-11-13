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
de esa misma pieza y marca. Rechaza mezclas de imagen y video, carruseles, piezas
purgadas y partes de video.

La solicitud `ImageAdForm` lleva mensaje, título, enlace HTTPS, presupuesto total interno,
fechas y país. En esta primera entrega admite COP, visitas al sitio web, «Más información»,
Instagram y un país explícito. No selecciona un país por defecto. Los límites locales de
Qualify son 8 MiB por imagen, 2.200 caracteres de mensaje y 100 de título. No son una
afirmación sobre los límites de Meta. Meta debe aceptar la validación exacta de la solicitud.

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
  portada 9:16), lectura de la imagen (8 MB) o del video (100 MB, 1 a 60 segundos).
- **Procedencia:** `pipeline_version` `ad-story-image-v1` / `ad-story-video-v1` en la fuente
  aprobada; la revisión guarda `kind` `unpublished-story-images` / `unpublished-story-videos`.
  Las parejas conservan exactamente su instantánea y su huella (test).
- **Público sugerido «Tus seguidores y quienes interactuaron contigo»:** los públicos
  personalizados de m-24828983 hoy se resuelven desde una publicación ya hecha
  (`publish_attempt_id`), que esta pieza no tiene; por eso este backend no lo agrega al
  anuncio. Queda como sugerencia de la pantalla hasta que exista un alcance por cuenta.
- **Sin verificar en vivo:** que Meta devuelva `object_story_spec.link_data`/`video_data` sin
  campos añadidos (la lectura de vuelta compara exacto y, si no coincide, se niega a activar),
  y si una historia ya publicada puede promocionarse por su id (m-24828971).

## Pendiente del ticket completo

- Integración en una pantalla de anuncios con selección de imágenes o videos y su portada,
  revisión y confirmación.
- Prueba real autorizada, con publicación de vista previa, formatos y presupuesto concretos,
  y la medición en vivo de la carga de videos.
- Gestión posterior de cambios pagados para esta nueva clase de fuente.

Este backend no añade un botón a la pieza ni completa por sí solo m-24828982. No requiere
un token nuevo ni activa procesos periódicos al desplegarse. Las migraciones 0150 y 0161
añaden los registros de fuente y carga con RLS forzado, procedencia e invariantes
reversibles. El lector
periódico de resultados conserva su configuración y preparación operativa existentes.
