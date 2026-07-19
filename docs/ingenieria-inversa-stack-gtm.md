# Ingeniería inversa del stack GTM (Viralnetix + partners) → Arquitectura y prioridades de Qualify

**Fecha:** 2026-07-17
**Fuentes:** sitios oficiales de los 12 servicios (fetched hoy).
**Objetivo:** entender cómo está construido el stack que Viralnetix ensambla para sus clientes, extraer los patrones de arquitectura, y decidir qué replica Qualify, qué integra, y en qué orden.

---

## 1. El insight central

Viralnetix no vende software: **ensambla un pipeline de datos** con herramientas de terceros. Ese pipeline tiene una anatomía clara y repetida:

```
ACCESO A LA WEB → DESCUBRIMIENTO → ENRIQUECIMIENTO → SEÑALES/INTENT → ORQUESTACIÓN → EJECUCIÓN → INFRA DE ENTREGA
     (Zyte)      (DiscoLike,       (BetterContact,    (Trigify,          (Clay)      (Instantly,     (Zapmail)
                  AI-Ark)           Prospeo)           PredictLeads,                   HeyReach)
                                                       Warmly)
```

Cada capa es un negocio independiente porque cada una resuelve un problema técnico distinto. **Qualify puede unificar las capas de descubrimiento, señales y orquestación para el nicho de influencer/social marketing** — donde ninguno de estos jugadores compite — e integrar (no construir) ejecución y deliverability.

La ventaja competitiva de Qualify: todos estos servicios operan sobre **LinkedIn/web B2B**. Nadie hace este stack completo sobre **TikTok/Instagram con contenido audiovisual**. Tu pipeline de Fase 1 (frames + transcripts + comments) es exactamente la "capa de acceso + descubrimiento" que ellos tienen para la web B2B, pero para social video.

---

## 2. Ingeniería inversa por capa

### Capa 0 — Acceso a la web: Zyte API (rotating proxy)

**Qué es:** una sola API que resuelve bans por sitio: selecciona automáticamente tipo de proxy (residencial vs datacenter), rotación de fingerprints/TLS (200k+ perfiles de navegador reales), headless browser gestionado, manejo de CAPTCHAs solo cuando se dispara, sesiones/cookies persistentes, y extracción con IA (modelos por dominio: ecommerce, artículos, jobs, SERP).

**Cómo funciona por dentro (inferido):** motor adaptativo con una librería de ~320k tácticas de unblocking; cada request evalúa la mínima herramienta necesaria (para no pagar browser rendering si no hace falta). Pricing por respuesta según complejidad del sitio ($0.13/1k HTTP simple → $1.01/1k browser-rendered, pay-as-you-go).

**Lección para Qualify:**
- Ya elegido como proveedor. Confirma el diseño de Fase 1: guardar el JSON crudo (re-parse sin re-scrape) es crítico porque cada request cuesta dinero.
- Copiar el patrón "mínima herramienta necesaria": intentar primero el endpoint HTTP barato, escalar a browser rendering solo si el hydration JSON no aparece.
- Presupuestar por tier: TikTok/IG son sitios "duros" → asumir tarifa browser-rendered en el modelo de costos.

### Capa 1 — Descubrimiento / TAM: DiscoLike y AI-Ark

**DiscoLike:** directorio de 70M+ dominios de empresa construido crawleando *toda la web con SSL* (no scrape de LinkedIn). Tres modos de búsqueda: (1) lookalike por dominio — "dame empresas similares a estos 4-5 dominios"; (2) ICP en lenguaje natural contra LLMs custom entrenados con texto de 60M sitios; (3) exact phrase matching contra el texto del homepage. Además: validación/dedup de dominios (muertos, parked), segmentación automática de listas de clientes, technographics desde el propio sitio.

**AI-Ark:** base B2B con AI company search, people search, **similarity search** (lookalikes), semantic search vía API, refresh cada 30 días, <1% bounce.

**Cómo funciona por dentro (inferido):** crawl masivo → embeddings del texto del sitio → índice vectorial para lookalike/semantic search + índice FTS para phrase matching + clasificadores para firmographics. Es literalmente *tu* arquitectura de Fase 1+4 (embeddings + FTS en ClickHouse) aplicada a homepages en vez de videos.

