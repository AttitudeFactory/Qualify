# Plan: personajes del negocio (m-25129385)

Estado: **construido** (rama sin PR todavía). Épica m-25026566. Rama `feat/m-25129385-personajes` desde `origin/main`
`f9e784b7` (planeado sobre la migración `0186`). La `0187` la tomó PR #842 (`subscription_payments`), así que esta tabla es la **`0188`**, que baja de la `0187`.

## Decisiones (2026-11-26, «creacion de tickets» y Deivid)

Estas decisiones mandan sobre el plan de abajo y las preguntas del final.

- **3 opciones** por ronda.
- **Dibujar no descuenta creaciones.** El gasto queda en los eventos de uso y en el tope mensual en dólares.
- **El dueño elige el estilo**, animado o realista. `style` es un dato abierto: lo valida el servicio y la tabla no lo cierra con un CHECK. La columna `source` vale `drawn` y deja espacio para un personaje que el dueño ya creó.
- **No se borra un personaje que está en un video sin aprobar** (`in_use`).
- **2 rondas al día** por negocio y máximo 5 guardados.
- Se guarda **la fecha del dibujo** (`drawn_at`) para el riesgo de los 30 días. Se mide en m-25128784.
- **Interruptor único**: `QUALIFY_CLIP_CHARACTER_SCENE` cubre la escena, los personajes y «Sugerir con IA». Sigue apagado.
- **Los dibujos corren en `creative-worker`**, como los stickers.

## Plan en 5 líneas

1. **Tabla `business_characters` (migración 0188)**: una fila por dibujo pedido. El dueño guarda una de las opciones y las demás se descartan. RLS completo, sin `DELETE`, y `creative_jobs` gana el tipo `business_character`. Baja limpio.
2. **Servicio `qualify_api.creative.business_characters`**: valida el interruptor, la descripción, el tope de 5 y el tope diario bajo el candado del negocio, y abre una ronda de forma idempotente (`request_key`).
3. **Dibujo**: un trabajo de `creative-worker` por opción en la piscina `byteplus:seedream-5-0-pro`. Seedream 5.0 pro va a 1080×1920 con el prompt `business-character-v1`, que sale de `avatar-escena-v1`. La guarda de precio usa la tabla `v10` y el tope mensual del negocio. El evento de uso queda con el costo real. La imagen se guarda byte a byte en R2, con 3 reintentos.
4. **Elegir y guardar**: el dueño elige una opción con un nombre y esa queda `saved`. Las demás quedan `discarded` y sus archivos se borran de R2. Se puede renombrar y borrar: borrar es lógico en la fila y real en R2.
5. **Reuso y límites**: `character_reference()` entrega a m-25128784 la imagen sin tocar, con su procedencia. Hay máximo 5 guardados y 2 rondas al día por negocio, una ronda abierta a la vez, y nada cobra de las creaciones. Todo queda detrás de `QUALIFY_CLIP_CHARACTER_SCENE`, apagado.

## Detalle

### Tabla 0188 `business_characters`

Una fila por **opción dibujada**. La ronda es el conjunto de filas con el mismo `round_id`. Se sigue el patrón de `0155_product_sticker_characters`.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid PK `gen_random_uuid()` | |
| `tenant_id` | uuid NOT NULL FK `tenants` | |
| `brand_id` | uuid NOT NULL | FK compuesta `(brand_id, tenant_id)` → `brands (id, tenant_id)` ON DELETE CASCADE |
| `round_id` | uuid NOT NULL | agrupa las 2–3 opciones de una descripción |
| `option_index` | smallint NOT NULL | CHECK 1..3; UNIQUE `(round_id, option_index)` |
| `request_key` | text NOT NULL | idempotencia de la ronda; UNIQUE `(tenant_id, brand_id, request_key, option_index)` |
| `description` | text NOT NULL | lo que escribió el dueño; CHECK 10..300 caracteres |
| `style` | text NOT NULL | dato abierto (lo valida el servicio); la tabla solo pide un nombre corto en minúsculas |
| `name` | text NULL | se pone al guardar; CHECK 1..40; índice único parcial `(brand_id, lower(btrim(name))) WHERE status='saved'` |
| `status` | text NOT NULL default `pending` | `pending → ready │ failed`; `ready → saved │ discarded`; `saved → deleted` |
| `fail_reason` | text NULL | `vendor_failed`, `moderated`, `budget_cap`, `uncertain`, `lost_result` |
| `object_key` | text NULL | CHECK contra la forma de la clave (ver R2); obligatorio en `ready`/`saved` |
| `content_type`, `width`, `height`, `byte_size`, `sha256` | | el archivo tal como llegó (byte a byte) |
| `model_id`, `model_revision` | text NOT NULL | procedencia |
| `prompt_version` | text NOT NULL | `business-character-v1` |
| `pipeline_version` | text NOT NULL | versión del módulo |
| `pricing_table_version` | text NOT NULL | `v10` |
| `quoted_usd` / `cost_usd` | numeric(12,6) | lo que miró la guarda / lo realmente cobrado (0 hasta saberlo) |
| `vendor_request_started_at` | timestamptz NULL | se estampa ANTES del POST: un reintento que lo encuentra no vuelve a pagar |
| `created_by` | uuid FK `users` | |
| `created_at`, `finished_at`, `saved_at`, `deleted_at` | timestamptz | CHECK `(status='saved') = (saved_at IS NOT NULL) OR status IN ('deleted','discarded')`; CHECK `(status='deleted') = (deleted_at IS NOT NULL)` |

