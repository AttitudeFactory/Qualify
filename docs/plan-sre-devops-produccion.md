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
| Causa de la caída | `api` y `reflex` se recrean **aunque el código no cambió**. Hipótesis inicial: `migrate` los arrastra. Causa real, reproducida el 2026-10-06 (§5, punto 2): `qualify-app` se construía una vez por servicio y el ID de la imagen cambiaba de un deploy a otro |
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
| 1 | ✅ Reflex: copiar `.web/backend` a `app`; bun desde `oven/bun` con caché; quitar `curl`/`unzip` del runtime. Medido en §5 | PR | — |
| 2 | ✅ Cero recreaciones innecesarias (§5): que un deploy sin cambios no recree `api`/`reflex` (p. ej. sacar `migrate` del grafo `depends_on` y correrlo como paso explícito en `deploy.sh` antes del `up`, o `up --no-recreate` condicionado) | PR | — |
| 3 | ✅ Construir la imagen `deploy/Dockerfile` (targets `app` y `web`) **en el CI** — hoy ningún job la construye, un Dockerfile roto sólo se descubre al desplegar | PR | — |
| 4 | ⏳ CD (preparado, §5; espera decisión y secretos del fundador): al quedar `main` en verde, Actions construye `app`/`web`(/`render`) y los publica en GHCR por SHA; el servidor sólo hace `pull` + `up`. Nunca compilar en producción. Rollback = desplegar el SHA anterior | PR | secretos de GitHub (llave ssh de deploy restringida, token GHCR) → **fundador** |
| 5 | Despliegue sin caída del backend: con Redis como state manager (punto 3.2) arrancar el `reflex` nuevo, esperar `healthy` y recién entonces retirar el viejo | PR | 1, 2, decisión 3.2 |
| 6 | `render` en producción: chequeo de `/health` en `deploy.sh`, imagen desde GHCR, límites de memoria (`mem_limit`) para que un render no tumbe Postgres | PR | decisión CX23→CX33 → **fundador** |
| 7 | SRE: monitoreo externo de `/ping` y `/api/...` con alerta, respaldos fuera del servidor (R2 + `age`, `plan-cicd-staging.md` §5.6), backups de Hetzner activados (QUA-121) | PR + fundador | — |
| 8 | Medir un deploy **con** cambio de código (antes y después de 1/3/4) y dejar los números en este documento | medición | acceso ssh → **fundador** |

## 5. Resultados por punto

### Punto 1 — Dockerfile según el ejemplo oficial de Reflex (2026-10-06)

Cambios en `deploy/Dockerfile`: bun sale de `oven/bun:1.4` (Reflex 0.9.12 exige bun ≥ 1.4.0 y usa el que encuentra en `PATH`) con caché de `/root/.bun/install/cache`; ni la etapa de export ni la imagen `app` instalan paquetes con `apt` (fuera `curl`/`unzip`); `.web/backend` se copia del export a `app`, y el build falla si el export no dejó `stateful_pages.json`.

Medido en la sesión en la nube (Docker 29, sin caché; **no** es el CX23):

| Medida | Valor |
|---|---|
| Build `web` en frío (deps + `reflex export`) | 45 s (export 37 s) |
| Build `app` tras `web` (capas compartidas) | 17 s |
| Imagen `app` / `web` | 541 MB / 110 MB |
| Arranque del backend hasta `/ping` 200, **con** `.web/backend` | 4,3–4,5 s (3 corridas) |
| Ídem **sin** `.web/backend` (lo que pasaba antes) | 5,5–6,7 s (3 corridas) |

`stateful_pages.json` sale `[]`: ninguna página crea clases de estado al evaluarse (los estados están a nivel de módulo), así que con el marcador el backend no evalúa ninguna página al arrancar. `.web/backend` también trae `upload_is_used` y `bundled_libraries.json`, que el backend lee al arrancar.

No se pudo medir el Dockerfile **anterior** en esta sesión: el proxy de la organización bloquea `deb.debian.org` y la versión anterior necesitaba `apt-get`. Este Dockerfile tampoco depende ya de ese espejo. La comparación en el servidor la hace el fundador con el próximo `just deploy` (punto 8).

### Punto 2 — un deploy sin cambios no recrea nada (2026-10-06)

Reproducido en la sesión con el stack de producción completo (`deploy/docker-compose.prod.yml` con `.env` desechable, Postgres y Redis reales, `alembic upgrade head` real), simulando `deploy.sh`: build + `up` desde un directorio de release nuevo con el **mismo** árbol.

