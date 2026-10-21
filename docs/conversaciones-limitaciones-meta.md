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
| 6 | Suscripción de la Página a los webhooks de la app (`subscribed_apps`) y campo `messages` suscrito en el panel | `webhooks.md:11,16`; `get-started.md:165` | **No existe** (`subscribed_apps` no aparece en el código: QUA-129) | — | Panel → Webhooks → Instagram → suscribir `messages`; `pages_manage_metadata` ya se pide | Pendiente |
| 7 | Forma del webhook: `object: instagram`, `entry[].messaging[]` con `sender`, `recipient`, `timestamp`, `message.mid/text/attachments/is_echo` | `webhooks.md:53-81` | Envelope mapea `messaging[]` a `field = "messages"`; handler bajo `instagram:messages` | Receptor y cola duraderos existentes (QUA-147) | — | Pendiente (ningún DM real ha llegado) |
| 8 | Lectura: `GET /{page-id}/conversations?platform=instagram` y `GET /{conversation-id}/messages?fields=…`; solo ~20 mensajes recientes con detalle | `get-started.md:133`; `instagram-api-with-instagram-login/conversations-api.md` («Note») | `MESSAGES_PAGE_LIMIT = 20`, una página por conversación; el webhook es el camino hacia delante | Poll local: `just conversations-sync --tenant …` | — | **Verificado para texto (2026-10-16, 21:44 UTC):** sonda de acceso, listado de conversaciones con participantes y `GET /{conversation-id}/messages` respondieron **200**; un DM de texto de un tester con rol se ingirió como un hilo (`counterpart` = IGSID, `external_conversation_id` = id `aWdf…`) con un mensaje `inbound` con `author_username` y `created_time`. **Pendiente:** adjuntos (media) y el envío (`POST /messages`, nunca llamado) |
| 9 | Conversaciones en «Requests» sin actividad 30 días dejan de aparecer | `conversations-api.md` («Limitations») | No modelado: un hilo ya guardado no desaparece de Qualify aunque Meta deje de listarlo | — | — | Documentado, no cubierto |
| 10 | Envío: `POST /{page-id}/messages` con `{"recipient":{"id":IGSID},"message":{"text"}}`; ≤ 1000 bytes UTF-8 | `send-message.md` («Send a basic message», «Limitations») | `build_payload` valida el límite; el servicio valida 1000 caracteres | Worker local: `just conversations-worker --tenant … --sync` | — | **Verificado (2026-10-16, 22:07 UTC):** una respuesta aprobada en `/conversations` salió por el worker (`claimed=1 sent=1`), `POST` **200** con `message_id`; `mark_sent` escribió la fila `outbound` con `delivery_status = sent` y `last_inbound_at` no se movió (B2) |
| 11 | Ventana de 24 h desde el último mensaje de la persona | `overview.md:27-28` | `WindowClosed` al redactar y `window_closed` al enviar (sender) | — | Human Agent tag (7 días) **no modelado**: otro permiso y otra App Review | Pendiente |
| 11b | «Visto» del cliente: webhook `messaging_seen` (`entry[].messaging[].read.mid` + `timestamp`) | `webhooks.md:41,211-236` | `parse_messaging_item` → `RemoteRead` → `mark_outbound_read` (toda salida ≤ timestamp pasa a `read`) | Sin webhook en local: no observable aquí | Suscribir `messaging_seen` en el panel (hoy solo `messages` y `mentions`) | Pendiente |
| 11c | Señales al cliente: `POST /{page-id}/messages` con `sender_action` = `mark_seen` / `typing_on` / `typing_off`, solo con `recipient` | `features/sender-actions.md` | `InstagramDirectSender.send_action`; `service.signal` las ignora si la ventana está cerrada; nunca pasan por el outbox | Se envían al abrir un hilo y mientras se escribe (cada ≥ 6 s) | — | Pendiente |
| 11d | Lo que Instagram **no** expone: «escribiendo…» del cliente y «entregado» | `webhooks.md` (campos: `messages`, `messaging_postbacks`, `messaging_seen`, `message_reactions`, …) | La UI no muestra typing ajeno ni «entregado»; solo «Enviando» (outbox), «Enviado» (200 de Meta) y «Visto» | — | — | No existe en la API |
| 11e | Adjuntos: entrada `attachments[].payload.url` (webhook) / `image_data.url`, `video_data.url`, `file_url` (edge); salida `message.attachment.{type,payload.url}` con URL pública — `image` png/jpeg ≤ 8 MB, `audio` aac/m4a/wav/mp4 ≤ 25 MB, `video` mp4/ogg/avi/mov/webm ≤ 25 MB, `file` pdf ≤ 25 MB; sticker `like_heart` sin payload | `webhooks.md:66-77`; `graph-api/reference/message.md:98`; `send-message.md` («Send an image», «Send a heart sticker», «Limitations») | `messages.media_url` guarda la URL CDN entrante; un adjunto saliente se sube a R2 y el sender publica la URL (`/public/media/{token}`, 15 min) **al enviar**; `document` se traduce a `file` en el cable; el corazón va como `media_type = sticker` sin objeto | `QUALIFY_PUBLIC_MEDIA_BASE_URL` apunta al túnel (FastAPI 3000) | Encuestas y ubicación **no existen** en la API de envío de Instagram | Pendiente (ni un adjunto entrante ni uno saliente observados aún) |
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
   callback que ya recibe `mentions`/`comments`. Y construir QUA-129 (`POST
   /{page-id}/subscribed_apps` al conectar), que hoy no existe.
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
4. Solo con `comments_served`: arrancar la app con `QUALIFY_STORY_COMMENTS=on`, monitorear la historia en Interacciones, sincronizar y pulsar «Analizar sentimiento» y «Analizar intención». Si el comentario aparece con su sentimiento y su intención, R1 queda confirmado y la capacidad se puede encender en producción.

