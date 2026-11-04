# ADR 42 — «Ideas para tus reels»: reels públicos compartidos, puerta medida y corrida semanal

**Estado:** `[APROBADO — decisiones de Herwin Rey (fundador), 2026-10-24 y 2026-10-25]` · propuesto por principal-architect.
**Ticket:** m-24854769 · **Épica:** la crea el product-owner desde el [anexo](#anexo--rebanadas-para-la-épica).
**Evidencia:** lectura del código de `main` del 2026-10-24 (§1.2, con líneas) y el análisis de experiencia de ux-designer del mismo día (abrir nunca busca, corrida semanal, cupo en tiempo).
**Numeración:** el análisis hablaba de «ADR 40», pero el 40 (SonarQube y Langfuse) y el 41 (cola de generación) ya estaban firmados en `main`. Esta decisión es la **42**.
**Nombre en pantalla:** la función se llama **«Ideas para tus reels»** y los referentes se muestran como **«cuentas que te inspiran»**. En el código y en este documento se sigue diciendo *referentes* y *Descubrir reels* hasta que el cambio de nombre llegue a la interfaz.

## 1. Contexto

### 1.1 El problema

«Descubrir reels» (`docs/descubrir-reels-scrapecreators.md`) gasta créditos de ScrapeCreators **y** llamadas a Claude sin control. La flota gasta unos **USD 50 al mes** con uso realista: unas 13.000 lecturas pagadas más un gasto parecido en Claude. A ese ritmo, el saldo de 3.681 créditos del 2026-10-15 dura **8 o 9 días**. Abrir la pantalla dispara una lectura que el dueño no pidió, y lo que se pagó se pierde en el siguiente despliegue.

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

**Claude cuesta lo mismo que el proveedor en cada apertura en frío.** Por eso este ADR guarda también los veredictos, no solo los reels.

## 2. Decisión

1. **Abrir la pantalla nunca gasta.** «Ideas para tus reels» lee de Postgres. Las lecturas pagadas solo pasan de tres maneras:
   - **(a) la corrida semanal** de cada marca activa, el **lunes a las 06:00 en la hora local del negocio** (`tenants.timezone`). Deja entre **6 y 8 ideas**;
   - **(b) «Buscar reels nuevos»**, como máximo **1 vez al día por marca**;
   - **(c) la lectura de 90 días**, que hace **solo el operador de Qualify** (rol admin).
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

Queda fuera, a propósito: las filas de `vendor_usage_events` y los topes por negocio van en R5, porque necesitan el tenant que dispara la llamada. Hoy la puerta solo registra en el log la `feature` de cada llamada.

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
