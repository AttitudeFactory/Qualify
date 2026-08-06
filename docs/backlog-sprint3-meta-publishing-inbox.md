# Backlog Sprint 3 — Publicación y bandeja de Meta sobre cuenta conectada

> 🔴 **ALCANCE SUPERADO EL 2026-08-05 — este documento es ahora REFERENCIA, no plan ejecutable.**
> El fundador rechazó **tanto la Forma A como la Forma B** de §6.3 y pidió un tercer corte: el mínimo demostrable.
> **El alcance vigente está en `docs/backlog-sprint3-mvp-demo.md` (Forma C — MVP demo, 9 items, una sola developer).**
> Lo que sigue siendo válido aquí y NO se ha duplicado allí: §1.3 (decisiones invalidadas — no reimplementar), §2 (verificación de código), §4 (épica B, aparcada al Sprint 4), §7 (parking lot con fase propietaria) y §8 (conflictos abiertos).
> Correcciones verificadas contra disco el 2026-08-05: **C0 está parcialmente obsoleto** (la suite offline corre 298/298), **A2 ya está resuelta** fuera de ingeniería, y **A6 se difiere salvo su núcleo**, que allí se llama `A6-min`. Detalle en §2 y §6.2 del fichero nuevo.

> **Estado: BORRADOR DE TRABAJO.** Nada aquí está `[APROBADO]` ni firmado. Ningún commit, ningún push.
> Autor: product-owner de la sesión `po-sprint3` (2026-07-31).
> Fichero de estado de la sesión: `.claude/sprint-state-2026-07-31-po-sprint3.md`.
> El sprint asume **Development Mode** y **no promete visibilidad pública** de los posts publicados.

## Índice

- §0 Encuadre y supuestos
- §1 Herencia: qué sobrevive de los backlogs previos
- §2 Verificación de código contra disco
- §3 Épica A — Publicación (ruta crítica)
- §4 Épica B — Bandeja de un solo canal
- §5 Épica C — Deuda y cumplimiento
- §6 Orden de ruta crítica y dimensionado
- §7 Parking lot (fuera de sprint, con fase propietaria y dependencia declarada)
- §8 Conflictos abiertos y decisiones que necesita el fundador
- §9 Prompt sugerido para `/team-dev`  ·  §9.1 variante para la Forma B

---

## §0 Encuadre y supuestos

**Objetivo del sprint:** cablear publicación y bandeja de Meta sobre la conexión de cuenta conectada que ya existe. Ordenado por **ruta crítica**: sin endpoint de publicación no hay producto que enseñar.

**Fase del mapa:** todo lo candidato a sprint es **Fase 1 Parte 4-A (publicación)** y **Fase 1 Parte 4-B (bandeja de un solo canal)**, por ADR 21 (firmada 2026-07-24). Nada de este sprint pertenece a Fase 2–6.

**Supuestos duros que gobiernan cada historia:**

| # | Supuesto | Consecuencia |
|---|---|---|
| S1 | **Development Mode.** `MetaOAuthSettings.access_posture = "development"` (`packages/api/src/qualify_api/config.py:54`) | El sprint **no promete visibilidad pública** de los posts. Sólo titulares de rol en la app ven el media publicado. Ningún criterio de aceptación puede afirmar "el reel se ve en la cuenta pública" |
| S2 | **V-TP-2 / A5-5 sigue ABIERTA.** App Mode Live + Business Verification no verificados contra cuenta real | Las historias marcadas `[dep V-TP-2]` abajo pueden ver su criterio de aceptación reformulado. Ninguna está **bloqueada** por ella: todas son construibles y testeables offline hoy |
| S3 | **TikTok publicación BLOQUEADA** (ADR 21, firmada) | Cero historias de TikTok. No es parking lot con fecha: es sin fecha |
| S4 | **Respuestas autónomas FUERA, permanentemente** (~65 % precisión en medio propio) | Sólo borrador + aprobación humana explícita. No es etiqueta de fase |
| S5 | **ADR 29 `[PROPUESTO]`, sin firmar.** BISU / Tech Provider no entra | Config activa = token de usuario (`config_id=1905711854132281`). Todo lo dependiente de BISU → parking lot §7 |
| S6 | **§3.a.ii Platform Terms nombra "housing"** y cliente uno es inmobiliaria | Toda historia que puntúe personas lleva bandera 🏠. **Ninguna historia de este sprint puntúa personas** — se declara para que no se cuele |
| S7 | **Vídeo-only.** El cliente de publicación es resumable-upload; imagen no tiene variante resumable | Imágenes → QUA-68, parking lot. `MEDIA_TYPE_REELS/STORIES/VIDEO` únicamente |

**Presupuesto de sprint (revisado en la ronda 2):** 5–6 items por compañero. **El lead decidió lanzar UN SOLO ingeniero de backend**, y la épica A es una **cadena serial sobre los mismos ficheros** — no la paralelizan cuatro personas. El architect lo dimensionó de forma independiente en *"entre 9 y 11 items, y ésa ya es la capacidad real del sprint"*. Por tanto este backlog propone **11 items en la Forma A recomendada (§6.3)**, aparca la **épica B entera al Sprint 4** y saca del presupuesto de ingeniería los cuatro entregables administrativos (§5 C2-bis).

> **Cambios de la ronda 2, para quien leyó la versión anterior:** nace **A0** (token de Página) y va primera, bloqueando A y B · **A5 abandona el bucle de sondeo** en el servidor y pasa a `start` + `advance` (baja de L a M) y de `[dep V-TP-2] PARCIAL` a **`NO`** · **C1 se rediseña** sobre `Principal` con credencial opaca y 401 · **C2 se parte** en un item de código y cuatro administrativos · **B4 se reescribe**: in-sprint es el bucle de aprobación y el seam, **no el generador** · **la épica B se aparca**.

---

## §1 Herencia: qué sobrevive de los backlogs previos

Auditoría de `docs/backlog-crm-workflows.md` §3/§4/§5.3 y `docs/integracion-cuentas-conectadas-meta.md` §4/§7.5-7.6/§8, contrastada **contra el filesystem de hoy**, no contra los docs.

### 1.1 Items HECHOS (no vuelven a entrar)

| Item previo | Evidencia en disco |
|---|---|
| **C-01…C-06** (tenancy, envelope v2, custodia+FSM, OAuth, matriz de capacidad, UI de conexiones) | `packages/api/src/qualify_api/connections/` con 16 módulos; `packages/api/tests/` con 16 suites |
| **`revoke_connection`** — `CLAUDE.md` lo declara inexistente y **está obsoleto** | `packages/api/src/qualify_api/connections/revoke.py` + `test_connections_revoke.py` + `test_connections_revoke_db.py` |
| **DDL de publicación y bandeja** (era el grueso percibido de C-07/C-08) | `migrations/postgres/versions/0003_publishing.py`, `0004_inbox.py` |
| **Cliente HTTP de publicación** (los 4 pasos del flujo, parseo `[V]`, streaming) | `packages/api/src/qualify_api/publishing/client.py` (325 líneas) + `test_publishing_client.py` |
| **Contrato de formas IG** (`shape_version`, presencia por permiso) | `packages/shared/src/qualify_shared/social/ig_shapes.py` + `test_ig_shapes.py` + `NOTES_ig_shapes_contract.md` |
| **Plano de objetos R2** (gate, tenant prefix, `media_key`, `ObjectStore`) | `packages/shared/src/qualify_shared/objects/` (config, gate, keys, s3) + 3 suites |
| **C-11 regla de decisión del filtro** | `packages/models/src/qualify_models/filter_decision.py` + `test_filter_decision.py` + `NOTES_qua23_filter_decision_rule.md` |

### 1.2 Items VIVOS (entran a este sprint, reencuadrados)

| Item previo | Qué queda vivo |
|---|---|
| **C-07** publicación con write-ahead + reconciliación | **Toda la capa de servicio, repositorio y rutas.** El DDL y el cliente existen; **nada los une**. Es la ruta crítica entera |
| **C-08** intake de DMs/comentarios poll-first | **Todo el intake.** El DDL existe; no hay cliente de Conversations API, ni servicio, ni poller |
| **C-10** borradores asistidos | Vivo pero **P3 en este sprint** — depende de C-08 y de un veredicto de datasci pendiente |
| **§8.3.2 huecos 1–5 de Platform Terms** | Vivos los cinco. Ninguno bloquea a cliente cero; los cinco vinculan cuando el primer agente de cliente uno use el producto |
| **Deuda del tenant global** (`packages/shared/src/qualify_shared/dev.py:32`) | Viva y ahora **bloqueante de facto**: `start_connect` devuelve 409 sin selección de tenant desde fuera del proceso |

### 1.3 Items INVALIDADOS por hallazgos posteriores — **no reimplementar**

Ésta es la sección que evita trabajo tirado. Cinco decisiones escritas en los docs previos ya no se sostienen.

| Decisión previa | Dónde está escrita | Qué la invalida |
|---|---|---|
| **"Alojar el media en una URL pública"** + URL firmada de R2 (W3-Q3, paso 2 del flujo) | `backlog-crm-workflows.md` §3.2 fila 2 y §3.6 W3-Q3 | **ADR 28a: subida resumable de bytes.** `publishing/client.py:287-311` sube el binario a `rupload.facebook.com` con cabeceras `offset`/`file_size`. **Meta nunca hace `cURL` de una URL nuestra.** No hay que emitir URL firmada, ni verificar si el fetcher acepta query strings, ni preocuparse del TTL. El requisito de infraestructura desaparece |
| Tabla **`publish_jobs`** | `integracion-cuentas-conectadas-meta.md` §4.2 | La tabla real es **`publish_attempts`** (`0003_publishing.py:71`) |
| Tablas **`inbox_threads` / `inbox_messages`** | encuadre del sprint-state §1 | Las tablas reales son **`threads`** (`0004_inbox.py:56`) y **`messages`** (`0004_inbox.py:105`) |
| **Columna de expiración de ventana en el hilo** (*"cada hilo lleva su fecha de expiración de ventana como columna"*) | `integracion-cuentas-conectadas-meta.md` §4.3 | **Condición B2 del architect** (`0004_inbox.py:16-19`): `window_expires_at` es **deliberadamente NO una columna**. Una copia materializada de (base + política) se queda rancia, y su modo de fallo rancio es exactamente "enviado fuera de ventana". Se calcula desde `last_inbound_at`, **nunca** desde `last_message_at` |
| **Deduplicación en dos capas con Redis `SETNX`** | `backlog-crm-workflows.md` §4.3 paso 2 y criterio de C-08 | **Decisión 2026-07-28** (`0004_inbox.py:136-138`): `UNIQUE(connection_id, external_message_id)` + upsert idempotente, **deliberadamente no un Redis SETNX**. A un tenant, cadencia de minutos, sin webhook concurrente, una constraint lo cubre sin una segunda dependencia |
| **Intake webhook-first** (§4.3 paso 1 original y §2.6 *"llega evento (webhook)"*) | `integracion-cuentas-conectadas-meta.md` §4.3 | Ya corregido a **POLL-FIRST** en `backlog-crm-workflows.md` §4.3, pero el doc del architect conserva la redacción vieja. **El poll no es red de seguridad: en Development Mode es el único camino que existe** (`webhooks.md:60-73` exige Live + Advanced + Business Verification) |

> **Corrección de cifras que se propagó y hay que no repetir** (`integracion-cuentas-conectadas-meta.md` §7.5): *"100 posts (50 si son carruseles)"* es **falso**. Son dos contadores distintos: 100 cuenta **posts publicados** (un carrusel = 1 post), 50 cuenta **contenedores IG** (un carrusel de 10 = 11 contenedores). **Los carruseles son más caros bajo la restricción que ata, no más baratos.** Regla: no hardcodear ninguna cifra; leer `GET /<IG_ID>/content_publishing_limit` en runtime.

---

## §2 Verificación de código contra disco

Leído directamente, no tomado del sprint-state. Cinco cosas que cambian el dimensionado.

### 2.1 `publishing/client.py` — completo como cliente, inutilizable como producto

**Superficie real verificada** (`packages/api/src/qualify_api/publishing/client.py`):

- `PublishClient` (Protocol) con exactamente 4 métodos: `create_container`, `upload_bytes`, `container_status`, `publish_container` (líneas 120-137).
- `HttpPublishClient` construido sobre **dos `AuthenticatedClient` ya autenticados** (`__init__`, línea 240) — uno para `graph.facebook.com`, otro para `rupload.facebook.com`, porque el esquema de `Authorization` difiere (R12). **Este módulo nunca ve un token.**
- Cuatro `_parse_*` con las lecturas `[V]` del corpus, aislados para que "cuando la realidad aterrice, aterrice en un sitio conocido".
- Constantes de sondeo ya parametrizadas: `CONTAINER_POLL_INTERVAL_SECONDS = 60`, `CONTAINER_POLL_CEILING_SECONDS = 300` (líneas 55-56).
- `UploadOutcome.retriable: bool | None` — **`None` no es `False`** (línea 112, ruling R10).

**Lo que le falta para ser usable desde una ruta — y es exactamente el hueco del sprint:**

1. **Nadie construye un `HttpPublishClient`.** No hay factoría de composición para publicación (`connections/composition.py` existe; su equivalente en `publishing/` no).
2. **El cliente no sondea.** `container_status` es una llamada única; el bucle que la repite hasta `FINISHED` con las dos constantes **no existe en ninguna parte**. Es lógica de servicio, no de cliente — y el servicio no existe.
3. **El cliente no toca la base de datos.** No hay escritura write-ahead de `publish_attempts`, no hay `idempotency_key`, no hay reconciliación por `creation_id`.
4. **El cliente no abre el media.** `upload_bytes` recibe `fileobj: IO[bytes]` y `file_size: int`; nadie los obtiene de `ObjectGate.open_object`.
5. **No hay ruta HTTP.** `packages/api/src/qualify_api/http/` contiene sólo `__init__.py`, `app.py`, `connections_routes.py`.

### 2.2 `connections_routes.py` — el patrón a imitar, con tres propiedades no negociables

Verificado en `packages/api/src/qualify_api/http/connections_routes.py`:

- **Inyección por `Depends` con un default que lanza.** `get_connect_service()` (línea 34) hace `raise NotImplementedError`, no construye un default: *"impide que un despliegue sin configurar hable en silencio con el Meta real"*. Las rutas de publicación deben hacer lo mismo.
- **El `tenant_id` NUNCA viene del cuerpo de la petición.** `StartConnectRequest` (línea 40) lo omite deliberadamente: *"un tenant id aceptado de un cliente es un bypass de autorización con pasos extra"*. Sale de `get_dev_tenant()` (línea 72).
- **Errores sin detalle diferenciador.** Un solo 403 para forjado/expirado/reutilizado (línea 90-93).

### 2.3 Migración 0003 — dos invariantes en la base que el servicio DEBE respetar

- **Trigger `publish_attempts_settle_once`** (líneas 54-66, 136-142): cualquier `UPDATE` sobre una fila con `settled_at IS NOT NULL` lanza `RAISE EXCEPTION` con `ERRCODE = 'check_violation'`. **Una reconciliación tardía no puede pisar un desenlace ya terminal.** El repositorio no puede "arreglarlo" con un `WHERE settled_at IS NULL`: el trigger existe precisamente para que un segundo camino de código no lo evite.
- **CHECK `ck_attempt_settled_matches_status`** (línea 122): `(settled_at IS NULL) = (status NOT IN ('published','failed'))`. Marcar `status='published'` sin poner `settled_at` **falla en la base**.
- Estados permitidos: `pending`, `uploading`, `processing`, `published`, `failed` (línea 116). **La FSM del servicio no puede inventar un sexto.**
- `UNIQUE(connection_id, idempotency_key)` (línea 110) — la identidad de la operación.
- Índice de reconciliación `(tenant_id, creation_id)` (línea 130) — la única vía soportada de resolver un desenlace ambiguo.
- RLS activo con `FORCE` y `NULLIF(current_setting('app.tenant_id', true), '')::uuid`. **Todo acceso pasa por `tenant_session`.**
- `scheduled_posts.media_object_key` es `Text NOT NULL` (línea 157) y el comentario dice *"siempre bajo `t/{tenant_id}/`, forzado en código por `require_tenant_prefix`"*.

