# Bandeja única de chats (WhatsApp + Instagram Direct, TikTok después): nota de arquitectura

`[PROPUESTA · 2026-11-13 · m-24789459 · principal-architect · sin firmar]`

> Nota de arquitectura para planear la épica «Bandeja unificada cross-canal». Parte de la
> propuesta UX aceptada (`docs/ux-chats-unificados.md`, `docs/mockups/chats-unificados.html`,
> D1–D5) y del código de `main` al 2026-11-13 (leído, no recordado). No es un ADR firmado: las
> decisiones marcadas `[PROPUESTO]` esperan al fundador. Secciones: 1 Dónde unificar ·
> 2 Descriptor de capacidades y lista · 3 Respuesta automática en Instagram · 4 Cortes ·
> 5 Riesgos y preguntas · 6 Qué no debe suponer la costura (TikTok).

**Resumen.**
- **Dónde unificar.** Se une la lectura de la bandeja y un descriptor de capacidades por canal.
  El envío no se une: las dos outboxes siguen (§1).
- **Menú automático.** Un motor neutral con un traductor por canal y un menú por negocio (§3.2).
- **Menú en Instagram.** Ya lo decidió el fundador el 2026-10-23 (m-24789557: menú fijo,
  «Hablar con alguien» siempre, ningún texto que diga que Qualify responde solo). Lo que falta:
  - escribir el ADR 48 en §6 (nunca se escribió);
  - hacer obligatoria en el esquema la entrega a persona;
  - revisar los textos de la app que chocan con la tercera condición (§3.3).
- **Lo que bloquea a clientes reales en Instagram** es el App Review de mensajes (§5).

## 1. Dónde unificar

### 1.1 Lo que hay en el disco

| Pieza | Instagram Direct (`channel='dm'`) | WhatsApp (`channel='whatsapp'`) |
|---|---|---|
| Tabla de hilos | `threads` (`inbox/models.py:98`, `ck_thread_channel`, `ck_thread_status` open/closed) | la misma |
| Lectura | costura `ConversationSource` (`conversations/contracts.py:162`) — **con forma de sondeo** (`list_conversations`, `list_messages` paginados) + webhook | sólo webhook (`whatsapp/handler.py`); `whatsapp/chats.py` con SQL fijo `t.channel = 'whatsapp'` (`chats.py:432,447,475,479`) |
| Envío | `ConversationSender` → `conversation_outbox` → `conversations/worker.py` | `build_send_payload` (`chats.py:178`) → `whatsapp_outbox` → `whatsapp/worker.py` (ritmo por destinatario, mensaje aprobado tras 24 h, purga `outbound_purge.py`) |
| Ventana 24 h | `conversations/window.py` reexporta `whatsapp/window.py` | compartida |
| Contadores | `attention/counts.py` (una consulta, cuatro números) | idem |
| Filtros | Todas / Pendientes / Leídas / Respondidas (`Qualify/conversations_vm.py:124-134`) | Abiertos / Cerrados / Sin leer / Pago por revisar (`Qualify/whatsapp_chats_vm.py:141-144`) |
| Estado propio | — | `whatsapp_thread_state` (menú automático, pausa) |
| UI | `conversations_{page,state,vm,provider}.py` (~6,3 k líneas) | `whatsapp_tab_chats.py` + `whatsapp_chats_{state,vm,provider}.py` (~8,2 k líneas) |

Hallazgo que decide la opción: **`ConversationSource` no le sirve a WhatsApp.** La Cloud API no
expone historial para leer por sondeo; WhatsApp sólo llega por webhook. Meter WhatsApp en esa
costura obliga a implementar `list_conversations`/`list_messages` vacíos: una costura que miente.
La costura correcta para unificar no es la de *ingesta* sino la de *lectura de la bandeja* (lo
que la pantalla lista y abre) y la de *capacidades* (lo que la pantalla puede ofrecer).

### 1.2 Opciones

| Opción | Qué es | Costo | Riesgo | Lo que TikTok necesitaría | ¿Se deshace? |
|---|---|---|---|---|---|
| A. Sólo UI | Un descriptor de capacidades y dos adaptadores en los VM de Reflex que alimentan una fila, un chat y un cuadro de respuesta; cada backend igual | Bajo (1 dev UI, ~3–4 PR) | La lista mezcla dos consultas paginadas en el VM (dos cursores, «cargar más» incorrecto, el doble de idas a la base); los contadores siguen con definiciones distintas; la lógica de «qué se puede» vive en la vista | Un tercer adaptador en la UI y una tercera consulta | Sí |
| B. Converger backends | WhatsApp sobre `ConversationSource/Sender`, una sola outbox y un solo worker | Alto (backend 3–4 semanas + migración de colas vivas) | Mueve la cola que hoy cobra pedidos reales de Bianki; payloads, claves de idempotencia (`wamid` vs `mid`), ritmo por destinatario y mensajes aprobados no encajan en un solo contrato; `Source` no aplica (1.1) | Implementar el mismo contrato | Difícil: la cola unificada tiene filas en producción |
| **C. Converger la lectura, no la escritura** | Un **servicio de bandeja** en backend: una consulta sobre `threads` para todos los canales + un **descriptor de capacidades** por canal; el envío sigue por canal (dos outboxes, dos workers) detrás de un despachador que elige el servicio por `threads.channel` | Medio (backend 2 PR + UI 4–5 PR) | Bajo: no toca colas ni webhooks; la consulta nueva se prueba contra las dos actuales | Registrar su descriptor, su fila en la consulta (`channel='tiktok_dm'`) y su propio servicio de envío/outbox | Sí: las pantallas viejas siguen funcionando hasta borrar |

