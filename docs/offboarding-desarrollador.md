# Offboarding de un desarrollador

`[VIGENTE 2026-10-24 · m-24852085 · m-24852090]` · Procedimiento genérico y reutilizable para cuando un
desarrollador deja Qualify. No se refiere a nadie en concreto. El inventario de accesos sale de
lo que el repo nombra hoy (`deploy/`, `.github/`, `justfile`, `.env.example`,
`deploy/.env.prod.example`, `docs/despliegue-hetzner.md`). Si el repo suma un sistema nuevo,
súmalo también aquí.

## 1. Cuándo se usa y quién hace cada cosa

Se usa siempre que un desarrollador (de planta, contratista o pasante) deja de trabajar en
Qualify, o cuando cambia a un rol sin acceso técnico (por ejemplo, el departamento Nexo).
Una salida urgente (desconfianza o incidente) se salta el §2: se ejecutan §3 y §4 el mismo día,
en ese orden.

| Rol | Quién | Qué hace |
|---|---|---|
| Aprueba y ejecuta | **Herwin** (fundador) | Decide la fecha. Es dueño de la organización de GitHub, de Hetzner, de Meta, de los proveedores y de `.env.prod`. Ejecuta todo lo marcado **[F]**. |
| Ejecuta Lark | **Darwin** (cofundador, super admin de Lark) | Ejecuta lo marcado **[D]**: baja en Lark, traspaso de documentos y bots del grupo. |
| Apoyo | agente `platform-engineer` | Verificaciones de solo lectura, `just env-push` **después del sí del fundador** y el registro (§5.3). Nunca revoca accesos de personas. |

## 2. Antes de la conversación (48 h antes)

El objetivo es que nada quede solo en la cabeza o en la máquina de la persona. Se hace con ella
si la salida es amistosa; si no, lo hace quien hereda el trabajo.

1. **Módulos.** Ver qué es suyo en `docs/equipo-agentes.md` y en `git log --since=90.days --author="<nombre>" --name-only --format= | sort | uniq -c | sort -rn | head -30`. Asignar un heredero por módulo.
2. **PRs abiertos:** `gh api "repos/AttitudeFactory/Qualify/pulls?state=open&per_page=100" --jq '.[]|select(.user.login=="<login>")|"\(.number) \(.title)"'`. Para cada uno se decide si se mergea (CI verde, `just merge`), lo hereda alguien o se cierra con un comentario que explique por qué.
3. **Ramas remotas sin PR:** `git fetch --prune && git for-each-ref --format='%(authorname) %(refname:short)' refs/remotes/origin | grep -i "<nombre>"`. Las que valgan la pena se convierten en PR borrador o se documentan. Se borran solo después de la salida.
4. **Tickets de Meegle:** en el espacio Qualify, la vista con `Assignee = <persona>` y estado distinto de Done. Se reasigna cada uno (Assignee y Reporter, porque solo ellos pueden mover el estado). Hacerlo **antes** de quitarle el espacio, porque después su nombre ya no aparece para filtrar.
5. **Conocimiento no escrito.** Una sesión de 60 min, grabada en Lark, con estas preguntas:
   - ¿Qué haces a mano que no esté en un `just` ni en un doc? (llaves locales, scripts sueltos, workarounds del venv)
   - ¿Qué cuenta de proveedor creaste tú o está a tu nombre? (el §3 lo confirma)
   - ¿Qué tests o servicios sabes que fallan a veces, y por qué?
   - ¿Qué decisión pendiente o deuda conoces que no tenga ticket?
   - ¿Qué cliente o tenant atiendes y qué le prometiste?

   Las respuestas van **a `docs/`** en el doc del módulo (sección «Notas de traspaso»), con un
   ticket por cada deuda nueva. La grabación sola no cuenta como traspaso.
