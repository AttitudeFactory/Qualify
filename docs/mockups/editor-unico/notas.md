# Editor único — notas de diseño para firmar (m-25026602)

`[PROPUESTO]` · ux-designer, 2026-11-26 · para Deivid.
Base: `docs/plan-editor-unico-clip-partes.md` (principal-architect, aprobado por Deivid el
2026-11-26), §2, §2.1 y §3; tickets ED-07 (m-25026638), ED-08 (m-25026640) y ED-06 (m-25026636).
Mockups: `index.html` en esta carpeta (se abre con doble clic, sin servidor).

> **Qué no se pudo comprobar.** Por instrucción, no abrí el navegador. Los mockups no se miraron
> renderizados: solo validé con `node` que el script y las especificaciones de cada pista
> funcionan sin errores. Antes de firmar, conviene abrir `index.html` y mirar cada pantalla en
> los dos anchos. Si algo se ve roto, es un error del dibujo, no una decisión de diseño.

## 1. Decisiones de diseño

| # | Decisión | Por qué |
|---|---|---|
| D1 | La parte con IA es **un bloque más de «Fotos y videos»**. En pantalla se llama **«Parte con IA n»**, con su propia cuenta, como hoy «Foto n» y «Video n». La palabra «bloque» no aparece en ningún texto de pantalla. | Es el nombre de «Agregar → Parte con IA». El dueño reconoce lo que agregó. |
| D2 | **Aspecto propio, nunca solo color:** tono iris, el ícono ✦ y la insignia del modo en la primera línea. Debajo, antes de crear, el nombre y los segundos; después, el estado con su palabra (`signal_pill` en chico). | P1 del sistema: el estado y el tipo se leen sin color. Se distingue del video propio (lavado del acento), de la foto (gris) y del efecto (punteado del acento). |
| D3 | **Sin crear = borde punteado + póster atenuado.** Creada = borde lleno y el cuadro de su propio video (tira de cuadros de ED-11b cuando exista). | Que se vea de un vistazo qué falta crear y qué ya se pagó, sin un cartel encima de cada parte. |
| D4 | **Insignia corta:** «Nueva» (cubre «Nueva, inspirada en el original», «Nueva, con tu producto» y «Nueva, con tu marca»), «Igual al original» y «Sigue a la anterior». El nombre completo va en el panel. Por debajo de ~120 px (una parte de 2 s en el celular) quedan solo los íconos y el nombre completo va en `aria-label`. | «Nueva, inspirada en el original» no cabe en una parte de 5 s a 375 px (220 px). |
| D5 | **El modo es una etiqueta (categoría) y el estado es una píldora con punto (señal).** | Tabla «¿qué badge?» de §5.3: categoría → `tag`, estado → `signal_pill`. |
| D6 | **Panel antes de crear, en este orden:** la caja «Todo el video» (plegada a una línea), «¿Qué pasa en esta parte?», «Fotos de tu producto», «Cuánto dura en tu video» y «¿Cómo la hacemos?» con su motivo. En escritorio van dos columnas: lo que se ve a la izquierda y cómo la hacemos a la derecha. Termina en «Listo». | Primero lo que el dueño sabe contar (qué se ve); el modo ya viene elegido por la regla con su motivo, así que suele quedar como está. |
| D7 | **Motivo del modo:** la línea `MODE_REASON_TEXTS` va debajo de la pregunta, con el ícono «i». Si el dueño lo cambió, la misma línea dice **«Lo cambiaste tú.»** (ícono lápiz), con **«Volver a lo que te propusimos»** al lado. | Un solo lugar para el porqué. La salida de vuelta es una hipótesis: quien cambió por error no recuerda cuál era. Se valida con la pregunta 6 del perfil §5. |
| D8 | **Opción que no se puede elegir:** se queda enfocable (`aria-disabled`), punteada y gris, con su razón en ámbar dentro de la tarjeta (los textos de `part_editor_vm`). | La misma regla que `q-button-off`: el lector de pantalla llega al motivo. |
| D9 | **Segundos antes de crear: enteros de 1 a 10** («− 1 s / + 1 s» y tiradores con imán de 1 s). Con menos de 4 s se avisa: «Se crea de 4 s y usa 4 s de tu mes. Cuando esté lista, eliges qué {n} s usar arrastrando sus barras.» **Después de crear**, los tiradores recortan dentro del video hecho, con imán de ½ s y gratis (`trim_start_s`/`trim_end_s`). | `VideoPartPlan.seconds` es entero (1–10). Es la única excepción al «imán de ½ s siempre» de §5.10 (pregunta 5). |
| D10 | **«Agregar → Parte con IA»** la pone ya en la pista, en el cabezal, con 5 s (o lo que quepa hasta 60 s), la foto del producto elegido y el modo que dé la regla. Abre su panel con el foco en «¿Qué pasa en esta parte?». «Siguiente» espera hasta que la parte tenga descripción («Falta contar qué pasa en la parte con IA 1.»). | Un toque menos y no hay dos formularios (pestaña y panel) para lo mismo. Rompe la regla de hoy de que una opción de «Agregar» nunca pone nada sola (pregunta 1). |
| D11 | **«Probar esta parte»** en lugar de «Probar este bloque» (el texto del ticket). Va en el panel de la parte, con la línea de costo pegada y **sin diálogo**: «Usa 1 vista previa. Te quedan {n}. Las demás las creas con «Crear».». Después, la parte queda «En fila» o «Creando» y el dueño sigue armando. | «Bloque» no es palabra del dueño. La misma familia de hoy: «Probar solo la parte 1» y «Rehacer esta parte» (pregunta 7). |
| D12 | **«Revisa y crea» separa los dos gastos y dice cuándo pasa cada uno:** «Ahora, al crear: 2 vistas previas, una por cada parte con IA…» y «Después, al aprobar: 9 s de video, solo los de las partes con IA (la de 3 s cuenta como 4)…». La línea corta se repite junto a «Crear». | La confusión más probable es entre vistas previas y segundos. Que los bloques propios no gastan es un beneficio, y se dice. |
| D13 | **Sin vistas previas:** «Crear» queda apagado con su motivo. La salida gratis se dice: «Si lo quieres hoy, quita las 2 partes con IA: con tus fotos y tu video se crea gratis.» | Nunca un callejón sin salida (N13). |
| D14 | **Resultado en la página del video** (`/drafts/<id>`, se enciende «Por aprobar»), con el mismo editor. Cabeza: «‹ Por aprobar»; h1: «Tu video». Sin «Paso N de M». | La pieza ya existe: tiene su dirección, se puede salir y volver (N3, N6). Pregunta 3. |
| D15 | **Progreso:** el estado va sobre cada parte en la pista. Lo que necesita una decisión («No salió», «No se pudo con el original», «Hay que rehacerla», «Venció») baja a una tarjeta a lo ancho debajo de la pista, con el motivo y los botones de hoy («Intentar de nuevo», «Hacerla nueva», «Quitar parte»). Arriba va la línea «Creando tus partes: van 1 de 4» con su barra. | En una parte de 4 s (176 px) no caben un motivo ni dos botones de 44 px. |
| D16 | **Las palabras de `part_progress_vm`/`part_review_vm` se reusan cambiando «la parte n» por «la parte con IA n»** («La parte con IA 1 está para revisar.»). | En el editor único, «parte 3» ya no es la tercera de la pista. |
| D17 | **Panel de una parte creada:** su video en su cuadro (`clip_player`), «Versión 2 de 2» con «Ver la anterior», «Se hizo con: «…»» y **«Me gusta así»** (botón principal del panel). «Rehacer esta parte» queda plegado. Abierto, muestra descripción, fotos, la forma («Cambiar la forma también crea una versión nueva.»), «Usa 1 vista previa. Te quedan {n}.» y «Crear otra versión». Recortar, mover, quitar, uniones, textos y capas son gratis y se hacen en la pista. | Una decisión a la vez: lo gratis (mirar, marcar, recortar) va primero y lo que cuesta va plegado. |
| D18 | **Aprobar = un diálogo** («¿Aprobamos tu video?») con la duración, los segundos que usa (solo las partes con IA), lo que queda y lo que viene después. Botón: **«Aprobar y usar 17 s»** / «Todavía no». Antes de abrirlo, el pie ya dice el total. | Gastar segundos no se deshace (§5.4: `rx.alert_dialog`). Nunca dice «publicar»: aprobar deja el video listo para programar. |
| D19 | **Espera de los finales:** `progress_panel` («Pidiendo tus partes en alta calidad: van 2 de 4» encima de la barra) y la lista de partes con su estado. «Puedes salir de aquí: te avisamos en Inicio cuando esté listo.» Al terminar: «Tu video está listo…», «Programar» (principal) y «Descargar». | Hipótesis: el dueño no se queda mirando (perfil §5, pregunta 3). Pregunta 6 sobre si se puede cambiar mientras tanto. |
| D20 | **«Hacer uno parecido»:** la tarjeta «Video de inspiración» va arriba, en una sola fila (miniatura, «Basado en un reel de @…», «Ir al video ↗»). Debajo, el editor ya armado y la línea viva «Te armamos tu video como el reel: 3 partes con IA y 2 tuyas. Revisa cada una; hasta «Crear» no gastas nada.». Cada parte del reel se puede mirar en su cuadro, en el panel. | La vista previa necesita alto en el celular. La comparación con el original va donde se decide. |
| D21 | **Contexto general (ED-06):** con nada elegido, una fila junto a la vista previa: «Tu video trata de: «…» · Cambiar» o, vacía, «Cuenta de qué trata tu video: guía el texto. · Escribir». En el panel de una parte con IA va la caja «Todo el video» con la regla, en una frase: «Esto guía el texto y el tono de todo el video. Lo que escribas abajo dice qué se ve en esta parte.». | Lo general se escribe una vez y se recuerda donde importa. |
| D22 | **Topes, antes del choque:** la opción de «Agregar» queda apagada (como «Foto o video» con 8 hoy, ED-12) y su motivo va encima del «+». Textos en `03-agregar.html` §D. «Pedir una idea» no se dibuja si no cabe ninguna parte (regla 5 del orbit). | §5.10: «Límites dichos antes del choque». |

