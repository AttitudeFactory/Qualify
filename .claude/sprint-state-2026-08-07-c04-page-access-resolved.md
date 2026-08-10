# C-04 — `page_access_required` resuelto: `business_management` es requisito para Pages de portfolio (2026-08-07)

**Estado: CERRADO con verificación en vivo.** Esta nota cierra la incógnita que
`sprint-state-2026-07-29-sprint2-pipeline.md` §7 dejó abierta con el arquitecto
(`/me/accounts` → `{"data": []}`) y documenta las tres trampas locales que la prueba destapó.

## Síntoma

El connect flow C-04 terminaba en `outcome=page_access_required` (`page_count=0`) con un
usuario que es **admin con acceso total** de la Page `Qualify.co` (1618064151381022) dentro
del Business Portfolio, app en Development Mode, rol en la app. La hipótesis inicial del
operador — "¿necesito Business Verification con documentos?" — era falsa.

## Causa raíz (comportamiento de Meta, no bug nuestro)

**`GET /me/accounts` no devuelve Pages cuya propiedad es de un Business Portfolio si el token
no lleva el scope `business_management`.** Comportamiento introducido con Graph v18.0
(sept 2023), recurrente en v23; ampliamente reportado en el foro de developers de Meta
(hilo 672345581624608). El `.env` pedía 4 scopes
(`instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement`) — todos
correctos pero insuficientes para el caso "activo en portfolio", que es exactamente el caso
del customer zero.

Esto refina el comentario de `service.py` (R9(f), "Meta filtra por TASKS, no ownership"):
las tasks del usuario sobre una Page de portfolio **solo se materializan en el edge si el
token lleva `business_management`**.

## Qué quedó demostrado

1. **Scope-set mínimo real del connect flow (caso portfolio):** los 4 anteriores +
   `business_management` = 5. Meta concedió además `public_profile` motu proprio.
