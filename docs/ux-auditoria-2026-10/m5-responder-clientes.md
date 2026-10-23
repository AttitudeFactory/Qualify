# M5 · Responder a clientes (comentarios, mensajes, consultas, interesados)

Auditoría de experiencia, solo sugerencias. Pantallas revisadas: `/inbox` «Interacciones»
(`Qualify/inbox_page.py`), `/conversations` «Conversaciones» con su segunda vista «Consultas desde
comentarios» (`Qualify/conversations_page.py`, `Qualify/followups_page.py`), `/leads`
(`Qualify/leads_page.py`). Comparadas con `/whatsapp?tab=chats` (`Qualify/whatsapp_tab_chats.py`).
Fecha: 2026-10-23. Perfil: `docs/perfil-cliente-pyme.md`.

## (a) El trabajo del módulo, en palabras del dueño

1. «Que nadie se quede sin respuesta»: ver de un vistazo quién me escribió o comentó y todavía no le contesté (meta: menos de 2 h, brief de la agencia de viajes §3.3).
2. «Contestar rápido desde el celular»: abrir, leer, aceptar o corregir la respuesta que me sugieren y mandarla, yo, con un toque.
3. «No perder al que quiere comprar»: que el que pregunta precio o disponibilidad salga primero, y que después sepa dónde quedó (su WhatsApp, su teléfono).

**Diagnóstico corto.** El mismo trabajo está repartido en **cuatro lugares sin enlace entre sí**
(Interacciones, Conversaciones › Mensajes, Conversaciones › Consultas desde comentarios, WhatsApp ›
Chats) más **Leads**, que queda suelto en el menú. Hoy el dueño tiene que recorrer los cuatro para
saber si alguien quedó sin respuesta, y en «Interacciones» lo primero que ve es una lista de
interruptores para «monitorear Reels», no a la gente que le escribió.

## (b) Hallazgos (ordenados por severidad)

Severidad: 1 = no puede terminar · 2 = palabras técnicas o de herramienta · 3 = demasiadas cosas en un paso · 4 = accesibilidad/celular · 5 = pulido.

### 1. No hay un solo lugar con «lo que falta por responder» — sev. 1 · L
- **Dónde:** `Qualify/ui/layout.py:61-64` (Interacciones y Conversaciones en «Escuchas»), `:51` (WhatsApp en la base), `:85` (Leads suelto); `Qualify/conversations_page.py:1596-1604` (la segunda vista escondida en un selector).
- **Problema, como lo diría el dueño:** «¿Dónde veo quién me falta por contestar? Entré a Conversaciones, estaba vacío, y resulta que el comentario estaba en Interacciones y el pedido en WhatsApp.»
- **Arreglo sugerido:** una pantalla de entrada del módulo «Responder» con la cuenta de pendientes por canal, que enlace a cada lista ya filtrada en «Pendientes». Usa `stat_card` y `card` existentes; nada nuevo.
  ```
  ┌ Por responder hoy ───────────────┐
  │ 3 mensajes de Instagram    [Ver] │  → /conversations (filtro Pendientes)
  │ 2 personas que quieren comprar   │  → /conversations?vista=consultas
  │ 5 comentarios sin respuesta[Ver] │  → /inbox (comentarios pendientes)
  │ 1 chat de WhatsApp         [Ver] │  → /whatsapp?tab=chats
  └──────────────────────────────────┘
  ```
  Título: «Por responder». Descripción: «Las personas que te escribieron o comentaron y todavía esperan tu respuesta.»

