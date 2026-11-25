# Épica — Filtrado de reels estilo TikTok for Business (ampliación de m-24872324)

> **Estado:** en curso (2026-11-25), 11 tickets creados (ver «Tickets en Meegle»). **No es una épica nueva**: amplía
> **m-24872324** «Filtrar reels de inspiradores, competidores y detractores por canal, región y
> objetivo» (Start, P2, creada por Herwin el 26/10, sin tickets hijos; PM y Frontend: Deivid).
> Revisada por `principal-architect` (factibilidad) y por análisis de costo el 2026-11-25.
> Todas las decisiones cerradas el 2026-11-25 (opción de costo B).

## Por qué

Hoy «Ideas para tus reels» (`Qualify/discover_reels.py`) muestra **8 ideas por corrida**, sacadas
solo de cuentas marcadas como `referente` (máx. 12). El dueño no puede filtrar nada. Las cuentas
marcadas como `competencia` no aportan ni un reel. Pero cada corrida ya revisa ~32 reels + 3 por
cuenta y **guarda el veredicto de Claude de todos** en `brand_reel_verdicts` (RLS, no se purga):
hay mucho más que mostrar sin pagar nada.

Deivid pidió el 2026-11-25 filtros «como TikTok Business» (captura de Top Ads) y **descubrir
cuentas nuevas**.

## Filtros

| TikTok | Qualify | m-24872324 | Dato detrás |
|---|---|---|---|
| Industry | **Nicho** fijo a la marca (rótulo, no filtro) | Igual | rubro de la marca |
| Region | **Región** (las 3 del Brand Kit) | Igual | `creators.country_code` (llenado por medir, RF-04) |
| Objective | **Objetivo** — **pospuesto** hasta que Herwin cierre el catálogo | Igual | ninguno hoy |
| — | **Tipo de cuenta**: inspiradores / competidores (+ «Descubrir cuentas nuevas») | inspiradores / competidores / detractores | `brand_account_labels`; RF-07a: `creators`, `creator_sightings` |
| — | **Canal** Instagram / TikTok | Igual | red de `public_reels` |
| (formato) | **Duración** <15 s, 15–30 s, 30–60 s, +60 s | No está | `public_reels.duration_s` |
| Reset | **Restablecer filtros** | Igual | — |
| Likes, Last 30 days, Search by product, Sort by | **Fuera** (Deivid, 2026-11-25, respeta el diseño de Herwin) | Excluidos | — |

**No replicable** (no es público): CTR, CVR, CPA, costo, alcance pagado, retención, demografía.

**Se mantiene:** filtro de producto **estricto** siempre activo, aviso «inténtalo más tarde», los
nombres de R15 m-24854846. Las 6–8 «ideas» de R11 no cambian: lo demás se muestra como «más
reels revisados» y **no pasa por el analizador de producción** (que solo corre sobre las ideas,
`reel_runs.py:1129`).

## Decisiones

1. ✅ «Competidores» = «competencia» (cuentas marcadas `competencia`). Sin «Competencia del sector».
2. ✅ Me gusta, fechas, búsqueda por producto y ordenar por: **fuera**. Sin choque con R10.
3. ✅ **Detractores fuera** (Deivid, 2026-11-25). En el asistente, `detractor` significa «No va
   contigo: no se parece a tu marca» (`creative_wizard_pages.py:3667`); sus reels no se leen ni
   aparecen en el filtro, aunque m-24872324 lo pedía.
4. ✅ **Opción de costo B firmada** (Deivid, 2026-11-25): ≈ +USD 0,6–0,8 por negocio al mes.
5. ✅ **Más de 6 competidores** (Deivid, 2026-11-25): el dueño elige cuáles 6 se leen cada lunes
   (por defecto los 6 primeros de su lista); para cualquier otro, botón «Ver sus reels ahora» que
   lo lee al momento (≈ USD 0,01 por cuenta, dentro del tope diario del negocio). Además, filtro
   **«Cuenta»** (una o varias) en la barra, sobre lo ya guardado, sin costo.

