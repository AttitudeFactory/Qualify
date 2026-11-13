# ADR 48 — Catálogo de WhatsApp: carga de productos por API desde Galería

`[PROPUESTO — principal-architect 2026-11-12, pendiente de firma del fundador · épica m-25017354 · conector m-25017356 · Galería m-25017357]`

Origen: decisión firmada del fundador (2026-11-12, D1–D2 de `docs/opciones-catalogo-whatsapp.md`,
rama `docs/m-24936714-opciones-catalogo-whatsapp`): «construyamos la carga por API, desde cada
producto: cargar, resincronizar, o cargar/sincronizar todos los productos». Este ADR no reabre esa
elección; fija el contrato que implementa el ingeniero de backend. Evidencia: `[V]` página oficial
leída hoy (URL y fecha) o código en disco; `[H]` inferencia nuestra; `[NO VERIFICADO]` sin fuente.

## 1. Decisión (resumen)

1. Qualify sube a Meta, por `POST /{catalog_id}/items_batch`, los productos de Galería
   (`brand_products`) al catálogo de Commerce Manager **conectado a mano** a la WABA del negocio y
   registrado en Qualify por un CLI administrativo. Qualify no crea ni conecta catálogos por API.
2. Tres acciones, **siempre disparadas por una persona**: cargar un producto, resincronizar un
   producto, cargar/sincronizar todos (con un «plan» en seco que la pantalla muestra antes de
   confirmar). Sin sincronización automática.
3. Tres tablas nuevas con RLS en **una** revisión `0154_whatsapp_catalog_sync` (sobre la cabeza
   `0153_seasonal_media_delete_no_cap`): `whatsapp_catalogs`, `whatsapp_catalog_items`,
   `whatsapp_catalog_sync_runs`. Un Postgres (ADR 31), sin cola nueva.
4. Las llamadas a Meta salen del **`whatsapp-worker` existente** (una segunda tarea junto a
   `OutboxTick`), nunca en la petición. **Ningún servicio nuevo en producción.**
5. `retailer_id` = `brand_products.id` (UUID en texto), fijado en la fila del artículo al primer
   envío y nunca recalculado.
6. La foto principal se sirve en una ruta pública **estable y firmada**
   `GET/HEAD /public/catalog-media/{tenant_id}/{media_id}/{firma}.jpg`, HMAC derivado de
   `QUALIFY_OAUTH_STATE_SECRET` con etiqueta de dominio propia: **sin variable de entorno nueva**.

## 2. Lo que dice Meta hoy (releído 2026-11-12)

Fuentes: [IB] `developers.facebook.com/docs/marketing-api/reference/product-catalog/items_batch/` ·
[CB] `…/product-catalog/check_batch_request_status/` · [PC]
`developers.facebook.com/docs/graph-api/reference/whats-app-business-account/product_catalogs/` ·
[CR] `developers.facebook.com/docs/marketing-api/catalog/reference` · [CM]
`developers.facebook.com/docs/permissions/reference/catalog_management` · [UI]
`developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/upload-inventory.md`.
Todas consultadas el 2026-11-12; ninguna muestra fecha de actualización.

