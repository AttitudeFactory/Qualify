# Spike: sistema visual de la marca como datos + Remotion

`[SPIKE 2026-11-17 · m-25042530 · épica m-25017272]` · Rama `spike/m-25042530-sistema-visual-marca`.
Nada de esto está conectado a la app: sin migración, sin producción, sin R2. Las imágenes viven solo en
disco local: `/Users/herwin/dev/qualify-eval-out/sistema-visual/`.

## 1. Pregunta y respuesta corta

1. ¿Puede un **sistema visual por marca guardado como DATOS** (no código), dibujado por Remotion,
   producir piezas al nivel del set de Bianki de noviembre (hecho con HTML + Chrome)?
   **Sí.** El sistema de Bianki, transcrito a un JSON, reproduce sus 8 piezas:
   - horario y pagos salen **idénticos píxel a píxel**;
   - los 4 shawarmas y el combo difieren en menos del 0,5 % de los píxeles;
   - la historia difiere en un 0,7 % de bordes, porque el original es JPG.
2. ¿Puede la IA, sola, **proponer** ese sistema para una marca desde cero?
   **Sí, con matices.** Una sola llamada (US$1,76) dio 3 propuestas válidas y distintas para Polette, sin
   tocar el JSON. Una de ellas se acerca a la vara de Bianki. Lo que falta para igualarla es el recorte
   del producto (§4.4), no el sistema.

## 2. El esquema `BrandVisualSystem` v0

- **Fuente:** el modelo pydantic `packages/creative/src/qualify_creative/brand_system/model.py`.
- **Esquema JSON exportado:** `brand_visual_system.v0.schema.json`, junto al modelo.

| Parte | Qué guarda |
|---|---|
| Identidad y versión | `id` estable, `version`, `parent_version`, `name` (en español, para el dueño), `style_family`, `rationale`, `provenance` (transcrito, propuesta de IA o edición del dueño; modelo y prompt) |
| `colors` | **Roles**, no una paleta: background, background_alt, background_edge, surface, on_surface, ink, accent, on_accent, shadow, shadow_deep, pop. Cada componente pinta con un rol o con un hex literal (el tono puntual de una marca, como el rojo de la cinta de Bianki) |
| `typography` | display / body / label: familia de Google Fonts o **archivo propio de la marca** (`src`), peso, espaciado, interlínea, mayúsculas |
| `background` | base (sólida, radial, lineal) + hasta 4 capas parametrizadas: rays, rings, dots, stripes, grid, waves, pattern_image (la trama de la marca), blobs, grain, confetti |
| `shapes` | radio, inclinación, sombra (dura, suave o ninguna) |
| `components` | Variantes de la **biblioteca de componentes de firma**: etiqueta (ceja), titular a dos colores, precio (banderín, placa, círculo, tiquete o simple), sello, cinta, marco de producto (recorte con halo o con sol, disco, arco, redondeado, mancha), tarjeta de datos, logo, destello, texto con chips |
| `tone` | La voz en una línea |
| `recipes` | Composiciones con huecos: `product_hero`, `combo`, `hours`, `payments`, `contact`, `story`. Cada receta tiene un formato y una lista de bloques (`photo`, `logo`, `product`, `stamp`, `text_stack`, `ticker`, `info_list`, `icon_feature`, `sun`, `glow`, `sparkle`), con su caja en fracciones del lienzo y la ruta al hueco que llena |

**Los huecos** son los datos del dueño, en un JSON aparte: producto, precio, horario, dirección, fotos.
Usan un marcado mínimo:

- `[[300 g]]`: chip;
- `**Av. …**`: texto destacado;
- `__«La Machiri»__`: negrita que no se parte;
- `<<a>>`: la parte pequeña de un banderín;
- `|`: corte forzado del titular.

**Versionado:** cada cambio es una versión nueva con `parent_version`. Volver atrás es marcar otra
versión como vigente; nunca se edita una versión.

**Motor:** la plantilla Remotion `brand_still`:

- `packages/render/src/templates/brand_still/BrandStill.tsx`;
- composiciones `brand-still-v0--{feed,square,story}`;
- manifiesto en `packages/render/templates/brand_still/manifest.json`.

Dibuja cualquier receta de cualquier sistema. **Una marca nueva es un JSON nuevo, no React nuevo**:
Polette se dibujó sin una línea de código propia.

- **Medida del texto:** cada línea se mide con la fuente real (canvas) y se achica hasta caber en su
  ancho.
- **Precio:** se imprime entero o no se imprime, y el motor lo avisa.
- **Altura:** un bloque de texto que no cabe en su caja se escala completo.

Para renderizar sin el servidor: `node scripts/brand-still-batch.mjs <jobs.json>` (un solo bundle).
Las hojas de contacto también son una composición de Remotion (`brand-still-contact-sheet`).

## 3. Fase 1: Bianki cargado tal cual

**Fuente.** El sistema no se rediseñó: se **transcribió** el CSS de `gen.py` y `stories.py`, de la
carpeta `_fuentes-para-regenerar/`:

- los tokens, las fuentes woff2 propias, cada componente y cada coordenada de cada pieza;
- los recortes, las fotos reales y el logo, de `a/`.

`gen.py` dice seguir el lenguaje de las pantallas 2 y 3 del local (Pedidos `64aaee5`). Las piezas de
Instagram salen de `gen.py`, así que ese archivo es la autoridad. No hubo llamada a IA.

**Archivos** (en `packages/api/evals/sistema_visual/bianki/`):

- el sistema: `system.v1.json`;
- los huecos: `content.*.json`.

**Resultado:** imágenes en `…/sistema-visual/bianki/` y vista general en
`…/bianki/vista-general-bianki.jpg` (original arriba, Qualify abajo).

| Pieza | Diferencia media por canal | Píxeles con diferencia > 32 |
|---|---|---|
| Horarios | 0,01 | 0,00 % |
| Métodos de pago | 0,02 | 0,00 % |
| Combo mixto | 0,42 | 0,29 % |
| Shawarma de pollo / carne / mixto / cerdo | 0,54–0,59 | 0,44–0,46 % |
| Historia «Abrimos» | 1,18 | 0,72 % (el original es JPG) |

**Diferencias que quedan, dichas con honestidad:**

- **Sello «300 gramos» y línea de ingredientes:** corridos un subpíxel. El sello escala sus anillos
  con el diámetro (12 px a 230 px de diámetro), en vez de los 12 px fijos de `gen.py`.
- **Historia:** la «a» pequeña del banderín lleva 0,25 em de margen; el original lleva 0,3 em.
- **Placement del recorte por producto:** viaja en los huecos (`product.box`), como en el `GEO` de
  `gen.py`. En producción saldría del recuadro del recorte.
- **Dato a revisar:** las piezas dicen 4:00 a 11:00 pm, como el set original. La página web de Bianki
  dice 4:00 pm a 12:00 am (`bianki-site/src/datos/faq.ts`). No lo corregí, porque el encargo era
  reproducir el set.

**Defectos del port encontrados y corregidos en el camino:**

1. El ajuste de ancho achicaba los banderines, y el original deja salir las puntas del lienzo.
2. Un bloque de texto con la caja corta se escalaba al 0,98.
3. La nota usaba 0,1 em de espaciado en vez de 0,16 em.
4. El chip usaba peso 800 en vez de 900.

## 4. Fase 2: Polette desde cero, solo IA

### 4.1 Qué datos recibió el modelo (y qué faltaba)

Solo lo que un cliente tendría después de completar «Tu marca»
(`packages/api/evals/sistema_visual/polette/brand_input.json`):

