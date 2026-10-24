# Épica — Moverse dentro de cada módulo: volver, saber el paso y seguir siempre a la vista

`[v1 · 2026-10-24 · product-owner]` · **Meegle:** Feature [m-24852238](https://project.larksuite.com/5h2wsx/story/detail/24852238) con 13 historias (Issues) enlazadas por el campo Feature; todas en Backlog, con Reporter y Assignee (Herwin) para que el equipo pueda moverlas.

**Origen:** pedido del fundador (2026-10-24): «la navegación interna de cada módulo, ir atrás (no existen) (debería ser fixed en mi opinión); saber en qué paso estamos; y las opciones de continuar ocultas abajo del todo (debería ser fixed en mi opinión). Lanza una revisión exhaustiva, créame una épica para este UX improvement y evalúa agregar un poco de Framer para las transiciones o carga de cards».

**Evidencia:** revisión del agente `ux-designer` por lectura de código, sin prueba en el navegador: [`ux-navegacion-pasos-2026-10-24.md`](ux-navegacion-pasos-2026-10-24.md) — §2 hallazgos H1–H8 con archivo:línea, §3 el «marco de paso a paso» con maquetas y las seis reglas (§3.4, futura N6b), §4 la tabla de opciones de movimiento (CSS / View Transitions / Motion), §5 las historias. Lo marcado «probable» o *hipótesis* falta medirlo en un celular. Persona: [`perfil-cliente-pyme.md`](perfil-cliente-pyme.md). Reglas: [`ux-guia-navegacion.md`](ux-guia-navegacion.md) N5, N6, N7, N12.

**Relación con la épica anterior** ([`epica-ux-navegacion-experiencia.md`](epica-ux-navegacion-experiencia.md), Feature m-24842956): esa épica fijó la regla N6, pero cada asistente la construyó a su manera y ninguno la fijó en pantalla. **NAV-2 (m-24842960) ya está en Done**: dio dirección a las pestañas (`?tab=`). Su resto (pasos y fichas) lo absorbe PASOS-3 (m-24852246). NAV-2 no se reabrió ni se cerró de nuevo: lleva un comentario que apunta a PASOS-3, y PASOS-3 lo nombra en su texto. Meegle no deja poner un Issue cerrado en «Relacionado con», así que el vínculo quedó en el comentario y en el texto.

**Restricciones firmadas que respetan todas las historias:** asistido, nunca autónomo: nada se publica ni se envía sin un toque del dueño, y cerrar o reabrir un cajón nunca envía nada. Además: ningún componente, color ni superficie de vidrio nuevos fuera del marco aprobado en PASOS-1, ni dependencias nuevas de npm sin la decisión del fundador (PASOS-12), y una sola Postgres (esta épica no toca el esquema).

**Toda historia de código incluye además** estos criterios: revisión local de experiencia (`ux-designer`, `qualify-ux` §6) antes de abrir el PR; prueba a 360 px en el navegador de cada ruta tocada, con captura en el PR (N12); `just ci-lint` y `just ci-test` en verde.

## 1. Lista de historias

| Ticket | ID | Historia | Prioridad | Tamaño | Arregla | Área | Bloqueada por |
|---|---|---|---|---|---|---|---|
| [m-24852240](https://project.larksuite.com/5h2wsx/issue/detail/24852240) | `PASOS-1` | Diseño: documentar el «marco de paso a paso» y la regla N6b antes del código | P0 | S | todas | ux-designer + aprobación del fundador | — |
| [m-24852241](https://project.larksuite.com/5h2wsx/issue/detail/24852241) | `PASOS-2` | Diseño: construir el marco en `Qualify/ui` (cabeza y pie fijos, vuelta arriba) | P0 | M | H2, H3, H5 | reflex-ui-engineer | PASOS-1 |
| [m-24852246](https://project.larksuite.com/5h2wsx/issue/detail/24852246) | `PASOS-3` | Navegación: el «atrás» del celular retrocede un paso y nunca saca del módulo (`?paso=`). **Absorbe NAV-2 (m-24842960)** | P1 | M | H4 | reflex-ui-engineer | — (en paralelo a PASOS-2) |
| [m-24852243](https://project.larksuite.com/5h2wsx/issue/detail/24852243) | `PASOS-4` | Tu marca: siempre puedo salir, «Seguir después» me lleva a Inicio y el contador dice la verdad | P0 | M | H1, H2, H5 | reflex-ui-engineer | PASOS-2 |
| [m-24852244](https://project.larksuite.com/5h2wsx/issue/detail/24852244) | `PASOS-5` | Crear publicación: «Siguiente» siempre a la vista, el paso arriba y nada de «no tienes productos» mientras carga | P0 | M | H2, H3, H5, H8 | reflex-ui-engineer | PASOS-2 |
| [m-24852245](https://project.larksuite.com/5h2wsx/issue/detail/24852245) | `PASOS-6` | Publicar ahora: los 3 pasos en el marco, «Siguiente» visible aunque suba muchas fotos | P1 | S | H2 | reflex-ui-engineer | PASOS-2 |
| [m-24852247](https://project.larksuite.com/5h2wsx/issue/detail/24852247) | `PASOS-7` | Cajones con pasos: el paso en la cabeza, contador que coincide y cerrar la promoción no borra nada | P1 | M | H5, H7 | reflex-ui-engineer | PASOS-2 |
| [m-24852249](https://project.larksuite.com/5h2wsx/issue/detail/24852249) | `PASOS-8` | WhatsApp: menú automático en el marco, con el paso arriba de todo | P1 | S | H2, H3, H5 | reflex-ui-engineer | PASOS-2 |
| [m-24852250](https://project.larksuite.com/5h2wsx/issue/detail/24852250) | `PASOS-9` | Quieren comprar: «Paso N de 3» y acciones a la vista; el título de la siguiente consulta no queda tapado | P2 | S | H2, H8 | reflex-ui-engineer | PASOS-2 |
| [m-24852251](https://project.larksuite.com/5h2wsx/issue/detail/24852251) | `PASOS-10` | Navegación: «Volver» dice a dónde, nunca se desplaza y aparece también cuando falla la carga | P1 | S | H6, H8 | reflex-ui-engineer | PASOS-2 |
| [m-24852252](https://project.larksuite.com/5h2wsx/issue/detail/24852252) | `PASOS-11` | Movimiento: el paso entra según la dirección y las tarjetas fantasma se funden, con el CSS que ya existe | P1 | S | H8 | reflex-ui-engineer | PASOS-2 |
| [m-24852253](https://project.larksuite.com/5h2wsx/issue/detail/24852253) | `PASOS-12` | Spike: Motion solo para la salida de tarjetas en Por aprobar, medido en un Android de gama baja (máx. 1 día). **Sin merge de dependencia sin la decisión del fundador** | P2 | S | — | data-scientist-fde o reflex-ui-engineer | — (independiente) |
| [m-24852260](https://project.larksuite.com/5h2wsx/issue/detail/24852260) | `PASOS-13` | Navegación: el menú siempre muestra en qué módulo estás (un solo ayudante de ruta actual, subpantallas, cápsula de vidrio que se recoloca). Causa confirmada: el menú compara `router.page.path`, que en «/» vale "/index", así que «Inicio» nunca se enciende | P0 | S | H9 | reflex-ui-engineer | — (arreglo, puede ir ya) |

En Meegle, las dependencias van en el campo «Bloqueado por»: PASOS-2 → PASOS-1 y PASOS-4…PASOS-11 → PASOS-2.

## 2. Orden

1. **PASOS-1** (m-24852240): el fundador aprueba la sección del marco en `docs/design-system.md` y la regla N6b **antes** de cualquier código.
   **PASOS-13** (m-24852260) va ya, sin esperar: es un arreglo (H9, reportado por el fundador el 2026-10-24) en `ui/layout.py` y `assets/glass-nav.js`.
2. **PASOS-2** (m-24852241): el marco en `Qualify/ui/`. **En paralelo, PASOS-3** (m-24852246) (`?paso=` y fichas con dirección), que no depende del aspecto del marco.
3. **PASOS-4** (m-24852243) y **PASOS-5** (m-24852244): el recorrido principal (marca y primera publicación), en ramas separadas.
4. El resto, sin dependencia entre sí: PASOS-7 (m-24852247), PASOS-10 (m-24852251), PASOS-11 (m-24852252), PASOS-6 (m-24852245), PASOS-8 (m-24852249), y al final PASOS-9 (m-24852250), que es P2.
5. **PASOS-12** (m-24852253) es independiente y puede correr cuando haya hueco. Termina con una tabla y la decisión del fundador, no con una dependencia en `main`.

**Choque de archivos a vigilar:** PASOS-4 y PASOS-5 tocan los dos `creative_wizard_pages.py`. PASOS-3 toca los estados de todos los asistentes (`?paso=`). Si van al mismo tiempo, PASOS-3 entra primero o se rebasa sobre la otra.

## 3. Movimiento: qué se decidió y qué queda para el fundador

Viene de la §4 de la revisión: **A (ampliar el CSS que ya existe) entra en la épica** como PASOS-11, sin costo ni dependencia. **C (Motion, antes Framer Motion)** queda solo como spike acotado (PASOS-12) para la salida de tarjetas. **B (View Transitions)** se descarta por ahora. Si el spike dice sí, la integración es una historia nueva que se carga después de la decisión.

## 4. Preguntas abiertas para el fundador

1. **Aprobar el marco (PASOS-1).** Sin esa aprobación no arranca ninguna historia de código salvo PASOS-3, PASOS-12 y PASOS-13.
2. **¿Hay un Android de gama baja para el spike?** Si no hay, PASOS-12 mide en Chrome con la CPU limitada 6× y lo dice en la tabla. Qué celulares usan los clientes es *hipótesis* (perfil §5 pregunta 3).
3. **«Seguir después» lleva a Inicio (N2).** Así lo dice la revisión, y lo aplica PASOS-4. Confirmar que también vale para Crear y Publicar ahora o si allí debe volver a «‹ Tus publicaciones».

## 5. Fuera de esta épica

- Cambiar qué se pide en cada paso: ya lo decidieron MARCA-4 (m-24848529), CREAR-2 (m-24848530), PUBLICAR-4 (m-24842986), WHATSAPP-4 (m-24848536) y ATENDER-6 (m-24842991).
- Guardar borradores en la base de datos: los borradores siguen en el estado de la sesión, como hoy el mensaje aprobado de WhatsApp.
- Gestos (deslizar para descartar) y cualquier otro uso de Motion.
