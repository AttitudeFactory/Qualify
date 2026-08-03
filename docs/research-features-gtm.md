# Teardown de features GTM (Fases 4-5): lookalike, enriquecimiento y outreach

**Fecha:** 2026-07-18
**Método:** Investigación de escritorio sobre fuentes primarias (pricing pages, docs, help centers) y secundarias (G2, Reddit, reviews independientes), acceso 2026-07-18. Los precios de entrada son públicos y varían por volumen/negociación; no validados con proveedores.
**Objetivo:** Validar o corregir `docs/ingenieria-inversa-stack-gtm.md` con datos reales de cómo los vendors referentes implementan las tres features diferenciadoras de Qualify (lookalike discovery, waterfall enrichment, outreach) — qué cobran de verdad, qué límites tienen y de qué se queja la gente.

> **Convención de motions:** distinguimos las dos motions que Qualify fusiona: **listening** (entender la conversación, equipos de marca/marketing) y **activation** (actuar sobre ella, equipos de growth/sales). Cada hallazgo se etiqueta con la motion que sirve.

> ⚠ **ANOTACIÓN DE ALCANCE GEOGRÁFICO (añadida 2026-07-30 por `gtm`, sin re-investigar).** Los vendors auditados abajo (Clay, Instantly, HeyReach, Smartlead, Zapmail, Prospeo, BetterContact, Trigify, PredictLeads, Warmly…) son **productos angloparlantes con precio en USD y bases de contactos B2B centradas en EE. UU./UE**. Tres consecuencias que **no** se verificaron en esa pasada y que hay que asumir abiertas:
> - **Cobertura de datos en LATAM no verificada.** Las bases B2B y los waterfalls de enriquecimiento tienen cobertura muy desigual fuera de EE. UU./UE; **ningún hit-rate LATAM está medido en este documento**. Un waterfall con 70 % de acierto en EE. UU. puede rendir mucho menos en Colombia o Uruguay, y aquí no se comprobó.
> - **Los precios en USD chocan con techos de gasto locales.** El trabajo de 2026-07-30 midió el techo de software de una PYME inmobiliaria LATAM en **US$50-185/mes para toda la empresa** (`docs/oferta-mercado-inmobiliario.md` §2.4) — **por debajo de una sola licencia** de varias herramientas de este doc. Los precios de abajo son correctos; lo que no está establecido es que sean pagables por un comprador LATAM.
> - **Outreach por email frío tiene supuestos legales por jurisdicción** (CAN-SPAM en EE. UU., GDPR en UE) y **Uruguay tiene protección de datos de grado GDPR** — Ley 18.331, adecuación UE reaffirmada 2024-01-15 `[S]`, hallazgo de `market-opportunity-analyst`. **La viabilidad legal del outreach frío en LATAM no se analizó aquí.**
>
> **No es una re-investigación**: es una anotación de alcance. Las cifras de vendor siguen siendo válidas **para su mercado de origen**.

---

## Hallazgo central (leer esto primero)

El teardown desmiente una premisa clave de `ingenieria-inversa-stack-gtm.md` §2 (Capa 1): la afirmación *"nadie ofrece [lookalike] para TikTok/IG con contenido real (los influencer tools usan solo bio + métricas)"* **ya no es cierta en 2026**. Modash lanzó una **Creator Lookalikes API** que explícitamente analiza *"visual themes, topics, and creative style"* con prompts en lenguaje natural y matching cross-platform; y Kuli hace análisis de video **frame-by-frame** como propuesta de valor central. El diferenciador de Qualify sigue existiendo, pero es **más estrecho de lo que dicen los docs** — ver la lista de contradicciones al final.

---

## Área 1 — Lookalike / discovery de creators (motion: listening → activation)

### Tabla comparativa

