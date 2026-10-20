# Plan — CI/CD a costo cero y despliegue a staging del MVP

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Estado:** `[PLAN 2026-10-05]` — encargo del fundador del mismo día. Nada de esto está implementado; dos agentes construyen el CI y la revisión automática en sus ramas usando este documento como contrato.
**Veredicto en una línea:** en un repo **privado** de una organización **Free**, casi todo lo "gratis" del mercado deja de serlo; el CI/CD a costo cero se arma con **CLIs open source dentro de GitHub Actions** y el bloqueo real se pone **en el deploy, no en el merge** (staging nunca recibe un `main` en rojo).
**Convención:** `[V 2026-10-05]` = verificado hoy contra la fuente (precio, licencia, límite); `[H]` = hipótesis o estimación propia; `[M]` = medido en este repo hoy. Los precios **caducan**.
**Alcance:** sólo planificación. No decide el host (§7 D1) ni escribe workflows, Dockerfiles ni código.

---

## 1. Estado actual (10 líneas)

1. Un solo workflow, `.github/workflows/ci.yml`: job `test` en `ubuntu-latest` con servicios `postgres:16` + `redis:7`. `[M]`
2. Pasos: `uv sync` → `ruff check` → `ruff format --check` → `alembic upgrade head` → `pytest -m "not integration"` (incluye los `db`). `[M]`
3. Dispara en `push` a **cualquier rama** + `pull_request` → cada push a una rama con PR abierto corre **dos veces**. `[M]`
4. Últimos 60 runs (2026-09-23 → 10-05): 38 `push` + 22 `pull_request`, mediana ~1,2 min de reloj, 54 verdes / 6 rojos → ~150 runs/mes. `[M]`
5. Sin coverage, sin SAST, sin escaneo de dependencias/secretos/contenedores, sin build de imágenes, sin despliegue. `[M]`
6. Sin branch protection posible: la API devuelve 403 en privado + Free (hecho dado por el encargo). Tampoco hay **environment secrets** ni reviewers de despliegue en privado Free. `[V 2026-10-05]`
7. No existe ningún `Dockerfile` en `main`; `packages/render/` (Node 22 + Remotion, con Dockerfile) llega con el PR #65, aún abierto. `[M]`
8. Despliegue: **ninguno**. `rxconfig.py` sin `api_url`/CORS y con `db_url="sqlite:///reflex.db"`; el OAuth de Meta vive en un túnel `cloudflared` efímero. `[M]`
9. Hay **dos procesos HTTP**: la app Reflex (con `avatar_api` montado por `api_transformer`) y la FastAPI `qualify_api.http.app:create_app` (rutas `/api/*` y `/public/media/*`, incluido `/api/connections/callback`). `[M]`
10. Migraciones: head `0037` en `main` (`0038` en curso en otra rama); se editan **en sitio** (ADR 27 R8a) porque nada está desplegado — el primer deploy cierra esa puerta. `[M]`

## 2. Pipeline objetivo

### 2.1 Disparadores (racionalizados)

| Evento | Qué corre | Por qué |
|---|---|---|
| `pull_request` a `main` (opened, synchronize, reopened, ready_for_review) | Etapas A–D | Es donde se decide el merge |
| `push` a `main` | Etapa A ligera + E + F | Lo mergeado se empaqueta y despliega |
| `workflow_dispatch` | Cualquier etapa (deploy manual, re-deploy de un SHA anterior = rollback) | Operación |
| `schedule` semanal (lunes 06:00 UTC) | Escaneo completo (G) | Detecta CVEs nuevas sobre código que no cambió |
| `push` a otras ramas | **Nada** | Hoy duplica cada run de PR |

`concurrency: group: ${{ github.workflow }}-${{ github.ref }}`, `cancel-in-progress: true` en PR (no en `main`). Borradores (`draft`) corren sólo la etapa A.

### 2.2 Grafo de jobs

