# Refinamiento técnico — Sprint 1 (Núcleo compartido: fundación de cuentas conectadas)

**Fecha:** 2026-07-24 · **Autor:** agente `principal-architect` · **Tipo:** refinamiento técnico PRE-DESARROLLO (no se escribe código de producto). · **Alcance:** convertir los criterios de aceptación de C-01…C-06 (`docs/backlog-crm-workflows.md` §5.2) en especificaciones concretas y testeables, y proponer la automatización del entorno de desarrollo del sprint.

**Contrato del sprint (Tramo 1 = C-01…C-06, Fase 1 Parte 4-A):**
- C-01 Fundación multi-tenant `tenant_id` en Postgres (RLS día uno)
- C-02 Envelope `payload_schema_version=2`, espacios de clave disjuntos
- C-03 Módulo `connections`: custodia de credenciales + FSM
- C-04 Flujo OAuth extremo a extremo (login fork Facebook Login for Business, ADR 25)
- C-05 Matriz permiso→capacidad
- C-06 UI de conexiones (Reflex)

**Reglas que este documento respeta y no relitiga:**
- ADR 21 / 22 / 24 / 25 están **APROBADAS/PROPUESTAS y firmadas** según corresponde. Aquí se **implementan**, no se rediscuten.
- **Nombres de permisos siguen `[V]`** (pendientes de verificar contra `reference/meta-instagram-platform/` y contra el endpoint de autorización — ADR 25 documenta **cuatro grafías en circulación** del scope de publicación). Todo lo que sigue especifica **estructura**, nunca literales de scope.
- **Bug de contenido conocido en la doc de Meta:** la página de permisos lista `instagram_business_manage_comments` con la **descripción de `content_publish` pegada debajo** (§2.5 del doc de integración). C-05 modela la intención (leer/analizar ≠ responder) pero **marca esa fila como PROVISIONAL** hasta verificación de segunda fuente.
- Este documento es propiedad del architect (`docs/`). **No** edita `docs/backlog-crm-workflows.md` (del PO) ni Linear.

**Estado del repo verificado (2026-07-24, filesystem, no docs):** `packages/models` y `packages/scraper` son proyectos `uv` **standalone** (cada uno con su `pyproject.toml` backend `uv_build`, su `.venv`/lock). El Reflex app vive en la **raíz** (`rxconfig.py`, `Qualify/`, `pyproject.toml` con `reflex`/`sqlmodel`). **No existen** `docker-compose.yml`, `migrations/`, `packages/shared`, ni ninguna tabla Postgres. `tenant_id` = **cero ocurrencias** en el repo. `packages/scraper` ya declara `markers = ["integration: hits a live scraping vendor over the network"]` — precedente reutilizable (§Task 2).

---

## Correcciones post-refinamiento (2026-07-25) — rulings de construcción tras los flags de pipeline

Al arrancar el build, pipeline halló que varios puntos de este refinamiento eran infactibles o meramente disciplinarios. Los rulings que los cierran están en `docs/arquitectura.md §6`, "Enmienda de construcción del Sprint 1 (2026-07-25)" (R1…R6). **Donde este documento y esa enmienda discrepen, gana la enmienda.** Resumen de lo corregido aquí:

- **C-03.1 — `platform_apps` NO es tenant-scoped (R1).** La frase "las cuatro tablas con `tenant_id`+RLS" es incorrecta para `platform_apps`: es **global** (registro de las apps de Meta de Qualify), `GRANT SELECT` a `qualify_app`, sin RLS. `social_connections` gana FK `platform_app_id` (provenance de `api_version`, no scoping).
- **C-02.2 — la clave de primera parte NO termina en `content_signature` (R5).** Es `t/{tenant_id}/fp/{platform}/{connection_id}/{object_id}` **overwrite-latest**, no content-addressed (evita acumular un blob por cada respuesta Graph byte-distinta). `content_signature` permanece en el envelope/provenance para staleness, fuera de la clave.
- **C-04.0 — el paso 0 detecta la Página vinculada en el CALLBACK, no antes de emitir la URL (R4).** No hay path API pre-auth. El gate es enumeración post-consentimiento (`/me/accounts`); sin Página → `link_required`, token descartado en memoria, cero credencial persistida. El invariante testeable sobrevive; cambia de "no *emite* URL" a "no *finaliza*".
- **C-01/C-03 — refuerzos estructurales (R2/R3/R6):** denormalizar `tenant_id` en `oauth_credentials`/`connection_events` con FK compuesta anti-deriva; GRANTs a nivel de columna que retienen `ciphertext` de `qualify_app` (rol `qualify_credential` separado); test de atributos de rol (`rolsuper=false AND rolbypassrls=false`) porque `FORCE RLS` no sujeta a superuser/bypassrls.
- **ADR 26/27 — APROBADAS por el fundador (2026-07-25).** ADR 26 con tres condiciones de workspace fold-in (root name `qualify-workspace`; `[tool.uv.sources] workspace=true` por cada cruce; `--import-mode=importlib` + sin `__init__.py` en tests). `Qualify/` se queda en la raíz como member (no se mueve a `packages/crm/`). Auth real diferida a QUA-66 (Sprint 1 usa stub de tenant en dev).

---

## TAREA 1 — Detalle técnico por historia

### C-01 — Fundación multi-tenant (`tenant_id`) en Postgres

Convierte los criterios de §5.2/C-01 y el ruling vinculante de §1.5 en DDL + política RLS + helper de sesión + test de aislamiento concretos.

#### C-01.1 DDL (esquema propuesto, Alembic revision 0001 — ver Task 2)

Cuatro tablas de negocio del núcleo. **Toda** lleva `tenant_id NOT NULL` **excepto `tenants`**, cuya PK `id` **es** el `tenant_id` (una tabla no se referencia a sí misma por una segunda columna). `users` es tenant-scoped en este sprint (identidad = tenant-scoped); la posibilidad "un humano en N tenants" se difiere a una tabla `identities` superior — se **declara** para no cerrar la puerta, no se construye.

```sql
-- Extensión para gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),   -- == tenant_id
    name          text        NOT NULL,
    country       text        NOT NULL,          -- 'CO' (PuntoServis) | 'UY' (inmobiliaria)
    timezone      text        NOT NULL,          -- IANA, p.ej. 'America/Bogota'
    currency      text        NOT NULL,          -- ISO-4217
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid        NOT NULL REFERENCES tenants(id),
    email         text        NOT NULL,
    display_name  text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)                     -- email único dentro del tenant
);
CREATE INDEX ix_users_tenant     ON users (tenant_id);

CREATE TABLE tenant_members (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid        NOT NULL REFERENCES tenants(id),
    user_id       uuid        NOT NULL REFERENCES users(id),
    role          text        NOT NULL CHECK (role IN ('owner','admin','agent','viewer')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id)                   -- un asiento por usuario y tenant
);
CREATE INDEX ix_members_tenant   ON tenant_members (tenant_id);

CREATE TABLE brands (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid        NOT NULL REFERENCES tenants(id),
    name          text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_brands_tenant    ON brands (tenant_id);
```

