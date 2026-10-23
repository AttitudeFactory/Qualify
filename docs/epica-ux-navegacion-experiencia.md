# Épica — Qualify en palabras del dueño: navegación y experiencia

`[v1 · 2026-10-23 · product-owner]` · **Meegle:** Feature [m-24842956](https://project.larksuite.com/5h2wsx/story/detail/24842956) con 47 historias (Issues) enlazadas por el campo Feature; 7 borradores más esperan revisión antes de cargarse (§4).

**Origen:** pedido del fundador (2026-10-23): «revisa todo el UX de mi sitio, genera un reporte, invoca al product owner y asígnale crear la épica y las historias para mejorar el UX de nuestra app, separa el trabajo por dominio/módulo, debe existir un patrón guideline de navegación por mi app».

**Evidencia:** auditoría del agente `ux-designer` por lectura de código, sin pruebas con clientes: [`ux-auditoria-2026-10.md`](ux-auditoria-2026-10.md) (hallazgos transversales T1–T11), [`ux-guia-navegacion.md`](ux-guia-navegacion.md) (mapa del menú, reglas N1–N13, §7 decisiones pendientes) y los siete informes [`ux-auditoria-2026-10/m1…m7`](ux-auditoria-2026-10/). Persona: [`perfil-cliente-pyme.md`](perfil-cliente-pyme.md). Todo lo que depende de cómo se comporta el dueño está marcado *hipótesis* en la historia.

**Restricciones firmadas que respetan todas las historias:** asistido, nunca autónomo (nada se publica ni se envía sin un toque del dueño, regla N13); sin programación en TikTok; sin componentes ni colores nuevos sin decisión del fundador y cambio previo en `docs/design-system.md` (la barra inferior del celular es la decisión 5); una sola Postgres.

**Toda historia de código incluye además** estos criterios: revisión local de experiencia (`ux-designer`, `qualify-ux` §6) antes de abrir el PR; prueba a 360 px de cada ruta tocada (N12); `just ci-lint` y `just ci-test` en verde.

## 1. Dominios

| Dominio | Prefijo | Fuente | Historias | P0 listas |
|---|---|---|---|---|
| Navegación e Inicio (transversal) | `[NAV]` | `ux-guia-navegacion.md`, m7 | 9 | 3 |
| Acceso, tu marca y tus redes | `[MARCA]` | m1 | 7 | 2 |
| Tus productos | `[PRODUCTOS]` | m2 | 6 | 1 |
| Crear publicación | `[CREAR]` | m3 | 6 | 2 |
| Aprobar, programar y publicar | `[PUBLICAR]` | m4 | 6 | 2 |
| Responder a clientes | `[ATENDER]` | m5 | 7 | 2 |
| WhatsApp | `[WHATSAPP]` | m6 | 8 | 3 |
| Resultados y menciones | `[RESULTADOS]` | m7 | 5 | 1 |

## 2. Decisiones del fundador que bloquean historias

De [`ux-guia-navegacion.md`](ux-guia-navegacion.md) §7. Una historia bloqueada no se empieza hasta que el fundador decida; si la respuesta es «no», el PO la reescribe o la descarta.

| # | Decisión | Desbloquea |
|---|---|---|
| 1 | Inicio nuevo en `/` y Menciones pasa a Resultados › «Quién habla de ti» | NAV-4 (m-24842962), RESULTADOS-5 (m-24843003) |
| 2 | Reordenar el menú en Inicio · Atiende · Publica · Resultados · Tu negocio (renombra las zonas firmadas «Escuchas / Publicas») | NAV-1 (m-24842957), RESULTADOS-5 (m-24843003) |
| 3 | Un solo «Por responder» que reúne Interacciones, Conversaciones, Consultas y Leads | ATENDER-1 (m-24842990) |
| 4 | Sacar del menú del cliente Creadores y Señales (Vitrina ya decidida: se elimina, NAV-10) | NAV-1 (m-24842957) |
| 5 | Barra inferior fija en el celular (patrón nuevo del sistema de diseño) | NAV-7 (m-24842964) |
| 6 | Acortar el asistente de marca a un mínimo obligatorio y dejar de bloquear el resto de la app | MARCA-4 (borrador) |

**Ya decidido (2026-10-23):** «vitrina se elimina por completo, no tiene relación con nuestro producto por ahora» → NAV-10 (m-24848515), lista en la ola 1. La decisión 4 queda solo para Creadores y Señales.

Otras decisiones que piden algunas historias (fuera de §7):

- **Política de registro por invitación** — opción (a) quitar «Preparar mi marca» del acceso, u (b) avisar antes y capturar interés: MARCA-5 (m-24842968).
- **¿El dueño ve el costo de generar?** — CREAR-5 (borrador).
- **Proceso nuevo en segundo plano para comentarios** — ATENDER-5 (borrador), tras la revisión del arquitecto.

## 3. Lista de historias

| Ticket | Dominio | Historia | Prioridad | Tamaño | Área | Bloqueada por |
|---|---|---|---|---|---|---|
| [m-24842957](https://project.larksuite.com/5h2wsx/issue/detail/24842957) | `NAV-1` | Navegación: adoptar la guía, menú ordenado por los trabajos del dueño | P1 | L | reflex-ui-engineer | #2, #4 |
| [m-24848515](https://project.larksuite.com/5h2wsx/issue/detail/24848515) | `NAV-10` | Navegación: eliminar Vitrina de la app | P0 | S | reflex-ui-engineer | — |
| [m-24842958](https://project.larksuite.com/5h2wsx/issue/detail/24842958) | `NAV-9` | Navegación: un nombre por lugar en menú, título y pestaña (N1) | P0 | S | reflex-ui-engineer | — |
| [m-24842959](https://project.larksuite.com/5h2wsx/issue/detail/24842959) | `NAV-8` | Navegación: ningún texto dice o insinúa que Qualify publica o responde solo (N13) | P0 | S | reflex-ui-engineer | — |
| [m-24842960](https://project.larksuite.com/5h2wsx/issue/detail/24842960) | `NAV-2` | Navegación: cada pestaña y ficha con su dirección; «atrás» del celular no saca del módulo (N5, N7) | P1 | M | reflex-ui-engineer | — |
| [m-24842961](https://project.larksuite.com/5h2wsx/issue/detail/24842961) | `NAV-3` | Navegación: ningún vacío sin salida y toda tarea termina con su siguiente paso (N3, N8) | P1 | M | reflex-ui-engineer | — |
| [m-24842962](https://project.larksuite.com/5h2wsx/issue/detail/24842962) | `NAV-4` | Navegación: Inicio en `/` con «Hoy tienes», «Para tu primera publicación» y «Así te fue» | P1 | L | reflex-ui-engineer + backend-engineer | #1 |
| [m-24842963](https://project.larksuite.com/5h2wsx/issue/detail/24842963) | `NAV-6` | Navegación: contadores de pendientes en el menú y en la pestaña del navegador (N11) | P1 | M | reflex-ui-engineer + backend-engineer | — |
| [m-24842964](https://project.larksuite.com/5h2wsx/issue/detail/24842964) | `NAV-7` | Navegación: barra inferior en el celular con Inicio, Por responder, Crear y Tu semana | P2 | M | reflex-ui-engineer | #5 |
| [m-24842965](https://project.larksuite.com/5h2wsx/issue/detail/24842965) | `MARCA-1` | Tu marca: al terminar, «Tu marca está lista» y el botón «Crear mi primera publicación» | P0 | S | reflex-ui-engineer | — |
| [m-24842966](https://project.larksuite.com/5h2wsx/issue/detail/24842966) | `MARCA-2` | Tu marca: textos del acceso y del asistente en palabras del dueño (sin Brand Kit, brandboard, insights) | P0 | S | reflex-ui-engineer | — |
| [m-24842967](https://project.larksuite.com/5h2wsx/issue/detail/24842967) | `MARCA-3` | Acceso: crear la cuenta con cuatro campos con etiqueta y el país en lugar de zona horaria y moneda | P1 | M | reflex-ui-engineer | — |
| borrador (sin ticket) | `MARCA-4` | Tu marca: lo mínimo en 5 pasos y el resto sin bloquear la app | P1 | L | reflex-ui-engineer | #6, revisión |
| [m-24842968](https://project.larksuite.com/5h2wsx/issue/detail/24842968) | `MARCA-5` | Acceso: el visitante sin invitación sabe antes de empezar que la necesita | P1 | S | reflex-ui-engineer | fundador (fuera de §7) |
| [m-24842969](https://project.larksuite.com/5h2wsx/issue/detail/24842969) | `MARCA-6` | Tus redes: saber de un vistazo si mi Instagram funciona, qué puedo hacer y qué sigue al conectarlo | P1 | M | reflex-ui-engineer | — |
| [m-24842970](https://project.larksuite.com/5h2wsx/issue/detail/24842970) | `MARCA-7` | Tu marca: «Editar mi marca» abre en el resumen de mi marca, no en el ranking de referentes | P2 | M | reflex-ui-engineer | — |
| [m-24842971](https://project.larksuite.com/5h2wsx/issue/detail/24842971) | `PRODUCTOS-6` | Tus productos: textos y errores en palabras del dueño | P0 | S | reflex-ui-engineer | — |
| [m-24842972](https://project.larksuite.com/5h2wsx/issue/detail/24842972) | `PRODUCTOS-1` | Tus productos: «Crear publicación con este producto» abre Crear con el producto ya elegido | P1 | M | reflex-ui-engineer | — |
| [m-24842973](https://project.larksuite.com/5h2wsx/issue/detail/24842973) | `PRODUCTOS-2` | Tus productos: volver a mi publicación con el producto que agregué (N4) | P2 | M | reflex-ui-engineer | — |
| [m-24842974](https://project.larksuite.com/5h2wsx/issue/detail/24842974) | `PRODUCTOS-3` | Tus productos: agregar un producto en tres pasos desde el celular, la foto primero | P1 | M | reflex-ui-engineer | — |
| [m-24842976](https://project.larksuite.com/5h2wsx/issue/detail/24842976) | `PRODUCTOS-4` | Tus productos: editar sin perder cambios, en pantalla completa en el celular y con su dirección | P1 | M | reflex-ui-engineer | — |
| [m-24842977](https://project.larksuite.com/5h2wsx/issue/detail/24842977) | `PRODUCTOS-5` | Tus productos: marcar la foto principal y quitar fotos sin equivocarme | P2 | S | reflex-ui-engineer | — |
| [m-24842978](https://project.larksuite.com/5h2wsx/issue/detail/24842978) | `CREAR-1` | Crear: al aprobar, «Aprobada. Todavía no se publica.» con el botón «Elegir día y hora» | P0 | S | reflex-ui-engineer | — |
| [m-24842979](https://project.larksuite.com/5h2wsx/issue/detail/24842979) | `CREAR-4` | Crear: todo dice «publicación» y habla como el dueño (sin POST, caption, CTA, HITL, Brand Kit ni proveedores) | P0 | M | reflex-ui-engineer | — |
| borrador (sin ticket) | `CREAR-2` | Crear: una publicación en cuatro pasos cortos, lo opcional detrás de «Más opciones» | P1 | L | reflex-ui-engineer | revisión |
| [m-24842980](https://project.larksuite.com/5h2wsx/issue/detail/24842980) | `CREAR-6` | Crear: en el celular ver todos los tipos con su explicación y escribir los datos clave sin comas | P1 | S | reflex-ui-engineer | — |
| [m-24842981](https://project.larksuite.com/5h2wsx/issue/detail/24842981) | `CREAR-3` | Crear: en Mis publicaciones, estados en texto y un solo botón claro por publicación | P1 | M | reflex-ui-engineer | — |
| borrador (sin ticket) | `CREAR-5` | Crear: el costo de pedir otra versión, en la moneda del negocio o como creaciones del mes | P2 | M | reflex-ui-engineer + creative-engineer | revisión |
| [m-24842982](https://project.larksuite.com/5h2wsx/issue/detail/24842982) | `PUBLICAR-1` | Tu semana: en el celular, «Tienes {n} publicaciones aprobadas esperando día y hora» con su botón | P0 | S | reflex-ui-engineer | — |
| [m-24842983](https://project.larksuite.com/5h2wsx/issue/detail/24842983) | `PUBLICAR-5` | Tu semana y Publicar ahora: textos y errores en español sencillo (sin POST, caption, Stories, Cold/Hot, tenant, R2) | P0 | S | reflex-ui-engineer | — |
| [m-24842984](https://project.larksuite.com/5h2wsx/issue/detail/24842984) | `PUBLICAR-2` | Tu semana: aprobar o descartar una publicación desde su ficha | P1 | M | reflex-ui-engineer | — |
| [m-24842985](https://project.larksuite.com/5h2wsx/issue/detail/24842985) | `PUBLICAR-3` | Tu semana: programar eligiendo solo día y hora, o «Ahora» | P1 | M | reflex-ui-engineer | — |
| [m-24842986](https://project.larksuite.com/5h2wsx/issue/detail/24842986) | `PUBLICAR-4` | Publicar ahora: subir algo del teléfono en tres pasos y saber qué sigue al publicar | P1 | M | reflex-ui-engineer | — |
| [m-24842987](https://project.larksuite.com/5h2wsx/issue/detail/24842987) | `PUBLICAR-6` | Tu semana: volver siempre a mi semana y usarla con el pulgar | P2 | M | reflex-ui-engineer | — |
| [m-24842988](https://project.larksuite.com/5h2wsx/issue/detail/24842988) | `ATENDER-8` | Atender: comentarios, conversaciones e interesados en palabras del dueño, sin números internos | P0 | S | reflex-ui-engineer | — |
| [m-24842989](https://project.larksuite.com/5h2wsx/issue/detail/24842989) | `ATENDER-3` | Comentarios: primero las respuestas listas para aprobar; configurar qué revisar, detrás de «Más opciones» | P0 | M | reflex-ui-engineer | — |
| borrador (sin ticket) | `ATENDER-4` | Comentarios: responder en público cualquier comentario, también preguntas y quejas | P0 | M | backend-engineer + reflex-ui-engineer | revisión |
| borrador (sin ticket) | `ATENDER-5` | Comentarios: buscar, ordenar y preparar respuestas solos, sin que el dueño tenga la pantalla abierta | P0 | L | backend-engineer + reflex-ui-engineer | revisión |
| [m-24842990](https://project.larksuite.com/5h2wsx/issue/detail/24842990) | `ATENDER-1` | Atender: un solo «Por responder» con los pendientes de cada canal y pestañas con su dirección | P1 | L | reflex-ui-engineer + backend-engineer | #3 |
| [m-24842991](https://project.larksuite.com/5h2wsx/issue/detail/24842991) | `ATENDER-6` | Quieren comprar: responder en tres pasos cortos y pasar a la siguiente consulta | P1 | M | reflex-ui-engineer | — |
| [m-24842992](https://project.larksuite.com/5h2wsx/issue/detail/24842992) | `ATENDER-7` | Clientes interesados: escribirles por WhatsApp desde la lista y saber a quién ya contacté | P2 | M | reflex-ui-engineer + backend-engineer | — |
| [m-24842993](https://project.larksuite.com/5h2wsx/issue/detail/24842993) | `WHATSAPP-1` | WhatsApp: con el chat vencido, decir qué pasa y llevar a los mensajes aprobados | P0 | S | reflex-ui-engineer | — |
| [m-24842994](https://project.larksuite.com/5h2wsx/issue/detail/24842994) | `WHATSAPP-8` | WhatsApp: textos sin opt-in, leads, Marketing, Lanzar ni Revocar; distintivos de los chats explicados | P0 | S | reflex-ui-engineer | — |
| [m-24842995](https://project.larksuite.com/5h2wsx/issue/detail/24842995) | `WHATSAPP-3` | WhatsApp: publicar el menú automático con un solo botón y saber qué sigue | P0 | M | reflex-ui-engineer | — |
| borrador (sin ticket) | `WHATSAPP-2` | WhatsApp: enviar un mensaje aprobado desde el chat vencido | P0 | M | backend-engineer + reflex-ui-engineer | revisión |
| borrador (sin ticket) | `WHATSAPP-4` | WhatsApp: armar el menú automático en cuatro pasos, sin identificadores técnicos | P0 | L | reflex-ui-engineer | revisión |
| [m-24842996](https://project.larksuite.com/5h2wsx/issue/detail/24842996) | `WHATSAPP-5` | WhatsApp: enviar una promoción en tres pasos (mensaje, a quién, revisar) | P1 | M | reflex-ui-engineer | — |
| [m-24842997](https://project.larksuite.com/5h2wsx/issue/detail/24842997) | `WHATSAPP-6` | WhatsApp: crear un mensaje de promoción guiado para que lo aprueben a la primera | P1 | M | reflex-ui-engineer | — |
| [m-24842998](https://project.larksuite.com/5h2wsx/issue/detail/24842998) | `WHATSAPP-7` | WhatsApp: cuatro pestañas con nombres de tareas, «Tu número» en una línea y tablas como tarjetas en el celular | P1 | L | reflex-ui-engineer | — |
| [m-24842999](https://project.larksuite.com/5h2wsx/issue/detail/24842999) | `RESULTADOS-2` | Resultados: Menciones, Clarity y Señales en palabras del dueño (sin Rage clicks, snapshot, placeholder ni roadmap) | P0 | M | reflex-ui-engineer | — |
| [m-24843000](https://project.larksuite.com/5h2wsx/issue/detail/24843000) | `RESULTADOS-1` | Menciones: ver las malas con un toque, saber qué hacer y leerlas completas en el celular | P1 | M | reflex-ui-engineer | — |
| [m-24843001](https://project.larksuite.com/5h2wsx/issue/detail/24843001) | `RESULTADOS-3` | Tu página web: cuántas personas la visitaron y qué arreglar primero, sin entender de analítica | P1 | L | reflex-ui-engineer | — |
| [m-24843002](https://project.larksuite.com/5h2wsx/issue/detail/24843002) | `RESULTADOS-4` | Tu página web: el equipo conecta Clarity desde Configuración y el dueño nunca ve claves | P1 | M | reflex-ui-engineer | — |
| [m-24843003](https://project.larksuite.com/5h2wsx/issue/detail/24843003) | `RESULTADOS-5` | Resultados: un solo lugar con Redes, WhatsApp, Tu página web y «Quién habla de ti» | P2 | L | reflex-ui-engineer + backend-engineer | #1, #2 |

## 4. Borradores que esperan revisión antes de cargarse

Regla del PO: lo que necesita revisión de factibilidad (`principal-architect`) o de costo y medición
(`data-scientist-fde`) no se carga en Meegle hasta pasar esa revisión. Siete historias quedan como
borrador (texto completo en §8); el hilo principal corre la revisión y el PO carga las que sobrevivan.

| Borrador | Prioridad | Revisión que necesita |
|---|---|---|
| MARCA-4 — marca mínima en 5 pasos | P1 · L | Arquitecto: desbloqueo de `brand_kit_complete` (`auth_state.py:282`) y referentes en segundo plano. Además, decisión #6 |
| CREAR-2 — crear en 4 pasos | P1 · L | Arquitecto: reordenar `generator_views` sin romper avatar/video |
| CREAR-5 — costo en la moneda del negocio | P2 · M | Fundador (¿quién ve el costo?) + datasci si se cuentan «creaciones del mes» |
| ATENDER-4 — responder en público cualquier comentario | P0 · M | Datasci: el prompt de respuestas para neutros y negativos se mide antes (`qualify-measure`); arquitecto: permiso de comentarios ya concedido en App Review |
| ATENDER-5 — comentarios ordenados y preparados en segundo plano | P0 · L | Arquitecto: worker nuevo o extendido, idempotencia, presupuesto de llamadas a Meta; datasci: costo de clasificar cada comentario; fundador si es un proceso nuevo en producción |
| WHATSAPP-2 — enviar mensaje aprobado desde el chat vencido | P0 · M | Arquitecto: envío de una plantilla a un contacto (hoy solo en campañas), idempotencia, costo |
| WHATSAPP-4 — menú automático en 4 pasos | P0 · L | Arquitecto: identificadores generados sin romper menús publicados |

## 5. Orden sugerido, por olas

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

**Ola 2 — guía base y pasos guiados (P1, listos).** NAV-2 (m-24842960) (direcciones `?tab=`), NAV-3 (m-24842961) (vacíos y
siguientes pasos), NAV-6 (m-24842963) (contadores); MARCA-3 (m-24842967), MARCA-6 (m-24842969); PRODUCTOS-1 (m-24842972), PRODUCTOS-3 (m-24842974), PRODUCTOS-4 (m-24842976);
CREAR-3 (m-24842981), CREAR-6 (m-24842980); PUBLICAR-2 (m-24842984), PUBLICAR-3 (m-24842985), PUBLICAR-4 (m-24842986); ATENDER-6 (m-24842991); WHATSAPP-5 (m-24842996), WHATSAPP-6 (m-24842997),
WHATSAPP-7 (m-24842998); RESULTADOS-1 (m-24843000), RESULTADOS-4 (m-24843002) → RESULTADOS-3 (m-24843001). Más los borradores de §5 que pasen la
revisión (ATENDER-4, ATENDER-5, WHATSAPP-2 y WHATSAPP-4 son P0 y suben al frente de esta ola).

**Ola 3 — los hubs que dependen de decisiones del fundador.** NAV-1 (m-24842957) (menú nuevo, #2 y #4),
NAV-4 (m-24842962) (Inicio, #1), ATENDER-1 (m-24842990) (Por responder, #3), RESULTADOS-5 (m-24843003) (Resultados, #1 y #2),
MARCA-4 (#6, tras revisión), NAV-7 (m-24842964) (barra inferior, #5, primero el sistema de diseño). MARCA-5 (m-24842968)
cuando el fundador elija la opción de registro.

**Ola 4 — pulido (P2).** PRODUCTOS-2 (m-24842973), PRODUCTOS-5 (m-24842977), PUBLICAR-6 (m-24842987), ATENDER-7 (m-24842992), MARCA-7 (m-24842970), CREAR-5.

El celular (N12) no es una historia aparte: cada historia que toca una pantalla lo trae en sus
criterios.

## 6. Preguntas abiertas para el fundador

1. Las seis decisiones de §2 (guía §7).
2. **«Piezas»**: NAV-9 (m-24842958) la renombra «Mis publicaciones» (informe m3); el mapa de la guía la llama
   «Por aprobar». ¿Cuál queda? (Si es «Por aprobar», se decide junto con la #2.)
3. **«Leads»**: `docs/design-system.md` §7.2 dice usar «lead» y `qualify-ux` §3 lo prohíbe. NAV-9 (m-24842958)
   y ATENDER-8 (m-24842988) usan «Clientes interesados» («Interesados» en el menú). Confirmar, y corregir el
   glosario del sistema de diseño en el mismo PR de NAV-9 (m-24842958).
4. **Moneda por defecto en Venezuela** (MARCA-3 (m-24842967)): ¿bolívares o dólares? *Hipótesis*: muchos locales
   ponen el precio en dólares (perfil §5 pregunta 4).
5. **Registro sin invitación** (MARCA-5 (m-24842968)): opción (a) o (b).
6. **Costo de generar** (CREAR-5): ¿lo ve el dueño o solo el equipo?
7. **«Reel» o «video corto»** y **¿Clarity la usa algún cliente hoy?**: validar con Bianki/Polette
   (perfil §5 preguntas 4-5). RESULTADOS-3 (m-24843001) quedó P1 y no P0 por esto.

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
- ⚑ Bloqueada por decisión del fundador #2: Reordenar el menú en Inicio · Atiende · Publica · Resultados · Tu negocio (renombra las zonas firmadas «Escuchas / Publicas»).
- ⚑ Bloqueada por decisión del fundador #4: Sacar del menú del cliente Creadores y Señales (Vitrina ya decidida: se elimina, NAV-10).

Criterios de aceptación:
- El menú del cliente tiene como máximo 12 entradas, en el orden de la guía §3, y ninguna con `enabled=False` ni insignia «pronto» (N10).
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

Fuera de alcance: Creadores y Señales (NAV-1 (m-24842957), decisión 4). Cualquier otro cambio en el menú (NAV-9 (m-24842958), NAV-1 (m-24842957)).

Evidencia: Decisión del fundador, 2026-10-23: «vitrina se elimina por completo, no tiene relación con nuestro producto por ahora»; `docs/ux-guia-navegacion.md §3, §7`; `docs/ux-auditoria-2026-10.md T11`; `docs/ux-auditoria-2026-10/m7-escucha-medicion.md hallazgo 6`

#### NAV-9 · [m-24842958](https://project.larksuite.com/5h2wsx/issue/detail/24842958) — Navegación: un nombre por lugar en menú, título y pestaña (N1)

*Como dueño, quiero que cada lugar tenga un solo nombre, en mis palabras, en el menú, en el título de la pantalla y en la pestaña del navegador, para saber siempre dónde estoy.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Para cada entrada del menú, el texto de `layout.py`, el `h1` del `page_header` y el `title` de `add_page` coinciden (N1); una prueba offline lo verifica.
- Ninguna entrada del menú, título ni pestaña contiene «Brand Kit», «Catálogo», «Conexiones», «pieza», «Piezas», «Planificador», «Stories», «Interacciones», «Leads», «Clarity» ni «Borrador».
- Los textos de «volver» que nombran estas pantallas usan el nombre nuevo (N7): «‹ Tus productos», «‹ Tu semana», «‹ Mis publicaciones».

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
- ⚑ Bloqueada por decisión del fundador #1: Inicio nuevo en `/` y Menciones pasa a Resultados › «Quién habla de ti».

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
- ⚑ Bloqueada por decisión del fundador #5: Barra inferior fija en el celular (patrón nuevo del sistema de diseño).

Criterios de aceptación:
- Existe la sección del patrón en `docs/design-system.md`, aprobada por el fundador, antes del PR de código.
- A 360 px la barra muestra 4 accesos + «Más», objetivos ≥ 44 px, y no tapa contenido ni botones principales.
- En escritorio no aparece.

Fuera de alcance: Cambiar el cajón actual de escritorio.

Evidencia: `docs/ux-guia-navegacion.md §6; §7 decisión 5`; `docs/ux-auditoria-2026-10.md T10`

### [MARCA] Acceso, tu marca y tus redes

#### MARCA-1 · [m-24842965](https://project.larksuite.com/5h2wsx/issue/detail/24842965) — Tu marca: al terminar, «Tu marca está lista» y el botón «Crear mi primera publicación»

*Como dueño que acaba de terminar su marca, quiero que me lleven a crear mi primera publicación, para ver el resultado enseguida.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Al terminar la marca se ve exactamente «Tu marca está lista» con los tres accesos de la propuesta (N3).
- Ya no se aterriza en Menciones al terminar; el texto «Mejorar tu perfil» desaparece.
- Botones de la tarjeta con área táctil ≥ 44 px (N12).

Fuera de alcance: Acortar el asistente (MARCA-4). Inicio (NAV-4 (m-24842962)): cuando exista, «Seguir después» lleva a Inicio.

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
- Un negocio registrado con «Colombia» queda con zona `America/Bogota` y moneda COP; «Uruguay» con `America/Montevideo` y UYU; «Venezuela» con `America/Caracas` (moneda por defecto a confirmar con el fundador, ver preguntas).
- A 360 px el formulario es de una columna, sin desplazamiento horizontal, botones ≥ 44 px (N12).

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgos 7-9, historia A1`

#### MARCA-4 · borrador (sin ticket) — Tu marca: lo mínimo en 5 pasos y el resto sin bloquear la app

*Como dueño, quiero dejar lista mi marca en 5 pasos cortos, para poder hacer mi primera publicación hoy.*

**P1 · L · reflex-ui-engineer**
- ⚑ Bloqueada por decisión del fundador #6: Acortar el asistente de marca a un mínimo obligatorio y dejar de bloquear el resto de la app.
- ⚑ Necesita: Revisión de factibilidad del arquitecto (desbloqueo de `brand_kit_complete` en `auth_state.py` y referentes en segundo plano).

Criterios de aceptación:
- El camino obligatorio tiene como máximo 5 pasos y «Paso N de M» cuenta solo los que ve ese dueño (N6).
- Terminado el paso ⑤, todas las pantallas de la app se abren; lo opcional aparece en «Mejora tu marca».
- Cada paso tiene «Seguir después», que guarda y no pierde datos; «Atrás» conserva lo escrito.
- No queda ninguna pantalla de espera sin control (referentes en segundo plano).

Fuera de alcance: Cambiar los modelos o prompts que leen el perfil.

Evidencia: `docs/ux-auditoria-2026-10/m1 hallazgo 3, historia B1`; `docs/ux-guia-navegacion.md §7 decisión 6`; `docs/ux-auditoria-2026-10.md §3`

#### MARCA-5 · [m-24842968](https://project.larksuite.com/5h2wsx/issue/detail/24842968) — Acceso: el visitante sin invitación sabe antes de empezar que la necesita

*Como visitante sin invitación, quiero saber antes de armar mi marca que necesito una invitación, para no perder 15 minutos de trabajo.*

**P1 · S · reflex-ui-engineer**
- ⚑ Necesita: Decisión del fundador fuera de §7: política de registro por invitación — opción (a) quitar «Preparar mi marca» del acceso, u opción (b) avisar antes y cerrar con captura de interés.

Criterios de aceptación:
- Ningún recorrido termina en «Qualify es solo por invitación» sin ofrecer dejar los datos de contacto.
- Se implementa la opción que elija el fundador, con los textos exactos de la propuesta.

Fuera de alcance: Abrir el registro público (decisión aparte).

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

### [PRODUCTOS] Tus productos

#### PRODUCTOS-6 · [m-24842971](https://project.larksuite.com/5h2wsx/issue/detail/24842971) — Tus productos: textos y errores en palabras del dueño

*Como dueño, quiero que la pantalla de productos me hable de lo que gano y en mis palabras, para entenderla sin preguntar a nadie.*

**P0 · S · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Ningún texto visible de `catalog_page.py` / `catalog_state.py` / `catalog_vm.py` contiene «plantilla», «Reel», «feed», «pieza», «gancho», «provisionada» ni «base de datos».
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
- Ninguna cadena visible de `creative_pages.py`, `content_generator.py`, `creative_vm.py`, `creative_state.py`, `variations_view.py`, `voice_lab.py` contiene POST, caption, CTA, Flyer, Story, UGC, HITL, Bandeja, Copy, Brand Kit, Claude, `QUALIFY_` ni «base de datos».
- Los avisos de marca llevan a `/brand/kit` y dicen «tu marca».
- Las cadenas quedan exactamente como en la propuesta. «Video corto» frente a «reel» es *hipótesis* (perfil §5 pregunta 4).
- No se tocan menú ni títulos de pestaña (NAV-9 (m-24842958)).

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgos 3, 4, 8, 9, 10, 12, historias B1-B3`; `docs/ux-auditoria-2026-10.md T4, T7`

#### CREAR-2 · borrador (sin ticket) — Crear: una publicación en cuatro pasos cortos, lo opcional detrás de «Más opciones»

*Como dueño, quiero crear una publicación en 4 pasos cortos, para terminarla en 2 minutos desde el celular.*

**P1 · L · reflex-ui-engineer**
- ⚑ Necesita: Revisión de factibilidad del arquitecto (reordenar `generator_views` en `creative_state.py:425-494` sin romper los tipos de avatar/video).

Criterios de aceptación:
- `/create` muestra «Paso N de 4» con esos cuatro pasos (N6).
- Datos clave, qué evitar, campaña, formato y presentador quedan en «Más opciones» con valores rellenados.
- «Atrás» conserva lo escrito; una segunda publicación con valores por defecto se completa con 3 toques de «Siguiente» y «Crear».
- A 360 px: una columna, sin desplazamiento lateral, botones ≥ 44 px (N12).

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

#### CREAR-3 · [m-24842981](https://project.larksuite.com/5h2wsx/issue/detail/24842981) — Crear: en Mis publicaciones, estados en texto y un solo botón claro por publicación

*Como dueño, quiero ver en mis publicaciones un solo botón claro por cada una, para saber qué me toca hacer.*

**P1 · M · reflex-ui-engineer**
- Lista para empezar.

Criterios de aceptación:
- Cada tarjeta muestra su estado en texto y un único botón principal según la tabla.
- Ningún texto visible contiene Cold, Hot ni evergreen; la ayuda no vive solo en `title=`.

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgos 5 y 12, historia A3`

#### CREAR-5 · borrador (sin ticket) — Crear: el costo de pedir otra versión, en la moneda del negocio o como creaciones del mes

*Como dueño con presupuesto chico, quiero saber antes de pedir otra versión si me cuesta y cuánto, en mi moneda, para no llevarme sorpresas.*

**P2 · M · reflex-ui-engineer + creative-engineer**
- ⚑ Necesita: Decisión del fundador fuera de §7: ¿el dueño ve el costo de generar, o solo el equipo que opera la cuenta?.
- ⚑ Necesita: Revisión de costo del data-scientist-fde si se muestra «N de tus creaciones del mes».

Criterios de aceptación:
- Desaparece «Consume créditos» sin número.
- Si se muestra costo, va en la moneda del negocio o en «N de tus creaciones del mes», sin depender de pasar el mouse.
- *Hipótesis* (perfil §5 preguntas 1-2): validar con Bianki/Polette quién debe ver el costo.

Fuera de alcance: Cambiar la tabla de precios versionada (`qualify_creative/pricing_data/`).

Evidencia: `docs/ux-auditoria-2026-10/m3 hallazgo 6, historia C1`

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
- Las cadenas quedan exactamente como en la propuesta. «Reel» → «video corto» es *hipótesis* (perfil §5 pregunta 4).
- No se tocan menú ni títulos de pestaña (NAV-9 (m-24842958)) ni los textos de publicación automática (NAV-8 (m-24842959)).

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

#### ATENDER-4 · borrador (sin ticket) — Comentarios: responder en público cualquier comentario, también preguntas y quejas

*Como dueño, quiero poder contestar en público cualquier comentario, también preguntas y quejas, para que nadie quede ignorado delante de los demás.*

**P0 · M · backend-engineer + reflex-ui-engineer**
- ⚑ Necesita: Revisión del data-scientist-fde: el borrador para comentarios neutros y negativos cambia el prompt de respuestas (medir antes, `qualify-measure`).
- ⚑ Necesita: Revisión del arquitecto: confirmar que responder en público usa el permiso de comentarios ya concedido (App Review).

Criterios de aceptación:
- Cada comentario ofrece «Responder aquí» y «Escribirle en privado».
- Se prepara respuesta para comentarios positivos, neutros y negativos; en los negativos se exige editar o confirmar «Revísala antes de aprobar».
- Nada se envía sin el toque del dueño (N13); el comentario respondido pasa a «Respondidos».
- El cambio de prompt queda medido y documentado según `qualify-measure`; `just ci-test` en verde con pruebas de RLS.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgo 3, historia 5`; `docs/ux-auditoria-2026-10.md §3`

#### ATENDER-5 · borrador (sin ticket) — Comentarios: buscar, ordenar y preparar respuestas solos, sin que el dueño tenga la pantalla abierta

*Como dueño, quiero que los comentarios nuevos se busquen y se ordenen solos, para no tener que pulsar botones antes de ver quién quiere comprar.*

**P0 · L · backend-engineer + reflex-ui-engineer**
- ⚑ Necesita: Revisión del arquitecto: worker nuevo o extensión de uno existente (`*-worker`), idempotencia y presupuesto de llamadas a Meta.
- ⚑ Necesita: Revisión de costo del data-scientist-fde: clasificar con Haiku cada comentario sin pantalla abierta.
- ⚑ Necesita: Decisión del fundador si implica un proceso nuevo en producción.

Criterios de aceptación:
- Un comentario nuevo aparece ordenado y con borrador sin abrir la pantalla, dentro del intervalo acordado con el arquitecto.
- «Analizar sentimiento», «Analizar intención» y «Generar borradores» dejan de ser pasos obligatorios; queda «Buscar ahora».
- Ningún comentario se responde sin aprobación (N13); el proceso es idempotente y guarda procedencia (modelo y versión del prompt).
- Costo por comentario medido y documentado antes de activarlo en producción.

Evidencia: `docs/ux-auditoria-2026-10/m5 hallazgo 6, historia 6`; `docs/ux-auditoria-2026-10.md §3`

#### ATENDER-1 · [m-24842990](https://project.larksuite.com/5h2wsx/issue/detail/24842990) — Atender: un solo «Por responder» con los pendientes de cada canal y pestañas con su dirección

*Como dueño, quiero ver en una sola pantalla cuántas personas esperan mi respuesta en cada canal, para no dejar a nadie sin contestar más de 2 horas.*

**P1 · L · reflex-ui-engineer + backend-engineer** · Depende de: NAV-2 (m-24842960)
- ⚑ Bloqueada por decisión del fundador #3: Un solo «Por responder» que reúne Interacciones, Conversaciones, Consultas y Leads.

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

#### WHATSAPP-2 · borrador (sin ticket) — WhatsApp: enviar un mensaje aprobado desde el chat vencido

*Como dueño, quiero responder a un cliente aunque hayan pasado más de 24 horas, para no perder una venta.*

**P0 · M · backend-engineer + reflex-ui-engineer** · Depende de: WHATSAPP-1 (m-24842993)
- ⚑ Necesita: Revisión del arquitecto: envío de una plantilla a un solo contacto (hoy solo existe en campañas), idempotencia y costo por conversación.

Criterios de aceptación:
- Con el chat vencido aparece «Enviar un mensaje aprobado»; la lista muestra solo plantillas aprobadas con vista previa.
- Se envía solo tras tocar «Enviar» (N13); el mensaje aparece en la conversación con su estado.
- Reintentos no duplican el envío; pruebas offline con RLS en verde.

Evidencia: `docs/ux-auditoria-2026-10/m6 hallazgo 1, historia 1`

#### WHATSAPP-4 · borrador (sin ticket) — WhatsApp: armar el menú automático en cuatro pasos, sin identificadores técnicos

*Como dueño, quiero armar mi menú automático en 4 pasos cortos con mis textos y mi catálogo, para que WhatsApp atienda lo básico sin que yo aprenda a programar.*

**P0 · L · reflex-ui-engineer**
- ⚑ Necesita: Revisión de factibilidad del arquitecto: generar identificadores de pasos automáticamente sin romper menús ya publicados.

Criterios de aceptación:
- «Paso N de 4», «Atrás» sin perder datos (N6).
- Ningún identificador técnico visible en el camino principal.
- Un dueño de prueba termina en ≤ 5 min desde la plantilla (*hipótesis*, perfil §5 pregunta 3).

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
- ⚑ Bloqueada por decisión del fundador #1: Inicio nuevo en `/` y Menciones pasa a Resultados › «Quién habla de ti».
- ⚑ Bloqueada por decisión del fundador #2: Reordenar el menú en Inicio · Atiende · Publica · Resultados · Tu negocio (renombra las zonas firmadas «Escuchas / Publicas»).

Criterios de aceptación:
- Las cuatro pestañas tienen dirección propia (N5) y sus títulos cumplen N1.
- Cada cifra abre la lista filtrada (N11); sin datos, cada pestaña dice qué conectar (N8).
- Las redirecciones de `/clarity` y Menciones funcionan; los conteos respetan RLS.

Evidencia: `docs/ux-guia-navegacion.md §3; §7 decisiones 1-2`; `docs/ux-auditoria-2026-10.md T3`; `docs/ux-auditoria-2026-10/m7 «Navegación»`

