# Plan — lo que hay que construir para grabar el video de `catalog_management` (App Review)

`[PLAN 2026-11-13 · m-25026326 · se ejecuta bajo m-25026261 cuando el fundador avise · épica m-24786384]`

Origen: decisión D3 del fundador (2026-11-13, `docs/arquitectura-meta-negocios-ajenos.md`,
sección «Decisión del fundador»): `catalog_management` va **en el mismo envío** que los permisos
de WhatsApp para terceros, y «desarrollemos lo necesario para poder grabar ese video». Este plan
es solo eso: lo mínimo para que «crear, actualizar y eliminar un catálogo» sea verdad en Qualify y
le sirva a un dueño real. Lo ejecutan subagentes coordinados por el hilo principal; **todo lo que
necesitan está aquí o en los archivos que se nombran.**

Evidencia: `[V]` página oficial de Meta leída el **2026-11-13** (URL en §Fuentes) o código en disco
· `[S]` tercero · `[H]` inferencia · `[F]` decisión del fundador · **`[NO VERIFICADO]`**.

---

## 0. Qué exige Meta que se vea

| Exigencia | Nivel | Fuente |
|---|---|---|
| Video de `catalog_management`: «Demonstrate the complete Facebook login process on your app platform» y «how your app user creates, updates, and deletes a product catalog on your app platform» | `[V]` | [F-1] |
| Uso permitido: soluciones de comercio y de inventario de productos | `[V]` | [F-1] |
| Depende de `business_management`, cuya revisión pide mostrar datos de **rendimiento de anuncios** (impresiones, gasto, clics…) | `[V]` | [F-1] |
| Los revisores deben ver cómo el usuario inicia sesión y **el proceso de autorización completo**; para cada permiso, un usuario accediendo a los datos | `[V]` | [F-2] |
| Interfaz en inglés si se puede; si no, **subtítulos y textos de ayuda** (en inglés) | `[V]` | [F-2] |
| Alta resolución (idealmente 1080 o más) con el monitor a 1440 px de ancho o menos | `[V]` | [F-2] |
| Cada permiso con su descripción propia (no se reutiliza texto) y su grabación; sin grabación no se aprueba | `[V]` | [F-3] |
| Meta prueba con **sus propias cuentas**; nunca credenciales personales; instrucciones de acceso a la app; «si no podemos acceder a tu app… se rechazará la solicitud completa» | `[V]` | [F-3][F-4] |
| Evaluación **por permiso**: «no se aprobará para dicho permiso» si no se verifica | `[V]` | [F-4] |
| Aprobación parcial dentro de un envío y cómo reenviar solo lo rechazado | `[S]` / **`[NO VERIFICADO]`** | consultor (§Fuentes) |
| Si un token de **usuario del sistema** del propio portafolio vale como evidencia en vez del inicio de sesión | **No**, en la práctica: el video exige el inicio de sesión completo `[V F-1]`; ninguna página habla de tokens de usuario del sistema `[V F-2]` | — |

**Consecuencia de diseño:** la grabación debe mostrar a un dueño **iniciando sesión con Meta y
concediendo `catalog_management`** sobre un portafolio que no es Qualify.co, y luego creando,
actualizando y eliminando su catálogo dentro de Qualify. Por acceso estándar, eso solo lo puede
hacer alguien **con rol en la app** (el fundador) `[V F-5]`.

## 1. Qué gana el dueño

El dueño que vende por WhatsApp y no tiene catálogo **crea su catálogo de WhatsApp desde Galería
con un toque**, sin entrar a Commerce Manager (que no conoce y que está en inglés técnico); le
cambia el nombre cuando cambia su negocio; y lo **elimina** si se equivocó o cierra, sabiendo
antes cuántos productos dejarán de verse en su WhatsApp. Hoy en ese estado Galería solo ofrece
«Pedir mi catálogo de WhatsApp» (un pedido al equipo, `Qualify/catalog_whatsapp_vm.py:55`): el
equipo lo crea a mano. Esto lo convierte en autoservicio, que es lo que pide el Modelo B (D1).