Notas de modelado que fijan invariantes del sprint:
- **Índice encabezado por `tenant_id`** en toda tabla de negocio (criterio explícito). Las FKs a `tenants(id)` hacen imposible una fila huérfana.
- **`brand_id` y `tenant_id` son ortogonales** (ADR 24b): `brands` cuelga de un tenant, pero **el mapeo tenant→marca no impide que dos tenants observen la misma marca** en el plano de medio ganado — eso vive en las tablas analíticas de `brand_id` (ClickHouse), que **no** llevan `tenant_id`. Este DDL sólo cubre el plano de primera parte/CRM.
- **`tenant_id` NO se añade a ninguna tabla de medio ganado** (criterio explícito) — destruiría la economía del scrape compartido de ADR 18.
- Rol de aplicación **sin privilegio de crear estas tablas**: las crea el rol propietario (C-01.3).

#### C-01.2 Esquema de políticas RLS

Por cada tabla de negocio, en **la misma migración que la crea** (ruling vinculante §1.5). Ejemplo para `social_connections` (C-03) — el patrón es idéntico en `users`, `tenant_members`, `brands`, y todas las de C-03:

```sql
ALTER TABLE social_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_connections FORCE  ROW LEVEL SECURITY;   -- sujeta también al propietario
CREATE POLICY tenant_isolation ON social_connections
    USING       (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK  (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

Para `tenants` la política compara contra la PK:
```sql
CREATE POLICY tenant_isolation ON tenants
    USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

Decisiones que sostienen la garantía (no negociables):
- **`NULLIF(current_setting('app.tenant_id', true), '')`** — el `missing_ok = true` **no basta por sí solo**. **Corregido 2026-07-25 (ruling R7, `docs/arquitectura.md` §6), tras verificación empírica contra Postgres 16:** un GUC personalizado queda **definido para la vida de la sesión** en cuanto se fija una vez, y al terminar la transacción `set_config(..., is_local => true)` lo revierte a `''`, **no a "no definido"**. `current_setting(...)` devuelve NULL **sólo en una conexión física que nunca tocó el GUC**; en cualquier conexión reusada del pool devuelve `''` y `''::uuid` lanza `invalid input syntax for type uuid` — un 500 duro, no cero filas. La redacción anterior de este bullet ("si el GUC no está fijado devuelve NULL … no error ni fuga") era **falsa** para el régimen permanente. `NULLIF` restaura el NULL que el diseño siempre asumió → `tenant_id = NULL` es NULL → la fila se filtra → **fail-closed** (cero filas), sin error. (Nótese que ni siquiera la versión rota era una *fuga*: abortaba la transacción. Era un defecto de corrección/disponibilidad.)
- **Tests que acompañan, dos y no uno:** "GUC sin fijar → 0 filas en todas las tablas" (conexión nueva) **y** "GUC des-fijado en conexión **reusada** del pool → 0 filas" — sólo el segundo ejercita el régimen permanente. Más un **test estructural sobre `pg_policies`** que afirme que toda tabla con `tenant_id` tiene su política `tenant_isolation` y que su `qual`/`with_check` llevan la forma `NULLIF`: los helpers de autoría de 0001 y 0002 son copias independientes, y ningún test funcional caza que una tabla futura nazca con la forma vieja.
- **`WITH CHECK`** además de `USING`: impide **escribir** una fila de otro tenant (un INSERT con `tenant_id` = B bajo GUC = A es rechazado), no sólo leerla.
- **`FORCE ROW LEVEL SECURITY`**: en Postgres el propietario de la tabla **se salta RLS por defecto**. FORCE lo sujeta. Es la diferencia entre "hay políticas" y "las políticas protegen".

#### C-01.3 Roles de base — tres, con fronteras precisas

El error clásico (§1.5) es que la app conecte como propietario de las tablas: las políticas existen y no protegen nada. Se evita con separación de roles:

| Rol | Uso | RLS | Propiedad |
|---|---|---|---|
| `qualify_owner` | Ejecuta migraciones (DDL). Nada de runtime | Sujeto (por FORCE) | **Dueño** de las tablas |
| `qualify_admin` | **Sólo** aprovisionamiento de tenants y seed (op inherentemente cross-tenant: crear la fila de `tenants` ocurre cuando aún no hay "tenant actual") | **`BYPASSRLS`** | No dueño |
| `qualify_app` | Runtime de la aplicación (API, workers, UI) | **Sujeto** | **No dueño**, sin BYPASSRLS |

`qualify_app` recibe `GRANT SELECT, INSERT, UPDATE, DELETE` sobre las tablas, nunca `OWNER`. La app **jamás** usa `qualify_admin`; ese rol lo usa exclusivamente el código de alta de tenant y el seed (C-01.5). Esto hace que "crear un tenant" sea una operación privilegiada y explícita, no un camino que la ruta de request pueda tomar por accidente.

#### C-01.4 Helper de sesión único — el único camino a la base

Un **solo** módulo posee el `Engine` de `qualify_app` y lo mantiene privado (no exportado). Todo repositorio obtiene su sesión de aquí, y aquí se fija el GUC por transacción:

```python
# packages/shared/src/qualify_shared/db/session.py  (ver Task 2 layout)
from contextlib import contextmanager
from collections.abc import Iterator
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.orm import Session

_engine = _build_app_engine()   # rol qualify_app; privado al módulo

@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[Session]:
    """Única puerta a Postgres para código de tenant. Fija app.tenant_id por transacción."""
    with _engine.begin() as conn:
        # set_config(..., is_local=true) == SET LOCAL, pero parametrizable → sin inyección
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"),
                     {"tid": str(tenant_id)})
        yield Session(bind=conn)
```

- `set_config(clave, valor, is_local=true)` es el equivalente **parametrizable** de `SET LOCAL` (`SET LOCAL` no admite parámetros de bind → habría que interpolar el `tenant_id`, superficie de inyección). Alcance = transacción.
- No hay `SessionLocal` público ni `get_engine()` exportado. **El linter/test de C-01 falla si un repositorio construye su propia sesión** o consulta sin pasar por `tenant_session` (criterio "test que falla si una consulta omite el scope de tenant").
- El aprovisionamiento de tenant y el seed usan un helper distinto (`admin_session()` sobre `qualify_admin`), claramente nombrado y fuera del alcance de la ruta de request.

#### C-01.5 Test de aislamiento — afirma "no puede leer", no "existe política"

El test decisivo se ejecuta **como `qualify_app`** (si corriera como owner/superuser, RLS se saltaría y el test sería vacío):

```python
def test_tenant_a_cannot_read_tenant_b(seeded_ab):   # A y B con filas sembradas
    with tenant_session(TENANT_A) as s:
        rows = s.execute(select(SocialConnection)).scalars().all()   # SIN WHERE explícito
    tenants_seen = {r.tenant_id for r in rows}
    assert tenants_seen == {TENANT_A}          # la garantía positiva
    assert TENANT_B not in tenants_seen        # la garantía que importa: 0 filas de B

def test_unset_guc_reads_zero_rows(seeded_ab):
    with _engine.begin() as conn:              # sin fijar app.tenant_id
        n = conn.execute(text("SELECT count(*) FROM social_connections")).scalar()
    assert n == 0                              # fail-closed

def test_cannot_write_other_tenant(seeded_ab):
    with tenant_session(TENANT_A) as s, pytest.raises(Exception):
        s.add(SocialConnection(tenant_id=TENANT_B, ...)); s.flush()   # WITH CHECK lo bloquea
```

Requisitos del harness (Task 2): estos tests llevan marca `db` (necesitan Postgres, no red externa); corren en CI vía service container y localmente vía `docker-compose`. Migración **reproducible y reversible** (`alembic downgrade base` limpio). `uv run pytest` verde **sin red**.

