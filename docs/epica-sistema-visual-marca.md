# Épica — Sistema visual de la marca: identidad, consistencia y creatividad propia en cada imagen

`[ABIERTA · creada 2026-11-17]` · Feature Meegle **m-25042540** —
https://project.larksuite.com/5h2wsx/story/detail/25042540 · sigue a la épica de imagen y carrusel
**m-25017272** (`docs/epica-refactor-imagen-carrusel.md`) y reutiliza su pipeline.

## Decisiones del fundador (2026-11-17)

Tomadas por Herwin Rey (fundador) el 2026-11-17, al ver las dos primeras piezas reales con la capa
encendida. Rigen sobre todo lo demás de este documento.

| # | Tema | Decisión |
|---|---|---|
| S1 | Dirección | Cada negocio tiene un **«sistema visual de la marca»**: identidad a través de las imágenes, consistencia entre piezas y una creatividad propia de esa marca (no siete diseños iguales para todos). |
| S2 | Cuándo se propone | Cuando «Tu marca» está completa con unos datos mínimos, la IA genera **automáticamente** propuestas de sistema visual y las muestra **sobre el contenido del propio dueño** (su producto estrella con su precio, su horario, una historia) bajo la pregunta **«¿Cómo se vería tu marca?»**; el dueño elige una. **No en el Alta** (faltan datos). |
| S3 | Kit de inicio = «Plantillas» | El kit de inicio (ubicación, horarios, formas de pago, contacto, menú, íconos de destacados, un flyer por producto principal; también el mural del feed y las historias diarias como en la carpeta de Bianki) **es** el módulo «Plantillas» dentro de «Crear publicación»; el dueño vuelve a generar cada una con los datos de ese módulo. |
| S4 | Volver atrás | Volver a una versión anterior del sistema visual es **muy importante: requisito duro**. |
| S5 | Pilotos | El sistema que Bianki ya tiene se **reutiliza tal cual**; Polette es la prueba desde cero. |
| S6 | Reglas que siguen | Composición solo en Remotion (sin Pillow como compositor); nada de base de datos, runtime ni proveedor nuevo sin tabla de opciones y su decisión; asistido, nunca autónomo; procedencia; aislamiento por negocio. |

## Por qué (evidencia)

- **Lo que hay en producción** `[V]`: desde el 2026-11-17 la capa de texto + composición en Remotion
  está encendida para todos los negocios (`QUALIFY_IMAGE_LAYER=on`): Seedream hace la foto base,
  Claude escribe la capa, Remotion compone **uno de 7 diseños genéricos**
  (`docs/catalogo-disenos-imagen-carrusel.md` §2). Dos piezas reales de Bianki (una imagen y un
  carrusel de 3, «Shawarma mixto») salieron de punta a punta sin errores
  (`docs/modelos-generativos/pruebas.md`, CAPA-004).
- **El juicio del fundador** `[F]`: el resultado es **«muy sencillo»**. CAPA-004 muestra por qué:
  la foto es todo el lienzo y el texto va en una franja; la foto se achicó con laterales borrosos
  (`band … photo reduced`, A); el precio no salió porque el pedido normal de «Imagen» nunca llena
  `price_line` (B); la palabra de acento cayó al color del texto por contraste.
- **El listón** `[V]`, hecho fuera de Qualify (`/Users/herwin/Documents/Bianki/Instagram y Google
  2026-11/`: `vista-general-flyers.jpg`, `vista-iconos-en-circulo.jpg`,
  `9-stories-diarias/vista-general.jpg`, `8-feed/feed-mural-completo.jpg`,
  `pipeline-redes-y-seedance.md` §2). Lo que lo hace funcionar:
  1. **Fondo de marca** (rojo con rayos y aros, o crema con aros), no la foto como lienzo entero.
  2. **Producto recortado sobre un disco** de rayos amarillos.
  3. **Componentes de firma**: etiqueta inclinada («¡ELIGE TU FAVORITO!»), titular en dos colores
     (blanco + amarillo), banderín de precio con la referencia en dólares, sello «300 gramos»,
     cinta inferior que corre con datos del negocio.
  4. **Datos reales del negocio** (dirección «Av. Los Agustinos en Korner», 4:00 PM a 11:00 PM,
     métodos de pago por moneda, WhatsApp, web), nunca inventados.
  5. **Series de la misma receta**: un flyer por producto, el mural 3×3, 7 historias sin precio.

  Ese conjunto se armó con tokens de marca (rojo `#e3000f`, amarillo `#ffd200`, crema `#fff8df`,
  rojo oscuro `#7a0008`; Unbounded 800 + Archivo) y componentes HTML reutilizables — es decir, ya
  es un **sistema** expresado como datos + componentes. Qualify puede expresarlo igual, en Remotion.