### 2. «Interacciones» empieza por configurar, no por responder — sev. 1 · M
- **Dónde:** `Qualify/inbox_page.py:283-309` (orden del cuerpo: sincronización → lista de Reels con interruptor → comentarios → borradores al final), `:1214-1219` (subtítulo «… elige cuáles monitorear»).
- **Problema:** «Entré a contestar comentarios y me salen interruptores de "Monitoreado". Las respuestas listas están abajo del todo; en el celular nunca llego.»
- **Arreglo sugerido:** invertir el orden: (1) respuestas listas para aprobar, (2) comentarios por publicación, (3) «Qué publicaciones revisar» plegado detrás de «Más opciones». Nuevo encabezado:
  - Título: «Comentarios»
  - Subtítulo: «Lo que te comentaron en tus publicaciones de las últimas 2 semanas, con la respuesta lista para que la apruebes.»
  ```
  ┌ Comentarios ─────────────────────┐
  │ Respuestas listas para aprobar(4)│
  │ ┌ @ana: «¿Tienen delivery?» ────┐│
  │ │ ↳ «¡Hola Ana! Sí, hasta…»     ││
  │ │ [Aprobar y responder] [Editar]││
  │ └───────────────────────────────┘│
  │ Comentarios por publicación      │
  │ ▸ Más opciones: qué publicaciones│
  │   revisar                        │
  └──────────────────────────────────┘
  ```

### 3. Los comentarios con preguntas o quejas no tienen cómo responderse en público — sev. 1 · M
- **Dónde:** `Qualify/inbox_page.py:1071-1077` y `:1206` («…para comentarios **positivos**…»); `Qualify/replies_provider.py:93` (solo genera borradores para comentarios positivos); `Qualify/inbox_page.py:366-376` (el único botón de la tarjeta es «Responder por DM»).
- **Problema:** «Alguien preguntó el precio, o se quejó, y no hay botón para contestarle ahí. Solo me ofrece mandarle un mensaje privado.»
- **Arreglo sugerido:** en cada tarjeta de comentario, dos acciones con el mismo peso: «Responder aquí» (abre el borrador en la misma tarjeta, con `chat_bubble` como ya hacen los borradores) y «Escribirle en privado». Para quejas, que el borrador nunca salga sin edición («Revísala antes de aprobar»). Sin envío automático: sale solo al pulsar «Aprobar y responder».

### 4. Palabras técnicas y en inglés en toda la pantalla de comentarios — sev. 2 · S
- **Dónde y reemplazo exacto:**
  | Archivo:línea | Hoy | Sugerido |
  |---|---|---|
  | `inbox_page.py:1216` | «Interacciones» | «Comentarios» |
  | `inbox_page.py:373` | «Responder por DM» | «Escribirle en privado» |
  | `inbox_page.py:135`, `:522` | «Monitoreado» / «No monitoreado» | «Revisando comentarios» / «Sin revisar» |
  | `inbox_page.py:529` | «No monitoreado · vencido» | «Ya no se revisa (pasaron 2 semanas)» |
  | `inbox_page.py:151`, `:558`, `:680` | «Sin caption» | «Sin texto» |
  | `inbox_page.py:979-980` | «Los comentarios se sincronizan automáticamente cada 5 minutos…» | «Buscamos comentarios nuevos cada 5 minutos mientras tienes esta pantalla abierta.» |
  | `inbox_page.py:922` | «Sincronizar comentarios» | «Buscar comentarios nuevos» |
  | `inbox_page.py:852`, `:869` | «Analizar sentimiento» / «Analizar intención» | un solo botón «Ordenar por prioridad» (o que corra solo al llegar el comentario; ver hallazgo 6) |
  | `inbox_page.py:741` | «Requiere atención comercial» | «Quieren comprar» |
  | `inbox_page.py:340` | «… · no fiable» | «… · revísalo» |
  | `inbox_page.py:1200` | «Borradores asistidos» | «Respuestas listas para aprobar» |
  | `inbox_page.py:1090` | «Aceptar y enviar» | «Aprobar y responder» |
  | `inbox_page.py:479` | «Resumen general — todos los comentarios sincronizados» | «Cómo te comentan: buenos, neutros y malos» |
  | `followups_vm.py:54` | «Intención comercial» | «Quiere comprar» |
  | `followups_vm.py:55` | «Abierta desde Interacciones» | «La abriste tú desde Comentarios» |
  | `followups_state.py:61-62` | «…(falta la clave del modelo)…» | «Ahora no podemos sugerirte un mensaje. Escríbelo tú y apruébalo.» |
  | `conversations_state.py:173` | «…falta configurar la clave del modelo.» | «Ahora no podemos sugerirte una respuesta. Escríbela tú.» |
  | `leads_page.py:20-21` | «Leads» / «Personas captadas por tu funnel…» | «Clientes interesados» / «Personas que dejaron sus datos para que las contactes, con su permiso guardado.» |
  | `leads_page.py:65` | «Datos extra» | «Lo que te contaron» |
  | `Qualify.py:266` (título de pestaña) | «Qualify · Leads» | «Qualify · Clientes interesados» |
  | `Qualify.py:255` | «Qualify · Interacciones» | «Qualify · Comentarios» |
  | `layout.py:85` | «Leads» | «Interesados» |