### C-02 — Envelope `payload_schema_version = 2` con espacios de clave disjuntos

Modifica `packages/scraper/src/qualify_scraper/shared.py` (hoy: keying `(platform, url)` brand-agnóstico, líneas 10-11 y 120-122). La decisión es del architect (ADR 22b); la implementación es de `pipeline`. **Sin ruta de compatibilidad v1** — hay cero envelopes persistidos fuera de tests (R2 no existe).

#### C-02.1 Campos nuevos del envelope

```python
class SourceClass(StrEnum):
    SCRAPE          = "scrape"            # ADR 18: N marcas comparten un scrape
    FIRST_PARTY_API = "first_party_api"   # respuesta de Graph API, nunca compartible

class RawPayloadEnvelope(BaseModel):
    payload_schema_version: int = 2       # bump; gobierna forma + algoritmo de firma
    source_class:  SourceClass
    transport:     str                    # 'zyte' | 'graph_api' | ...  (canal concreto)
    platform:      str
    source_url:    str                    # ver C-02.4: token SIEMPRE removido
    tenant_id:     UUID | None = None     # obligatorio si first_party_api (validador)
    connection_id: UUID | None = None     # obligatorio si first_party_api (validador)
    transport_meta: dict[str, Any]        # RENOMBRE de zyte_request_meta
    content_signature: str                # SIN CAMBIOS, sin salt de tenant (C-02.3)
    # ... resto de campos de v1 preservados
```

- `zyte_request_meta` → **`transport_meta`**: renombre, no rediseño. El nombre viejo es vendor-específico; una respuesta de Graph API no tiene metadata de Zyte. Sigue siendo metadata brand-agnóstica del transporte (request id, coste, timing; para Meta: `api_version` y cabeceras de rate limit `X-Business-Use-Case-Usage` [V]).
- `transport` (canal) es distinto de `source_class` (naturaleza legal del dato): un mismo `first_party_api` podría llegar por `graph_api` hoy y por otro transporte mañana; el eje legal no debe acoplarse al canal.

#### C-02.2 Derivación de clave POR ENCIMA del store (dos espacios disjuntos)

La regla de aislamiento se deriva **del envelope**, en una función libre, **no** dentro de ninguna implementación de `RawPayloadStore` (ADR 22, razonamiento 3: si cada store deriva su clave, cada impl reimplementa el aislamiento y cualquiera puede equivocarse):

```python
def raw_payload_key(env: RawPayloadEnvelope) -> str:
    if env.source_class is SourceClass.SCRAPE:
        # ADR 18 intacto: brand-agnóstico → N marcas comparten un scrape
        return f"scrape/{env.platform}/{_url_hash(env.source_url)}"
    # first_party_api: PREFIJADO por tenant_id. Espacio de clave disjunto del de scrape.
    return f"t/{env.tenant_id}/fp/{env.platform}/{env.connection_id}/{env.content_signature}"
```

Los dos prefijos (`scrape/…` vs `t/{tenant_id}/fp/…`) **no se solapan nunca**: aislamiento por construcción de la ruta, no por que las URLs de distintos tenants "no colisionen" (propiedad incidental = fuga). El argumento decisivo de ADR 22 no es sólo la fuga sino la **supresión dirigida**: con prefijo, borrar el raw de un tenant es un `DELETE`/`list-by-prefix`; sin él es imposible sin un índice inverso que nadie ha diseñado.

#### C-02.3 Por qué `content_signature` NO lleva salt de tenant

`content_signature` se computa sobre los bytes canónicos del payload **y nada más**. Añadir un salt de tenant rompería sus tres usos legítimos:
- **Dedup**: contenido idéntico debe tener identidad idéntica.
- **Re-parse auditable**: re-parsear el mismo raw debe reproducir la misma firma.
- **Detección de staleness**: comparar dos capturas del mismo objeto.

El aislamiento es una propiedad de la **ruta de almacenamiento** (el prefijo de clave), **no de la identidad del contenido**. Salar la firma confundiría ambas cosas y no compraría aislamiento que el prefijo ya da (ADR 22, razonamiento 4).

#### C-02.4 Inconstruibilidad + no fuga de token

```python
@model_validator(mode="after")
def _first_party_needs_tenant(self) -> "RawPayloadEnvelope":
    if self.source_class is SourceClass.FIRST_PARTY_API and (
        self.tenant_id is None or self.connection_id is None
    ):
        raise ValueError("first_party_api envelope requires tenant_id and connection_id")
    return self
```

- **Es inconstruible** un envelope de primera parte sin tenant → **no existe camino de código** que emita una clave sin prefijo (el validador falla antes).
- **`source_url` para primera parte** = la URL de la petición a Graph API con `access_token` y **cualquier parámetro de credencial eliminados** antes de firmar/archivar. Test dedicado: el `access_token` **nunca** aparece en el envelope, ni en `source_url`, ni en `transport_meta`, ni en logs (§2.6 del doc de integración: un token en un payload archivado es una fuga **persistente**).

**Criterios de aceptación cubiertos:** campos nuevos ✓, dos espacios disjuntos ✓, derivación sobre el store ✓, inconstruibilidad ✓, `content_signature` sin salt ✓, sin shim v1 ✓, token nunca en el envelope ✓. **Dependencia:** C-01 (necesita el tipo `tenant_id`). `uv run pytest` sin red en `packages/scraper`.

### C-03 — Módulo `connections`: custodia de credenciales + FSM

Módulo interno del monolito modular (ADR 1) — **no** una distribución aparte. Vive en `packages/api` como paquete `connections` (Task 2). Cuatro tablas (DDL base en §2.2 del doc de integración), todas con `tenant_id NOT NULL` + RLS del patrón C-01.2.

#### C-03.1 Tablas — puntos que el refinamiento fija sobre el DDL de §2.2

