# Organización de agentes ("squads") para Qualify

Este documento es el mapa de quién-es-quién entre los subagentes de Claude Code configurados en `.claude/agents/` y `.claude/commands/`. Es un documento vivo de organización interna del proyecto, no de producto — actualízalo cuando se cree, renombre o repropósito un agente o squad.

## Agente raíz: second-brain

**`qualify-second-brain`** (`.claude/agents/qualify-second-brain.md`) es el punto de entrada persistente para todo el proyecto. No reemplaza a los tres squads de abajo — coordina hacia ellos. Úsalo como agente de hilo principal (`claude --agent qualify-second-brain`) para cualquier sesión que no esté ya enfocada en un squad específico: preguntas de estado/contexto, decidir a qué squad enrutar un pedido, o delegar una pregunta puntual a un solo specialist sin levantar un squad completo.

## Squads (equipo lead + specialists, vía slash command)

| Squad | Slash command | Lead (hilo principal) | Specialists | Cuándo usarlo |
|---|---|---|---|---|
| Research | `/team-research` | `research-lead` | `principal-architect`, `data-scientist-fde`, `gtm-specialist` | Investigación de mercado, modelos, o arquitectura que aún no tiene una decisión firme — cualquier fase. |
| Handoff / PO | `/team-po` | `po-lead` | `product-owner`, `principal-architect`, `data-scientist-fde` | Convertir hallazgos de research en backlog ejecutable, con desafío de factibilidad y de fase. |
| Dev | `/team-dev` | `dev-lead` | `principal-architect`, `pipeline-engineer`, `data-scientist-fde`, `reflex-ui-engineer` (solo si el sprint toca `Qualify/`) | Implementación de código — hoy Fase 1 Parte 2/3 (scraper, ClickHouse/Celery) y el dashboard CRM. |

Cada lead nunca implementa mientras su squad trabaja — coordina, aprueba planes y sintetiza. Ningún squad hace commit/push sin pedirlo el usuario.

## Specialists y sus skills

Cada specialist tiene una sección "Skills at your disposal" en su archivo de agente que apunta a skills instalados en `.claude/skills/` — invócalos vía la tool `Skill`, no de memoria.

| Specialist | Dueño de (paths) | Fase(s) | Skills clave asignadas |
|---|---|---|---|
| `principal-architect` | `docs/`, `CLAUDE.md` | Todas — diseña y audita | `develop-adr`, `architecture-patterns`, `improve-codebase-architecture`, `clickhouse-architecture-advisor`, `clickhouse-best-practices` |
| `pipeline-engineer` | `packages/scraper/`, `packages/pipeline/`, `packages/shared/`, `docker-compose.yml`, `migrations/` | Fase 1 Parte 2/3 | `scrape`, `scrape-analyze-page`, `scrape-spec`/`scrape-define`, `scrape-create-spider`, `scrape-zyte-login` (plugin `zyte-web-data`), `clickhousectl-local-dev`, `clickhouse-best-practices` |
| `data-scientist-fde` | `packages/models/` | Fase 1 Parte 1 (y eval continua) | `model-evaluation`, `eval-driven-dev`, `exploratory-data-analysis`, `hf-cli` |
| `gtm-specialist` | `docs/*research*`, `docs/*alternativas*` | Investigación de mercado — todas las fases | `competitor-profiling`, `customer-research`, `positioning`, `pricing` |
| `product-owner` | `docs/backlog-*.md` | Conversión research → backlog | — |
| `reflex-ui-engineer` | `Qualify/` (app Reflex) | Dashboard CRM — hoy scaffold Fase 1, crecerá en Fase 2 (dashboards), Fase 4 (CRM de creators), Fase 6 | `reflex-docs`, `setup-python-env`, `reflex-process-management` (obligatorios, ver `CLAUDE.md` §Agents), `dataviz` |

### Agentes de utilidad (fuera de los squads de producción)

- `linkedin-bitacora` — ghostwriter de marca personal de Herwin. Genera un post diario en inglés (días de semana) sobre sus aprendizajes como FDE + CTA suave de coaching neurocientífico / transformación de carrera, y lo entrega como borrador de Gmail a `hlrd1993+qualify@gmail.com`. Vive solo en `bitacora/` y su propio archivo; **no toca producto, docs ni el org de squads**. Regla dura: denylist anti-filtración (nunca nombre de producto, competidores, vendors/costos, modelos, esquema de datos ni roadmap; nunca cita commits). Automatizado vía routine cloud `trig_01SHp5v6tsxFtpRjazgF49Cq` (`0 11 * * 1-5` UTC = 8:00 Montevideo). No es un cuarto squad ni parte del pipeline de Qualify.

