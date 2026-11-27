# Anuncios: colección sin catálogo — factibilidad (m-25113485)

`[PAUSADA 2026-11-24 · decisión de Raúl]` No se construye por ahora: el carrusel de productos
(m-25113484, PR #800) cubre «varios productos con foto y precio». Se retoma cuando haya catálogo
en Meta o una prueba viva (§7) muestre que Instagram la acepta sin catálogo.

> Investigación de solo lectura, 2026-11-24, principal-architect. **Sin llamadas vivas a Meta**
> (no hay cuenta de prueba en este entorno). Etiquetas: **[V]** verificado en documentación
> oficial de Meta o en el SDK `facebook-python-business-sdk` 26.0.0; **[S]** fuente secundaria;
> **[H]** hipótesis. ADR 25 manda: nada de esto se construye sin la prueba viva de §7.

## 1. Veredicto

**Factible por API sin catálogo de Meta, pero NO con los permisos actuales, y con una duda
abierta sobre Instagram que puede tumbarlo.**

- La colección sin catálogo existe en la API: Instant Experience (lienzo) con portada + elementos
  de foto, y miniaturas que apuntan a esos elementos **[V]**.
- Cada elemento de foto del lienzo referencia una **foto subida a la Página de Facebook**
  (`photo_id`), no un `image_hash` de la cuenta publicitaria **[V]**. Subir esa foto
  (`POST /{page_id}/photos`, también con `published=false`) exige **`pages_manage_posts`** +
  tarea `CREATE_CONTENT` **[V]**, permiso que Qualify **no pide** hoy en el flujo de anuncios **[V]**.
- Riesgo que decide: una página de Meta (hoy redirigida, citada por el buscador) dice que en
  Instagram la colección **solo** funciona con la plantilla *Instant Storefront* (que es de
  catálogo) **[S]**. La guía de desarrolladores lista Instagram Feed y Stories como ubicaciones
  de la colección sin condicionar la plantilla **[V]**. Solo una prueba viva lo resuelve.
- Bajo las miniaturas **no** aparecen nombre ni precio sin catálogo: las miniaturas son recortes
  1:1 de las fotos del lienzo **[V]** (`element_crops` solo admite `100x100`). Nombre y precio
  viven dentro del lienzo (elementos de texto) **[H]**. Esto choca con «productos abajo» si el
  dueño espera ver precios en el anuncio.

## 2. Instant Experience (lienzo) por API

- Crear elementos: `POST /{page_id}/canvas_elements` con uno de `canvas_photo`, `canvas_video`,
  `canvas_button`, `canvas_footer`, `canvas_header`, `canvas_text`, `canvas_carousel`,
  `canvas_product_set`, `canvas_product_list`, `canvas_store_locator`, `canvas_lead_form`,
  `canvas_existing_post`, `canvas_template_video` **[V]** (SDK 26.0.0 `Page.create_canvas_element`).
- Crear el lienzo: `POST /{page_id}/canvases` con `name`, `background_color`,
  `body_element_ids`, `is_published`, `is_hidden`, `enable_swipe_to_open`,
  `source_template_id`, `hero_asset_facebook_post_id`, `hero_asset_instagram_media_id` **[V]**
  (SDK 26.0.0 `Page.create_canvase` — así, con la errata).
- **Debe publicarse antes de usarse en un anuncio** («It needs to be published before it can be
  used in ad campaigns») y **solo se edita mientras no está publicado** **[V]**. Un lienzo
  publicado es inmutable: cambiar algo = lienzo nuevo.
- `canvas_photo`: campos `photo_id`, `style` (`FIT_TO_WIDTH`…), `open_url_action {url}`,
  `top_padding`, `bottom_padding`; `product_tags` (con `product_id` de catálogo) está **en lista
  de permitidos** **[V]**. Sin catálogo se usan fotos sin etiquetas.
- `canvas_product_list` y `canvas_product_set` exigen IDs de un catálogo **[V]** → descartados.
- Plantillas por API (`source_template_id`): *Get New Customers* `133471657203838`, *Showcase Your
  Business* `1063217037112304`, *Sell Products (Without Catalog)* `424787857903852`, *Lifestyle*
  `1369752616394017`, *Grid* `1932289657009030` **[V]**. Qué elementos trae cada una se lee con
  `GET /{template_id}?fields=document` **[V]**; no lo probamos **[H]**. No hace falta plantilla:
  armar los elementos a mano es lo documentado.
- Permisos que la guía de Instant Experiences lista: `pages_manage_ads`, `pages_read_engagement`,
  `pages_show_list` y la tarea `ADVERTISE` en la Página **[V]**.

## 3. AdCreative de colección sin catálogo

`POST /act_{ad_account_id}/adcreatives` **[V]** (guía de colección):

```json
{
  "object_type": "SHARE",
  "object_story_spec": {
    "page_id": "<PAGE_ID>",
    "instagram_user_id": "<IG_ID>",
    "link_data": {
      "link": "https://fb.com/canvas_doc/<CANVAS_ID>",
      "message": "<texto>",
      "name": "<titular>",
      "image_hash": "<hash de portada>",
      "call_to_action": {"type": "LEARN_MORE"},
      "collection_thumbnails": [
        {"element_id": "<CANVAS_PHOTO_ID_1>", "element_crops": {"100x100": [[x0, y0], [x1, y1]]}},
        "… exactamente 4 …"
      ]
    }
  }
}
```

- Portada de video: `video_data` con `video_id`, `image_url`, `collection_thumbnails`, y
  `object_type=VIDEO` **[V]**.
- Miniaturas: **cuatro obligatorias**; `element_id` = elemento de foto o de lista de productos;
  **no** puede ser la imagen de cabecera; `element_crops` obligatorio para fotos, solo clave
  `100x100`; `element_child_index` solo para fotos con etiquetas o listas de productos **[V]**.
  SDK 26.0.0: `AdCreativeLinkData.collection_thumbnails: list<AdCreativeCollectionThumbnailInfo>`
  (`element_id`, `element_crops: AdsImageCrops`, `element_child_index`) **[V]**.
- `template_data` existe en `AdCreativeObjectStorySpec` (tipo `AdCreativeLinkData`) **[V]**, pero
  la guía solo lo usa para la variante *template video* con `retailer_item_ids` (catálogo) → no
  aplica **[V]**.
- Las coordenadas de `element_crops` son píxeles de la foto original (cuadrado centrado
  calculado con `width`/`height` que ya guardamos) **[H]**; la muestra de Meta usa
  `[[0,0],[100,100]]`.

## 4. Permisos

| Permiso | ¿Lo pedimos? | ¿Hace falta? |
|---|---|---|
| `ads_management`, `ads_read`, `pages_manage_ads`, `business_management` | Sí, `MetaOAuthSettings.ads_requested_scopes` (`packages/api/src/qualify_api/config.py:58`) **[V]** | Sí (anuncio, lienzo) **[V]** |
| `pages_read_engagement`, `pages_show_list` | Vienen de `QUALIFY_META_SCOPES` (variable de entorno, no en el repo) **[H]** | Sí, para lienzos y fotos de Página **[V]** |
| **`pages_manage_posts`** | **No** en el flujo de anuncios; ningún código del repo lo usa **[V]**; puede estar en `QUALIFY_META_SCOPES` de producción — comprobar con `/me/permissions` **[H]** | **Sí**, para `POST /{page_id}/photos` → `photo_id` de cada `canvas_photo` **[V]** |
| `catalog_management` | Va en la revisión de WhatsApp (decisión D3 del 2026-11-13) | **No** para esta variante **[V]** |

`pages_manage_posts` con acceso estándar sirve para los activos que administra el fundador
(ADR 29) **[H heredada]**; para negocios ajenos necesita App Review **por permiso** (ADR 25/29) y
encaja mal en un caso de uso «publicidad»: Meta revisa que se use para publicar en la Página.
Alternativa a probar: que `canvas_photo` acepte una foto subida con `temporary=true` o una foto
que ya exista en la Página — sigue siendo `POST /{page_id}/photos` → mismo permiso **[H]**.

## 5. Instagram y países

- Ubicaciones de la colección por API: Facebook Feed, Facebook Reels, **Instagram Feed,
  Instagram Stories** **[V]** (guía de colección).
- «The collection ad format can only be used on Instagram with Instant Storefront as the
  post-click Instant Experience template» — página de negocios de Instagram citada por el
  buscador, hoy redirigida a `facebook.com/business/instagram` **[S]**. Si sigue vigente, en
  Instagram la colección necesita catálogo y esta historia no se puede hacer para Instagram.
- Guías de terceros: unas dicen que la colección exige catálogo, otras que Instagram muestra
  *Storefront* y *Customer Acquisition* **[S]**, contradictorias.
- Países: no encontramos restricción específica del formato para CO, VE ni UY **[sin evidencia]**.
  Las restricciones de pago o de cuenta publicitaria en VE son generales de anuncios, no de la
  colección **[H]**.

## 6. Secuencia de llamadas (propuesta, sin probar en vivo)

1. Portada: imagen → `POST /act_{id}/adimages` (ya lo hace el carrusel) **y** `POST
   /{page_id}/photos` `published=false` → `photo_id` para el elemento de cabecera/foto del lienzo.
2. Por cada uno de los 4 productos: `POST /{page_id}/photos` `published=false` → `photo_id`.
3. Por cada producto: `POST /{page_id}/canvas_elements` `canvas_photo={photo_id, style:
   FIT_TO_WIDTH, open_url_action:{url: enlace del producto}}`; más `canvas_text` con
   «Nombre · Precio» **[H]**; y un `canvas_button`/`canvas_footer` con el enlace general
   (`button_style` obligatorio) **[V]**.
4. `POST /{page_id}/canvases` `name`, `body_element_ids=[portada, foto1, texto1, …, pie]`,
   `is_published=true` → `GET /{canvas_id}?fields=canvas_link,is_published`.
5. `POST /act_{id}/adcreatives` como §3, 4 miniaturas = los 4 `canvas_photo` de producto.
6. `GET /{creative_id}/previews?ad_format=INSTAGRAM_STANDARD` y `INSTAGRAM_STORY` — si Meta
   rechaza, aquí aparece la restricción de §5.
7. Anuncio en pausa con el `creative_id`, igual que hoy.

## 7. Riesgos

1. **Instagram puede exigir Instant Storefront (catálogo)** **[S]** — decide toda la historia.
   Validar con los pasos 1–6 sobre la cuenta de prueba en pausa del fundador (m-24828971, de
   Herwin) antes de escribir código. Costo de la prueba: US$0 (anuncio en pausa).
2. **Permiso nuevo `pages_manage_posts`** — una revisión de App Review más y reconectar cada
   cuenta; justificar su uso solo para fotos no publicadas puede ser rechazado.
3. **Sin precios bajo la portada**: las miniaturas son solo fotos; el precio queda en el lienzo.
4. **Lienzo inmutable tras publicar**: cada cambio crea fotos de Página, elementos y un lienzo
   nuevos; hay que guardar sus ids (procedencia, reintentos idempotentes) y no hay limpieza
   documentada de lienzos publicados **[H]**.
5. `product_tags` en `canvas_photo` está en lista de permitidos **[V]** — no contar con etiquetas.

## 8. Esquema de implementación reutilizando el carrusel

`packages/api/src/qualify_api/ads/carousel.py` (m-25113484, en esta rama) ya resuelve casi todo:

- `CollectionSource` = `CarouselSource` + `cover: ImageSelection`, con `cards` **exactamente 4**
  (`MIN_CARDS = MAX_CARDS = 4`) y las mismas validaciones de `snapshot()` (JPG/PNG, nombre y precio
  del Catálogo, enlace `https`). Pipeline `ad-catalog-collection-v1`.
- `collection_payload()` hermano de `carousel_payload()`: misma CTA y `page_id`/`instagram_user_id`,
  pero `link` = `canvas_link` y `collection_thumbnails` en lugar de `child_attachments`.
- Lo nuevo es un paso de **preparación del lienzo** (fotos de Página → elementos → lienzo
  publicado) en `unpublished_service` junto a la subida de imágenes, fuera de la petición
  (trabajador), con los ids de foto/elemento/lienzo guardados en el registro de carga con RLS
  (como 0181 hace con los `image_hash`) para reintentar sin duplicar.
- Una guarda de permisos como la de `lead_forms_service.py:45` que exija `pages_manage_posts`
  y lleve a «Reconecta tu cuenta» si falta.
- Ninguna tabla, servicio ni proveedor nuevo; una revisión de migración solo para las columnas
  de ids del lienzo **[H]**.

## 9. Fuentes

- Guía de colección (v27.0): https://developers.facebook.com/docs/marketing-api/guides/collection
  y https://developers.facebook.com/documentation/ads-commerce/marketing-api/creative/collection-ads
- Instant Experiences: https://developers.facebook.com/docs/marketing-api/guides/instant-experiences
- Canvas Photo: https://developers.facebook.com/docs/marketing-api/reference/canvas-photo
- Canvas Product List: https://developers.facebook.com/docs/marketing-api/reference/canvas-product-list
- Fotos de Página (permisos): https://developers.facebook.com/docs/graph-api/reference/page/photos/
- SDK 26.0.0: https://github.com/facebook/facebook-python-business-sdk/tree/26.0.0/facebook_business/adobjects
  (`page.py` `create_canvas_element`/`create_canvase`, `canvas.py`, `adcreativelinkdata.py`,
  `adcreativecollectionthumbnailinfo.py`, `adcreativeobjectstoryspec.py`)
- **[S]** https://business.instagram.com/a/collection-on-instagram (redirige; frase citada por el buscador)
- **[S]** https://cropink.com/facebook-collection-ads, https://www.socialmediaexaminer.com/how-to-use-instant-experiences-on-facebook-and-instagram/
- Repo: `packages/api/src/qualify_api/config.py:58`, `connections/meta_oauth.py:222-226`,
  `ads/carousel.py`, `ads/lead_forms_service.py:45`, `docs/anuncios-pieza-sin-publicar.md` § carrusel.