6. **Archivos locales.** Pedir que confirme qué tiene en su máquina: `.env` con valores de
   producción, `~/.ssh/qualify_*`, dumps de la base (`/opt/qualify/backups` copiados con
   `rsync`), exportaciones de Meegle/Lark. Lo que tenga se borra y lo confirma por escrito. Lo
   que vio sigue en el §3: borrar el archivo no reemplaza rotar el secreto.

## 3. Inventario de accesos y revocación

**ROTAR** = la persona vio o pudo copiar el valor: se cambia el secreto (orden en el §4).
**QUITAR** = basta con sacar su cuenta, porque el secreto no pasó por sus manos.
Regla práctica: **si alguna vez corrió `just env-push` o `just deploy`, tuvo en su `.env` local
los valores de producción, así que todo el bloque B se rota.** Si solo trabajó con el `.env` de
desarrollo, en el bloque B rotas únicamente las llaves de desarrollo compartidas que tenía.

### A. GitHub (organización `AttitudeFactory`) **[F]**

| Acceso | Cómo se ve / se quita | Acción |
|---|---|---|
| Miembro de la organización | `gh api orgs/AttitudeFactory/members --jq '.[].login'` → `gh api -X DELETE orgs/AttitudeFactory/memberships/<login>` | QUITAR |
| Colaborador externo / del repo (`Qualify` y el repo de la landing en Vercel) | `gh api orgs/AttitudeFactory/outside_collaborators --jq '.[].login'`; `gh api repos/AttitudeFactory/<repo>/collaborators --jq '.[].login'` → `gh api -X DELETE repos/AttitudeFactory/<repo>/collaborators/<login>` | QUITAR |
| Invitaciones pendientes | `gh api orgs/AttitudeFactory/invitations` → `gh api -X DELETE orgs/AttitudeFactory/invitations/<id>` | QUITAR |
| Deploy keys del repo | `gh api repos/AttitudeFactory/Qualify/keys --jq '.[]\|"\(.id) \(.title)"'` → borrar las que haya creado: `gh api -X DELETE repos/AttitudeFactory/Qualify/keys/<id>` | QUITAR |
| Tokens *fine-grained* aprobados por la organización | `gh api orgs/AttitudeFactory/personal-access-tokens --jq '.[]\|select(.owner.login=="<login>")'` (en GitHub Free puede responder 404: entonces revisar *Org Settings → Personal access tokens*) | QUITAR |
| **Token *classic* `read:packages` con el que el servidor hace `docker login ghcr.io`** (`docs/despliegue-hetzner.md` §7.1, paso 4) | Ver de quién es: el login vive en `/home/deploy/.docker/config.json` (root no tiene). Por `ssh qualify-prod`, decodificar con `python3` el campo `auths["ghcr.io"].auth` y quedarse solo con lo que va antes de `:` (el servidor no tiene `jq`; nunca imprimir el resto). Resultado del 2026-10-24 en el §7. Si es de la persona, al sacarla de la org **los deploys dejan de bajar imágenes** | ROTAR antes de quitarla: token nuevo del fundador (§4, paso 2) |
| Secretos de Actions: `QUALIFY_DEPLOY_SSH_KEY`, `_TARGET`, `_KNOWN_HOSTS`, `DEVOPS_WEBHOOK_URL`, `DEVOPS_WEBHOOK_SECRET`, `CLAUDE_CODE_OAUTH_TOKEN` (los únicos que existían el 2026-10-24; `ANTHROPIC_API_KEY`, `SONAR_TOKEN` y `SONAR_HOST_URL` los nombran los workflows, pero no están creados) | `gh api repos/AttitudeFactory/Qualify/actions/secrets --jq '.secrets[].name'`. Un miembro con escritura no los lee, pero un workflow en una rama sí podría exfiltrarlos | ROTAR los que haya manejado o si tuvo escritura y hay sospecha; si no, QUITAR basta |
| `CLAUDE_CODE_OAUTH_TOKEN` | Ligado a la suscripción Claude Max **de quien corrió `claude setup-token`** (`docs/calidad-codigo-revision-automatica.md` §2.1). Si fue la persona, la revisión `claude-review` gasta su cuota y muere con su cuenta | ROTAR con un token del fundador |
| `CODEOWNERS` | Hoy solo `@hlrd93`; si se agregó a la persona, quitarla en un PR | QUITAR |

