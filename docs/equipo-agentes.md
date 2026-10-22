# Organización de agentes ("squads") para Qualify

Este documento es el mapa de quién-es-quién entre los subagentes de Claude Code configurados en `.claude/agents/` y `.claude/commands/`. Es un documento vivo de organización interna del proyecto, no de producto — actualízalo cuando se cree, renombre o repropósito un agente o squad.

**Actualizado 2026-10-22.** Todos los agentes leen primero [`.claude/agent-context.md`](../.claude/agent-context.md): el estado real del negocio y de la aplicación, las decisiones que no se deshacen y las reglas de la casa (PR con ticket de Meegle, `uv`, textos para clientes en español). Cuando cambie el negocio se actualiza ese archivo, no los quince agentes. Su dueño es `qualify-second-brain`.

## Agente raíz: second-brain

**`qualify-second-brain`** (`.claude/agents/qualify-second-brain.md`) es el punto de entrada persistente para todo el proyecto. No reemplaza a los squads — coordina hacia ellos. Úsalo como agente de hilo principal (`claude --agent qualify-second-brain`) para cualquier sesión que no esté ya enfocada en un squad: preguntas de estado (lee `git log`, los PRs abiertos y la cola de Meegle), decidir a quién enrutar un pedido, o delegar a un solo specialist.

## Regla de entrega: todo termina en un PR

Decisión del fundador (2026-10-22): **toda entrega de un agente que cambia archivos termina en un PR** con su ticket de Meegle (`<tipo>/m-<id>-<slug>`, título con `(m-<id>)`, descripción con `Resolves m-<id>`). En un squad, **solo el lead abre el PR**; los teammates dejan los cambios en el árbol. **Ningún agente mergea**: el merge es del fundador, con `just merge` y CI en verde. Ningún agente publica, envía ni despliega de verdad sin su visto bueno.

## Squads (lead + specialists, vía slash command)

| Squad | Slash command | Lead (hilo principal) | Specialists | Cuándo usarlo |
|---|---|---|---|---|
| Research | `/team-research` | `research-lead` | `principal-architect`, `data-scientist-fde`, `gtm-specialist`, + `market-opportunity-analyst` y `sales-consultant` (solo si el objetivo es de mercado) | Investigación de mercado, vendors, modelos o arquitectura que aún no tiene una decisión firme. |
| Handoff / PO | `/team-po` | `po-lead` | `product-owner`, `principal-architect`, `data-scientist-fde` | Convertir investigación, pedidos de clientes o decisiones del fundador en tickets de Meegle listos para construir. |
| Dev | `/team-dev` | `dev-lead` | `principal-architect` siempre; `backend-engineer`, `creative-engineer`, `reflex-ui-engineer`, `platform-engineer`, `data-scientist-fde` solo si el objetivo toca sus rutas | Implementar un épico o un conjunto de tickets de Meegle. |

Cada lead nunca implementa mientras su squad trabaja — coordina, aprueba planes, abre el PR y sintetiza.

## Specialists y sus skills

Cada specialist tiene una sección de skills en su archivo de agente — invócalos vía la tool `Skill`, no de memoria.