**Causa real.** `api`, `reflex`, `migrate` y `calendar-worker` compartían `image: qualify-app:<tag>` **y** el mismo `build:`. Compose construye la imagen una vez por servicio, cada copia con su etiqueta `com.docker.compose.service`, y el tag se lo queda la que termina última (a veces `api`, a veces `reflex`). Por eso el ID de `qualify-app` cambiaba entre dos deploys del mismo árbol, y Compose recreaba `api`/`reflex` por cambio de imagen. `migrate` también se recreaba, pero era síntoma, no causa.

**Arreglo.**
1. Sólo `api` declara `build:` de `qualify-app`; los demás servicios sólo la nombran.
2. `migrate` pasa a un perfil propio y deja de ser `depends_on` de `api`/`reflex`/`calendar-worker`. `deploy.sh` corre `run --rm migrate` y, sólo si sale 0, `up -d`. Una migración fallida sigue sin servir tráfico.

| Escenario (mismo árbol, release dir nuevo) | Antes | Después |
|---|---|---|
| Contenedores recreados | `migrate`, `api`, `reflex` | **ninguno** (2 deploys seguidos) |
| Tiempo `build` + `migrate` + `up` | 13 s | 6–7 s |
| Deploy con cambio de código Python | — | recrea `api`, `reflex` y `caddy` (correcto) |

El primer deploy con este cambio recrea `api`/`reflex` una vez, por el cambio de configuración. Del deploy anterior queda un contenedor `qualify-prod-migrate-1` salido; es inocuo y se puede borrar a mano una vez (`docker rm qualify-prod-migrate-1`). **Cambia el procedimiento manual:** un `dc up -d` a secas ya no migra; es `dc run --rm migrate && dc up -d` (runbook actualizado).

### Punto 3 — `deploy/Dockerfile` se construye en el CI (2026-10-06)

Job `ci` / `docker-deploy`:
- **Qué hace:** construye `web` y `app` sin publicarlos, con caché de GHA (`scope=deploy`), y después corre dos smoke tests: el backend de Reflex arranca y responde `/ping` 200, y Caddy sirve `/`, `/login` y una ruta dinámica.
- **Cuándo corre:** en PRs que tocan alguna entrada de las imágenes (`deploy/**`, `Qualify/**`, `packages/*/src/**`, locks, `rxconfig.py`, `assets/**`, `migrations/**`) y siempre en `main`. Un PR sólo de docs no lo corre.

Un Dockerfile roto, o una página que rompe `reflex export`, se descubre en el PR y ya no en el servidor de producción. Entra en la lista de checks que exige `just merge` (y en `infra/github/ruleset-main.json`), junto con `changes`. Cuando se salta, el check queda `skipped` y cuenta como verde, así que `changes` también tiene que ser requerido: si fallara, `docker-deploy` y `node-render` se saltarían y pasarían como verdes. **Efecto en PRs abiertos antes de este cambio:** no tienen ese check, así que `just merge` los rechaza hasta que se les mergee `main` (o se fuerza con `--admin`).

### Punto 4 — CD: opciones para el fundador (2026-10-06) `[DECISIÓN PENDIENTE]`

Hoy cada deploy compila en el servidor de producción (export del frontend incluido, ~10–15 min en frío en el CX23, compitiendo por CPU y RAM con los usuarios) y sólo se dispara a mano desde la Mac.

| Opción | Cómo | Compila en producción | Qué secretos | Pros | Contras |
|---|---|---|---|---|---|
| **A. GHCR + ssh restringido** (recomendada) | Actions construye y publica `qualify-{app,web,deploy}:<sha>` en GHCR; después hace ssh con una llave que **sólo** puede ejecutar `server-deploy.sh deploy <sha>`. El servidor hace `pull`, saca compose y scripts de `qualify-deploy` (nunca del cliente) y corre `migrate` → `up` | **no** | GitHub: llave ssh restringida, destino, `known_hosts`. Servidor: token *classic* `read:packages` | Imagen idéntica a la que probó el CI; rollback = otro sha; resultado y logs en Actions; es el diseño de `plan-cicd-staging.md` §5.5 | La llave vive en GitHub (acotada por el forced command); GHCR es un registro nuevo |
| B. GHCR + el servidor se actualiza solo | Igual que A para las imágenes, pero un timer en el servidor consulta un tag `:main` cada N minutos y despliega | no | Servidor: token `read:packages`. GitHub: nada | Ninguna llave del servidor en GitHub | Deploys silenciosos (el resultado no vuelve a Actions); el rollback exige "fijar" un tag a mano; más piezas en el servidor |
| C. Sin registro: Actions dispara `deploy.sh` | Actions hace lo mismo que la Mac hoy (`git archive` por ssh) y el servidor compila | **sí** | GitHub: llave ssh | Ningún servicio nuevo | Sigue compilando en producción: deploys lentos y el CX23 cargado durante cada build |
| D. Runner auto-hospedado en el servidor | Un runner de Actions en el propio CX23 hace build y `up` | sí | Token de registro del runner | Sin ssh entrante; minutos de Actions gratis | Cualquier workflow del repo ejecuta como `docker` (= root) en producción; compila en producción |