**Accesibilidad y celular (todas las pantallas).**
- Ningún desplazamiento lateral a 375 px. La pista se desliza dentro de su caja, como hoy.
- Todos los toques miden 44 px o más.
- El nombre accesible de una parte con IA dice todo: «Parte con IA 1, Nueva, de 0:06 a 0:11, sin crear».
- Una sola línea viva `role="status"`. Las decisiones están en tarjetas con encabezado.
- Teclado igual que §5.10: Enter elige y lleva al panel; Escape lo cierra; ←/→ cambian de lugar.

**Palabras.** Todas salen de `part_editor_vm`, `reel_parts_vm`, `mode_choice.MODE_REASON_TEXTS`,
`parts.NOTICE_TEXTS`, `part_progress_vm`, `part_review_vm`, `parts_start_vm`, `clip_editor_vm` y
`clip_joins_vm`. Las únicas **nuevas** son estas (para revisar con `qualify-copy-es`):

- «Parte con IA n»
- «Sin crear · gratis hasta «Crear»»
- «Cuánto dura en tu video»
- «Lo cambiaste tú.» / «Volver a lo que te propusimos» (el primero ya estaba en el ticket)
- «Probar esta parte»
- la línea de las partes de menos de 4 s
- los textos de los topes de 6 partes y de 60 s
- «Solo se juntan dos partes con IA seguidas.»
- «Ahora, al crear» / «Después, al aprobar»
- «¿Aprobamos tu video?» / «Aprobar y usar {n} s» / «Todavía no»
- «Pidiendo tus partes en alta calidad: van {k} de {n}» / «Preparando tu video final»
- «Te armamos tu video como el reel…»

