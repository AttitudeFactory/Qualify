# Síntesis: Alternativas ya desarrolladas para la Fase 1 (Qualify)

**Alcance de Fase 1:** (1) rotación de proxies · (2) social listening · (3) outreach
**Método:** Investigación de mercado (web, julio 2026), mapeada a la arquitectura de Qualify

## Resumen ejecutivo

Los tres bloques de la Fase 1 tienen alternativas maduras ya desarrolladas — la decisión es cuánto delegar en cada uno. Recomendación por bloque: **proxies:** Zyte API o Decodo como capa gestionada (no operar rotación propia); **listening:** comprar la ingesta (EnsembleData/Data365), transcripción barata (Groq/AssemblyAI) y Gemini para visión — el análisis multimodal sí se construye porque es el diferenciador; **outreach:** infraestructura de dominios/mailboxes vía Zapmail o Mailreef (ambos con API headless) y email finding con Prospeo o Findymail. Con este stack, lo único que Qualify construye en Fase 1 es la orquestación y la capa multimodal.

---

## Bloque 1 — Rotación de proxies

| Alternativa | Precio aprox. | Notas |
|---|---|---|
| **Zyte API** (ya en tu arquitectura) | PAYG desde $0 (tope $100/mes); Standard $100/mes | Rotación + CAPTCHAs + anti-bloqueo gestionados; 95%+ éxito en benchmarks |
| **Bright Data Web Unlocker** | Desde $1.50/1K requests; residencial ~$4/GB | Líder en éxito (97.9% en sitios complejos incl. Instagram); pool de 400M+ IPs; geo-targeting ciudad/ASN |
| **Oxylabs** | ~$6/GB residencial; Web Unblocker ~$9.40/GB | Enfoque calidad/enterprise, IPs Tier-1 |
| **Decodo (ex-Smartproxy)** | ~$4/GB; Site Unblocker 93.79% éxito | El "sweet spot" precio/velocidad (sub-2.5ms) |
| **Presupuesto: DataImpulse / IPRoyal** | $1–1.75/GB | Para volumen tolerante a menor tasa de éxito |

**Implicación:** todos manejan rotación, sticky sessions y CAPTCHAs sin intervención manual — no hay razón para construir rotación propia en Fase 1. Zyte sigue siendo buena elección por precio de entrada; Bright Data es el fallback premium si Instagram/TikTok bloquean demasiado. Nota: si compras la ingesta como API (Bloque 2), este bloque se reduce a los scrapers que sí operes tú.

---

## Bloque 2 — Social listening

### 2a. Ingesta / scraping de perfiles y contenido

| Alternativa | Modelo | Precio aprox. | Notas |
|---|---|---|---|
| **EnsembleData** | API por unidades | $100–$1,400/mes | TikTok, IG, YouTube, X, Reddit, Threads, Pinterest, FB. Usado por plataformas de influencer marketing — el fit más directo |
| **Data365** | API por registros | Desde ~$0.60/1K registros | Precio transparente, bajo la media del mercado (~$0.98/1K) |
| **Apify** | Marketplace de actors | ~$1.70/1K (variable) | 24,000+ actors listos; ideal para prototipar |
| **Phyllo / InsightIQ** | Data gateway consentido | Desde ~$199/mes (custom) | 25+ plataformas, esquema unificado; complementario post-outreach (datos first-party) |

**Implicación:** el waterfall enrichment de Qualify se arma en Fase 1 encadenando EnsembleData → Data365 como fallback, sin escribir scrapers propios. Scrapers sobre Zyte cuando el volumen justifique internalizar.

### 2b. Filtro 1 — transcripción de audio

| Alternativa | Precio (batch) | Notas |
|---|---|---|
| **Groq Whisper-v3** | ~$0.04/h | 10–30× más barato que OpenAI; ideal para filtrado masivo |
| **AssemblyAI** | $0.0025/min (~$0.15/h) | El más barato por minuto entre APIs "premium" |
| **Deepgram Nova-3** | $0.0043/min (~$0.26/h) | Mejor balance batch/streaming |

**Implicación:** transcribir el 100% del contenido candidato como primer filtro es económicamente viable, tal como está diseñada la cascada.

### 2c. Filtro 3 — visión / VLM sobre video