```
PR ─┬─ A1 checks ......... un solo job, un solo `uv sync`:                              [bloquea]
    │                         ruff check --output-format=github · ruff format --check
    │                         · gitleaks (commits del PR) · pip-audit (uv export)
    │                         · npm audit (si cambia render; informa → bloquea sem. 3)
    ├─ A2 py-offline ...... pytest -m "not integration and not slow and not db" + coverage + comentario [bloquea]
    ├─ A3 sast ............ semgrep CE (diff-aware) — ruff S ya corre en A1               [bloquea en ERROR]
    │
    ├─ B1 py-db (needs A1) . servicios pg+redis · alembic upgrade head · pytest -m "db and not slow"
    │                         · alembic downgrade base (reversibilidad, ADR 27)          [bloquea]
    ├─ B2 node (paths: packages/render/**) . npm ci · tsc --noEmit · build             [bloquea]
    │
    ├─ C1 docker-build (paths: Dockerfile*, uv.lock, package-lock.json, packages/render/**)
    │      build sin push, cache type=gha · trivy image (CRITICAL/HIGH con fix)          [informa → bloquea sem. 3]
    │
    └─ D1 review (opened / ready_for_review / comentario "@claude") . claude-code-action [informa]

main ─ A1+A2+B1 (re-verifica lo mergeado) ─▶ E1 build+push GHCR (tag = SHA, +staging)
                                         ─▶ E2 trivy sobre la imagen publicada
                                         ─▶ F1 deploy-staging (SSH → deploy.sh <sha>) ─▶ F2 smoke (/_health, /api/…)
                                         └▶ si algo falla: issue "main en rojo" + NO deploy

semanal ─ G: gitleaks historial completo · semgrep completo · pip-audit · npm audit
             · osv-scanner (repo) · trivy sobre las imágenes `:staging` vivas
```

### 2.3 Qué «bloquea» si GitHub no deja bloquear

Sin branch protection en privado Free `[V 2026-10-05]`, ningún check impide técnicamente el botón de merge. Tres capas, de más a menos dura:

| Capa | Mecanismo | Dureza |
|---|---|---|
| **1. Gate en el deploy** | F1 tiene `needs:` sobre A1/A2/B1 re-ejecutados en `main` + E2. Un merge rojo **no llega a staging**; abre issue "main en rojo" automáticamente | **Dura** — es la que importa: lo que ve Meta y el cliente nunca está roto |
| 2. Puerta única de merge | Receta `just merge <pr>`: `gh pr checks <pr>` todo verde + no draft + squash. Regla en `CLAUDE.md`: agentes y humanos mergean **sólo** por ahí (extiende la regla ya vigente "nunca push a main") | Convención con herramienta |
| 3. Pago más barato | **GitHub Team: US$4/usuario/mes** `[V 2026-10-05; la página lo marca "first 12 months"]` → branch protection + required checks en privado, 3.000 min/mes, environment secrets. Con 1 asiento = US$4/mes | Dura en el merge |

Nombres de job **estables** (`checks`, `py-offline`, `sast`, `py-db`, `node`, `docker-build`, `review`): si un día se paga Team, se declaran como required sin tocar workflows.

## 3. Herramientas a costo cero para repo PRIVADO