## Qué se queda de la Fase 1 de m-25017272 y qué cambia

**Se queda** (no se toca): la cola de generación (ADR 41, `creative-worker`), la composición en
Remotion por diapositiva y su reintento de 10 minutos (A4/B4), Seedream solo como foto base, la
llamada de Claude que ve la foto, la regla del precio (B5: una pieza con precio nunca se publica
sin él), la regeneración única de la base, el registro de costo por pieza (m-25042157),
`piece_layers` y su procedencia, «Usar mi foto» con el candado de la Galería (ADR 49 §2.6).

**Cambia:** el catálogo cerrado de 7 diseños deja de ser el destino y pasa a ser el **respaldo**
para negocios sin sistema. Para un negocio con sistema, la capa elige una **receta de su marca**
(fondo, disposición, componentes de firma, tipografía, colores) y llena sus espacios. El ADR que
cambia el modelo de composición (sistema visual versionado como dato del negocio, recetas en
Remotion) lo escribe `principal-architect` después del spike; esta épica no lo decide.

### Historias abiertas de m-25017272

| Ticket | Qué pasa | Por qué |
|---|---|---|
| m-25017300 Datos del negocio | **Se queda**, sube de importancia | Lo necesitan las muestras de «¿Cómo se vería tu marca?» y las plantillas de datos. Ya existen métodos de pago (migración 0135) y ubicación (0169); faltan horarios y contacto en un solo lugar (verificar en el código al tomarla). |
| m-25017301 Spike destacados por API | **Se queda** | Decide si íconos y portadas son solo descarga. |
| m-25017303 Portada de destacado | **Absorbida** por m-25042562 | Pasa a ser una receta del sistema. |
| m-25017304 Íconos para destacados | **Absorbida** por m-25042562 | Ídem (`vista-iconos-en-circulo.jpg` es el listón). |
| m-25017307 Flyer informativo | **Absorbida** por m-25042561 | Ubicación, horarios, pagos, contacto y menú son plantillas de datos del sistema. |
| m-25017308 Tipo «Otros» | **Se queda, aparcada** (P3) | Cuando salga, usa recetas del sistema en vez de los 7 diseños. |
| m-25017309 Pantalla en cuatro pasos | **Se queda, se re-alcanza** | El paso «tipo» muestra las recetas y las plantillas; espera a la Fase 2 de esta épica para no rediseñar dos veces. |
| m-25017310 «Repetir este diseño» | **Reemplazada** por esta épica | El sistema visual *es* el estilo del negocio; los ajustes de un toque (m-25042566) cubren «me gustó así». |
| Arreglo de «foto reducida» (CAPA-004 A, sin ticket) | **Reemplazado** para negocios con sistema | Las recetas ponen el producto en su ventana o recortado en el disco. Si el spike se mata, se reabre la opción 1 de CAPA-004 (recortar con tolerancia) para los 7 diseños. |
| m-25017286/287/288/292/293/294/295/297/298/299/311/313 | **Se quedan** | Son pipeline y carrusel; funcionan igual con recetas. |
| m-25019811…m-25019827 | **Se quedan** | Deudas del pipeline, ajenas a esta decisión. |

Los tickets absorbidos o reemplazados **no se cerraron**: los cierra el fundador o el hilo
principal (no son de esta épica).

