# Investigación: Higgsfield como proveedor de transiciones de vídeo

> Estado: COMPLETO (2026-10-09). Investigación web; ningún cambio de código.
> Leyenda de evidencia: **[P]** = verificado en fuente primaria (docs/pricing/ToS de Higgsfield
> o del proveedor) · **[S]** = fuente secundaria (blog, reseña, agregador) · **[I]** = inferencia
> propia.

## 0. Contexto en Qualify (leído del repo, no de docs)

- El seam es `GenerationProvider` (`packages/creative/src/qualify_creative/providers.py`):
  `name`, `supports: frozenset[GenerationTask]`, `generate(request, *, api_key)` síncrono
  (el adapter hace polling dentro) y `estimate_cost_usd(request, pricing)`.
- `GenerationTask` hoy: `COPY`, `PRODUCT_IMAGE`, `RESTYLE_*`, `AVATAR_VIDEO`, `SCENE_VIDEO`
  (Seedance), `TEMPLATE_RENDER` (Remotion). No existe una tarea de transición.
- `SeedanceVideoAdapter` (`adapters/byteplus_ark.py`) sólo envía `role: "first_frame"`;
  ya pide `return_last_frame=True` (útil para encadenar planos).
- `packages/render` (Remotion 4.0.532) no depende todavía de `@remotion/transitions`.

## 1. Qué es Higgsfield

Higgsfield tiene **dos superficies distintas** y conviene no mezclarlas:

1. **App web de consumo (`higgsfield.ai`)** — suscripción con créditos, "apps" y presets de
   cámara/VFX. Aquí vive el producto **"Smooth Transitions"** (`higgsfield.ai/apps/transitions`):
   - Entradas: "Clip 1" y "Clip 2", que pueden ser dos clips, dos fotos o una mezcla. **[P]**
   - Cada vídeo de entrada se limita a 5 s; la transición añade 5 s; salida máx. 15 s. **[P]**
   - El aspect ratio de la salida se fija al del primer clip. **[P]**
   - Modelo subyacente no declarado; los ejemplos están rotulados "Created with Kling
     Transition". **[P, pero ambiguo]**
   - Latencia declarada: 30 s – 2 min. **[P, marketing en la propia página]**
   - Los derechos de **uso comercial** se desbloquean con planes de pago. **[P]**
   - **No se menciona ninguna API** para esta app. **[P]**
   - Flujo "Start/End Frames" sobre Kling (fotograma inicial + final; morphs, swaps de
     producto, loops 360° usando la misma imagen como inicio y fin); en el flujo web sólo
     funciona con el preset "General" y recomiendan 5 s para transiciones. **[P, blog propio]**
2. **API de desarrolladores ("Higgsfield Cloud" / `open.higgsfield.ai`, docs en
   `docs.higgsfield.ai`)** — catálogo de modelos de pago por uso. El índice de modelos
   menciona 67 entradas de vídeo y 17 de imagen. **[P]**

**Modelos: casi todos revendidos.** El catálogo de la API (open.higgsfield.ai, leído
2026-10-09) lista Seedance 2.0/2.5 (ByteDance), Kling 3.0 y Kling O3 (Kuaishou), MiniMax H3 /
Hailuo, Wan 2.6–3.0 y Happy Horse (Alibaba), LTX 2.5 (Lightricks), Grok Imagine (xAI). Como
"Higgsfield Exclusive" sólo aparecen **Genjutsu** (transferencia de movimiento), **Cinema
Studio 4.0** (dirección automática de escena), Soul/Soul 2 (imagen) y Ads Studio. **[P]**
Veo y Sora **no** aparecen en el catálogo de la API (sí en marketing/SEO de la app). **[P]**

**Presets de transición/efectos en la API: no existen.** Ni el índice de docs, ni la página de
modelos, ni el OpenAPI suplementario exponen "transitions", "effects", "motion presets" o los
presets de cámara (Super Dolly In, etc.). Esos presets son de la app web. **[P]** Lo que la
API sí expone es la **primitiva** con la que se construye una transición: first/last frame.

## 2. La API pública (verificado en `docs.higgsfield.ai`)