## 2. Patrón nuevo para firmar en `docs/design-system.md`: el bloque IA

Va como una subsección de §5.10 («Línea de tiempo»). No crea componentes nuevos: es una variante
de `.q-tl__block` en la pista «Fotos y videos».

**Anatomía** (56 px de alto, la altura de la pista de medios):

```
┌──────────────────────────────┐   borde: punteado 2 px (sin crear) · lleno 1 px (creada)
│ (✦ ↳ Sigue a la anterior)    │   línea 1: insignia del modo (etiqueta)
│ [Parte con IA 2 · 3 s]       │   línea 2: nombre y segundos (sin crear) · o estado (creada)
└──────────────────────────────┘   fondo: póster (reel o producto) atenuado · o su propio cuadro
```

**Clases** (todas sobre lo que ya existe en `assets/qualify-creative.css`):

| Clase / atributo | Qué es |
|---|---|
| `.q-tl__block[data-tl-block="ai"]` | El bloque IA. Columna de dos líneas; borde `--iris-a7`, fondo `--iris-a4`, texto `--iris-12`. |
| `[data-ai-state="plan\|queued\|creating\|review\|ready\|failed\|refused\|redo\|expired"]` | El estado: los mismos de `PartState` más `plan` (sin crear). |
| `.q-tl__mode` | La insignia del modo: ✦ + ícono del modo + palabra (`.q-tl__mode-word`). Píldora oscura con borde `--iris-a7`. |
| `.q-tl__state` | El estado sobre el bloque: punto o cargador + palabra (`.q-tl__state-word`) en el tono de `STATE_TONES`, sobre `--black-a8`. |
| `.q-tl__pic` (sin cambio) | El póster antes de crear (atenuado: `opacity .45`, `saturate(.4)`) y el cuadro de la parte después. Velo iris para que se lean las letras. |
| `@container q-tl-block (max-width: 120px)` | Bloque angosto: se ocultan la palabra del modo y los segundos. Con 70 px o menos se oculta también la palabra del estado (queda en `aria-label`). |
| `.ai-mark` | La misma insignia sobre la vista previa mientras el cabezal está en una parte con IA sin crear: «✦ Parte con IA 1 · se crea al tocar «Crear»». |

