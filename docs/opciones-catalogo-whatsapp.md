# Catálogo de WhatsApp (WA-23): tres opciones para el fundador

`[v1 2026-11-03 · m-24936714]` · Catálogo nativo de WhatsApp para negocios con muchos productos
(ferreterías, no solo comida): hecho a mano en Commerce Manager, sincronizado desde Qualify, o ambos
· Fecha de acceso de las fuentes de Meta: **2026-11-03**.

Convención de evidencia: `[V]` verificado en fuente oficial (URL) · `[S]` secundaria · `[H]`
hipótesis/estimación · `[F]` decisión del fundador · `[NO VERIFICADO]` no pude confirmarlo hoy.
Las URL de Meta se citan abreviadas como **[M-n]** y se listan completas al final de §2.

## Decisión del fundador (pendiente)

_Esta sección mandará sobre el resto cuando Herwin elija._ Opción elegida: — · Fecha: — ·
Condiciones: —. Estado del documento: `[PROPUESTO]`.

## 0. La pregunta y qué buscamos esta vez

**La pregunta, en palabras del fundador:** ¿le damos a los negocios un catálogo nativo de WhatsApp
(el de la tiendita con carrito), y lo armamos a mano en Meta o lo subimos y mantenemos al día desde
el catálogo de Qualify, incluido el precio?

**Disparador:** el número real de Bianki quedó conectado en producción el 2026-11-03 `[F]`, y el
fundador ve el catálogo como módulo para negocios con **cientos de referencias**, por ejemplo una
ferretería, no solo comida `[F]`.

**Para el dueño del negocio:** hoy el cliente final ve el menú como listas de 10 filas con «Ver
más»; con catálogo nativo vería fotos, precio y un carrito, y el pedido le llega al dueño ya armado
(producto, cantidad, precio). Para una ferretería con 400 referencias, las listas de 10 son
inservibles; el catálogo no.

**Qué buscamos esta vez (propuesta): aprender.** Antes de construir una sincronización, saber si
(1) Meta acepta nuestro catálogo y nuestro token en la WABA de Qualify.co, (2) los clientes finales
de un negocio real usan el carrito, y (3) el dueño de una ferretería mantendría su catálogo en
Qualify. Adopción vendrá después; hoy no hay ningún negocio con cientos de productos cargados.

## 1. Lo que ya existe en Qualify

| Pieza | Dónde | Qué hace hoy | Qué le falta para un catálogo de Meta |
|---|---|---|---|
| Productos | `packages/api/src/qualify_api/catalog/models.py` (`brand_products`, migración 0038) | nombre, `slug` único por marca (derivado del nombre), descripción, `price_amount Numeric(12,2)` + `price_currency` texto, categoría, etiquetas, `is_active`, `position` | **No hay columna `sku`/código.** El `retailer_id` de Meta debe ser estable; el `slug` cambia si se renombra el producto → no sirve como clave |
| Fotos y videos | mismo archivo (`product_media`, `object_key` en R2) | normalizados al subir | Sin URL pública estable (ver abajo) |
| Alta de productos | `catalog/service.py` `create_product` | uno por uno desde «Tus productos» | **No existe importación por CSV ni por lotes** (revisado también `Qualify/catalog_*.py`) |
| Menú de WhatsApp | `whatsapp/catalog.py`, `whatsapp/menus/schema.py` (`ProductsNode`) | WA-15: pinta `brand_products` como listas interactivas, 10 filas por mensaje con «Ver más», agrupadas por categoría | Nada; es la opción A |
| Pedidos | `whatsapp/orders.py` | el pedido confirmado se guarda en `whatsapp_thread_state.context["_order"]`, idempotente por `wamid` de entrada | No entiende el mensaje entrante `type=order` de Meta |
| Conexión del número | `whatsapp/connect.py` | `GET /debug_token`; exige `whatsapp_business_messaging` + `whatsapp_business_management` (`REQUIRED_SCOPES`) | **`catalog_management` no se exige ni se ha visto** en el token; `business_management` tampoco está en `REQUIRED_SCOPES` (la guía de WA-13 dice que el token se generó con él; no se comprobó en vivo) |
| Cliente Graph | `whatsapp/client.py` | botones, listas, media, plantillas | **No hay constructores de mensajes `product` / `product_list` / `catalog_message`** |
| Envío | `whatsapp/outbox.py`, `whatsapp/worker.py` | patrón outbox idempotente | Reutilizable tal cual |
| URL pública de imágenes | `http/public_media_routes.py` + `qualify_shared/objects/gate.py` | `GET /public/media/{token}` con **tokens en Redis que caducan** (hechos para que Meta descargue una pieza al publicar) | Un catálogo de Meta necesita **URL estables**: Meta vuelve a bajar la imagen cuando quiere. Es el punto de diseño real de la opción C |

`docs/plan-modulo-whatsapp-cloud-api.md` §5.5 ya lo anticipó: «Es un conector, no un modelo nuevo».
Sigue siendo cierto para el producto, pero el conector necesita tres cosas que no existen: código
estable por producto, carga por lotes y URL públicas estables.

## 2. Lo que dice Meta hoy (verificado)

### 2.1 Conexión y permisos

| Afirmación | Nivel | Fuente |
|---|---|---|
| Un catálogo se crea por la Commerce API o en Commerce Manager; si el negocio ya tiene uno, debe usar ese | `[V]` | [M-2] |
| **Una WABA admite un solo catálogo**, y ese catálogo sirve a todos los números de la WABA | `[V]` | [M-2] |
| Se conecta por API con `POST /{waba_id}/product_catalogs` y `catalog_id`; devuelve `success`; no se puede actualizar ni borrar por ese borde | `[V]` | [M-3] |
| Leer ese borde pide `whatsapp_business_management`, `whatsapp_business_messaging`, **`catalog_management`** y `public_profile`; para el POST la página no lista permisos | `[V]` | [M-3] |
| `catalog_management` permite crear, leer, actualizar y borrar catálogos de negocio de los que el usuario es administrador; **depende de `business_management`** | `[V]` | [M-4] |
| La página de `catalog_management` no dice si basta acceso estándar; la verificación del negocio se exige para todo acceso avanzado | `[V]` (lo que dice) / `[NO VERIFICADO]` (el nivel) | [M-4] |
| Por la interfaz: WhatsApp Manager → Catálogo → Elegir catálogo → Conectar; el catálogo debe ser del mismo portafolio que la WABA | `[S]` | Kommo, 360dialog, WANotifier (2026-11-03) |
| Socio con cliente que ya tiene catálogo: el cliente le da acceso de gestión y el socio conecta en WhatsApp Manager; cliente sin catálogo: se crea bajo el business ID del socio | `[V]` | [M-2] |
| Ajustes por número: `/{phone_number_id}/whatsapp_commerce_settings` con `is_cart_enabled` (por defecto `true`) e `is_catalog_visible` (por defecto `false`) | `[V]` | [M-5] |
| Qué activo hay que asignar al usuario del sistema en Business Settings (catálogo con «Administrar catálogo») | `[NO VERIFICADO]` | — |

