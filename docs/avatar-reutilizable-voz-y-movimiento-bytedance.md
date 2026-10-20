# Avatar reutilizable con la misma voz y réplica de movimientos: suite ByteDance (BytePlus)

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN 2026-10-15]` · fuentes consultadas el 2026-10-15 · **sin llamadas en vivo ni de pago**

Marcas:
- **[DOC]**: documentación oficial de BytePlus. El Markdown se extrajo de `window._ROUTER_DATA…curDoc.MDContent` y entre paréntesis va la fecha de última actualización de cada página.
- **[PRECIO]**: página de precios oficial.
- **[2ª]**: tercero.
- **no verificado**: no confirmado en fuente primaria.
- **inferencia**: deducción nuestra a partir de fuentes primarias.

Este documento amplía lo que ya está en otros cuatro y no lo repite:
- [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md): caras reales, edición con Seedance y precios por token.
- [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md)
- [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md): cómo Seed Speech guarda las voces.
- [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md): lip-sync posterior y el patrón *voice-as-audio*.

Encaje en el producto:
- **Motor de compra:** activación (reels con la cara y la voz de una persona de la marca). No toca la escucha.
- **Fase:** carril creativo de *dogfooding* (Parte 4-A, ADR 21).
- **Infraestructura:** se compra, no se construye.

---

## Resumen: respuesta directa

### ¿Se puede guardar el avatar para reutilizarlo con el MISMO perfil de voz?

**Sí, pero la unión entre avatar y voz la tenemos que guardar nosotros. BytePlus no tiene ningún objeto que guarde cara y voz juntas.**

1. **OmniHuman 1.5 y 2.0 no guardan nada.** Cada llamada recibe:
   - en la 1.5: `image_url` + `audio_url`, más `prompt`, `mask_url` y `seed` opcionales;
   - en la 2.0: `image_urls` + `audio_url`, más `prompt` y `enable_watermark`.

   El «Subject Recognition» (`realman_avatar_picture_create_role_omni_cv`) parece un `create_role` por el nombre, pero solo devuelve `{"status":0|1}`: si hay un sujeto humano o humanoide. **No devuelve ningún ID.**

   Con OmniHuman, «avatar guardado» significa: la foto en R2, más el `seed` y el prompt que nos gustaron, guardados en Postgres. El `seed` da un resultado «con probabilidad extremadamente alta» igual si el resto de parámetros no cambia.
2. **BytePlus tiene cuatro objetos persistentes con ID. Ninguno guarda la voz:**

   | Objeto | ID | Se crea a partir de | Para qué sirve |
   |---|---|---|---|
   | **Clone Avatar** (Vision AI) | `resource_id` | video de la persona de >1 min (recomendado 3–5 min) | 300 USD por avatar + 0,015 USD/s de video generado; se maneja con audio |
   | **Flash Avatar** (Vision AI) | `resource_id` | video de 10–15 s | entrenamiento de ~10 min; precio **no publicado** |
   | **Interactive Avatar flowact-r2** (Vision AI) | `role_id` | una foto | **solo streaming en tiempo real** por WebSocket + ByteRTC; no sirve para reels |
   | **Real-person asset group** (ModelArk) | `group-…`, más un `asset://…` por cada archivo | prueba de vida + imágenes, videos y audios de la persona | solo para Seedance 2.0 / 2.5; reutilizable en N generaciones |

3. **Todos los motores de BytePlus reciben la voz como audio, no como voz guardada.**
   - Clone Avatar, Flash Avatar, OmniHuman e Interactive Avatar piden un `audio_url` o PCM.
   - Ninguno acepta un `speaker_id` de Seed Speech.
   - El audio que guarda un asset de ModelArk sirve **solo como referencia de timbre**: Seedance genera su propia voz «parecida» (ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §1.1).
4. **La voz persistente vive en Seed Speech** (`speaker_id`, permanente, sin API de borrado).

   El «mismo perfil de voz» se consigue así:
   - una fila nuestra une `speaker_id` + foto + `asset_group_id` (y `resource_id` de Clone Avatar si algún día se compra) + consentimiento;
   - cada guion se sintetiza a un MP3 en R2, que es lo que reciben todos los motores.

   La tabla está en la §5.
5. **Comparación con HeyGen:** el Digital Twin sí guarda avatar y voz juntos. Al crear el twin, HeyGen clona la voz de las imágenes de entrenamiento y la devuelve en `avatar_item.default_voice_id`. Es lo que BytePlus no tiene.

### ¿Puede el avatar replicar los movimientos de un reel de referencia?

**OmniHuman, no. DreamActor M2.0, sí, y está en BytePlus internacional por API. Seedance 2.x, en teoría sí, pero rechaza el reel si sale una cara real.**

| Producto | ¿Copia el movimiento de un video? | ¿Está en BytePlus internacional? | Bloqueo principal |
|---|---|---|---|
| **OmniHuman 1.5 / 2.0** | **No.** No acepta video. Los gestos y la cámara solo se describen en el prompt («primero… luego…») | Sí | — |
| **DreamActor M2.0** | **Sí.** Imagen + «template video» de ≤30 s. Copia **movimiento, expresiones faciales y movimiento de labios**, y conserva la cara y el fondo de la imagen | **Sí**: `dreamactor_m20_gen_video_cvtob`, **0,05 USD/s**, concurrencia 1, 720p a 25 fps | Copia **los labios del reel**, no los de nuestro guion. Hace falta un segundo paso de lip-sync con nuestro MP3. La documentación no dice si la salida conserva el audio del reel |
| **DreamActor M1 / «动作模仿»** | Sí (versión anterior) | **No documentado en BytePlus.** Solo consta en Volcengine (China) | — |
| **Seedance 2.x** (`reference_video`, modo reference) | **Sí, documentado:** «action transfer»; hereda «subject, camera movement, action performance» del video de referencia | Sí | **Rechaza un video de referencia con una cara humana real** (`PrivacyInformation`). Un reel de un creador con cara no pasa. Sirve para reels sin cara (cámara, producto, manos) |
| **Clone Avatar** | Solo los gestos del **propio video de entrenamiento** de la persona, que reproduce «randomly… in rotation». No copia un reel externo | Sí | — |

**Ruta viable para «persona de la marca + movimientos del reel + su voz»:**
1. DreamActor M2.0 con la foto de la persona y el reel recortado a ≤30 s.
2. Lip-sync de esa salida con el MP3 de Seed Speech: HeyGen Lipsync Precision o Sync.so (ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.13).
3. Montaje.

Costo: **≈0,8 USD por cada 10 s** sin reintentos. Que la calidad del lip-sync sobre una salida de DreamActor sea aceptable en español está **no verificado**.

---

## 1. Evidencia: ¿se puede guardar el avatar?

### 1.1 OmniHuman 1.5 / 2.0: sin estado

