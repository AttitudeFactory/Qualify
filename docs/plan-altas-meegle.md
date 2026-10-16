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

Resend ─ webhook email.delivered / bounced / opened ─▶ POST /api/mail/resend ─▶ invites.delivery → Meegle (nodo Invitada, estado)
Signup ─ register_business consume la invitación ─▶ Meegle (nodo Registrada, Tenant)
```

- **Bandeja, no handler inline.** El límite de 1 s y los reenvíos de Meegle son exactamente lo que
  QUA-147 ya resuelve: la ruta solo verifica la firma e inserta la fila (`webhook_events` con
  `object = "meegle"`, `field = "<event_type>"`, `idempotent_key` como huella); el procesador del
  `webhook-worker` la asienta con reintentos. Un handler nuevo por evento, mismo contrato `Outcome`.
- **Cliente Meegle** (`qualify_api.meegle.client`): httpx fino, sin SDK (estilo de la casa): token
  de plugin cacheado 2 h, `update_fields`, `operate(confirm|rollback)`, `comment`, `workflow` (para
  resolver `node_id` por nombre una vez y cachearlo), `query`.
- **Conciliación:** `signup_invites.meegle_work_item_id` (nuevo) ↔ campo «Qualify ref» del ítem.
  Los eventos repetidos se filtran por `idempotent_key`; un nodo ya completado no se vuelve a
  completar (la API lo rechaza y el handler lo trata como `ok`).
- **Identidad en Meegle:** las escrituras van con `X-User-Key` de un miembro del espacio
  (`QUALIFY_MEEGLE_USER_KEY`; de inicio el de Herwin, `7697105028321938981`). Meegle marca esas
  operaciones con `source = "openapi"`, y el procesador **ignora** los eventos con ese origen para
  no reaccionar a sus propias escrituras.
- **Resend** (nuevo endpoint): webhook firmado (Svix: `svix-id`, `svix-timestamp`,
  `svix-signature` con `QUALIFY_RESEND_WEBHOOK_SECRET`) → columnas nuevas en `signup_invites`
  (`resend_email_id`, `delivered_at`, `opened_at`, `bounced_at`) → escritura en Meegle. El envío
  guarda el `id` que devuelve Resend para casar el evento.

**Variables nuevas (`.env.prod`):** `QUALIFY_MEEGLE_BASE_URL=https://meegle.com`,
`QUALIFY_MEEGLE_PLUGIN_ID`, `QUALIFY_MEEGLE_PLUGIN_SECRET`, `QUALIFY_MEEGLE_CALLBACK_TOKEN`,
`QUALIFY_MEEGLE_PROJECT_KEY`, `QUALIFY_MEEGLE_WORK_ITEM_TYPE`, `QUALIFY_MEEGLE_USER_KEY`,
`QUALIFY_RESEND_WEBHOOK_SECRET`. Sin las de Meegle, el motor queda apagado (el `just invite` de hoy
sigue funcionando); un test estático confina el secreto del plugin a `qualify_api.meegle`.

## 4. Fases

| Fase | Entrega | Verificación |
|---|---|---|
| **M0 — manual (Herwin, sin código)** | Tipo «Alta de cliente» con nodos y campos en el espacio Qualify; plugin «Qualify» en el Developer Platform con Event Listener (tipo: *Other work item*; eventos 2001, 2004, 1005), URL de callback `https://qualify.attitudefactory.co/api/meegle/events` y token; instalarlo en el espacio. Resend: API key en `.env.prod` (runbook `despliegue-hetzner.md` §9) y webhook hacia `/api/mail/resend`. | El plugin aparece instalado; el log del `api` muestra el primer evento firmado. |
| **M1 — motor (PR)** | `qualify_api.meegle` (settings, client, receiver, handlers), ruta `/api/meegle/events`, migración `0064` (`meegle_work_item_id` + columnas de entrega), handler de nodo Datos → invitación + correo + escritura, `1005` → vencer, `register_business` → nodo Registrada. Tests offline con transporte falso; `db` para la bandeja. | Completar «Datos» en Meegle manda el correo y el ítem muestra enlace y estado en < 1 min. |
| **M2 — entrega (PR)** | Webhook de Resend → `signup_invites` → nodo Invitada / estado rebotó / abierta. | Un correo real a un buzón propio avanza el nodo; uno a un dominio inexistente marca `rebotó`. |
| **M3 — automatizaciones (Herwin)** | Las 3–4 reglas nativas de §2 y, si quiere, el grupo de Lark por ítem. | Recordatorio llega al tercer día. |
| **Futuro** | Nodos 4 y 5 los completa Qualify (Brand Kit guardado, primera publicación); el alta en la llamada (A2) crea el ítem desde Qualify o desde un formulario de Lark Base. | — |

## 5. Decisiones abiertas

- **D1 — Quién firma en Meegle.** Las escrituras de Qualify salen a nombre del `X-User-Key`
  configurado. Recomendado: un usuario «Qualify bot» miembro del espacio, para que el historial no
  diga que fue Herwin. Hasta que exista, el de Herwin.
- **D2 — Dominio del callback.** Hoy `qualify.attitudefactory.co`; cuando `app.qualify.la` esté en
  Hetzner, se cambia la URL en el plugin (caliente, sin publicar versión nueva).
- **D3 — Reenviar.** Revertir + completar «Datos» crea una invitación nueva (como `just invite`).
  Alternativa: un campo booleano «Reenviar» que dispare `1009`. Recomendado: la reversión, es un
  gesto nativo y queda en el historial del ítem.
- **D4 — Resend en `qualify.la`.** Sigue abierta (ver runbook §9: en el plan Free reemplaza al
  dominio actual).

## 6. Lo que este plan NO hace

- No construye UI en Qualify (ni `/admin`, ni lista de invitaciones). Si algún día hace falta,
  los datos ya están en `signup_invites` y en Meegle.
- No usa el conector de automatización del plugin (triggers/acciones propias): las reglas nativas
  bastan, y el conector exige publicar versiones del plugin por cada cambio de formulario.
- No mueve el registro ni la custodia a Meegle: Meegle ve correo, nombre, negocio, estado y
  enlace; nunca contraseñas, tokens ni datos de cuentas conectadas.
