# Catálogo cerrado de diseños para imagen y carrusel (PROPUESTA, pendiente de aprobación del fundador)

`[PROPUESTA · ux-designer · 2026-11-13 · sin aprobar]` · Épica **m-25017272** · ADR 49
(`docs/adr-49-pipeline-imagen-carrusel.md`) · Historias que lo usan: m-25017283 (capa de texto),
m-25017285 (composición en Remotion), m-25017287 (segunda mirada), m-25017294 (texto por
diapositiva), m-25017303 y m-25017304 (destacados), m-25017307 (datos del negocio), m-25017308
(«Otra idea»).

**Para quién es:** quien construye la composición en Remotion (`packages/render`) y quien escribe
el prompt de la capa (`qualify_api/creative/image_pipeline/layer.py`). Los identificadores
(`layout_id`, espacios de texto, parámetros) van en inglés porque son código y son el contrato entre
los dos; el nombre en español es el que usa el equipo y el que leería el dueño si llega a verlo.

**Convención de confianza** (la de `docs/perfil-cliente-pyme.md`): `[F]` decisión del fundador ·
`[E]` evidencia en el repositorio · `[H]` hipótesis. **Nada de este documento se probó con dueños
ni con un render real.** Los límites de caracteres y los tamaños son `[H]` hasta que m-25017292
los mida con las tipografías de Bianki y Polette (§10).

## 0. Resumen

Siete diseños. Claude elige uno por imagen (o por diapositiva), con dos o tres parámetros. Remotion
no confía en la elección: comprueba que el texto no tape lo importante, que se lea y que quepa, y si
algo falla baja por una cadena de respaldo fija hasta **Franja de color**, que siempre funciona.

| # | `layout_id` | Nombre (equipo y dueño) | Qué es | Formatos |
|---|---|---|---|---|
| 1 | `photo_only` | Solo la foto | Foto a sangre + logo. Sin texto | 4:5 · 1:1 · 9:16 |
| 2 | `plate` | Texto en recuadro | Recuadro opaco del color de la marca en la zona tranquila de la foto | 4:5 · 1:1 · 9:16 |
| 3 | `scrim` | Texto sobre sombra | Sombra oscura que sube desde un borde; texto blanco encima | 4:5 · 1:1 · 9:16 |
| 4 | `band` | Franja de color | La foto arriba (o abajo) y una franja sólida con el texto; el texto nunca toca la foto | 4:5 · 1:1 · 9:16 |
| 5 | `info_card` | Datos del negocio | Título + 1 a 4 bloques (dónde, horario, formas de pago, lo más pedido, pedidos) con datos guardados | 4:5 · 1:1 · 9:16 |
| 6 | `brand_fill` | Fondo de color | Sin foto: fondo del color de la marca, logo grande, mensaje | 4:5 · 1:1 · 9:16 |
| 7 | `highlight_circle` | Círculo para destacados | Fondo de color y un ícono, una palabra o una foto dentro del círculo central | solo 9:16 |

Lo que ya está decidido y este catálogo respeta `[F]`: sin botones dibujados; sin pastilla de precio
(el precio vuelve solo si el fundador lo aprueba, §4 y pregunta 1); composición solo en Remotion;
segunda mirada de Claude con una corrección; el dueño cambia el texto y se recompone gratis; logo una
sola vez; asistido, nunca autónomo.

## 1. Reglas comunes a todos los diseños

### 1.1 Lienzo y zonas seguras

| Formato | Lienzo | Margen | Zona donde puede ir texto, logo y contador |
|---|---|---|---|
| Publicación vertical 4:5 | 1080×1350 | 64 px a cada lado | x 64–1016, y 64–1286 |
| Publicación cuadrada 1:1 | 1080×1080 | 64 px; **título dentro de los 810 px centrales** `[H]` | x 64–1016 (título x 135–945), y 64–1016 |
| Historia 9:16 | 1080×1920 | 64 px laterales; arriba **270 px** (14 %) y abajo **384 px** (20 %) los tapa Instagram | x 64–1016, **y 270–1536** |
| Círculo de destacado | 1080×1920 | El círculo central | Círculo de **600 px de diámetro** con centro en (540, 960) `[H]`, lo confirma m-25017301 |

- La foto y los colores de fondo sí llenan las zonas tapadas; lo que no entra ahí es texto, logo ni
  contador.
- `[H]` La cuadrícula del perfil de Instagram muestra hoy las miniaturas recortadas a 3:4: una 4:5
  pierde ~34 px por lado (lo cubre el margen de 64) y una 1:1 pierde ~135 px por lado; por eso el
  título de la 1:1 va en los 810 px centrales. Verificarlo en un perfil real antes de construir.

### 1.2 Lo que Claude informa de la foto (parte de `LayerSpec`)

Claude no solo escribe: primero describe la foto en tres campos que el compositor usa para
comprobar, no para decorar.

| Campo | Tipo | Qué es |
|---|---|---|
| `subject_box` | `[x0, y0, x1, y1]`, fracciones 0–1 redondeadas a 0,05 | El rectángulo que **no se puede tapar**: el producto, la persona o el plato. Si hay varios, la unión |
| `logo_in_photo` | booleano | La foto ya muestra el logo real del negocio (letrero, empaque, delantal). Si es `true`, no se dibuja logo |
| `base_has_invented_text` | booleano (ADR 49 §8.2) | La foto de Seedream trae letras, botones o un logo inventado → se regenera la base una vez. Con la foto del dueño siempre `false` |

### 1.3 Legibilidad sin bordes ni contornos

Ningún texto lleva contorno, borde ni sombra de letra como recurso para leerse (se quita el
`textShadow` de `Headline` en los diseños nuevos). La legibilidad sale siempre de una de cuatro
superficies, y el contraste se **calcula**, no se confía:

| Superficie | Diseños | Cómo se garantiza el contraste |
|---|---|---|
| **Recuadro opaco** (100 %, sin transparencia) | `plate`, contador | Color del recuadro = `surface` o `accent` de la marca. El color del texto lo elige el compositor: el primero de `[palette.text, #FFFFFF, #111111]` que llegue a **4,5:1** contra el recuadro. Con colores sólidos siempre existe uno: blanco o negro dan al menos ~4,6:1 sobre cualquier color |
| **Sombra** (degradado negro) | `scrim` | Texto siempre `#FFFFFF`. Debajo de cada línea de texto la sombra es **al menos 60 % negra**. Peor caso, un píxel blanco puro de la foto: queda `#666666` y el blanco contra eso da **5,7:1**. No hay que medir la foto |
| **Franja o fondo sólido** | `band`, `info_card`, `brand_fill`, `highlight_circle` | Igual que el recuadro: color de la marca + texto elegido por cálculo, ≥ 4,5:1 |
| **Mosaico del logo** | todos | El logo va sobre un mosaico redondeado `surface` (o blanco si `surface` no existe) al 100 %, como hoy en `Logo` de `components.tsx` |