## 2. Qué existe hoy y qué falta

| Verbo del video | Hoy | Falta | Dónde |
|---|---|---|---|
| Iniciar sesión y conceder `catalog_management` | Facebook Login for Business para Instagram (`QUALIFY_META_CONFIG_ID`) y una configuración aparte para anuncios (`QUALIFY_META_ADS_CONFIG_ID`), `packages/api/src/qualify_api/config.py:110–111`; WhatsApp solo por CLI con token de usuario del sistema (`whatsapp/connect.py`) | Un inicio de sesión que pida `catalog_management` + `business_management` sobre el portafolio del dueño (§3.1) | `connections/`, `config.py` |
| Crear catálogo | No existe (ADR 48 §1: «Qualify no crea ni conecta catálogos») | `POST /{business_id}/owned_product_catalogs` + `POST /{waba_id}/product_catalogs` | `whatsapp/catalog_sync/client.py` (nuevo método), servicio, worker |
| Registrar el catálogo en Qualify | CLI administrativo `just whatsapp-catalog-connect` (`catalog_sync/connect.py`) | Que la creación escriba la fila `whatsapp_catalogs` sola | `catalog_sync/service.py`, `store.py` |
| Actualizar: subir y re-sincronizar productos | **Existe**: `items_batch` + `check_batch_request_status` (`client.py:104–155`), tres acciones (`service.py`), worker (`worker.py`) | Nada | — |
| Actualizar: cambiar el nombre | No existe | `POST /{catalog_id}` con `name` | cliente, servicio, worker |
| Eliminar catálogo | No existe | `DELETE /{catalog_id}` + estado local | cliente, servicio, worker |
| Pantalla | Galería › WhatsApp con estados `none` / `connected` / `missing_permission` / `auth_error` (`Qualify/catalog_whatsapp_{vm,provider,state,page}.py`) | Botón «crear», nombre editable, «eliminar» con confirmación, estados «creando» / «eliminando» | las cuatro capas de Galería |
| Datos | `whatsapp_catalogs` con `UNIQUE (waba_id)` y `UNIQUE (brand_id)`, `source ∈ {qualify, manual}`, `access_state` (`migrations/postgres/versions/0158_whatsapp_catalog_sync.py`) | Ciclo de vida del catálogo y bandeja de operaciones (§3.6) | migración nueva |

## 3. Decisiones de diseño del plan

**3.1 Modelo y token de la grabación.** Modelo B (D1): un **portafolio de demostración** que el
fundador controla por completo y que **no es Qualify.co** (la app debe estar en un portafolio
distinto del cliente `[V F-5]`), con su propia cuenta de WhatsApp y un número de prueba propio
(no el de Bianki, no el número de prueba del panel de la app, que vive en el portafolio de la app
`[V F-9]`). Dos rutas de inicio de sesión, en este orden de preferencia:
- **(a) El registro integrado de m-24789620**, con su configuración pidiendo además
  `catalog_management` y el activo «catálogos» (`catalog_ids` en la sesión `[V F-8]`). Un solo
  inicio de sesión para los tres videos del envío. Requiere que m-24789620 esté construido y que
  el registro funcione en acceso estándar para alguien con rol en la app — **`[NO VERIFICADO]`**
  (Meta: «no podrás incorporar clientes hasta tener acceso avanzado» `[V F-7]`).
- **(b) Respaldo: una configuración de Facebook Login for Business solo para catálogo**, igual
  que la de anuncios (`QUALIFY_META_ADS_CONFIG_ID`, precedente en disco), con token de usuario del
  dueño. Funciona hoy en acceso estándar para quien tiene rol `[V F-5]`. Cuesta **una variable de
  entorno nueva** (`QUALIFY_META_CATALOG_CONFIG_ID`) que hay que preparar en producción.