| Dato | Fuente | Nota |
|---|---|---|
| Nombre, rubro, `@polette.sc` | Pedidos `docs/marca.md`, semilla `backend/app/semilla.py` | |
| Logo | Pedidos `frontend/public/marca/polette/logo.svg` | El de `docs/marca/` trae un fondo violeta pegado; se usó el transparente. Al modelo se le mostró rasterizado (conversión, no composición) |
| Colores (9) y tipografías (Peralta, Sour Gummy) | Brandboard (`docs/marca.md` y el PDF de 58 páginas) | |
| Productos y precios | Semilla de Pedidos | Sunday Fruit (1,99 USD, 150 g), Bowl de yogurt (3,50 USD), Combo Dúo (6,00 USD) |
| Fotos | PDF del brandboard, páginas 1 y 53 | Copa sobre fondo violeta y cono en la mano. **Son fotos de presentación, no fotos del local, y ninguna es recorte** |
| Horario | Pedidos `docs/pantallas-publico.md` | «4 pm a medianoche». **Supuesto**: el documento no dice los días ni distingue tienda |
| Dirección | Pedidos (el Combo Vecino dice «el local de al lado» de Bianki) | **Inferida**: Korner Club, Paramillo |
| Pagos | `README.md` de Pedidos | Bolívares, dólares, pesos, USDT |

**Faltaba:** foto de producto recortada, fotos reales del local de Polette, horario confirmado y
número de WhatsApp.

### 4.2 La llamada