## Reglas que aplican a todas las historias

- Aislamiento por negocio: toda tabla nueva con `tenant_id` + RLS en la misma migración
  (`qualify-migration`).
- Procedencia: cada versión del sistema guarda su origen (portado a mano, propuesta de IA con
  modelo + versión del prompt, ajuste de un toque) y cada pieza guarda la versión del sistema con
  la que se compuso.
- Idempotencia: un reintento no vuelve a pedir propuestas ni cobra dos veces.
- Asistido, nunca autónomo: la IA propone, el dueño elige; nada se publica sin aprobación.
- Solo Remotion compone; sin proveedor nuevo sin tabla de opciones (recorte del producto: m-25042543).
- Textos para el cliente en español (`qualify-copy-es`); revisión local de `ux-designer` antes de
  cada PR que toque pantallas. Nombre para el cliente: **«estilo de tu marca»** (propuesta; «sistema
  visual» es nuestro nombre interno) — lo confirma la revisión de UX.
- Cambios de prompt o modelo medidos y documentados en `docs/modelos-generativos/`
  (`qualify-measure`).
- Meegle: Herwin como Reporter y Assignee; se reasigna al tomarla.

## Fases

P = prioridad, T = tamaño. «Bloqueado por» está cargado en Meegle. **[C]** = condicionada al
resultado del spike (ver el criterio más abajo). **[F]** = necesita una decisión del fundador antes
de construir.

**Por qué este corte.** El camino de Bianki (sistema portado tal cual) no necesita propuestas de
IA: con el modelo de datos, el volver atrás y las recetas en Remotion (Fases 1–2) Bianki ya publica
piezas a la altura de su carpeta, y con las plantillas de datos (Fase 4) tiene su kit completo.
Por eso la Fase 4 depende de la 2 y **no** de la 3: si las propuestas de IA fallan en Polette, el
valor de Bianki sale igual. La Fase 3 (propuestas automáticas) es la apuesta más incierta y la más
cara de medir; va sola, condicionada al spike. El arreglo del precio (m-25042541) no espera a nadie y
arregla un fallo real de producción (CAPA-004 B), por eso es la primera historia construible.

### Fase 0 — Spike (en curso)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25042530 | Spike: el sistema de Bianki portado tal cual a datos + Remotion, y Polette desde cero con propuestas de la IA | creative | P1/M | — (en curso, otro agente; sigue colgado de m-25017272) |

### Fase 1 — El sistema como dato del negocio, versionado, con Bianki cargado

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25042544 | El estilo de mi marca queda guardado como versiones (modelo de datos + procedencia) **[C]** | backend + creative | P1/M | 25042530 |
| m-25042545 | Volver a una versión anterior del estilo de mi marca | creative + reflex-ui | P1/M | 25042544 |
| m-25042546 | Bianki usa el estilo que ya tiene, cargado tal cual | creative | P1/S | 25042544, 25042530 |

### Fase 2 — Recetas y componentes de marca en Remotion (reemplazan los 7 diseños si hay sistema)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25042547 | Componentes de firma en Remotion, con los colores y letras de cada marca **[C]** | creative | P1/L | 25042530, 25042544 |
| m-25042548 | Recetas por tipo de pieza para negocios con estilo; los demás siguen con los 7 diseños | creative | P1/L | 25042544, 25042547, 25042541 |
| m-25042541 | El precio del catálogo aparece en la imagen del pedido normal | creative (+ui texto) | P1/S | — (puede empezar ya) |
| m-25042550 | Claude elige la receta y escribe dentro de sus espacios (capa nueva, medida) | creative (medición datasci) | P1/M | 25042548 |
| m-25042543 | Tabla de opciones para recortar el producto (proveedor o modelo) **[F]** | datasci (+architect) | P1/S | — |
| m-25042551 | El producto sale recortado sobre el disco de la receta **[F]** | creative | P2/M | 25042543, 25042547 |