### B. Producción en Hetzner (VPS compartido con Pedidos) **[F]**

| Acceso | Cómo se ve / se quita | Acción |
|---|---|---|
| Llave SSH en `deploy` y `root` (`just deploy` entra como root) | `ssh qualify-prod 'ssh-keygen -lf ~/.ssh/authorized_keys'` y lo mismo como root. Quitar su línea con el fundador presente. **Nunca** la línea `command="/opt/qualify/bin/server-deploy.sh",restrict … qualify-ci-deploy` | QUITAR. Con root, avisar al dueño de Pedidos (su acceso también llegaba ahí) |
| Llave de CI `qualify_ci_deploy` | Si la persona la generó o tuvo la privada: par nuevo (§7.1, pasos 1 y 3) y `QUALIFY_DEPLOY_SSH_KEY` nuevo | ROTAR solo si la tuvo |
| Consola de Hetzner (proyecto «Qualify») | console.hetzner.cloud → proyecto → *Security → Members* | QUITAR |
| Sesión remota de Claude `qualify-prod` | Corre con la cuenta del fundador. Solo hay que revisar si se le compartió | QUITAR (si aplica) |
| `.env.prod`: `QUALIFY_SUPABASE_SECRET_KEY`, `QUALIFY_RESEND_API_KEY`, `QUALIFY_RESEND_WEBHOOK_SECRET`, `QUALIFY_MEEGLE_PLUGIN_SECRET`, `QUALIFY_MEEGLE_CALLBACK_TOKEN`, `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL`, `QUALIFY_META_APP_SECRET`, `QUALIFY_META_WEBHOOK_VERIFY_TOKEN`, `QUALIFY_WA_WEBHOOK_VERIFY_TOKEN`, `QUALIFY_OAUTH_STATE_SECRET`, `QUALIFY_R2_ACCESS_KEY_ID`/`_SECRET_ACCESS_KEY`, `QUALIFY_ANTHROPIC_API_KEY`, `QUALIFY_BYTEPLUS_ARK_API_KEY`, `QUALIFY_BYTEPLUS_SPEECH_API_KEY`, `QUALIFY_BYTEPLUS_CV_API_KEY`, `QUALIFY_OMNIHUMAN_REQ_KEY`, `QUALIFY_PIXABAY_API_KEY`, `QUALIFY_PEXELS_API_KEY`, `QUALIFY_CANVA_CLIENT_SECRET`, `HF_TOKEN`, `SCRAPECREATORS_API_KEY`, `ZYTE_API_KEY` | `just env-push` (§4). Los dos *verify token* se cambian también en el panel de webhooks de Meta | ROTAR si los tuvo (ver la regla de arriba) |
| `QUALIFY_DB_*_PASSWORD` (6 roles) | `env-push` los rechaza a propósito: editar `.env.prod` y `just deploy` (el `migrate` aplica el `ALTER ROLE`). Postgres no está expuesto fuera del servidor, así que basta con quitar el SSH salvo que copiara un dump o el archivo | ROTAR solo si tuvo `.env.prod` o un dump; solo el fundador |
| `QUALIFY_DEV_FERNET_KEY` | **No se rota por offboarding**: rotarla deja indescifrables todas las credenciales OAuth guardadas. Si se filtró de verdad, es un incidente (`engineering:incident-response`): llave nueva + `QUALIFY_DEV_KEY_ID` nuevo y reconectar las cuentas de cada tenant | Decide el fundador |
| `QUALIFY_HEYGEN_API_KEY` | HeyGen está obsoleto: revocar la llave en HeyGen y vaciarla | ROTAR = eliminar |
| Respaldos `/opt/qualify/backups` | Si los copió con `rsync`, contienen datos de clientes: pedir que los borre y dejarlo en el registro | QUITAR + confirmar |

