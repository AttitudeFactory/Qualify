# Sprint-state — sesión PO Sprint 3 (Meta publishing + inbox), 2026-07-31

Lead: `po-sprint3` (po-lead). Equipo: product-owner, principal-architect, data-scientist-fde.
Objetivo: backlog de Sprint 3 listo para `/team-dev`, en `docs/backlog-sprint3-meta-publishing-inbox.md`.

**Nada de esto está commiteado ni firmado. Ningún item marcado APROBADO.**

---

## 1. Encuadre recibido del team-lead (verificado en disco por el lead hoy)

Objetivo del fundador: **cablear publicación y bandeja de Meta sobre la conexión de cuenta conectada.**

### Estado verificado contra el filesystem (por `po-sprint3`, 2026-07-31)

| Hecho | Evidencia en disco |
|---|---|
| La API expone **solo dos rutas** | `packages/api/src/qualify_api/http/` contiene únicamente `app.py` y `connections_routes.py` |
| `publishing/client.py` existe y **no está cableado a ninguna ruta** | `packages/api/src/qualify_api/publishing/` = `__init__.py` + `client.py` (15 KB). No hay `routes.py`, `service.py`, `repository.py`, `models.py` |
| El cliente es **vídeo-only, subida resumable** | `publishing/__init__.py` docstring: "Video only: reel, video story and carousel video, via the resumable byte upload to `rupload.facebook.com` (ADR 28a). Image publishing needs a public HTTP surface and is deferred to QUA-68" |
| Superficie del cliente | `PublishClient` (Protocol), `HttpPublishClient`, `ContainerStatus`, `ResumableContainer`, `UploadOutcome`, `PublishError`, `MEDIA_TYPE_REELS/STORIES/VIDEO`, `CONTAINER_POLL_INTERVAL_SECONDS`, `CONTAINER_POLL_CEILING_SECONDS`, `UPLOAD_CHUNK_BYTES` |
| **El DDL ya existe** — el hueco es la capa de servicio, no el esquema | `migrations/postgres/versions/0003_publishing.py`, `0004_inbox.py` (commiteadas en `27e1f5c`) |
| Tablas de `0003_publishing` | **`publish_attempts`** (`0003_publishing.py:72`) — tenant_id, connection_id, scheduled_post_id, idempotency_key, creation_id, media_product_type, adapter_version, status, platform_error_code, retriable, raw_response_r2_key, published_media_id, settled_at — y **`scheduled_posts`** (`:146`) — media_object_key, media_content_type, media_product_type, caption, thumb_offset, scheduled_for, scheduled_tz, status |
| Tablas de `0004_inbox` | **`threads`** (`0004_inbox.py:57`) — channel, external_thread_id, status, last_message_at, last_inbound_at — y **`messages`** (`:106`) — thread_id, external_message_id, direction, author_external_id, author_username, text, posted_at, raw_payload_r2_key, shape_version |

> ⚠ **CORRECCIÓN DEL LEAD (2026-07-31), detectada por el architect.** Las dos filas de arriba tenían **tres de los cuatro nombres de tabla mal**: escribí `publishing_attempts`, `inbox_threads` e `inbox_messages` infiriéndolos del nombre del fichero de migración en vez de leer el argumento de `op.create_table`. Los nombres reales, verificados con `grep -n 'op.create_table(' -A1`, son **`publish_attempts`**, **`threads`** y **`messages`** — y son los que usan los GRANT y las políticas RLS. Ya corregidos arriba. Cualquier criterio de aceptación escrito contra los nombres antiguos apunta a tablas que no existen.
| No hay ninguna conexión real en base | Filas de `social_connections` son sintéticas de test; el flujo real muere en `link_required` (pages=1, pages_with_ig=0) |
| Tenant dev es un **global de proceso** | `packages/shared/src/qualify_shared/dev.py` — la API no puede seleccionar tenant desde fuera; `start` devuelve 409. Deuda real. |

### Hallazgos de la sesión de hoy que condicionan el diseño

1. **Facebook Login for Business exige `config_id`.** Sin él, el diálogo salta al callback sin conceder activos y `/me/accounts` devuelve 0 páginas. Nuestro `authorization_url` manda `scope=`. Config creada: `config_id=1905711854132281` (token de usuario). → historia obligatoria.
2. **La grafía correcta es `instagram_content_publish`** (no `..._publishing`, que es errata de Meta). Verificado dos veces contra el endpoint de autorización. No hardcodear desde documentación.
3. **App Mode es global a la app.** En Development Mode los posts con media solo los ven titulares de rol. Reel público real exige Live + probablemente Business Verification. **V-TP-2 / A5-5 sigue abierta y bloquea la premisa de ADR 21.** El sprint asume Development Mode y no promete visibilidad pública.
4. **Precondición dura de ADR 25** (Página administrada con IG vinculada) ya está enforced con dos desenlaces (`page_access_required` vs `link_required`). Funciona. No tocar.

### Restricciones duras

- **TikTok publicación BLOQUEADA** por ADR 21 (firmada). Fuera del sprint por completo.
- **Respuestas autónomas fuera, permanentemente.** ~65% precisión. Solo asistidas (borrador + aprobación humana).
- **Inbox de un solo canal**, no unificado cross-canal (Fase 6).
- **ADR 29 `[PROPUESTO]`, sin firmar.** BISU / Tech Provider **no entra**. Config activa = token de usuario. Historias dependientes → parking lot con la dependencia declarada.
- **§3.a.ii Platform Terms nombra "housing"** entre las eligibility determinations prohibidas; cliente uno es inmobiliaria. Toda historia que puntúe personas lleva esa bandera. Ver `docs/integracion-cuentas-conectadas-meta.md` §8.3.3.
- **Cinco huecos de superficie** exigidos por Platform Terms y no cumplidos (política de privacidad, endpoint de borrado/deauthorize, política de retención, canal de vulnerabilidades, ToS con cláusula §5.b.ii.4.a). Vinculan **cuando el primer agente de cliente uno use el producto**, no en App Review. → merecen historias. Ver §8.3.2.

---

## 2. Reparto de tareas y propiedad de ficheros

| Agente | Escribe en | No toca |
|---|---|---|
| product-owner | `docs/backlog-sprint3-meta-publishing-inbox.md` | todo lo demás |
| principal-architect | `docs/arquitectura.md` (solo si una decisión cuaja en ADR), `.claude/sprint-state-2026-07-31-po-sprint3.md` (append) | el backlog |
| data-scientist-fde | nada en `docs/`; append a este sprint-state | el backlog |
| po-sprint3 (lead) | este fichero, `.claude/compass-sage/ledger.md` | el backlog |

---

## 3. Bitácora de la sesión

(las entradas se añaden abajo conforme ocurren)

### 2026-07-31 — arranque
Lead verificó el estado de disco de la tabla de arriba antes de repartir. Equipo lanzado.

## Findings recorded by agents (append-only)

### [2026-07-31 01:11] product-owner — CORRECCIÓN: los nombres de tabla del sprint-state §1 son inexactos

Verificado leyendo las migraciones, no los docs. La tabla del encuadre dice `publishing_attempts`, `inbox_threads`, `inbox_messages`. Los nombres REALES en el DDL aplicado son:
- `migrations/postgres/versions/0003_publishing.py:71` -> tabla **`publish_attempts`** (no `publishing_attempts`)
- `0004_inbox.py:56` -> tabla **`threads`** (no `inbox_threads`)
- `0004_inbox.py:105` -> tabla **`messages`** (no `inbox_messages`)
Cualquier historia, consulta o repositorio escrito contra los nombres del sprint-state fallará. El backlog usa los nombres reales.

Además, columnas que el encuadre omite y son de diseño (no cosméticas):
- `publish_attempts` tiene `retriable` (bool nullable), `started_at`, trigger `publish_attempts_settle_once` que hace IRREVERSIBLE cualquier fila con `settled_at IS NOT NULL` (RAISE EXCEPTION, ERRCODE check_violation), y CHECK `(settled_at IS NULL) = (status NOT IN ('published','failed'))`. El servicio debe respetar ambos o los tests de DB explotan.
- `threads` ya trae `assigned_agent_id` nullable (FK a users) y `last_inbound_at` separado de `last_message_at` (condición B2: la ventana de 24h deriva de last_inbound_at, NUNCA de last_message_at). NO existe columna `window_expires_at`, es deliberado.
- `messages` NO tiene `author_*` no-nulo: `author_external_id`/`author_username` son nullable por REQUIRES_PERMISSION (`instagram_manage_comments`), y `posted_at` es nullable por IF_REQUESTED. El orden cae a `ingested_at`.

### [2026-07-31 01:13] data-scientist-fde — AUDITORIA DEL 65 %: no es una medicion, y se ha extrapolado de la tarea equivocada

**Origen real, verificado leyendo el fichero:** `packages/models/NOTES_manychat_activation_layer.md` §2.2, tabla en la linea 148. NO es `NOTES_pain_signal_feasibility.md`.

**Que es realmente el 65 %:** una precision calculada con Bayes, no medida. La formula esta escrita en el propio fichero (linea 153): `Precision = TPR*pi / (TPR*pi + FPR*(1-pi))`, con **TPR 0,85 / FPR 0,05** — que el autor introduce como *"a reasonable zero-shot NLI operating point"*, es decir un punto de operacion **supuesto**, nunca medido — y **pi ~= 10 %**, que el propio fichero califica de *"a stated modelling assumption, not a measurement"*. El fichero remata: *"It is the **ratio between rows**, not the absolute, that carries the argument."* El autor sabia que el numero absoluto no era el argumento; la cadena de citas posteriores se quedo con el absoluto y tiro el aviso.

**Sobre que tarea se midio:** sobre ninguna, y sobre la tarea equivocada. El 65 % describe la **precision de un detector de intencion** (clasificador zero-shot NLI: "este mensaje lleva la intencion X"). NO describe la calidad de un texto generado. En este repo **no existe ni una sola medicion de calidad de borrador de respuesta**, en ningun idioma, sobre ningun conjunto.

**Veredicto: "65 % de precision = 1 de cada 3 borradores mal" es una extrapolacion, y falla dos veces.**
1. **Cambio de tarea.** Precision de un clasificador != tasa de acierto de un generador. Son metricas de objetos distintos. Un FP del disparador significa *"se ofrecio un borrador para un mensaje que no tenia esa intencion"*, no *"se genero un texto incorrecto"*.
2. **Cambio de modo de fallo.** En modo asistido el FP del disparador es **el fallo barato por construccion**: el humano ve un borrador que no aplica y lo descarta. El coste es un segundo de atencion, no un incidente. La cifra que se cita como prueba de que el modo autonomo es inviable describe, literalmente, el error que el modo asistido ya absorbe.

**La conclusion (autonomas fuera, permanentemente) SIGUE SIENDO CORRECTA — pero no por este numero.** Se sostiene sobre tres bases que si aguantan, y que recomiendo que sean las citadas:
- **(a) Ausencia total de evidencia.** Cero mediciones de calidad de borrador sobre DMs en espanol en este repo. Enviar sin aprobacion humana sobre evidencia nula es injustificable con independencia de que numero se cite.
- **(b) Asimetria irreversible del coste del error.** Un envio autonomo equivocado es la marca hablando, es irrecuperable y es capturable en pantalla. Ya esta argumentado en `backlog-crm-workflows.md` §4.6 (W4-Q6) y no depende de ninguna cifra.
- **(c) Vertical regulada.** Cliente uno es inmobiliaria: un envio autonomo que afirme algo sobre disponibilidad o cualificacion lo responde el brokerage (Fair Housing), y Platform Terms §3.a.ii nombra "housing". Esta es **mas fuerte** que el 65 % y hoy aparece como argumento secundario.

**Riesgo concreto de dejar el 65 % como esta:** es un numero falsable pegado a una regla declarada *permanente*. Si manana alguien mide una tasa de aceptacion de borradores del 85 % sobre DMs reales — perfectamente posible, porque es **otra metrica de otra tarea** — los docs invitan a reabrir una decision que no deberia depender de ese numero. La regla es mas robusta sin la cifra que con ella.

**Propuesta de correccion (no la aplico yo, no soy dueno de esos ficheros):** mantener el ruling intacto; reescribir su fundamento como (a)+(b)+(c); degradar el 65 % a lo que es — un calculo bayesiano ilustrativo **sobre el disparador**, con TPR/FPR/pi supuestos declarados en linea. Ficheros afectados: `CLAUDE.md:226`, `docs/arquitectura.md:288` (ADR 21) y `:877`, `docs/integracion-cuentas-conectadas-meta.md:445,470,556`, `docs/backlog-crm-workflows.md:569,571,861`, `docs/registro-validacion-features.md:130`. La correccion es del architect (ADR 21) y del PO (backlog); yo solo aporto el hallazgo.

### [2026-07-31 01:13] principal-architect — Ruta crítica: (a) scheduling FUERA, (b) object store real pero inconstruible, (c) bandeja sin scheduler

**Las tres dependencias no declaradas que el PO necesita para dimensionar. Verificado contra disco hoy, no contra docs.**

---

### (a) Programación diferida (`scheduled_posts`) — **FUERA DE SPRINT**. Veredicto: no pasa.

Evidencia de disco:
- `grep -rl celery` sobre `*.py` / `*.toml` / `*.yml` en todo el repo (excluyendo `.venv`): **cero coincidencias**. No hay Celery declarado, ni importado, ni configurado, en ningún sitio.
- `docker-compose.yml` expone exactamente dos servicios: `postgres` y `redis`. No hay worker, no hay beat, no hay ClickHouse.
- `justfile` no tiene ninguna receta de worker (`dev` = `up` + `migrate` + `seed`).
- `packages/pipeline/` **no existe**.

Conclusión: `migrations/postgres/versions/0003_publishing.py` crea `scheduled_posts` con `scheduled_for` y `scheduled_tz`, pero **no existe ningún proceso capaz de despertarse a esa hora**. Construir la programación diferida en Sprint 3 significa introducir Celery + Beat + un servicio worker en compose + supervisión — es decir, **arrancar Fase 1 Parte 3 dentro de un sprint de publicación**. Eso no es una historia, es un sprint entero, y encima es el camino crítico de otra cosa (el pipeline de ingesta).

**Recomendación al PO:** el sprint entrega **publicación inmediata (publish-now)** sobre `publish_attempts`. `scheduled_posts` se queda como DDL aplicada sin consumidor — lo cual es correcto y no es deuda: la tabla ya existe, la historia de scheduling la rellenará después sin migración nueva. Si el fundador quiere "programar", lo máximo que cabe sin Celery es **escribir la fila `scheduled_posts` en estado `pending` y un endpoint de disparo manual** (`POST /scheduled-posts/{id}/run`), que es honesto: la UI puede decir "programado" pero alguien tiene que apretar. Yo prefiero no ofrecerlo: promete un reloj que no existe.

---

### (b) `packages/shared/src/qualify_shared/objects/` — **cliente real y bien diseñado, pero HOY INCONSTRUIBLE**. Veredicto: pasa con condición.

