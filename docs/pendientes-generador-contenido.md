# Pendientes del generador de contenido

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración ya está en el código (2026-10-16), lista para probar cuando lleguen las llaves de BytePlus**: el detalle y lo que falta está en el §6 de este documento.

**Fecha:** 2026-10-05 · **Dueño:** Deivid · **Tickets:** QUA-110 (generación), QUA-109 (POST), QUA-116 (plantillas)

Lo que el generador (`/create`) todavía no resuelve para que un POST generado pueda **publicarse solo** desde el Planificador. Cada punto dice qué falla hoy, por qué se dejó así y qué hay que tocar cuando se retome.

---

## 1. Los archivos generados se guardan en local, no en R2 — `[RESUELTO 2026-10-06]`

**Decisión (2026-10-05):** se deja en local por ahora. Se archiva aquí para resolverlo después.

**Resuelto (2026-10-06, rama `feat/generated-media-r2`).** Cada archivo generado vive **solo en R2**, sin copia local (pedido del fundador el mismo día: «no me sirve tenerlo en local»):

- Va a `t/{tenant}/generated/{draft}/r{revisión}/{nombre}` (`media.generated_object_key`), con su `content_type` guardado junto al objeto (`ObjectGate.put_media`). Esa clave es a la vez `image_assets.media_url` (lo que muestra la app) y `object_key` (lo que publica el Planificador).
- Es **única por generación**: regenerar sube la revisión y nunca sobrescribe el objeto de una revisión aprobada.
- La miniatura del video también vive en R2 (`params.thumbnail_key`).
- **Si R2 rechaza el archivo**, la pieza falla con «No pudimos guardar la pieza en R2. Inténtalo de nuevo en un momento.» y no se guarda en ningún otro sitio.
- Todas las pantallas lo muestran por `/r2media/<token>` (`r2_media.issue_view_path`, token de una hora): el resultado del generador (incluida la descarga y el póster del video), el detalle del borrador y las miniaturas del calendario (`planner_provider._thumbnail_url`).
- Canva lee la pieza desde R2 (`R2ReadingMediaStore`).

Verificado contra el bucket real con un viaje completo: escribir, comprobar el prefijo del Planificador, leer y borrar el objeto de prueba. El criterio de cierre está cubierto por `test_a_generated_pieces_r2_copy_is_publishable`.

**Queda fuera:** los borradores generados **antes** de este cambio siguen en el disco (se siguen viendo; para publicarlos hay que regenerarlos). El catálogo (`uploads/{tenant}/catalog/…`) y lo que vuelve de Canva siguen en local. Nada borra las revisiones viejas de R2.

*Lo que sigue es el registro original del pendiente.*

**Qué pasa hoy**
- Todo lo que el generador produce (slides del flyer o carrusel, salidas fijas y Reel de las plantillas, video del presentador, su voz y su miniatura) se escribe en el disco del servidor, bajo `generated/{tenant}/{draft}/…` (`creative/media.py`, `generated_key`).
- `R2ReadingMediaStore` **lee** de R2 (el logo del Brand Kit) pero **escribe siempre en local**.
- El Planificador solo publica archivos que viven en R2 bajo `t/{tenant}/…`. Un POST generado sale como no publicable con el motivo `media_not_in_r2` («Los archivos del POST todavía no están listos para publicar (R2)», `planner/publishable.py`).
- Se puede publicar a mano descargando el archivo, pero no por el Planificador ni por el ejecutor automático (QUA-111).

**Qué hay que hacer**
1. Que `MediaStore.write` reciba el `tenant_id` y el `content_type`, y que la implementación de producción suba con `ObjectGate.put_media(tenant_id, key, fileobj, content_type)` (exige el tipo y lo guarda con el objeto).
2. Claves en el prefijo del tenant y **únicas por generación**: `t/{tenant}/generated/{draft}/{generación}/{nombre}`. Hoy una regeneración reescribe los mismos nombres de archivo; una revisión aprobada nunca debe apuntar a un objeto que otra generación sobrescriba (nota de QUA-111 del 2026-09-27, punto 6).
3. Guardar la clave de R2 en `image_assets.object_key` y mostrarla en la app con `/r2media/<token>` (`r2_media.issue_view_path`), igual que ya hace el Brand Kit con el brandboard.
4. La miniatura del video (`params.thumbnail_key`) también a R2, para que el calendario y el detalle del borrador puedan mostrarla.
5. En desarrollo sin R2 configurado, seguir cayendo a local (el mismo criterio que `brand_finish`: un fallo de R2 no pierde el borrador).

