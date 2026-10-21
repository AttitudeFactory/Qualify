# Costos comparativos — voz, avatar, video, imagen y lectura de reels

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[COMPARATIVA 2026-10-15]` · precios oficiales consultados el 2026-10-15, salvo donde se indica

**Referencia de volumen:** **100 videos de 30 s al mes** = 50 min de video ≈ 50.000 caracteres de guion en español (~500 por video). En las columnas «con reintentos» se suma un 50 % para regeneraciones: OmniHuman y Seedance avisan de que no todo resultado sale bien a la primera.

Los precios de HeyGen **se contradicen entre sus propias páginas**: help center frente a blog. Se muestran como rango y hay que confirmarlos en `platform.heygen.com/pricing`. Lo que no está publicado figura como «no publicado».

Detalle y fuentes de cada herramienta:
- [investigacion-voz-seed-speech-vs-heygen.md](investigacion-voz-seed-speech-vs-heygen.md)
- [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md)
- [descubrir-reels-scrapecreators.md](descubrir-reels-scrapecreators.md)

## 1. Voz (TTS y clonado)

| Herramienta | Precio unitario | Alta de la voz | Por video de 30 s | 100 videos/mes | Fuente |
|---|---|---|---|---|---|
| **BytePlus Seed Speech** (`seed-icl-2.0`, pago por uso) | 30 USD / millón de caracteres | **2 USD por voz**, una vez, en la 1.ª síntesis | **≈0,015 USD** | **≈1,5 USD** (3 con reintentos) + 2 USD por voz | [billing](https://docs.byteplus.com/en/docs/byteplusvoice/voicereplicationbilling) |
| Seed Speech, prepago | 2,80 USD / 100.000 caracteres al año | slot prepago | ≈0,014 USD | ≈1,4 USD | idem |
| BytePlus Seed Audio 1.0 | 0,15 USD/min | — | 0,075 USD | ≈7,5 USD | [audiopricing](https://docs.byteplus.com/en/docs/byteplusvoice/audiopricing) |
| HeyGen Voice instant clone | Creación gratis «during the preview»; síntesis **no publicada** (un tercero cita 15 USD/M, **no verificado**) | gratis (preview) | ≈0,0075 USD (no verificado) | ≈0,75 USD (no verificado) | [models](https://developers.heygen.com/models) |
| HeyGen Voice professional | 0,6 créditos API/min (≈0,03–0,036 USD/min, inferido) | slot **no publicado** | ≈0,015–0,018 USD | ≈1,5–1,8 USD + slot | [changelog](https://developers.heygen.com/changelog) |
| HeyGen Starfish (voces de catálogo, sin clonar) | 0,12 USD/min | — | 0,06 USD | 6 USD | [help](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) |
| ElevenLabs (v2/v3/v4) | 0,08 USD / 1.000 caracteres (Turbo/Flash: 0,04) | plan Starter 6 USD/mes | ≈0,02–0,04 USD | ≈2–4 USD + plan | [pricing/api](https://elevenlabs.io/pricing/api) |

**Conclusión:** la voz es **marginal** frente al video. Lo que cambia de un proveedor a otro es el español mexicano (solo Seed Speech lo distingue), cuánta muestra pide (Seed Speech 10–30 s; HeyGen professional ≥20 min) y el consentimiento.

## 2. Avatar que habla (foto + audio → video con lip-sync)

| Herramienta | Precio unitario | Por video de 30 s | 100 videos/mes | Con reintentos (×1,5) | Notas |
|---|---|---|---|---|---|
| HeyGen Avatar III Photo/Studio | 0,99 USD/min | 0,50 USD | ~50 USD | ~75 USD | calidad inferior |
| HeyGen Avatar III Digital Twin | 0,60 USD/min (+2,13 USD por creador) | 0,30 USD | ~30 USD | ~45 USD | 4K en twins |
| **HeyGen Avatar IV Photo / imagen** | **2,31–3,00 USD/min** | **1,16–1,50 USD** | **~116–150 USD** | ~173–225 USD | **TTS incluido** (inferido); sin control de consentimiento |
| HeyGen Avatar IV Digital Twin | 4,83 USD/min (+2,13 USD por creador) | 2,42 USD | ~242 USD | ~362 USD | consentimiento por webcam con registro |
| HeyGen Avatar V Twin | 4,00–7,20 USD/min | 2,00–3,60 USD | ~200–360 USD | ~300–540 USD | el más reciente |
| **BytePlus OmniHuman 2.0** | **0,07 USD/s** | **2,10 USD** + voz | **~210 USD** | ~315 USD | audio de 4–300 s; concurrencia no documentada |
| BytePlus OmniHuman 1.5 | 0,12 USD/s | 3,60 USD + voz | ~360 USD | ~540 USD | **concurrencia 1**, ~12 min por clip |
| OmniHuman 1.5 vía fal.ai | 0,16 USD/s | 4,80 USD | ~480 USD | ~720 USD | revendedor |
| BytePlus Clone Avatar | 300 USD por avatar + 0,015 USD/s | 0,45 USD | ~45 USD + 300 USD por creador | — | requiere video de ≥1 min |

Fuentes: [HeyGen API pricing](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained) · [blog HeyGen](https://www.heygen.com/blog/best-ai-avatar-talking-head-apis) · [OmniHuman 1.5](https://docs.byteplus.com/en/docs/byteplus-vision/omnihuman1_5overview) · [producto OmniHuman](https://www.byteplus.com/en/product/OmniHuman) · [fal.ai](https://fal.ai/models/fal-ai/bytedance/omnihuman/v1.5) · [Clone Avatar](https://docs.byteplus.com/en/docs/byteplus-vision/clone-avatar-onepage).

## 3. Video generado e imagen (lo que el generador ya usa)

| Herramienta | Precio | Por video de 30 s | Notas | Fuente |
|---|---|---|---|---|
| Seedance 1.0 Pro (`seedance-1-0-pro-250528`) | 2,5 USD / millón de tokens | según tokens (no medido por 30 s) | sin audio; clips de 2–12 s | verificado en vivo el 2026-10-07 |
| **Seedance 2.0 mini** (`dreamina-seedance-2-0-mini-260615`) | **0,38 USD por 5 s a 720p** sin video de entrada; hasta ≈0,91 si se le da un video de referencia | **≈2,27 USD** (≈2,5–5,5 con video de referencia) | habla con voz propia; el audio de referencia solo da el timbre y **no se cobra**; **rechaza caras reales** salvo real-person asset | corregido 2026-10-15, ver [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md) |
| Seedance 2.x (activación) | requiere **>30 USD de saldo** para activarse | — | — | verificado el 2026-10-07 |
| Seedream 5.0 lite (`seedream-5-0-lite-260128`) | **0,035 USD/imagen** | — | imágenes del carrusel y del anuncio | verificado en vivo el 2026-10-07 |
| Remotion (plantillas) | **0,00 USD** con licencia Free (equipo ≤3) | 0 | render propio | `pricing` `remotion_selfhost` |

## 4. Lectura de reels y revisión de rubro («Descubrir reels»)

| Concepto | Precio | Por marca (~10 referentes) | Fuente |
|---|---|---|---|
| ScrapeCreators, lista de reels | 1 crédito por página (12 IG / 10 TikTok) | 15–35 créditos por lectura completa de 30 días | medido en vivo el 2026-10-15 |
| Créditos ScrapeCreators | 1,88 USD por 1.000 (Freelance) · 0,99 USD por 1.000 (Business); no caducan | **0,45–2 USD/mes** con una lectura diaria | [scrapecreators.com](https://scrapecreators.com) |
| Transcripción, **solo bajo demanda** («Ver transcripción» / «Replicar») | IG: 1 crédito por reel ≤120 s (0 desde la caché o sin voz) · TikTok: 0 (subtítulos nativos) | 1 crédito por reel de Instagram que alguien abra; una lectura no paga ninguna | medido en vivo el 2026-10-15 |
| Detalle / comentarios (para replicar) | 1 crédito cada uno (0 con `cache_max_age`) | ≈2 créditos por reel replicado | [docs](https://docs.scrapecreators.com) |
| Revisión de rubro con Claude (`claude-sonnet-5`, effort bajo) | según tokens (lotes de 20 reels) | no medido en vivo; se registra por llamada (`CallStats`) | `reels_ai.review_reels` |

Saldo de ScrapeCreators el 2026-10-15: **3.681 créditos**.

## 5. Coste por pieza de punta a punta — un reel de 30 s con la cara y la voz de la marca

| Ruta | Componentes | Por video | 100/mes | Lo que ofrece | Lo que exige |
|---|---|---|---|---|---|
| **A. HeyGen de punta a punta** (Avatar IV Photo) | avatar + TTS de HeyGen | **1,16–1,50 USD** | **~116–150 USD** | lo más barato con calidad IV; 9:16 nativo; concurrencia 10 | consentimiento propio (Photo no lo controla) |
| **A'. HeyGen Digital Twin** (Avatar IV) | twin + voz clonada automática | 2,42 USD (+2,13 por creador) | ~242 USD | consentimiento verificado por HeyGen | video de entrenamiento de 15–600 s |
| **B. Seed Speech + OmniHuman 2.0** | voz clonada (0,015) + avatar (2,10) | **≈2,12 USD** | **~212 USD** (+2 USD por voz) | es-MX explícito; mejor cuerpo entero y cámara | verificación empresarial de BytePlus; prueba de cara real pendiente |
| **C. Seed Speech + HeyGen Avatar IV** | voz clonada (0,015) como `audio_url` + avatar | ≈1,18–1,52 USD | ~118–152 USD | una sola voz clonada reutilizable en todos los motores | se pierden los ajustes de voz de HeyGen |
| **D. Seedance 2.0 mini, solo timbre** | Seedance + muestra de voz como referencia | ≈2,28 USD | ~228 USD | todo en ModelArk; escenas generadas | la voz es **aproximada**: Seedance regenera el audio, no hace lip-sync del nuestro; caras reales solo con real-person asset |
| **D'. Seedance 2.0 mini + HeyGen Lipsync Precision** | escena de Seedance + nuestro MP3 con lip-sync posterior | **≈3,16 USD** | ~316 USD | la escena de Seedance hablando con la **voz exacta** de la marca | dos proveedores; A/B pendiente frente a Sync.so |
| E. OmniHuman 1.5 | avatar 1080p + voz | ≈3,62 USD | ~362 USD | 1080p | concurrencia 1: colas de horas |

**Lectura:**
- **La opción más barata con buena calidad es HeyGen Avatar IV Photo (A)**, pero obliga a construir el consentimiento.
- **C** suma la ventaja de una sola voz clonada y reutilizable casi sin coste extra.
- **B** cuesta ~40 % más que A/C. Solo compensa si los planos de cuerpo entero o el español mexicano marcan la diferencia en el A/B.
- **D** es barata pero la voz solo se parece. Para que Seedance hable con la voz exacta de la marca hace falta **D'** (un lip-sync posterior), ≈3,16 USD por reel. El detalle por motor está en [voz-clonada-en-modelos-de-video.md](voz-clonada-en-modelos-de-video.md).

En todas las rutas, **la voz es menos del 2 % del coste**: el video manda.

## 6. Precios que faltan confirmar

- **HeyGen:** el precio real en `platform.heygen.com/pricing` (2,31 frente a 3,00 USD/min en Avatar IV Photo, 4,00 frente a 7,20 en Avatar V), la síntesis instant cuando acabe la preview, el slot professional, y las condiciones de marca blanca y uso multi-tenant.
- **BytePlus:**
  - si OmniHuman 2.0 se activa sin pasar por ventas, su concurrencia, y si hay saldo mínimo de activación;
  - **qué tarifa aplica a OmniHuman 2.0**: su página de producto da 0,07 USD/s y también 0,12 USD/s («lip sync tier»), así que la ruta B podría costar ≈3,62 USD y no ≈2,12;
  - la combinación OmniHuman + edición con Seedance cuesta ≈4,8–24 USD por reel (ver [omnihuman-caras-reales-y-edicion-seedance.md](omnihuman-caras-reales-y-edicion-seedance.md)).
- **Seedance 2.0 mini:** coste medido de un video de 30 s real (el cálculo de 0,38 USD por 5 s sale de la fórmula de tokens; no se ha medido).
- **Claude:** coste medido de la revisión de rubro por marca y mes.
