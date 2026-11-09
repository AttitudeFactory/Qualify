# Seedream: conexión cortada a los ~60 s y tamaño de salida — 3 de noviembre de 2026

Ticket: m-24820842. Autor: creative-engineer. No hubo llamadas pagadas: todo se diagnosticó
con el registro, una lectura de solo lectura de la base de datos y lecturas de R2.

## Qué pasó

Una galería (diapositiva 1, Seedream 5.0 lite, 4 imágenes de referencia, salida 1728x2160)
falló dos veces igual: borradores `b9c3ec5e…` y `3dbfe77c…`. El error fue `RemoteProtocolError:
Server disconnected without sending a response` y la pieza terminó como `provider_error`.

- Cada intento duró 195,6 s y 194,1 s en total: **3 intentos × ~63 s + 6 s de espera**. Cada
  intento se cortó a unos 60 s sin respuesta, mientras se generaba la imagen. El límite de
  lectura del cliente era de 180 s.
- **El pedido estaba bien:**
  - el cuerpo medía ~1,1 MB, con un límite documentado de 30 MB por imagen;
  - el volante que sí funcionó ese día llevaba 6 referencias y ~2,1 MB;
  - los parámetros eran los mismos.
- **Costos:**
  - Cada nuevo intento volvía a pagar las dos llamadas a Claude (~USD 0,10), porque una falla
    síncrona de Seedream no congela la copia.
  - Seedream pudo haber cobrado imágenes que nunca llegaron, por los 3 intentos. No se puede
    verificar desde aquí.

## Cambios

1. **Reintentos de Seedream** (`byteplus_ark._post`, `SEEDREAM_MAX_POST_ATTEMPTS = 2`,
   `SEEDREAM_FAST_DROP_SECONDS = 10`).
   - Una conexión caída se reenvía **una sola vez**, y solo si cayó en menos de 10 s: en ese
     caso el proveedor no había empezado.
   - Un intento que corrió ~60 s nunca se reenvía: puede estar generándose y cobrándose.
   - Seedance conserva sus 3 intentos: su POST solo crea la tarea y responde de inmediato.
   - Cada intento queda en el registro (INFO) con su duración y su resultado.
2. **Mensaje al dueño.** Cuando Seedream corta la conexión o no responde
   (`SeedreamDisconnected`), el dueño lee: «El generador de imágenes tardó demasiado y cortó la
   conexión. Tu pedido quedó guardado: vuelve a intentarlo en unos minutos.». La razón de la
   falla sigue siendo `provider_error`.
3. **Tamaño de salida** (decisión del fundador): unos 2 MP, nunca por debajo del tamaño
   publicado. Se lee al generar, así que aplica a toda generación nueva, incluso de briefs
   viejos.

   | Proporción | Antes | Ahora (pedido) | Lo que se envía con Seedream 5.0 lite / 4.5 |
   |---|---|---|---|
   | 4:5 | 1728x2160 | 1280x1600 | 1728x2160 |
   | 1:1 | 2048x2048 | 1280x1280 | 1920x1920 |
   | 9:16 | 1440x2560 | 1080x1920 | 1440x2560 |
   | 3:4 | 1728x2304 | 1248x1664 | 1680x2240 |
   | Avatar de marca (1:1) | 2048x2048 | 1280x1280 | 1920x1920 |

   **Importante:** según `image-generation-api.md` (leído el 2026-11-03), Seedream 5.0 lite y
   4.5 piden al menos **3.686.400 píxeles** (2560x1440). Solo 5.0 pro, 5.0 flash y 4.0 bajan a
   921.600. Para que nunca se rechace un pedido, el adaptador (`seedream_size`) sube el tamaño
   al mínimo de cada modelo, con las mismas proporciones y en múltiplos de 16.

   Con el modelo configurado hoy (5.0 lite, el predeterminado) el ahorro real es solo en 1:1,
   un 12 % menos de píxeles. Para renderizar ~45 % menos píxeles hay que pasar a Seedream
   5.0 flash o pro. Eso es un cambio de modelo: se decide aparte y se mide con
   `qualify-measure`.

## Pendiente

- Confirmar en la consola de BytePlus si los intentos cortados se cobraron.
- Que un reintento no vuelva a pagar a Claude: hay que congelar la copia y la selección por
  revisión, lo que trae la cola de ADR 41.
- Probar `stream: true` con una sonda pagada (~USD 0,04), si el fundador la autoriza.

## Prueba pagada: `stream: true` (2026-11-03, autorizada por el fundador)

**Qué se pidió.** Se reconstruyó exacta la diapositiva 1 del borrador `a3059dc9…`, cuyo intento
real también se cortó: «attempt 1: RemoteProtocolError in 63.6 s».

- Mismo texto de la traza (2814 caracteres) y las mismas 4 referencias: foto de producto,
  guía de composición, fondo y el logo de la ranura imagotipo.
- Modelo `seedream-5-0-lite-260128`. Se pidió 1280x1600; el adaptador lo subió al mínimo del
  modelo y se envió 1728x2160.