**Ya resuelto y que no hay que rehacer:** `image_assets.content_type` ya se rellena en cada escritura (punto 2 de abajo), así que en cuanto el archivo esté en R2 el Planificador tiene todo lo que pide.

**Criterio de cierre:** un POST generado y aprobado pasa `publishable.evaluate()` sin `media_not_in_r2`, y el ejecutor de QUA-111 lo publica.

---

## 2. Las imágenes se guardan en JPEG — `[RESUELTO 2026-10-05]`

**Problema:** Meta solo acepta imágenes JPEG y el publicador rechaza cualquier otra cosa (comprueba el tipo declarado **y** los bytes, `publishing/staging.py`). El generador guardaba PNG: los flyers y carruseles, y las salidas fijas de las plantillas (feed 4:5 e historia 9:16, que Remotion devuelve en PNG). Era el hallazgo H1 de QUA-116.

**Solución:** `qualify_creative.photo.normalize.to_meta_jpeg`. Se renderiza en PNG como siempre y se **guarda en JPEG** en un único punto (`creative/media.py`, flyer y salidas fijas de plantilla):
- bytes JPEG reales, archivo `.jpg`, `content_type = image/jpeg`;
- sin redimensionar ni enfocar (son gráficos ya a su tamaño final; el enfoque haría halos en el texto) y croma completo 4:4:4 para que el texto de color no se corra;
- la transparencia se aplana sobre blanco (JPEG no tiene canal alfa: sin esto quedaría negra);
- calidad 92, bajando solo si el archivo superara los 8 MB que permite Meta.

Además, cada escritura del generador (imagen o video) rellena ahora `image_assets.content_type` (`image/jpeg` o `video/mp4`), que el Planificador exige y que hasta hoy quedaba vacío.

---

## 3. El media se genera con la primera variante válida, no con la aprobada — `[PENDIENTE]`

El flyer o el video se producen con la primera variante de copy que pasa las reglas de marca, no con la que el operador elige al aprobar. El caption publicado y el texto que aparece dentro de la imagen o el video pueden no coincidir. Viene de la nota de coordinación de QUA-111 (2026-09-27, punto 5).

**Qué hay que hacer:** generar (o regenerar) el media con la variante seleccionada, o fijar la variante antes de producir el media.

**Actualización 2026-10-06:** los videos (avatar humano, avatar animado y video publicitario) y «Con plantilla» piden **una sola opción** de copy, porque el motor de ángulos todavía no existe. Para ellos el desajuste desaparece: la única variante es la del media. Sigue aplicando al guion para creador real (3 opciones, sin media) y a los flyers ya generados.

**Actualización 2026-10-08:** la imagen publicitaria también pide **una sola opción**. Solo el guion para creador real ofrece 3, y no genera media, así que el desajuste ya no se da en piezas nuevas.

---

## 4. Seedance y BYOK — Seedance `[HECHO 2026-10-08]`, BYOK `[FUERA DE ALCANCE]`

- **Seedance (videos con avatar) y Seedream (imagen publicitaria)** entran por BytePlus ModelArk como adaptadores del `GenerationProvider` (`qualify_creative/adapters/byteplus_ark.py`). Precios en la tabla `v3`.
  - **Seedance 1.0** es el modelo de pruebas: video sin voz y de 12 s como máximo, así que el guion queda en el texto del post.
  - **Seedance 2.x** habla el guion, pero necesita más saldo para activarse y rechaza caras reales como referencia.
  - ~~**HeyGen** sigue disponible con `QUALIFY_VIDEO_ENGINE=heygen`.~~ `[RETIRADO 2026-10-16]`: ya no está en el código; el presentador que habla es OmniHuman, ver §6.
- Las claves de los proveedores las paga la plataforma (decisión D4); no hay «trae tu propia clave».

