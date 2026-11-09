# Stickers y videos cortos de tu marca: crear, aprobar y mandar (m-24955647)

Especificación de experiencia (ux-designer, 2026-11-08). **Propuesta: no se revisó en la app corriendo.**
Base: decisión del fundador en `docs/opciones-stickers-videos-cortos.md` §9 (beta gratis B + E; «Crear
con IA» por pieza con costo antes de generar; todo pasa por «Por aprobar»; las temporadas se guardan),
`docs/ux-whatsapp-menu-orbit.md` (seis filas, nunca una séptima), `docs/ux-whatsapp-atajos.md`
(«Fotos y videos» → «¿De dónde?»), `docs/ux-whatsapp-enviar-imagen.md`. Sin componentes nuevos:
`drawer`, `step_progress`, `choice_card`, `media_thumb`, `chat_bubble`, `callout`, `tone_badge`,
`signal_pill`, `empty_state`, `skeleton_card`.

## 1. Dónde empieza: «Crear para esta temporada»

- **Su casa es «Tu marca»**, sección nueva **«Stickers y videos de tu marca»**: son identidad, como
  el logo y los colores, y se guardan de temporada en temporada. Ahí está la biblioteca (§4) y el
  botón **«Crear para esta temporada»**. Lo creado pasa por **«Por aprobar»** como toda pieza.
- **Atajos al mismo flujo** (no otros flujos): el aviso de «Tu semana» (§4) y, en «Por aprobar»
  vacío, el enlace «Crea tus stickers y videos de temporada».
- **Flujo en `drawer`, 3 pasos** («Paso N de 3», «‹ Atrás» sin perder nada):
  1. **«¿Para qué ocasión?»** `choice_card`: la temporada que viene según el calendario del país
     (CO/VE/UY), **ya elegida** («Navidad 2026 · faltan 3 semanas»), la siguiente, **«Todo el año»**
     (sin fecha) y **«Otra ocasión»** con campo «Nombre de la ocasión» (≤ 24, contador «0/24»,
     ejemplo «Por ejemplo: Aniversario del local»).
  2. **«¿Cómo lo creamos?»** dos `choice_card`, la primera **ya elegida**, nunca las dos:
     - **«Con lo que ya tienes · gratis»** — «Stickers con tu logo y tus colores, y videos con tus
       fotos ya aprobadas. Sin costo.»
     - **«Crear con IA · unos US$0,05 por video»** — «La IA anima una foto tuya para que se mueva
       sola. Tiene costo y solo hace videos: no puede dejar el fondo transparente que necesita un
       sticker.» (precio de la tabla vigente, nunca escrito a mano).
  3. **«Revisa y crea»** en palabras: «Vamos a preparar 6 stickers y 4 videos para «Navidad 2026».
     Llegan a Por aprobar en unos minutos. Nada se manda sin que lo apruebes.» → **[Crear]**.
     Con IA, el paso 3 es **«¿Qué foto animamos?»** (grilla de fotos aprobadas y de Tus productos,
     una sola) y el botón dice el costo: **[Crear el video · unos US$0,05]**. Si la guarda de precio
     (ADR 41) lo frena: «Este mes ya usaste lo que tu plan trae para videos con IA. Usa «Con lo que
     ya tienes», que es gratis.»
- **Falta material** (lo dice el paso 2, no un error al final): sin logo, «Para tus stickers
  necesitamos tu logo. Súbelo en Tu marca.» [Subir mi logo]; sin fotos aprobadas, «Para tus videos
  necesitamos al menos una foto aprobada.» [Ir a Por aprobar]. Con uno de los dos se crea lo posible.