| Aspecto | Dato | Evid. |
|---|---|---|
| Base URL | `https://api.higgsfield.ai` (algún doc antiguo dice `platform.higgsfield.ai`) | [P] |
| Auth | `Authorization: Key <API_KEY_ID>:<API_KEY_SECRET>`; sólo servidor | [P] |
| Envío | `POST /<vendor>/<modelo>/<variante>` con JSON; `Idempotency-Key` opcional | [P] |
| Ciclo | `queued → in_progress → completed / failed / nsfw / canceled`; respuesta con `request_id`, `status_url`, `cancel_url` | [P] |
| Polling | `GET /requests/{request_id}/status` | [P] |
| Webhooks | query param `hf_webhook=<https url>`; reintentos 2 h en 5xx; **sin firma documentada** (re-verificar con el endpoint de status) | [P] |
| Salida | `video.url` (MP4); retención "al menos 7 días" → copiar a R2 | [P] |
| Rate limit | por **concurrencia** por cuenta/modelo, sin cifras públicas; al exceder responde **400** (no 429), sin `Retry-After`; ejemplo de mensaje con límite 4 | [P] |
| Cobro | prepago por créditos (top-up), créditos caducan al año; `failed`/`nsfw`/timeout no se cobran; factura sólo con contrato de compromiso | [P] |
| SDK | Python `higgsfield-client` (sync/async); TS listado como "coming soon" en una página y "disponible" en el FAQ | [P, contradictorio] |
| Estimación de coste | la página de billing menciona un endpoint de estimación; **no aparece** en el OpenAPI | [P, contradictorio] |

**First/last frame — la primitiva clave — SÍ está en la API:**

- `POST /kling-video/o3/first-last-frame`: `first_frame_url` (obligatorio), `last_frame_url`
  (opcional), `prompt` (obligatorio, ≤2.500 car.), `duration` 3–15 s (def. 5),
  `aspect_ratio` `16:9 | 9:16 | 1:1`, `mode` `std | pro | 4k` (def. `pro`), `sound`
  `on | off`, multi-shot opcional. Las URLs deben ser HTTPS públicas. **[P]**
- Kling 3.0 image-to-video usa otros nombres: `image_url` + `last_image_url`. **[P]**
- Seedance 2.0 en Higgsfield: el endpoint `reference-to-video` remite a un endpoint
  image-to-video aparte con `image_url`/`end_image_url` (no documentado en esa página). **[P]**
- Las páginas de modelo **no traen precio**; el precio está en la consola. **[P]**

**Madurez:** la página de anuncio de la API (`higgsfield.ai/blog/higgsfield-api`) tiene fecha
de publicación 2026-09-16 en sus metadatos — la API tiene **~3 semanas** a fecha de este
informe. **[P]** Las propias docs se contradicen en base URL, SDK TS y endpoint de
estimación, y declaran que los schemas de modelo "se están rediseñando". **[P]**

## 3. Precio y términos

### 3.1 Precio

- La API se factura **aparte** de las suscripciones de la web: saldo prepago en USD,
  tarifa publicada por generación/segundo, auto top-up, saldo caduca al año. **[P]**
- Tarifas en `open.higgsfield.ai` (2026-10-09), **todas con descuento promocional** (30–50%)
  y banner "100% cashback on API spendings": **[P, promocional — no presupuestar con esto]**

| Endpoint (Higgsfield API) | USD/s promo | USD/s lista | 5 s promo | 5 s lista |
|---|---|---|---|---|
| Kling O3 First/Last Frame | 0,042–0,056 | ~0,084–0,112 [I: ×2] | 0,21–0,28 | ~0,42–0,56 |
| Kling 3.0 Standard I2V | 0,042–0,063 | 0,084 (std) | 0,21–0,32 | 0,42 |
| Seedance 2.0 | desde 0,099 | 0,141 | ~0,50 | ~0,71 |
| Wan 3.0 | desde 0,025 | 0,050 | 0,13 | 0,25 |

- La app "Smooth Transitions" no publica coste por generación; funciona con créditos de la
  suscripción web, que **no** es la API. **[P]**

### 3.2 Términos de uso (Terms of Use, "Last updated: July 26, 2026", vigente para todos desde 2026-08-27) **[P]**

- §4.4: Higgsfield **no reclama la propiedad** de inputs ni outputs y **no restringe el uso
  comercial**; los derechos sobreviven a la cancelación y se pueden sublicenciar. El help
  center lista explícitamente publicidad, campañas pagadas y contenido de marca. **[P]**
- §4.4/§16.5: Higgsfield **puede usar Content, Inputs y Outputs para entrenar** sus
  modelos; sólo los clientes con **Enterprise Agreement** quedan excluidos. Lo ya usado no
  se puede retirar. **[P]** → Para Qualify significa que las fotos de producto y logos de
  *nuestros tenants* alimentarían el entrenamiento de un tercero salvo contrato Enterprise.
