# Plan — lo que hay que construir para grabar el video de `catalog_management` (App Review)

`[PLAN 2026-11-13 · m-25026326 · se ejecuta bajo m-25026261 cuando el fundador avise · épica m-24786384]`

Origen: decisión D3 del fundador (2026-11-13, `docs/arquitectura-meta-negocios-ajenos.md`,
sección «Decisión del fundador»): «si, junto con los de whatsapp para terceros», y después
«desarrollemos lo necesario para poder grabar ese video». Este plan es solo eso: lo mínimo para que
«crear, actualizar y eliminar un catálogo» sea verdad en Qualify y le sirva a un dueño real. Lo
ejecutan subagentes coordinados por el hilo principal; **todo lo que necesitan está aquí o en los
archivos que se nombran.**

Evidencia: `[V]` página oficial de Meta leída el **2026-11-13** (URL en §Fuentes) o código en disco
· `[S]` tercero, o lectura resumida de una página que nadie ha leído entera · `[H]` inferencia ·
`[F]` decisión del fundador · **`[NO VERIFICADO]`**.

---

## 0. Qué exige Meta que se vea

| Exigencia | Nivel | Fuente |
|---|---|---|
| Video de `catalog_management`: «Demonstrate the complete Facebook login process on your app platform» y «how your app user creates, updates, and deletes a product catalog on your app platform» | `[V]` | [F-1] |
| Uso permitido: soluciones de comercio y de inventario de productos | `[V]` | [F-1] |
| Depende de `business_management`, cuya revisión pide mostrar datos de **rendimiento de anuncios** (impresiones, gasto, clics…) | `[V]` | [F-1] |
| Los revisores deben ver cómo el usuario inicia sesión y **el proceso de autorización completo**; para cada permiso, un usuario accediendo a los datos | `[V]` | [F-2] |
| Interfaz en inglés si se puede; si no, **subtítulos y textos de ayuda**. Los subtítulos se añaden **al editar el video**; la pantalla de Qualify sigue en español y no gana textos ni controles para la grabación (pauta 7 de §3.8) | `[V]` / decisión del plan | [F-2] |
| Alta resolución (idealmente 1080 o más) con el monitor a 1440 px de ancho o menos | `[V]` | [F-2] |
| Cada permiso con su descripción propia (no se reutiliza texto) y su grabación; sin grabación no se aprueba | `[V]` | [F-3] |
| Meta prueba con **sus propias cuentas**; nunca credenciales personales; instrucciones de acceso a la app; «si no podemos acceder a tu app… se rechazará la solicitud completa» | `[V]` | [F-3][F-4] |
| Evaluación **por permiso**: «no se aprobará para dicho permiso» si no se verifica | `[V]` | [F-4] |
| Aprobación parcial dentro de un envío y cómo reenviar solo lo rechazado | `[S]` / **`[NO VERIFICADO]`** | consultor (§Fuentes) |
| Si un token de **usuario del sistema** del propio portafolio vale como evidencia en vez del inicio de sesión | **No**, por inferencia `[H]`: el video exige el inicio de sesión completo `[V F-1]`, y la página de grabaciones no habla de tokens de usuario del sistema | [F-1][F-2] |

**Consecuencia de diseño:** la grabación debe mostrar a un dueño **iniciando sesión con Meta y
concediendo `catalog_management`** sobre un portafolio que no es Qualify.co, y luego creando,
actualizando y eliminando su catálogo dentro de Qualify. Antes de la aprobación, eso solo lo puede
hacer alguien **con rol en la app** (el fundador): el acceso estándar se pide a usuarios con rol en
la app `[V F-5]`.

## 1. Qué gana el dueño

El dueño que vende por WhatsApp y no tiene catálogo **muestra sus productos y precios dentro de
WhatsApp con un toque desde Galería**, sin entrar a Commerce Manager (que no conoce y que está en
inglés técnico); le cambia el nombre si hace falta; y **quita sus productos de WhatsApp** si se
equivocó o cierra, sabiendo antes qué dejarán de ver sus clientes. Hoy en ese estado Galería solo
ofrece «Pedir mi catálogo de WhatsApp» (un pedido al equipo, `Qualify/catalog_whatsapp_vm.py:55`):
el equipo lo crea a mano. Esto lo convierte en autoservicio, que es lo que pide el Modelo B (D1).

## 2. Qué existe hoy y qué falta

