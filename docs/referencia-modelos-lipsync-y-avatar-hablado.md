# Referencia: modelos de lip-sync y de avatar hablado

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[REFERENCIA 2026-10-15]` · fuentes consultadas el 2026-10-15 · **sin llamadas de pago ni en vivo a ninguna API de generación**

Marcas:
- **[DOC]**: documentación oficial del fabricante. En BytePlus y Volcengine, el Markdown se extrajo de `window._ROUTER_DATA…curDoc.MDContent`; entre paréntesis va la fecha de actualización de la página.
- **[PRECIO]**: página de precios oficial del fabricante.
- **[REV]**: revendedor (fal.ai, Replicate, kie.ai). Su precio es **el del revendedor**, no el del fabricante.
- **[2ª]**: tercero (blog, comparativa).
- **[GH]** / **[HF]**: repositorio de GitHub o ficha de Hugging Face, leídos por API el 2026-10-15.
- **no verificado**: no confirmado en fuente primaria.
- **(cálculo)**: cifra derivada por nosotros de un precio unitario oficial.

**Caso de uso que ordena todo el documento:** reels de marketing de 30 s, 9:16, en los que una persona (o un personaje) dice el guion de la marca **con la voz clonada de la marca**. La voz la sintetiza Seed Speech o HeyGen y llega como **un MP3 por guion** (patrón *voice-as-audio*). La pregunta clave para cada modelo es: **¿acepta nuestro MP3 tal cual y mueve los labios con él?**

Este documento es un índice de referencia. No repite lo ya verificado; lo enlaza:
- [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md): Seedance y el audio, HeyGen Lipsync, Sync.so, Kling, Hedra, Veed, Creatify, Wan, MiniMax, Runway, ElevenLabs.
- [avatar-reutilizable-voz-y-movimiento-bytedance.md](avatar-reutilizable-voz-y-movimiento-bytedance.md): OmniHuman, Clone Avatar, Flash Avatar, Interactive Avatar, DreamActor M2.0, real-person assets.
- [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md): caras reales en OmniHuman y edición con Seedance.
- [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md): OmniHuman frente a HeyGen.
- [costos-comparativos-herramientas-ia.md](costos-comparativos-herramientas-ia.md): costos por pieza.

**Encaje en el producto:** motor de compra = **activación** (generación de piezas). Fase = carril creativo de *dogfooding* (Parte 4-A, ADR 21), no el pipeline de escucha de la Fase 1. Regla de `CLAUDE.md`: lip-sync y avatar son **commodity → buy**. El autoalojamiento de modelos abiertos se documenta como referencia, no como recomendación.

---

## Resumen: qué usar hoy en cada familia y por qué

| Familia | Qué usar hoy | Por qué | Alternativa para el A/B |
|---|---|---|---|
| **A. Video + audio → video con labios nuevos** | **HeyGen Lipsync Precision** (`POST /v3/lipsyncs`) | Acepta **nuestro MP3 exacto** ([DOC]); ≈0,87 USD por 30 s directo ([PRECIO] help center); la cuenta, la key y el adaptador ya existen | **Sync.so lipsync-2-pro / sync-3** (≈2,0–4,0 USD por 30 s); **LatentSync vía fal** (0,20 USD por vídeo ≤40 s) como línea base barata |
| **B. Foto + audio → video hablado** | **HeyGen Avatar IV** con `audio_url` | Acepta nuestro MP3; 9:16 nativo a 1080p; concurrencia 10; ≈1,16–1,50 USD por 30 s; ya integrado | **OmniHuman 2.0** (≈2,10–3,60 USD, cuerpo entero y cámara), **Kling Avatar** (≈1,68 USD) y **Hedra Character-3** (≈1,50 USD) |
| **C. Foto + video de movimiento → video** | **DreamActor M2.0** (BytePlus Vision AI) **+ un paso de la familia A** con nuestro MP3 | Copia movimiento, expresiones y labios del vídeo guía con caras reales ([DOC]); 0,05 USD/s; luego hay que resincronizar los labios con nuestro guion | **Kling Motion Control** (fal, 0,126–0,168 USD/s), **Wan-Animate** (fal 0,08 USD/s; abierto Apache-2.0) |

Hallazgos nuevos de esta pasada (no estaban en los documentos previos):
1. **ByteDance SÍ tiene un lip-sync vídeo→vídeo por API, pero solo en Volcengine (China):** AI MediaKit «视频口型对齐» (*video lip alignment*), `POST https://mediakit.cn-beijing.volces.com/api/v1/tools/lip-sync`, vídeo MP4 de una sola persona real de hasta 30 min + audio mp3/aac/wav/m4a/flac, **1 CNY por minuto de salida** ([DOC] Volcengine, 2026-08-27 / 2026-09-09 / 2026-09-24). **En BytePlus (internacional) no está publicado:** un buscador indexó dos páginas de BytePlus VOD con «lip-sync», pero el 2026-10-15 devuelven el documento vacío y no aparecen en el índice de 637 páginas. Detalle en §3.
2. **LatentSync (ByteDance, abierto) está alojado en fal a 0,20 USD por vídeo de hasta 40 s** ([REV]) y en Replicate (L40S, ≈0,11 USD por ejecución típica [REV]). Código Apache-2.0, pesos **OpenRAIL++** ([HF]): uso comercial permitido con restricciones de uso. VRAM de inferencia: 8 GB (v1.5) / 18 GB (v1.6) ([GH]).
3. **Los revendedores encarecen mucho HeyGen Lipsync:** fal cobra 0,05 USD/s (Speed) y 0,10 USD/s (Precision) = 3 y 6 USD/min, frente a 0,84 y 1,74 USD/min directos en HeyGen. Para HeyGen, ir directo.
4. **ElevenLabs no hace lip-sync propio.** Su FAQ: «At the moment, ElevenLabs does not offer lip syncing as part of Dubbing. Lip sync is available in Image & Video, Flows, and Studio via third party models» ([DOC]). En su API de vídeo, el único modelo que mueve labios con un audio dado es `creatify-aurora`.
5. **Captions/Mirage sí tiene API:** Mirage Avatar X (imagen o vídeo + audio → vídeo) a **0,15 USD/s en tramos de 6 s** directo ([PRECIO]); fal lo revende a 0,30 USD/s.
6. **No existe ningún benchmark independiente** de lip-sync en español. Todas las comparativas de calidad están firmadas por el fabricante o por los autores del modelo (§2, columna «calidad»).

---

## Glosario

| Término | Qué significa aquí |
|---|---|
| **Lip-sync** (sincronía labial) | Redibujar o generar la boca para que coincida con un audio. En sentido estricto, es la familia A: el vídeo ya existe y solo cambia la boca (a veces la cara). |
| **Dubbing / doblaje visual** | Lip-sync aplicado a un vídeo doblado a otro idioma. Los productos de «video translation» (HeyGen, D-ID, Captions) traducen, sintetizan la voz y aplican lip-sync; **la voz no es nuestro MP3**, salvo que se use su API de lip-sync suelta. |
| **Talking head / avatar hablado** | Familia B: de una foto (o un avatar entrenado) y un audio sale un vídeo de la persona hablando. |
| **Digital twin / avatar entrenado** | Avatar creado a partir de un vídeo de entrenamiento de la persona (HeyGen Digital Twin, BytePlus Clone Avatar, Tavus Phoenix, D-ID Premium+). Persistente, con ID. |
| **Motion transfer / animación por plantilla** | Familia C: una foto + un vídeo «guía» → vídeo de la persona de la foto haciendo los movimientos del guía. Los labios salen del guía, no de nuestro guion. |
| **Audio exacto** | El vídeo final suena con **nuestro MP3**, sin re-síntesis, y la boca lo sigue. Opuesto a «solo timbre» (Seedance, MiniMax H3): el modelo genera su propia voz parecida. |
| **RTF** (*real-time factor*) | Tiempo de proceso ÷ duración del audio. RTF 6 = 1 min de audio tarda 6 min. |
| **SyncNet / LSE-C, LSE-D** | Métricas académicas de sincronía labial (confianza y distancia). Las usan los papers; no miden naturalidad ni identidad. |

---

## 1. Tablas maestras por familia

Supuestos de costo en todas las tablas:
- Reel de **30 s, 9:16, 720p** salvo donde se indica; un intento; sin la voz (la voz cuesta 0,015–0,06 USD por reel, ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §3).
- Para la familia A se supone que el vídeo de entrada ya existe (su costo va aparte, §4).
- «Directo» = API del fabricante; «[REV]» = revendedor.
- Columna «¿nuestro audio?»: **Sí** = documentado que el vídeo se genera desde/para el audio dado; **Timbre** = solo imita la voz; **No** = no acepta audio.

### 1.A Video + audio → video con labios nuevos (lip-sync / dubbing)