### C. Proveedores y herramientas (consolas)

| Sistema | Ruta | Acción |
|---|---|---|
| Meegle (espacio Qualify) **[F]** | *Space configuration → Members* → quitar (después del §2.4) | QUITAR |
| Lark / Feishu **[D]** | Admin console → *Organización → Miembros* → desactivar; transferir sus Docs/Drive al heredero; revisar los bots personalizados del grupo Qualify-devs (si él creó el de «Qualify deploy», regenerar el webhook → `DEVOPS_WEBHOOK_URL`) | QUITAR (+ ROTAR el webhook si lo creó) |
| Meta Business (portafolio Qualify.co) **[F]** | business.facebook.com → *Configuración → Usuarios → Personas* → quitar; revisar *Activos asignados* (páginas, cuentas de IG, WhatsApp) | QUITAR |
| App de Meta (roles) **[F]** | developers.facebook.com → app → *Roles de la app → Roles* (admin/developer/tester) y *Evaluadores de Instagram*. Si era admin o developer, vio el App Secret | QUITAR + ROTAR `QUALIFY_META_APP_SECRET` si era admin/developer |
| BytePlus ModelArk **[F]** | console.byteplus.com → *IAM → Users* → borrar su subusuario y sus AccessKeys; llaves de API de Ark/Speech/CV | QUITAR + ROTAR |
| Anthropic **[F]** | console.anthropic.com → *Settings → Members* y *API keys* (borrar las suyas); claude.ai → *Settings → Members* para el asiento de Claude | QUITAR + ROTAR las llaves compartidas |
| Cloudflare (R2) **[F]** | dash.cloudflare.com → *Manage account → Members*; *R2 → Manage API tokens* | QUITAR + ROTAR el token R2 |
| Supabase **[F]** | supabase.com/dashboard → organización → *Team* | QUITAR (+ ROTAR la secret key si la vio) |
| Vercel (team `attitude1`: landing y DNS de `attitudefactory.co`) **[F]** | vercel.com → team → *Settings → Members*; *Settings → Tokens* de CI si los creó | QUITAR |
| Resend, Canva, ScrapeCreators, Zyte, Pixabay, Pexels, Hugging Face **[F]** | *Team/Members* de cada panel; las llaves van en el bloque B | QUITAR |
| Langfuse (autoalojado en local, `just langfuse-*`) y SonarQube (`infra/sonarqube`) | Viven en la máquina de alguien (hoy, la de un desarrollador: §7.2). Si viven en la suya, se pierden: exportar lo que sirva. `SONAR_TOKEN` se rota si lo creó | QUITAR / ROTAR |
| Restos de Zoho (Mail/Cliq) y Google | Zoho Mail admin → desactivar el buzón; Google Drive/Calendar compartidos → quitarle permisos | QUITAR |

## 4. Orden de rotación (sin romper producción)

Todo pasa por los caminos documentados (`qualify-prod-ops`): nada de `docker compose` ni editar
`.env.prod` a mano, salvo la excepción documentada para las contraseñas de la base.

1. **[F] Apagar el despliegue automático** mientras dura la rotación: `gh variable set QUALIFY_AUTO_DEPLOY --body off`. Sacar un respaldo: `just deploy-backup qualify-prod`.
2. **[F] Lo que mantiene vivo el despliegue, primero:** token GHCR nuevo del fundador (`docker login ghcr.io` en el servidor, §7.1 paso 4) y, si aplica, la llave de CI nueva más `QUALIFY_DEPLOY_SSH_KEY`. Probar con `gh workflow run deploy -f ref=main` y `just deploy-status qualify-prod`. Si este paso falla, todavía no se quitó nada a la persona y producción sigue en pie.
3. **[F] Llaves nuevas en cada proveedor, sin revocar las viejas todavía.** Comprobar que cada llave nueva funciona antes de subirla (por ejemplo, el saldo de ScrapeCreators o una llamada mínima a Anthropic).
4. **Subirlas** desde el `.env` local del fundador (el agente puede ejecutarlo con su sí):
   ```bash
   just env-push qualify-prod --dry-run QUALIFY_ANTHROPIC_API_KEY QUALIFY_R2_SECRET_ACCESS_KEY …
   just env-push qualify-prod QUALIFY_ANTHROPIC_API_KEY QUALIFY_R2_SECRET_ACCESS_KEY …
   just deploy-status qualify-prod
   ```
   Una sola llamada con varias claves recrea los servicios una vez (~15 s). Los pares (R2 id + secreto, verify tokens + panel de Meta) van en la misma llamada.
