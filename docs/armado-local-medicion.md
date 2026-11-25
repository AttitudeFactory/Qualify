# Armado local de video — memoria, CPU y tope diario

`[MEDIDO 2026-11-16 · m-25026575 (EF-15) · épica «Video automático con efectos, por pasos» (m-25026566, ADR 50)]`

El armado local de EF-06 («Tu video, con efectos», a costo 0) corre en el `creative-worker`. Ese
contenedor tiene `mem_limit: 768m` y comparte el VPS (2 vCPU ARM) con Pedidos. Esta medición dice
si cabe en esa memoria, cuánta CPU gasta y de dónde sale el tope diario de piezas locales por
negocio (decisión D3: una pieza local no gasta creaciones ni vistas previas, así que nada más la
limita).

## Cómo se midió

- Harness: `deploy/measure/local_video_memory.py` y `deploy/measure/local-video-memory.sh`
  (`make`, `run`, `clean`; `PLATFORM=linux/arm64` emula arm64).
- Imagen `qualify-memtest:deps` (amd64, PyAV 19.0.1), con `packages/` de 379707cb montado en
  solo lectura.
- Fuentes sintéticas con ruido que se mueve y bitrate de celular, hechas en un contenedor aparte
  que no se mide. No se descargó ningún video ni se llamó a un proveedor.
- Cada caso corre en un contenedor nuevo con `--memory 768m --memory-swap 768m`, sin red y sin
  Postgres ni Redis. Llama `render_local_part` directo (preparar → foto quieta → cámara rápida).
- La cifra que decide un OOM es la **memoria anónima** del cgroup (`anon` en `memory.stat`,
  muestreada cada 50 ms). `memory.peak` llega a 768 en los casos 4K y 5K, pero es page cache de
  los archivos copiados: se recupera (`oom_kill` = 0).
- Los textos se midieron con la parte de EF-05 que corre en el worker (`overlay_text_layers`, 3
  PNG sintéticos), sin el servicio Remotion, que vive en otro contenedor.

## Resultados (amd64, 8 núcleos, sin límite de CPU como en producción)

| Caso | Fuente | s fuente | Velocidad | Rotación | Textos | Anon MiB | RSS MiB | CPU s | Pared s | OOM |
|---|---|---|---|---|---|---|---|---|---|---|
| hd15_x1 | 1080p H.264 | 15 | ×1 | no | 0 | 148 | 191 | 49 | 33 | no |
| hd_30_x2 | 1080p H.264 | 30 | ×2 | no | 0 | 147 | 190 | 71 | 45 | no |
| hd_60_x10 | 1080p H.264 | 60 | ×10 | no | 0 | 148 | 192 | 104 | 66 | no |
| k4_30_x2 | 4K H.264 | 30 | ×2 | no | 0 | 305 | 348 | 338 | 189 | no |
| k4_60_x10 | 4K H.264 | 60 | ×10 | no | 0 | 313 | 356 | 464 | 260 | no |
| k4_60_x2 | 4K H.264 | 60 | ×2 | no | 0 | 312 | 355 | 956 | 518 | no |
| k4rot_30_x2 | 4K H.264 | 30 | ×2 | sí | 0 | 308 | 350 | 393 | 244 | no |
| k4rot_60_x10 | 4K H.264 | 60 | ×10 | sí | 0 | 308 | 351 | 514 | 317 | no |
| k4hevc10_60_x10 | 4K HEVC 10 bits | 60 | ×10 | no | 0 | 488 | 531 | 764 | 436 | no |
| mixta | 3 tramos 4K + 2 fotos 4000×3000 | 70 + 10 | ×2/×3/×4 | 1 de 3 | 0 | 326 | 369 | 850 | 486 | no |
| k4_60_x2_3textos | 4K H.264 | 60 | ×2 | no | 3 | 450 | 496 | 1190 | 771 | no |
| k5_30_x2 | 5K HEVC | 30 | ×2 | no | 0 | 496 | 540 | 516 | 290 | no |
| k5_60_x10 | 5K HEVC | 60 | ×10 | no | 0 | 496 | 540 | 844 | 496 | no |
| **k5_112_x20 (caso del ticket)** | 5K HEVC | 112 | ×20 | no | 0 | 500 | 543 | 1381 | 794 | no |
| k5_112_x10 | 5K HEVC | 112 | ×10 | no | 0 | 503 | 547 | 1642 | 937 | no |
| k5_112_x2 | 5K HEVC | 112 | ×2 | no | 0 | 503 | 546 | 1973 | 1099 | no |
| k5_112_x2_3textos | 5K HEVC | 112 | ×2 | no | 3 | 498 | 542 | 2094 | 1273 | no |
| up480_lanczos (m-25041163, grafo aparte, antes del código) | 480×854 → 1080×1920 | 60 | ×1 | no | 0 | 191 | 225 | 102 | 54 | no |
| up480_bicubic (m-25041163, grafo aparte, antes del código) | 480×854 → 1080×1920 | 60 | ×1 | no | 0 | 190 | 224 | 91 | 49 | no |

Las dos filas `up480_*` midieron solo el agrandado, con un grafo aparte. El camino real desde
m-25041163 está en la sección siguiente.

## Armado a 1080×1920 (m-25041163, medido 2026-11-17)