- **Problema:** «¿Qué es monitorear? ¿Qué es un DM? ¿Funnel?»

### 5. Identificadores internos a la vista — sev. 2 · S
- **Dónde:** `Qualify/inbox_page.py:413` (`mono(comment.external_thread_id)`), `:1162` (`mono(draft.source_id)`), `:693` aprox. (id de la publicación en el detalle).
- **Problema:** «¿Qué es este número largo?» y la respuesta lista no dice a qué publicación pertenece.
- **Arreglo sugerido:** quitar los identificadores; en su lugar, la miniatura de la publicación (`media_thumb`, 40 px) y «En tu publicación del martes».

### 6. Los comentarios y su prioridad dependen de que el dueño tenga la pantalla abierta y pulse botones — sev. 1 · L
- **Dónde:** `Qualify/inbox_page.py:979-980` (solo se buscan mientras está la pantalla abierta), `:842-875` («Analizar sentimiento», «Analizar intención»), `:1009-1020` («Generar borradores»).
- **Problema:** «Si no entro, nadie me avisa. Y cuando entro tengo que pulsar tres botones antes de ver algo.» Con la meta de 2 h, un comentario de la mañana se ve a la noche.
- **Arreglo sugerido:** que buscar, ordenar y preparar la respuesta corran solos en segundo plano (solo la **preparación**: el envío sigue siendo siempre del dueño). La pantalla muestra el resultado y un solo botón secundario «Buscar ahora». Aviso de pendientes en el menú (hallazgo 9). Esfuerzo L porque toca un proceso en segundo plano (decisión del fundador sobre infraestructura).

### 7. «Consultas desde comentarios» está escondida en un selector y repite el trabajo de Interacciones — sev. 3 · M
- **Dónde:** `Qualify/followups_page.py:28-36` (selector «Mensajes / Consultas desde comentarios»), `Qualify/inbox_state.py:1099` (salto de Interacciones a `/conversations?consulta=`).
- **Problema:** «Le di "Responder por DM" y me mandó a otra pantalla, a una pestaña que nunca había visto. ¿Cómo vuelvo al comentario?»
- **Arreglo sugerido:** renombrar la vista a «Quieren comprar (N)» y mostrarla **primero** cuando N > 0. Al aprobar, aviso «Listo. Le escribiste a @ana. ¿Seguimos con la siguiente?» con «Siguiente» y «Volver a comentarios». En la tarjeta, la publicación de origen enlaza de vuelta a `/inbox` en ese comentario.

### 8. La tarjeta de consulta mezcla cuatro decisiones en una — sev. 3 · M
- **Dónde:** `Qualify/followups_page.py:262-271` (`_origin`, `_route`, `_draft`, `_notice`, `_actions` juntos), `:184-206` (casilla + texto del aviso público).
- **Problema:** en el celular es una tarjeta larguísima: quién es, por dónde sale, qué le digo, si además comento en público, y cinco botones.
- **Arreglo sugerido:** pasos cortos dentro de la misma tarjeta, con valores ya rellenados:
  ```
  ① Qué preguntó         ② Qué le respondes          ③ Revisa y aprueba
  @ana · «¿precio?»      [borrador ya escrito]       «Le llega a @ana por mensaje
  en tu publicación      ↻ Otra idea                  privado. También dejamos
  del martes                                          "Te escribimos al privado 💬"
  [Responderle]          [Atrás] [Siguiente]          en su comentario.»
                                                      [Atrás] [Aprobar y enviar]
  ```
  El aviso público pasa a ser una opción marcada por defecto en el paso 3 con su texto ya escrito; «Por dónde sale» se dice en una frase, sin el ícono de información que solo se lee al pasar el mouse (`followups_page.py:119`).

