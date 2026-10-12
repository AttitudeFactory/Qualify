# Qualify — CRM de Marketing Moderno con Social Intelligence

> Plataforma que combina **social listening con IA** (estilo [Buzzmonitor](https://contenido.getbuzzmonitor.com/ia-para-social-listening)) con un **motor de GTM y activación de revenue** (estilo [Viralnetix](https://viralnetix.com/#services)), construida sobre un pipeline propio de ingesta y enriquecimiento de contenido social (TikTok / Instagram Reels).

## Visión

Las marcas hoy usan dos mundos separados: herramientas de social listening para *entender* la conversación (menciones, sentiment, crisis) y herramientas de GTM/CRM para *actuar* sobre ella (outbound, pipeline, campañas). **Qualify une ambos**: escucha todo lo que se dice sobre una marca y su competencia en redes sociales, lo transforma en insights accionables con IA, y convierte esos insights directamente en acciones de marketing y ventas — identificación de creators/leads, respuestas inteligentes, alertas de crisis y campañas — sin trabajo manual.

## Qué queremos lograr

1. **Monitorear el universo completo de una marca** en TikTok e Instagram Reels: posts, video, audio, captions y comentarios — no solo texto, también contenido audiovisual (visual listening).
2. **Transformar millones de datos en insights claros con un clic**: sentiment, temas, relaciones entre términos, resúmenes cualitativos generados por IA (AI Insights).
3. **Prevenir crisis de reputación** con alertas automáticas sobre menciones, picos de sentiment negativo y menciones dentro de videos/audios.
4. **Mapear públicos e influencers**: características de audiencia (idioma, ubicación, intereses), scoring de creators y gestión de relaciones tipo CRM.
5. **Servir al operador multi-emprendimiento**: N negocios propios (locales, inmobiliaria, agencia…) sobre la misma instalación, cada uno como tenant aislado con su propio login (`1 login = 1 tenant = 1 negocio`) — ver [`docs/modelo-negocio-operador-multi-emprendimiento.md`](docs/modelo-negocio-operador-multi-emprendimiento.md).
6. **Activar revenue**: pasar del insight a la acción — outbound automatizado a creators/leads calificados, smart replies con RAG, reporting de campañas en tiempo real y CRM siempre limpio y enriquecido.

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

**Monolito modular + workers asíncronos**, con dos planos LÓGICOS de datos sobre **un solo motor PostgreSQL** (ADR 31): el schema `public` para el estado transaccional del CRM (pipelines, campañas, gifting, agent runs) y los schemas `ingestion`/`search`/`signals` para los hechos analíticos: métricas, transcripciones, embeddings). Los módulos se comunican por eventos de dominio (`mention.detected`, `trend.spike`, `creator.enriched`), nunca por llamadas directas.

Módulos:

| Módulo | Responsabilidad |
|---|---|
| Core CRM | Workspaces, pipelines de creators, campañas, gifting (Postgres) |
| Listening & Ingesta *(Fase 1, en curso)* | Pipeline Zyte → Redis/Celery → workers CPU (ffmpeg, CLIP, sentiment) → GPU serverless (vision + whisper) → Postgres analítico + R2 — ver [docs/plan-ingesta-social.md](docs/plan-ingesta-social.md) |
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
- Migración de infra según volumen: el plano analítico a **ClickHouse** cuando se cruce el umbral de ADR 31 (>100 M filas, p95 > 2 s, o un cliente con >5 000 posts/día), GPU dedicada

## Estructura del repo

```
Qualify/
├── README.md
├── docs/
│   ├── arquitectura.md                   # Arquitectura del sistema: módulos, datos, ADRs
│   ├── plan-ingesta-social.md            # Plan de implementación Fase 1
│   └── ingenieria-inversa-stack-gtm.md   # Análisis del stack Viralnetix + roadmap priorizado
├── docker-compose.yml            # (Fase 1) Postgres (pgvector), Redis, api, workers
├── packages/                     # (Fase 1) shared, scraper, pipeline, models, gpu-service
├── migrations/postgres/          # Alembic — todo el esquema, transaccional y analítico
└── scripts/
```

## Operación en producción (runbook)

Producción es un VPS de Hetzner (`qualify-prod` en `~/.ssh/config`) con el stack de `deploy/docker-compose.prod.yml`: `caddy`, `api`, `reflex`, `postgres` y `redis`. El runbook completo, desde el primer despliegue hasta los respaldos, está en [`docs/despliegue-hetzner.md`](docs/despliegue-hetzner.md). Todo se corre desde la Mac, dentro del repo:

| Qué | Comando |
|---|---|
| Desplegar `main` (construye en el servidor, migra, reinicia) | `just deploy qualify-prod` |
| Desplegar otro ref (rollback = un sha anterior) | `just deploy qualify-prod <sha\|rama>` |
| Contenedores + salud a través de Caddy | `just deploy-status qualify-prod` |
| Logs (todos, o un servicio) | `just deploy-logs qualify-prod [api\|reflex\|caddy\|postgres\|redis]` |
| Respaldo de la base ahora | `just deploy-backup qualify-prod` |
| Cambiar un secreto, sin desplegar código | `just env-push qualify-prod KEY` |

### Sesión remota de Claude en el servidor

En el VPS corre una sesión de Claude Code, **`qualify-prod`**, para operar producción desde claude.ai/code o la app móvil de Claude (estado, logs, reinicios, respaldos, rollbacks). Montaje y riesgos: [`docs/despliegue-hetzner.md`](docs/despliegue-hetzner.md) §13.

- **Conectarse:** abrir [claude.ai/code](https://claude.ai/code) o la pestaña *Code* de la app y elegir la sesión `qualify-prod`. Está iniciada con la cuenta del fundador y solo aparece ahí.
- **Si no aparece** (reinicio del servidor, o la red se cayó más de ~10 min):
  ```bash
  ssh -t -i ~/.ssh/qualify_hetzner deploy@2.28.112.133 'bash -lc "qualify-claude --continue"'
  ```
  Desengancharse con **Ctrl-b d**; nunca Ctrl-C, que la apaga.
- **Login vencido** (avisa con 3 días): `/login` dentro de la sesión.

### Desplegar sin GitHub Actions

Para no gastar minutos de Actions: se compila en el servidor desde la Mac. En los ejemplos, `78821b7` es el commit que estaba en producción el 2026-10-12 y `113` un número de PR.

```bash
just deploy qualify-prod          # main
just deploy qualify-prod 78821b7  # un commit concreto, o revertir a uno anterior
```

Sube el código por ssh, compila en el servidor, corre `migrate`, levanta el stack y chequea la salud. Si falla la compilación o la migración, producción sigue en el release anterior. Tarda más que por Actions (2 vCPU que siguen atendiendo tráfico).

- **Desde la sesión remota** no se puede: el servidor no tiene el código ni acceso a GitHub, a propósito. Lo que sí hace sin gastar minutos es revertir a un sha que ya tenga imágenes en GHCR: pedirle, por ejemplo, «revierte a `78821b7d0260ac2c1823ff74a92ee34a2a3623d8`» (corre `/opt/qualify/bin/server-deploy.sh rollback 78821b7d0260ac2c1823ff74a92ee34a2a3623d8`, que salta `migrate` y por eso sirve también a través de una migración, donde `just deploy 78821b7` falla). El sha va completo, de 40 caracteres; en `ls /opt/qualify/releases`, los que desplegó Actions (y por eso tienen imágenes en GHCR) son los de nombre de 40 caracteres; los de `just deploy` tienen 12.
- **Sin CI** (sin minutos, `just merge` se niega): correr lo mismo en la Mac y forzar a propósito, solo el fundador:
  ```bash
  just ci-lint && just ci-test && just up && just test-db && just merge 113 --admin
  ```

### Cambiar un secreto (`just env-push`)

Los secretos de producción viven en **un solo archivo**: `/opt/qualify/.env.prod` en el servidor (dueño `deploy`, permisos 600). Ningún despliegue lo sobrescribe, ni `just deploy` ni el de GitHub Actions: lo que se cambia ahí queda. Se edita desde la Mac, nunca a mano en el servidor:

1. Poner el valor nuevo en el `.env` local, en la raíz del repo.
2. Ver qué va a cambiar, sin escribir nada:
   ```bash
   just env-push qualify-prod --dry-run SCRAPECREATORS_API_KEY
   ```
   Por cada clave sale `same`, `change <huella vieja> -> <huella nueva>` o `add`. La huella son los 8 primeros caracteres del sha256 del valor: sirve para comparar sin mostrar el secreto.
3. Aplicar (acepta varias claves a la vez):
   ```bash
   just env-push qualify-prod SCRAPECREATORS_API_KEY QUALIFY_ANTHROPIC_API_KEY
   ```

Qué hace:

- Copia **sólo las claves nombradas**. Las demás de `.env.prod` no se tocan.
- Antes de escribir deja un respaldo `/opt/qualify/.env.prod.bak-<UTC>` y conserva los 10 más recientes.
- Corre `docker compose up -d --no-build`. Compose recrea exactamente los servicios que leen `.env.prod` (`api`, `reflex` y `calendar-worker` si está activo) y no reinicia `postgres`, `redis` ni `caddy`. No construye imágenes ni corre `migrate`. Son unos 10 s, y al final imprime la salud del sitio.
- Los valores viajan por el stdin de ssh, nunca por argumentos ni por la terminal.
- Desde un worktree lee el `.env` del checkout principal. Otro archivo: `QUALIFY_ENV_SOURCE=/ruta/.env just env-push …`.
- Una clave nueva llega a los contenedores sin tocar el compose, porque el compose les pasa `.env.prod` completo.

Se niega a propósito con estas claves, y dice qué hacer en su lugar:

| Clave | Por qué | En su lugar |
|---|---|---|
| `QUALIFY_DB_*_PASSWORD` | la contraseña se aplica al rol con `migrate` (`ALTER ROLE`) | editar `.env.prod` y `just deploy` |
| `QUALIFY_PUBLIC_URL` | está horneada en el frontend estático | editar `.env.prod` y `just deploy` (reconstruye) |
| `QUALIFY_DEV_FERNET_KEY` | rotarla deja indescifrables todas las credenciales OAuth guardadas | no se rota así |
| `COMPOSE_*`, `QUALIFY_IMAGE_*` | cambian la forma del stack, no son un secreto | editar `.env.prod` y `just deploy` |

**Deshacer un cambio:** volver a empujar el valor anterior desde el `.env` local, o restaurar el respaldo en el servidor:

```bash
ssh qualify-prod 'cd /opt/qualify/current && cp -p /opt/qualify/.env.prod.bak-<UTC> /opt/qualify/.env.prod && docker compose --env-file /opt/qualify/.env.prod $(test -f deploy/release.env && echo --env-file deploy/release.env) -f deploy/docker-compose.prod.yml up -d --no-build'
```

**Antes de empujar una llave de proveedor, verificar que sirve.** El 2026-10-07 se subió una llave de Scrape Creators con 0 créditos. Para Scrape Creators:

```bash
curl -s -H "x-api-key: $(grep '^SCRAPECREATORS_API_KEY=' .env | tail -n 1 | cut -d= -f2-)" https://api.scrapecreators.com/v1/credit-balance
```

**Por qué no Redis ni un gestor de secretos.** El Redis de producción no tiene contraseña y solo persiste por snapshots: no es un lugar para secretos. Recargar en caliente, sin los ~10 s de reinicio, no justifica hoy una pieza nueva. Si llega a hacer falta para las llaves de proveedores, el camino es una tabla en Postgres cifrada con la llave Fernet existente, que la app lea al usarla. Los secretos de arranque (contraseñas de base de datos, llave Fernet, Meta, Supabase) se quedan en `.env.prod` de todas formas.

## Stack

Python 3.11+ · FastAPI · Celery + Redis 7 · PostgreSQL (ambos planos) · pgvector · Cloudflare R2 · Zyte API · SigLIP2 · Qwen3-VL · faster-whisper · robertuito · sentence-transformers · LangGraph · RunPod/Modal (GPU serverless) · Hetzner VPS
