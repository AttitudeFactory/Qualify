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

## Incidente: tres clips cortados al crear la tarea — 2026-11-03 (m-24820842)

- **Qué pasó.** Los borradores 9808559f, cb647505 y 0bcd259b (21:47–21:53, `reflex.log`)
  fallaron con `POST /contents/generations/tasks` → `ReadTimeout` a los ~62 s. La primera
  tarea igual se creó (`cgt-20261104094816-85ali`) un segundo después de que cortamos, y
  terminó `Invalid video_url`.
- **Causa.** ModelArk descarga los videos de referencia **dentro** del POST. Los de stock eran
  1080p (5,08 MB / 15 s a 25 fps y 3,56 MB / 6,6 s a 60 fps), y `/public/media` los servía
  sin `Content-Length`, sin rangos y leyendo el objeto entero de R2 antes del primer byte
  (5–8 s), a ~0,2 MB/s por el túnel de desarrollo.
- **Cambios (sin llamadas pagadas).** (1) Cada video de referencia se aligera antes de pagar
  el texto: 720p en el lado corto, ≤ 30 fps, H.264 crf 23, sin audio, recortado a
  max(duración del clip, 5 s) dentro de los límites de la familia (2.0: 2–15 s cada uno,
  15 s en total; 2.5: 2–30 s, 30 s en total); la réplica fiel (`edit`) no se recorta. Medido
  en local con los dos archivos del incidente: 5,08 MB → 0,83 MB (5 s, 2,2 s de CPU) y
  3,56 MB → 1,47 MB (5 s, 60 → 30 fps, 2,1 s). (2) `/public/media` manda `Content-Length`,
  `Accept-Ranges` y responde rangos (206), leyendo R2 por tramos de 1 MB. (3) El POST que
  crea la tarea espera 180 s; si se corta o vence, **no se reenvía**: se busca la tarea en
  la lista (`filter.model`) y se adopta. La API no tiene clave de idempotencia (docs leídas
  el 2026-11-03), así que **toda** tarea de Seedance 2.x (clips y el final 1080p de un
  borrador 2.5) va con `execution_expires_after` = el vencimiento pedido (48 h si no se pidió
  ninguno) + 1..3000 s al azar (o − 1..3000 s si pasaría de 72 h). La lista devuelve ese
  valor y permite reconocer la tarea propia. **Solo se adopta por esa marca**: la lista
  abarca toda la cuenta de BytePlus, con las tareas de todos los clientes, así que una tarea
  parecida sin la marca (mismo modelo, misma resolución, mismo momento) puede ser de otro
  cliente y nunca se adopta; sube el error del POST (revisión de código 2026-11-04, B1).
  Fuera de la marca solo se exige que la tarea se haya creado después de empezar el POST y
  que no esté cancelada: `ratio`, `resolution`, `duration` y `draft` **no** se comparan,
  porque `ratio: adaptive` y `duration: -1` pueden volver ya resueltos («9:16», 5 s) y
  rechazar la tarea propia la dejaría cobrada y sin borrador (revisión 2026-11-04, S1).
  **Seedance 1.x no lleva marca y nunca se adopta**: el campo solo está documentado y en uso
  para 2.x, así que un POST de 1.x que vence sube su error como antes (sin duplicar).
- **Pendiente.** Medir en vivo el tiempo del POST con referencias ligeras (próxima prueba
  SD25-003 o en uso real).

## `extend` («Sigue a la anterior») — construido 2026-11-13, medido en vivo 2026-11-14 (EXT-001)

- **Tickets:** m-24880328 (modo `extend` en adaptador, esquema y servicio) y m-24921070
  (VE-13, el cableado por parte). Primera prueba en vivo: EXT-001, abajo (US$1,13). Las
  preguntas [H] de la lista siguiente quedan respondidas allí; se dejan como se escribieron
  antes de medir.
- **Qué se manda.** Una tarea omni de 2.5 con `omni_reference_task_type: extend`,
  `ratio: adaptive`, `duration` = los segundos de la parte (4–10), `draft: true` (480p),
  `generate_audio` como cualquier parte, las fotos del producto como `reference_images` y
  **un** `reference_video`: el archivo de la parte anterior tal como salió de Seedance (la
  copia byte a byte que guarda la cola, `queue-{job}.bin`, copiada sin recodificar a
  `extend-source-{asset}.mp4` en la carpeta de la parte). Sin recodificar porque BytePlus
  acepta rostros solo en salidas propias sin editar. El precio se estima con
  `reference_video_seconds` = lo que dura ese archivo (tarifa «con video de entrada»).
  Prompt: `part_extend_prompt` (versión de prompt de parte 5), empieza por «Extend video
  @Video1: continue it seamlessly from its last frame…»; el modelo clasifica la tarea por el
  prompt (`TaskTypeMismatch` si no la pide).
- **Lo que no se sabe [H] y cómo lo cubre el código:**
  1. *¿`extend` acepta `draft: true`?* Interruptor `QUALIFY_PARTS_EXTEND` (`off` por
     omisión, `draft` para activarlo). Apagado, nada crea ni manda una parte `extend`: el
     plan la rechaza con «Por ahora no podemos crear una parte que siga a la anterior» y la
     pantalla muestra la opción desactivada. Si la prueba muestra que no acepta borrador,
     se queda apagado (nunca se pasa a un final sin vista previa).
  2. *¿Devuelve solo el tramo nuevo o el video entero?* `QUALIFY_SEEDANCE_EXTEND_OUTPUT`
     (`auto` por omisión, `segment`, `whole`). En `auto` se mide la salida y se compara con
     las dos lecturas (segundos pedidos frente a entrada + pedidos). La pieza guarda
     `params.part.extend.output`, `input_seconds` y `output_seconds`; la unión se queda solo
     con el tramo nuevo en los dos casos (`part_join.part_span`), así que ningún cuadro de la
     parte anterior sale dos veces (prueba sintética con PyAV en
     `test_creative_part_extend.py`).
  3. *¿Cómo se interpreta `duration`?* Se manda la duración del tramo nuevo. Si la prueba
     muestra que es la duración total, se corrige aquí y en `_clip`.
