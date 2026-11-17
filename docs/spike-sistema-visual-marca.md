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
llegar ahí hace falta quitar el fondo de la foto del dueño. Elegir proveedor es decisión del
fundador; no se adoptó ninguno:

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
