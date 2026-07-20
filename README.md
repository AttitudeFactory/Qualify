# Qualify — CRM de Marketing Moderno con Social Intelligence

> Plataforma que combina **social listening con IA** (estilo [Buzzmonitor](https://contenido.getbuzzmonitor.com/ia-para-social-listening)) con un **motor de GTM y activación de revenue** (estilo [Viralnetix](https://viralnetix.com/#services)), construida sobre un pipeline propio de ingesta y enriquecimiento de contenido social (TikTok / Instagram Reels).

## Visión

Las marcas hoy usan dos mundos separados: herramientas de social listening para *entender* la conversación (menciones, sentiment, crisis) y herramientas de GTM/CRM para *actuar* sobre ella (outbound, pipeline, campañas). **Qualify une ambos**: escucha todo lo que se dice sobre una marca y su competencia en redes sociales, lo transforma en insights accionables con IA, y convierte esos insights directamente en acciones de marketing y ventas — identificación de creators/leads, respuestas inteligentes, alertas de crisis y campañas — sin trabajo manual.

## Qué queremos lograr

1. **Monitorear el universo completo de una marca** en TikTok e Instagram Reels: posts, video, audio, captions y comentarios — no solo texto, también contenido audiovisual (visual listening).
2. **Transformar millones de datos en insights claros con un clic**: sentiment, temas, relaciones entre términos, resúmenes cualitativos generados por IA (AI Insights).
3. **Prevenir crisis de reputación** con alertas automáticas sobre menciones, picos de sentiment negativo y menciones dentro de videos/audios.
4. **Mapear públicos e influencers**: características de audiencia (idioma, ubicación, intereses), scoring de creators y gestión de relaciones tipo CRM.
5. **Activar revenue**: pasar del insight a la acción — outbound automatizado a creators/leads calificados, smart replies con RAG, reporting de campañas en tiempo real y CRM siempre limpio y enriquecido.

## Características principales

| Área | Característica | Inspiración |
|---|---|---|
| Social Listening | Seguimiento de cualquier término, marca o competidor; sentiment en español (robertuito); clasificación automática de posts con ML | Buzzmonitor |
| Visual Listening | IA describe imágenes y videos (Moondream2 / Qwen2.5-VL) + transcripción de audio (faster-whisper) → búsqueda por palabras clave dentro de contenido audiovisual | Buzzmonitor |
| AI Insights | Resúmenes cualitativos automáticos de informes de monitoreo con un clic | Buzzmonitor |
| Dashboards | Dashboards ilimitados en tiempo real: KPIs, campañas, comparativas de competencia | Buzzmonitor |
| Alertas | Alertas automáticas de crisis, menciones en video/audio y picos de conversación | Buzzmonitor |
| Audiencias | Mapeo de públicos: género, ubicación, idioma, temas de interés | Buzzmonitor |
| CRM de creators | Base de creators/influencers con métricas, historial de contenido y scoring de afinidad de marca | Qualify |
| GTM Engine | Outbound automatizado (secuencias, enriquecimiento de leads), inbound intelligence, CRM limpio y enriquecido automáticamente | Viralnetix |
| Smart Replies | Respuestas sugeridas con RAG sobre comentarios/transcripts para atención al cliente y community management | Buzzmonitor + Viralnetix |

## Arquitectura

Arquitectura completa en [docs/arquitectura.md](docs/arquitectura.md) (diagramas, esquemas de datos, ADRs). Resumen:

**Monolito modular + workers asíncronos**, con dos planos de datos: **PostgreSQL** (estado transaccional del CRM: pipelines, campañas, gifting, agent runs) y **ClickHouse** (hechos analíticos: métricas, transcripciones, embeddings). Los módulos se comunican por eventos de dominio (`mention.detected`, `trend.spike`, `creator.enriched`), nunca por llamadas directas.

Módulos:

| Módulo | Responsabilidad |
|---|---|
| Core CRM | Workspaces, pipelines de creators, campañas, gifting (Postgres) |
| Listening & Ingesta *(Fase 1, en curso)* | Pipeline Zyte → Redis/Celery → workers CPU (ffmpeg, CLIP, sentiment) → GPU serverless (vision + whisper) → ClickHouse + R2 — ver [docs/plan-ingesta-social.md](docs/plan-ingesta-social.md) |
| Cascada Multimodal | 3 filtros de costo creciente: transcripción → CLIP/OCR → VLM solo para pre-calificados |
| Waterfall Enrichment | Perfil on-demand: cache → scrape directo → APIs fallback, con TTL por tipo de dato |
| Orquestador Agentivo | Grafos LangGraph que convierten eventos en workflows (prospección autónoma) con checkpoints humanos y presupuestos |
| Outreach | Secuencias vía Instantly/HeyReach (buy, don't build); respuestas mueven deals de etapa |
| Atribución | Códigos/UTM por creador vía Shopify → ROI por creador/campaña |

## Roadmap por fases

### Fase 1 — Ingesta y enriquecimiento social *(en curso — ver plan detallado)*
Pipeline completo TikTok/IG Reels: scraping, extracción de frames/audio, filtro CLIP, descripciones visuales, transcripciones, comentarios con sentiment, índice FTS. Es la base de datos sobre la que se construye todo lo demás.

La Fase 1 cubre tres bloques: **rotación de proxies**, **social listening** y **outreach**. Cada uno tiene alternativas ya desarrolladas (buy vs build) — análisis completo con precios en [docs/alternativas-fase1.md](docs/alternativas-fase1.md). Resumen:

| Bloque | Alternativa recomendada | Fallback / plan B | Se construye |
|---|---|---|---|
| Rotación de proxies | Zyte API (rotación + CAPTCHAs gestionados) | Bright Data Web Unlocker (premium anti-bloqueos), Decodo (~$4/GB) | Nada |
| Listening — ingesta | EnsembleData (API TikTok/IG) | Data365 (~$0.60/1K registros), Apify (prototipos) | Solo scrapers que decidamos internalizar |
| Listening — transcripción (Filtro 1) | Groq Whisper-v3 (~$0.04/h) | AssemblyAI ($0.15/h), Deepgram Nova-3 | Nada |
| Listening — visión (Filtro 3) | Gemini Flash sobre frames muestreados | Twelve Labs (POC si falla precisión de detección de marca) | La capa multimodal propia (diferenciador) |
| Outreach — infraestructura email | Zapmail (mailboxes + warmup, API headless) + Smartlead (envío, API/white label **en plan Pro, $94/mes** — el tier Base $39/mes no la incluye) | Mailreef, Instantly (API v1 deprecada 2026-01-19, apuntar a la nueva) | Nada (deliverability = problema resuelto, riesgoso de reimplementar) |
| Outreach — email finding | Prospeo (~$0.01/email verificado en **lookup individual**; en bulk el hit rate real es ~4.5% y cobra por fila importada — no usar el 98% para modelar coste de enriquecimiento masivo) | Findymail, Anymailfinder | Nada |

Principio: en Fase 1 solo se construye la **orquestación** (Celery/LangGraph) y la **capa de análisis multimodal**; todo lo demás se compra vía API. Ningún SaaS de listening (HypeAuditor, Brandwatch, Brand24, Upfluence) resuelve el punto ciego multimodal en video — ese diferenciador queda intacto. (Nota: el discovery/lookalike de creators sobre contenido *sí* tiene ya competencia — Modash, Kuli, Syncly Social — ver `docs/research-features-gtm.md`; el diferenciador de Qualify en esa capa se redefinió como fusión listening→activation + eje comentarios/provenance, no "nadie lo hace con contenido".)

### Fase 2 — Social Listening + AI Insights
- Monitoreo de términos, hashtags y competidores (queries guardadas + scheduler)
- Informes de sentiment y temas; relaciones entre términos
- AI Insights: resúmenes cualitativos automáticos de cualquier informe (LLM sobre `search.content_index`)
- Dashboards en tiempo real (KPIs, evolución de menciones, share of voice)

### Fase 3 — Alertas y Visual Listening avanzado
- Alertas automáticas: picos de menciones, sentiment negativo, palabras clave críticas
- Alertas sobre menciones *dentro* de videos/audios (vía transcripts + vision descriptions)
- Detección de logos/productos en frames; clustering visual con embeddings

### Fase 4 — Audiencias y CRM de creators
- Mapeo de públicos: idioma, ubicación, temas de interés por audiencia
- Perfiles de creators: métricas históricas, afinidad de marca, engagement real
- Scoring y calificación de leads/creators (el "Qualify" del nombre)
- Vistas CRM: pipeline de relaciones con influencers, notas, estados

### Fase 5 — Activación GTM
- Smart replies con RAG (comentarios y DMs) para atención al cliente
- Outbound automatizado a creators calificados: secuencias, enriquecimiento, seguimiento
- Reporting de campañas en tiempo real y atribución de contenido
- Integraciones: export a CRMs externos, webhooks, API pública

### Fase 6 — Hardening y escala
- Multi-tenant, roles y permisos por marca/agencia
- Observabilidad completa, SLAs, load testing
- Migración de infra según volumen (ClickHouse Cloud, GPU dedicada)

## Estructura del repo

```
Qualify/
├── README.md
├── docs/
│   ├── arquitectura.md                   # Arquitectura del sistema: módulos, datos, ADRs
│   ├── plan-ingesta-social.md            # Plan de implementación Fase 1
│   └── ingenieria-inversa-stack-gtm.md   # Análisis del stack Viralnetix + roadmap priorizado
├── docker-compose.yml            # (Fase 1) ClickHouse, Redis, api, workers
├── packages/                     # (Fase 1) shared, scraper, pipeline, models, gpu-service
├── migrations/clickhouse/        # DDL versionado
└── scripts/
```

## Stack

Python 3.11+ · FastAPI · Celery + Redis 7 · PostgreSQL · ClickHouse · Cloudflare R2 · Zyte API · CLIP · Moondream2 / Qwen2.5-VL · faster-whisper · robertuito · sentence-transformers · LangGraph · RunPod/Modal (GPU serverless) · Hetzner VPS