- **Umbrales:** todo texto ≥ **4,5:1**. La única excepción es la palabra de acento del título
  (`accent_word`), que puede usar el `accent` de la marca si llega a **3:1**, porque el título es texto
  grande: a este tamaño de lienzo (1080 px que el teléfono muestra en ~390 px), «texto grande» de WCAG
  equivale a ≥ 66 px normal o ≥ 52 px en negrita, y el título mínimo es 72 px en negrita. Si no llega a
  3:1, la palabra se dibuja del mismo color que el resto, sin aviso.
- Fuera de la paleta no hay colores. Sin paleta, valen los de `props.ts` (`DEFAULT_ACCENT`, etc.).

### 1.4 Tamaños de letra (lienzo de 1080 px de ancho)

El compositor ajusta solo: empieza en el máximo y baja de 4 en 4 px hasta que el texto cabe en sus
líneas. **Nunca baja del mínimo, nunca corta palabras, nunca pone puntos suspensivos ni guiones.**
Un mínimo de 40 px se ve como ~14 pt en un teléfono; 32 px, como ~11,5 pt.

| Espacio | 4:5 | 1:1 | 9:16 | Peso |
|---|---|---|---|---|
| `title` | 104 → 72 | 96 → 72 | 112 → 76 | Negrita, tipografía de títulos de la marca |
| `title` en `brand_fill` | 120 → 80 | 112 → 76 | 128 → 84 | Negrita |
| `subtitle` | 52 → 40 | 48 → 40 | 56 → 44 | Normal, tipografía de texto |
| `call_phrase` | 44 → 40 | 44 → 40 | 48 → 44 | Seminegrita (600) |
| `info_blocks[].label` | 34 → 32 | 34 → 32 | 36 → 34 | Negrita |
| `info_blocks[].value` | 46 → 40 | 44 → 40 | 50 → 44 | Normal |
| Un solo bloque grande (`info_card` con 1 bloque) | valor 72 → 56 | 68 → 52 | 80 → 60 | Normal |
| `highlight_circle` palabra | — | — | 140 → 96 | Negrita |
| Contador «2/5» | 32 | 32 | — | Seminegrita |

- La tipografía de títulos solo va en `title` y en la palabra del destacado; todo lo demás va con la de
  texto. Si la tipografía de títulos de la marca es manuscrita o decorativa `[H]`, el mínimo del
  título sube a 84 px (lo decide el compositor por una lista corta de familias manuscritas).
- Texto en minúsculas normales (como una oración). El compositor no transforma a mayúsculas.

### 1.5 Espacios de texto (los mismos nombres en Python y en `props.ts`)

| Espacio | Nombre para el equipo | Lo escribe | Si está vacío |
|---|---|---|---|
| `title` | Título | Claude (o el dueño al editar) | Obligatorio en todo diseño con texto; sin título, el diseño pasa a `photo_only` |
| `subtitle` | Subtítulo | Claude / dueño | El contenedor se encoge; no queda hueco |
| `call_phrase` | Frase de invitación | Claude / dueño | No se dibuja nada |
| `info_blocks[]` | Bloques de datos `{kind, label, value}` | Claude elige `kind` y orden; **`value` sale de los datos guardados del negocio**, nunca del modelo | El bloque no existe si falta el dato (§7, segundo fallo) |
| `price_ref` | Precio | Claude da `product_id`; el compositor lee el precio del catálogo y lo formatea en la moneda del negocio | No se dibuja |
| `slide_counter` | Contador | El compositor (`n/N`) | Solo en carrusel |
| `highlight_content` | Contenido del círculo | Claude: `icon` + `icon_id` de un juego cerrado, `word`, o `photo` | — |

Los límites de cada espacio dependen del diseño y están en la ficha de cada uno (§2). Van en el
esquema pydantic: Claude no puede devolver un texto más largo (la respuesta estructurada se rechaza y
se pide de nuevo, dentro de la misma llamada).

**Bloques de datos** (`kind` → etiqueta fija → ícono de Lucide → de dónde sale el valor, m-25017300):

| `kind` | Etiqueta | Ícono | Valor |
|---|---|---|---|
| `location` | Dónde estamos | `map-pin` | Dirección guardada (la de WhatsApp, `location_address`) |
| `hours` | Horario | `clock` | Horario guardado |
| `payment` | Formas de pago | `wallet` | Métodos guardados (`brand_payment_methods`), hasta 4, separados por « · » |
| `products` | Lo más pedido | `utensils` (comida) o `shopping-bag` (resto) | Hasta 3 nombres del catálogo (y su precio si la pregunta 1 lo permite) |
| `contact` | Pedidos | `message-circle` | Número de WhatsApp conectado o guardado |

Las etiquetas son fijas para que ninguna pieza vuelva a decir «Ubicación» sin dirección: Claude elige
qué bloques van, no cómo se llaman. Límite de valor: 60 caracteres, 2 líneas (3 en 9:16). Una
dirección más larga no la acorta Claude: la pantalla le pide al dueño una versión corta (hueco, §8).

### 1.6 Parámetros

**Claude puede fijar** (y nada más):

| Parámetro | Valores | En qué diseños |
|---|---|---|
| `layout_id` | los 7 de §0 | todos |
| `anchor` | `plate`: `top_left` · `top_right` · `bottom_left` · `bottom_right` · `top_center` · `bottom_center`; `scrim` y `band`: `top` · `bottom` | `plate`, `scrim`, `band` |
| `container_color` | `surface` · `accent` | `plate`, `band`, `info_card`, `brand_fill`, `highlight_circle` |
| `accent_word` | índice de **una** palabra del título, o `null` | todos los que tienen título, menos `scrim` |
| `info_blocks[].kind` y su orden | los 5 de §1.5 | `info_card`, `brand_fill` (solo `contact` o `location`) |
| `price_ref` | `product_id` del catálogo o `null` | según §4 |
| `highlight_content` | `icon` (+ `icon_id`) · `word` · `photo` | `highlight_circle` |

**Claude no puede fijar:** tipografía, tamaño, posición en píxeles, colores hexadecimales, opacidad,
sombras o contornos, mayúsculas forzadas, emojis, flechas, íconos fuera de los bloques, formas o
botones, posición y tamaño del logo, contador, recorte de la foto.

### 1.7 Comprobaciones del compositor antes de dibujar (deterministas, sin IA)

1. **No tapar lo importante:** el rectángulo de cada contenedor de texto, del logo y del contador no
   se cruza con `subject_box` (tolerancia 16 px).
2. **Zona segura:** todo texto, logo y contador dentro de la zona de §1.1.
3. **Cabe:** cada espacio entra en sus líneas sin bajar del mínimo de §1.4.
4. **Contraste:** §1.3.
5. **Logo una vez:** uno, o ninguno si `logo_in_photo`.

**Cadena de respaldo** si falla 1 o 2: probar los otros `anchor` del mismo diseño → `band` en el
borde más lejano del sujeto → `band` con la foto entera reducida (el fondo desenfocado que ya hace
`CoverPhoto`). Si falla 3: quitar `call_phrase`, luego `subtitle`; el título nunca se quita. Cada
caída queda escrita en la capa (`fallbacks: [...]`) para que la segunda mirada (m-25017287) y la
medición la vean.