Lo que sí es real (leído entero, no inferido):
- `gate.py` — `ObjectStore` (Protocol), `ObjectGate` con `put_media` / `open_object`, tope duro `MAX_MEDIA_BYTES = 300 MiB`, `ObjectSizeExceeded`, `UnsizedStream`, medición de longitud sin asumir posición 0. `presign_get` ausente **por diseño** (ADR 28b: la rama imagen se difiere a QUA-68).
- `keys.py` — `tenant_prefix()`, `media_key(tenant_id, connection_id, media_id)`, `require_tenant_prefix()` que además rechaza `..`. El prefijo `t/{tenant_id}/` es el mismo espacio que ya emite `qualify_scraper` (ADR 22/24). Esto es el análogo RLS del plano de objetos y está bien hecho.
- `s3.py` — `R2ObjectStore` sobre `put_object` (no `upload_fileobj`, deliberadamente: nada de multipart).
- `config.py` — `R2Settings.from_env()`, cuatro variables **obligatorias sin fallback** (`QUALIFY_R2_ENDPOINT_URL`, `QUALIFY_R2_ACCESS_KEY_ID`, `QUALIFY_R2_SECRET_ACCESS_KEY`, `QUALIFY_R2_BUCKET`), `__repr__` que redacta el secreto.

**Los dos bloqueos, ambos verificados:**
1. **`boto3` no está declarado en ninguna parte.** `grep -rn boto3` sobre `*.toml` y `*.lock`: **cero coincidencias**. `packages/shared/pyproject.toml` declara sólo `pydantic`, `sqlalchemy`, `psycopg`. El propio docstring de `s3.py` lo admite y explica por qué (declararlo obliga a `uv sync`, la operación que corrompe el venv compartido). Es decir: **`R2ObjectStore` no se puede instanciar en este workspace hoy**. Todo lo que hay verde está probado contra un doble en memoria.
2. **No hay bucket R2 configurado.** `.env` en la raíz contiene exactamente cuatro variables, todas de Meta (`QUALIFY_META_APP_ID`, `_REDIRECT_URI`, `_SCOPES`, `_APP_SECRET`). **Ninguna `QUALIFY_R2_*`.** No hay evidencia en disco de que exista una cuenta R2 ni un bucket aprovisionado.

**Impacto para el PO:** el gate no es un esqueleto — es código terminado. Pero entre él y un byte subido a Meta faltan **dos tareas de infraestructura que no son código de producto**: declarar `boto3` (con el ritual `rm -rf .venv && uv sync --group ml` que documenta CLAUDE.md) y aprovisionar el bucket + credenciales. **Ambas son precondición del primer publish real y deben ser historias explícitas, no supuestos.** Ninguna cabe como "detalle de implementación" dentro de otra historia.

---

### (c) Bandeja poll-first — **NO necesita scheduler; un pull manual basta, y además es lo único honesto**. Veredicto: pasa, con el alcance recortado.

Dos hechos de disco lo deciden, ambos en `packages/shared/src/qualify_shared/social/ig_shapes.py`:

1. **Los webhooks son inalcanzables para cliente cero.** `UNCOVERED_SURFACES` incluye `webhook_payloads`, motivo: Standard Access sólo permite interactuar con personas que tienen un rol en la app; `unblocked_by = "Business Verification + Advanced Access"`. Con webhooks fuera, **poll-first no es una preferencia de diseño, es la única opción**.
2. **La incrementalidad por tiempo no existe.** `COMMENT_LIMITS`: `max_per_query=50`, `returns_top_level_only=True`, **`filterable_by_timestamp=False`**. `INCREMENTAL_POLLING_NOTE` lo dice explícitamente: no hay cursor `since`, la de-duplicación tiene que ser **por id de comentario**, y un comentario nuevo a mitad de paginación desplaza la ventana.

Como el poll no puede ser incremental por tiempo, **la frecuencia del poll no compra frescura de forma proporcional** — compra riesgo de agotar el presupuesto de 200 llamadas/hora del Development Mode. Un `POST /inbox/sync` (o un botón "Actualizar" en la UI) da exactamente la misma corrección de datos que un beat cada 5 minutos, sin introducir Celery.

**Recomendación al PO:** endpoint de pull manual, disparado por la UI, con de-duplicación por `external_message_id` (la migración ya tiene `UniqueConstraint("connection_id", "external_message_id", name="uq_message_external_id")` — el upsert idempotente ya está soportado por el esquema). Nada de scheduler en este sprint. Cuando llegue Celery (Parte 3), el mismo servicio se envuelve en una tarea sin reescribir nada.

### [2026-07-31 01:14] principal-architect — Correcciones al §1: nombres de tabla erróneos (4/4) y la bandeja es SOLO comentarios (DM inalcanzable)

Dos correcciones a la tabla "Estado verificado contra el filesystem" del §1 de este mismo fichero. **El PO debe escribir criterios de aceptación contra estos nombres, no contra los de la tabla**, o los tests nombrarán tablas que no existen.

### 1. Los nombres de tabla del §1 están mal en cuatro de cuatro casos

Verificado con `grep -A1 "op.create_table("` sobre las dos migraciones:

| §1 dice | La migración crea realmente | Fichero:línea |
|---|---|---|
| `publishing_attempts` | **`publish_attempts`** | `0003_publishing.py:72` |
| `scheduled_posts` | `scheduled_posts` ✓ (único correcto) | `0003_publishing.py:146` |
| `inbox_threads` | **`threads`** | `0004_inbox.py:57` |
| `inbox_messages` | **`messages`** | `0004_inbox.py:106` |

No es cosmético: los `GRANT` de la migración son sobre `publish_attempts`, `threads`, `messages`, y las políticas RLS también. Una historia que diga "insertar en `inbox_threads`" no compila.

Observación de diseño, no defecto: `threads` y `messages` son nombres **genéricos** en un esquema Postgres compartido con `social_connections`, `brands`, `tenants`. Sobrevive porque hoy sólo hay un canal, pero es exactamente el nombre que colisiona cuando llegue el inbox cross-canal de Fase 6. **No lo cambio ahora** — renombrar una tabla ya migrada por estética es peor que convivir con el nombre, y ADR 27/R8a permite editar migraciones en sitio sólo porque nada está desplegado. Lo dejo anotado como riesgo asumido.

### 2. La bandeja de este sprint es **sólo comentarios**. DM no es alcanzable, y no por falta de trabajo.

`0004_inbox.py:96` impone `CheckConstraint("channel IN ('comment','dm')")`, así que el esquema admite `dm`. **La API de Meta no.** `packages/shared/src/qualify_shared/social/ig_shapes.py` — que es contrato verificado contra el corpus primario, con citas que un test comprueba que siguen resolviendo — fija dos exclusiones independientes:

- `UNCOVERED_SURFACES["direct_messages"]`: bajo la bifurcación de login firmada (ADR 25), una app con Standard Access **sólo puede interactuar con personas que tienen un rol en la app**. Un cliente real que manda un DM no tiene rol. `unblocked_by = "Business Verification + Advanced Access"` — la misma puerta que bloquea V-TP-2.
- `UNCOVERED_SURFACES["direct_messages_human_toggle"]`: **independientemente de cualquier scope de OAuth**, el titular de la cuenta tiene que activar a mano `Instagram > Ajustes > Mensajes > Controles > Herramientas conectadas > Permitir acceso a mensajes`. Es una acción humana dentro de la app de Instagram, **no concedible programáticamente**. Consecuencia para la UI: un poll de DM que devuelve vacío es **ambiguo** entre "no hay mensajes" y "el titular nunca activó el acceso", y una bandeja que pinte silencio como cero está mintiendo.

El docstring del propio módulo lo dice sin rodeos: la mitad de DM del ticket original se cortó a propósito porque *"fijar el tipo de una API que no podemos llamar sería un contrato sólo de nombre"*.

**Veredicto:** cualquier historia de DM en el backlog va al **parking lot**, con la dependencia declarada = Business Verification + Advanced Access (la misma de V-TP-2/A5-5), **más** una acción manual del titular que ni siquiera esa verificación desbloquea. El sprint entrega bandeja de **comentarios sobre media propia**. Si el fundador quiere DM, la respuesta no es "más ingeniería".

### 3. Corolario que el PO necesita para escribir la historia de sincronización

Otras exclusiones de `UNCOVERED_SURFACES` que cambian lo que "todos los comentarios" significa, y que por tanto deben aparecer como **límites conocidos** en los criterios de aceptación en vez de descubrirse como bugs:

- `returns_top_level_only=True` → **las respuestas a comentarios no llegan** por esta arista. Un hilo de bandeja tendrá el comentario raíz y nada más.
- `age_gated_media_comments` → no se devuelven en absoluto.
- `restricted_user_comments` → retenidos; **el recuento de esta arista no es el que el titular ve en la app**. No usarlo como métrica visible sin etiquetarlo.
- `live_video_comments` → sólo legibles mientras la emisión está en vivo; un poll posterior nunca los captura.
- `non_organic_comments` (comentarios en anuncios) → tipo distinto, requiere Marketing API. Fuera del alcance orgánico de ADR 21.
- `UNSUPPORTED_FIELDS` = `comment_type`, `mentioned_instagram_users` → Meta los declara no soportados en el nodo. No pedirlos.

### [2026-07-31 01:15] data-scientist-fde — BLOQUEANTE DE ENTORNO: el .venv compartido esta corrupto, packages/models no importa

**Sintoma verificado, no inferido:** `uv run --no-sync pytest packages/models/tests --collect-only -q` -> **8 errores de coleccion**, `83/90 tests collected`. `.venv/bin/python -c "import qualify_models"` -> `ModuleNotFoundError`. Afecta a `test_eval_harness`, `test_eval_metrics`, `test_eval_schema`, `test_eval_integration`, `test_crm_cost`, `test_fase0_cost` y 2 mas.

**Diagnostico:** es exactamente la corrupcion del editable-install que `CLAUDE.md` ya documenta. Los cuatro paquetes SIGUEN apareciendo en `uv pip list` como editables con ruta correcta, y los `.pth` en `site-packages` existen y apuntan a rutas que existen (`packages/models/src`, verificado con `os.path.exists` -> True). Pero `site.addpackage()` no los inyecta en `sys.path`: reproducido a mano, `sys.path` queda sin la entrada. torch y transformers SI estan instalados, luego el venv se sincronizo con `--group ml` en algun momento. **El sintoma es indistinguible de "no esta instalado" mirando `uv pip list` — por eso enganya.**

**Por que importa a este sprint:** cualquier criterio de aceptacion que diga "los tests de `packages/models` pasan" es **hoy inverificable**. Si un agente de `/team-dev` arranca sobre este venv, sus primeras dos horas se van en esto.

**Fix conocido y unico que ha funcionado (dos precedentes en `CLAUDE.md`):** `rm -rf .venv && uv sync --group ml`. **NO lo he ejecutado** — mis reglas prohiben sincronizar sin permiso del lead, y hay agentes trabajando en paralelo sobre el mismo venv. Requiere que el lead lo coordine cuando nadie mas este ejecutando nada.

**Sospecha sobre la causa, sin confirmar:** lo detecte inmediatamente despues de la primera invocacion de `.claude/skills/durable-findings/scripts/record_finding.py` via `uv run` (sin `--no-sync`), que imprimio `Uninstalled 2 packages / Installed 2 packages`. **No puedo afirmar causalidad** — no comprobe el venv antes. Pero el script se le pide a TODOS los agentes de la sesion y se invoca sin `--no-sync` en la documentacion de la skill. **Recomendacion barata y sin riesgo: invocarlo siempre como `uv run --no-sync .claude/skills/.../record_finding.py`.** El script solo usa stdlib (`argparse`, `datetime`, `sys`), no necesita resolver el workspace.

### [2026-07-31 01:17] principal-architect — Auditoría del hueco de publicación: faltan 8 capas, no 5 — y el sondeo no cabe en una petición HTTP

Auditoría del hueco entre `packages/api/src/qualify_api/publishing/client.py` y una ruta HTTP servible. El §2.1 del backlog enumera cinco carencias y las cinco son correctas; **faltan tres más, y una de ellas cambia la forma del servicio, no sólo su tamaño.**

### Las capas que faltan, en orden de dependencia

| # | Capa | Fichero que no existe | ¿Cabe en el sprint? |
|---|---|---|---|
| L1 | Modelos ORM de `publish_attempts` y `scheduled_posts` | `publishing/models.py` | Sí — espejo de `connections/models.py` |
| L2 | Repositorio: write-ahead, transición, reconciliación por `creation_id` | `publishing/repository.py` | Sí |
| L3 | Servicio: idempotencia, apertura del media, bucle de sondeo, liquidación | `publishing/service.py` | Sí, **si se acepta L6** |
| L4 | Composición: dos `AuthenticatedClient` (dos esquemas) + `ObjectGate` | `publishing/composition.py` | Sí |
| L5 | Rutas HTTP + `include_router` en `app.py` | `http/publishing_routes.py` | Sí |
| **L6** | **Ingreso del media a R2** — alguien tiene que llamar a `ObjectGate.put_media` | **no existe ni está nombrado en el backlog** | Sí, pero es historia propia |
| **L7** | **Ejecutor del sondeo** — 60 s × 5 min dentro de una petición HTTP | decisión de arquitectura, ver abajo | Sí, con el diseño de abajo |
| **L8** | Persistencia de `raw_response_r2_key` (provenance) | parte de L2/L3 | Sí, o se declara nulo a propósito |

### L6 — la dependencia no declarada que rompe la demo

`scheduled_posts.media_object_key` es `Text NOT NULL` y el gate exige que la clave viva bajo `t/{tenant_id}/`. **Pero en todo el repo no hay una sola llamada a `put_media`.** Ni ruta de subida, ni script, ni comando `just`. Grep: `ObjectGate` sólo aparece en `gate.py` y en sus tests.

Consecuencia: aunque L1–L5 se construyan perfectas, **no hay forma de meter un vídeo en el sistema**. La cadena entera del sprint termina en un bucket vacío. Esto tiene que ser una historia explícita: `POST /api/media` multipart → `ObjectGate.put_media` → devuelve el `media_object_key`. Es pequeña, pero **es la primera de la cadena, no la última**, y hoy no está en ningún sitio.

### L7 — EL PROBLEMA DE FORMA: el sondeo no cabe en una petición HTTP, y no hay ejecutor durable

`CONTAINER_POLL_INTERVAL_SECONDS = 60`, `CONTAINER_POLL_CEILING_SECONDS = 300`. Un `POST /publish` que haga el bucle completo **bloquea hasta cinco minutos**, y eso antes de contar la subida: 300 MiB por una subida doméstica son varios minutos más. Una petición HTTP de 8–10 minutos no es un detalle de tuning, viola la regla 4 del proyecto (*nada caro en la ruta de request*), y sin Celery **no hay dónde moverlo**.

Tres salidas, y sólo una es defendible sin Celery:

- **(i) `BackgroundTasks` de FastAPI. RECHAZADA.** Muere con el proceso y deja la fila en `processing` para siempre. Da la ilusión de asincronía con cero durabilidad — y el modo de fallo es el peor posible: la fila dice "en curso" cuando no hay nada en curso.
- **(ii) Celery. FUERA DE SPRINT** — ver el hallazgo (a) de más arriba.
- **(iii) SONDEO DIRIGIDO POR EL CLIENTE. RECOMENDADA.** Se parte la operación en llamadas cortas, cada una idempotente y cada una liquidando su propio paso en la base:
  - `POST /api/publishing/attempts` → write-ahead de `publish_attempts` (`status='pending'`, `idempotency_key`), crea contenedor, sube bytes, pasa a `processing`, **devuelve 202 + `attempt_id`**. Larga (la subida), pero acotada y sin espera pasiva.
  - `GET /api/publishing/attempts/{id}` → **una** llamada a `container_status`; si `FINISHED`, llama a `media_publish` y liquida; si terminal de error, liquida a `failed`. Devuelve el estado.
  - La UI (o el fundador con curl) repite el GET. **El intervalo de 60 s pasa de ser un `sleep` del servidor a ser cadencia del cliente**, que es exactamente lo que Meta recomienda y lo que el presupuesto de 200 llamadas/hora tolera.

  **Por qué es seguro sin ejecutor durable:** el registro write-ahead y el índice `ix_attempt_reconcile (tenant_id, creation_id)` ya existen precisamente para esto. Si el cliente abandona, la fila queda en `processing` con su `creation_id`, y **el mismo GET la reconcilia cuando alguien vuelva** — `ContainerStatus.PUBLISHED` es, en palabras del propio `client.py`, "cómo la reconciliación descubre que una publicación de la que dudábamos sí funcionó". No se pierde nada; sólo se difiere.

  **Coste honesto:** un intento abandonado que nadie vuelve a mirar se queda `processing` indefinidamente. Es aceptable a un tenant y con un operador humano; **deja de serlo en cuanto haya clientes**, y ahí entra Celery. Que quede escrito para que nadie lo lea como diseño final.

Esto merece **fila de ADR `[PROPUESTO]`** (no la firmo, no la escribo como aprobada):

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| El sondeo del contenedor lo dirige el cliente (una llamada de estado por petición HTTP), no un bucle en el servidor | `BackgroundTasks` de FastAPI / worker Celery | No existe ejecutor durable (cero Celery en el repo) y `BackgroundTasks` muere con el proceso dejando la fila en `processing` sin nada en curso. El registro write-ahead + `ix_attempt_reconcile` ya hacen la reconciliación posible, así que partir el bucle no pierde información: la difiere. Celery convertiría el sprint en Fase 1 Parte 3 |

### Dos invariantes de base que el servicio DEBE respetar, y que son fáciles de incumplir

1. **El trigger `publish_attempts_settle_once` lanza `check_violation` ante CUALQUIER `UPDATE` de una fila liquidada.** El repositorio no puede taparlo con un `WHERE settled_at IS NULL`: el trigger existe para que un segundo camino no lo evite. Lo correcto es **capturar `check_violation` y tratarlo como "ya liquidado" — el camino idempotente del reintento**, no como error 500. Criterio de aceptación obligatorio.
2. **`ck_attempt_settled_matches_status`**: `(settled_at IS NULL) = (status NOT IN ('published','failed'))`. Poner `status='published'` sin `settled_at` **revienta en la base**. Estado y sello se escriben en el mismo `UPDATE`, siempre.

### L8 — provenance

`publish_attempts.raw_response_r2_key` es nullable, así que la v1 puede dejarlo nulo. **Pero entonces la historia debe decirlo explícitamente**, porque la regla de provenance del proyecto es dura y un nulo silencioso se lee después como "se perdió". Si se rellena, añade una dependencia de R2 más en la ruta de publicación (además de la de leer el media). Mi recomendación: **rellenarlo desde el principio para las respuestas de `media_publish` y de fallo** — es una escritura pequeña y es la única traza que quedará de la primera llamada real a Meta, que es justo la que nadie querrá haber perdido.

### Veredicto de dimensionado, contra el presupuesto declarado del §0

El backlog estima "~18–20 items ejecutables" con cuatro roles. **Discrepo del método, no de los números.** L1→L2→L3→L4→L5 es una **cadena serial** sobre los mismos ficheros: no la paralelizan cuatro personas. La Épica A realista es **un rol trabajando en serie, más L6 y las precondiciones de infra en paralelo**. Sumando: L1–L8 + declarar `boto3` + aprovisionar R2 + `config_id` + deuda de tenant = **entre 9 y 11 items, y ésa ya es la capacidad real del sprint**. La Épica B (bandeja) sólo cabe si la Épica A se recorta, y no debe recortarse: sin publicación no hay producto que enseñar, que es el propio encuadre del §0.

### [2026-07-31 01:17] data-scientist-fde — CAPA DE IA DE LA BANDEJA: que es in-sprint (poco) y que no (casi todo)

`docs/backlog-crm-workflows.md` §4.5 lista seis cosas. Las separo por lo que cuesta construirlas, no por lo atractivas que son.

**A) Llamada a LLM por API — barato de construir, coste por mensaje:**
- **Generacion del borrador.** Una llamada. El propio §4.5 dice que la generacion pertenece al orquestador, no a la cascada. Correcto.

**B) Exige modelo propio, fine-tuning, embeddings o RAG — FUERA DE SPRINT, sin discusion:**
- **Disparador de intencion zero-shot NLI (`MoritzLaurer/bge-m3-zeroshot-v2.0`).** No esta comprometido, es una **propuesta de Fase 3**. 568M params, **jamas ejecutado en este repo**, latencia CPU sin medir (§4.5(6) lo declara como input abierto). Y arrastra un prerequisito que nadie ha escrito: **un taxon de etiquetas de intencion curado y no solapado**. Ese taxon es trabajo de producto, no de ingenieria, y no existe.
- **Retrieval / RAG.** No hay ningun modelo de embeddings comprometido en Fase 1 (`arquitectura.md` §4/§8.1: `bge-m3` es *propuesto*). Sin corpus indexado no hay nada que recuperar.
- **Sentimiento sobre DMs.** Ver hallazgo separado: el modelo comprometido no hace la tarea que la bandeja necesita.

**C) La puerta barata previa a generar (§4.5(5)).** Arquitectonicamente correcta y la suscribo como principio — pero **su justificacion economica no aplica a este sprint**. El calculo de `eval/conversation_cost.py` (119 % del ingreso por contacto) es sobre **la economia de precios de ManyChat**, no sobre la de Qualify: aqui hay dos tenants y ningun modelo de precios por contacto. A este volumen la puerta no ahorra nada. Lo que si hay que construir ahora es **el sitio donde encaja**, no la puerta.

---

**RECOMENDACION — una cosa, no un catalogo.**

**In-sprint: el bucle de aprobacion y el seam del proveedor de borradores. NO el generador.**

Razon: el sprint es fontaneria y **no existe ni un solo DM real en base**. El flujo muere en `link_required`, `messages` esta vacia, no hay corpus. **Construir un generador de borradores antes de que exista el primer mensaje real es construir contra evidencia cero** — y es precisamente lo que la auditoria del 65 % dice que no volvamos a hacer.

Lo que si es caro de retrofitear y por tanto debe entrar ahora:
1. **La maquina de estados de aprobacion** (`draft` -> `approved` -> `sent` / `discarded`), con `approved_by` y `approved_at`. `A1 §1.6` ya decia que el bucle humano se disena desde el dia uno; sigue siendo cierto y **es plomeria pura**, que es de lo que va este sprint.
2. **El seam `DraftProvider` typed**, con la misma forma que `SentimentProvider` en `packages/models/src/qualify_models/providers.py`. Dos implementaciones: un stub determinista (para tests, offline) y un hueco declarado para la llamada real. Provenance obligatoria en el resultado: `model_id` + `prompt_version`.
3. **La telemetria de aceptar / editar / descartar.** Esto NO es analitica de producto: **es el unico camino por el que este proyecto llegara a tener una medicion real de calidad de borrador**, que es exactamente lo que hoy no existe (ver auditoria del 65 %). Sin esa telemetria, dentro de tres sprints seguiremos citando una cifra calculada con Bayes en 2026-07.

El generador real es un dia de trabajo cuando haya corpus. El bucle de aprobacion sin telemetria es deuda permanente.

### [2026-07-31 01:18] principal-architect — Deuda del tenant global: la causa raíz es la ausencia de principal, no el global — salida mínima y su frontera exacta

### El diagnóstico real: el defecto no es que el tenant sea global

`packages/shared/src/qualify_shared/dev.py:32` es `_dev_tenant: UUID | None = None`, un global de módulo. El síntoma es el 409 de `connections_routes.py:72-74`. Pero **quitar el global no arregla nada por sí solo**: si el tenant pasa a venir de una cabecera, hemos convertido el `tenant_id` en un dato que el cliente elige — exactamente el bypass que `StartConnectRequest` documenta como intolerable (*"un tenant id aceptado de un cliente es un bypass de autorización con pasos extra"*).

**La causa raíz es que no hay autenticación, luego no hay principal del que derivar un tenant.** Cualquier arreglo que no introduzca una credencial sólo muda el bypass de sitio.

### Salida mínima viable

Cuatro piezas, ninguna toca RLS ni las puertas sancionadas:

1. **`Principal`** — dataclass congelada `(tenant_id: UUID, user_id: UUID)`. Es el tipo que la autenticación real producirá; el resto del código nunca vuelve a cambiar.
2. **Resolución por credencial opaca, desde el entorno, sin migración.** `QUALIFY_DEV_PRINCIPALS="<token>:<tenant_uuid>:<user_uuid>,..."`. El cliente presenta `Authorization: Bearer <token>` — **presenta una credencial, no un identificador**, que es toda la diferencia entre autenticar y aceptar lo que le digan.
   - **Descartada la tabla de tokens en Postgres (migración 0005).** Una tabla parece el principio de la autenticación de verdad e invita a construir encima; el mapa de entorno se borra de un tirón cuando llegue la real, no deja esquema que deshacer, y no añade una lectura a la ruta de request. Es deuda que se ve.
   - **Descartado un `ContextVar` alimentado por cabecera `X-Tenant-Id`.** Es el global con mejor higiene de hilos y **el mismo agujero de autorización**.
3. **Dependencia `current_principal()`** en un `http/deps.py` nuevo, con el mismo patrón que `get_connect_service`: default que lanza, sobrescribible en tests. **Devuelve 401, no 409.** El 409 de hoy miente: dice "conflicto de estado" cuando el hecho es "no estás autenticado", y esa mentira es la que hace que el fallo parezca un bug del servidor en vez de una credencial ausente.
4. **Las rutas toman `principal: Principal = Depends(current_principal)`** y pasan `principal.tenant_id` a los servicios. Los servicios no cambian: siguen llamando a `tenant_session(tenant_id)`.

**Coherencia con R7 y con las puertas: total, porque el arreglo vive POR ENCIMA de la puerta.** Nada del GUC, del `NULLIF`, del `set_config(..., is_local => true)` ni de las políticas se toca. `tenant_session` sigue siendo el único camino a datos de tenant; lo único que cambia es de dónde sale el UUID que se le pasa. `admin_session` y `credential_session` no se rozan.

**`qualify_shared.dev` sobrevive, con un solo consumidor legítimo:** la UI Reflex, que corre **en proceso, un operador, una sesión** — el caso para el que se escribió y donde un global es honesto. Lo que hay que impedir es que nazca un segundo consumidor HTTP. Recomiendo una línea en su docstring diciéndolo, y ninguna llamada nueva a `get_dev_tenant()` desde `http/`.

### Defecto adicional de la misma familia, hoy en el código

`StartConnectRequest` (`connections_routes.py:40-44`) omite `tenant_id` a propósito **pero declara `user_id: UUID` en el cuerpo**. Es la misma clase de bypass, menos visible: el cliente elige a quién se le atribuye la conexión, y ese `user_id` acaba en `connection_events` como actor. Con `Principal` en su sitio, `user_id` sale del principal y **desaparece del cuerpo**. La historia que arregla el tenant debe arreglar esto en la misma pasada o no habrá una segunda ocasión barata.

### ¿Precondición de todo, o puede ir en paralelo? — Respuesta precisa

**Ni una cosa ni la otra; la frontera es exacta y conviene no redondearla:**

- **NO es precondición de L1–L4** (modelos, repositorio, servicio, composición de publicación). Todas esas capas reciben `tenant_id` como argumento y se testean sin HTTP. Pueden empezar mañana sin esperar a nada.
- **SÍ es precondición dura de L5** (cualquier ruta HTTP nueva) **y de toda prueba empírica de extremo a extremo, incluida la del fundador con curl.** Hoy es literalmente imposible seleccionar tenant desde fuera del proceso.
- **Y es precondición barata que se encarece rápido:** cada ruta que se escriba contra `get_dev_tenant()` habrá que reescribirla después. Con dos rutas es trivial; con las seis u ocho que este sprint quiere añadir, deja de serlo.

**Recomendación de orden:** va **primera o segunda del sprint**, en paralelo con L1–L2, y **debe estar terminada antes de que se escriba la primera ruta de publicación**. No es "deuda que arreglamos si sobra tiempo" — es fundación, en el mismo sentido en que ADR 24 declaró fundación al `tenant_id`: el coste de arreglarla crece con cada consumidor que se le cuelga.

### [2026-07-31 01:18] data-scientist-fde — COSTE POR UNIDAD: ~$0,0013/borrador con Haiku; despreciable a este volumen, CERRADO

**Supuestos, todos explicitos y todos discutibles.**
- Forma del prompt tomada de `packages/models/src/qualify_models/eval/conversation_cost.py:77-81` (constantes ya en disco, no inventadas): sistema 300 tok + historial del hilo 400 tok + salida 120 tok. **Sin RAG** (no hay embeddings en Fase 1), luego los 3 chunks x 300 tok de conocimiento **no aplican**: total **700 tok entrada / 120 tok salida**.
- Precios verificados contra la tabla vigente de Anthropic (no de memoria): Haiku 4.5 $1/$5 por millon (entrada/salida) · Sonnet 5 $3/$15 lista, $2/$10 introductorio hasta 2026-08-31 · Opus 5 $5/$25.
- Volumen: **cliente cero** = dogfooding sobre cuentas propias, orden de 5-50 DMs/dia. **Cliente uno** = una inmobiliaria, un solo canal (IG), estimo 20-100 DMs entrantes/dia. Tomo **50 DMs/dia = 1.500/mes** como caso central y **500/dia = 15.000/mes** como techo generoso.

**Coste por borrador de respuesta (una llamada, sin RAG):**

| Modelo | $/borrador | 1.500/mes | 15.000/mes (10x) |
|---|---|---|---|
| Haiku 4.5 | **$0,0013** | **$1,95** | $19,50 |
| Sonnet 5 (intro) | $0,0026 | $3,90 | $39,00 |
| Sonnet 5 (lista) | $0,0039 | $5,85 | $58,50 |
| Opus 5 | $0,0065 | $9,75 | $97,50 |

**Coste por mensaje clasificado:**
- **Si la clasificacion la hace un encoder auto-hospedado** (robertuito o el NLI zero-shot) en el worker CPU ya provisionado: **coste marginal cero**. El gasto es el VPS fijo. Con el matiz de §4.5(6): NLI zero-shot ejecuta un forward pass **por par (texto, etiqueta)**, luego el computo escala con `mensajes x nº etiquetas`, no con mensajes. Es una restriccion de throughput, no de dolares.
- **Si la clasificacion la hace un LLM** (~500 tok entrada / 20 tok salida): Haiku 4.5 = **$0,0006/mensaje** -> **$0,90/mes** a 1.500 mensajes.

