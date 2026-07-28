# Sprint 1 — estado de resume (2026-07-25)

Prompt de continuación para cerrar el Sprint 1 (núcleo compartido de cuentas conectadas,
Fase 1 Parte 4-A). El build se detuvo por límite mensual de gasto con **5 de 6 historias
construidas**. Nada commiteado.

**Cómo usarlo:** abre una sesión nueva con `claude --agent dev-lead` y pega el bloque de
"PROMPT" de abajo como primer mensaje. Es una CONTINUACIÓN self-contained (no el `/team-dev`
enlatado, que reconstruiría desde cero).

## Snapshot del estado

| Historia | Estado | Verificación |
|---|---|---|
| C-01 multi-tenant + RLS | ✅ construida | pipeline offline (50); RLS en vivo = pendiente docker/CI |
| C-02 envelope v2 (R5) | ✅ construida | pipeline offline (48) |
| C-03 connections (custody+FSM, R1/R2/R3) | ✅ construida | pipeline offline (67); grants/RLS en vivo = pendiente docker/CI |
| C-04 flujo OAuth | ❌ **falta** | — |
| C-05 matriz permiso→capacidad (pesimista) | ✅ construida | lead-verified 14/14 |
| C-06 pantalla conexiones + stub tenant | ✅ construida | lead-verified 9/9 + navegador |

Más: workspace uv + infra (docker-compose, alembic, justfile, CI) + stub de tenant en dev.
Contexto durable: `docs/refinamiento-sprint1.md`, `docs/arquitectura.md §6` (ADR 26/27 + R1–R6),
Linear QUA-13…18, y `.claude/compass-sage/ledger.md`.

## PROMPT (pegar en `claude --agent dev-lead`)

```
CONTINUACIÓN del Sprint 1 — Núcleo compartido de cuentas conectadas (Fase 1 Parte 4-A).
NO es un sprint nuevo: 5 de 6 historias YA están construidas y en el árbol de trabajo
(nada commiteado). Tu trabajo es cerrar la última historia + verificar + integrar.

LEE PRIMERO (todo el contexto es durable, no lo re-deduzcas):
  - docs/refinamiento-sprint1.md  — spec técnico por historia (§C-01…§C-04) + automatización.
  - docs/arquitectura.md §6  — ADR 26/27 (APROBADAS) + enmienda de rulings R1–R6 del build.
  - Comentarios de refinamiento y rulings en Linear QUA-13/14/15/16/17/18.
  - .claude/compass-sage/ledger.md  — bitácora del build (qué se construyó y verificó).
  - VERIFICA CONTRA EL FILESYSTEM antes de citar cualquier estado (fallo recurrente del repo).

YA CONSTRUIDO — NO lo rehagas (verifícalo con `git status` + tests):
  - Workspace uv (raíz qualify-workspace, 3 guardas: root-name≠miembros, [tool.uv.sources],
    --import-mode=importlib sin __init__.py en tests) + venv fuera de anaconda (.python-version).
  - Infra: docker-compose (PG16+Redis7), alembic.ini + migrations/postgres/, justfile (just dev),
    .pre-commit, .github CI.
  - C-01 (packages/api tenancy + packages/shared/db: tenant_session/admin_session/dev + seed 2 tenants,
    migración 0001, RLS 3-roles). C-02 (packages/scraper/shared.py envelope v2, R5). C-03
    (packages/api/connections: migración 0002, FSM/crypto/locks/resolver/events con fakes).
  - C-05 (packages/models/permission_capability.py — matriz PESIMISTA, 14 tests verdes).
  - C-06 (Qualify/ pantalla /connections + selector de tenant dev — 9 tests verdes, verificado en
    navegador) — construido contra STUBS locales (capabilities.py, tenant.py, provider mock).

LO QUE FALTA — tu alcance (3 bloques):

  1) C-04 — flujo OAuth extremo a extremo (packages/api). La ÚNICA historia sin construir.
     Spec: refinamiento §C-04 + QUA-16. Aplica los rulings ya firmados:
       - state HMAC sobre {tenant,brand,user,jti,iat}; one-time jti (SET NX EX 600 + GETDEL).
       - callback R4: login-fork por ENUMERACIÓN POST-CONSENTIMIENTO (no pre-URL); sin Página
         vinculada → estado link_required, token descartado en memoria, cero credencial persistida.
       - granted_scopes leídos de /me/permissions y guardados como LITERALES CRUDOS (no interpretar
         — eso es resolve_scope_keys de C-05).
       - verify post-conexión VÍA CredentialResolver (nunca token crudo); nace degraded si falla.
       - upsert idempotente unique(tenant_id, platform, external_account_id).
       - endpoints FastAPI = primera superficie HTTP de packages/api; test con Starlette TestClient.
       - INCLUYE lo que C-03 dejó diferido: el CredentialReader con engine qualify_credential + GUC.

  2) VERIFICACIÓN DOCKER (la más importante que queda; C-01/C-03 solo están verificados OFFLINE):
       - `just dev` (up → migrate → seed) — necesita docker + QUALIFY_MIGRATION_DSN (owner).
       - `uv run pytest -m db` — ejercita EN VIVO el aislamiento RLS, los column-grants del token
         (qualify_app NO lee ciphertext), la FK compuesta anti-drift y el GUC-bleed pooled.
       - Re-verifica también las suites puras (C-02 48, C-05 14, C-06 9, etc.).

  3) INTEGRACIÓN de los stubs de Qualify/ con los paquetes reales (borra los TODOs de swap):
       - Qualify/capabilities.py → import de packages/models permission_capability (misma forma).
       - Qualify/tenant.py → packages/shared dev helpers; reconciliar TenantRef(id,label) →
         TenantOption(id,name,country).
       - Qualify/connections_provider.py mock → loader real vía tenant_session(tenant_id).
       - auth_url placeholder /oauth/start → URL real que emite C-04.
       - Requiere cablear que Qualify/ (member del workspace) importe qualify-shared/qualify-models.

EQUIPO (spawnea SOLO lo necesario — es un cierre, no un sprint completo):
  - pipeline-engineer → C-04 + CredentialReader + exponer en packages/ lo que Qualify consume.
  - reflex-ui-engineer → los swaps de integración en Qualify/ (bloque 3).
  - principal-architect → revisa C-04 (superficie OAuth/seguridad), mantén docs/ADRs en sync.
  - data-scientist-fde → NO se necesita (C-05 hecho); spawnéalo solo si surge una duda de modelo.

MAPA DE PROPIEDAD DE FICHEROS (disjunto, sin conflicto):
  pipeline → packages/api, packages/shared, packages/scraper, migrations/, root pyproject, infra.
  reflex-ui → Qualify/.  architect → docs/, CLAUDE.md.

REGLAS DURAS:
  - Un SOLO agente corre `uv sync`/`uv venv` a la vez (venv compartido; un uv concurrente corrompió
    los editables este sprint). Los db-marked tests necesitan docker (no corren en el sandbox del agente).
  - `uv run pytest` verde SIN red en todo paquete tocado; marcas integration (red, nunca CI) / db
    (Postgres/Redis local). Type hints en toda firma; ruff limpio.
  - Ningún access_token en logs, claves de R2, ni en el envelope. Flush incremental a disco.
  - NADIE commitea ni pushea. El árbol queda para revisión del fundador.

OBJETIVO DEMOSTRABLE AL CERRAR: conectar por OAuth la cuenta real de IG de la tienda desde el CRM,
verla sana en /connections leyendo del backend real (no mock), y `uv run pytest -m db` verde probando
que ningún tenant alcanza los datos ni el token de otro.
```