El paso 1 decide entre (a) y (b) con la prueba P-7. **Las funciones de catálogo no dependen de la
ruta:** toman la credencial de la conexión de WhatsApp de la marca con `CredentialResolver`
(como `HttpWhatsAppCatalogClient` hoy). Si se elige (b), la conexión de catálogo es una
credencial aparte de la marca y el paso 2 dice cómo se resuelve.

**3.2 En la petición o en el worker.** Las tres operaciones van por el **`whatsapp-worker`
existente** como una tercera tarea junto a `OutboxTick` y `CatalogSyncTick`, no en la petición:
crear son **dos llamadas encadenadas** (crear + conectar) que deben sobrevivir a un corte entre
ambas, todas pueden recibir 80014/80009 y reintentarse, y así ninguna llamada a Meta queda en el
camino de la pantalla (ADR 48 §1.4). No son llamadas pagas (Meta no cobra catálogos `[H]`), así
que no necesitan guardia de precio. La pantalla muestra «Creando…» y consulta el estado.

**3.3 Idempotencia de «crear».** Un catálogo por cuenta de WhatsApp `[V F-10]`; un reintento
nunca crea dos:
1. La operación es una fila con `UNIQUE (tenant_id, request_key)` (como las corridas de ADR 48);
   un doble toque inserta una sola.
2. Antes de crear, el worker lista `GET /{waba_id}/product_catalogs`: si ya hay uno conectado,
   **lo adopta** (no crea) y lo registra.
3. El nombre que Qualify pone lleva un sufijo fijo con el id corto de la operación; si el worker
   murió entre crear y conectar, en el reintento lista `GET /{business_id}/owned_product_catalogs`
   y adopta el que tenga ese sufijo en vez de crear otro. Que esa lectura esté permitida con el
   token del dueño: **`[NO VERIFICADO]`** (P-8).
4. El `catalog_id` se guarda en la fila **en la misma transacción** en que el worker recibe la
   respuesta de creación, antes de conectar.

**3.4 Qué hace «eliminar».** Solo se puede eliminar desde Qualify un catálogo **que Qualify creó**
(columna nueva `created_by_qualify`); un catálogo que el dueño hizo a mano en Commerce Manager
nunca se borra desde aquí — se desconecta de Qualify, no se destruye `[H]`, decisión del plan.
Bloqueado mientras haya corridas `pending`/`sent`. Confirmación con el número de productos que
dejarán de verse en WhatsApp. Meta: `DELETE /{catalog_id}`, bloqueado por defecto si hay
conjuntos de productos vivos (`allow_delete_catalog_with_live_product_set`, por defecto `false`;
no se manda `true`) `[V F-11]`. Al terminar: la fila del catálogo pasa a `deleted` (no se borra:
las corridas son procedencia y `qualify_app` no tiene DELETE sobre ellas), los artículos pasan a
un estado terminal, y la marca vuelve al estado «sin catálogo». Qué le pasa a la cuenta de
WhatsApp cuando se borra un catálogo conectado: **`[NO VERIFICADO]`** (P-9); el borde de la WABA
no permite desconectar `[V F-12]`.

**3.5 Lo que nunca se toca.** El número real de Bianki y su cuenta: la grabación y todas las
pruebas en vivo usan el portafolio de demostración y un tenant de demostración. Guardas en el
código: «eliminar» exige `created_by_qualify`; «crear» exige que la marca no tenga catálogo; el CLI
`whatsapp-catalog-connect` sigue existiendo para el Modelo A y no cambia.

**3.6 Datos: el delta propuesto** (lo fija el paso 2, una revisión, reversible, con RLS):
- `whatsapp_catalogs` gana `lifecycle` (`creating` | `active` | `deleting` | `deleted` |
  `failed`, por defecto `active` para las filas existentes), `created_by_qualify boolean NOT NULL
  DEFAULT false`, `name text NULL`, `business_id text NULL`; `UNIQUE (waba_id)` y
  `UNIQUE (brand_id)` pasan a **índices únicos parciales** `WHERE lifecycle <> 'deleted'` (para
  que se pueda crear otro tras eliminar). `catalog_id` pasa a nulo solo mientras `creating`
  (`CHECK`).
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