**Recomendación `[PROPUESTO]`: C.** Da a la pantalla una sola lista ordenada y paginada y una sola
definición de «por responder», que es lo que el dueño ve; deja intacto lo que manda mensajes de
verdad. A es lo mismo con la deuda puesta en el sitio equivocado (paginación y reglas en la UI);
B es costo y riesgo sin beneficio visible.

**Primer corte con valor visible:** la **fila compartida + la lista unificada sólo de lectura**
bajo «Por responder» (cortes C1+C3 de §4): Bianki ve en una lista los clientes que esperan, en
WhatsApp e Instagram, ordenados por hora, y al tocar uno abre el chat de hoy de su canal (enlace
profundo). Ya cumple «una bandeja»; el chat y el cuadro de respuesta compartidos vienen después.

### 1.3 Lo que NO se une, y por qué

- **Las outboxes y sus workers** (`conversation_outbox`, `whatsapp_outbox`). Cada fila guarda el
  payload ya construido en el formato del canal; la idempotencia se apoya en el id de mensaje del
  canal; WhatsApp tiene ritmo por destinatario, mensaje aprobado fuera de ventana y purga propia.
  Unirlas es migrar una cola con envíos pendientes en producción a cambio de nada que el dueño vea.
- **La ingesta** (webhook de Meta para Instagram/WhatsApp, sondeo de Instagram). Identidades
  distintas: IGSID no es portable (`contracts.py:13-19`), el `wa_id` es un teléfono.
- **El estado del menú automático** (`whatsapp_thread_state`) — ver §3: si se generaliza, se
  generaliza como estado del *motor de menú*, no como columnas nuevas en `threads`.
- **La identidad del cliente entre canales.** Nada de unir «la misma persona» por WhatsApp e
  Instagram: no hay identificador común y unirlas por nombre sería inventar datos.

## 2. Descriptor de capacidades y la lista unificada

### 2.1 Forma

Dos partes, porque una es del canal y otra del chat:

- **Estática, del canal** — `ChannelCapabilities` (dataclass congelada, sin base de datos) en un
  módulo nuevo `packages/api/src/qualify_api/inbox/channels.py`, registrada por canal:
  `channel`, `attachments` (conjunto de tipos: Instagram `REPLY_MEDIA_TYPES` de
  `contracts.py:208`; WhatsApp imagen/video/documento/audio), `max_buttons` (y si son botones
  bajo el mensaje o lista), `stickers` (`native` WhatsApp · `heart_only` Instagram), `voice_note`,
  `saved_messages`, `window` (`hours=24`, `after_window = approved_template | none`),
  `menu_handoff`, `payments`, `suggest_reply`, `close_reopen`, `read_receipts`. El VM traduce
  esto a los `can_*` que pide la UX (`ux-chats-unificados.md` §5).
- **Dinámica, del chat** — viene en cada fila de la consulta: `window_closes_at`,
  `automation` (`menu` / `owner` / `none`), `payment_status`, `status`, `pending`.

Una prueba une el descriptor con la realidad: las capacidades declaradas deben coincidir con lo
que el sender/servicio del canal sabe construir (p. ej. `attachments` de Instagram ==
`REPLY_MEDIA_TYPES`), para que el descriptor no derive en una mentira de UI. Sugerir respuesta en
WhatsApp se declara `False` hasta que exista (§4 C8), y además pasa por una bandera por negocio
porque cuesta.

### 2.2 La consulta de la lista

**Una consulta**, no proveedores por canal mezclados en el VM:

- `SELECT … FROM threads t WHERE t.channel = ANY(:channels)` dentro de `tenant_session` (RLS por
  `tenant_id`); `:channels` sale de una lista blanca del registro, nunca del texto de la URL.
- Último mensaje con `LEFT JOIN LATERAL` (como `chats.py:420-431`); lo que es sólo de WhatsApp
  (`whatsapp_thread_state`, estado del pago, `whatsapp_outbox` para la vista previa) con
  `LEFT JOIN` que da `NULL` en Instagram. Sin N+1: una ida a la base por página.
- Orden y página por cursor `(last_message_at DESC NULLS LAST, id DESC)`, sobre el índice que ya
  existe `ix_thread_inbox_order (tenant_id, last_message_at)`. Un cursor compuesto (instante + id),
  no `before` solo como hoy (`chats.py:351`), para no perder hilos con el mismo instante.
- Las acciones sobre un hilo (`enviar`, `cerrar`, `asignar`) reciben sólo `thread_id`; el
  despachador lee `channel` de la fila **bajo RLS** y llama al servicio del canal. El canal nunca
  viene del cliente.
- Costo: dos subconsultas correlacionadas por fila (pendiente y nombre) × 50 filas. Con el volumen
  de hoy (cientos de hilos por negocio) es trivial. Si el p95 de la página pasa de 300 ms, la
  salida es desnormalizar `last_outbound_at` en `threads` (migración pequeña), no otro almacén.

### 2.3 Qué significa «por responder» (una sola definición)

Hoy hay tres definiciones distintas:

| Lugar | Definición |
|---|---|
| `counts.py` Instagram | último entrante sin leer (`last_read_at`) y sin saliente posterior |
| `counts.py` / lista WhatsApp «Sin leer» | algún entrante posterior al último saliente, **sin mirar `status`** |
| Filtros Instagram | Pendientes / Leídas / Respondidas usan `last_read_at` |

Propuesta `[PROPUESTO]`, igual para todos los canales:

- **Por responder** = `status = 'open'` **y** el último mensaje entrante es posterior al último
  saliente (respondió el dueño **o** el menú automático; ver §5 R3).
- **Todos** = abiertos, con o sin respuesta. **Cerrados** = `status = 'closed'`.
- **Pago por revisar** = chip extra, sólo si el negocio tiene al menos un chat en ese estado.
- «Leídas» desaparece como filtro; `last_read_at` sigue como dato (punto en la fila).
- El predicado vive **una vez** en SQL (función de Python que devuelve el fragmento) y lo usan la
  lista y `attention/counts.py`, para que el número del menú y la lista no puedan diferir.

