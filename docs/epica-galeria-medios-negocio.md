# Épica — Galería con fotos y videos del negocio para crear publicaciones con lo elegido

`[PROPUESTA 2026-11-05 · épica m-24955913]` · Dueño del documento: product-owner.
**Nombre:** la pantalla antes «Tus productos» / «Catálogo» se llama **«Galería»** en el menú
(primera entrada de «Publica», decisión del fundador 2026-11-05). Su ruta sigue siendo `/catalog`
y el módulo de código sigue siendo `catalog`.
Decisiones del fundador firmadas el 2026-11-05 (§2). Una decisión de arquitectura queda abierta
para `principal-architect` (§4) y dos preguntas menores para el fundador (§8).

## 1. Por qué

**Pedido del fundador (2026-11-05):** «necesitaba cargar clips y fotos de mi negocio… mi
catálogo debería estar separado de piezas por aprobar… desde catálogo selecciono contenido para
generar piezas y después aprobarlas».

Para el dueño de un local de comida (Bianki, Polette) o de una agencia, las fotos y videos
reales de su local, su equipo, su cocina o su proceso son el contenido que más confianza da y
que hoy no tiene dónde guardar en Qualify. Con esta épica:

1. Guarda en **Galería** las fotos y videos de su negocio, separados de sus productos y
   separados de las piezas «Por aprobar».
2. Corta sus videos en partes y quita lo que no sirve.
3. Elige varias fotos y videos (del negocio y de sus productos) y crea con ellos **una**
   publicación, que llega a «Por aprobar». Nada se publica sin su aprobación.

### Lo que hay hoy (leído en disco, `main` en `785e9df9`)

| Qué | Dónde | Estado |
|---|---|---|
| Medios del catálogo | tabla `product_media` (migración `0038`), `product_id NOT NULL` | Solo medios de un producto; no hay dónde poner el local |
| Subida | `CatalogService.add_media` (`packages/api/src/qualify_api/catalog/service.py`) | Foto → JPEG para Instagram; video → `VideoNormalizer.normalize`: H.264, vertical, **≤ 15 s, sin sonido** (`-an`, `MAX_SECONDS = 15.0` en `qualify_creative/video/normalize.py`); clave `uploads/{tenant}/catalog/{product}/…`; máximo 12 por producto |
| Quitar un medio | `CatalogService.remove_media` | Borra la **fila**; el objeto queda en R2 («procedencia de piezas ya hechas») |
| Crear desde el catálogo | `/create?producto=<id>` (m-24842972, `catalog_vm.create_with_product_href`) | Un producto a la vez, validado bajo RLS |
| Formato carrusel (hoy rotulado «Galería» en el generador) | `ContentKind.CAROUSEL`, `SlideSource` (`generated`, `animated`, `existing`, `stock`) | 2–10 diapositivas; ninguna fuente es «foto o video del catálogo tal cual» |
| Borrado en R2 | `ObjectGate.delete_prefix` (ADR 39) | Solo por debajo de `PURGEABLE_ROOTS` (hoy solo `generated/`); una raíz nueva es una decisión revisada |
| Purga al desconectar | migración `0106_connection_purge.py` | Protege `product_media.object_key`; una tabla nueva de medios debe sumarse a esa lista |
| Cupo de video | m-24921139 (segundos de video al mes) | Cuenta video **generado** |

Fuera de esta épica (ya en curso en otro PR): renombrar «Tus productos» → «Galería» y subirlo
al inicio de la zona «Publica». PR #483 (categorías de productos) toca `catalog_page.py` y
`catalog_state.py`: las historias de pantalla se basan en `main` después de ese merge.

## 2. Decisiones firmadas (fundador, 2026-11-05)

| # | Decisión | Qué cambia en las historias |
|---|---|---|
| D1 | Los videos **del negocio** se guardan **con su sonido**; si se usa o no se decide al crear la publicación | La normalización del negocio no lleva `-an` (AAC); `/create` ofrece el interruptor de sonido |
| D2 | Duración máxima del video del negocio: **60 s**. Qualify elige el tramo al crear cuando el formato pide menos | Subida corta a 60 s; el generador elige el tramo (regla determinista, §5 CM-6) |
| D3 | Los videos **de producto** siguen como hoy: ≤ 15 s, sin sonido | Ningún cambio en `add_media` de productos |
| D4 | En Galería el dueño **corta** un video del negocio en partes y **quita** partes; lo quitado se borra de verdad (no se recupera tras confirmar). Cada parte que queda es un medio propio | Historias CM-3 y CM-4; el original y lo quitado salen de R2 al confirmar |

