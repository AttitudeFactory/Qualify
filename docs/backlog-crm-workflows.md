# Backlog — Procesos del CRM de cuentas conectadas (W1–W5)

**Fecha:** 2026-07-24 · **Autor:** agente `product-owner` (sesión /team-po) · **Reorganizado:** 2026-07-24 por `po-rm` para plegar las **5 decisiones del fundador del 2026-07-24** (registradas en `.claude/sprint-state-2026-07-23-ig-crm.md`, sección "FOUNDER DECISIONS"). · **Estado:** los conflictos de fase que antes estaban PROPUESTOS ahora están **FIRMADOS** (ADR 21/22/24 APROBADAS); las decisiones abiertas B0-2/B0-3/B0-6 quedan **resueltas** y B0-4 **reencuadrada**.

> **Bitácora de la reorganización (2026-07-24, las 5 decisiones del fundador):**
> 1. **Business Portfolio: lo posee el FUNDADOR bajo su propia entidad** (B0-3/A5-2 resueltas). C-03 deja de cubrir incertidumbre de propiedad; `key_id` por fila se mantiene como buena práctica, ya no como cobertura de propiedad. Frontera de IP con PuntoServis limpia.
> 2. **"Promociones": orgánico primero, publicidad pagada diferida** (B0-2 resuelta). El post orgánico promocional es día uno (cubierto). La Marketing API (`ads_management`, método de pago, Business Manager, cero investigación en el repo) va al parking lot **con su propia pasada de investigación**.
> 3. **Principio de prioridad: NÚCLEO COMPARTIDO primero.** El Tramo 1 se reordena/valida explícitamente por lo que sirve **a los dos** clientes (tienda + inmobiliaria). La tienda es el banco de pruebas. Lo específico de un cliente (WhatsApp, asientos multi-agente) y TikTok quedan diferidos.
> 4. **Reclasificación de fases: FIRMADA.** El backlog cita ADR 21/22/24 como **APROBADAS**. `arch-rm` aplica el cambio a `CLAUDE.md` y `arquitectura.md` en paralelo (R3) — este doc no adelanta su redacción exacta.
> 5. **robertuito → adoptar un modelo más nuevo con licencia limpia, pendiente de investigación** (B0-4 reencuadrada; investigación R6 de `datasci-rm`). El seam `SentimentProvider` es el mecanismo que absorbe el swap.

**Instrucción del fundador que define el formato de este documento:** los procesos se definen y refinan **antes** de desarrollar nada, y sólo después se asignan a un roadmap por prioridad. Por eso este doc va **workflows primero (§1–§4), backlog después (§5)**, y no al revés. Un item de §5 que no tenga su proceso definido en §1–§4 no debería entrar a sprint.

## 0. Encuadre — situación comercial real y qué la ancla

Todo lo que sigue se ordena por esta realidad, no por el mapa de fases abstracto:

| | Cliente cero | Cliente uno |
|---|---|---|
| Quién | Tienda **PuntoServis** (Cúcuta, Colombia). El fundador es **franquiciado** y administra él mismo las cuentas | Agencia **inmobiliaria en Uruguay** (amigo del fundador) |
| Asientos | 1 (él) | **N agentes humanos** de ventas |
| Medio | **Propio (owned)** | **Propio (owned)** |
| Estado | Necesidad inmediata | Segundo, no este sprint |

**Los dos son medios propios.** Ésa es la única razón por la que este documento existe: `packages/models/NOTES_manychat_activation_layer.md` §2.2 midió que la respuesta asistida es **~65 % de precisión con tasa base de medio propio (π≈10 %)** frente al **7,9 % de medio ganado (π≈0,5 %, 11,6 falsos positivos por acierto)**. El veredicto "inshippable" que mató esa feature para la tesis original de Qualify **no transfiere**, porque la premisa no transfiere.

**Restricción arquitectónica del fundador, textual:** *"yo no les voy a pedir o regalar mi inteligencia de negocio"*. La herramienta corre **en paralelo** al tooling de marketing que PuntoServis suministra a sus franquiciados; nada se construye *para* PuntoServis ni se comparte con ellos. Consecuencias en `docs/integracion-cuentas-conectadas-meta.md` §3.7 — no es una postura, es diseño.

**Fuera de alcance, declarado:** sindicación a portales de clasificados (**Gallito**, **MercadoLibre**). Es la queja real del cliente uno, pero es **otra superficie de integración** por completo, sin relación con las APIs de Meta. Se anota para que no se pierda; no se dimensiona aquí.

### 0.1 Prioridad declarada del fundador (orden de este backlog)

1. **Multi-tenant / `tenant_id`** — dos tenants reales desde el día uno.
2. **Conceder permisos desde las cuentas sociales de los clientes.**
3. **Publicar (reels, stories, promociones) y administrar desde el CRM.**
4. **Todos los canales de DM atendidos.**

> **Principio de priorización FIRMADO por el fundador (2026-07-24, decisión 3): NÚCLEO COMPARTIDO primero.** Textual: *"me quiero enfocar en las features que pueden reusar ambos emprendimientos."* El Tramo 1 (§5.2) se ordena y valida explícitamente por lo que sirve **a los dos** clientes a la vez — la fundación multi-tenant, la capa de conexión, la publicación orgánica y la bandeja poll-first son el **denominador común** de la tienda (cliente cero) y de la inmobiliaria (cliente uno). **La tienda es el banco de pruebas del núcleo compartido, no un desvío.** Lo específico de un solo cliente —WhatsApp y asientos multi-agente (inmobiliaria), publicación en TikTok (bloqueada por auditoría)— queda **diferido a propósito** (parking lot §5.4). Construir primero el denominador común es la instrucción, no una inferencia del PO. Cada item del Tramo 1 lleva ahora una línea **"Sirve a"** que hace explícito por qué es núcleo compartido.

Dirección declarada: **TikTok**. Ver §3.4 — está bloqueado por auditoría y **no admite mitigación de ingeniería**.

### 0.2 Los dos conflictos con el mapa de fases — se declaran, no se resuelven aquí

| # | Conflicto | Estado |
|---|---|---|
| **C-A** | `CLAUDE.md` sitúa **multi-tenant isolation en Fase 6** (última). El fundador la quiere primera. | **El architect lo adelantó** en `docs/integracion-cuentas-conectadas-meta.md` §1.2: *"Adelanto duro a día uno. Es la única reversión real del mapa […] No existe versión de esto con multi-tenancy pospuesta"*. ✅ **FIRMADO (decisión 4, 2026-07-24): ADR 21/22/24 APROBADAS.** `arch-rm` aplica la reclasificación a `CLAUDE.md` y `arquitectura.md` (R3) — este doc no adelanta su redacción. |
| **C-B** | `CLAUDE.md` sitúa el **inbox social unificado en Fase 6**. La prioridad #4 del fundador vive ahí. | Architect §3.6 lo reclasifica a **Parte 4-B, ahora**, con el argumento de que en medio propio *"leer y escribir no son fases distintas, son el mismo bucle"*. ✅ **FIRMADO (decisión 4): ADR 21 APROBADA.** Precisión que persiste (§7): una bandeja **de un solo canal** es Parte 4-B; el inbox **unificado cross-canal** se queda en Fase 6. |

**Ambos conflictos están ahora FIRMADOS**, no reordenados por el PO: el fundador aprobó mover multi-tenant + bandeja de un solo canal fuera de Fase 6 (decisión 4). El backlog de §5 va ordenado por la prioridad del fundador; donde un item discrepa del **texto vigente** de `CLAUDE.md` lo dice, entendiendo que ese texto lo actualiza `arch-rm` en paralelo (R3) — la discrepancia es transitoria, no un conflicto abierto.

### 0.3 Estado del código verificado contra el filesystem (2026-07-24), no contra los docs

| Afirmación | Verificado |
|---|---|
| `packages/models/` | Existe. Cascada multimodal + `eval/` + `oauth_scope.py` **con tests** (`test_oauth_scope.py`, 15 tests) + `test_filter_calibration.py` (6) + `test_ig_comments.py` (12) + 4 `NOTES_*.md` incl. `NOTES_fase0_oauth_crm.md` |
| `packages/scraper/` | Existe. `shared.py` (`RawPayloadEnvelope`, `canonical_bytes`, `content_signature`), parsers TikTok/IG, `client.py` Zyte |
| `packages/shared`, `packages/pipeline`, `packages/gpu-service` | **NO existen** |
| ClickHouse, Postgres, Redis, `docker-compose.yml`, `migrations/` | **NO existen** |
| `Qualify/` (Reflex) | Existe. SQLite + `Mention` de seed; **sin conexión al pipeline** |
| `reference/meta-instagram-platform/` | **Aterrizando** (cosecha en curso). Ya citables: `app-review.md`, `conversations-api.md`, `webhooks.md`. **Ausencia en un corpus parcial no es ausencia en la API** |
| **`tenant_id` / `tenant_id` en el código** | **CERO ocurrencias en todo el repo.** Lo único que existe es `brand_id` (`packages/scraper/src/qualify_scraper/schemas.py:76`, `shared.py:37`) |

Esa última fila es el hallazgo que define W1: **la multi-tenancy es terreno virgen**, no un refactor. Y es exactamente por eso que es barata **ahora** y carísima después.

---

## 1. W1 — Proceso: multi-tenancy y propagación de `tenant_id`

**Estado:** BORRADOR — enviado a `architect-r` y a `datasci` para desafío. No entra a sprint sin superar ambos.

### 1.1 Qué es un tenant aquí, y por qué la pregunta no es retórica

Hay **tres** niveles candidatos y el código actual sólo conoce uno:

```
Tenant / Workspace        ← NO EXISTE en el código
  └── Marca (brand)       ← existe: brand_id en packages/scraper
        └── Conexión social (cuenta IG/FB conectada)   ← NO EXISTE
              └── Contenido, comentarios, DMs, métricas
```

- **Tenant** = la unidad de facturación, aislamiento y contrato. Cliente cero = 1 tenant. Cliente uno = 1 tenant.
- **Marca** = lo que se monitoriza/administra. `docs/integracion-cuentas-conectadas-meta.md` §2.2 es explícito: *"una tenant puede tener N marcas"*, y `brand_id` es **nullable** en `social_connections`.
- **Conexión** = una cuenta profesional concreta autorizada por OAuth.

**Por qué importa para los dos clientes reales:** la inmobiliaria puede querer una marca por oficina o por desarrollo inmobiliario, con los mismos agentes atendiendo varias. Si `brand_id` se usa como tenant, eso obliga a duplicar usuarios por marca — y a partir de ahí el modelo de asientos deja de cerrar.

> **✅ W1-Q1 RESUELTA (architect-r, 2026-07-24): gana `tenant_id`.**
> `workspace_id` queda renombrado a `tenant_id` en `integracion-cuentas-conectadas-meta.md` §2.2 y en la ADR. Tres razones del architect: (1) el fundador y la tarea dicen `tenant_id`, y separarse de quien firma cuesta algo y no compra nada; (2) **`workspace` es un concepto de producto; `tenant` es un concepto de aislamiento** — pueden divergir legítimamente más adelante (un tenant, varios workspaces), y nombrar la frontera de aislamiento `workspace_id` cierra esa puerta; (3) el renombrado es **gratis hoy** — la ADR está PROPUESTA y sin construir, y hay **cero ocurrencias de cualquiera de los dos nombres en el repo**.
> Este backlog usa `tenant_id` en todo criterio de aceptación.

> **✅ W1-Q2 RESUELTA — y NO es una jerarquía. `brand_id` y `tenant_id` son ORTOGONALES.**
> Mi lectura inicial ("`brand_id` se vuelve hijo de `tenant_id`") era **incorrecta**. El ruling del architect:
>
> > **`brand_id` = qué se observa. `tenant_id` = quién tiene derecho a verlo.**
>
> Fundirlos **rompe la mitad superviviente de ADR 18**: dos tenants distintos pueden monitorizar la misma marca — eso *es* la economía de "N marcas comparten un scrape". Si marca fuera tenant, desaparece.
>
> **De ahí sale la regla dual, y es la que decide qué lleva `tenant_id` siquiera:**
>
> | Clase de dato | Clave | ¿Compartible entre tenants? |
> |---|---|---|
> | Hechos de medio ganado (posts scrapeados, comentarios públicos, menciones) | `brand_id` | **Sí** — contenido público; compartirlo es la economía de ADR 18 |
> | Datos de primera parte (respuestas de Graph API, insights propios, DMs, hilos, credenciales) | `tenant_id` | **Nunca** — ADR 22 |
>
> > **⚠ Corolario contraintuitivo, y es el que evita un error irreversible: `tenant_id` NO va en todo prefijo de `ORDER BY`.** Ponerlo en las tablas de medio ganado **destruiría la economía del scrape compartido**. Va en las tablas de primera parte y de conversación.
>
> **Asimetría conocida que se registra en vez de ocultarse:** las filas de medio ganado **no son auto-aislantes**. La comprobación "¿tiene este tenant derecho a esta marca?" vive en la aplicación, sobre el mapeo tenant→marca. Es defendible porque el dato subyacente es público (una fuga expone *qué marca monitoriza alguien*, no datos privados de nadie), pero **no** es el aislamiento estructural que se exige a primera parte. **No se documenta como aislamiento uniforme.**

### 1.2 Proceso de alta de tenant (end to end)

| # | Paso | Actor | Resultado observable |
|---|---|---|---|
| 1 | Crear tenant (nombre, país, zona horaria, moneda) | Operador de Qualify (hoy: el fundador) | Fila en `tenants`. `tenant_id` UUID emitido |
| 2 | Crear el usuario propietario | Operador | Fila en `users` + `tenant_members(role='owner')` |
| 3 | El propietario invita asientos adicionales | Propietario | `tenant_invitations` → al aceptar, `tenant_members(role='agent'\|'viewer')` |
| 4 | Crear al menos una marca | Propietario | `brands(tenant_id, …)`. **Toda marca pertenece a exactamente un tenant** |
| 5 | Conectar una cuenta social a una marca | Propietario/admin | → **W2** (§2). `social_connections(tenant_id, brand_id, …)` |
| 6 | El tenant queda operativo | — | Todo dato posterior nace con `tenant_id` |

**Regla dura, y es la que hace verificable todo lo demás:** ninguna fila de negocio se crea sin `tenant_id`. No hay estado "global" ni fila huérfana; el propio tenant del fundador (cliente cero) es un tenant normal, sin caso especial. Un caso especial para el fundador es exactamente el atajo que hace que el aislamiento no se pruebe nunca.

### 1.3 Propagación por los dos planos de datos

Sigue la regla de dos planos de `docs/arquitectura.md` §1.3/§2 — Postgres es verdad transaccional, ClickHouse hechos analíticos inmutables, **las escrituras nunca cruzan**:

| Plano / almacén | Cómo viaja el tenant | Nota |
|---|---|---|
| **Postgres** | Columna `tenant_id` NOT NULL en **toda** tabla de negocio + índice encabezado por ella | Plano del CRM: conexiones, credenciales, usuarios, hilos de DM, intentos de publicación |
| **ClickHouse** | `tenant_id` como columna y **en el prefijo del `ORDER BY`** | ⚠ **El architect no fija ningún `ORDER BY` este sprint** (requiere el gate `clickhouse-architecture-advisor`; es inmutable una vez creado). Se presenta como candidato PROPUESTO-NO-LOCKEADO |
| **R2 (payloads crudos)** | `tenant_id` **obligatorio en el prefijo de la clave** cuando `source_class='first_party_api'` | Ver §1.4. Esto **invierte** el keying de ADR 18 |
| **Redis** | Namespace por tenant en colas, locks de refresh, dedupe de webhooks y contadores de rate limit | Efímero, pero un lock sin namespace es una colisión cross-tenant |
| **Provenance de señales** | Toda señal derivada lleva `tenant_id` + `connection_id` además de `source_id` + `detector_version`/`pipeline_version` | `CLAUDE.md` lo exige para señales; `integracion-cuentas-conectadas-meta.md` §2.4c añade el eje "base legal de adquisición" |

### 1.4 La inversión de ADR 18 — el punto con riesgo de fuga real

`packages/scraper/src/qualify_scraper/shared.py:10-11` documenta el diseño actual, textual en el código:

> *"keyed by `(platform, url)`, not `brand_id`, so N brands monitoring the same post share a single scrape"*

Ese razonamiento es **correcto para scraping** (un post público es el mismo objeto para todos, y compartirlo ahorra coste de Zyte) y **peligroso para primera parte**: una respuesta de Graph API contiene analytics privados y comentarios de la cuenta de **un** cliente. `docs/integracion-cuentas-conectadas-meta.md` §2.4b lo dictamina sin ambigüedad:

> *"Colapsar ambos casos en una sola función de clave es una fuga cross-tenant, no una optimización."*

