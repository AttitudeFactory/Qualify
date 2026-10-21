# Plan — entornos (dev · QA · producción), R2 por entorno y datos «casi reales» para reproducir bugs

**Estado:** `[DISCOVERY 2026-10-21 · m-24823878]` — encargo del fundador del mismo día: *«revisemos toda la arquitectura y devops… no he revisado nada sobre R2, ni tenemos instancia de QA (`qa.qualify.la`), todos los developers usan las API keys de producción de R2; quiero agilizar las pruebas con datos lo más parecidos a producción para replicar bugfixes»*. Nada de esto está implementado.
**Convención:** `[M]` = medido hoy en el repo; `[H]` = hipótesis o estimación; `[?]` = estado del servidor o de una consola que la sesión no puede ver — **confirmar a mano antes de actuar**.
**Docs que continúa (no repite):** [`despliegue-hetzner.md`](despliegue-hetzner.md) (runbook de producción), [`plan-sre-devops-produccion.md`](plan-sre-devops-produccion.md) (CD, cero caída, monitoreo), [`plan-cicd-staging.md`](plan-cicd-staging.md) (CI a costo cero, respaldos a R2 con `age`), [`backlog-retencion-datos-r2.md`](backlog-retencion-datos-r2.md) (ciclo de vida de los objetos).

---

## 0. Resumen en cinco líneas

1. **Hoy hay un solo entorno real** (`qualify.attitudefactory.co` + `app.qualify.la`, un CX23 en Hetzner compartido con Pedidos) y **un solo bucket de R2 con una sola llave**, que también usa cada developer en su `.env` local `[M: el código no distingue entorno; el fundador lo confirma]`.
2. Eso significa que **cualquier portátil de desarrollo puede leer, sobrescribir y llenar de basura el media de todos los clientes**, y que lo que un dev prueba en local queda escrito en el bucket de producción.
3. No existe QA: un bugfix se valida en local con datos de seed (que no se parecen a producción) o directamente en producción.
4. Propuesta: **tres entornos con nombre** (`dev`, `qa`, `prod`), **un bucket y una llave de R2 por entorno**, **QA en `qa.qualify.la`** desplegado con **las mismas imágenes de GHCR** que producción, y una receta **`just qa-refresh`** que copia producción → QA **anonimizada** (base + media de los tenants elegidos).
5. Más 12 puntos para llegar a una producción estable (§6), resumidos en el ticket de Meegle.

---

## 1. R2 en dos minutos (para quien no viene de Cloudflare)

| Concepto | Qué es | Cómo lo usa Qualify hoy |
|---|---|---|
| **R2** | Almacenamiento de archivos («objetos») de Cloudflare, **compatible con la API S3 de Amazon**: el código usa `boto3` como si fuera S3. Sin cargo por descarga (egress $0); se paga almacenamiento + operaciones | `packages/shared/src/qualify_shared/objects/` (`R2ObjectStore`, la **única** puerta: un test estático prohíbe crear clientes S3 en otro sitio) `[M]` |
| **Bucket** | Un «disco» con nombre. Los permisos y las reglas de borrado automático (lifecycle) se ponen **por bucket** | Uno solo, el de `QUALIFY_R2_BUCKET` `[M]` |
| **Clave (key)** | La ruta del archivo dentro del bucket | Siempre `t/{tenant_id}/…` — el equivalente de RLS para archivos; el `ObjectGate` rechaza cualquier clave fuera del prefijo del tenant `[M]` |
| **API token** | Par *Access Key ID* + *Secret*. En R2 se crea con permiso (**Object Read** u **Object Read & Write** o *Admin*) y se puede **limitar a uno o varios buckets** | Uno, con permiso de escritura, compartido entre producción y los devs `[?]` |
| **Acceso público / dominio propio** | Un bucket puede servirse en un dominio público | **No se usa, a propósito** (ADR 28e): el navegador ve el media a través de `/r2media/<token>` (Reflex) y Meta lo descarga por `/public/media/<token>` (FastAPI); tokens de 1 h guardados en Redis. Nunca URLs presignadas |
| **Lifecycle rules** | Reglas «borrar lo que tenga más de N días bajo este prefijo», las ejecuta Cloudflare | Ninguna todavía; propuestas en `backlog-retencion-datos-r2.md` (RET-02) |
| **Cloudflare Images / Stream** | Productos **aparte** de R2: Images redimensiona y convierte imágenes al vuelo; Stream codifica video y lo sirve adaptativo (HLS) | No se usan. **No hacen falta hoy** (ver §5) |