| Alternativa | Enfoque | Notas |
|---|---|---|
| **Gemini API** | Prompting multimodal directo sobre video/frames | Encaja con tu diseño (Gemini Flash); Gemini Omni (I/O 2026) amplía capacidades nativas |
| **Twelve Labs** | Video intelligence con búsqueda semántica y embeddings | La alternativa "ya desarrollada" más completa al pipeline frames+YOLO+OCR+VLM; modelos ajustables con datos propios |
| **Google Video Intelligence** | Labels/logos/OCR gestionado | Productizado pero rígido |

**Implicación:** en Fase 1, Gemini sobre frames muestreados basta (puedes saltarte YOLO/Tesseract). POC con Twelve Labs solo si la precisión de detección de marca resulta insuficiente.

### 2d. Plataformas completas (buy total)

**HypeAuditor** (Recruitment API + listening de keywords en IG/TikTok) es lo más cercano a tu Fase 1 completa; **Brandwatch** y **Brand24** son texto-céntricos; **Upfluence** solapa con tu tesis de social commerce — vigilar como competidor. Ninguna resuelve el punto ciego multimodal (~70% de menciones en video sin texto): tu diferenciador sigue abierto, y comprar una de estas lo sacrificaría.

---

## Bloque 3 — Outreach (email frío con rotación de dominios)

### 3a. Infraestructura de dominios, mailboxes y warmup

| Alternativa | Precio aprox. | Notas |
|---|---|---|
| **Zapmail** | ~$32.50/mes por 10 mailboxes Google; API en plan Pro | Dominios + DNS + warmup automatizados; **API headless** para gestionar mailboxes a escala — el modelo que citas en tu visión |
| **Mailreef** | Desde ~$240/mes + costo por envío | Servidores pre-calentados, provisión de dominios/mailboxes; punto medio entre plug-and-play y control total |
| **Smartlead** | $13–19/dominio/año + $3.99–9/mailbox/mes | Motor de envío con rotación de cuentas, warmup, **API + white label** en plan Pro — candidato a ser el backend de outreach de Qualify. **Corrección (`research-features-gtm.md`, 2026-07-18):** el tier Base ($39/mes) trae mailboxes ilimitados **sin API**; la API/white label solo está en Pro (**$94/mes**) — no asumir el coste del tier barato al presupuestar la integración |
| **Instantly** | Planes con warmup incluido | Referente UX; API más limitada para uso embebido. **Corrección:** Instantly deprecó su API v1 el 2026-01-19 y se partió en 3 módulos de precio separado (Outreach/Credits/CRM) — cualquier integración debe apuntar a la API nueva |

**Implicación:** no construyas warmup ni rotación de dominios — es un problema resuelto y arriesgado de reimplementar (deliverability). Para embeber outreach en Qualify, la vía corta es Smartlead white label (envío, plan Pro $94/mes) + Zapmail API (aprovisionamiento de mailboxes).

### 3b. Email finding (localizar el correo del creador)

| Alternativa | Precio aprox. | Notas |
|---|---|---|
| **Prospeo** | ~$0.01/email; 98% precisión (lookup individual) | El más barato por contacto verificado en lookup individual |
| **Findymail** | ~$49/1K verificados; desde $49/mes | Mayor yield bruto; garantía de rebote |
| **Anymailfinder** | $49/1K, planes desde $14/mes | Solo cobra emails verificados |
| **Hunter.io** | $49–299/mes | Referente clásico, API sólida |

**Corrección (`research-features-gtm.md`, 2026-07-18):** el 98% de precisión de Prospeo es válido **solo para lookup individual**. En **bulk** (el modo relevante para enriquecer creators a escala) el hit rate observado cae a **~4.5%** (45/1,000) y **cobra por cada fila importada aunque no haya match** (los créditos no rotan). No usar el 98% para modelar el coste de enriquecimiento masivo de creators — sigue siendo válido como escalón final del waterfall (lookup puntual sobre un creator ya identificado), no como fuente de estimación de coste bulk.

**Implicación:** el paso autónomo "detectar creador → buscar correo → redactar propuesta" se resuelve con Prospeo/Findymail vía API + LLM para la redacción; solo la orquestación (LangGraph/BullMQ) es tuya.

---

## Insights → Oportunidades

