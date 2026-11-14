# Subidas del dueño que nadie usa en R2 — opciones para decidir

**Ticket:** m-25026465 · **Estado:** `[PROPUESTO 2026-11-13 — pendiente de la decisión del fundador]` ·
**Origen:** la revisión de código del PR #643 (m-25026384, «Subir foto o video» del Planificador) ·
**Formato:** `qualify-business-decisions`.

Etiquetas de evidencia: `[V]` código o datos leídos en disco, una lectura de producción o la
documentación oficial del proveedor con fecha; `[S]` derivado de un `[V]` con una cuenta no medida;
`[H]` estimación. Un número calculado hereda la etiqueta más débil. `[F]` = decisión del fundador.

**Esta investigación no cambió nada:** no se borró ni escribió ningún objeto en R2, no se tocó la
base de producción ni Cloudflare, y no se escribió código de la aplicación.

## 0. Decisión del fundador

Pendiente. La pregunta cerrada está en §9.

## 1. El marco

**La pregunta:** ¿qué hacemos con los archivos que el dueño sube y que después no usa — los elige
y no guarda, los cambia por otro, o la app solo los usa de paso?

**Qué buscamos esta vez:** que el costo de guardar tenga techo **sin arriesgar ningún original del
dueño**. No es una decisión de caja: hoy esto cuesta cero (§4).

**Para el dueño del negocio:** no ve nada distinto en ninguna opción mientras todo salga bien. Lo
único que le puede pasar es malo: que desaparezca una foto que sí estaba usando (opción D), o que
«Guardar» tarde más con un video pesado (opción B).

**Restricciones ya firmadas `[F]`:**

- El bucket de producción (`qualify-artifacts`) tiene una regla de bloqueo sobre `t/` que rechaza
  borrar y sobrescribir, y el fundador la mantiene (ADR 39, enmiendas del 2026-11-06).
- Las subidas del dueño van a `t/{negocio}/uploads/…` **a propósito bajo ese bloqueo**: «nada se
  puede borrar nunca: aceptable» (`docs/mudanza-subidas-r2.md` §2, decisión del 2026-11-05). Las
  opciones B y C **reabren esa decisión solo para lo que todavía no se guardó**; lo guardado sigue
  bajo `t/`. La opción D la reabre entera.
- Un solo Postgres; ningún servicio, runtime ni proveedor nuevo sin tabla de opciones; todo worker
  idempotente; local y producción comparten el bucket y los agentes nunca escriben ni borran en R2.

## 2. Qué flujos guardan un archivo antes de que algo lo use

Todos escriben con `owner_uploads.put_once` (la mayoría por `Qualify/upload_store.py`), con una
llave nueva por subida: `t/{negocio}/uploads/[{carpeta}/]{uuid4}_{nombre}` (el catálogo usa
`{uuid4}.{ext}`). La llave queda **solo en
el estado de la pantalla** (Reflex, guardado en disco en `/app/.states`, sobrevive a un despliegue)
hasta que el dueño guarda. `[V]` — leído en el código de `main` (a6667370).

