# Sprint 3 — Forma C: MVP demo de publicación en Meta

> **Estado: BORRADOR DE TRABAJO.** Nada aquí está `[APROBADO]` ni firmado. Ningún commit, ningún push.
> Autor: product-owner, sesión del **2026-08-05**. Encargo: **recortar el Sprint 3 a un MVP demostrable**, por decisión del fundador tomada hoy.
> Documento de referencia (evidencia, parking lot, decisiones invalidadas): **`docs/backlog-sprint3-meta-publishing-inbox.md`**. Este fichero **no lo sustituye**: lo recorta y lo cita.

## Índice

- §0 Por qué un fichero nuevo y no una cuarta forma dentro del anterior
- §1 La demo, en una frase — y lo que la demo NO demuestra
- §2 Deriva verificada contra disco (2026-07-31 → 2026-08-05)
- §3 Forma C — lo que ENTRA (9 items, una developer)
- §4 Lo que SALE, con su razón y su destino
- §5 Precondiciones que NO son ingeniería
- §6 Los riesgos que este recorte introduce
- §7 Si 9 items siguen siendo demasiado: las dos únicas demos más pequeñas que existen
- §8 Decisiones que aún necesita el fundador
- §9 Prompt de arranque para `/team-dev` (una sola developer, sin contexto del repo)

---

## §0 Por qué un fichero nuevo y no una cuarta forma dentro del anterior

`backlog-sprint3-meta-publishing-inbox.md` tiene 891 líneas y hace de **expediente**: la herencia de backlogs previos (§1), las cinco decisiones invalidadas que no hay que reimplementar (§1.3), la verificación de código (§2), el parking lot con fase propietaria (§7) y los conflictos abiertos (§8). Todo eso sigue vigente y **no se duplica aquí**.

Lo que el fundador ha pedido es otra cosa: **un documento que una sola developer sin contexto pueda ejecutar**. Meter una "Forma C" en la §6.3 de un documento de 891 líneas obliga a leer las 891 para saber qué queda dentro. Este fichero es el ejecutable; aquél es la referencia. Ambos se cruzan por ID de item (A0, A1, A3…), que se conserva sin renumerar precisamente para que el cruce sea trivial.

**Se ha añadido un puntero al principio del documento anterior** para que nadie lo ejecute creyendo que sigue siendo el alcance vigente.

---

## §1 La demo, en una frase — y lo que la demo NO demuestra

### 1.1 La frase

> **El fundador sube un vídeo por `POST /api/media` autenticado con `Authorization: Bearer <token>`, dispara `POST /api/publishing/attempts` con su `idempotency_key`, repite `GET /api/publishing/attempts/{id}` hasta que el intento queda `published`, y el reel (o la historia) aparece en la cuenta de Instagram real que él administra.**

Verificable, en presente, sin adjetivos. Todo lo que hay en esa frase existe al final del sprint o el sprint no está terminado.

### 1.2 Lo que la demo NO demuestra — y no por falta de trabajo

- **No demuestra visibilidad pública, y no puede.** En Development Mode, *"any data generated while an app is in Development mode, such as test posts, **can only be seen by role users**"* (Meta, App Modes) y, por fuente de campo independiente, *"**posts with media are only visible to app developers/testers** — everyone else sees the post without the image"* (Postiz). Ambas citas en `integracion-cuentas-conectadas-meta.md:353-354`. **La media es exactamente lo que degrada**, que es justo lo que publica la Parte 4-A. El fundador verá su reel; un tercero desconectado, no. **Ningún criterio de aceptación de este sprint afirma lo contrario.**
- **No demuestra que se atiendan mensajes directos.** Los DM no son construibles ni testeables hoy, por **dos verjas independientes** (`integracion-cuentas-conectadas-meta.md:567`, K3.8): (a) con Standard Access la app sólo interactúa con quien tiene **rol en la app** — un cliente real que manda un DM no lo tiene; (b) el titular debe activar a mano *Instagram > Ajustes > Mensajes > Controles > Herramientas conectadas*, **acción humana no concedible programáticamente, que ni la verificación desbloquea**. No es deuda: es una superficie cerrada.
- **No demuestra bandeja de ninguna clase.** Ni comentarios. Ver §4 y §7.
- **No demuestra publicación programada.** Se entrega **publish-now**. Cero Celery en el repo (verificado hoy: `grep -rlc celery` → cero coincidencias) y no se introduce.
- **No demuestra publicación de imágenes.** No existe variante resumable para imagen (`client.py:59`). Sólo vídeo: `REELS`, `STORIES`, `VIDEO`.
- **No demuestra TikTok.** Bloqueado sin fecha por ADR 21 (firmada).

---

## §2 Deriva verificada contra disco (2026-07-31 → 2026-08-05)

El backlog anterior se escribió el 2026-07-31. Verificado hoy, punto por punto. **Donde disco y documento discrepan, gana el disco.**

| Afirmación del backlog del 07-31 | Verificado hoy 2026-08-05 | Veredicto |
|---|---|---|
| `publishing/` tiene sólo el cliente; no hay modelos, repositorio, servicio ni composición | `ls packages/api/src/qualify_api/publishing/` → `__init__.py`, `client.py` | ✅ **VIGENTE** |
| `http/` tiene sólo `app.py` y `connections_routes.py` | confirmado | ✅ **VIGENTE** |
| `config_id` → cero ocurrencias | `grep -rn config_id packages/ Qualify/` → cero | ✅ **VIGENTE** |
| `boto3` no declarado en ningún `.toml` | `grep -rn boto3 --include="*.toml" .` → cero | ✅ **VIGENTE** |
| Cero llamadas a `put_media` fuera del gate y sus tests | confirmado | ✅ **VIGENTE** |
| `.env` tiene cuatro variables, todas de Meta; ninguna `QUALIFY_R2_*` | confirmado: `QUALIFY_META_APP_ID`, `_REDIRECT_URI`, `_SCOPES`, `_APP_SECRET` | ✅ **VIGENTE** |
| Cero ocurrencias de `deauthorize` / `data_deletion` | confirmado | ✅ **VIGENTE** |
| Migraciones `0003_publishing` y `0004_inbox` aplicadas, con trigger `publish_attempts_settle_once` y ambos CHECK | confirmado leyendo `0003_publishing.py:50-142` | ✅ **VIGENTE** |
| **C0: el `.venv` está corrupto y "cualquier criterio que diga *los tests pasan* es hoy INVERIFICABLE"** | **`uv run --no-sync pytest -m "not integration" -q` → 298 passed en 2,71 s.** Pero `.venv/bin/python -c "import qualify_shared"` → `ModuleNotFoundError` para los cuatro paquetes | 🟡 **PARCIALMENTE OBSOLETO — cambia el arranque del sprint. Ver abajo.** |
| **`CLAUDE.md`: "147/147 verde offline"** | **298/298** | 🟡 **OBSOLETO** (fichero del architect; no lo toco) |

### 2.1 El hallazgo que abarata el arranque: **C0 deja de ser un bloqueo**

El backlog del 07-31 abría con *"BLOQUEO DE ENTORNO, antes de asignar nada"* y exigía `rm -rf .venv && uv sync --group ml` con nadie más ejecutando nada, antes de repartir una sola historia. **Hoy eso ya no es cierto:** la suite offline corre entera y verde por la vía que el proyecto usa de verdad (`uv run --no-sync pytest`).

Lo que **sigue roto** es el intérprete desnudo: `.venv/bin/python -c "import qualify_api"` falla. Eso importa exactamente en un sitio — **el criterio de aceptación de C3**, que lo usa como prueba. Consecuencia práctica:

- **La developer arranca hoy, sin ritual previo.** Nadie pierde las dos primeras horas ahí.
- **El ritual `rm -rf .venv && uv sync --group ml` se ejecuta una sola vez, dentro de C3**, que es la historia que toca `uv.lock` de todas formas. Ahí es donde tiene que estar, no delante del sprint.
- La regla de `CLAUDE.md` sigue en pie: **nunca alternar `uv sync` ↔ `uv sync --group ml`**, y todo lo demás con `uv run --no-sync`.

---

## §3 Forma C — lo que ENTRA (9 items, una sola developer)

### 3.0 Tabla de alcance

| Orden | ID | Item | Prio | Tam | Bloquea a |
|---|---|---|---|---|---|
| 1 | **A0** | Token de **Página** (hoy se cifra el de usuario) | **P0** | S–M | A5, A6-min, A7 |
| 2 | **A1** | `config_id` en el diálogo de consentimiento | **P0** | S | A5, A7 |
| 3 | **C1** | `Principal`: autenticación mínima con credencial opaca | **P0** | M | A7, y toda prueba e2e |
| 4 | **A3** | Staging del media a R2 (capa L6) | **P0** | S | A5 |
| 5 | **A4** | Repositorio write-ahead + idempotencia (L1+L2) | **P0** | M | A5, A6-min |
| 6 | **A5** | Servicio `start()` + `advance()` (L3+L4) | **P0** | M | A6-min, A7 |
| 7 | **A6-min** | **Prohibición de segundo `media_publish`** (recorte de A6) | **P0** | S | A7 |
| 8 | **A7** | Las tres rutas HTTP (L5) | **P0** | M | — la demo |
| 9 | **C3** | Declarar `boto3` + el ritual del venv | **P1** | S | camino real de A3 |

