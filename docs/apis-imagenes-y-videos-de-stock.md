# APIs de imágenes y videos de stock para el generador (`/create`)

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

`[INVESTIGACIÓN VENDOR 2026-10-16]` · fuentes consultadas el 2026-10-16 · **sin cuentas creadas ni claves usadas**

Marcas: **[DOC]** documentación o licencia oficial leída hoy · **[LIVE]** llamada real a la API, sin clave · **[2ª]** fuente de terceros · **no verificado** = no confirmado en fuente primaria (página con 403, contenido tras login o precio solo por ventas) · **inferencia** = lectura nuestra, no lo dice el proveedor.

**Pregunta del fundador.** Queremos una fuente de imágenes y videos de stock que funcione con API key, para que el operador (o el propio generador) busque e inserte media libre de regalías en una pieza: flyer, carrusel/«Galería», clip corto o avatar. Hoy `/create` solo usa el catálogo de productos, subidas y piezas anteriores. El fundador mencionó Pixabay como ejemplo.

**Motor de compra:** activación (la marca produce contenido). No toca la escucha. **Fase:** el generador creativo es *dogfooding* sobre medios propios (Parte 4-A, ADR 21) y Motor de Contenido de Marca. Es infraestructura que **se compra, no se construye**: solo nos toca el selector, la descarga a R2 y la procedencia.

**Cómo usaría Qualify el stock**, y lo que cada licencia tiene que permitir:
1. uso comercial en anuncios y publicaciones de marca;
2. guardar el archivo elegido en nuestro bucket R2;
3. editarlo y componerlo (producto sobre fondo de stock, texto encima);
4. usarlo como entrada o referencia de modelos generativos (Seedream, Seedance);
5. que **varios tenants** busquen con **nuestra** clave.

---

## Alternativa a Pexels (2026-10-16)

`[ADDENDUM 2026-10-16 · gtm-specialist]` · todo re-verificado hoy en páginas oficiales · **sin cuentas creadas ni claves usadas**. Esta sección manda sobre §1-§5 donde las contradiga.

