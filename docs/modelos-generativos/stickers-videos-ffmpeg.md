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

## Pendiente de medir

CPU real en el ARM de producción (el banco usó un M1 Pro y un contenedor arm64 limitado a 2 CPU,
con la máquina cargada por otras sesiones), imágenes reales de Bianki y Polette, la imagen `app`
de producción misma (`ffmpeg -encoders`), y la **prueba en teléfono real** (Android e iPhone:
¿se anima solo el sticker?, ¿transparente?, ¿miniatura del video?). Las tres necesitan al fundador.
