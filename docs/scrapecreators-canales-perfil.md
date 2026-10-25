# ScrapeCreators por canal — qué podemos mostrar en «Esto es lo que vimos en tu Instagram»

Épica m-24852192. Descubrimiento 2026-10-24, medido con la CLI oficial (`scrapecreators` 1.0.87,
equivalente a `just sc …`). Saldo antes: 6874 créditos.

Cuentas medidas (solo datos públicos; aquí no se copian payloads):

| Cuenta | Red | Por qué | Estado medido |
|---|---|---|---|
| `bianki.sc` | IG | cliente real | 2 seguidores, **0 publicaciones**, categoría «Restaurant», bio con dirección y horario, 2 enlaces en la bio (WhatsApp y web) |
| `qualifymkt.co` | IG | cuenta propia | 3 seguidores, **0 publicaciones**, sin bio, sin categoría |
| `paraisodelpan` | IG | panadería pequeña de Ureña (Táchira, VE), hallada con `search-profiles` | 179 seguidores, 35 publicaciones, categoría «Bakery», **última publicación en 2021** |
| `crepesywaffles` | IG | marca grande de comida en CO (contraste; respuesta de caché, 0 créditos) | 1 M seguidores, verificada, enlace a Linktree |
| TikTok: ver §2 | | | |

**Hallazgo de partida:** las dos cuentas propias que vamos a dar de alta primero tienen **0
publicaciones**. La pantalla debe estar diseñada para el caso «cuenta nueva»: todo lo que
dependa de publicaciones (miniaturas, frecuencia, mejores publicaciones, promedios,
etiquetas que ya usa) tiene que poder ocultarse sin dejar huecos.

## 0. Qué lee y guarda hoy el prellenado

Código en `origin/main` (12fc775d). En este árbol de trabajo los archivos aún no existen.

- `referentes/scrapecreators_client.py · fetch_profile_and_posts(network, handle)` =
  1 llamada de perfil (`/v1/instagram/profile` o `/v1/tiktok/profile`) + de 1 a 5 páginas
  de publicaciones (`/v2/instagram/user/posts` o `/v3/tiktok/profile/videos`, `sort_by=latest`)
  hasta salir de la ventana de 7 días. Tope: `CallCaps.scrapecreators_requests = 6`.
- La «instantánea» normalizada (`SNAPSHOT_SCHEMA = 4`, guardada en `creator_profile_cache`
  por inquilino) conserva: `username, fullName, bio, category` (IG: `category_name` →
  `business_category_name` → `overall_category_name`; TikTok siempre vacío), `followers,
  following, postsCount, isVerified, isPrivate, profilePicUrl, externalUrl` (TikTok siempre
  vacío), `relatedProfiles` (IG), `totalLikes` (TikTok), `fetchedAt`, `recentPosts` (solo
  `postId, takenAt, likes, comments, views, shares, aiGenerated, aiLabel, aiSource` de los
  posts **de los últimos 7 días**), `topHashtags` (12 más usadas en todas las páginas leídas),
  `recentCaptions` (12 textos, 300 caracteres c/u).
- **Se descarta**: `bio_links` (enlaces de la bio, incluido el de WhatsApp), miniaturas y
  enlaces de cada publicación, ubicaciones etiquetadas, la cuadrícula de 12 publicaciones que
  ya trae el propio perfil de IG, `is_professional_account`, `highlight_reel_count`, `id`.
- `creative/brand_prefill.py · _propose()` escribe en `brand_kit_details.connect.prefill.proposal`:
  - `connect`: `network, username, sector, rubro_text, country_code, city, hashtags` (las
    sugeridas, en píldoras);
  - `profile` (`profile_document`): `username, fullname, bio, category, followers` (texto
    «12.000»), `followers_count, pic` (**la URL firmada del CDN, no una copia en R2**),
    `metrics` (Publicaciones / Interacción / Likes por publicación, ventana 7 días);
  - `palette`: `palette, logo_colors, logo_source="profile"` (colores de la foto de perfil);
  - más `usage` (créditos, tokens) y `provenance` (endpoints, `fetched_at`, ejecuciones de Claude).