| Modelo | Empresa / suite | Acceso | Entrada → salida (límites) | ¿Nuestro audio? | Caras reales / consentimiento | Precio oficial | **Reel 30 s** | Licencia |
|---|---|---|---|---|---|---|---|---|
| **HeyGen Lipsync Precision** | HeyGen API v3 | Directo; [REV] fal | vídeo + audio (URL o `asset_id`) → vídeo; mantiene formato con `keep_the_same_format`; `enable_dynamic_duration` | **Sí** («you bring the video *and* your own audio») | No documenta control de consentimiento para lip-sync | 1,74 USD/min ([PRECIO] help center) · fal 0,10 USD/s | **≈0,87** directo · 3,00 fal | Comercial |
| HeyGen Lipsync Speed | idem | idem | idem | Sí | idem | 0,84 USD/min · fal 0,05 USD/s | ≈0,42 · 1,50 fal | Comercial |
| **Sync.so lipsync-2** | Sync Labs | Directo; [REV] fal, Replicate | vídeo + audio → vídeo; cara a 512×512; vídeo de 1 min (Hobbyist) a 30 min (Scale+) | **Sí** | Solo caras humanas o humanoides; consentimiento **no documentado** en las páginas leídas | 0,04–0,05 USD/s | ≈1,20–1,50 | Comercial |
| **Sync.so lipsync-2-pro** | Sync Labs | idem | idem + superresolución por difusión; cara hasta 350×350 px | **Sí** | idem | 0,067–0,083 USD/s · fal 5 USD/min · Replicate 0,08325 USD/s | ≈2,01–2,49 | Comercial |
| **Sync.so sync-3** | Sync Labs | idem | idem; 4K nativo; perfiles y oclusiones; «can open silent lips» | **Sí** | idem | 0,107–0,133 USD/s · fal 8 USD/min | ≈3,21–3,99 | Comercial |
| Sync.so react-1 | Sync Labs | [REV] fal | vídeo + audio; además reajusta la emoción | Sí | idem | fal 10 USD/min | ≈5,00 fal | Comercial |
| **Kling Lip-Sync** | Kuaishou / Kling AI | Directo (sin precio en la tabla oficial); [REV] fal, Replicate | fal: vídeo **2–10 s**, 720p/1080p, ≤100 MB; audio 2–60 s, ≤5 MB | **Sí** | Filtro de seguridad por defecto; consentimiento no documentado | fal y Replicate 0,014 USD/s (fal redondea a tramos de 5 s) | ≈0,42 (3 llamadas de 10 s) | Comercial |
| **Veed Lipsync v2** | VEED | [REV] fal (modelo propio de VEED) | vídeo + audio → vídeo | **Sí** | no documentado | fal 0,07 USD/s (v1: 0,40 USD/min) | ≈2,10 (v1 ≈0,20) | Comercial |
| PixVerse Lipsync | PixVerse | [REV] fal | vídeo + audio (o texto) → vídeo | Sí | no documentado | fal 0,04 USD/s | ≈1,20 | Comercial |
| **Volcengine AI MediaKit 视频口型对齐** | **ByteDance / Volcengine** | Directo, **solo región cn-beijing**; [REV] kie.ai | MP4 de **una sola persona real**, cara frontal (≤45° de giro, ≤15° de inclinación), ≤30 min, sin HDR + audio mp3/aac/wav/m4a/flac → vídeo; RTF 6–8 | **Sí** («用音频内容驱动视频中人物的面部表情与口型») | Exige persona real (o dibujo de proporciones humanas); **no documenta consentimiento** | **1 CNY/min de salida** ([PRECIO] Volcengine) · kie.ai ≈0,04 USD/s | **≈0,5 CNY ≈ 0,07 USD** (cálculo, 1 USD ≈ 7,1 CNY supuesto) · kie.ai ≈1,20 | Comercial (nube china) |
| **LatentSync 1.5 / 1.6** | **ByteDance** (código abierto) | Autoalojado; [REV] fal, Replicate | vídeo + audio → vídeo; cara a 256 (1.5) / 512 px (1.6); 25 fps | **Sí** | Sin controles (es código) | fal 0,20 USD hasta 40 s, luego 0,005 USD/s · Replicate L40S 0,000975 USD/s (≈0,11 USD por ejecución típica) | **≈0,20** fal | Código Apache-2.0; pesos **OpenRAIL++** (comercial con restricciones de uso) |
| MuseTalk 1.5 | Tencent Music (Lyra Lab), abierto | Autoalojado; [REV] fal (cobro por cómputo, sin tarifa clara) | vídeo (o imagen) + audio → vídeo; cara 256×256; tiempo real (30 fps en V100) | Sí | — | — | GPU propia | Código MIT; modelo «available for any purpose, even commercially»; dependencias con licencia propia |
| Wav2Lip | IIIT Hyderabad / autores de Sync Labs | Autoalojado | vídeo + audio → vídeo; cara 96×96 (HD comercial 192×288 solo vía Sync) | Sí | — | — | GPU propia | **No comercial** («personal/research/non-commercial purposes») |
| VideoReTalking | Tencent AI Lab (OpenTalker), abierto | Autoalojado; fal no publica ficha | vídeo + audio → vídeo | Sí | — | — | GPU propia | Código Apache-2.0 (dependencias GFPGAN, GPEN…; verificar) |
| **InfiniteTalk** (vídeo→vídeo) | Meituan (MeiGen), abierto | Autoalojado; [REV] fal | vídeo + audio + prompt → vídeo; resincroniza **labios, cabeza, cuerpo y expresión**; 480p/720p; longitud ilimitada | Sí | — | fal 0,30 USD/s (×1,25 por encima de 81 fotogramas) | ≈9,0–11,3 fal | Apache-2.0 |
| Seedance 2.5 `edit` (re-doblaje) | ByteDance / BytePlus ModelArk | Directo | vídeo 4–30 s + prompt → vídeo con voz **sintetizada por Seedance** | **No documentado** con un audio dado | Rechaza caras reales salvo real-person asset | 6,40 USD/M tokens con vídeo de entrada | ≈8,29 (cálculo) | Comercial |

### 1.B Foto + audio → video hablado (avatar desde imagen)

