# Backlog — Fase 5: Motor de Ángulos + generación orquestada

**Fecha:** 2026-08-10 · **Autor:** sesión de handoff (research → backlog).
**Decisión rectora:** `docs/adr-32-motor-angulos-creativo.md` (`[PROPUESTO]`, pendiente de firma).
**Evidencia:** `docs/comparativa-apis-creativo-motor-angulos.md` (vendors/precios), `docs/brief-decisiones-motor-angulos.md` (D1–D16).

## Lectura obligatoria antes de usar este backlog

- **Fase.** Todo esto es **Fase 5 (GTM activation)** — el Motor de Ángulos es una "play" en el sentido del roadmap (signal → brief → acción asistida → push). La fase actual del roadmap es Fase 1. **Nada de este backlog entra a un sprint de `/team-dev` hasta que el ADR 32 esté firmado y se abra Fase 5.**
- **Gate de datos (duro).** El *wedge de insight* (Epic B) depende de `search.content_index` + comentarios + `signals` en el plano analítico — **no construidos** (Fase 1 Parte 3 + Fase 3). Sin esos datos, el motor es un wrapper de una API, que es exactamente lo que el ADR 32 prohíbe. Epic A (orquestación) y Epic C (imagen MVP) pueden prototiparse contra fixtures antes, pero **no se shippea como producto** sin cerrar el gate de datos.
- **Qué NO se construye (no-goals explícitos, ADR 32):** generador de creativo propio; marketplace de diseñadores como producto; integración de Omneky/Pencil/AdCreative como motor (su insight compite con el nuestro); generación autónoma sin aprobación humana.
- **Provenance es regla dura** (como en todo el repo): cada ángulo/brief/asset lleva la fuente (`post_id`/`comment_id`) + `detector_version`/`pipeline_version` + `model_id`/`revision`.
- El backlog accionable vive en **Linear** (equipo `Qualify-market`); este doc registra historias y razonamiento. IDs propuestos: `F5-MA-##`.

---

## Épica A — Fundación de orquestación *(prototipable sin el gate de datos)*

### F5-MA-01 — `GenerationProvider` protocol + seam de adaptadores (fal primario, Replicate espejo)

- **Historia:** Como plataforma, quiero una interfaz única `generate(task, params, budget_ctx) -> job` con implementaciones intercambiables, para orquestar cualquier proveedor de creativo sin acoplar el motor a ninguno.
- **Criterios de aceptación (verificables):**
  - Existe un protocolo `GenerationProvider` (mismo patrón que `Provider` en `packages/models` y `VideoFetcher` en `packages/scraper`), con adaptadores `FalAdapter` y `ReplicateAdapter`.
  - Un test de contrato por adaptador valida forma de request/response contra fixtures grabadas (sin red en CI; marcador `integration` para las llamadas reales).
  - El código de negocio nunca importa el SDK de fal/Replicate directamente — solo el protocolo.
- **Fase:** 5. **Dependencias:** ninguna dura (prototipable con fixtures). **Prioridad/tamaño:** Alta / M. **Dueño natural:** pipeline-engineer.

### F5-MA-02 — `CreativeRouter` con cadenas de fallback (criterios F/P/Q)

- **Historia:** Como marketer, quiero que si el proveedor primario falla, se pasa de presupuesto, o la calidad no alcanza, el motor caiga automáticamente al siguiente eslabón de la cadena, para que una generación no se caiga por un proveedor.
- **Criterios de aceptación (verificables):**
  - El router recorre una `chain` ordenada aplicando: **(F)** fallo/timeout → siguiente; **(P)** coste proyectado > cap restante → downgrade/bloqueo; **(Q)** score < umbral → siguiente.
  - **El primer fallback ante (F) es saltar de agregador para el MISMO modelo** (fal→Replicate) antes de cambiar de modelo.
  - `max_retries_per_provider` respetado; toda decisión de salto queda logueada con motivo.
- **Fase:** 5. **Dependencias:** F5-MA-01, F5-MA-03. **Prioridad/tamaño:** Alta / M. **Dueño:** pipeline-engineer.

