# Diseño del módulo «Creadores» — frontera, esquema y contrato de la Entrega 1

**Fecha:** 2026-11-04 · **Autor:** principal-architect · **Estado:** `[PROPUESTO — pendiente de firma del fundador]`, junto con **ADR 45** (`docs/arquitectura.md` §6), que enmienda ADR 33.
**Decisión de origen:** el fundador (Herwin) decidió el 2026-11-04 construir el módulo en 5 entregas, solo Instagram al principio. Épica Meegle: la Feature m-24880379 («Invitaciones a influencers locales», PM Deivid) pasa a ser la épica madre.
**Documentos hermanos (se escriben en paralelo, no se tocan desde aquí):** `docs/epica-creadores.md` (historias) y `docs/ux-creadores.md` (pantallas y textos).
**Insumos leídos:** ADR 33 y `docs/modulo-creator-fit-estrategia.md`; ADR 34, 42 y 44; migraciones 0034, 0036, 0117, 0119 y 0121; `qualify_api/creators/`, `qualify_api/vendors/scrapecreators.py`, `qualify_api/referentes/{reel_store,reel_runs,reels}.py`, `qualify_api/growth/`, `qualify_api/conversations/`, `qualify_api/inbox/models.py`, `Qualify/creators_page.py`, `Qualify/ui/layout.py`, `Qualify/creator_discovery.py`; el corpus de Meta en `reference/meta-instagram-platform/`.

> **Para quien construye la Entrega 1:** el contrato está en §7 (migración), §8 (lectura pagada), §9 (métricas) y §10 (funciones que llama la pantalla). Lo demás explica por qué es así.

---

## 1. Qué cambia respecto de ADR 33

ADR 33 (firmado 2026-08-10) dijo tres cosas que este diseño toca:

| ADR 33 decía | Qué pasa ahora | Por qué no es una contradicción silenciosa |
|---|---|---|
| (a) «Creator Fit» **no es un módulo**: no hay schema propio, porque las tres funciones escribían en schemas ajenos | **Sí hay módulo**: `qualify_api.creators` gana tablas propias por negocio (seguimiento, campañas, candidatos, ofertas) | El criterio de ADR 33 era el de ADR 1: un módulo es estado propio + eventos. En agosto no había estado propio; ahora lo hay (campaña → candidato → oferta → acuerdo). Se aplica el mismo criterio a hechos nuevos |
| (c) la lista corta es una entidad colgada de `brand_id`, con `source_id`; nunca un perfil agregado sin fuentes | **Se conserva**: `campaign_candidates` cuelga de la marca, y cada razón del encaje cita reels concretos (§6.3) | No hay schema `crm` en el código; la entidad vive en `public`, como todo lo demás |
| Aclaración del fundador: **E3 eliminada** — «el contacto con influencers se queda manual dentro del servicio de agencia — no se automatiza» | **Entra al software el contacto asistido**: borrador de invitación, oferta, historial de negociación y sugerencias de respuesta. **Qualify nunca envía el primer mensaje**; el dueño lo copia y lo manda desde su teléfono | Es una enmienda explícita (ADR 45). Lo que se mantiene de la aclaración: **nada se automatiza**. El primer contacto sigue siendo manual; las respuestas, cuando el creador ya escribió, van por la bandeja asistida que ya existe |

Lo que **no** cambia: (b) la API de Creator Marketplace, si algún día se usa, entra por `connections` + la matriz C-05; (d) la compuerta G-JOIN (identidad TikTok↔Instagram) sigue cerrando la puerta a TikTok en este módulo; QUA-70-C sigue descartado (sin cuentas de creadores, sin pagos, sin contratos firmados).

## 2. La restricción de Meta que da forma a la Entrega 3 (verificada en el corpus)

**Un negocio no puede escribirle primero a una persona por Instagram Direct desde la API.** Verificado contra el corpus cosechado de la documentación oficial (cosecha del 2026-07-24, `reference/meta-instagram-platform/manifest.jsonl`):

1. `reference/meta-instagram-platform/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api.md`, línea 36 — Meta dice que la app solo puede enviar un mensaje a un usuario de Instagram después de que ese usuario le haya escrito a la cuenta profesional, y que tiene 24 horas para responder.
2. `reference/meta-instagram-platform/documentation/business-messaging/instagram-messaging/overview.md`, líneas 26–28 — el mismo modelo en la ruta de Facebook Login (la que usa Qualify, ADR 25): la conversación empieza cuando la persona escribe; la app tiene 24 horas, ampliables solo con la etiqueta de agente humano.
3. `reference/meta-instagram-platform/documentation/instagram-platform/private-replies.md`, líneas 39–42 — la única excepción: **una** respuesta privada a quien comentó en una publicación propia, dentro de 7 días; los mensajes siguientes solo si la persona responde.

**WhatsApp:** un mensaje que inicia el negocio exige plantilla aprobada y consentimiento previo de la persona (la regla que ya aplica `whatsapp_opt_ins`, migración 0060). Un creador que nunca habló con el negocio no dio ese consentimiento. **Correo:** enviar en nombre del negocio desde nuestro dominio es infraestructura de envío en frío (comprar, Fase 5) y riesgo de reputación del dominio.

**Consecuencia de diseño:** la Entrega 3 deja el envío en manos del dueño (copiar el texto, mandarlo desde su teléfono, marcar «Invitado»). Cuando el creador responde al Direct o al WhatsApp del negocio, el hilo entra por el módulo `conversations`, que ya existe, y la ventana de 24 h queda abierta: desde ahí las respuestas sugeridas pasan por la bandeja de salida aprobada, igual que hoy. **Es la regla 4 (asistido, nunca autónomo) y además es lo único que Meta permite.**

> Se reabre si Meta habilita mensajes iniciados por la marca hacia creadores (por ejemplo, dentro de la Creator Marketplace API con su App Review propio): esa puerta entraría por `connections`, según ADR 33 (b).

## 3. Frontera de módulo — decisión

**Decisión: se extiende `packages/api/src/qualify_api/creators/`.** Hoy es el banco global de cuentas públicas (migración 0036: `vendor_payloads`, `creators`, `creator_sightings`). Gana una mitad por negocio, con RLS.

| Opción | Qué sería | Por qué se descarta o se elige |
|---|---|---|
| **A. Extender `creators` (elegida)** | La mitad global (dato público) y la mitad por negocio de la misma entidad, en un solo módulo | Mismo patrón que `referentes/reel_store.py`, que ya junta tablas globales y por tenant de una misma cosa. La regla de módulo de ADR 31 (cada módulo escribe su parte) se cumple: las tablas nuevas son de `creators` y de nadie más |
| B. Módulo nuevo `influencers` o `creator_fit` | Tablas por negocio en un paquete aparte | Partiría la misma entidad (la cuenta pública y lo que un negocio hace con ella) en dos módulos, y el nuevo leería y escribiría las tablas globales de `creators`. Es la «fachada» que ADR 33 (1) criticaba, al revés |
| C. Dentro de `leads` | Candidatos como un tipo de lead | `leads` es **demanda**: clientes del negocio que llegan por el formulario y por la intención de compra (`lead_form_settings`, `leads`). Un creador es **oferta**: alguien a quien el negocio contrata. El ciclo de vida (invitar, ofertar, negociar) y quien lo consume (no Conversaciones/intención) son otros; mezclarlos ensucia las cifras de leads |
| D. Un schema `crm` | Lo que imaginó ADR 33 (c) | No existe en el código ni en las migraciones. Crearlo para tres tablas agrega una convención sin beneficio. La sustancia de (c) —colgado de la marca, con fuentes— se respeta en `public` |

**Dependencias permitidas:** `creators` usa la API pública de `referentes.reel_store` para `public_reels` y `reel_accounts` (tablas de 0117 que son de `referentes`) en vez de escribir SQL propio sobre ellas; usa `vendors.scrapecreators` (la puerta medida) y `vendors.usage` (nuevo, §8.4). La Entrega 3 y la 5 leen y enlazan `threads` del módulo `inbox`/`conversations` por su API, nunca escribiendo sus tablas. **Ningún otro módulo escribe las tablas de `creators`.**

> **Consolidación posible, fuera de este alcance:** `public_reels` y `reel_accounts` describen cuentas públicas, como `creators`. Si un tercer módulo llega a necesitarlas, conviene mudarlas a `creators`. Hoy no se mueve nada.

## 4. Qué queda global y qué es de cada negocio

**Global, sin `tenant_id` ni RLS (dato público; misma regla que 0023, 0036, 0117 y 0119):** `vendor_payloads`, `creators`, `creator_sightings`, `reel_accounts`, `public_reels`, `public_reel_analyses` y las dos tablas nuevas de §5: `creator_snapshots` y `public_reel_reads`.