**Lectura para Qualify.** `catalog_management` **sí hace falta** para cualquier camino que toque el
catálogo por API (opción C; y para que Qualify **lea** por API qué catálogo está conectado). En la
opción B, el dueño (o el fundador) conecta el catálogo en la interfaz, el `catalog_id` se registra
**a mano** en Qualify (`source = manual`, §4) y Qualify solo **envía** mensajes con `catalog_id` +
`product_retailer_id` y **lee** el webhook `order`: para eso basta `whatsapp_business_messaging`
[M-6]. Por ADR 29, el acceso estándar funciona para activos que el fundador administra; que también
valga para `catalog_management` es lo más probable pero **no lo verifiqué**: se prueba regenerando
el token del usuario del sistema con ese permiso y llamando `GET /{waba_id}/product_catalogs`
(ADR 25: verificado en vivo, no por documentación).

### 2.2 Carga de productos

| Afirmación | Nivel | Fuente |
|---|---|---|
| `POST /{catalog_id}/items_batch`: hasta **5.000** solicitudes por llamada (recomienda < 3.000), carga ≤ 28 MB; métodos `CREATE`, `UPDATE`, `DELETE`; `allow_upsert` por defecto `true` | `[V]` | [M-7] |
| Para `PRODUCT_ITEM` exige `availability`, `brand`, `condition`, `description`, `id`, `image`, `link`, `price`, `title` | `[V]` | [M-7] |
| `price` es texto «monto + espacio + ISO 4217», p. ej. `9.99 USD` | `[V]` | [M-7] |
| `availability`: `in stock`, `out of stock`, `available for order`, `discontinued` | `[V]` | [M-7] |
| Cada llamada devuelve `handles` para consultar `check_batch_request_status`; el límite es por catálogo según la fórmula «Catalog Batch» (error 80014), sin cifra fija | `[V]` | [M-7] |
| Que un catálogo solo para WhatsApp pueda omitir `link` | `[NO VERIFICADO]` (la referencia general lo exige) | [M-7] |
| `POST /{catalog_id}/product_feeds` con `schedule` (ejemplo `DAILY` a una hora) apuntando a un archivo que alojamos (TSV, XML o comprimido); `update_schedule` solo crea/actualiza, nunca borra («útil para precio y disponibilidad»); `deletion_enabled` por defecto `true` y no se puede apagar después | `[V]` | [M-8] |
| Intervalos menores a un día (`HOURLY`) | `[NO VERIFICADO]` (la página remite a otra referencia) | [M-8] |
| Meta revisa los artículos automáticamente y puede rechazarlos; se apela en Commerce Manager | `[V]` | [M-1] |
| Límite de artículos por catálogo | `[NO VERIFICADO]` | — |

**Lote o archivo programado.** Para «el precio cambió, que se vea ya», el lote (`items_batch`) es
mejor: actualiza solo lo que cambió, minutos después, y devuelve un `handle` que nos da
idempotencia y estado por artículo. El archivo programado es más barato de construir (un endpoint
que sirve un TSV) pero refresca como mucho a su intervalo, y con `deletion_enabled` un archivo
vacío por error **borra el catálogo entero**. Recomendación técnica: lote como mecanismo, y nada de
archivo programado salvo como respaldo con `update_schedule` (que no borra).

### 2.3 Mensajes y pedidos

| Afirmación | Nivel | Fuente |
|---|---|---|
| Mensaje de catálogo (miniatura del catálogo entero), de producto único, multiproducto y carrusel de productos | `[V]` | [M-1] |
| Multiproducto: **hasta 30 productos** en secciones; encabezado de texto obligatorio; `catalog_id` + `product_retailer_id`; no necesita plantilla | `[V]` | [M-9] |
| Producto único y multiproducto solo se envían **dentro de conversaciones existentes**, no como notificación | `[V]` | [M-6], [M-9] |
| Existen plantillas de catálogo, de producto único, multiproducto y carrusel (para escribir fuera de la ventana) | `[V]` | [M-0] |
| Carrito: hasta 99 unidades por artículo, sin tope de artículos distintos; no caduca; **el negocio no puede editarlo ni mandarlo** | `[V]` | [M-1] |
| Por la Cloud API **no aparece el ícono de carrito** en la cabecera del chat | `[V]` | [M-1] |
| El pedido entra como webhook `messages[].type = "order"` con `order.catalog_id`, `order.text` y `product_items[]` (`product_retailer_id`, `quantity`, `item_price`, `currency`) | `[V]` | [M-10] |
| Los mensajes fuera de plantilla solo van dentro de la ventana de 24 h | `[V]` | [M-11] |
| **Desde el 2026-10-01 Meta volvió a cobrar los mensajes de servicio, por mensaje, con 1.000 gratis al mes por número**; la tarifa de Colombia está en la tabla CSV/PDF | `[V]` | [M-12] |

**Lectura para Qualify.** El pedido de Meta es **informativo**: llega con precio y cantidad, pero
el pago se coordina fuera de WhatsApp (§2.4). Encaja con lo que ya hace `orders.py`: un pedido
confirmado se guarda una vez por `wamid` y un humano lo atiende. Lo nuevo es mapear
`product_retailer_id` → `brand_products.id`. **Ojo con el cobro de mensajes de servicio:** afecta a
todo el módulo de WhatsApp, no solo al catálogo, y contradice el supuesto de «servicio gratis» de
docs anteriores; hay que revisarlo aparte.

### 2.4 Límites: precio y moneda, existencias, pagos, revisión

| Afirmación | Nivel | Fuente |
|---|---|---|
| Un precio por artículo en una moneda (`price` es un solo texto con un código ISO); `currency` del pedido es «la moneda del catálogo» | `[V]` | [M-7], [M-10] |
| Si Commerce Manager acepta **VES**, **COP** y **UYU** como moneda de catálogo | `[NO VERIFICADO]` (solo hallé la tabla de pagos antigua de Meta, que no aplica) | — |
| **No hay existencias por cantidad**: solo el estado `availability` | `[V]` (por los campos de `items_batch`) | [M-7] |
| Pagos dentro de WhatsApp: la documentación solo tiene guías para **India, Brasil y México** | `[V]` | [M-0] |
| Por tanto, en Colombia, Venezuela y Uruguay el pedido no se paga dentro de WhatsApp | `[H]` sobre `[V]` | inferido de [M-0] |
| Las ventas deben cumplir las Políticas de Comercio; artículos rechazados se apelan | `[V]` | [M-1] |
| Productos de ferretería que las Políticas de Comercio restringen (químicos, armas, herramientas peligrosas) | `[NO VERIFICADO]` | — |

**Venezuela.** Con un solo precio por moneda, el negocio tiene que escoger: catálogo en USD (lo
habitual en el comercio venezolano) y el bolívar se habla en el chat, o catálogo en VES y
re-sincronizar precios a diario por la tasa. Lo segundo es justo el caso en el que la opción C
brilla y la B se vuelve un trabajo manual diario. Si Meta no acepta VES, la pregunta desaparece:
USD y punto.

### 2.5 Multi-negocio (más adelante)

| Afirmación | Nivel | Fuente |
|---|---|---|
| Un socio (Solution Partner) puede gestionar el catálogo de un cliente si el cliente le da acceso, o crearlo bajo su propio business ID | `[V]` | [M-2] |
| `catalog_management` sobre catálogos **de otro negocio** pasa por App Review (screencast creando, editando y borrando un catálogo) | `[V]` (requisitos de revisión) | [M-4] |
| Si ese caso exige acceso avanzado (QUA-203, camino de Tech Provider) | `[NO VERIFICADO]`; por ADR 29, lo probable es que sí para activos que el fundador no administra | — |