| Verbo del video | Hoy | Falta | Dónde |
|---|---|---|---|
| Iniciar sesión y conceder `catalog_management` | Facebook Login for Business para Instagram (`QUALIFY_META_CONFIG_ID`) y una configuración aparte para anuncios (`QUALIFY_META_ADS_CONFIG_ID`), `packages/api/src/qualify_api/config.py:110–111`; WhatsApp solo por CLI con token de usuario del sistema (`whatsapp/connect.py`) | Un inicio de sesión que pida `catalog_management` + `business_management` sobre el portafolio del dueño, **dentro de conectar WhatsApp en Cuentas conectadas** (§3.1, pauta 1) | `connections/`, `config.py`, pantalla de Cuentas conectadas |
| Crear catálogo | No existe (ADR 48 §1: «Qualify no crea ni conecta catálogos») | `POST /{business_id}/owned_product_catalogs` + `POST /{waba_id}/product_catalogs` | `whatsapp/catalog_sync/client.py` (nuevo método), servicio, worker |
| Registrar el catálogo en Qualify | CLI administrativo `just whatsapp-catalog-connect` (`catalog_sync/connect.py`) | Que la creación escriba la fila `whatsapp_catalogs` sola | `catalog_sync/service.py`, `store.py` |
| Actualizar: subir y re-sincronizar productos | **Existe**: `items_batch` + `check_batch_request_status` (`client.py:104–155`), tres acciones (`service.py`), worker (`worker.py`) | Nada | — |
| Actualizar: cambiar el nombre | No existe | `POST /{catalog_id}` con `name` | cliente, servicio, worker |
| Eliminar catálogo | No existe | `DELETE /{catalog_id}` + estado local | cliente, servicio, worker |
| Pantalla de Galería | Galería › WhatsApp con estados `none` / `connected` / `missing_permission` / `auth_error` (`Qualify/catalog_whatsapp_{vm,provider,state,page}.py`) | Acción principal de crear, «Más opciones» con cambiar el nombre y quitar (con confirmación), estados «creando» / «quitando» / error (§3.8) | las cuatro capas de Galería |
| Datos | `whatsapp_catalogs` con `UNIQUE (waba_id)` y `UNIQUE (brand_id)`, `source ∈ {qualify, manual}`, `access_state` (`migrations/postgres/versions/0158_whatsapp_catalog_sync.py`) | Ciclo de vida del catálogo y bandeja de operaciones (§3.6) | migración nueva |

## 3. Decisiones de diseño del plan

**3.1 Modelo y token de la grabación.** Modelo B (D1): un **portafolio de demostración** que el
fundador controla por completo y que **no es Qualify.co** (la app debe estar en un portafolio
distinto del cliente `[V F-5]`), con su propia cuenta de WhatsApp y un número propio (no el de
Bianki). El número de prueba que da el panel de la app no se usa: lo más probable es que viva en el
portafolio de la app, y la página de inicio solo habla de «your test phone number ID» sin decir de
qué portafolio es `[H]` / **`[NO VERIFICADO]`** [F-8]. Dos rutas de inicio de sesión; **la elección
se cierra en el paso 1, no aquí**:
- **(a) El registro integrado de m-24789620**, con su configuración pidiendo además
  `catalog_management` y el activo «catálogos» (`catalog_ids` en la sesión `[V F-7]`). Un solo
  inicio de sesión para los tres videos. **La evidencia hoy apunta en contra antes de la
  aprobación:** la página del registro integrado dice, según la lectura del revisor del
  2026-11-13, que en modo desarrollo quien tiene rol de administrador, desarrollador o probador ve
  los permisos, pero **en modo Live solo aparecen en el flujo los permisos ya aprobados con acceso
  avanzado** `[S]` (lectura resumida de [F-6], pendiente de leerla entera o comprobarlo en vivo); y
  la app de Qualify está en Live (`qualify-context` §1). Además Meta dice «no podrás incorporar
  clientes hasta tener acceso avanzado» `[V F-6]`.
- **(b) Una configuración de Facebook Login for Business solo para catálogo**, igual que la de
  anuncios (`QUALIFY_META_ADS_CONFIG_ID`, precedente en disco), con token de usuario del dueño. Se
  apoya en que el acceso estándar se puede pedir a usuarios con rol en la app `[V F-5]`; que eso
  siga valiendo con la app en Live para Facebook Login for Business es lo que hoy hace funcionar
  Instagram con las cuentas del fundador (`qualify-context` §1) `[H]`. **Cuesta una variable de
  entorno nueva, `QUALIFY_META_CATALOG_CONFIG_ID`, y eso necesita el sí del fundador** (regla de
  `CLAUDE.md`; `qualify-prod-ops` reglas 1 y 3: `env-stage` de una clave nueva se pregunta antes,
  se anuncia, se apaga el despliegue automático y se despliega a mano).
- **Lo que (b) deja abierto, y el paso 2 debe resolver:** la conexión de **WhatsApp** del tenant
  de demostración en producción. El usuario del sistema de Qualify.co no ve una cuenta de WhatsApp
  de otro portafolio (compartirla como socio exige acceso avanzado `[V]`, arquitectura §4), y crear
  y conectar necesitan el `waba_id` de la marca. Opciones para el paso 2: que la configuración (b)
  pida también los dos permisos de WhatsApp y la conexión salga de ese token de usuario (vencimiento
  incluido), o que el `waba_id` se lea de los activos concedidos en el inicio de sesión
  **`[NO VERIFICADO]`**. Con (a) el registro integrado da `waba_id` y token por cliente.

**Las funciones de catálogo no dependen de la ruta:** toman la credencial de la conexión de la
marca con `CredentialResolver` (como `HttpWhatsAppCatalogClient` hoy).