## 4. Pasos de ejecución

Cada paso dice: **quién** · recibe · toca · acepta si · pruebas · devuelve · depende de ·
¿paralelo? El hilo principal coordina y no escribe código (`qualify-lead`).

**Paso 0 — Ticket y rama.** Hilo principal. Recibe este plan. Crea con `meegle-ticket` las
historias bajo m-25026261 (o usa m-25026261 si el fundador prefiere un solo ticket) y la rama
`feat/m-<id>-catalogo-crear-eliminar` desde `origin/main`. Acepta si: existe el `m-<id>` antes del
primer push. Devuelve: ids y rama. Depende de: aviso del fundador.

**Paso 1 — Pruebas en vivo con el fundador (P-7, P-8, P-9, P-10).** `principal-architect` con el
fundador (que ejecuta en su sesión, §5 pasos F1–F3). Recibe §7 de este plan. Toca:
`docs/plan-video-app-review-catalog-management.md` §7 (resultados). Con el Explorador de la Graph API, token del fundador, sobre
el **portafolio de demostración**: crear un catálogo, renombrarlo, conectarlo a la cuenta de
WhatsApp de demostración, borrarlo estando conectado, listar `owned_product_catalogs`. Acepta si:
cada prueba tiene resultado escrito (comando sin token, código de respuesta, campo leído) y la
ruta (a) o (b) de §3.1 queda elegida. Devuelve: ruta elegida + respuestas reales. Depende de: F1–F3.
No paralelo con el paso 2 (lo condiciona).

**Paso 2 — Contrato técnico y enmienda de ADR 48.** `principal-architect`. Recibe: §3, resultados
del paso 1, `migrations/postgres/versions/0158_whatsapp_catalog_sync.py`,
`packages/api/src/qualify_api/whatsapp/catalog_sync/*.py`, ADR 48. Toca: §13 nuevo de ADR 48
(DDL exacto, firmas de servicio, máquina de la operación, códigos de error, cómo se resuelve la
credencial en la ruta elegida). Acepta si: un ingeniero puede implementar sin preguntar; el DDL
cumple `qualify-migration` (RLS en la misma revisión, `downgrade` completo). Devuelve: §13.
Depende de: 1.

**Paso 3 — Textos y flujo de pantalla.** `ux-designer`. Recibe: §1, §2 fila «Pantalla», §3.4,
`Qualify/catalog_whatsapp_vm.py`, `qualify-copy-es`, `qualify-ux`. Toca: un bloque «Textos» en
§13 de ADR 48 (o `docs/mockups/` si hace falta un mockup). Entrega: el texto del botón de crear,
del estado «creando», del cambio de nombre, de la confirmación de eliminar (con el número de
productos), de los errores, y los **subtítulos en inglés** para el video. Acepta si: sin
anglicismos ni «catálogo de Meta» técnico frente al dueño; un paso, una decisión; legible a 360 px.
Depende de: 2 (puede empezar en paralelo con su borrador).

**Paso 4 — Backend.** `backend-engineer`. Recibe: §13 de ADR 48. Toca: revisión nueva en
`migrations/postgres/versions/` (número provisional; se renumera en el paso 9),
`whatsapp/catalog_sync/client.py` (crear, conectar, renombrar, eliminar, listar propios; métodos
en la clase existente o una clase hermana ligada a un `business_id`), `service.py`
(`create_catalog`, `rename_catalog`, `delete_catalog`, cada uno inserta una operación con
`request_key`), `worker.py` (tercera tarea del tick), `store.py`, `models`, `just` si hace falta.
Acepta si: un doble toque crea una sola operación; un corte entre crear y conectar no deja dos
catálogos (prueba con el falso); eliminar está prohibido sin `created_by_qualify` y con corridas
en vuelo; ningún token ni texto de cliente en logs; credencial solo por `CredentialResolver`; RLS
probado. Pruebas: unitarias offline con `FakeWhatsAppCatalogClient` extendido; `-m db` con
aislamiento tenant A/B sobre `whatsapp_catalog_ops`; `upgrade → downgrade → upgrade`. Devuelve:
commits empujados a la rama. Depende de: 2. Paralelo con 5 (contrato fijo).