| Modelo | Empresa / suite | Acceso | Entrada → salida (límites) | 9:16 | ¿Nuestro audio? | Caras reales / consentimiento | Precio oficial | **Reel 30 s** | Licencia |
|---|---|---|---|---|---|---|---|---|---|
| **HeyGen Avatar IV** (Photo / imagen arbitraria) | HeyGen API v3 | Directo; [REV] fal | imagen (o look) + `audio_url` o guion → vídeo; audio ≤10 min; 25 fps; 1080p por defecto | **Sí, nativo** | **Sí** | Photo/imagen: «HeyGen runs no consent check» | 2,31–3,00 USD/min (las páginas oficiales se contradicen) · fal 0,10 USD/s | **≈1,16–1,50** · 3,00 fal | Comercial |
| HeyGen Avatar V | HeyGen API v3 | Directo; [REV] fal (Digital Twin) | **solo Digital Twin** (no foto); `motion_prompt`; comprobación de elegibilidad | Sí | Sí | Twin: consentimiento por webcam obligatorio | 4,00–7,20 USD/min · fal 0,10 USD/s | ≈2,00–3,60 · 3,00 fal | Comercial |
| **OmniHuman 1.5** | ByteDance / BytePlus Vision AI | Directo (AK/SK, verificación empresarial); [REV] fal, Replicate | foto + audio <60 s → 720p/1080p; RTF 23–27; **concurrencia 1** | Sí (hereda el encuadre de la foto; inferencia) | **Sí** | Acepta caras reales según la doc; sin flujo de consentimiento (contractual) | 0,12 USD/s · fal y Replicate 0,16 USD/s | ≈3,60 · 4,80 [REV] | Comercial |
| **OmniHuman 2.0** | idem | Directo | foto (aspecto 0,4–2,5) + audio 4–300 s → 720p nativo; `enable_watermark` por defecto | Sí | **Sí** | idem | 0,07 o 0,12 USD/s (qué tarifa aplica: **no verificado**) | ≈2,10–3,60 | Comercial |
| OmniHuman 1.0 | idem | [REV] Replicate | foto + audio ≤30 s | — | Sí | idem | Replicate 0,14 USD/s | ≈4,20 | Comercial |
| **Kling Avatar** (v1 / v2, Standard / Pro) | Kuaishou / Kling AI | Directo; [REV] fal | imagen + audio + prompt → vídeo | no documentado en fal | **Sí** | Filtro de seguridad; «realistic humans, animals, cartoons» | 0,056 USD/s 720p · 0,112 USD/s 1080p ([PRECIO] kling.ai) · fal 0,0562 (Std) / 0,115 (Pro) | **≈1,68** (1080p ≈3,36) | Comercial |
| **Hedra Character-3** | Hedra | Directo; revende ElevenLabs para voz | imagen + 1–4 audios (0,5–600 s) → 540p/720p/1080p | **Sí** | **Sí** | no documentado | 0,05 USD/s 720p · 0,0625 USD/s 1080p | **≈1,50** (1080p ≈1,88) | Comercial |
| **Veed Fabric 1.0** (y Fast) | VEED | [REV] fal (revendedor oficial) | imagen + audio → 480p/720p; ≤1 min por llamada (soporte de VEED) | no documentado | **Sí** | no documentado | fal 0,08 (480p) / 0,15 (720p) USD/s; Fast 0,10 / 0,20; soporte VEED cita 0,05 | ≈4,50 (480p ≈2,40) | Comercial |
| **Creatify Aurora v2** | Creatify | Directo (suscripción); [REV] fal; dentro de la API de ElevenLabs | foto «real or AI-generated» + MP3/WAV ≤59,7 s → 480p–2k | no documentado | **Sí** | No documenta consentimiento | 0,7 créditos/s a 720p (0,15–0,198 USD/crédito) · fal 0,14 USD/s | ≈3,15–4,16 · 4,20 fal | Comercial |
| **Mirage Avatar X** | Captions / Mirage | Directo (Mirage API); [REV] fal | imagen **o vídeo** de referencia + audio 3–180 s → vídeo; referencia de vídeo ≤120 s; 9:16 o 16:9 | **Sí** | **Sí** | no documentado | **0,15 USD/s en tramos de 6 s** · fal 0,30 USD/s | **≈4,50** · 9,00 fal | Comercial |
| **Tavus** (Phoenix-4 / 4.5) | Tavus | Directo | «face» (`replica_id`) entrenada desde foto o vídeo + guion o `audio_url` → vídeo | no verificado | **Sí** | Solo sujetos humanos o humanoides; flujo de guion de consentimiento para réplicas personales | Starter 59 USD/mes con 10 min y 1 USD/min extra; Growth 397 USD/mes con 100 min y 0,90 USD/min (la página muestra dos versiones de precios) | ≈0,45–0,50 + plan | Comercial |
| **D-ID** (V2 Photo, V3 Pro, V4 Expressive) | D-ID | Directo | foto + texto o audio → vídeo; V4 con «sentiments» | no verificado | Sí en V2 (`talks`); resto no verificado | no verificado | **No verificado**: la página de precios solo renderiza con JS; terceros citan Launch 35 USD/mes (comercial) y Scale 138,60 USD/mes | no verificado | Comercial |
| MiniMax H3 Max Lip Sync | MiniMax | **[REV] fal** (no aparece en la API oficial de MiniMax) | imagen + audio ≥5 s, ≤15 min → 480p–2K; `enable_transcription` | sigue el aspecto de la imagen | **Sí** | filtro de seguridad | fal 0,08 USD/s (768p), 0,16 (1080p); ×1,2 por encima de 15 s | ≈2,88 (768p) | Comercial |
| sync-3 image-to-video | Sync Labs | [REV] fal | imagen + audio → vídeo; «works with any illustration» | — | Sí | — | fal 0,1333 USD/s | ≈4,00 | Comercial |
| **Wan 2.2-S2V** | Alibaba (Tongyi Wan) | Directo Model Studio (**solo Pekín**); [REV] fal, Replicate; abierto | imagen + audio (+ prompt, + pose opcional) → 480p/720p; fal: 40–120 fotogramas a 16 fps (≤7,5 s por llamada) | sigue la imagen | **Sí** | — | Alibaba 0,129 USD/s 720p · fal 0,20 · Replicate 0,02 USD/s (dato de la ficha) | ≈3,87 · 6,00 fal | **Apache-2.0** |
| Wan 2.5 / 2.6 i2v con `audio_url` | Alibaba | Directo Model Studio | imagen + audio 3–30 s → vídeo 5/10 s | — | Probable; **lip-sync no verificado** | — | 0,10 USD/s 720p (flash 0,05) | ≈3,00 | Comercial |
| **InfiniteTalk** (imagen→vídeo) | Meituan, abierto | Autoalojado; [REV] fal | imagen + audio → vídeo de longitud ilimitada; 480p/720p | — | Sí | — | fal 0,20 USD/s | ≈6,00 | Apache-2.0 |
| MultiTalk | Meituan, abierto | Autoalojado; [REV] fal | imagen + 1–2 audios → conversación; 480p (720p multi-GPU) | — | Sí | — | fal 0,20 USD/s | ≈6,00 | Apache-2.0 |
| LongCat-Video-Avatar (1.0 / 1.5) | Meituan, abierto | Autoalojado; [REV] fal | imagen + audio → vídeo | — | Sí | — | fal 0,15 (480p) / 0,30 (720p) USD/s | ≈4,50–9,00 | MIT ([HF]) |
| EchoMimic V3 | Ant Group, abierto | Autoalojado; [REV] fal | imagen + audio + prompt → vídeo hasta 768×768; 12 GB VRAM | — | Sí | — | fal 0,20 USD/s | ≈6,00 | Apache-2.0 |
| FantasyTalking | Alibaba AMAP, abierto | Autoalojado | imagen + audio + prompt → 512×512 (sobre Wan2.1-I2V-14B-720P) | — | Sí | — | — | GPU propia | Apache-2.0 |
| Hallo / Hallo2 / Hallo3 | Universidad Fudan, abierto | Autoalojado | foto + audio → vídeo (Hallo2: largo y alta resolución; Hallo3: sobre CogVideoX-5B) | — | Sí | — | — | GPU propia | Código MIT; **modelos InsightFace no comerciales**; Hallo2 alta resolución bajo S-Lab (no comercial); Hallo3 sujeto a la licencia CogVideoX |
| SadTalker | Xi'an Jiaotong / Tencent AI Lab (OpenTalker), abierto | Autoalojado; [REV] fal (por cómputo) | foto + audio → cabeza que habla (3DMM) | — | Sí | — | — | GPU propia | «updated to Apache 2.0… removed the non-commercial restriction» (README) |
| SoulX-FlashTalk 14B | SoulX (empresa no verificada) | [REV] fal | imagen + audio → avatar | — | Sí | — | fal 0,02 USD/s | ≈0,60 | no verificado |
| BytePlus Clone Avatar | ByteDance / Vision AI | Directo | avatar entrenado (vídeo >1 min) + `audio_url` → hasta 12 min | — | Sí | sin verificación nativa | 300 USD por avatar + 0,015 USD/s | ≈0,45 + 300 por persona | Comercial |
| BytePlus Flash Avatar | ByteDance / Vision AI | Directo | avatar entrenado con vídeo de 10–15 s + audio <5 min (`realman_lipsync_*`) | — | Sí | — | **no publicado** | no publicado | Comercial |
| Seedance 2.x con `reference_audio` | ByteDance / ModelArk | Directo | imagen/vídeo + audio de referencia → vídeo con voz **generada** | según `ratio` | **Timbre** | Rechaza caras reales salvo real-person asset | 3,5–10,7 USD/M tokens | ≈2,27–6,93 | Comercial |

### 1.C Foto + video de movimiento → video (motion transfer)

| Modelo | Empresa / suite | Acceso | Entrada → salida (límites) | ¿Qué audio sale? | ¿Necesita después un lip-sync de la familia A? | Caras reales | Precio | **Reel 30 s** (sin el paso A) | Licencia |
|---|---|---|---|---|---|---|---|---|---|
| **DreamActor M2.0** | ByteDance / BytePlus Vision AI | Directo (AK/SK); [REV] fal, Replicate | 1 imagen + vídeo guía ≤30 s → 720p a 25 fps; RTF ≈18; concurrencia 1 | **No documentado** si conserva el del guía | **Sí**: copia «motion, facial expressions, and lip movements» **del guía** | Sí («real people, animation, pets») | **0,05 USD/s** (igual en fal y Replicate) | **≈1,50** (+0,87 con HeyGen Precision) | Comercial |
| DreamActor M1 («动作模仿») | ByteDance / Volcengine | Solo Volcengine (China); **no documentado en BytePlus** | — | — | Sí | — | — | — | Comercial |
| **Kling Motion Control** (v2.6 / v3, Std / Pro) | Kuaishou / Kling AI | [REV] fal | imagen + vídeo guía (≤30 s con orientación «video»); vínculo facial opcional | **El del guía** (`keep_original_sound`, por defecto `true`) | **Sí** | filtro de seguridad | fal v3: 0,126 (Std) / 0,168 (Pro) USD/s | ≈3,78–5,04 | Comercial |
| **Wan 2.2-Animate** (move / replace) | Alibaba, abierto | Autoalojado; [REV] fal | imagen + vídeo guía → personaje con los movimientos y expresiones del guía; «replace» lo inserta en el vídeo | no documentado | Sí | — | fal 0,08 USD/s 720p (0,06 a 580p) | ≈2,40 | **Apache-2.0** |
| Wan Motion | fal (sobre Wan) | [REV] fal | imagen + vídeo guía; `adapt_motion`, `enhance_identity` | no documentado | Sí | — | fal 0,06 USD/s 720p (+0,08 con `enhance_identity`) | ≈1,80 | Comercial |
| MiniMax H3 Max Recast | MiniMax | [REV] fal | vídeo fuente 5–30 s (planos ≤15 s) + una foto por persona → **sustituye a las personas** conservando movimiento | no documentado | Probable (los labios siguen el original) | Sí (fotos de referencia) | fal 0,30 (768p) / 0,45 (1080p) USD/s | ≈9,00–13,50 | Comercial |
| Runway Act-Two | Runway | Directo | personaje + vídeo de actuación → vídeo; **no acepta audio** | — | Sí | — | 0,05 USD/s | ≈1,50 | Comercial |
| Seedance 2.x `reference_video` («action transfer») | ByteDance / ModelArk | Directo | imagen + vídeo de referencia → escena nueva | generado por Seedance | Sí, si se quiere nuestra voz | **Rechaza caras reales** (`PrivacyInformation`) salvo asset de la misma persona | con vídeo de entrada 2,1–6,4 USD/M tokens | ≈2,70 (mini, 30 s de entrada + 30 s de salida; cálculo) – 8,29 (2.5) | Comercial |
| **LivePortrait** | Kuaishou (Kling Research), abierto | Autoalojado; [REV] fal (por cómputo) | foto + vídeo guía → **solo la cara** (expresión y pose de cabeza) | — | Sí | — | — | GPU propia | Código MIT; **los modelos de detección InsightFace no son comerciales** (hay que sustituirlos) |
| BytePlus Clone Avatar | ByteDance / Vision AI | Directo | repite los gestos **de su propio vídeo de entrenamiento**, no de un reel externo | nuestro audio (`audio_url`) | No | — | 300 USD + 0,015 USD/s | ≈0,45 | Comercial |

---

## 2. Fichas por modelo

Formato: qué es · acceso · entradas y salidas · nuestro audio · caras reales · calidad (y quién la firma) · precio y reel de 30 s · licencia · GPU si se autoaloja. Lo que ya está verificado en otro documento se resume en una línea y se enlaza.

### 2.1 ByteDance

#### LatentSync (familia A, código abierto)