- **Las etiquetas que ya usa no se guardan en la propuesta** (`topHashtags` vive solo en la
  instantánea de `creator_profile_cache`); ciudad y país salen de **texto** (bio + categoría)
  vía `discovery_seed.seed_from_profile`, no de ubicaciones etiquetadas.

## 1. Endpoints de Instagram

Costo leído de `--help` y confirmado con `credits_charged` en cada respuesta. «Caché» =
acepta `--cache-max-age` (0 créditos si ScrapeCreators ya tiene una copia). Sin caché = cada
llamada cobra.

| Endpoint (CLI) | Ruta | Créditos | Caché | Para qué sirve aquí |
|---|---|---|---|---|
| `instagram profile --handle` | `/v1/instagram/profile` | 1 | sí | **Todo lo de la cabecera + las 12 últimas publicaciones** |
| `instagram user-posts --handle` | `/v2/instagram/user/posts` | 1 por página (12) | **no** | Lo que ya trae el perfil, paginable (más de 12) |
| `instagram user-reels --handle` | `/v1/instagram/user/reels` | 1 por página | no | Solo reels; trae **fijados** (`timeline_pinned_user_ids`) |
| `instagram user-highlights --handle` | — | 1 | no | Historias destacadas (lista) |
| `instagram user-highlight-detail --id` | | 1 | no | Contenido de una destacada |
| `instagram post --url` | `/v1/instagram/post` | 1 (10 con `--download-media`) | sí | Detalle de una publicación |
| `instagram basic-profile --userId` | | 1 | sí | Perfil reducido por id |
| `instagram profile-post-count --handle` | | 1 (422 sin cobro si solo hay estimado) | — | Solo el total de publicaciones (el perfil ya lo trae) |
| `instagram search-profiles --query` | | 1 | no | Buscar cuentas por nombre (útil al operador del Alta, no a la pantalla) |
| `instagram user-tagged-posts --user-id` | | 1 | no | Publicaciones donde otros etiquetan a la marca (no se probó) |
| `instagram user-embed`, `media-transcript`, `post-comments` | | 1 | — | Fuera del alcance de esta pantalla |

### 1.1 `instagram profile` — campos útiles (medido en las 4 cuentas)

`data.user.`:
- Identidad: `username, full_name, id, fbid, is_verified, is_private, is_professional_account,
  is_business_account` (falso incluso en negocios: no sirve para distinguir),
  `profile_pic_url`, `profile_pic_url_hd`.
- Texto: `biography`, `biography_with_entities.entities[]` (vacío en las 4), `pronouns[]`.
- Categoría: `category_name`, `business_category_name`, `overall_category_name` (en inglés:
  «Restaurant», «Bakery»; `null` en `qualifymkt.co`), `should_show_category`.
- Enlaces: `external_url` (Linktree en la marca grande; vacío en Bianki aunque tiene enlaces),
  **`bio_links[]` → `{title, url, link_type ("external"|"whatsapp"), lynx_url, is_pinned}`**
  (Bianki: «Pedir por WhatsApp» → `wa.me/58…` y su web; la panadería: `wa.me/57…`).
- Contacto de empresa: `business_email`, `business_phone_number`, `business_address_json`,
  `business_contact_method`, `should_show_public_contacts` → **vacíos / `UNKNOWN` en las 4
  cuentas, incluida la marca grande**: la lectura sin sesión no los expone. No contar con ellos.
- Cifras: `edge_followed_by.count` (seguidores), `edge_follow.count`,
  `edge_owner_to_timeline_media.count` (total de publicaciones), `highlight_reel_count`
  (**0 en las 4, incluso en la marca grande → no fiable**), `has_clips`, `hide_like_and_view_counts`.
- **`edge_owner_to_timeline_media.edges[0..11].node`** — las 12 publicaciones más recientes,
  ya pagadas con el perfil: `shortcode, url, __typename (XDTGraphImage / XDTGraphVideo medidos),
  is_video, product_type ("clips" = reel), display_url, thumbnail_src, display_resources[]
  (10 tamaños), video_url, dimensions, taken_at_timestamp, edge_media_to_caption…text,
  edge_media_preview_like.count, comment_count, video_view_count, video_play_count,
  location {name, lat, lng}` (7 de 12 publicaciones de la panadería: «Ureña, Tachira,
  Venezuela»), `is_paid_partnership, is_ad, coauthor_producers`, `edge_media_to_tagged_user`.
  No trae marca de «fijada».
