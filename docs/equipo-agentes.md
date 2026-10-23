# Organización de agentes y skills de Qualify

Mapa de los subagentes de Claude Code (`.claude/agents/`) y de las skills propias de Qualify (`.claude/skills/qualify-*`). Documento vivo de organización interna, no de producto.

**Actualizado 2026-10-22** (PR #214, m-24840372).

## El modelo: skills primero, pocos subagentes

Siguiendo la guía actual de Anthropic (revisada el 2026-10-22):

- **Las skills son la unidad principal.** Empaquetan procedimientos y conocimiento y cargan solo cuando aplican; los antiguos comandos de `.claude/commands/` ya son skills. Todo lo propio de Qualify vive en skills `qualify-*`.
- **Los subagentes existen para aislar contexto y elegir modelo**, no como personajes. Sirven cuando el trabajo llenaría la conversación principal de código, logs o archivos: el subagente lo hace en su propia ventana y devuelve un resumen. Cada subagente **precarga** sus skills (`skills:` en su frontmatter).
- **`CLAUDE.md` se queda corto** (se carga entero en cada sesión; Anthropic recomienda menos de 200 líneas). Lo largo se mudó a `qualify-pr`, `qualify-dev-env` y `qualify-history`.
- **Los equipos de agentes experimentales están apagados** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` fuera de `.claude/settings.json`): cuestan bastante más tokens que una sesión normal, no aplican las skills de los agentes y los squads no se usaban desde agosto. Los squads ahora son skills que coordinan subagentes normales.

**Regla del fundador (2026-10-22): el código y las tareas con muchos logs SIEMPRE van a un subagente**, en Opus 5.5 para escribir código o en el modelo que mejor encaje para leer logs o buscar. El hilo principal coordina, decide y resume (`qualify-lead`).

## Subagentes (9)

| Agente | Modelo | Dueño de (rutas) | Skills precargadas |
|---|---|---|---|
| `backend-engineer` | opus | `packages/api/` (salvo creative/catalog/stock/canva), `packages/shared/`, `packages/scraper/`, `migrations/postgres/` (todas) | context, pr, dev-env, migration |
| `creative-engineer` | opus | `packages/creative/`, `packages/render/`, `qualify_api.{creative,catalog,stock,canva}` | context, pr, dev-env, copy-es, measure |
| `reflex-ui-engineer` | opus | `Qualify/`, `assets/`, `rxconfig.py`, E2E | context, pr, dev-env, copy-es |
| `platform-engineer` | opus | `deploy/`, `.github/`, `infra/`, `docker-compose*.yml`, `justfile` | context, pr, dev-env, prod-ops |
| `data-scientist-fde` | opus | `packages/models/`, `packages/api/evals/`, `docs/modelos-generativos/` | context, pr, dev-env, measure |
| `principal-architect` | opus | `docs/arquitectura.md`, `docs/adr-*.md`, `CLAUDE.md` | context, pr, migration, history |
| `market-analyst` | sonnet | Oferta: `docs/*research*`, `*alternativas*`, `ingenieria-inversa-*`, `dolores-*`, `apis-*`, `costos-*`, `comparativa-*` · Vector: `docs/oportunidades-mercado-*.md` · Demanda: `docs/demanda-ventas-*.md` | context |
| `product-owner` | opus | `docs/backlog-*.md`, `docs/epica-*.md`, tickets de Meegle (Features, Issues, Altas) | context, backlog, copy-es, meegle-ticket, meegle, meegle-altas, lark-admin |
| `ux-designer` | opus | `docs/perfil-cliente-pyme.md`, `docs/ux-*.md`, skill `qualify-ux`; revisión de experiencia en `.github/workflows/ux-review.yml` (solo sugiere, no escribe código de la app) | context, ux, copy-es, design:user-research, design:design-critique, design:ux-copy, design:accessibility-review |

Todos precargan además `durable-findings`. `product-owner` es dueño de los tickets de Meegle y de `docs/backlog-*.md` / `docs/epica-*.md` (vía `qualify-backlog`); el hilo principal le delega y corre el desafío del arquitecto y datasci.

## Skills propias de Qualify

| Skill | Para qué | Quién la usa |
|---|---|---|
| `qualify-context` | El negocio, los clientes, la app módulo por módulo, decisiones firmadas, reglas de la casa | Todos (precargada) |
| `qualify-lead` | Enrutar a subagentes y modelos, briefs, coordinar sin implementar, entregar, estado | Hilo principal |
| `qualify-pr` | Ticket → rama → checks → PR → nunca mergear; tabla de CI; presupuesto de Actions | Todos |
| `qualify-dev-env` | Recetas `just`, tests, trampas del venv, workers que actúan de verdad | Ingenieros |
| `qualify-migration` | Revisiones Alembic con RLS, numeración, reversibilidad | backend, architect |
| `qualify-copy-es` | Textos para clientes en español sin anglicismos | creative, UI, ux |
| `qualify-ux` | Lista de chequeo de experiencia: beneficios en vez de funcionalidades, palabras prohibidas, pasos cortos por dominio, accesibilidad y celular, cómo reportar en un PR | ux, UI |
| `qualify-measure` | Golden sets, evals, costo, documentar cada prueba de modelo | datasci, creative |
| `qualify-prod-ops` | Producción, despliegues, secretos, incidentes | platform |
| `qualify-backlog` | De evidencia a historias y tickets | Hilo principal |
| `qualify-lark-admin` | Ítems y configuración de Meegle, administración de Lark: MCP, CLIs oficiales (`meegle`, `lark-cli` y sus skills) o Chrome para las consolas | Hilo principal, platform |
| `qualify-history` | Visión original, pipeline de earned media, mapa de fases, decisiones pasadas | architect |
| `qualify-team-dev` / `qualify-team-po` / `qualify-team-research` | Squads que dispara el fundador (`/qualify-team-…`) | Hilo principal |

También del proyecto: `meegle-ticket`, `meegle-altas`, `durable-findings`, `compass-skill-synthesis`, `sage-skill-evolution`, y skills genéricas (`develop-adr`, `eval-driven-dev`, `competitor-profiling`, …). Las skills de ClickHouse se desenlazaron de `.claude/skills/` (siguen en `.agents/skills/` para cuando se cruce el umbral de ADR 31).

## Qué cambió el 2026-10-22

| Antes | Ahora |
|---|---|
| 13 agentes congelados en agosto (ClickHouse, Linear, repo sin implementar) | Contexto real en `qualify-context` |
| `qualify-second-brain`, `dev-lead`, `po-lead`, `research-lead`, `product-owner` | Skills `qualify-lead` y `qualify-backlog` en el hilo principal |
| `gtm-specialist`, `market-opportunity-analyst`, `sales-consultant` | `market-analyst` con tres modos (oferta, vector, demanda) |
| `pipeline-engineer` | `backend-engineer`; nuevos `creative-engineer` y `platform-engineer` |
| `/team-dev`, `/team-po`, `/team-research` en `.claude/commands/` sobre equipos experimentales | Skills `qualify-team-*` con subagentes normales |
| `CLAUDE.md` de 355 líneas | ~160 líneas + `qualify-pr`, `qualify-dev-env`, `qualify-history` |
| `linkedin-bitacora` | Eliminado (rutina en la nube apagada) |

### Los tres modos del mercado

Siguen siendo **consultores externos**: miran el mercado y devuelven oportunidades y requisitos de producto, no el marketing ni las ventas de Qualify. **Oferta** documenta el campo con fuente y fecha; **vector** escribe tesis de oportunidad con adyacencia razonada contra el disco, falsador y validación más barata; **demanda** ensaya ventas como diagnóstico y produce **hipótesis, nunca hallazgos** (no puede inventar un dolor; todo `[H]`, o `[V]` si el fundador confirma que un prospecto real lo dijo). `qualify-team-research` sintetiza la demanda en una sección aparte.

## COMPASS y SAGE: ciclo de vida de la librería de skills

La organización de agentes no es estática — evoluciona con evidencia, mediante dos meta-protocolos instalados como skills de proyecto y operados desde el hilo principal con la skill `qualify-lead`:

- **COMPASS** (`.claude/skills/compass-skill-synthesis/`) — *síntesis cooperativa de skills*, adaptado del paper de Li, Zhao & Pajarinen (arXiv:2502.10148): cuando un agente o squad detecta un hueco de capacidad (ningún skill/specialist lo cubre, o el mismo procedimiento se improvisa ≥2 veces según el ledger), se sintetiza un skill nuevo (`SKILL.md` + Python ejecutable cuando el procedimiento es determinista) y se asigna al agente mejor calificado por dominio — no al que descubrió el hueco. Ciclo closed-loop del paper: el asignado lo prueba en la tarea que originó el hueco y escribe una **auto-reflexión** (qué acertó, qué estaba ambiguo) que el sintetizador incorpora al skill antes de cerrarlo. También soporta **bootstrapping**: destilar skills desde procedimientos ya improvisados con éxito en sesiones pasadas (nuestras "demostraciones expertas"), sin esperar la repetición. Skills que codifican decisiones de arquitectura requieren visto bueno de `principal-architect`.
- **SAGE** (`.claude/skills/sage-skill-evolution/`) — *auto-mejora dirigida por resultados*, adaptado del paper de Peng et al. (arXiv:2603.15255): cada lead registra los outcomes de las tareas de su squad (`success`/`partial`/`failure`/`improvised`) en `.claude/compass-sage/ledger.md`. Ante fallos repetidos (≥2 del mismo agente en el mismo tipo de subtarea → **rebalancear** la carga a otro agente; ≥2 entre agentes distintos con el mismo skill → **reescribir** ese `SKILL.md`), el sistema ajusta routing, skills o charters de agentes — una variable a la vez, siempre citando las entradas del ledger que lo motivan. No es RL literal (no hay GRPO a nivel harness); es el mismo objetivo — maximizar el ratio de éxito por subtarea — optimizado sobre los artefactos editables: instrucciones de skills, charters y enrutamiento.

**Invariantes protegidos** (nunca se "evolucionan"): las reglas duras de `CLAUDE.md` y de la skill `qualify-context` §3 (aislamiento por tenant con RLS, provenance, buy-vs-build, idempotencia, respuestas asistidas y nunca autónomas), los límites de file ownership de cada squad, y la regla de entrega (PR sí, merge nunca). Si un patrón de fallos parece exigir cambiar uno de estos, es una decisión del usuario, no un rewrite de SAGE.

### Procedencia de los conceptos (papers de origen)

Ambos meta-protocolos son **adaptaciones, no implementaciones literales**: los papers optimizan políticas de RL o pesos de modelos, mientras que aquí el sustrato optimizable son artefactos editables (instrucciones de `SKILL.md`, charters de agentes, enrutamiento). Se documenta aquí para que la trazabilidad no dependa de la memoria de una sesión.

| Protocolo | Paper de origen | Qué se tomó | Qué **no** se tomó |
|---|---|---|---|
| **COMPASS** (síntesis de skills) | Zhiyuan Li, Wenshuai Zhao, Joni Pajarinen — *Closed-Loop Vision-Language Planning for Multi-Agent Coordination*, [arXiv:2502.10148](https://arxiv.org/abs/2502.10148) (v1 2025-02-14, rev. v3 2026-05-05) | La **librería de skills** como estrategias reutilizables generadas y refinadas dinámicamente; el **bootstrapping desde demostraciones expertas**; el **ciclo closed-loop** (probar el skill en la tarea que originó el hueco y refinarlo con la auto-reflexión del asignado). | El componente vision-language (VLM sobre observaciones parciales) y el protocolo de comunicación multi-hop: aquí no hay percepción visual ni agentes parcialmente observables. |
| **SAGE** (evolución de skills) | Yulin Peng, Xinxin Zhu, Chenxing Wei, Nianbo Zeng, Leilei Wang, Ying Tiffany He, F. Richard Yu — *SAGE: Multi-Agent Self-Evolution for LLM Reasoning*, [arXiv:2603.15255](https://arxiv.org/abs/2603.15255) (2026-03-16, rev. 2026-03-17) | La **co-evolución multi-agente en bucle cerrado** desde un backbone compartido y, sobre todo, el **control de calidad anti-degradación** (el rol de Critic evitando *curriculum drift*) → aquí se materializa como el ledger de outcomes, la regla de "una variable a la vez" y los invariantes protegidos de arriba. | El entrenamiento con RLVR/GRPO y los roles Challenger/Planner/Solver/Critic como agentes de razonamiento: nuestro SAGE no entrena pesos, reescribe instrucciones y enrutamiento. |

> **Nota de colisión de acrónimo (verificada 2026-07-20).** Existe un paper distinto que también se llama COMPASS — Meaden, Jarosz, Jodłowski & Melnik, *COMPASS: A Multi-Dimensional Benchmark for Evaluating Code Generation in Large Language Models*, [arXiv:2508.13757](https://arxiv.org/abs/2508.13757) (2025-08-19) — que es un **benchmark de generación de código** en tres ejes (corrección, eficiencia algorítmica, calidad/mantenibilidad) sobre 50 problemas de Codility con ~400K envíos humanos como referencia. **No es la fuente del protocolo COMPASS de este repo**: comparte el acrónimo, no el contenido. Se deja registrado explícitamente para que no se cite por error como origen del skill de síntesis. (Su tesis —que un modelo con alta corrección no necesariamente produce código eficiente ni mantenible— es de todos modos relevante como criterio de revisión de código, pero eso es una decisión de calidad, no la procedencia de COMPASS.)