Cerrar un chat en Instagram no necesita migración: `threads.status` ya admite `closed`. Falta
decidir si un mensaje entrante nuevo lo reabre (en WhatsApp: verificar en `chats.py` y
`handler.py` antes del corte C9).

## 3. Respuesta automática (menú) también en Instagram Direct

> Ampliación pedida por el fundador el 2026-11-13: llevar el menú automático de WhatsApp
> («Respuesta automática», que considera maduro) a Instagram Direct, robustecerlo y,
> si conviene, unificar los menús de los dos canales.

### 3.1 Cómo está construido hoy

| Pieza | Dónde | ¿Atado a WhatsApp? |
|---|---|---|
| Definición del menú (nodos `text`/`buttons`/`list`/`products`/`order_summary`/`collect`/`handoff`, entradas globales: bienvenida, preguntas iniciales, comandos, palabras clave) | `whatsapp/menus/schema.py` (pydantic, sin I/O) | **Sí, en los límites**: valida los de la Cloud API (3 botones de 20, listas de 10 filas, filas de 24/72, 4 preguntas iniciales, 30 comandos; `schema.py:10-17,43-60`). La estructura del grafo no |
| Motor | `whatsapp/menus/engine.py` — `step(definition, state, inbound, catalog, payment_methods) → (acciones, estado)`, **puro y determinista** (`engine.py:1-8`) | **Casi no.** Sus salidas son abstractas (`SendText`, `SendButtons`, `SendList`, `SendPaymentCard`, `Handoff`, `SetContext`, `engine.py:273-362`). Lo único de WhatsApp: `inbound_from_message(WAMessage)` (`engine.py:217-228`) y los topes de lista que usa para paginar |
| Productos por categoría | `engine.py:23-49, 543-731` (centro = lista de categorías, «Ver más», ids `cat:`/`catmore:`/`cats:back`/`prod:`) | Paginado pensado para la lista de 10 filas de WhatsApp |
| Paso de pago | `engine.py:56-77` (insertado en tiempo de ejecución, nodo reservado `PAYMENT_NODE_ID`), `whatsapp/payments.py`, tabla `brand_payment_methods` (0135, ya por marca) | Los métodos no; la tarjeta con QR se sube como medio de WhatsApp (`handler.py:72-79`) |
| Estado por conversación | `whatsapp_thread_state` (cursor `node_id`, `context` con el pedido, `attempts`, `automation_paused_at`) — clave `thread_id` de `threads` | El nombre y los permisos del rol del webhook; la forma no |
| Pegamento | `whatsapp/handler.py:486-592`: carga el menú publicado del **número**, corre `step`, guarda estado, encola en `whatsapp_outbox` (`kind='automation'`), traduce acciones a cuerpos de la Cloud API (`outbox_payload`, `handler.py:357-389`) | **Sí**, todo |
| Tomar el control / Devolver al menú | `whatsapp/chats.py` `pause_automation` / `resume_automation(_at)` (`chats.py:368-385`); estado pausado = motor inerte | Concepto neutral, código en el módulo WhatsApp |
| Menús guardados, versión publicada, archivo y selector | `whatsapp/menus/repository.py` (0058, 0148): versiones inmutables, **una publicada por número** (`uq_wa_menu_phone_published`), menú pausable | **Sí**: el menú se publica a un `phone_number_row_id` |
| Preguntas iniciales / comandos hacia Meta | `whatsapp/menus/automation.py` → `POST /{PHONE_NUMBER_ID}/conversational_automation` | Sí. Instagram tiene su propio `conversations/ice_breakers*.py` |
| Atajos del chat (filas del «+») | 0140 `whatsapp_chat_shortcuts` | Del cuadro de respuesta del dueño, no del menú automático |

Conclusión: **el corazón (esquema + motor) ya es casi independiente del canal**; lo que está
atado es la publicación al número, el traductor de acciones a la Cloud API, la entrada desde el
webhook y el nombre de las tablas. Por eso la extracción es barata.

### 3.2 Opciones para Instagram

| Opción | Qué es | Costo | Riesgo | Migración | ¿Se deshace? | TikTok después |
|---|---|---|---|---|---|---|
| a. Segundo motor sólo para Instagram | Copiar motor + esquema + editor a `conversations/` | Alto (duplica ~2 k líneas probadas y el editor) y doble mantenimiento para siempre | Los dos motores divergen; cada arreglo se hace dos veces | Sí (tablas propias) | Sí, pero caro | Un tercer motor |
| **b. Motor neutral + traductor por canal; una definición por negocio con ajustes por canal acotados** | Mover esquema y motor a un paquete neutral (`qualify_api/chat_automation/`), con un **traductor** por canal (WhatsApp: listas y botones interactivos; Instagram: respuestas rápidas, plantilla de botones, carrusel genérico, preguntas iniciales). El menú es del negocio; los ajustes por canal se limitan a **encendido/apagado y textos de presentación** (bienvenida, aviso de automatización), nunca a otro grafo | Medio (backend 3–4 PR) | Bajo si el primer PR es un movimiento sin cambio de comportamiento (mismas pruebas verdes) | Sí: publicación por canal y estado neutral (§3.6) | Sí: WhatsApp sigue igual si Instagram se apaga | Un traductor y su fila de límites |
| c. Una sola definición, sin ajustes | Igual que b sin ajustes por canal | Algo menor que b | El dueño no puede dejar el menú sólo en WhatsApp ni cambiar la bienvenida en Instagram; la validación debe usar la intersección de límites de todos los canales, lo que encoge WhatsApp | Sí | Sí | Cada canal nuevo puede encoger el menú de todos |