- §5.2(i): prohibido revender o "explotar comercialmente el Servicio"; §11.5: prohibido
  sublicenciar/redistribuir el Developer Access u ofrecerlo "standalone or as a
  pass-through without added value". **[P]** Qualify embebiendo la generación dentro de su
  generador es "valor añadido" en lectura literal **[I]**, pero no hay cláusula de
  plataforma/reseller explícita: confirmar por escrito antes de producción.
- §6.4: pueden incrustar marcas de agua invisibles / metadatos tipo C2PA; §5.5/§11.7:
  obligación de declarar contenido IA donde la ley lo exija y prohibido quitar la
  procedencia. **[P]** Compatible con la etiqueta de divulgación IA que Qualify ya aplica a
  `SCENE_VIDEO` (F5-MA-10).
- §11.9/§13.8: pueden cambiar la API y **suspender el acceso de inmediato** ante riesgo de
  seguridad o incumplimiento. §12: el cliente indemniza a Higgsfield; la indemnización
  frente a reclamaciones de PI sólo existe en Enterprise. **[P]**

### 3.3 Riesgo reputacional **[S]**

Forbes (feb. 2026) y prensa de Kazajistán documentaron quejas de facturación ("unlimited"
recortado tras el pago, cancelaciones difíciles), pagos a creadores retrasados y contenido
ofensivo en su programa de creadores; su cuenta de X fue suspendida el 2026-02-09. Un
análisis de julio 2026 criticó la licencia de entrenamiento. La empresa reconoció errores
operativos y discute parte de las acusaciones. Nada de esto afecta a la API técnicamente,
pero sí a la decisión de **poner datos de tenants** en ese proveedor.

## 4. Comparativa para el mismo trabajo (transición de ~2–5 s entre dos planos, 9:16)

| Opción | First+last frame | 9:16 | Duración | Coste 5 s (720p aprox.) | Integración | Evid. |
|---|---|---|---|---|---|---|
| **Seedance 1.0 pro vía BytePlus** (ya integrado) | **Sí** (`role: first_frame` + `role: last_frame`) | Sí | 2–12 s | **≈ USD 0,26** (102.960 tokens × 2,5/M); 2 s ≈ 0,10; 1080p 5 s ≈ 0,61 | Cambio pequeño en `_VideoSpec` | [P] |
| Seedance 1.0 pro **fast** | **No** (no está en la lista de modelos FLF) | Sí | 2–12 s | — | — | [P] |
| Seedance 2.0 / 2.5 (BytePlus) | Sí | Sí | 4–15 / 4–30 s | 7,0–10,7 USD/M tokens → ~0,7–1,1 | Mismo adapter | [P] |
| Higgsfield → Kling O3 FLF | Sí | Sí | 3–15 s | 0,21–0,28 promo / ~0,42–0,56 lista | Adapter nuevo | [P] |
| Kling API oficial (Kuaishou) | Sí (Kling 3.0: 1–2 imágenes) | Sí | 3–15 s | 0,11–0,22 USD/s según revendedor → 0,55–1,10 | Adapter nuevo | [S] |
| Runway API | `promptImage` con `position: first/last`; soporte por modelo sin confirmar (gen3a_turbo retirado 2026-07-30; gen4_turbo reportado sólo "first") | Sí | 5/10 s | gen4.5 0,12 USD/s → 0,60; gen4_turbo 0,05/s → 0,25 | Adapter nuevo | [P] precio / [S] FLF |
| Luma Ray 2 | keyframes `frame0`/`frame1` | Sí | 5/9 s | ~0,10–0,20 USD/s → 0,50–1,00 | Adapter nuevo | [S] |
| **Remotion `@remotion/transitions`** | n/a (transición determinista entre dos escenas) | Sí | libre | **USD 0** marginal (VPS propio, Free License ≤3 personas) | Ya tenemos el servicio | [P] |

Notas:

- **Seedance ya cubre la primitiva.** La doc oficial de ModelArk (*Create a video generation
  task*) lista "Image-to-video (first and last frames)" para *Dreamina Seedance 2.5, 2.0
  series, Seedance 1.5 pro y Seedance 1.0 pro*: dos objetos `image_url` con `role`
  obligatorio `first_frame`/`last_frame`; pueden ser idénticos (loop); si los aspect ratios
  difieren, manda el primero y el último se recorta. Es **mutuamente excluyente** con
  reference-to-video. **[P, leído 2026-10-09]** Nuestro `SeedanceVideoAdapter` sólo envía
  `first_frame` y ya pide `return_last_frame=True`: añadir `last_frame` es ~10 líneas. **[I]**