| # | Pantalla | Quién escribe | Carpeta | Cuándo una fila apunta al archivo | Cuándo queda sin uso |
|---|---|---|---|---|---|
| 1 | «Crear publicación» (`/create`): fondo, productos, avatar, referencia, fotos de diapositiva, clips de imagen, video y audio, editor de partes | `CreativeState._save_uploads` (lo llaman 13 manejadores; 12 están conectados a una pantalla). `handle_photo_upload`, del formulario anterior hoy sin pantalla, escribe aparte | (ninguna) | Al tocar «Crear»: `content_briefs.media` y `content_briefs.source_media_key` | Quitar o cambiar un archivo, salir sin crear, «nueva publicación», cambiar de tipo de pieza, cerrar el editor de partes a medias. Además: si falla el archivo N de una subida de varios, los N−1 anteriores ya están en R2 y se pierden sus llaves |
| 2 | Planificador › «Subir foto o video» | `PlannerState._store_own_upload` | `planner/` | Al tocar «Guardar y continuar»: `content_briefs.source_media_key`, `image_assets.object_key` | «Cambiar archivo», elegir y no guardar, guardado rechazado |
| 3 | «Hacer uno parecido» (Ideas para tus reels) | `reel_replication.import_reference` | (ninguna) | Al tocar «Crear» en `/create` | Cada toque que no termina en «Crear». Un segundo toque sobre el mismo reel escribe otra vez su referencia (un corte de 5 s sin audio) |
| 4 | Referencia de Pinterest | `pinterest_reference.import_pin_reference` | `pinterest/` | Al tocar «Crear» | Salir, cambiarla, «La referencia no se aplicó» |
| 5 | Asistente de marca: logo, versiones, elementos, fuentes | `BrandWizardState._stage_logo_file` | `logo/…`, `font/…` | **Nunca.** Al guardar, `brand_finish` copia los bytes a `t/{negocio}/brand/{marca}/…` y la fila apunta a la copia | **Siempre**: cada subida deja un objeto que ninguna fila nombra |
| 6 | Documentos de la marca (brief, brandboard) | `BrandDocumentState._stage` | `brief/`, `brandboard/` | **Nunca.** Se lee una vez para analizarlo | **Siempre** |
| 7 | Muestra de voz | `VoiceLabState.handle_sample_upload` | (ninguna) | **Nunca.** Al clonar se guarda un WAV recodificado en `brand/{marca}/voice/` | **Siempre**: la grabación original del dueño queda además de la copia |
| 8 | Catálogo: foto o video de producto | `CatalogService.add_media` | `catalog/{producto}/` | En la misma llamada (`product_media.object_key`) | Al quitar la foto: `remove_media` borra la fila y deja el archivo, por diseño. Y si falla el guardado de la fila justo después de escribir el archivo (raro) |

**No dejan nada en R2 al abandonar** `[V]`: el formulario del Catálogo y la Galería esperan en el
**disco del servidor** (`uploads/{negocio}/catalog_staging/` y `gallery-staging/`), se limpian solos
a las 24 h y solo escriben en R2 junto con su fila. La Galería vive fuera de `t/`
(`gallery/{negocio}/…`) y tiene un conciliador diario que borra lo que quedó sin fila.

**Qué vuelve inalcanzable una subida hoy**, en resumen:

1. La llave vivía solo en el estado de la pantalla y nunca llegó a una fila (flujos 1–4).
2. El flujo usa la subida de paso y guarda otra copia (flujos 5–7): huérfana al 100 %.
3. La fila que la nombraba se borra o se reescribe y el archivo queda (quitar una foto del
   catálogo; `parts_plan` reescribe `content_briefs.media`; regenerar reemplaza `image_assets.params`).
4. **Ningún código puede borrar bajo `uploads/`**: `ObjectGate` no tiene método para esa raíz y
   `PURGEABLE_ROOTS` es solo `("generated/",)`. Y aunque lo tuviera, el bucket lo rechazaría.

Nada se deduplica: la misma foto subida dos veces son dos objetos (solo la Galería compara por SHA-256).

## 3. Qué puede apuntar a una subida

Esto es lo que una purga tendría que revisar antes de borrar un solo objeto (opción D). `[V]` salvo
lo marcado.