5. **[F] Contraseñas de la base** (solo si aplica): editar `.env.prod` y `just deploy qualify-prod`, según la tabla del README.
6. **[F] Revocar las llaves viejas** en cada proveedor, y solo entonces quitar las cuentas de la persona (§3 A y C). Al final, **[D]** baja en Lark.
7. **[F] Encender de nuevo el despliegue automático** (`merge` hasta el 2026-11-12, `daily` desde entonces) y revisar `just deploy-logs qualify-prod api` durante 10 min.

Si algo se rompe entre el 4 y el 6: se vuelve a empujar el valor anterior o se restaura
`/opt/qualify/.env.prod.bak-<UTC>`, siguiendo el README («Deshacer un cambio»), con el sí del
fundador.

## 5. Después

### 5.1 Verificación

```bash
gh api orgs/AttitudeFactory/members --jq '.[].login'                 # no aparece
gh api orgs/AttitudeFactory/outside_collaborators --jq '.[].login'   # no aparece
gh api repos/AttitudeFactory/Qualify/collaborators --jq '.[].login'  # no aparece
gh api repos/AttitudeFactory/Qualify/keys --jq '.[].title'           # solo llaves conocidas
ssh qualify-prod 'ssh-keygen -lf ~/.ssh/authorized_keys'             # solo llaves conocidas (y como root)
just env-push qualify-prod --dry-run <claves rotadas>                # todas «same»
just deploy-status qualify-prod                                      # todo sano
gh run list --workflow deploy --limit 1                              # último deploy verde
```

Y en las consolas: Meegle, Lark, Meta (portafolio y roles de la app), BytePlus, Anthropic,
Cloudflare, Supabase y Vercel ya no la muestran.

### 5.2 Lo que se queda

- **Sus commits y PRs se quedan.** No se reescribe la historia ni se cambia la autoría. Las ramas
  sin valor se borran después de la salida.
- Sus tickets cerrados se quedan con su nombre. Los abiertos ya se reasignaron en el §2.4.
- **Pago y administrativo:** _[pendiente: liquidación, último pago, equipo devuelto, NDA/cesión
  de código vigente, correo de cierre]_ — lo completa el fundador.

### 5.3 Registro

Se guarda en el ticket de Meegle del offboarding (no en el repo: lleva nombres).

```markdown
**Offboarding — <nombre> (<login GitHub>)**
- Fecha de salida: AAAA-MM-DD · Fecha de ejecución: AAAA-MM-DD
- Aprobó: Herwin · Ejecutaron: <Herwin / Darwin / agente>
- Traspaso (§2): módulos → <heredero>; PRs <n°s>; tickets reasignados <n>; doc de traspaso <ruta>
- Quitados (§3): <lista>
- Rotados (§4): <claves, sin valores> · deploy de verificación <run id>
- Excepciones / pendientes: <…>
- Verificación (§5.1): OK el AAAA-MM-DD por <quién>
```

## 6. Lista para copiar