## Historias (bajo m-24872324), en orden de PR

| # | Id | Historia (resumen) | Relación | Área | Prio | Tam | Pago |
|---|---|---|---|---|---|---|---|
| 0 | RF-00 | Medir el llenado de `country_code` y `category` en las cuentas de las marcas (consulta, sin código). ≥70 % → se usa lo que hay | Decide el alcance de RF-04 | datasci | P1 | S | No |
| 1 | RF-01 | Consulta filtrable sobre `brand_reel_verdicts` (`fits` = sí) ⨝ `public_reels` ⨝ `brand_account_labels`: canal, tipo de cuenta, duración, región, nicho; las 6–8 ideas + «más reels revisados» paginados. Sin llamadas pagadas al abrir. Incluye el antiguo RF-03 | Base de m-24872324; respeta R9 y R11 | backend | P1 | M | No |
| 2 | RF-02 | Barra de filtros fija (Canal, Tipo de cuenta, Cuenta —una o varias—, Duración) + «Restablecer filtros»; en el teléfono, chips con hoja desde abajo | Implementa la UI de m-24872324 | ui | P1 | M | No |
| 3 | RF-04 | Región y rubro de cada cuenta: primero gratis (caché de perfiles, `region` de TikTok, ubicación del reel); lo que falte, sumado a la revisión de cuentas que ya existe (`referentes/ai.py`), con procedencia. Posible migración 0182 sobre `creators` (global) | Requisito de Región/Nicho | backend + datasci | P1 | S | Mínimo |
| 4 | RF-02b | Región y Nicho en la barra | Completa m-24872324 | ui | P1 | S | No |
| 5 | RF-05 | Leer reels de cuentas `competencia` en la corrida semanal: las 6 que elige el dueño (por defecto las 6 primeras); botón «Ver sus reels ahora» para cualquier otra (lectura manual por la puerta que paga, dentro del tope diario); gasto separado por etiqueta. Enmienda R4/R8 en `docs/adr-42-ideas-reels-costo.md` | Cubre el criterio 10 de m-24872324 | backend | P1 | M | **Sí** |
| 6 | RF-09 | Insignias: «En ascenso» (`lift` de `creators/metrics.py`) y «Top 10 % de tu rubro» (tras RF-04), con versión | Nuevo | backend + ui | P2 | M | No |
| 7 | RF-07a | «Descubrir cuentas nuevas» gratis: cuentas de la base compartida (`creators`, `creator_sightings`) no marcadas, filtrables por seguidores, región, rubro, mediana de vistas, interacción; botón «Seguir como inspiración / competidor» (lo pulsa el dueño) | Nuevo | backend + ui | P2 | M | No |
| 8 | RF-10 | Comparar 2–3 cuentas con lo ya guardado | Reusa m-24946132 | ui | P3 | S | No |
| 9 | RF-07b | Buscar cuentas nuevas pagando (`PhasedDiscovery`, casi solo TikTok: Instagram no tiene búsqueda de usuarios) solo si 7a da <8 resultados; presupuesto propio 50/día, 200/mes | Puerta medida de R16 m-24854853 | backend | P2 | M | **Sí** |
| 10 | RF-11 | Objetivo: tabla fija `format` → vender / darse a conocer / conversar | Espera catálogo de Herwin | backend + ui | P3 | S | No |

**Tickets en Meegle** (creados 2026-11-25, Backlog, asignados a Deivid, bajo m-24872324):
RF-00 m-25119446 · RF-01 m-25119458 · RF-02 m-25119460 · RF-04 m-25119461 · RF-02b m-25119463 ·
RF-05 m-25119465 · RF-09 m-25119466 · RF-07a m-25119467 · RF-10 m-25119468 · RF-07b m-25119482 ·
RF-11 m-25119483. «Bloqueado por»: RF-02←01; RF-04←00; RF-02b←02,04; RF-05←01; RF-09←01,04;
RF-07a←01,04; RF-10←02; RF-07b←07a; RF-11←01 (+ catálogo de Herwin).