Qué vive en R2 hoy `[M]`: piezas generadas por el Motor de Contenido, media preparado para publicar en Meta (`publishing/staging.py`), stock importado (Pexels/Pixabay), avatar y voz de marca, Brand Kit terminado, media saliente de WhatsApp y de Conversaciones.

Qué **no** vive en R2 y debería saberse `[M]`: los **documentos del Brand Kit** (`Qualify/brand_documents.py`) y el staging del **catálogo** (`Qualify/catalog_state.py`) se escriben en el disco local de Reflex (`uploaded_files`, volumen `uploads` en producción). Ese volumen **no entra en `backup-db.sh`** (sólo hace `pg_dump`) y **no se puede copiar a QA** con las herramientas de R2.

---

## 2. Hallazgos

### 2.1 R2

| # | Hallazgo | Riesgo | Evidencia |
|---|---|---|---|
| R-1 | **Una sola llave de R2 para producción y para todos los devs** | Un portátil perdido, un `.env` pegado en un chat o un script mal escrito alcanza el media de **todos** los tenants (leer, sobrescribir; borrar si la llave lo permite). Rotarla rompe a todos a la vez | Pedido del fundador; `R2Settings.from_env()` lee las mismas 4 variables en todos los entornos `[M]` |
| R-2 | **Lo que un dev prueba en local se escribe en el bucket de producción** | Basura huérfana bajo `t/<uuid-de-tenant-local>/…` que nadie puede atribuir ni limpiar; ensucia cualquier métrica de costo (RET-07) | Los tenants locales tienen otros UUID que los de producción, así que no se pisan, pero se acumulan `[H]` |
| R-3 | El código **no sabe en qué entorno corre** | No hay forma de que un worker se niegue a enviar en QA, ni de que un banner diga «esto es QA» | No existe `QUALIFY_ENV` ni nada equivalente `[M]` |
| R-4 | Archivos de cliente en disco local sin respaldo | Si el disco del CX23 muere, los documentos del Brand Kit se pierden aunque la base se recupere | §1, `backup-db.sh` `[M]` |
| R-5 | Sin reglas de lifecycle, sin política de retención firmada | Costo sin techo (hoy pequeño) y objetos colgados tras publicar | `backlog-retencion-datos-r2.md` sigue `[PROPUESTO]` `[M]` |
| R-6 | Los respaldos de Postgres viven en el mismo disco que la base | Un respaldo que muere con el servidor no es respaldo | `despliegue-hetzner.md` §8, §11 `[M]`; si hay `rsync` manual o backups de Hetzner activos `[?]` |

### 2.2 Entornos, despliegue y operación

