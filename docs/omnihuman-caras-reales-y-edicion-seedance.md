# OmniHuman con la cara de una persona real y edición posterior con Seedance

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN 2026-10-15]` · fuentes consultadas el 2026-10-15 · **sin llamadas en vivo ni de pago**

Marcas: **[DOC]** documentación oficial de BytePlus (Markdown extraído de `window._ROUTER_DATA…curDoc.MDContent`; se indica la fecha de última actualización de cada página) · **[2ª]** tercero · **no verificado** = no confirmado en fuente primaria · **inferencia** = deducción nuestra a partir de fuentes primarias.

Contexto previo, que este documento amplía sin repetir:
- [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md)
- [investigacion-caras-reales-video-ia.md](investigacion-caras-reales-video-ia.md)
- [costos-comparativos-herramientas-ia.md](costos-comparativos-herramientas-ia.md)

Motor de compra que sirve: **activación** (la marca produce reels con la cara de su cliente o creador). No toca la escucha. Fase del roadmap: dogfooding del generador creativo (Parte 4-A, ADR 21). Es infraestructura comprada, no construida.

---

## Resumen: respuesta directa

### A. ¿OmniHuman acepta fotos de personas reales?

**Sí, según toda la documentación. Nadie lo ha verificado en vivo.**

- El producto se llama `realman_avatar_…` y se describe como «single image + audio» de «people or other subjects».
- Vision AI **no documenta ningún error de «persona real»**. Ni las páginas de OmniHuman 1.5 o 2.0, ni los códigos comunes, ni el pre-filtro tienen un equivalente a `PrivacyInformation` de Seedance.
- El único rechazo de contenido documentado es `50510 Algovproxy Risk Error`, que cubre:
  - menores;
  - odio;
  - desnudos y violencia;
  - desinformación.
- **El Content Pre-filter de Vision AI se puede desactivar desde la consola.** Aun así, quedan unas «baseline content safety policies» sin especificar.
- **No hay verificación, prueba de vida ni flujo de *real-person asset*** en Vision AI. El consentimiento es solo contractual:
  - la AUP GenAI prohíbe representar la imagen o la voz de una persona «without appropriate consent»;
  - también prohíbe quitar marcas de agua.
- **El filtro de figuras públicas documentado es el de ModelArk**, que analiza las salidas de Seedance y Seedream. En la documentación de Vision AI no aparece. Si OmniHuman tiene uno, **no está verificado**.
- **Terceros:**
  - Hedra y evolink [2ª] dicen que funciona con «real portraits» o «real people».
  - fal.ai y Hedra no documentan ninguna moderación de caras.
  - ElevenLabs traslada la responsabilidad al usuario y aplica las políticas del proveedor del modelo.

### B. ¿Se puede editar o extender con Seedance el video de OmniHuman?

**Directamente, no. Por la vía del real-person asset, en principio sí, pero hay que probarlo.**

1. **Como referencia directa (URL), lo más probable es que Seedance lo rechace.**
   - Seedance 2.x rechaza imágenes y videos de referencia con caras humanas reales: `InputVideoSensitiveContentDetected.PrivacyInformation`.
   - **La excepción de «outputs de confianza» no incluye OmniHuman.** Cubre solo:
     - videos de Seedance 2.0/2.5;
     - el último fotograma de esos videos;
     - imágenes t2i de Seedream 5.0.
   - Y la propia documentación lo excluye de forma literal: *«Only outputs from the ModelArk platform are trusted; cross-platform use is not supported.»* OmniHuman vive en Vision AI, otra plataforma.
   - Que el detector marque concretamente un video de OmniHuman es **no verificado** (inferencia fuerte).
2. **Sí existe una vía documentada: subir el video de OmniHuman como asset de video al grupo de la persona verificada.**
   - Pasos: prueba de vida de la persona (H5) → `CreateAsset` con `AssetType=Video` y un video de 2–30 s → chequeo de consistencia facial → `asset://…` como `reference_video`.
   - La documentación permite subir «image, video, and audio» de la persona. Lo sube el cliente de BytePlus (nosotros) por API, y el único control es la comparación facial.
   - **No verificado:** que un video generado por IA a partir de su foto pase esa comparación y no choque con alguna regla no publicada.
3. **Los tres modos sirven, pero la duración limita.**
   - **Modos:**
     - `edit`: cambiar el fondo, añadir el producto;
     - `extend`: alargar hacia delante o hacia atrás;
     - `reference`: escena nueva con la persona.
   - **Límites de duración:**
     - 2.0 / fast / mini: hasta 15 s de video de referencia en total;
     - 2.5: hasta 30 s (edit: 4–30 s);
     - asset: 2–30 s por video.
   - **OmniHuman puede generar más que eso:** <60 s en 1.5 y hasta 300 s en 2.0. **Para editar, hay que trocear.**
4. **Lip-sync y voz: no garantizados.**
   - **Lo documentado:**
     - con `generate_audio=true`, Seedance **genera** el audio (voz, efectos y música) y siempre en mono;
     - con `false`, la salida es muda;
     - en edit, la salida puede ser **hasta 0,4 s más corta** que la entrada;
     - en extend, la salida «usually only includes the tail» del original.
   - **No documentado:** ningún parámetro para conservar el audio original. Que el edit respete la boca fotograma a fotograma es **no verificado**.
   - **Pipeline seguro:** `generate_audio=false` y volver a montar el WAV original con ffmpeg, midiendo la deriva.
5. **Costo:** con video de entrada se cobran los segundos de entrada más los de salida, aunque a una tarifa por token más baja. Ver la tabla de la sección 5.

