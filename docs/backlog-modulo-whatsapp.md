# Backlog — Módulo WhatsApp (Cloud API): plan de ejecución

**Fecha:** 2026-10-14 · **Estado:** `[PLAN DE EJECUCIÓN — entregas 1–4 ordenadas por la prioridad D5; D1 pendiente, bloquea solo WA-13]`
**Plan padre:** [plan-modulo-whatsapp-cloud-api.md](plan-modulo-whatsapp-cloud-api.md) (contexto, permisos de Meta, arquitectura, decisiones). Este documento lo ordena en **entregas que Bianki usa** y le da a cada historia su contrato técnico sobre el código que existe hoy.
**Hecho antes de este backlog:** WA-00 parcial (D3 y D4 aplicados de facto), WA-01 (caso de uso WhatsApp, WABA de prueba `2338576026889338`, número de prueba `1393787420477981`, Paso 1 del panel completado), WA-03 (receptor `/api/whatsapp/webhook` grabando en el intake de QUA-147; PRs #123 y #125).
**Linear:** proyecto «Módulo WhatsApp (Cloud API)», un hito por entrega. El autoservicio para tenants ajenos es [QUA-203](https://linear.app/qualify-market/issue/QUA-203), fuera de estas entregas.

---

## 0. La prioridad que ordena todo (D5)

Para un local de comida rápida lo que mueve dinero es **el pedido**; el 80 % de los chats son cuatro preguntas repetidas y la quinta es la venta. De ahí el orden:

| Entrega | Qué puede hacer Bianki al terminarla | Historias | Apaga Baileys |
|---|---|---|---|
| **1. Cimientos** | El número está conectado a Qualify; cada mensaje entrante queda en `threads`/`messages`; Qualify puede enviar texto, media y botones dentro de la ventana de 24 h | WA-04 · WA-05 · WA-06 · WA-07 · WA-08 | no |
| **2. Chats** | Una persona atiende desde el computador: lista de conversaciones, hilo, responder, asignar, "pedido listo"; perfil del negocio y QR por canal; el número real de Bianki en la API | WA-10 · WA-11 · WA-12 · WA-13 | **sí** (paridad mínima: atender) |
| **3. Menú que toma el pedido** | Bienvenida, atajos, menú de productos desde el catálogo, pedido estructurado que pasa a una persona; editor de menús; métricas por entrada | WA-14 · WA-15 · WA-16 · WA-17 | **sí, del todo** (paridad con el bot + pedido) |
| **4. Volver a vender** | Plantillas, opt-ins, campañas con costo visible, analítica | WA-18 · WA-19 · WA-20 · WA-21 | — |
| 5. Después | Flows de pedido, catálogo nativo con carrito, llamadas, autoservicio multi-tenant (QUA-203) | WA-22 · WA-23 · WA-24 | — |

**Gates de decisión:** D1 (número de Bianki) bloquea **solo WA-13**; todo lo demás se prueba con el número de prueba. D2 (menús deterministas bajo ADR 21) se toma como **sí** porque el fundador pidió implementar el módulo entero; queda escrito en el plan §9.1 como aplicado salvo objeción.

---

## 1. Reglas que aplican a todas las historias

- **Tenant por `phone_number_id`, nunca por payload.** El worker resuelve `social_connections` por `(platform='whatsapp', external_account_id=phone_number_id)`; un número sin conexión es `orphan` y no se asocia a nadie.
- **Idempotencia por `wamid`.** `messages.external_message_id` ya es `UNIQUE (connection_id, external_message_id)`; el intake de QUA-147 ya deduplica entregas. Nada se reenvía dos veces por un reintento.
- **Ventana de 24 h como política, no como reloj.** `threads.last_inbound_at` manda; fuera de ventana solo plantillas. `whatsapp/window.py` es la única función que lo decide.
- **Nada de texto de usuario en logs.** Identificadores y enumeraciones (patrón `CommentsReadError` / `WAChangeSummary`).
- **Tokens:** el system user token entra una vez por `whatsapp.connect`, se cifra en `oauth_credentials` y solo `qualify_credential` lo lee; ningún módulo de WhatsApp ve el token (recibe un `AuthenticatedClient` del `CredentialResolver`).
- **RLS en toda tabla nueva** (política `NULLIF` de 0001, `test_rls_policy_shape.py` la verifica sola); grants mínimos por rol y documentados en el docstring de la migración.
- **Cada historia termina con tests offline** (contrato, fakes) **y, si toca esquema, `db`** (`just test-db`), y **`just migrate-down` limpio**.
- **UI:** `app_shell(page_header, page_body)`, tonos `ok/warn/error/info/neutral`, nunca un color Radix crudo (`docs/design-system.md` §9.1).

---

## 2. Entrega 1 — Cimientos

### WA-04 · Migración `0056_whatsapp` + espejos ORM

**Qué crea**

| Tabla | Columnas clave | Grants |
|---|---|---|
| `whatsapp_phone_numbers` | `id`, `tenant_id`, `brand_id` (nullable), `connection_id` + FK compuesta `(connection_id, tenant_id) → social_connections` (R2), `waba_id`, `phone_number_id` **UNIQUE**, `display_phone_number`, `verified_name`, `name_status`, `quality_rating`, `messaging_limit_tier`, `platform_status`, `automation` jsonb (ice breakers/commands/bienvenida publicados), `last_synced_at`, `created_at` | `qualify_app`: SELECT, INSERT, UPDATE · `qualify_webhook_worker`: SELECT (`id, tenant_id, connection_id, phone_number_id`) · `qualify_admin`: SELECT |
| `whatsapp_thread_state` | `thread_id` PK + FK compuesta `(thread_id, tenant_id) → threads`, `menu_version_id` (nullable hasta 0057), `node_id`, `context` jsonb (pedido en curso), `automation_paused_at`, `paused_by_user_id`, `updated_at` | `qualify_app`: SELECT, INSERT, UPDATE · `qualify_webhook_worker`: SELECT, INSERT, UPDATE |
| `whatsapp_outbox` | `id`, `tenant_id`, `connection_id` (+ FK compuesta), `thread_id` (nullable), `kind` CHECK `('reply','automation','campaign_send')`, `payload` jsonb (cuerpo del `POST /messages` ya construido), `status` CHECK `('pending','sending','sent','failed','dead')`, `attempts`, `next_attempt_at`, `locked_by`, `locked_at`, `wamid`, `error_code`, `created_by_user_id` (nullable), `created_at`, `sent_at` | `qualify_app`: SELECT, INSERT, UPDATE · `qualify_webhook_worker`: INSERT |

**Qué cambia**

- `threads.channel` CHECK → `('comment','dm','whatsapp')`; `messages` gana `delivery_status` (`sent/delivered/read/failed`, nullable) y `delivery_error_code`; índice parcial `ix_message_outbound_pending` no hace falta (lo cubre el outbox).
- `social_connections.linked_page_id` → nullable + `CHECK ((platform = 'whatsapp') OR (linked_page_id IS NOT NULL))` (`ck_conn_linked_page_by_platform`). ADR 25 sigue intacto para Instagram: el `NOT NULL` pasa a ser condicional, no desaparece.
- `qualify_webhook_worker` gana SELECT/INSERT/UPDATE sobre `threads` y `messages` (hoy solo lee `social_connections`): es quien escribe el inbound. Documentado en el docstring igual que 0050 explica su BYPASSRLS.
- ORM: `qualify_api/whatsapp/models.py` (tres clases), `inbox/models.py` (CHECK + dos columnas), `connections/models.py` (`linked_page_id: str | None`), `connections/repository.py` (`GrantInput.linked_page_id: str | None`).

**Aceptación:** `just migrate` y `just migrate-down` limpios; `test_whatsapp_schema_db.py` pinta la tabla de permisos efectivos por rol (patrón `test_webhook_schema_db.py`); `test_rls_policy_shape.py` pasa sin tocarlo; suite offline verde.

### WA-05 · Alta administrativa de la conexión + tarjeta en `/connections`

- `python -m qualify_api.whatsapp.connect --tenant <uuid> --brand <uuid> --waba-id <id> --phone-number-id <id>` (`just whatsapp-connect`). Lee `QUALIFY_WA_SYSTEM_USER_TOKEN` del entorno **solo en este proceso**; nunca lo imprime.
- Verifica antes de escribir: `GET /debug_token` (scopes contienen `whatsapp_business_messaging` y `whatsapp_business_management`, `is_valid`) y `GET /{phone_number_id}?fields=verified_name,display_phone_number,quality_rating,messaging_limit_tier,name_status,status`. Si algo falla, no crea nada (**V-WA-1** queda cerrada con este comando en Development Mode).
- Persiste por `PostgresConnectionRepository.persist_grant(GrantInput(platform='whatsapp', account_type='waba_phone_number', external_account_id=phone_number_id, external_username=display_phone_number, linked_page_id=None, granted_scopes=<debug_token>, token_type='system_user', expires_at=None, …))` → `social_connections` + `oauth_credentials` cifrado + evento; FSM `pending → active` con `VERIFY_OK`; fila en `whatsapp_phone_numbers`. Idempotente: segunda ejecución rota la credencial (versión +1) y refresca metadatos.
- `permission_capability.py`: `ScopeKey.WA_MESSAGING` / `WA_MANAGEMENT` → capacidades `WA_SEND`, `WA_TEMPLATES`, `WA_AUTOMATION`; `check_connection_health` funciona igual (mismo `/debug_token`).
- `/connections`: `platform_badge('whatsapp')`, etiqueta = número visible + nombre verificado, "Verificar ahora" operativo. Sin botón de conectar (QUA-203).

**Aceptación:** el comando contra el número de prueba deja la tarjeta `active` en `/connections`; `test_whatsapp_connect.py` con doble de Graph (sin red) cubre éxito, token sin scopes, número ajeno, re-ejecución.

### WA-06 · Cliente Graph `whatsapp/client.py`

`WhatsAppClient` (Protocol) + `HttpWhatsAppClient(graph_client: AuthenticatedClient, graph_url)`, mismo molde que `publishing/client.py`:

| Método | Endpoint |
|---|---|
| `send_text`, `send_interactive_buttons` (≤3), `send_interactive_list`, `send_image/document/video` (por link o `media_id`), `send_template` | `POST /{PHONE_NUMBER_ID}/messages` |
| `mark_read`, `typing_indicator` | `POST /{PHONE_NUMBER_ID}/messages` (`status: read`, `typing_indicator`) |
| `upload_media`, `media_url`, `download_media` | `POST /{PHONE_NUMBER_ID}/media`, `GET /{MEDIA_ID}`, `GET <url>` |
| `get_phone_number` | `GET /{PHONE_NUMBER_ID}?fields=…` |
| `get_business_profile`, `update_business_profile` | `GET/POST /{PHONE_NUMBER_ID}/whatsapp_business_profile` |
| `set_conversational_automation`, `get_conversational_automation` | `POST /{PHONE_NUMBER_ID}/conversational_automation`, `GET …?fields=conversational_automation` |
| `create_qr_code`, `list_qr_codes`, `delete_qr_code` | `/{PHONE_NUMBER_ID}/message_qrdls` |

Errores: `WhatsAppApiError(status, code, subcode, error_data.details sin texto de usuario)`; 190/401 dispara `degrade_connection_on_auth_error`. Cada `_parse_*` es `[V]` contra fixtures grabadas del número de prueba (`packages/api/tests/fixtures/whatsapp/`).

**Aceptación:** tests con `httpx.MockTransport` por endpoint; un smoke manual `just whatsapp-smoke --tenant … --to <mi número>` envía texto + botones al destinatario de prueba y recibe el `wamid`.

### WA-07 · Handler de entrada en `webhooks.processor`

- El procesador pasa a despachar por **`(object, field)`** con retrocompatibilidad: `handlers` acepta claves `"whatsapp_business_account:messages"` y las antiguas de solo `field`. Sin esto, `messages` de WhatsApp colisionaría con el `messages` de Instagram DM.
- `qualify_api/whatsapp/handler.py` → `whatsapp_messages_handler(resolve, repo, client_factory, menu_engine)`:
  1. `wa_shapes.parse_whatsapp_notification` sobre el `value` del change (contrato → `dead(contract_violation)` si no cuadra).
  2. Resolver `phone_number_id` → `(tenant_id, connection_id)` (`whatsapp/resolve.py`, mismo molde que `mentions/resolve.py`; `orphan` si no hay conexión).
  3. `messages[]`: upsert `threads` (`channel='whatsapp'`, `external_thread_id=wa_id`, `last_inbound_at`, `last_message_at`) y `messages` (`direction='inbound'`, `external_message_id=wamid`, `text` o descriptor del tipo, `shape_version`, `raw_payload_r2_key=None` porque el crudo ya vive en `meta_webhook_deliveries`); media entrante: `media_id` + `mime` en `messages`, descarga diferida a WA-11.
  4. `statuses[]`: `UPDATE messages SET delivery_status, delivery_error_code WHERE external_message_id = wamid` (el outbound lo creó WA-08).
  5. `mark_read` del mensaje entrante; si el hilo no está pausado, invoca el motor de menús (WA-14; hasta entonces no hace nada) y encola en `whatsapp_outbox` lo que el motor devuelva.
  6. `Outcome(processed)`.
- Repositorio `whatsapp/repository.py` con la variante Postgres (sesiones `webhook_worker_session()`) y una en memoria para tests.

**Aceptación:** `test_whatsapp_handler.py` con la fixture viva (`status read`) y la sintética (texto + lista + imagen): hilos y mensajes exactos, segunda ejecución del mismo change no duplica, número desconocido → `orphan`; `test_webhook_processor.py` sigue verde con el despacho por `(object, field)`.

### WA-08 · Outbox y ventana de 24 h

- `whatsapp/window.py`: `window_state(last_inbound_at, now) -> OPEN(until)|CLOSED` (pura). `whatsapp/outbox.py`: `enqueue_reply(...)`, `OutboxSender.run_once()` que reclama `pending` (`FOR UPDATE SKIP LOCKED`, backoff `4^n` como pide Meta), construye el cliente con `CredentialResolver.client_for(connection_id, scheme='Bearer')`, envía, escribe `messages` (`direction='outbound'`, `wamid`) y marca `sent`; respeta el límite por par (1 mensaje / 6 s al mismo usuario) y rechaza texto libre fuera de ventana (`failed`, `error_code='window_closed'`) salvo `kind='campaign_send'`.
- CLI `python -m qualify_api.whatsapp.worker --tenant <uuid> [--once] [--interval 5]` (`just whatsapp-worker`), mismo molde y **misma advertencia** que `calendar-worker`: localmente siempre `--tenant`. En producción, servicio `whatsapp-worker` en `docker-compose.prod.yml` junto a `webhook-worker`.

**Aceptación:** tests del sender con cliente falso (envío, reintento, `dead`, ventana cerrada, pacing); E2E manual: un mensaje encolado llega al destinatario de prueba y su `delivered` vuelve por WA-07 al mismo `messages`.

---

## 3. Entrega 2 — Chats (apaga Baileys en su mínimo)

### WA-10 · API HTTP de chats

`http/whatsapp_routes.py` gana, con `Principal` (C1): `GET /api/whatsapp/threads?connection_id=&status=` (último mensaje, no leídos, estado de ventana, asignado), `GET /api/whatsapp/threads/{id}/messages?before=`, `POST /api/whatsapp/threads/{id}/messages` (`text` | `image` | `buttons`) → `whatsapp_outbox` kind `reply` (409 si la ventana está cerrada, con `window_closed_at`), `POST …/assign`, `POST …/close`, `POST …/takeover` (pausa automatización) y `…/resume`. `GET /api/whatsapp/media/{message_id}` sirve media entrante vía R2 (descarga perezosa con el cliente, cache por `media_id`).

### WA-11 · Pantalla `/whatsapp` — pestaña Chats

`Qualify/whatsapp_page.py` + `whatsapp_state.py` + `whatsapp_vm.py` + `whatsapp_provider.py` (provider lee por `tenant_session`, mismo molde que `inbox_provider.py`). Lista de conversaciones (nombre/número, último mensaje, hora, badge de ventana `ok` abierta / `warn` cierra en < 1 h / `neutral` cerrada, asignado), hilo con burbujas y estados de entrega, compositor (texto, foto, 3 botones rápidos), acciones asignar / cerrar / "tomar el control". Refresco con el mismo temporizador de `/inbox` (45 s) más refresco al enviar. Entrada en el menú lateral: «WhatsApp», icono `message-circle`.

### WA-12 · Pestañas Conexión y Perfil + QR

Conexión: número, nombre verificado, `name_status`, calidad, nivel de mensajería, salud (`check_connection_health`), último webhook recibido, botón "Verificar ahora". Perfil: formulario del `whatsapp_business_profile` (descripción, dirección, email, web, categoría, foto vía `upload_media`). QR: lista y alta de códigos con texto prellenado por canal (mostrador, empaque, bio de Instagram), descarga del PNG que devuelve Meta y enlace `wa.me`; el texto prellenado es la clave de entrada que WA-17 mide.

### WA-13 · Número real de Bianki y apagado de Baileys *(gate D1)*

Runbook en el plan §10: Paso 2 del panel (crear WABA real bajo Qualify.co o reutilizar la de prueba convertida, registrar el número según D1, verificación SMS, display name, PIN de dos pasos), `just whatsapp-connect` en producción con `--brand` Bianki, webhook ya suscrito (WA-03), prueba de humo con un cliente real, apagado de Baileys y exportación del historial del teléfono si D1 = B. Criterio: el primer pedido real atendido desde `/whatsapp`.

---

## 4. Entrega 3 — Menú que toma el pedido

### WA-14 · Modelo y motor de menús (`0057_whatsapp_menus`)

- Tablas `whatsapp_menus` (`tenant_id, phone_number_id, name, published_version_id`) y `whatsapp_menu_versions` (`menu_id, version, definition jsonb, published_at, published_by`), RLS, versiones inmutables.
- `whatsapp/menus/schema.py` (Pydantic): `MenuDefinition{entry: {on_first_message, keywords[], ice_breakers[≤4, ≤80], commands[≤30], welcome}, nodes: {id → Node}}`; `Node.kind ∈ text | buttons | list | products | order_summary | collect | handoff`; `options[{id, label, next}]`; validación de límites de Meta (3 botones, 10 filas, 24/20 caracteres).
- `whatsapp/menus/engine.py`, **puro**: `step(definition, state, inbound) -> (actions: list[OutboundMessage], next_state)`; `inbound` = texto, `button_reply.id`, `list_reply.id` o comando; `handoff` pausa el hilo; respuesta desconocida repite el nodo con ayuda; nunca llama a red ni a DB.
- `whatsapp_thread_state.menu_version_id` gana su FK.

**Aceptación:** tests tabla-dirigidos del motor (recorridos completos, entrada desconocida, handoff, reanudación), validación de límites.

### WA-15 · Pedido asistido desde el catálogo

- Nodo `products`: se construye desde `brand_products` activos (nombre, precio, categoría; 10 por sección, secciones por categoría); nodo `order_summary` acumula `context.order[]` (producto, cantidad), muestra total y botones «Confirmar / Agregar más / Cancelar»; `Confirmar` → `handoff` con el pedido estructurado guardado en `context` y un mensaje interno en el hilo (`direction='outbound'`, tipo `order_summary`, visible solo en Qualify) para que la persona vea el pedido completo arriba del chat.
- En Chats: tarjeta de pedido en la cabecera del hilo y respuesta rápida «Pedido listo» (texto dentro de ventana, gratis).

### WA-16 · Editor de menús y publicación al número

Pestaña Menú en `/whatsapp`: árbol de nodos (editar texto, opciones, destino), vista previa estilo teléfono, «Publicar versión» (crea `menu_version`, la activa y llama a `set_conversational_automation` con ice breakers, comandos y bienvenida para que lo que se ve en WhatsApp y lo que ejecuta Qualify sea el mismo dato), historial de versiones, interruptor «Pausar menú en este número».

### WA-17 · Entradas y métricas

Relación QR/enlace → `entry.keywords` (el texto prellenado) para que cada canal abra el nodo correcto; en Conexión, contadores por entrada (hilos abiertos por primer mensaje), pedidos confirmados por el menú, handoffs y tiempo medio hasta la primera respuesta humana. Sin tablas nuevas: consultas sobre `threads`/`messages`/`whatsapp_thread_state`.

---

## 5. Entrega 4 — Volver a vender

### WA-18 · Plantillas (`0058_whatsapp_templates`)
Espejo de las plantillas de la WABA (`name, language, category, status, quality, components jsonb, meta_template_id`), alta desde Qualify (`POST /{WABA_ID}/message_templates`), handler `whatsapp_business_account:message_template_status_update` en el procesador, pestaña Plantillas con `tone_badge` por estado. Requiere método de pago en la WABA para enviarlas (no para crearlas).

### WA-19 · Opt-ins (`0058`)
`whatsapp_opt_ins (tenant_id, brand_id, phone_e164, source, consent_text, proof, captured_at, revoked_at)`; fuentes: formulario de leads (ya guarda `whatsapp_phone` y `consent_text`), nodo `collect` del menú («¿Quieres recibir promos?» con botón), importación con evidencia; palabra «STOP»/«BAJA» entrante → `revoked_at`.

### WA-20 · Campañas (`0058`)
`whatsapp_campaigns` + `whatsapp_campaign_sends`; audiencia = opt-ins vigentes filtrados; envíos por `whatsapp_outbox` kind `campaign_send` con ritmo y límite de mensajería; `131049` → reintento ≥ 24 h; costo estimado por envío (`pricing.category` del status webhook lo confirma a posteriori); pestaña Campañas con resultado entregado/leído/fallido/costo.

### WA-21 · Analítica
`GET /{WABA_ID}?fields=analytics,conversation_analytics` en Conexión: mensajes por día, costo por categoría, comparado con lo que suma `whatsapp_campaign_sends`.

---

## 6. Entrega 5 — Después (no planificar todavía)

- **WA-22 Flows**: pedido/reserva como formulario nativo (Flow JSON, `nfm_reply`), versión con endpoint cifrado para precios en vivo.
- **WA-23 Catálogo nativo**: sync `brand_products`/`product_media` → catálogo de Commerce Manager conectado a la WABA; mensajes multi-producto y mensaje de pedido (`order`) con carrito.
- **WA-24 Llamadas** (Calling API; exige límite ≥ 2.000).
- **QUA-203** autoservicio para tenants ajenos (Embedded Signup v4 + acceso avanzado).

---

## 7. Orden de trabajo y dependencias

```
WA-04 ──► WA-05 ──► WA-06 ──► WA-07 ──► WA-08 ──► WA-10 ──► WA-11 ──► WA-13 (D1)
                                  │                 └──► WA-12
                                  └──► WA-14 ──► WA-15 ──► WA-16 ──► WA-17
                                                   WA-18 ──► WA-19 ──► WA-20 ──► WA-21
```

Cada historia es un PR propio, mergeado por `just merge` con CI verde. Una historia no empieza hasta que la anterior de su fila esté en `main`. Las verificaciones empíricas del plan (§9.2) se cierran así: V-WA-1 en WA-05, V-WA-3 en WA-13, V-WA-2 solo si D1 = C.
