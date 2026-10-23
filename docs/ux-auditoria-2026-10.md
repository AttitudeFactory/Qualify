# Auditoría de experiencia de la app — octubre 2026

`[v1 · 2026-10-23 · agente ux-designer]` · **Alcance:** todas las pantallas que ve un cliente en
`Qualify/` (≈ 27 000 líneas de vistas, 30 rutas). **Método:** lectura del código de cada pantalla
(textos, pasos, estados vacíos y de error, navegación) contra `docs/perfil-cliente-pyme.md` y la
checklist `qualify-ux`. **No** hubo pruebas con clientes ni recorrido en vivo: todo lo que depende de
cómo se comporta el dueño está marcado *hipótesis* y enlazado a una pregunta del perfil §5.
Solo sugerencias: no se tocó código de la app.

| Documento | Qué tiene |
|---|---|
| Este archivo | Resumen, hallazgos transversales, prioridades y épica propuesta |
| [`ux-guia-navegacion.md`](ux-guia-navegacion.md) | **El patrón de navegación**: mapa del menú, reglas N1–N13, recorrido principal, decisiones pendientes |
| [`ux-auditoria-2026-10/m1-acceso-marca-conexiones.md`](ux-auditoria-2026-10/m1-acceso-marca-conexiones.md) | Registro, entrada, asistente de marca, conexiones, configuración |
| [`ux-auditoria-2026-10/m2-catalogo.md`](ux-auditoria-2026-10/m2-catalogo.md) | Tus productos |
| [`ux-auditoria-2026-10/m3-crear-piezas.md`](ux-auditoria-2026-10/m3-crear-piezas.md) | Crear publicación (`content_generator.py`), revisión, galería |
| [`ux-auditoria-2026-10/m4-planificar-publicar.md`](ux-auditoria-2026-10/m4-planificar-publicar.md) | Planificador, publicar, historias |
| [`ux-auditoria-2026-10/m5-responder-clientes.md`](ux-auditoria-2026-10/m5-responder-clientes.md) | Interacciones, conversaciones, consultas, leads |
| [`ux-auditoria-2026-10/m6-whatsapp.md`](ux-auditoria-2026-10/m6-whatsapp.md) | WhatsApp: chats, menú automático, plantillas, contactos, campañas |
| [`ux-auditoria-2026-10/m7-escucha-medicion.md`](ux-auditoria-2026-10/m7-escucha-medicion.md) | Inicio/Menciones, Señales, Clarity, Vitrina |

Cada informe de módulo tiene hasta 12 hallazgos con `archivo:línea`, el problema en palabras del
dueño, el arreglo exacto (texto o pasos con maqueta), esfuerzo S/M/L, su navegación actual y
propuesta, y hasta 8 historias sugeridas.

## 1. Veredicto en cinco líneas

1. **El dueño no sabe por dónde empezar:** aterriza en Menciones (`/`), que no le dice ni «qué hago
   hoy» ni «cómo me va».
2. **Los trabajos están partidos:** responder está en 4 lugares sin enlace; publicar, en 4 entradas
   que no se encadenan; medir, en 3.
3. **Casi ninguna tarea termina con un siguiente paso:** aprobar, publicar, crear un producto o
   enviar una consulta acaban en un aviso flotante o en un callejón sin salida.
4. **La app habla como la herramienta, no como el dueño:** Brand Kit, POST, caption, CTA, Cold/Hot,
   opt-in, leads, insights, «identificador del paso», nombres de proveedores y variables de servidor.
5. **Los procesos que se repiten son formularios largos:** 12 pasos obligatorios de marca, 8 pantallas
   antes de «Generar», 8 datos por pieza al programar, 7+ campos por plantilla de WhatsApp.

## 2. Hallazgos transversales (aparecen en varios módulos)

| # | Hallazgo | Módulos | Regla de la guía |
|---|---|---|---|
| T1 | No hay Inicio: todo aterriza en Menciones | m1, m7 | N2 |
| T2 | Tareas que terminan en toast o sin salida (aprobar, publicar, crear producto, consulta, menú de WhatsApp publicado, chat vencido) | m1–m6 | N3, N8 |
| T3 | Mismo trabajo en varios lugares (responder ×4, publicar ×4, medir ×3, «conectar» ×2) | m1, m4, m5, m6, m7 | §3 mapa |
| T4 | Tres o cuatro nombres para lo mismo: pieza / POST / borrador / publicación; Marca / Brandkit / Tu Brand Kit / Editar Brand Kit; Conexiones / Cuentas conectadas | m1, m3, m4 | N1 |
| T5 | Ir a otro módulo a buscar algo y no poder volver (Crear → Catálogo; Planificador → Piezas) | m2, m3, m4 | N4, N7 |
| T6 | Pestañas y fichas sin dirección propia: «atrás» del celular saca del módulo (WhatsApp `?tab=`, editor del catálogo, detalle de comentarios, vista Consultas) | m2, m5, m6 | N5 |
| T7 | Palabras prohibidas, en inglés o internas en todos los módulos | todos | `qualify-copy-es`, `qualify-ux` §3 |
| T8 | Formularios de varios dominios en una pantalla | m1, m2, m3, m4, m6 | N6 |
| T9 | Textos que contradicen «asistido, nunca autónomo»: «Publicación automática activa» (`planner_drawer.py:1601`), «Qualify no podrá publicar o responder mensajes por ti» (`connections_page.py:604`) | m1, m4 | N13 |
| T10 | En el celular: botones de 24–32 px, información solo al pasar el mouse, tablas de 6–10 columnas, 8 pestañas en una fila | todos | N12 |
| T11 | Menú con cosas que el dueño no puede usar: Creadores y Señales «pronto», Vitrina (demo de otro negocio; **decidido 2026-10-23: se elimina por completo**) | m7 | N10 |

