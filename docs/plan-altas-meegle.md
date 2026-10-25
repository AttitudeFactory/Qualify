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
| Cuenta de Instagram | text | opcional; Qualify la lee y la normaliza (`@usuario`, `usuario` o el enlace del perfil → `usuario`) desde m-24852194; la usará la precarga de la identidad de marca (épica m-24852192). Clave `field_dbfee5`. El campo antiguo «Instagram / TikTok» (`field_7ec111`) sigue en el tipo pero Qualify no lo lee |
| Plan | select: `Básico · Plus · Pro` | opcional (m-24852131); vacío = Básico. Las unidades de cada plan viven en `planes-v1` (código), nunca en Meegle |
| Paquete | select: `+2 videos · +20 creaciones · +10 vistas previas` | opcional (m-24852131); los paquetes fijos de `precios-planes-v1`, 90 días desde que se aplican. Sin precios en el ítem |
| Motivo | text | opcional (m-24852131); queda en el historial del plan y del paquete |

**Campos que escribe Qualify** (solo lectura para el equipo, por convención):

| Campo | Tipo | Quién lo pone |
|---|---|---|
| Estado Qualify | select: `pendiente · invitada · entregada · abierta · rebotó · registrada · vencida · error` | Qualify |
| Enlace de invitación | link | Qualify, al invitar (sirve para mandarlo a mano por WhatsApp). Forma `/registro?invitacion=<token>` desde el 2026-10-21; los enlaces viejos `/signup?invite=` siguen abriendo |
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
| — | **Plan ampliado** | equipo (solo administradores del espacio) | m-24852131. Para un negocio ya registrado: se llenan «Plan» / «Paquete» / «Motivo» y se completa. Qualify aplica el plan (subir vale desde ya, bajar desde el mes siguiente) y suma el paquete una vez, y comenta «Plan de {negocio}: Plus. Se sumó el paquete +2 videos, vence el {fecha}.». Se puede revertir y completar otra vez: cada vez suma el paquete elegido una vez. Si el negocio aún no se registró, la elección reemplaza la que espera en la invitación. Valor no válido o rechazo: estado=`error`, comentario y el nodo se revierte. |
| 4 | **Kit de marca listo** | Qualify (futuro, A2) | Cuando el Brand Kit queda guardado. Hoy se completa a mano. |
| 5 | **Primera publicación** | Qualify (futuro) | Cuando sale la primera publicación por el Planificador. Hoy a mano. |

**Plan y paquete al dar de alta (m-24852131).** Al completar **Datos**, Qualify valida «Plan» y
«Paquete» (un valor que no existe falla como un correo inválido: no se crea la invitación) y los
guarda en la invitación (`signup_invites.alta_*`, migración 0096). Cuando `register_business`
crea el negocio los aplica con las mismas funciones del equipo (`just set-plan`, `just add-pack`:
historial con quién —el usuario de Meegle que completó el nodo—, cuándo, Motivo e ítem), y el
paquete vence 90 días después del registro. Idempotencia por evento de Meegle: las claves son
`meegle:<id del evento>:plan` y `:pack`. Se escucha solo el 2001 (nodo completado), nunca la
edición de campos (1009, §7.4). El equipo ve el historial con `just plans --tenant …` y
`just packs --tenant …`. Ninguna pantalla ni correo del dueño muestra precios.

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

### 3bis. Avisos de cambios en tickets al grupo de Lark `[ENTREGADO 2026-10-19]`

Decisión del fundador (2026-10-19): el equipo quiere enterarse en **Qualify-devs** de lo que cambia en
los tickets del espacio (Features `story`, Issues `issue`, Tasks `sub_task`), y Meegle no avisa a nadie
por defecto (solo @menciones y las reglas que configure un admin). Se exprime primero el plan Free
(§7.4) y se programa solo lo que las reglas nativas no pueden hacer: **un aviso genérico por cualquier
cambio de campo**, con quién, qué cambió (campo: antes → después), el ítem y su enlace.