| Afirmación | Nivel |
|---|---|
| Parámetros de `items_batch`: `item_type` (`PRODUCT_ITEM`), `requests` (arreglo JSON, ≤ 5.000; recomienda < 3.000), `allow_upsert` (por defecto `true`: un `UPDATE` crea si no existe). Cada elemento: `method` ∈ `CREATE`/`UPDATE`/`DELETE` y `data` | `[V]` [IB] |
| El ejemplo de la página envía campos de formulario (`-F item_type=PRODUCT_ITEM`, `-F requests=<JSON>`); se usa esa forma | `[V]` [IB] |
| Campos obligatorios de `PRODUCT_ITEM`: `id`, `title`, `description`, `link`, `image`, `price`, `availability`, `brand`, `condition`. **`image` es un arreglo de objetos `{"url": …, "tag": [...]}`** (≤ 21); `image_link` es opcional y se ignora si viene `image` | `[V]` [IB] |
| `id` ≤ 100 caracteres; `title` ≤ 100 [IB] (la referencia general dice 200, recomienda 65 [CR]); `description` ≤ 5.000 [IB] (9.999 en [CR]); se recorta al menor | `[V]` |
| `price`: «monto, espacio, código ISO de 3 letras», punto decimal, sin símbolo (`9.99 USD`) | `[V]` [IB][CR] |
| `availability` ∈ `in stock`, `out of stock`, `available for order`, `discontinued`; `condition` ∈ `new`, `refurbished`, `used` | `[V]` [IB] |
| Imagen JPEG o PNG, **≥ 500 × 500 px**, ≤ 8 MB; si se cambia la imagen, **la URL nueva debe ser distinta** | `[V]` [CR] |
| `link` «debe estar en el dominio del sitio del negocio» y no en un dominio de Facebook | `[V]` [CR] |
| Respuesta: `handles` (lista; vacía = nada ingerido) y `validation_status[]` con `retailer_id`, `errors[].message`, `warnings[].message` | `[V]` [IB] |
| Límite por catálogo: error **80014** («demasiadas llamadas de carga por lotes»); sin cifra fija | `[V]` [IB] |
| `GET /{catalog_id}/check_batch_request_status?handle=…&load_ids_of_invalid_requests=true&fields=handle,status,warnings,errors_total_count,ids_of_invalid_requests` → `data[0]` con `status`, `warnings[]` (`line`, `id`, `message`), `errors_total_count`, `ids_of_invalid_requests[]` (ids de artículo). Errores 80009 (demasiadas llamadas), 100, 190 | `[V]` [CB] |
| Valores de `status` distintos de `finished`, y un campo `errors[]` en esa respuesta | `[NO VERIFICADO]` (la página solo muestra `finished`) |
| `GET /{waba_id}/product_catalogs` → `{"data": [ProductCatalog…]}`; leer pide `whatsapp_business_management`, `whatsapp_business_messaging`, **`catalog_management`**; errores 100, 200, 80008. No admite borrar ni actualizar | `[V]` [PC] |
| Una WABA, un catálogo, compartido por todos sus números | `[V]` [UI] |
| `catalog_management` depende de `business_management`; su App Review pide un video creando, editando y borrando un catálogo; la página no dice si basta acceso estándar | `[V]` [CM] / nivel `[NO VERIFICADO]` |
| Que `link` pueda omitirse en un catálogo solo de WhatsApp, o que Meta acepte `https://wa.me/…` | `[NO VERIFICADO]` — [CR] apunta en contra (ver §11, R1) |
| Que COP, VES y UYU se acepten como moneda de artículo; estado de revisión por artículo por API | `[NO VERIFICADO]` |

## 3. Tablas (revisión `0154_whatsapp_catalog_sync`)

Todas: `tenant_id uuid NOT NULL` → `tenants.id`; `ENABLE` + `FORCE ROW LEVEL SECURITY`; política
`tenant_isolation` con `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`;
`UNIQUE (id, tenant_id)` para las FK compuestas, como las tablas de 0057; `downgrade()` borra las
tres. Prueba `-m db`: el negocio A no ve filas de B por `tenant_session`.

**`whatsapp_catalogs`** — uno por (marca, WABA).
`id uuid PK` · `tenant_id` · `brand_id uuid NOT NULL → brands.id ON DELETE CASCADE` ·
`phone_number_row_id uuid NOT NULL` (FK compuesta `(phone_number_row_id, tenant_id)` →
`whatsapp_phone_numbers (id, tenant_id)`) · `waba_id text NOT NULL` · `catalog_id text NOT NULL` ·
`link_url text NULL CHECK (link_url LIKE 'https://%')` (sitio web del negocio para el campo `link`
de Meta, dado en el alta; §5 y R1) · `source text NOT NULL CHECK IN ('qualify','manual')` (`qualify` = Qualify escribe artículos; esta
entrega solo crea `qualify`; `manual` queda para la opción B) · `access_state text NOT NULL DEFAULT
'ok' CHECK IN ('ok','missing_permission','auth_error')` · `access_checked_at timestamptz NOT NULL` ·
`connected_by uuid NOT NULL → users.id` · `connected_at`, `updated_at timestamptz NOT NULL`.
`UNIQUE (waba_id)` (un catálogo por WABA, [UI]) · `UNIQUE (brand_id)` · índice `(tenant_id)`.