```
Paso 2 de 3                          Paso 3 de 3 (gratis)
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ ‹ Atrás              Paso 2 de 3│  │ ‹ Atrás              Paso 3 de 3│
│ ¿Cómo lo creamos?               │  │ Revisa y crea                   │
│ ┌─────────────────────────────┐ │  │ Vamos a preparar 6 stickers y   │
│ │(•) Con lo que ya tienes     │ │  │ 4 videos para «Navidad 2026».   │
│ │    · gratis                 │ │  │ Llegan a Por aprobar en unos    │
│ │ Stickers con tu logo y tus  │ │  │ minutos. Nada se manda sin que  │
│ │ colores, y videos con tus   │ │  │ lo apruebes.                    │
│ │ fotos ya aprobadas.         │ │  │                                 │
│ ├─────────────────────────────┤ │  │                                 │
│ │( ) Crear con IA · unos      │ │  │                                 │
│ │    US$0,05 por video        │ │  │                                 │
│ │ Tiene costo y solo hace     │ │  │                                 │
│ │ videos: sin fondo           │ │  │                                 │
│ │ transparente.               │ │  │                                 │
│ └─────────────────────────────┘ │  │                                 │
│ [         Siguiente           ] │  │ [            Crear            ] │
└─────────────────────────────────┘  └─────────────────────────────────┘
```

## 2. La tanda en «Por aprobar»

- Grupo con título de temporada y progreso: **«Navidad 2026 · 3 de 10 listos»** (`step_progress`
  de barra); lo que se está preparando es `skeleton_card` con «Preparando…».
- **Una tarjeta por pieza:** vista previa cuadrada; `tone_badge` **«Sticker»** o **«Video»** (texto),
  el peso («320 KB») y la etiqueta de temporada. **Los stickers se animan al estar a la vista** (son
  livianos y es lo que se aprueba); **los videos solo al tocar** (icono `play`). Con
  `prefers-reduced-motion`, nada se mueve hasta tocar.
- **Botones:** **«Aprobar»** y **«Pedir otro»**. «Pedir otro» rehace solo esa pieza, del mismo tipo:
  un sticker cambia de movimiento (latido → rebote → giro → brillo) o de base (logo ↔ texto de
  temporada); un video toma otras fotos u otro movimiento. Gratis en la tanda gratis; en una pieza
  hecha con IA lo dice antes: «Pedir otro cuesta unos US$0,05. ¿Lo creamos?» [Sí, crear otro] [Cancelar].
- **«Aprobar los listos»** al pie del grupo, con confirmación «Vas a aprobar 7 stickers y videos de
  «Navidad 2026». Desde ahí los puedes mandar en tus chats.» (pregunta 1 al fundador).
- **Fallas, en la tarjeta:** muy pesado → `signal_pill` warn «Muy pesado» + «Salió muy pesado para
  WhatsApp. Pide otro.»; no salió → «Este no salió. Pide otro.»; la tanda entera falla → `callout`
  «No pudimos preparar tus stickers. Vuelve a intentarlo en un rato.» [Intentar de nuevo].
- **Regla:** lo no aprobado **nunca** aparece en el chat. No hay «mandar sin aprobar» (más estricto
  que las piezas de hoy, por decisión del fundador).

## 3. Mandarlo desde el chat

- **Seis filas, sin fila nueva.** En «+» → «Fotos y videos» → **«¿De dónde?»** aparece una tercera
  tarjeta **solo cuando hay algo aprobado**: «Stickers y videos de tu marca — Para saludar y
  celebrar con tu marca.» (si hay de un solo tipo: «Stickers de tu marca» o «Videos de tu marca»).
  Sin nada aprobado no se muestra (decisión del fundador: solo cuando hay algo listo).
- **«¿Qué le mandas?»** (paso 2 de 3): si hay de los dos, `segmented_control` «Stickers · Videos».
  Grilla de 3 columnas con la **temporada actual primero** («Navidad 2026») y debajo **«De otras
  temporadas»**, más recientes arriba. Los stickers se animan a la vista; los videos, quietos.
- **«Revisa y envía»** (paso 3 de 3), ayuda «Así le llega. Nada sale sin que toques «Enviar».»:
  - Sticker: la vista previa **sola, sin burbuja ni texto** y la línea «Los stickers llegan solos,
    sin texto.»
  - Video: burbuja con el video quieto y el campo **«Texto que acompaña el video (opcional)»**,
    vacío por defecto, contador «0/1024».