### 2.4 Migración 0004 — la bandeja, y por qué las columnas nulas lo son

- Tablas **`threads`** y **`messages`** (nombres reales, ver §1.3).
- `threads.assigned_agent_id` **ya nace nullable** con FK a `users` (línea 71). No hay que migrarla; sólo no usarla.
- `threads.last_inbound_at` separado de `last_message_at` (líneas 75-79). **`last_message_at` es orden de bandeja y NUNCA base de ventana.**
- `messages`: `author_external_id` y `author_username` **nullable por `Presence.REQUIRES_PERMISSION`** (`instagram_manage_comments`); `posted_at` **nullable por `Presence.IF_REQUESTED`**. El orden cae a `ingested_at` cuando falta.
- `messages.shape_version` **NOT NULL** (línea 135) — provenance del contrato QUA-67 bajo el que se parseó la fila.
- `author_external_id` es un IGSID: **identidad no portable** (`IGSID_IS_PORTABLE_IDENTITY is False`). **Prohibido unirlo contra cualquier otro identificador de persona.**
- `UNIQUE(connection_id, external_message_id)` **sin `tenant_id`** (condición B1) — añadirlo enunciaría un invariante más débil.

### 2.5 El plano de objetos SÍ existe — y el `media_object_key` no es una promesa vacía

`packages/shared/src/qualify_shared/objects/` está completo y con tests:

- `keys.media_key(tenant_id, connection_id, media_id)` → `t/{tenant_id}/media/{connection_id}/{media_id}`.
- `keys.require_tenant_prefix` rechaza `..` y cualquier clave fuera del prefijo, **sin ecoar la clave ofensora**.
- `ObjectGate.put_media` exige `content_type` explícito y aplica un techo duro `MAX_MEDIA_BYTES` con **un solo PUT, multipart deliberadamente no implementado**.
- `ObjectGate.open_object` **re-verifica el prefijo en lectura** — *"una clave leída de una fila de base de datos sigue siendo input"*. Devuelve `IO[bytes]`, que es exactamente lo que `upload_bytes` consume.
- ⚠ **`boto3` no está declarado como dependencia.** `s3.py:23-25` lo importa perezosamente dentro de la factoría, precisamente para no forzar un `uv sync` que corrompe el venv compartido. **Consecuencia para el sprint: el camino real a R2 no es ejercitable sin declarar boto3.** Todo lo demás corre contra el doble en memoria.

### 2.6 `dev.py` — la deuda del tenant, medida

`packages/shared/src/qualify_shared/dev.py:32`: `_dev_tenant: UUID | None = None`, **un global de módulo**. `set_dev_tenant` escribe sobre `global`. El docstring lo admite: *"process-local, unsuitable for a real multi-user server"*.

Consecuencia verificada: `connections_routes.py:72-74` → si no hay tenant seleccionado **en el mismo proceso**, `POST /api/connections/start` devuelve **409**. Un cliente HTTP externo (curl, Postman, la prueba del fundador) **no tiene forma de seleccionar tenant**. Esto no es cosmético: bloquea la prueba empírica de extremo a extremo.

### 2.7 `config_id` — cero ocurrencias

`grep -rn "config_id" packages/ Qualify/` → **cero resultados**. `MetaOAuthSettings` (`config.py:33-67`) tiene `app_id`, `redirect_uri`, `state_secret`, `authorize_url`, `api_version`, `requested_scopes`, `access_posture`, `graph_auth_scheme`, `rupload_auth_scheme`. **No tiene `config_id`.** `MetaOAuthClient.authorization_url` (`meta_oauth.py:158-169`) construye `client_id`/`redirect_uri`/`state`/`response_type` + `scope` opcional. Es exactamente el fallo del hallazgo 1.

---

## §3 Épica A — Publicación (ruta crítica)

> **Alcance declarado de la épica.** Dentro: **vídeo únicamente** — reel, story de vídeo y vídeo de carrusel, vía subida resumable de bytes (ADR 28a). Fuera y explícito: **imágenes → QUA-68** (no existe variante resumable para imagen, `client.py:59`; meterla exigiría la superficie HTTP pública que ADR 28 existe para evitar); **carrusel como producto** (el `is_carousel_item` del cliente existe, el flujo de agrupación no); **publicidad pagada / Marketing API** (parking lot §7); **TikTok** (bloqueado, S3).

### A0 — 🔴 Token de **Página**: hoy guardamos el de usuario y Meta exige el de Página

> **Bloquea la épica A y la épica B por igual. Ninguna historia de la primera ronda lo cubría.** Es un hueco de la capa de conexión (C-04), no de la de publicación: A1 arregla el diálogo, A2 la grafía, A5 asume que `CredentialResolver.client_for()` devuelve algo utilizable — **nadie había comprobado qué devuelve**.

- **Historia:** Como equipo de marketing de una marca, quiero que al conectar mi cuenta el sistema guarde la credencial que la plataforma realmente acepta, para que la primera publicación funcione en vez de fallar con un error que parece un bug del producto.
- **Criterios de aceptación:**
  - `list_linked_pages` añade **`access_token`** a la lista de `fields`. Hoy es `"id,name,instagram_business_account{id,username}"` (`meta_oauth.py:197`) y **Meta no devuelve el token por Página si no se pide**, así que ni un parser tolerante podría recogerlo.
  - `LinkedPage` gana `page_access_token: str | None`, **marcado `[V]`** — no se ha observado la respuesta real.
  - El callback cifra y persiste **el token de Página de la Página elegida**, no el de usuario. Hoy `service.py:223` cifra `grant.access_token`, que viene de `exchange_code` y es de **usuario**.
  - **Sin migración.** `oauth_credentials.token_type` es `text` libre; `token_type='page'` vs `'user'` es representable hoy (mismo argumento que ADR 29(g) hizo para BISU).
  - **Los dos `[V]` abiertos se cierran en vivo y se registran, no se infieren:** (i) ¿hay que intercambiar antes el token de usuario corto por uno largo para que el de Página sea de larga duración? (ii) ¿se sigue necesitando el token de **usuario** para algo — `/me/permissions` lo usa hoy — y por tanto hay que custodiar **dos** credenciales por conexión?
  - **Si la respuesta a (ii) es sí, la decisión de custodia se eleva al architect antes de codificarla.** La custodia de C-03 es append-only por diseño; dos tipos de token por conexión es una decisión de custodia, no de fontanería.
  - **Aviso de PPA en el flujo de conexión:** la UI recomienda **completar Page Publishing Authorization preventivamente**. `content-publishing.md:19-21` es literal: una cuenta conectada a una Página que exige PPA *"cannot be published to until PPA has been completed"* y — la parte peligrosa — *"**there's no way for you to determine if an app user's Page requires PPA**"*. Mismo patrón que la precondición de Página vinculada de ADR 25, **salvo que ésta no se puede detectar por API en absoluto**.
  - `uv run pytest -m "not integration"` verde sin red, con doble de plataforma.
- **Fase:** Fase 1 Parte 4-A (remediación de C-04, mismo módulo que A1/A2).
- **Evidencia:** hallazgo del architect `.claude/sprint-state-2026-07-31-po-sprint3.md` [2026-07-31 01:21] · `reference/meta-instagram-platform/instagram-platform/content-publishing.md:30` y `comment-moderation.md:17` → fila **Access Tokens = `Facebook Page access token`** en la columna *Instagram API with Facebook Login*, que es la bifurcación firmada (ADR 25) · verificado en disco: `connections/service.py:223`, `meta_oauth.py:192-200`, `_parse_accounts_response` (`meta_oauth.py:99-124`, sin campo de token en la dataclass) · PPA: `content-publishing.md:19-21`.
- **Prioridad / tamaño:** **P0 / S–M** (el código es pequeño; el riesgo está en los dos `[V]` abiertos)
- **Dependencias:** ninguna. **Bloquea A5, A6, A7 y toda la épica B.** Construye sobre `packages/api/src/qualify_api/connections/meta_oauth.py`, `service.py`, `credential_reader.py`.
- **`[dep V-TP-2]`: NO.**

### A1 — El diálogo de consentimiento debe pedir activos (`config_id`)

- **Historia:** Como equipo de marketing de una marca, quiero que al conectar mi cuenta el diálogo de Meta me pida explícitamente qué Página e Instagram autorizo, para que la conexión quede realmente habilitada y no aparente estar conectada sin poder publicar nada.
- **Criterios de aceptación:**
  - `MetaOAuthSettings` gana `config_id: str | None` leído de entorno (`QUALIFY_META_CONFIG_ID`), **con el mismo tratamiento de dato que `requested_scopes` y `graph_auth_scheme`**: nunca literal en código.
  - `MetaOAuthClient.authorization_url` incluye `config_id` en la query **cuando está definido**, y lo **omite entero** cuando no lo está (no manda cadena vacía — el precedente exacto de `meta_oauth.py:165-168`).
  - Test unitario sin red: con `config_id` definido, la URL generada contiene `config_id=...`; sin él, el parámetro **no aparece**.
  - Test unitario sin red: `config_id` y `scope` **coexisten** en la URL sin que uno anule al otro (la resolución empírica de cuál gana es A2, no este item).
  - `uv run pytest -m "not integration"` verde sin red.
  - **No se firma ningún valor de `config_id` en el repo.** El `1905711854132281` de la sesión de campo va a `.env` / documentación operativa, no a un default de código.
  - 🔴 **La verificación de scopes concedidos se vuelve load-bearing, y el criterio lo dice explícitamente.** Si el `config_id` determina el conjunto de permisos que el diálogo pide, entonces **`requested_scopes` deja de ser la fuente de verdad de lo que pedimos**, y esa fuente pasa a ser un artefacto de la consola de Meta que **vive fuera del repositorio, sin control de versiones y sin revisión**. `list_granted_scopes` (`/me/permissions`) es lo único que queda dentro del sistema capaz de decir qué se concedió de verdad. El código ya lo persiste verbatim (`service.py:204,219`); **el criterio es que exista un test que falle si `granted_scopes` deja de persistirse**, y que la degradación por scope ausente sea observable en la UI, no silenciosa.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** hallazgo 1 de la sesión de campo, `.claude/sprint-state-2026-07-31-po-sprint3.md` §1 *"Hallazgos… 1"* (sin `config_id` el diálogo salta al callback sin conceder activos y `/me/accounts` devuelve 0 páginas) · fichero verificado `packages/api/src/qualify_api/connections/meta_oauth.py:158-169` (hoy sólo manda `scope`) · `packages/api/src/qualify_api/config.py:49-67` (el precedente de "esto es dato").
- **Prioridad / tamaño:** **P0 / S**
- **Dependencias:** ninguna. **Bloquea a todas las demás historias de la épica A y a toda la épica B**: sin activos concedidos no hay `ig_user_id` sobre el que publicar ni hilo que leer. Construye sobre `packages/api/src/qualify_api/connections/meta_oauth.py` y `config.py`.
- **`[dep V-TP-2]`: NO.** Es construible y testeable hoy en Development Mode.

### A2 — La grafía del scope de publicación se resuelve empíricamente, nunca desde documentación

- **Historia:** Como equipo de marketing, quiero que la app pida el permiso de publicación con el nombre que la plataforma realmente acepta, para no descubrir en el momento de publicar que el consentimiento que di no incluía publicar.
- **Criterios de aceptación:**
  - Existe un **script/comando de resolución** (no un test de red en CI) que, dada una lista de grafías candidatas, consulta el endpoint de autorización y reporta cuál es aceptada y cuál rechazada. Marcado `integration`, **nunca en el run por defecto**.
  - El resultado se persiste como **dato operativo** (`QUALIFY_META_SCOPES` / documento de operación), **no como literal en código**. Un `grep` de `instagram_content_publish` sobre `packages/` debe seguir devolviendo cero *defaults hardcodeados*.
  - Existe un test unitario sin red que afirma la **regla**, no el valor: `requested_scopes` vacío ⇒ el parámetro `scope` se omite; poblado ⇒ se serializa separado por comas.
  - La documentación operativa registra la grafía verificada **con fecha y método de verificación**, y anota explícitamente que `instagram_content_publishing` es **errata de la propia documentación de Meta**.
  - `uv run pytest -m "not integration"` verde sin red.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** hallazgo 2 de la sesión de campo, `.claude/sprint-state-2026-07-31-po-sprint3.md` §1 (*"la grafía correcta es `instagram_content_publish`… verificado dos veces contra el endpoint de autorización. No hardcodear desde documentación"*) · precedente de la casa: `config.py:49-51` marca `requested_scopes` como `[V]`, *"never hardcoded"* · `integracion-cuentas-conectadas-meta.md` §7.4 (*"el publish scope tiene cuatro grafías en circulación"*, recogido en `CLAUDE.md`).
- **Prioridad / tamaño:** **P0 / S**
- **Dependencias:** A1 (el diálogo tiene que conceder activos para que la respuesta del endpoint sea interpretable). Construye sobre `packages/api/src/qualify_api/config.py`.
- **`[dep V-TP-2]`: NO.**

### A3 — Staging del media a R2: la clave que la publicación va a abrir

> ⚠ **REENCUADRADA tras el hallazgo del architect [2026-07-31 01:13](a).** La versión anterior de este item creaba la fila de `scheduled_posts` y trataba la programación diferida como parte del sprint. **No lo es:** `grep -rl celery` sobre todo el repo da **cero**, `docker-compose.yml` sólo tiene `postgres` y `redis`, `packages/pipeline/` no existe. **No hay ningún proceso capaz de despertarse a la hora programada.** El sprint entrega **publicación inmediata (publish-now)**. `scheduled_posts` se queda como DDL aplicada sin consumidor — lo cual **no es deuda**: la tabla ya existe y la historia de scheduling la rellenará sin migración nueva. → parking lot §7.

- **Historia:** Como equipo de marketing de una marca, quiero subir el vídeo de mi reel y que quede guardado en un sitio propio antes de que se toque la plataforma, para que un fallo a mitad de publicación no me obligue a volver a subir el archivo.
- **Criterios de aceptación:**
  - Existe un servicio de staging que: recibe bytes + `content_type` + `media_product_type`, construye la clave con **`qualify_shared.objects.keys.media_key(tenant_id, connection_id, media_id)`** (nunca a mano) y escribe vía **`ObjectGate.put_media`**. Devuelve el `media_object_key`.
  - 🔴 **Esto es la capa L6 y es la PRIMERA de la cadena, no la última.** En todo el repo **no hay una sola llamada a `put_media`**: `grep` de `ObjectGate` sólo pega en `gate.py` y sus tests. Sin esta historia, aunque el resto de la épica A salga perfecta, **no hay forma de meter un vídeo en el sistema y la cadena entera termina en un bucket vacío**.
  - **No crea fila de `scheduled_posts`.** `publish_attempts.scheduled_post_id` es nullable (`0003_publishing.py:81`) precisamente para admitir publish-now. Escribir una fila de programación que nadie va a leer sería prometer un reloj que no existe.
  - `media_product_type` se valida contra `{'REELS','STORIES','VIDEO'}` **antes** de subir nada, con el mismo vocabulario que `RESUMABLE_MEDIA_TYPES` (`client.py:63`).
  - Una clave fuera del prefijo `t/{tenant_id}/` **levanta `TenantPrefixViolation`** y no sube nada. Test explícito.
  - Un `content_type` vacío es rechazado (`ObjectGate.put_media` ya lo hace; el test lo afirma desde el servicio) — un objeto guardado como `application/octet-stream` es causa plausible de un `ERROR` de contenedor que parece venir de otro sitio.
  - Un objeto por encima de `MAX_MEDIA_BYTES` (300 MiB) levanta `ObjectSizeExceeded` **sin dejar rastro parcial**.
  - Toda la suite corre contra un **doble en memoria de `ObjectStore`**; `uv run pytest -m "not integration"` verde **sin red y sin boto3 instalado**.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** hallazgo del architect en `.claude/sprint-state-2026-07-31-po-sprint3.md` [01:13](a) (Celery inexistente, verificado con `grep`) y (b) (el gate es código terminado, no esqueleto) · `packages/shared/src/qualify_shared/objects/keys.py:35-43` (`media_key`) y `:46-60` (`require_tenant_prefix`) · `objects/gate.py:82-101` (`put_media`) · `0003_publishing.py:81` (`scheduled_post_id` nullable) · `client.py:59-63`.