### 9. Ningún aviso de pendientes fuera de la pantalla — sev. 3 · M
- **Dónde:** `Qualify/ui/layout.py:61-64`, `:85` (el menú no lleva cuentas); `Qualify/conversations_page.py:222-236` (el «N sin responder» solo se ve dentro de Conversaciones).
- **Problema:** «No sé que alguien me escribió hasta que entro justo a esa pantalla.»
- **Arreglo sugerido:** contador en el menú junto a cada entrada del módulo con la misma insignia `tone_badge` en tono `warn` que ya usa `_pending_badge`, y en el título de la pestaña del navegador «(3) Qualify · Por responder». Sin cambiar colores ni componentes.

### 10. Las pantallas no funcionan bien a 360 px — sev. 4 · S
- **Dónde:** `Qualify/inbox_page.py:103` y `:764` y `Qualify/conversations_page.py:203` (`width="260px"` fijo en selectores y buscador); `inbox_page.py:155` (`max_width="380px"`); `leads_page.py:56-75` (tabla de 6 columnas con desplazamiento horizontal); botones `size="1"` (~24 px) en «Responder por DM» (`inbox_page.py:376`), «Aceptar y enviar / Editar / Descartar» (`:1094-1110`), filtros (`conversations_page.py:412`); «no fiable» solo explicado al pasar el mouse (`inbox_page.py:339-347`).
- **Arreglo sugerido:** `width="100%"` con `max_width` en selectores; botones de acción principal en `size="3"` (≥ 44 px); la tabla de Leads se vuelve una lista de `card` en el celular: nombre, interés, botón «Escribirle por WhatsApp»; la explicación de «revísalo» como texto visible bajo la etiqueta, no en `tooltip`.

### 11. Leads es una lista de solo lectura sin siguiente paso — sev. 3 · M
- **Dónde:** `Qualify/leads_page.py:33-53`, `:78-84` («Comparte el formulario de captura…» sin decir dónde está ni dar el enlace).
- **Problema:** «Veo el nombre y el teléfono, ¿y ahora? ¿Ya le escribí o no? ¿Dónde está el formulario que tengo que compartir?»
- **Arreglo sugerido:** botón por persona «Escribirle por WhatsApp» (ya existe el enlace `wa_href`, falta que sea botón grande) y estado «Pendiente / Ya le escribiste» con `signal_pill`. Estado vacío con el enlace real y «Copiar enlace»: «Todavía no hay interesados. Comparte este enlace en tu perfil o en tus historias para que te dejen sus datos.» (hipótesis: que el dueño contacte desde WhatsApp personal y no desde el número del negocio, §5 pregunta 2 y 3).

### 12. Botones de envío que no dicen a quién ni por dónde — sev. 5 · S
- **Dónde:** `Qualify/inbox_page.py:1090`, `:1134` («Aceptar y enviar», «Guardar y enviar»); `Qualify/conversations_page.py:1479` («Responder»), confirmaciones `conversations_state.py:169` («Respuesta en cola. Sale en unos segundos.»).
- **Arreglo sugerido:** «Aprobar y responder a @ana» y la confirmación «Listo, le respondiste a @ana. Sale en unos segundos.» («en cola» suena a sistema). Las tarjetas de «Respuestas listas» muestran a quién y en qué publicación antes del botón.

## (c) Navegación