### F5-MA-03 — Tabla de precios versionada + job de refresco

- **Historia:** Como responsable de márgenes, quiero que el coste por pieza se calcule contra una tabla de precios versionada y cacheada, no contra literales en código, porque los precios de agregador fluctúan 2–4x.
- **Criterios de aceptación (verificables):**
  - Existe una tabla `creative_pricing` versionada (modelo, unidad, precio, fecha, fuente) resuelta por el router.
  - Un job programado refresca precios; un cambio no rompe adaptadores pineados (pin de versión explícito por modelo).
  - El cap de presupuesto y la estimación por-pieza leen de esta tabla.
- **Fase:** 5. **Dependencias:** ninguna. **Prioridad/tamaño:** Alta / S. **Dueño:** pipeline-engineer.

### F5-MA-04 — Config por-cuenta (`creative_engine_config`) + presupuesto + credenciales

- **Historia:** Como admin/marketer, quiero configurar por cada cuenta su cap mensual, tier por defecto, proveedores habilitados por tarea y credenciales, para operar dentro del presupuesto de cada cliente.
- **Criterios de aceptación (verificables):**
  - Esquema `creative_engine_config` por cuenta con: `monthly_budget_cap_usd`, `budget_spent_usd`, `default_tier`, `hitl_required=true`, `aggregators` (primary/mirror), `task_chains` por tarea (chain, `max_cost_per_piece_usd`, `quality_threshold`), `brand_kit`, `fallback_policy`.
  - Credenciales por adaptador se guardan como `secret_ref` a store cifrado (patrón `qualify_credential`/`oauth_credentials.ciphertext`), **nunca en claro**; test estático lo verifica.
  - Cada generación registra un evento en `billing.usage_events` (coste válido, patrón BetterContact — ver C6 de `backlog-features-gtm.md`); al 100% del cap con `hard_stop_on_cap=true` el motor no genera.
- **Fase:** 5. **Dependencias:** F5-MA-03; `billing.usage_events` (diseñado, no construido). **Prioridad/tamaño:** Alta / L. **Dueño:** pipeline-engineer + architect (RLS/custodia).

### F5-MA-05 — Gobernanza: data-residency + gate de licencia/consentimiento

- **Historia:** Como responsable legal/operativo, quiero poder restringir por cuenta los proveedores por residencia de datos y bloquear usos que exijan licencia/consentimiento, para no incumplir con marcas sensibles ni con licencias de modelo.
- **Criterios de aceptación (verificables):**
  - Flag `data_residency_restricted` por cuenta que fuerza la cadena a proveedores US/EU (Luma/Runway/FLUX/Google), excluyendo Kling/Seedance/Hailuo/Pippit.
  - FLUX.2-dev self-host y clonado de avatares (HeyGen/Arcads) quedan **bloqueados** hasta ADR/licencia específica (BFL de pago; consentimiento + App Review). Klein-4B (Apache-2.0) permitido para self-host.
- **Fase:** 5. **Dependencias:** F5-MA-02. **Prioridad/tamaño:** Media / S. **Dueño:** architect.

---

## Épica B — El *wedge de insight* (Motor de Ángulos) *(GATE DE DATOS: Parte 3 + Fase 3)*

### F5-MA-06 — Recuperación de evidencia earned media

- **Historia:** Como marketer, quiero que Qualify reúna la evidencia de qué está funcionando ahora en mi categoría (ganchos, formatos, temas, objeciones, lenguaje) desde el earned media analizado, para fundar los ángulos en datos y no en opinión.
- **Criterios de aceptación (verificables):**
  - Capa de query sobre `search.content_index` + features del módulo `hooks` + sentimiento/temas de comentarios + señales de engagement, filtrable por categoría/competidores/ventana temporal y `tenant_id` (RLS).
  - Cada pieza de evidencia retorna su provenance (`post_id`/`comment_id`, `fragment_type`, versión de detector).
- **Fase:** 5. **Dependencias (duras):** `search.content_index` + comentarios (Parte 3), `signals` (Fase 3), módulo `hooks`. **Prioridad/tamaño:** Alta / M. **Dueño:** datasci + pipeline-engineer.

