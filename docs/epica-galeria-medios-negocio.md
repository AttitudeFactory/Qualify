# Épica — Galería con fotos y videos del negocio para crear publicaciones con lo elegido

`[PROPUESTA 2026-11-05 · épica m-24955913]` · Dueño del documento: product-owner.
**Nombre:** la pantalla antes «Tus productos» / «Catálogo» se llama **«Galería»** en el menú
(primera entrada de «Publica», decisión del fundador 2026-11-05). Su ruta sigue siendo `/catalog`
y el módulo de código sigue siendo `catalog`.
Decisiones del fundador firmadas el 2026-11-05 (§2, D1–D9). Las decisiones de arquitectura que
bloqueaban CM-1 y CM-3 están tomadas (§4: ADR 47 y enmienda de ADR 39, `principal-architect`
2026-11-05) y el fundador aprobó el servicio `media-worker` (D8). No queda nada abierto (§8).

## 1. Por qué

**Pedido del fundador (2026-11-05):** «necesitaba cargar clips y fotos de mi negocio… mi
catálogo debería estar separado de piezas por aprobar… desde catálogo selecciono contenido para
generar piezas y después aprobarlas».

Para el dueño de un local de comida (Bianki, Polette) o de una agencia, las fotos y videos
reales de su local, su equipo, su cocina o su proceso son el contenido que más confianza da y
que hoy no tiene dónde guardar en Qualify. Con esta épica:

1. Guarda en **Galería** las fotos y videos de su negocio, separados de sus productos y
   separados de las piezas «Por aprobar».
2. Corta sus videos en partes y quita lo que no sirve.
3. Elige varias fotos y videos (del negocio y de sus productos) y crea con ellos **una**
   publicación, que llega a «Por aprobar». Nada se publica sin su aprobación.

### Lo que hay hoy (leído en disco, `main` en `785e9df9`)

| Qué | Dónde | Estado |
|---|---|---|
| Medios del catálogo | tabla `product_media` (migración `0038`), `product_id NOT NULL` | Solo medios de un producto; no hay dónde poner el local |
| Subida | `CatalogService.add_media` (`packages/api/src/qualify_api/catalog/service.py`) | Foto → JPEG para Instagram; video → `VideoNormalizer.normalize`: H.264, vertical, **≤ 15 s, sin sonido** (`-an`, `MAX_SECONDS = 15.0` en `qualify_creative/video/normalize.py`); clave `uploads/{tenant}/catalog/{product}/…`; máximo 12 por producto. **Los archivos de producto no están en R2:** `LocalMediaStore` (`Qualify/catalog_provider.py:63`) los escribe en el volumen `uploads` del servidor, que `deploy/backup-db.sh` no respalda |
| Cómo llega el archivo | `CatalogState._park` / `ingest_pending` (`Qualify/catalog_state.py:1081-1160`) | `await upload.read()` carga el archivo entero en memoria; la transcodificación corre en un evento en segundo plano del proceso de Reflex, que se reinicia en cada despliegue (uno por merge) |
| Quitar un medio | `CatalogService.remove_media` | Borra la **fila**; el objeto queda en R2 («procedencia de piezas ya hechas») |
| Crear desde el catálogo | `/create?producto=<id>` (m-24842972, `catalog_vm.create_with_product_href`) | Un producto a la vez, validado bajo RLS |
| Formato carrusel (hoy rotulado «Galería» en el generador) | `ContentKind.CAROUSEL`, `SlideSource` (`generated`, `animated`, `existing`, `stock`) | 2–10 diapositivas; ninguna fuente es «foto o video del catálogo tal cual» |
| Borrado en R2 | `ObjectGate.delete_prefix` (ADR 39) | Solo por debajo de `PURGEABLE_ROOTS` (hoy solo `generated/`); una raíz nueva es una decisión revisada. Esta épica suma `delete_gallery_media` (enmienda de ADR 39, §4.2) sin tocar `PURGEABLE_ROOTS` |
| Purga al desconectar | migración `0106_connection_purge.py` | Protege `product_media.object_key`; una tabla nueva de medios debe sumarse a esa lista |
| Cupo de video | m-24921139 (segundos de video al mes) | Cuenta video **generado** |

Fuera de esta épica (ya en curso en otro PR): renombrar «Tus productos» → «Galería» y subirlo
al inicio de la zona «Publica». PR #483 (categorías de productos) toca `catalog_page.py` y
`catalog_state.py`: las historias de pantalla se basan en `main` después de ese merge.

## 2. Decisiones firmadas (fundador, 2026-11-05)

| # | Decisión | Qué cambia en las historias |
|---|---|---|
| D1 | Los videos **del negocio** se guardan **con su sonido**; si se usa o no se decide al crear la publicación | La normalización del negocio no lleva `-an` (AAC); `/create` ofrece el interruptor de sonido |
| D2 | Duración máxima del video del negocio: **60 s**. Qualify elige el tramo al crear cuando el formato pide menos | Subida corta a 60 s; el generador elige el tramo (regla determinista, §5 CM-6) |
| D3 | Los videos **de producto** siguen como hoy: ≤ 15 s, sin sonido | Ningún cambio en `add_media` de productos |
| D4 | En Galería el dueño **corta** un video del negocio en partes y **quita** partes; lo quitado se borra de verdad (no se recupera tras confirmar). Cada parte que queda es un medio propio | Historias CM-3 y CM-4; el original y lo quitado salen de R2 al confirmar |
| D5 | Una publicación hecha solo con fotos y videos propios de Galería **cuenta como una creación del mes**, igual que cualquier otra | CM-6: descuenta una creación; no descuenta segundos de video |
| D6 | «Usar el sonido de tus videos» **empieza apagado** | CM-7: el interruptor arranca apagado |
| D7 | El formato carrusel del generador se rotula **«Carrusel»** (solo el texto) | Lo hace el PR #485, fuera de esta épica; CM-7 ya no lo incluye |
| D8 | **Se aprueba `media-worker`**: contenedor nuevo siempre encendido, misma imagen, ~100 MB en reposo y hasta 768 MB y 1 CPU mientras transcodifica | CM-1 lo despliega (§4.3) |
| D9 | La barra inferior del teléfono **no cambia**: Galería sigue bajo «Más» | Ninguna historia toca la barra inferior |