| # | Hallazgo | Evidencia |
|---|---|---|
| E-1 | **No hay QA.** Un fix se prueba en local con seed (2 tenants sintéticos) o en producción | `just seed`, `conversations-seed` son datos de juguete `[M]` |
| E-2 | Producción despliega **directo desde `main`** (diario desde el 2026-11-12; por merge hasta entonces): no hay un paso intermedio donde mirar el cambio con datos reales | `.github/workflows/deploy.yml`, variable `QUALIFY_AUTO_DEPLOY` `[M]` |
| E-3 | El CD sólo conoce **un** destino (`QUALIFY_DEPLOY_SSH_TARGET`) | `deploy.yml` `[M]` — añadir QA es un segundo juego de secretos y un input `environment` |
| E-4 | Proveedores externos probablemente compartidos entre dev y producción: **Meta** (una app, `1670943920870196`), **Supabase** (un proyecto), **Anthropic / BytePlus / Pexels / Resend** (una llave) | `.env.example` no separa por entorno `[M]`; qué llave tiene cada dev `[?]` |
| E-5 | Tres procesos **envían de verdad** (calendario, WhatsApp, DMs). Una copia de producción con esas credenciales en QA publicaría en cuentas reales de clientes | `CLAUDE.md` §Commands `[M]` |
| E-6 | La llave maestra de credenciales se llama `QUALIFY_DEV_FERNET_KEY` y el código cae a una llave **commiteada** si falta | `connections/crypto.py:22,42` `[M]`; el compose de prod la exige, pero el código no |
| E-7 | Sin rastreo de errores (Sentry o similar), sin monitoreo externo, sin `GET /api/health` | grep sin resultados `[M]`; `despliegue-hetzner.md` §11.6 |
| E-8 | El CX23 (4 GB) aloja producción **y** Pedidos; el perfil `render` (Remotion) sigue apagado por falta de memoria; las funciones con torch fallan al usarse | `plan-sre-devops-produccion.md` §2, `despliegue-hetzner.md` §11.2 `[M]`; si se pasó a CX33 `[?]` |
| E-9 | Claude Code corre en el servidor como `deploy` (grupo `docker` = root) con acceso a `.env.prod` y a la base | Decisión consciente del 2026-10-12 (`despliegue-hetzner.md` §13). Se anota porque con datos reales de clientes merece revisarse junto con los demás secretos |
| E-10 | Dominio canónico todavía `qualify.attitudefactory.co`; `qualify.la` sólo como host extra | `despliegue-hetzner.md` §1.1 `[M]` |

---

## 3. Propuesta: tres entornos con nombre

| | **dev** (cada portátil) | **qa** (`qa.qualify.la`) | **prod** (`app.qualify.la` / `qualify.attitudefactory.co`) |
|---|---|---|---|
| Para qué | Escribir código | Reproducir un bug con datos casi reales; validar un fix antes de producción; demos | Clientes |
| Host | Docker local (`just dev`) | **VPS propio** (recomendado, ver D1) | CX23/CX33 actual |
| Imágenes | Build local | **Las mismas `ghcr.io/attitudefactory/qualify-*:<sha>`** que irán a prod | Promovidas desde QA |
| Base de datos | Seed **o** snapshot anonimizado de QA (`just dev-snapshot`, §4.4) | Copia anonimizada de prod, refrescada a demanda o semanal | Real |
| Bucket R2 | `qualify-dev` (lectura/escritura) + **lectura** de `qualify-qa` | `qualify-qa` | `qualify-prod` |
| Llave R2 | Una por dev, sólo `qualify-dev` RW + `qualify-qa` R | Sólo `qualify-qa` RW (+ `qualify-prod` **R** en el job de refresco, nunca en la app) | Sólo `qualify-prod` RW, **sólo en el servidor** |
| Meta | App de prueba (*Test App* de la app principal) o modo `memory` | App de prueba, cuentas propias de Attitude | App real |
| Supabase | Proyecto `qualify-dev` (o `QUALIFY_AUTH_FAKE=1`) | Proyecto `qualify-qa` | Proyecto actual |
| Workers que envían | Apagados (o `memory`) | **Apagados por defecto**; si se encienden, sólo con allowlist de tenants internos | Encendidos |
| `QUALIFY_ENV` | `dev` | `qa` | `prod` |

Más un bucket **`qualify-backups`** (sólo escritura desde el servidor de prod, con lifecycle 14 d + 8 sem), que es lo que `plan-cicd-staging.md` §5.6 ya proponía.

### 3.1 `QUALIFY_ENV` — que el código sepa dónde está

