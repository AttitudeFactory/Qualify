# IS-Net `isnet-general-use`: quitar el fondo de la foto del producto (candidato)

> **Estado: candidato, no conectado.** Es el modelo que recomienda RECORTE-001 para la opción B de
> la historia m-25042543. El fundador decide entre las opciones de
> [`spike-sistema-visual-marca.md` §7.6](../spike-sistema-visual-marca.md). Hoy el repositorio
> nombra `birefnet-general-lite` en `qualify_creative/photo/segment.py`, y esa elección no se
> sostiene en un servidor de 4 GB (ver más abajo).

| Campo | Valor |
|---|---|
| Proveedor | Local: `rembg` 2.0.88 + onnxruntime 1.32.0 en CPU. Sin llamadas a terceros: la foto no sale del servidor |
| Modelo | `isnet-general-use` (IS-Net, «Highly Accurate Dichotomous Image Segmentation», `xuebinqin/DIS`) · archivo `isnet-general-use.onnx`, 178,6 MB, md5 `fc16ebd8b0c10d971d3513d564d01e29` · release `v0.0.0` de `danielgatis/rembg` |
| Entrada | Cualquier tamaño; el modelo trabaja a 1024×1024 y la máscara se lleva al tamaño original |
| Salida | Máscara alfa de 8 bits (`L`), del mismo tamaño que la foto; se usa con `LocalBiRefNetSegmenter(model_name="isnet-general-use")` tal cual |
| Licencia | Código Apache-2.0. Los pesos se publican con ese repositorio, sin licencia propia; los términos del conjunto DIS5K no se leyeron. Uso comercial: **sí, con esa reserva** |
| Costo | US$0 por foto: CPU y RAM del servidor, una vez por foto del catálogo |
| Memoria | ~1,3 GB de pico en Linux arm64 (1,34 GB medido), 1,2 GB en macOS. **No cabe en ningún tope actual** de `deploy/docker-compose.prod.yml`: creative-worker y media-worker tienen 768m, y render tiene 1536m pero ya lo ocupa Chromium |
| Tiempo | 1,1–1,6 s por foto en M1 Pro; 5–8 s en Linux arm64 con 2 CPU (Docker Desktop); 1,7 s de carga |

## Por qué este y no `birefnet-general-lite`

| | `birefnet-general-lite` (lo que dice el repositorio) | `isnet-general-use` | `u2net` |
|---|---|---|---|
| Calidad en fotos de teléfono (botellas) | La mejor | Casi igual; manchas fantasma suaves en 1 de 3 | Pierde una tapa blanca en 1 de 3 |
| Fotos GoPro de comida con fondo cargado | Se lleva la plancha del trompo | El mejor en el trompo; deja semitransparente un segundo producto | Se pierde el segundo producto |
| Pico de RAM en Linux arm64 | **Más de 6 GB: muere por memoria** | 1,34 GB | 0,96 GB |
| Por foto (Linux, 2 CPU) | — | 5–8 s | 2–4 s |

`birefnet-general-lite` gana en calidad pero no corre en el CAX21. `u2net` es el más liviano, pero
pierde partes del producto (tapas, un segundo producto), que es el error más caro para la marca.

## Pruebas

- [RECORTE-001](pruebas.md#recorte-001) — 2026-11-26/27: 10 fotos reales (teléfono, estudio, GoPro)
  × 3 modelos, en Mac y en un contenedor Linux arm64. Costo US$0.

## Lo que falta antes de conectarlo

1. **Medir en el CAX21 real** (arm64 nativo): el pico de RAM y el tiempo con 1 CPU, y la memoria
   libre del servidor a esa hora.
2. **Conjunto de oro:** ~30 fotos reales del catálogo de varios negocios, cada una con su veredicto
   (sirve / no sirve) según reglas escritas antes. Pasa si sirve en ≥ 80 % de las fotos de producto.
3. **Regla de rechazo,** para volver a la foto en el disco cuando el recorte no sirva: la caja del
   alfa pegada al borde, un producto partido en piezas o una proporción de primer plano fuera de
   rango.
4. **Dónde corre:** un proceso de una sola foto, con su propio tope (~1,5 GB) y uno a la vez en todo
   el servidor, como media-worker. Es un servicio o tope nuevo: pide la decisión del fundador.
5. **Procedencia:** guardar en la fila de la máscara el modelo, el md5 de los pesos y la versión
   de rembg.
