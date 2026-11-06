# Mudanza de las subidas del dueño a R2 (CM-9, m-24957283)

**Épica:** m-24955913 (`docs/epica-galeria-medios-negocio.md` §4.4 y §5 CM-9). **Decisión del
fundador:** 2026-11-05. **Código:** `packages/api/src/qualify_api/creative/owner_uploads.py`
(llaves, escritura única, lectores, mapa), `creative/local_media_move.py` (la copia única),
`Qualify/upload_store.py` (las pantallas), `Qualify/upload_route.py` (`/_upload/`), migración
`0138_local_media_moves.py`.

## 1. Qué cambia

Hasta hoy las fotos y videos de producto, las fotos de referencia del generador, los
documentos de la marca, los logos y fuentes del asistente de marca, las grabaciones de voz,
las referencias de reels y las ediciones traídas de Canva se guardaban **solo** en el volumen
local `qualify-prod_uploads` (`uploads/{negocio}/…`, `generated/{negocio}/…`), sin respaldo.

- **Lo nuevo va a R2** desde el despliegue de este cambio, escrito una sola vez.
- **Lo viejo se copia una vez**, a mano, con un comando (§4). Cada archivo queda en la tabla
  `local_media_moves`: llave vieja → llave en R2, tamaño, SHA-256, estado y procedencia.
- **Todo lector resuelve una llave vieja** por esa tabla cuando el archivo ya no está en el
  volumen: el generador (`R2ReadingMediaStore`), los adjuntos de WhatsApp
  (`ProductionBlobStore`), las vistas previas (`/_upload/…`) y las pantallas
  (`upload_store.read_upload`). Una llave vieja guardada en un JSON que no se reescribió sigue
  leyendo su archivo.

## 2. Prefijo elegido: `t/{negocio}/uploads/…`

| Opción | Qué es | Riesgo |
|---|---|---|
| **A. `t/{negocio}/uploads/…`** (elegida) | Bajo el bloqueo de `t/` (no borra, no sobrescribe) | Nada se puede borrar nunca: aceptable, ver abajo |
| B. `uploads/{negocio}/…` fuera de `t/`, como la Galería | Se podría borrar | Hay que construir un borrado con política que hoy nadie pidió, y una foto de producto quitada por error se pierde |

**Por qué A:** son los originales del dueño y el objetivo de CM-9 es no perderlos. El catálogo
nunca borra el archivo al quitar una foto (la fila se va, el objeto queda: procedencia de las
piezas ya hechas), así que nada necesita borrar. Cada llave lleva un `uuid4` nuevo
(`new_upload_key`) y la copia usa un mapa 1:1 (`uploads/{n}/{resto}` → `t/{n}/uploads/{resto}`),
así que **ninguna escritura choca con un objeto de su mismo nombre**; `put_once` igual mira
antes de escribir y nunca sobrescribe. Las piezas viejas del volumen (`generated/{n}/…`) van a
`t/{n}/generated-local/…`, **fuera** de `t/{n}/generated/`, que la regla de 90 días de ADR 39
vacía: nunca tuvieron una decisión de retención y no se les inventa una aquí.

Las ediciones nuevas de Canva van con los demás archivos de su pieza
(`t/{n}/generated/{pieza}/canva-…`), donde las cubre ADR 39 como al resto de la pieza.

## 3. Inventario de llaves locales

**Columnas de una llave entera — se reescriben a la llave de R2** al verificar cada archivo
(`REWRITE_COLUMNS`, en la misma transacción que deja la fila del mapa en `verified`):

| Tabla.columna | Quién escribía una llave local |
|---|---|
| `product_media.object_key` | Catálogo (`catalog/service.py`) |
| `content_briefs.source_media_key` | Foto subida al crear una pieza (`creative_state.handle_photo_upload`) |
| `content_drafts.preview_key` | Piezas anteriores al 2026-10-06 (`generated/…`) |
| `brand_kits.logo_asset_key`, `template_asset_key`, `reference_image_keys` (arreglo) | Identidad de marca de antes de que el asistente guardara en R2 |
| `brand_kit_assets.object_key` | Archivos del asistente de marca |
| `brand_voice_clones.sample_object_key`, `preview_object_key` | Laboratorio de voz |
| `image_assets.object_key`, `mask_object_key` | Piezas anteriores al 2026-10-06 |
| `canva_design_links.source_object_key`, `exported_object_key` | Canva (exportaba a `generated/…`) |

