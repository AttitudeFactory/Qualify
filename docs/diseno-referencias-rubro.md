# Referencias por rubro entre negocios — diseño fase 1 (m-25091393)

Autor: principal-architect, 2026-11-23. Estado: **[PROPUESTO]**; D1, D2, D6 y D7 aprobados por
Raul (2026-11-23). **PR 1 fusionado** (PR 797, 2026-11-24): `ad_reference_facts` es la
migración **`0180`** (no `0179`, que ya estaba tomada). PR 2 y PR 3 esperan el ADR 51 y los
términos (m-24828985). Las secciones de abajo conservan el diseño original; donde difiere de lo
construido, manda el código (`qualify_api/ads/reference_facts.py`).

Objetivo: «las heladerías en Cúcuta pagan en promedio X por mensaje». Fase 1 = (1) registrar
desde el primer anuncio el rubro, el país y los resultados mensuales de cada promoción; (2) una
tabla agregada rubro × país × mes llenada por un proceso, que nunca identifica a un negocio;
(3) mostrar un grupo solo con K ≥ 5 negocios. Fase 2 (sembrar con el historial de las cuentas
que administra Attitude Factory, `ads_read`, como m-25091692) queda fuera; solo se le deja sitio.

Marcas: `[V]` verificado en el código con ruta; `[S]` fuente secundaria; `[H]` supuesto mío,
sin verificar.

---

## 1. Lo que ya existe (leído del código)

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| ¿De dónde sale el rubro hoy? | Dos campos en el JSONB `brand_kit_details.connect` (una fila por marca): **`sector`**, una clave de una **lista fija de 8** (`food_drink`, `fashion_beauty`, `fitness_health`, `travel_lifestyle`, `real_estate`, `technology`, `education`, `entertainment`) que llena el pre-llenado del Alta (`seed.niches[0]`) y el dueño aprueba en la propuesta; y **`rubro_text`**, **texto libre** («Tu rubro», m-25029206). | [V] `qualify_api/referentes/discovery_seed.py:194` `NICHE_LABELS`; `creative/brand_prefill.py:1224,1287`; `Qualify/brand_finish.py:100,333-351`; migración `0033` |
| ¿Lo tiene el perfil de inversión? | **No.** `ad_investment_profiles` (0176) guarda ticket, margen, clientes por semana, tope mensual, objetivo y moneda. Sin rubro. `budget_suggestion.py:25` lo dice: «shortcut: no rubro dimension». | [V] `ads/investment_profile.py`; `ads/budget_suggestion.py:25` |
| ¿Qué guarda la segmentación? | `ad_promotions.targeting` (JSONB de Meta) y `request_snapshot.audience_snapshot` con **una** `LocationOption` (`key`, `name`, `type` ∈ país/región/ciudad, `country_code` ISO-2 obligatorio). Un radio alrededor de un punto guarda el país del punto. El camino antiguo sin `audience` guarda solo `cities[{key}]`, sin país. | [V] `ads/audience.py:36-62,159-205,276-300`; `ads/wizard_workflow.py:169-183` |
| ¿País del negocio como respaldo? | `tenants.country` NOT NULL; también `connect.country_code` y `connect.city` (texto libre). | [V] migración `0001` línea 105; `creative/brand_context.py:114` |
| ¿Qué resultados se guardan? | `ad_promotion_insights`: **una fila por promoción y día** (PK `promotion_id, day`), `currency`, `metrics` JSONB con `spend, reach, impressions, clicks, ctr, cpc, cpm, actions[]`, `observed_at`, `pipeline_version='ad-results-v1'`. RLS normal. Se lee una ventana móvil de **28 días cerrados** (`until = ayer`, hora de la cuenta) cada 25 min. | [V] migración `0127`; `ads/results_service.py:455-490,535-575`; `ads/results.py:13` |
| ¿Quién lo llena? | `ads-reads-worker` (`reads_cli`): recorre negocios, `refresh_daily_account_health` + `poll_promotion_results`, un candado consultivo por negocio. **En producción está apagado** (`replicas: ${QUALIFY_ADS_READ_WORKER_REPLICAS:-0}`). | [V] `ads/reads_cli.py`; `deploy/docker-compose.prod.yml:528-553` |
| ¿Costo por conversación hoy? | **No se calcula.** Existen dos conteos posibles: (a) `promotion_conversation_count` = hilos distintos que Qualify atribuyó a la promoción (`ad_message_attributions`), solo si el chat llega a un canal conectado; (b) la acción de Meta `onsite_conversion.messaging_conversation_started_7d`, que ya viaja en `actions[]` porque se pide `actions`, pero cuyo nombre es solo `[S]` y **no se ha verificado en vivo** (ADR 25). m-25091391 decide la definición y está bloqueado. | [V] `ads/messaging_attribution.py:211-226`; `docs/discovery-asesor-inversion-meta.md:156` |
| ¿Unidad de `spend` en insights? | Decimal en la unidad mayor de la moneda de la cuenta. **[H] sin verificar en vivo**: las compensaciones de `money.py` (COP 1, USD/UYU 100) aplican a presupuestos y topes, no consta que apliquen a `spend` de insights. Verificar con una promoción real antes de convertir a centésimas. | [V] `ads/results.py:139` (`nonnegative(row.get("spend"))`); `ads/money.py` |
| ¿Hay tablas globales sin RLS? | Sí, con excepción escrita: `hashtags`/`hashtag_terms` (0023), `vendor_balance` (0117), `public_reel_analyses` (0119, excepción firmada); y puertas por rol con políticas `FOR SELECT TO <rol>` (0134, `reels_worker_read`). `global_session` existe para tablas globales. | [V] migraciones citadas; `qualify_shared/db/session.py:99-120`; `qualify_shared/db/reels_worker.py` |
| ¿Cuándo es final un mes? | Meta: los insights «no cambian después de 28 días». | [V] citado en `docs/discovery-asesor-inversion-meta.md` §6 |