Consecuencia: `catalog_management` se suma a la lista de permisos de App Review (como
`ads_management` en ADR 38). Por ADR 29(3) la revisión es **por permiso**: se puede pedir sin
arrastrar los demás.

### Fuentes de Meta (acceso 2026-11-03)

- [M-0] https://developers.facebook.com/documentation/business-messaging/whatsapp/llms.txt (índice: plantillas de catálogo; pagos solo India, Brasil, México)
- [M-1] https://developers.facebook.com/docs/whatsapp/cloud-api/guides/sell-products-and-services/
- [M-2] https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/upload-inventory.md
- [M-3] https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account/product_catalogs/
- [M-4] https://developers.facebook.com/docs/permissions/reference/catalog_management
- [M-5] https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/set-commerce-settings.md
- [M-6] https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/single-product-messages.md
- [M-7] https://developers.facebook.com/docs/marketing-api/reference/product-catalog/items_batch/
- [M-8] https://developers.facebook.com/docs/marketing-api/reference/product-catalog/product_feeds/
- [M-9] https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/multi-product-messages.md
- [M-10] https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/order.md
- [M-11] https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages.md
- [M-12] https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing.md
- `[S]` https://support.kommo.com/docs/whatsapp-catalogs · https://docs.360dialog.com/docs/messaging/catalogs · https://help.wanotifier.com/en/article/how-to-setup-product-catalog-8ktm07/

## 3. Las opciones

| Opción | Qué es | Para el dueño | Costo / esfuerzo | ¿Se puede deshacer? | Riesgo principal | Evidencia |
|---|---|---|---|---|---|---|
| **A. Dejar como está** | El menú de listas de WA-15 (10 filas + «Ver más») y el pedido de `orders.py` | Ya funciona; para 20 productos alcanza, para 400 no | 0 | — | Perder al negocio de muchas referencias | `[V]` código |
| **B. Catálogo a mano en Commerce Manager** | El dueño (o nosotros) arma el catálogo en Meta y lo conecta a la WABA; Qualify solo **envía** mensajes de producto y **lee** el pedido | Fotos, precio y carrito en WhatsApp; pero carga los productos **dos veces** (Qualify y Meta) y cambia precios en Meta | S: 3–6 días-persona `[H]` | Sí: desconectar el catálogo; el código queda | Los dos catálogos se desfasan (precio en Meta ≠ precio en Qualify) | §2.1, §2.3 |
| **C. Sincronización desde Qualify** | Qualify crea el catálogo, sube productos y precios por lotes y re-sincroniza al cambiar; mensajes y pedido como en B | Carga una vez, en español, en Qualify; el precio nuevo aparece solo | L: 15–25 días-persona `[H]` (incluye CSV + código + URL estables) | Sí técnicamente; **App Review de `catalog_management`** es una vía de un solo sentido ante Meta | Rechazo de artículos o del permiso; imágenes caídas; un error de lote que deja precios viejos | §2.2, §2.5 |
| **D. Ambos (B primero, C encima)** | B ahora con el negocio piloto; C solo si el piloto prueba uso y alguien mantiene ≥100 productos | Lo de B ya; lo de C cuando haga falta | S ahora + L después `[H]` | Sí | Que B «funcione suficiente» y C nunca llegue, o que el piloto engañe (Bianki es del fundador) | §2 |

### A. Dejar como está
- **Cliente final:** listas de 10 filas por mensaje, por categoría; pide escribiendo cantidades en
  el flujo del menú.
- **Límite real:** con 400 referencias son unos 45 mensajes (9 productos por página más la fila «Ver más»). No hay búsqueda.
- **Mejora barata dentro de A:** un nodo de búsqueda por texto («escribe lo que buscas») sobre
  `brand_products` — útil para una ferretería tenga o no catálogo nativo (§5).

### B. Catálogo a mano en Commerce Manager
- **Cliente final:** abre la tiendita, mira fotos, arma el carrito y lo envía; el negocio recibe un
  pedido estructurado.
- **Prerrequisitos en Meta:** catálogo en el mismo portafolio que la WABA (Qualify.co para Bianki)
  `[S]`; conectarlo en WhatsApp Manager; `is_catalog_visible=true` en el número [M-5]. El
  `retailer_id` («Id. de contenido») de cada artículo lo pone quien lo carga.
- **En Qualify:** constructores `product` / `product_list` en `whatsapp/client.py`; un selector de
  productos en la conversación para que **el humano elija y envíe** (asistido, nunca automático);
  intake del webhook `order` → `orders.py`, idempotente por `wamid`, con provenance
  (`catalog_id`, `wamid`). Una sola tabla nueva, `whatsapp_catalogs` (§4, con su migración), con el
  `catalog_id` registrado a mano (`source = manual`): B no necesita `catalog_management`.
- **Precio que ve el dueño en Qualify:** el del pedido (`item_price`), no el de `brand_products`.
  Si difieren, se muestra el del pedido y un aviso.
- **Esfuerzo:** S, 3–6 días-persona `[H]`.
- **Riesgos:** doble carga; el pedido trae un `retailer_id` que Qualify no conoce (se muestra con
  el nombre que trae y sin vínculo); en Venezuela con VES, cambiar precios a mano a diario.

### C. Sincronización desde Qualify
- **Cliente final:** igual que B.
- **Prerrequisitos en Meta:** `catalog_management` (+ `business_management`) en el token del
  usuario del sistema, verificado en vivo; el usuario del sistema con el catálogo asignado
  `[NO VERIFICADO]`; para negocios ajenos, App Review de `catalog_management` [M-4].
- **En Qualify:** todo lo de B + código de producto, importación CSV, URL públicas estables,
  tablas de §4, un worker de sincronización y la pantalla de estado («3 productos rechazados por
  Meta»).
- **Esfuerzo:** L, 15–25 días-persona `[H]`: CSV + `sku` 4–6, URL estables 2–3, tablas + worker +
  reintentos 5–8, estado de revisión en UI 2–4, lo de B 3–6.
- **Riesgos:** ver §6.

### D. Ambos
B se construye de modo que C sea un añadido: el `retailer_id` que se pide en Commerce Manager es
el mismo código (`sku`) que luego tendrá `brand_products`, así un catálogo hecho a mano puede
pasar a sincronizado sin volver a crear artículos (con `allow_upsert`, el lote actualiza lo que ya
existe) [M-7].

## 4. Modelo de datos y sincronización propuestos (opción C/D)

Todo en el Postgres de siempre (ADR 31), sin almacén, cola ni proceso nuevo: un worker de bucle
como los demás. Cada tabla con `tenant_id` + RLS `NULLIF(current_setting('app.tenant_id', true),
'')::uuid` en la misma revisión (`qualify-migration`).

**`brand_products.sku text NULL`** + `UNIQUE (brand_id, sku)` donde no sea nulo. Es el
`retailer_id` de Meta. Si el dueño no pone código, se genera uno estable una sola vez (p. ej. el
`id` corto) y **nunca** se deriva del nombre.