- **Prioridad / tamaño:** **P0 / S** (era M; sin `scheduled_posts` es la mitad)
- **Dependencias:** **C3** (declarar `boto3`) y **C4** (aprovisionar el bucket R2) para el camino real; **ninguna** para el camino de test. Construye sobre `packages/shared/src/qualify_shared/objects/`.
- **`[dep V-TP-2]`: NO.**

### A4 — Repositorio de publicación: el registro write-ahead y la idempotencia

- **Historia:** Como equipo de marketing, quiero que si el sistema se cae en mitad de una publicación quede rastro de qué se intentó, para que nadie tenga que adivinar si el post salió y para que reintentar no me duplique el reel en la cuenta.
- **Criterios de aceptación:**
  - `PublishAttemptRepository` con, como mínimo: `start_attempt(...)` (INSERT antes de cualquier llamada a plataforma), `record_creation_id(...)`, `advance_status(...)`, `settle(...)`, `find_by_idempotency_key(...)`, `find_unsettled_by_creation_id(...)`.
  - **La fila se escribe ANTES de la primera llamada a Meta.** Test: un fallo inyectado en `create_container` deja la fila en `status='pending'` con `creation_id IS NULL` — **no deja ausencia de fila**.
  - **Idempotencia:** llamar dos veces con la misma `(connection_id, idempotency_key)` **no crea una segunda fila** y **no dispara una segunda publicación**; devuelve el desenlace del intento existente. Test con el `UNIQUE uq_attempt_idempotency` real (`db`) y con doble en memoria (offline).
  - **La `idempotency_key` la elige el llamante**, no se genera dentro del repositorio (es lo que hace la operación identificable desde fuera).
  - **Existen los modelos ORM** de `publish_attempts` y `scheduled_posts` (`publishing/models.py`), espejo de `connections/models.py`. Es la capa L1 y hoy no existe.
  - **El repositorio respeta el trigger, no lo esquiva, Y lo traduce bien:** **prohibido** un `UPDATE ... WHERE settled_at IS NULL` que convierta el conflicto en un no-op silencioso (`0003_publishing.py:50-53` dice literalmente por qué). Lo correcto es **capturar `check_violation` y tratarlo como "ya liquidado" — el camino idempotente del reintento**, no como un 500. **Criterio obligatorio**, con test: un `settle` sobre una fila ya asentada devuelve el desenlace existente, no un error de servidor.
  - `settle` escribe `settled_at` **y** un `status` terminal en la misma sentencia — el CHECK `ck_attempt_settled_matches_status` lo exige.
  - Provenance completa en cada fila: `tenant_id`, `connection_id`, `adapter_version`, `media_product_type`, y `raw_response_r2_key` cuando haya respuesta cruda archivada.
  - Todo acceso pasa por **`tenant_session`** (RLS). Test `db`: una fila de otro tenant es **invisible**, no filtrada en Python.
  - `uv run pytest -m "not integration"` verde sin red; los tests de constraints/trigger llevan marca `db`.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `0003_publishing.py:71-142` (columnas, `uq_attempt_idempotency`, ambos CHECK, trigger `publish_attempts_settle_once`, índice `ix_attempt_reconcile`) · `backlog-crm-workflows.md` §3.2 paso 6 y ADR 22(e) · `integracion-cuentas-conectadas-meta.md` §4.2 regla 1 (*"write-ahead del `creation_id`… si no está escrito, la llamada no ocurre"*).
- **Prioridad / tamaño:** **P0 / M**
- **Dependencias:** ninguna funcional. Construye sobre `migrations/postgres/versions/0003_publishing.py` y el patrón de `packages/api/src/qualify_api/connections/repository.py`.
- **`[dep V-TP-2]`: NO.**

### A5 — Servicio de publicación: la FSM contenedor → publicación, con **sondeo dirigido por el cliente**

> 🔴 **REFORMULADA. El bucle de sondeo en el servidor no cabe en una petición HTTP** (hallazgo del architect [2026-07-31 01:17], L7). 60 s × 300 s significa que un `POST /publish` con el bucle completo **bloquea hasta cinco minutos**, más la subida (300 MiB por una conexión doméstica son varios minutos). Una petición de 8-10 minutos viola la regla de *nada caro en la ruta de request*, y **sin Celery no hay dónde moverlo**.
>
> **Dos salidas descartadas, con su razón:** (i) `BackgroundTasks` de FastAPI — **muere con el proceso y deja la fila en `processing` para siempre**; da ilusión de asincronía con cero durabilidad, y su modo de fallo es el peor posible: la fila dice "en curso" cuando no hay nada en curso. (ii) Celery — **fuera de sprint**, convertiría esto en Fase 1 Parte 3.
>
> **Salida adoptada: sondeo dirigido por el cliente.** La operación se parte en llamadas cortas, cada una idempotente y cada una liquidando su propio paso en la base. **Es seguro sin ejecutor durable** porque el registro write-ahead y el índice `ix_attempt_reconcile` existen justo para esto: si el cliente abandona, la fila queda en `processing` con su `creation_id` y **el mismo GET la reconcilia cuando alguien vuelva**. No se pierde información; se difiere.
>
> **Coste honesto, escrito para que nadie lo lea como diseño final:** un intento abandonado que nadie vuelve a mirar se queda `processing` indefinidamente. Es aceptable a un tenant con un operador humano; **deja de serlo en cuanto haya clientes**, y ahí entra Celery.
>
> → **Merece fila de ADR `[PROPUESTO]`.** La redacta el architect; este backlog no la firma.

- **Historia:** Como equipo de marketing de una marca, quiero publicar un reel desde el CRM y ver cómo avanza, para no tener que reintentar a mano ni descubrir el fallo cuando ya es tarde.
- **Criterios de aceptación:**
  - Existe `PublishService` con **dos operaciones cortas**, no una larga:
    - `start(...)` → `start_attempt` (write-ahead, `status='pending'`) → `create_container` → `record_creation_id` → `open_object` + `upload_bytes` → `status='processing'`. Devuelve el `attempt_id`. Larga por la subida, pero **acotada y sin espera pasiva**.
    - `advance(attempt_id)` → **UNA** llamada a `container_status`; si `FINISHED`, llama a `media_publish` y liquida; si terminal de error, liquida a `failed`; si `IN_PROGRESS`, devuelve el estado sin liquidar. **Idempotente.**
  - **Ninguna función del servicio duerme, espera ni itera sobre `container_status`.** Test estático: `grep` de `sleep` / `asyncio.sleep` dentro de `publishing/` → **cero**.
  - **El techo de 300 s se comprueba contra la columna `started_at` de la fila** (`0003_publishing.py:102-107`), no con un contador de bucle ni un reloj en memoria. Un `advance` sobre un intento cuyo `started_at` supera `CONTAINER_POLL_CEILING_SECONDS` liquida a `failed` con motivo **distinguible** de un `ERROR` de contenedor. ⚠ *Nota: la columna se llama `started_at`, no `created_at` — `created_at` sólo existe en `scheduled_posts`.*
  - `CONTAINER_POLL_INTERVAL_SECONDS` pasa a ser **cadencia recomendada al cliente**, documentada en el contrato de la ruta — no un `sleep` del servidor. Es exactamente lo que Meta recomienda y lo que el presupuesto de 200 llamadas/hora tolera.
  - **Los cinco `ContainerStatus` se tratan como cinco, no como un booleano listo/no-listo:** `FINISHED` → publica; `IN_PROGRESS` → devuelve estado sin liquidar; `ERROR` y `EXPIRED` → terminal, **jamás se reintenta hacia ellos**; `PUBLISHED` → **se asienta como éxito sin volver a llamar a `media_publish`** (es cómo la reconciliación descubre un éxito del que dudábamos).
  - **Desenlace distinguible para PPA.** Un fallo de publicación por Page Publishing Authorization se mapea a un motivo propio, **no a un `failed` genérico**. `content-publishing.md:19-21` avisa de que **no hay forma de detectar por API si una Página exige PPA**: un fallo de PPA registrado como error opaco son horas persiguiendo un bug que no existe.
  - **`UploadOutcome.retriable is None` se trata como desconocido, no como `False`** (`client.py:110-112`, ruling R10). Test con los tres valores.
  - El estado de `publish_attempts` avanza de forma observable: `pending` → `uploading` → `processing` → (`published` | `failed`). **Ningún sexto estado.**
  - **El token se resuelve en el momento de publicar, no en el de componer.** Si la conexión no está en un estado que permita publicar (`revoked`/`degraded`), **no publica y registra el motivo**; no reintenta contra una credencial muerta.
  - El servicio **nunca ve un token**: obtiene sus dos clientes de `CredentialResolver.client_for(..., scheme=...)` con `graph_auth_scheme` y `rupload_auth_scheme` de settings. Test estático: `grep` de construcción de `httpx.AsyncClient` dentro de `publishing/` → cero (fuera del propio `client.py`).
  - Existe una **factoría de composición** para publicación, al estilo de `connections/composition.py`.
  - Toda la suite corre contra un `PublishClient` falso; `uv run pytest -m "not integration"` verde **sin red**.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `packages/api/src/qualify_api/publishing/client.py:9-18` (el orden del flujo y por qué no es arbitrario), `:55-56` (constantes de sondeo), `:70-85` (los cinco estados y `is_terminal`), `:101-118` (`UploadOutcome` y R10), `:231-249` (dos clientes, cero tokens) · `connections/resolver.py:103-109` (`client_for`) · `backlog-crm-workflows.md` §3.5 (*"se ejecuta con el token vigente en el momento de publicar"*).
- **Prioridad / tamaño:** **P0 / M** (era L; partir el bucle en `start` + `advance` elimina la parte que la hacía grande — no hay ejecutor, no hay concurrencia, no hay temporizador que testear)
- **Dependencias:** **A0** (token de Página — sin él la primera llamada real falla), **A3** (media en R2 para abrir), **A4** (repositorio). Construye sobre `packages/api/src/qualify_api/publishing/client.py`, `connections/resolver.py`, `qualify_shared.objects.gate`.
- **`[dep V-TP-2]`: NO.** *(Corregido: era `PARCIAL`.)* El architect lo cierra en dirección favorable: `content-publishing.md:27` lista **Standard Access** en ambas columnas y `comment-moderation.md:25-26` lo explicita — *"Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard"*. **Publicar sobre las cuentas del propio fundador es una operación de Standard Access, ejecutable hoy.** Esto cierra además **A5-1** en dirección favorable.
- ⚠ **Riesgo propio, sin nombre de dependencia:** `overview.md:43` advierte que *"algunas funcionalidades pueden no funcionar correctamente hasta tener Advanced Access"*. Es incertidumbre real, **pero no es ninguna de las tres preguntas de V-TP-2**, y etiquetarla como tal invitaría a esperar en balde una verificación que no la va a responder. El criterio *"el reel es visible públicamente"* **no forma parte de esta historia** por S1.

### A6 — Reconciliación por `creation_id`: la única transición del sistema con reintento ciego prohibido

- **Historia:** Como equipo de marketing, quiero que si la publicación se corta a mitad el sistema averigüe qué pasó de verdad en Instagram en vez de volver a publicar, para no encontrarme el mismo reel dos veces en mi cuenta delante de mi audiencia.
- **Criterios de aceptación:**
  - Un fallo **ambiguo** en `publish_container` (timeout, respuesta sin `id`, error de transporte tras enviar) **NO reintenta**: entra en reconciliación por `creation_id`.
  - La reconciliación **consulta a Meta**, no a la base local, y entra por el índice `ix_attempt_reconcile (tenant_id, creation_id)`.
  - `_parse_publish_response` lanzando por ausencia de `id` es un **caso documentado y esperado**, no un bug: el servicio lo captura y reconcilia (`client.py:197-204`).
  - **Test de la propiedad, no del camino feliz:** timeout inyectado tras enviar `media_publish` → reconciliación → **cero republicaciones**, y el intento acaba en `published` si el contenedor dice `PUBLISHED`.
  - **Test negativo explícito:** no existe camino de código que llame a `publish_container` dos veces con el mismo `creation_id`. Verificable por test, no por revisión.
  - Una reconciliación tardía sobre un intento **ya asentado** no lo pisa (lo garantiza el trigger; el test lo afirma desde el servicio).
  - **El estado local no es autoritativo sobre qué hay publicado.** Cualquier recuento de publicados se lee de la API. Razón: otra herramienta (PuntoServis) publica en la misma cuenta.
  - **`raw_response_r2_key` se rellena desde el principio** para las respuestas de `media_publish` y de fallo (capa L8). La columna es nullable, así que la v1 *podría* dejarla nula — **pero entonces la historia tendría que decirlo explícitamente**, porque la regla de provenance del proyecto es dura y un nulo silencioso se lee después como "se perdió". Es una escritura pequeña y **es la única traza que quedará de la primera llamada real a Meta**, que es justo la que nadie querrá haber perdido.
  - `uv run pytest -m "not integration"` verde sin red.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** **ADR 22(e)** y `integracion-cuentas-conectadas-meta.md` §4.2 reglas 2 y 3 (*"la única transición del sistema que tiene prohibido el retry con backoff"*, *"se reconcilia contra Meta, no contra nuestra base"*) · `backlog-crm-workflows.md` §3.2 (*"el paso 5 es el único irreversible del sistema entero"*) y §3.3 (Qualify no es el único escritor) · `0003_publishing.py:128-130` (el índice existe para esto y sólo para esto) · `client.py:197-204`.
- **Prioridad / tamaño:** **P0 / M**
- **Dependencias:** **A4**, **A5**. Construye sobre `publish_attempts` y `publishing/client.py`.
- **`[dep V-TP-2]`: NO.**

### A7 — Las rutas HTTP de publicación

- **Historia:** Como equipo de marketing, quiero disparar y consultar una publicación desde el CRM, para gestionar la cuenta desde una sola herramienta sin depender del móvil.
- **Criterios de aceptación:**
  - Nuevo `packages/api/src/qualify_api/http/publishing_routes.py` con **tres rutas que reflejan el sondeo dirigido por el cliente** (A5):
    - `POST /api/media` (multipart) → `ObjectGate.put_media` → devuelve el `media_object_key`. **Es la capa L6 y es la PRIMERA de la cadena, no la última** (ver A3).
    - `POST /api/publishing/attempts` → invoca `PublishService.start(...)`, recibe la `idempotency_key` del cliente y devuelve **`202` + `attempt_id`**.
    - `GET /api/publishing/attempts/{id}` → invoca `PublishService.advance(...)`: **una** comprobación de estado, liquidando si procede. La UI (o el fundador con curl) repite el GET a la cadencia recomendada.
  - **El `tenant_id` NUNCA viene del cuerpo ni de la query.** Sale del `Principal` (ver C1). El modelo Pydantic **no tiene campo `tenant_id`** — test que lo afirma sobre el esquema.
  - **Ninguna ruta bloquea más allá de lo que tarda su propio paso.** `GET /attempts/{id}` no espera a que el contenedor termine: devuelve el estado actual.
  - **La dependencia por defecto lanza `NotImplementedError`**, no construye un cliente real (`connections_routes.py:34-37`). Test: la app sin configurar **no habla con Meta**.
  - **La `idempotency_key` es obligatoria** en el cuerpo de publicación. Un POST sin ella es **422**, no una clave generada por el servidor.
  - Repetir el mismo POST con la misma `idempotency_key` devuelve **el mismo `attempt_id`** y **no publica dos veces**.
  - Ningún cuerpo de respuesta ni mensaje de error contiene token, `ciphertext`, ni cuerpo de respuesta de Meta (`client.py:38-39`: *"los mensajes de error llevan códigos de estado, nunca cuerpos"*).
  - Las rutas se registran en `app.py` junto a las de conexiones.
  - Tests con `dependency_overrides` y un servicio falso completo: **el flujo entero corre sin red y sin base de datos**, igual que `test_oauth_callback.py`.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `packages/api/src/qualify_api/http/connections_routes.py:1-18` (el docstring que fija el patrón), `:34-37`, `:40-44`, `:72-74` · `packages/api/src/qualify_api/http/` verificado: sólo `app.py` y `connections_routes.py`.