---

## 2. Decisión central: un agregado entre negocios frente a «RLS en cada tabla»

| Opción | Qué es | A favor | En contra |
|---|---|---|---|
| **A. Mantener lo actual** | Sin agregado. `budget_suggestion` sigue con valores generales. | Cero trabajo, cero riesgo | No cumple el ticket |
| **B. Tabla global + rol dedicado** (recomendada) | Hechos por negocio en una tabla **con RLS normal**; un rol `qualify_ad_reference` (NOBYPASSRLS, sin `app.tenant_id`) los lee con una política `FOR SELECT TO qualify_ad_reference` y **solo inserta** en una tabla global `ad_reference_benchmarks` sin `tenant_id` ni RLS. `qualify_app` solo hace SELECT sobre ella. | Mismo patrón ya firmado (0119/0134). Ningún dato de un negocio sale de su tabla con RLS salvo hacia el rol que agrega. Lo publicado no tiene `tenant_id`, `brand_id` ni `promotion_id`. Ningún negocio puede falsificar una referencia (sin INSERT para `qualify_app`). Filas publicadas inmutables | Un rol y una puerta más (migración, `deploy/bootstrap_db_roles.py`, DSN). Requiere una excepción escrita a la regla |
| C. Igual que B pero con `admin_session` | El agregador lee con `qualify_admin` (BYPASSRLS) | Sin rol nuevo; `reads_cli` ya importa `admin_session` para listar negocios | `admin_session` es «solo alta y semilla»; BYPASSRLS lee **todo** de todos para una función de producto. Es justo lo que la regla de puertas prohíbe |
| D. Función SECURITY DEFINER o vista | Calcula el agregado al leer | Sin tabla agregada | No es «llenado por un proceso»; el número cambia en vivo cuando entra o sale un negocio (diferenciación inmediata); no se puede congelar |
| E. Copias por negocio | El proceso escribe el agregado publicado en la tabla de cada negocio, con RLS | Cumple la regla al pie de la letra | Escribe N copias con una puerta que cruza negocios de todos modos (admin o un bucle de sesiones), riesgo de copias distintas, más código. No reduce la exposición frente a B |

**Recomendación: B.** La regla protege los datos de un negocio. Una fila que no tiene ningún
identificador de negocio y que solo publica un rol que no puede escribir nada más es el mismo caso
que `hashtags` y `public_reel_analyses`. Necesita una **ADR corta con excepción** (borrador en
§9). No es la excepción del 2026-11-04 (§1.6, procedencia de filas aprobadas una a una): esta es
una excepción a la regla de RLS, como la de 0119.

---

## 3. Rubro: qué campo y con qué granularidad