**Proceso derivado:** el envelope pasa a `payload_schema_version = 2` con `source_class: 'scrape' | 'first_party_api'`, `zyte_request_meta` → `transport_meta`, y **la función de clave se bifurca por `source_class`**. Es trabajo de `pipeline` sobre `shared.py`; la decisión es del architect. Hoy **ninguna de las dos cosas ha empezado** (verificado en el fichero).

### 1.5 Garantías de aislamiento — seis capas, y cada una es verificable por separado

Se enumeran así porque "es multi-tenant" no es un criterio de aceptación y "ninguna consulta cruza tenants" sí lo es.

| Capa | Garantía | Cómo se verifica |
|---|---|---|
| **L1 — Scoping de consulta** | Toda consulta lleva el filtro de tenant | Test: un repositorio sin `tenant_id` no compila / falla |
| **L2 — Defensa en profundidad (Postgres RLS)** | Aunque L1 falle, la base no devuelve filas ajenas | Test de integración: sesión con tenant A, `SELECT` sin `WHERE` → 0 filas de B |
| **L3 — Almacenamiento (R2)** | Ninguna clave de primera parte es alcanzable sin el prefijo de tenant | Test unitario de la función de clave (§1.4) |
| **L4 — Secretos** | DEK por tenant; una clave comprometida no abre otro tenant | `oauth_credentials.key_id` por fila (§2.2 del doc del architect) |
| **L5 — Recursos compartidos** | Un tenant ruidoso no degrada a otro **en la ruta de lectura** | Token bucket por tenant delante del scheduler de fetch. **Capa posterior, no día uno** — ver corrección abajo |
| **L6 — Auditoría** | Toda acción sobre una conexión es atribuible a tenant + actor | `connection_events` append-only |

> **Corrección del architect a mi L5 — la escribí más cara de lo que es.** Yo afirmé que el techo de Meta es por app y que por tanto el cliente uno puede degradar al cliente cero desde el día uno. **Es falso para publicación:** el límite de **100 posts/24 h es por cuenta de Instagram, no por app** [V], así que la inmobiliaria **no puede agotar la cuota de publicación de cliente cero**. Lo que sí es de nivel app es el **volumen de llamadas a Graph API** (Business Use Case rate limits).
>
> **Consecuencia:** el riesgo de vecino ruidoso es real en la ruta de **lectura/webhook/polling**, no en publicación. Eso hace L5 una garantía **más estrecha y más barata** de lo que escribí, y es la razón por la que el architect la coloca como **capa posterior** y no como día uno: con dos tenants la exposición está acotada y el mecanismo correcto depende de datos de volumen de llamadas que **no tenemos**. Estructura exacta del límite marcada **[V]**.

**Cómo se parte la "multi-tenant isolation" de Fase 6** (ruling del architect — mover el bloque entero habría sido tan erróneo como no mover nada):

| Pieza | Cuándo |
|---|---|
| Identificador `tenant_id` + RLS de Postgres + keying de R2 | **Ahora — deja de ser Fase 6, pasa a fundación** |
| Fair-share de rate limit (L5) | Capa posterior |
| Cuotas de recursos, auditoría multi-tenant completa | **Se queda en Fase 6** (hardening genuino) |

**✅ W1-Q5 RESUELTA: RLS desde el día uno** — por coherencia, no por preferencia. El architect ya dictaminó dos veces esta sesión que el aislamiento debe ser **estructural, no disciplinario** (el validador que hace inconstruible un envelope de primera parte sin tenant; la derivación de clave por encima del store). Dictar que Postgres se apañe con disciplina de aplicación contradiría ambas — y Postgres es donde viven **las credenciales OAuth y los DMs**.

**Pero el coste no está donde yo lo situé.** Lo caro de retrofitar no son las políticas: son (i) que toda tabla tenga `tenant_id NOT NULL` y (ii) **un único helper de sesión que fije el GUC de tenant por transacción**. Con (i) y (ii) desde el principio, añadir políticas después es mecánico; sin ellos, no ocurre nunca.

> **Ruling vinculante:** desde la primera migración, toda tabla de tenant lleva `tenant_id NOT NULL`; **un solo** helper de conexión/sesión ejecuta `SET LOCAL app.tenant_id` por transacción y **es el único camino a la base**; las políticas RLS se declaran **en la misma migración que crea la tabla**.

**Dos detalles que se olvidan siempre y son los que sostienen la garantía:**

- **El rol de la aplicación NO debe ser propietario de las tablas.** En Postgres el propietario **se salta RLS** por defecto. Que la app conecte como propietario significa que las políticas existen y **no protegen nada** — peor que no tenerlas, porque fabrican confianza falsa.
- Usar **`FORCE ROW LEVEL SECURITY`** donde el propietario también deba quedar sujeto, y probar el aislamiento con **una lectura cross-tenant que espera cero filas**, no con un test que afirma que una política está declarada. La garantía es *"no puede leer filas de otro tenant"*, no *"hay una política"*.

### 1.6 Modelo de asientos y roles — dirigido por el cliente uno

Cliente cero necesita 1 asiento. Cliente uno es la razón de que exista este apartado.

| Rol | Puede | No puede |
|---|---|---|
| `owner` | Todo, incluido conectar/desconectar cuentas, facturación, invitar | — |
| `admin` | Conectar cuentas, publicar, gestionar asientos | Facturación |
| `agent` | Atender conversaciones asignadas, redactar respuestas, publicar si se le concede | Tocar conexiones ni credenciales |
| `viewer` | Leer dashboards | Escribir |

**Regla:** ningún rol accede jamás a `oauth_credentials`. Ni el `owner`. Los tokens sólo los resuelve el `CredentialResolver` del servidor, que entrega **un cliente HTTP ya autenticado, nunca un token** (§2.3 del doc del architect). Es la regla que impide que un token acabe en un log o en un payload archivado.

La asignación de conversaciones entre `agent`s se define en **W4** (§4) — aquí sólo se fija que el asiento existe y a qué tenant pertenece.

### 1.7 Frontera de IP con PuntoServis, traducida a proceso

1. La app de Meta se registra bajo el **portfolio de negocio del fundador**, nunca bajo el de PuntoServis. Sin integración, sin export, sin cuenta compartida (§3.7.1).
2. ✅ **RESUELTA (decisión 1 del fundador, 2026-07-24 — A5-2/B0-3): el Business Portfolio lo posee el FUNDADOR, bajo su propia entidad.** La cuenta profesional de Instagram de la tienda vive bajo el portfolio del fundador, **no** bajo el de PuntoServis. Consecuencias: (a) la frontera de IP con PuntoServis queda **limpia** por construcción; (b) la custodia de tokens de C-03 **deja de tener que cubrir incertidumbre de propiedad** — el `key_id` por fila se mantiene como buena práctica de rotación, pero **ya no está forzado** por la duda de quién posee el activo. La pregunta que bloqueaba la custodia de tokens está cerrada.
3. **Qualify no es el único escritor sobre la cuenta.** Correr "en paralelo" a otra herramienta significa que otra herramienta publica ahí. Regla derivada y vinculante: **el estado local nunca es autoritativo sobre qué hay publicado; se reconcilia contra la API.**

### 1.8 Preguntas abiertas de W1

| # | Cuestión | Dueño | Bloquea |
|---|---|---|---|
| W1-Q1 | ~~Nombre canónico~~ | ~~architect~~ | ✅ **RESUELTA: `tenant_id`** (§1.1) |
| W1-Q2 | ~~¿`brand_id` hijo de `tenant_id`?~~ | ~~architect~~ | ✅ **RESUELTA: son ORTOGONALES**, no jerárquicos. Regla dual en §1.1 |
| W1-Q3 | Custodia de la master key: entorno de ejecución vs KMS/Vault | **fundador** (riesgo de negocio, no técnico) | Diseño de `oauth_credentials`. **Sigue abierta** — es independiente de la propiedad del portfolio (A5-2, ya resuelta): dónde vive la master key no cambia por quién posee la cuenta |
| W1-Q4 | ~~Firma de la reclasificación de fases (§3.6 del architect)~~ | ~~fundador~~ | ✅ **RESUELTA (decisión 4, 2026-07-24): FIRMADA.** ADR 21/22/24 APROBADAS; `arch-rm` aplica el cambio a `CLAUDE.md` (R3) |
| W1-Q5 | ~~¿RLS desde el día uno?~~ | ~~architect~~ | ✅ **RESUELTA: sí, RLS desde la primera migración** — con el rol de app **no propietario** y `FORCE ROW LEVEL SECURITY` (§1.5) |
| W1-Q6 | **NUEVO:** estructura exacta de los límites de rate (por cuenta vs por app) | **architect** sobre `reference/` | Dimensionado de L5 (capa posterior, no día uno) |

---

## 2. W2 — Proceso: conexión y onboarding de cuentas sociales del cliente

**Estado:** BORRADOR — enviado a `architect-r`. Contiene afirmaciones **[V]** sin verificar contra `reference/meta-instagram-platform/`, que **no existe todavía**.

> **Regla de honestidad de esta sección.** Todo dato concreto de la API de Meta va marcado **[V]** = *pendiente de verificar contra el corpus cosechado antes de escribir DDL o código*. El **proceso** no depende de esos detalles; **el dimensionado y varios modos de fallo, sí**. Donde no sé, lo digo. No se inventa ninguna capacidad de API.

### 2.1 La pregunta del fundador, respondida con su condición

> *¿Se puede automatizar el onboarding de las cuentas sociales de un futuro cliente vía las APIs de la plataforma, en vez de hacerlo a mano?*

**Sí — y el cuello de botella no es de ingeniería, es administrativo.** El flujo programático (el cliente hace clic, autoriza, la app recibe el token) es el patrón estándar de la plataforma. Lo que decide si sirve para **un tercero** no es el código sino el nivel de acceso de la app.

**Y aquí está la asimetría que hace este sprint posible.** `docs/integracion-cuentas-conectadas-meta.md` §3.1 (verificado por `architect-r` el 2026-07-24 sobre documentación oficial de Meta, tres citas literales encadenadas):

- *"Apps in **Development mode** can only request permissions from **role users**"*
- *"se **aprueba automáticamente** el acceso estándar para todos los permisos y las funciones"*
- *"**If your app will only be used by app users who have a role on the app itself you do not need to complete verification.**"*

Es decir: mientras **todos** los usuarios tengan un rol en la app (admin/developer/tester), **no hay App Review, no hay Business Verification, no hay entidad legal en la ruta crítica.** El fundador cumple por partida doble: es admin de la app y administrador de la cuenta profesional de la tienda. Y lo publicado es **contenido real y público** — Meta no tiene ninguna palanca que degrade la visibilidad de un post por el nivel de acceso de la app.

> **La frontera que hay que instrumentar en el producto, no sólo documentar.** `docs/integracion-cuentas-conectadas-meta.md` §3.4c: *"La línea Development Mode / Advanced Access es simultáneamente la frontera técnica, la frontera legal y la frontera estratégica."* Que las tres coincidan da **un único disparador observable**: el primer usuario **sin rol en la app** que intenta conectar. Ese evento debe ser detectable en el producto, no un juicio subjetivo. Ver W2-Q3.

### 2.2 Los dos regímenes de onboarding — mismo código, distinto gate

| | **Régimen A — usuarios con rol** | **Régimen B — terceros** |
|---|---|---|
| Quién | Cliente cero (fundador). Diseño y pilotos | Cliente uno y siguientes |
| Gate | **Ninguno.** Acceso estándar auto-aprobado | **App Review + Business Verification: 2–4 meses**, rechazable y revocable |
| Precondición | Rol en la app, concedido por nosotros | **Entidad legal con NIF/domicilio/web activa coincidentes** |
| Estado hoy | **Disponible ya** | No arrancado |
| Código | **Idéntico** | **Idéntico** |

**La consecuencia de planificación es la única que importa aquí:** el código de la capa de conexión es el mismo en ambos regímenes, así que **construirlo ahora no es trabajo especulativo** — es, además, requisito del propio trámite: Meta exige demo funcional del caso de uso para App Review (`integracion-cuentas-conectadas-meta.md` §1.4, punto 3). Se graba el screencast de lo que ya funciona.

**Corrección heredada, para que no se repita:** el "tope de 25 usuarios de prueba" que circula en `fase0-zernio-mercado.md` §1.1 y en `integracion-cuentas-conectadas-meta.md` §1.4 **no está respaldado por fuente primaria** (§3.1, corrección 1). El límite real es cualitativo — *tener un rol en la app* —, no un cupo numérico. Ningún item de §5 debe dimensionarse contra la cifra 25.

### 2.3 El flujo, paso a paso

| # | Paso | Actor | Estado resultante | Modo de fallo |
|---|---|---|---|---|
| **0** | **Precondición de login fork (nueva, 2026-07-24):** detectar si la cuenta IG tiene una **Página de Facebook vinculada**. Si no, **guiar el enlace ANTES de arrancar el OAuth** | Sistema + admin | `link_required` | Sin Página vinculada → el flujo de *Facebook Login for Business* no puede conceder `mentioned_media`/`mentioned_comment`; **no se lanza el OAuth**, se muestra la guía de enlace |
| 1 | El admin del tenant elige "Conectar cuenta" sobre una marca | Admin | — | — |
| 2 | Qualify genera una URL de autorización con `state` firmado y de un solo uso, que liga la sesión a `(tenant_id, brand_id, user_id)` | Sistema | — | `state` reutilizado o expirado → rechazo |
| 3 | El cliente autoriza en la pantalla de Meta y **elige qué permisos concede** | Cliente | — | Cierra la ventana → sin conexión, sin fila huérfana |
| 4 | Callback: se valida `state`, se canjea el `code` por token [V] | Sistema | `pending` | `state` inválido → 403 y descarte |
| 5 | Se leen los **scopes realmente concedidos** de la respuesta, no los solicitados | Sistema | — | **Ver §2.5 — este paso es el que casi siempre se omite** |
| 6 | Se cifra el token y se escribe `oauth_credentials` v1; `social_connections` apunta a él | Sistema | `pending` → `active` | Fallo de cifrado → sin conexión |
| 7 | Verificación inmediata: una llamada barata de identidad confirma que el token sirve | Sistema | `active` + `last_verified_at` | Falla → `degraded`, no `active` |
| 8 | Se suscriben webhooks para esa conexión [V] | Sistema | — | Fallo → conexión usable pero sin tiempo real; **debe ser visible** |
| 9 | Backfill inicial del contenido reciente | Worker | — | Bloqueado por Parte 3 (§2.7) |

**Regla de idempotencia:** la clave natural es `unique (tenant_id, platform, external_account_id)`. Reconectar la misma cuenta **actualiza la fila, no crea una segunda** — es el análogo transaccional de `(brand_id, platform, post_id)` en el plano analítico.

**Regla de correctitud sobre el paso 5, y es la que produce el resto de esta sección:** se persiste `granted_scopes`, **nunca la lista solicitada**. Meta permite conceder permisos **parcialmente**. Una app que asume que recibió lo que pidió falla más tarde, en producción, con un 403 que parece un bug de otra cosa.

### 2.4 Qué ve el cliente

1. **Antes:** qué se le va a pedir y **para qué**, en lenguaje de negocio, no de scopes. *"Para publicar tus reels desde Qualify"*, no *"instagram_business_content_publish"*.
2. **Durante:** la pantalla de Meta. No la controlamos y **no debe imitarse** — imitarla es phishing.
3. **Después:** la cuenta conectada con su estado de salud, **qué permisos concedió y qué queda inhabilitado por los que no concedió** (§2.5), y un botón de desconectar que funcione de verdad.
4. **Cuando algo se rompe:** aviso proactivo con la acción concreta a hacer. La revocación silenciosa —nos enteramos por un 401— es **un driver de carga de soporte**, no una nota al pie.

### 2.5 Degradación por scope denegado — el contrato que no existe en ningún documento

`packages/models/src/qualify_models/oauth_scope.py` (en disco, 28 celdas = 7 superficies × 4 etapas) modela qué **etapas de la cascada** aplican a cada superficie. Lo que sigue es la pieza complementaria que falta: qué **capacidad de producto** sobrevive a cada permiso denegado. Sin ella, un scope denegado se manifiesta como un 403 en runtime en vez de como una feature apagada en la UI.

| Permiso [V] | Habilita | Si se **deniega**, sigue funcionando | Se apaga |
|---|---|---|---|
| Básico de la cuenta | Identidad, media propio, insights | — (sin él no hay conexión) | **Todo** |
| Publicación de contenido | **W3** entero | Lectura, comentarios, DMs | Publicar reels/stories/promociones |
| Gestión de mensajes | **W4** (DMs) | Publicación, comentarios, listening propio | La bandeja de DM entera |
| Gestión de comentarios | Moderar/responder comentarios | Publicación, DMs, **lectura y análisis de comentarios** | Sólo la **respuesta**; el sentiment sigue |

