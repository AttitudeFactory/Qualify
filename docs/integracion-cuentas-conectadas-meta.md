# Integración de cuentas conectadas de Meta (Instagram Business/Creator) en el CRM de Qualify

**Estado:** análisis de arquitectura — **PROPUESTO, pendiente de aprobación del fundador**. Nada aquí supersede una ADR RESUELTA.
**Autor:** agente `architect` · **Sesión:** /team-dev, 2026-07-23.
**Pregunta que responde:** el fundador quiere conectar las cuentas Business/Creator de sus clientes al CRM SaaS de Qualify. ¿Dónde encaja eso en el mapa de fases, cómo se diseña la capa de conexión, y se compra o se construye la integración con Meta?
**ADRs que produce:** ~~ADR 20 / 21 / 22~~ → **ADR 21** (ubicación en el mapa + ruling read/write), **ADR 22** (arquitectura de conexión + provenance de primera parte), **ADR 23** (build nativo Meta vs. agregador embebido). Ver `docs/arquitectura.md` §6.
**[Corrección de numeración, architect-r 2026-07-24]** La numeración original colisionaba: **ADR 20 ya estaba ocupada** en `arquitectura.md` §6 (superficie de activación conversacional, sesión ManyChat del 2026-07-23). Todo se desplaza +1. Las referencias a "ADR 20" en §4.2 y §4.3 de este documento **sí apuntan a la ADR 20 existente** (la de activación conversacional) y son correctas tal cual.

> ⚠ **NOTA DE MOTOR (2026-08-05, ADR 31).** Este documento se escribió cuando el plano analítico era ClickHouse. **Ya no lo es: es PostgreSQL** (schemas `ingestion`/`search`/`signals`, misma base que el CRM). Donde el texto diga *«ClickHouse»*, léase *«el plano analítico»* — la separación de preocupaciones que este doc establece **sobrevive intacta**, porque era de dominio y no de motor. Tres consecuencias sí cambian de signo y están corregidas en línea abajo: la supresión dirigida deja de ser cara (§2.6), el `ORDER BY` deja de ser inmutable (§4, §5.2), y las tablas de primera parte llevan RLS igual que el CRM.

---

## 0. Encuadre — qué cambió hoy y por qué invalida parte del análisis en disco

`docs/fase0-zernio-mercado.md` §6.1 dictaminó **NO-GO** sobre la Fase 0 propuesta. Ese veredicto se apoyaba en tres razones independientes, y **dos de las tres eran razones sobre un producto que ya no es el que se propone**.

El propio documento nombra la distinción en §2.3:

- **Uso A** — embeber un agregador dentro de un SaaS vertical (un CRM que además publica). Ayrshare lo comercializa activamente y sus términos lo permiten.
- **Uso B** — revender una API de publicación a desarrolladores. Los términos de Ayrshare lo prohíben literalmente.

El NO-GO se apoyaba en **Uso B**. La aclaración del fundador nos sitúa en **Uso A**: las cuentas conectadas alimentan el CRM de Qualify, no se revende una API a terceros.

### 0.1 Conclusiones de `fase0-zernio-mercado.md` que **NO sobreviven** al cambio

| Conclusión | Por qué cae |
|---|---|
| §2.3 — "el motor (1) [venta a devs] queda inviable por los términos de Ayrshare" | No hay motor (1). Las cláusulas anti-reventa no aplican a Uso A. **Ayrshare y todo el set de agregadores vuelven a ser candidatos elegibles** (aunque §3 de este doc los descarta por otras razones) |
| §2.5 — márgenes negativos al revender | La aritmética asumía COGS por cuenta contra un **precio de reventa de $1–6/cuenta**. En Uso A el COGS por cuenta se compara contra el **precio de un asiento de CRM/listening** (categoría Buzzmonitor, órdenes de magnitud por encima). El cálculo de margen se rehace entero y deja de ser el argumento decisivo |
| §3 — "el MCP ya no diferencia" | Correcto pero irrelevante: el MCP no es el producto |
| §5.1 — "el plan gratuito de Metricool cubre a la PYME típica" | Es el techo de precio de **herramientas de publicación**. Metricool Free no hace listening multimodal de *earned media*; no fija el techo de la categoría en la que compite Qualify |
| §6.1 — veredicto NO-GO | **Vacado para el objetivo re-encuadrado.** Sigue vigente, sin cambios, para el producto original (API de publicación vendida a desarrolladores) |

### 0.2 Conclusiones que **sobreviven intactas** y siguen siendo vinculantes

| Conclusión | Por qué no cambia |
|---|---|
| §1.2 — App Review + Business Verification: **2–4 meses**, entidad legal con NIF/domicilio/web como requisito previo, resultado binario y rechazable | Es un trámite **del lado de la plataforma**. Es indiferente a qué construyas encima. **Sigue siendo la ruta crítica** |
| §2.4 — el agregador vende **su aprobación**, no código; el self-host no es un atajo | Argumento estructural, independiente del modelo de negocio |
| §4.1/§4.2 — OAuth no alcanza competidores ni creadores no afiliados; TikTok cierra el listening comercial; menciones IG excluyen Stories y menciones sin `@`; búsqueda por hashtag limitada a 30 hashtags únicos / 7 días | Define el **límite de cobertura del CRM**. Ahora importa *más*, no menos: es lo que nunca se puede prometer internamente ni en ventas |
| §6.2 Riesgo 1 — "consentimiento alquilado" bajo la vía comprada | **Sobrevive y empeora.** Ver §3.2 |
| Custodia multi-tenant de credenciales OAuth como preocupación de día uno | Sin cambios. Se custodian tokens de cuentas de negocio de los clientes de nuestros clientes desde el primer cliente |

### 0.3 El cambio conceptual que reordena todo lo demás

ADR 19 evaluó la vía OAuth como **sustituto** de la Fase 1: pausas el scraping y vendes publicación. Bajo ese encuadre, §4.2 tiene razón sin matices — OAuth da *owned media*, el producto de Qualify es *earned media*, luego OAuth no puede reemplazar a la Fase 1.

Bajo el re-encuadre, OAuth es un **complemento** de la Fase 1, no un sustituto:

- **Scraping (Fase 1)** = adquisición de terceros sin consentimiento → competidores, creadores no afiliados, conversación de categoría. Es el **carril outbound / de descubrimiento**.
- **API de plataforma con OAuth** = adquisición de primera parte con consentimiento → contenido propio del cliente, comentarios de su audiencia, menciones y etiquetas dirigidas a él. Es el **carril inbound / de engagement**.

Un CRM necesita los dos. La misma propiedad que hace inútil a OAuth para descubrimiento —sólo alcanza a quien te dio permiso— lo hace **exactamente lo correcto** para la mitad inbound: los que comentan y te mencionan son leads calientes que se identificaron solos. Ese conjunto es estrecho pero de altísima intención, y el scraping no lo produce con la misma calidad de consentimiento.

Esta es la razón por la que varias conclusiones de la investigación previa se invierten: no porque la evidencia fuera mala, sino porque evaluaba una relación de sustitución que ya no es la que hay sobre la mesa.

---

## 1. (A1) Ubicación en el mapa de fases y estatus de la precondición de ADR 19

### 1.1 Qué tipo de objeto es esto

No es una fase. Es una **segunda vía de adquisición hacia el mismo downstream**.

El pipeline de Fase 1 es, de forma abstracta: `adquirir → persistir raw verbatim (R2) → parsear a tipos → materializar hechos (ClickHouse) → indexar → detectar señales`. La vía OAuth cambia **sólo el primer paso**. Desde el envelope de raw-payload hacia abajo, produce el mismo tipo de filas: posts, comentarios, fragmentos de texto indexables, y más adelante señales tipadas.

Esto ya estaba anticipado en la nota de soporte de ADR 19: `shared.py` (`canonical_bytes`, `content_signature`, `RawPayloadEnvelope`, el seam `RawPayloadStore`, el versionado triaxial) *"generaliza de 'hydration scrapeado' a 'respuesta cruda de API de terceros'"*. La costura ya existe; lo que falta es declararla y versionarla (§2.4).

**Ruling:** la integración de cuentas conectadas se documenta como **Fase 1 Parte 4 — Ingesta de primera parte (API de plataforma)**, hermana de la Parte 2 (scraping) y **dependiente dura de la Parte 3** (§1.3). No se crea una "Fase 0" ni se reordena el mapa 1→6.

### 1.2 Reparto de las capacidades sobre el mapa de fases existente

Ninguna de estas capacidades es nueva en el mapa; lo que cambia es **de dónde llegan los datos**. Esto es deliberado: evita inventar fases y hace explícito qué scope pertenece a más adelante.

| Capacidad | Fase del mapa | Cambio que introduce la vía OAuth |
|---|---|---|
| **Capa de conexión y consentimiento** (OAuth, custodia de tokens, aislamiento multi-tenant, salud de conexión, webhooks) | **Fase 6** (`multi-tenant isolation`) | **Adelanto duro a día uno.** Es la única reversión real del mapa, y es la misma que ADR 19 ya identificaba como no diferible. No existe versión de esto con multi-tenancy pospuesta |
| Ingesta de media propio + comentarios + menciones/tags | **Fase 1** | Nueva Parte 4. Comparte el downstream de la Parte 3 |
| Ingesta de **insights** (serie temporal post × día × métrica) | **Fase 1 / Fase 2 frontera** | Tabla ClickHouse nueva (`ingestion.owned_metrics`). Es la primera tabla analítica con un caso de uso de producto inmediato |
| Reporting de sentiment/temas sobre el corpus de comentarios propios | **Fase 2** | Sin cambio de fase. Llega antes porque el corpus llega antes, y sin depender de que el scraping esté calibrado |
| Alertas de mención de marca propia (texto) | **Fase 3** | Sin cambio de fase; **alcance recortado**: sólo marca propia, sólo texto, sin Stories, sin menciones sin `@` |
| Señales tipadas con provenance sobre comentarios | **Fase 3** | Sin cambio. El corpus de entrada es de primera parte → provenance gana el eje "base legal de adquisición" (§2.4) |
| Comentaristas/mencionadores como candidatos de creator | **Fase 4** | Nuevo top-of-funnel **consentido** que el scraping no produce |
| **Publicación / scheduling en cuentas conectadas** | **Fase 5** (`activation: push`) | **Recomendación explícita: fuera de alcance del primer entregable.** Ver §1.4 |

### 1.3 La precondición de ADR 19: ¿sigue vinculando?

ADR 19 llevaba una condición dura: **completar Fase 1 Parte 3 antes de pausar**. La Parte 3 no ha empezado.

**Ruling: la precondición se disuelve en su forma y se endurece en su sustancia.**

- **Se disuelve en la forma.** La condición era un seguro contra un *pausado*. Su razón, textual en la nota de soporte, era que las Partes 1+2 *"no han producido todavía ningún dato aterrizado en ningún store, es decir, cero valor realizado"*, y la Parte 3 es el paso que convierte trabajo de valor-cero en valor demostrable. Bajo el re-encuadre **no se pausa nada**, luego no hay pausa que condicionar. La cláusula, leída literalmente, queda sin objeto.
- **Se endurece en la sustancia.** La Parte 3 *es* el downstream al que aterriza la ingesta de primera parte: R2 como raw store, `packages/shared`, las colas Celery, y el DDL de ClickHouse (`ingestion.*`, `search.content_index`). Construir la Parte 4 sin la Parte 3 produce **un segundo pipeline huérfano que tampoco aterriza en ningún sitio** — exactamente el modo de fallo contra el que la precondición aseguraba, ahora duplicado. Pasa de ser "lo que terminas antes de despedirte" a **ruta crítica del trabajo nuevo**.

**Matiz operativo, y es el que hace la regla accionable.** No todo bloquea por igual:

| Bloque de trabajo | ¿Bloqueado por la Parte 3? |
|---|---|
| Capa de conexión: OAuth, cifrado de tokens, refresh, máquina de estados de salud, tablas Postgres | **No.** Es plano transaccional puro. Puede construirse **en paralelo** desde hoy |
| Endpoint de intake de webhooks + verificación de firma | **No** (si el payload crudo aterriza en disco/R2 y se encola; sí necesita Redis, que es Parte 3 temprana) |
| Fetch de media/comentarios/menciones/insights y su materialización analítica | **Sí, duro.** Sin `ingestion.*` ni el raw store no hay dónde ponerlo |
| Sentiment/señales sobre comentarios propios | **Sí**, por transitividad |

### 1.4 Secuenciación recomendada — el hallazgo que resuelve el conflicto de calendario aparente

Los dos trabajos que parecen competir por el mismo tiempo **no compiten**, porque uno de ellos no consume capacidad de ingeniería.

La ruta crítica hacia GA no es código: es **constitución/verificación de entidad legal ante Meta + App Review + Business Verification: 2–4 meses** (`fase0-zernio-mercado.md` §1.2). Ese reloj corre solo. Por tanto:

1. **Semana 0 — arrancar el reloj administrativo.** Es tarea del fundador, coste de ingeniería cero, y **domina cualquier otra decisión de secuencia** (mismo razonamiento (2) de ADR 19, que sigue siendo correcto). Ítem cero real: si no hay sociedad constituida con NIF, domicilio y web activa coincidentes, ése es el bloqueo previo al bloqueo.
2. **En paralelo — Fase 1 Parte 3.** La ventana de 2–4 meses de espera administrativa es aproximadamente el tiempo que la Parte 3 necesita. El tiempo muerto del trámite se convierte en el tiempo de construir el downstream.
3. **En paralelo — capa de conexión (§2).** No bloqueada, y es el artefacto que hay que grabar en screencast para el propio App Review: Meta exige demo funcional del caso de uso. Construirla **no es trabajo especulativo, es un requisito del trámite**.
4. **Desarrollo y design partners no están bloqueados.** Bajo Standard Access el tope es de **25 usuarios de prueba** — suficiente para toda la fase de diseño y para los primeros clientes piloto. Lo que bloquea App Review es la GA, no el desarrollo.
5. **Parte 4 (ingesta de primera parte)** entra cuando la Parte 3 tiene `ingestion.*` y el raw store en pie.

### 1.5 Forma del registro: ADR nueva, no reescritura de ADR 19

**Ruling: ADR nueva (ADR 21 — renumerada desde "ADR 20", ver corrección de numeración en la cabecera), que re-encuadra el alcance de ADR 19 sin editarla.**

- El objeto de decisión de ADR 19 es un **producto** (API de publicación sobre agregador, vendida a devs/PYMES, con Fase 1 pausada). El objeto nuevo es una **capacidad dentro del producto existente**. Son decisiones distintas.
- Las ADRs no se reescriben, se superseden (Nygard). ADR 19 documenta un razonamiento válido sobre una propuesta que el fundador nunca aprobó; borrarlo destruye el registro y, sobre todo, **su análisis de riesgos sigue siendo el mejor que hay** sobre custodia de credenciales, exactly-once, techos de rate limit por app y deriva de adapters — todo eso se hereda, no se descarta.
- ADR 19 permanece **PROPUESTO**. Si el fundador confirma que no persigue el producto de publicación vendida a desarrolladores, pasa a **RETIRADA** — pero esa transición la firma él, no yo.

### 1.6 Alcance que se deja explícitamente fuera (flag anti-scope-creep)

Por la regla de `CLAUDE.md` de no colar scope de fases posteriores en silencio:

- **Publicación/scheduling (Fase 5): fuera.** Es la mitad que concentra todos los problemas duros de ADR 19 (exactly-once bajo fallo ambiguo, deriva de adapters, techos de rate limit compartidos) y ninguna diferenciación — `NOTES_fase0_agentive_layer.md` §2 lo demuestra con números: en el lado write **todo feature de IA es un wrapper fino** y la barrera de entrada es la fontanería, no la IA. La mitad de lectura es donde la tesis de Qualify tiene tracción. **Read-first, write-later:** leer es lo que hace a esto Qualify; publicar es lo que lo haría un clon de Zernio. El scope de publicación se re-abre como decisión de Fase 5 cuando haya señales que activar.
- **Smart replies / RAG (Fase 5): fuera** del primer entregable, aunque el corpus de comentarios lo habilita. Requiere el bucle de aprobación humana descrito en `NOTES_fase0_agentive_layer.md` §5.2 (layer 5) — que sí conviene diseñar desde el día uno como decisión de producto, aunque no se construya.
- **Billing por créditos (`billing.usage_events`, Fase 5): fuera.** No se mintea el esquema.
- **Otras plataformas (TikTok, LinkedIn, X): fuera.** TikTok, además, está estructuralmente cerrado para el eje de lectura comercial (§0.2).

---

## 2. (A2) Arquitectura de conexión de cuentas

> **Nota de verificación.** En el momento de escribir esto `reference/meta-instagram-platform/` **no existe todavía** (la cosecha de `pipeline` está en curso). Todo dato concreto de la API de Meta que aparece abajo va marcado **[V]** = *pendiente de verificar contra el corpus cosechado antes de escribir DDL o código*. La **arquitectura** no depende de esos detalles; el **dimensionado y algunos modos de fallo, sí**. No se inventan capacidades: donde no sé, lo digo.

### 2.1 Dónde vive cada cosa — y la tercera preocupación que el modelo de dos planos no cubre

`docs/arquitectura.md` §1.3/§2 define dos planos: **Postgres = verdad transaccional del CRM**, **ClickHouse = hechos analíticos inmutables**, que nunca se cruzan en escritura y se unen por `creator_id`. La integración de cuentas conectadas respeta esa separación y **añade una tercera preocupación que ninguno de los dos planos cubre: los secretos**.

| Preocupación | Plano | Contenido |
|---|---|---|
| Estado de la conexión (quién conectó qué, con qué scopes, salud, historial) | **Postgres** | `social_connections`, `connection_events` |
| **Material criptográfico** (access/refresh tokens de terceros) | **Postgres cifrado + KMS externo** | `oauth_credentials` (ciphertext), master key **nunca** en la base ni en el repo |
| Hechos observados (posts, comentarios, menciones, métricas) | **Postgres, schemas analíticos** *(ClickHouse cuando se escribió — ADR 31)* | `ingestion.*`, `search.content_index`, `signals.events` |
| Payload crudo verbatim de cada respuesta de la API | **R2** | `RawPayloadEnvelope` (ADR 18, extendido — §2.4) |
| Colas, locks de refresh, dedupe de webhooks, contadores de rate limit | **Redis** | efímero |

La regla de no-cruce se mantiene, pero cambia de naturaleza con ADR 31: el CRM escribe el schema `public`, los workers escriben los schemas analíticos y R2. **Antes era imposible cruzar (motores distintos); ahora es disciplina de módulo** — y la lectura sí puede hacer un `JOIN` real en vez de una reconciliación en aplicación. `connection_id` (UUID de Postgres) viaja como **columna de provenance** en ClickHouse — es un identificador, no una escritura cruzada.

### 2.2 Modelo de datos de la conexión (Postgres) — PROPUESTO

Módulo nuevo `connections` dentro del monolito modular (ADR 1). Cuatro tablas, y la separación entre las dos primeras es deliberada.

**`social_connections`** — una fila por (workspace, plataforma, cuenta externa).

```
id                  uuid pk
tenant_id        uuid not null          -- tenant. Índice y RLS-scope de TODA consulta
brand_id            uuid                   -- puede ser null: una workspace puede tener N marcas
platform            text not null          -- 'instagram' | 'facebook_page' | ...
account_type        text not null          -- 'business' | 'creator'
external_account_id text not null          -- ig_user_id
external_username   text
linked_page_id      text                   -- Página de FB vinculada, si la vía de login la exige [V]
granted_scopes      text[] not null
status              text not null          -- máquina de estados, §2.3
current_credential_version int not null
connected_by_user_id uuid not null
connected_at        timestamptz not null
last_verified_at    timestamptz
disconnected_at     timestamptz
unique (tenant_id, platform, external_account_id)
```

`unique (tenant_id, platform, external_account_id)` es la clave natural de idempotencia de la conexión — el análogo de `(brand_id, platform, post_id)` en el plano analítico. Reconectar la misma cuenta actualiza la fila, no crea una segunda.

**`oauth_credentials`** — tabla aparte, **append-only, versionada**.

