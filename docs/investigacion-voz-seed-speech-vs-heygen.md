# Voz clonada — BytePlus Seed Speech frente a HeyGen

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN VENDOR 2026-10-15]` · fuentes consultadas el 2026-10-15 · sin llamadas en vivo

Marcas: **[DOC]** documentación oficial · **[2ª]** tercero · **no verificado** = no confirmado en fuente primaria.

Las docs de BytePlus (`docs.byteplus.com`) solo renderizan con JS: el Markdown se lee del HTML inicial en `window._ROUTER_DATA…curDoc.MDContent`. Las URLs citadas son las públicas `https://docs.byteplus.com/en/docs/<producto>/<slug>`.

## Resumen

- **El coste de la voz es marginal** con cualquiera de los dos (1–8 USD/mes para 100 videos de 30 s). Lo que decide es el español latino, el encaje con Seedance/OmniHuman y quién carga con el consentimiento.
- **Recomendación: Seed Speech Voice Replication 2.0 (`seed-icl-2.0`) como clonador principal.**
  - Es el único con **español mexicano explícito**.
  - Le bastan 10–30 s de muestra.
  - Cuesta céntimos.
  - Es el mismo proveedor que Seedance.
- **HeyGen solo si compramos sus avatares de punta a punta.** No como proveedor de voz para el pipeline de Seedance.
- **Ningún motor de video acepta el `speaker_id` de Seed Speech.** El patrón que funciona es **voice-as-audio**: la voz vive en Seed Speech y los demás motores consumen el MP3 sintetizado.
- **Seed Speech no tiene API para borrar ni exportar voces.** La voz queda atada a la cuenta BytePlus de Qualify. Hay que diseñar con eso.

## 1. Qué es cada producto