| Categoría | Elegida | Costo | Dónde corre | Qué produce en el PR | Descartada · por qué |
|---|---|---|---|---|---|
| Lint / estilo | `ruff` (ya en el repo) + reglas `S` (bandit) y `C90` (complejidad, informativo) | US$0, MIT | A1 `checks`, runner GitHub | Anotaciones en línea nativas (`--output-format=github`) | **Bandit** aparte: `ruff S` reimplementa sus reglas — una herramienta menos `[H]` |
| Calidad (dashboard) | **Ninguna en semanas 1–2**; quality gate = suma de CLIs (§6 sem. 3) | US$0 | — | Checks + comentario de coverage | **SonarQube Cloud Free:** privado hasta **50k LoC** `[V]`; Qualify tiene ~75k líneas fuente no vacías ni comentario (sin tests) `[M]` → fuera del límite; Team desde **US$34/mes** `[V]`. **SonarQube Community Build:** gratis `[V]`, pero **sólo analiza la rama principal, sin análisis ni decoración de PR** `[V]`, pide **4 GB de RAM** `[V]` y Postgres 15–18 `[V]` → un servidor más que mantener para un panel que nadie mira en el PR. Ver D5 |
| SAST | **Semgrep CE CLI** (`p/python`, `p/typescript`, `p/dockerfile`) | US$0, LGPL-2.1, corre offline sin login `[V]` | A3 (diff-aware) + G (completo) | Anotaciones vía **reviewdog** (`-f=sarif`) `[H: licencia MIT]` | **CodeQL:** en privado exige GitHub Code Security, **US$30/committer/mes** `[V]`; subir SARIF a Code Scanning también. Licencia de reglas del Registry (uso interno OK, no revender) `[H]` |
| Vulnerabilidades de dependencias | **pip-audit** sobre `uv export --frozen` (DB: PyPI Advisory/OSV) · **npm audit** (GitHub Advisory DB) · **OSV-Scanner** semanal (Apache-2.0 `[V]`) · **Dependabot alerts** | US$0 — Dependabot alerts y dependency graph "incluidos en todos los planes" `[V]` | A1, G; Dependabot en GitHub | Fallo de job + resumen; PRs de Dependabot semanales | Soporte de OSV-Scanner a `uv.lock` no confirmado `[H]` → por eso pip-audit sobre el export. Dependabot sobre `uv.lock` `[H]` (verificar al configurarlo) |
| Contenedores | **Trivy CLI** (Apache-2.0 `[V]`) instalado por versión fija + checksum | US$0 | C1, E2, G | Tabla de CVEs en el job summary | **`aquasecurity/trivy-action` por tag: PROHIBIDO.** En marzo 2026 los atacantes reescribieron 75 de 76 tags de `trivy-action` y los de `setup-trivy`, y exfiltraron los secretos de cada workflow que corrió `[V 2026-10-05, Wiz/SafeDep]`. Regla general: **toda action de terceros fijada por SHA de commit** |
| Secretos | **Gitleaks CLI** (MIT `[V]`, binario o `ghcr.io/gitleaks/gitleaks` por digest) | US$0 | A1 (commits del PR), G (historial) | Fallo con fichero:línea | **`gitleaks-action` v2:** licencia propietaria, en organizaciones exige license key (gratis, con registro) `[V]` → el CLI evita el alta. **Push protection de GitHub:** GitHub Secret Protection **US$19/committer/mes** `[V]` |
| Coverage | **pytest-cov** + **`py-cov-action/python-coverage-comment-action`** (MIT, funciona en privado, nada sale de GitHub `[V]`) + **diff-cover** para % de líneas cambiadas `[H]` | US$0 | A2 (+ B1 combina `.coverage`) | Comentario en el PR con % total y del diff; badge SVG | **Codecov Developer:** en privado **1 usuario y 250 subidas/mes** `[V]`; Team US$5/usuario `[V]`. El HTML navegable del action no existe en privado `[V]` → se sube como artifact |
| Revisión automática | **`anthropics/claude-code-action@v1`** (fijado por SHA) | US$0 marginal con **`CLAUDE_CODE_OAUTH_TOKEN`** (`claude setup-token`, cuentas Pro/Max `[V]`) — consume la cuota Max del fundador; alternativa API key = pago por tokens (~US$0,3–1/revisión con Sonnet `[H]`) | D1 | Comentario de revisión + sugerencias en línea | **CodeRabbit:** gratis **sólo repos públicos**; Essentials **US$24/dev/mes** `[V]`. **Copilot code review:** no está en Copilot Free; consume créditos (US$0,05–5 por revisión) `[V]` |
| Typecheck | `tsc --noEmit` para `packages/render` | US$0 | B2 | Fallo con fichero:línea | **pyright/mypy en Python:** sin configuración hoy; activarlo generaría cientos de errores heredados → informativo, más adelante `[H]` |
| Imágenes | `docker/build-push-action` + buildx con cache `type=gha` → **GHCR privado** | US$0 — almacenamiento y ancho de banda del Container registry "actualmente gratis", aviso de 1 mes antes de cambiar `[V]`; transferencia desde Actions con `GITHUB_TOKEN` no cuenta `[V]` | C1 (sin push), E1 (push) | — | Docker Hub privado (límites de pull) `[H]` |

## 4. Presupuesto de minutos de Actions

Plan Free, privado: **2.000 min/mes**, sin método de pago **el uso se bloquea al agotarse** `[V]`. Con método de pago, Linux 2-core cuesta **US$0,006/min** `[V]` (500 min extra ≈ US$3). Runners auto-hospedados: **gratis** `[V]`.

Supuestos `[H]`: 30 PRs/mes, 3 pushes por PR, 30 merges a `main`; duraciones facturadas por job, redondeadas al minuto.

| Bloque | Jobs y minutos por ejecución `[H]` | Ejecuciones/mes | Min/mes |
|---|---|---|---|
| PR (cada push) | checks 2 · py-offline 3 · sast 2 · py-db 3 = **10** | 90 | 900 |
| PR condicional | node 2 (20 % de PRs) · docker-build 6 (20 %) | 90 | ~145 |
| Revisión Claude | ~3 por disparo, ~1,5 disparos por PR | 45 | 135 |
| `main` | checks+py-offline+py-db 7 · build+push 2 imágenes 8 · trivy 2 · deploy+smoke 2 = **19** | 30 | 570 |
| Semanal | escaneo completo ~8 | 4,3 | 35 |
| **Total** | | | **~1.785 (89 %)** |

