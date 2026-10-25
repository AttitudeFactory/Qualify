# Escalar la generación de video: el límite de concurrencia de BytePlus

> Estado: análisis (2026-10-24), actualizado el 2026-10-25 con los arreglos fusionados (#325, #316) y
> la aprobación de ADR 41 (§2.2–2.4). Sin código ni llamadas de generación. Autor: data-scientist-fde.

## 0. Resumen

- **El límite es real y está documentado:** Seedance 2.5 admite **10 tareas a la vez y 600 por
  minuto por cuenta principal**, sumando todas las versiones. **Borradores y finales comparten las
  mismas 10.** Pasarse de 10 **no da error: la tarea espera en una cola de BytePlus** hasta 48 h.
  Pasarse de 600 por minuto o del fondo de esa cola da 429. Se sube **por ticket**. **Seedance 2.5
  no tiene modo flex ni de lotes con descuento** (solo 1.0 pro y 1.5 pro, que se retira el
  2026-11-11). Sí tiene `priority` 0–9 gratis para ordenar la cola.
- **Seedream** (500 imágenes por minuto) no es problema. **OmniHuman 1.5 admite 1 tarea a la vez**
  (dato del 2026-10-16, no se pudo releer hoy) y es tan crítico como Seedance.
- **Nuestro código no tiene cola, ni tope de hilos, ni reparto por negocio.** Hasta el 2026-10-24
  esperaba 8 min desde que creaba la tarea y, si la cola de BytePlus pasaba de ~6 min, **el video se
  cobraba y nunca aparecía**. **Ya arreglado** (#325, #316): la tarea se guarda con su id, la ventana
  cuenta desde `running`, una tarea en cola queda pendiente y se recupera por id. Huecos con ticket:
  m-24852492 (recuperar sin pantalla) y m-24852495 (OmniHuman). La cola propia es ADR 41, aprobado.
- **Medido hoy** (`arkcli gen list`, solo lectura): borrador de 5 s, **66–115 s** (n = 6); final
  1080p, **38 s** y US$2,87 (n = 1, el primer final medido en vivo).
- **Demanda** (24/48/96 tareas al mes por negocio Básico/Plus/Pro; picos como hipótesis): 10 a la
  vez **sobran para 10 y 50 negocios** en cualquier escenario. Con uso típico **alcanzan hasta
  ~500**. Desde ahí fallan los picos del lunes (19 % de tareas con más de 6 min de cola a 1 000
  negocios) y del fin de semana: a 1 000 negocios, **35–52 min de espera**. En el peor caso (todos
  agotan el cupo y BytePlus va el doble de lento) el límite llega a **~200 negocios**.
- **Recomendación:** (1) ya, los arreglos baratos de §4.0, para que una cola nunca cueste un video
  perdido; (2) medir la espera real; (3) ticket a BytePlus hacia los 100 negocios; (4) cola propia
  con reparto justo y **finales de piezas programadas hechos de noche** antes de los 200; (5)
  «Generar ya» con cobro extra **solo cuando haya fila**. Un «agendar más barato» no tiene ahorro de
  proveedor detrás: sería margen regalado.

## 1. El límite, verificado en fuentes oficiales

Fuentes leídas el 2026-10-24: copias en
`/private/tmp/claude-501/…/scratchpad/pricing/byteplus-docs/` (descargadas ese día) y, con
`arkcli docs get /docs/<página>` (solo lectura), `model-list`, `traffic-burst-handling-best-practices`,
`error-codes`, `batch-inference` y `online-inference-flex`. Más la consola «Model activation» de
nuestra cuenta (texto leído con Chrome, sin tocar nada).

### 1.1 Qué es exactamente el «10»

| Pregunta | Respuesta | Fuente (cita) |
|---|---|---|
| ¿Por modelo o por cuenta? | **Por modelo y por cuenta principal**, sumando todas las versiones del modelo y todas las subcuentas. | `seedance-2-5`, «Rate limits»: *«Under the same primary account, requests to the same model, regardless of model version, are subject to the following limits.»* `traffic-burst-handling`: *«Model rate limits: under the same primary account, limits are enforced per model (regardless of version).»* `model-pricing`: *«view the limits of each account and all its sub-accounts»* |
| ¿Cuánto? | Seedance 2.5: **10 tareas a la vez y 600 RPM** (cuenta de empresa). Una cuenta individual: 3 y 180. | `model-list`, «Video generation › Limits»: *«dreamina-seedance-2-5-260628 · Enterprise: 600 · Enterprise: 10 · Flex: Not supported · Individual: 180 · Individual: 3»*. Consola de nuestra cuenta: *«Dreamina-Seedance-2.5 · Activated · non-4K shared: 10 concurrent, 600 RPM»* |
| ¿Borradores y finales por igual? | **Sí, comparten las mismas 10.** El borrador es un parámetro (`draft: true`) del mismo modelo, no otro modelo, y el límite es «regardless of model version». Un final también es una tarea de `POST /contents/generations/tasks` del mismo modelo. | Lo anterior + `create-video-generation-task-api`, `draft`: *«Controls whether to enable draft mode»* (mismo endpoint, mismo `model`). Inferencia nuestra: ninguna página separa borrador y final en los límites |
| ¿Otros modelos de video? | Cada uno tiene **sus propias 10**: Seedance 2.0, 2.0 fast, 2.0 mini, 1.5 pro, 1.0 pro y 1.0 pro fast, 10 cada uno (2.0 en 4K: 1). Son cubetas separadas. | `model-list` (tabla de límites) y consola |
| ¿Qué pasa al pasarse de 10? | **No se rechaza: la tarea entra en cola** (`status: queued`) y espera turno en BytePlus. | `seedance-2-5` y `video-generation-tutorial`: *«Maximum concurrent tasks: … When this limit is reached, newly created tasks enter a queue for processing.»* |
| ¿Y al pasarse de 600 RPM? | La creación falla con **HTTP 429** (`ModelAccountRpmRateLimitExceeded`). | *«RPM … If this limit is exceeded, the task creation request fails due to rate limiting.»*; `error-codes`: *«429 · ModelAccountRpmRateLimitExceeded»* |
| ¿Tiene fondo la cola de BytePlus? | **Sí, pero el número no está publicado.** Pasado ese fondo, 429 `QuotaExceeded`. | `error-codes`: *«429 · QuotaExceeded · The request has exceeded the quota. … The number of tasks in the queued state for the current account has exceeded the limit.»* |
| ¿Cuánto espera una tarea en cola? | Hasta `execution_expires_after` (por defecto **48 h**, rango 1 h–72 h); después, `expired`. | `create-video-generation-task-api`: *«The default value is 172800 seconds, which is 48 hours. Value range: [3600, 259200]»* |
| ¿Se puede ordenar la cola? | **Sí: `priority` 0–9** en Seedance 2.5 y 2.0, dentro del mismo endpoint. No interrumpe lo que ya corre. | *«priority … Supported by Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series. … the request is inserted before all lower-priority requests under the same Endpoint.»* *«Priority affects only the queue order. It does not interrupt tasks that are already running»* |
| ¿Se puede subir? | **Sí, con un ticket**; no es un plan de pago publicado ni se ajusta desde la consola. | `traffic-burst-handling`: *«They are set by ModelArk and cannot be manually adjusted. … If you have traffic demands exceeding the default limits, submit a ticket to request a quota increase.»* `model-pricing`: *«To increase your limits, submit a request on the console.»* |
| ¿Hay modo flex / lote / sin conexión con descuento? | **Para Seedance 2.5 y 2.0, no.** `service_tier: flex` (50 % de precio, cuota diaria en lugar de concurrencia) existe solo para Seedance 1.5 pro, 1.0 pro y 1.0 pro fast. 1.5 pro se retira el **2026-11-11**. El «Batch inference» de texto no cubre video. | `create-video-generation-task-api`, `service_tier`: *«flex: Offline inference mode, with higher TPD quota …, priced at 50% of online inference … Dreamina Seedance 2.5 and Dreamina Seedance 2.0 series models are not currently supported.»* `video-generation-tutorial`: *«Offline inference · ✗ ✗ ✗ ✗ ✓ ✓ ✓»*. `model-list`: *«1.0 pro · 600 · 10 · TPD 500B»*, *«This model is retiring and will be retired on November 11, 2026»* (1.5 pro). `batch-inference`: *«This topic doesn't cover batch video generation.»* |

Una nota sobre otro código de error: `InflightBatchsizeExceeded` dice *«You have reached the maximum
concurrency limit for your current recharge amount. You can recharge to unlock a higher concurrency
quota»*. Sugiere que en algunos modelos la concurrencia sube con el saldo recargado. **Ninguna
página lo liga a Seedance** (para video, pasarse de 10 encola). Hay que preguntarlo en el ticket.

### 1.2 Imagen (Seedream) y presentador (OmniHuman)

| Modelo | Límite | Qué pasa al pasarse | Fuente |
|---|---|---|---|
| Seedream 5.0 lite / pro / flash, 4.5, 4.0 | **500 imágenes por minuto (IPM)** por modelo y cuenta | 429 `ModelAccountIpmRateLimitExceeded` (síncrono: se rechaza, no se encola) | `model-list`: *«dola-seedream-5-0-pro-260628 · 500 … seedream-5-0-260128 · 500 · Also supports seedream-5-0-lite-260128»*; consola: *«Dola-Seedream-5.0-lite · IPM 500»*; `error-codes`: *«429 · ModelAccountIpmRateLimitExceeded · IPM (Images Per Minute) limit of the model is exceeded.»* |
| OmniHuman 1.5 (Vision AI, otra consola) | **1 tarea a la vez** | Nuestro código lo trata como «concurrency» / `code 50429` → 429 | Leído de la documentación oficial el 2026-10-16 y anotado en `byteplus_omnihuman.py` (*«USD 0.12/s, concurrency 1»*) y en `docs/investigacion-avatar-omnihuman-vs-heygen.md` §1 (*«0,12 USD/s, concurrencia 1»*). **Hoy no se pudo releer:** las páginas de Vision AI se cargan con JavaScript y WebFetch las devuelve vacías. Hay que confirmarlo en la consola de Vision AI |

**Seedream no es un problema:** un negocio Pro hace a lo sumo unas pocas decenas de imágenes al mes, y
500 por minuto da para miles de negocios. **OmniHuman sí lo es.** Con una sola tarea a la vez y
~12 min de render por cada 30 s de video (RTF 23–27, mismo documento), dos dueños que pidan
presentador a la vez ya hacen cola de 12 min. Se satura a una escala parecida a la de Seedance
(§3.4), pero cada espera es más larga. Va en el mismo ticket (§4.3).

### 1.3 Duración real de una tarea (medida)

Con `arkcli gen list` (solo lectura: lista las tareas de los últimos 7 días, no genera nada) salen
las 15 tareas de la cuenta. Tiempo = `updated_at − created_at`; incluye la cola de BytePlus, que a
este volumen es cero.

| Tarea | Modelo | Tipo | Tokens | Tiempo |
|---|---|---|---:|---:|
| `cgt-20261023233147-a011i` | Seedance 2.5 | borrador 480p 5 s, sin video | 49 673 | 73 s |
| `cgt-20261024000242-qe2h5` | Seedance 2.5 | borrador 480p 5 s, sin video | 49 673 | 70 s |
| `cgt-20261024004006-2xl5m` | Seedance 2.5 | borrador 480p 5 s, sin video | 49 673 | 66 s |
| `cgt-20261024063856-4djtl` | Seedance 2.5 | borrador con 1 video de 7,33 s | 115 690 | 87 s |
| `cgt-20261024064403-nwzl2` | Seedance 2.5 | borrador con 1 video de 7,33 s | 118 851 | 115 s |
| `cgt-20261023231810-six2h` | Seedance 2.5 | borrador con 2 videos (22 s) | 259 802 | 96 s |
| `cgt-20261024004332-yguur` | Seedance 2.5 | **final 1080p** de `…2xl5m` | 245 388 | **38 s** |
| 7 tareas, 2026-10-20 a 22 | Seedance 1.0 pro | 720p 5 s | 247 962 | 100–380 s (mediana 120) |

- **Borrador de 5 s: 66–115 s, mediana ~80 s** (n = 6). **Final: 38 s** (n = 1).
- **Hallazgo aparte:** el final `…yguur` es el **primer final 1080p medido en vivo**. Cobró
  245 388 tokens: US$2,871 a 11,70/M, frente a 2,85 calculados en `docs/modelo-cobro-generacion.md`
  (+0,7 %: H2 confirmada, D26 de ese documento). Su borrador no tenía video de entrada, así que **no responde**
  si el final vuelve a cobrar el video de referencia. Registrado en la ficha
  `docs/modelos-generativos/seedance-2-5.md` (2026-10-25).
- **Hipótesis para la demanda:** un borrador de 10 s tarda el doble que uno de 5 s (~160 s). Un final
  de 10 s, ~80 s. Para planificar uso **120 s por borrador y 60 s por final** de media, y el doble
  (240 / 120 s) como escenario de BytePlus lento. Son 6 + 1 mediciones de un solo día, sin carga.

## 2. Cómo se comporta nuestro código en el límite

Este apartado se escribió el 2026-10-24 sobre el código de ese momento (§2.1). Dos arreglos ya
fusionados cambiaron las dos fallas graves (§2.2); los huecos que quedan tienen ticket (§2.3).

### 2.1 Antes de los arreglos (código del 2026-10-24, leído en `byteplus_ark.py`, `dispatch.py`, `service.py`, `draft_mode.py` y `media.py`)

1. **Lanzar la tarea.** `SeedanceVideoAdapter._create` → `_ArkClient._post` reintenta el POST hasta
   3 veces con espera lineal de 2 s y 4 s (`MAX_POST_ATTEMPTS = 3`, `POST_RETRY_STATUSES = {429, 503}`,
   `POST_RETRY_BACKOFF_SECONDS = 2.0`). Es la única espera ante un 429, y dura 6 s en total. Como
   pasarse de 10 **no da 429** (encola), este reintento solo actúa ante 600 RPM, el fondo de cola
   (`QuotaExceeded`) o una sobrecarga (`ServerOverloaded`). *Sigue igual.*
2. **Esperar el resultado.** `_wait` consultaba cada 5 s durante **480 s como máximo**
   (`DEFAULT_POLL_TIMEOUT_SECONDS = 480.0`), **contados desde que se creó la tarea, cola incluida**.
   Al pasarse lanzaba `ArkTaskTimeout` y **abandonaba** la tarea. BytePlus la seguía haciendo y **la
   cobraba**. *Arreglado en #325 (§2.2).*
3. **Nadie la recuperaba.** `SeedanceVideoAdapter.get_task` existía, pero ningún módulo de
   `qualify_api` lo llamaba. El video pagado se perdía. *Arreglado en #325.*
4. **Hilos sin tope.** `InlineDispatcher._start` lanza un `threading.Thread` daemon por cada
   generación o final. No hay pool, semáforo, cola propia ni reparto por negocio: 50 pedidos a la
   vez son 50 hilos y 50 tareas en BytePlus, 40 de ellas en la cola FIFO de BytePlus. Los hilos
   mueren con el proceso (despliegue). *Sigue igual: lo resuelve la cola de ADR 41.*
5. **Sin modelo de reserva.** `MediaProducer` llama al router con `chain=(link,)`: un solo eslabón.
   *Sigue igual (§4.5).*
6. **Lo que veía el dueño:** tras 8 min, «Está tardando más de lo normal. Revisa Borradores en un
   rato.», pero la pieza quedaba `FAILED` y el video no aparecía nunca, aunque BytePlus lo cobrara.
   En un final, `FINAL_STALE_SECONDS = 20 min` y un reintento que **pagaba otra vez**. El «reaper»
   (`reap_stale_drafts`) pasaba a `FAILED/timeout` los borradores en `DRAFTING` con más de 20 min
   **desde su creación** (OmniHuman: 40 + 10 min), y mataba un carrusel largo vivo.
7. **El presentador** (OmniHuman) espera hasta 40 min (`DEFAULT_POLL_TIMEOUT_SECONDS = 40 * 60`).
   Con una sola tarea a la vez, el segundo dueño en cola puede pasarse de esa ventana con su render
   ya pagado. *Sigue igual (m-24852495).*

**Consecuencia, con ese código:** toda tarea que esperara en la cola de BytePlus más de ~8 min menos
su propio render (≈ 6 min de cola para un borrador) **fallaba para el dueño y se cobraba igual**. El
límite real no era «10 a la vez» sino «10 a la vez con menos de ~6 min de cola». Ese es el umbral
que usa el modelo de demanda de §3, que por eso describe el **peor caso previo a los arreglos**.

### 2.2 Ya fusionado (2026-10-24)

| PR | Ticket | Qué cambia |
|---|---|---|
| #325 | [m-24852154](https://project.larksuite.com/5h2wsx/issue/detail/24852154) | Cada tarea de Seedance se guarda en `creative_vendor_tasks` (migración `0090`) en cuanto ModelArk la acepta, con el texto del que salió y antes de esperar nada. **La ventana de render cuenta desde la primera respuesta `running`**, no desde la creación. Una tarea `queued` se espera **hasta 1 h** en el hilo y después **queda pendiente, nunca fallida**: la pieza sigue en curso (sin reembolso). **La siguiente lectura de la pantalla la reclama por su id**, espera la tarea y rehace la pieza con el mismo texto; una tarea con id no se vuelve a enviar. `failed`/`expired` sí falla la pieza y reembolsa. **El reaper la salta hasta 49 h**, más allá de la caducidad de 48 h de BytePlus. Los finales guardan su tarea por recurso: un final reintentado retoma la misma tarea y no paga dos veces. La pantalla de espera dice que el video está en fila y llegará a «Por aprobar» |
| #316 | [m-24852156](https://project.larksuite.com/5h2wsx/issue/detail/24852156) | **El reaper mide 20 min desde el último avance** (`content_drafts.updated_at`), no desde la creación del borrador. Cada archivo que guarda una generación sella `updated_at` (en la sesión del negocio dueño), y entrar en `DRAFTING` también. Un carrusel de 10 diapositivas animadas ya no se da por muerto mientras avanza; un hilo muerto deja de sellar y se recoge 20 min después de su último avance. Sin migración |

**Efecto en el umbral:** con #325, esperar en la cola de BytePlus ya no hace perder el video. El
umbral de falla pasa de «~6 min de cola» a la caducidad de la tarea en BytePlus
(`execution_expires_after`, 48 h por defecto). Lo que queda es **espera**, no pérdida: a escala
(§3.4) la cola sigue creciendo en los picos, solo que el dueño recibe su video tarde en lugar de no
recibirlo.

### 2.3 Huecos que quedan, con ticket

| Ticket | Hueco |
|---|---|
| [m-24852492](https://project.larksuite.com/5h2wsx/issue/detail/24852492) | **Recuperación sin pantalla.** La tarea pendiente se reclama en la siguiente lectura de la pantalla; si el dueño no vuelve a abrirla, nadie la recoge. Falta un paso de worker que la reclame solo |
| [m-24852495](https://project.larksuite.com/5h2wsx/issue/detail/24852495) | **OmniHuman** no tiene todavía el mismo arreglo: con 1 tarea a la vez y 40 min de ventana, el presentador en fila puede pasarse con su render pagado |

### 2.4 Decisiones tomadas sobre este análisis

- **ADR 41 está APROBADO** (#318, firmado por el fundador el 2026-10-24):
  `docs/adr-41-cola-generacion-concurrencia.md`. Cola `creative_jobs` en el único Postgres,
  `creative-worker`, carriles inmediato y nocturno.
- **Finales nocturnos con confirmación** (ADR 41 §1.4 y §3): el final de toda vista previa aprobada se hace
  la primera noche después de aprobar, y **todo final espera la confirmación del dueño** antes de
  publicarse (estado `final_ready`). Responde a la decisión abierta 2 de
  `docs/epica-escalar-generacion.md` (m-24852169).
- **Ticket a BytePlus hacia los 100 negocios** (ADR 41 §1.4, m-24852172), como recomienda §4.3.

## 3. Modelo de demanda

Simulación de colas reproducible:
`/private/tmp/claude-501/-Users-herwin-Desktop-Qualify/c255668b-5f9b-4506-b5ad-cd3f8cc2ee30/scratchpad/concurrency_sim.py`
(`python3 -I concurrency_sim.py 10`; Python puro, sin llamadas a proveedores). 10 servidores FIFO,
igual que la cola de BytePlus. 30 réplicas de un pico de 3 horas, midiendo la hora central.

### 3.1 Supuestos

| Supuesto | Valor | Tipo |
|---|---|---|
| Tareas de Seedance por negocio y mes, con el cupo entero | Básico 20 vistas previas + 4 finales = **24**; Plus 40 + 8 = **48**; Pro 80 + 16 = **96** | decidido (planes 2026-10-24; D5–D7 de `modelo-cobro-generacion.md`) |
| Mezcla de planes | 60 % Básico, 30 % Plus, 10 % Pro → **38,4 tareas/negocio/mes** con el cupo entero | hipótesis |
| Uso del cupo | 50 % (típico) y 100 % (todos lo agotan) | hipótesis |
| Duración por tarea | borrador 120 s, final 60 s, media 110 s (el 83 % son borradores). Escenario «BytePlus lento»: el doble | medido a 5 s (§1.3); 10 s y lento, hipótesis |
| Reparto en el tiempo | 22 días hábiles. El 70 % en 8 horas de trabajo (10–13 h y 15–19 h, horas del comercio) | hipótesis |
| Factor de pico sobre la hora media | día normal ×3 (almuerzo); lunes por la mañana ×4; jueves y viernes, todos preparando el fin de semana ×6 | hipótesis |
| Ráfagas | cada sesión lanza 1 tarea (50 %), 3 (30 %) o 5 (20 %) a la vez: un juego de ángulos, varias piezas | hipótesis |
| Umbral de falla | una tarea que espera más de **6 min** en cola se pasa de la ventana de 8 min del adaptador: falla para el dueño y se cobra igual (§2) | del código |

### 3.2 Resultados: uso del cupo al 50 %, BytePlus normal

| Negocios | Pico | Tareas en la hora pico | Carga media (tareas corriendo) | Máximo en sistema (corriendo + en cola) | Espera p50 / p95 | Tareas que esperan > 6 min |
|---:|---|---:|---:|---:|---|---:|
| 10 | fin de semana ×6 | 5 | 0,1 | 8 | 0 / 0 s | 0 % |
| 50 | fin de semana ×6 | 23 | 0,7 | 13 | 0 / 0 s | 0 % |
| 200 | fin de semana ×6 | 92 | 2,8 | 21 | 0 / 3 s | 0 % |
| 500 | día normal ×3 | 115 | 3,5 | 23 | 0 / 35 s | 0 % |
| 500 | fin de semana ×6 | 229 | 7,0 | 65 | 0 / 139 s | 0 % |
| 1 000 | día normal ×3 | 229 | 7,0 | 65 | 0 / 139 s | 0 % |
| 1 000 | lunes ×4 | 306 | 9,3 | 97 | 153 / 624 s | **19 %** |
| 1 000 | fin de semana ×6 | 458 | 14,0 | 508 | 35 / 52 min | **100 %** |

### 3.3 Resultados: escenarios duros

| Escenario | Primer tamaño con fallas | Detalle |
|---|---|---|
| Cupo al 100 %, BytePlus normal | **~500 negocios** el lunes (19 % > 6 min) y el fin de semana (100 %) | 200 negocios el fin de semana: p95 77 s, 0 % de fallas |
| Cupo al 50 %, BytePlus lento ×2 | **~500** en un día normal (2,6 %); el lunes, 36 % | 200 negocios el fin de semana: p95 152 s, 0,2 % |
| Cupo al 100 % y BytePlus lento ×2 (el peor caso) | **~200**: lunes 7 %, fin de semana **86 %** (espera p50 16 min) | 50 negocios: p95 51 s, 0 % |

### 3.4 Lectura

- **Para 10 y 50 negocios, 10 tareas a la vez sobran** en todos los escenarios, incluido el peor (0 %
  de fallas; espera p95 ≤ 51 s). Ahí lo único que llena las 10 es una ráfaga de un mismo dueño: un
  juego de ángulos con 5 videos ocupa la mitad de la cuota él solo.
- **A ~200 negocios empieza a doler,** pero solo en el peor caso (todos agotan el cupo y BytePlus va
  lento): el viernes, 86 % de fallas. En el caso típico va bien.
- **A ~500 negocios las 10 ya no alcanzan** en los picos de lunes y fin de semana, aun con uso
  típico. **A 1 000, el pico del fin de semana se vuelve una cola de 35–52 minutos** (14 de carga
  media sobre 10 de capacidad: la cola crece sin parar mientras dure el pico).
- **Regla práctica:** hacen falta unas **14 tareas a la vez por cada 1 000 negocios con uso
  típico** en el pico del fin de semana, y unas 28 si todos agotan el cupo. Para que la espera p95 no
  pase de ~2 min, la carga media en el pico no debe superar ~70 % de la capacidad.
- **Cuello de botella de la ventana de 8 min:** con el código del 2026-10-24, la falla llegaba antes
  de que se notara la cola: toda tarea con más de ~6 min en cola se perdía y se cobraba (§2.1). **#325
  lo arregló** (§2.2): el umbral pasa de «6 min de cola» a «48 h» (`execution_expires_after`), y las
  columnas «> 6 min» de §3.2–3.3 se leen ahora como **espera**, no como videos perdidos.
- **OmniHuman** (1 a la vez, ~12 min por presentador de 30 s). Hipótesis: la mitad de los negocios
  hace 1 presentador al mes. El único carril se satura (carga media 1) en el pico del fin de semana
  a **~420 negocios**, y en el pico normal a ~840. Desde ~200 negocios, la espera media en el pico del
  viernes ya es de ~5 min. Por su ventana de 40 min, el cuarto en la fila falla.
- **Riesgo aparte:** las diapositivas de un carrusel se animan **una tras otra** en el mismo hilo
  (`media.py`, `for position, slide in enumerate(...)`). Un carrusel de 10 diapositivas animadas son
  ~10 × 2 min = 20 min de Seedance, justo el umbral del reaper (`DEFAULT_REAP_AFTER_MINUTES = 20`).
  Con cola, el reaper lo daba por muerto aunque siguiera vivo. **Arreglado en #316:** el reaper
  mide desde el último avance (§2.2).

## 4. Opciones con costo

Precios de la tabla `v7` y de la consola (2026-10-24). Una «creación» vale para el equipo como
máximo USD 0,15 (30 creaciones = USD 4,50, D3). Esfuerzo: XS < 1 día, S 1–3 días, M 1–2 semanas,
L > 2 semanas.

### 4.0 Arreglos previos, sin los que ninguna opción funciona

Son baratos y no dependen de la escala. Arreglan lo de §2.1. **Estado 2026-10-25:** el primero, el
segundo (ventana desde `running`; `execution_expires_after` por caso queda para ADR 41) y el cuarto
están fusionados (#325, #316, §2.2); `callback_url` sigue pendiente.

| Arreglo | Costo | Esfuerzo | Efecto |
|---|---|---|---|
| Recuperar la tarea por su id tras `ArkTaskTimeout`: guardar `task_id`, que un paso del worker consulte `get_task` y asiente el video cuando llegue | USD 0 | S | Lo pagado nunca se pierde; «Revisa Borradores en un rato» pasa a ser verdad |
| Separar la ventana de cola de la de render: contar los 8 min desde `running`, no desde la creación; fijar `execution_expires_after` según el caso (1 h para «ya», hasta 24 h para «agendado») | USD 0 | XS | El umbral de falla pasa de ~6 min de cola a lo que decidamos |
| Usar `callback_url` en lugar de 96 consultas por tarea (límite: 20 QPS de consulta por cuenta) | USD 0 | S | Con 50 tareas en cola, consultar cada 5 s ya son 10 QPS: la mitad del límite |
| Que el reaper no mate un carrusel largo vivo (latido por diapositiva) | USD 0 | XS | Quita el riesgo de §3.4 |

### 4.1 Cola propia con reparto justo por negocio

Una tabla `generation_jobs` en Postgres (con RLS) y un worker CLI más (`creative-worker`, como
`calendar-worker`). El worker no lanza más de **10 tareas** a BytePlus en total ni más de **2 por
negocio**, y reparte por turnos entre negocios. Así un dueño con un juego de 5 ángulos no deja a
los demás detrás. Es el «CeleryDispatcher» que `dispatch.py` ya prevé, sin Celery: no hace falta
otro runtime (ADR 31, «sin Celery»).

| Costo | Latencia para el dueño | Esfuerzo | Riesgo |
|---|---|---|---|
| USD 0 de proveedor; el worker vive en el VPS actual | Igual que hoy sin saturación. Saturado, la espera se reparte por igual y se puede mostrar («Tu video está en fila: unos 4 minutos») | M | Bajo. Patrón ya usado en el repo (outbox + worker idempotente). **No crea capacidad**: a 1 000 negocios el viernes sigue habiendo 35–52 min de espera, solo que repartida y visible, en lugar de fallas cobradas |

### 4.2 «Agendar» frente a «Generar ya»

- **Hechos que cambian la idea:**
  - **Seedance 2.5 no tiene modo flex ni de lotes:** no hay descuento por esperar (§1.1). Un video
    agendado le cuesta al equipo lo mismo que uno inmediato.
  - Lo que sí existe gratis es **`priority` 0–9**. «Generar ya» puede pasar delante en la cola de
    BytePlus sin pagar nada más al proveedor.
  - **De noche hay capacidad sobrada:** 10 a la vez × 8 h ÷ 110 s ≈ **2 600 tareas por noche**, todas las tareas de un mes de ~100 negocios Básico (24 cada uno) en una sola noche.
- **El «agendar» natural ya existe:** la mayoría de los videos aprobados se programan en el
  Planificador para otro día. El **final** (el 83 % del costo y la tarea que el dueño no necesita
  ver al momento) puede hacerse «antes de la hora de publicación», en horas valle, sin preguntarle
  nada. La vista previa sí la quiere ver ya (es el paso de decidir), así que va siempre inmediata.

| Variante | Costo para el equipo | Latencia para el dueño | Esfuerzo | Riesgo |
|---|---|---|---|---|
| A. **Final diferido automático**: el final de una pieza programada se hace en horas valle, con plazo = hora de publicación − 1 h; sin opción visible | USD 0 | Ninguna visible (el video está antes de publicarse) | S, sobre 4.1 | Bajo: si el final falla de noche, queda tiempo de reintentar antes de publicar. Saca del pico la parte de los finales |
| B. **«Agendar» explícito** (sin costo extra) frente a **«Generar ya»** (prioridad 9, por ejemplo +1 creación ≈ USD 0,15 de cupo) | USD 0 de proveedor. Si «agendar» fuera *más barato* para el dueño, ese descuento sale de nuestro margen: no hay ahorro de BytePlus que trasladar | «Ya»: la de hoy. «Agendar»: hasta la mañana siguiente | M (UI + reglas de cupo + copy) | Medio: una decisión más en cada pieza (contra `qualify-ux`, «un paso, una decisión»). Cobrar por la prioridad solo tiene sentido **cuando hay cola**; sin cola, el dueño paga por nada y lo nota |
| C. **«Generar ya» solo cuando hay fila**: la opción aparece únicamente si la espera estimada pasa de ~3 min («Hay fila: tu video estará en ~12 min. ¿Lo quieres ya por 1 creación?») | Igual que B | Igual que B | M | Bajo: solo se ofrece cuando aporta. Necesita la estimación de espera de 4.1 |

### 4.3 Pedir más concurrencia a BytePlus

| Costo | Latencia para el dueño | Esfuerzo | Riesgo |
|---|---|---|---|
| Desconocido: la documentación solo dice «submit a ticket». Puede ser gratis, pedir un compromiso de gasto o ligarse al saldo recargado (`InflightBatchsizeExceeded` lo sugiere para otros modelos) | Elimina la espera mientras dure el cupo concedido | XS (un ticket con números: este documento) | Plazo de respuesta desconocido y puede ser un no. **Pedirlo antes de necesitarlo**: hacia los ~100 negocios, para tener margen a ~300–500. Pedir a la vez Seedance 2.5 (p. ej. 30) y OmniHuman (p. ej. 3–5) |

### 4.4 Varias cuentas o regiones

| Costo | Latencia para el dueño | Esfuerzo | Riesgo |
|---|---|---|---|
| USD 0 por cuenta. Cada cuenta principal de empresa suma 10; una individual, solo 3 | Como 4.3, ×N cuentas | M: llaves por cuenta en `credential_session`, enrutar y **fijar cada borrador a su cuenta** (el final usa `draft_task_id`, que solo existe en la cuenta que hizo el borrador) | **Alto.** Las **regiones no sirven**: el límite es por cuenta principal y Seedance 2.5 se publica en `ap-southeast-1`. Según `model-list`, solo `seed-2-0` y `seedream-5-0-lite` están también en `eu-west-1`. Varias cuentas para esquivar un límite puede violar los términos; cada cuenta necesita su verificación de empresa, su facturación y su revisión de datos (endpoints personalizados, no los preajustes que ceden datos). Último recurso, y solo con el visto bueno escrito de BytePlus |

### 4.5 Otro modelo cuando hay saturación

Cada modelo de video tiene sus propias 10 (§1.1). Seedance 2.0 fast y 2.0 mini aceptan referencias,
pero **no tienen modo borrador**: no sirven para la vista previa ni para el final de un borrador de
2.5. El único uso posible es generar **directamente** un video final cuando 2.5 está lleno.

| Modelo de reserva | Costo de un video de 5 s, 720p, sin video de entrada (calculado: 21 600 tokens/s en 9:16) | Latencia | Esfuerzo | Riesgo |
|---|---|---|---|---|
| Seedance 2.0 fast (USD 5,60/M) | ≈ USD 0,60 (frente a 3,44 de vista previa + final en 2.5) | Sin espera mientras 2.0 fast tenga hueco | M (activar el modelo, enrutar con dos eslabones en `chain`, cambiar el flujo de la pieza: sin vista previa) | **Alto en producto:** el dueño recibe otro flujo (sin vista previa) y otra calidad, a 720p. **Sin medir:** el mandato exige un set de referencia y una comparación antes de usarlo. Además 2.0 fast **no está activado** en la cuenta |
| Seedance 2.0 mini (USD 3,50/M) | ≈ USD 0,38 | Igual | Igual | Igual, y peor calidad esperable |
| Seedance 1.0 pro con `flex` (USD 1,25/M fuera de línea) | ≈ USD 0,31 (247 962 tokens) | Horas (sin garantía) | M | Sin referencias de video ni audio, sin borrador. Calidad medida peor (motivo del paso a 2.5) |

Conclusión: el modelo de reserva es la opción **más cara en producto** y la única que exige una
medición previa. Queda para cuando 4.1 + 4.2A + 4.3 no alcancen.

## 5. Recomendación y épica propuesta

Orden por costo/beneficio. Cada escalón se activa por una señal medida, no por fecha:

| # | Historia | Cuándo | Esfuerzo | Señal que la dispara |
|---|---|---|---|---|
| 1 | **Arreglos de §4.0**: recuperar por id, ventana desde `running`, `execution_expires_after`, reaper del carrusel | **Hecho** (#325, #316; quedan m-24852492 y m-24852495) | S | — |
| 2 | **Medir**: guardar por tarea `queued_at` / `running_at` / `finished_at` (de `get_task` o del callback) y un tablero de «tareas a la vez» y «espera en cola» | Ya | S | — |
| 3 | **Ticket a BytePlus**: Seedance 2.5 a 30 a la vez y OmniHuman a 3–5; preguntar si sube con el saldo y si habrá `flex` para 2.5 | Hacia 100 negocios | XS | p95 de tareas a la vez ≥ 5 en la semana |
| 4 | **Cola propia con reparto justo** (4.1) y la espera estimada a la vista | Antes de 200 negocios | M | Alguna espera en cola > 60 s, o p95 a la vez ≥ 7 |
| 5 | **Final diferido automático** para piezas programadas (4.2 A) | Junto con 4 | S | — |
| 6 | **«Generar ya» solo cuando hay fila** (4.2 C), con prioridad 9 por +1 creación | Cuando haya cola real | M | Espera p95 en el pico > 3 min durante 2 semanas |
| 7 | Modelo de reserva o varias cuentas (4.5 / 4.4) | Solo si 3 + 4 + 5 no alcanzan | M–L | Concurrencia concedida agotada, con fallas |

**Sobre la idea del fundador:** «agendar» tiene sentido, pero **no como descuento**: BytePlus no
cobra menos por esperar en Seedance 2.5, así que un «agendado más barato» es margen regalado. La
forma que más rinde es la invisible: los **finales** de piezas programadas se hacen de noche (son la
mayor parte del costo y nadie los espera en pantalla). «Generar ya» con cobro extra se ofrece solo
cuando hay fila de verdad. Si no, el dueño paga por una prioridad que no le cambia nada.

**Lo que este análisis no sabe** (y la historia 2 mide):

- La distribución real de picos por hora y día: hoy hay 7 tareas de 2.5 en total.
- La duración de borradores y finales de 10 s, y cómo cambia con la carga de BytePlus.
- El fondo de la cola de BytePlus (el número que dispara `QuotaExceeded`).
- La concurrencia de OmniHuman, que hoy no se pudo releer en la fuente.
