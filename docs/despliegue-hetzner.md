# Despliegue de Qualify en Hetzner — `qualify.attitudefactory.co`

**Estado:** `[LISTO PARA EJECUTAR 2026-10-05]` — el repo ya es desplegable; lo que falta lo hace el fundador (crear el servidor, el registro DNS, el `.env.prod` y los ajustes de Meta). Cierra la bifurcación de host de [`prioridad-despliegue-subdominio.md`](prioridad-despliegue-subdominio.md) §4: **Hetzner**.
**Para qué:** que Meta App Review tenga una URL pública estable donde iniciar sesión, y que el callback OAuth de Meta tenga un redirect URI fijo (`https://qualify.attitudefactory.co/api/connections/callback`) en vez del túnel `cloudflared` efímero.
**Piezas en el repo:** `deploy/Dockerfile`, `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `deploy/.env.prod.example`, `deploy/deploy.sh`, `deploy/bootstrap-server.sh`, `deploy/backup-db.sh`, `deploy/bootstrap_db_roles.py`, y las recetas `just deploy*`.

---

## 1. Qué corre en el servidor

Un solo servidor, un solo `docker compose`, un solo origen público. Caddy es lo único expuesto a internet (80/443) y reparte por ruta:

```
                 internet ──► :80/:443  caddy  (TLS automático Let's Encrypt + frontend estático)
                                          │
        /api/*, /public/media/*  ─────────┼──► api      FastAPI  (uvicorn, qualify_api.http.app:create_app)
        /_event, /_upload, /ping,         │
        /_health, /avatar/*, /r2media/* ──┼──► reflex   backend de Reflex (websocket + rutas propias)
        todo lo demás  ───────────────────┘    /srv     export estático del frontend de Reflex

  red interna (sin puertos publicados):  postgres (pgvector/pgvector:pg16)  ·  redis 7
  paso explícito antes del `up`:         migrate  (`run --rm`; alembic upgrade head + contraseñas de los roles)
  opcionales (perfil, apagados):         calendar-worker (PUBLICA DE VERDAD) · render (Remotion)
```

| Ruta | Destino | Qué es |
|---|---|---|
| `/api/*` | `api:8000` | FastAPI. Incluye el callback OAuth de Meta `/api/connections/callback` |
| `/public/media/*` | `api:8000` | Ruta sin autenticación desde la que **Meta descarga** las imágenes que se publican (QUA-68) |
| `/_event` | `reflex:8000` | WebSocket de Reflex (sincronización de estado) |
| `/_upload`, `/_upload/*` | `reflex:8000` | Subidas (POST) y archivos subidos (GET) |
| `/ping`, `/_health`, `/_all_routes` | `reflex:8000` | Salud e introspección de Reflex |
| `/avatar/*` | `reflex:8000` | Proxy de avatares de creadores (`Qualify/avatar_proxy.py`, montado con `api_transformer`) |
| `/r2media/*` | `reflex:8000` | Medios de R2 para borradores (`Qualify/r2_media.py`, mismo `api_transformer`) |
| todo lo demás | `/srv` en Caddy | Frontend estático (`reflex export --frontend-only`); rutas dinámicas como `/drafts/[id]` las resuelve el cliente desde `404.html` |

No hay colisiones: las rutas que monta el `api_transformer` de Reflex (`/avatar`, `/r2media`) no comparten prefijo con FastAPI (`/api`, `/public/media`), y ninguna página de Reflex usa esos prefijos.

**Por qué dos imágenes y no tres.** `qualify-app` (Python) sirve a la vez `api`, `reflex`, `migrate` y `calendar-worker`, cambiando sólo el comando: el proceso de Reflex ya importa `qualify_api` en proceso (servicios de conexiones y publicación, e `inbox_provider.py` llama a `create_app()` por `httpx.ASGITransport`), así que una imagen "sólo API" tendría exactamente las mismas dependencias. `qualify-web` es Caddy con el frontend ya exportado adentro: en producción el frontend no necesita ni Node ni Python.

**Lo que la imagen NO trae:** el grupo `ml` (torch/transformers) ni `dev`. `qualify_models` va en `PYTHONPATH` (igual que en CI) porque el CRM importa su tabla pura `permission_capability` al arrancar. Consecuencia: lo que necesita torch localmente — análisis de sentimiento de comentarios, borradores de respuesta y transcripción local con whisper del Brand Kit — **falla al usarse** en este servidor (no al arrancar). Ver §11.

## 2. Crear el servidor (consola de Hetzner)

1. <https://console.hetzner.cloud> → proyecto (crear uno "Qualify" si no existe) → **Add Server**.
2. **Location:** la más cercana a los usuarios con stock (Ashburn `ash` o Hillsboro `hil` para LatAm; Falkenstein/Nuremberg si no). La disponibilidad cambia por ubicación — si un tipo sale "unavailable", probar otra.
3. **Image:** Ubuntu **24.04**.
4. **Type:** *Shared vCPU · x86*. **El CX22 ya no se vende** (Hetzner renovó la línea y subió precios el 2026-06-15, ver [`plan-cicd-staging.md`](plan-cicd-staging.md) §5.8): su equivalente es el **CX23** (2 vCPU · 4 GB · 40 GB). Alcanza para este compose **sin** el perfil `render`. Si se va a activar Remotion, usar **CX33** (4 vCPU · 8 GB). x86, no ARM (CAX): la imagen de Remotion/Chromium es x86.
5. **Networking:** IPv4 pública (sí) + IPv6.
6. **SSH keys:** *Add SSH key* → pegar la pública del Mac (`cat ~/.ssh/id_ed25519.pub`; si no existe, `ssh-keygen -t ed25519`). Así no se crea contraseña de root.
7. **Firewalls (opcional, gratis):** crear uno con entrantes TCP 22, 80, 443 y UDP 443. El script también configura `ufw` en el propio servidor.
8. **Backups** (opcional, +20 % del precio): instantáneas diarias del disco completo. Complementan, no reemplazan, el `pg_dump` de §8.
9. Nombre: `qualify-prod`. **Create & Buy** y anotar la IPv4.

## 3. Preparar el servidor (una vez)

Desde el Mac, en la raíz del repo:

```bash
ssh root@<IP> 'bash -s' < deploy/bootstrap-server.sh
```

Instala Docker + Compose (repositorio oficial de Docker), crea 2 GB de swap, el usuario `deploy` (en el grupo `docker`, con la misma llave SSH que root), `/opt/qualify/{releases,backups}`, `ufw` (sólo 22/80/443), desactiva el login por contraseña y deja el cron del respaldo nocturno. Es idempotente: se puede volver a correr.

Comprobar: `ssh deploy@<IP> docker ps` (debe responder sin `sudo`).

> **Ojo con Docker y ufw:** Docker publica puertos por su propia cadena de iptables, que se salta `ufw`. Es seguro aquí sólo porque el compose de producción no publica nada salvo Caddy. **Nunca** añadir `ports:` a `postgres` ni a `redis`. Para entrar a la base no hace falta publicarla: `dc exec postgres psql -U qualify_owner qualify` en el servidor (§7).

## 4. El archivo de secretos `/opt/qualify/.env.prod`

```bash
scp deploy/.env.prod.example deploy@<IP>:/opt/qualify/.env.prod
ssh deploy@<IP>
chmod 600 /opt/qualify/.env.prod
nano /opt/qualify/.env.prod
```

Cada variable está comentada en el ejemplo. Lo esencial:

| Variable | Cómo llenarla |
|---|---|
| `QUALIFY_PUBLIC_URL` / `QUALIFY_DOMAIN` | `https://qualify.attitudefactory.co` / `qualify.attitudefactory.co` |
| `QUALIFY_ACME_EMAIL` | Correo para avisos de Let's Encrypt |
| `QUALIFY_DB_OWNER_PASSWORD`, `QUALIFY_DB_APP_PASSWORD`, `QUALIFY_DB_ADMIN_PASSWORD`, `QUALIFY_DB_CREDENTIAL_PASSWORD` | `openssl rand -hex 24` cada una (hex: van dentro de una URL) |
| `QUALIFY_DEV_FERNET_KEY` | `python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. **Guardarla también en el gestor de contraseñas:** si se pierde, todos los tokens OAuth guardados quedan ilegibles |
| `QUALIFY_OAUTH_STATE_SECRET` | `openssl rand -hex 32` |
| `QUALIFY_META_*`, `QUALIFY_SUPABASE_*`, `QUALIFY_R2_*`, `QUALIFY_ANTHROPIC_API_KEY`, … | Los mismos valores que el `.env` local (no copiar `QUALIFY_*_DSN` ni `QUALIFY_REDIS_URL`: el compose los arma) |

El compose **se niega a arrancar** si falta alguno de: contraseñas de BD, `QUALIFY_DEV_FERNET_KEY`, `QUALIFY_OAUTH_STATE_SECRET`, `QUALIFY_META_APP_ID/SECRET`, `QUALIFY_SUPABASE_URL/PUBLISHABLE_KEY`. Es a propósito: en el código esos valores caen a un default de desarrollo **commiteado**, y sin este chequeo producción correría silenciosamente con la llave de desarrollo. `QUALIFY_AUTH_FAKE` se fuerza vacío pase lo que pase en el archivo.

`QUALIFY_PUBLIC_MEDIA_BASE_URL` lo arma el compose como **el origen pelado** (`https://qualify.attitudefactory.co`): el código ya agrega `/public/media/<token>` (`qualify_api.config.PublicMediaSettings.public_media_url`). Ponerle `/public/media` al final —como sugiere [`plan-cicd-staging.md`](plan-cicd-staging.md) §5.7 punto 4— duplicaría la ruta y Meta recibiría URLs 404 al publicar.

## 5. DNS (zona en Vercel)

```bash
vercel dns add attitudefactory.co qualify A <IPv4>
vercel dns add attitudefactory.co qualify AAAA <IPv6>   # opcional
vercel dns ls attitudefactory.co                         # verificar
dig +short qualify.attitudefactory.co                    # debe devolver la IP del servidor
```

**Importante:** la zona tiene un registro comodín `*` (ALIAS) que manda **todos** los subdominios a Vercel. Sin un registro `A` explícito para `qualify`, el subdominio seguiría resolviendo a Vercel y Caddy nunca obtendría el certificado. El registro explícito gana sobre el comodín.

Hacer esto **antes** del primer deploy: Caddy pide el certificado a Let's Encrypt en cuanto arranca, y Let's Encrypt valida contra la IP que publica el DNS.

## 6. Primer despliegue

Desde el Mac, en la raíz del repo:

```bash
just deploy deploy@<IP>                 # despliega origin/main
just deploy deploy@<IP> <sha-o-rama>    # o un ref concreto (ya commiteado)
```

Qué hace `deploy/deploy.sh deploy`:

1. `git archive` del ref (sólo lo **commiteado** — nunca el árbol sucio ni el `.env`) → `/opt/qualify/releases/<sha>`. El servidor no necesita acceso a GitHub.
2. `docker compose build` (la primera vez tarda ~10–15 min en un CX23: dependencias de Python + export del frontend; luego queda en caché). La imagen `qualify-app` la construye **sólo** el servicio `api`; los demás la nombran. Si varios servicios la construyeran, cada copia saldría con otra etiqueta de servicio y el ID cambiaría en cada deploy, lo que recrearía `api`/`reflex` aunque el código fuera el mismo.
3. `docker compose run --rm migrate` (`alembic upgrade head` como `qualify_owner` + `ALTER ROLE` con las contraseñas de `.env.prod`; levanta `postgres` antes) y, **sólo si terminó bien**, `docker compose up -d`. `migrate` es un paso explícito con perfil propio, no una dependencia de `api`/`reflex`. Un deploy sin cambios de imagen no recrea ningún contenedor, así que no hay ventana de 502. Mientras `migrate` corre, el release anterior sigue atendiendo, igual que antes de este cambio. Por eso toda migración tiene que ser compatible con el código anterior (expandir → contraer en dos deploys, §7). Recién entonces `/opt/qualify/current` pasa a apuntar al release nuevo: si el build o la migración fallan, `current` (y con él `status`, `logs` y el cron de respaldo) se queda en el último release bueno.
4. Chequeos de salud a través de Caddy: `/ping` = 200, `/api/connections/callback?code=x&state=x` = **403** (estado inválido: prueba que llegó a FastAPI; un 502 sería falla), `/login` = 200.

Después: abrir <https://qualify.attitudefactory.co/login>. Para crear el primer negocio usar `/signup`, o por consola:

```bash
ssh -t deploy@<IP> 'cd /opt/qualify/current && docker compose --env-file /opt/qualify/.env.prod \
  -f deploy/docker-compose.prod.yml run --rm -it api \
  python -m qualify_api.auth.provision register --name "Attitude" --email <correo> \
  --country CO --timezone America/Bogota --currency USD'
```

> **El primer despliegue cierra ADR 27 R8a.** Hasta hoy las migraciones se editaban en sitio porque nada estaba desplegado. Desde que haya datos en este servidor, **toda migración nueva es aditiva** y una revisión ya aplicada no se vuelve a editar (editarla no la re-ejecuta: `alembic` la da por aplicada).

## 7. Actualizar, revertir, ver logs

```bash
just deploy deploy@<IP>                    # actualizar a origin/main
just deploy deploy@<IP> <sha-anterior>     # revertir el código a un release previo
just deploy-status deploy@<IP>             # contenedores + chequeos de salud
just deploy-logs deploy@<IP>               # logs de todo, en vivo
just deploy-logs deploy@<IP> reflex        # de un servicio: api | reflex | caddy | migrate | postgres | redis
```

En el servidor directamente:

```bash
cd /opt/qualify/current
alias dc='docker compose --env-file /opt/qualify/.env.prod $(test -f deploy/release.env && echo --env-file deploy/release.env) -f deploy/docker-compose.prod.yml'
dc ps
dc logs -f --tail=200 api
dc restart reflex
dc exec postgres psql -U qualify_owner qualify
```

Se conservan los últimos 5 releases en `/opt/qualify/releases`. Revertir código es re-desplegar un SHA anterior; **revertir un esquema no**: si un release trajo una migración, el anterior debe ser compatible con el esquema nuevo (expandir → contraer en dos deploys), o restaurar un respaldo (§8).

Cambiar un secreto: editar `/opt/qualify/.env.prod` y `just deploy` (o `dc run --rm migrate && dc up -d` en el servidor; el `migrate` es lo que aplica una contraseña de base de datos cambiada a su rol). Cambiar `QUALIFY_PUBLIC_URL` exige reconstruir (`--build`): está horneada en el frontend estático.

### 7.1 Deploy desde GitHub Actions (CD) — opcional, lo activa el fundador

Con esto montado, Actions construye para un commit de `main` tres imágenes y las publica en GHCR (`ghcr.io/attitudefactory/qualify-{app,web,deploy}:<sha>`). `qualify-deploy` lleva sólo el directorio `deploy/` de ese commit. El servidor hace `pull`, toma el compose y los scripts del release de `qualify-deploy`, y corre `migrate` → `up`. **Nunca compila en producción.** El workflow es `.github/workflows/deploy.yml` y el lado del servidor es `deploy/server-deploy.sh`. `just deploy` desde la Mac sigue funcionando igual y se puede alternar con el CD.

Montaje (una vez):

1. **Llave de deploy, sólo para esto.** En la Mac:
   ```bash
   ssh-keygen -t ed25519 -N '' -C qualify-ci-deploy -f ~/.ssh/qualify_ci_deploy
   ```
2. **Script fijo en el servidor.** Hacer primero un `just deploy` de un `main` que ya incluya `deploy/server-deploy.sh`, y después:
   ```bash
   ssh deploy@<IP> 'install -D -m 755 /opt/qualify/current/deploy/server-deploy.sh /opt/qualify/bin/server-deploy.sh'
   ```
   Vive fuera de `releases/` a propósito: un deploy no puede reemplazar el comando que la llave tiene permitido. Si el script cambia en el repo, se reinstala con el mismo comando.
3. **Restringir la llave** en `~deploy/.ssh/authorized_keys` del servidor, en **una** línea:
   ```
   command="/opt/qualify/bin/server-deploy.sh",restrict ssh-ed25519 AAAA…(contenido de qualify_ci_deploy.pub)… qualify-ci-deploy
   ```
   Esa llave sólo puede pedir `deploy <sha>`: sin shell, sin túneles, sin pty, y sin mandar archivos. El compose y los scripts del release salen de `qualify-deploy:<sha>` en GHCR, nunca de quien tiene la llave. **Límite real:** la llave despliega cualquier commit que el CI haya publicado; publicar en GHCR exige permiso de escritura en el repositorio, que ya alcanza para cambiar lo que corre en producción. `deploy` está en el grupo `docker` (equivale a root), y por eso importa que la llave no pueda pedir nada más.
4. **Permiso de lectura de GHCR en el servidor.** Las imágenes son privadas. Crear un token *classic* con sólo `read:packages` (GitHub Packages no acepta tokens *fine-grained*), con vencimiento, y:
   ```bash
   ssh deploy@<IP> 'docker login ghcr.io -u <usuario-github> --password-stdin' <<<"<token>"
   ```
5. **Secretos del repositorio** (*Settings → Secrets and variables → Actions*):

   | Secreto | Valor |
   |---|---|
   | `QUALIFY_DEPLOY_SSH_KEY` | contenido de `~/.ssh/qualify_ci_deploy` (la mitad **privada**) |
   | `QUALIFY_DEPLOY_SSH_TARGET` | `deploy@<IP>` |
   | `QUALIFY_DEPLOY_SSH_KNOWN_HOSTS` | salida de `ssh-keyscan -t ed25519 <IP>`, después de comparar su huella con `ssh deploy@<IP> ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` |

6. **Primer deploy manual:** *Actions → deploy → Run workflow* (ref `main`). Debe terminar con los tres chequeos `ok` en el servidor y el smoke externo en verde.
7. **Opcional, deploy automático:** variable de repositorio `QUALIFY_AUTO_DEPLOY=true`. Con ella, cada run de `ci` en verde sobre `main` (después de un merge) despliega solo.

Operación:

| Tarea | Cómo |
|---|---|
| Desplegar un commit | *Run workflow* con su sha o rama |
| Revertir | *Run workflow* con el sha anterior (sus imágenes siguen en GHCR). Si entre medio hubo una migración, marcar **`skip_migrate`**: la imagen vieja no conoce la revisión nueva y `alembic upgrade` fallaría con `Can't locate revision` (comprobado). Sólo es seguro porque las migraciones son expandir → contraer. Con `just deploy <sha-anterior>` desde la Mac pasa lo mismo y no hay atajo: el rollback a través de una migración se hace por el workflow |
| Si fallan los chequeos después del `up` | el release nuevo ya está corriendo y `current` apunta a él; el workflow queda en rojo. Revertir como arriba |
| Ver qué imágenes corren | `cat /opt/qualify/current/deploy/release.env` |
| Comandos a mano en el servidor | el alias `dc` de arriba, que ya agrega `--env-file deploy/release.env` cuando existe (sin él, Compose buscaría `qualify-app:latest` y compilaría en el servidor) |

Límites:
- **Perfil `render`:** el CD se niega si `COMPOSE_PROFILES` incluye `render`, porque su imagen todavía no se publica (punto 6 del plan). Mientras tanto, ese caso se despliega con `just deploy`.
- **`calendar-worker`:** el CD no lo toca. Los perfiles salen sólo de `.env.prod`.

## 8. Respaldos de Postgres

`bootstrap-server.sh` deja un cron diario (03:15 UTC) que corre `deploy/backup-db.sh` como `deploy`:

- `/opt/qualify/backups/qualify-<UTC>.dump` — `pg_dump -Fc` de la base `qualify`.
- `/opt/qualify/backups/globals-<UTC>.sql` — `pg_dumpall --roles-only` (los cuatro roles con sus hashes de contraseña; `pg_dump` no los incluye).
- Retención: 14 días (`QUALIFY_BACKUP_KEEP_DAYS`). Log en `/opt/qualify/backups/backup.log`.

Respaldo manual (p. ej. antes de un deploy con migración): `just deploy-backup deploy@<IP>`.

**Esos archivos viven en el mismo disco que la base.** Copiarlos fuera, por ejemplo desde el Mac:

```bash
rsync -av deploy@<IP>:/opt/qualify/backups/ ~/Backups/qualify/
```

(Subirlos a un bucket R2 cifrados con `age`, como propone [`plan-cicd-staging.md`](plan-cicd-staging.md) §5.6, queda pendiente — §11.)

### Restaurar un respaldo

En el servidor, con el stack arriba:

```bash
cd /opt/qualify/current
alias dc='docker compose --env-file /opt/qualify/.env.prod $(test -f deploy/release.env && echo --env-file deploy/release.env) -f deploy/docker-compose.prod.yml'
dc stop api reflex calendar-worker
dc exec -T postgres psql -U qualify_owner -d postgres -c 'DROP DATABASE qualify WITH (FORCE);'
dc exec -T postgres psql -U qualify_owner -d postgres -c 'CREATE DATABASE qualify OWNER qualify_owner;'
dc exec -T postgres pg_restore -U qualify_owner -d qualify --exit-on-error < /opt/qualify/backups/qualify-<UTC>.dump
dc run --rm migrate && dc up -d   # migrate re-aplica las contraseñas de .env.prod y queda en head
```

Los roles son globales del clúster y sobreviven al `DROP DATABASE`, así que no hace falta `globals-*.sql` salvo que se haya perdido el volumen entero; en ese caso, con un volumen nuevo, primero `dc up -d postgres`, luego `dc exec -T postgres psql -U qualify_owner -d postgres < globals-<UTC>.sql` (ignorar el error de que `qualify_owner` ya existe), y después los pasos de arriba.

## 9. Ajustes en Meta y demás proveedores (después del primer deploy)

**Meta** — app `1670943920870196` en <https://developers.facebook.com/apps/1670943920870196/>:

1. *Facebook Login for Business → Settings → Valid OAuth Redirect URIs*: `https://qualify.attitudefactory.co/api/connections/callback` (exacto, debe coincidir con `QUALIFY_META_REDIRECT_URI`). Quitar las URLs de túneles `cloudflared`.
2. *App settings → Basic → App Domains*: `qualify.attitudefactory.co` (y `attitudefactory.co`).
3. *App settings → Basic → Add platform → Website → Site URL*: `https://qualify.attitudefactory.co/`.
4. En la misma página: Privacy Policy URL y User Data Deletion (URL de instrucciones) — App Review los exige; deben ser páginas públicas (pueden vivir en `attitudefactory.co`).
5. Para los revisores de App Review: crear un usuario de prueba con `/signup` y darles esas credenciales en las instrucciones de la revisión.

**Supabase** (auth de la app): *Authentication → URL Configuration*: Site URL `https://qualify.attitudefactory.co` y añadirla a *Redirect URLs*.

**Canva**: registrar `https://qualify.attitudefactory.co/canva/callback` y `https://qualify.attitudefactory.co/canva/return` en el portal de desarrolladores, y `QUALIFY_CANVA_REDIRECT_URI` igual a la primera.

Luego actualizar [`prioridad-despliegue-subdominio.md`](prioridad-despliegue-subdominio.md) §7 pasos 7–9 y arrancar Business Verification.

## 10. Servicios opcionales

Se activan con `COMPOSE_PROFILES` en `/opt/qualify/.env.prod` y un `just deploy`.

- **`calendar-worker`** — el ejecutor del Planificador (QUA-111). **Publica de verdad** en las cuentas conectadas. En el servicio `reflex` el worker embebido está **forzado a `off`**, así que sin este perfil nada programado sale. Alcance por defecto `--all-tenants`; para limitarlo: `QUALIFY_CALENDAR_WORKER_SCOPE=--tenant=<uuid>`. Nota: la pantalla del Planificador informa el estado del worker *embebido* (apagado) aunque este servicio esté corriendo.
- **`render`** — servicio Remotion (Node + Chromium headless) para el generador por plantillas. Pide ~1 GB de RAM al renderizar: en un CX23 hay riesgo de quedarse sin memoria; usar CX33. Sin él, el generador por plantillas falla con error claro; el resto de la app no se entera.

## 11. Pendientes conocidos (no bloquean el despliegue)

1. **El callback OAuth termina en JSON.** `/api/connections/callback` responde `{"outcome": ..., "connection_id": ...}` en vez de redirigir a `/connections`. Funciona, pero el revisor de Meta ve un JSON crudo al terminar de conectar. Pide un redirect a la UI (cambio de código en `connections_routes.py`, fuera de este PR).
2. **Funciones que necesitan torch no corren en este servidor** (sentimiento de comentarios, borradores de respuesta, whisper local del Brand Kit). Para activarlas: o el grupo `ml` en la imagen (varios GB más; no cabe holgado en un CX23), o moverlas a proveedores hospedados.
3. **La API HTTP no tiene login real.** Las rutas `/api/*` que exigen `Principal` usan `QUALIFY_DEV_PRINCIPALS`; vacío = 401 (seguro). La UI no las necesita (llama a los servicios en proceso). El callback OAuth y `/public/media/*` no la usan.
4. **Nombres `DEV` en la llave maestra** (`QUALIFY_DEV_FERNET_KEY`, `QUALIFY_DEV_KEY_ID`) y default commiteado en `crypto.py`: el compose lo vuelve obligatorio, pero el código sigue cayendo a la llave de desarrollo si se ejecuta fuera de este compose. Renombrar + fail-closed en código es trabajo aparte (también lo pide `plan-cicd-staging.md` §5.4).
5. **Divergencias con [`plan-cicd-staging.md`](plan-cicd-staging.md)** (plan del mismo día, aún sin firmar): ese plan propone construir las imágenes en GitHub Actions, publicarlas en GHCR y desplegar por SSH con llave forzada desde Actions; este PR construye **en el servidor** a partir de un `git archive` lanzado desde el Mac (lo que se pidió: el fundador despliega desde su Mac, sin depender de CI ni de secretos en GitHub). El compose ya está parametrizado por `QUALIFY_IMAGE_TAG`, así que migrar a imágenes de GHCR después es cambiar `build:` por `image: ghcr.io/...` y `build` por `pull` en `deploy.sh`. Tampoco hay aún `GET /api/health` (el healthcheck usa `/openapi.json`) ni respaldo a R2.
6. **Monitoreo externo** (un ping HTTP cada 5 min desde un servicio gratuito) — no configurado.

## 12. Cómo se verificó (2026-10-05, en el Mac, sin servidor)

El mismo `deploy/docker-compose.prod.yml`, con un proyecto Compose aparte (`-p qualify-smoke`, sin chocar con el stack de desarrollo), un `.env` desechable y Caddy en `http://localhost:18480` sin TLS (`QUALIFY_DOMAIN=http://localhost`, `QUALIFY_PUBLIC_URL=http://localhost:18480`, `QUALIFY_HTTP_PORT=18480`, `QUALIFY_HTTPS_PORT=18443`):

```bash
QUALIFY_ENV_FILE=/ruta/.env.smoke docker compose -p qualify-smoke \
  --env-file /ruta/.env.smoke -f deploy/docker-compose.prod.yml up -d --build
```

| Comprobación | Resultado |
|---|---|
| `docker build --target app` / `--target web` | OK (imagen app 380 MB, sin torch; `reflex export` en ~25 s) |
| `migrate` sobre volumen vacío | `0001 → 0040` aplicadas; `bootstrap_db_roles` fija las 3 contraseñas; re-ejecutarlo es inocuo |
| Roles | Los tres DSN de la app conectan; las contraseñas de desarrollo (`app_dev`, …) son **rechazadas** |
| `/`, `/login`, `/signup`, `/brand`, `/design` | 200 (estático desde Caddy) |
| `/drafts/abc123` (ruta dinámica) | 200 (fallback SPA) |
| `/ping`, `/_health` | 200 (backend de Reflex) |
| `/api/connections/callback?code=x&state=x` | **403** `invalid or expired state` → llegó a FastAPI (no 502) |
| `/public/media/<token inexistente>` | 404 desde FastAPI |
| `/avatar/tiktok/nobody`, `/r2media/<token malo>` | 200 / 404 desde el backend de Reflex (`api_transformer`) |
| WebSocket `/_event` | `101 Switching Protocols` + paquete de apertura de Engine.IO; en un navegador real, `/connections` sin sesión ejecuta su `on_load` por el websocket y redirige a `/brand/start` |
| Puertos publicados | Sólo Caddy; `postgres`/`redis`/`api`/`reflex` sin puertos en el host |
| Falta `QUALIFY_DEV_FERNET_KEY` | `docker compose` se niega a arrancar (error de interpolación) |
| Worker embebido en `reflex` | Log `calendar.embedded.off` |
| Perfil `calendar-worker` | Arranca `--all-tenants`, primer tick `tenants=0` |
| `backup-db.sh` + restauración de §8 | Dump + globals escritos; `DROP/CREATE DATABASE` + `pg_restore` recupera una fila testigo, `alembic_version = 0040` y las 48 políticas RLS |
| `caddy validate` con el dominio real | `Valid configuration` |
| Contraseñas crudas de BD dentro de `api`/`reflex` | Vacías (sólo llegan los DSN por rol; la del dueño superusuario no la tiene ningún proceso que sirve tráfico) |
| `QUALIFY_CALENDAR_WORKER_INTERVAL=45` con el perfil activo | El worker arranca con `interval=45s` |
| `deploy.sh deploy HEAD` en un "servidor" vacío (con un `ssh` de prueba que ejecuta en local) | `git archive` → release → build → migrate → `up` → `current` → los tres chequeos `ok`, salida 0 |
| `deploy.sh deploy` con `.env.prod` roto (sin llave Fernet) | Falla con salida 1 y `current` **sigue** en el release anterior, que sigue sirviendo |
| `deploy.sh status` / `deploy.sh backup` (mismo `ssh` de prueba) | `ok` en los tres chequeos y salida 0; si un chequeo no da el código esperado, `FAIL` y salida ≠ 0 (camino ejercitado en la primera corrida, que además destapó un fallo con arreglos vacíos en bash 3.2, ya corregido) |

No verificado localmente: la emisión real del certificado (requiere DNS apuntando al servidor), el build en x86 del servidor (aquí fue arm64), el perfil `render` (su imagen no se construyó en esta sesión) y `deploy.sh` a través de un ssh real (se probó con un `ssh` de prueba que ejecuta los mismos comandos en local).