## 3. Reglas que la épica respeta

- **Aislamiento por negocio:** toda tabla nueva lleva `tenant_id` + RLS con la política
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` en la misma revisión; acceso solo
  por `tenant_session`.
- **Procedencia:** cada parte cortada guarda el id del video de origen, sus puntos de corte y la
  versión del proceso; cada pieza guarda qué medios usó, qué tramo y si llevó sonido.
- **Asistido, nunca autónomo:** la publicación queda en «Por aprobar»; no se programa ni se
  publica sola.
- **Datos del cliente y proveedores:** los medios del negocio no se mandan a un modelo
  generativo (BytePlus) en esta épica: el carrusel usa los archivos tal cual y Claude solo
  escribe el texto a partir del contexto de la marca.
- **R2:** sin objetos huérfanos al cortar o quitar; las piezas guardan su propia copia para que
  borrar en Galería no rompa una pieza ya hecha (y esa copia sigue ADR 39, 90 días).

## 4. Decisiones de arquitectura (`principal-architect`, 2026-11-05)

`[ADOPTADAS por principal-architect el 2026-11-05 dentro de las decisiones firmadas D1–D4 — ADR 47
en docs/arquitectura.md §6 y enmienda de ADR 39 (docs/adr-39-retencion-piezas.md). Sin proveedor,
almacén de datos ni lenguaje nuevos. El fundador aprobó el servicio
media-worker el 2026-11-05 (D8, §4.3)]`

### 4.0 Lo que se verificó en disco antes de decidir (`main` en `785e9df9`)

- **Los medios de producto no están en R2.** `CatalogService` se construye con
  `LocalMediaStore(media_root())` (`Qualify/catalog_provider.py:63`) y escribe en el volumen Docker
  `uploads` (`deploy/docker-compose.prod.yml`); `deploy/backup-db.sh` solo respalda Postgres. El
  plan de servidor documentado tiene 40 GB de disco (`docs/despliegue-hetzner.md`).
- **Hoy una fila de `product_media` sin producto no se filtraría al menú de WhatsApp:** todas las
  lecturas filtran `product_id = …` o `product_id IN (…)` (`catalog/service.py`,
  `catalog/read.py:58`, `whatsapp/attachments.py:893`) y en SQL `NULL IN (…)` nunca es verdadero.
  El riesgo que señala el product owner es **latente** (la próxima lectura por marca que olvide el
  filtro), no actual. La recomendación B se sostiene por otras razones (abajo).
- **La subida carga el archivo entero en memoria** (`await upload.read()` en
  `Qualify/catalog_state.py:1113`) y la transcodificación corre en un evento del proceso de Reflex,
  que muere con cada despliegue (uno por merge, `QUALIFY_AUTO_DEPLOY`).
- **`creative-worker` tiene `mem_limit: 512m`** compartido con hasta 3 descargas de videos pagados,
  y su rol de base de datos sigue `NOLOGIN` hasta que el fundador ponga su contraseña.
- **`ObjectGate` no presigna nada** (ADR 28c) y solo borra bajo `generated/` (`PURGEABLE_ROOTS`) o
  por manifiestos explícitos (`delete_brand_prefill_objects`, `delete_connection_objects`).
- **Los workers que recorren todos los negocios** leen solo ids con `admin_session` y trabajan con
  `tenant_session` (`whatsapp/worker.py:86`): patrón sin rol nuevo.

### 4.1 Dónde viven los medios del negocio → tabla nueva `business_media`, archivos en R2

| Opción | Qué es | Para el dueño | Costo | Riesgo principal |
|---|---|---|---|---|
| A. `product_media.product_id` opcional | Una tabla, columna `scope` | Igual | Una migración | Dos ciclos de vida en una tabla: el producto deja el objeto al quitar, el negocio lo borra (D4); `ON DELETE CASCADE`, `is_primary`, el índice `(product_id, position)` y el tope de 12 pierden sentido; contradice `0066`; cada lectura futura por marca debe acordarse de `product_id IS NOT NULL` |
| B. Tabla nueva, archivos en el volumen local (como los productos) | `business_media`, `LocalMediaStore` | Igual | 0 | El volumen no tiene respaldo y el disco es de 40 GB; el borrado de D4 y la copia a `generated/` de CM-6 ya hablan R2 |
| **C. Tabla nueva `business_media`, archivos en R2** | Una carpeta por medio `t/{tenant}/gallery/{media_id}/` | Sus videos quedan en almacenamiento durable | ~US$0,01–0,02 por negocio y mes (§6) | Una unión de dos fuentes en CM-5/CM-6 |

**Decisión: C.** Las lecturas de productos no cambian; las reglas propias (60 s, sonido, cortes,
borrado real) tienen su lugar; los archivos van a R2, donde la puerta ya controla el prefijo del
negocio y CM-6 copia lo usado a `generated/{draft_id}/`. Los medios de producto se quedan donde
están (fuera de alcance; el volumen sin respaldo queda como riesgo aparte, §4.4).

Forma de la tabla (la escribe CM-1 con `qualify-migration`):

- `id`, `tenant_id`, `brand_id` (FK compuesta a `brands (id, tenant_id)`), `media_type`
  (`image`/`video`), `object_key`, `poster_key` (video), `content_type`, `width`, `height`,
  `duration_ms`, `bytes`, `has_audio`, `position`, `filename`, `upload_sha256`, `created_at`,
  `deleted_at` (lápida, §4.2).
- **Procedencia del corte:** `source_media_id` (sin FK: el original se borra), `cut_start_ms`,
  `cut_end_ms`, `job_id`, `pipeline_version` (`gallery-ingest-v1`, `gallery-cut-v1`).
- `CHECK`: los tres campos del corte van todos o ninguno, con `cut_end_ms > cut_start_ms`; video ⇒
  `duration_ms <= 60000`; foto ⇒ `has_audio = false` y sin duración.
- `tenant_id` + `ENABLE` + `FORCE ROW LEVEL SECURITY` + política `NULLIF(current_setting(
  'app.tenant_id', true), '')::uuid` en la misma revisión; grants como `product_media`; toda lectura
  filtra `deleted_at IS NULL`.
- `object_key` y `poster_key` entran en `_PROTECTED_KEYS` de `connections/purge.py` (la lista que
  usa la purga de conexiones de `0106`).

**Se reabre si** el dueño pide pasar una foto del negocio a un producto (o al revés) más de una vez
al mes (una tabla `media` con vínculos), o si los medios de producto se mudan a R2 (unificar llaves).

### 4.2 Borrar en R2 → método nuevo y estrecho `delete_gallery_media`; escribir → confirmar → borrar

| Opción | Qué es | Riesgo principal |
|---|---|---|
| A. Sumar `gallery/` a `PURGEABLE_ROOTS` y usar `delete_prefix` | Una línea | `delete_prefix` recibe un texto libre del que llama: cualquier carpeta de la Galería del negocio se podría vaciar por error, y ADR 39 mezcla dos políticas en un método |
| B. Manifiesto explícito de llaves (como la purga de conexiones) | Se valida cada llave | Una parte subida a medias o una portada sin fila no está en ningún manifiesto: quedan huérfanas |
| **C. `ObjectGate.delete_gallery_media(tenant_id, media_id: UUID)`** | La puerta arma ella misma `t/{tenant}/gallery/{media_id}/` desde un UUID, lista y borra todo lo que hay debajo | Un método más en la puerta (decisión revisada: esta) |
| D. Reglas de ciclo de vida de R2 | Por edad | Descartadas por lo mismo que en ADR 39: no saben qué sigue en uso |

**Decisión: C**, con estas reglas:

1. **Un medio = una carpeta** `t/{tenant}/gallery/{media_id}/` (`video.mp4` + `poster.jpg`, o
   `photo.jpg`). Una parte cortada es un medio nuevo con su carpeta, y su id es determinista:
   `uuid5(job_id, índice de la parte)`.
2. **Lo quitado nunca se escribe:** solo se codifican los tramos que se quedan. Lo quitado vive
   dentro del original y desaparece con él; no hay objetos de «partes quitadas» que limpiar.
3. **Orden del corte** (job `cut`, §4.3):
   1. Al confirmar, una transacción crea el job con su clave de idempotencia (`UNIQUE`) y deja el
      original marcado como «en corte» (`job_id` activo): otro corte del mismo video se rechaza.
   2. El worker codifica cada parte a un archivo temporal y la sube a su llave determinista
      (`put_media`, un PUT atómico; un reintento sobrescribe la misma llave).
   3. **Una transacción** inserta las filas de las partes (`ON CONFLICT (id) DO NOTHING`), pone
      `deleted_at` al original y deja el job en `parts_saved`. **Este es el punto sin retorno.**
   4. `delete_gallery_media(original)`.
   5. Una transacción borra la fila del original y deja el job en `done`.
   - Falla antes de 3: el original sigue intacto y visible; el reintento rehace 2 sobre las mismas
     llaves. Si el job falla definitivo (3 intentos), el worker borra las carpetas
     `uuid5(job_id, i)` de cada parte: se enumeran sin listar el bucket.
   - Falla entre 3 y 5: el original ya no se ve (lápida) y el reintento repite 4 y 5, que son
     idempotentes (una carpeta vacía responde 0 objetos).
4. **«Quitar» un medio entero** (pregunta 3 del product owner): **sí borra el objeto**, con la
   misma secuencia sin el paso 2 — lápida → `delete_gallery_media` → borrar la fila —, en la misma
   petición (son 1–2 objetos). Si R2 falla, la lápida queda y el conciliador termina. Las piezas no
   se rompen porque CM-6 copia lo usado a `generated/{draft_id}/` (ADR 39 sigue rigiendo esa
   copia); un armado en curso que llegue después de la lápida descarta el medio con el aviso de
   CM-7.
5. **Conciliador diario** (en `media-worker`): por negocio con Galería, lista
   `t/{tenant}/gallery/` y borra (a) las carpetas sin fila, sin lápida y sin job activo, de más de
   24 h — la subida cortada entre el PUT y la fila —, (b) las lápidas de más de 1 h y (c) los
   archivos de espera del volumen de más de 24 h sin job activo. Registra
   cuántas carpetas, objetos y bytes borró. Así **ningún objeto queda huérfano** aunque falle
   cualquier paso.
6. `PURGEABLE_ROOTS` **no cambia** (`("generated/",)`); el test que fija los métodos de la puerta
   suma `delete_gallery_media` citando la enmienda de ADR 39. Fuera de `gallery/{uuid}/` el método no
   borra nada.

**Se reabre si** un dueño pide recuperar algo quitado más de una vez (entonces lápida de 7 días
antes de borrar), o si la Galería necesita carpetas compartidas entre medios.

### 4.3 Subida de un video de 60 s → por Reflex en trozos a disco, tope 500 MB, proceso en `media-worker`

**Tope de tamaño: 500 MB por archivo** `[H]` (un minuto en 4K a 60 cuadros en HEVC de iPhone ≈
400 MB; 4K en H.264 de Android ≈ 350 MB por minuto). El 300 MB que se proponía rechazaría el modo
de grabación más común en un iPhone reciente. Se comprueba en el selector (`max_size`) y otra vez en
el servidor mientras se lee (corta al pasar el tope). A lo sumo **3 videos esperando** por negocio.

| Opción | Qué es | Riesgo principal |
|---|---|---|
| A. Como hoy | Reflex, archivo entero en memoria, transcodifica en un evento de Reflex | 400 MB en la memoria del único proceso de Reflex; 1–3 min de CPU contra la pantalla; el trabajo muere en cada despliegue y deja el archivo de espera |
| B. Directo a R2 con URL prefirmada (PUT) | No pasa ningún byte por el servidor | Método `presign_put` en la puerta (ADR 28c decidió no presignar); CORS en el bucket (configuración de Cloudflare del fundador); un subidor propio en JS fuera de `rx.upload`; un paso «terminé» y limpieza de PUT abandonados; un PUT único tampoco se reanuda (eso pide multipart, más código) |
| **C. Por Reflex en trozos de 1 MiB al volumen; job en Postgres; `media-worker` transcodifica y sube a R2** | `rx.upload` de siempre (con barra de progreso), sin el archivo en memoria | Los bytes pasan por el servidor una vez (el tráfico no es el cuello hoy `[H]`); un servicio más |

Y dónde se procesa: en `creative-worker` (descartado: 512 MB compartidos con descargas de videos
pagados — un FFmpeg sin memoria tumbaría la generación — y su rol sigue `NOLOGIN`); en
`calendar-worker` (descartado: publica de verdad y ADR 41 prohíbe las esperas largas ahí); en un
evento de Reflex (descartado arriba).

**Decisión: C**, así:

- **Espera:** la subida se copia en trozos de 1 MiB a `uploads/{tenant}/gallery-staging/{upload_id}`,
  calculando el SHA-256 al vuelo; nunca `await upload.read()` entero. Las fotos siguen el camino
  corto (normalizar en el evento de Reflex, son segundos) y van a R2 igual.
- **Cola en Postgres** (sin almacén nuevo): tabla `gallery_jobs` con `tenant_id` + RLS NULLIF:
  `id`, `tenant_id`, `brand_id`, `kind` (`ingest`, `cut`), `status` (`queued`, `running`,
  `parts_saved`, `done`, `failed`), `idempotency_key` con `UNIQUE (tenant_id, idempotency_key)`,
  `staged_path`, `source_media_id`, `segments` (jsonb), `attempts` (máx. 3), `lease_until`
  (10 min), `last_error_code`, `result` (jsonb: ids de las partes, objetos y bytes borrados),
  `pipeline_version`, fechas. Reclamo con `FOR UPDATE SKIP LOCKED` dentro de `tenant_session`; los
  ids de negocio con jobs pendientes salen de `admin_session` (solo ids, como `whatsapp-worker`).
  Sin rol nuevo.
- **Claves de idempotencia:** subida = `ingest:{sha256 del archivo}` (subir dos veces el mismo
  archivo no crea dos medios); corte = `cut:{source_media_id}:{sha256 de los tramos que se quedan,
  ordenados}:{pipeline_version}`. Repetir o reintentar devuelve el mismo job y las mismas partes.
- **Servicio `media-worker`** (misma imagen `app`, worker CLI en bucle como los demás):
  `python -m qualify_api.catalog.media_worker --all-tenants`, `cpus: 1.0`, `mem_limit: 768m`,
  volumen `uploads`, **un job a la vez en todo el servidor**, FFmpeg con `-threads 2` bajo `nice`.
  `ingest`: `ffprobe` → H.264 + AAC 128 kbps (D1), vertical, hasta 1080×1920, primeros 60 s (D2),
  portada JPEG → `put_media` → fila → borra el archivo de espera. `cut`: §4.2 paso 3, desde el video
  ya normalizado (1080p), con recodificación para precisión de ≤ 0,1 s. El video de producto no
  cambia (D3).
- **Pantalla:** el estado se lee del job, así «Preparando tu video…» sobrevive a recargar la página
  y a un despliegue.
- **Costo:** R2 ≈ US$0,01–0,02 por negocio y mes (§6) y operaciones despreciables; < US$1 al mes
  para 50 negocios `[H]`. CPU y memoria salen del servidor que ya pagamos: **US$0 mientras el
  servidor alcance**.

**Aprobado por el fundador (2026-11-05, D8):** un contenedor más siempre encendido en el servidor
compartido con Pedidos — ~100 MB en reposo `[H]`, hasta 768 MB y 1 CPU mientras transcodifica.
Mismo lenguaje e imagen; era una decisión de infraestructura y el fundador la aprobó.

**Se reabre si** más del 10 % de las subidas de video fallan en un mes (redes móviles: entonces
subida reanudable por partes directa a R2, opción B con multipart); más de 200 videos al día o
espera p95 de la cola > 5 min; `media-worker` se queda sin memoria; o la memoria libre del servidor
baja de 500 MB con `media-worker` trabajando.

### 4.4 Riesgo encontrado aparte (no lo resuelve esta épica)

Los medios de **producto** viven en el volumen `uploads` sin respaldo: si el disco del servidor se
pierde, se pierden todas las fotos y clips de producto de todos los negocios (las piezas ya hechas
no, porque están en R2). Propuesta: ticket de `platform-engineer` para respaldar el volumen o
mudar los medios de producto a R2 con la misma puerta. Decide el fundador.

## 5. Historias

Orden de trabajo: CM-1 → CM-2 → CM-3 → CM-4 → CM-5 → CM-6 → CM-7 → CM-8. CM-3 puede ir en
paralelo con CM-2; CM-6 en paralelo con CM-5.

### CM-1 — Galería (servidor): guardar fotos y videos del negocio sin producto — m-24955918

- **Historia:** Como dueño de un local de comida, quiero guardar fotos y videos de mi local que
  no son de un producto, para tenerlos listos al crear publicaciones.
- **Área:** creative-engineer (módulo `catalog`, migración, `media-worker`) + platform-engineer
  (servicio `media-worker` en `deploy/docker-compose.prod.yml`, aprobado por el fundador el 2026-11-05, D8, §4.3).
  **P1 · L** (era M: suma la cola y el worker). **Depende de:** §4 (decidido 2026-11-05).
- **Criterios de aceptación** (ajustados a §4.1–§4.3 el 2026-11-05):
  - [ ] Migración reversible (`qualify-migration`) con las tablas `business_media` y
    `gallery_jobs` de §4.1/§4.3; `tenant_id` + `ENABLE`/`FORCE` RLS + política NULLIF en la
    misma revisión; grants a `qualify_app`/`qualify_admin` como `product_media`; los `CHECK` de
    §4.1; `UNIQUE (tenant_id, idempotency_key)` en `gallery_jobs`. `product_media` no cambia.
  - [ ] `object_key` y `poster_key` de `business_media` entran en `_PROTECTED_KEYS` de
    `connections/purge.py` (test de la purga).
  - [ ] Los archivos van a R2 bajo `t/{tenant}/gallery/{media_id}/` por `ObjectGate.put_media`;
    nada del negocio se escribe con `LocalMediaStore` salvo el archivo de espera.
  - [ ] `ObjectGate` gana `delete_gallery_media(tenant_id, media_id: UUID)` (enmienda de ADR 39):
    arma el prefijo desde el UUID, lista y borra, idempotente; `PURGEABLE_ROOTS` sigue siendo
    `("generated/",)`; el test que fija los métodos de la puerta se actualiza citando la enmienda;
    test de que no borra fuera de `gallery/{uuid}/` ni de otro negocio.
  - [ ] `CatalogService` gana `list_business_media`, `add_business_media`,
    `remove_business_media` (y la lectura de jobs pendientes) bajo `tenant_session`; un negocio
    nunca ve ni borra medios de otro (test con dos tenants).
  - [ ] **Subida en trozos:** el manejador de Reflex copia el archivo en trozos de 1 MiB a
    `uploads/{tenant}/gallery-staging/{upload_id}` con SHA-256 al vuelo (nunca
    `await upload.read()` entero); tope de **500 MB** en el selector (`max_size`) y en el
    servidor (corta al pasarlo); a lo sumo 3 videos esperando por negocio.
  - [ ] **Foto del negocio:** misma normalización que la de producto (JPEG para Instagram), en el
    evento de Reflex; va a R2.
  - [ ] **Video del negocio (D1, D2), en `media-worker`, nunca en el proceso de Reflex:** job
    `ingest` con clave `ingest:{sha256}` (subir dos veces el mismo archivo da un solo medio);
    H.264, vertical, hasta 1080×1920, **con sonido AAC 128 kbps**, primeros **60 s**; se guarda
    `has_audio` (sin pista de sonido queda `false`), `duration_ms` real y la portada; luego se
    borra el archivo de espera. El video de producto no cambia (≤ 15 s, sin sonido): test que lo
    fija.
  - [ ] `media-worker`: `python -m qualify_api.catalog.media_worker --all-tenants`; ids de negocio
    por `admin_session` (solo ids), todo lo demás por `tenant_session`; un job a la vez;
    reclamo `FOR UPDATE SKIP LOCKED` con `lease_until` de 10 min y 3 intentos; un job cortado por
    un despliegue se retoma solo (test).
  - [ ] **Quitar** un medio: lápida (`deleted_at`) → `delete_gallery_media` → borrar la fila; si R2
    falla, la lápida queda y el conciliador termina (§4.2 regla 4).
  - [ ] **Conciliador diario** de §4.2 regla 5. **Ningún objeto huérfano:** test con el
    almacenamiento falso que lista `t/{tenant}/gallery/` tras subida exitosa, subida cortada entre
    el PUT y la fila, quitar y quitar con R2 caído.
  - [ ] Si el original dura más de 60 s, el resultado del job lo indica para que la pantalla avise.
  - [ ] Tope por negocio: 60 medios `[H]` (filas vivas + jobs `ingest` pendientes), con
    `CatalogError` y su texto.
  - [ ] Ningún medio del negocio aparece en las lecturas de productos (Galería, menú de
    WhatsApp, selector de producto en `/create`): test.
  - [ ] **Medición** en la arquitectura de producción (arm64): tiempo y memoria máxima de
    transcodificar un video de 60 s en 4K HEVC con los parámetros elegidos, anotados en el PR; si
    pasa de 600 MB o de 3 min, bajar el preset o escalar antes de codificar.
  - [ ] `just ci-test` y `just test-db` verdes.
- **Fuera de alcance:** cortar (CM-3), elegir el tramo (CM-6), etiquetar o describir con IA.

### CM-2 — Galería (pantalla): «Fotos y videos de tu negocio» con subir, ver y quitar — m-24955919

- **Historia:** Como dueño de un local, quiero subir desde el teléfono fotos y videos de mi
  negocio en Galería, para mostrar mi local real en mis publicaciones.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-1; PR #483 mergeado (mismos
  archivos).
- **Criterios de aceptación (texto exacto):**
  - [ ] En la pantalla **Galería** (`/catalog`), una sección junto a tus productos (arriba) con título **«Fotos y videos de tu
    negocio»** y la línea **«Muestra tu local, tu equipo y cómo trabajas. Úsalas en tus
    publicaciones.»**
  - [ ] Botón **«Agregar fotos o videos»**; en el teléfono abre la cámara o las fotos del teléfono (el
    selector del sistema); acepta varias a la vez.
  - [ ] Mientras procesa un video: **«Preparando tu video…»**; el estado sale del job (CM-1), así
    sigue ahí al recargar la página o tras un despliegue (ajuste por §4.3).
  - [ ] Video de más de 500 MB (§4.3): **«Ese video pesa más de 500 MB. Prueba con uno más corto.»**
    (texto propuesto por el arquitecto; lo confirma `ux-designer`). Con 3 videos preparándose:
    **«Estamos preparando tus videos. Sube el siguiente en un momento.»** (propuesto, ídem).
  - [ ] La subida muestra su avance (`rx.upload` con progreso): un video de 400 MB por datos
    móviles tarda minutos.
  - [ ] Video de más de 60 s: **«Guardamos el primer minuto de tu video. Si quieres otra parte,
    puedes cortarlo aquí mismo.»**
  - [ ] Vacío: **«Todavía no tienes fotos ni videos de tu negocio. Sube algunas de tu local, tu
    equipo o tu trabajo.»**
  - [ ] Cada medio muestra su miniatura (los videos con su duración, p. ej. «0:42») y la acción
    **«Quitar»** con la confirmación **«¿Quitar este video de tu Galería? Las publicaciones que
    ya hiciste no cambian.»** (o «esta foto»).
  - [ ] Errores con los textos que ya existen (archivo ilegible, demasiado pesado, tope),
    sin códigos ni inglés (`qualify-copy-es`).
  - [ ] A 375 px de ancho: botones de 44 px, sin desplazamiento horizontal (`qualify-ux`);
    revisión local de `ux-designer` antes del PR.
  - [ ] `just ci-test` verde (tests de view-model de los textos y estados).
- **Fuera de alcance:** cortar (CM-4), elegir para una publicación (CM-5), ordenar a mano.

### CM-3 — Galería (servidor): cortar un video del negocio en partes y borrar lo quitado — m-24955923

- **Historia:** Como dueño de un local, quiero cortar mi video en partes y quitar lo que no
  sirve, para quedarme solo con los momentos buenos, cada uno listo para usar.
- **Área:** creative-engineer (corte con FFmpeg, ya aceptado en el stack, dentro de
  `media-worker`). **P1 · M.** **Depende de:** CM-1 (tablas, `media-worker`,
  `delete_gallery_media`) y §4.2 (decidido 2026-11-05).
- **Entrada:** el id del video del negocio y una lista ordenada de tramos `[inicio, fin]` (ms)
  marcados «se queda» o «se quita». Mínimo 3 s por parte que se queda `[H]` (lo que acepta
  Instagram en un video).
- **Criterios de aceptación** (ajustados a §4.2–§4.3 el 2026-11-05):
  - [ ] **Validación del pedido:** tramos dentro de `[0, duration_ms]`, ordenados y sin
    solaparse, cada parte que se queda ≥ 3 s, al menos una; si no, `CatalogError` con su texto.
  - [ ] **En segundo plano:** confirmar crea un job `cut` en `gallery_jobs` y responde enseguida;
    lo procesa `media-worker`, nunca la petición ni el proceso de Reflex.
  - [ ] **Precisión:** cada parte empieza y termina a ≤ 0,1 s del punto elegido (se
    recodifica desde el video ya normalizado; no se corta en el fotograma clave más cercano).
    Test con un video de prueba con contador de fotogramas, medido con `ffprobe`.
  - [ ] **Sonido:** cada parte conserva el sonido del original (D1), sincronizado.
  - [ ] **Lo quitado nunca se escribe:** solo se codifican los tramos que se quedan (§4.2 regla 2).
  - [ ] **Procedencia:** cada parte guardada lleva `source_media_id`, `cut_start_ms`,
    `cut_end_ms`, `job_id` y `pipeline_version` (`gallery-cut-v1`); la procedencia sobrevive al
    borrado del original.
  - [ ] **Idempotencia:** clave `cut:{source_media_id}:{sha256 de los tramos que se quedan,
    ordenados}:{pipeline_version}` con `UNIQUE`; el id de cada parte es `uuid5(job_id, índice)`.
    El mismo pedido repetido o reintentado da el mismo job y las mismas partes, sin duplicados ni
    proceso doble. Un corte distinto del mismo video mientras otro está en curso se rechaza.
  - [ ] **Orden seguro (§4.2 regla 3):** (1) job + original «en corte»; (2) partes a R2 en sus
    llaves deterministas; (3) **una transacción**: filas de las partes + lápida del original + job
    `parts_saved`; (4) `delete_gallery_media(original)`; (5) borrar la fila del original + job
    `done`. Falla antes de (3): el original queda intacto y visible; si el job falla definitivo,
    se borran las carpetas `uuid5(job_id, i)`. Falla entre (3) y (5): el reintento repite (4) y
    (5). **Ningún objeto huérfano:** test que lista `t/{tenant}/gallery/` en el almacenamiento
    falso tras éxito, fallo en cada paso y reintento.
  - [ ] **Cancelar** (no confirmar) no toca el original ni escribe nada: no hay job sin confirmar.
  - [ ] Si el original ya se usó en una pieza, la pieza no se rompe (usa su copia, CM-6).
  - [ ] Aislamiento: no se puede cortar un video de otro negocio (test).
  - [ ] `just ci-test` verde; el test de FFmpeg se salta con aviso si no hay binario.
- **Fuera de alcance:** recortar el cuadro, filtros, velocidad, música, volver a unir partes.

### CM-4 — Galería (pantalla): cortar un video con «Cortar aquí» y «Quitar esta parte» — m-24955924

- **Historia:** Como dueño de un local, quiero cortar mi video desde el teléfono mirando una
  línea de tiempo, para no necesitar otra aplicación.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-2, CM-3.
- **Flujo (una decisión por paso):** en un video del negocio, **«Cortar video»** → pantalla
  **«Corta tu video en partes»** con el video, la línea de tiempo y la línea de reproducción.
  1. Ayuda: **«Mueve la línea hasta donde quieres cortar y toca «Cortar aquí».»**
  2. **«Cortar aquí»** divide la parte en la que está la línea; las partes se ven numeradas en
     la línea de tiempo («Parte 1», «Parte 2»…).
  3. Tocar una parte la selecciona; **«Quitar esta parte»** pide **«¿Quitar esta parte? No se
     puede recuperar.»** con **«Quitar»** / **«Volver»**.
  4. **«Guardar partes»** pide **«Vamos a guardar N partes y borrar el video original. ¿Seguimos?»**
     con **«Guardar»** / **«Volver»**. Mientras `media-worker` corta: **«Cortando tu video…»**
     (propuesto por el arquitecto, §4.3; lo confirma `ux-designer`) — el dueño puede salir y
     volver. Al terminar: **«Listo: tu video quedó en N partes.»**
  5. **«Cancelar»** con cambios sin guardar pide **«¿Salir sin guardar? Tu video queda como
     estaba.»**; sin cambios, sale directo.
- **Criterios de aceptación:**
  - [ ] Los textos de arriba, exactos.
  - [ ] Parte de menos de 3 s: **«Cada parte debe durar al menos 3 segundos.»** y no deja
    guardar.
  - [ ] Si se quitaron todas las partes, «Guardar partes» no está disponible y se lee **«Deja al
    menos una parte o cancela.»**
  - [ ] Funciona con el dedo a 375 px (arrastrar la línea, botones de 44 px); se puede adelantar
    y retroceder por fotogramas con dos botones para afinar el punto.
  - [ ] Cada parte guardada aparece como un medio propio en «Fotos y videos de tu negocio»,
    en orden, y el original desaparece.
  - [ ] Revisión local de `ux-designer`; `just ci-test` verde.
- **Fuera de alcance:** las mismas que CM-3; cortar videos de producto.

### CM-5 — Galería (pantalla): elegir varias fotos y videos y «Crear publicación con estas» — m-24955926

- **Historia:** Como dueño de un local, quiero elegir varias fotos y videos de mi negocio y de mis
  productos, para crear una sola publicación con ellos.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-2.
- **Criterios de aceptación:**
  - [ ] Botón **«Elegir para una publicación»** en Galería; al tocarlo, las miniaturas se
    pueden marcar, en dos grupos: **«De tu negocio»** y **«De tus productos»** (las fotos y videos
    de cada producto, con su nombre).
  - [ ] Barra fija abajo con **«N elegidas»** y **«Crear publicación con estas»**; **«Cancelar»**
    sale sin elegir nada.
  - [ ] Hasta 10 (lo que acepta Instagram en un carrusel); la undécima: **«Puedes elegir hasta
    10.»**
  - [ ] El orden de la publicación es el orden en que el dueño los tocó (se ve un número en
    cada miniatura).
  - [ ] «Crear publicación con estas» abre `/create?medios=<lista>` (cada elemento dice si es
    del negocio o de un producto); el enlace de producto único (`?producto=`) sigue funcionando.
  - [ ] A 375 px, la barra no tapa el contenido; revisión local de `ux-designer`;
    `just ci-test` verde.
- **Fuera de alcance:** guardar la selección para después; elegir piezas ya hechas.

### CM-6 — Generador (servidor): crear una publicación con los medios elegidos — m-24955927

- **Historia:** Como dueño de un local, quiero que Qualify arme la publicación con las fotos y
  videos que elegí, tal cual, para mostrar mi negocio real.
- **Área:** creative-engineer. **P1 · L.** **Depende de:** CM-1 (y CM-3 para partes cortadas).
- **Propuesta:** formato por defecto **carrusel** (`ContentKind.CAROUSEL`, hoy rotulado «Galería» en el generador) con una fuente de
  diapositiva nueva «medio del catálogo» (`SlideSource`), una diapositiva por medio, en el orden
  elegido; con un solo medio, una publicación de imagen o de video. Claude escribe el texto con
  el contexto de la marca (sin mandar los archivos a un modelo).
- **Criterios de aceptación:**
  - [ ] Valida cada medio bajo RLS: uno de otro negocio, borrado o mal formado se descarta sin
    error (como `?producto=` hoy, m-24842972).
  - [ ] **Tramo (D2):** si el formato pide menos que la duración del video, Qualify elige un
    tramo con una regla determinista y documentada (primera versión: el tramo de la duración
    pedida que empieza en el segundo 0, o el siguiente si el primero es de menos de 3 s `[H]`); el
    tramo se guarda en la pieza. En el carrusel un video de hasta 60 s entra entero.
  - [ ] **Sonido (D1):** la pieza respeta lo que el dueño elige en `/create` (con o sin el
    sonido de sus videos); un video de producto siempre va sin sonido. Si el formato lleva voz
    generada, el sonido del video se apaga y la pantalla lo dice (CM-7).
  - [ ] **Copia propia:** los archivos que usa la pieza se copian a `generated/{draft_id}/`,
    así ADR 39 los borra con la pieza y quitar un medio en Galería no rompe la pieza.
  - [ ] **Procedencia:** la pieza guarda la lista de medios (tipo, id, tramo, sonido) y la
    versión del armado.
  - [ ] La pieza termina en «Por aprobar» (`/drafts`) y no se programa sola.
  - [ ] **Cupo (D5):** una publicación hecha solo con fotos y videos propios descuenta **una
    creación del mes**, igual que cualquier otra, y **no** descuenta segundos de video
    (m-24921139). Test que fija las dos cosas.
  - [ ] `just ci-test` verde.
- **Fuera de alcance:** elegir el tramo con IA (medición de `data-scientist-fde` antes);
  montaje de varios videos en un solo video vertical (Plantilla o Video por partes, siguiente
  paso); usar los medios del negocio como referencia de Seedance (manda datos del cliente a
  BytePlus).

### CM-7 — Generador (pantalla): `/create` abre con lo elegido y pregunta por el sonido — m-24955928

- **Historia:** Como dueño de un local, quiero ver lo que elegí al llegar a «Crear» y decidir si
  se oye el sonido de mis videos, para no repetir pasos.
- **Área:** reflex-ui-engineer. **P1 · M.** **Depende de:** CM-5, CM-6.
- **Criterios de aceptación:**
  - [ ] `/create?medios=…` salta la elección de producto y muestra las miniaturas elegidas en
    orden, con **«Cambiar»** que vuelve a Galería con la selección.
  - [ ] Si hay al menos un video del negocio con sonido: interruptor **«Usar el sonido de tus
    videos»**, que **empieza apagado** (D6).
  - [ ] Si el formato lleva voz: **«Esta publicación lleva voz, así que tus videos van sin
    sonido.»**
  - [ ] Si se descartó algún medio (borrado o de otro negocio): **«Uno de los medios que
    elegiste ya no está en tu Galería.»**
  - [ ] Al terminar, el mismo aviso que hoy y el enlace a «Por aprobar».
  - [ ] Usa el rótulo «Carrusel» que deja el PR #485 (D7); este ticket no cambia ese texto.
  - [ ] Revisión local de `ux-designer`; `just ci-test` verde (test del view-model con
    `?medios=` válido, ajeno y mal formado).
- **Fuera de alcance:** editar el orden dentro de `/create` (se cambia en Galería).

### CM-8 — Pruebas: de Galería a «Por aprobar» con fotos y videos del negocio (E2E) — m-24955929

- **Historia:** Como equipo, queremos una prueba de punta a punta del camino completo, para no
  romperlo sin enterarnos.
- **Área:** reflex-ui-engineer (Playwright, `tests/e2e`, nicho locales de comida). **P2 · M.**
  **Depende de:** CM-1…CM-7.
- **Criterios de aceptación:**
  - [ ] El recorrido: subir una foto y un video de 20 s con sonido en «Fotos y videos de tu
    negocio» → cortar el video en 3 partes y quitar la del medio (confirmando) → elegir la foto,
    la parte 1 y una foto de producto → «Crear publicación con estas» → con sonido → la pieza
    aparece en «Por aprobar» con 3 diapositivas en ese orden.
  - [ ] Comprueba en el almacenamiento de prueba que el original y la parte quitada ya no
    están, y que la pieza tiene su copia.
  - [ ] Un segundo negocio no ve los medios del primero (ni en Galería ni por `?medios=`).
  - [ ] Ningún proveedor real pagado: generación de texto simulada.
  - [ ] Corre a 375 px de ancho.

## 6. Impacto en R2 (almacenamiento)

Cálculo `[H]` sobre parámetros del disco (`-crf 23 -preset veryfast`, tope 1080×1920) y el
precio público de R2 Standard (US$0,015 por GB al mes, `[S]`, no verificado hoy):

| Qué | Peso por archivo | Comentario |
|---|---|---|
| Video de producto, 15 s, sin sonido (hoy) | ~6–11 MB | Sin cambio |
| Video del negocio, 60 s, con sonido | ~22–45 MB (video 3–6 Mbps + AAC 128 kbps ≈ 1 MB) | 4× la duración de un video de producto |
| Partes cortadas | suman menos que el original | El original y lo quitado se borran (D4): no hay doble guardado |
| Copia en la pieza (CM-6) | lo usado | Se borra con la pieza a los 90 días (ADR 39) |

Un negocio con 20 videos de 60 s guarda ~0,45–0,9 GB → **~US$0,01–0,02 al mes** `[H]`. No mueve
el costo por negocio; lo que sí pesa es la **subida** (100–400 MB por video en el teléfono) y la
**CPU** de transcodificar un minuto en el servidor compartido: por eso la decisión §4.3 (tope de
500 MB, subida en trozos, `media-worker` con 1 CPU y un job a la vez). Los medios del negocio van a
R2; los de producto siguen en el volumen local del servidor (§4.4).

## 7. Prioridad y razón

1. **CM-1 + CM-2** — el fundador no puede guardar hoy los videos de su local; es la base de todo.
2. **CM-5 + CM-6 + CM-7** — el camino que pidió: elegir en Galería y que la pieza llegue a «Por
   aprobar».
3. **CM-3 + CM-4** — cortar y quitar (pedido explícito, va después de la subida).
4. **CM-8** — cierra la épica.

Ninguna historia toca la revisión de la app de Meta: es Instagram/Facebook con lo que ya está
aprobado.

## 8. Respuestas del fundador (2026-11-05) `[FIRMADO]`

Las tres preguntas que quedaban abiertas, respondidas (D5–D7 en §2):

- **P1 → sí cuenta.** Una publicación armada solo con tus fotos y videos de Galería cuenta como
  una creación del mes, igual que cualquier otra. No descuenta segundos de video (no se genera
  video).
- **P2 → apagado.** El interruptor «Usar el sonido de tus videos» empieza apagado; el dueño lo
  enciende si quiere.
- **P3 → «Carrusel».** El formato carrusel del generador se rotula «Carrusel» (solo el texto;
  `ContentKind.CAROUSEL` no cambia). Se hace en el PR #485, fuera de esta épica.

Además: `media-worker` aprobado (D8) y la barra inferior del teléfono no cambia (D9).

## 9. Tickets

| Id | Ticket | Área |
|---|---|---|
| Épica | m-24955913 | — |
| CM-1 | m-24955918 | creative-engineer |
| CM-2 | m-24955919 | reflex-ui-engineer |
| CM-3 | m-24955923 | creative-engineer |
| CM-4 | m-24955924 | reflex-ui-engineer |
| CM-5 | m-24955926 | reflex-ui-engineer |
| CM-6 | m-24955927 | creative-engineer |
| CM-7 | m-24955928 | reflex-ui-engineer |
| CM-8 | m-24955929 | reflex-ui-engineer |