Demasiado justo. Palancas, en orden:

| Palanca | Ahorro `[H]` |
|---|---|
| `concurrency` con `cancel-in-progress` en PR (los pushes en ráfaga cancelan el anterior) | −20–30 % del bloque PR |
| (Ya aplicado en la tabla) lint + gitleaks + auditoría de dependencias en un solo job `checks`: un `uv sync` en vez de tres, menos redondeo | ya descontado |
| `paths-filter`: un PR que sólo toca `docs/**` corre sólo `checks` | −10–15 % |
| Cache de `uv` (`setup-uv` `enable-cache`) y `npm` (`setup-node` `cache: npm`), buildx `type=gha` | −1–2 min por job |
| Drafts sólo corren la etapa A; revisión Claude sólo en opened/ready/`@claude` | — |
| **Válvula:** runner auto-hospedado en el host de staging **sólo para E1** (build de imágenes, gratis `[V]`), de noche | −240 |

Objetivo medible: **≤ 1.300 min/mes** (65 %). Revisión semanal del uso en *Settings → Billing*; si dos meses seguidos supera 80 %, ver D3.

## 5. Staging del MVP

### 5.1 Qué es este entorno (leer antes que el resto)

`qualify.attitudefactory.co` será **el único entorno estable**: el redirect URI que Meta revisa, el que ve el cliente cero, donde vivirán **tokens OAuth reales** (Polet, Bianki). Se llama "staging" en el CI, pero se opera con disciplina de producción en secretos, backups y migraciones. Consecuencias inmediatas:

- **ADR 27 R8a se cierra en el primer deploy**: desde ese día las migraciones son **sólo aditivas**; nunca más se edita una revisión aplicada (D7).
- **El worker del calendario publica de verdad** (`QUALIFY_CALENDAR_WORKER=embedded` por defecto arranca dentro de cada proceso backend). En staging: `QUALIFY_CALENDAR_WORKER=off` en la app y, si se decide encenderlo, **un servicio `calendar-worker` aparte** con `QUALIFY_CALENDAR_WORKER_TENANTS` explícito (D6).

### 5.2 Arquitectura en el host (Docker Compose)

```
                 Internet :443 / :80
                        │
                ┌───────▼────────┐  TLS automático (Let's Encrypt)
                │     caddy      │  qualify.attitudefactory.co
                └──┬──────────┬──┘
   /api/* , /public/media/*   │  todo lo demás (incl. /_event websocket, /_health, /r2media)
          ┌────────▼───┐   ┌──▼─────────────┐
          │    api     │   │      app       │   misma imagen `qualify-app`, dos comandos:
          │ uvicorn    │   │ reflex run     │   api = uvicorn qualify_api.http.app:create_app --factory
          │ :8010      │   │ --env prod     │   app = reflex run --env prod (un puerto, :3000)
          └──┬───┬─────┘   └──┬───┬──┬──────┘
             │   │            │   │  └────────────► render :3001 (Node 22 + Remotion, imagen `qualify-render`)
       ┌─────▼┐ ┌▼──────┐ ◄───┘   │
       │postgres│ │ redis │◄───────┘     red interna `qualify_net`; NINGÚN puerto publicado salvo caddy
       │  :5432 │ │ :6379 │
       └───┬────┘ └───────┘
           │ volumen pgdata          (calendar-worker: servicio opcional, misma imagen, D6)
           └─► pg_dump nocturno → R2 bucket `qualify-backups`
```