### 1.8 Reglas de redacción para el prompt de la capa

- El título dice **qué gana el cliente o qué es el producto**: «Tu shawarma, recién hecho», no
  «Promoción». Prohibido como título completo: «Ubicación», «Horario(s)», «Métodos de pago»,
  «Productos», «Promoción», «Información», «Menú» (son etiquetas; en el destacado sí valen).
- Español sin anglicismos ni modismos de un solo país (`qualify-copy-es`); sin emojis, sin etiquetas
  «#», sin mayúsculas sostenidas; a lo sumo un «¡…!» por pieza.
- **Ningún dato en texto libre:** `title`, `subtitle` y `call_phrase` se rechazan si traen símbolo de
  moneda, cifras de precio, un número de 7 o más dígitos (teléfono) o una hora («9 a. m.», «21:00»).
  Esos datos solo entran por `price_ref` e `info_blocks`. Así no se inventa una dirección ni un precio.
- `call_phrase` es una invitación en forma de frase, no la etiqueta de un botón: «Pídelo por
  WhatsApp», «Te esperamos hoy». Se dibuja como texto, sin caja, sin borde, sin flecha.
- No repetir el nombre del negocio si el logo está en la pieza.

## 2. Los siete diseños

**Leyenda de los dibujos.** Escala: una columna ≈ 45 px, una fila ≈ 90 px (ancho interior = 1080 px).
`░` foto · `S` sujeto (`subject_box`, no se tapa) · `▓` color sólido de la marca (recuadro, franja o
fondo) · `▒` sombra oscura · `[L]` logo en su mosaico · `(1/5)` contador del carrusel ·
`· · interfaz · ·` zona que tapa Instagram en historias (sin texto ni logo). Los textos de los
dibujos son ejemplos inventados para mostrar tamaños, no textos de un cliente; lo que va entre
corchetes, `[dirección guardada]`, sale de los datos del negocio.

### 2.1 `photo_only` — Solo la foto

```text
4:5 · 1080×1350             1:1 · 1080×1080             9:16 · 1080×1920 (sin contador)
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│░[L]░░░░░░░░░░░░░░░░░░░░│  │░[L]░░░░░░░░░░░░░░░░░░░░│  │· · · · · · · · · · · · │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │· · · · interfaz  · · · │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │· · · · · · · · · · · · │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░[L]░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│
│░░░░░░░SSSSSSSSS░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░SSSSSSSSS░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░(1/5)│  │░░░░░░░SSSSSSSSS░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  └────────────────────────┘  │░░░░░░░SSSSSSSSS░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│                              │░░░░░░░SSSSSSSSS░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░(1/5)│                              │░░░░░░░░░░░░░░░░░░░░░░░░│
└────────────────────────┘                              │░░░░░░░░░░░░░░░░░░░░░░░░│
                                                        │░░░░░░░░░░░░░░░░░░░░░░░░│
                                                        │· · · · · · · · · · · · │
                                                        │· · · · interfaz  · · · │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · · · · · · · · · │
                                                        └────────────────────────┘
```

- **Elegirlo cuando:** el dueño pidió «solo la foto»; una diapositiva de desarrollo del carrusel
  donde la foto cuenta todo (otro ángulo del plato, el local por dentro); la foto del dueño ya trae
  texto propio (una pizarra, un letrero) que no conviene tapar.
- **No elegirlo cuando:** la pieza es una promoción o un dato (horario, dirección): sin texto no se
  entiende. Claude no lo elige por su cuenta para una portada de carrusel ni para una pieza suelta;
  solo si el dueño lo pidió o la diapositiva es de desarrollo.
- **Espacios:** ninguno de texto. Logo y, en carrusel, contador.
- **Legibilidad:** no hay texto; el logo va en su mosaico.
- **Parámetros:** ninguno.
- **Sirve a:** cualquier tipo cuando el dueño pide sin texto; carrusel · desarrollo. Detalle en §5.

### 2.2 `plate` — Texto en recuadro

```text
4:5 · 1080×1350             1:1 · 1080×1080             9:16 · 1080×1920
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│░[L]░░░░░░░░░░░░░░░░░░░░│  │░[L]░░░░░░░░░░░░░░░░░░░░│  │· · · · · · · · · · · · │
│░░░░░░░░░░░░░SSSSSSSS░░░│  │░░░░░░░░░░░░░░SSSSSSS░░░│  │· · · · interfaz  · · · │
│░░░░░░░░░░░░░SSSSSSSS░░░│  │░░░░░░░░░░░░░░SSSSSSS░░░│  │· · · · · · · · · · · · │
│░░░░░░░░░░░░░SSSSSSSS░░░│  │░░░░░░░░░░░░░░SSSSSSS░░░│  │░[L]░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░SSSSSSSS░░░│  │░░░░░░░░░░░░░░SSSSSSS░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░░░░░░░░░░░░░SSSSSSSS░░░│  │░░░░░░░░░░░░░░SSSSSSS░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░░░░░░░░░░░░░SSSSSSSS░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░▓ Tu shawarma,    ▓░░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│  │░▓ recién hecho    ▓░░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░▓ Tu shawarma,    ▓░░░░│  │░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│  │░░░░░░░░░░░░░SSSSSSSS░░░│
│░▓ recién hecho    ▓░░░░│  │░░░░░░░░░░░░░░░░░░░(1/5)│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░▓ Salsa de la casa▓░░░░│  └────────────────────────┘  │░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│
│░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│                              │░▓ Tu shawarma,    ▓░░░░│
│░░░░░░░░░░░░░░░░░░░(1/5)│                              │░▓ recién hecho    ▓░░░░│
└────────────────────────┘                              │░▓ Salsa de la casa▓░░░░│
                                                        │░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│
                                                        │· · · · · · · · · · · · │
                                                        │· · · · interfaz  · · · │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · · · · · · · · · │
                                                        └────────────────────────┘
```

- **Elegirlo cuando:** la foto tiene una **zona tranquila** (pared lisa, cielo, mesa vacía, fondo
  desenfocado) en una esquina o en un borde, de al menos ~45 % del ancho y ~25 % del alto, que no se
  cruza con el sujeto. Es el diseño por defecto de una promoción con foto de Seedream, que suele dejar
  fondo desenfocado alrededor del producto `[H]`.
- **No elegirlo cuando:** el sujeto llena el cuadro o está en el centro y no queda esquina libre; la
  foto está llena de detalle en todas partes (mercado, local lleno); el texto pasa de los límites de
  abajo. En esos casos, `band`.
- **Espacios y límites:**

  | Espacio | 4:5 | 1:1 | 9:16 |
  |---|---|---|---|
  | `title` | ≤ 28 car., ≤ 2 líneas | ≤ 24 car., ≤ 2 líneas | ≤ 28 car., ≤ 2 líneas |
  | `subtitle` | ≤ 60 car., ≤ 2 líneas | ≤ 44 car., ≤ 2 líneas | ≤ 60 car., ≤ 2 líneas |
  | `call_phrase` | ≤ 26 car., 1 línea | ≤ 24 car., 1 línea | ≤ 26 car., 1 línea |
  | `price_ref` | 1 línea bajo el título, si §4 lo permite | igual | igual |

  Ancho máximo del recuadro: 72 % del lienzo (4:5 y 9:16), 76 % (1:1). Relleno interior 48 px,
  esquinas de 32 px. Palabra más larga del título: ≤ 13 caracteres (si es más larga, el compositor
  baja el tamaño; si al mínimo no cabe, pasa a `band`).
