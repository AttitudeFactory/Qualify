# Organización de agentes para Qualify

Mapa de quién-es-quién entre los subagentes de Claude Code en `.claude/agents/` y los playbooks de squad en `.claude/commands/`. Documento vivo de organización interna, no de producto: se actualiza cuando se crea, fusiona o cambia un agente.

**Actualizado 2026-10-22.** Todos los agentes leen primero [`.claude/agent-context.md`](../.claude/agent-context.md): el estado real del negocio y de la aplicación, las decisiones que no se deshacen y las reglas de la casa. Cuando cambie el negocio se actualiza ese archivo, no cada agente. Su dueño es `qualify-lead`.

## Nueve agentes (antes catorce)

Consolidación del 2026-10-22, a pedido del fundador. El ledger de squads (`.claude/compass-sage/ledger.md`) no registra trabajo desde el 2026-08-07: el trabajo real pasa en sesiones directas y PRs, y cada agente extra es un traspaso que pierde contexto. Se fusionó lo que se solapaba y se mantuvo lo que corresponde a un área con volumen real.

| Antes | Ahora | Por qué |
|---|---|---|
| `qualify-second-brain`, `dev-lead`, `po-lead`, `research-lead` | **`qualify-lead`** | Compartían ~80 % de la disciplina (delegar, no implementar, no re-spawnear, durabilidad, SAGE). Lo propio de cada squad ya vivía en su comando. |
| `gtm-specialist`, `market-opportunity-analyst`, `sales-consultant` | **`market-analyst`** con tres modos (oferta, vector, demanda) | Poco volumen; los tres ejes se conservan como modos con sus reglas, y `/team-research` puede lanzar una instancia por modo para que se contradigan. |
| `pipeline-engineer` | **`backend-engineer`** | Apuntaba a un pipeline Celery/ClickHouse que nunca se construyó (ADR 31). |
| — | **`creative-engineer`**, **`platform-engineer`** | El generador y la operación acumularon decenas de PRs sin dueño. |
| `linkedin-bitacora` | eliminado | Pedido del fundador. |

**No se atomiza más.** Partir un área en agentes más chicos multiplica traspasos sin agregar capacidad; el acotamiento se hace con la propiedad de rutas, no con más agentes.

## Regla de entrega: todo termina en un PR

Decisión del fundador (2026-10-22): toda entrega que cambia archivos termina en un PR con su ticket de Meegle (`<tipo>/m-<id>-<slug>`, título con `(m-<id>)`, descripción con `Resolves m-<id>`). En un squad, **solo el lead abre el PR**; los teammates dejan los cambios en el árbol. **Ningún agente mergea**: el merge es del fundador, con `just merge` y CI en verde. Nadie publica, envía ni despliega de verdad sin su visto bueno.

## El lead y los squads

**`qualify-lead`** (opus, hilo principal: `claude --agent qualify-lead`) es el punto de entrada: responde estado (git, PRs abiertos, Meegle), delega lo de un área a un solo specialist, y cuando hace falta un squad, lo dirige siguiendo el playbook del comando. Regla: el equipo más chico que resuelva — un specialist antes que un squad.

| Squad | Comando | Equipo | Cuándo |
|---|---|---|---|
| Dev | `/team-dev` | `principal-architect` si hay migración, contrato, vendor o permiso de Meta + solo los ingenieros cuyas rutas toca el objetivo | Implementar un épico o varios tickets de Meegle que cruzan áreas. Un objetivo de un área va directo a su ingeniero. |
| Handoff | `/team-po` | `product-owner` + `principal-architect` (+ `data-scientist-fde` si hay IA) | Convertir investigación, pedidos de clientes o decisiones en tickets desafiados y listos. |
| Research | `/team-research` | Lo que pida el objetivo: `principal-architect`, `data-scientist-fde`, y `market-analyst` × 1-3 modos | Investigar mercado, vendors, modelos o arquitectura sin decisión firme. |

## Specialists