### Estructura actual
```
Menú
├─ Base:     Conexiones · WhatsApp (/whatsapp?tab=chats … 5 pestañas)
├─ Escuchas: Menciones · Interacciones (/inbox) · Conversaciones (/conversations) · (Creadores, Señales: pronto)
├─ Publicas: …
└─ suelto:   Leads (/leads)

/inbox «Interacciones» (una sola página larga, sin rutas)
  sincronizar → Reels con interruptor → resumen → tarjetas por publicación
     └─ «Ver comentarios» → detalle (botón «Volver», sin ruta propia: atrás del navegador sale del módulo)
  → borradores (al final)
  «Responder por DM» ──salta──▶ /conversations?consulta=<id> (otra sección del menú)

/conversations «Conversaciones»
  selector [Mensajes | Consultas desde comentarios (N)]   ← la segunda vista no tiene ruta propia
  Mensajes: lista ⇄ conversación (en celular, una a la vez con «Volver»)
  Consultas: tarjetas; al aprobar/descartar → toast, se queda en la lista. Sin enlace de regreso al comentario.

/leads: tabla de solo lectura; sin enlaces a ningún otro lugar.
WhatsApp › Chats: misma forma lista ⇄ conversación que Conversaciones, pero en otra sección del menú.
```
**Callejones sin salida:** detalle de comentarios (sin ruta; atrás del navegador pierde el lugar);
consulta aprobada (no propone la siguiente); Leads (no lleva a escribirle a nadie desde Qualify);
estados vacíos de Conversaciones y Consultas sin acción (`conversations_page.py:436-454`,
`followups_page.py:283-289`).

### Estructura propuesta
```
Menú › «Responder» (una sola entrada con contador de pendientes)
/responder              «Por responder» — resumen de pendientes por canal (hallazgo 1)
├─ /responder/mensajes      Instagram (hoy /conversations, vista Mensajes)    pestaña «Mensajes (3)»
├─ /responder/quieren-comprar  hoy la vista Consultas                         pestaña «Quieren comprar (2)»
├─ /responder/comentarios   hoy /inbox (respuestas listas arriba)             pestaña «Comentarios (5)»
│    └─ /responder/comentarios/<publicación>   detalle con ruta propia (atrás funciona)
├─ /whatsapp?tab=chats      se enlaza como pestaña «WhatsApp (1)» (el módulo WhatsApp conserva su lugar)
└─ /responder/interesados   hoy /leads                                         pestaña «Interesados»
```
- Las pestañas usan el `segmented_control` que ya usan Publicar y WhatsApp; cada una con ruta o `?tab=` propio, para que «atrás» y los enlaces funcionen.
- `page_header` por pestaña: título = el beneficio («Mensajes por responder», «Quieren comprar», «Comentarios», «Clientes interesados»); subtítulo de una línea; mismo `account_selector` a la derecha.
- Títulos de pestaña del navegador: «(N) Qualify · Por responder», «Qualify · Comentarios», «Qualify · Quieren comprar», «Qualify · Clientes interesados».
- **Al terminar** una respuesta: se queda en la misma lista, la tarjeta respondida baja a «Respondidas» y se ofrece «Siguiente pendiente». Con cero pendientes, estado vacío con salida al siguiente trabajo del dueño: «¡Al día! No hay nadie esperando tu respuesta. ¿Preparamos la publicación de mañana?» → `/create`.
- **Enlaces entre módulos:** desde una pieza publicada (Publicar/Piezas) → «Ver comentarios de esta publicación» (`/responder/comentarios/<publicación>`); desde una consulta aprobada con teléfono → «Guardar como interesado» (hipótesis, §5 pregunta 7: si el dueño mide «valió la pena» en mensajes o ventas).
- Las rutas actuales (`/inbox`, `/conversations`, `/leads`) redirigen a las nuevas para no romper enlaces.

## (d) Historias de usuario propuestas

### Grupo A · Un solo lugar para no dejar a nadie sin respuesta
1. **Como dueño, quiero ver en una sola pantalla cuántas personas esperan mi respuesta en cada canal, para no dejar a nadie sin contestar más de 2 horas.**
   - Muestra el número de pendientes de mensajes de Instagram, consultas de compra, comentarios y chats de WhatsApp, cada uno con «Ver» que abre la lista ya filtrada en pendientes.
   - Con cero pendientes muestra «¡Al día! No hay nadie esperando tu respuesta.» con un enlace a crear la próxima publicación.
   - A 360 px se ve en una columna, sin desplazamiento horizontal, con botones de al menos 44 px.