| Tabla.columna | Tipo | Qué guarda |
|---|---|---|
| `product_media.object_key` | texto | La llave entera (catálogo) |
| `content_briefs.source_media_key` | texto | La llave entera (también puede ser de Galería o de «Publicar») |
| `content_briefs.media` | JSON | Llaves guardadas dentro del JSON: `background_key`, `product_keys[]`, `avatar_image_key`, `brand_logo_key`, `brand_logo_reference_keys[]`, `brand_element_keys[]`, `reference_video_key`, `clip_first_frame_key`, `clip_last_frame_key`, `clip_image_keys[]`, `clip_video_keys[]`, `clip_audio_keys[]`, `slides[].object_key`, `slides[].reference_video_key`, `source_pins[].image_key`, y los `clip_*` de cada parte |
| `content_briefs.video_plan`, `creative_angles.brief` | JSON | Un brief entero o su `source_media_key` |
| `image_assets.object_key`, `.media_url`, `.mask_object_key` | texto | La llave entera: lo que sube el flujo 2 (Planificador) queda aquí al guardar |
| `content_drafts.preview_key` | texto | La llave entera: la portada de una pieza propia cuando es una foto subida |
| `image_assets.params` | JSON | Procedencia: `sources[].source_key`, `from_key`, `thumbnail_key` |
| `canva_design_links.source_object_key`, `.exported_object_key` | texto | `[S]` — hoy guardan llaves de piezas; están en `REWRITE_COLUMNS` por las llaves viejas |
| `whatsapp_outbox.attachment` | JSON | Procedencia: `source_key` |
| `creative_pipeline_steps.request` / `.result` | JSON | Llaves dentro del JSON; **una parte va como JSON dentro de un texto** (`rendered_prompt.volatile_suffix`), que una búsqueda campo por campo no ve. Si lleva llaves: sin verificar |
| `template_runs.props` / `.outputs`, `creative_vendor_tasks.context` | JSON | `[S]` — listadas en `docs/mudanza-subidas-r2.md` §3; contenido no leído |
| `brand_kits.*`, `brand_kit_assets.object_key`, `brand_voice_clones.*` | texto / arreglo | Hoy guardan llaves de `brand/…`; una llave de `uploads/` solo si la copia única del volumen la reescribió |
| `local_media_moves.r2_key` | texto | El mapa llave vieja → llave de R2: una llave vieja `uploads/{negocio}/…` en cualquier JSON cuenta como referencia a su `r2_key` |
| El estado de las pantallas abiertas (`/app/.states`) | fuera de Postgres | Las llaves de subidas a medio usar |

**Lo que ya existe y se puede reusar** `[V]`: `inventory()` en
`packages/api/src/qualify_api/creative/local_media_move.py` barre **todas** las columnas de texto,
JSON y arreglo de toda tabla con `tenant_id`, sin lista escrita a mano. Hoy busca llaves viejas
(`uploads/{negocio}/`); para las de R2 habría que cambiarle el patrón. Las otras listas del repo
(`_PROTECTED_KEYS` de la purga de conexiones, `referenced_keys` del Planificador) están escritas a
mano y ninguna coincide con esta tabla: a cada una le falta alguna columna. Por eso la tabla de
arriba es una guía para leer, no la lista que usaría una purga.

**Lo que un barrido puede no ver:**

- **Una llave dentro de un JSON guardado como texto.** `inventory()` sí encuentra la fila (busca
  con `LIKE` sobre el texto de la columna) y la cuenta como «incrustada», pero no extrae la llave;
  y si la misma fila tiene además una llave entera, la incrustada ni se cuenta. Una purga tendría
  que preguntar al revés: por cada objeto candidato, si su llave aparece en algún texto.
- **El estado de las pantallas abiertas**, que no está en Postgres.
- **Una columna nueva**, si se usa una lista a mano en vez del barrido por esquema.
- **Una tabla sin `tenant_id`**: `inventory()` no las mira.

## 4. Cuánto hay

**Medición del 2026-11-13** `[V]`: un listado de solo lectura de `t/` por la puerta existente
(`R2ObjectStore.list_prefix`), que suma objetos y bytes sin imprimir llaves ni negocios (Apéndice A).

| Bajo `t/{negocio}/…` | Objetos | Tamaño |
|---|---|---|
| `media/` (lo que sale por «Publicar» y el Planificador) | 111 | 1.439,7 MiB |
| `generated/` (piezas; ADR 39) | 452 | 351,1 MiB |
| `gallery/` (bajo `t/`; `[S]` Galería anterior al cambio del 2026-11-06) | 47 | 78,2 MiB |
| `stock/` | 76 | 67,3 MiB |
| **`uploads/`** | **112** | **44,2 MiB** |
| `creative-refs/`, `brand/`, `whatsapp/` | 80 | 51,8 MiB |
| **Total bajo `t/`** | **878** | **≈ 2,0 GiB** |