**Tokens.** Ningún color nuevo en el sentido de §9.2. Se usa la escala **iris de Radix**, que el
sistema ya carga y usa para el lavado de zona del sidebar (§3.1, `iris-a3`). Lo nuevo es el
**rol**: «hecho con IA». Pasos:

- `iris-a4`: fondo;
- `iris-a7`: borde e insignia;
- `iris-a8`: borde punteado sin crear;
- `iris-12`: texto (≥ 4.5:1 sobre `iris-a4` en oscuro);
- `iris-11`: el ícono «i» del motivo.

Los estados usan los tonos de siempre:

- `info`: Creando;
- `ok`: Lista;
- `warn`: Para revisar, No se pudo con el original, Hay que rehacerla y Venció;
- `error`: No salió;
- `neutral`: En fila.

Una parte en error lleva borde de 2 px `tomato-9`; una en aviso, `amber-9`. La elegida lleva, como
cualquier bloque, borde de 2 px `accent-9`.

**Estados.**

| Estado | Borde | Fondo | Línea 2 | Tiradores |
|---|---|---|---|---|
| `plan` (sin crear) | punteado 2 px `iris-a8` | póster atenuado | «Parte con IA n · 5 s» | segundos, de 1 en 1 s (1–10) |
| `queued` / `creating` | 1 px `iris-a7` | póster atenuado | «En fila» (reloj) / «Creando» (cargador `sm`) | no (se está haciendo) |
| `review` / `ready` | 1 px `iris-a7` | su cuadro | «Para revisar» / «✓ Lista» | recorte dentro del video hecho, ½ s, gratis |
| `failed` | 2 px `tomato-9` | póster | «No salió» | no |
| `refused` / `redo` / `expired` | 2 px `amber-9` | póster o su cuadro | su palabra | no |

**Reglas.**

1. Una parte con IA va siempre a ×1: en su panel no hay «Velocidad», «Girar» ni «Cortar».
2. Las uniones, los textos y las capas funcionan igual a su lado y encima.
3. Nunca se dibuja solo el color: siempre ✦ + insignia + palabra.
4. En el celular la insignia se acorta a íconos. El nombre completo siempre está en `aria-label` y en el panel.
5. La insignia del modo es una categoría (`tag`). El estado es una señal (`signal_pill`).
6. **Excepción al imán de ½ s:** antes de crear, los tiradores de una parte con IA cambian sus segundos de 1 en 1 s.

**Panel** (`.q-tl-panel`, sin cambios). Lo nuevo es su contenido:

- la caja «Todo el video» (`.whole`, material control);
- «¿Cómo la hacemos?» como `choice_card` con `role="radio"`;
- la línea del motivo (`.why-line`);
- la línea de costo (`.cost`) pegada a cada botón que gasta.

**Lo que NO hace.**

- No muestra el modo con colores distintos por modo: el ícono y la palabra bastan.
- No pone botones sobre la parte en la pista: las acciones van en el panel o en la tarjeta de decisiones.

## 3. Preguntas para Deivid (de a una; cada una con su recomendación)

**P1 · «Agregar → Parte con IA»: ¿la pone ya o abre el panel lateral?**

- **A · La pone ya** en el cabezal y abre su panel con el foco en «¿Qué pasa en esta parte?».
  Es gratis y se quita con «Quitar».
- B · Abre la pestaña «Parte con IA» del panel lateral, y se pone con un botón «Ponerla en tu video».