```markdown
- [ ] Fecha aprobada por Herwin; ticket de Meegle del offboarding creado
- [ ] §2 Módulos con heredero (docs/equipo-agentes.md)
- [ ] §2 PRs abiertos mergeados, heredados o cerrados
- [ ] §2 Ramas remotas revisadas
- [ ] §2 Tickets de Meegle reasignados (Assignee y Reporter)
- [ ] §2 Sesión de conocimiento → notas en docs/ + tickets de deuda
- [ ] §2 Confirmación escrita de que borró .env, llaves y dumps locales
- [ ] §4.1 QUALIFY_AUTO_DEPLOY=off + just deploy-backup
- [ ] §4.2 Token GHCR del servidor y llave de CI son del fundador; deploy de prueba verde
- [ ] §4.3 Llaves nuevas creadas y probadas en cada proveedor
- [ ] §4.4 just env-push (dry-run → push) + deploy-status
- [ ] §4.5 Contraseñas de la base (solo si aplica)
- [ ] §3A GitHub: org, colaboradores, invitaciones, deploy keys, PATs, secretos, CODEOWNERS
- [ ] §3B SSH (deploy y root) + consola de Hetzner; aviso a Pedidos si tenía root
- [ ] §3C Meegle, Meta (portafolio + roles de la app), BytePlus, Anthropic/Claude, Cloudflare, Supabase, Vercel, demás paneles
- [ ] §3C Lark (Darwin): baja, documentos transferidos, webhook del bot revisado
- [ ] §4.6 Llaves viejas revocadas
- [ ] §4.7 Despliegue automático encendido de nuevo; logs revisados
- [ ] §5.1 Verificación completa
- [ ] §5.2 Nota administrativa completada
- [ ] §7 Tabla de dueños de credenciales críticas re-verificada (GHCR, Claude, SSH)
- [ ] §5.3 Registro pegado en el ticket; ticket en Done
```

## 7. Dueños de credenciales críticas

`[VERIFICADO 2026-10-24 · m-24852090]` · Regla del fundador: estas credenciales son **solo de
Herwin**. Si un día dejan de serlo, el offboarding de esa persona deja de ser rutina (§4.2). La
verificación se hizo en modo solo lectura, sin imprimir ningún valor: solo usuarios, huellas de
llaves y metadatos. Se repite en cada offboarding y cuando alguien cambie una de estas piezas.

### 7.1 Tabla

| Credencial | Dueño previsto | Dueño verificado (2026-10-24) | ¿Coincide? |
|---|---|---|---|
| Token GHCR *classic* `read:packages` del VPS (§7.1 paso 4 de `despliegue-hetzner.md`) | Herwin | Usuario `hlrd93` en `/home/deploy/.docker/config.json` (archivo del 2026-10-07). Root no tiene login de GHCR (no hace falta: los deploys tiran las imágenes como `deploy`). | **Sí, por el usuario.** Matiz: el usuario de `docker login` lo escribe quien hace el login; GHCR autentica por el token. Comprobar el dueño real del token pide usarlo contra la API de GitHub, y no se hizo en esta revisión. Pendiente para el fundador: en *GitHub → Settings → Developer settings → Tokens (classic)* debe figurar un token `read:packages` con fecha de vencimiento; si no lo ve, el token es de otra persona → rotarlo (§4.2). |
| `CLAUDE_CODE_OAUTH_TOKEN` (workflow `review`) | Herwin (su suscripción Claude) | El secreto lo creó `hlrd93` el 2026-10-05 18:14 UTC, desde `gh` en una sesión de Claude Code, y nunca se actualizó (registro de auditoría de la organización). **La cuenta de Claude que lo emitió no se puede ver**: los logs del workflow lo enmascaran y la acción no imprime la cuenta. | **Probable, sin verificar.** Lo subió Herwin; si el `claude setup-token` lo corrió él, es suyo. Para cerrarlo: el fundador lo regenera con `claude setup-token` en su Mac y lo sube con `gh secret set CLAUDE_CODE_OAUTH_TOKEN` (pide el valor por la terminal, nunca como argumento). |
| SSH root del VPS (`just deploy`, `just env-push`, `just edge-install`; llega también a Pedidos) | Herwin | **Una sola llave** en `/root/.ssh/authorized_keys`: la de `~/.ssh/qualify_hetzner` del Mac del fundador (misma huella; en el servidor la línea no lleva comentario). No hay otros usuarios con llaves fuera de `root` y `deploy`. | **Sí.** |
| SSH `deploy` | Herwin + CI | La misma llave del fundador, sin restricción, y `qualify-ci-deploy` con `command="/opt/qualify/bin/server-deploy.sh",restrict`. La mitad privada de la de CI está en el Mac del fundador y en el secreto `QUALIFY_DEPLOY_SSH_KEY`, que creó `hlrd93` el 2026-10-07. | **Sí.** |
| `.env.prod` del VPS | Herwin | Solo se lee o escribe por SSH root o `deploy` (filas de arriba), así que hoy solo lo alcanza Herwin. | **Sí, por SSH.** Ver la discrepancia de abajo. |
| Resto de secretos de Actions (`QUALIFY_DEPLOY_SSH_*`, `DEVOPS_WEBHOOK_*`) | Herwin | Todos creados por `hlrd93` (2026-10-07 y 2026-10-19). | **Sí.** |