- Índices: `ix_business_characters_tenant (tenant_id)` y `ix_business_characters_brand (brand_id, status, created_at)`. UNIQUE `(tenant_id, id)` para la FK de `creative_jobs`.
- **RLS**: `ENABLE` + `FORCE` + política `tenant_isolation` con `NULLIF(current_setting('app.tenant_id', true), '')::uuid` en `USING` y `WITH CHECK`.
- **Permisos**: `qualify_app` tiene `SELECT, INSERT, UPDATE`. No tiene `DELETE`, porque la fila guarda la procedencia de un pago. `qualify_admin` tiene `SELECT`. `qualify_creative_worker` no recibe nada: según ADR 41, el sujeto se lee del lado del tenant.
- **`creative_jobs`**: el tipo `business_character` y la columna `business_character_id` con FK `(tenant_id, business_character_id)` → `(tenant_id, id)` y CASCADE. `ck_creative_jobs_subject` pasa a pedir exactamente uno de `draft_id` / `seasonal_media_id` / `sticker_character_id` / `business_character_id`. `uq_creative_jobs_business_character` deja un solo trabajo pagado por opción. La piscina `byteplus:seedream-5-0-pro` ya se sembró en la 0155, así que no hace falta sembrarla de nuevo.
- **Downgrade**: se niega mientras exista una fila o un trabajo de personaje, para no perder la procedencia de un pago. Después restaura las restricciones de `creative_jobs` y borra la columna y la tabla. CI corre `upgrade → downgrade base → upgrade`.
- El tope de 5 **no** va en la base, porque no se puede expresar con un índice. Lo cuida el servicio con `SELECT … FOR UPDATE` sobre la fila del negocio, igual que `check_avatar_daily_cap`.

### Imágenes en R2

- La raíz queda fuera de `t/`. El candado del bucket en `t/` niega borrar y sobrescribir, y aquí borrar tiene que funcionar. La clave también queda fuera de la purga de 90 días de ADR 39, porque el personaje se reutiliza. Clave: `seasonal/{tenant}/{brand}/personajes-negocio/{character_id}.{jpg|png}`. Está bajo `seasonal_brand_prefix`, que ya figura en `tenant_roots`, y no choca con la carpeta `personajes/` de los stickers.
- **Byte a byte**: lo que devuelve Seedream se guarda sin recodificar. Según AVESC-001, Seedance 2.x acepta caras solo cuando son salidas propias de Seedream sin modificar. Por eso la extensión es la del formato recibido. Esto obliga a agregar en `packages/shared` el ayudante `business_character_key()` y `ObjectGate.put_/delete_/open_business_character()`. Hoy `seasonal_media_key` solo admite `webp|mp4`, así que el cambio en `shared` es chico, pero pertenece a backend-engineer.
- **Procedencia** en la fila: proveedor `byteplus`, `model_id`/`model_revision`, `prompt_version`, `pipeline_version`, `pricing_table_version`, `quoted_usd`/`cost_usd`, `sha256` y la descripción. El prompt completo es reproducible a partir de la descripción, el estilo, la paleta y la versión.
- **Escritura**: 3 intentos con espera (`PUT_ATTEMPTS`, como en los stickers). Si la escritura falla después de pagar, la opción queda `failed` con `lost_result` y el costo queda registrado. Nada de esto toca los personajes ya guardados.
- Al **descartar** o **borrar** se hace `delete` real en R2. Si el borrado falla, se registra y se reintenta en la próxima pasada; la fila ya está `discarded`/`deleted`.