### F5-MA-07 — Síntesis y ranking de ángulos (LLM) con provenance

- **Historia:** Como marketer, quiero recibir ángulos distintos y priorizados, cada uno con la evidencia que lo respalda, para elegir sobre datos y no sobre un firehose de ideas.
- **Criterios de aceptación (verificables):**
  - Un LLM (Claude) agrupa la evidencia en ángulos `{promesa/gancho, emoción, formato, citas de evidencia, por-qué-ahora}`.
  - Ranking evidence-weighted = f(velocidad de engagement de la fuente × recencia × relevancia al producto); reproducible y auditable.
  - Provenance obligatoria: cada ángulo enlaza los `post_id`/`comment_id` de los que salió + `pipeline_version`.
- **Fase:** 5. **Dependencias:** F5-MA-06. **Prioridad/tamaño:** Alta / M. **Dueño:** datasci.

### F5-MA-08 — Generación de brief de producción por ángulo

- **Historia:** Como marketer, quiero que un ángulo seleccionado se convierta en un brief accionable (guion/gancho, dirección visual, spec de formato, variantes de copy, CTA, assets de producto requeridos), para pasar directo a generación.
- **Criterios de aceptación (verificables):**
  - Por ángulo aprobado se produce un brief estructurado y editable, con el `brand_kit` de la cuenta inyectado (refs de producto, paleta, avatar/voz si aplica).
  - El brief es el contrato de entrada de la capa de generación (Épica C).
- **Fase:** 5. **Dependencias:** F5-MA-07. **Prioridad/tamaño:** Alta / M. **Dueño:** datasci.

### F5-MA-08b — Modelo de datos del motor (con provenance)

- **Historia:** Como plataforma, quiero persistir ángulos, briefs, assets y jobs de generación con provenance y contabilidad de coste, para trazabilidad y para el loop de aprendizaje.
- **Criterios de aceptación (verificables):**
  - Tablas `angles`, `briefs`, `creative_assets`, `generation_jobs` (proveedor, modelo, coste, unidad, duración/segundos, estado) con RLS por `tenant_id` y FK a la fuente earned media.
  - Migración Alembic con RLS en la misma revisión (ADR 27).
- **Fase:** 5. **Dependencias:** Parte 3 (plano analítico). **Prioridad/tamaño:** Alta / M. **Dueño:** architect + pipeline-engineer.

---

## Épica C — Generación (capa imagen primero)

### F5-MA-09 — Adaptador de imagen MVP (FLUX.2 [pro] → Seedream 4.0)

- **Historia:** Como marketer, quiero generar imágenes de ad on-brief con fidelidad de producto, empezando por la capa más barata y rápida de validar.
- **Criterios de aceptación (verificables):**
  - Genera imagen desde un brief vía fal (FLUX.2 [pro]) con fallback a Seedream 4.0; usa `reference_images` del `brand_kit` para consistencia de producto.
  - Ruta a Ideogram cuando el creativo lleva texto legible (headline/CTA/packaging), según la cadena de la cuenta.
  - Coste por pieza registrado en `billing.usage_events`; respeta el cap.
- **Fase:** 5. **Dependencias:** F5-MA-01/02/03/04, F5-MA-08. **Prioridad/tamaño:** Alta / M. **Dueño:** pipeline-engineer.

### F5-MA-10 — Capas video base (Kling) y UGC-avatar (HeyGen) por tier *(v2)*

- **Historia:** Como marketer con presupuesto, quiero también video base y UGC con vocero, activables por tier.
- **Criterios de aceptación (verificables):**
  - Video base vía Kling 2.5 Turbo (estándar) con cadena por tier; UGC-avatar vía HeyGen (API pública por-uso) + Captions/Mirage como fallback; Creatify solo como adaptador dedicado para cuentas ecommerce con contrato Enterprise.
  - Veo/Arcads solo en tier premium, tratados como upsell (coste ~10x); Sora **excluido** (cierre de API 2026-09-24).
- **Fase:** 5 (v2). **Dependencias:** F5-MA-09. **Prioridad/tamaño:** Media / L. **Dueño:** pipeline-engineer.