Números reales: hoy hay unos 7 negocios en 3 países, y ninguno tiene anuncios. Para «Comida y
bebida × CO × COP × mes» se necesitan 5 negocios de comida con anuncios **en el mismo mes**.
Un rubro fino («heladería») no llenará K = 5 en mucho tiempo.

| Opción | Qué es | Trabajo | Se agrupa bien | Primer grupo publicable |
|---|---|---|---|---|
| **R1. `connect.sector` actual** (recomendada en fase 1) | La lista fija de 8 ya existe y el dueño la aprueba en la propuesta | Ninguno en el esquema; validar el valor contra `NICHE_LABELS` | Sí (lista fija) | El más temprano posible |
| R2. Lista fija nueva de dos niveles | `sector → rubro` (≈25 rubros: heladería, comida rápida, inmobiliaria, agencia de viajes…). Columna `brands.ad_rubro text NULL` + `ad_rubro_set_by`, `ad_rubro_set_at`. Una pregunta en «Tu marca», sugerida desde `rubro_text` con la misma técnica de palabras que `brand_answers_vm._RUBRO_WORDS`; el dueño la confirma (entrada manual, §1.6) | 1 columna + 1 pregunta en pantalla | Sí | Muy tarde; y publicar dos niveles exige comprobar el complemento (§5) |
| R3. `rubro_text` libre | Texto del dueño | Ninguno | **No**: no se puede agrupar sin normalizar | Nunca |

**Recomendación: R1 para publicar.** Guardar en el hecho la clave de `sector` del momento. R2
solo cuando un grupo `sector × país × mes` tenga al menos 2K = 10 negocios, que es lo que hace
falta para partirlo en dos subgrupos de 5. El mensaje al dueño sería entonces «negocios de comida
y bebida en Colombia», no «heladerías en Cúcuta». **Decisión D1.**

`sector` vacío o fuera de la lista → el hecho se guarda con `sector NULL` y no entra en ningún
grupo.

---

## 4. País, ciudad, moneda y objetivo

- **País:** el de la segmentación (`audience_snapshot.location.country_code`). Es donde se pagan
  las impresiones. Un negocio de Cúcuta que anuncia en San Cristóbal cuenta en VE. Para el camino
  antiguo, que guarda solo la ciudad, se usa `tenants.country` y queda `geo_source='tenant'`.
  **[H]** Supongo que cada promoción tiene **una** ubicación (`AudienceDraft.location` es un solo
  valor). Con públicos personalizados conviene comprobarlo.
- **Ciudad:** se guarda la `key` de Meta cuando `location.type='city'`, pero **no se publica en
  fase 1**. Publicar a la vez país y ciudad permite restar (país − ciudad = el resto, que puede
  tener menos de K). Si algún día se publica, se publica solo cuando la ciudad **y** su
  complemento tienen K cada uno.
- **Moneda:** forma parte de la clave del grupo. Nunca se mezclan monedas. La moneda es la de la
  cuenta (`ad_promotions.currency`, siempre igual a la de las filas de insights). Una cuenta en
  USD en Colombia forma su propio grupo.
- **Objetivo:** también forma parte de la clave (`ad_promotions.objective`, valor de Meta tal
  cual). El CPM y el CPC cambian mucho según la meta de optimización, y el costo por conversación
  solo tiene sentido con objetivo de mensajes. **[H]** Falta confirmar qué valores de `objective`
  guardan hoy «chat», «website» y «lead». Esto divide los grupos por 3, aunque la mayoría de los
  negocios pequeños usará mensajes. **Decisión D2.**

Clave del grupo: `(source, sector, country_code, currency, objective, month)`.

---

## 5. Métricas, umbrales y anonimato

**Por negocio y mes** (suma de sus promociones en el grupo; mes calendario en la zona horaria de
la cuenta, porque así vienen los días):

| Métrica | Cálculo | Mínimo para que el negocio cuente [H] |
|---|---|---|
| CPM | Σ gasto / Σ impresiones × 1000 | ≥ 1.000 impresiones |
| CPC | Σ gasto / Σ clics (todos, como `clicks` de Meta) | ≥ 20 clics |
| Costo por conversación | Σ gasto (objetivo de mensajes) / Σ conversaciones | ≥ 5 conversaciones; **no se publica hasta que m-25091391 fije la definición** (Meta `messaging_conversation_started_7d` frente a hilos observados). Los dos conteos se guardan desde ya |