**La última fila es la de mayor valor de producto y conviene no perderla:** leer y analizar los comentarios (sentiment, temas, intención) **no depende del permiso de responderlos**. Un cliente que deniegue el permiso de escritura sigue recibiendo el análisis completo. Eso convierte "conceder permisos" en una escalera con valor en cada peldaño, en vez de un todo-o-nada — y es el argumento de onboarding más fuerte que tenemos con un cliente desconfiado.

> **⚠ BUG DE CONTENIDO EN LA DOC DE META — y cae justo en la fila que sostiene el argumento.** `architect-r` detectó que la página de permisos de Meta tiene `instagram_business_manage_comments` con **la descripción de *content_publish* pegada debajo**. Encabezado y Dependencies correctos, prosa equivocada.
> **Es precisamente la fila de la que depende la escalera de onboarding.** Es *plausible* que leer caiga bajo el permiso básico y escribir bajo `manage_comments` —que es lo que sostendría la escalera— **pero no se asume**. El architect la marca como **la verificación de mayor valor que queda tras WhatsApp**, porque el argumento comercial con un cliente desconfiado descansa sobre ella.
> **Esta tabla se trata como PROPUESTA hasta que esa fila se verifique contra una segunda fuente.**

> **✅ V1 RESUELTA (2026-07-24, por `pipeline`) — Y NO COMO SE HABÍA PLANTEADO.**
> Se preguntaba si publicación y mensajes son **Advanced-only por naturaleza**. **No lo son, y la pregunta estaba mal formulada:** *el nivel de acceso es una propiedad de la **app**, no del permiso individual.* **No existe la trampa "Advanced-only por permiso"**, y la auto-aprobación del acceso estándar para usuarios con rol **se sostiene**.
> Dato metodológico que conviene no perder: la "página de referencia por permiso" que se buscaba **no existe** — `/docs/permissions/reference/<perm>` redirige (301) a una única página de 1,14 MB que lista **requisitos de envío a App Review por permiso**, no clasificación por nivel de acceso.
> **La frontera real es de propiedad**, literal de la doc de Meta: Advanced Access *"required if your app serves Instagram professional accounts that you don't own or manage and can be used by app users who do not have a role on your app… This access level requires App Review and Business Verification."*
> **§2.5 y §2.1 se sostienen. W3 y W4 quedan desbloqueados para cliente cero.**

### 2.6 Custodia, refresh y salud — resumen del proceso

Diseño completo en `docs/integracion-cuentas-conectadas-meta.md` §2.2/§2.3. Lo que W2 fija como **proceso**:

- **Append-only versionado.** Un refresh **nunca muta la fila existente**: escribe `version+1` y mueve el puntero en la misma transacción. Consecuencia: **un refresh fallido no destruye el token que funcionaba.** Es la regla de provenance aplicada a credenciales — nada derivado se sobrescribe, se versiona.
- **Lock distribuido por conexión antes de refrescar.** [V] Los tokens de larga duración caducan a ~60 días y se refrescan sobre sí mismos; **dos refrescos concurrentes pueden invalidar el token y desconectar al cliente en silencio.** Un solo refresh en vuelo por conexión, siempre.
- **Refrescar al ~75 % de vida, no al 95 %.** Deja margen de reintentos antes del acantilado.
- **`degraded` no es cosmético.** Es el estado que separa "fallo transitorio de red" de "el cliente revocó desde la app de Instagram". Sin él, un 401 puntual desconecta a un cliente que no hizo nada.
- **El token nunca sale de la capa de acceso.** Los workers piden un cliente HTTP **ya autenticado**, no un token. Corolario no negociable: **el `access_token` jamás aparece en logs, ni en la clave de R2, ni dentro del `RawPayloadEnvelope`.** Un token filtrado en un payload archivado es una fuga **persistente**.
- **Una conexión sin verificar no es una conexión sana.** `last_verified_at` lo actualiza un chequeo barato periódico.

### 2.7 Qué de W2 está bloqueado por la Parte 3, y qué no

`docs/integracion-cuentas-conectadas-meta.md` §1.3 — y es el matiz que hace accionable el sprint:

| Bloque | ¿Bloqueado por Parte 3 (R2, `packages/shared`, Celery, DDL `ingestion.*`)? |
|---|---|
| OAuth, cifrado de tokens, refresh, máquina de estados, tablas Postgres | **No.** Plano transaccional puro. **Se puede construir hoy** |
| Intake de webhooks + verificación de firma | **No**, si el payload crudo aterriza y se encola (necesita Redis, que es Parte 3 temprana) |
| Fetch y materialización analítica de media/comentarios/menciones/insights | **Sí, duro.** Sin `ingestion.*` ni raw store no hay dónde ponerlo |
| Sentiment/señales sobre comentarios propios | **Sí**, por transitividad |

**Los pasos 1–8 del §2.3 no están bloqueados. El paso 9 sí.** Ésa es la línea de corte del primer sprint.

### 2.8 Preguntas abiertas de W2

| # | Cuestión | Dueño | Bloquea |
|---|---|---|---|
| W2-Q1 | ~~V1/A5-1: ¿publicación y mensajes Advanced-only por naturaleza?~~ | ~~architect~~ | ✅ **RESUELTA: no existe trampa por permiso** — el nivel de acceso es propiedad de la **app** (§2.5) |
| W2-Q2 | Nombres reales de permisos, TTL de token, mecánica de refresh, cabecera de firma de webhook | **architect** sobre `reference/` | Todas las celdas [V] |
| W2-Q3 | ¿Cómo detecta el producto que un usuario **sin rol en la app** intenta conectar? Es el disparador de la frontera de §2.1 | **architect** | Instrumentar la frontera |
| W2-Q4 | ¿Bloquea W3/W4 el envelope v2, o basta con que la conexión no persista payloads hasta que exista? | **architect** | Orden de sprint |
| W2-Q5 | WhatsApp: ¿hereda la exención de Development Mode, o su gate es de verificación de entidad y número? | **investigación** | *"Todos los canales de DM"* — ver §4 |

---

## 3. W3 — Proceso: publicación (reels, stories, promociones) y TikTok

**Estado:** BORRADOR — enviado a `architect-r`. **Meta y TikTok NO son simétricos y esta sección no los trata como tales.**

### 3.0 Ambigüedad que hay que resolver antes de estimar: qué es una "promoción"

El fundador pidió publicar *"reels, stories, promociones"*. Las dos primeras son tipos de contenido con endpoint conocido. **"Promociones" no lo es**, y admite dos lecturas con **coste y gate radicalmente distintos**:

| Lectura | Qué es | Gate | Tamaño |
|---|---|---|---|
| **(a) Post orgánico promocional** | Un post/reel/story normal cuyo *contenido* promociona una oferta | **Ninguno adicional.** Es W3 tal cual | Incluido |
| **(b) Publicidad pagada** | Impulsar/crear anuncios: presupuesto, segmentación, pujas | **Marketing API — familia de permisos distinta, con toda probabilidad Advanced-only, más un método de pago y un Business Manager** | **Fase 5, no este sprint** |

**Ninguna evidencia en el repo cubre la lectura (b).** `docs/integracion-cuentas-conectadas-meta.md` §3.1 verifica publicación de contenido y volumen, y **no menciona la Marketing API en ningún punto**. La tabla de ManyChat (`ingenieria-inversa-manychat.md` §1.2) sí registra el disparador de anuncios como *"🔴 requiere ser el anunciante"* y §5.1 #20 marca Custom Audiences/CAPI como 🟡 *"exige el Business Manager del cliente"* — indicio de que el eje pagado es otro régimen, no prueba de su gate.

> ✅ **W3-Q1 RESUELTA (decisión 2 del fundador, 2026-07-24 — B0-2): AMBAS, orgánico primero.** *"Promociones"* = **(a) post orgánico promocional día uno** (es W3 tal cual, Content Publishing API, cubierto y sin gate adicional). La **(b) publicidad pagada** (Marketing API) va al **parking lot (§5.4) con su propia pasada de investigación** y **no bloquea el Sprint 1**.
> **Y el split es mayor de lo que parece: (b) NO es "W3 se hace más grande" — es una línea de producto distinta que requiere investigación desde cero.** Tres razones (confirmadas por el architect): es la **Marketing API** (otra familia de permisos —`ads_management`—, otro app product, más método de pago y Business Manager); queda **aguas abajo del reloj de App Review de todos modos**, porque gestionar el gasto publicitario de terceros es el caso paradigmático de *"cuentas que no posees ni administras"*; y **gasta dinero real del cliente**, con su propio ciclo de vida, unidad económica y riesgo. Por eso el fundador la difirió con investigación propia en vez de meterla al Sprint 1.

### 3.1 Meta — verificado, y no bloqueado para cliente cero

`docs/integracion-cuentas-conectadas-meta.md` §3.1, verificado sobre documentación oficial el 2026-07-24:

| Capacidad | Estado | Nota operativa |
|---|---|---|
| Publicar **reels** | ✅ `POST /{ig-user-id}/media` → `/media_publish` | Dos pasos: contenedor, luego publicación |
| Publicar **stories** | ✅ `media_type=STORIES` | **Trampa de parseo:** al releer el objeto, `media_type` devuelve `IMAGE`/`VIDEO`; hay que consultar **`media_product_type`** para confirmar que es story |
| Volumen | ⚠️ **Ver §3.1b — no hay una sola cifra, y la que yo había escrito era falsa** | Ninguna de las cifras candidatas ata a una tienda que publica 1–3/día |
| App Review / Business Verification | ✅ **No requeridos** para cliente cero (§2.1) | La visibilidad del post **no** se degrada por el nivel de acceso |
| Página de Facebook vinculada | ⚠️ **REQUERIDA — corrección por el fork de login** | **Actualizado 2026-07-24.** Mi fila anterior ("no requerida vía *Instagram API with Instagram Login*") **quedó obsoleta** cuando el login fork se decidió a favor de **Facebook Login for Business** (`integracion-cuentas-conectadas-meta.md` §7; formalizado como **ADR 25** por `arch-rm` (R4) en `arquitectura.md` §6). Razón del fork: `mentioned_media`/`mentioned_comment` son **exclusivos de Facebook Login**, y perderlos borraría la cascada multimodal de la vía de cuenta conectada. Consecuencia dura: **una Página de Facebook vinculada es precondición**, y **W2 debe detectarla** (~~guiar el enlace ANTES del OAuth~~ → **en el callback, tras el consentimiento**; ver §2.3, precondición nueva). **Dos actualizaciones posteriores:** (i) el *mecanismo* quedó corregido por la ruling **R4** (2026-07-25, `arquitectura.md` §6) — no existe path API pre-auth, luego el gate vinculante es la **enumeración post-consentimiento en el callback**, y la guía en UI es sólo un hint pre-flight; (ii) ADR 25 pasó a **`[APROBADO]`** el **2026-07-26** (firmada por el fundador, sin cambios) |

### 3.1b Límites de publicación — **corrección de una fabricación mía, y la doc de Meta se contradice**

**Lo que yo había escrito era falso.** Puse *"100 posts por API en ventana móvil de 24 h (50 si son carruseles)"*. **El paréntesis no existe en ninguna fuente**: lo fabriqué reconciliando dos cifras que había visto, y la reconciliación invierte la dirección real del coste. No se vuelve a escribir así.

**Las tres afirmaciones que sí están en el corpus, citadas literalmente y SIN reconciliar** (verificadas a mano el 2026-07-24):

| Fuente en disco | Qué dice literalmente |
|---|---|
| `content-publishing.md:61` | *"Instagram accounts are limited to **100 API-published posts** within a 24-hour moving period. **Carousels count as a single post.** This limit is enforced on the `POST /<IG_ID>/media_publish` endpoint"* |
| `content-publishing.md:111` (sección de carrusel) | *"Accounts are limited to **50 published posts** within a 24-hour period. Publishing a carousel counts as a single post."* |
| `content_publishing_limit.md` | `quota_total` = *"The maximum number of **IG Containers** the app user can publish within the `quota_duration`"* — **currently `50`**, `quota_duration` = 86400 s. `quota_usage` = *"the number of times the app user has **published a container**"* |

> **La propia documentación de Meta se contradice: la página dice 100 posts en la línea 61 y 50 posts en la línea 111.** Y la tercera fuente mide una **unidad distinta** (contenedores, no posts). **No se reconcilian aquí.** Reconciliarlas es exactamente el error que cometí la primera vez.
>
> **Regla vinculante para W3, y es la única afirmación segura: no se hardcodea NINGUNA de las tres cifras.** Se lee **`GET /<IG_ID>/content_publishing_limit` en runtime** y se respeta lo que devuelva — Meta marca sus propios valores como *"currently"*, es decir, sujetos a cambio. Es además lo que la propia doc recomienda: *"We recommend that your app also enforce the publishing rate limit, especially if your app allows app users to schedule posts"*.
>
> **Qué gatea esto realmente:** ninguna de las cifras candidatas ata a cliente cero (1–3 posts/día). Gatea el **scheduling futuro y el trabajo multi-cuenta**, no el primer entregable. Se documenta ahora porque un implementador que herede mi frase original habría planificado carruseles al revés.

**Lo que NO se sabe y no se afirma:** si un carrusel de 10 items consume 1 u 11 unidades del contador de contenedores. Es una inferencia razonable (cada item necesita su contenedor más el contenedor de carrusel, `content-publishing.md:100-105`) **pero no está documentada como tal**, y la línea 111 no encaja limpiamente en esa lectura. **Se resuelve leyendo `quota_usage` antes y después de publicar un carrusel de prueba** — medición, no deducción.

### 3.2 El flujo de publicación

| # | Paso | Nota de correctitud |
|---|---|---|
| 1 | **Componer**: media + caption + cuenta destino + programación opcional | Estado local, no toca la plataforma |
| 2 | **Alojar el media en una URL pública** | [V] Meta hace `cURL` del media **en el momento de publicar**, no en el de componer. Esa URL debe seguir viva y ser pública entonces. Si el media vive en R2, hay que emitir una URL alcanzable con vida suficiente — **es un requisito de infraestructura, no un detalle** |
| 3 | **Crear el contenedor** | Devuelve un id de contenedor |
| 4 | **Esperar a que el contenedor esté listo** [V] | El vídeo se procesa asíncronamente. Publicar demasiado pronto falla |
| 5 | **Publicar el contenedor** | El paso con efecto externo **irreversible** |
| 6 | **Persistir el resultado** en `publish_attempts` con `idempotency_key`, respuesta cruda, `connection_id`, `adapter_version`, `tenant_id` | Provenance de un efecto, no de un dato |
| 7 | **Reconciliar contra la API** | §3.3 — no contra la base local |

**El paso 5 es el único irreversible del sistema entero.** Todo lo demás en Qualify es lectura o estado interno; publicar toca la cuenta pública de un cliente. Merece un tratamiento distinto al de un job cualquiera: `publish_attempts` se escribe **antes** del intento, no después, para que un fallo ambiguo (timeout tras enviar) deje rastro en vez de desaparecer.

**Exactly-once bajo fallo ambiguo — atenuado, no eliminado.** `docs/integracion-cuentas-conectadas-meta.md` §3.4a: con N=1 tenant, 1 plataforma y 1 cuenta, *"el radio de daño es un reel duplicado en una cuenta que el propio operador ve y borra. Eso es una molestia, no un incidente de confianza con un cliente"*. **Ese razonamiento caduca exactamente cuando conecta el primer tercero** — el mismo disparador observable de §2.1.

> **ADR 22(e) — regla vinculante, y es la más estricta del sistema entero:**
> **`media_publish` es la única transición del sistema con *retry ciego prohibido*.** Un fallo ambiguo (timeout tras enviar) **no se reintenta**: se resuelve **por reconciliación contra la API**.
>
> Y la plataforma regala el ancla para hacerlo: el **`creation_id` del contenedor** de Meta es *"un ancla de idempotencia que la plataforma regala: estable, consultable, sobrevive a nuestro crash"* (ADR 22, razonamiento 7). El patrón es **write-ahead + reconciliación, nunca reintento**: se persiste el intento con su `creation_id` **antes** de publicar; si la respuesta se pierde, se consulta el estado del contenedor en vez de volver a publicar.
>
> Es la diferencia entre "probablemente no duplicamos" y "no podemos duplicar". Se construye así desde el día uno: retrofitarlo después de tener clientes es hacerlo con datos ya sucios.

### 3.3 Qualify no es el único escritor — regla vinculante

`docs/integracion-cuentas-conectadas-meta.md` §3.7.3: la herramienta corre **en paralelo** al tooling de PuntoServis, es decir, **otra herramienta publica en la misma cuenta**.

> **Regla: el estado local NUNCA es autoritativo sobre qué hay publicado. Se reconcilia contra la API.**

Cualquier feature que cuente posts, mida rendimiento o evite duplicados **debe leer de Meta, no de la base de datos propia**. Es una restricción arquitectónica derivada de la frontera de IP con PuntoServis, y afecta al diseño del calendario, del dashboard de métricas y de cualquier lógica anti-duplicado.

