# Stickers animados y videos cortos de la marca en WhatsApp — opciones para decidir

**Ticket:** m-24955647 · **Estado:** `[DECIDIDO 2026-11-08]` — ver §9 ·
**Autor:** principal-architect, 2026-11-08 · **Formato:** `qualify-business-decisions`.

Etiquetas de evidencia: `[V]` código, datos o tabla de precios en disco, o hecho de Meta ya
verificado; `[S]` derivado de un `[V]` con una fórmula no medida para ese caso, o fuente externa;
`[H]` estimación. Un número calculado hereda la etiqueta más débil. `[F]` = decisión del fundador.

## 1. El marco

**La pregunta, en palabras del fundador:** ¿cómo le damos al negocio stickers animados y videos
cortos sin sonido con su marca, que pueda mandar en el chat de WhatsApp y renovar por temporada?

**Qué buscamos esta vez:** **aprender** si los clientes de Bianki responden a esto, gastando lo
mínimo. Nadie lo ha pedido con dinero en la mano; es una idea del fundador para que el chat de un
negocio pequeño se vea «de marca» sin diseñador.

**Para quién:** dueños de negocios de comida en CO/VE/UY (hoy Bianki, shawarma; Polette, helados),
que atienden desde el celular, sin presupuesto para diseñador ni agencia. El dueño no edita nada:
aprueba o pide otro.

**Qué ve el cliente en WhatsApp** (límites de Meta verificados el 2026-11-05 `[V]`):

| Formato | Archivo | Cómo se ve |
|---|---|---|
| Sticker animado | WebP animado, ≤ 500 KB (512×512 es la medida de sticker de Meta `[S]`) | Se anima solo, sin marco ni burbuja, si el fondo es transparente; si no, es un cuadrado pegado |
| Video corto | MP4, ≤ 16 MB | Burbuja con miniatura; se reproduce al tocar |
| GIF, SVG, Lottie | — | **No se aceptan** como mensaje animado `[V]` |

Un MP4 mudo de 3–5 s pesaría 200–600 KB `[H]`, sin medir.

**Decisiones del fundador que ya son restricciones `[F]`:** FFmpeg aceptado en producción para
videos cortos (2026-11-06); doble aprobación como toda pieza (el dueño aprueba antes de que algo
se pueda mandar); se regenera por temporada (Navidad, Día de la Madre…) **conservando las
anteriores**; «Stickers» y «Videos cortos» aparecen en el menú de envío del chat solo cuando el
negocio tiene algo listo.

**Lo que implica «renovable por temporada»:**

- **Guardado:** las de temporadas pasadas se conservan, así que **no pueden caer en la regla de
  90 días de ADR 39** (que borra `t/{tenant}/generated/{draft}/` 90 días después del último uso;
  un sticker de Navidad no se usa de enero a noviembre). Hace falta una regla propia: biblioteca
  por temporada fuera de `PURGEABLE_ROOTS`, bajo un prefijo sin el bloqueo de `t/` (como hizo la
  Galería con `gallery/{tenant}/…`, m-24971181), y que el dueño pueda archivar. Es una enmienda a
  ADR 39, no un cambio silencioso.
- **Volumen:** ~6 stickers (≤ 500 KB) + ~4 videos (≤ 0,6 MB) por temporada y negocio ≈ 5,4 MB;
  4 temporadas al año ≈ 22 MB/negocio/año `[H]`; 30 negocios ≈ 0,65 GB → R2 a US$0,015/GB-mes
  ≈ US$0,01/mes `[S]`. Filas: ~40 por negocio al año en Postgres (ADR 31, nada nuevo). El costo
  no está en guardar.
- **Aprobación:** cada temporada es un lote nuevo que pasa por «Por aprobar». Lo no aprobado nunca
  aparece en el menú. Esto es **más estricto** que las piezas de hoy, que se pueden mandar sin
  aprobar con un aviso (`docs/ux-whatsapp-enviar-imagen.md` §2.2): así lo pidió el fundador.