---

## Épica D — HITL, publicación y loop

### F5-MA-11 — UI Reflex: selección de ángulo (HITL #1)

- **Historia:** Como marketer, quiero ver los ángulos rankeados **con su evidencia** y elegir cuáles producir, para decidir sobre datos.
- **Criterios de aceptación (verificables):**
  - Vista Reflex que lista ángulos con score y las citas de evidencia (posts/comentarios fuente); permite seleccionar 1–N para generar brief.
- **Fase:** 5. **Dependencias:** F5-MA-07. **Prioridad/tamaño:** Alta / M. **Dueño:** reflex-ui-engineer.

### F5-MA-12 — UI Reflex: revisión/aprobación de creativo (HITL #2)

- **Historia:** Como marketer, quiero revisar, editar copy y aprobar las variantes generadas antes de publicar, para no publicar nada sin control humano.
- **Criterios de aceptación (verificables):**
  - Vista de revisión de assets con edición de copy, aprobación/rechazo (rechazo dispara salto de calidad (Q) o regeneración); nada se publica sin aprobación (`hitl_required=true`).
- **Fase:** 5. **Dependencias:** F5-MA-09. **Prioridad/tamaño:** Alta / M. **Dueño:** reflex-ui-engineer.

### F5-MA-13 — Publicación / export

- **Historia:** Como marketer, quiero publicar el creativo aprobado en la cuenta conectada o exportarlo, reusando la maquinaria de publicación existente.
- **Criterios de aceptación (verificables):**
  - Publica reusando el path de Parte 4 (`publish_attempts`/`scheduled_posts`) o exporta el asset; registra el vínculo asset→publicación para el loop.
- **Fase:** 5. **Dependencias:** Parte 4 (publishing), F5-MA-12. **Prioridad/tamaño:** Media / M. **Dueño:** pipeline-engineer.

### F5-MA-14 — Loop de aprendizaje (performance → ranking) *(v2)*

- **Historia:** Como marketer, quiero que el motor aprenda qué ángulos convirtieron de verdad para mi cuenta, para que las próximas sugerencias mejoren.
- **Criterios de aceptación (verificables):**
  - Las métricas de performance del creativo publicado (owned media) vuelven y ajustan el ranking de ángulos por cuenta; el ajuste es auditable y no sobreescribe la evidencia original.
- **Fase:** 5 (v2). **Dependencias:** F5-MA-13, métricas de owned media. **Prioridad/tamaño:** Media / L. **Dueño:** datasci.

---

## Épica E — Validación

### F5-MA-15 — Kill criterion instrumentado *(decidir antes de escribir código)*

- **Historia:** Como fundador, quiero medir si los ángulos generados-por-evidencia superan a los briefs manuales del marketer, para saber si este wedge tiene foso o hay que apagarlo.
- **Criterios de aceptación (verificables):**
  - Se define y se instrumenta una métrica de comparación (ángulos del motor vs. briefs manuales) sobre N campañas, con umbral y ventana explícitos.
  - Si tras N campañas el motor no supera al baseline manual, se documenta la decisión de apagar el wedge. La métrica existe **antes** del primer sprint de producto.
- **Fase:** 5 (transversal). **Dependencias:** F5-MA-13 (para tener campañas reales). **Prioridad/tamaño:** Alta / S. **Dueño:** datasci + fundador.

---

## Orden sugerido de ataque

1. **Cerrar gates:** firma del ADR 32 + confirmar que Parte 3/Fase 3 están en el horizonte.
2. **Épica A** (fundación de orquestación) — prototipable ya contra fixtures; construye el seam sin lock-in.
3. **Épica C / F5-MA-09** (imagen MVP) — valida generación on-brief end-to-end contra briefs manuales.
4. **Épica B** cuando el gate de datos abra — convierte el generador en Motor de Ángulos (el foso).
5. **Épica D** (HITL + publicación) y luego **F5-MA-15** (kill criterion) con campañas reales.
6. **v2:** video/UGC (F5-MA-10) y loop de aprendizaje (F5-MA-14).