- **`social_connections`**: `unique (tenant_id, platform, external_account_id)` (idempotencia de conexión). `linked_page_id` pasa de `[V]` opcional a **obligatorio** por ADR 25 (Facebook Login exige Página vinculada). `status` = FSM (C-03.3). `current_credential_version int NOT NULL` (puntero append-only). `access_posture text NOT NULL CHECK (access_posture IN ('development','live'))` — **dato, no constante hardcodeada** (ADR 22a).
- **`oauth_credentials`** — **append-only versionada**: `unique (connection_id, version)`, `version` monotónico, `ciphertext bytea`, **`key_id text NOT NULL`** por fila (rotación incremental sin re-cifrar todo — buena práctica de rotación, ya **no** forzada por incertidumbre de propiedad tras la decisión #1 del fundador). Nunca `UPDATE`; sólo `INSERT version+1`.
- **`connection_events`** — auditoría append-only: `granted|refreshed|refresh_failed|scope_changed|degraded|revoked|reconnected`, con `connection_id`, `credential_version`, `actor` (`user`|`system`), `platform_error_code`, `raw_response_r2_key`, `occurred_at`. Es el provenance de efectos sobre credenciales — responde "¿por qué se desconectó este cliente?" sin adivinar.
- **`platform_apps`** — `app_id`, referencia al secreto (no el secreto), `api_version` de Graph, `config_version`. Hace que la versión de Graph API sea **dato** (Meta deprecia con calendario; el `api_version` con el que se obtuvo un payload es provenance).

#### C-03.2 Interfaz `CredentialResolver` — devuelve cliente, nunca token

Regla dura (§1.6, §2.3): **ningún rol, ni `owner`, lee `oauth_credentials` por la vía de la aplicación.** Los workers piden un **cliente HTTP ya autenticado**:

```python
class AuthenticatedClient(Protocol):
    """Envuelve httpx.AsyncClient con la credencial inyectada. NO expone el token."""
    async def get(self, url: str, **kw) -> httpx.Response: ...
    async def post(self, url: str, **kw) -> httpx.Response: ...

class CredentialResolver(Protocol):
    async def client_for(self, connection_id: UUID) -> AuthenticatedClient:
        """Descifra la credencial vigente EN MEMORIA, la adjunta como header/param
        dentro del cliente, y devuelve el cliente. El token jamás cruza esta frontera."""
```

- El descifrado ocurre dentro del resolver; el plaintext vive sólo el tiempo de construir el cliente y **nunca se retorna ni se loguea**.
- Test: no existe método público que devuelva el token; un intento de `owner` de leer `oauth_credentials` por el repositorio de aplicación falla (RLS + ausencia de repo que exponga `ciphertext`).
- Custodia de la master key (entorno de ejecución vs KMS/Vault) sigue **abierta (W1-Q3)** — independiente de la propiedad del portfolio. El `key_id` por fila mantiene esa puerta abierta sin coste. Recomendación pragmática vigente: master key inyectada por el entorno, diferir KMS hasta requisito de compliance.

#### C-03.3 FSM `pending→active→degraded→revoked` — un evento de dominio por transición

```
pending ──grant OK──────────▶ active ──401/190──▶ degraded ──verificación falla N veces──▶ revoked
                                 ▲                    │                                       │
                                 └──verificación OK───┘                                       │
                                 └──────────────── reconnect (nuevo grant) ───────────────────┘
```

| Transición | Disparador | Evento de dominio (ADR 6) | Fila `connection_events` |
|---|---|---|---|
| `→ pending` | callback OAuth canjea code | `connection.granted` | `granted` |
| `pending → active` | verificación de identidad OK | `connection.activated` | — (implícito en granted+verified) |
| `pending → degraded` | verificación post-conexión falla | `connection.degraded` | `degraded` |
| `active → degraded` | 401/190 en runtime | `connection.degraded` | `degraded` |
| `degraded → active` | verificación barata OK | `connection.recovered` | — |
| `degraded → revoked` | N verificaciones fallan / revocación confirmada | `connection.revoked` | `revoked` |
| `* → active` (reconnect) | nuevo grant | `connection.reconnected` | `reconnected` |

- **`degraded` no es cosmético**: separa "fallo transitorio de red" de "el cliente revocó desde la app de Instagram". Sin él, un 401 puntual desconecta a un cliente que no hizo nada.
- Cada transición emite **exactamente un** evento de dominio por el bus (ADR 6); el módulo de notificaciones lo consume para pedir reconexión. La revocación silenciosa es un driver de carga de soporte, no una nota al pie.

#### C-03.4 Lock distribuido + refresh append-only

```python
# Redis SETNX con TTL corto, namespaced por conexión (y por tenant, §1.3)
lock_key = f"refresh:{tenant_id}:{connection_id}"
```

- **Un solo refresh en vuelo por `connection_id`**. Dos refrescos concurrentes pueden invalidar el token de larga duración (se refresca sobre sí mismo, ~60 días [V]) y desconectar al cliente en silencio.
- Éxito → `INSERT oauth_credentials(version+1)` + `UPDATE social_connections.current_credential_version` **en la misma transacción**. Un refresh fallido **no destruye** la credencial que funcionaba (test explícito).
- Refrescar al **~75 % de vida**, no al 95 % (margen de reintentos antes del acantilado). Celery Beat escanea `expires_at` dentro de ventana.
- Retención corta de versiones anteriores (p.ej. las 2 últimas) para diagnóstico; purga por job.

**Sprint 1 usa Redis** para este lock (y para el `state` de C-04): ver la decisión de Redis en Task 2 — **declarado, no asumido**. `uv run pytest` sin red (refresh y plataforma mockeados; el lock se testea contra el Redis del compose bajo marca `db`).

### C-04 — Flujo OAuth de conexión, extremo a extremo

**Código idéntico en ambos regímenes** (usuarios con rol / terceros); lo que cambia es el gate administrativo, no el flujo. La tienda (cliente cero) es el banco de pruebas literal. Endpoints en `packages/api` (FastAPI). Depende de C-01 (tenant) y C-03 (custodia). **No depende de V1.**

#### C-04.0 Paso 0 — precondición del login fork (Facebook Login for Business, ADR 25)

> ⚠ **El cuerpo de esta subsección quedó SUPERSEDIDO por el ruling R4** (`docs/arquitectura.md` §6; resumido en las correcciones de cabecera de este doc). No existe path API pre-auth, luego "antes de emitir la URL" es **infactible**: el gate vinculante es la **enumeración post-consentimiento en el callback**. Lo que sobrevive intacto es el invariante — sin Página vinculada → `link_required`, **cero credencial persistida, cero conexión usable**, token descartado en memoria — y lo que cambia es la palabra operativa: **no *finaliza*** la conexión, no "no *emite* URL". La UI **puede** mostrar la guía de vinculación como hint pre-flight barato, pero eso **no es verificación**. Lo que sigue se conserva como registro del razonamiento original; **impleméntese R4**.

**Antes de emitir cualquier URL de autorización**, detectar si la cuenta IG destino tiene una **Página de Facebook vinculada** (`mentioned_media`/`mentioned_comment` son exclusivos de Facebook Login → perderlos borraría la cascada multimodal de la vía conectada, ADR 25):

- Si **no** hay Página vinculada → estado `link_required`; se muestra la guía de enlace; **NO se emite la URL de OAuth** y **no** nace fila de conexión.
- Si hay Página vinculada → se procede al paso 1; `social_connections.linked_page_id` se poblará en el callback (columna **obligatoria**).
- Test: sin Página vinculada → `link_required`, cero URL emitida, cero fila.

> La detección concreta del vínculo Página↔IG depende de nombres de endpoint/scope `[V]` (W2-Q2). La **estructura** —fork antes del OAuth, estado `link_required`, no emitir URL— no depende de esos literales y es lo que C-04 fija ahora.

#### C-04.1 Pasos del flujo

| # | Paso | Estado resultante | Modo de fallo |
|---|---|---|---|
| 1 | Admin elige "Conectar cuenta" sobre una marca | — | — |
| 2 | Se genera URL de autorización con **`state` firmado, de un solo uso**, ligado a `(tenant_id, brand_id, user_id)` | — | `state` reusado/expirado → rechazo |
| 3 | El cliente autoriza en Meta y **elige qué permisos concede** | — | Cierra ventana → sin conexión, sin fila huérfana |
| 4 | Callback: valida `state`, canjea `code` por token [V] | `pending` | `state` inválido → 403 y descarte |
| 5 | Se leen los **scopes realmente concedidos** de la respuesta (no los solicitados) → `granted_scopes` | — | concesión parcial silenciosa (§C-04.2) |
| 6 | Se cifra el token → `oauth_credentials` v1; `social_connections` apunta a él; se puebla `linked_page_id` | `pending`→ | fallo de cifrado → sin conexión |
| 7 | **Verificación inmediata**: llamada barata de identidad confirma el token | `active` + `last_verified_at` | falla → nace **`degraded`, no `active`** |
| 8 | (Diferido a Sprint 2) suscripción de webhooks — **no** en Parte 4-A (gate Advanced Access) | — | — |
| 9 | (Bloqueado por Parte 3) backfill de contenido | — | fuera de este sprint |

**Pasos 1–7 son el alcance de C-04.** El 8 (webhooks) y el 9 (backfill) están fuera.

#### C-04.2 `state` firmado de un solo uso

- **Firma**: token opaco = `HMAC-SHA256(secret, payload)` sobre `payload = {tenant_id, brand_id, user_id, jti, iat}`. La firma impide manipulación; **no** se confía en el navegador.
- **Un solo uso**: `jti` se persiste en Redis con TTL (p.ej. 10 min) vía `SETNX`; el callback lo **consume** (`GETDEL`/borrado atómico). Un `state` reusado no encuentra su `jti` → rechazo. Expiración por TTL.
- El callback **reconstituye el contexto del `state`**, no de parámetros de query no firmados → el `(tenant_id, brand_id, user_id)` de destino es inatacable.

#### C-04.3 `granted_scopes` reales — el paso que casi siempre se omite

```python
# El callback persiste lo CONCEDIDO, jamás la lista solicitada:
granted = parse_granted_scopes(token_response)   # de la respuesta de Meta
connection.granted_scopes = list(granted)        # text[] en Postgres
```

- Meta permite **concesión parcial**. Una app que asume que recibió lo que pidió falla más tarde con un 403 que parece un bug de otra cosa. Test explícito de concesión parcial (se piden 4 familias, se conceden 2 → `granted_scopes` refleja 2, y C-05 apaga las capacidades correspondientes en la UI, no en runtime).
- Los **literales** de scope siguen `[V]` (ADR 25: cuatro grafías del scope de publicación en circulación). El parser guarda las cadenas **tal cual las devuelve el endpoint**; la traducción literal→capacidad la hace C-05 tras un `resolve_scope_keys` que absorbe las variantes. **No se hardcodea ninguna grafía desde documentación.**

#### C-04.4 Idempotencia y desconexión

- **Idempotencia**: `unique (tenant_id, platform, external_account_id)`. Reconectar la misma cuenta **actualiza la fila** (y añade `oauth_credentials version+1`), no crea una segunda. Análogo transaccional de `(brand_id, platform, post_id)`.
- **Desconectar funciona de verdad**: transición `→ revoked`, emite `connection.revoked` + fila `connection_events`. No es sólo un flag de UI.
- **Suite offline**: doble de la plataforma (fake del authorization/token endpoint). **Cero red en CI.**

### C-05 — Matriz permiso → capacidad (degradación explícita)

Hermana de `packages/models/src/qualify_models/oauth_scope.py` y con su mismo estilo (StrEnum, `pydantic.BaseModel`, tupla de registros, `ASSESSMENT_VERSION`, funciones `lookup`/derivadas puras). **Vive en `packages/models`** (es assessment, no runtime de conexión). Depende de C-04 (produce `granted_scopes`); los **nombres de permiso `[V]` NO entran en la lógica**.

#### C-05.1 Separación literal ↔ lógica (la que absorbe el bloqueo `[V]`)

La función pura opera sobre **claves abstractas de scope**, no sobre literales de Meta. Los literales viven en una tabla aparte, versionada, resoluble empíricamente contra el endpoint de autorización (ADR 25: 4 grafías):

```python
ASSESSMENT_VERSION = "perm-capability-v1"

class ScopeKey(StrEnum):          # abstracto — NO es el literal de Meta
    BASIC            = "basic"
    CONTENT_PUBLISH  = "content_publish"
    MANAGE_COMMENTS  = "manage_comments"
    MANAGE_MESSAGES  = "manage_messages"
    MANAGE_INSIGHTS  = "manage_insights"

# [V] Rellenado desde el endpoint de autorización, NO desde documentación.
# Aislar aquí las grafías permite cambiarlas sin tocar la lógica de capacidades.
SCOPE_LITERALS: dict[ScopeKey, tuple[str, ...]] = { ... }   # p.ej. varias grafías por clave

def resolve_scope_keys(granted_literals: frozenset[str]) -> frozenset[ScopeKey]:
    """Traduce las cadenas concedidas por Meta a claves abstractas, tolerando variantes."""
```

#### C-05.2 Firma de la función pura + registro por capacidad

```python
class Capability(StrEnum):
    CONNECT_ACCOUNT  = "connect_account"     # sin BASIC no hay conexión
    PUBLISH_CONTENT  = "publish_content"     # W3 entero
    READ_COMMENTS    = "read_comments"       # lectura de comentarios
    ANALYZE_COMMENTS = "analyze_comments"    # sentiment/temas/intención
    REPLY_COMMENTS   = "reply_comments"      # moderar/responder
    MANAGE_DMS       = "manage_dms"          # W4: bandeja de DM
    READ_INSIGHTS    = "read_insights"       # métricas propias

class CapabilityVerdict(BaseModel):
    capability: Capability
    enabled:    bool
    requires:   ScopeKey | None              # scope que la habilita (None = siempre)
    reason:     str                          # motivo por capacidad DESHABILITADA

def assess_capabilities(granted: frozenset[ScopeKey]) -> tuple[CapabilityVerdict, ...]:
    """granted_scopes (resueltos) → capacidades, con motivo por cada una deshabilitada.
    Pura, versionada por ASSESSMENT_VERSION, sin efectos. La UI (C-06) la consume."""
```

#### C-05.3 Propiedad de producto que se PINEA por test

Cubre las cuatro familias de §2.5 y fija el argumento de onboarding más fuerte:

| Capacidad | `requires` | Si se deniega su scope, ¿sigue? |
|---|---|---|
| `CONNECT_ACCOUNT` | `BASIC` | No — sin BASIC no hay conexión |
| `PUBLISH_CONTENT` | `CONTENT_PUBLISH` | Publicación off; lectura/comentarios/DMs siguen |
| `MANAGE_DMS` | `MANAGE_MESSAGES` | Bandeja off; publicación/comentarios/listening siguen |
| `READ_COMMENTS` | `BASIC` | **Sí** — leer no depende de `MANAGE_COMMENTS` |
| `ANALYZE_COMMENTS` | `BASIC` | **Sí** — el sentiment sigue aunque se deniegue responder |
| `REPLY_COMMENTS` | `MANAGE_COMMENTS` | Sólo la **respuesta** se apaga |
| `READ_INSIGHTS` | `MANAGE_INSIGHTS` | Insights off; el resto sigue |

**El test pinea la totalidad de la matriz** y, en particular, `assert assess({BASIC}).enabled(ANALYZE_COMMENTS) is True` con `MANAGE_COMMENTS` ausente — **denegar responder comentarios NO deshabilita leerlos ni analizarlos**. Es "conceder permisos" como una escalera con valor en cada peldaño.

#### C-05.4 ⚠ Bug de contenido de la doc de Meta — la fila que sostiene la escalera

La página de permisos de Meta lista `instagram_business_manage_comments` con la **descripción de `content_publish` pegada debajo** (§2.5). Es *plausible* que **leer** caiga bajo BASIC y **responder** bajo `MANAGE_COMMENTS` —justo lo que sostiene la escalera— **pero no se asume**:

- C-05 codifica la **intención** (leer/analizar bajo BASIC; responder bajo MANAGE_COMMENTS) pero marca esas dos filas como **`PROVISIONAL`** en el registro (`reason` incluye la advertencia), y expone un flag `assessment_provisional=True` mientras no haya verificación de **segunda fuente**.
- Es la verificación de mayor valor que queda (§2.5): el argumento comercial con un cliente desconfiado descansa sobre ella. La UI (C-06) muestra la capacidad, pero el registro es honesto sobre su estatus hasta cerrar la verificación.

**La UI muestra feature deshabilitada con su motivo, nunca un 403 en runtime.** `uv run pytest` sin red; matriz completa pineada.

### C-06 — UI de conexiones en el CRM (Reflex)

Primera pantalla del CRM que toca datos reales. Vive en `Qualify/` (Reflex, ADR 8). Depende de C-03/C-04 (datos de conexión) y C-05 (motivos de capacidad). **Lee del tenant de la sesión** — nunca puede pintar datos de otro tenant. Sigue las skills `reflex-docs`/`reflex-process-management` para la implementación.

#### C-06.1 Estado (Reflex `State`)

```python
class ConnectionsState(rx.State):
    connections: list[ConnectionVM]     # view-models, NO entidades ORM crudas
    # Se cargan SIEMPRE vía tenant_session(session_tenant_id) — el helper único de C-01.4.
    # El tenant sale de la sesión autenticada del CRM, jamás de un parámetro de URL.
```

- El `State` obtiene `session_tenant_id` de la sesión del CRM y consulta a través de `tenant_session` (C-01.4). La RLS es la red inferior; el scoping explícito es la superior (defensa en profundidad L1+L2).
- **View-models, no ORM**: `ConnectionVM` expone `status`, `external_username`, `last_verified_at`, `granted_scopes`, y las capacidades con su motivo — **nunca** campos de `oauth_credentials`. No hay ruta desde la UI al ciphertext.

#### C-06.2 Componentes

| Componente | Responsabilidad | Detalle load-bearing |
|---|---|---|
| `connection_list` | Lista de conexiones del tenant | Vacía → estado "conecta tu primera cuenta" con CTA a C-04 |
| `connection_card` | Una conexión | Badge de estado `active`\|`degraded`\|`revoked`; `external_username`; `last_verified_at` legible; chips de permisos concedidos |
| `degraded_banner` | Estado `degraded` **accionable** | **Botón "Reconectar"** que relanza C-04 (no un icono decorativo). Copia con la acción concreta a hacer |
| `disabled_capabilities` | Capacidades apagadas con su motivo | Consume `assess_capabilities` de C-05: *"Publicar reels — deshabilitado: no concediste el permiso de publicación"*. Nunca un 403 |
| `disconnect_action` | Desconectar | Confirma; dispara `→ revoked` de C-03; refleja el nuevo estado tras reconciliar |

#### C-06.3 Reglas de correctitud

- **Estado `degraded` visible y accionable** (criterio explícito): la reconexión es un botón, no un tooltip.
- **Nunca** se muestra ni se registra material de credencial (token, ciphertext, `key_id`). Test de que el `ConnectionVM` no puede transportar esos campos.
- **Capacidades con motivo**: se pinta lo que C-05 devuelve, incluida la marca `PROVISIONAL` de C-05.4 si aplica (no se afirma en la UI una capacidad cuya fila está sin verificar como si fuera segura).
- **Aislamiento en la UI**: test de que la pantalla, con sesión de tenant A, **no** puede pintar conexiones de B (la consulta pasa por `tenant_session(A)` → RLS devuelve 0 filas de B). Es el mismo invariante de C-01.5 ejercido desde la capa de presentación.
- Hoy `Qualify/` corre sobre SQLite/seed **sin conexión al pipeline**; C-06 es la primera pieza que lo conecta a Postgres real vía los view-models — no reescribe el scaffold de mentions, añade la ruta `/connections`.

---

## TAREA 2 — Automatización del entorno de desarrollo (DISEÑO, no implementación)

Diseño de la automatización que el fundador pidió ("cosas para automatizar, ej. Docker para levantar entorno rápido"). Todo con **`uv`**, nunca pip/conda.

### T2.0 — Decisión de layout: ¿uv workspace ahora? — **RULING: SÍ. Es mi decisión y la firmo.** (ADR 26)

**Estado hoy (verificado):** `packages/models` y `packages/scraper` son proyectos `uv` **standalone** (cada uno con su `pyproject.toml` de backend `uv_build`, su `.venv` y su lock). El Reflex app vive en la **raíz** con su propio `pyproject.toml` (reflex/sqlmodel) y `uv.lock`. No hay raíz común de dependencias.

**Lo que el Sprint 1 fuerza:** C-01 crea un backend CRM/Postgres nuevo; C-02 modifica `packages/scraper/shared.py`; C-01.4 (helper de sesión) y C-02.2 (derivación de clave) son **cross-cutting** — los necesitan tanto `api` como `scraper`. C-05 vive en `packages/models` y C-06 en `Qualify/`. **Aparecen imports cruzados entre paquetes por primera vez.** Tres standalone con locks separados no pueden compartir tipos sin publicar a un índice o hacer path-installs frágiles.

**Ruling:** convertir el repo en un **uv workspace** con raíz común **ahora**. Mismo patrón de argumento que `tenant_id`: es **la última ventana barata** (tres paquetes, cero imports cruzados aún); después de que `api` importe de `shared` en 40 sitios, unificar locks es un refactor con riesgo.

| Decisión | Discarded | Motivo |
|---|---|---|
| **uv workspace, raíz aggregator** (`[tool.uv.workspace] members=["packages/*"]`), un solo lock, un `.venv` | Seguir con 3 proyectos standalone; o un monorepo con path-deps manuales | (1) Los imports cruzados de C-01/C-02/C-05 llegan este sprint → sin workspace hay que publicar a un índice o path-installs frágiles. (2) `uv` resuelve el workspace con **un lock coherente** y `uv sync` único → arranque reproducible (objetivo del fundador). (3) Greenfield: 3 paquetes, cero cruces → coste de conversión mínimo **hoy**, alto tras el primer cruce. (4) Bump de versión atómico entre `shared`↔`api`↔`scraper` |
| Nuevo backend en **`packages/api`** como **monolito modular** (ADR 1) con módulos internos `tenancy`, `connections` | Un paquete por módulo (`packages/tenancy`, `packages/connections`, …) | ADR 1 ya decidió monolito modular; proliferar distribuciones para un fundador en solitario es sobre-ingeniería. Módulos = paquetes Python internos, no distribuciones |
| Nuevo **`packages/shared`** para lo cross-cutting: helper `tenant_session` (C-01.4), derivación de clave sobre el store (C-02.2), tipos de ID, base de eventos de dominio | Poner el helper en `api` y que `scraper` importe de `api` | `scraper` no debe depender del backend CRM. Lo que ambos comparten baja a `shared` (coincide con el layout planificado de `CLAUDE.md`) |
| **El envelope permanece en `packages/scraper/shared.py`** este sprint (C-02 lo edita ahí); su mudanza a `packages/shared` se anota como follow-up | Mover el envelope a `packages/shared` dentro del Sprint 1 | La historia C-02 dice "edita `shared.py`". Mover + editar a la vez es riesgo innecesario mid-sprint. La **derivación de clave** (función libre) sí nace en `packages/shared`; el modelo del envelope se muda después |
| `Qualify/` (Reflex) **se une al workspace como member** para que C-06 dependa de los view-models de `api` | Dejar el Reflex app fuera del workspace | C-06 necesita leer modelos de conexión del backend; un member evita duplicar tipos. **Sub-pregunta que NO fuerzo:** el Reflex app está hoy en la **raíz** (no bajo `packages/`); unirlo puede requerir moverlo a `packages/crm/` o declararlo member explícito. Lo dejo como decisión de arranque del sprint, no lo prescribo — su árbol de deps (reflex) es pesado y el movimiento tiene coste |

**Coste que se acepta de frente:** unificar tres locks en uno y un `.venv` compartido. Los paquetes pasan de `requires-python>=3.12` heterogéneo a la restricción del workspace (todos ya en `>=3.12`, sin conflicto). `packages/models` arrastra torch/transformers — el `.venv` del workspace será pesado; se mitiga con dependency-groups (`uv sync --no-group heavy` para trabajo de solo-backend). **Payoff:** `uv sync` único, imports cruzados nativos, arranque de una orden.

### T2.1 — `docker-compose.yml` local

Servicios mínimos del Sprint 1. **Redis se declara, no se asume** — y la conclusión es que **SÍ hace falta en el Sprint 1**, no sólo "pronto para C-08":

```yaml
services:
  postgres:
    image: postgres:16          # RLS estable; FORCE ROW LEVEL SECURITY; current LTS práctico
    environment:
      POSTGRES_DB: qualify
      POSTGRES_USER: qualify_owner      # dueño de objetos = ejecuta migraciones
      POSTGRES_PASSWORD: dev_only
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U qualify_owner -d qualify"]
      interval: 2s
      timeout: 3s
      retries: 20
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 20

volumes:
  pgdata:
```

**Por qué Redis en el Sprint 1 (declarado):** dos usos del Tramo 1 lo necesitan — el **lock distribuido de refresh por `connection_id`** (C-03.4) y el **`state` OAuth de un solo uso** (C-04.2). Ambos están especificados como Redis en la arquitectura (§2.3, §2.6) y Redis es Parte 3 temprana de todos modos. Alternativa considerada y descartada: hacer el lock con **advisory locks de Postgres** y el `state` con una tabla → mantendría el Sprint 1 en Postgres-only, pero sería un mecanismo desechable que C-08 (Sprint 2) reemplaza por Redis igualmente. **Ruling: incluir Redis ahora** y ejercitar el mecanismo real. Los roles `qualify_app`/`qualify_admin` los crea la migración 0001 (no el compose), para que la creación de roles sea versionada y reproducible.

**No van en el compose (Sprint 1):** ClickHouse (Parte 3, sin `ingestion.*` este sprint), workers Celery (no hay fetch/backfill en Parte 4-A), MinIO/R2 (sin raw store todavía). Se añaden cuando su historia entre.

### T2.2 — Herramienta de migraciones — **RULING: Alembic (Postgres) + SQL versionado (ClickHouse).** (ADR 27)

| Plano | Herramienta | Motivo |
|---|---|---|
| **Postgres** (C-01/C-03) | **Alembic** | Grafo de revisiones con `upgrade`/`downgrade` (criterio "migración reversible"), integración con SQLAlchemy que el CRM ya usa (Reflex/SQLModel). **RLS, roles y `FORCE ROW LEVEL SECURITY` van como SQL a mano dentro de `op.execute()`** — **autogenerate NO se usa para RLS/roles/políticas** (no las detecta; se escriben en `upgrade`/`downgrade` explícitos). Las migraciones corren como **`qualify_owner`**, nunca como `qualify_app` |
| **ClickHouse** (Parte 3, futuro) | **SQL versionado** en `migrations/clickhouse/NNNN_*.sql` | `CLAUDE.md` ya lo prescribe. Alembic no tiene dialecto CH decente. El `ORDER BY` es **inmutable** → un directorio SQL lineal numerado es más claro y auditable que un grafo de revisiones para DDL que no se altera |

**Por qué no un solo mecanismo:** el plano Postgres es transaccional con FKs y esquema que evoluciona → el grafo + `downgrade` de Alembic se gana su sitio. El plano ClickHouse es append-only inmutable → SQL lineal. Forzar ambos a la misma herramienta pierde en los dos. La migración 0001 de Alembic incluye: extensión `pgcrypto`, las 4 tablas de C-01, las 4 de C-03, **creación de los tres roles**, `GRANT`s a `qualify_app`, y **`ENABLE`+`FORCE RLS`+políticas en la misma revisión que crea cada tabla** (ruling §1.5).

### T2.3 — Comando único de arranque (justfile)

**`just`** sobre Makefile: sin `.PHONY`, sintaxis limpia, buena ergonomía con `uv`. `justfile` en la raíz:

```make
set shell := ["bash", "-cu"]

# Levanta infra + migra + siembra los DOS tenants reales. El objetivo del fundador.
dev: up migrate seed

up:
    docker compose up -d
    # espera a healthy (Postgres + Redis) antes de continuar
    docker compose ps --format '{{{{.Health}}}}' | grep -q healthy

migrate:
    uv run alembic upgrade head        # corre como qualify_owner (DDL + RLS + roles)

seed:
    uv run python -m qualify_api.seed  # usa admin_session() (qualify_admin, BYPASSRLS)

test:
    uv run pytest -m "not integration"  # unit + db; nunca red externa

test-db:
    uv run pytest -m "db"               # necesita el Postgres/Redis del compose

lint:
    uv run ruff check .
fmt:
    uv run ruff format .

down:
    docker compose down -v              # -v borra el volumen: reset limpio
```

**Seed de los dos tenants reales** (`qualify_api.seed`, vía `admin_session()` sobre `qualify_admin` porque crear tenants es cross-tenant):

- **Tenant PuntoServis** (Cúcuta, CO, `America/Bogota`, COP): 1 `owner` (el fundador). 1 marca. Banco de pruebas del núcleo compartido.
- **Tenant inmobiliaria** (UY, `America/Montevideo`, UYU): 1 `owner` + **N `agent`** (parametrizable, p.ej. 3). ≥1 marca. Es la razón de que exista el modelo de asientos.
- El seed **no** crea conexiones sociales reales (eso exige OAuth vivo); deja los tenants operativos para que C-04 conecte contra el doble de plataforma. Tras sembrar, un chequeo de humo abre `tenant_session(PUNTOSERVIS)` y verifica que **no ve** filas de la inmobiliaria (ejerce C-01.5 en el arranque).

`just dev` = "levantar entorno rápido" en una orden: `up` → `migrate` → `seed`, con espera de healthcheck para que no haya carreras.

### T2.4 — pytest sin red, pre-commit, CI

**Dos marcas de pytest** (el scraper ya tiene precedente con `integration`), configuradas en cada `pyproject.toml` de member o en el `[tool.pytest.ini_options]` raíz del workspace:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: hits an external network/paid vendor or downloads model weights (Zyte, HF, Meta) — NEVER in CI",
    "db: needs the local Postgres/Redis from docker-compose — runs in CI via service containers",
]
addopts = "-m 'not integration'"   # por defecto: unit + db, jamás red externa
```

- **`integration`**: red externa / pesos / vendors de pago. Nunca en CI. Es la marca existente del scraper, generalizada.
- **`db`**: necesita Postgres/Redis locales (el test de aislamiento de C-01.5, el lock de C-03.4). **No** es red externa → corre en CI con service containers. Los tests puros (C-02 envelope, C-05 matriz) no llevan marca y corren en cualquier lado sin infra.

**pre-commit** (`.pre-commit-config.yaml`): `ruff check --fix` + `ruff format` (lint y formato, ya es la convención de `CLAUDE.md`). Hook local con `uv run` para no depender del ruff del sistema. Type hints obligatorios (convención `CLAUDE.md`); opcionalmente un hook `mypy`/`pyright` sobre los paquetes nuevos.

**Esbozo de CI** (GitHub Actions, `.github/workflows/ci.yml`):

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16, env: { POSTGRES_PASSWORD: ci, POSTGRES_DB: qualify }, ports: ["5432:5432"], options: >- --health-cmd pg_isready --health-interval 2s --health-retries 20 }
      redis:    { image: redis:7, ports: ["6379:6379"], options: >- --health-cmd "redis-cli ping" --health-interval 2s --health-retries 20 }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5           # uv, no pip/conda
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run alembic upgrade head       # migra contra el Postgres de servicio
      - run: uv run pytest -m "not integration"  # unit + db; red externa excluida
```