Desde m-25041163 toda salida del armado local es 1080×1920. «Preparar» no agranda; su archivo
es un paso intermedio. La cámara rápida (`camara_rapida-v2`) agranda con bicubic en la misma
codificación a 1080×1920 que ya hacía. Decisión de Deivid (2026-11-17), textual: «Un solo paso
(Recomendado)». Se descartó agrandar en «preparar» (A), porque codificaba dos veces a
1080×1920. Mismo harness, amd64 con 8 núcleos y límite de 768m; producción = CPU s ÷ 2 vCPU ÷ 0,7:

| Caso | v1 (antes) CPU s · prod | A: agranda «preparar» CPU s · prod | **B: un solo paso (en el código)** CPU s · prod | Anon MiB (B) | OOM |
|---|---|---|---|---|---|
| hd_30_x2 (1080p horizontal, 30 s, ×2) | 71 · ~0,9 min | 296 · ~3,5 min | **191 · ~2,3 min** | 239 | no |
| hd_60_x10 (1080p horizontal, 60 s, ×10) | 104 · ~1,2 min | 416 · ~5 min | **149 · ~1,8 min** | 238 | no |
| small_x1 (480×854, 60 s, ×1) | — (salía en 480×854) | 436 · ~5,2 min | **386 · ~4,6 min** | 236 | no |

- Antes, un 1080p horizontal salía en 608×1080. Ahora sale en 1080×1920, con 3,2 veces más
  píxeles, y cuesta más CPU. Los casos 4K no cambian: ya salían en 1080×1920.
- El caso más caro es un tramo largo a ×1, porque se codifican 1800 cuadros a 1080×1920. Aun
  así queda dentro de lo que cuesta un 4K de celular (~5–12 min), que es la base del tope
  diario de 10.
- La memoria no sube: ~240 MiB de memoria anónima.

arm64 (producción) no se midió: el build emulado de la imagen pasó de 25 min y se cortó. La
memoria en arm64 debería ser parecida; el tiempo no.

## Lectura

- **Ningún caso supera 600 MB.** El peor es 5K HEVC de 112 s: 503 MiB de memoria anónima (527 MB,
  el 65 % de 768m). No hace falta un tope de memoria para cumplir el límite.
- **El paso que pesa es «preparar»**, por el decodificador de 5K o de 10 bits. La velocidad y la
  duración casi no cambian la memoria, solo el tiempo. 4K HEVC de 10 bits (lo que graba un iPhone)
  pesa casi como 5K.
- **Margen:** la base del harness es de 90 MiB de RSS; el worker real carga más. Si una unión de
  partes (~200 MiB, corre aparte en el mismo proceso) coincide con un «preparar» de 5K, la suma
  pasa de 700 MiB. Además, después de un 5K el proceso se queda con ~420–475 MiB que glibc no
  devuelve.
- **Lo que limita es la CPU.** El armado corre en el bucle del worker: mientras arma, no prepara
  piezas de otros negocios. Estimado en producción (CPU s ÷ 2 vCPU ÷ ~0,7):

| Pieza | Tiempo de worker estimado en producción |
|---|---|
| 1080p, 15–60 s (a 1080×1920 desde m-25041163) | ~2–2,5 min |
| 480×854 agrandado a 1080×1920, 60 s a ×1 | ~4,6 min |
| 4K de celular, 30–60 s | ~5–12 min |
| 4K HEVC 10 bits, 60 s | ~10 min |
| Peor caso: 5K de 112 s con 3 textos | ~25–30 min |

## Tope diario (decisión de Deivid, 2026-11-16: «10 al día (Recomendado)»)

- 10 armados locales por negocio y por día. Cuenta cada armado: pieza nueva, «otra versión» y
  cada parte local de un video por partes.
- Se reinicia a la medianoche del negocio (`tenants.timezone`).
- Configurable sin cambiar código: `QUALIFY_LOCAL_DAILY_CAP` (por defecto 10; un valor que no es
  un entero mayor que 0 usa 10). Código del rechazo: `local_daily_cap_reached`
  (`qualify_api/creative/local_cap.py`). Cuenta las filas de `creation_charges` con
  `request_kind = 'local_video'`, así que con `QUALIFY_CREATIONS_QUOTA=off` no actúa.
- Peor uso por negocio con 4K típico: ~1,7 h de worker al día.

| Opción | Peor uso por negocio al día | Para el dueño |
|---|---|---|
| 5 | ~50 min | 1–2 reels al día con reintentos |
| **10 (elegida)** | ~1,7 h | De sobra para publicar a diario con versiones |
| 20 | ~3,3 h | Un solo negocio puede ocupar el worker media mañana |

## Tope por pieza (m-25042483, medido 2026-11-17)

Decisión de Deivid (2026-11-17), textual: «Bajarlos a 4K 8 bits (Recomendado)».

- **Fuente de máximo 3840×2160 a 8 bits.** Si el armado local lee un video más grande o de 10
  bits, no lo decodifica. Encola un trabajo `normalize_local` para el media-worker (ADR 47) y
  la pieza espera sin aviso al dueño. El media-worker lo convierte a H.264 de 8 bits que entra en
  4K, sin agrandar, con la rotación aplicada y sin recortar el tiempo (sin audio hasta
  `local-source-v1`; con su sonido desde `local-source-v2`, m-25049580). Se normaliza el
  archivo entero una sola vez, y la copia queda en `t/{negocio}/normalized/…` para cualquier
  pieza que use ese video. Las fotos y videos de la Galería ya llegan en 1080×1920 y no pasan
  por aquí. Versión: `local-source-v2` (`local-source-v3` desde m-25071265, con 1 B-frame).
  Queda en la procedencia de cada tramo.