- **El cliente recibe:** el sticker animado, suelto, como cualquier sticker de WhatsApp; o el video
  en su burbuja, sin sonido, que se reproduce al tocar, con el texto si el dueño lo escribió.
- Fuera de las 24 horas, igual que hoy: el «+» no existe y queda «Enviar un mensaje aprobado».

## 4. Temporadas y renovación

- **Biblioteca en Tu marca › «Stickers y videos de tu marca»:** una fila por temporada,
  «Navidad 2026 · 6 stickers, 4 videos», la actual abierta y las anteriores cerradas. Cada una:
  **«Archivar»** (sale del chat, se guarda; aviso «Listo: «Día de la Madre 2026» ya no aparece en tus
  chats.» [Deshacer]) y, en «Archivadas», **«Volver a usar»**. Nada se borra solo.
- **En el chat, una temporada que ya pasó** baja a «De otras temporadas»; no desaparece hasta que
  el dueño la archiva.
- **Aviso en «Tu semana», tres semanas antes** de una fecha del calendario del país, si esa
  temporada todavía no tiene tanda: **«Navidad está cerca: crea tus stickers y videos.»**
  [Crear para Navidad] (abre el flujo en el paso 2 con la ocasión elegida) · «Ahora no» (no vuelve
  esa temporada).

## 5. Textos

- Tu marca: «Stickers y videos de tu marca», «Para saludar y celebrar con tu marca en WhatsApp.»,
  «Crear para esta temporada», «Archivar», «Archivadas», «Volver a usar».
- Vacío de la sección: «Aún no tienes stickers ni videos» · «Créalos gratis con tu logo y tus fotos
  aprobadas. Los mandas en tus chats con un toque.» [Crear para esta temporada].
- Flujo: los textos de §1 («¿Para qué ocasión?», «Todo el año», «Otra ocasión», «Nombre de la
  ocasión», «¿Cómo lo creamos?», «Con lo que ya tienes · gratis», «Crear con IA · unos US$0,05 por
  video», «Revisa y crea», «¿Qué foto animamos?», «Crear», «Crear el video · unos US$0,05»).
- Por aprobar y chat: §2 y §3 («Sticker», «Video», «Preparando…», «Pedir otro», «Aprobar los
  listos», «Muy pesado», «Stickers y videos de tu marca», «¿Qué le mandas?», «De otras temporadas»,
  «Los stickers llegan solos, sin texto.», «Texto que acompaña el video (opcional)»).
- **Honestidad de la IA:** siempre con el costo al lado del botón y en «Pedir otro»; siempre la
  frase «solo hace videos: no puede dejar el fondo transparente que necesita un sticker»; nunca
  «mágico», «automático» ni promesas de resultado.
- Sin inglés: «Stickers» se acepta porque así lo dice WhatsApp en español; «IA», no «AI».

## 6. Pruebas y preguntas

- **Pruebas:** el «+» sigue con 6 filas; «¿De dónde?» muestra la tercera tarjeta solo con algo
  aprobado y con el nombre según el tipo; una pieza sin aprobar nunca está en «¿Qué le mandas?»;
  temporada actual primero; sticker sin campo de texto, video con campo opcional vacío; el flujo
  preelige la temporada que viene y «Con lo que ya tienes»; el botón con IA lleva el costo de la
  tabla vigente y «Pedir otro» con IA confirma; nada con `autoplay` en videos; con
  `prefers-reduced-motion` nada se anima; «Archivar» la saca del chat y «Volver a usar» la devuelve.
- **Preguntas para el fundador:**
  1. ¿Se permite **«Aprobar los listos»** (todo el grupo con una confirmación), o una por una?
  2. El costo de la IA: ¿se muestra en **dólares** («unos US$0,05») o como parte del plan («usa 1 de
     tus 10 videos con IA del mes»)?