- CI ejecuta **unit + db**, nunca `integration`. El `alembic upgrade head` contra el Postgres de servicio valida que la migración (incluidas RLS/roles) es reproducible.
- Un solo `uv sync` gracias al workspace (T2.0). Sin workspace habría que sincronizar 3 proyectos por separado.

---

## ADRs nuevas que este refinamiento firma (añadidas a `docs/arquitectura.md` §6)

Dos decisiones de infraestructura de desarrollo que el Sprint 1 fuerza. Nacieron **PROPUESTO** (ruling técnico del architect, no requerían firma del fundador). **Actualización 2026-07-26:** ambas están hoy en **`[APROBADO]`** en `docs/arquitectura.md` §6 — firmadas por el fundador el **2026-07-25**. La nota original las declaraba "de estatus consistente con ADR 25"; **ADR 25 también quedó firmada, el 2026-07-26**, así que la comparación ya no distingue nada. `docs/arquitectura.md` §6 es la fuente de verdad del estatus.

**ADR 26 — Monorepo como `uv` workspace + `packages/api` (monolito modular) + `packages/shared`.**
- Decisión: convertir el repo en un `uv` workspace (raíz aggregator, un lock, un `.venv`); el backend CRM nuevo vive en `packages/api` como monolito modular (ADR 1) con módulos `tenancy`/`connections`; lo cross-cutting (helper de sesión C-01.4, derivación de clave C-02.2) baja a `packages/shared`; `Qualify/` se une como member.
- Descartado: seguir con 3 proyectos `uv` standalone; un paquete por módulo de dominio.
- Motivo: los imports cruzados de C-01/C-02/C-05 llegan este sprint; es la última ventana barata (greenfield, cero cruces); `uv sync` único y bump atómico. Coste aceptado: unificar 3 locks en uno.