| Pieza | Decisión | Nota |
|---|---|---|
| Proxy | **Caddy** | TLS automático con una línea por host; WebSockets sin configuración extra `[H]`. Traefik descartado: etiquetas Docker y más superficie para un solo host |
| Postgres | `postgres:16` (las migraciones sólo usan `pg_trgm` y `pgcrypto`, contrib estándar `[M]`); `pgvector/pgvector:pg16` cuando llegue Parte 3 | Sin `ports:`; `shm_size` 256 MB |
| Redis | `redis:7` con `appendonly yes` | Lo usan los locks/`state` OAuth y el estado de Reflex con varios workers |
| Reflex | `REFLEX_API_URL=https://qualify.attitudefactory.co`, `REFLEX_REDIS_URL`, `GRANIAN_WORKERS=2` `[H]` | Con Redis, Reflex arranca `2·CPU+1` workers `[V]` — por eso el calendario embebido va `off` |
| Render | Sólo red interna; `QUALIFY_RENDER_URL=http://render:3001` `[H puerto]` | Chromium de Remotion: límite de memoria `mem_limit` 2 GB `[H]` |
| Logs | Driver `json-file` con `max-size: 10m`, `max-file: 5`; `docker compose logs -f <svc>` | Agregador centralizado: fuera de alcance (Fase 6) |
| Healthchecks | `pg_isready`, `redis-cli ping`, app `GET /_health` `[V: ruta de Reflex]`, api `GET /api/...` (añadir `/api/health`) | Caddy sólo enruta a contenedores sanos |
| Monitor externo | Ping HTTP cada 5 min desde un servicio gratuito (UptimeRobot/Better Stack) `[H: plan gratis no verificado]` | **No** un cron de Actions: 1 run/h = ~720 min/mes |

### 5.3 Red, firewall y acceso

- Firewall de Hetzner (gratis `[H]`) + `ufw`: entrantes sólo 80, 443 y 22.
- SSH sólo con llave; usuario `deploy` no-root. La llave que usa Actions va en `authorized_keys` con **`command="/opt/qualify/deploy.sh"`, `no-pty`, `no-port-forwarding`**: aunque se filtre, sólo puede desplegar un SHA. (El grupo `docker` equivale a root: por eso la llave forzada importa.)
- Postgres y Redis nunca expuestos; acceso de administración por `ssh -L`.

### 5.4 Secretos

**Environment secrets no existen en privado Free** `[V]` → el diseño minimiza lo que vive en GitHub:

| Dónde | Qué |
|---|---|
| **GitHub — secretos de repositorio** (sí disponibles en Free) | `STAGING_SSH_KEY`, `STAGING_SSH_HOST`, `STAGING_SSH_KNOWN_HOSTS`, `CLAUDE_CODE_OAUTH_TOKEN`. Nada de la app |
| **Host — `/opt/qualify/.env`** (`chmod 600`, dueño `deploy`, fuera del repo, respaldado cifrado aparte) | DSNs de los cuatro roles (`QUALIFY_MIGRATION_DSN`, `QUALIFY_APP_DSN`, `QUALIFY_ADMIN_DSN`, `QUALIFY_CREDENTIAL_DSN`), `QUALIFY_REDIS_URL`, `QUALIFY_META_*` (incl. `QUALIFY_META_REDIRECT_URI`), `QUALIFY_OAUTH_STATE_SECRET`, llave maestra de credenciales (hoy `QUALIFY_DEV_FERNET_KEY` + `QUALIFY_DEV_KEY_ID`), `QUALIFY_ANTHROPIC_API_KEY`, `QUALIFY_HEYGEN_API_KEY`, `QUALIFY_R2_*`, `QUALIFY_SUPABASE_*`, `QUALIFY_CANVA_*`, `QUALIFY_PUBLIC_MEDIA_BASE_URL`, `QUALIFY_RENDER_URL`, `QUALIFY_CALENDAR_WORKER=off` |
| **Host — sólo lectura de GHCR** | PAT fino con `read:packages` para `docker login ghcr.io` |
| **Nunca** | En el repo, en una imagen, en logs, en argumentos de línea de comandos |

Tres trampas del código actual que staging **no puede heredar** `[M]`:

1. `packages/api/src/qualify_api/connections/crypto.py` trae una llave Fernet por defecto **commiteada** y cae en ella si falta `QUALIFY_DEV_FERNET_KEY`. Staging debe **fallar al arrancar** si la variable no está (fail-closed), y la variable merece un nombre sin `DEV`.
2. Las migraciones `0001`/`0002` crean los roles con contraseñas de desarrollo (`app_dev`, `admin_dev`, `credential_dev`); su propio comentario manda rotarlas fuera de banda. El bootstrap del host ejecuta `ALTER ROLE … PASSWORD` una vez, antes del primer arranque.
3. `QUALIFY_AUTH_FAKE=1` y `QUALIFY_DEV_PRINCIPALS` deben estar **prohibidos** en staging: chequeo al arranque que aborta si aparecen junto a `QUALIFY_ENV=staging`.

Gitleaks marcará 1 y 2 como hallazgos el primer día: van a `.gitleaks.toml` como allowlist **con motivo escrito**, no se silencian a ciegas.

