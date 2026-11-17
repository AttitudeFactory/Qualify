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

## Pendiente

- Tope por pieza (fuente de máximo 4K a 8 bits, o 60 s por tramo) y no armar en paralelo con una
  unión de partes: propuesta aparte, sin decidir.
- Volver a medir cuando el compose de EF-05 se enganche en `video_pipeline/local.py`, y en arm64
  cuando haya una imagen arm64 construida.
- `QUALIFY_CREATIVE_DISPATCHER=queue` en producción: confirmado el 2026-11-16 (`/opt/qualify/.env.prod`,
  línea 149, leído por Deivid sin cambios).
