# Formato de los tickets de Meegle

`[VIGENTE 2026-10-21 · m-24823777]` · Un solo formato para todo el equipo, personas y agentes.
Meegle no deja crear plantillas de descripción desde su API, así que el formato vive aquí: lo copias
en la UI de Meegle o lo aplica la skill `/meegle-ticket` de Claude Code (`.claude/skills/meegle-ticket/`).
Si cambias este documento, la skill cambia con él: es su única fuente.

## 1. Qué tipo de ítem

| Lo que vas a hacer | Tipo en Meegle | Plantilla | Etiqueta principal |
|---|---|---|---|
| Algo funciona mal | **Issue** | Default Issue | `Bug` |
| Algo nuevo que ve el usuario | **Issue** | Default Issue | `Feature` |
| Mejorar algo que ya existe | **Issue** | Default Issue | `Improvement` |
| Trabajo interno (refactor, infra, tests, docs) | **Issue** | Default Issue | `Deuda técnica`, `Infraestructura`, `Testing` o `Documentación` |
| Una iniciativa de varios PRs | **Feature** (la épica) | Product Feature Request o Technical Request | — |

**El Issue es la unidad de trabajo:** un Issue → un PR (o pocos). Una Feature agrupa Issues y se
nombra `Épica — <tema>`; el Issue apunta a ella con el campo **Feature**. No abras un PR contra una
Feature.

## 2. Título

`<Área>: <qué pasa o qué se quiere>`, en español, sin punto final, que se entienda sin abrir el ticket.

- ✅ `Altas en Meegle: «Estado Qualify» no se escribe (select como objeto)`
- ✅ `Generador: elegir el producto desde imagen de stock`
- ❌ `Arreglar bug`, `Mejoras varias`, `WIP`

El área es el módulo tal como lo llama el equipo: Altas en Meegle, Generador, Planificador,
Conversaciones, WhatsApp, Conexiones, Brand Kit, Deploy, CI…

## 3. Campos

| Campo | Regla |
|---|---|
| **Priority** | `P0` producción rota o un cliente bloqueado — se atiende hoy · `P1` bloquea otro trabajo o es de esta semana · `P2` lo normal · `P3` cuando haya hueco. Ante la duda, `P2`. |
| **Label** | La etiqueta principal de la tabla §1, más las de área que apliquen (`UI`, `SEO`, `i18n`, `Accesibilidad`…). |
| **Feature** | La épica a la que pertenece, si hay una. |
| **Reporter / Assignee** | Quién lo pide / quién lo hace. Sin Assignee, el ticket no tiene dueño: queda en Backlog. |
| **Bloquea / Bloqueado por / Relacionado con** | Para enlazar Issues entre sí en lugar de escribir «ver ticket X» en el texto. |

## 4. Descripción

Markdown con secciones en negrita, siempre en este orden. Sección que no aplica, se borra; no se
deja vacía. **Criterios de aceptación** no se borra nunca: es lo que dice cuándo el ticket está
terminado, y cada criterio se puede comprobar (un test, una pantalla, un comando, un dato en la base).

### Bug

```markdown
**Qué pasa**
Lo observado, dónde (PROD / dev / CI), desde cuándo y a quién afecta (tenant, ítem, usuario).

**Cómo reproducirlo**
1. …
2. …

**Qué debería pasar**
…

**Causa**
Si ya se conoce, con la evidencia (log, respuesta de la API, línea de código). Si no, se borra.

**Arreglo**
- …

**Criterios de aceptación**
- [ ] …

**Fuera de alcance**
- …
```

### Feature / mejora

```markdown
**Contexto**
Por qué ahora y quién lo pide. Enlace al doc, ADR o conversación de origen.

**Qué se quiere**
Como <rol> quiero <capacidad> para <resultado>.

**Propuesta**
- …

**Criterios de aceptación**
- [ ] …

**Fuera de alcance**
- …

**Referencias**
- `docs/…`
```

### Tarea técnica

```markdown
**Contexto**
Qué problema causa hoy no hacerlo (lentitud, riesgo, costo, deuda que frena otra tarea).

**Qué hay que hacer**
- …

**Cómo verificarlo**
El comando, test o medición que demuestra que quedó hecho y que no rompió nada.

**Criterios de aceptación**
- [ ] …

**Fuera de alcance**
- …
```

## 5. Del ticket al PR

El número del ticket es el de su URL (`…/issue/detail/24789646` → `m-24789646`) y va en tres sitios
(regla completa en `CLAUDE.md`, «Every PR carries its Meegle ticket number»):

- rama: `<tipo>/m-<id>-<slug>` — `feat/m-24789646-dm-propuesto`
- título del PR, al final: `feat(conversations): DM drafts from comment intents (m-24789646)`
- descripción del PR: `Resolves m-24789646`

Las reglas de Meegle que deberían mover el ticket al abrir y al mergear el PR **no mueven nada**
(medido 2026-10-20): muévelo a mano — **In Progress** al empezar, **RESOLVED** al abrir el PR,
**Done** al mergear.
