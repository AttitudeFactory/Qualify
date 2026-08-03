# Backlog — Features GTM (teardown Fases 3-5)

> ⚠ **ARCHIVADO como backlog accionable, 2026-07-28.** El backlog vive únicamente en Linear (equipo `Qualify-market`). Los items de este doc ya están seedeados como issues en el proyecto Linear "Parking lot — features analizadas (no planificadas)" (p.ej. P3-0 → `QUA-24`, P3-2 → `QUA-25`). Las correcciones de coste F1-C1/F1-C2 (§ inicial) ya están RESUELTAS y aplicadas en `docs/alternativas-fase1.md`/`README.md` — no requieren issue. **Lo que sigue siendo válido aquí:** la evidencia del teardown y el razonamiento de fase-mapping; para prioridad/estado, Linear gana.

**Fecha:** 2026-07-18
**Fuente de evidencia:** `docs/research-features-gtm.md` (teardown de Modash/Kuli/Upfluence/Syncly, Clay/BetterContact/Prospeo, Trigify/Warmly, Instantly/Smartlead/HeyReach).
**Autor:** product-owner (sesión /team-po).

## Lectura obligatoria antes de usar este backlog

Esta investigación es, casi en su totalidad, sobre **Fases 3, 4 y 5** del roadmap (señales, creator discovery/lookalike, waterfall enrichment, outreach). **La fase actual del roadmap es Fase 1** (pipeline de ingesta/enriquecimiento social: scraping → extracción → filtro CLIP → visión → transcripción → sentiment de comentarios → índice FTS). Ver `CLAUDE.md` → "Roadmap phase map".

**Conclusión honesta de phase-mapping: no hay ningún item de Fase 1 que toque código en esta ronda.** El único punto donde esta investigación roza la Fase 1 son **dos correcciones al modelo de coste de decisiones de vendor ya cerradas** (Prospeo, Smartlead) — son correcciones de documentación/costo, no features. Todo lo demás es parking lot por fase. No se fuerza nada de Fase 3/4/5 a un tramo "listo para /team-dev": eso sería violar la disciplina de fase. Ver la sección final "Prompt sugerido para /team-dev" — explica por qué no hay handoff de código esta ronda.

Estado de código verificado contra el filesystem (no contra los docs): existe `packages/models/` (cascada multimodal — filtro/visión/transcripción/sentiment con tests). **No existen** `packages/shared`, `packages/scraper`, `packages/pipeline`, `packages/gpu-service`, ni ClickHouse/`search.content_index`, ni `signals.events`/`crm.creators`/`billing.usage_events`. Toda la Fase 3/4/5 depende de capas de datos que aún no están construidas (Parte 3 de la Fase 1).

---

## Fase 1 ahora — correcciones al modelo de coste de decisiones ya cerradas

Categoría distinta del backlog de features Fase 3/4/5: NO son features ni tocan código, son correcciones a supuestos de coste detrás de decisiones de vendor que `CLAUDE.md` marca como ya cerradas en Fase 1. Se listan aquí porque corrigen la fase actual, no una futura.

### F1-C1 — Corregir el supuesto de coste de Prospeo (98% es solo lookup individual)

- **Historia:** Como equipo de growth de una marca, quiero que el modelo de coste de enriquecimiento de contacto use el hit-rate real de Prospeo en bulk (no la cifra de lookup individual), para no presupuestar el enriquecimiento masivo de creators con un supuesto 20x optimista.
- **Tipo:** Corrección de documentación / modelo de coste. **No es código. No es una feature de Fase 4/5.**
- **Criterios de aceptación (verificables):**
  - Los docs dejan de citar "Prospeo ~$0.01/email, 98% precisión" como aplicable a enriquecimiento masivo.
  - Queda registrado que el 98% es *solo lookup individual*; en bulk el hit rate observado es ~4.5% (45/1,000) y **cobra por cada fila importada aunque no haya match** (créditos no rotan).
  - La decisión de vendor NO cambia (Prospeo sigue válido como escalón de waterfall); solo se corrige la cifra usada para modelar coste.