**Dos hechos nuevos.**
1. **Pexels pausó la emisión de claves.** [pexels.com/api](https://www.pexels.com/api/) dice dos veces «New API key issuance is currently paused.» Sin lista de espera ni fecha. **[DOC]**
2. El fundador dice que **Pixabay «no tiene por ahora videos»**. Lo verificamos primero (A).

### A. Pixabay y el video: lo que es verdad hoy

**Veredicto: la API de video de Pixabay existe, está documentada y responde. No hay aviso de retirada, pausa ni restricción.** Lo que sí es cierto es que es más pobre que la de Pexels.

- **La documentación oficial la incluye** ([pixabay.com/api/docs](https://pixabay.com/api/docs/), leída hoy). **[DOC]**
  - La portada dice: «Our API is a RESTful interface for searching and retrieving royalty-free images and videos released by Pixabay under the Content License».
  - Tiene su propia sección, «Search Videos», con `GET https://pixabay.com/api/videos/`.
  - Parámetros: `key`, `q`, `lang` (incluye `es`), `id`, `video_type` («all», «film», «animation»), `category`, `min_width`, `min_height`, `editors_choice`, `safesearch`, `order`, `page`, `per_page`.
  - Respuesta: `duration` y `videos{large, medium, small, tiny}`, cada uno con `url`, `width`, `height`, `size` y `thumbnail`.
  - En toda la página no hay aviso de *deprecated*, *paused* ni *discontinued*, ni ninguna restricción propia del video.
- **[LIVE] El endpoint sigue activo.** Sin clave, `GET https://pixabay.com/api/videos/?q=cafe` responde `400 [ERROR 400] Invalid or missing API key`, **el mismo error** que el endpoint de imágenes `GET https://pixabay.com/api/?q=cafe`. *Inferencia:* un endpoint retirado respondería 404 o 410, no pediría la clave.
- **Terms sin cambios:** siguen siendo los del «Last updated: November 18, 2024», y su §2 define «Videos» como contenido licenciado ([Terms](https://pixabay.com/service/terms/)). **[DOC]**
- **Prensa y foros:** no encontramos ningún anuncio de retirada (búsqueda web hoy). **[2ª]**
- **Lo que de verdad limita el video de Pixabay:**
  - (a) **No hay filtro de orientación.** `orientation` solo existe en imágenes, así que el 9:16 se filtra en el cliente con `height > width`.
  - (b) «If a large video version is not available, an empty URL value and a size of zero is returned».
  - (c) El tope de 500 resultados accesibles por consulta deja **pocos verticales**.
  - (d) El «full API access» solo afecta a las imágenes de alta resolución («Request full API access for retrieving high resolution images»). No toca el video.
- **No verificado:** cuántos videos verticales devuelve en español para los rubros reales. No se puede medir sin clave, y la web `pixabay.com/videos/…` responde 403 de Cloudflare a `curl`.
- **Si el fundador vio «sin videos» con su propia clave** (por ejemplo, una consulta con `hits: []`), conviene revisar la URL exacta, sin la clave. Es lo único que podría contradecir la documentación. *Hipótesis* de dónde viene la confusión: la página de docs muestra la clave y el filtro de orientación solo en «Search Images».

### B. Candidatos a sustituir a Pexels, re-verificados hoy

Criterio duro: **fotos y video por API**, con **clave obtenible hoy por autoservicio** (sin pausa y sin pasar por ventas).

| Proveedor | Fotos + video por API | Vertical 9:16 | Clave hoy | Gratis / precio | Límites | Licencia para Qualify (comercial · atribución · R2 · edición) | IA como entrada | Multi-tenant / SaaS | Español | Encaje |
|---|---|---|---|---|---|---|---|---|---|---|
| **Pixabay** (referencia) | **Sí y sí** (ver A) | Fotos: `orientation=vertical`. Video: filtro en el cliente | **Sí**: cuenta en [pixabay.com/accounts/register](https://pixabay.com/accounts/register/) y clave en [/api/docs](https://pixabay.com/api/docs/) | 0 USD | 100 req/60 s, caché de 24 h obligatoria | Comercial sí, sin atribución en la pieza, **descarga obligatoria**, edición sí | Silencio (solo veta minería ML) | Silencio | `lang=es` | **Sigue siendo el principal** |
| **Vecteezy API** | **Sí** (`content_type` = `photo`, `video`, …) | Fotos: `orientation=vertical`. **Video: sin filtro**; se deduce de `file_metadata.available_download_sizes` (**verificar**) | **Autoservicio**: «Start for Free» en [vecteezy.com/developers](https://www.vecteezy.com/developers). El *checkout* de pago por uso (`/checkout/v2-api-payg-unlimited`) está en el HTML. Pero el OpenAPI dice «to request access»: **no verificado si la clave gratis es instantánea** | **Free:** 500 descargas/mes, solo contenido gratuito. **Pago por uso:** **0,002 USD por llamada + 1,00 USD por descarga**. Business: ventas | Cuotas por llamadas y descargas (`X-QUOTA-*`). Tasa por segundo no publicada | Comercial sí. **Atribución obligatoria en Free**, no en pago. URL de descarga firmada 24 h: «use them immediately to download the file and keep a local copy». **Pero** la licencia dice «You may not download or stockpile Content… up to 30 days» | **Prohibido**: Terms, Prohibited Activities 21, «for any machine learning and/or artificial intelligence purposes» | **Bandera roja**: «Using Content within software applications which allow a third party to generate on-demand designs is also not permitted». Choca con su propia landing («Give your users access… directly in your app or website») | Sin parámetro `lang` documentado (**no verificado**) | **Alternativa n.º 1 con condiciones** (C) |
| **Magnific (ex-Freepik) API** | **Sí** (`/v1/resources`, `/v1/videos`) | **Sí, en el servidor**: `filters[aspect_ratio]=9:16` en video | **Autoservicio con plan de pago**: claves en [magnific.com/user/organization/api-keys](https://www.magnific.com/user/organization/api-keys), tras contratar en [magnific.com/pricing](https://www.magnific.com/pricing) | Premium **15 €/mes** o **10,50 €/mes anual**. Stock por API sin créditos, **tope de 100 descargas/día** (Premium, Premium+, Pro) | 50 hits/s por IP, 10 hits/s de media en 2 min, 30.000 RPM por clave | Comercial sí. Atribución salvo suscripción. Descarga «in a device the User owns or controls» | **Prohibido**: Terms (junio 2026), «for any machine learning and/or artificial intelligence purposes» | **Bandera roja**: un tercero solo si la producción «is not done by automatic means» y con «specific substantial human intervention». *API Services T&C*: **403 de nuevo** | `Accept-Language: es-ES` | **n.º 3**: técnicamente el mejor, legalmente el peor |
| **Coverr API** | **Solo video** (+ música). La landing dice «video, image, and audio search», pero la doc solo trae Videos, Collections, Categories, Audios y Video Scenes | **Campo `is_vertical`** y `aspect_ratio` en la respuesta. Sin filtro de búsqueda | **Contradictorio**: [coverr.co/developers](https://coverr.co/developers) dice «Create an account and access your API keys instantly», pero [api.coverr.co/docs/auth](https://api.coverr.co/docs/auth/) sigue con «contact us at team@coverr.co» | Demo: **50 llamadas/h**, gratis. Producción: **2.000/h**, «available only on paid plans» (Pro 24 USD o 10,8 USD/mes; Ultimate 119 o 42 USD) | 50 o 2.000 por hora | «All content accessed through the API is commercially licensed. **Videos require Coverr attribution**». Edición sí | **Solo prohíbe entrenar**: «must not be used to train AI algorithms, develop AI models… or as a dataset». **No dice nada de usarlo como entrada** (corrige §1 y §3.1-3 de este doc, que lo trataban como prohibición de IA en general) | **Bandera roja**: «can't be resold or offered as part of services… This applies to… video editing services». La landing de la API, en cambio, invita a «Embed the Coverr API… inside your product» | No documentado | **n.º 2 solo para video** |
| **Shutterstock** | Cuenta de prueba: fotos sí, **video 0** | Video sin 9:16 (`4_3`, `16_9`, `nonstandard`) | La de prueba sí ([/account/developers/apps](https://www.shutterstock.com/account/developers/apps)). La de video, solo por ventas | Prueba: 3M imágenes, 500 licencias/mes, 100 req/h | — | *Platform License* pensada para apps (por ventas) | API terms con **403** | Sí, con *Platform License* | `language=es` | Fuera (sin video por autoservicio) |
| **Storyblocks** | Sí (video, imágenes, audio) | `orientation` (valores no verificados) | Claves de **prueba** al crear cuenta. Producción **solo por ventas** **[2ª, la página oficial no carga]** | Por cotización | — | API para plataformas (`user_id`, `project_id`) | No verificado | Por contrato | No verificado | Ruta de pago, no de autoservicio |
| **Depositphotos** | Sí (la licencia define «File» incluyendo video) | — | Se pide la clave tras elegir plan y «may refuse a key for any reason» | Precio de revendedor | — | Es un **programa de revendedor** («Reseller API» / «Partner API») | No menciona | Pensado para revender, no para componer | — | Fuera |
| **Pond5** | — | — | No hay portal de desarrolladores: 403 DataDome y ninguna API pública encontrada **[2ª]** | — | — | — | — | — | — | Fuera |
| **123RF, Dreamstime** | — | — | No hay API pública con alta hoy. Solo plugins viejos de WordPress **[2ª]** | — | — | — | — | — | — | Fuera |
| **Envato / Mixkit** | — | — | [build.envato.com/api](https://build.envato.com/api/): «Envato Market has an API». Elements y Mixkit no tienen API | — | — | — | — | — | — | Fuera |
| **Canva Connect** | **No expone el banco de stock**: diseños, assets propios, exportación | — | — | — | — | — | — | — | — | Fuera |
| **Adobe Stock** | Sí | No verificado | «Beginning in November, 2024, the Stock API will only be available to Stock for Enterprise customers» | Contrato | — | — | — | — | — | Fuera |
| **Getty / iStock** | Sí (`/v3/search/videos/creative`) | No verificado | «Please contact your Getty Images account rep» | Contrato | — | URLs de descarga < 24 h | No verificado | Clave atada a la licencia del cliente | — | Fuera |
| **Wikimedia Commons** | Sí (MediaWiki API, sin clave) | `fileh:` y `filew:` en la búsqueda | Abierta | 0 | Etiqueta de *User-Agent* | **Licencia por archivo** (mucho CC BY-SA: atribución y *ShareAlike*). Material documental, no de stock | Según la CC | Sin garantía | **[LIVE]** `café filemime:video/webm` → 347 resultados, documentales | Fuera para anuncios |
| **Openverse** | **Sin video**: `/v1/videos/` da 404 **[LIVE]** | — | — | — | — | — | — | — | — | Fuera |
| **Life of Vids** | Sin API (sitio de descarga) | — | — | — | — | — | — | — | — | Fuera |

**Fuentes de la tabla** (todas leídas el 2026-10-16):
- **Pexels:** [pexels.com/api](https://www.pexels.com/api/).
- **Pixabay:** [api/docs](https://pixabay.com/api/docs/), [Terms](https://pixabay.com/service/terms/).
- **Vecteezy:**
  - [developers](https://www.vecteezy.com/developers?lang=en-US);
  - [OpenAPI v2](https://www.vecteezy.com/api-docs/api/v2/swagger.json): base `https://api.vecteezy.com` con *bearer*; `/v2/{account_id}/resources`; `orientation` «only applicable to photos and pngs»; `duration`, `ai_generated` y `license_type`; `dimensions`, `tags` y `ai_generated` en la respuesta «Only available for paid customers»; «Resizing is not supported for free API accounts»;
  - [License Agreement](https://www.vecteezy.com/licensing-agreement) («Last updated: June 22nd, 2026»);
  - [Terms](https://www.vecteezy.com/terms) («Last updated: October 6, 2025»).
- **Magnific:**
  - [quickstart](https://docs.magnific.com/quickstart), [pricing API](https://docs.magnific.com/pricing), [rate limits](https://docs.magnific.com/ratelimits);
  - [Videos API](https://docs.magnific.com/api-reference/videos/videos-api): remite a `terms-of-use#api-services`;
  - [planes](https://www.magnific.com/pricing);
  - [Terms of Use](https://www.magnific.com/legal/terms-of-use) («June 2026»).
- **Coverr:** [developers](https://coverr.co/developers), [pricing](https://coverr.co/pricing), [docs/auth](https://api.coverr.co/docs/auth/), [docs/videos](https://api.coverr.co/docs/videos/), [license](https://coverr.co/license).
- **Shutterstock:** [API pricing](https://www.shutterstock.com/api/pricing). Los [API terms](https://www.shutterstock.com/developers/api-terms) dieron 403.
- **Storyblocks:**
  - [storyblocks.com/api](https://www.storyblocks.com/api) devolvió vacío (202) al leerla directamente;
  - lo de las claves de prueba sale del extracto del buscador **[2ª]**.
- **Depositphotos:** [api-agreement](https://depositphotos.com/api-agreement.html).
- **Pond5:** [apis.io](https://apis.io/providers/pond5/) **[2ª]**.
- **Envato:** [build.envato.com/api](https://build.envato.com/api/).
- **Canva:** [Connect docs](https://www.canva.dev/docs/connect/).
- **Adobe:** [Stock API](https://developer.adobe.com/stock/docs/getting-started/).
- **Getty:** [developer docs](https://developer.gettyimages.com/docs/).
- **Wikimedia y Openverse:** llamadas **[LIVE]** sin clave.

### C. Lista corta (top 3) y recomendación

**Conclusión de partida.** Hoy **no existe un sustituto limpio de Pexels**: ninguno da a la vez fotos y video, clave por autoservicio, filtro vertical y licencia sin prohibición de IA ni de apps. **El que más se acerca sigue siendo Pixabay, que sí tiene video** (A). Las alternativas de abajo **añaden catálogo**, no resuelven la licencia.

Un dato del código cambia el ranking. Según el [plan](plan-integracion-stock-pexels-pixabay.md) §1.3, **todo video de stock del Clip va a Seedance**, y en producción **todo fondo del Flyer y de la Galería va a Seedream**. Por eso un proveedor que prohíbe la IA **no sirve para el Clip**: solo sirve para la ruta sin IA (compositor local `_flyer` y fondo literal del avatar con HeyGen).

1. **Vecteezy API: la alternativa recomendada para fotos y video, con condiciones.**
   - **A favor:**
     - es el único con fotos y video, plan gratis (500 descargas/mes) y pago por uso sin suscripción: 1 USD por descarga, 0,002 USD por llamada;
     - su producto API está pensado para meterlo en una app;
     - tiene filtro `ai_generated`.
   - **Condiciones:**
     - (a) **nunca a Seedream ni Seedance**: sus Terms prohíben «any machine learning and/or artificial intelligence purposes»;
     - (b) **confirmación escrita antes de producción** de que el contrato API anula, para nosotros, la cláusula «on-demand designs» y el tope de 30 días;
     - (c) en Free hay que mostrar la atribución, y no da dimensiones, tags ni el campo `ai_generated`. Para uso real hace falta el pago por uso.
   - **Alta:** [vecteezy.com/developers](https://www.vecteezy.com/developers), botón «Start for Free».
2. **Coverr API: complemento solo de video vertical, y la única novedad que puede alimentar a Seedance.**
   - **A favor:**
     - su licencia solo prohíbe *entrenar* y *usar como dataset*; sobre usarlo como entrada calla, igual que Pixabay (zona gris, no prohibición);
     - marca `is_vertical` en cada clip;
     - es barato: Demo gratis a 50 llamadas/h; producción con Pro, 10,8 a 24 USD/mes.
   - **Banderas rojas:**
     - la licencia excluye ofrecerlo dentro de «video editing services»;
     - el video exige atribución;
     - la propia documentación se contradice sobre cómo se obtiene la clave.
   - **Alta:** [coverr.co/developers](https://coverr.co/developers), botón «Get API Key». Si no da la clave al instante: `team@coverr.co`.
3. **Magnific API: técnicamente la mejor, legalmente la peor.**
   - **A favor:** 9:16 en el servidor, filtro de personas y de IA, y `es-ES`.
   - **En contra:**
     - prohíbe la IA;
     - prohíbe que un tercero use el contenido salvo «not done by automatic means» con intervención humana sustancial;
     - el tope es de 100 descargas/día con Premium (15 €/mes).
   - **Solo tendría sentido** con contrato Business/Enterprise y sus *API Services T&C*, que hoy dan 403.
   - **Alta:** [magnific.com/pricing](https://www.magnific.com/pricing), y después [magnific.com/user/organization/api-keys](https://www.magnific.com/user/organization/api-keys).

**Descartados hoy por no tener autoservicio:**
- **Storyblocks:** el que mejor encaja por contrato con video para plataformas, pero producción solo por ventas.
- **Shutterstock:** su video va solo por ventas.
- **Adobe, Getty, Depositphotos y Pond5:** contrato, revendedor o sin portal.

### D. Banderas rojas legales (nuevas o corregidas)

1. **Vecteezy:**
   - «on-demand designs» prohíbe exactamente el modelo de Qualify;
   - «stockpile… up to 30 days» choca con guardar la copia en R2 como fuente de verdad;
   - prohibición expresa de IA.
   
   Las tres están en la licencia general. No encontramos términos propios de la API. **Precio claro, apto para citar:** 1,00 USD por descarga y 0,002 USD por llamada (pago por uso).
2. **Coverr:**
   - **corrección a este documento**: no prohíbe la IA como entrada, solo el entrenamiento y el uso como dataset;
   - sí excluye «video editing services» y exige atribución del video servido por API.
3. **Magnific:** sin cambios desde la investigación inicial (Terms de junio 2026). Las *API Services T&C* siguen dando 403.
4. **Concentración:** Pixabay y Pexels siguen siendo de Canva. Las páginas legales de Vecteezy y Coverr no nombran a Canva, así que **sí diversificarían** el riesgo de que cambien los términos.

---

## 1. Resumen

- **Recomendación: Pexels como principal (imágenes y video) y Pixabay como complemento y respaldo.** Son los dos únicos proveedores de la lista que reúnen las cinco cosas:
  - API gratuita con clave;
  - filtro vertical nativo (Pexels lo tiene en fotos **y en videos**);
  - búsqueda en español;
  - licencia que permite anuncios sin atribución y modificar el archivo;
  - ninguna regla contra guardar el archivo en R2. Pixabay, de hecho, **obliga** a descargarlo a tu servidor.
- **Las dos son de Canva** (Canva Germany GmbH) y comparten casi palabra por palabra los mismos Terms (Pexels 2024-11-15, Pixabay 2024-11-18). Tener las dos amplía el catálogo, pero **no diversifica el riesgo legal**: si Canva cambia los términos, cambian ambas.
- **Usar el stock como entrada de IA (Seedream/Seedance) es zona gris en Pexels y Pixabay, y está prohibido en otros tres.**
  - Pexels y Pixabay no lo prohíben. Lo único que vetan es el scraping y la minería de datos «for machine learning purposes».
  - **Unsplash** (API Terms §12), **Freepik/Magnific** (Terms §8.1) y **Coverr** (licencia) prohíben de forma expresa usar su contenido para fines de IA o machine learning. Quedan fuera de la ruta que alimenta modelos.
- **El mayor riesgo legal no es la IA; son las personas.** Pexels y Pixabay prohíben sugerir que una persona o marca de la foto **respalda** tu producto, y no entregan *model releases*. Poner un producto de la marca junto a una persona de stock en un anuncio cae justo en esa zona. Mitigación en §5.
- **La ruta de pago queda para después.** Sirve para cuando un cliente necesite personas con *release* e indemnización: **Shutterstock** (su *Platform License* está pensada para apps donde el usuario final crea contenido) o **Storyblocks** (enfocado en video). Las dos venden por contrato y sin precio público. Getty/iStock y Adobe Stock solo funcionan con contrato enterprise.
- **Descartados:**
  - Openverse: licencias CC con atribución, sin video y sin garantía sobre la licencia.
  - Mixkit: no tiene API.
  - Videvo: absorbido por Freepik.
  - Envato: su API solo cubre Market.
  - Tenor: API cerrada desde el 2026-06-30.
  - GIPHY: no sirve para anuncios y prohíbe guardar copias.

---

## 2. Comparativa — acceso técnico y precio

| Proveedor | Imágenes | Video | Vertical 9:16 | Auth | Gratis / límites | Pago (USD) | Español | Formatos / tamaños |
|---|---|---|---|---|---|---|---|---|
| **Pexels** | Sí | Sí | **Sí, nativo**: `orientation=portrait` en fotos y videos | API key en header `Authorization` | **200 req/h y 20.000 req/mes**. Gratis e «ilimitado» si cumples los términos (se pide por formulario) | Gratis | `locale=es-ES` (28 locales) | Fotos: `original`, `large2x`, `portrait` 800×1200, etc. Videos: `video_files` con `width`/`height`/`fps`/`quality` (hd/sd/hls)/`link` |
| **Pixabay** | Sí (foto, ilustración, vector) | Sí | Imágenes: `orientation=vertical`. **Videos: sin filtro de orientación**; hay que filtrar por `width`/`height` en la respuesta | API key en query `key` | **100 req/60 s** por clave. Caché de 24 h obligatoria. `totalHits` con tope de 500 por consulta | Gratis. Original y 1920 px solo con «full API access» aprobado | `lang=es` | Imagen: 640 px (URL válida 24 h), 1280 px, 1920 px y original con aprobación. Video: `large` ~4K, `medium` ~1080p, `small`, `tiny` |
| **Unsplash** | Sí | **No** | Solo fotos: `orientation=portrait` | Access Key (`Client-ID`); OAuth para acciones de usuario | Demo 50 req/h; producción 1.000 req/h (tras aprobación) | Gratis | `lang` en beta, **hay que pedirlo por email** | `raw`/`full`/`regular` 1080/`small`/`thumb` + parámetros imgix |
| **Openverse** | Sí (CC, ~800M imágenes+audio) | **No** | `aspect_ratio=tall` | Anónimo u OAuth2 *client credentials* | **[LIVE]** anónimo funciona; tasas exactas no publicadas en la doc | Gratis (se reserva cobrar el uso comercial) | La consulta `café` devolvió resultados de Flickr | URL del origen (Flickr, etc.) |
| **Freepik → Magnific** | Sí (foto, vector, PSD, IA) | Sí (incluye el catálogo ex-Videvo) | **Sí**: `filters[aspect_ratio]=9:16`, `orientation=vertical` | Header `x-magnific-api-key` | 50 hits/s por IP, 30.000 req/min por clave | Premium €10,50/mes anual (hay más planes). Por API: **100 descargas de stock/día sin créditos** en Premium/Premium+/Pro; Business/Enterprise sin tope, con créditos. Coste por descarga **no verificado** | `Accept-Language: es-ES` | Descarga con `image_size` 100–2000 px u original. Video con `options` (4K, mp4…) |
| **Shutterstock** | Sí | Sí (no en la cuenta gratuita) | Video: `aspect_ratio` solo `4_3`, `16_9`, `nonstandard`. **No hay valor 9:16** | OAuth 2.0 (Basic para algunos endpoints) | Cuenta de prueba gratis: 3M imágenes de la colección libre, **0 video**, 100 req/h, hasta 500 licencias/mes «small-scale» | *Unlimited* y *Pay Per Use*: **solo por ventas** | `language=es` | Varias resoluciones; reverse/similar search |
| **Getty / iStock** | Sí | Sí | No verificado | `api-key` + OAuth2 | **No hay autoservicio**: la clave la da tu representante de cuenta | Por contrato | No verificado | URLs de descarga válidas < 24 h |
| **Adobe Stock** | Sí | Sí | No verificado | Server-to-server (Enterprise) | **Desde nov 2024, solo clientes Stock for Enterprise** | Por contrato | Locales (no verificado `es_ES`) | — |
| **Storyblocks** | Sí | **Sí, su fuerte** | Parámetro `orientation` en la búsqueda de video (valores no verificados) | HMAC (clave pública y privada, `EXPIRES`) | Claves de prueba gratis, «solo uso interno» | **Solo por ventas** | No verificado | Exige `user_id` y `project_id` en cada búsqueda y descarga |
| **Coverr** | No | Sí | Categoría *Vertical* en la web | API key (`/docs/auth/`) | API gratis «as long as you don't charge for it yourself» | Coverr+ (precio no verificado) | No verificado | — |
| **Mixkit** (Envato) | — | Sí (web) | Sí en la web | **No tiene API** | — | — | — | — |
| **Videvo** | — | — | — | **Redirige a freepik.com/videos** (absorbido) | — | — | — | — |
| **Envato** | — | — | — | La API pública solo cubre **Envato Market** (compras y ventas), no Elements | — | — | — | — |
| **GIPHY** | GIF/stickers | Clips | — | API key (beta y producción) | Beta 100 req/h; producción con revisión | «Pricing discussion» | — | mp4, webp |
| **Tenor** | — | — | — | **API cerrada el 2026-06-30** | — | — | — | — |

Fuentes de la tabla (todas consultadas el 2026-10-16):
- Pexels:
  - [API docs](https://www.pexels.com/api/documentation/)
- Pixabay:
  - [API docs](https://pixabay.com/api/docs/)
  - [about](https://pixabay.com/service/about/): 6,3M+ assets, Canva Germany GmbH
- Unsplash:
  - [documentación](https://unsplash.com/documentation)
- Openverse:
  - [auth y throttling](https://docs.openverse.org/api/reference/authentication_and_throttling.html)
  - [ToS](https://docs.openverse.org/terms_of_service.html)
  - [LIVE] `GET https://api.openverse.org/v1/images/?q=café&license_type=commercial,modification&aspect_ratio=tall` → `result_count: 240`, primeros resultados de Flickr con CC BY-SA 2.0
- Freepik/Magnific:
  - [docs](https://docs.magnific.com/introduction): `docs.freepik.com` redirige con 301
  - [pricing API](https://docs.magnific.com/pricing)
  - [rate limits](https://docs.magnific.com/ratelimits)
  - [OpenAPI](https://storage.googleapis.com/fc-freepik-pro-rev1-eu-api-specs/magnific-api-v1-openapi.yaml): `/v1/resources`, `/v1/videos` y sus `filters`
  - [planes](https://www.magnific.com/pricing)
- Shutterstock:
  - [API pricing](https://www.shutterstock.com/api/pricing)
  - [API reference](https://api-reference.shutterstock.com/)
- Getty:
  - [developer docs](https://developer.gettyimages.com/docs/)
- Adobe:
  - [Stock API getting started](https://developer.adobe.com/stock/docs/getting-started/)
- Storyblocks:
  - [API reference](https://documentation.storyblocks.com/): colección Postman pública
- Coverr:
  - [API docs](https://api.coverr.co/docs/)
  - [página developer](https://coverr.co/stock-video-footage/developer)
- Envato:
  - [Envato API](https://build.envato.com/api/)
- GIPHY:
  - [API docs](https://developers.giphy.com/docs/api/)
- Tenor:
  - [9to5Google](https://9to5google.com/2026/06/30/google-tenor-api-gif-updates/) [2ª]
  - [Shacknews](https://www.shacknews.com/article/149852/google-tenor-api-service-discontinued-twitter-discord-whatsapp-bluesky) [2ª]

> **Precio claro, apto para citar:** Pexels y Pixabay son **0 USD** por petición y por descarga. Freepik/Magnific Premium cuesta **€10,50/mes facturado anualmente** e incluye «API access with credit-based usage». Sus descargas de stock por API **no gastan créditos hasta 100/día** en Premium, Premium+ y Pro. Shutterstock, Getty, Adobe y Storyblocks **no publican precio**: se negocia con ventas.

---

## 3. Comparativa — licencia frente al uso de Qualify

| Proveedor | Comercial en anuncios / redes | Atribución | Hotlink | Guardar en R2 y editar | IA como entrada o entrenamiento | Personas / marcas | SaaS multi-tenant con nuestra clave |
|---|---|---|---|---|---|---|---|
| **Pexels** | **Sí.** La licencia nombra «ads, banners, marketing campaigns» | No en la pieza. **Sí en la app**: «prominent link to Pexels» al buscar | No exigido | **Sí** (descargar y modificar). Ojo con el «Standalone» (ver abajo) | **Silencio** sobre usarlo como entrada. Solo prohíbe scraping y minería «for machine learning purposes» (§8). Pexels no garantiza que el contenido sea humano | Prohibido mostrar a personas reconocibles de forma ofensiva o **implicar respaldo**. Logos: nada de uso comercial sobre bienes. **Sin model releases** | No lo prohíbe de forma expresa. Prohíbe «replicate a similar or competing service» y la copia sistemática |
| **Pixabay** | **Sí** («Use Content for free», modificable) | No en la pieza. **Sí en la app**: mostrar de dónde viene al listar resultados | **Prohibido el hotlink permanente** de imágenes: hay que descargarlas | **Sí, y es obligatorio** descargar a tu servidor | Igual que Pexels: §8 veta la minería «for machine learning purposes». Sobre usarlo como entrada no dice nada | Igual que Pexels: prohíbe el uso engañoso y sugerir respaldo o afiliación. Vetado el uso político y el de salud o medicación | Igual que Pexels. Además, la API es «for real human requests»: nada de descargas masivas ni consultas automáticas en volumen |
| **Unsplash** | Sí | **Obligatoria en la app**: fotógrafo + Unsplash + enlace | **Obligatorio** usar las URLs de la API «for all uses» + llamar a `download_location` | **En conflicto** con el hotlink obligatorio | **Prohibido**: API Terms §12, «in connection with any machine learning and/or artificial intelligence purposes»; Terms §8 lo mismo | — | Sublicenciar solo con consentimiento escrito (API Terms §8) |
| **Openverse** | Depende de cada licencia CC. Hay que filtrar `license_type=commercial,modification` | **Obligatoria** (CC BY), a veces **ShareAlike** | URL del origen | Según la CC | Según la CC (CC no veta la IA) | Ni Openverse ni CC dan releases. **Sin garantía de licencia** | La ToS se reserva cobrar el uso comercial |
| **Freepik → Magnific** | Sí, con restricciones | **Obligatoria salvo suscripción** Premium, Premium+ o Pro | — | Descarga permitida «in a device the User owns or controls» | **Prohibido**: §8.1, «for any machine learning and/or artificial intelligence purposes» | Contenido editorial o con logos o personas de fondo: **solo uso editorial** | **Muy restrictivo**: un tercero solo puede usarlo si la producción «is not done by automatic means», con «substantial human intervention» y **el User (no el tercero) elige** el item. Sin sublicencia |
| **Shutterstock** | Sí, con la licencia contratada | No verificado | — | Platform License: el usuario final no puede descargar el archivo crudo, solo usarlo en proyectos hechos en la app | **No verificado** (licencia con 403) | Imágenes con *release* (estándar del sector, no verificado aquí) | **Sí, es el caso de uso de la *Platform License***: «end users [may] use assets commercially in content made within your app». Hay que imponer restricciones en tu EULA |
| **Getty / iStock** | Por contrato | Por contrato | URLs de descarga caducan < 24 h | Por contrato | No verificado | Releases (no verificado) | Clave atada al acuerdo de licencia **del cliente** |
| **Storyblocks** | Licencia amplia (web, TV, streaming) [DOC, página comercial] | No verificado | — | Por contrato | No verificado | Filtros `has_talent_released`/`has_property_released` | API pensada para plataformas (`user_id`/`project_id`). El EULA individual de 2024 cubre solo al suscriptor [2ª] |
| **Coverr** | Sí (licencia web) | No en la pieza. **Logo clicable obligatorio en la app** | — | Sí | **Prohibido** entrenar IA o usarlo como dataset | Coverr obtiene releases pero **no los entrega** | **No**: la API es gratis solo si no cobras, y la FAQ excluye ofrecerlo dentro de «website builders, or video editing services» |
| **GIPHY** | **No** (contenido de terceros, sin licencia comercial; inferencia, API Terms con 403) | «Powered By GIPHY» | **Obligatorio**: «should not be cached, proxied, rewritten, or stored» | **No** sin aprobación escrita | — | — | — |

Fuentes:
- Pexels:
  - [licencia](https://www.pexels.com/license/)
  - [Terms](https://www.pexels.com/terms-of-service/): «Last updated: November 15th, 2024»; «Pexels, a Canva Germany GmbH brand»
- Pixabay:
  - [License summary](https://pixabay.com/service/license-summary/)
  - [Terms](https://pixabay.com/service/terms/): «Last updated: November 18, 2024»
  - [API docs](https://pixabay.com/api/docs/)
- Unsplash:
  - [licencia](https://unsplash.com/license)
  - [API Terms](https://unsplash.com/api-terms)
  - [Terms](https://unsplash.com/terms)
  - [API Guidelines](https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines)
- Freepik/Magnific:
  - [Terms of Use](https://www.magnific.com/legal/terms-of-use): versión «June 2026»; operador Magnific AI, S.L.U., Málaga; `freepik.com/legal/terms-of-use` redirige ahí
  - Las [API Services T&C](https://www.magnific.com/legal/api-services) devolvieron **403**: **no verificadas**
- Coverr:
  - [licencia](https://coverr.co/license)
  - [API docs](https://api.coverr.co/docs/)
- Shutterstock:
  - [API pricing](https://www.shutterstock.com/api/pricing): Platform License
  - La licencia general (`/license`) dio **403**
- GIPHY:
  - [API docs](https://developers.giphy.com/docs/api/)

### 3.1 Tres cláusulas que cambian el diseño (citas literales)

1. **«Standalone» (Pexels y Pixabay, Terms §5).** No se puede «sell or distribute the Content … on a Standalone basis». La definición incluye esto: *«using the Content in its original form or solely using a filter, changing colors, resizing or cropping the Content remains Standalone use»*. En cambio: *«using the Content with a combination of images, videos, audio files, other media, text, illustrations, background features and editing techniques is not Standalone use, so long as the combined effect is to make a "new" creative work.»* → **Una pieza de Qualify siempre debe combinar el stock con algo más:** texto, logo, producto o música. Publicar el clip de stock tal cual, solo recortado a 9:16, es la zona de riesgo. ([Pexels Terms](https://www.pexels.com/terms-of-service/))
2. **Respaldo o endoso (Pexels y Pixabay).** La licencia de Pexels prohíbe *«implying that people or brands shown in the imagery endorse your product»*. Los Terms prohíben *«suggesting that any depicted person, brand, organisation or other third party endorses or is affiliated with you»*. → Componer el producto del cliente junto a una persona de stock es exactamente el caso dudoso. ([Pexels license](https://www.pexels.com/license/), [Pixabay Terms](https://pixabay.com/service/terms/))
3. **IA (Unsplash, Magnific, Coverr — prohibición expresa).**
   - Unsplash API Terms §12 prohíbe usar el contenido de la API *«in connection with any machine learning and/or artificial intelligence purposes»* y remite a unsplash.com/data. Sus Terms §8 añaden *«(e.g., training any machine learning and/or artificial intelligence models)»*.
   - Magnific §8.1 exige que el usuario *«Does not use the Magnific Content … for any machine learning and/or artificial intelligence purposes»*.
   - **Inferencia nuestra:** «any … artificial intelligence purposes» es lo bastante amplio para cubrir pasar la imagen a Seedream o Seedance como referencia. No es solo entrenamiento.

---

## 4. Notas por proveedor

### Pexels — principal
- **Por qué:**
  - es el único gratuito con `orientation=portrait` **en video** (el formato central de Reels y TikTok);
  - acepta `size` (`large` 4K / `medium` Full HD / `small` HD) y `locale=es-ES`;
  - en fotos acepta `color` (incluido hex), útil para casar con la paleta del Brand Kit;
  - cada `video_files` trae `width`/`height`/`fps`, así que se elige la rendición 1080×1920 sin descargar nada.
- **Límites:**
  - 200 req/h y 20.000/mes por defecto. Sobra para el operador.
  - Para el generador automático (varias búsquedas por pieza y tenant), pedir el aumento «unlimited». Pexels lo concede gratis a quien cumple la atribución y lo pide **con una demo de la integración**.
  - Las respuestas 429 no traen los headers `X-Ratelimit-*`.
- **Obligaciones en la UI:**
  - enlace visible a Pexels en el selector;
  - crédito al autor «when possible».
  - En la pieza publicada no hace falta atribución.
- **Gotchas:**
  - los filtros `min_duration`/`max_duration` existen **solo en `/videos/popular`**, no en `/videos/search`. La duración se filtra en el cliente con el campo `duration`;
  - no hay filtro «sin personas»;
  - **SDK:** REST plano con `httpx`. No encontramos SDK oficial en Python (**no verificado**).

### Pixabay — complemento y respaldo
- **Por qué:**
  - suma otro catálogo (6,3M+ assets, también de Canva) con ilustraciones y vectores (`image_type`);
  - tiene filtros `colors` (incluido `transparent`, útil para recortes), `category` y `editors_choice`;
  - acepta `lang=es`.
  - Su regla de **descargar al servidor** encaja exactamente con R2.
- **Gotchas:**
  - (a) **el video no tiene filtro de orientación**: hay que filtrar por `width < height` en las renditions. Como `totalHits` tiene tope de 500 por consulta, los resultados verticales salen pocos;
  - (b) **caché de 24 h obligatoria**: repetir una búsqueda idéntica no puede volver a la API;
  - (c) la URL de 640 px caduca en 24 h. 1920 px y el original requieren pedir «full API access»;
  - (d) **«real human requests»** y nada de «lots of automated queries»: el generador que busca solo tiene que ir cacheado y con tope;
  - (e) la API no expone un filtro de contenido generado por IA (no verificado si lo marca en la respuesta).

### Unsplash — descartado para Qualify
Tiene buena calidad fotográfica, pero choca con dos de nuestros usos:
- **hotlink obligatorio para todo uso**, que impide la copia en R2 como fuente de verdad;
- **prohibición expresa de usos de IA**, que impide pasarlo a Seedream.

Además, no tiene video y el español está en beta por solicitud.

### Freepik → Magnific — técnicamente el mejor, legalmente el peor encaje
- **Lo técnico:**
  - es el que tiene mejores filtros: video con `aspect_ratio` 9:16, `duration`, `resolution`, `fps` y `ai-generated` (para excluir contenido de IA); imágenes con `people` y `ai-generated`;
  - acepta `Accept-Language: es-ES`;
  - cuesta €10,50/mes con 100 descargas por día.
- **Hallazgo:** Freepik pasó a llamarse **Magnific** (Magnific AI, S.L.U., Málaga). Sus docs, términos y `videvo.net` redirigen a Magnific o Freepik, y las previews de video de la API salen de `cdnpk.net/videvo_files/…`. Videvo ya **no es un proveedor independiente**.
- **Por qué no:** la licencia (§8.1) hace tres cosas:
  - prohíbe los fines de IA;
  - prohíbe que un tercero use el contenido salvo si la producción es a mano, con intervención humana sustancial y con el *User* eligiendo el item. En Qualify el «tercero» es cada tenant, y el generador elige solo;
  - exige atribución salvo suscripción Premium.
- Las *API Services T&C* dieron 403: **no verificadas**. Podrían relajar algo de esto, pero no lo sabemos.

### Shutterstock — ruta de pago para SaaS (imágenes)
- **A favor:** la *Platform License* describe literalmente nuestro modelo: el usuario final usa el asset comercialmente dentro de lo que crea en la app, sin descargar el archivo crudo.
- **En contra:**
  - (a) la cuenta gratuita no tiene video y solo da la colección libre («small-scale projects»);
  - (b) los planes *Unlimited* y *Pay Per Use* solo se contratan por ventas;
  - (c) el filtro de video `aspect_ratio` no ofrece 9:16 (`4_3`, `16_9`, `nonstandard`);
  - (d) sus términos sobre IA **no verificados** (403).

### Storyblocks — ruta de pago para SaaS (video)
- **A favor:**
  - API pensada para plataformas: pide `user_id`/`project_id` por petición y reparte regalías por descarga;
  - filtros de video `orientation`, `min_duration`/`max_duration`, `quality`, `has_talent_released` (personas con release) e `is_editorial`;
  - tope de 10k resultados por búsqueda.
- **En contra:** claves de prueba gratis «solo uso interno» y precio por cotización.
- El EULA individual de 2024 solo cubre al suscriptor ([2ª, infogram](https://infogram.com/Storyblocks-EULA-2024.pdf)). Para multi-tenant hay que pedir el *API agreement*.

### Getty / iStock y Adobe Stock — fuera de alcance hoy
- **Getty:** la clave sale de un representante de cuenta y va atada al acuerdo de licencia del cliente. Las URLs de descarga caducan en menos de 24 h.
- **Adobe:** desde noviembre de 2024 la Stock API es solo para clientes «Stock for Enterprise».
- Las dos tienen sentido solo si un cliente grande trae su propio contrato (BYO-licencia), no como fuente por defecto.

### Coverr, Mixkit, Videvo, Envato, Openverse, GIPHY, Tenor
- **Coverr:** buen catálogo vertical y etiqueta los clips de IA, pero su API gratis excluye a quien cobra («don't charge for it yourself»). Su FAQ excluye integrarlo en «video editing services», y su licencia veta entrenar IA.
- **Mixkit** (de Envato): no tiene API.
- **Envato:** la API pública cubre solo Envato Market.
- **Openverse:** agrega licencias CC sin garantía (*«does not … make any representations or warranties about licensing status»*). Exige atribución, a veces ShareAlike, y no tiene video. No es apto para anuncios de marca.
- **GIPHY:** contenido sin licencia comercial y sin poder guardarlo.
- **Tenor:** API cerrada (sin altas desde el 2026-01-13, apagado el 2026-06-30, [2ª]).
- **Depositphotos:** su «API Program» es un acuerdo de **revendedor** ([depositphotos.com/api-agreement.html](https://depositphotos.com/api-agreement.html), [2ª]). No es una API para apps de producción.

---

## 5. Recomendación

**Principal: Pexels** (imágenes y video). **Complemento y respaldo: Pixabay** (más fotos e ilustraciones; video vertical solo filtrado en el cliente). Detrás de una interfaz `StockProvider` común, igual que el `Provider` de `qualify_models`, para cambiar o sumar proveedores sin reescribir.

**El razonamiento, punto por punto:**
- **Comercial y social sin atribución:** los dos lo permiten de forma expresa (Pexels nombra anuncios y campañas).
- **Vertical:** Pexels lo resuelve en el servidor para fotos y videos. Pixabay solo para fotos.
- **R2:** ninguno exige hotlink. Pixabay obliga a descargar. Guardamos la copia y servimos desde R2.
- **Composición** (producto sobre fondo, texto encima): es justo lo que la cláusula «Standalone» considera obra nueva.
- **IA:** es el único par de la lista sin prohibición expresa. Sigue siendo **gris, no blanco** (§6).
- **Coste:** 0 USD. El límite real es la tasa (Pexels 200/h hasta que pidamos «unlimited»; Pixabay 100/min con caché de 24 h).

**Ruta de pago, cuando un cliente lo pida:**
- Storyblocks para video y Shutterstock para imágenes, ambos por contrato.
- Las dos se negocian una vez para todos los tenants y traen *releases* de personas y una licencia de plataforma.
- No contratar antes de tener un cliente que lo exija: no hay precio público y hay que pasar por ventas.

**Lo que conviene construir con esto:**
1. **Procedencia por asset** (regla dura del proyecto). Guardar:
   - `provider`, `provider_asset_id`, `author` y `author_url`;
   - `source_page_url`, `license_name` y `license_snapshot_date` (fecha de los Terms vigentes);
   - `query`, `retrieved_at` y `r2_key`;
   - `tenant_id` y en qué pieza se usó.
   
   Si un proveedor cambia la licencia o retira un asset, sabremos qué piezas lo usan.
2. **Atribución en el selector**, no en la pieza: «Fotos y videos de Pexels / Pixabay» con enlace, y el autor en cada miniatura.
3. **El generador no usa nunca el stock «solo»**: siempre lo combina con texto, logo o producto (cláusula Standalone).
4. **Caché de búsquedas de 24 h** por `(provider, query, filtros)` y tope de búsquedas automáticas por pieza. Es obligatorio para Pixabay y prudente para la tasa de Pexels.
5. **Pedir ampliación de límites por escrito a Pexels (y a Pixabay)** describiendo el caso real: un SaaS multi-tenant que compone piezas de marca y puede pasar fondos a modelos generativos. La respuesta escrita es también la mejor defensa ante la zona gris de IA y multi-tenant.

---

## 6. Riesgos legales para el fundador

1. **Personas reconocibles y respaldo (el más alto).**
   - Pexels y Pixabay no dan *model release* y prohíben implicar que la persona o marca de la imagen respalda el producto.
   - Un anuncio con el producto del cliente junto a una persona de stock puede violar la licencia y, además, los derechos de imagen de esa persona, que Pexels y Pixabay dejan explícitamente a cargo del usuario.
   - **Mitigación:** por defecto, usar stock de escenas, fondos, texturas y producto sin personas; avisar en la UI cuando el asset tenga personas (la detección con el VLM que ya usamos es **inferencia**, no está construida); y para anuncios con personas, la ruta de pago con *releases*.
2. **Stock como entrada de IA.**
   - Pexels y Pixabay no lo prohíben, pero tampoco lo autorizan: sus Terms solo vetan el scraping y la minería para ML.
   - Unsplash, Magnific y Coverr sí lo prohíben: **nunca deben entrar en la ruta Seedream/Seedance**.
   - Aparte de la licencia, Seedance **rechaza** referencias con caras humanas reales (`PrivacyInformation`, ver [avatar-reutilizable-voz-y-movimiento-bytedance.md](avatar-reutilizable-voz-y-movimiento-bytedance.md)). Así que un clip de stock con personas tampoco pasaría técnicamente como `reference_video`.
3. **Multi-tenant con una sola clave.**
   - Ningún Terms gratuito habla de SaaS. Todos prohíben «replicate a similar or competing service» y la copia sistemática.
   - Un selector dentro de un editor de contenido no es un banco de stock, pero **esto es una lectura nuestra, no una autorización**.
   - Magnific y Coverr, en cambio, lo restringen de forma explícita.
4. **Sin garantía ni indemnización.**
   - Los gratuitos no indemnizan.
   - Pexels dice que no garantiza que el contenido sea humano ni la exactitud de la información.
   - Si un asset subido por un contribuidor infringe derechos de un tercero, el riesgo recae en el usuario: en la práctica, el tenant y Qualify.
5. **Marcas y logos en la imagen.** Prohibido usar comercialmente un contenido con marcas visibles «in relation to goods and services». Hay que evitar fondos con logos ajenos.
6. **Usos sensibles (Pixabay).** Vetados el contexto político, el de salud o medicación y el de contenido adulto. Es relevante si algún tenant es una marca regulada (ver [oferta-mercado-marca-regulada.md](oferta-mercado-marca-regulada.md)).
7. **Concentración.** Pexels y Pixabay son del mismo dueño (Canva) y tienen Terms casi idénticos. Un cambio de política afecta a las dos a la vez. La interfaz `StockProvider` y la procedencia por asset son la cobertura.

## 7. Qué quedó sin verificar

- Las *API Services Terms* de Magnific (403) y el coste en créditos por descarga de stock en los planes Business y Enterprise.
- Los términos de IA de Shutterstock (licencia con 403) y sus precios *Unlimited* / *Pay Per Use*.
- Precios, valores del filtro `orientation` y licencia de plataforma de Storyblocks. La página comercial devolvió el contenido vacío.
- Getty/iStock y Adobe: filtros de vertical y precios (solo por contrato).
- Las tasas exactas de Openverse (no publicadas en la doc).
- Los API Terms de GIPHY (403).
- Si existe un SDK oficial en Python para Pexels o Pixabay.
- Cuánto video vertical real hay en Pixabay: sin clave no se pudo medir y no la pedimos, por instrucción.