**VEREDICTO: el coste es despreciable a este volumen y lo cierro.**

El techo absoluto del escenario mas caro que se puede construir en este sprint — Opus 5 generando **todos** los borradores, sin puerta previa, a 10x el volumen estimado — es **~$98/mes**. El caso central realista con Haiku es **~$3/mes** contando clasificacion.

**Consecuencia para el backlog, y es la parte util:** ninguna historia de este sprint debe justificarse ni dimensionarse por ahorro de coste de inferencia, y **ninguna decision de diseno debe tomarse para abaratar la llamada al LLM**. A dos tenants, el coste de la capa de IA esta por debajo del ruido frente a cualquier otra linea (Zyte, el VPS, una hora de ingenieria). La puerta barata de §4.5(5) se construye **cuando exista un modelo de precios por contacto**, no ahora; construirla ahora es optimizacion prematura con justificacion importada de la economia de otro producto.

**Nota menor de mantenimiento:** `packages/models/src/qualify_models/eval/fase0_cost.py:29-31` cachea precios a 2026-06-24. He verificado que las tres filas que tiene (`claude-opus-4-8` 5/25, `claude-sonnet-5` 3/15, `claude-haiku-4-5` 1/5) **siguen siendo correctas**. Falta `claude-opus-5` (5/25, igual que 4.8) y no recoge el precio introductorio de Sonnet 5 ($2/$10 hasta 2026-08-31). No bloquea nada.

### [2026-07-31 01:19] data-scientist-fde — SENTIMIENTO EN LA BANDEJA: robertuito no aplica a DMs — cambia criterios de aceptacion

**Esto cambia criterios de aceptacion del product-owner. Por eso va a disco y no solo al lead.**

`messages.text` existe y es nullable (`0004_inbox.py:123`). **NO existe columna de sentimiento en el DDL** — verificado leyendo la migracion entera. El esquema no presupone sentimiento, y creo que hizo bien.

**Pregunta: ¿transfiere `pysentimiento/robertuito-sentiment-analysis` de comentario publico de TikTok a DM entrante?**

**Respuesta corta: la pregunta esta mal planteada, y por eso la respuesta importa.** El problema no es que robertuito pierda accuracy en DMs. Es que **resuelve una tarea que la bandeja no necesita.**

**1. El eje del modelo es ortogonal al valor del DM.** robertuito da polaridad de 3 clases (POS/NEG/NEU). El DM que vale dinero en una inmobiliaria es *"hola, sigue disponible el piso de Chamberi?"* — que es **NEU**. Y el DM que no vale nada — *"me encanta vuestro contenido!!"* — es **POS**. La polaridad esta anticorrelacionada con el valor de negocio en una bandeja transaccional. Un triaje ordenado por polaridad ordenaria la cola **al reves**.

**2. La distribucion de etiquetas colapsa.** En comentarios publicos POS/NEG son clases pobladas. En DMs entrantes a una marca la inmensa mayoria son consultas transaccionales, es decir **NEU**. Un clasificador de 3 clases sobre un corpus ~80 % NEU degenera a un predictor casi constante: la accuracy agregada sale alta y el contenido informativo es cercano a cero. **Un criterio de aceptacion tipo "accuracy >= X" sobre este stream se aprueba solo y no significa nada.**

**3. El desplazamiento de dominio es real pero secundario.** robertuito se entreno sobre tuits en espanol: emision publica, tercera persona, sin destinatario. Un DM es primera persona, con destinatario explicito, registro de servicio al cliente y a menudo con datos concretos (calle, precio, fecha). No es catastrofico — la longitud es comparable — pero **no hay ni una medicion**, ni un fixture de DM en este repo, ni corpus. Lo digo como argumento sobre la definicion de la tarea y la distribucion de etiquetas, **no como medicion**: no he podido ejecutar nada (el venv esta roto, ver hallazgo aparte, y no existen fixtures de DM).

**4. El unico uso legitimo de la polaridad que §4.5 identifica esta fuera de este sprint.** §4.5(4) dice: generar borradores **solo para polaridad positiva**, imitando a ManyChat. Esa puerta de seguridad aplica a **comentarios publicos**. Y W4-Q6 ya resolvio (`backlog-crm-workflows.md:630`) que van **DMs privados primero, y no esta cerca**.

**CONCLUSION: en un sprint de solo-DM, robertuito no tiene ningun trabajo que hacer.** No es que transfiera mal — es que la superficie donde servia (comentario publico) esta explicitamente diferida.

**Que recomiendo al product-owner:**
- **NO escribir una historia de sentimiento sobre `messages`** en este sprint. Ni columna, ni worker, ni criterio.
- Si aun asi entra por presion de alcance, **el criterio de aceptacion no puede ser accuracy agregada**. Tendria que ser, como minimo, **macro-F1 estratificado por longitud de mensaje y reportando la clase NEU por separado**, contra una baseline de mayoria — porque si el modelo no bate a "predice siempre NEU", no aporta nada. §4.5 ya pide estratificacion por longitud (`backlog-crm-workflows.md:619`); esto la endurece.
- Lo que la bandeja **si** necesita es **intencion**, no polaridad. Y la intencion no esta comprometida (es el hueco documentado de §4.5(1), Fase 3). Ver hallazgo de alcance: fuera de sprint.

**Efecto colateral positivo:** esto **descarga la B0-4/R6** (buscar sustituto de robertuito con licencia limpia) de la ruta critica de Sprint 3. Sigue siendo deuda real de Fase 1 para comentarios publicos, pero **no bloquea nada de la bandeja de DMs**, porque la bandeja de DMs no deberia usar polaridad.

### [2026-07-31 01:19] data-scientist-fde — BANDERA §3.a.ii / HOUSING: frontera tecnica entre priorizar y determinar elegibilidad

**Esto es una LECTURA DE RIESGO, no un dictamen legal.** No soy abogado y no lo presento como tal. `docs/integracion-cuentas-conectadas-meta.md` §8.3.3 ya hizo la lectura juridica y ya calibro su propia incertidumbre; **no la repito ni la contradigo**. Lo que aporto es la **frontera tecnica**: que propiedad concreta del codigo separa lo que cae dentro de lo que cae fuera, en forma verificable.

La clausula (§3.a.ii, literal, verificada en §8.3.3): *"Processing Platform Data to make eligibility determinations about people, including for **housing**..."*

**La frontera NO es "¿es un score?".** Es un compuesto de tres propiedades. Una historia queda marcada si cumple **las tres**; si falla cualquiera, esta fuera de mi lectura.

| Eje | Fuera (verde) | Dentro (marcado) |
|---|---|---|
| **1. Unidad de la prediccion** | El score es propiedad de un **texto**: `messages.id` o `threads.id`. "¿Este mensaje es una consulta de compra?" "¿Es spam?" "¿Es urgente?" | El score es propiedad de una **persona**: `author_external_id`. "¿Este contacto es buen comprador?" |
| **2. Que gobierna la salida** | **Permutacion**: reordena una cola que un humano trabaja entera. Ninguna fila desaparece. | **Filtro**: un umbral hace que a ciertas personas no se les conteste, no se les ensene una vivienda, o no se les vuelva a contactar. Filas desaparecen. |
| **3. Persistencia** | Transitorio: se calcula para ordenar la cola de hoy y no se guarda contra la persona. | Persistido en una tabla con forma de persona y reutilizado entre interacciones. Esto ademas toca **§3.a.v** (construccion de perfiles), que segun §8.3.3 "muerde antes". |

**Traduccion a reglas de codigo, verificables con un test estatico** — este repo ya tiene ese patron (`packages/shared/tests/test_object_store_sanctity.py`, `test_gate_coverage.py`), asi que es barato:

1. Ninguna columna de score/prioridad cuelga de una tabla con forma de persona, ni tiene `author_external_id` como clave. Los scores cuelgan de `messages` o `threads`.
2. Ningun score aparece en un `WHERE`/`HAVING` que **elimine** filas. Solo en `ORDER BY`. Toda fila puntuada sigue siendo visible en la UI, en alguna posicion.
3. Ningun score se persiste indexado por identidad de persona.

**El esquema ya empuja en esta direccion y conviene decirlo:** `0004_inbox.py:118-121` lleva un comentario explicito de que el IGSID **no es identidad portable** y de que **no debe unirse a ningun otro identificador de persona**. Mi regla 1 es la extension natural de esa decision, no una nueva.

**Y una restriccion que NO esta en §8.3.3 y que es especifica de la capa de IA de este sprint — es mi aportacion, y creo que es la parte que se escaparia:**

> **El prompt del generador de borradores recibe texto del hilo, nunca un atributo derivado de la persona.**

Si el prompt incluye *"este contacto parece comprador serio / presupuesto bajo / poco cualificado"*, entonces **el score existe, esta dentro del LLM, no esta registrado y no es auditable**. Se cumplirian formalmente las tres reglas de arriba (no hay columna, no hay WHERE, no hay persistencia) y aun asi el sistema estaria puntuando personas para decidir como se les trata en materia de vivienda — sin ninguna traza. **Un score no deja de ser un score porque viva en un prompt.** Esta regla es tan verificable como las otras: es una asercion sobre que campos se serializan al prompt, y se testea.

**Lo que necesita decision del fundador (no de ingenieria, y no mia):**
- **(a)** Si en el vertical inmobiliario se computa **alguna vez** un score a nivel de persona. §8.3.3 ya lo eleva como decision de alcance del fundador; yo solo anado que **si la respuesta es "no", conviene que sea una invariante enforced por test, no una intencion documentada** — porque la diferencia entre priorizar y filtrar es un `WHERE` de una linea que cualquiera anade sin mala fe.
- **(b)** Donde cae el **filtrado de spam**, que es el unico caso legitimo que elimina filas. Mi lectura: filtrar por **contenido del mensaje** no es una determinacion de elegibilidad sobre la persona; filtrar por **atributo del remitente** si lo parece. Pero la frontera hay que enunciarla, porque hoy no esta escrita en ningun sitio.
- **(c)** El punto de optica de §8.3.3 (una app llamada **Qualify**, que puntua personas, presentada a App Review para un cliente inmobiliario). No es mio y no lo toco.

### [2026-07-31 01:21] principal-architect — BLOQUEANTE NO DECLARADO: guardamos token de USUARIO y Meta exige token de PÁGINA para publicar y para leer comentarios (+ PPA, + conflicto ads_management)

> **Leer esto antes de dimensionar la épica A o la B. Bloquea las dos, no está en ninguna historia, y es barato AHORA y caro después.**

## 1. El token que guardamos no es el token que la publicación necesita

**Lo que Meta exige, en su propia tabla de requisitos, columna *Instagram API with Facebook Login* (que es la bifurcación firmada, ADR 25):**

- `reference/meta-instagram-platform/instagram-platform/content-publishing.md:30` → fila **Access Tokens** = **`Facebook Page access token`**.
- `reference/meta-instagram-platform/instagram-platform/comment-moderation.md:17` → fila **Access Tokens** = **`Facebook Page access token`**.

(La columna *Instagram Login* dice "Instagram User access token"; ésa no es nuestra rama.)

**Lo que el código guarda hoy:** el **token de usuario** de `/oauth/access_token`. Verificado línea a línea:

- `connections/service.py:223` — `ciphertext=self._encryptor.encrypt(grant.access_token)`, donde `grant` viene de `exchange_code` (`meta_oauth.py:179-190`), es decir el token de **usuario**.
- `meta_oauth.py:192-200` — `list_linked_pages` llama a `/me/accounts` con `fields="id,name,instagram_business_account{id,username}"`. **`access_token` NO está en la lista de campos.** Meta no devuelve el token por Página si no se pide, así que ni siquiera un parser tolerante podría recogerlo.
- `_parse_accounts_response` (`meta_oauth.py:99-124`) construye `LinkedPage(page_id, page_name, instagram_account_id, instagram_username)` — **no hay campo de token en la dataclass.**

**Consecuencia directa:** `HttpPublishClient.create_container` se autenticará con un token de usuario contra un endpoint que Meta documenta como de token de Página. **La primera llamada real de la épica A falla**, y falla con un error de plataforma que va a parecer un bug nuestro. Lo mismo para la épica B: `GET /<IG_MEDIA_ID>/comments` está bajo el mismo requisito.

**Es un hueco de la capa de conexión (C-04), no de la de publicación.** Ninguna historia del backlog lo cubre: A1 arregla el diálogo, A2 la grafía del scope, A5 asume que `CredentialResolver.client_for()` devuelve algo utilizable. Nadie ha comprobado **qué** devuelve.

### Salida propuesta (no la firmo; necesita revisión de custodia)

1. `list_linked_pages` añade `access_token` a `fields`. Cambio de una palabra.
2. `LinkedPage` gana `page_access_token: str | None`. **Se marca `[V]`**: no hemos observado la respuesta real.
3. El callback cifra y persiste **el token de Página de la Página elegida**, no el de usuario.
4. **Sin migración.** `oauth_credentials.token_type` es `text` libre — exactamente el argumento que ADR 29 (g) ya hizo para BISU. `token_type='page'` vs `'user'` es representable hoy.
5. **Preguntas abiertas que NO resuelvo por inferencia y que el pipeline debe cerrar en vivo:** (i) ¿hay que intercambiar antes el token de usuario corto por uno largo para que el de Página sea de larga duración? (ii) ¿se sigue necesitando el token de **usuario** para algo (`/me/permissions` lo usa hoy) y por tanto hay que custodiar **dos** credenciales por conexión? La custodia de C-03 es append-only por diseño; dos tipos de token por conexión es una decisión de custodia, no de fontanería.

**Recomendación de encuadre para el PO: historia P0 propia, `A0`, antes de A5, y bloqueante de las épicas A y B por igual.** Tamaño S–M; el riesgo está en las dos preguntas abiertas, no en el código.

---

## 2. Page Publishing Authorization (PPA) — precondición dura, indetectable, y ausente de todo el expediente

`content-publishing.md:19-21`, literal: *"An Instagram professional account connected to a Page that requires Page Publishing Authorization (PPA) **cannot be published to until PPA has been completed**"*, y — la parte que la hace peligrosa — *"**there's no way for you to determine if an app user's Page requires PPA**, we recommend that you advise app users to preemptively complete PPA"*.

Es exactamente el mismo patrón que la precondición de Página vinculada de ADR 25 (enforced en el callback, ruling R4), **salvo que ésta no se puede detectar por API en absoluto**. No aparece en `docs/integracion-cuentas-conectadas-meta.md`, ni en el backlog, ni en el sprint-state.

**Qué exige del backlog:** (a) un aviso en el flujo de conexión recomendando completar PPA preventivamente; (b) que el mapeo de errores de publicación tenga un desenlace **distinguible** para "la Página exige PPA", en vez de caer en un `failed` genérico. Un fallo de PPA que se registre como error opaco es horas de depuración persiguiendo un bug que no existe.

---

## 3. CONFLICTO con ADR 21 que necesita decisión del fundador: `ads_management` / `ads_read`

