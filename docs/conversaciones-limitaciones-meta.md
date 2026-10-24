# Conversaciones (QUA-226) — limitaciones externas y dependencias de Meta

**Estado: 2026-10-16.** Lista verificable que exige el criterio de aceptación 7 del ticket:
cada fila dice qué está implementado en código, qué está configurado en el entorno local,
qué hay que habilitar o aprobar en Meta y qué depende de una cuenta o un token real. Las
columnas con «pendiente» son exactamente eso: nada de lo que sigue se ha observado contra
Instagram en vivo.

> Regla de la casa: el canal en memoria (`QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`) valida
> la interfaz y el flujo interno (bandeja → respuesta → outbox → sender → burbuja). **No
> demuestra que la API de Instagram funcione.** Lo que sí lo demostraría es la columna
> «Verificación» de la tabla 2, hoy vacía.

## 1. Qué hay en el código (rama QUA-226)

| Pieza | Módulo | Estado |
| --- | --- | --- |
| Contratos de canal, repositorios, outbox con aprobación humana, servicio de bandeja, sincronización | `qualify_api.conversations` (E1) | Hecho y probado offline y con `db` |
| Pantalla `/conversations` en Escuchas: cuentas, acceso, lista, hilo, marcar leído, responder | `Qualify/conversations_*.py` (E2) | Hecho; validación en localhost pendiente |
| Adaptador de Instagram Direct (`ConversationSource` + `ConversationSender`) sobre la Messenger Platform | `conversations/instagram_source.py` (E3) | **Lectura verificada en vivo el 2026-10-16** (acceso, listado, mensaje de texto); adjuntos y **envío sin verificar** |
| Handler de webhook `instagram:messages` y mapeo de `entry[].messaging[]` en el envelope | `conversations/webhook.py`, `webhooks/envelope.py` (E3) | Escrito desde el corpus; **sin verificar en vivo** |
| Sender del outbox (ventana revalidada al enviar) y worker con reconciliación opcional | `conversations/sender.py`, `conversations/worker.py` (E5) | Hecho y probado offline |
| Recibos de lectura («Visto») | `webhook.py` (`read` → `ingest_read`), `repository.mark_outbound_read` | Hecho; **solo llega por webhook** (`messaging_seen`), en local no hay webhook |
| Señales de presencia (`mark_seen` al abrir, `typing_on` al escribir) | `service.signal`, `instagram_source.send_action` | Hecho; inline y sin aprobación porque no son contenido; **sin verificar en vivo** |
| Adjuntos: foto, audio, vídeo y PDF en ambos sentidos; corazón (`like_heart`) saliente | `instagram_source` (CDN URL entrante, `attachment` saliente con `document → file`), `sender` (URL pública al enviar; un sticker no enlaza nada), `conversations_page` (cuatro dropzones + ❤️) | Hecho; **sin verificar en vivo** |
| Nota de voz grabada en el navegador | `assets/qualify-voice.js` (Web Audio → WAV 16 kHz mono, en partes base64 < 1 MB) → `conversations_state.voice_*` → R2 como cualquier audio | Hecho; sin ffmpeg ni códec: Instagram acepta `wav` |
| Textos largos | `service.split_reply` + `reply_text`: una fila de outbox por cada ≤ 1000 caracteres, cortadas por párrafo/frase/palabra | Hecho; la pantalla avisa «Se enviará en N mensajes» y ya no limita |
| Perfil del contacto (nombre, usuario, foto) | `instagram_source.fetch_profile` (User Profile API, `GET /{IGSID}?fields=name,username,profile_pic`), `sync.refresh_profile` (al crear el hilo y cada 24 h: la URL de la foto caduca), `threads.counterpart_*` (0065) | Hecho; **sin verificar en vivo**; sin perfil la UI muestra iniciales |
| Borradores asistidos con modelo (E4) | `conversations/suggest.py` (compuerta → `claude-haiku-5-5` con *strict tool use* → veredicto de *grounding*), `conversation_drafts` (0065, RLS, coste por fila), `PostgresDraftRepository`, `composition.grounding_for` (marca + catálogo) | Hecho y probado offline; el envío sigue siendo solo `reply(..., approval=HumanApproval(draft_id))` |
| Paginación histórica de un hilo («cargar anteriores») | `repository.list_messages(limit)` | **Fuera de alcance**: se muestran los últimos 50; el repositorio no expone cursor |

## 2. Dependencias de Meta, con evidencia

