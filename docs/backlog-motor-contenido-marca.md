# Backlog / Plan de sprint — Motor de Contenido de Marca

**Fecha:** 2026-08-13 · **Estado:** `[PLAN — pendiente de revisión del fundador]`
**Track:** paralelo al 🔴 [despliegue en `qualify.attitudefactory.co`](prioridad-despliegue-subdominio.md). No compite por el camino crítico de Meta: nada de este módulo necesita App Review ni Business Verification.
**Decisión rectora existente:** [`docs/adr-32-motor-angulos-creativo.md`](adr-32-motor-angulos-creativo.md) `[APROBADO 2026-08-10]`.
**Evidencia de vendors/precios:** [`docs/comparativa-apis-creativo-motor-angulos.md`](comparativa-apis-creativo-motor-angulos.md).
**Backlog hermano (no se duplica, se reutiliza):** [`docs/backlog-fase5-motor-angulos.md`](backlog-fase5-motor-angulos.md) — historias `F5-MA-01…04` se construyen **acá**.

---

## 0. Qué es esto y por qué no es lo mismo que el Motor de Ángulos

El ADR 32 aprobó la pata de creativo como **Motor de Ángulos**: `insight (earned media) → brief → orquestación de generación`. Su Épica B está bloqueada por un **gate de datos duro** (`search.content_index` + comentarios + `signals`, o sea Fase 1 Parte 3 + Fase 3, ninguna arrancada).

Lo que se pide acá es distinto y **no toca ese gate**: generar contenido **fundado en la identidad first-party del cliente registrado en el tenant** — su marca, su branding, su tono. El grounding no viene del mercado, viene del cliente. Eso lo hace construible hoy.

```
Motor de Ángulos (ADR 32, Épica B)   ← grounding: earned media ajeno   ← BLOQUEADO (Parte 3 + Fase 3)
Motor de Contenido de Marca (esto)   ← grounding: identidad propia     ← CONSTRUIBLE YA
                └── comparten: Épica A (orquestación) + capa de generación
```

**La tensión que hay que nombrar antes de empezar.** El ADR 32 prohíbe explícitamente shippear "un wrapper de una API". Un generador que solo recibe un prompt libre **es** ese wrapper — ChatGPT lo hace gratis. Lo que salva a este módulo es que el brand kit y el perfil de voz sean **activos persistidos, versionados, destilados de material real del cliente y auditables**, no un `system_prompt` escrito a mano en un formulario. Por eso el Slice 1 (sustrato de marca) va **antes** que la generación, y por eso `MC-14` (kill criterion) se define antes de escribir la primera línea de generación.

**Consecuencia formal:** esto requiere una enmienda al ADR 32 o un ADR 34 (`MC-00`). Tres cosas que el ADR 32 no contempla: (a) el grounding first-party como wedge válido, (b) la **capa de copy/texto**, que la comparativa de APIs no cubre — solo cubre imagen/video/UGC/ad-insight, (c) invertir parcialmente el orden: brand kit antes que ángulos.

### Decisiones tomadas en esta sesión (fundador, 2026-08-13)

| # | Pregunta | Respuesta |
|---|---|---|
| Q1 | Modalidad del MVP | **Copy + imagen.** El post completo de IG/FB. Video queda v2 (ADR 32 ya lo dice). |
| Q2 | Origen del tono | **Las tres fuentes:** formulario manual (S1) + destilado del contenido ya publicado del cliente (S2) + destilado de web/perfil público para arranque en frío (S3). |
| Q3 | Credenciales de generación | **Llave de plataforma ahora, BYOK detrás del mismo seam.** Se construye el resolver con las dos rutas; solo se implementa la de plataforma. |
| Q3-bis | Credenciales de la **capa de copy** (2026-08-16) | **La API de Anthropic entra por BYOK desde el día 1.** El cliente trae su propia key, cifrada bajo el patrón `qualify_credential`. Resolución final de Q3: **BYOK implementado para Anthropic (texto), llave de plataforma para fal/Replicate (imagen)** — un solo `CredentialResolver`, dos rutas vivas. |