- **Evidencia:** `research-features-gtm.md` §Área 2 tabla (línea 69), notas Prospeo (línea 77), Contradicción #3 (línea 122).
- **Docs afectados:** `docs/alternativas-fase1.md` §3b (línea 82), `README.md`. — **RESUELTO (aprobado por el usuario, 2026-07-18)** — las ediciones ya están aplicadas en el working tree (sin commitear). **`CLAUDE.md` NO está afectado**: el architect verificó (2026-07-18) que su línea de stack lista Prospeo/Smartlead sin cifra de precio ni precisión — no hay nada que corregir ahí; el 98% vive solo en `alternativas-fase1.md`.
- **Prioridad / tamaño:** Alta (corrige la fase actual) / S.
- **Dependencias:** Ninguna. Solo edición de docs.

### F1-C2 — Corregir el tier de Smartlead que incluye API/white-label (Pro $94, no Base $39)

- **Historia:** Como responsable de la decisión de outreach de Fase 1, quiero que el modelo de coste refleje que la API/white-label de Smartlead vive en el tier Pro ($94/mes), no en el Base ($39/mes), para no planear la integración sobre el tier equivocado.
- **Tipo:** Corrección de documentación / modelo de coste. **No es código.**
- **Criterios de aceptación (verificables):**
  - Los docs dejan de implicar que el white-label/API de Smartlead está en el tier barato.
  - Queda registrado: Base $39 = mailboxes ilimitados **sin API**; Pro $94 = API + webhooks + white-label.
  - La decisión de vendor NO cambia (Zapmail/Smartlead/Prospeo se sostiene); solo se ajusta el supuesto de coste e integración.
- **Evidencia:** `research-features-gtm.md` §Área 3b tabla (línea 101), notas Smartlead (línea 106), Contradicción #4 (línea 124).
- **Docs afectados:** `docs/alternativas-fase1.md` §3b (línea 73). — **RESUELTO (aprobado por el usuario, 2026-07-18)** — la edición ya está aplicada en el working tree (sin commitear).
- **Prioridad / tamaño:** Alta / S.
- **Dependencias:** Ninguna.

---

## Correcciones a documentación (contradicciones del teardown)

Cross-check de las 7 contradicciones de `research-features-gtm.md` (líneas 114-130) contra el doc que cada una corrige. **Todas son correcciones de documentación, no código.** No edito `docs/ingenieria-inversa-stack-gtm.md`, `docs/alternativas-fase1.md` ni `README.md` (no son mi archivo en esta sesión). **Estado 2026-07-18: el usuario confirmó la aprobación de las correcciones de coste (Prospeo/Smartlead/Trigify) y de la reescritura de tesis competitiva — C1, C2, C3 y C4 quedan RESUELTAS; sus ediciones ya están aplicadas en el working tree (sin commitear).** `CLAUDE.md` y `docs/arquitectura.md` son decisión del architect: se le envían para que decida si son dignos de ADR (el architect está haciendo el flip equivalente en `arquitectura.md` §8.1 items 1 y 5 en paralelo).

| # | Corrección | Doc(s) a editar | Dueño de la edición |
|---|---|---|---|
| C1 | El diferenciador lookalike ya NO es "nadie lo hace con contenido real" — Modash Creator Lookalikes (contenido visual/tópicos, API pública $16.2K/año) y Kuli (frame-by-frame) ya leen contenido. Reescribir el moat como: fusión listening→activation + multimodal completo (audio/transcript+comentarios) + señales con provenance; español-first como refuerzo **no probado**. | `ingenieria-inversa-stack-gtm.md` §2 Capa 1 (línea 48) y §6 (línea 261); posible nota en `CLAUDE.md`/`README.md` | ingenieria/README → **RESUELTO (aprobado por el usuario, 2026-07-18)**; CLAUDE.md → **architect** |
| C2 | Pricing Trigify desactualizado: doc cita "$40–$199/mes"; tiers 2026 reales Essential $149 / Growth $270 / Scale $549, sistema de créditos, PAYG $0.012/crédito. | `ingenieria-inversa-stack-gtm.md` §2 Capa 3 (línea 67) | **RESUELTO (aprobado por el usuario, 2026-07-18)** |
| C3 | Prospeo 98% = solo lookup individual; bulk ~4.5% y cobra por fila. (= F1-C1) | `alternativas-fase1.md` §3b, `README.md` (NO `CLAUDE.md` — verificado sin cifra ahí) | **RESUELTO (aprobado por el usuario, 2026-07-18)** |
| C4 | Smartlead API/white-label en Pro ($94), no Base ($39). (= F1-C2) | `alternativas-fase1.md` §3b (línea 73) | **RESUELTO (aprobado por el usuario, 2026-07-18)** |
| C5 | Instantly deprecó API v1 el 2026-01-19 y se partió en 3 módulos de precio separado. Cualquier integración Fase 5 apunta a la API nueva; documentar en la futura ADR de outreach. | `docs/arquitectura.md` — **ya registrado** bajo la nota de ADR 7 (§6) | **RESUELTO** (architect, 2026-07-18) |
| C6 | Lección de diseño para `billing.usage_events` (Fase 5): cobrar por **dato válido** (patrón BetterContact), no por intento (anti-patrón Clay, credit-burn impredecible). | `docs/arquitectura.md` — **ya registrado** en §8.1 item 6 | **RESUELTO** (architect, 2026-07-18) |
| C7 | **Se confirma:** nadie hace capa de señales sobre TikTok/IG audiovisual — el diferenciador de Fase 3 sigue intacto. No requiere corrección; es una validación a preservar. | ninguno (validación) | — |

