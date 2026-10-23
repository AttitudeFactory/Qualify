# Estrategia de contenido — Bianki y Polette

**Fecha:** 2026-08-16, oferta actualizada el 2026-10-23 · **Estado:** `[RECOMENDACIÓN — para decisión del fundador]`
**Pregunta que responde:** para estos dos negocios concretos, ¿qué ruta de imagen (`GENERATE` / `FROM_UPLOAD` / `RESTYLE_UPLOAD`), qué features del [Motor de Contenido de Marca](diseno-motor-contenido-marca.md) y qué APIs?
**Método:** lectura de los dos sitios en vivo (2026-08-16), con la oferta corregida por el fundador (2026-10-05 y 2026-10-23) + investigación de mercado sobre contenido de food & beverage local, backlash de imagen generada en restauración, y política de divulgación de IA de Meta para anunciantes.
**Convención de confianza:** `[V]` verificado contra fuente primaria · `[S]` fuente secundaria · `[H]` hipótesis del autor.

---

## 0. Veredicto en tres líneas

1. **`GENERATE` queda fuera para todo lo que sea producto**, en los dos negocios. No por gusto estético: por backlash documentado del consumidor, por política de anuncios de Meta, y porque el cliente entra al local y compara la foto con lo que le sirven.
2. **`FROM_UPLOAD` es el caballo de batalla** — foto real tuya dentro de tu marco de marca. Es la ruta que convierte una sesión de fotos en semanas de publicaciones.
3. **`RESTYLE_UPLOAD` sirve, pero partido en dos**, y solo la mitad es segura sin etiqueta.

---

## 1. Qué son los dos negocios

Bianki y Polette son **de un mismo dueño, que las maneja por separado, como dos marcas, con un solo
inicio de sesión** (afirmación del fundador, 2026-10-23).

| | **Bianki** | **Polette** |
|---|---|---|
| Qué vende | **Shawarma y ensaladas** (fundador, 2026-10-05 y 2026-10-23) | **Helados de yogur** (fundador, 2026-10-05 y 2026-10-23) |
| Dónde | Korner, San Cristóbal, Táchira `[V]` | Korner, San Cristóbal, Táchira — **puerta con puerta con Bianki** `[V]` |
| Precios y horario | Por confirmar con el fundador: los de agosto eran de la oferta anterior | Por confirmar |
| Cliente | Oficinistas y profesionales urbanos `[V]` (agosto) | Público joven, consumo social y compartible `[H]` |
| Promesa | *«Precio a la vista, porción en mano»* `[V]` (agosto, por confirmar) | La marca lleva el nombre de la hija del fundador `[V]` |
| Voz | Casual, con humor, léxico local («gocho») `[V]` | Cálida y personal, con narrativa de origen `[V]` |
| Otros activos | — | Tarjeta de sellos: 9 compras → 1 gratis `[V]` (agosto) |

**Dos observaciones que valen más que el resto del documento:**

**(a) Bianki tiene una promesa de honestidad visual escrita en su propio eslogan.** *«Precio a la vista, porción en mano»* es literalmente una promesa de que lo que ves es lo que recibes. Publicar un shawarma generado por IA no sería un desliz estético: **sería contradecir el posicionamiento en su propio idioma.** No hay argumento de marketing que sobreviva a eso.

**(b) Dos locales, una puerta al lado de la otra, un mismo dueño.** Un combo cruzado (shawarma o ensalada + helado de yogur) es una *historia*, no solo una promoción — y las historias de «los dos locales del Korner» se cuentan solas en una ciudad del tamaño de San Cristóbal. `[H]`, a confirmar con el fundador.

---

## 2. El hallazgo que decide la ruta: la imagen de comida generada por IA es activamente tóxica en 2026

Esto no es una preferencia de diseño. Es un hecho de mercado documentado, y llegó a su punto álgido **este mismo verano**:

- La discusión estalló en X a mediados de **julio de 2026**: las imágenes de comida generadas se perciben como *uncanny*, excesivamente brillantes y directamente poco apetecibles, y como creadoras de expectativas engañosas. `[S]`
- El daño no se queda en la estética. La conclusión que reportan los análisis de 2026 es demoledora para un negocio nuevo: **una vez el cliente sospecha que usas imágenes de IA, el supuesto pasa a ser «están escondiendo lo mala que se ve la comida de verdad»**. `[S]`
- Casos reales: un restaurante de San Francisco retiró sus imágenes generadas después de que la crítica online **escalara a vandalismo**; la plataforma de catering Forkable sustituyó fotos reales de restaurantes por generadas sin avisarles, y el escándalo fue el propio sector. `[S]`
- El argumento de los fotógrafos comerciales, que es el que aplica aquí: *«si generas imágenes de tu comida y no usas tu producto real, ¿cómo estableces confianza con tu cliente?»* `[S]`

**Por qué esto pega más fuerte en tu caso concreto:** eres un **local físico que abre**, en una ciudad donde el cliente entra andando. La distancia entre la foto y el plato es de cinco metros y treinta segundos. En un e-commerce que envía a otra ciudad, una foto embellecida tarda días en desmentirse; en el Korner se desmiente en el mostrador. Y el primer mes de un local es exactamente cuando se decide su reputación.

---

## 3. Y no es solo reputación: es política de anuncios de Meta

Aquí está la parte que convierte la recomendación en algo casi mecánico. Meta hizo obligatoria en 2026 la divulgación de contenido generado por IA para anunciantes, y **la línea que traza mapea con precisión sobre nuestras tres rutas**: `[S]`

| Operación sobre la imagen | ¿Requiere etiqueta «AI-generated»? |
|---|---|
| Corrección de color, recorte, *color grading*, limpieza de objetos, *upscaling* | **No** |
| IA que **genera el sujeto** de la imagen — una persona, un producto, una escena | **Sí, sin excepciones** |
| IA que **modifica sustancialmente o compone** contenido visual | **Sí** |

Y las consecuencias de saltárselo no son teóricas: **«Undisclosed AI Content» es en 2026 la tercera causa de rechazo de anuncios en Meta, con el 14% de todos los rechazos.** Primera infracción = *strike* y rechazo; segunda en 90 días = retención de 24h de la cuenta; tercera = suspensión. `[S]`

Traducido a nuestras rutas:

| Ruta | Etiqueta Meta | Riesgo de confianza | Veredicto |
|---|---|---|---|
| `FROM_UPLOAD` (composición determinista) | **Ninguna** — no interviene IA | **Cero** | ✅ Libre |
| `RESTYLE_UPLOAD` en modo *enhance* (luz, color, limpieza, upscale) | **Ninguna** | Bajo | ✅ Libre |
| `RESTYLE_UPLOAD` en modo *escena* (fondo nuevo, contexto compuesto) | **Sí** | Medio | ⚠️ Con etiqueta y criterio |
| `GENERATE` de un producto | **Sí** | **Alto** | ❌ No para producto |

### 3.1 La consecuencia de diseño: `RESTYLE_UPLOAD` hay que partirlo en dos

En el diseño del módulo `RESTYLE_UPLOAD` es una sola ruta. **Debe ser dos**, porque la frontera de Meta pasa justo por en medio:

- **`RESTYLE_ENHANCE`** — luz, color, contraste, limpieza de fondo desordenado, aumento de resolución. **No requiere etiqueta.** Es la ruta de más valor práctico para vosotros (ver §5).
- **`RESTYLE_SCENE`** — poner el producto en un fondo o contexto nuevo. **Requiere etiqueta.** Útil para un post de ambiente, nunca para «así es el plato».

Que la distinción viva en el enum y no en la cabeza del que redacta el brief es lo que evita el *strike*.

---

## 4. Lo que sí funciona en esta categoría, según la evidencia

- **El contenido de clientes reales supera al profesional pulido en un 40%, y convierte 4× más que el contenido de marca** (Stackla). `[S]` En food & beverage local, lo auténtico no es una estética: es el mecanismo.
- **Micro-influencers locales baten a los grandes.** Un creador gastronómico con 40.000 seguidores *en tu ciudad* mueve más tráfico medible que uno de 500.000 repartidos por el país. `[S]`
- **Postres y comida rápida son categorías de vídeo corto.** Lo que rinde: vídeos de 10 segundos del helado sirviéndose con sus toppings, el shawarma armándose, el detrás de cámaras de la preparación. Cadencia sugerida: 3–4 publicaciones/semana en Instagram, ≥1 TikTok/semana. `[H]`, extrapolado de la evidencia de agosto sobre bebidas.
- **Instagram se está indexando en Google.** Un Reel bien subtitulado con el nombre del local y la ubicación aparece en búsqueda. Para un local nuevo en una ciudad media, eso es descubrimiento gratis. `[S]`