- **Prioridad / tamaño:** **P1 / M**
- **Dependencias:** **A3, A4, A5, A6** y **C1**, que es **precondición dura**: hoy es literalmente imposible seleccionar tenant desde fuera del proceso, y cada ruta escrita contra `get_dev_tenant()` habría que reescribirla después. Con dos rutas es trivial; con las seis u ocho que este sprint añade, deja de serlo. Construye sobre `packages/api/src/qualify_api/http/`.
- **`[dep V-TP-2]`: NO.**

---

## §4 Épica B — Bandeja de un solo canal

> 🔴 **RECORTE DE ALCANCE OBLIGATORIO — hallazgo del architect [2026-07-31 01:14](2). La bandeja de este sprint es SÓLO COMENTARIOS. Los DM no son alcanzables, y no por falta de trabajo.**
>
> `0004_inbox.py:96` admite `channel IN ('comment','dm')`, así que **el esquema** permite `dm`. **La API de Meta no.** `packages/shared/src/qualify_shared/social/ig_shapes.py` (contrato verificado contra el corpus primario, con citas que un test comprueba que siguen resolviendo) declara dos exclusiones **independientes**:
> - `direct_messages` — bajo ADR 25 con Standard Access la app **sólo puede interactuar con personas que tienen rol en la app**. Un cliente real que manda un DM no lo tiene. `unblocked_by = "Business Verification + Advanced Access"` — la misma puerta que V-TP-2.
> - `direct_messages_human_toggle` — **con independencia de cualquier scope de OAuth**, el titular tiene que activar a mano *Instagram > Ajustes > Mensajes > Controles > Herramientas conectadas > Permitir acceso a mensajes*. Es una acción humana dentro de la app de Instagram, **no concedible programáticamente**. Ni la verificación la desbloquea.
>
> **Toda historia de DM → parking lot §7.** Y ojo con la consecuencia de producto: un poll de DM que devuelve vacío es **ambiguo** entre "no hay mensajes" y "el titular nunca activó el acceso". Una bandeja que pinte silencio como cero **está mintiendo**.
>
> _Nota de implementación para quien escriba el test:_ `UNCOVERED_SURFACES` es una **tupla** de `UncoveredSurface` (`ig_shapes.py:591`), no un dict. El acceso por nombre es una búsqueda, no un `[...]`.

> 🔴 **DEPENDENCIA DE A0 — la épica B la hereda igual que la A.** `GET /<IG_MEDIA_ID>/comments` exige **token de Página** (`comment-moderation.md:17`), y hoy guardamos el de usuario. **Toda la épica B está bloqueada por A0.**

> ⚠ **FRONTERA DE FASE sobre el sentimiento — el architect la fija y es fina.** El análisis de sentimiento sobre comentarios de medio propio **como campo de triaje de un hilo** (una etiqueta por mensaje, para ordenar la bandeja) es **Parte 4-B y pasa**. Como **reporting, agregación, gráficas o resumen LLM** es **Fase 2 (Social listening + AI Insights)** y **no pasa**. **La frontera no es el modelo, es el consumidor:** un valor por fila en la bandeja, sí; un panel que agrega esos valores, no. Por eso **no hay historia propia de sentimiento en este sprint** — si la hubiera, se colaría Fase 2 disfrazada de campo de base de datos. Nota adicional del datasci: **no existe columna de sentimiento en el DDL** (verificado leyendo `0004_inbox.py` entera) y **el esquema hizo bien** en no presuponerla.

> **Segundo recorte, del mismo hallazgo [01:14](3): "todos los comentarios" no significa todos.** Estos límites van escritos en los criterios de aceptación como **límites conocidos**, no descubiertos como bugs más tarde: `returns_top_level_only=True` (**las respuestas a comentarios no llegan**), `age_gated_media_comments` (no se devuelven), `restricted_user_comments` (retenidos — **el recuento no coincide con el que ve el titular en la app**), `live_video_comments` (sólo durante la emisión; un poll posterior nunca los captura), `non_organic_comments` (comentarios en anuncios — Marketing API, fuera de ADR 21). Y `UNSUPPORTED_FIELDS = {comment_type, mentioned_instagram_users}`: **no pedirlos**.

### B1 — Cliente de lectura de comentarios y el contrato de formas

- **Historia:** Como equipo de community de una marca, quiero que el sistema lea los comentarios de mi propio contenido tal y como la plataforma los devuelve de verdad, para que lo que veo en la bandeja no dependa de suposiciones sobre el formato.
- **Criterios de aceptación:**
  - Existe un cliente de lectura con la **misma forma** que `publishing/client.py` y `connections/meta_oauth.py`: un `Protocol`, una implementación HTTP sobre `AuthenticatedClient`, y **una función `_parse_*` por endpoint marcada `[V]`**. Ninguna otra parte del código parsea respuestas de Meta.
  - **Reutiliza `qualify_shared.social.ig_shapes`** como contrato de presencia/nulabilidad. **Prohibido** redeclarar formas de campo dentro de `qualify_api`.
  - Los campos de `UNSUPPORTED_FIELDS` **no se solicitan**; existe un test que lo afirma sobre los parámetros de la petición.
  - **Paginación con los límites reales:** `max_per_query=50`, sin filtro por `timestamp`. La de-duplicación es **por id de comentario**, no por ventana temporal.
  - El cliente **nunca ve un token**: recibe un `AuthenticatedClient` construido por `CredentialResolver.client_for(..., scheme=graph_auth_scheme)`.
  - Los mensajes de error llevan **código de estado, nunca cuerpo** (mismo motivo que `client.py:38-39`).
  - `uv run pytest -m "not integration"` verde **sin red**, contra fixtures de forma.
- **Fase:** Fase 1 Parte 4-B.
- **Evidencia:** `packages/shared/src/qualify_shared/social/ig_shapes.py:49` (`SHAPE_VERSION = "ig-comment-shapes-1.0.0"`), `:263` (`COMMENT_LIMITS`), `:265` (`INCREMENTAL_POLLING_NOTE`), `:278` (`UNSUPPORTED_FIELDS`), `:591` (`UNCOVERED_SURFACES`) · hallazgo del architect [01:13](c) y [01:14](3) · patrón de `packages/api/src/qualify_api/publishing/client.py:1-40`.
- **Prioridad / tamaño:** **P1 / M**
- **Dependencias:** **A0** (token de Página — `comment-moderation.md:17`), **A1** (sin activos concedidos no hay cuenta que leer), **A2** (los scopes de lectura se resuelven por el mismo mecanismo). Construye sobre `packages/shared/src/qualify_shared/social/ig_shapes.py` y `connections/resolver.py`.
- **`[dep V-TP-2]`: NO.** Los comentarios sobre media propia **sí** son alcanzables en Development Mode; es lo que distingue esta épica de la de DM.

### B2 — Sincronización manual: el pull que es la ruta de producción, no el respaldo

- **Historia:** Como equipo de community de una marca, quiero pulsar "Actualizar" y que aparezcan todos los comentarios nuevos de mi contenido sin que se me duplique ninguno, para no dejar a nadie sin responder.
- **Criterios de aceptación:**
  - Existe un servicio de sincronización + una ruta `POST /api/inbox/sync` que dispara el pull para una conexión. **No se introduce Celery, ni Beat, ni un servicio worker en `docker-compose.yml`.**
  - **El poll es la ruta de producción, no el respaldo.** El endpoint de webhook **NO se construye** (no puede dispararse en Development Mode: exige app Live + Advanced Access + Business Verification). Lo que sí se construye es **la costura** que lo admitirá después.
  - **Test de la costura:** sustituir la fuente de eventos (pull por push) **no reescribe** el servicio de normalización ni el repositorio. Verificable porque ambos dependen de una interfaz, no del transporte.
  - **De-duplicación por `external_message_id`**, apoyada en `UNIQUE(connection_id, external_message_id)` con **upsert idempotente**. Test: correr la sincronización dos veces seguidas sobre el mismo payload **no crea filas nuevas** y **no altera `last_message_at`**.
  - **NO se introduce Redis `SETNX`.** La decisión de 2026-07-28 (`0004_inbox.py:136-138`) es explícita: a un tenant, cadencia de minutos, sin webhook concurrente, la constraint lo cubre **sin una segunda dependencia**. El criterio de C-08 en `backlog-crm-workflows.md` §5.3 que pide dos capas queda **superado**.
  - **Un comentario nuevo a mitad de paginación desplaza la ventana** — está documentado en `INCREMENTAL_POLLING_NOTE` y el servicio debe ser correcto bajo ese régimen (la de-dup por id lo absorbe). Test con paginación desplazada.
  - **La frecuencia de sincronización es un parámetro de producto declarado**, con su consecuencia de coste explícita: el presupuesto de Development Mode es **200 llamadas/hora**, y como el poll no puede ser incremental por tiempo, **más frecuencia no compra frescura proporcional — compra riesgo de agotar el presupuesto**.
  - `uv run pytest -m "not integration"` verde sin red; los tests de constraint llevan marca `db`.
- **Fase:** Fase 1 Parte 4-B.
- **Evidencia:** hallazgo del architect [01:13](c) (*"un `POST /inbox/sync` da exactamente la misma corrección de datos que un beat cada 5 minutos, sin introducir Celery"*) · `0004_inbox.py:136-138` (la decisión anti-SETNX, literal) · `ig_shapes.py:263,265` · `backlog-crm-workflows.md` §4.3 (POLL-FIRST, con las citas de `webhooks.md:60-73` y `conversations-api.md:19-20`) · §5.3 C-08.
- **Prioridad / tamaño:** **P1 / M**
- **Dependencias:** **A0**, **B1**, **B3**, **C1**. Construye sobre `migrations/postgres/versions/0004_inbox.py`.
- **`[dep V-TP-2]`: NO.**

### B3 — Normalización de hilos y mensajes, con provenance

- **Historia:** Como equipo de community de una marca, quiero que cada comentario quede guardado con su origen y su fecha de llegada, para poder auditar de dónde salió cualquier cosa que la bandeja me muestre.
- **Criterios de aceptación:**
  - Cada comentario se materializa como fila de **`messages`** colgada de un hilo en **`threads`** (nombres reales — ver §1.3).
  - **Clave natural del hilo:** `UNIQUE(connection_id, channel, external_thread_id)`. Re-sincronizar **actualiza** el hilo, no crea uno nuevo.
  - **`shape_version` es obligatorio y se rellena con `ig_shapes.SHAPE_VERSION`** (`"ig-comment-shapes-1.0.0"`), nunca con una cadena literal. Es la provenance de bajo qué contrato se parseó la fila y lo que hace un re-parse posible.
  - **Provenance completa por fila:** `tenant_id`, `connection_id`, `external_message_id`, `shape_version` y `raw_payload_r2_key` cuando se archive el crudo. La regla de la casa (`CLAUDE.md`, *"toda señal derivada lleva provenance"*) aplica a la ingesta de primera parte igual que al scraping.
  - **Los nulos se respetan como contrato, no se rellenan:** `author_external_id`/`author_username` **nulos cuando falta `instagram_manage_comments`** (`Presence.REQUIRES_PERMISSION`), `posted_at` **nulo cuando el `timestamp` no vino** (`Presence.IF_REQUESTED`). **Prohibido fabricar un timestamp**: el orden cae a `ingested_at`.
  - **`last_inbound_at` se actualiza sólo con mensajes `direction='inbound'`; `last_message_at` con cualquiera.** Test que los desacopla explícitamente: un mensaje saliente mueve `last_message_at` y **NO** `last_inbound_at`.
  - **No se crea ninguna columna `window_expires_at`** ni ninguna copia materializada de la ventana (condición B2, `0004_inbox.py:16-19`). Si se muestra una ventana, se **calcula** desde `last_inbound_at`.
  - **`author_external_id` no se une contra ningún otro identificador de persona** (`IGSID_IS_PORTABLE_IDENTITY is False`, `ig_shapes.py:154`). Test estático o revisión con criterio escrito.
  - `threads.assigned_agent_id` **existe y se deja nula**. No se construye UI de asignación (parking lot).
  - Todo acceso vía **`tenant_session`** (RLS). Test `db` de aislamiento cruzado.
  - `uv run pytest -m "not integration"` verde sin red.
- **Fase:** Fase 1 Parte 4-B.
- **Evidencia:** `0004_inbox.py:9-28` (condiciones B1/B2 y el origen de cada nulabilidad), `:56-103` (`threads`), `:105-156` (`messages`) · `ig_shapes.py:49,154` · hallazgo del PO en el sprint-state [01:11].
- **Prioridad / tamaño:** **P1 / M**
- **Dependencias:** **B1**. Construye sobre `migrations/postgres/versions/0004_inbox.py` y `packages/shared/src/qualify_shared/social/ig_shapes.py`.
- **`[dep V-TP-2]`: NO.**

### B4 — El **bucle de aprobación** y el seam `DraftProvider` — no el generador

> 🔴 **REESCRITA ENTERA tras el veredicto del datasci [2026-07-31 01:17 y 01:22]. Lo in-sprint es la fontanería del bucle humano; el generador NO.**
>
> **Razón:** el sprint es fontanería y **no existe ni un solo comentario real en base** (`messages` vacía, el flujo muere en `link_required`). **Construir un generador de borradores antes de que exista el primer mensaje real es construir contra evidencia cero** — precisamente lo que la auditoría del 65 % dice que no volvamos a hacer. El generador real es **un día de trabajo cuando haya corpus**; el bucle de aprobación sin telemetría es **deuda permanente**.