## 3. Lo que impide terminar (severidad 1), por módulo

| Módulo | Hallazgo | Dónde | Esf. |
|---|---|---|---|
| Acceso y marca | El invitado sin invitación completa 12 pasos y choca con «solo por invitación» | m1 H1 | M |
| Acceso y marca | Al terminar la marca aterriza en Menciones, no en su primera publicación | m1 H2, `creative_wizard_pages.py:1186` | S |
| Acceso y marca | 12 pasos obligatorios bloquean toda la app (incluido un paso de espera que no se puede saltar) | m1 H3 | L |
| Crear | Aprobar en la revisión deja al dueño sin botón siguiente; «Programar» solo existe en la galería | m3 H1 | S |
| Planificar y publicar | Tres puertas para un trabajo; aprobar no lleva a programar; `/publish` pide volver a subir los archivos | m4 H1, `creative_state.py:5239` | M |
| Planificar y publicar | En el celular la semana abre vacía y «Sin programar» está cerrado | m4 H2, `planner_page.py:1149` | S |
| Responder | No hay un solo lugar con «lo que falta por responder» | m5 H1 | L |
| Responder | «Interacciones» empieza por configurar Reels, no por responder | m5 H2, `inbox_page.py:283` | M |
| Responder | Los comentarios con preguntas o quejas no se pueden responder en público | m5 H3 | M |
| Responder | La prioridad de comentarios depende de que el dueño tenga la pantalla abierta | m5 H6 | L |
| WhatsApp | Chat vencido (24 h): «solo plantillas», pero no hay cómo enviar una desde el chat | m6 #1, `whatsapp_tab_chats.py:785` | M |
| WhatsApp | El menú automático se arma como un diagrama con identificadores | m6 #2 | L |
| WhatsApp | Guardar y publicar el menú son dos acciones lejanas: «ya guardé, ¿por qué no responde?» | m6 #3 | M |
| Resultados | Inicio no dice «cómo me va» ni «qué hago hoy» | m7 H1 | L |
| Resultados | Clarity: el dueño no puede configurarla ni entenderla | m7 H3 | L |

## 4. Orden sugerido (para el backlog)

1. **Arreglos rápidos que destraban** (todos S, sin decisión pendiente): siguiente paso tras aprobar
   (m3 H1), abrir «Sin programar» en el celular (m4 H2), fin de la marca → Inicio/Crear (m1 H2),
   copy que contradice «asistido» (T9), barrido de palabras prohibidas por módulo (T7).
2. **Guía de navegación base** (N1, N3, N5, N7, N8, N10): nombres únicos, `?tab=` en todas las
   pestañas, ningún vacío sin salida, menú sin «pronto» ni demo. Necesita decisión 4 de la guía.
3. **Inicio** (T1) y **Por responder** (T3): los dos hubs que cambian la experiencia. Decisiones 1–3.
4. **Asistentes en pasos** (T8): marca mínima, crear en 4 pasos, programar en día+hora, producto en
   3 pasos, plantilla y menú de WhatsApp guiados.
5. **Celular** (T10) en cada historia que toque una pantalla, no como historia aparte.

## 5. Épica propuesta

**Épica — Qualify en palabras del dueño: navegación y experiencia** (una Feature en Meegle con
historias separadas por dominio). El detalle de cada historia sale de la sección (d) del informe de
cada módulo y de la guía; el `product-owner` la arma y la carga.

| Dominio | Prefijo de historia | Fuente |
|---|---|---|
| Navegación e Inicio (transversal) | `[NAV]` | `ux-guia-navegacion.md`, m7 |
| Acceso y tu marca | `[MARCA]` | m1 |
| Tus productos | `[PRODUCTOS]` | m2 |
| Crear publicación | `[CREAR]` | m3 |
| Aprobar, programar y publicar | `[PUBLICAR]` | m4 |
| Responder a clientes | `[ATENDER]` | m5 |
| WhatsApp | `[WHATSAPP]` | m6 |
| Resultados y menciones | `[RESULTADOS]` | m7 |

## 6. Lo que esta auditoría no sabe (validar)

- Qué palabras usa el dueño de verdad («reel», «historia», «estado», «post»): §5 pregunta 4.
- Si el dueño entra él mismo o lo opera el equipo: §5 pregunta 2. Cambia cuánto pesa el celular.
- Qué mide para decir «valió la pena»: §5 pregunta 7. Cambia qué muestra Inicio y Resultados.
- Prueba en vivo a 360 px de cada ruta (este informe se hizo leyendo código).