- **Mismo motor, segunda capa.** `qualify_api.meegle.tickets.TicketNotifier` cuelga de los mismos
  handlers (`qualify_api.meegle.handlers`), que ahora **enrutan por tipo de ítem**: el tipo «Alta de
  cliente» → motor de altas (igual que antes); `story` / `issue` / `sub_task`
  (`QUALIFY_MEEGLE_TICKET_TYPES`) → notificador; cualquier otro → `unsupported`
  (`other_work_item_type`, guardado y reprocesable). Claves registradas: `meegle:1001` creado,
  `meegle:1009` campo modificado, `meegle:3001` cambio de estado, `meegle:2001` / `meegle:2004` nodo
  completado / revertido, `meegle:1005` terminado. Mismo contrato `Outcome`, misma dedup por
  `idempotent_key` (en el INSERT), mismo descarte de `source = "openapi"` (así, si un día Qualify
  escribe en un ticket, no se avisa a sí mismo).
- **Qué se cree y de dónde.** Nombre, tipo y estado del ítem se **releen por la Open API**
  (`MeegleClient.query` con el tipo del evento) — la firma del evento no cubre el cuerpo (§3) y la
  relectura demuestra además que el ítem existe en el espacio configurado (si no: `dead` /
  `work_item_not_found`). El **delta** (quién: `user_info`; antes → después: `field_info`; nodo:
  `node_info`) solo existe en el evento — la alternativa, el endpoint de registros de operación,
  cuesta una llamada más por evento contra las 500/día para las mismas cadenas — y se renderiza
  con los metadatos del tipo (`POST /field/all`, nombres y etiquetas de opciones, una vez por tipo
  por proceso). Para `3001` sin `work_item_status` en `field_info`, el estado nuevo sale del ítem
  releído. El enlace es `{QUALIFY_MEEGLE_WEB_URL}/{simple_name}/{tipo}/detail/{id}` (`simple_name`
  del espacio por `POST /open_api/projects/detail`, una vez por proceso; sin él, el aviso va sin
  enlace).
- **Formato** (`msg_type = text`, solo Lark — sin clave `text` de Cliq/Slack; Lark enlaza las URL):

  ```
  🎫 Herwin Rey cambió el estado · Issue «WA-21 · Analítica de la WABA»
  Status: Backlog → Done
  https://project.larksuite.com/5h2wsx/issue/detail/24789637
  ```

  Verbos: `creó` (+ estado o nodo actual), `modificó` (una línea por campo, saltando los que no
  cambian; máximo 12), `cambió el estado`, `completó el nodo «X»`, `revirtió el nodo «X»` (+ motivo),
  `terminó` (+ motivo). Si el evento no trae persona: `una automatización` / `el sistema`.
- **Resultado por evento.** `processed` / `sent`; rechazo definitivo de Lark (`code` ≠ 0 que no sea
  el límite de ritmo, o HTTP 4xx) → `processed` / `lark_rejected:<code>` (Lark contesta 200 aunque
  rechace: se mira el `code`); Lark caído, 5xx o `11232` (límite de ritmo) → excepción → la cola
  reintenta con backoff. La URL del webhook es secreta (quien la tenga publica en el grupo) y nunca
  llega a un log.
- **Coste por aviso:** 1 webhook de Meegle (el evento) + 1 llamada a la Open API (`query`) +
  1 petición a Lark. `fields_meta` y `simple_name` se cachean por proceso. Ver §7.4.
- **Apagado = off.** Sin `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL` el motor de altas sigue igual y los
  eventos de tipos de ticket quedan `unsupported`, reprocesables el día que se ponga. Las seis
  variables de §3 siguen siendo obligatorias (el notificador lee por la misma Open API).