---

## Parking lot — Fase 3 (Señales / intent + visual listening)

> No entra a sprint hasta que el roadmap abra Fase 3. Todos estos dependen de que exista `search.content_index` + comentarios en ClickHouse (Fase 1 Parte 3, aún no construida).

### P3-0 — Primitiva de clasificación zero-shot de texto (topic/intent/stance) + extensión del golden-set

- **Historia:** Como equipo de growth/community de una marca, quiero que Qualify distinga *de qué trata* una mención (tema, intención, postura), no solo si es positiva o negativa, para detectar señales accionables (queja de pago a un creator, "abierto a colaboraciones", fricción con una marca) que la polaridad de 3 clases no puede separar.
- **Contexto (por qué es su propio item, separable de P3-1):** la cascada actual (`packages/models`) solo tiene polaridad de 3 clases (robertuito); **no tiene clasificador de topic/intent/stance**. Ese hueco bloquea 7 de 10 dolores de creador/podcaster detectables como señal (NOTES §1) y es la primitiva que habilita la capa de "señales tipadas sobre TikTok/IG audiovisual" (hueco competitivo confirmado). A diferencia del resto de P3-1, **no depende de `search.content_index`/`signals.events`** (Fase 1 Parte 3, no construida): corre sobre texto que ya existe (caption/transcript/comentarios) y se puede shippear como spike YA contra las fixtures de `packages/models`.
- **Criterios de aceptación (verificables):**
  - Implementado como un nuevo `Provider` zero-shot de texto bajo el protocolo de `packages/models` (no forkea la cascada). Checkpoint primario `MoritzLaurer/bge-m3-zeroshot-v2.0` (MIT, verificado live en HF Hub 2026-07-18, hf-inference disponible); fallback más barato `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (MIT). Etiquetas candidatas configurables (no reentrenamiento).
  - **Métrica por señal, no micro-promediada:** precision/recall/F1 + PR-AUC en el umbral calibrado, reportadas **por label** (p.ej. pago-atrasado y crisis tienen perfiles de coste opuestos).
  - **Extensión estratificada del golden-set** (`arquitectura.md` §7): reusar el mismo set de ~100 videos con una **segunda capa de labels multi-label a nivel de fragmento**; augmentación dirigida para las señales de baja tasa base (p.ej. retraso de pago) hasta ≥30-50 positivos por señal, en un pool **separado** del set representativo para no inflar la precisión in-the-wild; dos anotadores + acuerdo (Cohen's κ) reportado en el subconjunto de topic/stance.
  - Umbral calibrado **por señal** al perfil de coste (recall para crisis/disputa de baja base; precision para intent que dispara acción GTM).
  - Provenance: cada salida lleva `detector_version` + umbral + `label_set_version` (regla dura; alineado con ADR 16).
  - **Revisión de licencia (riesgo heredado, no nuevo):** si se añade el refuerzo de emoción `pysentimiento/robertuito-emotion-analysis`, su licencia está **sin declarar** en el Hub — misma pregunta que ya aplica al `robertuito-sentiment-analysis` ya comprometido, no un riesgo nuevo; confirmar términos comerciales upstream antes de lockear (los zero-shot MIT pueden emitir labels tipo-emoción como sustituto comercial limpio si falla). Ver ADR 13.
  - Corre con `uv run pytest` sin red sobre las fixtures existentes.
- **Fase:** 3, **pero shippable como spike YA** (igual que P4-3): no depende de Fase 1 Parte 3 — corre sobre `packages/models` + fixtures actuales. El resto de P3-1 (materializar señales en ClickHouse) sí espera a Parte 3.
- **Evidencia:** `packages/models/NOTES_pain_signal_feasibility.md` §1 (7/10 dolores resueltos por esta única primitiva), §2 (checkpoints verificados live), §4 (extensión del golden-set), §5 (coste incremental <5% del coste por video de la cascada). *(Fuente distinta de `research-features-gtm.md` — item traído por decisión explícita del lead, 2026-07-18.)*
- **Prioridad / tamaño:** Alta dentro de Fase 3 (primitiva de mayor apalancamiento — convierte "señales tipadas sobre audiovisual" de no-construible a construible) / M. **[Dueño natural: datasci]**
- **Dependencias:** **Ninguna dura** — corre sobre fixtures existentes. Es la **primitiva habilitante** de la que dependen P3-1 (lógica de detección real, una vez exista ClickHouse) y P3-2 (intent en comentarios), y el "por qué" detrás de las alertas de crisis.

### P3-1 — Librería de detectores de señales tipados con provenance (anti-firehose)

- **Historia:** Como equipo de growth de una marca, quiero recibir señales accionables y priorizadas (no un firehose de alertas), cada una con su fuente rastreable, para actuar sobre las pocas que importan sin ahogarme en ruido.
- **Criterios de aceptación:**
  - Cada señal persiste provenance: `post_id`/`comment_id`/`source_id` + `detector_version` (regla dura de arquitectura).
  - **Filtros disciplinados + scoring, no firehose**: la queja #1 de Trigify es "50 alertas/día, 5 accionables" — el diseño debe incluir umbral/scoring configurable y medir la tasa señal-accionable, no solo el volumen bruto.
  - Detectores tipados y componibles (no reglas ad-hoc dispersas).
  - Corre con `uv run pytest` sin red sobre fixtures.
- **Fase:** 3.
- **Evidencia:** `research-features-gtm.md` §3a notas Trigify (línea 92: volumen sin actionability), Contradicción #7 (línea 130: nadie lo hace en social audiovisual); `ingenieria-inversa-stack-gtm.md` §2 Capa 3.
- **Prioridad / tamaño:** Alta dentro de Fase 3 (corazón del producto) / L.
- **Dependencias:** `search.content_index` + comentarios (Fase 1 Parte 3). Construye sobre la salida de `packages/models`. **Depende de P3-0** como primitiva de detección: la lógica de señales tipadas necesita el clasificador zero-shot de topic/intent/stance (P3-0) para separar señales que la polaridad de 3 clases no distingue — P3-0 es shippable antes (spike sobre fixtures), esta capa lo consume una vez exista ClickHouse.

### P3-2 — Señal de comentaristas/audiencia como eje mapeable (engagement capture)

- **Historia:** Como equipo de community de una marca, quiero mapear quién comenta/interactúa con un creator o competidor (p.ej. "usuario preguntó dónde comprar", "usuario se queja del producto de la competencia"), para convertir la audiencia en intent accionable.
- **Criterios de aceptación:**
  - Detecta y tipa intent desde la sección de comentarios con provenance al `comment_id`.
  - El eje comentaristas se materializa de forma consultable (no solo sentiment agregado).
- **Fase:** 3 (alimenta el eje de similitud de Fase 4, P4-2).
- **Evidencia:** `research-features-gtm.md` línea 45 (nadie usa la señal de comentarios), línea 53; `ingenieria-inversa-stack-gtm.md` línea 77 (engagement capture = mina de oro de Trigify).
- **Prioridad / tamaño:** Alta dentro de Fase 3 / M.
- **Dependencias:** Comentarios en ClickHouse (Fase 1 Parte 3). Habilita P4-2.

---

## Parking lot — Fase 4 (Creator discovery + CRM + waterfall enrichment)

> No entra a sprint hasta Fase 4. Depende de `search.embeddings` + `crm.creators` (diseñados, no construidos) y de la salida de la cascada multimodal.

### P4-1 — Lookalike de creators sobre embeddings de contenido multimodal completo

- **Historia:** Como equipo de marketing de una marca, quiero encontrar creators similares a un set de handles usando el contenido real de sus videos (audio/transcript + visión + captions + comentarios), no su bio ni sus métricas, para descubrir talento que los tools basados en metadata no ven.
- **Criterios de aceptación:**
  - Matching sobre embeddings del contenido propio (centroide por creator), no metadata.
  - Diferenciador explícito frente a Modash (solo eje visual+tópicos, sin audio ni comentarios): incluir el eje **audio/transcript + comentarios**.
  - Provenance: cada match rastreable a los `post_id` que formaron el centroide + `pipeline_version`.
  - **Challenged & survived (datasci, 2026-07-18, verificado contra HF Hub; bajo, sin decisión de usuario). Se implementa como un nuevo `EmbeddingProvider` bajo el protocolo `Provider` de `packages/models` (no forkea la cascada), apoyado en `search.embeddings` (vector store + ANN, aún no construido; cubierto por ADRs 10-13 del architect). Cuatro condiciones son AC obligatorias:**
    1. **Centroide POR MODALIDAD, fusionado en el scoring — no un vector multimodal único.** Texto y visión viven en espacios de embedding distintos (p.ej. 1024 vs 768) y no son cosine-comparables: prohibido concatenar/promediar en un solo vector; se puntúa por modalidad y se fusiona al rankear (ADR 10/11).
    2. **Creators multi-nicho se representan con sub-centroides (clustering), no un centroide promedio único** (`centroid_ix`, ADR 10) — un promedio de contenido disperso no matchea bien con nada.
    3. **Checkpoint de embedding validado en golden-set entre `intfloat/multilingual-e5-large` / `BAAI/bge-m3` / `Qwen/Qwen3-Embedding-0.6B` (los tres comercial-OK), no fijado a priori.** (Nombre `multilingual-e5-large` alineado con `arquitectura.md` §8.1 item 2 / ADR 13; tanto la variante non-instruct como `-instruct` son MIT/comercial-OK — arquitectura lista la non-instruct por la similaridad simétrica sin prefijos query:/passage:, mejor fit para lookalike creator-a-creator.) **Prohibido** `jinaai/jina-embeddings-v3` (cc-by-nc-4.0, no comercial). `sentence-transformers` (citado en `CLAUDE.md`) es la librería runtime, no el checkpoint.
    4. **Piso de cold-start:** creators por debajo de un mínimo de contenido (N posts / tokens de transcript, N por calibrar en golden-set) no se indexan para lookalike o se marcan baja-confianza.
  - Si el eje visual del centroide usa `moondream3-preview`: AC de **revisión de licencia comercial** — su licencia es ahora `other`, no Apache-2.0 (el default de código `Qwen/Qwen3-VL-4B-Instruct` sí es Apache-2.0). Corrige de paso `modelos-multimodal-fase1.md` línea 4 ("todos Apache-2.0", falso para moondream3).
  - Coste: el embedding es barato (reutiliza la salida ya enriquecida de la cascada Fase 1); el gate de coste real es la inferencia VLM+ASR de Fase 1, ya presupuestada. No modelar este item como nueva inferencia pesada.
- **Fase:** 4.
- **Evidencia:** `research-features-gtm.md` §Área 1 (línea 35 redefinición del moat; líneas 51-57 el eje que sobrevive; línea 43 Modash no transcribe ni usa comentarios).
- **Prioridad / tamaño:** Alta dentro de Fase 4 / L.
- **Dependencias:** `search.embeddings`, `crm.creators` (no construidos). Construye sobre `packages/models`. **Nota de conflicto research↔arquitectura:** el research estrecha el moat que `ingenieria-inversa-stack-gtm.md` §6 da por sentado — resuelto vía C1 antes de que este item entre a sprint.

### P4-2 — Comentaristas como eje de similitud del lookalike (el eje que nadie usa)

- **Historia:** Como equipo de marketing de una marca, quiero que la búsqueda de creators similares considere el solapamiento de su audiencia de comentaristas, para encontrar creators que comparten público real (no solo estética), un eje que ningún competidor ofrece.
- **Criterios de aceptación:**
  - El lookalike incorpora una señal de similitud derivada de los comentaristas/audiencia, no solo del contenido del creator.
  - Documentado como diferenciador: Modash/Kuli/Syncly no usan el eje comentarios.
  - **Challenged & survived (datasci, 2026-07-18): ML-sólido como concepto (similitud item-item sobre un grafo bipartito usuario↔creator — collaborative filtering, bien precedentado), NO es ruido inherente — pero es el eje propenso a ruido y sobrevive SOLO con estas cuatro precondiciones como AC:**
    1. **Ponderar por IDF y descartar comentaristas hub — el modo de fallo dominante.** Cuentas hiperactivas (giveaway/bot/follow-back/spam) comentan en todo y fabrican solapamiento espurio entre creators no relacionados. El solapamiento crudo sin ponderar no se usa; los de frecuencia extrema se descartan. Sin esto, el eje solo re-rankea por popularidad de comentaristas.
    2. **Piso de volumen de solapamiento:** requiere creator con ≥ N comentaristas distintos, y el solapamiento cuenta solo con ≥ K comentaristas compartidos (N/K por calibrar en golden-set, pero el piso debe existir).
    3. **Filtrado spam/bot upstream es dependencia dura:** las reglas de spam del comment-worker (P3-2) DEBEN correr antes de que los comentaristas alimenten similitud, o los bot rings dominan. Precondición explícita, no solo dependencia de datos.
    4. **Eje SECUNDARIO ponderado en el score fusionado con el centroide de contenido (P4-1), validado por lift incremental sobre content-only — no señal de ranking única.** Si no añade lift medible sobre P4-1 en el eval, no se lanza.
  - Componente NUEVO (no fork, no rewrite): se implementa bajo el protocolo `Provider` como `EmbeddingProvider` + agregación creator→centroide sobre comentaristas; depende de que `search.embeddings` exista primero. Hoy `packages/models` corre robertuito *sentiment* sobre comentarios, pero no produce embeddings ni tiene superficie de similitud.
- **Fase:** 4.
- **Evidencia:** `research-features-gtm.md` línea 53 (comentaristas como eje de similitud — nadie lo usa), línea 45.
- **Prioridad / tamaño:** Media-alta dentro de Fase 4 (moat #2 según el research) / M.
- **Dependencias:** **DURA/bloqueante sobre P3-2** — P4-2 no puede entrar a sprint antes de que P3-2 (filtrado spam/bot + comentaristas materializados) haya shippeado; sin la remoción upstream de bots + IDF-weighting el eje colapsa a ruido de popularidad (todos comparten las mismas mega-cuentas en comentarios). También depende de P4-1 (infra de lookalike/`search.embeddings`). Confirmado por architect (registrado en `arquitectura.md` §6, moat pilar #2) y datasci (2026-07-18).

### P4-3 — [HIPÓTESIS] Validación empírica del moat "español-first"

- **Historia:** Como PO, quiero una medición empírica de si la calidad de discovery/transcripción de los competidores se degrada en español, para decidir si "español-first" es un pilar del moat o solo un refuerzo secundario — antes de posicionar producto sobre esa premisa.
- **Tipo:** Tarea de evaluación/research, **no feature**. Etiquetada como HIPÓTESIS: el research dice explícitamente que no puede afirmarse el moat español sin medición (línea 49, 55).
- **Criterios de aceptación:**
  - WER de transcripción ES medido sobre fixtures ES (nuestro pipeline vs. baseline), o test de los lookalikes de Modash/Kuli/Syncly con creators hispanos.
  - Resultado que confirme o descarte la degradación en español con datos, no afirmación.
  - Mientras no exista esta medición, ningún doc de posicionamiento presenta "español-first" como pilar del moat (solo como refuerzo no probado).
- **Fase:** 4 (o antes como spike de evaluación si el lead lo aprueba; encaja en el golden-set de `arquitectura.md` §7).
- **Evidencia:** `research-features-gtm.md` línea 49 (sin evidencia pública; pendiente datasci), línea 55 (refuerzo secundario sin probar).
- **Prioridad / tamaño:** Media / S-M. **[Dueño natural: datasci]**
- **Dependencias:** Ninguna dura; usa `packages/models` + fixtures ES.

### P4-4 — Waterfall de contacto de creator (pay-per-valid-data)

- **Historia:** Como equipo de growth de una marca, quiero resolver el contacto de un creator recorriendo una cascada (bio → link-in-bio → website → API externa) que solo consuma presupuesto cuando devuelve un dato válido, para no quemar créditos en intentos fallidos.
- **Criterios de aceptación:**
  - Cascada ordenada con corte al primer match válido.
  - **Contabiliza solo el dato válido** (patrón BetterContact), no el intento (anti-patrón Clay).
  - Prospeo/BetterContact integrados como escalones finales vía API (buy, no build — infra de contacto es comprada).
  - Provenance del origen del dato de contacto por creator.
- **Fase:** 4.
- **Evidencia:** `research-features-gtm.md` línea 75 (waterfall crece con listas heterogéneas multi-región — relevante para creators multi-idioma), línea 79 (patrón BetterContact vs Clay); Contradicción #6 (línea 128).
- **Prioridad / tamaño:** Media dentro de Fase 4 / M.
- **Dependencias:** `crm.creators`. Alimenta el modelo de créditos de Fase 5 (P5-1).

---

## Parking lot — Fase 5 (GTM activation: billing + outreach)

> No entra a sprint hasta Fase 5.

### P5-1 — Modelo de créditos `billing.usage_events` predecible (cobrar por dato válido)

- **Historia:** Como marca que paga por uso, quiero que el consumo de créditos sea predecible y visible antes de confirmar una acción, y que solo se me cobre por datos válidos, para no sufrir el "credit burn" impredecible que es la queja #1 de Clay.
- **Criterios de aceptación:**
  - `billing.usage_events` cobra por **dato válido entregado** (patrón BetterContact), no por intento (anti-patrón Clay).
  - Consumo estimado y visible **antes** del commit de la operación.
  - Provenance de cada evento de uso (qué operación/fuente lo generó).
- **Fase:** 5.
- **Evidencia:** `research-features-gtm.md` §Área 2 notas Clay (línea 67: cobra por intento fallido, $3,000 quemados; línea 73), Contradicción #6 (línea 128).
- **Prioridad / tamaño:** Alta dentro de Fase 5 (define confianza del modelo de negocio) / M.
- **Dependencias:** `billing.usage_events` (diseñado, no construido). Consume la contabilidad de P4-4.

### P5-2 — Integración de outreach (buy, no build)

- **Historia:** Como equipo de growth de una marca, quiero empujar listas calificadas + mensaje redactado a herramientas de outreach existentes (Smartlead/Instantly email, HeyReach LinkedIn), para activar sin que Qualify construya infraestructura de deliverability.
- **Criterios de aceptación:**
  - Integración vía API contra el vendor decidido (buy, no build — deliverability es problema resuelto y arriesgado).
  - Apunta a la **API nueva de Instantly** (v1 deprecada 2026-01-19), no la v1.
  - Modela los **caps de LinkedIn de HeyReach** (20–25 conexiones/día, ~10 invites-con-nota/mes) si gestiona envío multi-cuenta.
  - Usa el tier correcto de Smartlead (Pro $94, que incluye API — ver F1-C2).
- **Fase:** 5.
- **Evidencia:** `research-features-gtm.md` §Área 3b (líneas 100-108), Contradicciones #4 y #5 (líneas 124, 126).
- **Prioridad / tamaño:** Media dentro de Fase 5 / M.
- **Dependencias:** Señales (P3-1) + waterfall (P4-4) para tener a quién y con qué contactar. ADR de outreach (C5).

---

## Prompt sugerido para /team-dev

**No hay handoff de código para /team-dev esta ronda.** Y es el resultado esperado, no un fallo: `docs/research-features-gtm.md` es un teardown de features de **Fases 3/4/5** (señales, lookalike, enriquecimiento, outreach), y la fase actual del roadmap es **Fase 1** (solo el pipeline de ingesta). Tras el phase-mapping honesto, cero items de esta investigación tocan código dentro del alcance de Fase 1.

Lo único que corrige la Fase 1 son **F1-C1** y **F1-C2** (correcciones al modelo de coste de Prospeo y Smartlead) más las 7 correcciones de documentación (sección "Contradicciones") — ninguna es código, y ninguna es mi archivo para editar:
- **Para el architect:** decidir si C1/C5/C6 y las notas de `CLAUDE.md` ameritan ADR o edición de `docs/arquitectura.md`.
- **Para el lead — RESUELTO (usuario aprobó, 2026-07-18):** las ediciones a `docs/ingenieria-inversa-stack-gtm.md` (C1, C2), `docs/alternativas-fase1.md` (C3/F1-C1, C4/F1-C2) y `README.md` (C1, C3) fueron aprobadas por el usuario y ya están aplicadas en el working tree (sin commitear).

El trabajo de código de Fase 1 que sí queda pendiente (Parte 2 scraping, Parte 3 orquestación/ClickHouse) **no sale de esta investigación** — sale de `docs/plan-ingesta-social.md`, y es material para un /team-dev distinto, no para este backlog.