**Recomiendo A.** Es un toque menos y evita tener dos formularios para lo mismo. Es una excepción
firmada a la regla 4 del orbit y a §5.10-8 («nunca agrega sola»). El ticket ya lo dice así
(«agrega un bloque IA vacío»).

**P2 · «Pedir una idea» con la pista ya armada: ¿qué pasa con lo que había?**

- **A · Agrega las partes propuestas al final**, hasta los topes, y la línea viva dice cuántas cupieron.
- B · Reemplaza todo, con confirmación. No hay «Deshacer» (D-E6), así que se perdería trabajo.
- C · Solo se ofrece con la pista vacía.

**Recomiendo A.** Nunca borra nada y sigue siendo gratis.

**P3 · ¿Dónde vive el resultado (progreso, rehacer, aprobar)?**

- **A · En la página del video** (`/drafts/<id>`, «Por aprobar»), con el mismo editor y sin «Paso N de M».
- B · Sigue en el generador, en el paso 1, con la pista en modo resultado.

**Recomiendo A.** Tiene su dirección, se puede salir y volver, y el menú se enciende bien (N3, N6).
B deja una pieza ya creada colgando dentro de un asistente.

**P4 · Color del bloque IA**

- **A · Escala iris**, que ya está en el sistema, con el rol nuevo «hecho con IA».
- B · Sin escala nueva: gris con borde de acento y ✦. Se confunde con el video propio, que usa el
  lavado del acento.

**Recomiendo A.** Se distingue de un vistazo y no agrega una escala que no se cargue hoy.

**P5 · Segundos de una parte con IA antes de crear**

- **A · Enteros de 1 a 10**, con «± 1 s» y un imán de 1 s.
- B · De ½ en ½ s, como todo, redondeando al crear.

**Recomiendo A.** Es lo que se pide de verdad (`seconds: int`). Con B el dueño ve 4,5 s y se crea otra cosa.

**P6 · Mientras se preparan los finales de 1080p, ¿se puede seguir cambiando el video?**

- **A · No:** queda quieto hasta que esté listo («Mientras se prepara, tu video no se puede cambiar.»).
- B · Sí, y se vuelve a juntar después.

**Recomiendo A.** Lo aprobado es lo que se paga, y B suma armados que cuentan en el tope de 10 al día.

**P7 · ¿«Probar esta parte» o «Probar este bloque»?**

- **A · «Probar esta parte».**
- B · «Probar este bloque», como dice el ticket.

**Recomiendo A.** «Bloque» no es una palabra del dueño, y la familia de hoy es «Probar solo la
parte 1» y «Rehacer esta parte».

**P8 · Insignia del modo en la pista**

- **A · La palabra corta** («Nueva», «Igual al original», «Sigue a la anterior») en la pista y el
  nombre completo en el panel.
- B · El nombre completo de hoy («Nueva, inspirada en el original»), que no cabe a 375 px.

**Recomiendo A.**

**P9 · «Video o audio tuyo» de la hoja de la parte (base propia para «Tu video, con tu marca»): ¿dónde queda?**

- **A · Dentro del panel de la parte con IA**, en «Más opciones».
- B · Se retira: el video propio va como bloque propio y la IA no lo usa como base.

**Recomiendo A**, para no perder nada (la regla de Deivid). El plan §2.1 no lo nombra: hay que
confirmarlo con principal-architect.

## 4. Qué necesita `reflex-ui-engineer` (PR 6–8)

- **Línea de tiempo:** en `ui/timeline_vm.py`, `kind="ai"` con `mode`, `state` y `poster` en la fila
  del bloque. En `ui/timeline.py`, las dos líneas del bloque IA. En `qualify-creative.css`, el
  bloque de clases de §2 (en `editor-unico.css` están listas para copiar, marcadas «NUEVO»).
- **Panel:** `ai_part_panel` en `clip_editor_view.py`, con las palabras de `part_editor_vm`.
- **Agregar:** `ADD_OPTIONS` suma `("ai_part", "sparkles", "Parte con IA")` detrás de
  `QUALIFY_CLIP_AI_PARTS`, con su motivo de tope en `described_by`.
- **Resultado:** la página del video monta el mismo editor en modo resultado (según P3), con la
  tarjeta de decisiones y la línea «Creando tus partes: van k de n».
- **Aprobar:** un `rx.alert_dialog` con `seconds_line` adaptada: solo cuentan las partes con IA.
- **Antes del PR:** revisión de ux-designer en el navegador a 375 px y en escritorio, como siempre.