- **Historia:** Como equipo de community de una marca, quiero aprobar, editar o descartar cada respuesta antes de que salga, y que quede constancia de qué hice con ella, para responder más rápido sin que se envíe nunca en mi nombre nada que yo no haya visto.
- **⚠ Estado:** **el datasci recomienda que esta historia CAIGA del sprint**, y este backlog lo suscribe (ver §6). Se conserva especificada porque si entra, entra así y no de otra forma.
- **Criterios de aceptación — lo que SÍ es in-sprint (fontanería pura, cero modelos):**
  - **NO EXISTE CAMINO DE CÓDIGO QUE ENVÍE SIN ACCIÓN HUMANA EXPLÍCITA.** Test negativo obligatorio. No depende de ningún modelo.
  - **Máquina de estados de aprobación**: `draft` → `approved` → `sent` / `discarded`, con `approved_by` y `approved_at`. Es lo caro de retrofitear y es plomería, que es de lo que va este sprint.
  - **Seam `DraftProvider` typed**, con la misma forma que `SentimentProvider` (`packages/models/src/qualify_models/providers.py`). **Dos implementaciones: un stub determinista** (para tests, offline) **y un hueco declarado** para la llamada real. Provenance obligatoria en el resultado: `model_id` + `prompt_version`.
  - **Telemetría aceptar / editar / descartar, más el diff de edición.** Esto **no es analítica de producto**: es **el único camino por el que este proyecto llegará a tener una medición real de calidad de borrador**, que es exactamente lo que hoy no existe. Sin ella, dentro de tres sprints seguiremos citando una cifra calculada con Bayes en julio de 2026.
  - **Puerta determinista de entrada degenerada — criterio duro y cerrable este sprint:**
    > Existe `classify_comment_shape(text: str | None) -> CommentShape` con `CommentShape ∈ {EMPTY, EMOJI_ONLY, MENTION_ONLY, TOO_SHORT, NON_TARGET_LANGUAGE, ELIGIBLE}`. Un fixture de **60 comentarios etiquetados a mano** (10 por clase) se clasifica **60/60 exactos**. **Ningún comentario con forma distinta de `ELIGIBLE` alcanza el generador ni el clasificador de polaridad** — test negativo sobre la ruta.

    **60/60 es exigible porque es determinista:** si falla uno, la regla está mal, no el modelo. Etiquetador: cualquier ingeniero, ~30 minutos. **Es la única pieza de la capa de IA de B4 que puede cerrarse este sprint con criterio duro.**

    **Y no es un caso borde:** en comentarios de Instagram, plausiblemente **entre el 40 % y el 60 %** del corpus es entrada degenerada — sólo emoji (`🔥🔥`), sólo tag (`@maria mira esto`), una palabra, o no-español. *(Rango a ojo, **sin medir, porque no hay corpus** — se declara como estimación, no como dato.)* robertuito **emitirá una etiqueta confiada sobre `🔥🔥`**. Eso no es un fallo del modelo: es que se le está preguntando algo que no tiene respuesta. **La puerta es determinista y va ANTES de cualquier modelo**, clasificando por forma del texto (recuento de tokens alfabéticos, proporción de emoji/menciones, detección de idioma), nunca por polaridad.
  - **Frontera de medio propio como condición de alcance, no como flag:** cubre comentarios en **contenido propio del tenant**.
  - El borrador arrastra los `source_id` de lo que usó para fundamentarse: el aprobador **puede comprobar la afirmación en vez de confiar en ella**.
  - `uv run pytest -m "not integration"` verde sin red.
- **Criterios que NO se cierran este sprint, y por qué (esto sustituye a los antiguos `[pendiente reto datasci]`, ya resueltos):**
  - **Puerta de polaridad (robertuito):** si entrase, **el criterio no puede ser accuracy agregada**. Sería *macro-F1 estratificado por longitud* (buckets 1-3 tokens alfabéticos / 4-15 / >15), **reportando la baseline de clase mayoritaria en cada bucket junto a la métrica**; aceptación = macro-F1 supera la baseline de mayoría en el bucket >15, y el bucket 1-3 se declara **fuera de cobertura** (lo cubre la puerta determinista, no el modelo). **No se escribe ningún número de umbral, y ése es el punto.**
  - **Calidad del borrador:** **no existe conjunto dorado y no se puede construir este sprint**, ni con capacidad infinita — **falta la materia prima**. Lo que genera esa materia prima es la telemetría de arriba. El dimensionado del conjunto (n=100, Wilson 95 %) va al parking lot §7 como historia del sprint siguiente.
- **Corrección a la justificación de la puerta barata — no se quita la puerta, se le cambia el argumento:**
  > La versión anterior justificaba la puerta con *"una conversación de 3 turnos cuesta el 119 % de lo que ese contacto ingresa"*. **Ese 119 % es sobre la economía de precios por contacto de ManyChat, no sobre la de Qualify**: `eval/conversation_cost.py` divide por `PlanEconomics.revenue_per_included_contact`, que son los planes de ManyChat. **Qualify tiene dos tenants y ningún modelo de precios por contacto.**
  >
  > **Coste real, cerrado por el datasci:** **~$0,0013 por borrador** con Haiku 4.5 (700 tok entrada / 120 tok salida, sin RAG porque no hay embeddings en Fase 1), **~$2/mes** a 1.500 comentarios. **Techo del peor escenario construible en este sprint** —Opus 5 generando todos los borradores, sin puerta, a 10× el volumen— **~$98/mes**.
  >
  > **Consecuencia vinculante: ninguna historia de este sprint se dimensiona ni se justifica por ahorro de coste de inferencia, y ninguna decisión de diseño se toma para abaratar la llamada al LLM.** A dos tenants el coste de la capa de IA está por debajo del ruido frente a Zyte, el VPS o una hora de ingeniería. **La puerta se mantiene, pero por calidad y superficie de fallo, no por coste** — tal como estaba escrita, un lector futuro concluiría que existe para ahorrar dinero, mediría $2/mes, y la quitaría.

> 🔴 **CORRECCIÓN DEL FUNDAMENTO — auditoría del data-scientist-fde [2026-07-31 01:13]. Este backlog NO cita el 65 % como base de la regla.**
>
> **La regla se mantiene intacta: respuestas autónomas fuera, permanentemente.** Lo que cambia es su fundamento, porque el que circulaba era falsable y estaba mal extrapolado.
>
> **Qué es realmente el 65 %** (`packages/models/NOTES_manychat_activation_layer.md` §2.2, línea 148): una precisión **calculada con Bayes, no medida** — `Precision = TPR·π / (TPR·π + FPR·(1−π))` con **TPR 0,85 / FPR 0,05 supuestos** (*"a reasonable zero-shot NLI operating point"*) y **π ≈ 10 % declarado por el propio fichero como *"a stated modelling assumption, not a measurement"***. El fichero remata: *"It is the **ratio between rows**, not the absolute, that carries the argument."* La cadena de citas posteriores se quedó con el absoluto y tiró el aviso.
>
> **Y describe la tarea equivocada:** el 65 % es la precisión de un **detector de intención**, no la calidad de un **texto generado**. En este repo **no existe ni una sola medición de calidad de borrador**, en ningún idioma, sobre ningún conjunto. Peor: en modo asistido un falso positivo del disparador es **el fallo barato por construcción** — el humano ve un borrador que no aplica y lo descarta. La cifra que se citaba como prueba de que lo autónomo es inviable **describe literalmente el error que el modo asistido ya absorbe**.
>
> **El fundamento correcto, y es más fuerte:**
> 1. **(a) Ausencia total de evidencia.** Cero mediciones de calidad de borrador sobre comentarios en español en este repo. Enviar sin aprobación humana sobre evidencia nula es injustificable **con independencia de qué número se cite**.
> 2. **(b) Asimetría irreversible del coste del error.** Un envío autónomo equivocado es la marca hablando, es irrecuperable y es capturable en pantalla.
> 3. **(c) Vertical regulada.** Cliente uno es inmobiliaria: un envío autónomo que afirme algo sobre disponibilidad o cualificación lo responde el brokerage (Fair Housing), y Platform Terms **§3.a.ii nombra "housing"**.
>
> **Riesgo de no corregirlo:** el 65 % es un número falsable pegado a una regla declarada *permanente*. Si mañana alguien mide una tasa de aceptación de borradores del 85 % — perfectamente posible, **porque es otra métrica de otra tarea** — los docs invitan a reabrir una decisión que no debería depender de esa cifra. **La regla es más robusta sin el número que con él.**
>
> **Ficheros que siguen citándolo mal y NO son míos** (corrección pendiente de sus dueños): `CLAUDE.md:226`, `docs/arquitectura.md:288` y `:877` (ADR 21 — **architect**), `docs/integracion-cuentas-conectadas-meta.md:445,470,556` (**architect**), `docs/registro-validacion-features.md:130`. En **mis** ficheros: `docs/backlog-crm-workflows.md:569,571,861` — pendiente, fuera del alcance de esta sesión, anotado aquí para que no se pierda.

> ⚠ **W4-Q6 queda SUPERADA POR CAUSA EXTERNA, no revocada — y conviene que se lea así.**
>
> `backlog-crm-workflows.md` §4.6 resolvió **"DM privado primero"** con dos razones: mejor precisión **y** coste del error acotado (*"un borrador de DM equivocado es privado, en un hilo que abrió el contacto, y recuperable; una respuesta pública equivocada es la marca hablando en público bajo su propio post"*). Se eligió deliberadamente **la superficie segura primero, para obtener telemetría sin el modo de fallo público**.
>
> **Esa opción ya no existe.** El recorte de DM no reordena preferencias: **elimina la alternativa segura**. El sprint queda forzado a la superficie que W4-Q6 había diferido por arriesgada. **Nadie debe leer mañana que "se decidió hacer comentarios primero" — no se decidió, se quedó sin opciones.**
>
> **Dos consecuencias duras:**
> - **La restricción de ManyChat deja de ser opcional.** *"Generar sólo para polaridad positiva"* estaba planteada como *"cuando lleguen los comentarios públicos"*. **Los comentarios públicos son este sprint.** Si B4 entra, esa puerta entra con él. Composición que conviene registrar: esa puerta **es exactamente polaridad de 3 clases, es decir, lo único que robertuito sabe hacer** — su único trabajo legítimo en toda la bandeja.
> - **R6 y B4 viven o mueren juntas.** Si B4 entra, la puerta de polaridad entra, y entonces **R6** (sustituir robertuito por un modelo con licencia limpia) está en la ruta crítica de la única historia generativa del sprint. Si B4 cae, R6 sale de la ruta crítica.

- **Fase:** Fase 1 Parte 4-B (ADR 21c, sólo modalidad asistida). **Es escritura a plataforma** (`POST /<IG_COMMENT_ID>/replies`), luego hereda **A0**, `instagram_manage_comments` y la misma condicional de `ads_management`.
- **Evidencia:** veredictos del datasci en `.claude/sprint-state-2026-07-31-po-sprint3.md` [01:13], [01:17], [01:18], [01:21], [01:22] · `packages/models/NOTES_manychat_activation_layer.md` §0.4 (ManyChat autogenera **sólo** para comentarios positivos: *"no es un hueco de producto, es gestión de riesgo disfrazada de feature"*) y §2.3 (errores de identificación de idioma en mensajes muy cortos) · `packages/models/src/qualify_models/eval/conversation_cost.py:77-81` (constantes del prompt, en disco) · `backlog-crm-workflows.md` §4.5, §4.6 W4-Q6.
- **Prioridad / tamaño:** **P3 / M** — **recomendado FUERA del sprint** (§6).
- **Dependencias:** **A0, B1, B2, B3**. Construye sobre `packages/models/src/qualify_models/providers.py` (el seam) y la FSM de aprobación nueva.
- ⚠ **Límite que no es de fase:** las respuestas autónomas quedan fuera y **ningún sprint posterior las desbloquea**. Cambiarlo exige una **medición de calidad de borrador** que hoy no existe, no una fase nueva.
- 🏠 **Bandera §3.a.ii/housing — cuatro reglas, verificables por test estático.** La frontera **no es "¿es un score?"**: es un compuesto. Una historia queda marcada si el score es de **persona** (no de texto) **y** gobierna un **filtro** (no una permutación) **y** se **persiste** contra identidad. Traducido a reglas de código, con el patrón de test estático que este repo ya usa (`test_object_store_sanctity.py`, `test_gate_coverage.py`):
  1. **Ninguna columna de score/prioridad cuelga de una tabla con forma de persona**, ni tiene `author_external_id` como clave. Los scores cuelgan de `messages` o `threads`. *(Extensión natural de `0004_inbox.py:118-121`, que ya prohíbe unir el IGSID contra otro identificador de persona.)*
  2. **Ningún score aparece en un `WHERE`/`HAVING` que elimine filas.** Sólo en `ORDER BY`. Toda fila puntuada sigue visible en alguna posición.
  3. **Ningún score se persiste indexado por identidad de persona.**
  4. 🔴 **El prompt del generador recibe texto del hilo, NUNCA un atributo derivado de la persona.** *(Regla que no está en §8.3.3 y que es la que se escaparía.)* Si el prompt incluye *"este contacto parece comprador serio / presupuesto bajo / poco cualificado"*, entonces **el score existe, vive dentro del LLM, no está registrado y no es auditable**: se cumplirían formalmente las tres reglas anteriores y el sistema seguiría puntuando personas para decidir cómo se les trata en materia de vivienda, **sin ninguna traza**. **Un score no deja de serlo por vivir en un prompt.** Es tan verificable como las otras: es una aserción sobre qué campos se serializan al prompt.

  **Con estas cuatro reglas, B4 tal como está especificada queda FUERA de la bandera** — no puntúa personas, ordena una cola y redacta texto. Se declara porque el siguiente paso natural (ordenar la bandeja por un score de lead) **sí** la activaría.

---

## §5 Épica C — Deuda y cumplimiento

### C0 — 🔴 BLOQUEO DE ENTORNO, antes de asignar nada

> **No es una historia: es una precondición del sprint, y la ejecuta el lead, no un ingeniero.**
>
> El `.venv` compartido está **corrupto** (hallazgo del datasci, [2026-07-31 01:15], verificado): `uv run --no-sync pytest packages/models/tests --collect-only -q` → **8 errores de colección**, `83/90`. `.venv/bin/python -c "import qualify_models"` → `ModuleNotFoundError`. Los cuatro paquetes **siguen apareciendo** en `uv pip list` como editables con ruta correcta y los `.pth` existen y apuntan a rutas que existen — pero `site.addpackage()` no los inyecta en `sys.path`. **El síntoma es indistinguible de "no está instalado" mirando `uv pip list`; por eso engaña.**
>
> **Consecuencia directa para este backlog: cualquier criterio de aceptación que diga "los tests de `packages/models` pasan" es hoy INVERIFICABLE.** Un agente de `/team-dev` que arranque sobre este venv se deja las dos primeras horas aquí.
>
> **Único fix con precedente (dos veces en `CLAUDE.md`): `rm -rf .venv && uv sync --group ml`.** Debe coordinarlo el lead **cuando nadie más esté ejecutando nada** — no lo lanza un agente en paralelo.
>
> **Mitigación barata y sin riesgo, aplicable ya:** invocar siempre `record_finding.py` como `uv run --no-sync ...`. La skill lo documenta sin `--no-sync` y el script sólo usa stdlib (`argparse`, `datetime`, `sys`) — no necesita resolver el workspace. **Sospecha sin confirmar** de que ésa fue la causa (se observó `Uninstalled 2 packages / Installed 2 packages` inmediatamente antes); no hay causalidad probada, pero la mitigación es gratis.

### C1 — `Principal`: la causa raíz no es el global, es la ausencia de principal

> 🔴 **REESCRITA con el diagnóstico del architect [2026-07-31 01:18].** La versión anterior proponía una cabecera de operador. **Quitar el global no arregla nada por sí solo:** si el tenant pasa a venir de una cabecera de identificador, hemos convertido el `tenant_id` en un dato que **el cliente elige** — exactamente el bypass que `StartConnectRequest` documenta como intolerable. **La causa raíz es que no hay autenticación, luego no hay principal del que derivar un tenant.** Cualquier arreglo que no introduzca una **credencial** sólo muda el bypass de sitio.