**`whatsapp_catalogs`** — uno por (marca, WABA): `tenant_id`, `brand_id`, `waba_id`,
`catalog_id`, `source` (`manual` | `qualify`), `currency`, `connected_at`, `connected_by`,
`UNIQUE (waba_id)` (Meta: un catálogo por WABA [M-2]). Con `source = manual` Qualify nunca escribe
en el catálogo: solo envía y lee.

**`whatsapp_catalog_items`** — uno por producto sincronizado: `tenant_id`, `catalog_row_id`,
`product_id`, `retailer_id`, `last_pushed_hash` (hash del contenido enviado: título, descripción,
precio, moneda, disponibilidad, URL de imagen), `last_pushed_at`, `meta_review_status`
(`pending` | `approved` | `rejected`), `meta_error` (código y enumeración, nunca texto de usuario
en logs), `pipeline_version`. `UNIQUE (catalog_row_id, retailer_id)`.

**`whatsapp_catalog_sync_runs`** — una por llamada a `items_batch`: `tenant_id`,
`catalog_row_id`, `request_key` (hash del lote; `UNIQUE` → el mismo lote no se manda dos veces),
`handle` de Meta, `status`, `items_total`, `items_failed`, `started_at`, `finished_at`. Es la
procedencia de cada fila de `whatsapp_catalog_items`.

**Worker `whatsapp-catalog-sync-tick --tenant <uuid>`** (en local, siempre con `--tenant`):
1. Elige productos con `updated_at > last_pushed_at` **y** hash distinto, con un retardo de
   ~5 min desde el último cambio (para no mandar diez lotes si el dueño corrige diez precios).
2. Arma un lote (`UPDATE` con `allow_upsert`; `DELETE` para productos borrados o inactivos, o
   `availability = out of stock` si se prefiere conservarlos), ≤ 3.000 por llamada [M-7].
3. Guarda la `sync_run` **antes** de llamar (outbox), llama, guarda el `handle`.
4. En la siguiente vuelta consulta `check_batch_request_status` con el `handle` y vuelca errores
   por artículo.
5. Sin precio de por medio: estas llamadas no cuestan dinero en Meta; el guardián de precio no
   aplica, pero sí un tope de lotes por hora por catálogo para no chocar con el error 80014.

**URL públicas estables para imágenes.** Hoy solo hay tokens que caducan. Propuesta: una ruta
`GET /public/catalog-media/{media_id}.{ext}?s=<firma>` con firma HMAC **sin caducidad** sobre
`(tenant_id, media_id, object_key)`, servida desde R2 como `public_media_routes.py`. Se revoca
borrando el `product_media` (404). No requiere servicio nuevo. Alternativa descartada: hacer
público un prefijo de R2 — expone el árbol de claves del tenant (ADR 22) y no se revoca por
artículo.

**Lo que sigue siendo asistido.** La sincronización mueve datos del propio negocio a su propio
catálogo; no habla con nadie. Ningún mensaje de producto sale sin que un humano lo elija y lo
envíe desde la conversación; el pedido entrante nunca dispara una respuesta automática.

**Reversibilidad.** Las tres tablas y la columna son una migración reversible; apagar la
sincronización es parar el worker; el catálogo en Meta queda y el dueño puede seguir a mano
(pasa a `source = manual`).

## 5. Encaje para una ferretería con cientos de referencias

- **Prerrequisito, sea cual sea la opción:** importar productos por CSV en «Tus productos» (nombre,
  código, precio, moneda, categoría, foto opcional por URL o después) y la columna `sku`. Nadie
  carga 400 tornillos uno por uno. Esto vale también para A.
- **Fotos:** una ferretería rara vez tiene foto de cada referencia. Meta exige `image` por
  artículo [M-7]; artículos sin foto no entran al catálogo (o entran con una imagen genérica de
  categoría, a validar con la revisión de Meta `[NO VERIFICADO]`).
- **Buscar:** el catálogo nativo deja al cliente final desplazarse por la tiendita; el negocio solo
  puede mandar 30 productos por mensaje [M-9]. Para «¿tienen tornillo drywall 6 × 1?» lo útil es
  que el humano busque en Qualify y envíe un multiproducto con las 5 coincidencias — búsqueda en el
  selector, no en Meta.
- **Comparado con hoy:** de unos 45 mensajes de listas a una tiendita con fotos y carrito; el pedido
  llega con cantidades y precios.
- **Existencias:** solo «hay / no hay» [M-7]. Si el dueño no actualiza, el cliente pide algo
  agotado; el pedido sigue siendo informativo y lo confirma un humano.
- **Venezuela:** un precio por moneda (§2.4). En USD el catálogo es estable; en VES exige
  re-sincronización diaria, que solo la opción C hace sin trabajo manual.

## 6. Recomendación

**D, empezando por B sin construir aún la sincronización** — porque lo que buscamos es aprender
(§0) y B responde las tres preguntas (token, uso real del carrito, pedido) con la quinta parte del
esfuerzo; la importación por CSV con `sku` se hace ya porque sirve en cualquier camino.

**Costo de equivocarse:** 3–6 días-persona `[H]` si nadie usa el carrito; si el piloto funciona y
tardamos en C, el dueño mantiene dos catálogos unas semanas.

**La reabrimos (pasamos a C) si,** al **2026-12-15**, un negocio piloto con **≥100 productos**
recibe **≥10 pedidos de carrito** en un mes, o si un negocio venezolano necesita precios en VES
que cambian a diario. Si al 2026-12-15 hay < 3 pedidos de carrito en total, volvemos a A + CSV +
búsqueda.

**Validación más barata (antes de escribir código):** en la WABA de Bianki, crear a mano en
Commerce Manager un catálogo de 10 productos con `retailer_id` = código propuesto, conectarlo,
activar `is_catalog_visible`, y desde el Explorador de la Graph API mandar un multiproducto a un
número de prueba dentro de la ventana; hacer un pedido y mirar el webhook `order` en
`webhook_inbox`. En paralelo, regenerar el token del usuario del sistema con `catalog_management`
y probar `GET /{waba_id}/product_catalogs`. Medio día, sin código.

**Top 3 riesgos:**
1. **Permiso y token:** `catalog_management` no está en el token actual; en negocios ajenos exige
   App Review propio. Señal temprana: el `GET` de la validación falla con error 200.
2. **Imágenes y revisión de Meta:** sin URL estables o con artículos rechazados (ferretería sin
   fotos, productos restringidos), el catálogo queda a medias. Señal: > 10 % rechazados en el piloto.
3. **Moneda en Venezuela y cobro de mensajes:** un solo precio por moneda; y desde el 2026-10-01 los
   mensajes de servicio se cobran pasados 1.000 al mes por número [M-12] — el multiproducto deja de
   ser «gratis» para un negocio con mucho tráfico.

## 7. Épica propuesta y historias

> **Borrador `[PROPUESTO]` — 2026-11-03.** Nada de esto está creado en Meegle ni decidido: espera el sí del fundador sobre la opción (§6). Los datos de Meta ya están cotejados con §2 (referencias [M-n]); lo que sigue sin verificar está en §8 y no debe pasar a un ticket sin confirmarse.

### 7.1 Feature (épica) — «Épica — Catálogo de WhatsApp»