**Paso 5 — Pantalla.** `reflex-ui-engineer`. Recibe: §13 de ADR 48, textos del paso 3. Toca:
`Qualify/catalog_whatsapp_{vm,provider,state,page}.py` y sus pruebas. El estado `none` ofrece
«crear» (y conserva «Pedir mi catálogo de WhatsApp» como segunda opción); `connected` muestra el
nombre editable y «eliminar» solo si `created_by_qualify`; estados `creando`/`eliminando` con
consulta periódica. Acepta si: toda acción destructiva tiene confirmación; funciona a 360 px;
sin texto en inglés frente al dueño. Pruebas: VM y estado offline. Depende de: 2, 3. Paralelo con 4.

**Paso 6 — Ruta de inicio de sesión.** Si el paso 1 eligió (a): `backend-engineer` dentro de
m-24789620 añade `catalog_management` + `business_management` a la configuración del registro
integrado y guarda `catalog_ids`. Si eligió (b): `backend-engineer` añade la configuración de
catálogo junto a la de anuncios (`config.py`, ruta OAuth de `connections/`) y
`platform-engineer` prepara `QUALIFY_META_CATALOG_CONFIG_ID` con `just env-stage`. Acepta si: el
fundador, con rol en la app, completa el inicio de sesión sobre el portafolio de demostración y
`/debug_token` muestra los dos permisos. Depende de: 1, F4.

**Paso 7 — Revisión UX local.** `ux-designer`, en navegador a **360 px** sobre la rama, contra la
pila local con el falso de Meta. Devuelve sugerencias para «Sugerencias de UX» del PR (aplicada /
pendiente). Depende de: 4, 5.

**Paso 8 — Revisión de código independiente.** Un subagente que **no** escribió el código, con
`review-agent` sobre el diff completo contra la base de `main`. Acepta si: «No findings» o cada
hallazgo resuelto y re-revisado. Depende de: 4, 5, 6.

**Paso 9 — Renumerar la migración y CI.** `backend-engineer`, al final: `git fetch`, tomar el
número siguiente a la cabeza de `origin/main`, renumerar solo la revisión de la rama;
`just ci-lint`, `just ci-test`, `just test-db`. Abre el PR por REST (`qualify-pr`). Depende de: 7, 8.

**Paso 10 — Fusión y despliegue.** Hilo principal, **solo con el sí del fundador** a esa fusión
y **con la medición del paso 11 ya hecha**: `just merge <pr>` con CI verde; despliegue por la vía
documentada (`qualify-prod-ops`). Si se añadió variable de entorno (ruta b), prepararla **antes**
de fusionar. Tras el despliegue: `just deploy-status qualify-prod` y los logs del
`whatsapp-worker` por `just deploy-logs` para ver que arrancó limpio. Depende de: 9, 11.