---

## 5. Recomendación por negocio

### Bianki

| Prioridad | Ruta | Para qué |
|---|---|---|
| 1 | **`FROM_UPLOAD`** | La porción real en la mano, con el precio a la vista, dentro del marco de marca. **Es el eslogan hecho imagen** — y el diferenciador frente a cualquier competidor: enseñar el tamaño real de la porción es una ventaja que solo tiene quien no miente |
| 2 | **`RESTYLE_ENHANCE`** | Vas a fotografiar con teléfono, en un local pequeño, con la luz que haya. Corregir luz y color sobre tu foto real es exactamente la banda que Meta no obliga a etiquetar, y es lo que separa una foto de móvil de una foto vendible |
| 3 | `GENERATE` | Solo para piezas **sin producto**: una promo de catering B2B, una placa de horario, un fondo abstracto. Nunca un shawarma ni una ensalada |
| ❌ | `RESTYLE_SCENE` | No lo necesitas. Tu contexto real —el mostrador, la mano, el papel— es mejor activo que cualquier fondo compuesto |

### Polette

| Prioridad | Ruta | Para qué |
|---|---|---|
| 1 | **`FROM_UPLOAD`** | La copa real con tu marco. El helado **es** el contenido en esta categoría; el trabajo del módulo es vestirlo, no reinventarlo |
| 2 | **`RESTYLE_ENHANCE`** | El helado de yogur es blanco sobre blanco con toppings de color: con mala luz se ve gris y plano. Aquí el retoque tiene un ROI visible |
| 3 | `RESTYLE_SCENE` | Con moderación y **con etiqueta**: la copa en un contexto de ambiente para una publicación de temporada. Nunca como «así te llega» |
| ❌ | `GENERATE` de producto | El público joven es el que mejor detecta imagen generada y el que más castiga la impostura `[H]` |

**Y lo más rentable para Polette no lo hace este módulo:** un vídeo de teléfono del helado sirviéndose, con los toppings cayendo, dura 10 segundos y gana a cualquier estático que generemos. El módulo debe darte el **copy** y el **estático de marca**; la cámara del teléfono te da el Reel. Decir lo contrario sería venderte humo.

---

## 6. Qué APIs, en concreto

| Necesidad | Herramienta | Coste | Nota |
|---|---|---|---|
| Composición de marca (`FROM_UPLOAD`) | **Pillow**, con plantilla diseñada en Canva y exportada a PNG con el hueco transparente | **$0** | Sin API, sin red, determinista. La plantilla se autoría visual y se renderiza por código |
| Retoque (`RESTYLE_ENHANCE`) | **FLUX.2 [pro]** modo edit vía **fal.ai**; fallback **Seedream 4.0** | ~$0.03/img | Ancla del catálogo (ADR 32). Si algún día hace falta fidelidad máxima del producto: **Nano Banana Pro** (hasta 14 referencias), solo en fal |
| Escena (`RESTYLE_SCENE`) | Mismo par | ~$0.03/img | Con etiqueta de IA obligatoria en anuncios |
| Concepto (`GENERATE`) | **FLUX.2 [pro]** → **Seedream 4.0**; **Ideogram 3.0** si la pieza lleva texto legible | $0.03–0.09 | Uso marginal en estos dos negocios |
| Copy con voz de marca | **Claude `claude-opus-5`** | ~$0.01–0.03/pieza | Las dos marcas tienen voces muy distintas y muy definidas; es donde el perfil de voz se gana el sueldo |

**Coste realista mensual, `[H]`:** con 3–4 posts/semana por marca, unas 30 piezas/mes entre las dos. Si el 70% va por `FROM_UPLOAD` (gratis) y el 30% lleva retoque, son ~9 llamadas de imagen (~$0.30) más el copy (~$0.60). **Menos de un dólar al mes de API para las dos marcas.** El coste de este módulo no es el gasto en API — es tu tiempo construyéndolo.