**`whatsapp_catalog_items`** — una por producto enviado alguna vez.
`id uuid PK` · `tenant_id` · `catalog_row_id uuid NOT NULL` (FK compuesta → `whatsapp_catalogs`,
`ON DELETE CASCADE`) · `product_id uuid NULL → brand_products.id ON DELETE SET NULL` (la fila
sobrevive al producto para poder borrar el artículo en Meta) · `retailer_id text NOT NULL` ·
`state text NOT NULL CHECK IN ('queued','uploading','synced','error','deleted')` · `pending_op text
NULL CHECK IN ('upsert','delete')` · `pending_hash text NULL` · `last_pushed_hash text NULL` (el
último que Meta aceptó) · `last_pushed_at timestamptz NULL` · `error_code text NULL` (enumeración
§4.3) · `meta_error_code int NULL` · `sync_version int NOT NULL DEFAULT 0` (+1 en cada encolado) ·
`last_run_id uuid NULL → whatsapp_catalog_sync_runs.id ON DELETE SET NULL` · `pipeline_version text
NOT NULL` (versión del mapeo §5, p. ej. `wa-catalog-map-v1`) · `created_at`, `updated_at`.
`UNIQUE (catalog_row_id, retailer_id)` · índice único parcial `(catalog_row_id, product_id) WHERE
product_id IS NOT NULL` · índices `(tenant_id)`, `(last_run_id)`.

**`whatsapp_catalog_sync_runs`** — una por llamada a `items_batch` (el outbox).
`id uuid PK` · `tenant_id` · `catalog_row_id` (FK compuesta) · `request_key text NOT NULL` ·
`trigger text NOT NULL CHECK IN ('upload_one','resync_one','sync_all')` · `status text NOT NULL
CHECK IN ('pending','sending','sent','finished','partial','failed')` · `item_ids uuid[] NOT NULL`
(filas de `whatsapp_catalog_items`, ≤ 1.000) · `upserts int NOT NULL`, `deletes int NOT NULL`,
`items_failed int NULL` · `handle text NULL` · `attempts int NOT NULL DEFAULT 0` ·
`next_attempt_at timestamptz NOT NULL` · `locked_by text NULL`, `locked_at timestamptz NULL` ·
`error_code text NULL`, `meta_error_code int NULL` · `requested_by uuid NOT NULL → users.id` ·
`requested_at`, `sent_at`, `finished_at timestamptz` · `pipeline_version text NOT NULL`.
`UNIQUE (tenant_id, request_key)` · índice parcial de reclamo `(next_attempt_at) WHERE status IN
('pending','sending','sent')` · índice `(catalog_row_id, sent_at)` para el tope por hora.

**Permisos.** `qualify_app`: `SELECT, INSERT, UPDATE, DELETE` en `whatsapp_catalogs`; `SELECT,
INSERT` en los artículos y `UPDATE` **por columna** sin `retailer_id`, `catalog_row_id`,
`tenant_id` (el `retailer_id` inmutable lo hace cumplir Postgres, no la disciplina); `SELECT, INSERT,
UPDATE` en las corridas (sin `DELETE`: son la procedencia). `qualify_admin`: `SELECT` solo en
`whatsapp_catalogs` (operación y descubrimiento). Ninguno para `qualify_webhook*` ni
`qualify_credential`.

**Volumen.** Artículos ≤ productos (Bianki: 22). Corridas: ~5 por negocio y día en el peor uso →
~1.800 filas/año/negocio, < 1 MB. Retención de corridas: seguimiento (§10).

## 4. Hash de contenido y estados

