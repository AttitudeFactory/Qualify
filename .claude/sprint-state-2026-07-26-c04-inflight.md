# Sprint 1 — estado 2026-07-26, C-04 en vuelo, equipo caído por límite mensual

Continuación de `.claude/sprint-state-2026-07-25-sprint1-resume.md` (que era el prompt de
arranque de ESTA sesión, ya obsoleto — no lo uses para retomar, usa este). Nada commiteado.
Verificado contra filesystem por el dev-lead, no contra reportes de agentes sin cruzar.

## Qué pasó en esta sesión

Retomé con `pipeline`/`architect`/`reflex-ui` spawneados en paralelo. Verifiqué Docker en vivo
yo mismo (los sandboxes de los agentes no tienen Docker): arreglé un Postgres nativo de Homebrew
que robaba el puerto 5432, y un `.venv` de workspace con editable-installs rotos. Encontré y
enruté al architect un defecto real de RLS (el GUC `app.tenant_id` vuelve a `''` no a `NULL` en
conexión pooled reusada — `NULLIF` es el fix, ya aplicado y verificado 18/18 en vivo). Architect
firmó esa ruling (R7/R8, `docs/arquitectura.md §6`) y aprobó el plan de C-04 de pipeline (con una
arista FSM nueva: `(REVOKED, VERIFY_FAIL) → DEGRADED`). `reflex-ui` completó su Bloque 1 (swap de
los 3 stubs de `Qualify/` por paquetes reales) — verificado en navegador, 17 tests.

**A las ~23:14 del 25/07, `pipeline` y `reflex-ui` murieron al mismo tiempo por el LÍMITE DE GASTO
MENSUAL** (no horario — mismo modo de falla que mató a todo el equipo el 23-24/07, documentado en
`.claude/sprint-state-2026-07-23-ig-crm.md`). `architect` seguía vivo/idle. **Respawnear es inútil
hasta que el fundador suba el límite** en claude.ai/settings/usage.

## Snapshot verificado contra filesystem (2026-07-26)

| Historia | Estado | Verificación |
|---|---|---|
| C-01 multi-tenant + RLS | ✅ | **18/18 en vivo** contra Postgres real (incluye el fix R7/R8 + test estructural sobre `pg_policies`) |
| C-02 envelope v2 (R5) | ✅ | offline, architect confirmó conformidad total con el spec |
| C-03 connections (custody+FSM) | ✅ | offline + vivo; **falta la arista `(REVOKED, VERIFY_FAIL)→DEGRADED`** que architect aprobó — nunca se codeó |
| C-04 flujo OAuth | 🟡 **código sólido, incompleto** | Ver detalle abajo |
| C-05 matriz permiso→capacidad | ✅ | 14/14 |
| C-06 pantalla conexiones | ✅ | Bloque 1 (stubs→real) verificado en navegador; Bloque 2 (auth_url real) bloqueado |