2. **Business Verification / App Review NO hacen falta** para customer zero: usuario con rol
   en la app + Development Mode bastó — consistente con ADR 21/29 y con la doc oficial
   ("If your app will only be used by app users who have a role on the app itself you do
   not need to complete verification").
3. **Corrida completa exitosa** (2026-08-07 05:34 UTC):
   - Callback: `{"outcome":"active","connection_id":"18b0355f-6831-4b71-b0a5-9332249ddc12","external_username":"qualifymkt.co","page_count":0,"linked_page_count":0}`
   - Fila en `social_connections`: `status=active`, `linked_page_id=1618064151381022`,
     `access_posture=development`, `granted_scopes={pages_show_list,business_management,instagram_basic,instagram_content_publish,pages_read_engagement,public_profile}`
   - `connection_events`: `granted` ×2 (persistencia + verificación post-grant).

## Cosmético detectado (no bloqueante)

El camino exitoso de `ConnectService.complete_connect` construye el `ConnectResult` **sin**
rellenar `page_count`/`linked_page_count` (`service.py:251`); solo los dead-ends los
reportan. Por eso el callback exitoso muestra ceros. Si se quiere que el éxito también
reporte los counts de R9(e.1), es pasar dos kwargs.

## Trampas locales que la prueba destapó (todas mordieron hoy)

1. **El Postgres de Homebrew (`postgresql@15`) se re-arranca solo** (launchd) y roba
   `localhost:5432` al de Docker → la API falla con `role "qualify_app" does not exist`
   (está hablando con la base equivocada). Fix: `brew services stop postgresql@15`.
   Ya había pasado el 2026-07-29; volvió a pasar hoy. Mientras ese servicio exista
   instalado, cada reinicio de la máquina es una recaída en potencia.
2. **El seed debe correrse con el `.env` cargado** — `_ensure_platform_app` lee
   `QUALIFY_META_APP_ID` del entorno; sin él, la fila de `platform_apps` se crea con el
   app id por defecto y el connect real muere con `PlatformAppMissing`. La base tenía
   1.734 filas de `platform_apps` (basura de tests `app-123`) y **ninguna** para las dos
   apps reales (`1369177161823305` vieja, `1670943920870196` actual).
3. **El puerto 8000 local lo ocupa un contenedor de otro proyecto ("Itaca")** en IPv6 —
   `curl localhost:8000` puede responder 200 desde la app equivocada. La API de Qualify
   corre en **8010** para estas pruebas.

## Receta operativa que funcionó (para repetir la prueba)

```bash
docker compose up -d --wait
brew services stop postgresql@15        # si está corriendo
set -a; source .env; set +a
PYTHONPATH="$PWD/packages/api/src:$PWD/packages/shared/src:$PWD/packages/models/src:$PWD/packages/scraper/src" \
  uv run --no-sync python -m qualify_api.seed   # asegura platform_apps con el app id real
cloudflared tunnel --url http://127.0.0.1:8010  # URL nueva cada corrida → re-registrar en Meta
# actualizar QUALIFY_META_REDIRECT_URI en .env con la URL del túnel
PYTHONPATH=... uv run --no-sync --with uvicorn \
  uvicorn "qualify_api.http.app:create_app" --factory --host 127.0.0.1 --port 8010
# generar la authorization URL vía ConnectService.start_connect (state TTL = 10 min)
```

La redirect URI se registra en el App Dashboard: **Facebook Login for Business → Settings →
Valid OAuth Redirect URIs** (`developers.facebook.com/apps/<app_id>/fb-login/settings/`).

## A0 (Sprint 3) — ENTREGADO el mismo día, con los dos `[V]` cerrados en vivo

Con el túnel aún vivo se ejecutó el item 1 del Sprint 3 (`docs/backlog-sprint3-mvp-demo.md`
§3/A0): custodiar el token de **Página** en vez del de usuario.

- **Código:** `meta_oauth.py` pide `access_token` en los `fields` de `/me/accounts`;
  `LinkedPage.page_access_token` (repr redactado, misma disciplina que `TokenGrant`);
  `service.py` cifra el token de Página con `token_type='page'` y cae al de usuario con
  warning si faltara. Suite offline **343/343**, ruff limpio.
- **Reconnect en vivo:** misma conexión (`18b0355f…`), credencial **versión 2,
  `token_type='page'`**, evento `reconnected` + `granted`, verify (`/me`) en verde con el
  token de Página — el round-trip cifrar→custodiar→leer como `qualify_credential`→
  descifrar→autenticar funciona con la credencial nueva.
- **`[V]` (i) — CERRADO:** `debug_token` sobre la credencial custodiada:
  `type=PAGE`, `is_valid=true`, **`expires_at=0` (no expira)** sin intercambio previo a
  long-lived del token de usuario. No hace falta ningún paso extra.
  **Matiz nuevo: `data_access_expires_at` ≈ +90 días (2026-11-05)** — la ventana de
  acceso a datos sí caduca aunque el token no; es lo que un refresco futuro debe vigilar.
  El `expires_at` en base (el del grant de usuario, ~2026-10-06) queda como aproximación
  conservadora: promete de menos, nunca de más.
- **`[V]` (ii) — CERRADO: una sola credencial por conexión.** `/me/permissions` se lee en
  vuelo con el token de usuario en memoria y nada vuelve a leerlo tras el callback. No hay
  segunda custodia que elevar al architect.
- **Bonus observado:** `granular_scopes` devuelve `instagram_content_publish` con
  `target_ids=[17841448653847824]` (el IG de `@qualifymkt.co`) — la concesión de
  publicación es por cuenta, y está.

## Smoke de publicación end-to-end — EL PRIMER REEL PUBLICADO POR QUALIFY (2026-08-07 06:05 UTC)

Con el token de Página de A0 en custodia se corrió un smoke manual de la vía resumable
completa (script en scratchpad, usando el `HttpPublishClient` commiteado + el resolver
real): contenedor → upload a `rupload` → poll → `media_publish`.

**Resultado: publicado.** Media `18087084638657399`, `media_product_type=REELS`,
`https://www.instagram.com/reel/Dbump-jElJz/`, cuenta `@qualifymkt.co` (~~visible solo para
usuarios con rol — Development Mode~~ **corregido 2026-08-08: FALSO — el reel es públicamente
visible sin sesión, verificado en incógnito por el fundador y por fetch anónimo del embed;
KC-1 queda invertido por medición. Ver `docs/integracion-cuentas-conectadas-meta.md` §3.1,
bloque 2026-08-08**). Vídeo: el fixture `sample_source.mp4` (HEVC
1080×1920, 61 s, 9.3 MB) — **HEVC aceptado**, contenedor `FINISHED` en el primer sondeo.

### La pregunta cara, cerrada gratis

**`ads_management`/`ads_read` NO hacen falta para publicar** en este escenario — Página
propiedad de un Business Portfolio, exactamente el escenario del fundador que el PO marcó
el 2026-08-05 como *"medible en una tarde; decidirlo a ciegas cuesta un App Review"*. El
token custodiado no lleva ningún `ads_*` y el publish salió. Queda medido, no inferido.

### Tres defectos reales del cliente commiteado, invisibles para la suite offline

1. **`WriteTimeout` en el upload:** `InjectingCredentialResolver` construye el
   `httpx.AsyncClient` con timeouts por defecto (5 s de write) — imposible subir 9 MB.
   El upload necesita timeout explícito (funcionó con 600 s).
2. **`_achunks` → `Transfer-Encoding: chunked` sin `Content-Length` → 
   `ParameterValidationError` (retriable=false) de `rupload`.** Con cuerpo dimensionado
   (httpx emite `Content-Length`) el mismo upload devuelve `success=true`. El streaming
   del cliente commiteado (`client.py:216-228`) no puede funcionar tal cual contra
   `rupload`; hay que aportar `Content-Length` (se conoce: es `file_size`).
3. **`ReadTimeout` en `media_publish`:** la llamada tarda más que los 5 s por defecto.

Los tres son insumos directos de A5 (servicio) y de la composición: timeouts como dato,
`Content-Length` en el upload.

### A6-min, demostrado en vivo antes de existir

El `media_publish` del smoke **murió por `ReadTimeout` y aun así publicó** — la
reconciliación de solo-lectura posterior encontró el contenedor en `PUBLISHED` y el reel
en `/media`. Es letra por letra el modo de fallo irreversible por el que el PO metió
A6-min como P0 (*"la publicación sí ocurrió y el estado no ha propagado → segunda
llamada → dos reels públicos"*). El smoke lo esquivó reconciliando a mano en vez de
reintentar; el código de A5/A6-min tiene que hacer exactamente eso.

### Parsers `[V]` de QUA-19 que tocaron realidad hoy

`_parse_container_response` (id+uri, uri en `rupload.facebook.com`), 
`_parse_upload_response` (ambas formas: `debug_info` y `success:true`),
`_parse_status_response` (`FINISHED`, `PUBLISHED`). `_parse_publish_response` sigue `[V]`
(el timeout impidió ver el body de éxito; la publicación se confirmó por reconciliación).

## Sesión nocturna 2026-08-07: Sprint 3 ejecutado hasta 8 de 9 items

Tras el smoke, la misma sesión ejecutó la cadena del backlog (`docs/backlog-sprint3-mvp-demo.md`
§3) de corrido. En `main`, un commit por item:

| Item | Commit | Nota |
|---|---|---|
| A0 token de Página | `2a1db36` | `[V]`×2 cerrados en vivo |
| A1 `config_id` | `7541466` | falta el paso manual del dashboard + `QUALIFY_META_CONFIG_ID` |
| C1 `Principal` | `c897b50` | `QUALIFY_DEV_PRINCIPALS` ya en `.env` con token para el founder |
| A3 staging | `0376939` | |
| A4 repositorio write-ahead | `93546f9` | + `MemoryPublishAttemptRepository` en código prod (precedente `InMemoryEventPublisher`; `--import-mode=importlib` impide imports entre tests) |
| A5+A6-min servicio | `279a472` | un solo commit: se entrelazan en `advance()` |
| A7 rutas | `408ea05` | la cadena demo §1.1 corre entera en la suite sin red/DB |

**Estado de suites al cierre: offline 398/398 · db 40/40.**

Decisiones tomadas durante la ejecución que el lector debe conocer:

- **El cliente QUA-19 se corrigió hacia lo medido**, revirtiendo un test commiteado:
  upload con cuerpo dimensionado (`Content-Length`) en vez del streaming chunked que
  `rupload` rechaza; timeouts explícitos (`UPLOAD_TIMEOUT` 600 s, `GRAPH_WRITE_TIMEOUT`
  60 s); `PublishError` gana `platform_code`/`platform_subcode` numéricos (códigos, nunca
  cuerpos). `_achunks` eliminado — su argumento de memoria perdió contra una medición.
- **Agujero encontrado y cerrado durante la implementación** (con test de regresión): el
  marcador de rechazo-con-código sobreescribía `publish_sent_awaiting_confirmation`, y un
  `advance()` posterior con `FINISHED` habría reenviado. `_send_was_emitted` acepta ambas
  grafías.
- **El ceiling de 300 s nunca liquida un intento cuyo envío ya salió** — liquidar `failed`
  sobre una publicación que aterrizó sería la mentira irreversible; con marcador, solo el
  veredicto del contenedor termina el intento.

**Lo único que queda del sprint: C3** (declarar `boto3`+`uvicorn`, ritual del venv
`rm -rf .venv && uv sync --group ml`). **Deliberadamente NO ejecutado esta noche:** muta
`uv.lock` y el ritual tiene dos precedentes de corromper el venv compartido — si falla
sin nadie despierto, el workspace amanece roto. Sin C3 el camino REAL de R2 no se puede
instanciar (las credenciales `QUALIFY_R2_*` tampoco están en `.env` aún), pero toda la
cadena de código y tests está verde con dobles. C3 + credenciales R2 + un vídeo real por
las rutas = la demo del §1.1 completa.

## Deuda que esta nota NO resuelve

- La conexión activa quedó bajo el tenant **PuntoServis** con un túnel efímero ya muerto o
  por morir; es una conexión de prueba real (token cifrado en custodia) — decidir si se
  revoca (`revoke_connection`) o se conserva para las pruebas de publishing de Sprint 3.
- `docs/integracion-cuentas-conectadas-meta.md` y el refinamiento de C-04 deberían recoger
  el scope-set de 5 — ficheros del arquitecto, no se tocaron aquí.
- Meta procesa con v25.0 y el default del código sigue en v21.0 (deuda ya registrada el
  29-07, sin cambio).