**Recomendación `[PROPUESTO]`: b, con los ajustes por canal acotados a presentación.** Una sola
cosa que aprende el dueño («tu menú»), un solo motor probado, y cada canal decide cómo se ve. La
validación deja de ser «los límites de WhatsApp» y pasa a ser «los límites de cada canal
encendido», comprobada por su traductor al publicar (la regla de hoy, `schema.py:8-10`, se
mantiene: nada publicado puede producir un mensaje que Meta rechace).

Traducción propuesta para Instagram (límites de §3.4):

| Acción del motor | Instagram |
|---|---|
| `SendButtons` (≤ 3, 20 car.) | respuestas rápidas (≤ 13, 20 car.) — o plantilla de botones (≤ 3, texto ≤ 640) cuando el texto pasa del límite de una respuesta rápida |
| `SendList` (≤ 10 filas, con descripción) | respuestas rápidas si ninguna fila depende de su descripción; si no, texto numerado + respuestas rápidas (el motor ya acepta la posición tecleada, `engine.py:83-86`) |
| Productos | carrusel de plantilla genérica (≤ 10 elementos, título y subtítulo de 80, foto del producto) — **el mayor beneficio para un negocio de comida**; en el primer corte basta con respuestas rápidas |
| `SendPaymentCard` | imagen (QR) + texto |
| Preguntas iniciales | API de preguntas iniciales de Instagram (ya cliente en `conversations/ice_breakers_client.py`) |
| Comandos (`/menu`) | no existen; menú persistente queda fuera del primer corte |

**Primer corte que pone un menú funcionando en Instagram** (M2→M3→M4 de §4, mínimos): el mismo
menú de Bianki publicado también en su Instagram, con texto, botones y listas como respuestas
rápidas, productos por categorías como respuestas rápidas, resumen del pedido, paso de pago con
imagen y entrega a una persona. Sin carrusel, sin menú persistente. Funciona hoy sólo con cuentas
con rol en la app (§3.4): para clientes reales de Bianki depende de App Review.

### 3.3 «Asistido, nunca autónomo»: qué dice el texto, sin suponer

> **Corregido el 2026-11-13.** Una versión anterior de esta nota decía que no había registro de
> la decisión y pedía una firma nueva. Era un error: la decisión existe y cubre Instagram.

**La decisión existe.** Meegle **m-24789557** «Decisión del fundador: DM con menú automático vs
ADR 21» (migrado de Linear QUA-138), en Done desde el 2026-10-23. Comentario del fundador de ese
día: **opción B — excepción acotada a «asistido, nunca autónomo»**. Se permite un menú
automático en mensajes directos — el comentario nombra **Instagram y WhatsApp** — sólo si:

1. el texto del menú es **fijo**: el dueño lo escribe o lo aprueba una vez; ningún modelo genera
   contenido en ese envío;
2. la opción **«Hablar con alguien» está siempre** y lleva la conversación a la bandeja asistida
   (borrador + aprobación humana);
3. **ningún texto de la app dice ni sugiere que Qualify responde solo**; se llama «Tu menú de
   bienvenida» (coherente con m-24842959).

Toda respuesta libre sigue asistida; las respuestas autónomas con IA siguen fuera (m-24789464).
Desbloquea m-24789558 y m-24789559 y alinea m-24789472 y m-24842995. (Antecedente: la regla D2
de `docs/plan-modulo-whatsapp-cloud-api.md` §9.1, líneas 197 y 372, *automático = determinista y
declarado; generativo = asistido*. La excepción del 2026-11-04, `docs/arquitectura.md` §1.6, no
viene al caso: trata de procedencia de filas, no de envíos.)

**Lo pendiente es escribir el ADR, nunca se hizo.** El comentario encarga al principal-architect
registrarla como enmienda a ADR 21 en `docs/arquitectura.md` §6. Verificado hoy: ni
`docs/arquitectura.md` ni ningún `docs/adr-*.md` mencionan m-24789557, QUA-138, «menú de
bienvenida» ni «Hablar con alguien»; el último número del registro es el **47**
(`docs/arquitectura.md:304`). Le toca el **ADR 48** («Enmienda a ADR 21: menú fijo en mensajes
directos»), como fila de la tabla de §6 con estado **APROBADO por el fundador 2026-10-23
(m-24789557)**, no `[PROPUESTO]`: es la transcripción de una decisión firmada.

**El código de Instagram todavía no la refleja**, a propósito: `conversations/outbox.py:1-9`
(«ADR 21c en código»): `approved_by_user_id` NOT NULL, la prueba estática
`test_conversations_outbox_sanctity.py`, y el rol del webhook sin ningún privilegio sobre
`conversation_outbox` (0065).

**Mecanismo propuesto**: la aprobación del envío automático es **la publicación de la versión
del menú** (`published_by_user_id`), y cada fila automática lleva `menu_version_id` + `node_id`
como procedencia. En el esquema: `kind='automation'` en `conversation_outbox` con
`approved_by_user_id` nulo **sólo** para ese tipo y `menu_version_id` obligatorio (CHECK), y un
permiso de INSERT al rol del webhook limitado a ese tipo. Se quita una protección de seguridad
deliberada, así que pasa por `security-review` antes de mergear.

#### Contraste con las tres condiciones

**1 · Texto fijo, sin modelo en el envío.** Se cumple en el envío:
- El motor es puro, sin red ni modelo (`whatsapp/menus/engine.py:1-8`), y el handler no llama a
  ninguno (`whatsapp/handler.py:486-592`).
- La IA sólo actúa en el editor, antes de publicar, y como propuesta:
  - «Sugerir con IA» (`menus/suggest_ai.py:1-7`) reemplaza el campo en pantalla, el dueño puede
    deshacerlo y nada se guarda ni se publica ahí.
  - «Cargar mi menú desde una foto o mi página» (`menus/import_ai.py:1-9`) propone datos que el
    dueño acepta campo por campo.
  - En los dos casos lo enviado es lo publicado.

