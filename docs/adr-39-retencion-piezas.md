# ADR 39 — Retención de las piezas: los archivos se borran de R2 a los 3 meses, con aviso

**Estado:** `[PROPUESTO — decisiones del responsable del ticket m-24828907, 2026-10-22; pendiente de firma del fundador]`
**Ticket:** m-24828907 («Piezas: aviso para descargar antes del borrado a los 3 meses»).
**Código:** `packages/api/src/qualify_api/creative/retention.py` (la regla), `creative/retention_job.py` (quién la corre), `qualify_shared/objects/gate.py` (`ObjectGate.delete_prefix`; `delete_gallery_media` por la enmienda del 2026-11-05, al final), migración `0076_piece_media_retention.py`.

## Contexto

Desde el 2026-10-06 cada archivo que genera el generador de contenido (imágenes, videos, pósters, voz, escenas intermedias de plantilla) vive **solo en R2**, bajo `t/{tenant}/generated/{draft_id}/r{revisión}/…`, sin fecha de caducidad. Con cada regeneración la revisión anterior se queda en R2 aunque ya ninguna fila apunte a ella. El almacenamiento crece sin techo.

El ticket pide borrar el contenido a los 3 meses y avisar antes para que el operador lo descargue.

Esto **no** es la política de `docs/backlog-retencion-datos-r2.md` (RET-01…08): aquella trata la media ganada de la ingesta (7–30 días, reglas de ciclo de vida de R2, sin código). Son planos distintos y no deben unificarse sin una decisión nueva.

## Decisión

1. **Fecha de borrado** = la más reciente de (a) la generación de la revisión actual (`MAX(image_assets.created_at)` de sus archivos en R2) y (b) el último evento de calendario que sale o salió (`scheduled`, `publishing`, `published`), **más 90 días**. No se guarda: se deriva cada vez de lo que ya está guardado, así no puede quedar desactualizada. Regenerar o volver a programar una pieza le da otros 90 días.

   **(c) Envío por WhatsApp (decisión del fundador, 2026-11-04, m-24945888).** Mandar una pieza a un cliente desde `/whatsapp` → Chats («Foto o menú» → «Tus piezas») cuenta como un uso, igual que publicarla: la fecha de borrado es también la más reciente con el último envío por WhatsApp de esa pieza, más 90 días. Tampoco se guarda: se deriva de las filas de `whatsapp_outbox` en estado `sent` cuya `attachment->>'draft_id'` es la pieza (migración 0123; `creative.retention.read_facts`). Un envío en cola o rechazado no cuenta. Una pieza generada hace 100 días y enviada hace 10 no se borra hasta dentro de 80. La foto que sale por WhatsApp es una copia en `t/{tenant}/whatsapp/outbound/…`, fuera de `PURGEABLE_ROOTS`: borrar la pieza no afecta un envío en cola, y esas copias no tienen todavía regla de retención propia.
2. **Aviso** en la app (galería `/drafts` y ficha `/drafts/{id}`) desde **15 días antes**: «Descarga esta pieza: se elimina el DD/MM/AAAA (en N días)», con el botón «Descargar» de m-24828908. Sin correo ni WhatsApp (fuera de alcance del ticket).
3. **Retención por calendario:** una pieza con un evento `scheduled` o `publishing` **nunca** se borra, sea cual sea la fecha (el publicador lee los bytes de R2 al publicar). Las piezas «recurrentes» con ocurrencias futuras se retienen; se borran 90 días después de su último evento. Los eventos `failed` y `cancelled` no retienen ni alargan nada.
4. **Qué se borra:** la **carpeta entera** de la pieza (`t/{tenant}/generated/{draft_id}/`), no solo las claves a las que apunta la base de datos: así salen también las revisiones viejas y los intermedios sin fila. La fila, su copy y su procedencia **se conservan**; `content_drafts.media_purged_at` marca «Contenido eliminado».
5. **Registro:** cada borrado (real o de prueba) queda en `content_draft_purges` (qué prefijo, cuántos objetos y bytes, fecha de vencimiento, cuándo), de solo inserción para la app, con RLS.
6. **Quién lo corre:** el servicio `calendar-worker` (ya siempre encendido en producción) lo corre al arrancar y cada 24 h, aislado: si falla, sigue publicando. Hay además un comando manual, `just piece-purge --tenant <uuid> [--execute]`.
7. **Borrado real desde el despliegue** (cambio del 2026-10-22, decisión del responsable del ticket: «que funcione tal cual la UI»): el job borra de R2 y marca la pieza sin activar nada. `QUALIFY_PIECE_PURGE_EXECUTE=0` en `.env.prod` es el interruptor de emergencia: con él solo registra qué borraría. El comando manual `just piece-purge` sigue siendo de prueba salvo `--execute`. El primer borrado posible es hacia el 2027-01-04 (90 días después de la primera pieza en R2).
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