**Recomendación: A**, primero sólo manual y con `QUALIFY_AUTO_DEPLOY=true` después de 2 o 3 deploys manuales sanos.

**Costo:**
- **GHCR:** hoy no cobra almacenamiento ni transferencia de imágenes de contenedor, tampoco privadas, y GitHub promete avisar con un mes de anticipación `[V: docs.github.com, "How use of GitHub Packages is measured", vía buscador; la página no fue accesible desde la sesión]`.
- **Minutos de Actions:** ~4–8 min por deploy con la caché caliente `[H]`. Con auto-deploy y ~30 merges al mes son ~150–250 min, a sumar al presupuesto de `plan-cicd-staging.md` §4.

**Preparado en el repo (inerte hasta que el fundador lo monte):**
- `.github/workflows/deploy.yml`: `workflow_dispatch`, más `workflow_run` de `ci` en `main` cuando la variable `QUALIFY_AUTO_DEPLOY` es `true`.
- `deploy/server-deploy.sh`: el forced command. No lee nada del cliente salvo el sha: el `deploy/` del release sale de la imagen `qualify-deploy:<sha>` (target `deploy-bundle` del Dockerfile), así que la llave sólo puede desplegar un commit que el CI publicó. Arma el release en un directorio temporal y lo mueve al final; si el release ya existe, lo reutiliza sin borrarlo. El workflow sólo acepta commits que estén en `main`.
- `deploy/healthcheck.sh`: los chequeos que comparten `deploy.sh` y `server-deploy.sh`.
- Prefijo de registro en `docker-compose.prod.yml` (`QUALIFY_IMAGE_PREFIX`; vacío = como hoy).
- Pasos de montaje en `despliegue-hetzner.md` §7.1.

Probado en la sesión con un registro local en lugar de GHCR, sobre un "servidor" vacío:
- **Primer deploy:** `0001 → 0040`, chequeos `ok`, 20 s.
- **Re-deploy del mismo sha:** no recrea nada.
- **`up` con el comando de `deploy.sh` sobre ese release:** no compila (respeta `release.env`).
- **La llave rechaza** todo lo que no sea `deploy <sha de 40 hex>`. Un sha que el CI no publicó falla en el `pull`, antes de tocar el disco: `current` no cambia.
- **Re-deploy del sha al que ya apunta `current`:** reutiliza el release sin borrarlo.
- El release incluye `backup-db.sh`, que el cron nocturno ejecuta desde `current/deploy/` (antes `.dockerignore` excluía `deploy/*.sh` del contexto; ningún target de la app los copia).
- **Con el perfil `render` activo,** el CD se niega.

**Lo que no se pudo probar acá:** el push real a GHCR (el proxy de la sesión bloquea las descargas de GHCR) y el ssh real. Lo prueba el primer *Run workflow* del fundador.

## 6. Reglas para quien ejecute este plan

- **Sin acceso al servidor.** La sesión en la nube no tiene llave ssh y no debe pedirla: todo cambio llega por PR; desplegar y medir en producción lo hace el fundador con `just deploy deploy@<IP>`.
- **Merge sólo con CI en verde y vía `just merge <pr>`** (nunca `gh pr merge`, nunca push a `main`). `just` se instala con `uv tool install rust-just`.
- Cada servicio o runtime nuevo (registro de imágenes, monitoreo, etc.) se presenta con tabla de opciones + recomendación y lo elige el fundador.
- El perfil `calendar-worker` **publica de verdad**: ningún cambio puede activarlo como efecto secundario.