Variable obligatoria en el compose de prod y QA. Usos mínimos:
- **Guardas al arrancar:** en `qa`/`prod`, abortar si falta `QUALIFY_DEV_FERNET_KEY` (y renombrarla a `QUALIFY_CREDENTIAL_KEY`), si aparece `QUALIFY_AUTH_FAKE` / `QUALIFY_SIGNUP_OPEN` / `QUALIFY_DEV_PRINCIPALS`, o si **el bucket no termina en `-<env>`** (atrapa el error de pegar la llave equivocada, que es justo R-1).
- **Guardas de envío:** en `qa`, los workers de calendario, WhatsApp y DMs sólo actúan sobre `QUALIFY_SEND_ALLOWLIST_TENANTS`; vacío = no envían.
- **Banner** «QA — datos anonimizados» en la barra superior, y `LANGFUSE_TRACING_ENVIRONMENT` derivado de ella.

### 3.2 Dónde corre QA (decisión D1)

| Opción | Costo `[H]` | A favor | En contra |
|---|---|---|---|
| **A. VPS aparte (CX23)** — recomendada | ~€6–7/mes (precio de `plan-cicd-staging.md` §5.8, verificar) | Aislamiento real: un QA que se queda sin memoria o un refresco pesado no toca a clientes; se puede romper y recrear | Un servidor más que mantener (mismo `bootstrap-server.sh`) |
| B. Mismo VPS, otro proyecto Compose | €0 | Ya hay proxy de entrada multi-producto (`/opt/edge`) | El CX23 ya va justo con prod + Pedidos; QA con datos de prod duplica RAM y disco; un error de `docker compose -p` pega a prod |
| C. Entornos efímeros por PR | Más alto y más trabajo | Lo ideal a futuro | Prematuro con el equipo actual |

### 3.3 Flujo de despliegue con QA

```
PR verde ──► merge a main ──► CD construye qualify-{app,web,deploy}:<sha> en GHCR (una sola vez)
                                   │
                                   ├──► deploy a QA automático (cada merge)  ── smoke + prueba manual del fix
                                   │
                                   └──► «promover <sha> a prod» (workflow_dispatch, o diario con el último sha sano en QA)
```

Cambios: `deploy.yml` gana un input `environment: qa|prod` y dos juegos de secretos (`QUALIFY_DEPLOY_SSH_TARGET_QA`, …); `QUALIFY_AUTO_DEPLOY` pasa a gobernar QA, y prod se despliega sólo con un sha que ya pasó por QA. Sin GitHub Team no hay *environment secrets*; los secretos se distinguen por nombre (como ya se hace).

---

## 4. Datos «casi reales» para reproducir bugs

### 4.1 Principio

Nunca se copia producción tal cual. Se copia **la forma** de los datos (tenants, marcas, borradores, calendario, conversaciones, media) y se **destruye lo que identifica personas o da acceso**.

### 4.2 `just qa-refresh` (corre contra QA, nunca contra prod)

1. **Base:** tomar el `pg_dump` nocturno más reciente de `qualify-backups` (no se abre conexión nueva a prod) → `pg_restore` en el Postgres de QA → `alembic upgrade head` (QA puede ir por delante de prod).
2. **Anonimizar** con un script SQL versionado (`deploy/qa/anonymize.sql`) que corre **antes** de levantar la app:

   | Qué | Cómo |
   |---|---|
   | `oauth_credentials` (tokens de Meta/WhatsApp/Canva) | **Borrar.** Además QA usa otra llave Fernet, así que aunque quedara algo sería ilegible. Conexiones → estado `revoked` |
   | Usuarios (emails, nombres, teléfonos) | Reescribir a `qa+<hash>@qualify.la`; los usuarios internos de Attitude se conservan para poder entrar |
   | Contactos, mensajes de WhatsApp/DM, comentarios | Nombres y teléfonos → sintéticos; el **texto** se conserva sólo para tenants internos/de demo, el resto se reemplaza por texto genérico de igual longitud `[H: decidir con el fundador, D3]` |
   | Webhooks pendientes, outbox, `scheduled_posts` futuros | Vaciar o marcar cancelados (nada «pendiente de enviar» llega vivo a QA) |
   | Tokens de `/public/media` y `/r2media` | Viven en Redis: QA tiene su propio Redis vacío |
   | Invitaciones, secretos de webhook de Meegle/Resend | Borrar |