2. **Como dueño, quiero ver un contador de pendientes en el menú y en la pestaña del navegador, para enterarme sin tener que entrar a buscar.**
   - La entrada «Responder» del menú muestra el total con la insignia de tono de advertencia existente; desaparece en 0.
   - El título de la pestaña empieza por «(N)» cuando hay pendientes.
   - El contador se actualiza al responder sin recargar la página.
3. **Como dueño, quiero que las secciones de responder sean pestañas de un mismo lugar con su propia dirección, para moverme entre ellas y volver atrás sin perderme.**
   - Pestañas «Mensajes», «Quieren comprar», «Comentarios», «WhatsApp», «Interesados», cada una con su ruta; el botón «atrás» del navegador vuelve a la pestaña anterior.
   - `/inbox`, `/conversations` y `/leads` redirigen a su pestaña nueva.
   - El detalle de comentarios de una publicación tiene ruta propia.

### Grupo B · Comentarios: responder primero, configurar después
4. **Como dueño, quiero ver primero las respuestas listas para aprobar de mis comentarios, para contestar en un minuto desde el celular.**
   - La pantalla de comentarios empieza por «Respuestas listas para aprobar»; la elección de publicaciones a revisar queda en «Más opciones».
   - Cada respuesta muestra a quién, el comentario y la publicación (miniatura), sin números internos.
   - El botón dice «Aprobar y responder»; nada sale sin pulsarlo.
5. **Como dueño, quiero poder contestar en público cualquier comentario, también preguntas y quejas, para que nadie quede ignorado delante de los demás.**
   - Cada comentario ofrece «Responder aquí» y «Escribirle en privado».
   - Se puede preparar respuesta para comentarios positivos, neutros y negativos; en los negativos el borrador pide revisión antes de aprobar.
   - El comentario respondido pasa a «Respondidos».
6. **Como dueño, quiero que los comentarios nuevos se busquen y se ordenen solos, para no tener que pulsar botones antes de ver quién quiere comprar.**
   - Los comentarios se buscan, ordenan y se prepara la respuesta sin que la pantalla esté abierta (solo preparar; el envío sigue siendo del dueño).
   - «Analizar sentimiento», «Analizar intención» y «Generar borradores» dejan de ser pasos obligatorios; queda un solo «Buscar ahora».
   - Todos los textos de la pantalla pasan la lista de palabras prohibidas (`qualify-ux` §3) con los reemplazos del hallazgo 4.

### Grupo C · Quieren comprar y Clientes interesados
7. **Como dueño, quiero responder a quien quiere comprar en tres pasos cortos y pasar al siguiente, para atender varias consultas seguidas sin perderme.**
   - La tarjeta va en pasos: «Qué preguntó» → «Qué le respondes» (borrador ya escrito, «Otra idea») → «Revisa y aprueba» con la frase de por dónde le llega; «Atrás» no borra lo escrito.
   - Al aprobar aparece «Listo. Le escribiste a @usuario.» con «Siguiente» y «Volver a comentarios».
   - La pestaña se llama «Quieren comprar (N)» y se muestra primero cuando N > 0.
8. **Como dueño, quiero escribirle por WhatsApp a cada cliente interesado desde la lista y saber a quién ya contacté, para que ninguno se enfríe.**
   - En el celular la lista es de tarjetas: nombre, qué le interesa, botón «Escribirle por WhatsApp».
   - Cada persona muestra «Pendiente» o «Ya le escribiste» como texto (no solo color).
   - El estado vacío muestra el enlace real del formulario con «Copiar enlace» y dice dónde compartirlo.
   - Hipótesis §5 pregunta 2 y 3: confirmar con Bianki y la agencia de viajes si contactan desde el número del negocio o el personal.