| Agente | Dueño de (rutas) | Qué cubre |
|---|---|---|
| `principal-architect` | `docs/arquitectura.md`, `docs/adr-*.md`, `CLAUDE.md` | Límites de módulos, esquema y RLS, restricciones de Meta, buy-vs-build, ADRs, auditoría docs↔código |
| `product-owner` | Tickets de Meegle, `docs/backlog-*.md`, `docs/epica-*.md` | Historias con criterios verificables a partir de evidencia |
| `backend-engineer` | `packages/api/` (salvo creative/catalog/stock/canva), `packages/shared/`, `packages/scraper/`, `migrations/postgres/` (todas) | Cuentas conectadas, publicación, planificador, interacciones, conversaciones, WhatsApp, seguimientos, referentes, auth, Meegle, workers |
| `creative-engineer` | `packages/creative/`, `packages/render/`, `qualify_api.{creative,catalog,stock,canva}` | Brand Kit, catálogo, Crear pieza, proveedores de generación, tabla de precios, Remotion, retención de piezas |
| `reflex-ui-engineer` | `Qualify/`, `assets/`, `rxconfig.py`, E2E | Las pantallas de los clientes, design system, textos en español |
| `platform-engineer` | `deploy/`, `.github/`, `infra/`, `docker-compose*.yml`, `justfile` | Producción en Hetzner, proxy de entrada, CI/CD y minutos, secretos, respaldos, observabilidad |
| `data-scientist-fde` | `packages/models/`, `packages/api/evals/`, `docs/modelos-generativos/` | Golden sets, evals de prompts y modelos, costo por pieza |
| `market-analyst` | Oferta: `docs/*research*`, `*alternativas*`, `ingenieria-inversa-*`, `dolores-*`, `apis-*`, `costos-*`, `comparativa-*` · Vector: `docs/oportunidades-mercado-*.md` · Demanda: `docs/demanda-ventas-*.md` | Mercado como consultor externo, en el modo que nombre el brief |

Los skills de cada agente están en su archivo; se invocan con la tool `Skill`, no de memoria.

### Los tres modos del mercado (antes tres agentes)

Añadidos como agentes el 2026-07-29 y fusionados como modos el 2026-10-22. Siguen siendo **consultores externos**: miran el mercado y devuelven oportunidades y requisitos de producto, no el marketing ni las ventas de Qualify (eso no tiene dueño, por decisión del fundador). Las reglas que justificaban separarlos viajan dentro del agente:

- **Oferta** documenta el campo tal como está, con fuente y fecha, y es el proveedor de evidencia de los otros dos modos.
- **Vector** escribe tesis de oportunidad con adyacencia razonada **contra el disco**, falsador y validación más barata. Nunca inventa un tamaño de mercado.
- **Demanda** ensaya ventas como diagnóstico y produce **hipótesis, nunca hallazgos**: no puede inventar un dolor, todo va `[H]` (o `[V]` si el fundador confirma que un prospecto real lo dijo), y un requisito entra al backlog solo tras validarlo un prospecto real. El lead lo sintetiza en una sección aparte.

### Skill transversal: `durable-findings`

Aplica a todos los agentes: volcar a disco por secciones en vez de bufferear un informe final, y un hallazgo que cambia los supuestos de otro agente lo escribe su descubridor. Sintetizado vía COMPASS el 2026-07-26 tras cuatro pérdidas de trabajo por sesiones cortadas por límite de gasto. Mantenimiento: `qualify-lead`.

## COMPASS y SAGE: ciclo de vida de la librería de skills

La organización de agentes no es estática — evoluciona con evidencia, mediante dos meta-protocolos instalados como skills de proyecto y operados principalmente por `qualify-lead`:

- **COMPASS** (`.claude/skills/compass-skill-synthesis/`) — *síntesis cooperativa de skills*, adaptado del paper de Li, Zhao & Pajarinen (arXiv:2502.10148): cuando un agente o squad detecta un hueco de capacidad (ningún skill/specialist lo cubre, o el mismo procedimiento se improvisa ≥2 veces según el ledger), se sintetiza un skill nuevo (`SKILL.md` + Python ejecutable cuando el procedimiento es determinista) y se asigna al agente mejor calificado por dominio — no al que descubrió el hueco. Ciclo closed-loop del paper: el asignado lo prueba en la tarea que originó el hueco y escribe una **auto-reflexión** (qué acertó, qué estaba ambiguo) que el sintetizador incorpora al skill antes de cerrarlo. También soporta **bootstrapping**: destilar skills desde procedimientos ya improvisados con éxito en sesiones pasadas (nuestras "demostraciones expertas"), sin esperar la repetición. Skills que codifican decisiones de arquitectura requieren visto bueno de `principal-architect`.
- **SAGE** (`.claude/skills/sage-skill-evolution/`) — *auto-mejora dirigida por resultados*, adaptado del paper de Peng et al. (arXiv:2603.15255): cada lead registra los outcomes de las tareas de su squad (`success`/`partial`/`failure`/`improvised`) en `.claude/compass-sage/ledger.md`. Ante fallos repetidos (≥2 del mismo agente en el mismo tipo de subtarea → **rebalancear** la carga a otro agente; ≥2 entre agentes distintos con el mismo skill → **reescribir** ese `SKILL.md`), el sistema ajusta routing, skills o charters de agentes — una variable a la vez, siempre citando las entradas del ledger que lo motivan. No es RL literal (no hay GRPO a nivel harness); es el mismo objetivo — maximizar el ratio de éxito por subtarea — optimizado sobre los artefactos editables: instrucciones de skills, charters y enrutamiento.