| Afirmación | Fuente |
|---|---|
| 1.5, cuerpo de la petición: `req_key=realman_avatar_picture_omni15_cv`, `image_url`, `mask_url` (opcional), `audio_url`, `seed` (opcional, −1 = aleatorio), `prompt`, `pe_fast_mode`, `output_resolution` (720/1080), `callback_url`. **Ningún ID de avatar ni de rol.** | [DOC] [omnihuman-video_generation](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-video_generation) (2026-10-15) |
| `seed`: «If the random seed is the same positive integer and other parameters are consistent, the generated content will have an extremely high probability of being identical in effect». | idem |
| 2.0, cuerpo de la petición: `req_key=realman_avatar_picture_omni20_cv`, `prompt`, `audio_url`, `image_urls`, `enable_watermark`. Audio de 4–300 s. **Sin `seed` ni `mask_url`.** | [DOC] [omnihuman-2-0-video-generation](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation) (2026-10-15) |
| Subject Recognition (`realman_avatar_picture_create_role_omni_cv`) devuelve `resp_data: {"status":1}` (contiene un humano o humanoide) o `0`. **No es un «role» persistente.** | [DOC] [omnihuman-subject_recognition](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-subject_recognition) (2026-10-15) |
| Las URLs de video de Vision AI caducan en 1 h y las de imagen en 24 h. | [DOC] [FAQ Vision AI](https://docs.byteplus.com/en/docs/byteplus-vision/FAQ) §3 (2026-09-16) |

**Conclusión:** con OmniHuman no hay nada que «guardar» en BytePlus. Reutilizar la cara significa:
- volver a mandar la misma foto (en R2, servida con URL pública);
- en la 1.5, el mismo `seed` y un prompt de estilo fijo, para que los resultados sean consistentes.

### 1.2 BytePlus Clone Avatar: persistente, sin voz

| Pregunta | Respuesta | Fuente |
|---|---|---|
| ¿Es un avatar persistente con ID? | **Sí.** El entrenamiento (`req_key=realman_avatar_training_task`, `CVSubmitTask`) devuelve `resp_data.resource_id`, «Unique identifier for the corresponding trained Clone Avatar». La generación (`realman_avatar_creation_task`) recibe ese `resource_id` en cada llamada. | [DOC] [create-clone-avatar](https://docs.byteplus.com/en/docs/byteplus-vision/create-clone-avatar) (2026-10-15) · [generate-clone-avatar-video](https://docs.byteplus.com/en/docs/byteplus-vision/generate-clone-avatar-video) (2026-10-15) |
| ¿Cuánto dura? ¿Se puede borrar? | **No documentado.** La página de producto promete «management (addition, deletion, modification, and query) of image resources», pero la API solo documenta enviar, consultar y cancelar tareas. **No hay API para borrar ni listar.** | [DOC] [clone-avatar-onepage](https://docs.byteplus.com/en/docs/byteplus-vision/clone-avatar-onepage) (2026-03-05) |
| ¿Guarda la voz? | **No.** La generación recibe `resource_id` + `audio_url` (mp3/wav) + `templ_start_*` + callback. No tiene parámetro de voz ni de texto. La página de producto dice «Voice Replication: Using Doubao's large speech model…», pero eso describe el producto conjunto con la voz de Doubao (Seed Speech), no un campo de la API. | [DOC] generate-clone-avatar-video · onepage |
| Entrada | Video de entrenamiento: «A 3-5 minute video is recommended (**Must longer than 1 minute**)»; mp4; ≥720p (1080p recomendado); >25 fps; 20–50 Mbps; ≤1 GB. Protocolo de grabación: 10 s en silencio con la boca cerrada y luego 3–5 min leyendo un guion. Cabeza dentro de ±30°. Sin manos cerca de la cara. | [DOC] create-clone-avatar · onepage |
| Salida | Video hablado de hasta **12 min** por sesión. `video_url` válida 1 h. `aigc_meta_tagged` = marca de agua implícita. | [DOC] onepage · generate-clone-avatar-video |
| Movimiento | «Motion Replication: Based on the training videos uploaded by users, replicate the gestures and body movements of the avatar, which will be **randomly played in rotation**». Repite los gestos de su propio video; **no copia un reel externo**. `templ_start_seconds` elige desde qué segundo del video de entrenamiento se empieza. | [DOC] onepage · generate-clone-avatar-video |
| Tiempo de entrenamiento | «3-6 hour fine-tuning» | [DOC] onepage |
| Precio | **300 USD por avatar** (paquete de recursos: «For each resource package purchased, one clone avatar can be created») + **0,015 USD/s** de video generado. Concurrencia 1. Solo se cobra si la llamada sale bien. [PRECIO] | [DOC] onepage |
| Prueba gratuita | En la prueba no se pueden crear avatares. Hay que usar el avatar oficial de prueba `250623-zhibo-linyunzhi`. Si generar video con él durante la prueba se cobra: **no verificado**. | [DOC] onepage |
| ¿Acepta personas reales? ¿Con verificación? | Es su propósito: «a single-person video input is used to create an avatar character». **No hay prueba de vida ni flujo de consentimiento** documentado. Solo hay comprobaciones técnicas del material («ray, face, etc.») y el Content Pre-filter (`50510`). El consentimiento queda como obligación contractual (AUP GenAI; ver [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md) §1.4). | [DOC] onepage · create-clone-avatar (errores) |

**Lectura para Qualify:**
- Clone Avatar es lo más parecido a un Digital Twin de HeyGen, **sin voz y sin consentimiento nativo**.
- Su costo marginal es muy bajo: 0,015 USD/s, unas 8 veces menos que OmniHuman 1.5. Por eso solo compensa con mucho volumen por persona.
- Punto de equilibrio frente a OmniHuman 2.0: 300 / (0,07 − 0,015) ≈ **5.450 s ≈ 91 min** de video por persona. Frente a OmniHuman 1.5: 300 / (0,12 − 0,015) ≈ **48 min**. Es un cálculo.
- Además exige que la persona grabe más de 1 minuto (recomendado 3–5) siguiendo un protocolo de estudio. Eso choca con el flujo de «sube una foto».

### 1.3 Flash Avatar: persistente, entrenamiento corto, precio no publicado

| Afirmación | Fuente |
|---|---|
| Entrenamiento: `req_key=realman_lipsync_training_tob`, `video_url` (mp4/mov, <500 MB, **>3 s, recomendado 10–15 s**, ≥720p, >20 Mbps), `alpha_url` opcional. Devuelve `resource_id`. | [DOC] [Create-Flash-Avatar](https://docs.byteplus.com/en/docs/byteplus-vision/Create-Flash-Avatar) (2026-10-15) |
| «generate a custom digital human in as little as 10 minutes using a 10-15 second training video» | [DOC] [ShootingGuideonFlashAvatar](https://docs.byteplus.com/en/docs/byteplus-vision/ShootingGuideonFlashAvatar) (2026-04-03) |
| Generación: `req_key=realman_lipsync_creation_tob`, `resource_id`, `audio_url` (**<5 min**), `bg_audio_url`, `align_audio_auto` (repite el video de entrenamiento en bucle), `align_audio_reverse` (bucle en vaivén, sin salto de fotogramas), `output_alpha` (0–3, incluido WebM con alfa), `aigc_optimize`. **Sin parámetro de voz.** | [DOC] [generate-flash-avatar-video](https://docs.byteplus.com/en/docs/byteplus-vision/generate-flash-avatar-video) (2026-10-15) |
| Precio | **No publicado** en la documentación ni en la página de producto de OmniHuman (búsqueda del 2026-10-15). **No verificado.** Hay que preguntar a ventas. |

**Lectura (inferencia):**
- Por el `req_key` (`lipsync`) y por `align_audio_auto`, Flash Avatar parece **re-sincronizar los labios sobre el video de entrenamiento en bucle**, no generar movimiento nuevo.
- Sirve para un «presentador fijo» con fondo transparente. No sirve para copiar un reel.

### 1.4 Interactive Avatar (flowact-r2): `role_id` persistente, pero en vivo

| Afirmación | Fuente |
|---|---|
| Paso 1, `req_key=avatar_far2_create_role`, recibe **una imagen** (JPG/PNG <5 MB) y devuelve `resp_data.role_id`. | [DOC] [interactive-avatar-flowact-r2-create-role](https://docs.byteplus.com/en/docs/byteplus-vision/interactive-avatar-flowact-r2-create-role) (2026-08-25) |
| Paso 2: WebSocket `wss://ic-cv-digital-human.byteintlapi.com/virtual_human/avatar_live/live`, con `avatar_type=flowact-r2`, `input_mode=audio`, `role=<role_id>`. Se alimenta con **PCM a 16 kHz** por streaming y emite **por ByteRTC** (`rtc_app_id`, `rtc_room_id`, `rtc_token`). Hay una lista fija de acciones de «live» (saludar, corazón con las manos, pulgar arriba…). | [DOC] [interactive-avatar-flowact-r2](https://docs.byteplus.com/en/docs/byteplus-vision/interactive-avatar-flowact-r2) (2026-08-25) |
| Cuánto dura el `role_id`, precio, si guarda voz | **No documentado.** La entrada es solo audio. |

**Lectura:** es el único «role» persistente a partir de **una sola foto**, pero el producto es una **sesión de directo** (RTC), no un render a MP4. Para reels habría que grabar la salida RTC. **No se recomienda** para este flujo.

### 1.5 ModelArk real-person asset: el «avatar guardado» de Seedance

| Pregunta | Respuesta | Fuente |
|---|---|---|
| ¿Qué es? | Un **asset group** (`GroupType=LivenessFace`, ID `group-…`) creado tras la prueba de vida de la persona, más **assets** (`AssetType=Image\|Video\|Audio`), cada uno con su ID y usado como `asset://<id>`. Seedance 2.0 / 2.5 los acepta como referencia «de confianza». | [DOC] [guide-preview (Private real-human asset library guide, «invited users only»)](https://docs.byteplus.com/en/docs/ModelArk/guide-preview) (2026-10-13) · [get-asset-group-api](https://docs.byteplus.com/en/docs/ModelArk/get-asset-group-api) (2026-09-28) |
| ¿Es el «avatar guardado» para Seedance? | **Sí**, es el único camino documentado para usar una cara real en Seedance 2.x. «Human actors only need to authorize once; subsequent additions of makeup and styling do not require repeating the real-person verification». | [DOC] [upload-real-person-portrait-assets](https://docs.byteplus.com/en/docs/ModelArk/upload-real-person-portrait-assets) (2026-10-13) |
| ¿Se reutiliza en N generaciones? | **Sí.** No hay límite de usos documentado. La propia guía recomienda vigilar `LastInferenceTime` y borrar los assets que no se usen, lo que implica uso repetido. | [DOC] guide-preview |
| ¿Cuánto dura? | **No hay caducidad documentada para el asset ni para el grupo creados por API.** Hay tres matices: (1) en el flujo de **consola con QR** se fija un «**authorization validity period**», y los grupos de consola solo se pueden borrar con la autorización caducada o rechazada; (2) los assets creados **durante un plan Advanced de pago** se **borran 15 días después** de que el plan caduque; (3) los creados en el plan Entry (gratis) o antes del plan de pago no se borran. | [DOC] upload-real-person-portrait-assets · [delete-asset-group-api](https://docs.byteplus.com/en/docs/ModelArk/delete-asset-group-api) (2026-09-28) · [seedance-2-0-purchase-guide](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0-purchase-guide) (2026-09-28) |
| ¿Incluye la voz? | **Incluye un audio de la persona** (wav/mp3, 2–30 s, ≤15 MB), pero Seedance lo usa como **referencia de timbre**: la voz de salida la genera el modelo y puede «differ significantly». **No es el perfil de voz de Seed Speech.** | [DOC] [create-asset-api](https://docs.byteplus.com/en/docs/ModelArk/create-asset-api) (2026-09-28) · [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §1.1 |
| Alta por API | `CreateVisualValidateSession` → `H5Link` (zh/en/zh-Hant, un solo uso) → `GetVisualValidateResult` (`BytedToken` válido 30 min) → `GroupId` → `CreateAsset` (solo por URL, sin Base64) → `GetAsset` hasta `Active`. Firma AK/SK en `ark.ap-southeast-1.byteplusapi.com`, `Version=2024-01-01`. Prueba de vida «free for a limited time». | [DOC] [h5-create-visual-validate-session-api](https://docs.byteplus.com/en/docs/ModelArk/h5-create-visual-validate-session-api) · [asset-group-id-get-visual-validate-result-api](https://docs.byteplus.com/en/docs/ModelArk/asset-group-id-get-visual-validate-result-api) (2026-09-28) |
| Plan | **Basic** (gratis): verificación solo por consola. **Advanced Entry** (gratis): también por API, 50 assets y 50 grupos, 3 QPM en `CreateAsset`. **Advanced**: 1.400 USD/mes o 14.000 USD/año, 1 M de assets y 120 QPM. [PRECIO] | [DOC] seedance-2-0-purchase-guide |
| Obligaciones | Registro de consentimiento (fecha, versión, método; §2.4). Derecho de retirada del consentimiento: si la persona lo retira, hay que dejar de procesar y borrar. El plazo de conservación lo fija y comunica el cliente (nosotros). | [DOC] [Usage Rules H5/API](https://docs.byteplus.com/en/docs/ModelArk/BytePlus_Real_Person_Verification_H5_and_API_Usage_Rules) |
| Gestión | `ListAssetGroups`, `GetAssetGroup`, `UpdateAssetGroup`, `DeleteAssetGroup`, `DeleteAsset`, etc. **Sí hay API de borrado**, a diferencia de Seed Speech y Clone Avatar. Solo funciona sobre recursos de la propia cuenta. | [DOC] guide-preview |

### 1.6 HeyGen Digital Twin, como comparación

| Afirmación | Fuente |
|---|---|
| «Creating a digital twin **clones one voice from the training footage automatically**». Devuelve `avatar_item.id`, `avatar_group.id` y `avatar_item.default_voice_id` (y `avatar_group.default_voice_id`, que tiene prioridad). | [DOC] [avatar-from-video](https://developers.heygen.com/docs/avatar-from-video.md) |
| La voz es «its own resource». No se borra al borrar el avatar; se borra con `DELETE /v3/voices/{voice_id}`. | idem |
| Video de entrenamiento de 15–600 s (~2 min recomendados). Consentimiento obligatorio: enlace de webcam válido 24 h, o video de consentimiento o exención en Enterprise. | idem · [avatar-consent](https://developers.heygen.com/docs/avatar-consent.md) |
| Creación del Digital Twin: **2,13 USD por llamada**. Video Avatar IV Twin: 4,83 USD/min. Avatar V Twin: 7,20 USD/min. Avatar III Twin: 0,60 USD/min. [PRECIO] | [help center de HeyGen](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) (pie: «Last updated on September 16, 2026») |

**Diferencia clave:** HeyGen es el único proveedor revisado que deja **cara + voz + consentimiento** unidos en un mismo objeto suyo. En BytePlus esos tres datos viven en tres productos distintos (Seed Speech, Vision AI y ModelArk), y la unión es nuestra.

---

## 2. ¿Con el mismo perfil de voz?

### 2.1 Dónde vive la voz

- Seed Speech Voice Replication 2.0 (`seed-icl-2.0`) guarda la voz con un `speaker_id`:
  - en postpaid lo elegimos nosotros (`custom_speaker_id`);
  - «no longer incur storage fees or expire» (`ExpireTime: 0`);
  - queda **fija tras la primera síntesis**;
  - **no hay API de borrado ni de exportación**;
  - puede pasar a `Expired` si la cuenta entra en impago.

  Fuentes: [DOC] [voicereplication](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication) y [voicereplicationopenapi](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplicationopenapi) (2026-09-04), resumido en [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md) §3.

### 2.2 ¿Hay un enlace nativo voz ↔ avatar en BytePlus?

**No.** Ningún producto de video acepta un `speaker_id` ni un texto para sintetizar con la voz guardada:

| Producto | Cómo recibe la voz | ¿Acepta `speaker_id` o texto + voz? |
|---|---|---|
| OmniHuman 1.5 / 2.0 | `audio_url` (wav/mp3) | No |
| Clone Avatar | `audio_url` (mp3/wav) | No |
| Flash Avatar | `audio_url` (<5 min) + `bg_audio_url` | No |
| Interactive Avatar | PCM a 16 kHz por WebSocket | No |
| DreamActor M2.0 | **No recibe audio** (solo imagen + video) | No |
| Seedance 2.x + asset | `reference_audio` (timbre); el texto va en el prompt | No: re-sintetiza |

Fuentes: las páginas [DOC] de la §1 y [dreamactor-m2-0-api-document](https://docs.byteplus.com/en/docs/byteplus-vision/dreamactor-m2-0-api-document) (2026-10-15).

**Matiz:** la página de producto de Clone Avatar presenta la voz («Doubao's large speech model») como parte de la solución. Que BytePlus venda un paquete conjunto Clone Avatar + voz con un enlace gestionado por ellos está **no verificado**: la API publicada no lo refleja.

**Conclusión:** la unión se hace en nuestra base de datos. El contrato entre las piezas es el patrón *voice-as-audio* (un MP3 por guion en R2), ya recomendado en [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §6.

---

## 3. ¿Puede el avatar replicar los movimientos de un video de referencia?

### 3.1 OmniHuman: no

- Las entradas de la 1.5 y la 2.0 son imagen + audio + prompt (§1.1). **No hay `video_url` de entrada.**
- La página de producto lo confirma: entradas «a single image, audio, and an optional text prompt». Cámara y gestos se controlan **por prompt**. Fuente: [byteplus.com/en/product/OmniHuman](https://www.byteplus.com/en/product/OmniHuman), consultada el 2026-10-15.
- La guía de la 1.5 documenta coreografía de acciones por texto: «Describe the order of actions using words like 'first' and 'then'…», gestos antes o después de hablar y movimientos de cámara («Pan the camera to the right…»). Fuente: [DOC] [omnihuman1_5overview](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman1_5overview) (2026-01-07).
- **Aproximación posible (inferencia):** describir con nuestro VLM (Qwen3-VL, ya en la cascada de la Fase 1) los movimientos del reel de referencia como un prompt «primero… luego…» y pasárselo a OmniHuman. Es **imitación descrita, no réplica**.

### 3.2 DreamActor M2.0 (BytePlus Vision AI): sí, por API

| Campo | Valor | Fuente |
|---|---|---|
| Qué hace | «By inputting a single image and a template video, it can drive the character in the image to replicate the **motion, facial expressions, and lip movements** from the template video, while preserving the subject and background features of the input image consistently». Multipersona y sujetos no humanos. Reproduce también movimientos de cámara. | [DOC] [dreamactor-m2-0-introduction](https://docs.byteplus.com/en/docs/byteplus-vision/dreamactor-m2-0-introduction) (2026-02-06) |
| Endpoint | `https://cv.byteplusapi.com`, `Action=CVSync2AsyncSubmitTask` / `CVSync2AsyncGetResult`, `Version=2024-06-06`, firma HMAC-SHA256 con AK/SK, `Service=cv`, `Region=ap-singapore-1` | [DOC] [dreamactor-m2-0-api-document](https://docs.byteplus.com/en/docs/byteplus-vision/dreamactor-m2-0-api-document) (2026-10-15) |
| `req_key` | `dreamactor_m20_gen_video_cvtob` | idem |
| Entradas | `image_urls` (1 imagen) o `binary_data_base64`; jpeg/png ≤4,7 MB, 480×480–1920×1080. `video_url` público; mp4/mov/webm, **≤30 s**, 200×200–2048×1440. `cut_result_first_second_switch` (por defecto `true`, recorta 1 s de transición inicial). | idem |
| Salida | MP4 a **720p y 25 fps**, con un aspecto «aim to closely match the input image, but may not be identical». `video_url` válida 1 h. `aigc_meta_tagged`. **RTF ≈18**: unos 3 min por 10 s. | [DOC] introduction · API |
| Audio | **No hay entrada de audio.** Si la salida conserva el audio del reel: **no documentado** (tampoco en fal.ai [2ª]). | [DOC] API · [fal.ai DreamActor v2](https://fal.ai/models/fal-ai/bytedance/dreamactor/v2/llms.txt) [2ª] |
| Precio | **0,05 USD/s, concurrencia 1** [PRECIO]. fal.ai lo revende al mismo precio. | [DOC] introduction · fal.ai [2ª] |
| Caras reales | «Image supports driving for **real people**, animation, pets» y «Driving source: Video (supports **real people**, animation, pets)». No hay prueba de vida ni consentimiento documentados. Único rechazo de contenido: `50510` (Content Pre-filter). | [DOC] introduction · API |
| Activación | «go to Vision AI console to activate the service and collect ak/sk». La consola de Vision AI exige verificación empresarial. Las capacidades que no salen en la consola se piden al equipo comercial. Que DreamActor salga en la consola de nuestra cuenta: **no verificado**. | [DOC] introduction · [FAQ](https://docs.byteplus.com/en/docs/byteplus-vision/FAQ) §1 y §7 |

**Implicaciones para el flujo pedido:**
1. **Los labios salen del reel, no de nuestro guion.** Para que la persona diga *nuestro* texto con *su* voz hace falta un paso de lip-sync sobre la salida de DreamActor, con el MP3 de Seed Speech:
   - HeyGen `POST /v3/lipsyncs` en modo `precision`: 1,74 USD/min;
   - o Sync.so lipsync-2-pro: 0,083 USD/s.

   Ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.11 y §2.13.

   OmniHuman **no sirve** para ese paso porque no acepta video.
2. **Duración:** ≤30 s por llamada, así que un reel más largo hay que trocearlo. Con concurrencia 1 y RTF 18, un reel de 30 s tarda unos 9 min en cola única.
3. **Origen del reel:** los reels de «Descubrir reels» son de terceros. Usarlos como plantilla de movimiento implica:
   - descargarlos y servirlos desde R2, porque DreamActor necesita una URL pública;
   - reproducir la actuación (gestos y expresiones) de otro creador.

   La AUP GenAI de BytePlus prohíbe usar la semejanza de una persona sin consentimiento (citada en [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md) §1.4). Que copiar solo el movimiento esté permitido, y que no haya un problema de derechos de autor sobre el reel, **no está verificado ni es un dictamen legal**. Para la prueba: usar **un reel grabado por el propio fundador** o uno con permiso.

### 3.3 DreamActor M1 / «动作模仿» (Volcengine)

- La noticia de apertura de las APIs de Jimeng/Volcengine incluye «动作模仿 DreamActor M1» para empresas ([oschina](https://www.oschina.net/comment/news/369848) [2ª]).
- El árbol de documentación de **BytePlus** Vision AI (consultado el 2026-10-15) solo tiene **DreamActor M2.0**. No hay página de M1.
- Conclusión: M1 está **no verificado en BytePlus internacional**. Volcengine es la nube china, con otra cuenta y otra jurisdicción. **No se recomienda.**

### 3.4 Seedance 2.x con `reference_video`: copia movimiento, pero no con caras reales

| Afirmación | Fuente |
|---|---|
| Omni reference: «inherit… **subject, camera movement, action performance**, and overall style from reference videos». | [DOC] [seedance-2-0](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0) (2026-09-29) |
| Guía de prompts: «Applicable scenarios: **Action transfer**, subject reuse, atmosphere reference». Plantillas: «Refer to the [Motion Description] from [Video N] to generate [Scene Description], keeping the motion details consistent» y «Refer to the [Camera Movement Description] from [Video N]…». Ejemplo: «refer to the overall camera movement and action rhythm in @Video 1». | [DOC] [seedance-2-0-prompt-guide](https://docs.byteplus.com/en/docs/modelark/seedance-2-0-prompt-guide) (2026-09-28) |
| «Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models **do not support directly uploading reference images or videos that contain real human faces**». | [DOC] [create-video-generation-task-api](https://docs.byteplus.com/en/docs/ModelArk/create-video-generation-task-api) (2026-10-13) |
| Límites del `reference_video`: 2.0, fast y mini, ≤3 clips de 2–15 s y 15 s en total; 2.5, ≤10 clips y 30 s en total. Solo URL o `asset://`. Se cobran los segundos de entrada. | memoria del proyecto (verificada el 2026-10-14) · [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md) §2.4 y §2.6 |

**Lectura:**
- Un reel de un creador con la cara visible da `InputVideoSensitiveContentDetected.PrivacyInformation`.
- La excepción de real-person asset **no lo cubre**: el asset tiene que ser de **la persona verificada**. Un video de otro creador falla la comparación facial («If the material is determined to be a different person, the upload will fail»).
- Que el bloqueo afecte a reels con la cara pequeña, de espaldas o parcial: **no verificado**.
- **Para qué sí sirve:** copiar el movimiento de cámara y el ritmo de reels **sin cara** (producto, manos, plano en primera persona) para el B-roll.

### 3.5 Resumen de productos con movimiento

| Producto | API en BytePlus internacional | `req_key` / modelo | Precio | Límites | ¿Caras reales? |
|---|---|---|---|---|---|
| OmniHuman 1.5 | Sí (Vision AI) | `realman_avatar_picture_omni15_cv` | 0,12 USD/s | audio <60 s; concurrencia 1 | Sí según la documentación; **no verificado en vivo** |
| OmniHuman 2.0 | Sí (Vision AI) | `realman_avatar_picture_omni20_cv` | 0,07 o 0,12 USD/s (qué tarifa aplica: **no verificado**) | audio 4–300 s | idem |
| **DreamActor M2.0** | **Sí** (Vision AI) | `dreamactor_m20_gen_video_cvtob` | **0,05 USD/s** | video ≤30 s; 720p a 25 fps; concurrencia 1 | **Sí**, imagen y video de origen |
| DreamActor M1 | **No documentado** (solo Volcengine) | — | — | — | — |
| Seedance 2.0 mini (`reference_video`) | Sí (ModelArk) | `dreamina-seedance-2-0-mini-260615` | 0,045 USD/s de entrada + salida (con video) | ≤15 s de referencia | **No** (salvo asset de la persona verificada) |
| Seedance 2.5 (`reference_video`) | Sí (ModelArk; requiere paquete de recursos) | `dreamina-seedance-2-5-260628` | 0,138 USD/s de entrada + salida a 720p | ≤30 s | **No** (idem) |
| Clone Avatar | Sí (Vision AI) | `realman_avatar_training_task` / `realman_avatar_creation_task` | 300 USD + 0,015 USD/s | entrenamiento >1 min | Sí, sin verificación nativa |

---

## 4. Tabla de productos: persistencia y voz

| Producto | Plataforma | ¿Objeto persistente? | ID | ¿Guarda voz? | ¿Copia movimiento de un reel? | Alta de la persona | Costo fijo | Costo variable | ¿Borrado por API? |
|---|---|---|---|---|---|---|---|---|---|
| OmniHuman 1.5 / 2.0 | Vision AI | **No** | — (solo `seed` en 1.5) | No | No (solo prompt) | 1 foto | 0 | 0,07–0,12 USD/s | n/a |
| Clone Avatar | Vision AI | **Sí** | `resource_id` | No | No (sus propios gestos) | video >1 min (3–5 min recomendado) | **300 USD por avatar** | 0,015 USD/s | **No documentado** |
| Flash Avatar | Vision AI | **Sí** | `resource_id` | No | No (lip-sync en bucle, inferencia) | video de 10–15 s | **no publicado** | **no publicado** | No documentado |
| Interactive Avatar flowact-r2 | Vision AI | **Sí** | `role_id` | No | No | 1 foto | no publicado | no publicado | No documentado |
| DreamActor M2.0 | Vision AI | **No** | — | No (sin entrada de audio) | **Sí** (≤30 s) | 1 foto | 0 | 0,05 USD/s | n/a |
| Real-person asset | ModelArk | **Sí** | `group-…` + `asset://…` | Audio solo como timbre | Sí, pero con video de la **misma** persona | prueba de vida H5 + materiales | 0 (Entry, 50 assets) | tokens de Seedance | **Sí** |
| Seed Speech `seed-icl-2.0` | BytePlus Voice | **Sí** (la voz) | `speaker_id` | **Sí** | n/a | muestra de 10–30 s | 2 USD por voz | 30 USD por M de caracteres | **No** |
| HeyGen Digital Twin | HeyGen | **Sí** | `avatar_id` + `avatar_group_id` + `default_voice_id` | **Sí, juntos** | No | video de 15–600 s + consentimiento por webcam | 2,13 USD por twin | 0,60–7,20 USD/min | Sí (voz y avatar) |

---

## 5. Modelo de datos propuesto (mínimo)

**Principios:**
- Una fila por **persona de la marca**: es la «identidad» reutilizable.
- Los IDs de cada proveedor en filas aparte, porque una persona puede tener varios a la vez: un `speaker_id`, un `group-…` con N assets y, quizá, un `resource_id` de Clone Avatar.
- La voz **no se duplica**: se reutiliza la tabla `brand_voice_clones` de la migración 0032, con las columnas `provider` / `external_voice_id` / `consent_id` que ya propone [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md) §6.
- RLS en las dos tablas nuevas, con la política `NULLIF(current_setting('app.tenant_id', true), '')::uuid` de 0001.
- Procedencia en cada render (`CLAUDE.md`, regla de procedencia).

**Esquema (borrador para el arquitecto, no es una migración):**

```sql
-- Who: the person whose face and voice the brand may use.
CREATE TABLE brand_avatars (
  id                uuid PRIMARY KEY,
  tenant_id         uuid NOT NULL REFERENCES tenants(id),
  brand_id          uuid NOT NULL REFERENCES brands(id),
  display_name      text NOT NULL,
  photo_key         text NOT NULL,      -- R2: normalized front-facing photo (OmniHuman/DreamActor input)
  photo_sha256      text NOT NULL,
  voice_clone_id    uuid REFERENCES brand_voice_clones(id),  -- the SAME voice profile (Seed Speech speaker_id lives there)
  default_seed      integer,            -- OmniHuman 1.5 reproducibility
  default_prompt    text,               -- persona style prompt (gestures/framing)
  consent_text_version text NOT NULL,
  consent_evidence_key text NOT NULL,   -- R2: signed consent / read-aloud authorization clip
  consent_by        uuid NOT NULL REFERENCES users(id),
  consent_at        timestamptz NOT NULL,
  withdrawn_at      timestamptz,        -- consent withdrawal => stop + delete at providers (Usage Rules §(4))
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Where: every external object that represents this person at a provider.
CREATE TABLE brand_avatar_provider_refs (
  id               uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES tenants(id),
  avatar_id        uuid NOT NULL REFERENCES brand_avatars(id),
  provider         text NOT NULL,  -- 'byteplus_ark' | 'byteplus_vision' | 'heygen'
  kind             text NOT NULL,  -- 'asset_group' | 'asset_image' | 'asset_video' | 'asset_audio'
                                   -- | 'clone_avatar' | 'flash_avatar' | 'interactive_role' | 'heygen_twin'
  external_id      text NOT NULL,  -- group-…, asset-…, resource_id, role_id, avatar_id
  parent_ref_id    uuid REFERENCES brand_avatar_provider_refs(id),  -- asset -> its asset_group
  source_media_key text,           -- R2 object it was created from
  status           text NOT NULL,  -- 'pending' | 'active' | 'failed' | 'retired'
  authorization_expires_at timestamptz,  -- console-flow assets; paid-plan reclamation
  last_used_at     timestamptz,
  retired_at       timestamptz,
  metadata         jsonb NOT NULL DEFAULT '{}',
  UNIQUE (provider, external_id)
);
```

**Lo que este esquema no decide, y debe decidir el arquitecto:**
- `brand_voice_clones` hoy tiene `UNIQUE(brand_id)`. Con varias personas por marca, la voz tiene que ser **por persona**, no por marca.
- Los renders (`template_runs`, `image_assets` o la tabla que use el generador) deben guardar como procedencia: `avatar_id`, `voice_clone_id`, `speaker_id` en el momento del render, proveedor, `req_key`, `task_id`, `seed`, `prompt` y la clave R2 del MP3. La regla de procedencia del proyecto lo exige.
- La revisión iría después de la cabeza actual, que en este worktree es `0061`.

**Dónde vive cada pieza:**

| Pieza | R2 | Postgres | BytePlus / HeyGen |
|---|---|---|---|
| Foto de la persona | **sí** (`photo_key`) | clave + sha256 | no se guarda (OmniHuman y DreamActor la reciben por URL) |
| Muestra de voz y evidencia de consentimiento | **sí** | claves + texto y versión del consentimiento | la muestra se envía a Seed Speech (cuánto la retienen: **no documentado**) |
| Perfil de voz | — | `brand_voice_clones.external_voice_id` | **Seed Speech `speaker_id`** (permanente, sin borrado) |
| MP3 de cada guion | **sí** (clave idempotente) | clave en el render | — |
| Real-person asset group y assets | material de origen en R2 | `brand_avatar_provider_refs` | **ModelArk** (`group-…`, `asset://…`) |
| Clone Avatar (si se compra) | video de entrenamiento | `provider_refs` | **Vision AI `resource_id`** |
| Salidas de OmniHuman, DreamActor y Seedance | **sí, copiadas enseguida** (URL de 1 h en Vision AI, de 24 h en ModelArk) | metadatos y procedencia | caducan |
| Reel de referencia (movimiento) | **sí** (DreamActor necesita URL pública) | clave + origen (URL del reel, autor) | — |

---

## 6. Plan de prueba de la suite

### 6.1 Diagrama del flujo de datos

```
                      [R2] foto.jpg      [R2] muestra_voz.wav + consentimiento
                            |                         |
                            |                         v
                            |            (1) Seed Speech voice_clone
                            |                         |
                            |              [BytePlus] speaker_id  ---> [Postgres] brand_voice_clones
                            |                         |
                            |           guion ------> (2) TTS seed-icl-2.0
                            |                         |
                            |                   [R2] guion.mp3  ---> [Postgres] render.audio_key
                            |                         |
           +----------------+-----------+             |
           |                            |             |
           v                            v             v
 (3a) OmniHuman 1.5/2.0         (3b) DreamActor M2.0          [R2] reel_ref.mp4 (<=30 s)
      foto + mp3 + prompt            foto + reel_ref.mp4 <---------------+
           |                            |
           |                            v
           |                   clip con movimientos y labios del reel
           |                            |
           |                            v
           |                   (3c) lip-sync con guion.mp3
           |                        (HeyGen Lipsync / Sync.so)
           v                            v
     [R2] clip_hablado.mp4  <-----------+          (URL del proveedor: 1 h -> copiar ya)
           |
           |      (4) Seedance 2.0 mini / 2.5: B-roll / escena SIN cara
           |          (texto, imagen de producto, reference_video sin cara)
           |          o con asset://persona (real-person asset de ModelArk)
           |                            |
           |                     [R2] broll_*.mp4
           |                            |
           +------------+---------------+
                        v
          (5) montaje Remotion/ffmpeg con la pista guion.mp3 original
                        |
                 [R2] reel_final.mp4 + etiqueta "generado con IA"
                        |
          [Postgres] render: avatar_id, voice_clone_id, speaker_id,
                     proveedor, req_key, task_id, seed, prompt, claves R2
```

### 6.2 Credenciales y activaciones

Variables que existen hoy en `.env` del checkout principal (solo nombres):
- `QUALIFY_BYTEPLUS_ARK_API_KEY`, `QUALIFY_BYTEPLUS_ARK_BASE_URL`
- `QUALIFY_HEYGEN_API_KEY`
- `QUALIFY_R2_ENDPOINT_URL`, `QUALIFY_R2_ACCESS_KEY_ID`, `QUALIFY_R2_SECRET_ACCESS_KEY`, `QUALIFY_R2_BUCKET`
- y otras sin relación: Meta, Supabase, ScrapeCreators, Langfuse.

**Faltan:**
- **AK/SK de BytePlus.** Nombres propuestos: `QUALIFY_BYTEPLUS_AK` / `QUALIFY_BYTEPLUS_SK`. Los necesitan OmniHuman, DreamActor, Clone Avatar y la API de assets.
- **API key de Seed Speech.** Nombre propuesto: `QUALIFY_BYTEPLUS_SPEECH_API_KEY`.

| # | Paso administrativo | Para qué | Costo | Fuente |
|---|---|---|---|---|
| A1 | **Verificación empresarial** de la cuenta BytePlus | Activar Vision AI. También vale para crear grupos de real-person asset en consola | 0 | [DOC] FAQ §7 · upload-real-person-portrait-assets |
| A2 | Subusuario IAM con AK/SK. Políticas: `CVFullAccess` (Vision AI) y la de Ark para la API de assets | Firmar las llamadas a `cv.byteplusapi.com` y `ark.ap-southeast-1.byteplusapi.com` | 0 | [DOC] FAQ §6 |
| A3 | Vision AI → activar **OmniHuman 1.5 / 2.0** y **DreamActor M2.0**. Si DreamActor no sale en la consola, pedirlo a ventas | — | 0 de activación (saldo mínimo de Vision AI: **no verificado**) | [DOC] FAQ §1 · dreamactor-m2-0-introduction |
| A4 | Seed Speech: activar Voice Replication 2.0 y crear la API key | Clonar y sintetizar | Prueba gratuita de 20.000 caracteres y 10 voces | [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md) §2 |
| A5 | ModelArk: activar **Seedance 2.0 mini** | B-roll y escenas con asset | **≥30 USD** en Credits, AI Savings Plan o paquete de recursos (2.5 exige paquete de recursos). **Ojo: los Credits «cannot be withdrawn»**: es un prepago no reembolsable, utilizable solo en BytePlus | [DOC] [seedance-model-activation-usage-and-refund](https://docs.byteplus.com/en/docs/ModelArk/seedance-model-activation-usage-and-refund) (2026-10-08) |
| A6 | Plan **Advanced Creation Rights (Entry)**, aceptando los textos legales | Usar la API de assets (el plan Basic es solo consola) | 0 | [DOC] seedance-2-0-purchase-guide |
| A7 | Sujeto de prueba: **el propio fundador** (su cara, su voz, su prueba de vida). Reel de referencia: **uno grabado por él** o uno con permiso | Evitar terceros sin consentimiento | 0 | — |

### 6.3 Pruebas, en orden

Supuestos: clips de 10 s a 720p, sin reintentos.

| # | Prueba | Qué confirma | Costo estimado |
|---|---|---|---|
| T1 | Seed Speech: `voice_clone` con 20 s del fundador leyendo una frase de autorización (`text`), y TTS de un guion de 10 s a MP3 → R2 | Calidad de la voz en es-MX; que el `speaker_id` sirva en síntesis repetidas | **0** dentro de la prueba gratuita. Fuera de ella: 2 USD de voz + ≈0,005 USD |
| T2 | OmniHuman 1.5: foto + MP3 de 10 s, `seed` fijo, prompt con gestos | Cara real aceptada, lip-sync en español, consistencia con el mismo `seed` (repetir 2 veces) | 2 × 10 × 0,12 = **2,40 USD** |
| T2b | OmniHuman 2.0: la misma foto + el mismo MP3 | Comparar con la 1.5; ver qué tarifa cobra (0,07 o 0,12) | **0,70–1,20 USD** |
| T3 | **DreamActor M2.0**: foto + reel de referencia de 10 s → R2. `ffprobe`: ¿hay pista de audio? | Que copie el movimiento con una cara real; que conserve la identidad de la foto; audio de salida | 10 × 0,05 = **0,50 USD** |
| T3b | Lip-sync de la salida de T3 con el MP3 de T1: HeyGen Lipsync Precision (A/B opcional con Sync lipsync-2-pro) | Que el lip-sync con nuestra voz funcione sobre DreamActor | HeyGen: 10/60 × 1,74 ≈ **0,29 USD** · Sync: 10 × 0,083 ≈ 0,83 USD |
| T4 | Seedance 2.0 mini: B-roll **sin cara** de 5 s, (a) solo texto e imagen de producto y (b) `reference_video` = un reel sin cara (movimiento de cámara) | B-roll y copia de cámara sin moderación de caras | (a) 5 × 0,076 ≈ **0,38 USD** · (b) (5 + 5) × 0,045 ≈ **0,45 USD** |
| T4b | Seedance 2.0 mini con un reel **con** cara de tercero como `reference_video` | Confirmar el rechazo `PrivacyInformation` (síncrono o asíncrono) | **0** si rechaza («only charged for successfully generated videos», [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §1.6) |
| T5 (opcional) | Real-person asset: H5 del fundador → `GroupId` → `CreateAsset` (imagen + audio de 10 s sintetizado en T1) → Seedance 2.0 mini `reference` de 5 s con `asset://` y la frase entre comillas | El «avatar guardado» de Seedance; reutilizarlo en 2 generaciones; parecido de timbre | 0 (verificación gratis) + 2 × 0,38 ≈ **0,76 USD** |
| T6 | Montaje: clip de T2 o de T3b + B-roll de T4 + pista MP3 original (ffmpeg/Remotion) | Sincronía final y deriva | **0** |
| T7 (aplazar) | Clone Avatar: primero el avatar de prueba `250623-zhibo-linyunzhi` con nuestro MP3; solo si T2 o T3 fallan en calidad, comprar 1 avatar | Calidad de un avatar entrenado frente a OmniHuman | Prueba: **no verificado** si cuesta (0,015 USD/s fuera de la prueba) · compra: **300 USD** |
| T8 (aplazar) | Flash Avatar | — | Pedir el precio a ventas antes |

**Total de uso (T1–T6, sin opcionales):** **≈4,7–5,2 USD** (0 + 2,40 + 0,70–1,20 + 0,50 + 0,29 + 0,38 + 0,45 + 0 + 0):
- más los **30 USD prepago** de Seedance (no reembolsables, pero se consumen en las pruebas siguientes);
- más 2 USD de voz si se sale de la prueba gratuita.

Con T5: **≈5,5–6,0 USD**. Clone Avatar (300 USD) **no** entra en la primera ronda.

**Orden recomendado y criterios de corte:**
1. A1–A7 (administrativo).
2. **T1**: sin la voz no hay nada que unir.
3. **T2 / T2b**: el avatar hablado base. Si OmniHuman rechaza la cara real (`50510`), se pasa a HeyGen Digital Twin o Avatar IV como plan B (la key ya existe).
4. **T3 + T3b**: la pregunta de movimiento. Si DreamActor no conserva la identidad o el lip-sync posterior falla, la réplica de movimiento queda como «imitación por prompt» (§3.1).
5. **T4 / T4b**: B-roll y confirmación del bloqueo de caras.
6. **T6**: montaje.
7. T5 solo si se quiere a la persona **dentro** de escenas de Seedance.
8. T7 y T8 solo con volumen que lo justifique (Clone Avatar compensa a partir de ~48–91 min de video por persona, §1.2).

**Qué medir en cada salida:**
- `ffprobe`: duración, fps, pistas de audio;
- parecido facial con la foto (revisión visual; más adelante, el embedding facial de la cascada);
- sincronía labios-MP3;
- consistencia entre dos renders con el mismo `seed` / asset;
- costo real (`usage` en ModelArk; facturación en Vision AI).

### 6.4 Preguntas a ventas o soporte de BytePlus

1. ¿Clone Avatar tiene API para borrar y listar `resource_id`? ¿Cuánto dura el avatar? ¿Se vende junto a la voz de Seed Speech con un enlace gestionado por ellos?
2. ¿Precio de Flash Avatar y de Interactive Avatar? ¿Cuánto duran el `resource_id` y el `role_id`?
3. ¿DreamActor M2.0 se activa en autoservicio o hay que pedirlo? ¿La salida conserva el audio del video plantilla?
4. ¿Hay alguna regla interna contra usar como plantilla de movimiento el video de **otra** persona (reel de un tercero)?
5. ¿La API de assets (plan Entry) está abierta o es «invited users only», como dice el título de la guía?
6. ¿Cuánto retiene Seed Speech la muestra de voz? ¿Ofrecen borrado de `speaker_id` bajo petición?

---

## 7. Lo que queda «no verificado»

1. Que OmniHuman y DreamActor acepten en la práctica la cara real del fundador con el pre-filtro activado (T2, T3).
2. Que DreamActor esté en autoservicio en la consola y que su salida conserve el audio del reel.
3. Calidad del lip-sync (HeyGen o Sync) sobre una salida de DreamActor en español (T3b).
4. Tarifa efectiva de OmniHuman 2.0 (0,07 o 0,12 USD/s).
5. Precio, duración y API de borrado de Flash Avatar, Interactive Avatar y Clone Avatar.
6. Si generar video con el avatar de prueba de Clone Avatar se cobra durante la prueba gratuita.
7. Que DreamActor M1 o «动作模仿» exista en BytePlus internacional (solo consta en Volcengine).
8. Que el bloqueo de caras de Seedance afecte a reels con la cara parcial o pequeña.
9. Saldo mínimo, si lo hay, para activar Vision AI.
10. Si el uso de reels de terceros como plantilla de movimiento es conforme a la AUP y a los derechos de autor. **No es un dictamen legal.**

## Fuentes (consultadas el 2026-10-15)

**BytePlus Vision AI [DOC]:**
- Clone Avatar OnePage (2026-03-05): https://docs.byteplus.com/en/docs/byteplus-vision/clone-avatar-onepage
- Create Clone Avatar (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/create-clone-avatar
- Generate Clone Avatar video (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/generate-clone-avatar-video
- Create Flash Avatar (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/Create-Flash-Avatar
- Generate Flash Avatar video (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/generate-flash-avatar-video
- Shooting Guide on Flash Avatar (2026-04-03): https://docs.byteplus.com/en/docs/byteplus-vision/ShootingGuideonFlashAvatar
- Interactive Avatar, Create Role (2026-08-25): https://docs.byteplus.com/en/docs/byteplus-vision/interactive-avatar-flowact-r2-create-role
- Interactive Avatar, Stream Interface (2026-08-25): https://docs.byteplus.com/en/docs/byteplus-vision/interactive-avatar-flowact-r2
- DreamActor M2.0 Introduction (2026-02-06): https://docs.byteplus.com/en/docs/byteplus-vision/dreamactor-m2-0-introduction
- DreamActor M2.0 API (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/dreamactor-m2-0-api-document
- OmniHuman 1.5 API (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-video_generation
- OmniHuman 2.0 API (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation
- OmniHuman 1.5 Overview (2026-01-07): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman1_5overview
- Subject Recognition (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-subject_recognition
- Vision AI FAQ (2026-09-16): https://docs.byteplus.com/en/docs/byteplus-vision/FAQ
- Página de producto OmniHuman [PRECIO]: https://www.byteplus.com/en/product/OmniHuman

**BytePlus ModelArk [DOC]:**
- Private real-human asset library guide (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/guide-preview
- Add real-human assets (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/upload-real-person-portrait-assets
- CreateAsset (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/create-asset-api
- GetAssetGroup (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/get-asset-group-api
- DeleteAssetGroup (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/delete-asset-group-api
- CreateVisualValidateSession (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/h5-create-visual-validate-session-api
- GetVisualValidateResult (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/asset-group-id-get-visual-validate-result-api
- Advanced Creation Rights purchase guide (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0-purchase-guide
- Real Person Verification H5/API Usage Rules: https://docs.byteplus.com/en/docs/ModelArk/BytePlus_Real_Person_Verification_H5_and_API_Usage_Rules
- Copyright and Portrait Feature Usage Rules: https://docs.byteplus.com/en/docs/ModelArk/copyright_and_portrait_feature_usage_rules
- Activate, use, and cancel Seedance models (2026-10-08): https://docs.byteplus.com/en/docs/ModelArk/seedance-model-activation-usage-and-refund
- Seedance 2.0 series tutorial (2026-09-29): https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0
- Seedance 2.0 prompt guide (2026-09-28): https://docs.byteplus.com/en/docs/modelark/seedance-2-0-prompt-guide
- Create a video generation task (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/create-video-generation-task-api

**BytePlus Voice [DOC]:**
- Voice Replication, guía de pedido y uso: https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication
- Management APIs: https://docs.byteplus.com/en/docs/byteplusvoice/voicereplicationopenapi

**HeyGen:**
- Avatar from video (Digital Twin) [DOC]: https://developers.heygen.com/docs/avatar-from-video.md
- Avatar consent [DOC]: https://developers.heygen.com/docs/avatar-consent.md
- API pricing [PRECIO] (pie: 2026-09-16): https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained

**Terceros [2ª]:**
- fal.ai, DreamActor v2: https://fal.ai/models/fal-ai/bytedance/dreamactor/v2/llms.txt
- OSChina, apertura de APIs de Jimeng/Volcengine (DreamActor M1): https://www.oschina.net/comment/news/369848