Hay textos fijos que el dueño **no escribió**, y la decisión dice «lo escribe o lo aprueba una
vez»:
- textos que trae Qualify: la línea de ayuda ante una respuesta que el menú no entiende, la
  entrega por defecto (`engine.py:56-57`), «Elige una de las opciones para seguir.» y «Te
  confirmamos el monto en …» del paso de pago (`engine.py:56-77`);
- textos armados con datos del dueño en el momento del envío: la respuesta «Formas de pago»
  (`starter.composed_payment_text`, `engine.py:78-81`), las listas del catálogo y el total del
  pedido.

Todos son deterministas, sin modelo. **Que el dueño los «aprueba» al publicar el menú es una
interpretación**, no está en el texto: lo marco para que el ADR 48 lo diga en una línea.

**2 · «Hablar con alguien» siempre.** Hoy sólo **por costumbre**, el esquema no lo obliga:
- El iniciador lo trae (`menus/starter.py:368`, `fallback_node: "persona"` en `:523`).
- El esquema sólo exige que «Confirmar» termine en una entrega a persona y que `fallback_node`
  sea una entrega (`menus/schema.py:420, 443-458`).
- Tras 2 respuestas no reconocidas el motor entrega solo (`engine.py:133, 1276`).
- No verifiqué si el editor deja borrar la opción «persona» (`Qualify/whatsapp_menu_vm.py`).

Para cumplir la decisión, M2 debe pasar la regla a la validación del esquema: una opción visible
de entrega a persona alcanzable desde el nodo de inicio, y el editor no la deja quitar.

**3 · Ningún texto dice que Qualify responde solo.** Hay una prueba que ya cuida dos frases
(`Qualify/test_whatsapp_menu_publish.py:316`: ni «responde solo» ni «Qualify responde»). Textos
que **pueden chocar** con «Tu menú de bienvenida» o con la idea de que responde algo automático.
No decido el texto, sólo lo marco para el fundador y UX:

| Texto | Dónde vive |
|---|---|
| «Respuesta automática» (nombre de la pestaña y de la sección) | `Qualify/whatsapp_vm.py:79,90`; `Qualify/whatsapp_page.py:10,232`; `Qualify/whatsapp_chats_vm.py:1295,1297` («Ir a Respuesta automática») |
| «Atiende y vende por WhatsApp: tus chats, tu menú automático y tus promociones.» | `Qualify/whatsapp_page.py:163` (y su prueba `Qualify/test_whatsapp_copy.py:112`) |
| «Todavía no tienes una respuesta automática con tus productos activa.» | `Qualify/whatsapp_chats_vm.py:1294` |
| «Al enviarlo, la respuesta automática vuelve a atender este chat.» | `Qualify/whatsapp_chats_vm.py:1301` |
| «Al responder, la respuesta automática se pausa en esta conversación.» | `Qualify/whatsapp_tab_chats.py:2481` |
| «…tomar el control de la respuesta automática…» | `Qualify/whatsapp_tab_chats.py:2558` |
| «…puede publicar el menú automático ni la bienvenida.» | `Qualify/capabilities.py:111` |
| «Está respondiendo tu menú automático · Responder yo» (franja propuesta) | `docs/ux-chats-unificados.md:78` y la maqueta `docs/mockups/chats-unificados.html` |
| «WhatsApp: Respuesta automática» en el árbol de «Ajustes de chats» | `docs/ux-chats-unificados.md:63` |
| Aviso al cliente propuesto en esta nota, «Te responde el menú automático de {negocio}» | §5 P6 de esta nota. Lo lee el **cliente final**, no el dueño; la condición 3 habla de «la app». Si cae dentro, choca con ella; si no, es la vía para el aviso que Meta recomienda (§3.4) |
| Nombre del corte M5, «Respuesta automática» dentro de «Ajustes de chats» | §4.2 de esta nota |

Lo generativo («Sugerir respuesta») sigue asistido sin excepción.

#### ¿Algo del mecanismo va más allá de la decisión?

- **El mecanismo de la outbox (aprobación = versión publicada) cabe** en la condición 1, siempre
  que M3 lo limite así:
  - sólo filas con `menu_version_id` de una versión publicada;
  - sólo texto, botones, listas, la imagen del QR o fotos del catálogo;
  - nada producido por un modelo.

  Una prueba estática debe impedir que `suggest.py` o cualquier generador escriba `kind='automation'`.
- **Necesitan al fundador** (fuera del texto del 2026-10-23):
  - (a) la reanudación automática del menú tras un tiempo sin respuesta del dueño (§3.5 punto 5,
    §5 P5), si se elige: el texto sólo prevé que la conversación pase a la persona;
  - (b) el aviso al cliente con la palabra «automático» (tabla anterior);
  - (c) que los textos fijos de Qualify y los armados con datos del dueño cuenten como
    «aprobados una vez» al publicar.
- **Nada más.** El carrusel de productos (M7) usa fotos y nombres del catálogo: es texto fijo.

### 3.4 Restricciones de Meta para respuestas automáticas en Instagram

Fuente: copia local de la documentación de Meta en `reference/meta-instagram-platform/`
(cosechada; último cambio del archivo de resumen en git: 2026-07-28). Leída hoy en el disco; **no**
verificada en vivo contra la API (ADR 25 exige la prueba en vivo antes del corte M4).