- `edge_related_profiles` (cuentas parecidas): vacío en las 4.

### 1.2 `instagram user-posts` — campos útiles

`items[]` (12 por página, `next_max_id` + `more_available`): `code, url, pk, media_type
(1 foto, 2 video, 8 carrusel), product_type, taken_at, caption.text, like_count,
comment_count, play_count/ig_play_count, like_and_view_counts_disabled, display_uri,
image_versions2.candidates[].url, video_versions[], video_duration, location, usertags,
ai_label_info, accessibility_caption` (texto alternativo de Instagram, p. ej. «Video by …
on June 2…»), `is_paid_partnership`. **Mismas 12 publicaciones que el perfil**: la primera
página no añade nada que el perfil no traiga; solo sirve para ir más atrás. No trae marca de fijada.

### 1.3 `instagram user-reels`

`items[].media`: lo de arriba para reels (`like_count, comment_count, play_count, caption.text,
image_versions2, video_duration, code`) + **`timeline_pinned_user_ids[]` y
`clips_tab_pinned_user_ids[]`** (fijado en la cuadrícula / en la pestaña de reels) y
`locations[]`. Paginación `paging_info.max_id/more_available`. Panadería: 11 reels en 1 página.

### 1.4 `instagram user-highlights`

`highlights[]` — vacío en la panadería (y `highlight_reel_count` = 0 en las 4 cuentas). No
se pagó `user-highlight-detail`. Las historias (24 h) no tienen endpoint por usuario.

### 1.5 Duración de las URL de imagen (IG)

Las URL de `cdninstagram.com` llevan `oe=<hex>` = vencimiento Unix. Medido en el momento de la
lectura: **foto de perfil y miniaturas ≈ 104–108 h (≈ 4,4 días); video ≈ 35 h**. Coincide con
lo que ya documentó `Qualify/avatar_proxy.py` («~3-4 días en Instagram, ~1 día en TikTok») y su
lección: una URL guardada se muere sola, y una lectura servida desde caché (de ScrapeCreators o
de `creator_profile_cache`) puede llegar **ya vencida**. Hoy `proposal.profile.pic` guarda la
URL del CDN, no una copia: si el dueño entra 5 días después del Alta, la foto no carga. Para
foto de perfil y miniaturas: **descargar los bytes en el mismo trabajo del Alta y subirlos a
R2** (0 créditos extra; ~12 descargas pequeñas al CDN).

## 2. Endpoints de TikTok

Cuentas medidas (halladas con `tiktok search-users --query "comida rapida cucuta"`, 1 crédito):
`comidasneftincucuta` (comidas rápidas, Cúcuta; 3.645 seguidores, 185 videos, publica varias
veces por semana) y `karli.comidarapida` (comidas rápidas, Cúcuta; 1.840 seguidores, 96 videos).

| Endpoint (CLI) | Ruta | Créditos | Caché | Para qué sirve aquí |
|---|---|---|---|---|
| `tiktok profile --handle` | `/v1/tiktok/profile` | 1 | sí | Cabecera. **`itemList` vino vacío en las 2 cuentas**: no trae videos |
| `tiktok profile-videos --handle --sort-by latest` | `/v3/tiktok/profile/videos` | 1 por página (10) | no | Últimos videos, con fijados (`is_top`) salvo `--include-pinned false` |
| `tiktok profile-videos --sort-by popular` | ídem | 1 por página (10) | no | **Los 10 más vistos de siempre** — «tus mejores videos» en 1 crédito |
| `tiktok video --url` | | 1 (10 con `--download-media`) | sí | Detalle + subtítulos nativos (`--get-transcript`, mismo precio) |
| `tiktok profile-region --handle` | | no indicado en `--help` | — | País de la cuenta (no se llamó) |
| `tiktok user-audience --handle` | | no indicado en `--help` | — | Demografía de la audiencia (no se llamó; no apto para una pantalla de primer ingreso) |
| `tiktok user-showcase --handle` | | no indicado | — | Vitrina de TikTok Shop (no aplica: Shop no opera en CO/VE) |
| `tiktok search-users --query` | | 1 | no | Buscar la cuenta por nombre (operador del Alta) |