| Vendor | ¿Cómo hace el lookalike? | Señal usada | Precio | Límites / quejas reales |
|---|---|---|---|---|
| **Modash** | *Creator Lookalikes API*: analiza contexto de contenido (temas visuales, tópicos, estilo creativo) + prompts en lenguaje natural; cross-platform (IG→TikTok, etc.) | **Contenido** (no demografía por defecto; filtros demográficos se aplican encima) | API lookalike desde **$16,200/año** (3,000 créditos/mes; 0.025 créditos/resultado, hasta 50/request). Plataforma base $199–$499/mes anual | Pool 350M+ creators >1K followers. Quejas: techos por tier ("per-tier ceilings"); datos "no verificados por el creator" en algunas plataformas |
| **Kuli** | Análisis de video **frame-by-frame** (estilo visual, autenticidad del mensaje, brand safety, factores de viralidad); lookalike por estética, overlap de audiencia y cadencia de contenido | **Contenido multimodal** (lo más cercano a Qualify) | Custom (no público) | Competidor directo de la tesis de Qualify — vigilar de cerca |
| **Upfluence** | *Jaice AI*: lookalike "en un clic" desde tus top performers; matching por audiencia/nicho/objetivos | **Metadata** (follower count, engagement, demografía) — "primarily relies on metadata-based filtering rather than deep content analysis" | Modular desde **$478/mes** (módulo Search & Contact); AWS Marketplace $11,940–$42,600/año. No publica precios, mínimo 12 meses | Quejas fuertes: contrato real de 12 meses vendido como "6 meses/mensual" sin salida anticipada; análisis de fake followers limitado |

### Notas por vendor