### Fase 3 — Propuestas de la IA y «¿Cómo se vería tu marca?» **[C]**

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25042552 | Datos mínimos de «Tu marca» y disparo automático de las propuestas **[F]** | backend + reflex-ui | P1/S | 25042544, 25017300 |
| m-25042555 | La IA propone estilos distintos para mi marca **[C]** | creative (medición datasci) | P1/L | 25042544, 25042548 |
| m-25042557 | «¿Cómo se vería tu marca?»: veo las propuestas sobre mi contenido y elijo una | reflex-ui | P1/L | 25042552, 25042555 |
| m-25042560 | Los negocios que ya usan Qualify reciben su estilo una sola vez **[F]** | reflex-ui + backend | P2/M | 25042557 |
| m-25042558 | Qué pasa con publicaciones aprobadas o programadas al cambiar o volver de estilo **[F]** | creative | P2/S | 25042545 |

### Fase 4 — El kit de inicio es «Plantillas» en «Crear publicación»

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25042563 | «Plantillas» muestra mi kit y vuelvo a generar cada pieza con sus datos | reflex-ui + creative | P2/L | 25042548, 25042561 |
| m-25042561 | Plantillas con datos reales: ubicación, horarios, formas de pago, contacto y menú | creative | P2/L | 25042548, 25017300 |
| m-25042562 | Íconos de destacados y portadas con el estilo de mi marca | creative | P2/M | 25042547, 25017301 |

### Fase 5 — Mural, historias diarias y ajustes de un toque

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25042564 | Mural del perfil 3×3 con la guía de orden de publicación | creative + reflex-ui | P3/L | 25042548 |
| m-25042565 | Siete historias diarias sin precio, con espacio para los stickers | creative | P3/M | 25042548 |
| m-25042566 | Ajustes de un toque que guardan una versión nueva del estilo | creative + reflex-ui | P3/M | 25042545, 25042555 |

## Historias (detalle)

Los criterios completos están en cada ticket; aquí lo verificable y el texto exacto que lee el
cliente.

**m-25042544 — Versiones del estilo.** Como dueña de la heladería, quiero que el estilo de mi marca
quede guardado, para que todas mis piezas se vean de la misma familia y nada se pierda si lo cambio.
- Cada negocio tiene 0..N versiones; una sola activa; una versión nunca se edita (cambiar = versión
  nueva). Guarda: tokens (colores, letras, fondos), componentes y sus variantes, recetas
  habilitadas, origen (`ported` / `ai_proposal` / `adjustment`) con modelo, versión del prompt y
  versión del esquema.
- Cada pieza nueva guarda la versión con la que se compuso.
- Sin datastore nuevo (tabla en Postgres con RLS); la forma exacta la fija el resultado del spike y
  el ADR de `principal-architect`.
- Test de aislamiento: un negocio no lee versiones de otro. `just ci-test` verde.

**m-25042545 — Volver atrás (requisito duro S4).** Como dueño, quiero volver a un estilo anterior con
un toque, para probar sin miedo.
- En «Tu marca», sección **«Versiones anteriores»**; cada fila: miniatura, «Usada desde el {fecha}»
  y botón **«Volver a esta»**.
- Confirmación: **«¿Volver a este estilo? Tus próximas publicaciones usarán este estilo. Las que
  ya publicaste no cambian.»** Botones **«Volver»** y **«Cancelar»**. Aviso: **«Listo, volviste a
  tu estilo anterior.»**
- Volver mueve el puntero de la versión activa, no borra nada: la versión que se deja también queda
  en la lista.
- Lo que pasa con aprobadas y programadas lo decide m-25042558; hasta entonces no se recomponen.

**m-25042546 — Bianki tal cual.** Como dueño de Bianki, quiero que Qualify use el estilo que ya tengo,
para no perder lo que funciona. Carga de su sistema (tokens y componentes de
`pipeline-redes-y-seedance.md` §2.1) como versión `ported`; verificación: el flyer de un producto y
la pieza de horarios renderizados en Remotion lado a lado con `vista-general-flyers.jpg`, aprobados
por el fundador. Solo el negocio de Bianki.