### 3.4 TikTok — bloqueado, y es peor de lo que decía el repo

`docs/integracion-cuentas-conectadas-meta.md` §3.2, literal de las [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) de TikTok:

> *"Unaudited API Clients can only post contents in `SELF_ONLY` viewership."*
>
> *"Unaudited API Clients can allow up to 5 users to post in a 24 hour window. **All user accounts using the API client to post must be set to private at the time of posting.**"*

**La segunda frase no estaba recogida en ningún documento del repo antes de ayer.** No es que el *post* salga privado: **la cuenta entera tiene que estar en privado en el momento de publicar**. Para una cuenta de tienda eso significa **apagar el escaparate para poder publicar en él**. No es "no funciona": es destructivo.

La restricción aplica *"regardless of account ownership"* — **administrar la cuenta uno mismo no la levanta.** La simetría que se planteaba como hipótesis **no existe**.

| | Meta (IG) | TikTok |
|---|---|---|
| ¿Bloquea a **cliente cero** (cuentas propias)? | **No** | **Sí** |
| ¿La cuenta propia levanta la restricción? | Sí, es el mecanismo exacto | **No.** Explícitamente independiente de la propiedad |
| Naturaleza del gate | Administrativo, corre en paralelo, coste de ingeniería cero | Administrativo **y además degrada el producto** mientras corre |

> **Distinción que hay que preservar en todo material de producto y en el roadmap:** lo bloqueado es **la publicación en TikTok vía API**, no TikTok como canal. El fundador puede publicar a mano en TikTok hoy mismo. Lo que no puede es que **Qualify lo haga por él**. El roadmap dice *"publicación programada en TikTok"*, nunca *"TikTok"* — la diferencia es literalmente lo que se le promete al cliente cero.
>
> **Sin fecha. Sin mitigación de ingeniería.** Ningún item de §5 lo planifica.

### 3.5 Programación (scheduling) — por qué no es "publicar, pero luego"

Un post programado es una **promesa con efecto externo diferido**, y eso cambia sus requisitos:

- Sobrevive a reinicios: la programación vive en Postgres, no en memoria ni en un `countdown` de Celery.
- **Se ejecuta con el token vigente en el momento de publicar, no con el de la programación.** Si la conexión pasó a `degraded` entre medias, el post **no se publica y se avisa** — no se reintenta a ciegas contra una credencial muerta.
- La zona horaria es la del **tenant** (Colombia y Uruguay son husos distintos; con dos tenants ya es un bug real, no teórico).
- El media del paso 2 debe seguir vivo y público **en el momento de publicar**, que puede ser días después de componer.

### 3.6 Preguntas abiertas de W3

| # | Cuestión | Dueño | Bloquea |
|---|---|---|---|
| W3-Q1 | **¿"Promociones" = orgánico promocional (a) o publicidad pagada (b)?** | **fundador** | El tamaño y la fase de W3 |
| W3-Q2 | ~~V1/A5-1 para publicación~~ | ~~architect~~ | ✅ **RESUELTA, no pendiente.** W3 desbloqueado para cliente cero |
| W3-Q3 | ~~Alojamiento del media~~ | ~~architect~~ | ✅ **RESUELTA: se mintea la URL firmada en el paso de PUBLICAR, no en el de componer.** El TTL sólo tiene que cubrir **la operación de publicación (minutos)**, no el horizonte de programación (días). **El problema se disuelve por secuenciación, no por infraestructura.** Mi §2.7 se sostiene, con la precisión de que depende de **la rebanada R2** de la Parte 3 — subconjunto estricto, sin ClickHouse, sin Celery, sin `ingestion.*`. Bonus: un bucket público con media de clientes es un activo expuesto permanentemente; una URL firmada de minutos no. **[V]** verificar que el fetcher de Meta acepta una URL con query string de firma; si no, ruta propia con token opaco caducable |
| W3-Q4 | Ciclo de vida del contenedor: timeouts, estados, reintentos seguros | **architect** sobre `reference/` | Pasos 3–5 |

---

## 4. W4 — Proceso: atención de DMs y comentarios (todos los canales, multi-agente)

**Estado:** BORRADOR — enviado a `architect-r` **y a `datasci`** (es la sección con carga de ML).

### 4.1 Por qué esto no es "la parte de escritura" y por qué eso reordena el mapa

`docs/integracion-cuentas-conectadas-meta.md` §3.4b hace la observación que reconcilia el conflicto aparente entre el mapa de fases y la prioridad del fundador:

> *"Atender un canal es un bucle: llega un mensaje o comentario (**leer**) → se clasifica por intención/sentimiento/urgencia (**aquí está todo el valor de IA**) → se responde (**escribir**). […] **leer y escribir no son fases distintas en media propia, son el mismo bucle.** Partirlo entre Fase 1 y Fase 5/6 es lo que hacía que el mapa de fases pareciera contradecir al fundador. No le contradecía: estaba trazado para otro producto."*

Consecuencia de reparto, y es la que justifica el tamaño: **publicar (W3) es commodity — se construye delgado y aburrido. Atender (W4) no lo es**, porque la mitad que decide si sirve es la de clasificación y triaje, que es literalmente la tesis de Qualify aplicada a medio propio.

**Ruling de modelado, vinculante** (`integracion-cuentas-conectadas-meta.md` §3.5): **los hilos y mensajes de DM son Postgres. No van a `ingestion.*`.** Un hilo tiene ciclo de vida y se actualiza; un `ReplacingMergeTree` no es el sitio para un objeto que cambia de estado varias veces por hora y se lee sincrónicamente para pintar una bandeja. A ClickHouse van los **hechos derivados** (sentimiento, intención, volumen, tiempo de respuesta), que son inmutables y analíticos. Los planos se unen en lectura, nunca en escritura.

**Corolario de secuenciación, favorable:** por vivir en Postgres, W4 es **la parte del roadmap menos bloqueada por la Parte 3**.

### 4.2 Matriz de canales — "todos los canales de DM" no es un conjunto homogéneo

Ventanas y límites de `docs/ingenieria-inversa-manychat.md` §2.3 (fuente primaria ManyChat + política de Meta, acceso 2026-07-23):

| Canal | Ventana de automatización | Después | Gate para cliente cero | Estado en este backlog |
|---|---|---|---|---|
| **Instagram DM** | **24 h** desde la última interacción del contacto | 7 días **sólo manual** vía live chat [V] | ✅ Ninguno (§2.1) | **Dentro** |
| Comentarios en media propio | n/a (superficie pública) | — | ✅ Ninguno | **Dentro** |
| **Messenger** (Página FB) | 24 h | Ídem | ⚠ Requiere Página + rol; no verificado que herede la exención | **Condicionado** |
| **WhatsApp** | 24 h | **Sólo plantillas aprobadas**, de pago por conversación | ❌ **Cloud API: Business Verification + verificación del número + plantillas aprobadas una a una.** Es plausible que **NO herede** la exención de §2.1, porque su gate no es de permisos sino de verificación de entidad | **BLOQUEADO pendiente de investigación (A5-4)** |
| **TikTok DM** | 48 h y **máximo 10 mensajes** sin respuesta | — | ❌ **Partner cerrado, no self-serve**; cuenta *Business* obligatoria (creator NO); geobloqueo; 1 cuenta por cuenta | **Fuera** |
| Telegram | Sin ventana | — | Ninguno | Fuera de la prioridad declarada |

> **"Todos los canales de DM atendidos" se parte en dos, y hay que decirlo antes de prometerlo:** **Instagram ✅ ahora**, **WhatsApp ⏳ tras trámite**, **TikTok ❌ programa cerrado**.
>
> **A5-4 es la pregunta de investigación más valiosa que queda abierta.** `fase0-zernio-mercado.md` §1.1 marca WhatsApp Business como *"no verificado en esta pasada — pendiente"*: es el **único canal de la prioridad declarada del fundador sobre el que no hay ninguna evidencia primaria**. Y hay una razón comercial para subir su prioridad por encima de su tamaño técnico: el inmobiliario latinoamericano funciona sobre WhatsApp. Para el cliente uno, WhatsApp probablemente **es** el canal, no un canal más.

**Límite duro que ninguna arquitectura elude** (`ingenieria-inversa-manychat.md` §2.3): **el DM saliente en frío no existe como primitiva.** La ventana **la abre el usuario, no la marca**. Sanciones documentadas por incumplir: advertencias en Business Suite, restricción de envío, **despublicación de la Página de Facebook**, **desactivación de la cuenta de Instagram**. Ninguna feature de este backlog puede iniciar conversaciones.

### 4.3 El bucle de atención — **POLL-FIRST**, y esto no es una preferencia de diseño

> **🔴 HALLAZGO QUE CAMBIA LA FORMA DE W4 (datasci-2, 2026-07-24, sobre el corpus ya cosechado en `reference/meta-instagram-platform/` — citas de ficheros en disco, no de memoria).**
>
> Mi borrador anterior era **webhook-first. Estaba mal**, y de una forma que habría metido la prioridad declarada del fundador detrás de un trámite de 2–4 meses **que la Conversations API no le impone**.
>
> | Fuente en disco | Qué dice |
> |---|---|
> | `app-review.md:12-16` | *"My app is only for a business I own or manage"* → **Standard Access, App Review NOT required**. *"I am a Tech Provider and my app serves multiple businesses"* → Advanced Access, **required** |
> | `conversations-api.md:19-20` | *"**Standard Access** if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard"* |
> | `webhooks.md:60-73` | Los webhooks exigen la app en **Live**, **Advanced Access** para `comments` y `live_comments`, y **Business Verification: Required** en las tres vías de login |
>
> > **El push en tiempo real está gateado detrás de App Review + Business Verification. El polling no.**
>
> **Consecuencia de diseño, y es vinculante para C-08:** el intake se diseña **poll-first**. Los webhooks son una **optimización de latencia para la fase Tech Provider**, no infraestructura de día uno. Un W4 webhook-first bloquea al cliente cero por un trámite que no le aplica.
>
> **Dos requisitos que se derivan y van a criterios de aceptación:**
> - El mecanismo de ingesta (poll vs push) es una **costura intercambiable**, no una decisión horneada. El mismo workflow sirve a cliente cero por polling y a cliente uno por webhook más tarde, y la diferencia **no puede ser una reescritura**.
> - El polling tiene un perfil de coste y latencia que el push no tiene: **el intervalo de poll es un parámetro de producto con consecuencia directa de coste.** Se nombra explícitamente, no se deja implícito.

| # | Paso | Plano | Nota |
|---|---|---|---|
| 1 | **Intake**: **poll periódico** de mensajes/comentarios (día uno). Webhook como costura alternativa cuando haya Advanced Access | Redis → R2 | Si/cuando se use webhook: verificar firma **antes de parsear**, 200 rápido, **no** llamar a Graph API dentro del handler |
| 2 | **Deduplicar** | Redis + almacén | Meta no garantiza entrega exactly-once. Dos capas: Redis `SETNX` con TTL (barato) + garantía durable aguas abajo, **porque Redis puede perder estado** |
| 3 | **Materializar el hilo** (crear o actualizar) | **Postgres** | `tenant_id`, `connection_id`, contacto, canal, estado, ventana |
| 4 | **Clasificar**: sentimiento, intención, urgencia | Worker → ClickHouse | §4.5. Hecho derivado con provenance |
| 5 | **Enrutar/asignar** a un agente humano | Postgres | §4.4 |
| 6 | **Redactar**: borrador asistido | Postgres | §4.5. **Siempre borrador, nunca envío autónomo** |
| 7 | **Enviar** tras aprobación humana | Efecto externo | Verificar la ventana **en el momento de enviar** |
| 8 | **Auditar** | Postgres | Quién respondió qué, cuándo, con qué borrador, aceptado/editado/descartado |

**Regla de fiabilidad heredada de §2.6 del doc del architect: ningún hecho debe tener el webhook como único camino.** Los webhooks se pierden, la app puede estar caída durante la ventana de reintentos, y una suscripción puede quedar desactivada por Meta tras fallos repetidos. **El webhook da latencia; el poll da completitud.** **En una bandeja esto no es higiene, es correctitud** — un DM perdido es un cliente sin responder dentro de una ventana de 24 h que no se puede reabrir.

Nótese que el hallazgo de datasci-2 **refuerza** esta regla en vez de contradecirla: si el poll de reconciliación tenía que existir de todos modos, y el webhook está gateado, entonces **construir el poll primero no añade trabajo — sólo lo reordena**, y elimina el trámite de la ruta crítica de cliente cero.

### 4.4 Multi-agente — el modelo del cliente uno

La inmobiliaria es la razón de esta subsección: **N agentes humanos sobre una bandeja compartida**.

| Concepto | Regla |
|---|---|
| **Propiedad** | Un hilo tiene **como máximo un** `assigned_agent_id` a la vez. Cero (sin asignar) es un estado válido y visible |
| **Asignación** | Manual (tomar / reasignar) o por regla (round-robin, por canal, por marca). ManyChat valida el patrón: *asignación automática de conversaciones* + grupos de equipo (`ingenieria-inversa-manychat.md` §1.5) |
| **Colisión** | Dos agentes no responden a la vez: el hilo se bloquea al agente asignado; otro debe reasignar explícitamente. **Sin esto, la bandeja compartida produce respuestas duplicadas al cliente final** |
| **Escalado** | Un agente devuelve el hilo a la cola o lo escala al `admin` |
| **Visibilidad** | Un `agent` ve los hilos de su tenant; **jamás los de otro tenant** (§1.5 L1/L2) |
| **Auditoría** | Toda transición de asignación y todo envío es atribuible a `(tenant_id, user_id, thread_id, timestamp)` |

> **⚠ CONFLICTO DE ALCANCE, declarado y no resuelto por mí.**
> `docs/integracion-cuentas-conectadas-meta.md` §3.6 clasifica *"Gestión de asientos multi-agente"* como **"Sigue sin fase — es cliente uno (inmobiliaria), fuera de este sprint por instrucción explícita"**.
> La tarea #17 me pide **definir** el proceso multi-agente.
> **Ambas cosas son compatibles y así lo trato:** el proceso queda **definido aquí** (que es exactamente lo que pidió el fundador — procesos antes que código), y sus items van al **parking lot de §5**, no al sprint. Cliente cero tiene **un** asiento y no necesita nada de §4.4.
> Lo que sí hay que decidir ahora, porque es caro después: si el esquema de `threads` nace **sin** `assigned_agent_id`, añadirlo luego es una migración con datos vivos. **Recomendación del PO:** la columna nace nullable desde el día uno; la *UI* de asignación es parking lot. Coste hoy: una columna. Coste después: una migración con bandeja en producción.

### 4.5 La capa de IA — anclada en la investigación, no inventada

Cuatro hallazgos de `packages/models/NOTES_manychat_activation_layer.md` y `docs/ingenieria-inversa-manychat.md` gobiernan esta subsección. Los cuatro tienen fuente.

**(1) El disparador es un clasificador zero-shot NLI, no un LLM.** `NOTES_manychat_activation_layer.md` §1.1 desmonta la feature de *Reconocimiento de intención* de ManyChat en tres tells independientes: la fórmula de prompt *USUARIO + verbo + SOBRE + ARTÍCULO* es literalmente un `hypothesis_template`; la guía *"un tema, una palabra clave, evita solapamiento"* es el fallo característico del scoring por entailment independiente; y *"cuanto más estrecho el foco, mayor precisión"* es consejo de umbral/separabilidad, no de prompting.

> *"la feature que dispara **todas** las automatizaciones de ManyChat — el punto de entrada de todo el producto — cuesta un forward pass de un encoder pequeño por etiqueta candidata, no una llamada a un LLM."*

Es **validación comercial externa** de que un cross-encoder NLI de ~500M params es adecuado en producción a escala de consumo. Refuerza `MoritzLaurer/bge-m3-zeroshot-v2.0` (MIT, verificado vivo en `hf-inference` el 2026-07-23) y **le da un segundo rol**: no sólo detector de señales de Fase 3, también **disparador de activación**. Un checkpoint, dos roles, sin infra nueva.

**(2) La respuesta asistida es shippable aquí, y NO lo era en la tesis original.** `NOTES_manychat_activation_layer.md` §2.2, aplicando Bayes con TPR 0,85 / FPR 0,05:

| Plano | Prior | Precisión | Falsos positivos por acierto |
|---|---|---|---|
| **Medio propio** (DM/comentario a tu cuenta) | ~10 % | **65 %** | 0,5 |
| Medio ganado (comentario público en vídeo ajeno) | ~0,5 % | **7,9 %** | **11,6** |

**Los dos clientes del fundador son medio propio.** El NO-GO de esa nota se dictó sobre la fila de abajo y **no transfiere a la de arriba**. Pero 65 % significa **1 de cada 3 borradores mal**: inaceptable para responder solo, perfectamente utilizable como borrador que un humano acepta o descarta.