| Restricción | Estado |
|---|---|
| Sólo se puede escribir después de que la persona escribió; 24 h para responder | [docs de Meta: `instagram-api-with-instagram-login/messaging-api.md:36`; `business-messaging/instagram-messaging/overview.md:27-28`] + [repo: ventana compartida `conversations/window.py`] |
| Etiqueta de agente humano para responder fuera de las 24 h: **sólo cuando responde una persona**, no para el menú | [docs de Meta: `messaging-api.md:84`, `overview.md:28`]; el repo dice que pide otro permiso y otra App Review y **no está modelada** [repo: `docs/conversaciones-limitaciones-meta.md` fila 11] |
| Respuestas rápidas: hasta 13, 20 caracteres, sólo texto | [docs de Meta: `features/quick-replies.md:5`] |
| Plantilla de botones: hasta 3 botones, texto ≤ 640 | [docs de Meta: `button-template.md:5,133`] + [repo: `contracts.py:244`] |
| Plantilla genérica: ≤ 10 elementos, título y subtítulo de 80 | [docs de Meta: `generic-template.md:100-105`] |
| Preguntas iniciales: hasta 4; no disponibles en escritorio | [repo: `conversations/ice_breakers.py:39`]; [docs de Meta: `features/ice-breakers.md:7-9`] |
| Menú persistente: no se actualiza en conversaciones abiertas; no personalizable por persona | [docs de Meta: `features/persistent-menu.md:13-19`] |
| **Debe existir un camino a una persona** (las apps de mensajería de Instagram «deben tener» escalamiento a agente humano) | [docs de Meta: `overview.md:72-74`, `features/human-agent-escalation.md`]. Lo cumplen el nodo `handoff` + la bandeja; hay que poder demostrarlo |
| **Avisar que es automático** «cuando lo exija la ley aplicable», y al pasar de persona a automático; Meta lo recomienda siempre | [docs de Meta: `messaging-api.md:61-76`]. Si la ley de CO/VE/UY lo exige: [sin verificar]. Recomiendo una línea fija en la bienvenida de Instagram, decidida con `qualify-copy-es` |
| Con acceso Standard sólo se puede conversar con personas con rol en la app; para clientes reales hace falta Advanced Access de `instagram_manage_messages` + app en Live | [repo: `docs/conversaciones-limitaciones-meta.md` fila 2, «QUA-142, en curso, plazo Meta 2026-12-11»; estado actual sin verificar] |
| **App Review:** para apps que otros negocios usan, el video debe mostrar cómo se arma una experiencia automatizada o una bandeja propia y cómo maneja mensajes | [docs de Meta: `app-review/apps-for-other-businesses.md:5-19,45-55,83-87`]. **Cambia lo que se declara:** si el menú automático de Instagram va a existir, conviene que la sumisión de `instagram_manage_messages` lo muestre (menú + entrega a persona + bandeja), en vez de sólo la bandeja asistida. Si la sumisión ya salió sin él, preguntar si hace falta una nueva [sin verificar] |
| Equivalente de `request_welcome` de WhatsApp (mensaje al abrir el chat) en Instagram | [sin verificar]; el menú de Instagram arrancaría con el primer mensaje o el toque de una pregunta inicial |

### 3.5 Robustecer lo de hoy: puntos débiles con evidencia

1. **Estado y respuesta no son atómicos; una caída deja al cliente sin respuesta.** El estado
   se guarda en una transacción y cada fila de la outbox en otra (`handler.py:66-69`,
   `560-582`); la repetición del webhook se salta el paso del menú porque el mensaje ya está
   (`handler.py:17-19`). El propio docstring acepta perder «a lo sumo una respuesta automática»:
   el cursor avanzó y el cliente no recibió la lista. Arreglo: estado + outbox en **una**
   transacción.
2. **Sin candado por conversación.** El procesador de webhooks reclama filas con
   `FOR UPDATE SKIP LOCKED` y se declara seguro con varios trabajadores
   (`webhooks/worker.py:66`), pero el estado del menú se lee y se escribe sin bloqueo: dos
   mensajes seguidos del mismo cliente en dos trabajadores pisan el estado (el segundo gana).
   Hoy no pasa porque producción corre **una** réplica de `webhook-worker`
   (`deploy/docker-compose.prod.yml:357`). Arreglo: `pg_advisory_xact_lock` por `thread_id` o
   `SELECT … FOR UPDATE` del estado dentro de la transacción de 1.
3. **Respuestas automáticas ya encoladas salen aunque el dueño haya tomado el control.** La
   outbox de WhatsApp no mira la pausa al enviar (`whatsapp/outbox.py`: `automation` sólo
   aparece para la tarjeta de pago, `951-964`); si el dueño toca «Tomar el control» entre el
   encolado y el envío, el cliente recibe la lista del menú después del mensaje del dueño.
   Arreglo: el remitente descarta (estado `cancelled`) filas `automation` de hilos pausados
   después de su `created_at`.
4. **Un rechazo de Meta a un mensaje automático no cambia el estado del menú.** La fila queda
   `failed` (terminal, «una persona decide», `outbox.py:27-43`) pero el cursor ya avanzó y el
   hilo no se entrega a nadie: el cliente ve silencio y el chat no aparece como «por responder»
   si su último entrante es anterior al último saliente encolado [a verificar con una prueba].
   Arreglo: un fallo terminal de una fila `automation` pausa el hilo con motivo «no se pudo
   enviar» y lo devuelve a «Por responder».
5. **Una conversación entregada a una persona queda pausada para siempre.** No hay reanudación
   por tiempo (búsqueda de `resume`/`stale` en `whatsapp/` y `menus/`: nada); si el dueño no
   toca «Devolver al menú», el próximo pedido de ese cliente días después no lo atiende el menú.
   Pregunta para el fundador (§5 P5), no un defecto en sí.

Lo que sí está bien cubierto: repetición del mismo webhook
(`tests/test_whatsapp_handler.py:241`), cambio de versión con conversaciones en curso (reinicia
el cursor, conserva el pedido; `:456`), confirmación repetida (`:621`), toques de productos de
listas viejas (`engine.py:42-46`). Observabilidad: sólo un log por paso (`handler.py:583-592`);
no hay métrica de entregas a persona, ni de fallos de envío automático por hilo.

### 3.6 Datos que cambian (para M3)