### 4.1 Seedance 2.5: modo borrador y render final al aprobar `[HECHO 2026-10-22, borradores probados en vivo 2026-10-23]` (m-24820142)

- **Cómo funciona.** Si el modelo de Seedance tiene modo borrador (hoy solo `dreamina-seedance-2-5-260628`), todo video se genera primero como **borrador a 480p** (`draft: true`), sin importar `QUALIFY_SEEDANCE_RESOLUTION`. Aplica al clip, al video con presentador de Seedance y a las diapositivas animadas de la galería.
  - Al pulsar **«Aprobar esta versión»** se aprueba el texto y se lanza el **final a 1080p** solo con el id del borrador (`content: [{"type": "draft_task", ...}]`). Ni el prompt ni las referencias, `ratio`, `duration`, `seed`, `generate_audio` u `omni_reference_task_type` se reenvían: ModelArk da error aunque coincidan.
- **El final reemplaza al borrador en la misma fila de `image_assets`.** Así Piezas, las descargas y el Planificador no cambian.
  - Lo que el final necesita se guarda en `params["draft"]`: id, `created_at`, modelo, cómo se terminó el video y el costo del borrador. Ver `qualify_api/creative/draft_mode.py`.
  - La salida 1080p de 2.5 es HEVC de 10 bits: se **transcodifica a H.264** con `PyAvVideoFitter`. A la vez se vuelve a poner el logo (en el clip) o el texto (en la diapositiva).
- **Cuándo se bloquea.**
  - Mientras el final no está, el Planificador no publica la pieza (`MEDIA_DRAFT_PENDING`).
  - Si el borrador tiene más de 7 días, se avisa antes de llamar a la API (`DraftExpired`) y la solución es regenerar.
  - Si el final falla, la versión aprobada se conserva y aparece «Reintentar video final».
- **Costos.** El borrador y el final se registran por separado en `creative_usage_events`, con los tokens reales de cada tarea (desde 2026-10-23 también en la columna `output_tokens` de esa fila, no solo en `image_assets.params`).
  - **Con video de entrada la tarifa es otra** (tabla de precios `v7`, 2026-10-23): BytePlus cobra 2.5 a USD 6,40/M tokens a 480p/720p y 7,00/M a 1080p cuando la tarea lleva videos de referencia, frente a 10,70/M y 11,70/M sin video. El final paga la tarifa que corresponde a su **borrador**: por eso el borrador guarda `video_input` y la duración de sus videos en `params["draft"]`.
  - **Los tokens cobrados incluyen el video de entrada.** La estimación previa al gasto (`estimate_video_tokens`) suma los segundos de los videos de referencia (medidos con PyAV; si no se pueden leer, el máximo de 30 s) a los del video que se genera. Sin eso se quedaba corta unas 2,4 veces. Medición: [modelos-generativos/seedance-2-5.md](modelos-generativos/seedance-2-5.md).
- **Pendiente.**
  - ~~**Activar Seedance 2.5 en ModelArk.**~~ `[HECHO 2026-10-23]`: `dreamina-seedance-2-5-260628` es el modelo activo en `QUALIFY_SEEDANCE_MODEL` y en `QUALIFY_SEEDANCE_REFERENCE_MODEL` (el 2026-10-22 la cuenta respondía `403 AccessDenied`).
  - ~~**Probar en vivo un borrador.**~~ `[HECHO 2026-10-23]`: tres borradores con referencias y uno sin ellas, en [modelos-generativos/seedance-2-5.md](modelos-generativos/seedance-2-5.md).
  - **Probar en vivo el final** de un borrador: medir su costo (y si sus tokens vuelven a contar el video de entrada; hoy la estimación supone que sí), ver si los fotogramas salen iguales y obtener el error real de un borrador caducado.
  - `omni_reference_task_type`: el generador solo manda `reference` (crea videos a partir de referencias). Editar o extender un video **no está implementado**: `edit` exige `ratio: adaptive` y `duration: -1`, y `extend` exige `ratio: adaptive`.
