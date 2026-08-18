# Estrategia de contenido — Bianki Gaucha y Polet Bubble Tea

**Fecha:** 2026-08-16 · **Estado:** `[RECOMENDACIÓN — para decisión del fundador]`
**Pregunta que responde:** para estos dos negocios concretos, ¿qué ruta de imagen (`GENERATE` / `FROM_UPLOAD` / `RESTYLE_UPLOAD`), qué features del [Motor de Contenido de Marca](diseno-motor-contenido-marca.md) y qué APIs?
**Método:** lectura de los dos sitios en vivo (2026-08-16) + investigación de mercado sobre contenido de food & beverage local, backlash de imagen generada en restauración, y política de divulgación de IA de Meta para anunciantes.
**Convención de confianza:** `[V]` verificado contra fuente primaria · `[S]` fuente secundaria · `[H]` hipótesis del autor.

---

## 0. Veredicto en tres líneas

1. **`GENERATE` queda fuera para todo lo que sea producto**, en los dos negocios. No por gusto estético: por backlash documentado del consumidor, por política de anuncios de Meta, y porque el cliente entra al local y compara la foto con el vaso.
2. **`FROM_UPLOAD` es el caballo de batalla** — foto real tuya dentro de tu marco de marca. Es la ruta que convierte una sesión de fotos en semanas de publicaciones.
3. **`RESTYLE_UPLOAD` sirve, pero partido en dos**, y solo la mitad es segura sin etiqueta.

---

## 1. Qué son los dos negocios `[V]`

| | **Bianki Gaucha** | **Polet Bubble Tea** |
|---|---|---|
| Qué vende | Comida callejera uruguaya/brasileña: pizza al corte, chivitos, salgados. Más suscripción de jugos y catering de oficina | Bubble tea: milk tea, fruit tea, toppings (tapioca, popping boba) |
| Dónde | Korner, San Cristóbal, Táchira · 7:00–21:00 | Korner, San Cristóbal, Táchira · 11:00–21:00 — **puerta con puerta con Bianki** |
| Precios | $1.20–$7.00 · combos $3–8 · catering $9–40/semana | $4.00 la bebida · Combo Dúo $7 · **Combo Vecino (bebida + pizza) $6** · Pack Fiesta $35 |
| Cliente | Oficinistas y profesionales urbanos; B2B para catering | Millennials y Gen Z; consumo social y compartible |
| Promesa | *«Precio a la vista, porción en mano»* | *«Descubierto lejos, preparado en casa»* — la marca lleva el nombre de la hija del fundador |
| Voz | Casual, con humor, léxico local («la esquina gaucha», «gocho») | Cálida y personal, con narrativa de origen |
| Otros activos | — | Tarjeta de sellos: 9 compras → 1 gratis |

**Dos observaciones que valen más que el resto del documento:**

**(a) Bianki tiene una promesa de honestidad visual escrita en su propio eslogan.** *«Precio a la vista, porción en mano»* es literalmente una promesa de que lo que ves es lo que recibes. Publicar una pizza generada por IA no sería un desliz estético: **sería contradecir el posicionamiento en su propio idioma.** No hay argumento de marketing que sobreviva a eso.

**(b) El Combo Vecino ya existe y es un activo de contenido infrautilizado.** Dos marcas distintas, una puerta al lado de la otra, un combo compartido a $6. Eso no es una promoción: es una *historia* — y las historias de "los dos locales del Korner" se cuentan solas en una ciudad del tamaño de San Cristóbal.

---

## 2. El hallazgo que decide la ruta: la imagen de comida generada por IA es activamente tóxica en 2026

Esto no es una preferencia de diseño. Es un hecho de mercado documentado, y llegó a su punto álgido **este mismo verano**:

- La discusión estalló en X a mediados de **julio de 2026**: las imágenes de comida generadas se perciben como *uncanny*, excesivamente brillantes y directamente poco apetecibles, y como creadoras de expectativas engañosas. `[S]`
- El daño no se queda en la estética. La conclusión que reportan los análisis de 2026 es demoledora para un negocio nuevo: **una vez el cliente sospecha que usas imágenes de IA, el supuesto pasa a ser «están escondiendo lo mala que se ve la comida de verdad»**. `[S]`
- Casos reales: un restaurante de San Francisco retiró sus imágenes generadas después de que la crítica online **escalara a vandalismo**; la plataforma de catering Forkable sustituyó fotos reales de restaurantes por generadas sin avisarles, y el escándalo fue el propio sector. `[S]`
- El argumento de los fotógrafos comerciales, que es el que aplica aquí: *«si generas imágenes de tu comida y no usas tu producto real, ¿cómo estableces confianza con tu cliente?»* `[S]`

**Por qué esto pega más fuerte en tu caso concreto:** eres un **local físico que abre**, en una ciudad donde el cliente entra andando. La distancia entre la foto y el vaso es de cinco metros y treinta segundos. En un e-commerce que envía a otra ciudad, una foto embellecida tarda días en desmentirse; en el Korner se desmiente en el mostrador. Y el primer mes de un local es exactamente cuando se decide su reputación.

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
- **Micro-influencers locales baten a los grandes.** Un creador gastronómico con 40.000 seguidores *en tu ciudad* mueve más tráfico medible que uno de 500.000 repartidos por el país. En bubble tea específicamente se reportan aumentos de **20–30% de tráfico peatonal** vía micro-influencers. `[S]`
- **Bubble tea es una categoría de vídeo corto.** Lo que rinde: vídeos de 10 segundos de una combinación de toppings nueva, el vertido, el detrás de cámaras de la preparación. Cadencia sugerida: 3–4 posts/semana en Instagram, ≥1 TikTok/semana. `[S]`
- **Instagram se está indexando en Google.** Un Reel bien subtitulado con el nombre del local y la ubicación aparece en búsqueda. Para un local nuevo en una ciudad media, eso es descubrimiento gratis. `[S]`