- Publicación del menú: hoy `whatsapp_menus.phone_number_row_id` + `uq_wa_menu_phone_published`.
  Propuesto: una tabla de **destinos** del menú (`menu_id`, `channel`, `connection_id` o
  `phone_number_row_id`, `enabled`, textos de presentación), con unicidad «un menú publicado por
  destino», RLS en la misma revisión y backfill de los números de hoy. Reversible.
- Estado por conversación: renombrar `whatsapp_thread_state` a un nombre neutral (las políticas
  RLS y las concesiones siguen a la tabla) y ampliar la concesión del rol del webhook a hilos
  `dm`. El `context` ya es JSON y no cambia.
- `conversation_outbox`: `kind='automation'` como en §3.3.

## 4. Cortes de la épica, en orden de dependencias

Cada corte es un PR. «UI» = reflex-ui-engineer; «BE» = backend-engineer; «DS» =
data-scientist-fde; «UX» = ux-designer (medición o revisión, no código).

### 4.1 Bandeja

| # | Corte | Dueño | Depende de | Migración |
|---|---|---|---|---|
| C1 | Servicio de lectura de la bandeja (una consulta, cursor compuesto, §2.2) + `ChannelCapabilities` (§2.1) + predicado único de «por responder» usado también por `attention/counts.py` (§2.3) | BE | — | No |
| C2 | Fila compartida (la de Instagram generalizada, una sola píldora con prioridad en el VM) | UI | — (puede leer los VM de hoy) | No |
| C3 | **Lista unificada bajo «Por responder»** con filtro de canal (sólo con ≥ 2 canales) y Por responder / Todos / Cerrados (+ «Pago por revisar»); al tocar abre el chat de hoy de su canal | UI | C1, C2 | No |
| C4 | Hilo y burbujas compartidos; **primero** UX mide el contraste en claro y oscuro (D2), después UI aplica el juego único de reglas en `qualify-inbox.css` | UX → UI | C3 | No |
| C5 | Cuadro de respuesta compartido guiado por capacidades + despachador de envío por `threads.channel` (las dos outboxes siguen) + «Mensajes guardados» para todos los canales | UI + BE | C1, C4 | No [verificar que la tabla de plantillas de Instagram no tenga el canal en su clave] |
| C6 | «Ajustes de chats»: sacar la configuración de WhatsApp de la pantalla de mensajes; traer preguntas iniciales y mensajes guardados de Instagram; «Tu número» pasa a «Tus redes» | UI | — (en paralelo a C2–C4) | No |
| C7 | Nombres de D5 + redirecciones (`/whatsapp` → `/responder?tab=mensajes&canal=whatsapp`, enlaces profundos de notificaciones y del menú lateral) | UI | C3, C6 | No |
| C8 | «Promociones» junto a «Anuncios» (D3) | UI | — | No |
| C9 | «Cerrar chat» / «Reabrir» en Instagram; regla de reapertura al llegar un mensaje (igual en los dos canales) | BE + UI | C1 | No (`threads.status` ya existe) |
| C10 | Formas de pago y «Cómo llegar» como datos del negocio en «Ajustes de chats › Para todos tus chats»; el «+» de Instagram los manda | BE + UI | C6 (y C5 para el «+» de Instagram) | **Sí** para «Cómo llegar»: hoy vive en `whatsapp_phone_numbers.location_*` (`whatsapp/models.py:141-144`) → pasa a la marca con backfill. Formas de pago no: `brand_payment_methods` (0135) ya es por marca |
| C11 | «Sugerir respuesta» en WhatsApp (D4) | DS (medir) ∥ BE → UI | C5 para el botón; la medición puede empezar ya | No |

**C11 en detalle.** Se reutiliza `conversations/suggest.py` (Haiku 5.5, esfuerzo bajo, una
herramienta estricta, `needs_review` con chequeo local de precios) con un adaptador de los
registros de WhatsApp al `ThreadRecord`/`MessageRecord` que pide `gate`/`transcript`, y contexto
de WhatsApp (ventana, si el menú está atendiendo, pedido en curso). Costo: lo medido para
borradores de comentarios es **US$0,00009–0,00017 por borrador** [V, `docs/interacciones-fase-b-
respuestas-comerciales.md:99`, `docs/respuestas-comentarios-medicion.md:146`]; un chat lleva más
contexto, estimado ≤ US$0,001 por toque [H] → 30 toques al día ≈ US$1 al mes por negocio [H].
El libro de consumo se engancha solo: toda llamada pasa por `claude_tools.messages_create` →
`ledger_sink` (`claude_tools.py:255-351`); hace falta una **función propia** (`respuesta-whatsapp`,
junto a `respuesta-dm` de `suggest.py:216` y `docs/libro-de-consumo-claude.md:60`) para ver el
costo por canal. Guardia de precio: tope diario por negocio antes de la llamada, y bandera por
negocio apagada por defecto. **`qualify-measure` antes de encender:** un conjunto de chats reales
de WhatsApp de Bianki (anonimizado), tasa de borradores usables y de `needs_review`, costo medido
por toque, documentado el mismo turno en `docs/modelos-generativos/` y en la ficha de Haiku 5.5.

### 4.2 Respuesta automática (menú)