Nunca se promedian los `cpm`/`cpc` diarios que da Meta: siempre se trabaja con cocientes de sumas.

**Número del grupo:** **media recortada de los valores por negocio**. Cada negocio cuenta una
vez. Se quitan `floor(0,2·n)` valores por cada extremo (con n = 5, el mayor y el menor) y se
promedian los demás. Se descartó la mediana: con n = 5 la mediana *es* el valor exacto de un
negocio. Se descartó el cociente de sumas: lo domina quien más gasta. El número se muestra
redondeado a 2 cifras significativas con `money_display` («$1.200 COP»).

**Reglas de publicación** (todas por métrica):

1. **K:** al menos 5 negocios distintos (`tenant_id`) que pasen el mínimo. Por debajo no se
   escribe ninguna fila: ni el número ni el conteo.
2. **Dominancia:** se suprime el grupo si un solo negocio pone más del 50 % del gasto
   elegible [H]. La media recortada ya le quita peso, pero esta regla evita publicar «un negocio
   grande y cuatro casi vacíos».
3. **Solo meses cerrados:** el mes M se construye cuando su último día tiene más de 28 días
   (cuando Meta ya no cambia los insights). La referencia llega con unas 4 semanas de retraso.
4. **Inmutable:** `INSERT … ON CONFLICT DO NOTHING`, sin permiso de UPDATE ni DELETE. Si un
   negocio se va (desconecta, se purga o se borra), lo ya publicado no se recalcula. Así salir
   no deja una diferencia que se pueda restar.
5. **Una sola partición por mes:** solo `sector × país × moneda × objetivo`. Sin fila «todos los
   objetivos», sin ciudad y sin rubro fino. Cualquier nivel que se solape necesita la regla del
   complemento (§4).
6. **El negocio del propio dueño:** **entra en el cálculo** (un único número para todos; si cada
   dueño viera una versión distinta, habría más formas de restar). Pero a un dueño que
   contribuyó al grupo solo se le muestra si `n − 1 ≥ K` (cinco negocios *además* del suyo). Su
   pantalla sabe si contribuyó aplicando los mismos mínimos a sus propios hechos, que puede leer
   con RLS. No hace falta escribir nada de vuelta.
7. **No se muestra n.** Si se mostrara, se podría seguir quién entra y quién sale mes a mes. La
   fila guarda `n_*` solo para la regla 6 y para auditoría.

**Riesgo abierto (D3):** K cuenta **negocios** (`tenant_id`). Con ADR 43 (un login, varios
negocios) y con los negocios que opera Attitude Factory, una misma persona puede controlar 4 de
los 5 negocios de un grupo y deducir el quinto. Opciones: contar por titular (login dueño, cuando
exista ADR 43) o por portafolio de Meta (`social_connections.client_business_id`, 0170, hoy NULL
en todas las conexiones). En fase 1 recomiendo contar por negocio y abrir la regla cuando se
construya ADR 43.

---

## 6. Esquema propuesto (próxima migración, `0179` contra `origin/main` al implementar)

### `ad_reference_facts` — por negocio, RLS normal

| Columna | Tipo | Nota |
|---|---|---|
| `tenant_id` | uuid NOT NULL | RLS `NULLIF(current_setting('app.tenant_id', true), '')::uuid`, ENABLE + FORCE |
| `promotion_id` | uuid | PK (`promotion_id`, `month`); FK (`promotion_id`, `tenant_id`) → `ad_promotions` ON DELETE CASCADE |
| `month` | date | primer día del mes (hora de la cuenta) |
| `brand_id` | uuid NOT NULL | |
| `sector` | text NULL | copia de `connect.sector` validada contra `NICHE_LABELS`; NULL = no entra |
| `sector_read_at` | timestamptz | procedencia: cuándo se leyó |
| `country_code` | char(2) NOT NULL | CHECK `^[A-Z]{2}$` |
| `geo_source` | text | `targeting` \| `tenant` |
| `city_key` | text NULL | clave de ciudad de Meta, no se publica en fase 1 |
| `currency` | text NOT NULL | CHECK `^[A-Z]{3}$` |
| `objective` | text NOT NULL | |
| `spend_minor` | bigint NOT NULL | centésimas (ver unidad [H] en §1) |
| `impressions`, `clicks` | bigint NOT NULL | |
| `conversations_meta` | int NULL | acción de Meta; NULL si no vino |
| `conversations_observed` | int NULL | hilos de `ad_message_attributions` |
| `days` | int | días con insights sumados |
| `source_observed_at` | timestamptz | max `ad_promotion_insights.observed_at` (procedencia) |
| `source_pipeline_version` | text | `ad-results-v1` |
| `pipeline_version` | text NOT NULL | `ad-reference-facts-v1` |
| `closed` | bool NOT NULL default false | true cuando el mes es final; el upsert lleva `WHERE NOT ad_reference_facts.closed` |
| `updated_at` | timestamptz | |