- **60 s de video por tramo** (`SEGMENT_SOURCE_MAX_S`), a cualquier velocidad: se rechaza antes
  de crear la pieza (`segment_source_too_long`). El worker lo vuelve a revisar y muestra el
  aviso revisado por ux-designer: «Cada bloque puede tomar hasta 1 minuto de tu video, aunque
  lo aceleres…».
- **No arma a la vez que una unión de partes.** La unión espera su turno y el armado local se
  reintenta en la pasada siguiente, sin fallar (`creative/heavy_video.py`).
- **Memoria del compose.** El decodificador quedó en 2 hilos y x264 en `rc-lookahead 10`
  (`video_text_compose-v2`, `layer-compose-v2`). Entre pasos se devuelve la memoria libre
  (`malloc_trim`). Probé primero solo `malloc_trim`, y el caso con 3 textos bajó apenas de 501 a
  491. Lo que pesaba era el compose: x264 retenía ~30 cuadros de 1080×1920 y el decodificador
  usaba hilos automáticos.

Peor caso con la fuente ya normalizada (harness de EF-15, amd64 con 8 núcleos, límite de 768m):

| Caso | Antes, RSS / anon MiB | Ahora, RSS / anon MiB | OOM |
|---|---|---|---|
| k4_60_x2_3textos (4K, 3 textos) | 501 / 455 | **343 / 296** | no |
| k4_60_x2 | 355 / 312 | 362 / 319 | no |
| k4rot_60_x10 (girado) | 351 / 308 | 359 / 316 | no |
| mixed_3x4k_2photos | 369 / 326 | **376 / 333 (el peor)** | no |
| 5K HEVC y 4K HEVC 10 bits | 531–547 / 488–503 | ya no llegan al armado: se normalizan antes | — |

Todos quedan por debajo de 450 MiB de RSS.

**La normalización en el media-worker** (768m, 1 CPU, ffmpeg de Debian, primeros 10 s de cada
fuente, memoria anónima de ffmpeg):

| Configuración de x264 | 4K HEVC 10 bits | 5K HEVC |
|---|---|---|
| veryfast por defecto, 2 hilos | 985 MiB: el kernel lo mata por memoria con 768m | 1023 MiB |
| lookahead 5, 1 hilo | 672 | 705 |
| **sin lookahead, sin B-frames ni mbtree, 1 hilo (hasta `local-source-v2`; desde v3, 1 B-frame: ver m-25071265)** | **414** | **443** |
| ultrafast | 359 | 387 |

Con la configuración del código, el normalizador real lleva un 4K HEVC de 10 bits de 60 s a 4K
de 8 bits (118 MiB). Pico anon: 434 MiB. Sin OOM. Tarda 314 s en amd64 con 1 CPU; en arm64 se
espera que tarde más. La copia es un paso intermedio: el armado la vuelve a codificar en
1080×1920, así que lo que ahorraría un lookahead no importa.

Si la normalización no termina, la pieza espera hasta 11 h 15 min: 3 intentos de hasta 3 h 05
min cada uno, más 2 h en cola. Después falla sin cobro y con el texto de siempre. Si la
máquina falla una vez por algo pasajero, se encola un trabajo nuevo; al segundo fallo de ese
tipo, la pieza falla. Un archivo ilegible falla de una vez.

## Sonido original en los tramos a velocidad normal (m-25049580)

Desde `local-v2` el video armado siempre lleva una sola pista de sonido, en el formato de la
unión de partes: AAC estéreo, 48 kHz, 128 kbps. Un tramo a ×1 conserva su sonido, recortado
al mismo inicio y fin que su imagen. Un tramo acelerado, una foto o un video sin sonido dan
silencio de su duración exacta. En cada corte el sonido se funde 80 ms, como en la unión.

- **Preparar** (`prepare-v2`) deja el sonido del tramo junto al MP4 en un WAV de 16 bits a
  48 kHz estéreo, contado desde el primer cuadro de video. Así no se codifica AAC dos veces.
- **Cámara rápida** (`camara_rapida-v3`) arma la pista única y codifica AAC una vez, contando
  muestras desde 0: no hay deriva entre cortes.
- **La copia normalizada** (`local-source-v2`) ya conserva el sonido (AAC 192 kbps, 48 kHz). Las
  copias `local-source-v1` eran mudas y no se vuelven a leer: la versión nueva es otra clave y
  otro trabajo.
- Los textos y las capas copian la pista tal cual.
- La procedencia queda en `params.local.sound`: qué tramos llevan su sonido y por qué los demás
  no (`sped_up`, `photo`, `no_audio`).

### Costo medido (2026-11-19)

Medí con el harness de EF-15 (amd64 con 8 núcleos, límite de 768m, imagen
`qualify-memtest:deps`). «Antes» es main en c35606a1, sin sonido; «después» es esta rama. Las
fuentes sintéticas del harness traen AAC estéreo, así que los tramos a ×1 recorren el camino con
sonido. Agregué tres casos a ×1: `k4_60_x1`, `k4_60_x1_3texts` y `mixed_x1_x5_x1`. Cada
caso corrió con la máquina libre y en un contenedor nuevo.

| Caso | Antes: RSS / anon MiB · CPU s | Después: RSS / anon MiB · CPU s | OOM |
|---|---|---|---|
| hd15_x1 (1080p, 15 s a ×1) | 284 / 241 · 113 | 284 / 240 · 103 | no |
| k4_60_x1 (4K, 60 s a ×1) | 358 / 314 · 558 | 354 / 311 · 563 | no |
| mixed_x1_x5_x1 (4K ×1, 4K ×5, 1080p ×1) | 377 / 334 · 432 | 387 / 344 · 374 | no |
| mixed_3x4k_2photos (el peor de m-25042483) | 391 / 348 · 410 | 371 / 328 · 386 | no |