| # | Corte | Dueño | Depende de | Migración |
|---|---|---|---|---|
| M1 | Robustecer WhatsApp (§3.5 puntos 1–4): estado + outbox en una transacción, candado por conversación, descartar automáticas de hilos pausados, fallo terminal → entrega a persona, métricas de entregas y fallos | BE | — **puede empezar ya** | Probablemente no (estado `cancelled` en la outbox: verificar el CHECK; si falta, sí) |
| M2 | Extraer el motor neutral (`chat_automation/`: esquema, motor, `Inbound` neutral, traductor de WhatsApp = el `outbox_payload` de hoy). Sin cambio de comportamiento: mismas pruebas verdes; **más** la condición 2 de m-24789557 como regla de validación (entrega a persona visible desde el inicio, §3.3) | BE | M1 (mismos archivos) | No |
| M3 | Destinos del menú por canal + estado neutral + `kind='automation'` en `conversation_outbox` (§3.3, §3.6) | BE | M2, **ADR 48 escrito en `docs/arquitectura.md` §6** (transcripción de m-24789557, ya firmada) y una revisión de que el cambio de la outbox de Instagram queda dentro de las tres condiciones (sólo versiones publicadas, sin modelo, prueba estática; `security-review`) | **Sí** |
| M4 | Traductor e integración de Instagram: entrada desde el webhook de `conversations` (`choice_kind`/`choice_payload` ya existen en `contracts.py:113-116`), respuestas rápidas, plantilla de botones, imagen del pago, preguntas iniciales, aviso de automatización. **Prueba en vivo con una cuenta con rol antes de mergear (ADR 25)** | BE | M3; para clientes reales, App Review (QUA-142) | No |
| M5 | «Respuesta automática» dentro de «Ajustes de chats» con encendido por canal y vista «Así le llega» por canal | UI | C6, M3 | No |
| M6 | Franja «quién responde» (Responder yo / Devolver al menú) en el hilo compartido, también para Instagram | UI | C4, M4 | No |
| M7 | Carrusel de productos en Instagram (plantilla genérica con foto) | BE + UI | M4 | No |

**Pueden empezar antes de la bandeja:** M1, M2 (y M3 en cuanto esté escrito el ADR 48), C1, C2, C6,
C8, la medición de C11. **Dependen de la bandeja:** C3→C4→C5→C7, C9 (de C1), C10 (de C6/C5),
M5 (de C6), M6 (de C4).

## 5. Riesgos y preguntas que hay que cerrar antes de empezar un corte

1. **App Review de mensajes de Instagram (antes de C3 si se quiere valor en Instagram, y antes
   de M4).** Con acceso Standard, Instagram Direct sólo funciona con personas con rol en la app;
   para los clientes reales de Bianki hace falta Advanced Access de `instagram_manage_messages`
   (QUA-142, plazo de Meta 2026-12-11 según `docs/conversaciones-limitaciones-meta.md` fila 2;
   estado de hoy sin verificar). Sin él, «una bandeja» muestra sólo WhatsApp a los clientes. Y si
   habrá menú en Instagram, la sumisión debería mostrarlo (§3.4).
2. **Menú en Instagram: decidido, falta escribirlo y cumplirlo (antes de M3).** El fundador lo
   aprobó el 2026-10-23 (m-24789557) con tres condiciones (§3.3). Falta escribir el ADR 48 en
   §6. Además, tres puntos fuera del texto de esa decisión necesitan su respuesta:
   - (a) reanudación automática del menú (P5);
   - (b) un aviso al cliente con la palabra «automático» (P6);
   - (c) si los textos fijos de Qualify cuentan como «aprobados al publicar».

   Y los textos de la app que chocan con la condición 3 (tabla de §3.3) van a UX y al fundador
   antes de M5/M6.
3. **«Por responder» cuando contestó el menú (antes de C1).** ¿Un chat al que respondió el menú
   automático está «por responder»? Propuesta: no, salvo que se haya entregado a una persona
   (`Handoff`) o falló un envío. Lo decide el PO con el fundador.
4. **Costo de «Sugerir respuesta» (antes de C11).** Cada toque es una llamada pagada: confirmar
   tope por negocio y si cuenta en el cupo de creaciones o es gratis para el dueño
   (`qualify-business-decisions` si cambia el plan).
5. **Pausa eterna tras «Tomar el control» (antes de M1).** ¿Vuelve el menú solo después de N
   horas sin mensajes del dueño, o sólo con «Devolver al menú»?
6. **Aviso de automatización y ley local (antes de M4).** ¿Línea fija «Te responde el menú
   automático de {negocio}» en Instagram (y en WhatsApp por coherencia)? Verificar si CO/VE/UY lo
   exigen; Meta lo recomienda siempre.

Riesgo técnico principal: tocar `whatsapp_tab_chats.py` (2,6 k líneas) y su estado (2,7 k) en
paralelo en C2–C7 y M5–M6 produce conflictos; un solo dueño de UI por archivo y cortes en serie
sobre esos dos archivos.

## 6. Qué no debe suponer la costura (TikTok DM después)

Sin investigar la API de TikTok: la costura no debe suponer que…

- el canal tiene **historial legible por sondeo** (WhatsApp no lo tiene; `ConversationSource`
  sí lo supone) — la ingesta es por canal, la bandeja lee `threads`;
- existe una **ventana de 24 h** ni un «mensaje aprobado» después: la regla de ventana es un dato
  del descriptor (`window.hours`, `after_window`), puede no existir o ser otra;
- hay **botones, listas o respuestas rápidas**: el motor de menú debe funcionar con texto y número
  tecleado (ya lo hace, `engine.py:83-86`) y el traductor declara lo que hay;
- el identificador del cliente es **portable** o comparable con el de otro canal;
- se pueden enviar **medios** o **stickers**, ni con qué tamaños;
- el canal da **confirmaciones de lectura** o perfil del cliente;
- todo canal tiene **un número o una página** a la que se publica el menú (el destino es
  `connection_id` genérico, §3.6);
- una nueva entrada en `ck_thread_channel` es gratis: agregar `tiktok_dm` es una migración (CHECK)
  más su descriptor, su traductor, su ingesta y su propia outbox.

Lo que sí puede suponer: `threads`/`messages` con RLS como almacén único de conversaciones, una
outbox por canal con aprobación humana (o versión de menú publicada, según m-24789557 / ADR 48),
y el motor de menú puro como cerebro de la respuesta automática.
