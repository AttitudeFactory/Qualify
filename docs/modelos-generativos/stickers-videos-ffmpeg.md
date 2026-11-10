# Stickers animados y videos cortos de marca con FFmpeg y Pillow — recetas B y E (m-24955647)

Ficha de las dos recetas que el fundador eligió el 2026-11-08 (`docs/opciones-stickers-videos-cortos.md`
§9): **B**, video corto mudo a partir de imágenes ya aprobadas, y **E**, sticker animado dibujado
por código con el logo del Brand Kit. No hay modelo ni proveedor: son FFmpeg y Pillow corriendo en
el `media-worker`. Costo de proveedor **US$0 por pieza**. Medición: [STICKERS-001](pruebas.md#stickers-001).

| Campo | Valor |
|---|---|
| Herramientas | FFmpeg de Debian bookworm (`apt-get install ffmpeg`, `deploy/Dockerfile` imagen `app`, capa m-24957792): 5.1.9 con `libx264`, `libwebp_anim` (libwebp 1.2.4), `zoompan` y `xfade` — **comprobado en una imagen igual** (`python:3.12-slim-bookworm` + la misma línea de `apt`, arm64), **no en la imagen de producción** (GHCR pidió credenciales). Pillow 13.0.0 (`uv.lock`) |
| Dónde corre | `media-worker` (ADR 47), `mem_limit` 768m, 1 trabajo a la vez |
| Versión de receta | `recipe-b-v0` / `recipe-e-v0` (propuesta; la historia de `media-worker` la fija y la guarda como procedencia) |
| Límites de WhatsApp que aplican | Sticker WebP animado ≤ **500 KB**; video MP4 ≤ 16 MB, **H.264 Main o Baseline sin cuadros B**, sin audio o AAC, `faststart` (`docs/opciones-conectar-sistema-de-pedidos.md` §4, leído de Meta el 2026-11-05). La medida 512×512 del sticker y los límites de cuadros no los dice esa página `[no verificado]` |
| Datos | Solo imágenes del propio negocio ya aprobadas y su logo; nada sale del servidor |

## Receta B — video corto mudo (3–5 s)

Ajustes recomendados: **`-preset veryfast -crf 28 -profile:v main -bf 0`**, 24 cps, `yuv420p` en
rango limitado, `-an`, `+faststart`, `-threads 2 -filter_threads 1` (igual que la normalización de
Galería). 720×1280 (vertical) o 512×512. `-preset medium` no ayuda: a igual CRF salió más pesado
en paneo, fundido y logo, y tarda el doble.

```bash
# Comunes a las cuatro variantes (D = segundos, N = D*24 cuadros, W×H = 720x1280 o 512x512)
ENC="-frames:v N -r 24 -an -c:v libx264 -preset veryfast -profile:v main -bf 0 -crf 28 \
     -pix_fmt yuv420p -threads 2 -movflags +faststart"
FIT="scale=W:H:force_original_aspect_ratio=increase,crop=W:H,setsar=1"
TAIL="scale=out_range=tv,format=yuv420p[v]"   # las JPEG entran en rango completo (yuvj420p)

# 1. Acercamiento lento (zoompan sobre la foto a 2× para que no tiemble)
ffmpeg -threads 2 -filter_threads 1 -i foto.jpg -filter_complex \
  "[0:v]scale=2W:2H:force_original_aspect_ratio=increase,crop=2W:2H,setsar=1,\
zoompan=z='min(zoom+0.18/N,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=N:s=WxH:fps=24,$TAIL" \
  -map "[v]" $ENC salida.mp4

# 2. Paneo (vertical: de izquierda a derecha sobre la foto a la altura del video)
ffmpeg -threads 2 -filter_threads 1 -loop 1 -framerate 24 -t D -i foto.jpg -filter_complex \
  "[0:v]scale=-2:H,crop=W:H:x='(iw-W)*t/D':y=0,fps=24,$TAIL" -map "[v]" $ENC salida.mp4

# 3. Fundido entre 3 fotos (S = (D+1)/3 s por foto, dos fundidos de 0,5 s)
ffmpeg -threads 2 -filter_threads 1 \
  -loop 1 -framerate 24 -t S -i a.jpg -loop 1 -framerate 24 -t S -i b.jpg -loop 1 -framerate 24 -t S -i c.jpg \
  -filter_complex "[0:v]$FIT[a];[1:v]$FIT[b];[2:v]$FIT[c];\
[a][b]xfade=transition=fade:duration=0.5:offset=S-0.5[ab];\
[ab][c]xfade=transition=fade:duration=0.5:offset=2S-1.0,$TAIL" -map "[v]" $ENC salida.mp4

# 4. Foto quieta y logo que aparece al final (logo al 45 % del lado corto, entra en D-1,2 s)
ffmpeg -threads 2 -filter_threads 1 -loop 1 -framerate 24 -t D -i foto.jpg \
  -loop 1 -framerate 24 -t D -i logo.png -filter_complex \
  "[0:v]$FIT[bg];[1:v]format=rgba,scale=L:-1,fade=in:st=D-1.2:d=0.6:alpha=1[l];\
[bg][l]overlay=(W-w)/2:(H-h)/2:shortest=1,$TAIL" -map "[v]" $ENC salida.mp4
```

Medido (5 s, CRF 28, fotos de relleno): 720×1280 de **114 a 614 KB**, 512×512 de **66 a 267 KB**;
en un contenedor arm64 de 2 CPU y 768 MB, **0,6 a 5,4 s** de reloj y como mucho **183 MB** de
memoria. El fundido de 3 fotos es el más pesado en bytes; el logo final, el más lento (escala el
PNG de 1024 px en cada cuadro: **escalar el logo una vez antes** es la mejora obvia).

Comprobar antes de guardar: `ffprobe` dice `h264`, perfil `Main`, `has_b_frames=0`, `yuv420p`,
sin pista de audio, duración ±0,1 s, y el archivo < 16 MB.

## Receta E — sticker animado 512×512 (2–3 s)

Cuadros: Pillow dibuja 24–36 cuadros RGBA de 512×512 a **12 cps** (2–3 s) con el logo recortado a
su contenido, encajado con 16 px de margen, con borde blanco de 12 px (`MaxFilter` sobre el alfa) y
uno de cuatro movimientos (latido, rebote, giro ±12°, brillo que cruza) o un texto corto. Dibujar
36 cuadros costó **≤ 0,45 s de CPU**.

Codificación recomendada: **FFmpeg `libwebp_anim`, calidad 70, `-compression_level 4`**.

```bash
ffmpeg -framerate 12 -i cuadros/f%03d.png -c:v libwebp_anim -lossless 0 -quality 70 \
  -compression_level 4 -loop 0 -pix_fmt yuva420p -threads 2 sticker.webp
```

Equivalente en Pillow, sin FFmpeg (entre un 1 % y un 40 % más pesado en este banco; la mayor diferencia, en el brillo):

```python
frames[0].save("sticker.webp", save_all=True, append_images=frames[1:], duration=83, loop=0,
               lossless=False, quality=70, method=4, background=(0, 0, 0, 0))
```

- **Nunca `-compression_level 6` (Pillow `method=6`):** 8–23 veces más lento (14–55 s por sticker
  en el contenedor de 2 CPU) para un 3–13 % menos de peso.
- **Peso:** con calidad 70 el peor caso del banco (giro de la insignia) fue **422 KB con 36 cuadros**
  y **326 KB con 30**; con calidad 80 y 36 cuadros llegó a **490 KB**, a 10 KB del tope. Los
  movimientos que cambian todo el dibujo en cada cuadro (giro, rebote) pesan el doble que los que
  repiten cuadros (latido, brillo): el codificador funde los cuadros iguales.
- **Regla de guardado:** si el archivo pasa de **450 KB** (margen de 50 KB), volver a codificar con
  calidad 60 y, si aún no cabe, con 30 cuadros (2,5 s); nunca guardar uno > 500 KB.
- **Fondo del contenedor:** FFmpeg escribe el color de fondo de la animación como blanco opaco
  (`0xFFFFFFFF`) y Pillow como transparente (`0x00000000`, lo que escribió por omisión en el banco; `background=(0, 0, 0, 0)` lo deja explícito). La
  transparencia de cada cuadro es la misma en los dos; si en la prueba de teléfono algún cliente
  muestra un cuadrado blanco, se cambia a Pillow (o se reescribe el fondo con `webpmux`).
- **Texto:** ajustar el tamaño de letra para que quepa en 480 px (el «¡Gracias por tu pedido!» de
  44 px en DejaVu Sans tocó el borde). La imagen `app` trae DejaVu (`fonts-dejavu-core` y la copia
  de `qualify_creative/fonts/`).

Comprobar antes de guardar: 512×512, animado, `loop=0`, con alfa, duración 2–3 s
(`webpmux -info` o Pillow), ≤ 500 KB.

## Receta C — sticker con la plantilla Remotion (m-24987158, 2026-11-09)

Desde el 2026-11-09 los stickers se dibujan con la plantilla `sticker` v1 de `packages/render`
(decisión del fundador, `docs/opciones-stickers-videos-cortos.md` §9.1); E queda de respaldo.
Medición: [STICKERS-002](pruebas.md#stickers-002).

- **Cómo:** el servicio de render recibe el logo (o el recorte, o el texto), la paleta y la
  tipografía de la marca, y devuelve una sola imagen PNG transparente de 3072×2560 con los 30
  cuadros (512×512, 15 cps, 2 s). `qualify_creative.seasonal.sticker_c` la corta, comprueba el
  margen de 16 px y codifica con el escritor de Pillow de E, su escalera (70 → 60 → mitad de
  cuadros) y `validate_sticker`; el alfa va con pérdida a 70.
- **Aspecto:** borde blanco de ~15 px que sigue la forma (dilatar + desenfocar + umbral sobre el
  alfa, en un filtro SVG), sombra suave, movimientos con resorte que empiezan y terminan quietos
  (el primer cuadro es la vista previa en WhatsApp): latido con anillos, rebote con aplastamiento
  y sombra en el suelo, giro de moneda con el reverso en el color de la marca, brillo con
  destellos, y texto con ola de palabras.
- **Respaldo:** sin servicio (`/health` no responde, sin la plantilla, sin el paquete listo), con
  el render fallido o con un archivo que no cabe, la misma ranura sale por E; el trabajo guarda
  `engine` y `fallback`. `QUALIFY_SEASONAL_STICKERS=pillow` fuerza E.
- **Versión:** `seasonal-c-1`. Proveedor US$0 (licencia gratuita de Remotion, `remotion_selfhost`).

## Pendiente de medir

CPU real en el ARM de producción (el banco usó un M1 Pro y un contenedor arm64 limitado a 2 CPU,
con la máquina cargada por otras sesiones), imágenes reales de Bianki y Polette, la imagen `app`
de producción misma (`ffmpeg -encoders`), y la **prueba en teléfono real** (Android e iPhone:
¿se anima solo el sticker?, ¿transparente?, ¿miniatura del video?). Las tres necesitan al fundador.

## Lo que quedó en código (m-24976892, 2026-11-08)

Recetas puras en `packages/creative/src/qualify_creative/seasonal/` (`video.py`, `sticker.py`,
`look.py`, `ffmpeg.py`, `recipes.py`); el trabajo `seasonal_media` de `media-worker` en
`packages/api/src/qualify_api/creative/seasonal_job.py`. Qué lote se crea es dato del backend
(`qualify_api.whatsapp.seasonal.STANDARD_BATCH`). Versión de receta guardada en el resultado del
trabajo: `seasonal-b-1` / `seasonal-e-1` (la fila guarda la de la biblioteca, `seasonal-v1`).
Costo: US$0,00 (sin llamadas pagas).

**Común.** `ffmpeg -nostdin -hide_banner -loglevel error -y -filter_threads 1
-filter_complex_threads 1 … -threads 1`, bajo `nice -n 10`, máximo 90 s por llamada (un solo
hilo, no 2 como el banco: el `media-worker` tiene 1 CPU). Muerto por señal o por tiempo = falla
transitoria (se reintenta); otro error = `ffmpeg_failed`; sin `ffmpeg` o sin `libx264` =
`ffmpeg_missing`. Fuentes leídas con Pillow, rotadas por EXIF, achicadas a 1600 px; > 50 MP se
rechaza por cabecera.

**B — video.** `-an -r 24 -c:v libx264 -preset veryfast -crf 28 -profile:v main -bf 0
-pix_fmt yuv420p -color_range tv -movflags +faststart -threads 1`. Si pasa de 1 MB se vuelve a
codificar con crf 30 y 32; > 16 MB a crf 32 → `too_large`. 720 px de ancho, alto según la
primera foto entre 1:1 y 9:16 (horizontal → 1:1). Las fotos entran ya recortadas por Pillow a la
medida exacta en PNG (así no hay JPEG en rango completo ni escalado por cuadro; el logo de
`b-logo` se dibuja una vez en una capa PNG del tamaño del video):

| Receta | Movimiento | Duración |
|---|---|---|
| `b-zoom` | `zoompan=z='1+0.12*on/96'` sobre la foto a 2× | 4 s |
| `b-pan` | foto 20 % más ancha, `crop=W:H:x='(iw-W)*t/4'` | 4 s |
| `b-xfade` | 2–3 fotos de 2 s, `xfade=transition=fade:duration=0.5` | 3,5 s / 5 s |
| `b-logo` | foto (o, sin foto, degradado primario→secundario 720×720) y el logo en tarjeta blanca con borde del color primario, `fade=t=in:st=2.4:d=0.8:alpha=1` | 4 s |

Antes de guardar, ffprobe: `h264`, `yuv420p`, perfil `Main`, `has_b_frames=0`, sin audio,
3–5 s, con medidas y duración leídas del archivo; si no, `ffmpeg_failed`. Si ffprobe falta,
falla, tarda o no devuelve JSON, también `ffmpeg_failed` (transitorio): nunca se marca listo un
video sin revisar.

**E — sticker.** 30 cuadros RGBA 512×512 a 15 cps (2 s), margen 16 px, base en caja de 380 px
con contorno blanco de 10 px; movimientos `e-latido`, `e-rebote`, `e-giro` (giro de moneda en el
60 % del ciclo), `e-brillo`, `e-texto` (tipografía del Brand Kit → familia de Google Fonts →
DejaVu Sans; hasta 3 líneas en 440×300; aparece con rebote, un vaivén de ±4° y queda quieto: con
vaivén todo el ciclo pesó 474 KB). **Codifica Pillow** (`save_all=True, format="WEBP",
lossless=False, quality=70, method=4, loop=0, background=(0, 0, 0, 0)`); sin respaldo con
FFmpeg (deja el fondo de la animación opaco): un Pillow sin WebP falla con `webp_unavailable`.
Calidad 70; si pasa de 450 KB, 60; si aún pasa, la
mitad de los cuadros a 60; se guarda el primero ≤ 450 KB o, en el último intento, ≤ 500 KB; si no,
`too_large`. Antes de devolver: WebP 512×512, animado, esquina transparente, ≤ 500 KB.
Confirmado aquí lo del banco: con FFmpeg el fondo de la animación (`ANIM`) sale `ffffffff`, con
Pillow `00000000`.

**Medido en la Mac (M1, FFmpeg 8.0, Pillow 13.0.0, imágenes de relleno, un hilo):**

| Receta | Peso | Ajuste | Reloj |
|---|---|---|---|
| e-latido / e-rebote / e-giro / e-brillo | 45 / 94 / 47 / 77 KB | q 70 | 0,2–0,35 s |
| e-texto «¡Gracias por tu pedido!» / «¡Feliz Día de la Madre para todas!» | 271 / 333 KB | q 70 | 0,4–0,6 s |
| b-zoom / b-pan / b-xfade (3) / b-logo (720×900) | 322 / 61 / 147 / 73 KB | crf 28 | 0,4–0,8 s |
| b-logo sin foto (720×720) | 21 KB | crf 28 | 0,5 s |

`-bf 0` subió el peso (b-zoom pasó de 158 a 322 KB), todo lejos de 1 MB. Memoria: Python
~106 MB y el FFmpeg más grande ~182 MB de RSS máximo (macOS, no el contenedor).

**El trabajo `seasonal_media`.** Lee la fila primero (solo `pending`/`failed` del intento actual
se dibujan); el logo, las piezas aprobadas (`source_ref` = ids separados por coma, revalidados
como piezas de foto aprobadas de ESTE negocio) y la tipografía se leen por `ObjectGate.open_object`
(limitado a las raíces del inquilino); dibuja en un directorio temporal que se borra siempre; guarda
con `put_seasonal_media(..., attempt=…)` en `seasonal/{t}/{b}/{temporada}/{id}-{intento}.{webp|mp4}`
(3 intentos de escritura, misma clave); luego `mark_ready` (costo 0) o `mark_failed` con
`no_source`, `unreadable_source`, `too_large`, `ffmpeg_failed`, `ffmpeg_missing` o
`unknown_recipe`. Un `payload` que no coincide con su fila (temporada, tipo, receta, origen) se
rechaza (`payload_mismatch`) sin leer nada, y el logo es siempre el del Brand Kit
(`logo_asset_key`). En la cola del `media-worker` la Galería va primero: un lote de temporada no
retrasa la subida de un dueño. Un `StaleAttempt` («Pedir otro» a mitad de camino) borra el archivo recién
escrito de ESE intento y descarta el resultado. Agotados los reintentos, la fila queda `failed` y
se borra la clave del intento.

**Pruebas offline:** `packages/creative/tests/test_seasonal_recipes.py` (cuadros, márgenes,
búsqueda de calidad, límites, fondo transparente, y con FFmpeg las 11 combinaciones con perfil
Main sin cuadros B) y `packages/api/tests/test_seasonal_job.py` (servicio real en memoria,
`ObjectGate` sobre almacén en memoria — nunca R2). El CI no tiene FFmpeg: salta 12 pruebas y
corre la mitad Pillow (41).

## «Crear con IA» — videos con Seedance (m-24976893, 2026-11-08)

Opción por lote, nunca por defecto: `STANDARD_BATCH["ai"]` = 3 videos `ai-seedance`, una foto
aprobada cada uno (las 3 piezas de foto aprobadas más recientes; el paso «¿Qué foto animamos?»
viene después). La IA **no hace stickers** (sin fondo transparente) hasta que la prueba en teléfono
diga lo contrario.

| Ajuste | Valor |
|---|---|
| Modelo | `seedance-1-0-pro-fast-251015` (el más barato), imagen a video, `480p`, 5 s, proporción de la foto más cercana entre 1:1, 3:4 y 9:16, `camera_fixed=false`, sin audio (1.0 es mudo) |
| Prompt | `AI_PROMPT` en `qualify_creative/seasonal/ai.py`, versión `seasonal-ai-1`: movimiento natural sutil sin cambiar producto, texto ni logo |
| Foto | JPEG ≤ 1280 px como *data URL* (nunca un enlace público) |
| Estimado | `estimate_ai_video_cost_usd()` con la tabla `v7` y la fórmula de ModelArk (ancho × alto × 24 × s / 1024): 48.600 tokens × US$1,0/M = **US$0,0486**; la pantalla muestra «unos US$0,05 por video» (centavo hacia arriba) y el total del lote. Con 2.5 el mismo cálculo da US$0,53, igual a lo medido en `seedance-2-5.md` |
| Confirmación | `quote_batch` antes de crear; `plan_batch(mode="ai", accepted_total_usd=…)` rechaza (`CostNotConfirmed`) si el total confirmado no cubre la cotización; «Pedir otro» de un video con IA pide confirmar su costo otra vez |
| Guarda de precio | en `creative-worker`, al enviar, y nada llega a BytePlus si falla: (1) el estimado no puede pasar el precio aceptado al planear (la cotización de la tabla guardada en el trabajo, `pricing_version`) → `price_changed`; (2) la marca debe tener tope mensual (`creative_engine_config`; el generador toma «sin configuración» como ilimitado, aquí se rechaza) → `no_budget_cap` («Tu negocio no tiene tope de gasto configurado.»); (3) estimado > lo que queda del tope → `budget_cap` («Esta pieza superaría tu tope de gasto.») |
| Plazo | 30 min desde `creative_jobs.submitted_at` (un reinicio del worker no lo alarga): pasado eso el trabajo termina, la fila queda `vendor_timeout`, el cupo se libera y, como no hay forma de cancelar la tarea, se anota el precio cotizado con el id de la tarea (si llegara a terminar, no se anota dos veces) |
| Descarga | solo `https` de `*.bytepluses.com` / `*.byteplus.com` (lista permitida, `VIDEO_HOST_SUFFIXES`); otra URL → `vendor_url_refused`, sin descargar, y el log dice el host en nivel ERROR. **Sin evidencia del host real:** no hay en el repo ninguna URL de resultado de Seedance; Ark podría servir desde `*.volces.com`, que NO está en la lista. **La prueba pagada (m-24976890) debe anotar el host de `content.video_url`** y, si no está en la lista, se agrega antes de activar «Con IA» |
| Cola | `creative_jobs` tipo `seasonal_video` (0146), en el grupo de Seedance (cuenta en los 10 cupos de ADR 41); el id de tarea se guarda al aceptarse y nunca se reenvía |
| Posproceso | `clip_from_video`: sin audio, máx. 5 s, 720 px de ancho, H.264 Main sin cuadros B, crf 28→32 (< 1 MB objetivo, ≤ 16 MB), validado con ffprobe como la receta B |
| Costo real | tokens facturados (`usage.completion_tokens`) × tarifa de la tabla → `creative_usage_events` (sin `draft_id`, `provider=byteplus`, id = uuid5 de la tarea: una tarea se anota una sola vez aunque `finish` se repita; `unit = seasonal_video_token`, la marca con la que se suma el mes y que sobrevive al borrado de la temporada) + gasto del mes de la marca solo si la fila es nueva; también se anota cuando la URL del video se rechaza (la tarea ya se cobró), y el mismo valor en `brand_seasonal_media.cost_usd` |

**No se ha llamado a Seedance para esto**: no hay prueba en vivo. La prueba pagada (≈ US$2,5) y la
de teléfono siguen pendientes de autorización del fundador; al correrlas se anotan en `pruebas.md`
y aquí.