- **Legibilidad:** recuadro opaco (§1.3). Nada de vidrio ni transparencia: sobre una foto, la
  transparencia vuelve a depender de la foto.
- **Parámetros:** `anchor` (6 posiciones), `container_color`, `accent_word`. En 9:16 las posiciones
  `top_*` quedan por debajo de los 270 px y las `bottom_*` por encima de los 1536 px.
- **Sirve a:** promoción de producto, «Usar mi foto», «Otra idea», carrusel · portada y desarrollo.

### 2.3 `scrim` — Texto sobre sombra

```text
4:5 · 1080×1350             1:1 · 1080×1080             9:16 · 1080×1920
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│░░░░░░░░░░░░░░░░░░░░[L]░│  │░░░░░░░░░░░░░░░░░░░░[L]░│  │· · · · · · · · · · · · │
│░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│  │· · · · interfaz  · · · │
│░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│  │· · · · · · · · · · · · │
│░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░[L]░│
│░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│
│░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│
│░░░░░░░SSSSSSSSSS░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░SSSSSSSSSS░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│  │░░░░░░░SSSSSSSSSS░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │▒ Helado de yogur▒▒▒▒▒▒▒│  │░░░░░░░SSSSSSSSSS░░░░░░░│
│▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│  │▒ con fresas de hoy▒▒▒▒▒│  │░░░░░░░SSSSSSSSSS░░░░░░░│
│▒ Helado de yogur▒▒▒▒▒▒▒│  │▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│▒ con fresas de hoy▒▒▒▒▒│  │▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒(1/5)│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│▒ Solo este sábado▒▒▒▒▒▒│  └────────────────────────┘  │▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│
│▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│                              │▒ Helado de yogur▒▒▒▒▒▒▒│
│▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒(1/5)│                              │▒ con fresas de hoy▒▒▒▒▒│
└────────────────────────┘                              │▒ Solo este sábado▒▒▒▒▒▒│
                                                        │▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│
                                                        │· · · sombra sigue  · · │
                                                        │· · · · interfaz  · · · │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · · · · · · · · · │
                                                        └────────────────────────┘
```

- **Elegirlo cuando:** la mitad de abajo (o de arriba) de la foto es de poca importancia (mesa,
  piso, cielo, desenfoque) y el sujeto termina antes del 55 % del alto (`subject_box.y1 ≤ 0,55` con
  `anchor: bottom`; `y0 ≥ 0,45` con `anchor: top`). Es el diseño que más deja ver la foto; sirve a
  fotos de ambiente.
- **No elegirlo cuando:** el sujeto llega al borde del texto; el texto es largo (más de lo de abajo);
  hace falta precio o datos (la sombra oscurece y el dato pierde peso); la foto ya es muy oscura y la
  pieza quedaría negra en la mitad.
- **Espacios y límites:**

  | Espacio | 4:5 | 1:1 | 9:16 |
  |---|---|---|---|
  | `title` | ≤ 32 car., ≤ 2 líneas | ≤ 26 car., ≤ 2 líneas | ≤ 32 car., ≤ 2 líneas |
  | `subtitle` | ≤ 56 car., ≤ 2 líneas | ≤ 44 car., ≤ 1 línea | ≤ 56 car., ≤ 2 líneas |
  | `call_phrase` | ≤ 26 car., 1 línea | — (no cabe con aire) | ≤ 26 car., 1 línea |
  | `price_ref` | no | no | no |

- **Legibilidad:** degradado negro de 0 % a 75 %, que cubre el 45 % del alto del lado elegido; el
  texto se coloca solo donde la sombra ya vale ≥ 60 % (§1.3). Texto siempre blanco. En 9:16 con
  `anchor: bottom`, la sombra sigue hasta abajo pero el texto termina en y 1536.
- **Parámetros:** `anchor` (`top` · `bottom`). Sin `container_color` (la sombra es negra siempre) y
  sin `accent_word` (el contraste del color de acento sobre la foto no se puede garantizar).
- **Sirve a:** promoción de producto, «Usar mi foto», «Otra idea», carrusel · portada y desarrollo.

### 2.4 `band` — Franja de color

```text
4:5 · 1080×1350             1:1 · 1080×1080             9:16 · 1080×1920
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│░[L]░░░░░░░░░░░░░░░░░░░░│  │░[L]░░░░░░░░░░░░░░░░░░░░│  │· · · · · · · · · · · · │
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │· · · · interfaz  · · · │
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │· · · · · · · · · · · · │
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░[L]░░░░░░░░░░░░░░░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │▓ Tu combo de mediodía▓▓│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │▓ Shawarma y bebida▓▓▓▓▓│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│▓ Tu combo de mediodía▓▓│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│▓ Shawarma y bebida▓▓▓▓▓│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 1/5▓│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│▓ Pídelo por WhatsApp▓▓▓│  └────────────────────────┘  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│                              │▓ Tu combo de mediodía▓▓│
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 1/5▓│                              │▓ Shawarma y bebida▓▓▓▓▓│
└────────────────────────┘                              │▓ Pídelo por WhatsApp▓▓▓│
                                                        │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
                                                        │▓ · sin texto · interfaz│
                                                        │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
                                                        │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
                                                        │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
                                                        └────────────────────────┘
```

- **Elegirlo cuando:** no hay zona tranquila; el sujeto llena el cuadro; el texto es el más largo
  de los diseños con foto; hace falta precio; o la foto es del dueño y viene cargada `[H]`. **Es el
  respaldo final de todos los diseños con foto:** el texto nunca toca la foto, así que siempre se lee.
- **No elegirlo cuando:** la foto pierde lo que la hace buena al recortarse (un plano muy vertical en
  4:5 con el sujeto de arriba a abajo); en ese caso la franja usa la foto entera reducida (respaldo
  del §1.7) o se elige `scrim`.
- **Geometría:** la franja ocupa entre el 32 y el 40 % del alto (4:5), 34–42 % (1:1); en 9:16 va
  desde ~y 1150 hasta el borde, y el texto termina en y 1536 (el resto de la franja queda de color,
  bajo la interfaz). La foto llena el resto con recorte centrado en el centro de `subject_box`; si el
  sujeto no entra entero en esa ventana, la foto se reduce sin recortar.
- **Espacios y límites:**

  | Espacio | 4:5 | 1:1 | 9:16 |
  |---|---|---|---|
  | `title` | ≤ 36 car., ≤ 2 líneas | ≤ 30 car., ≤ 2 líneas (en 810 px centrales) | ≤ 36 car., ≤ 2 líneas |
  | `subtitle` | ≤ 70 car., ≤ 2 líneas | ≤ 50 car., ≤ 1 línea | ≤ 70 car., ≤ 2 líneas |
  | `call_phrase` | ≤ 28 car., 1 línea | ≤ 28 car., 1 línea (si no hay subtítulo) | ≤ 28 car., 1 línea |
  | `price_ref` | 1 línea, a la derecha del título o debajo | igual | igual |