**Pipeline recomendado (a):**
- OmniHuman (o HeyGen) **solo para los planos hablados**, sin editarlos.
- Seedance **solo para planos sin la persona** (producto, local), que no activan la moderación de caras.
- Montaje en Remotion o ffmpeg con la pista de voz original.
- Coste: **≈1,9–4,9 USD por reel de 30 s** sin reintentos (≈1,3–1,6 USD con HeyGen en lugar de OmniHuman).
- La vía de edición con real-person asset (a′) cuesta 2–5 veces más y depende de dos supuestos sin verificar. Queda como experimento.

---

## 1. Evidencia A: OmniHuman y caras reales

### 1.1 Qué dice la documentación de OmniHuman

| Afirmación | Fuente |
|---|---|
| 1.5: «generate a video based on a single image + audio… images of any frame size… that contain **people** or other subjects (pets, animations, etc.)». | [DOC] [omnihuman1_5overview](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman1_5overview) (act. 2026-01-07) |
| 1.5, entradas: JPG/PNG <5 MB, <4096²; audio **<60 s** («If the audio exceeds 60 seconds, an error will be generated»); prompt en zh/en/ja/ko/**es-MX**/id. | [DOC] [omnihuman-video_generation](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-video_generation) (act. **2026-10-15**) |
| 1.5, salida: MP4 720p/1080p (1080p por defecto), RTF 27 (1080p) / 23 (720p); **0,12 USD/s, concurrencia 1**. | [DOC] overview 1.5 |
| 2.0, entradas: imagen hasta 30 MB, aspecto 0,4–2,5, 300–6000 px; audio **4–300 s**, wav/mp3, <15 MB; `image_urls` (array); **`enable_watermark`, activado por defecto**. | [DOC] [omnihuman-2-0-video-generation](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation) (act. **2026-10-15**) |
| 2.0, página de producto: «native 720p», «30s to 300s Video Output», «$0.07 per second» (tier de cámara y cuerpo) y «$0.12 per second» (tier de lip sync). **Cuál de los dos tiers se aplica al `req_key` `omni20`: no verificado.** | [byteplus.com/en/product/OmniHuman](https://www.byteplus.com/en/product/OmniHuman) |
| La URL del video de salida **caduca en 1 h**; la tarea, en 12 h. | [DOC] API 1.5/2.0 · [FAQ](https://docs.byteplus.com/en/docs/byteplus-vision/FAQ) (act. 2026-09-16) |
| Subject Recognition (`realman_avatar_picture_create_role_omni_cv`) solo comprueba si hay un sujeto humano o humanoide (`status` 0/1). **No es un control de identidad.** | [DOC] [omnihuman-subject_recognition](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-subject_recognition) (act. 2026-10-15) |

### 1.2 Códigos de error: no hay ninguno de «persona real»

- **Errores de negocio de OmniHuman 1.5 y 2.0** ([DOC], páginas de la API):
  - `50429` QPS;
  - `50430` concurrencia;
  - `50500` / `50501` internos;
  - **`50510 Algovproxy Risk Error` = «Content Pre-filter failed»**.
- **Errores comunes de Vision AI** ([DOC] [common-responses-and-error-codes](https://docs.byteplus.com/en/docs/byteplus-vision/docs-common-responses-and-error-codes), act. 2025-10-14):
  - `50200`–`50207`: parámetros e imagen;
  - `50400`: auth;
  - `50402`: servicio inexistente;
  - `50429`, `50500`, `50501`.
- **Ninguno menciona privacidad, cara, persona real ni prueba de vida.**
- Para comparar, ModelArk sí los tiene:
  - `InputImageSensitiveContentDetected.PrivacyInformation`: «the input image may contain real person»;
  - su equivalente `InputVideo…`.
  - Fuente: [DOC] [ModelArk error-codes](https://docs.byteplus.com/en/docs/ModelArk/error-codes) (act. 2026-10-06).

### 1.3 Content Pre-filter de Vision AI

Fuente: [DOC] [vision-ai-content-pre-filter](https://docs.byteplus.com/en/docs/byteplus-vision/vision-ai-content-pre-filter) (act. 2025-12-26).

- **Categorías:** Minor Safety, Hate Speech, Nudity/Sexual/Graphic, Misinformation. **No incluye «persona real» ni «figura pública».**
- **Se activa y desactiva** por servicio en *Console → Overview → Activated API List*. Viene activado por defecto.
- **Aunque se desactive:** «our services still maintain baseline content safety policies». Esa base no está publicada.
- **Datos:** los logs y el contenido filtrado se guardan «for a limited period» en Malasia o Singapur.

### 1.4 AUP, términos y activación

- **[DOC] [AUP GenAI](https://docs.byteplus.com/en/docs/legal/acceptable_use_policy_byteplus_genai)** (act. 2026-08-31). Prohíbe:
  - «to depict a person (living or dead)'s voice or likeness **without appropriate consent or rights**…»;
  - tratar datos biométricos sin consentimiento o base legal;
  - «delete, remove, obscure, alter or conceal any… watermarks… that indicate that the content may be generated by a BytePlus GenAI Service».

  **Implicación (inferencia):** si un video de OmniHuman 2.0 con marca de agua pasa por Seedance edit y la marca desaparece, eso podría leerse como «alterar» la marca. Para evitarlo, generar con `enable_watermark=false`, un parámetro documentado, y añadir nuestro propio etiquetado de IA (C2PA o aviso visible).
- **[DOC] FAQ de Vision AI §7:** «An enterprise-verified account is required to activate the service».
- **No existe un flujo de real-person asset en Vision AI.** No aparece en la API de 1.5 ni de 2.0, ni en la FAQ ni en el pre-filtro. El único flujo de verificación de BytePlus está en ModelArk y se limita a Seedance 2.0/2.5. Ver la sección 2.3.

### 1.5 Terceros que revenden OmniHuman 1.5

| Revendedor | Qué dice sobre personas reales | Precio | Fuente |
|---|---|---|---|
| fal.ai (`fal-ai/bytedance/omnihuman/v1.5`) | «an image of a human figure»; sin mención de consentimiento ni moderación | 0,16 USD/s | [fal.ai](https://fal.ai/models/fal-ai/bytedance/omnihuman/v1.5) [2ª] |
| Hedra | Página del modelo: sin mención de consentimiento ni moderación; solo 16:9; 720p/1080p. Página «talking photo»: acepta **«real portraits»**, ilustraciones, imágenes de IA… | 0,16 USD/s | [hedra/omnihuman-15](https://mkt.hedra.com/models/video/bytedance/omnihuman-15) · [hedra talking-photo](https://hedra.com/uses/talking-photo-ai) [2ª] |
| ElevenLabs | Creative Terms §2: si el input contiene la imagen de una persona identificable, el usuario garantiza tener «all consents… required under applicable law», incluido el tratamiento por «any AI Model Provider»; guardar registros 5 años. §1.3: las políticas del proveedor del modelo también aplican. No menciona OmniHuman por nombre. | — | [elevenlabs.io/creative-terms](https://elevenlabs.io/creative-terms) (act. 2026-10-09) |
| evolink (reseña de «30 días») | «Works with real people, anime characters, pets…»; ~4 % de regeneraciones por errores o resultados malos; no menciona rechazos por cara real | — | [evolink blog](https://evolink.ai/blog/omnihuman-1-5-review-bytedance-ai-avatar-generator-ultimate-guide) (2025-12-30) [2ª] |
| Dreamina (CapCut, app de consumo) | Su flujo de avatar parte de «una imagen de sí mismos o una imagen generada por IA de Seedream» más la voz; no se encontró ninguna política que obligue a verificar identidad | — | [dreamina omnihuman-ai](https://dreamina.capcut.com/es-es/tools/ai-human-generator) [2ª] |

- No se encontró ningún foro, issue de GitHub ni reseña que informe de **rechazos** de fotos reales en OmniHuman. La búsqueda se hizo el 2026-10-15.
- La ausencia de quejas no prueba nada, pero contrasta con Seedance 2.0, donde Adobe, APIYI y ComfyUI sí documentan el bloqueo (ver [investigacion-caras-reales-video-ia.md](investigacion-caras-reales-video-ia.md) §2).

**Conclusión A:** según la documentación, sí. Falta la prueba en vivo con una cara real que haya dado su consentimiento (sección 7, T1).

---

## 2. Evidencia B: Seedance sobre un video de OmniHuman

### 2.1 La restricción de caras reales

- [DOC] [create-video-generation-task-api](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api) (act. 2026-10-13): «Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models **do not support directly uploading reference images or videos that contain real human faces**».
- Ofrece tres salidas:
  1. outputs propios de ciertos modelos;
  2. personajes digitales predefinidos;
  3. real-person assets autorizados.
- Código: `InputVideoSensitiveContentDetected.PrivacyInformation`, HTTP 400 ([DOC] error-codes).

### 2.2 La excepción de outputs propios no incluye OmniHuman

Fuente: [DOC] [seedance-portrait-asset-guide](https://docs.byteplus.com/en/docs/ModelArk/seedance-portrait-asset-guide), act. 2026-10-08.

**Qué outputs son de confianza:**

| Output de confianza | Desde | Validez |
|---|---|---|
| Videos con cara generados por Seedance 2.5 / 2.0 | 11-mar-2026 | 30 días |
| Último fotograma de esos videos | 16-abr-2026 | 30 días |
| Imágenes con cara de **Seedream 5.0** lite/pro/flash **t2i** | 16-abr-2026 | 30 días |

**Condiciones literales:**
- «**Only outputs from the ModelArk platform are trusted; cross-platform use is not supported.**»
- «Only outputs under the same account are trusted».
- «Only original model outputs are trusted; they cannot be used after secondary editing».
- «Compressing or forwarding files may invalidate trust verification».
- «Trust takes effect only when face moderation is triggered».

**Conclusión:**
- OmniHuman es **BytePlus Vision AI**: otro host (`cv.byteplusapi.com`), otra consola y otra activación. **No está en la lista y queda excluido por la regla de «cross-platform»** (fuente primaria).
- Que el video concretamente active la moderación de caras es **no verificado**. Inferencia: muy probable, porque es fotorrealista y parte de una cara real. Hay además reportes de falsos positivos incluso con caras generadas por IA (Adobe, citado en [investigacion-caras-reales-video-ia.md](investigacion-caras-reales-video-ia.md)).

### 2.3 El real-person asset sí puede cubrir el caso: el video de OmniHuman como asset de video

**[DOC] [Private real-human asset library guide](https://docs.byteplus.com/en/docs/ModelArk/2333589)** (act. 2026-10-13; **el título dice «invited users only»**, ver riesgos):
- «Asset: An asset file (**currently supports uploading images, videos, and audio files**), which is a trusted asset that can be directly used for inference by… Seedance 2.0 and… 2.5».
- **Flujo por API, todo con AK/SK:**
  1. `CreateVisualValidateSession` devuelve `H5Link` y `BytedToken`.
  2. La persona hace la prueba de vida en el H5 (idiomas: `zh`, `en`, `zh-Hant`; **no hay español**).
  3. `GetVisualValidateResult` devuelve `GroupId`. El token vale 30 min.
  4. `CreateAsset` con `GroupId`, `URL` y `AssetType=Image|Video|Audio`.
  5. Se sondea `GetAsset` hasta que el estado sea `Active`.
- **El chequeo:** «the system will compare the facial features of the uploaded image with the reference image collected during real-person verification. If the material is determined to be a different person, the upload will fail.» «If multiple faces are detected in the material, it cannot be uploaded.»
- **Coste del chequeo:** la verificación de persona real es «currently free for a limited time».

**[DOC] [CreateAsset](https://docs.byteplus.com/en/docs/ModelArk/create-asset-api)** (act. 2026-09-28):
- **Video:**
  - mp4/mov; 480p, 720p, 1080p o 4K;
  - **2–30 s**, ≤200 MB;
  - **24–60 fps**;
  - aspecto 0,4–2,5;
  - total de píxeles entre 407.696 y 8.295.044 (720×1280 = 921.600 entra).
- **Moderación:** `Moderation.Strategy=Skip` está disponible («skip most non-baseline content security review policies»).
- **Latencia:** «Higher latency is expected when uploading video assets». No hay SLA.

**[DOC] [Usage Rules del H5/API](https://docs.byteplus.com/en/docs/ModelArk/BytePlus_Real_Person_Verification_H5_and_API_Usage_Rules)** (act. 2026-04-15):
- §5.2: la exención de la revisión de imagen real va «**on a per-End-User basis**». Solo las solicitudes de ese usuario final, bajo su cuenta única, quedan exentas.
- §5.3: prohíbe usar el material con su imagen o su voz más allá de lo consentido.
- §2: consentimiento explícito con casilla activa (no premarcada) y registro de la marca de tiempo y la versión aceptada.

**[DOC] [Terms of Use for Asset Library](https://docs.byteplus.com/en/docs/ModelArk/2275639)** (act. 2026-09-28): con los «Authorized Assets», el cliente garantiza tener la autorización plena y asume la responsabilidad. Subir material de titularidad dudosa «constitutes inducing and abusing the model».

**Por qué la biblioteca de avatares virtuales NO sirve:**
- La carta de compromiso ([DOC] [2275638](https://docs.byteplus.com/en/docs/ModelArk/2275638)) exige que el avatar «not identical or similar to the portrait or image of any natural person».
- La guía ([DOC] [2333565](https://docs.byteplus.com/en/docs/ModelArk/2333565)) insiste: «must not resemble any real human person's portrait».
- Un OmniHuman de un cliente real no cumple ninguna de las dos.

**Conclusión (inferencia apoyada en fuentes primarias):**
- Que la persona verificada aparezca en un video generado por IA a partir de su foto es exactamente el caso que el grupo de assets puede cubrir: «assets related to the real person (such as the real person's image, video, and audio)».
- Ninguna regla publicada exige que el material sea una grabación de cámara.
- Dos incógnitas siguen **sin verificar**:
  1. si la comparación facial acepta un rostro sintetizado por OmniHuman, que puede variar levemente;
  2. si existe alguna regla interna contra subir material sintético al grupo de personas reales.

### 2.4 Modos: edit, extend, reference

**Modos de Seedance** ([DOC] [seedance-2-5](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5), act. 2026-10-13 · [DOC] [seedance-2-0](https://docs.byteplus.com/en/docs/modelark/seedance-2-0), act. 2026-09-29 · [DOC] API):

| Modo | Para qué sirve aquí | Restricciones documentadas |
|---|---|---|
| **edit** | Cambiar o limpiar el fondo, añadir el producto en la mano, cambiar el vestuario | 2.5: `omni_reference_task_type=edit`, `ratio=adaptive`, `duration=-1`, video de **4–30 s**; la salida conserva el aspecto y la duración, con «no more than **0.4 seconds**» menos. El prompt debe incluir «edit/add/remove/replace…». 2.0 / fast / mini: edit soportado con video de ≤15 s. |
| **extend** | Alargar el plano: entrada o salida de la persona, transición al local | 2.5: `extend`, `ratio=adaptive`, `duration` 4–30 o −1. 2.0: «the generated video **usually only includes the tail footage** of the original video», salvo que el prompt pida «then end with Video 1». Con 2–3 clips rellena la transición e incluye los originales. |
| **reference** | Escena nueva con la persona (asset) y el producto | Sin restricciones especiales de aspecto ni duración. No puede mezclarse con `first_frame` / `last_frame`. |

Con `auto`, el modelo decide el modo. Si el modo declarado no coincide con lo que el modelo deduce, la tarea falla con `InvalidParameter.TaskTypeMismatch` (asíncrono).

**Límites de duración: OmniHuman frente a Seedance**

| Pieza | Límite | Fuente |
|---|---|---|
| OmniHuman 1.5 | audio <60 s → video <60 s | [DOC] |
| OmniHuman 2.0 | audio 4–300 s | [DOC] |
| Asset de video (`CreateAsset`) | 2–30 s por video | [DOC] |
| Seedance 2.0 / fast / mini, referencia | ≤3 videos, 2–15 s cada uno, **15 s en total**; salida ≤15 s | [DOC] API |
| Seedance 2.5, referencia | ≤10 videos, 2–30 s (edit 4–30 s), **30 s en total**; salida ≤30 s | [DOC] API |

**Implicación:** un reel de 30 s pasa entero por 2.5, o en 2 tramos de 15 s por 2.0, y cada tramo es un asset aparte. Lo que pase de 30 s no se puede editar de una vez.

**Compatibilidad técnica OmniHuman → Seedance:**
- MP4 de 720p/1080p entra en los formatos de Seedance.
- Fotogramas por segundo: OmniHuman 1.0 documenta 30 fps (citado en [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md)). Los de 1.5 y 2.0 están **no verificados**, pero cualquier valor entre 24 y 60 fps sirve.
- La URL caduca en 1 h: hay que copiarla a R2 enseguida y servirla con una URL pública.

### 2.5 Lip-sync y voz al editar o extender

**Lo que está documentado:**
- `generate_audio` es `true` por defecto: «The model will automatically **generate** matching human voice, sound effects and background music based on the text prompt and visual content».
- «All generated videos with audio are **mono**».
- `false` produce una salida muda.
- La tarea de edición «edits the visuals **or audio** of an original video». Un ejemplo de prompt: «remove the background music from @Video 1». Eso sugiere que el modelo procesa el audio de entrada.
- La salida MOV (H.264 4:4:4 + PCM) se recomienda para edit/extend «to improve… audiovisual consistency».
- Edit: la salida puede ser hasta 0,4 s más corta «due to input frame processing».

**Lo que NO está documentado (no verificado):**
- No existe un parámetro tipo `keep_original_audio`.
- No se garantiza que la voz de entrada salga intacta.
- No se garantiza que el edit conserve la boca fotograma a fotograma. Es un modelo generativo que regenera todo el cuadro y no admite máscara.
- En `extend`, la voz del tramo nuevo la genera Seedance: con el prompt entre comillas y, como mucho, con el timbre del `reference_audio` (asset de audio de la persona, 2–30 s). El lip-sync de ese tramo es de Seedance, no de OmniHuman.

**Pipeline seguro para conservar la voz:**
1. Ejecutar el edit con `generate_audio=false`.
2. Volver a montar el WAV original con ffmpeg (`-map`).
3. Medir la deriva con `ffprobe`.

Si la salida sale hasta 0,4 s más corta, hay que alinear con desplazamiento o estiramiento. El riesgo de desincronía visible está **no verificado**.

### 2.6 Cómo se cobran los segundos de entrada

Fuente: [DOC] [model-pricing](https://docs.byteplus.com/en/docs/ModelArk/model-pricing), act. 2026-10-08.

**Fórmula:**
- Tokens ≈ `(segundos de video de entrada + segundos de salida) × ancho × alto × fps / 1024`.
- Si la entrada lleva video, la **tarifa por token es más baja**, pero se cobran **más segundos**.
- Hay un **consumo mínimo** cuando hay video de entrada. La tabla está en un Lark externo y no se consultó.

**Precios unitarios.** A 720p (1280×720 o 720×1280) y 24 fps salen 21.600 tokens/s; a 1080p, 48.600 tokens/s.

| Modelo | Sin video de entrada (USD/s de salida) | Con video (USD por s de entrada + salida) |
|---|---|---|
| Seedance 2.5, 720p | 10,70/M → **0,231** | 6,40/M → **0,138** |
| Seedance 2.5, 1080p | 11,7/M → **0,569** | 7,0/M → **0,340** |
| Seedance 2.0, 720p | 7,0/M → **0,151** | 4,3/M → **0,093** |
| Seedance 2.0 fast, 720p | 5,6/M → **0,121** | 3,3/M → **0,071** |
| Seedance 2.0 mini, 720p | 3,5/M → **0,076** | 2,1/M → **0,045** |
| Seedance 1.0 pro, 720p, mudo (sin video de entrada) | 2,5/M → **≈0,054** | no acepta video |

**Comprobación con la tabla oficial:**
- 2.0 a 720p, 15 s de entrada + 5 s de salida = 20 × 0,093 = **1,86 USD**, que coincide con el «0.84–1.86» oficial.
- 2.5 a 720p, 30 s + 5 s = 35 × 0,138 = **4,84 USD**, que coincide con el «1.244–4.838».

**Nota:** activar Seedance 2.x exige **>30 USD de saldo**. Es prepago, no un gasto (memoria del proyecto, verificado el 2026-10-07).

---

## 3. ¿Aplica el pre-filtro de figuras públicas?

- **En Seedance (ModelArk): sí.**
  - [DOC] [content_pre_filter_faq](https://docs.byteplus.com/en/docs/ModelArk/content_pre_filter_faq), act. 2026-09-10.
  - Analiza las salidas y bloquea las caras o voces parecidas a figuras públicas de su conjunto de referencia: políticos, deportistas, empresarios, famosos, medios.
  - «Not… a comprehensive block».
  - Aplica a cualquier salida de Seedance, también a la que use un real-person asset.
  - **Riesgo:** el cliente o creador puede ser «famoso local». Si aparece en el conjunto de referencia, la salida se bloquea aunque tenga verificación (inferencia; no verificado).
- **En OmniHuman (Vision AI): no documentado.** El pre-filtro de Vision AI no tiene la categoría de figuras públicas, y la política «baseline» no está publicada → **no verificado**.

---

## 4. Pipelines viables

| | Pipeline | Cómo | Qué resuelve | Qué exige | Riesgos |
|---|---|---|---|---|---|
| **(a)** | OmniHuman para el plano hablado + Seedance para planos **sin** la persona + montaje | OmniHuman (foto + voz clonada) para los tramos a cámara; Seedance (texto o imagen del producto) para B-roll del producto y el local; Remotion/ffmpeg con la pista de voz original | No toca la moderación de caras de Seedance; lip-sync de OmniHuman intacto; la voz no pasa por Seedance | Verificación empresarial + activación de OmniHuman en Vision AI + AK/SK; Seedance 1.0 pro ya funciona con la key actual | A (OmniHuman con cara real) sin verificar en vivo; concurrencia 1 en 1.5 |
| **(a′)** | (a) + **edición** del plano hablado con Seedance vía real-person asset | Prueba de vida de la persona → `CreateAsset(Video)` con el clip de OmniHuman → Seedance `edit`/`extend` con `asset://`, `generate_audio=false` → volver a montar la voz | Cambiar o extender el fondo del plano hablado, meter el producto en la escena | Todo lo de (a) + plan Advanced Creation Rights (Entry, gratis) + aceptar 4 textos legales + consentimiento propio | Comparación facial con un rostro sintético (no verificada); deriva de lip-sync ≤0,4 s; acceso por API «invited users only»; costo alto |
| **(b)** | Seedance 2.x directo con real-person asset + `reference_audio` | Prueba de vida → assets de imagen (y audio de la voz) → Seedance `reference` con la frase entre comillas y `generate_audio=true` | Todo en ModelArk, escenas completas con la persona, sin OmniHuman | Verificación empresarial + Advanced Entry + >30 USD de saldo | Seedance **genera** la voz: el texto exacto y el parecido de la voz con la de la persona no están garantizados; lip-sync propio, no el del audio exacto; salida mono |
| **(c)** | HeyGen (Avatar IV Photo o Digital Twin) para el plano hablado + Seedance para B-roll sin la persona | HeyGen `audio_url` con la voz clonada; Seedance para producto y local; montaje | 9:16 nativo, concurrencia 10, **la key de HeyGen ya está en `.env`**, consentimiento por webcam (Twin) | Nada nuevo en BytePlus para el plano hablado | Photo Avatar sin control de consentimiento; precios de HeyGen contradictorios |

## 5. Costo por reel de 30 s (9:16, 720p, sin reintentos)

Supuestos:
- Reel de 30 s = **18 s a cámara + 12 s de B-roll** (2 clips de 6 s), salvo en (a′) y (b).
- Voz con Seed Speech: ≈0,015 USD, despreciable.
- Remotion: 0 USD.
- Precios de la sección 2.6 y de [costos-comparativos-herramientas-ia.md](costos-comparativos-herramientas-ia.md).
- Columna «×1,5»: reintentos.

| Pipeline | Desglose | Por reel | ×1,5 |
|---|---|---|---|
| **(a) OmniHuman 2.0 + B-roll Seedance 1.0 pro** | 18 s × 0,07–0,12 = 1,26–2,16 · B-roll 12 s × 0,054 = 0,65 | **≈1,9–2,8 USD** | ≈2,9–4,2 |
| (a) OmniHuman 1.5 + B-roll Seedance 2.0 mini | 18 s × 0,12 = 2,16 · 12 s × 0,076 = 0,91 | **≈3,1 USD** | ≈4,6 |
| (a) OmniHuman 1.5 + B-roll Seedance 2.5 | 2,16 + 12 s × 0,231 = 2,77 | **≈4,9 USD** | ≈7,4 |
| **(a′) OmniHuman 30 s + edit Seedance 2.0 mini** (2 tramos de 15 s) | OmniHuman 30 s: 2,10–3,60 · edit 2 × (15 + 15) s × 0,045 = 2,72 (+ consumo mínimo) | **≈4,8–6,3 USD** | ≈7,2–9,5 |
| (a′) OmniHuman 30 s + edit Seedance 2.5, 720p (1 tramo) | 2,10–3,60 + (30 + 30) s × 0,138 = 8,29 | **≈10,4–11,9 USD** | ≈15,6–17,9 |
| (a′) idem, 1080p | 2,10–3,60 + 60 s × 0,340 = 20,4 | **≈22,5–24 USD** | ≈34–36 |
| **(b) Seedance 2.0 mini + real-person asset** (2 × 15 s) | 30 s × 0,076 | **≈2,3 USD** | ≈3,4 |
| (b) Seedance 2.0 estándar (2 × 15 s) | 30 s × 0,151 | **≈4,5 USD** | ≈6,8 |
| (b) Seedance 2.5, 720p, toma única de 30 s | 30 s × 0,231 | **≈6,9 USD** | ≈10,4 |
| **(c) HeyGen Avatar IV Photo + B-roll Seedance 1.0 pro** | 18 s × (2,31–3,00)/60 = 0,69–0,90 · 0,65 | **≈1,3–1,6 USD** | ≈2,0–2,4 |
| (c) HeyGen Avatar IV Digital Twin + B-roll Seedance 2.0 mini | 18 s × 4,83/60 = 1,45 · 0,91 (+2,13 USD por creador, una vez) | **≈2,4 USD** | ≈3,5 |

**Costes fijos o de activación (no por reel):**
- **Seedance 2.x:** >30 USD de saldo prepago.
- **Real-person asset:**
  - plan Advanced Creation Rights Entry: gratis, 50 assets o grupos y 3 QPM en `CreateAsset`;
  - el plan siguiente cuesta **1.400 USD/mes**: 1 M de assets y 120 QPM ([DOC] [purchase guide](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0-purchase-guide), act. 2026-09-28).
  - **Ojo:** los assets creados durante un plan de pago **se borran** 15 días después de que caduque.
- **Vision AI:** sin saldo mínimo documentado (no verificado).

---

## 6. Recomendación

1. **Producción: pipeline (a) o (c).** Plano hablado con OmniHuman o HeyGen, **sin editarlo después**. B-roll del producto y el local con Seedance; mientras no salga una persona, no hay moderación de caras ni real-person asset. Montaje en Remotion con la pista de voz original.
   - Es lo más barato: ~1,3–3 USD por reel.
   - Conserva el lip-sync.
   - No depende de ninguna excepción de confianza.
   - La elección entre OmniHuman y HeyGen sale del A/B ya recomendado en [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md). HeyGen tiene la ventaja de que la key ya existe.
2. **Para fondos distintos detrás de la persona, sin editar con Seedance:**
   - poner el fondo en la **foto de entrada** de OmniHuman, editada con Seedream 5.0 o compuesta antes, porque OmniHuman anima la escena de la foto;
   - o describirlo en el prompt de OmniHuman, que admite «environmental interaction» y elementos añadidos según su documentación.

   Es mucho más barato que un edit de video. Que la calidad baste está **no verificado**.
3. **(a′) queda como experimento**, solo si el fundador quiere planos en los que la persona hable dentro de una escena generada (por ejemplo, una extensión con movimiento). Depende de dos supuestos sin verificar y de un acceso por API que la documentación marca como «invited users only». Cuesta 2–5 veces más que (a).
4. **(b) para planos con la persona en los que no hace falta el texto exacto** (gestos, caminar por el local, sostener el producto). Seedance no reproduce un audio dado con lip-sync exacto: genera la voz a partir del prompt.
5. **Para todos los pipelines:**
   - etiquetado de IA (C2PA o aviso visible);
   - `enable_watermark=false` en OmniHuman 2.0 solo si ponemos nuestra propia marca, para no «alterar» la de BytePlus después;
   - consentimiento con casilla activa y registro (§2 de las Usage Rules);
   - **no aceptar figuras públicas**.

---

## 7. Plan de prueba en vivo de bajo costo

**Credenciales y activaciones que faltan.** En `.env` del checkout principal hoy solo existen:
- `QUALIFY_BYTEPLUS_ARK_API_KEY` y `QUALIFY_BYTEPLUS_ARK_BASE_URL`;
- `QUALIFY_HEYGEN_API_KEY`;
- `QUALIFY_R2_ENDPOINT_URL`, `QUALIFY_R2_ACCESS_KEY_ID`, `QUALIFY_R2_SECRET_ACCESS_KEY` y `QUALIFY_R2_BUCKET`.

Solo se listaron los nombres de las variables, no sus valores. **No hay AK/SK de BytePlus.** Hacen falta para Vision AI y para la API de assets.

**Pasos previos (sin coste de uso):**
1. **Verificación empresarial** de la cuenta de BytePlus. La exigen Vision AI y el plan Advanced.
2. **Sub-cuenta IAM con AK/SK.** Políticas: `CVFullAccess` para OmniHuman y `ArkFullAccess` para la API de assets. Variables nuevas propuestas: `QUALIFY_BYTEPLUS_AK` y `QUALIFY_BYTEPLUS_SK`.
3. **Vision AI → Model Plaza → activar OmniHuman 1.5** (y 2.0 si aparece) y confirmar el estado del Content Pre-filter.
4. **ModelArk:** activar Seedance 2.0 mini (>30 USD de saldo) y el plan **Advanced Creation Rights (Entry)**, que es gratis, aceptando:
   - Terms of Use for Asset Library;
   - Commitment Letter;
   - Real Person Verification Usage Rules;
   - Customer Code of Conduct.
5. **Sujeto de prueba: el propio fundador.** Es su cara, su consentimiento y su prueba de vida, y evita cualquier problema con terceros.
6. **Material:** una foto frontal 9:16, un audio de 5–6 s con su voz clonada (Seed Speech) y una foto de producto. Todo servido desde R2 con URL pública.

**Pruebas**

| # | Llamada | Qué confirma | Costo estimado |
|---|---|---|---|
| T1 | OmniHuman 1.5 `CVSubmitTask`, foto real + audio de 5 s, `output_resolution=720`, pre-filtro **activado** | **A**: si acepta la cara real o devuelve `50510`; calidad en español; fps y duración de la salida (`ffprobe`) | 5 × 0,12 = **0,60 USD** |
| T1b | OmniHuman 2.0 `CVSync2AsyncSubmitTask`, la misma foto + audio de 5 s (mínimo 4 s), `enable_watermark=false` | A en 2.0; qué tarifa se cobra (0,07 o 0,12) | **0,35–0,60 USD** |
| T2 | Seedance 2.0 mini, `reference_video` = URL de la salida de T1 (sin asset), prompt de edit | **B directo**: ¿`PrivacyInformation`? ¿Síncrono (400) o asíncrono? ¿Se cobra el rechazo? | 0 si rechaza (que el rechazo no se cobre está **no verificado**) · ≈0,45 si pasa |
| T3 | `CreateVisualValidateSession` → H5 (el fundador, `lng=en`) → `GetVisualValidateResult` → `CreateAsset(AssetType=Video, URL=salida de T1)` → `GetAsset` | **Si un video de OmniHuman pasa la comparación facial** (`Active` o `Failed`); si la API de assets está abierta o es «invited only» | **0 USD** (verificación gratis por tiempo limitado, plan Entry) |
| T3b | `CreateAsset(AssetType=Image)` con la foto original + `AssetType=Audio` con la voz | Assets para (b) | 0 USD |
| T4 | Seedance 2.0 mini `edit` con `asset://` de T3, «replace the background with a coffee shop; keep the person, lips and speech unchanged», **dos variantes**: `generate_audio=false` y `true` | Modo edit sobre OmniHuman; si `true` conserva o regenera la voz; deriva de duración (≤0,4 s); lip-sync tras volver a montar la voz | 2 × (5 + 5) s × 0,045 ≈ **0,90 USD** (+ consumo mínimo) |
| T5 | Seedance 2.0 mini `extend` con `asset://` de T3 + `reference_audio` (asset de T3b), «extend backward: the person walks into the shop, then end with Video 1» | Si la salida incluye el original; voz y lip-sync del tramo nuevo | ≈ (5 + 5) × 0,045 ≈ **0,45 USD** |
| T6 | Seedance 2.0 mini `reference` con la imagen de T3b + `reference_audio` + frase entre comillas, 5 s | Pipeline (b): parecido de la voz, texto exacto, lip-sync | 5 × 0,076 ≈ **0,38 USD** |
| T7 | HeyGen Avatar IV, la misma foto + el mismo audio de 5 s (`audio_url`) | A/B con T1 para (c) | ≈ 5/60 × (2,31–3,00) ≈ **0,19–0,25 USD** |

**Total de uso:**
- **≈3–4 USD**;
- más los **>30 USD de saldo prepago** de Seedance 2.x, que quedan disponibles, no se gastan;
- y la latencia de 1.5: ≈2 min por 5 s a 720p, con RTF 23.

**Orden:**
- T1 decide A.
- T2 confirma el bloqueo directo.
- T3 es la pieza crítica de B. Si falla, (a′) queda descartada y quedan (a)/(c) + (b).
- T4–T6 solo se ejecutan si T3 da `Active`.

**Qué medir en cada salida:**
- `ffprobe`: duración, fps y pistas de audio;
- comparación de duración entrada/salida;
- revisión visual del lip-sync con la voz original vuelta a montar;
- `usage.completion_tokens` frente a la estimación de costo.

**Pregunta para ventas o soporte de BytePlus, en paralelo:**
- si la API de assets es «invited users only» o la abre el plan Entry;
- si subir material **generado por IA** de una persona verificada (por OmniHuman) a su grupo cumple las reglas;
- si la excepción por usuario final (§5.2) cubre un modelo B2B en el que Qualify sube el material en nombre del cliente.

---

## 8. Lo que queda «no verificado»

1. Que OmniHuman 1.5 o 2.0 acepte en la práctica una cara real con el pre-filtro activado (T1).
2. Que tenga un filtro de figuras públicas o una política «baseline» que afecte a caras reales.
3. Qué tarifa se aplica a OmniHuman 2.0 (0,07 o 0,12 USD/s) y sus fps de salida.
4. Que Seedance marque como `PrivacyInformation` un video de OmniHuman, y si los rechazos se cobran (T2).
5. Que `CreateAsset(Video)` acepte un video de OmniHuman de la persona verificada (T3).
6. Que la API de assets esté disponible con el plan Entry o requiera invitación.
7. Que el edit conserve la voz con `generate_audio=true` y el lip-sync con la voz vuelta a montar (T4).
8. El consumo mínimo de tokens con video de entrada (tabla en un Lark externo).
9. La calidad del parecido de voz y el texto exacto en el pipeline (b) (T6).

## Fuentes (consultadas el 2026-10-15)

**BytePlus [DOC]** (Markdown extraído del HTML; fecha de actualización de cada página entre paréntesis):
- OmniHuman 1.5 API (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-video_generation
- OmniHuman 2.0 API (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation
- OmniHuman 1.5 overview (2026-01-07): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman1_5overview
- Subject Recognition (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-subject_recognition
- Subject Detection (2026-10-15): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-subject_detection
- Vision AI FAQ (2026-09-16): https://docs.byteplus.com/en/docs/byteplus-vision/FAQ
- Vision AI Content Pre-filter (2025-12-26): https://docs.byteplus.com/en/docs/byteplus-vision/vision-ai-content-pre-filter
- Vision AI common error codes (2025-10-14): https://docs.byteplus.com/en/docs/byteplus-vision/docs-common-responses-and-error-codes
- GenAI AUP (2026-08-31): https://docs.byteplus.com/en/docs/legal/acceptable_use_policy_byteplus_genai
- Producto OmniHuman: https://www.byteplus.com/en/product/OmniHuman
- Create video generation task (2026-10-13): https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api
- Seedance 2.0 tutorial (2026-09-29): https://docs.byteplus.com/en/docs/modelark/seedance-2-0
- Seedance 2.5 tutorial (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5
- Portrait asset guide (2026-10-08): https://docs.byteplus.com/en/docs/ModelArk/seedance-portrait-asset-guide
- Add real-human assets (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/upload-real-person-portrait-assets
- Private real-human asset library guide (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/2333589
- CreateAsset (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/create-asset-api
- CreateVisualValidateSession (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/h5-create-visual-validate-session-api
- Real Person Verification Usage Rules (2026-04-15): https://docs.byteplus.com/en/docs/ModelArk/BytePlus_Real_Person_Verification_H5_and_API_Usage_Rules
- Asset Library Terms (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/2275639
- Virtual Avatar Commitment Letter (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/2275638
- Private virtual portrait library (2026-10-13): https://docs.byteplus.com/en/docs/ModelArk/2333565
- Advanced Creation Rights purchase guide (2026-09-28): https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0-purchase-guide
- Content filter FAQ (2026-09-10): https://docs.byteplus.com/en/docs/ModelArk/content_pre_filter_faq
- Error codes (2026-10-06): https://docs.byteplus.com/en/docs/ModelArk/error-codes
- Model pricing (2026-10-08): https://docs.byteplus.com/en/docs/ModelArk/model-pricing

**Terceros [2ª]:**
- fal.ai OmniHuman 1.5: https://fal.ai/models/fal-ai/bytedance/omnihuman/v1.5
- Hedra OmniHuman 1.5: https://mkt.hedra.com/models/video/bytedance/omnihuman-15
- Hedra talking photo: https://hedra.com/uses/talking-photo-ai
- ElevenLabs Creative Terms (2026-10-09): https://elevenlabs.io/creative-terms
- evolink, reseña de OmniHuman 1.5 (2025-12-30): https://evolink.ai/blog/omnihuman-1-5-review-bytedance-ai-avatar-generator-ultimate-guide
- Dreamina AI human generator: https://dreamina.capcut.com/es-es/tools/ai-human-generator