En otra corrida, con dos mediciones a la vez (la CPU no sirve para comparar, la memoria sí),
también salieron por debajo de 450 MiB de RSS y sin OOM:

| Caso | Después: RSS / anon MiB |
|---|---|
| small_x1 | 281 / 237 |
| k4_60_x2 | 358 / 315 |
| k4_60_x2_3texts | 347 / 302 |
| k4_60_x1_3texts | 353 / 310 |
| mixed_3x4k_2photos | 399 / 356 (el máximo visto) |

Lectura:
- **Memoria: igual que antes.** La diferencia es de ±20 MiB, el ruido normal entre corridas. El
  sonido se lee y se escribe por bloques de un segundo, y el codificador AAC retiene menos de
  1024 muestras. El máximo visto en cualquier corrida fue **399 MiB de RSS** y sigue por debajo
  de 450 MiB (m-25042483).
- **CPU: igual que antes, dentro del ruido** (±10 %). Decodificar y codificar el sonido cuesta
  segundos frente a los minutos del video. El tope de 10 armados al día (m-25026575) no
  cambia.
- **Disco:** el WAV de un tramo de 60 s ocupa 11 MiB en la carpeta temporal y se borra al
  terminar.
- **Costo:** US$0. No se llama a ningún proveedor.

## B-frames en el normalizador (m-25071265, medido 2026-11-20)

Pregunta: ¿se le pueden devolver los B-frames (`bframes=3`) al normalizador sin pasar de
~550 MiB anon en el media-worker y sin perder calidad? `rc-lookahead=0`, `mbtree=0` y 1 hilo no
cambian.

**Respuesta: `bframes=3` no cabe** (661 MiB anon en el 4K de 10 bits, 679 en el 5K). Tampoco
`bframes=2` (629 / 652). **`bframes=1` sí cabe** (524 / 542 MiB, sin OOM) y da casi toda la
mejora de calidad de 3. Deivid eligió `bframes=1` el 2026-11-20; queda en el código con la
versión `local-source-v3`.

### Cómo se midió

- Harness nuevo: `deploy/measure/local-normalize-memory.sh` y `local_normalize_memory.py`.
  Reusa el muestreo y las fuentes sintéticas de EF-15. Llama al normalizador real
  (`FfmpegLocalSourceNormalizer.normalize_file`) y solo cambia `X264_PARAMS` según la variante:
  `b0` (`local-source-v2`), `b1`, `b2` y `b3`.
- Imagen `qualify-memtest:ffmpeg` = `qualify-memtest:deps` + el ffmpeg de Debian bookworm
  (5.1.9), el mismo que instala la imagen de la app.
- Cada codificación corre en un contenedor nuevo con el límite del media-worker leído de
  `docker-compose.prod.yml`: `--memory 768m --memory-swap 768m --cpus 1.0`, sin red. amd64, 8
  núcleos, hasta 4 contenedores a la vez (cada uno con 1 CPU).
- Memoria: el pico de `anon` del cgroup cada 50 ms (ffmpeg más el proceso de Python, que parte de
  23 MiB) y el RSS máximo de ffmpeg. CPU: segundos de usuario + sistema de ffmpeg.
- Fuentes sintéticas (ningún archivo personal, ningún proveedor):
  - `k4_hevc10_60`: el peor caso de m-25042483. Es el clip de EF-15: 4K HEVC de 10 bits, 60 s,
    ruido en bloques que se desplaza más grano por cuadro, 40 Mb/s. La copia queda al tope de
    tasa (~35 Mb/s).
  - `testsrc2_k4_hevc10_60`: 4K HEVC de 10 bits hecho con ffmpeg (`testsrc2` con grano leve,
    `-pix_fmt yuv420p10le -c:v libx265`, 40 Mb/s, tono de 440 Hz), 60 s.
  - `k5_hevc_10`: 5K HEVC de 8 bits, 10 s, el mismo ruido. Fue el peor caso de memoria en
    m-25042483.
- Calidad (`quality`): SSIM (`All`) y PSNR (`average`) de ffmpeg, de la copia contra su fuente.
  La fuente pasa por el mismo `scale_filter` del normalizador, así que solo cuenta la
  codificación. Se mide a resolución de publicación (el recorte 9:16 centrado de «preparar»,
  llevado a 1080×1920 con bicubic) y a 4K.
- Video publicado (`publish` + `compare`): `render_local_part` con un tramo de 10 s a ×1 sobre la
  copia, contra el mismo armado sobre la fuente original. Para eso, en la medición se levanta el
  límite de 4K 8 bits, como antes de m-25042483.

### Memoria (768m, 1 CPU)

Pico de `anon` del cgroup en MiB. Entre paréntesis, las veces que el cgroup tocó el límite
(`memory.events max`): es la caché de páginas del archivo que se lee y se escribe, que el kernel
recupera. Ninguna corrida tuvo OOM (`oom_kill` = 0).

| Fuente | b0 (`local-source-v2`) | **b1 (elegida)** | b2 | b3 (lo que pedía el ticket) |
|---|---|---|---|---|
| k4_hevc10_60 (peor caso de calidad) | 449 (0) | **524** (159) | 629 (925) | 661 (1385) |
| testsrc2_k4_hevc10_60 | 432 (0) | **507** (516) | 618 (1000) | 643 (1237) |
| k5_hevc_10 (peor caso de memoria) | 466 (0) | **542** (0) | 652 (0) | 679 (0) |

