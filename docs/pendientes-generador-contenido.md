# Pendientes del generador de contenido

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
- Todo lo que el generador produce (slides del flyer o carrusel, salidas fijas y Reel de las plantillas, video de HeyGen y su miniatura) se escribe en el disco del servidor, bajo `generated/{tenant}/{draft}/…` (`creative/media.py`, `generated_key`).
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
  - **HeyGen** sigue disponible con `QUALIFY_VIDEO_ENGINE=heygen`.
- Las claves de los proveedores las paga la plataforma (decisión D4); no hay «trae tu propia clave».

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
