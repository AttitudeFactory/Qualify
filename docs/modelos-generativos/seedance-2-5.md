# Seedance 2.5 — borradores con referencias (m-24820142)

| Campo | Valor |
|---|---|
| Proveedor | BytePlus ModelArk (`https://ark.ap-southeast.bytepluses.com/api/v3`), llave `QUALIFY_BYTEPLUS_ARK_API_KEY` |
| Modelo | `dreamina-seedance-2-5-260628`, activo desde 2026-10-23 en `QUALIFY_SEEDANCE_MODEL` y `QUALIFY_SEEDANCE_REFERENCE_MODEL` |
| Precio | Por token, inferencia en línea ([model-pricing](https://docs.byteplus.com/en/docs/ModelArk/model-pricing)). **Sin video de entrada:** 480p/720p USD 10,70/M, 1080p 11,70/M. **Con video de entrada:** 480p/720p USD 6,40/M, 1080p 7,00/M. El final de un borrador paga la tarifa que corresponde a su borrador. Tabla de precios `v7` (`qualify_creative/pricing_data/v7.json`) |
| Uso en Qualify | `SeedanceVideoAdapter` (`qualify_creative/adapters/byteplus_ark.py`) desde `MediaProducer` (`qualify_api/creative/media.py`): clip, video con presentador de Seedance y diapositiva animada de la galería. Con 2.5 todo video sale como **borrador a 480p** y el final a 1080p se hace al aprobar (`docs/pendientes-generador-contenido.md` §4.1) |
| Datos | Imágenes del catálogo y de la marca, videos y audios que sube el operador. Los videos y audios de referencia viajan como URL pública temporal (`/public/media/{token}`); ModelArk no acepta Base64 para ellos. Endpoint personalizado, no los preajustes autorizados que ceden datos |
| Tickets | m-24820142 (modo borrador), m-24820832 (criterios 3–4), m-24849431, m-24848887, m-24849137 |

## Prueba SD25-001 — borradores con y sin video de referencia — 2026-10-23

- **Quién:** Deivid con Claude Code, prueba local real de «Crear pieza».
- **Montaje:** la API (`qualify_api`) en local en el puerto 8010 detrás de un túnel rápido de `cloudflared`, con `QUALIFY_PUBLIC_MEDIA_BASE_URL` apuntando al túnel (la ruta `/public/media/{token}` vive en la API, no en Reflex). Pasos en `.env.example`.
- **Ajustes:** borrador (`draft: true`) a 480p, 5 s, `omni_reference_task_type: reference` cuando hay referencias.
- **Material:** fotos de producto y videos cortos subidos por el operador. No hay caras reales en las referencias (2.x las rechaza).

| Pieza / tarea | Entradas | Tokens cobrados (`usage.completion_tokens`) | Costo registrado entonces | Costo real (tarifa con video) |
|---|---|---|---|---|
| Galería `30fd667e`, diapositiva animada | Sin video de referencia | 49.673 | US$0,531501 (10,70/M) | US$0,531501 (misma tarifa) |
| Clip, `cgt-20261024063856-4djtl` | 3 imágenes + 1 video (7,33 s) + 1 audio | 115.690 | US$1,237883 (10,70/M) | **US$0,740416** (6,40/M) |
| Galería, diapositiva animada, `cgt-20261024064403-nwzl2` | 1 video de referencia (7,33 s) | 118.851 | US$1,271706 (10,70/M) | **US$0,760646** (6,40/M) |
| Clip `39323f4d` | 2 videos de referencia (22 s en total) | 259.802 | US$2,779881 (10,70/M) | **US$1,662733** (6,40/M) |

**Resultado:**

- El clip siguió **todas** sus referencias: las tres imágenes, el video y el audio. La diapositiva animada siguió el movimiento y el ritmo de su video de referencia.
- **Hallazgo 1, la tarifa.** Las tareas con video de entrada se registraron a 10,70/M, la única tarifa de la tabla `v5` («input without video»). BytePlus cobra 6,40/M en ese caso. En las tres tareas con video, el registro sumó US$5,29 frente a US$3,16 reales, un 67 % de más. Corregido con la tabla `v7`. Ahora el borrador guarda `video_input` y el final usa la tarifa de su borrador.
- **Hallazgo 2, los tokens incluyen el video de entrada.** La fórmula `ancho × alto × 24 × segundos / 1024` del video de salida da unos 48.000 tokens para 5 s a 480p (9.607 tokens/s en 9:16, 9.870 en 3:4). El borrador sin video cobró 49.673, lo esperado. Con un video de 7,33 s cobró 115.690 y 118.851, unas **2,4 veces** la estimación.
  - Si se suman los segundos del video de entrada a los de salida, a la misma tasa por segundo y al tamaño de salida, la fórmula encaja con las tres mediciones. Con (5 + 7,33) s salen 118.461 (9:16) a 121.697 (3:4), frente a 115.690 y 118.851 cobrados. Con (5 + 22) s salen 259.403 (9:16) a 266.490 (3:4), frente a 259.802 cobrados.
  - Así calcula ahora la estimación previa al gasto (`estimate_video_tokens`, `input_video_seconds`). Los segundos del video de referencia se leen con PyAV. Si no se pueden leer, se usa el máximo que acepta una tarea (30 s), para no quedarse corto.
- **Hallazgo 3, el costo no quedaba en el registro de uso.** Las filas de Seedance en `creative_usage_events` tenían `unit = second`, `pieces = 5` y `output_tokens = 0`: los tokens solo estaban en `image_assets.params`. Desde este cambio `output_tokens` lleva `completion_tokens`.
- **Costo por pieza con la tarifa corregida:** un borrador de 5 s con un video de referencia de unos 7 s cuesta ≈ US$0,75. Sin video cuesta ≈ US$0,53.

**Pendiente:**

- Medir en vivo un **final a 1080p** de un borrador con video. No se sabe si sus tokens vuelven a contar el video de entrada; la estimación supone que sí, para no quedarse corta. Con 5 s a 1080p (9:16) y 7,33 s de entrada serían ≈ 600.000 tokens, ≈ US$4,20 a 7,00/M. Sin el video de entrada serían ≈ 243.000 tokens, ≈ US$1,70.
- Confirmar las tarifas con la primera factura de BytePlus.
- Seedance 2.0 (y fast, mini) también tiene tarifa con video, pero no está en la tabla. Hoy se cobra a la tarifa sin video, que es la más alta: el registro se pasa, nunca se queda corto.

> Cuando la bitácora central (`docs/modelos-generativos/pruebas.md`, hoy sin commitear en otra rama) llegue a `main`, copiar esta entrada ahí.