| Insight | Oportunidad | Impacto | Esfuerzo |
|---|---|---|---|
| Proxies, ingesta, warmup y email finding son commodities con API | Fase 1 = orquestación + capa multimodal; todo lo demás se compra | Alto | Bajo |
| Transcripción masiva cuesta centavos/hora | Filtro 1 sobre el 100% del contenido es viable | Alto | Bajo |
| Zapmail/Smartlead ofrecen API headless y white label | Outreach embebido en Qualify sin construir infraestructura de email | Alto | Medio |
| Los SaaS de listening son texto-céntricos | El diferenciador multimodal sigue sin competencia directa | Alto | — |
| Upfluence conecta listening con e-commerce | Análisis competitivo antes de definir el pitch | Medio | Bajo |

## Recomendaciones para la Fase 1

1. **Alta — Comprar la ingesta:** EnsembleData primario + Data365 fallback; Zyte solo para scrapers propios que decidas operar. Bright Data como plan B premium anti-bloqueos.
2. **Alta — Filtro 1 con Groq Whisper-v3 o AssemblyAI**, indexando transcripciones en ClickHouse desde el día uno.
3. **Alta — Outreach sobre Smartlead (white label/API) + Zapmail (mailboxes) + Prospeo (email finding):** cero infraestructura propia de deliverability.
4. **Media — Gemini Flash directo para el Filtro 3** (frames muestreados); POC vs Twelve Labs solo si falla la precisión.
5. **Baja — No comprar HypeAuditor/Brandwatch**; usarlos en trial como baseline de calidad.

## Preguntas para investigar después

- Costo end-to-end por 1,000 videos procesados con el stack recomendado (POC).
- Términos de servicio y riesgo legal del scraping por proveedor y región.
- Precisión Gemini Flash vs Twelve Labs detectando menciones de marca sin texto.
- Límites reales del white label de Smartlead (¿multi-tenant para tus clientes?).
- Precio custom de Phyllo para enriquecimiento consentido post-outreach.

## Notas de metodología

Investigación de escritorio (julio 2026) sobre pricing público y comparativas. Precios de entrada publicados, variables por volumen/negociación; no validados con proveedores.

## Fuentes

- Proxies: [Comparativa rotating proxies 2026 (Proxyway)](https://proxyway.com/best/rotating-proxies) · [Residential proxy pricing $/GB](https://dataimpulse.com/blog/residential-proxy-pricing-comparison/) · [Benchmarks unblockers (AIMultiple)](https://aimultiple.com/web-unblockers) · [Zyte API pricing](https://docs.zyte.com/zyte-api/pricing.html) · [Bright Data vs Oxylabs 2026](https://use-apify.com/blog/bright-data-vs-oxylabs-2026)
- Ingesta: [EnsembleData pricing](https://ensembledata.com/pricing) · [Data365 pricing](https://data365.co/pricing) · [Comparativa scraping APIs 2026](https://www.socialcrawl.dev/blog/best-social-media-scraping-apis-2026) · [Phyllo pricing](https://www.getphyllo.com/pricing)
- Transcripción: [Comparativa STT 2026 (Deepgram)](https://deepgram.com/learn/best-speech-to-text-apis-2026) · [Precios STT junio 2026](https://www.buildmvpfast.com/api-costs/transcription) · [Benchmarks STT (FutureAGI)](https://futureagi.com/blog/speech-to-text-apis-in-2026-benchmarks-pricing-developer-s-decision-guide/)
- Visión: [Twelve Labs](https://www.twelvelabs.io/) · [Gemini video understanding](https://ai.google.dev/gemini-api/docs/video-understanding) · [Gemini Omni (TechCrunch)](https://techcrunch.com/2026/05/19/googles-gemini-omni-turns-images-audio-and-text-into-video-and-thats-just-the-start/)
- Listening SaaS: [Social listening APIs 2026 (ForumScout)](https://forumscout.app/blog/social-listening-api) · [Monitoring APIs (Modash)](https://www.modash.io/blog/social-media-monitoring-apis)
- Outreach: [Cold email infrastructure 2026 (Mailforge)](https://www.mailforge.ai/blog/cold-email-infrastructure-tools) · [Zapmail review + API](https://coldemailkit.com/tools/zapmail) · [Smartlead pricing](https://www.smartlead.ai/pricing) · [Mailreef](https://www.mailreef.com/) · [Email finder APIs 2026 (Prospeo)](https://prospeo.io/s/email-finder-api) · [Email finder API (Findymail)](https://www.findymail.com/blog/best-email-finder-api/)