**3.2 En la petición o en el worker.** Las tres operaciones van por el **`whatsapp-worker`
existente** como una tercera tarea junto a `OutboxTick` y `CatalogSyncTick`, no en la petición:
crear son **dos llamadas encadenadas** (crear + conectar) que deben sobrevivir a un corte entre
ambas, todas pueden recibir 80014/80009 y reintentarse, y así ninguna llamada a Meta queda en el
camino de la pantalla (ADR 48 §1.4). No son llamadas pagas (Meta no cobra catálogos `[H]`), así
que no necesitan guardia de precio. La pantalla muestra «creando» y consulta el estado.

**3.3 Idempotencia de «crear».** Un catálogo por jerarquía de cuentas de WhatsApp («one catalog per
WhatsApp account hierarchy» `[V F-9]`); un reintento nunca crea dos:
1. La operación es una fila con `UNIQUE (tenant_id, request_key)` (como las corridas de ADR 48);
   un doble toque inserta una sola.
2. Antes de crear, el worker lista `GET /{waba_id}/product_catalogs`: si ya hay uno conectado,
   **lo adopta** (no crea) y lo registra con **`created_by_qualify = false`**: puede ser uno que el
   dueño hizo a mano, y Qualify nunca gana el derecho de eliminarlo por adoptarlo (§3.4). Solo un
   catálogo que esta misma operación creó — reconocido por el `catalog_id` guardado (punto 4) o por
   el sufijo (punto 3) — se registra con `true`.
3. El nombre que Qualify pone es el de la marca más un sufijo fijo con el id corto de la operación;
   si el worker murió entre crear y conectar, en el reintento lista
   `GET /{business_id}/owned_product_catalogs` y adopta el que tenga ese sufijo. **El sufijo nunca
   se muestra en pantalla:** una vez conectado, el worker renombra el catálogo al nombre de la marca
   sin sufijo (una llamada más, la misma de «cambiar el nombre»). Ese renombre es **el último paso
   de la misma operación `create`** que tocó la persona y conserva su `requested_by`; no es una fila
   `rename` aparte ni un cambio que Qualify haga por su cuenta. Que esa lectura esté permitida con
   el token del dueño: **`[NO VERIFICADO]`** (P-8).
4. El `catalog_id` se guarda en la fila **en la misma transacción** en que el worker recibe la
   respuesta de creación, antes de conectar.

**3.4 Qué hace «quitar» (eliminar).** Solo se puede eliminar desde Qualify un catálogo **que
Qualify creó** (columna nueva `created_by_qualify`). Un catálogo que el dueño hizo a mano en
Commerce Manager **no muestra el botón de quitar y no se construye ningún «Desconectar»** (§8).
Bloqueado mientras haya corridas en vuelo — `pending`, `sending` o `sent`, los tres estados que el
índice de reclamo de la migración 0158 trata como en vuelo. Confirmación según la pauta 3 de §3.8.
Meta: `DELETE /{catalog_id}`, bloqueado por defecto si hay conjuntos de productos vivos
(`allow_delete_catalog_with_live_product_set`, por defecto `false`; no se manda `true`) `[V F-10]`.
Al terminar: la fila del catálogo pasa a `deleted` en vez de borrarse — **decisión de diseño, no
impuesta por los permisos** (`qualify_app` sí tiene DELETE sobre `whatsapp_catalogs`): las
corridas y los artículos la referencian y son procedencia. Los artículos pasan a un estado
terminal y la marca vuelve al estado «sin catálogo». Qué le pasa a la cuenta de WhatsApp (y a los
productos ya enviados en chats) cuando se borra un catálogo conectado: **`[NO VERIFICADO]`** (P-9);
el borde de la WABA no permite desconectar `[V F-11]`.

**3.5 Lo que nunca se toca.** El número real de Bianki y su cuenta: la grabación y todas las
pruebas en vivo usan el portafolio de demostración y un tenant de demostración. Guardas en el
código: «quitar» exige `created_by_qualify`; «crear» exige que la marca no tenga catálogo; el CLI
`whatsapp-catalog-connect` sigue existiendo para el Modelo A. Un caso de borde que fija el paso
2: si la marca tiene una fila `creating` o `failed`, esa fila ocupa el índice único de `brand_id`
(§3.6) y el alta por CLI chocaría; el contrato dice si el CLI se niega con un mensaje claro o
reutiliza la fila.

**3.6 Datos: el delta propuesto** (lo fija el paso 2, una revisión, reversible, con RLS):
- `whatsapp_catalogs` gana `lifecycle` (`creating` | `active` | `deleting` | `deleted` |
  `failed`, por defecto `active` para las filas existentes), `created_by_qualify boolean NOT NULL
  DEFAULT false`, `name text NULL`, `business_id text NULL`; `UNIQUE (waba_id)` y
  `UNIQUE (brand_id)` pasan a **índices únicos parciales** `WHERE lifecycle <> 'deleted'` (para
  que se pueda crear otro tras eliminar). **Una creación `failed` conserva su lugar a propósito:
  el reintento reutiliza esa misma fila** (`failed → creating` con una operación nueva) en vez de
  insertar otra, para heredar el `catalog_id` si Meta llegó a crearlo antes del fallo; así el
  índice no bloquea el reintento y no quedan filas huérfanas. `catalog_id` puede ser nulo solo
  mientras `creating` o `failed` (`CHECK`).