- **Historia:** Como equipo de marketing de una marca, quiero que el sistema sepa quién soy y a qué cuenta pertenezco cuando opero desde fuera del CRM, para poder conectar y publicar sin que la API me rechace por no saber quién soy — y sin que nadie más pueda decir que es yo.
- **Criterios de aceptación — cuatro piezas, ninguna toca RLS ni las puertas sancionadas:**
  - **`Principal`**: dataclass congelada `(tenant_id: UUID, user_id: UUID)`. Es el tipo que la autenticación real producirá; **el resto del código nunca vuelve a cambiar**.
  - **Resolución por credencial opaca desde el entorno, sin migración:** `QUALIFY_DEV_PRINCIPALS="<token>:<tenant_uuid>:<user_uuid>,..."`. El cliente presenta `Authorization: Bearer <token>` — **presenta una credencial, no un identificador**, que es toda la diferencia entre autenticar y aceptar lo que le digan.
    - ❌ **Descartada la tabla de tokens en Postgres (migración 0005):** una tabla parece el principio de la autenticación de verdad e invita a construir encima; el mapa de entorno **se borra de un tirón** cuando llegue la real, no deja esquema que deshacer, y no añade una lectura a la ruta de request. **Es deuda que se ve.**
    - ❌ **Descartado un `ContextVar` alimentado por cabecera `X-Tenant-Id`:** es el global con mejor higiene de hilos y **el mismo agujero de autorización**.
  - **Dependencia `current_principal()`** en un `http/deps.py` nuevo, con el patrón de `get_connect_service` (default que lanza, sobrescribible en tests). **Devuelve `401`, no `409`.** El 409 de hoy **miente**: dice "conflicto de estado" cuando el hecho es "no estás autenticado", y esa mentira es la que hace que el fallo parezca un bug del servidor en vez de una credencial ausente.
  - **Las rutas toman `principal: Principal = Depends(current_principal)`** y pasan `principal.tenant_id` a los servicios. **Los servicios no cambian**: siguen llamando a `tenant_session(tenant_id)`.
  - 🔴 **`user_id` sale del cuerpo de la petición en la misma pasada.** `StartConnectRequest` omite `tenant_id` a propósito **pero declara `user_id: UUID` en el cuerpo** (`connections_routes.py:40-44`) — **es la misma clase de bypass, menos visible**: el cliente elige a quién se le atribuye la conexión, y ese `user_id` acaba en `connection_events` **como actor**. Con `Principal` en su sitio, sale del principal y **desaparece del cuerpo**. **La historia que arregla el tenant arregla esto o no habrá una segunda ocasión barata.**
  - **Coherencia con R7 y con las puertas: total, porque el arreglo vive POR ENCIMA de la puerta.** Nada del GUC, del `NULLIF`, del `set_config(..., is_local => true)` ni de las políticas se toca. `tenant_session` sigue siendo el único camino a datos de tenant; **lo único que cambia es de dónde sale el UUID que se le pasa**. `admin_session` y `credential_session` no se rozan. Test que lo afirma.
  - **`qualify_shared.dev` sobrevive con un solo consumidor legítimo:** la UI Reflex, que corre **en proceso, un operador, una sesión** — el caso para el que se escribió y donde un global es honesto. **Se impide que nazca un segundo consumidor HTTP:** una línea en su docstring diciéndolo, y **ninguna llamada nueva a `get_dev_tenant()` desde `http/`** (verificable con `grep`).
  - Un token que no resuelve → **401**. Un principal cuyo tenant no contiene al usuario → **403**. Test con dos tenants sembrados.
  - `uv run pytest -m "not integration"` verde sin red; el test cross-tenant lleva marca `db`.
- **Fase:** Fase 1 (fundación multi-tenant, ADR 24 — *"el identificador es fundación, no endurecimiento"*). **No es Fase 6.**
- **Evidencia:** diseño del architect en `.claude/sprint-state-2026-07-31-po-sprint3.md` [2026-07-31 01:18] · `packages/shared/src/qualify_shared/dev.py:31-52` (el global y su docstring) · `packages/api/src/qualify_api/http/connections_routes.py:13-17`, `:40-44`, `:72-74` · ADR 24 en `CLAUDE.md`.
- **Prioridad / tamaño:** **P0 / M**
- **Dependencias:** ninguna. **La frontera exacta, sin redondear:**
  - **NO es precondición de A4, A5 ni de la composición** — todas reciben `tenant_id` como argumento y se testean sin HTTP. **Pueden empezar mañana sin esperar a nada.**
  - **SÍ es precondición dura de A7 y B2** (toda ruta HTTP nueva) **y de toda prueba empírica de extremo a extremo, incluida la del fundador con curl.**
  - **Es precondición barata que se encarece rápido:** cada ruta escrita contra `get_dev_tenant()` habrá que reescribirla. Con dos rutas es trivial; con las seis u ocho que este sprint añade, deja de serlo. → **va primera o segunda del sprint, en paralelo con A4, y terminada antes de la primera ruta.**
- **`[dep V-TP-2]`: NO.**

### C2 — El endpoint de borrado/desautorización (**el único de los cinco huecos que es código**)

> ⚠ **DESAGRUPADA tras el reto del architect [01:23].** La versión anterior metía los cinco huecos de Platform Terms en una sola historia. **De los cinco, sólo uno es código.** Mezclar cuatro entregables administrativos con uno de ingeniería **infla el sprint y esconde que cuatro no consumen capacidad de ingeniería**. Los otros cuatro van al **Bloque 0** de abajo, con el precedente de `docs/backlog-crm-workflows.md` §5.1.

- **Historia:** Como persona cuyos comentarios trata Qualify, quiero poder pedir que se borren mis datos y que se corte el acceso de la app, para no depender de que alguien se acuerde de hacerlo a mano.
- **Criterios de aceptación:**
  - Endpoint de **deauthorize callback** y endpoint de **data deletion callback**, ambos con test. *(Hoy: **cero** ocurrencias de `deauthorize` / `data_deletion` / `deletion_callback` en el repo.)*
  - **El endpoint dispara la revocación real**, y es barato porque **`connections/revoke.py` ya existe** (idempotente, publicado en el seam de `connections/__init__.py`).
  - **La mecánica de borrado ya existe** (delete-by-prefix sobre `t/{tenant_id}/`, `packages/scraper/src/qualify_scraper/shared.py:252-262`); **lo que falta es la puerta**.
  - El endpoint es **idempotente**: dos llamadas para el mismo usuario no fallan la segunda.
  - `uv run pytest -m "not integration"` verde sin red.
- **Fase:** Fase 1 Parte 4 (cumplimiento de la vía de cuenta conectada). **No es Fase 6.**
- **Evidencia:** `integracion-cuentas-conectadas-meta.md` **§8.3.2** hueco 2 (§3.d.i.1), verificado contra el repo el 2026-07-30 · §8.3.1 (la mecánica de borrado y `revoke.py` ya existen) · reto del architect [01:23] sección Épica C.
- **Prioridad / tamaño:** **P2 / S**
- **Dependencias:** **C1** (es una ruta HTTP). Construye sobre `packages/api/src/qualify_api/connections/revoke.py` y `qualify_shared.objects`.
- **`[dep V-TP-2]`: NO** — pero comparte disparador temporal con ella: **vincula cuando el primer agente de cliente uno use el producto**, no en App Review.

### C2-bis — **Bloque 0: cuatro entregables que NO consumen capacidad de ingeniería**

> **No son historias de sprint y no se asignan a ningún ingeniero.** Son documentos, URLs y una cláusula. Se registran con la **misma fecha de vencimiento** —*"cuando el primer agente de cliente uno use el producto"*— para que no se pierdan ni inflen el presupuesto. **Dueño: el fundador** (ver §8.2 F3).

| # | Entregable | § Platform Terms | Estado verificado | Coste |
|---|---|---|---|---|
| 1 | **Política de privacidad pública**, accesible, **no geobloqueada**, que explique qué datos se tratan, para qué y cómo pedir su borrado. Su URL vive en configuración | 4.a, 4.b, 4.c | `grep` sobre `packages/`, `Qualify/`, `migrations/` → **cero** | Bajo, **pero es entregable de App Review** |
| 2 | **Política de retención escrita**: qué decide cuándo un dato "deja de ser necesario" | 3.d.i.2.a | **cero** ocurrencias de `retention`/`ttl`/`purge` | Bajo en código, **decisión de producto** en realidad |
| 3 | **Canal de reporte de vulnerabilidades**: `SECURITY.md` y/o `.well-known/` | 6.a.ii | verificado por `ls`, no existe | **Trivial** |
| 4 | **Cláusula en los ToS con el tenant** que le prohíba contractualmente violar los términos o políticas de Meta | 5.b.ii.4.a | no hay ToS en el repo | Bajo — **una cláusula, no un contrato nuevo** |

**Nota operativa que conviene entender antes de escribir la #2:** el derecho de auditoría de Meta **sobrevive un año** y **hasta que se hayan borrado afirmativamente todas las copias** (§7.c.vii). **Borrar de verdad es lo que cierra la ventana**; guardar "por si acaso" la alarga.

🏠 **Bandera §3.a.ii/housing sobre el entregable #1:** la política de privacidad debe redactarse sabiendo que **§4.c la convierte en el límite legal de lo que se puede hacer con los datos** (*"tratar los datos sólo como diga nuestra política de privacidad"*). **Una política escrita a la ligera estrecha o ensancha lo que Fase 4 podrá hacer.** Redactarla es una decisión de producto con consecuencia de roadmap.

### C3 — Declarar `boto3` y reparar el ritual de sincronización

- **Historia:** Como equipo de desarrollo, quiero que el cliente de almacenamiento de objetos se pueda instanciar de verdad, para que el vídeo que el usuario sube llegue a algún sitio y no sólo a un doble de test.
- **Criterios de aceptación:**
  - `boto3` (y `botocore`) declarados en `packages/shared/pyproject.toml`. *(Hoy: `grep -rn boto3` sobre `*.toml` y `*.lock` → **cero**; `packages/shared/pyproject.toml` declara sólo `pydantic`, `sqlalchemy`, `psycopg`.)*
  - El import perezoso de `objects/s3.py:23-25` **se mueve a nivel de módulo** y **se borra la nota** que explica por qué estaba diferido — pero **el guardián estático de `tests/test_object_store_sanctity.py` se queda** (lo dice el propio docstring: *"leave the guard"*).
  - **El ritual se ejecuta como una sola operación coordinada por el lead:** `rm -rf .venv && uv sync --group ml`. **Nunca alternando `uv sync` ↔ `uv sync --group ml`** — eso, y no la concurrencia, es lo que corrompe el venv (dos precedentes en `CLAUDE.md`).
  - Tras el ritual: `uv run --no-sync pytest -m "not integration"` **verde**, y `.venv/bin/python -c "import qualify_models, qualify_shared, qualify_api, qualify_scraper"` sin error.
  - `R2ObjectStore` se puede **instanciar** en el workspace (con settings falsos; no requiere bucket real).
- **Fase:** Fase 1 (habilitación de infraestructura de Parte 4-A).
- **Evidencia:** hallazgo del architect [2026-07-31 01:13](b) (*"`R2ObjectStore` no se puede instanciar en este workspace hoy"*, verificado con `grep`) · `packages/shared/src/qualify_shared/objects/s3.py:1-14` (el docstring que documenta la deuda y su condición de cierre) · `CLAUDE.md`, trampa operativa del venv compartido.
- **Prioridad / tamaño:** **P1 / S** (código trivial; el riesgo está en el ritual, no en el diff)
- **Dependencias:** **C0** (el venv ya está roto; conviene hacer C0 y C3 en la misma operación). **Bloquea el camino real de A3.**
- **`[dep V-TP-2]`: NO.**
- ⚠ **Coordinación obligatoria:** esta historia toca `uv.lock`. **Ningún otro agente puede estar ejecutando nada** mientras corre.

### C4 — Aprovisionar el bucket R2 y sus credenciales

- **Historia:** Como equipo de marketing de una marca, quiero que el vídeo que subo se guarde en un almacenamiento real de la empresa, para que publicar no dependa de un fichero que sólo existe en la máquina de alguien.
- **Criterios de aceptación:**
  - Existen las **cuatro variables obligatorias sin fallback** que `R2Settings.from_env()` exige: `QUALIFY_R2_ENDPOINT_URL`, `QUALIFY_R2_ACCESS_KEY_ID`, `QUALIFY_R2_SECRET_ACCESS_KEY`, `QUALIFY_R2_BUCKET`. *(Hoy: `.env` en la raíz tiene exactamente cuatro variables y **las cuatro son de Meta**; **ninguna `QUALIFY_R2_*`**.)*
  - El bucket **no es público**. `ObjectGate` no expone `presign_get` **por diseño** (ADR 28b) y ADR 28a elimina la necesidad de una URL pública: Meta **nunca hace `cURL` de una clave nuestra**, recibe los bytes por `rupload`. Un bucket público sería un activo expuesto permanentemente **sin ninguna contrapartida**.
  - Ninguna credencial entra en git. `R2Settings.__repr__` ya redacta el secreto; el test lo afirma.
  - Un test marcado `integration` (fuera de CI) escribe y lee un objeto real bajo `t/{tenant_id}/` y verifica que una clave fuera del prefijo es rechazada.
  - `just test` (`-m "not integration"`) **sigue verde sin credenciales R2** — un desarrollador sin bucket puede trabajar.
- **Fase:** Fase 1 (habilitación de infraestructura de Parte 4-A).
- **Evidencia:** hallazgo del architect [2026-07-31 01:13](b) (*"no hay evidencia en disco de que exista una cuenta R2 ni un bucket aprovisionado"*, verificado sobre `.env`) · `packages/shared/src/qualify_shared/objects/config.py` (`from_env`, cuatro variables sin fallback, `__repr__` redactado) · `objects/gate.py` (`presign_get` ausente por ADR 28b) · §1.3 de este documento (por qué la URL firmada ya no hace falta).
- **Prioridad / tamaño:** **P1 / S** en ingeniería — **pero es una decisión y un gasto del fundador**, no una tarea de código (ver §8).
- **Dependencias:** **C3**. **Bloquea el primer publish real** (no los tests).
- **`[dep V-TP-2]`: NO.**

---

## §6 Orden de ruta crítica y dimensionado

> 🔴 **REESTRUCTURADA. El lead resolvió K2 y decidió NO lanzar dos ingenieros de backend.** La forma del sprint cambia en consecuencia. **Las dos opciones se presentan abajo para que el fundador elija sin releer el documento entero: el recorte es una RECOMENDACIÓN, no un hecho consumado.**

### 6.1 Por qué esto es una cadena y no un abanico

**Sin endpoint de publicación no hay producto que enseñar.** Ése es el criterio de orden. Y el architect añade la razón que lo convierte en cadena: **L1→L2→L3→L4→L5 (modelos → repositorio → servicio → composición → rutas) es trabajo serial sobre los mismos ficheros. No lo paralelizan cuatro personas.**

```
C0 (venv) → C3 (boto3) → C4 (bucket R2)      [infra, en paralelo]
                              │
A0 (token de Página) ─────────┼──→ bloquea A5, A6, A7 y TODA la épica B
     │                        │
     ├→ A1 (config_id) → A2 (grafía del scope)
     │
C1 (Principal) ──────────┐    │
     │                   │    │
     └→ A3 (staging/L6) ─┴────┴→ A4 (repo) → A5 (start+advance) → A6 (reconcil.) → A7 (rutas)
```

### 6.2 Tabla de prioridad y tamaño

| # | Item | Prio | Tam | Bloquea a | `[dep V-TP-2]` | 🏠 |
|---|---|---|---|---|---|---|
| C0 | Reparar el venv compartido | **Precondición** | — | todo | no | — |
| **A0** | **Token de Página + aviso de PPA** | **P0** | **S–M** | **A5, A6, A7 y toda la épica B** | no | — |
| A1 | `config_id` en `authorization_url` | **P0** | S | A2, A5, A7, épica B | no | — |
| A2 | Grafía del scope, empírica | **P0** | S | A5 | no | — |
| C1 | `Principal` (401, `user_id` fuera del cuerpo) | **P0** | M | A7, B2, toda prueba e2e | no | — |
| A3 | Staging del media a R2 (**L6**) | **P0** | S | A5 | no | — |
| A4 | Repositorio write-ahead + idempotencia (**L1+L2**) | **P0** | M | A5, A6 | no | — |
| A5 | Servicio `start` + `advance` (**L3+L4**) | **P0** | **M** | A6, A7 | no *(era `PARCIAL`)* | — |
| A6 | Reconciliación por `creation_id` (**L8**) | **P0** | M | A7 | no | — |
| A7 | Rutas HTTP (**L5**) | **P1** | M | — | no | — |
| C3 | Declarar `boto3` | **P1** | S | A3 (camino real) | no | — |
| C4 | Aprovisionar bucket R2 | **P1** | S | primer publish real | no | — |
| — | — | — | — | — | — | — |
| B1 | Cliente de lectura de comentarios | **P1** | M | B2, B3 | no | — |
| B3 | Normalización de hilos/mensajes | **P1** | M | B2, B4 | no | — |
| B2 | Sincronización manual (pull) | **P1** | M | B4 | no | — |
| C2 | Endpoint deauthorize/data-deletion | **P2** | S | primer usuario real | no | — |
| B4 | Bucle de aprobación + `DraftProvider` | **P3** | M | — | no | no aplica (4 reglas declaradas) |