**La regla de 0117 sigue mandando, y se extiende a las tablas nuevas:** ninguna tabla global gana una columna que nombre un tenant, una marca o un usuario, ni registra quién pidió, siguió o miró una cuenta. Que una fila exista dice solo que algún negocio la leyó, nunca cuál. Un test estructural (como `test_public_reels_db.py`) lo fija para `creator_snapshots` y `public_reel_reads`.

**Por negocio, con `tenant_id NOT NULL` + `ENABLE` + `FORCE` + la política `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`:** `tracked_creators` (E1), `creator_campaigns` y `campaign_candidates` y `candidate_fit_scores` (E2), `candidate_invitations` (E3), `candidate_offers` (E4–E5), y `vendor_usage_events` (ya existe, 0117). Toda fila de marca lleva la FK compuesta `(brand_id, tenant_id) → brands (id, tenant_id)` (`uq_ads_brand_tenant`, 0114), igual que las tablas de 0117.

**Por qué el seguimiento es por marca y no por tenant:** la campaña es de una marca (su producto viene del catálogo de esa marca) y los referentes de 0117 ya son por marca. Un dueño con dos marcas en el mismo negocio sigue a un creador por marca; la lectura pagada es global, así que no paga dos veces.

### 4.1 Una fuga lateral que se acepta, nombrada

Si el negocio B agrega a `@x` y existe una lectura de menos de 24 h, B la recibe sin costo y ve «Datos de hace 3 horas». B puede deducir que **algún** negocio miró a `@x` hoy. No sabe cuál. ADR 42 tiene la misma fuga con los referentes. Mitigación barata en E1: la ficha muestra la fecha de la lectura **por día** («Datos de hoy», «Datos de ayer»), nunca la hora. Se reabre si un cliente lo señala o si un creador pequeño de una ciudad con un solo negocio cliente lo vuelve identificable; la alternativa entonces es leer por negocio y pagar dos veces.

## 5. Historial de métricas — decisión

**El problema:** `public_reels` sobrescribe los contadores (con la guarda monotónica de `metrics_at`), y `vendor_payloads` guarda solo la última respuesta por consulta. Sin filas de historial, la lectura de hoy borra la de la semana pasada, y **ningún proveedor vende ese historial** (`growth/organic.py`, 0034). La Entrega 4 necesita congelar «la mediana real con la que se hizo la oferta», y la comparación necesita saber de cuándo es cada número.

| Opción | Qué es | Veredicto |
|---|---|---|
| A. Reusar `creator_reads` / `creator_post_reads` (0034, `qualify_api.growth`) | Tablas por tenant, solo agregar filas | **Descartada.** Por tenant: dos negocios que siguen al mismo creador tendrían dos historiales a medias y pagarían dos lecturas, lo contrario de 0036/0117. No tienen procedencia (ni payload ni versión de parser), ni `saves`, ni audio, ni colaboraciones. Siguen siendo de la cuenta propia del Brand Kit (`source = 'profile'`), sin cambios |
| **B. Tablas globales nuevas, solo agregar filas (elegida)** | `creator_snapshots` (una fila por lectura de una cuenta) y `public_reel_reads` (una fila por reel en esa lectura) | Dato público, compartido, con la procedencia de cada contador. Cumple la regla de 0117 (§4) |
| C. Sin historial; calcular siempre sobre `public_reels` | Cero tablas | La oferta no podría citar el número con que se calculó y la comparación mezclaría lecturas de fechas distintas sin decirlo |

**Volumen (calculado, entradas `[H]`):** una lectura = 1 fila de `creator_snapshots` + hasta 48 de `public_reel_reads`. Con 20 negocios × 30 lecturas al mes: 7.200 lecturas y ~346.000 filas al año; con 200 negocios, ~3,5 M filas al año. Lejos del umbral de ADR 31 (100 M). Sin purga en E1; se reabre a los 20 M de filas.

**El payload crudo:** cada página se guarda en `vendor_payloads` (y en R2 cuando pase de 100 KB, R6 de ADR 42). Como esa fila se reescribe en la siguiente lectura de la misma consulta, cada fila de historial fija **qué** respuesta leyó con `source_payload_id` + `source_payload_fetched_at` (la misma regla que 0117 para `public_reels`): un re-parseo confía en el payload solo mientras su `fetched_at` coincide. Los contadores ya extraídos quedan para siempre en las filas de historial; lo que se pierde al reescribir es la posibilidad de re-parsear campos **todavía no leídos** de lecturas viejas. Límite aceptado y escrito; se reabre si un campo nuevo necesita historia (entonces: archivar cada página en R2 bajo un prefijo global `public/creator-reads/`, ≈ 300 KB por lectura comprimida).

## 6. Tablas de las cinco entregas

Convenciones para todas las tablas por negocio de este módulo: `id uuid` con `gen_random_uuid()`, `tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE`, `brand_id uuid NOT NULL` con FK compuesta a `brands (id, tenant_id)` ON DELETE CASCADE, `UNIQUE (id, tenant_id, brand_id)` como destino de las FK compuestas de las tablas hijas (así una fila nunca cuelga de otra marca, ni siquiera dentro del mismo negocio — patrón de 0117), RLS `ENABLE` + `FORCE` + política `NULLIF` en la misma revisión, `GRANT` a `qualify_app` y `SELECT` a `qualify_admin`. Los nombres de los estados son códigos en inglés; la pantalla los traduce (`qualify-copy-es`).

### 6.1 Entrega 1 — Analizar y comparar

Global (§5): `creator_snapshots`, `public_reel_reads`; columnas nuevas en `public_reels`. Por negocio: `tracked_creators`. Detalle de columnas en §7.

### 6.2 Entrega 2 — Encajar

**`creator_campaigns`** (por marca). El nombre evita chocar con `campaigns` (0045), que agrupa publicaciones del calendario.

| Columna | Tipo | Nota |
|---|---|---|
| `name` | text NOT NULL | único por marca sin distinguir mayúsculas |
| `goal` | text NOT NULL | CHECK `('visits','sales','launch','awareness')` — lista cerrada, la traduce la pantalla |
| `product_id` | uuid NULL | FK compuesta `(product_id, tenant_id) → brand_products (id, tenant_id)`; la migración de E2 agrega `uq_brand_products_id_tenant` (0038 no la tiene) |
| `city`, `country_code` | text NOT NULL DEFAULT '' | dónde ocurre la campaña |
| `starts_on`, `ends_on` | date NULL | CHECK `ends_on >= starts_on` |
| `budget_cap` | numeric(12,2) NULL | NULL = sin tope declarado (no es cero) |
| `currency` | text NOT NULL | CHECK `('COP','USD','VES','UYU')`; sin conversión entre monedas (§6.5) |
| `pay_modes` | text[] NOT NULL | subconjunto de `('in_kind','paid','experience')` = canje, pago, experiencia |
| `brief` | text NOT NULL DEFAULT '' | lo que el dueño quiere, en sus palabras |
| `status` | text NOT NULL DEFAULT 'draft' | `('draft','active','closed','archived')` |
| `created_by_user_id`, `created_at`, `updated_at` | | |

**`campaign_candidates`** (un creador dentro de una campaña).

| Columna | Tipo | Nota |
|---|---|---|
| `campaign_id` | uuid NOT NULL | FK compuesta `(campaign_id, tenant_id, brand_id) → creator_campaigns`, CASCADE |
| `tracked_creator_id` | uuid NOT NULL | FK compuesta `(tracked_creator_id, tenant_id, brand_id) → tracked_creators` |
| `status` | text NOT NULL DEFAULT 'proposed' | `('proposed','shortlisted','discarded','invited','replied','negotiating','agreed','declined','closed')` |
| `status_changed_at`, `discard_reason` | | `discard_reason` texto libre del dueño |
| `invited_at`, `invited_channel` | timestamptz / text NULL | E3; canal `('instagram','whatsapp','email','other')` |
| `thread_id` | uuid NULL | E3; FK compuesta `(thread_id, tenant_id) → threads (id, tenant_id)` (`uq_thread_id_tenant`, 0004), ON DELETE SET NULL (`thread_id`) |
| `thread_linked_at`, `thread_link_source` | | `('suggested','manual')` — ver §6.4 |
| `agreed_offer_id` | uuid NULL | E5; FK compuesta a `candidate_offers` (se agrega en la migración de E4) |
| | | `UNIQUE (campaign_id, tracked_creator_id)` — un creador entra una vez por campaña; es la clave idempotente de «agregar a la campaña» |

**`candidate_fit_scores`** (el encaje por dimensión; solo se agregan filas, la pantalla muestra la última por dimensión).