- Tabla nueva **`whatsapp_catalog_ops`** (bandeja de salida): `tenant_id NOT NULL`, `brand_id`,
  `catalog_row_id`, `op ∈ {create, rename, delete}`, `request_key` con
  `UNIQUE (tenant_id, request_key)`, `status`, `attempts`, `locked_by`/`locked_at`,
  `meta_error_code`, `error_code`, `requested_by` (usuario), `pipeline_version`; RLS ENABLE +
  FORCE + la política `NULLIF` de la casa; sin DELETE para `qualify_app` (procedencia).
- El estado de los artículos tras eliminar usa los valores que ya admite
  `whatsapp_catalog_items.state` si alguno sirve; si no, se añade uno en el `CHECK`.

**3.7 Supuestos de ADR 48 que se enmiendan** (en el mismo PR que el código, como §13 nuevo de
`docs/adr-48-catalogo-whatsapp-carga-por-api.md`): §1.1 «Qualify no crea ni conecta catálogos
por API» → crea, conecta, renombra y elimina, siempre por el toque de una persona; §9 el CLI deja
de ser la única puerta de alta; §10 «Fuera de alcance» pierde esas líneas. **No cambian:** el
mapeo, `retailer_id`, la ruta pública de la foto, las tres acciones de sincronización.

**3.8 Pautas de UX de la revisión previa al PR (2026-11-13).** Encargo para los pasos 3 y 5:
son propuestas, no el texto final; el paso 3 cierra la redacción con `qualify-copy-es`.
1. **El inicio de sesión de Facebook vive donde ya vive conectar:** en Cuentas conectadas, como
   parte de conectar WhatsApp. Galería nunca tiene un segundo «conectar» solo para el catálogo;
   enlaza allí. La pantalla nunca muestra «portafolio», «Commerce Manager», «permiso» ni el nombre
   técnico de un permiso; elegir el negocio pasa dentro de la ventana de Meta. Línea propuesta:
   «Conecta tu WhatsApp para mostrar tus productos y precios a tus clientes».
2. **Términos de comercio (R5):** el dueño no queda solo frente a Commerce Manager. El estado es un
   aviso más un pedido al equipo, reutilizando el patrón de «Pedir mi catálogo de WhatsApp». En el
   Modelo B el portafolio es del cliente, así que puede que el equipo no pueda aceptar esos términos
   por él; si lo hacemos nosotros o lo guiamos es `[H]` y se cierra con P-10. **El texto no promete
   «lo hacemos nosotros» hasta entonces.**
3. **Confirmación de quitar:** dice en palabras simples qué deja de ver el cliente, que Galería no
   cambia y que no se puede deshacer; botones con verbos, nunca «Aceptar»/«Cancelar»; la entrada
   está bajo «Más opciones». Propuesta — título «¿Quitar tus productos de WhatsApp?»; cuerpo «Tus
   clientes dejarán de ver tus {n} productos y precios dentro de WhatsApp. Tus productos aquí en
   Galería no cambian. No se puede deshacer: si luego quieres mostrarlos otra vez, Qualify crea un
   catálogo nuevo y los subes de nuevo.»; si P-9 lo confirma, añadir «Los productos que ya enviaste
   en chats dejarán de abrirse.»; botones «Sí, quitar de WhatsApp» / «Dejarlos en WhatsApp»;
   entrada «Quitar mis productos de WhatsApp»; bloqueado mientras se sube algo: «Espera a que
   terminen de subir tus productos; después puedes quitarlos.»
4. **Nombre del catálogo:** precargado con el nombre de la marca; el sufijo de §3.3 nunca se ve (se
   quita con el renombre automático). «Cambiar el nombre» vive bajo «Más opciones» con la ayuda
   «Así aparece tu catálogo en tus herramientas de Meta; tus clientes no lo ven» — si WhatsApp le
   muestra el nombre al cliente es `[H]` y se cierra en el paso 1 (P-11). Para el video, «actualizar»
   se muestra sobre todo subiendo productos (R7); el renombre es el segundo ejemplo, no el centro de
   la pantalla.
5. **Sin catálogo todavía:** una acción principal que dice qué gana el dueño y una salida
   secundaria. Propuesta: «Tus clientes verán tus productos y precios dentro de WhatsApp. Lo creamos
   ahora y luego eliges qué productos subir.» · principal «Mostrar mis productos en WhatsApp» ·
   secundaria «Prefiero que lo haga el equipo» (manda el pedido de hoy). Al crear, el siguiente paso
   aparece enseguida: «Subir mis productos a WhatsApp» (existe).
