# ADR 39 — Retención de las piezas: los archivos se borran de R2 a los 3 meses, con aviso

**Estado:** `[PROPUESTO — decisiones del responsable del ticket m-24828907, 2026-10-22; pendiente de firma del fundador]`
**Ticket:** m-24828907 («Piezas: aviso para descargar antes del borrado a los 3 meses»).
**Código:** `packages/api/src/qualify_api/creative/retention.py` (la regla), `creative/retention_job.py` (quién la corre), `qualify_shared/objects/gate.py` (`ObjectGate.delete_prefix`), migración `0076_piece_media_retention.py`.

## Contexto

Desde el 2026-10-06 cada archivo que genera el generador de contenido (imágenes, videos, pósters, voz, escenas intermedias de plantilla) vive **solo en R2**, bajo `t/{tenant}/generated/{draft_id}/r{revisión}/…`, sin fecha de caducidad. Con cada regeneración la revisión anterior se queda en R2 aunque ya ninguna fila apunte a ella. El almacenamiento crece sin techo.

El ticket pide borrar el contenido a los 3 meses y avisar antes para que el operador lo descargue.

Esto **no** es la política de `docs/backlog-retencion-datos-r2.md` (RET-01…08): aquella trata la media ganada de la ingesta (7–30 días, reglas de ciclo de vida de R2, sin código). Son planos distintos y no deben unificarse sin una decisión nueva.

## Decisión

1. **Fecha de borrado** = la más reciente de (a) la generación de la revisión actual (`MAX(image_assets.created_at)` de sus archivos en R2) y (b) el último evento de calendario que sale o salió (`scheduled`, `publishing`, `published`), **más 90 días**. No se guarda: se deriva cada vez de lo que ya está guardado, así no puede quedar desactualizada. Regenerar o volver a programar una pieza le da otros 90 días.
2. **Aviso** en la app (galería `/drafts` y ficha `/drafts/{id}`) desde **15 días antes**: «Descarga esta pieza: se elimina el DD/MM/AAAA (en N días)», con el botón «Descargar» de m-24828908. Sin correo ni WhatsApp (fuera de alcance del ticket).
3. **Retención por calendario:** una pieza con un evento `scheduled` o `publishing` **nunca** se borra, sea cual sea la fecha (el publicador lee los bytes de R2 al publicar). Las piezas «recurrentes» con ocurrencias futuras se retienen; se borran 90 días después de su último evento. Los eventos `failed` y `cancelled` no retienen ni alargan nada.
4. **Qué se borra:** la **carpeta entera** de la pieza (`t/{tenant}/generated/{draft_id}/`), no solo las claves a las que apunta la base de datos: así salen también las revisiones viejas y los intermedios sin fila. La fila, su copy y su procedencia **se conservan**; `content_drafts.media_purged_at` marca «Contenido eliminado».
5. **Registro:** cada borrado (real o de prueba) queda en `content_draft_purges` (qué prefijo, cuántos objetos y bytes, fecha de vencimiento, cuándo), de solo inserción para la app, con RLS.
6. **Quién lo corre:** el servicio `calendar-worker` (ya siempre encendido en producción) lo corre al arrancar y cada 24 h, aislado: si falla, sigue publicando. Hay además un comando manual, `just piece-purge --tenant <uuid> [--execute]`.
7. **Activación en dos pasos:** se despliega en **modo de prueba** (solo registra qué borraría). El borrado real se activa con `QUALIFY_PIECE_PURGE_EXECUTE=1` en `.env.prod`, después de revisar el registro. El primer borrado posible es hacia el 2027-01-04 (90 días después de la primera pieza en R2).
8. **Fuera de alcance:** las piezas anteriores al 2026-10-06 (archivos locales `generated/{tenant}/…`) y las exportaciones de Canva (también locales): ni aviso ni borrado.

### Cambio deliberado en la puerta de R2

`ObjectGate` gana **un** método, `delete_prefix(tenant_id, prefix, execute=False)`. Hasta hoy la puerta no podía borrar nada, y su conjunto de métodos está fijado en `test_objects_gate.py`: este ADR es la decisión revisada que ese test exige. Límites:

- solo carpetas **por debajo** de una raíz de `PURGEABLE_ROOTS` (hoy solo `generated/`), nunca la raíz misma ni el tenant entero;
- el prefijo del tenant se comprueba como en cualquier otra llamada, y debe terminar en `/`;
- el kit de marca, el stock, el raw de primera parte y la media de publicación **no** se pueden borrar por aquí. Una raíz nueva en `PURGEABLE_ROOTS` es una decisión revisada, igual que el conjunto de métodos.

## Alternativas descartadas

- **Reglas de ciclo de vida de R2** (lo que proponía RET-02 para la ingesta): borran por edad del objeto sin mirar el calendario, así que no pueden respetar las piezas programadas ni las recurrentes, no avisan y no marcan la fila. Una pieza programada para dentro de 4 meses se publicaría con un 404.
- **Guardar la fecha de borrado en una columna:** se desactualiza en cuanto se regenera o se programa la pieza; derivarla es más barato y siempre es cierto.
- **Borrar solo las claves de `image_assets`:** dejaría en R2 las revisiones viejas y los intermedios, que son justamente lo que crece sin que nadie lo vea.
- **Borrar también la fila:** rompe el historial del Planificador («Usado ×N»), las campañas y la procedencia de los ángulos. Lo que cuesta es el byte, no la fila.

## Consecuencias

- El costo de R2 del generador tiene techo: lo vigente más 90 días.
- Una pieza usada como insumo de otra (fondo, producto o referencia elegidos en la pestaña «Piezas» del generador) deja de estar disponible cuando se borra: la pieza que la usó se ve igual, pero no se podrá **regenerar** con ese insumo (el error ya existe, `media.py`). Las diapositivas de carrusel no se ven afectadas: se copian a la carpeta de la pieza nueva.
- Una pieza borrada no es publicable (`UnpublishableReason.MEDIA_PURGED`), no muestra miniatura, no se ofrece en el selector «Piezas» y su descarga deja de existir.
- Revisión de la política: si un cliente pide recuperar piezas borradas más de una vez, o si el costo de R2 deja de importar, se revisan los 90 días.