Las **dos** tablas de requisitos, en la columna Facebook Login, dicen lo mismo:

> *"If the app user was granted a role on the Page connected to your app user's Instagram professional account **via the Business Manager**, your app will also need: `ads_management`, `ads_read`"*
> (`content-publishing.md:29`, `comment-moderation.md:20`)

**El fundador administra sus Páginas desde Business Manager** — es el escenario descrito, no el excepcional. Y ADR 21 declara la publicidad de pago (`ads_management` / Marketing API) **explícitamente fuera de alcance**, como item futuro de investigación/ADR.

**La tensión es real y no la resuelvo yo:** pedir `ads_management` en el diálogo de consentimiento (i) ensancha materialmente lo que el usuario concede, (ii) es un permiso que ADR 21 aparcó a propósito, y (iii) muy probablemente empuja hacia App Review antes de lo previsto. No pedirlo puede significar que la publicación **no funcione** para la configuración exacta que tiene cliente cero.

**→ DECISIÓN DEL FUNDADOR.** Formulada para que sea respondible: *¿autorizamos añadir `ads_management` y `ads_read` al conjunto de scopes solicitados si la prueba empírica demuestra que la publicación falla sin ellos para una Página gestionada desde Business Manager?* No es una decisión de arquitectura: es alcance de consentimiento y calendario de trámite. **Yo no la firmo.**

Nota de secuenciación barata: la respuesta se puede **medir antes de decidir**. La prueba de A2 (resolución empírica de grafías contra el endpoint de autorización) puede, en la misma sesión, intentar publicar sin `ads_*` y ver si Meta lo rechaza. Medir primero cuesta una tarde; decidir a ciegas cuesta un App Review.

---

## 4. Lo BUENO: A5-1 queda cerrada en dirección favorable

`content-publishing.md:27` — fila **Access Levels**: **`Advanced Access` y `Standard Access`**, en **ambas** columnas. Y `comment-moderation.md:25-26` lo hace explícito: *"Standard Access if your app serves Instagram professional accounts **you own or manage and have added to your app in the App Dashboard**"*.

**Luego la publicación NO es Advanced-only por naturaleza**, que es justo lo que preguntaba A5-1 en `docs/integracion-cuentas-conectadas-meta.md` §A5 y lo que habría tumbado la mitad Meta de la asimetría de ADR 21. Concuerda con el cierre de V1 ya registrado en `CLAUDE.md` (*"el nivel de acceso es propiedad de la app y del escenario, no del permiso"*), y ahora con cita directa para la superficie de publicación, que antes no se había mirado.

**Consecuencia práctica, y es la que el fundador quería:** la demo de extremo a extremo de la épica A es **ejecutable en Development Mode, antes de que V-TP-2 cierre**, para cuentas que él posee o gestiona y ha añadido en el App Dashboard.

### [2026-07-31 01:21] data-scientist-fde — CORRIJO MI HALLAZGO ANTERIOR: la bandeja es COMENTARIOS, no DMs — y eso invierte W4-Q6

**AUTOCORRECCION.** Escribi el hallazgo de sentimiento [01:2x] razonando sobre **DMs**. Despues lei `docs/backlog-sprint3-meta-publishing-inbox.md` §4, que aplica el recorte del architect [01:14](2): **los DM no son alcanzables** (Advanced Access + un toggle humano dentro de la app de Instagram que ni la verificacion desbloquea), y **la bandeja de este sprint es SOLO COMENTARIOS en contenido propio**. Corrijo, porque parte de aquel hallazgo no aplica y dejarlo sin corregir induciria a error.

**Lo que retiro:** el argumento de desplazamiento de dominio. Un comentario publico de IG en espanol es **texto social publico corto en espanol** — practicamente el dominio de entrenamiento de robertuito (tuits). De todas las etapas de la cascada comprometida, **esta es la que mejor transfiere**, no la peor. Mi objecion de registro/primera-persona/intencion-transaccional era sobre DMs y **no aplica a comentarios**.

**Lo que se mantiene, y ahora es lo unico que importa:**

**1. El criterio de aceptacion no puede ser accuracy agregada.** En comentarios sobre contenido propio de una marca la clase mayoritaria esta muy desbalanceada (probablemente POS, al reves que en DMs, pero desbalanceada igual). **Cualquier criterio debe reportar la baseline de clase mayoritaria junto a la metrica.** Si el modelo no bate a "predice siempre la mayoritaria", no aporta nada y la accuracy alta lo esconde.

**2. El regimen de fallo NO es un caso borde, es la mayoria del corpus.** `NOTES_manychat_activation_layer.md` §2.3 ya avisa de errores de identificacion de idioma en mensajes muy cortos, y el propio backlog B4 lo cita. Lo hago concreto: en comentarios de Instagram, una fraccion grande — a ojo entre el 40 % y el 60 %, **sin medir, no hay corpus** — es **entrada degenerada**: solo emoji ("🔥🔥"), solo tag ("@maria mira esto"), una palabra, o no-espanol. robertuito **emitira una etiqueta confiada sobre "🔥🔥"**. Eso no es un fallo del modelo: es que se le esta preguntando algo que no tiene respuesta.

**CONSECUENCIA DE DISENO para B4, y es barata:** la puerta previa al generador que B4 ya exige **debe ser deterministica y anterior a cualquier modelo**. Clasificacion por forma del texto (recuento de tokens alfabeticos, proporcion de emoji/menciones, deteccion de idioma), no por polaridad. La polaridad — si se usa — va **detras** de esa puerta, nunca delante. Un `NEU` de robertuito sobre un emoji no es informacion, es ruido con etiqueta.

---

**INVERSION QUE EL PRODUCT-OWNER DEBE VER, y es lo mas importante de esta nota:**

`backlog-crm-workflows.md` §4.6 **W4-Q6 resolvio "DM privado primero"** con dos razones: mejor precision Y **coste del error acotado** (*"un borrador de DM equivocado es privado, en un hilo que abrio el contacto, y recuperable; una respuesta publica equivocada es la marca hablando en publico bajo su propio post"*). Se eligio deliberadamente **la superficie segura primero, para obtener telemetria sin el modo de fallo publico**.

**Esa opcion ya no existe.** El recorte del architect no reordena preferencias: **elimina la alternativa segura**. El sprint queda forzado a la superficie que W4-Q6 habia diferido por arriesgada. Tres consecuencias:

- **W4-Q6 queda superada por causa externa, no revocada.** Conviene que se anote asi y no que alguien lea manana que "se decidio hacer comentarios primero" — no se decidio, se quedo sin opciones.
- **La restriccion de ManyChat de §4.5(4) deja de ser opcional.** *"Generar solo para polaridad positiva"* estaba planteada como *"cuando lleguen los comentarios publicos"*. Los comentarios publicos **son este sprint**. Si B4 entra, esa puerta entra con el. Y notese la composicion elegante que §4.6 ya senalaba: esa puerta es exactamente polaridad de 3 clases, **es decir, lo unico que robertuito sabe hacer**. Su unico trabajo legitimo en toda la bandeja es este.
- **Refuerza que B4 caiga del sprint.** El backlog ya lo marca P3 y *"candidato natural a caer"*. Suscribo, y anado razon: **el primer incremento generativo del proyecto iria directo a la superficie publica, sin telemetria previa, sin corpus y sin haber podido usar la privada como banco de pruebas.** La advertencia del propio §4.6 sobre la **fatiga de aprobacion** (*"a volumen, los revisores sellan sin leer"*) se escribio precisamente para no poner borradores en superficie publica antes de medir la tasa real de edicion/descarte. Hoy esa tasa sigue sin existir.

**Sobre R6 (sustituir robertuito por licencia limpia):** al reves de lo que dije en el hallazgo anterior — **no queda descargada**. Si B4 entra, la puerta de polaridad entra, y entonces R6 esta en la ruta critica de la unica historia generativa del sprint. Si B4 cae, R6 sale de la ruta critica. **R6 y B4 viven o mueren juntas.**

### [2026-07-31 01:22] data-scientist-fde — CRITERIOS DE ACEPTACION MEDIBLES PARA B4 + dimensionado del conjunto dorado (n=100)

Sobre el backlog real (`docs/backlog-sprint3-meta-publishing-inbox.md`), la unica historia con modelo es **B4**. B1/B2/B3 no tienen modelo y sus criterios ya son verificables — no los toco.

**B4 tiene hoy dos criterios `[pendiente reto datasci]`. Los cierro asi:**

---

**1. Puerta deterministica de entrada degenerada — SI es in-sprint, S, y NO necesita conjunto dorado.**

No es un modelo, es una regla sobre la forma del texto, luego su criterio puede ser exacto:

> Existe `classify_comment_shape(text: str | None) -> CommentShape` con `CommentShape ∈ {EMPTY, EMOJI_ONLY, MENTION_ONLY, TOO_SHORT, NON_TARGET_LANGUAGE, ELIGIBLE}`. Un fixture de **60 comentarios etiquetados a mano** (10 por clase) se clasifica con **60/60 exactos**. Ningun comentario con forma distinta de `ELIGIBLE` alcanza el generador ni el clasificador de polaridad — test negativo sobre la ruta.

60/60 es exigible porque es determinista: si falla uno, la regla esta mal, no el modelo. Etiquetador: cualquier ingeniero del equipo, ~30 minutos. **Es la unica pieza de la capa de IA de B4 que puede cerrarse este sprint con criterio duro.**

---

**2. Puerta de polaridad (robertuito) — NO cerrable este sprint. Falta el conjunto.**

Si entra, el criterio **no puede ser accuracy**:

> Sobre un conjunto etiquetado de comentarios reales de contenido propio del tenant: **macro-F1 estratificado por longitud** (buckets: 1-3 tokens alfabeticos / 4-15 / >15), reportando **la baseline de clase mayoritaria en cada bucket** junto a la metrica. Umbral de aceptacion: **macro-F1 supera la baseline de mayoria en el bucket >15 tokens**, y el bucket 1-3 se declara **fuera de cobertura** (lo cubre la puerta deterministica de arriba, no el modelo).

**No escribo un numero de umbral**, y ese es el punto: el backlog ya dice *"no se escribe ninguna cifra de precision, recall o umbral sin medicion"*. Suscribo y lo dejo asi.

---

**3. Calidad del borrador — NO existe conjunto dorado, y CREARLO ES LA HISTORIA. La dimensiono.**

Hoy no hay ni un comentario real en base (`messages` vacia, el flujo muere en `link_required`). **No se puede construir un conjunto dorado de calidad de borrador este sprint**, ni con capacidad infinita: falta la materia prima.

**Lo que si genera la materia prima ya esta en B4** — el criterio de telemetria aceptado/editado/descartado + diff. Confirmo que es correcto y que **es lo unico de B4 que es realmente urgente**: retrofitearlo es caro, y sin el seguiremos dentro de tres sprints citando cifras calculadas en vez de medidas.

**Dimensionado del conjunto dorado, para el sprint siguiente (calculo mio, Wilson 95 %):**

| n | Semiancho del IC 95 % en p=0,80 | Peor caso (p=0,50) | Sirve para |
|---|---|---|---|
| 30 | ±13,9 pp | ±16,8 pp | Nada decidible |
| 50 | ±10,9 pp | ±13,4 pp | Descartar un desastre |
| **100** | **±7,8 pp** | ±9,6 pp | **Decidir si vale la pena; no distingue 75 % de 80 %** |
| 200 | ±5,5 pp | ±6,9 pp | Comparar dos prompts entre si |

**Recomiendo n=100.** Coincide con el mandato del conjunto dorado ya escrito (`arquitectura.md` §7, ~100 items) y con el precedente en disco (`packages/models/eval_data/golden_set_v1.jsonl`, que hoy tiene **5 lineas** y dos etiquetas marcadas como provisionales — util como formato, no como conjunto).

- **Quien etiqueta: la persona que enviaria la respuesta, no un ingeniero.** La pregunta es *"¿enviarias esto tal cual?"* — es un juicio de voz de marca, y un ingeniero no lo tiene. Cliente cero: el fundador. Cliente uno: un agente de la inmobiliaria.
- **Etiqueta binaria** (enviable sin editar / no), mas la edicion real cuando la respuesta es "no". La edicion es la senal cara y es la que despues entrena o evalua cualquier cosa.
- **Solape de 30 items con un segundo etiquetador** para medir acuerdo (Cohen kappa). Sin esto no se sabe si el 80 % mide el modelo o mide al etiquetador. **Si kappa < 0,4, el conjunto no es utilizable y hay que reescribir la rubrica antes de medir nada.**
- **Coste: ~2-3 h de etiquetado** (100 items + 30 de solape, a ~1 min por item mas la edicion). **Talla: S de ingenieria (el arnes ya existe: `eval/harness.py`, `eval/metrics.py`, `eval/schema.py`), M de tiempo humano no-ingeniero.** El cuello de botella es la disponibilidad del etiquetador, no el codigo.
- **Provenance obligatoria** en cada fila: `model_id` + revision + `prompt_version`, igual que `SentimentResult` ya hace.

---

**4. Un criterio de B4 que corregiria — la justificacion de la puerta barata.**

B4 justifica la puerta con *"una conversacion de 3 turnos cuesta el 119 % de lo que ese contacto ingresa"*. **Ese 119 % es sobre la economia de precios por contacto de ManyChat, no sobre la de Qualify** (`eval/conversation_cost.py` divide por `PlanEconomics.revenue_per_included_contact`, que son los planes de ManyChat). Qualify tiene dos tenants y **ningun modelo de precios por contacto**: el coste real medido es **~$0,0013 por borrador** con Haiku 4.5, **~$2/mes** al volumen central.

**No propongo quitar la puerta** — es correcta, pero por otra razon: filtra entrada degenerada (§2 de esta nota) y es la costura estructural. **Propongo cambiarle la justificacion escrita**, porque tal como esta, un lector futuro concluira que la puerta existe para ahorrar dinero, medira $2/mes, y la quitara. El argumento que aguanta a este volumen es **calidad y superficie de fallo, no coste**.

### [2026-07-31 01:23] principal-architect — Reto de fase por épica, resolución de las tres contradicciones doc-vs-código, y qué condiciona realmente V-TP-2

## A. Reto de fase — veredicto por épica

Contra el mapa de fases de `CLAUDE.md` y ADR 21 / 24 / 25. Épica A leída del backlog ya escrito (§3, historias A1-A7); B y C leídas del encuadre del §1 de este fichero, porque §4-§5 aún no estaban en disco cuando revisé.

### Épica A — Publicación → **PASA CON CONDICIÓN**

Clasificación de fase **correcta**: A1-A7 son todas **Fase 1 Parte 4-A**. Nada de Fase 2-6 se ha colado, no hay TikTok, no hay dependencia de ADR 29 / BISU, no hay historia que puntúe personas (S6 bien declarado). El alcance declarado del §3 —vídeo sí, imagen a QUA-68, carrusel-como-producto fuera, Marketing API fuera— es exactamente la frontera de ADR 28a. **Bien construida.**

