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
RF-11 m-25119483 · RF-12 m-25119986 (país por IA, creado después). «Bloqueado por»: RF-02←01; RF-04←00; RF-02b←02,04; RF-05←01; RF-09←01,04;
RF-07a←01,04; RF-10←02; RF-07b←07a; RF-11←01 (+ catálogo de Herwin).

**Resultado RF-00 (2026-11-25, base local):** 59 cuentas `referente`/`competencia`; 0 % con
`creators.country_code` y 0 % con `creators.category` (en toda `creators`: 0 con categoría, 5
con país). `category` guarda la categoría de la red (`creators/snapshots.py:375`), no el rubro.
58/59 tienen país aproximado en `creator_sightings.country_code` (país de la búsqueda).
Producción no se midió (sin acceso desde esta máquina); Deivid decidió seguir con lo sabido:
**RF-04 con alcance completo** — país gratis primero, rubro inferido con IA dentro de la revisión
de cuentas existente, con procedencia.

**Cobertura tras RF-04 (2026-11-25, base local, solo lectura):** país gratis 0 % → **98 %**
(58/59: 32 por la `region` de los videos de TikTok, 26 por `creator_sightings`); rubro 0 % hasta
que cada cuenta vuelva a pasar por la revisión con IA. Hallazgo: `creator_discovery._tiktok_author`
busca el país en `author.region`, pero TikTok lo trae en `aweme_info.region`.

**Eval REFERENTES-RUBRO-001 (2026-11-25, USD 0,39):** rubro 0,87 en test (pasa ≥ 0,85); país por
IA 0,815 / 0,827 (no pasa ≥ 0,95, inventa el país). Decisión de Deivid: **país solo de fuentes
gratis** en RF-04; el país por IA pasa a **RF-12 m-25119986** (prompt `referentes-review-4` con
evidencia escrita, bloqueado por RF-04). PRs: RF-01 #806, RF-04 #807.

**Muestreo humano y prompt v3 (2026-11-25):** Deivid revisó los 14 casos dudosos de rubro. Reglas:
quien enseña → Educación; deporte y medios generales → Entretenimiento; medio temático → su tema;
el rubro es lo que la cuenta ES; sin evidencia → fuera. `referentes-review-3` las incorpora:
rubro en test 0,941 / 0,906 (v2: 0,894 / 0,847), sin regresión, USD 0,4287. Excepción aceptada:
«Viajes y estilo de vida» 0,57 / 0,43 (n = 7, todo lauratuttman). El país por IA pasa a
`referentes-review-4` en RF-12. #806 fusionado (main 9407a6a6); #807 fusionado (main ee64050b, migración 0182).