6. **Estados intermedios y errores:** creando «Estamos creando tu catálogo de WhatsApp. Tarda unos
   segundos; puedes seguir usando la pantalla.»; quitando «Estamos quitando tus productos de
   WhatsApp…»; fallo «No pudimos crear tu catálogo de WhatsApp. Inténtalo de nuevo en un rato; si
   sigue igual, escríbenos.» + «Escribir al equipo». Nunca códigos de error (80014, 80009) ni «Meta
   devolvió un error».
7. **Nada en inglés y ningún control que exista solo para la grabación;** los subtítulos se ponen al
   editar el video.
8. Un catálogo que no creó Qualify no muestra «quitar», y no se construye «Desconectar» (§3.4, §8).

## 4. Pasos de ejecución

Cada paso dice: **quién** · recibe · toca · acepta si · pruebas · devuelve · depende de ·
¿paralelo? El hilo principal coordina y no escribe código (`qualify-lead`).

**Paso 0 — Ticket y rama.** Hilo principal. Recibe este plan. Crea con `meegle-ticket` las
historias bajo m-25026261 (o usa m-25026261 si el fundador prefiere un solo ticket) y la rama
`feat/m-<id>-catalogo-crear-eliminar` desde `origin/main`. Acepta si: existe el `m-<id>` antes del
primer push. Devuelve: ids y rama. Depende de: aviso del fundador.

**Paso 1 — Pruebas en vivo con el fundador (P-7 a P-11) y elección de ruta.**
`principal-architect` con el fundador (que ejecuta en su sesión). Recibe §3.1 y §7. Toca: §7 de
este plan (resultados). Hace, en este orden:
1. **Mirar el modo de la app en el panel** (Live o desarrollo) y si la configuración de prueba de
   F4 muestra `catalog_management` en el flujo a una cuenta con rol en la app.
2. Con la configuración de prueba de F4: intentar el registro integrado (ruta a) y el inicio de
   sesión de Facebook Login for Business (ruta b) sobre el portafolio de demostración (P-7).
3. Con el Explorador de la Graph API y el token del fundador, sobre el portafolio de demostración:
   crear un catálogo **antes** de F3 (P-10, términos de comercio) y con solo `name` (R6),
   renombrarlo, conectarlo a la cuenta de WhatsApp de demostración, listar `owned_product_catalogs`
   (P-8), mirar si WhatsApp muestra el nombre al cliente (P-11), y borrarlo estando conectado
   (P-9).
Acepta si: cada prueba tiene resultado escrito (comando sin token, código de respuesta, campo
leído) y la ruta (a) o (b) queda propuesta; **si es (b), la variable nueva queda pedida al
fundador y respondida**. Devuelve: ruta + respuestas reales. Depende de: F1, F2, F4. No paralelo con
el paso 2 (lo condiciona).

**Paso 2 — Contrato técnico y enmienda de ADR 48.** `principal-architect`. Recibe: §3, resultados
del paso 1, `migrations/postgres/versions/0158_whatsapp_catalog_sync.py`,
`packages/api/src/qualify_api/whatsapp/catalog_sync/*.py`, ADR 48. Toca: §13 nuevo de ADR 48
(DDL exacto, firmas de servicio, máquina de la operación, códigos de error, cómo se resuelve la
credencial en la ruta elegida y, en (b), **cómo se crea en producción la conexión de WhatsApp del
tenant de demostración**, §3.1). Acepta si: un ingeniero puede implementar sin preguntar; el DDL
cumple `qualify-migration` (RLS en la misma revisión, `downgrade` completo). Devuelve: §13.
Depende de: 1.

**Paso 3 — Textos y flujo de pantalla.** `ux-designer`. Recibe: §1, §2, §3.4, §3.8,
`Qualify/catalog_whatsapp_vm.py`, `qualify-copy-es`, `qualify-ux`. Toca: un bloque «Textos» en
§13 de ADR 48 (o `docs/mockups/` si hace falta un mockup). Entrega: los textos de §3.8 cerrados
(Galería y la entrada en Cuentas conectadas), y aparte los **subtítulos en inglés** para editar el
video. Acepta si: sin anglicismos ni palabras técnicas de Meta frente al dueño; un paso, una
decisión; legible a 360 px. Depende de: 2 (puede empezar en paralelo con su borrador).

**Paso 4 — Backend.** `backend-engineer`. Recibe: §13 de ADR 48. Toca: revisión nueva en
`migrations/postgres/versions/` (número provisional; se renumera en el paso 9),
`whatsapp/catalog_sync/client.py` (crear, conectar, renombrar, eliminar, listar propios; métodos
en la clase existente o una clase hermana ligada a un `business_id`), `service.py`
(`create_catalog`, `rename_catalog`, `delete_catalog`, cada uno inserta una operación con
`request_key`), `worker.py` (tercera tarea del tick), `store.py`, `models`, `just` si hace falta.
Acepta si: un doble toque crea una sola operación; un corte entre crear y conectar no deja dos
catálogos (prueba con el falso); un catálogo adoptado queda con `created_by_qualify = false` y no
se puede eliminar; un reintento tras `failed` reutiliza la fila; eliminar está
prohibido sin `created_by_qualify` y con corridas `pending`/`sending`/`sent`; ningún token ni
texto de cliente en logs; credencial solo por `CredentialResolver`; RLS probado. Pruebas:
unitarias offline con `FakeWhatsAppCatalogClient` extendido; `-m db` con aislamiento tenant A/B
sobre `whatsapp_catalog_ops`; `upgrade → downgrade → upgrade`. Devuelve: commits empujados a la
rama. Depende de: 2. Paralelo con 5 (contrato fijo).