- **Remotion** (`TransitionSeries`): dos escenas se solapan durante la transición; la
  duración total = suma de secuencias − transiciones; `presentation` por defecto `slide()`,
  también `fade()`, `wipe()`… y `TransitionSeries.Overlay` para efectos sobre el corte (p.
  ej. light leaks) sin acortar la línea de tiempo. **[P]** Se instala con
  `npx remotion add @remotion/transitions`; `packages/render` **aún no lo tiene** (Remotion
  4.0.532). Catálogo completo de presentaciones (flip, clockWipe, iris…) no verificado en
  esta sesión. **[S]**
- **Lo que una IA aporta y Remotion no:** morph de sujeto (producto A → producto B),
  "match cut" con movimiento de cámara inventado, swaps de outfit/producto, loops 360°.
  Lo que Remotion aporta y la IA no: determinismo, coste cero, cero moderación/NSFW,
  latencia de segundos, el logo y el texto de la marca nunca se deforman, y sin etiqueta
  de IA obligatoria (un `fade` no es contenido sintético).

## 5. Veredicto

**Recomendación: SKIP Higgsfield (no implementar ahora). BUILD transiciones deterministas en
Remotion como camino por defecto. Para transiciones generativas, usar Seedance first+last
frame en el adapter que ya existe.** Higgsfield queda como candidato a "agregador
secundario" sólo si un día queremos Kling O3 y no hay vía directa razonable.

Por qué no Higgsfield:

1. **No aporta la pieza que lo haría único.** Los presets de transición/efectos/cámara
   son de la app web y **no están en la API**. **[P]** Lo que la API expone (first/last
   frame) es la misma primitiva que Seedance 1.0 pro ya nos da vía BytePlus. **[P]**
2. **Es un revendedor.** Kling, Seedance, Wan, MiniMax… revendidos con su margen y sus
   promociones; lo exclusivo (Genjutsu, Cinema Studio, Soul) no sirve para transiciones. **[P]**
3. **Datos de tenants y entrenamiento.** Sin Enterprise Agreement, los inputs (fotos de
   producto, logos de nuestros clientes) pueden usarse para entrenar sus modelos. **[P]**
4. **API inmadura**: ~3 semanas, docs contradictorias, schemas "en rediseño", rate limit
   sin cifras que responde `400` (no `429`), webhooks sin firma, precios promocionales
   temporales. **[P]**
5. **Riesgo contractual y reputacional**: cláusula anti pass-through (§11.5) sin régimen
   de plataforma explícito, suspensión inmediata posible (§11.9), historial de quejas de
   facturación. **[P]/[S]**
6. **Coste por post**: a precio promo, Kling O3 vía Higgsfield (~USD 0,21–0,28 / 5 s)
   empata con Seedance 1.0 pro (~0,26 / 5 s a 720p); a precio de lista es ~2× más caro. **[P]/[I]**

Riesgos de la alternativa recomendada (Seedance FLF): calidad de morph no evaluada con
productos reales; 1.0 pro es mudo; mínimo 2 s; la latencia real de Seedance no está medida
en este repo (el adapter tolera hasta 480 s de polling). Validarlo con 3–5 pares de fotos
del golden set antes de exponerlo al operador.

### 5.1 Cómo encajaría (si se decidiera implementar)

**A. Seedance FLF (recomendado, mínimo):** sin nueva `GenerationTask`. Reutilizar
`GenerationTask.SCENE_VIDEO` — sigue siendo metraje generado, lleva la etiqueta de IA — y
añadir el parámetro opcional `last_frame` en `_VideoSpec.from_params`, que en `body()`
emite un segundo `image_url` con `role: "last_frame"`. Validaciones previas a la llamada:
`last_frame` exige `first_frame`; el modelo debe estar en la lista FLF (1.0 pro, 1.5 pro,
2.x; **no** 1.0 pro fast); se rechaza junto con referencias. Salida: MP4 a R2 en el acto
(URL de 24 h), `Usage.media_seconds` = duración reportada. El clip resultante entra en
Remotion como port `video` (ya existe en el contrato, `CONTRACT.md` §1) entre las dos
escenas.

