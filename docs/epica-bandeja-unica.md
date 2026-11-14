# Épica — Bandeja única de chats y respuesta automática en todos los canales

`[EN CURSO · planeada 2026-11-12, actualizada 2026-11-14 · épica m-25017839 · ticket base m-24789459 · product-owner · 17 tickets en Meegle, 19 historias sin ticket · primer incremento fusionado]`

> **Estado al 2026-11-14.** El primer incremento (m-25017843 → m-25017844 → m-25017859) está
> fusionado en `main`; m-25017859 (PR #665) se fusionó el 2026-11-14 y su despliegue no estaba
> confirmado al escribir esto. BU-A13 tiene ticket: **m-25026457** (PR #653, en producción).
> Nada de la lista única ni de «Cerrar» en Instagram se ha visto funcionar en un navegador. Detalle
> por historia en §3 y §7; decisiones del fundador de la lista en §6 (vii); seguimientos sin ticket
> en §5.

> Épica en Meegle: **m-25017839** (Feature, Product Feature Request,
> https://project.larksuite.com/5h2wsx/story/detail/25017839). El fundador aprobó el 2026-11-12
> crear la épica y **solo los 16 tickets que pueden empezar ya**: 12 historias enlazadas a la épica
> y los 4 Issues aparte de §7 (sin enlace a la épica). Las historias con ticket llevan su `m-<id>`;
> las otras 20 (19 del borrador más BU-B10, agregada en la revisión) conservan su id provisional `BU-*` y dicen «Sin ticket todavía» y qué esperan.
> El 2026-11-13 se creó m-25026457 para BU-A13 tras la decisión «Ventana + cerrar chat» (§6 (vii)):
> quedan 19 sin ticket.
> Al crearse, todos en Backlog, Reporter y Assignee el fundador (sin desarrollador asignado todavía).
>
> Fuentes: la propuesta UX aceptada `docs/ux-chats-unificados.md` (D1–D5, 2026-11-12) y su maqueta
> `docs/mockups/chats-unificados.html`; la nota de arquitectura `docs/arquitectura-bandeja-unica.md`
> (opción C para la bandeja, opción (b) para los menús, cortes C1–C11 y M1–M7); el pedido del
> fundador del 2026-11-12; la descripción del PR #608. Cada afirmación tomada de esos
> documentos lleva su sección entre corchetes, p. ej. `[arq §2.3]`, `[UX §3 D2]`, `[PR #608]`.
> Lo marcado **[supuesto PO]** es mío y no tiene otra fuente.
>
> Secciones: 1 Resultado · 2 Cómo se organiza en Meegle · 3 Pista A «Una sola bandeja» ·
> 4 Pista B «Respuesta automática en todos los canales» · 5 Primer incremento y paralelo ·
> 6 Decisiones del fundador · 7 Issues aparte (fuera de la épica) · 8 Lo que creo que está mal o no
> se puede entregar así · 9 Prompt para `/qualify-team-dev`.

## 1. El resultado, en palabras del dueño

> «Veo en una sola lista a todos los clientes que me están esperando, me escriban por WhatsApp o
> por Instagram; les contesto igual en los dos, sin buscar botones distintos; y mi menú automático
> toma los pedidos en los dos canales sin que se me pierda ningún cliente.»

Evidencia: pedido del fundador del 2026-11-12 (los dos chats deben verse y funcionar igual,
configuración separada de los mensajes, menos pestañas y submenús) `[UX §0]` y del 2026-11-12
(el menú automático de WhatsApp también en Instagram, más robusto, menús unificables) `[arq §3]`.

**Cómo sabremos que funcionó** (tres señales comprobables):

1. **Un solo número de «Por responder».** El contador del menú lateral y la lista dan el mismo
   número para todos los negocios, porque los dos usan el mismo predicado `[arq §2.3]`. Se
   comprueba con una prueba que compara `attention/counts.py` con la consulta de la lista, y con
   una lectura en producción del negocio de Bianki el día del despliegue.
2. **Ninguna respuesta automática perdida.** Durante 14 días después de m-25017866, cero hilos de
   WhatsApp con el cursor del menú avanzado y su fila automática `failed` sin entrega a una persona
   (métrica nueva de m-25017866, `[arq §3.5]` puntos 1 y 4). Hoy no se puede medir: no existe esa
   métrica `[arq §3.5, último párrafo]`.
3. **El menú atiende en Instagram.** Al menos un pedido completo (productos → resumen → paso de
   pago o entrega a una persona) tomado por el menú en el Instagram de Bianki con una cuenta de
   prueba con rol en la app (prueba en vivo de ADR 25), y, cuando haya Advanced Access, con un
   cliente real `[arq §3.2, «Primer corte…»]`.

## 2. Cómo se organiza en Meegle

- **Feature m-25017839** `Épica — Bandeja única de chats y respuesta automática`, plantilla
  Product Feature Request (617476, porque es algo que ve el dueño), con las historias de las pistas
  A y B enlazadas por el campo «Feature». Los cuatro Issues de §7 quedan **fuera** de la épica; el
  de «Persona sin nombre» (m-25017852) está «Relacionado con» m-25017844 y m-25017859.
- **Dependencias cargadas en Meegle («Bloqueado por»):** m-25017859 ← m-25017843, m-25017844;
  m-25017866 ← m-25017846; m-25017868 ← m-25017866.

| Id provisional | Ticket | Prioridad |
|---|---|---|
| BU-A1 | m-25017843 | P1 |
| BU-A2 | m-25017844 | P2 |
| BU-A3 | m-25017859 | P1 |
| BU-A4 | m-25017860 | P2 |
| BU-A9 | m-25017861 | P2 |
| BU-A12 | m-25017862 | P2 |
| BU-A13 | m-25026457 (creado el 2026-11-13) | P1 |
| BU-A16 | m-25017863 | P2 |
| BU-A19 | m-25017864 | P2 |
| BU-A20 | m-25017865 | P3 |
| BU-B1 | m-25017846 | P1 |
| BU-B2 | m-25017866 | P1 |
| BU-B3 | m-25017868 | P2 |
| BU-S1 | m-25017848 | P2 |
| BU-S2 | m-25017849 | P2 |
| BU-S3 | m-25017850 | P2 |
| BU-S4 | m-25017852 | P1 |
- **El Issue base m-24789459** «Bandeja unificada cross-canal» (Backlog, `parking-lot`, sin
  Assignee): recomiendo **no convertirlo** en Feature (cambiar el tipo de un ítem no es algo que
  hagamos por API y perdería su historial) sino enlazarlo a la Feature nueva como la historia de
  la propuesta UX, que ya se entregó con el PR #611 (maqueta y decisiones, mergeado), quitarle
  `parking-lot`, ponerle Assignee y moverlo a Done. Así los PR #611 y este documento siguen
  apuntando a un ticket válido. Alternativa: dejarlo como «Relacionado con» de la Feature y
  cerrarlo como reemplazado. **No se hizo nada; espera el visto bueno del fundador.** Hoy ya está
  enlazado a la Feature 24789418 «Parking lot — features analizadas (no planificadas)»: cambiar su
  campo «Feature» lo sacaría de esa épica, por eso no se tocó.
- Todas las historias con Assignee al crearlas (sin Assignee el equipo no puede moverlas).
- Ya entregado esta semana, **no se replanea**: m-25017173 (PR #606: sin subpestaña «Stickers y
  videos» en WhatsApp › Chats, «Enviar» en los dos canales, camino de vuelta desde Tu marca; en
  producción, ticket RESOLVED, falta la comprobación visual) y m-25017174 (PR #608: demora de los
  mensajes; Done, el fundador confirmó «Llegan rápido»).

**Convenciones de este documento.** Prioridad según `docs/formato-tickets-meegle.md` §3 (P1 =
bloquea otro trabajo o es de esta semana; P2 = lo normal; P3 = cuando haya hueco). Tamaño S
(≤ 1 día), M (2–3 días), L (≥ 4 días) **[supuesto PO]**. Dueño: `reflex-ui` / `backend` /
`creative` / `platform` / `datasci` / `ux`. Todo PR de código cumple además `just ci-lint` y
`just ci-test` verdes; todo PR que toca pantallas pasa la revisión local de `ux-designer` antes de
abrirse (`qualify-pr`). Eso no se repite en cada historia.

## 3. Pista A — «Una sola bandeja»

Base: opción C de la nota de arquitectura — **se une la lectura, no la escritura**: una consulta
sobre `threads` para todos los canales y un descriptor de capacidades por canal; el envío sigue por
canal, con dos outboxes y dos workers `[arq §1.2, §1.3]`. Cortes de origen C1–C11 `[arq §4.1]`.

**Dónde partí o junté cortes del arquitecto, y por qué**

| Corte | Qué hice | Por qué |
|---|---|---|
| C4 | Partido en m-25017860 (medir contraste, `ux`) y BU-A5 (hilo y burbujas, `reflex-ui`) | Son dos dueños y la medición es condición de D2 `[UX §3 D2]`: se entrega sola (una tabla en el doc) y decide el alfa antes de tocar CSS |
| C5 | Partido en BU-A6 (despachador de envío, `backend`), BU-A7 (cuadro de respuesta, `reflex-ui`) y BU-A8 (mensajes guardados en todos los canales) | El corte junta backend, UI y una biblioteca nueva para WhatsApp: no cabe en un PR. El despachador se prueba solo; la biblioteca tiene su propia pregunta de esquema `[arq §4.1 C5, «verificar…»]` |
| C6 | Partido en m-25017861 («Ajustes de chats») y BU-A10 («Tu número» → «Tus redes») | Cada uno tiene valor propio y tocan pantallas distintas (`/whatsapp` vs `/connections`) |
| C10 | Partido en BU-A14 (migración «Cómo llegar» a la marca, `backend`) y BU-A15 (sección y «+» de Instagram, `reflex-ui`) | La migración con relleno se despliega y verifica antes de cambiar pantallas `[arq §4.1 C10]` |
| C11 | Partido en m-25017863 (medición, `datasci`), BU-A17 (servicio con tope y bandera, `backend`) y BU-A18 (botón, `reflex-ui`) | La medición puede empezar ya `[arq §4.1 C11]`; encender cuesta dinero y depende de la decisión (iii) |
| — | Agregadas m-25017864…BU-A22 | Restos UX de las revisiones de esta semana que el fundador asignó a esta épica (pedido 2026-11-12, punto 4) |

### m-25017843 (BU-A1) · Bandeja: una sola consulta de chats y una sola definición de «por responder»

> **Done — PR #625, fusionado el 2026-11-13.** La regla vive en
> `packages/api/src/qualify_api/inbox/awaiting.py`. El PR #649 (bajo m-25017859, fusionado el
> 2026-11-13) le agregó el límite de la ventana de Instagram (§6 (vii) 1); el PR #665 la conectó a
> la lista, los contadores, las tarjetas e Inicio.

- **Tipo / etiqueta:** Issue · `Improvement` · **P1** (bloquea m-25017859, BU-A6, BU-A13) · **M** · dueño `backend`
- **Depende de:** — · **Bloqueada por:** — (la decisión (ii) quedó decidida por el fundador el 2026-11-13: «Solo si pasó a persona»; regla en §6 (ii))
- **Historia:** Como dueño de un local de comida que atiende por WhatsApp e Instagram, quiero que
  Qualify cuente igual a los clientes que me esperan en los dos canales, para que el número del
  menú y la lista nunca digan cosas distintas.
- **Propuesta:** servicio de lectura de la bandeja en `qualify_api/inbox/` con una consulta sobre
  `threads` filtrada por una lista blanca de canales, último mensaje con `LEFT JOIN LATERAL`,
  datos de WhatsApp con `LEFT JOIN` (nulos en Instagram), cursor compuesto
  `(last_message_at DESC NULLS LAST, id DESC)` sobre `ix_thread_inbox_order` `[arq §2.2]`;
  `ChannelCapabilities` congelada por canal en `inbox/channels.py` `[arq §2.1]`; el predicado de
  «por responder» vive una vez y lo usan la lista y `attention/counts.py` `[arq §2.3]`.
- **Criterios de aceptación**
  - [x] Prueba: con hilos de WhatsApp e Instagram del mismo negocio, la consulta devuelve una lista
        ordenada por hora y una página por ida a la base (sin N+1: la prueba cuenta las consultas).
  - [x] Prueba: dos hilos con el mismo `last_message_at` aparecen los dos al paginar (cursor compuesto).
  - [x] Prueba: el número de `attention/counts.py` y el total de «Por responder» de la consulta son
        iguales en los casos: entrante sin respuesta, respondido por el dueño, respondido por el
        menú, entregado a una persona, envío automático fallido, chat cerrado.
  - [x] Prueba de la regla decidida (ii): un chat abierto contestado solo por el menú **no** cuenta;
        uno entregado a una persona («Hablar con alguien» o turno del dueño) **sí** cuenta; uno con un
        envío automático fallido **sí** cuenta; uno cerrado no cuenta.
  - [x] Prueba de aislamiento: con dos negocios, la consulta en `tenant_session` del negocio A no
        devuelve hilos de B; un canal fuera de la lista blanca se rechaza.
  - [x] Prueba que une el descriptor con la realidad: `attachments` de Instagram ==
        `REPLY_MEDIA_TYPES`; `suggest_reply` de WhatsApp es `False` `[arq §2.1]`.
  - [x] p95 de una página de 50 hilos < 300 ms con los datos de prueba (si no, se anota y se abre
        la desnormalización de `last_outbound_at`, no otro almacén) `[arq §2.2]`.
  - Pruebas en `packages/api/tests/test_inbox_unified_db.py`, `test_inbox_unified.py`,
    `test_inbox_channels.py` y `test_inbox_awaiting.py`.
- **Texto para el cliente:** ninguno (backend).
- **Fuera de alcance:** cambiar pantallas; unir outboxes o workers; unir la identidad de una persona
  entre canales `[arq §1.3]`.
- **Migración:** no `[arq §4.1 C1]` · **Medición:** no · **Firma:** ya tomada (decisión (ii), 2026-11-13).

### m-25017844 (BU-A2) · Conversaciones: una sola fila de chat para WhatsApp e Instagram

> **Done — PR #624, fusionado el 2026-11-13.** El fundador vio la fila en su celular en producción
> («se ve bien», 2026-11-13). Sin ver en pantalla: el orden de las etiquetas, abrir con Enter o
> Espacio, un chat con carrito, la captura a 360 px. La etiqueta de tiempo cambió después a
> «Quedan {N} min para responder» y la prioridad final es la de §6 (vii) 9.

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **M** · dueño `reflex-ui`
- **Depende de:** — (puede leer los VM de hoy `[arq §4.1 C2]`) · **Bloqueada por:** —
- **Historia:** Como dueño de un local que contesta desde el celular, quiero que cada chat se vea
  igual sin importar el canal y con una sola etiqueta de lo más urgente, para entender de un
  vistazo a quién atender primero.
- **Propuesta:** generalizar la fila de `conversations_page.py:333-430`; WhatsApp deja la suya
  (`whatsapp_tab_chats.py:236-306`). Una sola píldora elegida en el VM con la prioridad
  «Pago por revisar» › «Responde en N min» › «Quiere comprar»; sin «Cerrado» en la fila
  `[UX §2, §4 punto 7, §5]`.
- **Criterios de aceptación**
  - [x] Prueba del VM: con pago por revisar, ventana por cerrar e intención de compra a la vez, la
        fila muestra solo «Pago por revisar» (`Qualify/test_chat_row.py`).
  - [ ] Pantalla a 360 px: ninguna fila ocupa más de un renglón de etiquetas (captura en el PR).
        Solo hay prueba (`test_the_pills_against_one_line_at_360_px`); la captura sigue debiéndose.
  - [x] La fila muestra el glifo del canal, el punto de espera, el nombre, la hora y la vista previa
        con «Tú: » cuando el último mensaje es del negocio (visto en producción, 2026-11-13).
- **Texto para el cliente:** «Pago por revisar», «Responde en {N} min», «Quiere comprar»,
  «Tú: » (ya existen; no se crean nuevos). Reemplazado el 2026-11-13: «Responde en {N} min» →
  «Quedan {N} min para responder» (§6 (vii) 3).
- **Fuera de alcance:** la lista unificada (BU-A3); colores de burbuja (BU-A5).
- **Migración / medición / firma:** no / no / no.

### m-25017859 (BU-A3) · Conversaciones: lista única de chats bajo «Por responder»

> **Fusionada el 2026-11-14 — PR #665 (commit `91b06afa`); ticket RESOLVED, nunca vista en un
> navegador.** Antes, el PR #649 (2026-11-13) agregó a la regla el límite de la ventana de
> Instagram. Entregado: una lista de WhatsApp e Instagram bajo «Por responder» › «Mensajes» con la
> fila compartida y filtro de canal; filtros «Por responder · Todos · Cerrados · Pago por revisar»
> más «Sin responder a tiempo · N»; los contadores del menú, las tarjetas, las pestañas e Inicio
> leen la misma regla que la lista; aviso de chats de Instagram vencidos sin respuesta; explicación
> única del cambio de números; «Quedan {N} min para responder»; en WhatsApp › Chats el filtro
> «Sin leer» pasa a «Por responder» y lista por la regla. Se quitaron la pestaña «WhatsApp» y los
> filtros propios de Instagram («Abiertas», «Cerradas»). Sin migración. Textos y decisiones en
> §6 (vii).
>
> **Límites conocidos:** Inicio todavía cuenta solo Instagram; la lista sigue refrescándose
> mientras la tapa un chat abierto en el celular; no hay índice en
> `whatsapp_outbox (connection_id, wamid)` (2,5–3 s con 3.000 chats, anterior a esta historia); la
> columna propuesta `threads.last_person_reply_at` no se hizo; un chat cuyo mensaje más reciente se
> anula con tres o más páginas cargadas puede salir de la lista hasta cambiar de filtro.

- **Tipo:** Issue · `Feature`, `UI` · **P1** (primer valor visible de la épica) · **M** · dueño `reflex-ui`
- **Depende de:** m-25017843, m-25017844 · **Bloqueada por:** — (decisión (ii) tomada el 2026-11-13); para que muestre chats
  de Instagram de clientes reales, decisión/riesgo (v)
- **Historia:** Como dueño de la tienda de shawarma, quiero ver en una sola lista a los clientes que
  me esperan por WhatsApp o Instagram, ordenados por hora, para no tener que revisar dos pantallas.
- **Propuesta:** lista bajo «Por responder» que lee m-25017843; filtros «Por responder» · «Todos» ·
  «Cerrados» (+ «Pago por revisar · N» solo si hay alguno); filtro de canal solo con dos o más
  canales conectados; al tocar un chat se abre **el chat de hoy de su canal** (enlace profundo)
  `[arq §1.2 «Primer corte…», §4.1 C3; UX §2, §4 punto 5]`. TikTok no se dibuja `[UX §4 punto 6]`.
- **Criterios de aceptación**
  - [x] Prueba del VM: con un solo canal conectado no se dibuja el filtro de canal; con dos, sí
        (la prueba lo decide por chats en dos canales: `test_the_channel_filter_needs_chats_on_two_channels_and_has_no_tiktok`).
  - [x] Prueba del VM: «Pago por revisar · N» aparece solo con N ≥ 1.
  - [ ] Pantalla: tocar un chat de WhatsApp abre su chat en la pantalla de WhatsApp de hoy, y uno de
        Instagram el de Conversaciones, en el mismo hilo (prueba e2e o captura en el PR). Sin ver en
        un navegador.
  - [x] El contador «Por responder» del menú lateral y el total de la lista coinciden (señal 1 de §1):
        prueba con base de datos `test_inbox_counters_db.py`, en los dos canales. La lectura en
        producción del negocio de Bianki sigue pendiente.
  - [x] «Cargar más» trae la página siguiente sin repetir ni saltar chats (prueba con el cursor de m-25017843).
  - [x] Después de abrir un chat desde la lista única, «‹ Por responder» vuelve a la lista única, no a la lista propia del canal (si no, el dueño queda con dos listas, peor que hoy) — prueba e2e o del VM `[revisión UX, puntos 6–7]` (prueba del VM en `Qualify/test_inbox_list.py`).
- **Texto para el cliente:** «Por responder», «Todos», «Cerrados», «Pago por revisar · {N}»,
  «WhatsApp», «Instagram». Lista vacía: «Ya respondiste a todos. Aquí verás a quien te escriba por WhatsApp o Instagram.» `[revisión UX]`.
  Agregados por las decisiones de §6 (vii): «Sin responder a tiempo · {N}»,
  «Quedan {N} min para responder», «{N} chats de Instagram ya no se pueden responder aquí · Ver»,
  «Respóndele desde Instagram», la explicación única con «Entendido».
- **Fuera de alcance:** chat y cuadro de respuesta compartidos (BU-A5, BU-A7); recordar el filtro de
  canal (pregunta abierta `[UX §6.1]`).
- **Migración / medición / firma:** no / no / no.

### m-25017860 (BU-A4) · Chats: medir el contraste del tinte de canal en las burbujas (condición de D2)

- **Tipo:** Issue · `Accesibilidad`, `Documentación` · **P2** · **S** · dueño `ux`
- **Depende de:** — (puede empezar ya) · **Bloqueada por:** —
- **Historia:** Como dueño que lee los chats en el celular al sol del local, quiero que el texto de
  mis mensajes se lea bien en los dos canales, para no equivocarme al revisar lo que mandé.
- **Propuesta:** medir en el navegador, en claro y en oscuro, el contraste del texto gray-12 sobre
  `{canal}-a4` (instagram pink, whatsapp green, tiktok purple) y del degradado de hoy; si el tinte
  no llega a 4,5:1, proponer otro paso de alfa dentro de la misma opción `[UX §3 D2, §1 hallazgo 7,
  §6.5]`.
- **Criterios de aceptación**
  - [ ] Tabla en `docs/ux-chats-unificados.md` (§D2) con la razón de contraste medida por canal y
        tema, el método (herramienta y captura) y el alfa elegido que pasa 4,5:1 para texto de 15 px.
  - [ ] Si ningún alfa pasa, el doc lo dice y la historia BU-A5 queda marcada «necesita al fundador».
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** cambiar CSS (BU-A5).
- **Migración / medición / firma:** no / sí (medición de contraste, no de modelo) / no.

### BU-A5 · Conversaciones: un solo hilo de chat con el color suave de cada canal

> **Sin ticket todavía — espera a m-25017859 y m-25017860 (sin decisión pendiente).**

- **Tipo:** Issue · `Improvement`, `UI`, `Accesibilidad` · **P2** · **L** · dueño `reflex-ui`
- **Depende de:** m-25017859, m-25017860 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero que el chat de WhatsApp y el de Instagram se vean y se usen
  igual, para no aprender dos pantallas.
- **Propuesta:** un solo juego de reglas en `assets/qualify-inbox.css` que lea `T.platform_scale`
  (quitar el degradado de Instagram y el juego verde aparte de WhatsApp); cabecera con «‹ Por
  responder», nombre, canal y hasta cuándo se le puede escribir; «⋯» (`rx.menu`) con Asignar,
  Cerrar chat y Ajustes de este canal; franja plegable del pedido con la tarjeta de hoy adentro
  `[UX §2, §4 puntos 8–9, §5]`.
- **Criterios de aceptación**
  - [ ] Las burbujas enviadas usan el alfa medido en m-25017860 en los dos canales; captura a 360 px en
        claro y en oscuro en el PR.
  - [ ] `grep` en `assets/qualify-inbox.css`: no queda el degradado `purple-9 → pink-9 → orange-9`
        ni las reglas `.q-wa-msg--glass…` aparte.
  - [ ] «Asignar» aparece en «⋯» solo si el negocio tiene más de una persona con acceso (prueba del VM).
  - [ ] La franja del pedido muestra el total y el estado del pago y al abrirse muestra la tarjeta de hoy sin cambios.
- **Texto para el cliente:** «‹ Por responder», «Asignar», «Cerrar chat», «Ajustes de este canal»,
  «Pedido · {N} productos · {total} · Pago por revisar», «Pago recibido», «Pedido listo» `[UX §2]`.
  Línea de ventana: «Puedes escribirle hasta las {hora}» **[supuesto PO, propuesto]**.
- **Fuera de alcance:** cuadro de respuesta (BU-A7); franja «quién responde» (BU-B8).
- **Migración / medición / firma:** no / no / no. Riesgo: `whatsapp_tab_chats.py` (2,6 k líneas) y
  su estado se tocan también en BU-A7, m-25017861, BU-B7, BU-B8: un solo dueño de UI por archivo y en
  serie `[arq §5, último párrafo]`.

### BU-A6 · Bandeja: enviar desde cualquier chat por el canal correcto

> **Sin ticket todavía — m-25017843 ya está fusionada (2026-11-13); puede crearse.**

- **Tipo:** Issue · `Improvement` · **P2** · **M** · dueño `backend`
- **Depende de:** m-25017843 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero que mi respuesta salga por el mismo canal por el que me escribió
  el cliente sin tener que elegirlo, para no equivocarme de canal.
- **Propuesta:** las acciones sobre un hilo (`enviar`, `cerrar`, `asignar`) reciben solo
  `thread_id`; un despachador lee `channel` de la fila **bajo RLS** y llama al servicio del canal;
  `conversation_outbox` y `whatsapp_outbox` siguen intactas `[arq §2.2, §1.3]`.
- **Criterios de aceptación**
  - [ ] Prueba: un envío a un hilo `whatsapp` termina en `whatsapp_outbox` y uno `dm` en
        `conversation_outbox`, con el formato y la clave de idempotencia de hoy.
  - [ ] Prueba: un `thread_id` de otro negocio falla sin escribir nada (RLS); ningún parámetro del
        cliente puede fijar el canal.
  - [ ] Prueba estática de hoy `test_conversations_outbox_sanctity.py` sigue verde (todo envío de
        Instagram lleva `approved_by_user_id`).
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** unir outboxes o workers `[arq §1.3]`; menú automático.
- **Migración / medición / firma:** no / no / no.

### BU-A7 · Conversaciones: un solo cuadro de respuesta que muestra solo lo que el canal puede mandar

> **Sin ticket todavía — espera a BU-A5 y BU-A6; la decisión (iv) solo para usar `orbit_menu` en Instagram.**

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **L** · dueño `reflex-ui`
- **Depende de:** BU-A5, BU-A6 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero el mismo cuadro de respuesta en WhatsApp e Instagram, con las
  herramientas de todos los días a la vista, para contestar rápido sin buscar.
- **Propuesta:** tres renglones: texto; herramientas con icono y nombre (Foto o video · Botones ·
  Mensajes guardados · y en Instagram Archivo, Nota de voz, ❤); «+» · «Sugerir respuesta» ·
  «Enviar». Lo que el canal no puede mandar no se dibuja; la vista solo pregunta «¿se dibuja?» a
  los `can_*` del VM, que salen de `ChannelCapabilities` `[UX §2, §5; arq §2.1]`. El «+» con sus
  5 filas iguales (Tus productos · Tu oferta · Tu menú · Formas de pago · Cómo llegar) y «Fotos y
  videos» fuera del «+» `[UX §2, §4 punto 4]`. Usar `orbit_menu` en Instagram necesita el visto
  bueno del fundador `[UX §6.3; design-system §5.9]` (ver decisión iv).
- **Criterios de aceptación**
  - [ ] Prueba del VM por canal: los `can_*` coinciden con el descriptor; «Sugerir respuesta» no se
        dibuja en WhatsApp mientras BU-A18 no exista.
  - [ ] «Enviar» es el único botón sólido del cuadro (captura en el PR, los dos canales, 360 px).
  - [ ] El «+» tiene las mismas 5 filas en los dos canales; ninguna se dibuja deshabilitada.
- **Texto para el cliente:** «Foto o video», «Botones», «Mensajes guardados», «Archivo», «Nota de
  voz», «Sugerir respuesta», «Enviar», «Tus productos», «Tu oferta», «Tu menú», «Formas de pago»,
  «Cómo llegar» `[UX §2, §3 D5]`.
- **Fuera de alcance:** estado «Enviando…» (BU-A21); sugerencias en WhatsApp (BU-A17/A18).
- **Migración / medición / firma:** no / no / visto bueno del fundador para `orbit_menu` en
  Instagram (decisión iv o al empezar esta historia).

### BU-A8 · Chats: «Mensajes guardados» para WhatsApp e Instagram

> **Sin ticket todavía — espera a BU-A7.**

- **Tipo:** Issue · `Feature` · **P2** · **M** · dueño `backend` (+ `reflex-ui` en el mismo PR si es chico)
- **Depende de:** BU-A7 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero guardar una vez mis respuestas de siempre («¿a qué hora
  abren?», precios) y usarlas en los dos canales, para no escribirlas otra vez.
- **Propuesta:** las «Plantillas» de Instagram (con `{nombre}` y `[precio]`) pasan a ser una sola
  biblioteca para todos los canales y se llaman «Mensajes guardados» `[UX §1 hallazgo 2, §3 D4–D5]`.
  Antes de empezar, verificar si la tabla de plantillas de Instagram tiene el canal en su clave
  `[arq §4.1 C5]`.
- **Criterios de aceptación**
  - [ ] Un mensaje guardado creado desde Instagram aparece en el cuadro de WhatsApp y viceversa
        (prueba del servicio y del VM).
  - [ ] Ningún texto visible dice «Plantillas» para esta biblioteca (`grep` en `Qualify/`); el
        «Mensaje aprobado» de WhatsApp conserva su nombre.
  - [ ] Prueba de aislamiento por negocio.
- **Texto para el cliente:** «Mensajes guardados»; «Mensaje aprobado» se queda `[UX §3 D5]`.
- **Fuera de alcance:** mensajes aprobados de WhatsApp (otra cosa).
- **Migración:** no según la nota; **sí** si la clave de la tabla incluye el canal (verificar) ·
  **Medición / firma:** no / no.

### m-25017861 (BU-A9) · Chats: «Ajustes de chats» aparte de los mensajes

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **L** · dueño `reflex-ui`
- **Depende de:** — (en paralelo a m-25017844…BU-A5 `[arq §4.1 C6]`) · **Bloqueada por:** la revisión de sus textos contra la condición 3 de m-24789557 (decisión (vi))
- **Historia:** Como dueño, quiero preparar mis chats (mi menú, preguntas iniciales,
  mensajes guardados) en un lugar distinto del que uso para contestar, para que la pantalla de
  mensajes tenga menos pestañas.
- **Propuesta:** «Ajustes de chats» en Atiende con «Para todos tus chats» (Mensajes guardados ·
  Formas de pago · Cómo llegar), «WhatsApp» (el menú, hoy «Respuesta automática» · Preguntas iniciales) e
  «Instagram» (Preguntas iniciales); sacar la configuración de WhatsApp de la pantalla de mensajes
  `[UX §2, §3 D1]`. Rutas propuestas `/chats/ajustes/whatsapp` y `/chats/ajustes/instagram`
  (nombres a decidir `[UX §5]`).
- **Criterios de aceptación**
  - [ ] Pantalla: la pantalla de mensajes de WhatsApp ya no muestra pestañas de configuración
        (captura antes/después).
  - [ ] Las preguntas iniciales de los dos canales muestran la línea «Lo que tu cliente puede tocar
        al abrir el chat».
  - [ ] Ninguna función de configuración de hoy se pierde: lista de lo que había y dónde quedó, en el PR.
  - [ ] **Antes de empezar:** los textos de esta historia se revisan contra la condición 3 de m-24789557 con la decisión (vi) ya tomada.
- **Texto para el cliente:** «Respuesta automática» como nombre de la entrada: **pendiente de la decisión de nombres del fundador (condición 3 de m-24789557, decisión (vi) de §6); tabla de textos que pueden chocar en `[arq §3.3, «Contraste con las tres condiciones», punto 3]`**; propuesta de la revisión UX: «Tu menú de bienvenida». Sin choque: «Ajustes de chats», «Para todos tus chats»,
  «Preguntas iniciales», «Lo que tu cliente puede tocar al abrir el chat» `[UX §2, §3 D1, D5]`.
- **Fuera de alcance:** «Tu número» (BU-A10); encendido por canal del menú (BU-B7).
- **Migración / medición / firma:** no / no / no.

### BU-A10 · Conexiones: «Tu número» de WhatsApp pasa a «Tus redes»

> **Sin ticket todavía — espera a m-25017861.**

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **S** · dueño `reflex-ui`
- **Depende de:** m-25017861 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero ver en un solo lugar si mi WhatsApp, mi Instagram y mi Facebook
  están conectados, para saber dónde arreglar una conexión.
- **Propuesta:** el estado de conexión del número va a «Tus redes» (`/connections`) con los estados
  de `docs/design-system.md` §7.3 `[UX §1 hallazgo 6, §3 D1]`.
- **Criterios de aceptación**
  - [ ] «Tus redes» muestra el número de WhatsApp con «Conectada», «Desconectada» o «Sin acceso».
  - [ ] Ya no hay pestaña «Tu número» (`grep` y captura); un enlace viejo redirige a «Tus redes».
- **Texto para el cliente:** «Tus redes», «Conectada», «Desconectada», «Sin acceso».
- **Fuera de alcance:** formas de pago y «Cómo llegar» (BU-A14/A15).
- **Migración / medición / firma:** no / no / no.

### BU-A11 · Navegación: un solo nombre por cosa y redirecciones a la bandeja

> **Sin ticket todavía — espera a m-25017859 y m-25017861.**

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **M** · dueño `reflex-ui`
- **Depende de:** m-25017859, m-25017861 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero que cada cosa tenga el mismo nombre en los dos canales y que los
  avisos me lleven al chat correcto, para no perderme.
- **Propuesta:** nombres de D5 (Preguntas iniciales, Botones, Mensajes guardados, Enviar) en toda la
  app; `/whatsapp` → `/responder?tab=mensajes&canal=whatsapp`; enlaces de notificaciones y del menú
  lateral a la bandeja; el contador de «Por responder» suma lo que hoy es el de «WhatsApp»
  `[arq §4.1 C7; UX §3 D5, §5]`.
- **Criterios de aceptación**
  - [ ] `grep` en `Qualify/`: no quedan «Atajos» ni «Respuestas rápidas» en textos visibles.
  - [ ] Prueba de rutas: `/whatsapp` y un enlace viejo a un chat terminan en el mismo chat dentro
        de la bandeja.
  - [ ] Menú lateral: «Por responder» queda encendido en la lista y dentro de cada chat.
- **Texto para el cliente:** «Preguntas iniciales», «Botones», «Mensajes guardados», «Enviar».
- **Fuera de alcance:** «Promociones» (BU-A12).
- **Migración / medición / firma:** no / no / no.

### m-25017862 (BU-A12) · Menú: «Promociones por WhatsApp» junto a «Anuncios»

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **S** · dueño `reflex-ui`
- **Depende de:** — · **Bloqueada por:** —
- **Historia:** Como dueño, quiero encontrar las promociones por WhatsApp junto a los anuncios,
  porque las dos sirven para llegar a quien hoy no me escribe.
- **Propuesta:** entrada propia en la zona Publica; Atiende pierde «WhatsApp» `[UX §3 D3]`.
- **Criterios de aceptación**
  - [ ] Menú lateral: «Promociones por WhatsApp» aparece junto a «Anuncios», con Enviadas ·
        Mensajes aprobados · Clientes que aceptaron, sin cambios de función.
  - [ ] El total de entradas del menú lateral no crece `[UX §3 D3, «costo aceptado»]`.
- **Texto para el cliente:** «Promociones por WhatsApp».
- **Fuera de alcance:** cambios a cómo se envían las promociones.
- **Migración / medición / firma:** no / no / no.

### m-25026457 (BU-A13) · Conversaciones: cerrar y reabrir chats de Instagram

> **Fusionada y en producción — PR #653 (2026-11-13, commit `ec0d79fc`); ticket RESOLVED: «Cerrar»
> nunca se vio funcionar en un navegador.** Ticket creado el 2026-11-13 por la decisión «Ventana +
> cerrar chat» (§6 (vii) 1). Entregado: «Cerrar» / «Reabrir» y marca «Cerrado» en la cabecera, en el
> mismo lugar que WhatsApp; los contadores dejan de contar los cerrados. El cierre no procede si
> llegó un mensaje del cliente más nuevo que el que mostraba la pantalla («{nombre} te acaba de
> escribir. Lee su mensaje antes de cerrar.»); solo un mensaje realmente nuevo reabre un chat
> cerrado (uno repetido no). En la pantalla de Instagram los filtros quedaron «Abiertas» y
> «Cerradas» (§6 (vii) 2), que la lista única de m-25017859 quitó después. Las mismas dos
> protecciones en WhatsApp quedan sin ticket (§5).

- **Tipo:** Issue · `Feature` · **P1** en Meegle (el borrador decía P2) · **M** · dueño `backend` (+ `reflex-ui`)
- **Depende de:** m-25017843 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero cerrar un chat de Instagram ya atendido como hago en WhatsApp,
  para que solo me quede a la vista lo pendiente.
- **Propuesta:** «Cerrar chat» / «Reabrir» en Instagram sobre `threads.status`; misma regla de
  reapertura al llegar un mensaje en los dos canales (verificar primero qué hace hoy WhatsApp en
  `chats.py` y `handler.py`) `[arq §2.3 último párrafo, §4.1 C9]`.
- **Criterios de aceptación**
  - [x] Prueba: un chat de Instagram cerrado sale de «Por responder» y aparece en «Cerrados».
  - [x] Prueba: un mensaje nuevo del cliente reabre el chat en los dos canales (o la regla que se
        decida, escrita en el PR con lo que se encontró en WhatsApp). Lo hallado en WhatsApp (PR
        #653): cierra sin comprobar si entró un mensaje y reabre con cualquier entrante, incluso
        repetido; corregirlo queda sin ticket.
- **Texto para el cliente:** «Cerrar chat», «Reabrir». Entregado: «Cerrar», «Reabrir», «Cerrado»,
  «{nombre} te acaba de escribir. Lee su mensaje antes de cerrar.».
- **Fuera de alcance:** asignar chats.
- **Migración:** no (`threads.status` ya admite `closed`) · **Medición / firma:** no / no.

### BU-A14 · Identidad de marca: «Cómo llegar» pasa a ser dato del negocio

> **Sin ticket todavía — espera a m-25017861.**

- **Tipo:** Issue · `Deuda técnica` · **P2** · **M** · dueño `backend`
- **Depende de:** m-25017861 · **Bloqueada por:** —
- **Historia:** Como dueño, quiero cargar una sola vez cómo llegar a mi local y usarlo en cualquier
  chat, para no repetirlo por canal.
- **Propuesta:** mover `whatsapp_phone_numbers.location_*` a la marca con relleno; las formas de pago
  ya son por marca (`brand_payment_methods`, 0135) `[arq §4.1 C10]`.
- **Criterios de aceptación**
  - [ ] Migración reversible, con RLS en la misma revisión y relleno de los números existentes
        (`qualify-migration`); prueba de subida y bajada.
  - [ ] Prueba: el «Cómo llegar» que manda hoy WhatsApp sale igual después de la migración.
- **Texto para el cliente:** ninguno nuevo.
- **Fuera de alcance:** pantallas (BU-A15).
- **Migración:** **sí** · **Medición / firma:** no / no.

### BU-A15 · Chats: formas de pago y «Cómo llegar» para todos los canales

> **Sin ticket todavía — espera a BU-A14 y BU-A7.**

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **M** · dueño `reflex-ui`
- **Depende de:** BU-A14, BU-A7 · **Bloqueada por:** —
- **Historia:** Como dueño de un local de comida, quiero mandar mis formas de pago y cómo llegar
  también por Instagram, para cerrar pedidos que llegan por ahí.
- **Propuesta:** las dos secciones en «Ajustes de chats › Para todos tus chats»; el «+» de
  Instagram las manda `[UX §1 hallazgo 4, §3 D4]`.
- **Criterios de aceptación**
  - [ ] Pantalla: «Formas de pago» y «Cómo llegar» se editan en «Para todos tus chats» y ya no en
        WhatsApp.
  - [ ] Desde un chat de Instagram, el «+» manda las dos (prueba con una cuenta con rol en la app;
        captura en el PR).
- **Texto para el cliente:** «Formas de pago», «Cómo llegar», «Para todos tus chats».
- **Fuera de alcance:** el paso de pago del menú automático en Instagram (BU-B6).
- **Migración / medición / firma:** no / no / no.

### m-25017863 (BU-A16) · Medición: «Sugerir respuesta» con chats reales de WhatsApp

- **Tipo:** Issue · `Testing` · **P2** · **M** · dueño `datasci`
- **Depende de:** — (puede empezar ya `[arq §4.1]`) · **Bloqueada por:** —
- **Historia:** Como fundador, quiero saber cuánto cuesta y qué tan útil es «Sugerir respuesta» en
  chats de WhatsApp antes de encenderlo, para decidir su tope y su lugar en el plan.
- **Propuesta:** conjunto anonimizado de chats reales de WhatsApp de Bianki; reutilizar
  `conversations/suggest.py` con un adaptador de registros; tasa de borradores usables y de
  `needs_review`, costo medido por toque `[arq §4.1 C11 en detalle]`.
- **Criterios de aceptación**
  - [ ] Documento en `docs/modelos-generativos/` y ficha del modelo actualizada el mismo turno
        (`qualify-measure`), con el comando para repetirlo.
  - [ ] Costo por toque medido (no estimado) y peor caso, listos para la decisión (iii).
  - [ ] Los datos de clientes en el conjunto están anonimizados (sin teléfonos ni nombres).
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** encender la función para un negocio.
- **Migración / medición / firma:** no / **sí** / no.

### BU-A17 · WhatsApp: «Sugerir respuesta» en el servicio, con tope diario y apagado por defecto

> **Sin ticket todavía — espera a m-25017863 y la decisión (iii) para encenderlo.**

- **Tipo:** Issue · `Feature` · **P2** · **M** · dueño `backend`
- **Depende de:** m-25017863 · **Bloqueada por:** decisión (iii) **para encenderlo** en cualquier
  negocio (se puede construir apagado)
- **Historia:** Como dueño que recibe pedidos por WhatsApp, quiero un borrador de respuesta que yo
  reviso antes de enviar, para contestar más rápido entre cliente y cliente.
- **Propuesta:** adaptador de registros de WhatsApp a `ThreadRecord`/`MessageRecord`; contexto de
  ventana, menú y pedido; función propia del libro de consumo `respuesta-whatsapp`; tope diario por
  negocio antes de la llamada; bandera por negocio apagada por defecto `[arq §4.1 C11]`. Sigue
  siendo asistido: el borrador nunca se envía solo `[arq §3.3, último renglón]`.
- **Criterios de aceptación**
  - [ ] Prueba: con la bandera apagada no se hace ninguna llamada pagada.
  - [ ] Prueba: con el tope del día alcanzado la llamada se rechaza antes de enviarse.
  - [ ] Prueba: cada llamada deja una fila en el libro de consumo con la función `respuesta-whatsapp`.
  - [ ] Prueba: el borrador entra al cuadro de respuesta, nunca a `whatsapp_outbox` sin el toque de «Enviar».
- **Texto para el cliente:** mensaje al alcanzar el tope: pendiente de la decisión (iii).
- **Fuera de alcance:** el botón (BU-A18); precio o lugar en el plan.
- **Migración / medición / firma:** no / sí (heredada de m-25017863) / decisión (iii) para encender.

### BU-A18 · WhatsApp: botón «Sugerir respuesta» en el chat

> **Sin ticket todavía — espera la decisión (iii).**

- **Tipo:** Issue · `Feature`, `UI` · **P2** · **S** · dueño `reflex-ui`
- **Depende de:** BU-A7, BU-A17 · **Bloqueada por:** decisión (iii)
- **Historia:** la de BU-A17, del lado de la pantalla.
- **Criterios de aceptación**
  - [ ] Con la bandera del negocio apagada el botón no se dibuja (prueba del VM).
  - [ ] Con la bandera encendida, el borrador llega al cuadro de texto y no se envía hasta tocar «Enviar».
- **Texto para el cliente:** «Sugerir respuesta».
- **Migración / medición / firma:** no / no / decisión (iii).

### m-25017864 (BU-A19) · Stickers: «Volver al chat» en el último paso de crearlos

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **S** · dueño `reflex-ui`
- **Depende de:** — · **Bloqueada por:** —
- **Evidencia:** resto de las revisiones UX de esta semana, asignado a esta épica por el fundador
  (2026-11-12). Patrón ya usado: `BACK_TO_CHAT` en `whatsapp_location_vm.py:57` y
  `whatsapp_payments_vm.py:87`.
- **Historia:** Como dueño que fue a crear stickers de temporada desde un chat, quiero volver al
  mismo chat al terminar, para mandarlos sin buscar al cliente otra vez.
- **Criterios de aceptación**
  - [ ] Al terminar de crear stickers llegando desde un chat, el último paso muestra «Volver al chat»
        y lleva al mismo chat (prueba con `return_to`).
  - [ ] Si se llegó desde Tu marca, el enlace no aparece.
- **Texto para el cliente:** «Volver al chat» (el doc UX §2 dice «Volver a tus chats»; propongo el
  de la app, que ya existe; ver §8).
- **Fuera de alcance:** cambiar el flujo de creación.
- **Migración / medición / firma:** no / no / no.

### m-25017865 (BU-A20) · Stickers: «Ver todos en Tu marca» al pie del selector del chat

- **Tipo:** Issue · `Improvement`, `UI` · **P3** · **S** · dueño `reflex-ui`
- **Depende de:** — · **Bloqueada por:** —
- **Evidencia:** igual que m-25017864.
- **Historia:** Como dueño, quiero ir desde el selector de stickers del chat a todos mis stickers,
  para gestionarlos donde se crean y se aprueban.
- **Criterios de aceptación**
  - [ ] Al pie del selector aparece «Ver todos en Tu marca» y lleva a Tu marca con un camino de
        vuelta al chat (prueba del VM o e2e).
- **Texto para el cliente:** «Ver todos en Tu marca».
- **Migración / medición / firma:** no / no / no.

### BU-A21 · Conversaciones: «Enviando…» → «Enviado» en la burbuja (hipótesis)

> **Sin ticket todavía — hipótesis; espera a BU-A5 y m-25017850.**

- **Tipo:** Issue · `Improvement`, `UI` · **P3** · **M** · dueño `reflex-ui`
- **Depende de:** BU-A5; para Instagram, el Issue aparte m-25017850 (marca de «enviado») ·
  **Bloqueada por:** —
- **Evidencia:** **hipótesis**, sin evidencia todavía: sugerencia de la revisión UX del PR #608
  («para que el dueño no toque "Enviar" dos veces») `[PR #608, «Sugerencias de UX»]`. Validar en
  la prueba con el dueño de Bianki antes de construir.
- **Historia:** Como dueño, quiero ver que mi mensaje está saliendo y cuándo salió, para no
  mandarlo dos veces.
- **Criterios de aceptación**
  - [ ] La burbuja muestra «Enviando…» mientras la fila de la outbox está pendiente y «Enviado»
        cuando se marcó enviada, en los dos canales (prueba del VM con los dos estados).
  - [ ] Un envío fallido muestra «No se pudo enviar» **[supuesto PO, propuesto]**.
- **Texto para el cliente:** «Enviando…», «Enviado», «No se pudo enviar» (este último propuesto).
- **Migración / medición / firma:** no / no / no.

### BU-A22 · Instagram: «Fotos y videos» en el chat antes de la unificación (condicionada)

> **Sin ticket todavía — espera la decisión (iv); no se crea si elige esperar.**

- **Tipo:** Issue · `Improvement`, `UI` · **P3** · **M** · dueño `reflex-ui`
- **Depende de:** — · **Bloqueada por:** decisión (iv). **No se crea** si el fundador elige esperar
  a BU-A7.
- **Historia:** Como dueño, quiero mandar fotos y videos de mis piezas por Instagram como ya lo
  hago por WhatsApp, para mostrar el producto en la conversación.
- **Criterios de aceptación**
  - [ ] Desde un chat de Instagram, «Foto o video» abre el paso «¿De dónde?» (Tus piezas · De tu
        celular · stickers y videos de marca) y manda solo los tipos de `REPLY_MEDIA_TYPES`.
- **Texto para el cliente:** «Foto o video», «¿De dónde?», «Tus piezas», «De tu celular» `[UX §2]`.
- **Migración / medición / firma:** no / no / **sí** (decisión iv, `orbit_menu` fuera de WhatsApp).

## 4. Pista B — «Respuesta automática en todos los canales»

Base: opción (b) de la nota — **un motor de menú neutral con un traductor por canal; un menú por
negocio; los ajustes por canal se limitan a encendido/apagado y textos de presentación**, nunca a
otro grafo `[arq §3.2]`. El esquema y el motor ya son casi independientes del canal; lo atado a
WhatsApp es la publicación al número, el traductor a la Cloud API, la entrada desde el webhook y
el nombre de las tablas `[arq §3.1, «Conclusión»]`. Cortes de origen M1–M7 `[arq §4.2]`.

**Dónde partí cortes, y por qué**

| Corte | Qué hice | Por qué |
|---|---|---|
| M1 | Partido en m-25017846 (puntos 1–2: transacción única + candado) y m-25017866 (puntos 3–4 + métricas) | Cuatro arreglos en el código que hoy cobra pedidos reales: dos PR más chicos se revisan mejor; m-25017866 puede necesitar migración (estado `cancelled`) y m-25017846 no |
| M3 | Partido en BU-B4 (destinos del menú por canal + estado neutral) y BU-B5 (`kind='automation'` en `conversation_outbox`) | Solo BU-B5 quita la garantía deliberada de Instagram y necesita el ADR 48 (número provisional: el PR #618 también reclama el 48; el ADR toma el siguiente número libre al escribirse) escrito (transcripción de m-24789557), la decisión (i-c) y `security-review` `[arq §3.3, §4.2 M3]`; BU-B4 es un cambio de esquema para WhatsApp con relleno que no la toca |

### m-25017846 (BU-B1) · WhatsApp: el menú automático guarda su paso y su respuesta juntos, una conversación a la vez

- **Tipo:** Issue · `Bug` (pérdida aceptada en el código) · **P1** (protege pedidos reales de Bianki;
  bloquea m-25017868) · **M** · dueño `backend`
- **Depende de:** — (**puede empezar ya** `[arq §4.2 M1]`) · **Bloqueada por:** —
- **Qué pasa:** el estado del menú se guarda en una transacción y cada fila de la outbox en otra; la
  repetición del webhook se salta el paso porque el mensaje ya está, y el propio docstring acepta
  perder «a lo sumo una respuesta automática» (`handler.py:66-69, 560-582, 17-19`). Además el
  estado se lee y escribe sin candado: con dos trabajadores, dos mensajes seguidos del mismo
  cliente pisan el estado; hoy no pasa porque producción corre una réplica de `webhook-worker`
  `[arq §3.5 puntos 1–2]`.
- **Historia:** Como dueño de un local que toma pedidos con el menú automático, quiero que ningún
  cliente quede sin respuesta del menú por una caída, para no perder pedidos sin enterarme.
- **Arreglo:** estado + outbox en **una** transacción; `pg_advisory_xact_lock` por `thread_id` o
  `SELECT … FOR UPDATE` del estado dentro de esa transacción `[arq §3.5]`.
- **Criterios de aceptación**
  - [ ] Prueba (`-m db`): una falla simulada entre el paso del motor y la escritura de la outbox deja
        el cursor sin avanzar; la repetición del webhook produce la respuesta una sola vez.
  - [ ] Prueba (`-m db`): dos mensajes del mismo cliente procesados en dos sesiones concurrentes
        terminan con el estado del segundo aplicado sobre el del primero (sin pisarse).
  - [ ] Las pruebas que hoy cubren repetición, cambio de versión y confirmación repetida siguen verdes
        (`tests/test_whatsapp_handler.py:241, :456, :621`).
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** extraer el motor (BU-B3); Instagram.
- **Migración / medición / firma:** no / no / no.

### m-25017866 (BU-B2) · WhatsApp: si el dueño toma el control o un envío automático falla, el chat vuelve al dueño

- **Tipo:** Issue · `Bug` · **P1** · **M** · dueño `backend`
- **Depende de:** m-25017846 (mismos archivos) · **Bloqueada por:** —
- **Qué pasa:** (3) respuestas automáticas ya encoladas salen aunque el dueño haya tocado «Tomar el
  control»: la outbox no mira la pausa al enviar (`whatsapp/outbox.py:951-964`); (4) un rechazo de
  Meta deja la fila `failed` pero el cursor avanzó y el hilo no se entrega a nadie; el cliente ve
  silencio y el chat podría no aparecer como «por responder» [a verificar con una prueba]. No hay
  métrica de entregas a persona ni de fallos automáticos por hilo `[arq §3.5 puntos 3–4, último
  párrafo]`.
- **Historia:** Como dueño, quiero que cuando respondo yo el menú no siga mandando mensajes, y que
  si el menú no pudo contestar el chat me aparezca para atenderlo, para que el cliente nunca quede
  esperando.
- **Arreglo:** el remitente descarta (`cancelled`) las filas `automation` de un hilo pausado
  cuando la pausa es posterior a su `created_at` (lectura del PO de `[arq §3.5 punto 3]`, ver §8
  punto 5); un fallo terminal de una fila
  `automation` pausa el hilo con motivo «no se pudo enviar» y lo devuelve a «Por responder»;
  contadores de entregas a persona y de fallos automáticos por hilo `[arq §3.5]`.
- **Criterios de aceptación**
  - [ ] Prueba: fila `automation` encolada, luego pausa, luego tick del worker → la fila queda
        `cancelled` y no se llama a la Cloud API.
  - [ ] Prueba: fila `automation` que Meta rechaza → hilo pausado con motivo y presente en «Por
        responder» (predicado de m-25017843 o el de hoy si m-25017843 no está).
  - [ ] Métrica o log estructurado con las dos cuentas, consultable en producción (comando en el PR);
        habilita la señal 2 de §1.
- **Texto para el cliente:** píldora en la fila: «Tu menú no pudo responder» — **pendiente de la decisión de nombres del fundador (condición 3 de m-24789557, decisión (vi) de §6); tabla de textos que pueden chocar en `[arq §3.3, «Contraste con las tres condiciones», punto 3]`**. Propuesta de la revisión UX: «Tu menú no le llegó: respóndele tú».
  - [ ] **Antes de empezar:** los textos de esta historia se revisan contra la condición 3 de m-24789557 con la decisión (vi) ya tomada.
- **Fuera de alcance:** reanudar solo el menú tras N horas (decisión (i-a) de §6).
- **Migración:** **verificar** el CHECK de estados de `whatsapp_outbox`; si `cancelled` no existe,
  sí `[arq §4.2 M1]` · **Medición / firma:** no / no.

### m-25017868 (BU-B3) · Respuesta automática: motor de menú independiente del canal, con «Hablar con alguien» obligatorio

- **Tipo:** Issue · `Deuda técnica` · **P2** · **M** · dueño `backend`
- **Depende de:** m-25017846, m-25017866 · **Bloqueada por:** —
- **Historia:** Como fundador, quiero que el menú que ya funciona en WhatsApp viva en un motor que
  sirva a cualquier canal, para llevarlo a Instagram (y después a TikTok) sin copiarlo.
- **Qué hay que hacer:** mover esquema y motor a `qualify_api/chat_automation/` con un `Inbound`
  neutral; el traductor de WhatsApp es el `outbox_payload` de hoy; la validación pasa a «límites de
  cada canal encendido», comprobada por su traductor al publicar `[arq §3.2, §4.2 M2]`. La nota corregida agrega a este corte la condición 2 de m-24789557 como regla del esquema: una opción visible de entrega a persona («Hablar con alguien») alcanzable desde el inicio, y el editor no la deja quitar `[arq §3.3 «Contraste…» punto 2, §4.2 M2]`.
- **Criterios de aceptación**
  - [ ] Todas las pruebas de hoy del motor y del handler de WhatsApp pasan sin cambiar sus aserciones.
  - [ ] Prueba: un menú sin una opción de entrega a persona alcanzable desde el inicio no se puede publicar; prueba del editor: la opción no se puede borrar.
  - [ ] Antes de mergear: cuántos menús publicados hoy no cumplen la regla (consulta en el PR), para no apagar ninguno en producción sin avisar.
  - [ ] `grep`: el paquete `chat_automation/` no importa nada de `qualify_api.whatsapp`.
  - [ ] Ningún menú publicado hoy deja de validar (prueba con las definiciones de prueba existentes).
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** Instagram; cambios de esquema.
- **Migración / medición / firma:** no / no / no.

### BU-B4 · Respuesta automática: un menú por negocio publicado en uno o varios canales

> **Sin ticket todavía — espera a m-25017868 (sin decisión pendiente: el menú en Instagram ya está decidido en m-24789557).**

- **Tipo:** Issue · `Deuda técnica` · **P2** · **M** · dueño `backend`
- **Depende de:** m-25017868 · **Bloqueada por:** — (no toca la garantía de Instagram; ver §8)
- **Historia:** Como dueño, quiero tener un solo menú y decidir en qué canales responde, para no
  mantener dos.
- **Qué hay que hacer:** tabla de destinos del menú (`menu_id`, `channel`, `connection_id` o
  `phone_number_row_id`, `enabled`, textos de presentación) con «un menú publicado por destino»,
  RLS en la misma revisión y relleno de los números de hoy; renombrar `whatsapp_thread_state` a un
  nombre neutral (las políticas siguen a la tabla) `[arq §3.6]`.
- **Criterios de aceptación**
  - [ ] Migración reversible con RLS y relleno; prueba de subida y bajada (`qualify-migration`).
  - [ ] Después de la migración, el menú publicado de Bianki en WhatsApp sigue respondiendo igual
        (prueba del handler con los datos rellenados).
  - [ ] Prueba de aislamiento por negocio sobre la tabla de destinos.
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** ampliar la concesión del rol del webhook a hilos `dm` (va en BU-B5).
- **Migración:** **sí** · **Medición / firma:** no / no.

### BU-B5 · Conversaciones: envíos automáticos aprobados por la versión publicada del menú

> **Sin ticket todavía — espera el ADR 48 escrito por `principal-architect` (transcripción de m-24789557) y la decisión (i-c).**

- **Tipo:** Issue · `Feature` · **P2** · **M** · dueño `backend`
- **Depende de:** BU-B4 · **Bloqueada por:** ADR 48 escrito (transcripción, no firma nueva) y la decisión (i-c) (si los textos fijos de Qualify y los armados con datos del dueño cuentan como aprobados al publicar)
- **Historia:** Como dueño, quiero que publicar mi menú cuente como mi aprobación de lo que el menú
  manda por Instagram, para que responda solo lo que yo escribí.
- **Qué hay que hacer:** `kind='automation'` en `conversation_outbox` con `approved_by_user_id` nulo
  **solo** para ese tipo y `menu_version_id` obligatorio (CHECK); procedencia `menu_version_id` +
  `node_id` en cada fila; concesión de INSERT al rol del webhook limitada a ese tipo; ampliar la
  concesión del estado neutral a hilos `dm` `[arq §3.3, §3.6]`.
- **Criterios de aceptación**
  - [ ] Prueba (`-m db`): una fila `kind='automation'` sin `menu_version_id` se rechaza; una fila de
        otro tipo sin `approved_by_user_id` se sigue rechazando.
  - [ ] Prueba (`-m db`): el rol del webhook no puede insertar filas de otro tipo.
  - [ ] `test_conversations_outbox_sanctity.py` actualizada para permitir solo esa excepción, con un
        comentario que cita el ADR 48.
  - [ ] `security-review` hecha antes de mergear, con su resultado en el PR `[arq §3.3]`.
  - [ ] Prueba estática: ni `suggest.py` ni ningún generador escriben `kind='automation'`; solo versiones publicadas, solo texto, botones, listas, QR o fotos del catálogo `[arq §3.3 «¿Algo del mecanismo…»]`.
- **Texto para el cliente:** ninguno.
- **Fuera de alcance:** generativo («Sugerir respuesta») sigue asistido sin excepción `[arq §3.3]`.
- **Migración:** **sí** · **Medición:** no · **Firma:** ADR 48 escrito (transcripción de m-24789557) + decisión (i-c).

### BU-B6 · Instagram: el menú automático responde en Instagram Direct

> **Sin ticket todavía — espera a BU-B5, las decisiones (i-b) y (vi) para el aviso, y el riesgo (v) para clientes reales.**

- **Tipo:** Issue · `Feature` · **P2** · **L** · dueño `backend`
- **Depende de:** BU-B5 · **Bloqueada por:** decisión (i-b) (aviso al cliente con «automático») y (vi) (nombres); para clientes reales, riesgo (v) (Advanced Access)
- **Historia:** Como dueño de la tienda de shawarma, quiero que mi menú tome pedidos también por
  Instagram, para atender a esos clientes aunque esté ocupado.
- **Qué hay que hacer:** traductor e integración de Instagram: entrada desde el webhook de
  `conversations` (`choice_kind`/`choice_payload`), botones y listas como respuestas rápidas (o
  plantilla de botones si el texto pasa el límite), productos por categorías como respuestas
  rápidas, resumen del pedido, paso de pago como imagen + texto, preguntas iniciales, entrega a una
  persona, aviso de automatización. Sin carrusel ni menú persistente `[arq §3.2 «Primer corte…»,
  tabla de traducción; §4.2 M4]`.
- **Criterios de aceptación**
  - [ ] Pruebas del traductor: ninguna acción del motor produce un mensaje fuera de los límites de
        Instagram (13 respuestas rápidas de 20 caracteres; plantilla de botones ≤ 3, texto ≤ 640)
        `[arq §3.4]`.
  - [ ] **Prueba en vivo** con una cuenta con rol en la app antes de mergear (ADR 25), documentada en
        el PR: pedido completo hasta el paso de pago y una entrega a persona (señal 3 de §1).
  - [ ] El camino a una persona se puede demostrar (requisito de Meta `[arq §3.4]`).
  - [ ] Con el destino de Instagram apagado, nada cambia en ese canal (prueba).
- **Texto para el cliente:** aviso al cliente final, borrador del arquitecto: «Te responde el menú
  automático de {negocio}» `[arq §5 punto 6]` — **pendiente de la decisión de nombres del fundador (condición 3 de m-24789557, decisión (vi) de §6); tabla de textos que pueden chocar en `[arq §3.3, «Contraste con las tres condiciones», punto 3]`**, y de la decisión (i-b). Propuesta de la revisión UX: «Este es el menú de {negocio}. Toca "Hablar con alguien" cuando quieras.»
  - [ ] **Antes de empezar:** los textos de esta historia se revisan contra la condición 3 de m-24789557 con la decisión (vi) ya tomada.

- **Fuera de alcance:** carrusel (BU-B9); menú persistente; comandos tipo `/menu`.
- **Migración / medición / firma:** no / no / (i-b), (vi).

### BU-B7 · Chats: el menú en «Ajustes de chats», encendido por canal

> **Sin ticket todavía — espera a m-25017861, BU-B4 y la decisión de nombres (vi).**

- **Tipo:** Issue · `Feature`, `UI` · **P2** · **M** · dueño `reflex-ui`
- **Depende de:** m-25017861, BU-B4 (Instagram, también BU-B6) · **Bloqueada por:** decisión (vi), nombres
- **Historia:** Como dueño, quiero ver mi menú automático y decidir en qué canal responde, y ver
  cómo le llega al cliente en cada uno, para confiar en lo que va a recibir.
- **Propuesta:** el menú (hoy «Respuesta automática») dentro de «Ajustes de chats», encendido por canal y vista
  «Así le llega» por canal `[arq §4.2 M5; UX §2]`.
- **Criterios de aceptación**
  - [ ] El interruptor de Instagram no se dibuja mientras BU-B6 no esté (regla «no se dibuja»).
  - [ ] «Así le llega» muestra, para el mismo nodo, la versión WhatsApp (botones) y la de Instagram
        (respuestas rápidas) cuando las dos existen.
  - [ ] Apagar un canal cambia solo el destino de ese canal (prueba del servicio).
- **Texto para el cliente:** «Así le llega». El nombre de la sección («Respuesta automática») y el del interruptor por canal: **pendiente de la decisión de nombres del fundador (condición 3 de m-24789557, decisión (vi) de §6); tabla de textos que pueden chocar en `[arq §3.3, «Contraste con las tres condiciones», punto 3]`**. Propuesta de la revisión UX: «Tu menú de bienvenida», con «Usar en WhatsApp» / «Usar en Instagram».
  - [ ] **Antes de empezar:** los textos de esta historia se revisan contra la condición 3 de m-24789557 con la decisión (vi) ya tomada.
- **Migración / medición / firma:** no / no / (vi).

### BU-B8 · Conversaciones: franja «quién responde» en el chat, también en Instagram

> **Sin ticket todavía — espera a BU-A5 y BU-B6, y la prueba del nombre «Responder yo» con el dueño.**

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **M** · dueño `reflex-ui`
- **Depende de:** BU-A5, BU-B6 (para Instagram; para WhatsApp basta BU-A5) · **Bloqueada por:** la
  prueba del nombre «Responder yo» vs «Tomar el control» con el dueño de Bianki `[UX §6.2]`
- **Historia:** Como dueño, quiero ver justo encima de donde escribo si me está contestando el menú
  o yo, y cambiarlo con un toque, para no pisarme con el menú.
- **Criterios de aceptación**
  - [ ] Con el menú atendiendo, la franja muestra el texto que salga de la decisión (vi) + «Responder yo»;
        con el dueño, «Estás respondiendo tú · Devolver al menú» (prueba del VM en los dos canales).
  - [ ] «Tomar el control» ya no está en la cabecera del chat `[UX §4 punto 8]`.
  - [ ] **Antes de empezar:** los textos de esta historia se revisan contra la condición 3 de m-24789557 con la decisión (vi) ya tomada.
- **Texto para el cliente:** «Está respondiendo tu menú automático» — **pendiente de la decisión de nombres del fundador (condición 3 de m-24789557, decisión (vi) de §6); tabla de textos que pueden chocar en `[arq §3.3, «Contraste con las tres condiciones», punto 3]`**; propuesta de la revisión UX: «Este cliente está usando tu menú · Responder yo». «Responder yo», «Estás respondiendo tú», «Devolver al menú» `[UX §2]` — el nombre «Responder yo» se prueba antes.
- **Migración / medición / firma:** no / no / no (sí la prueba con el dueño).

### BU-B9 · Instagram: carrusel de productos con foto en el menú automático

> **Sin ticket todavía — espera a BU-B6.**

- **Tipo:** Issue · `Feature` · **P3** · **M** · dueño `backend` (+ `reflex-ui` para «Así le llega»)
- **Depende de:** BU-B6 · **Bloqueada por:** —
- **Historia:** Como dueño de un local de comida, quiero que el menú de Instagram muestre mis
  productos con foto, para que el cliente elija viendo la comida.
- **Propuesta:** plantilla genérica (≤ 10 elementos, título y subtítulo de 80, foto) — según la nota
  «el mayor beneficio para un negocio de comida» `[arq §3.2 tabla, §4.2 M7]`.
- **Criterios de aceptación**
  - [ ] Prueba del traductor: categorías con más de 10 productos se parten en páginas válidas.
  - [ ] Prueba en vivo con cuenta con rol (ADR 25), captura en el PR.
- **Texto para el cliente:** ninguno nuevo (títulos y precios del catálogo).
- **Migración / medición / firma:** no / no / no.

### BU-B10 · Respuesta automática: cambiar los nombres que ya están en la app según la decisión de nombres

> **Sin ticket todavía — espera la decisión de nombres del fundador (vi).**

- **Tipo:** Issue · `Improvement`, `UI` · **P2** · **S** · dueño `reflex-ui`
- **Depende de:** — · **Bloqueada por:** decisión (vi)
- **Evidencia:** condición 3 de m-24789557 (fundador, 2026-10-23: ningún texto de la app dice ni
  sugiere que Qualify responde solo; se llama «Tu menú de bienvenida»); tabla de textos ya construidos
  que pueden chocar `[arq §3.3, «Contraste con las tres condiciones», punto 3]`.
- **Historia:** Como dueño, quiero que la app llame a mi menú siempre con el mismo nombre y sin decir
  que contesta sola, para entender que responde lo que yo escribí.
- **Propuesta:** cambiar, según lo que decida el fundador, los textos de la tabla del arquitecto que ya
  están en la app: «Respuesta automática» (pestaña, sección y «Ir a Respuesta automática»), «tu menú
  automático» del subtítulo de WhatsApp, «Todavía no tienes una respuesta automática con tus productos
  activa.», «Al enviarlo, la respuesta automática vuelve a atender este chat.», «Al responder, la
  respuesta automática se pausa en esta conversación.», «…tomar el control de la respuesta
  automática…» y «…puede publicar el menú automático ni la bienvenida.» (archivos y líneas en la
  tabla del arquitecto).
- **Criterios de aceptación**
  - [ ] `grep` en `Qualify/`: ningún texto visible de la tabla queda con el nombre viejo.
  - [ ] La prueba que ya cuida dos frases (`Qualify/test_whatsapp_menu_publish.py:316`) se amplía a
        los nombres que se dejan de usar.
  - [ ] Revisión local de `ux-designer` antes del PR.
- **Texto para el cliente:** el que decida el fundador en (vi); propuesta de la revisión UX: «Tu menú
  de bienvenida».
- **Fuera de alcance:** textos nuevos de otras historias (cada una lleva su propia revisión).
- **Migración / medición / firma:** no / no / decisión (vi).

## 5. Primer incremento y lo que corre en paralelo

**Primer incremento — fusionado (2026-11-13/14):** m-25017843 (PR #625) y m-25017844 (PR #624)
Done; m-25017859 (PRs #649 y #665) fusionada el 2026-11-14, RESOLVED y sin ver en un navegador;
m-25026457 (BU-A13, PR #653) en producción, RESOLVED y sin ver en un navegador. Lo que sigue es
la comprobación en producción, en celular y escritorio, de la lista y de «Cerrar».

**Seguimientos sin ticket** (salieron de los PR #649, #653 y #665):

- Las mismas protecciones de cerrar y reabrir en WhatsApp (hoy cierra sin comprobar si entró un
  mensaje y reabre con cualquier entrante, incluso repetido).
- `threads.last_inbound_at` queda vacío cuando Meta no entrega la hora de un mensaje que llega solo
  por la resincronización de Instagram; ese chat sería invisible para la regla.
- Borrar el código de la explicación única después del 2026-11-28.
- Inicio contando las dos redes (hoy solo Instagram).
- Contraste del gris de las filas cerradas.

**Primer incremento, como se planeó: m-25017843 → m-25017844 → m-25017859.** Una lista bajo
«Por responder» con los clientes que esperan en WhatsApp e Instagram, ordenados por hora, con una
sola etiqueta por fila y el mismo número en el menú y en la lista; al tocar, abre el chat de hoy de
su canal `[arq §1.2 «Primer corte con valor visible»]`. Advertencia: mientras no haya Advanced
Access de Instagram, los clientes reales de Bianki solo aparecerán por WhatsApp (riesgo v, §8
punto 1).

**En paralelo desde el día uno** (sin dependencias entre sí, dueños distintos):

| Línea | Historias | Dueño |
|---|---|---|
| Robustez del menú de hoy | m-25017846 → m-25017866 → m-25017868 | `backend` (uno solo: mismos archivos) |
| Bandeja | m-25017843 | `backend` (otra persona) |
| Pantallas sin dependencia | m-25017844, m-25017861 (empieza cuando esté la decisión (vi)) → BU-A10, m-25017862, m-25017864, m-25017865 | `reflex-ui` — ojo: m-25017844 y m-25017861 tocan `whatsapp_tab_chats.py`; en serie, un dueño `[arq §5]` |
| Medición | m-25017860 (contraste), m-25017863 (Sugerir respuesta) | `ux`, `datasci` |
| Fuera de la épica | m-25017848…m-25017852 (§7) | `backend` / `platform` |

**Después:** m-25017859 → BU-A5 → BU-A7 → (BU-A8, BU-A11, BU-A15, BU-A18, BU-A21); BU-A6 tras m-25017843
(ya fusionada, BU-A6 puede empezar); BU-A13 = m-25026457, ya entregada; BU-A14 tras m-25017861. Pista B: BU-B4 tras m-25017868; BU-B5 → BU-B6 → (BU-B7 Instagram,
BU-B8 Instagram, BU-B9) con el ADR 48 escrito (transcripción de m-24789557) y las decisiones (i-b), (i-c) y (vi). BU-B10 espera la decisión (vi).

## 6. Decisiones del fundador antes de empezar historias concretas

### (i) Menú automático en Instagram: lo que ya está decidido y lo que va más allá

**Ya decidido, no se vuelve a preguntar.** El fundador decidió el 2026-10-23 en **m-24789557**
(antes QUA-138), opción B: excepción acotada a «asistido, nunca autónomo». Se permite un menú
automático en mensajes directos de **Instagram y WhatsApp** solo si (1) el texto es fijo, escrito o
aprobado una vez por el dueño, sin contenido generado por un modelo en ese envío; (2) «Hablar con
alguien» está siempre y lleva a la bandeja asistida; (3) ningún texto de la app dice ni sugiere que
Qualify responde solo; se llama «Tu menú de bienvenida» `[arq §3.3, «La decisión existe»]`.

**Pendiente, sin ser decisión del fundador:** escribir el **ADR 48** («Enmienda a ADR 21: menú fijo
en mensajes directos») como transcripción de m-24789557, con estado aprobado el 2026-10-23. Lo
escribe `principal-architect` `[arq §3.3, «Lo pendiente es escribir el ADR»]`. El mecanismo de la
nota (aprobación = publicar la versión del menú; excepción acotada en `conversation_outbox`) cabe en
la condición 1 si se limita a versiones publicadas y contenido sin modelo `[arq §3.3, «¿Algo del
mecanismo…»]`.

**Decisiones del fundador que van más allá del texto del 2026-10-23** `[arq §3.3]`:

**(i-a) ¿El menú vuelve solo después de un tiempo sin respuesta del dueño?** Hoy un chat entregado a
una persona queda pausado para siempre `[arq §3.5 punto 5, §5 P5]`.

| Opción | Qué es | Para el dueño | Riesgo |
|---|---|---|---|
| **A. Solo con «Devolver al menú»** | Como hoy | Controla cuándo vuelve el menú | Un cliente que vuelve días después no lo atiende el menú si el dueño olvidó tocar el botón |
| B. Vuelve solo tras N horas sin mensajes del dueño | Reanudación automática | No tiene que acordarse | El menú le contesta a alguien con quien el dueño estaba hablando; no está en el texto del 2026-10-23 |

**Recomendación: A** por ahora, con un aviso en la fila cuando un chat lleva más de un día en manos
del dueño sin respuesta [supuesto PO]. **Bloquea:** solo una historia futura de reanudación (no hay
ninguna creada); m-25017866 no la necesita.

**(i-b) ¿Se avisa al cliente final con la palabra «automático»?** Meta lo recomienda siempre y lo
exige donde la ley lo pida (CO/VE/UY sin verificar) `[arq §3.4]`; la condición 3 habla de «la app»
y no está claro si cubre lo que lee el cliente final `[arq §3.3, tabla]`.

| Opción | Qué es | Riesgo |
|---|---|---|
| A. Aviso con «automático» («Te responde el menú automático de {negocio}») | Cumple la recomendación de Meta | Puede chocar con la condición 3 |
| **B. Aviso sin «automático», diciendo que es un menú y cómo llegar a una persona** | Propuesta UX: «Este es el menú de {negocio}. Toca "Hablar con alguien" cuando quieras.» | Si la ley exige la palabra, no alcanza (sin verificar) |
| C. Sin aviso | Nada que decidir | Contra la recomendación de Meta; riesgo en App Review |

**Recomendación: B**, y verificar la ley local antes de BU-B6. **Bloquea:** BU-B6.

**(i-c) ¿Cuentan como «aprobados una vez» al publicar los textos fijos que trae Qualify y los
armados con datos del dueño?** Ejemplos: la línea de ayuda ante una respuesta no entendida, la
entrega por defecto, «Elige una de las opciones para seguir.», «Te confirmamos el monto en …», la
respuesta «Formas de pago», las listas del catálogo y el total del pedido. Todos deterministas, sin
modelo; que el dueño los apruebe al publicar «es una interpretación, no está en el texto» `[arq
§3.3, «Contraste…» punto 1]`.

| Opción | Qué es | Para el dueño | Riesgo |
|---|---|---|---|
| **A. Sí: publicar el menú los aprueba, y la vista previa los muestra** | El ADR 48 lo dice en una línea | Ve antes de publicar todo lo que el menú puede mandar | Textos que no escribió salen con su aprobación implícita |
| B. Solo lo que el dueño escribió; los textos de Qualify pasan a ser editables y se aprueban uno a uno | Más pasos para armar el menú | Control total | Más trabajo de pantalla y de dueño |

**Recomendación: A**, con la condición de que «Así le llega» muestre esos textos antes de publicar.
**Bloquea:** BU-B5 (y por ella BU-B6, BU-B9).

### (ii) Qué significa «Por responder» cuando el menú automático ya contestó — **DECIDIDA**

**Decisión del fundador (2026-11-13, hora de Colombia), en sus palabras: «Solo si pasó a persona».**
Un chat abierto que el menú automático ya contestó cuenta como «Por responder» **solo** si se entregó a
una persona (el cliente tocó «Hablar con alguien» o es el turno del dueño) o si falló un envío
automático. Contestado solo por el menú, no cuenta. Es la opción B que se recomendaba `[arq §5 punto 3,
§2.3]`. Los fallos los marca m-25017866.

Descartadas: A, cualquier respuesta del menú saca el chat de la lista (escondía fallos y entregas a
persona); C, solo cuenta la respuesta del dueño (lista larga, el menú parece no servir).

Ya no bloquea: m-25017843 y m-25017859 pueden empezar. Decisión de dos vías: es un predicado en una
función, se cambia en un PR. Construida en m-25017843 (PR #625); la regla vive en
`packages/api/src/qualify_api/inbox/awaiting.py`.

### (vii) Lista única: chats vencidos de Instagram, cerrar chats y textos — **DECIDIDAS**

Decisiones del fundador tomadas durante m-25017859 y m-25026457, en sus palabras, con la fecha que
registra el comentario del ticket. Todas son de dos vías (una constante o un predicado, se cambian
en un PR).

1. **2026-11-13, «Ventana + cerrar chat»** (m-25017859). Un chat de Instagram cuenta como «Por
   responder» solo mientras su ventana de respuesta de 24 h está abierta; WhatsApp, sin límite. Y
   «Cerrar chat» llega a Instagram: BU-A13 pasó a ticket, m-25026457. Construido en los PR #649 y
   #653.
2. **2026-11-13, «Abiertas y Cerradas»** (m-25026457). En la pantalla de mensajes de Instagram el
   primer filtro pasó de «Todas» a «Abiertas» y el de cerrados a «Cerradas»; la marca de la cabecera
   es «Cerrado». La lista única (m-25017859) quitó después esos filtros propios de Instagram: los
   filtros de la lista son «Por responder · Todos · Cerrados · Pago por revisar» más «Sin responder a
   tiempo · N».
3. **2026-11-13, «Quedan N min»** (m-25017859). La etiqueta de tiempo de la fila dice «Quedan {N} min
   para responder»; reemplaza a «Responde en N min» de la propuesta UX.
4. **2026-11-13, «Sí, los de UX»** (m-25017859). Aviso de chats de Instagram que vencieron sin
   respuesta: «{N} chats de Instagram ya no se pueden responder aquí · Ver». Explicación única del
   cambio de números: «Ahora "Por responder" muestra solo a quien espera que una persona le
   conteste. Los chats que ya resolvió tu menú no cuentan.», con el botón «Entendido».
5. **2026-11-14, «Solo dos semanas»** (m-25017859). La explicación se muestra hasta el 27 de
   noviembre inclusive (desde el 2026-11-28, hora de Bogotá, ya no) en vez de recordar en el
   navegador que se descartó: una marca guardada en el navegador sobreviviría a la sesión del
   negocio y choca con la regla de limpieza al cerrar sesión
   (`docs/modelo-negocio-operador-multi-emprendimiento.md` §6.1); se descartó abrir una excepción.
   «Entendido» la oculta por el resto de la sesión en ese negocio. El código de la explicación se
   borra después de esa fecha (seguimiento sin ticket, §5).
6. **2026-11-14, «Respóndele desde Instagram»** (m-25017859). Etiqueta y marca de cabecera de un
   chat de Instagram vencido sin respuesta. Elegida sobre la de UX, «Respóndele desde la app de
   Instagram», porque no se pudo comprobar que cupiera en una fila de 360 px.
7. **2026-11-14, «Sí, Por responder»** (m-25017859). En WhatsApp › Chats el filtro «Sin leer» se
   llama «Por responder» y lista por la regla.
8. **2026-11-14, «Sí, ese nombre»** (m-25017859). El filtro de los chats de Instagram que vencieron
   sin respuesta se llama «Sin responder a tiempo».
9. **Prioridad de la etiqueta de la fila, como quedó construida:** «Pago por revisar» › («Quiere
   comprar»: lugar vacío, todavía no hay señal del backend) › etiqueta de tiempo › «Esperando el
   pago».

**Sigue sin decidir por el fundador:** «Todas las redes» en vez del segundo «Todos» en el filtro de
canal.

**Tomadas por el agente líder, abiertas a que el fundador las cambie:** «Pago por revisar» incluye
chats cerrados (igual que en la pantalla de WhatsApp); el aviso de chats vencidos cubre los últimos
7 días; la entrada de WhatsApp del menú lateral abre «Por responder» solo mientras muestra su
número.

### (iii) «Sugerir respuesta» en WhatsApp: tope de costo y lugar en el plan

**Es una decisión de negocio y va por el procedimiento `qualify-business-decisions`** (marco,
evidencia con niveles, costo por unidad con la calculadora, tabla de opciones, recomendación). No
pongo precios ni costos nuevos aquí. Lo que ya hay, con su nivel según la nota `[arq §4.1 C11]`:
borradores de comentarios medidos en US$0,00009–0,00017 cada uno [V]; un chat, estimado ≤ US$0,001
por toque [H]; 30 toques al día ≈ US$1 al mes por negocio [H]. Cada toque es una llamada pagada a
Claude `[UX §3 D4]`.

| Opción (a llenar con el procedimiento) | Qué es |
|---|---|
| A. Dejar como está | Solo en Instagram |
| B. Incluido en el plan con tope diario por negocio | Gratis para el dueño hasta el tope |
| C. Descuenta del cupo de creaciones | Cada toque consume unidades |
| D. Solo en algunos planes | Lo decide el empaque |

**Recomendación: no recomiendo precio ni lugar todavía;** primero m-25017863 da el costo medido y
después el procedimiento. Mientras tanto, construir BU-A17 apagado por defecto con tope diario
`[arq §4.1 C11]`. **Bloquea:** encender BU-A17 y BU-A18 en cualquier negocio.

### (iv) «Fotos y videos» en Instagram antes de la unificación

| Opción | Qué es | Para el dueño | Costo |
|---|---|---|---|
| **A. Esperar al cuadro único (BU-A7)** | Llega con la unificación | Espera unas semanas | Nada extra |
| B. Adelantarlo en la pantalla de Instagram de hoy (BU-A22) | Usa `orbit_menu` fuera de WhatsApp, que pide su visto bueno `[UX §6.3; design-system §5.9]` | Lo tiene antes | Una pantalla que BU-A7 reemplaza; trabajo que se tira |

**Recomendación: A** — no hay pedido de un cliente con evidencia [supuesto PO: no encontré uno], los
clientes reales de Instagram dependen de (v), y BU-A7 lo trae. **La reabrimos si** un cliente pide
mandar fotos por Instagram antes de que BU-A7 esté en curso. **Bloquea:** BU-A22 (no se crea con A).

### (v) Riesgo: Advanced Access de Instagram y App Review, con plazo de Meta

Tal como lo dice la nota `[arq §5 punto 1]`:

> «Con acceso Standard, Instagram Direct sólo funciona con personas con rol en la app; para los
> clientes reales de Bianki hace falta Advanced Access de `instagram_manage_messages` (QUA-142,
> plazo de Meta 2026-12-11 según `docs/conversaciones-limitaciones-meta.md` fila 2; estado de hoy
> sin verificar). Sin él, «una bandeja» muestra sólo WhatsApp a los clientes. Y si habrá menú en
> Instagram, la sumisión debería mostrarlo (§3.4).»

Y en §3.4: si la sumisión ya salió sin el menú, «preguntar si hace falta una nueva [sin verificar]».
**Su estado actual no se comprobó** (ni la nota ni este borrador).

| Opción | Qué es | Bloquea |
|---|---|---|
| **A. Verificar el estado esta semana** | Leer el ítem de Meegle que heredó QUA-142 y la consola de Meta; si la sumisión no salió, incluir menú + entrega a persona + bandeja en el video | Nada; desbloquea decidir lo demás |
| B. Mandar la sumisión solo con la bandeja asistida | Más rápido si ya está lista | Una segunda sumisión para el menú |
| C. Aplazar el menú de Instagram hasta después de la revisión | Menos alcance | BU-B6 para clientes reales |

**Recomendación: A** (lo más barato que cierra el hueco). **Bloquea:** el valor de m-25017859 en
Instagram para clientes reales y el uso de BU-B6 con clientes reales (no su construcción ni la
prueba con cuentas con rol).

### (vi) Nombres del menú en la app (condición 3 de m-24789557)

La condición 3 pide que ningún texto de la app diga ni sugiera que Qualify responde solo, y nombra
«Tu menú de bienvenida». La app ya tiene textos que pueden chocar y la propuesta UX trae otros
(tabla en `[arq §3.3, «Contraste…» punto 3]`). El fundador decide los nombres; aquí van las
propuestas de la revisión UX, no una elección.

| Lugar | Hoy o propuesto antes | Propuesta de la revisión UX |
|---|---|---|
| Nombre del menú (pestaña, sección, «Ajustes de chats») | «Respuesta automática» | «Tu menú de bienvenida» |
| Interruptor por canal | «Responde en WhatsApp» / «Responde en Instagram» | «Usar en WhatsApp» / «Usar en Instagram» |
| Franja «quién responde» | «Está respondiendo tu menú automático · Responder yo» | «Este cliente está usando tu menú · Responder yo» |
| Píldora cuando falló un envío | «Tu menú no pudo responder» | «Tu menú no le llegó: respóndele tú» |
| Aviso al cliente final | «Te responde el menú automático de {negocio}» | «Este es el menú de {negocio}. Toca "Hablar con alguien" cuando quieras.» (ver i-b) |

**Opciones:** A. adoptar las propuestas de la revisión UX; B. adoptar otras; C. mantener los de hoy
(choca con la condición 3). **Recomendación del PO: decidirlo de una vez para toda la épica**, no
historia por historia. **Bloquea:** el inicio de m-25017861, BU-B6, BU-B7, BU-B8, BU-B10, y el texto
de la píldora de m-25017866.

**Las preguntas P5 y P6 de la nota** `[arq §5]` quedaron dentro de (i-a) y (i-b).

## 7. Issues aparte, fuera de la épica

Se crean sin el campo «Feature» y con «Relacionado con» hacia la épica.

### m-25017848 (BU-S1) · Mensajes: aviso inmediato con LISTEN/NOTIFY para que los mensajes lleguen sin esperar el ciclo

- **Tipo:** Issue · `Improvement`, `Infraestructura` · **P2** · **M** · dueño `backend` (+ `platform`)
- **Contexto:** después del PR #608, `webhook-worker` despierta cada 5 s y procesa los mensajes
  primero; nada empuja un mensaje, cada salto espera un temporizador. El PR deja LISTEN/NOTIFY como
  seguimiento `[PR #608, «Why» y «Limitations»]`. Postgres ya está: no es un almacén nuevo (ADR 31).
- **Qué hay que hacer:** al guardar un evento de webhook (y al aprobar un envío), `NOTIFY` en un
  canal; los workers hacen `LISTEN` y despiertan al instante, con el ciclo de 5 s como respaldo.
- **Cómo verificarlo:** medir en producción el tiempo entre `received_at` del evento y el mensaje
  guardado (antes/después), con la consulta en el PR.
- **Criterios de aceptación**
  - [ ] Prueba (`-m db`): un `NOTIFY` despierta al worker antes del ciclo; sin `NOTIFY` el ciclo sigue funcionando.
  - [ ] Una conexión caída de `LISTEN` se reconecta sola y lo registra en el log.
  - [ ] Mediana de llegada medida y anotada en el ticket, antes y después.
- **Fuera de alcance:** el sondeo de 15 s de la pantalla del chat `[PR #608, «Limitations»]` (otro
  ticket si se quiere empujar a la UI).

### m-25017849 (BU-S2) · `webhook-worker`: sacar el análisis de comentarios del ciclo de mensajes

- **Tipo:** Issue · `Deuda técnica` · **P2** · **M** · dueño `backend`
- **Contexto:** «A message arriving during the comment-analysis sweep (every 10 min) still waits for
  the sweep to finish» `[PR #608, «Limitations»]`.
- **Qué hay que hacer:** correr los barridos (análisis de comentarios, sentimiento de menciones) fuera
  del ciclo de mensajes, por ejemplo en un hilo de fondo del mismo proceso, como hizo #608 con el
  re-sync de Instagram. Un contenedor nuevo es decisión de `platform-engineer` y del fundador
  (memoria del servidor de 4 GB) **[supuesto PO]**.
- **Cómo verificarlo:** prueba con un barrido bloqueado: un mensaje entrante se procesa en el
  siguiente ciclo.
- **Criterios de aceptación**
  - [ ] Prueba: con el barrido bloqueado, el lote de mensajes del siguiente tick se procesa.
  - [ ] Los barridos no corren más seguido ni cuestan más que hoy (prueba de cadencia como en #608).
  - [ ] Apagado ordenado: el hilo de fondo se cancela y se une al cerrar.
- **Fuera de alcance:** cambiar el modelo o el costo del análisis de comentarios.

### m-25017850 (BU-S3) · Conversaciones: la marca de «enviado» de Instagram se pierde cuando el eco entra antes que `mark_sent`

- **Tipo:** Issue · `Bug` · **P2** · **S** · dueño `backend`
- **Qué pasa:** carrera previa a #608: un eco entrante (webhook o re-sync) puede insertar la fila del
  mensaje saliente antes de `mark_sent`, y la fila queda sin `delivery_status='sent'` ni
  `media_object_key` (sigue habiendo una fila por id de mensaje) `[PR #608, «Limitations»]`.
- **Arreglo (propuesto en el PR #608):** `ON CONFLICT … DO UPDATE` con `COALESCE` en
  `_INSERT_OUTBOUND_MESSAGE` (`conversations/outbox.py:333`).
- **Criterios de aceptación**
  - [ ] Prueba (`-m db`): eco insertado primero, después `mark_sent` → la fila termina con
        `delivery_status='sent'` y `media_object_key`, una sola fila.
  - [ ] Prueba: el orden normal (primero `mark_sent`) no cambia.
- **Fuera de alcance:** el estado visible «Enviando…» (BU-A21, que depende de este arreglo en Instagram).

### m-25017852 (BU-S4) · Conversaciones: la persona que escribe por Instagram aparece como «Persona sin nombre»

> **Done — PR #622, fusionado el 2026-11-13.** El fundador confirmó que se ve el @usuario. Sin
> nombre ni usuario, la fila dice «Cliente de Instagram» o «Cliente de WhatsApp» (m-25017844).

- **Tipo:** Issue · `Bug` · **P1** (lo vio el fundador esta semana probando con un negocio real;
  nadie queda bloqueado, por eso no es P0) · **M** · dueño `backend` (+ `reflex-ui` para el texto)
- **Qué pasa:** en PROD, en la lista y el chat de Conversaciones, una persona que escribe por
  Instagram aparece como «Persona sin nombre» (`Qualify/conversations_vm.py:841`). La pantalla prueba
  `threads.counterpart_name`, después `counterpart_username`, después el `messages.author_username`
  del entrante más nuevo, y si no hay nada usa ese texto. Reportado por el fundador (2026-11-12).
- **Causa** (diagnóstico leído en el código; **producción todavía sin revisar**)
  - **Confirmado al leer el código:** un hilo creado por el webhook de Instagram no guarda nombre ni
    usuario (`conversations/webhook.py:290-312`; `sync.py:275-307` no llama al perfil), y el webhook
    inserta `author_username` en NULL que un re-sync posterior nunca llena (`repository.py:269-282`).
    Solo el re-sync periódico nombra hilos (`sync.py:244` → `GET /{igsid}?fields=name,username,profile_pic`,
    `instagram_source.py:576-606`); si falla, usa el usuario del participante del listado
    (`sync.py:337-339`). La llamada al perfil quedó registrada en vivo como 403 código 230 (necesita
    el consentimiento de la persona) en `docs/conversaciones-limitaciones-meta.md:299`: el nombre real
    y la foto normalmente no llegan; solo puede llegar el @usuario.
  - **Posible, sin confirmar** (la revisión en producción está en curso): (1) el re-sync nunca llegó
    a este hilo — la verificación de acceso detiene la sincronización sin error (`sync.py:170-183`),
    o límites de uso, porque cada ronda hace una llamada de mensajes por conversación sin tope
    (`worker.py:496-498`); (2) el listado no incluye esta conversación (acceso Standard sin rol en
    la app, o una solicitud de mensaje); (3) el perfil devuelve solo `profile_pic`, se salta el
    usuario del participante y se sella `profile_at`, que bloquea reintentar por 24 h (`sync.py:337`).
  - **No es la causa:** el PR #608 (solo tocó `worker.py`).
- **Arreglo (el más chico propuesto)**
  - Completar con el usuario del participante un perfil que no trae usuario (`sync.py:337`).
  - Al crear un hilo desde el webhook, nombrarlo con una llamada
    `GET /{page}/conversations?platform=instagram&user_id={IGSID}&fields=participants` (una llamada
    a Graph por hilo nuevo; no se espera permiso nuevo — **sin verificar en vivo**).
  - Opcional: llenar `author_username` en el conflicto (`repository.py:269`).
  - Agregar las pruebas que faltan (hoy no hay ninguna de `refresh_profile`/`fetch_profile`/`parse_profile`).
- **Límite que ningún cambio de código resuelve:** el nombre real y la foto necesitan el
  consentimiento de la persona (código 230) y, para quien no tiene rol en la app, Advanced Access
  vía App Review (riesgo v de §6).
- **Criterios de aceptación**
  - [ ] Prueba: un hilo creado por el webhook con un IGSID nuevo termina con `counterpart_username`
        lleno usando la respuesta de `participants` (cliente de Graph simulado).
  - [ ] Prueba: un perfil que devuelve solo `profile_pic` conserva el usuario del participante y no
        bloquea el reintento sin nombre.
  - [ ] Pruebas nuevas de `parse_profile`, `fetch_profile` y `refresh_profile` (403 código 230,
        respuesta parcial, respuesta completa).
  - [ ] Prueba del VM: sin nombre y con usuario, la fila y la cabecera muestran «@usuario»; sin
        nada, muestran el texto acordado abajo.
  - [ ] En PROD, después del despliegue, el hilo que vio el fundador muestra su @usuario (o el PR
        dice cuál de las causas posibles lo impide, con la evidencia).
- **Texto para el cliente:** con solo el usuario: «@{usuario}». Sin nada: propongo «Cliente de
  Instagram» en lugar de «Persona sin nombre» — dice de dónde viene y no suena a error
  **[supuesto PO, propuesto; revisar con `ux-designer`/`qualify-copy-es`]**.
- **Fuera de alcance:** obtener nombre real y foto sin consentimiento; unir la persona con su chat
  de WhatsApp `[arq §1.3]`.
- **Relacionado con:** m-25017844/m-25017859 (la fila compartida muestra este nombre).

## 8. Lo que creo que está mal o no se puede entregar así en las fuentes

1. **El «primer corte con valor visible» es, para clientes reales, solo de WhatsApp** hasta que haya
   Advanced Access `[arq §1.2 vs §5 punto 1]`. Y Bianki tiene un solo número, así que el filtro de
   canal ni se dibuja `[UX §4 punto 5]`. El valor real del primer incremento es una sola lista y un
   solo número de «Por responder», no «los dos canales juntos». Hay que decírselo así al fundador.
2. **C4, C5, C6, C10, C11 y M1, M3 no son un PR cada uno** (juntan dueños, una medición previa, una
   migración o una firma): los partí (§3 y §4). Ver tablas al principio de cada pista.
3. **M3 mezcla lo que necesita el ADR 48 con lo que no.** Partido en BU-B4/BU-B5. El menú en Instagram ya está decidido (m-24789557, 2026-10-23), así que BU-B4 no espera ninguna decisión.
4. **«Volver a tus chats» (UX §2) vs «Volver al chat» (la app, `whatsapp_location_vm.py:57`,
   `whatsapp_payments_vm.py:87`, y el pedido del fundador).** Propongo «Volver al chat» en todos lados;
   el doc UX debería corregirse.
5. **Arreglo 3 de §3.5 de la nota:** «descarta filas `automation` de hilos pausados después de su
   `created_at`» se puede leer al revés. Entiendo «filas creadas antes de la pausa»; m-25017866 lo fija con
   una prueba.
6. **Riesgo de conflictos en `whatsapp_tab_chats.py` y su estado** `[arq §5]`: casi la mitad de la
   pista A y BU-B7/BU-B8 pasan por ahí. Un solo `reflex-ui-engineer` dueño de esos archivos, en serie.
7. **«Por responder» con el menú** (decisión ii) bloqueaba m-25017843; el fundador la tomó el
   2026-11-13 («Solo si pasó a persona»), así que el primer incremento ya puede empezar.

## 9. Prompt para `/qualify-team-dev` (actualizado 2026-11-14, con el primer incremento fusionado)

```
/qualify-team-dev Épica «Bandeja única de chats y respuesta automática» — doc
docs/epica-bandeja-unica.md. Ya fusionado: m-25017843 (PR #625), m-25017844 (PR #624),
m-25017859 (PRs #649, #665), m-25026457 (BU-A13, PR #653), m-25017852 (PR #622). Regla de
«Por responder» en packages/api/src/qualify_api/inbox/awaiting.py; decisiones (ii) y (vii) en §6.
Menú en Instagram: decidido el 2026-10-23 (m-24789557); el ADR 48 lo escribe principal-architect.
Pendientes del fundador: (i-a/b/c), (iii), (iv), (vi) y «Todas las redes». Siguiente:
- Comprobar en producción, celular y escritorio, la lista única de m-25017859 y «Cerrar» de
  m-25026457 (ninguna se vio en un navegador); con eso pasan de RESOLVED a Done.
- backend-engineer (A): m-25017846 → m-25017866 → m-25017868 (mismos archivos, una sola persona; pruebas -m db).
- backend-engineer (B): BU-A6 (crear el ticket); los seguimientos sin ticket de §5 si el fundador los prioriza.
- reflex-ui-engineer (único dueño de whatsapp_tab_chats.py y conversations_page.py): m-25017861 → BU-A10;
  m-25017862, m-25017864 y m-25017865 entre medio si no tocan esos archivos; BU-A5 cuando esté m-25017860.
- ux-designer: m-25017860 (contraste del tinte, condición de D2) y la prueba «Responder yo» con Bianki (BU-B8).
- data-scientist-fde: m-25017863 (medición de Sugerir respuesta, qualify-measure).
- backend-engineer (fuera de la épica): m-25017850, m-25017849, m-25017848.
Cada historia es un PR con su m-<id>; nada de BU-B5/B6/B9 sin el ADR 48 escrito y (i-b)/(i-c)/(vi) decididas.
```