| Columna | Tipo | Nota |
|---|---|---|
| `candidate_id` | uuid NOT NULL | FK compuesta a `campaign_candidates`, CASCADE |
| `dimension` | text NOT NULL | `('niche','audience','performance','risk')` |
| `score` | smallint NULL | 0–100; **NULL = desconocido, nunca cero** |
| `evidence_level` | text NOT NULL | `('verified','inferred','unknown')` = comprobado, inferido, desconocido |
| `reasons` | jsonb NOT NULL | lista de `{text, level, reels: [reel_id, …], metric: <clave de §9> \| null}` — cada razón cita reels de la lectura o una métrica; ver la regla de §12.3 |
| `snapshot_id` | uuid NOT NULL | FK a `creator_snapshots` (global): **qué lectura** se juzgó |
| `metrics_version` | text NOT NULL | versión de §9 usada |
| `model_id`, `prompt_version`, `schema_version` | text NOT NULL | para `performance`, que se calcula con reglas sin IA: `model_id = 'rules'`, `prompt_version = metrics_version` |
| `input_hash` | text NOT NULL | hash de lo que lee el modelo (campaña + lectura + versiones) |
| `cost_usd` | numeric(12,6) NOT NULL DEFAULT 0 | |
| | | `UNIQUE (candidate_id, dimension, input_hash)` — un encaje se repite solo si cambia la campaña, la lectura o el modelo |

Dos verdades que la pantalla debe decir y el modelo no puede tapar: **la audiencia por ciudad no es observable** desde datos públicos (solo la Creator Marketplace API o las estadísticas del propio creador la dan), así que `audience` será casi siempre `inferred` (biografía, textos, lugares etiquetados) o `unknown`; y **`is_paid_partnership` casi nunca viene marcado** (0 de 665 reels en ADR 34 (e)), así que «0 colaboraciones pagadas» se lee «ninguna declarada», no «no hace publicidad».

### 6.3 Entrega 3 — Invitar

**`candidate_invitations`** (borradores de invitación con la voz de la marca; versionados).

| Columna | Tipo | Nota |
|---|---|---|
| `candidate_id` | uuid NOT NULL | FK compuesta, CASCADE |
| `version` | int NOT NULL | `UNIQUE (candidate_id, version)` |
| `channel` | text NOT NULL | `('instagram','whatsapp','email','other')` |
| `body` | text NOT NULL | el texto final que el dueño aprobó (puede editarlo) |
| `model_id`, `prompt_version`, `input_hash`, `cost_usd` | | procedencia del borrador; si el dueño lo escribió entero, `model_id = 'manual'` |
| `approved_by_user_id`, `approved_at` | NULL | aprobar = el dueño dice «este es el texto» |
| `copied_at` | timestamptz NULL | el dueño tocó «Copiar» |
| `marked_sent_at`, `marked_sent_by_user_id` | NULL | el dueño marcó «Ya lo envié» — **Qualify no envía nada** |

No hay columna de «enviado por Qualify», ni outbox, ni worker: no existe camino de envío en E3.

### 6.4 Enlace con Conversaciones (E3 y E5)

Cuando el creador responde al Direct o al WhatsApp del negocio, el hilo ya existe en `threads` (módulo `inbox`/`conversations`). El enlace candidato → hilo es `campaign_candidates.thread_id`:

- **Sugerido:** si `threads.counterpart_username` (Instagram) coincide con el `handle` de un candidato `invited` de la misma marca, Conversaciones muestra «¿Es @x, de tu campaña <nombre>?» y un toque lo enlaza (`thread_link_source = 'suggested'`). Nunca se enlaza solo: un homónimo o una cuenta con el nombre cambiado no debe recibir el contexto de una oferta.
- **A mano:** desde la ficha del candidato, «Enlazar conversación» lista los hilos recientes de la marca (`'manual'`). En WhatsApp no hay usuario de Instagram que comparar: siempre a mano.

La dirección de la dependencia: `creators` guarda el `thread_id`; `conversations` no sabe nada de campañas. En E5, `conversations.suggest` recibe un proveedor de contexto opcional que, dado un `thread_id`, devuelve el resumen de la última oferta (si el hilo está enlazado). El borrador sugerido pasa por la bandeja de salida aprobada de siempre (`conversation_outbox`, `approved_by_user_id NOT NULL`), dentro de la ventana de 24 h que abrió el creador al escribir.

### 6.5 Entregas 4 y 5 — Presupuestar y negociar

**`candidate_offers`** (cada propuesta o contrapropuesta es una versión inmutable; nunca se edita una versión enviada, se crea otra).

| Columna | Tipo | Nota |
|---|---|---|
| `candidate_id` | uuid NOT NULL | FK compuesta, CASCADE |
| `version` | int NOT NULL | `UNIQUE (candidate_id, version)` — clave idempotente de «guardar oferta» |
| `previous_offer_id` | uuid NULL | la versión a la que responde |
| `proposed_by` | text NOT NULL | `('business','creator')` — una contraoferta del creador la registra el dueño |
| `deliverables` | jsonb NOT NULL | `[{kind: 'reel'\|'story'\|'post'\|'visit', qty, notes}]` |
| `due_on` | date NULL | |
| `usage_rights` | text NOT NULL | `('none','organic','ads')` + `usage_days int NULL` |
| `pay_mode` | text NOT NULL | `('in_kind','paid','experience','mixed')` |
| `amount`, `currency` | numeric(12,2) NULL / text | moneda de la campaña; NULL en canje puro |
| `in_kind_description`, `in_kind_value` | text / numeric NULL | valor del canje si el dueño lo declara; NULL = sin valorar (no es cero) |
| `expected_views` | bigint NULL | por defecto: mediana de vistas de la lectura × reels entregados |
| `expected_views_basis` | jsonb NULL | `{snapshot_id, metrics_version, median_views, sample}` — **el número congelado con el que se presupuestó** |
| `cost_per_1000_views` | numeric(12,4) NULL | `(amount + in_kind_value) / expected_views × 1000`; NULL si falta alguno |
| `status` | text NOT NULL DEFAULT 'draft' | `('draft','sent','countered','accepted','declined','withdrawn')` |
| `recorded_by_user_id`, `recorded_at` | | |
| `suggested_by_model_id`, `prompt_version` | NULL | si el texto o los términos los sugirió la IA (E5) |

Es entrada manual que el dueño aprueba una por una, así que cae en la excepción de procedencia del 2026-11-04 (`docs/arquitectura.md` §1.6); la parte derivada (`expected_views`, `cost_per_1000_views`) lleva su base en `expected_views_basis`.

**Total contra el tope:** suma de `amount + in_kind_value` de las ofertas `sent` o `accepted` vigentes (la última versión por candidato), en la moneda de la campaña. Una oferta en otra moneda no se convierte: se muestra aparte con un aviso. Un canje sin valor declarado cuenta como «sin valorar», nunca como cero.

**Negociación (E5):** el estado del candidato se deriva de su última oferta (`sent` → `negotiating`, `accepted` → `agreed` y `agreed_offer_id`, `declined` → `declined`). El «resumen de lo acordado» es una vista de la versión aceptada, no una tabla.

## 7. Contrato de la Entrega 1 — la migración

**Una revisión**, con el siguiente número sobre la cabeza de `origin/main` (hoy `0123_whatsapp_outbox_attachment` → **0124**; volver a mirar antes de escribirla, `qualify-migration` §1). Docstring con el ticket de la historia de E1 y «ADR 45».

### 7.1 `public_reels` — columnas nuevas (global)

| Columna | Tipo | Qué guarda |
|---|---|---|
| `coauthors` | jsonb NULL | lista de handles normalizados de `coauthor_producers` (colaboraciones); NULL = no se leyó, `[]` = ninguna |
| `sound_id` | text NULL | id del audio (IG: `music_asset_info.audio_cluster_id` o el id del audio original; el parser elige y lo documenta), para contar «audios más usados» por id y no por título |
| `sound_is_original` | boolean NULL | audio original de la cuenta (true) o licenciado (false) |
| `counts_hidden` | boolean NOT NULL DEFAULT false | la cuenta ocultó vistas y likes (`like_and_view_counts_disabled`) — distingue «oculto» de «no vino» |

`is_paid_partnership` ya existe (0117) y hoy **nadie la llena**: el parser v2 la lee del reel. Como es `NOT NULL DEFAULT false`, `false` significa «no declarado», y así lo lee §9.

### 7.2 `creator_snapshots` (global, una fila por lectura de una cuenta)

| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid PK | **lo genera el servicio antes de la primera llamada** (las claves de cobro lo usan, §8.3) |
| `network`, `handle` | text NOT NULL | mismos CHECK que 0036 (`_NETWORK_CHECK`, `_HANDLE_CHECK`) |
| `read_at` | timestamptz NOT NULL | cuándo empezó la lectura |
| `status` | text NOT NULL | `('ok','partial','private','missing','error')` |
| `followers`, `following`, `posts_count` | bigint NULL | NULL = no vino |
| `full_name`, `bio`, `category`, `external_url`, `avatar_url` | text NOT NULL DEFAULT '' | |
| `is_verified`, `is_private` | boolean NOT NULL DEFAULT false | |
| `reels_target` | int NOT NULL | 48 en E1 |
| `reels_read`, `pages_read` | int NOT NULL DEFAULT 0 | |
| `oldest_taken_at`, `newest_taken_at` | timestamptz NULL | el tramo que cubre la lectura |
| `credits` | int NOT NULL DEFAULT 0 | créditos que costó (un número, sin dueño) |
| `profile_payload_id` | uuid NULL | FK `vendor_payloads.id` ON DELETE SET NULL |
| `profile_payload_fetched_at` | timestamptz NULL | CHECK: si hay `profile_payload_id`, hay fecha (regla de 0117) |
| `parser_version` | int NOT NULL | CHECK `> 0` |
| `created_at` | timestamptz NOT NULL DEFAULT now() | |

`UNIQUE (network, handle, read_at)`; índice `(network, handle, read_at DESC)` para «la última lectura». CHECK `reels_read >= 0 AND pages_read >= 0 AND credits >= 0`. **Grants:** `SELECT, INSERT` a `qualify_app` (sin UPDATE ni DELETE: solo se agregan filas), `SELECT` a `qualify_admin`.

### 7.3 `public_reel_reads` (global, un reel en una lectura)

| Columna | Tipo | Nota |
|---|---|---|
| `snapshot_id` | uuid NOT NULL | FK `creator_snapshots.id` ON DELETE CASCADE |
| `network`, `reel_id` | text NOT NULL | une con `public_reels (network, reel_id)` sin FK (patrón 0119) |
| `position` | int NOT NULL | orden en la lista del proveedor (1 = el más nuevo, salvo fijados) |
| `taken_at` | timestamptz NOT NULL | |
| `views`, `likes`, `comments`, `saves`, `shares` | bigint NULL | NULL = no vino o está oculto; nunca 0 por defecto |
| `source_payload_id` | uuid NULL | FK `vendor_payloads.id` ON DELETE SET NULL — la página de donde salió |
| `source_payload_fetched_at` | timestamptz NULL | CHECK como en 0117 |
| `parser_version` | int NOT NULL | |

PK `(snapshot_id, reel_id)`; índice `(network, reel_id, snapshot_id)` para la curva de un reel. **Grants:** `SELECT, INSERT` a `qualify_app`; `SELECT` a `qualify_admin`.

Duración, texto, audio, colaboración y patrocinio **no** se repiten aquí: no cambian entre lecturas y viven en `public_reels`. Lo que cambia (contadores) va en cada lectura.

### 7.4 `tracked_creators` (por marca, RLS)

| Columna | Tipo | Nota |
|---|---|---|
| `id`, `tenant_id`, `brand_id` | | convenciones de §6; FK compuesta de marca; `UNIQUE (id, tenant_id, brand_id)` |
| `network` | text NOT NULL | CHECK `IN ('instagram','tiktok')`; **el servicio acepta solo `instagram` en E1** (TikTok espera G-JOIN, ADR 33 (d)) |
| `handle` | text NOT NULL | `_HANDLE_CHECK` |
| `note` | text NOT NULL DEFAULT '' | nota libre del dueño |
| `status` | text NOT NULL DEFAULT 'active' | `('active','archived')` |
| `last_snapshot_id` | uuid NULL | FK `creator_snapshots.id` ON DELETE SET NULL — una tabla por negocio puede apuntar a una global; **nunca al revés** |
| `refresh_state` | text NOT NULL DEFAULT 'never' | `('never','reading','ok','failed')` |
| `refresh_error` | text NULL | código cerrado de §10.3 |
| `refresh_started_at` | timestamptz NULL | para no dejar «leyendo» colgado: más de 5 min = se puede volver a pedir |
| `added_by_user_id` | uuid NULL | FK `users.id` ON DELETE SET NULL |
| `created_at`, `updated_at`, `archived_at` | | |

`UNIQUE (brand_id, network, handle)` — clave idempotente de «agregar creador» (`INSERT … ON CONFLICT DO UPDATE SET status = 'active', archived_at = NULL` reactiva un archivado). Índices `(tenant_id)` y `(brand_id, status)`. **Grants:** `SELECT, INSERT, UPDATE` a `qualify_app` (sin DELETE: «Quitar de la lista» archiva), `SELECT` a `qualify_admin`.

### 7.5 `vendor_usage_events` — dos funciones nuevas

Se reemplaza `ck_vendor_usage_feature` para sumar `'creator_profile'` y `'creator_reels'`. Así los topes de creadores se cuentan aparte de los de «Ideas para tus reels» (que usan `profile` y `reels_list`), sin depender de un prefijo en `request_key`. `scrapecreators.FEATURES` gana las mismas dos constantes (`FEATURE_CREATOR_PROFILE`, `FEATURE_CREATOR_REELS`).

### 7.6 `downgrade()`

Borra `tracked_creators`, `public_reel_reads`, `creator_snapshots` y las cuatro columnas de `public_reels`; para devolver el CHECK viejo **primero borra** las filas de `vendor_usage_events` con las dos funciones nuevas (se pierde el registro de consumo de creadores — es lo único que no se puede conservar con el CHECK anterior; se escribe en el docstring). Lo que se pierde al bajar es historial pagado y no se puede volver a comprar.

### 7.7 Tests de la migración (`-m db`)

- RLS: el tenant A no ve ni escribe `tracked_creators` del tenant B por `tenant_session`; una fila con `brand_id` de otro tenant es rechazada por la FK compuesta.
- Estructural: `creator_snapshots` y `public_reel_reads` no tienen ninguna columna `tenant_id`, `brand_id`, `user_id` ni nada que termine en `_user_id`/`_tenant_id`/`_brand_id` (como `test_public_reels_db.py`).
- `qualify_app` no puede `UPDATE` ni `DELETE` en las dos globales nuevas.
- `upgrade head → downgrade base → upgrade head` sin restos (lo corre CI).

## 8. Contrato de la Entrega 1 — la lectura pagada

### 8.1 Cambios en `qualify_api.vendors.scrapecreators` (la puerta)

- `REEL_PARSER_VERSION` pasa a **2** (vive hoy en `referentes/reel_runs.py:95`; se muda a `scrapecreators` para que los dos caminos compartan uno). `_instagram_reel` agrega al diccionario del reel: `paidPartnership: bool`, `coauthors: list[str]`, `soundId: str | None`, `soundIsOriginal: bool | None`, `countsHidden: bool`. Los consumidores actuales ignoran claves nuevas.
- Nueva función, y `fetch_reels` se reescribe encima de ella sin cambiar su comportamiento:

```python
@dataclass(frozen=True)
class ReelPage:
    path: str                    # "/v1/instagram/user/reels"
    params: dict[str, str]       # handle (+ max_id) — la clave de vendor_payloads
    payload: dict[str, Any]      # la respuesta cruda, entera
    reels: list[dict[str, Any]]  # ya parseados (forma de _instagram_reel), sin repetir
    next_cursor: str | None

def fetch_reel_pages(
    network: str,
    handle: str,
    *,
    max_reels: int,
    max_pages: int = REEL_MAX_PAGES,
    feature: str = FEATURE_REELS_LIST,
    client: httpx.Client | None = None,
    on_page: Callable[[ReelPage], None] | None = None,
) -> list[ReelPage]: ...
```

  Para cuando junta `max_reels` reels, sin cursor, con cursor repetido o en `max_pages`. `on_page` se llama **después de cada página pagada y antes de pedir la siguiente**, para que el llamador guarde el payload y cobre ese crédito aunque la página siguiente falle.

- Nueva función para el perfil con su crudo:

```python
def fetch_profile_raw(
    network: str, handle: str, *, feature: str, client: httpx.Client | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:  # (payload crudo, perfil normalizado)
```

  `fetch_profile` queda igual (llama a esta y devuelve el normalizado).

### 8.2 Cambios en `qualify_api.creators.repository` y `referentes.reel_store`

- `CachedPayload` gana `id: UUID`; `put_payload` lo devuelve. Sin eso no hay `source_payload_id` que guardar.
- `PublicReel` gana `is_paid_partnership`, `coauthors`, `sound_id`, `sound_is_original`, `counts_hidden`, `source_payload_id`, `source_payload_fetched_at`; el `upsert_reels` de Postgres los escribe con la misma guarda monotónica. **Esto arregla de paso una deriva:** hoy `reel_runs._public_reel` no llena `source_payload_id` ni `is_paid_partnership`, que 0117 creó para eso (§15).

