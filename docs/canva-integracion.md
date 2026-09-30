# Integración con Canva — enviar piezas a editar y traerlas de vuelta

*28-sep-2026. **El código existe y tiene tests contra dobles, pero nunca se ejecutó contra la API real de Canva**: no había credenciales de integración cuando se escribió. Este documento dice cómo configurarlo y qué debe confirmar la primera prueba real.*

## 1. Qué hace

Desde el resultado del generador (`/signals`), la tarjeta **"Editar en Canva"**:

1. **Conectar Canva** (una vez por usuario): OAuth 2.0 con PKCE (S256). Los tokens se guardan **cifrados** por `(tenant, usuario)` en `canva_accounts`, con el mismo `Encryptor` que las credenciales de Meta.
2. **Editar en Canva**: sube el archivo de la pieza a los "Subidos" del usuario, crea un diseño del mismo tamaño y abre el editor de Canva **en la misma pestaña**.
   - **Imagen**: queda colocada dentro del diseño.
   - **Video**: la API de Canva no puede colocarlo; queda en "Subidos" y el usuario lo arrastra al diseño.
3. Al pulsar **"Volver"** en Canva, el usuario cae en `/canva/return`: Qualify exporta el diseño (PNG, o MP4 1080p vertical/horizontal según la forma) y lo guarda junto a los archivos del borrador (`generated/<tenant>/<draft>/canva-….png|mp4`).
4. **Traer de Canva** vuelve a exportar cuando se quiera (por si el usuario cerró la pestaña sin pulsar "Volver" o siguió editando). Si una re-exportación falla, se conserva el último archivo bueno.

La edición traída **no reemplaza** la media del borrador: se muestra aparte, con su descarga. Decidir si sustituye a la pieza aprobable es una decisión de producto pendiente.

## 2. Piezas de código

| Pieza | Archivo |
|---|---|
| Cliente HTTP de Canva Connect (OAuth, assets, designs, exports) | `packages/creative/src/qualify_creative/adapters/canva_connect.py` |
| Tablas `canva_accounts`, `canva_design_links` (RLS) | `migrations/postgres/versions/0030_canva.py` |
| Modelos, repositorio (Postgres + memoria), servicio, composición | `packages/api/src/qualify_api/canva/` |
| Proveedor, estado y páginas Reflex | `Qualify/canva_provider.py`, `Qualify/canva_state.py`, `Qualify/canva_pages.py` |
| Tarjeta en el generador | `Qualify/content_generator.py` (`_canva_card`) |
| Tests | `packages/creative/tests/test_canva_connect.py`, `packages/api/tests/test_canva_service.py`, `Qualify/test_canva_state.py` |

## 3. Configuración (cuando tengas las credenciales)

1. En el [Developer Portal de Canva](https://www.canva.com/developers/) (requiere **MFA** en la cuenta), crea una integración en **"Outside Canva"** (Connect API).
2. **Scopes**: `asset:read`, `asset:write`, `design:meta:read`, `design:content:read`, `design:content:write`.
3. **Redirect URL (OAuth)**: `http://127.0.0.1:3000/canva/callback` en local.
4. **Return navigation**: actívala y pon como Return URL `http://127.0.0.1:3000/canva/return`.
5. En `.env`:

   ```
   QUALIFY_CANVA_CLIENT_ID=...
   QUALIFY_CANVA_CLIENT_SECRET=...
   # opcional; por defecto http://127.0.0.1:3000/canva/callback
   QUALIFY_CANVA_REDIRECT_URI=...
   ```

6. Aplica la migración: `just migrate` (o `just down` + `just dev` si recreas la base).

Sin las dos primeras variables, la tarjeta dice que Canva no está configurado y no ofrece botones.

Mientras la integración no pase la **revisión pública** de Canva, solo la puede usar el equipo de Canva del desarrollador. Para clientes hace falta enviarla a revisión (justificación de scopes, cuenta de prueba y sin redirect URLs locales).

## 4. Qué debe confirmar la primera prueba real

Todo esto se escribió según la documentación de canva.dev del 28-sep-2026, sin verificarlo en vivo:

1. **Intercambio del código**: que el endpoint de token acepta las credenciales por **Basic auth** y el cuerpo `application/x-www-form-urlencoded`, y que `expires_in` viene en segundos.
2. **Refresh**: que cada refresh devuelve un refresh token nuevo (el código lo asume y lo reemplaza siempre). Si falla, el código olvida la cuenta y pide reconectar.
3. **Subida de asset**: la cabecera `Asset-Upload-Metadata` con `name_base64`, y la forma del job (`job.status`, `job.asset.id`).
4. **Crear diseño**: `design_type: {type: "custom", width, height}` + `asset_id`; que la respuesta trae `design.urls.edit_url` y `design.updated_at` (segundos unix).
5. **Return navigation**: que `correlation_state` sobrevive en `edit_url` y vuelve dentro del `correlation_jwt`. **La firma del JWT no se verifica**, porque el endpoint de claves estaba en preview. La defensa es que `correlation_state` es aleatorio, se busca bajo RLS del tenant, debe haberlo creado el mismo usuario, y el diseño se vuelve a leer con el token de ese usuario. Si Canva publica un endpoint de claves estable, añadir la verificación en `decode_correlation_jwt`.
6. **Export**: formas `format: {type: "png"}` y `{type: "mp4", quality: "vertical_1080p"}`, y `job.urls` como lista. Qué pasa con un video 4:5 (¿`vertical_1080p` conserva el recorte?).
7. **Misma pestaña**: que la sesión de Reflex (login + verificador PKCE en el estado) sobrevive al ir a canva.com y volver. Si no sobrevive, habría que guardar el verificador en Postgres, ligado al `state`.
8. **Plan Free**: que subir, crear y exportar funcionan en Canva Free (según la documentación, sí; PNG transparente y exportación "pro" requieren plan de pago).

## 5. Límites conocidos (documentados por Canva)

- **Subidas**: imágenes hasta 50 MB y videos hasta 500 MB.
- **URLs**: `edit_url` válida 30 días y solo para ese usuario; las URLs de exportación duran 24 h (por eso se descargan al momento).
- **Rate limits**: por usuario, 20 diseños/min, 30 subidas/min y 20 exports/min (500/día). Por app, 5.000 exports/día.
- **Sin webhook de "diseño editado"**: la señal es el botón "Volver" o "Traer de Canva".
- **Video**: no se puede colocar automáticamente en el diseño. Una mini-app de Canva (Apps SDK) podría hacerlo más adelante, pero exige otra revisión.

Fuentes: ver la investigación del 28-sep-2026 (canva.dev: create-design, asset-uploads, exports, return-navigation-guide, rate limits en el OpenAPI `api.yml`).