**Discrepancias y matices que hay que conocer:**

1. **Producción no es «solo Herwin» por el lado de GitHub.** `main` no tiene protección y
   `QUALIFY_AUTO_DEPLOY=true`: cualquiera con escritura en el repo puede empujar a `main` y eso se
   despliega solo, con el código corriendo junto a `.env.prod`. Hoy tienen escritura **seis
   cuentas además del fundador** (tres de ellas *admin* del repo; dos son también *owners* de la
   organización, y un *admin* puede sobrescribir los secretos de Actions). Ninguna ve los valores,
   pero sí puede cambiar lo que corre. Es la condición que ya describe el §7.1 paso 3 de
   `despliegue-hetzner.md` («publicar en GHCR exige escritura, que ya alcanza para cambiar lo que
   corre en producción»), ahora con números.
2. **El repo pasó a público el 2026-10-24** (registro de auditoría). Dos consecuencias: los logs de
   Actions son visibles para cualquiera (los secretos siguen enmascarados) y, con el repo público,
   GitHub Free **sí** permite proteger ramas: `just protect-main` (`infra/github/ruleset-main.json`)
   ya se podría aplicar. Lo decide el fundador.
3. **GHCR y Claude dependen de cuentas personales por diseño.** GitHub Packages no acepta tokens
   *fine-grained* para `docker login`, así que el token *classic* siempre es de una persona, y
   `CLAUDE_CODE_OAUTH_TOKEN` es una suscripción personal. Que sean de Herwin es lo correcto; lo que
   falta es confirmarlo en sus pantallas (filas de arriba).

### 7.2 Dependencia de una sola persona: Langfuse y SonarQube

Según el fundador, los dos corren autoalojados en la máquina de un desarrollador (Deivid). Lo que
el repo y el servidor muestran el 2026-10-24:

| Herramienta | Configuración que hay | Qué significa |
|---|---|---|
| Langfuse (`infra/langfuse/`, `just langfuse-*`) | `LANGFUSE_BASE_URL=http://localhost:3100` en `.env.example`; el VPS no tiene ninguna clave `LANGFUSE_*` en `.env.prod`. | Cada máquina apunta a **su propio** `localhost`. Producción no envía trazas. Los conjuntos de datos, puntuaciones y colas de anotación de las evaluaciones (`just eval-*`, `just langfuse-setup`) viven en los volúmenes Docker de quien lo levantó. No hay túnel ni host compartido configurado en el repo. |
| SonarQube (`infra/sonarqube/`, `sonar.yml`) | El README propone `https://sonar.attitudefactory.co`, pero ese nombre responde 404 desde Vercel (el comodín DNS del dominio); los secretos `SONAR_HOST_URL` y `SONAR_TOKEN` no existen y la variable `SONAR_ENABLED` no está puesta, así que `sonar` sale *skipped* en cada push. | El análisis en CI está apagado. Si Sonar corre, corre a mano contra `127.0.0.1:9000` en esa máquina y su historial solo existe ahí. |