Si Meta cambia de criterio, repetir estos pasos y sustituir el resultado de arriba.

**Riesgo para el día en que se encienda:** una historia caduca a las 24 h pero el monitoreo dura 14 días. La sincronización seguirá pidiendo `GET /{story-id}/comments` durante esos días; si Meta deja de servir el id al caducar, la marca de «medio borrado» (código 100, subcódigo 33) la dejará de monitorear sola, como a un Reel borrado.


## 7. Fase C — continuar en privado (m-24789646): estado por origen

Cada operación de Meta que Fase C necesita y que no está verificada va detrás de una **capacidad por origen**, apagada por defecto (`packages/api/src/qualify_api/followups/capabilities.py`). Se enciende con su variable a `on` (cualquier otro valor la deja apagada), pero una capacidad **no implementada** sigue apagada aunque la variable diga `on`: no hay código que ejecutar. Su estado se cambia en el código, con la evidencia aquí, nunca con un ajuste.

| Capacidad | Variable | Estado actual | Qué falta para activarla |
| --- | --- | --- | --- |
| `comment_private_reply` — respuesta privada a un comentario (`recipient.comment_id`: un solo mensaje, dentro de 7 días) | `QUALIFY_COMMENT_PRIVATE_REPLY` | **Por verificar** (construida en PR 2) | Prueba real R1 con un tester (abajo) |
| `story_comments` — comentarios en historias | `QUALIFY_STORY_COMMENTS` | **Limitación de Meta** (§6: «Comments cannot be made on story media») | Que Meta abra el edge; repetir `just story-probe` |
| `story_reply_context` — a qué historia responde un DM (`reply_to.story`) | `QUALIFY_STORY_REPLY_CONTEXT` | No implementado en Qualify | Código (PR 5) y prueba real R3 (necesita la suscripción de webhooks, QUA-129, o que la sincronización traiga `reply_to`) |
| `public_notice` — aviso público «Te enviamos la información por DM 💬» | `QUALIFY_PUBLIC_NOTICE` | No implementado en Qualify | Código (PR 4) y prueba en producción de la respuesta pública (QUA-128, R4) |

El DM normal a un hilo con la ventana de 24 h abierta **no** es una capacidad: QUA-226 lo verificó en producción y siempre está disponible.

**Vínculo de datos (`interaction_followups`, migración 0071).** Una fila por interacción (comentario o respuesta a historia): su intención comercial (`comment_intent_results`, si la abrió un análisis), el hilo privado del autor en Conversaciones, el envío que una persona aprobó (`conversation_outbox`) y el estado del aviso público, independiente del DM. El borrador sigue en `conversation_drafts` y la entrega en el outbox: aquí no se copian. El hilo privado se crea **solo cuando una persona aprueba un envío** (abrir una consulta no llena Conversaciones de hilos vacíos), y se puede crear antes de que la persona escriba porque el `from.id` de un comentario es el IGSID del autor (`ig-comment.md`), el mismo identificador que usan los DMs (`overview.md`: «specific to the person and the Instagram account»); R1 lo comprobará comparando el `recipient_id` que devuelve Meta con el del hilo.

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