**(3) Ruling: respuestas asistidas con aprobación humana DENTRO; respuestas autónomas FUERA.** `integracion-cuentas-conectadas-meta.md` §3.4d. Y **"fuera" no es una etiqueta de fase**: no es que las respuestas autónomas lleguen en Fase 5, es que **con 1 de cada 3 mal no funcionan**. Ningún sprint posterior las desbloquea sin nueva evidencia.

**(4) Precedente de gestión de riesgo: ManyChat auto-genera respuestas SÓLO para comentarios positivos.** `NOTES_manychat_activation_layer.md` §0.4: *"no es un hueco de producto, es gestión de riesgo disfrazada de feature: positivo es la única clase de polaridad donde equivocarse es barato."* Un operador que **posee la cuenta, el post y el hilo** aun así confina la generación a la clase segura. **Qualify no puede justificar ser menos conservador que el incumbente teniendo priors peores.**

**Qué modelo hace qué, contra lo que existe en disco:**

| Necesidad | ¿Cubierta por un modelo comprometido? |
|---|---|
| Polaridad del comentario/DM (3 clases) | ✅ **`pysentimiento/robertuito-sentiment-analysis`**, ya implementado en `packages/models/src/qualify_models/sentiment.py`. **El único encaje 1:1 de toda la teardown** |
| Intención ("pregunta por precio" vs "pregunta por horario") | ❌ **Hueco.** La polaridad no separa dos intenciones que ambas son NEU. Requiere el zero-shot NLI de (1) |
| Detección de pregunta | ❌ Hueco. No es un eje de polaridad |
| Generación del borrador | ❌ No está en la cascada, y **correctamente**: la generación pertenece al orquestador (LangGraph), no a la cascada |