- **Script:** `propose.py`, con `claude-fable-5-2` (el más capaz que permite la llave).
- **Llave:** no hay llave de evaluación de Anthropic, así que se usó `QUALIFY_ANTHROPIC_API_KEY`.
- **Corridas:** **1**. 17.051 tokens de entrada + 40.588 de salida = **US$1,76**, 423 s.
- **Validación:** 3 de 3 propuestas válidas contra el esquema a la primera.
- **Ediciones:** ninguna entre el JSON y el render.
- **Salidas:** `polette/out/20261117T044842Z/`.
- **Bitácora:** [SISVIS-001](modelos-generativos/pruebas.md#sisvis-001).

Imágenes: `…/sistema-visual/polette/propuesta-{1,2,3}/{producto-estrella,horario,historia}.png`.
Vista general: `…/polette/vista-general-polette.jpg`.

### 4.3 Juicio de cada propuesta frente a la vara de Bianki

1. **«Violeta pop»** (pop de alto contraste: rayos violeta, trama de frutas, precio en banderín
   naranja, sello estrellado).
   - Es la más cercana a Bianki: jerarquía fuerte, titular a dos colores bien medido y precio
     legible.
   - Se ve como una marca y no como «una foto con una banda».
   - Debajo de Bianki porque el producto vive en un disco a media página y no domina el lienzo como
     el recorte del shawarma.
   - El horario es correcto, pero le sobra aire abajo.
2. **«Crema y mora»** (editorial cálido: crema con ondas, foto en arco, precio en placa rosada).
   - Limpia y coherente, pero tímida: titulares y precio chicos, mucho vacío.
   - La historia termina en medio sol cortado que no aporta.
   - Es la más «de catálogo» y la más lejos de la energía de Bianki.
3. **«Fiesta de frutas»** (lúdico: fondo rosado con la trama y confeti, foto en mancha, íconos).
   - Usa más recursos de la marca (trama, colores secundarios) y la historia con la foto enmarcada
     funciona.
   - El rosado con trama más el confeti carga el fondo.
   - En el producto estrella la descripción queda chica.

Ninguna rompe una regla dura: precio entero, zonas seguras de la historia respetadas, español sin
anglicismos en lo que escribió el modelo.

Dos anglicismos aparecen, pero **son míos**, en los huecos: «crema soft» viene del texto del producto
en Pedidos y «toppings» lo puse yo en la cinta. Esto muestra que el contenido del dueño también
necesita pasar por la revisión de `qualify-copy-es`.

### 4.4 Imágenes de producto: lo que se hizo y lo que haría falta

**Lo que se hizo:** Polette no tiene recortes. La foto del brandboard va dentro del marco que eligió
cada propuesta (disco, arco o mancha); el motor convierte `cutout_*` en `disc` cuando la foto no es
recorte. No se generó nada con Seedream: costo 0.

**La diferencia con Bianki** es, sobre todo, este recorte: el shawarma recortado llena el lienzo. Para
llegar ahí hace falta quitar el fondo de la foto del dueño.

> **Corrección (2026-11-26, SISVIS-002).** Lo que decía aquí, que quitar el fondo pedía elegir un
> proveedor nuevo, es falso. El repositorio ya tiene dos caminos sin proveedor nuevo:
>
> - **`LocalBiRefNetSegmenter`** (`packages/creative/src/qualify_creative/photo/segment.py`), sin
>   conectar. Usa el modelo `birefnet-general-lite`, de licencia libre, a través de `rembg`.
> - **El recorte por color de las figuritas** (`chroma_key` en `seasonal/kawaii.py`), en numpy.
>
> Lo que se midió con los dos está en §7.4. La tabla de abajo queda como contexto: la opción A es,
> justamente, el segmentador que ya existe.

| Opción | Cómo | Costo y riesgo |
|---|---|---|
| A. Modelo abierto en nuestro servidor (familia BiRefNet / RMBG) | Un paso de normalización al subir la foto al catálogo, como hoy las fotos y los clips | Sin costo por imagen y sin enviar fotos a terceros. Pide CPU/RAM en el VPS de 4 GB (o en un worker aparte) y revisar la licencia de los pesos (algunos son no comerciales) |
| B. API de quitar fondo (remove.bg, Photoroom, Clipdrop o similar) | Una llamada por foto al subirla, guardada como versión «recorte» | Unos centavos por imagen y buena calidad en comida. Es un proveedor nuevo con datos del cliente: pide tabla de opciones y ADR |
| C. Edición de imagen generativa (Seedream 5.0 con referencia) que aísla el producto sobre un fondo plano, más A o B para el canal alfa | Regenera el producto limpio cuando la foto es mala | Cuesta por imagen y puede alterar el producto real (riesgo de marca). Igual necesita A o B para la transparencia |

## 5. Costo del spike

| Concepto | USD |
|---|---|
| Claude Fable 5.2, 1 corrida de propuestas | 1,76 |
| Seedream / Seedance | 0 (no se llamaron) |
| Renders Remotion (local) | 0 |
| **Total** | **1,76** |

Cada pieza tarda entre 0,8 y 1,6 s en el Mac, ya con el bundle hecho.

> **Corrección (2026-11-26).** En SISVIS-001 no se midió la memoria ni el tiempo dentro de la imagen
> de render de producción (`mem_limit: 1536m`, concurrencia 1). Los segundos de arriba son del Mac,
> fuera de Docker. La medida en la imagen está en §7.5.

## 6. Qué necesitaría producción

1. **Guardado y versiones:**
   - una tabla `brand_visual_systems` con `tenant_id` + RLS, `(system_id, version)` inmutable,
     `parent_version`, `provenance` y el JSON;
   - un puntero «vigente» por negocio.
   - Volver atrás = mover el puntero. Las propuestas no elegidas se guardan.
   - Cada pieza registra `(system_id, version)` con su procedencia.
   - Las fuentes y la trama propias de la marca van a R2.
2. **Dónde se generan las propuestas:** un trabajo en la cola de generación (ADR 41) que se dispara
   al completar «Tu marca».
   - Con Fable 5.2 tarda unos 7 minutos y cuesta unos US$1,8 por marca; hay que medir Opus 5.5 al
     esfuerzo `high`, por costo.
   - Fable no está en las tablas versionadas de precios: hace falta una versión nueva con guardia de
     precio.
   - Las 3 propuestas se muestran dibujadas con el contenido del dueño, y él elige una (aprobación
     humana).
3. **Datos mínimos de la marca para generarlas:**
   - nombre y rubro;
   - logo con transparencia;
   - al menos 1 producto con foto y precio;
   - horario y dirección.
   - Los colores y las tipografías ayudan pero no son obligatorios: sin ellos el modelo los propone.
   - Sin recorte del producto, el tope de calidad baja (§4.4).
4. **El motor:**
   - llevar `brand_still` al servidor de render con su contrato (`CONTRACT.md`, puerto de tipo
     `brand_visual_system`), validación 422 contra el esquema e informe por pieza (avisos de
     precio retirado y bloques escalados);
   - fuentes de marca subidas como recurso;
   - una prueba de regresión que compare los renders de Bianki contra los originales (hoy es un
     script del spike).
5. **El kit inicial** (ubicación, horarios, pagos, contacto, menú, íconos de destacados, un volante
   por producto principal): faltan las recetas `contact`, `menu` e `icon`. El motor ya tiene las
   piezas; son datos nuevos, no React nuevo.
6. **Revisión de texto:** el contenido del dueño (huecos) también debe pasar por `qualify-copy-es`
   (§4.3).

## 7. SISVIS-002 (2026-11-26): propuestas restringidas con negocios reales y pocos datos

**Por qué:** el arquitecto señaló el supuesto más riesgoso: que las propuestas de la IA sirvan
también con datos pobres (Polette traía un brandboard completo). El fundador aprobó la prueba con
un tope de US$15. Detalle de las llamadas en
[SISVIS-002](modelos-generativos/pruebas.md#sisvis-002).

### 7.1 Esquema v1: la IA elige, el equipo dibuja

`model_v1.py` + `recipe_library.v1.json` + `fonts.v1.json`, en
`packages/creative/src/qualify_creative/brand_system/`.

- **La geometría es del equipo:** una biblioteca versionada de recetas (3 de producto 4:5, 4 de
  horario, 4 de historia 9:16), sacada de Bianki y de las 3 propuestas de SISVIS-001. La arma
  `build_library.py`: los hex pasan a roles y las etiquetas a `{{tag}}`.
- **La propuesta solo elige:**
  - colores por rol (único lugar con hex);
  - tipografías de una lista cerrada de 44 familias de Google con ñ, ¿, ¡ y tildes, y sus pesos;
  - una variante de fondo con parámetros acotados;
  - variantes de componentes con colores por rol;
  - una voz, una etiqueta por pieza y hasta 3 frases de cinta;
  - un id de receta por pieza.
- **Lo que la propuesta no escribe:** nombre, precio, descripción y fotos. Se llenan desde los
  datos al componer (`compile_to_v0` y `contents`), y el motor dibuja el documento v0 como siempre.
- **Validación en Python:** esquema, rangos, listas cerradas y contraste por pares. El render
  además informa si perdió un precio o achicó un bloque; esas propuestas se descartan y se cuentan.

### 7.2 Negocios y datos

- **Los eligió el fundador.** Sus nombres quedan solo en disco local; aquí se llaman negocio 1 y
  negocio 2.
- **Negocio 2:** su «Tu marca» guardada es **solo el nombre**:
  - el alta quedó en el paso «redes»;
  - la precarga de Instagram (foto, colores, bio y 24 publicaciones) quedó «propuesta» y nunca
    se aceptó, así que no se usó.
- **Negocio 1** (bar de jugos) tiene logo (una palabra, sin isotipo cuadrado), 3 colores y
  1 producto con precio y 3 fotos de teléfono.
  - Su posicionamiento es una sola línea con la ciudad.
  - No hay tipografías, horario, dirección ni pagos.
- **Ninguno de los dos tiene horario guardado:** la segunda pieza fue un segundo producto. En
  el negocio 1 es el mismo producto con otra foto.
- **Origen de los datos:** producción, solo con `SELECT`; las fotos, de R2 solo con `GET`. Todo queda
  en disco local; la rama solo tiene código y métricas anónimas
  (`packages/api/evals/sistema_visual/sisvis002_metrics.json`).

### 7.3 Resultado

| | Fable 5.2 | Opus 5.5 | SISVIS-001 (Fable, esquema libre) |
|---|---|---|---|
| Costo por ronda de 3 propuestas | US$0,46–0,56 | US$0,13–0,17 | US$1,76 |
| Tiempo por ronda | 103–136 s | 48–68 s | 423 s |
| Válidas a la primera | 6/6 | 6/6 | 3/3 |
| Descartadas en el render | 0 | 1 (bloque de texto achicado a 0,82) | — |

**Gasto total:** US$1,32 de US$15 (Fable 1,02, Opus 0,30).

**Juicio por negocio:**

- **Negocio 1:** con un solo producto y fotos de teléfono, hay piezas que se pueden publicar
  como publicación de producto: «Cartel de sol» (Fable) y «Cartel turquesa» y «Mercado fresco»
  (Opus). Quedan muy por debajo de la vara de Bianki por tres cosas:
  1. La foto con fondo vive en un disco, sin recorte.
  2. El título es el nombre del producto tal como lo escribió el dueño (dos palabras genéricas, en
     minúscula), sin gramaje ni ingredientes.
  3. El logo, que es una palabra ancha, queda chico en cajas pensadas para un isotipo cuadrado.
  - El «segundo producto» repite el mismo producto con otra foto.
- **Negocio 2:** ninguna propuesta sirve. Sin producto, precio ni foto, las piezas son el nombre
  sobre un fondo. **Hallazgo sobre el dato mínimo:** para generar el sistema y el kit hace falta al
  menos 1 producto con foto y precio, y un logo; el nombre solo no alcanza.

**Fable contra Opus:**

- Calidad parecida: las dos dan 3 familias distinguibles por negocio.
- Opus cuesta 3,3 a 3,6 veces menos y tarda la mitad.
- Opus tuvo el único descarte en render: escala tipográfica demasiado grande para la receta.
- Para producción, Opus 5.5 con esfuerzo `high` es suficiente con el esquema restringido.

**Lo que falla y v2 debe cerrar:**

1. **Variedad entre negocios baja:** los dos modelos repiten los mismos tres tríos (pop redondeado,
   cartel condensado, editorial con serifa) en los dos negocios.
2. **Fuga de datos en el texto libre:** el modelo escribió «Hecho en <ciudad>» (sacado del
   posicionamiento) y el nombre del negocio en la cinta. Para el negocio 2 supuso, solo por el nombre,
   que vende bebidas («Frescura en cada sorbo»). La cinta y las etiquetas deberían ser frases sin
   datos, o llenarse desde los datos.
3. **Logos anchos:** las cajas de logo de la biblioteca asumen un logo cuadrado. Hace falta una
   variante por proporción del logo.

### 7.4 Recorte del producto sin proveedor nuevo

- **`LocalBiRefNetSegmenter`:** no se pudo probar sin instalar. Pide `rembg[cpu]` (onnxruntime) y
  los pesos de `birefnet-general-lite`, y ninguno está en el venv ni en `~/.u2net`. Según el
  encargo, no se instaló ni se descargó nada. Es la opción A de §4.4, ya escrita en el repositorio;
  conectarla pide agregar la dependencia y medir la RAM en el servidor. **Medido después en
  RECORTE-001 (§7.6):** recorta muy bien, pero en Linux arm64 muere por memoria aun con 6 GB.
- **Recorte por color de las figuritas** (`kawaii.chroma_key`, numpy, sin dependencias nuevas), sobre
  una foto por negocio (`packages/api/evals/sistema_visual/cutout_probe.py`):

| Foto | Fondo | Resultado | Tiempo | RAM pico del proceso |
|---|---|---|---|---|
| Botellas de jugo, foto de teléfono (negocio 1) | pared y mesón | **No sirve:** borra partes de las botellas | 0,77 s | 193 MB |
| Shawarma sobre blanco (un tenant de prueba, solo para comparar) | blanco plano | **Recorte limpio**, con un halo leve | 0,28 s | 136 MB |
| Miniatura de video con texto (otro tenant de prueba) | oscuro con líneas | No sirve | 0,32 s | 128 MB |

- **Conclusión:** el recorte por color solo sirve con fondo plano (fotos de estudio o generadas, como
  las figuritas). Para fotos de teléfono hace falta el segmentador.
- **Requisitos del recorte por color:** fondo de un solo color conectado al borde. Su rampa
  (`KEY_LOW` 45, `KEY_HIGH` 120) está calibrada para el magenta de Seedream; para blanco funciona
  igual. Habría que agregar una regla que lo descarte si el fondo no es plano; la de las figuritas
  ya existe (`no_character`).

### 7.5 Memoria y tiempo de `brand_still` en la imagen de render de producción

**Cómo se midió:**

- Imagen construida desde la rama con `packages/render/Dockerfile` (arm64, igual que el servidor),
  corriendo con `--memory 1536m --memory-swap 1536m` y `RENDER_CONCURRENCY=1`, como el `mem_limit`
  de `deploy/docker-compose.prod.yml`.
- Las piezas pasan por la API HTTP real: `POST /assets`, `POST /render` y consulta de
  `GET /jobs/{id}` (`packages/api/evals/sistema_visual/render_memprobe.py`).
- La memoria es el `memory.peak` del cgroup del contenedor: Node + Chromium + el bundle cargado.

| Pieza | Tiempo por imagen (3 corridas) | Pico de memoria del contenedor |
|---|---|---|
| Bianki, producto (9:16: foto del local de 650 KB, recorte de 1600 px, 2 fuentes propias) | 2,07 s en frío; 0,83 y 0,78 s después | **327 MB** |
| SISVIS-002, historia (9:16: foto de teléfono 1080×1440, fuentes de Google por red) | 1,29 / 1,17 / 1,57 s | **237 MB** (contenedor recién iniciado; 58 MB antes de la primera pieza) |
| SISVIS-002, producto (4:5) | 1,15 / 1,12 / 1,03 s | menos de 327 MB (el pico no subió) |

- En reposo: 79–103 MB.
- **Margen:** la pieza más pesada usa el 21 % del límite de 1536 MB y tarda menos de 2,1 s, contra
  los 10 minutos que aguanta la cola. La condición 3 del criterio de la épica se cumple con holgura.

**Hallazgo en la construcción:** con el Dockerfile tal cual, el paso `npx remotion bundle` se quedó
sin memoria de Node (`JavaScript heap out of memory`) en la VM de Docker Desktop (8 GB). Pasó dándole
4 GB de heap a ese paso, en una copia local del Dockerfile que no se publicó. No se sabe si pasa en
CI ni si `brand_still` lo empeora: hay que mirar el job `docker-render` cuando esta rama se proponga.
Si hace falta, es una línea (`NODE_OPTIONS=--max-old-space-size=4096` en ese paso) y solo afecta la
construcción, no el límite de 1536 MB en marcha.

### 7.6 Recorte del producto: medición RECORTE-001 y opciones para la historia m-25042543

**Qué se midió:** se probaron 3 modelos abiertos en CPU (`birefnet-general-lite`, `isnet-general-use`
y `u2net`) sobre 10 fotos reales:

- 3 de teléfono del negocio 1;
- 3 de estudio de Polette;
- 4 GoPro de Bianki.

Se midió en el Mac y en un contenedor Linux arm64. El detalle está en
[RECORTE-001](modelos-generativos/pruebas.md#recorte-001) y la ficha del candidato en
[isnet-general-use.md](modelos-generativos/isnet-general-use.md).

**Resultado en una línea:** el modelo que nombra el repositorio recorta mejor que nadie, pero no
cabe en el servidor. IS-Net recorta casi igual con 1,3 GB, que tampoco caben en ningún tope de hoy.

**La prueba visual** (solo en disco local) es
`/Users/herwin/dev/qualify-eval-out/sistema-visual/recorte/render/antes-despues.jpg`:

- son las mismas 2 propuestas de SISVIS-002 con los mismos datos;
- el producto recortado va sobre un disco de la marca, como en Bianki;
- la caja del producto sale del alfa del recorte, como dato del hueco, sin tocar la plantilla.

Cierra la brecha más visible con la vara de Bianki.

| Opción | Calidad en fotos de teléfono | Costo por foto | RAM / tiempo | Licencia | Dónde correría | ¿Se puede deshacer? |
|---|---|---|---|---|---|---|
| A. `birefnet-general-lite` en nuestro servidor (lo que ya está en `segment.py`) | La mejor de las 3: tapas y bordes limpios. Falla en el trompo (se lleva la plancha) y le muerde un pedazo al cono | US$0 | **No corre:** OOM en Linux arm64 aun con 6 GB; 8–30 s por foto en M1 Pro | MIT código y pesos: sí | En ningún lado del CAX21 de 4 GB | Sí (sin datos a terceros), pero no es viable |
| **B. `isnet-general-use` en nuestro servidor** | Casi igual en botellas y estudio. Manchas fantasma suaves en 1 de 3 fotos de teléfono; deja semitransparente un segundo producto en GoPro | US$0 | **1,34 GB de pico**, 5–8 s por foto con 2 CPU (Linux arm64), 1,1–1,6 s en M1 Pro | Apache-2.0 el código; los pesos no traen licencia propia: sí, con esa reserva | Un proceso de una foto a la vez con su propio tope (~1,5 GB), al subir la foto al catálogo. **No cabe en creative-worker (768m)** | Sí: es un modelo propio, se cambia por otro sin migrar datos (se recalcula la máscara) |
| C. API pagada de quitar fondo (solo referencia: Photoroom Basic) | Buena en comida según el proveedor; **no se probó** | US$0,02 por imagen, lista pública (photoroom.com/api/pricing, 2026-11-26); ~US$0,40 al mes con 20 fotos por cliente | Ninguna en nuestro servidor; una llamada de red | Comercial, con contrato | En el proveedor: **las fotos del cliente salen a un tercero** (proveedor nuevo: pide ADR y revisar si guarda o entrena con los datos) | En parte: el código se deshace, los datos ya enviados no |
| D. Seedream 5.0 pro regenera el producto sobre fondo plano + recorte por color (el camino de las figuritas) | **No se probó en esta medición.** El recorte por color sobre fondo plano generado ya funciona (figuritas en producción). **Puede cambiar el producto real:** etiqueta, teléfono impreso, cantidad de botellas | US$0,045 por imagen a 1K (`pricing_data/v9.json`); ~US$0,90 al mes con 20 fotos | Casi nada en nuestro servidor (numpy, ~0,2–0,8 s y <200 MB) | Comercial; Seedream 5.0 pro no cede datos (fundador, 2026-11-12) | BytePlus + nuestro worker, que ya existe | Sí en el código; el riesgo de marca está en cada pieza (una botella inventada es un producto que no existe) |

**Recomendación (decide el fundador): B**, IS-Net en nuestro servidor, una foto a la vez y solo
cuando el dueño sube o elige una foto de producto. Es la única opción que:

- recorta lo bastante bien las fotos de teléfono;
- no manda fotos a terceros;
- no inventa el producto;
- no cuesta por foto.

Es una puerta de dos vías: el modelo se cambia sin migrar nada. Si mañana BiRefNet corre en menos
memoria, se recalcula la máscara.

**Para adoptarla tiene que ser cierto que:**

1. en el CAX21 real el pico sea ≤ 1,5 GB y la foto tarde menos de ~20 s con 1 CPU, sin empujar a
   otros servicios a swap (medir con el servidor en su hora más cargada);
2. sirva en ≥ 80 % de un conjunto de oro de ~30 fotos reales del catálogo, juzgadas con reglas
   escritas antes;
3. exista una regla de rechazo que vuelva a la foto en el disco cuando el recorte no sirva: caja del
   alfa pegada al borde, producto en varias piezas o primer plano fuera de rango;
4. el fundador acepte un proceso o tope nuevo en el servidor (regla de la casa para todo servicio
   nuevo).

**Si el punto 1 falla,** la siguiente es D para las fotos que el dueño marque, con aprobación de la
pieza como hoy. C solo si D cambia demasiado los productos.

**Cambio propuesto en el código** (no hecho; lo hace creative-engineer): `SEGMENTATION_MODEL` →
`"isnet-general-use"` y corregir el docstring de `LocalBiRefNetSegmenter`. El «~2s per photo» no es
cierto en CPU.