## Apéndice — imágenes de revisión del Alta (m-24854328, 2026-10-28)

La foto propuesta como logo y las miniaturas comparten la raíz existente
`t/{tenant}/brand/{brand}/kept/{profile|post}/`. Las miniaturas se reducen a 480 px,
se guardan por hash de contenido y nunca requieren descargar media con el proveedor.

El borrado usa `ObjectGate.delete_brand_prefill_objects`: un manifiesto explícito,
validado por tenant, marca, tipo y hash antes de borrar el primer objeto. No se
amplía `PURGEABLE_ROOTS` ni se autoriza borrar prefijos generales del kit. Al aprobar
se conserva la foto que se promueve como logo y se borran las miniaturas; al empezar
de cero se incluyen ambas. Un fallo conserva el manifiesto en el documento para el
reintento diario. Una propuesta de más de 30 días cuyo borrador aún no fue adoptado
por registro también se limpia, bajo el mismo bloqueo que la aprobación. Los
archivos ya adoptados como logo no se borran por esta limpieza.

## Enmienda — borrar medios de la Galería (2026-11-05, épica m-24955913, ADR 47)

**Estado:** `[ADOPTADA por principal-architect el 2026-11-05 dentro de la decisión D4 firmada por el fundador ese día; detalle en docs/epica-galeria-medios-negocio.md §4.2]`.

**Por qué hace falta.** El fundador decidió (D4) que el dueño corte en Galería un video de su negocio y que el original y lo quitado **se borren de verdad** al confirmar. Los medios del negocio viven en R2 bajo `t/{tenant}/gallery/{media_id}/` (ADR 47). Este ADR solo permitía borrar por prefijo bajo `generated/`; esta enmienda es la decisión revisada que exigen `PURGEABLE_ROOTS` y el test que fija los métodos de la puerta.

**Decisión.**

1. `ObjectGate` gana **un** método, `delete_gallery_media(tenant_id, media_id: UUID)`. La puerta arma ella misma el prefijo `t/{tenant}/gallery/{media_id}/` desde el UUID — el que llama nunca pasa un texto —, lista lo que hay debajo y lo borra en lotes de 1.000. Idempotente: una carpeta vacía o ya borrada responde 0 objetos. Fuera de esa carpeta no borra nada.
2. **`PURGEABLE_ROOTS` no cambia** (`("generated/",)`): la regla de 90 días de este ADR no alcanza la Galería, y `delete_prefix` sigue sin poder vaciar `gallery/`. Los medios de la Galería no caducan: se quedan hasta que el dueño los quita o los corta.
3. **Una carpeta por medio.** Una parte cortada es un medio nuevo con carpeta propia e id determinista `uuid5(job_id, índice)`. Lo quitado **nunca se escribe**: solo se codifican los tramos que se quedan, así que borrar el original borra también lo quitado.
4. **Orden: escribir → confirmar en la base → borrar.** Nunca se borra un objeto antes de que la base diga que su reemplazo existe. Corte: partes en R2 → **una transacción** con las filas de las partes, la lápida del original (`business_media.deleted_at`) y el job en `parts_saved` → `delete_gallery_media(original)` → borrar la fila del original y el job en `done`. «Quitar»: lápida → `delete_gallery_media` → borrar la fila. Un fallo antes de la transacción deja el original intacto (y el job fallido borra las carpetas `uuid5(job_id, i)`, que se enumeran sin listar); un fallo después se termina en el reintento, porque los pasos que quedan son idempotentes.
5. **Sin huérfanos:** un conciliador diario del `media-worker` borra las carpetas de `t/{tenant}/gallery/` sin fila, sin lápida y sin job activo de más de 24 h, y termina las lápidas de más de 1 h. Cada borrado (carpetas, objetos, bytes) queda en `gallery_jobs.result` o en el log del conciliador.
6. **Las piezas no dependen de la Galería:** CM-6 copia a `generated/{draft_id}/` lo que una pieza usa, y esa copia sigue la regla de 90 días de este ADR. Borrar en Galería nunca rompe una pieza hecha.

**Alternativas descartadas.** (a) Sumar `gallery/` a `PURGEABLE_ROOTS`: `delete_prefix` recibe un texto libre y mezclaría dos políticas en un método. (b) Manifiesto explícito de llaves, como `delete_connection_objects`: una parte subida a medias o una portada sin fila no está en ningún manifiesto. (c) Reglas de ciclo de vida de R2: lo mismo que en la decisión original — no saben qué sigue en uso.

**Se reabre si** un dueño pide recuperar algo quitado más de una vez (lápida de 7 días antes de borrar), o si la Galería necesita carpetas compartidas entre medios.
