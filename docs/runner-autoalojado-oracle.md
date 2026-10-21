# Runner auto-hospedado de GitHub Actions en un VPS gratuito — investigación y prompt de trabajo

**Ticket:** [m-24828956](https://project.larksuite.com/5h2wsx/issue/detail/24828956) · **Estado:** `[INVESTIGACIÓN 2026-10-21]` — nada de esto está construido; este documento fija la decisión de proveedor y deja listo el prompt con el que se ejecutan las tres fases.
**Convención:** `[V 2026-10-21]` = verificado hoy contra una fuente pública enlazada; `[H]` = hipótesis o estimación propia; `[M]` = medido en este repo. Los límites de las capas gratuitas **caducan** (Oracle recortó el suyo a la mitad en junio de 2026 sin anuncio).

---

## 1. Por qué ahora

1. Desde **2026-11** la organización vuelve a GitHub Free: **2.000 min/mes** de Actions en repo privado, cada job facturado redondeando al minuto entero. Medido 2026-10-01..15: **4.294 min facturados (~8.600/mes) con 94 merges** (`CLAUDE.md` § CI). `[M]`
2. Los recortes ya hechos en `ci.yml` (un solo job `test`, sin CI en `push` a `main`, Docker/Node sólo por `paths:`, revisión de Claude bajo demanda, deploy diario) bajan el consumo, pero no lo sacan del riesgo: **si la cuota se agota sin método de pago, el uso se bloquea** y `just merge` deja de dejar pasar nada (regla del fundador: nada entra a `main` con CI rojo). `[V]` en [`plan-cicd-staging.md`](plan-cicd-staging.md) §5.
3. Los **runners auto-hospedados no consumen minutos del plan**: GitHub los documenta como gratuitos. `[V 2026-10-21]` — [docs de facturación](https://docs.github.com/en/actions/reference/usage-limits-billing-and-administration). ⚠ GitHub anunció en 2025-12 un cargo de **US$0,002/min** para self-hosted en repos privados desde 2026-03 y lo **pospuso sin fecha** 48 h después; no lo ha retirado. `[V 2026-10-21]` — [devclass](https://devclass.com/2025/12/17/github-to-charge-for-self-hosted-runners-from-march-2026/), [The Register](https://www.theregister.com/2025/12/17/github_charge_dev_own_hardware/), [estado a 2026-10](https://tenki.cloud/blog/github-actions-runner-pricing-2026). Si vuelve, a nuestro volumen (~8.600 min) serían ~US$17/mes: sigue siendo más barato que comprar minutos (US$0,006/min = US$52), pero deja de ser cero.

## 2. Opciones de VPS gratuito (lo que hay de verdad en octubre de 2026)

| Proveedor | Qué da gratis **para siempre** | Arquitectura | Sirve para nuestro `ci/test`? | Trampas |
|---|---|---|---|---|
| **Oracle Cloud Always Free** | **Ampere A1: 1.500 OCPU-h + 9.000 GB-h al mes = 2 OCPU / 12 GB** (desde **2026-06-15**; antes 4 / 24). Además 2 × `VM.Standard.E2.1.Micro` (1/8 OCPU, 1 GB, x86), 200 GB de block storage en total, 10 TB de salida/mes. `[V 2026-10-21]` | **arm64** (A1) · x86 (micro) | **Sí** — 2 núcleos y 12 GB sobran para `uv sync` + pytest + Postgres + Redis + un `docker build`. `[H]` | (a) **«Out of host capacity»** al crear A1 en regiones saturadas (EE. UU. sobre todo); Frankfurt/Singapur suelen dar en minutos; hay que reintentar. (b) **Recupera instancias ociosas**: p95 de CPU, red **y** memoria < 20 % durante 7 días → la para. Un runner que sólo corre con PRs es un candidato: hay que mantenerlo vivo o pasar la cuenta a **Pay As You Go** (sin cargo mientras se esté dentro de los límites; quita la recuperación y mejora el acceso a capacidad). (c) Instancias por encima del nuevo límite fueron **terminadas** a partir de 2026-08-18. (d) La cuenta exige tarjeta real; muchas prepagadas fallan. |
| **Google Cloud Free Tier** | 1 × `e2-micro` (0,25 vCPU compartida, 1 GB), 30 GB disco, 1 GB salida/mes, sólo en `us-west1`/`us-central1`/`us-east1`. `[V 2026-10-21]` | x86 | **No** — 1 GB de RAM no aguanta `uv sync` del workspace + torch CPU del grupo `sentiment` ni los servicios de Postgres/Redis. `[H]` | La **IP externa cuesta US$0,005/h (~US$3,6/mes)** aunque la VM sea gratis; un runner sólo sale, así que puede ir sin IP pública vía Cloud NAT… que también cuesta. |
| **AWS** | Ya **no hay 12 meses gratis** para cuentas creadas después de 2025-07-15: créditos de hasta US$200 por ~6 meses. `[V 2026-10-21]` | x86/arm64 | Temporal | Se acaba. |
| **Azure** | 750 h/mes de `B1s`, `B2pts v2` (arm) y `B2ats v2` durante **12 meses** + US$200 por 30 días. `[V 2026-10-21]` | x86/arm64 | Temporal (12 meses) | Se acaba; después B2pts v2 ≈ US$8/mes. |
| Hetzner (de pago, referencia) | CX23 2 vCPU / 4 GB **€3,79/mes**; CAX11 arm64 2 vCPU / 4 GB ~€3,79. | x86 / arm64 | Sí | Es el plan B si Oracle falla: ~€4/mes es menos que 700 minutos comprados a GitHub. Ya operamos ahí (`despliegue-hetzner.md`). |

Fuentes del recorte de Oracle: [InfoQ 2026-07](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [heise](https://www.heise.de/en/news/Oracle-halves-free-cloud-resources-11334516.html), [linuxiac](https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/), [Oracle Community](https://community.oracle.com/customerconnect/discussion/964620/do-the-new-reduced-ampere-a1-free-tier-limits-apply-to-existing-users), [doc oficial Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) (la regla del 20 %/7 días está ahí; la página indexada aún muestra en algunos cachés las cifras viejas). Comparativas: [cloud-free-tier-2026](https://github.com/emmanuelakwasi/cloud-free-tier-2026), [klymentiev](https://klymentiev.com/blog/free-vps), [mrplanb](https://www.mrplanb.com/datacenter/free-vps-tiers), [samnet](https://www.samnet.dev/learn/guides/free-vps-guide/).

### Decisión recomendada

**Oracle Always Free, shape `VM.Standard.A1.Flex` 2 OCPU / 12 GB, Ubuntu 24.04 aarch64, boot de 50–100 GB.** Es la única capa gratuita permanente con potencia útil, y su arquitectura **coincide con la de producción**: el servidor de Hetzner es arm64 (`deploy.yml` construye las imágenes en `ubuntu-24.04-arm` precisamente por eso), así que el runner puede además construir las imágenes de `deploy` de forma nativa. Lo que **no** debe ir a este runner: `render.yml` (la imagen de Remotion/Chromium es x86, `despliegue-hetzner.md` §2) y el job `deploy` (hace ssh al servidor con una llave que es secret de Actions, no del runner).

Dos salvaguardas no negociables, porque la capa gratuita de Oracle **es un préstamo** (ya lo recortaron una vez):

1. **Vuelta atrás sin commit.** `runs-on: ${{ vars.QUALIFY_CI_RUNNER || 'ubuntu-latest' }}`: si Oracle recupera o termina la VM, se vacía la variable del repo y el siguiente run vuelve a GitHub-hosted.
2. **Nada que no esté en el repo.** La VM se levanta entera con `deploy/bootstrap-runner.sh`; perderla cuesta 15 minutos, no una tarde.

## 3. Qué cambia en nuestros workflows (lo que el prompt genérico no sabe)

| Punto | Hoy | En el runner |
|---|---|---|
| `runs-on` | `ubuntu-latest` fijo | `${{ vars.QUALIFY_CI_RUNNER \|\| 'ubuntu-latest' }}`; la variable vale `["self-hosted","linux","ARM64","oci-free"]` (JSON en `vars` funciona en `runs-on`). |
| gitleaks (`ci.yml` y `security.yml`) | descarga `gitleaks_<v>_linux_x64.tar.gz` fija | resolver por `uname -m` → `linux_arm64`; el checksum se verifica igual. |
| `services:` postgres/redis | Docker lo trae el runner de GitHub | **Docker Engine en la VM**, el usuario del runner en el grupo `docker`; `postgres:16` y `redis:7` son multi-arch. Probar que `services:` arranca antes de migrar nada más. |
| `gh api` (comentario de cobertura) | `gh` preinstalado | instalar `gh` CLI (paquete oficial, hay build arm64). `GH_TOKEN` sigue siendo `${{ github.token }}`. |
| `setup-uv` + `actions/cache` | caché remota de GitHub (red) | `enable-cache: false` y `UV_CACHE_DIR=/var/cache/uv` persistente en disco local; mucho más rápido y no gasta red. |
| `docker/build-push-action` cache `type=gha` | caché de GitHub | `type=local,dest=/var/cache/buildx` o simplemente la caché del daemon local. |
| Limpieza | runner efímero, siempre limpio | cron diario: `docker system prune -af --filter until=72h`, borrar `_work/*/` de runs > 7 días, podar `/var/cache/uv` si pasa de 8 GB. Boot de 50 GB; medir el disco la primera semana. |
| Seguridad | aislado por GitHub | repo **privado** (sin PRs de forks); runner registrado a nivel de **repositorio**, no de org; usuario `runner` sin sudo; sin `.env.prod` ni llaves de producción en la VM; SSH sólo desde la IP del fundador; ningún puerto de entrada hace falta (el runner sólo abre salida 443 a `github.com`, `api.github.com`, `*.actions.githubusercontent.com`, `codeload.github.com`, `pkg.actions.githubusercontent.com`, `ghcr.io`). |

## 4. El prompt (actualizado con el contexto real de Qualify)

Cópialo tal cual en una sesión nueva. Los corchetes del original ya están rellenados; lo que sigue entre `⟨⟩` es lo único que falta decidir al momento de ejecutar.

```text
Actúa como un Ingeniero DevOps y Cloud Senior experto en GitHub Actions, Oracle Cloud Infrastructure
(OCI) y automatización de infraestructura.

Quiero montar un Self-Hosted Runner de GitHub Actions en una máquina virtual de la capa Always Free
de Oracle Cloud, y migrar a él los workflows de mi repositorio privado para no consumir los 2.000
minutos/mes del plan GitHub Free (vigente desde 2026-11) y que el costo sea cero.

Contexto del proyecto (repositorio AttitudeFactory/Qualify, privado, organización GitHub Free):
- Monorepo Python 3.12 gestionado con `uv` (workspace con varios paquetes; `uv sync --locked`).
  Herramientas que corren en CI: `ruff`, `pytest` con `--cov`, `alembic` (migraciones up → down → up
  contra Postgres), `gitleaks` (binario descargado por release), `gh api` (comenta cobertura en el PR).
- El job principal (`.github/workflows/ci.yml`, job `test`) usa `services:` de GitHub Actions:
  `postgres:16` y `redis:7`. Necesita Docker en el host del runner.
- Hay además: `security.yml` (semanal: semgrep, bandit, pip-audit, trivy, gitleaks sobre toda la
  historia), `review.yml` (revisión con Claude Code bajo demanda), `images.yml` (docker build x86 de
  `deploy/Dockerfile`, sólo si cambian sus entradas) y `deploy.yml` (construye imágenes arm64 en
  `ubuntu-24.04-arm` y hace ssh al servidor de producción, que es arm64).
- Un servicio Node 22 (`packages/render/`, Remotion + Chromium) con su propio workflow; su imagen es
  x86 y NO debe migrar al runner arm64.
- Runner actual en GitHub-hosted: `ubuntu-latest` (x64) y `ubuntu-24.04-arm` (arm64).
- La VM destino es Ampere A1 (arm64), 2 OCPU / 12 GB, Ubuntu 24.04 aarch64 — el límite Always Free
  vigente desde 2026-06-15. Todo lo que instales tiene que ser para aarch64.
- Restricciones que debes respetar: (1) la vuelta atrás a GitHub-hosted tiene que ser una variable de
  repositorio (`vars.QUALIFY_CI_RUNNER`), no un cambio de código; (2) la VM se reconstruye entera con
  un solo script idempotente guardado en el repo (`deploy/bootstrap-runner.sh`); (3) el runner se
  registra a nivel de repositorio con las etiquetas `self-hosted, linux, ARM64, oci-free`, corre como
  servicio systemd bajo un usuario sin sudo, y en la VM no vive ningún secreto de producción;
  (4) Oracle recupera instancias con p95 < 20 % de CPU/red/memoria durante 7 días — propón cómo
  evitarlo (keepalive legítimo o paso a Pay As You Go dentro de los límites gratuitos) y qué hacer si
  la creación falla con «Out of host capacity».

Ayúdame paso a paso y espera mi respuesta entre fases:

Fase 1 — Infraestructura en OCI con `oci` CLI
- Comandos exactos para: compartimento, VCN con subred pública y gateway de internet, security list
  con SOLO salida (0.0.0.0/0 tcp/443 y 80) más ssh tcp/22 restringido a ⟨mi IP⟩, y la instancia
  `VM.Standard.A1.Flex` con 2 OCPU / 12 GB, imagen Ubuntu 24.04 aarch64, boot volume de 50 GB y mi
  llave ssh. Explícame cómo averiguar el OCID de la imagen y del availability domain y cómo reintentar
  si no hay capacidad. Indícame qué NO hace falta abrir (el runner sólo abre conexiones salientes).

Fase 2 — Script `deploy/bootstrap-runner.sh`
- Un solo script Bash idempotente, ejecutado por ssh como root, que: actualiza el sistema; instala
  Docker Engine + buildx + compose plugin, `git`, `curl`, `jq`, `ffmpeg`, `gh` CLI y `uv` (aarch64);
  crea el usuario `runner` en el grupo `docker`; descarga y verifica `actions-runner-linux-arm64`
  (última versión), lo configura con un token de registro que paso por variable de entorno (nunca en
  el script), con las etiquetas de arriba, y lo instala como servicio systemd que arranca al boot;
  crea `/var/cache/uv` persistente; instala un cron diario de limpieza (`docker system prune -af
  --filter until=72h`, `_work` de runs viejos, caché de uv > 8 GB) y configura un swapfile de 2 GB.
  Que el script se pueda volver a ejecutar sin romper nada.

Fase 3 — Workflows
- Cómo queda `ci.yml` con `runs-on: ${{ vars.QUALIFY_CI_RUNNER || 'ubuntu-latest' }}`, el paso de
  gitleaks resolviendo la arquitectura con `uname -m` (`linux_x64` / `linux_arm64`), `setup-uv` sin
  caché remota y `UV_CACHE_DIR` local, y los `services:` de Postgres/Redis funcionando en el runner.
  Luego lo mismo para `security.yml`. Dime qué cambiar en `deploy.yml` para que el job `images`
  (arm64) pueda construir en el runner con caché local de buildx, dejando `deploy` (ssh) y
  `render.yml` en GitHub-hosted. Incluye cómo verificar que un run consumió 0 minutos facturados.

Empecemos con la Fase 1. Antes de darme comandos, dime qué información necesitas de mi lado
(región home de mi tenancy, si ya tengo `oci` CLI configurado, mi IP pública para el ssh, si la
cuenta es Free o Pay As You Go).
```

## 5. Lo que falta decidir (el fundador)

| # | Decisión | Recomendación |
|---|---|---|
| D1 | Cuenta OCI Free pura o pasar a **Pay As You Go** dentro de los límites gratuitos | PAYG: quita la recuperación por inactividad y el «out of capacity» pega menos; el riesgo es un cargo si alguien sale de los límites — poner un budget alert de US$1. |
| D2 | Región home | Una con capacidad A1 (Frankfurt o São Paulo si existe en la cuenta); se fija al crear la cuenta y **no se puede cambiar**. |
| D3 | Qué migra en la primera tanda | Sólo `ci/test` una semana, medir disco y duración; después `security.yml` y `deploy/images`. |
| D4 | Si GitHub reactiva el cargo de US$0,002/min | Seguir en el runner (~US$17/mes a nuestro volumen) o volver a `ubuntu-latest` con la variable; decidir cuando pase, no antes. |