### 5.5 Proceso de deploy (push de `main` → GHCR → pull en el host)

```
E1  build qualify-app y qualify-render → ghcr.io/attitudefactory/qualify-{app,render}:<sha> (+ :staging)
E2  trivy image <sha>   (CRITICAL con fix disponible = no deploy, desde sem. 3)
F1  ssh deploy@host  <sha>        # la llave forzada ejecuta deploy.sh <sha>
      deploy.sh:
        1. docker compose pull  (imágenes :<sha>)
        2. pg_dump -Fc → /opt/qualify/backups/pre-<sha>.dump  (+ copia a R2)
        3. docker compose run --rm migrate  alembic upgrade head      # como qualify_owner
        4. docker compose up -d api app render [calendar-worker]
        5. espera healthchecks (90 s máx)
        6. si falla → re-despliega el <sha> anterior (guardado en /opt/qualify/CURRENT) y sale ≠ 0
        7. escribe <sha> en CURRENT
F2  smoke desde el runner: GET https://qualify.attitudefactory.co/_health y /api/health = 200
```

| Tema | Regla |
|---|---|
| Por qué pull desde GHCR y no build en el host | Imagen idéntica a la escaneada; el host no necesita código fuente ni Node; rollback = re-pull de un tag |
| Rollback de código | `gh workflow run deploy-staging -f sha=<anterior>` (o `just deploy-staging <sha>`) |
| Rollback de esquema | **Forward-fix por defecto.** `alembic downgrade` sólo si la revisión es reversible y no destruye datos; si no, restaurar `pre-<sha>.dump`. Las migraciones deben ser **compatibles hacia atrás con la imagen anterior** (expand → contract en dos deploys) |
| Retención de imágenes | Últimos 10 SHAs en GHCR; borrado semanal de los demás `[H]` |

### 5.6 Backups de Postgres

| Capa | Frecuencia | Retención | Costo |
|---|---|---|---|
| `pg_dump -Fc` → R2 `qualify-backups` (cifrado con `age`, llave fuera del host) | Diario + antes de cada deploy | 14 diarios + 8 semanales (lifecycle de R2) | R2: céntimos a este volumen `[H: precio no verificado hoy]` |
| Backups del servidor de Hetzner | Diario | 7 | **20 % del precio del servidor** `[V, fuente secundaria]` |
| **Simulacro de restore** | Mensual, a un Postgres desechable | — | Criterio de hecho de la semana 2 |

### 5.7 Dominio, Meta y redirects

1. `vercel dns add attitudefactory.co qualify A <IP>` (+ AAAA). Caddy emite el certificado al primer request.
2. `QUALIFY_META_REDIRECT_URI=https://qualify.attitudefactory.co/api/connections/callback` y registrarlo en *Facebook Login for Business → Valid OAuth Redirect URIs* (app `1670943920870196`); borrar los túneles `cloudflared` de los runbooks.
3. Mismo ejercicio para Supabase Auth (Site URL + Redirect URLs) y Canva (`QUALIFY_CANVA_REDIRECT_URI`).
4. `QUALIFY_PUBLIC_MEDIA_BASE_URL=https://qualify.attitudefactory.co/public/media`: Meta descarga de ahí los medios que se publican.
5. Recién con esto en verde: Business Verification (`docs/prioridad-despliegue-subdominio.md` §6).

### 5.8 Host: comparativa

Corrección a `docs/prioridad-despliegue-subdominio.md` §4: el **CX22 ya no existe** y Hetzner subió precios el 2026-06-15; el "€4–6/mes" está desactualizado. Además, la página oficial mostró hoy los planes CX de EU-Central como "currently unavailable" `[V 2026-10-05]` — confirmar disponibilidad por ubicación al provisionar.