**Riesgo:** si esa persona se va o su máquina falla, se pierden el historial de evaluaciones de
Langfuse (las mediciones que exige `qualify-measure`) y el historial de Sonar, y nadie más puede
correr `just eval-*` contra los mismos datos. No toca a producción.

**Opciones para sacarlos de una máquina personal** (house rule: nada de infraestructura ni
proveedor nuevo sin tabla de opciones y decisión del fundador; precios a confirmar al contratar):

| Opción | Qué implica | Costo | Datos y riesgos |
|---|---|---|---|
| **A. Dejarlo como está + exportación documentada** | Un `just langfuse-export` (o `pg_dump` del Postgres de Langfuse + copia de ClickHouse/MinIO) a R2 una vez por semana; los *datasets* de evaluación también en `packages/api/evals/` como archivos. Sonar no necesita respaldo: se reanaliza `main` cuando haga falta. | $0 y ~½ día de trabajo. | Sigue siendo de una persona: solo reduce la pérdida. Nadie más ve las trazas en vivo. |
| **B. En el VPS de Hetzner** | Hoy el VPS es un ARM de 2 vCPU y 4 GB: medido 1,4 GB de RAM disponible y 70 % de disco (11 GB libres de 38). Langfuse v4 (web, worker, Postgres, ClickHouse, Redis, MinIO) recomienda 4 núcleos y 16 GB; SonarQube pide 4 GB libres y `vm.max_map_count` del host. **No cabe sin agrandar el servidor**, y el servidor es compartido con Pedidos: el `sysctl` y la carga de ClickHouse/Elasticsearch le afectan, igual que el corte del Caddy compartido al publicar subdominios (`just edge-install`). | Subir a un plan de 8 vCPU / 16 GB, del orden de 15–30 €/mes más según la línea (ARM o x86; Hetzner cambió precios el 2026-06-15), o un servidor aparte CX43 como propone la Etapa B de `plan-observabilidad-langfuse.md`. | Los datos se quedan en nuestra infraestructura (UE, Núremberg). Suma respaldos, actualizaciones y un punto de falla junto a producción. |
| **C. Gestionado: Langfuse Cloud y SonarQube Cloud** | Langfuse Cloud: plan *Hobby* gratis (≈50 000 unidades/mes, 30 días de datos, 2 usuarios) o *Core* ≈29 USD/mes (≈100 000 unidades, 90 días, usuarios ilimitados); región UE (Fráncfort) o EE. UU. SonarQube Cloud: **gratis para repos públicos** (este lo es desde hoy), con análisis de PR y ramas que la Community Build no tiene; para repo privado el plan gratuito cubre hasta ≈50 000 líneas y el de equipo empieza en ≈30 USD/mes; datos en la UE. | 0–29 USD/mes en Langfuse; 0 en Sonar mientras el repo sea público. | **Proveedor nuevo con datos de clientes:** las trazas de Langfuse llevan los textos de los tenants (catálogo, Brand Kit, comentarios). Exige región UE, revisar el DPA y decidir si se anonimiza antes de enviar; `plan-observabilidad-langfuse.md` eligió autoalojar justamente para que los datos no salgan. Sonar solo ve código, que ya es público. |

**Recomendación — decisión del fundador:** separar las dos.
- **SonarQube → opción C (SonarQube Cloud gratis)** mientras el repo siga público: elimina la
  dependencia, cuesta $0, solo ve código ya público y agrega análisis de PR. Si el repo vuelve a
  privado, apagarlo: `semgrep` + `bandit` del workflow `security` ya cubren lo esencial. El
  workflow `sonar` gasta un minuto por push a `main` solo con `SONAR_ENABLED=true`.
- **Langfuse → opción A ya**, y **C (UE, *Hobby*) o la Etapa B propia** solo cuando haga falta
  compartir trazas en vivo o enviar trazas de producción, decidiéndolo junto con qué datos de
  clientes pueden salir. Meterlo en el VPS compartido (B en el mismo servidor) es la opción menos
  recomendable: no cabe, y el riesgo lo paga también Pedidos.
