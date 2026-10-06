# Plan — mejoras de SRE/DevOps sobre la producción en Hetzner

**Estado:** `[PLAN 2026-10-06]` — punto de partida medido, trabajo pendiente ordenado. Lo ejecuta una sesión en la nube (código + PRs); **nada de esto toca el servidor directamente**.

**Contexto:** el PR #85 (despliegue en un VPS de Hetzner con Compose + Caddy) se mergeó el 2026-10-06 (`d226124`). Producción corre en `https://qualify.attitudefactory.co` (CX23: 2 vCPU · 4 GB, Núremberg). Runbook: [`despliegue-hetzner.md`](despliegue-hetzner.md). Plan de CI/CD original: [`plan-cicd-staging.md`](plan-cicd-staging.md).

## 1. Línea base medida (2026-10-06)

Deploy de `main` (`d226124`, árbol idéntico al release previo `8a31f78`) con `just deploy deploy@<IP>` desde la Mac, con un sondeo externo a `/ping` y `/login` cada ~2 s:

| Medida | Valor |
|---|---|
| Tiempo total (Mac → chequeos en verde), todo en caché | **28 s** (subida 4 s · build 6 s · `up` + migrate ~7 s · poda 5 s · health 2 s) |
| Chequeos de `deploy.sh` | 3/3 ok |
| Caída observada | **~10 s de 502 en `/ping`** (backend de Reflex). `/login` (estático en Caddy) siguió en 200 |
| Causa de la caída | `migrate` (one-shot) se recrea en cada `up` y Compose recrea `api` y `reflex`, que dependen de él, **aunque la imagen no cambió** |
| Deploy con cambio de código | **no medido**. Compila en el propio servidor de producción (export del frontend incluido); el runbook estima 10–15 min en frío |

Hoy **no hay deploy automático**: mergear a `main` no despliega. El deploy es manual desde la Mac del fundador.

## 2. Remotion (servicio `render`) — no está orquestado en producción

- Está **definido** en `deploy/docker-compose.prod.yml` como perfil opcional `render`, pero en el servidor `COMPOSE_PROFILES` está vacío: **el contenedor no existe y su imagen nunca se construyó allí**. El generador por plantillas (`ContentKind.TEMPLATE`) falla en producción con error claro.
- El runbook pide **CX33** (4 vCPU · 8 GB) para activarlo: Chromium pide ~1 GB al renderizar y el CX23 tiene ~2,9 GB disponibles con el stack actual. **Es una decisión del fundador** (costo del servidor), no de la sesión.
- Huecos de orquestación aunque se active: `deploy.sh status` no chequea `render` (`/health` con `bundleReady`); `api`/`reflex` no lo declaran en `depends_on`; el CI construye la imagen de render sólo si el PR toca `packages/render/**` y nunca la publica; el build de la imagen (descarga de Chrome Headless Shell) correría en el servidor de producción.

## 3. Brechas contra el ejemplo oficial de Reflex

Referencia: `reflex-dev/reflex` → `docker-example/production-compose` (Dockerfile, Caddyfile, `compose.prod.yaml`). La arquitectura coincide (Caddy + TLS automático + `reflex export --frontend-only` estático + `reflex run --env prod --backend-only`, sin bun/node en runtime, mismas rutas al backend). Faltan:

1. **`.web/backend` no se copia a la imagen `app`.** El ejemplo lo copia desde la etapa de export "para que el backend sólo evalúe las páginas con estado al arrancar". Sin él, el arranque es más lento y alarga la caída de cada deploy.
2. **Estado en disco con 1 worker** (`GRANIAN_WORKERS=1`, volumen `reflex_states`). El ejemplo robusto usa `REFLEX_REDIS_URL` y `2·CPU+1` workers; Redis ya está en el stack. **Cuidado:** el login vive en el estado del backend (`Qualify/auth_state.py`) — antes de cambiar, verificar la expiración de tokens del state manager de Redis (`redis_token_expiration` en `rx.Config`) para no cerrar sesiones antes de tiempo, y que Redis persista (`--save` ya está).
3. **bun lo descarga Reflex en cada build** (por eso la etapa instala `curl`/`unzip`). El ejemplo hace `COPY --from=oven/bun:1 /usr/local/bin/bun` + `--mount=type=cache,target=/root/.bun/install/cache`.
4. La imagen `app` instala `curl`/`unzip` "por si acaso"; el ejemplo no los necesita en runtime.
5. Menor: `precompressed` sólo `gzip` (el ejemplo admite `br zstd` si se activan en `frontend_compression_formats`).

## 4. Trabajo pendiente, en orden

| # | Qué | Tipo | Bloqueado por |
|---|---|---|---|
| 1 | Reflex: copiar `.web/backend` a `app`; bun desde `oven/bun` con caché; quitar `curl`/`unzip` del runtime. Medir el arranque antes/después | PR | — |
| 2 | Cero recreaciones innecesarias: que un deploy sin cambios no recree `api`/`reflex` (p. ej. sacar `migrate` del grafo `depends_on` y correrlo como paso explícito en `deploy.sh` antes del `up`, o `up --no-recreate` condicionado) | PR | — |
| 3 | Construir la imagen `deploy/Dockerfile` (targets `app` y `web`) **en el CI** — hoy ningún job la construye, un Dockerfile roto sólo se descubre al desplegar | PR | — |
| 4 | CD: al quedar `main` en verde, Actions construye `app`/`web`(/`render`) y los publica en GHCR por SHA; el servidor sólo hace `pull` + `up`. Nunca compilar en producción. Rollback = desplegar el SHA anterior | PR | secretos de GitHub (llave ssh de deploy restringida, token GHCR) → **fundador** |
| 5 | Despliegue sin caída del backend: con Redis como state manager (punto 3.2) arrancar el `reflex` nuevo, esperar `healthy` y recién entonces retirar el viejo | PR | 1, 2, decisión 3.2 |
| 6 | `render` en producción: chequeo de `/health` en `deploy.sh`, imagen desde GHCR, límites de memoria (`mem_limit`) para que un render no tumbe Postgres | PR | decisión CX23→CX33 → **fundador** |
| 7 | SRE: monitoreo externo de `/ping` y `/api/...` con alerta, respaldos fuera del servidor (R2 + `age`, `plan-cicd-staging.md` §5.6), backups de Hetzner activados (QUA-121) | PR + fundador | — |
| 8 | Medir un deploy **con** cambio de código (antes y después de 1/3/4) y dejar los números en este documento | medición | acceso ssh → **fundador** |

## 5. Reglas para quien ejecute este plan

- **Sin acceso al servidor.** La sesión en la nube no tiene llave ssh y no debe pedirla: todo cambio llega por PR; desplegar y medir en producción lo hace el fundador con `just deploy deploy@<IP>`.
- **Merge sólo con CI en verde y vía `just merge <pr>`** (nunca `gh pr merge`, nunca push a `main`). `just` se instala con `uv tool install rust-just`.
- Cada servicio o runtime nuevo (registro de imágenes, monitoreo, etc.) se presenta con tabla de opciones + recomendación y lo elige el fundador.
- El perfil `calendar-worker` **publica de verdad**: ningún cambio puede activarlo como efecto secundario.