- **Legibilidad:** franja sólida (§1.3).
- **Parámetros:** `anchor` (`top` · `bottom`), `container_color`, `accent_word`.
- **Sirve a:** todos los tipos con foto; carrusel · portada, desarrollo y cierre.

### 2.5 `info_card` — Datos del negocio

```text
4:5 · 1080×1350             1:1 · 1080×1080             9:16 · 1080×1920
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│░░░░░░░░░░░░░░░░░░░░[L] │  │░░░░░░░░░░░░░░░░░░░░[L] │  │· · · · · · · · · · · · │
│░░░░░░SSSSSSSSSSSS      │  │░░░░░░SSSSSSSSSSSS      │  │· · · · interfaz  · · · │
│░░░░░░SSSSSSSSSSSS      │  │░░░░░░SSSSSSSSSSSS      │  │· · · · · · · · · · · · │
│░░░░░░SSSSSSSSSSSS      │  │ Ven por tu shawarma    │  │░░░░░░░░░░░░░░░░░░░░[L] │
│ Ven por tu shawarma    │  │ (◎) Dónde estamos      │  │░░░░░░SSSSSSSSSSSS      │
│ (◎) Dónde estamos      │  │    [dirección guardada]│  │░░░░░░SSSSSSSSSSSS      │
│    [dirección guardada]│  │ (◷) Horario            │  │░░░░░░SSSSSSSSSSSS      │
│ (◷) Horario            │  │    [horario guardado]  │  │░░░░░░SSSSSSSSSSSS      │
│    [horario guardado]  │  │ (▣) Formas de pago     │  │ Ven por tu shawarma    │
│ (▣) Formas de pago     │  │    [métodos guardados] │  │ (◎) Dónde estamos      │
│    [métodos guardados] │  │                        │  │    [dirección guardada]│
│ (☰) Lo más pedido      │  │                   (1/5)│  │    [segunda línea]     │
│    [3 productos]       │  └────────────────────────┘  │ (◷) Horario            │
│                        │                              │    [horario guardado]  │
│                   (1/5)│                              │ (▣) Formas de pago     │
└────────────────────────┘                              │    [métodos guardados] │
                                                        │                        │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · interfaz  · · · │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · · · · · · · · · │
                                                        └────────────────────────┘
```

Con **un solo bloque** (carrusel de «Información de tu negocio», un dato por diapositiva):

```text
4:5 · un dato (diapositiva 3)  1:1 · un dato, sin logo
┌────────────────────────┐  ┌────────────────────────┐
│                     [L]│  │                        │
│                        │  │                        │
│                        │  │                        │
│                        │  │         (◷)            │
│         (◷)            │  │                        │
│                        │  │       Horario          │
│       Horario          │  │    Lunes a sábado      │
│    Lunes a sábado      │  │   de 11 a. m. a 9 p. m.│
│   de 11 a. m. a 9 p. m.│  │                        │
│                        │  │                        │
│                        │  │                        │
│                        │  │                   (3/5)│
│                        │  └────────────────────────┘
│                        │
│                   (3/5)│
└────────────────────────┘
```

- **Elegirlo cuando:** la pieza es «Información de tu negocio» o «Otra idea» pide datos (dónde
  estamos, horario, formas de pago); y solo con los bloques cuyos datos existen.
- **No elegirlo cuando:** falta el dato (no se arma la pieza: se le pide al dueño, §7); la pieza es
  una promoción de un producto (para eso, `plate` o `band` con precio).
- **Geometría:** fondo sólido; arriba, una tira de foto opcional (foto real del local o del producto,
  de la Galería o generada **sin** lugares, §7) del 30–35 % del alto (4:5), 25 % (1:1), 25 % (9:16).
  Sin foto, el título sube y el logo va arriba a la izquierda sobre el fondo.
- **Espacios y límites:**

  | Espacio | 4:5 | 1:1 | 9:16 |
  |---|---|---|---|
  | `title` | ≤ 30 car., ≤ 2 líneas | ≤ 24 car., 1 línea | ≤ 30 car., ≤ 2 líneas |
  | `subtitle` | no | no | ≤ 50 car., 1 línea |
  | `info_blocks` | 1–4 (3 con tira de foto) | 1–3 (2 con tira de foto) | 1–4 |
  | `label` | fija (§1.5) | fija | fija |
  | `value` | ≤ 60 car., ≤ 2 líneas | ≤ 44 car., ≤ 2 líneas | ≤ 60 car., ≤ 3 líneas |
  | `call_phrase` | no | no | ≤ 28 car., 1 línea |

  Un solo bloque: ícono de 120 px, etiqueta, valor grande (§1.4), título opcional arriba.
- **Legibilidad:** fondo sólido (§1.3); íconos del mismo color que el texto.
- **Parámetros:** `container_color` (por defecto `surface`), `info_blocks[].kind` y orden,
  `accent_word`.
- **Sirve a:** «Información de tu negocio» (imagen y carrusel · desarrollo), «Otra idea» con datos,
  historia con datos.

### 2.6 `brand_fill` — Fondo de color

```text
4:5 · 1080×1350 · fondo ▓   1:1 · 1080×1080 · fondo ▓   9:16 · 1080×1920
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│                        │  │                        │  │· · · · · · · · · · · · │
│                        │  │        [ LOGO ]        │  │· · · · interfaz  · · · │
│        [ LOGO ]        │  │                        │  │· · · · · · · · · · · · │
│                        │  │  Este lunes festivo    │  │                        │
│                        │  │  también abrimos       │  │                        │
│  Este lunes festivo    │  │                        │  │        [ LOGO ]        │
│  también abrimos       │  │                        │  │                        │
│                        │  │  Te esperamos con      │  │                        │
│                        │  │  shawarma recién hecho │  │  Este lunes festivo    │
│  Te esperamos con      │  │                        │  │  también abrimos       │
│  shawarma recién hecho │  │ Escríbenos por WhatsApp│  │                        │
│                        │  │                   (5/5)│  │                        │
│ Escríbenos por WhatsApp│  └────────────────────────┘  │  Te esperamos con      │
│                        │                              │  shawarma recién hecho │
│                   (5/5)│                              │                        │
└────────────────────────┘                              │ Escríbenos por WhatsApp│
                                                        │                        │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · interfaz  · · · │
                                                        │· · · · · · · · · · · · │
                                                        │· · · · · · · · · · · · │
                                                        └────────────────────────┘
```

- **Elegirlo cuando:** no hay foto o no hace falta: un aviso («abrimos el festivo desde las…» —
  la hora va en un bloque, no en el título), una frase, el **cierre del carrusel**, «Otra idea» sin
  producto.
- **No elegirlo cuando:** hay un producto que mostrar (sin foto no se vende comida `[E]`
  `estrategia-contenido-bianki-polet.md` §0); más de dos piezas seguidas del mismo negocio con este
  diseño (se ve todo igual `[H]`).