**Paso 5 — Pantalla de Galería.** `reflex-ui-engineer`. Recibe: §13 de ADR 48, textos del paso 3,
§3.8. Toca: `Qualify/catalog_whatsapp_{vm,provider,state,page}.py` y sus pruebas. El estado `none`
ofrece la acción principal de crear y, como secundaria, el pedido al equipo de hoy; sin conexión de
WhatsApp, enlaza a Cuentas conectadas (no conecta aquí); `connected` lleva «Más opciones» con
cambiar el nombre y, solo si `created_by_qualify`, quitar; estados creando / quitando / error con
consulta periódica. Acepta si: toda acción destructiva tiene confirmación; funciona a 360 px; sin
texto en inglés. Pruebas: VM y estado offline. Depende de: 2, 3. Paralelo con 4.

**Paso 6 — Ruta de inicio de sesión (backend + pantalla).**
- **6a, backend** (`backend-engineer`). Si el paso 1 eligió (a): dentro de m-24789620 añade
  `catalog_management` + `business_management` a la configuración del registro integrado y guarda
  `catalog_ids`. Si eligió (b): la configuración de catálogo junto a la de anuncios (`config.py`,
  ruta OAuth de `connections/`), la conexión de WhatsApp que fijó el paso 2, y la clave documentada
  en `.env.example`; `platform-engineer` la prepara con `just env-stage` **solo con el sí del
  fundador (`qualify-prod-ops` reglas 1 y 3)**.
- **6b, pantalla** (`reflex-ui-engineer`). La entrada «conectar» que muestra el guion (§6,
  segundos 10–45): en Cuentas conectadas, como parte de conectar WhatsApp (pauta 1), y el enlace
  desde Galería.
Acepta si: el fundador, con rol en la app, completa el inicio de sesión sobre el portafolio de
demostración desde Cuentas conectadas y `/debug_token` muestra los permisos. Depende de: 1, 2, 3, F4.

**Paso 7 — Revisión UX local.** `ux-designer`, en navegador a **360 px** sobre la rama, contra la
pila local con el falso de Meta, incluida la entrada de Cuentas conectadas. Devuelve sugerencias
para «Sugerencias de UX» del PR (aplicada / pendiente). Depende de: 4, 5, 6.

**Paso 8 — Revisión de código independiente.** Un subagente que **no** escribió el código, con
`review-agent` sobre el diff completo contra la base de `main`. Acepta si: «No findings» o cada
hallazgo resuelto y re-revisado. Depende de: 4, 5, 6.

**Paso 9 — Renumerar la migración y CI.** `backend-engineer`, al final: `git fetch`, tomar el
número siguiente a la cabeza de `origin/main`, renumerar solo la revisión de la rama;
`just ci-lint`, `just ci-test`, `just test-db`. Abre el PR por REST (`qualify-pr`). Depende de: 7, 8.

**Paso 10 — Fusión y despliegue.** Hilo principal, **solo con el sí del fundador** a esa fusión
y **con la medición del paso 11 ya hecha**: `just merge <pr>` con CI verde; despliegue por la vía
documentada (`qualify-prod-ops`). Si se añadió variable de entorno (ruta b), prepararla **antes**
de fusionar, con el despliegue automático apagado y despliegue a mano (reglas 1 y 3). Tras el
despliegue: `just deploy-status qualify-prod` y los logs del `whatsapp-worker` por
`just deploy-logs` para ver que arrancó limpio. No hay ruta pública nueva que probar por el borde
(la foto ya usa la de ADR 48 §8); **si el paso 2 añade alguna**, probarla con `curl` contra el
dominio real tras el despliegue (lección del PR #634: una ruta nueva de la API que no estaba en el
Caddy de la app respondía la página web). Depende de: 9, 11.