| | **Hetzner CX33** (recomendado) | Hetzner CX23 | Railway (Hobby) | Fly.io | Servidor existente |
|---|---|---|---|---|---|
| Recursos | 4 vCPU · 8 GB · 80 GB NVMe · 20 TB | 2 vCPU · 4 GB · 40 GB | Por uso | Por máquina | ¿? |
| Precio | **€8,49 + €0,50 IPv4 + €1,70 backups ≈ €10,69/mes + IVA** `[V 2026-10-05, costgoat.com actualizado 2026-09-05; la página de Hetzner no muestra precio]` | €5,49 + €0,50 (+ backups) `[V, ídem]` | US$5/mes con US$5 incluidos; ~US$20 por vCPU-mes, ~US$10 por GB RAM-mes, US$0,15/GB volumen `[V]` → **~US$40–50/mes** para ~3,5 GB residentes `[H]` | shared-cpu-1x 2 GB **US$13,39/mes**, volumen US$0,15/GB, Managed Postgres Basic **US$38/mes** `[V]` → **~US$35–65/mes** `[H]` | US$0 marginal `[H]` |
| ¿Cabe todo? | Sí: PG + Redis + 2 procesos Python + Remotion/Chromium con holgura `[H]` | **No con Remotion**: Chromium renderizando + Reflex + PG en 4 GB = OOM probable `[H]` | Sí | Sí | Depende |
| Custodia de credenciales (llave maestra en entorno controlado) | Propia | Propia | En infra de terceros | En infra de terceros | Propia si es de Attitude |
| WebSockets de Reflex | Sí (Caddy) | Sí | Sí | Sí | Sí |
| Trabajo inicial | Mayor (provisionar, Caddy, deploy.sh) — 1–2 días `[H]` | Ídem | Horas | Horas | Variable |

**Recomendación:** Hetzner CX33 x86 (no ARM: la imagen de Remotion/Chromium y los builds multi-arch añaden riesgo sin ahorro — CAX21 cuesta €10,49 `[V, ídem]`). Es el host ya nombrado en `CLAUDE.md` §Stack, mantiene el modelo de custodia de credenciales, y es ~4× más barato que Railway/Fly con este perfil de memoria. SonarQube **no** va en este host (ver D5).

### 5.9 Lo que exige del repo (trabajo para los agentes de implementación)

| Artefacto | Contenido |
|---|---|
| `Dockerfile` (raíz, imagen `qualify-app`) | Multi-stage: `uv sync --frozen --no-dev` (sin grupo `ml`) + **frontend de Reflex pre-compilado en el build** (no en el arranque); usuario no-root; `HEALTHCHECK` |
| `packages/render/Dockerfile` | Ya viene con el PR #65; añadir usuario no-root y `HEALTHCHECK` si faltan |
| `rxconfig.py` | `api_url` desde `REFLEX_API_URL`, `cors_allowed_origins` = el dominio, `db_url` desde entorno (hoy apunta a `reflex.db` en SQLite: confirmar si algo lo usa todavía o montar volumen `[H]`) |
| `deploy/staging/compose.yml`, `Caddyfile`, `deploy.sh`, `env.example` (sólo nombres) | §5.2–5.5 |
| `qualify_api` | `GET /api/health`; chequeos fail-closed de §5.4 |
| `justfile` | `deploy-staging sha=""` (dispara el workflow), `merge pr` (§2.3), `ci-local` (lo mismo que A1+A2) |
| `pyproject.toml` | `[tool.coverage]` (fuentes = los `src/` + `Qualify/`, omitir tests); ruff `S` y `C90` |
| `.github/dependabot.yml` | `uv` (raíz), `npm` (`packages/render`), `github-actions`, `docker`; semanal, agrupado |
| `.gitleaks.toml`, `.semgrepignore` | Allowlist con motivo |

## 6. Plan por fases

| Semana | Entregables | Criterio de hecho |
|---|---|---|
| **1 (6–10 oct) — CI robusto** | Disparadores y `concurrency` de §2.1 · jobs A1–A3, B1, B2 · coverage con comentario · Claude review (D1 del grafo) · `dependabot.yml` · `just merge` · regla en `CLAUDE.md` · todas las actions de terceros fijadas por SHA | Un PR nuevo muestra los checks con nombres estables, un comentario de coverage con % del diff, una revisión de Claude; un PR que sólo toca `docs/` corre ≤ 2 min; minutos por push de PR medidos ≤ 12 |
| **2 (13–17 oct) — Imágenes + staging** | Dockerfile de la app · C1 + E1 + E2 · host aprovisionado · Caddy + compose + `deploy.sh` · DNS · rotación de contraseñas de roles · `.env` del host · redirects de Meta/Supabase/Canva · backups | `https://qualify.attitudefactory.co` sirve login con TLS; **un callback OAuth de Meta completa contra una cuenta real**; simulacro de rollback a un SHA anterior hecho; simulacro de restore de `pg_dump` hecho; un merge rojo a `main` **no** despliega y abre issue |
| **3 (20–24 oct) — Quality gate + hardening** | Gate: gitleaks = falla · semgrep `ERROR` = falla · trivy CRITICAL con fix = no deploy · pip-audit/npm audit high = falla · coverage del diff ≥ 80 % = falla (total sólo informa) · escaneo semanal G · SSH forzado, `ufw`, `unattended-upgrades` · runbook de rotación de llaves · nota de cierre de ADR 27 R8a · decisión D5 | Un PR con un secreto, una CVE alta o un diff sin tests sale rojo; uso de minutos del mes ≤ 65 % proyectado; los ADR 35/36 de abajo pasan a firma |