Tres condiciones, todas registradas arriba en este fichero:
1. **Falta `A0` (token de Página).** Bloqueante y no declarado.
2. **A5 debe dejar de pedir un bucle de sondeo en el servidor.** `advance()` de un paso, techo comprobado contra `created_at`.
3. **A3 depende de dos items de infra** (declarar `boto3`, aprovisionar R2) que deben existir como historias propias, no como supuestos.

Además, una precisión de fase que sí conviene hacer: **A1 y A2 no son publicación, son remediación de C-04** (el flujo de conexión). Misma fase, distinto módulo. Merecen ir juntas y primero, porque el resto de la épica y **toda la épica B** dependen de que la conexión conceda activos.

### Épica B — Bandeja de un solo canal → **PASA CON CONDICIÓN FUERTE**

Fase correcta (**Parte 4-B**, ADR 21/24), y el encuadre acierta en lo que rechaza: cross-canal a Fase 6 (*"un buzón no es una bandeja unificada hasta que unifica más de un canal"*), respuestas autónomas fuera permanentemente. Condiciones:

1. **Es SÓLO comentarios.** DM inalcanzable por dos vías independientes → parking lot. (Bloque anterior de este fichero.)
2. **Depende de `A0` igual que la épica A** — `GET /<IG_MEDIA_ID>/comments` exige token de Página (`comment-moderation.md:17`).
3. **Sin scheduler**, pull manual.
4. **⚠ Reto de fase real: el análisis de sentimiento sobre comentarios de medio propio.** Como **campo de triaje de un hilo** (una etiqueta por mensaje, para ordenar la bandeja) es Parte 4-B y pasa. Como **reporting, agregación, gráficas o resumen LLM**, es **Fase 2 (Social listening + AI Insights)** y **no pasa**. La frontera no es el modelo, es el consumidor: un valor por fila en la bandeja, sí; un panel que agrega esos valores, no. Si el backlog escribe la historia sin esa frontera, se cuela Fase 2 disfrazada de campo de base de datos.
5. **Respuestas asistidas (C-10): pasan**, con la restricción de ADR 21 (borrador + aprobación humana explícita). Pero son **escritura a plataforma** (`POST /<IG_COMMENT_ID>/replies`), luego heredan `A0`, `instagram_manage_comments`, y la misma condicional de `ads_management`. **P3 dentro del sprint es la prioridad correcta**; en la práctica creo que no cabe (ver dimensionado).

### Épica C — Deuda y cumplimiento → **PASA, PERO MAL AGRUPADA**

Fase correcta (fundación, ADR 24). El problema es de composición, no de fase: la épica mezcla **trabajo de ingeniería** con **entregables que no son código**, y eso distorsiona el presupuesto del sprint.

- **C1 tenant** → ingeniería, fundación, **precondición de toda ruta HTTP nueva**. Ver el bloque de diseño más arriba.
- **`boto3` + bucket R2** → dos items de infra, precondición del primer publish real.
- **Los cinco huecos de Platform Terms (§8.3.2): sólo UNO es código.** El **endpoint de borrado/desautorización** (data deletion / deauthorize callback) es un endpoint HTTP que además debe disparar la revocación — y `connections/revoke.py` **ya existe**, así que es barato. Los otros cuatro (política de privacidad, política de retención, canal de vulnerabilidades, cláusula §5.b.ii.4.a del ToS) son **documentos y URLs**: tarea del fundador, no capacidad de desarrollo. **Recomiendo partirlos explícitamente**, construir el endpoint en este sprint y aparcar los cuatro documentos como tareas del fundador con la misma fecha de vencimiento (*"cuando el primer agente de cliente uno use el producto"*).

### Rechazos limpios (confirmo el encuadre, sin cambios)

- **Publicación en TikTok** — bloqueada por ADR 21 firmada. Cero historias. Sin fecha, no parking lot con fecha.
- **Inbox cross-canal** — Fase 6.
- **Respuestas autónomas** — fuera permanentemente; no es etiqueta de fase, es un problema de precisión.
- **Cualquier cosa BISU / Tech Provider** — ADR 29 `[PROPUESTO]`, sin firmar → parking lot con dependencia declarada.
- **Marketing API / publicidad de pago** — fuera del alcance orgánico de ADR 21. **Ojo:** esto choca con el requisito condicional de `ads_management`; ver el conflicto para el fundador registrado arriba. El choque es de **permiso**, no de funcionalidad — no reabre el alcance de publicidad.

---

## B. Contradicciones doc-vs-código: resolución de las tres

### 1. `config_id` obligatorio → **OMISIÓN, no contradicción. Se resuelve sin firma.**

Ningún doc afirma lo contrario; simplemente ninguno lo menciona (`grep config_id docs/` sólo pega en el backlog de hoy). No contradice ADR 25: la refina. **Resolución: addendum operativo, sin firma del fundador**, porque no cambia ninguna decisión firmada.

**Pero tiene una consecuencia arquitectónica que sí hay que registrar y que nadie ha nombrado:** si el `config_id` de Facebook Login for Business determina el conjunto de permisos que el diálogo pide, entonces **`requested_scopes` deja de ser la fuente de verdad de lo que pedimos**, y esa fuente pasa a ser un artefacto de la consola de Meta que **vive fuera del repositorio, sin control de versiones y sin revisión**. Consecuencia: **la verificación de scopes concedidos por `/me/permissions` se vuelve MÁS crítica, no menos** — es lo único que queda dentro del sistema capaz de decir qué se concedió de verdad. `list_granted_scopes` ya existe y ya persiste `granted_scopes` verbatim (`service.py:204, 219`), así que el código está bien; lo que falta es que el doc diga por qué eso ahora es load-bearing. Merece **enmienda `[PROPUESTO]` a ADR 25** en `docs/arquitectura.md` §6.

### 2. Grafía `instagram_content_publish` → **ERRATA DE ENUMERACIÓN EN TEXTO FIRMADO. Se corrige por addendum, NO por re-firma. Cero defecto de código.**

- `docs/arquitectura.md:293` (fila de ADR 25, **firmada por el fundador 2026-07-26**) enumera `instagram_content_publishing`.
- **Meta dice lo contrario en su propia tabla de requisitos:** `content-publishing.md:29`, columna Facebook Login → **`instagram_content_publish`**. Corrobora documentalmente el hallazgo de campo de hoy, por una vía distinta a la del endpoint de autorización.
- **El código está bien y no hay que tocarlo.** `packages/models/src/qualify_models/permission_capability.py:136-140` siembra **las cinco grafías** bajo `ScopeKey.CONTENT_PUBLISH`, incluidas ambas variantes de la rama Facebook Login, con el comentario explícito *"ambas sembradas para que ninguna se rechace en silencio"*. `.env` ya lleva la correcta.
- **Resolución, y por qué no necesita firma:** la enumeración de esa fila es **ilustrativa, no normativa**. La regla normativa de ADR 25 —recogida en `CLAUDE.md`— es *"nunca hardcodear una grafía desde documentación; resolverla empíricamente contra el endpoint de autorización"*, y esa regla **no cambia**; si acaso, este hallazgo la confirma. **No edito la fila firmada.** Propongo addendum `[PROPUESTO]` que corrija la enumeración y cite `content-publishing.md:29`.

### 3. App Mode global degrada visibilidad → **YA RESUELTA EN DISCO. No hay contradicción viva.**

Verificado: `docs/integracion-cuentas-conectadas-meta.md:347` **ya lleva la frase tachada** (`~~Un reel publicado por una app en Development Mode es un reel público normal.~~`) con el bloque de retirada del 2026-07-29, doble fuente primaria (App Modes de Meta + campo independiente vía Postiz), y el ruling completo en `docs/arquitectura.md` §6 (i.2). El hallazgo 3 de la sesión de campo de hoy **corrobora lo ya registrado; no destapa nada nuevo**. Nada que resolver, nada que firmar. Lo anoto porque el §1 de este fichero lo presenta como hallazgo nuevo y podría inducir a alguien a reabrirlo.

---

## C. V-TP-2 / A5-5: qué queda condicionado y qué puede arrancar mañana

**V-TP-2 pregunta tres cosas** (`docs/integracion-cuentas-conectadas-meta.md` §A5, fila A5-5): (a) ¿el toggle a Live Mode exige App Review y/o Business Verification, o es self-serve? (b) ¿sobrevive un permiso de Standard Access al paso a Live para un titular de rol? (c) ¿ve un tercero un reel publicado con la app en Development Mode?

### Historias INDEPENDIENTES de V-TP-2 — arrancan mañana, las siete

**A1, A2, A3, A4, A5, A6, A7 y toda la épica C.** Ninguna está bloqueada, y **confirmo el `NO` del backlog con una razón que el backlog no tenía**: `content-publishing.md:27` lista **Standard Access** en ambas columnas y `comment-moderation.md:25-26` lo explicita — *"Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard"*. Luego **publicar y leer comentarios sobre las cuentas del propio fundador es una operación de Standard Access**, ejecutable hoy. Esto cierra además **A5-1** en dirección favorable.

### Corrección al backlog: **A5 debe pasar de `PARCIAL` a `NO`**

El `PARCIAL` de A5 cita *"algunas funcionalidades pueden no funcionar correctamente hasta tener Advanced Access"* (`overview.md:43`). Es una incertidumbre real **pero no es V-TP-2**: no es ninguna de sus tres preguntas. Etiquetarla como `[dep V-TP-2]` invita al fundador a **esperar** a una verificación que no la va a responder. **Debe ser `NO`, con una nota de riesgo propia y sin nombre de dependencia.** La precisión importa: el objetivo del §6 es que el fundador sepa qué arrancar sin esperar, y un `PARCIAL` mal puesto le cuesta días.

### Lo que V-TP-2 SÍ condiciona, y no es ninguna historia

**Condiciona el calendario, no el código.** Si (b) vuelve negativa —un permiso de Standard **no** sobrevive al paso a Live para un titular de rol— entonces todo lo que este sprint construya **deja de funcionar para cliente cero el día en que la app se ponga en Live** para cliente uno. Formulado para el fundador:

> **Puedes arrancar el sprint entero mañana. Lo que no debes hacer hasta que V-TP-2 cierre es planificar el alta de cliente uno encima de una instalación de cliente cero que funciona** — porque el toggle que da de alta al uno puede apagar al cero.

Ninguna historia cambia por eso. Lo que cambia es el orden de dos hitos de negocio, y ésa es la decisión que V-TP-2 compra.

### Recomendación operativa: una sola sesión empírica cierra siete preguntas

Todas se responden con la misma app, la misma cuenta y la misma tarde. Ordenadas por dependencia:

1. **Grafía del scope** (A2) — contra el endpoint de autorización.
2. **`config_id`** (A1) — que el diálogo conceda activos de verdad.
3. **Token de Página** [NUEVA, mía] — ¿devuelve `/me/accounts` un `access_token` por Página al pedirlo en `fields`? ¿es de larga duración?
4. **`ads_management` / `ads_read`** [NUEVA, mía] — ¿falla `create_container` sin ellos para una Página gestionada desde Business Manager? **Medir antes de decidir.**
5. **PPA** [NUEVA, mía] — ¿la Página del fundador exige Page Publishing Authorization?
6. **V-TP-2 (a)(b)(c)** — el toggle a Live y sus consecuencias.
7. **V-TP-7** (de ADR 29) — ¿exige BISU un status de Tech Provider ya concedido?

Las cinco primeras se hacen **sin tocar el modo de la app** y desbloquean el sprint entero. La 6 es la única que cambia el estado de la app y por tanto **debe ir la última de la sesión**.

### [2026-07-31 01:24] product-owner — Backlog Sprint 3 en disco + tres cosas que el lead debe resolver antes de lanzar /team-dev

Fichero: `/Users/herwin/Desktop/Qualify/docs/backlog-sprint3-meta-publishing-inbox.md` (703 lineas, 15 candidatos: A1-A7 publicacion, B1-B4 bandeja, C0-C4 deuda/cumplimiento). Incorporados los tres hallazgos del architect y la auditoria del datasci.

## 1. BLOQUEANTE DE PROCESO — `packages/api/` NO esta en el mapa de propiedad de /team-dev
`.claude/commands/team-dev.md:22` reparte: pipeline -> `packages/scraper/`, `docker-compose.yml`, `migrations/`, `packages/shared/`; datasci -> `packages/models/`; ui -> `Qualify/`; architect -> `docs/`, `CLAUDE.md`. **`packages/api/` no aparece**, y 12 de las 15 historias de Sprint 3 viven ahi. La misma linea dice *"Anything outside these paths requires my approval — surface it, don't edit"*. Sin extender el mapa explicitamente, el equipo se para en la primera historia.

**Y hay conflicto de capacidad encima:** 12 items de `packages/api/` para un solo pipeline-engineer duplican el presupuesto declarado de 5-6 por companero. Propuesta en el backlog §6.3: dos instancias de backend con fronteras disjuntas — `publishing/` + `http/publishing_routes.py` una, `connections/` + `config.py` + bandeja + `shared/` la otra. Unico fichero compartido: `app.py`. Si solo cabe uno, la epica B entera cae al siguiente sprint (publicacion primero, es el criterio declarado).

## 2. Seis decisiones documentadas que ya NO se sostienen — no reimplementar (backlog §1.3)
- **"Alojar el media en una URL publica" + URL firmada de R2** (W3-Q3, `backlog-crm-workflows.md` §3.2 fila 2 y §3.6). **MUERTA por ADR 28a**: `publishing/client.py:287-311` sube bytes a `rupload.facebook.com`. Meta **nunca hace cURL de una clave nuestra**. Desaparece el requisito de infraestructura, el TTL y el [V] de si el fetcher acepta query strings.
- **Tabla `publish_jobs`** (`integracion-cuentas-conectadas-meta.md` §4.2) -> real es `publish_attempts`.
- **Columna de expiracion de ventana en el hilo** (§4.3 del mismo doc, literal: *"cada hilo lleva su fecha de expiracion de ventana como columna"*) -> **prohibida por la condicion B2 del architect** (`0004_inbox.py:16-19`). Se calcula desde `last_inbound_at`, nunca se materializa.
- **Dedup en dos capas con Redis SETNX** (§4.3 paso 2 y criterio de C-08) -> **superada por la decision de 2026-07-28** (`0004_inbox.py:136-138`): constraint + upsert idempotente, *"deliberadamente no un Redis SETNX"*.
- **Intake webhook-first** (§4.3 y §2.6 del doc del architect) -> es POLL-FIRST; el doc conserva la redaccion vieja.
- **"100 posts (50 si son carruseles)"** -> falso. Dos contadores distintos: 100 = posts publicados (carrusel = 1), 50 = **contenedores IG** (carrusel de 10 = 11). Los carruseles son **mas caros** bajo la restriccion que ata, no mas baratos.

## 3. K1 — la correccion del 65 % toca ficheros que NO son mios
Aplicada en mi backlog (§4 B4): el ruling *autonomas fuera* se mantiene, reescrito sobre (a) ausencia total de evidencia + (b) asimetria irreversible del coste del error + (c) vertical regulada/§3.a.ii housing. **El 65 % ya no aparece como fundamento en mi fichero.** Siguen citandolo mal, y son de otros duenos: `CLAUDE.md:226`, `docs/arquitectura.md:288` y `:877` (ADR 21 — architect), `docs/integracion-cuentas-conectadas-meta.md:445,470,556` (architect), `docs/registro-validacion-features.md:130`. **Mios y pendientes de una sesion posterior:** `docs/backlog-crm-workflows.md:569,571,861`.