### Opciones y costo (tabla `v10`, sin llamadas)

- **Seedream 5.0 pro** (`dola-seedream-5-0-pro-260628`) a 1080×1920, que son 2,07 MP y caen en el tramo 1K. Cada imagen es un POST: el adaptador hace una imagen por llamada.
- **Sin imágenes de referencia**: la descripción va como texto, más la paleta del Brand Kit en hexadecimal para la ropa. Si se agrega el logo como referencia, la primera referencia es gratis y el costo no cambia.
- `seedream_image_cost(v10, size="1080x1920", references=0)` = **US$0,045 por opción**.
  - **2 opciones: US$0,09 por ronda.** 3 opciones: US$0,135 por ronda.
  - AVESC-001 midió US$0,045 por dibujo y de 27,5 a 58,4 s cada uno.
- Una imagen moderada o rechazada no se cobra. Si la conexión se cae, el monto cotizado se registra como gastado: es mejor contar de más que de menos.
- Peor caso por negocio con 2 rondas al día y 3 opciones: US$0,27 al día y unos US$8 al mes.

### Topes por negocio

- **5 personajes guardados** (`saved`), como dice el ticket. El sexto se rechaza.
- **2 rondas de dibujo por día** (decidido). Se cuentan en el día del negocio: el tope **se reinicia a la medianoche en la hora del negocio** (`tenants.timezone`, o UTC si está vacía). Cuenta toda ronda iniciada, salvo la que falló completa sin pagar nada, igual que el tope del avatar. Una opción que quizá se pagó (conexión caída, error 5xx o un intento anterior que murió) anota su cotización en `cost_usd`, así que una ronda que falló así cuenta (revisión de m-25129385).
- **Una ronda abierta a la vez**: el negocio no puede pedir otra hasta elegir o descartar la que tiene abierta. Las rondas sin elegir se descartan solas a los 7 días.
- La **guarda de precio** compara la cotización de cada opción con lo que queda del tope mensual en dólares (`creative_engine_config`, solo si `hard_stop_on_cap`). Pasarse lo rechaza antes de llamar a BytePlus. **Exceso aceptado:** las 3 opciones se revisan en paralelo contra el mismo saldo, así que una ronda puede pasarse del tope hasta en dos opciones (US$0,09). Es el mismo patrón de los stickers.
- **Sin imágenes huérfanas:** si el dueño elige una opción, o descarta la ronda, mientras otra se sigue dibujando, el worker borra de R2 la imagen que acaba de escribir al ver la opción descartada.

### Qué cobra contra el cupo

- **Dibujar un personaje no descuenta creaciones ni videos.** Es un paso de preparación, como «Sugerir con IA» (m-25129386). Esto es la pregunta 2.
- **Sí cuenta**, siempre:
  - el evento en `creative_usage_events`, con unidad `business_character_image`, id derivado de la opción (un solo registro), `paid_by=platform` y `pricing_table_version`;
  - el gasto del mes del negocio (`budget_spent_usd`).
- El uso del personaje en una escena lo cobra m-25128784: el borrador no cobra y la aprobación descuenta de la cuota de videos.

### Interruptor

- `QUALIFY_CLIP_CHARACTER_SCENE` está apagado por defecto en `.env.example` y en `deploy/.env.prod.example`. Además hace falta `QUALIFY_BYTEPLUS_ARK_API_KEY`.
- Con el interruptor apagado, toda función pública lanza `CharacterRefused("switched_off")` antes de leer o escribir nada. El trabajo del worker también se niega y no paga.
- No se enciende en producción. Encenderlo para clientes depende además de m-25129387 (los términos de datos de BytePlus).

### Contrato para la pantalla (`qualify_api.creative.business_characters`)

