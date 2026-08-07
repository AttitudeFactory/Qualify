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

## Deuda que esta nota NO resuelve

- La conexión activa quedó bajo el tenant **PuntoServis** con un túnel efímero ya muerto o
  por morir; es una conexión de prueba real (token cifrado en custodia) — decidir si se
  revoca (`revoke_connection`) o se conserva para las pruebas de publishing de Sprint 3.
- `docs/integracion-cuentas-conectadas-meta.md` y el refinamiento de C-04 deberían recoger
  el scope-set de 5 — ficheros del arquitecto, no se tocaron aquí.
- Meta procesa con v25.0 y el default del código sigue en v21.0 (deuda ya registrada el
  29-07, sin cambio).
