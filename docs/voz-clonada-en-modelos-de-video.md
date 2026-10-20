# Voz clonada de la marca en los modelos de video (Seedance y otros)

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN 2026-10-15]` · fuentes consultadas el 2026-10-15 · sin llamadas de pago a ninguna API

Marcas: **[DOC]** documentación oficial · **[PRECIO]** página de precios oficial · **[2ª]** tercero · **no verificado** = no confirmado en fuente primaria.

Se construye sobre [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md), [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md) y [costos-comparativos-herramientas-ia.md](costos-comparativos-herramientas-ia.md); no repite lo que ya está allí.

## Resumen

- **Seedance (2.0, fast, mini y 2.5) no tiene ninguna vía documentada para hacer lip-sync de un audio dado.** Hace hablar al personaje con **voz generada por el propio modelo**. Puede **imitar el timbre** de un `reference_audio`, pero BytePlus reconoce que el resultado puede «diferir significativamente» de la referencia. La voz que se oye **no es nuestro MP3**.
  - Lo más cercano es la tarea `edit` de la 2.5: re-dobla un video con lip-sync «palabra a palabra», pero la voz nueva **también la sintetiza Seedance**.
- **La voz real no dispara filtro de privacidad en Seedance.** Hay `PrivacyInformation` para imagen y video, pero **no para audio**. Los rechazos de audio documentados son «sensitive» y copyright.
  - Los *real-person assets* **sí admiten audio de 2–30 s**, con verificación facial y autorización del titular.
- **El audio de entrada no se cobra en Seedance.** La fórmula de tokens solo suma los segundos de **video** de entrada; Runway, que revende Seedance 2.5, lo dice explícitamente: «images and audio free».
  - Corrección a la comparativa de costos: **Seedance 2.0 mini cuesta ≈2,27 USD por 30 s a 720p**, no 2,5–5,5 USD. Ese rango era el de «con video de entrada».
- **Para que Seedance «hable» con la voz exacta de la marca hace falta un segundo paso de lip-sync** sobre nuestro MP3. Hay tres proveedores con API para «video + audio → video con labios resincronizados»:
  - **HeyGen Lipsync** (`POST /v3/lipsyncs`): 0,84 USD/min en Speed y 1,74 USD/min en Precision. **Ya tenemos cuenta y adaptador.**
  - **Sync.so**: lipsync-2, 0,04–0,05 USD/s; lipsync-2-pro, 0,067–0,083 USD/s; sync-3, 0,107–0,133 USD/s.
  - **Kling Lip-Sync**: precio oficial no publicado en la tabla.
- **Nuestro clonador actual (HeyGen) ya puede producir el audio suelto.**
  - La referencia oficial de `POST /v3/voices/clone` dice: «The resulting voice can be used with **POST /v3/voices/speech** and POST /v3/videos».
  - Devuelve un `audio_url` MP3 con marcas de tiempo por palabra.
  - Costo: Starfish a **0,12 USD/min** según el help center oficial (≈0,06 USD por reel). Un tercero dice 0,04 USD/min: **contradicción**.
- **Los motores que aceptan un audio externo y le hacen lip-sync** (imagen + audio → video): OmniHuman, HeyGen (Avatar IV/V), Kling Avatar, Hedra Character-3, Veed Fabric, Creatify Aurora y Wan 2.5/2.6 (`audio_url`).
  - **Solo timbre** (como Seedance): MiniMax H3.
  - **Sin entrada de audio:** Veo 3.1 y Gemini Omni Flash. Omni dice textual: «Uploading audio references is unsupported in the current version of the API».
- **Recomendación** (§6):
  - Una sola fuente de voz que produzca un **MP3 por guion**, guardado en R2 (patrón *voice-as-audio*).
  - Para Seedance: **escena con Seedance y después lip-sync con HeyGen Lipsync Precision sobre ese MP3** (≈3,16 USD por reel con 2.0 mini; ≈316 USD por 100 reels).
  - **Sync.so lipsync-2-pro** como alternativa en un A/B.
  - **Fuente única: Seed Speech `seed-icl-2.0`** (es-MX). Hasta que pase el spike, el clon HeyGen ya existente vía `POST /v3/voices/speech` hace de puente.

## 1. Seedance 2.0 / 2.0 fast / 2.0 mini / 2.5 (BytePlus ModelArk)

Fuentes [DOC], todas consultadas el 2026-10-15 (fecha de actualización de cada página entre paréntesis):
- [create-video-generation-task-api](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api) (2026-10-13)
- [seedance-2-0](https://docs.byteplus.com/en/docs/modelark/seedance-2-0) (2026-09-29) y [seedance-2-0-prompt-guide](https://docs.byteplus.com/en/docs/modelark/seedance-2-0-prompt-guide) (2026-09-28)
- [seedance-2-5](https://docs.byteplus.com/en/docs/modelark/seedance-2-5) (2026-10-13) y [seedance-2-5-prompt-guide](https://docs.byteplus.com/en/docs/modelark/seedance-2-5-prompt-guide) (2026-09-28)
- [seedance-portrait-asset-guide](https://docs.byteplus.com/en/docs/modelark/seedance-portrait-asset-guide) (2026-10-08) y [upload-real-person-portrait-assets](https://docs.byteplus.com/en/docs/modelark/upload-real-person-portrait-assets) (2026-10-13)
- [error-codes](https://docs.byteplus.com/en/docs/modelark/error-codes) (2026-10-06) y [model-pricing](https://docs.byteplus.com/en/docs/modelark/model-pricing) (2026-10-08)

### 1.1 ¿Puede el personaje decir un audio exacto?

**Respuesta corta: no hay ninguna vía documentada de «lip-sync a un audio dado» en Seedance.** El audio de referencia se usa como *referencia* (timbre, melodía, contenido), y el audio de salida **lo genera el modelo**.

Lo que dicen las docs, textual:

| Pieza | Qué documenta | Lectura para Qualify |
|---|---|---|
| `generate_audio` (por defecto `true`) | «The model will automatically generate matching human voice, sound effects and background music based on the text prompt and visual content. It is recommended to put dialogue content in double quotes». Salida siempre **mono** | El audio de salida es síntesis del modelo, no nuestro MP3 |
| `reference_audio` (rol único para audio) | «inherit… **timbre, music melody, and dialogue content** from reference audio» (seedance-2-0, «Omni reference») | Admite heredar «contenido de diálogo», pero no promete reproducción literal |
| Fórmula de prompt 2.0 | «Voice timbre reference: "Character" says: "lines", voice timbre references "Audio n"» · «Audio content reference: Ideal appearance timing + "Audio n"» | Dos usos: timbre (guion en el prompt) o colocar el contenido de un audio en un momento. El ejemplo oficial del segundo uso es **música de fondo** («use [Audio 1] as the background music throughout»), no habla |
| FAQ 2.0 «Inaccurate voice reference» | «the audio voice in the final generated video **differs significantly** from the reference voice». Solución: describir la voz en el prompt («Use the low, thick, warm… voice of @Audio 1 to say») | **La fidelidad del timbre no está garantizada**; BytePlus lo reconoce |
| Guía 2.5, capacidades R2V | «Audio reference — References audio information such as music, dialogue, voice, tone, or timbre» · «Subject image + audio reference» | Igual que 2.0, más amplio |
| Guía 2.5, **audio editing** (tarea `edit`) | «Adds, removes, or modifies audio in video». Ejemplo: «Translate the spoken dialogue in the video into Chinese… Precisely adjust the lip movements to match» · FAQ: «Require word-level lip synchronization» | **Lo más cercano a lip-sync que tiene Seedance:** re-doblar un video y reajustar labios. Pero la voz nueva **la sintetiza el modelo** desde el texto del prompt; no hay ejemplo con un `reference_audio` como pista a respetar |

**Conclusión 1.1:**
- Seedance 2.x **sí puede hacer hablar a un personaje con lip-sync propio** (genera voz + labios a la vez) y **puede aproximar el timbre** de nuestra voz clonada si le pasamos una muestra como `reference_audio`.
- **No consta que reproduzca un MP3 dado palabra por palabra con su ritmo exacto.** Que «dialogue content» de un audio de referencia salga literal en el video es **no verificado**: requiere un spike en vivo.
- La voz que se oye en el video **no es nuestro audio**: es una re-síntesis del modelo con timbre parecido, y BytePlus admite que puede diferir «significativamente».
- Si se necesita la voz exacta de la marca, Seedance no basta: hace falta un paso de lip-sync posterior (ver §2.13).

### 1.2 `omni_reference_task_type` en 2.5 (`reference` / `edit` / `extend`)

Solo existe en Seedance 2.5 ([create-video-generation-task-api](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api), [seedance-2-5](https://docs.byteplus.com/en/docs/modelark/seedance-2-5) «Task types and constraints»). Por defecto `auto`.

| Valor | Cuándo | Restricciones | Uso para la voz |
|---|---|---|---|
| `reference` | al menos un `reference_image`/`reference_video`/`reference_audio` | ninguna sobre `ratio`/`duration` (4–30 s) | **Personaje nuevo que habla** con timbre de `@Audio 1`. 2.5 admite **solo audio** como entrada (2.0 no) |
| `edit` | al menos un `reference_video` + intención de editar en el prompt | `ratio: adaptive`, `duration: -1`, video de 4–30 s | **Re-doblaje con lip-sync** de un video ya hecho (por ejemplo, un clip mudo de Seedance) — con voz sintetizada por Seedance, no la nuestra |
| `extend` | `reference_video` + intención de extender | `ratio: adaptive` | Alargar un clip; no aporta a la voz |

- El modelo **reclasifica la tarea según el prompt**: si no coincide con el valor declarado, falla con `InvalidParameter.TaskTypeMismatch` (error asíncrono) ([error-codes](https://docs.byteplus.com/en/docs/modelark/error-codes)).
- **2.5 genera hasta 30 s en una sola tarea** (`duration` 4–30); la serie 2.0, 4–15 s. Un reel de 30 s con 2.0 son dos tareas encadenadas.
- Idiomas: 2.5 añade **español** al habla nativa («Spanish, Indonesian, Portuguese…») ([create-video-generation-task-api](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api)). Que sea español latino y no peninsular: **no documentado**.
- Seedance 2.5 sí distingue en el prompt `{}` para diálogo, `()` música, `<>` efectos y `【】` subtítulos, y recomienda indicar el idioma antes de un diálogo que no sea chino ([seedance-2-5](https://docs.byteplus.com/en/docs/modelark/seedance-2-5), «Prompt rules»).

### 1.3 Límites de la entrada de audio

| | Seedance 2.0 / fast / mini | Seedance 2.5 |
|---|---|---|
| Clips de audio | 0–3, **2–15 s cada uno, ≤15 s en total** | 0–10, **2–30 s cada uno, ≤30 s en total** |
| ¿Solo audio (sin imagen ni video)? | **No**: «include at least one reference image or video» | **Sí** |
| Formato | wav, mp3; ≤15 MB por archivo; cuerpo ≤64 MB | idem |
| Forma de pasarlo | URL pública, Base64 (`data:audio/wav;base64,…`) o `asset://<id>` | idem |
| Mezclar con `first_frame`/`last_frame` | **No** (escenarios mutuamente excluyentes) | **No** |

