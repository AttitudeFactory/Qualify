# Caras reales en video con IA — qué modelo hay detrás de cada app, qué se permite y qué vía tiene Qualify

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN DE MERCADO 2026-10-15]` · fuentes consultadas el 2026-10-15

Marcas: **[1ª]** fuente primaria (web, documentación, política o comunicado del proveedor) · **[2ª]** prensa o blog · **no verificado** = no confirmado en fuente primaria.

Pregunta del fundador: los videos con caras de presidentes y políticos que circulan, ¿se hacen todos con Seedance (por ejemplo en ElevenLabs o DaVinci Resolve)?

## Respuesta corta

- **No es cierto que «todas usan Seedance».**
  - **ElevenLabs** revende unos 27 modelos de video de unos 10 proveedores; Seedance es solo uno.
  - **DaVinci Resolve no genera video con IA.** Retoca caras y clona voz sobre un video hecho en otro sitio.
- **Seedance 2.x por los canales oficiales de ByteDance bloquea caras reales:** API de BytePlus, CapCut/Dreamina, y Jimeng/Doubao desde feb-2026.
  - El único caso viral atribuido a Seedance es el de **celebridades** (Cruise y Pitt, feb-2026), hecho en Jimeng antes de las restricciones. Probablemente de ahí viene la creencia (inferencia).
- **En los casos documentados de políticos, la herramienta casi nunca se conoce.** Cuando se atribuye, es por la marca de agua (Sora, Veo) o porque el autor lo declara (Grok).
- **Recomendación para Qualify:**
  - **no dar soporte a figuras públicas ni políticos**;
  - aceptar caras reales solo con prueba de vida de la propia persona;
  - etiquetar el contenido con C2PA o una marca visible.

## 1. App por app

| App | Modelo(s) subyacente(s) | ¿Acepta caras reales? | Política sobre figuras públicas | Fuente |
|---|---|---|---|---|
| **ElevenLabs** | Agregador: Seedance 1/1.5/2.0/2.5, OmniHuman 1.5, Veo 3.x, Gemini Omni, Kling 2.5–3.0, Sora 2, Wan 2.5, MiniMax H3, Runway Gen-4.5, LTX 2, HeyGen Avatar 4, Veed Fabric, Sync, Creatify | Depende del modelo; filtro propio no verificado | Prohíbe suplantar a candidatos y cargos electos sin autorización; uso político solo con consentimiento escrito | [elevenlabs.io/video](https://www.elevenlabs.io/video) · [use-policy](https://elevenlabs.io/use-policy) [1ª] |
| **DaVinci Resolve 21** | No genera. Herramientas: Face Age Transformer, Face Reshaper, Speech Generator (clona voz con ~10 s) | No aplica (edita) | No encontrada | [businesswire](https://www.businesswire.com/news/home/20260414941745/en/) [1ª] · [newsshooter](https://www.newsshooter.com/2026/06/02/davinci-resolve-21-final-release/) [2ª] |
| **CapCut / Dreamina** | Seedance 2.0 | **No** (restringido desde el lanzamiento) | Salvaguardas + marca invisible + C2PA | [capcut.com/newsroom](https://www.capcut.com/newsroom/dreamina-seedance-2) [1ª] |
| **Jimeng / Doubao** (China) | Seedance 2.0 | Solo tu propia cara, con verificación en vivo (desde el 9-feb-2026) | No permite fotos de personas reales como referencia | [technode](https://technode.com/2026/02/10/bytedance-suspends-seedance-2-0-feature-that-turns-facial-photos-into-personal-voices-over-potential-risks/) [2ª] |
| **API de BytePlus** | Seedance 2.0/2.5, OmniHuman | Solo con *real-person asset* (prueba de vida de la persona) | Pre-filtro de salida contra figuras públicas; la AUP prohíbe usar una imagen sin consentimiento | [upload-real-person-portrait-assets](https://docs.byteplus.com/en/docs/ModelArk/upload-real-person-portrait-assets) · [content_pre_filter_faq](https://docs.byteplus.com/en/docs/ModelArk/content_pre_filter_faq) [1ª] |
| **Higgsfield** | Agregador: Seedance, Kling, Wan, Grok Imagine, Sora, Veo, Hailuo + DOP propio | Soul ID (cara reutilizable); filtro no verificado | Scoring de similitud con celebridades (detecta, no prohíbe) | [help center](https://higgsfield.ai/creator-hub/help-center/ai-models/which-ai-model-should-i-use) [1ª] |
| **Venice.ai** | Seedance 2.0 | Sí, con **autodeclaración** de consentimiento (409 `needs_consent`) | Rechaza parecidos reconocibles de figuras públicas (422) | [docs.venice.ai](https://docs.venice.ai/guides/media/seedance-face-consent) [1ª] |
| **fal.ai** | Seedance 2.0 y otros | No documentado | No documentado | [fal.ai](https://fal.ai/models/bytedance/seedance-2.0/image-to-video) [1ª] |
| **Kling** | Propio | No verificado | Uso político prohibido sin consentimiento escrito (cl. 3.1(e)) | [grailogic](https://grailogic.com/articles/ai-video-censorship-2026/) [2ª] |
| **Hailuo / MiniMax** | Propio (H3) | No verificado | No verificado | grailogic [2ª] |
| **Google Veo / Gemini Omni** | Propio | `personGeneration=allow_adult` por defecto; `allow_all` solo con allowlist | Prohíbe suplantación engañosa sin aviso (4.2) y engaño electoral (4.4) | [Vertex](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/veo-video-generation) · [política](https://policies.google.com/terms/generative-ai/use-policy) [1ª] |
| **OpenAI Sora 2** | Propio; **cerrado en 2026** (app abr-2026, API sep-2026) | Solo *cameos* verificados por la propia persona | Figuras vivas bloqueadas; históricas permitidas | [engadget](https://engadget.com/ai/openai-is-shutting-down-its-sora-video-generation-app-211023358.html) · [nbcnews](https://www.nbcnews.com/tech/tech-news/openai-sora-2-guardrails-sag-aftra-bryan-cranston-rcna238715) [2ª] |
| **Runway** | Propio (Gen-4.5, Aleph) | Solo con permiso | Sin excepción explícita para figuras públicas | [conductatlas](https://conductatlas.com/platform/runway/runway-usage-policy/use-of-another-persons-image-video-or-audio-without-permission/) [2ª] |
| **Pika** | Propio | Solo con derechos | Prohíbe celebridades y políticos sin consentimiento, y campañas políticas | grailogic [2ª] |
| **Hedra** | Character-3 propio + OmniHuman 1.5 | No verificado | No verificado (AUP inaccesible) | [hedra.com/terms](https://hedra.com/terms) [1ª] |
| **Grok Imagine** (xAI) | Propio | Sí, en la práctica (casos documentados) | Solo prohíbe lo pornográfico y la violación del derecho de publicidad; no exige consentimiento | [AUP archivada](https://x.ai/legal/acceptable-use-policy/previous-2025-01-02) [1ª] |
| **Open-weight** (Wan 2.2, LTX-2, HunyuanVideo 1.5, Deep-Live-Cam) | Pesos locales | Sin filtro remoto | Solo licencia y ley | [runpod](https://www.runpod.io/articles/guides/wan-2-7-runpod) · [lightricks](https://static.lightricks.com/legal/ltx-2-open-weights-license-0.X.pdf) [2ª/1ª] |

Qué modelo se usa «típicamente» para los virales de políticos: **no verificado**. No existe ningún análisis forense que lo atribuya.

## 2. Seedance: mismo modelo, distinto filtro según el canal

- **API de BytePlus.** Para usar una cara real hay que crear un *real-person asset*:
  1. El titular de la cuenta (con verificación de identidad o de empresa) genera un QR.
  2. La persona retratada inicia sesión en **su propia** cuenta de BytePlus.
  3. Hace la prueba de vida.
  4. Se comprueba que la cara coincide.
  5. Queda una autorización con fecha de validez.

  Además hay un pre-filtro de salida que compara caras y voces con las de figuras públicas: «not… a comprehensive block».
- **Revendedores que confirman el bloqueo:**
  - [APIYI](https://docs.apiyi.com/en/faq/seedance2-asset-face-reference): «upstream content-safety restriction… no proxy is allowed».
  - [ComfyUI](https://docs.comfy.org/tutorials/partner-nodes/bytedance/seedance-2-0): usa el mismo flujo de prueba de vida.
  - [Adobe Firefly](https://community.adobe.com/questions-404/reference-content-can-t-include-real-human-faces-when-using-seedance-2-0-and-seedance-2-0-fast-1631867): Seedance 2.0 rechaza caras reales, a veces también caras generadas por IA (falsos positivos).
- **Revendedores que se contradicen:**
  - Venice pide una autodeclaración, sin prueba de vida.
  - [EvoLink](https://evolink.ai/blog/seedance-2-0-real-human-video-api-guide) afirma «without identity verification». **No verificado; tratarlo como señal de riesgo.**

### Lo que esto implica para Qualify como plataforma

El [Platform Customer Code of Conduct](https://docs.byteplus.com/en/docs/ModelArk/2353368) de BytePlus [1ª] se aplica a quien integra Seedance y lo abre a empresas o creadores externos. Qualify probablemente encaja ahí: es una interpretación nuestra, falta confirmarlo con BytePlus. Obligaciones:

- verificación de identidad de los usuarios finales (2.2);
- **resolver incidentes graves en 5 minutos** (2.4);
- poder rastrear cada pieza generada hasta el ID del usuario final, con un mapeo anónimo hacia BytePlus (2.5);
- **bibliotecas de assets de personas reales por usuario final**, con las autorizaciones guardadas y auditorías (2.6);
- penalizaciones contractuales si se incumple (2.7);
- los agregadores no pueden reintegrar la API en plataformas de contenido de usuarios (2.1);
- revender sin autorización: penalización del 20 % del compromiso mínimo (3).

## 3. Casos 2025–2026 y herramienta atribuida

| Fecha | Caso | Herramienta | Fuente |
|---|---|---|---|
| May 2025 | Deepfake de Macri en las elecciones de CABA | Sin confirmar (hipótesis: Stable Diffusion + Runway + ElevenLabs) | [eleconomista](https://eleconomista.com.ar/politica/como-hizo-video-falso-macri-inteligencia-artificial-sacudio-eleccion-caba-n84843) |
| Jun 2025 | TIME genera disturbios y fraude electoral falsos | Veo 3 | [lavocedinewyork](https://lavocedinewyork.com/en/news/2025/06/04/veo-3-the-ai-that-manufactures-falsehoods-the-latest-frontier-of-deepfake) |
| Oct 2025 | Protesta «No Kings» falsa en Reino Unido | Veo (marca de agua) | [politifact](https://api.politifact.com/factchecks/2025/oct/20/tweets/No-Kings-AI-video-UK-protest) |
| Nov 2025 | Audios falsos de Trump | Sora (marca de agua) | [leadstories](https://leadstories.com/hoax-alert/2025/11/fact-check-recordings-trump-rant-not-release-epstein-flies-ai.html) |
| Ene 2026 | Imágenes sexualizadas de políticos y mujeres | Grok | [nbcnewyork](https://www.nbcnewyork.com/news/national-international/grok-chatbot-restricts-image-generation-backlash-sexualized-deepfakes/6441507/) |
| Feb 2026 | Cruise contra Pitt (celebridades) | **Seedance 2.0** (Jimeng, antes de las restricciones) | [hollywoodreporter](https://www.hollywoodreporter.com/business/business-news/mpa-cease-and-desist-bytedance-seedance-2-0-1236510957/) |
| Mar 2026 | El NRSC publica un deepfake de Talarico | Sin revelar | [cnn](https://www.cnn.com/2026/03/13/politics/james-talarico-ai-deepfake-republicans-midterms) |
| Abr 2026 | Elecciones de Hungría: videos de Magyar y von der Leyen | No identificada | [euperspectives](https://euperspectives.eu/2026/04/hungarys-election-is-flooded-with-ai-deepfakes-and-nobody-is-stopping-them/) |
| Ago 2026 | Van Orden contra Rebecca Cooke | Grok | [wpr](https://www.wpr.org/news/social-media-deepfakes-ai-grok-rebecca-cooke-derrick-van-orden) |
| Oct 2026 | Deepfake de la senadora Kipp (Colorado) | No identificada | [denvergazette](https://www.denvergazette.com/2026/10/13/colorado-election-office-investigates-deepfake-election-video/) |

## 4. Marco legal y de plataformas

- **UE, AI Act art. 50:**
  - Se aplica desde el **2-ago-2026**: los deployers deben etiquetar los deepfakes.
  - El marcado legible por máquina tiene transición hasta el ~2-dic-2026 (Digital Omnibus); su adopción formal hay que verificarla en el Diario Oficial.
  - Multas de hasta 15 M EUR o el 3 % de la facturación.
  - Qualify probablemente cumple los dos roles, deployer y proveedor. Necesita asesoría legal.
  - Fuentes: [faegredrinker](https://www.faegredrinker.com/en/insights/publications/2026/7/eu-ai-act-commission-confirms-transparency-code-of-practice-as-adequate-and-publishes-final-version-of-its-guidelines-on-transparency-obligations) · [compliancehub](https://compliancehub.wiki/eu-ai-act-august-2-2026-what-actually-applies-article-50-omnibus/).
- **EE. UU.:**
  - **TAKE IT DOWN Act**, solo para imágenes íntimas; retirada en 48 h; la FTC lo aplica desde el 19-may-2026 ([ftc](https://search.ftc.gov/news-events/news/press-releases/2026/05/ftc-begins-enforcing-take-it-down-act)).
  - **NO FAKES Act**, aprobado en comité el 18-jun-2026; **no es ley todavía** ([senado](https://www.blackburn.senate.gov/2026/6/blackburn-coons-bipartisan-bill-to-protect-individuals-and-creators-from-deepfakes-passes-senate-judiciary-committee)).
  - Leyes de deepfakes electorales en 30–31 estados ([citizen.org](https://www.citizen.org/article/tracker-legislation-on-deepfakes-in-elections/)).
- **México:**
  - sin reforma federal aprobada; hay iniciativas de feb–mar-2026 ([Gaceta](https://gaceta.diputados.gob.mx/PDF/66/2026/feb/20260218-II-3.pdf));
  - reformas estatales, sobre todo para contenido íntimo: San Luis Potosí, Morelos, Coahuila, Jalisco.
- **Brasil (elecciones de oct-2026):** la Resolución TSE 23.732/2024, actualizada por la 23.755/2026, exige etiquetar el contenido de IA y prohíbe los deepfakes en propaganda ([barbieri](https://www.barbieriadvogados.com/inteligencia-artificial-nas-eleicoes-2026/)).
- **Meta:** exige declarar el contenido creado o alterado digitalmente en anuncios políticos o sociales; sin anuncios políticos en la UE desde oct-2025 (reglamento TTPA).
- **TikTok:** exige etiquetar el contenido de IA realista.

## 5. Vías legítimas para la cara real de un cliente o creador, con su consentimiento

1. **BytePlus real-person asset** (Seedance 2.0/2.5). La vía más sólida: prueba de vida de la propia persona y autorización con caducidad.
   - Fricción: la persona necesita su propia cuenta de BytePlus.
   - Implica las obligaciones de plataforma de la sección 2.
   - Flujo por API, con `CreateVisualValidateSession` → H5 de prueba de vida → `CreateAsset`, ya investigado; ver la memoria de BytePlus.
2. **HeyGen Digital Twin.** Consentimiento por webcam o QR, con registro en `consent_status`. Ver [investigacion-avatar-omnihuman-vs-heygen.md](investigacion-avatar-omnihuman-vs-heygen.md).
3. **Venice + Seedance.** Solo autodeclaración: más débil, y de origen no verificado.
4. **OmniHuman.** Sin requisito publicado de prueba de vida; la responsabilidad recae sobre quien integra.
5. ~~Sora cameos~~: cerrado en 2026.

**Decisión recomendada (pendiente de product-owner / sales-consultant):**
- no soportar figuras públicas ni políticos;
- caras reales solo con prueba de vida de la propia persona;
- etiquetado con C2PA o marca visible en todas las piezas con personas.