---

## 1. Estado real del repo que este plan asume (verificado en disco 2026-08-13)

| Pieza | Estado | Uso en este plan |
|---|---|---|
| `packages/api/.../tenancy/models.py` → `Tenant`, `Brand` | ✅ existe (`Brand` solo tiene `id/tenant_id/name/created_at`) | `Brand` es la clave natural del brand kit. **Hay que extenderlo, no crear un concepto paralelo de "cliente".** |
| `packages/api/.../connections/` (C-03/C-04) | ✅ cuentas conectadas Meta, FSM, custodia cifrada | Fuente de S2 (contenido publicado propio) |
| `packages/api/.../publishing/` + migración `0003` | ✅ `publish_attempts`, `scheduled_posts` | Salida de `MC-13` (publicar el aprobado) |
| `packages/shared/.../objects/` (`s3.py`, `keys.py`, `gate.py`) | ✅ existe, con `tenant_prefix` / `media_key` / `require_tenant_prefix` | Assets del brand kit van bajo `t/{tenant_id}/…`, sin excepción |
| `packages/scraper/` (Zyte + parsers) | ✅ existe | Fuente de S3 (web/perfil público en frío) |
| `packages/models/.../providers.py` (`VisionProvider`, …) | ✅ patrón `Protocol` establecido | Molde exacto de `GenerationProvider` |
| `billing.usage_events` | ❌ diseñado, no construido | **No se espera.** Se contabiliza en `creative_usage_events` local, migrable después |
| `search.content_index` / `signals` | ❌ no construidos | **No se usan.** Es lo que mantiene este track desbloqueado |
| SDK de Anthropic / cualquier LLM | ❌ **cero ocurrencias en el repo** | `MC-09` introduce la primera dependencia de LLM del proyecto, **bajo BYOK** — diseño en §2.1, riesgos en §5 |
| `oauth_credentials` (cifrado de sobre + rol `qualify_credential`) | ✅ existe, pero **atado a conexiones sociales** | El patrón se reutiliza; la tabla no. BYOK necesita `provider_credentials` nueva en `MC-01` |

---

## 2. Arquitectura propuesta

Dos paquetes, siguiendo el patrón ya establecido (`qualify_scraper` puro y testeable ↔ `qualify_api.connections` con estado y RLS):

```
packages/creative/            → qualify_creative      (PURO: sin DB, sin red en tests)
├── providers.py              GenerationProvider Protocol + tipos de tarea/resultado
├── adapters/
│   ├── fal.py                FalAdapter          (imagen: FLUX.2 pro, Seedream 4.0, Ideogram)
│   ├── replicate.py          ReplicateAdapter    (espejo obligatorio, ADR 32 D5)
│   └── anthropic_copy.py     CopyAdapter         (texto: Claude, BYOK — §2.1)
├── credentials.py            CredentialResolver Protocol → TenantKeyResolver | PlatformKeyResolver
├── pricing.py + pricing/v1.json   tabla de precios VERSIONADA (por-pieza Y por-token)
├── router.py                 CreativeRouter — cadenas de fallback F / P / Q
├── brand/
│   ├── kit.py                schema del Brand Kit (Pydantic)
│   ├── voice.py              BrandVoiceProfile + destilación S1/S2/S3
│   └── fidelity.py           gate de fidelidad de marca (reglas duras + juez LLM)
└── tests/fixtures/           respuestas grabadas por proveedor → contract tests sin red

packages/api/src/qualify_api/creative/   (ESTADO: DB, RLS, HITL)
├── models.py                 brand_kits, brand_voice_profiles, content_briefs,
│                             content_drafts, generation_jobs, creative_usage_events,
│                             creative_engine_config
├── repository.py / service.py
└── fsm.py                    máquina de estados del draft (patrón connections/fsm.py)

migrations/postgres/versions/0005_creative.py   tablas + RLS en la MISMA revisión (ADR 27)
Qualify/                                        editor de brand kit + revisión/aprobación de drafts
```

