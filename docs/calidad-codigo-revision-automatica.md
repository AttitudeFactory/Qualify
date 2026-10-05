# Calidad de código: revisión automática con Claude, anotaciones de ruff y SonarQube

`[IMPLEMENTADO 2026-10-05]` — rama `ci/auto-review-sonarqube`. Todo lo descrito aquí es
costo cero u open source, o usa la suscripción Claude Max que el fundador ya paga. Las
afirmaciones de precio y capacidad llevan `[V fecha]` con el enlace donde se verificaron;
lo no verificado se marca como tal.

**Restricción de partida:** el repo es **privado** y la organización está en **GitHub
Free** — sin *branch protection*, sin *Advanced Security*, y 2 000 minutos de Actions al
mes para repos privados `[V 2026-10-05]`
([tabla de minutos](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions)).
Nada de lo que sigue puede **bloquear** un merge (no hay branch protection que lo
imponga); todo es señal para el humano que mergea.

## 1. Las piezas

| Pieza | Archivo | Cuándo corre | Qué produce | Costo |
|---|---|---|---|---|
| Anotaciones de `ruff` en el diff | `.github/workflows/review.yml`, job `ruff` | PR no-draft a `main`, no Dependabot | Comentarios de revisión en las líneas **añadidas** con cada hallazgo de `ruff check`, y sugerencias de un clic con `ruff format --diff` | 0 (solo `GITHUB_TOKEN`) |
| Revisión automática con Claude | `review.yml`, job `claude-review` | PR no-draft a `main`, no Dependabot; cada push cancela la revisión anterior | Comentarios inline (archivo:línea) con hallazgos concretos + un resumen de ≤ 10 líneas; nunca aprueba/rechaza | Suscripción Max (token OAuth) o API por tokens |
| `@claude` bajo demanda | `review.yml`, job `claude-mention` | Comentario en issue/PR que contenga `@claude` | Responde en un comentario *sticky*; puede editar archivos y hacer commits en una rama | Ídem |
| SonarQube Community Build | `.github/workflows/sonar.yml` + `sonar-project.properties` + `infra/sonarqube/` | Push a `main` y `workflow_dispatch` (solo sobre `main`) | Dashboard con bugs, vulnerabilidades, hotspots, duplicación, cobertura y los hallazgos de ruff importados | 0 (autoalojado; ~4 GB RAM en el VPS) |

Ninguna pieza duplica a `ci.yml`: `ci.yml` sigue siendo la única que **falla** por lint,
formato, migraciones o tests. Aquí todo es `fail-level=none` / `continue-on-error`.

### 1.1 Revisión con Claude (`anthropics/claude-code-action@v1`)