- **Ventana de 24 h:** stickers y videos se mandan dentro de una conversación abierta, igual que
  las fotos de hoy; fuera de la ventana solo salen plantillas (un sticker no puede ir en una
  plantilla `[S]`, docs de Meta, sin verificar en vivo — ADR 25).

## 2. Lo que hay en disco hoy

- **FFmpeg ya está en la imagen `app`** (`deploy/Dockerfile`, m-24957792: +385 MB en disco) y ya lo
  usa `media-worker` (ADR 47, `mem_limit` 768m) para los videos de la Galería `[V]`. Opciones que
  usan FFmpeg en ese worker **no agregan runtime ni imagen**.
- **Remotion** (`packages/render`): dos plantillas, `hello_world` y `promo_producto`; salida MP4
  H.264 y PNG; **sin FFmpeg propio** (Remotion trae el suyo) y sin salida WebP `[V]`. En producción
  es el perfil opcional `render`, **apagado salvo que se active**, y el comentario del compose y
  `docs/despliegue-hetzner.md` dicen que activarlo pide un servidor más grande (Chromium ~1 GB por
  render, `mem_limit` 1536m) `[V]`. El compose describe un VPS de 3,8 GB compartido con Pedidos,
  con los topes de memoria ya sobrecomprometidos (~4,75 GiB de topes) `[V]`.
- **Licencia de Remotion:** la tabla de precios pone `remotion_selfhost` = US$0,00 «mientras el
  equipo sea de ≤ 3» y `docs/plan-mvp-plantillas-remotion.md` fija el disparador en 4 personas
  (Automators a US$100/mes) `[V]`. **Hoy el equipo es de 5** (Herwin, Darwin, Yesika, Deivid, Raul):
  ese 0,00 probablemente ya no es cierto. Lo marco como desvío a revisar, sea cual sea la elección.
- **Seedance** está cableado en `qualify_creative/adapters/byteplus_ark.py` (`seedance-1-0-pro-fast`,
  `dreamina-seedance-2-0-mini`, `dreamina-seedance-2-5`) con precios en `pricing_data/v7.json` `[V]`.
  Un borrador 480p de 5 s con 2.5 costó **≈ US$0,53** (49.673 tokens × 10,70/M, medido;
  `docs/modelos-generativos/seedance-2-5.md`) `[V]`. Con `seedance-1-0-pro-fast` (US$1,0/M) la
  misma fórmula da ≈ 48.000 tokens ≈ **US$0,05** `[S]` (fórmula medida en 2.5, no en 1.0).
- **WhatsApp:** el módulo ya **recibe** stickers (`whatsapp/models.py`) y manda fotos JPEG/PNG
  ≤ 5 MB (`whatsapp/attachments.py`); **no manda** ni stickers ni video todavía `[V]`.

## 3. Opciones