### 2.1 `tiktok profile` — campos útiles

`user.`: `uniqueId` (el usuario), `id` y `secUid` (**identificadores estables**: el usuario se
puede cambiar, `uniqueIdModifyTime`), `nickname`, `signature` (bio — en ambas cuentas trae
**dirección y teléfono** escritos a mano), **`bioLink.link`** (Neftin: enlace a su Instagram),
`avatarLarger/Medium/Thumb`, `verified`, `privateAccount`, `language` («es»), `createTime`,
`commerceUserInfo.commerceUser`, `ttSeller`, `isOrganization`. `stats.`/`statsV2.`:
`followerCount, followingCount, heartCount` (me gusta recibidos en total), `videoCount`,
`friendCount`. **No hay categoría ni rubro**, ni correo/teléfono estructurados, ni ubicación.

### 2.2 `tiktok profile-videos` — campos útiles

`aweme_list[]` (10 por página, `max_cursor` + `has_more`): `aweme_id, share_url, desc` (texto),
`create_time, desc_language, region` («CO» en los 20 videos), **`is_top`** (fijado),
`aweme_type`, `image_post_info` (si es carrusel de fotos), `text_extra[].hashtag_name`,
`statistics.{play_count, digg_count, comment_count, share_count, collect_count,
whatsapp_share_count, repost_count}`, `video.{duration (ms), cover.url_list[],
origin_cover.url_list[], dynamic_cover}`, **`anchors[]` con `schema = aweme://poi/detail`** →
lugar etiquetado: `keyword` («Cúcuta»), `extra.location.{lat,lng}`, `extra.poi_backend_type`
(10 de 10 videos populares de Karli), `aigc_info` (etiqueta de IA), `author.*` (copia del perfil).

### 2.3 Duración de las URL (TikTok)

`x-expires` en la URL: **portadas de video ≈ 23 h; foto de perfil ≈ 47 h**. Más corto que
Instagram: copiar a R2 en el mismo trabajo es obligatorio, no opcional.

## 3. Tabla campo → disponibilidad → pantalla

Leyenda: **Instantánea** = lo que `fetch_profile_and_posts` ya conserva; **prefill** = lo que
`connect.prefill.proposal` guarda hoy; **Pantalla** = si se puede mostrar sin inventar.
Créditos extra = sobre el costo actual del Alta (IG: 2 típicos; ver §5).