**4 items M + 5 items S.** El presupuesto de la casa es de 5-6 items por compañero y por sprint; **esto son 9 y hay que decirlo con todas las letras** (§6.1). El architect dimensionó la Forma A en *"entre 9 y 11 items, y ésa ya es la capacidad real del sprint"*: la Forma C recorta ~3 items y aligera dos de los que quedan, pero **no baja de 9 sin cambiar la definición de demo** — ver §7.

### 3.1 Orden: es una cadena serial, no un abanico

```
A0 ─→ A1 ─┐
          ├─→ A5 ─→ A6-min ─→ A7   ← la demo
A3 ─→ A4 ─┘         (C1 debe estar antes de A7)
C1 ─────────────────────────┘
C3 ─→ (habilita el camino REAL de A3; los tests no lo necesitan)
```

L1→L2→L3→L4→L5 (modelos → repositorio → servicio → composición → rutas) es trabajo serial **sobre los mismos ficheros**. Una sola developer no es una limitación aquí: es la forma correcta de este trabajo.

---

### A0 — Token de **Página**: hoy guardamos el de usuario y Meta exige el de Página

- **Historia:** Como equipo de marketing de una marca, quiero que al conectar mi cuenta el sistema guarde la credencial que la plataforma realmente acepta, para que la primera publicación funcione en vez de fallar con un error que parece un bug del producto.
- **Criterios de aceptación:**
  - `list_linked_pages` añade **`access_token`** a la lista de `fields`. Hoy es `"id,name,instagram_business_account{id,username}"` (`meta_oauth.py:197`) y **Meta no devuelve el token por Página si no se pide**: ni un parser tolerante podría recogerlo.
  - `LinkedPage` gana `page_access_token: str | None`, **marcado `[V]`** — no se ha observado la respuesta real.
  - El callback cifra y persiste **el token de la Página elegida**, no el de usuario. Hoy `service.py:223` cifra `grant.access_token`, que viene de `exchange_code` y es **de usuario**.
  - **Sin migración.** `oauth_credentials.token_type` es `text` libre; `token_type='page'` vs `'user'` es representable hoy.
  - **Los dos `[V]` abiertos se cierran en vivo y se registran, no se infieren:** (i) ¿hay que intercambiar antes el token de usuario corto por uno largo para que el de Página sea de larga duración? (ii) ¿se sigue necesitando el token de **usuario** para algo —`/me/permissions` lo usa hoy— y por tanto hay que custodiar **dos** credenciales por conexión?
  - **Si la respuesta a (ii) es sí, se eleva al fundador/architect antes de codificarla.** Dos tipos de token por conexión es una decisión de **custodia**, no de fontanería, y la custodia de C-03 es append-only por diseño.
  - `uv run --no-sync pytest -m "not integration"` verde sin red, con doble de plataforma.
- **RECORTE respecto de la Forma A:** el aviso de **PPA (Page Publishing Authorization)** deja de ser trabajo de UI. **Se conserva como (a)** una línea en la documentación operativa que el fundador lee antes de conectar y **(b)** un desenlace distinguible en A5. Razón: en este sprint no se toca la UI Reflex, y un aviso en una UI que nadie abre durante la demo no compra nada. El hecho peligroso sigue registrado: *"there's no way for you to determine if an app user's Page requires PPA"* (`content-publishing.md:19-21`) — **no es detectable por API en absoluto**.
- **Fase:** Fase 1 Parte 4-A (remediación de C-04).
- **Evidencia:** `backlog-sprint3-meta-publishing-inbox.md` §3/A0 · `reference/meta-instagram-platform/instagram-platform/content-publishing.md:30` y `comment-moderation.md:17` (fila *Access Tokens = Facebook Page access token* en la columna *Instagram API with Facebook Login*, que es la bifurcación firmada en ADR 25) · verificado en disco: `connections/service.py:223`, `meta_oauth.py:192-200`.
- **Dependencias:** ninguna. Construye sobre `packages/api/src/qualify_api/connections/{meta_oauth,service,credential_reader}.py`.

### A1 — El diálogo de consentimiento debe pedir activos (`config_id`)

- **Historia:** Como equipo de marketing de una marca, quiero que al conectar mi cuenta el diálogo de Meta me pida explícitamente qué Página e Instagram autorizo, para que la conexión quede realmente habilitada y no aparente estar conectada sin poder publicar nada.
- **Criterios de aceptación:**
  - `MetaOAuthSettings` gana `config_id: str | None` leído de entorno (`QUALIFY_META_CONFIG_ID`), con el **mismo tratamiento de dato** que `requested_scopes` y `graph_auth_scheme`: nunca literal en código.
  - `MetaOAuthClient.authorization_url` incluye `config_id` en la query **cuando está definido** y lo **omite entero** cuando no (no manda cadena vacía — precedente exacto en `meta_oauth.py:165-168`).
  - Test sin red: con `config_id` definido la URL lo contiene; sin él, **el parámetro no aparece**.
  - Test sin red: `config_id` y `scope` **coexisten** sin que uno anule al otro.
  - **Ningún valor de `config_id` se escribe en el repo.** Va a `.env`.
  - **Test que falla si `granted_scopes` deja de persistirse.** Con `config_id`, el conjunto de permisos que el diálogo pide lo determina un artefacto de la consola de Meta que **vive fuera del repositorio, sin control de versiones**. `requested_scopes` deja de ser la fuente de verdad y `/me/permissions` (`list_granted_scopes`) pasa a ser lo único dentro del sistema que sabe qué se concedió de verdad. El código ya lo persiste verbatim (`service.py:204,219`); el criterio es que **exista un test que lo blinde**.
  - `uv run --no-sync pytest -m "not integration"` verde sin red.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** hallazgo de la sesión de campo del fundador (sin `config_id` el diálogo salta al callback sin conceder activos y `/me/accounts` devuelve **0 páginas**), registrado en `backlog-sprint3-meta-publishing-inbox.md` §3/A1 · verificado hoy: `grep -rn config_id packages/ Qualify/` → **cero**.
- **Dependencias:** ninguna. Construye sobre `connections/meta_oauth.py` y `qualify_api/config.py`.

### C1 — `Principal`: sin autenticación no hay demo que se pueda enseñar

> **Por qué sobrevive al recorte, si "autenticación" suena a endurecimiento:** hoy `POST /api/connections/start` toma el tenant de `get_dev_tenant()`, **un global de módulo** (`qualify_shared/dev.py:32`), y devuelve **409** si no hay tenant seleccionado *en el mismo proceso*. Un cliente HTTP externo —curl, Postman, el navegador del fundador— **no tiene forma de seleccionar tenant**. Sin C1, la frase de la demo (§1.1) es literalmente inejecutable.

- **Historia:** Como equipo de marketing de una marca, quiero que el sistema sepa quién soy y a qué cuenta pertenezco cuando opero desde fuera del CRM, para poder conectar y publicar sin que la API me rechace por no saber quién soy — y sin que nadie más pueda decir que es yo.
- **Criterios de aceptación:**
  - **`Principal`**: dataclass congelada `(tenant_id: UUID, user_id: UUID)`. Es el tipo que la autenticación real producirá; el resto del código no vuelve a cambiar.
  - **Resolución por credencial opaca desde entorno, sin migración:** `QUALIFY_DEV_PRINCIPALS="<token>:<tenant_uuid>:<user_uuid>,..."`. El cliente presenta `Authorization: Bearer <token>` — **presenta una credencial, no un identificador**, que es toda la diferencia entre autenticar y creerse lo que le digan.
    - ❌ **Descartada la tabla de tokens en Postgres:** parece el principio de la autenticación de verdad e invita a construir encima. El mapa de entorno **se borra de un tirón** cuando llegue la real.
    - ❌ **Descartado un `ContextVar` alimentado por cabecera `X-Tenant-Id`:** es el global con mejor higiene de hilos y **el mismo agujero de autorización**.
  - **Dependencia `current_principal()`** en un `http/deps.py` nuevo, con el patrón de `get_connect_service` (default que lanza, sobrescribible en tests). **Devuelve `401`, no `409`.** El 409 de hoy miente: dice "conflicto de estado" cuando el hecho es "no estás autenticado".
  - **Las rutas toman `principal: Principal = Depends(current_principal)`** y pasan `principal.tenant_id` a los servicios. **Los servicios no cambian**: siguen llamando a `tenant_session(tenant_id)`.
  - **`user_id` sale del cuerpo de la petición en la misma pasada.** `StartConnectRequest` omite `tenant_id` a propósito **pero declara `user_id: UUID` en el cuerpo** (`connections_routes.py:44`) — es la misma clase de bypass, menos visible: el cliente elige a quién se le atribuye la conexión, y ese `user_id` acaba en `connection_events` **como actor**.
  - **Nada de RLS se toca.** Ni el GUC, ni el `NULLIF`, ni `set_config(..., is_local => true)`, ni las políticas. `tenant_session` sigue siendo el único camino a datos de tenant; **lo único que cambia es de dónde sale el UUID que se le pasa**. `admin_session` y `credential_session` no se rozan. Test que lo afirma.
  - **`qualify_shared.dev` sobrevive con un solo consumidor legítimo:** la UI Reflex, que corre en proceso, un operador, una sesión. Se impide que nazca un segundo consumidor HTTP: una línea en su docstring y **ninguna llamada nueva a `get_dev_tenant()` desde `http/`** (verificable con `grep`).
  - Un token que no resuelve → **401**.
  - `uv run --no-sync pytest -m "not integration"` verde sin red.
