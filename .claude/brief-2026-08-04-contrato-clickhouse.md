# Brief — Contrato de esquema ClickHouse antes del DDL de Parte 3

**Fecha:** 2026-08-04
**Preparado por:** `qualify-second-brain` (sesión de enrutado, sin trabajo de dominio)
**Destinatario:** sesión propia con `claude --agent principal-architect` (o `research-lead` + `/team-research` si se decide ampliar)
**Estado del repo al preparar el brief:** rama `feat/2026-07-27-domain-commits`, working tree limpio, HEAD `52ba1ea`

---

## 0. Por qué esta sesión existe ahora y no dentro de dos semanas

El fundador (Herwin) **acaba de entregar la Fase 1 a otro developer** y se reserva la Fase 2 (social listening) y la Fase 4 (lookalike). Eso convierte una deuda documental latente en un riesgo con fecha:

- Ese developer va a construir **Fase 1 Parte 3** — `docker-compose` con ClickHouse, `migrations/clickhouse/`, `packages/pipeline`. Verificado en disco 2026-08-04: **nada de eso existe todavía** (`docker-compose.yml` solo tiene `postgres` + `redis`; no hay `migrations/clickhouse/`; no hay `packages/pipeline/`).
- El único documento que contiene DDL ejecutable es **`docs/plan-ingesta-social.md` §3** (ocho tablas, §3.1–§3.8). Es lo que ese developer va a usar.
- **El `ORDER BY` de ClickHouse es inmutable.** CLAUDE.md lo marca como regla dura; ADR 24 lo usa como argumento decisivo (*«retrofitear no es refactor, es reconstruir y re-ingerir todo el plano analítico»*).
- Herwin es el **único consumidor** de esas tablas (Fase 2 lee `search.content_index`; Fase 4 lee los embeddings/centroides), pero **no es quien las escribe**. Contrato entre dos personas, con una de las partes ausente de la decisión.

Objetivo de la sesión: **dejar `docs/plan-ingesta-social.md` §3 en un estado en el que se pueda aplicar tal cual sin heredar deuda inmutable.** No es escribir el DDL — eso es del otro developer.

---

## 1. Hallazgo de proceso: §3 es un doc con desincronización conocida y no reparada

No se está descubriendo esto ahora. Del ledger COMPASS/SAGE (`.claude/compass-sage/ledger.md`, línea 25):

> `2026-07-20 | architect | principal-architect | doc reconciliation: fold zyte_request_meta into ADR 18 note + rewrite superseded brand-scoped note in plan-ingesta-social.md | failure | interrupted by session limit before completing; plan-ingesta-social.md STILL contradicts ADR 18 on disk — pending on team reset`

Esa reconciliación nunca se completó. Estado verificado en disco **hoy** (`grep`, no lectura de docs):

| Símbolo | En `plan-ingesta-social.md` | Debería, según ADR |
|---|---|---|
| `zyte_request_meta` | presente (L186) | ADR 22(b): renombrado a `transport_meta` |
| `source_class` | **0 ocurrencias** | ADR 22(b): campo del envelope v2 |
| `tenant_id` | **0 ocurrencias** | ADR 24: identificador de fundación |
| `payload_schema_version = 2` | describe v1 | ADR 22(b) |
| `crm.creator_centroids` | **0 ocurrencias** | `arquitectura.md` L185, ADR 9/11/12 |
| `ingestion.owned_metrics` | **0 ocurrencias** | parking lot: «frontera Fase 1/2» |

**Implicación de método para esta sesión:** `arquitectura.md` §6 (ADRs) es la ley; `plan-ingesta-social.md` §3 es un borrador anterior que sobrevivió sin reconciliar. Cualquier diferencia entre ambos se resuelve a favor del ADR, salvo que el ADR no cubra el caso — y entonces es decisión nueva que hay que tomar aquí.

---

## 2. Lo que NO hay que tocar (para no relitigar)

Verificado antes de escribir el brief. Estas decisiones están firmadas y son entrada, no debate:

- **ADR 24(c) — regla dual de keying.** Media ganada → `brand_id`, compartible entre tenants. Primera parte → `tenant_id`, nunca compartible. Explícitamente: ***`tenant_id` NO va en el prefijo de todos los `ORDER BY`***. Por tanto `ORDER BY (brand_id, ...)` en las tablas `ingestion.*` de media ganada **es correcto y no es deuda**. (El segundo-cerebro se equivocó en esto durante la sesión de enrutado y lo corrigió al verificar; se registra para que nadie lo re-litigue en la otra dirección.)
- **ADR 24(b)** — `brand_id` no se fusiona con `tenant_id`. Ejes ortogonales.
- **ADR 11** — una tabla/índice por `(modalidad, modelo, dim)`; `search.visual_embeddings` queda **diseñada-no-construida**.
- **ADR 9** — lookalike sobre ClickHouse nativo (`vector_similarity`/HNSW), índice sobre snapshot con swap atómico `EXCHANGE TABLES`.
- **ADR 12** — lookalike = fusión centroide de contenido + filtros de metadata.
- **ADR 18** — provenance y la economía «N marcas comparten un scrape» en la rama de media ganada.
- **ADR 22** — envelope v2, dos espacios de clave disjuntos, `content_signature` sin salt de tenant.
- El discriminador `content_type` **fuera** del `ORDER BY` de `ingestion.posts` (razonado en L175 contra `schema-pk-prioritize-filters`).

Existe la skill `clickhouse-best-practices` (31 reglas, obligatoria al revisar esquemas) y `clickhouse-architecture-advisor`. La sesión de 2026-07-19 ya citó `schema-types-lowcardinality`, `schema-pk-prioritize-filters`, `schema-json-when-to-use` — mismo estándar de citación aquí.

---

## 3. Las decisiones abiertas (el trabajo real)

### D1 — ¿`search.content_index` indexa también medio propio (Parte 4)?

`search.content_index` (§3.6) es hoy una tabla desnormalizada de fragmentos de media ganada: `caption|frame|transcript|comment`, con `ORDER BY (brand_id, content_type, posted_date, post_id, source_id)`.

La Fase 1 **Parte 4** introduce ingesta de primera parte (cuentas conectadas vía Meta). El parking lot registra `ingestion.owned_metrics` como *«frontera Fase 1/2, duro-bloqueado por la Parte 3»* — sin dueño y sin decisión.

Tensión: ADR 24(c) manda keying distinto para cada clase de dato. **Una sola tabla no puede ser a la vez brand-keyed compartible y tenant-keyed aislada.** Si el contenido de medio propio (captions de los propios reels, comentarios recibidos) acaba en `content_index` para que el listening lo vea junto al ganado, hay que decidir *ahora* si:

- (a) tablas separadas — `search.content_index` (ganado) + `search.owned_content_index` (propio, `tenant_id` líder), con la unión hecha en query; o
- (b) una tabla con `source_class` en el `ORDER BY` — pero entonces hay filas tenant-scoped en una tabla sin aislamiento estructural, que es justo lo que ADR 22(2) llama obligación de supresión dirigida, no mero riesgo; o
- (c) medio propio no entra nunca al índice de listening.

Nota de ADR 22(d): los hilos de DM son Postgres, no `ingestion.*`; su cara analítica sí es ClickHouse. Eso resuelve conversaciones, **no** resuelve el contenido publicado propio.

### D2 — Dónde aterrizan tema / intención / postura

Fase 2 promete «informes de sentiment y **temas**» (`README.md` §Fase 2). El esquema §3.6 solo tiene `sentiment LowCardinality(String) DEFAULT ''`. **No hay columna de tema, intención ni postura.** Con el esquema actual, "informes de temas" no es construible ni con la Parte 3 entregada.

La primitiva que lo produce es **P3-0** (Linear `QUA-24`): clasificador zero-shot multi-label sobre `bge-m3-zeroshot-v2.0`, que emite por fragmento un conjunto de labels + `detector_version` + umbral + `label_set_version` (regla dura de provenance, ADR 16). Está desbloqueada hoy (corre sobre fixtures de `packages/models`, no depende de Parte 3) y Herwin la va a construir después de esta sesión.