Permisos: `qualify_app` SELECT/INSERT/UPDATE (lo escribe la pasada por negocio con
`tenant_session`). `qualify_ad_reference`: política `ad_reference_read FOR SELECT TO
qualify_ad_reference USING (true)` y GRANT SELECT **por columna** sobre todo menos
`promotion_id`, `brand_id` y `city_key`.

### `ad_reference_benchmarks` — global, sin `tenant_id` ni RLS (excepción §9)

| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid PK | |
| `source` | text NOT NULL | CHECK IN (`qualify_clients`, `managed_seed`): `managed_seed` queda reservado para fase 2 con su propia etiqueta |
| `sector`, `country_code`, `currency`, `objective`, `month` | | clave del grupo |
| `method_version` | text NOT NULL | `ad-reference-v1` (K, mínimos, recorte, dominancia) |
| `cpm_minor`, `cpc_minor`, `cost_per_conversation_minor` | bigint NULL | NULL = esa métrica no llegó a K |
| `cpm_n`, `cpc_n`, `conversation_n` | int NULL | CHECK ≥ 5 cuando la métrica no es NULL; nunca se muestran |
| `conversation_definition` | text NULL | p. ej. `meta_messaging_started_7d`; NULL hasta m-25091391 |
| `facts_pipeline_version` | text NOT NULL | |
| `facts_digest` | text NOT NULL | sha256 de los hechos usados (claves y valores ordenados): procedencia comprobable sin poner ids de negocios en una tabla global |
| `built_at` | timestamptz NOT NULL | |

UNIQUE (`source`, `sector`, `country_code`, `currency`, `objective`, `month`, `method_version`)
→ clave de idempotencia. GRANT: `qualify_ad_reference` SELECT + INSERT; `qualify_app` y
`qualify_admin` SELECT. Nadie tiene UPDATE ni DELETE (el `downgrade` borra la tabla).

Volumen: unas 50 empresas × 4 promociones/mes × 1,5 meses ≈ 300 hechos/mes, **≈ 3.600 filas al
año** [H]. Referencias: como máximo 8 × 3 × 3 × 3 × 12 ≈ 2.600 al año; en la práctica, decenas.
**Costo por cliente al mes: US$0.** No hay llamadas nuevas a Meta ni a ningún proveedor: todo
sale de filas que ya se guardan.

---

## 7. El proceso

| Paso | Puerta | Cuándo | Idempotencia | Procedencia |
|---|---|---|---|---|
| **Hechos por negocio** | `tenant_session(tenant)`, dentro de `reads_cli.tick` después de `poll_promotion_results` (mismo candado por negocio) | Cada pasada del `ads-reads-worker` (60 s; solo recalcula meses no cerrados, como máximo 2 por promoción) | PK (`promotion_id`, `month`) + upsert con guarda `NOT closed` | `source_observed_at`, `source_pipeline_version`, `sector_read_at`, `pipeline_version` |
| **Referencias** | puerta nueva `qualify_shared/db/ad_reference.py` (rol `qualify_ad_reference`, DSN `QUALIFY_AD_REFERENCE_DSN`, NOLOGIN hasta tener contraseña, como `reels_worker.py`). Solo la puede importar `qualify_api.ads.reference_build` (prueba estática) | En el mismo bucle de `reads_cli`, como máximo una vez al día: `pg_try_advisory_lock` global y salida inmediata si el mes cerrado ya tiene filas `method_version` | UNIQUE del grupo + `ON CONFLICT DO NOTHING` | `method_version`, `facts_pipeline_version`, `facts_digest`, `built_at` |

- Hace falta cerrar los hechos (`closed = true`) antes de construir: los cierra el paso por
  negocio cuando `último_día(M) + 28 días < hoy`. El constructor solo lee `closed`.