3. **Media:** copiar de `qualify-prod` a `qualify-qa` **sólo los prefijos `t/<tenant_id>/` de los tenants elegidos** (por defecto los internos/de demo; uno concreto con `--tenant <uuid>` cuando el bug es de ese cliente). Como las claves ya están particionadas por tenant (ADR 22), es un `rclone copy r2prod:qualify-prod/t/<uuid>/ r2qa:qualify-qa/t/<uuid>/` — copia servidor a servidor, sin pasar los bytes por un portátil. El job usa una llave **de sólo lectura** sobre `qualify-prod` que vive únicamente en el servidor de QA.
4. **Verificar:** chequeo automático de que no queda ningún email ajeno a `@qualify.la`/allowlist, ninguna fila en `oauth_credentials`, ningún `scheduled_posts` futuro en estado programado.

### 4.3 Reproducir un bug de un cliente concreto

`just qa-refresh --tenant <uuid>` → abrir `qa.qualify.la`, entrar con un usuario interno al que el script dio acceso a ese tenant → reproducir → fix en una rama → el merge lo despliega en QA → comprobar ahí → promover a prod. La copia de un tenant real a QA debe quedar **registrada** (quién, cuándo, qué tenant) y QA no debe guardar más de N días de ese tenant `[H]`.

### 4.4 En local (`just dev-snapshot`)

- Descarga el último dump **ya anonimizado** de QA (no de prod) y lo restaura en el Postgres local.
- Para el media: la llave del dev lee `qualify-qa` y escribe en `qualify-dev`. Implementación propuesta, pequeña: un `ReadThroughObjectStore` en `qualify_shared/objects/` que lee primero de `qualify-dev` y, si no está, de `qualify-qa` (sólo lectura); toda escritura va a `qualify-dev`. Respeta la regla «un solo módulo construye clientes S3» y el `ObjectGate` no cambia.
- Así ningún portátil vuelve a tener una llave de producción.

---

## 5. ¿Hace falta Cloudflare Images o Stream?

**Hoy no.** El volumen es pequeño, el media se sirve con tokens cortos por `/r2media` y el destino real del video es Meta, no el navegador. Señales para reabrirlo `[H]`:
- **Stream** si el navegador empieza a reproducir mucho video largo (el backend de Reflex está haciendo de servidor de video con Range requests; con muchos usuarios eso compite con el websocket).
- **Images** si las pantallas cargan miniaturas a tamaño completo (listas, calendario) y se nota en la carga. Alternativa más barata: generar la miniatura una vez al subir (Pillow ya se usa para normalizar) y guardarla en R2 junto al original.

---

## 6. Camino a una producción estable y ordenada (checklist del ticket)

Ordenado por riesgo; cada fase deja algo usable. Épica en Meegle: **Épica — Entornos dev/QA/prod, R2 por entorno y producción estable** (`story/detail/24824104`), con un Issue por entrega:

| Punto | Issue | Prioridad | Bloqueado por |
|---|---|---|---|
| Este discovery | m-24823878 | P1 | — |
| 1–2 R2: bucket y llave por entorno, rotar la de producción | m-24824121 | P1 | — |
| 2 Secretos de proveedores por entorno (+ Claude Code en el servidor, punto 12) | m-24828494 | P2 | — |
| 3 Respaldos fuera del servidor | m-24824122 | P1 | — |
| 4 `QUALIFY_ENV` y guardas | m-24828495 | P1 | — |
| 5 Instancia de QA en `qa.qualify.la` | m-24828498 | P1 | m-24828495, m-24824121 |
| 6 CD por entorno y promoción | m-24828499 | P2 | m-24828498 |
| 7a `just qa-refresh` + anonimización | m-24828500 | P1 | m-24824122, m-24828498 |
| 7b `just dev-snapshot` + `ReadThroughObjectStore` | m-24828502 | P2 | m-24828500 |
| 8 Rastreo de errores, `/api/health`, monitoreo | m-24828503 | P2 | — |
| 9 Capacidad y `mem_limit` | m-24828504 | P2 | — |
| 10 Retención y lifecycle de R2 | m-24828505 | P2 | m-24824121 |
| 11 Runbooks | m-24828506 | P3 | m-24824122, m-24828494 |
| 12 Dominio canónico `app.qualify.la` | m-24828507 | P3 | — |

