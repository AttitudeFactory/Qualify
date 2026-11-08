# ADR 42 — «Ideas para tus reels»: reels públicos compartidos, puerta medida y corrida semanal

**Estado:** `[APROBADO — decisiones de Herwin Rey (fundador), 2026-10-24 y 2026-10-25]` · propuesto por principal-architect.
**Enmienda:** [del 2026-11-04 — R7 y R8](#enmienda-del-2026-11-04--r7-y-r8), al final del documento.
**Ticket:** m-24854769 · **Épica:** la crea el product-owner desde el [anexo](#anexo--rebanadas-para-la-épica).
**Evidencia:** lectura del código de `main` del 2026-10-24 (§1.2, con líneas) y el análisis de experiencia de ux-designer del mismo día (abrir nunca busca, corrida semanal, cupo en tiempo).
**Numeración:** el análisis hablaba de «ADR 40», pero el 40 (SonarQube y Langfuse) y el 41 (cola de generación) ya estaban firmados en `main`. Esta decisión es la **42**.
**Nombre en pantalla:** la función se llama **«Ideas para tus reels»** y los referentes se muestran como **«cuentas que te inspiran»**. En el código y en este documento se sigue diciendo *referentes* y *Descubrir reels* hasta que el cambio de nombre llegue a la interfaz.

## 1. Contexto

### 1.1 El problema

«Descubrir reels» (`docs/descubrir-reels-scrapecreators.md`) gasta créditos de ScrapeCreators **y** llamadas a Claude sin control. La flota gasta unos **USD 50 al mes** con uso realista: unas 13.000 lecturas pagadas más un gasto parecido en Claude. A ese ritmo, el saldo de 3.681 créditos del 2026-10-15 dura **8 o 9 días**. Abrir la pantalla dispara una lectura que el dueño no pidió, y lo que se pagó se pierde en el siguiente despliegue.

*→ Enmienda del 2026-11-04, punto 6: la medición de R17 no sostiene los USD 50 al mes.*

### 1.2 Lo que hace hoy el código (verificado el 2026-10-24)

| # | Hecho | Dónde |
|---|---|---|
| H1 | La vista lee **al montarse**: entrar a la opción ya gasta si no hay memoria | `Qualify/discover_reels.py:1006` |
| H2 | La memoria vive **solo en el proceso**: lectura por marca (6 h), veredictos de Claude (`_verdicts`) y transcripciones (`_transcripts`) | `Qualify/reels_discovery.py:100, 562, 918-981` |
| H3 | Hay un solo proceso de backend (`GRANIAN_WORKERS: "1"`) y **cada merge despliega**. Del 20 al 24 de octubre hubo de 15 a 54 merges por día, así que la memoria dura **15–90 min** en horario de trabajo, no 6 h | `deploy/docker-compose.prod.yml:221`, `git log --first-parent` |
| H4 | La lectura del mes cubre hasta 12 cuentas × 4 páginas × 1 crédito. La de 90 días, hasta 12 páginas por cuenta. **Antes del filtro se pagan además hasta 40 transcripciones de Instagram** (1 crédito cada una) | `reels_discovery.py:83, 289-292, 402, 857-860`, `scrapecreators_client.py:535` |
| H5 | **Fuga: se paga y no se muestra nada.** El scrape se hace antes de comprobar el brief y la clave de Anthropic. Sin brief no se muestra nada, pero los créditos ya se gastaron | `reels_discovery.py:839-879` |
| H6 | **Fuga: cada reintento paga otra vez.** Si la revisión de Claude falla, el resultado no se guarda, y cada apertura o «Intentar de nuevo» paga otra vez la lectura entera | `reels_discovery.py:973-980` |
| H7 | **No hay guardián de saldo.** El proveedor manda `credits_remaining` y `credits_charged` en cada respuesta y nadie los lee. Un 402 (sin saldo) se trata como «cuenta ilegible» | `scrapecreators_client.py:107-135`, `reels_discovery.py:307-313` |
| H8 | **Fuga en los avatares.** Cuando caduca la URL firmada, el último recurso es `fetch_profile` (1 crédito) **sin pasar por `vendor_payloads`**, con un tope de 60/h. Eso da hasta 1.440 créditos al día en el peor caso. Las imágenes viven en el volumen Docker `avatars`, sin copia | `Qualify/avatar_proxy.py:249-290`, `docker-compose.prod.yml:225` |
| H9 | Ya hay un **precedente firmado de caché compartida entre tenants**: `vendor_payloads`, `creators` y `creator_sightings` (0036), sin `tenant_id` ni RLS porque guardan dato público (la misma regla que 0023). La búsqueda de referentes los usa; Descubrir reels no | `migrations/postgres/versions/0036_creator_pool.py` |
| H10 | El cliente del proveedor y el pipeline viven en la capa Reflex (`Qualify/`), así que un worker de `qualify_api` no puede usarlos. Las listas de reels no guardan el payload crudo y los veredictos no guardan con qué modelo ni con qué prompt se hicieron | `Qualify/scrapecreators_client.py`, `Qualify/reels_discovery.py` |

### 1.3 Lo que cuesta hoy

Los precios salen de `docs/costos-comparativos-herramientas-ia.md:61`. En el plan Freelance, un crédito cuesta **USD 0,00188**. Claude cuesta **≈ USD 0,001 por reel revisado**, medido en `packages/api/evals/reels_ai/README.md`.

| Caso | Créditos | USD |
|---|---|---|
| Apertura en frío repetida, típica (después de un deploy) | ~28 | ≈ 0,05 en créditos + 0,06 en Claude = **0,11** |
| Primera apertura de una marca | 65–88 | ≈ 0,20 |
| Lectura de 90 días | 60 típico, 184 como máximo | 0,11–0,35 |
| Una marca al mes, con 3 aperturas al día | ~1.660 | **≈ 6,5** |

*→ Enmienda del 2026-11-04, punto 6: el costo por apertura se confirma (USD 0,09–0,10); las 3 aperturas al día, no.*

**Claude cuesta lo mismo que el proveedor en cada apertura en frío.** Por eso este ADR guarda también los veredictos, no solo los reels.

## 2. Decisión

1. **Abrir la pantalla nunca gasta.** «Ideas para tus reels» lee de Postgres. Las lecturas pagadas solo pasan de tres maneras:
   - **(a) la corrida semanal** de cada marca activa, el **lunes a las 06:00 en la hora local del negocio** (`tenants.timezone`). Deja entre **6 y 8 ideas**;
   - **(b) «Buscar reels nuevos»**, como máximo **1 vez al día por marca**;
   - **(c) la lectura de 90 días**, que hace **solo el operador de Qualify** (rol admin).
   - *→ Enmienda del 2026-11-04, punto 1: única excepción, la primera apertura de una marca que nunca tuvo corrida adelanta su corrida semanal (la paga el worker, no la pantalla).*
2. **Los reels públicos se guardan una vez para todos los tenants.** Van en tablas globales sin `tenant_id` y sin RLS, con el mismo patrón que 0036 (§3.1). Ninguna fila global dice qué tenant o qué marca pidió, siguió o miró una cuenta.
3. **Lo que es de cada negocio va en tablas con RLS** (§3.2): veredictos de Claude, corridas, ideas con marca de visto/nuevo, y consumo.
4. **Cada llamada de pago a ScrapeCreators pasa por una sola puerta medida en `packages/api`** (§4). La puerta aplica:
   - un interruptor por variable de entorno;
   - un **piso global de 500 créditos**: por debajo no se llama al proveedor;
   - la parada global ante un 402;
   - una **alerta a Lark por debajo de 2.000 créditos**;
   - el **tope de cada negocio: 150 créditos al día y 600 al mes**.

   El consumo se carga **al tenant que disparó la lectura**. Leer algo que ya está guardado no cuesta nada. Un test estático prohíbe llamar al proveedor fuera de esa puerta.
5. **Frescura:**
   - la página 1 de una cuenta se vuelve a leer si tiene más de **24 h**;
   - el recorrido completo de 30 días, que refresca las vistas de los reels viejos, si tiene más de **72 h**;
   - una transcripción no se vuelve a pagar nunca;
   - un veredicto se repite solo si cambia el brief o lo que el modelo leería.
6. **Marcas inactivas:** una marca que no abrió la pantalla en **14 días** no tiene corrida semanal.
7. **Retención:** las corridas y las ideas de cada marca se guardan **4 semanas**. Siempre se conserva la última corrida buena.
8. **Una búsqueda que falla nunca reemplaza lo guardado.**
   - Si falla el filtro de Claude, se guarda lo que se leyó y la siguiente corrida solo reintenta la revisión.
   - Sin brief, no se lee nada.

   Así se cierran H5 y H6.
9. **Lo que ve el dueño:**
   - nunca ve créditos ni dinero (decisión del 2026-10-20 y D1 de `docs/modelo-cobro-generacion.md`);
   - cuando se acaba el tope o el cupo diario, ve lo guardado y «Mañana puedes buscar otra vez»;
   - cuando llegan ideas nuevas, aparece un aviso en **Inicio**.
10. **«Hacer uno parecido»** abre Crear pieza prellenado con el reel (4 pasos). Toma de la BD el texto, la transcripción, el sonido, el formato y el gancho, sin llamar al proveedor. Lo que se genere se cobra en creaciones (`modelo-cobro-generacion.md`).
11. **Portadas y avatares de referentes van a R2, con un prefijo público global** (`public/reel-covers/…`, `public/avatars/…`). Es una **excepción firmada a la clave por tenant de ADR 22**, porque es dato público, igual que 0036.
    - Las portadas se bajan **durante la corrida** y solo de los reels que quedan como idea: la de Instagram caduca en ~4 días y la idea vive 7.
    - Los avatares se copian **una vez** del volumen a R2.
    - Cuando falta un avatar, se busca primero en `vendor_payloads` (perfil, 30 días, 0 créditos) y solo después en el proveedor, a través de la puerta medida, con un tope de **10/h**.
12. **El cliente de ScrapeCreators y el pipeline se mudan a `packages/api`:**
    - `qualify_api.vendors.scrapecreators`, que es la puerta;
    - `qualify_api.referentes.reels`, que es el servicio.

    Reflex se queda con el estado y la vista. Las corridas las atiende un servicio nuevo, `reels-worker`: un bucle CLI en la misma imagen `app`, sin runtime nuevo, con su propio rol de base de datos, igual que los otros workers.
13. **Se sigue en el plan Freelance.** Business no compensa a este volumen.
14. El video:
    - el MP4 del CDN sigue sirviendo mientras su URL firmada esté viva (24–33 h);
    - después, la tarjeta usa el reproductor oficial de la red, que ya existe;
    - no se paga por renovar el MP4.

### 2.1 Costo esperado (por marca activa y mes, 8 referentes, Freelance)

| Disparo | Créditos | USD (créditos + Claude) | Veces/mes | USD/mes |
|---|---|---|---|---|
| Corrida semanal: recorrido de 30 días (~25) + transcripciones de Instagram de los candidatos nuevos (~10–15) | ~37 | 0,07 + 0,03 | 4,33 | ≈ 0,43 |
| «Buscar reels nuevos»: página 1 de las cuentas con más de 24 h (≤ 8) + ~3 transcripciones | ~11 | 0,02 + 0,005 | 4 realista, 22 como máximo | 0,10–0,57 |
| **Total** | **~200** | | | **≈ 0,55 realista, ≈ 1,0 máximo** |

- Una marca inactiva cuesta **0**.
- La flota de 8 marcas pasa de **≈ USD 50 al mes a ≈ USD 4–8** (−85–90 %), sin contar las cuentas que comparten varias marcas.
  - *→ Enmienda del 2026-11-04, punto 6: la medición no sostiene los USD 50 de partida; hoy pueden gastar 4 marcas, ≈ USD 0,8 al mes.*
- El tope de 600 créditos al mes deja 3 veces de margen sobre lo esperado.
- **Filas por año:** unos 22.000 reels públicos y 30.000 veredictos con 8 marcas; unos 360.000 reels con 100 marcas. Es poco para Postgres y ni roza el umbral de ADR 31.
- **R2:** < 50 MB entre portadas y avatares, menos de USD 0,001 al mes.

## 3. Esquema (una migración sobre la cabeza de `origin/main`; hoy es 0092)

### 3.1 Globales: dato público, sin `tenant_id` ni RLS

La excepción se escribe en el docstring, como en 0036, y `test_rls_policy_shape` no enumera estas tablas.

| Tabla | Columnas clave | Notas |
|---|---|---|
| `reel_accounts` | `network`, `handle` (UNIQUE juntos, con los mismos CHECK de normalización que `creators`), `page1_at`, `full_walk_at`, `covered_days`, `newest_taken_at`, `status` (`ok`/`missing`/`private`/`error`), `last_http_status`, `credits_total`, `refresh_lock_until` | El candado evita que dos tenants refresquen la misma cuenta a la vez |
| `public_reels` | UNIQUE `(network, reel_id)`; `handle`, `taken_at`, `caption`, `duration_s`, `sound` JSONB, `is_paid_partnership`, `views`, `likes`, `comments`, `saves`, `shares`, **`metrics_at`**, `first_seen_at`, `cover_r2_key`, `transcript`, `transcript_source` (`vendor_stt`/`tiktok_vtt`/`none`), `transcript_at`, **`source_payload_id` → `vendor_payloads.id`, `parser_version`** | Upsert con guardia monótona (`WHERE EXCLUDED.metrics_at > public_reels.metrics_at`). Índice `(network, handle, taken_at DESC)` |
| `vendor_payloads` (ya existe) | + `payload_r2_key` | Guarda la respuesta cruda de cada página, con el cursor en `params_key`. `expires_at` es «servir hasta», no «guardar hasta». Una página de más de **100 KB** va a R2 en gzip |
| `vendor_balance` | `vendor` PK, `credits_remaining`, `observed_at` | Se actualiza gratis con cada respuesta |

### 3.2 Por tenant: `tenant_id NOT NULL` + ENABLE + FORCE + la política `NULLIF`, en la misma revisión

| Tabla | Columnas clave | Idempotencia |
|---|---|---|
| `brand_reel_verdicts` | `brand_id`, `network`, `reel_id`, `brief_hash`, `input_hash`, `affinity`, `fits`, `format`, `hook`, `reason`, **`model_id`, `prompt_version`, `effort`**, `cost_usd` | UNIQUE `(brand_id, network, reel_id, brief_hash, input_hash)` |
| `brand_reel_runs` | `brand_id`, `trigger` (`weekly`/`manual`/`operator_90d`), `run_date`, `status` (`queued`/`running`/`ok`/`check_failed`/`budget_stopped`/`error`), `days`, `accounts_total`, `accounts_done`, `credits`, `cost_usd`, `brief_hash`, `pipeline_version`, `queued_at`, `started_at`, `finished_at` | UNIQUE `(brand_id, trigger, run_date)`: el programador y el doble clic no repiten |
| `brand_reel_ideas` | `run_id`, `brand_id`, `network`, `reel_id`, `rank`, `window`, `verdict_id`, `seen_at` | UNIQUE `(run_id, network, reel_id)` |
| `vendor_usage_events` | `brand_id` (nullable), `vendor`, `feature` (`reels_list`/`reels_transcript`/`avatar_refresh`/`profile`), `credits`, `usd_estimate`, `request_key` UNIQUE, `payload_id` | El tope es un `SUM` del día o del mes. Es la semilla del `billing.usage_events` de Fase 5, separada de `creative_usage_events` |

Cómo se derivan los datos de la pantalla:

- **Cupo del botón:** a partir de la última corrida `manual` (`finished_at` + 1 día, en hora local). No hace falta columna.
- **Progreso real:** `accounts_done / accounts_total`.
- **Marca inactiva:** la última apertura (`seen_at`) tiene más de 14 días.
  - *→ Enmienda del 2026-11-04, punto 2: se lee de `brand_reel_activity.last_opened_at`, no de `seen_at`.*
- **La vista lee la última corrida `ok`.** Las ideas son un `JOIN` de `brand_reel_ideas` con `public_reels`.

La migración lleva un test `-m db` que prueba que el tenant A no lee las filas del tenant B en las cuatro tablas con RLS.

## 4. Fronteras de módulo

- **`qualify_api.vendors.scrapecreators`** es la única puerta de pago (`metered_get`). Hace, en orden:
  1. comprueba el interruptor `QUALIFY_SCRAPECREATORS_PAID`;
  2. no llama si el saldo está bajo el piso (`vendor_balance` < 500);
  3. comprueba el tope del tenant;
  4. llama al proveedor;
  5. registra `vendor_usage_events` y `vendor_payloads`;
  6. actualiza el saldo;
  7. ante un 402, para todo;
  8. avisa a Lark por debajo de 2.000.

  Un test estático, como el de las puertas de base de datos, falla si otro módulo llama a `api.scrapecreators.com`. La búsqueda de referentes, el asistente del Brand Kit y los avatares también pasan por esta puerta.
- **`qualify_api.referentes.reels`** es el servicio:
  - `view()` solo lee la BD;
  - `enqueue_run()` deja una corrida en cola, idempotente;
  - `run()` es lo único que paga, y lo llama solo el worker.
- **`reels-worker`** es un bucle CLI (`just reels-worker`). Cada pocos segundos toma las corridas en cola y cada 15 min programa las semanales que vencieron. Va en el compose de producción como `webhook-worker`, con su propio rol de base de datos. En local, siempre con `--tenant <uuid>`.
- **`Qualify/`** se queda con el estado y la vista. `Qualify/reels_discovery.py` desaparece o queda como un adaptador de tarjetas.

## 5. Opciones consideradas

| Opción | Por qué no |
|---|---|
| Caché persistente por marca (el resultado armado, como JSONB y con RLS) | Paga dos veces la misma cuenta pública, no guarda el payload crudo ni la procedencia por reel, y no limita el gasto |
| Mantener la memoria del proceso con un TTL más largo | Cada merge despliega, así que la memoria vive 15–90 min (H3) |
| Leer al abrir, de forma perezosa por cuenta | Sigue gastando sin que el dueño lo pida, y la primera apertura del día espera. Ux-designer prefirió la corrida semanal |
| Confirmar antes de cada lectura pagada | Va contra la decisión de no mostrar cobros y le pasa al dueño una decisión que no puede tomar |
| Redis como caché | No tiene copia de seguridad, no guarda el crudo ni la procedencia, y ADR 31 dice Postgres |
| Plan Business de ScrapeCreators | A unos 2.000 créditos al mes de flota, los 500.000 tardarían años en gastarse. Abarata el crédito, pero no controla el gasto |
| Haiku 5.5 en lugar de Sonnet 5 | La eval lo vio fallar trampas. Con los veredictos guardados, Claude baja a ~USD 0,15 al mes por marca |
| Renovar el MP4 con `/v1/instagram/post` | 1 crédito por reproducción, y el reproductor oficial ya resuelve el caso |

## 6. Consecuencias

- **Gasto acotado por diseño:** el peor caso de un negocio son 600 créditos al mes (≈ USD 1,1) más su Claude, y el peor caso de la flota lo corta el piso global.
- **Se cumplen las reglas de la casa que hoy no se cumplen aquí:**
  - payload crudo guardado;
  - procedencia en cada fila derivada;
  - idempotencia en las corridas y en el consumo;
  - trabajo caro fuera de la petición, con un guardián de precio delante.
- **Ganancia de red:** dos negocios del mismo rubro y ciudad que se inspiran en la misma cuenta pagan una sola lectura.
- **Costo:**
  - las vistas de los reels viejos pueden tener hasta 72 h, y la tarjeta dice la fecha de los datos;
  - la primera apertura de una marca nueva muestra un estado vacío hasta su primera corrida o hasta «Buscar reels nuevos»;
    - *→ Enmienda del 2026-11-04, punto 1: ya no; esa apertura encola su primera corrida y la pantalla dice que se está preparando.*
  - hay un servicio más en producción (`reels-worker`).
- **Riesgo nuevo:** que algún día alguien añada a una tabla global una columna de tenant o de marca. La regla va en el docstring de la migración y en la revisión de seguridad del PR.

## 7. Qué lo reabriría

- Más del 30 % de las marcas activas usan «Buscar reels nuevos» todos los días: la corrida semanal no les basta.
- Algún cliente reporta que las vistas desactualizadas le hicieron elegir mal.
- ScrapeCreators empieza a cobrar su caché o más que duplica el precio.
- Aparece un dato no público en una fila global.
- El consumo de la flota supera 5.000 créditos al mes con menos de 20 marcas activas: quiere decir que algo se salta la puerta.

## Anexo — rebanadas para la épica

El product-owner las archiva tal cual: una rebanada, un Issue y un PR. Áreas: **BE** = backend-engineer, **UI** = reflex-ui-engineer, **PL** = platform-engineer, **UX** = revisión de ux-designer antes del PR, **DS** = data-scientist-fde.

### F1 — persistencia y puerta (cierra las fugas H5–H8)

| # | Rebanada | Área | Depende de | Criterio de aceptación verificable |
|---|---|---|---|---|
| R1 | Mudar el cliente de ScrapeCreators y el pipeline de reels a `packages/api` (`qualify_api.vendors.scrapecreators`, `qualify_api.referentes.reels`) sin cambiar el comportamiento; `Qualify/` importa de allí | BE | — | Los tests de `Qualify/test_reels_discovery.py` y `test_scrapecreators_client.py` pasan desde `packages/api`; no queda en `Qualify/` código que llame al proveedor para reels |
| R2 | Puerta medida `metered_get`: interruptor, piso de 500, parada ante 402, lectura de `credits_remaining`, alerta a Lark bajo 2.000; test estático que prohíbe otras llamadas | BE | R1 | Un test con saldo simulado de 499 no hace la llamada; un 402 deja el interruptor en parada; el test estático falla si se añade un `httpx.get` al dominio del proveedor fuera de la puerta |
| R3 | Migración: `reel_accounts`, `public_reels`, `vendor_balance`, `vendor_payloads.payload_r2_key` (globales) + `brand_reel_verdicts`, `brand_reel_runs`, `brand_reel_ideas`, `vendor_usage_events` (RLS) | BE | — | `just test-db` pasa con el aislamiento A/B en las cuatro tablas con RLS; upgrade → downgrade → upgrade limpio en CI |
| R4 | `run()` persistente: comprueba brief y clave **antes** de pagar; refresco por cuenta con TTL de 24/72 h y candado; transcripciones y veredictos en BD con procedencia; un fallo de Claude deja la corrida en `check_failed` sin borrar lo guardado | BE | R2, R3 | Test: sin brief no hay llamada al proveedor; con Claude caído, una segunda corrida no vuelve a pagar listas; dos tenants con el mismo referente generan una sola lectura |
| R5 | Topes por negocio (150/día, 600/mes) desde `vendor_usage_events`, cargados al tenant que dispara; un tope alcanzado deja la corrida en `budget_stopped` | BE | R2, R3 | Test con 149 + 2 créditos: la segunda llamada no se hace y queda registrada la parada |
| R6 | Raw de las listas en `vendor_payloads` (a R2 en gzip si pasa de 100 KB) con `parser_version` | BE | R3 | Se puede re-parsear una página guardada sin red; medir y anotar en el PR cuánto pesa una página real |
| R7 | La vista lee la BD: abrir no llama al proveedor; muestra la última corrida `ok` con «Actualizado …» y la fecha de los datos | UI + UX | R4 | Test de la vista: abrir con la BD vacía muestra el estado vacío y hace cero llamadas al proveedor |

**Nota de R1 (m-24854844).** El pipeline ya vive en `qualify_api.referentes.reels` y el cliente en `qualify_api.vendors.scrapecreators`, pero el armado del brief de la marca (`brand_brief`: semilla de la búsqueda, Brand Kit y catálogo) sigue en `Qualify/reels_discovery.py` y llega al servicio como `BriefLoader` inyectado. Por eso un worker de `qualify_api` todavía no puede correr una búsqueda solo. **El armado del brief se muda a `packages/api` en R4**, que es la corrida persistente que comprueba el brief antes de pagar.

**Nota de R2 (m-24854847, reducida por la épica «Video por partes» m-24921048).** La puerta es `metered_get(client, path, params, *, feature)` en `qualify_api.vendors.scrapecreators`, y todas las lecturas pasan por ella: perfil, publicaciones, reels, transcripción (`reels_transcript`), tendencias, la búsqueda de referentes y el asistente del Brand Kit (`Qualify/creator_discovery.py`) y el avatar (`Qualify/avatar_proxy.py`, `avatar_refresh`). Hace, en orden:

1. El interruptor `QUALIFY_SCRAPECREATORS_PAID`: sin definir, la puerta está abierta; con `0`, `false`, `off` o `no`, no llama.
2. Lee `vendor_balance`. Si no puede leerlo, no llama.
3. Tras un 402, el proceso queda parado hasta que se registre un saldo nuevo de 500 o más.
4. Con un saldo menor de 500, no llama.
5. Llama al proveedor.
6. Guarda el `credits_remaining` de la respuesta, con guardia monótona por `observed_at`.
7. Ante un 402, guarda 0. Así el piso para también a los demás procesos.

El saldo de cada respuesta se fecha en el momento en que salió la petición, no cuando llegó la respuesta. Así, una respuesta lenta que salió antes de un 402 nunca reemplaza el 0 que dejó ese 402.

Para volver después de recargar créditos está `just sc-balance-refresh`, que lee la ruta gratuita `/v1/credit-balance` y lo guarda. Si no puede guardarlo, falla con error: nunca muestra un número que no quedó guardado. En local toma la clave y la base de datos del `.env`. En producción se corre dentro del contenedor, en el servidor y con el alias `dc` de `docs/despliegue-hetzner.md` §7:

```bash
dc exec api python -c "from qualify_api.vendors.scrapecreators import refresh_balance; print(refresh_balance())"
```

Los procesos que ya estaban parados por el 402 vuelven solos en su siguiente llamada, sin reiniciarse.

**El piso no es exacto.** Cada proceso lee el saldo antes de llamar, y varias llamadas pueden estar en vuelo al mismo tiempo. El piso puede pasarse hasta en (llamadas en paralelo × créditos por llamada); hoy son unas decenas, dentro de la reserva de 500. Una cuenta exacta pediría reservar créditos antes de cada llamada, y no se hace. Un test estático (`test_scrapecreators_gate_sanctity.py`) falla si cualquier otro módulo nombra `api.scrapecreators.com`, usa `BASE_URL` o hace la petición cruda. No tiene más excepción que la puerta, y eso incluye `referentes/reel_analysis*`. El saldo se lee y se escribe por una puerta nueva sin tenant, `global_session` (rol `qualify_app`, sin `app.tenant_id`, así que RLS no muestra ni acepta filas de ningún tenant).

**Avisos a Lark por saldo (añadidos 2026-11-04, antes aplazados).** El aviso está construido y apagado; se activa con `QUALIFY_SCRAPECREATORS_BALANCE_ALERTS=1`, que se lee al arrancar (cambiarlo pide reiniciar la app y los workers) (ticket de deuda técnica m-24945859, decisión del fundador del 2026-11-04). Apagado, no sale ningún mensaje a ningún canal, pero la cuenta sigue: cada aviso se anota en `alerts_sent` y queda en el log (nivel WARNING, con tipo y créditos). Un aviso anotado mientras está apagado se da por gastado, así que al encenderlo no llega una ráfaga de avisos viejos: el siguiente sale en el próximo cruce real después de una recarga. Lo que sigue describe el comportamiento con el aviso encendido. Tres avisos, cada uno **una sola vez por episodio**: por debajo de 2.000 («Quedan N créditos de ScrapeCreators (menos de 2.000). Recargar antes de llegar a 500, donde las búsquedas se frenan.»), por debajo del piso de 500 (la puerta deja de llamar) y ante un 402 («Se acabaron los créditos…», con el paso para volver). Si el saldo cae de golpe, sale solo el más grave. Qué avisos ya salieron se guarda en `vendor_balance.alerts_sent` (migración 0121), y cada escritura del saldo decide y lo anota en la misma transacción, bajo un candado consultivo por proveedor (`pg_advisory_xact_lock`). Así, entre la app y todos los workers, avisa solo un proceso (prueba con ocho escrituras simultáneas en `test_scrapecreators_balance_db.py`). Un aviso vuelve a quedar listo solo con una recarga: la lectura del operador (`just sc-balance-refresh`) en su nivel o por encima, o cualquier respuesta al menos 200 créditos por encima. No basta una respuesta normal, porque una respuesta se fecha cuando salió la petición y el proveedor cuenta cuando cobra: cerca de 2.000 pueden llegar desordenadas (1.999 y después 2.000) y eso no es una recarga. El envío va en un hilo aparte y sin reintentos: nunca frena ni rompe la llamada pagada. Un comando que termina justo después de escribir (la recarga) espera los envíos pendientes al salir, como mucho 10 s en total, en vez de perderlos. Destino: el bot del grupo Qualify-devs, el mismo del aviso de deploy (`QUALIFY_DEVOPS_WEBHOOK_URL` y `_SECRET` en `.env.prod`, con los valores de los secretos de GitHub, que la app no hereda); si falta, el canal interno `QUALIFY_SUPPORT_WEBHOOK_URL`; si faltan los dos, solo el log.

Las filas de `vendor_usage_events` y los topes por negocio llegaron con R5 (nota siguiente).

**Excepción al tope por negocio (2026-11-05, decisión del fundador, m-24956180).** Un negocio puede quedar **sin el tope de 150 al día y 600 al mes** (y sin el presupuesto propio de Creadores, 50/300). Se decide por negocio desde su ítem «Alta de cliente» en Meegle, con el campo «Lecturas sin límite» (`Sí · No`), y queda en `business_read_limits` (migración 0131) con el ítem, quién lo activó y cuándo. El primero es Bianki, para revisar creadores sin tope. Lo que **no** cambia: cada crédito se anota antes de la llamada en `vendor_usage_events` (contabilidad, procedencia, idempotencia), y siguen el piso global de 500, la parada ante un 402, el interruptor, `no_tenant` y `usage_unreadable`; solo se salta la comprobación del tope (`book(..., capped=False)`). Costo: ≈ USD 0,0019 por crédito (tabla de precios `v7`, `scrapecreators.per_credit`); una revisión de un creador cuesta como mucho 5 créditos (≈ USD 0,0095). El gasto de un negocio sin tope solo lo frena el piso global, así que se revisa en `vendor_usage_events`. Puerta de dos vías: `No` en el Alta lo devuelve al tope, y bajar la migración devuelve a todos.

**Nota de R5 (m-24854849).** Los topes viven en `qualify_api.vendors.usage` y los aplica la misma puerta (`metered_get`), entre el piso y la llamada. Cómo quedó:

- **Toda lectura pagada es de algún negocio (decisión de Deivid del 2026-11-04, «incluir todo»).** Una llamada sin negocio al que cobrarle no se hace (`no_tenant`): un worker o un comando que lea tiene que decir para quién (`--tenant`). Nada queda fuera del tope: la lectura de 90 días del operador (`operator_90d`), las tendencias y el último recurso de los avatares cuentan como cualquier otra. **Esto reemplaza la decisión de QUA-107** de que las tendencias no se cobraban a ningún negocio: desde el 2026-11-04 se cobran al negocio de la sesión, y el test que lo fijaba ahora fija lo contrario.
- **A quién se cobra.** Al negocio que disparó la lectura. O el cliente HTTP lleva el cargo (`usage.bind`, para las corridas que reparten llamadas entre hilos) o el código que llama abre `usage.charge_to(tenant, marca)` (`asyncio.to_thread` y `create_task` lo copian). Lo que ya está guardado (cuenta fresca en `reel_accounts`, la caché compartida de la búsqueda, una foto en disco) no llama al proveedor, así que no se cobra a nadie: dos negocios que siguen la misma cuenta pagan una sola lectura, cargada al que la disparó.
- **Antes de llamar** la puerta anota 1 crédito en `vendor_usage_events` para ese negocio, en una sola transacción bajo un candado consultivo por tenant (`pg_advisory_xact_lock`): suma lo del día y lo del mes en la hora local del negocio (`tenants.timezone`; si no se puede leer, cuenta en UTC y lo avisa una vez en el log) y, si el crédito pasaría de **150 en el día o 600 en el mes**, no anota nada y no llama (`tenant_daily_cap` o `tenant_monthly_cap`). Dos llamadas en paralelo con 149 gastados: pasa una sola (prueba con ocho en `test_vendor_usage_caps_db.py`). Dentro de un proceso, un candado por tenant se toma **antes** de pedir conexión, así que una búsqueda con 12 hilos usa como mucho una conexión del pool por negocio mientras espera, y no agota el pool. Ningún candado se sostiene durante la llamada. `created_at` es el `now()` de la base.
- **Después** de la respuesta, si el proveedor dice `credits_charged` mayor que 1, se anota la diferencia (fila `:extra`) sin mirar el tope: ya está gastado. La tabla es solo de agregar para `qualify_app`, así que una llamada que falla (red, 404, respuesta de la caché del proveedor) conserva su crédito: la cuenta puede pasarse, nunca quedarse corta.
- Cada fila lleva `usd_estimate` (`scrapecreators.per_credit` de la tabla de precios) y `pricing_table_version` (`v7`). Si la tabla no se puede leer o escribir, la puerta no llama (`usage_unreadable`).
- **Caminos cobrados y con tope:** la corrida persistente (`reel_runs.run`, todos los disparadores), la lectura vieja de «Descubrir reels» (`reels.discover`, mes y 90 días) y su «Ver transcripción», la búsqueda de referentes y la cuenta agregada a mano (`PhasedDiscovery`, `lookup_account`, incluido el recálculo de `referentes_provider`), el comando `creator_discovery` (exige `--tenant`), la lectura del perfil del Brand Kit, del asistente y del Alta (`brand_prefill.prefill_brand_kit`), las tendencias (`trending_state`, negocio de la sesión) y el último recurso de los avatares cuando lo pide la precarga de la sesión. La petición `<img>` de un avatar no lleva sesión: ya no paga nunca.
- **Lo que ve el dueño** cuando un tope frena una lectura (nunca créditos ni dinero), por el motivo de `ScrapeCreatorsBlocked.reason`; los demás motivos conservan su texto:
  - tope del día: «Ya hiciste todas las búsquedas de hoy. Mañana puedes buscar de nuevo.»
  - tope del mes: «Este mes ya hiciste todas las búsquedas. Desde el 1 de <mes siguiente> puedes buscar de nuevo.» (mes en español, en la zona del negocio)
  - lectura del perfil en el Brand Kit: «Hoy ya no podemos leer tu perfil. Completa tus datos tú mismo; mañana podremos leerlo.»; mensual: «Este mes ya no podemos leer tu perfil. Completa tus datos tú mismo; desde el 1 de <mes> podremos leerlo.», con el botón «Completar mis datos» hacia el flujo manual (`/brand/manual`).
  - título de «Descubrir reels» cuando un tope la frena: «Por hoy ya no hay más búsquedas» / «Este mes ya no hay más búsquedas», con «Volver al inicio».
  - Aparecen en «Descubrir reels», «Ver transcripción», la búsqueda de negocios parecidos y las tendencias. En la lectura del perfil del Brand Kit y en la búsqueda de negocios parecidos se muestran en tono de aviso (`warn`), no en el recuadro rojo de error: un tope es un límite, no una falla. Si el tope dejó la clasificación sin cuentas, en lugar de «No hay nada para clasificar…» se lee «Puedes añadir negocios a mano abajo o continuar.»
  - La foto de perfil del propio negocio (Brand Kit y propuesta del Alta) se guarda en disco apenas se lee, cobrada a ese negocio si hace falta la lectura pagada, porque la petición `<img>` no paga.
- Con la corrida: si el tope frena la lectura de una cuenta, la corrida queda `budget_stopped` y `RunOutcome.stopped` dice el motivo; si frena una transcripción, se dejan de pagar transcripciones y la revisión sigue con lo que hay (igual que el piso en R4).
- La migración 0124 amplía el CHECK de `feature` de 0117 a las siete que usa la puerta (`posts`, `referentes_search`, `trending`).

**Nota de R4 (m-24854848).** La corrida persistente vive en `qualify_api.referentes.reel_runs` (también se llega desde `qualify_api.referentes.reels`: `run`, `view`, `enqueue_run`) y guarda en `reel_store` (Postgres, y una versión en memoria para los tests). Cómo quedó:

- `enqueue_run(tenant, marca, trigger)` es idempotente por `(brand_id, trigger, run_date)`. Con `retry=True` vuelve a encolar una corrida `check_failed` o `error` («Intentar de nuevo»); una `ok` no se repite.
- `run(tenant, run_id)` es lo único que paga. Toma la corrida (`queued` → `running`) y **antes de cualquier llamada de pago** arma el brief y busca la clave de Anthropic: sin brief o sin clave termina `check_failed` sin llamar a nadie (H5).
- Por cuenta: si el recorrido completo tiene más de 72 h (o cubre menos días de los que pide la corrida) lee el recorrido; si no, y la página 1 tiene más de 24 h, lee solo la página 1; si no, no lee. Antes toma `refresh_lock_until` (10 min) y vuelve a mirar la frescura ya con el candado; al terminar solo suelta su propio candado. Si otro negocio lo tiene, espera hasta 5 min a que termine y usa lo que ese guardó.
- Solo los `MAX_PAID_TRANSCRIPTS` (40) reels de Instagram más vistos entre los candidatos pueden pagar transcripción, la tengan o no: un reintento no baja más en la lista.
- Las transcripciones quedan en `public_reels` (`transcript_at`), y nunca se pisan. Los veredictos quedan en `brand_reel_verdicts` con `model_id`, `prompt_version` (`reels_ai.REVIEW_PROMPT_VERSION`: hash del prompt de sistema, de la herramienta y del mensaje armado para una marca y un reel de prueba), `effort` y `cost_usd`. `input_hash` incluye lo que lee el modelo, el modelo, el esfuerzo y la versión del prompt.
- Si Claude falla, la corrida queda `check_failed` y no se borra nada; la siguiente no paga listas ni transcripciones (H6). Un rechazo de la puerta (interruptor, piso, 402) la deja `budget_stopped`; un error inesperado, `error`.
- Al cerrar `ok` guarda hasta 8 ideas en `brand_reel_ideas` (por vistas, con `window_days` 7, 30 o 90).
- **ADR 44:** `run(analyze=…)` recibe el analizador de ideas; su costo se suma a `cost_usd` y un fallo no cambia el estado. `analyze_run_ideas` (VE-04a, m-24921056) todavía no existe en `main`, así que lo conecta VE-04a.
- El armado del brief se mudó a `qualify_api.referentes.brand_brief`; `Qualify/reels_discovery.py`, `referentes_review.brand_brief` y `referentes_provider.rebuild_seed` son adaptadores sin cambio de comportamiento.
- Límites conocidos: la URL de subtítulos de TikTok no se guarda (caduca), así que un TikTok solo se transcribe en la corrida que leyó su cuenta; los créditos de la corrida se cuentan por respuestas del proveedor (una respuesta de su caché también cuenta); no hay concesión para una corrida que quede en `running` si el proceso muere: eso es de R8.
  - *→ Enmienda del 2026-11-04: la corrida que queda en `running` la recupera R8 (punto 4); el conteo por respuesta se corrige en R5 (punto 7).*

### F2 — corrida semanal, botón, R2 y nombre nuevo

| # | Rebanada | Área | Depende de | Criterio de aceptación verificable |
|---|---|---|---|---|
| R8 | `reels-worker` (`just reels-worker`, `--tenant` en local) en el compose de producción, con su propio rol de BD: atiende las corridas en cola y programa la semanal del lunes a las 06:00 hora local; omite marcas sin abrir en 14 días | BE + PL | R4, R5 | Test con reloj falso: a las 06:00 del lunes en `America/Bogota` encola una corrida por marca activa, ninguna para una marca inactiva, y una segunda pasada no duplica (UNIQUE) |
| R9 | Botón «Buscar reels nuevos»: encola una corrida `manual`, como máximo una al día por marca; muestra el progreso real (`accounts_done / accounts_total`) y, al agotarse, «Mañana puedes buscar otra vez» | UI + UX | R8 | Dos pulsaciones el mismo día crean una sola corrida; la pantalla nunca muestra créditos ni dinero |
| R10 | Lectura de 90 días solo para el operador de Qualify (corrida `operator_90d`) | BE + UI | R8 | Un usuario de negocio no ve la pestaña ni puede encolarla (test de permiso) |
| R11 | Ideas: 6–8 por corrida, marca de visto/nuevo, retención de 4 semanas (purga salvo la última `ok`) y aviso en Inicio cuando llegan | BE + UI + UX | R8 | Test de purga a 29 días; el aviso de Inicio aparece con ideas sin ver y desaparece al abrirlas |
| R12 | Portadas a R2 (`public/reel-covers/`) durante la corrida, solo de las ideas | BE | R8 | Una idea de 6 días muestra su portada desde R2 aunque la URL del CDN haya caducado |
| R13 | Avatares a R2 (`public/avatars/`): copia única del volumen; si falta, `vendor_payloads` (perfil, 30 días) y después la puerta, con tope de 10/h | BE + PL | R2 | Tras la copia, una URL firmada vencida no gasta créditos (test); el script de copia informa cuántos avatares copió y cuántos fallaron |
| R14 | «Hacer uno parecido» abre Crear pieza prellenado (4 pasos) con el texto, la transcripción, el sonido, el formato y el gancho guardados | UI + UX | R7 | Pulsarlo no llama a ScrapeCreators y deja Crear en el paso 1 con los campos rellenos |
| R15 | Nombre en pantalla: «Ideas para tus reels» y «cuentas que te inspiran» (copy según `qualify-copy-es`) | UI + UX | — | No queda «Descubrir reels» ni «referentes» en ningún texto que lea el cliente |
| R16 | Mover la búsqueda de referentes y el asistente del Brand Kit a la puerta medida | BE | R2 | El test estático de R2 pasa sin excepciones para esos módulos |
| R17 | Medición: consumo semanal por tenant y función (consulta SQL documentada) antes y después de F1, una semana cada uno | DS | R5 | El resultado queda anotado en `docs/descubrir-reels-scrapecreators.md` con la fecha |

R15 puede ir en paralelo con todo lo demás. R16 y R17 no bloquean el lanzamiento.

**Nota de R12 (m-24854859).** Construido sobre R7 y R8 (migración 0141). Cómo quedó:

- `public_reels` guarda el enlace de la portada (`cover_url` + `cover_url_at`), con la misma regla que `video_url` en el mismo upsert, y `cover_r2_used_at`, la última vez que una idea usó la copia. Un CHECK obliga a que `cover_r2_key` sea exactamente `public/reel-covers/<red>/<reel>.jpg` de esa fila: dos negocios escriben un solo objeto.
- `referentes/reel_covers.copy_idea_covers` corre en el gancho de `production_run` antes de `analyze_run_ideas`, nunca en `scoped_run`. Si la copia ya existe, solo mueve la fecha; si no, y la firma del enlace no caducó, baja la portada (CDN de la red, https por el 443, sin credenciales, sin redirecciones, 8 s, 3 MB), la recodifica (JPEG de 720 px como mucho, calidad 80, sin metadatos), la sube y la anota con `UPDATE … WHERE cover_r2_key IS NULL` por `tenant_session`. Un fallo queda en el log sin el enlace y no cambia la corrida.
- La puerta pública suma la raíz `reel-covers/` (forma exacta, solo `image/jpeg`, 1 MiB como mucho) y `delete_public_object`, solo para portadas. `reel_covers` usa `put_public` y `open_public`; `reel_retention`, además, `delete_public_object`; `Qualify/` no importa la puerta (test estático).
- La ruta `/avatar/reel/<red>/<reel>?s=…`, firmada con el reel (HMAC de `red` y `reel`), sirve la copia de R2 (caché de una semana) o un 404 `no-store`; sin la firma responde 404 sin leer R2. Esa lectura usa su propio cliente de R2 (2 s para conectar, 5 s para leer, sin reintentos) y sus propios hilos. La forma firmada `?u=&s=` queda como respaldo en vivo, sin copia en disco (caché de una hora). La caché en disco `avatars/reels/` se retiró del código; los archivos del servidor siguen ahí hasta que el fundador diga.
- `purge_reel_covers` borra la copia 30 días después de su último uso, en la misma pasada diaria y con el mismo interruptor que F9 (`purge_all`). Lo hace en una sola transacción con la fila bloqueada: primero limpia la fila, después borra el objeto y al final confirma. Si R2 falla, la fila vuelve a quedar como estaba. Una idea que usa la copia en ese momento espera y, al ver que ya no hay copia, la vuelve a copiar.
- R2 y la base no son una sola transacción (decidido en la revisión de R12, 2026-11-05). Si la subida a R2 sale bien y falla la escritura en la base, queda un objeto que ninguna fila nombra: la próxima copia del mismo reel lo adopta sin volver a subirlo (la clave es la del reel; el bucket de producción no deja sobrescribir, medido el 2026-11-05) y, si no hay otra, es una imagen pública pequeña que ninguna purga alcanza. Se acepta.
- `signature_expired`, los dominios del CDN (sin unavatar.io) y `heif_to_jpeg` se mudaron a `qualify_api.vendors.cdn_media`; el worker y el proxy los comparten.
- Límite conocido: el enlace de una portada es el de la última lectura de la cuenta (la primera página se relee pasadas 24 h; el resto, pasadas 72 h), y el de TikTok vive ~1 día. Una idea de TikTok cuyo enlace ya caducó no se copia y muestra el dibujo de reserva; arreglarlo costaría créditos (releer la cuenta), igual que el límite de «Replicar».

## Enmienda del 2026-11-04 — R7 y R8

**Estado:** los puntos 1, 8 y 9 los decidió Herwin Rey (fundador) el 2026-11-04 (en el 8 y el 9, lo que no es decisión suya lo dice al lado). El 10 es un dato, no una decisión. Los puntos 2 a 5 dicen cómo quedó lo construido en R7 (m-24854854) y R8 (m-24854855), que salen en un solo PR. El punto 6 es la medición de R17 (m-24854861) y el 7 dice cómo quedó R5 (m-24854849) frente a lo que proponía esta enmienda. Lo firmado arriba no se reescribe: cada línea que cambia lleva una nota que apunta aquí.

1. **La primera apertura de una marca sin corridas adelanta su corrida semanal** (opción A). Es la única excepción a «abrir la pantalla nunca gasta» (§2.1).
   - Solo si la marca no tiene ninguna corrida, tiene brief y tiene cuentas. La pantalla llama a `reel_runs.ensure_first_run()`, que solo encola: paga el `reels-worker`.
   - Es la misma fila `UNIQUE (brand_id, trigger, run_date)` que encolaría el lunes, así que esa semana no hay otra. Pasa como mucho una vez por marca y cuesta ≤ 88 créditos (12 cuentas × 4 páginas + 40 transcripciones).
   - Mientras corre, la pantalla dice que está preparando las ideas y vuelve a leer la BD, sin costo.
   - Descartada, la opción B: no gastar al abrir, con la pantalla vacía hasta el lunes o con el operador encolando a mano todas las marcas al desplegar.
   - El otro disparador automático que gasta, el reintento de un chequeo fallido, está en el punto 8.
2. **Inactividad:** la señal es `brand_reel_activity.last_opened_at` (migración `0134_reels_worker`, con RLS). La escribe `reel_runs.mark_opened()` al abrir la pantalla, solo hacia adelante y como mucho una vez por hora; si falla, queda en el log y la pantalla sigue. **Una marca sin fila está inactiva.** Reemplaza la derivación desde `seen_at` de §3.2: una marca que todavía no tiene ideas nunca tendría `seen_at` y nunca se activaría.
3. **Rol del worker:** se abandona el plan de 0117 de recortar los permisos de `qualify_app`. `qualify_reels_worker` (creado en 0119) usa la puerta `qualify_shared/db/reels_worker.py`. De los negocios solo **lee**: una política `FOR SELECT` para ese rol y permisos por columna en `brand_reel_runs`, `brand_reel_activity` y `tenants` (solo `id` y `timezone`), lo justo para decidir qué corre y cuándo. Todo lo que escribe de un negocio (encolar, tomar, recuperar, terminar) y lo que paga la corrida va por `tenant_session(tenant_id)`, como en ADR 41. **Escribe** solo en las dos tablas globales del análisis (0119), por la cola de ADR 44 (VE-04a, `reel_analysis_queue`): el video de cada idea guardado en R2 y su borrado a los 30 días (punto 9).
4. **Programación y recuperación, como quedaron:**
   - una marca vence el lunes a las 06:00 de `tenants.timezone`, con una ventana de 24 h, si se abrió en los 14 días anteriores. Cerrada la ventana, esa semana no se recupera;
   - `run_date` es el lunes **local**, nunca la fecha UTC;
   - en la cola, `manual` y `operator_90d` van antes que `weekly`; después, la más vieja;
   - columna `attempts`: una corrida `running` por más de 30 min vuelve a `queued`, y a los 3 intentos termina en `error`. Esas escrituras, `progress` y `finish` exigen el `started_at` de la toma, así que un proceso viejo nunca pisa la corrida de otro;
   - un SIGTERM (un deploy) devuelve a la cola la corrida en curso.
5. **La pantalla perdió** «Actualizar», la lectura de 90 días y el «Ver transcripción» pagado: los tres pagaban desde el proceso de Reflex. La tarjeta muestra la transcripción que guardó la corrida, y las memorias del proceso de H2 (§1.2) se borraron. R9 («Buscar reels nuevos») y R10 (90 días, solo el operador) devuelven la búsqueda y la lectura de 90 días como corridas del worker.
6. **Medición** (R17, `docs/descubrir-reels-scrapecreators.md` §5, 2026-11-04):
   - toda la cuenta de ScrapeCreators gastó **156 créditos del 21-10 al 03-11**: ≈ 82 por semana, ≈ USD 0,15 por semana;
   - la pantalla se leyó **2 de 19 días**, y una apertura en frío cuesta USD 0,09–0,10;
   - los ≈ USD 50 al mes de §1.1 y §2.1 no los sostienen los datos;
   - con el uso de hoy, F1 no ahorra: compra un peor caso acotado y ninguna lectura repetida después de un deploy. Empieza a ahorrar cuando una marca pasa de ~1 apertura en frío por semana.
7. **R5, como quedó** (m-24854849; los detalles, en la nota de R5 de arriba). Esta enmienda proponía dos cosas y R5 resolvió otra cosa en las dos:
   - Se proponía que el tope sumara el `credits_charged` de cada respuesta. R5 anota 1 crédito antes de cada llamada (con tope) y, si la respuesta dice `credits_charged` mayor que 1, la diferencia después (sin tope). Una respuesta de la caché del proveedor (0) conserva su 1: la cuenta puede pasarse, nunca quedarse corta. Aparte, `brand_reel_runs.credits` de la corrida sigue contando 1 por respuesta (`reel_runs._counting_client`).
   - Se proponía que la corrida de 90 días del operador (≤ 184 créditos: 12 × 12 + 40) no contara contra el tope diario del negocio. R5 la cuenta como cualquier otra lectura («incluir todo», 2026-11-04): con poco margen en el día queda en `budget_stopped` a mitad de camino; pedirla otra vez al día siguiente no relee lo ya leído (24 h / 72 h).
   - En el `reels-worker`, cada corrida (la del lunes, la primera de la opción A y un reintento del punto 8) se cobra a su negocio y su marca; un tope alcanzado la deja en `budget_stopped` sin la llamada siguiente (`test_reels_worker_r5_charges.py`).
   - De los caminos cobrados que lista la nota de R5, R7 retiró la lectura vieja de «Descubrir reels» y su «Ver transcripción» (punto 5): en «Ideas para tus reels» queda solo la corrida del worker. La pantalla no distingue todavía un tope de un piso: muestra el mensaje de una corrida detenida, porque el motivo (`RunOutcome.stopped`) no se guarda en la corrida.
8. **Reintento automático de un chequeo fallido** (fundador, 2026-11-04). Es un **disparador automático nuevo que gasta Claude**, además de la corrida semanal (§2) y de la primera corrida del punto 1.
   - Una corrida que termina `check_failed` (Claude caído, sin clave, sin brief) vuelve sola a la cola 15 min después de terminar, mientras se tomó menos de 3 veces: como mucho 2 reintentos por corrida.
   - Solo la última corrida de la marca (la que muestra la pantalla) y solo si terminó hace menos de 24 h (regla de la revisión de código del 2026-11-04). Un worker caído más tiempo, o una fila anterior a 0134, nunca repite el chequeo de otra semana con los datos de hoy.
   - Un reintento solo paga la revisión de Claude: las cuentas leídas y las transcripciones pagadas quedan guardadas, y el brief y la clave se miran antes de pagar.
   - La pantalla dice cuándo reintenta (`RunView.next_retry_at`). Después del tercer intento, o pasado ese día, espera al lunes.
9. **Videos de las ideas en R2 para «Replicar con mi marca» toda la semana** (fundador, 2026-11-04).
   - Al terminar `ok`, la corrida pasa sus ideas al análisis compartido de ADR 44 (`reel_analysis_worker.analyze_run_ideas`, VE-04a). Cada video se baja del CDN mientras su enlace sirve (gratis) y se guarda en R2 sin audio y sin recodificar.
   - Cada pasada del `reels-worker` atiende además la cola de ese análisis (`drain_once`). Nunca llama a ScrapeCreators; a Haiku solo con el interruptor de VE-04c (punto 10).
   - Se borran a los 30 días (VE-12, `reel_retention`). La fecha de borrado se escribe en la fila antes de subir el video: nada queda en R2 sin fecha.
   - **Límite conocido** (revisión de código del 2026-11-04; no lo decidió el fundador): si otro negocio leyó la misma cuenta hasta 72 h antes, la corrida no la vuelve a leer y el enlace de la idea ya pasó de 20 h. No se puede bajar, no queda copia y «Replicar» queda apagado para esa idea toda la semana. Arreglarlo costaría créditos (releer la página 1 de esas cuentas): si se paga o no lo decide el fundador.
10. **Gasto automático nuevo con VE-04c: la ficha de cada idea con Haiku** (dato para el fundador, 2026-11-06; las reglas son las de ADR 44 y no cambian aquí).
   - Solo con `QUALIFY_REEL_ANALYSIS_DESCRIBE=1` (apagado por defecto). Prendido, la corrida semanal de cada marca describe sus ideas nuevas al terminar `ok`; las que ya tienen ficha se reusan.
   - 1 llamada a Haiku por reel, a lo sumo 2 (un reintento): ≈ USD 0,0055 por reel normal, como mucho USD 0,0099 por llamada. Como mucho 10 análisis nuevos por corrida, y una corrida deja 6 a 8 ideas.
   - El tope de la flota: 1.500 llamadas al día para todos (`QUALIFY_REEL_ANALYSIS_FLEET_DAILY`), contadas antes de cada llamada; incluye lo que piden los negocios desde la pantalla (50 al día por negocio). Techo ≈ USD 15 al día.
   - Con 4 marcas activas: ≤ 32 reels por semana, ≈ USD 0,18 por semana normal (≈ USD 0,75 al mes) y ≤ USD 0,63 por semana en el peor caso. Menos si las marcas comparten reels.
   - El costo queda en la fila global y en Langfuse, nunca en el libro de consumo de un negocio (decisión 10 de la épica) ni en los créditos de R5 (`test_reels_worker_analysis_drain.py`). R4 lo suma además, como dato, al `cost_usd` de la corrida que lo disparó.
   - Una fila cuyo video ya se borró a los 30 días no la toma ni la descarga ni la descripción (FN3): leería un objeto que ya no existe.