- **Desde qué fecha:** solo promociones con `approved_at ≥ QUALIFY_AD_REFERENCE_FROM` (la fecha
  en que los términos con la cláusula del §8 estén publicados). Sin esa fecha, el paso no
  escribe nada. Así nada se usa de forma retroactiva.
- **Dependencia operativa:** `ads-reads-worker` está en `replicas: 0` en producción. Sin él no
  hay insights ni hechos. Encenderlo es una decisión de `qualify-prod-ops`
  (`deploy/ads-reads-worker.md`) que ya hace falta para los resultados.

**Lectura del dueño:** `qualify_api.ads.reference.load_reference(tenant_id=, brand_id=)` con
`acting_login` (como el resto de pantallas de anuncios). Con un único `tenant_session`, porque
la tabla global la puede leer `qualify_app` sin `app.tenant_id` especial:
1. lee el `sector` de su marca, el país y la moneda de su última promoción (o los de la cuenta
   elegida y `tenants.country`), y el objetivo;
2. lee la última referencia cerrada del grupo con `source='qualify_clients'`;
3. comprueba con sus propios hechos si contribuyó, y aplica la regla 6;
4. devuelve `None` (pantalla vacía, sin cifras inventadas) o
   `{mes, métrica, valor_redondeado, fuente}`.

No hace falta tocar `global_session` ni su prueba de exclusividad.

---

## 8. Términos y consentimiento — para el fundador (no lo decido)

El borrador de m-24828985 (`docs/anuncios-autorizacion-borrador.md`) **no dice nada** de usar
los resultados de un negocio, aunque sea anonimizados, para referencias de otros negocios. Además
no hay una página de términos publicada en la app (lo dice el mismo borrador). Puntos para la
revisión jurídica:

- ¿Hace falta una cláusula? Recomiendo que sí, antes del primer anuncio de un cliente. Texto de
  partida para el abogado: «Usamos los resultados de tus anuncios (costos por mil impresiones, por
  clic y por conversación), combinados con los de al menos otros cuatro negocios y sin datos que
  te identifiquen, para mostrar referencias por rubro y país. Nunca mostramos los resultados de un
  negocio por separado.»
- ¿Aviso, consentimiento expreso (opt-in) o derecho de exclusión (opt-out)? Un opt-out costaría
  una columna y un filtro; un opt-in reduce mucho la probabilidad de llegar a K.
- Si un negocio pide borrar sus datos, sus hechos se borran en cascada, pero las referencias ya
  publicadas no se recalculan (regla 4). ¿Es aceptable con las leyes 1581 (CO) y 18.331 (UY) y
  en Venezuela cuando el negocio es una persona natural?
- Fase 2: si las cuentas de terceros que administra Attitude Factory se pueden usar para sembrar
  referencias depende del contrato de agencia de cada cliente, no de estos términos.

---

## 9. Borrador de ADR (fila corta para §6 de `docs/arquitectura.md`)

> | 51 | **[PROPUESTO — principal-architect, 2026-11-23 · m-25091393]** **Referencias de anuncios entre negocios: hechos con RLS, una tabla global solo de agregados y un rol que solo publica.** Los resultados mensuales de cada promoción se copian a `ad_reference_facts` (RLS normal, `tenant_session`). Un rol `qualify_ad_reference` (NOBYPASSRLS, sin `app.tenant_id`, política `FOR SELECT TO` en esa tabla y permisos por columna) construye `ad_reference_benchmarks`. **Excepción a «RLS en cada tabla»**, como 0023 y 0119: la tabla no tiene `tenant_id`, `brand_id` ni `promotion_id`; solo publica grupos con al menos 5 negocios, por media recortada, solo meses cerrados e inmutables, en una única partición `sector × país × moneda × objetivo × mes`. `qualify_app` solo lee. **Descartadas:** `admin_session` (BYPASSRLS para una función de producto), función SECURITY DEFINER o vista (cálculo en vivo, se puede restar al salir un negocio), copias por negocio (más código, misma exposición). **Se reabre si:** se publica un segundo nivel que se solape (ciudad o rubro fino; exige regla de complemento), se construye ADR 43 (K por titular), se siembra fase 2 (`source='managed_seed'`), o la revisión jurídica de m-24828985 exige opt-in. |

Además: una línea en §7 (riesgos), «reidentificación por diferencia o por control de varios
negocios del grupo», que apunte a este ADR.

---

## 10. PRs, orden y pruebas