### 4.1 Hash
`content_hash = sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))`
sobre **el `data` exacto que se enviaría a Meta** (§5) más `"_v": pipeline_version`. Entra todo lo
que Meta ve: título, descripción, precio y moneda, disponibilidad, condición, marca, `link` y la URL
de la imagen (que incluye `media_id`: cambiar la foto principal cambia la URL, como exige [CR]).
Un cambio de nombre del negocio, del número o del mapeo deja el artículo desactualizado, a propósito.

### 4.2 Estado por producto que lee la pantalla (calculado, §9)

| Estado | Regla (en orden) |
|---|---|
| `queued` / `uploading` | artículo en `queued` / `uploading` (incluye un borrado pendiente) |
| `error` | artículo en `error` (con `error_code`) |
| `not_eligible` | sin artículo vivo y el producto no es elegible; razón ∈ `inactive`, `no_price`, `no_currency`, `no_photo`, `photo_format`, `photo_too_small` (también un artículo `synced` cuyo producto sigue activo pero dejó de ser elegible, §12) |
| `not_uploaded` | sin artículo, o artículo `deleted` |
| `out_of_date` | `synced` y `content_hash(actual) ≠ last_pushed_hash`, o producto inactivo (se borrará) |
| `synced` | `synced` y hash igual |

Elegible = `is_active` y `price_amount > 0` y `price_currency` cumple `^[A-Z]{3}$` y tiene foto
principal JPEG o PNG (`photo_format` si no) con `width ≥ 500` y `height ≥ 500`.

### 4.3 Errores de artículo (`error_code`)
`meta_rejected` (en `ids_of_invalid_requests` o con `errors` en `validation_status`) ·
`meta_unconfirmed` (24 h sin `finished`) · `no_permission` · `send_failed` (reintentos agotados).
Nunca se guarda ni se registra el `message` de Meta (puede repetir el título del dueño).

### 4.4 Máquina de la corrida (la mueve solo el worker, salvo la creación)
`pending` (servicio) → `sending` (reclamo) → `sent` (`handles` guardado) → `finished` (cero
inválidos) | `partial` (algunos inválidos) | `failed`. `sending` → `pending` ante error transitorio,
80014/80009, o reclamo vencido (> 10 min). `pending`/`sending` → `failed` al agotar intentos o por
error de autorización. Un `handles` vacío → `failed` con `error_code='nothing_ingested'`.

## 5. Mapeo Qualify → Meta (`pipeline_version = wa-catalog-map-v1`)

| Campo Meta | Origen | Regla / respaldo |
|---|---|---|
| `id` | `whatsapp_catalog_items.retailer_id` | `str(product.id)` al crear la fila; nunca se recalcula |
| `title` | `brand_products.name` | `strip()`, recortado a 100 caracteres por grafema, sin «…» |
| `description` | `brand_products.description` | vacía → el nombre; texto plano; recorte a 5.000 |
| `brand` | `brands.name` | recorte a 100 [H] |
| `price` | `price_amount`, `price_currency` | `f"{amount.quantize(Decimal('0.01'))} {currency}"` → `12500.00 COP`; punto decimal, sin miles |
| `availability` | — | `in stock` (solo se suben productos activos) |
| `condition` | — | `new` |
| `link` | `whatsapp_catalogs.link_url` (sitio web del negocio, dado en el alta con `--link-url`) | sin sitio: `https://wa.me/{dígitos de display_phone_number}` — `[NO VERIFICADO]`, ver R1 |
| `image` | foto principal (`ProductRecord.primary_photo_key`, su fila `product_media`) | `[{"url": <URL firmada §8>}]`, sin `tag` |
| `method` | — | `UPDATE` con `allow_upsert=true` (crea o actualiza, idempotente); `DELETE` con `data={"id": retailer_id}` |

## 6. Las tres acciones (`qualify_api.whatsapp.catalog_sync.service`)

```python
def plan_catalog_sync(*, tenant_id: UUID, brand_id: UUID) -> SyncPlan
# SyncPlan(new: int, changed: int, deletes: int, unchanged: int, in_flight: int,
#          not_eligible: Mapping[str, int], plan_key: str)   # nada se escribe
def upload_product(*, tenant_id: UUID, brand_id: UUID, product_id: UUID,
                   requested_by: UUID) -> EnqueueResult
def resync_product(*, tenant_id: UUID, brand_id: UUID, product_id: UUID,
                   requested_by: UUID) -> EnqueueResult
def sync_all(*, tenant_id: UUID, brand_id: UUID, requested_by: UUID,
             plan_key: str) -> EnqueueResult
# EnqueueResult(run_ids: tuple[UUID, ...], upserts: int, deletes: int,
#               unchanged: int, in_flight: int)
```