- **Espacios y límites:**

  | Espacio | 4:5 | 1:1 | 9:16 |
  |---|---|---|---|
  | `title` | ≤ 60 car., ≤ 3 líneas | ≤ 48 car., ≤ 3 líneas | ≤ 60 car., ≤ 4 líneas |
  | `subtitle` | ≤ 110 car., ≤ 3 líneas | ≤ 80 car., ≤ 2 líneas | ≤ 110 car., ≤ 3 líneas |
  | `call_phrase` | ≤ 28 car., 1 línea | ≤ 28 car., 1 línea | ≤ 28 car., 1 línea |
  | `info_blocks` | 0–1 (`contact`, `location` o `hours`) | 0–1 | 0–2 |

- **Legibilidad:** fondo sólido; logo grande (200 px) centrado arriba: es **el** logo de la pieza.
- **Parámetros:** `container_color` (por defecto `accent`), `accent_word`, bloque opcional.
- **Sirve a:** carrusel · cierre (por defecto), carrusel · portada sin foto, «Otra idea», historia de
  aviso, «Información de tu negocio» · cierre.

### 2.7 `highlight_circle` — Círculo para destacados

```text
9:16 · ícono                9:16 · palabra              9:16 · foto en círculo
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│· · · · interfaz  · · · │  │· · · · interfaz  · · · │  │· · · · interfaz  · · · │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│                        │  │                        │  │                        │
│                        │  │                        │  │                        │
│                        │  │                        │  │                        │
│                        │  │                        │  │                        │
│       ╭────────╮       │  │       ╭────────╮       │  │       ╭────────╮       │
│     ╭─╯        ╰─╮     │  │     ╭─╯        ╰─╮     │  │     ╭─╯        ╰─╮     │
│     │            │     │  │     │            │     │  │     │ ░░░░░░░░░░ │     │
│     │    (◷)     │     │  │     │    Menú    │     │  │     │ ░░SSSSSS░░ │     │
│     │   ícono    │     │  │     │            │     │  │     │ ░░SSSSSS░░ │     │
│     │            │     │  │     │            │     │  │     │ ░░░░░░░░░░ │     │
│     ╰─╮        ╭─╯     │  │     ╰─╮        ╭─╯     │  │     ╰─╮        ╭─╯     │
│       ╰────────╯       │  │       ╰────────╯       │  │       ╰────────╯       │
│                        │  │                        │  │                        │
│                        │  │                        │  │                        │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│· · · · interfaz  · · · │  │· · · · interfaz  · · · │  │· · · · interfaz  · · · │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
└────────────────────────┘  └────────────────────────┘  └────────────────────────┘
```

- **Elegirlo cuando:** el tipo es «Portada para historias destacadas» (palabra o foto) o «Íconos para
  destacados» (ícono). Es el único diseño de esos dos tipos.
- **No elegirlo cuando:** cualquier otro tipo.
- **Espacios y límites:** `highlight_content = icon` → `icon_id` de un juego cerrado de Lucide
  (`utensils`, `ice-cream-cone`, `map-pin`, `clock`, `wallet`, `star`, `message-circle`,
  `shopping-bag`, `home`, `plane`, `gift`, `heart`…; la lista final la fija m-25017304), 320 px, trazo
  igual en todo el juego. `word` → ≤ 9 caracteres, 1 línea (cabe en 600 px a 96 px). `photo` → la
  foto del dueño recortada en círculo de 600 px, centrada en `subject_box`.
- **Legibilidad:** fondo sólido; ícono y palabra con el color elegido por cálculo (≥ 4,5:1; el
  ícono, ≥ 3:1 como gráfico).
- **Sin logo:** el destacado ya está en el perfil del negocio; un logo dentro del círculo no se lee.
- **Parámetros:** `container_color`, `highlight_content`, `icon_id`. En un juego de íconos, todos
  con el mismo color.
- **Sirve a:** «Portada para historias destacadas», «Íconos para destacados». Solo descarga hasta que
  m-25017301 diga si la API los publica `[H]`.

## 3. Cobertura: tipo de pieza × formato × diseño

El primero de cada celda es el **diseño por defecto** cuando Claude duda; los demás, por orden de
preferencia. «—» = esa combinación no existe.

| Tipo de pieza (rol) | 4:5 | 1:1 | 9:16 |
|---|---|---|---|
| Promoción de un producto (imagen) | `plate`, `band`, `scrim`, `photo_only`* | igual | igual |
| «Usar mi foto» (foto real del dueño) | `band`, `plate`, `scrim`, `photo_only`* | igual | igual |
| Carrusel · portada | `plate`, `band`, `scrim`, `brand_fill` | igual | — (ver §8) |
| Carrusel · desarrollo | `plate`, `band`, `scrim`, `photo_only`, `info_card` (1 bloque) | igual | — |
| Carrusel · cierre | `brand_fill`, `band` | igual | — |
| Información de tu negocio (imagen) | `info_card` | `info_card` (≤ 3 bloques) | `info_card` |
| Información de tu negocio (carrusel) | portada: `band`, `plate`, `brand_fill` · desarrollo: `info_card` (1 bloque) · cierre: `brand_fill` | igual | — |
| Portada para historias destacadas | — | — | `highlight_circle` (`word` o `photo`) |
| Íconos para destacados | — | — | `highlight_circle` (`icon`), un juego |
| «Otra idea» (texto libre) | `plate`, `band`, `scrim`, `brand_fill`, `info_card`** | igual | igual |

\* Solo si el dueño pidió la pieza sin texto. \*\* Solo si la idea pide datos guardados.

**Lo que queda sin diseño** está en §8.

## 4. Dónde van el precio y el logo (una vez cada uno)

### Precio `[F]` hoy no se dibuja (decisión #10); esta es la propuesta para cuando vuelva

- **Solo por referencia** (`price_ref` → precio del catálogo al componer), formateado en la moneda y
  el formato del negocio; precios enteros o nada (`qualify-copy-es` §5). Si el producto no tiene
  precio en el catálogo, no se dibuja y no se avisa en la imagen.
- **Como texto, nunca como pastilla ni botón:** una línea del mismo contenedor que el título, en la
  tipografía de títulos, al 70 % de su tamaño, del mismo color (o del `accent` si llega a 3:1).
- **Dónde sí:** dentro del recuadro de `plate`, dentro de la franja de `band`, y en el bloque
  `products` de `info_card` (un precio por producto, hasta 3).
- **Dónde no:** `scrim`, `photo_only`, `brand_fill`, `highlight_circle`; portada de carrusel con
  varios productos; nunca suelto sobre la foto.
- **Una vez por producto y por imagen.** En un carrusel, el precio de un producto va en su diapositiva
  de desarrollo, no se repite en la portada ni en el cierre.

### Logo

- **Uno o ninguno por imagen.** Ninguno si `logo_in_photo` es `true` (el logo real ya se ve) o en
  `highlight_circle`.
- **Tamaño y forma:** mosaico de 112 px (≈ 10 % del ancho), esquinas de 24 px, color `surface` (o
  blanco) al 100 %; el logo adentro al 82 %, como el `Logo` actual. En `brand_fill`, 200 px centrado
  arriba.