**Reglas duras que este módulo hereda y no negocia:**
- RLS por `tenant_id` en toda tabla nueva, en la misma revisión Alembic (ADR 27 / R7 — el `NULLIF(...)` es load-bearing).
- Todo acceso a DB por las puertas sancionadas de `qualify_shared.db` (`tenant_session`). Un test estático ya prohíbe construir `Engine`/`Session` fuera de ahí.
- Credenciales **nunca en claro** — patrón `qualify_credential` / `oauth_credentials.ciphertext`.
- **Provenance obligatoria**: cada draft lleva `brief_id`, `voice_profile_version`, `model_id` + `revision`, `pricing_table_version`, `pipeline_version`. Un copy generado sin saber qué perfil de voz lo produjo es inauditable.
- El código de negocio **jamás** importa el SDK de fal/Replicate/Anthropic directamente — solo el protocolo.

### El flujo completo

```
[S1 formulario] ─┐
[S2 owned media]─┼─► BrandVoiceProfile (versionado) ──HITL#0 aprobación──┐
[S3 web pública]─┘                                                       │
                                                                         ▼
   Marketer: objetivo + formato + tema/producto ──► ContentBrief ──► CreativeRouter
                                                                         │
                                        ┌────────────────────────────────┴───────────┐
                                        ▼                                            ▼
                             CopyAdapter (Claude)                        FalAdapter → Replicate
                             N variantes de copy                         imagen on-brand
                                        │                                            │
                                        └──────────► Brand Fidelity Gate ◄───────────┘
                                             reglas duras + juez → (Q) del router
                                                        │
                                                        ▼
                                    ContentDraft ──HITL#2 revisión/edición/aprobación──►
                                                        │
                                              publishing/ (0003) o export
```

### 2.1 La capa de copy: Anthropic bajo BYOK

Esta es la primera dependencia de LLM del proyecto (cero ocurrencias de `anthropic` en el repo hoy) y la única capa que **no** tiene espejo de agregador: la imagen puede saltar fal→Replicate para el mismo modelo, el texto no. Eso cambia el diseño en cinco puntos concretos.

**1. Custodia de la key — y la trampa que hay que blindar con un test.** El SDK de Anthropic resuelve credenciales del entorno cuando se construye sin argumentos (`ANTHROPIC_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → perfil OAuth en disco). Eso significa que **si el resolver de tenant falla y alguien construye `Anthropic()` pelado, el fallo es silencioso: la llamada sale con la key ambiente de la plataforma y se factura a la cuenta equivocada, sin error.** Regla dura y test estático que la verifica: en `qualify_creative` el cliente se construye **siempre** con `api_key=` explícito, resuelto del `CredentialResolver`; ninguna ruta puede caer al entorno. Si no hay key de tenant, se levanta excepción — no se degrada.

**2. Almacenamiento.** `oauth_credentials` está atado a conexiones sociales; una API key genérica no encaja ahí. `MC-01` crea `provider_credentials` (`tenant_id`, `brand_id`, `provider`, `ciphertext`, `key_fingerprint`, `validated_at`, `status`) con el mismo cifrado de sobre y el rol `qualify_credential` como único lector del ciphertext. Deja de ser trabajo diferido: es requisito del primer sprint.

**3. Validación al guardar, no en producción.** Una key inválida no debe descubrirse cuando el marketer aprieta "generar". Al guardarla se valida con una llamada que **no consume tokens** — `client.models.list()` — y se marca `validated_at`. Un `401` en producción se mapea a un estado de conexión legible ("la API key de Anthropic de esta marca ya no es válida"), no a un 500 genérico.

**4. Sin espejo: la cadena de fallback del texto es distinta.** El `(F)` del router no puede saltar de agregador. La cadena real es: reintento con backoff (el SDK ya reintenta 429/5xx, `max_retries` por defecto 2) → y después una decisión de política **por marca**, `on_credential_failure`:
- `block` (**default**) — falla explícito. El gasto es del cliente; Qualify no lo asume por su cuenta.
- `platform_fallback` — opt-in explícito del admin: la pieza se genera con la llave de plataforma y se marca en `creative_usage_events` como gasto de Qualify. Nunca implícito.

Aparte de esto, conviene activar el fallback server-side de Anthropic para rechazos de política (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`): reintenta el mismo request en otro modelo dentro de la misma llamada. Relevante para las marcas reguladas del §5.6 — y hay que **comprobar `stop_reason` antes de leer `content`**: un rechazo devuelve HTTP 200 con `content` vacío, así que el código que indexa `content[0]` se rompe.