- **Cargar uno:** exige catálogo `source='qualify'` y `access_state='ok'`, producto elegible y sin
  artículo vivo; crea la fila del artículo (`retailer_id`) en `queued` —o reutiliza la fila `deleted` de ese
  mismo producto, que conserva su `retailer_id`— y una corrida de 1.
- **Resincronizar uno:** exige artículo `synced` o `error`; si el hash no cambió y no está en
  `error`, no encola nada (`unchanged=1`). Producto ya inactivo → encola su `DELETE`.
- **Sincronizar todos:** recalcula el plan; si su `plan_key` ≠ el que vio la persona → `PlanChanged`
  (la pantalla vuelve a mostrar la confirmación). Encola altas nuevas + cambiadas elegibles y
  `DELETE` de artículos vivos cuyo producto está inactivo o desapareció (`product_id IS NULL`);
  omite los iguales y los que ya están en vuelo. Trozos de ≤ 1.000 artículos por corrida.
- **Idempotencia:** `request_key = sha256(catalog_row_id ‖ trigger ‖ sorted((item_id, op,
  hash, sync_version)))` (con `sync_version`: reintentar un artículo en `error` sin cambios es una
  petición nueva; un doble clic sigue siendo la misma), `INSERT … ON CONFLICT (tenant_id, request_key) DO NOTHING`; los artículos se toman con
  `SELECT … FOR UPDATE` y uno en `queued`/`uploading` nunca entra en otra corrida. Pedir dos veces
  sin cambios no encola nada. Errores al usuario como excepciones tipadas (`CatalogNotConnected`,
  `CatalogPermissionMissing`, `ProductNotEligible(reason)`, `PlanChanged`), sin texto de usuario.
- Todo por `tenant_session(tenant_id)`; nada llama a Meta.

## 7. Worker (dentro de `whatsapp-worker`)

**Por qué no en la petición:** Meta procesa el lote en diferido (`handle` + consulta), hay límites
por catálogo (80014) y reintentos; un lote de 1.000 bloquearía Reflex. Regla 7 de la casa.

- `CatalogSyncTick` en `whatsapp/catalog_sync/worker.py`, con el mismo `TenantSource`
  (`ScopedTenants` con `--tenant`, `DiscoveredTenants` con `--all-tenants`). `whatsapp/worker.py`
  la lanza como **tarea asyncio aparte** del mismo proceso cada `--catalog-interval` segundos
  (por defecto 30; `0` la apaga), para que una llamada lenta a Meta no frene los envíos del
  outbox. Sin cambios en `docker-compose.prod.yml`. Local: `just whatsapp-tick --tenant <uuid>`.
- **Reclamo** por inquilino: `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` sobre corridas con
  `next_attempt_at ≤ now()` y `status IN ('pending','sent')` o `('sending' y locked_at < now()-10
  min)`.
- **Envío** (`pending`): si el catálogo ya tuvo **≥ 10 envíos en la última hora** (`sent_at`), se
  deja para luego. Si no: `status='sending'`, `attempts+1`, se construye `data` desde el estado
  actual del producto (§5), se guarda `pending_hash` y `state='uploading'` en cada artículo, se
  hace commit y después `POST /{catalog_id}/items_batch` con `item_type=PRODUCT_ITEM`,
  `allow_upsert=true`, `requests=<JSON>`. Reenviar tras una caída es seguro: `UPDATE`+upsert y
  `DELETE` por `id` son idempotentes en Meta.
- **Respuesta:** guarda `handles[0]`, `sent_at`, `status='sent'`, `next_attempt_at=now()+30 s`;
  los artículos con `errors` en `validation_status` pasan ya a `error/meta_rejected`.