| # | Requisito | Fuente en el corpus | Código | Entorno local (2026-10-16) | Meta | Verificación en vivo |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Permiso `instagram_manage_messages` en el token de Página | `business-messaging/instagram-messaging/get-started.md:27,50`; `features/send-message.md` («Requirements») | La matriz C-05 lo conoce (`MANAGE_DMS`); el adaptador devuelve `PERMISSION_MISSING` sin llamar a Meta si no está concedido | **Concedido en desarrollo (2026-10-16, 21:37 UTC):** añadido a `QUALIFY_META_SCOPES` y a la *configuración* de Facebook Login for Business (con `config_id`, el diálogo pide los permisos de la configuración, no los del parámetro `scope`); la conexión `qualifymkt.co` reconectada lo lleva | App Review para Advanced Access (QUA-140, envío 2) sigue pendiente para clientes sin rol | **Verificado** (acceso estándar, tester con rol) |
| 2 | Nivel de acceso: con Standard Access solo se puede tratar con personas con rol en la app | `overview.md:122`; `send-message.md` («Limitations»); `webhooks.md:12-13` | — | Posture `development` en todas las conexiones | Para clientes reales: Advanced Access de `instagram_manage_messages` + app en Live (QUA-142, en curso, plazo Meta 2026-12-11) | Pendiente |
| 3 | El dueño activa «Permitir acceso a los mensajes» en la app de Instagram | `get-started.md:129`; `ig_shapes.UNCOVERED_SURFACES["direct_messages_human_toggle"]` | No hay señal de API: `AccessStatus.UNKNOWN`/`OK` con lista vacía se muestran como «por verificar», nunca como cero | Activado en `qualifymkt.co` el 2026-10-16 (captura del dueño; «Quién puede enviarte solicitudes» = Todos) | Acción humana del dueño de cada cuenta | No automatizable (confirmado por captura, no por API) |
| 4 | Página de Facebook vinculada a la cuenta profesional (fork Facebook Login, ADR 25) | `get-started.md:15`, `send-message.md` («Requirements») | `social_connections.linked_page_id NOT NULL`; el adaptador dirige `/{page-id}/conversations` y `/{page-id}/messages` | Presente en las conexiones | — | Pendiente |
| 5 | Token de Página con tarea `MESSAGE`/`MODERATE` | `get-started.md:16,48`; `send-message.md` | El resolver inyecta la credencial de la conexión (R3) | Credenciales de desarrollo sin el scope 1 | Reconectar tras el punto 1 | Pendiente |
| 6 | Suscripción de la Página a los webhooks de la app (`subscribed_apps`) y campo `messages` suscrito en el panel | `webhooks.md:11,16`; `get-started.md:165` | **Construido (m-24789549):** al conectar o reconectar, `connections/page_subscription.py` hace `POST /{page-id}/subscribed_apps` con `subscribed_fields=messages` y el token de la Página; al desconectar, `DELETE` con el token de la app (mejor esfuerzo). Cada intento queda en `connection_events` (`page_subscribed` / `page_subscribe_failed` / `page_unsubscribed` / `page_unsubscribe_failed`, con el código de error de Meta en `platform_error_code`); un fallo nunca impide conectar | `ConnectionSummary.page_subscription` (`subscribed` / `failed` / `unsubscribed` / sin dato) | Panel → Webhooks → Instagram → suscribir `messages`; `pages_manage_metadata` ya se pide | Construido; la llamada a mano (R3, 2026-10-22) es la evidencia de que `messages` basta |
| 7 | Forma del webhook: `object: instagram`, `entry[].messaging[]` con `sender`, `recipient`, `timestamp`, `message.mid/text/attachments/is_echo` | `webhooks.md:53-81` | Envelope mapea `messaging[]` a `field = "messages"`; handler bajo `instagram:messages` | Receptor y cola duraderos existentes (QUA-147) | — | Pendiente (ningún DM real ha llegado) |
| 8 | Lectura: `GET /{page-id}/conversations?platform=instagram` y `GET /{conversation-id}/messages?fields=…`; solo ~20 mensajes recientes con detalle | `get-started.md:133`; `instagram-api-with-instagram-login/conversations-api.md` («Note») | `MESSAGES_PAGE_LIMIT = 20`, una página por conversación; el webhook es el camino hacia delante | Poll local: `just conversations-sync --tenant …` | — | **Verificado para texto (2026-10-16, 21:44 UTC):** sonda de acceso, listado de conversaciones con participantes y `GET /{conversation-id}/messages` respondieron **200**; un DM de texto de un tester con rol se ingirió como un hilo (`counterpart` = IGSID, `external_conversation_id` = id `aWdf…`) con un mensaje `inbound` con `author_username` y `created_time`. **Pendiente:** adjuntos (media) y el envío (`POST /messages`, nunca llamado) |
| 9 | Conversaciones en «Requests» sin actividad 30 días dejan de aparecer | `conversations-api.md` («Limitations») | No modelado: un hilo ya guardado no desaparece de Qualify aunque Meta deje de listarlo | — | — | Documentado, no cubierto |
| 10 | Envío: `POST /{page-id}/messages` con `{"recipient":{"id":IGSID},"message":{"text"}}`; ≤ 1000 bytes UTF-8 | `send-message.md` («Send a basic message», «Limitations») | `build_payload` valida el límite; el servicio valida 1000 caracteres | Worker local: `just conversations-worker --tenant … --sync` | — | **Verificado (2026-10-16, 22:07 UTC):** una respuesta aprobada en `/conversations` salió por el worker (`claimed=1 sent=1`), `POST` **200** con `message_id`; `mark_sent` escribió la fila `outbound` con `delivery_status = sent` y `last_inbound_at` no se movió (B2) |
| 11 | Ventana de 24 h desde el último mensaje de la persona | `overview.md:27-28` | `WindowClosed` al redactar y `window_closed` al enviar (sender) | — | Human Agent tag (7 días) **no modelado**: otro permiso y otra App Review | Pendiente |
| 11b | «Visto» del cliente: webhook `messaging_seen` (`entry[].messaging[].read.mid` + `timestamp`) | `webhooks.md:41,211-236` | `parse_messaging_item` → `RemoteRead` → `mark_outbound_read` (toda salida ≤ timestamp pasa a `read`) | Sin webhook en local: no observable aquí | Suscribir `messaging_seen` en el panel (hoy solo `messages` y `mentions`) | Pendiente |
| 11c | Señales al cliente: `POST /{page-id}/messages` con `sender_action` = `mark_seen` / `typing_on` / `typing_off`, solo con `recipient` | `features/sender-actions.md` | `InstagramDirectSender.send_action`; `service.signal` las ignora si la ventana está cerrada; nunca pasan por el outbox | Se envían al abrir un hilo y mientras se escribe (cada ≥ 6 s) | — | Pendiente |
| 11d | Lo que Instagram **no** expone: «escribiendo…» del cliente y «entregado» | `webhooks.md` (campos: `messages`, `messaging_postbacks`, `messaging_seen`, `message_reactions`, …) | La UI no muestra typing ajeno ni «entregado»; solo «Enviando» (outbox), «Enviado» (200 de Meta) y «Visto» | — | — | No existe en la API |
| 11e | Adjuntos: entrada `attachments[].payload.url` (webhook) / `image_data.url`, `video_data.url`, `file_url` (edge); salida `message.attachment.{type,payload.url}` con URL pública — `image` png/jpeg ≤ 8 MB, `audio` aac/m4a/wav/mp4 ≤ 25 MB, `video` mp4/ogg/avi/mov/webm ≤ 25 MB, `file` pdf ≤ 25 MB; sticker `like_heart` sin payload | `webhooks.md:66-77`; `graph-api/reference/message.md:98`; `send-message.md` («Send an image», «Send a heart sticker», «Limitations») | `messages.media_url` guarda la URL CDN entrante; un adjunto saliente se sube a R2 y el sender publica la URL (`/public/media/{token}`, 15 min) **al enviar**; `document` se traduce a `file` en el cable; el corazón va como `media_type = sticker` sin objeto | `QUALIFY_PUBLIC_MEDIA_BASE_URL` apunta al túnel hacia el servidor de `qualify_api` (en local `uvicorn` en el puerto 8010; no a Reflex en el 3000, que no tiene la ruta `/public/media`; ver `.env.example`) | Encuestas y ubicación **no existen** en la API de envío de Instagram | Pendiente (ni un adjunto entrante ni uno saliente observados aún) |
| 11f | Perfil del contacto: `GET /{IGSID}?fields=name,username,profile_pic` con token de Página; consentimiento implícito al escribir al negocio; la URL de la foto caduca en días | `features/user-profile.md` | `fetch_profile` → `threads.counterpart_name/username/avatar_url/profile_at`; se refresca cada 24 h; cualquier error deja el hilo sin perfil (iniciales) | — | Advanced Access para cuentas sin rol, como el resto | Pendiente |
| 11g | Tiempos de Graph y envíos ambiguos: httpx espera 5 s por defecto y Meta tarda más en el edge de mensajes con adjuntos y en un envío cuya media descarga de Qualify durante la petición | Observado 2026-10-16: `ReadTimeout` repetidos en `GET /{conversation-id}/messages`; un envío de foto hizo `ReadTimeout`, se reintentó y **llegó dos veces** | Lecturas con 30 s y envíos con 60 s (`READ_TIMEOUT_S`/`SEND_TIMEOUT_S`); un fallo de transporte **después** de enviar la petición (`ReadTimeout`, `RemoteProtocolError`, …) es `is_ambiguous`: el sender lo cierra como `failed` con `send_ambiguous` y no reintenta; la pantalla dice «puede haber salido» y la sincronización muestra el eco si salió | — | La Messenger Platform no admite claves de idempotencia | Verificado el fallo; la mitigación, pendiente de observar |
| 11h | Sticker `like_heart` por API | `send-message.md` («Send a heart sticker») | `reply_sticker` existe y funciona (POST 200, 2026-10-16) | — | En la app de la persona llega como un **corazón blanco**, no el rojo de la app | **Verificado**; por eso el botón ❤️ envía el emoji como texto (`HEART_TEXT`) |
| 11i | Audio por la API de lectura: **no existe**. Cualquier mensaje de audio (las notas de voz de la persona y los ecos de los audios que envía Qualify) vuelve del edge `GET /{conversation-id}/messages` como `is_unsupported: true`, con `message` vacío y sin `attachments` | **Verificado en vivo 2026-10-16** (sonda sobre el hilo real) | El parser lo guarda como `media_type = other`; la pantalla dice «Contenido que Instagram no muestra aquí (p. ej. una nota de voz)» y la lista «Nota de voz u otro contenido»; el envío de audio sí funciona (POST 200 y la persona lo oye) | — | Un webhook `messages` con `is_unsupported` se trata igual | Verificado |
| 11j | Deshacer el envío («eliminar para todos») y editar un mensaje | Ningún endpoint en el corpus (`features/*`, `webhooks.md`: solo `is_deleted` cuando el **cliente** borra) | «Eliminar para mí» = `messages.deleted_at` (local, por tenant); no hay «para todos» ni «editar» en la pantalla | — | No existe en la Messenger Platform para Instagram | Documentado |
| 12 | Códigos de error (190 auth, 10 y 2xx permisos, 429/5xx reintentables) | `graph_errors.py` (190 verificado en vivo 2026-08-14 en otro módulo); el resto, lectura del corpus | `InstagramDirectError.is_auth_error / is_permission_error / is_retryable` | — | — | Solo 190 verificado (en otro endpoint) |
| 13 | Presupuesto de llamadas en Development Mode: 200/h por par Página-app | `ACCESS-MODEL.md` vía QUA-20 | `--sync-interval` 300 s por defecto; el ledger de llamadas del inbox **no** está cableado | — | — | Pendiente |

## 3. Qué debe configurar el fundador antes de una prueba real

1. **Meta App Dashboard → Casos de uso → Personalizar:** añadir `instagram_manage_messages`
   (hoy queda fuera del envío 1, QUA-124). Comprobar su nivel de acceso (Standard es
   suficiente para cuentas con rol en la app; Advanced para clientes).
2. **`.env` (local) y `.env.prod`:** añadir `instagram_manage_messages` a
   `QUALIFY_META_SCOPES` y **reconectar** la cuenta de Instagram desde `/connections` para
   que el nuevo token lo lleve. Hasta entonces el adaptador responde `PERMISSION_MISSING`
   (`scope_not_granted`) sin gastar llamadas.
3. **Instagram (app del dueño):** Configuración → Mensajes y respuestas a historias →
   Controles de mensajes → Herramientas conectadas → *Permitir acceso a los mensajes*.
4. **Meta App Dashboard → Webhooks → Instagram:** suscribir el campo `messages` al mismo
   callback que ya recibe `mentions`/`comments`. La suscripción de la Página
   (`POST /{page-id}/subscribed_apps`) la hace Qualify al conectar desde m-24789549.
5. **Cuenta de prueba:** un tester con rol en la app que escriba por DM a la cuenta
   conectada (Standard Access solo cubre a personas con rol). Sin eso ningún webhook ni poll
   devolverá mensajes aunque todo lo anterior esté bien.
6. **Worker:** `just conversations-worker --tenant <uuid> --sync` para el poll + envío, o el
   `webhook-worker` ya existente para la vía por webhook.

## 4. Qué puede impedir la prueba real aunque todo esté configurado

- **App Review / Advanced Access** (QUA-140, QUA-142): para cualquier persona sin rol en la
  app. Bloquea clientes reales, no el desarrollo con testers.
- **Ambigüedad Live/Standard (enmienda ADR 21/24, punto d):** si la app pasa a Live, no está
  probado que los permisos con Standard Access sigan funcionando para los roles. Probar con
  un tester antes de cambiar el modo.
- **Interruptor del dueño (fila 3):** sin él, poll y webhook devuelven vacío y no hay forma
  de distinguirlo por API. La bandeja lo muestra como «por verificar».

## 5. Pendientes que este ticket deja escritos

- **E4 — borradores asistidos: hecho.** `suggest.py` + `conversation_drafts` (0065). Lo que
  queda: observar el coste real por sugerencia (queda en la fila: `model_id`, tokens, USD) y
  decidir si el catálogo vacío debe bloquear la sugerencia en vez de marcarla «requiere
  revisión».
- **Saldo del modelo:** el 2026-10-16 la primera «Sugerir respuesta» real devolvió `400 Your credit balance is too low` de la API de Anthropic (la cuenta de `QUALIFY_ANTHROPIC_API_KEY` sin saldo). La pantalla lo dice en un toast y el botón vuelve a estar disponible; hasta recargar saldo no hay sugerencias en ningún entorno.
- **Verificación en vivo de la segunda pasada:** perfil (11f), adjuntos de vídeo/PDF/corazón y
  nota de voz (11e) están escritos desde el corpus; hay que mandar y recibir uno de cada.
- **Paginación histórica de un hilo:** el repositorio expone `limit` sin cursor; la pantalla
  muestra los últimos 50 y lo dice. Añadir `before` al repositorio y «cargar anteriores» a
  la pantalla es un seguimiento pequeño.
- **Ledger de llamadas (fila 13):** `inbox.repository.calls_in_last_hour` existe para
  comentarios; cablearlo al poll de conversaciones queda para cuando haya tráfico real.
- **«Requests» a 30 días (fila 9):** decidir si merece alerta.
- **Migración 0065:** `origin/main` ya tiene `0063_signup_invites` y `0064_signup_invites_meegle`.
  La migración de esta rama debe renumerarse a `0065` sobre `0064` al incorporar `main`,
  antes de aplicarla en cualquier entorno compartido (ensayado en un worktree aparte). En la
  base de desarrollo local las columnas de perfil y `conversation_drafts` se aplicaron a mano
  como `qualify_owner` el 2026-10-16 (la revisión ya estaba aplicada y se editó *in place*).

## 6. Comentarios de historias (m-24789644, R1)

