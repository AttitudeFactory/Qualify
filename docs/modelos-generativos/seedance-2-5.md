# Seedance 2.5 — borradores con referencias (m-24820142)

| Campo | Valor |
|---|---|
| Proveedor | BytePlus ModelArk (`https://ark.ap-southeast.bytepluses.com/api/v3`), llave `QUALIFY_BYTEPLUS_ARK_API_KEY` |
| Modelo | `dreamina-seedance-2-5-260628`, activo desde 2026-10-23 en `QUALIFY_SEEDANCE_MODEL` y `QUALIFY_SEEDANCE_REFERENCE_MODEL` |
| Precio | Por token, inferencia en línea ([model-pricing](https://docs.byteplus.com/en/docs/ModelArk/model-pricing)). **Sin video de entrada:** 480p/720p USD 10,70/M, 1080p 11,70/M. **Con video de entrada:** 480p/720p USD 6,40/M, 1080p 7,00/M. El final de un borrador paga la tarifa que corresponde a su borrador. Tabla de precios `v7` (`qualify_creative/pricing_data/v7.json`) |
| Uso en Qualify | `SeedanceVideoAdapter` (`qualify_creative/adapters/byteplus_ark.py`) desde `MediaProducer` (`qualify_api/creative/media.py`): clip, video con presentador de Seedance y diapositiva animada de la galería. Con 2.5 todo video sale como **borrador a 480p** y el final a 1080p se hace al aprobar (`docs/pendientes-generador-contenido.md` §4.1) |
| Datos | Imágenes del catálogo y de la marca, videos y audios que sube el operador. Los videos y audios de referencia viajan como URL pública temporal (`/public/media/{token}`); ModelArk no acepta Base64 para ellos. Endpoint personalizado, no los preajustes autorizados que ceden datos |
| Tickets | m-24820142 (modo borrador), m-24820832 (criterios 3–4), m-24849431, m-24848887, m-24849137, m-24854841 (SD25-002) |

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

- Medir en vivo un **final a 1080p** de un borrador con video (el de un borrador sin video ya está medido: SD25-002, USD 2,87 frente a 2,85, H2 confirmada). No se sabe si sus tokens vuelven a contar el video de entrada; la estimación supone que sí, para no quedarse corta. Con 5 s a 1080p (9:16) y 7,33 s de entrada serían ≈ 600.000 tokens, ≈ US$4,20 a 7,00/M. Sin el video de entrada serían ≈ 243.000 tokens, ≈ US$1,70.
- Confirmar las tarifas con la primera factura de BytePlus.
- Seedance 2.0 (y fast, mini) también tiene tarifa con video, pero no está en la tabla. Hoy se cobra a la tarifa sin video, que es la más alta: el registro se pasa, nunca se queda corto.

## Prueba SD25-002 — primer final 1080p medido en vivo — 2026-10-24 (m-24854841)

- **Modelo:** `dreamina-seedance-2-5-260628`, endpoint personalizado de ModelArk (no los preajustes que ceden datos).
- **Tarea:** `cgt-20261024004332-yguur`, el **final** del borrador `cgt-20261024004006-2xl5m` (borrador 480p, 5 s, 49.673 tokens, **sin video de entrada**).
- **Ajustes:** final a 1080p desde el borrador (`draft_task_id`), 5 s, misma proporción que el borrador (3:4 por su conteo de tokens). Tarifa 1080p sin video de entrada, USD 11,70/M (tabla `v7`).
- **Cómo se leyó:** `arkcli gen list` (solo lectura, tareas de los últimos 7 días) durante el análisis de concurrencia (`docs/escalar-generacion-concurrencia.md` §1.3). La tarea ya existía en la cuenta; este análisis no lanzó ninguna generación. Tiempo = `updated_at − created_at`, cola de BytePlus incluida (cero a este volumen).

| Medida | Calculado (`docs/modelo-cobro-generacion.md`) | Medido |
|---|---|---|
| Tokens (`usage.completion_tokens`) | 243.360 (48.672 tokens/s × 5 s, 1080p 3:4) | **245.388** (+0,8 %) |
| Costo | USD 2,85 (0,5695/s × 5 s) | **USD 2,87** (245.388 × 11,70/M = 2,871; +0,7 %) |
| Tiempo de render | — | **38 s** |

**Resultado:**

- **H2 confirmada** («el final 1080p cuesta lo que dice la fórmula», `docs/modelo-cobro-generacion.md`, D26): la desviación es 0,7 %, dentro de lo que ya se vio en los borradores (49.673 cobrados frente a 49.350 calculados a 3:4, +0,65 %). Los techos de costo del final no cambian.
- El final tarda **menos que su borrador** (38 s frente a 66 s): para planificar la cola, 60 s por final es conservador (n = 1).
- **No responde** si un final vuelve a cobrar el video de entrada de su borrador: este borrador no tenía video. Ese pendiente de SD25-001 sigue abierto.
- n = 1, un solo día, sin carga en BytePlus.

## Medición continua: cola, tareas a la vez y render — desde 2026-10-26 (m-24852158)

SD25-002 y la tabla de `docs/escalar-generacion-concurrencia.md` §1.3 salieron de `arkcli gen list`
(`updated_at − created_at`, sin separar cola y render). Desde m-24852158 cada tarea de Seedance y de
OmniHuman deja sus marcas en `creative_vendor_task_timings` (migración 0094), tomadas de las mismas
consultas que el adaptador ya hace mientras espera (ninguna llamada extra a BytePlus):

| Marca | Cuándo se pone | Cuándo queda vacía o «tarde» |
|---|---|---|
| `submitted_at` | ModelArk acepta la tarea (el mismo momento en que 0090 guarda el id) | — |
| `running_at` | primera respuesta `running` (`generating` en OmniHuman) | vacía si ninguna espera en vivo la vio pasar de `queued` a `running` (una reanudada que ya la encuentra corriendo): la espera queda desconocida, nunca inflada |
| `finished_at` + `final_status` | primera respuesta final | `finished_late` = sí cuando la vio una reanudada sin haberla visto activa: es un tope, cuenta para «a la vez» pero no para el render |

Resolución: una consulta cada 5 s, así que cada marca tiene hasta 5 s de error.

**Cómo leerlo** (solo el equipo; ninguna pantalla del dueño lo muestra):

```bash
just creative-queue-report --days 7            # todos los negocios, horas de Bogotá
just creative-queue-report --days 7 --json     # lo mismo, para guardar
```

Devuelve, por grupo de modelos (Seedance 2.5 borradores y finales juntos, porque comparten las 10 de
BytePlus; OmniHuman aparte), para todo el periodo, por día y por hora:

- **a la vez**: cuántas tareas del grupo estaban en BytePlus (en cola o corriendo, ella incluida) en el
  momento en que se envió cada tarea; p50 / p95 / máx sobre las tareas;
- **espera**: `running_at − submitted_at`, p50 / p95 / máx;
- **render**: `finished_at − running_at` por borrador y final.

Y los tres disparadores de la épica: p95 a la vez ≥ 5 (ticket a BytePlus, m-24852172), alguna espera
> 60 s o p95 a la vez ≥ 7 (cola propia), espera p95 > 5 min («Generar ya», m-24852171).

**Datos de arranque.** La migración copia las tareas que ya estaban en `creative_vendor_tasks` (desde
0090) con `submitted_at` y `finished_at` (marcado como «tarde») y sin `running_at`: sirven para «a la vez»,
no para espera ni render. **Primeras mediciones reales de producción: pendientes** hasta que esto se
despliegue y corra una semana; se anotan aquí como SD25-003 (borrador y final de 10 s), con la salida de
`just creative-queue-report --days 7`.

## Revisión de precios para los pesos v2 — 2026-10-24 (m-24851828)

- **Sin llamadas al proveedor.** Se intentó releer en vivo la página de precios de ModelArk
  y la del producto Seedance: las dos cargan los precios con JavaScript y no se pudieron leer.
  Se usan las tarifas de `v7` (leídas el 2026-10-07 y el 2026-10-23).
- **Sonido:** `v7` tiene una sola tarifa con o sin `generate_audio`. En SD25-001 el clip con
  sonido facturó 115.690 tokens y la diapositiva sin sonido 118.851, los dos dentro de la
  fórmula: el sonido no añade tokens. Los pesos v2 no cambian con «Con sonido».
- **Costo por segundo con vista previa 480p + final 1080p** (proporción 3:4, la más cara):
  sin video de entrada USD 0,675 por segundo (0,106 + 0,569); con video de entrada USD 0,404
  por segundo de salida más entrada. Un clip de 5 s cuesta ≈ USD 3,44: **23 creaciones**
  (`docs/creaciones-del-mes-medicion.md` §5).

> Cuando la bitácora central (`docs/modelos-generativos/pruebas.md`, hoy sin commitear en otra rama) llegue a `main`, copiar esta entrada ahí.