**Campos JSON y texto — no se reescriben, resuelve el mapa:** `content_briefs.media`
(`background_key`, `product_keys`, `avatar_image_key`, `brand_logo_key`,
`brand_logo_reference_keys`, `brand_element_keys`, `slides[].object_key`,
`slides[].reference_video_key`, `reference_video_key`, `clip_first_frame_key`,
`clip_last_frame_key`, `clip_image_keys`, `clip_video_keys`, `clip_audio_keys`),
`content_briefs.video_plan`, `template_runs.props` / `outputs`, `creative_pipeline_steps`,
`creative_vendor_tasks.context`, `image_assets.params`, `whatsapp_outbox.attachment`, y el estado
de las pestañas abiertas de Reflex (`.states`), que guarda llaves de subidas a medio usar.

**El conteo por tabla y campo lo da el propio comando**: el `--dry-run` barre **todas** las
columnas `text`, `varchar`, `json`, `jsonb` y arreglos de toda tabla con `tenant_id` y, por
negocio, dice en cuáles hay llaves locales, cuántas filas, cuántas llaves distintas, cuántas
no tienen archivo y si esa columna se reescribe o la resuelve el mapa. Así una columna que la
lista de arriba no conoce aparece igual. El barrido de producción va al PR antes del `--apply`.

**Quedan fuera:** las salas de espera (`uploads/{n}/gallery-staging/`, `catalog_staging/`), que
su propio flujo vacía en minutos, y la tabla `gallery_jobs.staged_path`.

## 4. Cómo se corre en producción (el fundador, con su visto en cada paso)

El comando corre en un contenedor `api` de un solo uso, que ya monta el volumen `uploads` en
`/data/uploaded_files` y tiene las credenciales de R2 y de la base. **No corre en el despliegue.**

```bash
ssh -t deploy@<IP> 'cd /opt/qualify/current && docker compose --env-file /opt/qualify/.env.prod \
  -f deploy/docker-compose.prod.yml run --rm api \
  python -m qualify_api.creative.local_media_move --all-tenants'               # 1. ensayo
```

1. **Ensayo (`--dry-run`, lo que hace sin opciones):** no escribe nada. Por negocio: archivos y
   bytes que copiaría, los ya copiados y el inventario. Lista los archivos sin negocio
   (`UNOWNED`), que nunca se copian ni se borran. Pegar la salida en el PR.
2. **Copia (`--apply`):** copia, verifica (tamaño + SHA-256 leído de R2) y mapea archivo por
   archivo. Se puede cortar y relanzar: no repite ni salta nada. Un `CONFLICT` (la llave de R2
   ya tenía otro archivo) no se sobrescribe ni se mapea: se revisa a mano. Un `FAILED` (R2 caído)
   se reintenta relanzando. Se puede empezar por un negocio: `--tenant <uuid>`.
3. **Comprobar** en la app que las fotos de producto y las piezas viejas se ven y se publican.
4. **Borrado local (`--delete-local`), en una corrida aparte y solo con el visto del fundador:**
   borra un archivo del volumen solo si su fila está `verified` y **tanto** el archivo local
   **como** el objeto de R2 siguen teniendo el tamaño y el SHA-256 de la fila. Nada se borra en
   R2, nunca. `--apply` y `--delete-local` no se pueden pedir juntos.

Memoria: el archivo se lee de disco en trozos de 1 MiB para el SHA-256 y se sube desde el disco
(un solo PUT por archivo, tope de 300 MB de `ObjectGate`); la verificación lee R2 en trozos.

## 5. Exposición de `/_upload/`

`/_upload/<llave>` servía los archivos del volumen a quien tuviera la ruta. Ahora sirve **esos
mismos** archivos desde R2 cuando ya no están en el volumen, y solo `t/{n}/uploads/…` y
`t/{n}/generated-local/…`: la identidad de marca, las piezas y los objetos de las conexiones
siguen detrás de los tokens de `/r2media`. Las cabeceras son las de Reflex para subidas
(`nosniff`; descarga salvo un PDF). Los videos se sirven por rangos; nada se guarda entero en
memoria (el contenedor `reflex` tiene 768 MiB con FFmpeg dentro).

## 6. Reversa

`alembic downgrade 0137` borra la tabla del mapa. Solo es seguro **antes** del `--delete-local`:
después, una llave vieja guardada en un JSON ya no tendría ni archivo ni mapa (los objetos de R2
siguen ahí). El código anterior lee las llaves viejas del volumen, así que revertir el código
antes del borrado local no pierde nada; las subidas hechas en R2 en el medio solo se verían
con este código.