- **Qué es:** lip-sync de extremo a extremo con un modelo de difusión latente condicionado por audio (Whisper → *cross-attention* en la U-Net), supervisado con SyncNet. Edita la boca de un vídeo existente; no genera cuerpo ni cabeza ([GH] [bytedance/LatentSync](https://github.com/bytedance/LatentSync), README).
- **Versiones:** **1.6** (2025-06-11, entrenada a 512×512 «to mitigate the blurriness problem») y 1.5 (2025-03-14, capa temporal, mejor en chino). Último *push* al repositorio: 2025-06-20; 6.141 estrellas ([GH] API, 2026-10-15). Sin versiones posteriores visibles.
- **Licencia:** código **Apache-2.0** ([GH]); pesos `ByteDance/LatentSync-1.6` y `-1.5` con **OpenRAIL++** ([HF] API, 2026-10-15). OpenRAIL++ permite uso comercial con restricciones de uso (lista de usos prohibidos). La canalización de datos (solo entrenamiento) usa InsightFace, cuyos modelos no son comerciales ([GH] README de insightface); **que la inferencia dependa de InsightFace: no verificado**.
- **VRAM:** inferencia mínima **8 GB (1.5)** y **18 GB (1.6)**; entrenamiento 20–55 GB ([GH] README).
- **Entradas y salidas:** vídeo + audio → vídeo; el preprocesado remuestrea a 25 fps y 16 kHz. Parámetros `inference_steps` (20–50) y `guidance_scale` (1,0–3,0; más alto = más sincronía, pero «may cause the video distortion or jitter»).
- **Alojado:**
  - **fal** `fal-ai/latentsync`: **0,20 USD por vídeo de hasta 40 s**, luego 0,005 USD/s; `video_url` + `audio_url`, `guidance_scale` 1–2, `loop_mode` (pingpong/loop) si el audio es más largo ([REV] [llms.txt](https://fal.ai/models/fal-ai/latentsync/llms.txt)). Qué versión (1.5 o 1.6) sirve fal: **no documentado**.
  - **Replicate** `bytedance/latentsync`: L40S a 0,000975 USD/s, «costs approximately $0.11 to run» ([REV] [replicate.com/bytedance/latentsync](https://replicate.com/bytedance/latentsync)).
- **Calidad:** el paper ([arXiv 2412.09262](https://arxiv.org/abs/2412.09262), firmado por ByteDance) dice superar a métodos previos en sincronía (SyncNet). Sin comparativa independiente. Al editar solo la boca, hereda el límite de toda la familia A: si el personaje no habla en el vídeo de entrada, el resultado empeora (no verificado para LatentSync en concreto).
- **Para Qualify:** la opción **más barata con API** para el paso «vídeo de Seedance + nuestro MP3» (≈0,20 USD por reel en fal). Candidata al A/B junto a HeyGen Precision y Sync.

#### OmniHuman 1.0 / 1.5 / 2.0 (familia B)

Ya documentado en [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md) y [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md). Resumen:
- BytePlus **Vision AI** (no ModelArk), AK/SK, verificación empresarial. 1.5: foto + audio <60 s, 720p/1080p, **0,12 USD/s, concurrencia 1**, RTF 23–27. 2.0: audio 4–300 s, 720p nativo, 0,07 o 0,12 USD/s (tarifa efectiva **no verificada**).
- **Acepta nuestro MP3** (`audio_url`), sin TTS propio. Acepta caras reales según la doc; no hay flujo de consentimiento (contractual, AUP GenAI).
- **No acepta vídeo de entrada:** no sirve como paso de lip-sync sobre un clip existente.
- Revendedores hoy: fal 1.5 a 0,16 USD/s; Replicate `bytedance/omni-human` (1.0) a 0,14 USD/s y `omni-human-1.5` a 0,16 USD/s ([REV] fichas de Replicate, 2026-10-15).
- Calidad: HeyGen dice ganar a OmniHuman 1.5 en el 85,7 % de las comparaciones (firmado por HeyGen). Alibaba dice que Wan-S2V lo supera ([arXiv 2508.18621](https://arxiv.org/abs/2508.18621), firmado por Alibaba). Nada independiente.

#### DreamActor M1 / M2.0 (familia C)

Ya documentado en [avatar-reutilizable-voz-y-movimiento-bytedance.md](avatar-reutilizable-voz-y-movimiento-bytedance.md) §3.2–3.3. Resumen:
- **M2.0** en BytePlus Vision AI (`dreamactor_m20_gen_video_cvtob`): 1 imagen + vídeo guía ≤30 s → 720p a 25 fps; copia «motion, facial expressions, and lip movements»; caras reales, animación y mascotas; **0,05 USD/s**, concurrencia 1. Mismo precio en fal y Replicate ([REV]).
- **No recibe audio.** Los labios salen del vídeo guía: para que diga nuestro guion hace falta **después** un paso de la familia A con nuestro MP3.
- **M1** («动作模仿») solo consta en Volcengine (China), no en BytePlus.

#### Seedance 2.x: `reference_audio` y el `edit` de 2.5 (voz propia, no lip-sync de un audio dado)

Ya documentado en [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §1. Resumen:
- `reference_audio` da **timbre** (y quizá contenido), pero la voz que suena **la genera Seedance**; BytePlus reconoce que puede «differ significantly».
- El `edit` de 2.5 re-dobla con lip-sync «palabra a palabra», **con voz sintetizada desde el texto del prompt**. Pasar nuestro MP3 como `@Audio 1` en un `edit` es una **hipótesis no documentada** (≈8,29 USD por 30 s a 720p, cálculo).
- **Conclusión:** Seedance no es un modelo de lip-sync de la familia A y no acepta nuestro audio exacto.

#### Volcengine AI MediaKit «视频口型对齐» (familia A) — nuevo

- **Qué es:** «基于您上传的一段人物视频和一段驱动音频，用音频内容驱动视频中人物的面部表情与口型»: a partir de un vídeo de una persona y un audio, mueve **la expresión facial y la boca** según el audio. Casos de uso declarados: vídeo corto, presentadores virtuales, formación y **marketing** ([DOC] [video-lip-alignment](https://docs.volcengine.com/docs/6448/2658349), act. 2026-09-09).
- **Endpoint:** `POST https://mediakit.cn-beijing.volces.com/api/v1/tools/lip-sync` con `Authorization: Bearer {MediaKit API Key}`. Es asíncrono: devuelve `task_id`; se sondea con `GET /api/v1/tasks/{task_id}` o se usa `callback_url`. Tiene `client_token` (idempotencia) y `queue_id` (colas) ([DOC] [submit-video-lip-alignment-task-api](https://docs.volcengine.com/docs/6448/2656064), act. 2026-08-27).
- **Entradas:**
  - `video_url`: **MP4**; «仅支持单人真人出镜视频» (solo una persona real; dibujos solo con proporciones faciales humanas); cara frontal (giro ≤45°, inclinación ≤15°), sin oclusiones, luz estable; **≤30 min**; sin HDR.
  - `audio_url`: mp3, aac, wav, m4a, flac; «建议为清晰的单人声» (una sola voz limpia).
  - Orígenes: URL pública, `mediakit://` (subida local), `vod://`, `tos://`.
  - `enable_video_loop`: si el audio es más largo, repite el vídeo en vaivén (adelante → atrás → adelante); si es más corto, recorta.
- **Salida:** `result.video_url` (enlace de 24 h) o escritura directa en VOD/TOS; `result.duration` (base del cobro). **RTF 6–8**: 1 min de audio tarda unos 6–8 min.
- **Nuestro audio:** **sí**. Es exactamente el caso «vídeo + nuestro MP3».
- **Precio:** **1 CNY por minuto de salida**, en pospago o con «多媒体处理资源包» ([PRECIO] [计费说明](https://docs.volcengine.com/docs/6448/2486473), act. 2026-09-24). Un reel de 30 s = 0,5 CNY ≈ **0,07 USD** (cálculo con 1 USD ≈ 7,1 CNY; tipo de cambio supuesto, no verificado hoy).
- **Caras reales y consentimiento:** exige persona real; **no documenta** consentimiento ni prueba de vida.
- **Qué modelo hay debajo:** **no documentado**. Que sea un derivado de LatentSync es especulación.
- **Bloqueos para Qualify:** región **cn-beijing** y cuenta de Volcengine (nube y jurisdicción chinas); los requisitos de alta para una empresa extranjera están **no verificados**. Calidad en español **no verificada**.
- **Revendedor fuera de China:** kie.ai ofrece «Volcengine Video-to-Video Lip Sync» a 8 créditos/s (≈0,04 USD/s), vídeo ≤500 MB, audio ≤10 MB, modos `lite`/`basic`, sin nombrar el modelo ([REV] [kie.ai](https://kie.ai/volcengine-video-to-video-lip-sync)). Que sea el mismo servicio que MediaKit: **no verificado**.

#### BytePlus Clone Avatar, Flash Avatar e Interactive Avatar

Ya documentados en [avatar-reutilizable-voz-y-movimiento-bytedance.md](avatar-reutilizable-voz-y-movimiento-bytedance.md) §1.2–1.4. Lo relevante aquí:
- **Flash Avatar** usa los `req_key` `realman_lipsync_training_tob` y `realman_lipsync_creation_tob`: entrena con un vídeo de 10–15 s y luego **resincroniza los labios de ese mismo vídeo en bucle** con un audio (<5 min). Es lo más parecido a un lip-sync vídeo→vídeo que hay en BytePlus internacional, pero **exige entrenar antes un `resource_id`** y su precio **no está publicado**. No sirve para un clip arbitrario de Seedance (inferencia).
- **Clone Avatar:** avatar entrenado con un vídeo de más de 1 min; 300 USD por avatar + 0,015 USD/s; recibe `audio_url`.
- **Interactive Avatar:** solo streaming en directo (RTC); no sirve para reels.

### 2.2 HeyGen

- **Lipsync** (`POST /v3/lipsyncs`, familia A):
  - vídeo + audio como URL o `asset_id`;
  - `mode: precision` («avatar-inference lip-sync»); Speed por defecto;
  - `enable_dynamic_duration` (por defecto `true`), `keep_the_same_format`, `fps_mode` (`vfr`/`cfr`/`passthrough`), `start_time`/`end_time`, `disable_music_track`, `enable_watermark` (por defecto `false`), lotes de hasta 100 ([DOC] [lipsync-precision](https://developers.heygen.com/lipsync-precision.md)).
  - Precio y contradicciones: [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.11 (0,84 / 1,74 USD/min en el help center).
  - **Revendedor:** fal `fal-ai/heygen/v3/lipsync/speed` a 0,05 USD/s y `/precision` a 0,10 USD/s ([REV]): **3,4–3,6 veces más caro** que directo.
- **Video Translate** (`POST /v3/video-translations`): usa la misma máquina de lip-sync, precedida de transcripción, traducción y voz; 175+ idiomas. Textual: «Lip Sync API = engine only — you bring the audio. Video Translation API = translation, optionally followed by the engine» ([DOC] [video-translate](https://developers.heygen.com/docs/video-translate.md)). **No usa nuestro MP3**: para nuestra voz, Lipsync.
- **Avatar IV** (familia B): motor por defecto. Acepta Digital Twin, Photo Avatar, Studio Avatar e **imagen arbitraria**; `motion_prompt` y `expressiveness`.
- **Avatar V:** solo Digital Twin, con comprobación de elegibilidad y «cross-reference animation». **Avatar III:** canal foto→vídeo, 4K en twins ([DOC] [models](https://developers.heygen.com/models.md)).
- **Límites comunes:** audio de entrada ≤10 min; salida a 25 fps, 1080p por defecto, **16:9 o 9:16**; ≤30 min por escena; concurrencia 10 (pago por uso) / 20 (Enterprise); `POST /v3/lipsyncs/batches` 30 por minuto ([DOC] [usage-limits](https://developers.heygen.com/docs/usage-limits.md)).
- **Caras reales:** Photo Avatar e imagen arbitraria sin control de consentimiento; Digital Twin con consentimiento obligatorio por webcam ([investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md) §3). Para Lipsync sobre un vídeo dado: consentimiento **no documentado**.
- **Calidad:** «Precision… frame-accurate… for cinematic content» y el 85,7 % de victorias de Avatar V frente a OmniHuman 1.5 están **firmados por HeyGen**.

### 2.3 Sync Labs (sync.so)

**Modelos** ([DOC] [sync.so/docs/models](https://sync.so/docs/models.mdx), 2026-10-15):

| Modelo | USD/s a 25 fps | Rasgos |
|---|---|---|
| lipsync-1.9.0-beta (legado) | 0,02–0,025 | labios genéricos; el más rápido |
| lipsync-2 | 0,04–0,05 | conserva el estilo de habla; cara a 512×512 |
| lipsync-2-pro | 0,067–0,083 | superresolución por difusión; barba y dientes; cara hasta 350×350 px; 1,5–2× más lento |
| sync-3 | 0,107–0,133 | procesa el plano completo; 4K nativo; oclusiones y perfiles; «can open silent lips» |
| react-1 (solo visto en fal) | fal 10 USD/min | lip-sync + edición de la emoción |

- **Límites:**
  - duración máxima del vídeo según el plan: de **1 min (Hobbyist) a 30 min (Scale+)**;
  - lipsync-2 y 2-pro trocean en bloques de 30–40 s y pueden fallar con muchos cortes de escena;
  - necesitan que el personaje **ya esté hablando** en el vídeo («still frame limitation»);
  - **no admite animales ni personajes no humanoides** ([DOC] FAQ).
- **Audio:** **sí, nuestro audio exacto** (`audio_url`). `sync_mode` (`cut_off`, `loop`, `bounce`, `silence`, `remap`) para desajustes de duración ([REV] fal).
- **Revendedores:** fal (v2 3 USD/min, v2-pro 5 USD/min, sync-3 8 USD/min, sync-3 image-to-video 0,1333 USD/s) y Replicate (lipsync-2 0,05 USD/s, lipsync-2-pro 0,08325 USD/s). Están en línea con el precio directo del plan Creator.
- **Origen:** los autores de Wav2Lip remiten el uso comercial de Wav2Lip a Sync Labs ([GH] README de Wav2Lip).
- **Calidad:** todo lo publicado lo firma el fabricante.

### 2.4 Kling (Kuaishou)

- **Avatar** (familia B): imagen + audio (+ prompt).
  - Directo: 0,056 USD/s a 720p y 0,112 a 1080p ([PRECIO], ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.1).
  - fal: Standard 0,0562 y Pro 0,115 USD/s; «realistic humans, animals, cartoons» ([REV] fal).
- **Lip-Sync** (familia A):
  - Directo: sin precio en la tabla oficial.
  - fal y Replicate: **0,014 USD/s** (fal redondea a tramos de 5 s).
  - En fal, el vídeo debe durar **2–10 s**, ser 720p o 1080p y pesar ≤100 MB; el audio, 2–60 s y ≤5 MB ([REV] [fal](https://fal.ai/models/fal-ai/kling-video/lipsync/audio-to-video/llms.txt)). Un reel de 30 s son 3 llamadas.
- **Motion Control** (familia C): imagen + vídeo guía; conserva por defecto el sonido del guía; vínculo facial opcional; fal v3 0,126 (Std) / 0,168 (Pro) USD/s ([REV]).
- **LivePortrait** (abierto) es también de Kuaishou (§2.13).

### 2.5 Hedra: Character-3 (familia B)

Ya documentado en [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.6: imagen + 1–4 audios (0,5–600 s), 540p/720p/1080p con 9:16, **0,05 USD/s a 720p**; revende el clonado de ElevenLabs. Consentimiento y caras reales: **no documentados**.

### 2.6 VEED: Fabric 1.0 (familia B) y Lipsync (familia A)

- **Fabric 1.0:** imagen + audio, 480p/720p; fal 0,08/0,15 USD/s; Fast 0,10/0,20 USD/s. El soporte de VEED cita 0,05 USD/s y ≤1 min por llamada: contradicción (ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.8).
- **VEED Lipsync v2** (2026-07-13): vídeo + audio → vídeo, **0,07 USD/s** en fal; la v1, 0,40 USD/min ([REV] [fal veed/lipsync/v2](https://fal.ai/models/veed/lipsync/v2/llms.txt)).
- ElevenLabs usa Fabric (y OmniHuman) para el lip-sync de su app ([voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.12).

### 2.7 Creatify: Aurora (familia B)

Ya documentado en [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §2.9: foto «real or AI-generated» + MP3/WAV (≤59,7 s en v2), 480p–2k; créditos solo por suscripción (99 o 299 USD/mes); fal 0,14 USD/s a 720p.

**Novedad:** es el único modelo de lip-sync con audio dado dentro de la **API de vídeo de ElevenLabs** (`model_id: creatify-aurora`, con `audio_guidance_scale` y salida 480p/720p) ([DOC] [ElevenLabs, create video](https://elevenlabs.io/docs/api-reference/flows/video/create.md)).

### 2.8 Tavus (familia B con avatar entrenado)

- **API asíncrona de vídeo** (`POST /v2/videos`): una «face» (`replica_id`) + guion **o `audio_url`** → vídeo. **Acepta nuestro audio** ([DOC] [create-video](https://docs.tavus.io/api-reference/video-request/create-video.md)).
- **Modelos:**
  - Phoenix-4.5: desde foto o vídeo; vista previa en ~1 min y ajuste en segundo plano;
  - Phoenix-4: cuerpo entero; hay que esperar al entrenamiento completo;
  - Phoenix-3: legado, solo desde vídeo.
  - Textual: «All models accept a human or clearly human-shaped subject… Animals, mascots, and other non-human figures are not» ([DOC] [which-training-path](https://docs.tavus.io/sections/faces/which-training-path.md)).
- **Consentimiento:** flujo con guion de consentimiento para réplicas personales, con marca blanca en los planes altos ([PRECIO] [tavus.io/pricing](https://www.tavus.io/pricing)).
- **Precio:** la página muestra **dos versiones incoherentes**:
  1. Starter 59 USD/mes con 10 min y 1 USD/min extra; Growth 397 USD/mes con 100 min y 0,90 USD/min;
  2. Starter 22 USD/mes con 5 min, Builder 59 USD/15 min, Growth 397 USD/50 min, Business 975 USD/250 min.

  Un reel de 30 s ≈ **0,45–0,50 USD** de excedente más la cuota mensual. **Hay que confirmarlo en el panel.**
- **Foco del producto:** vídeo conversacional en tiempo real (CVI). El vídeo asíncrono es secundario.

### 2.9 D-ID (familias A y B)

- **Productos de la API:** V2 Photo Avatars (`/talks`: foto + texto o audio), V3 Pro (`/clips`, Premium+ entrenado), V3 Instant (Express Avatar desde vídeo propio), **V4 Expressive** (con «sentiments») y **Video Translate** con lip-sync ([DOC] [docs.d-id.com/llms.txt](https://docs.d-id.com/llms.txt)).
- **Nuestro audio:** documentado para V2 (`talks`). Para V4 y para lip-sync sobre un vídeo propio: **no verificado**.
- **Precio: no verificado.** La página oficial de precios de la API solo renderiza con JS. Un tercero ([Creatify, blog](https://creatify.ai/blog/d-id-pricing-(2026)-plans-credits-and-what-you-ll-actually-pay) [2ª]) cita Build a 14,40 USD/mes anual (solo uso personal), **Launch a 35 USD/mes** (primer plan comercial) y Scale a 138,60 USD/mes.

### 2.10 Captions / Mirage: Avatar X (familia B; admite vídeo de referencia)

- **Sí tiene API** (Mirage API). Avatar X: «Expressive human video generation model (video/image + audio → video)», **0,15 USD/s en tramos de 6 s**. Un reel de 30 s = 4,50 USD ([PRECIO] [captions.ai/help/docs/api/pricing.md](https://captions.ai/help/docs/api/pricing.md)).
- fal lo revende al doble (0,30 USD/s): `audio_url` obligatorio; `image_reference_url`, `video_reference_url` (≤120 s) o un avatar de catálogo; audio de 3–180 s; **9:16 o 16:9** ([REV] [fal](https://fal.ai/models/mirage-api/avatar-x/reference-to-video/llms.txt)).
- **Acepta nuestro audio.** Caras reales y consentimiento por API: **no documentados** en las páginas leídas.
- La app de Captions también dobla a 30+ idiomas con lip-sync y crea un «AI Twin» desde un selfi ([DOC] [captions.ai/llms.txt](https://captions.ai/llms.txt)); eso no usa nuestro audio.

### 2.11 ElevenLabs

- **No tiene lip-sync propio.** Textual: «At the moment, ElevenLabs does not offer lip syncing as part of Dubbing. Lip sync is available in Image & Video, Flows, and Studio via third party models» ([DOC] [FAQ](https://elevenlabs.io/docs/help-center/product/dubbing/do-you-offer-lip-sync-in-dubbing.md)).
- **API de Image & Video** (plan Pro o superior; si no, `402 paid_plan_required`). Modelos: `bytedance-seedance-v2`, `-v2-fast`, `-v2-mini`, `-v2.5`, `creatify-aurora`, `veo-3.1-generate-001` y `veo-3.1-fast-generate-001`.
  - El único que mueve los labios con un audio dado es **`creatify-aurora`**.
  - Los Seedance aceptan `audios` «e.g. for lipsync», con los límites de Seedance (timbre) ([DOC] [create video](https://elevenlabs.io/docs/api-reference/flows/video/create.md), [quickstart](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/image-and-video.md)).
- **Avatars** (en la app): identidades persistentes con «multiple lip-sync models» elegidos por la plataforma; algunos modelos están restringidos en EE. UU. ([DOC] [avatars](https://elevenlabs.io/docs/overview/capabilities/image-video/avatars.md)). Por API: **no verificado**.
- **Lectura:** ElevenLabs es un **revendedor** de lip-sync (Aurora por API; Veed y OmniHuman en la app). Solo tiene sentido si ya se usa su voz.

### 2.12 Otros comerciales vistos en revendedores

| Modelo | Familia | Qué hace | Precio [REV] | Nota |
|---|---|---|---|---|
| MiniMax H3 Max Lip Sync | B | imagen + audio (≥5 s, ≤15 min) → 480p–2K; `enable_transcription` | fal 0,05 (480p) / 0,08 (768p) / 0,16 (1080p) / 0,32 (2K) USD/s; ×1,2 por encima de 15 s | **No figura en la API oficial de MiniMax**, que solo documenta `reference_audio` como timbre ([DOC] [video-generation-v2-create](https://platform.minimax.io/docs/api-reference/video-generation-v2-create.md)). Matiza el «solo timbre» de los documentos previos, pero solo por la vía fal |
| MiniMax H3 Max Recast | C | sustituye a las personas de un vídeo de 5–30 s por las de unas fotos, conservando el movimiento | fal 0,30 / 0,45 USD/s | Los labios siguen el vídeo original |
| PixVerse Lipsync | A | vídeo + audio o texto | fal 0,04 USD/s | — |
| Argil avatars | B | avatares del catálogo de Argil + audio | fal 0,02 USD por segundo de entrada | Al parecer solo avatares de Argil (no verificado) |
| SoulX-FlashTalk 14B / FlashHead 1.3B | B | avatar hablado desde audio | fal 0,02 / 0,005 USD/s | Empresa y licencia no verificadas |

### 2.13 Código abierto (autoalojado)

| Modelo | Autor | Familia | Licencia del código | Licencia de los pesos y dependencias | **¿Uso comercial?** | GPU (según README) | Alojado en |
|---|---|---|---|---|---|---|---|
| **LatentSync 1.6** | ByteDance | A | Apache-2.0 | OpenRAIL++ | **Sí, con restricciones de uso** | 18 GB en inferencia (1.5: 8 GB) | fal, Replicate |
| **MuseTalk 1.5** | Tencent Music (Lyra Lab) | A (y B desde imagen) | MIT | «available for any purpose, even commercially»; Whisper, ft-mse-vae, DWPose y S3FD con licencia propia; datos de prueba no comerciales | **Sí** (revisar dependencias) | Tiempo real en V100; 4 GB de VRAM en un portátil (8 s en ~5 min, fp16) | fal |
| **Wav2Lip** | IIIT Hyderabad | A | sin licencia SPDX | «personal/research/non-commercial purposes only»; la versión HD comercial, vía Sync Labs | **No** | — | — |
| VideoReTalking | Tencent AI Lab (OpenTalker) | A | Apache-2.0 | GFPGAN, GPEN, PIRenderer…; aviso: prohibido vulnerar derechos de imagen | Probable; **revisar dependencias** | — | — |
| Hallo / Hallo2 / Hallo3 | Universidad Fudan | B | MIT | **Modelos de InsightFace no comerciales**; la alta resolución de Hallo2 va bajo S-Lab License 1.0 (CodeFormer, no comercial); Hallo3 deriva de **CogVideoX-5B**: uso comercial previa inscripción gratuita, hasta 1 M de visitas al mes | **No tal cual** (hay que sustituir InsightFace; Hallo3 sujeto a la licencia CogVideoX) | A100 (Hallo, Hallo2); H100 (Hallo3) | — |
| EchoMimic V1 / V2 / V3 | Ant Group | B | Apache-2.0 | V3: Apache-2.0 en HF | **Sí** | V3: 12 GB de VRAM, hasta 768×768; probado en A100 80G, 4090D 24G y V100 16G | fal (V3, 0,20 USD/s) |
| SadTalker | Xi'an Jiaotong / Tencent AI Lab | B | «updated to Apache 2.0… removed the non-commercial restriction» (GitHub no detecta SPDX) | HF `vinthony/SadTalker`: MIT | **Sí** (revisar dependencias) | — | fal (por cómputo) |
| **LivePortrait** | Kuaishou (KlingAIResearch) | C (solo cara) | MIT | «The models of InsightFace are for non-commercial research purposes only… remove and replace InsightFace's detection models» | **Sí, sustituyendo InsightFace** (por ejemplo, con MediaPipe, como hace el nodo de kijai) | RTX 4090 de referencia | fal (por cómputo) |
| **Wan 2.2-S2V-14B** | Alibaba | B | Apache-2.0 | Apache-2.0 | **Sí** | **≥80 GB de VRAM** en una GPU; multi-GPU con FSDP | Alibaba (Pekín), fal, Replicate |
| **Wan 2.2-Animate** | Alibaba | C | Apache-2.0 | Apache-2.0 | **Sí** | no especificado en el extracto leído | fal |
| **InfiniteTalk** | Meituan (MeiGen) | **A y B** (*sparse-frame video dubbing*: labios, cabeza y cuerpo) | Apache-2.0 | Apache-2.0, sobre Wan2.1-I2V-14B | **Sí** | Modo de VRAM muy baja; 480p/720p; integración con Wan2GP | fal (0,20 / 0,30 USD/s) |
| MultiTalk | Meituan (MeiGen) | B (multipersona) | Apache-2.0 | Apache-2.0 | **Sí** | 480p en una RTX 4090 con VRAM baja; 720p multi-GPU | fal (0,20 USD/s) |
| LongCat-Video-Avatar 1.0 / 1.5 | Meituan | B | — | MIT ([HF]) | **Sí** | no leído | fal (0,15–0,30 USD/s) |
| FantasyTalking | Alibaba AMAP | B | Apache-2.0 | Apache-2.0, sobre Wan2.1-I2V-14B-720P | **Sí** | A100, 512×512 y 81 fotogramas: 40 GB (15,5 s/it), 20 GB o 5 GB (42,6 s/it) | — |

Fuentes: README y API de cada repositorio en GitHub y fichas de Hugging Face, consultados el 2026-10-15 (lista en «Fuentes»).

**Referencia de costo de GPU alojada** (no es una recomendación de autoalojar): Replicate cobra una L40S a 0,000975 USD/s (≈3,51 USD/h) y una H100 a 0,001525 USD/s (≈5,49 USD/h) ([REV] fichas de `bytedance/latentsync` y `wan-video/wan-2.2-s2v`). Un modelo de 14B que necesita ≥80 GB (Wan-S2V) probablemente cuesta más por reel autoalojado que comprado, salvo con volumen alto (cálculo pendiente, no medido).

**Calidad de los modelos abiertos:** cada paper se compara con los anteriores y gana; ninguna comparativa es independiente. Ejemplos: LatentSync (ByteDance); MuseTalk ([arXiv 2410.10122](https://arxiv.org/abs/2410.10122), Tencent); InfiniteTalk ([arXiv 2508.14033](https://arxiv.org/abs/2508.14033), Meituan, dice mejorar a MultiTalk); Wan-S2V ([arXiv 2508.18621](https://arxiv.org/abs/2508.18621), Alibaba, dice superar a Hunyuan-Avatar y a OmniHuman).

---

## 3. Qué hay dentro de la suite de ByteDance y qué falta

### 3.1 ¿Hay lip-sync vídeo→vídeo de ByteDance por API?

**Respuesta directa: sí en China (Volcengine), no en BytePlus internacional.** Y como código abierto, sí (LatentSync), alojado por terceros.

| Vía | ¿Existe? | Dónde | Estado el 2026-10-15 | Fuente |
|---|---|---|---|---|
| **Volcengine AI MediaKit «视频口型对齐»** (`/api/v1/tools/lip-sync`) | **Sí**, vídeo + audio → vídeo | Volcengine, región `cn-beijing` | Publicado; 1 CNY/min de salida; RTF 6–8 | [DOC] [6448/2658349](https://docs.volcengine.com/docs/6448/2658349), [6448/2656064](https://docs.volcengine.com/docs/6448/2656064), [6448/2486473](https://docs.volcengine.com/docs/6448/2486473) |
| BytePlus VOD AI MediaKit «video lip sync» | **Indicios, no publicado** | BytePlus (internacional) | Un buscador indexó `docs.byteplus.com/docs/byteplus-vod/ai-mediakit-video-lip-sync` y `…/ai-mediakit-create-a-video-lip-sync-task` (el buscador citó «last updated September 29, 2026»), pero hoy ambas URL devuelven `curDoc: null` y **no aparecen** en el índice de 637 documentos de BytePlus VOD, que sí lista otras herramientas de AI MediaKit (desenfoque de caras, separación de voz, Seed Speech…). Lectura: **en preparación o retirado; no verificable** | Extracción del `_ROUTER_DATA` de esas URL, 2026-10-15 |
| BytePlus Vision AI | **No** como producto de lip-sync sobre un vídeo cualquiera | — | El árbol de Vision AI solo tiene OmniHuman, DreamActor M2.0, Clone Avatar, Flash Avatar, Interactive Avatar y Dreamina. **Flash Avatar** (`realman_lipsync_*`) resincroniza labios, pero solo sobre su propio vídeo de entrenamiento (precio no publicado) | [DOC] árbol de Vision AI, 2026-10-15 · [avatar-reutilizable-voz-y-movimiento-bytedance.md](avatar-reutilizable-voz-y-movimiento-bytedance.md) §1.3 |
| BytePlus ModelArk (Seedance 2.5 `edit`) | **No** con un audio dado | ModelArk | Re-dobla con voz **generada** por Seedance; con nuestro MP3, no documentado | [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §1.2 |
| **LatentSync** (abierto) | **Sí** | GitHub/HF; alojado en fal y Replicate | 1.6 (2025-06); sin novedades en el repositorio desde 2025-06-20 | [GH], [HF], [REV] |
| kie.ai «Volcengine video-to-video lip sync» | Revendedor | kie.ai | ≈0,04 USD/s; modelo no nombrado | [REV] |

### 3.2 Mapa de la suite por familia

| Familia | Qué tiene ByteDance | Dónde | Qué falta |
|---|---|---|---|
| **A. Vídeo + audio → vídeo** | MediaKit «视频口型对齐»; LatentSync (abierto); Flash Avatar (solo sobre su vídeo entrenado) | Volcengine (China); GitHub; Vision AI | **Ninguna API internacional publicada** para resincronizar un clip arbitrario (por ejemplo, de Seedance) con nuestro MP3 |
| **B. Foto + audio → vídeo** | OmniHuman 1.0 / 1.5 / 2.0; Clone Avatar (entrenado) | BytePlus Vision AI | Nada esencial. Faltan: un objeto que guarde cara + voz juntos (HeyGen sí lo tiene), flujo de consentimiento nativo, concurrencia >1 en 1.5 y la tarifa efectiva de 2.0 |
| **C. Foto + vídeo de movimiento → vídeo** | DreamActor M2.0 (BytePlus); DreamActor M1 (solo Volcengine); Seedance 2.x «action transfer» (sin caras reales) | Vision AI; Volcengine; ModelArk | Que la salida de DreamActor conserve o reciba audio. Siempre hace falta un paso A para nuestro guion |
| **Voz propia (no lip-sync de un audio dado)** | Seedance 2.x (`generate_audio`, `reference_audio`, `edit` de 2.5) | ModelArk | Reproducir un MP3 dado palabra por palabra |
| **Voz** | Seed Speech (`seed-icl-2.0`) | BytePlus Voice | API de borrado de la voz |

**Consecuencia práctica:** dentro de BytePlus internacional, la única forma de que «la persona diga nuestro MP3» es **la familia B (OmniHuman)**. Para que una escena de **Seedance** o una salida de **DreamActor** diga nuestro MP3 hace falta un proveedor de la familia A **fuera de BytePlus** (HeyGen, Sync, LatentSync vía fal, Kling) o **Volcengine** (China).

---

## 4. Rutas para Qualify y costo por reel de 30 s

Supuestos: 30 s, 9:16, 720p; un intento; voz de Seed Speech ≈0,015 USD (con HeyGen Starfish, +0,045 USD); «×100» = 100 reels al mes. Las cifras son **cálculos** sobre precios oficiales (o de revendedor, donde se indica). Costos de Seedance: [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §1.6.

| # | Ruta | Familia | ¿Voz exacta de la marca? | Costo por reel (USD) | ×100 | Qué exige / riesgo |
|---|---|---|---|---|---|---|
| **R1** | **HeyGen Avatar IV** (foto + nuestro MP3) | B | **Sí** | **≈1,18–1,52** | ≈118–152 | Ya integrado. Photo sin control de consentimiento: hay que construir el nuestro |
| R2 | Hedra Character-3 720p | B | Sí | ≈1,52 | ≈152 | Cuenta nueva; consentimiento no documentado |
| R3 | Kling Avatar 720p (directo) | B | Sí | ≈1,70 | ≈170 | Cuenta nueva |
| R4 | OmniHuman 2.0 (BytePlus) | B | Sí | ≈2,12–3,62 | ≈212–362 | AK/SK + verificación empresarial; tarifa 0,07 o 0,12 sin confirmar |
| R5 | Mirage Avatar X (directo) | B | Sí | ≈4,52 | ≈452 | Cuenta nueva; admite vídeo de referencia |
| **R6** | **Seedance 2.0 mini → HeyGen Lipsync Precision** | escena + A | **Sí** | **≈3,16** | ≈316 | Ruta ya recomendada en [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) §6 |
| **R7** | **Seedance 2.0 mini → LatentSync (fal)** | escena + A | **Sí** | **≈2,49** | ≈249 | Cuenta de fal; calidad sin probar en español; pesos OpenRAIL++ |
| R8 | Seedance 2.0 mini → Kling Lip-Sync (fal) | escena + A | Sí | ≈2,71 | ≈271 | 3 llamadas de ≤10 s (límite de fal) y unir los tramos |
| R9 | Seedance 2.0 mini → Sync lipsync-2-pro | escena + A | Sí | ≈4,30–4,78 | ≈430–478 + plan | Plan de Sync (5–249 USD/mes) |
| R10 | Seedance 2.0 mini → Sync sync-3 | escena + A | Sí | ≈5,50–6,28 | ≈550–628 + plan | El de mejor calidad declarada; el más caro |
| R11 | Seedance 2.0 mini → Volcengine MediaKit | escena + A | Sí | **≈2,36** | ≈236 | **Cuenta de Volcengine en China**; sin probar |
| R12 | Seedance 2.5 (una toma de 30 s) → HeyGen Precision | escena + A | Sí | ≈7,82 | ≈782 | Sin costura entre dos tomas de 15 s |
| R13 | Seedance 2.0 mini con timbre (sin paso A) | voz propia | **No** (voz aproximada) | ≈2,29 | ≈229 | Solo para borradores; etiquetar «voz aproximada» |
| **R14** | **DreamActor M2.0 → HeyGen Precision** (persona + movimientos de un reel) | C + A | **Sí** | **≈2,39** | ≈239 | AK/SK de BytePlus; DreamActor con concurrencia 1; reel guía propio o con permiso |
| R15 | DreamActor M2.0 → LatentSync (fal) | C + A | Sí | ≈1,72 | ≈172 | Igual que R14 + calidad sin probar |
| R16 | Kling Motion Control v3 Std (fal) → HeyGen Precision | C + A | Sí | ≈4,67 | ≈467 | Solo revendedor |
| R17 | Wan-Animate (fal, 720p) → HeyGen Precision | C + A | Sí | ≈3,29 | ≈329 | Revendedor; o autoalojado Apache-2.0 |

**Lectura:**
- **Si basta una persona hablando a cámara:** R1 (HeyGen Avatar IV) sigue siendo lo más barato con nuestro MP3 y ya está integrado. Hedra y Kling (R2, R3) son los candidatos baratos del A/B; OmniHuman (R4) solo si gana en cuerpo entero o cámara.
- **Si la escena la genera Seedance:** el paso A cuesta entre **0,07 USD** (Volcengine, con bloqueo de jurisdicción) y **≈4 USD** (sync-3). **LatentSync vía fal (0,20 USD) es 4 veces más barato que HeyGen Precision (0,87 USD)** y está hecho por el mismo fabricante que Seedance; merece entrar en el A/B.
- **Si hay que copiar los movimientos de un reel:** R14 o R15 (DreamActor + paso A), por ≈1,7–2,4 USD.
- **En todas las rutas exactas, el paso de lip-sync es el que hay que elegir por calidad en español**, no por precio: entre las opciones de lip-sync puro (de Volcengine a sync-3) la diferencia es de ≈4 USD por reel.

**A/B propuesto (cuando se autoricen llamadas de pago):** el mismo clip de Seedance 2.0 mini de 30 s con el personaje hablando y el mismo MP3 de la voz de la marca en español, pasado por HeyGen Precision, LatentSync (fal), Sync lipsync-2-pro y Kling Lip-Sync. Costo estimado: ≈2,27 (clip) + 0,87 + 0,20 + 2,49 + 0,42 ≈ **6,3 USD** sin reintentos (cálculo). Medir: sincronía visible en sílabas «p/b/m», dientes, deriva de duración (`ffprobe`), parecido facial y artefactos en los cortes.

---

## 5. Abierto / pendiente de verificar

1. **BytePlus VOD «video lip sync»**: si existe y cuándo se publica (dos URL indexadas, hoy vacías). Preguntar a BytePlus.
2. **Volcengine MediaKit 视频口型对齐**: qué modelo usa; si una empresa no china puede abrir cuenta y usarlo; calidad en español; si kie.ai revende el mismo servicio.
3. **LatentSync en fal**: qué versión sirve (1.5 o 1.6); si la inferencia depende de modelos de InsightFace (no comerciales); alcance exacto de las restricciones de OpenRAIL++ para avatares de personas reales.
4. **Calidad en español** de cualquier lip-sync (A) sobre caras generadas por Seedance: **no hay benchmark independiente**; solo un A/B propio lo resuelve.
5. **HeyGen**: precio real de Lipsync (0,84/1,74 USD/min en el help center frente a 2/4 USD/min de G2 y 3/6 USD/min vía fal); consentimiento al hacer lip-sync de un vídeo con una persona real.
6. **Kling Lip-Sync directo**: precio oficial y límite de duración del vídeo (fal impone 2–10 s).
7. **MiniMax H3 Max Lip Sync**: si existe en la API oficial de MiniMax o solo vía fal.
8. **Mirage Avatar X**: qué hace exactamente con un `video_reference_url` (¿conserva el movimiento del vídeo o solo la identidad?) y su política de caras reales.
9. **D-ID**: precios oficiales de la API y si V4 acepta audio propio.
10. **Tavus**: cuál de las dos versiones de su página de precios es la vigente.
11. **DreamActor M2.0**: si conserva el audio del vídeo guía y si se activa en autoservicio.
12. **Wan 2.5/2.6 i2v con `audio_url`**: si los labios siguen el audio (la doc no dice «lip-sync»).
13. **Costo de autoalojar** LatentSync o InfiniteTalk por reel (tiempo real de inferencia en L40S/H100): no medido.
14. **Licencias abiertas para uso comercial con caras reales**: las licencias (Apache, MIT, OpenRAIL++) no sustituyen al consentimiento ni a las obligaciones de etiquetado (AI Act art. 50; ver [investigacion-caras-reales-video-ia.md](investigacion-caras-reales-video-ia.md)). **Esto no es un dictamen legal.**

---

## Fuentes (consultadas el 2026-10-15)

**ByteDance / Volcengine [DOC] [PRECIO]:**
- 视频口型对齐, guía (act. 2026-09-09): https://docs.volcengine.com/docs/6448/2658349
- 提交视频口型对齐任务 API (act. 2026-08-27): https://docs.volcengine.com/docs/6448/2656064
- 视频工具计费 (act. 2026-09-24): https://docs.volcengine.com/docs/6448/2486473
- AI MediaKit, índice de documentos: https://docs.volcengine.com/docs/Intelligentprocessing/Productadvantages-25?lang=zh
- BytePlus VOD, URL indexadas y vacías hoy: https://docs.byteplus.com/docs/byteplus-vod/ai-mediakit-video-lip-sync · https://docs.byteplus.com/docs/byteplus-vod/ai-mediakit-create-a-video-lip-sync-task
- BytePlus Vision AI (árbol de documentos leído desde): https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation
- El resto de páginas de BytePlus (OmniHuman, DreamActor, Clone/Flash Avatar, Seedance) están citadas en los documentos enlazados al principio.

**ByteDance, código abierto [GH] [HF]:**
- LatentSync: https://github.com/bytedance/LatentSync · https://huggingface.co/ByteDance/LatentSync-1.6 · paper https://arxiv.org/abs/2412.09262

**HeyGen [DOC]:**
- Lipsync Precision: https://developers.heygen.com/lipsync-precision.md · Speed: https://developers.heygen.com/lipsync-speed.md
- Video Translate: https://developers.heygen.com/docs/video-translate.md
- Models: https://developers.heygen.com/models.md
- Usage limits: https://developers.heygen.com/docs/usage-limits.md
- Precios [PRECIO]: https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained

**Sync Labs [DOC]:** https://sync.so/docs/models.mdx · https://sync.so/docs/product/billing.mdx

**Kling [PRECIO]:** https://kling.ai/dev/pricing (vía [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md))

**Tavus:** https://docs.tavus.io/api-reference/video-request/create-video.md · https://docs.tavus.io/sections/faces/which-training-path.md · https://www.tavus.io/pricing

**D-ID:** https://docs.d-id.com/llms.txt · https://docs.d-id.com/docs/v2-photo-avatar-quickstart.md · [2ª] https://creatify.ai/blog/d-id-pricing-(2026)-plans-credits-and-what-you-ll-actually-pay

**Captions / Mirage:** https://captions.ai/help/docs/api/pricing.md · https://captions.ai/llms.txt

**ElevenLabs [DOC]:** https://elevenlabs.io/docs/help-center/product/dubbing/do-you-offer-lip-sync-in-dubbing.md · https://elevenlabs.io/docs/api-reference/flows/video/create.md · https://elevenlabs.io/docs/eleven-api/guides/cookbooks/image-and-video.md · https://elevenlabs.io/docs/overview/capabilities/image-video/avatars.md

**MiniMax [DOC]:** https://platform.minimax.io/docs/api-reference/video-generation-v2-create.md · https://platform.minimax.io/docs/guides/local-deploy-h3.md

**Revendedores [REV]** (precio del revendedor; fichas `llms.txt` de fal y páginas de modelo de Replicate):
- fal: https://fal.ai/models/fal-ai/latentsync/llms.txt · https://fal.ai/models/fal-ai/sync-lipsync/v2/pro/llms.txt · https://fal.ai/models/fal-ai/sync-lipsync/v3/llms.txt · https://fal.ai/models/fal-ai/heygen/v3/lipsync/precision/llms.txt · https://fal.ai/models/fal-ai/heygen/v3/lipsync/speed/llms.txt · https://fal.ai/models/fal-ai/heygen/avatar4/image-to-video/llms.txt · https://fal.ai/models/fal-ai/kling-video/lipsync/audio-to-video/llms.txt · https://fal.ai/models/fal-ai/kling-video/ai-avatar/v2/pro/llms.txt · https://fal.ai/models/fal-ai/kling-video/v3/standard/motion-control/llms.txt · https://fal.ai/models/veed/lipsync/v2/llms.txt · https://fal.ai/models/veed/fabric-1.0/llms.txt · https://fal.ai/models/fal-ai/creatify/aurora/llms.txt · https://fal.ai/models/mirage-api/avatar-x/reference-to-video/llms.txt · https://fal.ai/models/minimax/h3-max/lip-sync/image-to-video/llms.txt · https://fal.ai/models/minimax/h3-max/recast/llms.txt · https://fal.ai/models/fal-ai/infinitalk/video-to-video/llms.txt · https://fal.ai/models/fal-ai/wan/v2.2-14b/speech-to-video/llms.txt · https://fal.ai/models/fal-ai/wan/v2.2-14b/animate/move/llms.txt · https://fal.ai/models/fal-ai/bytedance/dreamactor/v2/llms.txt · https://fal.ai/models/fal-ai/echomimic-v3/llms.txt · https://fal.ai/models/fal-ai/pixverse/lipsync/llms.txt · catálogo: https://api.fal.ai/v1/models
- Replicate: https://replicate.com/bytedance/latentsync · https://replicate.com/bytedance/omni-human · https://replicate.com/bytedance/omni-human-1.5 · https://replicate.com/bytedance/dreamactor-m2.0 · https://replicate.com/sync/lipsync-2 · https://replicate.com/sync/lipsync-2-pro · https://replicate.com/kwaivgi/kling-lip-sync · https://replicate.com/wan-video/wan-2.2-s2v
- kie.ai: https://kie.ai/volcengine-video-to-video-lip-sync

**Código abierto [GH] [HF]** (README, API de GitHub y de Hugging Face):
- Wav2Lip: https://github.com/Rudrabha/Wav2Lip
- MuseTalk: https://github.com/TMElyralab/MuseTalk · https://arxiv.org/abs/2410.10122
- VideoReTalking: https://github.com/OpenTalker/video-retalking
- Hallo / Hallo2 / Hallo3: https://github.com/fudan-generative-vision/hallo · https://github.com/fudan-generative-vision/hallo2 · https://github.com/fudan-generative-vision/hallo3
- CogVideoX-5B I2V, licencia: https://huggingface.co/THUDM/CogVideoX-5b-I2V
- EchoMimic: https://github.com/antgroup/echomimic · https://github.com/antgroup/echomimic_v2 · https://github.com/antgroup/echomimic_v3
- SadTalker: https://github.com/OpenTalker/SadTalker
- LivePortrait: https://github.com/KlingAIResearch/LivePortrait (licencia: https://raw.githubusercontent.com/KlingAIResearch/LivePortrait/main/LICENSE)
- InsightFace, licencia de los modelos: https://github.com/deepinsight/insightface
- Wan 2.2 (S2V y Animate): https://github.com/Wan-Video/Wan2.2 · https://huggingface.co/Wan-AI/Wan2.2-S2V-14B · https://arxiv.org/abs/2508.18621
- InfiniteTalk: https://github.com/MeiGen-AI/InfiniteTalk · https://arxiv.org/abs/2508.14033
- MultiTalk: https://github.com/MeiGen-AI/MultiTalk
- LongCat-Video-Avatar: https://huggingface.co/meituan-longcat/LongCat-Video-Avatar
- FantasyTalking: https://github.com/Fantasy-AMAP/fantasy-talking