Qué soporta hoy la acción, verificado contra su README, `docs/usage.md`,
`docs/solutions.md` y `action.yml` en `main`, y contra la documentación oficial de Claude
Code `[V 2026-10-05]` ([docs](https://code.claude.com/docs/en/github-actions),
[repo](https://github.com/anthropics/claude-code-action)):

- **Dos modos detectados por configuración.** Con `prompt` corre en *automation mode*
  (revisión automática en `pull_request`); sin `prompt` corre en *interactive mode* y
  espera la frase `@claude` (configurable con `trigger_phrase`) en comentarios de
  issue/PR, reviews, o título/cuerpo de una issue nueva. El `mode` explícito desapareció
  en v1.
- **Autenticación.** `anthropic_api_key` (API, pago por token) **o**
  `claude_code_oauth_token`: «OAuth token that authenticates with your Claude
  subscription, available on Pro, Max, Team, and Enterprise plans. Generate one by
  running `claude setup-token` locally». Con el token OAuth «runs use your Claude
  subscription instead of API billing». El token queda atado a la suscripción de quien
  lo generó, por eso Anthropic recomienda API key solo cuando el secreto se comparte
  entre repos de una organización. También existe *workload identity federation*
  (OIDC → Claude Console) para no guardar secretos; no aplica a una suscripción.
- **GitHub.** Si no se pasa `github_token`, la acción se autentica como la **Claude
  GitHub App** (`https://github.com/apps/claude`, hay que instalarla en el repo; requiere
  `id-token: write`). Si se pasa `github_token: ${{ secrets.GITHUB_TOKEN }}` no hace
  falta la app, pero los commits que haga Claude **no disparan** otros workflows
  (limitación documentada de GitHub). Por eso `claude-review` (solo comenta) usa
  `GITHUB_TOKEN` y `claude-mention` (puede hacer commits) usa la app.
- **Quién puede disparar.** El actor debe tener permiso de escritura en el repo (se
  relaja con `allowed_non_write_users`) y no ser un bot (`allowed_bots`, vacío por
  defecto — evita bucles claude→claude). Dependabot además se filtra en el `if`.
- **Acotar herramientas y costo.** `claude_args` acepta cualquier flag del CLI:
  `--allowedTools` (lista blanca de herramientas; el servidor MCP de comentarios
  inline solo arranca si se nombra `mcp__github_inline_comment__create_inline_comment`
  ahí), `--max-turns`, `--model`. La revisión se acota al diff **por prompt** (`gh pr
  diff` + Read/Grep para contexto) y por `--max-turns 40`; el `concurrency` con
  `cancel-in-progress` evita pagar dos revisiones del mismo PR cuando llegan pushes
  seguidos. Inline comments con `confirmed: true` se publican directo; sin él pasan por
  un clasificador que filtra comentarios de prueba.
- **Salida.** Solo comentarios: hallazgo = comentario inline anclado en archivo:línea,
  en español; un único resumen con `gh pr comment`; prohibido aprobar/rechazar,
  comentar estilo que ya cubre ruff, o tocar archivos.
- **Borradores y bots.** `if: github.event.pull_request.draft == false &&
  github.actor != 'dependabot[bot]'`; eventos `opened, synchronize, reopened,
  ready_for_review` sobre `branches: [main]`.
- **Permisos mínimos.** `claude-review`: `contents: read`, `pull-requests: write`,
  `issues: write`, `id-token: write`. `claude-mention`: añade `contents: write`
  (commits) y `actions: read` (leer resultados de CI).

El prompt de revisión vive en el YAML y revisa, en este orden: corrección; seguridad
(secretos, SQL parametrizado, `Engine`/`Session` solo a través de las puertas de
`qualify_shared.db.session`); **RLS** (toda tabla con `tenant_id` en
`migrations/postgres/` necesita `ENABLE` + `FORCE ROW LEVEL SECURITY` y una política
`tenant_isolation` con `NULLIF(current_setting('app.tenant_id', true), '')::uuid` — el
`NULLIF` no se «simplifica», regla R7 de `arquitectura.md` §6); convenciones del repo
(ruff E/F/I/UP a 100 columnas, type hints, Conventional Commits en inglés, docs en
español / código en inglés, `uv`, migraciones reversibles); y «read the filesystem, not
the docs» (verificar en disco lo que el PR afirma).

### 1.2 `ruff` → reviewdog

`ruff check --output-format=rdjson` escribe directamente el *Reviewdog Diagnostic
Format* (verificado en local con ruff 0.15.22: emite `diagnostics[]` con `code`,
`location.range` y `suggestions`), así que no hace falta conversor. `reviewdog
-f=rdjson -reporter=github-pr-review -filter-mode=added -fail-level=none` publica cada
hallazgo como comentario de revisión **solo en líneas añadidas** y nunca falla el job.

Sobre el token: la sección *GitHub Actions* del README de reviewdog muestra
`REVIEWDOG_GITHUB_API_TOKEN: ${{ secrets.GITHUB_TOKEN }}` con
`-reporter=github-pr-review` `[V 2026-10-05]`
([README](https://github.com/reviewdog/reviewdog#github-actions)); la única excepción
documentada son PRs desde *forks* (el `GITHUB_TOKEN` no tiene escritura y reviewdog
degrada a anotaciones de log), que en un repo privado no aplica. El job necesita
`pull-requests: write`. Instalación con `reviewdog/action-setup@v1` (última v1.5.0
`[V 2026-10-05]`). `ruff` se instala desde el lockfile con `uv sync --only-group dev`
— la misma versión que impone `ci.yml`.

### 1.3 SonarQube Community Build (autoalojado)

- **SonarQube Cloud no sirve a costo cero para este repo** `[V 2026-10-05]`
  ([precios](https://www.sonarsource.com/plans-and-pricing/)): es gratis con todas las
  funciones solo para **repos públicos** con licencia OSI; para privados existe un *Free
  tier* limitado a **50 k LOC** y el plan Team cuesta **34 USD/mes hasta 100 k LOC**.
  Qualify ya mide ~80 k líneas de Python fuera de tests (≈ 38 k en `packages/*/src` +
  ≈ 42 k en `Qualify/`, contadas el 2026-10-05), por encima del tier gratuito.
- **Community Build** es gratuita, open source y autoalojada (antes *Community
  Edition*; versión actual 26.9 `[V 2026-10-05]`
  [downloads](https://www.sonarsource.com/products/sonarqube/downloads/)). Lo que **no**
  tiene: análisis de ramas, análisis de PR y decoración de PR — «all three are
  unavailable in Community Build… these analyses start with Developer Edition»
  `[V 2026-10-05]`
  ([docs](https://docs.sonarsource.com/sonarqube-server/latest/analyzing-source-code/pull-request-analysis/introduction.md)).
  Consecuencia: **un dashboard de `main`**, no comentarios en PRs; la señal por PR la
  dan Claude y reviewdog.
- **Acción:** `SonarSource/sonarqube-scan-action@v8` (última v8.3.0 `[V 2026-10-05]`;
  es la misma acción para Server/Community y Cloud, cambia solo por `SONAR_HOST_URL`).
  Lee `sonar-project.properties`; recomienda `fetch-depth: 0`.
- **Cobertura:** se genera **en el mismo job** (`uv run --no-sync --with pytest-cov
  pytest -m "not integration and not db and not slow" --cov=… --cov-report=xml`) en vez
  de descargar el artefacto de `ci.yml`. Motivo: los tests `db` necesitan el Postgres de
  compose y el nombre del artefacto lo controla otro workflow; regenerar la suite offline
  cuesta 1-2 minutos y no acopla los dos workflows. Si `ci.yml` publica `coverage.xml`
  como artefacto estable, se puede sustituir por `dawidd6/action-download-artifact@v27`
  (`[V 2026-10-05]` última versión) filtrando por `commit: ${{ github.sha }}`.
- **ruff en Sonar:** `sonar.python.ruff.reportPaths=ruff-report.json`, con el JSON
  nativo de `ruff check --output-format=json`. La documentación de Sonar no dice el
  formato; se verificó en el código del analizador (`RuffJsonReportReader` lee `code`,
  `filename`, `location.row/column`, `end_location`) `[V 2026-10-05]`
  ([fuente](https://github.com/SonarSource/sonar-python/blob/master/python-commons/src/main/java/org/sonar/plugins/python/ruff/RuffJsonReportReader.java)).
- **Sin quality gate bloqueante** en v1 (`sonar.qualitygate.wait=false`). El gate
  recomendado para Python (cobertura nueva ≥ 60 %, 0 bugs/vulnerabilidades nuevas,
  duplicación nueva < 3 %) y cómo crearlo están en `infra/sonarqube/README.md` §3.

## 2. Secretos que debe crear el fundador

Todos en **GitHub → repo → Settings → Secrets and variables → Actions → New repository
secret**. Ninguno es obligatorio para que CI siga verde.

### 2.1 `CLAUDE_CODE_OAUTH_TOKEN` (recomendado: usa la suscripción Max)

1. En una terminal local, con Claude Code ya logueado con la cuenta Max:
   `claude setup-token`. Abre el navegador, autoriza, y devuelve un token de larga
   duración (documentado como *long-lived token* en
   [autenticación](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token)).
2. Guárdalo como secreto `CLAUDE_CODE_OAUTH_TOKEN`. No lo pegues en ningún archivo.
3. Instala la **Claude GitHub App** en el repo (`https://github.com/apps/claude`) — la
   necesita `claude-mention` para que sus commits disparen `ci.yml`. `claude-review`
   funciona sin ella.
4. Alternativa guiada: `claude` en el repo → `/install-github-app` hace los tres pasos y
   abre un PR con su propio `claude.yml`; en ese caso **no mergees ese `claude.yml`**
   (duplicaría `review.yml`), solo aprovecha el secreto y la app.

Atención: el token pertenece a la cuenta que lo generó; si esa cuenta cambia de plan o
revoca sesiones, los jobs de Claude pasan a saltarse con aviso (no fallan).

### 2.2 `ANTHROPIC_API_KEY` (alternativa, pago por tokens)

Solo si no se quiere usar la suscripción. Clave de la Claude Console; el YAML la usa
únicamente cuando `CLAUDE_CODE_OAUTH_TOKEN` no existe. Costo real por revisión: depende
del tamaño del diff; `--max-turns 40` y el `concurrency` acotan el peor caso.

### 2.3 `SONAR_HOST_URL` y `SONAR_TOKEN`

Pasos completos en `infra/sonarqube/README.md` §1-2: levantar el compose en el VPS de
staging detrás de Caddy/Traefik con TLS, cambiar la contraseña `admin/admin` en el primer
login, crear el proyecto con key `qualify`, generar un *Project analysis token* y guardar
`SONAR_HOST_URL` (la URL pública `https://…`) y `SONAR_TOKEN`.

## 3. Qué pasa cuando faltan los secretos (nada se rompe)

- `review.yml` / jobs de Claude: la presencia del secreto se evalúa en `env`
  (`HAS_CLAUDE_OAUTH: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN != '' }}`) porque el contexto
  `secrets` no se puede usar en `if:`. Sin ninguno de los dos, el único paso que corre
  imprime un `::notice::` y una línea en el *Step Summary*; el job termina **verde**.
  Con secreto presente pero inválido (token caducado, cuota agotada, Anthropic caído), el
  paso de Claude tiene `continue-on-error: true`: el job también termina verde y el
  fallo se ve en el log.
- `review.yml` / job `ruff`: no depende de ningún secreto. Con cero hallazgos no publica
  nada (reviewdog lo informa en el log).
- `sonar.yml`: un job `preflight` exporta `configured=true|false`; `analyze` tiene
  `if: needs.preflight.outputs.configured == 'true' && github.ref == 'refs/heads/main'`.
  Sin secretos: `preflight` verde con aviso, `analyze` **skipped**, workflow verde.

Verificado en ejecuciones reales de la rama (ver el PR): sin ningún secreto configurado,
`review.yml` y `sonar.yml` terminan en verde.

## 4. Alternativas descartadas (precio en repos privados)

| Herramienta | Qué daría | Por qué no | Precio verificado |
|---|---|---|---|
| **CodeRabbit** | Revisión IA de PRs, muy pulida | Solo gratis para repos **públicos**; para privados no hay tier gratuito | Essentials **24 USD/dev/mes** (anual), Team 48, Advanced 72 `[V 2026-10-05]` ([pricing](https://www.coderabbit.ai/pricing)) |
| **GitHub Copilot code review** | Revisión automática nativa en PRs | Requiere licencia Copilot de pago por usuario; Copilot Free solo tiene «review selection» en VS Code; además consume *AI credits* por revisión (0,05-5 USD estimados) | Pro **10 USD/mes**, Business **19 USD/usuario/mes**, Pro+ 39 `[V 2026-10-05]` ([planes](https://docs.github.com/en/copilot/get-started/plans), [code review](https://docs.github.com/en/copilot/concepts/agents/code-review)) |
| **SonarQube Cloud (SonarCloud)** | Lo mismo que Community **más** análisis de ramas y decoración de PR, sin servidor | Gratis solo en repos públicos OSI; el tier gratuito privado se queda en 50 k LOC (Qualify ≈ 80 k) | Team **34 USD/mes hasta 100 k LOC** `[V 2026-10-05]` ([pricing](https://www.sonarsource.com/plans-and-pricing/)) |
| **CodeQL (code scanning)** | SAST profundo con queries de GitHub | Gratis solo en repos públicos; en privados exige **GitHub Code Security**, que solo se compra en planes Team/Enterprise — la org está en Free | **30 USD/committer activo/mes** (Code Security), 19 USD Secret Protection `[V 2026-10-05]` ([precios](https://github.com/enterprise/advanced-security), [requisito de plan](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security)) |
| **Codecov** | Cobertura por PR con comentarios y gráficos | Plan Developer gratuito limitado a **1 usuario** en privados y 250 subidas/mes; Sonar ya muestra cobertura y la señal por PR la puede dar un comentario propio más adelante | Team **5 USD/usuario/mes** (máx. 10), Pro 12 `[V 2026-10-05]` ([pricing](https://about.codecov.io/pricing/)) |

Lo que sí es gratis y queda abierto para el otro track de CI (`security.yml`,
Dependabot): el escaneo de secretos y de dependencias con herramientas open source
(gitleaks, pip-audit, Trivy) — fuera del alcance de este documento.

## 5. Mantenimiento

- Pines: `anthropics/claude-code-action@v1` (tag flotante oficial; v1.0.241 al
  escribir), `reviewdog/action-setup@v1`, `SonarSource/sonarqube-scan-action@v8`,
  `sonarqube:26.9.0.129388-community` (fijo a propósito; subirlo es un acto
  deliberado, ver `infra/sonarqube/README.md` §5). Dependabot (track del otro agente)
  puede mantener los tags de acciones.
- Si el prompt de revisión empieza a generar ruido, ajustar el prompt en `review.yml`,
  no los permisos: la lista `--allowedTools` ya es la mínima para leer el diff y
  comentar.
- Para hacer el gate de Sonar bloqueante: `sonar.qualitygate.wait=true` en
  `sonar-project.properties`. Sin branch protection sigue sin impedir el merge; solo
  pinta el check en rojo.