### 8.3 El algoritmo de `refresh_creator` (en `qualify_api/creators/snapshots.py`)

1. **Interruptor y pertenencia:** `creators_enabled(tenant_id)` (§11); la fila de `tracked_creators` se lee por `tenant_session` (RLS) y debe ser de esa marca y `active`.
2. **Frescura (0 créditos):** si existe una `creator_snapshots` de `(network, handle)` con `status IN ('ok','partial','private','missing')` y `read_at >= now − 24 h`, se enlaza (`last_snapshot_id`) y se devuelve `fresh`. Es la caché compartida entre negocios.
3. **Tope del negocio (§8.4):** si lo que queda del día o del mes en créditos de creadores es menor que `SNAPSHOT_MAX_CREDITS` (5), se devuelve `cap_reached` sin llamar.
4. **Candado de cuenta:** `reel_store.try_lock_account(network, handle, until = now + 120 s)` (la columna `reel_accounts.refresh_lock_until` de 0117), el mismo candado que usa «Ideas para tus reels»: dos negocios, o un doble toque, nunca pagan dos lecturas de la misma cuenta a la vez. Si no se obtiene, espera hasta 30 s sondeando cada 2 s; si al soltarse ya hay una lectura fresca, vuelve al paso 2; si no, `busy`. Bajo el candado se vuelve a revisar el paso 2.
5. `refresh_state = 'reading'`, `snapshot_id = uuid4()`.
6. **Perfil (1 crédito):** `fetch_profile_raw(feature=FEATURE_CREATOR_PROFILE)` → `put_payload` → `record_usage(request_key=f"creators:{snapshot_id}:profile")`. 404 → `missing`, fin. Cuenta privada → `private`, fin (no se paga la lista).
7. **Reels (hasta 4 créditos):** `fetch_reel_pages(max_reels=48, feature=FEATURE_CREATOR_REELS, on_page=…)`; por página: `put_payload` y `record_usage(request_key=f"creators:{snapshot_id}:reels:{n}")`. Un error en la página n deja las anteriores: `partial`.
8. **Una transacción** (`tenant_session`): `INSERT creator_snapshots`; `INSERT public_reel_reads`; el upsert de `public_reels` (global, monotónico); el upsert de `creators` (la fila de 0036 con `read_at`); `UPDATE tracked_creators SET last_snapshot_id, refresh_state = 'ok'`. Para que sea una sola transacción sin que `creators` escriba SQL sobre tablas de `referentes`, `reel_store` expone `upsert_reels_in(session, rows)` y `creators.repository` expone `upsert_creators_in(session, rows)`: el mismo SQL de hoy, recibiendo una sesión abierta; los métodos actuales pasan a llamarlos.
9. **Siempre**, en `finally`: `reel_store.finish_account(…, page1=True, credits=…, lock_until=…)` libera el candado solo si sigue siendo suyo. `ScrapeCreatorsBlocked` (interruptor, piso global de 500, parada por 402) → `blocked`, sin cambiar la última lectura buena.

**Idempotencia, en resumen:** la frescura de 24 h (paso 2), el candado por cuenta (paso 4), `UNIQUE (tenant_id, request_key)` en `vendor_usage_events` (un reintento del mismo `snapshot_id` no cobra dos veces), `UNIQUE (network, handle, read_at)` en `creator_snapshots` y `UNIQUE (brand_id, network, handle)` en `tracked_creators`. **Una lectura que falla nunca reemplaza la última buena** (`last_snapshot_id` solo se mueve en el paso 8).

**Fuera del camino de la petición:** la pantalla llama a `refresh_creator` desde un evento en segundo plano de Reflex (`@rx.event(background=True)` + `asyncio.to_thread`), nunca dentro de un manejador que bloquee la vista. Son hasta 5 llamadas de ~1–3 s. No hay worker en E1 (decisión del fundador: «Actualizar» manual); si en E2 llega una relectura semanal, la atiende `reels-worker` (ADR 42 R8), no un servicio nuevo.

### 8.4 El tope por negocio — se construye la parte de R5 que hace falta

ADR 42 R5 (topes por negocio desde `vendor_usage_events`) sigue pendiente: la puerta solo registra en el log (`scrapecreators.py:145`). La Entrega 1 **no puede salir sin tope** (regla 7: guarda de precio delante de toda llamada pagada), así que construye la pieza genérica y R5 la reusa:

```python
# qualify_api/vendors/usage.py
def record_usage(
    session: Session, *, tenant_id: UUID, brand_id: UUID | None, vendor: str, feature: str,
    credits: int, request_key: str, payload_id: UUID | None,
    usd_per_credit: Decimal, pricing_table_version: str,
) -> bool:  # False si request_key ya existía (ON CONFLICT DO NOTHING)

def credits_used(
    session: Session, *, tenant_id: UUID, features: Collection[str], since: datetime
) -> int:

@dataclass(frozen=True)
class CreditBudget:
    day_used: int
    day_cap: int
    month_used: int
    month_cap: int
    def remaining(self) -> int: ...  # min(day_cap - day_used, month_cap - month_used)
```

**Topes propuestos para creadores** (parámetros, puerta de dos vías): **50 créditos al día y 300 al mes por negocio**, contados solo sobre `creator_profile` + `creator_reels`, aparte de los 150/600 de «Ideas para tus reels». Día y mes en la hora local del negocio (`tenants.timezone`), como R5. Precio: USD 0,00188 por crédito (plan Freelance, ADR 42 §1.3), `pricing_table_version = 'scrapecreators-freelance-2026-10'`. Entre dos lecturas simultáneas de creadores distintos del mismo negocio el tope puede pasarse por una lectura (≤ 5 créditos); se acepta.

El dueño **nunca ve créditos ni dinero** (ADR 42 §2.9): al tope ve la última lectura y «Mañana puedes actualizar otra vez» (texto final en `docs/ux-creadores.md`).

## 9. Contrato de la Entrega 1 — las métricas (una sola fórmula, versionada)

### 9.1 Las cinco fórmulas que hay hoy, y cuál manda

| Dónde | Qué calcula | Denominador |
|---|---|---|
| `referentes/reels.py:622` `engagement_label` | (likes + comentarios + compartidos + guardados) / vistas, por reel | vistas |
| `referentes/reels.py:632` `daily_views_label` | vistas / días desde la publicación | días |
| `referentes/reels.py:672` `account_lifts` | vistas / mediana de vistas de su cuenta | mediana propia |
| `vendors/scrapecreators.py:1703` `profile_metrics` | media(likes + comentarios) / seguidores, últimos 7 días | seguidores |
| `Qualify/creator_discovery.py:416` | (likes vistos + comentarios vistos) / publicaciones / seguidores | seguidores |

Tres de ellas se llaman «interacción» y miden cosas distintas: una sobre vistas, dos sobre seguidores, una suma compartidos y guardados (que Instagram no da de cuentas ajenas, así que la misma cuenta saldría distinta en TikTok e Instagram).

**Decisión (`metrics_version = "cm-1"`):** en el módulo Creadores, **«Interacción» es la mediana, reel por reel, de (likes + comentarios) / vistas**, sobre los reels medibles (§9.2).

- **Sobre vistas y no sobre seguidores:** un reel se reparte a no seguidores; dividir por seguidores castiga al creador pequeño que hace un reel que se mueve, y premia a la cuenta grande y dormida. La relación con los seguidores tiene su propia fila, con su propio nombre: «vistas por seguidor».
- **Solo likes y comentarios:** son los dos que Instagram da de una cuenta ajena; así un mismo número significa lo mismo en las dos redes cuando llegue TikTok.
- **Mediana de cocientes y no cociente de sumas:** un reel viral no debe arrastrar la cifra de toda la cuenta (el mismo principio de `account_lifts`).

Las otras cuatro siguen donde están **y no se usan en Creadores**. `profile_metrics` (la cuenta propia en el Brand Kit) y `creator_discovery.py` (un spike sin ruta) quedan como deuda: cuando se toquen, se renombran a «interacción por seguidor» o se pasan a `creators.metrics`. Ticket aparte; no bloquea E1.

**Versionado:** `CREATOR_METRICS_VERSION = "cm-1"` en `qualify_api/creators/metrics.py`. Cambiar una definición, un umbral o una ventana = nueva versión. Toda ficha, comparación, puntaje de encaje y base de oferta lleva la versión con la que se calculó. La ficha no se guarda: se recalcula de la lectura (pocas decenas de filas), así que `(snapshot_id, metrics_version)` es su procedencia completa.