Decisión: ¿columnas en `content_index`? ¿tabla `signals.events` adelantada de Fase 3? ¿una tabla hija de labels? Multi-label sobre una tabla ya desnormalizada por fragmento tiene cardinalidad no trivial. **Lo que sea, debe caber sin cambiar el `ORDER BY` de §3.6, o cambiarlo ahora.**

### D3 — `search.embeddings` está desactualizada respecto a ADR 9/11/12 y §8

§3.7 dice literalmente `embedding Array(Float32), -- dim según modelo (ej. 384 o 768)` y `embedding_model LowCardinality(String)` — es decir, **una tabla mixta multi-modelo/multi-dim**, que es exactamente la alternativa que **ADR 11 rechazó** (*«un índice ANN exige dim fija»*).

Además:
- `arquitectura.md` §8 punto 2 propone **`bge-m3` a 1024-dim** (MIT) sustituyendo al tentativo MiniLM-384 — en estado `[PROPUESTO]`, con CLAUDE.md exigiendo golden-set antes de fijar checkpoint. Los `ej. 384 o 768` de §3.7 son de la era anterior.
- **`crm.creator_centroids` no existe en `plan-ingesta-social.md`**, pese a ser el activo real del lookalike (`arquitectura.md` L185–193: los vectores viven en la tabla hija, no en `crm.creators`, que churnea por upserts con TTL 24-72h y reconstruiría el HNSW en cada merge).
- ADR 9 (snapshot + `EXCHANGE TABLES`) no está reflejado en ningún DDL.

Aquí hay un **orden de operaciones** que decidir: ¿se congela ahora el DDL de embeddings con dim fija (y cuál), o se marca explícitamente *diseñada-no-construida* hasta que el golden-set cierre el checkpoint? La segunda opción es coherente con cómo ADR 11 trató `search.visual_embeddings`. Lo que **no** es aceptable es que el otro developer aplique §3.7 tal cual y deje una tabla mixta.

### D4 — Reconciliación pendiente de ADR 18 / ADR 22 en §3

El item que murió en 2026-07-20. `zyte_request_meta` → `transport_meta`, `payload_schema_version = 2`, `source_class`, y la nota brand-scoped superseded. Es higiene, no decisión — pero es la higiene que hace que el doc sea seguro de ejecutar.

---

## 4. Entregable esperado

1. **`docs/plan-ingesta-social.md` §3 actualizado** (español) — reconciliado con ADR 18/22/24, con las decisiones D1–D3 materializadas en el DDL y cada `ORDER BY` justificado contra `clickhouse-best-practices` con la regla citada.
2. **Una sección de contrato explícita** en ese mismo doc: qué tablas consume Fase 2, qué tablas consume Fase 4, y qué queda *diseñada-no-construida*. Es el documento que el otro developer y Herwin comparten.
3. **ADR nuevo si D1 o D3 exigen decisión no cubierta** — formato §6, estado `[PROPUESTO]`, para firma del fundador. No dar por aprobado nada que cambie una regla firmada.
4. **Fila en el ledger** (`.claude/compass-sage/ledger.md`) con el outcome, y cierre explícito del item de 2026-07-20 si se completa.

## 5. Reglas de la casa que aplican a esta sesión

- **Leer el filesystem, no los docs**, para afirmar qué existe. Es regla dura de CLAUDE.md y el caso de `revoke.py` está dejado a propósito como ejemplo.
- **No commitear ni pushear** sin que Herwin lo pida.
- **Flush incremental a disco** por sección completada. Cuatro muertes de sesión registradas en el ledger; los agentes que escribieron incrementalmente no perdieron nada. Ver skill `durable-findings`.
- **No ejecutar `uv sync` / `uv venv`** (trampa #2/#3 de CLAUDE.md). Esta sesión no debería necesitar tocar el venv en absoluto.
- Producto/docs en **español**; código y `CLAUDE.md` en inglés.