```python
def characters_unavailable_reason() -> str | None
def list_characters(tenant_id, brand_id) -> CharactersView
    # saved: list[Character]; open_round: DrawingRound | None;
    # rounds_left_today: int; slots_left: int  (5 - guardados)
def request_drawings(tenant_id, brand_id, user_id, *, description: str,
                     style: Literal["animado", "realista"], request_key: str) -> DrawingRound
def drawing_round(tenant_id, brand_id, round_id) -> DrawingRound      # la pantalla lo consulta
def choose_option(tenant_id, brand_id, round_id, option_id, *, name: str) -> Character
def discard_round(tenant_id, brand_id, round_id) -> None
def rename_character(tenant_id, brand_id, character_id, *, name: str) -> Character
def delete_character(tenant_id, brand_id, character_id) -> None
def character_reference(tenant_id, brand_id, character_id) -> CharacterReference  # para m-25128784
```

- **Estados**:
  - Opción: `pending` (dibujando), `ready`, `failed` (con su texto), `saved`, `discarded`, `deleted`.
  - Ronda: `drawing` (alguna en `pending`), `ready` (al menos una lista y ninguna pendiente), `failed` (todas fallaron) y `closed`.
- La vista de imagen sale por URL firmada o por bytes a través de `ObjectGate.open_business_character(tenant, brand, key)`, que liga la lectura al negocio.
- **Errores**: `CharacterRefused(code, text)`. La pantalla lee `code` y muestra `text`.

| Código | Texto |
|---|---|
| `switched_off` | «Los personajes todavía no están listos en tu cuenta. Mientras tanto, puedes crear tus videos sin ellos.» |
| `limit_reached` | «Ya tienes 5 personajes guardados. Borra uno para crear otro.» |
| `daily_cap` | «Hoy ya pediste dibujos 2 veces, que es lo máximo por día. Mañana puedes pedir otra vez.» (se reinicia a la medianoche del negocio) |
| `round_open` | «Ya te dibujamos 3 opciones. Elige una, o descártalas para pedir otras nuevas.» |
| `style_unknown` | «Elige cómo quieres a tu personaje: dibujo animado o realista.» |
| `not_ready` | «Ese dibujo todavía se está haciendo. Espera un momento y elígelo de nuevo.» |
| `description_short` | «Cuéntanos un poco más cómo es tu personaje.» |
| `description_long` | «Tu descripción es muy larga. Déjala en 300 letras o menos.» (300 se acepta; 301 no) |
| `name_invalid` | «Ponle a tu personaje un nombre de hasta 40 letras.» |
| `name_taken` | «Ya tienes un personaje con ese nombre. Elige otro.» |
| `not_found` | «No encontramos ese personaje. Puede que ya lo hayas borrado.» |
| `in_use` | «Este personaje está en un video que todavía no apruebas. Quítalo de ese video para poder borrarlo.» |

- **`in_use`** cuenta los videos en `drafting`, `generated`, `failed` y `rejected`: los dos últimos se pueden reintentar y el reintento necesita la imagen.
- **Fallo de una opción** (`BusinessCharacter.failure_text`), sin hablar de cobro:
  - `vendor_failed` / `uncertain` / `lost_result`: «Este dibujo no salió. Elige uno de los otros, o pide dibujos nuevos.»
  - `moderated`: «No pudimos dibujar ese personaje. Cambia un poco la descripción y vuelve a intentarlo.»
  - `budget_cap`: «Ahora no pudimos dibujarlo. Inténtalo más tarde.»
- **Fallo de la ronda completa** (`DrawingRound.failure_text`, vacío si salió alguna):
  - «Ningún dibujo salió. Puedes volver a pedirlos.»
  - Si la ronda pagó algo y por eso cuenta para el tope (`DrawingRound.counts_for_the_day`), se agrega: «Esta vez cuenta como uno de tus 2 pedidos del día.»
- **¿Una ronda que falló a medias deja elegibles los dibujos que salieron?** **Sí.** La ronda queda `ready` mientras haya al menos una opción lista. Las opciones que fallaron muestran «Este dibujo no salió. Elige uno de los otros, o pide dibujos nuevos.», y el dueño elige entre las que salieron. Lo cubre la prueba `test_a_half_failed_round_keeps_the_drawings_that_came_out_eligible`.

#### Notas para la pantalla (m-25112921)

