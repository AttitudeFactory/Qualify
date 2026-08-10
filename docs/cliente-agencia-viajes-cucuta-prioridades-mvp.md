# Cliente nuevo: agencia de viajes (Cúcuta) — prioridades del MVP de Qualify contra su brief

**Fecha:** 2026-08-08 · **Fuente:** brief confidencial del fundador (agencia de viajes en lanzamiento, Cúcuta; ex-LATAM, IATA/Sabre/NDC; destino insignia Santa Marta/Caribe; público binacional Cúcuta–Táchira).
**Pregunta que responde:** ¿qué partes del MVP de Qualify sirven los requerimientos de este cliente, en qué orden, y qué se compra en vez de construirse?

> **Marco de negocio.** Este cliente es el tercero del modelo «agencia gestionada apalancada en la herramienta» (`docs/oferta-mercado-agencia-gestionada.md`): el fundador presta el servicio de marketing y Qualify es el apalancamiento interno, no un SaaS que el cliente compra. El fee de referencia del brief (COP 2,5–4,5 M/mes ≈ US$625–1.125) cae dentro del rango agencia LATAM verificado (US$500–1.500) — el brief **confirma** la economía de ese doc, no la contradice.

> **Confidencialidad.** El brief exige NDA y protege tarifas netas/consolidadores/márgenes. Este doc referencia requerimientos, no los reproduce completos, y no contiene ningún dato de tarifas del cliente.

## 1. Qué cambió anoche y por qué reordena esta priorización

La sesión nocturna del 2026-08-07 (`.claude/sprint-state-2026-08-07-c04-page-access-resolved.md`) dejó en `main`:

- **La cadena de publishing Meta completa (A0–A7)** — token de Página en custodia, staging, repositorio write-ahead, servicio con polling y prohibición de segundo publish, rutas HTTP. **Primer reel real publicado por Qualify** (`@qualifymkt.co`, Development Mode). Solo falta C3 (deps `boto3`/`uvicorn` + ritual del venv) y credenciales R2.
- **KC-1 resuelto (`9df0e22`): Development Mode NO da visibilidad pública.** ~~El reel publicado solo lo ven usuarios con rol en la app.~~ **FALSIFICADO 2026-08-08 por medición:** el reel ES públicamente visible sin sesión — ver la corrección en P0 más abajo.

La consecuencia estratégica: ~~el código de publishing ya no es el bloqueante — el acceso a producción de Meta sí~~ **(reescrito 2026-08-08 tras la medición del fundador: tampoco el acceso lo es).** El reel publicado en Development Mode resultó **públicamente visible sin sesión** — KC-1 estaba mal, y para activos que el fundador administra **no hay ni código ni trámite bloqueando la publicación pública desde el mes 1**. Lo que queda entre hoy y la operación real es configuración (credenciales R2, `config_id`, seed del tenant), no ingeniería ni App Review. La tensión Zernio pierde su urgencia: ver la corrección en P0.

## 2. Mapeo del brief → Qualify

| Requerimiento del brief | ¿Qualify? | Estado real en el repo | Bucket |
|---|---|---|---|
| 3.1 Branding, identidad, plantillas | No | — | Servicio de agencia, fuera de Qualify |
| 3.2 Web, SEO local, GBP, píxel/GA4/GTM | No | — | Comprar/operar con herramientas estándar |
| 3.3 Calendario de contenidos (12–16 posts + 8–12 reels/mes) | **Sí — ideas por hooks de competencia** | Spike de hooks (Fases A/B entregadas) + harvester TikTok a $0 (`packages/scraper/research/`) | **Qualify HOY** |
| 3.3 Community management ≤2 h (comentarios/DMs IG-FB) | **Sí — inbox Parte 4-B + respuestas asistidas** | Esquema `0004` (`threads`/`messages`) aplicado; capa de servicio sin construir | **Pull-forward** |
| 3.3 Publicación/scheduling IG | **Sí — Parte 4-A** | Cadena A0–A7 en `main`, publish en vivo demostrado; **público bloqueado por App Mode** | **Pull-forward, gated** |
| 3.3 Scheduling TikTok | **No por API** | ADR 21: cliente API no auditado fuerza cuenta privada — sin mitigación | Manual / agregador auditado |
| 3.4 Meta Ads / Google Ads (pauta, CPL/ROAS) | No en el MVP | Marketing API = ítem de investigación diferido (ADR 21) | Ads Manager directo |
| 3.5 WhatsApp Business + CRM sencillo | No en el MVP | WhatsApp no es canal de Qualify; el propio brief propone HubSpot free/Kommo | Comprar (el brief ya lo dice) |
| 3.6 Reportería mensual | Parcial | La parte social orgánica (comunidad, respuesta, contenido) la dará Qualify; la de pauta sale de Ads Manager | Mixto |
| §2 Listening de marca/competencia Cúcuta–Táchira | **Sí — el corazón del producto** | Fase 1 Parte 3 no arrancada (sin Celery/esquemas analíticos/R2) | Roadmap real |