- **RECORTE respecto de la Forma A:** el test `db` de dos tenants sembrados y el 403 *"principal cuyo tenant no contiene al usuario"* **se difieren**. Razón: con un mapa de entorno escrito por el propio operador, ese 403 sólo se dispara si él se equivoca al escribir su `.env`; el aislamiento real lo sigue dando RLS, que no se toca. **Se anota como deuda explícita** — cuando la autenticación real llegue, ese chequeo vuelve y deja de ser opcional.
- **Fase:** Fase 1 (fundación multi-tenant, ADR 24 — *"el identificador es fundación, no endurecimiento"*). **No es Fase 6.**
- **Evidencia:** diseño del architect recogido en `backlog-sprint3-meta-publishing-inbox.md` §5/C1 · `packages/shared/src/qualify_shared/dev.py:31-52` · `packages/api/src/qualify_api/http/connections_routes.py:13-17,40-44,72-74`.
- **Dependencias:** ninguna. **Va temprano y termina antes de la primera ruta nueva**: cada ruta escrita contra `get_dev_tenant()` habría que reescribirla después.

### A3 — Staging del media a R2: la clave que la publicación va a abrir

- **Historia:** Como equipo de marketing de una marca, quiero subir el vídeo de mi reel y que quede guardado en un sitio propio antes de que se toque la plataforma, para que un fallo a mitad de publicación no me obligue a volver a subir el archivo.
- **Criterios de aceptación:**
  - Existe un servicio de staging que recibe bytes + `content_type` + `media_product_type`, construye la clave con **`qualify_shared.objects.keys.media_key(tenant_id, connection_id, media_id)`** (nunca a mano) y escribe vía **`ObjectGate.put_media`**. Devuelve el `media_object_key`.
  - **Es la capa L6 y es la PRIMERA de la cadena, no la última.** Verificado hoy: en todo el repo **no hay una sola llamada a `put_media`** fuera de `gate.py` y sus tests. Sin esta historia la cadena entera termina en un bucket vacío.
  - **No crea fila de `scheduled_posts`.** `publish_attempts.scheduled_post_id` es nullable (`0003_publishing.py:81`) justamente para admitir publish-now. Escribir una fila de programación que nadie va a leer sería prometer un reloj que no existe.
  - **`media_product_type` se valida contra `{'REELS','STORIES','VIDEO'}`** antes de subir nada, con el mismo vocabulario que `RESUMABLE_MEDIA_TYPES` (`client.py:63`).
  - 🔴 **Trampa de parseo de historias, escrita como criterio para que no se descubra tarde:** lo que se persiste y lo que se razona es **`media_product_type`, nunca `media_type`**. Al releer un media ya publicado, `media_type` devuelve **`IMAGE`/`VIDEO` incluso para una historia**; la propiedad que distingue una historia es `media_product_type` (`0003_publishing.py:89-91`, que ya lo documenta en la columna). Guardar el campo equivocado dejaría toda consulta futura de *"¿esto fue reel o historia?"* **silenciosamente mal**. Test explícito sobre una historia.
  - Una clave fuera del prefijo `t/{tenant_id}/` **levanta `TenantPrefixViolation`** y no sube nada. Test explícito.
  - Un `content_type` vacío es rechazado. Un objeto que supera `MAX_MEDIA_BYTES` levanta `ObjectSizeExceeded` **sin dejar rastro parcial**.
  - Toda la suite corre contra un **doble en memoria de `ObjectStore`**: verde **sin red y sin boto3 instalado**.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `packages/shared/src/qualify_shared/objects/keys.py` (`media_key`, `require_tenant_prefix`) · `objects/gate.py:82-101` (`put_media`) y `:103` (`open_object` re-verifica el prefijo en lectura) · `0003_publishing.py:81,89-91` · `client.py:59-63`.
- **Dependencias:** **C3** para el camino real; **ninguna** para el camino de test.

### A4 — Repositorio de publicación: el registro write-ahead y la idempotencia

> **CONSERVADA ÍNTEGRA por decisión del fundador.** ADR 22(e) la llama *"la regla más estricta del sistema entero"*: impide publicar el mismo reel dos veces y cuesta poco.

- **Historia:** Como equipo de marketing, quiero que si el sistema se cae en mitad de una publicación quede rastro de qué se intentó, para que nadie tenga que adivinar si el post salió y para que reintentar no me duplique el reel en la cuenta.
- **Criterios de aceptación:**
  - **Existen los modelos ORM** de `publish_attempts` y `scheduled_posts` (`publishing/models.py`), espejo de `connections/models.py`. Es la capa L1 y hoy no existe.
  - `PublishAttemptRepository` con, como mínimo: `start_attempt(...)` (INSERT **antes** de cualquier llamada a plataforma), `record_creation_id(...)`, `advance_status(...)`, `settle(...)`, `find_by_idempotency_key(...)`.
  - **La fila se escribe ANTES de la primera llamada a Meta.** Test: un fallo inyectado en `create_container` deja la fila en `status='pending'` con `creation_id IS NULL` — **no deja ausencia de fila**.
  - **Idempotencia:** llamar dos veces con la misma `(connection_id, idempotency_key)` **no crea una segunda fila** y **no dispara una segunda publicación**; devuelve el desenlace del intento existente. Test con el `UNIQUE uq_attempt_idempotency` real (marca `db`) y con doble en memoria (offline).
  - **La `idempotency_key` la elige el llamante**, no se genera dentro del repositorio: es lo que hace la operación identificable desde fuera.
  - **El repositorio respeta el trigger, no lo esquiva, y lo traduce bien.** `publish_attempts_settle_once` (`0003_publishing.py:54-66,136-142`) lanza `RAISE EXCEPTION` con `ERRCODE = 'check_violation'` ante **cualquier** `UPDATE` de una fila con `settled_at IS NOT NULL`. **Prohibido** un `UPDATE ... WHERE settled_at IS NULL` que convierta el conflicto en un no-op silencioso — el trigger existe precisamente para que un segundo camino de código no lo evite (lo dice la migración, líneas 50-53). Lo correcto es **capturar `check_violation` y tratarlo como "ya liquidado" — el camino idempotente del reintento**, no como un 500. **Criterio obligatorio, con test.**
  - `settle` escribe `settled_at` **y** un `status` terminal en la **misma sentencia**: el CHECK `ck_attempt_settled_matches_status` (`:122`) lo exige — `(settled_at IS NULL) = (status NOT IN ('published','failed'))`.
  - **Ningún sexto estado.** Los permitidos son `pending`, `uploading`, `processing`, `published`, `failed` (`:116`), y el CHECK los fuerza.
  - Provenance completa en cada fila: `tenant_id`, `connection_id`, `adapter_version`, `media_product_type`.
  - Todo acceso pasa por **`tenant_session`** (RLS). Test `db`: una fila de otro tenant es **invisible**, no filtrada en Python.
  - Verde sin red; los tests de constraints/trigger llevan marca `db`.
- **RECORTE respecto de la Forma A:** se cae **`find_unsettled_by_creation_id(...)`**, cuyo único consumidor era la reconciliación completa (A6). Vuelve con A6 en el Sprint 4. **El índice `ix_attempt_reconcile (tenant_id, creation_id)` ya existe en la base** (`:130`) y no hay que crearlo entonces.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `0003_publishing.py:71-142` (columnas, `uq_attempt_idempotency`, ambos CHECK, el trigger, el índice de reconciliación) · ADR 22(e) · `integracion-cuentas-conectadas-meta.md` §4.2 regla 1 (*"write-ahead del `creation_id`… si no está escrito, la llamada no ocurre"*).
- **Dependencias:** ninguna funcional. Construye sobre `0003_publishing.py` y el patrón de `connections/repository.py`.

### A5 — Servicio de publicación: `start()` + `advance()`, con **sondeo dirigido por el cliente**

> **El bucle de sondeo en el servidor no cabe en una petición HTTP.** 60 s × 300 s significa que un `POST /publish` con el bucle completo bloquea hasta cinco minutos, más la subida. Y **sin Celery no hay dónde moverlo**. Dos salidas descartadas, con su razón: (i) `BackgroundTasks` de FastAPI — **muere con el proceso y deja la fila en `processing` para siempre**, ilusión de asincronía con cero durabilidad; (ii) Celery — **fuera de sprint**, convertiría esto en Fase 1 Parte 3.