## Mapa de fases → quién construye qué

Ver `CLAUDE.md` "Roadmap phase map" para el detalle completo; resumen de propiedad:

1. **Fase 1** (actual) — ingestión/enriquecimiento: `pipeline-engineer` (Parte 2/3) + `data-scientist-fde` (Parte 1, cascada multimodal) + `reflex-ui-engineer` (scaffold del dashboard, sin conectar aún a datos reales) + `principal-architect` supervisando ClickHouse/queues.
2. **Fase 2** — listening + AI insights: `data-scientist-fde` (reporting/resúmenes LLM) + `reflex-ui-engineer` (dashboards en tiempo real) + `principal-architect` (diseño de `search.content_index` consumption).
3. **Fase 3** — señales + visual listening avanzado: `data-scientist-fde` (detectores tipados) + `principal-architect` (`signals.events` con provenance) — sin specialist dedicado aún; se cubre desde `/team-research` hasta que haya volumen de trabajo propio.
4. **Fase 4** — creator discovery + CRM: `data-scientist-fde` (embeddings/lookalike) + `reflex-ui-engineer` (UI de CRM) + `pipeline-engineer` (contact waterfall) — sin specialist de "creator scoring" dedicado aún.
5. **Fase 5** — activación GTM: mayormente compra de vendors (`gtm-specialist` ya cubrió la decisión) — falta specialist de integración de outbound cuando arranque esta fase.
6. **Fase 6** — hardening de plataforma: sin specialist dedicado; candidato futuro (`platform-engineer` para multi-tenancy/observabilidad) cuando el trabajo tenga volumen propio.

No crear specialists para fases 3/5/6 todavía — el squad de research (`/team-research`) cubre el trabajo exploratorio hasta que exista suficiente volumen de tareas repetibles para justificar un agente dedicado (mismo criterio que se usó para crear `reflex-ui-engineer`).

## COMPASS y SAGE: ciclo de vida de la librería de skills

La organización de agentes no es estática — evoluciona con evidencia, mediante dos meta-protocolos instalados como skills de proyecto y operados principalmente por `qualify-second-brain`:

- **COMPASS** (`.claude/skills/compass-skill-synthesis/`) — *síntesis cooperativa de skills*, adaptado del paper de Li, Zhao & Pajarinen (arXiv:2502.10148): cuando un agente o squad detecta un hueco de capacidad (ningún skill/specialist lo cubre, o el mismo procedimiento se improvisa ≥2 veces según el ledger), se sintetiza un skill nuevo (`SKILL.md` + Python ejecutable cuando el procedimiento es determinista) y se asigna al agente mejor calificado por dominio — no al que descubrió el hueco. Ciclo closed-loop del paper: el asignado lo prueba en la tarea que originó el hueco y escribe una **auto-reflexión** (qué acertó, qué estaba ambiguo) que el sintetizador incorpora al skill antes de cerrarlo. También soporta **bootstrapping**: destilar skills desde procedimientos ya improvisados con éxito en sesiones pasadas (nuestras "demostraciones expertas"), sin esperar la repetición. Skills que codifican decisiones de arquitectura requieren visto bueno de `principal-architect`.
- **SAGE** (`.claude/skills/sage-skill-evolution/`) — *auto-mejora dirigida por resultados*: cada lead registra los outcomes de las tareas de su squad (`success`/`partial`/`failure`/`improvised`) en `.claude/compass-sage/ledger.md`. Ante fallos repetidos (≥2 del mismo agente en el mismo tipo de subtarea → **rebalancear** la carga a otro agente; ≥2 entre agentes distintos con el mismo skill → **reescribir** ese `SKILL.md`), el sistema ajusta routing, skills o charters de agentes — una variable a la vez, siempre citando las entradas del ledger que lo motivan. No es RL literal (no hay GRPO a nivel harness); es el mismo objetivo — maximizar el ratio de éxito por subtarea — optimizado sobre los artefactos editables: instrucciones de skills, charters y enrutamiento.

**Invariantes protegidos** (nunca se "evolucionan"): las reglas duras de `CLAUDE.md` (provenance, `ORDER BY` inmutable, dos planos de datos, buy-vs-build, idempotencia), los límites de file ownership de cada squad, y la regla de no commit/push. Si un patrón de fallos parece exigir cambiar uno de estos, es una decisión del usuario, no un rewrite de SAGE.