---

## 5. Recomendación por negocio

### Bianki Gaucha

| Prioridad | Ruta | Para qué |
|---|---|---|
| 1 | **`FROM_UPLOAD`** | La porción real en la mano, con el precio a la vista, dentro del marco de marca. **Es el eslogan hecho imagen** — y el diferenciador frente a cualquier competidor: enseñar el tamaño real de la porción es una ventaja que solo tiene quien no miente |
| 2 | **`RESTYLE_ENHANCE`** | Vas a fotografiar con teléfono, en un local pequeño, con la luz que haya. Corregir luz y color sobre tu foto real es exactamente la banda que Meta no obliga a etiquetar, y es lo que separa una foto de móvil de una foto vendible |
| 3 | `GENERATE` | Solo para piezas **sin producto**: una promo de catering B2B, una placa de horario, un fondo abstracto. Nunca un chivito |
| ❌ | `RESTYLE_SCENE` | No lo necesitas. Tu contexto real —el mostrador, la mano, el papel— es mejor activo que cualquier fondo compuesto |

### Polet Bubble Tea

| Prioridad | Ruta | Para qué |
|---|---|---|
| 1 | **`FROM_UPLOAD`** | El vaso real con tu marco. La bebida **es** el contenido en esta categoría; el trabajo del módulo es vestirla, no reinventarla |
| 2 | **`RESTYLE_ENHANCE`** | Bubble tea es color y capas: la separación entre leche, té y perlas se pierde con mala luz. Aquí el retoque tiene un ROI visible |
| 3 | `RESTYLE_SCENE` | Con moderación y **con etiqueta**: la bebida en un contexto de ambiente para un post estacional. Nunca como "así te llega" |
| ❌ | `GENERATE` de bebida | El público de bubble tea es Gen Z: es el demográfico que mejor detecta imagen generada y el que más castiga la impostura |

**Y lo más rentable para Polet no lo hace este módulo:** un vídeo de teléfono del vertido, con las perlas cayendo, dura 10 segundos y gana a cualquier estático que generemos. El módulo debe darte el **copy** y el **estático de marca**; la cámara del teléfono te da el Reel. Decir lo contrario sería venderte humo.

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

1. **Una sesión de fotos, antes de abrir.** Teléfono, junto a la ventana, fondo neutro. 8–10 productos de Bianki, 6–8 bebidas de Polet, más manos, mostrador y detalle de las perlas. Es media mañana de trabajo y es el activo del que vivirá todo el trimestre.
2. **Dos brand kits, dos plantillas.** Marcos distintos para cada marca — comparten local, no identidad. La plantilla es lo que hace que 10 fotos rindan como 40 posts.
3. **Semanas −2 y −1: expectativa.** `FROM_UPLOAD` sobre la foto del producto + copy de cuenta atrás. Aquí la voz de marca es todo el diferencial: Bianki con humor gocho, Polet con la historia del nombre.
4. **Semana 0: apertura.** El Combo Vecino como pieza estrella, publicada en las dos cuentas cruzándose. Es la historia que ninguna cadena puede contar.
5. **Desde la semana 1: UGC.** La tarjeta de sellos de Polet ya te da la excusa para pedir la foto. Repostear al cliente convierte 4× mejor que lo que produzcamos nosotros — y es gratis.
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
3. **`brand_kit.image_policy` deja de ser una idea y pasa a ser campo**: qué rutas se permiten por marca. Para Bianki y Polet, `GENERATE` de producto queda bloqueado por política, no por criterio del momento.
4. **`ContentDraft` necesita un flag `requires_ai_disclosure`**, derivado de la ruta usada y propagado en `ApprovedCreative`. Cuando la pieza vaya a un anuncio, el módulo de Ads tiene que saber que hay que marcarla — y el 14% de rechazos dice que olvidarlo es caro.
5. **La capa 1 del gate de fidelidad gana una regla:** si el brief pide una ruta bloqueada para esa marca, se rechaza **antes** de gastar. La política deja de depender de que alguien se acuerde.

---

## 10. Lo que hay que decidir

1. ¿Se acepta partir `RESTYLE_UPLOAD` en `ENHANCE` / `SCENE` y meter `ENHANCE` al MVP?
2. ¿`GENERATE` de producto se bloquea **por política de marca** en Bianki y Polet, o se deja a criterio pieza a pieza?
3. Siguen abiertas del hilo anterior: **(a)** descargar y publicar a mano vs **(b)** descargar → editar fuera → volver a subir → publicar desde Qualify.
4. Un local es una `brand` si tiene identidad social propia ([modelo de negocio](modelo-negocio-operador-multi-emprendimiento.md) §1). Bianki y Polet la tienen, y comparten país, moneda y propiedad → **un tenant, dos brands**. Coincide con el gate `LOY-00` de la iniciativa Loyalty; conviene cerrarlo una sola vez para las dos.