- Una línea fija bajo el botón de dibujar: «Hoy puedes pedir dibujos 2 veces (cada vez te mostramos 3 opciones). Dibujar no gasta tus creaciones.»
- En la descripción, un contador «0/300» y el ejemplo «Por ejemplo: una chef joven con delantal rojo, sonriendo.»
- Botones de salida:
  - «Ver mis personajes», junto a `limit_reached`;
  - «Ver ese video», junto a `in_use`: el video es `CharacterRefused.draft_id`.

### Prompt `business-character-v1`

- Marco fijo en inglés, tomado de `avatar-escena-v1` porque fue el que funcionó:
  - personaje original y ficticio, que no sea una celebridad ni una persona real;
  - cuerpo de las rodillas hacia arriba, de frente, con las manos vacías y visibles;
  - fondo claro liso, formato vertical 9:16;
  - sin texto, sin logos y sin marca de agua.
- Se agrega el estilo («stylized 3D animated cartoon» o «photorealistic photo»), más la descripción del dueño en español entre comillas, limpia y recortada, más la paleta del Brand Kit para la ropa.
- La tipografía del Brand Kit no entra, porque la imagen no lleva texto; entra en la escena (m-25128784). El texto del prompt se prueba con pruebas puras.

### Qué NO entra

- La pantalla para crear y elegir personajes: m-25112921.
- La pista «Personajes» del Clip, la llamada a Seedance 2.5, el cobro de la cuota de videos y el tope de 3 escenas: m-25128784. Aquí solo se entrega `character_reference()`.
- Sugerir la línea con IA: m-25129386. Tampoco entra sugerir la descripción del personaje.
- Los términos de datos de BytePlus y el aviso al cliente: m-25129387, que bloquea encender el interruptor para clientes, no la construcción.
- Elegir o clonar la voz del personaje.
- Subir la foto de una persona real como personaje: Seedance 2.x niega caras reales.
- Editar o retocar la imagen de un personaje guardado.
- Migrar el «avatar animado» del Brand Kit (`logo_brief.brand_avatar`) a un personaje. Nunca corrió en vivo.
- Correr Seedream de pago sin el OK escrito de Deivid y encender interruptores en producción.

## Preguntas para Deivid

Cada pregunta va con una recomendación. No están decididas.

1. **¿Cuántas opciones por ronda: 2 o 3?** Recomiendo **3** (US$0,135 frente a US$0,09). Elegir bien al personaje pesa en todos los videos, y la diferencia es de US$0,045.
2. **¿Dibujar personajes descuenta creaciones?** Recomiendo **no**. Es preparación, como «Sugerir con IA»; el gasto queda limitado por el tope diario y el tope mensual en dólares, y el uso real se cobra en la escena.
3. **¿El dueño elige el estilo (animado o realista)?** Recomiendo **sí, los dos**. AVESC-001 aceptó los dos como referencia; el animado tuvo el defecto de la escala del producto y la voz 5 dB más baja.
4. **¿Qué pasa al borrar un personaje que está en un Clip sin aprobar?** Recomiendo **negarlo** con `in_use`. Si no, el final en 1080p de m-25128784 se quedaría sin la imagen.
5. **¿Cuántas rondas al día por negocio?** Recomiendo **3**, como el tope diario del avatar: peor caso de unos US$12 al mes por negocio con 3 opciones.
6. **¿Hay un riesgo de 30 días?** AVESC-001 anota que Seedance admite caras de Seedream «de menos de 30 días sin modificar». Un personaje guardado podría ser rechazado como referencia pasado un mes. Recomiendo **guardar la fecha del dibujo**, no fijar reglas aquí, y medirlo en m-25128784 con un personaje de más de 30 días antes de encender. Si se confirma, se permite volver a dibujarlo desde su descripción y su prompt.
7. **¿Uso un interruptor propio, `QUALIFY_CLIP_CHARACTERS`, o reuso `QUALIFY_CLIP_AVATAR_ANIMATED`?** Recomiendo **uno propio**. El personaje reemplaza al bloque de presentador que m-25128784 elimina, y así los interruptores viejos pueden irse con él.
8. **¿Los dibujos corren en `creative-worker` (ADR 41) o al momento en el servidor?** Recomiendo **el worker**, como los stickers: es la regla de nunca pagar dos veces y no deja a la pantalla esperando 30 a 60 s. Esto agrega el tipo nuevo en `creative_jobs` dentro de la misma 0188.