## 3. Prioridades

### P0 — Decisión de acceso a producción Meta (semana 0, decisión del fundador — no código)

> **DECIDIDO por el fundador, 2026-08-08: BUILD.** Hecho nuevo que sustenta la decisión: el fundador **crea y gestiona las redes de este cliente con ownership completo** — el cliente cae en el lado barato de la frontera de ADR 29 (activos que el fundador administra), igual que el inmobiliario. Todo Parte 4-A/4-B es construible y testeable bajo Standard Access. **Corrección 2026-08-08 (medición del fundador): KC-1 estaba mal.** El reel publicado en Development Mode (`Dbump-jElJz`) es **públicamente visible sin sesión** — verificado en incógnito por el fundador y por fetch anónimo del embed. **No hace falta App Review para visibilidad pública en activos que el fundador administra**; el build sirve al cliente desde el mes 1 sin trámite. El reloj de App Review queda circunscrito al primer cliente cuyos activos el fundador no administre («cliente dos» de ADR 29), y la opción agregador pierde su driver de reloj — solo se reevaluaría por TikTok scheduling. Evidencia completa: `docs/integracion-cuentas-conectadas-meta.md` §3.1, bloque 2026-08-08.

Dos caminos mutuamente informados, ninguno se resuelve escribiendo más código:

1. **App Review + Business Verification** para llevar la app a Live. La enmienda a ADR 21 ya decía «el reloj administrativo arranca en semana 0»; este cliente lo arranca de verdad. El review es **por permiso** (ADR 29): se puede someter solo `instagram_content_publish` + los de páginas sin arrastrar messaging.
2. **Comprar el agregador** (tensión Zernio, founder-gated): US$1–6/cuenta/mes bajo una app ya revisada por Meta *y* auditada por TikTok — resolvería publishing público + TikTok scheduling + fan-out de DMs de un golpe, desplazando `connections/` y `publishing/` (Sprint 1 + Sprint 3-A).

Lo que el run nocturno aporta a esta decisión: el costo de «build» ya está pagado en gran parte (la cadena funciona), pero **lo pagado no compra visibilidad pública** — el sunk cost no debe decidir. Con 3 clientes reales y TikTok en el brief, la opción agregador merece evaluarse con números antes de someter el App Review. **Recomendación: sesión corta con el arquitecto para cerrar la tensión abierta del 2026-07-30 antes de escribir una línea más de Parte 4-A.**

### P1 — Hook intelligence vertical viajes (sirve YA, costo ~$0)

Reusar tal cual el camino que ya existe para inmobiliario:

- **Corpus:** lista de cuentas candidatas (agencias de viajes competidoras en Cúcuta/Norte de Santander + creadores de destino Santa Marta/Caribe + agencias venezolanas de frontera), gemelo de `docs/corpus-candidatos-inmobiliario-tachira-cucuta.md`. Tarea natural del `gtm-specialist`.
- **Harvest:** `packages/scraper/research/harvest.py` (yt-dlp, $0, TikTok probado; respetar el rate-limit 429 documentado).
- **Análisis:** CLI de `qualify_models.hooks` → hooks hablado/mostrado/texto-en-pantalla de los primeros 3 s, con views como outcome.

Salida directa al requerimiento 3.3: banco mensual de ideas de ganchos con evidencia («qué está funcionando en video de Santa Marta») para los 8–12 reels/mes, asignables a CM o influencers — exactamente el módulo de calendario+hooks que el demo inversor mostró como visión. Bonus: la Fase D del spike (diseñada, sin datos) consigue su segundo vertical de datos reales.