| Specialist | Dueño de (paths) | Qué cubre | Skills clave |
|---|---|---|---|
| `principal-architect` | `docs/arquitectura.md`, `docs/adr-*.md`, `CLAUDE.md` | Límites de módulos, esquema y RLS, restricciones de Meta, buy-vs-build, ADRs, auditoría docs↔código | `develop-adr`, `architecture-patterns`, `engineering:system-design`, `security-review` |
| `backend-engineer` *(antes `pipeline-engineer`, renombrado 2026-10-22)* | `packages/api/` (salvo creative/catalog/stock/canva), `packages/shared/`, `packages/scraper/`, `migrations/postgres/` (todas las revisiones) | Cuentas conectadas, publicación, planificador, interacciones, conversaciones, WhatsApp, seguimientos, referentes, auth, Meegle, workers | `meegle-altas`, `architecture-patterns`, `zyte-web-data:*` (solo exploración) |
| `creative-engineer` *(nuevo 2026-10-22)* | `packages/creative/`, `packages/render/`, `qualify_api.{creative,catalog,stock,canva}` | Brand Kit, catálogo, Crear pieza (ángulos, variaciones), proveedores de generación (BytePlus, Claude, Canva, stock), tabla de precios, Remotion, retención de piezas | `eval-driven-dev`, `canva:*`, `frontend-design` |
| `reflex-ui-engineer` | `Qualify/`, `assets/`, `rxconfig.py`, E2E | Las pantallas que usan los clientes, design system, textos en español | `reflex-docs`, `setup-python-env`, `reflex-process-management` (obligatorios), `design:*`, `dataviz` |
| `platform-engineer` *(nuevo 2026-10-22)* | `deploy/`, `.github/`, `infra/`, `docker-compose*.yml`, `justfile` | Producción en Hetzner, proxy de entrada, CI/CD y su presupuesto de minutos, secretos, respaldos, observabilidad | `engineering:deploy-checklist`, `engineering:incident-response`, `security-review` |
| `data-scientist-fde` | `packages/models/`, `packages/api/evals/`, `docs/modelos-generativos/` | Golden sets y medición de clasificadores con Claude, evals de prompts y modelos, costo por pieza, librerías multimodales | `eval-driven-dev`, `model-evaluation`, `claude-api`, `hf-cli` |
| `product-owner` | Tickets de Meegle, `docs/backlog-*.md`, `docs/epica-*.md` | Historias con criterios verificables a partir de evidencia | `meegle-ticket`, `meegle` |
| `gtm-specialist` | `docs/*research*`, `docs/*alternativas*`, `docs/ingenieria-inversa-*`, `docs/dolores-*`, `docs/fase0-*` | Mercado: eje **oferta** | `competitor-profiling`, `customer-research`, `positioning`, `pricing` |
| `market-opportunity-analyst` | `docs/oportunidades-mercado-*.md` | Mercado: eje **vector** | `customer-research`, `competitor-profiling`, `positioning`/`pricing` como lentes |
| `sales-consultant` | `docs/demanda-ventas-*.md` | Mercado: eje **demanda** | `customer-research`, `competitor-profiling`, `positioning` |

**Por qué dos ingenieros nuevos (2026-10-22).** El criterio del org es crear un specialist solo cuando hay volumen repetible. Desde agosto, `packages/api` creció a 30 módulos, el generador (`packages/creative` + `packages/render`) y la operación (`deploy/` + CI) acumularon decenas de PRs cada uno, y ninguno tenía dueño: `pipeline-engineer` seguía apuntando a un pipeline Celery/ClickHouse que nunca se construyó (ADR 31). El volumen ya existe; por eso se renombra uno y se crean dos.

### Los tres ejes del mercado: `gtm-specialist` · `market-opportunity-analyst` · `sales-consultant`

Añadidos el **2026-07-29** a pedido del fundador. Los dos nuevos son **consultores externos**, no funciones internas: no llevan el marketing ni el pipeline de ventas de Qualify — miran hacia afuera y devuelven **oportunidades y requisitos de producto**. Esa distinción es el punto entero del alta, y la primera versión de estos agentes (escrita el mismo día y descartada) se equivocó justamente ahí: los definió como departamento interno de marketing y ventas. Si alguien vuelve a proponer "un agente de marketing", este párrafo es la corrección.

Son **miembros condicionales** de `/team-research`: el lead los spawnea solo cuando el objetivo es de mercado (tendencias, dolores, innovaciones, oportunidad por nicho, qué exige el comprador). No van por defecto — el ledger registra muertes rutinarias por límite de gasto, así que una ronda de cinco teammates es un riesgo real, no una mejora gratis.

**Justificación del alta (honesta):** el criterio del org es "no crear specialists hasta que haya volumen repetible" (ver abajo), y ese criterio **no** es lo que motiva estos dos. `gtm-specialist` tiene ~4 filas en 85 del ledger: el squad de research no está saturado. Lo que los justifica es una **capacidad hoy ausente**: nadie mira el mercado *hacia adelante* (qué se está moviendo, qué se está innovando, dónde está el whitespace) ni *desde la demanda* (qué exige el comprador que no tenemos). `gtm-specialist` documenta el campo tal como está, que es un trabajo distinto.

La separación no es por tema sino por **eje / dirección de mirada** — es lo que evita que los tres escriban el mismo párrafo:

| Agente | Eje | Pregunta que responde | No hace |
|---|---|---|---|
| `gtm-specialist` | **Oferta / estado** | ¿Qué existe hoy? Competidores, vendors, incumbentes, features, precios, quejas documentadas — todo con fuente y fecha. | No escribe la conclusión prospectiva ni el requisito de producto. Es el **proveedor de evidencia** de los otros dos. |
| `market-opportunity-analyst` | **Vector / movimiento** | ¿Hacia dónde se mueve el mercado? Cambios de plataforma/formato/política, capacidades de IA que acaban de volverse baratas, **dónde se está desperdiciando o reasignando el presupuesto de marketing de las marcas**, señales de innovación (changelogs, funding, ofertas de empleo como indicador adelantado) → **tesis de oportunidad** con score de adyacencia, falsador y validación más barata. | No hace teardowns (eso es gtm). No define nuestro pricing, canales, CAC ni presupuesto — eso quedó **sin dueño** por decisión del fundador. No infla la adyacencia para que una tesis aterrice. |
| `sales-consultant` | **Demanda** | ¿Qué exige el comprador cuando alguien intenta venderle una herramienta de esta categoría? Ensaya la conversación de venta como instrumento **diagnóstico** y devuelve la **cola de requisitos** rankeada por (deals bloqueados × baratura de validación), más biblioteca de objeciones (las que **no** podemos responder honestamente son las filas valiosas) y criterios de descalificación. | No es el motor de smart-replies del producto (Fase 5) ni el inbox asistido de Parte 4-B. No es nuestra función interna de ventas. **No escribe `docs/backlog-*.md`.** |

**Nota sobre el "ahorro de inversión en marketing"** del pedido original: se interpreta como **el ahorro del comprador**, no el nuestro — dónde las marcas queman presupuesto hoy y si Qualify puede eliminar ese desperdicio. Es una de las clases de oportunidad más fuertes precisamente porque el comprador la puede medir, lo que hace legible su disposición a pagar.