- **Dónde:** arriba a la izquierda por defecto (en 9:16, desde y 294). El compositor lo mueve a la
  primera esquina libre en este orden: arriba izquierda → arriba derecha → abajo derecha → abajo
  izquierda. Libre = no se cruza con el contenedor de texto ni con `subject_box`. En carrusel, abajo a
  la derecha es del contador. Si no hay esquina libre, el logo baja a 88 px y va dentro de la esquina
  del recuadro o la franja.
- **Claude no lo coloca:** solo informa `logo_in_photo`.
- **Carrusel:** logo en la portada y en el cierre, no en las diapositivas de desarrollo
  (pregunta 3).

### Contador del carrusel

`n/N` en un recuadro pequeño (`surface` al 100 %, texto por cálculo ≥ 4,5:1, 32 px), abajo a la
derecha a 64 px de los bordes, **en todas las diapositivas, en el mismo lugar** (pregunta 5). En
`band` con `anchor: bottom` va dentro de la franja, sin recuadro. Lo pone el compositor; Claude no lo
escribe.

## 5. Una pieza sin texto

```text
4:5 · con logo              4:5 · logo ya en la foto
┌────────────────────────┐  ┌────────────────────────┐
│░[L]░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│
└────────────────────────┘  └────────────────────────┘
```

- La foto a sangre, recortada con el centro en `subject_box`; **sin sombra, sin oscurecer** (el
  `dim` de `CoverPhoto` va en 0).
- El logo en su mosaico, arriba a la izquierda, o ninguno si `logo_in_photo`.
- En carrusel, el contador; en historia, nada en las zonas de interfaz.
- Sin título, sin frase, sin precio. Si el dueño quiere decir algo, va en el texto de la publicación
  (la descripción que acompaña a la foto), no en la imagen.
- En la pantalla, el dueño llega a esto con «Sin texto en la imagen» (m-25017309); al editar, vaciar el
  título hace lo mismo y se recompone gratis.

## 6. Carrusel: roles y coherencia

| Rol | Qué lleva | Diseños |
|---|---|---|
| Portada (diapositiva 1) | Título que da ganas de deslizar; subtítulo opcional; sin datos | `plate`, `band`, `scrim`, `brand_fill` |
| Desarrollo (2 … N-1) | Un producto, un paso o un dato por diapositiva; título corto o nada | `plate`, `band`, `scrim`, `photo_only`, `info_card` (1 bloque) |
| Cierre (N) | La invitación (`call_phrase`) y cómo pedir (`contact` o `location`) | `brand_fill`, `band` |

- **Iguales en todas:** paleta, `container_color`, tipografías, lugar del contador.
- **Pueden cambiar:** el diseño y el `anchor` de cada diapositiva, según su foto.
- Con 2 diapositivas: portada + cierre. Con 3 o más: portada + desarrollo + cierre.
- La segunda mirada (m-25017287) revisa las N juntas: si una diapositiva se ve distinta sin razón,
  la corrige con un diseño de la lista de su rol.

## 7. Los dos fallos de ejemplo, con el catálogo nuevo

### 7.1 Historia de Bianki: título blanco con borde negro sobre lo más cargado, tapando el producto y el logo

```text
HOY (historia)              NUEVO · placa arriba        NUEVO · si no hay calma
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│· · · · interfaz  · · · │  │· · · · interfaz  · · · │  │· · · · interfaz  · · · │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│░░░░░░░░[logo escena]░░░│  │░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░[L]│  │░[L]░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░▓ Tu shawarma,    ▓░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░▓ recién hecho    ▓░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░TÍTULO BLANCO CON░░░░│  │░▓ Salsa de la casa▓░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░BORDE NEGRO SSSSS░░░░│  │░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░SOBRE LO MÁS SSSS░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░CARGADO SSSSSSSSS░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│
│░░░░( BERIRN NON )░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│░░░░[ PÍDELO YA ]░░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │▓ Tu shawarma,▓▓▓▓▓▓▓▓▓▓│
│░░░░░░░░░░░░░░░░░░░░[L]░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │▓ recién hecho▓▓▓▓▓▓▓▓▓▓│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░SSSSSSSSSSSS░░░░░░│  │▓ Salsa de la casa▓▓▓▓▓▓│
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░░░░░│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│· · · · interfaz  · · · │  │· · · · interfaz  · · · │  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
└────────────────────────┘  └────────────────────────┘  └────────────────────────┘
```

1. La base trae «BERIRN NON», una píldora y un logo inventado → `base_has_invented_text: true` → se
   regenera la base una vez (ADR 49 §2.1). Ningún diseño dibuja botones; la píldora no puede salir del
   compositor.
2. Claude informa `subject_box` (el shawarma, centro-abajo) y elige `plate` con `anchor: top_left`
   sobre la zona tranquila; el compositor comprueba que el recuadro no se cruza con el sujeto ni con
   la zona de interfaz.
3. Si la foto nueva no tiene zona tranquila, la cadena de respaldo lleva a `band` abajo: el texto
   queda en una franja de color, sin tocar la foto, y termina en y 1536.
4. Un solo logo, el de la marca, en una esquina libre. El título va en minúsculas normales, sin borde,
   con contraste ≥ 4,5:1 calculado.

### 7.2 Pieza «Ubicación» sin dirección y con una calle europea inventada

```text
HOY                         NUEVO · Datos del negocio   SI FALTA LA DIRECCIÓN
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │Para mostrar dónde      │
│· · · · interfaz  · · · │  │· · · · interfaz  · · · │  │estás, falta tu         │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │  │dirección.              │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░░░░░░░░░░░░░░░░░░░[L] │  │                        │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░foto real del local   │  │Dirección de tu local   │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │░░(Galería) o sin foto  │  │[____________________]  │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │ Te esperamos en        │  │Ej.: C.C. Las Palmas,   │
│░░░░UBICACIÓN░░░░░░░░░░░│  │ el local               │  │local 5, San Cristóbal  │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │ (◎) Dónde estamos      │  │                        │
│░calle europea inventada│  │    [dirección guardada]│  │[ Guardar y seguir ]    │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │    [segunda línea]     │  └────────────────────────┘
│░░░░░░░░░░░░░░░░░░░░░░░░│  │ (◷) Horario            │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │    [horario guardado]  │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │ (☏) Pedidos            │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │    [WhatsApp guardado] │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │                        │
│░░░░░░░░░░░░░░░░░░░░░░░░│  │                        │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│· · · · interfaz  · · · │  │· · · · interfaz  · · · │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │
│· · · · · · · · · · · · │  │· · · · · · · · · · · · │
└────────────────────────┘  └────────────────────────┘
```

1. El tipo «Información de tu negocio» **no se puede crear sin el dato**: si falta la dirección, el
   paso «Qué debe decir» (m-25017309) la pide antes de gastar una creación, con un ejemplo de
   respuesta válida. El texto propuesto: «Para mostrar dónde estás, falta tu dirección.» + campo
   «Dirección de tu local» + «Guardar y seguir». Se guarda en los datos del negocio (m-25017300) y
   sirve para la próxima vez.