**m-25042547 — Componentes de firma.** Como dueño, quiero que mis piezas lleven los detalles que hacen
reconocible mi marca. Componentes parametrizados por la versión: fondo de marca (rayos, aros,
liso), disco del producto, etiqueta inclinada, titular en dos colores, banderín de precio (con
referencia en otra moneda si el negocio la tiene), sello (p. ej. «300 gramos»), cinta inferior con
datos. Contraste ≥ 4,5:1 en texto pequeño y 3:1 en títulos, comprobado por el compositor; sin
Pillow. Tests de cuadros con tolerancia como m-25026581.

**m-25042548 — Recetas por tipo.** Como dueño con estilo, quiero que una «Imagen» de producto salga
como mis flyers, no como un diseño genérico. Recetas mínimas: flyer de producto (fondo de marca +
producto en disco + titular + banderín), pieza con la foto como protagonista (ventana de foto
dentro del fondo de marca), historia. Un negocio sin estilo activo sigue con los 7 diseños sin
cambios (test). La regla del precio B5, la cola, el reintento y el registro de costo se mantienen.

**m-25042541 — Precio en la imagen.** Como dueño del local de comida, quiero que la imagen de mi
producto muestre su precio, para que el cliente no tenga que preguntar. Con producto del catálogo
con precio, el pedido normal de «Imagen» lleva `price_line` (hoy solo lo llenan las Variaciones,
CAPA-004 B); el paso 2 deja de decir «La imagen sale sin letras ni precios…» y dice **«Si tu
producto tiene precio, lo ponemos en la imagen.»**; una pieza con precio nunca sale sin él (B5).

**m-25042550 — Claude elige la receta.** La capa recibe las recetas de la versión activa y llena sus
espacios con el esquema cerrado; medida contra la capa actual en un set de Bianki y Polette y
documentada en `pruebas.md`.

**m-25042543 / m-25042551 — Recorte del producto.** Hoy quitar el fondo está fuera de alcance porque sería
un proveedor nuevo (épica m-25017272). Primero la tabla de opciones para el fundador (sin recorte
con ventana de foto, modelo local, servicio externo, Seedream con la foto del producto como
referencia sobre fondo liso), con costo por pieza, datos del cliente que salen y memoria del
servidor. Después, si elige, el producto recortado en el disco, guardado en la Galería del negocio.

**m-25042552 — Mínimos y disparo.** Cuando «Tu marca» cumple el mínimo que decida el fundador, se
encola una sola vez la generación de propuestas (idempotente). Aviso en «Tu marca» mientras falta
algo: **«Para mostrarte cómo se vería tu marca, falta: {lista}.»** Nunca en el Alta.

**m-25042555 — Propuestas de la IA.** Claude propone N versiones `ai_proposal` a partir del logo, sus
colores, el rubro y los productos; deben ser distintas entre sí (no tres tonos de una), y cada una
se renderiza con las recetas de m-25042548. Costo y tiempo por juego de propuestas medidos y
registrados; tope por negocio.

**m-25042557 — «¿Cómo se vería tu marca?».** Pantalla con título **«¿Cómo se vería tu marca?»**,
subtítulo **«Preparamos estas opciones con tu logo, tus colores y tus productos. Elige la que más
se parezca a tu negocio.»** Cada propuesta se ve sobre el contenido real del dueño: su producto
estrella con su precio, su horario y una historia (si falta un dato, se omite esa muestra, no se
inventa). Botones **«Elegir esta»** y **«Ver otras opciones»** (si el fundador elige ese
formato). Mientras se generan: **«Estamos preparando tus opciones. Te avisamos cuando estén
listas.»** Al elegir: **«Listo. Tus próximas publicaciones usarán este estilo.»** Pensada para el
teléfono; revisión de `ux-designer` antes del PR.