### P2 — Tercer tenant + conexiones (operativo, Sprint 1 ya lo cubre)

Alta del tenant de la agencia de viajes vía seed/`admin_session`, y cuando existan las cuentas IG/FB del cliente, conectar por el connect flow C-04 (scope-set de 5 con `business_management`, ya verificado en vivo). La multi-tenancy es fundación desde ADR 24; esto es ejecución, no construcción. Nota ADR 29: durante la fase de construcción el fundador tendrá control total del Business del cliente (lo crea desde cero), así que todo es testeable bajo Standard Access; la frontera llega cuando los activos queden a nombre del cliente (requisito 4.1 del brief).

### P3 — Inbox Parte 4-B + respuestas asistidas (IG/FB)

Sirve el KPI más duro del brief (respuesta ≤2 h → ≤1 h). El esquema (`0004`: `threads`/`messages`) existe; falta la capa de servicio + el fan-out de mensajes (cuya vía — Graph API propia vs agregador — depende de P0). Respuestas **asistidas** (borrador + aprobación humana), nunca autónomas — ADR 21. WhatsApp queda explícitamente fuera: lo cubre WhatsApp Business + el CRM comprado que el propio brief sugiere.

### P4 — Cerrar Parte 4-A (publishing propio)

Si P0 decide «build»: ejecutar C3 (con el ritual del venv y nadie más trabajando), credenciales R2, y el paso manual de `config_id` del dashboard — con eso la demo §1.1 corre completa. TikTok siempre manual (ADR 21). Si P0 decide «buy», congelar aquí.

### P5 — Listening real (Fase 1 Parte 3) — el fondo del embudo

Monitoreo de marca/competencia y sentimiento para la reportería mensual y el posicionamiento binacional. Sigue siendo el camino largo (Celery, esquemas `ingestion`/`search`/`signals`, R2) y **no** lo necesita el mes 1 de este cliente; lo necesita el mes 3–6 (fase de optimización del brief). No adelantarlo por este brief: P1 da el 80 % del valor de «inteligencia de contenido» a 1 % del costo.

## 4. Qué se compra (y el brief está de acuerdo)

| Necesidad | Herramienta | Nota |
|---|---|---|
| CRM de leads + embudo WhatsApp | HubSpot free / Kommo | El brief lo propone él mismo (3.5) |
| WhatsApp Business (catálogo, etiquetas, respuestas rápidas) | WhatsApp Business app | API/chatbots = deseable, no obligatorio |
| Pauta Meta + Google | Ads Manager / Google Ads directo | Pagada desde cuenta del cliente (4.1); ads en Qualify = diferido |
| Píxel, GTM, GA4, Search Console | Estándar | Día uno |
| Web/landing | Fuera de Qualify | Con botón WhatsApp + formulario |

## 5. KPIs del brief: qué medirá Qualify y qué no

- **Cubre Qualify (cuando P1–P4 aterricen):** volumen/cadencia de contenido publicado, performance de posts propios IG, tiempo de respuesta en IG/FB, crecimiento de comunidad, banco de hooks con provenance (`hook_pattern@vX`).
- **No cubre el MVP (medir en la fuente):** leads, CPL, CAC, ROAS (Ads Manager + CRM comprado), y todo lo de WhatsApp.
- **Cumplimiento normativo del contenido** (RNT visible, leyenda ESCNNA, precios con condiciones — §9 del brief): son reglas del *servicio* hoy; candidato natural a validación de plantilla en el compositor de publicaciones si Parte 4-A sigue viva, no un requisito del MVP.

## 6. Próximos pasos concretos

1. **Fundador:** decidir P0 (App Review vs agregador) — todo lo demás de publishing/inbox cuelga de ahí.
2. **gtm-specialist:** doc de cuentas candidatas del vertical viajes (gemelo del inmobiliario).
3. **Operación:** confirmar cuentas → harvest → primer informe de hooks del vertical (entregable vendible en la propuesta de 90 días del brief).
4. **Seed:** tercer tenant al existir el naming del cliente (3.1 está en curso — el naming aún no existe).
5. **Higiene pendiente que este cliente vuelve urgente:** C3 + rebuild del venv (`rm -rf .venv && uv sync --group ml`, sin agentes activos) y decidir qué hacer con la conexión de prueba viva bajo PuntoServis.