| | De dónde sale la animación | Cadena | Dónde corre FFmpeg · peso en el servidor | Costo por pieza | Tiempo por pieza | Calidad / marca | Riesgos | Qué bloquea |
|---|---|---|---|---|---|---|---|---|
| **A. No hacerlo** | — | — | — | US$0 | — | El chat sigue con fotos y texto | Ninguno técnico; se pierde la prueba | Nada |
| **B. Solo videos cortos con lo que ya hay** | Imágenes ya aprobadas (piezas, catálogo) con un movimiento simple: acercamiento lento, paneo, fundido entre 2–3 fotos, logo al final | Pieza aprobada → `media-worker` → FFmpeg (`zoompan`/`xfade`) → MP4 mudo 720p, 3–5 s → R2 → «Por aprobar» | Imagen `app`, `media-worker` ya existente · ~5–15 s de CPU por video, 1 a la vez, dentro de sus 768m `[H]` | Proveedor US$0 `[V]`; CPU y R2 despreciables `[S]` | Segundos `[H]` | Fiel: son las fotos y el logo reales. Poco vistoso; no da stickers | Que se vea «presentación de fotos»; peso real sin medir | Nada: no toca Remotion ni proveedores |
| **C. Plantillas Remotion** | Plantillas nuevas en `packages/render` (logo que rebota, precio que entra, saludo de temporada) con colores y tipografía del Brand Kit, fondo transparente para stickers | Props de marca → render Remotion → MP4 + secuencia PNG con alfa → FFmpeg → WebP animado 512×512 ≤ 500 KB → R2 → «Por aprobar» | MP4 en Remotion; WebP en `media-worker` (Remotion no exporta WebP) · **activa el perfil `render`**: ~1–1,5 GB más de RAM → pide servidor más grande `[V]` | Proveedor US$0; **licencia probablemente ya de pago** (US$100/mes por el equipo de 5 `[S]`, sin confirmar); servidor mayor ≈ + algunos US$/mes `[H]` | 20–90 s por render en ARM `[H]` | La mejor fidelidad de marca y la más vistosa: diseño exacto, transparencia, texto legible; renovar = cambiar props | Licencia; RAM en un VPS ya justo; trabajo de diseño por plantilla (Node/TS) | Agrandar el VPS y aclarar la licencia antes de producción |
| **D. Video generativo (Seedance)** | Seedance anima una foto del catálogo o de la pieza (Seedance 1.0 pro fast o 2.5) | Foto → `creative-worker` (ADR 41, guarda de precio) → BytePlus → MP4 → FFmpeg (quita audio, recorta, baja a 512×512 y 10–15 fps) → MP4 y WebP → «Por aprobar» | `media-worker` para FFmpeg; la generación fuera del servidor · peso bajo en el VPS | 1.0 fast 480p 5 s ≈ **US$0,05** `[S]`; 2.5 480p 5 s ≈ **US$0,53** `[V]`, ×N stickers y temporadas | Minutos (cola de BytePlus, cupo 10 compartido con los clientes) `[V]` | Movimiento natural, pero **sin fondo transparente** (el sticker queda cuadrado) y el logo o el precio se deforman `[H]` | Costo por temporada; cupo compartido; datos del cliente a BytePlus solo por endpoints propios; WebP ≤ 500 KB difícil con video real `[H]` | Medición pagada antes de decidir |
| **E. Stickers por código en Python, sin Remotion** | Logo del Brand Kit (PNG con transparencia), una foto del producto ya recortada o un texto corto de temporada, con movimientos fijos (latido, rebote, giro, brillo) dibujados con Pillow | Brand Kit → Pillow genera 24–36 cuadros con alfa → FFmpeg (`libwebp_anim`) → WebP 512×512 ≤ 500 KB → R2 → «Por aprobar» | Imagen `app`, `media-worker` · ~2–5 s de CPU por sticker `[H]` | Proveedor US$0 `[V]` | Segundos `[H]` | Fiel (logo y colores exactos) y transparente; diseño más simple que C | Que el FFmpeg de Debian traiga `libwebp_anim` está **sin verificar** en la imagen (`[S]`; se comprueba gratis con `ffmpeg -encoders`); fotos de producto sin recorte no sirven como sticker | Nada |
| **F. El dueño sube los suyos** | El dueño o su diseñador hacen stickers en otra app y los suben | Subida → validación (WebP animado ≤ 500 KB, 512×512) → «Por aprobar» | Solo validación con FFmpeg/ffprobe · nulo | US$0 | Lo que tarde el dueño | Depende de él | Casi nadie lo hará: contradice «sin diseñador» | Nada; puede convivir con B o E |

Canva (ya integrado) también exporta diseños animados, pero en MP4/GIF y con trabajo del dueño
dentro de Canva: es F con otro editor, no una opción aparte.

## 4. Medido frente a estimado

**No se puede saber sin probar:** el peso real de un MP4 mudo de 3–5 s (200–600 KB es una
estimación); si un WebP animado de 512×512 cabe en 500 KB con 2–3 s de movimiento; si el FFmpeg
de la imagen trae `libwebp_anim`; el tiempo de CPU en el ARM de producción; si Seedance deja logo
y precio legibles; y, sobre todo, **cómo se ve en un teléfono real**: si el sticker se anima solo
en Android y en iPhone, si el video muestra miniatura y si pesa lo que esperamos al llegar.