---

## 7. La estrategia de apertura, concreta

Lo que necesitas no es un generador: es **convertir una sesión de fotos en semanas de publicaciones**. Ese es el trabajo real del módulo para ti.

1. **Una sesión de fotos, antes de abrir.** Teléfono, junto a la ventana, fondo neutro. 8–10 productos de Bianki, 6–8 sabores y combinaciones de Polette, más manos, mostrador y detalle de los toppings. Es media mañana de trabajo y es el activo del que vivirá todo el trimestre.
2. **Dos brand kits, dos plantillas.** Marcos distintos para cada marca — comparten local, no identidad. La plantilla es lo que hace que 10 fotos rindan como 40 posts.
3. **Semanas −2 y −1: expectativa.** `FROM_UPLOAD` sobre la foto del producto + copy de cuenta atrás. Aquí la voz de marca es todo el diferencial: Bianki con humor gocho, Polette con la historia del nombre.
4. **Semana 0: apertura.** Un combo cruzado entre los dos locales como pieza estrella, publicada en las dos cuentas cruzándose `[H]`. Es la historia que ninguna cadena puede contar.
5. **Desde la semana 1: UGC.** La tarjeta de sellos de Polette ya te da la excusa para pedir la foto. Repostear al cliente convierte 4× mejor que lo que produzcamos nosotros — y es gratis.
6. **Micro-influencers de San Cristóbal, no de Caracas.** Dos o tres, con producto a cambio.

---

## 8. Qué NO debe intentar resolver este módulo (para ti)

- **El vídeo.** La categoría premia Reels y tu teléfono los hace mejor y más rápido que cualquier API. La capa de vídeo de ADR 32 es v2 y para ti probablemente nunca sea prioritaria.
- **El UGC.** Es tu contenido de mayor conversión y no se genera: se pide y se repostea. Un *pipeline* de UGC sería la siguiente feature más rentable del producto — más que mejorar la generación.
- **Sustituir la cámara.** El módulo viste, ordena y escribe. La foto la tomas tú, y esa es precisamente la ventaja competitiva.

---

## 9. Consecuencias para el diseño del módulo

Cinco cambios concretos que esta investigación obliga sobre [`diseno-motor-contenido-marca.md`](diseno-motor-contenido-marca.md):

1. **`RESTYLE_UPLOAD` se parte en `RESTYLE_ENHANCE` y `RESTYLE_SCENE`.** La frontera de etiquetado de Meta pasa entre las dos (§3.1).
2. **`RESTYLE_ENHANCE` entra al MVP.** Es la ruta nº2 de los dos negocios reales; dejarla fuera deja cojos a ambos.
3. **`brand_kit.image_policy` deja de ser una idea y pasa a ser campo**: qué rutas se permiten por marca. Para Bianki y Polette, `GENERATE` de producto queda bloqueado por política, no por criterio del momento.
4. **`ContentDraft` necesita un flag `requires_ai_disclosure`**, derivado de la ruta usada y propagado en `ApprovedCreative`. Cuando la pieza vaya a un anuncio, el módulo de Ads tiene que saber que hay que marcarla — y el 14% de rechazos dice que olvidarlo es caro.
5. **La capa 1 del gate de fidelidad gana una regla:** si el brief pide una ruta bloqueada para esa marca, se rechaza **antes** de gastar. La política deja de depender de que alguien se acuerde.

---

## 10. Lo que hay que decidir

1. ¿Se acepta partir `RESTYLE_UPLOAD` en `ENHANCE` / `SCENE` y meter `ENHANCE` al MVP?
2. ¿`GENERATE` de producto se bloquea **por política de marca** en Bianki y Polette, o se deja a criterio pieza a pieza?
3. Siguen abiertas del hilo anterior: **(a)** descargar y publicar a mano vs **(b)** descargar → editar fuera → volver a subir → publicar desde Qualify.
4. ~~¿Un tenant con dos brands, o dos tenants?~~ **Respondida por el fundador (2026-10-23):** Bianki y Polette son de un mismo dueño, que las maneja **por separado, como dos marcas, con un solo inicio de sesión**. Cómo encaja con `1 login = 1 tenant = 1 negocio` está en el [diseño del motor](diseno-motor-contenido-marca.md) D14.