**B. Remotion determinista (camino por defecto):** añadir `@remotion/transitions` a
`packages/render` y usar `TransitionSeries` en las composiciones de plantilla; el tipo de
transición puede ser un port `string` con `enum` en el manifest (`fade|slide|wipe|…`).
Coste `remotion_selfhost` = 0,00 ya registrado en `pricing_data`.

**C. Higgsfield (sólo si se reabre):** `HiggsfieldVideoAdapter`, `name="higgsfield"`,
`supports={SCENE_VIDEO}`; `POST https://api.higgsfield.ai/kling-video/o3/first-last-frame`
con `first_frame_url`, `last_frame_url`, `prompt`, `duration` 3–15, `aspect_ratio="9:16"`,
`mode="std"`, `sound="off"`; cabecera `Authorization: Key id:secret` + `Idempotency-Key`
derivada del draft; polling a `/requests/{id}/status` hasta `completed|failed|nsfw|canceled`
(no se cobran fallos ni NSFW); tratar `400` "Maximum number of concurrent requests" como
reintento con backoff. Diferencia con Seedance: **exige URLs HTTPS públicas** (no `data:`),
así que hace falta una URL R2 prefirmada de corta vida. Precio en `pricing_data` por
segundo, con nota de que la tarifa de lista es ~2× la promocional. Precondición:
Enterprise Agreement (exclusión de entrenamiento) y confirmación escrita del §11.5.

## 6. Fuentes

Primarias (Higgsfield):
- https://docs.higgsfield.ai/docs/llms.txt (índice de docs)
- https://docs.higgsfield.ai/docs/quickstart.md
- https://docs.higgsfield.ai/docs/how-to/introduction.md
- https://docs.higgsfield.ai/docs/api-reference/overview.md
- https://docs.higgsfield.ai/docs/concepts/requests.md
- https://docs.higgsfield.ai/docs/concepts/rate-limits.md
- https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md
- https://docs.higgsfield.ai/docs/how-to/webhooks.md
- https://docs.higgsfield.ai/docs/help/faq.md
- https://docs.higgsfield.ai/docs/models.md
- https://docs.higgsfield.ai/docs/openapi.json
- https://docs.higgsfield.ai/docs/models/kling-o3/first-last-frame.md
- https://docs.higgsfield.ai/docs/models/kling-o3/image-reference.md
- https://docs.higgsfield.ai/docs/models/seedance-2/reference-to-video.md
- https://open.higgsfield.ai/ y https://open.higgsfield.ai/models/kling-video/v3.0/std/text-to-video/playground (catálogo y precios)
- https://higgsfield.ai/apps/transitions
- https://higgsfield.ai/blog/Kling-Start-End-Frames
- https://higgsfield.ai/blog/higgsfield-api
- https://higgsfield.ai/terms-of-use-agreement
- https://higgsfield.ai/blog/terms-of-use-privacy-policy-update
- https://higgsfield.ai/creator-hub/help-center/account-and-privacy/who-owns-my-generations-and-can-i-use-them-commercially

Primarias (otros):
- https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api (leída con el navegador, `_ROUTER_DATA…MDContent`)
- https://docs.dev.runwayml.com/guides/pricing
- https://www.remotion.dev/docs/transitions/ y https://www.remotion.dev/docs/transitions/transitionseries
- `packages/creative/src/qualify_creative/pricing_data/v3.json` (tarifas Seedance ya registradas)

Secundarias:
- https://www.forbes.com.au/?p=177110 (investigación Forbes, feb. 2026)
- https://qazinform.com/amp/scam-claims-and-backlash-hit-kazakhstans-ai-unicorn-higgsfield-b311a7/
- https://startupfortune.com/?p=16602 (crítica de la licencia de entrenamiento, jul. 2026)
- https://ai-for-real-life.beehiiv.com/p/how-to-use-higgsfield-ai-to-create-seamless-transitions-between-scenes
- https://www.runcomfy.com/models/kling/kling-3.0/pro/image-to-video y https://catalog.empiriolabs.ai/models/kling-v3 (precios Kling por revendedor)
- https://docs.comfy.org/tutorials/api-nodes/runway/video-generation (retiro de gen3a_turbo)
- https://apiframe.ai/guides/luma-api-guide y https://www.runcomfy.com/ko/models/luma/luma-dream-machine (Luma)
- https://comfy.org/hub/models/seedance-2-5-first-last-frame.md
