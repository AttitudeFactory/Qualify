# Plan — Altas de clientes operadas desde Meegle (sin pantalla de superadmin)

`[PLAN 2026-10-16]` · Decisión del fundador (2026-10-16): **opción 3** — el seguimiento de cada
alta (invitación → registro → kit → primera publicación) vive en **Meegle**, y todo lo operativo se
gestiona con los flujos y automatizaciones que ya ofrecen Lark y Meegle. **No se construye la
pantalla `/admin`** de `plan-superadmin-alta-clientes.md` (Fases A0–A1 quedan sustituidas por este
plan; A2–A4 siguen vigentes como futuro y se enganchan aquí como nodos).

**Construye sobre:** el registro solo por invitación del PR #106 (`qualify_api.auth.invites`,
`qualify_api.mail` sobre Resend, migración `0063_signup_invites`) y la bandeja de webhooks de
QUA-147 (`qualify_api.webhooks`: grabar → asentar en el `webhook-worker`).

## 0. La idea en una frase

Cada cliente es **un ítem de trabajo «Alta de cliente»** en el espacio Meegle *Qualify*, con un
flujo de nodos. Herwin y el equipo solo tocan Meegle; **Qualify es un motor sin pantalla** que
reacciona a los eventos del ítem (nodo completado, ítem terminado) y escribe de vuelta en el mismo
ítem (campos, nodos, comentarios). Los recordatorios, avisos a Lark y grupos de chat los hace Meegle
con sus reglas de automatización, no Qualify.

## 1. Lo verificado (2026-10-16, docs oficiales de Meegle)