**RF-05 construido (2026-11-25, m-25119465, migración 0183).** Backend completo, sin
llamadas pagadas durante el desarrollo (pruebas sin red con fakes y `-m db` en una base
aislada). La corrida del lunes lee las 6 cuentas `competencia` elegidas
(`brand_account_labels.read_weekly`; sin elección, las 6 primeras por `position`) después
de los referentes. «Ver sus reels ahora» es una corrida `competitor_now` de una cuenta, una
por negocio, cuenta y día local (`referentes/competitors.py`). El gasto queda aparte:
`competitor_reels_list` / `competitor_reels_transcript` en `vendor_usage_events` y
`competitor_credits` / `competitor_cost_usd` en `brand_reel_runs`. El filtro
«Competidores» de RF-01 ya trae sus reels (también los de una lectura manual, aunque no
haya corrida del lunes). Peor caso de la corrida semanal: 130 créditos, antes 88. Costo
estimado: ≈ USD 0,5 al mes por negocio y ≈ USD 0,01–0,02 por cada lectura manual. Detalle
en la enmienda RF-05 de `docs/adr-42-ideas-reels-costo.md`. **La pantalla espera a RF-02
(#810):** el selector y el botón van en `Qualify/discover_reels.py` cuando #810 esté en
`main`.

**RF-13 (m-25120327, 2026-11-25): la barra con las piezas de LiquidOS y una sola lista.**
Pedido de Deivid tras la prueba en vivo. La barra, los desplegables, los chips, la hoja desde
abajo y el cajón «Tus competidores» usan solo botones, popovers y el `drawer` del sistema, con
el skin de Radix. Ya no hay reglas `.q-rf-*` ni el recuadro oscuro detrás de la barra. Desde
el 2026-11-26 hay un panel suave del sistema (`T.CARD_BG`) y cada filtro es un chip de una
palabra. En escritorio, todo va en una fila centrada: los filtros, «Competidores» y «Quitar
filtros». En el teléfono, «Filtros · N» y «Competidores» van lado a lado, y «Filtros» abre una
sola hoja con todos los filtros (`docs/design-system.md` §5.8). Debajo hay **una sola lista
sin encabezados**: primero
las ideas, con «Hacer uno parecido», y después los otros reels revisados, sin ese botón. Se
muestran 16 (`LIST_PAGE`) y «Ver más» trae los 16 siguientes. Se quitaron «Ideas de hace N
días», «Más reels revisados» y sus textos. Los textos de RF-05 que nombraban esa sección ahora
dicen «tus ideas». Sigue sin haber llamadas pagadas: es la misma lectura de RF-01, con
`limit=16`.

**RF-14 (m-25129383, 2026-11-26): «Buscar reels nuevos».** Es la R9 de ADR 42. El botón
encola una corrida `manual` de la marca para el día local del negocio
(`referentes/manual_search.py`). La paga el `reels-worker` con `reel_runs.run`, la única puerta
que paga. Lee las mismas cuentas que la corrida del lunes: los referentes y los 6 competidores
elegidos (`_run_claimed` ya no limita los competidores a `weekly`). Lo ya leído no se paga dos
veces: cuentas leídas hace menos de 24 h, transcripciones y veredictos guardados.

- **Una al día por marca:** se busca la corrida con `ReelRunStore.manual_run`; el `UNIQUE
  (brand_id, trigger, run_date)` de 0117 evita la segunda, aunque lleguen dos clics a la vez.
  Una búsqueda terminada no se vuelve a encolar ese día, encuentre lo que encuentre. Hay una
  excepción: si la compuerta la paró antes del tope del negocio (lecturas pagadas en pausa,
  piso del proveedor), esa búsqueda no ocurrió y el siguiente toque la vuelve a encolar en la
  misma fila. Si falla la revisión y el worker la va a reintentar solo, sigue «buscando». Si
  lleva más de 15 min en cola, el botón se libera y avisa una vez: «La búsqueda está tardando
  más de lo normal. En un rato toca «Buscar reels nuevos» para ver si ya llegaron.» Sin
  brief o sin cuentas, avisa: «Para buscar reels nuevos, primero agrega al menos una cuenta que te
  inspire.»
- **Tope del negocio:** si ya se gastó (150 al día, 600 al mes), no se encola nada y aparece
  «Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana.» (en el mensual, el
  texto mensual de RF-05). Si se alcanza a mitad de la corrida, la compuerta la para
  (`budget_stopped`).
- **Pantalla:** abrir solo lee (`search_state`). Mientras corre, el botón queda ocupado (girador,
  `aria-busy`) y sobre la lista sale «Estamos buscando reels nuevos. La lista se actualiza sola en
  unos minutos.». Un reloj del navegador relee gratis cada 12 s y, al terminar, recarga la lista
  sin mensajes. Si ya se buscó hoy o se llegó al tope, el botón no queda muerto: recarga gratis
  y muestra una sola vez el aviso del día («Ya buscaste reels nuevos hoy. Vuelve a intentarlo
  mañana.») o el del tope. Es un aviso con id fijo: el siguiente reemplaza al anterior.
  Una búsqueda `manual` que termina mal no pone «No pudimos traer ideas nuevas» sobre las
  ideas guardadas.
- **Barra:** en la versión ancha, el botón va después de «Competidores» y antes de «Quitar
  filtros», para que no cambie de lugar cuando aparece ese botón. El ícono es `search`;
  mientras busca, el texto y el nombre accesible dicen «Buscando…», y el aviso «Estamos
  buscando…» es un `callout` informativo dentro de la única región `role="status"`. Desde
  1000 px de barra lleva texto; entre 760 y 1000 px solo el ícono, para que la fila no se
  parta (medido en vivo: a ~780 px los chips quedan entre 92 y 117 px y «Buscar» no cabe).
  Con RF-02b la fila ancha empieza en 850 px y el texto del botón sigue desde 1000 px. En la
  versión angosta es un tercer botón de solo ícono de 44 px, en la misma fila que «Filtros» y
  «Competidores», con su nombre en `aria-label` y `title`.
- Sin migración y sin llamadas pagadas en las pruebas (fakes detrás de la compuerta real).
  Costo: ≈ USD 0,10–0,15 por búsqueda, aprobado por Deivid para producción.

**RF-02b backend (2026-11-25, m-25119463):** `referentes/reviewed_reels.py` une `creators`
(`region_code`, `rubro`, de RF-04) con `LEFT JOIN` en Postgres y en el gemelo en memoria.
Filtros: `ReelFilters.of(regions=["CO", …])` (ISO-2, una o varias) y `niches=[clave]`.
Opciones: `REGION_OPTIONS` = los tres mercados del negocio (`tenancy.locale.COUNTRIES`:
Colombia, Venezuela, Uruguay) + «Todas»; `brand_niche(tenant, brand)` lee el rubro del Brand Kit
(`connect.sector`; si no hay clave, `rubro_text`) con `tenant_session` y da «Nicho: …».
**Cuentas sin país o sin rubro:** con el filtro apagado («Todas», sin nicho) entran siempre; con
un filtro activo quedan fuera (un dato desconocido nunca coincide). Igual para las ideas. El nicho
**no** se aplica por defecto: la cobertura de rubro es ~0 % hasta que las cuentas vuelvan a pasar
por la revisión, y filtrar por defecto vaciaría la lista. Sin migración, sin llamadas pagadas.

**RF-02b pantalla (2026-11-26, m-25119463, rama `feat/m-25119463-region-nicho-ui`):**
- **«Región»** es el quinto filtro, después de «Duración» (los cuatro de RF-02 no cambian de
  lugar). Opciones: «Todas» (primera, como en los demás filtros), «Colombia», «Venezuela» y
  «Uruguay». En la barra ancha es un chip más («Región» sin filtro, «Venezuela» con él); en
  la hoja «Filtros» del celular es un grupo más, con las mismas filas de radio que Canal y
  Duración, de 44 px. «Restablecer filtros» la deja en «Todas». Con «Todas» siguen las cuentas
  sin país conocido; con un país, solo las de ese país (la regla del backend). Cambiar la
  región es otra lectura de lo guardado, igual que los demás filtros: cero llamadas pagadas.
- **«Nicho: …»** es una línea de solo lectura con el rubro del Brand Kit
  (`reels_discovery.brand_niche_line` → `reviewed_reels.brand_niche`, con `tenant_session`).
  Va al final del grupo «Región», debajo de sus opciones y tras una línea fina, en el
  desplegable y en la hoja por igual. No es un chip ni una línea propia en la barra (regla de
  Deivid: nada solo en una fila). Se lee al abrir la pantalla; sin rubro, no se dibuja; otro
  negocio en la misma pestaña empieza sin ella.
- **Opciones B + C de Deivid (2026-11-26):**
  - **B.** En la barra ancha, «Quitar filtros» es un botón de solo ícono de 44 px
    (`rotate-ccw`, «Quitar filtros» en `aria-label` y `title`), al final de la fila, después
    de la lupa. En el pie del panel de la barra angosta sigue con sus palabras.
  - **C.** En la barra angosta, «Filtros» le pregunta al navegador al tocarlo si la ventana
    es de teléfono (640 px o menos, `matchMedia`). En el teléfono abre la hoja desde abajo;
    en una ventana más ancha, el mismo panel entra desde la derecha, como «Tus
    competidores». Son dos `drawer` del sistema y se abre uno. Al cerrarse, el foco vuelve a
    «Filtros».
  - **«Competidores»** sigue la misma regla de 640 px desde la barra ancha y desde la
    angosta (Deivid, 2026-11-26): abre desde abajo en el teléfono y desde la derecha en una
    ventana más ancha. Ya no depende de en qué barra está el botón. Al cerrarse, el foco
    vuelve al botón que lo abrió.
- **Cortes de la barra** (cuenta completa en `assets/qualify-creative.css`). Deivid midió en
  vivo los anchos naturales con «Compiten contigo» y «Venezuela» elegidos a la vez: 88 + 155
  + 88 + 98 + 108 + 133 + 44 + 116 + 7 × 12 ≈ 914 px. La estimación anterior era 918 px.
  Con «Quitar filtros» de 44 px queda en 842 px, así que la fila ancha pasa de 760 a
  **850 px** de contenido. El texto de «Buscar reels nuevos» sigue desde **1000 px**: 842
  + ~133 de las palabras ≈ 975 px; el ancho de las palabras es una estimación. Sin cubrir:
  tres o más valores largos a la vez (≈ 879 px con los cinco); entre 850 px y ese ancho, el
  chip más largo termina en «…».
- Sin migración, sin backend nuevo, sin llamadas pagadas.

**RF-09, backend (2026-11-25, `referentes/reel_badges.py`, fórmula `rb-1`):** sin migración
ni llamadas pagadas; se recalcula al leer, desde `public_reels` y `creators` (globales).
«En ascenso»: `lift` de `creators/metrics.py` (cm-1) ≥ 2,0 (el mismo `LIFT_HIGHLIGHT` de
«x2 sobre su media»), con la mediana de ≥ 3 reels medibles de la cuenta en 90 días. Ojo:
la cifra «xN sobre su media» de hoy usa otra mediana (reels de la corrida, ~30 días, sin
madurez), así que puede no coincidir con la insignia; para que coincidan, la pantalla
muestra `provenance.value`.
«Top 10 % de tu rubro»: vistas ≥ percentil 90 de los reels medibles de 90 días de las
cuentas del mismo `creators.rubro`; muestra mínima 30 reels de ≥ 3 cuentas; sin rubro (o
`otro`) nunca hay insignia; la pantalla debe pasar los rubros de la marca
(`DiscoverySeed.niches`) para que «tu rubro» sea cierto: solo se otorga en esos, y una
marca sin rubro conocido no recibe ninguna. Cada insignia lleva su procedencia (reel,
`rb-1`, `cm-1`, ventana, muestra, umbral).
La pantalla (RF-13) llama `reel_badges.badges_for_reviewed(...)` junto a `reviewed_reels`.

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

### RF-07b: búsqueda pagada de cuentas nuevas

Decisión de Deivid (2026-11-25, opción 1): el presupuesto propio de la búsqueda (50 créditos
al día y 200 al mes por negocio, en su zona horaria) cuenta **dentro** del tope general del
negocio (150/600). La puerta medida reserva cada crédito en ese tope antes de llamar. Se mide
con su propia feature, `discover_accounts_search` (migración 0185), para leerla aparte de
las demás. Por eso un día de muchas búsquedas puede dejar menos cupo para la corrida
semanal de ideas de los lunes. Es una puerta de dos vías: sacar la feature del tope general
es un cambio de código, sin migración. Cada búsqueda cuesta 1 crédito (≈ USD 0,0019), 2 como
máximo, y repetirla en la misma semana cuesta 0 porque la respuesta queda en
`vendor_payloads`. Código: `qualify_api.creators.discover_paid`.

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