- **Historia:** Como equipo de marketing de una marca, quiero publicar un reel desde el CRM y ver cómo avanza, para no tener que reintentar a mano ni descubrir el fallo cuando ya es tarde.
- **Criterios de aceptación:**
  - Existe `PublishService` con **dos operaciones cortas**, no una larga:
    - `start(...)` → `start_attempt` (write-ahead, `status='pending'`) → `create_container` → `record_creation_id` → `open_object` + `upload_bytes` → `status='processing'`. Devuelve el `attempt_id`.
    - `advance(attempt_id)` → **UNA** llamada a `container_status`; si `FINISHED`, llama a `publish_container` y liquida; si terminal de error, liquida a `failed`; si `IN_PROGRESS`, devuelve el estado **sin liquidar**. **Idempotente.**
  - **Ninguna función del servicio duerme, espera ni itera sobre `container_status`.** Test estático: `grep` de `sleep` / `asyncio.sleep` dentro de `publishing/` → **cero**.
  - **El techo de 300 s se comprueba contra la columna `started_at`** (`0003_publishing.py:102-107`), no con un contador de bucle ni un reloj en memoria. Un `advance` sobre un intento cuyo `started_at` supera `CONTAINER_POLL_CEILING_SECONDS` liquida a `failed` con motivo **distinguible** de un `ERROR` de contenedor. ⚠ *La columna se llama `started_at`, no `created_at` — `created_at` sólo existe en `scheduled_posts`.*
  - `CONTAINER_POLL_INTERVAL_SECONDS` es **cadencia recomendada al cliente**, documentada en el contrato de la ruta, no un `sleep` del servidor. Es lo que Meta recomienda y lo que el presupuesto de 200 llamadas/hora tolera.
  - **Los cinco `ContainerStatus` se tratan como cinco, no como un booleano listo/no-listo** (`client.py:70-85`): `FINISHED` → publica · `IN_PROGRESS` → devuelve estado sin liquidar · `ERROR` y `EXPIRED` → terminal, **jamás se reintenta hacia ellos** · **`PUBLISHED` → se asienta como éxito SIN volver a llamar a `publish_container`**.
  - **Desenlace distinguible para PPA.** Un fallo por Page Publishing Authorization se mapea a un motivo propio, **no a un `failed` genérico**. Como no hay forma de detectar por API si una Página exige PPA, un fallo de PPA registrado como error opaco son horas persiguiendo un bug que no existe.
  - **`UploadOutcome.retriable is None` se trata como desconocido, no como `False`** (`client.py:110-112`). Test con los tres valores.
  - **El token se resuelve en el momento de publicar, no en el de componer.** Si la conexión está `revoked`/`degraded`, **no publica y registra el motivo**.
  - El servicio **nunca ve un token**: obtiene sus dos clientes de `CredentialResolver.client_for(..., scheme=...)` con `graph_auth_scheme` y `rupload_auth_scheme` de settings. Test estático: `grep` de construcción de `httpx.AsyncClient` dentro de `publishing/` → cero (fuera del propio `client.py`).
  - Existe una **factoría de composición** para publicación, al estilo de `connections/composition.py` (hoy no existe su equivalente).
  - Toda la suite corre contra un `PublishClient` falso; verde **sin red**.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `packages/api/src/qualify_api/publishing/client.py:9-18` (el orden del flujo y por qué no es arbitrario), `:55-56`, `:70-85`, `:101-118`, `:231-249` · `connections/resolver.py` (`client_for`).
- **Dependencias:** **A0**, **A3**, **A4**.
- **Nota de riesgo propia:** `overview.md:43` advierte de que *"algunas funcionalidades pueden no funcionar correctamente hasta tener Advanced Access"*. Es incertidumbre real. **No la resuelve V-TP-2** y no se etiqueta como tal.

### A6-min — La prohibición del segundo `media_publish` (recorte de A6)

> 🔴 **ITEM NUEVO, creado por este recorte. Léase §6.2 antes de decidir sacarlo:** el fundador autorizó diferir **A6**, y este item es exactamente **la parte de A6 que NO se puede diferir sin abrir un agujero real de doble publicación**. Es S. Lo que se difiere es el resto de A6 (servicio de reconciliación por índice, archivado del crudo, el test negativo estático, la regla de *"el recuento de publicados se lee de la API"*), que es **recuperación ante fallo parcial**, no protección contra publicar dos veces.

- **Historia:** Como equipo de marketing, quiero que si la publicación se corta justo al enviarla el sistema **se pare** en vez de volver a intentarlo, para no encontrarme el mismo reel dos veces en mi cuenta delante de mi audiencia.
- **Criterios de aceptación:**
  - **Una vez enviado `publish_container` para un intento, ningún `advance()` posterior vuelve a enviarlo.** El intento queda marcado como *envío ya emitido* usando `platform_error_code` (columna `Text` nullable ya existente, `0003_publishing.py:95` — **sin migración**) con un código reservado y documentado, p. ej. `publish_sent_awaiting_confirmation`.
  - **Un fallo ambiguo de `publish_container` NO liquida el intento.** Ni a `published` (no consta) ni a `failed` (podría haber publicado, y el trigger `settle_once` haría esa mentira **irreversible**). Queda en `processing`, marcado, y **visible como tal**.
  - **A partir de ese punto, `advance()` sólo lee `container_status` y sólo puede terminar en:** `PUBLISHED` → liquida a `published`; `ERROR`/`EXPIRED` → liquida a `failed`; `FINISHED` o `IN_PROGRESS` → **devuelve "pendiente de confirmación" sin publicar y sin liquidar**.
  - **`_parse_publish_response` lanzando por ausencia de `id` es un caso documentado y esperado, no un bug** (`client.py:197-204`, y `content-publishing.md:316` lo describe: *"If … the media_publish endpoint does not return the published media ID, you can get the container's publishing status"*). El servicio lo captura y entra en el camino de arriba.
  - **Test obligatorio de la propiedad, no del camino feliz:** timeout inyectado *después* de enviar `publish_container` → un segundo `advance()` → **cero llamadas nuevas a `publish_container`**, verificado sobre el doble.
  - **Test obligatorio del caso lento:** el mismo escenario pero con `container_status` devolviendo `FINISHED` en el segundo `advance()` (el contenedor todavía no refleja la publicación) → **sigue sin republicar**. Éste es el test que cierra el agujero; el anterior no lo cierra solo.
  - Verde sin red.
- **Lo que este item NO hace, y hay que saberlo:** un intento que se queda en *pendiente de confirmación* y que nadie vuelve a mirar **se queda ahí indefinidamente**. No se pierde información (el `creation_id` está escrito y el índice existe), **se difiere**. Resolverlo automáticamente es A6 completa, Sprint 4.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** ADR 22(e) · `integracion-cuentas-conectadas-meta.md` §4.2 reglas 2 y 3 (*"la única transición del sistema que tiene prohibido el retry con backoff"*, *"se reconcilia contra Meta, no contra nuestra base"*) y `:538` (*"el riesgo #2 de ADR 19 se concentra entero en el paso 3… un post duplicado es un fallo visible para el público del cliente"*) · `client.py:197-204` · `0003_publishing.py:95,128-130`.
- **Dependencias:** **A4**, **A5**.

### A7 — Las tres rutas HTTP

- **Historia:** Como equipo de marketing, quiero disparar y consultar una publicación desde fuera del CRM, para gestionar la cuenta desde una sola herramienta sin depender del móvil.
- **Criterios de aceptación:**
  - Nuevo `packages/api/src/qualify_api/http/publishing_routes.py` con **tres rutas que reflejan el sondeo dirigido por el cliente**:
    - `POST /api/media` (multipart) → staging de A3 → devuelve el `media_object_key`.
    - `POST /api/publishing/attempts` → `PublishService.start(...)`, recibe la `idempotency_key` del cliente, devuelve **`202` + `attempt_id`**.
    - `GET /api/publishing/attempts/{id}` → `PublishService.advance(...)`: **una** comprobación de estado, liquidando si procede. El cliente repite el GET a la cadencia recomendada.
  - **El `tenant_id` NUNCA viene del cuerpo ni de la query.** Sale del `Principal`. El modelo Pydantic **no tiene campo `tenant_id`** — test que lo afirma sobre el esquema.
  - **Ninguna ruta bloquea más allá de lo que tarda su propio paso.** El GET no espera a que el contenedor termine.
  - **La dependencia por defecto lanza `NotImplementedError`**, no construye un cliente real (patrón de `connections_routes.py:34-37`): *"impide que un despliegue sin configurar hable en silencio con el Meta real"*. Test: la app sin configurar **no habla con Meta**.
  - **La `idempotency_key` es obligatoria** en el cuerpo. Un POST sin ella es **422**, no una clave generada por el servidor.
  - Repetir el mismo POST con la misma `idempotency_key` devuelve **el mismo `attempt_id`** y **no publica dos veces**.
  - Ningún cuerpo de respuesta ni mensaje de error contiene token, `ciphertext` ni cuerpo de respuesta de Meta (`client.py:38-39`: *"los mensajes de error llevan códigos de estado, nunca cuerpos"*).
  - Las rutas se registran en `app.py` junto a las de conexiones.
  - Tests con `dependency_overrides` y un servicio falso completo: **el flujo entero corre sin red y sin base de datos**, igual que `test_oauth_callback.py`.
- **Fase:** Fase 1 Parte 4-A.
- **Evidencia:** `packages/api/src/qualify_api/http/connections_routes.py:1-18,34-37,40-44,72-74` · verificado hoy: `http/` contiene sólo `__init__.py`, `app.py`, `connections_routes.py`.
- **Dependencias:** **A3, A4, A5, A6-min** y **C1** (precondición dura).