**5. La unidad de coste es el token, no la pieza.** `F5-MA-03` estaba diseñada para precios por-imagen. El copy factura por token de entrada y salida (Opus 5: $5 / $25 por millón), así que la tabla de precios necesita **dos unidades** y el chequeo `(P)` del router necesita una estimación *antes* de la llamada — que existe y es exacta: `client.messages.count_tokens()`. Nada de estimadores tipo `tiktoken`: subestiman los tokens de Claude.

**Palanca de coste que hay que diseñar desde el principio, no optimizar después.** El brand kit + el voice profile son un prefijo **estable** que se repite en cada generación de la misma marca; el brief es lo volátil. Con ese orden — kit y perfil primero, brief al final, breakpoint de `cache_control` al cierre del prefijo estable — las lecturas de caché cuestan ~0.1× y la escritura 1.25× (rentable desde la segunda llamada). El mínimo cacheable en Opus 5 es de 512 tokens, que un brand kit real supera con holgura. Esto **impone una restricción al render del prompt de `MC-08`**: nada volátil (timestamp, id de request, JSON sin ordenar) puede colarse por delante del brand kit, o la caché no sirve para nada. Se verifica midiendo `usage.cache_read_input_tokens` — si sale 0 en llamadas repetidas, hay un invalidador silencioso.

**Detalles de API que el implementador no debe adivinar** (vienen del skill `claude-api`, no de memoria): modelo por defecto `claude-opus-5`; thinking adaptativo (`thinking={"type": "adaptive"}`) y profundidad vía `output_config={"effort": ...}`; **`temperature`/`top_p`/`top_k` devuelven 400** — la variación de estilo se pide por prompt, no por sampling; el prefill de turno assistant también devuelve 400 — la salida estructurada se fuerza con `output_config.format` + JSON Schema, que es exactamente lo que necesitan la destilación de tono (`MC-03b`/`MC-04`) y el juez de fidelidad (`MC-11`).

**Una propiedad que BYOK regala:** los rate limits son de la cuenta del cliente. Un 429 de una marca no afecta a las demás — cosa que la llave única de plataforma sí haría.

**Y una que quita:** con BYOK el gasto de copy es del cliente, así que `hard_stop_on_cap` cambia de significado en esta capa — deja de ser una protección financiera de Qualify y pasa a ser un guardarraíl de producto. El cap sigue existiendo y sigue frenando, pero la semántica hay que documentarla distinta en el admin para no engañar al marketer.

---

## 3. El sustrato de marca (lo que decide si esto tiene foso)

`BrandKit` — lo que el marketer declara:

| Campo | Por qué está |
|---|---|
| `name`, `category`, `positioning_statement` | Contexto base |
| `audience` (quién, dónde, registro tú/usted/vos) | En CO/VE el registro es señal fuerte de marca |
| `language` + `regional_variant` | `es-CO` ≠ `es-ES`; el modelo se va a España si no se le fija |
| `tone_axes` (formal↔coloquial, sobrio↔entusiasta, técnico↔simple) | Ejes numéricos, no adjetivos sueltos — hacen el tono medible |
| `do_examples` / `dont_examples` (copy real) | Los ejemplos mueven más el output que cualquier adjetivo |
| `banned_words`, `forbidden_claims` | **Chequeo determinista, no LLM.** Inmobiliaria y servicios financieros tienen claims prohibidos por regulación |
| `emoji_policy`, `hashtag_policy`, `cta_patterns`, `length_targets` | Reglas verificables por regex/conteo → gate barato |
| `palette_rgb`, `logo_asset_key`, `reference_images[]` (≤14) | Consistencia visual; van a R2 bajo `t/{tenant_id}/brand/{brand_id}/…` |
| `locked_style_lora_ref` | Nulo en MVP; hook para LoRA por cliente en v2 |

`BrandVoiceProfile` — lo que el sistema **destila** y el humano aprueba:
- Versionado e inmutable (`version` monotónica). Un draft apunta a la versión con la que se generó; cambiar el perfil no reescribe la historia.
- Provenance: qué fuentes lo alimentaron (`post_id`s propios, URLs), qué modelo lo destiló, qué revisión.
- **No entra en vigor sin aprobación humana (HITL #0).** Un tono destilado que nadie revisó es peor que ninguno: se propaga silenciosamente a todo el contenido.

**Aviso de alcance sobre S2 (contenido ya publicado).** En disco hay `publish_attempts`/`scheduled_posts` (lo que *nosotros* publicamos) y `threads`/`messages` (inbox). **No existe** ninguna tabla con el histórico de posts publicados del cliente ni sus captions. S2 exige por tanto un lector nuevo de owned media vía Graph API (`/media` sobre la conexión ya existente) — es trabajo real, está sizeado como `MC-03a`, y es first-party (sin scraping, sin permisos nuevos más allá de los que C-04 ya obtiene). Si `MC-03a` se cae del sprint, S1+S3 siguen dando un perfil utilizable y S2 se añade después sin refactor.

---

## 4. Historias

Convención de IDs: `MC-##` para lo nuevo; `F5-MA-##` cuando la historia **ya existe** en el backlog del Motor de Ángulos y se construye acá (no se duplica).

### Slice 0 — Gate (sin código)

| ID | Historia | Dueño | Tamaño |
|---|---|---|---|
| **MC-00** | ADR 34 `[PROPUESTO]`: grounding first-party como wedge válido bajo ADR 32; se añade la capa de copy al catálogo; orden brand-kit-antes-que-ángulos; kill criterion propio. Foldeado en `arquitectura.md` §6 al firmarse. | principal-architect | S |

**Criterio de aceptación:** el ADR responde explícitamente "¿en qué se diferencia esto de ChatGPT con un buen prompt?" con una respuesta instrumentable, no retórica.

### Slice 1 — Sustrato de marca *(el diferenciador; cero dependencias externas)*

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MC-01** | Modelo de datos + migración `0005_creative` con RLS en la misma revisión: `brand_kits`, `brand_voice_profiles` (versionado), `content_briefs`, `content_drafts`, `generation_jobs`, `creative_usage_events`, `creative_engine_config` y **`provider_credentials`** (BYOK: ciphertext + `key_fingerprint` + `validated_at` + `status`, legible solo por `qualify_credential`). `just migrate-down` limpio. | — | architect + pipeline | M |
| **MC-02** | Brand Kit manual (S1): schema Pydantic + CRUD por `brand_id` + validación + assets a R2 vía `brand_asset_key()` nuevo bajo `tenant_prefix`. Test: una key fuera del prefijo del tenant levanta `TenantPrefixViolation`. | MC-01 | pipeline | M |
| **MC-03a** | Lector de owned media: trae los últimos N posts publicados del cliente (caption, tipo, métricas básicas) por la conexión Meta existente; idempotente por `(connection_id, media_id)`. | connections | pipeline | M |
| **MC-03b** | Destilación de tono desde owned media (S2) → propuesta de `tone_axes`, `do_examples`, léxico recurrente, patrones de CTA/hashtag, con provenance a los `media_id` fuente. | MC-03a | datasci | M |
| **MC-04** | Destilación en frío (S3): desde URL del sitio o perfil público vía `qualify_scraper` → mismo shape de propuesta que MC-03b. Cubre al cliente sin cuenta conectada aún. | MC-02 | pipeline + datasci | M |
| **MC-05** | `BrandVoiceProfile` versionado + **HITL #0**: el marketer ve la propuesta destilada campo por campo con su evidencia, edita y aprueba. Sin aprobación no hay perfil activo. Un draft referencia siempre una versión concreta. | MC-02..04 | pipeline | M |

### Slice 2 — Orquestación *(= Épica A del ADR 32; se construye acá y sirve a los dos motores)*

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **F5-MA-01** | `GenerationProvider` Protocol + `FalAdapter` + `ReplicateAdapter` + `CopyAdapter` (Anthropic). Contract test por adaptador contra fixtures grabadas (sin red en CI; llamadas reales bajo marcador `integration`). El negocio nunca importa el SDK. | — | pipeline | M |
| **F5-MA-03** | Tabla de precios versionada (`pricing/v1.json`: modelo, **unidad — `per_piece` o `per_mtok_in`/`per_mtok_out`**, precio, fecha, fuente) + job de refresco. Cero literales de precio en código. Pin explícito de versión por modelo. | — | pipeline | S |
| **MC-06a** | `CredentialResolver` con dos rutas vivas: **`TenantKeyResolver` (BYOK, implementado para Anthropic)** y `PlatformKeyResolver` (env, para fal/Replicate). Custodia sobre `provider_credentials`. **Test estático: `qualify_creative` no puede construir un cliente Anthropic sin `api_key=` explícito** — la caída silenciosa al `ANTHROPIC_API_KEY` del entorno es el fallo que factura a la cuenta equivocada. Ninguna key en claro, ni en logs ni en excepciones. | F5-MA-01, MC-01 | pipeline + architect | M |
| **MC-06b** | Alta y validación de key BYOK: se valida al guardar con `models.list()` (cero tokens), se sella `validated_at`, y un `401` en producción se traduce a estado legible por marca — no a un 500. Política `on_credential_failure` por marca: `block` (default) o `platform_fallback` (opt-in explícito, gasto marcado como de Qualify en `creative_usage_events`). | MC-06a | pipeline | S |
| **F5-MA-02** | `CreativeRouter` con cadenas de fallback: **(F)** fallo/timeout → siguiente, y el *primer* salto es **mismo modelo, otro agregador** (fal→Replicate); **(P)** coste proyectado > cap restante → downgrade o bloqueo; **(Q)** score < umbral → siguiente. Todo salto logueado con motivo. | F5-MA-01, -03 | pipeline | M |
| **MC-07** | `creative_engine_config` por brand (cap mensual, tier, cadenas por tarea, `hitl_required=true`, `hard_stop_on_cap`, `on_credential_failure`) + contabilidad en `creative_usage_events`. Para copy se registran las **cuatro** cifras de `usage` (input, output, `cache_read_input_tokens`, `cache_creation_input_tokens`) y el `(P)` pre-vuelo estima con `count_tokens()`. El admin debe explicar que bajo BYOK el cap es guardarraíl de producto, no tope de gasto de Qualify. Migrable a `billing.usage_events` cuando exista. | MC-01, F5-MA-03 | pipeline | M |

### Slice 2-bis — Sustrato de foto

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MC-16** | **`photo_recipe`** (`qualify_creative.photo`): normalización (EXIF/HEIC/P3/export — los 4 fallos silenciosos, corren siempre) → segmentación local `birefnet-general-lite` con **máscara persistida junto al asset** → derivados que la consumen (recorte, sombra sintética, preset cálido solo-sujeto). Parámetros por marca en `brand_kit.photo_recipe`, calibrados una vez. Tests: normalización con fixtures de iPhone (HEIC girado), derivados deterministas contra máscara grabada (la segmentación en sí bajo marcador `integration`). Veto de licencia en test estático: `bria-rmbg` prohibido. | MC-01 | pipeline | M |

### Slice 3 — Generación on-brand

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MC-08** | `ContentBrief`: contrato de entrada (objetivo, plataforma/formato, tema o producto, CTA, restricciones) + **inyección determinista** del brand kit + voice profile activo. El mismo brief + mismo perfil = mismo prompt renderizado (testeable sin red). **Orden obligatorio: prefijo estable (kit + perfil) primero, brief al final** — nada volátil por delante, o la caché de prompt no sirve. Test: dos renders con briefs distintos comparten prefijo byte a byte. | MC-05, MC-07 | pipeline + datasci | M |
| **MC-09** | Generación de copy: N variantes vía `CopyAdapter` sobre `claude-opus-5` (thinking adaptativo + `effort`; sin `temperature` — la variación se pide por prompt), con `cache_control` al cierre del prefijo estable. Se comprueba `stop_reason` antes de leer `content`, y se opta a `fallbacks: "default"` para rechazos de política. Provenance y las cuatro cifras de coste por variante; se verifica que `cache_read_input_tokens > 0` en la segunda llamada. | MC-08, F5-MA-02 | datasci | M |
| **MC-10** | Generación de imagen on-brand: FLUX.2 [pro] → Seedream 4.0; ruta a **Ideogram** cuando el creativo lleva texto legible (headline/CTA/packaging); usa `reference_images` y `palette_rgb` del kit. | MC-08, F5-MA-02 | pipeline | M |
| **MC-11** | **Brand Fidelity Gate**: capa 1 determinista (`banned_words`, `forbidden_claims`, longitud, emoji/hashtag policy, idioma/variante) → rechazo duro; capa 2 juez LLM contra los ejes de tono, con `output_config.format` + JSON Schema (nada de parsear texto libre) → score 0-1 que alimenta la **(Q)** del router. La capa 1 corre siempre, incluso si la 2 se desactiva o la key BYOK falla. | MC-09, MC-10 | datasci | M |

### Slice 4 — HITL y salida

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MC-12** | UI Reflex: editor de brand kit + revisión/aprobación del voice profile destilado con su evidencia (HITL #0) + alta de la **API key de Anthropic de la marca** (write-only: se guarda, se valida, se muestra solo el fingerprint y el estado; nunca se re-lee ni se pinta). | MC-05, MC-06b | reflex-ui | M |
| **MC-13** | UI Reflex: bandeja de drafts — ver variantes copy+imagen, editar copy, aprobar/rechazar. Rechazo dispara (Q) o regeneración. **Nada sale sin aprobación** (`hitl_required=true`). | MC-11 | reflex-ui | M |
| **MC-14** | Salida: publicar el draft aprobado reusando `publishing/` (`publish_attempts`/`scheduled_posts`, migración 0003) o exportar. Se registra el vínculo draft→publicación para el loop futuro. | MC-13, publishing | pipeline | M |

### Slice 5 — Validación *(se define ANTES de escribir Slice 3)*

| ID | Historia | Dueño | Tamaño |
|---|---|---|---|
| **MC-15** | **Kill criterion — confirmado por el fundador 2026-08-18: a los DOS MESES de la apertura.** La pregunta es una y no necesita golden set: *¿sigues publicando con el módulo, o volviste a hacer los posts a mano?* Si volviste a mano, el módulo falló y se apaga o se rediseña. Se sustituye así la prueba ciega con umbral que heredaba de ADR 32: esa ceremonia existía porque el Motor de Ángulos se vendía como foso frente a competidores; este módulo es para los negocios propios del operador, y el uso real es la única señal que importa. **Métrica auxiliar, gratis:** piezas publicadas desde Qualify / piezas publicadas en total, medido en la semana 8. | fundador | S |

---

## 5. Riesgos y puntos donde este plan puede estar equivocado

1. **Primera dependencia de LLM del repo, y llega bajo BYOK.** Hoy hay cero ocurrencias de `anthropic` en el proyecto. Detalle de diseño en §2.1. Los tres riesgos que quedan vivos: (a) **la caída silenciosa a la key del entorno** — es el único fallo de esta capa que no hace ruido y factura mal, por eso lleva test estático propio en `MC-06a`; (b) **sin espejo de agregador**, una key inválida o un 429 del cliente no tienen ruta alternativa salvo la política explícita `on_credential_failure`; (c) la **API cambia** — modelo, betas y unidades de precio se pinean y se releen de la skill `claude-api` antes de tocar el adaptador, nunca de memoria.
2. **El juez LLM juzgando output de LLM.** Si el mismo modelo genera y evalúa el tono, el score se auto-confirma. Mitigación mínima: la capa 1 (determinista) manda y nunca se desactiva; el golden set de `MC-15` se etiqueta a mano.
3. **S2 puede rendir poco.** Un cliente con 12 posts genéricos no tiene tono destilable. `MC-03b` debe devolver "evidencia insuficiente" en vez de inventar un perfil — un perfil fabricado es peor que ausente.
4. **Precios de agregador volátiles (2–4x).** Ya mitigado por diseño (`F5-MA-03`), pero exige que el job de refresco exista desde el primer sprint, no después.
5. **Solapamiento con el Motor de Ángulos.** Slice 2 es literalmente la Épica A del ADR 32. Riesgo de divergencia si alguien la construye dos veces: por eso las historias conservan su ID `F5-MA-##` y se cierran en Linear (equipo `Qualify-market`) al completarse acá.
6. **Marcas reguladas.** Los dos tenants seedeados (PuntoServis, Inmobiliaria UY) — inmobiliaria en particular — arrastran claims prohibidos. `forbidden_claims` con chequeo determinista no es *nice to have*, es el requisito que hace publicable el output.
7. **`Brand` hoy es casi vacío** (`id/tenant_id/name`). Si "el cliente" del modelo agencia necesita más que un `Brand`, esa decisión se toma en `MC-01` y afecta al resto del repo — no se resuelve inventando una entidad paralela dentro de `creative/`.

---

## 6. Orden de ataque y paralelismo

```
MC-00 (ADR) ──┬──► Slice 1 (sustrato de marca)  ──┐
              │      MC-01 → MC-02 → MC-03a/b, MC-04 → MC-05
              │                                     ├──► Slice 3 ──► Slice 4
              └──► Slice 2 (orquestación)  ────────┘
                     F5-MA-01, F5-MA-03 → MC-06a → MC-06b → F5-MA-02 → MC-07
              MC-15 se define en paralelo, antes de que arranque Slice 3
```

- **Slice 1 y Slice 2 son independientes entre sí** — se pueden atacar en paralelo por dos ejecutores.
- El **camino crítico real del proyecto sigue siendo el despliegue** (`prioridad-despliegue-subdominio.md`). Este track no lo toca ni lo retrasa: no necesita dominio estable, ni App Review, ni Business Verification.
- Primer entregable demostrable sugerido: **MC-01 + MC-02 + MC-05 + MC-12 (mitad brand kit)** — brand kit cargado, perfil de voz aprobado y visible en la UI, *sin generar nada todavía*. Prueba el sustrato antes de gastar un dólar en APIs de generación. La otra mitad de MC-12 (alta de la key BYOK) viaja con `MC-06a/b`, en el Slice 2.
- **Ojo con la destilación de tono:** `MC-03b` y `MC-04` ya usan un LLM, así que en la práctica la capa de copy se necesita antes de lo que sugiere el orden de slices. Dos salidas: distilar con la llave de plataforma en desarrollo (el destilado no es contenido publicable), o adelantar `MC-06a` al Slice 1. Recomendado lo segundo — la custodia es la pieza que no conviene retocar después.