**Lección para Qualify:**
- El equivalente en tu dominio: **creator lookalike search**. "Dame creators similares a estos 5 handles" usando embeddings de su contenido (transcripts + vision descriptions + captions). **Corrección (`research-features-gtm.md`, 2026-07-18):** la afirmación de que "nadie ofrece esto con contenido real" ya no es cierta en 2026 — Modash (*Creator Lookalikes API*, eje visual+tópicos+captions, ~$16.2K/año) y Kuli (análisis frame-by-frame + transcripción de audio) ya hacen lookalike sobre contenido; Syncly Social (YC, TikTok-native) fusiona listening+discovery sobre audio+visual. El diferenciador sobreviviente, más estrecho de lo que este doc asumía: (1) **fusión listening→activation** en una sola plataforma — los tres competidores anteriores son solo discovery, ninguno cierra el loop a señales+outreach; (2) **la señal de comentarios/audiencia** como eje de similitud — nadie la usa; (3) la capa de señales tipadas con provenance (§2 Capa 3, confirmado vacío en social); (4) multimodal completo (audio+comentarios, no solo visual) y español-first, como refuerzos secundarios **no pilares** — el eje audio ya tiene competencia (Kuli, Syncly) y el español está sin validar empíricamente. Ver `docs/arquitectura.md` §6 (nota de corrección de tesis) y §8.1 item 1.
- Búsqueda de creators en lenguaje natural ("creators fitness en español que mencionan proteína y entrenan en casa") = query semántica sobre `search.embeddings` + filtros en `posts`.
- Patrón clave: **la fuente primaria (contenido real) le gana al metadato auto-reportado**. DiscoLike gana a ZoomInfo porque lee el sitio, no el perfil de LinkedIn. Qualify gana a HypeAuditor si lee el video, no la bio.

### Capa 2 — Enriquecimiento de contactos: BetterContact y Prospeo

**BetterContact:** *waterfall enrichment* — agrega 20+ proveedores de datos en una suscripción. Un algoritmo ("BetterAI") analiza cada contacto y decide **la secuencia óptima de proveedores** a consultar; itera hasta encontrar match. Luego 4 capas de verificación externa (email y móvil); **solo cobra si el dato es válido**. GDPR/CCPA. ~150k enrichments/día.

**Prospeo:** email finder + mobile finder + verificador: por dominio, por nombre+empresa, desde LinkedIn/Sales Navigator (extensión), bulk y API. Compite como *proveedor individual* dentro de waterfalls como el de BetterContact/Clay.

**Cómo funciona por dentro (inferido):** router de proveedores con estadísticas históricas de hit-rate por segmento (país, industria, seniority) → llama proveedores en orden de probabilidad/costo → verificación SMTP + heurísticas + señales externas → cache agresivo para no repagar.

**Lección para Qualify:**
- Patrón **waterfall con verificación y cobro por dato válido** = el estándar de calidad del mercado. Para Qualify: waterfall de contacto de creators (email en bio → link-in-bio (Linktree etc.) → email en website del creator → APIs de terceros como Prospeo/BetterContact como último escalón).
- Arquitectura: un `enrichment-worker` con tabla de proveedores, orden dinámico por hit-rate histórico, cache por (platform, creator_id), y verificación antes de persistir.
- **Integrar, no construir**: BetterContact y Prospeo tienen API; son un escalón del waterfall, no competencia.

### Capa 3 — Señales e intent: Trigify, PredictLeads, Warmly

**Trigify** (el más cercano a Qualify): "Signal Layer for AI Agents". Monitorea 11+ plataformas sociales (LinkedIn, X, Reddit, YouTube, podcasts) con: profile monitors, Boolean search, engagement capture (quién dio like/comentó un post). Cada señal es **una persona nombrada + el post fuente adjunto (provenance)**. Librería de 16+ tipos de señal ABM (cambio de rol, engagement con competidor, buying-window = combinación de señales en ventana temporal, empezó a contratar…). Workflows disparados por señal: agente razona el contexto → enriquece persona/email → push a Instantly/Attio/Slack/Sheets. Co-pilot IA ("Jarvis") que configura monitores y workflows desde lenguaje natural. Todo expuesto por REST API + **MCP** + CLI. Pricing por créditos (**corrección `research-features-gtm.md` 2026-07-18:** tiers 2026 reales Essential $149/mes [15K créditos], Growth $270/mes [40K], Scale $549/mes [100K], PAYG $0.012/crédito — la cifra "$40–$199/mes" de este doc está desactualizada).