**Fuera de la tabla, sin consumir capacidad de ingeniería:** **C2-bis** (los cuatro entregables administrativos, dueño el fundador).

### 6.3 Las dos formas del sprint — **el fundador elige**

#### Forma A — RECOMENDADA: publicación completa, bandeja al Sprint 4

**11 items: C0, A0, A1, A2, C1, A3, A4, A5, A6, A7, C3, C4.**

- **Un solo ingeniero de backend**, con propiedad de `packages/api/` extendida explícitamente en el prompt.
- Coincide con el dimensionado del architect: *"L1-L8 + declarar boto3 + aprovisionar R2 + `config_id` + deuda de tenant = **entre 9 y 11 items, y ésa ya es la capacidad real del sprint**"*.
- **Qué se entrega:** un reel se sube, se publica y se reconcilia, desde una ruta HTTP autenticada, contra una cuenta real en Development Mode.
- **Qué NO se entrega:** ninguna bandeja. El fundador no ve un solo comentario en el CRM al final del sprint.

#### Forma B — publicación recortada + bandeja mínima

Metería B1+B3+B2 a costa de **sacar A6 (reconciliación) y A7 (rutas)** del sprint.

- **Por qué este backlog NO la recomienda:** sacar A6 significa entregar publicación **sin** la protección contra doble publicación, y ADR 22(e) la llama *"la regla más estricta del sistema entero"*. Sacar A7 significa que no hay ruta HTTP, es decir **no hay nada que enseñar** — que es el encuadre del §0 negado.
- **Se registra porque la decisión de aceptar publicación sin bandeja es del fundador, no de ingeniería.**

### 6.4 La pregunta que decide, formulada para que sea respondible

> **¿Aceptas terminar el sprint con publicación funcionando de extremo a extremo y CERO bandeja, o prefieres media publicación y media bandeja?**

Este backlog recomienda **Forma A** y la razón es del propio encuadre: **sin endpoint de publicación no hay producto que enseñar**. Media bandeja tampoco lo es.

### 6.5 Épica B — aparcada al Sprint 4, con su razón

**B1, B2, B3 y B4 salen del Sprint 3.** No es un juicio sobre su valor:

1. **Dependen de A0**, que es la última pieza en descubrirse y la primera en la cadena.
2. **El presupuesto es de 5-6 tareas por compañero** y la épica A ya lo consume entero con un solo backend.
3. **La cadena de la épica A es serial sobre los mismos ficheros** — meter la B no la acelera, sólo abre un segundo frente sobre un ingeniero que ya está saturado.

**Lo que NO cambia por aparcarla:** los recortes ya decididos siguen vigentes cuando llegue — sólo comentarios, sin scheduler, pull manual, y el sentimiento sólo como campo de triaje, nunca como panel.

---

## §7 Parking lot — con la fase propietaria y la dependencia declarada

> Nada de aquí entra al sprint. Se registra con su dueño de fase para que no se cuele por la puerta de atrás ni se pierda.

| Item | Fase propietaria | Dependencia declarada | Por qué no ahora |
|---|---|---|---|
| **Programación diferida** (consumidor de `scheduled_posts`, scheduler, disparo por hora) | **Fase 1 Parte 3** | **Celery + Beat + servicio worker en compose.** Verificado: `grep -rl celery` → **cero**; `docker-compose.yml` = `postgres` + `redis`; `packages/pipeline/` no existe | Construirlo aquí es **arrancar la Parte 3 dentro de un sprint de publicación** — y la Parte 3 es la ruta crítica de otra cosa (el pipeline de ingesta). La DDL ya está aplicada; la historia futura la rellena **sin migración nueva**. ⚠ **Alternativa descartada:** un `POST /scheduled-posts/{id}/run` manual — la UI diría "programado" y alguien tendría que apretar. **Promete un reloj que no existe** |
| **Épica B entera (bandeja de comentarios): B1, B2, B3, B4** | **Fase 1 Parte 4-B** — sigue en fase, sólo se difiere de sprint | **A0** (token de Página) + presupuesto de 5-6 tareas por compañero con **un solo** ingeniero de backend | Ver §6.5. Los recortes ya decididos siguen vigentes cuando llegue: sólo comentarios, sin scheduler, pull manual, sentimiento sólo como campo de triaje |
| **Conjunto dorado de calidad de borrador (n=100)** | Fase 1 Parte 4-B, sprint siguiente | **Corpus real**: hoy `messages` está vacía y el flujo muere en `link_required`. **Falta la materia prima, no la capacidad** | Dimensionado por el datasci (Wilson 95 %): n=100 → ±7,8 pp en p=0,80; **decide si vale la pena, no distingue 75 % de 80 %**. **Etiqueta la persona que enviaría la respuesta, no un ingeniero** (*"¿enviarías esto tal cual?"* es juicio de voz de marca). Etiqueta binaria + la edición real. **Solape de 30 items con un segundo etiquetador para medir Cohen kappa; si kappa < 0,4 el conjunto no es utilizable** y hay que reescribir la rúbrica antes de medir nada. ~2-3 h de etiquetado; **S de ingeniería** (el arnés ya existe: `eval/harness.py`, `metrics.py`, `schema.py`), **M de tiempo humano no-ingeniero**. El cuello de botella es el etiquetador |
| **Reporting / agregación / paneles de sentimiento** | **Fase 2** (Social listening + AI Insights) | — | **La frontera no es el modelo, es el consumidor:** un valor por fila en la bandeja es Parte 4-B; **un panel que agrega esos valores es Fase 2** y se colaría disfrazado de campo de base de datos |
| **Disparador de intención zero-shot NLI** (`bge-m3-zeroshot-v2.0`) | **Fase 3** | Un **taxón de etiquetas de intención curado y no solapado** que **no existe** y es trabajo de producto, no de ingeniería · test de licencia (R6) · latencia CPU sin medir | 568M params, **jamás ejecutado en este repo**. Y el cómputo escala con `mensajes × nº de etiquetas`: **añadir una quinta intención cuesta lo mismo que un 25 % más de volumen** |
| **Retrieval / RAG sobre la bandeja** | Fase 3-4 | Ningún modelo de embeddings comprometido en Fase 1 (`bge-m3` es *propuesto*) + corpus indexado | **Sin corpus indexado no hay nada que recuperar** |
| **Programación diferida vía endpoint manual** (`POST /scheduled-posts/{id}/run`) | Fase 1 Parte 3 | — | **Descartada explícitamente, no diferida:** la UI diría "programado" y alguien tendría que apretar. **Promete un reloj que no existe** |
| **Publicación de imágenes** | Fase 1 Parte 4-A · **QUA-68** | Superficie HTTP pública para el media | **No existe variante resumable para imagen** (`client.py:59`). Meterla reintroduce el alojamiento público que ADR 28 existe para evitar |
| **Carrusel como producto** (agrupación multi-ítem) | Fase 1 Parte 4-A | Publicación de imágenes (QUA-68) para el caso mixto | `is_carousel_item` existe en el cliente; el flujo de agrupación no. Y bajo el contador que ata (**contenedores**, no posts) un carrusel de 10 cuesta **11**, no 1 |
| **Bandeja de DM** | **Fase 6** (cross-canal) / desbloqueo parcial en 4-B | **Business Verification + Advanced Access** (la misma puerta de V-TP-2/A5-5) **MÁS** una acción manual del titular en la app de Instagram (*Ajustes > Mensajes > Controles > Herramientas conectadas*) **que ni la verificación desbloquea** | Dos exclusiones independientes en `ig_shapes.py`. **Si el fundador quiere DM, la respuesta no es "más ingeniería"** |
| **Endpoint de webhook** (push en tiempo real) | Fase 1 Parte 4-B, diferido | App **Live** + **Advanced Access** para `comments`/`live_comments` + **Business Verification** (`webhooks.md:57,60,63,73`) | Para cliente cero **no puede dispararse en absoluto**. Sería código imposible de ejercitar contra una cuenta real. **Lo que sí se construye ahora es la costura** (B2) |
| **BISU / Tech Provider** y todo lo dependiente | ADR 29 **`[PROPUESTO]`, sin firmar** | **Firma de ADR 29** | Config activa = **token de usuario**. Nada se construye contra un modelo de acceso no firmado |
| **UI de asignación multi-agente** (tomar/reasignar/escalar, bloqueo anti-colisión) | Sin fase (cliente uno) | Asientos multi-agente | Cliente cero tiene **un** asiento. La columna `assigned_agent_id` **ya existe nullable**; sólo la UI se aparca |
| **Respuestas autónomas** | **Fuera, y no es cuestión de fase** | Evidencia nueva: una **medición de calidad de borrador** que hoy no existe | Ver §4 B4. Fundamento: ausencia total de evidencia + asimetría irreversible del error + vertical regulada. **No** el 65 % |
| **Publicidad pagada / Marketing API** | Fase 5 | `ads_management`, otro app product, método de pago, Business Manager | **Cero líneas sobre Marketing API en todo el repo.** Necesita investigación desde cero antes de dimensionarse. **No es "publicación más grande"** |
| **Publicación programada en TikTok** | **Bloqueada, sin fecha** | Ninguna — **no hay mitigación de ingeniería** | `SELF_ONLY` + **la cuenta entera debe estar en privado al publicar**, *"regardless of account ownership"*. ADR 23(c): ni comprar ni construir |
| **Canal WhatsApp** | Sin fase | Investigación B0-5 (¿hereda la exención de Development Mode?) | Probablemente **el canal de cliente uno**; su prioridad sube cuando B0-5 cierre |
| **Bandeja unificada cross-canal** | **Fase 6** | Más de un canal ingiriendo | *Una bandeja no es unificada hasta que unifica más de un canal* (ADR 21/24) |
| **Señales tipadas + clasificador zero-shot NLI** (`bge-m3-zeroshot-v2.0`) | Fase 3 | Test de licencia (R6) + golden set | Doble rol confirmado (detector + disparador). **B4 no lo necesita para el primer tramo** |
| **Scoring de leads/creadores** | Fase 4 | 🏠 **Decisión de alcance del fundador o asesoría legal** sobre §3.a.ii/housing, **más** consentimiento válido por §3.a.v | **La Fase 4 hereda una restricción que el mapa de fases no registra**, y sólo en el vertical inmobiliario — el del cliente uno |
| **Renombrar `threads`/`messages`** a nombres con prefijo | Fase 6 (cuando llegue cross-canal) | — | **Riesgo asumido y declarado por el architect**, no defecto. Renombrar una tabla ya migrada por estética es peor que convivir con el nombre |
| **Listening de competidores, discovery, lookalike** | Fases 1(P2/P3)–4 | Pipeline de scraping (Parte 2/3) | **Estructuralmente inalcanzable por OAuth.** *Cualquier material de producto que insinúe monitorización de competidores desde cuentas conectadas es falso* |

---

## §8 Conflictos abiertos y decisiones que necesita el fundador

### 8.1 Conflictos entre documentos y realidad — surfaced, no resueltos por mí

| # | Conflicto | Quién lo resuelve |
|---|---|---|
| K1 | **El 65 % como fundamento de "autónomas fuera".** El datasci demuestra que es un cálculo bayesiano con TPR/FPR/π **supuestos**, sobre la **tarea equivocada** (precisión de un detector, no calidad de un generador). La regla se sostiene sobre (a)+(b)+(c); la cifra la debilita. Ficheros afectados que **no son míos**: `CLAUDE.md:226`, `docs/arquitectura.md:288` y `:877` (ADR 21), `docs/integracion-cuentas-conectadas-meta.md:445,470,556`, `docs/registro-validacion-features.md:130`. **Míos y pendientes:** `docs/backlog-crm-workflows.md:569,571,861` | **architect** (ADR 21) + PO en una sesión posterior |
| K2 | ~~`packages/api/` no está en el mapa de propiedad de `/team-dev`~~ | ✅ **RESUELTO por el lead:** se extiende la propiedad explícitamente en el prompt y se lanza **un solo** ingeniero de backend. Consecuencia: épica B al Sprint 4 (§6.5) |
| K7 | 🔴 **`ads_management` / `ads_read` chocan con ADR 21.** Ambas tablas de requisitos, columna Facebook Login, dicen lo mismo: *"If the app user was granted a role on the Page connected to your app user's Instagram professional account **via the Business Manager**, your app will also need `ads_management`, `ads_read`"* (`content-publishing.md:29`, `comment-moderation.md:20`). **El fundador administra sus Páginas desde Business Manager** — es el escenario descrito, no el excepcional. Y ADR 21 declara la publicidad de pago **explícitamente fuera de alcance** | **FUNDADOR** (ver §8.2 F7). No es arquitectura: es alcance de consentimiento y calendario de trámite |
| K8 | **PPA (Page Publishing Authorization) no aparece en ningún documento del expediente** — ni en `integracion-cuentas-conectadas-meta.md`, ni en el sprint-state. Es precondición dura **e indetectable por API** | **architect** (documentarla) + **fundador** (completarla preventivamente sobre su Página) |
| K3 | **`docs/integracion-cuentas-conectadas-meta.md` §4.2/§4.3 contradice el DDL aplicado** en tres puntos: tabla `publish_jobs` (real: `publish_attempts`), *"cada hilo lleva su fecha de expiración de ventana como columna"* (el architect la prohibió explícitamente, B2), e intake *"webhook"* (es POLL-FIRST) | **architect** — es su fichero |
| K4 | **`CLAUDE.md` declara que `revoke_connection` no existe.** Existe desde 2026-07-28 (`connections/revoke.py` + 2 suites) | **architect** |
| K5 | **`docs/modelos-multimodal-fase1.md` conserva la fila de visión sin corregir** (`moondream3-preview` BSL 1.1, nunca ejecutado) | **architect** — pendiente declarado desde 2026-07-23 |
| K6 | **`.claude/skills/durable-findings/` documenta `record_finding.py` sin `--no-sync`**, y hay sospecha (no probada) de que eso corrompió el venv | **lead** |

### 8.2 Decisiones que necesitan al fundador — no las toma ingeniería