**Estado: 2026-10-21 — R1 cerrado como limitación de Meta.** Meta lista las historias y su número de comentarios, pero **no entrega los comentarios por la API**: `GET /{story-id}/comments` responde `400 (#10) Comments cannot be made on story media.` La capacidad `story_comments` queda implementada y **apagada**, y no debe encenderse mientras Meta no abra ese edge (encendida, cada sincronización fallaría en la historia monitoreada). Evidencia y procedimiento, abajo.

### Resultado de R1 (2026-10-21, 16:5x UTC)

Prueba con una conexión real en local (Facebook Login for Business, acceso Standard, posture `development`), cuenta `@rauldevgames` con los permisos `instagram_basic`, `instagram_manage_comments`, `pages_read_engagement`, `pages_show_list`, `business_management`, `instagram_content_publish`. Una historia publicada a las 16:45 UTC con un comentario de otra cuenta. Salida de `just story-probe`:

```json
{
  "verdict": "comments_refused",
  "stories_listed": 1,
  "stories_error": null,
  "checks": [
    {
      "story_id": "18138008500637031",
      "media_product_type": "STORY",
      "timestamp": "2026-10-21T16:45:58+00:00",
      "media_error": null,
      "comments_on_first_page": null,
      "has_more_comments": null,
      "comments_error": {"http_status": 400, "code": 10, "subcode": null}
    }
  ]
}
```

Lectura directa del mismo id, para el texto exacto del error (solo mensaje y código; sin token):

