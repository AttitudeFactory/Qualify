# Despliegue de Qualify en Hetzner — `qualify.attitudefactory.co`

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Estado:** `[LISTO PARA EJECUTAR 2026-10-05]` — el repo ya es desplegable; lo que falta lo hace el fundador (crear el servidor, el registro DNS, el `.env.prod` y los ajustes de Meta). Cierra la bifurcación de host de [`prioridad-despliegue-subdominio.md`](prioridad-despliegue-subdominio.md) §4: **Hetzner**.
**Para qué:** que Meta App Review tenga una URL pública estable donde iniciar sesión, y que el callback OAuth de Meta tenga un redirect URI fijo (`https://qualify.attitudefactory.co/api/connections/callback`) en vez del túnel `cloudflared` efímero.
**Piezas en el repo:** `deploy/Dockerfile`, `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `deploy/.env.prod.example`, `deploy/deploy.sh`, `deploy/bootstrap-server.sh`, `deploy/backup-db.sh`, `deploy/bootstrap_db_roles.py`, `deploy/bootstrap-claude.sh` + `deploy/claude-server.md` (§13), y las recetas `just deploy*`.

---

## 1. Qué corre en el servidor

Un solo servidor con **dos composes independientes**: el de Qualify y el **proxy de entrada** del VPS (`/opt/edge`, ver §1.1). Desde el 2026-10-14 el proxy de entrada es lo único expuesto a internet (80/443): termina el TLS de todos los productos del servidor y le pasa a Qualify su dominio por la red Docker `qualify-edge`. El Caddy de Qualify ya no publica puertos; reparte por ruta en HTTP plano:

```
                 internet ──► :80/:443  edge   (/opt/edge — TLS de todos los dominios del VPS)
                                          │  qualify.attitudefactory.co ─► red qualify-edge
                                          │  pedidos.attitudefactory.co ─► red pedidos (otro producto, otro compose)
                                          ▼
                                 :80  caddy  (router interno de Qualify + frontend estático; sin puertos publicados)
                                          │
        /api/*, /public/media/*  ─────────┼──► api      FastAPI  (uvicorn, qualify_api.http.app:create_app)
        /_event, /_upload, /ping,         │
        /_health, /avatar/*, /r2media/* ──┼──► reflex   backend de Reflex (websocket + rutas propias)
        todo lo demás  ───────────────────┘    /srv     export estático del frontend de Reflex

  red interna (sin puertos publicados):  postgres (pgvector/pgvector:pg16)  ·  redis 7
  paso explícito antes del `up`:         migrate  (`run --rm`; alembic upgrade head + contraseñas de los roles + registro de la app de Meta)
  workers siempre activos:               webhook-worker · whatsapp-worker · conversations-worker · calendar-worker (PUBLICA DE VERDAD lo aprobado y programado)
  opcionales (perfil, apagados):         render (Remotion)
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

### 1.1 Proxy de entrada (`deploy/edge/`, vive en `/opt/edge`)

**Regla del fundador (2026-10-14):** Qualify y Pedidos son dos productos que comparten VPS y no deben afectarse entre sí. Por eso la puerta del servidor no pertenece a ninguno:

| Pieza | Dónde | Quién la cambia |
|---|---|---|
| Proxy de entrada (Caddy estándar, `caddy:2.11-alpine`) | `/opt/edge` (`docker-compose.yml`, `Caddyfile`, `.env`) | `just edge-install <target>`; nunca un despliegue de producto |
| Red `qualify-edge` | Docker, externa | La crea `install.sh`; el Caddy de Qualify se une con el alias `qualify-web` |
| Red `pedidos` | Docker, externa | La crea `install.sh`; el backend de Pedidos se une como `pedidos-backend:8420` |
| Certificados TLS | volumen `edge_edge_data` | Caddy del proxy (Let's Encrypt, `EDGE_ACME_EMAIL`) |

Qué garantiza: desplegar Qualify recrea su Caddy interno pero **no toca el proxy**, así que Pedidos no se corta; si Qualify o Pedidos están caídos, solo su dominio responde 502; las rutas de Pedidos ya no viven en este repo de producto sino en `deploy/edge/Caddyfile`. Lo fija `packages/api/tests/test_deploy_edge.py` (ningún servicio de Qualify publica puertos ni menciona Pedidos).

**Hosts extra de Qualify** (2026-10-16): `QUALIFY_EXTRA_HOSTS` en `/opt/edge/.env` (separados por espacio) hace que el proxy responda también en esos nombres hacia el mismo Qualify, con certificado propio; la URL canónica sigue siendo `QUALIFY_DOMAIN`. Primer uso: `app.qualify.la`, el dominio al que el plugin de Meegle manda sus eventos (`docs/plan-altas-meegle.md`). Pasos: registro `A` de `app` en la zona `qualify.la` (§5), `QUALIFY_EXTRA_HOSTS=app.qualify.la` en `/opt/edge/.env`, `just edge-install <target>` (recarga sin corte); comprobar `curl -I https://app.qualify.la/ping` → 200.

**Cambiar una ruta del proxy:** editar `deploy/edge/Caddyfile` y `just edge-install <target>` (copia y aplica; Caddy recarga sin cortar conexiones si solo cambió el Caddyfile: `cd /opt/edge && docker compose exec edge caddy reload --config /etc/caddy/Caddyfile`).

**Corte único desde el esquema anterior** (Caddy de Qualify en 80/443), en este orden:

1. Una vez, como root en el servidor: `install -d -o deploy -g deploy /opt/edge`.
2. Desde el Mac: `just edge-install <target>`. La primera vez crea `/opt/edge/.env` desde la plantilla y se detiene: poner `EDGE_ACME_EMAIL` (y revisar los dos dominios).
3. Desde el Mac: `just edge-install <target> --wait-for-ports`. Crea las redes, copia los certificados actuales al volumen del proxy (no hace falta emitir nuevos), deja el contenedor creado y **se queda esperando** a que 80/443 queden libres.
4. Con eso esperando, desplegar Qualify (workflow `deploy` o `just deploy`). Al recrearse, el Caddy de Qualify suelta 80/443 y el proxy arranca en ese mismo segundo. El healthcheck del despliegue ya pasa por el proxy.
5. Comprobar: `install.sh` imprime `/ping` de Qualify (200) y el código de Pedidos (cualquier código HTTP; 502 = backend de Pedidos apagado).

Corte esperado: unos segundos para los dos dominios, una sola vez. Vuelta atrás: `cd /opt/edge && docker compose down` y desplegar el commit anterior de Qualify (que vuelve a publicar 80/443).

## 2. Crear el servidor (consola de Hetzner)

1. <https://console.hetzner.cloud> → proyecto (crear uno "Qualify" si no existe) → **Add Server**.
2. **Location:** la más cercana a los usuarios con stock (Ashburn `ash` o Hillsboro `hil` para LatAm; Falkenstein/Nuremberg si no). La disponibilidad cambia por ubicación — si un tipo sale "unavailable", probar otra.
3. **Image:** Ubuntu **24.04**.
4. **Type:** *Shared vCPU · x86*. **El CX22 ya no se vende** (Hetzner renovó la línea y subió precios el 2026-06-15, ver [`plan-cicd-staging.md`](plan-cicd-staging.md) §5.8): su equivalente es el **CX23** (2 vCPU · 4 GB · 40 GB). Alcanza para este compose **sin** el perfil `render`. Si se va a activar Remotion, usar **CX33** (4 vCPU · 8 GB). Ojo con la arquitectura: el servidor de producción resultó ser **aarch64** (el primer deploy por CI falló con una imagen amd64, 2026-10-06), y por eso todas las imágenes, render incluido, se construyen para `linux/arm64`. Remotion soporta Chrome Headless Shell en Linux arm64; al agrandar, elegir el plan de 4 vCPU · 8 GB de la **misma** arquitectura que el servidor actual.
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
| `QUALIFY_DB_OWNER_PASSWORD`, `QUALIFY_DB_APP_PASSWORD`, `QUALIFY_DB_ADMIN_PASSWORD`, `QUALIFY_DB_CREDENTIAL_PASSWORD`, `QUALIFY_DB_WEBHOOK_PASSWORD`, `QUALIFY_DB_WEBHOOK_WORKER_PASSWORD` | `openssl rand -hex 24` cada una (hex: van dentro de una URL) |
| `QUALIFY_DEV_FERNET_KEY` | `python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. **Guardarla también en el gestor de contraseñas:** si se pierde, todos los tokens OAuth guardados quedan ilegibles |
| `QUALIFY_OAUTH_STATE_SECRET` | `openssl rand -hex 32` |
| `QUALIFY_RESEND_API_KEY`, `QUALIFY_MAIL_FROM`, `QUALIFY_INVITE_SIGNER`, `QUALIFY_MAIL_REPLY_TO`, `QUALIFY_RESEND_WEBHOOK_SECRET` | Correo transaccional (invitaciones y SMTP de Supabase), ver §9 «Resend». Sin la API key la app arranca igual: `just invite` crea la invitación y **imprime el enlace** para mandarlo a mano, y la recuperación de contraseña sigue saliendo por el remitente por defecto de Supabase (sólo llega a miembros del proyecto) |
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

Para el host extra `app.qualify.la` (la zona `qualify.la` también tiene comodín `*` hacia Vercel):

```bash
vercel dns add qualify.la app A 2.28.112.133
dig +short app.qualify.la                                # debe devolver 2.28.112.133
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
3. `docker compose run --rm migrate` (`alembic upgrade head` como `qualify_owner` + `ALTER ROLE` con las contraseñas de `.env.prod` + `python -m qualify_api.connections.platform_app`, que registra `QUALIFY_META_APP_ID` en `platform_apps` de forma idempotente; levanta `postgres` antes) y, **sólo si terminó bien**, `docker compose up -d`. `migrate` es un paso explícito con perfil propio, no una dependencia de `api`/`reflex`. Un deploy sin cambios de imagen no recrea ningún contenedor, así que no hay ventana de 502. Mientras `migrate` corre, el release anterior sigue atendiendo, igual que antes de este cambio. Por eso toda migración tiene que ser compatible con el código anterior (expandir → contraer en dos deploys, §7). Recién entonces `/opt/qualify/current` pasa a apuntar al release nuevo: si el build o la migración fallan, `current` (y con él `status`, `logs` y el cron de respaldo) se queda en el último release bueno.
4. Chequeos de salud a través de Caddy: `/ping` = 200, `/api/connections/callback?code=x&state=x` = **303** hacia `/connections?connect=invalid_state` (estado inválido: prueba que llegó a FastAPI; un 502 sería falla), `/login` = 200.

Después: abrir <https://qualify.attitudefactory.co/login>. Para crear el primer negocio usar `/registro` (antes `/signup`, que sigue sirviendo), o por consola:

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

Se conservan los últimos 5 releases en `/opt/qualify/releases`, pero solo las imágenes de los **2 más nuevos** (el vivo y el anterior). Después del health check, `server-deploy.sh` borra las etiquetas de los demás shas y las `qualify-*:latest` que deja `just deploy`. También borra las imágenes colgadas y el caché de build de más de 24 h. Nunca toca volúmenes ni imágenes que no sean `qualify-*` (Pedidos, edge). Revertir a un sha más viejo vuelve a bajar sus imágenes de GHCR (m-24852229). Revertir código es re-desplegar un SHA anterior; **revertir un esquema no**: si un release trajo una migración, el anterior debe ser compatible con el esquema nuevo (expandir → contraer en dos deploys), o restaurar un respaldo (§8).

Cambiar un secreto (llaves de proveedores: Scrape Creators, Anthropic, HeyGen, BytePlus, Meta…): ponerlo en el `.env` local y empujarlo desde la Mac, sin desplegar código:

```bash
just env-push qualify-prod --dry-run SCRAPECREATORS_API_KEY   # compara huellas, no escribe
just env-push qualify-prod SCRAPECREATORS_API_KEY             # escribe y recrea
```

Copia las claves nombradas (y sólo ésas) del `.env` local a `/opt/qualify/.env.prod`, deja un respaldo `.env.prod.bak-<UTC>` (se guardan los 10 más recientes) y corre `dc up -d --no-build`: Compose incluye el `env_file` en el hash de configuración de cada servicio, así que recrea exactamente los que leen `.env.prod` (`api`, `reflex`, `calendar-worker` si está activo) y no toca `postgres`, `redis` ni `caddy`. Los valores viajan por el stdin de ssh, nunca por argumentos ni por la terminal; la salida sólo muestra una huella sha256 de 8 caracteres por clave. Desde un worktree lee el `.env` del checkout principal (o el de `QUALIFY_ENV_SOURCE`).

Se niega, a propósito, con: contraseñas de base de datos y `QUALIFY_PUBLIC_URL` (necesitan `migrate` o reconstruir: editar `.env.prod` y `just deploy`; el `migrate` es lo que aplica una contraseña cambiada a su rol, y `QUALIFY_PUBLIC_URL` está horneada en el frontend estático), `QUALIFY_DEV_FERNET_KEY` (rotarla deja indescifrables todas las credenciales OAuth guardadas) y `COMPOSE_*`/`QUALIFY_IMAGE_*` (cambian la forma del stack, no un secreto).

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
   Vive fuera de `releases/` a propósito: un deploy no puede reemplazar el comando que la llave tiene permitido. **Si el script cambia en el repo, hay que reinstalarlo con el mismo comando** (ojo: entre el 2026-10-09 y el 2026-10-24 nadie lo reinstaló y el servidor corrió una copia sin soporte de render ni la poda nueva; m-24852229) (el CD toma el compose y los scripts de cada release del bundle, pero ejecuta siempre esta copia fija). Detalle que el script ya contempla (2026-10-09): un `just deploy` desde la Mac entra como root y deja su release en `releases/` propiedad de root; la poda de releases viejas del CD, que corre como `deploy`, la hace entonces a través de un shell root de la imagen `qualify-web`, y va después del health check para que una limpieza nunca ponga en rojo un deploy que ya sirve.
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
7. **Aviso en el grupo `Qualify-devs` (Lark):** el job `notify` publica una tarjeta por cada deploy intentado (`.github/scripts/deploy_notify.py`): resultado (✅/❌ y en qué etapa), commit con su PR y autor, quién lo disparó (merge, manual o diario), acción (deploy/rollback), duración de `resolve` → `images` → `deploy` con el paso que falló, y botones a la corrida y a la app. Solo habla Lark (bot personalizado; ya no hay respaldo de Cliq). Para activarlo: en Lark, grupo *Qualify-devs → ⚙ Configuración → Bots → Añadir bot → Bot personalizado*, nombre «Qualify deploy»; en *Configuración de seguridad* marcar **Palabras clave personalizadas** = `Deploy` (todos los títulos la llevan) o **Verificación de firma** y copiar el secreto; copiar la URL del webhook. En GitHub, secreto `DEVOPS_WEBHOOK_URL` = `https://open.larksuite.com/open-apis/bot/v2/hook/<token>` y, si se eligió firma, `DEVOPS_WEBHOOK_SECRET`. Sin `DEVOPS_WEBHOOK_URL` el job sólo deja un aviso; un fallo o rechazo de Lark (responde 200 con `code ≠ 0`) deja un *warning* y nunca falla el deploy. El secreto `CLIQ_DEVOPS_WEBHOOK_URL` ya no se lee: borrarlo.
8. **Opcional, deploy automático:** variable de repositorio `QUALIFY_AUTO_DEPLOY`. Con `merge` (o `true`) despliega cada push a `main`, es decir, cada merge. Con `daily` despliega una vez al día (07:23 UTC), solo si `main` cambió. Con cualquier otro valor no despliega solo. Comandos y calendario en el README, sección «Operación en producción».

### Avisos al chat de cada épica (m-24822994)

El mismo job `notify` puede enviar además un mensaje por chat de épica. Lee los `m-<id>`
del commit y su PR y, si encuentra un despliegue anterior exitoso entre las últimas cinco
corridas exitosas, los commits incluidos desde ese destino. El destino anterior se toma del
paso de despliegue, no del `head_sha` de Actions (un deploy manual puede usar otro commit).
Consulta los Issues en Meegle, su campo **Feature** y el grupo de cada Feature. Dos épicas
que comparten chat reciben un solo mensaje, con sus tickets. No mueve estados en Meegle.

Un webhook de bot personalizado solo sirve para su grupo original. Para este envío se usa
una **aplicación de Lark con capacidad de bot**, permiso `im:message:send_as_bot` y membresía
en cada chat de épica. No se usa el token personal de un desarrollador. El plugin de Meegle
debe poder leer los Issues y Features del espacio Qualify, actuando como el usuario configurado.

Configurar en GitHub Actions, sin poner valores secretos en el repositorio:

| Tipo | Nombre | Contenido |
|---|---|---|
| Variable | `DEPLOY_MEEGLE_PLUGIN_ID` | ID del plugin de Meegle |
| Variable | `DEPLOY_MEEGLE_USER_KEY` | Miembro del espacio autorizado para las lecturas |
| Secreto | `DEPLOY_MEEGLE_PLUGIN_SECRET` | Secreto del plugin |
| Variable | `DEPLOY_LARK_APP_ID` | ID de la aplicación de Lark |
| Secreto | `DEPLOY_LARK_APP_SECRET` | Secreto de la aplicación |
| Variable | `DEPLOY_EPIC_NOTIFICATIONS` | `true` para habilitar; apagado por defecto |
| Variable | `DEPLOY_EPIC_DRY_RUN` | `true` resuelve los chats sin enviar mensajes |

Primero activar ambos interruptores para comprobar en el log la relación chat/épicas sin
enviar nada. Después desactivar `DEPLOY_EPIC_DRY_RUN` y desplegar un PR con un ticket ligado
a una épica cuyo chat incluya al bot; comprobar un mensaje con el resultado y el enlace a
la corrida. El envío usa una clave por corrida/intento/chat para deduplicar reintentos.
Una repetición de Actions es otro intento y puede producir otro aviso.

Si no hay destino anterior, un rollback o una divergencia, solo se enruta el commit destino.
El rango se limita a 100 commits y 100 tickets: un rango truncado cancela los avisos por
épica, con un warning, en lugar de presentar una lista parcial como completa. Los tickets
sin épica/chat quedan identificados en el log. Sin credenciales, ante un error de Meegle o
si el bot no está en un chat, el despliegue mantiene su resultado y el aviso general a
Qualify-devs sigue funcionando. Un rechazo en un chat no impide intentar los restantes.
No se añade ningún job ni trigger de Actions; las llamadas van en el presupuesto de tres
minutos del job existente. Los cambios de estado de tickets de Meegle son otra integración
(`QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL`), no se activan con estos interruptores.

Operación:

| Tarea | Cómo |
|---|---|
| Desplegar un commit | *Run workflow* con su sha o rama |
| Revertir | *Run workflow* con el sha anterior (sus imágenes siguen en GHCR). Si entre medio hubo una migración, marcar **`skip_migrate`**: la imagen vieja no conoce la revisión nueva y `alembic upgrade` fallaría con `Can't locate revision` (comprobado). Sólo es seguro porque las migraciones son expandir → contraer. Con `just deploy <sha-anterior>` desde la Mac pasa lo mismo y no hay atajo: el rollback a través de una migración se hace por el workflow |
| Si fallan los chequeos después del `up` | el release nuevo ya está corriendo y `current` apunta a él; el workflow queda en rojo. Revertir como arriba |
| Ver qué imágenes corren | `cat /opt/qualify/current/deploy/release.env` |
| Comandos a mano en el servidor | el alias `dc` de arriba, que ya agrega `--env-file deploy/release.env` cuando existe (sin él, Compose buscaría `qualify-app:latest` y compilaría en el servidor) |

Límites:
- **Perfil `render`:** desde m-24803289 el workflow publica `qualify-render:<sha>` (arm64) en cada deploy. Si `COMPOSE_PROFILES` incluye `render`, `server-deploy.sh` también la baja y, después del `up`, espera hasta ~2,5 min a que el contenedor quede `healthy` (bundle de Remotion listo); si no, el deploy sale en rojo con el release ya vivo, como cualquier chequeo. Un sha anterior a ese PR no se puede desplegar con el perfil activo (no tiene imagen de render): el script lo dice antes de tocar nada. Activarlo son dos pasos del fundador: agrandar el servidor (abajo) y agregar `COMPOSE_PROFILES=render` a `/opt/qualify/.env.prod`.
- **`calendar-worker`:** siempre activo desde 2026-10-21 (m-24828928); cada despliegue lo recrea como a los demás workers. Los perfiles (hoy sólo `render`) salen sólo de `.env.prod`.

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
5. Para los revisores de App Review: crear un usuario de prueba con `/registro` y darles esas credenciales en las instrucciones de la revisión.

**Supabase** (auth de la app): *Authentication → URL Configuration*: Site URL `https://qualify.attitudefactory.co` y añadirla a *Redirect URLs*.

**Resend** — correo transaccional de Qualify: las invitaciones de `just invite` (`qualify_api.mail`, PR #106) y el **SMTP propio de Supabase Auth** para los correos de recuperación de contraseña (`/forgot` → `/reset`). Sin SMTP propio, Supabase sólo manda correo a los miembros del proyecto y con tope de 2 por hora: ningún cliente recibiría el enlace. **Remitente decidido (2026-10-16): `no-reply@send.qualify.la`** — el dominio del producto; Lark Mail ocupa la raíz de `qualify.la` (MX, SPF, DKIM) y por eso el envío va en un subdominio. Plan Free de Resend: 3.000 correos/mes, 100/día, **un solo dominio verificado**, así que `send.attitudefactory.co` (DNS puestos el 2026-10-09) se retira una vez verificado el nuevo.

1. <https://resend.com/domains> → *Add Domain*: `send.qualify.la`, región `sa-east-1`. Resend muestra tres registros (DKIM `resend._domainkey.send` TXT, y el par de envío: MX `send` + TXT SPF `send`, o sus equivalentes CNAME). Ponerlos en la zona de Vercel **sin tocar la raíz** (los MX/SPF/DKIM de Lark viven en `@`):

   ```bash
   vercel dns add qualify.la resend._domainkey.send TXT "<valor que da Resend>"
   vercel dns add qualify.la send MX "<host feedback-smtp que da Resend>" 10
   vercel dns add qualify.la send TXT "v=spf1 include:amazonses.com ~all"   # el SPF exacto lo da Resend
   ```

   Pulsar *Verify DNS records*; la propagación tarda minutos. Después, en Resend, borrar `send.attitudefactory.co` (plan Free: un dominio) y, cuando nada lo use, sus registros en la zona de `attitudefactory.co`.
2. <https://resend.com/api-keys> → *Create API Key*: nombre `qualify-prod`, permiso **Sending access**, dominio limitado a `send.qualify.la`. La clave (`re_…`) se muestra una sola vez: guardarla en el gestor de contraseñas.
3. En `/opt/qualify/.env.prod` (o desde el Mac con `just env-push qualify-prod QUALIFY_RESEND_API_KEY QUALIFY_MAIL_FROM QUALIFY_INVITE_SIGNER QUALIFY_MAIL_REPLY_TO`, que copia esas claves del `.env` local sin mostrarlas):

   ```bash
   QUALIFY_RESEND_API_KEY=re_…
   QUALIFY_MAIL_FROM=Herwin de Qualify <no-reply@send.qualify.la>
   QUALIFY_INVITE_SIGNER=Herwin Rey
   # Opcional: con valor, la invitación dice «Responde este correo». Un buzón que alguien lea.
   QUALIFY_MAIL_REPLY_TO=herwin.rey@qualify.la
   ```

   Un cambio en `.env.prod` no recrea nada por sí solo: `dc up -d` (o el siguiente deploy) para que `api` y `reflex` lo lean.
4. Supabase → *Authentication → Emails → SMTP Settings* → **Enable Custom SMTP**: sender email `no-reply@send.qualify.la`, sender name `Qualify`, host `smtp.resend.com`, puerto `465`, usuario `resend`, contraseña = la misma API key. Al activarlo, Supabase sube el tope de correos de auth a 30/hora; se ajusta en *Authentication → Rate Limits*.
5. Supabase → *Authentication → URL Configuration → Redirect URLs*: añadir `https://qualify.attitudefactory.co/reset`, `https://app.qualify.la/reset` y `http://localhost:3100/reset` (el enlace de recuperación vuelve ahí con el token; una URL que no esté en la lista cae al Site URL y el token se pierde).
6. Comprobar: `/forgot` con un correo propio → llega desde `no-reply@send.qualify.la`; y una invitación real desde el servidor, que debe llegar al buzón (si Resend falla, el CLI imprime el enlace y el motivo —dominio sin verificar, clave inválida, cuota— queda en el log):

   ```bash
   dc run --rm -T api python -m qualify_api.auth.provision invite --email <tu correo> --name Prueba
   ```

   Cada envío aparece en <https://resend.com/emails> con su estado (delivered / bounced).
7. **Webhook de entrega** (plan `plan-altas-meegle.md`, M2): <https://resend.com/webhooks> → *Add Webhook* → *Endpoint URL* `https://app.qualify.la/api/mail/resend` (el mismo host extra del callback de Meegle, decisión D2 del plan; el proxy lo manda al mismo `api`, así que `https://qualify.attitudefactory.co/api/mail/resend` también respondería, pero se registra el de `qualify.la` para no cambiarlo tras la migración) → *Events*: marcar `email.delivered`, `email.opened` y `email.bounced` (los demás se aceptan y quedan `unsupported` en la bandeja; mejor no suscribirlos). Al crearlo, Resend muestra el **Signing Secret** (`whsec_…`): va en `/opt/qualify/.env.prod` como

   ```bash
   QUALIFY_RESEND_WEBHOOK_SECRET=whsec_…
   ```

   y luego `dc up -d` para que `api` lo lea. Sin la variable el endpoint responde **503** a cada evento (Resend reintenta y el log del `api` lo dice en ERROR); con ella, un evento mal firmado o viejo (> 5 min) es 401. Qué hace cada evento: entregado → `signup_invites.delivered_at` y, si la invitación salió de un ítem de Meegle, estado `entregada` + nodo **Invitada**; abierto → `opened_at` y estado `abierta`; rebote → `bounced_at`, estado `rebotó` y un comentario en el ítem con el motivo. Comprobar: mandar una invitación a un buzón propio y ver en <https://resend.com/webhooks> → el endpoint → *Attempts* un 200; en Meegle el ítem pasa a `entregada`. Un correo a un dominio inexistente debe dejar el ítem en `rebotó`. Nota: las recuperaciones de contraseña de Supabase salen por la misma cuenta y también disparan el webhook; no casan con ninguna invitación y se asientan `ignored:unknown_email`.

**Canva**: registrar `https://qualify.attitudefactory.co/canva/callback` y `https://qualify.attitudefactory.co/canva/return` en el portal de desarrolladores, y `QUALIFY_CANVA_REDIRECT_URI` igual a la primera.

Luego actualizar [`prioridad-despliegue-subdominio.md`](prioridad-despliegue-subdominio.md) §7 pasos 7–9 y arrancar Business Verification.

## 10. Servicios opcionales

Se activan con `COMPOSE_PROFILES` en `/opt/qualify/.env.prod` y un deploy. Para `render`, mejor el workflow (*Run workflow* con `main`) que `just deploy`: el workflow baja la imagen ya construida en CI, mientras que `just deploy` la compila en el servidor (descarga de Chrome Headless Shell incluida).

> **`calendar-worker` ya no es opcional (2026-10-21, m-24828928).** Era un perfil que nunca se activó en el servidor, y como el worker embebido de `reflex` está **forzado a `off`**, ninguna publicación programada salía en producción. Ahora es un servicio siempre activo, como `whatsapp-worker`: el ejecutor del Planificador (QUA-111) **publica de verdad**, pero sólo lo que una persona aprobó y programó. Al arrancar, su primer tick publica lo aprobado y vencido que siga dentro de la ventana de 24 h (`EXECUTION_WINDOW`); lo más viejo expira. Alcance por defecto `--all-tenants`; para limitarlo: `QUALIFY_CALENDAR_WORKER_SCOPE=--tenant=<uuid>`. Cada tick deja un latido en Redis que el Planificador lee (QUA-118), así que la pantalla muestra el servicio como disponible.

- **`render`** — servicio Remotion (Node + Chromium headless) para el generador por plantillas. Pide ~1 GB de RAM al renderizar (tope `mem_limit` de 1,5 GB, para que un render no tumbe Postgres): en un CX23 hay riesgo de quedarse sin memoria; usar CX33. Sin él, el generador por plantillas falla con error claro; el resto de la app no se entera.

## 11. Pendientes conocidos (no bloquean el despliegue)

1. ~~**El callback OAuth termina en JSON.**~~ **Resuelto (QUA-123, 2026-10-06).** `/api/connections/callback` responde siempre `303` a `/connections?connect=<código>` (`active`, `degraded`, `link_required`, `page_access_required`, `invalid_state`, `denied`) y la pantalla muestra el aviso correspondiente. En la URL sólo viaja ese código: ni ids, ni usuario, ni conteos (los conteos de páginas siguen en el log del servicio `api`). El destino sale de `QUALIFY_APP_URL` o, si no está, de `REFLEX_DEPLOY_URL`, que el compose ya fija a `QUALIFY_PUBLIC_URL`.
2. **Funciones que necesitan torch no corren en este servidor** (sentimiento de comentarios, borradores de respuesta, whisper local del Brand Kit). Para activarlas: o el grupo `ml` en la imagen (varios GB más; no cabe holgado en un CX23), o moverlas a proveedores hospedados.
3. **La API HTTP no tiene login real.** Las rutas `/api/*` que exigen `Principal` usan `QUALIFY_DEV_PRINCIPALS`; vacío = 401 (seguro). La UI no las necesita (llama a los servicios en proceso). El callback OAuth y `/public/media/*` no la usan.
4. **Nombres `DEV` en la llave maestra** (`QUALIFY_DEV_FERNET_KEY`, `QUALIFY_DEV_KEY_ID`) y default commiteado en `crypto.py`: el compose lo vuelve obligatorio, pero el código sigue cayendo a la llave de desarrollo si se ejecuta fuera de este compose. Renombrar + fail-closed en código es trabajo aparte (también lo pide `plan-cicd-staging.md` §5.4).
5. **Divergencias con [`plan-cicd-staging.md`](plan-cicd-staging.md)** (plan del mismo día, aún sin firmar): ese plan propone construir las imágenes en GitHub Actions, publicarlas en GHCR y desplegar por SSH con llave forzada desde Actions; este PR construye **en el servidor** a partir de un `git archive` lanzado desde el Mac (lo que se pidió: el fundador despliega desde su Mac, sin depender de CI ni de secretos en GitHub). El compose ya está parametrizado por `QUALIFY_IMAGE_TAG`, así que migrar a imágenes de GHCR después es cambiar `build:` por `image: ghcr.io/...` y `build` por `pull` en `deploy.sh`. Tampoco hay aún `GET /api/health` (el healthcheck usa `/openapi.json`) ni respaldo a R2.
6. **Monitoreo externo** (un ping HTTP cada 5 min desde un servicio gratuito) — no configurado.

## 12. Cómo se verificó (2026-10-05, en el Mac, sin servidor)

*(Desde 2026-10-14 el compose de producción no publica puertos: para repetir este smoke añadir `-f deploy/docker-compose.standalone.yml`, que publica el Caddy de Qualify en `QUALIFY_HTTP_PORT`, y crear una vez `docker network create qualify-edge`.)*

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
| `/api/connections/callback?code=x&state=x` | **403** `invalid or expired state` → llegó a FastAPI (no 502). *Desde QUA-123 la respuesta esperada es **303** a `/connections?connect=invalid_state`.* |
| `/public/media/<token inexistente>` | 404 desde FastAPI |
| `/avatar/tiktok/nobody`, `/r2media/<token malo>` | 200 / 404 desde el backend de Reflex (`api_transformer`) |
| WebSocket `/_event` | `101 Switching Protocols` + paquete de apertura de Engine.IO; en un navegador real, `/connections` sin sesión ejecuta su `on_load` por el websocket y redirige a `/brand/start` |
| Puertos publicados | Sólo Caddy; `postgres`/`redis`/`api`/`reflex` sin puertos en el host |
| Falta `QUALIFY_DEV_FERNET_KEY` | `docker compose` se niega a arrancar (error de interpolación) |
| Worker embebido en `reflex` | Log `calendar.embedded.off` |
| `calendar-worker` | Arranca `--all-tenants`, primer tick `tenants=0` |
| `backup-db.sh` + restauración de §8 | Dump + globals escritos; `DROP/CREATE DATABASE` + `pg_restore` recupera una fila testigo, `alembic_version = 0040` y las 48 políticas RLS |
| `caddy validate` con el dominio real | `Valid configuration` |
| Contraseñas crudas de BD dentro de `api`/`reflex` | Vacías (sólo llegan los DSN por rol; la del dueño superusuario no la tiene ningún proceso que sirve tráfico) |
| `QUALIFY_CALENDAR_WORKER_INTERVAL=45` con el perfil activo | El worker arranca con `interval=45s` |
| `deploy.sh deploy HEAD` en un "servidor" vacío (con un `ssh` de prueba que ejecuta en local) | `git archive` → release → build → migrate → `up` → `current` → los tres chequeos `ok`, salida 0 |
| `deploy.sh deploy` con `.env.prod` roto (sin llave Fernet) | Falla con salida 1 y `current` **sigue** en el release anterior, que sigue sirviendo |
| `deploy.sh status` / `deploy.sh backup` (mismo `ssh` de prueba) | `ok` en los tres chequeos y salida 0; si un chequeo no da el código esperado, `FAIL` y salida ≠ 0 (camino ejercitado en la primera corrida, que además destapó un fallo con arreglos vacíos en bash 3.2, ya corregido) |

No verificado localmente: la emisión real del certificado (requiere DNS apuntando al servidor), el build en x86 del servidor (aquí fue arm64), el perfil `render` (su imagen no se construyó en esta sesión) y `deploy.sh` a través de un ssh real (se probó con un `ssh` de prueba que ejecuta los mismos comandos en local).

## 13. Claude Code en el servidor (Remote Control)

**Decisión del fundador, 2026-10-12:** una sesión de Claude Code corre **en el servidor**, como el usuario `deploy`, y se maneja desde claude.ai/code o la app móvil de Claude con *Remote Control*, para operar producción (estado, logs, diagnóstico, reinicios, rollbacks, respaldos) sin abrir el Mac. Se evaluaron tres modelos — usuario restringido a un script fijo, sin Claude en el VPS, y Claude como `deploy` — y se eligió el último a sabiendas de lo que implica:

- `deploy` está en el grupo `docker`, que **equivale a root**: Claude puede leer `.env.prod`, la base de datos con datos de clientes y cualquier volumen. Lo que lee viaja a Anthropic como parte de la conversación.
- La sesión entra con la cuenta **Pro/Max personal** del fundador: quien acceda a esa cuenta de claude.ai maneja producción. Conviene tener 2FA activo en ella.
- Las reglas de `/etc/claude-code/managed-settings.json` (instaladas por el script) son **cinturón contra accidentes, no frontera de seguridad**: la documentación de Claude Code aclara que las reglas de Bash comparan texto, no el programa que corre. Bloquean lo obvio — `down -v`, `docker volume rm/prune`, `system prune`, `DROP DATABASE`, leer o editar `.env.prod` — y desactivan el modo `bypassPermissions`, así que cada comando que cambia algo pide aprobación (desde el móvil, un toque).
- Si un día hace falta que el modelo sea frontera de verdad, el camino es el modelo descartado: usuario `claude` sin `docker`, con `sudo -u deploy` sólo sobre un script fijo, igual que la llave del CI (§7.1).

**Qué se instala** (`deploy/bootstrap-claude.sh`, idempotente): `tmux`; Claude Code para `deploy` con el instalador nativo oficial (`~deploy/.local/bin/claude`, se actualiza solo); `qdc`, el alias `dc` de §7 convertido en comando (los alias no existen en el shell no interactivo de Claude); `qualify-claude`, que arranca o re-engancha la sesión en `tmux`; los *managed settings*; y `/opt/qualify/CLAUDE.md` (fuente: `deploy/claude-server.md`), con las reglas de operación que Claude lee al arrancar.

**Montaje (una vez):**

1. Desde el Mac, con el alias que entra como **root**:
   ```bash
   just claude-bootstrap qualify-prod
   ```
2. Iniciar sesión — es interactivo y no se puede automatizar (Remote Control no acepta API key ni el token de `claude setup-token`):
   ```bash
   ssh deploy@<IP>
   claude          # dentro: /login → tecla c copia la URL → abrirla en el navegador del Mac → pegar el código
   ```
   Salir con `/exit`.
3. Arrancar la sesión remota, en el mismo ssh:
   ```bash
   qualify-claude
   ```
   La primera vez pregunta si habilitar Remote Control (`y`) y si confiar en `/opt/qualify` (`y`). Muestra una URL y un QR. Desengancharse con **Ctrl-b d**: la sesión sigue viva en `tmux` al cerrar el ssh.
4. En claude.ai/code o en la app móvil aparece la sesión **`qualify-prod`**.

**Operación:**

| Situación | Qué hacer |
|---|---|
| Volver a la terminal de la sesión | `ssh deploy@<IP>` → `qualify-claude` (re-engancha) |
| La red se cayó más de ~10 min y la sesión desapareció | `qualify-claude --continue` (retoma la conversación; funciona durante ~4 h) |
| Reinicio del servidor | La sesión **no** vuelve sola: `qualify-claude` de nuevo |
| Aviso de que el login vence (llega con 3 días) | En la sesión, `/login` otra vez; si vence, Remote Control se detiene hasta re-loguear |
| Cambiar las reglas de Claude | Editar `deploy/bootstrap-claude.sh` / `deploy/claude-server.md` en el repo y repetir `just claude-bootstrap qualify-prod` |
| Quitarlo | `ssh deploy@<IP> 'tmux kill-session -t claude; ~/.local/bin/claude logout'` |

**Límites:**
- Desde el servidor Claude sólo puede desplegar shas cuyas imágenes **ya están en GHCR** (`/opt/qualify/bin/server-deploy.sh deploy|rollback <sha>`): un commit nuevo de `main` lo despliega el workflow `deploy` (§7.1). No hay checkout del repo ni credenciales de GitHub en el servidor, a propósito.
- Requisitos que la documentación de Remote Control impone y conviene no romper: no exportar `ANTHROPIC_API_KEY` en el entorno de `deploy` (bloquea Remote Control), ni `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`. Sólo usa HTTPS saliente: no hay que abrir puertos ni tocar `ufw`.
- Memoria: el proceso de Claude Code ocupa unos cientos de MB; en un CX23 con el stack completo hay margen, con el perfil `render` activo, vigilar `free -h`.
- **Sin verificar todavía contra un servidor real** (se escribió el 2026-10-12 desde el Mac): que `remote-control` aplique los *managed settings* a sus sesiones (es lo esperado, son procesos locales) y que la app de escritorio de Claude pueda engancharse a la sesión (la documentación sólo nombra claude.ai/code y la app móvil).
