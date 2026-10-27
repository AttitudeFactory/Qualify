# Épica — Moverse dentro de cada módulo: volver, saber el paso y seguir siempre a la vista

`[v2 · 2026-10-27 · seguimiento de entrega]` · **Meegle:** Feature [m-24852238](https://project.larksuite.com/5h2wsx/story/detail/24852238) con 13 historias (Issues) enlazadas por el campo Feature. Se crearon en Backlog con Reporter y Assignee (Herwin); el estado de entrega actualizado está en §6.

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

## 4. Decisiones del fundador (2026-10-25)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | ¿Se aprueba el marco de paso a paso (PASOS-1)? | **Sí, tal cual.** Arriba fijo: «‹ destino», «Paso N de M» y la barra de avance. Abajo fijo: «Atrás» y «Siguiente»; en el celular el pie **ocupa el lugar** de la barra de accesos mientras dura el asistente. Quedan desbloqueadas PASOS-2 en adelante. |
| 2 | ¿Adónde lleva «Seguir después» en Crear y en Publicar ahora? | **A Inicio** en todos los asistentes (N2), igual que en Tu marca. Inicio muestra lo que quedó a medias con «Seguir». |
| 3 | ¿En qué equipo se mide el spike de Motion (PASOS-12)? | **En Chrome con la CPU limitada 6×.** Si el resultado sale justo, se confirma después en un Android real. |

## 5. Fuera de esta épica

- Cambiar qué se pide en cada paso: ya lo decidieron MARCA-4 (m-24848529), CREAR-2 (m-24848530), PUBLICAR-4 (m-24842986), WHATSAPP-4 (m-24848536) y ATENDER-6 (m-24842991).
- Guardar borradores en la base de datos: los borradores siguen en el estado de la sesión, como hoy el mensaje aprobado de WhatsApp.
- Gestos (deslizar para descartar) y cualquier otro uso de Motion.

## 6. Entrega y continuación — 2026-10-27

El traspaso [m-24861081](https://project.larksuite.com/5h2wsx/issue/detail/24861081) recuperó el WIP de Crear publicación y continuó las historias restantes. La navegación restaura pasos y fichas mediante direcciones propias; las acciones permanecen visibles en los recorridos y cajones. Los borradores siguen siendo de la sesión y las publicaciones y mensajes conservan su aprobación explícita.

| Historia | Entrega | Estado |
|---|---|---|
| PASOS-1 · m-24852240 | [PR #330](https://github.com/AttitudeFactory/Qualify/pull/330) | Entrega previa |
| PASOS-2 · m-24852241 | [PR #359](https://github.com/AttitudeFactory/Qualify/pull/359) | Entrega previa |
| PASOS-3 · m-24852246 | [PR #386](https://github.com/AttitudeFactory/Qualify/pull/386) | Integrado |
| PASOS-4 · m-24852243 | [PR #363](https://github.com/AttitudeFactory/Qualify/pull/363) | Entrega previa |
| PASOS-5 · m-24852244 | [PR #383](https://github.com/AttitudeFactory/Qualify/pull/383) | Integrado; WIP terminado |
| PASOS-6 · m-24852245 | [PR #384](https://github.com/AttitudeFactory/Qualify/pull/384) | Integrado |
| PASOS-7 · m-24852247 | [PR #391](https://github.com/AttitudeFactory/Qualify/pull/391) | Integrado; Meegle: Done |
| PASOS-8 · m-24852249 | [PR #392](https://github.com/AttitudeFactory/Qualify/pull/392) | Integrado; Meegle: Done |
| PASOS-9 · m-24852250 | [PR #393](https://github.com/AttitudeFactory/Qualify/pull/393) | Integrado; Meegle: Done |
| PASOS-10 · m-24852251 | [PR #394](https://github.com/AttitudeFactory/Qualify/pull/394) | Integrado; Meegle: Done |
| PASOS-11 · m-24852252 | [PR #397](https://github.com/AttitudeFactory/Qualify/pull/397) | Integrado; Meegle: Done |
| PASOS-12 · m-24852253 | [PR #390](https://github.com/AttitudeFactory/Qualify/pull/390) | Informe integrado; decisión de adopción pendiente del fundador |
| PASOS-13 · m-24852260 | [PR #347](https://github.com/AttitudeFactory/Qualify/pull/347) | Entrega previa |

Los estados Done de PASOS-7…11 se verificaron en Meegle el 2026-10-27. PASOS-12 no se marca Done: su informe está integrado y la decisión de adopción sigue pendiente del fundador.

Se conservó el arreglo previo de salida de ficha e icono de Oportunidades, [PR #355](https://github.com/AttitudeFactory/Qualify/pull/355).

**Validación registrada.** El conjunto PASOS-7…11, integrado con la navegación y el main de referencia, pasó 9.767 pruebas offline. Cada PR conserva sus pruebas focales y CI propio antes de la integración. La revisión local a 360 px comprobó recorridos, contadores, acciones, borradores y alturas de encabezados; Marca se comprobó también con CPU 6×. Los informes y capturas están en los README de [PASOS-5](../testing/evidence/m-24852244/README.md), [PASOS-6](../testing/evidence/m-24852245/README.md), [PASOS-3](../testing/evidence/m-24852246/README.md), [PASOS-7](../testing/evidence/m-24852247/README.md), [PASOS-8](../testing/evidence/m-24852249/README.md), [PASOS-9](../testing/evidence/m-24852250/README.md) y [PASOS-10](../testing/evidence/m-24852251/README.md). La [evidencia de PASOS-11](../testing/evidence/m-24852252/README.md) también está integrada con el PR #397. Cada README precisa el alcance y la versión.

La última corrección del movimiento del menú se comprobó con el callback generado real y el CSS del producto en Chromium con DOM aislado: 380 ms, entrada según dirección, archivo y nodos conservados, y movimiento reducido. La base compartida local carecía de una columna reciente de conexiones (`reconnect_reason`); se mantuvo intacta. Los recorridos funcionales se habían comprobado en la app; esto no equivale a otra pasada funcional del menú sobre la última base. PASOS-11 pasó 208 pruebas focales, lint y render tras su integración local; su CI en el PR #397 terminó en verde antes de integrarse. Los datos sintéticos se restauraron o desactivaron y el entorno de autenticación de pruebas se conservó sin copiar credenciales a la entrega.

**Destino del arrastre.**

- Paso anterior visible durante la carga de Marca: corregido en PASOS-3, ocultando contador y barra hasta resolver el paso.
- Título `h1` y propiedades del título de `drawer()` enviadas a CSS: corregidos en PASOS-7.
- Texto de fondo visible a través de Más móvil y primarios desactivados que parecían activos: corregidos e integrados en PASOS-11 (PR #397) con los materiales y estados existentes.

**Motion.** La comparación está en §4.1 de [la revisión de navegación](ux-navegacion-pasos-2026-10-24.md). Añade 50,34 KiB gzip a la app y no mostró una mejora de fluidez en el fixture con CPU 6×. La recomendación es conservar CSS. El prototipo y las muestras permanecen en la rama `spike/m-24852253-motion-cards`; esa dependencia no se incorpora a producción. La decisión del fundador sigue pendiente en PASOS-12.