- **Consulta** (`sent`): `GET /{catalog_id}/check_batch_request_status` (§2). Sin `finished` →
  reintento con espera 30 s, 1, 2, 5, 10 min (tope); a las 24 h → `failed`, artículos
  `meta_unconfirmed`. Con `finished`: ids en `ids_of_invalid_requests` → `error/meta_rejected`;
  el resto → `synced`, `last_pushed_hash=pending_hash`, `last_pushed_at`; los `DELETE` → `deleted`.
  Corrida `finished` o `partial`, `items_failed`.
- **Errores:** 80014/80009 → `pending` a +15 min. Transporte o 5xx → `pending` con espera 1, 5,
  15, 60 min; al 5.º intento `failed` y artículos `error/send_failed`. Autorización
  (`WhatsAppApiError.is_auth_error`; 190 → `auth_error`; 200/10 → `missing_permission`) →
  corrida `failed`, artículos `error/no_permission`, `whatsapp_catalogs.access_state` actualizado:
  la pantalla deja de ofrecer acciones y muestra «falta permiso».
- **Cliente:** `HttpWhatsAppCatalogClient(graph_client: AuthenticatedClient, graph_url: str,
  catalog_id: str)` con `items_batch(requests) -> BatchAck` y `batch_status(handle) ->
  BatchStatus`, reutilizando `_raise_for_status`/`_json_object` de `client.py`. El
  `AuthenticatedClient` sale de `CredentialResolver` por la `connection_id` del número del
  catálogo (el mismo token de usuario del sistema). Versión de Graph: `MetaOAuthSettings.graph_url`.
- **Registros:** solo `tenant_id`, `run_id`, `catalog_row_id`, conteos, `status`, códigos.
- **Costo:** las llamadas a Meta no cuestan; no hay guardián de precio (no hay llamada pagada), el
  tope por hora hace de guardián de cuota.

## 8. Ruta pública y estable de la foto

- `GET/HEAD /public/catalog-media/{tenant_id}/{media_id}/{sig}.jpg`, router propio bajo
  `/public/` (`http/public_catalog_media_routes.py`), como ADR 28e.
- `sig = base64url(HMAC-SHA256(K, DOMAIN ‖ tenant_id ‖ 0x00 ‖ media_id))` (enmienda del hilo
  principal, 2026-11-12: sin `object_key`, para que la firma se compruebe **antes** de tocar la
  base; la llave del objeto es inmutable por fila, así que no hace falta atarla) sin
  relleno (43 caracteres), `DOMAIN = b"qualify:wa-catalog-media:v1\x00"`,
  `K = QUALIFY_OAUTH_STATE_SECRET` — mismo patrón que `ads/edit_review.py`, ya presente en `api` y
  `whatsapp-worker` vía `*app-env` (con `:?` en producción). **No hay variable nueva ni nada que
  preparar en el servidor.** Si el secreto falta, es el de desarrollo o mide < 32, la ruta responde
  404 y el servicio rechaza encolar (`CatalogMediaUnavailable`). URL base:
  `QUALIFY_PUBLIC_MEDIA_BASE_URL` (existente).
- **Orden de comprobación**, todo con **el mismo 404** byte a byte (`{"detail":"not found"}`):
  forma de UUID y firma (`hmac.compare_digest`, antes de tocar la base) → por
  `tenant_session(tenant_id)`: fila `product_media` de tipo imagen con ese `id` → su producto tiene
  un artículo no `deleted` en un catálogo del negocio →
  `ObjectGate` abre el objeto con la comprobación de prefijo del inquilino
  (`TenantPrefixViolation` → 404) → objeto ausente → 404.
- **Respuesta:** `Content-Type` de la fila (`image/jpeg`), `Content-Length`, rangos como
  `public_media_routes.py`, `Cache-Control: public, max-age=86400` (el objeto es inmutable: cada
  archivo tiene llave nueva).
- **Revocación:** borrar la foto (fila fuera), quitar el artículo (`deleted`), cambiar la foto
  principal (la URL vieja deja de estar en el catálogo; la nueva tiene otro `media_id`), o rotar el
  secreto (todas caen; el hash cambia y la pantalla las marca desactualizadas).
