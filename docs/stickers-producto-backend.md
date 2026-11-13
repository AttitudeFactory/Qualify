# Stickers de producto («tierno»): backend y contrato para la pantalla

Ticket m-25017372. Construido el 2026-11-12 sobre el banco STICKERS-KAWAII-001
([pruebas.md](modelos-generativos/pruebas.md#stickers-kawaii-001)) y la propuesta de UX
[ux-stickers-producto.md](ux-stickers-producto.md), con las decisiones del fundador del mismo día.

## Decisiones del fundador (2026-11-12) que mandan sobre la propuesta de UX

| # | Tema | Decisión | Efecto en el producto |
|---|---|---|---|
| 1 | Recorte del dibujo | Color plano con numpy es «conversión»: permitido. Todo lo demás lo compone Remotion; Pillow no dibuja | `qualify_creative.seasonal.kawaii.cut_out`; plantilla `sticker` v2 |
| 2 | Costo | Se muestra en **creaciones, nunca en dólares** (decisión 8). Un dibujo usa 1 creación (el peso de una imagen en `pesos-creaciones-v3`). Lo que falla no se cobra | El dólar real va al registro de consumo y a la procedencia, nunca a la pantalla |
| 3 | «Pedir otro» | **Guarda todos los dibujos** y el dueño elige; sin tope de cantidad: el límite es el mes | Cada «Pedir otro» crea un dibujo nuevo |
| 4 | Orden en el chat | **Primero los de temporada**, después los de producto | También en la biblioteca |

Con esto, D1 = B, D2 = C, D3 = B y D4 = B de la tabla del §9 de la propuesta de UX.

## Flujo

1. **Dibujo del producto (pagado, 1 creación).** El dueño elige un producto con foto. Se cobra 1
   creación al pedirlo. `creative-worker` llama una vez a Seedream 5.0 pro
   (`dola-seedream-5-0-pro-260628`, 1K, prompt `kawaii-v3`, tabla de precios `v9`:
   `per_sticker_character` = US$0,045). Pasa por el freno de presupuesto del mes en dólares
   antes de llamar. Recorta el fondo y deja el dibujo `ready`. Si falla, queda `failed` y la
   creación se devuelve.
2. **El dueño elige un dibujo** (`approved`). Es la primera aprobación.
3. **Stickers (gratis).** Un sticker por mensaje, con movimiento, quieto o los dos. Los dibuja
   Remotion (`sticker` v2, modo con mensaje) en `media-worker` y llegan a «Por aprobar». El
   dueño aprueba cada uno: es la segunda aprobación. Nada se manda solo.

Mensajes: «¡Gracias por tu pedido!», «Bienvenido», «En camino», «Entregado», «Listo para
recoger» o uno propio de hasta 25 caracteres. Un mensaje corto (hasta 12 caracteres) salta
(`rebote`); uno largo, de dos líneas, late (`latido`).

## Contrato para la pantalla (`Qualify/product_sticker_provider.py`)

`gateway()` devuelve la puerta. Todos los métodos son bloqueantes: se llaman fuera del event
loop. Todo rechazo es `ProductStickerError` (o `SeasonalError` de la biblioteca) y su
`.message` se muestra tal cual.

| Método | Devuelve | Para |
|---|---|---|
| `products(tenant, brand)` | `ProductStep(products, without_photo, preselected)` | Paso 1: la grilla y «N productos no salen porque no tienen foto» |
| `cost(tenant, brand)` | `CreationsCost(creations, left, unlimited, can_pay, cost_line, button_label, message)` | «Este dibujo usa 1 creación. Te quedan 12 este mes.» y el botón «Crear dibujo · 1 creación» |
| `presets()` / `max_message_chars()` / `check_message(text)` | mensajes / 25 / texto limpio | Paso 2 |
| `create_character(tenant, brand, product_id, user, accepted_creations)` | `CharacterCard` (`pending`) | «Crear» y «Pedir otro» (siempre uno nuevo) |
| `characters(tenant, brand, product_id=None)` | `list[CharacterCard]` | Los dibujos para elegir, el más nuevo primero |
| `use_character(…)` / `discard_character(…)` | `CharacterCard` | «Usar este dibujo» / «No me gusta» |
| `make_stickers(tenant, brand, character_id, messages, user, animated=True, still=False)` | `list[StickerCard]` (`pending`) | Crear los stickers de los mensajes |
| `stickers(tenant, brand)` | `list[StickerCard]` | «De tus productos» en Por aprobar y Aprobados |
| `approve_stickers` / `another_sticker` / `delete_sticker` | `StickerCard`(s) | Las acciones de la biblioteca: aprobar, dibujar otra vez (gratis) y eliminar |

Estados de un dibujo: `pending` («Dibujando…»), `ready` (elegible), `failed` (`failure_text`:
«Este dibujo no salió y no se te cobró. Puedes pedir otro.»), `approved` (el elegido). Estados de un sticker:
los de la biblioteca (`pending`, `ready`, `approved`, `rejected`, `failed`, `archived`).

Errores y textos:

| Error | Texto |
|---|---|
| `NoProductPhoto` | «Para dibujar tu producto necesitamos una foto de él. Sube la foto en Tus productos y vuelve aquí.» |
| `CostChanged` | «El costo cambió. Revísalo antes de crear.» |
| `NotEnoughCreationsLeft` | «Te falta 1 creación este mes. Vuelves a tener creaciones el 1 de diciembre. Mientras tanto, los stickers de temporada son gratis.» |
| `StartFailed` | «No pudimos empezar a dibujar. No se te cobró. Vuelve a intentarlo en un momento.» |
| `CharacterNotFound` | «No encontramos ese dibujo. Actualiza la pantalla.» |
| `CharacterChanged` | «Este dibujo cambió mientras tanto. Actualiza la pantalla.» |
| `CharacterNotReady` | «Este dibujo todavía no está listo. Llega en unos minutos.» |
| `CharacterNotApproved` | «Primero elige este dibujo para hacer stickers con él.» |
| `MessageEmpty` | «Escribe el mensaje del sticker.» |
| `MessageTooLong` | «Máximo 25 letras. Prueba algo más corto, como «¡Gracias!».» |
| `NoMessages` | «Elige al menos un mensaje.» |
| `NoVariant` | «Elige si lo quieres con movimiento, quieto o los dos.» |

Los motivos de falla de un dibujo (`budget_cap`, `no_source`, `vendor_failed`, etc.) están en
`product_stickers.REASON_TEXT`. Desde m-25018822 (2026-11-13) la guarda de precio sigue la regla
del generador: sin fila en `creative_engine_config` (o con `hard_stop_on_cap` en falso) no hay tope
en dólares, y el límite del dueño es la cuota de creaciones que cobra `request_character`; solo un
tope con `hard_stop_on_cap` rechaza (`budget_cap`). `no_budget_cap` ya no se escribe; su texto queda
para los dibujos que fallaron antes. Todos dicen «No se te cobró». Los de un sticker
están en `whatsapp.seasonal.REASON_TEXT`. Hay dos nuevos: `render_unavailable` y
`character_unavailable`.

## Datos (migración 0155)

- `product_sticker_characters`: un dibujo por fila, con RLS. Guarda la procedencia completa:
  producto y foto de origen, modelo, `prompt_version`, `pipeline_version`,
  `pricing_table_version`, precio cotizado, costo real, id del cobro en creaciones y la marca
  previa al POST que evita pagar dos veces.
- Archivos en R2 a través de `ObjectGate`, dentro de la biblioteca del negocio y fuera de la
  purga: `seasonal/{tenant}/{brand}/personajes/{id}-1.webp` (dibujo recortado) y `-2.webp`
  (imagen original del proveedor, sin pérdida, para recortar mejor sin volver a pagar).
- `creative_jobs`: tipo `sticker_character` con su sujeto `sticker_character_id` y un trabajo
  por dibujo. Va en su propio grupo `byteplus:seedream-5-0-pro`, con 20 cupos sembrados y 10
  en uso por defecto.
- Los stickers son filas de `brand_seasonal_media` con la temporada `productos` («De tus
  productos»), `source_kind = character`, `source_ref = {dibujo}:{mensaje}` y receta
  `k-animado` o `k-quieto`.

## Vocabulario para la pantalla

**Dibujo** es el personaje: se paga con 1 creación y se *dibuja*. **Sticker** es el dibujo con su
mensaje: es gratis y se *prepara*. «Pedir otro dibujo · 1 creación» y «Hacer de nuevo · gratis»
nunca deben compartir etiqueta (sugerencia de UX de la revisión).

## Lo que falta

- Las pantallas (reflex-ui-engineer), sobre esta puerta. Pendiente de la revisión de UX: recordar el último mensaje usado para preelegirlo en el paso 2 (hoy solo se preelige el producto).
- Una prueba pagada de punta a punta en producción con un negocio real, después del
  despliegue: el costo por dibujo sale del banco (US$0,045). El banco ya gastó US$0,315 de
  los US$0,50 autorizados.
- El recorte se midió en el banco: con contorno oscuro (`kawaii-v1` y `v3`), entre 0 y 0,43 %
  del borde quedó teñido de magenta. Sin contorno (`v2`), el 2,3 %. El producto usa `v3`. El
  mismo código, en numpy, se corrió en local sobre esas 6 imágenes: fueron menos de 1,2 s por
  imagen, sin ninguna llamada pagada.