| Llamada | Respuesta |
| --- | --- |
| `GET /{ig-user-id}/stories` | **200**, 1 historia |
| `GET /18138008500637031?fields=id,media_product_type,comments_count` | **200**, `media_product_type: STORY`, **`comments_count: 1`** |
| `GET /18138008500637031/comments` | **400**, `OAuthException` código 10: **«(#10) Comments cannot be made on story media.»** |

Conclusión: no es un permiso que falte (el mismo token lee los comentarios de los Reels, y Meta sabe que la historia tiene uno: `comments_count: 1`); es el edge `/comments`, que Meta no ofrece para historias. Lo que sí queda abierto, sin probar: si el webhook `comments` notifica los comentarios de historias (requiere la suscripción de webhooks, QUA-129).

**Tropiezos de la prueba, por si se repite:** (1) en el `.env` local, `QUALIFY_META_APP_SECRET` tenía pegada la variable siguiente en la misma línea, y el canje del código fallaba con 400; (2) Facebook invalidó la sesión una vez (`190`/`460`) tras iniciar sesión en el navegador integrado, y hubo que reconectar; (3) el diálogo reutiliza la «configuración anterior» del usuario: conectó `@rauldevgames`, no `qualifymkt.co` — para elegir otra cuenta, «Editar configuración».

### Qué dice la documentación (corpus `reference/meta-instagram-platform/`)

| Pregunta | Respuesta del corpus | Fuente |
| --- | --- | --- |
| ¿Las historias salen en `GET /{ig-user-id}/media`? | No: tienen su propio edge, `GET /{ig-user-id}/stories`, con los mismos nodos IG Media (`media_product_type = STORY`) | `instagram-graph-api/reference/ig-user/stories.md`; `reference/instagram-media.md:91` |
| ¿Qué devuelve `/stories`? | Solo las historias de las últimas 24 h; nunca las de Live ni las que son un reenvío | `ig-user/stories.md` («Limitations») |
| ¿Qué permisos pide `/stories`? | `instagram_basic` + `pages_read_engagement` (y `ads_read` o `ads_management` si el rol en la Página viene de Business Manager) | `ig-user/stories.md` («Permissions») |
| ¿Se puede comentar una historia? | Sí: la guía de respuestas privadas incluye «story» entre lo que una persona comenta | `private-replies.md:5,9,46` |
| ¿`GET /{story-id}/comments` devuelve esos comentarios? | **No lo dice**, ni a favor ni en contra. **La prueba real dice que no** (arriba) | `ig-media/comments.md`, `comment-moderation.md` |
| ¿El webhook `comments` se dispara con historias? | **No lo dice** | `webhooks.md` |
| Respuestas a historias | Son **otra cosa**: llegan como DM (`messages` con `reply_to.story`), no como comentarios; las trata Conversaciones (QUA-229) | `changelog.md:192`; `webhooks.md` |

### Qué hay en el código

| Pieza | Dónde | Estado |
| --- | --- | --- |
| Lectura de `/stories` (mismos campos y mismo parser que `/media`, paginada, sin `since`) | `inbox/media_client.py` (`list_recent_stories`) | Hecho y probado offline contra el contrato |
| Capacidad `story_comments`: con `QUALIFY_STORY_COMMENTS=on` el selector añade las historias, una historia se puede monitorear y sus comentarios se sincronizan por el mismo `/comments` | `inbox/service.py` (`story_comments`), `inbox/composition.py` (`story_comments_enabled`) | Hecho; **apagada por defecto**. Apagada, `/stories` no se llama y una historia sigue siendo `unsupported_surface` |
| Sentimiento e intención de esos comentarios | Sin cambios: un comentario de historia se guarda como el de un Reel y entra en las dos colas | Probado contra Postgres (`test_inbox_story_comments_db.py`) |
| Etiqueta «Historia» en Interacciones | `Qualify/inbox_vm.py` (`STORY_LABEL`) | Hecho (PR 4a) |
| Sonda de R1 (solo lectura) | `inbox/story_probe.py`, `just story-probe` | Hecha y probada offline; **ejecutada contra Meta el 2026-10-21** (resultado arriba) |

### Cómo repetir R1 (cuatro pasos)

1. Publicar una historia en `qualifymkt.co` y que un tester con rol en la app la comente (Standard Access solo cubre a personas con rol).
2. Con la conexión real de `qualifymkt.co` en la base (OAuth funcionando en local, o en el servidor), ejecutar la sonda **sin encender nada**: `just story-probe --tenant <uuid> --connection <uuid>`. Hace como máximo 7 llamadas, anotadas en el presupuesto de 200/h de la conexión, e imprime un JSON sin tokens ni texto de comentarios.
3. Leer el `verdict` del JSON:
   - `comments_served`: Meta devuelve los comentarios → seguir al paso 4.
   - `comments_empty`: la historia se lista pero el edge devuelve una página vacía aunque haya comentarios → limitación de Meta.
   - `comments_refused`: el edge responde con error (el JSON trae `http_status`, `code` y `subcode`) → limitación de Meta o de permisos.
   - `stories_not_listed`: falla `/stories` (lo más probable, falta `pages_read_engagement`) → configuración pendiente.
   - `no_live_story`: no había historia en las últimas 24 h → repetir el paso 1.
4. Solo con `comments_served`: arrancar la app con `QUALIFY_STORY_COMMENTS=on`, monitorear la historia en Interacciones, sincronizar y esperar el análisis automático (m-24852204: corre solo tras la búsqueda). Si el comentario aparece con su sentimiento y su intención, R1 queda confirmado y la capacidad se puede encender en producción.

Si Meta cambia de criterio, repetir estos pasos y sustituir el resultado de arriba.

**Riesgo para el día en que se encienda:** una historia caduca a las 24 h pero el monitoreo dura 14 días. La sincronización seguirá pidiendo `GET /{story-id}/comments` durante esos días; si Meta deja de servir el id al caducar, la marca de «medio borrado» (código 100, subcódigo 33) la dejará de monitorear sola, como a un Reel borrado.


## 7. Fase C — continuar en privado (m-24789646): estado por origen

Cada operación de Meta que Fase C necesita y que no está verificada va detrás de una **capacidad por origen**, apagada por defecto (`packages/api/src/qualify_api/followups/capabilities.py`). Se enciende con su variable a `on` (cualquier otro valor la deja apagada), pero una capacidad **no implementada** sigue apagada aunque la variable diga `on`: no hay código que ejecutar. Su estado se cambia en el código, con la evidencia aquí, nunca con un ajuste.

| Capacidad | Variable | Estado actual | Qué falta para activarla |
| --- | --- | --- | --- |
| `comment_private_reply` — respuesta privada a un comentario (`recipient.comment_id`: un solo mensaje, dentro de 7 días) | `QUALIFY_COMMENT_PRIVATE_REPLY` | **Verificado** (R1, 2026-10-22) | Encenderla en el despliegue (abajo, «Qué necesita producción») |
| `story_comments` — comentarios en historias | `QUALIFY_STORY_COMMENTS` | **Limitación de Meta** (§6: «Comments cannot be made on story media») | Que Meta abra el edge; repetir `just story-probe` |
| `story_reply_context` — a qué historia responde un DM (`reply_to.story`) | `QUALIFY_STORY_REPLY_CONTEXT` | **Verificado** (R3, 2026-10-22) | Encenderla y **suscribir la Página** de cada cuenta a la app (sin eso Meta rechaza el DM de vuelta, abajo) |
| `public_notice` — aviso público «Te enviamos la información por DM 💬» | `QUALIFY_PUBLIC_NOTICE` | **Verificado** (R4, 2026-10-22, con el arreglo del tiempo de espera de `replies/client.py`) | Encenderla en el despliegue (abajo) |

El DM normal a un hilo con la ventana de 24 h abierta **no** es una capacidad: QUA-226 lo verificó en producción y siempre está disponible.

**Respuesta pública a un comentario comercial (Fase B, m-24789645).** Usa el mismo `POST /{ig-comment-id}/replies` y el mismo tiempo de espera de 60 s que el aviso público; no es una capacidad de esta tabla porque siempre pasa por un borrador aprobado. Probada en vivo el 2026-10-23 (`sent`, ≈ 6 s de Meta): [interacciones-fase-b-respuestas-comerciales.md](interacciones-fase-b-respuestas-comerciales.md) §7 y §10.

**Vínculo de datos (`interaction_followups`, migración 0071).** Una fila por interacción (comentario o respuesta a historia): su intención comercial (`comment_intent_results`, si la abrió un análisis), el hilo privado del autor en Conversaciones, el envío que una persona aprobó (`conversation_outbox`) y el estado del aviso público, independiente del DM. El borrador sigue en `conversation_drafts` y la entrega en el outbox: aquí no se copian. El hilo privado se crea **solo cuando una persona aprueba un envío** (abrir una consulta no llena Conversaciones de hilos vacíos), y se puede crear antes de que la persona escriba porque el `from.id` de un comentario es el IGSID del autor (`ig-comment.md`), el mismo identificador que usan los DMs (`overview.md`: «specific to the person and the Instagram account»); R1 lo comprobó: el `recipient_id` que devolvió Meta es el `from.id` del comentario y el id del hilo DM del autor (2026-10-22).

### Respuesta privada a un comentario (PR 2) y cómo hacer R1

**Contrato que se construyó** (`features/private-replies.md` de Messenger Platform y `instagram-platform/private-replies.md`): `POST /{page-id}/messages` con `{"recipient": {"comment_id": …}, "message": {"text": …}}` — el mismo endpoint y el mismo token de Página que ya envían los DMs en producción (la guía de Instagram Platform escribe `/{ig-user-id}/messages`; la de Messenger Platform, `/{page-id}/messages`, que es la que usa Qualify). Permisos documentados: `instagram_manage_comments` y `pages_messaging` (la guía de Instagram Platform añade `instagram_basic` y `pages_read_engagement`). Límites: **un solo mensaje por comentario, dentro de 7 días** desde que se escribió; la conversación sigue solo si la persona responde (entonces aplica la ventana de 24 h). Llega a la bandeja principal si la persona sigue a la cuenta, o a «Solicitudes» si no.

**Cómo lo aplica Qualify:**

| Regla | Dónde |
| --- | --- |
| Un tipo de envío más del outbox (`kind = 'private_reply'`), con `comment_id` y `reply_deadline` (comentario + 7 días); sigue exigiendo `approved_by_user_id` | migración 0073, `conversations/outbox.py` (`PrivateReplyTarget`) |
| Como mucho una respuesta privada viva (`pending`/`sending`/`sent`) por comentario; una `failed` no bloquea otro intento | índice `uq_conv_outbox_private_reply`, `PrivateReplyExists` |
| El plazo de 7 días se revalida al enviar (`private_reply_expired`), igual que la ventana de 24 h de un DM | `conversations/sender.py` |
| Si la persona escribió por DM en las últimas 24 h, se envía un DM normal (verificado) y no se gasta la respuesta privada | `followups/service.py` (`SendOptions.chosen`) |
| Se guarda el `recipient_id` que devuelve Meta (`conversation_outbox.recipient_external_id`); si no coincide con el IGSID del hilo, el envío se conserva y se registra `conversations.sender.recipient_mismatch` | `conversations/sender.py` |

**R1, paso a paso (cuando se haga):**

1. Un tester con rol en la app (Standard Access solo cubre a personas con rol) comenta una publicación o Reel de la cuenta conectada **y no le ha escrito por DM en las últimas 24 h**.
2. Comprobar que el token de la conexión tiene `pages_messaging` además de `instagram_manage_comments`; si no, reconectar pidiéndolo.
3. Arrancar la app **y el worker** con `QUALIFY_COMMENT_PRIVATE_REPLY=on` (el sender también la comprueba: con la capacidad apagada, una respuesta privada en cola se marca `failed` con `private_reply_disabled` en vez de enviarse), abrir la consulta de ese comentario, aprobar un texto corto y correr `just conversations-tick --tenant <uuid>`.
4. Resultado esperado: la fila del outbox queda `sent`, con `recipient_external_id` igual al `external_thread_id` del hilo DM (sin `recipient_mismatch` en el log), y el tester ve el mensaje en Instagram con el enlace a la publicación.
5. Pegar aquí la fecha, el código de respuesta y la comprobación del destinatario (sin tokens ni textos). Con eso, la capacidad pasa a **verificada** en `followups/capabilities.py`.

### Consultas desde comentarios (PR 3)

- **Apertura automática (B1).** Tras cada análisis automático de intención (m-24852204: después de cada búsqueda de comentarios y en el barrido del `webhook-worker`), cada comentario con intención comercial de los **últimos 7 días** que aún no tiene consulta se abre en Conversaciones → «Consultas desde comentarios», con su borrador. Los más antiguos no se abren solos (ya no admiten respuesta privada), pero se pueden abrir a mano. El análisis no se deshace si la apertura falla: se reintenta en el siguiente.
- **Apertura a mano.** «Responder por DM» en cada comentario de Interacciones abre (o reutiliza) su consulta y lleva a `/conversations?consulta=<id>`, con la tarjeta primero y resaltada.
- **El borrador** lo escribe el mismo generador que «Sugerir respuesta» (Claude Haiku), con contexto: que es un DM que responde a un comentario público, en qué publicación y qué intención se detectó. Solo usa los datos validados del negocio; si falta uno, marca «Requiere revisión» y lista lo que hay que confirmar. Si el borrador falla, la tarjeta ofrece «Generar borrador».
- **Decidir.** Editar, «Regenerar» (el borrador anterior queda descartado), «Descartar» la consulta o «Aprobar y enviar». Al aprobar, el mensaje entra al outbox con la aprobación de la persona y el borrador queda `accepted` (enviado tal cual) o `edited` (con el texto enviado): `generated_text` frente a `final_text` es el diff guardado (B2).
- **Cuándo no se puede enviar**, la tarjeta lo dice por cada vía: el DM, si la persona no escribió en 24 h; la respuesta privada, si pasaron 7 días o si la capacidad está apagada («Por verificar», con su variable).
- **Límite conocido:** la lista muestra las consultas de todas las cuentas del negocio, no solo la elegida en el selector de cuenta.

### Aviso público (PR 4)

El aviso «Te enviamos la información por DM 💬» es una **respuesta pública al comentario** (`POST /{ig-comment-id}/replies`, el mismo cliente `replies/client.py` que ya usan las respuestas a comentarios). Es un paso **posterior e independiente** del mensaje privado: tiene su propio estado en `interaction_followups` (`notice_*`, migraciones 0071 y 0074) y nunca toca el envío ni la bandeja.

**Reglas:**

| Regla | Dónde |
| --- | --- |
| Solo se ofrece en un **comentario** (una respuesta a historia no tiene comentario público) y con `public_notice` encendida; sin la capacidad, la tarjeta no muestra la casilla y aprobar con un aviso se rechaza | `followups/service.py` (`public_notice_available`, `approve_and_queue`), CHECK `ck_followup_notice_comments_only` |
| La persona ve el texto (por defecto «Te enviamos la información por DM 💬», editable, máximo 300 caracteres) y lo aprueba **en el mismo clic** que el mensaje; si desmarca la casilla, sale solo el mensaje | `Qualify/followups_page.py`, `followups_state.py` |
| Nada sale sin aprobación humana (ADR 21c): el aviso pasa a `pending` solo al aprobar con `HumanApproval`; el worker solo publica avisos `pending` | `followups/repository.py` (`approve_followup`), `followups/notice.py` |
| Se publica **solo tras un mensaje confirmado**: la fila del outbox enlazada (`outbox_id`) está `sent` con `external_message_id`. Si quedó `failed` o `dead` (incluidos `send_ambiguous`, `private_reply_expired`, `private_reply_disabled`), el aviso queda `skipped` con el código `dm_<estado>:<código>` y no se llama a Meta. Mientras el mensaje está en cola, el aviso espera | `followups/notice.py` (`skip_unsent`, `claim`) |
| **Un único aviso por interacción**: la fila del followup es la clave; el worker la reclama con un UPDATE guardado (`pending → posting`, `FOR UPDATE SKIP LOCKED`) y cada cierre exige `notice_status = 'posting'`; el id de Meta es único por conexión | migración 0074, índice `uq_followup_notice_external_id` (0071) |
| Error **transitorio** (HTTP 429/5xx, códigos 1, 2, 4, 17, 32, 341, 613): vuelve a `pending` con espera `4^intentos` s, hasta 5 intentos (`max_attempts:<código>`). Error **definitivo** (otro código de Meta, p. ej. `http_400_code_100`, o `http_401_code_190`): `failed`. En `notice_error_code` solo hay códigos, nunca texto | `followups/notice.py` |
| Si la petición pudo llegar a Meta sin respuesta clara (corte de red, 200 sin id, worker caído a mitad con la fila en `posting` más de 10 min), el aviso queda `failed` con `notice_ambiguous` y **no se reintenta**: un segundo aviso público es peor que ninguno | `followups/notice.py` |
| Un fallo del aviso no afecta al mensaje ni a la bandeja: no cambia el followup aprobado ni el outbox, y un error de token no degrada la conexión (eso lo decide el envío de mensajes) | `followups/notice.py` |
| Lo publica el **conversations-worker**, después del envío de cada pasada y aunque el envío haya fallado; la capacidad se lee en el worker: con `public_notice` apagada allí, un aviso que le llegue queda `failed` con `public_notice_disabled` (igual que una respuesta privada con su capacidad apagada). Con `QUALIFY_CONVERSATIONS_DM_CHANNEL=memory` los avisos van a un cliente en memoria y no se publica nada | `conversations/worker.py`, `followups/composition.py` |

**Cómo se probará R4 en producción (QUA-128):**

1. Partir de una consulta cuyo mensaje privado ya se puede enviar (R1 hecho, o un tester que escribió por DM en las últimas 24 h) en un comentario de un tester con rol en la app. Comprobar que el token de la conexión tiene `instagram_manage_comments` (y `pages_read_engagement`), los permisos de la respuesta a comentarios.
2. Encender `QUALIFY_PUBLIC_NOTICE=on` **en la app y en el conversations-worker** (y `QUALIFY_COMMENT_PRIVATE_REPLY=on` si el envío es por respuesta privada). En la tarjeta debe aparecer «Publicar también un aviso en el comentario» con el texto por defecto.
3. Aprobar el mensaje con el aviso marcado. Antes de que salga el mensaje, comprobar en la base que el followup tiene `notice_status = 'pending'` y que no hay respuesta pública en Instagram.
4. Correr `just conversations-tick --tenant <uuid>` (o esperar al worker). Esperado: la fila del outbox queda `sent`; en la misma pasada, el followup pasa a `posted` con `notice_external_id` y `notice_posted_at`, y el tester ve la respuesta pública bajo su comentario. Repetir el tick: no aparece una segunda respuesta.
5. Caso negativo: con otro comentario, provocar que el mensaje no salga (p. ej. aprobar con `QUALIFY_COMMENT_PRIVATE_REPLY` apagada en el worker → `private_reply_disabled`). Esperado: `notice_status = 'skipped'` con `notice_error_code = 'dm_failed:private_reply_disabled'` y ninguna respuesta pública.
6. Pegar aquí la fecha, los estados y códigos observados (sin tokens ni textos de usuario). Con eso, `public_notice` pasa a **verificada** en `followups/capabilities.py`.

### Respuestas a historias (PR 5)

Una respuesta a una historia **no es un comentario**: llega como un mensaje directo, y Meta indica a qué historia responde junto al mensaje. Qualify lo lee de las dos vías documentadas:

| Vía | Contrato (corpus) | Cuándo se lee |
| --- | --- | --- |
| Webhook `messages` | `message.reply_to.story = {"id": STORY-ID, "url": CDN-URL}` (`instagram-messaging/webhooks.md`, «Included when a customer replies to a story»; desde el 2025-12-12 también trae `link_sticker_url`, que Qualify no guarda) | Siempre: el dato ya viene en la entrega, no cuesta una llamada |
| Sincronización (`GET /{conversation-id}/messages`) | campo `story` del nodo Message (`graph-api/reference/message.md`: «Only mentions and replies are supported»); Qualify toma `story.reply_to = {"link", "id"}` e ignora `story.mention` | Solo con `story_reply_context` encendida: añadir `story` cambia la petición a Meta |

**Cómo lo aplica Qualify:**

| Regla | Dónde |
| --- | --- |
| La historia se guarda en el mensaje (`messages.story_reply_id`, `story_reply_url`); solo en mensajes **entrantes** (CHECK), y la URL nunca sin el id. La URL es del CDN de Meta y caduca (una historia dura 24 h): se muestra mientras funcione | migración 0075 |
| Un `reply_to` con `mid` (respuesta a otro mensaje), una mención de historia o un mensaje propio (eco) **no** es una respuesta a historia | `conversations/webhook.py`, `instagram_source.py` |
| Si la sincronización guardó el mensaje sin la historia y luego llega con ella (webhook, o sincronización con la capacidad encendida), se completa; nunca se sobrescribe una historia ya guardada ni se toca nada más del mensaje | `conversations/repository.py` (`insert_message`) |
| En el hilo de Conversaciones, la burbuja dice «Respondió a tu historia» (con enlace mientras la URL funcione) | `Qualify/conversations_page.py` |
| Con la capacidad encendida, el análisis automático de intención clasifica también el texto de las respuestas a historias con el mismo `IntentSignal`, y las comerciales de las **últimas 24 h** se abren en «Consultas desde comentarios» con su borrador | `intent/repository.py`, `followups/origins.py`, `followups/workspace.py` |
| Solo un DM que Meta marcó como respuesta a una historia es una consulta de este origen; cualquier otro DM ya es una conversación y se responde en ella | `followups/service.py` |
| Sale siempre como **DM normal** en el mismo hilo, dentro de la ventana de 24 h (verificado en QUA-226); nunca respuesta privada ni aviso público (no hay comentario) | `followups/service.py`, CHECKs de 0071 |
| La tarjeta dice «Respondió a tu historia por mensaje directo» con el enlace a la historia | `Qualify/followups_vm.py` |

**R3, paso a paso (cuando se haga):**

1. Publicar una historia en la cuenta conectada. Un tester con rol en la app responde a la historia por mensaje directo con una pregunta comercial (p. ej. «¿Cuánto cuesta?»).
2. Encender `QUALIFY_STORY_REPLY_CONTEXT=on` **en la app y en el conversations-worker** y correr `just conversations-tick --tenant <uuid> --sync` (o esperar al webhook si la Página está suscrita, QUA-129).
3. Comprobar en la base que el mensaje tiene `story_reply_id` (y `story_reply_url`), y en Conversaciones que la burbuja dice «Respondió a tu historia». Si llegó por la sincronización, confirmar que la respuesta de Meta trae `story.reply_to` (y no otra forma): es la parte del contrato que la documentación no muestra completa.
4. Buscar comentarios nuevos en Interacciones y esperar el análisis automático: la consulta aparece en «Consultas desde comentarios» con «Respondió a tu historia», borrador y ruta «Mensaje directo». Aprobarla y comprobar que sale en el mismo hilo.
5. Pegar aquí la fecha, la vía por la que llegó (webhook o sincronización) y la forma observada (sin tokens ni textos de usuario). Con eso, `story_reply_context` pasa a **verificada** en `followups/capabilities.py`.

### Resultados de las pruebas reales (2026-10-22)

Prueba en local contra la API real de Meta, con la conexión de `@rauldevgames` (Facebook Login for Business, acceso Standard, app «QualifyMkt Connector»), reconectada con `instagram_manage_messages` y `pages_messaging` (Meta concedió además `pages_manage_metadata`), y un tester con rol en la app. Las tres capacidades encendidas solo en esa ejecución; los mensajes se aprobaron con `HumanApproval` y los envió el `conversations-worker` (`--once`). Sin tokens ni textos de usuario.

| Prueba | Resultado | Evidencia |
| --- | --- | --- |
| Lectura de DMs con el nuevo token | ✅ | Una pasada de sincronización trajo 34 mensajes. El perfil del contacto (`GET /{igsid}?fields=name,username,profile_pic`) responde `403`, código 230 (Meta pide el consentimiento de esa persona): los hilos se ven sin foto, no bloquea nada |
| `from.id` del comentario = IGSID del DM | ✅ | Los comentarios del tester llegan con el mismo id que su hilo de DM (`936018996002128`) |
| **R1** — respuesta privada a un comentario | ✅ | `POST /{page-id}/messages` con `recipient.comment_id`: fila `private_reply` `sent` con `message_id`; el `recipient_id` de Meta es el IGSID del hilo (sin `recipient_mismatch`) |
| **R4** — aviso público tras el DM confirmado | ✅ con arreglo | 1.ª prueba: el aviso **se publicó** pero quedó `failed`/`notice_ambiguous`: `POST /{comment-id}/replies` tardó más que los 5 s por defecto de httpx y el cliente cortó. Arreglo: `REPLY_TIMEOUT` de 60 s en `replies/client.py` (afecta también a las respuestas públicas a comentarios). 2.ª prueba con el arreglo: el DM `sent` y en la misma pasada el aviso `posted` con id de Meta; una segunda pasada no publicó otro (un solo aviso bajo el comentario) |
| **R3** — llegada de la respuesta a una historia | ✅ | La sincronización trae `story.reply_to` con el id y la URL de la historia; quedan en `messages.story_reply_id`/`story_reply_url`, y la consulta se abre con la ruta «Mensaje directo» |
| **R3** — responder por DM | ✅ con configuración | Sin la Página suscrita a la app, Meta rechaza **cualquier DM normal** con `(#10) Este mensaje se envió fuera del período permitido` (subcódigo 2534022), aunque la persona haya escrito minutos antes: `GET /{page-id}/subscribed_apps` estaba vacío. Tras `POST /{page-id}/subscribed_apps?subscribed_fields=messages`, un mensaje nuevo del tester abrió la ventana y el DM salió (`sent`). La suscripción no vale para los mensajes anteriores a ella. La respuesta privada no depende de esto |

**Qué necesita producción (para activar Fase C):**

1. **Permisos.** En `.env.prod`, `QUALIFY_META_SCOPES` debe incluir `instagram_manage_messages`, `pages_messaging` y `pages_manage_metadata` (este último para suscribir la Página). Si producción usa `QUALIFY_META_CONFIG_ID`, la configuración de Facebook Login for Business del panel de Meta debe pedir los mismos permisos.
2. **Reconectar** cada cuenta de Instagram en `/connections` para que su token los lleve (comprobar en la tarjeta que «Bandeja de mensajes directos» queda disponible).
3. **Suscribir la Página** de cada cuenta a la app: `POST /{page-id}/subscribed_apps?subscribed_fields=messages`. Desde m-24789549 lo hace Qualify al **reconectar** (paso 2); si falla, la cuenta queda conectada y el fallo queda en `connection_events` (`page_subscribe_failed` + código de Meta). Sin esto, ningún DM normal sale (24 h cerrada para la app) y no llegan webhooks de mensajes. Solo los campos de **Página** van por este endpoint: los de Instagram (`messages`, `comments`, `mentions`) se eligen en el panel de la app.
4. En Instagram, cada cuenta con **«Permitir acceso a los mensajes»** activado.
5. **Encender las capacidades** en `.env.prod` (lo leen la app y el `conversations-worker`): `QUALIFY_COMMENT_PRIVATE_REPLY=on`, `QUALIFY_PUBLIC_NOTICE=on`, `QUALIFY_STORY_REPLY_CONTEXT=on`, y reiniciar los contenedores.
6. **Desplegar el arreglo del tiempo de espera** de `replies/client.py` antes de encender `public_notice`.
7. **Acceso Standard:** todo lo anterior funciona solo con personas con rol en la app. Para clientes reales hace falta Advanced Access y App Review de esos permisos (QUA-140, QUA-142).


## 8. Preguntas iniciales, botones y respuestas rápidas (m-24789472, PR 2)

> §8, §9 y §10 son el detalle de cada fase de m-24789472. La tabla consolidada de las cuatro
> herramientas (criterio R3 del ticket), los requisitos comunes, el menú persistente y la
> lista única de pruebas reales pendientes están en **§11**.

Cuando la persona **toca** una opción en vez de escribir, Qualify guarda el mensaje como cualquier otro (el texto es el título de la opción) y además **qué tocó**: `messages.choice_kind` y `messages.choice_payload` (migración 0082). Nada de esto responde solo: la respuesta sigue siendo un borrador que una persona aprueba.

| Vía | Contrato (corpus, **no verificado en vivo**) | Qué hace Qualify |
| --- | --- | --- |
| Respuesta rápida | `message` normal con `text` = título y `quick_reply.payload` (`instagram-messaging/features/quick-replies.md`) | Mensaje entrante + `choice_kind = 'quick_reply'` y el payload |
| Pregunta inicial (Ice Breaker), botón de plantilla, menú persistente | ítem `postback {mid, title, payload}` en `entry[].messaging[]` (`webhooks.md` «Messaging postbacks»). `mid` viene desde Graph v11.0 (`webhooks.md`, tabla de campos; changelog v11.0); el ejemplo de `features/ice-breakers.md` aún lo omite | Mensaje entrante con texto = `title`; el tipo sale del prefijo del payload: `QF_` pregunta inicial, `QFB_` botón, `QFM_` menú, otro = botón (`conversations/choices.py`). Sin `mid`: id sintético `qf-postback:` + sha256(remitente, timestamp, payload, título) |
| Sincronización (`GET /{conversation-id}/messages`) | El nodo Message (`graph-api/reference/message.md`) **no tiene** campo de postback ni de respuesta rápida. El changelog v11.0 da a entender que el postback sí figura en el historial con el mismo `mid` (por eso Meta añadió `mid` al webhook) | Nunca trae tipo ni payload. Si la sincronización guardó el `mid` antes, el webhook (o su reproducción) completa `choice_kind`/`choice_payload` en la **misma** fila; nunca se duplica ni se reemplaza un par ya guardado |

**Qué debe hacer el fundador antes de una prueba real (R5):**

1. En el panel de la app, webhooks de **Instagram**: suscribir el campo **`messaging_postbacks`** (`features/ice-breakers.md`: «subscribe your app to the `messaging_postbacks` webhook under the Instagram topic»). Sin esto, las preguntas iniciales y los botones no llegan; las respuestas rápidas sí (van por `messages`). No es un campo de Página: `connections/page_subscription.py` no lo cambia.
2. Configurar preguntas iniciales con payload `QF_*` (PR 3 lo hará desde Qualify; mientras tanto, a mano por la API de Ice Breakers).
3. Un tester toca una pregunta inicial desde el teléfono (no existen en escritorio): comprobar que llega con `mid`, que el hilo muestra el mensaje y en la base `choice_kind = 'ice_breaker'`. Pegar aquí la fecha y la forma observada (sin tokens ni textos de usuario).
4. Comprobar en la sincronización si el postback figura en `GET /{conversation-id}/messages` y con qué `message`: es la parte que el corpus no muestra.

**Reproducir los postbacks que ya llegaron** (quedaron `unsupported` / `not_a_message` en `meta_webhook_events`, se guardan 29 días): `just webhook-requeue-postbacks [--account <ig_id>]` cuenta cuáles volverían (no cambia nada); con `--execute` los devuelve a la cola y el `webhook-worker` los convierte en mensajes, uno por `mid`. Repetirlo no duplica nada.

## 9. Preguntas iniciales (Ice Breakers) por cuenta (m-24789472, PR 3)

Cada cuenta de Instagram tiene sus preguntas iniciales en `conversation_ice_breakers` (migración 0083): el borrador que la persona edita (las cuatro del ticket por defecto, payloads `QF_PRODUCTO`, `QF_PRECIO`, `QF_UBICACION_HORARIO`, `QF_CATALOGO`), lo último publicado, quién lo publicó y la última lectura de vuelta. Código: `conversations/ice_breakers.py` (servicio) y `conversations/ice_breakers_client.py` (Graph). Publicar y quitar son acciones de una persona y están detrás de la capacidad `ice_breakers` (`QUALIFY_ICE_BREAKERS=on`, **por verificar**); editar el borrador funciona sin ella.

| Operación | Contrato (corpus, **no verificado en vivo**) | Qué hace Qualify |
| --- | --- | --- |
| Publicar | `POST /{page}/messenger_profile?platform=instagram`, cuerpo `{"platform": "instagram", "ice_breakers": [{"call_to_actions": [{question, payload}], "locale": "default"}]}`, token de Página (`features/ice-breakers.md`); máximo 4; `locale: "default"` obligatorio | Un solo bloque `default`; 60 s de espera; después lee de vuelta |
| Leer de vuelta | `GET /{page}/messenger_profile?fields=ice_breakers&platform=instagram`. **El corpus se contradice:** `ice-breakers.md` muestra `data` como lista de bloques por idioma; `page/messenger_profile.md`, como un objeto por propiedad (`[{"ice_breakers": [...]}]`) | Acepta las dos formas; guarda la lectura con `shape_version` `ig-ice-breakers-messenger-profile-0.1.0` |
| Quitar | `DELETE /{page}/messenger_profile?platform=instagram` con cuerpo `{"fields": ["ice_breakers"]}` | El borrador se conserva; lee de vuelta |
| Límite | 10 llamadas cada 10 minutos por Página (`messenger_profile.md`) | Publicar = 2 llamadas; si Meta lo frena, `rate_limited` y un mensaje para esperar |
| Largo de la pregunta | El corpus no lo dice | 80 caracteres, provisional (el de WhatsApp) |

`{page}` es el `linked_page_id` de la conexión (con un token de Página, `me` es la misma Página). Errores: solo códigos (`last_error_code`: `auth_expired`, `permission_missing`, `rate_limited`, `meta_unavailable`, `ambiguous`, `rejected`, `unexpected_response`, `connection_unavailable`, `unexpected`; `last_error_detail`: `http_<estado>_code_<código>`); la base los restringe a `[a-z0-9_]`, nunca guarda el texto de Meta. Un fallo ambiguo (la petición pudo llegar) se resuelve leyendo de vuelta.

**Prueba real pendiente (R6):** con `QUALIFY_ICE_BREAKERS=on` y un tester, publicar las cuatro desde Qualify, comprobar en el teléfono (no existen en escritorio) que aparecen, anotar aquí qué forma devolvió el `GET` y qué permiso pidió Meta (`pages_messaging` o `instagram_manage_messages`), medir el largo máximo de una pregunta, tocar una y ver que llega a Conversaciones como pregunta inicial (§8), y luego quitarlas. Sin tokens ni textos de usuario en las notas.

## 10. Respuestas rápidas y mensajes con botones (m-24789472, fase 3)

Una persona del negocio puede enviar, siempre con su aprobación y con la ventana de 24 h abierta, un mensaje con **respuestas rápidas** (opciones para tocar debajo del texto) o un **mensaje con botones** (plantilla de botones). Código: `conversations/interactive.py` (validación y forma del cuerpo), `InstagramDirectSender.build_payload(..., quick_replies=)` y `build_button_template_payload`, `ConversationService.reply_text(..., quick_replies=)` y `reply_buttons`. Las plantillas de la biblioteca pueden llevar botones (`conversation_reply_templates.buttons`, migración 0084).

| Qué | Contrato (corpus, **no verificado en vivo**) | Qué hace Qualify |
| --- | --- | --- |
| Respuestas rápidas | `message.quick_replies: [{content_type: "text", title, payload}]` junto a `message.text` (`features/quick-replies.md`); máximo 13, título de hasta 20 caracteres («before being truncated»); `{content_type: "user_phone_number"}` sin título; solo en el teléfono, desaparecen al tocar una | Rechaza 14 o más, títulos de 21 o más, repetidos o vacíos; payload por defecto `QR_<título>`; `user_email` no figura en el corpus de Instagram y no se ofrece. En una respuesta larga que se parte en varios mensajes, van **solo en el último** |
| Mensaje con botones | `message.attachment = {type: "template", payload: {template_type: "button", text (≤ 640), buttons (1–3)}}`; botón `postback {title, payload}` o `web_url {url, title}` (`button-template.md`); no existe en la versión web | Nunca se parte: más de 640 caracteres se rechaza. Payload `QFB_…` (el toque llega como botón, §8); enlaces solo `https://`; título de botón de hasta 20 caracteres |
| Eco del envío | El eco de una plantilla no trae `text` (forma tomada del cuerpo enviado) | El webhook toma el texto de `attachments[0].payload.text` y guarda `media_type = 'interactive'` |
| Plantilla genérica (carrusel, ≤ 10 elementos) | `generic-template.md` | **Fuera de alcance**: necesita una imagen por elemento y ninguna pantalla la pide todavía |

Las dos están detrás de capacidades **por verificar** y apagadas por defecto: `quick_replies` (`QUALIFY_QUICK_REPLIES=on`) y `structured_templates` (`QUALIFY_STRUCTURED_TEMPLATES=on`). Con la capacidad apagada, el servicio rechaza el envío con «no disponible todavía» antes de escribir nada, y el `conversations-worker` vuelve a mirarla antes de llamar a Meta: una fila ya en cola queda `failed` con `quick_replies_disabled` / `structured_templates_disabled`.

**Pruebas reales pendientes:**

- **R7 (respuestas rápidas):** con `QUALIFY_QUICK_REPLIES=on` y un tester, enviar un mensaje con tres respuestas rápidas y una de teléfono; comprobar en el teléfono que aparecen, que un título de 20 caracteres no se corta, y que al tocar una llega a Conversaciones como «Respuesta rápida: …» con su payload `QR_…` (§8). Anotar aquí la respuesta de `POST /messages`.
- **R8 (mensaje con botones):** con `QUALIFY_STRUCTURED_TEMPLATES=on` (y `messaging_postbacks` suscrito, §8), enviar un texto con un botón de enlace y dos `postback`; comprobar que se ven en el teléfono, que el enlace abre, que un toque llega como «Botón: …» con su `QFB_…`, y qué forma trae el eco (y la sincronización) del mensaje enviado. Sin tokens ni textos de usuario en las notas.

## 11. m-24789472 — las cuatro herramientas (criterio R3)

**Estado: 2026-10-23.** Todo lo construido está en la rama `feat/m-24789472-ice-breakers-quick-replies` (la biblioteca de plantillas de texto, PR 1, ya está en `main`). **Nada de m-24789472 se ha probado todavía contra Instagram en vivo**: lo único verificado que usa esta sección es lo que ya se verificó antes (el DM de texto normal, QUA-226, §2 fila 10; la suscripción de la Página, §7 R3). El resto es el contrato del corpus, y cada fila lo dice.

Rutas del corpus: `IGM/` = `reference/meta-instagram-platform/documentation/business-messaging/instagram-messaging/`; `GAPI/` = `reference/meta-instagram-platform/docs/graph-api/`.

### 11.1 La tabla

| | Plantillas de mensajes (texto / con botones) | Preguntas iniciales (Ice Breakers) | Respuestas rápidas (Quick Replies) | Menú persistente |
| --- | --- | --- | --- | --- |
| **Para qué sirve** | Que el **negocio** responda más rápido con textos, o mensajes con botones, ya preparados | Que la **persona** empiece el chat tocando una pregunta | Que la **persona** conteste tocando una opción bajo un mensaje del negocio | Accesos fijos (horario, catálogo, web…) siempre visibles en el chat |
| **Quién la usa** | La persona del negocio, en el redactor de Conversaciones | Quien abre el chat con la cuenta | Quien recibe el mensaje del negocio | Quien está en el chat |
| **Qué permite la API** | **Texto:** no hay API de respuestas guardadas: `GET`/`POST /{page-id}/saved_message_responses` se retiraron el 2019-04-30 (`GAPI/changelog/4-30-2019-endpoint-deprecations.md:245,269`), así que la biblioteca vive en Qualify. **Con botones:** *button template*, texto ≤ 640 caracteres UTF-8 y 1–3 botones `postback` o `web_url` (`IGM/button-template.md`, «Properties»); el corpus no da largo para el título del botón. **Genérica:** ≤ 10 elementos, título y subtítulo ≤ 80, ≤ 3 botones por elemento (`IGM/generic-template.md`). **Producto:** solo con productos de un catálogo de Meta y el token de la Página dueña de ese catálogo (`IGM/features/product-template.md`) | `POST`/`GET`/`DELETE /{page}/messenger_profile?platform=instagram`, token de Página; **máximo 4** preguntas por idioma; bloque `locale: "default"` obligatorio (`IGM/features/ice-breakers.md`). 10 llamadas cada 10 min por Página, compartidas con todo `messenger_profile` (`GAPI/reference/page/messenger_profile.md:135`). **Largo de la pregunta: no documentado** | **Máximo 13** por mensaje, título de hasta 20 caracteres «before being truncated», solo texto; `content_type: "user_phone_number"` precarga el teléfono del perfil y no se muestra si el perfil no lo tiene (`IGM/features/quick-replies.md`). El corpus de Instagram **no** documenta `user_email` | `messenger_profile` con la propiedad `persistent_menu`: botones `web_url` y `postback`, un bloque por idioma con `default`; no admite `composer_input_disabled` ni `webview_height_ratio`; Meta **recomienda** ≤ 5 elementos (buena práctica, no un límite de la API) (`IGM/features/persistent-menu.md`) |
| **Condiciones de Meta** | Todo mensaje del negocio requiere la ventana de 24 h abierta (`IGM/overview.md`, «How it works»); Instagram no tiene plantillas aprobadas como WhatsApp para escribir fuera de ella. Botones y genérica: no existen en la versión web | Solo en el teléfono: «not available on desktop» (`ice-breakers.md`, «Limitations»). **Cuándo** aparecen (solo en un chat nuevo o también con historial): el corpus no lo dice | Solo en el teléfono («not available on desktop»); desaparecen al tocar una; el título tocado se publica en el chat como mensaje de la persona (`quick-replies.md`) | App de Instagram v226 o superior en iOS/Android; **no se actualiza en tiempo real**: las conversaciones abiertas no ven el menú nuevo hasta refrescar la bandeja; **no se personaliza por persona** (`persistent-menu.md`, «Limitations», «Requirements») |
| **Evento que llega** | La respuesta de la persona: `messages` (texto) o, si toca un botón `postback`, `messaging_postbacks` (`button-template.md`, «Postback button»). Un botón `web_url` no avisa | Ítem `postback {title, payload}` bajo el campo `messaging_postbacks` del tema Instagram (`ice-breakers.md`, «Webhook event»); con `mid` desde Graph v11.0 (`IGM/webhooks.md:40`). **El corpus se contradice:** `webhooks.md:39` también pone «Icebreaker option» entre lo que dispara `messages` | `messages` con `text` = título y `quick_reply.payload` (`quick-replies.md`). El ejemplo de la respuesta de teléfono trae `"object": "page"`, no `instagram`: anotarlo en la prueba | `postback` al tocar un elemento, y «the standard messaging window opens»: 24 h para responder (`persistent-menu.md`, «How it works») |
| **Qué construyó Qualify** | **Texto** (PR 1, en `main`): `conversations/templates.py` + migración 0079 — biblioteca por cuenta, 4 por defecto sembradas una sola vez, variables `{nombre}`/`{marca}`, título ≤ 60, cuerpo ≤ 1000 (un DM), ≤ 50 por cuenta; sale por `ConversationService.reply_text` con `HumanApproval` (`service.py:346`). **Con botones** (fase 3): `conversation_reply_templates.buttons` (0084), `conversations/interactive.py` (límites en `:46-52`; título de botón ≤ 20, **elegido por Qualify**, provisional), `reply_buttons` (`service.py:389`), payload `QFB_…`. **Genérica y producto:** no | `conversations/ice_breakers.py` (servicio: borrador, publicado, lectura de vuelta), `conversations/ice_breakers_client.py` (Graph), migración 0083, panel «Preguntas iniciales» en la cabecera de Conversaciones (`Qualify/ice_breakers_panel.py`); payloads `QF_PRODUCTO`, `QF_PRECIO`, `QF_UBICACION_HORARIO`, `QF_CATALOGO` (`choices.py:77-82`); largo **80 caracteres, provisional** (`ice_breakers.py:94`, tomado de WhatsApp). Capacidad `ice_breakers`. Recepción: `webhook.parse_postback` (`webhook.py:219`) → mensaje entrante con `choice_kind = 'ice_breaker'` (0082) | `interactive.py` (≤ 13, título ≤ 20, sin repetidos; `user_phone_number`; payload por defecto `QR_<título>`), `InstagramDirectSender.build_payload(..., quick_replies=)`, `reply_text(..., quick_replies=)`, redactor de Conversaciones; en una respuesta partida van solo en el último mensaje. Capacidad `quick_replies`. Recepción: `webhook._quick_reply_payload` (`webhook.py:203`) → `choice_kind = 'quick_reply'` | **Solo la recepción:** un payload `QFM_…` llega como `choice_kind = 'menu'` y el hilo lo etiqueta (`choices.py:54`, `choices.postback_kind`). No hay configuración, ni cliente, ni pantalla, ni capacidad (§11.5) |
| **Estado** | Texto: **Verificado** (la biblioteca no llama a Meta; la vía de envío es el DM de texto verificado en QUA-226). Con botones: **Por verificar** (R8). Genérica: **No implementado en Qualify** (fuera de alcance, §10). Producto: **No implementado en Qualify**, y el catálogo propio de Qualify no sirve: hace falta un catálogo de Meta | Publicar, leer y quitar: **Por verificar** (R6). Toque: **Por verificar** (R5) y **Configuración pendiente** mientras `messaging_postbacks` no esté marcado en el panel | **Por verificar** (R7). No necesita suscripción nueva: llega por `messages` | Configurarlo: **No implementado en Qualify** (opcional en el ticket). Recepción: **Por verificar** |

**Lo que Qualify hace con cualquier toque:** lo guarda como un mensaje entrante con su texto (el título) y además **qué tocó** (`messages.choice_kind`/`choice_payload`); el hilo lo muestra con su origen («Pregunta inicial: Precio», «Respuesta rápida: Sí», «Botón: Ver catálogo»; `choices.choice_label`), y el payload orienta el borrador de `suggest.py` (`choices.choice_context`). **Nada responde solo:** la respuesta sigue siendo un borrador que una persona aprueba. Un toque cuenta como mensaje de la persona y mueve `last_inbound_at`, la base de la ventana de 24 h en Qualify; que Meta abra la ventana con un toque solo está documentado para el menú persistente, y para preguntas iniciales y botones es una de las pruebas (R5, R8).

### 11.2 Qué se promete y qué no

**Se promete (entrega base B1–B6, sin depender de Meta):** biblioteca de plantillas de texto por cuenta usable desde el redactor; las 4 preguntas iniciales por cuenta (por defecto, edición, validación, persistencia) con su cliente de `messenger_profile` probado contra el contrato; respuestas rápidas y mensajes con botones detrás de sus capacidades; los toques crean o completan el hilo sin duplicar; nada sale sin aprobación humana; aislamiento por tenant.

**No se promete** (lista del ticket):

- más de 4 preguntas iniciales;
- preguntas o menús distintos por persona;
- que se vean en escritorio;
- escribir fuera de la ventana de 24 h;
- importar las «respuestas guardadas» de la app de Instagram (no hay API desde 2019);
- usar el catálogo de Qualify como plantilla de producto de Meta.

Tampoco entra (fuera de alcance del ticket): respuestas automáticas a cualquier opción, plantillas por sector o generadas con IA, otros canales.

### 11.3 Requisitos comunes

| Requisito | Para qué | Estado |
| --- | --- | --- |
| Token de Página con `instagram_manage_messages` (fork Facebook Login, ADR 25) | Enviar respuestas rápidas y botones, y leer DMs. Para recibir webhooks, además `instagram_basic` y `pages_manage_metadata`, y la app publicada (`IGM/webhooks.md`, «Requirements») | **Verificado** con acceso Standard (§2 fila 1). Qué permiso exige `messenger_profile` para las preguntas iniciales (`pages_messaging` o `instagram_manage_messages`) **no lo dice el corpus**: se anota en R6 |
| Campos de webhook `messages` **y** `messaging_postbacks` | `messages` trae texto y respuestas rápidas; `messaging_postbacks`, los toques en preguntas iniciales, botones y menú | `messages`: suscrito. **`messaging_postbacks` se marca en el panel de la app → Webhooks → Instagram** (`ice-breakers.md`: «subscribe your app to the `messaging_postbacks` webhook under the Instagram topic»). **No es un campo de Página:** `connections/page_subscription.py` solo envía `subscribed_fields=messages` y no lo cambia. **Configuración pendiente** hasta confirmarlo marcado (el 2026-10-16 el panel tenía `messages` y `mentions`, §2 fila 11b) |
| Página suscrita a la app (`POST /{page-id}/subscribed_apps`, QUA-129) | Sin ella Meta rechaza todo DM normal con `(#10)` subcódigo 2534022 y no llegan webhooks de mensajes (§7, R3 del 2026-10-22) | **Construido** (m-24789549): Qualify lo hace al conectar o reconectar; cada intento queda en `connection_events` |
| Acceso Standard = solo personas con rol en la app (QUA-140) | Todas las pruebas de abajo se hacen con un tester con rol | Para clientes reales: Advanced Access de `instagram_manage_messages` (QUA-140, QUA-142) |
| Toques solo por webhook | La sincronización (`GET /{conversation-id}/messages`) no trae tipo ni payload (§8): el `webhook-worker` tiene que estar recibiendo los webhooks de la app (el callback del panel) | En local no hay webhook (§2 fila 11b): las pruebas de toques se hacen donde llega el callback |

### 11.4 Capacidades y su estado

Un solo registro para todo el despliegue (`packages/api/src/qualify_api/followups/capabilities.py:113-135`). Se enciende con la variable exactamente en `on`; apagadas por defecto. Cambiar el estado es un cambio de código con su evidencia en este documento, nunca un ajuste.

| Capacidad | Variable | Estado | Qué pasa apagada |
| --- | --- | --- | --- |
| `ice_breakers`: publicar y quitar las preguntas iniciales de una cuenta | `QUALIFY_ICE_BREAKERS` | **Por verificar** (R6), apagada | Editar y guardar el borrador funciona; publicar y quitar responden «no disponible todavía» (`IceBreakerUnavailable`) sin llamar a Meta |
| `quick_replies`: respuestas rápidas bajo un DM | `QUALIFY_QUICK_REPLIES` | **Por verificar** (R7), apagada | El servicio rechaza el envío antes de escribir nada; una fila ya en cola queda `failed` con `quick_replies_disabled` (`sender.py:73,215`) |
| `structured_templates`: DM como plantilla de botones | `QUALIFY_STRUCTURED_TEMPLATES` | **Por verificar** (R8), apagada | Igual, con `structured_templates_disabled` (`sender.py:74,218`) |

La biblioteca de plantillas de **texto** no tiene capacidad: no llama a Meta y sale como un DM normal, verificado. Recibir toques tampoco: el handler siempre está activo y solo guarda.

### 11.5 Menú persistente: documentado, no construido

**Por qué no se construyó:**

- El ticket lo deja **opcional** («Si el resto está entregado, configurar hasta 3-5 accesos…») y el resto todavía espera sus pruebas reales (§11.6).
- **No se actualiza en las conversaciones abiertas** hasta que la persona refresca la bandeja (`persistent-menu.md`, «Limitations»): un cambio desde Qualify no se vería enseguida, y la app tiene que tolerar toques de elementos que ya no existen.
- **No es por persona** (no se personaliza por PSID): es un único menú por cuenta e idioma.

**Lo que ya funciona sin construirlo:** si alguien configura el menú por otra vía (la API a mano) con payloads que empiezan por `QFM_`, el toque llega como `postback`, se guarda como mensaje entrante con `choice_kind = 'menu'` y el hilo lo etiqueta como menú (`conversations/choices.py:54`, `choices.postback_kind`). Un payload sin ese prefijo se trata como botón. Necesita `messaging_postbacks` marcado, como las preguntas iniciales.

**Qué haría falta para construirlo** (orden de trabajo, no compromiso):

1. Una tabla por cuenta con `tenant_id` + RLS, como `conversation_ice_breakers` (0083): borrador, lo publicado, quién lo publicó, la última lectura de vuelta. La revisión la escribe backend-engineer, numerada sobre la cabeza de `main`.
2. Extender el cliente de `messenger_profile` (`ice_breakers_client.py`) con `persistent_menu`: mismo endpoint y mismo token. Según `messenger_profile.md`, un `POST` solo sobrescribe las propiedades que lleva el cuerpo, así que no pisaría las preguntas iniciales; comprobarlo en vivo. Comparte con ellas el límite de 10 llamadas cada 10 min por Página.
3. Validación: `postback` con `QFM_…` y `web_url` solo `https://`; tope de 5 (el que recomienda Meta, provisional); largo del título sin documentar en el corpus de Instagram, provisional.
4. Una capacidad `persistent_menu` en el registro, `to_verify` y apagada, y un panel junto al de «Preguntas iniciales».
5. Una prueba real: publicar, ver cuánto tarda en aparecer en un chat abierto y en uno nuevo, tocar un elemento y comprobar la ventana de 24 h.

### 11.6 Pruebas reales pendientes

Numeración: R5–R8 son las de §8–§10. En el ticket, **R1** = preguntas iniciales publicadas, vistas en el teléfono y con su evento real (R5 + R6); **R2** = respuestas rápidas y botones enviados y la respuesta recibida (R7 + R8); **R3** = esta sección.

**Qué anotar en cada prueba** (aquí, junto a su casilla): fecha y hora UTC; cuenta usada; por dónde llegó (webhook o sincronización); código HTTP y código/subcódigo de Meta; la **forma** observada (claves y tipos, no valores); el estado resultante en la base (`choice_kind`, `delivery_status`, `last_error_code`). **Nunca** tokens, textos de la persona ni números de teléfono. Con una prueba en verde, el estado de la capacidad pasa a `verified` en `followups/capabilities.py` en el mismo PR que la evidencia.

**P0 — Preparación (una vez).** Estado: **pendiente**.

- [ ] Cuenta conectada `qualifymkt.co` o `@rauldevgames`, reconectada con `instagram_manage_messages`, `pages_messaging` y `pages_manage_metadata`; en `connection_events`, un `page_subscribed` reciente.
- [ ] Panel de la app → Webhooks → Instagram: `messages` **y** `messaging_postbacks` marcados.
- [ ] Un tester con rol en la app, con la app de Instagram en el **teléfono** (iOS o Android; nada de esto existe en escritorio ni en la web).
- [ ] App, `conversations-worker` y `webhook-worker` corriendo donde llega el callback, con `QUALIFY_ICE_BREAKERS=on`, `QUALIFY_QUICK_REPLIES=on` y `QUALIFY_STRUCTURED_TEMPLATES=on` **solo para la prueba**. En local, siempre `--tenant <uuid>`.

**R6 — Publicar las preguntas iniciales** (ticket R1). Estado: **pendiente**.

- [ ] Conversaciones → elegir la cuenta → «Preguntas iniciales» → publicar las cuatro por defecto. Anotar: estado final (publicado, o error con su código), qué forma devolvió la lectura de vuelta (`GET`: lista de bloques por idioma u objeto por propiedad, §9) y si Meta pidió algún permiso.
- [ ] En el teléfono del tester: abrir un chat **nuevo** con la cuenta (sin historial) y otro **con historial**. Anotar en cuál aparecen y si hizo falta refrescar la bandeja. Confirmar que no aparecen en escritorio.
- [ ] Largo: editar una pregunta con 40, 60 y 80 caracteres, publicarla y anotar si se ve completa o cortada. Probar más de 80 exige una llamada directa a la API fuera de Qualify (el validador lo rechaza); si se hace, anotar el resultado y ajustar `MAX_QUESTION_CHARS`.
- [ ] Quitar las preguntas desde el panel: la lectura de vuelta queda vacía y desaparecen del teléfono (anotar cuánto tardan).

**R5 — Tocar una pregunta inicial** (ticket R1). Estado: **pendiente**.

- [ ] El tester toca «¿Quieres consultar un precio?». Anotar: si llegó el webhook, bajo qué campo (`messaging_postbacks` o `messages`: el corpus se contradice), si trae `mid`, y que el hilo muestra «Pregunta inicial: Precio» con `choice_kind = 'ice_breaker'` y `choice_payload = 'QF_PRECIO'`.
- [ ] Ventana de 24 h: con un tester que **no** escribió en las últimas 24 h, que solo toque la pregunta; aprobar una respuesta y correr `just conversations-tick --tenant <uuid>`. `sent` = el toque abre la ventana; `(#10)` subcódigo 2534022 = no la abre (limitación de Meta, y Qualify tendría que dejar de contar el toque para la ventana).
- [ ] Sincronización: `just conversations-tick --tenant <uuid> --sync`; anotar si el toque aparece en `GET /{conversation-id}/messages`, con qué `mid` y qué texto, y comprobar que el mensaje no se duplica.
- [ ] Si había postbacks guardados de antes: `just webhook-requeue-postbacks --account <ig_id>` (solo cuenta, no cambia nada) y luego con `--execute`; repetirlo no debe duplicar.

**R7 — Respuestas rápidas** (ticket R2). Estado: **pendiente**.

- [ ] Desde el redactor, aprobar un mensaje con tres respuestas rápidas (una con un título de exactamente 20 caracteres) y una de teléfono; correr el tick. Anotar la respuesta de `POST /messages` (HTTP, `message_id`).
- [ ] En el teléfono: aparecen las cuatro, el título de 20 no se corta, la de teléfono aparece solo si el perfil del tester tiene uno; no se ven en escritorio.
- [ ] El tester toca una de texto: llega por `messages` con `quick_reply.payload` = `QR_…`, el hilo dice «Respuesta rápida: …» y las opciones desaparecen. Tocar la de teléfono: anotar el `object` de la entrega (`instagram`, o `page` como el ejemplo del corpus) y la forma, **sin** el número.
- [ ] Anotar la forma del eco del mensaje enviado (webhook con `is_echo`) y la de la sincronización.

**R8 — Mensaje con botones** (ticket R2). Estado: **pendiente**.

- [ ] Aprobar un mensaje con un botón de enlace (`https://`) y dos `postback` (desde una plantilla con botones de la biblioteca o desde el redactor); correr el tick. Anotar la respuesta de `POST /messages`.
- [ ] En el teléfono: se ven los tres botones (no en la web) y el enlace abre en el navegador de la app.
- [ ] El tester toca un `postback`: llega como `postback` (anotar el campo y si trae `mid`), el hilo dice «Botón: …» con `choice_kind = 'button'` y el `QFB_…`. Repetir con un botón la prueba de la ventana de 24 h de R5.
- [ ] Anotar la forma del eco (Qualify toma el texto de `attachments[0].payload.text`, §10) y si la sincronización lo trae, y cómo.

**Menú persistente (opcional, no construido).** Estado: **pendiente**.

- [ ] Solo si se decide construirlo o probarlo a mano: configurar dos elementos por la API (`postback` `QFM_HORARIO` y un `web_url`), tocar el `postback` desde el teléfono y comprobar que llega como menú; anotar cuánto tarda en aparecer en un chat abierto y en uno nuevo, y si las preguntas iniciales siguen publicadas después del `POST`.