### C3 — Declarar `boto3` y ejecutar el ritual del venv

- **Historia:** Como equipo de desarrollo, quiero que el cliente de almacenamiento de objetos se pueda instanciar de verdad, para que el vídeo que el usuario sube llegue a algún sitio y no sólo a un doble de test.
- **Criterios de aceptación:**
  - `boto3` (y `botocore`) declarados en `packages/shared/pyproject.toml`. *(Verificado hoy: `grep -rn boto3 --include="*.toml" .` → cero.)*
  - El import perezoso de `objects/s3.py:23-25` **se mueve a nivel de módulo** y se borra la nota que explica por qué estaba diferido — pero **el guardián estático de `tests/test_object_store_sanctity.py` se queda** (lo dice su propio docstring).
  - **El ritual se ejecuta como una sola operación, con nadie más ejecutando nada:** `rm -rf .venv && uv sync --group ml`. **Nunca alternando `uv sync` ↔ `uv sync --group ml`** — eso, y no la concurrencia, es lo que corrompe el venv compartido (dos precedentes en `CLAUDE.md`).
  - Tras el ritual: `uv run --no-sync pytest -m "not integration"` **verde** y `.venv/bin/python -c "import qualify_models, qualify_shared, qualify_api, qualify_scraper"` **sin error**. *(Hoy lo primero ya pasa —298/298— y lo segundo **falla**: ver §2.1.)*
  - `R2ObjectStore` se puede **instanciar** en el workspace con settings falsos (no requiere bucket real).
- **Fase:** Fase 1 (habilitación de infraestructura de Parte 4-A).
- **Evidencia:** `packages/shared/src/qualify_shared/objects/s3.py:1-25` (el docstring que documenta la deuda y su condición de cierre) · `CLAUDE.md`, trampa operativa del venv compartido.
- **Dependencias:** ninguna. **Bloquea el camino real de A3** (no sus tests).
- ⚠ **Coordinación obligatoria:** toca `uv.lock`. Ningún otro proceso puede estar ejecutando nada mientras corre.

---

## §4 Lo que SALE, con su razón y su destino

> Regla de la casa: nada sale "porque no da tiempo". Sale con **por qué** y con **quién lo hereda**. Lo que sale y ya estaba en el parking lot de `backlog-sprint3-meta-publishing-inbox.md` §7 no se repite aquí — se hereda íntegro.

| ID | Item | Por qué sale | A dónde va |
|---|---|---|---|
| **C0** | El ritual del venv como **bloqueo previo al sprint** | 🟡 **Obsoleto, verificado hoy:** la suite offline corre 298/298 en 2,71 s. El bloqueo que justificaba parar el sprint ya no existe | **Absorbido por C3**, que es la historia que toca `uv.lock` de todas formas |
| **A2** | Resolución empírica de la grafía del scope | **Ya está hecha y no es ingeniería.** El propio backlog registra que el fundador verificó `instagram_content_publish` **dos veces contra el endpoint de autorización**, y `.env` ya tiene `QUALIFY_META_SCOPES`. Lo que queda —fijar el valor y anotar fecha y método— es **configuración y documentación** | **§5, precondición P-NE-2** (dueño: fundador). El script de resolución `integration` se difiere: no hay nada que resolver hoy |
| **A6** (todo salvo A6-min) | Servicio de reconciliación por `creation_id`, archivado de `raw_response_r2_key`, test negativo estático, *"el recuento se lee de la API"* | Decisión del fundador. Es **recuperación ante fallo parcial**, no protección contra doble publicación — **una vez que A6-min está dentro** (§6.2) | **Sprint 4**, Fase 1 Parte 4-A. El índice `ix_attempt_reconcile` ya existe en la base; no habrá migración |
| **B1, B2, B3** | Bandeja de **comentarios**: cliente de lectura, normalización, sincronización manual | Tres items M sobre una developer que ya lleva 9. Y dependen de **A0**, que es la primera pieza de la cadena de publicación | **Sprint 4**, Fase 1 Parte 4-B. Los recortes ya decididos siguen vigentes: sólo comentarios, sin scheduler, pull manual |
| **B4** | Bucle de aprobación + seam `DraftProvider` + puerta determinista | **`messages` está vacía: no existe ni un comentario real en base.** Construir el bucle de borradores antes del primer mensaje real es construir contra evidencia cero | **Sprint 4-5**, Fase 1 Parte 4-B. **Las respuestas autónomas siguen fuera y ningún sprint las desbloquea** |
| **Bandeja de DM** | Cualquier cosa que prometa "atendemos mensajes directos" | **No construible ni testeable hoy**, por dos verjas independientes (§1.2). La segunda —el toggle manual del titular en la app de Instagram— **ni la verificación la desbloquea** | **Fase 6** (cross-canal) / desbloqueo parcial en 4-B. **Si el fundador quiere DM, la respuesta no es "más ingeniería"** |
| **C2** | Endpoints `deauthorize` / `data deletion` | No es camino crítico de la demo. Barato porque `connections/revoke.py` ya existe | **Sprint 4.** Vence *"cuando el primer agente de cliente uno use el producto"*, no en App Review |
| **C4** | Aprovisionar el bucket R2 | **No es ingeniería:** es una cuenta y un gasto | **§5, precondición P-NE-3** (dueño: fundador). **Sin él, el sprint entrega código verde y ningún byte llega a Meta** |
| **C2-bis** | Política de privacidad, política de retención, `SECURITY.md`, cláusula de ToS | Cuatro entregables administrativos. **No consumen capacidad de ingeniería** | **§5, precondición P-NE-5** (dueño: fundador) |
| **PPA como aviso en la UI** | Recorte dentro de A0 | Este sprint no toca la UI Reflex; un aviso en una pantalla que nadie abre durante la demo no compra nada | **Documentación operativa + desenlace distinguible en A5** |
| **Test `db` de dos tenants + 403 cross-principal** | Recorte dentro de C1 | Con un mapa de principals escrito por el propio operador, ese 403 sólo se dispara si él se equivoca al escribir su `.env`. El aislamiento real lo da RLS, que no se toca | **Vuelve con la autenticación real**, y entonces deja de ser opcional |
| **Programación diferida** | Consumidor de `scheduled_posts`, scheduler, disparo por hora | **No hay ningún proceso capaz de despertarse a la hora programada.** Verificado hoy: cero coincidencias de `celery` en el repo; `docker-compose.yml` = `postgres` + `redis`; `packages/pipeline/` no existe | **Fase 1 Parte 3.** La DDL ya está aplicada; la historia futura la rellena **sin migración nueva**. ⚠ Descartada explícitamente la variante `POST /scheduled-posts/{id}/run`: **promete un reloj que no existe** |
| **Imágenes, carrusel, publicidad pagada, TikTok** | — | Sin cambios respecto del backlog anterior | **Parking lot §7 de `backlog-sprint3-meta-publishing-inbox.md`**, íntegro |

---

## §5 Precondiciones que NO son ingeniería

> Separadas a propósito de las que sí lo son. **Ninguna consume capacidad de desarrollo, y sin las tres primeras la demo no ocurre aunque el código esté verde.**

| # | Precondición | Dueño | Bloquea | Estado verificado hoy |
|---|---|---|---|---|
| **P-NE-1** | **Token de Página disponible**: que la Página que el fundador administra esté vinculada a la cuenta profesional de Instagram, y que él tenga rol en la app. Es la precondición dura de ADR 25, enforced como enumeración post-consentimiento | fundador | **A0** y con ella la demo entera | La conexión existe pero **muere en `link_required`** según el backlog anterior |
| **P-NE-2** | **Grafía del scope de publicación fijada en `.env`**, con **fecha y método de verificación anotados** en documentación operativa, y la nota de que `instagram_content_publishing` es **errata de la propia documentación de Meta** | fundador | A1 (interpretar la respuesta del diálogo) | ✅ Verificada dos veces contra el endpoint de autorización; `QUALIFY_META_SCOPES` ya está en `.env`. **Falta anotarla** |
| **P-NE-3** | **`config_id` en `.env`** (`QUALIFY_META_CONFIG_ID`). El valor sale de la consola de Meta y **no se escribe en el repo** | fundador | A1 | Hay un valor de la sesión de campo. **Cero ocurrencias en código, que es lo correcto** |
| **P-NE-4** | **Cuenta y bucket R2 aprovisionados** con las cuatro variables sin fallback que `R2Settings.from_env()` exige: `QUALIFY_R2_ENDPOINT_URL`, `QUALIFY_R2_ACCESS_KEY_ID`, `QUALIFY_R2_SECRET_ACCESS_KEY`, `QUALIFY_R2_BUCKET`. **El bucket NO es público** — `ObjectGate` omite `presign_get` por diseño (ADR 28b) y ADR 28a elimina la necesidad de URL pública: Meta **nunca hace `cURL` de una clave nuestra**, recibe los bytes por `rupload` | fundador (gasto) | **el primer publish real**; no los tests | ❌ `.env` tiene cuatro variables y **las cuatro son de Meta** |
| **P-NE-5** | **Los cuatro entregables administrativos (C2-bis):** política de privacidad pública y no geobloqueada · política de retención escrita · canal de reporte de vulnerabilidades (`SECURITY.md` / `.well-known/`) · cláusula en los ToS con el tenant que le prohíba violar los términos de Meta | fundador | **el primer usuario que no sea él**, no la demo | ❌ Los cuatro ausentes, verificado |
| **P-NE-6** | **Arrancar el reloj administrativo** (App Review + Business Verification) | fundador | **cliente uno**, no la demo | Trámite externo de 2-4 meses que corre en paralelo con **coste de ingeniería cero**. Cada semana que no arranca no se recupera con código |