- **Para probar en local con videos o audios de referencia** hace falta una URL pública, porque ModelArk descarga esos archivos y no acepta Base64.
  - `QUALIFY_PUBLIC_MEDIA_BASE_URL` debe apuntar al servidor de **`qualify_api`**: la ruta `/public/media/{token}` vive ahí, no en Reflex.
  - En local: `uvicorn --factory qualify_api.http.app:create_app --host 127.0.0.1 --port 8010 --env-file .env` y, en otra terminal, `cloudflared tunnel --url http://127.0.0.1:8010`. En Git Bash hay que anteponer `MSYS_NO_PATHCONV=1`, o la URL se estropea.
  - La URL de un túnel rápido cambia en cada arranque y caduca: hay que copiarla al `.env` y reiniciar Reflex.

---

## 5. «Regenerar» en Borradores — aviso `[HECHO 2026-10-09]`, reinicio del proceso `[PENDIENTE]`

Anotado el 2026-10-09 tras verificarlo (sin cambios de código todavía).

- **Qué hace hoy.** «Regenerar» (`CreativeState.reject_current(regenerate=True)`) devuelve el borrador a «generando» y lo despacha al mismo hilo en segundo plano que usa `/create`; la pantalla de Borradores sondea el estado (`poll_draft`, hasta 5 min). Es asíncrono: la petición vuelve enseguida.
- **Qué falta.**
  1. ~~**No avisa al terminar.**~~ Hecho el 2026-10-09: `poll_draft` reutiliza `_generation_done_events(outcome, source="draft")` — toast («Tu borrador ya está regenerado…» / «No se pudo regenerar…») y notificación del navegador si la pestaña está detrás; «Regenerar» pide el permiso una vez.
  2. ~~**El sondeo se detiene al salir del borrador.**~~ Hecho el 2026-10-09: el sondeo sigue aunque abras otro borrador u otra página; solo deja de refrescar el detalle que no está en pantalla, y avisa al terminar.
  3. **Un reinicio del proceso mata la generación en curso.** El despachador «inline» (`InlineDispatcher`, diseño §7.4) corre la generación en un hilo *del propio proceso*: una recarga automática por cambio de código en desarrollo, un despliegue o un corte la pierden; el borrador queda en «generando» hasta que el barrendero lo marca como fallido por tiempo (`reaper`). Observado el 2026-10-09: dos «Regenerar» de una imagen publicitaria fallaron con `provider_error` sin detalle y sin gasto mientras el backend se reiniciaba por copias de archivos, y un borrador creado justo antes de apagar el servidor quedó en «generando». La solución de fondo es la migración a Celery (§7.4), no un parche en la UI.
- **Además, el fallo real de los «Regenerar» del 2026-10-09 — `[RESUELTO 2026-10-09]`.** El rastro de la consola lo dejó claro: `UniqueViolation uq_copy_variant_ordinal`. `finish_generation` guardaba las variantes nuevas con los mismos `ordinal` que las de la revisión anterior, y la restricción única (0009) las rechazaba — después de pagar al proveedor. Ahora el repositorio reemplaza las variantes del borrador (y limpia `selected_variant_id`, que apuntaba a una de la revisión vieja), igual que ya reemplazaba los medios; y la migración **0048** concede al rol de la app el `DELETE` sobre `copy_variants` e `image_assets`, que 0009 nunca dio (el reemplazo de medios habría fallado igual). Prueba: `packages/api/tests/test_creative_regenerate_db.py`.
- **Qué tocar cuando se retome.** Solo queda el punto 3, que es del despachador (migración a Celery), no del generador ni de la UI.

---

## 6. Videos con avatar: de HeyGen a ByteDance — `[DECIDIDO 2026-10-16]` · `[HECHO]` en el código, pendiente de llaves

**Decisión del fundador (2026-10-16):** los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** para el avatar que habla, **Seedance** para el video, **Seedream** para la imagen y el primer fotograma, y **Seed Speech** para la voz clonada de la marca. HeyGen queda **retirado**; los documentos que lo mencionan llevan el aviso `[OBSOLETO]`. La investigación que respalda la decisión: [Avatar que habla — OmniHuman frente a HeyGen](investigacion-avatar-omnihuman-vs-heygen.md), [Voz clonada — Seed Speech frente a HeyGen](investigacion-voz-seed-speech-vs-heygen.md), [Avatar reutilizable — suite ByteDance](avatar-reutilizable-voz-y-movimiento-bytedance.md) y [Costos comparativos](costos-comparativos-herramientas-ia.md).