El primer B-frame cuesta ~75 MiB, el segundo ~105–110 y el tercero ~30: x264 retiene más
cuadros 4K. Una segunda corrida de b0 y b1
sobre `k4_hevc10_60` repitió las mismas cifras (449 y 524).

**Ojo con el margen:** el proceso de Python de esta medición ocupa 23 MiB. El media-worker real
carga más (SQLAlchemy, boto3), y eso se suma a ffmpeg en el mismo cgroup. Con b1 quedan ~225 MiB
hasta 768m en el peor caso medido; con b0 quedaban ~300. El `anon` en reposo del media-worker
real no está medido: queda pendiente junto con la medición del iPhone. Los toques al límite con
4K son caché de páginas, que el kernel recupera (sin OOM en ninguna corrida).

### Tiempo (60 s de 4K HEVC de 10 bits, 1 CPU, amd64)

| Variante | CPU s | Pared s |
|---|---|---|
| b0 | 424 | 429 |
| b1 | 454 (+7 %) | 460 |

Medido con solo esas dos codificaciones en la máquina. En la primera tanda corrían 4 a la vez
y además el cálculo de SSIM: ahí b0 tardó 707–732 s, b1 1075–1081 s, b2 1149–1184 s y b3
832–846 s. Esas cifras no sirven para comparar. En arm64 (producción) será más lento.

### Calidad de la copia (60 s completos)

SSIM `All` / PSNR `average` en dB, de la copia contra su fuente.

| Fuente | Dónde | b0 (`local-source-v2`) | **b1** | b2 | b3 |
|---|---|---|---|---|---|
| k4_hevc10_60 (ruido al tope de tasa) | publicación 1080×1920 | 0,9402 / 32,14 | **0,9454 / 32,56** | 0,9462 / 32,64 | 0,9463 / 32,64 |
| k4_hevc10_60 | copia 4K | 0,8854 / 30,22 | **0,8941 / 30,62** | 0,8958 / 30,67 | 0,8959 / 30,67 |
| testsrc2_k4_hevc10_60 | publicación 1080×1920 | 0,9936 / 48,28 | **0,9937 / 48,33** | 0,9938 / 48,46 | 0,9940 / 48,64 |
| testsrc2_k4_hevc10_60 | copia 4K | 0,9919 / 44,93 | **0,9920 / 44,85** | 0,9921 / 45,06 | 0,9924 / 45,24 |

Con el mismo tope de tasa, los B-frames reparten mejor los bits. En el peor caso, a 1080×1920,
b1 se queda con el 85 % de la mejora de b3 (+0,0052 de +0,0061 SSIM). m-25042483 midió con otro
método (0,944 con veryfast por defecto y 0,929 sin B-frames); esas cifras no se comparan con
estas. La única cifra que baja es el PSNR de la copia 4K de
`testsrc2` con b1 (−0,08 dB); su SSIM sube. Es ruido de la codificación y no llega a la
publicación (fila de arriba).

### Video publicado (10 s a ×1, `render_local_part`)

Cada video armado desde la copia, contra el mismo armado desde la fuente original. SSIM `All` /
PSNR `average` en dB.

| Fuente | b0 | **b1** | b2 | b3 |
|---|---|---|---|---|
| k4_hevc10_60 | 0,9149 / 28,71 | **0,9179 / 28,80** | 0,9180 / 28,81 | 0,9180 / 28,81 |
| testsrc2_k4_hevc10_60 | 0,9822 / 31,04 | **0,9821 / 31,05** | 0,9822 / 31,04 | 0,9821 / 31,06 |

- En el peor caso, b1 mejora el video publicado (+0,003 SSIM, +0,1 dB). Con `testsrc2`, todas las
  variantes quedan iguales dentro de ±0,0001 SSIM y ±0,02 dB.
- El nivel absoluto es más bajo que en m-25042483 (49 dB). Aquí la referencia es el armado desde
  la fuente de 10 bits, y ese camino convierte el color distinto que el normalizador. Esa
  diferencia es la misma en todas las variantes. No la investigué: solo comparo variantes entre
  sí.

### Decisión (Deivid, 2026-11-20: b1)

| Opción | Anon peor caso | SSIM publicación, peor caso | CPU | Nota |
|---|---|---|---|---|
| Dejar b0 (`local-source-v2`) | 466 MiB | 0,9402 | base | Sin cambio ni copias nuevas |
| **b1 (`local-source-v3`, elegida y en el código)** | **542 MiB** | **0,9454** | +7 % | Cabe por poco; el worker real suma su propio Python |
| b2 | 652 MiB | 0,9462 | — | Pasa de ~550 |
| b3 (pedido original) | 679 MiB | 0,9463 | — | Pasa de ~550 |

Con la versión nueva, una fuente que ya tenía copia `local-source-v2` se vuelve a normalizar la
próxima vez que se arme (otra clave, otro trabajo). Hoy el editor está apagado en producción
(`QUALIFY_CLIP_EDITOR=off`), así que casi no hay copias v2.

- **Costo:** US$0. Fuentes sintéticas, ningún proveedor.

## Copia liviana de 480p al subir al generador (ED-09, m-25026643, medido 2026-11-20)

El `media-worker` hace, por cada video subido al generador, una copia de 480p sin sonido
(`upload-preview-480p-v1`, `qualify_creative.video.upload_preview`): todo el largo con los
mismos tiempos, derecha (la rotación ya aplicada), lado corto ≤ 480, H.264 8 bits CRF 28 con
tope de 1,2 Mbps, un cuadro clave por segundo, un solo hilo. Costo de proveedor: US$0.