**Plan mínimo de medición (necesita el OK del fundador; no se ha corrido nada):**

1. **Banco local gratis (US$0):** con el logo y 3 fotos aprobadas de Bianki, 4 videos con la
   opción B (acercamiento, paneo, fundido, logo final) y 6 stickers con la opción E (latido,
   rebote, giro × logo y texto «¡Gracias por tu pedido!»). Se mide peso, tiempo y CPU con la
   imagen `app` arm64. Si se quiere comparar con C: 2 stickers con una plantilla Remotion de
   prueba en local (sin licencia de producción en juego mientras no se despliegue `[H]`).
2. **Prueba pagada opcional (≈ US$2,5 `[S]`):** 4 animaciones de 5 s a 480p con Seedance 1.0 pro
   fast (≈ US$0,20) y 4 con Seedance 2.5 (≈ US$2,12), de las mismas fotos, pasadas por FFmpeg a
   MP4 y WebP. Pasa por la guarda de precio y el registro de consumo, fuera de horas de clientes
   (comparte el cupo de 10 tareas). Se documenta en `docs/modelos-generativos/pruebas.md`.
3. **Prueba en teléfono real:** desde el número de Bianki a un Android y un iPhone del equipo,
   dentro de una conversación abierta: 2 stickers y 2 videos. Se anota: ¿se anima solo el
   sticker?, ¿se ve transparente?, ¿miniatura del video?, peso recibido, tiempo de llegada.
   Costo de Meta: US$0 dentro de la ventana de servicio `[S]`. Es un envío real desde el número de
   un cliente: lo hace o autoriza el fundador.

## 5. Tipo de puerta

- **A, B, E, F son de dos vías:** sin proveedor nuevo, sin runtime nuevo, sin datos del cliente
  fuera; se apagan quitando la opción del menú.
- **C es casi de una vía en lo operativo:** prender `render` en producción obliga a agrandar el VPS
  y a pagar la licencia de Remotion (una cuota mensual que no se recupera). Se vuelve de dos vías
  si se prueba solo en local y se decide con el banco.
- **D es de dos vías en lo técnico pero tiene un costo que crece con cada temporada y negocio**, y
  manda fotos del cliente a BytePlus (ya aceptado para generar piezas, por endpoints propios).

**Pre-mortem — tres formas en que esto falla con Bianki:**

1. **El sticker llega como un cuadrado con fondo blanco** (o no se anima en iPhone) y Bianki deja
   de usarlo a la primera semana. *Señal:* la prueba de teléfono. *Qué hacemos:* solo stickers con
   transparencia real (E o C), nunca de video generativo.
2. **Bianki no aprueba la tanda de temporada a tiempo** y en Navidad el menú no tiene nada
   (la opción ni aparece). *Señal:* lote en «Por aprobar» a 7 días de la fecha. *Qué hacemos:*
   generar con 3 semanas de margen y avisarle en «Tu semana».
3. **Al cliente final no le importa:** no responde distinto a un sticker de marca que a un «ok».
   *Señal:* pocos envíos tras el primer mes. *Qué hacemos:* no seguir con C ni D; dejar B, que no
   costó nada.

## 6. Recomendación

**B para los videos + E para los stickers, ambos en `media-worker`, después del banco local
gratis y de la prueba en teléfono.** Es lo único que entrega los dos formatos con la marca exacta
y fondo transparente sin proveedor, sin runtime y sin agrandar el servidor: aprende si a los
clientes de Bianki les importa con un costo de US$0 por pieza. C queda como la mejora si el banco
muestra que E se ve pobre; D queda descartada por ahora (sin transparencia y con costo por
temporada).