- **Fuera de alcance (anotado):** las subtareas de nodo llegan como eventos `4001`–`4009` del ítem
  padre (p. ej. `4003` tarea completada), no como `work_item_type_key = sub_task`; no se manejan
  todavía (quedan `unsupported`). Y el notificador **no escribe** en Meegle: la parte 2 (§7.2) no
  necesitó código.

**Variables nuevas** (`.env.example`, `deploy/.env.prod.example`): `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL`
(obligatoria para avisar), `QUALIFY_MEEGLE_TICKET_TYPES` (opcional, `story,issue,sub_task`),
`QUALIFY_MEEGLE_WEB_URL` (opcional, por defecto `https://project.larksuite.com`: ahí viven las URL reales de los
ítems — verificado con los grupos de Lark que Meegle crea por ítem y con el parser de URL del MCP para
`story`, `issue` y `sub_task`; `meegle.com` es solo el host de la Open API).

## 4. Fases

| Fase | Entrega | Verificación |
|---|---|---|
| **M0 — manual (Herwin, sin código)** | Tipo «Alta de cliente» con nodos y campos en el espacio Qualify; plugin «Qualify» en el Developer Platform con Event Listener (tipo: *Other work item*; eventos 2001, 2004, 1005), URL de callback `https://app.qualify.la/api/meegle/events` y token; instalarlo en el espacio. Resend: API key en `.env.prod` y el webhook hacia `https://app.qualify.la/api/mail/resend` con su *Signing Secret* en `QUALIFY_RESEND_WEBHOOK_SECRET` (runbook `despliegue-hetzner.md` §9, paso 7). | El plugin aparece instalado; el log del `api` muestra el primer evento firmado. |
| **M1 — motor (PR)** — `[ENTREGADO 2026-10-16]` | `qualify_api.meegle` (settings, envelope, receiver, client, schema, onboarding, handlers), ruta `POST /api/meegle/events`, migración `0064` (`meegle_work_item_id` + `resend_email_id`/`delivered_at`/`opened_at`/`bounced_at`), handler de nodo Datos → invitación + correo + escritura, `1005` → vencer, `2004` → nada, `register_business` → nodo Registrada. Tests offline con `httpx.MockTransport` y motor falso (settings, sobre/firma, ruta, cliente, resolutor, casos de uso, handlers); `db` para la bandeja real + 0064 + el write-back del registro. | Completar «Datos» en Meegle manda el correo y el ítem muestra enlace y estado en < 1 min (el `webhook-worker` corre cada 30 s). **Pendiente de verificar en vivo**: requiere M0 (plugin instalado, tipo de ítem creado) y las variables en `.env.prod`. |
| **M2 — entrega (PR)** — `[ENTREGADO 2026-10-16]` | `POST /api/mail/resend` (`qualify_api.mail.webhook` + `routes` + `handlers`): firma Svix, bandeja de webhooks (`object = "resend"`), `invites.mark_delivery` → `delivered_at` / `opened_at` / `bounced_at` (primera vez), y escritura en Meegle a mejor esfuerzo (`mark_delivered` → estado `entregada` + nodo **Invitada**; `mark_opened` → `abierta`; `mark_bounced` → `rebotó` + comentario con el motivo). Variable `QUALIFY_RESEND_WEBHOOK_SECRET`; test estático la confina a `qualify_api/mail/`. Tests offline (firma válida / secreto equivocado / marca vencida / cabecera ausente, sobre, ruta, handlers con bandeja y Meegle falsos vía `httpx.MockTransport`, idempotencia) y `db` (columnas + bandeja real). Sin migración: las columnas son de 0064. | Un correo real a un buzón propio avanza el nodo; uno a un dominio inexistente marca `rebotó`. **Pendiente de verificar en vivo**: requiere el webhook registrado en Resend (runbook `despliegue-hetzner.md` §9) y el secreto en `.env.prod`. |
| **M4 — avisos de tickets (PR)** — `[ENTREGADO 2026-10-19]` | §3bis: `qualify_api.meegle.tickets` + `events`, handlers enrutados por tipo (`meegle:1001|1009|3001|2001|2004|1005`), cliente con tipo por llamada y `space_simple_name`, variable `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL`. Tests offline (`test_meegle_tickets.py`, handlers, cliente). Sin migración. | Runbook §7.3. **Pendiente en vivo**: bot de Lark, plugin suscrito a Feature/Issue, variable en `.env.prod`. |
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