### 9.2 Definiciones de `cm-1`

Entrada: los reels de una lectura (`public_reel_reads` + lo fijo de `public_reels`). **Reel medible:** `views` no nulo y > 0, `counts_hidden = false`, y con al menos **3 días** al momento de la lectura (`MATURITY_DAYS = 3`; antes, las vistas siguen creciendo — la curva de madurez no está calibrada, compuerta G-EDAD de ADR 34). **Muestra mínima:** `MIN_SAMPLE = 3` reels medibles; con menos, la métrica es `insufficient`, nunca cero.

| Clave | Etiqueta | Cálculo | Desconocido cuando |
|---|---|---|---|
| `followers` | Seguidores | de la lectura del perfil | no vino |
| `median_views` | Vistas típicas | mediana de `views` de los medibles | < 3 medibles |
| `mean_views` | Vistas promedio | media de `views` de los medibles | < 3 medibles |
| `views_per_follower` | Vistas por seguidor | `median_views / followers` | sin seguidores o sin mediana |
| `engagement_rate` | Interacción | mediana de `(likes + comments) / views` en medibles con `likes` conocido | < 3 con likes |
| `reels_per_week` | Reels por semana | `7 / median_gap_days` | < 3 reels con fecha |
| `median_gap_days` | Días entre reels | mediana de días entre reels consecutivos (ordenados por fecha; resiste a los fijados) | < 3 reels con fecha |
| `standout_reels` | Reels que se salieron | medibles con `views >= 2 × median_views` (`LIFT_HIGHLIGHT = 2.0`, el mismo umbral de `referentes.reels`), con su `lift = views / median_views` | < 3 medibles |
| `standout_share` | Parte de reels que se salen | `len(standout_reels) / medibles` | < 3 medibles |
| `top_reels` | Sus mejores reels | los 3 de más vistas (incluye los jóvenes, marcados «todavía sumando vistas») | sin vistas |
| `best_duration` | Duración que mejor le va | tramo (`≤15 s`, `16–30 s`, `31–60 s`, `61–90 s`, `>90 s`) con mayor mediana de vistas, entre los tramos con ≥ 3 medibles; con su ventaja sobre la mediana general | ningún tramo con ≥ 3 |
| `paid_partnerships` | Colaboraciones pagadas declaradas | reels con `is_paid_partnership` | nunca: 0 se muestra como «ninguna declarada» |
| `collabs` / `collaborators` | Colaboraciones con otras cuentas | reels con `coauthors` no vacío; los 5 handles más frecuentes | `coauthors` NULL en todos (lectura con parser v1) |
| `top_audios` | Audios que más usa | agrupar por `sound_id` (si falta, por título normalizado); los que aparecen ≥ 2 veces, top 5, marcando «audio propio» | sin audio en la lectura |
| `freshness_days` | Datos de hace… | días entre `read_at` y hoy; **desactualizado** desde 7 días (`STALE_DAYS = 7`) | — |

Los reels con vistas ocultas por la cuenta se cuentan aparte (`hidden_counts_reels`) y la ficha lo dice; nunca entran como cero.

### 9.3 Comparar creadores (2 a 4)

- **Los mismos N reels para cada uno, cada uno en su propio tiempo** (cambio del 2026-11-04, tras la revisión en el navegador: con una ventana de fechas común, un creador que publica ~10 reels por semana dejaba al que publica 1 con 1–2 reels en la ventana, y todas sus filas salían «Sin dato» aunque su ficha tenía datos). Cada creador se mide con **sus últimos N reels medibles** (§9.2), con `N = min(12, los que tenga el que menos tiene entre los que llegan al mínimo de `cm-1`, 3)` — `COMPARE_REELS = 12`. Un creador con menos de 3 reels medibles **no** baja N para los demás: sale con `few_reels` y sus filas `insufficient` (también «colaboraciones pagadas»: con tan pocos reels no se sabe, no es «ninguna»). Cada métrica de §9.2 se recalcula solo con esos N reels, salvo el ritmo (`reels_per_week`), que cuenta **todos** los reels de su tramo, incluidos los de vistas ocultas y los de menos de 3 días: cuentan para cada cuánto publica.
- **Qué devuelve por creador:** `reels_used` (cuántos reels entraron), `used_from` / `used_to` (las fechas que cubren) y `few_reels` (tiene menos que el mínimo: sus filas salen `insufficient`, «pocos reels», nunca cero). La comparación lleva `reels_per_creator` (N); `window_from` / `window_to` pasan a ser el tramo total que cubren todos. La pantalla dice de qué fechas es cada columna («@x: sus últimos 8 reels, del 2 al 30 de octubre»), porque un ritmo distinto da tramos distintos.
- **Filas:** `followers`, `median_views`, `views_per_follower`, `engagement_rate`, `reels_per_week`, `standout_share`, `paid_partnerships`, `best_duration`.
- **Lo mejor de cada fila se resalta**, solo entre valores `ok` (un desconocido nunca gana); empate = se resaltan todos los empatados. **No se resaltan** `followers` (más seguidores no es mejor para un negocio con poco presupuesto), `paid_partnerships` ni `best_duration` (no son «más es mejor»).
- **Sin puntaje sumado ni ranking total.** Sumar filas con unidades distintas inventa un número que nadie puede defender.
- **Avisos:** una lectura con más de 7 días («Datos de hace 9 días: actualiza para comparar con lo de hoy»); lecturas separadas por más de 7 días entre sí (`reads_apart`); un creador con menos de 3 reels medibles (`few_reels:<tracked_id>`, «@x tiene pocos reels para comparar»).

## 10. Contrato de la Entrega 1 — lo que llama la pantalla

### 10.1 Archivos

| Archivo | Qué tiene |
|---|---|
| `qualify_api/creators/metrics.py` | puro, sin BD ni red: `ReelRead`, `MetricValue`, las funciones de §9 y `build_sheet` / `compare` |
| `qualify_api/creators/tracking.py` | `TrackedCreatorStore` (Protocol), `MemoryTrackedCreatorStore` (gemelo para tests offline) y `PostgresTrackedCreatorStore` |
| `qualify_api/creators/snapshots.py` | `refresh_creator` (§8.3), la única función de E1 que paga |
| `qualify_api/creators/service.py` | la fachada que importa Reflex: las funciones de §10.2 |
| `qualify_api/creators/access.py` | `creators_enabled` (§11) |
| `qualify_api/vendors/usage.py` | §8.4 |

Reflex importa **solo** `qualify_api.creators.service` (y sus dataclasses). Toda función recibe el `tenant_id` y el `brand_id` de la sesión del servidor (ADR 43: el negocio sellado), nunca del navegador. En la URL viajan ids de `tracked_creators`, nunca handles (regla de privacidad: nada personal en la URL): `/creadores`, `/creadores/[tracked_id]`, `/creadores/comparar?ids=<uuid>,<uuid>`.

### 10.2 Funciones

```python
# qualify_api/creators/service.py
class CreatorsDisabled(Exception): ...         # el negocio no tiene el módulo (§11)
class InvalidHandle(ValueError): ...           # vacío, con espacios, > 30 caracteres, caracteres fuera de [a-z0-9._]
class UnsupportedNetwork(ValueError): ...      # E1: solo "instagram"
class TooManyToCompare(ValueError): ...        # fuera de 2..4

def creators_enabled(tenant_id: UUID) -> bool: ...

def add_creator(
    tenant_id: UUID, brand_id: UUID, handle: str, *, user_id: UUID,
    network: str = "instagram", note: str = "",
) -> TrackedCreator:
    """Normaliza el handle (acepta '@x', 'x' y la URL del perfil), lo guarda
    (idempotente; reactiva un archivado) y NO paga: la pantalla llama a
    `refresh_creator` enseguida, en segundo plano."""

def list_creators(
    tenant_id: UUID, brand_id: UUID, *, include_archived: bool = False,
    now: datetime | None = None,
) -> list[CreatorCard]: ...

def archive_creator(tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> None: ...

def refresh_creator(
    tenant_id: UUID, brand_id: UUID, tracked_id: UUID, *,
    now: datetime | None = None, client: httpx.Client | None = None,
) -> RefreshOutcome: ...                       # el único que paga (§8.3)

def creator_sheet(
    tenant_id: UUID, brand_id: UUID, tracked_id: UUID, *, now: datetime | None = None,
) -> CreatorSheet | None: ...                  # None = todavía sin lectura

def compare_creators(
    tenant_id: UUID, brand_id: UUID, tracked_ids: Sequence[UUID], *,
    now: datetime | None = None,
) -> Comparison: ...
```

Todas levantan `CreatorsDisabled` si `creators_enabled` es falso. Solo `refresh_creator` hace red; las demás leen Postgres y son baratas (la pantalla puede llamarlas al abrir).