- **Prueba en vivo propuesta (pendiente del OK de Deivid):** con un producto de Nibbles,
  parte 1 «Nueva» (borrador 5 s, sin video de entrada, ≈ US$0,53) y parte 2 `extend` sobre
  ella (borrador 5 s con 5 s de entrada: ≈ 95.000 tokens a 6,40/M ≈ US$0,61; si devuelve el
  video entero y se cobra por la salida de 10 s, ≈ US$0,93). Total ≈ **US$1,15–1,50**. Con
  el final 1080p de la parte 2 para ver si el contrato se mantiene (R10/VE-16), ≈ US$1,70–4,20
  más. Registrar ids de tarea, tokens, duración de salida y si la unión empalma.
  Se corrió sin el final 1080p: EXT-001, abajo.

### Prueba EXT-001 — `extend` en borrador sobre una parte «Nueva» — 2026-11-14 (m-24880328)

- **Montaje:** script fuera del repositorio, una tarea a la vez, sin repeticiones, tope de
  US$1,50. Llave de la app (`QUALIFY_BYTEPLUS_ARK_API_KEY`), de día (12:52–13:03, hora de
  Bogotá). Endpoint personalizado. Producto «Super Smash» de Nibbles como
  `reference_images` en las dos tareas; nada escrito en la base ni en R2. Detalle completo en
  [pruebas.md](pruebas.md#ext-001).
- **Ajustes:** borrador (`draft: true`) a 480p, 5 s, con audio. Parte 1:
  `omni_reference_task_type: reference`, `ratio: 9:16`. Parte 2: `extend`, `ratio: adaptive`,
  `duration: 5`, `reference_video` = el MP4 de la parte 1 sin recodificar (5,042 s).

| Tarea | Paso | Tokens | Tarifa | Costo | Salida |
|---|---|---|---|---|---|
| `cgt-20261114205252-35pwm` | Parte 1 «Nueva» | 48.437 | 10,70/M | US$0,518276 | 5,042 s |
| `cgt-20261114210137-3ugjk` | Parte 2 `extend` | 96.075 | 6,40/M | US$0,614880 | 5,000 s |
| | **Total** | | | **US$1,133156** | |

**Respuestas a las tres preguntas [H]:**

1. **`extend` acepta borrador.** La tarea vuelve con `draft: true`, 480p y 24 fps.
2. **Devuelve solo el tramo nuevo.** Se pidieron 5 s y llegaron 5,000 s. Desde este cambio
   `QUALIFY_SEEDANCE_EXTEND_OUTPUT` vale `segment` por omisión; si una salida mide más cerca
   de entrada + pedido que de lo pedido, se registra `creative.extend.unexpected_whole` y se
   trata como `whole` (la unión sigue sin repetir cuadros). `auto` y `whole` quedan como
   valores explícitos.
3. **`duration` es la duración del tramo nuevo**, como ya mandaba `_clip`. Sin cambios.

**Otros hallazgos:**

- **Tokens:** (5,04 s de entrada + 5 s de salida) × ~9.607 tokens/s ≈ 96.475 estimados frente
  a 96.075 cobrados: la fórmula de SD25-001 vale también para `extend`.
- **`ratio`:** la parte 2 responde `240:427` (el del video de entrada, 480×854). El código
  guarda el `ratio` del encargo; no rompe nada.
- **Unión:** el cuadro 0 de la parte 2 difiere del último de la parte 1 lo mismo que dos
  cuadros seguidos (3,0 frente a 3,1 de diferencia media por píxel). Audio en las dos partes,
  con nivel parecido en la unión (RMS 0,014 → 0,012).
- **Descargas:** ModelArk pidió el MP4 de entrada dos veces a la URL pública temporal.
- **Fidelidad del producto:** en la parte 1 el queso ya pasa a salsa chorreante, faltan
  pepinillos y cebolla, y al fondo aparece el logo redondo de otra cadena. La parte 2 lo
  conserva; el pan crece y aparece la mano que pide el prompt.

**Riesgos y pendiente:**

- **n = 1**: una pareja de tareas, un producto.
- **El final 1080p de una parte `extend` no se midió:** no se sabe si vuelve a cobrar el video
  de entrada (la estimación supone que sí) ni si el contrato se mantiene (R10/VE-16).
- **`extend` arrastra los defectos de la parte anterior:** la fidelidad del producto se
  degrada desde la parte 1 y la continuación la hereda.
- **Logo de otra cadena al fondo:** lo tiene que ver el control de marca antes de que la pieza
  llegue al dueño.
- `QUALIFY_PARTS_EXTEND` sigue en `off`; encenderlo (`draft`) es una decisión aparte.

## Prueba EF11-001 — cuadro preparado como «Image 1» en una parte «Nueva» con fotos (prompt de parte v6) — 2026-11-20/21 (m-25078702)

- **Qué se mide:** EF-11 (m-25026585, PR #768) dejó detrás de
  `QUALIFY_PARTS_PREPARED_FRAME_REFS` (apagado) el camino de una parte `reference` («Nueva»)
  que lleva tramos del video propio del dueño **y** fotos de producto. ModelArk no acepta
  `first_frame` junto a referencias, así que el primer cuadro del tramo, ya preparado (derecho
  y 9:16), va como primera `reference_image` y el prompt de la parte pasa a la versión 6
  (`PART_PREPARED_FRAME_PROMPT_VERSION`, `part_reference_prompt(opening_frame=True)`): agrega
  «The opening frame is Image 1: the shot starts on it and brings it to life.» y numera las
  fotos desde la 2.
- **Línea base:** la misma parte **sin** tramos propios, lo que hace hoy `main` con el
  interruptor apagado: solo las fotos, prompt de parte versión 3 (compilador 6).
- **Montaje:** `packages/api/evals/prompt_v6_partes/run_experiment.py`. Llama al
  `MediaProducer.produce` real y al `SeedanceVideoAdapter` real (nada de la lógica duplicada);
  el interruptor se enciende **solo dentro del proceso** de la variante v6. Almacén en memoria,
  nada escrito en la base ni en R2. Salidas fuera del repositorio (`%TEMP%/m-25078702/`).
- **Ajustes, iguales en las dos variantes:** `dreamina-seedance-2-5-260628`, borrador
  (`draft: true`) a 480p, 4 s (el mínimo de una parte), `ratio: 9:16`,
  `omni_reference_task_type: reference`, con audio (lo que pide el brief por omisión), misma
  descripción de la parte, mismo producto y misma marca ficticia.
- **Material real de un negocio nuestro (decisión de Deivid, 2026-11-20: «llave de app +
  material real»):** una hamburguesería del catálogo de desarrollo, leído solo con la puerta
  `tenant_session` de su negocio en una transacción de solo lectura y del volumen local de
  subidas por las mismas llaves de la app; nada escrito, cambiado ni borrado. Fotos: la foto
  principal de dos productos del catálogo (una smash triple sostenida en la mano y una smash
  doble sobre papel). «Video propio»: el único video que subió el negocio, un clip de 4,8 s de
  una hamburguesa de pan con ajonjolí sobre fondo negro que gira despacio (un clip de banco de
  imágenes que el dueño subió como referencia, no su propio producto); tramo 0,0–2,4 s en el
  caso A y 2,4–4,8 s en el B. Marca: paleta y tipografías del Brand Kit del negocio. El
  material se descargó a `%TEMP%\m-25078702\` (fuera del repositorio) y los casos se pasan
  al script con `--cases`; no entra al repositorio. Sin `--cases`, el script usa
  las fotos de muestra y los videos de efectos del repositorio.
- **Tope de gasto:** US$2,00 en total (Deivid, 2026-11-20, vía «creacion de tickets»). Cada
  tarea se cotiza con la fórmula del adaptador y la tabla `v8` antes de enviarse, se reserva
  con 10 % de margen en un `SpendLedger` con techo de US$2 y se liquida con los tokens que
  cobra ModelArk. Sin Claude: el texto es fijo (el prompt de una parte no lo usa).
- **Plan cotizado (corrida en seco, sin gasto):** 2 casos × 2 variantes = 4 tareas de 4 s a
  480p, 38.430 tokens estimados cada una (480×854×24×4/1024), US$0,411201 cada una a 10,70/M,
  **US$1,644804** en total; reservado con margen, US$1,81 ≤ US$2. Un tercer par (US$2,47)
  no cabía.
- **Horario y llave:** llave de la app (no hay `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY` en el
  `.env` local), huella `sha256:3c54154d`. La ventana de 23:00–05:00 (hora de Bogotá) es una
  regla del repositorio (m-24852161, `byteplus_eval_guard.py`), no del proveedor ni del precio;
  el script trae `--allow-daytime`, que pasa `allow_daytime` al guardia y queda registrado en el
  informe (`daytime_override`).

- **Corrida:** 2026-11-21, 02:08:33–02:12:47 UTC (21:08–21:12 en Bogotá), **4 min 14 s** para
  las 4 tareas, una a la vez. Fuera de la ventana de 23:00–05:00, con `--allow-daytime`, por
  decisión de Deivid con el visto bueno del fundador (2026-11-20, escrita en la sesión
  coordinadora); la lanzó esa sesión tras comprobar que Seedance tenía **0 tareas** en cola o
  corriendo.

| Caso | Variante | Tarea | Prompt de parte | Tokens cobrados | Costo |
|---|---|---|---|---|---|
| A, «Super smash» | Línea base | `cgt-20261121100843-gf972` | v3 | 38.830 | US$0,415481 |
| A, «Super smash» | v6 | `cgt-20261121100946-bog2f` | v6 | 38.830 | US$0,415481 |
| B, «Smash doble» | Línea base | `cgt-20261121101050-jdxjq` | v3 | 38.830 | US$0,415481 |
| B, «Smash doble» | v6 | `cgt-20261121101150-kp6py` | v6 | 38.830 | US$0,415481 |
| | **Total** | | | 155.320 | **US$1,661924** |

- **Costo:** cotizado US$1,644804, cobrado **US$1,661924** (+400 tokens, +1,04 %: 38.830 frente a
  38.430 de la fórmula). **US$0,415 por pieza** de 4 s a 480p, igual con y sin el cuadro
  preparado: la imagen de más no se cobra. Reservado con margen US$1,8096, por debajo del tope
  de US$2. Sin Claude.
- **Cómo se revisó:** tres cuadros por video (primero, del medio y último, 480×854) puestos al
  lado del cuadro de apertura enviado y de la foto del producto, mirados uno por uno. Además,
  la diferencia media por píxel (0–255, a 90×160) entre el primer cuadro de cada video y el
  cuadro de apertura preparado: cerca de 0, el video arranca en ese cuadro.

**Resultado por caso**

| Caso | Continuidad con el cuadro de apertura | Fidelidad al producto |
|---|---|---|
| A — v6 | **No.** Diferencia 52,0 (la línea base, que no lo recibe, da 44,9). Arranca en otra toma: pan con ajonjolí sobre una piedra oscura, queso chorreando, sin la lechuga ni la mesa clara del cuadro. | **Mezcla.** Toma el pan con ajonjolí del cuadro de apertura y la carne smash, el queso y la cebolla morada de la foto. La «Super smash» de la foto tiene pan liso y tres carnes; aquí el pan es otro y se ve una sola carne gruesa. Queso exagerado. |
| A — base | (no recibe cuadro) | **Buena.** Pan liso, carnes smash apiladas y cebolla morada como en la foto. Agrega pepinillos que la foto no muestra y exagera el queso hacia el final. |
| B — v6 | **Sí.** Diferencia 12,1: el primer cuadro es casi el de apertura y el video lo anima (la cámara gira y el queso se derrite). | **Mala.** Se queda con la hamburguesa del clip (pan con ajonjolí, lechuga, una carne). La «Smash doble» (pan liso, dos carnes, cheddar) no aparece. |
| B — base | (no recibe cuadro) | **Buena.** Pan liso, dos carnes, cheddar derretido como en la foto. Fondo oscuro con luz roja, de los colores de la marca. |

**Veredicto: v6 NO queda apto para encender `QUALIFY_PARTS_PREPARED_FRAME_REFS`.** En los dos
casos el cuadro de apertura y la foto del producto se contradicen, y Seedance resuelve el
choque de forma distinta cada vez: en A ignora el cuadro y mezcla los dos productos; en B
sigue el cuadro y pierde el producto del cliente. En ninguno se consiguen las dos cosas a la
vez, y en los dos la línea base es más fiel al producto. El interruptor sigue apagado.

**Limitaciones y qué falta:**

- **n = 2**, un solo negocio, un solo «video propio».
- **El «video propio» no muestra el producto:** es un clip de banco de imágenes que subió el
  negocio, de otra hamburguesa. El caso para el que se hizo EF-11 es el contrario: el dueño
  graba su propio producto, y el cuadro y las fotos coinciden. Esta corrida mide el peor caso
  (cuadro y foto contradictorios), no el caso normal. Para decidir sobre el caso normal hay
  que repetirla con un video propio de verdad que muestre el mismo producto de las fotos.
- Aun así, el riesgo existe en producción: nada impide que el tramo elegido muestre otra cosa
  que las fotos. Si se enciende algún día, conviene avisar al dueño o quitar las fotos cuando
  el tramo no muestre el producto.
- Borradores 480p de 4 s; no se midió el final 1080p.
- Corrida sin repetición: con la misma entrada Seedance puede dar otro resultado.
- El material real se descargó a `%TEMP%` y se borró al terminar, con todas las salidas. No
  quedó nada en el repositorio.

## Avatar como personaje en su escena, camino A: banco y corrida AVESC-001 (2026-11-26, m-25112921)

- **Qué mide.** Decisión de Deivid del 2026-11-26: el avatar del Clip es un **personaje** que
  actúa y habla dentro de la escena (toma el producto, lo muestra, lo come y dice su línea).
  Camino A: una sola tarea omni de Seedance 2.5 con tres imágenes de referencia (personaje
  dibujado por Seedream 5.0 pro, foto del producto, fondo) y la línea entre comillas
  (`dialogue`, que el adaptador agrega como `Dice a cámara: "…"`). El camino B (OmniHuman +
  Seed Speech) no se puede medir: no hay llaves.
- **Montaje.** `qualify_api/evals/avatar_scene_bench.py` (matriz, prompts `avatar-escena-v1`,
  costo, guardias, planilla) y `packages/api/evals/avatar_escena/run_experiment.py`
  (`just eval-avatar-escena plan | dibujar | escenas | planilla`). Usa los adaptadores reales
  (`SeedreamImageAdapter`, `SeedanceVideoAdapter`) y la tabla `v10`. Salidas y material en
  `%TEMP%/avatar-escena-seedance/`, nunca en el repositorio.
- **Matriz.** 2 personajes (realista y animado: 2.x suele rechazar caras que parecen reales;
  la doc admite salidas propias de Seedream de menos de 30 días sin modificar, por eso el
  dibujo viaja byte a byte) × 3 escenas (5, 8 y 10 s) sobre el fondo dibujado = 6 tareas;
  más la escena 1 sobre la foto real del local por personaje (2 tareas) **cuando exista esa
  foto**. Hoy no hay foto del local de nibbles: esa rama queda fuera.
- **Costo estimado (tabla `v10`, sin llamadas).** Dibujos: 2 opciones × (2 personajes + 1
  fondo) × US$0,045 = **US$0,27**. Escenas en borrador 480p 9:16: 5 s US$0,514, 8 s US$0,822,
  10 s US$1,028; 2 personajes = **US$4,73**. Total **US$5,00** (con 10 % de margen US$5,50).
  Con la foto del local, +US$1,03 (total US$6,03; con margen US$6,63). **Tope propuesto:
  US$8** (el código no acepta más de US$10).
- **Guardias.** `--dry-run` o `--i-have-spend-authorization` (uno de los dos, obligatorio);
  `--max-usd`, con la fase entera cotizada con margen antes de la primera llamada y cada
  llamada reservada antes de enviarse (`SpendLedger`), acumulado entre fases en `gasto.json`;
  escenas solo de 23:00 a 05:00 en Bogotá salvo `--allow-daytime`; una tarea a la vez; la
  prueba en seco corre con la red bloqueada (`network_guard`).
- **Métricas.** Automáticas por escena: acepta o rechaza la referencia (y el error),
  segundos reales y costo real (tokens × tabla). Juicio de Deivid y Herwin en
  `juicio-<juez>.csv`: personaje igual, producto reconocible, acción cumplida, voz en español
  bien, labios sincronizados, sin letras, creíble 1-3.
- **Activación de Seedance 2.5, verificada sin generar (2026-11-26).** Con la llave de API,
  ModelArk no tiene endpoint de saldo (el de facturación pide AK/SK, que no están en el
  `.env`). Se leyó la lista de tareas (`GET /contents/generations/tasks`: solo lectura, no
  crea ni cobra): 21 tareas de `dreamina-seedance-2-5-260628` en la ventana de la lista
  (19 `succeeded`, 2 `failed`), la última del 2026-11-21. El modelo está activado: la
  exigencia de más de US$30 de saldo era del 2026-10-07 y quedó atrás el 2026-10-23. El
  saldo actual no se pudo leer.
- **Resultados:** corrida `20261126-125745`, en la sección siguiente.

### Prueba AVESC-001 — camino A en vivo: 2 personajes × 3 escenas en borrador — 2026-11-26 (m-25112921)

- **Corrida:** `20261126-125745`, con el OK de Deivid escrito en la sesión. Material en
  `%TEMP%/avatar-escena-seedance/corridas/20261126-125745/` (`videos/`, `dibujos/`,
  `resultados.json`, `gasto.json`, `dibujos.json`, `juicio-deivid.csv`, `juicio-herwin.csv`).
  Producto: `%TEMP%/avatar-escena-seedance/material/producto-super-smash.jpg`, una foto del
  catálogo de nibbles (producto `fde5a706`, idéntica byte a byte a una de las fotos de la «smash
  doble») que se usó como super smash por decisión de Deivid; no se confirmó que muestre el
  producto real. La fidelidad al producto se mide contra esa foto. La revisión de cuadros y las transcripciones quedaron en
  `%TEMP%/avatar-escena-revision/` (con una hoja de contacto de los 6 videos). Nada de eso se
  copia al repositorio.
- **Modelos y ajustes:** dibujos con `dola-seedream-5-0-pro-260628` (1080×1920; se usó la opción 1
  del personaje realista, del animado y del fondo dibujado; las opciones 2 se pagaron y no se
  usaron). Escenas con `dreamina-seedance-2-5-260628`, borrador 480p (480×854, 24 cps), 9:16, con
  audio, prompt `avatar-escena-v1`, tabla de precios `v10`, una tarea a la vez.

**Costo y tiempo reales**

| Llamada | Segundos pedidos | Cotizado (US$) | Tokens cobrados | Cobrado (US$) | Tiempo (s) |
|---|---|---|---|---|---|
| 6 dibujos Seedream 5.0 pro | — | 0,27 | — | **0,27** (0,045 c/u) | 27,5 a 58,4 |
| realista e1 | 5 | 0,514 | 48.437 | **0,518** | 68,5 |
| realista e2 | 8 | 0,822 | 77.260 | **0,827** | 67,6 |
| realista e3 | 10 | 1,028 | 96.475 | **1,032** | 74,4 |
| animado e1 | 5 | 0,514 | 48.437 | **0,518** | 67,4 |
| animado e2 | 8 | 0,822 | 77.260 | **0,827** | 78,4 |
| animado e3 | 10 | 1,028 | 96.475 | **1,032** | 74,6 |
| **Total** | | 5,00 | | **5,02** (escenas 4,75) | |

- Cobrado = tokens × US$10,70/M (480p sin video de entrada). La cotización de `v10` se quedó
  corta en un 0,4 a 0,8 % por escena (≈ 9.650 a 9.690 tokens por segundo cobrados frente a
  ≈ 9.610 cotizados), como en SD25-001/002: dentro del margen del 10 % del libro de gasto. El tope
  de US$8 no se tocó. Una escena cuesta ≈ US$0,10 por segundo en borrador; el final a 1080p de
  esas mismas escenas costaría aparte ≈ US$0,57 por segundo (SD25-002), no medido aquí.
- Una escena tarda de 67 a 78 s, sin relación clara con su largo (la de 5 s tardó lo mismo que la
  de 8 s).

**Aceptación de las referencias.** Las 6 tareas terminaron bien con las tres imágenes (personaje,
producto, fondo); ninguna rechazó una referencia. **La cara realista dibujada por Seedream 5.0 pro
pasó** (el dibujo viajó byte a byte). Eso no prueba que pase una foto real de una persona: esa
rama no se midió.

**Audio.** Los 6 videos traen una pista AAC estéreo de 32 kHz que dura lo mismo que el video
(4,96 / 7,97 / 9,95 s). Transcripción local con faster-whisper en CPU, idioma `es`, con dos
modelos (`small` y `large-v3-turbo`); donde no coinciden se dice. La voz del personaje animado
sale más baja (RMS ≈ 0,045 frente a ≈ 0,08 del realista, unos 5 dB menos).

| Video | Línea esperada | Transcripción | Habla entre |
|---|---|---|---|
| realista e1 | ¡Mira esta super smash, recién hecha! | «¡Mira esta Super Smash recién hecha!» (los dos) | 2,0 y 4,7 s |
| realista e2 | Mmm, crujiente por fuera y jugosa por dentro. | «Mmm, crujiente por fuera y jugosa por dentro.» (`small`; turbo omite el «Mmm») | 4,6 y 7,8 s |
| realista e3 | Esta es la super smash de Nibbles. Ven hoy por la tuya. | «Esta es la Super **Splash** de **Nibles**. Ven hoy por la tuya.» (los dos) | 5,9 y 9,7 s |
| animado e1 | ¡Mira esta super smash, recién hecha! | «Mira esta Super Smash recién **hacha**.» (los dos) | 2,2 y 4,7 s |
| animado e2 | Mmm, crujiente por fuera y jugosa por dentro. | «Mmm, **cruyente** por fuera y jugosa por dentro.» (`small`; turbo «cruguiente») | 4,1 y 7,8 s |
| animado e3 | Esta es la super smash de Nibbles. Ven hoy por la tuya. | «Esta es la Super Smash de Nibbles. Ven hoy por la tuya.» (los dos) | 4,9 y 9,1 s |

Las seis dicen la frase completa, en español y dentro del video. Lo que va en negrita es donde los
dos modelos oyen lo mismo, distinto de la línea: puede ser pronunciación (la marca en inglés,
«hecha», la «j») o error de la transcripción. **Para juicio humano.**

**Juicio preliminar por cuadros** (6 cuadros por video más 9 recortes de la cara durante el habla;
sin oír). **Es preliminar: lo reemplaza la planilla de Deivid y Herwin** (la de Deivid, abajo).
Labios: en los seis la
boca cambia de forma mientras hay voz y está quieta o sonriendo antes; la sincronía fina, el acento
y la calidad de la voz quedan **para juicio humano**. La columna «Producto» compara con la foto
de catálogo usada como super smash, no con el producto real.

| Video | Personaje igual | Producto | Acción | Letras o logos | Defectos | Creíble (1-3) |
|---|---|---|---|---|---|---|
| realista e1 | sí (rizos, camiseta crema, delantal verde) | sí: dos carnes, queso, salsa de tomate, pepinillo, pan brillante | sí: la toma del mostrador y la acerca a cámara | ninguno inventado; el menú del fondo trae seudoletras borrosas que ya estaban en el dibujo del fondo | mancha de grasa en el mostrador donde estaba (verosímil) | 3 |
| realista e2 | sí | sí; mordida visible en el pan | sí: muerde, mastica con los ojos cerrados, baja un poco y habla | igual que e1 | la mordida solo marca el pan de arriba | 3 |
| realista e3 | sí | sí | sí: la muestra en una mano, señala con la otra e invita | igual que e1 | ninguno visto; habla recién desde el segundo 5,9 | 3 (voz pendiente: «Splash», «Nibles») |
| animado e1 | sí (gorra roja, coleta, delantal) | sí, pero **enorme**: tan ancha como su torso, ya sobre el mostrador | sí | igual que e1 | escala del producto | 2 |
| animado e2 | sí | sí; mordida visible | sí | igual que e1 | ninguno visto | 3 (voz pendiente: «cruyente») |
| animado e3 | sí | sí, salvo una grieta en el pan hacia el segundo 2 | sí: la sostiene en la palma y la señala | igual que e1 | grieta del pan; la hamburguesa se sostiene en una palma abierta | 3 |

**Juicio humano de Deivid (2026-11-26).** Labios bien en las escenas (Deivid): «los labios van
bien con las escenas». Dos defectos, en sus palabras:

- La saturación se exagera en el momento de masticar (e2).
- En el animado la mano no gira con la hamburguesa, solo gira la hamburguesa. No dijo en qué
  escena lo vio.

Lo demás (personaje igual, producto, acción, voz en español, letras, creíble) no lo juzgó: queda
vacío en `juicio-deivid.csv`. **El juicio de Herwin sigue pendiente.**

**Conclusión provisional (falta el juicio de Herwin).** El camino A sirve para un borrador: una
sola tarea de 5 a 10 s pone al personaje dentro del local, con el producto reconocible, cumpliendo
la acción (también comer) y diciendo la línea entera en español, con labios bien en las escenas
(Deivid), por ≈ US$0,10 el segundo y en poco más de un minuto. Las 6 se aceptan en lo
visual; 3 tienen una duda de pronunciación que solo se resuelve oyendo. Riesgos:

1. **La voz no se controla:** cada tarea inventa la suya. El mismo personaje puede sonar distinto
   de una parte a otra del Clip, y el dueño no puede elegirla ni clonarla (eso era el camino B,
   Seed Speech). Hay que oír e1, e2 y e3 seguidas.
2. **Pronunciación de nombres propios y palabras en inglés** («super smash», «Nibbles») y de algún
   fonema («hecha», «crujiente»): 3 de 6 con dudas según la transcripción.
3. **Escala y forma del producto** cambian (animado e1, grieta en animado e3): la fidelidad al
   producto necesita una revisión humana por escena.
4. **El momento de la línea no se controla:** en las de 10 s el personaje habla en la segunda
   mitad (desde 4,9 y 5,9 s); en las de 5 s la línea entra justa (termina a 4,7 s).
5. **Seudoletras del fondo:** vienen del dibujo del fondo; un fondo sin cartel las evita.
6. **Una muestra por casilla:** no se sabe cuánto varía si se repite.
7. **Sin probar:** una foto real de una persona (cara real), la foto real del local y el final a
   1080p (≈ US$0,57 por segundo más, según SD25-002).
8. **Datos del cliente:** la foto del producto viajó al id del modelo; antes de llevarlo a clientes
   hay que confirmar que esa vía no es una de las que ceden datos a BytePlus (regla del
   generador).
9. **Saturación al masticar** (Deivid): «la saturación se exagera en el momento de masticar» (e2).
10. **La mano y el producto** (Deivid): «en el animado la mano no gira con la hamburguesa, solo
    gira la hamburguesa».

## Prueba AVFOTO-001 — personaje dibujado por Seedream desde la foto de una persona real — 2026-11-26 (m-25129385, ADR 50 §12.12) · Seedance rechazó los 3 dibujos

- **Qué mide.** La opción de ADR 50 §12.12: el dueño sube la foto de una persona real que dio
  su permiso por escrito, Seedream 5.0 pro dibuja el personaje a partir de esa foto (imagen a
  imagen) y **solo ese dibujo** va a Seedance 2.5 como personaje. Tres preguntas: si Seedream
  acepta la foto, si Seedance acepta el dibujo (la clave: `docs/byteplus-datos-de-clientes.md`
  §1.4 nombra salidas de Seedream de **texto a imagen**) y cuánto se parece a la persona.
- **Montaje.** `qualify_api/evals/avatar_photo_bench.py` y
  `packages/api/evals/avatar_escena/personaje_foto.py` (`just eval-avatar-foto`), sobre las
  salvaguardas de AVESC-001. El material lista cada persona con `permiso_escrito: true`; sin
  él no se manda nada. Las fotos, los dibujos y la planilla están en
  `%TEMP%/avatar-foto-real/`, nunca en el repositorio.
- **Corrida:** `20261126-161128`, con el OK de Deivid escrito en la sesión coordinadora
  («OK US$3, ahora»), tope US$3. 3 personas (`p1`, `p2`, `p3`) con permiso escrito.
- **Modelos y ajustes:**
  - dibujos con `dola-seedream-5-0-pro-260628`, 1080×1920, la foto como única referencia,
    prompt `personaje-desde-foto-v1`, 2 opciones por foto;
  - escenas con `dreamina-seedance-2-5-260628`, la escena e1 de AVESC-001 (5 s, borrador 480p,
    9:16, con audio, prompt `avatar-escena-v1`), con la opción 1 de cada persona como
    «Image 1», la foto del producto y el fondo dibujado de AVESC-001;
  - tabla de precios `v10`.

**Resultado**

| Paso | Pedidos | Aceptados | Error | Costo (US$) | Tiempo |
|---|---|---|---|---|---|
| Seedream 5.0 pro, dibujo desde la foto | 6 (3 fotos × 2) | **6** | — | **0,27** (0,045 c/u) | 26 a 38 s |
| Seedance 2.5, escena con el dibujo | 3 | **0** | `HTTP 400 InputImageSensitiveContentDetected.PrivacyInformation: The request failed because the input image 'content[1]' may contain real person` | **0** (rechazo al crear la tarea, no se cobra) | ≈ 5 s |
| **Total** | | | | **0,27** | |

- `content[1]` es la primera imagen de referencia del cuerpo que arma `SeedanceVideoAdapter`
  (`content[0]` es el texto): **el dibujo del personaje**, no el producto ni el fondo.
- Request ids de los tres rechazos (no identifican a nadie):
  `02179572409229945c07e4ff35b1f55227084b3d76e9a8042e77d` (p1),
  `0217957240976109ded32e803badef81244c2c5f5c7f1be339226` (p2),
  `02179572410267116e812ea4822a09eb3d0e01cc9319ecd7bbb9e` (p3).
- Los dibujos viajaron byte a byte (sin recortar ni recomprimir), igual que en AVESC-001, y
  tenían minutos de hechos en la misma cuenta.

**Conclusión.** El camino «foto real → dibujo de Seedream (imagen a imagen) → Seedance» **no
funciona tal como se planteó**: Seedance no trata ese dibujo como «salida propia de
Seedream» y lo rechaza como persona real. En AVESC-001, un rostro igual de realista dibujado
por Seedream **desde texto** sí pasó. Que la diferencia sea el origen imagen a imagen (o el
parecido con una persona real de la foto) es **[inferencia]**: BytePlus no publica cómo lo
detecta.

**Qué lo reabriría** (nada de esto está medido):

1. **La verificación de identidad de BytePlus** para personas reales: la persona verifica su
   identidad con su propia cuenta y sube sus activos de retrato
   (`docs/byteplus-datos-de-clientes.md` §1.4, `upload-real-person-portrait-assets`). Cambia
   el flujo: la persona, no el dueño, tiene que hacer el trámite. Antes de construir hay que
   leer qué pide y si sirve para una cuenta como la nuestra (ver «Platform Customer», §1.5).
2. **Hipótesis: un dibujo estilizado o animado desde la foto** (por ejemplo, el estilo del
   personaje animado de AVESC-001, que pasó desde texto) podría no leerse como persona real.
   No está medido; cuanto menos se parezca, menos sirve la opción, así que la medición tendría
   que juzgar el parecido junto con la aceptación.

**Pendiente:** Deivid califica el parecido de los 6 dibujos (1 a 3) en
`%TEMP%/avatar-foto-real/corridas/20261126-161128/juicio-deivid.csv`; las columnas del video
quedan vacías. Observación sin juicio de parecido: en las 2 opciones de `p3`, Seedream
inventó letras rojas en el delantal pese a «No text» en el prompt; las otras 4 salieron sin
letras.

## Prueba AVFOTO-002 — personaje ANIMADO dibujado por Seedream desde la foto de una persona real — 2026-11-26 (m-25129385, ADR 50 §12.12) · Seedance aceptó los 3 dibujos

- **Qué mide.** La hipótesis que dejó AVFOTO-001: un personaje **3D animado** dibujado desde la
  misma foto real no se lee como persona real y Seedance lo acepta como «Image 1».
- **Corrida:** `20261126-162258`, con el OK de Deivid escrito en la sesión coordinadora («OK
  US$2, ahora»), tope US$2. Las mismas 3 personas con permiso escrito (`p1`, `p2`, `p3`) y el
  mismo `material.json` que AVFOTO-001. Material, videos y revisión solo en
  `%TEMP%/avatar-foto-real/` (corrida y `revision-20261126-162258/`); nada se copia al
  repositorio.
- **Modelos y ajustes:**
  - dibujos con `dola-seedream-5-0-pro-260628`, imagen a imagen, la foto como única
    referencia, 1080×1920, prompt `personaje-desde-foto-animado-v1`, **1 opción por foto**
    (`--estilo animado`);
  - escenas con `dreamina-seedance-2-5-260628`, la escena e1 de AVESC-001 (5 s, borrador 480p,
    9:16, con audio, prompt `avatar-escena-v1`), con el dibujo, la foto del producto y el fondo
    dibujado de AVESC-001;
  - tabla de precios `v10`, una tarea a la vez.

**Costo y tiempo reales**

| Llamada | Cotizado (US$) | Tokens cobrados | Cobrado (US$) | Tiempo (s) | Tarea |
|---|---|---|---|---|---|
| 3 dibujos Seedream 5.0 pro | 0,135 | — | **0,135** (0,045 c/u) | 33 a 34 | — |
| p1 e1 | 0,514 | 48.437 | **0,518** | 66,5 | `cgt-20261127042453-ct8kh` |
| p2 e1 | 0,514 | 48.437 | **0,518** | 61,4 | `cgt-20261127042559-278u7` |
| p3 e1 | 0,514 | 48.437 | **0,518** | 66,8 | `cgt-20261127042701-xbecn` |
| **Total** | 1,677 | | **1,690** | | |

La cotización quedó corta en un 0,8 % por escena, igual que en AVESC-001, dentro del margen del
10 %. El tope de US$2 no se tocó.

**Aceptación.** Las 3 tareas terminaron bien con las tres imágenes. **Ningún rechazo** del
filtro de persona real, cuando en AVFOTO-001 los 3 dibujos realistas de las mismas fotos se
rechazaron al crear la tarea.

**Video y audio.** Los 3 videos son 480×854 a 24 cps, 5,0 s (121 cuadros), con una pista AAC
estéreo de 32 kHz de 4,96 s. Transcripción local con faster-whisper en CPU, idioma `es`, con
`small` y `large-v3-turbo` (audio decodificado con PyAV):

| Video | Línea esperada | `small` | `large-v3-turbo` | Habla entre |
|---|---|---|---|---|
| p1 e1 | ¡Mira esta super smash, recién hecha! | «¡Mira esta Super Smash recién **hacha**!» | «Mira esta Super Smash recién **hacha**.» | 2,0 y 4,8 s |
| p2 e1 | ¡Mira esta super smash, recién hecha! | «¡Mira esta Super Smash recién **hacha**!» | «Mira esta Super Smash recién **hacha**.» | 1,9 y 4,6 s |
| p3 e1 | ¡Mira esta super smash, recién hecha! | «¡Mira esta Super Smash, recién **a techa**!» | «Mira esta Super Smash, recién **atecha**.» | 1,5 y 4,7 s |

Las tres dicen la frase completa en español. «hecha» se oye como «hacha» en los dos modelos, como
en el animado e1 de AVESC-001; puede ser pronunciación o error de la transcripción. **Para juicio
humano.** Volumen (RMS): p1 0,050, p2 0,083, p3 0,052.

**Juicio preliminar por cuadros** (6 cuadros por video y 9 recortes de la cara durante el habla,
sin oír). **Es preliminar: lo reemplaza la planilla de Deivid.** El parecido con la persona **no
se juzga aquí**: es de Deivid. Labios: en los tres la boca está cerrada o sonriendo antes de la
voz y cambia de forma mientras habla; la sincronía fina queda para juicio humano.

| Video | Personaje igual al dibujo | Producto | Acción | Letras o logos | Defectos | Creíble (1-3) |
|---|---|---|---|---|---|---|
| p1 e1 | sí (lentes, pelo, camiseta crema, delantal verde) | sí: dos carnes, queso, salsa de tomate, pepinillo, pan brillante | sí: la toma del mostrador con las dos manos y la acerca a cámara | ninguno inventado; el menú del fondo trae las seudoletras borrosas del dibujo del fondo | queda una gota de salsa en el mostrador (verosímil) | 3 |
| p2 e1 | sí (calvo, barba) | sí; el queso gotea al acercarla | sí | igual que p1 | ninguno visto | 3 |
| p3 e1 | sí (rizos) | sí | sí | **mancha roja en el delantal** (una forma, sin letras), que ya traía el dibujo de Seedream pese a «no letters, no logos» | la mancha del delantal | 2 |

En los tres, la hamburguesa llena el cuadro al final: es la cámara que se acerca, no un problema
de escala como el del animado e1 de AVESC-001.

**Conclusión.** **El personaje animado hecho desde la foto de una persona real, con su permiso,
sí pasa en Seedance 2.5** (3 de 3), mientras que el realista desde las mismas fotos no pasa
(AVFOTO-001, 0 de 3). Esto abre la opción de ADR 50 §12.12 **en su versión animada**: es un
hallazgo para una enmienda futura del §12, **pendiente del juicio de parecido de Deivid** (si no
se reconoce a la persona, la opción pierde su razón de ser). Siguen abiertos: muestra de 3 con
una sola escena de 5 s; no se midió la permanencia en escenas más largas ni en varias partes; el
dibujo intermedio debe tener menos de 30 días (R7); y lo que dice §12.12 sobre el permiso
escrito, el envío de la foto a BytePlus y la casilla de consentimiento sigue igual.

**Pendiente:** Deivid califica el parecido (1 a 3) del dibujo y del video en
`%TEMP%/avatar-foto-real/corridas/20261126-162258/juicio-deivid.csv`, más labios y voz en la
nota.