## 4. Correccion menor al hallazgo del architect [01:14]
`UNCOVERED_SURFACES` es una **tupla** de `UncoveredSurface` (`ig_shapes.py:591`), no un dict. El acceso `UNCOVERED_SURFACES["direct_messages"]` que aparece en el hallazgo es taquigrafia: quien escriba el test necesita una busqueda, no un subscript. La sustancia del hallazgo (DM inalcanzable por dos exclusiones independientes) es correcta y esta incorporada.

## 5. Seis decisiones que necesitan al FUNDADOR (backlog §8.2)
F1 ejecutar V-TP-2/A5-5 (App Mode Live + Business Verification contra cuenta real) — **no bloquea ninguna historia del sprint**, todas son construibles y testeables offline hoy; decide cuando el producto es ensenable a alguien que no es el. F2 aprovisionar bucket R2 (gasto) — bloquea el primer publish real. F3 politica de privacidad + retencion + clausula de ToS. F4 alcance sobre §3.a.ii/housing. F5 arrancar el reloj administrativo en semana 0. **F6 la mas urgente para no romper expectativas: ¿"programar" publicaciones entra o no? Este backlog dice NO — entrega publish-now.** Si su expectativa es un calendario funcionando, hay que decirselo ahora, no al final del sprint.

### [2026-07-31 01:26] po-sprint3 — RULING DE LEAD K2 — packages/api/ no tiene dueño en el mapa de /team-dev, y ahí viven 12 de 15 historias

Verificado por el lead contra .claude/commands/team-dev.md:22. El mapa de propiedad literal es: architect -> docs/, CLAUDE.md; pipeline -> packages/scraper/, docker-compose.yml, migrations/, packages/shared/; datasci -> packages/models/; ui -> Qualify/. **packages/api/ no aparece.** Las epicas A y B de Sprint 3 viven casi enteras ahi (12 de 15 historias), y ademas 12 items para un solo pipeline-engineer superan el presupuesto declarado de 5-6 tareas por teammate.

RULING: no se parte el sprint entre dos backend engineers. Sprint 3 = epica A (incluida la nueva A0, token de Pagina) + C1, con un solo backend engineer y ownership de packages/api/ extendida EXPLICITAMENTE en el prompt de /team-dev. La epica B (bandeja) entera pasa a Sprint 4, aparcada con su razon: depende de A0 y no cabe en el presupuesto.

MOTIVO: la ruta critica declarada por el fundador es 'sin endpoint de publicacion no hay producto que ensenar'. La bandeja depende de A0, que es una historia que ni siquiera existia al empezar la sesion.

LIMITE DE MI AUTORIDAD: recortar alcance es decision del fundador, no del lead. El backlog debe presentar las dos formas (con y sin epica B) para que pueda elegir sin releer 700 lineas. Esto se le presenta como recomendacion, NO como hecho consumado.

### [2026-07-31 01:26] po-sprint3 — COLA DE DECISIONES DEL FUNDADOR — estado tras la ronda 1 (el lead la cierra tras la ronda 2)

Lo que necesita decision del fundador ANTES de que /team-dev arranque. Ordenado por urgencia.

D1 (LA MAS URGENTE). Este backlog entrega **publish-now, no programacion diferida**. No hay Celery: 'grep -rl celery' -> cero. La tabla scheduled_posts existe en DDL pero no hay worker que la consuma; la programacion depende de Fase 1 Parte 3, no empezada. Si la expectativa del fundador es un calendario funcionando, hay que decirselo AHORA, no al final del sprint.

D2. Recorte de alcance: aceptar Sprint 3 = epica A + C1 (publicacion sin bandeja), con la epica B a Sprint 4. Ver ruling K2 arriba. Decision suya, no del lead.

D3. Autorizar o no anadir los scopes ads_management y ads_read si la prueba empirica demuestra que la publicacion falla sin ellos para una Pagina gestionada desde Business Manager. ADR 21 los aparco. Se puede MEDIR antes de decidir — no es una decision a ciegas.

D4. Gasto del bucket R2: bloquea el primer publish real. boto3 no esta declarado como dependencia y el bucket no esta aprovisionado.

D5. Cuando ejecutar V-TP-2 / A5-5 (App Mode Live + Business Verification). Hallazgo importante del architect: **no bloquea ninguna historia** — las quince son construibles offline en Development Mode. Lo que decide es CUANDO el resultado es ensenable a un tercero. content-publishing.md:27 lista Standard Access en ambas columnas, lo que cierra A5-1 favorablemente. El riesgo residual: si un permiso Standard no sobrevive al paso a Live, lo construido deja de funcionar para cliente cero el dia del alta del cliente uno.

D6. §3.a.ii / housing: si alguna vez se computa score de PERSONA en el vertical inmobiliario, y donde cae el filtrado de spam (unico caso legitimo que elimina filas). El datasci dejo la frontera traducida a tres reglas verificables con test estatico, mas una cuarta que no esta en §8.3.3: el prompt del generador recibe texto del hilo, nunca un atributo derivado de la persona.

D7. Si B4 (borradores generativos) entra o cae. El datasci recomienda que caiga, y senala que R6 y B4 viven o mueren juntas. Queda subsumida en D2 si se acepta el recorte.

BLOQUEANTE DE ENTORNO, no de decision: el .venv compartido esta corrupto (8 errores de coleccion, 83/90 en packages/models; 'import qualify_models' falla aunque uv pip list lo muestre). Es la trampa conocida de CLAUDE.md. Arreglo: 'rm -rf .venv && uv sync --group ml' con NADIE mas ejecutando. El lead NO lo ejecuto: hay agentes en paralelo en esta sesion. Consecuencia practica: hoy cualquier criterio de aceptacion del tipo 'los tests de packages/models pasan' es INVERIFICABLE.

### [2026-07-31 01:31] principal-architect — Reto item por item de §3-§5: 10 pasan, 4 con condición, B4 fuera — y por qué el sprint NO crece por A0

Reto item por item sobre §3-§5 tal como están escritas. **Diez pasan, cuatro pasan con condición, una no pasa.** El foco pedido —si el dimensionado sobrevive a A0— tiene una respuesta contraintuitiva que está al final.

| Item | Veredicto | Motivo en una línea |
|---|---|---|
| **A0** (nuevo) | **FALTA — P0** | Token de Página. Bloquea A5, A6, A7, B1, B2, B3 |
| A1 `config_id` | **Pasa** | Añadir un criterio sobre `granted_scopes` |
| A2 grafía | **Pasa con condición** | El script debe cubrir cinco preguntas, no una |
| A3 staging | **Pasa con condición** | Falta decir quién genera `media_id` — es un hueco de seguridad |
| A4 repositorio | **Pasa con condición** | El criterio del trigger es medio correcto; ver abajo |
| A5 servicio | **Pasa con condición** | El bucle de sondeo debe caer; **L → M** |
| A6 reconciliación | **Pasa** | Y **se encoge**, ver abajo |
| A7 rutas | **Pasa** | Ya incorpora el staging (L6). Correcto |
| B1 cliente lectura | **Pasa** | Hereda A0 |
| B2 sync | **Pasa** | Excelente spec; nada que objetar |
| B3 normalización | **Pasa** | Excelente spec; nada que objetar |
| B4 borradores | **NO PASA en Sprint 3** | Capacidad y dependencias, no fase |
| C0 venv | **Pasa** — no es historia | Precondición del lead. Bien encuadrado |
| C1 tenant | **Pasa con condición** | El mecanismo propuesto identifica, no autentica |
| C2 cinco huecos | **Pasa con re-agrupación** | 2 de ingeniería + 3 del fundador |
| C3 `boto3` | **Pasa** | Hacerlo en la misma operación que C0 |
| C4 bucket R2 | **Pasa** — es gasto, no código | Decisión del fundador |

---

### Los cuatro "con condición", en detalle

**A3 — hueco no cerrado: ¿quién genera `media_id`?** `media_key(tenant_id, connection_id, media_id)` documenta `media_id` como *"an opaque media_id the caller owns"*. La historia no dice quién es ese llamante. **Si el `media_id` viene del cliente HTTP, es un vector de sobrescritura dentro del propio tenant**: `require_tenant_prefix` rechaza `..` y las claves de otros tenants, pero **no impide que un tenant pise su propio objeto** reutilizando un `media_id`. Criterio a añadir: **`media_id` es un UUID4 generado en servidor, nunca aceptado del cuerpo de la petición**, y la respuesta devuelve la clave resultante. Es la misma disciplina que `tenant_id` no viniendo del cuerpo, aplicada un nivel más abajo.

**A4 — el criterio del trigger está a medias, y la mitad que falta es la que importa.** La historia dice que un `settle` sobre fila asentada *"debe propagar el error de la base como fallo explícito"* y prohíbe el `WHERE settled_at IS NULL`. **La prohibición es correcta; la propagación cruda no.** Hay dos llamantes con necesidades opuestas:
- Una **reconciliación** que encuentra la fila ya asentada está en su camino **idempotente normal** — debe devolver el desenlace existente, no fallar. Es exactamente el caso que `ContainerStatus.PUBLISHED` existe para resolver.
- Un **bug de servicio** que intenta re-asentar con un desenlace distinto sí debe reventar ruidosamente.

Resolución: el repositorio **captura `check_violation` y lanza un `AlreadySettled` tipado que lleva el desenlace existente**; el servicio decide. Lo que no puede pasar es que un reintento legítimo del operador acabe en un 500. Sin este matiz, A4 tal como está escrita produce un sistema que falla en su camino feliz de recuperación.

**A5 — el bucle cae, y con él el tamaño.** Ya está razonado arriba en este fichero (L7): un bucle de 60 s × 5 min dentro de una petición HTTP, más una subida de hasta 300 MiB, es una petición de 8-10 minutos y viola la regla 4. Sustitución: **`advance()` de un solo paso**, invocado por el `GET /api/publishing/attempts/{id}` que A7 ya define. El techo se comprueba contra `created_at`, no con un contador de bucle — **y eso hace los tests deterministas y sin `sleep`, que hoy no lo serían**. **A5 pasa de L a M.**

**C1 — el mecanismo propuesto identifica, no autentica.** La historia acepta *"una cabecera de operador validada contra `tenant_members`"*. La validación contra `tenant_members` es la **autorización** y es correcta; el problema es lo que hay debajo: **una cabecera que nombra a un operador es una identidad reclamada, no una credencial presentada.** Quien conozca un `user_id` obtiene sus tenants. Es el mismo bypass de `StartConnectRequest`, movido de cuerpo a cabecera. **Debe ser una credencial opaca** (`Authorization: Bearer <token>` resuelto contra un mapa de entorno, sin migración) **de la que se derive el principal, y sobre ese principal se valida la pertenencia.** Segundo punto: el criterio *"sin selección válida sigue devolviendo 409"* debe caer — con credencial, el código correcto es **401** (no autenticado), y el 403 que la historia ya define para no-pertenencia se queda. Mantener el 409 conserva una mentira del contrato actual.

---

### El único que no pasa

**B4 — fuera de Sprint 3.** No es objeción de fase (Parte 4-B es correcta, ADR 21c). Es que depende de B1+B2+B3 —los tres al final de la cadena— y de un veredicto de datasci. **Y descarto explícitamente la tentación de "rescatar" su criterio de telemetría** (registrar aceptado/editado/descartado + diff) hacia B3 para no perder el *"es gratis si se diseña desde el día uno"*: en Sprint 3 **no se genera ningún borrador**, luego no hay nada que registrar y el rescate crearía esquema muerto. Diferir B4 entero no cuesta nada. El *"gratis desde el día uno"* se cobra el día que se genere el primer borrador, no antes.

Lo que **sí** hay que preservar al diferirlo: su primer criterio —*no existe camino de código que envíe sin acción humana explícita*— **no es de B4**, es una propiedad del sistema. Debe vivir como test negativo permanente desde que exista cualquier escritura a plataforma, es decir **desde A5**.

---

### C2 — la re-agrupación concreta

De los cinco entregables, **dos son ingeniería y tres son del fundador**:
- **Ingeniería:** (2) endpoint de *deauthorize* + *data deletion callback* — barato porque `connections/revoke.py` y el borrado por prefijo ya existen; falta la puerta. (4) `SECURITY.md` — trivial, minutos.
- **Fundador / producto-legal:** (1) política de privacidad, (3) política de retención, (5) cláusula de ToS. **No consumen capacidad de desarrollo y no deben contarse contra el presupuesto del sprint.**

Contarlos como un solo item "M" oculta que tres quintos no son código, e infla artificialmente lo que parece que hay que recortar.

---

## ¿Sobrevive el dimensionado a A0? — Sí, y por un motivo que no es obvio

**A0 añade un item, pero las dos correcciones de arriba quitan aproximadamente el mismo trabajo:**
- **A5 pasa de L a M** al perder el bucle de sondeo.
- **A6 se encoge y casi se disuelve.** Con el sondeo dirigido por cliente, la reconciliación **deja de ser un camino de código aparte**: es literalmente lo que hace el `GET /attempts/{id}` cuando encuentra una fila en `processing` con `creation_id`. Los criterios de A6 siguen siendo válidos **como criterios de aceptación**, pero dejan de exigir un módulo propio. **Recomiendo fusionar A6 dentro de A5** conservando sus tests íntegros — es la simplificación de mayor palanca del backlog, y llega gratis con una corrección que había que hacer de todos modos.

**Balance neto: +1 item (A0), −1 item (A6 fusionado), y A5 baja un escalón de tamaño. El sprint no crece por A0.** Lo que A0 **sí** hace es mover riesgo de "descubrimiento en producción" a "trabajo planificado", que es exactamente lo que se quiere.

Con esto la épica A queda: **A0, A1, A2, A3, A4, A5(+A6), A7 = 7 items**, de los cuales tres son S.

### [2026-07-31 01:32] principal-architect — Ruling de capacidad: separar B de A es gratis SALVO una frase en A0 — y el texto exacto de sustitución para CLAUDE.md:226

## 1. Lectura técnica del recorte propuesto por el lead (épica A + C1, un solo ingeniero, B a Sprint 4)

**Respaldo el recorte. Y respondo la pregunta exacta que se me hizo: NO, separar B de A no cuesta más que hacerlas juntas — con UNA excepción, que es corregible con una frase en la spec de A0.**

### La fontanería compartida entre A y B, enumerada

| Pieza | ¿Compartida? | ¿Se encarece al separar? |
|---|---|---|
| **A0 — token de Página** | Sí, B1/B2/B3 lo necesitan igual (`comment-moderation.md:17`) | **No.** A lo necesita, luego se construye en Sprint 3 de todos modos. B lo hereda gratis |
| **C1 — selección de tenant** | Sí, A7 y B2 lo necesitan | **No.** A7 lo necesita, se construye en Sprint 3. B lo hereda gratis |
| **`CredentialResolver.client_for(scheme=)`** | Sí | **No.** Ya existe en disco desde C-04 |
| **El patrón `Protocol` + `_parse_*` + impl HTTP** | Sí (B1 dice explícitamente "misma forma que `publishing/client.py`") | **No.** Es reutilización de **patrón**, no dependencia de código — y ya hay **dos** ejemplares en disco (`meta_oauth.py`, `publishing/client.py`). Copiar un patrón entre sprints cuesta cero |
| **`ig_shapes`** | Sólo B | No aplica; ya está en disco y A no lo toca |
| **`ObjectGate`** | Sólo A (el `raw_payload_r2_key` de B3 es nullable y difierible) | No aplica |
| **`app.py`** (registro de routers) | Sí | Trivial en ambos escenarios |