### Borrador de filas para `docs/arquitectura.md` §6

| # | Decisión | Alternativa descartada | Razón |
|---|---|---|---|
| 35 | **[PROPUESTO 2026-10-05]** CI/CD a costo cero con CLIs open source dentro de GitHub Actions (ruff, Semgrep CE, Gitleaks CLI, pip-audit, npm audit, OSV-Scanner, Trivy CLI, pytest-cov, claude-code-action); **el gate duro está en el deploy, no en el merge**; actions de terceros fijadas por SHA | SonarQube Cloud / Codecov / CodeRabbit / GHAS | En privado Free todos cobran o no aplican (50k LoC, 1 usuario, sólo públicos, US$19–30/committer); el compromiso de `trivy-action` (marzo 2026) obliga a fijar por SHA |
| 36 | **[PROPUESTO 2026-10-05]** Staging/MVP en un VPS propio (Hetzner CX33) con Docker Compose + Caddy; imágenes en GHCR; deploy por SSH con llave forzada; secretos de la app sólo en el host; migraciones aditivas desde el primer deploy (cierra ADR 27 R8a) | Railway / Fly.io | ~4× más barato con este perfil de memoria, mantiene la custodia de la llave maestra en un host controlado; el costo es operar el servidor |

## 7. Decisiones del fundador

1. **D1 — Host.** Hetzner CX33 (~€10,69/mes + IVA, recomendado) · Railway (~US$40–50) · un servidor existente de Attitude (¿hay uno?).
2. **D2 — ¿`qualify.attitudefactory.co` es "staging" o la producción del MVP?** Con tokens reales de clientes, en la práctica es producción. Recomendado: un solo entorno ahora, operado como producción; un staging separado cuando haya cliente dos.
3. **D3 — ¿Pagar GitHub Team (US$4/usuario/mes)?** Da required checks, environment secrets y 3.000 min. Recomendado: **no por ahora**; reabrir si el uso supera 80 % dos meses o si entra un merge roto que el gate de deploy no hubiera parado.
4. **D4 — Token de la revisión de Claude.** `CLAUDE_CODE_OAUTH_TOKEN` de la suscripción Max (US$0 marginal, comparte cuota y límites con las sesiones del fundador) · API key con tope de gasto. Recomendado: OAuth Max, disparado sólo en opened/ready/`@claude`.
5. **D5 — SonarQube.** Recomendado: **no** (Community no comenta PRs, pide 4 GB y otro servidor; Cloud Free no alcanza a este repo). Reabrir si se quiere un panel histórico de deuda técnica: CX23 aparte (~€6/mes).
6. **D6 — Worker del calendario en staging.** Apagado por defecto · encendido sólo para tenants propios listados.
7. **D7 — Cierre de ADR 27 R8a** con el primer deploy: migraciones sólo aditivas y compatibles con la imagen anterior desde ese día.
8. **D8 — Backups:** confirmar bucket R2 dedicado, retención 14 d + 8 sem, y quién guarda la llave de cifrado de los dumps fuera del host.

## Fuentes verificadas hoy

GitHub: precios (`github.com/pricing`), minutos y sobrecosto de Actions, Packages/GHCR, environments en privado, Advanced Security (`github.com/security/plans`), Dependabot alerts en todos los planes. SonarSource: planes y Community Build (sólo rama principal, sin PR, 4 GB, PG 15–18). Codecov, CodeRabbit, Copilot code review: páginas de precios. `gitleaks/gitleaks` y `gitleaks/gitleaks-action`, `semgrep/semgrep`, `aquasecurity/trivy`, `google/osv-scanner`, `py-cov-action/python-coverage-comment-action`, `anthropics/claude-code-action` (README y `docs/setup.md`). Incidente de Trivy: Wiz y SafeDep (marzo 2026). Railway y Fly.io: páginas de precios. Hetzner: página de planes (sin precios visibles) + costgoat.com (actualizado 2026-09-05). Reflex: guía de self-hosting.