```
id                  uuid pk
connection_id       uuid not null fk
version             int not null           -- monotónico por connection_id
token_type          text not null          -- 'long_lived_user' | 'page' | ... [V]
ciphertext          bytea not null
key_id              text not null          -- qué DEK/master key cifró esto → rotación sin re-cifrar todo
issued_at           timestamptz not null
expires_at          timestamptz
created_at          timestamptz not null
unique (connection_id, version)
```

**Por qué tabla separada y no columnas en `social_connections`:** (1) el perfil de control de acceso es distinto — la UI del CRM lee `social_connections` constantemente y **nunca** debe tocar `oauth_credentials`; (2) el ciclo de vida es distinto (una conexión vive meses, sus credenciales rotan cada 60 días [V]); (3) permite el patrón append-only del §2.3, que es lo que hace segura la rotación.

**Por qué append-only con puntero:** el refresh **nunca muta la fila existente**. Escribe `version+1` y después actualiza `social_connections.current_credential_version` en la misma transacción. Consecuencia: **un refresh fallido o parcial no destruye el token que funcionaba**. Esto es la regla de provenance de `CLAUDE.md` aplicada a credenciales — nada derivado se sobrescribe, se versiona.

**`connection_events`** — auditoría append-only: `granted | refreshed | refresh_failed | scope_changed | degraded | revoked | reconnected`, con `connection_id`, `credential_version`, `actor` (usuario o `system`), `platform_error_code`, `raw_response_r2_key`, `occurred_at`. Es el equivalente de provenance para efectos sobre credenciales, y es lo que permite responder "¿por qué se desconectó este cliente?" sin adivinar.

**`platform_apps`** — nuestras registraciones de app (`app_id`, referencia al secreto, `api_version` de Graph, `config_version`). Existe para que la versión de la API de Graph sea **dato, no constante hardcodeada**: Meta deprecia versiones con calendario, y el `api_version` con el que se obtuvo un payload es provenance (§2.4).

**Custodia de la master key — PROPUESTO, decisión pendiente.** Envelope encryption: DEK por tenant, envuelta por una master key que vive **fuera de Postgres**. Recomendación pragmática para el estado actual del proyecto (VPS Hetzner, fundador en solitario): master key inyectada por el entorno de ejecución, `key_id` en cada fila para permitir rotación incremental, y **diferir un KMS/Vault real hasta que exista un requisito de compliance que lo exija**. La columna `key_id` es lo que mantiene esa puerta abierta sin coste hoy. **[Actualización 2026-07-24, A5-2 CERRADO:** con el Business Portfolio en propiedad del fundador (su propia entidad), la rotación por `key_id` deja de estar **forzada por incertidumbre de propiedad** — se conserva como buena práctica de rotación, no como hedge. La custodia se diseña sin cautividad de vendor/partner.**]** **No decido esto unilateralmente** — es una decisión de riesgo de negocio (una brecha aquí es un incidente reportable que involucra a los clientes *de nuestros clientes*), y va a §4 como pregunta abierta.

### 2.3 Ciclo de vida del token y salud de la conexión

**Máquina de estados** (`social_connections.status`):

```
pending ──grant OK──> active ──401/190──> degraded ──verificación falla──> revoked
                        ^                    │                               │
                        └──verificación OK───┘                               │
                        └───────────────── reconnect (nuevo grant) ──────────┘
```

- **`degraded` no es un estado cosmético**: es el que separa "fallo transitorio de red" de "el cliente revocó el permiso desde la app de Instagram". Sin él, un 401 puntual desconecta a un cliente que no hizo nada.
- Cada transición emite un **evento de dominio** (`connection.degraded`, `connection.revoked`) por el contrato de ADR 6, que el módulo de notificaciones consume para pedir reconexión. La revocación silenciosa —nos enteramos por un 401— es un driver de carga de soporte, no una nota al pie: ADR 19 ya lo identificó y sigue vigente.
- `last_verified_at` lo actualiza un chequeo barato periódico. **Una conexión sin verificar no es una conexión sana**, es una conexión sobre la que no sabemos nada.

**Refresh — el problema de la carrera.** [V] Los tokens de larga duración de Instagram caducan a ~60 días y se refrescan sobre sí mismos; dos refrescos concurrentes pueden invalidar el token y desconectar al cliente en silencio.

Diseño:
1. Celery Beat escanea `oauth_credentials` con `expires_at` dentro de una ventana (recomendado: refrescar al ~75% de vida, no al 95% — deja margen para reintentos antes del acantilado).
2. Antes de refrescar, **lock distribuido en Redis por `connection_id`** con TTL corto. Un solo refresh en vuelo por conexión, siempre.
3. Éxito → `INSERT version+1` + `UPDATE current_credential_version` en una transacción.
4. Fallo → `connection_events(refresh_failed)` + backoff. Tras N fallos → `degraded`.
5. **Nunca se borra la versión anterior inmediatamente.** Retención corta (p. ej. las 2 últimas versiones) para poder diagnosticar; purga por job.

**El token nunca sale de la capa de acceso.** Regla dura: los workers piden a un `CredentialResolver` un cliente HTTP ya autenticado, no un token. Consecuencia directa y no negociable: **el `access_token` jamás aparece en logs, ni en la clave de R2, ni dentro del `RawPayloadEnvelope`** (§2.4). Un token filtrado en un payload crudo archivado es una fuga persistente.

### 2.4 Provenance de primera parte — extensión de ADR 18

La ingesta de primera parte reutiliza el envelope de ADR 18, y ese reuso obliga a **tres cambios que no son cosméticos**. Los tres pertenecen a `packages/scraper/src/qualify_scraper/shared.py`, que **no es mío**: la decisión es mía, la implementación es de `pipeline`.

**(a) `payload_schema_version = 2`.** ADR 18 ya establece que `payload_schema_version` gobierna la forma del envelope y el algoritmo de firma, y que es un eje independiente precisamente para esto. Cambios de la v2:

- Nuevo campo `source_class: 'scrape' | 'first_party_api'`. Sin él, un payload archivado no dice **cómo se obtuvo**, y de eso dependen obligaciones legales distintas (§2.4c).
- `zyte_request_meta` → **`transport_meta`**. El nombre actual es vendor-específico; una respuesta de Graph API no tiene metadata de Zyte. Es renombrado, no rediseño: el contenido sigue siendo metadata brand-agnóstica del transporte (request id, coste, timing, y para Meta: `api_version` y las cabeceras de rate limit del §2.7).
- `source_url` para primera parte = la URL de la petición a Graph API **con el `access_token` y cualquier parámetro de credencial eliminados**. Se firma y se archiva la petición, no la credencial.

**(b) Inversión del keying de ADR 18 — y es la parte con riesgo de seguridad.** ADR 18 fija `raw_payload_key(platform, url)` **brand-agnóstico**, con el razonamiento explícito de que *"N marcas comparten un scrape"* (ahorro de coste Zyte). Ese razonamiento **se invierte** para primera parte: una respuesta de Graph API contiene analytics privados y comentarios de la cuenta de un cliente concreto y **jamás es compartible entre tenants**. La nota de soporte de ADR 19 ya lo anticipó; aquí queda decidido.

> **Regla:** para `source_class='first_party_api'` la clave de almacenamiento **debe** llevar `tenant_id` en el prefijo. El núcleo de ADR 18 (envelope autodescriptivo, firma sobre el payload íntegro, versionado triaxial) sobrevive; su *rationale* de keying no. Colapsar ambos casos en una sola función de clave es una fuga cross-tenant, no una optimización.

**(c) La provenance gana un eje: la base legal de adquisición.** Toda señal derivada de este corpus lleva, además de lo que ya exige `CLAUDE.md` (`post_id`/`comment_id` fuente + `detector_version`/`pipeline_version` + `model_id`/`revision` + `label_set_version` por ADR 16):

- `source_class` — cómo se adquirió el dato de origen.
- `connection_id` — **bajo qué consentimiento concreto**.

Razón: un dato adquirido por consentimiento es **revocable por quien lo concedió**. Cuando una conexión pasa a `revoked`, o el tenant ejerce supresión (GDPR), hay que poder localizar toda fila derivada de esa conexión. Sin `connection_id` como columna de provenance eso es imposible de responder, y la respuesta "no sabemos qué borrar" no es aceptable. Esto **generaliza** la regla de `CLAUDE.md`, no la contradice: *toda señal derivada lleva su origen técnico **y** su base de adquisición*.

~~**Consecuencia operativa que hay que aceptar de frente:** ClickHouse es append-only por diseño y el borrado dirigido es una mutación cara…~~ → **RETIRADA POR ADR 31 (2026-08-05), y en la dirección buena.** En Postgres la supresión dirigida es un `DELETE ... WHERE tenant_id = ?` sobre una tabla con RLS, más `ON DELETE CASCADE` hacia las hijas: **deja de ser una mutación cara que había que acotar con particionado y pasa a ser una operación ordinaria.** Esto importa más de lo que parece porque la supresión aquí **no es una optimización, es una obligación** (ADR 22(2)): el argumento que sostenía el prefijo de tenant en la clave de R2 era precisamente que borrar tenía que ser barato. Sigue siéndolo en R2 (borrado por prefijo) y ahora también en el plano analítico. Lo que sí queda pendiente y no lo resuelve el motor: **decidir y documentar el alcance exacto de una supresión** (qué se borra, qué se conserva anonimizado, y qué pasa con el raw en R2 del que se puede reconstruir).

### 2.5 Mapeo: superficie de lectura → entidad de Qualify

La columna que importa es la última: **qué es realmente cada superficie**. Confundir *owned* con *earned* es el error que llevaría a sobrevender la cobertura del CRM internamente.

| Superficie IG [V] | Naturaleza | Destino | Plano |
|---|---|---|---|
| **Media propio** (`/{ig-user-id}/media`) | Contenido **propio** del cliente | `ingestion.posts` con `source_class='first_party_api'` + `connection_id` — **misma tabla que el scraping**, no una paralela | CH |
| **Insights** de cuenta y de media (`/insights`) | Serie temporal **propia** | **`ingestion.owned_metrics`** — tabla nueva (post × día × métrica). Único shape genuinamente nuevo | CH |
| **Comentarios en media propio** (`/{ig-media-id}/comments`) | **Voz de audiencia de terceros** sobre contenido propio | `ingestion.comments` + `search.content_index` + (Fase 3) `signals.events` | CH |
| **`mentioned_media` / `mentioned_comment`** | **Earned media genuino** — contenido de terceros sobre el cliente | El *media* es un post de tercero → `ingestion.posts`. La *mención* es el hecho derivado → `signals.events` con `signal_type='brand_mention'` (ADR 16) | CH |
| **`tags`** (`/{ig-user-id}/tags`) | Earned media | Idéntico a `mentioned_media` | CH |
| **Autor de comentario / mención** | **Persona** | Candidato a `crm.creators` (Fase 4) + contacto CRM en Postgres | PG + CH |
| **La cuenta conectada en sí** | El cliente | **No** es un `crm.creators`. Es workspace/marca en Postgres | PG |
| **Webhooks** (`comments`, `mentions`, `messages`, `live_comments`) [V] | Notificación, **no dato** | Intake → cola → fetch (§2.6) | Redis → R2 → CH |
| **Publicación** (`/media` → `/media_publish`) | **Efecto externo** | `publish_attempts` en Postgres, con `idempotency_key` + respuesta cruda + `connection_id` + `adapter_version` | PG (**fuera de alcance**, §1.6) |

**Tres decisiones de modelado que quedan explícitas:**

1. **Un post es un post, venga de donde venga.** No se crea una familia de tablas `owned_*` paralela a `ingestion.*`. Un post adquirido por API y uno scrapeado son el mismo hecho con distinta procedencia, y `source_class` es exactamente la columna que registra esa diferencia. Duplicar el árbol de tablas duplicaría también `search.content_index` y todo lo que lo consume — coste permanente a cambio de nada.
2. **La mención es una señal, no una tabla.** El media mencionado es un post de tercero (hecho); que mencione a nuestro cliente es una observación derivada con provenance (señal). Modelarlo como `signals.events` lo hace consistente con ADR 16 y evita una tabla `mentions` que se solaparía con `posts` en el 90% de sus columnas.
3. **El comentarista es el activo de CRM, no el cliente.** El valor del carril inbound son las personas que se identificaron solas al comentar o mencionar. Ése es el punto de composición real con la Fase 4 (`crm.creators`), y es un top-of-funnel **consentido** que el scraping no produce con la misma calidad.

### 2.6 Intake de webhooks

**Principio rector: el webhook es una notificación, no un dato.** Meta entrega identificadores y un cambio; el objeto hay que ir a buscarlo. El endpoint de intake hace **lo mínimo posible** y devuelve 200 rápido — Meta reintenta ante no-2xx o lentitud, y un intake lento se convierte en reentregas duplicadas.

Flujo:

1. `POST /webhooks/meta` (FastAPI). **Verificar `X-Hub-Signature-256`** (HMAC-SHA256 del cuerpo crudo con el app secret) [V] **antes de parsear nada**. Firma inválida → 403 y descarte. Un webhook no verificado es entrada no confiable de internet.
2. Persistir la notificación cruda (envelope v2, `source_class='first_party_api'`) y encolar. **No** hacer llamadas a Graph API dentro del handler.
3. Deduplicar: Meta no garantiza entrega exactly-once. Clave de dedupe = hash de `(tenant_id, platform, object_id, field, change_time)`. Redis `SETNX` con TTL como filtro barato + `ReplacingMergeTree` aguas abajo como garantía durable. **Dos capas porque Redis puede perder estado y ClickHouse no.**
4. Worker de fetch: resuelve `connection_id` desde el objeto notificado, obtiene cliente autenticado del `CredentialResolver`, llama a Graph API, persiste el envelope de la respuesta, encola aguas abajo.
5. Aguas abajo **no cambia**: `comment_jobs` e `index_jobs` de la Parte 3 sirven igual. Colas nuevas: sólo `fp_intake_jobs` y `fp_fetch_jobs`.

**Regla de fiabilidad: ningún hecho debe tener el webhook como único camino.** Los webhooks se pierden, la app puede estar caída durante una ventana de reintentos, y una suscripción puede quedar desactivada por Meta tras fallos repetidos. Cada superficie lleva además un **poll periódico de reconciliación** por conexión (Celery Beat): el webhook da latencia, el poll da completitud.

> **Excepción que hay que verificar antes de nada — y tiene consecuencia de diseño dura.** [V] Existe la posibilidad de que `mentioned_media` **no sea enumerable**: que requiera un `media_id` obtenido previamente del webhook de `mentions`, en lugar de poder listarse. Si se confirma, **las menciones son la única superficie donde el webhook es el único camino de descubrimiento**, y una entrega perdida es una mención perdida para siempre — sin backfill posible. Eso convierte la fiabilidad del intake de webhooks de "buena práctica" en **requisito de corrección del producto**, y obliga a: reintentos agresivos, monitorización de la salud de la suscripción como métrica de primera clase, y una advertencia honesta al cliente sobre la completitud del feed de menciones. **Primera cosa a resolver contra `reference/meta-instagram-platform/` cuando la cosecha aterrice.** Si resulta enumerable, el poll de reconciliación cubre el hueco y esto se degrada a nota al pie.

### 2.7 Rate limits — un techo compartido entre tenants

ADR 19 lo listó como problema duro #4 y sigue vigente sin cambios: los límites de Meta son **por app** *y* por usuario. El techo por app es un recurso escaso **compartido entre todos nuestros tenants**: un tenant ruidoso degrada a los demás, y nuestro propio crecimiento degrada a los clientes existentes.

Diseño mínimo, y **debe existir antes de tener muchos tenants, no después**:

- Parsear la cabecera de uso por caso de negocio (`X-Business-Use-Case-Usage` [V]) en **cada** respuesta, y persistir la utilización por conexión. Meta publica el porcentaje consumido y el tiempo estimado hasta recuperar acceso; ignorarlo es volar a ciegas contra un techo compartido.
- Token bucket **por tenant** en Redis delante del scheduler de fetch, con cuota por workspace. Fair-share, no first-come.
- Circuit breaker global: al superar un umbral de utilización de app, degradar la frecuencia de polls antes de que la plataforma nos corte. **Preferir perder frescura a perder acceso.**
- Esta metadata entra en `transport_meta` del envelope (§2.4a) → el coste y la presión de rate limit por conexión quedan auditables, igual que el coste de Zyte por scrape.

### 2.8 La frontera de cobertura — lo que OAuth estructuralmente NO alcanza

Se escribe aquí para que **nunca** se sobrevenda internamente ni en producto. Ninguna de estas líneas se resuelve escalando, pagando o insistiendo; son propiedades del diseño de las plataformas (`fase0-zernio-mercado.md` §4.1/§4.2, verificado 2026-07-21).

| Capacidad | ¿Alcanzable por OAuth? |
|---|---|
| Sentiment/temas sobre comentarios de la marca propia | ✅ Sí, de inmediato |
| Insights de la cuenta y del contenido propio | ✅ Sí |
| Menciones y etiquetas dirigidas a la marca propia (texto/`@`) | ✅ Parcial — **sin Stories, sin menciones sin `@`** |
| Menciones **dentro de vídeo o audio** (visual listening) | ❌ No — exige el pipeline multimodal de la Fase 1 |
| Monitorización de **competidores** | ❌ **No, estructuralmente.** Un cliente no puede dar OAuth sobre la cuenta de un competidor |
| Discovery/scoring de **creadores no afiliados** | ❌ **No, estructuralmente** — es el núcleo de la Fase 4 y exige scraping |
| Share of voice, mapa de conversación de categoría | ❌ No |
| Cualquier listening comercial sobre **TikTok** | ❌ **No.** El Display API no consulta cuentas arbitrarias y el Research API rechaza usos comerciales |
| Búsqueda por hashtag | ⚠️ Muy limitada — **30 hashtags únicos por usuario en ventana de 7 días** |

**Consecuencia estratégica, dicha sin suavizar: esto no reemplaza a la Fase 1, la complementa.** El CRM que sale de las cuentas conectadas es real y vendible, pero cubre exclusivamente la mitad inbound. La mitad que contiene la tesis competitiva de Qualify —leer el contenido ajeno, descubrir creadores, medir la conversación de categoría— sigue requiriendo el pipeline de scraping, sin atajo. Cualquier material de producto que insinúe monitorización de competidores a partir de cuentas conectadas es falso.

---

## 3. (A5) La asimetría de cliente cero: Meta vs TikTok

**Estado:** RESUELTO sobre fuente primaria. Verificado por `architect-r` el **2026-07-24** mediante fetch en vivo de la documentación oficial de Meta y de TikTok. Las citas de esta sección son literales de la doc del fabricante, no de blogs de agregadores.

**Pregunta:** el fundador es **cliente cero** y publica en cuentas **que él mismo administra**. Toda la investigación en disco (`fase0-zernio-mercado.md` §1.1/§1.2) costeó únicamente el caso de **publicar en nombre de clientes terceros**. ¿Cambia eso el calendario de 2–4 meses?

**Respuesta corta: sí, en Meta se disuelve por completo; en TikTok empeora respecto de lo que teníamos escrito.**

### 3.1 Meta — el reloj administrativo NO bloquea a cliente cero

Tres afirmaciones de fuente primaria encadenadas cierran la cuestión:

| # | Afirmación literal | Fuente [P], accedida 2026-07-24 |
|---|---|---|
| 1 | *"Los permisos con acceso estándar solo se pueden solicitar a usuarios de la app que tengan **un rol en la app solicitante**"* — y — *"se **aprueba automáticamente** el acceso estándar para todos los permisos y las funciones"* | [Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels) |
| 2 | *"Apps in **Development mode** can only request permissions from **role users**, and only permissions with standard or advanced access levels."* | [App Modes](https://developers.facebook.com/docs/development/build-and-test/app-modes) |
| 3 | *"**If your app will only be used by app users who have a role on the app itself you do not need to complete verification.**"* | [Business Verification](https://developers.facebook.com/docs/development/release/business-verification) |

Encadenadas: si el único usuario de la app es alguien con **rol en la app** (admin/developer/tester), entonces (2) la app puede quedarse en **Development Mode**, (1) el acceso estándar a los permisos se concede **automáticamente, sin App Review**, y (3) **no hace falta Business Verification**.

El fundador cumple la condición por partida doble: es admin de la app *y* administrador de la cuenta profesional de Instagram de la tienda. **No hay trámite. No hay reloj. No hay entidad legal en la ruta crítica de cliente cero.**

> **CORRECCIÓN 2026-07-29 (architect, vía ADR 29 — `arquitectura.md` §6, enmienda del 2026-07-29). La cadena de arriba está INCOMPLETA: la cita 1 es una DISYUNCIÓN de dos términos y aquí sólo consta el primero.** La redacción real de Meta, en dos ficheros del corpus cosechado el 2026-07-24 y no leídos hasta hoy — `documentation/resp-plat-initiatives/individual-processes/app-review.md:7` y `documentation/instagram-platform/overview.md:107` — es: *"if your app will be used by anyone without a **Role on the app** **or a role in a Business that has claimed the app**"*. **Segundo término: un rol en un Business que ha *reclamado* la app.** No cambia nada del razonamiento de cliente cero (el fundador cumple el primer término), pero **abarata la variante de dar acceso a personas del cliente uno**: no exige una fila por persona en la consola de desarrollador, sino gestión de personas en Business Settings. Sigue descartada para GA por una razón peor que la escala — un rol en el Business Portfolio de Qualify concede acceso a los **activos** de ese portfolio, no sólo a la app. **Pendiente V-TP-1: precondiciones del *claim* de una app por un portfolio; si exigiese Business Verification, el segundo término colapsa sobre el trámite que evita.**
>
> **Y el HECHO NUEVO que reencuadra §3.7 y §6.5: el fundador es además el constructor y administrador del SaaS inmobiliario del cliente uno** (aportado por él el 2026-07-29). El cliente uno **no es de brazo extendido**. Consecuencia sobre §424 más abajo: la frontera no separa *cliente cero / cliente uno*, separa **activos que el fundador administra / activos que no** — y el primero del lado caro es el **cliente dos**. Detalle completo, veredictos sobre las variantes de app-por-tenant y el ruling de que `platform_apps` sigue global: **ADR 29**.

Y lo que se publica es contenido **real y público**. Es el punto que decide toda la sección: en la doc de [Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing) **no existe ningún mecanismo por el que el nivel de acceso o el estado de revisión degraden la visibilidad del post**. No es que no lo hayamos encontrado: es que Meta no tiene esa palanca. ~~Un reel publicado por una app en Development Mode es un reel público normal.~~

> ⚠ **LA ÚLTIMA FRASE QUEDA RETIRADA — 2026-07-29 (architect; error mío). Está CONTESTADA por doble fuente primaria, y es la premisa sobre la que se apoya ADR 21.** Ruling completo en `arquitectura.md` §6, enmienda del 2026-07-29 apartado **(i.2)**.
>
> - [P] Meta, [App Modes](https://developers.facebook.com/docs/development/build-and-test/app-modes), accedido 2026-07-29: *"Any data generated while an app is in Development mode, such as test posts, **can only be seen by role users**"* / *"…**will become visible to all app users once you switch**"*.
> - [P] campo independiente, [docs.postiz.com/providers/facebook](https://docs.postiz.com/providers/facebook) paso 8, accedido 2026-07-29: *"If you do not do this then posts made via the API will display for yourself but **will not be visible for other users**"* / *"**posts with media are only visible to app developers/testers** — everyone else sees the post without the image"*. (Ambas aportadas por `gtm-specialist` en `docs/research-modelo-acceso-tech-provider.md` §7.2.)
>
> **La primera mitad del párrafo SIGUE EN PIE:** sobre el eje **nivel de acceso** (Standard/Advanced) no hay degradación de visibilidad, y §1.1-bis de `fase0-zernio-mercado.md` no se toca. **El error fue de eje**: concluí *"Meta no tiene esa palanca"* al no encontrarla en la doc de **Content Publishing**, cuando vive en la de **App Modes** — que es un eje distinto y sí degrada, y degrada **la media**, justo lo que publica la Parte 4-A.
>
> **Consecuencia de ruta crítica: para publicar un reel público real la app tiene que estar en LIVE MODE**, luego *"Development Mode y no hay trámite"* deja de ser funcionalmente suficiente para publicar — el límite que §7.6 declaró de forma inespecífica, ahora con mecanismo y nombre. **La pregunta que decide ADR 21 pasa a ser: ¿pasar a Live Mode exige App Review y/o Business Verification, o es un toggle self-serve?** Si exigiera Business Verification, el reloj **sí** bloquea a cliente cero y el ruling central de esta sección se cae.
>
> **Calibración: contestada, no refutada** — la carga de la prueba se ha invertido y ya no se puede apoyar ADR 21 en ella sin prueba empírica. **V-TP-2 (A5-5) queda promovida a BLOQUEANTE.**

Capacidades confirmadas en esa misma doc para lo que el fundador pidió textualmente:

| Lo que pidió | Estado verificado |
|---|---|
| Publicar **reels** | ✅ `POST /{ig-user-id}/media` → `/media_publish` |
| Publicar **stories** | ✅ `media_type=STORIES`. Aviso operativo: al releer el objeto, `media_type` devuelve `IMAGE`/`VIDEO`; hay que consultar **`media_product_type`** para confirmar que es story. Esto es una trampa de parseo — anotarla en el mapeo de §2.5 |
| Volumen | ✅ **100 posts publicados por API en ventana móvil de 24 h** (50 si son carruseles). Órdenes de magnitud por encima de la necesidad de una tienda |
| **Atender DMs** | ✅ `instagram_business_manage_messages` |
| Moderar/responder comentarios | ✅ `instagram_business_manage_comments` |

Además, y es relevante para el coste de la capa de conexión de §2: la ruta **Instagram API with Instagram Login** *"does not require a Facebook Page to be linked to the Instagram professional account"*. Elimina la dependencia de Página de Facebook que `fase0-zernio-mercado.md` §1.1 daba por obligatoria.

#### Corrección a documentos en disco (dos, y una es mía)

1. **`fase0-zernio-mercado.md` §1.1, fila Instagram: "el tope es 25 usuarios de prueba" no está respaldado por fuente primaria.** La doc de Access Levels **no menciona ningún límite numérico**. El límite real es cualitativo — *tener un rol en la app* — no un cupo de 25. La cifra es probablemente un arrastre de la documentación antigua de Meta. Marcar como **[S] no verificado**.
2. **`docs/integracion-cuentas-conectadas-meta.md` §1.4, punto 4 — mío — repite el mismo "tope de 25 usuarios de prueba".** Queda corregido por esta sección. El razonamiento de §1.4 no cambia (desarrollo y pilotos no están bloqueados); cambia el motivo, y el motivo correcto es **más favorable**, no menos.

### 3.2 TikTok — peor de lo que teníamos escrito, y el matiz omitido es el que decide

`fase0-zernio-mercado.md` §1.1 registró que un cliente no auditado publica todo en `SELF_ONLY`. Es correcto pero **incompleto**, y lo omitido es exactamente lo que hace inviable el caso de cliente cero. Literal de [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines):

> *"Unaudited API Clients can only post contents in `SELF_ONLY` viewership."*
>
> *"Unaudited API Clients can allow up to 5 users to post in a 24 hour window. **All user accounts using the API client to post must be set to private at the time of posting.**"*

La segunda frase no estaba recogida en ningún documento del repo. No es que el *post* salga privado: **la cuenta entera tiene que estar en privado en el momento de publicar**. Para una cuenta de tienda eso significa apagar el escaparate para poder publicar en él. Es peor que "no funciona": es destructivo.

**Ruling: la publicación en TikTok vía API está cerrada para cliente cero hasta pasar auditoría, y no admite mitigación de ingeniería.** La restricción se aplica *"regardless of account ownership"* — administrar la cuenta uno mismo no la levanta. Ésta es precisamente la simetría que la hipótesis del lead planteaba como incierta: no la hay.

**Distinción que hay que preservar para no sobre-corregir:** lo bloqueado es **TikTok vía API**, no TikTok como canal. El fundador puede publicar a mano en TikTok hoy mismo. Lo que no puede es que Qualify lo haga por él. Cualquier roadmap debe decir "publicación programada en TikTok" y no "TikTok", porque la diferencia es lo que se le promete al cliente cero.

### 3.3 La asimetría, formulada

| | Meta (IG) | TikTok |
|---|---|---|
| ¿Bloquea a **cliente cero** (cuentas propias)? | **No.** Development Mode + acceso estándar | **Sí.** `SELF_ONLY` + cuenta forzada a privada |
| ¿Bloquea la **venta a terceros**? | **Sí.** Advanced Access → App Review + Business Verification | **Sí.** Auditoría del cliente API |
| ¿La cuenta propia levanta la restricción? | Sí, es el mecanismo exacto | **No.** Explícitamente independiente de la propiedad |
| Naturaleza del gate | **Administrativo**, corre en paralelo, coste de ingeniería cero | **Administrativo**, pero además **degrada el producto** mientras corre |

La asimetría **se confirma**, y con una consecuencia más fuerte que la hipótesis original: no es sólo que Meta sea más rápido. Es que **Meta tiene una modalidad de uso legítima, soportada y sin trámite para exactamente el caso de cliente cero, y TikTok no tiene ninguna**.

### 3.4 Re-ruling de A1: "read-first, write-later" — qué sobrevive y qué no

A1 dictaminó: *"Read-first, write-later: leer es lo que hace a esto Qualify; publicar es lo que lo haría un clon de Zernio"*, con publicación/scheduling y smart replies fuera de alcance hasta Fase 5. El fundador ha declarado desde entonces una prioridad que es exactamente la contraria. No se rubrica sin re-derivar.

**Ruling: A1 §1.6 queda ENMENDADO, no revocado. El eje era incorrecto.**

La razón no es que el fundador mande. Es que la regla estaba formulada sobre un eje —*leer vs. escribir*— que resulta no ser el eje que separa lo diferenciado de lo commodity. El eje verdadero es **media propia (owned) vs. media ajena (earned)**, y A1 asumió implícitamente earned porque toda la tesis de scraping vive ahí.

Desglosado, qué se cae y qué aguanta:

**(a) Lo que se cae: el argumento de "publicar es fontanería dura, luego Fase 5".**

Ese argumento heredaba de ADR 19 tres problemas reales: exactly-once bajo fallo ambiguo, deriva de adapters, y techos de rate limit compartidos entre tenants. **Los tres son problemas de multi-tenant y multi-plataforma.** Con N=1 tenant, 1 plataforma y 1 cuenta:

| Problema de ADR 19 | ¿Vincula a cliente cero? |
|---|---|
| Techo de rate limit compartido entre tenants | **No.** No hay otros tenants, y el techo es 100 posts/24 h contra una tienda que publica 1–3/día |
| Deriva de adapters sobre 15 plataformas | **No.** Un adapter, el de Meta |
| Exactly-once bajo fallo ambiguo | **Atenuado, no eliminado.** El radio de daño es un reel duplicado en una cuenta que el propio operador ve y borra. Eso es una molestia, no un incidente de confianza con un cliente |

El razonamiento de ADR 19 era **correcto sobre el producto que ADR 19 evaluaba** (un agregador vendido a terceros). No transfiere al caso mono-tenant sobre cuenta propia. Mantenerlo aquí sería aplicar el precio de un problema que no tenemos.

**(b) Lo que aguanta intacto, y es lo importante: construir lo diferenciado, envolver fino lo commodity.**

Esa regla sobrevive entera — sólo que ahora se aplica **dentro** del lado write, y lo parte en dos mitades de valor muy distinto:

- **Publicar reels/stories es commodity.** Sigue siendo verdad que ahí no hay ninguna diferenciación y que todo feature de IA es un wrapper fino (`NOTES_fase0_agentive_layer.md` §2). Se construye **delgado y aburrido**, sin ambición arquitectónica. No es el producto; es infraestructura para poder operar.
- **"Todos los canales de DM atendidos" NO es commodity, y no es propiamente el lado write.** Atender un canal es un bucle: llega un mensaje o comentario (**leer**) → se clasifica por intención/sentimiento/urgencia (**aquí está todo el valor de IA**) → se responde (**escribir**). La mitad que decide si esto sirve es la de clasificación y triaje, que es literalmente la tesis de Qualify aplicada a media propia.

Y de ahí sale la observación que reconcilia el conflicto aparente: **leer y escribir no son fases distintas en media propia, son el mismo bucle.** Partirlo entre Fase 1 y Fase 5/6 es lo que hacía que el mapa de fases pareciera contradecir al fundador. No le contradecía: estaba trazado para otro producto.

**(c) "Publicar lo haría un clon de Zernio" — dónde estaba bien y dónde estaba mal.**

Era una afirmación sobre **entrar en un mercado**, no sobre escribir código de publicación. Construir una ruta de publicación para un operador cuyas cuentas administras no es entrar en el mercado de Zernio; es dogfooding. El riesgo de clon reaparece en el instante en que **un tercero conecta su cuenta**.

Y ese instante tiene una frontera técnica exacta, que es la aportación útil de esta sección:

> **La línea Development Mode / Advanced Access es simultáneamente la frontera técnica, la frontera legal y la frontera estratégica.** Mientras todos los usuarios tengan un rol en la app: sin trámite, sin verificación de entidad, y no estamos en el mercado de Zernio. En cuanto uno no lo tenga: App Review + Business Verification + el reloj de 2–4 meses, y la pregunta "¿somos un clon de Zernio?" vuelve a estar viva y hay que responderla.

Que las tres fronteras coincidan es una propiedad valiosa: da **un único disparador observable** para re-abrir la decisión, en vez de un juicio subjetivo sobre cuándo hemos derivado demasiado.

**(d) Smart replies: enmienda concreta, no reversión.**

A1 las dejó fuera. Se corrige a: **respuestas asistidas con aprobación humana, DENTRO de alcance; respuestas autónomas, FUERA.** ~~El fundamento es numérico y ya estaba en disco: `NOTES_manychat_activation_layer.md` §2.2 mide precisión ≈65 % en tasas base de media propia (π≈10 %), frente al 7,9 % de media ajena. 65 % significa que **1 de cada 3 borradores está mal**~~ **[FUNDAMENTO SUSTITUIDO 2026-07-31 — `arquitectura.md` §6 enmienda (m). El 65 % no se midió: es una precisión bayesiana sobre TPR/FPR/π SUPUESTOS, y describe un DETECTOR DE INTENCIÓN, no la calidad de un texto generado. La regla no cambia; su base pasa a ser (a) cero mediciones de calidad de borrador en este repo, (b) asimetría irreversible del coste del error, (c) vertical regulada.]** — inaceptable para responder solo, perfectamente utilizable como borrador que un humano acepta o descarta. Es exactamente el bucle de aprobación humana (layer 5) que A1 §1.6 ya decía que había que **diseñar desde el día uno**. El diseño era correcto; la etiqueta de fase estaba mal.

Nota heredada del mismo teardown y que conviene no perder: la superficie de triggers de ManyChat es un **clasificador zero-shot NLI, no un LLM** (`ingenieria-inversa-manychat.md` §1.1), y auto-genera respuestas **sólo para comentarios positivos** — gestión de riesgo disfrazada de feature. Ambas cosas apuntan al mismo sitio: el primitivo de detección propuesto (`bge-m3-zeroshot-v2.0`) gana un segundo rol como trigger de activación, no sólo como detector de señales.

### 3.5 Consecuencia de secuenciación — y es favorable

El hallazgo que importa para planificar: **lo que el fundador pidió es la parte del roadmap MENOS bloqueada por la ruta crítica de la Parte 3.**

Ambas mitades viven casi enteras en el **plano transaccional de Postgres**, no en el analítico:

- **Publicar** necesita la capa de conexión (OAuth, custodia de tokens, refresh) + un origen de media. Nada de eso es ClickHouse.
- **Atender DMs** necesita intake de webhooks, hilos de conversación y estado (abierto/asignado/respondido). Eso es **estado transaccional mutable, leído y escrito en la ruta de petición del usuario** — es Postgres por definición, bajo la regla de dos planos. Lo que sí va a ClickHouse son los **hechos derivados** (sentimiento, intención, volumen, tiempo de respuesta), que son inmutables y analíticos.

**Ruling de modelado, y es vinculante para quien construya el inbox: los hilos y mensajes de DM son Postgres. No se meten en `ingestion.*`.** Un hilo de conversación tiene ciclo de vida y se actualiza; un `ReplacingMergeTree` no es el sitio para un objeto que cambia de estado varias veces por hora y que se lee sincrónicamente para pintar una bandeja. La regla de "los writes nunca cruzan los planos" se aplica igual: unen por `creator_id`.

Corolario: la Parte 3 sigue siendo ruta crítica **para la mitad de lectura de contenido** (§1.3 no cambia), pero **no bloquea la prioridad declarada del fundador**. Los dos trabajos siguen sin competir, y ahora por una razón mejor que la de §1.4.

### 3.6 Reclasificación propuesta del mapa de fases — **PROPUESTO**, pendiente de firma del fundador

El mapa de `CLAUDE.md` ordena **el producto** (SaaS multi-tenant sobre media ajena). La prioridad del fundador es una **pista de dogfooding sobre media propia** que adelanta rebanadas concretas. Se propone registrarla como tal en vez de reescribir el mapa, para no perder el orden que sigue siendo válido para el producto:

| Capacidad | Fase actual | Propuesto | Motivo |
|---|---|---|---|
| Publicar reels/stories en cuentas propias | Fase 5 | **Parte 4-A, ahora** | Los tres problemas duros de ADR 19 no vinculan a N=1 (§3.4a). Sin App Review (§3.1) |
| Bandeja de DMs + comentarios de cuentas propias | Fase 6 (inbox unificado) | **Parte 4-B, ahora** | Plano Postgres, mínimamente bloqueada; es donde está la diferenciación |
| Respuestas **asistidas** (borrador + aprobación humana) | Fase 5 | **Parte 4-B, ahora** | ~~65 % de precisión en media propia~~ **[cifra retirada, enmienda (m)]**: shippable con humano en el bucle, no sin él — por ausencia de evidencia de calidad de borrador, asimetría del coste del error y vertical regulada |
| Respuestas **autónomas** | Fase 5 | **Sigue fuera** | 1 de cada 3 mal. No es cuestión de fase, es cuestión de que no funciona |
| Publicación programada en TikTok | — | **Bloqueado, no planificado** | Auditoría; sin mitigación de ingeniería (§3.2). No poner fecha |
| Gestión de asientos multi-agente | Sin fase | **Sigue sin fase** | Es cliente uno (inmobiliaria), fuera de este sprint por instrucción explícita |
| Listening de competidores, discovery de creadores | Fases 1–4 | **Sin cambio** | Sigue exigiendo scraping. §2.8 no se toca |

**Esto no se aplica a `CLAUDE.md` hasta que el fundador lo firme.** Reordenar el mapa de fases es decisión suya; yo aporto la derivación.

### 3.7 Consecuencias de la frontera de IP con PuntoServis

La restricción del fundador —*"yo no les voy a pedir o regalar mi inteligencia de negocio"*, la herramienta corre **en paralelo** al tooling que PuntoServis suministra— tiene tres consecuencias arquitectónicas concretas, no es sólo una postura:

1. **La app de Meta se registra bajo el portfolio de negocio del fundador, nunca bajo el de PuntoServis.** Sin integración, sin export, sin cuenta compartida con su tooling.
2. **Verificación pendiente, y es del fundador, no de ingeniería: ¿quién posee la cuenta profesional de Instagram de la tienda?** Si el Business Portfolio que la contiene es de PuntoServis, la vía de §3.1 sigue funcionando (él concede su propia cuenta con su rol en la app), pero la **propiedad del activo** afecta a la durabilidad del token y a la propia frontera de IP. Hay que saberlo antes de construir la custodia de tokens, no después.
3. **Qualify no puede asumir que es el único escritor sobre la cuenta.** Correr "en paralelo" a otra herramienta de marketing significa que otra herramienta publica en la misma cuenta. De ahí una regla de diseño que se deriva directamente: **el estado local nunca es autoritativo sobre qué hay publicado; se reconcilia contra la API.** Cualquier feature que cuente posts, mida rendimiento o evite duplicados debe leer de Meta, no de la base de datos propia.

### 3.8 Qué queda abierto tras A5

| # | Cuestión | Dueño | Bloquea |
|---|---|---|---|
| A5-1 | Confirmar contra el corpus cosechado si `instagram_business_content_publish` y `instagram_business_manage_messages` son **Advanced-only por naturaleza**, pese a la regla general de auto-aprobación del acceso estándar | architect, sobre `reference/` | **Todo §3.1.** Si son Advanced-only, la mitad Meta de la asimetría se cae y hay que re-abrir la secuenciación |
| A5-2 | ~~Propiedad del Business Portfolio de la cuenta de la tienda~~ **CERRADO 2026-07-24: el fundador posee el Business Portfolio bajo su propia entidad** → custodia de tokens sin cautividad de vendor/partner, frontera de IP limpia, `key_id` deja de estar forzado por incertidumbre de propiedad (enmienda a ADR 22/23 en `arquitectura.md` §6) | fundador | ~~Custodia de tokens (§2.3), frontera de IP (§3.7)~~ — desbloqueado |
| A5-3 | ~~Firma del fundador sobre la reclasificación de §3.6~~ **FIRMADO 2026-07-24 (B0-6)** → ADRs 21/24 a APROBADO, `CLAUDE.md` y §6.2 actualizados | fundador | ~~Aplicar cambios a `CLAUDE.md`~~ — aplicado |
| A5-5 | **[NUEVO 2026-07-29 — la más bloqueante del expediente Meta]** **V-TP-2, promovida a bloqueante:** una sola prueba empírica contra una cuenta real que responda **(a)** ¿el toggle a **Live Mode** exige App Review y/o Business Verification, o es self-serve?, **(b)** ¿un permiso en Standard Access sigue funcionando para un titular de rol tras pasar a Live Mode? (ver la contradicción de `graph-api/changelog/version3.0.md:128` en `arquitectura.md` §6 enmienda 2026-07-29 (d)), **(c)** ¿es visible para un tercero un reel publicado con la app en Development Mode? Fusiona la prueba que §7.6 ya reclamaba, la retirada de §3.1 (arriba) y el pendiente #1 de `research-modelo-acceso-tech-provider.md`. Las otras cuatro (**V-TP-1**, **V-TP-3…V-TP-5**) no bloquean y están en `arquitectura.md` §6 enmienda 2026-07-29 (h) | **fundador** (es empírica, no documental) | **ADR 21 entera.** Si el paso a Live Mode exigiese Business Verification, el reloj administrativo **sí** bloquea a cliente cero y el ruling central de §3.1 se cae. Todo lo demás del expediente Meta está resuelto o no bloquea |
| A5-4 | WhatsApp Business como canal de DM | investigación | *"Todos los canales de DM"* incluye WhatsApp. `fase0-zernio-mercado.md` §1.1 lo marca **"no verificado — pendiente"**. Es el único canal de la prioridad declarada sobre el que no tenemos **ninguna** evidencia primaria |

A5-4 merece énfasis: la Cloud API de WhatsApp exige Business Verification, verificación del número y plantillas aprobadas — es decir, **es plausible que WhatsApp NO herede la exención de §3.1**, porque su gate no es de acceso a permisos sino de verificación de la entidad y del número. Si es así, "todos los canales de DM atendidos" se parte en dos: Instagram ✅ ahora, WhatsApp ⏳ tras trámite. No se afirma aquí porque no está verificado; se marca como la siguiente pregunta de investigación más valiosa.

---

## 4. (A2, extensión) La capa de conexión del lado write — PROPUESTO

§2 diseñó una capa de conexión **de sólo lectura**, coherente con el ruling *read-first* de A1. El §3.4 lo enmienda: publicar y atender DMs entran en alcance. Esta sección completa A2 con lo que esa enmienda obliga a añadir. No revisa nada de §2.1–§2.8; extiende.

Principio rector, heredado de §3.4(b): **la publicación se construye delgada y aburrida; el triaje de conversación es donde se invierte.** Todo lo de abajo está dimensionado para N=1 tenant, 1 plataforma, 1 operador. Cualquier generalización prematura a multi-tenant/multi-plataforma es precisamente el coste de ADR 19 que §3.4(a) demostró que no tenemos que pagar todavía.

### 4.1 La postura de acceso es dato, no constante

`platform_apps` (§2.2) gana una columna:

```
access_posture   text not null    -- 'development' | 'live'
```

No es cosmético: **de este valor depende quién puede conectar una cuenta**. En `development`, sólo usuarios con rol en la app (§3.1); un intento de conexión de cualquier otro **fallará**, y fallará con un error de Meta que no dice eso. Sin el campo, ese fallo llega a la UI como "error de OAuth" y se depura a ciegas.

Regla de producto que se deriva: mientras `access_posture='development'`, la UI de conexión debe declarar explícitamente que sólo admite cuentas administradas por titulares de rol en la app. Es la traducción a producto de la frontera de §3.4(c) — y es el aviso que evita prometerle a un tercero algo que la plataforma va a denegar.

### 4.2 Publicación — la máquina de estados, y por qué el problema real no es el que parece

> 🔴 **CORRECCIÓN 2026-07-31 (K3) — ESTA SECCIÓN CONTRADICE EL DDL YA APLICADO EN TRES PUNTOS. Escrita por `principal-architect`, `[PROPUESTO]`, sin firmar.** El texto de abajo se conserva porque su **razonamiento** sigue siendo correcto y es el que originó las migraciones; lo que caducó son los **nombres y un requisito de infraestructura**. Un equipo que herede la letra sin esta corrección construye cosas que no existen y, peor, infraestructura que nadie va a visitar.
>
> **(K3.1) La tabla se llama `publish_attempts`, no `publish_jobs`.** `migrations/postgres/versions/0003_publishing.py:72`. Los `GRANT`, las políticas RLS, el trigger `publish_attempts_settle_once` y el índice `ix_attempt_reconcile` usan ese nombre. `publish_jobs` **no existe en ninguna parte del repositorio**.
>
> **(K3.2) La máquina de estados de abajo NO es la que impone la base.** El diagrama `DRAFT → CONTAINER_CREATED → CONTAINER_READY → PUBLISHED / AMBIGUOUS` es conceptual. El `CHECK ck_attempt_status` aplicado admite **exactamente cinco valores**: `pending`, `uploading`, `processing`, `published`, `failed` (`0003_publishing.py:116`). **Un servicio no puede inventar un sexto**, y `AMBIGUOUS` en particular **no es un estado persistible**: es una *situación* que se resuelve por reconciliación mientras la fila sigue en `processing`. Además dos invariantes que el texto de abajo no menciona y que la base sí impone: el trigger rechaza **cualquier** `UPDATE` sobre una fila con `settled_at IS NOT NULL`, y `ck_attempt_settled_matches_status` obliga a escribir sello y estado terminal **en la misma sentencia**.
>
> **(K3.3) LA MÁS CARA DE LAS TRES: "alojar el media en una URL pública" está MUERTO desde ADR 28a, y no aparece tachado en ningún sitio de este documento.** La ruta vigente es **subida resumable de bytes** a `rupload.facebook.com` (`packages/api/src/qualify_api/publishing/client.py:287-311`, cabeceras `offset`/`file_size`). **Meta nunca hace `cURL` de una URL nuestra en la rama de vídeo.** Consecuencia para quien planifique: **no hay que emitir URLs firmadas, ni verificar si el fetcher de Meta acepta query strings, ni razonar sobre TTL de firma, ni exponer superficie HTTP pública alguna.** `ObjectGate` **omite `presign_get` deliberadamente** por esto (ADR 28b). Un equipo que herede la línea vieja construye un subsistema de URLs firmadas completo —con su superficie de ataque— para un cliente que no va a llamar. La excepción sigue siendo **imagen**, que no tiene variante resumable y por eso está diferida a **QUA-68**.
>
> **(K3.4) Bloqueante descubierto el 2026-07-31 que esta sección tampoco contempla: el token.** `content-publishing.md:30` exige **Facebook Page access token** en la columna de la rama firmada; hoy persistimos el de **usuario**. Y `content-publishing.md:19-21` añade una precondición **indetectable por API**: una Página que exija *Page Publishing Authorization* **no admite publicación** hasta completarla. Detalle en `.claude/sprint-state-2026-07-31-po-sprint3.md`.

La publicación en Instagram es un proceso **de dos llamadas con una fase asíncrona en medio**, no un POST:

1. `POST /{ig-user-id}/media` → devuelve un `creation_id` (contenedor). Meta procesa el media de forma asíncrona.
2. Sondear `GET /{container-id}?fields=status_code` hasta `FINISHED`.
3. `POST /{ig-user-id}/media_publish` con el `creation_id`.

El riesgo #2 de ADR 19 (doble publicación bajo fallo ambiguo) se concentra **entero en el paso 3**: se llama a `media_publish`, se agota el timeout, y no se sabe si publicó. Un reintento ciego duplica el post — y un post duplicado es un fallo **visible para el público del cliente**, no silencioso.

**El hallazgo que hace esto manejable: el `creation_id` es un ancla de idempotencia que la plataforma nos regala.** Es estable, consultable y sobrevive a nuestro fallo. Por tanto:

```
DRAFT → CONTAINER_CREATED → CONTAINER_READY → PUBLISHED
                    ↓               ↓              ↘ FAILED
              CONTAINER_FAILED  (expira)        AMBIGUOUS → (reconciliación) → PUBLISHED | CONTAINER_READY
```

**Reglas vinculantes:**

1. **Write-ahead del `creation_id`.** La fila de ~~`publish_jobs`~~ **`publish_attempts`** (K3.1) con el `creation_id` se persiste **antes** de llamar a `media_publish`. Es la misma disciplina que la regla *raw-antes-de-parsear* de ADR 18: si no está escrito, la llamada no ocurre. Sin esto, un crash entre la llamada y el registro pierde el ancla y el estado se vuelve irrecuperable.
2. **`media_publish` nunca se reintenta a ciegas.** Un fallo ambiguo entra en `AMBIGUOUS` y sale por **reconciliación**, jamás por reintento. Es la única transición del sistema que tiene prohibido el retry con backoff.
3. **La reconciliación consulta a Meta, no a nuestra base de datos.** Es la aplicación directa de §3.7(3): otra herramienta de marketing publica en la misma cuenta, luego **el estado local no es autoritativo sobre qué hay publicado**. Se reconcilia listando el media reciente de la cuenta y buscando el resultado del contenedor.
4. **Provenance de efecto externo** (ADR 20): todo publicado lleva `connection_id`, `creation_id`, `access_posture`, `api_version` y una `idempotency_key` propia. Un efecto externo es una escritura derivada y la regla de `CLAUDE.md` no distingue entre derivar una fila y derivar un post.

**Lo que NO se construye ahora**, y se dice para que no se cuele: calendario/scheduling como producto, fan-out multi-plataforma, cola de aprobación editorial, variantes por plataforma. Un operador publicando en una cuenta no necesita nada de eso, y cada pieza es exactamente el producto de ADR 19 entrando por la puerta de atrás.

### 4.3 Bandeja de DMs y comentarios — plano Postgres

> 🔴 **CORRECCIÓN 2026-07-31 (K3, continuación) — cuatro puntos de esta sección están superados por el DDL aplicado o por hallazgos posteriores.** `[PROPUESTO]`, sin firmar.
>
> **(K3.5) Las tablas se llaman `threads` y `messages`**, no `inbox_threads`/`inbox_messages` (`0004_inbox.py:57` y `:106`).
>
> **(K3.6) La fecha de expiración de ventana NO es una columna, y es deliberado.** El bullet de abajo pide *"cada hilo lleva su fecha de expiración de ventana como columna"*. **Rechazado y aplicado como rechazo** (condición B2 del architect, `0004_inbox.py:16-19`): una copia materializada de (base + política) **se queda rancia, y su modo de fallo rancio es exactamente "enviado fuera de ventana"** — es decir, el fallo que la columna pretendía evitar. Se **calcula** desde `last_inbound_at`, y **nunca** desde `last_message_at` (por eso las dos columnas existen separadas: `last_message_at` es orden de bandeja, jamás base de ventana).
>
> **(K3.7) El intake es POLL-FIRST, no webhook.** El bucle de abajo empieza *"llega evento (webhook, §2.6)"*. **Los webhooks no son alcanzables para cliente cero**: exigen app en Live + Advanced Access + Business Verification (`webhooks.md:60-73`), y `ig_shapes.UNCOVERED_SURFACES["webhook_payloads"]` lo registra como superficie no cubierta. **El poll no es red de seguridad: en Development Mode es el único camino que existe.** Lo que sí se construye es la costura que admitirá el webhook después. Y como `COMMENT_LIMITS.filterable_by_timestamp is False`, **el poll no puede ser incremental por tiempo**: la de-duplicación es por id, apoyada en `UNIQUE(connection_id, external_message_id)` — **sin Redis `SETNX`**, decisión explícita de `0004_inbox.py:136-138`.
>
> **(K3.8) La mitad de DM de esta sección no es construible hoy, por dos verjas independientes.** Standard Access sólo permite interactuar con quien tiene **rol en la app** (un cliente real que manda un DM no lo tiene), y además el titular debe activar a mano *Ajustes > Mensajes > Herramientas conectadas*, acción humana **no concedible programáticamente**. Coste conocido de la rama firmada, ya registrado como **(O8)** en `arquitectura.md` §6. **La bandeja construible ahora es de COMENTARIOS sobre media propia**, cuyo nivel de acceso se determina por propiedad de la cuenta y no por el rol de la contraparte (`comment-moderation.md:25-26`).

Confirmado por §3.5 y por ADR 20 (que ya lo dictaminó para el plano de conversaciones): **hilos y mensajes viven en Postgres; su cara analítica va a ClickHouse.** Aquí sólo se añade lo que la prioridad del fundador obliga a tener el día uno.

**La ventana de mensajería es estado transaccional de primer orden, no un detalle.** Meta sólo permite responder dentro de una ventana desde el último mensaje del usuario, y Private Replies sobre un comentario permite **un** mensaje, sobre media propio, ≤7 días (ADR 20, fuente primaria 2026-07-23). Consecuencias:

- ~~Cada hilo lleva su **fecha de expiración de ventana** como columna, no como cálculo en la UI.~~ **[RECHAZADO — ver K3.6. Se calcula desde `last_inbound_at`; no hay columna.]** Sigue en pie el porqué: es lo que decide si el botón de responder está activo, y una respuesta enviada fuera de ventana falla en la plataforma.
- Cada oportunidad de Private Reply lleva un flag de **consumida/no consumida**. Es un recurso de un solo uso; gastarlo por accidente es irreversible.

**Triaje — aquí está la inversión.** El bucle es: llega evento (~~webhook, §2.6~~ **poll — ver K3.7; el webhook no es alcanzable para cliente cero**) → se clasifica → se prioriza en la bandeja → el operador responde, opcionalmente sobre un borrador. La clasificación es el trabajo diferenciado y es un **clasificador zero-shot NLI, no un LLM** (§3.4d): intención, urgencia y sentimiento sobre el mensaje, con `label_set_version` (ADR 16) y `connection_id` como provenance.

**Respuestas asistidas, con la restricción de §3.4(d) escrita en el diseño y no sólo en el roadmap:** el sistema produce **borradores**, nunca envíos autónomos. ~~A 65 % de precisión, 1 de cada 3 borradores está mal;~~ **[cifra retirada, enmienda (m); el fundamento correcto es (a)/(b)/(c) de allí]** con humano en el bucle eso es un ahorro de tiempo, y sin él es un incidente recurrente en público — **irrecuperable y capturable en pantalla, que es la razón que no depende de ninguna medición.** La decisión de enviar es siempre una acción explícita de un humano.

**Fuera de alcance, explícitamente:** asientos multi-agente, asignación y handover bot↔humano. Son necesarios para el cliente uno (la inmobiliaria) y **no** para el cliente cero, que es un operador solo. Se diseña la tabla de hilos de forma que admita una columna `assigned_to` más adelante, y no se construye nada de asignación ahora.

### 4.4 Lo que esta extensión NO resuelve

| Cuestión | Estado |
|---|---|
| WhatsApp como canal de DM | **Abierto y es el hueco grande** — §3.8 A5-4. *"Todos los canales"* incluye WhatsApp y no hay evidencia primaria ninguna |
| ¿Publicar y mensajería son Advanced-only por naturaleza? | **Abierto** — §3.8 A5-1. Si lo son, §4.1 y §4.2 se reordenan detrás del trámite |
| `ORDER BY`/`PARTITION BY` de la cara analítica de conversaciones | **Deliberadamente no fijado.** Inmutable una vez enviado; exige el gate de `clickhouse-architecture-advisor` |
| Retención del raw de primera parte que contiene DMs | **Abierto** — addendum de ADR 18 en `arquitectura.md`, se decide con el plano de conversaciones |

---

## 5. (A3) Buy-vs-build re-ejecutado para el caso EMBEBIDO — PROPUESTO

`fase0-zernio-mercado.md` §2 evaluó agregadores para el **Uso B**: revender una API de publicación a desarrolladores. Ésa no es la pregunta actual. La pregunta es el **Uso A embebido**: Qualify publica y atiende DMs en las cuentas que el fundador administra, dentro de su propio CRM. Y §3 (A5) aporta un dato que ese análisis no tenía. Se re-ejecuta.

### 5.1 El argumento que decide, en una línea

`fase0-zernio-mercado.md` §2.4 estableció —y es el hallazgo más fuerte de aquella investigación— que **lo que compra un agregador hospedado no es el código de sus adapters, sino operar bajo su app ya aprobada**. Se demostró por contraste con Postiz: auto-hospedar el mismo código open-source **no** te presta ninguna aprobación, y el calendario de 2–4 meses vuelve intacto.

Aceptado ese hallazgo, la conclusión para cliente cero es inmediata:

> **§3.1 demuestra que, en Meta, para cliente cero no hay ninguna aprobación que saltarse.** Development Mode + rol en la app = publicar hoy, gratis, contenido público. Luego **el único gran driver de valor del agregador vale exactamente cero** en esta superficie.

No es que el build salga algo mejor en la comparación. Es que **el producto del agregador es la solución a un problema que cliente cero no tiene.**

### 5.2 Lo que queda en cada lado de la balanza, en Meta

**A favor de comprar, una vez retirada la aprobación:** el código de los adapters, y el fan-out multi-plataforma. Ambos se han vuelto baratos o irrelevantes por §3.4(a): **un** adapter, no quince, y sin necesidad de fan-out con una sola plataforma en alcance.

**En contra de comprar, y una de las dos razones es dirimente:**

1. **Coste recurrente y perpetuo por cuenta conectada** (Ayrshare $149/mes el plan de 1 perfil; bundle.social $100/mes; Zernio desde gratis hasta $6/cuenta) contra un coste de construcción que es **una sola vez** y ya está parcialmente diseñado en §2 y §4.
2. **Dirimente — colisiona de frente con la restricción de IP del fundador (§3.7).** Comprar significa que **los DMs de la tienda y los de sus clientes viajan por un tercero**. La restricción declarada es *"yo no les voy a pedir o regalar mi inteligencia de negocio"*, y las conversaciones con clientes son precisamente eso. La restricción se enunció frente a PuntoServis, pero es una restricción sobre **la clase** de arreglo, no sobre una contraparte concreta: no tendría ningún sentido negarse a compartir inteligencia de negocio con el socio comercial y a la vez enrutarla por Ayrshare.

**Y hay una asimetría que hace la comparación aún más desigual: los agregadores no cubren la mitad que importa.** Son herramientas de **publicación**. La bandeja de DMs y comentarios —el bucle leer→clasificar→responder de §3.4(b), donde está toda la diferenciación— **no es su superficie**. (Zernio lista WhatsApp/Telegram/Discord, pero como canales de *envío*, no como bandeja de entrada con estado, ventana de mensajería y triaje.) Comprar no ahorra nada del trabajo diferenciado; sólo del commodity, que es justo la parte que §3.4(b) ya dictamina construir delgada.

**Ruling Meta: BUILD NATIVO. Decisivo, no marginal.**

### 5.3 TikTok — el único sitio donde comprar compra algo real, y es el inverso exacto

La misma regla, aplicada al otro lado de la asimetría de §3.3, se invierte:

- La auditoría de TikTok es **por cliente de API**. El nuestro no está auditado; el de un agregador hospedado sí.
- Luego un agregador **sí** resuelve el problema que §3.2 declara sin mitigación de ingeniería: publicar **público** en TikTok en la cuenta del fundador.
- Y para cliente cero esto es **uso propio, no reventa** → la prohibición de reventa de Ayrshare (§2.3 de `fase0`) **no vincula** aquí. La cláusula que mataba el Uso B es irrelevante para el Uso A.

Es el mismo principio que en §5.1, con el signo cambiado, y conviene enunciarlo como regla generalizada porque es la forma correcta de aplicar la regla Buy/Build de `CLAUDE.md` a este dominio:

> **Se compra la aprobación, no el código.** Donde haya un gate de plataforma que no podamos pasar, comprar tiene sentido aunque el código sea trivial. Donde no haya gate, comprar no aporta nada aunque el código cueste.

**Pero la recomendación honesta no es comprar, y tampoco construir.** Antes de recomendar gasto hay que comprobar que se paga solo, y aquí no:

- $100–149/mes perpetuos para automatizar la publicación en **una** cuenta de TikTok de una tienda que publica unas pocas veces por semana.
- La alternativa es **publicar a mano**, que ya es posible hoy, cuesta cero, y no tiene ningún gate (§3.2: lo bloqueado es TikTok *vía API*, no TikTok).

**Ruling TikTok: NI comprar NI construir todavía — no automatizar.** Se re-abre cuando (a) el volumen haga doloroso el trabajo manual, o (b) la venta a terceros justifique perseguir la auditoría propia. Registrar la opción del agregador como la vía conocida, no ejercerla.

**Verificación pendiente antes de ejercerla algún día, y no se asume:** que el cliente de API auditado del agregador devuelva efectivamente opciones de privacidad **públicas** vía `creator_info` para una cuenta de cliente conectada. Es lo plausible —el gate es por cliente de API— pero `fase0` §2.4 sólo lo verificó para el modelo de conexión white-label en general, no para el comportamiento de `creator_info` de TikTok en concreto.

### 5.4 Matriz de decisión

| Superficie | Decisión | Razón |
|---|---|---|
| Publicación en Meta, cuentas propias | **BUILD** | No hay aprobación que comprar (§3.1). El coste del agregador es perpetuo y su valor dominante es cero aquí. Y enrutar por un tercero choca con §3.7 |
| DMs / comentarios / bandeja en Meta | **BUILD** | **No es superficie de agregador en absoluto**, y es la mitad diferenciada (§3.4b) |
| Publicación programada en TikTok | **NO AUTOMATIZAR** (agregador registrado como vía conocida, no ejercida) | Comprar resolvería el gate, pero $100–149/mes no se pagan para una cuenta que puede publicarse a mano gratis |
| Proxies / anti-bloqueo del pipeline de scraping | **BUY** (Zyte) — sin cambio | ADR 17. Nada de A5 lo toca |
| Venta a terceros, más adelante | **RE-ABRIR** | Es cuando la aprobación vuelve a valer, y el disparador es exactamente la línea Development/Advanced de §3.4(c) |

**Efecto neto sobre `alternativas-fase1.md`:** ninguno. Aquel documento evalúa la ingesta de media ajena (scraping, proxies, outreach) y sus recomendaciones siguen en pie sin tocar. Esta sección sólo cubre la superficie de cuentas conectadas, que no existía cuando se escribió.

---

## 6. Rulings de la sesión PO (2026-07-24) — respuestas a W1–W4

Sección de arbitraje. `po` redactó los procesos en `docs/backlog-crm-workflows.md` y elevó las preguntas que no le corresponden. Aquí se responden. Todo **PROPUESTO** salvo donde se diga otra cosa.

### 6.1 V1 / A5-1 — **CERRADO.** La pregunta no tenía respuesta porque estaba mal planteada

Marqué en §3.8 que lo único capaz de tumbar la mitad Meta de A5 era si `instagram_business_content_publish` y `instagram_business_manage_messages` fueran **Advanced-only por naturaleza**. `pipeline` fue a buscarlo y encontró algo mejor que una respuesta: **la pregunta no existe en el modelo de Meta.**

- Las páginas `/docs/permissions/reference/<permiso>` **no existen**: redirigen (301) a fragmentos de una única página de 1,14 MB que documenta **requisitos de envío a App Review**, no niveles de acceso. En sus 79 KB de texto, "Advanced Access" y "Standard Access" aparecen **una vez cada una**, en boilerplate.
- Porque **el nivel de acceso es propiedad de la app y de a quién sirve, no del permiso.** Un permiso no es "Advanced-only"; una *app* opera en un nivel u otro.

**Ruling: A5-1 se cierra a favor de §3.1. No hay trampa por permiso.** §3.1 se mantiene íntegro para cliente cero. `po` puede **desbloquear** los ítems de §5 que había gateado tras V1 (W3-Q2 y W4-Q2 quedan resueltos por esta vía, no pendientes).

#### 6.1-bis Pero la frontera se afila, y esto **sí** modifica §3 — la cita operativa

`pipeline` aportó la frase que convierte mi "frontera Development/Advanced" de principio en **prueba aplicable**. Literal del Instagram Platform overview:

> Standard Access: *"the default access level for all apps... intended for apps that will only be used by people who have roles on them... **If your app only serves your Instagram professional account or an account you manage, Standard Access is all your app needs.**"*
>
> Advanced Access: *"the access level required **if your app serves Instagram professional accounts that you don't own or manage** and can be used by app users who do not have a role on your app... **This access level requires App Review and Business Verification.**"*

**Definición operativa de la frontera, que sustituye a la formulación cualitativa de §3.4(c):**

> Una app necesita Advanced Access —y por tanto App Review + Business Verification— **en cuanto sirve una cuenta profesional que no posees ni administras, o admite usuarios sin rol en la app.** Ambas condiciones se cumplen con **el cliente uno**.

**Consecuencia que hay que decir sin suavizar, y que corrige el tono de mi propio reporte anterior:** el trámite de 2–4 meses **no es un problema de escala lejana. Vincula en el cliente uno.** Los agentes de la inmobiliaria no tendrán rol en nuestra app y sus cuentas no son nuestras. La distancia entre *"cliente cero desbloqueado"* y *"producto que da de alta clientes"* es **exactamente un ciclo de App Review**.

Esto **restaura en plena fuerza** el punto 1 de mi §1.4 (arrancar el reloj administrativo en la semana 0, coste de ingeniería cero). A5 nunca lo mató: sólo lo sacó de la ruta crítica **de cliente cero**. Con el cliente uno comprometido a corto plazo, el reloj vuelve a la ruta crítica del producto y **debe arrancar ya**.

**Y una advertencia de diseño que se deriva de un matiz de la misma doc:** *"Because of the limited scope of Standard Access, some features might not work properly until your app has been granted Advanced Access."* Es decir: **el camino de cliente cero no es una vista previa funcional limpia del camino real.** No se puede tratar "funciona para el fundador" como validación de que funcionará para un cliente. Toda estimación de W2/W3/W4 debe reservar presupuesto para diferencias de comportamiento que sólo aparecerán tras Advanced Access.

**Defecto documental de Meta, registrado para que no confunda a nadie al leer el corpus** (hallazgo de `pipeline`): en la página de permisos, `instagram_business_manage_comments` lleva **pegada la descripción de `instagram_business_content_publish`** ("allows an app to create organic feed photo and video posts"). El encabezado y las Dependencies son correctos; la prosa no. No tomar esa entrada al pie de la letra.

### 6.2 Conflicto de mapa de fases — **RULING: la multi-tenancy sale de la Fase 6. Es fundación, no endurecimiento**

`CLAUDE.md` coloca *multi-tenant isolation* en la **Fase 6** (última). El fundador la quiere primera. Se resuelve explícitamente, no por omisión.

**Ruling: el `tenant_id` y su propagación son FUNDACIÓN y entran ahora. Los mecanismos de aislamiento son por capas y no entran todos a la vez.** Esa distinción es la mitad del ruling: "multi-tenant isolation" en la Fase 6 empaqueta cosas de coste y urgencia muy distintos, y mover el bloque entero sería tan erróneo como dejarlo.

| Componente del bloque "multi-tenant" | Ruling | Motivo |
|---|---|---|
| El **identificador** `tenant_id` y su presencia en todo esquema y toda query | **AHORA — fundación** | Ver los cuatro motivos de abajo |
| Aislamiento **estructural** en Postgres (RLS) | **AHORA** — ver §6.3(c) | Barato hoy, disciplinario para siempre si se pospone |
| Aislamiento **estructural** en el keying de R2 | **AHORA** — ya decidido, ADR 22 | Es la misma decisión, ya tomada |
| Cuotas y **fair-share de rate limit** entre tenants | **Capa posterior, no día uno** — ver §6.4(2) | Con dos tenants el riesgo es real pero acotado, y el mecanismo correcto depende de datos que no tenemos |
| Cuotas de recursos, aislamiento de cómputo, auditoría multi-tenant completa | **Se queda en Fase 6** | Es endurecimiento genuino |

**Los cuatro motivos, en orden de fuerza:**

1. **La premisa de la Fase 6 es falsa.** Poner la multi-tenancy al final sólo tiene sentido si se es mono-tenant hasta alcanzar escala. **Hay dos tenants reales el día uno** (la tienda del fundador y la inmobiliaria con N agentes). No es una previsión: es el encargo.
2. **El identificador acaba en un prefijo de `ORDER BY` de ClickHouse, que es INMUTABLE una vez creada la tabla.** Retrofitear la tenancy no es un refactor: es reconstruir cada tabla del plano analítico y re-ingerirla. Es exactamente la migración que nadie sobrevive barata, y `CLAUDE.md` ya declara la inmutabilidad del `ORDER BY` como regla dura.
3. **Es greenfield AHORA MISMO. Verificado hoy: cero ocurrencias de `tenant_id` o `workspace_id` en todo el repo**; lo único existente es `brand_id` (`packages/scraper`, tests y README). El coste hoy es una columna y una convención. El coste después de que la Parte 3 emita el DDL es catastrófico. **Ésta es la última ventana en la que la decisión es barata.**
4. **Parte de la decisión ya está tomada aguas abajo.** ADR 20 ya dictaminó que el plano de conversaciones lleva el identificador de tenant como **clave líder**, y ADR 22 ya invirtió el keying de R2 a tenant-scoped. Dejar la multi-tenancy en la Fase 6 mientras dos ADRs vigentes dependen de ella es una incoherencia del mapa, no una prioridad.

**Segundo conflicto — el inbox unificado, también Fase 6. Ruling: se separa en dos cosas que el mapa confunde.**

- **La bandeja de un canal (Instagram), para las cuentas conectadas del tenant** → entra ahora, como Parte 4-B (ya propuesto en §3.6). No es "inbox unificado": es la cara de lectura/respuesta de una sola integración.
- **El inbox *unificado* cross-canal** (Instagram + WhatsApp + lo que venga, con contexto compartido y grafo cross-canal) → **se queda en la Fase 6**. Eso sí es plataforma, y su coste está dominado por integrar canales que todavía no tenemos.

Formulado como regla para que no se re-litigue: **una bandeja no es un inbox unificado hasta que unifica más de un canal.** El mapa de fases tenía razón sobre el segundo y nunca dijo nada sobre el primero.

**Estado: PROPUESTO.** Reordenar el mapa de fases lo firma el fundador (A5-3 / W1-Q4). Yo aporto la derivación y el coste de equivocarse; `CLAUDE.md` queda anotado, no modificado.

### 6.3 W1-Q1 / W1-Q2 / W1-Q5 — nombre, jerarquía y mecanismo de aislamiento

#### (a) W1-Q1 — **Ruling: `tenant_id`.** Y `workspace_id` de mis propios documentos se renombra a esto

Tres nombres para dos conceptos. Se resuelven así:

| Identificador | Qué significa | Estado |
|---|---|---|
| **`tenant_id`** | **Frontera de aislamiento.** Quién tiene derecho a ver algo. Cláusula primera de toda query, prefijo de toda clave de almacenamiento de primera parte | **Canónico. Se adopta** |
| `brand_id` | **Entidad observada.** Sobre qué marca versa un hecho | **Se conserva, no se fusiona** |
| ~~`workspace_id`~~ | — | **Renombrado a `tenant_id`** en §2.2 de este doc y en ADR 20 |

Motivos, en orden:

1. **El fundador y la tarea #14 dicen `tenant_id`.** Divergir en el nombre respecto de quien firma tiene coste y ningún beneficio.
2. **`workspace` es un concepto de *producto*; `tenant` es un concepto de *aislamiento*.** Pueden divergir: un tenant con varios workspaces es una evolución de producto perfectamente normal. Bautizar la frontera de aislamiento como `workspace_id` **cierra esa puerta** y obliga a un rename cuando se abra.
3. **El rename es gratis hoy.** ADR 20 fijó `workspace_id` como clave líder del plano de conversaciones, pero está **PROPUESTO y no construido**, y hoy hay **cero ocurrencias de ninguno de los dos nombres en el repo** (verificado 2026-07-24). Renombrar en documentación cuesta minutos; renombrar una clave líder de ClickHouse ya creada no cuesta: es imposible.

#### (b) W1-Q2 — **Ruling: `brand_id` NO se fusiona con `tenant_id`. Son ejes ortogonales, y confundirlos rompe ADR 18**

> **`brand_id` = *qué* se observa. `tenant_id` = *quién* tiene derecho a verlo.**

No están en la misma dimensión, y por eso la pregunta "¿marca == tenant el día uno?" tiene que responderse **no**, aunque hoy coincidan numéricamente:

- **Dos tenants distintos pueden monitorizar la misma marca.** Ése es literalmente el rationale que ADR 18 conserva: *"N marcas comparten un scrape"*. Si `brand_id` fuera el tenant, esa economía desaparece y ADR 18 pierde su mitad superviviente.
- **El cliente uno lo vuelve concreto de inmediato.** La inmobiliaria son N agentes atendiendo varias oficinas/marcas. Si la marca fuera el tenant, cada usuario habría que duplicarlo por marca y el modelo de asientos deja de cerrar — exactamente lo que `po` observó en W1-Q2, y tiene razón.

**De aquí sale una regla dual que hay que fijar antes de escribir DDL, porque decide qué lleva `tenant_id` y qué no:**

| Clase de dato | Clave | ¿Compartible entre tenants? |
|---|---|---|
| Hechos de **media ajena** (scraping: posts, comentarios públicos, menciones) | `brand_id` | **Sí.** Es contenido público; compartirlo es la economía de ADR 18 |
| Datos de **primera parte** (respuestas de Graph API, insights propios, DMs, hilos, credenciales) | `tenant_id` | **Nunca.** ADR 22 |

**Corolario que hay que decir en voz alta porque es contraintuitivo: `tenant_id` NO va en el prefijo de todos los `ORDER BY`.** Meterlo en las tablas de media ajena destruiría la economía de scrape compartido y sería un error caro e irreversible. Va en las tablas de primera parte y de conversaciones.

**Contrapartida honesta, y es una decisión de riesgo, no una obviedad:** significa que las filas de media ajena **no se auto-aíslan** — la comprobación de "¿este tenant tiene derecho a esta marca?" vive en la aplicación, sobre el mapeo tenant→marcas de Postgres. Es defendible porque el dato subyacente es público (una fuga expondría qué marca monitoriza alguien, no datos privados de nadie), pero **no es lo mismo que el aislamiento estructural** que sí exigimos en primera parte. Se registra como tal, no se disfraza.

**Y no se lockea aquí ningún `ORDER BY`.** Lo que se fija es el **principio** de qué eje aísla cada clase de tabla. Los `ORDER BY` y `PARTITION BY` concretos van **PROPUESTO-no-lockeado** y pasan por el gate de `clickhouse-architecture-advisor` antes de crear ninguna tabla, porque son inmutables una vez enviados.

#### (c) W1-Q5 — **Ruling: RLS de Postgres desde el día uno.** Y el motivo es de coherencia, no de gusto

He dictaminado dos veces esta misma sesión que el aislamiento de tenant debe ser **estructural y no disciplinario**: el `model_validator` que hace inconstruible un envelope de primera parte sin tenant, y la derivación de clave por encima del store para que ninguna implementación pueda reimplementar mal la regla (ADR 22). **Dictaminar que en Postgres basta con disciplina de aplicación sería incoherente con ambas.** El plano transaccional es donde viven las credenciales OAuth y los DMs — es el que menos margen tiene.

**Pero el coste real de RLS no está donde `po` teme.** Lo caro de retrofitear RLS no son las políticas: es (i) que toda tabla tenga `tenant_id NOT NULL` y (ii) que **todo acceso pase por un helper de sesión que fija el GUC de tenant por transacción**. Si (i) y (ii) existen desde el principio, añadir políticas después es mecánico; si no existen, no se añaden nunca. Por eso el ruling se formula sobre el mecanismo, no sobre la feature:

> **Vinculante desde la primera migración:** (1) toda tabla con datos de tenant lleva `tenant_id NOT NULL`; (2) **existe un único helper de conexión/sesión** que fija `SET LOCAL app.tenant_id` por transacción y **es el único camino de acceso a la base**; (3) las políticas RLS se declaran junto a la tabla, en la misma migración que la crea.

**Dos detalles que se equivocan sistemáticamente y que son load-bearing:**

- **El rol de aplicación NO debe ser el propietario de las tablas.** En Postgres el propietario **salta RLS** por defecto. Si la app se conecta como owner, las políticas existen y no protegen nada — el peor de los mundos, porque genera confianza infundada.
- Usar **`FORCE ROW LEVEL SECURITY`** en las tablas donde el propietario también deba quedar sujeto, y probar el aislamiento con **un test que intente cruzar tenants y espere cero filas** — no con un test que compruebe que la política existe. La garantía es "no se pueden leer filas ajenas", no "hay una policy declarada".

**Lo que NO entra el día uno:** cifrado por tenant más allá de la DEK ya diseñada en §2.2, cuotas de recursos, y auditoría multi-tenant completa. Eso sí es endurecimiento de Fase 6.

### 6.4 Respuestas al resto de preguntas abiertas de W2–W4

#### W3-Q3 — Alojamiento del media. **No arrastra la Parte 3, y el problema del TTL se disuelve**

Meta hace `cURL` del media desde una URL pública **en el momento de publicar**, no al componer. `po` teme que un post programado días antes obligue a una URL con TTL largo, y que eso meta la Parte 3 dentro de W3.

**Ruling: se genera la URL firmada en el paso de PUBLICAR, no en el de componer.** El media se guarda en R2 con clave privada; el worker de publicación mintea una URL prefirmada de vida corta justo antes de llamar a `/media`. Entonces el TTL sólo tiene que cubrir **la operación de publicación (minutos)**, no el horizonte de programación (días). El problema desaparece por secuenciación, no por infraestructura.

Consecuencias:

- **No arrastra la Parte 3.** Lo que W3 necesita es *almacenamiento de objetos con URL firmada*, que es un subconjunto estricto del cliente R2 y no toca ClickHouse, Celery ni `ingestion.*`. La línea de §2.7 de `po` (publicar no está bloqueado por la Parte 3) **se sostiene**, con la precisión de que sí depende de **la rebanada R2** de ella.
- **Beneficio de seguridad, no sólo de conveniencia:** un bucket público con media de clientes es un activo permanentemente expuesto; una URL prefirmada de minutos no lo es. La opción barata resulta ser también la correcta.
- **[V] Verificar contra el corpus antes de construir:** que el fetcher de Meta acepte una URL con query string de firma. Es un GET HTTPS normal, luego lo esperable es que sí, pero **hay plataformas que rechazan URLs firmadas** y esto es exactamente la clase de detalle que no se adivina. Si resultara que no, el fallback es una ruta pública propia con token opaco y caducidad — mismo diseño, distinta fachada.

#### W4-Q5 — `assigned_agent_id`. **Aprobado tal como lo propone `po`: la columna nace nullable el día uno; la UI de asignación al parking lot**

Es el mismo razonamiento que el `tenant_id` de §6.2, y `po` lo identifica correctamente como la misma forma de decisión. Coste hoy: una columna nullable. Coste después: una migración contra una bandeja viva, con hilos abiertos y agentes trabajando encima. **La asimetría entre ambos costes es de varios órdenes de magnitud y sólo existe mientras esto sea greenfield.**

Regla generalizada, porque en esta sesión ya ha aparecido tres veces (`tenant_id`, keying de primera parte, `assigned_agent_id`): **cuando una decisión de esquema es reversible hoy e irreversible tras el primer dato de producción, se toma hoy aunque la feature que la usa esté parkeada.** Lo que se aplaza es la funcionalidad, nunca la forma del dato.

#### Alcance multi-agente — **la gestión de `po` es correcta, se confirma**

§3.6 dice que los asientos multi-agente *"siguen sin fase"* y la tarea #17 pide **definir** el proceso. No hay contradicción: **definir un proceso no es construirlo**, y el fundador pidió explícitamente procesos definidos antes de desarrollar. Definir ahora es además lo que hace posible la decisión de W4-Q5, que sí es urgente.

Se confirma: proceso **definido** en §4.4, ítems al **parking lot** de §5, columna nullable en el esquema. Cliente cero tiene un asiento y no necesita nada de esto.

#### W3-Q1 — "Promociones". **`po` tiene razón en separarlo, y la separación es más grande de lo que parece**

Asumir (a) *post orgánico cuyo contenido promociona una oferta* es correcto y es lo que debe entrar en el backlog. Sobre (b) *publicidad pagada*, tres cosas que refuerzan dejarlo fuera y sin estimar:

1. **Es la Marketing API: otra familia de permisos, otro producto de app, y exige método de pago y Business Manager.** `po` verificó que no hay una sola línea sobre ella en el repo; lo confirmo, y mi §3.1 tampoco la menciona porque verifiqué publicación de contenido orgánico, no gasto publicitario.
2. **Está aguas abajo del reloj de §6.1 de todas formas.** Gestionar gasto publicitario de terceros es el caso paradigmático de "cuentas que no posees ni administras" → Advanced Access + Business Verification. No es una feature que se pueda adelantar a cliente cero ni aunque se quisiera.
3. **Es discutiblemente otro producto.** Gestión de campañas de pago no es CRM de cuentas conectadas; tiene su propio ciclo de vida, su propia unidad económica y su propio riesgo (se gasta dinero real del cliente). Meterlo en W3 lo haría irreconocible.

**Pregunta al fundador, tal como `po` la formula.** Si dijo (b), no es "W3 cambia de tamaño": es una línea de producto distinta y hay que investigarla desde cero.

#### §2.5 de `po` — el contrato de degradación por scope denegado. **Endosado, y elevado a requisito arquitectónico**

Es una aportación de `po`, no derivada de mis documentos, y es buena. La adopto con dos precisiones:

1. **La consecuencia arquitectónica es que la capacidad degradada tiene que ser un tipo, no una excepción.** Si "no tengo permiso para responder comentarios" se descubre cuando la API devuelve 403, ya es tarde: el usuario hizo clic en un botón que no debía existir. La conexión debe exponer un **conjunto de capacidades derivado de los scopes concedidos**, y la UI se pinta desde ese conjunto. Es el mismo patrón que `access_posture` en §4.1: **el estado de permisos es dato, no un error en tiempo de ejecución.**
2. **La fila que a `po` le importa —leer comentarios no depende del permiso de responderlos— es exactamente la que NO se puede verificar todavía**, y precisamente porque la entrada de `instagram_business_manage_comments` en la página de permisos está corrupta (§6.1). Es plausible que la lectura caiga bajo `instagram_business_basic` y la escritura bajo `manage_comments`, que es lo que sostendría la escalera. **No se asume.** Es la verificación de mayor valor que queda sobre el corpus después de la de WhatsApp, porque de ella depende el argumento de onboarding con un cliente desconfiado.

#### WhatsApp — el argumento comercial de `po` se acepta, y tiene una consecuencia de diseño

`po` argumenta que WhatsApp debe priorizarse **por encima de su tamaño técnico**, porque el negocio inmobiliario latinoamericano corre sobre WhatsApp y para el cliente uno probablemente *es* el canal, no uno de varios. Lo marca como argumento comercial suyo y no como hallazgo. **Aceptado**: encaja con A5-4, y es coherente con que su gate sea de **verificación de entidad y de número**, no de nivel de permiso — luego **es plausible que NO herede la exención de §3.1**, y eso lo hace independiente del reloj de App Review en vez de estar detrás de él.

**Consecuencia de diseño, que es lo que me toca aportar:** si los canales van a llegar con **estados de habilitación distintos y por motivos distintos** (Instagram por nivel de acceso, WhatsApp por verificación de entidad y plantillas, TikTok cerrado), entonces la bandeja **no puede modelar el canal como un enum con código especializado por rama**. El canal necesita ser una entidad con sus propias capacidades y su propio estado de habilitación — igual que `access_posture` y que el conjunto de capacidades de la conexión. Es la tercera vez que aparece el mismo patrón en esta sesión, y conviene fijarlo como regla: **todo gate de plataforma se modela como dato del que la UI y el orquestador leen, nunca como una rama de código.**

### 6.5 A3 re-ejecutado para el CLIENTE UNO — ¿el agregador salta el ciclo de App Review?

§5 respondió el buy-vs-build para **cliente cero**, donde no hay aprobación que comprar. El lead reformula, con razón, la pregunta que de verdad decide: **§6.1 demuestra que App Review + Business Verification vinculan en el cliente uno. ¿Enrutar al cliente uno por un agregador permite darlo de alta sin nuestro propio App Review?**

**Respuesta corta: en el papel sí, en la práctica no compra ni un día de calendario. Y el motivo no es el precio.**

**(a) Sí bypasea el gate — de la publicación.** Es literalmente el producto del agregador: el usuario final concede OAuth a **la app ya aprobada del agregador**, no a la nuestra. `fase0-zernio-mercado.md` §2.4 lo verificó (página de conexión white-label, sin claves ni aprobaciones propias). Esto es real y no lo discuto.

**(b) Pero la necesidad del cliente uno no es publicar. Es la bandeja.** La inmobiliaria son **agentes humanos atendiendo canales**. El agregador resuelve el gate de la mitad que el cliente uno menos necesita.

**(c) Y aquí está el argumento que decide, que es de calendario y no de dinero.** Los agregadores son herramientas de **publicación** (§5.2): la bandeja con estado, ventana de mensajería y triaje no es su superficie. Si eso se confirma, entonces:

> Necesitamos **nuestro propio App Review para la mitad de mensajería, pase lo que pase**. Y Meta revisa **por envío, no por permiso**: un mismo envío puede cubrir publicación y mensajería. Luego, una vez que pagamos el reloj por la mensajería —que es obligatorio—, **la publicación viaja gratis en el mismo envío**.
>
> **Conclusión: el agregador compra cero tiempo de calendario, y cuesta cuotas perpetuas, cautividad del consentimiento y la frontera de IP.**

**(d) La cautividad del consentimiento muerde más fuerte en un CRM que en un revendedor**, que es exactamente el contrapeso que el lead pide sopesar. Bajo la vía de compra, el grant de OAuth **pertenece al agregador**. Nosotros nunca custodiamos el token. Consecuencias que un revendedor puede tolerar y un CRM no:

- Si el agregador sube precios, cambia términos, cierra, o simplemente decide que somos competencia (recuérdese la cláusula literal de Ayrshare *"no accessing the site to build a similar or competitive product"*), **todos los clientes tienen que volver a consentir, uno por uno**. Es el peor momento posible para pedirle a un cliente que vuelva a autorizar: cuando algo ha ido mal.
- **El moat declarado de Qualify es poseer la relación con el cliente.** Alquilar el consentimiento es alquilar el moat. Y toda la §2.2 —custodia versionada, rotación, máquina de estados de salud, `connection_events` como auditoría— **deja de tener objeto**, porque no custodiamos nada.
- Y colisiona con §3.7 igual que en §5.2: los DMs de los clientes del cliente uno viajarían por un tercero.

**Ruling: se mantiene BUILD NATIVO, ahora también para el cliente uno, y por una razón más fuerte que la de §5.** No es que construir salga mejor: es que **el ciclo de App Review es inevitable por la mitad de mensajería, y una vez pagado cubre también la publicación.** El agregador cobra por saltarse un reloj que de todos modos hay que correr.

**Consecuencia operativa que sí cambia el plan, y es la más accionable de esta sección:** si el envío de App Review va a cubrir **publicación y mensajería juntas**, entonces la demo funcional que Meta exige grabar debe cubrir **ambas superficies**, y eso fija qué hay que tener construido antes de enviar. Refuerza el punto 3 de §1.4: construir la capa de conexión no es trabajo especulativo, **es un entregable del trámite** — y ahora sabemos que el entregable incluye la bandeja, no sólo el publicador.

**La bisagra falsable, dicha como tal y no escondida:** todo (c) depende de que **ningún agregador ofrezca bandeja de DMs de Instagram (recibir + responder) bajo su app aprobada**. Lo creo por la evidencia de §5.2 —se comercializan como herramientas de publicación y sus listas de canales de mensajería son de *envío*— pero **no lo he verificado producto a producto**. Si alguno sí la ofrece, (c) se cae, el reloj vuelve a ser evitable y esta decisión se re-abre. **Es la verificación que hay que hacer antes de comprometer el calendario del cliente uno**, y es barata comparada con lo que decide.

---

## 7. La bifurcación de login — **RULING: Facebook Login for Business.** Puerta de un solo sentido, decidida sobre el corpus

> **Estado: APROBADO (firmado por el fundador, 2026-07-26).** Este ruling se formalizó como **ADR 25** en `docs/arquitectura.md` §6 y el fundador lo firmó **sin cambios** el 2026-07-26 — ni la decisión ni sus consecuencias se modificaron. Dejó de ser sólo un ruling técnico del architect. Firmó con las dos incomodidades explícitas sobre la mesa: el **coste aceptado** es la fricción de onboarding (la Página de Facebook vinculada es precondición dura) y la decisión **ya estaba materializada en DDL aplicado** (`social_connections.linked_page_id NOT NULL`), con C-04 construido encima. Dos matices que la firma **no** ablanda: el *mecanismo* del gate de Página es la **enumeración post-consentimiento en el callback** (ruling R4, `arquitectura.md` §6), no la detección pre-auth; y el **aviso permanente sobre las cuatro grafías del scope de publicación** sigue vigente — resolver empíricamente contra el endpoint de autorización, nunca hardcodear desde documentación.

**Fuente:** `reference/meta-instagram-platform/`, cosechado por `pipeline` el 2026-07-24. Todas las citas de esta sección son de ficheros en disco; se pueden comprobar.

> `instagram-platform/app-review.md:23` — **"Warning: Your app can either use Facebook Login or Instagram Login but not both."**

Es irreversible y está aguas arriba de todo W2. Se decide antes de que exista una línea de código de conexión.

### 7.1 El dato que decide, y que invierte una preferencia previa mía

Las dos vías **no ofrecen el mismo conjunto de permisos**. `app-review.md:27-52`:

| Instagram API with **Facebook Login** | Instagram API with **Instagram Login** |
|---|---|
| Human Agent · **Instagram Public Content Access** · `ads_management` · `business_management` · `catalog_management` · `instagram_basic` · `instagram_branded_content_*` (3) · `instagram_content_publishing` · `instagram_manage_comments` · `instagram_manage_events` · **`instagram_manage_insights`** · `instagram_manage_messages` · `instagram_manage_upcoming_events` · `instagram_shopping_tag_products` · `pages_read_engagement` · `pages_show_list` | Human Agent · `instagram_business_basic` · `instagram_business_content_publishing` · `instagram_business_manage_comments` · `instagram_business_manage_messages` |

**Dieciocho contra cinco.** Y lo que falta en la columna derecha no es relleno:

**(a) `mentioned_media` y `mentioned_comment` existen, y son EXCLUSIVOS de Facebook Login.** Documentados en `documentation/instagram-platform/instagram-api-with-facebook-login/mentions.md:18-20` y como edges de `ig-user` (`.../reference/ig-user.md:90-92`):

> `GET /{ig-user-id}?fields=mentioned_media` — *"to get data about a **media object** on which a Business or Creator Account has been @mentioned **in a caption**"*
> `GET /{ig-user-id}?fields=mentioned_comment` — *"to get data about a comment that a Business or Creator Account has been @mentioned in"*
> `POST /{ig-user-id}/mentions` — para **responder** a ese comentario o a esa caption

**Esto es la superficie que decide si la cascada multimodal tiene algún uso en esta vía.** En la matriz de `oauth_scope.py`, `MENTIONED_MEDIA` es **la única** celda donde visión *y* transcripción son `APPLIES_UNCHANGED`. Es un **objeto de media de un tercero**, alcanzable por consentimiento y sin scrapear — la única superficie *earned* legítima de todo el camino OAuth.

> **Elegir Instagram Login borraría la cascada multimodal del camino de cuentas conectadas.** Sin `mentioned_media`, filtro, visión y transcripción se quedan **sin un solo caso de uso sin modificar**, y el sentiment sobre comentarios pasa a ser literalmente la única etapa que transfiere — es decir, el escenario de concentración de robertuito **llegando por un mecanismo documentado**. En esa vía Qualify sobre cuentas conectadas es una herramienta de publicación con analítica, no Qualify.

**Esto resuelve la preocupación de `datasci-2` y la resuelve en el sentido contrario al temido:** su lectura de que `mentions` aparece *"solely as a webhook field"* y llega **con forma de comentario (texto)** es **correcta — pero sólo para la vía Instagram Login**. En la vía Facebook Login existen los edges de lectura completos y el objeto de media. El corpus que consultó estaba incompleto (los ficheros viven bajo `documentation/instagram-platform/instagram-api-with-facebook-login/`). Su cautela metodológica era la correcta y su conclusión condicional se sostiene: **la bifurcación de login no era una elección de vocabulario, decidía si el diferenciador existe en esta vía.** Acertó en lo que importaba.

**(b) `Instagram Public Content Access` es exclusivo de Facebook Login** (`documentation/instagram-platform/overview.md:88`), y `overview.md:92` dice qué es: *"allows your app to access Instagram Graph API's **Hashtag Search** endpoints."* Es la **segunda y última** superficie earned alcanzable por OAuth. También desaparece en la vía Instagram Login.

**(c) `ads_management` y `catalog_management` sólo están en Facebook Login** → si el fundador responde **(b)** a W3-Q1 ("promociones" = publicidad pagada), esa puerta **sólo existe** en esta vía. Elegir Instagram Login la cierra sin haberle preguntado.

### 7.2 La asimetría de migración — cuál de las dos es realmente la puerta de un solo sentido

`app-review.md:54-63` documenta la migración **Facebook Login → Instagram Login**, con una tabla de equivalencia permiso a permiso y esto:

> *"your app might automatically be granted Advanced Access for the corresponding Instagram API permission and App Review isn't required."*

**No existe documentación de la migración inversa.** Luego:

> **Facebook Login preserva la opcionalidad; Instagram Login la consume.** Empezar en Facebook Login deja abierta una salida documentada —y potencialmente sin App Review— hacia la vía simple. Empezar en Instagram Login no deja ninguna hacia la completa.

Ante una decisión irreversible con información incompleta, la regla es elegir la rama que conserva la reversibilidad. Aquí además coincide con la rama de mayor capacidad, así que no hay que pagar nada por la opcionalidad.

### 7.3 El coste, dicho sin adornos — y la corrección de un juicio mío

La vía Facebook Login **exige una Página de Facebook vinculada** a la cuenta profesional. Ésa es toda la ventaja de la otra vía, y en mi §3.1 la registré como **beneficio** (*"elimina la dependencia de Página de Facebook que `fase0` §1.1 daba por obligatoria"*).

**Ese juicio queda corregido.** El dato era cierto y la conclusión que insinuaba, equivocada: valoré una reducción de fricción de onboarding sin saber que se pagaba con las dos únicas superficies earned del camino OAuth. La comparación correcta es:

| | Coste de Facebook Login | Coste de Instagram Login |
|---|---|---|
| Naturaleza | **De producto** — un paso más de onboarding | **Arquitectónica** — desaparecen `mentioned_media`, `mentioned_comment`, hashtag search y `ads_management` |
| ¿Mitigable? | **Sí.** Se guía al cliente a vincular la Página; la mayoría de cuentas Business ya la tienen vinculada | **No.** No hay rodeo de ingeniería, y la migración inversa no está documentada |
| ¿Reversible? | Sí — migración documentada hacia Instagram Login | No documentada |

**Una fricción de onboarding mitigable no se compra con el diferenciador del producto.** El ruling es Facebook Login.

**Requisito de producto que se deriva, no opcional:** como la Página vinculada es ahora precondición dura, el flujo de W2 debe **detectarla y guiar su vinculación antes de lanzar OAuth**, no descubrir que falta a mitad del grant. Es exactamente el patrón de §6.4: **el gate de plataforma se modela como dato del que la UI lee**, nunca como un 403 en tiempo de ejecución.

### 7.4 Consecuencias para lo ya escrito

1. **El vocabulario de scopes cambia entero.** La vía es `instagram_basic` / `instagram_content_publishing` / `instagram_manage_comments` / `instagram_manage_messages` / `instagram_manage_insights` (+ `pages_read_engagement`, `pages_show_list`), **no** la familia `instagram_business_*`. Todo W2/W3/W4 y `oauth_scope.py` deben revisarse contra esta lista. **`oauth_scope.py` no es mío** — se señala a quien lo posea.
2. **`social_connections.linked_page_id` (§2.2) deja de ser `[V]` opcional y pasa a ser obligatorio.**
3. **La ortografía del scope de publicación sigue SIN resolver** y el corpus la empeora: `app-review.md:39` dice `instagram_content_publishing` mientras `overview.md:88` dice `instagram_content_publish`. Con las variantes de la vía Instagram Login son **cuatro** grafías en circulación. **Se mantiene la regla de `pipeline`: no hardcodear ninguna desde documentación; resolver empíricamente contra el endpoint de autorización y registrar la respuesta como autoridad.**
4. **`story_insights` y las métricas agregadas (`total_comments`, `total_likes`, `total_views`) son exclusivas de Facebook Login** (`insights.md:44`, `insights.md:50`) — refuerzo adicional del ruling, encontrado después de tomarlo.
5. **Contradicción de Meta consigo misma, registrada:** `app-review.md` **omite `instagram_business_manage_insights`** de la lista de la vía Instagram Login, pero `insights.md:24` lo documenta como existente para esa vía. No cambia el ruling (insights está en ambas); sí confirma que **las listas de `app-review.md` no son exhaustivas** y no deben usarse como negativa concluyente sobre un permiso concreto.

### 7.5 Corrección de un error mío que se propagó al backlog — el límite de publicación

`pipeline` lo detectó en `DISCREPANCIES.md` §2 y tiene razón. Mi §3.1 dijo *"100 posts por API en ventana de 24 h (50 si son carruseles)"*, y `po` lo copió a `backlog-crm-workflows.md`. **Está mal, y en la dirección peligrosa.**

Son **dos contadores distintos**, no dos casos de uno:

- **100** cuenta **posts publicados**; un carrusel es **un** post (`content-publishing.md:61`).
- **50** cuenta **contenedores IG** (`.../ig-user/content_publishing_limit.md:47`), y un carrusel necesita **un contenedor por ítem más el contenedor del carrusel**.

Luego un carrusel de 10 imágenes es **1** post contra el límite de 100 y **11** contenedores contra el de 50. **Los carruseles son más caros bajo la restricción que ata, no más baratos** — mi redacción invertía el sentido. El origen del error: resumí dos cifras de una misma lectura y las reconcilié inventando un caso especial en vez de comprobar que medían cosas distintas.

**Regla, siguiendo a `pipeline`: no hardcodear ninguno de los dos números.** Leer `GET /<IG_ID>/content_publishing_limit` en ejecución — devuelve `quota_total`, `quota_duration` y `quota_usage`, y ambas cifras en prosa están marcadas *"currently"*. Para el volumen de cliente cero (1–3 posts/día) no ata ninguna; ata en cuanto haya programación o multi-cuenta.

### 7.6 Límite que ADR 21 debe declarar, con la formulación del lead

> **El acceso estándar está probado como libre-de-revisión; NO está probado como funcionalmente completo para publicar.**

`overview.md:43`: *"because of the limited scope of Standard Access, some features might not work properly until your app has been granted Advanced Access."* Es una salvedad del propio Meta, **inespecífica y no testeable desde la documentación**. ADR 21 y la reclasificación de §3.6 se apoyan en el acceso estándar, así que el límite va **dentro de la ADR**, no sólo en la nota de §6.1. **Resolución honesta: una prueba empírica contra una cuenta real** — tarea del fundador, no de documentación.

---

## 8. Los términos de Meta en lenguaje llano — sección escrita PARA EL FUNDADOR

**Estado:** EN CURSO (`principal-architect`, 2026-07-30). Encargo del fundador: *"lo que quiero es entender los términos y condiciones"*. **Esto es una sección de comprensión, no de decisión.** No hay nada que firmar aquí. Se puede leer de una pasada sin abrir el documento original de Meta.

**Fuente única de las citas de esta sección:** [Meta Platform Terms](https://developers.facebook.com/terms/dfc_platform_terms/), accedidas 2026-07-29 / 2026-07-30. Cada obligación lleva su número de sección para que se pueda comprobar.

### 8.0 El modelo mental, en cinco líneas

Si sólo se lee esto, es suficiente para tener el modelo correcto:

1. **Hay DOS regímenes, no uno, y se confunden con facilidad.** Uno es el **gate administrativo** (niveles de acceso, App Review, Business Verification, App Mode): decide **qué puede hacer técnicamente la app y a quién puede pedirle permisos**. El otro son las **Platform Terms**: un contrato que decide **qué podemos hacer con los datos**. Pasar el primero no es cumplir el segundo, y estar exento del primero **no exime del segundo**.
2. **Somos Tech Provider desde el primer cliente**, no desde el cliente número diez. La definición de Meta cubre *"a single integration on behalf of an individual client"*. Con eso se activa la sección §5.b entera.
3. **"Platform Data" incluye lo derivado.** Un score, un sentimiento, un embedding o un resumen de IA calculado sobre un DM **sigue siendo dato de Meta**. No se sale del contrato transformando el dato.
4. **La arquitectura ya cumple lo difícil; falta lo fácil.** El aislamiento entre clientes, la custodia de tokens y la mecánica de borrado están **bien resueltos por diseño** (§8.3.1). Lo que falta son cinco piezas de superficie: una política de privacidad, un endpoint de borrado, una política de retención, un canal de vulnerabilidades y una cláusula en nuestros términos de servicio (§8.3.2).
5. **Hay una cláusula que sí es un problema de producto, no de cumplimiento, y es del cliente uno:** §3.a.ii prohíbe usar datos de Meta para **determinaciones de elegibilidad sobre personas, y nombra explícitamente la vivienda** (§8.3.3). No invalida el producto, pero sí condiciona qué puede hacer el scoring en el vertical inmobiliario, y es decisión del fundador, no de ingeniería.

**Lo que NO hay que hacer con esta sección:** tratarla como una lista de tareas de última hora antes del App Review. El disparador de las obligaciones es **que alguien ajeno use el producto**, y eso —por la reclasificación de ADR 21— ocurre **antes** de cualquier trámite ante Meta (§8.6).

### 8.1 Las cinco definiciones que gobiernan todo, literales — **cierra V-TP-3**

En ADR 29 marqué estas definiciones como **[P] parafraseado** porque el primer intento de extracción las resumió. Aquí van **literales, en inglés, del glosario oficial** (accedido 2026-07-30 con el locale forzado a `en_US`; la versión en español de Meta existe y es igual de oficial, pero traduce los términos y eso arruina la precisión que se busca en un glosario).

| Término del glosario | Definición literal |
|---|---|
| **Tech Provider** | *"A Developer of an App whose primary purpose is to enable Users thereof to access and use Platform or Platform Data."* |
| **Client** | *"The User of a Tech Provider's App."* |
| **Service Provider** | *"An entity you use to provide you services in connection with Platform or any Platform Data."* |
| **App** | *"Any technical integration with Platform or to which we have assigned an App identification number. **Any code, APIs, SDKs, tools, plugins, bots, websites, applications, specifications, and other technology made available by you or on your behalf** in connection with Platform is considered part of your App."* |
| **Platform Data** | *"Any information, data, or other content you obtain from us, through Platform or through your App, whether directly or indirectly and whether before, on, or after the date you agree to these Terms, **including data anonymized, aggregated, or derived from such data**."* |

**Tres precisiones que salen de tener el literal delante y que cambian cosas:**

1. **El término del glosario es "Tech Provider", no "Technology Provider".** Es el mismo concepto, pero al citarlo en cualquier acuerdo o correspondencia con Meta hay que usar la grafía del glosario. (Corrección a mi propio texto en ADR 29, que usa las dos.)
2. **"App" es mucho más ancha de lo que suena, y esto sí nos afecta.** No es "el registro en el App Dashboard": es *"any code… tools… bots, websites, applications… made available by you or on your behalf"*. Es decir, **la app de Meta de Qualify incluye a Qualify entero** — la UI de Reflex, los workers de Celery, los prompts, todo lo que toque la plataforma. Consecuencia práctica: cuando los términos dicen *"tu App"*, no hay una frontera cómoda donde escudarse; lo que hagamos en el pipeline es conducta de la App.
3. **"Platform Data" incluye explícitamente lo derivado, lo agregado y lo anonimizado.** Esto es lo más importante de las cinco definiciones para Qualify y es fácil de pasar por alto: **un embedding, un sentimiento, una señal tipada o un resumen de LLM calculado sobre un DM de Instagram sigue siendo Platform Data.** No se "sale" de los términos por transformarlo. Toda la capa de señales de la Fase 3 sobre datos de cuentas conectadas nace dentro de este régimen. (Nótese que esto **no** afecta al plano *earned* de scraping, que no viene de la plataforma vía App.)

**Tres definiciones más, del mismo glosario, que cierran la cadena:**

| Término | Definición literal |
|---|---|
| **User** | *"the end user of an App (whether a person or an entity)"* |
| **Developer** | *"the person or entity that creates or operates an App"* |
| **Platform** | *"the set of APIs, SDKs, tools, plugins, code, technology, content, and services that enables others…"* (entrada truncada en la extracción — ver el aviso de §8.6) |

**Esto resuelve la cadena de figuras sin ambigüedad:** *Client* = *User* de la app de un Tech Provider, y *User* puede ser **una persona O UNA ENTIDAD**. Luego **la inmobiliaria, como negocio, es un *Client* perfectamente bien formado** — no hace falta forzar nada, y la relación de §5.b encaja de forma natural. (Corrijo aquí una lectura mía anterior de esta misma sección, que dijo que *Client* era necesariamente una persona: la definición de *User* dice explícitamente lo contrario.) Donde sí hay un hueco no es en **quién** es el Client, sino en la confusión entre el gate administrativo y las obligaciones contractuales — **§8.6**.

### 8.2 El mapa de obligaciones, en lenguaje llano

Cuatro grupos. Cada fila lleva su sección para poder comprobarla, pero está redactada para entenderse sin abrir el original. **He marcado con 🔴 las que tienen consecuencia real para Qualify y con ⚪ las que se cumplen solas o son burocracia de fondo.** No están todas las obligaciones del documento: están las que muerden.

#### (A) Lo que Qualify DEBE HACER

| | Obligación, en llano | §|
|---|---|---|
| 🔴 | **Tener una política de privacidad pública**, accesible, no geobloqueada, que explique qué datos tratamos, para qué, y cómo pedir su borrado | 4.a, 4.b |
| 🔴 | **Dar un mecanismo accesible para que una persona pida el borrado de sus datos**, y borrarlos cuando lo pida | 3.d.i.1 |
| 🔴 | **Borrar los datos cuando dejen de ser necesarios** para un propósito legítimo, cuando dejemos de operar el producto, cuando Meta lo pida para proteger a un usuario, o cuando el usuario pierda acceso a su cuenta | 3.d.i.2.a–e |
| 🔴 | **Tratar los datos sólo como diga nuestra política de privacidad.** La política no es un trámite: es el límite de lo que legalmente podemos hacer con los datos | 4.c |
| 🔴 | **Como Tech Provider: mantener una lista actualizada de Clients con sus datos de contacto**, y entregarla a Meta si la pide | 5.b.ii.3 |
| 🔴 | **Medidas de seguridad administrativas, físicas y técnicas** a la altura del estándar de la industria | 6.a.i |
| 🔴 | **Un canal accesible para que alguien nos reporte una vulnerabilidad**, y corregir lo que reporte | 6.a.ii |
| 🔴 | **Notificar a Meta** —por su formulario— cualquier tratamiento no autorizado de datos o incidente de seguridad, empezar la remediación de inmediato y cooperar | 6.b.i, 6.b.ii |
| ⚪ | Cooperar con revisiones de cumplimiento y con la **monitorización periódica** que Meta hace de la app | 7.a, 7.b |
| 🔴 | **Cooperar con auditorías de Meta, dando acceso a nuestros sistemas y registros**; corregir lo que revele; y **reembolsar a Meta el coste de la auditoría si encuentra incumplimiento** | 7.c.iii–vi |
| ⚪ | Mantener el contacto de la cuenta de la app al día | 8 |
| ⚪ | Si hay transferencia de datos al EEE/UK, aplicar las medidas técnicas y organizativas de Meta | 10A.d, 10B.c.iii |
| 🔴 | **No transferir derechos ni obligaciones sin consentimiento de Meta — y eso incluye fusiones y adquisiciones** | 11.a |

#### (B) Lo que Qualify NO PUEDE HACER

| | Prohibición, en llano | §|
|---|---|---|
| 🔴🔴 | **Tratar datos de plataforma para tomar determinaciones de elegibilidad sobre personas, incluida la VIVIENDA.** Literal: *"Processing Platform Data to make eligibility determinations about people, including for **housing**, employment, insurance, education opportunities, credit, government benefits, or immigration status."* Aplica a **todo** Platform Data, no a un subconjunto. **Ver §8.3, es el hallazgo más serio de esta sección** | 3.a.ii |
| 🔴 | **Tratar datos para discriminar** o fomentar discriminación que perjudique a personas por raza, etnia, color, origen nacional, religión, edad, sexo, orientación sexual, identidad de género, **situación familiar**, discapacidad, condición médica o genética, o cualquier otra categoría protegida | 3.a.i |
| 🔴 | **Construir o enriquecer perfiles de usuario sin consentimiento válido del usuario**, para cualquier propósito. Literal: *"Processing Platform Data without valid User consent in order to build or augment user profiles for any purpose."* | 3.a.v |
| 🔴 | **Vender, licenciar o comprar Platform Data** | 3.a.iv |
| ⚪ | Tratar datos para vigilancia o para fines policiales | 3.a.iii |
| 🔴 | **Descodificar, sortear, re-identificar, des-anonimizar o hacer ingeniería inversa** sobre Platform Data | 3.a.vi |
| 🔴 | **Cambiar la función principal de la app o el alcance del tratamiento de datos sin volver a pasar App Review** | 3.a.vii |
| 🔴 | **Tratar datos para fines que no estén entre los usos permitidos** en la documentación de Meta | 3.a.viii |
| 🔴 | **Compartir datos con terceros sin salvaguardas contractuales** | 3.c.iv.4 |
| ⚪ | Pedir o recoger por separado las credenciales de login de Meta de un usuario | 6.a.iii |
| 🔴 | **Transferir, compartir o solicitar identificadores de usuario de Meta, access tokens o app secrets** — con una única excepción: el Service Provider que nos ayuda a desarrollar u operar la app | 6.a.iv |
| ⚪ | Vender, transferir o sublicenciar la Plataforma | 2.a |

#### (C) Lo que Qualify DEBE GARANTIZAR (declaraciones y garantías)

| | En llano | §|
|---|---|---|
| 🔴 | Que **hemos obtenido todos los consentimientos, permisos y avisos** necesarios para el contenido que compartimos | 2.b.i.1 |
| 🔴 | Que el tratamiento de datos **coincide con lo que dice nuestra política de privacidad** | 4.c |
| 🔴 | Que los datos que **retenemos** cumplen la ley aplicable | 3.d.i |
| ⚪ | Que tenemos los derechos necesarios sobre el contenido de la app | 2.c.ii |
| ⚪ | **Certificar por escrito a Meta, si lo pide, que cumplimos** los términos y que el propósito para el que pedimos datos es conforme | 7.d |
| ⚪ | Que quien acepta en nombre de una entidad tiene poder para obligarla | 1.d |

#### (D) Lo que Qualify DEBE TENER POR ESCRITO con terceros

**Ésta es la categoría que el fundador entendió como "papeleo" y no lo es.** Ninguna de estas filas es RUT, dominio ni Business Verification: son **cláusulas en contratos**, no trámites ante un registro.

| | Con quién, y qué | §|
|---|---|---|
| 🔴 | **Con cada Service Provider (proveedor que trata datos por cuenta nuestra): un acuerdo escrito, ACEPTADO ANTES de usarlo**, por el que se compromete a usar los datos sólo para el servicio que le pedimos y **no para sus propios fines** | 5.a.i.1 |
| 🔴 | Que sus **sub-proveedores** queden obligados por escrito a lo mismo | 5.a.ii, 5.a.i.2 |
| 🔴 | Que **cesen el uso y borren los datos** cuando termine la relación | 5.a.iii |
| 🔴 | Poder **entregar a Meta la lista de proveedores y sub-proveedores** cuando la pida, con prueba de esos acuerdos | 5.a.iv |
| 🔴🔴 | **Como Tech Provider: prohibir CONTRACTUALMENTE a cada Client que viole los términos o las políticas de Meta.** Es decir: **nuestros propios Términos de Servicio con cada tenant deben incluir esa cláusula.** No es papeleo externo — es una línea en nuestro contrato de cliente | 5.b.ii.4.a |
| 🔴 | **Instrucción escrita expresa del Client** para compartir sus datos con un proveedor del propio Client | 5.b.ii.4.d |
| ⚪ | Un proceso escrito de notificación y retirada para reclamaciones de infracción sobre contenido de usuario | 2.c.iii |

#### (E) Qué pasa si esto termina

- Al terminar, **todos los derechos cesan de inmediato** y hay que dejar de usar la Plataforma (§11.h).
- **Sobreviven a la terminación** las secciones 2.b, 2.c, 3, 4, 5, 6, 7, 9, 10, 10A, 11 y 12 — es decir, **las obligaciones de datos, seguridad y auditoría no se extinguen con el contrato** (§11.h).
- El **derecho de auditoría de Meta sobrevive un año** después de que dejemos de tratar Platform Data, y **hasta que hayamos borrado afirmativamente todas las copias** (§7.c.vii). Traducción práctica: **borrar de verdad es lo que cierra la ventana de auditoría.** Guardar "por si acaso" la alarga.

### 8.3 Qué ya cumplimos y qué no — **verificado contra el repo el 2026-07-30**, no supuesto

#### 8.3.1 Lo que ya cumplimos, y en tres casos por diseño

| Obligación | Estado | Evidencia en el repo |
|---|---|---|
| §5.b.ii — *"Platform Data de un Client independiente del de otros Clients"* | ✅ **Cumplido estructuralmente** | RLS de ADR 24 en las 7 políticas + `UNIQUE(id, tenant_id)` con FK compuesta (R2) → un tenant cruzado es **inconstruible**, no sólo prohibido |
| §6.a.iv — no compartir access tokens ni app secrets | ✅ **Cumplido estructuralmente** | GRANTs a nivel de columna (R3): `qualify_app` **nunca** recibe `SELECT` sobre `oauth_credentials.ciphertext`; sólo el rol estrecho `qualify_credential` lo lee. Y `platform_apps.secret_ref` guarda una **referencia**, nunca el secreto |
| §3.d.i.2 — borrar datos cuando haga falta | ✅ **Mecánica ya resuelta** | El keying de R2 de la Parte 4 es `t/{tenant_id}/fp/{platform}/{connection_id}/{object_id}` → el borrado de un tenant es un **delete-by-prefix**. `packages/scraper/src/qualify_scraper/shared.py:252-262` lo documenta explícitamente |
| §5.b.ii.6 — cortar a un Client si Meta lo pide | ✅ **Existe** | `packages/api/src/qualify_api/connections/revoke.py` (idempotente), publicado en el seam de `connections/__init__.py` |
| §5.b.ii.3 — lista de Clients | 🟡 **Parcial** | Existe `tenants` (`name`, `country`, `timezone`, `currency`) y el contacto se alcanza vía `tenant_members` → `users.email`. **No hay un contacto de facturación/responsable en `tenants`**; hoy es una consulta, no un campo |
| §7.b — cooperar con monitorización | ✅ Nada que construir | `connection_events` es auditoría append-only |

> **Corrección a `CLAUDE.md`, verificada hoy:** `CLAUDE.md` afirma en la sección de estado del Sprint 1 que *"`revoke_connection` service — does not exist; C-06 needs it"*. **Eso está obsoleto**: `packages/api/src/qualify_api/connections/revoke.py` existe desde el 2026-07-28. La regla de la casa aplica —el sistema de ficheros es la verdad, los docs describen el estado objetivo— y esta fila es un ejemplo de por qué.

#### 8.3.2 Lo que hoy NO cumplimos. Cinco huecos, y ninguno es difícil

Ninguno bloquea a cliente cero (la exención de rol nos cubre mientras la app la use sólo el fundador). **Los cinco vinculan en cuanto haya un Client de verdad**, es decir en el mismo envío de App Review.

| # | Hueco | § | Estado verificado | Coste |
|---|---|---|---|---|
| 1 | **No hay política de privacidad.** Ninguna URL, ni en `config.py` ni en ningún sitio del repo | 4.a, 4.b, 4.c | `grep` sobre `packages/`, `Qualify/`, `migrations/`: **cero** ocurrencias | Bajo, pero **es un entregable del App Review**, no opcional |
| 2 | **No hay mecanismo de borrado para el usuario final**, ni endpoint de *data deletion callback*, ni endpoint de *deauthorize* | 3.d.i.1 | **cero** ocurrencias de `deauthorize` / `data_deletion` / `deletion_callback` | Bajo — la mecánica de borrado ya existe (delete-by-prefix); falta la **puerta** |
| 3 | **No hay política de retención.** Nada decide cuándo un dato "deja de ser necesario" | 3.d.i.2.a | **cero** ocurrencias de `retention` / `ttl` / `purge` en `packages/` | Bajo en código, **decisión de producto** en realidad |
| 4 | **No hay canal de reporte de vulnerabilidades.** No existe `SECURITY.md` ni `.well-known/` | 6.a.ii | verificado por `ls` | Trivial |
| 5 | **Nuestros Términos de Servicio con el tenant no existen**, luego no pueden contener la cláusula que §5.b.ii.4.a exige (prohibir contractualmente al Client violar los términos de Meta) | 5.b.ii.4.a | no hay ToS en el repo | Bajo — **una cláusula**, no un contrato nuevo |

**El patrón que conviene ver:** los cinco huecos son de **superficie de cumplimiento** (una URL, un endpoint, un fichero, una cláusula), no de arquitectura. La arquitectura ya está bien: el aislamiento, la custodia y la mecánica de borrado se construyeron correctos por diseño. **Es la mejor forma posible de que aparezca esta lista.**

#### 8.3.3 🔴🔴 El hallazgo serio, y es de producto, no de cumplimiento: §3.a.ii dice **housing**

Éste no es un hueco que se tape con un fichero. **El cliente uno es una inmobiliaria**, y §3.a.ii prohíbe literalmente:

> *"Processing Platform Data to make eligibility determinations about people, including for **housing**, employment, insurance, education opportunities, credit, government benefits, or immigration status."*

Y aplica a **todo** Platform Data — que por §8.1 incluye **lo derivado**: un score, una señal tipada, un sentimiento o un resumen calculado sobre un DM de Instagram sigue siendo Platform Data.

**Lo que hay que separar con cuidado, porque la respuesta no es "esto es ilegal":**

| Uso | Lectura |
|---|---|
| Priorizar a qué lead llamar primero, resumir su conversación, redactar un borrador de respuesta | **Fuera del ámbito de §3.a.ii en mi lectura.** No es una determinación sobre la *elegibilidad* de la persona; es gestión de la cola de trabajo del vendedor |
| Puntuar leads y usar ese score para decidir **a quién se le muestra una vivienda, a quién se le contesta y a quién no** | **Aquí es donde se cruza.** Deja de ser priorización y empieza a parecer una determinación sobre la persona respecto de una vivienda |
| Que el score se calcule con señales correlacionadas con atributos protegidos —nombre, barrio, forma de hablar, foto— | **Aquí además entra §3.a.i** (situación familiar y origen nacional están nombrados). Y un modelo no necesita recibir el atributo protegido para acabar usándolo |

**Tres consecuencias que sí son accionables hoy:**

1. **La Fase 4 (scoring de leads/creadores) y la Fase 5 (plays de activación) heredan una restricción que el mapa de fases no registra**, y la heredan **sólo en el vertical inmobiliario**, que es justo el del cliente uno. No es un problema de la Fase 1.
2. **§3.a.v muerde antes que §3.a.ii y es más fácil de incumplir sin darse cuenta:** *"Processing Platform Data without valid User consent in order to build or augment user profiles for any purpose."* El `crm.creators` de la Fase 4, con centroides de embeddings de contenido, **es literalmente construcción de perfiles**. Sobre el plano *owned*, la persona que manda un DM consintió ante **Meta**, no ante nosotros. **Ese consentimiento hay que tenerlo o no se puede perfilar.** Sobre el plano *earned* (scraping) la aplicabilidad es discutible porque el dato no viene de la Plataforma vía App — **y eso es una ambigüedad, no una vía libre; ver §8.6**.
3. **Hay un problema de óptica, independiente del fondo jurídico, y conviene decirlo:** el producto se llama **Qualify** y su promesa es *qualification/scoring*. Presentar a App Review una app llamada Qualify, que puntúa personas, para un cliente inmobiliario, invita exactamente a la pregunta de §3.a.ii. **Puede ser perfectamente conforme y aun así costar un ciclo de revisión** por cómo se lee. Merece pensarse cómo se describe la app en el envío.

**Calibración, con el mismo estándar que usé en la variante B: esto es una LECTURA, no un veredicto.** La cláusula es literal y verificada; la aplicación a un CRM de ventas inmobiliarias es **interpretación mía**, y no la resuelvo por inferencia. Lo que la resolvería: **una decisión de alcance del fundador** (que el scoring nunca alimente decisiones de acceso a vivienda, y que se documente así) **o asesoría legal**. Lo que **no** debe pasar es que llegue al backlog de la Fase 4 como si nadie lo hubiera visto.

### 8.4 El "papeleo" que el fundador descartó: ¿nos obliga hoy el par §6.a.iv / §5.a.i?

**Respuesta corta: no es el papeleo que él pensaba, no es un no-issue, y ya aplica hoy — pero se cumple eligiendo proveedores, no rellenando formularios.**

**Primero, qué NO es.** El fundador interpretó "acuerdo escrito de Service Provider" como **RUT + dominio + Business Verification**. No tiene nada que ver: eso son trámites ante Meta para subir de nivel de acceso. §5.a.i es **una cláusula en el contrato con un proveedor nuestro**. Son ejes distintos y descartar uno no descarta el otro.

**Segundo, a quién obliga exactamente.** El par funciona así:

- **§6.a.iv** nos prohíbe compartir identificadores de usuario de Meta, access tokens y app secrets — **con una excepción**: el *Service Provider* que nos ayuda a desarrollar u operar la app.
- **§5.a.i** dice que si usamos un Service Provider, **tiene que haber aceptado por escrito, ANTES de usarlo**, que usará esos datos sólo para el servicio que le pedimos y **nunca para sus propios fines**.

Es decir: §6.a.iv abre la puerta y §5.a.i pone la condición de la puerta. **La obligación se dispara por tener proveedores que tocan datos, no por vender a nadie.**

**Tercero, y esto es lo que hay que saber: ya aplica hoy.** Qualify ya tiene o va a tener proveedores que tratan Platform Data:

| Proveedor | ¿Toca Platform Data? | ¿Es Service Provider? |
|---|---|---|
| **Cloudflare R2** | Sí — guarda los payloads crudos de primera parte (`t/{tenant_id}/fp/…`) | **Sí** |
| **Hetzner VPS** | Sí — aloja el Postgres donde vive `oauth_credentials` | **Sí** |
| **HF Inference Providers / featherless-ai** | Sí, en cuanto la Parte 4 lea contenido: recibe frames, audio y texto | **Sí** |
| **Proveedor de LLM** (LangGraph, respuestas asistidas) | Sí — recibe el contenido de los DMs | **Sí** |
| **Zyte** | Plano *earned*; **discutible** — ver §8.6 | Ambiguo |

**Y aquí está la parte tranquilizadora, que es real:** el "acuerdo escrito" **no se negocia uno a uno**. Se cumple con el **DPA / los términos de tratamiento de datos que el propio proveedor publica** — Cloudflare, Hetzner y Hugging Face los tienen. Es el mecanismo estándar con el que cumple cualquier SaaS. Luego la obligación práctica se reduce a tres cosas:

1. **Usar proveedores que tengan DPA** (los cuatro de arriba lo tienen).
2. **Mantener la lista**, porque §5.a.iv obliga a entregarla a Meta si la pide. Hoy no existe esa lista; es un fichero, no un proyecto.
3. **No inventar un camino de datos hacia algo que no tenga DPA.** Ésta es la única de las tres que se puede incumplir por accidente.

**Cuarto — el caso concreto que el lead señala, y sí activa la cláusula: el SaaS inmobiliario que el fundador construye y administra.**

Ese sistema es **un tercero a efectos de estos términos**, aunque lo escriba la misma persona. Los términos no conocen "la misma persona": conocen entidades y sistemas. Dos escenarios:

- **Si el SaaS inmobiliario NUNCA recibe datos de Meta ni credenciales** → la cláusula no se activa y no hay nada que hacer. Es el escenario limpio, y es el que ya anticipa §3.7 punto 1 (*"la app de Meta se registra bajo el portfolio del fundador, nunca bajo el de PuntoServis; sin integración, sin export, sin cuenta compartida"*). **Recomendación: mantenerlo así por defecto.**
- **Si en algún momento se le pasan datos** —un lead, un resumen de conversación, un contacto extraído de un DM— **la cláusula deja de ser teórica**, y hay **dos rutas sancionadas, no una**:
  - tratarlo como **Service Provider nuestro** (§5.a.i): acuerdo escrito previo, sólo para el servicio pedido, nunca para sus fines; o
  - **la ruta más limpia, y existe exactamente para esto:** el SaaS inmobiliario es **el proveedor del propio Client**, y **§5.b.ii.4.d** permite compartir con él mediando **instrucción escrita expresa del Client**. Como el Client es la inmobiliaria, basta que la inmobiliaria lo pida por escrito.

**Ruling: no es un bloqueo, es un camino con nombre.** Lo que no vale es el camino intermedio —pasar datos porque es la misma persona y no consta en ningún sitio—, que es precisamente lo que §3.c.iv.4 (compartir con terceros sin salvaguardas contractuales) prohíbe.

**Un cabo suelto declarado:** no he verificado si el SaaS inmobiliario **hoy** toca credenciales o datos de plataforma. No es una pregunta de ingeniería sobre este repo — no hay ningún camino de datos hacia él en el código (verificado: cero referencias). Es una pregunta para el fundador sobre el otro sistema.

### 8.5 ¿Los programas de partner cambian alguna obligación o algún gate?

**Respuesta: no. Son comerciales; no tocan ni el régimen de obligaciones ni el gate de acceso.** El fundador pregunta esto porque Zernio se declara partner de Meta y de TikTok.

Lo que sostiene la respuesta, por mi lado (el de los términos):

1. **Las Platform Terms no condicionan nada a un estatus de partner.** Las obligaciones se enganchan a dos figuras: *Developer* y *Tech Provider*. Recorridas las secciones 1–11, **ningún deber se activa, se relaja ni se exime por pertenecer a un programa**. Un partner de Meta tiene exactamente las mismas obligaciones de §3, §4, §5, §6 y §7 que nosotros.
2. **El gate de acceso tampoco se mueve.** Lo que gobierna el acceso es el par (nivel de acceso, permiso) más el App Mode, y las exenciones se definen sobre *rol en la app* o *rol en un Business que ha reclamado la app* (§3.1 y su corrección). **Ser partner no es ninguna de esas dos cosas.**
3. **La única "designación" que sí concede algo técnico no es un programa de partner: es ser Tech Provider**, que habilita los tokens BISU (*"Tech Providers only"*, ADR 29 §5.2). Y eso no se solicita ni se gana — **Meta te clasifica así por lo que hace tu app**, según el cuestionario de Data Access Renewal.
4. **El único contraste de figuras que encontré en doc primaria es de facturación, no de acceso:** en el corpus de WhatsApp, la diferencia entre *Tech Provider* y *Solution Partner* es si necesitas línea de crédito y facturar a tus clientes el uso de la API. **Marcado [S]** — viene del corpus de WhatsApp y no he verificado que se generalice a Instagram.

**Traducción para el fundador: que Zernio se anuncie como partner de Meta no significa que tenga una puerta que nosotros no tengamos.** Significa que está en un programa comercial. La puerta que sí importa —Advanced Access sobre los permisos que necesita— la pasó por App Review, igual que tendremos que pasarla nosotros.

#### 8.5-bis Actualización 2026-07-30 — el pendiente se cierra, y la premisa de la pregunta era inexacta

Tres datos de `gtm-accessmodel` ([P], accedidos 2026-07-30), y los tres apuntan en la misma dirección que la respuesta de arriba.

**(1) El status formal de Tech Provider **exige** el trámite completo; es su resultado, no un atajo.** [P] [Get Started for Tech Providers](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers): concede *"Advanced access to `whatsapp_business_messaging`"* y *"…`whatsapp_business_management`"*, y exige verificación del negocio + App Review, con la frase que fija el orden: *"**Your business must be verified before you can start the app review process.**"*

> **Esto es lo más útil de los tres para el fundador: no existe la ruta "hazte partner o Tech Provider para ahorrarte la revisión".** El status llega **después** de la revisión. Cualquier plan que dependa de conseguirlo antes está mal ordenado.
>
> (Nota técnica, no de comprensión: esto pone en tensión la *etapa 0-bis* de ADR 29 — mi afirmación de que el flujo BISU se puede probar antes del trámite. Registrada como tensión sin resolver y como **V-TP-7** en `arquitectura.md` §6 apartado (j); **no afecta al ruling de ADR 29**, sólo a su calendario.)

**(2) El otro programa —Meta Business Partner— sí es esencialmente un badge.** [P] [Meta Business Partner Program Policies](https://www.facebook.com/business/marketing-partners/become-a-partner/fmp-product-policies): único requisito explícito, *"todos los participantes del Programa deben tener un negocio verificado"*. El documento **no menciona** App Review, niveles de acceso, permisos, cuotas ni tipos de token; su contenido son obligaciones, uso del badge/logo, confidencialidad y *Advertiser Rewards*. **Ausencia registrada como ausencia** (es gtm quien la registra así, y es la forma correcta). **Confirma el punto 1 de §8.5 desde el lado del programa: pertenecer no mueve el régimen de acceso.**

**(3) Y la premisa de la pregunta era inexacta — esto conviene decírselo al fundador tal cual: Zernio casi no se declara partner.** Cero ocurrencias de *partner*, *badge*, *certified* o *Tech Provider* en su home, en `zernio.com/social-media-api`, en 25 KB de su documentación de API y en su página de WhatsApp. Su única declaración está en una FAQ **de su propio blog** [S] y es **de publicidad**: *"Zernio is an approved Meta Marketing Partner, so its Ads API lets you create, pause, edit, and delete Meta campaigns"*. **La lista amplia que circula —"partner oficial de Meta, TikTok, LinkedIn, Pinterest, X"— sale de una reseña de un tercero, no de Zernio.**

**Y el remate, que es la mejor evidencia posible de toda esta sección:** el acceso de Zernio a publicación y mensajería de Instagram está **probado por su propia documentación técnica, sin depender de ningún partnership**. Es decir: un competidor vivo, con acceso demostrado, y **cuya única declaración de partner es sobre otra superficie (ads)**. Si el partnership fuese la llave del acceso, ahí se vería. No se ve.

**Pendiente que se cierra como NO VERIFICABLE, no como no verificado:** el **Meta Business Partner Directory exige login** (`facebook.com/business/partner-directory/search` → *"Debes iniciar sesión para continuar"*, incluso con user-agent de navegador). Consecuencia de campo que merece registrarse: **la afirmación de partner de un proveedor no es verificable de forma anónima por un comprador.** Ni el *"Meta Business Partner"* de ManyChat ni el *"approved Meta Marketing Partner"* de Zernio pudieron confirmarse ni desmentirse. **Queda como límite del método, no como hecho en ninguna dirección** — y refuerza la cautela ya registrada: ManyChat se declara Meta Business Partner y **no** aparece en la lista oficial de Messaging Partners de TikTok pese a integrarlo (`ingenieria-inversa-manychat.md` §2.4).

### 8.6 La pregunta que no formuló: ¿cambian los términos si el Client es un negocio que administra el propio proveedor?

**Respuesta: los términos NO cambian, y no hacía falta que cambiaran — pero hay un vacío real, y no está donde parecía.**

**Lo que NO es un problema, y conviene quitarlo de la mesa.** Cabía temer que administrar el stack del cliente uno colapsase las dos partes —proveedor y Client— en una sola, dejando sin sentido cláusulas que asumen dos partes (*"at the Client's request"*, *"contractually prohibit your Client"*, *"the Client's express written direction"*). **No colapsa.** La inmobiliaria es una entidad legal distinta, con su propio personal, y §8.1 confirma que *User* —y por tanto *Client*— puede ser *"a person or an entity"*. Que el fundador administre sus sistemas lo convierte en **su proveedor**, no en ella. Las cláusulas de §5.b siguen teniendo dos partes y siguen funcionando.

**Dónde SÍ está el vacío, y es exactamente el error que un fundador cometería.** Hay dos regímenes distintos, escritos en documentos distintos, que **describen la misma situación a la vez y nadie los reconcilia**:

| | Régimen del **gate administrativo** | Régimen de las **obligaciones contractuales** |
|---|---|---|
| Dónde vive | Developer Docs (Access Levels, App Review, App Modes) | Platform Terms §5.b |
| Qué dice del cliente uno | *"My app is only for a business I own **or manage**"* → acceso estándar → **App Review no requerido** | Una app que sirve a un *Client* → **eres Tech Provider** → §5.b entera te obliga |
| Qué pasa con el cliente uno | **Exento** | **Plenamente obligado** |

**El cliente uno satisface las dos descripciones al mismo tiempo, y nada dice que sean excluyentes.** La conclusión que se deriva es la que importa:

> **La exención es del TRÁMITE, no de las OBLIGACIONES.** No necesitar App Review no significa que las Platform Terms no apliquen todavía. Aplican desde el momento en que alguien que no eres tú usa la app — y la inmobiliaria son **agentes humanos**, no el fundador.

**Consecuencia concreta y accionable, que corrige la planificación:** los cinco huecos de §8.3.2 (política de privacidad, mecanismo de borrado, retención, canal de vulnerabilidades, cláusula en nuestros ToS) **no vinculan "cuando llegue el App Review". Vinculan cuando el primer agente de la inmobiliaria use el producto**, que por la reclasificación de ADR 21 es *ahora*, y que puede ocurrir **sin ningún trámite ante Meta**. Es decir: **el hito que activa las obligaciones llega ANTES que el hito que activa el papeleo**, y el mapa de fases no lo registra en ningún sitio.

Eso es el vacío, y merece nombrarse antes de firmar cualquier cosa, no después. **No es un incumplimiento hoy** —hoy sólo lo usa el fundador— pero el disparador está mucho más cerca de lo que sugiere "el reloj de 2-4 meses".

> **Confirmación desde un tercer sitio (2026-07-30) — y de paso resuelve una contradicción aparente del corpus.** `gtm-accessmodel` encontró dos textos de Meta que parecían decir cosas opuestas sobre el cliente único: el cuestionario de Data Protection Assessment dice *"Because this app allows people or businesses (clients) to access and use Platform Data, **it means that you are a Tech Provider**"* (basta **un** cliente), mientras que la tabla de App Review sólo exige Advanced Access para *"I am a Tech Provider and my app serves **multiple businesses**"* — **y no tiene fila para "Tech Provider con un solo cliente"**. **No se contradicen: gobiernan cosas distintas, y son exactamente los dos regímenes de esta sección.** El primero clasifica para **obligaciones**; el segundo para el **trámite**. Es decir, se puede ser Tech Provider a efectos de obligaciones —donde un solo cliente basta— sin disparar Advanced Access. La distinción de §8.6 no era una lectura forzada: es la que hace consistentes dos documentos de Meta que de otro modo se pelean.
>
> ⚠ **Pero el mismo hallazgo destapa un hueco en mi razonamiento, y es del fundador resolverlo (V-TP-8).** El cliente uno **no encaja en ninguna** de las dos filas de esa tabla: no es *"a business I own or manage"* y no es *"multiple businesses"*. Al comprobar por qué, aparece el defecto: sostuve que el fundador tiene *"full control of the client business"* de la inmobiliaria, apoyándome en que **construye y administra su SaaS**. **Administrar el stack de software de alguien no te hace admin de su Business Portfolio de Meta.** Son dos cosas distintas y he tratado una como la otra. **Pregunta concreta para el fundador: ¿eres admin del Business Portfolio de Meta de la inmobiliaria —de sus Páginas y su cuenta profesional de Instagram— o sólo administras su software?** Si es lo segundo, el cliente uno **no** está en el lado barato de la frontera, el default prudente es asumir que Advanced Access vincula, y la ventaja de secuenciación que celebré en §8.0 y en ADR 29 desaparece. **Es la verificación más barata de toda la lista y la que más cambia el calendario** — es la misma pregunta que §3.7 punto 2 ya dejó abierta para la tienda y que nadie hizo para la inmobiliaria. Detalle en `arquitectura.md` §6 enmienda 2026-07-29 apartado (j.8).

**Dos ambigüedades que dejo declaradas y NO resuelvo por inferencia:**

1. 🔴 **¿Los datos scrapeados son *Platform Data*?** Decide si todo el plano *earned* (ADR 18, Zyte, la Fase 1 entera) está dentro o fuera de este régimen — es decir, si §3.a.v (no perfilar sin consentimiento) alcanza al `crm.creators` construido sobre scraping. La definición de *Platform Data* es *"any information… you obtain from us, through Platform or through your App"*, y la de *Platform* incluye *"…technology, **content**, and services…"*. **La extracción de esa entrada me llegó truncada, y el extractor añadió por su cuenta que "no incluye los sitios web de Meta ni su contenido públicamente visible" — eso es lectura del extractor, NO texto de Meta, y no la adopto.** Con *"content"* dentro de la definición de *Platform*, la lectura de que scrapear el sitio público queda fuera **no está sostenida**. Lo que lo resolvería: la entrada completa de *Platform* verbatim (V-TP-6) y, si sigue ambigua, asesoría legal. **Lo que no vale es asumir que el plano earned está fuera porque nos conviene.**
2. **¿Se puede ser Tech Provider "de uno mismo"?** Si el único Client fuese una entidad del propio fundador, las cláusulas de dos partes quedarían vacías. **No es el caso del cliente uno** (la inmobiliaria es ajena) y por eso no bloquea nada, pero sí lo sería si el fundador constituyese una sociedad propia como tenant. Lo señalo para que no se descubra en ese momento.