### 10.3 Dataclasses (todas `frozen=True`)

```python
# metrics.py
MetricStatus = Literal["ok", "insufficient", "unknown"]

@dataclass(frozen=True)
class MetricValue:
    key: str                  # clave de §9.2
    value: float | None       # None si status != "ok"
    status: MetricStatus
    sample: int               # reels que entraron
    note: str = ""            # código: "hidden_counts", "young_reels", "no_followers"…

@dataclass(frozen=True)
class ReelRead:               # entrada de las funciones puras
    reel_id: str
    url: str
    taken_at: datetime
    duration_s: float | None
    views: int | None
    likes: int | None
    comments: int | None
    counts_hidden: bool
    is_paid_partnership: bool
    coauthors: tuple[str, ...] | None
    sound_id: str | None
    sound_title: str
    sound_is_original: bool | None

@dataclass(frozen=True)
class ReelCard:
    reel_id: str
    url: str                  # instagram.com/reel/<code>/ — para abrir
    embed_url: str            # el reproductor oficial (referentes.reels.embed_url)
    taken_at: datetime
    duration_s: float | None
    views: int | None
    likes: int | None
    comments: int | None
    lift: float | None        # vistas / mediana propia
    is_young: bool            # < MATURITY_DAYS: «todavía sumando vistas»
    is_paid_partnership: bool
    coauthors: tuple[str, ...]
    sound_title: str

@dataclass(frozen=True)
class DurationBucket:
    label: str                # "16–30 s"
    reels: int
    median_views: MetricValue
    lift_vs_overall: float | None

@dataclass(frozen=True)
class AudioUse:
    title: str
    reels: int
    is_original: bool | None

@dataclass(frozen=True)
class CreatorSheet:
    tracked_id: UUID
    network: str
    handle: str
    full_name: str
    bio: str
    avatar_url: str           # URL del CDN; caduca: la vista cae a iniciales
    is_verified: bool
    snapshot_id: UUID
    snapshot_status: str      # ok | partial | private | missing | error
    read_at: datetime
    freshness_days: int
    stale: bool               # freshness_days >= STALE_DAYS
    metrics_version: str      # "cm-1"
    reels_read: int
    measurable_reels: int
    hidden_counts_reels: int
    covered_from: datetime | None
    covered_to: datetime | None
    followers: MetricValue
    median_views: MetricValue
    mean_views: MetricValue
    views_per_follower: MetricValue
    engagement_rate: MetricValue
    reels_per_week: MetricValue
    median_gap_days: MetricValue
    standout_share: MetricValue
    top_reels: tuple[ReelCard, ...]
    standout_reels: tuple[ReelCard, ...]
    best_duration: DurationBucket | None
    duration_buckets: tuple[DurationBucket, ...]
    paid_partnerships: int
    collabs: int
    collaborators: tuple[str, ...]
    top_audios: tuple[AudioUse, ...]

@dataclass(frozen=True)
class ComparedCreator:
    tracked_id: UUID
    handle: str
    read_at: datetime
    stale: bool
    measurable_in_window: int

@dataclass(frozen=True)
class ComparisonRow:
    key: str
    values: tuple[MetricValue, ...]       # mismo orden que Comparison.creators
    best: tuple[int, ...]                 # índices resaltados; () si la fila no resalta
    highlights: bool

@dataclass(frozen=True)
class Comparison:
    creators: tuple[ComparedCreator, ...]
    window_from: datetime | None
    window_to: datetime | None
    metrics_version: str
    rows: tuple[ComparisonRow, ...]
    warnings: tuple[str, ...]             # códigos: "stale:<tracked_id>", "reads_apart", "short_window"

# service.py
@dataclass(frozen=True)
class TrackedCreator:
    id: UUID
    brand_id: UUID
    network: str
    handle: str
    note: str
    status: str               # active | archived
    refresh_state: str        # never | reading | ok | failed
    refresh_error: str | None
    last_snapshot_id: UUID | None
    created_at: datetime

@dataclass(frozen=True)
class CreatorCard:            # una fila de la lista
    tracked: TrackedCreator
    full_name: str
    avatar_url: str
    followers: int | None
    median_views: MetricValue
    engagement_rate: MetricValue
    read_at: datetime | None
    stale: bool

RefreshStatus = Literal[
    "read",          # se leyó ahora (créditos > 0)
    "fresh",         # había una lectura de menos de 24 h: 0 créditos
    "busy",          # otra lectura de la misma cuenta en curso: reintentar en unos segundos
    "cap_reached",   # tope del negocio: «Mañana puedes actualizar otra vez»
    "blocked",       # la puerta no llamó (interruptor, piso global, 402): «Ahora no pudimos actualizar»
    "missing",       # la cuenta no existe
    "private",       # la cuenta es privada: no se leen sus reels
    "error",         # falló la red o el proveedor; queda la última lectura buena
]

@dataclass(frozen=True)
class RefreshOutcome:
    status: RefreshStatus
    snapshot_id: UUID | None  # la lectura vigente después de la llamada
    credits: int              # para el registro y las pruebas; la pantalla NUNCA lo muestra
    partial: bool             # se leyeron menos páginas de las previstas
```

`refresh_error` usa los mismos códigos que `RefreshStatus` cuando el estado es `failed`.

### 10.4 Pruebas que definen «hecho» (offline salvo las marcadas)

- `metrics`: tabla de casos de §9.2 — 2 medibles → `insufficient`; un reel de 1 día no entra a la mediana; vistas ocultas no son cero; un viral no mueve `engagement_rate` (mediana); `best_duration` sin tramo de 3 → `None`; comparación con un `unknown` que no gana; empate resalta a los dos; `followers` no resalta.
- `snapshots` con `httpx.MockTransport` y `MemoryTrackedCreatorStore`: lectura fresca de otro negocio → `fresh`, 0 llamadas; tope 46/50 → `cap_reached`, 0 llamadas; 404 → `missing`, 1 crédito; privada → 1 crédito y sin lista; error en la página 3 → `partial`, 3 créditos registrados y lectura guardada; reintento con el mismo `snapshot_id` no duplica `vendor_usage_events`; `ScrapeCreatorsBlocked` → `blocked` sin mover `last_snapshot_id`.
- `-m db`: §7.7, más el candado — dos `refresh_creator` concurrentes de dos tenants sobre el mismo handle hacen una sola lectura.
- Estático: la prueba que prohíbe llamar al proveedor fuera de la puerta sigue verde (`fetch_reel_pages` y `fetch_profile_raw` usan `metered_get`).
- Evidencia de la CLI en el ticket (`qualify-scrapecreators`): `just sc instagram user-reels --handle carlosdelgadosc --pretty` mostrando la ruta JSON de `is_paid_partnership`, `coauthor_producers` y el id del audio que elija el parser.

## 11. Interruptor para «Fundadores»

No existe hoy un mecanismo de funciones por negocio (verificado: ni tabla ni variable de ese tipo en `packages/api` ni `Qualify/`). **Decisión para E1: una lista de negocios en una variable de entorno**, `QUALIFY_CREATORS_TENANTS` = UUIDs de tenant separados por comas; vacía o ausente = nadie. `creators_enabled(tenant_id)` la lee (con caché de proceso de 60 s) y es la única fuente:

- el menú muestra «Creadores» activo solo si es verdadera (hoy la entrada está fija en `False` en `Qualify/ui/layout.py:97`; pasa a depender del estado), y si no, sigue el «Pronto» actual de `Qualify/creators_page.py`;
- **cada función de `service.py` la vuelve a comprobar** (la pantalla no es la frontera de seguridad).

Por qué una variable y no una columna: es puerta de dos vías, no cambia esquema y se cambia con `just env-push` (lo hace el fundador, `qualify-prod-ops`). Se reabre cuando el módulo se abra a clientes: entonces el acceso sale del plan contratado, con su propia decisión de negocio (qué plan lo incluye y con qué tope).

«Fundadores» es un grupo de Lark (Herwin + Darwin), no un concepto de Qualify: hace falta que el fundador diga **qué negocios** entran a la lista (§17).

## 12. Procedencia, idempotencia y la compuerta de la Entrega 2

### 12.1 Procedencia de cada fila derivada