| Campo | IG | TikTok | Instantánea | prefill | Pantalla | Créditos extra |
|---|---|---|---|---|---|---|
| Foto de perfil | sí | sí | URL | URL (vence ~4 d IG / ~2 d TT) | sí, **copiada a R2** | 0 |
| Usuario, nombre visible | sí | sí | sí | sí | sí | 0 |
| Bio | sí | sí | sí | sí | sí (cita) | 0 |
| Categoría de Instagram | sí, en inglés («Restaurant», «Bakery»); vacía en `qualifymkt.co` | **no existe** | sí | sí | sí, **traducida** y solo si viene | 0 |
| Rubro (Claude) | derivado | derivado | — | sí (`rubro_text`, `sector`) | sí | 0 |
| Ciudad / país | texto de la bio; **+ lugares etiquetados** en publicaciones | texto de la bio; **+ lugar etiquetado** (`anchors` POI) y `region` por video | solo texto | sí (`city`, `country_code`) | sí, con «según tu bio/tus publicaciones» | 0 |
| Seguidores | sí | sí | sí | sí | sí | 0 |
| Siguiendo | sí | sí | sí | no | no aporta | — |
| Total de publicaciones | sí | sí | `postsCount` | no | sí | 0 |
| Me gusta totales recibidos | no | sí (`heartCount`) | `totalLikes` | no | sí en TikTok | 0 |
| Verificada | sí | sí | sí | no | sí (insignia) si es verdadero | 0 |
| **Enlaces de la bio** (título + URL) | sí, `bio_links[]` | sí, uno (`bioLink.link`) | **no** (solo `external_url`, vacío en Bianki) | no | **sí** | 0 |
| Enlace de WhatsApp | sí si está en `bio_links` (`wa.me/…`, `link_type`) | solo si lo escribió en la bio | no | no | sí, como «Tu botón de pedidos» (ver §4 PII) | 0 |
| Correo / teléfono / dirección de empresa (campos de Meta) | campos existen, **vacíos en 4/4** | no existen | no | no | **no** — no contar con ellos | — |
| **Miniaturas de publicaciones** | sí, 12 en el perfil | sí, 10 por página | **no** | no | **sí, cuadrícula de 6–12** (copiadas a R2) | IG 0 · TT 0 (ya se pide la página) |
| Textos (captions) | sí | sí | 12 × 300 car. | no | sí, una cita breve | 0 |
| Etiquetas que ya usa | sí | sí | `topHashtags` (12) | **no** | sí | 0 (falta guardarlas) |
| Etiquetas sugeridas | Claude + catálogo | ídem | — | sí | sí | 0 |
| Frecuencia de publicación | de 12 fechas | de 10 fechas/página | solo 7 días | solo «Publicaciones (7 días)» | sí, «publicas ~N por semana» o «última hace N meses» | 0 |
| Mejores publicaciones | ordenar las 12 por me gusta+comentarios | **`sort_by=popular`: top 10 de siempre** | no | no | sí («tus publicaciones que más gustaron») | IG 0 · TT +1 |
| Promedio de me gusta / comentarios | de las 12 | de las 10 | solo ventana 7 d | métrica «Likes por publicación» | sí, sobre las últimas N (decirlo) | 0 |
| Reproducciones | reels: `play_count` | `play_count` | `views` | no | sí en videos | 0 |
| Fijadas | solo vía `user-reels` (`timeline_pinned_user_ids`), no en perfil ni posts | `is_top` en `profile-videos` | no | no | opcional | IG +1 · TT 0 |
| Historias destacadas | `user-highlights` (vacío; `highlight_reel_count` = 0 incluso en marca grande) | no | no | no | **no** (no fiable) | +1 |
| Historial de seguidores | **no** (el proveedor no lo da) | no | no | no | no en el primer ingreso; requiere lecturas nuestras repetidas | — |
| Cuentas parecidas | `edge_related_profiles` (vacío 4/4) | no | `relatedProfiles` | no | no | — |
| Etiqueta «hecho con IA» | `ai_label_info` | `aigc_info` | sí | no | no aporta | — |
| Tono de voz | inferible de los textos (Claude) | ídem | captions | no | **sí, solo si hay ≥ 3 textos**, como sugerencia editable | 0 créditos, +1 llamada a Claude |
| «Qué te hace distinto» | no está en los datos | no | — | no | no (pregunta al dueño) | — |

**Filas que cambian la maqueta** (lo que la propuesta UX marcó «no disponible» o no mostró):
1. **Imágenes de publicaciones: sí disponibles**, y en IG ya pagadas con el perfil
   (`edge_owner_to_timeline_media.edges`, 12). Solo falta no tirarlas y copiarlas a R2.
2. **Enlaces de la bio** (`bio_links`): la instantánea solo guarda `external_url`, que en Bianki
   está vacío aunque tiene «Pedir por WhatsApp» y su web. Hay que leer `bio_links`.
3. **Frecuencia, mejores publicaciones y promedios** salen gratis de las 12/10 publicaciones;
   la métrica actual de 7 días da «0 publicaciones» a toda cuenta nueva o poco activa
   (Bianki, `qualifymkt.co`, la panadería).
4. **Tono de voz**: posible cuando hay textos, como propuesta editable; nunca en cuentas sin
   publicaciones.
5. **Lugar etiquetado** mejora ciudad/país (la panadería: «Ureña, Tachira, Venezuela» en 7/12;
   Karli: «Cúcuta» en 10/10).
6. **Categoría**: llega en inglés y no existe en TikTok — mostrarla traducida o no mostrarla.
7. **Destacadas, contacto de empresa, historial de seguidores: no** — sacarlos del diseño.