**Pedido del fundador (2026-10-16):** «migremos todo lo que está en HeyGen… dejar todo preparado para cuando tenga las api key se puedan probar, esto incluye el clonador de voz del brandkit». Hecho ese mismo día, probado sin red (dobles de los proveedores con el router y las tarifas reales); **nada se ha llamado todavía contra BytePlus**.

**Cómo funciona ahora el video con avatar (motor `omnihuman`):**

1. **La voz se resuelve primero, en el servidor** (`qualify_api/creative/voice_access.py`, `BrandVoiceResolver`). El navegador solo manda `"brand"` (la voz clonada de la marca) o el id de una voz pública de una lista cerrada; el id del clon nunca sale del servidor. Una voz que la marca no puede usar se rechaza **antes de gastar nada**.
2. **Seedream compone al presentador** (descrito, o la imagen del operador) con los productos y el fondo → `presenter.jpg`.
3. **Seed Speech lee el guion exacto** con esa voz → `voice.mp3` (TTS 1.0 para las voces públicas, Voice Replication 2.0 para la clonada). La primera síntesis con la voz clonada la «activa» (`activated_at`): BytePlus cobra ahí los USD 2 del slot y la voz ya no se puede reentrenar.
4. **OmniHuman hace hablar al presentador**, labios sincronizados (1.5 por defecto, audio < 60 s; 2.0 con `QUALIFY_OMNIHUMAN_REQ_KEY`). Foto y voz le llegan como **URL públicas con token** (no acepta Base64); el video que devuelve vive una hora, así que se copia en el acto → `video.mp4`.
   Desde m-24852495 el `task_id` se guarda al enviarlo, la espera cuenta desde `generating` y un
   render que tarda más que la espera se recupera por id sin volver a pagar foto, voz ni render
   (detalle en [Recuperar videos sin pantalla](recuperar-videos-sin-pantalla.md)).

Costos que se registran (`pricing_data/v5.json`): Seedream USD 0.035 por imagen, Seed Speech USD 30 por millón de caracteres, OmniHuman 1.5 USD 0.12 por segundo de voz (2.0: 0.07, pendiente de la primera factura). Un video de 20 s ≈ USD 2.45.

**Estado del código (2026-10-16):**

| Pieza | Hecho | Dónde |
|---|---|---|
| **OmniHuman** (avatar que habla) | Adaptador `GenerationProvider` (1.5 y 2.0, submit + poll, códigos de error), cotización en las recetas («Avatar hablando a cámara», USD 1.80 a 3.70) | `qualify_creative/adapters/byteplus_omnihuman.py`, `MediaProducer._omnihuman_video`, `render/recipes.py` |
| **Seed Speech** (voz) | Cliente (clonar, consultar, sintetizar), voces públicas en español, adaptador de locución | `qualify_creative/adapters/byteplus_speech.py` |
| **Clonador de voz del Brand Kit («Tu voz»)** | Clona en Seed Speech: la grabación se convierte a WAV 24 kHz mono (≤ 30 s), se guarda en R2 (procedencia), se entrena y el demo se copia a R2. Consentimiento con texto literal. Reentrena bajo el mismo id si la voz nunca se usó | `Qualify/voice_lab.py`, `qualify_api/creative/voice_clone.py`, migración **0067** |
| **Selector de voz en /create** | «Tu voz» primero (si está lista) y las voces públicas; solo con el motor OmniHuman | `Qualify/creative_provider.voice_options`, `CreativeState.load_voice_options`, `content_generator._avatar_section` |
| **Migración 0067** | `brand_voice_clones` neutral al proveedor (`provider`, `external_voice_id`, muestra y demo en R2, `consent_text`, `activated_at`); `template_runs.engine` acepta `omnihuman`. Reversible (probado bajar/subir) | `migrations/postgres/versions/0067_voice_clone_provider.py` (renumerada el 2026-10-19) |
| **HeyGen** | **Retirado del código**: adaptador, catálogo de looks/voces y sus pruebas borrados. Un borrador viejo con motor `heygen` se rechaza sin gastar | — |