## 3. Reglas que la épica respeta

- **Aislamiento por negocio:** toda tabla nueva lleva `tenant_id` + RLS con la política
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` en la misma revisión; acceso solo
  por `tenant_session`.
- **Procedencia:** cada parte cortada guarda el id del video de origen, sus puntos de corte y la
  versión del proceso; cada pieza guarda qué medios usó, qué tramo y si llevó sonido.
- **Asistido, nunca autónomo:** la publicación queda en «Por aprobar»; no se programa ni se
  publica sola.
- **Datos del cliente y proveedores:** los medios del negocio no se mandan a un modelo
  generativo (BytePlus) en esta épica: el carrusel usa los archivos tal cual y Claude solo
  escribe el texto a partir del contexto de la marca.
- **R2:** sin objetos huérfanos al cortar o quitar; las piezas guardan su propia copia para que
  borrar en Galería no rompa una pieza ya hecha (y esa copia sigue ADR 39, 90 días).

## 4. Decisión de arquitectura abierta (para `principal-architect`)

**¿Dónde viven los medios del negocio?** Bloquea CM-1. Las dos opciones:

| Opción | Qué es | A favor | En contra |
|---|---|---|---|
| A. `product_media.product_id` opcional | Columna `scope` (`product` / `business`) con `CHECK` (negocio ⇔ sin producto) | Una sola tabla, reutiliza `MediaRecord`, la purga de `0106` ya la protege | Cada lectura de productos (Galería, menú de WhatsApp, selector de `/create`, orden de productos) debe filtrar `product_id IS NOT NULL` o mostrará fotos del local como de un producto; el índice `(product_id, position)` y el `ON DELETE CASCADE` cambian de sentido; contradice la nota de `0066` («`product_media` ES el producto del cliente») |
| B. Tabla nueva `business_media` | Misma forma que `product_media` sin `product_id`, más `has_audio`, `source_media_id` (sin FK, el original se borra), `cut_start_ms`, `cut_end_ms`, `pipeline_version`; RLS en la misma revisión | Nada de lo que hoy lee productos cambia; la procedencia del corte tiene su sitio; reglas propias (60 s, sonido, sin «principal») | Una unión de dos tablas en la selección (CM-5) y en `/create` (CM-6); sumar la tabla a la lista protegida de `0106` |

**Recomendación del product owner:** B — el riesgo de A es que una foto del local aparezca como
foto de un producto en el menú de WhatsApp de un cliente. Decide el arquitecto.

El mismo arquitecto decide además, antes de CM-1 y CM-3:

1. **Borrado en R2 (D4):** el original cortado y las partes quitadas deben salir de R2. Hoy la
   puerta solo borra por debajo de `generated/` (ADR 39). Hace falta una raíz o un método nuevo
   (por ejemplo, prefijo `t/{tenant}/catalog/business/{media_id}/`) — es una decisión revisada
   de ADR 39 y del test que fija los métodos de la puerta.
2. **Subida de un video de 60 s:** un minuto grabado en un teléfono pesa 100–400 MB (4K HEVC)
   `[H]`. Hoy `normalize` recibe los bytes en memoria dentro del proceso de Reflex y transcodifica
   en línea, en un servidor compartido con Pedidos. ¿Tope de tamaño de archivo (propuesta
   300 MB) y normalización en segundo plano (cola de `creative-worker`, ADR 41) o en línea?
3. **Quitar un medio entero del negocio:** si las piezas guardan copia propia (CM-6), «Quitar»
   puede borrar también el objeto (hoy los productos dejan el objeto). Propuesta: sí.

## 5. Historias

Orden de trabajo: CM-1 → CM-2 → CM-3 → CM-4 → CM-5 → CM-6 → CM-7 → CM-8. CM-3 puede ir en
paralelo con CM-2; CM-6 en paralelo con CM-5.

### CM-1 — Galería (servidor): guardar fotos y videos del negocio sin producto — m-24955918

- **Historia:** Como dueño de un local de comida, quiero guardar fotos y videos de mi local que
  no son de un producto, para tenerlos listos al crear publicaciones.
- **Área:** creative-engineer (módulo `catalog`, migración). **P1 · M.** **Depende de:** la
  decisión de §4 (opción A/B, raíz de borrado, subida de 60 s).
- **Criterios de aceptación:**
  - [ ] Migración reversible (`qualify-migration`) con la opción que firme el arquitecto;
    `tenant_id` + RLS NULLIF en la misma revisión; grants a `qualify_app`/`qualify_admin` como
    `product_media`; la tabla o columna nueva entra en la lista protegida de la purga de
    conexiones (`0106`).
  - [ ] `CatalogService` gana `list_business_media`, `add_business_media`,
    `remove_business_media` bajo `tenant_session`; un negocio nunca ve ni borra medios de otro
    (test con dos tenants).
  - [ ] Foto del negocio: misma normalización que la de producto (JPEG para Instagram).
  - [ ] Video del negocio (D1, D2): H.264, vertical, **con sonido AAC**, cortado a **60 s** desde
    el inicio; se guarda `has_audio` (un video sin pista de sonido queda `false`) y la duración
    real. El video de producto no cambia (≤ 15 s, sin sonido): test que lo fija.
  - [ ] Si el original dura más de 60 s, la respuesta lo indica para que la pantalla avise.
  - [ ] Tope por negocio: 60 medios `[H]`, con `CatalogError` y su texto.
  - [ ] Ningún medio del negocio aparece en las lecturas de productos (Galería, menú de
    WhatsApp, selector de producto en `/create`): test.
  - [ ] `just ci-test` y `just test-db` verdes.
- **Fuera de alcance:** cortar (CM-3), elegir el tramo (CM-6), etiquetar o describir con IA.

### CM-2 — Galería (pantalla): «Fotos y videos de tu negocio» con subir, ver y quitar — m-24955919

- **Historia:** Como dueño de un local, quiero subir desde el teléfono fotos y videos de mi
  negocio en Galería, para mostrar mi local real en mis publicaciones.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-1; PR #483 mergeado (mismos
  archivos).
- **Criterios de aceptación (texto exacto):**
  - [ ] En la pantalla **Galería** (`/catalog`), una sección junto a tus productos (arriba) con título **«Fotos y videos de tu
    negocio»** y la línea **«Muestra tu local, tu equipo y cómo trabajas. Úsalas en tus
    publicaciones.»**
  - [ ] Botón **«Agregar fotos o videos»**; en el teléfono abre la cámara o las fotos del teléfono (el
    selector del sistema); acepta varias a la vez.
  - [ ] Mientras procesa un video: **«Preparando tu video…»**.
  - [ ] Video de más de 60 s: **«Guardamos el primer minuto de tu video. Si quieres otra parte,
    puedes cortarlo aquí mismo.»**
  - [ ] Vacío: **«Todavía no tienes fotos ni videos de tu negocio. Sube algunas de tu local, tu
    equipo o tu trabajo.»**
  - [ ] Cada medio muestra su miniatura (los videos con su duración, p. ej. «0:42») y la acción
    **«Quitar»** con la confirmación **«¿Quitar este video de tu Galería? Las publicaciones que
    ya hiciste no cambian.»** (o «esta foto»).
  - [ ] Errores con los textos que ya existen (archivo ilegible, demasiado pesado, tope),
    sin códigos ni inglés (`qualify-copy-es`).
  - [ ] A 375 px de ancho: botones de 44 px, sin desplazamiento horizontal (`qualify-ux`);
    revisión local de `ux-designer` antes del PR.
  - [ ] `just ci-test` verde (tests de view-model de los textos y estados).
- **Fuera de alcance:** cortar (CM-4), elegir para una publicación (CM-5), ordenar a mano.

### CM-3 — Galería (servidor): cortar un video del negocio en partes y borrar lo quitado — m-24955923

- **Historia:** Como dueño de un local, quiero cortar mi video en partes y quitar lo que no
  sirve, para quedarme solo con los momentos buenos, cada uno listo para usar.
- **Área:** creative-engineer (servicio de corte con FFmpeg, ya aceptado en el stack). **P1 · M.**
  **Depende de:** CM-1 y la decisión de borrado en R2 (§4.1).
- **Entrada:** el id del video del negocio y una lista ordenada de tramos `[inicio, fin]` (ms)
  marcados «se queda» o «se quita». Mínimo 3 s por parte que se queda `[H]` (lo que acepta
  Instagram en un video).
- **Criterios de aceptación:**
  - [ ] **Precisión:** cada parte empieza y termina a ≤ 0,1 s del punto elegido (se
    recodifica; no se corta en el fotograma clave más cercano). Test con un video de prueba
    con contador de fotogramas, medido con `ffprobe`.
  - [ ] **Sonido:** cada parte conserva el sonido del original (D1), sincronizado.
  - [ ] **Procedencia:** cada parte guardada lleva `source_media_id`, `cut_start_ms`,
    `cut_end_ms` y `pipeline_version`; la procedencia sobrevive al borrado del original.
  - [ ] **Idempotencia:** el mismo pedido (mismo origen + mismos tramos, clave de
    idempotencia) repetido o reintentado da las mismas partes, sin duplicados ni cobro de
    proceso doble.
  - [ ] **Orden seguro:** primero se escriben las partes en R2 y sus filas; solo cuando están
    confirmadas se borran de R2 el original y los tramos quitados. Si algo falla antes, el
    original queda intacto y se borran los archivos de partes a medio hacer. **Ningún objeto
    huérfano:** test que lista el prefijo del medio en el almacenamiento falso tras éxito, fallo
    y reintento.
  - [ ] **Cancelar** (no confirmar) no toca el original ni escribe nada.
  - [ ] Si el original ya se usó en una pieza, la pieza no se rompe (usa su copia, CM-6).
  - [ ] Aislamiento: no se puede cortar un video de otro negocio (test).
  - [ ] `just ci-test` verde; el test de FFmpeg se salta con aviso si no hay binario.
- **Fuera de alcance:** recortar el cuadro, filtros, velocidad, música, volver a unir partes.

### CM-4 — Galería (pantalla): cortar un video con «Cortar aquí» y «Quitar esta parte» — m-24955924

- **Historia:** Como dueño de un local, quiero cortar mi video desde el teléfono mirando una
  línea de tiempo, para no necesitar otra aplicación.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-2, CM-3.
- **Flujo (una decisión por paso):** en un video del negocio, **«Cortar video»** → pantalla
  **«Corta tu video en partes»** con el video, la línea de tiempo y la línea de reproducción.
  1. Ayuda: **«Mueve la línea hasta donde quieres cortar y toca «Cortar aquí».»**
  2. **«Cortar aquí»** divide la parte en la que está la línea; las partes se ven numeradas en
     la línea de tiempo («Parte 1», «Parte 2»…).
  3. Tocar una parte la selecciona; **«Quitar esta parte»** pide **«¿Quitar esta parte? No se
     puede recuperar.»** con **«Quitar»** / **«Volver»**.
  4. **«Guardar partes»** pide **«Vamos a guardar N partes y borrar el video original. ¿Seguimos?»**
     con **«Guardar»** / **«Volver»**. Al terminar: **«Listo: tu video quedó en N partes.»**
  5. **«Cancelar»** con cambios sin guardar pide **«¿Salir sin guardar? Tu video queda como
     estaba.»**; sin cambios, sale directo.
- **Criterios de aceptación:**
  - [ ] Los textos de arriba, exactos.
  - [ ] Parte de menos de 3 s: **«Cada parte debe durar al menos 3 segundos.»** y no deja
    guardar.
  - [ ] Si se quitaron todas las partes, «Guardar partes» no está disponible y se lee **«Deja al
    menos una parte o cancela.»**
  - [ ] Funciona con el dedo a 375 px (arrastrar la línea, botones de 44 px); se puede adelantar
    y retroceder por fotogramas con dos botones para afinar el punto.
  - [ ] Cada parte guardada aparece como un medio propio en «Fotos y videos de tu negocio»,
    en orden, y el original desaparece.
  - [ ] Revisión local de `ux-designer`; `just ci-test` verde.
- **Fuera de alcance:** las mismas que CM-3; cortar videos de producto.

### CM-5 — Galería (pantalla): elegir varias fotos y videos y «Crear publicación con estas» — m-24955926

- **Historia:** Como dueño de un local, quiero elegir varias fotos y videos de mi negocio y de mis
  productos, para crear una sola publicación con ellos.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-2.
- **Criterios de aceptación:**
  - [ ] Botón **«Elegir para una publicación»** en Galería; al tocarlo, las miniaturas se
    pueden marcar, en dos grupos: **«De tu negocio»** y **«De tus productos»** (las fotos y videos
    de cada producto, con su nombre).
  - [ ] Barra fija abajo con **«N elegidas»** y **«Crear publicación con estas»**; **«Cancelar»**
    sale sin elegir nada.
  - [ ] Hasta 10 (lo que acepta Instagram en un carrusel); la undécima: **«Puedes elegir hasta
    10.»**
  - [ ] El orden de la publicación es el orden en que el dueño los tocó (se ve un número en
    cada miniatura).
  - [ ] «Crear publicación con estas» abre `/create?medios=<lista>` (cada elemento dice si es
    del negocio o de un producto); el enlace de producto único (`?producto=`) sigue funcionando.
  - [ ] A 375 px, la barra no tapa el contenido; revisión local de `ux-designer`;
    `just ci-test` verde.
- **Fuera de alcance:** guardar la selección para después; elegir piezas ya hechas.

### CM-6 — Generador (servidor): crear una publicación con los medios elegidos — m-24955927

- **Historia:** Como dueño de un local, quiero que Qualify arme la publicación con las fotos y
  videos que elegí, tal cual, para mostrar mi negocio real.
- **Área:** creative-engineer. **P1 · L.** **Depende de:** CM-1 (y CM-3 para partes cortadas).
- **Propuesta:** formato por defecto **carrusel** (`ContentKind.CAROUSEL`, hoy rotulado «Galería» en el generador) con una fuente de
  diapositiva nueva «medio del catálogo» (`SlideSource`), una diapositiva por medio, en el orden
  elegido; con un solo medio, una publicación de imagen o de video. Claude escribe el texto con
  el contexto de la marca (sin mandar los archivos a un modelo).
- **Criterios de aceptación:**
  - [ ] Valida cada medio bajo RLS: uno de otro negocio, borrado o mal formado se descarta sin
    error (como `?producto=` hoy, m-24842972).
  - [ ] **Tramo (D2):** si el formato pide menos que la duración del video, Qualify elige un
    tramo con una regla determinista y documentada (primera versión: el tramo de la duración
    pedida que empieza en el segundo 0, o el siguiente si el primero es de menos de 3 s `[H]`); el
    tramo se guarda en la pieza. En el carrusel un video de hasta 60 s entra entero.
  - [ ] **Sonido (D1):** la pieza respeta lo que el dueño elige en `/create` (con o sin el
    sonido de sus videos); un video de producto siempre va sin sonido. Si el formato lleva voz
    generada, el sonido del video se apaga y la pantalla lo dice (CM-7).
  - [ ] **Copia propia:** los archivos que usa la pieza se copian a `generated/{draft_id}/`,
    así ADR 39 los borra con la pieza y quitar un medio en Galería no rompe la pieza.
  - [ ] **Procedencia:** la pieza guarda la lista de medios (tipo, id, tramo, sonido) y la
    versión del armado.
  - [ ] La pieza termina en «Por aprobar» (`/drafts`) y no se programa sola.
  - [ ] Reusar fotos y videos propios **no** descuenta segundos de video del cupo (m-24921139);
    si cuenta como una creación del mes es la pregunta P1 del fundador (§8).
  - [ ] `just ci-test` verde.
- **Fuera de alcance:** elegir el tramo con IA (medición de `data-scientist-fde` antes);
  montaje de varios videos en un solo video vertical (Plantilla o Video por partes, siguiente
  paso); usar los medios del negocio como referencia de Seedance (manda datos del cliente a
  BytePlus).

### CM-7 — Generador (pantalla): `/create` abre con lo elegido y pregunta por el sonido — m-24955928

- **Historia:** Como dueño de un local, quiero ver lo que elegí al llegar a «Crear» y decidir si
  se oye el sonido de mis videos, para no repetir pasos.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-5, CM-6.
- **Criterios de aceptación:**
  - [ ] `/create?medios=…` salta la elección de producto y muestra las miniaturas elegidas en
    orden, con **«Cambiar»** que vuelve a Galería con la selección.
  - [ ] Si hay al menos un video del negocio con sonido: interruptor **«Usar el sonido de tus
    videos»** (estado inicial: pregunta P2 del fundador, §8).
  - [ ] Si el formato lleva voz: **«Esta publicación lleva voz, así que tus videos van sin
    sonido.»**
  - [ ] Si se descartó algún medio (borrado o de otro negocio): **«Uno de los medios que
    elegiste ya no está en tu Galería.»**
  - [ ] Al terminar, el mismo aviso que hoy y el enlace a «Por aprobar».
  - [ ] Si el fundador aprueba P3 (§8): el formato carrusel se rotula **«Carrusel»** en todo el
    generador (solo textos; `ContentKind.CAROUSEL` no cambia), para no confundirlo con la
    pantalla Galería.
  - [ ] Revisión local de `ux-designer`; `just ci-test` verde (test del view-model con
    `?medios=` válido, ajeno y mal formado).
- **Fuera de alcance:** editar el orden dentro de `/create` (se cambia en Galería).

### CM-8 — Pruebas: de Galería a «Por aprobar» con fotos y videos del negocio (E2E) — m-24955929

- **Historia:** Como equipo, queremos una prueba de punta a punta del camino completo, para no
  romperlo sin enterarnos.
- **Área:** reflex-ui-engineer (Playwright, `tests/e2e`, nicho locales de comida). **P2 · M.**
  **Depende de:** CM-1…CM-7.
- **Criterios de aceptación:**
  - [ ] El recorrido: subir una foto y un video de 20 s con sonido en «Fotos y videos de tu
    negocio» → cortar el video en 3 partes y quitar la del medio (confirmando) → elegir la foto,
    la parte 1 y una foto de producto → «Crear publicación con estas» → con sonido → la pieza
    aparece en «Por aprobar» con 3 diapositivas en ese orden.
  - [ ] Comprueba en el almacenamiento de prueba que el original y la parte quitada ya no
    están, y que la pieza tiene su copia.
  - [ ] Un segundo negocio no ve los medios del primero (ni en Galería ni por `?medios=`).
  - [ ] Ningún proveedor real pagado: generación de texto simulada.
  - [ ] Corre a 375 px de ancho.

## 6. Impacto en R2 (almacenamiento)

Cálculo `[H]` sobre parámetros del disco (`-crf 23 -preset veryfast`, tope 1080×1920) y el
precio público de R2 Standard (US$0,015 por GB al mes, `[S]`, no verificado hoy):

| Qué | Peso por archivo | Comentario |
|---|---|---|
| Video de producto, 15 s, sin sonido (hoy) | ~6–11 MB | Sin cambio |
| Video del negocio, 60 s, con sonido | ~22–45 MB (video 3–6 Mbps + AAC 128 kbps ≈ 1 MB) | 4× la duración de un video de producto |
| Partes cortadas | suman menos que el original | El original y lo quitado se borran (D4): no hay doble guardado |
| Copia en la pieza (CM-6) | lo usado | Se borra con la pieza a los 90 días (ADR 39) |

Un negocio con 20 videos de 60 s guarda ~0,45–0,9 GB → **~US$0,01–0,02 al mes** `[H]`. No mueve
el costo por negocio; lo que sí pesa es la **subida** (100–400 MB por video en el teléfono) y la
**CPU** de transcodificar un minuto en el servidor compartido: por eso la decisión §4.2.

## 7. Prioridad y razón

1. **CM-1 + CM-2** — el fundador no puede guardar hoy los videos de su local; es la base de todo.
2. **CM-5 + CM-6 + CM-7** — el camino que pidió: elegir en Galería y que la pieza llegue a «Por
   aprobar».
3. **CM-3 + CM-4** — cortar y quitar (pedido explícito, va después de la subida).
4. **CM-8** — cierra la épica.

Ninguna historia toca la revisión de la app de Meta: es Instagram/Facebook con lo que ya está
aprobado.

## 8. Preguntas para el fundador

- **P1.** Una publicación armada solo con tus fotos y videos (sin imagen ni video generado),
  ¿cuenta como una creación del mes? Recomendación: sí cuenta como creación (el texto se genera)
  pero no descuenta segundos de video.
- **P2.** El interruptor «Usar el sonido de tus videos», ¿empieza encendido o apagado?
  Recomendación: apagado, como hoy (la música se pone en Instagram), y el dueño lo enciende.

- **P3. Dos cosas llamadas «Galería».** El generador ya rotula «Galería» al formato carrusel
  («Armando tu galería…», «Úsalo en un Clip o en una Galería», `creative_state.py`). Con la
  pantalla también llamada Galería, «Crear publicación con estas» desde Galería que arma «una
  Galería» confunde. Recomendación: renombrar el formato a **«Carrusel»** en el generador (un
  cambio de textos, sin tocar `ContentKind.CAROUSEL`), dentro de CM-7.

## 9. Tickets

| Id | Ticket | Área |
|---|---|---|
| Épica | m-24955913 | — |
| CM-1 | m-24955918 | creative-engineer |
| CM-2 | m-24955919 | reflex-ui-engineer |
| CM-3 | m-24955923 | creative-engineer |
| CM-4 | m-24955924 | reflex-ui-engineer |
| CM-5 | m-24955926 | reflex-ui-engineer |
| CM-6 | m-24955927 | creative-engineer |
| CM-7 | m-24955928 | reflex-ui-engineer |
| CM-8 | m-24955929 | reflex-ui-engineer |