**Nota sobre P-NE-5, entregable de retención:** el derecho de auditoría de Meta **sobrevive un año y hasta que se hayan borrado afirmativamente todas las copias** (§7.c.vii de Platform Terms). **Borrar de verdad es lo que cierra la ventana**; guardar "por si acaso" la alarga.

---

## §6 Los riesgos que este recorte introduce

### 6.1 El presupuesto se excede y no hay forma de que no

**9 items para una developer, contra un presupuesto de casa de 5-6.** No lo disimulo con tamaños optimistas: **la cadena de publicación tiene un suelo, y este es el suelo.** Cada item que se quite de los nueve rompe la frase de §1.1:

- sin **A0** la primera llamada real falla;
- sin **A1** el diálogo no concede activos y no hay `ig_user_id`;
- sin **C1** no se puede llamar a la API desde fuera del proceso (409 hoy);
- sin **A3** no hay forma de meter un vídeo en el sistema;
- sin **A4** no hay fila que escribir antes de llamar a Meta;
- sin **A5** no hay quien orqueste;
- sin **A6-min** se puede publicar dos veces (§6.2);
- sin **A7** no hay nada que enseñar;
- sin **C3** los bytes no salen del doble de test.

**Si nueve son demasiados, lo que hay que cambiar es la demo, no la lista.** Las dos únicas demos más pequeñas que existen están en §7.

### 6.2 🔴 El agujero de doble publicación que A4 sola NO cierra — y por qué A6-min es innegociable

El fundador autorizó diferir A6 sobre la base de que A4 protege contra publicar dos veces. **Leído el código, esa base es correcta sólo en parte, y la parte que falta importa.** Lo escribo entero porque es exactamente la información que pidió no esconder.

**Lo que A4 sí cierra.** `UNIQUE(connection_id, idempotency_key)` + `find_by_idempotency_key` cierran el caso frecuente: el operador pulsa "publicar" dos veces, el navegador reintenta el POST, la UI se recarga. El segundo POST encuentra el intento existente y devuelve su desenlace. **Ese agujero queda cerrado, y es el que más veces se dispara.**

**Lo que A4 no cierra, y A5 sólo cierra a medias.** El paso irreversible es `publish_container` (`media_publish`). Su modo de fallo característico está documentado por Meta y por el propio cliente: se envía la llamada, se agota el timeout o vuelve una respuesta **sin `id`** (`_parse_publish_response` lanza, `client.py:197-204`), y **no se sabe si publicó**. Bajo el diseño de A5:

1. `advance()` #1 lee `container_status` → `FINISHED` → llama a `publish_container` → timeout. La fila sigue en `processing`, sin liquidar.
2. El cliente vuelve a llamar. `advance()` #2 lee `container_status` **primero**. Si el contenedor ya refleja `PUBLISHED`, A5 lo asienta como éxito **sin republicar**. ✅ Cubierto por A5.
3. **Pero si el contenedor todavía devuelve `FINISHED`** —porque la publicación acaba de ocurrir y el estado no ha propagado— **A5, tal como está especificada, vuelve a llamar a `publish_container`.** ❌ **Dos reels en la cuenta, en público, delante de la audiencia.**

El paso 3 es el agujero. No es exótico: es la ventana de propagación de estado en la plataforma, y ocurre precisamente cuando la primera llamada **sí** funcionó. Nada en A4 lo ve, porque desde el punto de vista de la `idempotency_key` **es el mismo intento avanzando**, no un intento nuevo.

**Por eso A6-min entra y es P0.** Cuesta S: una marca en una columna que ya existe (`platform_error_code`, `Text` nullable), una rama en `advance()`, y dos tests. **El segundo de esos tests —contenedor devolviendo `FINISHED` en el segundo `advance()`— es el que cierra el agujero; el primero no lo cierra solo.**

**Si el fundador decide sacar también A6-min**, el sistema entregado publica un reel duplicado bajo un fallo de red en el peor momento posible, y **ADR 22(e) queda incumplida en código aunque el documento siga diciendo que se cumple**. Es su decisión; no es una decisión de ingeniería, y no debe tomarse sin este párrafo delante.

### 6.3 Un intento "pendiente de confirmación" se queda ahí para siempre

Con A6-min pero sin A6 completa, un intento que entró en el camino ambiguo y al que nadie vuelve a hacer `GET` **se queda sin liquidar indefinidamente**. No se pierde información —el `creation_id` está escrito y el índice `ix_attempt_reconcile` existe— pero **nadie lo resuelve solo**. Aceptable con un tenant y un operador humano que está mirando; **deja de serlo en cuanto haya clientes**. Es la misma frontera donde entra Celery.

### 6.4 Invariantes arquitectónicos que el recorte roza (y no rompe)

| Invariante | ¿Lo roza el recorte? | Veredicto |
|---|---|---|
| **ADR 22(e)** — prohibido el reintento ciego de `media_publish` | **Sí, de lleno.** Diferir A6 lo rozaría hasta romperlo | **No se rompe gracias a A6-min.** Sin A6-min, sí se rompe (§6.2) |
| **Provenance obligatoria en toda fila derivada** (regla dura de `CLAUDE.md`) | **Sí.** A6 completa incluía rellenar `raw_response_r2_key` desde el principio, *"la única traza que quedará de la primera llamada real a Meta"* | **Se difiere con contrapartida declarada:** `tenant_id`, `connection_id`, `adapter_version`, `media_product_type` y `creation_id` **sí** se persisten (A4). Lo que se pierde es **el crudo de la respuesta de Meta de la primera llamada real**, que es irrepetible. **Mitigación barata, opcional, que recomiendo:** que A5 escriba el `platform_error_code` y el `published_media_id` siempre — ambas columnas existen y no cuestan una migración |
| **RLS / `tenant_session` como única puerta** | **No.** C1 vive **por encima** de la puerta: sólo cambia de dónde sale el UUID | Intacto. Criterio explícito en C1 |
| **El `tenant_id` nunca viene del cliente** | **No.** C1 lo refuerza y de paso saca `user_id` del cuerpo | Se **mejora** |
| **Ningún token, ciphertext ni cuerpo de Meta en logs o errores** | No | Intacto; criterio en A5 y A7 |
| **Nada se construye contra ADR 29 (`[PROPUESTO]`, sin firmar)** | No. Config activa = token de usuario→Página, sin BISU ni Tech Provider | Respetado |
| **TikTok fuera** (ADR 21, firmada) | No | Respetado |
| **Respuestas autónomas fuera, permanentemente** | No — no hay nada generativo en este sprint | Respetado |

### 6.5 El recorte deja fuera la mitad del encargo que el fundador dio a la segunda developer

El encargo, literal, fue *"recrear ManyChat conectándose a Facebook Graph API para **atender mensajes** y **publicar reels e historias** en IG"*. **Este sprint entrega la segunda mitad y ninguna parte de la primera.** Y no es simetría de esfuerzo:

- **"Atender mensajes" como DM: no es diferible, es imposible hoy.** Dos verjas independientes (§1.2), una de ellas una acción humana dentro de la app de Instagram que ni la verificación desbloquea.
- **"Atender mensajes" como comentarios sobre media propia: sí es construible**, cuesta ~3 items M (B1, B3, B2) y **no cabe encima de los 9**.

Consecuencia de producto que conviene ver escrita: **una bandeja de DM que devuelva vacío es ambigua** entre "no hay mensajes" y "el titular nunca activó el acceso". Una bandeja que pinte ese silencio como cero **está mintiendo**. Es una razón más para no prometer DM ni siquiera como "vacío por ahora".

Si lo que el fundador quiere ver funcionando es *atender*, no *publicar*, la demo tiene que cambiar de sitio. Está dimensionado en §7, Forma C-alt.

### 6.6 Riesgos que este recorte **no** introduce pero siguen ahí

- **`ads_management` / `ads_read`.** Ambas tablas de requisitos dicen lo mismo: si el usuario tiene rol sobre la Página **vía Business Manager**, la app *también* necesita `ads_management` y `ads_read` (`content-publishing.md:29`, `comment-moderation.md:20`). **El fundador administra sus Páginas desde Business Manager** — es el escenario descrito, no el excepcional. Y ADR 21 declara la publicidad de pago explícitamente fuera de alcance. **Se puede MEDIR antes de decidir**: intentar publicar sin `ads_*` y ver si Meta rechaza. Medir cuesta una tarde; decidir a ciegas cuesta un App Review. → §8, F-C2.
- **PPA indetectable por API.** Si la Página del fundador exige Page Publishing Authorization, la publicación falla y **no hay forma programática de saberlo de antemano**. A5 lo hace distinguible; no lo evita.
- **`overview.md:43`** advierte de que *"algunas funcionalidades pueden no funcionar correctamente hasta tener Advanced Access"*. Incertidumbre real que **ninguna verificación pendiente resuelve**.