**Elección del motor:** `QUALIFY_VIDEO_ENGINE` vacío → `omnihuman` en cuanto estén las dos llaves (`QUALIFY_BYTEPLUS_SPEECH_API_KEY` y `QUALIFY_BYTEPLUS_CV_API_KEY`), `seedance` mientras tanto. Así nada cambia hoy y el avatar que habla se enciende solo al poner las llaves.

**Lo que falta para probarlo en vivo:**

- [ ] Las dos llaves de BytePlus en el `.env` (Seed Speech de la consola Voice; Vision AI para OmniHuman — según la investigación, con verificación empresarial).
- [ ] `QUALIFY_PUBLIC_MEDIA_BASE_URL` alcanzable desde internet: OmniHuman descarga la foto y la voz, `localhost` no le sirve. En local, un túnel hacia `qualify_api` (no hacia Reflex): los pasos están en §4.1, «Para probar en local».
- [ ] Confirmar con la primera factura la tarifa real de OmniHuman 2.0 y de las voces públicas (TTS 1.0 está tarifado como Voice Replication, el lado conservador).
- [ ] Las voces ya clonadas en HeyGen no se migran: el Brand Kit las muestra como «sin voz» y hay que clonar de nuevo.
- [ ] Seed Speech no tiene API para borrar voces: una voz reemplazada queda en la cuenta (BytePlus borra las no usadas a los 7 días).
- [ ] El cobro del slot de la voz clonada (USD 2 en la primera síntesis) no se registra todavía en `creative_usage_events`.

**Para el stock (2026-10-16):** el fondo de video detrás del avatar sigue fuera: el presentador es una imagen fija compuesta por Seedream. Se decide después de la primera prueba con OmniHuman.

---

## 7. Clip: referencias e imágenes y videos en un solo bloque — `[EN PARTE HECHO 2026-10-19]` (anotado 2026-10-19)

**Hecho (2026-10-19, pedido del fundador: «en el clip el drag and drop quiero que incluya los videos y estos se puedan poner como inicio y final»):** una sola tira «Orden del clip» con las imágenes **y** los videos, que se arrastran juntos; el primero abre el clip y el último lo cierra, sea imagen o video. Un video como inicio presta su **primer** fotograma y como final su **último** (`MediaProducer._clip_frame`, PyAV) y sigue yendo como video de referencia (movimiento). Un video nuevo entra antes de la imagen que cierra, para no quitarle el fotograma a una imagen sin que el operador lo pida (`CreativeState._clip_strip`). **Falta** lo de abajo: un solo selector para imágenes y videos (hoy siguen siendo dos bloques para añadir, «Imágenes» y «Videos») y decidir lo de «Audios».


**Pedido del fundador (2026-10-19):** «en el apartado de clip quiero que las referencias se unan con los videos».

**Qué pasa hoy:** la vista «Referencias» del Clip separa los insumos en bloques distintos: «Imágenes» (hasta 9, la primera abre el clip y la última lo cierra; las del medio llevan rol producto / lugar / estilo), «Videos» (hasta 3, de 2 a 15 s) y «Audios» (hasta 3), y cada bloque tiene su propio selector (Catálogo o Inspiración · Subir · Piezas). Con una inspiración de stock que trae imágenes y videos, el operador elige en dos sitios distintos lo que para él es una sola cosa: «mis referencias».

**Qué hay que hacer cuando se retome:**
1. Un solo bloque «Referencias» con imágenes y videos juntos, en el orden en que se eligen, cada uno con su marca de tipo (imagen / video) y su vista previa (el video con el play en el centro, sin modal y sin mover el contenido, igual que en el stock).
2. Un solo selector con las mismas pestañas, que muestre imágenes y videos a la vez.
3. Respetar los límites de Seedance 2.x por tipo (9 imágenes, 3 videos), con un aviso al pasar uno; los fotogramas de inicio y fin siguen siendo imágenes.
4. Por dentro el brief no cambia (`clip_image_keys`, `clip_video_keys`, roles y fotogramas): es un cambio de presentación en `Qualify/content_generator.py` (`_clip_references_view`, `_clip_block` y `_media_picker`) y de estado en `CreativeState` (`clip_images`, `clip_videos`).
5. Decidir con el fundador si «Audios» entra en el mismo bloque o queda aparte.