## 4. Puntos específicos

- **Miniaturas y vida de sus URL.** IG: `display_url` / `thumbnail_src` / `display_resources[]`
  (10 tamaños; usar ~480 px) en el perfil; vencen a las ~104–108 h. TikTok:
  `video.cover.url_list[0]` (o `origin_cover`), vence a las ~23 h. Descargarlas dentro del
  trabajo del Alta con las mismas reglas que `brand_prefill.fetch_picture` (solo hosts del CDN,
  tope de bytes, redirecciones a mano) y guardar en R2 bajo el prefijo del inquilino. Guardar
  en la propuesta la clave de R2, no la URL del proveedor. `--download-media` del proveedor
  cuesta **10 créditos por publicación**: no usarlo. Al estar en R2 aplica la retención de
  ADR 39 y el reintento de escritura (regla 3 del generador).
- **Textos.** IG `caption.text` / `edge_media_to_caption`, TikTok `desc`; ya se guardan 12
  (300 caracteres). Mostrar como mucho una cita corta, entre comillas y atribuida.
- **Frecuencia.** IG: con 12 fechas del perfil se calcula «N por semana» si la última es
  reciente, o «tu última publicación fue hace N meses» (la panadería: junio 2021). TikTok: 10
  fechas por página (Neftin: 10 videos en ~23 días). No usar la ventana de 7 días para esto.
- **Mejores publicaciones.** IG no tiene orden por popularidad: se ordenan las 12 recientes
  por me gusta + comentarios (decir «de tus últimas 12»). TikTok: `sort_by=popular` = top 10
  de siempre por 1 crédito (Karli: 392.375 reproducciones el primero).
- **Contacto de empresa (PII).** Los campos estructurados de Meta (`business_email`,
  `business_phone_number`, `business_address_json`) vienen vacíos sin sesión — también en la
  marca de 1 M de seguidores. Lo que sí llega es lo que el negocio publicó: enlaces `wa.me/<número>`
  en `bio_links` (Bianki, la panadería) y teléfono/dirección escritos en la bio (las dos de
  TikTok). Es dato público del propio negocio y se le muestra a su dueño, pero: guardarlo solo
  en el documento del inquilino (RLS), no en logs ni proveniencia, no enviarlo a ningún
  endpoint de BytePlus que ceda datos, y mostrar «Tu botón de WhatsApp» con el número
  enmascarado salvo que el dueño lo confirme. Si en una cuenta personal aparece un número, no
  mostrarlo.
- **Enlace externo / Linktree.** IG: `external_url` (Linktree en la marca grande) y `bio_links[]`
  (con `title`); TikTok: `bioLink.link` (Neftin apunta a su Instagram → ofrecer conectar la otra
  red). No se abre ni lee el Linktree: hoy no se lee ninguna web (regla de `brand_prefill`).
- **Lugares etiquetados.** IG: `node.location {name, lat, lng}` en el perfil y `location` en
  user-posts; TikTok: `anchors[]` con `schema aweme://poi/detail`. Usar como segunda fuente de
  ciudad cuando la bio no la dice, con la fuente registrada.
- **Fijadas.** IG solo en `user-reels` (`timeline_pinned_user_ids`, +1 crédito, y solo reels);
  TikTok `is_top` gratis en `profile-videos`. Bajo valor para esta pantalla.
- **Historial de seguidores.** Ningún endpoint lo da. Solo existe si nosotros leemos el perfil
  varias veces (`qualify_api.growth` ya guarda historia de TikTok). En el primer ingreso hay
  una sola lectura: no mostrar crecimiento (coincide con `profile_metrics`).
- **Verificada.** `is_verified` / `verified`; falso en todas las cuentas pequeñas medidas.
- **Categoría de empresa.** Solo IG, en inglés y opcional; `is_business_account` es falso en
  todas (también en la marca grande): usar `is_professional_account` si hace falta.
- **Promedios.** Me gusta y comentarios medios sobre las últimas 12 (IG) / 10 (TikTok);
  ojo con `like_and_view_counts_disabled` (IG) — ya se respeta en `_normalize_instagram_posts`.

## 5. Versión TikTok de la pantalla y créditos por Alta