**Fase 0 — contener el riesgo (esta semana)**
1. Crear buckets `qualify-dev`, `qualify-qa`, `qualify-backups`; renombrar o mantener el actual como `qualify-prod` (renombrar exige copiar: se puede dejar el nombre y documentarlo).
2. Llaves nuevas por entorno y por dev (§3), limitadas a su bucket. **Rotar la llave actual** y que quede sólo en `/opt/qualify/.env.prod`. Inventario de qué otras llaves de producción tienen los devs (Meta secret, Anthropic, BytePlus, Supabase secret, Resend) y separarlas donde el proveedor lo permita.
3. Respaldos fuera del servidor: `backup-db.sh` sube el dump cifrado con `age` a `qualify-backups` (llave privada fuera del servidor); incluir el volumen `uploads` o mover documentos del Brand Kit y catálogo a R2. Confirmar backups de Hetzner activos.

**Fase 1 — QA**
4. `QUALIFY_ENV` + guardas de arranque y de envío (§3.1); renombrar `QUALIFY_DEV_FERNET_KEY` y quitar el default commiteado del camino de `qa`/`prod`.
5. VPS de QA, DNS `qa.qualify.la`, `.env.qa`, Supabase y Meta de prueba, Resend con remitente de QA (o sin correo).
6. `deploy.yml` con `environment: qa|prod`; auto-deploy a QA en cada merge; prod sólo promueve shas que pasaron por QA.
7. `just qa-refresh` + `anonymize.sql` + verificación (§4.2); `just dev-snapshot` + `ReadThroughObjectStore` (§4.4).

**Fase 2 — producción estable**
8. Observabilidad mínima: rastreo de errores (Sentry o GlitchTip autoalojado — decisión con tabla de opciones), `GET /api/health`, monitoreo externo de `/ping` y `/api/health` con aviso al grupo Qualify-devs de Lark.
9. Capacidad: decidir CX23 → CX33 (o separar Pedidos) para habilitar `render` y dar margen; `mem_limit` por servicio para que un render no tumbe Postgres.
10. Política de retención de R2 firmada (RET-01/RET-08) y reglas de lifecycle **versionadas en el repo** (Terraform/wrangler), no clicadas en el dashboard; métrica de GB y objetos por prefijo (RET-07).
11. Runbooks: restaurar un respaldo (simulacro mensual con fecha), rotar cada llave, dar de baja a un dev, incidente «producción caída».
12. Revisar el acceso de Claude Code en el servidor de prod con la nueva separación de secretos (§2.2 E-9), y migrar el dominio canónico a `app.qualify.la` cuando Meta/Supabase/Canva lo tengan registrado.

---

## 7. Decisiones del fundador

1. **D1 — Host de QA:** VPS aparte CX23 (recomendado) · mismo VPS · efímeros por PR.
2. **D2 — Cadencia de prod:** promover sólo shas que pasaron por QA (recomendado) · seguir desplegando prod directo desde `main`.
3. **D3 — Texto de conversaciones de clientes en QA:** sólo tenants internos/demo con texto real (recomendado) · todos los tenants con texto real · nunca texto real.
4. **D4 — ¿Quién puede copiar un tenant real a QA?** Sólo el fundador (recomendado al principio) · cualquier dev con registro.
5. **D5 — Rastreo de errores:** Sentry (plan gratuito, datos fuera) · GlitchTip autoalojado (otro servicio a operar).
6. **D6 — Capacidad de producción:** CX33 · separar Pedidos · quedarse en CX23 sin `render`.