| Hecho | Fuente |
|---|---|
| El espacio **Qualify** existe (`project_key 6ad251e7ce655b7ed3a0e9b4`, `simple_name 5h2wsx`); sus tipos son los de la plantilla por defecto (Features, Issues, Tasks, Sprint, Versions) más la demo «Onboarding» de Meegle. No hay nada propio todavía. | `meegle project search`, `workitem meta-types` |
| **Meegle → Qualify:** un plugin con *Event Listener* recibe un `POST` por evento: `1001` ítem creado, `1009` campo modificado, `2001` nodo completado, `2004` nodo revertido, `1005` ítem terminado, `3001` cambio de estado. Cuerpo con `request_time`, `signature`, `data.idempotent_key`, `data.work_item_info[]`. Hay que responder **200 en < 1000 ms**; reintenta 4 veces; puede llegar **repetido y desordenado**. | [Event Listener](https://meegle.com/b/helpcenter/developer/event-listener) |
| Firma: `sha256(plugin_id + request_time + callback_token)` en hex, comparada con `signature`. No es HMAC. | [Signature verification](https://meegle.com/b/helpcenter/developer/compatibility-and-signiture-verification) |
| **Qualify → Meegle:** `POST https://meegle.com/open_api/authen/plugin_token` con `plugin_id` + `plugin_secret` → `plugin_access_token` (2 h, cachear). Cabeceras `X-Plugin-Token` + `X-User-Key` (el usuario en cuyo nombre actúa). | [Obtain access credentials](https://meegle.com/b/helpcenter/developer/plugin-access-token-obtain-a-plugin-access-token) |
| Endpoints (SDK oficial Go v2): crear ítem `POST /open_api/{project_key}/work_item/create` (`work_item_type_key`, `template_id`, `name`, `field_value_pairs`); actualizar campos `PUT /open_api/{project_key}/work_item/{type}/{id}` (`update_fields`); **completar nodo** `POST /open_api/{project_key}/workflow/{type}/{id}/node/{node_id}/operate` (`action`: confirm / rollback, `fields`, `node_owners`); flujo `POST …/{id}/workflow/query`; comentario `POST …/{id}/comment/create`; leer ítems `POST /open_api/{project_key}/work_item/{type}/query`. | `larksuite/project-oapi-sdk-golang` `v2/service/workitem/api.go`, `comment/api.go` |
| **Plan Free:** 20 asientos, plataforma abierta incluida, **10 reglas de automatización por espacio**, **500 llamadas API/día**, **100 webhooks/día**. Un alta consume ~3 webhooks y ~6 llamadas → holgura para decenas de altas diarias. | [Pricing](https://www.meegle.com/pricing) |
| Las automatizaciones nativas de Meegle (sin código) disparan por creación/cambio de campo/nodo/plazo y actúan con: actualizar campo, asignar, enviar mensaje de Lark, crear grupo, mover nodo. El «conector de automatización» (triggers/acciones propias de un plugin) existe pero **no hace falta** para este plan. | [Automated Connector](https://meegle.com/b/helpcenter/developer/automated-connector) |

## 2. El ítem «Alta de cliente»

Tipo de ítem nuevo en el espacio Qualify, **flujo de nodos** (no de estados). Se crea a mano en la
UI de Meegle (10 minutos); los campos pueden crearse por API.

**Campos que llena una persona** (al crear el ítem o en el primer nodo):

| Campo | Tipo | Nota |
|---|---|---|
| Nombre (name) | nativo | el negocio |
| Correo | text | literal; el `+alias` es el negocio |
| Nombre de la persona | text | para el saludo |
| Nota personal | multi-text | va en el correo («Como hablamos hoy…») |
| Instagram / TikTok | text | opcional hoy; lo usa A2 mañana |

**Campos que escribe Qualify** (solo lectura para el equipo, por convención):

| Campo | Tipo | Quién lo pone |
|---|---|---|
| Estado Qualify | select: `pendiente · invitada · entregada · abierta · rebotó · registrada · vencida · error` | Qualify |
| Enlace de invitación | link | Qualify, al invitar (sirve para mandarlo a mano por WhatsApp) |
| Vence | date | Qualify |
| Registrada el | date | Qualify |
| Tenant | text | Qualify, al registrarse |
| Qualify ref | text | `invite_id`; la llave de conciliación |

**Nodos (en orden):**

| # | Nodo | Quién lo completa | Qué pasa |
|---|---|---|---|
| 1 | **Datos** | persona | Completar = «enviar». Qualify valida el correo, crea la invitación, manda el correo por Resend, escribe enlace/vence/estado=invitada y comenta «Invitación enviada a …». Si falla, estado=`error` + comentario con el motivo y el nodo se revierte para que se corrija y se vuelva a completar. |
| 2 | **Invitada** | Qualify | Lo completa al confirmar Resend la entrega (estado=entregada). Rebote → estado=`rebotó` + comentario; el nodo no avanza. |
| 3 | **Registrada** | Qualify | Lo completa `register_business` al consumir la invitación: estado=registrada, Tenant, Registrada el. |
| 4 | **Kit de marca listo** | Qualify (futuro, A2) | Cuando el Brand Kit queda guardado. Hoy se completa a mano. |
| 5 | **Primera publicación** | Qualify (futuro) | Cuando sale la primera publicación por el Planificador. Hoy a mano. |

**Reenviar** = revertir el nodo Datos y completarlo otra vez (nueva invitación; la anterior sigue
válida hasta vencer, como hoy). **Anular** = terminar el ítem (evento `1005`): Qualify vence la
invitación en el acto (`expires_at = now()`).

**Automatizaciones nativas de Meegle que Herwin configura, sin código** (caben en las 10 del plan
Free): recordatorio por Lark si «Invitada» lleva 3 días sin «Registrada»; aviso al grupo cuando
estado = `rebotó` o `error`; aviso de celebración al completar «Registrada»; opcional: crear un
grupo de Lark por ítem (`group_type = auto`) para hablar con el cliente desde ahí.

## 3. Cómo se conectan

`[M1 ENTREGADO 2026-10-16]` — el motor existe en `packages/api/src/qualify_api/meegle/`
(`settings`, `envelope`, `receiver`, `client`, `schema`, `onboarding`, `handlers`), la ruta
en `qualify_api/http/meegle_routes.py` y la migración `0064_signup_invites_meegle`. Lo que
este apartado decía antes del PR se mantiene; lo que cambió al construirlo va marcado **(M1)**.

```
Meegle (ítem Alta de cliente)
  │ evento 2001 / 2004 / 1005 (POST firmado, idempotent_key)
  ▼
Qualify api  POST /api/meegle/events  ── graba en la bandeja de webhooks (object="meegle") y responde 200
  ▼ (webhook-worker, fuera del request)
qualify_api.meegle.processor
  ├─ nodo Datos completado → invites.create_invite + mail → Open API: update_fields, comment
  ├─ ítem terminado        → invites.expire
  └─ nodo Datos revertido  → nada (deja reenviar)

Resend ─ webhook email.delivered / opened / bounced (Svix) ─▶ POST /api/mail/resend ── bandeja (object="resend") ─▶ webhook-worker: invites.mark_delivery → Meegle (nodo Invitada, estado)
Signup ─ register_business consume la invitación ─▶ Meegle (nodo Registrada, Tenant)
```

- **Bandeja, no handler inline.** El límite de 1 s y los reenvíos de Meegle son exactamente lo que
  QUA-147 ya resuelve: la ruta solo verifica la firma e inserta la fila (`meta_webhook_events` con
  `object = "meegle"`, `field = "<event_type>"`, `entry_id = work_item_id`, `idempotent_key` como
  `dedup_key`); el procesador del `webhook-worker` la asienta con reintentos. Un handler nuevo por
  evento, mismo contrato `Outcome`. **(M1)** La bandeja ganó un `parser` enchufable
  (`webhooks.receiver.record_delivery(parser=…)`): misma puerta INSERT-only, misma dedup, misma
  cola y misma retención de 29 días para Meta y Meegle. La firma del cuerpo se guarda en
  `signature_header` con prefijo `meegle-sha256=`. Un cuerpo que no es un evento se graba
  `unparseable` y recibe 200 (reintentarlo no lo arreglaría); una firma mala es **401** y no escribe;
  un cuerpo > 256 KB es 413. Handlers registrados: `meegle:2001`, `meegle:1005`, `meegle:2004`
  (`production_meegle_handlers`, solo si `QUALIFY_MEEGLE_*` está puesto; si no, los eventos quedan
  `unsupported`, reprocesables).
- **Cliente Meegle** (`qualify_api.meegle.client`): httpx fino, sin SDK (estilo de la casa): token
  de plugin cacheado (renovado 5 min antes de `expire_time`), `update_fields`, `operate_node
  (confirm|rollback)`, `comment`, `workflow`, `query` y **(M1)** `fields_meta`
  (`POST /field/all`). Sobre de error `err_code`/`err_msg` (el del token, `error.code`/`msg`).
  Los logs llevan solo tipos de excepción y códigos, nunca el token ni el secreto.
- **(M1) Nombres, no ids.** El tipo «Alta de cliente» lo crea una persona en la UI, así que el
  código no conoce `field_key` ni valores de opción: `qualify_api.meegle.schema.SchemaResolver`
  resuelve por **nombre visible** (`MeegleNames`, por defecto los de §2; se pueden cambiar con
  `QUALIFY_MEEGLE_FIELD_*` / `QUALIFY_MEEGLE_NODE_*`) → clave del campo, valor de la opción del
  select «Estado Qualify» (si el campo no es select, manda la etiqueta tal cual) y `node_id` por
  nombre de nodo. Los ids de nodo son de plantilla (`started`, `state_0`, …: iguales para todos los
  ítems del tipo), así que se cachean por tipo y se releen del ítem a mano si falta uno. Un nombre
  que no existe es `MeegleSchemaError` → el evento se reintenta con backoff (da tiempo a crear el
  campo) y muere con el nombre en `last_error`.
- **(M1) Qué escribe cada caso** (`qualify_api.meegle.onboarding.OnboardingEngine`):
  - Nodo **Datos** completado (2001; el nodo se identifica por nombre a partir de
    `node_info.update_nodes`): lee el ítem por `query` (nunca confía en el payload del evento),
    `create_invite(…, meegle_work_item_id)` + correo por Resend; luego `Estado Qualify = invitada`,
    `Enlace de invitación`, `Vence` (ms), `Qualify ref` (= `signup_invites.id`) y el comentario
    «Invitación enviada a … Vence el …». Si el correo es inválido o Resend falla: `Estado = error`,
    comentario con el motivo (y, si la invitación sí quedó creada, el enlace queda en su campo para
    mandarlo a mano), y **Datos** se revierte con `rollback_reason`. Eso se asienta como
    `processed` con `invite_failed:<motivo>` — no se reintenta: lo arregla la persona (D3).
    Cualquier otro nodo completado: `processed` / `ignored:node=<nombre>`.
  - Ítem terminado (1005): `expire_invites_for_work_item` (todas las no usadas pasan a
    `expires_at = now()`), y `Estado = vencida` a mejor esfuerzo (un ítem terminado puede rechazar
    la escritura).
  - Nodo revertido (2004): nada (`ignored:rollback`).
  - Registro: `register_business`, tras cerrar su transacción, llama a `mark_registered`
    (`Estado = registrada`, `Tenant`, `Registrada el`, y `confirm` del nodo **Registrada**; si el
    nodo ya estaba completo, Meegle lo rechaza y se deja en log). **Nunca** falla un registro por
    Meegle: cualquier excepción queda en log con su tipo.
- **Conciliación:** `signup_invites.meegle_work_item_id` (migración 0064) ↔ campo «Qualify ref»
  del ítem. Los eventos repetidos se filtran por `idempotent_key`; un nodo ya completado no se
  vuelve a completar (la API lo rechaza y el handler lo trata como `ok`).
- **Identidad en Meegle:** las escrituras van con `X-User-Key` de un miembro del espacio
  (`QUALIFY_MEEGLE_USER_KEY`; de inicio el de Herwin, `7697105028321938981`). Meegle marca esas
  operaciones con `source = "openapi"`, y el procesador **ignora** los eventos con ese origen para
  no reaccionar a sus propias escrituras (**(M1)** se asientan `processed` / `ignored:openapi`;
  los de otro tipo de ítem, `unsupported` / `other_work_item_type`).
- **(M1) Límite de la firma.** `sha256(plugin_id + request_time + token)` no cubre el cuerpo: un
  `data` manipulado con una firma copiada pasaría. Meegle no ofrece nada más fuerte; lo que acota
  el daño es que el motor relee el ítem por la Open API autenticada antes de actuar y solo actúa
  sobre ítems del tipo y espacio configurados.
- **Resend** `[M2 ENTREGADO 2026-10-16]` — `POST /api/mail/resend` (`qualify_api.mail.routes`,
  montada en `http/app.py`). Firma Svix verificada en `qualify_api.mail.webhook`: cabeceras
  `svix-id`, `svix-timestamp`, `svix-signature` (`v1,<base64>`, varias separadas por espacio
  durante una rotación), secreto `QUALIFY_RESEND_WEBHOOK_SECRET` (`whsec_<base64>`), HMAC-SHA256
  de `"{svix-id}.{svix-timestamp}.{cuerpo}"` comparado en tiempo constante, marca de tiempo con
  tolerancia de 5 min. **Sin secreto el endpoint responde 503 (log en ERROR) y nunca acepta un
  evento sin firmar**; firma mala o cabecera ausente → 401 sin escribir; > 64 KB → 413. El evento
  firmado se graba en la **misma bandeja** (`object = "resend"`, `field = "email.<evento>"`,
  `entry_id = data.email_id`, dedup por hash del contenido; las tres cabeceras Svix quedan en
  `signature_header` con prefijo `svix=`) y responde 200; el `webhook-worker` lo asienta con
  `qualify_api.mail.handlers` (claves `resend:email.delivered|opened|bounced`; cualquier otro
  evento de Resend queda `unsupported`, guardado y reprocesable). El handler: (1) `invites.
  mark_delivery` casa `data.email_id` con `signup_invites.resend_email_id` y pone `delivered_at` /
  `opened_at` / `bounced_at` **solo la primera vez** (un reintento o un segundo «abierto» se asienta
  `processed` / `ignored:repeat`; un id sin invitación — p. ej. un correo de recuperación que
  Supabase mandó por la misma cuenta — `ignored:unknown_email`); (2) si la invitación viene de un
  ítem (`meegle_work_item_id`) y el motor está configurado, escribe en Meegle **a mejor esfuerzo**
  (`OnboardingEngine.mark_delivered|mark_opened|mark_bounced`): entregada → `Estado Qualify =
  entregada` + `confirm` del nodo **Invitada** (si ya estaba completo, Meegle lo rechaza y se deja
  en log); abierta → `Estado = abierta` (no toca nodos; si el «abierto» llegó antes que el
  «entregado», el estado no retrocede); rebotó → `Estado = rebotó` + comentario con
  `data.bounce.message` (`type` / `subType`) y la indicación de corregir «Correo» y volver a
  completar «Datos». Un fallo de Meegle se asienta `processed` / `meegle_failed:<tipo>` (la fila es
  el registro; reintentar no volvería a escribir porque la columna ya está puesta). Las claves que
  trae el payload de un rebote real se registran en el log (`resend bounce: … bounce_keys=…`)
  para confirmar la forma documentada con el primer rebote. **(M1)** `ResendMailer.send` devuelve
  el `id` de Resend y `send_invite_email` lo guarda en `resend_email_id`; el `Mailer` devuelve
  `str | None`.

**Variables nuevas (`.env.prod`):** `QUALIFY_MEEGLE_BASE_URL=https://meegle.com` (opcional),
`QUALIFY_MEEGLE_PLUGIN_ID`, `QUALIFY_MEEGLE_PLUGIN_SECRET`, `QUALIFY_MEEGLE_CALLBACK_TOKEN`,
`QUALIFY_MEEGLE_PROJECT_KEY`, `QUALIFY_MEEGLE_WORK_ITEM_TYPE`, `QUALIFY_MEEGLE_USER_KEY` (M1,
documentadas en `.env.example` y `deploy/.env.prod.example`); `QUALIFY_RESEND_WEBHOOK_SECRET` (M2, también documentada en ambos; sin ella `/api/mail/resend` responde 503 y el resto sigue igual).
Sin las seis de Meegle, el motor queda apagado — `MeegleNotConfigured` nombra las que faltan, el
`just invite` de hoy sigue funcionando y los eventos quedan `unsupported` en la bandeja; el test
estático `test_meegle_settings.py` confina el secreto del plugin a `qualify_api/meegle/`.

## 4. Fases

| Fase | Entrega | Verificación |
|---|---|---|
| **M0 — manual (Herwin, sin código)** | Tipo «Alta de cliente» con nodos y campos en el espacio Qualify; plugin «Qualify» en el Developer Platform con Event Listener (tipo: *Other work item*; eventos 2001, 2004, 1005), URL de callback `https://app.qualify.la/api/meegle/events` y token; instalarlo en el espacio. Resend: API key en `.env.prod` y el webhook hacia `https://app.qualify.la/api/mail/resend` con su *Signing Secret* en `QUALIFY_RESEND_WEBHOOK_SECRET` (runbook `despliegue-hetzner.md` §9, paso 7). | El plugin aparece instalado; el log del `api` muestra el primer evento firmado. |
| **M1 — motor (PR)** — `[ENTREGADO 2026-10-16]` | `qualify_api.meegle` (settings, envelope, receiver, client, schema, onboarding, handlers), ruta `POST /api/meegle/events`, migración `0064` (`meegle_work_item_id` + `resend_email_id`/`delivered_at`/`opened_at`/`bounced_at`), handler de nodo Datos → invitación + correo + escritura, `1005` → vencer, `2004` → nada, `register_business` → nodo Registrada. Tests offline con `httpx.MockTransport` y motor falso (settings, sobre/firma, ruta, cliente, resolutor, casos de uso, handlers); `db` para la bandeja real + 0064 + el write-back del registro. | Completar «Datos» en Meegle manda el correo y el ítem muestra enlace y estado en < 1 min (el `webhook-worker` corre cada 30 s). **Pendiente de verificar en vivo**: requiere M0 (plugin instalado, tipo de ítem creado) y las variables en `.env.prod`. |
| **M2 — entrega (PR)** — `[ENTREGADO 2026-10-16]` | `POST /api/mail/resend` (`qualify_api.mail.webhook` + `routes` + `handlers`): firma Svix, bandeja de webhooks (`object = "resend"`), `invites.mark_delivery` → `delivered_at` / `opened_at` / `bounced_at` (primera vez), y escritura en Meegle a mejor esfuerzo (`mark_delivered` → estado `entregada` + nodo **Invitada**; `mark_opened` → `abierta`; `mark_bounced` → `rebotó` + comentario con el motivo). Variable `QUALIFY_RESEND_WEBHOOK_SECRET`; test estático la confina a `qualify_api/mail/`. Tests offline (firma válida / secreto equivocado / marca vencida / cabecera ausente, sobre, ruta, handlers con bandeja y Meegle falsos vía `httpx.MockTransport`, idempotencia) y `db` (columnas + bandeja real). Sin migración: las columnas son de 0064. | Un correo real a un buzón propio avanza el nodo; uno a un dominio inexistente marca `rebotó`. **Pendiente de verificar en vivo**: requiere el webhook registrado en Resend (runbook `despliegue-hetzner.md` §9) y el secreto en `.env.prod`. |
| **M3 — automatizaciones (Herwin)** | Las 3–4 reglas nativas de §2 y, si quiere, el grupo de Lark por ítem. | Recordatorio llega al tercer día. |
| **Futuro** | Nodos 4 y 5 los completa Qualify (Brand Kit guardado, primera publicación); el alta en la llamada (A2) crea el ítem desde Qualify o desde un formulario de Lark Base. | — |

## 5. Decisiones (cerradas por el fundador el 2026-10-16)

- **D1 — Quién firma en Meegle: un usuario «Qualify bot».** Se crea como miembro en Lark
  (p. ej. `qualify@qualify.la`), se añade al espacio, y su `user_key` (`meegle user search`) va en
  `QUALIFY_MEEGLE_USER_KEY`. Hasta que exista, el de Herwin (`7697105028321938981`).
- **D2 — Dominio del callback: `app.qualify.la`.** El proxy de entrada del VPS lo sirve como host
  extra hacia el mismo Qualify (`QUALIFY_EXTRA_HOSTS` en `/opt/edge/.env`, registro `A` → `2.28.112.133`
  en la zona de Vercel; runbook `despliegue-hetzner.md` §1.1 y §5). La URL canónica de la app sigue
  siendo `qualify.attitudefactory.co` hasta la migración completa (QUA-151). Callback del plugin:
  `https://app.qualify.la/api/meegle/events`.
- **D3 — Reenviar = revertir y completar «Datos».** Gesto nativo del flujo de nodos, queda en el
  historial; crea una invitación nueva (la anterior sigue válida hasta vencer).
- **D4 — Remitente: `no-reply@send.qualify.la`.** Dominio nuevo en Resend (reemplaza a
  `send.attitudefactory.co` en el plan Free); registros en la zona de Vercel sin tocar la raíz, que es
  de Lark Mail. Pasos exactos en el runbook §9.

## 6. Lo que este plan NO hace

- No construye UI en Qualify (ni `/admin`, ni lista de invitaciones). Si algún día hace falta,
  los datos ya están en `signup_invites` y en Meegle.
- No usa el conector de automatización del plugin (triggers/acciones propias): las reglas nativas
  bastan, y el conector exige publicar versiones del plugin por cada cambio de formulario.
- No mueve el registro ni la custodia a Meegle: Meegle ve correo, nombre, negocio, estado y
  enlace; nunca contraseñas, tokens ni datos de cuentas conectadas.