**Resultado RF-00 (2026-11-25, base local):** 59 cuentas `referente`/`competencia`; 0 % con
`creators.country_code` y 0 % con `creators.category` (en toda `creators`: 0 con categoría, 5
con país). `category` guarda la categoría de la red (`creators/snapshots.py:375`), no el rubro.
58/59 tienen país aproximado en `creator_sightings.country_code` (país de la búsqueda).
Producción no se midió (sin acceso desde esta máquina); Deivid decidió seguir con lo sabido:
**RF-04 con alcance completo** — país gratis primero, rubro inferido con IA dentro de la revisión
de cuentas existente, con procedencia.

Descartadas: RF-06 «Competencia del sector» (decisión 1), RF-08 «Buscar por producto»
(decisión 2), RF-03 (fusionada en RF-01).

## Costo (extra por marca y mes, sobre los ~USD 0,55 de hoy)

Precios: crédito ScrapeCreators USD 0,0019 (`pricing_data/v10.json`); veredicto de Claude
USD 0,00098/reel (R17); tope por negocio 150/día, 600/mes. Estimaciones [S]; confirmar con una
semana de R17 tras cada historia.

| Opción | Más reels (RF-01) | Región/rubro (RF-04) | Competidores (RF-05) | Cuentas nuevas (RF-07b) | Extra/mes |
|---|---|---|---|---|---|
| A. Completa | Ficha para todos | Perfil + Claude | 12 cuentas, recorrido completo | 1/semana, tope común | ≈ USD 2,4 |
| **B. Recomendada** | Ficha solo para las 8 ideas | Gratis primero, Claude de respaldo | 6 cuentas, recorrido completo | Base compartida primero, presupuesto 50/200 | **≈ USD 0,6–0,8** |
| C. Mínima | Ficha solo para las 8 ideas | Solo gratis | 6 cuentas, página 1, sin transcripción | Sin pagar | ≈ USD 0,15 |

Todas son puertas de dos vías (constantes y presupuestos). Medición: `vendor_usage_events`
(`reels_list`, `reels_transcript`, `profile`, `referentes_search`), `brand_reel_runs.cost_usd`
y Langfuse.

## Restricciones y cuidados

- Toda lectura pagada pasa por `referentes/reel_runs.py` y `reel_schedule.py`. ScrapeCreators con
  `just sc`. Nada pagado sin OK de Deivid escrito en la sesión.
- Analizador de reels activo en producción (`QUALIFY_REEL_ANALYSIS_DESCRIBE=1`): solo sobre ideas.
- Migraciones: main en 0181, siguiente libre 0182 (avisar a «creacion de tickets» al reservarla).
  `creators` y `public_reels` son globales (dato público); `brand_*` con `tenant_session` y RLS.
- Procedencia en región/rubro inferidos e insignias. Asistido: «Seguir como…» lo pulsa el dueño.
- Un PR por ticket; review-agent + ux-designer antes de cada PR; merge con `just merge` por
  «creacion de tickets».

## Evidencia

- Pedido y decisiones de Deivid, 2026-11-25 (captura de Top Ads).
- m-24872324 (Herwin, 26/10); épica m-24854843 «Ideas para tus reels» (ADR 42).
- Código: `Qualify/discover_reels.py`, `packages/api/src/qualify_api/referentes/`
  (`reels.py:59-62,106-135`, `reel_runs.py:163,1129`), `Qualify/creative_wizard_pages.py:3667`,
  migraciones 0020, 0036, 0117, 0125.
- `docs/adr-42-ideas-reels-costo.md`, `docs/descubrir-reels-scrapecreators.md` (R17).
