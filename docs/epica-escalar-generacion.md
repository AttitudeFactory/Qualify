# Épica — Escalar la generación: cola, límite de 10 tareas de BytePlus y prioridad

`[PROPUESTO 2026-10-24 · m-24852152]` · Dueño del backlog: product-owner.

Épica en Meegle: [m-24852152](https://project.larksuite.com/5h2wsx/story/detail/24852152).
Relacionada con la épica de costos y cobro m-24848869 y con los planes m-24852145.

## Por qué

Pedido del fundador (2026-10-24): BytePlus limita Seedance 2.5 a **10 tareas a la vez y 600 por
minuto por cuenta principal**, borradores y finales juntos. Preparar la generación para crecer en
clientes. Probablemente no muerda al principio. Su idea: «agendar la generación» frente a «generar
ya» con costo extra.

Evidencia: `docs/escalar-generacion-concurrencia.md` (data-scientist-fde) y el diseño de
principal-architect (cola en Postgres, semáforo por proveedor, `creative-worker`, ADR 41).

- Pasarse de 10 encola en BytePlus hasta 48 h, sin error. Pasarse de 600 por minuto da 429.
- Saturación: ~500 negocios con uso típico, ~200 en el peor caso. OmniHuman, ~420.
- **Dos fallas de hoy** que no dependen de la escala: videos cobrados que nunca aparecen tras la
  espera de 8 min, y el reaper que mata carruseles largos vivos.
- «Agendar» no ahorra nada en BytePlus (Seedance 2.5 no tiene flex ni lotes). Lo que rinde: hacer
  de noche los finales de las piezas ya programadas.

## Historias

| Ticket | Título | Prioridad | Fase | Área | Bloqueado por |
|---|---|---|---|---|---|
| [m-24852154](https://project.larksuite.com/5h2wsx/issue/detail/24852154) | Video cobrado que nunca aparece tras la espera de 8 min: recuperar por id, contar desde «running» | P0 | P0 | creative | — |
| [m-24852156](https://project.larksuite.com/5h2wsx/issue/detail/24852156) | El reaper da por muerto un carrusel animado largo vivo | P0 | P0 | creative | — |
| [m-24852157](https://project.larksuite.com/5h2wsx/issue/detail/24852157) | Decisión del fundador: servicio `creative-worker` y ADR 41 | P1 | Decisión | architect → fundador | — |
| [m-24852158](https://project.larksuite.com/5h2wsx/issue/detail/24852158) | Medir espera en cola y tareas a la vez (queued / running / finished) | P1 | 1 | creative + datasci | m-24852154 |
| [m-24852159](https://project.larksuite.com/5h2wsx/issue/detail/24852159) | Adaptador de Seedance en enviar/consultar, 429 → `VendorBusy`, espera adaptativa | P2 | 1 | creative | m-24852154 |
| [m-24852160](https://project.larksuite.com/5h2wsx/issue/detail/24852160) | Cola `creative_jobs` y semáforo `vendor_slots` (migración con RLS) | P2 | 1 | creative | m-24852157 |
| [m-24852163](https://project.larksuite.com/5h2wsx/issue/detail/24852163) | `creative-worker` con carriles, cupos reservados y reparto justo | P2 | 1 | creative + platform | m-24852157, m-24852159, m-24852160 |
| [m-24852166](https://project.larksuite.com/5h2wsx/issue/detail/24852166) | Encolar en lugar de lanzar hilos; reaper desde `started_at` | P2 | 1 | creative | m-24852163, m-24852156 |
| [m-24852168](https://project.larksuite.com/5h2wsx/issue/detail/24852168) | Plazo del final (borrador + 7 d − 15 min), prioridad a < 24 h | P2 | 1 | creative | m-24852166 |
| [m-24852169](https://project.larksuite.com/5h2wsx/issue/detail/24852169) | Final de piezas programadas hecho de noche, antes de publicar | P2 | 1 | creative + backend + ui | m-24852166, m-24852168 |
| [m-24852170](https://project.larksuite.com/5h2wsx/issue/detail/24852170) | Aviso «Tu video está en fila…» y cancelar mientras espera | P2 | 1 | ui + creative | m-24852166 |
| [m-24852167](https://project.larksuite.com/5h2wsx/issue/detail/24852167) | Avisos a Lark y `just creative-queue` | P2 | 1 | platform | m-24852163, m-24852158 |
| [m-24852161](https://project.larksuite.com/5h2wsx/issue/detail/24852161) | Llaves de BytePlus separadas para desarrollo y evaluaciones | P2 | 1 | platform | — |
| [m-24852171](https://project.larksuite.com/5h2wsx/issue/detail/24852171) | «Generar ya» con costo extra solo cuando hay fila | P3 | 2 (espera p95 > 5 min) | ui + creative | m-24852170, m-24852167 |
| [m-24852172](https://project.larksuite.com/5h2wsx/issue/detail/24852172) | Ticket a BytePlus: Seedance 2.5 a 30, OmniHuman a 3–5 | P3 | 3 (~100 negocios o p95 a la vez ≥ 5) | fundador + datasci + platform | — |
| [m-24852173](https://project.larksuite.com/5h2wsx/issue/detail/24852173) | Grupos de cupos para OmniHuman y Seedream | P3 | 3 (espera OmniHuman > 5 min o ~200 negocios) | creative | m-24852166 |
| [m-24852174](https://project.larksuite.com/5h2wsx/issue/detail/24852174) | Varias cuentas de BytePlus, último recurso | P3 | 3 (cupo concedido agotado) | creative + platform | m-24852172 |

## Decisiones abiertas del fundador

1. Servicio `creative-worker` y ADR 41 (m-24852157): opción A (servicio nuevo, USD 0) frente a B/C/D.
2. Finales nocturnos (m-24852169): ¿aprobar la vista previa basta para publicar el final que se
   hace de noche, o el dueño debe ver el final antes?
3. Precio de «Generar ya» al activar la Fase 2 (m-24852171), ligado a los planes m-24852145.
4. Varias cuentas de BytePlus (m-24852174): solo con visto bueno escrito de BytePlus.

## Nota sobre llaves separadas

El límite es por cuenta principal sumando subcuentas: una llave aparte para evaluaciones **no**
separa la cuota (m-24852161). Las evaluaciones con video deben correr fuera del horario del comercio.