`uploads/` por carpeta: sin carpeta 32 objetos / 23,0 MiB · `logo/` 29 / 14,2 MiB · `catalog/` 23 /
3,8 MiB · `pinterest/` 26 / 3,2 MiB · `brief/` 2 / 0,2 MiB. Por tipo: 73 imágenes (21,7 MiB), 25
videos (13,2 MiB), 14 otros. Todo es de noviembre de 2026; 7 negocios tienen subidas. Todavía no
hay carpeta `planner/`: el PR #643 entró a `main` el mismo 2026-11-13.

**Cuántos son huérfanos:** no se puede dar el número exacto sin cruzar con la base de producción,
y eso no se hizo. Lo que sí se sabe:

- **Como máximo `[V]`: 112 objetos y 44,2 MiB** — todo `uploads/`.
- **Orden de magnitud `[S]`: decenas de objetos y decenas de MiB.** `logo/` y `brief/` (31 objetos,
  14,4 MiB) son de paso por diseño; `catalog/` (23) nace con su fila; el resto depende de cuántas
  veces se abandonó o cambió un archivo.
- El número incluye **las pruebas locales**: desarrollo y producción comparten el bucket (los 25
  «negocios» bajo `t/` no son 25 clientes). Tampoco se sabe desde aquí si la copia única del
  volumen (`--apply`) ya corrió; si corrió, hasta 48 objetos / 18,8 MB de los 112 vienen de ella.

**Cuánto cuesta:** R2 cobra US$0,015 por GB al mes, los primeros 10 GB no se cobran y borrar es
gratis `[V]` (precios de Cloudflare, consultados el 2026-11-13). Los 44,2 MiB valdrían US$0,0007 al
mes `[S]`; hoy, **cero**: todo `t/` pesa 2,0 GiB. (No se listó lo que está fuera de `t/`.)

**Hasta dónde puede crecer `[H]`:** el Planificador acepta videos de hasta 300 MB. Si 25 negocios
descartaran cada uno cuatro videos de 50 MB al mes, serían 5 GB al mes: 60 GB en un año, unos
US$0,75 al mes. **El dinero no justifica construir nada durante al menos un año.** Lo que sí puede
justificarlo: no conservar para siempre lo que el dueño descartó (incluida la grabación original de
su voz, flujo 7), y que un cliente pida borrar lo suyo — algo que hoy no se puede cumplir para
**nada** bajo `t/`, se use o no (eso es m-24973441, no este documento).

## 5. Qué permiten el bucket y ADR 39

**El bloqueo de `t/`.**