- **Amenazas:** ruta sin sesión; no enumerable (firma de 256 bits por medio, sin listado); no lee
  nada que no esté ya cargado al catálogo, que es público por intención; sin prefijo público en R2
  (ADR 22); un 404 uniforme no distingue «no existe» de «firma mala». Ancho de banda: Meta baja
  ~200 KB por artículo cuando quiere; egreso de R2 sin costo.

## 9. CLI de alta del catálogo y lectura para la pantalla

`python -m qualify_api.whatsapp.catalog_sync.connect --tenant <uuid> --brand <uuid> --catalog-id
<id> [--link-url <https://…>] [--user <uuid>]` (`just whatsapp-catalog-connect …`):
1. El número de la marca debe estar conectado (`whatsapp_phone_numbers`) → `waba_id`, conexión.
2. `GET /debug_token` sobre `QUALIFY_WA_SYSTEM_USER_TOKEN` (como `connect.py`, nunca impreso):
   válido y con `catalog_management` **y** `business_management` (`CATALOG_REQUIRED_SCOPES`, nuevo;
   `connect.REQUIRED_SCOPES` no cambia). Si no → exit 2, nada escrito.
3. Con la credencial guardada (`CredentialResolver`): `GET /{waba_id}/product_catalogs`; el
   `catalog_id` debe estar en `data[].id`. Autorización rechazada → exit 3; no conectado → exit 5.
4. Upsert por `waba_id` con `access_state='ok'`; repetirlo solo refresca. Si la WABA ya tiene
   **otro** `catalog_id` con artículos vivos → exit 6 (cambiar de catálogo deja huérfanos).
   Exit 1 error de API, 4 uso.

**Lectura:** `catalog_sync_view(*, tenant_id, brand_id) -> CatalogSyncView(connection:
Literal['none','connected','missing_permission','auth_error'], last_run: RunSummary | None,
products: Mapping[UUID, ProductSyncState(state, reason)])` en **tres consultas fijas** (catálogo +
última corrida; productos con su foto principal; artículos del catálogo), cálculo en memoria (§4.2).

## 10. Fuera de alcance y seguimientos

Sincronización automática al editar (D2 la descarta hoy) · estado de revisión por artículo
(`GET /{catalog_id}/products?fields=retailer_id,review_status`, `[NO VERIFICADO]`) · columna `sku`
e importación CSV (CAT-03) · mensajes de producto/multiproducto (CAT-01) · carrito → pedido (hoy un
`order` entrante se guarda como `other`, CAT-02) · `is_catalog_visible` por API · retención de
corridas (proponer 180 días) · catálogos en VES diario.

**Lo que debe hacer el fundador en Meta antes de producción:** crear el catálogo en Commerce
Manager dentro del portafolio Qualify.co y conectarlo a la WABA del negocio; asignarlo al usuario
del sistema con control total; regenerar el token con `catalog_management` + `business_management`
+ los dos de WhatsApp; correr de nuevo el alta del número y luego `just whatsapp-catalog-connect`;
activar «mostrar catálogo» del número. **Prueba P1 en vivo (ADR 25):** subir un producto de Bianki
y comprobar `finished` sin inválidos y la imagen bajada por Meta.

**App Review:** para catálogos de negocios que el fundador no administra, `catalog_management`
entra en la lista (como `ads_management` en ADR 38); la revisión es por permiso (ADR 29).

## 11. Riesgos y qué reabre esta decisión

- **R1 `link`.** [CR] pide el dominio del negocio y excluye dominios de Facebook; `wa.me` puede ser
  rechazado. Mitigación ya incluida: el alta acepta `--link-url` con el sitio del negocio (Bianki
  tiene uno) y solo sin sitio se usa `wa.me`. Si P1 lo rechaza: página pública mínima del producto servida por Qualify (decisión
  aparte) o pedir el sitio web al dueño.
- **R2 permiso.** Si el token no puede llevar `catalog_management` con acceso estándar → vuelve la
  opción B (D1).