Medido con `deploy/measure/upload-preview-memory.sh` (imagen `qualify-memtest:ffmpeg`, FFmpeg
5.1 de Debian, como la imagen de la app), en un contenedor nuevo por corrida con el límite del
media-worker (768m, 1 CPU), amd64. Fuentes sintéticas hechas con `make`: el 5K de 10 s de
m-25071265 repetido hasta 112 s por copia de flujo (sin recodificar), la misma versión en 10
bits, y el 4K HEVC de 10 bits con rotación de 90°. El Python de la medición ocupa 23 MiB.

| Fuente | Pico `anon` MiB | RSS de ffmpeg MiB | CPU s | Pared s | Copia |
|---|---|---|---|---|---|
| 5K HEVC 8 bits, 112 s | 282 | 303 | 458 | 465 | 854×480, 16,2 MiB, sin sonido |
| 5K HEVC 10 bits, 112 s | **407** | 428 | 383 | 388 | 854×480, 16,2 MiB, sin sonido |
| 4K HEVC 10 bits, 60 s, rotado 90° | 282 | 304 | 166 | 168 | 480×854, 8,7 MiB, sin sonido |

Ningún toque al límite (`memory.events max` = 0) ni OOM. El peor caso queda en ~430 MiB, debajo
de los 600 MiB del ticket y con ~340 MiB de margen hasta 768m. Lo que pesa es el decodificador
HEVC de 5K; la codificación a 480p casi no suma. En arm64 (producción) el tiempo será mayor; el
tiempo permitido es 300 s + 20 s por segundo de video (2540 s para 112 s), tope 3 h.

## Tira de cuadros de la línea de tiempo (ED-11b, m-25029110, medido 2026-11-23)

Desde `upload-preview-480p-strip-v2`, el mismo FFmpeg que hace la copia de 480p saca también la
tira de cuadros del editor: un cuadro por segundo, el último que haya hasta la mitad de cada
segundo (`i + 0,5` s; `setpts` + `fps`, que repite el cuadro anterior si el video no tiene
cuadros por más de un segundo, así que la tira nunca se corre), de 56 px de alto, en una sola imagen JPEG de una fila por minuto (60 cuadros por fila, tope
de una hora). El video se descarga y se decodifica una sola vez para las dos salidas
(`-filter_complex` con `split`). Va junto a la copia, en
`t/{tenant}/uploads/previews/{uuid5}/strip.jpg`. Costo de proveedor: US$0.

Las copias v1 que ya existían no se rehacen: se siguen mostrando, y su tira se pide aparte (un
trabajo v2 que encuentra la copia en su lugar y decodifica el original solo para la tira).

Medido con `deploy/measure/upload-preview-memory.sh run SOURCE [both|copy|strip]`, mismas
fuentes, imagen y límites que ED-09 (768m, 1 CPU, amd64), una corrida por contenedor:

| Fuente | Modo | Pico `anon` MiB | RSS de ffmpeg MiB | CPU s | Tira |
|---|---|---|---|---|---|
| 5K HEVC 10 bits, 112 s | copia sola (v1) | 406 | 427 | 372 | — |
| 5K HEVC 10 bits, 112 s | copia + tira (v2) | **408** | 430 | 465 | 6000×112, 109 KiB |
| 5K HEVC 10 bits, 112 s | tira sola | 367 | 390 | 329 | 6000×112, 96 KiB |
| 5K HEVC 8 bits, 112 s | copia + tira (v2) | 281 | 304 | 374 | 6000×112, 109 KiB |
| 4K HEVC 10 bits, 60 s, rotado 90° | copia + tira (v2) | 284 | 305 | 291 | 1920×56 (cuadros de 32 px), 15 KiB |
| 4K HEVC 10 bits, 60 s, rotado 90° | tira sola | 243 | 265 | 167 | 1920×56, 13 KiB |

Ningún OOM. La memoria no cambia con la tira (408 contra 406 MiB): el decodificador de 5K sigue
siendo lo que pesa. `memory.events max` > 0 en las corridas de 5K de 10 bits (también en la copia
sola): es la caché de archivos de la fuente de 900 MB empujando contra el límite, no memoria
anónima.

**Tiempo de CPU por minuto de video.** Las corridas largas varían mucho entre una y otra en esta
máquina (el mismo 5K de 8 bits dio 458 s de CPU con la copia sola el 2026-11-20 y 374 s con copia
+ tira hoy), así que el costo de la tira se midió aparte, con `-benchmark`, sobre 10 s del 5K de
10 bits, las variantes una detrás de otra en el mismo contenedor:

| Variante (10 s de 5K 10 bits) | CPU s, pasada 1 | CPU s, pasada 2 |
|---|---|---|
| copia sola, `-vf` (v1) | 40,2 | 62,5 |
| copia sola, `-filter_complex` | 35,8 | 34,4 |
| copia + tira (v2, lo que corre) | 36,1 | 52,9 |
| tira sola | 31,8 | 29,8 |

La segunda pasada muestra cuánto varía esta máquina (la misma copia sola: 34 a 63 s), así que el
costo propio de la tira no se puede separar con más precisión que eso. Lo que sí queda claro: la
tira sola (decodificar y tomar 1 cuadro por segundo) ya cuesta ~30 s de los ~35 s de la copia, o
sea que casi todo es decodificar el HEVC, y en la primera pasada, la más limpia, la tira sumó ~1 %.
La cota alta es la de las corridas largas: +25 % (465 contra 372 s).