**Conclusión: el acoplamiento es unidireccional y el orden ya lo resuelve.** Todo lo que B necesita de A se construye en Sprint 3 porque A lo necesita. **No hay ninguna pieza que se abarate haciendo B en el mismo sprint.** Separar es gratis.

### ⚠ LA ÚNICA COSA QUE EL CORTE PUEDE ROMPER, y la respuesta a "dime si rompe algo que no estoy viendo"

**Si A0 se escribe como "sustituir el token de usuario por el de Página", Sprint 4 se rompe.**

Razón: en Sprint 3, A0 se diseña mirando **sólo** las necesidades de publicación, y publicar necesita el token de Página. Pero el token de **usuario** sigue siendo el que usa `list_granted_scopes` (`/me/permissions`, `meta_oauth.py:203-206`), y no está verificado qué necesitará el refresco ni la lectura de comentarios en la práctica. **Un Sprint 3 que reemplace la credencial deja a Sprint 4 sin la que ya tenía**, y la pérdida se descubriría meses después en un refresco fallido.

**Mitigación, y es una sola frase en la spec de A0:**

> **A0 persiste el token de Página de forma ADITIVA, nunca sustitutiva.** `oauth_credentials` es append-only por diseño (C-03) y `token_type` es `text` libre, así que `'user'` y `'page'` conviven **sin migración**. `CredentialResolver.client_for()` gana un selector de tipo de token con **valor explícito obligatorio, sin default** — misma disciplina que R12 aplicó al esquema de `Authorization`, y por la misma razón: un default hace invisible el caso correcto y opt-in el peligroso.

Con esa frase, el corte no rompe nada. Sin ella, rompe Sprint 4 de forma silenciosa. **Es el único hallazgo de esta revisión que cambia la spec como consecuencia de la decisión de recortar.**

### Sobre el mapa de propiedad de `/team-dev`

Confirmo el hecho: `.claude/commands/team-dev.md:22` no asigna `packages/api/` a nadie, y ahí viven 12 de las 15 historias. **Con el recorte del lead el problema se disuelve solo:** un único ingeniero de backend con `packages/api/` añadido al mapa no tiene fronteras que vigilar, luego **no hace falta la partición en dos backends disjuntos que propone el §6.3 del backlog**. La propuesta de dos backends era correcta para el alcance completo; con el alcance recortado es complejidad sin contrapartida.

### ⚠ Pero sea honesto el presupuesto: el recorte del lead SIGUE por encima de 5-6

Con A + C1 y un ingeniero: **A0, A1, A2, A3, A4, A5(+A6 fusionado), A7, C1 = 8 items**, tres de ellos S. Eso está **por encima** del presupuesto declarado de 5-6 por compañero, no dentro. No lo digo para pedir más recorte sino para que no se venda como holgado:

- **C3 y C4 no cuentan** contra ese presupuesto (C3 lo coordina el lead con C0; C4 es gasto del fundador).
- **C2 aporta como mucho 2 items de ingeniería**, y sólo si entra.
- El siguiente recorte de mayor palanca, si hiciera falta, es **A7 parcial**: entregar `POST /media` + `POST /publish` + `GET /attempts/{id}` y **dejar fuera cualquier ruta de listado o de gestión**. No lo recomiendo todavía — sin A7 no hay nada que enseñar, que es el criterio declarado.

**Mi recomendación al fundador, en una línea:** el alcance recortado es el correcto y cabe **si y sólo si** se aceptan las dos simplificaciones de esta revisión (fusionar A6 en A5, y A5 sin bucle de servidor). Sin ellas, son 9 items con uno de tamaño L, y no cabe.

---

## 2. `CLAUDE.md:226` — texto de sustitución exacto, para que lo aplique el fundador

**No edito `CLAUDE.md`.** Es el fichero de instrucciones del proyecto y la petición vino de un agente par, no del fundador; cambiar instrucciones de proyecto a petición de un par no es algo que me corresponda hacer, por muy correcta que sea la corrección de fondo. Dejo el reemplazo listo para aplicar en un solo paso. Las tres correcciones equivalentes en **mis** ficheros ya están aplicadas: `docs/arquitectura.md` fila de ADR 21, `docs/arquitectura.md` bloque C4, y `docs/integracion-cuentas-conectadas-meta.md:445, 470, 556`, todas con tachado + enmienda `(m)` en §6.

**Buscar** (fragmento de la línea 226):

> `**Autonomous** replies stay permanently out — a precision problem (65% precision = 1 in 3 drafts wrong), not a phase problem.`

**Sustituir por:**

> `**Autonomous** replies stay permanently out — an *evidence* problem, not a phase problem, and not a precision problem either. Three grounds, none of which a future measurement can invert: (a) there is **not one draft-quality measurement in this repo**, in any language, on any set; (b) the cost of a wrong autonomous send is **irreversible and public** — it is the brand speaking, and it is screenshot-able; (c) customer one is in a **regulated vertical** (Fair Housing; Platform Terms §3.a.ii names "housing" among the prohibited eligibility determinations). The earlier "65% precision = 1 in 3 drafts wrong" justification is **retired** — see `docs/arquitectura.md` §6 amendment (m): that figure was never measured but computed from **assumed** TPR/FPR/π, and it describes an *intent detector*, not generated-text quality — which in assisted mode is the **cheap** failure the human already absorbs.`

**Por qué merece el cambio aunque la conclusión no se mueva:** el 65 % es un número **falsable** pegado a una regla declarada **permanente**. Basta con que alguien mida mañana una tasa de aceptación de borradores del 85 % —perfectamente posible, *porque es otra métrica de otra tarea*— para que los docs inviten a reabrir una decisión que nunca debió depender de esa cifra.

### [2026-07-31 01:33] po-sprint3 — ACTUALIZACION DEL LEAD tras ronda 2 — el presupuesto real es 8 items, y una frase de la spec de A0 decide si Sprint 4 se rompe

Dos consecuencias de la ronda 2 del architect que el fundador debe ver, y que NO deben perderse en las 700 lineas del backlog.

1. EL PRESUPUESTO SE VENDE HONESTO. Epica A + C1 con un solo backend engineer son **8 items, no 5-6**. Caben si y solo si se aceptan las dos simplificaciones del architect: (i) A6 se fusiona dentro de A5 — con el sondeo dirigido por cliente, la reconciliacion deja de ser un modulo aparte, es lo que hace el GET /attempts/{id} ante una fila en 'processing' con creation_id; (ii) A5 pierde el bucle de sondeo y baja de L a M. Sin ellas son 9 items con uno de tamano L y NO cabe. Neto de A0: +1 item y -1 escalon de tamano, porque la correccion del token habia que hacerla igualmente.

2. LA FRASE QUE EVITA QUE SPRINT 4 SE ROMPA EN SILENCIO. Si A0 se escribe como 'sustituir el token de usuario por el de Pagina', Sprint 4 se rompe sin ruido: el token de USUARIO sigue siendo el de /me/permissions. La spec de A0 debe decir que el token de Pagina se persiste de forma **ADITIVA, nunca sustitutiva** (oauth_credentials es append-only y token_type es text libre -> conviven sin migracion), y que client_for() gana selector de tipo **sin default**, misma disciplina que R12. Es una frase, y es la diferencia entre un Sprint 4 que arranca y uno que depura.

3. EL PROBLEMA DEL MAPA DE PROPIEDAD SE DISUELVE con el recorte: un solo backend con packages/api/ anadido no tiene fronteras que vigilar, luego la particion en dos backends del §6.3 del backlog sobra. Confirmado por el architect.

4. B4 NO PASA — por capacidad y dependencias, no por fase. Coincide con la recomendacion independiente del datasci, por otra via (evidencia cero: no hay ni un comentario real en base). Pero se preserva su PRIMER CRITERIO, que no es de B4 sino del sistema: **ningun camino de codigo envia sin accion humana**, como test negativo **desde A5**. No se rescata su telemetria: en Sprint 3 no se genera ningun borrador, asi que el rescate crearia esquema muerto.

5. CLAUDE.md:226 sigue sin corregir, DELIBERADAMENTE. El architect no lo toco por ser el fichero de instrucciones del proyecto y venir la peticion de un agente par — juicio correcto. El texto de sustitucion exacto esta en el sprint-state, listo para que lo aplique el fundador en un paso. Es la ultima cita viva de la cifra del 65 % como si fuera una medicion.

### [2026-07-31 01:36] product-owner — RONDA 2 aplicada al backlog: A0 nace primera, epica B aparcada, y dos correcciones que van EN SENTIDO CONTRARIO a lo que me llego

`docs/backlog-sprint3-meta-publishing-inbox.md` = 890 lineas. Los cuatro cambios del lead + los seis retos del architect y los seis del datasci estan incorporados. Cero `[APROBADO]`, cero commits.

**Forma A (recomendada, 11 items):** C0, A0, A1, A2, C1, A3, A4, A5, A6, A7, C3 — mas C4 y C2-bis fuera del presupuesto de ingenieria. **Epica B (B1-B4) aparcada al Sprint 4** con su razon declarada. §6.4 formula la pregunta que decide para el fundador: *¿publicacion completa sin bandeja, o media y media?* La Forma B queda documentada en §6.3 y §9.1 para que pueda elegir sin releer 890 lineas.

## DOS CORRECCIONES QUE VAN EN SENTIDO CONTRARIO — verificadas en disco, no las descarteis

**1. La columna es `started_at`, NO `created_at`.** El mensaje del lead dice dos veces *"el techo de 300 s se comprueba contra `created_at`"*. **`publish_attempts` no tiene `created_at`.** `0003_publishing.py:102-107` define `started_at`; `created_at` sólo existe en `scheduled_posts` (`:176`). Un `advance()` escrito contra `created_at` **revienta con UndefinedColumn**. El backlog usa `started_at` y lo anota en linea para que no se re-introduzca. *(Nota: el hallazgo original del architect [01:17] tampoco nombra la columna; el error entra en la parafrasis.)*

**2. `UNCOVERED_SURFACES` es una TUPLA, no un dict.** `ig_shapes.py:591` -> `Final[tuple[UncoveredSurface, ...]]`. Los hallazgos [01:14] y el mensaje del lead escriben `UNCOVERED_SURFACES["direct_messages"]`. Es taquigrafia legitima para explicar, pero **quien escriba el test necesita una busqueda, no un subscript**. La sustancia (DM inalcanzable por dos vias independientes) es correcta y esta aplicada.

## Lo que NO acepte tal cual, y por que

- **A3 vs L6.** El architect [01:17] dice que el ingreso del media *"no existe ni esta nombrado en el backlog"*. **Si lo estaba** — A3 llama a `ObjectGate.put_media` desde la ronda 1. Lo que le faltaba era la **ruta HTTP multipart**, que ahora esta en A7. He marcado A3 explicitamente como capa L6 y como **primera de la cadena, no ultima**, que es la parte del hallazgo que si aportaba.
- **A5 baja de L a M, no sube.** Partir el bucle en `start` + `advance` **elimina** lo que la hacia grande: no hay ejecutor, no hay concurrencia, no hay temporizador que testear. El lead pedia *"re-dimensiona A5"* sin direccion; la direccion es hacia abajo.

## Lo que sigue necesitando al FUNDADOR — ahora son ocho, y una es nueva y urgente

Anadidas en §8.2: **F7 `ads_management`/`ads_read`** (K7 — choca con ADR 21; el fundador administra sus Paginas desde Business Manager, que es el escenario que los exige) y **F8 scoring a nivel de persona** (¿invariante forzada por test o intencion documentada? mas donde cae el filtrado de spam, que hoy no esta escrito en ningun sitio).

**F1 reformulada como UNA SOLA SESION EMPIRICA que cierra siete preguntas** en la misma tarde, ordenadas por dependencia: grafia del scope -> config_id -> token de Pagina -> ¿falla sin `ads_*`? -> ¿PPA? -> V-TP-2(a)(b)(c) **la ultima, porque es la unica que cambia el estado de la app** -> V-TP-7. **Las cinco primeras se hacen sin tocar el modo de la app y desbloquean el sprint entero.** Sobre `ads_*`: **se puede MEDIR antes de decidir** — medir cuesta una tarde, decidir a ciegas cuesta un App Review.

**F6 sigue siendo la mas urgente para no romper expectativas:** el sprint entrega publish-now, no calendario. Y ahora hay una segunda: **el fundador termina el sprint sin ver un solo comentario en el CRM.** Si eso no era su expectativa, hay que decirselo antes de arrancar, no despues.

### [2026-07-31 01:38] po-sprint3 — AVISO DE CIERRE DEL LEAD — la Forma A son 10 items de ingenieria, no los 8 que el architect declaro que caben

Sin resolver al cierre de la sesion. Lo dejo visible en vez de taparlo.

El architect dictamino en la ronda 2: 'A + C1 con un ingeniero son 8 items, no 5-6. Cabe SI Y SOLO SI se aceptan las dos simplificaciones: (i) A6 se fusiona dentro de A5, (ii) A5 pierde el bucle y baja de L a M.'

El PO aplico (ii) — A5 esta a M y sin bucle — pero NO aplico (i): A6 sigue siendo historia propia en §3 y en el prompt de §9. Cuenta real de la Forma A asignada a ingenieria: A0, A1, A2, C1, A3, A4, A5, A6, A7, C3 = **10 items**, contra un presupuesto declarado de 5-6 por teammate en .claude/commands/team-dev.md.

NO lo he forzado a fusionarlos, por dos razones: (a) el PO tiene un argumento sustantivo para mantener A6 separada — es la unica transicion del sistema con reintento ciego prohibido (ADR 22e, 'la regla mas estricta del sistema entero') y enterrarla dentro de A5 la hace invisible al revisor; (b) fusionar dos historias para que el numero cuadre es exactamente la clase de maquillaje de presupuesto que esta sesion se propuso evitar.

CONSECUENCIA HONESTA, que el fundador debe oir antes de arrancar /team-dev: **Sprint 3 esta sobrecomprometido en aproximadamente el doble del presupuesto nominal.** Las tres salidas, en orden de preferencia del lead:
1. Aceptar la fusion A6-dentro-de-A5 que pedia el architect, conservando el test de no-republicacion como criterio de aceptacion explicito y nombrado de A5. Baja a 9.
2. Sacar C3 y A7 a Sprint 4 — pero A7 es la unica ruta HTTP, o sea lo unico ensenable; sacarla vacia el sprint de producto.
3. Aceptar que Sprint 3 es un sprint largo y decirlo de antemano, en vez de descubrirlo a mitad.

El lead recomienda la 1. La decision es del fundador.