| Campo | Valor propuesto |
|---|---|
| Título | `Épica — Catálogo de WhatsApp` |
| Tipo / plantilla | Feature (`story`) · Product Feature Request (`617476`) |
| Prioridad | **P2** — regla de `docs/formato-tickets-meegle.md` §3: no hay producción rota ni un cliente bloqueado (el menú de WA-15 ya toma pedidos en Bianki), ni bloquea otro trabajo de esta semana → «lo normal». |
| Etiquetas | La épica no lleva etiqueta principal (§1); las historias llevan `Feature` (+ `UI` donde aplica). |
| Relación | Hija temática de m-24789424 «Épica — WhatsApp (Cloud API), Bianki primero»; continúa WA-23 de `docs/backlog-modulo-whatsapp.md` §6. |
| Reporter / Assignee | Herwin / por asignar al crear las historias (sin Assignee el equipo no puede moverlas). |

**Objetivo (como lo diría el dueño; redacción nuestra, hipótesis `[H]`, no una cita de cliente).** «Tengo cientos de productos y no quiero escribirlos uno por uno en el chat. Quiero que mi cliente vea mis productos con foto y precio dentro de WhatsApp, arme su carrito y me llegue el pedido completo; y si cambio un precio en Qualify, que cambie también en WhatsApp sin hacerlo dos veces.»

**Evidencia.**
- Decisión/pedido del fundador (2026-11-03): evaluar el catálogo nativo de WhatsApp por las dos vías (a mano en Commerce Manager y carga en lote desde Qualify con re-sincronización de precios), pensando en negocios con muchas referencias — **ferreterías** —, no solo comida. `[F]`
- `docs/backlog-modulo-whatsapp.md` §6, WA-23 «Catálogo nativo» (planificado «después»). `[V]`
- Lo construido: WA-15 (m-24789631, Done) — menú desde `brand_products` en listas de 10 filas con «Ver más» y tarjeta de pedido arriba del chat (`whatsapp/catalog.py`, `whatsapp/orders.py`). Número real de Bianki en producción desde 2026-11-03. `[V]`
- **Hipótesis `[H]`:** que una ferretería quiera y use el catálogo nativo. Hoy no hay ninguna ferretería entre los clientes; Bianki y Polette son negocios del fundador (banco de prueba, no mercado). La Fase 1 está pensada para validarlo barato antes de construir la sincronización.

**Alcance.**
- Dentro: conectar un catálogo de Commerce Manager a la cuenta de WhatsApp Business del negocio y ver su estado en `/whatsapp`; enviar uno o varios productos desde el chat (asistido: la persona elige, Qualify envía); recibir el carrito del cliente como pedido en el hilo; importar productos y precios en lote a «Tus productos» con código de producto; sincronizar «Tus productos» con el catálogo y re-sincronizar al cambiar un precio; buscar por nombre o código en el menú.
- Fuera: pagos dentro de WhatsApp (Meta solo documenta pagos en India, Brasil y México [M-0]; §2.4); inventario en vivo (solo «hay / no hay» [M-7]); variantes (talla/color) más allá de una fila por referencia; catálogo en Instagram/Facebook Shops; respuestas o envíos autónomos (regla firmada: asistido, nunca autónomo); facturación o pasarela.

**Tickets relacionados encontrados en Meegle (consulta MQL 2026-11-03, solo lectura).**

| Ticket | Título | Estado | Relación |
|---|---|---|---|
| m-24789424 | Épica — WhatsApp (Cloud API), Bianki primero | — | épica madre del módulo |
| m-24789631 | WA-15 · Pedido asistido desde el catálogo | Done | se reutiliza su tarjeta de pedido (CAT-02) y su nodo de productos (CAT-05) |
| m-24842974 | [PRODUCTOS] Tus productos: agregar un producto en tres pasos desde el celular, la foto primero | Done | CAT-03 es la vía en lote; no la reemplaza |
| m-24842976 | [PRODUCTOS] Tus productos: editar sin perder cambios… | Done | CAT-03 añade el campo código al mismo formulario |
| m-24842971 | [PRODUCTOS] Tus productos: textos y errores en palabras del dueño | RESOLVED | mismo tono para los errores por fila de CAT-03 |
| m-24872310 | QA UX: Tus productos y regreso a Crear con el producto elegido | RESOLVED | — |

No encontré tickets de «importar», «catálogo nativo», «Commerce Manager» ni «SKU/código»: no hay duplicados.

### 7.2 Historias

Reglas comunes (de `docs/backlog-modulo-whatsapp.md` §1, aplican a todas): tenant por `phone_number_id`, nunca por el contenido del mensaje; idempotencia por `wamid`; la ventana de 24 h la decide solo `whatsapp/window.py`; nada de texto del cliente en logs; RLS con la política `NULLIF` en toda tabla nueva; tests offline y, si toca esquema, `db` (`just test-db`) y `just migrate-down` limpio; tokens solo por el `CredentialResolver`. Todo texto que lee el dueño, en español según `qualify-copy-es` («Tus productos», «publicación», «identidad de marca»; nunca «post», «Brand Kit», «SKU» a solas en pantalla — se dice «código del producto»).

---

#### CAT-00 · WhatsApp: conectar mi catálogo de Meta y ver en Qualify que quedó listo

- **Prioridad** P2 · **Tamaño** M · **Área** backend-engineer (+ reflex-ui-engineer para la tarjeta en `/whatsapp`) · **Etiquetas** `Feature`, `UI`
- **Dependencias:** WA-13 (número real conectado, hecho). **No exige `catalog_management`:** el identificador del catálogo se registra a mano (`source = manual`, §4), como en la opción B. Si el token lo trae (§8.1; se prueba en la validación del §6), Qualify además lo verifica con `GET /{waba_id}/product_catalogs` y cuenta los productos [M-3]. Bloquea CAT-01, CAT-02 y CAT-04.

**Historia.** Como dueña de un negocio que vende por WhatsApp, quiero conectar a mi número el catálogo que tengo (o que creo) en Meta y ver en Qualify si quedó listo, para que mis clientes puedan ver mis productos dentro del chat sin que yo tenga que escribir precios a mano.

**Criterios de aceptación.**
1. [ ] Con un catálogo de Commerce Manager ya conectado a la cuenta de WhatsApp Business del negocio, el operador registra su identificador en Qualify (recipe `just whatsapp-catalog-connect --tenant <uuid> --brand <uuid> --catalog-id <id>`, o un campo en la pestaña Conexión) y queda guardado asociado a la conexión de WhatsApp del tenant (`whatsapp_catalogs` con `tenant_id` y RLS, `source = manual`; `db` verde; `just migrate-down` limpio). Si el token trae `catalog_management`, Qualify lo contrasta con `GET /{waba_id}/product_catalogs` [M-3] (un solo catálogo por WABA [M-2]) y rechaza un identificador que no coincida; si no lo trae, lo guarda como «sin verificar» y el primer mensaje de producto enviado (CAT-01) lo confirma.
2. [ ] En `/whatsapp`, pestaña Conexión, una tarjeta «Catálogo» muestra uno de estos estados, con el texto exacto:
   - listo: «Tu catálogo está conectado y tus clientes ya lo ven en WhatsApp.»; con `catalog_management` en el token, en su lugar: «Tus clientes ya ven {n} productos con foto y precio en WhatsApp.»
   - sin catálogo: «Todavía no hay un catálogo conectado a este número. Créalo en el Administrador de ventas de Meta y vuelve aquí.» con el botón «Ver cómo hacerlo».
   - sin permiso (Meta rechaza el token al enviar un producto o al escribir `whatsapp_commerce_settings`): «Necesitamos que vuelvas a conectar WhatsApp para seguir usando tu catálogo.» con el botón «Conectar de nuevo».
   - el carrito o el catálogo están ocultos para los clientes: «Tu catálogo está conectado, pero tus clientes todavía no lo ven.» con el botón «Mostrar mi catálogo a mis clientes», que escribe `is_catalog_visible = true` (y `is_cart_enabled`) en `whatsapp_commerce_settings` [M-5] solo cuando el dueño lo pulsa; `is_catalog_visible` nace en `false`. El permiso que exige ese `POST` se confirma en la validación del §6 (`[NO VERIFICADO]`).