- **R3 moneda.** Si Meta rechaza COP/VES/UYU → catálogo en USD y la moneda pasa a ser del catálogo.

| Descartado | Por qué |
|---|---|
| Proceso `whatsapp-catalog-worker` nuevo | Exige tabla de opciones y firma (regla 2); el volumen cabe en el worker actual |
| Archivo programado (`product_feeds`) | Refresca a su intervalo y con `deletion_enabled` un archivo vacío borra todo |
| Llamar a Meta en la petición de Reflex | Lote diferido, límites y reintentos (§7) |
| `retailer_id` = `slug` | El `slug` cambia al renombrar |
| Prefijo público en R2 o URL prefirmada larga | ADR 22; una prefirmada caduca y Meta re-descarga |
| Variable `QUALIFY_CATALOG_MEDIA_SECRET` nueva | Hay que prepararla en producción; la derivación con dominio da la misma separación |

**Reabre:** > 5 % de artículos rechazados por `link` o imagen en un mes; > 10 lotes/hora necesarios
por catálogo; un negocio con > 3.000 productos; el fundador pide sincronización automática.

## 12. Implementación (m-25017356, 2026-11-12) — lo que el código hace distinto o precisa

Código: `packages/api/src/qualify_api/whatsapp/catalog_sync/`, ruta
`http/public_catalog_media_routes.py`, revisión `0154_whatsapp_catalog_sync`.

- **Elegibilidad:** razón nueva `photo_format` (foto principal que no es JPEG ni PNG; Meta solo
  acepta esos dos [CR]).
- **`request_key`** incluye el `sync_version` de cada artículo (§6).
- **Acciones:** `upload_product` sobre un producto que ya tiene artículo vivo se comporta como
  «Resincronizar» (no falla; sin cambios no encola nada). `resync_product` sin artículo vivo →
  `ItemNotUploaded`. Excepciones extra: `ProductNotFound`, `ItemNotUploaded`, base
  `CatalogSyncError`; `CatalogMediaUnavailable` vive en `media_url` y se reexporta en `service`.
- **Lectura (§9):** un artículo `synced` cuyo producto sigue activo pero ya no es elegible se
  muestra `not_eligible` con la razón (resincronizarlo no podría enviarlo). Si en el proceso no se
  puede construir la URL de la foto (secreto o URL base ausentes), los `synced` se muestran
  `synced` (no hay contra qué comparar) y las acciones rechazan con `CatalogMediaUnavailable`.
  Un catálogo `source='manual'` se lee como `connection='none'`.
- **Worker:** el descubrimiento con `--all-tenants` lee `whatsapp_catalogs` (el `SELECT` de
  `qualify_admin` es para eso), no los números. Al enviar, un `upsert` cuyo producto se borró o
  quedó inactivo se manda como `DELETE`; uno que dejó de ser elegible se deja fuera y el artículo
  vuelve a `synced` (si alguna vez se subió) o `deleted`. 80014/80009 no cuentan como intento.
  Un 4xx que no es de autorización ni de límite → `failed` + `send_failed` de inmediato
  (`error_code='meta_error'`): reenviar lo mismo no lo arregla. Sin URL de foto →
  `failed`/`media_unavailable`. Un error de autorización actualiza `access_state` pero no degrada la
  conexión del número (los mensajes siguen su propio camino, QUA-90). `just whatsapp-tick` (`--once`)
  hace una pasada del outbox y luego una del catálogo.
- **CLI de alta:** marca sin número conectado → exit 4 (precondición, nada escrito). Sin
  `--link-url` al repetir, se conserva el sitio guardado. Si la WABA y la marca apuntan a filas
  distintas, o la WABA ya está registrada en otro negocio → exit 6.
- **Esquema:** FK compuesta `(brand_id, tenant_id) → brands (id, tenant_id)`; el `UPDATE` por
  columna de `qualify_app` sobre los artículos excluye también `id`. El secreto se lee de
  `QUALIFY_OAUTH_STATE_SECRET` directamente (mismas reglas que `ads/edit_review.py`) para no exigir
  el resto de la configuración de Meta en la API.