**Paso 11 — Medir el worker, ANTES de fusionar (va entre el paso 9 y el 10).**
`platform-engineer`. La regla 9 de `qualify-prod-ops` pide medir bajo su tope todo trabajo nuevo
en el bucle de un worker **antes de encenderlo**, no después, y nunca con `docker` a mano en el
servidor. Se mide en local con el arnés que ya se usó para ADR 48 (PR #618): el bucle real del
`whatsapp-worker`, la imagen de producción, el tope real del compose (256 MiB, sin swap), un
Postgres desechable, un Meta falso y una red sin salida a internet. Los scripts de aquella
medición están guardados fuera del repo, en la carpeta de notas de la sesión
(`wamem-harness/`); llevarlos al repo como `just mem-whatsapp-worker` es un seguimiento ya
propuesto y, si ya existe, se usa esa receta. Escenarios: la tarea nueva sin operaciones; crear y
conectar; renombrar; eliminar; y una carga de 1.000 productos corriendo a la vez. Acepta si: el
pico queda bajo el tope con margen, la memoria no crece por ciclo y el `OutboxTick` mantiene su
ritmo. Devuelve: la tabla de escenarios para la descripción del PR. No hay ruta pública nueva que
probar por el borde (la foto ya usa la de ADR 48 §8); **si el paso 2 añade alguna**, probarla con
`curl` contra el dominio real tras el despliegue (lección del PR #634: una ruta nueva de la API
que no estaba en el Caddy de la app respondía la página web). Depende de: 4, 9.

**Paso 12 — Prueba en producción y grabación.** Fundador (graba) + hilo principal (guía con §6).
Sobre el tenant de demostración: crear, renombrar, subir un producto, eliminar. Acepta si: el video
cumple §0 y §6; el número de Bianki no aparece. Luego el envío (F6).

## 5. Lo que debe hacer el fundador en Meta

| # | Qué | Cuándo |
|---|---|---|
| F1 | Crear el **portafolio de demostración** (p. ej. «Tienda de prueba de Qualify»), distinto de Qualify.co, con él como administrador con control total; 2FA activo | Antes del paso 1 |
| F2 | Una **cuenta de WhatsApp de demostración** en ese portafolio con un número de prueba propio (una SIM barata, nunca el número de Bianki ni su WhatsApp personal) | Antes del paso 1 |
| F3 | En Commerce Manager de ese portafolio, **aceptar los términos de comercio** creando y borrando a mano un primer catálogo, si Meta lo pide (P-10) | En el paso 1 |
| F4 | En el panel de la app: crear la configuración de inicio de sesión de la ruta elegida con `catalog_management` + `business_management` (y en (a), el activo «catálogos») y pasar su id al hilo principal | Antes del paso 6 |
| F5 | Un **tenant de demostración** en Qualify (código de invitación) conectado al portafolio de demostración | Antes del paso 12 |
| F6 | En App Review: pedir los permisos de WhatsApp para terceros + `catalog_management` (+ `business_management` si el panel lo exige aparte), una descripción propia por permiso, los tres videos, e **instrucciones y credenciales de prueba** para que el revisor entre a Qualify | Tras el paso 12 |

## 6. Guion del video

Duración objetivo: 2–3 minutos, 1080p, ventana a 1440 px, subtítulos en inglés del paso 3.

| Seg. | Se ve | Subtítulo (idea, el texto final lo da el paso 3) |
|---|---|---|
| 0–10 | Qualify, sesión del dueño de demostración, Galería › WhatsApp sin catálogo | «A business owner wants a WhatsApp catalog» |
| 10–45 | Toca conectar; **inicio de sesión de Meta completo**: elige su portafolio de demostración, ve y acepta los permisos (incluido `catalog_management`) | «The owner logs in with Facebook and grants catalog_management» |
| 45–70 | Toca «crear»; «Creando…»; aparece el catálogo con su nombre, conectado a su WhatsApp | «The app creates a product catalog in the owner's business» |
| 70–90 | Cambia el nombre del catálogo y guarda | «The owner updates the catalog» |
| 90–115 | Sube un producto de Galería; estado «en WhatsApp» | «Products are added to the catalog» |
| 115–135 | Commerce Manager en otra pestaña: el catálogo con su nombre nuevo y el producto | «The change is visible in Meta Commerce Manager» |
| 135–165 | Toca «eliminar», lee la confirmación, confirma; vuelve al estado sin catálogo; Commerce Manager ya no lo muestra | «The owner deletes the catalog» |

Junto a los otros dos videos del mismo envío (mensaje enviado y recibido; plantilla creada,
m-24789620): si se usa la ruta (a), el inicio de sesión es el mismo registro integrado y puede
grabarse una vez y reutilizarse al principio de cada video; cada permiso conserva su grabación y
su descripción propias `[V F-3]`.

## 7. Riesgos y lo no verificado

| # | Riesgo o duda | Prueba que lo cierra |
|---|---|---|
| R1 / P-7 | El registro integrado no funciona en acceso estándar para alguien con rol en la app `[V F-7]` → la ruta (a) no se puede grabar antes de la aprobación | Paso 1: intentarlo sobre el portafolio de demostración; si falla, ruta (b) |
| R2 | `business_management` tiene que pedirse aparte y su video pide datos de anuncios `[V F-1]` | Ver en el panel de App Review si se añade solo como dependencia; si no, decidir con el fundador si se omite el permiso o se graba su caso |
| R3 / P-8 | Listar `owned_product_catalogs` con el token del dueño (idempotencia de §3.3) | Paso 1 |
| R4 / P-9 | Qué pasa al borrar un catálogo conectado a la cuenta de WhatsApp (¿error, desconexión, mensajes de producto rotos?) | Paso 1, en el portafolio de demostración |
| R5 / P-10 | «Debes aceptar los términos creando tu primer catálogo en Business Manager» `[V F-11]` → el **primer** catálogo de un dueño real podría no poder crearse por API | Paso 1: crear por API en un portafolio sin catálogos previos **antes** de F3; si falla, la pantalla le explica al dueño ese único paso |
| R6 | `owned_product_catalogs` lista `page_id` como «obligatorio» `[V F-13]`, cosa rara para un catálogo de comercio | Paso 1: crear con solo `name` (y `vertical=commerce`, el valor por defecto `[V F-13]`) |
| R7 | Que subir productos cuente como «updates» para el revisor `[NO VERIFICADO]` | El guion muestra renombrar **y** subir |
| R8 | Revisor sin acceso a Qualify → se rechaza **todo** el envío `[V F-4]` | F6: credenciales del tenant de demostración e instrucciones claras |
| R9 | Calendario: el envío de WhatsApp para terceros espera a este plan (D3) `[F]` | Correr los pasos 4–6 en paralelo con m-24789620 |
| R10 | El número de prueba del panel vive en el portafolio de la app y no sirve para el Modelo B; si admite catálogo, `[NO VERIFICADO]` | No se usa; F2 |

## 8. Qué NO entra

Sincronización automática al editar (ADR 48 D2) · importar CSV / `sku` (CAT-03) · catálogos de
varios negocios en una pantalla · desconectar sin borrar (Meta no lo ofrece por el borde de la
WABA `[V F-12]`) · borrar catálogos que no creó Qualify · conjuntos de productos, anuncios de
catálogo, verticales que no sean `commerce` · el registro integrado en sí (es m-24789620) ·
mostrar datos de anuncios para `business_management` (R2 decide).

## Fuentes (acceso 2026-11-13)

- [F-1] Permissions reference (`catalog_management`, `business_management`) — https://developers.facebook.com/docs/permissions/reference/catalog_management
- [F-2] App Review: grabaciones de pantalla — https://developers.facebook.com/docs/app-review/submission-guide/screen-recordings
- [F-3] App Review: guía de envío — https://developers.facebook.com/docs/app-review/submission-guide
- [F-4] App Review: introducción — https://developers.facebook.com/docs/app-review/introduction
- [F-5] Facebook Login for Business (portafolio separado; prueba con rol y control total) y Access levels — https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/ · https://developers.facebook.com/docs/graph-api/overview/access-levels/
- [F-7] Embedded Signup — https://developers.facebook.com/docs/whatsapp/embedded-signup/
- [F-8] Embedded Signup implementation — https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation.md
- [F-9] WhatsApp Cloud API Get Started — https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started.md
- [F-10] Upload inventory (un catálogo por cuenta de WhatsApp) — https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/upload-inventory.md
- [F-11] ProductCatalog reference (actualizar `name`, `DELETE`, términos de comercio) — https://developers.facebook.com/docs/marketing-api/reference/product-catalog/
- [F-12] WhatsApp Business Account `product_catalogs` — https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account/product_catalogs/
- [F-13] Business `owned_product_catalogs` — https://developers.facebook.com/docs/marketing-api/reference/business/owned_product_catalogs/
- `[S]` Aprobación parcial (12 de 15 permisos; anécdota de consultor) — https://singhamandeep.com/?p=3065
