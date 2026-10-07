# Pendientes del generador de contenido

**Fecha:** 2026-10-05 · **Dueño:** Deivid · **Tickets:** QUA-110 (generación), QUA-109 (POST), QUA-116 (plantillas)

Lo que el generador (`/create`) todavía no resuelve para que un POST generado pueda **publicarse solo** desde el Planificador. Cada punto dice qué falla hoy, por qué se dejó así y qué hay que tocar cuando se retome.

---

## 1. Los archivos generados se guardan en local, no en R2 — `[PENDIENTE, aplazado a propósito]`

**Decisión (2026-10-05):** se deja en local por ahora. Se archiva aquí para resolverlo después.

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

---

## 4. Seedance y BYOK — `[SIN EMPEZAR, fuera del alcance actual]`

- Seedance no tiene código; QUA-110 lo deja opcional.
- Las claves de los proveedores las paga la plataforma (decisión D4); no hay «trae tu propia clave».
