# Avatar humano que habla — BytePlus OmniHuman frente a HeyGen

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN VENDOR 2026-10-15]` · fuentes consultadas el 2026-10-15 · sin llamadas en vivo

Marcas: **[DOC]** documentación oficial · **[2ª]** tercero · **no verificado** = no confirmado en fuente primaria.

Caso de uso: foto del creador o de la persona + audio → video vertical con lip-sync para reels.

## Resumen

- **OmniHuman no está en ModelArk.** Está en **BytePlus Vision AI**, que tiene otro host, otra autenticación y otra activación, y **exige verificación empresarial**. La key de ARK no sirve. En `model-list` y `model-pricing` de ModelArk no aparece nada con «omni», «avatar» ni «lip».
- **Recomendación: HeyGen API v3 (Avatar IV) como proveedor principal.**
  - **Por defecto, Digital Twin** con el consentimiento por webcam que da la propia API.
  - Photo Avatar solo con un consentimiento propio de Qualify.
- **OmniHuman como opción secundaria y experimental** para:
  - planos de cuerpo entero y cámara cinematográfica;
  - sujetos no humanos: mascotas de marca, ilustraciones, productos que «hablan».
  - **Condición previa:** una prueba en vivo con la cara real de una persona que haya dado su consentimiento.

## 1. Dónde está OmniHuman

| | 1.0 Quick Mode | 1.5 | 2.0 |
|---|---|---|---|
| `req_key` | `realman_avatar_picture_omni_cv` | `realman_avatar_picture_omni15_cv` | `realman_avatar_picture_omni20_cv` |
| Action | `CVSubmitTask` / `CVGetResult` | idem | `CVSync2AsyncSubmitTask` / `…GetResult` |
| Precio | 0,12 USD/s | 0,12 USD/s, **concurrencia 1** | 0,07 USD/s (página de producto) |
| Audio | ≤30 s | **<60 s** | 4–300 s |
| Salida | MP4 30 fps | 720p / 1080p | 720p nativo |

- **Host y autenticación:**
  - `https://cv.byteplusapi.com`, `Version=2024-06-06`, firma HMAC-SHA256 con AK/SK, `Region=ap-singapore-1`.
  - Alternativa con Bearer: `https://openapi.cv.bytepluses.com/api/common/v3/submit_task`.