3. [ ] El conteo `{n}` (solo con `catalog_management`) sale de una lectura a Meta que se guarda con su fecha; la tarjeta dice «Actualizado {fecha}» en la zona horaria del negocio y un botón «Actualizar» vuelve a leer; sin el permiso dice «Conectado el {fecha}». Sin texto de cliente en logs.
4. [ ] Un tenant no ve ni puede leer el catálogo de otro (test de RLS y test de API con dos tenants).
5. [ ] Guía «Ver cómo hacerlo» en español, en `docs/` y enlazada desde la tarjeta: crear catálogo, cargar 10 productos a mano, conectarlo al número (pasos de la interfaz `[S]`, §2.1; el `retailer_id` de cada artículo es el código del producto que luego tendrá `brand_products.sku`, §3-D).
6. [ ] `just ci-test` verde; tests offline con un cliente Graph falso para los cuatro estados y el botón «Mostrar mi catálogo a mis clientes».

**Fuera de alcance.** Crear el catálogo desde Qualify (es CAT-04); editar productos en Meta desde Qualify; tiendas de Instagram o Facebook.

---

#### CAT-01 · WhatsApp: mandarle a mi cliente uno o varios productos desde el chat

- **Prioridad** P2 · **Tamaño** M · **Área** backend-engineer (+ reflex-ui-engineer para el selector) · **Etiquetas** `Feature`, `UI`
- **Dependencias:** CAT-00. Verificado: el multiproducto lleva hasta 30 productos en secciones y encabezado de texto obligatorio [M-9]; producto único y multiproducto solo van dentro de una conversación existente [M-6], [M-9]; fuera de la ventana solo plantillas de catálogo o producto [M-0] (fuera de alcance aquí).

**Historia.** Como dueño de una ferretería que atiende por WhatsApp, quiero elegir en el chat uno o varios productos de mi catálogo y mandárselos al cliente con foto y precio, para que vea exactamente lo que le ofrezco y pueda agregarlo a su carrito sin que yo copie fotos y precios.

**Criterios de aceptación.**
1. [ ] En el hilo de `/whatsapp`, un botón «Enviar productos» abre un selector con buscador por nombre o código; se pueden marcar uno o varios productos (hasta 30 por mensaje [M-9]), agrupados por categoría.
2. [ ] **Asistido:** nada sale sin que la persona pulse «Enviar». Un producto → mensaje de un producto; varios → mensaje de varios productos con título y secciones por categoría; ambos pasan por el outbox existente (idempotente: un reintento no duplica el envío; la clave de idempotencia y el `wamid` de vuelta quedan guardados).
3. [ ] Fuera de la ventana de 24 h el botón queda deshabilitado con el texto «Han pasado más de 24 horas desde el último mensaje del cliente. Para escribirle, usa un mensaje aprobado.» (la decisión la toma `whatsapp/window.py`).
4. [ ] Si Meta rechaza el envío (producto que ya no existe o no aprobado), el hilo muestra «No pudimos enviar {nombre}: ya no está en tu catálogo de WhatsApp. Revísalo en Tus productos.» y el código de error queda solo en el log como enumeración.
5. [ ] El mensaje enviado aparece en el hilo como tarjeta con las fotos y los nombres (lectura desde el catálogo guardado, sin texto del cliente en logs).
6. [ ] Tests offline del armado del mensaje (uno y varios, límite, secciones) contra fixtures del contrato de Meta; `just ci-test` verde.

**Fuera de alcance.** Envío automático por regla o por el menú sin una persona (contradice «asistido, nunca autónomo»); campañas con productos (WA-20 ya cubre plantillas); recomendaciones por IA de qué producto enviar.

---

#### CAT-02 · WhatsApp: recibir el carrito de mi cliente como pedido en el chat

- **Prioridad** P2 · **Tamaño** S · **Área** backend-engineer · **Etiquetas** `Feature`
- **Dependencias:** CAT-00. Mensaje entrante `type = "order"` verificado [M-10]: `order.catalog_id`, `order.text` y `product_items[]` con `product_retailer_id`, `quantity`, `item_price` y `currency` (la moneda del catálogo). Reutiliza `whatsapp/orders.py` (WA-15, m-24789631).

**Historia.** Como dueña de un negocio, quiero que cuando mi cliente me envíe su carrito desde WhatsApp me llegue como un pedido ordenado arriba del chat, igual que los pedidos del menú, para no tener que leer y sumar a mano lo que pidió.

**Criterios de aceptación.**
1. [ ] El intake de webhooks reconoce el mensaje de carrito y lo convierte en el mismo registro de pedido que ya usa WA-15 (`items` con producto, cantidad, precio unitario y moneda; `total`; `confirmed_at`), con `source_message_id` = `wamid` y una versión de origen propia (p. ej. `wa-native-cart-0.1.0`) como procedencia.
2. [ ] **Idempotente por `wamid`:** el mismo carrito entregado dos veces deja un solo pedido y conserva su primera fecha (test offline).
3. [ ] Cada línea del carrito se intenta enlazar con el producto de «Tus productos» por su código (`product_retailer_id` = `brand_products.sku`); si no hay enlace, la línea se muestra igual con el nombre que manda Meta y la marca «No está en Tus productos». El total se calcula con los precios que trae el carrito, no con los de Qualify; si difieren, la tarjeta lo dice: «Algunos precios del carrito no coinciden con los de Tus productos. Revisa antes de confirmar.»
4. [ ] La tarjeta de pedido existente aparece arriba del hilo con el título «Pedido desde tu catálogo de WhatsApp» y la respuesta rápida «Pedido listo» (texto libre, solo dentro de la ventana).
5. [ ] El tenant sale del `phone_number_id`, nunca del contenido; un carrito para un número sin conexión queda `orphan` (test).
6. [ ] **Convivencia con el pedido del menú:** hoy `orders.py` guarda un solo pedido vigente por hilo y una confirmación distinta lo reemplaza. Un carrito que llega mientras hay un pedido del menú sin atender **no lo pisa**: el registro pasa a admitir más de un pedido abierto por hilo (cada uno con `source` = `menu` | `cart`) o el anterior se archiva como mensaje interno del hilo antes de reemplazarlo; la tarjeta muestra los dos y ningún pedido sin atender se pierde (test offline: pedido del menú abierto + carrito → ambos visibles).
7. [ ] `just ci-test` verde; si se toca esquema, `db` verde y `just migrate-down` limpio.

