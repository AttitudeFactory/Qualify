# Fotos por categoría en el generador (m-24985141)

`[2026-11-13 · rondas 11 a 14 · decidido por Deivid · implementado en Qualify/creative_state.py y Qualify/content_generator.py]`

Este documento explica cómo el dueño elige las fotos y los videos de una publicación en
Clip, Avatar, Imagen publicitaria y Carrusel, y cómo eso llega al brief. **El producto del
catálogo es opcional**. Se elige en «Tus productos» del selector o en la fila «Producto»
del panel. Todo lo demás se elige en el mismo selector: el *drawer* con «Tus productos ·
Tu Galería · Subir · Publicaciones · Inspiración».

## 1. Las categorías

Cada foto de referencia lleva una categoría, que se cambia con el mismo selector en todos
los tipos:

| Lo que ve el dueño | Rol guardado | Para qué sirve |
|---|---|---|
| Producto | `product` | Es el producto que tiene que verse igual. |
| Fondo | `place` | Es el fondo de la escena. Hay uno solo. |
| Estilo | `style` | Es una guía de composición y aspecto, nunca el producto. |

Hasta la ronda 12, «Fondo» se llamaba «Lugar». Desde la ronda 13 solo cambió la
etiqueta: el rol guardado sigue siendo `place`, así que los borradores y los prompts no
cambian.

**En Avatar e Imagen publicitaria, solo una foto puede ser el Fondo.** Si el dueño marca otra, la anterior pasa a Estilo
y se muestra el aviso «Ahora esta es la foto de fondo. La anterior quedó como Estilo.».
Una foto nunca cambia de lugar en la lista al cambiar de categoría: la lista guarda su
propio orden.

**Categoría por defecto según de dónde viene la foto (Avatar e Imagen publicitaria):**
- Producto del catálogo, una foto de producto de la Galería o una subida: «Producto».
- Una foto del negocio de la Galería: «Fondo». Si ya hay un Fondo, entra como «Estilo».
- Inspiración, Pinterest o Publicaciones: «Estilo».

**El Clip tiene sus propias reglas, que no cambiaron:**
- Admite varias fotos como «Fondo», porque son referencias para el modelo de video y no un
  fondo único.
- Inspiración y Publicaciones entran como «Estilo». Todo lo demás entra como «Producto»,
  también Pinterest.
- Desde la Galería, una foto de producto entra como «Producto» y una del negocio como
  «Fondo».

**En el Carrusel** no hay categorías por foto: cada diapositiva elige su Foto y su Estilo,
y el Fondo es uno solo para todo el carrusel (§3).

## 2. Por tipo

### Clip
Tiene una sola sección, «Referencias (opcional)», y un solo botón, «Elegir fotos,
videos o audios». Cada foto lleva su categoría y los videos y audios van como
referencias. El brief manda `clip_image_keys` y `clip_image_roles`.

### Avatar (humano y animado)
Funciona como el Clip: una sola sección «Referencias (opcional)» con un botón, «Elegir
fotos y videos». Las fotos llevan su categoría y el video de referencia va en la misma
lista. No queda ningún bloque de fondo aparte.

### Imagen publicitaria
Tiene la misma lista, «Referencias (opcional)», solo con fotos y el botón «Elegir fotos
para tu publicación». `ad_mode` se deduce de lo que haya:

| Lo que hay en la lista | `ad_mode` |
|---|---|
| Producto y Fondo | `both` |
| Solo Producto | `product` |
| Solo Fondo | `background` |
| Nada | `scene` |

### Plantilla
No cambia: no usa fondo ni categorías.

### Traducción al brief (Avatar e Imagen)

| Categoría | Campo del brief |
|---|---|
| Fondo | `background_key` |
| Producto | `product_keys`, con `product_image_roles` = `product` |
| Estilo | `product_keys`, con `product_image_roles` = `composition` |

## 3. Carrusel: diapositiva por diapositiva (ronda 14, «Uno para todo»)

No hay lista arriba ni reparto automático. Cada diapositiva generada o animada elige,
dentro de «Lo que sale en esta diapositiva»:

- **Foto:** la foto del producto de esa diapositiva. Se elige con «Elegir foto» o
  «Cambiar foto», que abre el selector en «Tus productos», y se quita con «Quitar foto».
- **Estilo:** la guía, con «Elegir estilo», «Cambiar estilo» y «Quitar estilo».
- **Movimiento:** solo en las diapositivas animadas. Es un video, que va a
  `reference_video_key`.
- **Fondo:** hay uno solo para todo el carrusel (`background_key`). Se puede elegir desde
  cualquier diapositiva y se ve igual en todas, con el aviso «El fondo es el mismo en
  todas las diapositivas.». Cada diapositiva tiene su interruptor «Usar el fondo», que
  manda `use_background` y viene encendido. Si no hay fondo, el interruptor no aparece.

El selector se cierra apenas el lugar recibe lo que se eligió, y el foco vuelve al botón
que lo abrió.

**Traducción de cada diapositiva:**

| La diapositiva tiene | `product_index` | `guide_product_index` | `guide_alone` |
|---|---|---|---|
| Solo Foto | la foto | — | False |
| Foto y Estilo | el estilo | la foto | False |
| Solo Estilo | el estilo | — | True |
| Nada | — | — | False |

`product_keys` lleva todas las fotos y todos los estilos que usan las diapositivas, sin
repetir. `product_image_roles` dice `product` para las fotos y `composition` para los
estilos. El brief se valida con `MediaInputs` y `carousel_scene_plans`.

**Borradores viejos:** si una diapositiva de antes tiene como foto una imagen de
Inspiración y ningún estilo propio (la guía del 2026-11-03), esa imagen se lee como su
estilo y el producto que había elegido, como su foto.

## 4. La fila «Producto» del panel

La fila va justo encima de las opciones del panel. Muestra todas las referencias elegidas
como burbujas superpuestas (`.q-avatar-stack`):
- se ven hasta 4, o 3 y una «+N» que se lee «y N referencias más»;
- el grupo se lee «N referencias elegidas»;
- en la columna angosta de escritorio se ven al menos 2 burbujas de 24 px y su «+N».

El nombre del producto nunca se corta ni se monta sobre el botón. Su botón dice «Cambiar»
o «Elegir producto» y abre «Tus productos».

## 5. Textos

| Dónde | Texto |
|---|---|
| Selector de categoría | Producto · Fondo · Estilo |
| Aviso de un solo fondo | Ahora esta es la foto de fondo. La anterior quedó como Estilo. |
| Referencias del Avatar | Todo lo que el video debe seguir: fotos de tu producto, el fondo, un estilo y, si quieres, un video de referencia. |
| Referencias de la Imagen | Elige qué es cada foto: tu producto, el fondo (solo una) o un estilo para inspirar la imagen. |
| Diapositiva | Lo que sale en esta diapositiva · Elegir/Cambiar/Quitar foto, estilo, movimiento, fondo · Usar el fondo |
| Fondo del carrusel | El fondo es el mismo en todas las diapositivas. |