- Mismos parámetros, más `stream: true`. Cuerpo de 0,74 MB.
- Llave de la plataforma (no hay llave de evaluación en `.env`). Una sola llamada.

**Lo que dice la documentación.** `image-generation-streaming-responses.md` describe solo
estos eventos: error, `image_generation.partial_succeeded` (la imagen),
`image_generation.partial_failed` e `image_generation.completed` (uso). No menciona eventos de
progreso ni de «latido» mientras se genera.

**Resultado.**
- **El servidor cortó la conexión a los 62,8 s sin enviar nada**: ni encabezados HTTP, ni
  eventos, ni imagen.
- El modo `stream` **no evita el corte**: la respuesta empieza recién cuando la imagen está
  lista, y el corte llega antes.
- No hay imagen y no se reportó uso.
- **Costo:** como máximo USD 0,035 si BytePlus cobró la imagen que no entregó. Hay que
  confirmarlo en la consola.
- **Evidencia:** `%TEMP%\pb\stream-probe-events.json` (línea de tiempo) y el script
  `%TEMP%\pb\stream_probe.py`, ambos fuera del repositorio.
- No hay proxy configurado en el equipo.

**Conclusión.** El corte de ~60 s está en el camino hacia BytePlus (su puerta de entrada u
otro equipo intermedio), no en nuestro cliente. Con este pedido, la generación de Seedream
5.0 lite tarda más de 60 s.

**Próximos pasos:**
1. Revisar en producción (Hetzner) cuánto tardan los intentos de Seedream; el registro ya lo
   anota por intento. Así se sabe si el corte depende de la red local.
2. Generar en menos de 60 s:
   - Seedream 5.0 flash o pro con 1280x1600 (45 % menos píxeles); es un cambio de modelo y se
     mide aparte;
   - o menos referencias por escena.
3. Preguntar a BytePlus si existe un límite de 60 s en `/images/generations` síncrono, y si
   hay una variante asíncrona.

## Prueba en vivo de una galería (2026-11-03, borrador `320257e3…`, Nibbles)

**Qué pasó.** Diapositiva 1: Seedream respondió en 61,6 s. Diapositiva 2: imagen en 39,8 s y su
video de Seedance (USD 0,53). Diapositiva 3: corte a los 62,8 s. La galería entera falló
(`provider_error`) y se perdieron USD 0,66 ya pagados; volver a intentarlo pagaba todo otra vez.
Cada escena llevó 4 referencias, porque la guía de Inspiración de la diapositiva 1 viajaba
también a las diapositivas 2 y 3.

**Cambios (aprobados por el fundador, sin llamadas pagadas):**

1. **Una guía de Inspiración solo sirve a su propia diapositiva**
   (`qualify_creative.scene_plan.carousel_scene_plans`). La diapositiva de la guía lleva la foto
   del producto elegida (`guide_product_index`) y la guía. Una diapositiva de producto lleva
   solo su foto (más el fondo y los recursos de marca, si los tiene). En el caso del borrador
   `320257e3`, las diapositivas 2 y 3 pasan de 4 a 3 referencias. El volante en galería
   (`flyer_scene_plans`) sigue compartiendo la guía con todas sus imágenes: ahí la guía no
   tiene una imagen propia.
2. **Una diapositiva que falla ya no tira las terminadas.** Las diapositivas generadas o
   animadas que ya estaban hechas quedan en R2 y en la versión fallida del borrador
   (`image_assets` con proveedor, modelo, prompt y costo). El dueño lee, por ejemplo: «Ya
   guardamos 2 de 3 diapositivas. Al volver a intentarlo, solo se crean las que faltan.», y
   tiene el botón «Crear las que faltan». Ese botón crea una nueva revisión que reutiliza el
   texto (no se llama a Claude otra vez) y las diapositivas guardadas; solo las que faltan
   llegan a Seedream o Seedance.

**Precio de «Crear las que faltan» (decisión del fundador, 2026-11-03, confirmada el
2026-11-04).** El reintento cobra **lo mismo que costó la galería original**, que es justo lo
que se devolvió cuando falló (CREAR-5), aunque solo se paguen al proveedor las diapositivas que
faltan. Es el peso de la galería (`weight_for`, tabla `pesos-creaciones-v2.json`): **1 creación
hasta 3 diapositivas generadas, 2 hasta 7 y 3 hasta 10**, más, si tiene diapositivas animadas,
**una vista previa por cada una** (con la tabla v1, que no cuenta videos aparte, las creaciones
de esos videos). Los videos del mes de las diapositivas animadas se cobran al aprobar, como en
cualquier galería. No es «1 creación» fija: una galería de 4 a 10 diapositivas cuesta 2 o 3.
Si el reintento también falla, se devuelve igual. El cobro es uno por
revisión (`draft_id`, `revision`): un doble clic no cobra dos veces. En el código:
`ContentService.finish_gallery` (`packages/api/src/qualify_api/creative/service.py`).

**Pendiente.** La cola de ADR 41 (`QUALIFY_CREATIVE_DISPATCHER=queue`) no ofrece este reintento
todavía: allí las diapositivas se guardan, pero el botón no aparece.