**Fuera de alcance.** Cobro dentro de WhatsApp (Meta solo documenta pagos en India, Brasil y México [M-0]); descontar inventario; confirmar el pedido al cliente de forma automática.

---

#### CAT-03 · Tus productos: subir cientos de productos con su precio desde una hoja de cálculo

- **Prioridad** P2 · **Tamaño** L · **Área** creative-engineer (dueño de `qualify_api.catalog`; migración y servicio) + reflex-ui-engineer (pantalla) · **Etiquetas** `Feature`, `UI`
- **Dependencias:** ninguna de Meta — se puede construir en paralelo a la Fase 1 y sirve aunque no haya catálogo de WhatsApp. Relacionada con PRODUCTOS-3 (m-24842974) y PRODUCTOS-4 (m-24842976): no los reemplaza.

**Historia.** Como dueño de una ferretería con cientos de referencias, quiero subir todos mis productos con su código y precio desde una hoja de cálculo, y volver a subirla cuando cambien los precios, para no cargarlos uno por uno desde el celular.

**Criterios de aceptación.**
1. [ ] Migración: `brand_products` gana `sku` (texto, opcional) con unicidad por marca cuando no está vacío (`UNIQUE (brand_id, sku)` parcial; es el `retailer_id` de Meta, §4); RLS intacta; `db` verde; `just migrate-down` limpio. El formulario de PRODUCTOS-4 muestra el campo como «Código del producto (opcional)».
2. [ ] En «Tus productos», el botón «Subir desde una hoja de cálculo» abre un flujo de tres pasos con «Paso N de 3» arriba: ① «Descarga la plantilla» ② «Sube tu hoja» (CSV o XLSX) ③ «Revisa y guarda». La plantilla trae las columnas con nombres de persona, no de base de datos — «Código», «Nombre», «Precio», «Moneda», «Categoría», «Descripción», «Enlace de la foto», «¿Lo vendes? (sí/no)» — y una fila de ejemplo ya llena. En el celular, el paso ① avisa «Más fácil desde un computador» (hipótesis `[H]`: una hoja de cientos de filas se prepara en un computador).
3. [ ] Antes de guardar, el paso ③ dice: «Vamos a agregar {a} productos nuevos y actualizar {b}. {c} filas tienen errores.» con los botones «Guardar {a+b} productos», «Ver las {c} filas con errores» y «Cancelar». Nada se escribe sin «Guardar».
4. [ ] **Re-subida:** una fila cuyo «Código» ya existe en la marca actualiza ese producto (precio, nombre, categoría…), no lo duplica; una fila sin código crea un producto nuevo y Qualify le genera un `sku` estable una sola vez (§4). Subir dos veces el mismo archivo no cambia nada la segunda vez (idempotente, test offline).
5. [ ] Errores por fila, en palabras del dueño, cada uno con qué hacer, y descargables como hoja: «Fila {n}: falta el nombre. Escríbelo en tu hoja y vuelve a subirla.», «Fila {n}: el precio no es un número. Escribe solo cifras, por ejemplo 12500.», «Fila {n}: el código {codigo} aparece dos veces en el archivo. Deja una sola fila con ese código.», «Fila {n}: no pudimos abrir el enlace de la foto. Revisa que abra en tu celular.». Las filas buenas se guardan aunque otras fallen.
6. [ ] La moneda vacía toma la del negocio; los precios se guardan como `Numeric(12,2)`; las fotos por URL pasan por la misma normalización a R2 que la subida manual.
7. [ ] Un archivo de 1.000 filas se procesa sin bloquear la pantalla (en segundo plano con progreso «Procesando {x} de {y}…»); límite de filas y tamaño definidos y mostrados.
8. [ ] Cada producto creado o actualizado guarda su procedencia (importación, fecha, nombre del archivo); tests offline de parseo (CSV con `;` y `,`, decimales con coma, tildes) y test de RLS con dos tenants; `just ci-test` verde.

**Fuera de alcance.** Sincronizar con WhatsApp (CAT-04); integración directa con un sistema de inventario o facturación; variantes por talla o color; borrar en lote los productos que no vienen en el archivo (se desactivan a mano o en una historia posterior).

---

#### CAT-04 · WhatsApp: que mis productos y precios de Qualify se copien solos a mi catálogo de WhatsApp

- **Prioridad** P2 · **Tamaño** L · **Área** backend-engineer · **Etiquetas** `Feature`
- **Dependencias:** CAT-00 y CAT-03 (el `sku` es el `retailer_id` que Meta usa para cada artículo). Verificado: carga por lotes con `items_batch`, hasta 5.000 solicitudes por llamada (Meta recomienda < 3.000), `allow_upsert` por defecto [M-7]; campos obligatorios `availability`, `brand`, `condition`, `description`, `id`, `image`, `link`, `price` («9.99 USD») y `title` [M-7]; el archivo programado queda solo como respaldo (§2.2). Sin verificar: tiempo de revisión de los artículos, si `link` es opcional y el límite de artículos por catálogo (§8). URL pública y estable de la foto principal: la ruta firmada sin caducidad propuesta en §4.

**Historia.** Como dueña de un negocio, quiero que cuando agrego un producto o cambio un precio en «Tus productos» se actualice también mi catálogo de WhatsApp, para no hacer el mismo trabajo dos veces ni mostrarle a un cliente un precio viejo.

**Criterios de aceptación.**
1. [ ] El dueño activa la sincronización desde la tarjeta «Catálogo» con el interruptor «Mantener mis precios al día en WhatsApp», la explicación «Si cambias un precio aquí, también cambia en WhatsApp.» y la advertencia «Los productos que creaste a mano en Meta y no estén en Tus productos no se tocan.»; se puede apagar.
2. [ ] Un worker de bucle (`whatsapp-catalog-sync-tick`, §4, mismo patrón que los demás workers; localmente siempre con `--tenant <uuid>`) envía altas, cambios y bajas por lotes de hasta 3.000 [M-7]; cada producto se identifica en Meta por su `sku`.
3. [ ] **Re-sincronización al cambiar un precio:** editar el precio en «Tus productos» (a mano o por CAT-03) encola el cambio; el tiempo máximo hasta que se envía queda definido y probado.
4. [ ] **Idempotencia y procedencia:** cada envío tiene una clave por (producto, versión del contenido); reenviar el mismo lote no duplica artículos; cada producto guarda la última versión sincronizada, la fecha, el identificador del lote de Meta y la versión del sincronizador.
5. [ ] El estado por producto se ve en «Tus productos»: «En WhatsApp», «Esperando aprobación de WhatsApp», «WhatsApp no lo aceptó: {motivo en palabras del dueño}. Corrígelo aquí y lo enviamos de nuevo.». La tarjeta resume: «{n} productos en WhatsApp · {m} con problemas», y «{m} con problemas» se puede tocar para ver solo esos productos.
6. [ ] Un producto sin precio o sin foto no se envía y se marca «Falta precio o foto para mostrarlo en WhatsApp.».
7. [ ] Tests offline con un cliente Graph falso (lote, error parcial, reintento, baja); test de RLS; `db` verde y `just migrate-down` limpio si hay tablas nuevas; `just ci-test` verde.

**Fuera de alcance.** Traer a Qualify los productos creados a mano en Meta (sincronización de vuelta); inventario en vivo; más de un precio o moneda por producto (Meta admite un `price` con una sola moneda por artículo [M-7]); feed público para otros canales.