| # | PR | Área | Tamaño | ¿Antes de que un cliente tenga anuncios? |
|---|---|---|---|---|
| 0 | ADR 51 en `docs/arquitectura.md` §6/§7 + cláusula en `docs/anuncios-autorizacion-borrador.md` | architect | S | Sí, y es requisito de los demás |
| 1 | `0179` `ad_reference_facts` (RLS) + paso de hechos en `reads_cli.tick` + `QUALIFY_AD_REFERENCE_FROM` | backend | M | **Sí**: registra desde el primer anuncio |
| 2 | `0180` `ad_reference_benchmarks` + rol `qualify_ad_reference` + puerta + `reference_build` + `bootstrap_db_roles.py`/compose/`.env.prod.example` | backend + platform | M–L | Sí. No publica nada hasta K |
| 3 | `ads.reference.load_reference` + tarjeta en la pantalla de resultados (vacía por debajo de K) | backend + reflex-ui + UX | S–M | Se puede dejar para cuando el constructor registre su primer grupo publicable; antes solo mostraría el estado vacío |

PR 1 y PR 2 se pueden unir si un solo ingeniero lleva la numeración. Total: unos 3 PRs, unos
3–4 días de ingeniería [H].

**Pruebas de aceptación**

1. `-m db`: el negocio A no lee los hechos de B con `tenant_session`; `qualify_ad_reference` lee
   los hechos pero no `promotion_id`, `brand_id` ni `city_key` (permission denied), y no puede
   leer `ad_promotions` ni `ad_promotion_insights`.
2. `-m db`: `qualify_app` no puede hacer INSERT/UPDATE/DELETE en `ad_reference_benchmarks`;
   `qualify_ad_reference` no puede hacer UPDATE/DELETE.
3. Grupo con 4 negocios elegibles → ninguna fila; con 5 → una fila; volver a ejecutar → sigue
   habiendo una fila (idempotencia).
4. Un negocio con más del 50 % del gasto → la métrica se suprime.
5. Media recortada: con 5 valores conocidos el resultado es la media de los 3 centrales y no
   coincide con ningún valor individual del caso de prueba.
6. Monedas: un negocio en USD y cuatro en COP del mismo sector y país → ningún grupo llega a K.
7. Mes abierto (último día hace menos de 28 días) → no se construye; hechos `closed` no se
   modifican con un upsert posterior.
8. Un negocio se purga después de publicar → la fila publicada no cambia.
9. Lectura del dueño: con n = 5 y él dentro → `None`; con n = 6 y él dentro → valor; sin
   referencia → `None`, sin cifra.
10. Promoción aprobada antes de `QUALIFY_AD_REFERENCE_FROM` → ningún hecho.
11. Migraciones: `upgrade → downgrade base → upgrade` en CI; `test_rls_policy_shape` sigue
    pasando (la tabla global no tiene `tenant_id`).
12. En vivo, antes de PR 1, con una promoción real (ADR 25): unidad de `spend` en insights y
    nombre de la acción `onsite_conversion.messaging_conversation_started_7d`.

---

## 11. Decisiones pendientes

| # | Decisión | Quién | Recomendación |
|---|---|---|---|
| D1 | Granularidad del rubro: `sector` actual (8) o lista fina nueva | Raul / fundador | `sector` en fase 1; lista fina cuando un grupo llegue a 10 |
| D2 | El objetivo forma parte de la clave del grupo | Raul | Sí |
| D3 | K por negocio, por titular o por portafolio de Meta | fundador | Por negocio ahora; reabrir con ADR 43 |
| D4 | Cláusula en términos; aviso, opt-in u opt-out; borrado frente a inmutabilidad | fundador + abogado (m-24828985) | Cláusula + aviso antes del primer anuncio de un cliente |
| D5 | Firmar ADR 51 (excepción a RLS) | fundador | Firmar |
| D6 | Mínimos por negocio (1.000 impresiones / 20 clics / 5 conversaciones) y dominancia 50 % | Raul | Valores [H]; versionados en `method_version` |
| D7 | Encender `ads-reads-worker` en producción | Herwin (m-25103462, Raul no tiene acceso al servidor) | Ya hace falta para los resultados |

Estado 2026-11-24: D1, D2 y D6 aprobados por Raul tal como se recomiendan; D7 asignado a Herwin
en m-25103462; D3, D4 y D5 pendientes del fundador.