**Paso 11 — Medir el worker, ANTES de fusionar (va entre el paso 9 y el 10).**
`platform-engineer`. La regla 9 de `qualify-prod-ops` pide medir bajo su tope todo trabajo nuevo
en el bucle de un worker **antes de encenderlo**, no después, y nunca con `docker` a mano en el
servidor. Se mide en local con el arnés que ya se usó para ADR 48 (PR #618): el bucle real del
`whatsapp-worker`, la imagen de producción, el tope real del compose (256 MiB, sin swap), un
Postgres desechable, un Meta falso y una red sin salida a internet. Los scripts están fuera del
repo, en
`/Users/herwin/Library/Application Support/Claude/side-session-notes/local_559ebfc1-bd66-4180-8822-842df4f2df46/wamem-harness`
(`wamem.sh`, `run_worker.py`, `seed.py`, `fake_graph.py`, `summarize.py`); llevarlos al repo como
`just mem-whatsapp-worker` es un seguimiento ya propuesto y, si ya existe, se usa esa receta.
Escenarios: la tarea nueva sin operaciones; crear y conectar; renombrar; eliminar; y una carga de
1.000 productos corriendo a la vez. Acepta si: el pico queda bajo el tope con margen, la memoria no
crece por ciclo y el `OutboxTick` mantiene su ritmo. Devuelve: la tabla de escenarios para la
descripción del PR. Depende de: 4, 9.

**Paso 12 — Prueba en producción y grabación.** Fundador (graba) + hilo principal (guía con §6).
Sobre el tenant de demostración: conectar, crear, renombrar, subir un producto, quitar. Acepta si:
el video cumple §0 y §6; el número de Bianki no aparece. Luego el envío (F6). Depende de: 10, 6
(y F4), F5; en la ruta (a), además, **m-24789620 desplegado** (otro ticket y otro PR).

## 5. Lo que debe hacer el fundador en Meta

| # | Qué | Cuándo |
|---|---|---|
| F1 | Crear el **portafolio de demostración** (p. ej. «Tienda de prueba de Qualify»), distinto de Qualify.co, con él como administrador con control total; 2FA activo | Antes del paso 1 |
| F2 | Una **cuenta de WhatsApp de demostración** en ese portafolio con un número propio (una SIM barata, nunca el número de Bianki ni su WhatsApp personal) | Antes del paso 1 |
| F4 | En el panel de la app: crear una **configuración de inicio de sesión de prueba** con `catalog_management` + `business_management` (y el activo «catálogos» para la ruta a), y pasar su id al hilo principal; la definitiva se ajusta tras el paso 1 | **Antes del paso 1** (P-7 la necesita) |
| F3 | En Commerce Manager de ese portafolio, **aceptar los términos de comercio** creando y borrando a mano un primer catálogo, solo si la prueba P-10 muestra que Meta lo exige | Durante el paso 1, después de P-10 |
| F5 | Un **tenant de demostración** en Qualify, dado de alta por el ítem «Alta de cliente» de Meegle (`meegle-altas`; única vía de alta desde 2026-10-23), y conectado al portafolio de demostración desde Cuentas conectadas | Antes del paso 12 |
| F6 | En App Review: pedir los permisos de WhatsApp para terceros + `catalog_management` (+ `business_management` si el panel lo exige aparte), una descripción propia por permiso, los tres videos, e **instrucciones y credenciales de prueba** para que el revisor entre a Qualify | Tras el paso 12 |

F4 se lista antes de F3 porque se necesita antes; los ids no cambian para no romper referencias.

## 6. Guion del video

Duración objetivo: 2–3 minutos, 1080p, ventana a 1440 px. Los subtítulos en inglés del paso 3 se
añaden al editar; la pantalla sigue en español.

| Seg. | Se ve | Subtítulo (idea, el texto final lo da el paso 3) |
|---|---|---|
| 0–10 | Qualify, sesión del dueño de demostración, Galería › WhatsApp sin catálogo | «A business owner wants to show products in WhatsApp» |
| 10–45 | Sigue el enlace a Cuentas conectadas, toca conectar WhatsApp; **inicio de sesión de Meta completo**: dentro de la ventana de Meta elige su negocio y acepta los permisos (incluido `catalog_management`) | «The owner logs in with Facebook and grants catalog_management» |
| 45–70 | Vuelve a Galería, toca «Mostrar mis productos en WhatsApp»; estado creando; aparece el catálogo conectado a su WhatsApp | «The app creates a product catalog in the owner's business» |
| 70–95 | Sube un producto de Galería; estado «en WhatsApp» | «The owner updates the catalog: products are added» |
| 95–110 | «Más opciones» › cambiar el nombre y guardar | «The owner can also rename the catalog» |
| 110–130 | Commerce Manager en otra pestaña: el catálogo con su nombre y el producto | «The change is visible in Meta Commerce Manager» |
| 130–160 | «Más opciones» › «Quitar mis productos de WhatsApp», lee la confirmación, confirma; vuelve al estado sin catálogo; Commerce Manager ya no lo muestra | «The owner deletes the catalog» |

Junto a los otros dos videos del mismo envío (mensaje enviado y recibido; plantilla creada,
m-24789620): si se usa la ruta (a), el inicio de sesión es el mismo registro integrado y puede
grabarse una vez y reutilizarse al principio de cada video; cada permiso conserva su grabación y
su descripción propias `[V F-3]`.

## 7. Riesgos y lo no verificado

| # | Riesgo o duda | Prueba que lo cierra |
|---|---|---|
| R1 / P-7 | La ruta (a) no se puede grabar antes de la aprobación: con la app en Live el registro integrado solo muestra permisos ya aprobados con acceso avanzado `[S]` (lectura resumida de [F-6]), y «no podrás incorporar clientes hasta tener acceso avanzado» `[V F-6]`. **La evidencia apunta a la ruta (b)**, que se apoya en el acceso estándar para usuarios con rol `[V F-5]` | Paso 1: mirar el modo de la app y probar ambas rutas con la configuración de F4 |
| R2 | `business_management` tiene que pedirse aparte y su video pide datos de anuncios `[V F-1]` | Ver en el panel de App Review si se añade solo como dependencia; si no, decidir con el fundador si se omite el permiso o se graba su caso |
| R3 / P-8 | Listar `owned_product_catalogs` con el token del dueño (idempotencia de §3.3) | Paso 1 |
| R4 / P-9 | Qué pasa al borrar un catálogo conectado a la cuenta de WhatsApp (¿error, desconexión, productos ya enviados que dejan de abrirse?) | Paso 1, en el portafolio de demostración |
| R5 / P-10 | «Debes aceptar los términos creando tu primer catálogo en Business Manager» `[V F-10]` → el **primer** catálogo de un dueño real podría no poder crearse por API | Paso 1: crear por API en un portafolio sin catálogos previos **antes** de F3; si falla, pauta 2 de §3.8 |
| R6 | `owned_product_catalogs` lista `page_id` como «obligatorio» `[V F-12]`, cosa rara para un catálogo de comercio | Paso 1: crear con solo `name` (y `vertical=commerce`, el valor por defecto `[V F-12]`) |
| R7 | Que subir productos cuente como «updates» para el revisor `[NO VERIFICADO]` | El guion muestra subir **y** renombrar |
| R8 | Revisor sin acceso a Qualify → se rechaza **todo** el envío `[V F-4]` | F6: credenciales del tenant de demostración e instrucciones claras |
| R9 | Calendario: el envío de WhatsApp para terceros espera a este plan — consecuencia de D3, deducción nuestra `[H]`; el fundador no lo dijo con esas palabras | Correr los pasos 4–6 en paralelo con m-24789620 |
| R10 | El número de prueba del panel probablemente vive en el portafolio de la app y no sirve para el Modelo B `[H]`; de qué portafolio es y si admite catálogo, **`[NO VERIFICADO]`** [F-8] | No se usa; F2 |
| R11 / P-11 | Si WhatsApp le muestra al cliente el nombre del catálogo (decide el texto de ayuda de la pauta 4) `[H]` | Paso 1 |
| R12 | Ruta (b): cómo se crea la conexión de WhatsApp del tenant de demostración sin acceso avanzado (§3.1) | Paso 2, con lo que muestre el paso 1 |

## 8. Qué NO entra

Sincronización automática al editar (ADR 48 D2) · importar CSV / `sku` (CAT-03) · catálogos de
varios negocios en una pantalla · **«Desconectar» o quitar un catálogo que no creó Qualify** (no se
muestra el botón; Meta tampoco ofrece desconectar por el borde de la WABA `[V F-11]`) · conjuntos
de productos, anuncios de catálogo, verticales que no sean `commerce` · el registro integrado en sí
(es m-24789620) · mostrar datos de anuncios para `business_management` (R2 decide) · textos en
inglés o controles solo para la grabación.

## Fuentes (acceso 2026-11-13)

- [F-1] Permissions reference (`catalog_management`, `business_management`) — https://developers.facebook.com/docs/permissions/reference/catalog_management
- [F-2] App Review: grabaciones de pantalla — https://developers.facebook.com/docs/app-review/submission-guide/screen-recordings
- [F-3] App Review: guía de envío — https://developers.facebook.com/docs/app-review/submission-guide
- [F-4] App Review: introducción — https://developers.facebook.com/docs/app-review/introduction
- [F-5] Facebook Login for Business (portafolio separado; prueba con rol y control total) y Access levels (estándar = usuarios con rol en la app) — https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/ · https://developers.facebook.com/docs/graph-api/overview/access-levels/
- [F-6] Embedded Signup (incl. qué permisos aparecen en modo desarrollo y en Live) — https://developers.facebook.com/docs/whatsapp/embedded-signup/
- [F-7] Embedded Signup implementation — https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation.md
- [F-8] WhatsApp Cloud API Get Started (solo menciona «your test phone number ID») — https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started.md
- [F-9] Upload inventory («one catalog per WhatsApp account hierarchy») — https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/upload-inventory.md
- [F-10] ProductCatalog reference (actualizar `name`, `DELETE`, términos de comercio) — https://developers.facebook.com/docs/marketing-api/reference/product-catalog/
- [F-11] WhatsApp Business Account `product_catalogs` — https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account/product_catalogs/
- [F-12] Business `owned_product_catalogs` — https://developers.facebook.com/docs/marketing-api/reference/business/owned_product_catalogs/
- `[S]` Aprobación parcial (12 de 15 permisos; anécdota de consultor) — https://singhamandeep.com/?p=3065