---

#### CAT-05 · WhatsApp: que mi cliente encuentre un producto por nombre o código en el menú (opcional)

- **Prioridad** P3 · **Tamaño** M · **Área** backend-engineer · **Etiquetas** `Improvement`
- **Dependencias:** CAT-03 (código). Independiente de Meta: mejora el menú de WA-15 (m-24789631), útil aunque no se adopte el catálogo nativo.

**Historia.** Como dueño de una ferretería con cientos de productos, quiero que mi cliente escriba el nombre o el código de lo que busca y el menú le muestre solo esos productos, para que no tenga que pasar decenas de páginas de «Ver más».

**Criterios de aceptación.**
1. [ ] En el nodo de productos del menú, una opción «Buscar un producto» pide: «Escribe el nombre o el código de lo que buscas.»; la respuesta del cliente filtra los productos activos por nombre (sin tildes ni mayúsculas) o por código exacto.
2. [ ] Con resultados, la lista muestra hasta 10 y «Ver más»; sin resultados: «No encontramos “{texto}”. Prueba con otra palabra o escribe “menú” para volver.»
3. [ ] La búsqueda corre como `qualify_webhook_worker` con el filtro explícito por `tenant_id` del número (defensa en profundidad, como `load_catalog_for_phone`) y solo sobre columnas con permiso (ampliar el grant de 0059 si hace falta, en una migración reversible).
4. [ ] El texto del cliente no se escribe en logs; tests offline del filtro y del menú; `just ci-test` verde.

**Fuera de alcance.** Búsqueda por IA o por sinónimos; búsqueda dentro del catálogo nativo de Meta.

---

### 7.3 Orden de entrega y qué valida cada fase

| Paso | Qué | Qué valida | Costo |
|---|---|---|---|
| **0 · Validación sin código** (antes de cualquier historia) | El fundador crea a mano en Commerce Manager un catálogo de ~10 productos de Bianki, lo conecta a la cuenta de WhatsApp Business y, con la herramienta de Meta o una llamada de prueba del arquitecto, envía **un** mensaje de varios productos a un número propio y devuelve un carrito. | Que el catálogo se conecta a la WABA en nuestro país y con nuestro nivel de acceso, que el cliente ve fotos y precios, que el carrito llega por webhook y con qué forma. Si falla aquí, no se construye nada de la épica (salvo CAT-03/CAT-05, que no dependen de Meta). | Horas del fundador + arquitecto; sin desarrollo. |
| **Fase 1** — CAT-00 → CAT-02 → CAT-01 | Conectar y ver el estado; recibir el carrito como pedido (lo más barato y lo que más valor da); enviar productos desde el chat. | Si los clientes de Bianki usan el carrito más que el menú de listas: % de pedidos por carrito vs. por menú en 4 semanas. | M + S + M (≈ 6–10 días-persona `[H]`; más que los 3–6 de §3-B porque las historias incluyen la tarjeta de estados, el selector con buscador y la convivencia de pedidos) |
| **En paralelo** — CAT-03 | Importación en lote + código del producto. | Si un negocio con muchas referencias (una ferretería real, cuando la haya) carga su lista sin ayuda. Sirve también al menú y a la creación de publicaciones. | L |
| **Fase 2** — CAT-04 | Sincronizar «Tus productos» → catálogo, con re-sincronización de precios. | Solo si la Fase 1 mostró uso y hay un negocio con más productos de los que conviene mantener a mano en Meta. | L |
| **Cuando haga falta** — CAT-05 | Buscar por nombre o código en el menú. | Si un catálogo grande hace que el menú de listas se abandone en «Ver más». | M |

**Lo que todavía no está verificado antes de la Fase 1:** que el catálogo del portafolio Qualify.co se conecta a la WABA de Bianki y el multiproducto llega con fotos y precios (lo cierra la validación sin código del paso 0); el permiso que exige escribir `whatsapp_commerce_settings` (§8.2); si Commerce Manager acepta VES, COP y UYU (§8.4). `catalog_management` (§8.1–8.3) **no frena la Fase 1**: CAT-00 registra el identificador a mano; solo frena el conteo de productos de CAT-00 y la Fase 2 (CAT-04). Ya verificado: la forma del mensaje `order` [M-10], los límites del multiproducto [M-9] y que Meta revisa los artículos y puede rechazarlos [M-1] (cuánto tarda, no).

### 7.4 Preguntas para el fundador

1. ¿Firma la opción D (ambos, por fases) con la validación sin código del paso 0 como condición para empezar la Fase 1?
2. ¿Hay una ferretería concreta (nombre, país) que quiera probarlo? Sin ella, CAT-03 y CAT-04 se construyen sobre una hipótesis.
3. ¿El catálogo de WhatsApp entra en todos los planes o solo en uno superior? (decisión de plan: se prepara con `qualify-business-decisions` antes de mostrar el botón a clientes pagos).
4. ¿Acepta publicar la foto principal de cada producto en una URL pública y estable? Meta exige `image` por artículo y vuelve a descargarla [M-7]; la propuesta es una ruta firmada sin caducidad (§4).

## 8. Preguntas abiertas y lo no verificado

1. ¿Basta acceso estándar para `catalog_management` sobre el catálogo de Qualify.co? → probar en
   vivo (§6). `[NO VERIFICADO]`
2. ¿Qué permiso exige `POST /{waba_id}/product_catalogs`, y cuál el `POST` de `whatsapp_commerce_settings` (el botón «Mostrar mi catálogo a mis clientes» de CAT-00)? Las páginas no lo dicen. `[NO VERIFICADO]`
3. ¿Qué activo y qué tarea hay que asignarle al usuario del sistema sobre el catálogo?
   `[NO VERIFICADO]`
4. ¿Acepta Commerce Manager VES, COP y UYU como moneda de catálogo? `[NO VERIFICADO]`
5. ¿Puede un catálogo usado solo en WhatsApp omitir `link`? Si no, ¿qué URL ponemos (perfil de
   Instagram del negocio, una página pública en qualify.la)? `[NO VERIFICADO]`
6. ¿Límite de artículos por catálogo y frecuencia mínima del archivo programado? `[NO VERIFICADO]`
7. ¿Qué productos de ferretería restringen las Políticas de Comercio? `[NO VERIFICADO]`
8. ¿El multiproducto se factura como mensaje de servicio? La página de precios no nombra los
   interactivos; lo razonable es que sí `[H]`. Y, aparte de WA-23: **el cobro de mensajes de
   servicio desde 2026-10-01 [M-12] cambia el costo de todo el módulo de WhatsApp** (comprobado
   dos veces el 2026-11-03: 1.000 mensajes de servicio entregados gratis al mes por número, se
   cobra desde el 1.001; sin método de pago registrado Meta deja de entregarlos pasado el cupo) y
   hay que llevarlo a `modelo-cobro-generacion.md` y corregir
   `docs/plan-modulo-whatsapp-cloud-api.md` §0 punto 8, que aún dice «servicio gratis».
9. `connect.py` exige dos permisos, no tres: `business_management` no está en `REQUIRED_SCOPES`.
   Si C sigue adelante, `catalog_management` y `business_management` entran en esa lista y el
   número de Bianki se reconecta.
