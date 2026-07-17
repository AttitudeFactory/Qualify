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

## Arquitectura base

Pipeline de ingesta y enriquecimiento (ver [docs/plan-ingesta-social.md](docs/plan-ingesta-social.md)):

**Zyte (scraping) → Redis/Celery (colas) → Workers CPU (ffmpeg, CLIP, spam/sentiment) → GPU serverless (vision + whisper) → ClickHouse (analítica + FTS + embeddings) + Cloudflare R2 (artefactos)**

## Roadmap por fases

### Fase 1 — Ingesta y enriquecimiento social *(en curso — ver plan detallado)*
Pipeline completo TikTok/IG Reels: scraping, extracción de frames/audio, filtro CLIP, descripciones visuales, transcripciones, comentarios con sentiment, índice FTS. Es la base de datos sobre la que se construye todo lo demás.

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
│   ├── plan-ingesta-social.md            # Plan de implementación Fase 1
│   └── ingenieria-inversa-stack-gtm.md   # Análisis del stack Viralnetix + roadmap priorizado
├── docker-compose.yml            # (Fase 1) ClickHouse, Redis, api, workers
├── packages/                     # (Fase 1) shared, scraper, pipeline, models, gpu-service
├── migrations/clickhouse/        # DDL versionado
└── scripts/
```

## Stack

Python 3.11+ · FastAPI · Celery + Redis 7 · ClickHouse · Cloudflare R2 · Zyte API · CLIP · Moondream2 / Qwen2.5-VL · faster-whisper · robertuito · sentence-transformers · RunPod/Modal (GPU serverless) · Hetzner VPS