**BytePlus Seed Speech**
- Es un producto **aparte de ModelArk**: otra consola, otra API key y otro host.
  - Host: `voice.ap-southeast-1.bytepluses.com`, autenticación con la cabecera `X-Api-Key`.
  - Una key de ModelArk devuelve 401 / 45000010 ([PR byteplus-sa #4](https://github.com/byteplus-sa/ComfyUI-BytePlus-ModelArk/pull/4)).
  - No hay ningún modelo de TTS en el [model-list de ModelArk](https://docs.byteplus.com/en/docs/modelark/model-list).
- Dos vías para la voz de una persona:
  - **Voice Replication 2.0** (resource `seed-icl-2.0`): se registra una voz con `speaker_id` y se sintetiza con TTS.
  - **Seed Audio 1.0** (`/api/v3/tts/create`): hasta 3 audios de referencia de ≤30 s, salida de hasta 120 s ([seedaudio-01](https://docs.byteplus.com/en/docs/byteplusvoice/seedaudio-01)).

**HeyGen**
- Tres motores de voz: `orca` (HeyGen Voice, el propio), `starfish` (el propio anterior) y `elevenlabs`.
- Los clones instant y professional de la API v3 corren en **HeyGen Voice**, no en ElevenLabs ([heygen-voice](https://developers.heygen.com/docs/models/heygen-voice.md), [instant clone](https://developers.heygen.com/docs/voices/heygen-voice-instant-clone)).
- ElevenLabs es un motor de terceros explícito en `POST /v3/voices/speech` ([Third Party Speech](https://developers.heygen.com/docs/voices/speech)).

## 2. Comparativa

| Criterio | BytePlus `seed-icl-2.0` | HeyGen Voice (API v3) |
|---|---|---|
| Acceso para un tercero | Autoservicio con tarjeta, región Singapur. Prueba gratuita de 20.000 caracteres y 10 voces ([billing](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplicationbilling)) | Autoservicio de pago por uso, sin créditos gratis desde feb-2026; el workspace puede no tener permiso de clonar (`403`) ([pricing](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained)) |
| Muestra | 10–15 s según la API; 14–30 s WAV mono según la guía; ≤10 MB ([enrollment](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication-v3-voice-training), [VR 2.0](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplicationv2)) | Instant: 1–3 min recomendados (solo usa los 3 primeros). Professional: **≥20 min** ([doc](https://developers.heygen.com/docs/voices/professional-voice-clone)) |
| Español LatAm | **Sí: `mx = 16` (es-MX) distinto de `es = 3`** | Solo `es`; «a regional tag does not select a regional accent» |
| Cambio de idioma | **No**: «Cross-lingual voice cloning and synthesis are not supported» ([unidirectional_tts_http](https://docs.byteplus.com/en/docs/byteplusvoice/unidirectional_tts_http)) | No documentado en la API |
| Streaming | HTTP unidireccional + WebSocket; mp3/ogg_opus/pcm | SSE; WAV 44,1 kHz; `heygen-voice-1-turbo` de baja latencia ([TTS](https://developers.heygen.com/docs/voices/heygen-voice-speech)) |
| Consentimiento nativo | **Ninguno.** La carga es del cliente ([commitment-statement](https://docs.byteplus.com/en/docs/byteplusvoice/commitment-statement), AI Terms §1.8) | Voz por API: no documentado. Avatar digital twin: sí ([avatar-consent](https://developers.heygen.com/docs/avatar-consent.md)) |
| Precio | **30 USD por millón de caracteres + 2 USD por voz** (permanente) | Instant gratis durante la preview; precio de síntesis no publicado (un tercero cita 15 USD/M, no verificado) |
| 100 videos × 30 s (~50.000 caracteres) | **≈1,5–3 USD/mes** | ≈1–2 USD/mes (no verificado) |
| Calidad | Sin benchmark independiente (no verificado) | Primero en el TTS Arena de Artificial Analysis según prensa [2ª] |

**Lo único parecido a un control de consentimiento en BytePlus:** el parámetro `text` de `voice_clone` compara el audio con el texto leído y falla si difieren (error 45001109). Sirve para obligar a que la muestra sea la lectura de una frase de autorización. No verifica la identidad de quien habla.

## 3. Cómo guarda las voces Seed Speech

Fuentes: [guía de pedido y uso](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication) y [Management APIs](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplicationopenapi) (act. 2026-09-04), [Voice Enrollment](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication-v3-voice-training) (act. 2026-09-09).

**Modos de pago**
- **Prepaid:** se compran slots y cada uno trae un `SpeakerID` (`S_…`).
- **Postpaid:** el ID lo elegimos nosotros (`custom_speaker_id`).
  - Los **2 USD se cobran en la primera síntesis**.
  - **Desde esa primera síntesis la voz queda fija:** ya no se puede reentrenar.
  - Si una voz solo se probó y no se usa en 7 días, se borra.

**Duración**
- «no longer incur storage fees or expire» (`ExpireTime: 0`).
- Aun así existe el estado `Expired`, que se da también «if the account is in arrears»: **si la cuenta entra en impago, las voces pueden perderse.**

**Formato del ID postpaid**
- 8–256 caracteres `[A-Za-z0-9_-]`, empieza por letra.
- Único dentro de la cuenta.
- **Prohíbe dos minúsculas seguidas de `_` al inicio**: `qa_…` no vale, `qlf-…` sí.

**Operaciones**

| Operación | Disponible | Fuente |
|---|---|---|
| Crear/entrenar | `POST /api/v3/tts/voice_clone` (hasta 15 entrenamientos por slot) | enrollment |
| Consultar | `POST /api/v3/tts/get_voice` → `status` 0–4 y `demo_audio` (URL válida **1 h**) | [status query](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication-v3-voice-status-query) |
| Listar | `ListMegaTTSTrainStatus` / `BatchListMegaTTSTrainStatus` (firma AK/SK, `Service=speech_saas_prod`) | Management APIs |
| **Borrar** | **No documentado.** El error 45001110 «Voice deletion failed» sugiere que existe por dentro | [error codes](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplication-v3-error-code-reference) |
| Renombrar | No documentado | — |
| **Exportar** | **No.** Solo el `demo_audio` de 1 h | — |

**Datos y atadura a la cuenta**
- La voz **no es portable** entre cuentas ni entre proveedores. El error `OperationDenied.InvalidSpeakerID` habla de permisos por cuenta/AppID.
- Del audio de muestra, **no está documentado ni cuánto tiempo lo guardan ni dónde**.
- AI Terms ([enlace](https://docs.byteplus.com/en/docs/legal/AI-Services-terms)):
  - §3.2: retienen datos «as necessary».
  - §3.3: no entrenan sus modelos base con datos del cliente sin consentimiento.
  - §2.1: el output es del cliente.
- Al clonar aplica revisiones automáticas:
  - 45001104: la voz se parece a un objetivo protegido.
  - 45001127: el audio fue rechazado en la revisión.
  - 45001109: falla el chequeo de texto (WER).

**Multi-tenant (diseño propuesto)**
- Una sola cuenta de BytePlus para Qualify, con voces postpaid.
- `custom_speaker_id` **opaco** (`qlf-` + hex aleatorio), sin el `tenant_id` en claro.
- La correspondencia con tenant y marca vive solo en nuestra base de datos, con RLS.
- El aislamiento lo aplica Qualify (`voice_access`), igual que hoy con HeyGen.

## 4. ¿Se puede clonar en Seed Speech y pasar la voz a otros motores?

| Motor | ¿`speaker_id` de Seed? | Qué acepta | Límites | Flujo recomendado |
|---|---|---|---|---|
| Seed Speech TTS | **Sí** (ahí vive la voz) | texto + speaker | concurrencia 10; ID fijo tras la 1.ª síntesis | origen único → MP3 a R2 |
| Seedance 2.0 | No | audio: `audio_url` + `role:"reference_audio"`, en URL, Base64 o `asset://` | 2–15 s por clip, ≤3 clips, 15 s en total, **siempre con imagen o video**; wav/mp3 ≤15 MB | la muestra como **timbre** + el guion en el prompt |
| Seedance 2.5 | No | audio | ≤10 clips, 30 s en total; acepta solo audio | timbre, o el MP3 del guion (fidelidad no verificada) |
| OmniHuman 1.5 / 2.0 | No | `audio_url` + imagen | 1.5: <60 s, 0,12 USD/s, concurrencia 1 · 2.0: 4–300 s | MP3 sintetizado → **lip-sync exacto** |
| HeyGen `/v3/videos` | **No** (no importa voces externas) | `audio_url` / `audio_asset_id`, mp3/wav ≤32 MB | se pierden los `voice_settings` (velocidad, tono) | MP3 sintetizado → `audio_url` |

Fuentes:
- Seedance: [create-video-generation-task-api](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api) y [seedance-2-0](https://docs.byteplus.com/en/docs/modelark/seedance-2-0), que documenta la referencia de timbre: `"Character" says: "lines", voice timbre references "Audio n"`.
- OmniHuman: [omnihuman-video_generation](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-video_generation) y [omnihuman-2-0](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation).
- HeyGen: [create-video](https://developers.heygen.com/reference/create-video.md) y [audio-to-video](https://developers.heygen.com/audio-to-video.md).

**Seedance regenera el audio.** No hay documentación que diga que reproduce un MP3 dado con lip-sync exacto. Si una voz real suelta en `reference_audio` pasa algún filtro de privacidad: **no documentado**.

**Voice-as-audio frente a clonar en cada proveedor**
- **A favor:**
  - una sola clonación, un solo consentimiento y un solo pago de 2 USD;
  - datos biométricos en un único proveedor;
  - motores intercambiables y comparables (A/B);
  - audio cacheable;
  - español mexicano.
- **En contra:**
  - se pierden los controles nativos de HeyGen;
  - hay un salto más (TTS → R2 → URL con token);
  - no hay cambio de idioma: un video en inglés necesita otra voz entrenada en inglés.
- **Coste del salto:** ≈0,015 USD por video de 30 s. La subida a R2 con URL de token ya existe (`PublicReferenceLinks`).

## 5. Nuestro clonador hoy (leído del código el 2026-10-15)

- **Proveedor: solo HeyGen** (`HeyGenAvatarVideoAdapter.clone_voice` → `POST /v3/voices/clone`, motor Starfish). No usa el modelo nuevo HeyGen Voice.
- **`Qualify/voice_lab.py`:**
  - la muestra se guarda en el directorio local de uploads, **no en R2**;
  - se recodifica a WAV mono 44,1 kHz (máx. 300 s);
  - se sondea cada 4 s durante 300 s;
  - el consentimiento es **un checkbox**;
  - la UI dice «Clonando tu voz en HeyGen…», lo que choca con la regla de no nombrar proveedores ante el operador.
- **Tabla `brand_voice_clones`** (migración 0032):
  - columnas: `heygen_voice_id`, `status`, `language`, `consent_by/at`…;
  - `UNIQUE(brand_id)`;
  - no guarda la muestra, ni el texto del consentimiento, ni el proveedor.
- **`voice_access.BrandVoiceGuard`:** solo deja renderizar con el clon propio de la marca o con voces públicas de HeyGen.

## 6. Plan para añadir Seed Speech (sin implementar)

1. **Spike de una tarde** con la prueba gratuita, para cerrar tres puntos sin verificar:
   - qué va exactamente en `speaker` al sintetizar con `custom_speaker_id`;
   - qué diferencia hay entre una síntesis de prueba y la activación;
   - con qué fidelidad Seedance 2.x sigue un timbre real.
2. **Migración nueva y aditiva** (siguiente número tras la cabeza actual):
   - Tabla `brand_voice_consents`: `consent_text`, versión del texto, `sample_object_key` en R2, `sample_sha256`, duración, idioma, quién y cuándo. Con RLS.
   - Columnas nuevas en `brand_voice_clones`: `provider` (`heygen` | `byteplus_speech`), `external_voice_id`, `consent_id`, `provider_language`, `billing_mode`, `activated_at`, `preview_object_key` y `retired_at` (como no hay API de borrado, la voz sustituida se marca, no se borra).
   - Cambiar la unicidad a `UNIQUE(brand_id, provider) WHERE retired_at IS NULL`.
3. **Adaptador `qualify_creative/adapters/byteplus_speech.py`:**
   - Variable de entorno `QUALIFY_BYTEPLUS_SPEECH_API_KEY`.
   - Funciones `clone_voice`, `get_voice` y `synthesize` (`/api/v3/tts/unidirectional` con `X-Api-Resource-Id: seed-icl-2.0`; con MP3 hay que fijar `bit_rate`).
   - Expuesto como `GenerationProvider`, con `GenerationTask.VOICEOVER` y una tabla de precios v5.
4. **Voice Lab:**
   - El consentimiento pasa a ser leído: la persona graba una frase de autorización de 15–20 s, que se envía en `text`.
   - La muestra se guarda en R2.
   - Paso de **«Confirmar voz»**, porque la primera síntesis cobra y deja la voz fija.
   - Sin nombre de proveedor en los textos.
5. **`media.py`:**
   - `_brand_voiceover()` sintetiza el guion y lo guarda en R2 con una clave idempotente.
   - El audio se consume como `audio_url` en HeyGen y como `reference_audios` en Seedance.
   - `BrandVoiceGuard` pasa a tener en cuenta el proveedor.
6. Más adelante, un adaptador de OmniHuman para lip-sync exacto con la voz de la marca.

**Preguntas abiertas a BytePlus:**
- ¿Hay API de borrado o la ofrecen bajo petición?
- ¿Cuánto tiempo retienen la muestra?
- ¿Se pueden acotar las API keys por proyecto?
- ¿Seedance filtra voces reales en `reference_audio`?
- ¿Cuál es la latencia en ms?

**Preguntas abiertas a HeyGen:**
- ¿Cuál será el precio de la síntesis instant cuando acabe la preview?
- ¿Cuánto cuesta un slot professional?
- ¿Hay paso de consentimiento de voz en la API?