**Firewall de nivel de evidencia (regla dura, no aspiracional).** `sales-consultant` produce **hipótesis, no hallazgos** — un lead ensayado no tiene URL, así que por construcción no puede satisfacer el estándar del `research-lead` (regla #3: toda afirmación de mercado necesita URL y fecha de acceso). Tres restricciones escritas en su constitución:

1. **Anclaje** — toda persona, demanda, objeción y requisito traza a un artefacto real citado. Su corpus de sourcing es público y explícito: reseñas de 3 estrellas y "what I wish it did" en G2/Capterra, hilos de comunidad, **changelogs de competidores** (una feature enviada es una demanda del mercado hecha visible), posts de migración/churn, criterios de RFP, ofertas de empleo del rol que usaría la herramienta. **No puede inventar un dolor**; solo dramatizar uno documentado. Un hueco nombrado vale más que una invención fluida.
2. **Etiquetado** — todo output es `[H]` (hipótesis), o `[V]` solo si el fundador confirma que un prospecto real lo dijo. Cada doc abre con el descargo de que su contenido es ensayado.
3. **Gate de backlog** — un requisito no entra al backlog hasta que un prospecto real lo valide. Su entrega es una cola de *qué validar*, no de qué construir.

El `research-lead` sintetiza su output en una sección separada y explícitamente hipotética, nunca mezclada con hallazgos con fuente: la base de evidencia con fuente es el activo sobre el que se apoya toda la toma de decisiones del proyecto, y contaminarla con ficción convincente sería el peor daño disponible.

**Dos disciplinas más que el lead debe imponer:**

- **Vigilar la adyacencia contra el disco.** El score de adyacencia de `market-opportunity-analyst` es una afirmación sobre código, y buena parte de lo que describe `CLAUDE.md` está sin construir. Una adyacencia sobreestimada convierte un insight real de mercado en una mala decisión de build — peor que perderse la tendencia.
- **Anti-adulación.** Ambos consultores están contratados para ser incómodos: una tesis o un requisito que diga que el roadmap actual apunta mal es su output de mayor valor. Si una sesión de mercado devuelve solo hallazgos que respaldan el plan, es señal de que el brief fue sesgado, no una buena noticia.

**Huecos de skill conocidos (candidatos COMPASS, aún no sintetizados).** No se crean por adelantado — COMPASS exige reuso esperado, y estos agentes tienen cero historial. Se sintetizan tras la segunda improvisación exitosa:

- **Escaneo estructurado de tendencias / whitespace y scoring de oportunidad** (`market-opportunity-analyst`) — mientras tanto debe exponer la rúbrica explícita (inputs, pesos, cómo puntuó la adyacencia) en cada doc.
- **Estructura de metodología de ventas** (`sales-consultant`) — frameworks de discovery, calificación tipo MEDDIC/JTBD, taxonomías de manejo de objeciones; mientras tanto debe declarar qué framework aplica y por qué.

### Skill transversal: `durable-findings`

`durable-findings` (`.claude/skills/durable-findings/`) no pertenece a un specialist — **aplica a todos**. Sintetizado vía COMPASS el 2026-07-26 tras la cuarta ocurrencia del mismo modo de fallo en el ledger: las sesiones aquí mueren por límite de gasto de forma rutinaria, y todo lo que existe solo en una ventana de contexto se pierde. Codifica dos reglas y su corolario:

1. **Volcar por secciones, nunca bufferear un informe final.** El registro es inequívoco: los agentes que escribieron incrementalmente no perdieron nada; los que bufferearon lo perdieron todo.
2. **Un hallazgo que cambia los supuestos de otro agente lo escribe a disco su descubridor**, no se entrega solo por mensaje al lead — la ventana del lead es igual de mortal, y retransmitir no es persistir.
3. **Corolario:** toda afirmación sobre disco se verifica contra disco antes de darla por buena.

Incluye `scripts/record_finding.py` (append-only, por lo que cualquier agente puede registrar un hallazgo en un fichero cuyas otras secciones no le pertenecen sin riesgo de pisarlas). **Mantenimiento:** `qualify-second-brain` (dueño de `.claude/` y del ledger). **Ejecutores por defecto:** todos los agentes; los tres leads lo imponen a sus squads.

### Agentes de utilidad (fuera de los squads de producción)

- `linkedin-bitacora` — ghostwriter de marca personal de Herwin. Genera un post diario en inglés (días de semana) sobre sus aprendizajes como FDE + CTA suave de coaching neurocientífico / transformación de carrera, y lo entrega como borrador de Gmail a `hlrd1993+qualify@gmail.com`. Vive solo en `bitacora/` y su propio archivo; **no toca producto, docs ni el org de squads**. Regla dura: denylist anti-filtración (nunca nombre de producto, competidores, vendors/costos, modelos, esquema de datos ni roadmap; nunca cita commits). Automatizado vía routine cloud `trig_01SHp5v6tsxFtpRjazgF49Cq` (`0 11 * * 1-5` UTC = 8:00 Montevideo). No es un cuarto squad ni parte del pipeline de Qualify.

## Quién construye qué hoy

El mapa original de seis fases (`CLAUDE.md`) sigue describiendo la dirección de largo plazo, pero el producto en producción se movió a contenido, publicación y conversaciones para negocios pequeños. El reparto por área:

- **Generar contenido** (Brand Kit, catálogo, piezas, plantillas): `creative-engineer` + `reflex-ui-engineer`; `data-scientist-fde` mide prompts y modelos.
- **Publicar y planificar**, **interacciones, conversaciones y WhatsApp**: `backend-engineer` + `reflex-ui-engineer`; `data-scientist-fde` para la intención comercial.
- **Anuncios de Meta (ADR 38)**: `backend-engineer` (Marketing API) + `creative-engineer` (la pieza como anuncio) + `reflex-ui-engineer`; `principal-architect` sigue el App Review.
- **Producción, CI y costos de operación**: `platform-engineer`.
- **Listening de earned media, señales, lookalike y outreach** (Fases 2-5 originales, sin construir): se exploran con `/team-research` y se construyen con `backend-engineer` + `data-scientist-fde` cuando el fundador los abra.

## COMPASS y SAGE: ciclo de vida de la librería de skills

La organización de agentes no es estática — evoluciona con evidencia, mediante dos meta-protocolos instalados como skills de proyecto y operados principalmente por `qualify-second-brain`:

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