**Cuánto cuesta equivocarse:** unos días de trabajo de un ingeniero; nada de proveedor.
**La reabrimos si:** tras un mes con Bianki (y Polette) se mandan menos de 10 stickers o videos al
mes por negocio → se retira; o si el dueño rechaza más de la mitad de los stickers de E por cómo
se ven → se pasa a C con la licencia aclarada. Revisión: 2026-12-15 (antes de Navidad).

**Independiente de la elección:** revisar la licencia de Remotion (equipo de 5 frente al tope de 3)
y corregir `remotion_selfhost` en la tabla de precios si ya no es 0,00.

## 7. Lo que pediría la interfaz

El dueño ve las tandas de cada temporada en el flujo «Por aprobar» que ya existe, con una tarjeta
por sticker o video (que se anime en la vista previa), «Aprobar» o «Pedir otro», y la temporada
como etiqueta («Navidad 2026»). Una vez aprobado algo, el menú de envío del chat
(`docs/ux-whatsapp-menu-orbit.md` §2) muestra **una** fila: «Stickers» o «Videos cortos» si hay de
uno solo, «Stickers y videos» si hay de los dos, que abre el panel «¿Qué le mandas?» con las dos
tarjetas y la temporada actual primero; las anteriores, más abajo. Nunca una séptima fila. El
envío sigue el mismo camino de `whatsapp_outbox` aprobado.

## 8. Backlog después de la decisión (si elige B + E)

1. Banco local gratis y prueba en teléfono (sección 4), documentados; confirmar `libwebp_anim`.
2. Enmienda a ADR 39: biblioteca por temporada fuera de la purga de 90 días, prefijo propio
   fuera de `t/`, con archivo por el dueño.
3. Migración: tabla de stickers/videos por negocio y temporada, con RLS, procedencia
   (pieza o logo de origen, receta y versión del flujo) e idempotencia por (negocio, temporada,
   receta, origen).
4. `media-worker`: recetas B (MP4 mudo) y E (WebP animado) con validación de peso antes de guardar.
5. «Por aprobar»: tarjetas de sticker y video, aprobar / pedir otro.
6. WhatsApp: envío de `sticker` y `video` por el outbox aprobado, solo dentro de la ventana.
7. Menú del chat: la fila condicional y el panel «¿Qué le mandas?».
8. Calendario de temporadas por país (CO/VE/UY) y aviso 3 semanas antes en «Tu semana».

## Necesito que decidas

1. **¿Qué opción?** B + E (recomendada) · C · D · A (no hacerlo).
2. **¿Autorizas las pruebas?** El banco local gratis y la prueba en teléfono con el número de
   Bianki (Android y iPhone); y, aparte, si corre la prueba pagada de Seedance (≈ US$2,5).

## 9. Decisión del fundador (2026-11-08) `[F]`

- **Se lanza la versión beta a costo cero: B + E.** Videos cortos mudos a partir de las imágenes ya
  aprobadas (B) y stickers animados dibujados por código con la identidad de la marca (E), los dos
  con FFmpeg en el `media-worker` que ya existe. US$0 por pieza; sin proveedor, runtime ni servidor
  nuevos.
- **Además, la opción de generar con IA (D) como elección por pieza**, no como camino por defecto:
  junto a «Crear para esta temporada», un «Crear con IA» que anima una foto con Seedance, muestra el
  costo estimado antes de generar, pasa por la guarda de precio (ADR 41) y queda en el libro de
  consumo del negocio. El resultado sale como video; como sticker solo si la prueba de teléfono
  muestra que un sticker sin fondo transparente se ve bien (si no, la IA produce únicamente videos).
- **C queda como mejora posible** si el banco muestra que E se ve pobre; se decidiría con la
  licencia de Remotion aclarada.
- **Pruebas:** el banco local gratuito, la prueba en teléfono real desde el número de Bianki y la
  prueba pagada de Seedance (≈ US$2,5) se registran aquí cuando el fundador las autorice una a una.
- **Historias:** se abren bajo la épica de WhatsApp a partir de §8, más una para «Crear con IA».