- **Fuentes:** [1.5 API](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-video_generation) · [1.5 resumen/precio](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman1_5overview) · [2.0 API](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman-2-0-video-generation) · [API key](https://docs.byteplus.com/en/docs/byteplus-vision/api-key-usage-instructions) · [producto](https://www.byteplus.com/en/product/OmniHuman).
- **Activación:** Console → Model Plaza → «Activate Service». Exige una cuenta con verificación empresarial ([FAQ](https://docs.byteplus.com/en/docs/byteplus-vision/FAQ)). Si la 2.0 se activa sin pasar por ventas: no verificado.
- **Rarezas de la documentación:**
  - la de 1.0 menciona «Volcengine account… Dreamina», que parece un copia-pega de la versión china;
  - la página de producto se titula «2.0» pero enlaza el informe técnico de la 1.5.

## 2. Entradas y salidas

**OmniHuman**
- **Entradas:** una foto (1.5: JPG/PNG <5 MB · 2.0: hasta 30 MB, aspecto 0,4–2,5, así que el 9:16 entra) + `audio_url` (wav/mp3) + prompt opcional.
  - **No trae TTS:** la voz la ponemos nosotros.
  - Sin parámetro de aspecto de salida: que la salida conserve el encuadre de la foto es una inferencia, no verificada en vivo.
- **Prompt:**
  - idiomas: zh/en/ja/ko/**español de México**/id;
  - controla gestos, cámara y emociones, y admite secuencias «primero… luego…»;
  - multipersona con `mask_url`.
- **Tiempo de render (1.5, oficial):** RTF de 27 a 1080p y 23 a 720p, es decir **unos 11,5–13,5 min por clip de 30 s**.
- **Asíncrono:** `callback_url` disponible. **La URL del video caduca en 1 h:** hay que copiarla a R2 enseguida.
- La propia documentación avisa: «not every generation effect may meet your expectations». Hay que presupuestar reintentos.

**HeyGen** ([modelos](https://developers.heygen.com/models.md))
- **Motores:**
  - Avatar IV, el que usa por defecto: Studio, Digital Twin, Photo Avatar o una **imagen arbitraria** (`type:"image"`), con `motion_prompt` y `expressiveness`.
  - Avatar V: solo Digital Twin elegible.
  - Avatar III: 4K en twins.
- **Formas de crear el avatar:**
  - una sola foto ([avatar-from-photo](https://developers.heygen.com/docs/avatar-from-photo.md));
  - un video de entrenamiento de 15–600 s para Digital Twin, que además clona la voz automáticamente ([avatar-from-video](https://developers.heygen.com/docs/avatar-from-video.md)).
- **Entrada de voz:** TTS (300+ voces) o `audio_url` propio para lip-sync ([audio-to-video](https://developers.heygen.com/audio-to-video.md)).
- **Salida:** 1080p por defecto y **9:16 nativo**.
- **Asíncrono:** webhooks firmados, lotes de 100, subtítulos y fondo transparente ([webhooks](https://developers.heygen.com/docs/webhooks.md)).
- **Límites:**
  - guion de 5.000 caracteres;
  - audio de 10 o 30 min (los propios docs se contradicen);
  - concurrencia de 10 en pago por uso y 20 en Enterprise ([usage-limits](https://developers.heygen.com/docs/usage-limits.md)).

## 3. Caras reales y consentimiento

- **OmniHuman:**
  - Según la documentación acepta caras reales: el producto es `realman_avatar_…` y no se documenta ningún error de privacidad equivalente al `PrivacyInformation` de Seedance.
  - El único rechazo documentado es `50510` del Content Pre-filter, que cubre menores, odio, desnudos, violencia y desinformación, **no «persona real»** ([pre-filter](https://docs.byteplus.com/en/docs/byteplus-vision/vision-ai-content-pre-filter)).
  - **No lo ha verificado nadie en vivo.**
  - **No tiene flujo de consentimiento:** la responsabilidad es contractual del cliente (AI Terms §1.8; la [AUP GenAI](https://docs.byteplus.com/en/docs/legal/acceptable_use_policy_byteplus_genai) prohíbe usar la imagen de una persona sin consentimiento y quitar marcas de agua).
  - La 2.0 tiene `enable_watermark`, activado por defecto.
- **HeyGen:**
  - **Photo Avatar o imagen arbitraria: sin control de consentimiento.** Textual: «HeyGen runs no consent check and keeps no consent record for a photo avatar».
  - **Digital Twin: consentimiento obligatorio**, en tres niveles:
    1. webcam en una página de HeyGen, para todos los clientes (enlace válido 24 h);
    2. subir un video de consentimiento, solo Enterprise;
    3. saltárselo con un acuerdo de indemnidad, solo Enterprise.
  - El estado se consulta en `consent_status` ([avatar-consent](https://developers.heygen.com/docs/avatar-consent.md)).
  - Su [política de moderación](https://www.heygen.com/moderation-policy) prohíbe representar a personas reales sin consentimiento explícito.

## 4. Español y calidad

- **OmniHuman:**
  - el prompt admite español de México;
  - la calidad del lip-sync en español no está verificada;
  - un tercero dice que los gestos son más naturales en inglés [2ª].
- **HeyGen:** traducción de video a **175+ idiomas** con lip-sync ([video-translate](https://developers.heygen.com/docs/video-translate.md)).
- **No existe una comparativa independiente sólida entre los dos.**
  - El informe de Avatar V de HeyGen reporta un 85,7 % de victorias frente a OmniHuman 1.5. Es del propio fabricante y no se ha verificado.
  - Versely [2ª, sin metodología] dice que OmniHuman 1.5 gana en cuerpo entero.
  - **El criterio final debe ser un A/B propio con el mismo audio en español y la misma foto.**

## 5. Precio para ~100 videos de 30 s al mes (50 min)

Las dos páginas oficiales de HeyGen no coinciden en precios:
- el [help center](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) da 2,31 USD/min para Avatar IV Photo;
- el [blog](https://www.heygen.com/blog/best-ai-avatar-talking-head-apis) da 3,00 USD/min.

Hay que confirmarlo en `platform.heygen.com/pricing`.

| Opción | Unitario | 50 min | Con 1,5× de reintentos |
|---|---|---|---|
| HeyGen Avatar III Photo | 0,99 USD/min | ~50 USD | ~75 USD |
| **HeyGen Avatar IV Photo / imagen** | 2,31–3,00 USD/min | **~116–150 USD** | ~173–225 USD |
| HeyGen Avatar IV Digital Twin | 4,83 USD/min (+2,13 USD por creador) | ~242 USD | ~362 USD |
| HeyGen Avatar V Twin | 4,00–7,20 USD/min | ~200–360 USD | ~300–540 USD |
| **OmniHuman 2.0** | 0,07 USD/s | **~210 USD** | ~315 USD |
| **OmniHuman 1.5** | 0,12 USD/s | **~360 USD** | ~540 USD |
| OmniHuman 1.5 vía [fal.ai](https://fal.ai/models/fal-ai/bytedance/omnihuman/v1.5) | 0,16 USD/s | ~480 USD | ~720 USD |
| BytePlus Clone Avatar (requiere un video de ≥1 min) | 300 USD por avatar + 0,015 USD/s ([doc](https://docs.byteplus.com/en/docs/byteplus-vision/clone-avatar-onepage)) | ~45 USD + 300 por creador | — |

La voz para OmniHuman sale en ~4 USD/mes con ElevenLabs o ~1,5 USD/mes con Seed Speech; es despreciable. Ver [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md).

## 6. Riesgos

**OmniHuman**
- **Concurrencia 1 en la 1.5.** Con ~12 min por clip, 100 videos son unas 20 h de cola en serie; en picos de varios clientes, la espera es de horas.
- Otra credencial y otra activación distintas de las de ModelArk.
- Documentación inmadura.
- BytePlus «may discontinue… any AI Service at any time».
- Región `ap-singapore-1`.

**HeyGen**
- Precios que se contradicen entre sus propias páginas.
- Condiciones de marca blanca y uso multi-tenant poco explícitas: los Términos prohíben «white-labeling… unless we explicitly make such functionality available». **Hay que confirmarlo con ventas.**
- Jurisdicción: California.

**Etiquetado:** en los dos casos, poner un aviso visible de «contenido generado con IA» (Términos de HeyGen, AI Terms §1.4 de BytePlus y AI Act de la UE, art. 50; ver [investigacion-caras-reales-video-ia.md](investigacion-caras-reales-video-ia.md)).