> **⚠ RIESGO DE CONCENTRACIÓN — corregido tras el desafío de `datasci`, y la versión corregida es más estrecha y se sostiene mejor.**
>
> **Lo que escribí y era falso:** *"es la única etapa que transfiere sin cambios, por tanto toda la propuesta de valor de IA del día uno"*. `oauth_scope.py` (tarea #11, ya completada) dice que **`vision` y `transcription` también transfieren sin cambios** — a `mentioned_media` y `tags`. Si alguien contrasta esa frase con la matriz, se rompe.
>
> **La afirmación correcta, que es la que W4 necesita de verdad:**
>
> > En el **incremento de día uno** —sólo comentarios y DMs, sin VLM, sin GPU, sin scraping— **robertuito es el único modelo en el bucle**, y es el único modelo de la pila comprometida **sin licencia declarada**.
>
> **Segunda corrección, y para W4 importa más:** incluso dentro de ese incremento, robertuito **no es toda la IA — es 3 clases de polaridad y nada más**. No separa *"pregunta por el envío"* de *"pregunta por devoluciones"* (ambas NEU), no detecta preguntas, no rellena slots. Para un workflow de triaje, **robertuito cubre la puerta de seguridad, no el enrutado**. El primitivo de enrutado (`bge-m3-zeroshot-v2.0`) es un **hueco documentado, no una capacidad comprometida**.
>
> **La licencia es un riesgo heredado, no un descubrimiento nuevo:** ya estaba en `docs/modelos-multimodal-fase1.md:91`. Lo nuevo es sólo **la concentración**. El reencuadre completo está ahora en disco en `packages/models/NOTES_fase0_oauth_crm.md` §4.
>
> **Y el escape obvio no existe** (búsqueda en el Hub de `datasci-2`, 2026-07-24): **todo el tramo de alta descarga de sentiment social en español y multilingüe no declara licencia** — `cardiffnlp/twitter-xlm-roberta-base-sentiment`, `cardiffnlp/…-sentiment-multilingual`, `finiteautomata/beto-sentiment-analysis`: mismo problema, no son escape. `tabularisai/multilingual-sentiment-analysis` es **cc-by-nc-4.0** (clase ya rechazada por ADR 13). `nlptown/bert-base-multilingual-uncased-sentiment` es MIT pero **de forma equivocada** (5 estrellas de reseña de producto, no polaridad social). `VerificadoProfesional/SaBERT-Spanish-Sentiment` es apache-2.0 pero **binario, sin clase NEUTRAL** — y neutral es la clase mayoritaria en comentarios reales.
> **Único candidato real:** `UMUTeam/roberta-spanish-sentiment-analysis` (apache-2.0, 3 clases) — pero su base es `roberta-base-bne` (corpus de noticias/gobierno, **fuera de distribución** para texto social), **sin métricas publicadas** y con 4 órdenes de magnitud menos de uso.
>
> **Por tanto "lo cambiamos si la licencia da problemas" NO es una mitigación válida que escribir**: el objetivo del cambio está sin validar y su calidad es una **pregunta de golden set, no de compras**.
>
> ✅ **Steer del fundador (decisión 5, 2026-07-24 — B0-4 REENCUADRADA): adoptar un modelo más nuevo con licencia limpia, pendiente de investigación.** No es *"resolver la licencia o aceptar y anotar"*: es *"reemplazar robertuito (viejo, ~2021, roberta-base, sin licencia declarada) por uno más actual y con licencia comercial limpia"*. El brief de investigación (**R6, dueño `datasci-rm`**) exige **las tres cosas a la vez**: (a) más actual que robertuito, (b) licencia comercial limpia (Apache-2.0/MIT), (c) sentimiento social español de 3 clases (POS/NEG/**NEU**). Es una **tarea de investigación**, no una decisión cerrable en este backlog, y está **más acotada** que "busca un modelo nuevo" porque **nuevo ≠ licenciado**: los candidatos modernos de alta descarga (`cardiffnlp/twitter-xlm-roberta-base-sentiment` y su variante multilingüe) tampoco declaran licencia, y `tabularisai/multilingual-sentiment-analysis` es cc-by-nc-4.0 (clase rechazada por ADR 13).
> **El mecanismo que absorbe el swap es el seam `SentimentProvider`** (ya en disco, `providers.py`): la adopción del modelo nuevo es *cambiar una implementación detrás del seam*, no reescribir el bucle — el seam existe exactamente para esto. **La concentración también se mueve** a `MoritzLaurer/bge-m3-zeroshot-v2.0` (§3.4b), que **debe pasar el mismo test de licencia** en R6.
> **Resultado de R6 (dueño `datasci-rm`): pendiente de plegar aquí** una vez llegue el shortlist ranqueado (licencia + recencia + encaje + descargas + recomendación de si vale medir contra el golden set).

> **⚠ CONFLICTO ENTRE DOS FUENTES DE ML — se declara, no se resuelve aquí.**
> `datasci` sostiene que `vision`/`transcription` transfieren sin cambios a `mentioned_media` y `tags` (base: `oauth_scope.py`).
> `datasci-2` reporta que el corpus cosechado **no documenta ninguna edge `mentioned_media`, `mentioned_comment` ni `/tags`**, y que `mentions` aparece sólo como campo de webhook plegado en la notificación de `comments`. Si eso se confirma, **el dato de mención llega con forma de texto, no de media**, y entonces vision/transcription **no tienen caso de uso sin cambios** en la vía OAuth — con lo que la concentración en sentiment vuelve, por una ruta distinta y más concreta.
> **Peso de la evidencia:** el propio docstring de `oauth_scope.py` declara que **los nombres de edge son PROVISIONALES** y que fundamentarlos contra el corpus cosechado es trabajo de la tarea D1. `datasci-2` tiene el corpus; `oauth_scope.py` se escribió sin él. Eso inclina la balanza, **pero la resolución es de `architect`/D1, no mía**.
> **Regla operativa mientras tanto: ningún item de §5 asume que la cascada multimodal corre sobre menciones de Instagram.** Ninguno lo hace hoy.

**(5) Puerta barata ANTES de cualquier paso generativo — requisito de arquitectura, no de optimización.** El propio ManyChat enruta así: automatizaciones determinísticas primero → puerta barata *"¿esto es un escenario de IA?"* → generación sólo después. `eval/conversation_cost.py` (código con 13 tests, calculado y no estimado) explica por qué **tiene** que ser así: con la economía por contacto publicada de ManyChat, una conversación de 3 turnos con generación fundamentada sobre el modelo frontera **más barato** cuesta **119 % de lo que ese contacto ingresa** en el tramo Advanced (356 % con Sonnet), antes de clasificación, retrieval, infra o margen.

> **La cascada no es una optimización: es lo que hace que el precio exista.** Un W4 que ponga un LLM delante de cada mensaje entrante está mal **dos veces** — caro y arquitectónicamente equivocado. *"La IA lee el DM y responde"* no es una especificación válida. **La puerta barata es un paso con nombre propio en el flujo (§4.3 paso 4), no un detalle de implementación.**

**(6) El coste que ata no son los dólares, es el tamaño del taxón de etiquetas.** A escala de dos tenants, con el clasificador auto-hospedado en el worker CPU ya provisionado, el **coste marginal por clasificación es efectivamente cero** (el gasto es el VPS fijo, no la llamada). Pero **NLI zero-shot ejecuta un forward pass por par (texto, etiqueta candidata)**, no uno por mensaje: el cómputo escala con `mensajes × nº de etiquetas de intención`. **Añadir una quinta intención cuesta lo mismo que un 25 % más de volumen de mensajes.**

> **La palanca de throughput es el taxón de etiquetas, no el número de tenants.** Es una restricción de diseño sobre la lista de intenciones de W4, no una línea de presupuesto. **Y el número de throughput no existe**: nadie ha medido la latencia CPU de `bge-m3-zeroshot-v2.0` (568M params) en este repo, y no se inventa. Queda como **input abierto declarado**, no como cifra plausible. `datasci` ofrece medirlo contra los fixtures existentes si se quiere cerrar (tarea #12).

**Nota de calibración que hay que llevar al golden set** (`NOTES_manychat_activation_layer.md` §2.3): ManyChat admite errores de identificación de idioma en **mensajes muy cortos**. Los comentarios son cortos por construcción — **ése es el régimen de fallo, no el caso borde**. Consecuencia: reportar métricas **estratificadas por longitud**, porque un F1 agregado esconde el colapso en el bucket más corto, que además es el más grande.

### 4.6 Preguntas abiertas de W4

| # | Cuestión | Dueño | Bloquea |
|---|---|---|---|
| W4-Q1 | **A5-4: ¿WhatsApp Cloud API hereda la exención de Development Mode?** | **investigación** | Si no, *"todos los canales"* es sólo Instagram en el día uno. Probablemente **el canal del cliente uno** |
| W4-Q2 | ~~V1/A5-1 para mensajes~~ | ~~architect~~ | ✅ **RESUELTA, y la respuesta se parte en dos.** La **Conversations API** opera bajo **Standard Access** para cuentas propias (`conversations-api.md:19-20`) ⇒ **W4 NO está bloqueado para cliente cero**. Los **webhooks** llevan un set de requisitos **separado y adicional** (`webhooks.md:57,60,63,73`: app **Live** + **Advanced Access** para `comments`/`live_comments` + **Business Verification requerida en las tres vías de login**) ⇒ **el push NO está disponible para cliente cero**. V1 acertó **sobre permisos**; los webhooks no son una cuestión de permiso |
| W4-Q3 | ~~Licencia de robertuito: ¿resolver ahora o aceptar y anotar?~~ → **Reencuadrada (decisión 5): adoptar un modelo más nuevo con licencia limpia** | **investigación (R6, `datasci-rm`)** | Concentración de riesgo de §4.5. El seam `SentimentProvider` absorbe el swap; `bge-m3-zeroshot-v2.0` pasa el mismo test de licencia |
| W4-Q4 | ¿La ventana de 7 días manual requiere una etiqueta de agente humano y con qué condiciones? [V] | **architect** sobre `reference/` | Paso 7; qué se puede responder fuera de 24 h |
| W4-Q5 | ~~¿Nace `threads.assigned_agent_id` en el día uno?~~ | ~~architect~~ | ✅ **APROBADA tal como se propuso.** Columna nullable desde el día uno, UI de asignación al parking lot |
| W4-Q6 | ~~¿Comentarios públicos o sólo DMs privados en el primer tramo?~~ | ~~fundador/architect~~ | ✅ **RESUELTA: DMs privados primero, y no está cerca** — ver abajo |

**✅ W4-Q6 RESUELTA (`datasci`, 2026-07-24): DM privado primero.** No es un juicio de apetito de riesgo — **las dos superficies difieren en la misma dirección en precisión Y en coste del error**, así que no hay trade que hacer:

- **Precisión.** Un DM está **deliberadamente dirigido a la marca** — es la fila π≈10 % / 65 %. Un comentario en el post propio va dirigido *al post*, y a menudo a otros comentaristas: su prior es **claramente menor que el del DM**, aunque muy por encima del caso de medio ganado. **El DM tiene la mejor precisión disponible en cualquier superficie.**
- **Coste del error.** Un borrador de DM equivocado es privado, en un hilo que abrió el contacto, y recuperable. Una respuesta pública equivocada es **la marca hablando en público bajo su propio post**, visible para todo el que lo vea y lo bastante permanente como para capturarse en pantalla.

**El contraargumento esperable y por qué no cambia la respuesta:** el volumen de comentarios casi seguro supera al de DMs, así que el valor *parece* mayor ahí. Pero un primer incremento debe optimizar **aprendizaje con downside acotado**, y la telemetría aceptar/editar/descartar es igual de informativa desde DMs — mismo clasificador, mismo bucle de aprobación. Se obtiene el dataset de evaluación **sin el modo de fallo público**.

> **Advertencia que va explícita en W4: la aprobación humana mitiga el error del *modelo*, no el del *humano*.** La fatiga de aprobación es real — a volumen, los revisores sellan sin leer. *"Un humano lo aprueba"* **no es licencia para poner borradores en una superficie pública**; es una razón más para que la privada vaya primero **mientras se mide la tasa real de edición/descarte**.

**Cuando lleguen los comentarios públicos**, se adopta la restricción del propio ManyChat: generar **sólo para polaridad positiva**. Composición elegante que conviene registrar: **esa puerta es exactamente polaridad de 3 clases, es decir, precisamente lo que robertuito ya sabe hacer.** La única capacidad real del modelo comprometido es la puerta de seguridad de la superficie más arriesgada.

---

## 5. W5 — Backlog priorizado

**Orden de este backlog = prioridad declarada del fundador (§0.1)**, no el orden del mapa de fases. Donde ambos discrepan, el item lo dice.

### 5.0 Dónde la prioridad del fundador y el orden de dependencias NO coinciden — dicho de frente

Su orden es: multi-tenant → permisos → publicar → DMs. **Los dos primeros están completamente desbloqueados hoy. El tercero no del todo.**

Publicar necesita que el media esté en **una URL pública que Meta hace `cURL` en el momento de publicar** (§3.2 paso 2). Si el media vive en R2, eso arrastra una rebanada de la Parte 3 —que no ha empezado— dentro de W3. Por eso el reparto en dos tramos de abajo **no reordena su prioridad**: mantiene su orden y coloca en el Tramo 1 todo lo que se puede terminar sin bloqueo, dejando en el Tramo 2 lo que depende de decisiones abiertas (W3-Q3, V1). **Si V1 y W3-Q3 se cierran antes del sprint, C-06 y C-07 suben al Tramo 1 sin cambiar nada más.**

**Actualización 2026-07-24 — V1 se resolvió a favor y esto mejora el reparto.** No existe trampa de "Advanced-only por permiso", así que el Tramo 2 ya no está gateado por una verificación técnica. Lo que queda del Bloque 0 no es papeleo: **B0-1b (arrancar el reloj administrativo) es ahora el item de mayor plazo del proyecto** — consume cero capacidad de ingeniería y decide la fecha en que el cliente uno puede usar el producto.

### 5.1 Bloque 0 — Desbloqueos que no consumen capacidad de ingeniería

No son historias de usuario y no van a un sprint de código. Se listan primero porque **varios gatean el resto**, y porque el coste de olvidarlos es descubrirlos a mitad de sprint.

| # | Qué | Dueño | Gatea | Urgencia |
|---|---|---|---|---|
| **B0-1** | ~~V1 / A5-1: ¿publicación y mensajes son Advanced-only por naturaleza?~~ | ~~architect~~ | ~~C-07…C-10~~ | ✅ **RESUELTA 2026-07-24.** **No existe trampa por permiso** — el nivel de acceso es propiedad de la **app**, no del permiso. **Tramo 2 desbloqueado para cliente cero** |
| **B0-1b** | **El item de mayor plazo del proyecto: arrancar el reloj administrativo.** V1 acotó la frontera: **cliente cero no necesita nada; cliente uno dispara App Review + Business Verification** (sus cuentas y su personal no tienen rol en la app). **Y hay un segundo disparador que no habíamos visto: los webhooks exigen Business Verification incluso sobre cuentas propias** (`webhooks.md:63`), así que el reloj también gatea el **inbound en tiempo real de cliente cero** — bastante antes de lo que este doc decía | **fundador** | La fecha en que la inmobiliaria puede usar el producto **y** la fecha del push en tiempo real | **MÁXIMA por plazo, no por esfuerzo.** Coste de ingeniería **cero**. Precondición: entidad legal con NIF/domicilio/web activa coincidentes |
| **B0-1c** | **NUEVO — y convierte B0-1b en un item con dependencia de ingeniería.** Meta revisa **por envío, no por permiso**, así que **un solo envío cubre publicación y mensajería a la vez**. Por tanto la **demo funcional que Meta exige debe cubrir AMBAS superficies** — lo que fija qué hay que tener construido antes de enviar: **W2 + W3 + W4 en calidad de demo**. Construir la capa de conexión y el inbox **no es trabajo especulativo: es un entregable del trámite** | **fundador + architect** | El envío a App Review | Alta. Cambia el orden: no se envía hasta que el inbox exista, no sólo el publicador |
| **B0-2** | ~~**W3-Q1**: ¿"promociones" = orgánico o **publicidad pagada** (Marketing API)?~~ | ~~fundador~~ | ~~Tamaño y fase de W3~~ | ✅ **RESUELTA (decisión 2, 2026-07-24): AMBAS, orgánico primero.** Orgánico promocional = día uno (C-07). **Publicidad pagada (Marketing API) → parking lot §5.4 con su propia pasada de investigación.** No bloquea Sprint 1 |
| **B0-3** | ~~**A5-2**: ¿quién posee el Business Portfolio de la cuenta de la tienda?~~ | ~~fundador~~ | ~~Custodia de tokens (C-03), frontera de IP~~ | ✅ **RESUELTA (decisión 1, 2026-07-24): lo posee el FUNDADOR, bajo su propia entidad.** Frontera de IP con PuntoServis limpia. C-03 **deja de cubrir incertidumbre de propiedad**; `key_id` por fila se mantiene como buena práctica, ya no forzado por la duda |
| **B0-4** | **F1 → reencuadrada (decisión 5): adoptar un modelo de sentimiento más nuevo con licencia limpia, pendiente de investigación.** El brief exige las tres cosas (más actual que robertuito + Apache/MIT + 3 clases español social). **R6 RESUELTO 2026-07-24 (verificado contra el Hub en vivo por datasci-rm + lead): SÍ existen reemplazos licenciados drop-in** — `clapAI/modernBERT-base-multilingual-sentiment` (apache-2.0, hf-inference en vivo) y `clapAI/mmBERT-small-multilingual-sentiment` (MIT), ambos 3-clases label-compatibles con robertuito → cero cambio de contrato `SentimentProvider`. **Caveat que decide, no la licencia:** son de dominio multilingüe mixto, NO social-español como robertuito (TASS) → **la medición golden-set (~100 comentarios etiquetados) es el entregable, no la elección del modelo** (detalle en `docs/modelos-multimodal-fase1.md`). Recordatorio de por qué robertuito no puede quedarse sin más: *"sin licencia declarada"* **no es "sin restricciones"** — a falta de concesión aplica el copyright por defecto. La concentración **se mueve, no desaparece**: `bge-m3-zeroshot-v2.0` = MIT (verificado, pasa el test). El seam `SentimentProvider` absorbe el swap | **investigación (R6, `datasci-rm`) — CERRADA; queda la medición golden-set** | C-09, C-10 | Baja (era Alta). **Deja de ser riesgo abierto: hay reemplazos concretos con licencia limpia; sólo falta medir cuál rinde en ES social.** No bloquea el Tramo 1 |
| **B0-5** | **A5-4**: ¿WhatsApp Cloud API hereda la exención de Development Mode? | **investigación** | Todo el carril WhatsApp | Alta por valor comercial: probablemente **es** el canal del cliente uno |
| **B0-6** | ~~**A5-3 / W1-Q4**: firma de la reclasificación de fases (ADR 21, §3.6)~~ | ~~fundador~~ | ~~Aplicar cambios a `CLAUDE.md`~~ | ✅ **RESUELTA (decisión 4, 2026-07-24): FIRMADA.** ADR 21/22/24 **APROBADAS**. `arch-rm` aplica el cambio a `CLAUDE.md` y `arquitectura.md` en paralelo (R3). El backlog ya cita las ADR como aprobadas |
| **B0-7** | Colisión de numeración de ADRs detectada por el architect (`integracion-cuentas-conectadas-meta.md` declara producir ADR 20/21/22 con otra numeración que la de `arquitectura.md`) | **architect + fundador** | Legibilidad del registro | Baja, pero envenena las citas si se deja |

---

### 5.2 Tramo 1 — Fundación = NÚCLEO COMPARTIDO (desbloqueado hoy, sin dependencias externas)

Todo este tramo es **plano transaccional Postgres**. Nada aquí espera a la Parte 3, a `reference/`, ni a V1.

> **Validación explícita contra la decisión 3 del fundador (NÚCLEO COMPARTIDO primero).** El fundador pidió enfocarse en *"las features que pueden reusar ambos emprendimientos"*. El Tramo 1 **ya tenía esa forma**, y esta reorganización lo hace explícito: **los seis items (C-01…C-06) son exactamente el denominador común** de la tienda (cliente cero) y de la inmobiliaria (cliente uno). Ninguno es específico de un solo cliente. Cada uno lleva una línea **"Sirve a"** que lo justifica. Lo específico de un cliente —WhatsApp, asientos multi-agente, sindicación a portales— está fuera de este tramo por diseño (parking lot §5.4). **La tienda se usa como banco de pruebas del núcleo compartido**: se construye y se valida con cliente cero, y el mismo código sirve a cliente uno sin reescritura (§2.2).

#### C-01 — Fundación multi-tenant (`tenant_id`) en Postgres

- **Historia:** Como equipo de marketing de una marca, quiero que mis datos, mis cuentas conectadas y mis conversaciones sean invisibles e inalcanzables para cualquier otro cliente de Qualify, para poder confiarle las cuentas de mi negocio.
- **Sirve a (núcleo compartido):** **los dos clientes por igual, y es literalmente la razón de que exista más de un tenant.** Cliente cero (1 asiento) y cliente uno (N asientos) son tenants desde el día uno; sin esta fundación no hay forma de tener ambos negocios en el mismo producto sin fugas. Es el item más "compartido" del backlog.
- **Criterios de aceptación:**
  - Existen `tenants`, `users`, `tenant_members` (rol `owner|admin|agent|viewer`), `brands`, con `tenant_id` NOT NULL en toda tabla de negocio y un índice encabezado por él.
  - **`brand_id` y `tenant_id` son ortogonales, no jerárquicos** (§1.1): existe un mapeo tenant→marca, y **dos tenants pueden monitorizar la misma marca** — esa es la economía superviviente de ADR 18.
  - No existe fila de negocio de primera parte sin `tenant_id`; no hay estado global ni caso especial para el tenant del fundador.
  - **`tenant_id` NO se añade a las tablas de medio ganado** — hacerlo destruiría la economía del scrape compartido.
  - Test que falla si una consulta de repositorio omite el scope de tenant.
  - **RLS desde la primera migración**: políticas declaradas en la misma migración que crea la tabla; **un único** helper de sesión ejecuta `SET LOCAL app.tenant_id` por transacción y es el **único camino a la base**.
  - **El rol de la aplicación NO es propietario de las tablas** (el propietario se salta RLS por defecto), y se usa `FORCE ROW LEVEL SECURITY` donde el propietario deba quedar sujeto.
  - Test de aislamiento: sesión del tenant A, `SELECT` sin filtro explícito → **0 filas** del tenant B. **El test afirma "no puede leer filas de otro tenant", no "existe una política"** (§1.5).
  - Migración reproducible y reversible; `uv run pytest` verde **sin red**.
  - Seed de los **dos tenants reales**: tienda PuntoServis (1 asiento) e inmobiliaria (N asientos).
- **Fase:** Fase 6 en el texto vigente de `CLAUDE.md` → **adelantado a día uno (fundación)** por `integracion-cuentas-conectadas-meta.md` §1.2 (*"No existe versión de esto con multi-tenancy pospuesta"*) y **ADR 21 (APROBADA, decisión 4)**. La discrepancia con el texto de `CLAUDE.md` es **transitoria**: `arch-rm` sincroniza el mapa de fases en paralelo (R3).
- **Evidencia:** `integracion-cuentas-conectadas-meta.md` §1.2, §2.2 · ADR 22(a) · §1 de este doc.
- **Prioridad / tamaño:** **P0 / M**
- **Dependencias:** ninguna. **Bloquea todo lo demás.** Verificado: **cero ocurrencias** de `tenant_id`/`tenant_id` en el repo — es greenfield, no refactor.

#### C-02 — Envelope `payload_schema_version = 2` con espacios de clave disjuntos

- **Historia:** Como responsable del dato, quiero que un payload crudo de primera parte sea imposible de almacenar sin el prefijo de su tenant, para que ni una fuga cross-tenant ni una supresión imposible de cumplir puedan ocurrir por olvido de quien escribe el código.
- **Sirve a (núcleo compartido):** los dos. El contrato de datos de primera parte con espacios de clave disjuntos hace segura *cualquier* cuenta conectada — la fuga cross-tenant que previene es exactamente la que ocurriría entre cliente cero y cliente uno.
- **Criterios de aceptación:**
  - El envelope gana `source_class` (`scrape|first_party_api`), `transport`, `tenant_id`, `connection_id`; `zyte_request_meta` → `transport_meta`.
  - **Dos espacios de clave disjuntos**: la rama `scrape` conserva el keying brand-agnóstico de ADR 18; la rama de primera parte va **prefijada por `tenant_id`**.
  - La clave se deriva **del envelope, por encima del store** — ninguna implementación de `RawPayloadStore` reimplementa la regla de aislamiento.
  - **Es inconstruible** (validación que falla) un envelope de primera parte sin tenant. No existe camino de código que emita una clave sin prefijo.
  - `content_signature` **sin cambios y sin salt de tenant** (contenido idéntico debe tener identidad idéntica: dedup, re-parse auditable).
  - **Sin ruta de compatibilidad v1** — cero envelopes persistidos fuera de tests hoy.
  - Test: el `access_token` **nunca** aparece en el envelope, ni en `source_url`, ni en logs.
  - `uv run pytest` sin red en `packages/scraper`.
- **Fase:** Fase 1 Parte 4 (habilitador).
- **Evidencia:** **ADR 22(b)** y su razonamiento (1)(2)(3)(5) · `integracion-cuentas-conectadas-meta.md` §2.4 · §1.4 de este doc · código actual: `packages/scraper/src/qualify_scraper/shared.py:10-11,120-122`.
- **Prioridad / tamaño:** **P0 / M**
- **Dependencias:** C-01 (necesita que `tenant_id` exista). **Gratis hoy, caro en cuanto aterrice el raw store.** El argumento decisivo de ADR 22 no es la fuga sino la **supresión dirigida**: con prefijo, borrar el raw de un tenant es un delete por prefijo; sin él es imposible sin un índice inverso que nadie ha diseñado.

#### C-03 — Módulo `connections`: custodia de credenciales y máquina de estados

- **Historia:** Como cliente que conecta la cuenta de su negocio, quiero que mi autorización se guarde de forma que un fallo técnico no me desconecte en silencio y que nadie —ni el equipo de Qualify— pueda leer mi token, para no asumir un riesgo desproporcionado al conectarme.
- **Sirve a (núcleo compartido):** los dos. Toda cuenta conectada de cualquier cliente pasa por esta custodia; el refresh append-only y el `CredentialResolver` protegen igual el token de la tienda y el de la inmobiliaria.
- **Criterios de aceptación:**
  - Tablas `social_connections`, `oauth_credentials` (**append-only versionada**), `connection_events`, `platform_apps`, todas con `tenant_id`.
  - `access_posture: development|live` es **dato, no constante hardcodeada** (ADR 22a).
  - **Un refresh nunca muta la fila existente**: escribe `version+1` y mueve `current_credential_version` **en la misma transacción**. Test: un refresh fallido deja utilizable la credencial anterior.
  - Lock distribuido por `connection_id` antes de refrescar. Test: dos refrescos concurrentes → **una sola** llamada de refresh.
  - Máquina de estados `pending→active→degraded→revoked` con reconexión, y **un evento de dominio por transición**.
  - `CredentialResolver` devuelve **un cliente HTTP ya autenticado, nunca un token**. Test: ningún rol, ni `owner`, puede leer `oauth_credentials` por la vía de la aplicación.
  - `key_id` por fila (rotación incremental sin re-cifrar todo).
  - `uv run pytest` sin red (refresh y plataforma mockeados).
- **Fase:** Fase 1 Parte 4-A. **No bloqueado por la Parte 3** (`integracion-cuentas-conectadas-meta.md` §1.3).
- **Evidencia:** ADR 22(a) · `integracion-cuentas-conectadas-meta.md` §2.2, §2.3 · §2.6 de este doc.
- **Prioridad / tamaño:** **P0 / L**
- **Dependencias:** C-01. **B0-3 RESUELTA (decisión 1): el fundador posee el Business Portfolio bajo su propia entidad**, así que la custodia **ya no cubre incertidumbre de propiedad**. El `key_id` por fila se mantiene como **buena práctica de rotación** (rotar sin re-cifrar todo), **no** como cobertura de la duda. Custodia de la master key (entorno vs KMS) sigue pendiente de **W1-Q3** — independiente de la propiedad.

#### C-04 — Flujo OAuth de conexión, extremo a extremo

- **Historia:** Como administrador de un cliente, quiero conectar la cuenta profesional de Instagram de mi negocio en unos pocos clics y ver de inmediato si quedó bien conectada, para no depender de que alguien lo configure por mí.
- **Sirve a (núcleo compartido):** los dos, con **código idéntico** en ambos regímenes (§2.2). El fundador conecta su tienda hoy; el mismo flujo conecta a la inmobiliaria cuando pase App Review. La tienda es el banco de pruebas literal del flujo.
- **Criterios de aceptación:**
  - **Precondición de login fork (Facebook Login for Business):** el flujo **detecta si la cuenta IG tiene Página de Facebook vinculada** y, si no, **guía el enlace** (§2.3 paso 0). **Corregido por la ruling R4 (2026-07-25, `arquitectura.md` §6):** la detección ocurre **en el callback, tras el consentimiento**, no antes de emitir la URL — no existe path API pre-auth para inspeccionar una cuenta ajena sin token. La guía en UI puede mostrarse como hint pre-flight, pero **no es el gate**. Test corregido: sin Página vinculada → estado `link_required`, **cero credencial persistida y cero conexión usable** (el token recién canjeado se descarta en memoria); ~~"no se emite la URL de autorización"~~ es **infactible** y no debe testearse. Formalizado en **ADR 25**, **`[APROBADO]` desde el 2026-07-26** (firmada por el fundador, sin cambios); la estructura no depende de su redacción exacta.
  - URL de autorización con `state` **firmado y de un solo uso**, ligado a `(tenant_id, brand_id, user_id)`. Test: `state` reutilizado o expirado → rechazo.
  - El callback persiste **`granted_scopes` leídos de la respuesta, jamás la lista solicitada**. Test explícito de concesión parcial.
  - Verificación inmediata post-conexión: si falla, la conexión nace **`degraded`, no `active`**.
  - Idempotencia: reconectar la misma cuenta **actualiza la fila**, no crea una segunda (`unique (tenant_id, platform, external_account_id)`).
  - Desconectar funciona de verdad y emite `connection_events`.
  - Suite offline con un doble de la plataforma; **cero red en CI**.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `integracion-cuentas-conectadas-meta.md` §2.2, §3.1 · §2.3 de este doc. Nombres de permisos y TTL marcados **[V]** hasta `reference/` (W2-Q2).
- **Prioridad / tamaño:** **P0 / M**
- **Dependencias:** C-01, C-03. **No depende de V1** — el flujo es el mismo en ambos regímenes; lo que V1 decide es *qué permisos* se piden.

#### C-05 — Matriz permiso → capacidad (degradación explícita)

- **Historia:** Como cliente que no quiere conceder todos los permisos de golpe, quiero ver exactamente qué funciones pierdo con cada permiso que deniego, para poder empezar con lo mínimo y ampliar cuando confíe.
- **Criterios de aceptación:**
  - Función tipada y pura: `granted_scopes` → conjunto de capacidades habilitadas, con motivo por capacidad deshabilitada.
  - Cubre las cuatro familias de §2.5 y **pinea la propiedad de producto clave**: **denegar el permiso de responder comentarios NO deshabilita leerlos ni analizarlos**.
  - La UI muestra **feature deshabilitada con su motivo**, nunca un 403 en runtime.
  - Versionada como los demás artefactos de assessment (`ASSESSMENT_VERSION`), al estilo de `oauth_scope.py`.
  - `uv run pytest` sin red; totalidad de la matriz pineada por test.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** §2.5 de este doc (**contrato nuevo, no existía en ningún documento**) · complementa `packages/models/src/qualify_models/oauth_scope.py` (28 celdas, superficie × etapa).
- **Prioridad / tamaño:** **P1 / S**
- **Dependencias:** C-04. Nombres reales de permisos pendientes de W2-Q2; **la estructura no depende de ellos**.

#### C-06 — UI de conexiones en el CRM (Reflex)

- **Historia:** Como administrador, quiero una pantalla donde ver mis cuentas conectadas, su estado de salud y qué permisos concedí, para saber si mi herramienta está realmente funcionando sin tener que preguntar.
- **Sirve a (núcleo compartido):** los dos. Es la primera pantalla del CRM que toca datos reales, y sirve idéntica a ambos tenants: cada uno ve sólo sus propias conexiones.
- **Criterios de aceptación:**
  - Lista de conexiones del tenant con estado (`active|degraded|revoked`), `last_verified_at` y permisos concedidos.
  - Estado `degraded` **visible y accionable** (botón de reconectar), no un icono decorativo.
  - Capacidades deshabilitadas mostradas con su motivo (consume C-05).
  - **Nunca** se muestra ni se registra material de credencial.
  - La pantalla lee del tenant de la sesión; test de que no puede pintar datos de otro.
- **Fase:** Fase 1 Parte 4-A (UI).
- **Evidencia:** §2.4 de este doc · `Qualify/` existe hoy con SQLite de seed y **sin conexión al pipeline** (verificado).
- **Prioridad / tamaño:** **P1 / M**
- **Dependencias:** C-03, C-04, C-05. Es la primera pantalla del CRM que toca datos reales.

---

### 5.3 Tramo 2 — Publicar y atender (**DESBLOQUEADO** por V1, 2026-07-24)

> **V1 se resolvió a favor, con un límite que hay que decir en la misma frase:** no existe trampa de "Advanced-only por permiso" — el nivel de acceso es propiedad de la **app**, no del permiso. **Este tramo es construible para cliente cero sin App Review ni Business Verification… salvo los webhooks.**
>
> **Los webhooks NO están cubiertos por V1** porque su gate no es de permiso: exigen app **Live** + **Advanced Access** + **Business Verification** (`webhooks.md:57,60,63,73`). Para cliente cero **el webhook no puede dispararse en absoluto**, así que **el poll no es una red de seguridad: es el único camino que existe.** De ahí que C-08 sea poll-first y el endpoint de webhook quede **diferido**, no construido como si pudiera ejercitarse.
>
> **Lo que V1 sí acotó, y hay que respetarlo en cada item:** el alcance de todo este tramo es **cuentas que el fundador posee o administra**. En el instante en que una cuenta de la inmobiliaria se conecta, aplica Advanced Access y con él App Review + Business Verification. Eso no cambia el código (§2.2) — cambia **quién puede usarlo legalmente** y arranca un reloj de 2–4 meses (**B0-1b**).
>
> **⚠ Y cliente cero NO es una vista previa funcional limpia de la ruta real.** Literal de la doc de Meta: *"Because of the limited scope of Standard Access, some features might not work properly until your app has been granted Advanced Access."* **No se puede leer "le funciona al fundador" como validación de que le funcionará a un cliente.** Las estimaciones de C-07…C-10 llevan holgura explícita para comportamiento que sólo aparece tras Advanced Access.

#### C-07 — Publicación de reels y stories con write-ahead + reconciliación

- **Historia:** Como administrador de la tienda, quiero publicar y programar reels y stories desde el CRM, para gestionar la cuenta desde una sola herramienta sin depender del móvil.
- **Criterios de aceptación:**
  - Flujo contenedor → publicación, con espera del estado del contenedor antes de publicar.
  - `publish_attempts` se escribe **antes** del intento, con `idempotency_key`, `creation_id`, `tenant_id`, `connection_id`, `adapter_version` y la respuesta cruda.
  - **Retry ciego prohibido** (ADR 22e): ante fallo ambiguo se **reconcilia contra la API** usando `creation_id`. Test: timeout tras enviar → reconciliación, **cero republicaciones**.
  - Stories: se confirma el tipo por **`media_product_type`**, no por `media_type` (trampa de parseo documentada).
  - Programación: sobrevive a reinicios (Postgres), usa la **zona horaria del tenant**, y **se ejecuta con el token vigente en el momento de publicar**; si la conexión está `degraded` **no publica y avisa**.
  - El estado local **no** es autoritativo: el recuento de publicados se reconcilia contra la API (§3.3).
  - `uv run pytest` sin red.
- **Fase:** Fase 5 en el texto vigente de `CLAUDE.md` → **ADR 21(a) (APROBADA, decisión 4) lo trae a Parte 4-A ahora** como *commodity que se construye delgado*. Sincronización del mapa en paralelo (`arch-rm`, R3).
- **Evidencia:** `integracion-cuentas-conectadas-meta.md` §3.1 (verificado sobre doc oficial 2026-07-24), §3.3, §3.4a · **ADR 22(e)** y razonamiento (7) · ADR 23(a) BUILD nativo · §3 de este doc.
- **Prioridad / tamaño:** **P1 / L**
- **Dependencias:** C-03, C-04, **W3-Q3** (alojamiento del media — puede arrastrar Parte 3). **Alcance = post orgánico promocional (B0-2 decisión 2). La publicidad pagada (Marketing API) queda en el parking lot §5.4 con su propia pasada de investigación — NO es un ensanche de C-07.**

#### C-08 — Intake de DMs y comentarios: hilos en Postgres

- **Historia:** Como negocio, quiero que todos los mensajes y comentarios que me llegan aparezcan en un solo sitio sin perderse ninguno, para no dejar clientes sin responder.
- **Criterios de aceptación:**
  - **Intake POLL-FIRST.** Verificado en el corpus: los webhooks exigen app **Live + Advanced Access + Business Verification** (`webhooks.md:60-73`), mientras que la Conversations API opera bajo **Standard Access** para cuentas propias (`conversations-api.md:19-20`). Un diseño webhook-first mete la prioridad del fundador detrás de un trámite que no le aplica.
  - **El mecanismo de ingesta es una costura intercambiable** (poll hoy, webhook cuando haya Advanced Access). Test: cambiar de mecanismo **no reescribe** el resto del flujo.
  - **El intervalo de poll es un parámetro de producto declarado**, con su consecuencia de coste y latencia explícita — no un valor implícito en el código.
  - **El endpoint de webhook NO se construye en este item.** Para cliente cero no puede dispararse (app no Live, sin Advanced Access, sin Business Verification), así que sería código imposible de ejercitar contra una cuenta real. Se difiere hasta que la app esté Live y verificada. Lo que sí se construye es **la costura** que lo admitirá.
  - Cuando llegue: **verifica la firma antes de parsear**, responde 200 rápido y **no llama a la API dentro del handler**.
  - Deduplicación en **dos capas** (Redis `SETNX` con TTL + garantía durable aguas abajo) — *porque Redis puede perder estado*.
  - `threads` y `messages` en **Postgres, nunca `ingestion.*`** (ADR 22d), con `tenant_id`, `connection_id`, canal, estado y ventana.
  - **`threads.assigned_agent_id` nace nullable desde el día uno**, aunque la UI de asignación sea parking lot (W4-Q5: una columna hoy vs. una migración con bandeja en producción).
  - **El poll es la ruta de producción, no el respaldo.** El test *"webhook perdido → el poll lo recupera"* describe, en el día uno, **el único camino que existe** — se escribe como caso principal, no como caso de fallo.
  - La ventana de mensajería se calcula y se muestra; **enviar fuera de ventana está impedido por el sistema**, no por disciplina del usuario.
  - `uv run pytest` sin red.
- **Fase:** Fase 6 (inbox unificado) en el texto vigente de `CLAUDE.md` → **ADR 21 (APROBADA, decisión 4) trae la bandeja de UN SOLO canal a Parte 4-B ahora**; el inbox **unificado cross-canal** se queda en Fase 6 (§7). Sincronización del mapa en paralelo (`arch-rm`, R3).
- **Evidencia:** `integracion-cuentas-conectadas-meta.md` §2.6, §3.5 · **ADR 22(d)** · `ingenieria-inversa-manychat.md` §2.3 (ventanas y sanciones) · §4.2, §4.3 de este doc.
- **Prioridad / tamaño:** **P1 / L**
- **Dependencias:** C-01, C-03. Redis (Parte 3 temprana). **Alcance: Instagram únicamente.** WhatsApp bloqueado por B0-5; TikTok fuera.

#### C-09 — Sentimiento sobre comentarios de contenido propio: de prototipo a producto

- **⚠ ALCANCE REDUCIDO — el núcleo YA ESTÁ EN DISCO** (tarea #10/D2 completada 2026-07-24; verificado contra el filesystem). Existen: seam `SentimentProvider` en `providers.py`, `analyze_comments` → `CommentSentimentSummary`, `tests/test_ig_comments.py` (12 tests), y fixture `synthetic_ig_comments.json` **marcado explícitamente como SYNTHETIC**. Corrido con robertuito real sobre el fixture: `counts={'POS':1,'NEG':2,'NEU':2}`, `net_sentiment=-0.2`, `negative_share=0.4`. **Confirmado: corre hoy sin scraping, sin ClickHouse, sin VLM y sin GPU.**
- **Historia:** Como responsable de marketing, quiero ver el sentimiento de los comentarios en mi propio contenido **sobre datos reales de mi cuenta y de forma persistente**, para saber cómo recibe mi audiencia lo que publico sin leerlo todo a mano.
- **Criterios de aceptación (lo que falta para que sea producto y no prototipo):**
  - Se sustituye el fixture sintético por **payloads reales capturados**, lo que exige que **D1 (#9) fije las formas de campo contra el corpus cosechado** — hoy están marcadas *provisionales* a propósito.
  - **La sustitución obliga a borrar conscientemente el marcador `_fixture_kind: SYNTHETIC`** (hay un test que lo afirma). Ése es exactamente el momento de decidir si comentarios de usuarios reales deben vivir en un repo git. **Decisión de producto, no de ingeniería.**
  - Cada resultado **persiste** con provenance completa: `source_id` del comentario + `detector_version`/`pipeline_version` + `model_id`/`revision` + `tenant_id` + **`connection_id`** (bajo qué consentimiento se adquirió — ADR 22c).
  - Métricas **estratificadas por longitud** del fragmento: un F1 agregado esconde el colapso en el bucket más corto, **que es el más grande**.
  - **Se mantienen las tres restricciones deliberadas ya implementadas** y no se relajan sin datos: comentarios vacíos se **omiten, no se clasifican** (contados en `skipped_empty` para que los totales cuadren); **no se propone umbral de alerta** — elegir un corte de crisis sin datos etiquetados repetiría exactamente el defecto #13; y el test de integración afirma **vocabulario de etiquetas y provenance, nunca corrección** de la etiqueta.
- **Fase:** Fase 2 (reporting) sobre corpus de Parte 4. Llega antes porque el corpus llega antes.
- **Evidencia:** `packages/models/NOTES_fase0_oauth_crm.md` §6 (D2, resultados medidos) · `NOTES_manychat_activation_layer.md` §2.1, §2.3 · §4.5 de este doc.
- **Prioridad / tamaño:** **P1 / S** (era M; el núcleo ya está construido)
- **Dependencias:** C-08 (comentarios reales), **D1/#9** (formas de campo). **B0-4 (modelo de sentimiento) ya NO bloquea:** reencuadrada como investigación (R6, `datasci-rm`) y el seam `SentimentProvider` desacopla este item del modelo concreto — se adopta el reemplazo con licencia limpia detrás del seam sin tocar C-09. Robertuito puede correr como implementación de arranque mientras R6 cierra.

#### C-10 — Borradores asistidos de respuesta, con aprobación humana obligatoria

- **Historia:** Como agente que atiende conversaciones, quiero un borrador de respuesta ya redactado que yo apruebo, edito o descarto, para responder más rápido sin que se envíe nunca nada en mi nombre que yo no haya visto.
- **Criterios de aceptación:**
  - **Ninguna respuesta se envía sin acción humana explícita.** Test: no existe camino de código que envíe sin aprobación.
  - **Puerta barata con nombre propio antes de cualquier paso generativo** (§4.5.5). Test: ningún mensaje entrante llega al generador sin pasar la puerta. *"La IA lee el DM y responde"* no es una implementación aceptable.
  - **Frontera de medio propio como condición de alcance, no como flag:** el item cubre DMs y comentarios en **contenido propio del tenant**. En el momento en que alcance menciones o comentarios en contenido ajeno, la tasa base cae de π≈10 % a π≈0,5 % y la precisión de 65 % a 7,9 % — **mismo clasificador, mismo umbral, base distinta**. Escrito en el criterio, no dejado a la disciplina.
  - **Alcance del primer tramo: sólo DM privado** (W4-Q6 resuelta). Los comentarios públicos entran después y, cuando lo hagan, **sólo con polaridad positiva**.
  - Cada borrador registra **aceptado / editado / descartado** más el diff de edición — es la única señal real de calidad y **es gratis si se diseña desde el día uno**.
  - El borrador arrastra los `source_id` de lo que usó para fundamentarse; el aprobador **puede comprobar la afirmación en vez de confiar en ella**.
  - Se verifica la **ventana de mensajería en el momento de enviar**, no en el de redactar.
- **Fase:** Fase 5 en el texto vigente de `CLAUDE.md` → **ADR 21(c) (APROBADA, decisión 4) lo trae a Parte 4-B ahora, sólo en modalidad asistida.** Sincronización del mapa en paralelo (`arch-rm`, R3).
- **Evidencia:** `NOTES_manychat_activation_layer.md` §2.2 (**65 % en medio propio π≈10 % vs 7,9 % en medio ganado π≈0,5 %**), §0.4 (ManyChat autogenera **sólo positivos** — gestión de riesgo disfrazada de feature) · `integracion-cuentas-conectadas-meta.md` §3.4d · §4.5 de este doc.
- **Prioridad / tamaño:** **P2 / M**
- **Dependencias:** C-08, C-09.
- **⚠ Límite que no es de fase:** **las respuestas autónomas quedan fuera y ningún sprint posterior las desbloquea.** 65 % de precisión = **1 de cada 3 borradores mal**. No es que lleguen en Fase 5: es que a esa precisión no funcionan. Cambiar esto exige evidencia nueva, no una fase nueva.

#### C-11 — Cerrar el defecto del filtro: elegir la regla de decisión (causa raíz YA resuelta)

- **Historia:** Como equipo que confía en la cascada multimodal, quiero que el filtro use una regla de decisión validada, para que la etapa de visión sea alcanzable y las cifras de descarte de los documentos se correspondan con lo que hace el código.
- **⚠ ALCANCE MUY REDUCIDO — verificado contra el filesystem 2026-07-24, no contra el sprint-state.** Ya están en disco: `tests/test_filter_calibration.py` (6 tests, sin red, constantes medidas y hard-codeadas) **y la causa raíz resuelta** en `NOTES_fase0_oauth_crm.md` §2.2–§2.3.
- **La hipótesis de "torre de texto rota" está DESCARTADA con evidencia**, y este backlog deja de tratarla como abierta: el tokenizer real es `GemmaTokenizer` con `vocab_size` 256000 coincidente con el config; los ids CLIP (49406/49407) están en `text_config` **vestigiales y nunca se leen**; y un control positivo de nueve etiquetas sobre el mismo frame da un rango de **~4.500×** con orden semánticamente correcto. **Un encoder roto no produce ese ranking.**
- **El mecanismo real:** SigLIP calcula `sigmoid(cos · 112,67 − 16,77)`. El bias negativo grande es deliberado (pérdida sigmoide por pares, casi todo par en batch es negativo), así que **los scores absolutos pequeños son comportamiento correcto, no un bug** — por eso el defecto es invisible a simple vista. Invertir el umbral es el remate: **`threshold = 0.22` exige `cos ≥ 0,1376`, y la mejor etiqueta ajustada a mano sobre el frame real llega a 0,1034.** Ni un caption escrito para encajar supera la barra. El `0,22` se eligió casi con certeza como *softmax* uniforme sobre 5 etiquetas (`1/5 = 0,20`); SigLIP no tiene cabeza softmax.
- **Criterios de aceptación (lo único que queda):**
  - Se elige entre las tres opciones honestas —(a) umbral en espacio coseno, (b) top-k en vez de umbral, (c) umbral ajustado a datos etiquetados— **y la elección se justifica contra datos etiquetados, no por preferencia**.
  - **No se sustituye la constante equivocada por otra sin validar**: eso es el mismo defecto con mejor óptica.
  - Los dos tests que descargan pesos reciben marca `integration`; sustituto offline en el mismo cambio; **la cobertura se reubica y no baja**.
  - `HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run pytest -q` **verde en caché fría**.
- **Es una pregunta de golden set, y el golden set tiene 1 item.** Ése es el bloqueo real, y lleva sin financiarse desde hace sesiones.
- **Fase:** Fase 1 Parte 1 (deuda).
- **Evidencia:** `.claude/sprint-state-2026-07-23-ig-crm.md` §"VERIFIED Fase 1 defect" (reproducido de forma independiente por dos agentes) · `oauth_scope.py` docstring (*"el slot arquitectónico sobrevive — no que la implementación actual pueda ocuparlo"*).
- **Prioridad / tamaño:** **P2 / M**
- **Dependencias:** ninguna. Es la tarea #13 existente. **Relevancia en esta ruta:** el filtro sólo importa para media propio con pista visual; **no bloquea C-08/C-09/C-10**, que son de texto. Se incluye porque es deuda verificada y barata de acotar, no porque bloquee.

---

### 5.4 Parking lot — con la fase que lo posee

> Nada de aquí entra a sprint. Se registra con su dueño de fase para que no se cuele por la puerta de atrás ni se pierda.

| Item | Fase / estado | Por qué no ahora |
|---|---|---|
| **UI de asignación multi-agente** (tomar/reasignar/escalar, bloqueo anti-colisión, grupos) | Sin fase en `CLAUDE.md`; `integracion-cuentas-conectadas-meta.md` §3.6 lo deja **"sin fase — cliente uno"** | **Específico de cliente uno → diferido por decisión 3 (núcleo compartido primero).** Cliente cero tiene **un** asiento. El **proceso está definido en §4.4** y la columna `assigned_agent_id` nace en C-08; sólo la UI se aparca |
| **Canal WhatsApp** | Bloqueado por **B0-5** | **Específico de cliente uno → diferido por decisión 3.** Gate de verificación de entidad y número, plausiblemente **sin** la exención de §2.1. **Probablemente el canal del cliente uno** — su prioridad sube en cuanto B0-5 (investigación) cierre |
| **Publicación programada en TikTok** | **Bloqueado, sin fecha** | `SELF_ONLY` + **la cuenta entera debe estar en privado al publicar**, *"regardless of account ownership"*. Sin mitigación de ingeniería. ADR 23(c): **ni comprar ni construir**. El fundador puede publicar a mano; Qualify no puede hacerlo por él |
| **Publicidad pagada / Marketing API** | Fase 5, **sin investigar** → **diferida CON su propia pasada de investigación** (decisión 2, 2026-07-24) | **B0-2 RESUELTA: el fundador la difirió explícitamente.** No es "W3 más grande": es la **Marketing API** (otra familia de permisos —`ads_management`—, otro app product, método de pago, Business Manager), **aguas abajo del reloj de App Review** y gasta **dinero real del cliente**. **Cero líneas sobre Marketing API en todo el repo** → necesita investigación desde cero antes de dimensionarse. **Nuevo item de investigación (candidato a /team-research), no de código** |
| **Respuestas autónomas (sin humano)** | **Fuera, y no es cuestión de fase** | 1 de cada 3 mal en medio propio. Requiere evidencia nueva, no una fase nueva |
| **Sindicación a portales (Gallito, MercadoLibre)** | Sin fase, superficie distinta | Es la queja real del cliente uno pero **no tiene relación con las APIs de Meta**. Fuera por instrucción explícita |
| **Bandeja unificada cross-canal completa** | Fase 6 | C-08 cubre **Instagram**, no "todos los canales" |
| **Listening de competidores, discovery de creadores, lookalike** | Fases 1(P2/P3)–4 | **Estructuralmente inalcanzable por OAuth** (`integracion-cuentas-conectadas-meta.md` §2.8). Exige el pipeline de scraping. *Cualquier material de producto que insinúe monitorización de competidores desde cuentas conectadas es falso* |
| **Señales tipadas + clasificador zero-shot NLI** (`bge-m3-zeroshot-v2.0`) | Fase 3 (P3-0/P3-1) | Doble rol confirmado (detector + disparador de activación). **Hueco real** contra la cascada comprometida, pero C-09/C-10 no lo necesitan para el primer tramo |
| **Billing por créditos** (`billing.usage_events`) | Fase 5 | No se mintea el esquema. Recomendación heredada: **no copiar el precio por contacto de ManyChat, copiar su cascada** |
| **Insights / `ingestion.owned_metrics`** | Frontera Fase 1/2 | Duro-bloqueado por la Parte 3 |

---

## 6. Prompt sugerido para `/team-dev`

### 6.1 Por qué el primer sprint es sólo el Tramo 1

El presupuesto es de **5–6 items por compañero**, y tres items del Tramo 2 son **L** (C-07, C-08) sobre el mismo dueño que ya carga C-01…C-04. Meter los diez en un sprint produciría el fallo clásico: la fundación a medias y la publicación sin terminar, es decir, **nada demostrable**.

**Sprint 1 = Tramo 1 completo = el NÚCLEO COMPARTIDO** (decisión 3 del fundador: *"las features que pueden reusar ambos emprendimientos"*). Es la fundación de la que cuelga todo lo demás, la sirven **por igual la tienda y la inmobiliaria**, está **enteramente desbloqueada hoy**, y termina en algo que el fundador puede ver: **conectar la cuenta real de su tienda desde el CRM y verla sana**. **La tienda es el banco de pruebas del núcleo compartido**, no un cliente aparte. **Sprint 2 = Tramo 2** (C-07…C-10), ya desbloqueado por V1.

**Y arranca hoy, en paralelo y sin ingeniería: B0-1b** — el reloj administrativo de cliente uno.

### 6.2 El prompt

```
Sprint 1 — Núcleo compartido: fundación de cuentas conectadas (Fase 1 Parte 4-A).

Principio rector (decisión 3 del fundador, FIRMADA 2026-07-24): construir SÓLO el
núcleo compartido que reusan los DOS clientes — la tienda del fundador (cliente
cero, banco de pruebas) y la inmobiliaria (cliente uno). Nada específico de un solo
cliente entra en este sprint.

Lee primero, en este orden:
  1. docs/backlog-crm-workflows.md  — la bitácora de reorganización del encabezado
     (las 5 decisiones del fundador), §1 y §2 (procesos) y §5.2 (los items C-01…C-06).
     Los criterios de aceptación de §5.2 son el contrato del sprint, y cada item lleva
     una línea "Sirve a" que dice por qué es núcleo compartido.
  2. docs/integracion-cuentas-conectadas-meta.md §2, §3 y §7 — arquitectura de conexión,
     la asimetría Meta/TikTok verificada sobre fuente primaria, y el fork de login.
  3. docs/arquitectura.md ADR 21, 22, 24 y 25 (todas APROBADAS; la 25 desde el
     2026-07-26). ADR 22 es el contrato de datos de este sprint entero; ADR 25 fija
     Facebook Login for Business.

Objetivo demostrable al cerrar: conectar por OAuth la cuenta profesional real de
Instagram de la tienda desde el CRM (vía Facebook Login for Business, con la Página de
Facebook ya vinculada), verla en estado sano, y que ningún dato ni credencial de un
tenant sea alcanzable desde otro.

Reparto (respeta el mapa de propiedad de ficheros):

  pipeline-engineer  — C-01 fundación multi-tenant (tenant_id) en Postgres
                       C-02 envelope payload_schema_version=2 (packages/scraper/shared.py)
                       C-03 módulo connections: custodia de credenciales + FSM
                       C-04 flujo OAuth extremo a extremo — INCLUYE la precondición del
                            login fork: detectar la Página de Facebook vinculada EN EL
                            CALLBACK, tras el consentimiento (§2.3 paso 0, ADR 25;
                            mecanismo corregido por R4 — "antes del OAuth" es infactible,
                            no existe path API pre-auth).
  data-scientist-fde — C-05 matriz permiso→capacidad (packages/models, hermana de oauth_scope.py)
                       C-11 defecto del filtro: elegir la regla de decisión. OJO — la causa
                            raíz YA está resuelta y el test de pineo YA existe; lee
                            NOTES_fase0_oauth_crm.md §2.2-§2.4 antes de tocar nada. NO
                            recalibres sin datos etiquetados.
  reflex-ui-engineer — C-06 pantalla de conexiones en Qualify/
  principal-architect— sin código. Resuelve W1-Q5 (RLS día uno o no), W2-Q2 (nombres
                       reales de permisos/TTL contra reference/), W3-Q3 (alojamiento
                       del media), W4-Q5 (assigned_agent_id nullable ya), y la colisión
                       de numeración de ADRs (B0-7). Revisa C-02 antes de que se mezcle:
                       es la pieza con riesgo de fuga cross-tenant.

Reglas duras de este sprint:
  - `uv run pytest` verde SIN RED en todo paquete tocado. Los tests que descarguen
    pesos llevan marca `integration` y sustituto offline en el mismo cambio.
  - Type hints en toda firma nueva; ruff check + ruff format limpios.
  - Ningún access_token en logs, en claves de R2, ni dentro del envelope. Test que lo pinee.
  - Toda tabla de negocio nace con tenant_id NOT NULL. No hay caso especial para
    el tenant del fundador (él es un tenant normal — es el banco de pruebas del núcleo,
    no una excepción).
  - C-02 sin ruta de compatibilidad v1: hoy hay cero envelopes persistidos fuera de tests.
  - Nadie commitea ni pushea.

Fuera de alcance, explícito, cada uno con su motivo (§5.3/§5.4):
  - Publicar (C-07) y DMs (C-08): son Sprint 2 (Tramo 2), no específicos de cliente,
    pero L y sobre el mismo dueño — no caben en Sprint 1.
  - WhatsApp y UI de asignación multi-agente: ESPECÍFICOS DE CLIENTE UNO
    (inmobiliaria) — diferidos por decisión 3 (núcleo compartido primero). La columna
    threads.assigned_agent_id sí nace nullable en C-08; sólo la UI se aparca.
  - Publicación programada en TikTok: bloqueada por auditoría, SIN mitigación de
    ingeniería (SELF_ONLY + cuenta entera en privado al publicar). Sin fecha.
  - Publicidad pagada / Marketing API: B0-2 RESUELTA (decisión 2) = diferida CON su
    propia pasada de investigación. "Promociones" en este sprint = post orgánico
    promocional, nada de ads. Cero investigación de Marketing API en el repo.
  No adelantes ninguno aunque parezca pequeño.

Bloqueos/decisiones ya resueltos que el sprint aplica (no re-litigar):
  - B0-3 RESUELTA (decisión 1): el fundador posee el Business Portfolio bajo su propia
    entidad. C-03 se construye con key_id por fila como BUENA PRÁCTICA de rotación,
    ya NO como cobertura de incertidumbre de propiedad. Frontera de IP con PuntoServis limpia.
  - B0-4 REENCUADRADA (decisión 5): el reemplazo de robertuito por un modelo más nuevo
    con licencia limpia es investigación (R6, datasci), NO bloquea el Tramo 1. Robertuito
    puede correr como implementación de arranque; el seam SentimentProvider (ya en disco)
    absorbe el swap sin tocar el bucle. (C-09 es Sprint 2 de todos modos.)
  - Reclasificación de fases FIRMADA (decisión 4): ADR 21/22/24 APROBADAS. arch-rm
    sincroniza CLAUDE.md/arquitectura.md en paralelo (R3) — el sprint construye contra
    las ADR aprobadas y NO edita CLAUDE.md (no es su fichero).

Bloqueos abiertos que el sprint debe respetar sin resolver por su cuenta:
  - Los nombres de permisos siguen marcados [V]: C-05 se diseña con la estructura, no con
    los literales. Y la doc de Meta tiene un BUG DE CONTENIDO — la entrada de
    instagram_business_manage_comments lleva pegada la descripcion de content_publish.
    Verifica esa fila contra una segunda fuente.
  - VERIFICA CONTRA EL FILESYSTEM ANTES DE CITAR CUALQUIER DOC DE ESTADO. Varias
    afirmaciones de "esto no existe" resultaron falsas en las ultimas 24h (tests de
    oauth_scope, test de calibracion del filtro, NOTES_fase0_oauth_crm.md). Es el fallo
    recurrente de este proyecto.
```

### 6.3 Qué NO va en el prompt, y por qué

- **`CLAUDE.md` no se toca.** La reclasificación de fases (ADR 21, §3.6) sigue **PROPUESTA** hasta la firma del fundador (B0-6). El sprint construye contra las ADRs; el mapa se actualiza cuando él firme.
- **No se fija ningún `ORDER BY` de ClickHouse.** Es inmutable una vez creado y requiere el gate `clickhouse-architecture-advisor`. El Tramo 1 es Postgres puro, así que la cuestión ni se plantea — y ésa es otra razón para hacer este tramo primero.
- **No se mintea `billing.usage_events`** ni ninguna tabla de Fase 5.

---

## 7. Resumen de conflictos declarados

En un solo sitio, para el gate de calidad. **Ninguno resuelto por el PO.** Tras las decisiones del fundador del 2026-07-24: **C-A y C-B quedan FIRMADAS** (ya no son conflictos abiertos); **C-D** ya estaba resuelta; **C-C** se trata como compatible; **C-E** (conflicto entre dos fuentes de ML) sigue **abierto**, a resolución de `arch-rm`/D1.

> **Regla general que emergió tres veces esta sesión** (`tenant_id`, keying de primera parte, `assigned_agent_id`) y que el architect ha fijado como norma citable:
>
> > **Cuando una decisión de esquema es reversible hoy e irreversible tras el primer dato de producción, se toma hoy — aunque la feature que la usa esté aparcada. Lo que se difiere es la funcionalidad, nunca la forma del dato.**
>
> **Y dos reglas hermanas, del mismo tipo, sobre modelar gates como datos:**
> - **La capacidad degradada es un tipo, no una excepción.** Si *"no tengo permiso para responder comentarios"* se descubre cuando la API devuelve 403, ya es tarde: el usuario pulsó un botón que no debería haber existido. La conexión expone un **conjunto de capacidades derivado de los scopes concedidos**, y la UI pinta desde ese conjunto. **El estado de permiso es dato, no error de runtime.**
> - **Un canal es una entidad con sus propias capacidades y su propio estado de habilitación, no un enum con ramas por canal.** Los canales llegan habilitados por razones distintas — Instagram por nivel de acceso, WhatsApp por verificación de entidad y número, TikTok cerrado. **Todo gate de plataforma se modela como dato que leen la UI y el orquestador, nunca como una rama de código.**

| # | Conflicto | Estado |
|---|---|---|
| **C-A** | `CLAUDE.md`: multi-tenant isolation es **Fase 6**. El fundador la quiere primera | Architect la adelanta a día uno (§1.2, ADR 21/22/24). ✅ **RESUELTO — FIRMADO por el fundador (decisión 4, 2026-07-24, B0-6). ADR 21/22/24 APROBADAS.** `arch-rm` sincroniza `CLAUDE.md`/`arquitectura.md` (R3). Ya no es un conflicto abierto |
| **C-B** | `CLAUDE.md`: inbox unificado es **Fase 6**. Publicación es **Fase 5** | ADR 21 los trae a Parte 4-A/4-B. ✅ **RESUELTO — FIRMADO (decisión 4).** El architect **partió el conflicto en dos**: una bandeja **de un solo canal** sobre las cuentas conectadas del tenant es Parte 4-B y viene ahora; el inbox **unificado cross-canal** se queda en Fase 6. Regla para que no se re-litigue: **una bandeja no es un inbox unificado hasta que unifica más de un canal.** El mapa de fases tenía razón sobre el segundo y nunca habló del primero |
| **C-E** | **NUEVO — conflicto entre dos fuentes de ML, sin resolver.** ¿Transfieren `vision`/`transcription` sin cambios a `mentioned_media`/`tags`? `datasci` dice que sí (base: `oauth_scope.py`); `datasci-2` reporta que **el corpus cosechado no documenta esas edges en absoluto** | Resolución del **architect / tarea D1**. El propio docstring de `oauth_scope.py` declara los nombres de edge **PROVISIONALES** pendientes del corpus, lo que inclina la balanza hacia `datasci-2` — pero no lo decide el PO. **Ningún item de §5 asume hoy cascada multimodal sobre menciones** |
| **C-C** | La tarea #17 pide definir el proceso multi-agente; `integracion-cuentas-conectadas-meta.md` §3.6 lo deja fuera del sprint | **Tratados como compatibles:** proceso definido (§4.4), items en parking lot, y una sola columna nace ya (C-08). Confirmar con el architect |
| **C-D** | El fundador dice **"tenant"**; ADR 22 fija **`tenant_id`** | **Resuelto a favor de la ADR.** Se registra como desajuste de vocabulario, no de modelo (§1.1) |

**Y una discrepancia de orden, no de fase:** la prioridad del fundador pone publicar en tercer lugar, pero publicar arrastra una decisión de alojamiento de media (W3-Q3) que su segundo lugar no arrastra. El reparto en dos tramos **conserva su orden** y sólo separa lo terminable de lo que aún tiene una decisión abierta (§5.0).