---

## §7 Si 9 items siguen siendo demasiado: las dos únicas demos más pequeñas que existen

> No son variantes del mismo sprint: **son otras demos**. Se presentan con su aritmética para que la elección sea informada, no para ampliar el menú.

| | **Forma C** *(recomendada)* | **Forma C-min** | **Forma C-alt** |
|---|---|---|---|
| **La demo** | Sube un vídeo por una **ruta HTTP autenticada** y el reel aparece en la cuenta real | Un **comando en la terminal** publica un reel real desde el repo | El fundador comenta desde su móvil en su propio reel y el comentario **aparece persistido** tras pulsar una ruta de sincronización |
| **Items** | A0, A1, C1, A3, A4, A5, A6-min, A7, C3 → **9** | A0, A1, A3, A4, A5, A6-min, C3 → **7** | A0, A1, C1, B1, B3, B2 → **6** |
| **Tamaños** | 4 M + 5 S | 3 M + 4 S | 4 M + 2 S |
| **Necesita R2/boto3/bucket** | sí | sí | **no** |
| **Qué se lleva puesto** | — | **No hay API.** Nada que una UI pueda llamar; C1 queda para el Sprint 4 (barato mientras no haya rutas nuevas) | **No publica nada.** El reel lo sube él a mano desde el móvil |
| **Cuándo elegirla** | Es la única que produce **producto**: la ruta que la UI de la segunda developer va a consumir | Si el objetivo es **probar que la integración con Meta funciona** y nada más | Si lo que el fundador quiere ver es **"atender mensajes"** (§6.5), en su única forma construible: comentarios |

**Recomendación: Forma C.** Razón, en una línea: **C-min entrega una demo que no se puede construir encima** —un script no lo llama una UI— y el Sprint 4 tendría que rehacer la fachada entera. C-alt es legítima y más barata, pero deja al producto sin la capacidad que el fundador nombró primero.

**Lo que no recomiendo bajo ninguna forma: mezclar mitad de publicación y mitad de bandeja.** Media cadena de publicación no publica y media bandeja no atiende. Es la razón por la que el backlog anterior ya descartó su "Forma B".

---

## §8 Decisiones que aún necesita el fundador

| # | Decisión | Por qué es suya | Qué desbloquea |
|---|---|---|---|
| **F-C1** | **¿Forma C, C-min o C-alt?** (§7) | Define qué es "enseñar funcionando" | El arranque del sprint |
| **F-C2** | 🔴 **¿Se autoriza añadir `ads_management` / `ads_read` a los scopes solicitados SI la prueba empírica demuestra que la publicación falla sin ellos** para una Página gestionada desde Business Manager? | Pedirlos **ensancha materialmente** lo que el usuario concede, es un permiso que ADR 21 aparcó a propósito, y **probablemente empuja hacia App Review antes de lo previsto**. No pedirlos puede significar que la publicación no funcione para su configuración exacta | La épica A sobre su cuenta real. **Se puede medir antes de decidir, en la misma tarde** |
| **F-C3** | **¿Confirma que A6 completa se difiere, habiendo leído §6.2?** Y en concreto: **¿A6-min entra?** | El PO recomienda **sí entra** y explica el agujero exacto que se abre si no | Si A6-min sale, el sprint baja a 8 items y **entrega publicación que puede duplicar un reel bajo fallo de red** |
| **F-C4** | 💰 **Aprovisionar cuenta y bucket R2** (P-NE-4) | Gasto y cuenta a nombre de la empresa | **El primer publish real.** Sin él, el sprint entrega código verde y ningún byte llega a Meta |
| **F-C5** | **¿Su expectativa incluye "programar" publicaciones?** Este backlog entrega **publish-now** y dice NO | Si espera un calendario funcionando hay que decírselo ahora, no al final | Define si Fase 1 Parte 3 (Celery) se adelanta |
| **F-C6** | **¿Acepta que "atender mensajes" no entra?** (§6.5) | Es la mitad del encargo que dio a la segunda developer | Si la respuesta es "no lo acepto", la demo pasa a **Forma C-alt** y la publicación se va al Sprint 4 |
| **F-C7** | ⏱ **Arrancar el reloj administrativo** (App Review + Business Verification) | Trámite externo de 2-4 meses, **coste de ingeniería cero**, corre en paralelo | Cliente uno. Cada semana que no arranca no se recupera con código |

### 8.1 Conflictos entre documentos que este recorte destapa — no los resuelvo yo

| # | Conflicto | Quién lo resuelve |
|---|---|---|
| **KC-1** | **`integracion-cuentas-conectadas-meta.md` se contradice sobre la visibilidad en Development Mode.** La línea **358** dice *"para publicar un reel público real la app tiene que estar en LIVE MODE"* (corrección del 2026-07-29, con dos fuentes primarias en `:353-354`), y la línea **603** todavía dice *"Development Mode + rol en la app = publicar hoy, gratis, **contenido público**"* | **architect** — es su fichero. La 358 es posterior y va con fuentes; la 603 quedó sin corregir. **Este backlog sigue la 358**, que además coincide con la restricción del fundador |
| **KC-2** | **`CLAUDE.md` dice "147/147 verde offline".** Hoy son **298/298** | **architect** |
| **KC-3** | El bloqueo de entorno **C0** del backlog del 07-31 está parcialmente obsoleto (§2.1) | **Resuelto aquí**, verificado contra disco. Se anota para que nadie lo reintroduzca |
| **KC-4** | Los conflictos **K1, K3, K4, K5, K7, K8** del backlog anterior (§8.1) **siguen todos abiertos** y ninguno bloquea este sprint | **architect** / **fundador**, según la tabla original |

---

## §9 Prompt de arranque para `/team-dev`

> **Dimensionado para UNA sola developer sin contexto de este repo.** Antes de pegarlo, el lead debe tener respondidas **F-C1** y **F-C3** (§8), y conviene —no bloquea— que el fundador haya puesto `QUALIFY_META_CONFIG_ID` en `.env` (P-NE-3).