**PredictLeads:** company intelligence estructurada: news events (37 categorías: funding, launches, partnerships…, 20M fuentes, re-crawl cada 8 min), job openings (2.7M empresas, refresh 36h), technographics (54k tecnologías, detectadas vía script tags/DNS/job posts), key customers (logos extraídos de case studies con reconocimiento de imagen), similar companies (18.5M), firmographics (120M). Todo point-in-time, con URL fuente, QA humano diario, entregado vía API/webhooks/flat files/**MCP**.

**Warmly:** desanonimiza visitantes web a nivel persona, los enriquece, y los engancha con agentes (chat IA, popups, retargeting email+ads). Modelo de señales en 3 niveles: 1st party (web, producto, CRM), 2nd party (actividad social, cambios de rol), 3rd party (research intent). Un **Context Graph** unifica cada visita/email/meeting por cuenta para que los agentes actúen con contexto completo, y dos agentes (Inbound/TAM) con ML intent scoring y mapeo de buying committee.

**Cómo funcionan por dentro (inferido):** scraping/APIs → resolución de identidad (post → persona → empresa) → clasificación de eventos con ML → almacenamiento point-in-time con provenance → motor de reglas/scoring por ventana temporal → webhooks/workflows.

**Lección para Qualify (esta capa es el corazón del producto):**
- **Señal = persona + evento + post fuente + timestamp.** El provenance es lo que hace accionable la señal (puedes responder "en contexto"). Tu tabla de señales debe guardar siempre `post_id`/`comment_id` fuente.
- **Engagement capture** es la mina de oro de Trigify: quién comenta/da like revela intent. En Qualify: los commenters de un creator/competidor son la audiencia mapeable → señales tipo "usuario preguntó dónde comprar", "usuario se queja del producto de la competencia", "creator mencionó tu marca sin ser partner".
- **Librería de señales tipadas** (no búsquedas ad-hoc): catálogo versionado de detectores (mención de marca, pico de views, creator cambió de nicho, competidor lanzó campaña con X creator, sentiment negativo en ventana de 48h…). Combinables en "ventanas de compra" (N señales en M días).
- **Point-in-time + provenance + QA** (PredictLeads) = la disciplina de datos que justifica cobrar por ellos.
- **Context Graph** (Warmly) = tu visión de CRM: cada interacción (post, comment, DM, campaña) unificada por creator/marca para que humanos y agentes actúen con contexto completo.

### Capa 4 — Orquestación: Clay

**Qué es:** la capa donde todo se junta. Spreadsheet-como-workflow-engine: cada fila = lead/cuenta, cada columna = paso de enriquecimiento/acción. Componentes: (1) **data marketplace** — 200+ proveedores bajo un solo contrato, con créditos unificados; (2) **waterfall enrichment** nativo; (3) **Claygents** — agentes IA que investigan la web por fila con un prompt; (4) **signals** (job changes, promociones, funding); (5) **sequencer** + push a herramientas de outreach/ads; (6) **AI formulas** (transformaciones en lenguaje natural); (7) API/CLI/**MCP** para que agentes construyan tablas. Valuación $5B, 500k+ equipos. Casos: Anthropic 3x enrichment rate; Intercom +140% pipeline outbound.

**Cómo funciona por dentro (inferido):** motor de ejecución por celda con DAG implícito (columna B depende de A), rate-limiting por proveedor, sistema de créditos como unidad de facturación transversal, y sandbox de agentes con browsing.

**Lección para Qualify:**
- Clay ganó por ser **la capa de orquestación agnóstica**, no por tener los mejores datos. Para el MVP de Qualify no necesitas un spreadsheet engine genérico: necesitas **plays empaquetados** (workflows fijos parametrizables: "monitorea competidor → detecta creators que le funcionan → enriquece contacto → draft de outreach").
- El **sistema de créditos** como unidad de negocio: cada scrape/enrichment/señal consume créditos → pricing simple y márgenes controlables. Diseñar la contabilidad de créditos desde el principio (tabla `usage_events` junto a `pipeline_jobs`).
- **Exponer todo por API + MCP desde el día 1** — los 4 líderes del stack (Clay, Trigify, PredictLeads, Warmly) convergieron en MCP en 2026. Qualify debe nacer agent-ready: FastAPI ya definida → añadir servidor MCP delgado sobre los mismos endpoints.

### Capa 5 — Ejecución multicanal: Instantly y HeyReach

**Instantly:** cold email a escala → evolucionó a "sales engagement + lead intelligence": campañas con rotación de mailboxes ilimitados, warmup, verificación, base de leads B2B propia, CRM ligero, website visitor tracking, inbox placement testing, y agentes IA (sales agent, reply agent, copilot que construye campañas end-to-end). Analytics orientado a revenue (auto-pausa campañas malas).

**HeyReach:** lo mismo para LinkedIn: **rotación de N cuentas** LinkedIn bajo un costo fijo (patrón "unlimited senders"), secuencias con lógica condicional (if connected), unified inbox multi-cuenta, sentiment/auto-tagging de respuestas, sync nativo a HubSpot/CRMs, multicanal vía integración con Instantly, API/webhooks/MCP/CLI.

**Cómo funcionan por dentro (inferido):** pool de cuentas (mailboxes/perfiles LinkedIn) + scheduler con límites por cuenta que imitan comportamiento humano + rotación para superar límites por identidad + inbox unificado vía polling/IMAP/API no oficial + clasificador de replies (interested/not/ooo) que alimenta el CRM.

**Lección para Qualify:**
- El patrón exportable: **rotación de identidades con límites por cuenta + inbox unificado + clasificación de replies**. En social: gestionar respuestas a comentarios/DMs de marca desde varias cuentas, con límites anti-ban por plataforma.
- **No construir email/LinkedIn outreach** — integrarse: Qualify genera la lista calificada y el mensaje (smart reply con RAG sobre el contenido del creator) y la empuja a Instantly/HeyReach vía sus APIs, igual que hace Trigify. Qualify se posiciona *upstream* de ellos.
- Copiar el **unified inbox** para lo social-nativo (comentarios/DMs de TikTok/IG) en fase tardía.

### Capa 6 — Infra de deliverability: Zapmail

**Qué es:** infraestructura de mailboxes al por mayor: Google/Microsoft Business Starter a ~$2.5–3.5/mailbox, aprovisionamiento automatizado (10 min), DNS automático (SPF/DKIM/DMARC/tracking domain), 1 dominio por workspace (aislamiento de reputación), mailboxes pre-calentados, dominios aged, tests de inbox placement, export a 50+ herramientas de outreach, API headless "para SaaS y AI SDRs".

**Lección para Qualify:**
- No es capa a replicar. Relevante solo si Qualify ofrece outreach por email gestionado (fase muy tardía) — y entonces se consume su API headless.
- Patrón interesante: **aislamiento de reputación por workspace** ≈ tu aislamiento por marca/tenant: límites de scraping y cuentas de plataforma separados por cliente para que un tenant no queme al resto.

---

## 3. Patrones transversales (lo que TODOS hacen)

1. **Provenance obligatorio:** cada dato apunta a su fuente primaria (post, URL, página). Sin fuente no hay confianza ni acción en contexto.
2. **Waterfall + verificación + cobro por dato válido:** agregación de fuentes ordenada por probabilidad de éxito, verificación multicapa, solo se cobra lo válido.
3. **Sistema de créditos** como unidad de pricing transversal a features.
4. **Señales tipadas y componibles** (librería creciente) en vez de búsquedas ad-hoc; combinación en ventanas temporales para detectar "buying windows".
5. **Workflows disparados por señal** con agentes IA en el medio (razonar → enriquecer → redactar → push).
6. **API + webhooks + MCP + CLI**: el producto ES la capa de datos; la UI es opcional. Todos se venden como "capa para agentes".
7. **Co-pilot de configuración** (Jarvis de Trigify, Copilot de Instantly): lenguaje natural → configuración de monitores/campañas.
8. **Integración con el resto del stack** en vez de competir: Trigify empuja a Instantly; HeyReach integra Instantly; BetterContact vive dentro de Clay. El stack es un ecosistema de APIs.
9. **Point-in-time data + QA:** historial inmutable con timestamps (ya lo tienes con ReplacingMergeTree + partitions).
10. **Anti-ban como ventaja competitiva:** rotación (proxies, fingerprints, cuentas, mailboxes) con límites que imitan humanos.

---

## 4. Qué significa esto para la arquitectura de Qualify

Tu pipeline de Fase 1 (Zyte → Celery → ClickHouse/R2) ya es la capa 0-1. Lo que el análisis añade al diseño:

### 4.1 Nuevas tablas (ClickHouse)

```sql
-- Catálogo de señales detectadas (corazón del social listening accionable)
CREATE TABLE signals.events (
    brand_id UUID,
    signal_type LowCardinality(String),   -- brand_mention|competitor_mention|purchase_intent|complaint|creator_growth_spike|creator_niche_change|...
    platform LowCardinality(String),
    -- Provenance (patrón Trigify: señal = persona + evento + fuente)
    source_type LowCardinality(String),   -- post|comment|transcript|frame
    post_id String,
    source_id String,                     -- comment_id / frame_index / ''
    -- Persona resuelta
    actor_handle String,                  -- quién generó la señal (commenter o creator)
    actor_type LowCardinality(String),    -- creator|audience
    -- Scoring
    confidence Float32,
    intent_score Float32 DEFAULT 0,
    detector_version LowCardinality(String),
    detected_at DateTime,
    posted_at DateTime,
    posted_date Date DEFAULT toDate(posted_at)
) ENGINE = ReplacingMergeTree(detected_at)
PARTITION BY toYYYYMM(posted_date)
ORDER BY (brand_id, signal_type, posted_date, post_id, source_id);

-- Perfil agregado de creators (capa descubrimiento/lookalike)
CREATE TABLE crm.creators (
    creator_id String,
    platform LowCardinality(String),
    handle LowCardinality(String),
    -- Métricas agregadas (materializadas desde posts)
    followers UInt64, avg_views UInt64, avg_engagement Float32,
    niche_labels Array(LowCardinality(String)),
    content_embedding Array(Float32),     -- centroide de embeddings de su contenido → lookalike search
    -- Enriquecimiento de contacto (patrón waterfall)
    email String DEFAULT '', email_source LowCardinality(String) DEFAULT '',
    email_verified UInt8 DEFAULT 0,
    links Array(String),                  -- link-in-bio expandidos
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (platform, creator_id);

-- Contabilidad de créditos (patrón Clay/Trigify)
CREATE TABLE billing.usage_events (
    tenant_id UUID, brand_id UUID,
    action LowCardinality(String),        -- scrape|enrich_gpu|enrich_contact|signal_detect|export
    credits UInt32, ref_id String,
    created_at DateTime
) ENGINE = MergeTree()
ORDER BY (tenant_id, created_at);
```

### 4.2 Nuevos servicios

| Servicio | Patrón copiado de | Responsabilidad |
|---|---|---|
| `signal-worker` | Trigify | Corre detectores tipados sobre content_index/comments nuevos → `signals.events` → webhooks |
| `enrichment-contact-worker` | BetterContact | Waterfall de contacto de creator (bio → link-in-bio → website → API externa), verificación, cache |
| `creator-aggregator` | DiscoLike/AI-Ark | Materializa `crm.creators` (métricas + centroide de embeddings) para lookalike/semantic search |
| `workflow-engine` (fase tardía) | Clay/Trigify | Plays: trigger (señal) → enrich → agente (draft) → push (Instantly/HeyReach/Slack/webhook) |
| `mcp-server` | todos | Mismos endpoints de la API expuestos como tools MCP |

### 4.3 Integraciones (buy, no build)

- **Outreach:** Instantly API (email), HeyReach API (LinkedIn) — Qualify empuja leads calificados + drafts.
- **Contacto B2B:** Prospeo/BetterContact API como último escalón del waterfall.
- **Company intel** (si Qualify entra a B2B): PredictLeads API en vez de construir news/jobs crawling.
- **Deliverability:** Zapmail headless API solo si algún día se ofrece envío gestionado.

---

## 5. Roadmap actualizado: características priorizadas por fases

> Las fases 1-2 no cambian (son la base de datos). Lo aprendido re-prioriza fases 3-6.

### Fase 1 — Ingesta y enriquecimiento (actual, sin cambios)
Scraping TikTok/IG + frames + CLIP + vision + whisper + comments + FTS. *Es tu equivalente del crawl de DiscoLike: la fuente primaria propietaria.*

### Fase 2 — Social Listening consultable
- FTS + sentiment + dashboards (ya planeado)
- **Nuevo (patrón Zyte):** escalado de scraping por tiers de costo; scrape solo posts nuevos/stale
- **Nuevo (patrón PredictLeads):** todo dato con provenance URL + point-in-time; API pública desde el inicio

### Fase 3 — Capa de señales ⬅ *prioridad subida (antes "alertas")*
- Librería de detectores tipados v1: mención de marca, mención de competidor, intent de compra en comentarios, queja/crisis, pico de engagement, creator nuevo en nicho
- `signals.events` con provenance + confidence + `detector_version`
- Alertas → Slack/email/webhook al detectar señal (el workflow mínimo viable de Trigify)
- Engagement capture: mapear commenters recurrentes de competidores como audiencia accionable

### Fase 4 — Descubrimiento de creators + enriquecimiento de contacto
- `crm.creators` con centroide de embeddings → **creator lookalike search** ("similares a estos 5 handles") y búsqueda en lenguaje natural — el diferenciador DiscoLike aplicado a creators
- Waterfall de contacto con verificación (patrón BetterContact) + integración Prospeo/BetterContact como fallback
- Scoring de creators (afinidad de marca, engagement real vs inflado, sentiment de su audiencia)

### Fase 5 — Workflows y activación
- Plays empaquetados: señal → enrich → draft con agente (RAG sobre contenido del creator) → push a **Instantly / HeyReach / Slack / CRM** vía API
- Sistema de créditos (`billing.usage_events`) y multi-tenant con aislamiento de límites por cliente (patrón Zapmail)
- **Servidor MCP** sobre la API (mesa de entrada para agentes — todos los líderes lo tienen)

### Fase 6 — Plataforma
- Co-pilot de configuración en lenguaje natural (patrón Jarvis/Copilot): "monitorea mi marca y avísame si un creator con >100k se queja" → configura monitores + workflows
- Unified inbox social (comentarios/DMs multi-cuenta) con clasificación de replies (patrón HeyReach)
- Context graph por marca: timeline unificado de cada creator/audiencia (patrón Warmly)
- Backtest/replay de detectores sobre señales históricas (patrón Trigify) — gratis gracias a point-in-time en ClickHouse

### Anti-roadmap (no construir)
Envío de email/LinkedIn propio, infra de mailboxes, base de contactos B2B, news/jobs crawling B2B, spreadsheet engine genérico tipo Clay.

---

## 6. Resumen ejecutivo

| Capa | Referente | Qualify: build o buy | Fase |
|---|---|---|---|
| Acceso web | Zyte | **Buy** (ya decidido) | 1 |
| Ingesta social propietaria | — (ventaja única) | **Build** | 1-2 |
| Señales con provenance | Trigify | **Build** (corazón del producto) | 3 |
| Descubrimiento lookalike | DiscoLike/AI-Ark | **Build** (sobre embeddings propios) | 4 |
| Enriquecimiento contacto | BetterContact/Prospeo | **Build waterfall, buy proveedores** | 4 |
| Company intel B2B | PredictLeads | **Buy** (si se necesita) | 5+ |
| Workflows/orquestación | Clay | **Build acotado** (plays, no spreadsheet) | 5 |
| Ejecución outbound | Instantly/HeyReach | **Buy/integrar** | 5 |
| Deliverability | Zapmail | **Buy** (solo si aplica) | 6+ |
| Inbox + context graph | HeyReach/Warmly | **Build** | 6 |

**Tesis de producto refinada (corregida — ver `research-features-gtm.md`, 2026-07-18):** Qualify = *Trigify + DiscoLike para la economía de creators*: la **capa de señales** sobre contenido audiovisual de TikTok/IG sigue siendo terreno que nadie cubre (confirmado por el teardown), pero el **descubrimiento/lookalike** ya no lo es — Modash, Kuli y Syncly Social hacen lookalike sobre contenido. El diferenciador real es la combinación: señales tipadas con provenance + fusión listening→activation en una sola plataforma (los tres competidores de discovery son solo discovery) + eje de comentarios/audiencia como similitud (ninguno lo usa), agent-ready (API/MCP), integrado downstream con el stack de ejecución existente (Instantly, HeyReach, CRMs) en vez de competir con él. Multimodal completo y español-first quedan como refuerzos secundarios, no como el pilar del moat.