- Rechaza borrar y sobrescribir `[V]` (ADR 39, enmiendas del 2026-11-06; lo confirmó el PR #503).
- **Su condición nunca se anotó** `[V]`: no se sabe si es indefinida, por antigüedad («N días desde
  la subida») o hasta una fecha. No está en el repo; vive en Cloudflare. Cómo leerla sin cambiar
  nada: Apéndice A.
- Según Cloudflare `[V]` (consultado el 2026-11-13): las reglas de bloqueo se definen por prefijo
  literal, con tres condiciones posibles (antigüedad, fecha, indefinida), y **mandan sobre las
  reglas de ciclo de vida**: un objeto bloqueado no lo borra ninguna regla de ciclo de vida hasta
  que el bloqueo lo suelta.

**¿Puede una regla de ciclo de vida limpiar sin código?**

- **Bajo `t/`, no.** Primero, por el bloqueo. Segundo, porque las reglas filtran por prefijo literal
  y el negocio va en medio de la llave (`t/{negocio}/uploads/`): haría falta una regla por negocio.
  Tercero, porque borran por edad sin mirar si una fila usa el archivo: una foto de producto de hace
  un año se iría igual que un huérfano (el mismo motivo por el que ADR 39 las descartó para las piezas).
- **En un prefijo propio fuera de `t/`, sí**: una regla «borrar a los N días» sobre, por ejemplo,
  `upload-staging/`. Cloudflare borra normalmente dentro de las 24 h siguientes al vencimiento `[V]`. Es el
  mismo camino que ya tomaron la Galería (`gallery/`), los cortes de reels (`reel-windows/`) y la
  biblioteca por temporada (`seasonal/`) para poder borrar.

**ADR 39.** La regla de 90 días solo vacía `generated/`. `uploads/` quedó fuera a propósito en el
apéndice de CM-9 («nadie las borra»), y las piezas `own_media` (lo que sale del flujo 2) están
exentas por la enmienda del 2026-11-13. Sumar una raíz a `PURGEABLE_ROOTS` o un método de borrado a
la puerta es, por ese ADR, una decisión revisada: un test fija el conjunto de métodos de `ObjectGate`.

## 6. Opciones

| | Qué es | Para el dueño | Costo | Esfuerzo `[H]` | ¿Se deshace? | Riesgo principal |
|---|---|---|---|---|---|---|
| **A. Dejar como está y medir** | No se construye nada. Se repite la medición de §4 una vez al mes y se fija un umbral para reabrir | Nada cambia | US$0 hoy; en el peor caso `[H]` US$0,75 al mes dentro de un año | Ninguno ahora; medio día si se quiere la medición como comando | Sí, del todo | Lo descartado se sigue acumulando bajo `t/`, donde nada se puede borrar mientras exista el bloqueo |
| **B. Sala de espera en el disco del servidor** | Lo que se elige espera en el volumen `uploads` (como ya hacen Catálogo y Galería) y solo sube a R2 al guardar. Una limpieza borra del disco lo que lleva más de 24 h sin guardarse | Con un video pesado la espera pasa de «al elegir» a «al guardar». Un formulario que queda abierto más de 24 h pierde su archivo y hay que elegirlo otra vez | US$0. Sin Cloudflare, sin servicio nuevo | 3–5 días: los flujos 1–7 de §2, el más grande en `creative_state.py` | Sí: se vuelve al código de hoy; nada se pierde en R2 | Tocar el flujo de «Crear», que hoy funciona. Un archivo en espera se pierde si el disco falla antes de guardar (el dueño lo vuelve a subir) |
| **C. Sala de espera en R2 fuera de `t/` + regla de ciclo de vida** | Lo que se elige va a un prefijo nuevo (`upload-staging/{negocio}/…`); al guardar se copia a `t/{negocio}/uploads/…`; Cloudflare borra solo lo que lleve 7 días en la sala | Un formulario que queda abierto más de 7 días pierde su archivo y hay que elegirlo otra vez | US$0. Una regla nueva en Cloudflare, que hoy no está versionada en el repo (m-24828505) | 4–6 días: lo de B más una raíz y métodos nuevos en la puerta (enmienda a ADR 39) y la regla en Cloudflare, que pone el fundador | El código sí; lo que la regla borró, no | La regla vive fuera del repo: si alguien la cambia o la apunta mal, borra sin avisar |
| **D. Purga programada bajo `t/{negocio}/uploads/`** | Un proceso diario lista `uploads/`, cruza con todas las columnas de §3 y borra lo que nadie nombra desde hace N días | Nada si acierta. **Si se equivoca, pierde un original**: una publicación programada falla o una foto desaparece de su catálogo | US$0 en R2 | 5–8 días, más cambiar el bloqueo de `t/` en producción | **No**: lo borrado no vuelve; R2 es la única copia (los respaldos fuera del servidor, m-24824122, siguen en Backlog) | Un falso huérfano: una llave que solo vive en una pantalla abierta, o dentro de un texto que el barrido no extrajo |

**Lo que ninguna de las tres primeras resuelve:** los objetos que ya están (como máximo 112) se
quedan donde están. Solo D los borra, y solo si antes cambia el bloqueo.

**«Borrar al tocar Cambiar archivo»** no es una opción por sí sola. Bajo `t/` el bucket lo rechaza,
y no cubre al que cierra la pestaña. Dentro de B es gratis (se borra el archivo del disco al
cambiarlo); dentro de C es una llamada más (borrar el objeto de la sala); la limpieza por edad
sigue haciendo falta para lo abandonado.

**Detalle de B.** Es lo más simple que ya hay en casa: `catalog_staging/` tiene su limpieza a 24 h
(`_sweep_staging` en `Qualify/catalog_state.py`) y `gallery-staging/` la suya en el conciliador del
`media-worker`. Los tres flujos de paso (5–7) ya copian o recodifican al guardar, así que solo
cambian de dónde leen. Los flujos 1–4 pasarían a subir a R2 en «Crear» / «Guardar y continuar». La
vista previa de lo que espera se serviría por `/_upload/`, como antes de CM-9 (sin verificar: la
sala del Catálogo hoy no se sirve a nadie). Pendiente antes de construir: medir cuánto tarda
«Guardar» con un video de 300 MB (servidor → R2), y dos textos para el dueño que propone
`ux-designer` `[H]`: la espera («Subiendo tu video… 40 %. No cierres esta pantalla») y el archivo
que venció («Esta foto ya no está guardada. Elígela otra vez para seguir.»). No hay evidencia de
cuánto pesan los videos que suben los dueños.

**Detalle de D.** Antes de escribir una línea necesita tres decisiones del fundador: (1) cambiar el
bloqueo de `t/` —quitarlo o pasarlo a «por antigüedad»—, que afecta a **todo** lo que hay bajo
`t/` (identidad de marca, piezas, lo publicado), no solo a las subidas; (2) una raíz o un método de
borrado nuevo en la puerta (ADR 39); (3) cuántos días de gracia. Y el barrido tendría que cubrir
también el estado de las pantallas abiertas, que no está en Postgres.

## 7. Tipo de puerta

- **A, B y C son de dos vías:** se prueban, se miden y se vuelven atrás sin perder nada guardado.
- **D es de una vía:** borra originales. Si se elige, va con ensayo sin borrar (`--dry-run`) en
  producción primero, lista de lo que borraría revisada por el fundador, y días de gracia largos.

**Si D sale mal:**

1. Borra una foto que una pieza programada usa → la publicación falla. Señal temprana: el ensayo
   lista llaves que aparecen en `content_briefs.media`. Qué hacemos: no ejecutar hasta que el
   ensayo dé cero durante una semana.
2. Se cambia el bloqueo para la purga y otro error borra identidad de marca o lo publicado.
   Señal: ninguna antes del daño. Qué hacemos: no quitar el bloqueo; como mucho, pasarlo a «por
   antigüedad».
3. Una columna nueva guarda llaves y el barrido no se entera. Señal: ninguna. Qué hacemos: barrido
   por esquema (`inventory()`), nunca lista a mano.

## 8. Recomendación

**A — dejar como está y medir.** El objetivo es que el costo tenga techo sin arriesgar originales, y
el techo está lejos: todo `uploads/` pesa 44 MiB y cuesta cero. Cualquier cosa que se construya hoy
cuesta más que años de almacenamiento, y el único borrado de verdad (D) no se puede hacer bajo el
bloqueo y es el único que puede perder un archivo del dueño.

**Lo que cuesta equivocarse:** lo descartado se acumula bajo `t/` sin poder borrarse hasta que se
decida el bloqueo (m-24973441). En el peor caso `[H]`, menos de US$1 al mes dentro de un año.

**La reabrimos si** pasa cualquiera de estas, medido el día 15 de cada mes desde el **2026-12-15**:

- `uploads/` supera **5 GiB**, o crece más de **1 GiB en un mes**;
- un cliente pide que se borre algo que subió;
- se decide m-24973441 (el bloqueo de `t/`), que cambia lo que es posible.

**Si se reabre, el siguiente paso es B**, no C ni D: no agrega nada fuera del repo y repite un
patrón que ya funciona dos veces. Y hasta entonces, una sola regla hacia adelante, sin tocar lo que
hay: **un flujo nuevo que suba antes de guardar usa la sala de espera en disco**, no `t/…/uploads/`.

**Validación más barata:** repetir el listado del Apéndice A el 2026-12-15, ya con un mes de
«Subir foto o video» en producción, y comparar con la tabla de §4.

## 9. Necesito que decidas

1. **¿A, B, C o D?** (Recomendado: A.)
2. Si es A: **¿aceptas la regla hacia adelante** (flujo nuevo → sala de espera en disco) **y el
   umbral de 5 GiB / 1 GiB al mes?**
3. Aparte de la opción: **¿lees tú la regla de bloqueo en Cloudflare** (Apéndice A, punto 1) para
   anotar su condición en ADR 39? Es solo lectura y destraba m-24973441.

## Hallazgos aparte (no se arreglan aquí)

- **`t/{negocio}/media/` pesa 1,41 GiB: el 71 % de `t/`.** Es lo que sale por «Publicar» y el
  Planificador. Lo publicado desde «Publicar» no vence, por decisión del fundador (ADR 39, enmienda
  del 2026-11-13); para el resto de `media/` no hay regla de limpieza firmada
  (`docs/backlog-retencion-datos-r2.md`, RET-06), y todo está bajo el bloqueo. Si algún día pesa el
  almacenamiento, pesa ahí, no en `uploads/`.
- **«Hacer uno parecido» escribe una referencia nueva en cada toque** (un corte de 5 s sin audio),
  también sobre el mismo reel: no reusa la anterior.
- **Una subida de varios archivos que falla a la mitad pierde las llaves de los que ya subieron**
  (`_save_uploads` devuelve una lista vacía).
- **Guardar la identidad de marca puede dejar copias sin fila bajo `brand/`** cuando un guardado
  falla a medias (`brand_finish`); está fuera de `uploads/`.
- **Desarrollo y producción comparten el bucket** (m-24824121, en Backlog): toda medición de R2
  mezcla pruebas con clientes.

## Apéndice A — comandos de solo lectura

**1. Leer las reglas del bucket** (no cambia nada). En Cloudflare: R2 → `qualify-artifacts` →
Settings → «Bucket lock rules» y «Object lifecycle rules». O con Wrangler:

```bash
npx wrangler r2 bucket lock list qualify-artifacts
npx wrangler r2 bucket lifecycle list qualify-artifacts
```

Anotar de cada regla: prefijo y condición (indefinida, días, fecha).

**2. Repetir la medición de §4.** Con las cuatro variables `QUALIFY_R2_*` en el entorno; solo llama
a `list_prefix` (un `ListObjectsV2` por cada 1.000 objetos) e imprime las sumas por raíz y por
carpeta de `uploads/` (las cuentas por tipo, por mes y de negocios de §4 salieron de una variante
más larga del mismo listado):

```python
from collections import defaultdict

from qualify_shared.objects.config import R2Settings
from qualify_shared.objects.s3 import R2ObjectStore

totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
for obj in R2ObjectStore(R2Settings.from_env()).list_prefix("t/"):
    parts = obj.key.split("/")
    if len(parts) < 4:
        continue
    name = parts[2] if parts[2] != "uploads" else "uploads/" + (parts[3] if len(parts) > 4 else "")
    totals[name][0] += 1
    totals[name][1] += obj.size
for name, (count, size) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
    print(f"{name:<28} {count:>6} objetos {size / 1_048_576:>10.1f} MiB")
```

**3. El número exacto de huérfanos** no tiene comando hoy. Haría falta un ensayo de solo lectura
que cruce el listado con `inventory()` (§3) cambiándole el patrón a `t/{negocio}/uploads/`, corrido
dentro del contenedor `api` de producción como el ensayo de `docs/mudanza-subidas-r2.md` §4. Es
código nuevo: se hace solo si el fundador quiere el número antes de decidir.

## Apéndice B — lo que no se verificó

- La condición de la regla de bloqueo y si hay reglas de ciclo de vida en el bucket.
- El número exacto de huérfanos (falta el cruce con la base de producción).
- Si la copia única del volumen (`--apply`) ya corrió en producción.
- El contenido de `template_runs.props` / `.outputs` y `creative_vendor_tasks.context`, y si
  `rendered_prompt.volatile_suffix` lleva llaves.
- Cuánto vive el estado de una pantalla abierta antes de descartarse.
- Lo que pesa el bucket fuera de `t/` (`gallery/`, `public/`, `seasonal/`, `reel-windows/`).
- Los tiempos de «Guardar» con un video de 300 MB para la opción B.
