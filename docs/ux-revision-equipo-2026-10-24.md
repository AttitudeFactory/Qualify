# Revisión de experiencia del trabajo del equipo — 2026-10-24

> Revisión local de `ux-designer`, **solo sugerencias**: no aprueba ni bloquea nada; decide el
> fundador. Sirve a quien refresque los 47 PR de la épica de experiencia (#253–#299, Feature
> [m-24842956](https://project.larksuite.com/5h2wsx/story/detail/24842956)) sobre `main`.

## Alcance

| PR | Estado | Qué toca al cliente |
|---|---|---|
| **#304** `ecb9ca5` — Seedance 2.5 borrador, precio con video de entrada, presupuesto de instrucciones, interruptor de sonido | fusionado | Duraciones (presentador 5–60 s, clip 5/10/15 s), «Con audio» en clip y en la diapositiva animada de la galería, aviso de borrador 480p → final 1080p, «Aprobar esta versión», avisos tras aprobar, error del Planificador con un borrador |
| **#307** `fix/m-24820845-qa-visual-crear-pieza` — Crear cabe en 375 px, Descubrir reels más claro | abierto, en conflicto con `main` | `.q-seg-fit` (controles segmentados a lo ancho del celular), «Resumen» en rejilla, subtítulo de «Descubrir reels», «Replicar con mi marca · Muy pronto» |
| **#250** — épica multi-negocio en una sesión | fusionado, solo `docs/` | Propone textos futuros (selector de negocio, S3–S7); ningún texto llega hoy a la app |
| **#308** — hoja de ruta y backlog | fusionado, solo `docs/` | Ninguno |

Contrastado con `qualify-ux`, `qualify-copy-es`, `docs/ux-guia-navegacion.md` (N1–N13), la épica
`docs/epica-ux-navegacion-experiencia.md` v5 (decisiones del fundador §2, en especial **8: el dueño
nunca ve dinero** y **11: «reel (video corto)»**) y las ramas de CREAR: #255 (CREAR-2), #265
(CREAR-6), #274 (CREAR-3), #279 (CREAR-7), #284 (PRODUCTOS-3), #292 (PRODUCTOS-2) y #299
(CREAR-5). Las ramas de CREAR están **apiladas**: #265 contiene #255, y #274 → #279 → #284 → #292
→ #299 contienen a las anteriores; los conflictos se resuelven una vez, en la más baja que toque el
archivo, y suben con la pila.

Las líneas citadas son de `main` en `ecb9ca5` salvo que se diga otra rama.

## Hallazgos

### 1. El dueño ve dólares en su publicación («USD 0,51») — choca con la decisión 8

- **Dónde:** `Qualify/creative_vm.py:1130-1136` (insignia `f"Borrador · 480p{cost}"` con
  `" · USD {cents}"`), mostrada por `_video_draft_notice` en `Qualify/creative_pages.py:1388`.
  Además «Consume créditos» en `Qualify/creative_pages.py:2318` (nuevo en #304; los de 2138 y 2298 ya
  existían).
- **Lo que siente el dueño:** «¿Me van a cobrar 0,51 dólares cada vez? ¿Qué son créditos? ¿Cuántos
  tengo?» La épica decidió que el dueño cuenta en **creaciones del mes** y que el costo en dólares
  solo lo ve el equipo (decisión 8, CREAR-5). Hoy conviven tres monedas: dólares, «créditos» y, cuando
  entre #299, «creaciones».
- **Arreglo:** quitar el costo de la insignia (dejar «Vista previa», ver hallazgo 2) y llevar el
  monto en dólares al informe del equipo que ya trae #299 (`creations_report.py`). Cambiar
  «Consume créditos.» por la frase de #299 con el peso real, p. ej. «Usa 3 de tus creaciones.»; si
  el final no cobra creaciones aparte (lo decide data-scientist-fde, §Pesos), quitar la frase.

### 2. «480p», «1080p», «borrador», «final pendiente»: palabras de técnico sobre el video

- **Dónde:** `Qualify/creative_vm.py:1063, 1077-1090, 1106, 1136-1170`;
  `Qualify/creative_pages.py:1412, 2316-2319`; `Qualify/creative_state.py:5461, 5556`;
  `packages/api/src/qualify_api/planner/publishable.py:139`;
  `packages/api/src/qualify_api/creative/draft_mode.py:30, 77`.
- **Lo que siente el dueño:** «¿Qué es 480p? ¿Mi video salió mal? ¿Qué es "Generando final"?» Una
  dueña de heladería no sabe de resoluciones; sí entiende «vista previa» y «alta calidad».
- **Arreglo (mismo comportamiento, otras palabras):**

| Hoy | Propuesta |
|---|---|
| «Borrador · 480p · USD 0,51» | «Vista previa» |
| «Es una versión borrador, barata y a 480p. Al aprobarla generamos el video final a 1080p desde este mismo borrador.» | «Es una vista previa en calidad baja, para que decidas rápido. Al aprobarla preparamos el mismo video en alta calidad.» |
| «Generando final · 1080p» | «Preparando el video final» |
| «Estamos generando el video final a 1080p. Tarda unos minutos; puedes salir de esta pantalla.» | «Estamos preparando el video en alta calidad. Tarda unos minutos; puedes salir y lo verás aquí cuando esté listo.» |
| «Final pendiente» | «Falta el video final» |
| «Borrador caducado» / «El borrador caducó (se guarda 7 días): vuelve a generar…» | «La vista previa venció» / «Las vistas previas duran 7 días. Crea la publicación otra vez para tener una nueva.» |
| «Reintentar video final» | «Intentar de nuevo» |
| «Te quedas con esta versión y generamos el video final a 1080p desde este borrador. Consume créditos. Cuando esté listo eliges el día y la hora en que sale.» | «Te quedas con esta versión y preparamos el video en alta calidad. Tarda unos minutos. Cuando esté listo eliges el día y la hora en que sale.» (+ creaciones si aplica, hallazgo 1) |
| «Versión aprobada: estamos generando el video final a 1080p.» | «Aprobada. Estamos preparando el video en alta calidad.» |
| «El video final a 1080p está listo. Ahora elige cuándo sale.» | «Tu video ya está listo. Ahora elige cuándo sale.» |
| «El video es todavía un borrador a 480p: espera a que termine el video final (o reinténtalo desde la publicación).» (Planificador) | «Este video todavía es una vista previa. Espera a que esté listo el video final o inténtalo de nuevo desde la publicación.» |
| «Aprueba la publicación antes de generar su video final.» | «Primero aprueba la publicación; después preparamos el video final.» |

### 3. Seis duraciones a la vista del presentador, y algunas que luego no se pueden crear

- **Dónde:** `Qualify/creative_state.py:544` (`_DURATIONS = ("5","10","15","30","45","60")`), usado
  en `Qualify/content_generator.py:3325` (`_duration_select`, presentador) y `:3597` (guion para una
  persona). En #299 `duration_choices` (`creative_state.py:4859` de esa rama) ya limita el
  presentador a lo que la tabla de creaciones cubre (15 y 30 s).
- **Lo que siente el dueño:** «Elijo 60 s y me dice que no se puede» o «¿5 segundos de presentador
  me sirven de algo?». Seis botones de «5 s» a «60 s» en una fila es una decisión más de las que
  necesita; a 360 px cabe solo con la letra reducida de `.q-seg-fit` (#307).
- **Arreglo:** el control muestra **solo lo que se puede crear y cobrar**: presentador = la lista de
  `duration_choices` de #299 (hoy 15 y 30 s, ya rellenado con el último usado); guion para una persona
  = 15/30/45/60 (un guion de 5 s no es un caso del dueño; *hipótesis*: validar con la pregunta 6 de
  `docs/perfil-cliente-pyme.md` §5, mostrando el paso ③ con las duraciones). Si el fundador quiere presentador de 5–10 s o de
  45–60 s, primero data-scientist-fde le pone peso (§Pesos) y después aparece el botón.

### 4. Dónde va «Duración» y «Con audio» del clip en los cuatro pasos de CREAR-2

- **Dónde:** `Qualify/content_generator.py:3604-3628` (#304 los añade a `_section_channel`, que en
  #255 es el paso ③ «Cómo la quieres»).
- **Lo que siente el dueño:** el paso ③ crece: formato + duración + sonido + una explicación de dos
  frases. Con #299 además «Este video usa N de tus creaciones».
- **Arreglo (paso ③ de CREAR-2):**

```
③ Cómo la quieres                       Paso 3 de 4
  Formato     [ Reel (video corto) 9:16 | Publicación 4:5 ]
  Duración    [ 5 s | 10 s | 15 s ]      ← visible: cambia lo que usa del mes
  Este video usa 3 de tus creaciones. Te quedarían 15 de 30.
  ▸ Más opciones
      «El sonido del video y la campaña. Puedes crear sin tocarlos.»
      [●] Con sonido
          Sonido de ambiente y voces, creados junto con el video.
      Campaña  [▼]
  [ Atrás ]                         [ Siguiente ]
```

  Texto del interruptor: «Con sonido» (o mantener «Con audio») y ayuda
  «Sonido de ambiente y voces, creados junto con el video.» Quitar «Si el modelo de video no genera
  sonido, sale sin audio» (`content_generator.py:3632-3635`): «modelo» es palabra de técnico; si un
  tipo de video no puede traer sonido, mejor no mostrar el interruptor.

### 5. El subtítulo nuevo de «Descubrir reels» pisa el renombre de CREAR-6

- **Dónde:** #307, `Qualify/content_generator.py:345-349` de su rama (título «Descubrir reels»,
  «reels… de tus referentes, solo de tu producto o su categoría»). #265 lo renombra a «Descubrir
  ideas de videos» con «Los videos con más vistas de las cuentas que tomas de referencia, solo de tu
  rubro, para inspirarte o hacer uno parecido.»
- **Lo que siente el dueño:** «¿Qué es un referente? ¿Replicar?» La precisión de #307 (solo de tu
  producto o su categoría, que es lo que filtra `referentes/reels_ai.py`) es buena; el vocabulario no.
- **Arreglo:** título de #265 y frase combinada:
  «Los videos con más vistas de las cuentas que tomas de referencia, solo de tu producto o su
  categoría, para inspirarte o hacer uno parecido.»

### 6. «Muy pronto» en el botón de replicar: bien la idea, dos ajustes

- **Dónde:** #307, `Qualify/discover_reels.py:694-715` de su rama.
- **Lo que siente el dueño:** hoy (`main`) ve un botón apagado sin saber por qué; con #307 lo sabe.
  Bien. Pero la guía usa «Pronto» (N10) y la ayuda vive en un `tooltip`, que en el celular no se ve
  (N12, CREAR-6: «ninguna explicación vive solo en tooltip»).
- **Arreglo:** «Pronto» en lugar de «Muy pronto» (mismo texto que el menú) y la explicación como
  texto pequeño debajo del botón, visible siempre: «Pronto podrás hacer tu versión de este video con
  tu marca.» El tooltip puede quedarse para el mouse.

### 7. «Aprobar esta versión» frente a un solo «Aprobar» en todas partes

- **Dónde:** `Qualify/creative_vm.py:977`, `Qualify/creative_state.py:1218-1224`,
  `Qualify/creative_pages.py:2314-2324`; y `Qualify/variations_state.py:77` sigue diciendo
  «Pieza aprobada.» (CREAR-4 lo cambia).
- **Lo que siente el dueño:** el mismo botón cambia de nombre según el tipo de video; en Por aprobar
  (#274) y en la galería se llama «Aprobar».
- **Arreglo:** botón siempre «Aprobar» (CREAR-1/CREAR-3); lo que cambia es la frase de la tarjeta
  (hallazgo 2). Si el fundador prefiere distinguirlo, «Aprobar esta versión» es aceptable: no es un
  problema de palabras prohibidas, solo de un nombre por acción. «Pieza aprobada.» →
  «Publicación aprobada. Ahora elige cuándo sale.» (`APPROVED_TOAST`, mismo texto que la galería).

### 8. Tras aprobar desde la galería o Variaciones con el video aún en preparación, solo queda un aviso flotante

- **Dónde:** `Qualify/gallery_state.py:228-238` y `Qualify/variations_state.py:737-740`
  (`approval_notice` con `offer_schedule=False` → toast sin botón: «… Ábrela para ver cuándo está
  listo.»).
- **Lo que siente el dueño:** «¿Ábrela dónde?» El aviso desaparece y no hay a dónde tocar (N3).
- **Arreglo:** el toast lleva acción «Ver publicación» → `/drafts/<id>` cuando el video se está
  preparando o falló, igual que hoy lleva «Elegir día y hora» cuando ya se puede programar. A más
  largo plazo, la tarjeta de #274 (CREAR-3) muestra el estado en texto: «Preparando el video final»
  como estado y el botón principal deshabilitado con ese texto hasta que esté.

**Fuera del top 8 (pulido):** #307 cumple N12 en lo que toca —el «Resumen» en rejilla ya no parte
palabras a 375 px, las duraciones no se cortan («15 s» con espacio de no separación), `.q-seg-fit`
mete los cuatro formatos en el ancho— y conviene conservarlo entero. Los textos propuestos de #250
(selector de negocio) están en palabras del dueño y sin anglicismos; una sola nota: «Vas a publicar
en {negocio}. ¿Seguimos?» antes de **cada** publicación puede cansar a quien tiene un solo negocio:
mostrarlo solo a quien tiene dos o más (*hipótesis*: validar con la pregunta 2 de `docs/perfil-cliente-pyme.md` §5, con el dueño de Bianki y Polette). #308: sin
sugerencias.

## Reglas para resolver conflictos

Para quien fusione `main` (con #304) y #307 en las ramas de CREAR. Regla general: **el
comportamiento del equipo (#304, #307) se queda; el texto, el orden de pasos y la ubicación son los
de la historia de experiencia**. Ninguna regla elimina funciones de #304.

1. **Duraciones (`creative_state.py`, `_DURATIONS` / `DURATIONS` / `_CLIP_DURATIONS` /
   `SLIDE_SECONDS`).** #307 renombra `_DURATIONS` → `DURATIONS` con los valores viejos (15–60) y
   `_SLIDE_SECONDS` → `SLIDE_SECONDS`; #304 cambió los valores (5–60) y añadió `_CLIP_DURATIONS`.
   → **Ambos:** nombres públicos de #307, valores de #304 (`DURATIONS = ("5",…,"60")`,
   `CLIP_DURATIONS = ("5","10","15")`), y en la pila de #299 el control del presentador lee
   `duration_choices` (no la tupla fija). Lo que se ofrece en pantalla, según hallazgo 3.
2. **Controles de duración (`content_generator.py` `_duration_select`, `_section_channel`,
   `_slide_generated_fields`).** → **Ambos:** el bucle sobre la tupla de #304 + `_seconds_items(...)`
   y `class_name="q-seg-fit q-seg-fit--nowrap"` de #307; el `_duration_select` en `vstack` (etiqueta
   arriba) de #307. El nuevo control de duración del clip también lleva `_seconds_items` y
   `q-seg-fit--nowrap`.
3. **Diapositiva animada de la galería (`_slide_generated_fields`).** #304 envuelve la duración en
   un `vstack` con `_audio_switch`; #307 añade la clase al control. → **Ambos:** el `vstack` de #304
   con el control de #307 dentro.
4. **Duración y sonido del clip en `_section_channel`.** → **Comportamiento de #304, ubicación de
   CREAR-2 (#255):** duración visible en el paso ③; «Con audio» dentro del «Más opciones» del paso ③
   junto a la campaña (hallazgo 4). Si mover el interruptor complica la fusión, déjalo visible en ③:
   lo importante es que no aparezca en el paso ①.
5. **«Resumen» (`_summary_row`).** #255 cambió el clic a `CreativeState.edit_view(item["view"])` y
   `min_height="44px"`; #307 lo pasó a rejilla con `go_to_view(item["index"])`. → **Ambos:** rejilla y
   clases de #307 (`q-cr-summary-*`), clic y altura de #255 (`edit_view(item["view"])`, 44 px): los
   «Editar» deben llevar al paso correcto de los cuatro.
6. **Encabezado y subtítulo de Descubrir (`_DISCOVER_HEADING`).** → **Texto de CREAR-6 (#265)** con
   la precisión de #307 (hallazgo 5). Los comentarios de código pueden seguir diciendo «Descubrir
   reels».
7. **Botón «Replicar con mi marca» (`discover_reels.py`).** → **Comportamiento y estilo de #307**
   (variante gris, envoltorio para el puntero, `q-dr-*`), con «Pronto» y la ayuda visible debajo
   (hallazgo 6).
8. **Tarjeta de decisión y tarjeta «Aprobada» (`creative_pages.py` `_decision_bar_or_nothing`,
   `_approved_next`, `_video_draft_notice`).** → **Comportamiento de #304** (`approve_label` o
   «Aprobar», `approved_can_schedule`, `approved_hold_note`, sondeo del final, «Reintentar») **dentro
   del diseño de CREAR-1/CREAR-3** (un botón principal por tarjeta, botones ≥ 44 px). Textos según
   hallazgos 1, 2 y 7. `_video_draft_notice` va en la ficha junto a `_retention_notice`.
9. **Avisos tras aprobar (`gallery_state.py`, `variations_state.py`).** #274 toca `gallery_state.py`.
   → **Comportamiento de #304**: los tres sitios eligen su aviso con `approval_notice`; no volver a
   las constantes locales. Las constantes `APPROVED_*` viven ahora en `creative_vm.py`.
10. **Avisos de marca, `.q-seg-fit` en Formato y en las pestañas «De dónde viene».** → **#307
    entero**: no reescribir el CSS en las ramas de CREAR; si una rama cambia las etiquetas de
    Formato (p. ej. «Reel (video corto) 9:16», decisión 11), comprobar a 360 px que «cuadrada» y
    «(video corto)» no se parten a media palabra.
11. **Nombre «Crear pieza».** Solo aparece en el título de #307 y en comentarios; en la app ya dice
    «Crear publicación» (`content_generator.py:4637`). → **Texto de la épica** («Crear publicación»);
    no hay conflicto visible.

## Pesos de #299 (para que decida data-scientist-fde)

Sí, `pesos-creaciones-v1.json` de #299 necesita revisión antes de fusionarse sobre `main`:

1. **Duración del clip.** #304 añade `clip_duration` (5/10/15 s), distinto de `media_duration`.
   `_creations_price` de #299 pasa `duration_seconds=int(self.media_duration or 30)` también para el
   clip: un clip de 5 s se cobraría como de 15 s (6 en lugar de 3). Pasar `clip_duration` cuando
   `brief_kind == "clip"`.
2. **Presentador de 5 y 10 s, y de 45 y 60 s.** Con `_DURATIONS` de #304 aparecen; la tabla v1 solo
   cubre ≤15 (13) y ≤30 (25). Un presentador de 5 s cuesta 13; 45/60 s dan `CreationNotOffered`.
   Decidir: filas nuevas, o dejar el control limitado a `duration_choices` (hallazgo 3).
3. **Modo borrador de Seedance 2.5.** Ahora cada video pasa por un borrador a 480p y, al aprobar, un
   final a 1080p (un segundo cobro del proveedor, con la tarifa del borrador). Decidir si el peso de
   un video generado cubre los dos (se cobra al crear) o si el final cobra al aprobar, y si un final
   fallido devuelve creaciones como dice CREAR-5. Si cobra al aprobar, la tarjeta de aprobar debe
   decir cuántas usa (hallazgo 1).
4. **Precio con video de entrada.** Con un video de referencia, la tarifa por millón baja (6,40 vs
   10,70 a 480p) pero se cobran también los segundos del video de entrada (medido: ~116 000 vs
   ~48 000 tokens para 5 s, `docs/modelos-generativos/seedance-2-5.md`). Los pesos por segundos no
   miran la referencia.
5. **Versión de la tabla de precios.** v1 dice `"pricing_table_version": "v5"`; `main` ya está en
   **v7**. La procedencia de cada cobro debe citar la tabla vigente.
6. **Sonido.** v7 no le pone precio aparte al audio de Seedance 2.5; si el proveedor lo cobra
   distinto, el interruptor «Con audio» también debería cambiar el peso.