Por minuto de video, en amd64 y 1 CPU: **copia + tira de un 5K de 10 bits, 200 a 250 s de CPU**
(la copia sola, ~200 s), **4K de 10 bits rotado, ~290 s**; **la tira sola de una copia v1,
~170–180 s por minuto** (decodifica el original otra vez). En arm64 (producción) será más; el
tiempo permitido (300 s + 20 s por segundo de video) no cambia y sobra.

## Textos sobre el final de una parte hecha con Seedance (m-25103284, medido 2026-11-23)

El final de una parte con textos o capas se compone directo sobre el 1080p que entrega
Seedance 2.5 (H.265 de 10 bits), sin pasarlo antes a H.264, dentro del candado `heavy_video`.
Harness: `deploy/measure/recompose-memory.sh` (caso nuevo `part_final_hevc10_3texts_3layers`,
fuente sintética de 15 s, 1080×1920, 10 bits, retenida una sola vez en memoria), imagen
`qualify-memtest:deps`, `--memory 768m --memory-swap 768m`, amd64 sin límite de CPU.

| Caso | Anon pico MiB | RSS MiB | cgroup pico MiB | CPU s | Pared s | OOM |
|---|---|---|---|---|---|---|
| Final de una parte, H.265 10 bits, 3 textos + 3 capas | **467** | — | 631 | 221 | 176 | no |
| Referencia EF-14: final de un Clip, H.264, 3 textos + 3 capas | 416 | 463 | 507 | 175 | 142 | no |

La primera corrida de la parte (2026-11-23) dio 569 s de pared, pero coincidió con pruebas en la
misma máquina; la cifra de la tabla es la de la máquina descargada (2026-11-24).

Lectura: cabe en los 768m del worker (467 MiB anónimos). Son ~3 min en amd64 por 15 s y más en
arm64 (sin medir), cerca del lease de 10 min. Por eso el final de una parte con textos corre fuera
del bucle principal del worker, en el hilo de fondo de las uniones, con el lease renovado y
`rendering_at` estampado mientras dura.

Hilos del decodificador (`EF14_DECODE=<tipo>:<hilos>` en el harness; el código usa SLICE×2):

| Decodificador | Anon pico MiB | cgroup pico MiB | CPU s | Pared s |
|---|---|---|---|---|
| SLICE×2 (el código), máquina descargada | 467 | 631 | 221 | 176 |
| FRAME×2 | 469 | 580 | 245 | 190 |
| AUTO×2 | 469 | 579 | 185 | 138 |
| FRAME×4 | 490 | 602 | 340 | 281 |

Decisión: no se cambia el código. AUTO×2 ahorra ~20 %, FRAME×2 y FRAME×4 no ayudan, y en un
escritorio con carga variable esas diferencias son ruido. Ningún caso se acerca a 768m. Vale la
pena repetirlo en arm64.

## Transiciones entre los bloques de un Clip (m-25114465, medido 2026-11-24)

Un bloque puede unirse con el anterior con «Fundido» o «Barrido». El armado pega los bloques con
corte, como siempre, y después mezcla las uniones con el código de la unión de partes de EF-16
(`video_pipeline/block_join.py`: segmentos, 1 hilo, un decodificador a la vez). Un Clip con solo
cortes no pasa por ese paso.

Harness: `deploy/measure/local-video-memory.sh` con los casos nuevos `blocks3_cut`,
`blocks3_fade2` y `blocks3_wipe2` (y `CPUS=1`, nuevo), imagen `qualify-memtest:deps`,
`--memory 768m --memory-swap 768m --cpus 1`, amd64, en el volumen temporal `m25114465-clips`
(borrado al terminar). Bloques: 20 s de 4K H.264 a ×2, 15 s de 1080p a ×1 y 20 s de 4K a ×2.

| Caso | Salida s | Pico anon MiB | prepare / speed / unión, anon MiB | RSS MiB | CPU s | Pared s | OOM |
|---|---|---|---|---|---|---|---|
| blocks3_cut (referencia) | 35,0 | 327 | 327 / 295 / — | 370 | 537 | 542 | no |
| blocks3_fade2 (2 × 0,8 s) | 33,4 | **341** | 341 / 284 / 275 | 384 | 908 | 914 | no |
| blocks3_wipe2 (2 × 0,8 s) | 33,4 | 338 | 338 / 280 / 262 | 381 | 1053 | 1060 | no |

El pico de cgroup llega a 768 MiB en los tres casos: es la caché de páginas de los archivos
copiados y escritos, que el kernel suelta antes de un OOM (`oom_kill` 0).

Lectura: cabe con holgura en 768m (pico anónimo 341 MiB, el mismo paso `prepare` de siempre). El
paso de unión usa ~275 MiB. El costo es el tiempo: +372 s con fundidos y +518 s con barridos a
1 CPU, porque vuelve a codificar el Clip entero y cada transición decodifica el tramo anterior
desde su comienzo (sin buscar). Si hiciera falta bajar ese tiempo, la opción es buscar el
cuadro clave más cercano en `encode_transition`; queda anotado, sin ticket.

Después de la revisión (2026-11-25) cada tramo se decodifica desde el cuadro clave anterior
(`JoinClip.seek`; la salida es la misma byte por byte). Repetí `blocks3_fade2` en las mismas
condiciones: pico anon 338 MiB, unión 276 MiB, 929 s de CPU y 936 s de pared. No bajó el
tiempo. Esa corrida coincidió con pruebas en la misma máquina, pero con 3 bloques casi todo el
costo de la unión está en volver a codificar el Clip, no en decodificar desde el comienzo. La
búsqueda ayuda más con muchos bloques.