Fuente: [create-video-generation-task-api](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api) «Audio input requirements». Nota: el adaptador actual (`byteplus_ark.py`) dice que ModelArk no acepta Base64 para audio; **la doc de hoy dice que sí** (pero no para archivos grandes).

### 1.4 Voz real: ¿hay filtro de privacidad de voz?

- **Para imagen y video, sí**: `InputImageSensitiveContentDetected.PrivacyInformation` y `InputVideoSensitiveContentDetected.PrivacyInformation` («may contain real person») ([error-codes](https://docs.byteplus.com/en/docs/modelark/error-codes)).
- **Para audio, no existe un código `PrivacyInformation`.** Los únicos rechazos de audio documentados son:
  - `InputAudioSensitiveContentDetected` («may contain sensitive information»);
  - `InputAudioSensitiveContentDetected.PolicyViolation` («may be related to **copyright** restrictions»);
  - y sus equivalentes `Output…` sobre el audio generado.
- **Lectura:** según la documentación, una voz real como `reference_audio` **no dispara un filtro de «persona real»**. Si el filtro genérico «sensitive» la detecta como voz identificable: **no documentado, no verificado**. El riesgo práctico es el de copyright (por ejemplo, una muestra con música de fondo).
- Esto **no exime del consentimiento**: la AUP GenAI de BytePlus prohíbe usar la semejanza de una persona sin consentimiento (ver [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md) §3).

### 1.5 Real-person assets: ¿incluyen audio de 2–30 s?

**Sí.** [upload-real-person-portrait-assets](https://docs.byteplus.com/en/docs/modelark/upload-real-person-portrait-assets) (act. 2026-10-13) y [seedance-portrait-asset-guide](https://docs.byteplus.com/en/docs/modelark/seedance-portrait-asset-guide) (act. 2026-10-08):

- Tras la **verificación de persona real** y la autorización del titular, se suben «the real person's **image, video, and audio**» a la biblioteca privada; cada asset recibe un ID y se usa como `asset://<id>`, también en `audio_url` con `role: reference_audio`.
- Requisitos del audio del asset: **wav/mp3, 2–30 s, ≤15 MB**. «Different models support different input audio and video durations» (2.0 solo acepta clips ≤15 s; 2.5, ≤30 s).
- **Flujo de alta:** la cuenta usuaria (Qualify) genera un **QR de invitación** en el Model Playground (la cuenta debe tener **verificación de persona real o empresarial**); el titular escanea, inicia sesión en **su propia cuenta BytePlus**, pasa la verificación facial, sube sus materiales y autoriza; Qualify acepta el asset en consola.
- Cada subida pasa un **chequeo de consistencia** con la persona verificada; un grupo de assets = una sola persona.
- **Para Qualify:** es el único camino documentado para que Seedance use la **cara real** de alguien de la marca. Para la **voz** no hace falta (no hay filtro de privacidad de audio, §1.4), pero un asset de audio deja **registro de consentimiento verificado por BytePlus**, que hoy nadie más nos da para la voz. El alta es **manual, en consola**: no consta una API para crear la invitación (no verificado).

### 1.6 Costo por segundo y si se cobra el audio de entrada

[model-pricing](https://docs.byteplus.com/en/docs/modelark/model-pricing) (act. 2026-10-08) [PRECIO]:

- Fórmula: `tokens ≈ (duración del video de entrada + duración del video de salida) × ancho × alto × fps / 1024`.
- **El audio de entrada no aparece en la fórmula.** Solo se cobran los segundos de **video** de entrada. El supuesto de partida («los segundos de entrada se cobran») vale para el video de referencia, **no para el audio**. Que un `reference_audio` no sume tokens es una lectura de la fórmula; confirmar con `usage.completion_tokens` en el spike.
- «You are only charged for successfully generated videos»: un rechazo por moderación no se cobra.
- Con video de entrada aplica un **consumo mínimo de tokens** (tabla aparte).

Precio unitario (USD por millón de tokens, online) y costo derivado a **720p, 24 fps** (9:16 = 720×1280 = mismos píxeles que 16:9 → 21.600 tokens/s):

| Modelo | Sin video de entrada | Con video de entrada | USD/s a 720p sin video (cálculo) | 30 s a 720p | Comprobación con la tabla oficial (5 s, 16:9) |
|---|---|---|---|---|---|
| Seedance 2.5 (`dreamina-seedance-2-5-260628`) | 10,70 (1080p: 11,7) | 6,40 (1080p: 7,0) | **0,231** | **≈6,93 USD** (1 tarea) | 1,156 USD/5 s ✓ |
| Seedance 2.0 (`…-2-0-260128`) | 7,0 (1080p 7,7; 4K 4,0) | 4,3 | **0,151** | **≈4,54 USD** (2 tareas de 15 s) | 0,76 USD/5 s ✓ |
| Seedance 2.0 fast | 5,6 | 3,3 | **0,121** | **≈3,63 USD** | 0,60 USD/5 s ✓ |
| Seedance 2.0 mini (`…-2-0-mini-260615`) | 3,5 | 2,1 | **0,076** | **≈2,27 USD** | 0,38 USD/5 s ✓ |

- **Corrección a [costos-comparativos-herramientas-ia.md](costos-comparativos-herramientas-ia.md) §3:** allí Seedance 2.0 mini figura a «0,41–0,91 USD por 5 s» y «2,5–5,5 USD por 30 s». Ese rango es el de **«Input with video»** (2–15 s de video de entrada). Con imagen + audio de referencia y sin video de entrada, la tabla oficial da **0,38 USD por 5 s → ≈2,27 USD por 30 s**.
- A 1080p (solo 2.0 y 2.5): 2.0 ≈ 0,374 USD/s (≈11,2 USD por 30 s); 2.5 ≈ 0,569 USD/s (≈17,1 USD por 30 s).
- **Re-doblaje `edit` en 2.5** (video de 30 s → video de 30 s a 720p): (30 + 30) × 21.600 × 6,40 / 10⁶ ≈ **8,29 USD** (cálculo con la fórmula; la tabla oficial da 4,84 USD para 30 s de entrada → 5 s de salida, consistente).
- Activación de 2.x: saldo > 30 USD, o AI Savings Plan ≥ 30 USD, o un paquete de recursos ([seedance-2-0](https://docs.byteplus.com/en/docs/modelark/seedance-2-0)).
- Límites (online): concurrencia 10 (empresa) / 3 (individual), RPM 600/180; 4K: concurrencia 1 ([seedance-2-0](https://docs.byteplus.com/en/docs/modelark/seedance-2-0)).

## 2. Otros motores de video: ¿aceptan nuestro audio y hacen lip-sync?

Leyenda de la columna «modo»:
- **A = audio externo con lip-sync exacto:** el video se anima a partir de nuestro MP3 y se oye nuestro MP3.
- **T = solo timbre:** el modelo genera su propia voz parecida a una referencia.
- **P = voz propia:** genera voz desde el texto; no acepta audio.
- **L = lip-sync sobre un video ya hecho:** video + audio → video.

### 2.1 Kling (Kuaishou)

- **Modo A (Avatar):** imagen + audio. Precio oficial **0,4 Units (0,056 USD)/s a 720p · 0,8 Units (0,112 USD)/s a 1080p**, con 1 Unit = 0,14 USD (precio de lista) ([kling.ai/dev/pricing](https://kling.ai/dev/pricing), extraído del HTML el 2026-10-15) [PRECIO].
- **Modo L (Lip-Sync):** existe como tipo de tarea («Lip Sync» en la lista de task types de la misma página).
  - **El precio no aparece en la tabla oficial.** Un tercero dice 0,5 Units por 5 s (≈0,014 USD/s): **no verificado**.
  - Según terceros: flujo `identify-face` → `advanced-lip-sync` con `sound_file`/`audio_id`, video de 2–10 s, audio ≤5 MB ([RunComfy](https://www.runcomfy.com/models/kling/lipsync/audio-to-video) [2ª]): **no verificado**.
- **Modo P:** Kling 3.0 «With Native Audio × No Voice Control», 0,9 Units (0,126 USD)/s a 720p.
  - La fila implica que existe un modo con **Voice Control** (voz personalizada), pero su precio no figura.
  - Hay un clonado de voz propio («custom voice»: muestra de 5–30 s → `voice_id`) que solo consta en documentación de terceros ([GMI Cloud](https://docs.gmicloud.ai/model-quickstarts/audio/kling-custom-voice) [2ª]): **no verificado**.
- La documentación de la API de Kling solo renderiza con JS; los precios se leyeron del JSON embebido en la página de precios.

### 2.2 Google Veo 3.1 y Gemini Omni Flash

- **Veo 3.1:** modo P. **No acepta audio de entrada.**
  - Admite «Text-to-Video, Image-to-Video, Video-to-Video» (este último solo para extender clips de Veo) y hasta 3 imágenes de referencia.
  - El diálogo va entre comillas en el prompt; clips de 4/6/8 s, extensibles 7 s hasta 148 s; admite 9:16 ([ai.google.dev/gemini-api/docs/veo](https://ai.google.dev/gemini-api/docs/veo)) [DOC].
- **Gemini Omni Flash** (`gemini-omni-1.1-flash`): modo P.
  - Textual: «Uploading audio references is unsupported in the current version of the API» y «Voice editing is not supported».
  - Solo garantiza inglés: «other languages have not been evaluated».
  - Rechaza imágenes de «certain recognizable people».
  - Extiende de 10 s en 10 s hasta 40 s ([ai.google.dev/gemini-api/docs/omni](https://ai.google.dev/gemini-api/docs/omni)) [DOC].
  - Un tercero ([Muapi](https://muapi.ai/playground/gemini-omni-flash-1-1) [2ª]) anuncia «voice profiles»; **contradice la doc oficial**.
- **Precios** ([ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)) [PRECIO]:
  - Veo 3.1 con audio: Standard **0,40 USD/s**, Fast **0,10 USD/s (720p) / 0,12 (1080p)**, Lite **0,05 / 0,08 USD/s**.
  - Omni Flash: **≈0,10 USD/s a 720p** (17,50 USD por millón de tokens × 5.792 tokens/s).
- **Para usarlos con nuestra voz:** solo con un lip-sync posterior (§2.13).

### 2.3 MiniMax (Hailuo / H3 y MiniMax Speech)

- **Video — MiniMax H3 / H3-Max: modo T.**
  - `reference_audio` ≤3 clips, 2–15 s cada uno, ≤15 s en total. El ejemplo oficial dice: «Character speaks: … **Voice timbre follows reference audio 1**» ([video-generation-v2-create](https://platform.minimax.io/docs/api-reference/video-generation-v2-create.md)) [DOC].
  - Mismo patrón que Seedance: el guion va en el prompt y el audio solo da el timbre.
  - Duración 4–15 s (H3) / 5–15 s (H3-Max).
  - **Precio:** H3 a **0,08 USD/s (768P)** y 0,13 USD/s (2K); H3-Max a 0,05 (480P) / 0,08 (768P). **«Audio input: Free»** ([pricing](https://platform.minimax.io/docs/guides/pricing)) [PRECIO].
  - Los Hailuo 02 / 2.3 pasan a «Legacy Models» (0,28–0,56 USD por clip de 6–10 s). La página no dice si generan o aceptan audio.
- **Voz — MiniMax Speech: clonador utilizable como origen.**
  - Muestra de **10 s a 5 min** (mp3/m4a/wav, ≤20 MB); audio de ejemplo opcional <8 s ([speech-voice-clone](https://platform.minimax.io/docs/guides/speech-voice-clone.md)) [DOC].
  - **1,5 USD por voz**, «charged when the cloned voice is first used for synthesis».
  - Síntesis: speech-2.8-hd a **100 USD por millón de caracteres** (turbo 60) [PRECIO].
  - Si la voz no se usa en 7 días, se borra.
  - **Tiene API de borrado** (`Delete Voice`); Seed Speech no.
  - `text_validation` + `accuracy` rechazan la muestra si no coincide con un texto dado: sirve para una frase de consentimiento leída, como en Seed Speech ([voice-cloning-clone](https://platform.minimax.io/docs/api-reference/voice-cloning-clone.md)) [DOC].
  - `language_boost` incluye «Spanish»; no distingue es-MX.

### 2.4 Wan (Alibaba Cloud Model Studio)

- **Wan 2.5 / 2.6 image-to-video con `audio_url`: modo A probable.**
  - Doc textual: «The model generates the video using this audio». WAV/MP3, 3–30 s, ≤15 MB; si el audio es más largo que el video (5 o 10 s), se recorta ([image-to-video-api-reference](https://www.alibabacloud.com/help/en/model-studio/image-to-video-api-reference)) [DOC].
  - **La doc no dice explícitamente «lip-sync»:** que los labios sigan nuestro audio es **no verificado**.
- **wan2.2-s2v («speech-to-video», humano digital): modo A explícito.** Imagen + audio → video que habla o canta. **Solo región Pekín** y concurrencia 1 ([wan-s2v-overview](https://www.alibabacloud.com/help/tc/model-studio/wan-s2v-overview/)) [DOC].
- **Precios** ([model-pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)) [PRECIO]:
  - Internacional (Singapur): wan2.6-i2v a **0,10 USD/s (720p) / 0,15 (1080p)**; wan2.6-i2v-flash a 0,05 / 0,075 con audio; wan2.5-i2v-preview a 0,05 (480p) / 0,10 / 0,15.
  - wan2.2-s2v (Pekín): 0,071677 USD/s (480P) / **0,129018 USD/s (720P)**.

### 2.5 Runway

- **Act-Two** (`/v1/character_performance`): transfiere la actuación de un **video de referencia** (una persona actuando) a un personaje. **No acepta audio**: hace falta un actor grabado. 5 créditos/s = 0,05 USD/s ([guides/pricing](https://docs.dev.runwayml.com/guides/pricing)) [PRECIO].
- **«Generate avatar video from audio or text»** (`POST /v1/avatar_videos`): aparece en el índice de la API ([docs.dev.runwayml.com/api](https://docs.dev.runwayml.com/api/)) [DOC], pero **no figura en la tabla de precios**. Su precio y su comportamiento con un audio externo: **no verificados**.
- La tabla de Runway **no tiene ningún modelo de lip-sync** sobre video.
- **Dato útil:** Runway revende **Seedance 2.5 a 30 créditos/s a 720p (0,30 USD/s)**, «images and audio free». Es más caro que BytePlus directo (0,231 USD/s), pero **confirma que el audio de referencia no se cobra**.

### 2.6 Hedra Character-3

- **Modo A.** Imagen inicial + `audio` obligatorio.
  - 1–4 audios (uno por hablante, para multi-hablante), 0,5–600 s cada uno; el video dura lo que el audio.
  - 540p / 720p / 1080p, con 9:16 ([run-hedra-character-3](https://www.hedra.com/docs/api-reference/v3/run-a-model/run-hedra-character-3-hedra-character-3.md)) [DOC].
- **Precio** ([página del modelo](https://www.hedra.com/models/video/hedra/character-3)) [PRECIO]: **0,025 USD/s (540p) · 0,05 USD/s (720p) · 0,0625 USD/s (1080p)**.
  - El símbolo es «¢»; que sean USD es inferencia.
  - Terceros citan 6–8 créditos/s ([dailyaifixs](https://dailyaifixs.com/blog/hedra-pricing-2026-credits-burn-by-the-second) [2ª]): la fuente oficial manda.
- Revende clonado de ElevenLabs (`elevenlabs-voice-clone`) dentro de su API.

### 2.7 Sync.so (lip-sync puro, modo L)

- **Qué hace:** video + audio → mismo video con labios resincronizados.
  - Funciona sobre personajes generados por IA, pero el personaje «must look like it's talking»: con lipsync-2/2-pro un personaje estático puede no mover los labios; sync-3 «can open silent lips».
  - lipsync-2/2-pro generan la cara a 512×512 («usually sufficient for 1080p»); sync-3 trabaja en 4K nativo ([sync.so/docs/models](https://sync.so/docs/models)) [DOC].
- **Precios por segundo de salida** ([billing](https://sync.so/docs/product/billing.mdx)) [PRECIO]:

| Modelo | Hobbyist/Creator | Growth | Scale |
|---|---|---|---|
| lipsync-1.9.0-beta | 0,025 | 0,024 | 0,02 |
| lipsync-2 | 0,05 | 0,048 | 0,04 |
| **lipsync-2-pro** | **0,083** | 0,079 | 0,067 |
| sync-3 | 0,133 | 0,127 | 0,107 |
| TTS propio | 0,004 | 0,0038 | 0,0032 |

- **Planes:** 5 / 19 / 49 / 249 USD al mes, con concurrencia 1 / 3 / 6 / 15 y video de 1 a 30 min ([sync.so/pricing](https://sync.so/pricing)) [PRECIO].
- **Contradicción:** la página de planes muestra un «usage rate» genérico de 0,05 USD/s, y la de billing habla de «legacy usage plans» y de «credit-billed accounts use different pricing». Hay que confirmarlo en el dashboard.
- `sync_mode: cut_off` cobra la pista más corta (video o audio).

### 2.8 Veed Fabric 1.0

- **Modo A.** `image_url` + `audio_url` obligatorios. **0,08 USD/s (480p) · 0,15 USD/s (720p)** vía fal ([fal.ai/models/veed/fabric-1.0](https://fal.ai/models/veed/fabric-1.0)) [PRECIO de revendedor oficial].
- Contradicción: el soporte de VEED cita 0,05 USD/s y un máximo de 1 min por llamada ([support.veed.io](https://support.veed.io/en/articles/15230480-veed-fabric-1-0-api) [DOC]).

### 2.9 Creatify Aurora

- **Modo A.** Foto («real or AI-generated») + audio MP3/WAV. «The video is as long as the audio».
  - `aurora_v2`: hasta 59,7 s de audio y 480p–2k.
  - No documenta consentimiento ni restricciones de persona real ([aurora.md](https://docs.creatify.ai/api-documentation/aurora/aurora.md)) [DOC].
- **Precio:**
  - `aurora_v2`: **0,4 / 0,7 / 1,4 / 2,8 créditos/s** (480p / 720p / 1080p / 2k); `aurora_v1_fast`: 0,5 créditos/s.
  - Créditos solo por suscripción: **API Starter 99 USD/mes = 500 créditos (0,198 USD/crédito); API Pro 299 USD/mes = 2.000 (0,15 USD/crédito)** ([billing.md](https://docs.creatify.ai/billing.md)) [PRECIO].
  - Vía fal: 0,07 USD/s (480p) / 0,14 USD/s (720p), «pending final confirmation» ([labs.creatify.ai](https://labs.creatify.ai/) [DOC]).

### 2.10 OmniHuman 1.5 / 2.0 (BytePlus Vision)

- Ya cubierto en [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md). **Modo A.**
  - Imagen + `audio_url`; 0,12 USD/s (1.5) / 0,07 USD/s (2.0).
  - Vía fal, 1.5 a 0,16 USD/s ([fal](https://fal.ai/models/fal-ai/bytedance/omnihuman/v1.5), reconfirmado el 2026-10-15).
- **No acepta video de entrada:** no sirve para resincronizar un clip de Seedance. Solo puede **reemplazar** a Seedance partiendo de una imagen (por ejemplo, el último fotograma de Seedance o una imagen de Seedream).
  - La entrada de video de OmniHuman solo consta en el paper de investigación, no en la API ([DataCamp](https://www.datacamp.com/pl/blog/omnihuman) [2ª]): **no verificado**.

### 2.11 HeyGen

- **Modo A en avatares:** `POST /v3/videos` con `audio_url` / `audio_asset_id` (ya en `heygen_video.py`).
- **Modo L, nuevo para nosotros: Lipsync API** (`POST /v3/lipsyncs`).
  - Textual: «You bring the video *and* your own audio; the engine redraws the mouth to match. No translation, no audio generation».
  - Modos `speed` y `precision` («avatar-inference lip-sync»).
  - `enable_dynamic_duration` (por defecto `true`) ajusta la duración del video a la del audio; también `start_time`/`end_time`, `keep_the_same_format`, `callback_url` y lotes de 100 ([lipsync-speed](https://developers.heygen.com/lipsync-speed.md), [lipsync-precision](https://developers.heygen.com/lipsync-precision.md)) [DOC].
- **Precios** ([help center, «updated yesterday»](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained); el pie dice «Last updated on September 16, 2026») [PRECIO]:
  - «Lipsync Audio mode — you can upload your own audio to be lipsynced»: **Speed 0,84 USD/min · Precision 1,74 USD/min**.
  - Avatar IV Photo 2,31 USD/min · Starfish TTS 0,12 USD/min.
  - Que `POST /v3/lipsyncs` se facture con la tarifa «Lipsync Audio mode» de esa tabla es **inferencia**: la tabla está bajo «Video Translation».
  - Terceros dan 2 USD/min (Speed) y 4 USD/min (Precision) ([G2](https://www.g2.com/articles/heygen-api-pricing) [2ª]): **contradicción**; la tabla oficial manda.

### 2.12 ElevenLabs (Image & Video)

- En la **app/Studio** ofrece modelos de terceros (Sora 2, Veo 3.1, Kling, Seedance 1 Pro, Wan 2.5…).
  - Lip-sync textual: «Perfectly align speech and motion with **Veed or OmniHuman** lip-sync» ([elevenlabs.io/video](https://elevenlabs.io/video)) [DOC].
  - **No hace lip-sync propio:** une sus voces (incluidas las clonadas, presumiblemente) con Fabric u OmniHuman.
- **API:** la página no aclara si el flujo de video existe por API. Precio por video no publicado; la FAQ dice «Video generation requires a paid plan» y la tabla lo contradice. **No verificado** como componente de backend.
- Como **clonador** sí es fuente válida:
  - Instant Voice Cloning desde Starter (6 USD/mes) y Professional desde Creator (22 USD/mes) ([pricing](https://elevenlabs.io/pricing)).
  - TTS a **0,08 USD por 1.000 caracteres** (v3/v4/multilingual v2) y 0,04 (Flash/Turbo) ([pricing/api](https://elevenlabs.io/pricing/api)) [PRECIO].

### 2.13 Flujo combinado: video de Seedance sin nuestra voz → lip-sync posterior

1. Sintetizar el guion con la voz clonada → **MP3 en R2**. Su duración marca la del clip.
2. Generar la escena con Seedance:
   - Personaje **hablando**: `generate_audio: true` con el mismo guion entre comillas, para que la boca se mueva con ritmo de habla; los proveedores de lip-sync piden que el personaje «look like it's talking».
   - `duration` ≥ duración del MP3. Con 2.5 cabe un reel de 30 s en una sola tarea; con 2.0 son 2 tareas de ≤15 s, y el MP3 se parte en los mismos cortes.
   - Copiar el MP4 a R2 en menos de 24 h (la URL de ModelArk caduca).
3. Lip-sync con **nuestro MP3** sobre ese MP4:
   - **HeyGen** `POST /v3/lipsyncs` `mode: precision`: 1,74 USD/min.
   - o **Sync.so** lipsync-2-pro (0,083 USD/s) / sync-3 (0,133 USD/s).
   - o Kling Lip-Sync (precio no verificado).
   - La salida sustituye la pista de Seedance por nuestro audio.
4. **No sirven para el paso 3:** OmniHuman, Hedra, Fabric y Aurora (necesitan **imagen**, no video) ni Veo/Omni (sin audio de entrada).
   - Sí pueden ser **alternativas a Seedance** en planos de «persona que habla a cámara», partiendo de una imagen.
5. Sin verificar en vivo:
   - la calidad del lip-sync en **español** sobre caras generadas por Seedance;
   - si la Precision de HeyGen respeta el movimiento de cámara de Seedance;
   - si el paso de HeyGen acepta caras **no humanas** (mascotas de marca).

**¿Se puede saltar el paso 3 con la tarea `edit` de Seedance 2.5** («replace the vocals in @Video 1 with @Audio 1 and sync the lips»)? Las docs solo enseñan re-doblaje con **voz sintetizada desde texto**. Pasar nuestro MP3 como `reference_audio` en un `edit` es **hipótesis no documentada**. Probarlo en el spike cuesta ≈8,3 USD por 30 s a 720p (§1.6), más que HeyGen Precision (0,87 USD por 30 s).

## 3. Clonadores de voz utilizables como fuente

| Clonador | ¿Exporta el audio sintetizado por API? | Muestra | Costo por reel de 30 s (~500 caracteres) | Alta de la voz | Borrado por API | Español | Fuente |
|---|---|---|---|---|---|---|---|
| **HeyGen, el clon actual** (`POST /v3/voices/clone`, Starfish) | **Sí**: «The resulting voice can be used with POST /v3/voices/speech» → `audio_url` (MP3 en el ejemplo) + `word_timestamps` | ~30 s (código actual) | **≈0,06 USD** (Starfish 0,12 USD/min; un tercero dice 0,04 USD/min, **contradicción**) | plan de pago; slots limitados (`resource_limit_reached`) | **Sí** (`DELETE /v3/voices/{id}`) | `language` (`es`); sin variante regional | [clone-a-voice](https://developers.heygen.com/reference/clone-a-voice.md), [generate-speech](https://developers.heygen.com/reference/generate-speech.md), [help](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) |
| HeyGen Voice (nuevo instant clone, `POST /v3/models/audio/voices`) | Sí: `POST /v3/models/audio/tts` → WAV mono 44,1 kHz; 30 RPM | 1 grabación (usa 3 min) | **no publicado** (un tercero: 15 USD/M caracteres, no verificado) | gratis «during the preview» | Sí | no especifica región | [heygen-voice](https://developers.heygen.com/docs/models/heygen-voice.md), [TTS](https://developers.heygen.com/docs/voices/heygen-voice-speech) |
| **Seed Speech `seed-icl-2.0`** | Sí (HTTP/WebSocket; mp3/ogg/pcm) | 10–30 s | **≈0,015 USD** | 2 USD por voz, en la 1.ª síntesis | **No** (no documentado) | **es-MX explícito (`mx`)** | [investigación previa](investigacion-voz-seed-speech-vs-heygen.md) |
| MiniMax Speech (speech-2.8-hd) | Sí (T2A sync/async) | 10 s – 5 min | **≈0,05 USD** | **1,5 USD por voz**, en el 1.er uso; se borra si no se usa en 7 días | **Sí** | «Spanish» genérico | §2.3 |
| ElevenLabs (v3/v4) | Sí | instant ~30 s+; professional más | **≈0,04 USD** (+ plan de 6–22 USD/mes) | incluido en el plan | Sí (no reverificado hoy) | clona el acento de la muestra (no verificado) | §2.12 |
| Sync.so (TTS + clones) | Sí, dentro de su flujo de dubbing | — | 0,004 USD/s → 0,12 USD | 3–50 clones según plan; precio no publicado | — | — | [billing](https://sync.so/docs/product/billing.mdx) |

**Lectura:**
- **Todas las opciones de la tabla exportan audio.** En todas, el costo de la voz es de **0,015–0,12 USD por reel**: menos del 5 % del video.
- Lo que decide la fuente es otra cosa:
  1. español latino;
  2. si se puede borrar la voz (derecho de supresión);
  3. que el consentimiento quede registrado;
  4. no duplicar datos biométricos en varios proveedores.
- **Matiz importante sobre el clon HeyGen actual:**
  - La página de `/v3/voices/speech` se presenta como síntesis de «catalog voices (stock, designed)». La **referencia** de `clone-a-voice` dice que el clon resultante funciona en ese endpoint.
  - **No verificado en vivo** que un clon creado por nuestro adaptador devuelva audio en `/v3/voices/speech` con `engine: starfish`.
  - La licencia de uso del audio fuera de HeyGen **no está documentada** en estas páginas.

## 4. Costos

Supuestos:
- Reel de **30 s, 9:16, 720p** (1080p solo donde se indica).
- Guion de ~500 caracteres; un intento.
- Columna «con reintentos» = ×1,5, como en [costos-comparativos-herramientas-ia.md](costos-comparativos-herramientas-ia.md).
- Voz = Seed Speech (0,015 USD) salvo que se indique. Cambiar a HeyGen Starfish suma 0,045 USD por reel.
- Los cálculos sobre precio unitario oficial están marcados «(cálculo)».

### 4.1 Tabla maestra: motor → audio externo / lip-sync exacto / voz propia → costo por reel de 30 s

| # | Motor / ruta | ¿Acepta audio externo? | ¿Lip-sync exacto a nuestro MP3? | ¿Voz propia o clonado? | Precio unitario | **Reel 30 s (USD)** | **100 reels/mes (USD)** | Con reintentos | Fuente |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Seedance 2.0 mini + timbre | Sí, como `reference_audio` (2–15 s) | **No** (re-síntesis) | genera la suya | 3,5 USD/M tokens = 0,076 USD/s | **≈2,28** (cálculo; 2 tareas) | ≈228 | ≈342 | [model-pricing](https://docs.byteplus.com/en/docs/modelark/model-pricing) |
| 2 | Seedance 2.0 / 2.0 fast + timbre | Sí (2–15 s) | No | genera la suya | 0,151 / 0,121 USD/s | ≈4,55 / ≈3,64 | ≈455 / ≈364 | ≈683 / ≈546 | idem |
| 3 | Seedance 2.5 + timbre (una tarea de 30 s) | Sí (2–30 s; admite **solo audio**) | No | genera la suya | 10,70 USD/M tokens = 0,231 USD/s | ≈6,95 | ≈695 | ≈1.042 | idem |
| 4 | **Seedance 2.0 mini → HeyGen Lipsync Precision** | Sí | **Sí** | nuestra voz | 0,076 USD/s + 1,74 USD/min | **≈3,16** | **≈316** | ≈474 | idem + [HeyGen help](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) |
| 5 | Seedance 2.0 mini → HeyGen Lipsync Speed | Sí | Sí (menor fidelidad) | nuestra voz | + 0,84 USD/min | ≈2,71 | ≈271 | ≈407 | idem |
| 6 | Seedance 2.0 mini → Sync lipsync-2-pro (Creator) | Sí | Sí | nuestra voz | + 0,083 USD/s | ≈4,78 | ≈478 + 19 de plan | ≈717 | [sync billing](https://sync.so/docs/product/billing.mdx) |
| 7 | Seedance 2.0 mini → Sync sync-3 | Sí | Sí («can open silent lips») | nuestra voz | + 0,133 USD/s | ≈6,28 | ≈628 + plan | ≈942 | idem |
| 8 | Seedance 2.5 → HeyGen Precision | Sí | Sí | nuestra voz | 0,231 USD/s + 1,74 USD/min | ≈7,82 | ≈782 | ≈1.173 | idem |
| 9 | Seedance 2.5 `edit` (re-doblaje propio) | (hipótesis) | **no documentado** con audio dado | genera la suya | (30 + 30) s de tokens × 6,40 USD/M | ≈8,29 + el clip | — | — | §1.6 |
| 10 | OmniHuman 2.0 (imagen + audio) | **Sí** | **Sí** | no tiene TTS | 0,07 USD/s | ≈2,12 | ≈212 | ≈318 | [investigación previa](investigacion-avatar-omnihuman-vs-heygen.md) |
| 11 | HeyGen Avatar IV Photo/imagen + `audio_url` | **Sí** | **Sí** | TTS + clon propios | 2,31 USD/min (blog: 3,00) | ≈1,17–1,52 | ≈117–152 | ≈176–228 | [help](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) |
| 12 | Kling Avatar 720p (1080p) | **Sí** | **Sí** | custom voice (no verificado) | 0,056 (0,112) USD/s | ≈1,70 (≈3,38) | ≈170 (≈338) | ≈255 | [kling.ai/dev/pricing](https://kling.ai/dev/pricing) |
| 13 | Kling 3.0 con audio nativo | No | No | genera la suya; «Voice Control» sin precio | 0,126 USD/s | ≈3,78 | ≈378 | ≈567 | idem |
| 14 | Veo 3.1 Fast (+ HeyGen Precision) | **No** | solo con un paso L | genera la suya | 0,10 USD/s | 3,00 (≈3,89 con L) | 300 (≈389) | ≈584 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| 15 | Veo 3.1 Standard / Lite | No | No | genera la suya | 0,40 / 0,05 USD/s | 12,00 / 1,50 | 1.200 / 150 | — | idem |
| 16 | Gemini Omni Flash 1.1 | **No** («unsupported») | No | genera la suya (EN evaluado) | ≈0,10 USD/s | ≈3,00 | ≈300 | ≈450 | [omni](https://ai.google.dev/gemini-api/docs/omni) |
| 17 | MiniMax H3 768P + timbre (+ MiniMax Speech) | Sí, como timbre (entrada gratis) | No | clon MiniMax Speech | 0,08 USD/s | ≈2,45 (+1,5 por voz una vez) | ≈245 | ≈368 | [MiniMax pricing](https://platform.minimax.io/docs/guides/pricing) |
| 18 | Wan 2.6 i2v (`audio_url`), 720p / flash | **Sí** | probable, **no verificado** | — | 0,10 / 0,05 USD/s | ≈3,02 / ≈1,52 | ≈302 / ≈152 | ≈453 | [Alibaba pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing) |
| 19 | wan2.2-s2v 720p (solo Pekín) | **Sí** | **Sí** (S2V) | — | 0,129 USD/s | ≈3,89 | ≈389 | ≈584 | idem |
| 20 | Runway Act-Two | No (video de actuación) | No | — | 0,05 USD/s | 1,50 + actor grabado | — | — | [Runway pricing](https://docs.dev.runwayml.com/guides/pricing) |
| 21 | **Hedra Character-3** 720p (1080p) | **Sí** | **Sí** | revende ElevenLabs | 0,05 (0,0625) USD/s | **≈1,52** (≈1,89) | ≈152 (≈189) | ≈228 | [Hedra](https://www.hedra.com/models/video/hedra/character-3) |
| 22 | Veed Fabric 1.0 720p (480p) | **Sí** | **Sí** | — | 0,15 (0,08) USD/s | ≈4,52 (≈2,42) | ≈452 (≈242) | ≈678 | [fal](https://fal.ai/models/veed/fabric-1.0) |
| 23 | Creatify Aurora v2 720p | **Sí** | **Sí** | — | 0,7 créditos/s × 0,15–0,198 USD | ≈3,15–4,17 | ≈315–417 (suscripción mínima de 99 USD) | ≈473–625 | [Creatify billing](https://docs.creatify.ai/billing.md) |
| 24 | ElevenLabs Image & Video | Sí (sus voces) | vía Veed u OmniHuman | clonado propio | no publicado | — | — | — | [elevenlabs.io/video](https://elevenlabs.io/video) |

**Contradicciones de precio detectadas:**
- **HeyGen:**
  - Avatar IV Photo: 2,31 USD/min (help center) frente a 3,00 USD/min (blog).
  - Lipsync: 0,84/1,74 USD/min (help center) frente a 2/4 USD/min ([G2](https://www.g2.com/articles/heygen-api-pricing) [2ª]).
  - Starfish: 0,12 frente a 0,04 USD/min.
  - El help center dice «updated yesterday» y en el pie «Last updated on September 16, 2026».
- **Sync.so:** usage rate genérico de 0,05 USD/s (planes) frente a tarifas por modelo (billing, «legacy usage plans»).
- **Veed Fabric:** 0,08–0,15 USD/s (fal y VEED) frente a 0,05 USD/s (soporte de VEED).
- **Creatify Aurora:** créditos de la API frente a 0,07–0,14 USD/s vía fal («pending final confirmation»).
- **Seedance:** la tabla interna de costos usaba la tarifa «con video de entrada» para un caso sin video (§1.6).
- **Gemini Omni:** la doc oficial dice sin audio de entrada; Muapi dice «voice profiles».
- **Kling Lip-Sync:** sin precio en la tabla oficial; los terceros difieren 2,5×.

### 4.2 Costos fijos o de entrada

| Proveedor | Fijo |
|---|---|
| Seedance 2.x | saldo > 30 USD para activar (no es cuota mensual) |
| HeyGen API | prepago por uso desde 5 USD ([G2](https://www.g2.com/articles/heygen-api-pricing) [2ª]); ya lo tenemos |
| Sync.so | 5–249 USD/mes según plan (concurrencia 1–15) |
| Creatify | 99 o 299 USD/mes (créditos incluidos) |
| ElevenLabs | 6–22 USD/mes para clonar |
| MiniMax / Hedra / Kling / Wan | pago por uso (Kling: paquetes de recursos; precio por paquete no reverificado) |

## 5. Calidad del lip-sync: lo que se sabe y lo que no

- **No hay ningún benchmark independiente** que compare estos motores en **español** sobre caras generadas. Todas las afirmaciones de calidad son del fabricante.
- **Seedance:**
  - BytePlus admite que el timbre de referencia «differs significantly» sin una descripción de voz en el prompt.
  - El re-doblaje 2.5 tiene fallos documentados: voces asignadas al personaje equivocado, restos del idioma original, «Ripple-like audio artifacts» ([seedance-2-5-prompt-guide](https://docs.byteplus.com/en/docs/modelark/seedance-2-5-prompt-guide)).
- **Sync.so:** documenta sus límites (cara a 512×512 en lipsync-2/2-pro; personajes estáticos).
- **HeyGen:** «Precision» se describe como «frame-accurate… for cinematic content» (fabricante).
- **Criterio:** un A/B propio con el mismo MP3 en español sobre el mismo clip de Seedance: HeyGen Precision frente a Sync lipsync-2-pro frente a Sync sync-3. El costo de la prueba es inferior a 15 USD.

## 6. Recomendación para Qualify

**Fuente única de la voz de la marca: Seed Speech `seed-icl-2.0`.** Es coherente con [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md):
- es-MX explícito;
- muestra de 10–30 s;
- ≈0,015 USD por reel;
- mismo proveedor que Seedance.

Condiciones:
- La fuente entrega siempre lo mismo: **un MP3 por guion en R2**, con clave idempotente (*voice-as-audio*). Así ningún motor necesita conocer el `speaker_id`, y la fuente se puede cambiar sin tocar los motores.
- **Puente mientras no se haga el spike de Seed Speech:** el clon HeyGen que ya existe, vía `POST /v3/voices/speech` (≈0,06 USD por reel).
  - No hace falta clonar de nuevo ni pedir otro consentimiento.
  - Está documentado, pero falta verificarlo en vivo con un clon de nuestro adaptador.
- **Riesgo que obliga a decidir antes de migrar:** Seed Speech **no tiene borrado por API**; HeyGen y MiniMax sí. Si el derecho de supresión de la voz es requisito duro, **MiniMax Speech** es la alternativa (1,5 USD por voz, borrado por API, chequeo de texto leído), a costa de perder es-MX explícito.

**Ruta para que Seedance «hable» con la voz de la marca:**
1. **Exacta (por defecto para piezas publicables): Seedance genera la escena y HeyGen Lipsync Precision pone nuestra voz.**
   - Seedance 2.0 mini con el personaje hablando y el mismo guion; el MP3 en R2; después `POST /v3/lipsyncs` con `mode: precision` y `audio` = nuestro MP3.
   - **≈3,16 USD por reel · ≈316 USD por 100 reels (≈474 USD con reintentos).**
   - HeyGen ya está integrado (cuenta, clave, `upload_asset`, sondeo). Solo hay que añadir el endpoint de lipsync.
   - Con Seedance 2.5 (un reel de 30 s en una sola tarea, sin costuras): ≈7,82 USD.
2. **Barata (borradores y previsualización): Seedance con timbre.**
   - `reference_audio` = un clip de 10–15 s **sintetizado** por la fuente única, no la grabación cruda de la persona; así la muestra biométrica no sale a un segundo proveedor (en 2.0, junto a una imagen o video de referencia).
   - ≈2,28 USD por reel.
   - **Debe etiquetarse como «voz aproximada»:** no es la voz exacta.
3. **A/B antes de fijar el paso de lip-sync:** HeyGen Precision frente a **Sync.so lipsync-2-pro** (≈4,78 USD por reel) y sync-3. El ganador en español queda como proveedor de lip-sync.
4. **Para planos de «persona que habla a cámara»** sin escena de Seedance, sigue valiendo [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md):
   - HeyGen Avatar IV con `audio_url` (≈1,17 USD).
   - Kling Avatar (≈1,70 USD) y Hedra Character-3 (≈1,52 USD) entran como candidatos baratos del mismo A/B.
5. **Descartados como destino de la voz clonada:**
   - Veo 3.1 y Gemini Omni (sin entrada de audio).
   - MiniMax H3 (solo timbre, como Seedance).
   - Runway Act-Two (necesita un actor grabado).

**Fase del roadmap:**
- Generación de piezas y voz de marca = carril creativo de *dogfooding* (ADR 21, Parte 4-A), no el pipeline de escucha de la Fase 1.
- Proveedores de voz y de lip-sync = **buy** (commodity), por la regla de `CLAUDE.md`.

**Spike pendiente** (sin llamadas de pago hasta que se apruebe):
1. Que `POST /v3/voices/speech` devuelva audio con un clon de `POST /v3/voices/clone`.
2. Seedance 2.0 mini con el personaje hablando → HeyGen Precision con el MP3; medir la sincronía en español.
3. Lo mismo con Sync lipsync-2-pro.
4. Si un `edit` de Seedance 2.5 con `@Audio 1` reproduce el audio literal.
5. `usage.completion_tokens` con y sin `reference_audio`, para confirmar que el audio no se cobra.

Costo estimado del spike: **< 30 USD** más el saldo mínimo de activación de Seedance.