**Invariantes protegidos** (nunca se "evolucionan"): las reglas duras de `CLAUDE.md` y de `.claude/agent-context.md` §3 (aislamiento por tenant con RLS, provenance, buy-vs-build, idempotencia, respuestas asistidas y nunca autónomas), los límites de file ownership de cada squad, y la regla de entrega (PR sí, merge nunca). Si un patrón de fallos parece exigir cambiar uno de estos, es una decisión del usuario, no un rewrite de SAGE.

### Procedencia de los conceptos (papers de origen)

Ambos meta-protocolos son **adaptaciones, no implementaciones literales**: los papers optimizan políticas de RL o pesos de modelos, mientras que aquí el sustrato optimizable son artefactos editables (instrucciones de `SKILL.md`, charters de agentes, enrutamiento). Se documenta aquí para que la trazabilidad no dependa de la memoria de una sesión.

| Protocolo | Paper de origen | Qué se tomó | Qué **no** se tomó |
|---|---|---|---|
| **COMPASS** (síntesis de skills) | Zhiyuan Li, Wenshuai Zhao, Joni Pajarinen — *Closed-Loop Vision-Language Planning for Multi-Agent Coordination*, [arXiv:2502.10148](https://arxiv.org/abs/2502.10148) (v1 2025-02-14, rev. v3 2026-05-05) | La **librería de skills** como estrategias reutilizables generadas y refinadas dinámicamente; el **bootstrapping desde demostraciones expertas**; el **ciclo closed-loop** (probar el skill en la tarea que originó el hueco y refinarlo con la auto-reflexión del asignado). | El componente vision-language (VLM sobre observaciones parciales) y el protocolo de comunicación multi-hop: aquí no hay percepción visual ni agentes parcialmente observables. |
| **SAGE** (evolución de skills) | Yulin Peng, Xinxin Zhu, Chenxing Wei, Nianbo Zeng, Leilei Wang, Ying Tiffany He, F. Richard Yu — *SAGE: Multi-Agent Self-Evolution for LLM Reasoning*, [arXiv:2603.15255](https://arxiv.org/abs/2603.15255) (2026-03-16, rev. 2026-03-17) | La **co-evolución multi-agente en bucle cerrado** desde un backbone compartido y, sobre todo, el **control de calidad anti-degradación** (el rol de Critic evitando *curriculum drift*) → aquí se materializa como el ledger de outcomes, la regla de "una variable a la vez" y los invariantes protegidos de arriba. | El entrenamiento con RLVR/GRPO y los roles Challenger/Planner/Solver/Critic como agentes de razonamiento: nuestro SAGE no entrena pesos, reescribe instrucciones y enrutamiento. |

> **Nota de colisión de acrónimo (verificada 2026-07-20).** Existe un paper distinto que también se llama COMPASS — Meaden, Jarosz, Jodłowski & Melnik, *COMPASS: A Multi-Dimensional Benchmark for Evaluating Code Generation in Large Language Models*, [arXiv:2508.13757](https://arxiv.org/abs/2508.13757) (2025-08-19) — que es un **benchmark de generación de código** en tres ejes (corrección, eficiencia algorítmica, calidad/mantenibilidad) sobre 50 problemas de Codility con ~400K envíos humanos como referencia. **No es la fuente del protocolo COMPASS de este repo**: comparte el acrónimo, no el contenido. Se deja registrado explícitamente para que no se cite por error como origen del skill de síntesis. (Su tesis —que un modelo con alta corrección no necesariamente produce código eficiente ni mantenible— es de todos modos relevante como criterio de revisión de código, pero eso es una decisión de calidad, no la procedencia de COMPASS.)