**Modash** — [Creator Lookalikes API](https://www.modash.io/influencer-marketing-api/creator-lookalikes) (fuente primaria del pricing, verificada 2026-07-18) · [G2](https://www.g2.com/products/modash/reviews) (acceso 2026-07-18). Es la refutación más directa a nuestro "nadie lo hace con contenido real": el matching es explícitamente por contenido visual, no por bio. La cifra **$16,200/año** (3,000 créditos/mes, 0.025 créditos/resultado, hasta 50 resultados/request) está confirmada en la propia página de Modash. Sin embargo (a) no cubre audio/transcript ni comentarios, solo el eje visual + tópicos; (b) el precio de servir esto es alto, lo que valida que la discovery basada en contenido es cara de operar — dato útil para el modelo de créditos de Qualify (Fase 5); (c) sigue siendo un tool de *solo discovery*, sin la fusión listening+activation.

**Kuli** — [AI vs traditional platforms](https://kuli.one/blog/ai-vs-traditional-influencer-marketing-platforms-2026/) · [Creator Content Profile](https://kuli.one/blog/creator-content-profile/) (acceso 2026-07-18). El "Creator Content Profile" (análisis IA del video: estilo visual, patrones de comunicación, expertise, marcadores de autenticidad, brand safety) es casi idéntico a lo que Qualify quiere generar desde su pipeline multimodal. Es el competidor más peligroso de la tesis de producto.

**Upfluence** — [pricing](https://www.upfluence.com/pricing) · [review](https://www.creator-hero.com/blog/upfluence-pricing-and-review) (acceso 2026-07-18). Confirma la mitad "vieja" del mercado: lookalike sobre metadata. Aquí Qualify sí gana por contenido. La queja del contrato de 12 meses oculto es un patrón de posicionamiento aprovechable (transparencia de pricing/compromiso).

**Implicación para Qualify:** el diferenciador de lookalike se redefine. Ya no es "nadie lo hace con contenido" sino: (1) **fusión listening+activation** en una plataforma (Modash/Kuli son solo discovery); (2) **contenido multimodal completo** — audio/transcript + comentarios + visual, no solo el eje visual/tópicos de Modash; (3) **español-first** (robertuito, transcripción ES); (4) señales accionables con provenance encima del lookalike. Esto es Fase 4 en el phase map.

---

### Profundidad del análisis de contenido y qué eje sigue vacío (input para la ADR de tesis)

Esta sección responde a la pregunta que decide cuánto del diferenciador sobrevive: dado que Modash y Kuli **ya leen contenido** (no solo bio), ¿en qué eje concreto nadie compite todavía?

**Modash** — [Creator Lookalikes API](https://www.modash.io/influencer-marketing-api/creator-lookalikes) · [influencer lookalike tool](https://www.modash.io/influencer-lookalike-tool) · [help: how to find lookalikes](https://help.modash.io/en/articles/5467269-how-to-find-lookalike-creators) (acceso 2026-07-18). Analiza **solo el eje visual + texto**: "analysis of bios, captions, and visuals" + temas/estilo creativo; el lookalike se basa en "content similarity (topics, captions, hashtags)". **No transcribe audio ni usa la sección de comentarios.** Confirmado por doble vía durable: (1) la propia doc/help de Modash (solo bios/captions/visuals, sin mención de audio o comentarios), y (2) el posicionamiento explícito de un competidor (Syncly Social) contra Modash — "finds creators by what's actually in their videos using Audio Intelligence to transcribe what creators say" — el mercado confirma que Modash no transcribe. Precio de servir esto (verificado en la propia página de Modash): **0.025 créditos/resultado, tier lookalike desde $16,200/año** (3,000 créditos/mes, hasta 50 resultados/request).

**Kuli** — [Kuli](https://kuli.one/) · [review](https://influencermarketinghub.com/kuli/) (acceso 2026-07-18). **SÍ transcribe audio.** Literal: "breaks down the hook, **audio**, pacing, caption" y "analyzes **spoken words / spoken language** across hundreds of videos", indexado para query posterior. O sea, **el eje audio/transcript ya NO es único.** Lo que Kuli no muestra evidencia de usar: la **señal de la sección de comentarios** (indexa visual/spoken/brand-mentions/narrative, nunca commenters/audiencia).

**Tercer competidor a vigilar: Syncly Social** — [Syncly Social](https://syncly.app/social) · [creator discovery pricing](https://syncly.app/social/solution/creator-discovery/pricing) · [Modash alternatives](https://syncly.app/blog/modash-alternatives) (acceso 2026-07-18). **El competidor más peligroso del lado listening.** Es un YC company, **TikTok-native**, con tres productos en una plataforma: Syncly Social (social listening de video), Syncly Creator (discovery de creators), Syncly VOC (voz del cliente). Discovery "content-first" con **Audio Intelligence (STT) + AI Vision (texto en pantalla)** que matchea por palabras habladas, mood visual y sentiment de audiencia — no hashtags/followers. **Cubre audio+visual y encima fusiona listening+discovery** (más que Modash/Kuli, que son solo discovery), así que erosiona parte del pilar #1 — PERO no muestra evidencia de cerrar el loop a **activation/outreach** (señales→enrich→envío) ni de usar la **señal de comentarios** como eje de similitud. Pricing: **freemium** (exploración gratis sin tarjeta) + tiers pagos opacos (500+ resultados/búsqueda, 1,000+ exports/mes, "plan a medida") — sin cifra en dólares pública. Hay ya ≥2 players (Kuli, Syncly) en el eje audio; Syncly es además el que más se acerca a la fusión.

**Idioma (español):** sin evidencia pública de que Modash/Kuli/Syncly manejen bien o mal el español (Kuli es SF+Paris; Modash global). **No puede afirmarse que su calidad "se degrada en español"** sin un test empírico (WER de transcripción ES, o probar sus lookalikes con creators hispanos) — pendiente en datasci. No apoyar el moat en "español-first" sin esa medición.

**Conclusión — el eje que sigue vacío.** El diferenciador NO es "leemos contenido" (Modash/Kuli ya lo hacen en el eje visual, y Kuli+Syncly en audio). Lo que sobrevive como defendible, en orden de fuerza:
1. **Fusión listening→activation:** Modash/Kuli/Syncly son *solo discovery*; ninguno cierra el loop a señales + outreach. El pilar más sólido.
2. **Señal de comentarios/audiencia en el lookalike:** los commenters como eje de similitud — nadie lo usa.
3. **Capa de señales tipadas con provenance** encima (Fase 3, confirmado vacío en social).
4. **Español-first** — plausible pero **sin probar**; refuerzo secundario, no pilar, hasta validación de datasci.

El titular honesto del moat es *"fusión listening→activation + eje comentarios/señales con provenance"*, con "full multimodal (audio+transcript)" y "español" como refuerzos, no como el diferenciador principal — porque el eje audio ya tiene competencia (Kuli, Syncly).

---

## Área 2 — Waterfall enrichment de contacto (motion: activation)

### Tabla comparativa

| Vendor | Lógica de cascada | Precio | Match rate (claim / real) | Límites / quejas reales |
|---|---|---|---|---|
| **Clay** | 150+ proveedores bajo un contrato; waterfall nativo + Claygents (agentes web por fila) | 2 planes (mar-2026): **Launch $185/mes** (10K créditos), **Growth $495/mes** (25K). Waterfall 3–10+ créditos/lookup; Claygent 15–30 créditos/fila | — | **Cobra por cada intento, incluido el fallido** (3 proveedores sin match = pagas 3). Caso: **$3,000 quemados el primer mes**. Mar-2026 subió mid-tier ~28% y recortó créditos ~40%. G2 4.7/5 pero quejas concentran en "credit burn" impredecible |
| **BetterContact** | 20+ proveedores; IA secuencia por geografía/industria; **solo cobra por dato válido** | **$15/mes** (200 créditos) → Pro $49/mes (1,000) → hasta 50K; Enterprise desde $799/mes | **87–95% email** (real, se sostiene); 70–85% phone | Phone = **10x créditos** (1 móvil = 10 créditos) → 1,000 créditos = solo 100 teléfonos. El modelo pay-per-hit es el punto genuinamente bueno |
| **Prospeo** | Proveedor individual (no waterfall); email+mobile finder + verificador; se usa *dentro* de waterfalls | Basic $39/mes (1,000) → Pro $99 (5,000) → Business $199 (20K) → Corporate $369 (50K). ~$0.007–0.02/crédito | **98% claim en lookup individual**; independiente: 68% (34/50 validados). **Bulk: 4.5% hit rate** (45/1,000) **y cobró los 1,000 créditos** | 300 requests concurrentes, sin cap diario. **Créditos no rotan; bulk cobra por cada fila importada** aunque no haya match |

### Notas por vendor

**Clay** — [pricing 2026](https://www.landbase.com/blog/clay-pricing) · [G2](https://www.g2.com/products/clay-com-clay/reviews) · [amplemarket breakdown](https://www.amplemarket.com/blog/how-much-does-clay-really-cost) (acceso 2026-07-18). Enriquecer 1,000 contactos (email+phone+company) quema 15,000–25,000 créditos. El cambio de pricing de mar-2026 mandó a muchos clientes a buscar alternativas. **Refuerza la decisión "build waterfall acotado, no alquilar Clay"** — pero es una advertencia doble: el modelo de créditos propio de Qualify (Fase 5) no debe reproducir la impredecibilidad que es la queja #1 de Clay.

**BetterContact** — [pricing](https://bettercontact.rocks/pricing/) · [review](https://maildoso.ai/blog/catalog/lead-data/bettercontact) (acceso 2026-07-18). El 87–95% de match en email valida el patrón waterfall del doc. Sirve como último escalón del waterfall de Qualify (integrar, no construir). Confirma también que **el valor del waterfall crece con listas heterogéneas** (EU+LATAM+APAC mixto: un solo source ~35%, waterfall ~65%) — relevante porque los creators de Qualify serán multi-región/multi-idioma.

**Prospeo** — [pricing](https://prospeo.io/pricing) · [review independiente](https://emailwarmup.com/blog/email-deliverability-tools/prospeo-review/) (acceso 2026-07-18). **Corrección importante:** `alternativas-fase1.md` lo cita como "~$0.01/email, 98% precisión". Eso es cierto **solo para lookup individual**; en **bulk el hit rate cae a ~4.5% y cobra por cada fila**. Sigue siendo válido como escalón del waterfall, pero la cifra de 98% no debe usarse para modelar costos de enriquecimiento masivo de creators.

**Implicación para Qualify:** el waterfall de contacto de creator (bio → link-in-bio → website → API externa) es Fase 4. Diseñar la contabilidad de créditos para **cobrar solo por dato válido** (patrón BetterContact) y no por intento (anti-patrón Clay). Prospeo/BetterContact como escalones finales vía API.

---

## Área 3 — Señales / intent (motion: listening→activation) y Outreach (motion: activation)

### 3a. Señales (Trigify, Warmly)

| Vendor | Qué señales detecta | Tiempo real | Precio 2026 | Límites / quejas reales |
|---|---|---|---|---|
| **Trigify** | 11+ plataformas sociales (LinkedIn, X, Reddit, YouTube, podcasts); profile monitors, Boolean search, engagement capture (quién dio like/comentó); 16+ tipos de señal ABM. Señal = persona + post fuente (provenance) | Sí (monitores continuos) | **Essential $149/mes** (15K créditos), **Growth $270** (40K), **Scale $549** (100K); PAYG $0.012/crédito. Todo por 1 sistema de créditos (señales+enrich+engagement+Jarvis) | Quejas: filtrar "USA" devolvió leads de Arabia/Japón/UK (**data quality geo**); **volumen de señales** (50 alertas/día, 5 accionables); UI confusa/compleja |
| **Warmly** | Desanonimización de visitantes web + señales 3 niveles (1st/2nd/3rd party); job changes, funding, hiring | Sí | **$10,000/año** (deanon, 10K créditos/mes) → Inbound Chat $20K → Autopilot $30K | **Match: ~65% company / solo 5–20% persona.** Sitios >10K visitas/mes empujan coste real +30–50%. Empresas con señal que no visitaron tu sitio son invisibles. Contactos enriquecidos que rebotan = spend desperdiciado |

**Trigify** — [pricing](https://www.trigify.io/pricing) · [review](https://syncgtm.com/blog/trigify-review) · [Kondo review](https://www.trykondo.com/blog/trigify-ai-lead-engagement) (acceso 2026-07-18). **Corrección de pricing:** `ingenieria-inversa-stack-gtm.md` §2 Capa 3 cita "$40–$199/mes" — los tiers 2026 son **$149/$270/$549** (o el par legacy Starter $40 / Max $199 que ya no refleja los planes principales por crédito). El resto del teardown del doc (señal = persona + provenance, engagement capture como mina de oro, Jarvis co-pilot, MCP) se confirma. La queja de **volumen de señales sin ruido** es una lección de diseño directa para la librería de detectores de Qualify (Fase 3): filtros disciplinados y scoring, no firehose.

**Warmly** — [pricing/review](https://syncgtm.com/blog/warmly-review) · [G2](https://www.g2.com/products/warmly-warmly/reviews) (acceso 2026-07-18). El match a nivel persona de solo 5–20% es un dato crudo: la desanonimización web es débil en el eje que más importa (persona, no empresa). Es un patrón B2B-web, **poco transferible al social de Qualify** — pero confirma que Trigify/Warmly operan sobre LinkedIn/web B2B y **nadie hace la capa de señales sobre TikTok/IG audiovisual** (esa parte del doc sí se sostiene).

### 3b. Outreach (Instantly, HeyReach, Smartlead)

| Vendor | Canal | Warmup / deliverability | Precio | Límites de envío | Quejas reales |
|---|---|---|---|---|---|
| **Instantly** | Email | Warmup ilimitado; red compartida | Outreach Growth ($37/mes aprox, 5K emails, mailboxes ilimitados); Hypergrowth $77.60 (75K emails). **3 módulos separados** (Outreach/Credits/CRM) | Por mailbox (rotación ilimitada de mailboxes) | **Deprecó API v1 el 2026-01-19**; sin aprobación Gmail API; warmup compartido baja open rates en ~2 semanas; sorpresas de pricing al crecer leads; spam pese a "warmed up" en Gmail nuevos |
| **Smartlead** | Email | Warmup ilimitado; ESP matching (Gmail↔Gmail); UltraPremium gated a Unlimited $174 | Basic **$39/mes** (mailboxes ilimitados, **sin API**); Pro **$94/mes** (API+webhooks); Master Inbox 3.0 (94% precisión categorización reply) | Por mailbox, rotación de cuentas | Complejidad de setup; soporte lento en planes bajos; "campaigns failing to send, warmup pausing, analytics not loading" — crece más rápido que su ingeniería |
| **HeyReach** | LinkedIn | Límites que imitan humano | Growth **~$79/seat/mes**; Agency **~$999/mes** (50 senders); Unlimited ~$1,999 | **200 acciones/día por cuenta**; connection requests seguros **20–25/día**; invites con nota **~10/mes** | Riesgo de ban de LinkedIn si se fuerzan límites; el modelo "unlimited senders" es realmente por seat/agency |

**Instantly** — [comparativa](https://bavlio.com/blog/instantly-vs-smartlead-2026) · [Reddit sentiment](https://www.yalc.ai/blog/smartlead-vs-instantly-reddit/) (acceso 2026-07-18). **Dato crítico para arquitectura:** deprecó API v1 el 2026-01-19 y se partió en 3 módulos con precio separado — cualquier integración planeada (Fase 5) debe apuntar a la API nueva. El warmup de red compartida es una queja recurrente (Google security guidelines 2026).

**Smartlead** — [pricing](https://coldemailkit.com/tools/smartlead) · [review](https://marketbetter.ai/blog/smartlead-review-2026/) (acceso 2026-07-18). **La API está en Pro ($94/mes), no en Base** — relevante para la decisión Fase 1 de usar Smartlead como backend de outreach (el white-label/API no es el tier de entrada). Quejas de estabilidad ("failing to send, warmup pausing").

**HeyReach** — [sending limits](https://help.heyreach.io/en/articles/9892903-how-to-configure-my-sending-limits) · [pricing](https://leadhaste.com/blog/heyreach-pricing-2026) (acceso 2026-07-18). Los límites LinkedIn (20–25 conexiones/día, ~10 invites-con-nota/mes) son el techo real de cualquier motion de outreach social — Qualify debe modelar estos caps si algún día gestiona respuestas multi-cuenta (patrón unified inbox, Fase 6).

**Implicación para Qualify:** confirma "buy, don't build" para outreach (deliverability es un problema resuelto y arriesgado). Pero **matiza la decisión Fase 1**: Smartlead API/white-label vive en Pro, no en el tier barato; Instantly rehízo su API en 2026; los límites LinkedIn son duros. Nada de esto rompe la decisión (Zapmail/Smartlead/Prospeo), solo ajusta expectativas de coste e integración.

---

## Contradicciones / actualizaciones para reconciliar

Para **architect** (`docs/ingenieria-inversa-stack-gtm.md`, `CLAUDE.md`, `README.md`):

1. **[Contradicción fuerte — tesis de producto]** `ingenieria-inversa-stack-gtm.md` §2 Capa 1 y §6 afirman que *"nadie ofrece [lookalike] para TikTok/IG con contenido real (los influencer tools usan solo bio + métricas)"* y que DiscoLike aplicado a creators es un espacio vacío. **Ya no es cierto:** Modash Creator Lookalikes analiza contenido visual/tópicos/estilo con NL prompts (API pública, $16.2K/año) y Kuli hace análisis frame-by-frame de video como core. Recomiendo reescribir el diferenciador como: fusión listening+activation + multimodal **completo** (audio/transcript+comentarios, no solo visual) + español-first + señales con provenance — no "nadie lo hace con contenido".

2. **[Pricing desactualizado — Trigify]** §2 Capa 3 cita Trigify "$40–$199/mes". Tiers 2026 reales: Essential $149 / Growth $270 / Scale $549, sistema de créditos, PAYG $0.012/crédito.

3. **[Corrección de dato — Prospeo]** `alternativas-fase1.md` §3b y `CLAUDE.md`/`README.md` citan Prospeo "~$0.01/email, 98% precisión". El 98% es **solo lookup individual**; en bulk el hit rate cae a ~4.5% y cobra por cada fila importada. No cambiar la decisión (sigue válido como escalón de waterfall), pero no usar 98% para modelar coste de enriquecimiento masivo.

4. **[Ajuste de decisión Fase 1 — Smartlead]** `alternativas-fase1.md` propone Smartlead white-label/API como backend de outreach. La **API está en Pro ($94/mes), no en Base ($39)** — el tier barato no la incluye. Ajustar el modelo de coste, la decisión se sostiene.

5. **[Riesgo de integración — Instantly]** Instantly **deprecó API v1 el 2026-01-19** y se partió en 3 módulos de precio separado. Cualquier integración Fase 5 debe apuntar a la API nueva; documentarlo en la ADR de outreach.

6. **[Lección de diseño — modelo de créditos]** Clay (mar-2026: +28% precio, −40% créditos, cobra por intento fallido) y su queja #1 de "credit burn impredecible" son una advertencia directa para el `billing.usage_events` de Qualify (Fase 5): cobrar por **dato válido** (patrón BetterContact), no por intento, y hacer el consumo predecible/visible antes del commit.

7. **[Se confirma]** La afirmación de que Trigify/Warmly operan sobre LinkedIn/web B2B y **nadie hace la capa de señales sobre TikTok/IG audiovisual** sigue siendo correcta — el diferenciador de la capa de señales (Fase 3) está intacto.

## Fuentes

- **Lookalike:** [Modash Creator Lookalikes API](https://www.modash.io/influencer-marketing-api/creator-lookalikes) (pricing $16,200/año verificado en fuente primaria 2026-07-18) · [Modash how-to lookalikes](https://help.modash.io/en/articles/5467269-how-to-find-lookalike-creators) · [Modash G2](https://www.g2.com/products/modash/reviews) · [Kuli — AI vs traditional](https://kuli.one/blog/ai-vs-traditional-influencer-marketing-platforms-2026/) · [Kuli Creator Content Profile](https://kuli.one/blog/creator-content-profile/) · [Upfluence pricing](https://www.upfluence.com/pricing) · [Upfluence review](https://www.creator-hero.com/blog/upfluence-pricing-and-review) · [Syncly Social](https://syncly.app/social) · [Syncly creator discovery pricing](https://syncly.app/social/solution/creator-discovery/pricing)
- **Enrichment:** [Clay pricing (Landbase)](https://www.landbase.com/blog/clay-pricing) · [Clay G2](https://www.g2.com/products/clay-com-clay/reviews) · [Clay cost breakdown (Amplemarket)](https://www.amplemarket.com/blog/how-much-does-clay-really-cost) · [BetterContact pricing](https://bettercontact.rocks/pricing/) · [BetterContact review (Maildoso)](https://maildoso.ai/blog/catalog/lead-data/bettercontact) · [Prospeo pricing](https://prospeo.io/pricing) · [Prospeo review independiente](https://emailwarmup.com/blog/email-deliverability-tools/prospeo-review/)
- **Señales:** [Trigify pricing](https://www.trigify.io/pricing) · [Trigify review (SyncGTM)](https://syncgtm.com/blog/trigify-review) · [Trigify review (Kondo)](https://www.trykondo.com/blog/trigify-ai-lead-engagement) · [Warmly review (SyncGTM)](https://syncgtm.com/blog/warmly-review) · [Warmly G2](https://www.g2.com/products/warmly-warmly/reviews)
- **Outreach:** [Instantly vs Smartlead (Bavlio)](https://bavlio.com/blog/instantly-vs-smartlead-2026) · [Reddit sentiment (Yalc)](https://www.yalc.ai/blog/smartlead-vs-instantly-reddit/) · [Smartlead pricing (ColdEmailKit)](https://coldemailkit.com/tools/smartlead) · [Smartlead review (MarketBetter)](https://marketbetter.ai/blog/smartlead-review-2026/) · [HeyReach sending limits](https://help.heyreach.io/en/articles/9892903-how-to-configure-my-sending-limits) · [HeyReach pricing (Leadhaste)](https://leadhaste.com/blog/heyreach-pricing-2026)

*Acceso a todas las fuentes: 2026-07-18.*
</content>
</invoke>
