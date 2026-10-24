# Épica — Qualify en palabras del dueño: navegación y experiencia

`[v5 · 2026-10-23 · product-owner · segunda ronda de decisiones del fundador]` · **Meegle:** Feature [m-24842956](https://project.larksuite.com/5h2wsx/story/detail/24842956) con 62 historias (Issues) enlazadas por el campo Feature; todas cargadas. Ninguna espera ya una decisión ni una medición: ATENDER-5 (m-24848534) quedó «No por ahora» (aparcada); CREAR-5 (m-24848531) está lista tras la medición del 2026-10-23 (§2b).

**Origen:** pedido del fundador (2026-10-23): «revisa todo el UX de mi sitio, genera un reporte, invoca al product owner y asígnale crear la épica y las historias para mejorar el UX de nuestra app, separa el trabajo por dominio/módulo, debe existir un patrón guideline de navegación por mi app».

**Evidencia:** auditoría del agente `ux-designer` por lectura de código, sin pruebas con clientes: [`ux-auditoria-2026-10.md`](ux-auditoria-2026-10.md) (hallazgos transversales T1–T11), [`ux-guia-navegacion.md`](ux-guia-navegacion.md) (mapa del menú, reglas N1–N13, §7 decisiones pendientes) y los siete informes [`ux-auditoria-2026-10/m1…m7`](ux-auditoria-2026-10/). Persona: [`perfil-cliente-pyme.md`](perfil-cliente-pyme.md). Todo lo que depende de cómo se comporta el dueño está marcado *hipótesis* en la historia.

**Restricciones firmadas que respetan todas las historias:** asistido, nunca autónomo (nada se publica ni se envía sin un toque del dueño, regla N13); sin programación en TikTok; sin componentes ni colores nuevos sin decisión del fundador y cambio previo en `docs/design-system.md` (la barra inferior del celular es la decisión 5); una sola Postgres.

**Toda historia de código incluye además** estos criterios: revisión local de experiencia (`ux-designer`, `qualify-ux` §6) antes de abrir el PR; prueba a 360 px de cada ruta tocada (N12); `just ci-lint` y `just ci-test` en verde.

## 1. Dominios

| Dominio | Prefijo | Fuente | Historias | P0 listas |
|---|---|---|---|---|
| Navegación e Inicio (transversal) | `[NAV]` | `ux-guia-navegacion.md`, m7 | 9 | 3 |
| Textos que nacen en el servidor (transversal) | `[BACKEND/copy]` | seguimiento de la ola 1 | 1 | 0 |
| Acceso, tu marca y tus redes | `[MARCA]` | m1 | 8 | 2 |
| Tus productos | `[PRODUCTOS]` | m2 | 6 | 1 |
| Crear publicación | `[CREAR]` | m3 | 7 | 2 |
| Aprobar, programar y publicar | `[PUBLICAR]` | m4 | 6 | 2 |
| Responder a clientes | `[ATENDER]` | m5 | 11 | 3 |
| WhatsApp | `[WHATSAPP]` | m6 | 8 | 5 |
| Resultados y menciones | `[RESULTADOS]` | m7 | 6 | 1 |

## 2. Decisiones del fundador (decididas 2026-10-23)

El fundador respondió una a una las once decisiones el 2026-10-23; están registradas en [`ux-guia-navegacion.md`](ux-guia-navegacion.md) §7 y N10 (y `qualify-ux` §3 y `perfil-cliente-pyme.md` §2 para la 11). Las revisiones técnicas y de costo abrieron tres decisiones nuevas (§4).

| # | Decisión | Qué se decidió | Historias afectadas |
|---|---|---|---|
| 1 | Inicio | Sí: Inicio nuevo en `/`; Menciones pasa a Resultados › «Quién habla de ti» | NAV-4 (m-24842962), RESULTADOS-5 (m-24843003) |
| 2 | Menú | Sí: el mapa de la guía §3 (Inicio · Atiende · Publica · Resultados · Tu negocio) | NAV-1 (m-24842957), RESULTADOS-5 (m-24843003) |
| 3 | Por responder | Uno solo + WhatsApp enlazado como pestaña; el módulo WhatsApp conserva respuesta automática y promociones | ATENDER-1 (m-24842990) |
| 4 | «Pronto» | Vitrina se elimina por completo; Creadores y Señales se quedan en el menú con «Pronto» en texto (N10 reescrita) | NAV-10 (m-24848515), NAV-1 (m-24842957) |
| 5 | Celular | Sí: barra inferior (Inicio · Por responder · Crear · Tu semana + «Más»), documentada primero en `docs/design-system.md` | NAV-7 (m-24842964) |
| 6 | Marca | Mínimo de 5 pasos (negocio y rubro, logo, colores, cómo hablas, redes); el resto a «Mejora tu marca (opcional)»; la app deja de bloquearse | MARCA-4 (m-24848529) |
| 7 | Invitación | Opción (b): avisar antes; con código sigue, sin código deja nombre, negocio y WhatsApp | MARCA-5 (m-24842968) |
| 8 | Costo | El dueño ve «creaciones del mes» («Te quedan 18 de 30 este mes»), nunca dinero; el costo en dólares solo lo ve el equipo | CREAR-5 (m-24848531) |
| 9 | Nombre de «Piezas» | «Por aprobar» | NAV-9 (m-24842958), CREAR-4 (m-24842979), CREAR-3 (m-24842981) |
| 10 | Moneda en Venezuela | Dólares (USD) por defecto, editable | MARCA-3 (m-24842967) |
| 11 | Palabras | «reel (video corto)» e «historia»; nunca «story» | CREAR-4 (m-24842979), PUBLICAR-5 (m-24842983), PRODUCTOS-6 (m-24842971), CREAR-2 (m-24848530) |

Además, antes de las once: «vitrina se elimina por completo, no tiene relación con nuestro producto por ahora» → NAV-10 (m-24848515).

## 2b. Decisiones del fundador 2026-10-23 (segunda ronda)

El fundador respondió las siete decisiones que habían quedado pendientes (antigua §6, preguntas 1-6, más dos textos). Todas están aplicadas en los tickets de Meegle el mismo día.

| # | Decisión | Qué se decidió | Historias afectadas | Estado en Meegle |
|---|---|---|---|---|
| 1 | Respuestas públicas (**enmienda QUA-22**) | Qualify prepara respuestas también para **preguntas y quejas**, no solo para comentarios positivos; el dueño siempre revisa y envía (asistido, nunca autónomo). En las quejas, la propuesta sugiere seguir por mensaje privado. QUA-22 («solo positivos») queda **enmendada**; la fila ADR 21c pasa de [PROPUESTO] a decidida (la escribe el arquitecto) | ATENDER-4b (m-24848533), ATENDER-4a (m-24848532) | ATENDER-4b desbloqueada → Todo |
| 2 | Clasificar comentarios en segundo plano | **No por ahora (fundador, 2026-10-23)** | ATENDER-5 (m-24848534) | Sigue en Backlog, etiqueta parking-lot |
| 3a | Presentador de 30 s | El **dueño sí puede crearlo**; usa varias creaciones del mes y, antes de crear, la app le dice cuántas: «Este video con presentador usa 25 de tus creaciones. Te quedarían {n} este mes.» (pesos v1: 30 s = 25, 15 s = 13); con saldo menor que 25 se ofrece la versión de 15 s | CREAR-5 (m-24848531) | Criterios actualizados |
| 3b | Medición de producción | data-scientist-fde puede hacer **una sola** lectura agregada, de solo lectura, en producción: conteo de creaciones por negocio y por tipo en los últimos 60 días (solo conteos; ni textos ni datos de clientes finales), para fijar la asignación mensual real. **Hecha el 2026-10-23:** [`creaciones-del-mes-medicion.md`](creaciones-del-mes-medicion.md). Solo 3 días de uso, todo de negocios de prueba y solo imagen con texto: **solo el peso de la imagen está confirmado** (1; p95 USD 0,068); los demás pesos salen de la tabla v5 sin uso real. La asignación se queda en 30; volver a medir cuando 3 clientes reales tengan 30 días de uso | CREAR-5 (m-24848531) | Desbloqueada (lista); la segunda medición es seguimiento |
| 4 | WhatsApp después de 24 h | Que el cliente haya escrito antes cuenta como permiso **solo para retomar su tema** con una plantilla de seguimiento (tipo utilidad, «te escribo por tu pedido…»); las promociones siguen necesitando permiso explícito. Aviso: «Para enviarle promociones, esta persona tiene que aceptar recibirlas.» y, solo si existe una plantilla de utilidad aprobada para pedirlo, el botón «Pedirle que acepte» | WHATSAPP-2 (m-24848535) | Criterios actualizados; sigue lista |
| 5 | «Reintentar» | Solo si el fallo es pasajero (sin conexión, Instagram caído): «Tu respuesta no salió: Instagram no respondió.» + «Reintentar». Si borraron el comentario: «Borraron ese comentario. Ya no se puede responder.», sin reintentar (textos revisados por UX) | ATENDER-9 (m-24849130) | Reescrita → Todo (ola 2) |
| 6 | Nombre de «Señales» | Pasa a llamarse **«Oportunidades»** en menú, `h1` y pestaña (N1), sigue con «Pronto» | RESULTADOS-6 (m-24849134), NAV-1 (m-24842957) | Desbloqueada → Todo |
| 7a | Textos de fallo al responder | Rechazada: «Tu respuesta no salió. Respóndela en Instagram.»; resultado desconocido: «No sabemos si salió. Revísalo en Instagram.» Se aplican directamente en el PR #243 (ATENDER-3, m-24842989) | ATENDER-3 (m-24842989), ATENDER-9 (m-24849130) | ATENDER-8 (m-24842988) no citaba los textos viejos: sin cambios |
| 7b | Aviso de menciones nuevas (QUA-152) | «Llegaron menciones nuevas.» con el botón «Verlas» | RESULTADOS-2 (m-24842999) | Comentario en el ticket; **seguimiento**: el aviso no existe aún en `main` (PR #246 lo dejó fuera), el texto aplica cuando se construya QUA-152 |

## 3. Lista de historias

| Ticket | Dominio | Historia | Prioridad | Tamaño | Área | Bloqueada por |
|---|---|---|---|---|---|---|
| [m-24842957](https://project.larksuite.com/5h2wsx/issue/detail/24842957) | `NAV-1` | Navegación: adoptar la guía, menú ordenado por los trabajos del dueño | P1 | L | reflex-ui-engineer | — |
| [m-24848515](https://project.larksuite.com/5h2wsx/issue/detail/24848515) | `NAV-10` | Navegación: eliminar Vitrina de la app | P0 | S | reflex-ui-engineer | — |
| [m-24842958](https://project.larksuite.com/5h2wsx/issue/detail/24842958) | `NAV-9` | Navegación: un nombre por lugar en menú, título y pestaña (N1) | P0 | S | reflex-ui-engineer | — |
| [m-24842959](https://project.larksuite.com/5h2wsx/issue/detail/24842959) | `NAV-8` | Navegación: ningún texto dice o insinúa que Qualify publica o responde solo (N13) | P0 | S | reflex-ui-engineer | — |
| [m-24842960](https://project.larksuite.com/5h2wsx/issue/detail/24842960) | `NAV-2` | Navegación: cada pestaña y ficha con su dirección; «atrás» del celular no saca del módulo (N5, N7) | P1 | M | reflex-ui-engineer | — |
| [m-24842961](https://project.larksuite.com/5h2wsx/issue/detail/24842961) | `NAV-3` | Navegación: ningún vacío sin salida y toda tarea termina con su siguiente paso (N3, N8) | P1 | M | reflex-ui-engineer | — |
| [m-24842962](https://project.larksuite.com/5h2wsx/issue/detail/24842962) | `NAV-4` | Navegación: Inicio en `/` con «Hoy tienes», «Para tu primera publicación» y «Así te fue» | P1 | L | reflex-ui-engineer + backend-engineer | — |
| [m-24842963](https://project.larksuite.com/5h2wsx/issue/detail/24842963) | `NAV-6` | Navegación: contadores de pendientes en el menú y en la pestaña del navegador (N11) | P1 | M | reflex-ui-engineer + backend-engineer | — |
| [m-24842964](https://project.larksuite.com/5h2wsx/issue/detail/24842964) | `NAV-7` | Navegación: barra inferior en el celular con Inicio, Por responder, Crear y Tu semana | P2 | M | reflex-ui-engineer | — |
| [m-24849129](https://project.larksuite.com/5h2wsx/issue/detail/24849129) | `NAV-11` | Textos del servidor: errores y etiquetas que llegan al dueño en inglés o con nombres internos | P1 | S | backend-engineer | — |
| [m-24842965](https://project.larksuite.com/5h2wsx/issue/detail/24842965) | `MARCA-1` | Tu marca: al terminar, «Tu marca está lista» y el botón «Crear mi primera publicación» | P0 | S | reflex-ui-engineer | — |
| [m-24842966](https://project.larksuite.com/5h2wsx/issue/detail/24842966) | `MARCA-2` | Tu marca: textos del acceso y del asistente en palabras del dueño (sin Brand Kit, brandboard, insights) | P0 | S | reflex-ui-engineer | — |
| [m-24842967](https://project.larksuite.com/5h2wsx/issue/detail/24842967) | `MARCA-3` | Acceso: crear la cuenta con cuatro campos con etiqueta y el país en lugar de zona horaria y moneda | P1 | M | reflex-ui-engineer | — |
| [m-24848529](https://project.larksuite.com/5h2wsx/issue/detail/24848529) | `MARCA-4` | Tu marca: lo mínimo en 5 pasos y el resto sin bloquear la app | P1 | L | reflex-ui-engineer + creative-engineer | — |
| [m-24842968](https://project.larksuite.com/5h2wsx/issue/detail/24842968) | `MARCA-5` | Acceso: el visitante sin invitación sabe antes de empezar que la necesita | P1 | M | reflex-ui-engineer + backend-engineer | — |
| [m-24842969](https://project.larksuite.com/5h2wsx/issue/detail/24842969) | `MARCA-6` | Tus redes: saber de un vistazo si mi Instagram funciona, qué puedo hacer y qué sigue al conectarlo | P1 | M | reflex-ui-engineer | — |
| [m-24842970](https://project.larksuite.com/5h2wsx/issue/detail/24842970) | `MARCA-7` | Tu marca: «Editar mi marca» abre en el resumen de mi marca, no en el ranking de referentes | P2 | M | reflex-ui-engineer | — |
| [m-24849135](https://project.larksuite.com/5h2wsx/issue/detail/24849135) | `MARCA-8` | Tu marca: cambiar «¿Eres influencer o una marca?» y «rubro» por palabras más usadas | P2 | S | reflex-ui-engineer | — |
| [m-24842971](https://project.larksuite.com/5h2wsx/issue/detail/24842971) | `PRODUCTOS-6` | Tus productos: textos y errores en palabras del dueño | P0 | S | reflex-ui-engineer | — |
| [m-24842972](https://project.larksuite.com/5h2wsx/issue/detail/24842972) | `PRODUCTOS-1` | Tus productos: «Crear publicación con este producto» abre Crear con el producto ya elegido | P1 | M | reflex-ui-engineer | — |
| [m-24842973](https://project.larksuite.com/5h2wsx/issue/detail/24842973) | `PRODUCTOS-2` | Tus productos: volver a mi publicación con el producto que agregué (N4) | P2 | M | reflex-ui-engineer | — |
| [m-24842974](https://project.larksuite.com/5h2wsx/issue/detail/24842974) | `PRODUCTOS-3` | Tus productos: agregar un producto en tres pasos desde el celular, la foto primero | P1 | M | reflex-ui-engineer | — |
| [m-24842976](https://project.larksuite.com/5h2wsx/issue/detail/24842976) | `PRODUCTOS-4` | Tus productos: editar sin perder cambios, en pantalla completa en el celular y con su dirección | P1 | M | reflex-ui-engineer | — |
| [m-24842977](https://project.larksuite.com/5h2wsx/issue/detail/24842977) | `PRODUCTOS-5` | Tus productos: marcar la foto principal y quitar fotos sin equivocarme | P2 | S | reflex-ui-engineer | — |
| [m-24842978](https://project.larksuite.com/5h2wsx/issue/detail/24842978) | `CREAR-1` | Crear: al aprobar, «Aprobada. Todavía no se publica.» con el botón «Elegir día y hora» | P0 | S | reflex-ui-engineer | — |
| [m-24842979](https://project.larksuite.com/5h2wsx/issue/detail/24842979) | `CREAR-4` | Crear: todo dice «publicación» y habla como el dueño (sin POST, caption, CTA, HITL, Brand Kit ni proveedores) | P0 | M | reflex-ui-engineer | — |
| [m-24848530](https://project.larksuite.com/5h2wsx/issue/detail/24848530) | `CREAR-2` | Crear: una publicación en cuatro pasos cortos, lo opcional detrás de «Más opciones» | P1 | L | reflex-ui-engineer (revisa creative-engineer) | — |
| [m-24842980](https://project.larksuite.com/5h2wsx/issue/detail/24842980) | `CREAR-6` | Crear: en el celular ver todos los tipos con su explicación y escribir los datos clave sin comas | P1 | S | reflex-ui-engineer | — |
| [m-24842981](https://project.larksuite.com/5h2wsx/issue/detail/24842981) | `CREAR-3` | Crear: en Por aprobar, estados en texto y un solo botón claro por publicación | P1 | M | reflex-ui-engineer | — |
| [m-24848531](https://project.larksuite.com/5h2wsx/issue/detail/24848531) | `CREAR-5` | Crear: el dueño ve sus creaciones del mes («Te quedan 18 de 30 este mes»), nunca dinero | P2 | M | reflex-ui-engineer + creative-engineer + data-scientist-fde | — (medida 2026-10-23, §2b-3b) |
| [m-24849133](https://project.larksuite.com/5h2wsx/issue/detail/24849133) | `CREAR-7` | Crear: los títulos «Hashtags» pasan a «Etiquetas» | P2 | S | reflex-ui-engineer | — |
| [m-24842982](https://project.larksuite.com/5h2wsx/issue/detail/24842982) | `PUBLICAR-1` | Tu semana: en el celular, «Tienes {n} publicaciones aprobadas esperando día y hora» con su botón | P0 | S | reflex-ui-engineer | — |
| [m-24842983](https://project.larksuite.com/5h2wsx/issue/detail/24842983) | `PUBLICAR-5` | Tu semana y Publicar ahora: textos y errores en español sencillo (sin POST, caption, Stories, Cold/Hot, tenant, R2) | P0 | S | reflex-ui-engineer | — |
| [m-24842984](https://project.larksuite.com/5h2wsx/issue/detail/24842984) | `PUBLICAR-2` | Tu semana: aprobar o descartar una publicación desde su ficha | P1 | M | reflex-ui-engineer | — |
| [m-24842985](https://project.larksuite.com/5h2wsx/issue/detail/24842985) | `PUBLICAR-3` | Tu semana: programar eligiendo solo día y hora, o «Ahora» | P1 | M | reflex-ui-engineer | — |
| [m-24842986](https://project.larksuite.com/5h2wsx/issue/detail/24842986) | `PUBLICAR-4` | Publicar ahora: subir algo del teléfono en tres pasos y saber qué sigue al publicar | P1 | M | reflex-ui-engineer | — |
| [m-24842987](https://project.larksuite.com/5h2wsx/issue/detail/24842987) | `PUBLICAR-6` | Tu semana: volver siempre a mi semana y usarla con el pulgar | P2 | M | reflex-ui-engineer | — |
| [m-24842988](https://project.larksuite.com/5h2wsx/issue/detail/24842988) | `ATENDER-8` | Atender: comentarios, conversaciones e interesados en palabras del dueño, sin números internos | P0 | S | reflex-ui-engineer | — |
| [m-24842989](https://project.larksuite.com/5h2wsx/issue/detail/24842989) | `ATENDER-3` | Comentarios: primero las respuestas listas para aprobar; configurar qué revisar, detrás de «Más opciones» | P0 | M | reflex-ui-engineer | — |
| [m-24848532](https://project.larksuite.com/5h2wsx/issue/detail/24848532) | `ATENDER-4a` | Comentarios: medir la clasificación y los borradores de respuesta antes de responder a todos | P0 | M | data-scientist-fde | — |
| [m-24848533](https://project.larksuite.com/5h2wsx/issue/detail/24848533) | `ATENDER-4b` | Comentarios: responder en público cualquier comentario, también preguntas y quejas | P0 | M | backend-engineer + reflex-ui-engineer | — (QUA-22 enmendada, §2b-1) |
| [m-24848534](https://project.larksuite.com/5h2wsx/issue/detail/24848534) | `ATENDER-5` | Comentarios: buscar, ordenar y preparar respuestas solos, sin que el dueño tenga la pantalla abierta | P0 | L | backend-engineer + reflex-ui-engineer | «No por ahora» (fundador, 2026-10-23); parking-lot |
| [m-24842990](https://project.larksuite.com/5h2wsx/issue/detail/24842990) | `ATENDER-1` | Atender: un solo «Por responder» con los pendientes de cada canal y pestañas con su dirección | P1 | L | reflex-ui-engineer + backend-engineer | — |
| [m-24842991](https://project.larksuite.com/5h2wsx/issue/detail/24842991) | `ATENDER-6` | Quieren comprar: responder en tres pasos cortos y pasar a la siguiente consulta | P1 | M | reflex-ui-engineer | — |
| [m-24842992](https://project.larksuite.com/5h2wsx/issue/detail/24842992) | `ATENDER-7` | Clientes interesados: escribirles por WhatsApp desde la lista y saber a quién ya contacté | P2 | M | reflex-ui-engineer + backend-engineer | — |
| [m-24849130](https://project.larksuite.com/5h2wsx/issue/detail/24849130) | `ATENDER-9` | Comentarios: «Reintentar» una respuesta que no salió por un fallo pasajero | P2 | M | backend-engineer + reflex-ui-engineer | — |
| [m-24849131](https://project.larksuite.com/5h2wsx/issue/detail/24849131) | `ATENDER-10` | Quieren comprar: la tarjeta dice si el mensaje privado salió o falló | P1 | M | reflex-ui-engineer + backend-engineer | — |
| [m-24849132](https://project.larksuite.com/5h2wsx/issue/detail/24849132) | `ATENDER-11` | Comentarios: un solo aviso de error al ordenar los comentarios | P2 | S | reflex-ui-engineer | — |
| [m-24842993](https://project.larksuite.com/5h2wsx/issue/detail/24842993) | `WHATSAPP-1` | WhatsApp: con el chat vencido, decir qué pasa y llevar a los mensajes aprobados | P0 | S | reflex-ui-engineer | — |
| [m-24842994](https://project.larksuite.com/5h2wsx/issue/detail/24842994) | `WHATSAPP-8` | WhatsApp: textos sin opt-in, leads, Marketing, Lanzar ni Revocar; distintivos de los chats explicados | P0 | S | reflex-ui-engineer | — |
| [m-24842995](https://project.larksuite.com/5h2wsx/issue/detail/24842995) | `WHATSAPP-3` | WhatsApp: publicar el menú automático con un solo botón y saber qué sigue | P0 | M | reflex-ui-engineer | — |
| [m-24848535](https://project.larksuite.com/5h2wsx/issue/detail/24848535) | `WHATSAPP-2` | WhatsApp: enviar un mensaje aprobado desde el chat vencido | P0 | M | backend-engineer + reflex-ui-engineer | — |
| [m-24848536](https://project.larksuite.com/5h2wsx/issue/detail/24848536) | `WHATSAPP-4` | WhatsApp: armar el menú automático en cuatro pasos, sin identificadores técnicos | P0 | L | reflex-ui-engineer + backend-engineer | — |
| [m-24842996](https://project.larksuite.com/5h2wsx/issue/detail/24842996) | `WHATSAPP-5` | WhatsApp: enviar una promoción en tres pasos (mensaje, a quién, revisar) | P1 | M | reflex-ui-engineer | — |
| [m-24842997](https://project.larksuite.com/5h2wsx/issue/detail/24842997) | `WHATSAPP-6` | WhatsApp: crear un mensaje de promoción guiado para que lo aprueben a la primera | P1 | M | reflex-ui-engineer | — |
| [m-24842998](https://project.larksuite.com/5h2wsx/issue/detail/24842998) | `WHATSAPP-7` | WhatsApp: cuatro pestañas con nombres de tareas, «Tu número» en una línea y tablas como tarjetas en el celular | P1 | L | reflex-ui-engineer | — |
| [m-24842999](https://project.larksuite.com/5h2wsx/issue/detail/24842999) | `RESULTADOS-2` | Resultados: Menciones, Clarity y Señales en palabras del dueño (sin Rage clicks, snapshot, placeholder ni roadmap) | P0 | M | reflex-ui-engineer | — |
| [m-24843000](https://project.larksuite.com/5h2wsx/issue/detail/24843000) | `RESULTADOS-1` | Menciones: ver las malas con un toque, saber qué hacer y leerlas completas en el celular | P1 | M | reflex-ui-engineer | — |
| [m-24843001](https://project.larksuite.com/5h2wsx/issue/detail/24843001) | `RESULTADOS-3` | Tu página web: cuántas personas la visitaron y qué arreglar primero, sin entender de analítica | P1 | L | reflex-ui-engineer | — |
| [m-24843002](https://project.larksuite.com/5h2wsx/issue/detail/24843002) | `RESULTADOS-4` | Tu página web: el equipo conecta Clarity desde Configuración y el dueño nunca ve claves | P1 | M | reflex-ui-engineer | — |
| [m-24843003](https://project.larksuite.com/5h2wsx/issue/detail/24843003) | `RESULTADOS-5` | Resultados: un solo lugar con Redes, WhatsApp, Tu página web y «Quién habla de ti» | P2 | L | reflex-ui-engineer + backend-engineer | — |
| [m-24849134](https://project.larksuite.com/5h2wsx/issue/detail/24849134) | `RESULTADOS-6` | Resultados: «Señales» pasa a llamarse «Oportunidades» en menú, título y pestaña | P2 | S | reflex-ui-engineer | — |

## 4. Revisiones de arquitecto y data scientist (2026-10-23)

Las siete historias que esperaban revisión **pasaron con cambios**; los cambios están aplicados en
cada ticket (§8) y ya no queda ningún borrador. ATENDER-4 se separó en ATENDER-4a (m-24848532) (medición) y
ATENDER-4b (m-24848533) (producto). La revisión también corrigió MARCA-5 (m-24842968): no existe captura de interés, así que
se escribe en el módulo de leads de un tenant de la casa (`QUALIFY_INTEREST_TENANT_ID`).

| Historia | Resultado | Estado |
|---|---|---|
| MARCA-4 (m-24848529) — marca mínima en 5 pasos | Arquitecto: «Tus redes» primero con «No tengo redes»; `persist_brand_kit(adopt_voice=True)` tras el paso 5; progreso por nombre de paso; sin ADR | Lista |
| CREAR-2 (m-24848530) — crear en 4 pasos | Arquitecto: lo obligatorio de cada tipo va en el paso 1; criterio «escribir el tema y Siguiente hasta Crear» | Lista |
| WHATSAPP-2 (m-24848535) — mensaje aprobado desde el chat vencido | Arquitecto: outbox `template_reply` + migración; v1 solo con permiso activo; faltan tarifas de +58 y +598 | Lista (v1) |
| WHATSAPP-4 (m-24848536) — menú automático en 4 pasos | Arquitecto: identificadores slug + sufijo, nunca se regeneran; depende de WHATSAPP-3 (m-24842995) | Lista |
| ATENDER-4a (m-24848532) — medir clasificación y borradores | Data scientist: ~400 comentarios, κ ≥ 0,7, umbrales por clase, Haiku 5.5 en lugar de robertuito, ≈ USD 1,5 | Lista |
| ATENDER-4b (m-24848533) — responder en público cualquier comentario | Arquitecto: `instagram_manage_comments` no concedido en App Review (riesgo para clientes nuevos); la regla de solo positivos es deliberada (QUA-22) | Lista (QUA-22 enmendada, §2b-1); depende de ATENDER-4a (m-24848532) |
| ATENDER-5 (m-24848534) — comentarios preparados en segundo plano | Arquitecto: sin proceso nuevo (webhook + `conversations-worker`), tope diario 500; depende de QUA-147 y ATENDER-4a (m-24848532) | **No por ahora** (fundador, 2026-10-23); aparcada |
| CREAR-5 (m-24848531) — creaciones del mes | Data scientist: 1 creación = USD 0,15; pesos versionados; 30 por mes; devolución si falla | Lista: presentador de 30 s para el dueño con aviso previo (§2b-3a); medición hecha, solo el peso de imagen confirmado (§2b-3b) |

## 5. Orden sugerido, por olas

**Estado de la ola 1 (2026-10-23):** en PRs #235–#249; todos sus tickets en RESOLVED salvo PUBLICAR-5 (m-24842983) y WHATSAPP-8 (m-24842994), que esperan merges y suman los textos del seguimiento. La revisión de la ola dejó siete historias nuevas: NAV-11 (m-24849129), ATENDER-9 (m-24849130), ATENDER-10 (m-24849131), ATENDER-11 (m-24849132), CREAR-7 (m-24849133), RESULTADOS-6 (m-24849134) y MARCA-8 (m-24849135).

**Ola 1 — arreglos rápidos que destraban (P0, listos, sin decisión).** Empezar por NAV-10 (m-24848515)
(eliminar Vitrina, decisión del fundador 2026-10-23) y enseguida NAV-9 (m-24842958), en ese orden y no en
paralelo: son las dos únicas que tocan el menú y los títulos de pestaña (`Qualify/ui/layout.py`,
`Qualify/Qualify.py`). Las historias de texto de cada dominio no tocan esos archivos y pueden ir en
paralelo, una rama por dominio.

| Orden | Historia | Tamaño | Archivos principales |
|---|---|---|---|
| 0 | NAV-10 (m-24848515) — eliminar Vitrina | S | borra `vitrina_*.py`; `ui/layout.py`, `Qualify.py`, `docs/design-system.md`, `docs/plan-migracion-liquid-glass.md` |
| 1 | NAV-9 (m-24842958) — un nombre por lugar (después de NAV-10 (m-24848515)) | S | `ui/layout.py`, `Qualify.py`, `page_header` de cada página |
| 2 | CREAR-1 (m-24842978) — al aprobar, «Elegir día y hora» | S | `creative_pages.py`, `creative_state.py` |
| 2 | PUBLICAR-1 (m-24842982) — «Tienes {n} publicaciones aprobadas…» | S | `planner_page.py` |
| 2 | MARCA-1 (m-24842965) — «Tu marca está lista» | S | `creative_wizard_pages.py` |
| 2 | NAV-8 (m-24842959) — nada dice que Qualify actúa solo | S | `planner_drawer.py`, `connections_page.py`, `connections_vm.py` |
| 2 | WHATSAPP-1 (m-24842993) — chat vencido con salida | S | `whatsapp_tab_chats.py`, `whatsapp_chats_vm.py` |
| 3 | ATENDER-3 (m-24842989) — comentarios: primero las respuestas listas | M | `inbox_page.py` |
| 3 | WHATSAPP-3 (m-24842995) — publicar el menú con un botón | M | `whatsapp_tab_menu.py` |
| 4 | Textos por dominio: MARCA-2 (m-24842966), PRODUCTOS-6 (m-24842971), CREAR-4 (m-24842979), PUBLICAR-5 (m-24842983), ATENDER-8 (m-24842988), WHATSAPP-8 (m-24842994), RESULTADOS-2 (m-24842999) | S–M | los de cada dominio |

**Ola 2 — guía base, menú nuevo, hubs y lo que pasó la revisión (listos).**
Primero la base de direcciones y el menú, en este orden: NAV-2 (m-24842960) (`?tab=`) → NAV-1 (m-24842957) (menú del mapa §3,
Creadores y Oportunidades (antes Señales) con «Pronto»; después de NAV-10 (m-24848515) y NAV-9 (m-24842958)). Luego los hubs, en paralelo:
NAV-4 (m-24842962) (Inicio en `/`, ui + backend) y ATENDER-1 (m-24842990) (Por responder con WhatsApp enlazado, ui + backend).
Al frente, los P0 que pasaron la revisión: WHATSAPP-2 (m-24848535) (después de WHATSAPP-1 (m-24842993)), WHATSAPP-4 (m-24848536) (después de
WHATSAPP-3 (m-24842995)) y ATENDER-4a (m-24848532) (data scientist, puede empezar ya), y tras ella ATENDER-4b (m-24848533) (desbloqueada, §2b-1). Con ellos: MARCA-4 (m-24848529) y CREAR-2 (m-24848530) (L).
Desbloqueadas por la segunda ronda (§2b): ATENDER-9 (m-24849130) («Reintentar» solo en fallos pasajeros, tras ATENDER-3 (m-24842989)) y RESULTADOS-6 (m-24849134) («Oportunidades», tras NAV-1 (m-24842957)).
Sin dependencia entre sí: NAV-11 (m-24849129) (textos del servidor, backend), ATENDER-10 (m-24849131) (resultado del mensaje privado), NAV-3 (m-24842961), NAV-6 (m-24842963), MARCA-3 (m-24842967), MARCA-5 (m-24842968) (ui + backend), MARCA-6 (m-24842969); PRODUCTOS-1 (m-24842972),
PRODUCTOS-3 (m-24842974), PRODUCTOS-4 (m-24842976); CREAR-3 (m-24842981), CREAR-6 (m-24842980); PUBLICAR-2 (m-24842984), PUBLICAR-3 (m-24842985), PUBLICAR-4 (m-24842986); ATENDER-6 (m-24842991);
WHATSAPP-5 (m-24842996), WHATSAPP-6 (m-24842997), WHATSAPP-7 (m-24842998); RESULTADOS-1 (m-24843000), RESULTADOS-4 (m-24843002) → RESULTADOS-3 (m-24843001).

**Ola 3 — lo que depende de la ola 2 (P2).** RESULTADOS-5 (m-24843003) (Resultados con «Quién habla de ti»,
después de NAV-4 (m-24842962), RESULTADOS-1 (m-24843000) y RESULTADOS-3 (m-24843001)); NAV-7 (m-24842964) (barra inferior: primero el PR que documenta
el patrón en `docs/design-system.md`, después el código). CREAR-5 (m-24848531), lista desde la medición del 2026-10-23 (P2).
ATENDER-5 (m-24848534) queda fuera de las olas: «No por ahora» (fundador, 2026-10-23).

**Ola 4 — pulido (P2).** PRODUCTOS-2 (m-24842973), PRODUCTOS-5 (m-24842977), PUBLICAR-6 (m-24842987), ATENDER-7 (m-24842992), MARCA-7 (m-24842970), ATENDER-11 (m-24849132), CREAR-7 (m-24849133) y MARCA-8 (m-24849135) (esta última solo si la validación con dueños la confirma).

El celular (N12) no es una historia aparte: cada historia que toca una pantalla lo trae en sus
criterios.

## 6. Preguntas abiertas para el fundador

Las preguntas 1-6 de la v4 están **decididas** (§2b, 2026-10-23). Quedan:

1. ~~Peso del presentador de 30 s~~ — **cerrada (2026-10-23):** el «6» era una ilustración, no una cifra del
   fundador. Con los pesos v1, 30 s = 25 y 15 s = 13; con saldo menor que 25 se ofrece la de 15 s (CREAR-5 (m-24848531)).
2. **Fila ADR 21c** (enmienda de QUA-22): la redacta `principal-architect` en `docs/arquitectura.md`; el PO no
   escribe ADRs.
3. **«Leads» en el glosario**: `docs/design-system.md` §7.2 todavía dice «lead»; se corrige en el PR de
   NAV-9 (m-24842958).
4. **¿Clarity la usa algún cliente hoy?** Por eso RESULTADOS-3 (m-24843001) es P1 y no P0.

## 7. Fuera de esta épica (aparcado con motivo)

- **Invitar desde el chat de WhatsApp a recibir promociones** (m6 hallazgo 8, L): *hipótesis* sobre
  cómo el dueño pide permiso (perfil §5 pregunta 8) y toca consentimiento; se carga cuando haya
  evidencia de un cliente.
- **Unificar los chats de WhatsApp con Conversaciones** en una sola bandeja: lo resuelve en parte
  ATENDER-1 (m-24842990) (pestaña WhatsApp enlazada); unificar del todo es una decisión de arquitectura aparte.
- **Avisos fuera de la app** (correo o notificaciones de pendientes): no lo pidió ningún cliente;
  NAV-6 (m-24842963) cubre el contador dentro de la app.

## 8. Historias en detalle

### [NAV] Navegación e Inicio (transversal)

#### NAV-1 · [m-24842957](https://project.larksuite.com/5h2wsx/issue/detail/24842957) — Navegación: adoptar la guía, menú ordenado por los trabajos del dueño

*Como dueño de un local, quiero que el menú esté ordenado por lo que vengo a hacer (ver qué me toca hoy, atender, publicar, ver cómo me va, ajustar mi negocio), para encontrar cada cosa sin aprender cómo está construida la app.*

**P1 · L · reflex-ui-engineer** · Depende de: NAV-10 (m-24848515), NAV-9 (m-24842958), NAV-2 (m-24842960)
- Lista para empezar.

Criterios de aceptación:
- El menú del cliente tiene las 12 entradas de la guía §3, en su orden, más Creadores y Oportunidades (antes Señales, §2b-6); ninguna demo ni herramienta del equipo (N10).
- Creadores y Oportunidades muestran «Pronto» como texto visible; tocarlas nunca lleva a una pantalla vacía (N10).
- Cada entrada del menú, el `h1` de su `page_header` y el título de pestaña `Qualify · <nombre>` son idénticos (N1); una prueba offline lo comprueba recorriendo `NAV_ITEMS`.
- Abrir `/inbox`, `/conversations`, `/leads`, `/clarity` y `/stories` lleva a su nuevo lugar sin error; ningún enlace guardado se rompe.
- Las zonas se llaman «Atiende» y «Publica» y usan los mismos tintes `listen` / `publish` de hoy.

Fuera de alcance: La pantalla Inicio (NAV-4 (m-24842962)), «Por responder» (ATENDER-1 (m-24842990)) y «Resultados» (RESULTADOS-5 (m-24843003)): esta historia solo mueve el menú y las redirecciones; si alguno no existe aún, su entrada apunta a la pantalla actual. La barra inferior del celular (NAV-7 (m-24842964)).

Evidencia: `docs/ux-guia-navegacion.md §2, §3, §4 (N1, N10)`; `docs/ux-auditoria-2026-10.md T3, T11`; `docs/ux-auditoria-2026-10/m7-escucha-medicion.md hallazgos 6-7`

#### NAV-10 · [m-24848515](https://project.larksuite.com/5h2wsx/issue/detail/24848515) — Navegación: eliminar Vitrina de la app

*Como dueño de un local, quiero que la app no me muestre la demo de otro negocio, para ver solo lo que es mío.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- El menú no tiene ninguna entrada «Vitrina» (N10).
- Abrir `/vitrina` no muestra la demo: redirige a `/` sin error.
- `grep -ri vitrina Qualify/ assets/` no devuelve nada.
- `docs/design-system.md` ya no muestra Vitrina en el diagrama ni en el pie del menú, ni la excepción de voseo; `docs/plan-migracion-liquid-glass.md` quita `vitrina_page.py` del lote A.

Fuera de alcance: Creadores y Oportunidades (antes Señales): se quedan con «Pronto» (decisión 4, NAV-1 (m-24842957)). Cualquier otro cambio en el menú (NAV-9 (m-24842958), NAV-1 (m-24842957)).

Evidencia: Decisión del fundador, 2026-10-23: «vitrina se elimina por completo, no tiene relación con nuestro producto por ahora»; `docs/ux-guia-navegacion.md §3, §7`; `docs/ux-auditoria-2026-10.md T11`; `docs/ux-auditoria-2026-10/m7-escucha-medicion.md hallazgo 6`

#### NAV-9 · [m-24842958](https://project.larksuite.com/5h2wsx/issue/detail/24842958) — Navegación: un nombre por lugar en menú, título y pestaña (N1)

*Como dueño, quiero que cada lugar tenga un solo nombre, en mis palabras, en el menú, en el título de la pantalla y en la pestaña del navegador, para saber siempre dónde estoy.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Para cada entrada del menú, el texto de `layout.py`, el `h1` del `page_header` y el `title` de `add_page` coinciden (N1); una prueba offline lo verifica.
- Ninguna entrada del menú, título ni pestaña contiene «Brand Kit», «Catálogo», «Conexiones», «pieza», «Piezas», «Planificador», «Stories», «Interacciones», «Leads», «Clarity» ni «Borrador».
- Los textos de «volver» que nombran estas pantallas usan el nombre nuevo (N7): «‹ Tus productos», «‹ Tu semana», «‹ Por aprobar».

Fuera de alcance: Mover o agrupar entradas (NAV-1 (m-24842957), bloqueada por decisiones 2 y 4). Los textos dentro de cada pantalla (historias de texto de cada dominio).

Evidencia: `docs/ux-guia-navegacion.md §4 N1, N7`; `docs/ux-auditoria-2026-10.md T4`; `docs/ux-auditoria-2026-10/m1 hallazgos 4 y 6`; `docs/ux-auditoria-2026-10/m3 hallazgo 12`; `docs/ux-auditoria-2026-10/m4 H8`; `docs/ux-auditoria-2026-10/m5 hallazgo 4`; `docs/ux-auditoria-2026-10/m7 hallazgo 12`

#### NAV-8 · [m-24842959](https://project.larksuite.com/5h2wsx/issue/detail/24842959) — Navegación: ningún texto dice o insinúa que Qualify publica o responde solo (N13)

*Como dueño, quiero leer claramente que nada sale sin mi aprobación, para no tener miedo de que la app publique o conteste a mis clientes por su cuenta.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Los cinco textos quedan exactamente como en la propuesta.
- `grep -rniE "autom[aá]tica|por ti" Qualify/*.py` no devuelve ningún texto visible al cliente que diga que Qualify publica o responde solo (N13).
- Ningún texto visible del Planificador usa la palabra «evento».

Evidencia: `docs/ux-guia-navegacion.md §4 N13`; `docs/ux-auditoria-2026-10.md T9`; `docs/ux-auditoria-2026-10/m1 hallazgo 5`; `docs/ux-auditoria-2026-10/m4 H9`; Decisión firmada: asistido, nunca autónomo (ADR 21, qualify-context §3)

#### NAV-2 · [m-24842960](https://project.larksuite.com/5h2wsx/issue/detail/24842960) — Navegación: cada pestaña y ficha con su dirección; «atrás» del celular no saca del módulo (N5, N7)

*Como dueño que usa el celular, quiero que «atrás» y recargar me dejen donde estaba, para no perder la pestaña o la ficha que tenía abierta.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- En `/whatsapp`, `/conversations` e `/inbox`, cambiar de pestaña o vista cambia la URL; recargar la conserva; «atrás» del navegador vuelve a la pestaña anterior (N5).
- Abrir `/whatsapp?tab=plantillas` directamente muestra esa pestaña.
- Ningún botón o enlace de volver del alcance dice solo «Volver» o «‹» (N7).

Fuera de alcance: La ficha de producto con ruta propia (PRODUCTOS-4 (m-24842976)). Reagrupar pestañas de WhatsApp (WHATSAPP-7 (m-24842998)).

Evidencia: `docs/ux-guia-navegacion.md §4 N5, N7`; `docs/ux-auditoria-2026-10.md T6`; `docs/ux-auditoria-2026-10/m6 «Navegación»`; `docs/ux-auditoria-2026-10/m5 hallazgo 7, historia 3`

#### NAV-3 · [m-24842961](https://project.larksuite.com/5h2wsx/issue/detail/24842961) — Navegación: ningún vacío sin salida y toda tarea termina con su siguiente paso (N3, N8)

*Como dueño, quiero que cada pantalla vacía me diga qué falta y me lleve a hacerlo, y que al terminar algo me digan «listo» y qué sigue, para no quedarme sin saber qué hacer.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Cada `empty_state(` de una pantalla del cliente tiene `action=`, salvo las excepciones listadas en el PR (N8).
- Ninguna acción Guardar / Enviar / Aprobar / Publicar / Programar tiene un `rx.toast` como único resultado (N3).
- Con cero pendientes en conversaciones aparece «¡Al día! No hay nadie esperando tu respuesta.» con el botón «Crear publicación».

Fuera de alcance: Los siguientes pasos que ya tienen historia propia en su dominio (ver Contexto).

Evidencia: `docs/ux-guia-navegacion.md §4 N3, N8`; `docs/ux-auditoria-2026-10.md T2`; `docs/ux-auditoria-2026-10/m1-m6 (callejones listados en «Navegación» de cada informe)`

#### NAV-4 · [m-24842962](https://project.larksuite.com/5h2wsx/issue/detail/24842962) — Navegación: Inicio en `/` con «Hoy tienes», «Para tu primera publicación» y «Así te fue»

*Como dueño de un local, quiero abrir la app y ver qué tengo pendiente hoy y cómo me fue esta semana, para resolverlo en dos minutos sin buscar en el menú.*

**P1 · L · reflex-ui-engineer + backend-engineer**
- Lista para empezar.

Criterios de aceptación:
- Entrar a la cuenta, terminar la marca y «Seguir después» de un asistente llevan a `/` = Inicio; Menciones se abre en su propia ruta (N2).
- Inicio con 0 datos no está vacío: muestra «Para tu primera publicación» o «Todo al día» con su botón (N8).
- Cada cifra es una `card(interactive=True)` que abre la lista ya filtrada (N11).
- Los conteos respetan RLS: una prueba con dos tenants muestra solo los del tenant activo.
- A 360 px: una columna, objetivos ≥ 44 px (N12). Qué cifras importan al dueño es *hipótesis* (perfil §5 pregunta 7).

Fuera de alcance: Resultados como hub con pestañas (RESULTADOS-5 (m-24843003)). Avisos fuera de la app (correo, notificaciones).

Evidencia: `docs/ux-guia-navegacion.md §4 N2, N11; §7 decisión 1`; `docs/ux-auditoria-2026-10.md T1`; `docs/ux-auditoria-2026-10/m7 hallazgos 1-2, historias 1-3`; `docs/ux-auditoria-2026-10/m1 hallazgo 2, historia D1`

#### NAV-6 · [m-24842963](https://project.larksuite.com/5h2wsx/issue/detail/24842963) — Navegación: contadores de pendientes en el menú y en la pestaña del navegador (N11)

*Como dueño, quiero ver en el menú cuántas cosas me esperan (por responder, por aprobar, por programar), para enterarme sin entrar a buscar en cada pantalla.*

**P1 · M · reflex-ui-engineer + backend-engineer**
- Lista para empezar.

Criterios de aceptación:
- Cada entrada con pendientes muestra el número; con 0 no muestra nada.
- Responder un mensaje o aprobar una publicación baja el contador sin recargar la página.
- El título de la pestaña empieza por «(N)» cuando hay pendientes.
- No se agregan colores ni componentes nuevos; los conteos respetan RLS.

Fuera de alcance: Notificaciones push o por correo.

Evidencia: `docs/ux-guia-navegacion.md §4 N11`; `docs/ux-auditoria-2026-10/m5 hallazgo 9, historia 2`; `docs/ux-auditoria-2026-10/m4 historia 8`

#### NAV-7 · [m-24842964](https://project.larksuite.com/5h2wsx/issue/detail/24842964) — Navegación: barra inferior en el celular con Inicio, Por responder, Crear y Tu semana

*Como dueño que usa Qualify con una mano entre clientes, quiero tener a un toque lo que más uso, para no abrir el menú cada vez.*

**P2 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Existe la sección del patrón en `docs/design-system.md`, aprobada por el fundador, antes del PR de código.
- A 360 px la barra muestra 4 accesos + «Más», objetivos ≥ 44 px, y no tapa contenido ni botones principales.
- En escritorio no aparece.

Fuera de alcance: Cambiar el cajón actual de escritorio.

Evidencia: `docs/ux-guia-navegacion.md §6; §7 decisión 5`; `docs/ux-auditoria-2026-10.md T10`

### [BACKEND/copy] Textos que nacen en el servidor (transversal)

#### NAV-11 · [m-24849129](https://project.larksuite.com/5h2wsx/issue/detail/24849129) — Textos del servidor: errores y etiquetas que llegan al dueño en inglés o con nombres internos

*Como dueño, quiero que los mensajes que vienen del sistema también estén en mis palabras, para no encontrarme frases en inglés o técnicas en medio de una pantalla ya traducida.*

**P1 · S · backend-engineer**
- Lista para empezar.

Criterios de aceptación:
- Las tres cadenas quedan exactamente como en la propuesta y ninguna llega en inglés a la pantalla.
- Un barrido de `CatalogError(`, `raise …Error("` y etiquetas de campos en `packages/api` lista en el PR cualquier otra cadena que llegue al dueño y la corrige.
- Pruebas offline actualizadas.

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23); qualify-copy-es; MARCA-2 (m-24842966) — etiquetas aprobadas

### [MARCA] Acceso, tu marca y tus redes

#### MARCA-1 · [m-24842965](https://project.larksuite.com/5h2wsx/issue/detail/24842965) — Tu marca: al terminar, «Tu marca está lista» y el botón «Crear mi primera publicación»

*Como dueño que acaba de terminar su marca, quiero que me lleven a crear mi primera publicación, para ver el resultado enseguida.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Al terminar la marca se ve exactamente «Tu marca está lista» con los tres accesos de la propuesta (N3).
- Ya no se aterriza en Menciones al terminar; el texto «Mejorar tu perfil» desaparece.
- Botones de la tarjeta con área táctil ≥ 44 px (N12).

Fuera de alcance: Acortar el asistente (MARCA-4 (m-24848529)). Inicio (NAV-4 (m-24842962)): cuando exista, «Seguir después» lleva a Inicio.

Evidencia: `docs/ux-auditoria-2026-10/m1-acceso-marca-conexiones.md hallazgo 2, historia B3`; `docs/ux-auditoria-2026-10/m7 hallazgo 2`; `docs/ux-auditoria-2026-10.md §3, §4.1`

#### MARCA-2 · [m-24842966](https://project.larksuite.com/5h2wsx/issue/detail/24842966) — Tu marca: textos del acceso y del asistente en palabras del dueño (sin Brand Kit, brandboard, insights)

*Como dueño, quiero leer todo el registro y el asistente de marca en mis palabras, para no tener que preguntar qué significa.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `auth_pages.py`, `creative_wizard_pages.py`, `brand_*.py` contiene «Brand Kit», «Brandkit», «brandboard», «insights», «claims», «detractor», «Email», «Claude» ni «Anthropic».
- Las cadenas quedan exactamente como en la tabla del hallazgo 4 y la lista del hallazgo 11.
- No se tocan menú ni títulos de pestaña (los cambia NAV-9 (m-24842958)).

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgos 4 y 11, historia B2`; qualify-copy-es; `docs/ux-auditoria-2026-10.md T7`

#### MARCA-3 · [m-24842967](https://project.larksuite.com/5h2wsx/issue/detail/24842967) — Acceso: crear la cuenta con cuatro campos con etiqueta y el país en lugar de zona horaria y moneda

*Como dueño invitado, quiero crear mi cuenta con solo el nombre de mi negocio, mi contraseña y mi país, para entrar en menos de un minuto.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- El registro invitado muestra exactamente 4 campos con etiqueta visible; no hay campos de zona horaria ni moneda.
- Un negocio registrado con «Colombia» queda con zona `America/Bogota` y moneda COP; «Uruguay» con `America/Montevideo` y UYU; «Venezuela» con `America/Caracas` y USD por defecto (decisión 10), editable en Configuración.
- A 360 px el formulario es de una columna, sin desplazamiento horizontal, botones ≥ 44 px (N12).

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgos 7-9, historia A1`

#### MARCA-4 · [m-24848529](https://project.larksuite.com/5h2wsx/issue/detail/24848529) — Tu marca: lo mínimo en 5 pasos y el resto sin bloquear la app

*Como dueño, quiero dejar lista mi marca en 5 pasos cortos, para poder hacer mi primera publicación hoy.*

**P1 · L · reflex-ui-engineer + creative-engineer**
- Revisión: Arquitecto (2026-10-23): pasa con cambios; no necesita ADR.
- Lista para empezar.

Criterios de aceptación:
- El camino obligatorio tiene exactamente los 5 pasos con nombre y «Paso N de 5» (N6); «No tengo redes» lleva al paso 2 sin prellenar.
- Después del paso 5, `/create` no muestra ningún aviso de marca incompleta y todas las pantallas se abren.
- Un borrador guardado a mitad del flujo viejo (manual o conexión) se retoma en el paso nuevo equivalente sin perder datos.
- Cada paso tiene «Seguir después» y «Atrás» que no pierden lo escrito; no queda ninguna pantalla de espera sin control.
- Pruebas offline del mapeo de pasos y de `readiness` con los cinco datos mínimos.

Fuera de alcance: Cambiar los modelos o prompts que leen el perfil.

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgo 3, historia B1`; `docs/ux-guia-navegacion.md §7 decisión 6`; `docs/ux-auditoria-2026-10.md §3`

#### MARCA-5 · [m-24842968](https://project.larksuite.com/5h2wsx/issue/detail/24842968) — Acceso: el visitante sin invitación sabe antes de empezar que la necesita

*Como visitante sin invitación, quiero saber antes de armar mi marca que necesito una invitación, para no perder 15 minutos de trabajo.*

**P1 · M · reflex-ui-engineer + backend-engineer**
- Revisión: Arquitecto (2026-10-23): la suposición de una captura de interés existente era falsa.
- Lista para empezar.

Criterios de aceptación:
- Antes de empezar se lee el aviso exacto de invitación; ningún recorrido termina en «Qualify es solo por invitación» después de armar la marca.
- Con código válido el asistente sigue; sin código se piden solo nombre, negocio y WhatsApp, con etiqueta visible y la casilla «Acepto que me escriban por WhatsApp» obligatoria.
- Al enviar se ve «Listo. Te escribimos por WhatsApp cuando tu invitación esté lista.», no se crea ninguna cuenta y la entrada aparece en `/leads` del tenant de la casa.
- El POST rechaza envíos sin consentimiento, con el campo trampa lleno o por encima del límite; el número no se muestra en logs ni en tickets.

Fuera de alcance: Abrir el registro público (sigue siendo solo por invitación).

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgo 1, historia A2`; Política de registro solo por invitación (fundador, ~2026-10-13)

#### MARCA-6 · [m-24842969](https://project.larksuite.com/5h2wsx/issue/detail/24842969) — Tus redes: saber de un vistazo si mi Instagram funciona, qué puedo hacer y qué sigue al conectarlo

*Como dueño, quiero entender de un vistazo si mi Instagram funciona y qué puedo hacer con él, para no tener miedo de haber hecho algo mal.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- La tarjeta muestra uno de los tres estados en texto y las líneas «Puedes:» / «Todavía no puedes:» con enlace al paso que lo activa.
- Ningún texto visible contiene «Degradada», «Revocada», «Verificada:» ni menciona la documentación de Meta.
- Tras conectar con éxito aparece «Instagram conectado» y «Crear una publicación» (N3); con `?volver=/create` vuelve a Crear.

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgos 6 y 10, historias C1-C2`

#### MARCA-7 · [m-24842970](https://project.larksuite.com/5h2wsx/issue/detail/24842970) — Tu marca: «Editar mi marca» abre en el resumen de mi marca, no en el ranking de referentes

*Como dueño que entra a cambiar su logo, quiero ver primero mi marca por secciones, para cambiar lo que necesito sin ver cuentas de otros.*

**P2 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- `/brand/kit` abre en el resumen; la sección de referentes se llama «Negocios parecidos al tuyo».
- Sin voz configurada, la página se usa igual y muestra la fila opcional.
- Textos del editor: «Tu marca», «Editar mi marca», «Logo», «promesas que no puedes hacer».

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgo 12`

#### MARCA-8 · [m-24849135](https://project.larksuite.com/5h2wsx/issue/detail/24849135) — Tu marca: cambiar «¿Eres influencer o una marca?» y «rubro» por palabras más usadas

*Como dueño de un local, quiero que el asistente me pregunte con palabras de todos los días, para no dudar qué contestar.*

**P2 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Antes del PR, la validación con al menos dos dueños queda anotada en el ticket; si no se confirma, se cierra sin cambios.
- Si se confirma, ningún texto visible del asistente dice «influencer» ni «rubro».

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23); `docs/perfil-cliente-pyme.md §5 pregunta 4`

### [PRODUCTOS] Tus productos

#### PRODUCTOS-6 · [m-24842971](https://project.larksuite.com/5h2wsx/issue/detail/24842971) — Tus productos: textos y errores en palabras del dueño

*Como dueño, quiero que la pantalla de productos me hable de lo que gano y en mis palabras, para entenderla sin preguntar a nadie.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `catalog_page.py` / `catalog_state.py` / `catalog_vm.py` contiene «plantilla», «feed», «pieza», «gancho», «provisionada», «story» ni «base de datos»; «reel» solo como «reel (video corto)» (decisión 11).
- Las cadenas quedan exactamente como en la propuesta; el vacío tiene `action` (N8).
- No se tocan menú ni título de pestaña (NAV-9 (m-24842958)).

Evidencia: `docs/ux-auditoria-2026-10/m2-catalogo.md hallazgos 5 y 10, historia 8`

#### PRODUCTOS-1 · [m-24842972](https://project.larksuite.com/5h2wsx/issue/detail/24842972) — Tus productos: «Crear publicación con este producto» abre Crear con el producto ya elegido

*Como dueño, quiero crear una publicación desde mi producto con un toque, para no buscarlo otra vez en otra pantalla.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Tocar «Crear publicación con este producto» abre `/create?producto=<id>` con el producto ya elegido (N3).
- Un `?producto=` de otro tenant o inexistente se ignora sin error (RLS).
- Sin fotos, el botón está desactivado y dice «Primero súbele una foto».

Evidencia: `docs/ux-auditoria-2026-10/m2 hallazgo 1, historia 6`; `docs/ux-guia-navegacion.md §5`

#### PRODUCTOS-2 · [m-24842973](https://project.larksuite.com/5h2wsx/issue/detail/24842973) — Tus productos: volver a mi publicación con el producto que agregué (N4)

*Como dueño, quiero volver a mi publicación después de agregar un producto que faltaba, para no empezar de cero.*

**P2 · M · reflex-ui-engineer** · Depende de: PRODUCTOS-1 (m-24842972)
- Lista para empezar.

Criterios de aceptación:
- El recorrido Crear → Tus productos → Crear no pierde el paso ni lo escrito y vuelve con el producto elegido (N4).
- `?volver=` solo acepta rutas internas de la app.
- *Hipótesis* (perfil §5 pregunta 6): el dueño llega al catálogo desde Crear más que desde el menú.

Evidencia: `docs/ux-auditoria-2026-10/m2 historia 7`; `docs/ux-guia-navegacion.md §4 N4`; `docs/ux-auditoria-2026-10.md T5`

#### PRODUCTOS-3 · [m-24842974](https://project.larksuite.com/5h2wsx/issue/detail/24842974) — Tus productos: agregar un producto en tres pasos desde el celular, la foto primero

*Como dueño, quiero subir la foto de mi producto con la cámara del celular en el primer paso y que solo me pidan el nombre y, si quiero, el precio, para tenerlo listo en menos de un minuto.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- El primer paso es la foto; no aparecen «arrastra», «haz clic» ni siglas de formato en el camino principal.
- «Paso N de 3»; «Atrás» no pierde lo escrito (N6); sin foto el producto queda con «Falta la foto».
- La moneda viene elegida con la del negocio y se lee por su nombre.
- A 360 px una columna y botones ≥ 44 px (N12).

Evidencia: `docs/ux-auditoria-2026-10/m2 hallazgos 4, 6, 7, historias 1-2`

#### PRODUCTOS-4 · [m-24842976](https://project.larksuite.com/5h2wsx/issue/detail/24842976) — Tus productos: editar sin perder cambios, en pantalla completa en el celular y con su dirección

*Como dueño, quiero abrir un producto en pantalla completa y que me avisen si salgo sin guardar, para no perder el precio que corregí.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Cerrar o cambiar de producto con cambios pendientes muestra «¿Salir sin guardar?» con «Volver» y «Guardar y salir».
- En el celular la ficha ocupa la pantalla; «atrás» vuelve a la lista en la misma posición (N5).
- La tarjeta se anuncia como «Editar {producto}» en lector de pantalla; nada depende de pasar el mouse.

Evidencia: `docs/ux-auditoria-2026-10/m2 hallazgos 2, 3, 9, historias 3-4`

#### PRODUCTOS-5 · [m-24842977](https://project.larksuite.com/5h2wsx/issue/detail/24842977) — Tus productos: marcar la foto principal y quitar fotos sin equivocarme

*Como dueño, quiero marcar la foto principal y quitar fotos sin equivocarme, para que mis publicaciones salgan con la foto correcta.*

**P2 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- «Principal» y «Quitar» se leen como texto y miden ≥ 44 px; quitar es reversible o confirmado.
- Ninguna foto muestra medidas en píxeles.
- Los productos sin foto muestran «Falta la foto» en texto (no solo color).

Evidencia: `docs/ux-auditoria-2026-10/m2 hallazgos 8, 11, 12, historia 5`

### [CREAR] Crear publicación

#### CREAR-1 · [m-24842978](https://project.larksuite.com/5h2wsx/issue/detail/24842978) — Crear: al aprobar, «Aprobada. Todavía no se publica.» con el botón «Elegir día y hora»

*Como dueño, quiero que al aprobar una publicación me lleve a programarla, para no tener que buscarla otra vez.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Tras aprobar se ve la tarjeta con los textos exactos y «Elegir día y hora» abre `/planner?post=<id>` con esa publicación marcada (N3).
- Ningún texto dice ni sugiere que ya se publicó; el toast «POST aprobado…» desaparece.
- Botones ≥ 44 px en el celular (N12).

Fuera de alcance: «Publicar ahora» desde esta tarjeta (PUBLICAR-3 (m-24842985), cuando Tu semana pueda programar a la hora actual).

Evidencia: `docs/ux-auditoria-2026-10/m3-crear-piezas.md hallazgo 1, historia A1`; `docs/ux-auditoria-2026-10/m4 H1, historia 1`; `docs/ux-guia-navegacion.md §5`; `docs/ux-auditoria-2026-10.md §3, §4.1`

#### CREAR-4 · [m-24842979](https://project.larksuite.com/5h2wsx/issue/detail/24842979) — Crear: todo dice «publicación» y habla como el dueño (sin POST, caption, CTA, HITL, Brand Kit ni proveedores)

*Como dueño, quiero que todo diga «publicación» y esté en mis palabras, para no confundirme ni preguntar qué es cada cosa.*

**P0 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ninguna cadena visible de `creative_pages.py`, `content_generator.py`, `creative_vm.py`, `creative_state.py`, `variations_view.py`, `voice_lab.py` contiene POST, caption, CTA, Flyer, Story/story, UGC, HITL, Bandeja, Copy, Brand Kit, Claude, `QUALIFY_` ni «base de datos».
- Los avisos de marca llevan a `/brand/kit` y dicen «tu marca».
- Las cadenas quedan exactamente como en la propuesta; «reel» aparece como «reel (video corto)» donde el dueño elige el formato y nunca se escribe «story» (decisión 11).
- No se tocan menú ni títulos de pestaña (NAV-9 (m-24842958)).

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgos 3, 4, 8, 9, 10, 12, historias B1-B3`; `docs/ux-auditoria-2026-10.md T4, T7`

#### CREAR-2 · [m-24848530](https://project.larksuite.com/5h2wsx/issue/detail/24848530) — Crear: una publicación en cuatro pasos cortos, lo opcional detrás de «Más opciones»

*Como dueño, quiero crear una publicación en 4 pasos cortos, para terminarla en 2 minutos desde el celular.*

**P1 · L · reflex-ui-engineer (revisa creative-engineer)**
- Revisión: Arquitecto (2026-10-23): pasa con cambios.
- Lista para empezar.

Criterios de aceptación:
- `/create` muestra «Paso N de 4» con esos cuatro pasos (N6); lo obligatorio de cada tipo está en el paso 1, nunca detrás de «Más opciones».
- Con el mismo tipo y formato que la vez anterior, basta escribir el tema y tocar «Siguiente» hasta «Crear».
- Los «Editar» del resumen llevan al paso correcto; «Atrás» conserva lo escrito.
- Las pastillas de datos clave dicen si cambian la marca o quedan locales.
- Se actualizan las pruebas de `test_generator_voice_and_copy.py` (línea 289) para el nuevo orden; a 360 px una columna y botones ≥ 44 px.

Fuera de alcance: Cambios de modelos o prompts de generación.

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgo 2, historia A2`; `docs/ux-guia-navegacion.md §5`

#### CREAR-6 · [m-24842980](https://project.larksuite.com/5h2wsx/issue/detail/24842980) — Crear: en el celular ver todos los tipos con su explicación y escribir los datos clave sin comas

*Como dueño, quiero ver todas las opciones de qué crear con su explicación en el celular, para elegir sin adivinar.*

**P1 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- A 360 px se ven todos los tipos (incluidos «Variaciones» y «Descubrir ideas de videos») en columna con su descripción.
- Ninguna explicación vive solo en `tooltip` o `title=` (N12).
- No aparece «separado por comas».

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgos 7 y 11, historia D1`

#### CREAR-3 · [m-24842981](https://project.larksuite.com/5h2wsx/issue/detail/24842981) — Crear: en Por aprobar, estados en texto y un solo botón claro por publicación

*Como dueño, quiero ver en «Por aprobar» un solo botón claro por cada una, para saber qué me toca hacer.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Cada tarjeta muestra su estado en texto y un único botón principal según la tabla.
- Ningún texto visible contiene Cold, Hot ni evergreen; la ayuda no vive solo en `title=`.

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgos 5 y 12, historia A3`

#### CREAR-5 · [m-24848531](https://project.larksuite.com/5h2wsx/issue/detail/24848531) — Crear: el dueño ve sus creaciones del mes («Te quedan 18 de 30 este mes»), nunca dinero

*Como dueño con presupuesto chico, quiero saber antes de crear cuántas de mis creaciones del mes usa y cuántas me quedan, para no llevarme sorpresas.*

**P2 · M · reflex-ui-engineer + creative-engineer + data-scientist-fde**
- Decisión del fundador (2026-10-23, §2b-3a): el dueño sí puede crear el presentador de 30 s, con aviso previo de cuántas creaciones usa.
- Decisión del fundador (2026-10-23, §2b-3b): una sola lectura agregada de producción (conteo de creaciones por negocio y tipo, 60 días; solo conteos) para fijar la asignación mensual (supuesto: 30).
- Medición hecha el 2026-10-23 ([`creaciones-del-mes-medicion.md`](creaciones-del-mes-medicion.md)): solo 3 días de uso de negocios de prueba y solo imagen con texto. **Solo el peso de la imagen está confirmado** (1; p95 USD 0,068 < 0,15); los demás pesos salen de la tabla v5 sin uso real. La asignación se queda en 30; volver a medir cuando 3 clientes reales tengan 30 días de uso (seguimiento, no bloquea).
- Lista para empezar.
- Revisión: Data scientist (2026-10-23): pasa con cambios.

Criterios de aceptación:
- Cada pedido muestra las creaciones que usa y las que quedan, con los textos exactos; sin saldo suficiente no se genera nada.
- El presentador de 30 s lo puede crear el dueño; antes de crear se lee «Este video con presentador usa 25 de tus creaciones. Te quedarían {n} este mes.» con el número del peso versionado.
- Con saldo menor que 25 se ofrece la versión de 15 s (13 creaciones) en lugar de la de 30 s.
- Una generación fallida o moderada devuelve las creaciones.
- La asignación y los pesos se guardan con su versión, y cada cobro registra peso, versión de pesos y versión de la tabla de precios (procedencia).
- El equipo ve el costo real en dólares por pieza y por mes al lado de las creaciones cobradas; el dueño no ve montos.

Fuera de alcance: Cambiar la tabla de precios versionada (`qualify_creative/pricing_data/`). Leer textos, piezas o datos de clientes finales en producción. Confirmar los pesos que no son de imagen (segunda medición, seguimiento).

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgo 6, historia C1`

#### CREAR-7 · [m-24849133](https://project.larksuite.com/5h2wsx/issue/detail/24849133) — Crear: los títulos «Hashtags» pasan a «Etiquetas»

*Como dueño, quiero leer «Etiquetas» en lugar de «Hashtags», para entender cada bloque sin palabras en inglés.*

**P2 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún título ni aviso visible de `content_generator.py` y `creative_pages.py` dice «Hashtags».
- Las cadenas quedan exactamente como en la propuesta.

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23); qualify-copy-es

### [PUBLICAR] Aprobar, programar y publicar

#### PUBLICAR-1 · [m-24842982](https://project.larksuite.com/5h2wsx/issue/detail/24842982) — Tu semana: en el celular, «Tienes {n} publicaciones aprobadas esperando día y hora» con su botón

*Como dueño, quiero ver en el teléfono cuántas publicaciones tengo esperando día y hora, para programarlas de una vez.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- A 360 px, con n > 0, se ven el texto y el botón exactos sin arrastrar ni abrir paneles; el botón preselecciona las n.
- Con n = 0 el vacío lleva a `/create` (N8).
- Ningún texto del estado vacío contiene «POST».

Evidencia: `docs/ux-auditoria-2026-10/m4-planificar-publicar.md H2, historia 3`; `docs/ux-auditoria-2026-10.md §3, §4.1`

#### PUBLICAR-5 · [m-24842983](https://project.larksuite.com/5h2wsx/issue/detail/24842983) — Tu semana y Publicar ahora: textos y errores en español sencillo (sin POST, caption, Stories, Cold/Hot, tenant, R2)

*Como dueño, quiero que las pantallas de planificar y publicar hablen en español sencillo, para entender todo sin preguntar.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `planner_*.py`, `publishing_*.py`, `stories_*.py`, `trending_panel.py` contiene POST, Caption, Story/Stories, Cold, Hot, Likes, Ads, vendor, preview, tenant, R2.
- Las cadenas quedan exactamente como en la propuesta (decisión 11: «reel (video corto)» e «historia»).
- No se tocan menú ni títulos de pestaña (NAV-9 (m-24842958)) ni los textos de publicación automática (NAV-8 (m-24842959)).
- Ningún texto visible de `planner_vm.py` dice Feed, Cold, Hot ni evergreen; la confirmación de programar dice día y hora.

Evidencia: `docs/ux-auditoria-2026-10/m4 H3, H4, H8, historia 7`; `docs/ux-auditoria-2026-10.md T7`

#### PUBLICAR-2 · [m-24842984](https://project.larksuite.com/5h2wsx/issue/detail/24842984) — Tu semana: aprobar o descartar una publicación desde su ficha

*Como dueño, quiero aprobar o descartar una publicación desde mi semana, para revisar todo en un solo lugar.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- La ficha «En revisión» muestra «Aprobar» y «No la quiero»; al aprobar el estado cambia a «Aprobada» sin recargar y el texto dice cuándo sale.
- Aprobar no publica: sale solo a la hora programada que el dueño eligió (N13).
- Prueba offline del nuevo evento de aprobación desde Tu semana.

Evidencia: `docs/ux-auditoria-2026-10/m4 H7, historia 2`

#### PUBLICAR-3 · [m-24842985](https://project.larksuite.com/5h2wsx/issue/detail/24842985) — Tu semana: programar eligiendo solo día y hora, o «Ahora»

*Como dueño, quiero programar una publicación eligiendo solo día y hora, para terminar en menos de 2 minutos.*

**P1 · M · reflex-ui-engineer** · Depende de: CREAR-1 (m-24842978)
- Lista para empezar.

Criterios de aceptación:
- El paso «¿Cuándo sale?» muestra solo Día y Hora; lo demás en «Más opciones» (N6).
- La confirmación dice la frase exacta con día, hora y cuenta (N13).
- Con «Ahora», la publicación sale en el siguiente ciclo del worker solo después de tocar «Programar».

Evidencia: `docs/ux-auditoria-2026-10/m4 H1, H6, historias 1 y 4`

#### PUBLICAR-4 · [m-24842986](https://project.larksuite.com/5h2wsx/issue/detail/24842986) — Publicar ahora: subir algo del teléfono en tres pasos y saber qué sigue al publicar

*Como dueño, quiero subir una foto o un video de mi teléfono y publicarlo en tres pasos, y saber qué hacer después, para no perderme entre opciones.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Tres pasos con «Paso N de 3» y «Atrás» que no pierde lo elegido (N6).
- Formatos y tamaños solo aparecen en el error.
- Al publicar se ve el `callout` con los dos botones (N3), no solo un toast.

Evidencia: `docs/ux-auditoria-2026-10/m4 H5, H12, historias 5-6`

#### PUBLICAR-6 · [m-24842987](https://project.larksuite.com/5h2wsx/issue/detail/24842987) — Tu semana: volver siempre a mi semana y usarla con el pulgar

*Como dueño, quiero volver siempre a mi semana desde cualquier ficha y usarla con el pulgar, para no perderme entre pantallas.*

**P2 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- A 360 px la barra cabe en una línea antes de la semana.
- Nada del módulo depende de pasar el mouse; controles ≥ 44 px (N12).
- «‹ Tu semana» vuelve con la misma semana y vista.

Evidencia: `docs/ux-auditoria-2026-10/m4 H10, H11, historia 8`

### [ATENDER] Responder a clientes

#### ATENDER-8 · [m-24842988](https://project.larksuite.com/5h2wsx/issue/detail/24842988) — Atender: comentarios, conversaciones e interesados en palabras del dueño, sin números internos

*Como dueño, quiero que las pantallas de responder hablen en mis palabras y no me muestren números internos, para contestar sin preguntar qué es cada cosa.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `inbox_*.py`, `conversations_*.py`, `followups_*.py`, `leads_page.py`, `replies_provider.py` contiene monitorear, DM, caption, sincroniz-, sentimiento, intención, borradores asistidos, funnel, leads ni «en cola».
- No se muestra ningún identificador interno; cada respuesta lista dice a quién y en qué publicación.
- Las cadenas quedan exactamente como en la propuesta.

Evidencia: `docs/ux-auditoria-2026-10/m5-responder-clientes.md hallazgos 4, 5, 12`; `docs/ux-auditoria-2026-10.md T7`

#### ATENDER-3 · [m-24842989](https://project.larksuite.com/5h2wsx/issue/detail/24842989) — Comentarios: primero las respuestas listas para aprobar; configurar qué revisar, detrás de «Más opciones»

*Como dueño, quiero ver primero las respuestas listas para aprobar de mis comentarios, para contestar en un minuto desde el celular.*

**P0 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Al abrir Comentarios, lo primero son las respuestas listas para aprobar; los interruptores de revisar publicaciones solo aparecen al abrir «Más opciones».
- Cada respuesta muestra a quién, el comentario y la miniatura de la publicación; el botón dice «Aprobar y responder» y nada sale sin pulsarlo (N13).
- A 360 px sin desplazamiento horizontal y botones ≥ 44 px (N12).

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgos 2 y 10, historia 4`; `docs/ux-auditoria-2026-10.md §3`

#### ATENDER-4a · [m-24848532](https://project.larksuite.com/5h2wsx/issue/detail/24848532) — Comentarios: medir la clasificación y los borradores de respuesta antes de responder a todos

*Como dueño, quiero que las respuestas que me propone Qualify para cualquier comentario sean correctas y en mi voz, para aprobarlas sin miedo a decir algo falso.*

**P0 · M · data-scientist-fde**
- Revisión: Data scientist (2026-10-23): pasa con cambios; se separa en 4a (medición) y 4b (producto).
- Lista para empezar.

Criterios de aceptación:
- Clasificador: precisión por clase ≥ 0,80 y cobertura ≥ 0,70; cobertura de negativos ≥ 0,90; cobertura de «necesita respuesta» ≥ 0,95.
- Borradores: 0 datos inventados y 0 en tercera persona; ≥ 90 % usables en positivos y neutros, ≥ 80 % en negativos.
- Las respuestas sobre precios usan el catálogo (`assisted/grounding.py`) o declinan.
- Cada borrador guarda modelo, versión del prompt y costo; resultados documentados el mismo día en `docs/respuestas-comentarios-medicion.md`.

Fuera de alcance: Cambiar la pantalla o la regla de respuestas en producción (ATENDER-4b (m-24848533); la regla de solo positivos, QUA-22, quedó enmendada el 2026-10-23, §2b-1).

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgo 3, historia 5`; `docs/ux-auditoria-2026-10.md §3`

#### ATENDER-4b · [m-24848533](https://project.larksuite.com/5h2wsx/issue/detail/24848533) — Comentarios: responder en público cualquier comentario, también preguntas y quejas

*Como dueño, quiero poder contestar en público cualquier comentario, también preguntas y quejas, para que nadie quede ignorado delante de los demás.*

**P0 · M · backend-engineer + reflex-ui-engineer** · Depende de: ATENDER-4a (m-24848532), ATENDER-3 (m-24842989)
- Desbloqueada (fundador, 2026-10-23, §2b-1): **QUA-22 enmendada.** Qualify prepara respuestas también para preguntas y quejas; el dueño siempre revisa y envía; en las quejas la propuesta sugiere seguir por mensaje privado. Hoy `replies/gate.py` y `REPLY_SYSTEM_PROMPT` («sentimiento POSITIVO») lo impiden: esta historia los cambia. La fila ADR 21c la escribe el arquitecto.
- Revisión: Arquitecto + data scientist (2026-10-23): pasa con cambios.

Criterios de aceptación:
- Cada comentario ofrece «Responder aquí» y «Escribirle en privado».
- Se prepara respuesta para positivos, preguntas y quejas con el modelo y prompt de ATENDER-4a (m-24848532); en las quejas se exige editar o confirmar «Revísala antes de aprobar».
- El borrador de una queja invita a seguir por mensaje privado y no promete nada que el catálogo no diga.
- Nada se envía sin el toque del dueño (N13); un envío incierto muestra su estado; un comentario borrado no recibe borrador.
- Cada borrador guarda modelo, versión del prompt y costo; `just ci-test` en verde.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgo 3, historia 5`; `docs/ux-auditoria-2026-10.md §3`

#### ATENDER-5 · [m-24848534](https://project.larksuite.com/5h2wsx/issue/detail/24848534) — Comentarios: buscar, ordenar y preparar respuestas solos, sin que el dueño tenga la pantalla abierta

*Como dueño, quiero que los comentarios nuevos se busquen y se ordenen solos, para no tener que pulsar botones antes de ver quién quiere comprar.*

**P0 · L · backend-engineer + reflex-ui-engineer** · Depende de: ATENDER-4a (m-24848532)
- ⚑ **No por ahora (fundador, 2026-10-23, §2b-2).** Aparcada (parking-lot) hasta que el fundador la reabra.
- Revisión: Arquitecto + data scientist (2026-10-23): pasa con cambios; sin proceso nuevo.

Criterios de aceptación:
- Un comentario nuevo aparece ordenado y con borrador sin abrir la pantalla: ≤ 2 min con webhook, ≤ 15 min por sondeo.
- «Analizar sentimiento», «Analizar intención» y «Generar borradores» dejan de ser pasos obligatorios; queda «Buscar ahora».
- Ningún comentario se responde sin aprobación (N13); se respeta el tope diario; procedencia (modelo y versión del prompt) en cada fila.
- Se mide la memoria de robertuito en el worker (o se retira si ATENDER-4a (m-24848532) lo reemplaza) y el costo sobre el volumen real antes de activarlo.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgo 6, historia 6`; `docs/ux-auditoria-2026-10.md §3`

#### ATENDER-1 · [m-24842990](https://project.larksuite.com/5h2wsx/issue/detail/24842990) — Atender: un solo «Por responder» con los pendientes de cada canal y pestañas con su dirección

*Como dueño, quiero ver en una sola pantalla cuántas personas esperan mi respuesta en cada canal, para no dejar a nadie sin contestar más de 2 horas.*

**P1 · L · reflex-ui-engineer + backend-engineer** · Depende de: NAV-2 (m-24842960)
- Lista para empezar.

Criterios de aceptación:
- Se ven los cuatro conteos con «Ver» que abre la lista filtrada en pendientes (N11).
- Con cero pendientes: «¡Al día! No hay nadie esperando tu respuesta.» + enlace a crear la próxima publicación (N8).
- Cambiar de pestaña cambia la URL; «atrás» vuelve a la anterior; las rutas viejas redirigen.
- A 360 px una columna, botones ≥ 44 px; los conteos respetan RLS.

Fuera de alcance: Unificar los chats de WhatsApp en la misma bandeja: la pestaña WhatsApp enlaza a `/whatsapp?tab=chats`.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgo 1, historias 1 y 3`; `docs/ux-guia-navegacion.md §3; §7 decisión 3`; `docs/ux-auditoria-2026-10.md T3`

#### ATENDER-6 · [m-24842991](https://project.larksuite.com/5h2wsx/issue/detail/24842991) — Quieren comprar: responder en tres pasos cortos y pasar a la siguiente consulta

*Como dueño, quiero responder a quien quiere comprar en tres pasos cortos y pasar al siguiente, para atender varias consultas seguidas sin perderme.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- La tarjeta va en tres pasos; «Atrás» no borra lo escrito (N6).
- Al aprobar aparece la confirmación exacta con «Siguiente» y «Volver a comentarios» (N3).
- Ningún texto depende del ícono de información que solo se lee al pasar el mouse.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgos 7 y 8, historia 7`

#### ATENDER-7 · [m-24842992](https://project.larksuite.com/5h2wsx/issue/detail/24842992) — Clientes interesados: escribirles por WhatsApp desde la lista y saber a quién ya contacté

*Como dueño, quiero escribirle por WhatsApp a cada cliente interesado desde la lista y saber a quién ya contacté, para que ninguno se enfríe.*

**P2 · M · reflex-ui-engineer + backend-engineer**
- Lista para empezar.

Criterios de aceptación:
- A 360 px no hay tabla con desplazamiento horizontal; cada persona tiene «Escribirle por WhatsApp» ≥ 44 px.
- Cada persona muestra «Pendiente» o «Ya le escribiste» como texto.
- El vacío muestra el enlace real con «Copiar enlace» (N8).
- *Hipótesis* (perfil §5 preguntas 2-3): confirmar si contactan desde el número del negocio o el personal.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgos 10 y 11, historia 8`

#### ATENDER-9 · [m-24849130](https://project.larksuite.com/5h2wsx/issue/detail/24849130) — Comentarios: «Reintentar» una respuesta que no salió por un fallo pasajero

*Como dueño, quiero poder intentarlo otra vez cuando mi respuesta no salió por un problema pasajero, para que ese cliente no se quede sin contestar.*

**P2 · M · backend-engineer + reflex-ui-engineer** · Depende de: ATENDER-3 (m-24842989)
- Decidida (fundador, 2026-10-23, §2b-5): «Reintentar» solo si el fallo es pasajero (sin conexión, Instagram caído); si borraron el comentario, se dice y no se ofrece. Lista para empezar (ola 2).

Criterios de aceptación:
- Un fallo pasajero deja la respuesta visible con «Tu respuesta no salió: Instagram no respondió.» y «Reintentar».
- Un comentario borrado muestra «Borraron ese comentario. Ya no se puede responder.» y no ofrece «Reintentar».
- Un rechazo de otro tipo muestra «Tu respuesta no salió. Respóndela en Instagram.» y un resultado desconocido «No sabemos si salió. Revísalo en Instagram.» (textos de §2b-7a), ambos sin «Reintentar».
- «Reintentar» envía solo tras el toque del dueño (N13) y no duplica si se toca dos veces.
- Ningún código de error de Meta aparece en pantalla; la clasificación de fallos tiene prueba offline.

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23)

#### ATENDER-10 · [m-24849131](https://project.larksuite.com/5h2wsx/issue/detail/24849131) — Quieren comprar: la tarjeta dice si el mensaje privado salió o falló

*Como dueño, quiero saber si mi mensaje privado le llegó a quien quería comprar, para no creer que respondí cuando no fue así.*

**P1 · M · reflex-ui-engineer + backend-engineer**
- Lista para empezar.

Criterios de aceptación:
- Tras aprobar, la tarjeta no desaparece hasta saber el resultado; muestra los textos exactos de éxito o fallo.
- Un fallo deja la tarjeta visible; nada se reenvía solo (N13).
- Prueba offline del cambio de estado éxito/fallo.

Fuera de alcance: Botón «Reintentar» (sigue la decisión de ATENDER-9 (m-24849130)).

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23); `docs/ux-auditoria-2026-10/m5 hallazgo 7`

#### ATENDER-11 · [m-24849132](https://project.larksuite.com/5h2wsx/issue/detail/24849132) — Comentarios: un solo aviso de error al ordenar los comentarios

*Como dueño, quiero ver un solo aviso claro si algo falló al ordenar mis comentarios, para saber qué hacer sin leer dos cajas parecidas.*

**P2 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Si falla cualquiera de los dos análisis (o ambos), se ve un solo aviso con el texto exacto.
- Prueba offline con cada combinación de fallos.

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23)

### [WHATSAPP] WhatsApp

#### WHATSAPP-1 · [m-24842993](https://project.larksuite.com/5h2wsx/issue/detail/24842993) — WhatsApp: con el chat vencido, decir qué pasa y llevar a los mensajes aprobados

*Como dueño, quiero saber qué hacer cuando un cliente me escribió hace más de 24 horas, para no quedarme frente a un cuadro apagado.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Con el chat vencido se ven el aviso y el enlace exactos; ningún texto dice «ventana» ni «plantillas» al dueño.
- El enlace abre la pestaña de mensajes aprobados (N5).

Evidencia: `docs/ux-auditoria-2026-10/m6-whatsapp.md hallazgo 1`; `docs/ux-auditoria-2026-10.md §3`

#### WHATSAPP-8 · [m-24842994](https://project.larksuite.com/5h2wsx/issue/detail/24842994) — WhatsApp: textos sin opt-in, leads, Marketing, Lanzar ni Revocar; distintivos de los chats explicados

*Como dueño, quiero que WhatsApp me hable en mis palabras, para usarlo sin preguntar qué significa cada cosa.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `whatsapp_*.py` contiene opt-in, leads, Marketing, Lanzar, encola, Revocar, WhatsApp Manager, Sincronizar con Meta, Mediana ni p90.
- Los distintivos de cada chat se leen en texto con la hora límite.
- Las cadenas quedan exactamente como en la propuesta.
- Ningún texto visible dice «en cola», «ventana» ni «mostrador» en el siguiente paso del QR.

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgos 6, 10 y 12, historia 2`; `docs/ux-auditoria-2026-10.md T7`

#### WHATSAPP-3 · [m-24842995](https://project.larksuite.com/5h2wsx/issue/detail/24842995) — WhatsApp: publicar el menú automático con un solo botón y saber qué sigue

*Como dueño, quiero publicar mi menú con un solo botón y saber qué pasa, para no quedarme con cambios guardados que no responden.*

**P0 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Un toque en «Publicar en mi WhatsApp» + confirmar deja publicada la versión editada.
- El texto deja claro que el menú envía lo que escribió el dueño y que él puede tomar cualquier chat (N13).
- Tras publicar aparece el siguiente paso al QR (N3).

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgo 3, historia 4`; `docs/ux-auditoria-2026-10.md §3`

#### WHATSAPP-2 · [m-24848535](https://project.larksuite.com/5h2wsx/issue/detail/24848535) — WhatsApp: enviar un mensaje aprobado desde el chat vencido

*Como dueño, quiero responder a un cliente aunque hayan pasado más de 24 horas, para no perder una venta.*

**P0 · M · backend-engineer + reflex-ui-engineer** · Depende de: WHATSAPP-1 (m-24842993)
- Revisión: Arquitecto (2026-10-23): pasa con cambios; v1 lista.
- Decisión del fundador (2026-10-23, §2b-4): el chat previo cuenta como permiso solo para retomar su tema con una plantilla de seguimiento (utilidad); las promociones necesitan permiso explícito. El arquitecto confirma al empezar cómo se guarda el origen del permiso.
- Lista para empezar.

Criterios de aceptación:
- Con el chat vencido aparece «Enviar un mensaje aprobado»; la lista muestra solo plantillas aprobadas con vista previa.
- Si la persona escribió antes pero no aceptó promociones, la lista muestra solo mensajes de seguimiento y se lee «Para enviarle promociones, esta persona tiene que aceptar recibirlas.»; ninguna plantilla de promoción se puede elegir.
- Debajo de ese aviso aparece «Pedirle que acepte» solo si existe una plantilla de utilidad aprobada para pedir el permiso; sin ella, no hay botón. El envío sigue necesitando el toque del dueño (N13).
- Con permiso explícito activo se listan seguimiento y promociones; el servidor rechaza una promoción a un contacto sin permiso explícito (prueba offline).
- Se envía solo tras tocar «Enviar» (N13); el mensaje aparece en la conversación con su estado; reintentos con el mismo `request_key` no duplican.
- La migración es reversible y con RLS; pruebas offline en verde.

Fuera de alcance: Usar el chat previo como permiso para promociones (necesitan permiso explícito, §2b-4). Crear la plantilla para pedir el permiso (si no existe, no se muestra el botón).

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgo 1, historia 1`

#### WHATSAPP-4 · [m-24848536](https://project.larksuite.com/5h2wsx/issue/detail/24848536) — WhatsApp: armar el menú automático en cuatro pasos, sin identificadores técnicos

*Como dueño, quiero armar mi menú automático en 4 pasos cortos con mis textos y mi catálogo, para que WhatsApp atienda lo básico sin que yo aprenda a programar.*

**P0 · L · reflex-ui-engineer + backend-engineer** · Depende de: WHATSAPP-3 (m-24842995)
- Revisión: Arquitecto (2026-10-23): pasa con cambios.
- Lista para empezar.

Criterios de aceptación:
- «Paso N de 4», «Atrás» sin perder datos (N6).
- Ningún identificador técnico visible en el camino principal; renombrar un paso no cambia su identificador ni rompe un menú publicado.
- Se mide cuánto tarda un dueño de prueba desde la plantilla (meta ≤ 5 min, medición, no bloqueo).

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgo 2, historia 3`; `docs/ux-auditoria-2026-10.md §3`

#### WHATSAPP-5 · [m-24842996](https://project.larksuite.com/5h2wsx/issue/detail/24842996) — WhatsApp: enviar una promoción en tres pasos (mensaje, a quién, revisar)

*Como dueño, quiero enviar una promoción a mis clientes en 3 pasos, para que vuelvan sin pagar una agencia.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- La revisión dice cuántos, cuánto tarda y costo aproximado; botón «Enviar ahora»; nada se envía sin tocarlo (N13).
- No hay campo numérico obligatorio de ritmo ni códigos de error en pantalla.
- Tras enviar aparece «Ver respuestas en Chats» (N3).

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgos 4 y 5, historia 5`

#### WHATSAPP-6 · [m-24842997](https://project.larksuite.com/5h2wsx/issue/detail/24842997) — WhatsApp: crear un mensaje de promoción guiado para que lo aprueben a la primera

*Como dueño, quiero crear un mensaje de promoción guiado y sin nombres técnicos, para que me lo aprueben a la primera.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Cuatro pasos con vista previa al final; el dueño nunca escribe `{{…}}` ni un nombre con guion bajo.
- Los ejemplos de variables se rellenan solos y la plantilla llega a Meta con los campos que exige.
- Mensaje exacto al enviar (N3).

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgo 7, historia 6`

#### WHATSAPP-7 · [m-24842998](https://project.larksuite.com/5h2wsx/issue/detail/24842998) — WhatsApp: cuatro pestañas con nombres de tareas, «Tu número» en una línea y tablas como tarjetas en el celular

*Como dueño, quiero encontrar lo que necesito en 4 pestañas con nombres de tareas y leerlo en el celular, para usar WhatsApp sin buscar ni deslizar de lado.*

**P1 · L · reflex-ui-engineer** · Depende de: NAV-2 (m-24842960)
- Lista para empezar.

Criterios de aceptación:
- A 360 px las 4 pestañas se ven sin deslizar; objetivos ≥ 44 px (N12).
- `?tab=`/`?sub=` se actualizan; recargar o «atrás» conserva la pestaña (N5).
- Sin número conectado hay un botón de siguiente paso (N8); ninguna tabla se desliza de lado en el celular.

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgos 9, 10, 11, historia 8`; `docs/ux-guia-navegacion.md §3`

### [RESULTADOS] Resultados y menciones

#### RESULTADOS-2 · [m-24842999](https://project.larksuite.com/5h2wsx/issue/detail/24842999) — Resultados: Menciones, Clarity y Señales en palabras del dueño (sin Rage clicks, snapshot, placeholder ni roadmap)

*Como dueño, quiero que las pantallas de resultados hablen en mis palabras, para entender cómo me va sin saber de analítica.*

**P0 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `clarity_*.py`, `signals_page.py`, `components.py` (menciones), `state.py`, `mentions_paging.py` contiene Rage, Scroll, bot, JavaScript, Snapshot, Device, OS, Browser, token, placeholder, Fase, roadmap ni Likes.
- Las cadenas quedan exactamente como en la propuesta.
- No se tocan menú ni títulos de pestaña (NAV-9 (m-24842958)); sacar Señales del menú es NAV-1 (m-24842957).
- Seguimiento (fundador, 2026-10-23, §2b-7b): el aviso de menciones nuevas (QUA-152) dirá «Llegaron menciones nuevas.» con el botón «Verlas»; no existe aún en `main` (PR #246), aplica cuando se construya.

Evidencia: `docs/ux-auditoria-2026-10/m7-escucha-medicion.md hallazgos 4, 7, 11`; `docs/ux-auditoria-2026-10.md T7`

#### RESULTADOS-1 · [m-24843000](https://project.larksuite.com/5h2wsx/issue/detail/24843000) — Menciones: ver las malas con un toque, saber qué hacer y leerlas completas en el celular

*Como dueño, quiero ver solo las menciones malas con un toque y saber qué hacer, para que ningún cliente molesto quede sin respuesta.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Tocar «Negativas» filtra la lista; cada negativa muestra el texto y el botón exactos.
- Ningún texto sugiere que Qualify responde solo (N13); todo enlace externo lleva destino + ↗ (N9).
- Nada solo en tooltip; a 360 px filtros en una línea y paginador ≥ 44 px (N12).

Evidencia: `docs/ux-auditoria-2026-10/m7 hallazgos 5, 9, 10, historias 4-5`

#### RESULTADOS-3 · [m-24843001](https://project.larksuite.com/5h2wsx/issue/detail/24843001) — Tu página web: cuántas personas la visitaron y qué arreglar primero, sin entender de analítica

*Como dueño con página web, quiero saber cuántas personas la visitaron y qué arreglar primero, sin entender de analítica.*

**P1 · L · reflex-ui-engineer** · Depende de: RESULTADOS-4 (m-24843002)
- Lista para empezar.

Criterios de aceptación:
- La pantalla no contiene «token», «snapshot», «dimensión» ni el cupo de llamadas.
- Cada problema «alto» tiene «Avisar al equipo».
- Sin configuración se ve el mensaje exacto y no el formulario.

Evidencia: `docs/ux-auditoria-2026-10/m7 hallazgo 3, historia 6`

#### RESULTADOS-4 · [m-24843002](https://project.larksuite.com/5h2wsx/issue/detail/24843002) — Tu página web: el equipo conecta Clarity desde Configuración y el dueño nunca ve claves

*Como operador del negocio, quiero conectar Clarity desde Configuración con campos claros, para que el dueño nunca vea claves.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- La pantalla de lectura no muestra ningún campo de configuración.
- En Configuración los campos tienen etiqueta y caben a 360 px (N12).
- La clave sigue cifrada (sin cambios de almacenamiento).

Evidencia: `docs/ux-auditoria-2026-10/m7 hallazgos 3 y 8, historia 7`

#### RESULTADOS-5 · [m-24843003](https://project.larksuite.com/5h2wsx/issue/detail/24843003) — Resultados: un solo lugar con Redes, WhatsApp, Tu página web y «Quién habla de ti»

*Como dueño, quiero ver cómo me va en un solo lugar, para no buscar las cifras en tres pantallas distintas.*

**P2 · L · reflex-ui-engineer + backend-engineer** · Depende de: NAV-4 (m-24842962), RESULTADOS-1 (m-24843000), RESULTADOS-3 (m-24843001)
- Lista para empezar.

Criterios de aceptación:
- Las cuatro pestañas tienen dirección propia (N5) y sus títulos cumplen N1.
- Cada cifra abre la lista filtrada (N11); sin datos, cada pestaña dice qué conectar (N8).
- Las redirecciones de `/clarity` y Menciones funcionan; los conteos respetan RLS.

Evidencia: `docs/ux-guia-navegacion.md §3; §7 decisiones 1-2`; `docs/ux-auditoria-2026-10.md T3`; `docs/ux-auditoria-2026-10/m7 «Navegación»`

#### RESULTADOS-6 · [m-24849134](https://project.larksuite.com/5h2wsx/issue/detail/24849134) — Resultados: «Señales» pasa a llamarse «Oportunidades» en menú, título y pestaña

*Como dueño, quiero que esa entrada del menú diga lo que me va a dar, para entender qué viene sin preguntar.*

**P2 · S · reflex-ui-engineer** · Depende de: NAV-1 (m-24842957)
- Decidida (fundador, 2026-10-23, §2b-6): «Señales» se llama «Oportunidades». Lista para empezar.

Criterios de aceptación:
- Menú, `h1` y pestaña dicen «Oportunidades» (N1); la entrada muestra «Pronto» como texto y no lleva a una pantalla vacía (N10).
- Ningún texto visible dice «Señales» (tampoco «Avisos de oportunidad» como título).

Evidencia: Seguimiento de la ola 1 (PRs #235–#249, 2026-10-23); `docs/ux-guia-navegacion.md §4 N1, N10`