```
Sprint 3 de Qualify — MVP DEMO: publicar un reel en Instagram desde una ruta HTTP.

Backlog vinculante: docs/backlog-sprint3-mvp-demo.md. Léelo entero antes de planificar.
Documento de referencia (evidencia, decisiones ya invalidadas, parking lot):
docs/backlog-sprint3-meta-publishing-inbox.md — consúltalo, NO lo ejecutes: su alcance
está superado por el fichero de arriba.

CONTEXTO MÍNIMO DEL REPO (no lo des por sabido):
- Monorepo `uv` con workspace en la raíz, Python >=3.12. Paquetes en packages/*.
- Postgres + Redis por docker compose. `just dev` levanta todo desde frío
  (up -> migrate -> seed). `just test` = `uv run pytest -m "not integration"`.
- HAY MIGRACIONES YA APLICADAS que NO debes recrear: 0003_publishing.py crea
  `publish_attempts` y `scheduled_posts`; 0004_inbox.py crea `threads` y `messages`.
  Este sprint NO añade ninguna migración. Si crees que necesitas una, párate y pregunta.
- Toda lectura/escritura de datos de tenant pasa por `qualify_shared.db.session.tenant_session`
  (RLS). Está prohibido construir un Engine o una Session en cualquier otro sitio; hay un
  test estático que lo vigila.
- El cliente HTTP de publicación YA EXISTE y está terminado:
  packages/api/src/qualify_api/publishing/client.py. No lo reescribas. Lo que falta es
  TODO lo que hay encima: modelos ORM, repositorio, servicio, composición y rutas.
- El plano de objetos (R2) YA EXISTE y está terminado:
  packages/shared/src/qualify_shared/objects/ (keys.py, gate.py, s3.py). Usa
  `media_key(...)` y `ObjectGate.put_media` / `open_object`. Nunca construyas una clave
  a mano.
- El patrón de rutas HTTP a imitar es packages/api/src/qualify_api/http/connections_routes.py.

ENTORNO — verificado el 2026-08-05, no repitas el diagnóstico:
- `uv run --no-sync pytest -m "not integration" -q` -> 298 passed. Arranca directamente.
- NO ejecutes `uv sync` ni `uv venv` salvo dentro de la historia C3, y avísame antes:
  toca uv.lock y nadie más puede estar ejecutando nada. NUNCA alternes
  `uv sync` <-> `uv sync --group ml`: eso es lo que corrompe el venv compartido.
- Todo lo demás, siempre con `uv run --no-sync`.

ALCANCE: 9 historias, en este orden. Es una CADENA SERIAL sobre los mismos ficheros
(modelos -> repositorio -> servicio -> composición -> rutas), no un abanico. No las
reordenes sin decírmelo.

  A0  Token de PÁGINA. VA PRIMERA. Hoy connections/service.py:223 cifra el token de
      USUARIO y Meta exige el de PÁGINA para publicar. meta_oauth.py:197 ni siquiera lo
      pide: falta `access_token` en `fields`. Añádelo, da a LinkedPage un
      `page_access_token: str | None` marcado [V], y persiste el de Página. SIN migración:
      oauth_credentials.token_type es text libre.
      DOS [V] que cierras EN VIVO y REGISTRAS, no infieres: (i) ¿hace falta intercambiar
      el token corto de usuario por uno largo? (ii) ¿hay que custodiar DOS credenciales
      por conexión (/me/permissions usa el de usuario)? Si (ii) es sí, PÁRATE y avísame:
      es decisión de custodia, no de fontanería.  P0 / S-M.

  A1  `config_id` en MetaOAuthSettings y en authorization_url. Se lee de
      QUALIFY_META_CONFIG_ID. Se OMITE ENTERO si no está definido (no mandes cadena
      vacía). Añade el test que falla si `granted_scopes` deja de persistirse: con
      config_id, `requested_scopes` deja de ser la fuente de verdad de lo que pedimos y
      /me/permissions pasa a ser lo único que sabe qué se concedió.  P0 / S.

  C1  `Principal`. NO es "quitar un global": es que no hay autenticación, luego no hay
      principal del que derivar un tenant. Dataclass congelada (tenant_id, user_id);
      credencial opaca desde QUALIFY_DEV_PRINCIPALS; `Authorization: Bearer <token>`;
      dependencia current_principal() en un http/deps.py nuevo que devuelve 401, NO 409.
      En la misma pasada: `user_id` SALE del cuerpo de StartConnectRequest — hoy el
      cliente elige a quién se le atribuye la conexión y ese id acaba en
      connection_events como actor.
      RECHAZADAS de antemano: tabla de tokens en Postgres, y ContextVar con cabecera
      X-Tenant-Id (mismo agujero de autorización con mejor higiene de hilos).
      NO toca RLS, ni el GUC, ni el NULLIF, ni tenant_session: vive POR ENCIMA de la
      puerta.  P0 / M. Termínala ANTES de escribir la primera ruta nueva.

  A3  Staging del media a R2 (capa L6). En todo el repo NO HAY UNA SOLA llamada a
      put_media: sin esto la cadena entera acaba en un bucket vacío. NO crees fila de
      scheduled_posts (publish_attempts.scheduled_post_id es nullable justo para
      publish-now).
      TRAMPA DE HISTORIAS, escríbela como test: persiste y razona SIEMPRE sobre
      `media_product_type`, NUNCA sobre `media_type`. Al releer un media publicado,
      `media_type` devuelve IMAGE/VIDEO incluso para una historia; lo que distingue una
      historia es `media_product_type`.  P0 / S.

  A4  Modelos ORM (publishing/models.py) + repositorio write-ahead sobre publish_attempts.
      La fila se escribe ANTES de la primera llamada a Meta.
      EL TRIGGER `publish_attempts_settle_once` lanza check_violation ante CUALQUIER
      UPDATE de una fila ya liquidada. PROHIBIDO taparlo con `WHERE settled_at IS NULL`.
      Lo correcto es CAPTURAR check_violation y tratarlo como "ya liquidado" — el camino
      idempotente del reintento — NO como un 500.
      `settled_at` y el status terminal se escriben en el MISMO UPDATE
      (ck_attempt_settled_matches_status lo exige). Estados permitidos: exactamente
      pending, uploading, processing, published, failed. Ningún sexto.  P0 / M.

  A5  Servicio + composición: `start()` y `advance()`, dos operaciones CORTAS.
      NINGUNA función duerme, espera ni itera sobre container_status — test estático:
      grep de sleep/asyncio.sleep dentro de publishing/ -> cero.
      FastAPI BackgroundTasks está RECHAZADO: muere con el proceso y deja la fila en
      `processing` para siempre.
      El techo de 300 s se comprueba contra la columna `started_at` (NO `created_at`,
      que sólo existe en scheduled_posts).
      Los cinco ContainerStatus son cinco, no un booleano: FINISHED publica; IN_PROGRESS
      devuelve sin liquidar; ERROR y EXPIRED son terminales y jamás se reintenta hacia
      ellos; PUBLISHED se asienta como ÉXITO SIN volver a llamar a publish_container.
      `UploadOutcome.retriable is None` es DESCONOCIDO, no False.
      Un fallo por PPA (Page Publishing Authorization) se mapea a un motivo PROPIO, no a
      un `failed` genérico.  P0 / M.

  A6-min  LA PROHIBICIÓN DEL SEGUNDO media_publish. Es pequeña y es la que impide
      publicar el mismo reel dos veces; lee §6.2 del backlog antes de tocarla.
      Una vez enviado publish_container para un intento, NINGÚN advance() posterior
      vuelve a enviarlo. Marca el intento con un código reservado en `platform_error_code`
      (columna Text nullable que YA existe — sin migración).
      Un fallo ambiguo NO liquida el intento: ni a published (no consta) ni a failed
      (podría haber publicado, y el trigger haría esa mentira irreversible). Queda en
      `processing`, marcado.
      DOS TESTS OBLIGATORIOS: (1) timeout tras enviar publish_container -> segundo
      advance() -> cero llamadas nuevas a publish_container. (2) EL QUE DE VERDAD CIERRA
      EL AGUJERO: el mismo caso pero con container_status devolviendo FINISHED en el
      segundo advance() (el contenedor aún no refleja la publicación) -> sigue sin
      republicar.  P0 / S.

  A7  Tres rutas en un http/publishing_routes.py nuevo:
      POST /api/media (multipart) -> devuelve media_object_key
      POST /api/publishing/attempts -> 202 + attempt_id
      GET  /api/publishing/attempts/{id} -> invoca advance(), UN paso, sin bloquear
      idempotency_key OBLIGATORIA en el cuerpo (422 sin ella; no la generes tú).
      tenant_id y user_id salen del Principal, NUNCA del cuerpo ni de la query — test
      sobre el esquema Pydantic que lo afirma.
      La dependencia por defecto lanza NotImplementedError, no construye un cliente real.
      Ningún cuerpo de error lleva token, ciphertext ni cuerpo de respuesta de Meta.
      Regístralas en app.py.  P0 / M.

  C3  Declara boto3/botocore en packages/shared/pyproject.toml y sube el import perezoso
      de objects/s3.py a nivel de módulo. El guardián de test_object_store_sanctity.py se
      QUEDA. AVÍSAME ANTES DE EMPEZARLA: toca uv.lock y hay que ejecutar
      `rm -rf .venv && uv sync --group ml` con nadie más corriendo nada.  P1 / S.

FUERA DE ALCANCE — no lo empieces "por adelantar":
- Bandeja de cualquier tipo (comentarios o DM). Los DM además NO SON CONSTRUIBLES hoy:
  dos verjas independientes, una de ellas un toggle manual del titular dentro de la app
  de Instagram que ni la verificación desbloquea. Ningún criterio puede prometer
  "atendemos mensajes directos".
- Programación diferida. Hay CERO Celery en el repo y no se introduce. `scheduled_posts`
  se queda como DDL sin consumidor y eso es CORRECTO, no deuda. NO construyas un endpoint
  manual de disparo: prometería un reloj que no existe.
- Imágenes (no hay variante resumable), carrusel como producto, publicidad pagada,
  TikTok (bloqueado sin fecha, ADR 21 firmada).
- Reconciliación completa por creation_id (A6). Sólo entra A6-min.
- Cualquier cosa que dependa de ADR 29 (BISU / Tech Provider): está PROPUESTA, sin firmar.

SUPUESTOS QUE NO SE NEGOCIAN:
- Development Mode. NINGÚN criterio de aceptación puede afirmar que un post es visible
  públicamente: en Development Mode el media sólo lo ven usuarios con rol en la app.
- Vídeo únicamente (REELS / STORIES / VIDEO) por subida resumable de bytes. Meta NUNCA
  hace cURL de una clave nuestra: recibe los bytes por rupload.facebook.com. Si lees en
  algún doc "alojar el media en una URL pública", está muerto desde ADR 28a.
- Nombres de tabla REALES: publish_attempts, scheduled_posts, threads, messages.
  publishing_attempts / inbox_threads / inbox_messages NO EXISTEN.
- Nada se marca [APROBADO]. Nada se firma. Ningún commit ni push sin pedírmelo.

PUERTA DE CALIDAD, aplicada al plan ANTES de escribir una línea:
1. `uv run --no-sync pytest -m "not integration"` verde SIN RED. Lo que necesite la
   Postgres de compose lleva marca `db`. Lo que necesite red o vendedor lleva marca
   `integration` y NUNCA entra en el run por defecto.
2. Provenance persistida en toda fila derivada: tenant_id, connection_id, adapter_version,
   media_product_type.
3. Todo acceso a datos por tenant_session (RLS). Ningún filtrado por tenant en Python.
4. Ningún token, ciphertext ni cuerpo de respuesta de Meta en un error o en un log.
5. Type hints en toda firma nueva. `just lint` limpio.
6. Ninguna decisión de esquema o de custodia se hornea sin consultarme.

Levántame cualquier cosa fuera de tu frontera (packages/api/, packages/shared/,
migrations/) en vez de editarla. Y si el disco contradice un documento, gana el disco:
avísame y sigue con el disco.
```