## 7. Runbook — avisos de tickets y «LISTO» (2026-10-19)

Todo lo de este apartado lo hace una persona en Meegle / Lark; el PR deja el motor listo. Lo
verificado abajo se midió con el MCP de Meegle sobre el espacio real (`6ad251e7ce655b7ed3a0e9b4`,
`simple_name 5h2wsx`) el 2026-10-19.

### 7.1 Lo que hay en el espacio (medido)

| Tipo | `type_key` | Flujo | Estados / nodos |
|---|---|---|---|
| Features | `story` | **nodos** (`flow_type 0`) | Start → Product Evaluation → Product Design → UX Design → Tech Review → Tech Design → Backend / Web Frontend / Android / iOS Development → Testing → Product Acceptance Testing → **Finished** (`end`). Todas las épicas están en `Start`. |
| Issues | `issue` | **estados** (`flow_type 1`) | Backlog (`OPEN`) · Todo (`LSxcc1xn_`) · In Progress (`IN PROGRESS`) · RESOLVED · REOPENED · **Done** (`CLOSED`) · Terminated (`systemEnded`). 230 ítems; 104 en Done. Transiciones: In Progress → RESOLVED / Done; Done → REOPENED. |
| Tasks | `sub_task` | subtareas de nodo | Incomplete (`unfinished`) · Completed (`done`). Son subtareas (eventos `4001`–`4009` del ítem padre). |
| Alta de cliente | `6ad27a818d034c2af89a26d1` (`alta_cliente`) | nodos | los de §2 |

### 7.2 Qué es «LISTO» — y por qué la parte 2 no lleva código

**No existe nada llamado «LISTO» en el espacio**: ni como estado de ningún tipo, ni como opción de un
campo `select`, ni como vista (`search_view_by_title`). **«Listo» es la columna del tablero de Issues
que la interfaz en español muestra para el estado `Done` (`CLOSED`)** — confirmado por el fundador el
2026-10-19 con WA-12 (`24789628`), que está en esa columna y la API devuelve `Done` / `CLOSED` con
«If completed» = `true`. En Features el equivalente es el nodo **Finished** y en Tasks el estado
**Completed**.

Con esa lectura, **el cierre automático ya es nativo y no consume ninguna regla**: `Done` es estado
final del flujo de Issues, y entrar en él pone `archiving_status` («If completed») en `true` en la
misma operación. Evidencia (registro de operaciones de WA-21, `24789637`): un solo `modify` de
`work_item_status` `OPEN → CLOSED` acompañado de `archiving_status false → true` y `archiving_date`.
Los 104 Issues en Done tienen `archiving_status = true`. Para Features, completar el nodo `Finished`
termina el flujo; para Tasks, `Completed` es su único estado final.

Si «LISTO» resulta ser **otra cosa** (un estado nuevo que el fundador añada, o `RESOLVED`), la ruta
sigue siendo nativa — **una regla por tipo, tres de las diez**:

| Tipo | Disparador | Condición | Operación |
|---|---|---|---|
| Issues | *Status changed* (cambio de estado) | estado nuevo = «Listo» (o `RESOLVED`) | *Status transition* → **Done** |
| Features | *Field value changed* / *Node status changed* | el campo o nodo que signifique «Listo» | *Node operation* → completar **Finished** |
| Tasks | *Task completed* | — | nada que hacer: ya es final |