2. El título no puede ser «Ubicación» (§1.8): dice qué gana el cliente («Te esperamos en el local»).
   «Dónde estamos» es la etiqueta fija del bloque, y su valor sale de la dirección guardada.
3. **Ninguna foto generada muestra lugares:** para piezas con `location`, la tira de foto es la foto
   real del local de la Galería, un producto del catálogo, o no hay foto. El prompt de la base no
   pide fachadas, calles ni ciudades (regla para m-25017279 y m-25017307).

## 8. Huecos que este catálogo no cierra

1. **Carrusel en 9:16** (una secuencia de historias): Instagram no tiene carrusel de historias; hoy
   no hay tipo para eso. Si se pide, cada historia sería una pieza 9:16 con los mismos diseños, sin
   contador.
2. **Menú o lista de precios con más de 3 productos** (lo que más pide un local de comida `[H]`): el
   bloque `products` llega a 3. Una carta completa necesita un diseño de lista que no está aquí.
3. **Foto del dueño con texto propio** (pizarra, letrero, empaque con letras): Claude puede elegir
   `photo_only` o `band`, pero ningún campo marca dónde está ese texto para no taparlo.
4. **Anuncios de Meta:** el botón propio del anuncio se conserva `[F]` (#10), pero no se revisó cómo
   conviven estos diseños con el texto que Meta agrega alrededor.
5. **Diapositivas animadas** (m-25017297): este catálogo es de fotos fijas.
6. **Direcciones de más de 60 caracteres:** Claude no puede acortar un dato guardado; hace falta que
   el dueño guarde una versión corta (campo nuevo en m-25017300).
7. **Logo con fondo propio o en blanco:** la identidad de marca guarda un solo archivo de logo; sin
   variante clara u oscura, el mosaico es obligatorio.
8. **Zonas no validadas:** el recorte 3:4 de la cuadrícula y el círculo de 600 px son `[H]`.

## 9. Lo que necesita cada ingeniero

**Composición (m-25017285, `packages/render`):**

- Una composición `LayerStill` que recibe `layout_id`, `layout_version`, los espacios de §1.5, los
  parámetros de §1.6, `subject_box`, `logo_in_photo`, `slide_counter` y el formato; un componente por
  diseño. Parte de `PromoStill.tsx`: se reusan `CoverPhoto` (con `dim: 0` y punto de recorte),
  `Logo` y la carga de tipografías; **no** se usan `PricePill`, el botón con borde de la frase ni la
  sombra de `Headline`.
- El ajuste de tamaño, las comprobaciones y la cadena de respaldo de §1.7 son código determinista
  con pruebas por diseño y formato: una tabla de casos (sujeto en cada tercio, título de 13
  caracteres por palabra, paleta clara, paleta media `#777777`, sin paleta, sin logo).
- La versión del catálogo (`layout_version`) entra en la clave del render (ADR 49 §2.2): cambiar un
  margen es una versión nueva.
- La capa resuelta (con `fallbacks`) se devuelve para guardarla con la pieza.

**Prompt de la capa (m-25017283):**

- El enum de `layout_id` y los límites por diseño y formato de §2 en el esquema pydantic,
  generados desde la misma tabla que lee `props.ts` (un archivo de datos compartido, no dos copias).
- El prompt da a Claude, por diseño, solo el «elegirlo cuando / no elegirlo cuando» de §2, la tabla de
  cobertura del tipo pedido (§3) y las reglas de §1.8; le pide `subject_box` y `logo_in_photo`
  **antes** de elegir el diseño.
- Validadores de §1.8 (sin moneda, sin teléfono, sin horas, títulos prohibidos) en el esquema.
- Los datos (`price_ref`, `info_blocks`) solo con lo que el negocio tiene guardado: el prompt recibe la
  lista de bloques disponibles y no puede pedir otros.

**Segunda mirada (m-25017287):** su lista: ¿algo tapa el producto?, ¿se lee todo?, ¿hay letras
inventadas?, ¿el logo sale dos veces?, ¿el título dice algo o es una etiqueta?, ¿el diseño corresponde
a la foto?, ¿hubo `fallbacks`? Si corrige, solo puede cambiar diseño, `anchor`, `container_color`,
`accent_word` o acortar textos; no puede inventar datos.

## 10. Hipótesis y cómo validarlas

| Hipótesis | Cómo se valida | Quién |
|---|---|---|
| Los límites de caracteres caben con las tipografías reales | Render de los 7 diseños × 3 formatos con las marcas de Bianki y Polette y los títulos más largos permitidos | m-25017292 (datasci + creative) |
| El dueño prefiere el recuadro o la franja a la sombra | Mostrar a Bianki y Polette la misma foto en `plate`, `band` y `scrim` y preguntar cuál publicaría | ux-designer, perfil §5 pregunta 6 |
| Las fotos del dueño vienen más cargadas y piden `band` | Contar en la medición qué diseño eligió Claude y cuántas veces cayó al respaldo con «Usar mi foto» | m-25017292 |
| Un local de comida necesita una carta con precios | Perfil §5 pregunta 5 («¿qué es lo que más le cuesta hoy?») + pedir a Bianki una pieza de su carta | ux-designer |
| Cuadrícula 3:4 y círculo de 600 px | Publicar una prueba en un perfil de Attitude Factory (sin clientes) y medir | m-25017301 |

## 11. Preguntas para el fundador

1. **¿Vuelve el precio a la imagen, y cómo?** Recomendación: **sí, como una línea de texto dentro del
   recuadro o la franja, nunca como pastilla**, solo del catálogo, encendido por defecto en la
   promoción de un producto con precio, y hasta 3 precios en el bloque «Lo más pedido». La promesa
   de Bianki es «precio a la vista» `[E]`.
2. **¿El dueño puede cambiar de diseño, además de cambiar el texto?** Recomendación: **sí, con
   «Probar otro diseño»**, que muestra hasta 3 alternativas que pasaron las comprobaciones con esa
   foto, gratis y sin pedir otra foto (ADR 49 §2: cambiar de diseño no vuelve a llamar a Claude para
   escribir; sí corre la segunda mirada, que es su costo). Sin esto, si no le gusta, la única salida
   es «Crear otra».
3. **¿Logo en todas las diapositivas del carrusel o solo en portada y cierre?** Recomendación:
   **portada y cierre**; en el desarrollo, la foto respira y el logo repetido no suma `[H]`.
4. **¿Entra «Texto sobre sombra» (`scrim`) en el catálogo?** Es el único diseño con texto encima de
   la foto sin un recuadro. Recomendación: **sí, con sus límites** (título corto, sin precio, sujeto
   lejos del texto): el contraste está garantizado por cálculo (≥ 60 % de sombra = 5,7:1) y es el que
   más deja ver la comida.
5. **¿El contador va en todas las diapositivas, portada incluida?** Recomendación: **sí, «1/5» desde
   la portada, abajo a la derecha**: le dice a quien mira que hay más para deslizar, y Instagram solo
   muestra su propio contador unos segundos.