**ADR 27 — Migraciones: Alembic (Postgres) + SQL versionado (ClickHouse).**
- Decisión: Alembic para el plano Postgres (con RLS/roles/`FORCE RLS` escritos a mano en `op.execute()`, autogenerate **off** para políticas; migraciones como `qualify_owner`); SQL lineal numerado en `migrations/clickhouse/` para el plano analítico.
- Descartado: una sola herramienta para ambos planos; autogenerate para RLS.
- Motivo: Postgres transaccional evoluciona → grafo + `downgrade` de Alembic; ClickHouse append-only con `ORDER BY` inmutable → SQL lineal más claro; `CLAUDE.md` ya prescribe `migrations/clickhouse/`.

---

## Resumen para sincronizar a Linear (QUA-13…QUA-18)

- **C-01 (QUA-13):** DDL de `tenants`/`users`/`tenant_members(role)`/`brands` con `tenant_id NOT NULL` + índice; RLS con `current_setting('app.tenant_id', true)` **fail-closed** y `WITH CHECK`; **tres roles** (`qualify_owner` dueño, `qualify_admin` BYPASSRLS sólo para provisioning/seed, `qualify_app` no-dueño sujeto a RLS); **helper `tenant_session` único** con `set_config` parametrizado; test que afirma **0 filas de B** (no "existe política"), corriendo como `qualify_app`.
- **C-02 (QUA-14):** envelope v2 gana `source_class`/`transport`/`tenant_id`/`connection_id`, renombra `zyte_request_meta`→`transport_meta`; `raw_payload_key()` **libre, sobre el store**, con dos prefijos disjuntos (`scrape/…` vs `t/{tenant_id}/fp/…`); `content_signature` **sin salt** (dedup/re-parse/staleness); validador que hace **inconstruible** un first-party sin tenant; token nunca en el envelope.
- **C-03 (QUA-15):** 4 tablas (`oauth_credentials` **append-only versionada**, `key_id` por fila); `CredentialResolver` devuelve **cliente HTTP autenticado, nunca token**; **lock Redis por `connection_id`** antes de refrescar (INSERT v+1 + UPDATE puntero en una tx); FSM `pending→active→degraded→revoked` con **un evento de dominio por transición**; `access_posture` como dato.
- **C-04 (QUA-16):** **paso 0 login fork** (detectar Página FB vinculada → `link_required`, no emitir URL); `state` HMAC de un solo uso ligado a `(tenant_id,brand_id,user_id)` con `jti` en Redis; callback persiste **`granted_scopes` reales** (test de concesión parcial); verificación post-conexión → nace `degraded` si falla; idempotencia `unique(tenant_id,platform,external_account_id)`; suite offline con doble de plataforma.
- **C-05 (QUA-17):** función pura `assess_capabilities(frozenset[ScopeKey]) → tuple[CapabilityVerdict]` versionada (`ASSESSMENT_VERSION`), estilo `oauth_scope.py`; **literales de scope aislados** en `SCOPE_LITERALS`+`resolve_scope_keys` (absorbe las 4 grafías `[V]`); pinea que **denegar responder comentarios NO apaga leer/analizar**; fila `manage_comments` marcada **PROVISIONAL** por el bug de contenido de la doc de Meta.
- **C-06 (QUA-18):** pantalla Reflex `/connections` que lee del **tenant de sesión** vía `tenant_session`; `connection_card` con badge de estado + `last_verified_at` + permisos; `degraded_banner` **accionable** (botón Reconectar); capacidades deshabilitadas con motivo (consume C-05); **nunca** material de credencial; test de que sesión A no pinta datos de B.
- **Automatización:** **uv workspace** (ADR 26) + `packages/api`/`packages/shared`; **`docker-compose`** Postgres 16 + **Redis 7 (declarado necesario ya** para lock C-03.4 y `state` C-04.2); **Alembic** para Postgres con RLS/roles a mano + SQL versionado para ClickHouse (ADR 27); **`justfile`** con `just dev` = up→migrate→**seed de los dos tenants reales** (PuntoServis 1 asiento / inmobiliaria N asientos); pytest con marcas **`integration`** (red externa, nunca CI) y **`db`** (Postgres/Redis local, sí CI); pre-commit `ruff`; CI GitHub Actions con service containers, todo con `uv`.