| # | Decisión | Por qué es suya | Qué desbloquea |
|---|---|---|---|
| **F1** | 🔴 **Una sola sesión empírica cierra SIETE preguntas** — misma app, misma cuenta, misma tarde | Sólo él tiene la cuenta y el App Dashboard. **Las cinco primeras se hacen sin tocar el modo de la app y desbloquean el sprint entero.** Orden por dependencia: **(1)** grafía del scope (A2) · **(2)** `config_id` (A1) · **(3)** ¿devuelve `/me/accounts` un `access_token` por Página al pedirlo en `fields`, y es de larga duración? (A0) · **(4)** ¿falla `create_container` sin `ads_*` para una Página de Business Manager? (K7/F7) · **(5)** ¿la Página exige PPA? (K8) · **(6)** V-TP-2 (a)(b)(c) — **la única que cambia el estado de la app, por tanto la ÚLTIMA** · **(7)** V-TP-7 de ADR 29 | **Ninguna historia del sprint está bloqueada por V-TP-2** — el architect lo confirma con cita: `content-publishing.md:27` lista **Standard Access** en ambas columnas. Lo que V-TP-2 condiciona es **el calendario, no el código**: si (b) vuelve negativa, todo lo que este sprint construya **deja de funcionar para cliente cero el día en que la app pase a Live** para cliente uno. Formulado para él: *"puedes arrancar el sprint entero mañana; lo que no debes hacer hasta que V-TP-2 cierre es planificar el alta de cliente uno encima de una instalación de cliente cero que funciona — porque el toggle que da de alta al uno puede apagar al cero"* |
| **F2** | 💰 **Aprovisionar la cuenta y el bucket R2** (C4) | Es un gasto y una cuenta a nombre de la empresa | **El primer publish real.** Sin bucket, el sprint entrega código verde y ningún byte llega a Meta |
| **F3** | 📄 **Redactar/encargar la política de privacidad, la política de retención y la cláusula de ToS** (C2 items 1, 3, 5) | Son decisiones de producto y de contrato, no de código. Y **§4.c convierte la política de privacidad en el límite legal de lo que se puede hacer con los datos**: escribirla estrecha o ensancha lo que Fase 4 podrá hacer | El primer usuario que no sea él |
| **F4** | 🏠 **Alcance sobre §3.a.ii/housing**: declarar por escrito que **ningún score alimentará decisiones de acceso a vivienda**, o buscar asesoría legal | Es una lectura jurídica, no de ingeniería. El architect lo calificó explícitamente como *"una LECTURA, no un veredicto"* | **Fase 4 entera** para cliente uno. Y hay un problema de óptica independiente del fondo: presentar a App Review una app **llamada Qualify**, que puntúa personas, para un cliente inmobiliario, **invita exactamente a la pregunta de §3.a.ii** — puede ser conforme y aun así **costar un ciclo de revisión** por cómo se lee |
| **F7** | 🔴 **`ads_management` / `ads_read`**: *¿autorizamos añadirlos al conjunto de scopes solicitados **si la prueba empírica demuestra** que la publicación falla sin ellos para una Página gestionada desde Business Manager?* | Pedirlos (i) **ensancha materialmente** lo que el usuario concede, (ii) es un permiso que ADR 21 aparcó a propósito, y (iii) **muy probablemente empuja hacia App Review antes de lo previsto**. No pedirlos puede significar que la publicación **no funcione** para la configuración exacta que tiene cliente cero | La épica A sobre su cuenta real. ⚠ **Secuenciación barata: se puede MEDIR antes de decidir.** La sesión empírica de A2 puede, en la misma tarde, intentar publicar sin `ads_*` y ver si Meta lo rechaza. **Medir primero cuesta una tarde; decidir a ciegas cuesta un App Review** |
| **F8** | 🏠 **¿Se computa alguna vez un score a nivel de persona en el vertical inmobiliario?** Y si la respuesta es "no": **¿se convierte en invariante forzada por test, o se queda como intención documentada?** | El datasci lo formula así porque **la diferencia entre priorizar y filtrar es un `WHERE` de una línea que cualquiera añade sin mala fe**. Y falta enunciar dónde cae el **filtrado de spam**, el único caso legítimo que elimina filas: filtrar por **contenido del mensaje** no parece una determinación sobre la persona; filtrar por **atributo del remitente** sí. Hoy esa frontera no está escrita en ningún sitio | Fase 4 entera, y las cuatro reglas de test estático de B4 |
| **F5** | ⏱ **Arrancar el reloj administrativo** (App Review + Business Verification) en semana 0 | Trámite externo de 2-4 meses que **corre en paralelo** y tiene coste de ingeniería cero | Cliente uno. **Cada semana que no arranca es una semana de retraso que no se recupera con código** |
| **F6** | 🗓 **¿"Programar" publicaciones entra o no?** Este backlog dice **NO** (entrega publish-now) | Si su expectativa es un calendario funcionando, hay que decírselo ahora, no al final del sprint | Define si Fase 1 Parte 3 (Celery) se adelanta |

---

## §9 Prompt sugerido para `/team-dev`

> **Forma A (recomendada): épica A completa + C1, un solo ingeniero de backend. Épica B al Sprint 4.**
>
> **Antes de pegar esto, el lead debe:** (1) ejecutar **C0** — `rm -rf .venv && uv sync --group ml` con **nadie más ejecutando nada**; (2) confirmar con el fundador la pregunta de §6.4 (publicación completa sin bandeja vs. media y media); (3) idealmente, que el fundador haya corrido las **cinco primeras pruebas** de la sesión empírica de F1 — no bloquean el arranque, pero cierran los `[V]` de A0 y A2 antes de que alguien codifique contra una suposición.

```
Sprint 3 de Qualify: cablear PUBLICACIÓN de Meta sobre la conexión de cuenta conectada.
Backlog completo y vinculante en docs/backlog-sprint3-meta-publishing-inbox.md — leedlo
entero antes de planificar. Fase: Fase 1 Parte 4-A (ADR 21).

ALCANCE DEL SPRINT: épica A completa (A0-A7) + C1 + las dos historias de infra (C3, C4).
La épica B (bandeja de comentarios) está APARCADA al Sprint 4 — depende de A0 y no cabe en
el presupuesto con un solo backend. No la empecéis "por adelantar".

PRECONDICIÓN, ya ejecutada por mí: el .venv se ha recreado con `rm -rf .venv && uv sync
--group ml`. Nadie vuelve a correr `uv sync` ni `uv venv` durante el sprint. Sólo
`uv run --no-sync`. El script record_finding.py se invoca SIEMPRE con `--no-sync` (sólo usa
stdlib; no necesita resolver el workspace).

EXTENSIÓN DEL MAPA DE PROPIEDAD (aprobada por mí para este sprint, resuelve K2):
`packages/api/` NO estaba en el mapa de .claude/commands/team-dev.md:22. Se asigna entera a
backend. El resto del mapa sigue igual.

SUPUESTOS DUROS, no negociables:
- Development Mode. NINGÚN criterio de aceptación puede afirmar que un post es visible
  públicamente. V-TP-2/A5-5 la ejecuta el fundador y NO bloquea ninguna historia: el
  architect lo cerró con cita (content-publishing.md:27 lista Standard Access en ambas
  columnas). Si alguien os dice que hay que esperar a V-TP-2, está mal.
- Publicación INMEDIATA (publish-now). La programación diferida está FUERA: cero Celery en
  el repo y no se introduce. `scheduled_posts` se queda como DDL sin consumidor y eso es
  correcto, no deuda. NO construyáis un endpoint manual de disparo: promete un reloj que
  no existe.
- Vídeo únicamente (reel/story/vídeo de carrusel) vía subida resumable. Imágenes → QUA-68.
  Meta NUNCA hace cURL de una clave nuestra: recibe los bytes por rupload. Si veis en algún
  doc "alojar el media en una URL pública", está muerto desde ADR 28a.
- EL SONDEO LO DIRIGE EL CLIENTE. Ninguna función duerme, espera ni itera sobre
  container_status. `advance()` da UN paso. El techo de 300 s se comprueba contra la
  columna `started_at` (NO `created_at` — ésa sólo existe en scheduled_posts).
  FastAPI BackgroundTasks está RECHAZADO: muere con el proceso y deja la fila en
  `processing` para siempre.
- Nombres de tabla REALES: `publish_attempts`, `scheduled_posts`, `threads`, `messages`.
  Los nombres `publishing_attempts`/`inbox_threads`/`inbox_messages` NO EXISTEN.
- Nada se marca [APROBADO]. Nada se firma. Ningún commit, ningún push sin pedírmelo.

backend (pipeline-engineer). Frontera: packages/api/, packages/shared/, migrations/.
ORDEN OBLIGATORIO — es una cadena serial sobre los mismos ficheros, no un abanico:

  A0 — TOKEN DE PÁGINA. VA PRIMERA. Hoy `service.py:223` cifra el token de USUARIO y Meta
       exige token de PÁGINA para publicar (content-publishing.md:30) y para leer
       comentarios (comment-moderation.md:17). `meta_oauth.py:197` ni siquiera lo pide:
       falta `access_token` en `fields`. Añadidlo, dad a LinkedPage un
       `page_access_token: str | None` marcado [V], y persistid el de Página. Sin
       migración: `oauth_credentials.token_type` es text libre.
       DOS [V] ABIERTOS que cerráis en vivo y REGISTRÁIS, no inferís: (i) ¿hace falta
       intercambiar el token de usuario corto por uno largo? (ii) ¿hay que custodiar DOS
       credenciales por conexión (`/me/permissions` usa el de usuario)? Si (ii) es sí,
       ELEVAD AL ARCHITECT antes de codificar: es decisión de custodia, no de fontanería.
       Incluye el aviso de PPA en el flujo de conexión. P0/S-M.

  A1 — config_id en MetaOAuthSettings + authorization_url. Omitirlo entero si no está
       definido (no cadena vacía). Y añadid el test que falla si `granted_scopes` deja de
       persistirse: con config_id, `requested_scopes` DEJA de ser la fuente de verdad y
       `/me/permissions` pasa a ser lo único que sabe qué se concedió. P0/S.

  A2 — Resolución EMPÍRICA de la grafía del scope. Script marcado `integration`, resultado
       a entorno, NUNCA literal en código. P0/S.

  C1 — `Principal`. NO es "quitar el global": es que no hay autenticación, luego no hay
       principal. Dataclass congelada (tenant_id, user_id); credencial opaca desde
       QUALIFY_DEV_PRINCIPALS; `Authorization: Bearer <token>`; dependencia
       current_principal() en un http/deps.py nuevo que devuelve 401, NO 409. Y en la misma
       pasada: `user_id` SALE del cuerpo de StartConnectRequest — hoy el cliente elige a
       quién se atribuye la conexión y ese id acaba en connection_events como actor.
       RECHAZADAS: tabla de tokens en Postgres (invita a construir encima) y ContextVar con
       X-Tenant-Id (mismo agujero de autorización, mejor higiene de hilos).
       No toca RLS, ni el GUC, ni el NULLIF, ni tenant_session. Vive POR ENCIMA de la
       puerta. P0/M. Va en paralelo con A4 y DEBE estar antes de la primera ruta.

  A3 — Staging del media a R2 (capa L6). En todo el repo NO HAY UNA SOLA LLAMADA a
       put_media: sin esto la cadena entera termina en un bucket vacío. Usad
       `media_key()`, nunca construyáis la clave a mano. NO creéis fila de scheduled_posts:
       `publish_attempts.scheduled_post_id` es nullable justo para publish-now. P0/S.

  A4 — Modelos ORM (L1) + repositorio write-ahead (L2) sobre publish_attempts.
       El trigger publish_attempts_settle_once lanza check_violation ante CUALQUIER UPDATE
       de una fila liquidada. PROHIBIDO taparlo con `WHERE settled_at IS NULL`. Lo correcto
       es CAPTURAR check_violation y tratarlo como "ya liquidado" — el camino idempotente
       del reintento — NO como un 500. Y `settled_at` + status terminal se escriben en el
       MISMO UPDATE (ck_attempt_settled_matches_status). P0/M.

  A5 — Servicio (L3) + composición (L4): `start()` y `advance()`, dos operaciones cortas.
       Los cinco ContainerStatus son cinco, no un booleano. `UploadOutcome.retriable is
       None` es DESCONOCIDO, no False. Desenlace distinguible para PPA: un fallo de PPA
       registrado como `failed` genérico son horas persiguiendo un bug que no existe. P0/M.

  A6 — Reconciliación por creation_id (L8). media_publish es la ÚNICA transición del
       sistema con reintento ciego PROHIBIDO. Test obligatorio: timeout tras enviar → cero
       republicaciones. Y rellenad `raw_response_r2_key` desde el principio: es la única
       traza que quedará de la primera llamada real a Meta. P0/M.

  A7 — Rutas HTTP (L5): POST /api/media (multipart), POST /api/publishing/attempts (202 +
       attempt_id), GET /api/publishing/attempts/{id} (invoca advance()). idempotency_key
       OBLIGATORIA en el cuerpo (422 sin ella). tenant_id y user_id salen del Principal,
       NUNCA del cuerpo. Dependencia por defecto que lanza NotImplementedError. P1/M.

  C3 — Declarar boto3 en packages/shared/pyproject.toml y subir el import de s3.py a nivel
       de módulo. El guardián de test_object_store_sanctity.py se QUEDA (lo dice el propio
       docstring). COORDINADME esta historia: toca uv.lock y nadie más puede estar
       ejecutando nada. P1/S.

architect (principal-architect). Frontera: docs/, CLAUDE.md.
  ADR [PROPUESTO] del sondeo dirigido por el cliente (alternativas descartadas:
    BackgroundTasks y Celery, con su razón). NO firmada.
  Enmienda [PROPUESTO] a ADR 25: config_id, y por qué /me/permissions pasa a ser
    load-bearing. Addendum de la errata `instagram_content_publishing` →
    `instagram_content_publish` citando content-publishing.md:29. NO re-firméis la fila.
  Documentar PPA en docs/integracion-cuentas-conectadas-meta.md (hoy no aparece en ningún
    sitio del expediente).
  K1 — reescribir el fundamento de "autónomas fuera" en ADR 21 SIN la cifra del 65 %:
    (a) cero mediciones de calidad de borrador, (b) asimetría irreversible del error,
    (c) vertical regulada. La regla NO cambia; su fundamento sí.
  K3 — corregir §4.2/§4.3 contra el DDL aplicado (publish_jobs → publish_attempts; la
    columna de expiración de ventana está PROHIBIDA por la condición B2; el intake es
    POLL-FIRST, no webhook).
  K4 — borrar de CLAUDE.md la afirmación de que revoke_connection no existe.
  No necesita aprobación de plan para ediciones de doc/ADR.

datasci — NO SE ASIGNA EN ESTE SPRINT. B4 está aparcada con la épica B, y el conjunto
  dorado no se puede construir: `messages` está vacía, falta la materia prima. Si el lead
  quiere darle trabajo, el único item defendible es preparar el fixture de 60 comentarios
  etiquetados de la puerta determinista (10 por clase), que no necesita corpus real.

NO SE ASIGNA A INGENIERÍA:
  C4 (bucket R2) → gasto y cuenta del fundador. Sin él, el sprint entrega código verde y
    ningún byte llega a Meta.
  C2-bis (política de privacidad, retención, SECURITY.md, cláusula de ToS) → cuatro
    entregables administrativos del fundador, misma fecha de vencimiento: "cuando el primer
    agente de cliente uno use el producto". NO consumen capacidad de desarrollo.
  C2 (endpoints deauthorize/data-deletion) → cabe en Sprint 4; es barato porque
    connections/revoke.py ya existe.

PUERTA DE CALIDAD, aplicada a todo plan antes de que se escriba una línea:
1. Tests con `uv run --no-sync pytest -m "not integration"` SIN RED. Lo que necesite la
   Postgres de compose lleva marca `db`. Lo que necesite red o vendedor lleva `integration`
   y NUNCA entra en el run por defecto.
2. Provenance persistida en toda fila derivada: tenant_id, connection_id, adapter_version.
3. Todo acceso a datos por tenant_session (RLS). Ningún filtrado por tenant en Python.
4. Ningún token, ciphertext ni cuerpo de respuesta de Meta en un error o un log.
5. Type hints en toda firma nueva. `just lint` limpio.
6. Ninguna decisión de esquema o de custodia se hornea sin pasar por el architect.
7. Ninguna historia se dimensiona ni se justifica por ahorro de coste de inferencia: está
   medido en ~$0,0013/borrador y ~$2/mes. A este volumen el coste está bajo el ruido.

Levantadme cualquier cosa fuera de vuestra frontera en vez de editarla.
```

### 9.1 Variante para la Forma B (si el fundador la elige)

Sustituir el bloque de alcance por: **A0, A1, A2, C1, A3, A4, A5 + B1, B3, B2**, sacando **A6 y A7**. **Este backlog no lo recomienda** — sin A6 se entrega publicación sin la protección contra doble publicación (*"la regla más estricta del sistema entero"*, ADR 22e) y sin A7 no hay ruta HTTP, es decir **nada que enseñar**. Se documenta porque la decisión es del fundador.