| Fila | De dónde sale | Versión |
|---|---|---|
| `public_reels`, `public_reel_reads` | `source_payload_id` + `source_payload_fetched_at` (la página cruda en `vendor_payloads`) | `parser_version` (2) |
| `creator_snapshots` | `profile_payload_id` + `profile_payload_fetched_at` | `parser_version` |
| Ficha y comparación (no se guardan) | `snapshot_id` | `metrics_version` (`cm-1`) |
| `candidate_fit_scores` | `snapshot_id` + los `reel_id` citados en `reasons` | `model_id`, `prompt_version`, `schema_version`, `metrics_version`, `input_hash` |
| `candidate_invitations` | la campaña, la ficha y el Brand Kit (`input_hash`) | `model_id`, `prompt_version` (o `manual`) |
| `candidate_offers` | entrada del dueño, aprobada una por una (excepción del 2026-11-04) | `expected_views_basis` congela `snapshot_id` + `metrics_version` + la mediana |

### 12.2 Idempotencia

| Acción | Clave |
|---|---|
| Agregar creador | `UNIQUE (brand_id, network, handle)` |
| Leer (pagar) | frescura de 24 h + candado de `reel_accounts` + `UNIQUE (tenant_id, request_key)` en `vendor_usage_events` |
| Guardar la lectura | `UNIQUE (network, handle, read_at)`; `public_reels` con guarda monotónica |
| Agregar a campaña | `UNIQUE (campaign_id, tracked_creator_id)` |
| Calcular encaje | `UNIQUE (candidate_id, dimension, input_hash)` |
| Borrador de invitación / oferta | `UNIQUE (candidate_id, version)`; la versión la asigna el servicio dentro de la transacción (`max + 1` con `SELECT … FOR UPDATE` sobre el candidato) |

### 12.3 La compuerta de la Entrega 2 (el encaje con IA)

Ningún puntaje de encaje llega a la pantalla sin pasar esto (`qualify-measure`, lo construye `data-scientist-fde`):

1. **Conjunto dorado:** ≥ 40 pares (creador, campaña) de los nichos reales (comida, inmobiliaria, viajes), etiquetados por el equipo con «encaja / no encaja / no se sabe» y la razón, **escrito antes de mirar lo que dice el modelo**.
2. **Duras (cero tolerancia, las comprueba código y no el modelo):** toda razón cita al menos un `reel_id` que existe en la lectura juzgada **o** una clave de métrica de §9.2; ninguna razón `verified` sin una métrica medida o un texto del creador citado tal cual; `audience` nunca `verified` sin una fuente que la mida (con datos públicos, no la hay). Una respuesta que falla esto se descarta y no se guarda.
3. **Blandas (umbral que fija el fundador con el primer resultado):** acuerdo con el equipo en «preseleccionar / descartar»; costo por candidato.
4. **Medido y documentado** en `docs/modelos-generativos/pruebas.md` el mismo día (regla de la casa).

`performance` no usa IA: es una regla sobre `median_views`, `engagement_rate` y `reels_per_week` contra el presupuesto y el objetivo de la campaña, con `model_id = 'rules'`.

**Guarda de precio de E2:** el encaje corre en segundo plano, por candidato, con tope de tokens por llamada y un tope mensual de encajes por negocio (propuesto: 100), contado sobre `candidate_fit_scores.cost_usd`.

## 13. Costos

Precio del crédito: **USD 0,00188** (Freelance, ADR 42 §1.3) `[V]`. Cifras por negocio con el módulo activo, **calculadas** sobre supuestos de uso `[H]`:

| Concepto | Unidad | Valor |
|---|---|---|
| Una lectura (perfil + 4 páginas de 12 reels) | ≤ 5 créditos | ≤ USD 0,0094 |
| Una lectura que otro negocio ya hizo hoy | 0 créditos | USD 0 |
| Uso esperado: 10 creadores, primera lectura + 2 actualizaciones al mes | ~30 lecturas = ~150 créditos | ≈ USD 0,28 al mes |
| Peor caso: el tope mensual propuesto | 300 créditos | ≈ USD 0,56 al mes |
| Encaje con IA (E2), por candidato | estimado `[H]` USD 0,03–0,05 (48 textos + métricas); se mide en la compuerta | 20 candidatos ≈ USD 0,6–1 al mes |
| Invitación (E3) y sugerencia de respuesta (E5) | una llamada corta cada una | < USD 0,01 |
| Postgres | ~350.000 filas al año con 20 negocios | despreciable |
| Actions | solo el CI normal de cada PR | sin minutos extra |

Ningún servicio, runtime, cola ni almacén nuevo: Postgres, la puerta medida que ya existe, eventos en segundo plano de Reflex y (si llega una relectura programada) `reels-worker`.

## 14. Las entregas 2 a 5, en una línea de contrato cada una

| Entrega | Migración | Servicio nuevo en `creators/` | Depende de |
|---|---|---|---|
| E2 Encajar | `creator_campaigns`, `campaign_candidates`, `candidate_fit_scores`; `uq_brand_products_id_tenant` | `campaigns.py` (crear/editar campaña, agregar candidatos, preseleccionar/descartar), `fit.py` (encaje en segundo plano) | E1; la compuerta de §12.3 |
| E3 Invitar | `candidate_invitations`; columnas de invitación y `thread_id` en `campaign_candidates` | `invitations.py` (borrador con la voz de la marca, aprobar, copiar, «Ya lo envié»), `link_thread` / `suggest_thread_links` | E2; `conversations` (lectura de `threads`) |
| E4 Presupuestar | `candidate_offers`; `agreed_offer_id` | `offers.py` (guardar versión, tabla comparativa con costo por 1.000 vistas, total contra el tope) | E2 (`expected_views_basis` sale de E1) |
| E5 Negociar | ninguna | estados derivados, resumen de lo acordado; proveedor de contexto para `conversations.suggest` | E3, E4 |

## 15. Deriva encontrada (se arregla en E1 o se anota)

1. **`referentes/reel_runs.py` no llena la procedencia que 0117 creó**: `_public_reel` no pasa `source_payload_id`, `source_payload_fetched_at` ni `is_paid_partnership`, y `fetch_reels` descarta el payload crudo. La regla 5 (procedencia) no se cumple hoy en `public_reels`. E1 arregla el camino de creadores y deja a `reel_runs` listo para usar `fetch_reel_pages`; el cambio de `reel_runs` es una historia aparte de la épica de ADR 42.
2. **`creators.repository.CachedPayload` no expone el `id`** de `vendor_payloads`: sin él no hay `source_payload_id` posible. E1 lo agrega.
3. **Cinco fórmulas de «interacción»** (§9.1). E1 fija una para Creadores; las demás quedan como deuda nombrada.
4. **`docs/modulo-creator-fit-estrategia.md`** describe un módulo que ADR 33 dijo que no lo era y que ADR 45 vuelve a hacer módulo: lleva una nota fechada arriba.

## 16. Riesgos

- **Datos de personas.** Un creador es una persona natural. Las cifras públicas de su perfil son dato público compartido (como ADR 42), pero las ofertas, montos y notas de negociación son datos personales que el negocio trata, y Qualify los guarda por encargo (Ley 1581 de Colombia; equivalentes en Venezuela y Uruguay). Van solo en tablas con RLS, nunca en una global. **Antes de abrir el módulo a clientes**, la política de privacidad y el contrato con el negocio deben nombrar este uso (compuerta G-DPA de ADR 34, sin revisión legal todavía).
- **El proveedor cambia la forma del reel** (por ejemplo, deja de mandar `coauthor_producers`): se ve como columnas NULL, que §9 lee como desconocido y no como cero; el parser sube de versión.
- **La lista de creadores crece y nadie actualiza:** la ficha avisa desde 7 días; si el uso real pide más frescura, la relectura semanal va en `reels-worker`, no en la pantalla.
- **El encaje suena seguro sin serlo:** lo frena la compuerta de §12.3 y la etiqueta comprobado/inferido/desconocido en cada razón.
- **Fuga lateral entre negocios** por la caché compartida: §4.1.

## 17. Preguntas para el fundador

1. **Topes de creadores:** ¿50 créditos al día y 300 al mes por negocio, aparte de los 150/600 de «Ideas para tus reels»? (≈ USD 0,56 al mes en el peor caso.)
2. **Quién entra al interruptor:** ¿qué negocios van en `QUALIFY_CREATORS_TENANTS` — el negocio interno del equipo, o también los de clientes que ustedes operan (Bianki, Polette, la agencia de viajes)?
3. **La fuga lateral de §4.1:** ¿se acepta mostrar la fecha por día, o prefieres leer por negocio y pagar dos veces cuando dos negocios siguen al mismo creador?
4. **Monedas:** ¿presupuesto en la moneda de cada campaña (COP, USD, VES o UYU) sin convertir, como propone §6.5?
5. **Correo:** ¿confirmas que en E3 Qualify tampoco manda el correo (el dueño lo envía desde su cuenta)?
6. **Cuánto se guarda una negociación cerrada:** ¿se borran ofertas y notas N meses después de cerrar la campaña, o se guardan mientras el negocio exista?