### Clip de 60 s en 8 bloques y el latido (medido 2026-11-25, punta `cf3d0a53`)

Mismas condiciones (`qualify-memtest:deps`, `--memory 768m --memory-swap 768m --cpus 1`, amd64,
escritorio con Docker Desktop), fuentes hechas con
`make … --only k4_h264_60.mp4 hd_h264_15.mp4` en un volumen temporal propio
(`m25114465-clips-a84d`, borrado al terminar). Los tres casos se corrieron uno detrás del otro,
sin otra medición en paralelo. `blocks8_*` son 8 bloques de 7,5 s de salida que alternan 4K a ×2
y 1080p a ×1: 60 s con corte, 54,4 s con 7 uniones de 0,8 s (fundido y barrido alternados).

Para ver el latido, el harness corrió dentro de un envoltorio de medición que no está en el
repositorio: le pasa a `render_local_part` un `beat` que imprime la hora de cada latido, e imprime
la hora de cada paso. Es el mismo `beat` que recibe en el worker (`media._local_clip` →
`produce_local`); el resto no cambia. «Hueco» es el tiempo más largo entre dos latidos, contando
desde el arranque y hasta el final.

| Caso | Salida s | Pico anon MiB (tope 768) | prepare / speed / unión, anon MiB | CPU s | Pared s | `speed` s | Unión s | Hueco más largo sin latido | OOM |
|---|---|---|---|---|---|---|---|---|---|
| blocks3_wipe2 (2 barridos, con búsqueda) | 33,4 | 333 | 333 / 282 / 259 | 1157 | 1162 | 474 | 422 | 474 s (paso `speed`) | no |
| blocks8_cut (solo cortes) | 60,0 | **343** | 343 / 288 / — | 1378 | 1385 | 867 | no corre | **867 s** (paso `speed` hasta el final) | no |
| blocks8_mixed7 (7 uniones) | 54,4 | 340 | 340 / 280 / 278 | 1706 | 1715 | 635 | 708 | 636 s (paso `speed`) | no |

`oom_kill` 0 en los tres; el pico de cgroup llega a 768 MiB por la caché de páginas, como antes.

Lectura:

- **Memoria:** cabe. El pico sigue en `prepare` del 4K (~340 MiB); la unión de 7 transiciones
  usa 278 MiB, lo mismo que con 2.
- **Tiempo:** el Clip más largo con 7 uniones tarda 28,6 min de pared a 1 CPU; el paso de unión
  es 11,8 min de eso. `blocks3_wipe2` con la búsqueda tardó más que sin ella (1162 s contra
  1060 s el 2026-11-24), pero la diferencia está en `speed`, que no cambió: es ruido de la
  máquina. Las corridas del mismo día también varían (`speed` 867 s con cortes contra 635 s
  con uniones, sobre las mismas fuentes).
- **Latido durante la unión:** sí, cada ≤60 s (hueco más largo dentro de la unión: 60,0 s).
- **El hueco largo no está en la unión, está en `speed`:** `render_speed` no da latidos, y
  con 8 bloques a 1 CPU estuvo **14,5 min** sin latido (`blocks8_cut`, donde además no hay
  latido después de `speed` porque no hay unión, capas ni textos). El reaper marca fallido a
  los 20 min: queda un margen de ~5,5 min en amd64, y arm64 (no medido) puede ser más lento.
  No viene de m-25114465 (pasa igual sin transiciones), pero este Clip de 60 s es el que lo
  acerca al límite. Queda anotado para quien lleve el armado local; no se cambió código.

## Pendiente

- **Medir el normalizador con un video real de iPhone de 10 bits** (HEVC, 4K): necesita el
  teléfono de Deivid. Mismo harness: copiar el archivo al volumen `norm-clips` (carpeta `src/`),
  y correr `run`, `quality`, `publish` y `compare` (m-25071265).
- Medir en arm64 cuando haya una imagen arm64 construida.
- Encolar la normalización al subir el video, no al armar (ticket aparte).
- `QUALIFY_CREATIVE_DISPATCHER=queue` en producción: confirmado el 2026-11-16 (`/opt/qualify/.env.prod`,
  línea 149, leído por Deivid sin cambios).

## Encender el editor «Arma tu video» (B6, m-25048789)

Desde B6, «Crear» en el editor del Clip manda su receta en los campos que lee EF-06
(`media.segments`, `media.text_layers`, `media.effects`, con `clip_reference_mode = "local"`): las
fotos y los videos de la línea de tiempo en su orden, las velocidades, los cortes, el texto con su
lugar y sus tiempos, y Vapor, Humo y Brasas con sus tiempos. `media.edit_recipe` ya no se manda; un
borrador guardado con esa clave se sigue leyendo (se ignora). El interruptor sigue apagado
(`QUALIFY_CLIP_EDITOR=off` en `.env.example` y `deploy/.env.prod.example`). Para encenderlo en
producción falta:

- el OK de Deivid;
- A9 (m-25042483) en main;
- `QUALIFY_CREATIVE_DISPATCHER=queue` (ya confirmado) y el `creative-worker` corriendo: con hilos el
  backend rechaza el video (`local_unavailable`) y la pantalla lo dice;
- cambiar `QUALIFY_CLIP_EDITOR=1` en `/opt/qualify/.env.prod` por el camino documentado
  (`just env-push`, skill `qualify-prod-ops`) y reiniciar la app.