Solo si una regla nativa no pudiera hacer la transición (p. ej. una transición con formulario
obligatorio), el handler tiene ya el cliente a mano (`operate_node` / un `transition_state` por
añadir) respetando el descarte `openapi`; **no se implementa hasta que haga falta**.

### 7.3 Pasos manuales para activar los avisos

1. **Bot de Lark.** Grupo *Qualify-devs* (`oc_049b1d076c73cb424f05f852607afc5a`) → Configuración →
   Bots → Añadir bot → *Bot personalizado* «Meegle tickets». Sin firma ni palabra clave obligatoria
   (el motor manda texto plano sin `timestamp`/`sign`). Copiar el webhook a
   `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL` en `.env.prod` y reiniciar `webhook-worker`
   (`just deploy` / `docker compose up -d webhook-worker`).
2. **Ampliar el Event Listener del plugin.** Developer Platform → plugin «Qualify» → Event
   Listener: hoy solo *Other work item* (Alta de cliente, eventos 2001/2004/1005). Añadir **Feature**
   e **Issue** con los eventos que se quieran recibir por código (ver 7.5 para el reparto) y
   publicar una versión nueva del plugin (el callback se puede cambiar en caliente; la suscripción
   a eventos, no). Reinstalar la versión en el espacio.
3. **Reglas nativas** (7.5): Espacio → Automatización → Nueva regla.
4. **Comprobar:** cambiar el estado de un Issue de prueba; en < 1 min (el worker corre cada 30 s)
   el grupo recibe el texto de §3bis; `select status, last_error from meta_webhook_events where
   object = 'meegle' order by created_at desc limit 5` muestra `processed` / `sent`.

### 7.4 Presupuesto del plan Free (medido en meegle.com/pricing, 2026-10-19)

| Recurso | Free | Qué lo consume aquí |
|---|---|---|
| Reglas de automatización | **10 por espacio** | cada regla nativa de 7.5; las 3–4 de M3 (altas) |
| Standard API | **500 llamadas/día** | 1 por aviso por código (`query`); `field/all` y `projects/detail` una vez por proceso; ~6 por alta |
| Webhook | **100/día** | cada evento que el Event Listener entrega a `/api/meegle/events` (≈3 por alta) |

El cuello es el **webhook**: `1009` dispara **un evento por campo editado** (editar 5 campos en 20
tickets = 100 eventos = el día entero). Las reglas nativas no gastan ni webhooks ni API. De ahí el
reparto:

### 7.5 Reparto recomendado: reglas nativas vs código

| Caso | Vía | Receta / coste |
|---|---|---|
| Issue creado | **regla** `Issues · Work item created → Notification (grupo Qualify-devs)` con plantilla «{{creator}} creó {{name}} {{link}}» | 1 regla, 0 webhooks |
| Issue cambia de estado | **regla** `Issues · Status changed → Notification` («{{operator}} movió {{name}} a {{status}}») | 1 regla |
| Feature creada | **regla** `Features · Work item created → Notification` | 1 regla |
| Feature cambia de nodo | **regla** `Features · Node status changed → Notification` | 1 regla |
| Tarea completada | **regla** `Features · Task completed → Notification` (opcional) | 1 regla |
| **Cualquier campo** editado (asignado, prioridad, etiqueta, nombre…), con antes → después | **código** (este PR): suscribir el plugin a `1009` para Feature e Issue | 1 webhook + 1 API por edición |
| Ítem terminado, con motivo | **código**: `1005` | 1 webhook + 1 API |
| Nodo revertido, con motivo | **código**: `2004` | 1 webhook + 1 API |

Total reglas: 4–5 de avisos + 3–4 de altas (M3) = **≤ 9 de 10**. El código cubre igualmente
`1001`/`3001`/`2001` por si el fundador prefiere no gastar reglas en ellos; es solo cuestión de qué
eventos se suscriben en el plugin.