**Normalización del usuario** (igual en ambas redes, ya en `_normalize_handle`: minúsculas,
sin `@`). Falta aceptar enlaces pegados (`instagram.com/<usuario>/…`,
`tiktok.com/@<usuario>`, `vm.tiktok.com/…` — este último no se puede resolver sin una
llamada). En TikTok guardar además `user.id` / `secUid`: el usuario se puede cambiar y el
reclamo de cuenta (`account_claims`) quedaría huérfano.

**Lecturas por Alta**

| | Hoy | Propuesta para la pantalla |
|---|---|---|
| Instagram | perfil (1) + `user-posts` 1–5 páginas → **2 típicos** (cuenta nueva o poco activa: 2), tope 6 | **perfil solo (1)**: leer `edges` del perfil (12 publicaciones) y pedir `user-posts` solo si las 12 caben en 7 días (cuenta muy activa). Mismo dato, **1 crédito** |
| TikTok | perfil (1) + `profile-videos latest` 1–5 páginas → **2 típicos**, tope 6 | perfil (1) + `latest` (1, más páginas solo si la ventana lo pide) + `popular` (1) → **3 típicos**, tope 7 |
| Imágenes a R2 | 0 (foto de perfil solo se lee para la paleta) | 0 créditos; ~13 descargas al CDN |
| Claude | hasta 3 (rubro, catálogo, creación) | +1 opcional para tono de voz |

**Qué cambia en la pantalla TikTok** frente a la de Instagram: sin categoría (el rubro lo pone
Claude, ya es así); con «me gusta recibidos» totales; videos en vez de publicaciones
(portada 9:16, reproducciones); «tus videos más vistos» real (`popular`); ciudad desde POI y
`region`; el enlace de la bio a menudo es su Instagram.

**Modelo de datos sin depender de la red** — la propuesta ya lleva `network`; añadir en la
instantánea (subir `SNAPSHOT_SCHEMA`) y en `proposal.profile` campos comunes:
`stable_id`, `links[{title, url, kind: whatsapp|web|social|other}]`,
`recent_media[{id, url, kind: photo|video|carousel, taken_at, caption, likes, comments,
views, pinned, place, thumb_r2_key}]`, `top_media_ids[]` + `top_media_basis`
(«últimas 12» o «de siempre»), `place_hint{city, country_code, source: bio|tag|region}`,
`total_likes` (nulo en IG), `category` (nulo en TikTok), `pic_r2_key`. La pantalla pinta lo que
venga y oculta lo nulo.

## 6. Créditos gastados

- Saldo antes: **6874**. Saldo después: **6859** (Δ 15).
- Atribuibles a este trabajo: **12** — 10 con `credits_charged = 1` en la respuesta
  (`instagram search-profiles`, `profile`, `user-posts`, `user-reels`, `user-highlights` de
  `paraisodelpan`; `tiktok search-users`, 2 × `profile`, 2 × `profile-videos`) + **2** de los
  primeros `instagram profile --output …` de `bianki.sc` y `qualifymkt.co`: la CLI respondió
  «Request failed» al escribir el archivo pero **cobró la lectura** (la copia apareció luego en
  caché con esa hora). Las 3 de diferencia restantes no son de estas llamadas: la clave es
  compartida y hubo un salto de 2 entre dos llamadas seguidas (otro proceso usándola).
- 0 créditos: `bianki.sc` y `qualifymkt.co` (segunda lectura, caché), `crepesywaffles` (caché).
- Trampa para la skill `qualify-scrapecreators`: **`--output <ruta>` falló en la CLI 1.0.87 y
  aun así cobró**; redirigir la salida estándar (`> archivo.json`) funcionó. `--cache-max-age`
  solo existe en `profile`, `post`, `basic-profile`, `tiktok profile` y `tiktok video`;
  `user-posts`, `user-reels`, `user-highlights`, `search-*` y `profile-videos` no lo ofrecen en
  `--help` (`search-profiles` lo rechazó: «unknown option»). Toda página de publicaciones cobra.
- Copias crudas con datos públicos de perfiles: fuera del repositorio (carpeta de trabajo de la sesión del 2026-10-24, no versionada).