**Suite completa ahora mismo: `uv run pytest -m "not integration and not db"` → 112 passed, 0
failed.** (Subió de 67 a 112: +12 de C-04 que estaban en falso-rojo, +13 de `Qualify/` que no se
colectaban, +otras.) `uv run pytest -m db` → 21 passed, 1 failed (el failure es el bug preexistente
de test #10, no una regresión).

## Fix de infraestructura que apliqué yo mismo (nadie más corriendo `uv` en paralelo, seguro)

`pyproject.toml` raíz, dos cambios:
1. Añadí `pytest-asyncio>=0.24.0` al grupo `dev` + `asyncio_mode = "auto"` en
   `[tool.pytest.ini_options]`. Sin esto, los 12 tests de `test_oauth_callback.py` (async, contra
   `httpx.AsyncClient`) fallaban con "async def functions are not natively supported" — **no era
   un bug de lógica de pipeline, era una dependencia de test que faltaba**. Con el fix: los 12
   pasan limpio.
2. Añadí `"Qualify"` a `testpaths` (pedido explícito de reflex-ui en su reporte de Bloque 1): antes
   un `uv run pytest` pelado no coleccionaba los tests de C-06.

Corrí `uv sync` (default groups) y luego `uv sync --group ml` (el primero desinstala
`qualify-models`/torch porque `ml` no está en `default-groups` — necesario de nuevo porque
`Qualify/capabilities.py` ahora importa `qualify_models.permission_capability` en real).

## C-04 — qué hay y qué falta, verificado contra disco

**Código que SÍ aterrizó** (`packages/api/src/qualify_api/`): `config.py`,
`connections/{state_token,meta_oauth,credential_reader,read,repository,service,verifier}.py`,
`http/{app,connections_routes}.py`; `packages/shared/src/qualify_shared/db/credential.py`
(el `CredentialReader` que C-03 había diferido); `access_posture` cableado en
`connections/models.py` + migración 0002. Tests: `test_oauth_callback.py` (12, verdes),
`test_oauth_state.py`. Cubre: state HMAC + jti de un solo uso, login-fork post-consentimiento,
`granted_scopes` crudos, verify vía `CredentialResolver`, upsert idempotente, nace `degraded` si
falla el verify.

**Lo que falta, confirmado por grep, no por suposición:**
1. **Arista FSM `(REVOKED, VERIFY_FAIL) → DEGRADED`** — architect la aprobó explícitamente
   (mensaje "Q2"), nunca se escribió en `packages/api/src/qualify_api/connections/fsm.py`. Sin
   test tampoco.
2. **Servicio `revoke_connection`** — no existe en `packages/api/connections`. reflex-ui construyó
   un workaround directo en la UI contra el FSM con `TODO(C-03)` explícito para no bloquearse;
   es deuda consciente en la frontera equivocada, hay que cerrarla.
3. **Contrato pipeline→reflex-ui** — pipeline prometió mandarles `list_connections(tenant_id)` y
   `start_connect(tenant_id, brand_id, user_id) -> authorization_url` como funciones Python
   directas (no HTTP). No está claro si ese mensaje salió antes de morir; el propio reporte de
   reflex-ui dice que su Bloque 2 (swap de `/oauth/start` al endpoint real) sigue bloqueado
   esperándolo.
4. **`access_posture` en el callback** — la columna existe (NOT NULL), pero architect señaló que
   debe poblarse desde config, no una constante — verificar que `service.py` lo hace así.

## Deuda archivada, no bloqueante (tasks #9, #10)

- **#9** — `object_id` sin validar en el validador del envelope de C-02
  (`packages/scraper/shared.py`) permite traversal `../` en el store de disco (dev-only, R2 no
  afectado). Hallazgo del architect, fix propuesto: rechazar `/`, `..`, vacío, control chars en el
  validador Pydantic.
- **#10** — `test_credential_role_can_read_ciphertext` (`test_connections_schema.py:135`) hace
  `SELECT ciphertext, key_id FROM oauth_credentials` sin `WHERE` + `.one()`; rompe si se corre la
  suite `db` dos veces seguidas sin `docker compose down -v` entre medio (RLS deja pasar TODAS las
  filas acumuladas del tenant, no sólo la de este test). No es regresión de R7/R8, preexistía.

## Decisión pendiente del fundador — NO resuelta, no es del equipo

**ADR 25 (Facebook Login for Business, login fork) sigue en `[PROPUESTO]`** pero ya está
materializada en DDL aplicado y verificado en verde (`social_connections.linked_page_id NOT NULL`)
y es la base sobre la que se construyó todo C-04. ADR 26/27 (mismo tipo de ruling técnico del
architect) ya se firmaron el 25/07. El architect corrigió de paso una contradicción real dentro de
la propia ADR 25 (decía "detectar la Página antes de lanzar OAuth", cuando R4 doce líneas abajo ya
había corregido eso a "se detecta después, en el callback") — la decisión en sí no cambió, sólo el
texto que la contradecía. Pendiente: que el fundador la pase a `[APROBADO]` o pida discutirla.

## Actualización — dev-lead cerró #9/#10 y el sync de `CLAUDE.md` mientras el equipo seguía caído

Con `pipeline`/`reflex-ui` indisponibles y `architect` sin más trabajo posible (docs-only), el lead
tomó directamente los dos hallazgos ya diagnosticados por completo, sin superficie de diseño —
NO tocó nada de C-04 en sí (arista FSM, `revoke_connection`), eso sigue siendo de pipeline:

- **#9 cerrado.** `RawPayloadEnvelope` gana `_check_object_id_is_not_a_traversal`
  (`packages/scraper/src/qualify_scraper/shared.py`): rechaza caracteres de control y segmentos
  de ruta vacíos/`.`/`..`, validando POR SEGMENTO (no bloqueando `/` en general, porque
  `object_id` multi-segmento como `"17895/comments/p2"` es legítimo — hay un test que ya lo
  ejercita). 13 casos parametrizados nuevos + 1 test de sanidad, 38/38 verde en el fichero.
- **#10 cerrado.** La query sin `WHERE` de `test_credential_role_can_read_ciphertext` ahora filtra
  por `connection_id`. Verificado corriendo la suite `db` de ese fichero **3 veces seguidas sin
  `down -v` entre medio** — 6/6 las tres veces.
- **Limpieza de ruff sobre el código de C-04 que dejó pipeline** (`ruff check --fix` +
  `ruff format` sobre `packages/api`): un import sin usar, un bloque de imports desordenado, y
  varias líneas largas que el formatter envolvió. Cero cambios semánticos, sólo estilo.
- **`CLAUDE.md` sincronizado por el architect**, verificado limpio por el lead (cero frases
  obsoletas, cero bullets duplicados) — ver el mensaje de architect en el hilo para el detalle.

**Trampa operativa nueva, real, y se repitió DOS VECES en esta misma sesión sin que hubiera dos
agentes corriendo `uv` a la vez:** alternar entre `uv sync` (grupos por defecto, sin `ml`) y
`uv sync --group ml` corrompe el mecanismo de editable-install del venv compartido — los
paquetes quedan registrados (`uv pip list` los muestra) pero `import qualify_models` (etc.) falla
igual que si el venv nunca se hubiera sincronizado. **No es un problema de concurrencia como se
pensaba** — pasó en secuencia, un solo agente, dos veces. Único fix que funcionó las dos veces:
`rm -rf .venv && uv sync --group ml`. Recomendación para quien retome: evitar el toggle, sincronizar
siempre con `--group ml` si `Qualify/` va a correr sus tests (ahora en `testpaths`), y considerar
mover `qualify-models` a `default-groups` o documentar esto como trampa #3 en `CLAUDE.md` junto a
las otras dos que ya anotó el architect.

**Suite completa ahora mismo, verificada tras todo lo anterior:**
`uv run --no-sync pytest -m "not integration"` → **147 passed, 0 failed**.
`uv run --no-sync pytest -m "db"` → **22 passed, 0 failed**.

## Orden de respawn (sólo cuando el fundador confirme el límite subido)

1. **pipeline** — retoma exactamente los 4 gaps de C-04 de arriba (arista FSM, `revoke_connection`,
   el mensaje de contrato a reflex-ui, verificar `access_posture`), más #9 y #10 si hay tiempo.
   Recordarle: NO correr `uv sync` a menos que sea imprescindible (el venv ya está sano, con
   `pytest-asyncio` y `ml` sincronizados); si hace falta, avisar al lead primero.
2. **reflex-ui** — Bloque 2 (swap de `/oauth/start` al endpoint real) en cuanto pipeline mande el
   contrato de los seams. Puede seguir trabajando en paralelo con pipeline sin pisarse (ficheros
   disjuntos).
3. **architect** — sigue disponible sin límite (a la 23:14 del 25/07 seguía vivo). Puede revisar la
   arista FSM nueva y el `revoke_connection` cuando pipeline los entregue; mientras tanto, nada
   urgente pendiente de su lado salvo el sync final de `CLAUDE.md`/§6 cuando C-04 cierre del todo.

## Objetivo demostrable, sin cambios

Conectar por OAuth la cuenta real de IG de la tienda desde el CRM, verla sana en `/connections`
contra el backend real, `uv run pytest -m db` en verde probando que ningún tenant alcanza los
datos ni el token de otro. **Está más cerca de lo que el prompt de arranque de esta sesión
asumía** — el código de C-04 es sustancialmente bueno, sólo le faltaban 4 piezas puntuales y un
plugin de test.

---

## Contrato pipeline→reflex-ui (C-04) — CERRADO, escrito a disco 2026-07-26

Los 3 gaps de C-04 están cerrados. Ésta es la interfaz **final y verificada** que `Qualify/`
debe consumir en su Bloque 2. Son **funciones Python directas, no HTTP**: la UI corre en el
mismo proceso, así que un POST a su propio localhost sería un round trip de serialización
inútil que además pierde los tipos de excepción.

### Import único

```python
from qualify_api.connections import (
    ConnectionNotFound,
    ConnectionSummary,
    InvalidTransition,
    RevokeResult,
    list_connections,
    revoke_connection,
    start_connect,
)
```

Los tres nombres están re-exportados en `packages/api/src/qualify_api/connections/__init__.py`
(`__all__`). El wiring real vive en `connections/composition.py`; `http/app.py` ahora delega
ahí, de modo que HTTP y UI comparten **una sola** composición (y un solo `EventPublisher`).

### Firmas exactas

```python
def list_connections(tenant_id: UUID) -> tuple[ConnectionSummary, ...]: ...
    # qualify_api.connections.read — YA EXISTÍA, sin cambios.
    # Orden: más reciente primero (ORDER BY connected_at DESC).

def start_connect(*, tenant_id: UUID, brand_id: UUID | None, user_id: UUID) -> str: ...
    # qualify_api.connections.composition
    # Devuelve la authorization_url de Meta a la que redirigir.

def revoke_connection(
    *, tenant_id: UUID, connection_id: UUID, actor: str = "user"
) -> RevokeResult: ...
    # qualify_api.connections.composition
```

**`start_connect` y `revoke_connection` son keyword-only a propósito.** Tres UUID del mismo
tipo en fila es exactamente la firma donde un swap posicional compila, pasa el type-check y
conecta silenciosamente el tenant equivocado.

### Tipos de retorno

`ConnectionSummary` (frozen dataclass, `connections/read.py`) — sin cambios, credential-free
por construcción: `connection_id: UUID`, `brand_id: UUID | None`, `platform: str`,
`external_account_id: str`, `external_username: str | None`, `status: str`,
`granted_scopes: tuple[str, ...]`, `access_posture: str`, `last_verified_at: datetime | None`,
`connected_at: datetime`.

`RevokeResult` (frozen dataclass, `connections/revoke.py`) — exactamente tres campos:
`connection_id: UUID`, `status: ConnectionStatus`, `changed: bool`.
`changed is False` significa **ya estaba `revoked` y no se escribió nada** (no-op idempotente:
ni fila de auditoría ni domain event). Un doble click en "desconectar" no puede romper la
pantalla.

### Excepciones — comportamiento vinculante

| Función | Excepción | Cuándo | Qué debe hacer la UI |
|---|---|---|---|
| `start_connect` | `redis.RedisError` | Redis caído (el `jti` del state vive ahí) | error de infra, no del usuario |
| `revoke_connection` | `ConnectionNotFound` | no hay conexión con ese id **visible para ese tenant** | mensaje "no encontrada"; **nunca** reportar éxito |
| `revoke_connection` | `InvalidTransition` | el FSM no tiene arista `revoke` desde el estado actual | bug, no flujo de usuario — dejar propagar |
| `revoke_connection` | `ValueError` | la fila trae un `status` fuera del vocabulario del FSM | idem, dejar propagar |

**`ConnectionNotFound` es deliberadamente indistinguible de "es de otro tenant":** RLS filtra
la fila antes de que el servicio la vea, así que las dos son literalmente la misma lectura.
Ojo, **esto cambia el comportamiento actual de `Qualify/connections_provider.py:disconnect`**,
que hoy hace `return` en silencio cuando la fila es `None`. Devolver "revocada, todo bien" a
quien pasó un id que no le pertenece es lo que había que arreglar.

### Las dos piezas de `Qualify/` que esto desbloquea

1. **`connections_page.py:334`** — el redirect al placeholder `/oauth/start` se sustituye por
   `start_connect(...)`. Con eso muere también el `_OAUTH_START_ROUTE = "/oauth/start"` de
   `connections_provider.py:71` y su STUB.
2. **`connections_provider.py:disconnect` (líneas 96-125)** — se colapsa a una llamada a
   `revoke_connection(...)`. El `TODO(C-03)` de la línea 104 se borra: el servicio ya existe,
   escribe la fila de auditoría **y** publica el domain event (lo que el workaround de la UI
   no hacía — usaba `next_status`, no `apply_transition`, así que la transición no se
   anunciaba a nadie).

**Nota de vocabulario:** el servicio escribe `connection_events.event_type = "revoked"` (forma
corta, la del repositorio: `granted`/`reconnected`/`degraded`/`refresh_failed`), no
`"connection.revoked"` como escribía el workaround de la UI. Filas de auditoría y domain
events son dos sumideros con dos vocabularios — ver `connections/events.py`.

### Operativa

- **Las tres son bloqueantes** (Postgres; `start_connect` además Redis). Un event handler de
  Reflex tiene que correrlas fuera del event loop, exactamente como ya hace `connections_for`.
- **`start_connect` no toca Postgres** — sólo firma el `state` y lo registra en Redis. La
  escritura ocurre en el callback HTTP, que sigue siendo HTTP porque **Meta redirige un
  navegador real** a `/api/connections/callback`.
- Config necesaria en el entorno de la UI (`connections/config.py`): `QUALIFY_META_APP_ID`,
  `QUALIFY_META_APP_SECRET`, `QUALIFY_META_REDIRECT_URI`, `QUALIFY_OAUTH_STATE_SECRET`,
  `QUALIFY_META_SCOPES`, `QUALIFY_REDIS_URL`. Todas tienen fallback dev.

### Gaps 1 y 2, cerrados

- **Arista FSM `(REVOKED, VERIFY_FAIL) → DEGRADED`** — en `connections/fsm.py`, emite un único
  `DomainEventName.DEGRADED`. Cableada además en `service.py:_post_grant_trigger` (si no, sería
  código muerto): un grant fresco que aterriza sobre una conexión `revoked` y falla el verify
  ahora degrada, porque la fila ya apunta a una credencial recién rotada y `revoked` sería un
  campo de estado mintiendo sobre su propia fila. **Q1 (re-verificar una conexión ya `active`)
  sigue sin ruling y sigue siendo no-op.**
- **`revoke_connection`** — `connections/revoke.py`: `RevokeService` + `RevocationRepository`
  (Protocol) + `PostgresRevocationRepository`. Pasa por `apply_transition`, es idempotente, y
  no lee ni escribe `oauth_credentials` (hay un test estático que falla si el módulo llega a
  nombrar `ciphertext`/`key_id`/`OAuthCredential`).

**Suite tras los 3 gaps: 166 passed, 0 failed** (147 de baseline + 19 tests nuevos: 2 de FSM,
1 de callback, 12 de revoke offline, 4 de revoke contra Postgres vivo).
`uv run --no-sync pytest -m db` → **26 passed, 0 failed, corrido DOS VECES seguidas sin
`down -v` en medio** (la lección de la deuda #10: los fixtures nuevos filtran por
`connection_id`, no confían sólo en RLS). `ruff check` + `ruff format` limpios sobre
`packages/api`.

Fichero nuevo `packages/api/tests/test_connections_revoke_db.py`: prueba lo que el fake no
puede fingir — que la escritura pasa por la puerta con RLS, que la fila de otro tenant es
**invisible** (no meramente no consultada, `ConnectionNotFound` desde `TENANT_B`), y que la
fila de auditoría aterriza con la `credential_version` que estaba viva.

### Trampa de venv reencontrada (NO la arreglé — requiere `uv sync`, gated)

`qualify_models` **no es importable** ahora mismo: los `.pth` de editable-install están en
`.venv/lib/python3.12/site-packages/` (`qualify_api.pth`, `qualify_models.pth`, ...) pero
**ninguno se aplica a `sys.path`** — la corrupción descrita arriba. `packages/api|shared|scraper`
sobreviven sólo porque `[tool.pytest.ini_options] pythonpath` los lista explícitamente;
`packages/models/src` **no está en esa lista**, así que `uv run --no-sync pytest -m "not integration"`
pelado revienta en colección con `ModuleNotFoundError: No module named 'qualify_models'`
(`Qualify/test_connections.py`, `Qualify/test_connections_db.py`).

Workaround usado para verificar, sin tocar el venv:

```bash
PYTHONPATH=/Users/herwin/Desktop/Qualify/packages/models/src \
  uv run --no-sync pytest -m "not integration"   # → 166 passed
```

Fix permanente barato y sin sync, para que lo decida el lead: añadir `"packages/models/src"` a
`pythonpath` en el `pyproject.toml` raíz — es literalmente la misma red de seguridad
("belt-and-suspenders") que ya cubre a los otros tres, y el comentario que la documenta ya está
escrito ahí.