**m-25042563 / m-25042561 / m-25042562 — Plantillas.** En «Crear publicación», **«Plantillas»** lista el kit con
tarjetas **«Ubicación»**, **«Horarios»**, **«Formas de pago»**, **«Contacto»**, **«Menú»**,
**«Íconos para destacados»** y una por producto principal; cada una con **«Crear de nuevo»**. Si
falta el dato: **«Agrega tu dirección en Tu marca para crear esta plantilla.»** con el botón
**«Agregar dirección»** (análogos para horarios, formas de pago y contacto). Ninguna pieza muestra
un dato que el negocio no cargó.

**m-25042564 / m-25042565 — Mural e historias.** Mural de 3×3 en un lienzo de 3240×4320 cortado en 9 piezas
de 1080×1440, con la guía **«Publica primero la pieza 1»** (orden de abajo a la derecha hacia
arriba a la izquierda). Siete historias de 1080×1920 sin precios, con 250 px libres arriba y 300
abajo y el espacio marcado para el sticker de enlace.

**m-25042566 — Ajustes de un toque.** Botones **«Más color»**, **«Otra letra»** y **«Otro fondo»**;
cada uno crea una versión nueva y avisa **«Guardamos esto como una versión nueva. Puedes volver a
la anterior cuando quieras.»**

## Criterio para seguir o parar después del spike (m-25042530)

El fundador lo juzga mirando lado a lado; el spike entrega los renders y los números.

**Sigue el camino de Bianki (Fases 1, 2 y 4)** si se cumplen las tres:
1. Remotion reproduce desde datos 5 piezas de referencia (flyer de un producto, horarios,
   ubicación, formas de pago y una pieza del mural) y el fundador dice «publicable» en al menos 4.
2. Ningún retoque a mano en píxeles: todo sale de tokens + componentes + datos.
3. Cada imagen fija se compone en el perfil de render actual sin pasar el límite de memoria del
   contenedor ni la espera de 10 minutos (tiempo medido por pieza, anotado en `pruebas.md`).

**Sigue la Fase 3 (propuestas de la IA)** si además: entre las propuestas para Polette hay al menos
una que el fundador publicaría sin cambios, y las propuestas se distinguen entre sí a simple vista.
Costo y tiempo del juego de propuestas quedan medidos (no hay tope firmado todavía).

**Se para:**
- Si falla la Fase 3 pero no Bianki: la Fase 3 se aparca; los estilos se cargan a mano por el
  equipo para cada negocio (como Bianki) y se reabre cuando una nueva prueba pase el criterio.
- Si falla Bianki (no se reproduce en Remotion): se para la épica, se vuelve a la Fase 3 de
  m-25017272 con los 7 diseños y se abre el arreglo de «foto reducida» (CAPA-004 A, opción 1).

## Preguntas abiertas para el fundador (no decididas)

1. **Datos mínimos de «Tu marca» para disparar las propuestas** (m-25042552). Propuesta que se le hizo:
   obligatorios nombre + rubro, logo, un producto con foto y precio; colores sacados del logo;
   horarios, dirección y pagos opcionales — si falta uno, se omite esa muestra y esa plantilla.
2. **¿Se bloquea crear imágenes, carruseles, historias y plantillas hasta elegir un estilo, o se
   usa uno provisional?** (preguntado, sin respuesta).
3. **Tres propuestas + «Ver otras opciones», o cuatro** (él dijo cuatro; se sugirió tres).
4. **Recorte del producto**: qué proveedor o modelo (m-25042543, tabla de opciones).
5. **¿Generar propuestas y el kit de inicio consume creaciones?**, y el costo de plataforma por
   marca.
6. **Qué pasa con las publicaciones ya aprobadas o programadas** cuando el dueño cambia de estilo o
   vuelve a uno anterior (m-25042558).
7. **Negocios que ya usan Qualify**: cómo reciben su estilo (paso único, m-25042560).

## Fuera de alcance

- Editor libre para mover elementos a mano.
- Video: las capas de video y los efectos (m-25026581) siguen su épica; usarán los tokens del
  sistema más adelante.
- Publicar destacados por API (lo decide m-25017301).
- Generar el estilo en el Alta (decisión S2).
- Un proveedor de recorte antes de la decisión de m-25042543.
- Cambiar precios o planes.
