# ADR 43 — Un login, varios negocios, y una suscripción para todos

**Estado:** `[FIRMADO por el fundador, 2026-10-25]` · propuesto por principal-architect el mismo día. Decisiones F1–F5 en §7 y su registro textual en §9; en F2 el fundador eligió una opción distinta de la recomendada (§2.9).
**Ticket:** [m-24849187](https://project.larksuite.com/5h2wsx/issue/detail/24849187) (historia S0) · **Épica:** [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186) (`docs/epica-multi-negocio-una-sesion.md`).
**Reabre:** `docs/modelo-negocio-operador-multi-emprendimiento.md` §6.1 («`1 login = 1 tenant = 1 negocio`, sin switch», firmado el 2026-08-16, revertido por el fundador el 2026-10-23).
**Cambia:** D15 de `docs/modelo-cobro-generacion.md` («todo negocio empieza en Básico»: el plan y el saldo pasan a ser de la suscripción; ver §2.9.3).
**Evidencia de mercado:** `docs/oferta-limites-negocios-por-plan.md` (market-analyst, 2026-10-25, PR #341). Sus cifras son del analista, no decisiones del fundador.
**Numeración:** el ticket y la épica dicen «ADR 41», pero el 41 se firmó el 2026-10-24 para la cola de generación (`docs/adr-41-cola-generacion-concurrencia.md`). El 42 se firmó el mismo 2026-10-25 para «Ideas para tus reels» (`docs/adr-42-ideas-reels-costo.md`, PR #343). Esta decisión es la **43**. La rama del PR conserva el nombre que pidió el ticket (`docs/m-24849187-adr-41-multi-negocio`).
**Convención:** `[V]` verificado en disco o en fuente primaria el 2026-10-25 · `[H]` hipótesis o aritmética del autor.

---

## 0. Resumen

1. **Cada negocio sigue siendo un tenant con RLS** (ADR 24). Lo que cambia es que un login puede ser miembro de varios: una fila `users` por (tenant, login), con `UNIQUE(tenant_id, auth_user_id)` en lugar del `UNIQUE(auth_user_id)` global de hoy.
2. **Cambiar de negocio abre una instancia limpia:** el servidor valida la membresía, emite un pase de un solo uso, **rota el token de sesión de Reflex** y recarga. El estado del negocio anterior queda huérfano y nunca vuelve a pintarse; lo que siga corriendo para él termina en su propio tenant.
3. **Toda generación lleva el negocio sellado desde el servidor** y el worker lo vuelve a comprobar antes de leer el Brand Kit, el catálogo o un archivo y antes de escribir. Publicar y responder nombran el negocio **y** la cuenta de destino.
4. **La suscripción es de quien paga, por encima de los tenants:** tabla `subscriptions` sin `tenant_id`, aislada por GRANT (solo `qualify_admin`), y `tenants.subscription_id`. La app nunca la lee.
5. **Un solo saldo de generación para todos los negocios de la suscripción** (F2), movido por funciones `SECURITY DEFINER` que toman el tenant de la sesión y devuelven solo números; tope opcional por negocio y aviso por porcentaje, los dos como parámetros. Pasa por `security-review`. **Se construye ya** (F3).
6. **Negocios por suscripción:** Básico 2, Plus 3 y Pro 5 incluidos, extras comprables hasta un techo de 8 (F4); son parámetros del catálogo de planes y se controlan en el Alta. Cada negocio extra cuesta en infraestructura menos de USD 0,25 al mes `[H]`.

## 1. Contexto

### 1.1 Qué se revierte y por qué ahora

El 2026-08-16 el fundador firmó «`1 login = 1 tenant = 1 negocio`, sin switch»: cambiar de negocio era salir y volver a entrar con otra credencial guardada (alias `+negocio` por negocio). El 2026-10-23 lo revirtió: un mismo dueño maneja Bianki (shawarma y ensaladas) y Polette (helados de yogur) desde una sola sesión. El 2026-10-25 agregó dos condiciones (§1.3). Una decisión firmada solo se reabre con un ADR: este.

`[V]` Producción el 2026-10-23: 8 tenants, cada uno con 1 marca y 1 dueño; ninguna cuenta de IG está en dos tenants; Bianki no existe todavía. No hay datos que separar.

### 1.2 Qué hay hoy en el código (verificado el 2026-10-25 sobre `main` en `2f2bb984`)

La épica citó líneas el 2026-10-23; varias se movieron. Esta tabla es la vigente.

| Pieza | Estado | Dónde | Deriva frente a la épica |
|---|---|---|---|
| Un login = un negocio | `users.tenant_id NOT NULL` + `UniqueConstraint("auth_user_id", name="uq_users_auth_user_id")` | `packages/api/src/qualify_api/tenancy/models.py:53-75` (la restricción en `:57`) | Igual |
| Membresías con rol | `tenant_members` (owner/admin/agent/viewer), `UNIQUE(tenant_id, user_id)` | `tenancy/models.py:78-97` | Igual |
| Negocio en Supabase | Un solo `app_metadata.tenant_id`, escrito solo por la llamada de administración | `auth/supabase.py:20`, `:63-64` (`_parse_tenant_id`), `:150` | Igual |
| Segundo Alta con un correo ya registrado | `_resolve_identity_for_signup` devuelve el `tenant_id` **ya sellado** | `auth/service.py:96-124` | Igual |
| Mismo correo en otro negocio | «Ese email ya pertenece a otro negocio; usa un alias distinto por negocio.» | `auth/service.py:359-362` | **Era `:333-335`** |
| Negocio activo de la sesión | `AuthState.session_tenant_id`, solo lo escribe el login | `Qualify/auth_state.py:224-229` | — |
| Salir | `logout` revoca en el proveedor, resetea 39 estados y redirige | `Qualify/auth_state.py:852-985` | **Era `:784-888`** |
| Cambio de tenant sin salir (ya existe para el Brand Kit) | `_reset_brand_kit_states` | `Qualify/auth_state.py:470-490` | — |
| Tests de la higiene de salida | orden revocar → resetear → redirigir; lista de estados; **inverso**: todo `rx.State` que lee `AuthState` está en la lista; nada persistido en el cliente | `Qualify/test_auth_state.py:307`, `:319`, `:350`, `:377` | La épica citaba `:318-325`; el test inverso (`:350`) no estaba citado |
| Caches de módulo citados | `planner_state.py:125` y `planner_vm.py:414` **ya no tienen ningún cache**; los que hay son `planner_state.py:150` (`_timezones_for`, husos horarios) y `planner_vm.py:520` (`zone_countries`), datos estáticos | `Qualify/` | **Deriva**; inventario completo en §2.6 |
| Conexiones IG/FB | `UNIQUE(tenant_id, platform, external_account_id)` y `UNIQUE(id, tenant_id)` | `migrations/postgres/versions/0002_connections.py:143-146` | La épica citaba `:143` |
| Publicar en una cuenta de otro negocio | **Imposible por esquema:** FK compuesta `(connection_id, tenant_id)` → `social_connections(id, tenant_id)` en intentos y programaciones | `0003_publishing.py:111-115` (`fk_attempt_conn_tenant`), `:187-191` (`fk_sched_conn_tenant`) | No estaba citado |
| WhatsApp | `UNIQUE(phone_number_id)` global | `0057_whatsapp.py:157` | Igual |
| Cómo sale la generación de la petición | `TaskDispatcher` recibe solo `(tenant_id, draft_id)`; `run_generation` relee el borrador con `tenant_session(tenant_id)` y uno invisible es un no-op | `creative/dispatch.py:92-138`, `creative/service.py:1617-1647` | — |
| Archivos por negocio | `t/{tenant_id}/…` y `require_tenant_prefix` | `packages/shared/src/qualify_shared/objects/keys.py:46`, `objects/gate.py:194` | — |
| Cola de generación | `creative_jobs` con RLS y `creative-worker` **aprobados en ADR 41, sin construir** (cero apariciones en `migrations/` y `packages/`) | `docs/adr-41-cola-generacion-concurrencia.md` | — |
| Cupo de generación | `creation_charges` por `(tenant_id, brand_id, period_month)`, mismo cupo para todos | `0088_creation_charges.py:92-93`, `:163-174` | — |
| Planes y paquetes | `tenant_plan_assignments`, `creation_packs`, `creation_payments` **diseñados, sin construir**; `just set-plan` **no existe** en el `justfile` | `docs/modelo-cobro-generacion.md` D15–D19 | La migración que el diseño llamaba `0089` ya se usó para otra cosa (`0089_monitored_media_thumbnail`) |
| Puertas a la base | **Cinco**, no tres: `tenant_session`, `admin_session`, `credential_session`, `webhook_session`, `webhook_worker_session` | `packages/shared/src/qualify_shared/db/session.py:51`, `admin.py:35`, `credential.py:48`, `webhook.py:55`, `webhook.py:69` | `CLAUDE.md` nombra tres: deriva señalada |

### 1.3 Lo que pidió el fundador el 2026-10-25

1. **Cambiar de negocio es abrir una instancia limpia, con cuidado extremo de no mezclar negocios.** El miedo explícito es publicar o **crear piezas** para el otro negocio. La épica cubría publicar y enviar, no la generación.
2. **La suscripción se comparte entre los negocios del dueño.** Nuevo: la épica dejaba «facturación por operador» fuera de alcance.
3. **Abierto, sin decidir:** cuántos negocios caben en una suscripción.

---

## 2. Decisión

### 2.1 Identidad y membresías (S1, sin cambios frente a la épica)

- Una fila `users` por (tenant, login): `UNIQUE(tenant_id, auth_user_id)` reemplaza `uq_users_auth_user_id`. Los usuarios de un solo negocio no notan nada.
- `memberships_for(auth_user_id)` en `qualify_api.auth`, por `admin_session`, devuelve solo `(tenant_id, nombre, rol)`. Es la única lectura cruzada del camino de login y no devuelve nada más del negocio.
- `app_metadata.tenant_id` de Supabase pasa a ser **solo el negocio por defecto**. **Nunca es autoridad:** qué negocio puede abrir un login lo dicen `users` + `tenant_members`, releídos en el servidor.
- El `auth_user_id` sale siempre de la sesión del servidor, nunca de un argumento del navegador.

### 2.2 Cambiar de negocio = una instancia limpia (S4)

Hoy el estado de Reflex vive en el servidor, atado a un token que cada pestaña guarda en su `sessionStorage`. **Recargar la página conserva el token, y con él el mismo objeto de estado.** Eso deja un hueco concreto: un evento en segundo plano del negocio A (hay 287 en `Qualify/`, `@rx.event(background=True)`) que siga corriendo cuando el dueño cambia a B escribe su resultado, al volver de `async with self`, **en el estado que ya muestra B**. Resetear y recargar, como hace el logout, no lo cierra.

Por eso el cambio no resetea el estado: **lo abandona.**

1. `switch_tenant(destino)` en el servidor: toma el `auth_user_id` de la sesión, comprueba la membresía en el destino **sin caché**, registra el cambio en el tenant de destino (auditoría, S5) y emite un **pase de un solo uso**: 128 bits aleatorios, en Redis solo su hash, 60 s de vida, atado a `(auth_user_id, tenant destino)`, canjeable una vez (`GETDEL`). Mismo patrón que `PieceTokenStore` (`Qualify/piece_download.py:43-56`).
2. El navegador **borra el token de Reflex de `sessionStorage`** y navega a `/cambiar?pase=…`. Sin token, Reflex crea uno nuevo: **un estado nuevo, vacío**.
3. El `on_load` de `/cambiar` canjea el pase, vuelve a comprobar la membresía y llena `session_tenant_id` en ese estado nuevo. Un pase vencido, usado o ajeno lleva a `/login`.
4. El estado viejo queda huérfano: nadie lo vuelve a servir y caduca con la vida normal de los estados. Lo que corra todavía para A escribe en ese estado huérfano y en las filas de A.

El token de Supabase de la sesión (`_access_token`, solo del servidor) viaja dentro del pase, que vive 60 s en Redis y se borra al canjearlo; así el logout del estado nuevo puede seguir revocándolo. **Requiere la revisión de `security-review` antes de construir S4**: es la primera vez que ese token toca Redis.

`[H]` Que borrar la clave del token en `sessionStorage` produzca un estado nuevo es el comportamiento de Reflex 0.9.x leído en su cliente, no medido aquí. **Es criterio de aceptación de S4 y se prueba con Playwright antes de cualquier otra cosa;** si no se cumple, S4 no se construye sin volver a este ADR.

### 2.3 Dos pestañas con negocios distintos (S3, S4)

Definición precisa, consecuencia de §2.2:

- **Cada pestaña es su propia sesión con su propio negocio activo.** Cambiar en una no cambia la otra. Una pestaña nueva abre sin sesión (como hoy) y pide entrar y elegir negocio.
- **Lo que una pestaña hace, lo hace siempre en el negocio que muestra**, porque la acción la ejecuta el mismo estado que pintó la pantalla. Una pestaña nunca actúa en el negocio de otra.
- **«Duplicar pestaña» del navegador** copia el `sessionStorage` y puede compartir el estado. Antes de un cambio, las dos muestran el mismo negocio (sin riesgo); el primer cambio en una rota su token y la separa. Se prueba en S4.
- **Siempre visible cuál es:** el chip «Estás en {negocio}» (S3) y el título de la pestaña «{negocio} · Qualify», para distinguirlas en la barra del navegador. Sin un segundo color: el isotipo es monocromo.
- Un identificador que llega del navegador (el `draft_id` de la URL, el id de una conversación) se busca siempre con `tenant_session` del negocio de la sesión: si es de otro negocio, no existe. Así ya funciona hoy (`Qualify/creative_state.py:6050-6070`, `UnknownDraft`).

### 2.4 La generación lleva el negocio sellado (historia nueva S9, [m-24854772](https://project.larksuite.com/5h2wsx/issue/detail/24854772))

Normativo para todo trabajo que genera: copy y ángulos con Claude, imágenes con Seedream, video con Seedance, presentador con OmniHuman, voz con Seed Speech, render de Remotion, la precarga del Alta y el futuro `creative-worker` de ADR 41.

1. **Al encolar**, el `tenant_id` sale de la sesión del servidor (`AuthState.session_tenant_id`, por `_session_ids()`, `creative_state.py:2100`) y se guarda **una sola vez** al principio del manejador. Nunca de un argumento del evento, nunca releído a mitad de camino. En la cola de ADR 41, `creative_jobs.tenant_id` se escribe en el mismo `INSERT` que el cobro, dentro de `tenant_session` de ese negocio (la política `WITH CHECK` impide escribir otro).
2. **El worker vuelve a comprobar antes de leer**: abre `tenant_session(job.tenant_id)` y relee el borrador, el brief, la marca, el Brand Kit y los productos **por esa sesión**. Si alguno no aparece (RLS lo oculta si es de otro negocio), el trabajo termina `tenant_mismatch`, **sin llamar a ningún proveedor y devolviendo el cobro**. Hoy `run_generation` ya hace la primera mitad (`service.py:1630-1632`); falta el motivo propio y el test.
3. **Antes de cada archivo**: toda clave de R2 que se lee (foto del catálogo, logo, voz, video de referencia) o se escribe (resultado, miniatura, final) pasa por `require_tenant_prefix(job.tenant_id, clave)`. Las URL firmadas que reciben BytePlus y Remotion se generan solo desde claves que pasaron ese control. Una clave de otro negocio es `TenantPrefixViolation` **antes** de cualquier llamada pagada.
4. **Al escribir**, todas las filas (variantes, `image_assets`, `creative_usage_events`, `creative_vendor_tasks`) se escriben por la misma `tenant_session(job.tenant_id)`.
5. **El precio va antes que el proveedor**: el control de precio y cupo de ADR 41 corre después de 2 y 3, de modo que un trabajo rechazado por negocio no cuesta nada.
6. **Procedencia**: el trabajo y su resultado registran `tenant_id`, `brand_id` y la versión de pipeline que ya llevan; el registro de la llamada al proveedor lleva el `tenant_id` (no el nombre del negocio) para poder auditar.

### 2.5 Publicar y responder nombran el negocio y la cuenta de destino (S4, S5)

- Los textos de confirmación de la épica cambian para decir **dónde** sale (ver §4). La cuenta (`@usuario`, nombre de la Página o número de WhatsApp) **se relee del servidor en el momento de confirmar**, por `tenant_session`, a partir de la conexión de la publicación; no se toma de lo que la pantalla tenía cargado.
- La confirmación del final de ADR 41 en «Tu semana» y el correo de la mañana dicen el negocio en el asunto y en cada pieza.
- El servidor, al publicar o enviar, vuelve a comprobar la membresía sin caché (S5). La FK compuesta de `0003_publishing.py` ya impide, a nivel de esquema, programar una pieza de A en una cuenta de B.

### 2.6 Trabajos en curso cuando el dueño cambia de negocio (S4, S9)

- **Terminan en su propio negocio.** El resultado, el cobro, la devolución si falla y el aviso quedan en A.
- **Nunca aparecen en B.** B lista piezas, avisos y contadores por `tenant_session(B)`; lo que corre para A escribe, como mucho, en el estado huérfano de §2.2.
- **Al volver a A**, el dueño ve el resultado en «Tus creaciones» como cualquier pieza terminada, y el aviso de Inicio («Tu pieza está lista») si corresponde. No hay notificación cruzada («tu pieza de A está lista») dentro de B: si el fundador la quiere, es otra historia.
- Un trabajo de la cola (ADR 41) no depende de que alguien mire: sigue igual aunque el dueño cierre la pestaña.

### 2.7 Caches de proceso: inventario (S4)

Auditoría del 2026-10-25 sobre `Qualify/` y los paquetes del backend: `@cache`, `lru_cache`, `global` y diccionarios de módulo. **Ninguno guarda datos de un negocio con una clave sin negocio.** El cache que importa es el estado de Reflex, y lo cubre §2.2.

| Dónde | Qué guarda | Clave | Veredicto |
|---|---|---|---|
| `Qualify/r2_media.py:116` `_issued` | URL de vista de un archivo de R2 | `(tenant_id, clave, …)` (`:94`) | Con negocio: bien |
| `Qualify/reels_discovery.py:918-926` `_cache`, `_brand_locks`, `_reads` | Lectura de reels de los referentes | `(tenant_id, brand_id, días)` (`:929-930`) | Con negocio: bien |
| `Qualify/reels_discovery.py:350-355` `_transcripts` | Transcripción de un reel público | red + id del reel | Dato público, se comparte a propósito (ahorra pagar dos veces) |
| `Qualify/reels_discovery.py:562` `_verdicts` | Veredicto de Claude sobre un reel | (brief completo, reel) | La clave **es** toda la entrada: dos negocios solo comparten si escriben el mismo brief. No filtra nada |
| `Qualify/avatar_proxy.py:98, 255, 294, 445` | Fotos de perfil públicas, fallos, candados | red + usuario | Dato público |
| `packages/api/.../hashtags/catalog.py:247` `_choices` | Elección de hashtags | tupla de palabras | Catálogo global por diseño |
| `Qualify/creative_wizard_pages.py:6723` `_LABEL_LOCKS` | Un candado por marca | `brand_id` | Solo candados, sin datos |
| `Qualify/planner_state.py:150`, `planner_vm.py:520`, `packages/creative/.../compose.py:108,120`, `pricing.py:23`, `creations.py:286` | Husos horarios, países, fuentes, tablas de precios y pesos | datos estáticos | Sin negocio |
| `catalog_provider.py:45`, `piece_download.py:61`, `r2_media.py:53,64`, `stock_provider.py:57`, `variations_provider.py:117`, los `_GATEWAY` / `_SERVICE` de `followups`, `conversations`, `whatsapp_chats`, `ice_breakers`, y los `@cache` de `*/composition.py` | Servicios armados una vez por proceso | — | Sin estado por negocio: cada método recibe `tenant_id` |

El control que lo mantiene: el test inverso de `test_auth_state.py:350` solo encuentra clases escritas como `class X(rx.State)` en un archivo que contiene `get_state(AuthState)`. S4 lo cambia por una enumeración en tiempo de ejecución de **todas** las subclases de `rx.State` y una lista explícita de las que no guardan nada del negocio, más un test que falla si aparece un diccionario o un `@cache` de módulo nuevo en `Qualify/` sin estar en una lista revisada.

### 2.8 La suscripción compartida: el modelo (historia nueva S10, [m-24854773](https://project.larksuite.com/5h2wsx/issue/detail/24854773))

**Separar dos cosas que hoy nadie distingue:** quién puede **entrar** a un negocio (membresía: `users` + `tenant_members`, por tenant) y quién **paga** por él (suscripción, por encima de los tenants). Son independientes: el dueño de Bianki y Polette paga una suscripción y es miembro de los dos; mañana una persona del equipo del dueño puede ser miembro de un negocio sin tener nada que ver con la factura.

**Tablas (migración nueva, número contra `origin/main` al escribirla; hoy la cabeza es `0092`):**

| Tabla | Columnas | Aislamiento |
|---|---|---|
| `subscriptions` | `id`, `display_name`, `billing_owner_auth_user_id` (quien paga; puede ser NULL para una cuenta del equipo), `max_businesses` (NULL = lo que diga el plan), `status` (`active`/`paused`/`closed`), `created_via` (id del ítem de Meegle), `created_at` | **Sin `tenant_id`, aislada por GRANT:** `ENABLE` + `FORCE ROW LEVEL SECURITY` **sin ninguna política** (todo rol sin BYPASSRLS ve cero filas) y GRANT solo a `qualify_admin`. Excepción deliberada a «todo lleva `tenant_id`», declarada en el docstring de la migración, con un test que prueba que `qualify_app` no puede leerla |
| `subscription_plan_assignments` | `subscription_id`, `plan` (`basico`/`plus`/`pro`), `effective_month`, origen, motivo, quién, clave de idempotencia | Igual que `subscriptions`. **Reemplaza** a `tenant_plan_assignments` del diseño de D15, que no se llegó a construir |
| `tenants.subscription_id` | `uuid NOT NULL` FK a `subscriptions` | La columna vive en `tenants`, que ya tiene RLS por `id`; el negocio puede ver **el id** de su suscripción, no la fila |
| `subscription_pool_months`, `subscription_pool_business_usage`, `subscription_pool_movements` | El saldo común, lo usado por negocio y cada movimiento (§2.9.1) | Sin política; GRANT solo a `qualify_pool` (dueño de las funciones) y `qualify_admin`. La app las toca solo a través de `pool_reserve` / `pool_release` / `pool_balance` |
| `creation_packs`, `creation_payments` (D12, D19) | Como en el diseño de D17, pero con `subscription_id` | Los paquetes son **de la suscripción** y suman al saldo común; los pagos, solo `qualify_admin`, como ya decía el diseño |

**Por qué así y no una política propia:** cualquier lectura de la suscripción desde la app tendría que cruzar tenants (una suscripción tiene varios), y eso exige o bien una política con subconsulta, que rompe la forma única de la política (`test_rls_policy_shape`), o bien `admin_session` en el camino de la petición, que es la puerta que salta RLS. Ninguna de las dos hace falta: **el equipo escribe la suscripción** (por `just` y por el Alta, ambos fuera de la petición, por `admin_session`), y el único dato cruzado que la petición necesita, el saldo común, sale de las funciones de §2.9.1 como un número, sin que la app lea ninguna fila de otro negocio.

**Relleno inicial:** una suscripción por cada tenant que existe (1:1), con su plan actual (sin fila = Básico). Nadie nota nada.

**Cómo el Alta (S7) une un negocio a una suscripción.** El ítem «Alta de cliente» gana un campo **«Suscripción»** con dos valores: «Nueva» (por defecto) o «La de {correo del dueño}». Con «La de…»:

1. El servicio del Alta (webhook-worker, `admin_session`, fuera de la petición) busca la suscripción cuyo `billing_owner_auth_user_id` es ese login. Cero o más de una: el Alta falla a la vista con un comentario en el ítem; nunca adivina.
2. **Toma la fila de la suscripción con `SELECT … FOR UPDATE`**, cuenta sus tenants activos y compara con el máximo efectivo (§2.10). Así dos Altas a la vez no pasan las dos.
3. Crea el tenant con `subscription_id` y su fila del mes en `subscription_pool_business_usage` (con el tope opcional del campo «Tope de este negocio»); si el negocio pasa de los incluidos, registra el negocio extra comprado. Todo en la misma transacción.
4. Todo con clave de idempotencia por ítem de Meegle: repetir el evento no crea un segundo negocio.

«Inicio de sesión existente» (membresía, ya en S7) y «Suscripción» (factura) son campos distintos: lo normal es que vayan juntos, pero no se obligan.

### 2.9 Cupo común para todos los negocios de la suscripción (F2 = B, firmado)

El fundador eligió **B: un solo saldo para todos los negocios de la suscripción** (2026-10-25), en lugar de la C que recomendaba este ADR. Con el diseño de D15, 3 negocios eran 3 × USD 55 = **USD 165 de peor caso**; con el saldo común, el peor caso es el del plan (**USD 55** en Básico) con 1 o con 5 negocios (aritmética del analista sobre `modelo-cobro-generacion.md` §6). Qué ve el dueño: «Te quedan 18 de 30 este mes, entre tus 2 negocios».

#### 2.9.1 El problema técnico y cómo se resuelve sin saltarse RLS

Cobrar una creación exige saber cuánto queda del saldo común, y ese saldo lo gastan **varios tenants**. Desde `tenant_session` del negocio A no se puede leer lo que gastó B (RLS), y no se debe usar `admin_session` en la petición. La solución es un **contador propio de la suscripción** que nadie lee directamente, movido solo por **funciones `SECURITY DEFINER`** que toman el tenant de la sesión y devuelven solo números.

**Tablas del contador** (migración de S10; sin política RLS para ningún rol de la app: `ENABLE` + `FORCE ROW LEVEL SECURITY` sin política, GRANT solo al dueño de las funciones y a `qualify_admin`):

| Tabla | Qué guarda | Clave |
|---|---|---|
| `subscription_pool_months` | Cupo del mes de la suscripción (plan + paquetes vigentes, escrito por el equipo al asignar plan o paquete) y lo usado: `creations_used`, `videos_used`, `previews_used` | `(subscription_id, period_month)` |
| `subscription_pool_business_usage` | Lo usado por cada negocio en el mes, su tope opcional (`cap_creations`, `cap_videos`, `cap_previews`; NULL = sin tope) y `alert_sent_at` | `(subscription_id, tenant_id, period_month)` |
| `subscription_pool_movements` | Cada reserva y cada devolución, con su clave de idempotencia `(draft_id, revision, kind, movement)` `UNIQUE`, el tenant, la cantidad y qué fuente pagó (plan o paquete, D17) | Procedencia y conciliación |

**Las funciones** (`pool_reserve`, `pool_release` y `pool_balance`):

1. **De dónde sale el tenant:** de `NULLIF(current_setting('app.tenant_id', true), '')::uuid`, el mismo valor que usa la política RLS. Sin tenant en la sesión, la función lanza un error. **Nunca recibe un `tenant_id` ni un `subscription_id` como argumento.**
2. **De dónde sale la suscripción:** de `tenants.subscription_id` del tenant de la sesión. Las funciones son propiedad de un rol propio, `qualify_pool` (`NOLOGIN`, `NOBYPASSRLS`): al leer `tenants`, la política RLS de esa tabla le deja ver **solo la fila del tenant de la sesión**. La función no puede ver otro tenant aunque quisiera.
3. **Qué tocan:** solo las tres tablas del contador (GRANT por tabla a `qualify_pool`). No leen `creation_charges` ni ninguna tabla de negocio.
4. **Cómo reserva** (`pool_reserve(kind, units, draft_id, revision)`): bloquea la fila del mes de la suscripción con `SELECT … FOR UPDATE` (serializa los cobros de una suscripción, no los de otras), comprueba el saldo común **y** el tope del negocio si lo tiene, suma lo usado y escribe el movimiento. Si la clave de idempotencia ya existe, no hace nada y devuelve el mismo resultado. Devuelve `ok`, `pool_left`, `business_used`, `business_cap` y `alert` (verdadero una sola vez al mes, cuando el negocio cruza el umbral de §2.9.2).
5. **Cómo devuelve** (`pool_release(kind, units, draft_id, revision)`): resta lo usado una vez por clave; una devolución sin reserva previa no hace nada.
6. **Qué devuelven:** números del saldo común y del propio negocio. **Nunca** cuánto gastó cada uno de los otros negocios ni quiénes son.
7. **Endurecimiento obligatorio:** `SET search_path = pg_catalog, public` fijado en la definición, nombres calificados, `REVOKE ALL ON FUNCTION … FROM PUBLIC` y `GRANT EXECUTE` solo a `qualify_app`.
8. **Atomicidad con el cobro de hoy:** `pool_reserve` se llama dentro de la misma transacción de `tenant_session` que inserta la fila de `creation_charges` (`0088`). Si el `INSERT` falla, la reserva se deshace con él; si la reserva dice que no, no se inserta nada. `creation_charges` sigue siendo la procedencia por negocio; el contador es solo el saldo. Las devoluciones (generación fallida, final que falla) llaman a `pool_release` en la misma transacción que marcan la fila `refunded`.
9. **Conciliación:** un trabajo diario del equipo (`calendar-worker`, `admin_session`, fuera de la petición) compara, por suscripción y mes, la suma de `creation_charges` con `subscription_pool_months` y avisa en Lark si no cuadran.

**Por qué esto respeta las reglas:** la política RLS no cambia de forma, ningún rol nuevo tiene `BYPASSRLS`, el rol de la aplicación sigue sin poder leer nada de otro tenant y lo único cruzado que sale de la base es un número agregado. **Es una puerta nueva de la base** (la primera función `SECURITY DEFINER` del repo; `0044_social_account_claims.py:18` la había evitado a propósito), y por eso **S10 no se fusiona sin la revisión de `security-review`** de las funciones, sus GRANT y sus tests.

#### 2.9.2 Las protecciones para que un negocio no se lleve todo el saldo

Las dos son parámetros; ninguna es un número en el código.

| Protección | Dónde vive | Quién la pone | Qué pasa |
|---|---|---|---|
| **Tope por negocio (opcional)** | `subscription_pool_business_usage.cap_*`, por contador; NULL = sin tope | El equipo, en el Alta (campo «Tope de este negocio», vacío por defecto) o con `just pool-cap` | `pool_reserve` rechaza la creación aunque quede saldo común. El dueño ve «Este negocio ya usó lo que tenía reservado este mes. Pide más a Qualify.» |
| **Aviso por porcentaje** | `alerta_negocio_pct` en el catálogo de planes; `subscriptions.alert_business_pct` lo cambia para una suscripción | El catálogo (PR) o el equipo | Cuando un negocio cruza ese porcentaje del saldo común del mes, `pool_reserve` devuelve `alert = true` una sola vez; el servicio avisa al equipo en Lark (mismo canal que D18) y muestra en ese negocio «Este negocio ya usó el {X} % del cupo que compartes con tus otros negocios.» Nunca bloquea |

#### 2.9.3 Qué cambia en D15 y en lo diseñado

- **D15:** «todo negocio empieza en Básico» pasa a **«toda suscripción empieza en Básico; sus negocios comparten un solo saldo»**. Con un negocio por suscripción (todos los de hoy) el resultado es idéntico.
- **Planes y paquetes (m-24852145)** se construyen con la forma de la suscripción: `subscription_plan_assignments` reemplaza a `tenant_plan_assignments`; los **paquetes de 90 días son de la suscripción** y suman al cupo de `subscription_pool_months`; D17 (primero el plan, después el paquete que vence antes) se aplica dentro de `pool_reserve`, que registra en el movimiento qué fuente pagó.
- **El tope de alerta en dólares (D18)** pasa a ser por suscripción, calculado por el trabajo diario del equipo (fuera de la petición). El freno duro por marca (`creative_engine_config.monthly_budget_cap_usd`) queda solo para emergencias, como ya decía D18.
- **Se construye ya** (F3): no hay fase manual de 60 días. Bianki y Polette arrancan en una suscripción compartida con saldo común. Desaparece `tenant_quota_allotments` del diseño anterior: cada negocio lee el saldo con `pool_balance()`.

### 2.10 Cuántos negocios por suscripción (F4, firmado)

**Valores firmados:** Básico **2**, Plus **3** y Pro **5** negocios incluidos; se pueden comprar negocios extra hasta un **techo de 8 por suscripción**.

**Son parámetros, nunca números en el código.** Viven en el catálogo versionado de planes (`creations_data/planes-v<n>.json`, diseño de D15) como `negocios_incluidos` por plan y `negocios_techo` (8); `subscriptions.extra_businesses` cuenta los extras comprados y `subscriptions.max_businesses` puede fijar una excepción negociada. Máximo efectivo = `min(negocios_incluidos + extra_businesses, max_businesses o negocios_techo)`. Cambiar un valor del catálogo es un PR, como cualquier cambio de plan.

**Dónde se controla:** solo en el Alta (§2.8, paso 2), porque es la única puerta para agregar un negocio. Pasar de los incluidos exige marcar en el Alta «Negocio extra comprado»; pasar del techo no se puede. Bajar un valor nunca cierra un negocio que ya existe: impide el siguiente.

**Lo que cuesta un negocio más** (lo que el negocio cuesta exista o no uso; la generación se paga por uso y queda fuera):

| Concepto | Por negocio y mes | Tipo |
|---|---:|---|
| Almacenamiento en R2: Brand Kit + catálogo (~75 MB) + piezas con 90 días de retención (ADR 39; ~0,2–0,7 GB a uso típico) a USD 0,015/GB | ≤ USD 0,015 | `[H]` calculado, sin medir por tenant |
| Postgres: decenas de miles de filas al año, en la misma base del VPS | USD 0 | `[H]` |
| Conexiones de Meta: sin precio; `conversations-worker` sincroniza cada cuenta de IG cada 300 s (12 llamadas por hora, contra un límite de 200 por Página y app) | USD 0 | `[V]` `conversations/worker.py:30,56` |
| Workers: los mismos procesos recorren un tenant más por vuelta | USD 0 hasta cientos de negocios | `[H]` |
| Supabase: el mismo login no suma usuarios activos | USD 0 | `[H]` precio por usuario activo, a verificar |
| Correo de la mañana de ADR 41 (Resend): ~22 correos al mes por persona que aprueba, en cada negocio | USD 0 hasta ~100 negocios; luego ~USD 0,20 | `[V]` cifras de `adr-41-cola-generacion-concurrencia.md` §3.6 |
| Langfuse: las trazas de producción están apagadas (ADR 40) | USD 0 | `[V]` |
| Precarga del Alta (una vez, no por mes): tope USD 0,15, media medida USD 0,0275 | ≤ USD 0,15 una vez | `[V]` `epica-prellenado-brand-kit-alta.md:118` |
| Atención del equipo: el Alta, conectar los activos de Meta, dudas | Sin medir | El costo fijo real, y el que más pesa |

**Total de infraestructura: menos de USD 0,25 por negocio al mes** `[H]`. El tope de negocios no protege la infraestructura; protege el saldo común (más negocios, menos cupo por negocio) y el tiempo del equipo. La medición por tenant que pide el analista (llamadas a Meta, GB en R2, mensajes) es criterio de S10 para fijar el precio del negocio extra.

**El tope visto desde Meta** (hallazgo 3 del analista). Una corrección: el carril de acceso de Meta **es de la app de Qualify, no de cada suscripción**. La fila «my app is only for a business I own or manage» (Standard Access, sin App Review) vale para Qualify solo mientras **todos** los activos conectados sean de negocios que Attitude Factory posee o administra, y los conecte alguien con un rol en la app (ADR 29). El primer cliente externo que conecte su propia cuenta exige Advanced Access y App Review **por permiso**, tenga ese cliente 1 negocio o 8. Por eso:

- El tope de negocios **no cambia el carril de Meta** de Qualify; lo cambia el primer cliente externo. `V-TP-7` sigue abierto y no lo cierra este ADR; se resuelve como manda ADR 25, en vivo contra el panel de la app, no contra la documentación.
- Lo que sí toca a Meta es **de quién son los activos** que entran en una suscripción. Una suscripción con muchos negocios de dueños distintos es una agencia con otro contrato (`oferta-mercado-agencia-gestionada.md`). El control no es el número, es el Alta: el campo «Suscripción: la de {correo}» exige que el equipo confirme en el ítem que el negocio nuevo es **del mismo dueño o lo administra él** (sí/no), y un «no» deja el Alta como suscripción nueva.
- Los valores que firmó el fundador (2 / 3 / 5, techo 8) coinciden con los del analista y entran como valores del parámetro; no hizo falta ningún cambio de diseño.

### 2.11 Qué no cambia

- **Tenant = frontera de aislamiento (ADR 24)**, y `tenant_id` ≠ `brand_id`. La suscripción es un nivel **encima** de los tenants y **no** entra en ninguna clave de tabla de negocio ni del plano analítico.
- **Una sola Postgres (ADR 31).** Ningún almacén, runtime, cola ni proveedor nuevo: Redis ya existe y ya guarda pases del mismo tipo.
- **La forma de la política RLS no cambia.** Las tablas nuevas de negocio llevan la política estándar; las de la suscripción y del saldo común quedan fuera del alcance de `qualify_app` por GRANT. La única puerta nueva son las funciones del saldo (§2.9.1), sin `BYPASSRLS`.
- **Workers y webhooks** siguen resolviendo el tenant como hoy; S6 cierra la única ambigüedad (una cuenta de IG/FB en dos tenants).
- **El superadmin del equipo** sigue siendo otra épica. La facturación automática (proveedor de pago) sigue fuera: D19, cobro a mano.

---

## 3. Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Seguir con logout + login y alias `+negocio` (§6.1) | El fundador lo revirtió; además deja el cambio de negocio en manos del gestor de contraseñas del navegador |
| Cambiar de negocio reseteando el estado en el mismo token (como el logout) | Un evento en segundo plano de A escribe en el estado de B al volver (§2.2). Rotar el token lo hace imposible en lugar de improbable |
| Guardar el negocio activo en una cookie o en `localStorage` | El negocio activo es autoridad; vive en el servidor y se valida contra la membresía. El cliente no persiste nada del negocio (criterio 2 de la higiene) |
| Una puerta nueva `operator_session` con identidad global de operador (opción (c) de `modelo-negocio-operador-multi-emprendimiento.md` §3) | No hace falta para cambiar de negocio, que es lo pedido; la vista de cartera sigue fuera. Se reabre si llega la vista unificada |
| Suscripción con política RLS propia (subconsulta sobre `tenants`) | Rompe la forma única de la política y su test, y deja leer a la app algo que solo escribe el equipo |
| Saldo común leído con `admin_session` en la petición | Usaría en la petición la puerta que salta RLS para todo, para leer un número |
| Saldo común sumando `creation_charges` de todos los tenants en cada cobro | Exige leer filas de otros tenants; el contador propio de §2.9.1 da el mismo número sin leerlas |
| C: cupo común en la factura y repartido por negocio (lo que recomendaba este ADR) | El fundador eligió B (F2): el dueño quiere un saldo que use donde lo necesite; las protecciones de §2.9.2 cubren el riesgo de que un negocio se lo lleve |
| Construir la suscripción después de 60 días de factura a mano | El fundador eligió construir ya (F3) |
| Cupo por marca dentro de un solo tenant (Bianki y Polette como dos marcas de un tenant) | Mezcla en un tenant dos negocios con cuentas, clientes y dueños de activos distintos; la épica decidió tenant por negocio (D1 de §6 del modelo de negocio) |

## 4. Criterios de aceptación verificables, por historia

Los textos que ve el dueño siguen `qualify-copy-es`; los nuevos o cambiados van marcados.

| # | Criterio | Historia |
|---|---|---|
| A1 | Un trabajo de generación con `tenant_id` A y `draft_id` de B no llama a ningún proveedor, no cobra y termina `tenant_mismatch` (test con proveedores falsos que fallan si se los llama) | **S9** |
| A2 | Un brief que referencia una clave de R2 `t/{B}/…` desde un trabajo de A lanza `TenantPrefixViolation` antes de firmar ninguna URL ni llamar a BytePlus o Remotion | **S9** |
| A3 | Test estático: ningún llamado a `dispatch_generation`, `dispatch_finalize` ni al encolado de `creative_jobs` toma el `tenant_id` de un argumento del evento; todos lo toman de `_session_ids()` o equivalente | **S9** |
| A4 | Con la cola de ADR 41: el `creative-worker` abre `tenant_session(job.tenant_id)` para todo lo que lee y escribe; un test con dos tenants prueba que el resultado y el cobro quedan solo en el del trabajo | **S9** (con la épica m-24852152) |
| A5 | Playwright: borrar la clave del token en `sessionStorage` y recargar da un estado nuevo de Reflex (prueba previa de §2.2; si falla, S4 se detiene y vuelve al ADR) | **S4** |
| A6 | Playwright: en A se pide una generación lenta (proveedor falso de 30 s); se cambia a B; al terminar, nada de A aparece en B (lista, avisos, contadores, errores), y al volver a A la pieza está | **S4** |
| A7 | El pase de cambio: un solo uso, 60 s, atado a login y destino; vencido, repetido o de otro login lleva a `/login`; en Redis solo el hash. Revisado por `security-review` | **S4** |
| A8 | Dos pestañas, A y B: publicar en la pestaña A publica en la cuenta de A aunque la B se haya abierto después; cambiar de negocio en una no cambia la otra; «Duplicar pestaña» y luego cambiar en una deja la otra en el negocio anterior | **S4** |
| A9 | El título de la pestaña es «{negocio} · Qualify» y el chip «Estás en {negocio}» está en todas las páginas con sesión | **S3** |
| A10 | Confirmar publicación: **«Vas a publicar en {negocio}, en Instagram @{usuario}. ¿Seguimos?»** (cambia el texto de la épica); en Facebook, «en la página {nombre}»; la cuenta se relee del servidor al confirmar (test: cambiar la conexión entre abrir y confirmar muestra la nueva) | **S4** |
| A11 | Confirmar respuesta: **«Vas a responder como {negocio} (@{usuario}). ¿Seguimos?»**; en WhatsApp, **«Vas a responder como {negocio} desde el {número}. ¿Seguimos?»** | **S4** |
| A12 | La confirmación del final y el correo de la mañana de ADR 41 dicen el negocio en el asunto y en cada pieza | **S4** (con la épica m-24852152) |
| A13 | Test de cobertura del cambio de negocio: enumera en ejecución todas las subclases de `rx.State`; cada una está en la lista de lo que el cambio abandona o en una lista explícita de estados sin datos del negocio | **S4** |
| A14 | Test: no aparece en `Qualify/` un diccionario de módulo, un `@cache` o un `lru_cache` nuevo sin estar en la lista revisada de §2.7 | **S4** |
| A15 | Publicar y enviar comprueban la membresía sin caché; quitar a alguien de un negocio con la sesión abierta bloquea su siguiente publicación con «Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro.» | **S5** |
| A16 | `subscriptions`, `subscription_plan_assignments` y las tres tablas del saldo: test de base de datos que prueba que `qualify_app` no lee ni escribe ninguna fila directamente | **S10** |
| A17 | Relleno: cada tenant existente queda con su propia suscripción y su plan; el saldo que ve cada negocio no cambia | **S10** |
| A22 | `pool_reserve` / `pool_release` / `pool_balance`: con dos tenants en una suscripción, A gasta y B ve bajar el saldo común, pero ninguna llamada desde A devuelve cuánto gastó B; sin `app.tenant_id` lanzan error; una reserva repetida con la misma clave no cobra dos veces; dos reservas concurrentes nunca dejan el saldo negativo (test con dos transacciones) | **S10** |
| A23 | Las funciones tienen `search_path` fijo, `EXECUTE` solo para `qualify_app` y son propiedad de `qualify_pool`, sin `BYPASSRLS`; un test lo comprueba en el catálogo de Postgres. **Revisión de `security-review` antes de fusionar** | **S10** |
| A24 | Tope por negocio: con el tope de A alcanzado, A no puede crear aunque quede saldo común y ve «Este negocio ya usó lo que tenía reservado este mes. Pide más a Qualify.»; B sigue creando | **S10** |
| A25 | Aviso: cuando A cruza `alerta_negocio_pct` del saldo común, el equipo recibe un aviso en Lark y A ve «Este negocio ya usó el {X} % del cupo que compartes con tus otros negocios.», una sola vez al mes; el porcentaje sale del catálogo o de la suscripción, nunca del código | **S10** |
| A26 | El cobro en `creation_charges` y la reserva van en la misma transacción, y también la devolución y la liberación: si uno falla, no queda el otro (test) | **S10** |
| A27 | Conciliación diaria: la suma de `creation_charges` por suscripción y mes cuadra con `subscription_pool_months`; si no, aviso en Lark | **S10** |
| A18 | Alta con «Suscripción: la de {correo}»: une el negocio a esa suscripción con su tope opcional y es idempotente; pasar de los incluidos exige «Negocio extra comprado»; con el máximo efectivo alcanzado (nunca más de 8), falla a la vista con un comentario en el ítem; dos Altas a la vez no superan el máximo (test con dos transacciones) | **S7** (requiere S10) |
| A19 | El Alta con «Suscripción: la de…» exige la confirmación «el negocio es del mismo dueño o lo administra él»; sin ella, queda como suscripción nueva | **S7** |
| A20 | Ni los negocios incluidos (2 / 3 / 5) ni el techo (8) ni el porcentaje de aviso aparecen como números en el código (test: salen del catálogo de planes o de `subscriptions`) | **S10** |
| A21 | Medición por negocio (llamadas a Meta, GB en R2, mensajes) en el informe del equipo, para fijar el precio del negocio extra; no bloquea la construcción | **S10** |

## 5. Consecuencias

**Positivas.** Un dueño con varios negocios trabaja en una sola sesión. El cambio de negocio deja de depender de que un reset no olvide nada: el estado viejo no se reutiliza. La generación gana la misma garantía que publicar ya tenía por esquema. El dueño tiene un solo saldo para sus negocios y el peor caso queda acotado al plan.

**Negativas.** Cambiar de negocio cuesta una carga completa de página (1–2 s) y deja estados huérfanos hasta que caducan (memoria del backend; acotada por la vida de los estados). El pase lleva el token de Supabase por Redis durante 60 s. **Una puerta nueva de la base:** las funciones `SECURITY DEFINER` del saldo, con su rol `qualify_pool`, su revisión de seguridad y sus tests. Los cobros de una misma suscripción se serializan en una fila (a este volumen, milisegundos). Cinco tablas quedan sin `tenant_id` como columna de aislamiento, con su test. Un negocio sin tope puede gastar el saldo de los otros: es la contrapartida de B, aceptada por el fundador.

**Riesgos.**

| Riesgo | Mitigación |
|---|---|
| Reflex no da un estado nuevo al borrar el token | A5 es la primera tarea de S4; si falla, S4 vuelve al ADR |
| Un manejador nuevo relee el negocio a mitad de camino | A3 y la revisión de §2.4; con §2.2 el daño queda en el estado huérfano |
| m-24852145 construye `tenant_plan_assignments` | Prohibido por F3: se construye con la forma de la suscripción (§2.9.3) y depende de S10 |
| Un error en las funciones del saldo expone datos de otro negocio | Devuelven solo números, el rol no tiene `BYPASSRLS` y solo ve su fila de `tenants`; A22, A23 y `security-review` |
| Un negocio se lleva el saldo común | Tope opcional y aviso por porcentaje (§2.9.2) |
| Una suscripción de muchos negocios de dueños distintos (agencia encubierta) | El tope en el Alta y la confirmación de A19 |

## 6. Qué lo reabriría

- Que A5 falle (Reflex no rota el estado): se rediseña el cambio de negocio.
- Que el fundador pida una vista unificada de varios negocios: vuelve la opción (c), con su ADR.
- Que `security-review` rechace las funciones del saldo sin un arreglo posible: se vuelve a la opción C (cupo repartido por negocio, sin puerta nueva).
- Que la fila del mes de la suscripción se vuelva un cuello de botella (reserva con p95 > 100 ms): se parte el contador por tipo.
- Que `V-TP-7` se resuelva en contra (Meta trata como Tech Provider incluso a negocios propios): cambia el carril de Qualify, no este diseño.

## 7. Decisiones del fundador

Respondidas el 2026-10-25; registro textual en §9.

| # | Pregunta | Recomendación del ADR | Decisión |
|---|---|---|---|
| **F1** | ¿Firmas el diseño de §2.1–§2.7? | Sí | **Firmado tal como se propuso** |
| **F2** | Cupo: A (por negocio), B (saldo común) o C (común en la factura, repartido) | C | **B**, con tope opcional por negocio y aviso por porcentaje (§2.9) |
| **F3** | ¿Diseñar ahora y construir después de 60 días? | Sí | **Construir ya**; sin fase manual |
| **F4** | ¿Cuántos negocios por suscripción? | Parámetro; 2 en Básico | **Básico 2, Plus 3, Pro 5; extras hasta 8**, como parámetro del catálogo, controlado en el Alta |
| **F5** | TTL de la revisión de membresía; correo del login de Bianki y Polette | 60 s; correo neutro | **60 s al cargar páginas, nunca caché antes de publicar o enviar; el correo personal del dueño, sin alias por marca** |

## 8. Fuentes

- Código, verificado el 2026-10-25 en `main` `2f2bb984`: las líneas de §1.2 y §2.7.
- `docs/epica-multi-negocio-una-sesion.md` (diseño base, 2026-10-23).
- `docs/modelo-negocio-operador-multi-emprendimiento.md` §2.1, §3, §4, §6.1.
- `docs/modelo-cobro-generacion.md` §1, §6, D11–D19.
- `docs/precios-planes-qualify.md` (decisión de precios del 2026-10-24).
- `docs/oferta-limites-negocios-por-plan.md` (market-analyst, 2026-10-25).
- `docs/adr-41-cola-generacion-concurrencia.md` (cola, `creative-worker`, correo de la mañana).
- `docs/arquitectura.md` §6: ADR 24, 25, 29, 31, 39, 40.

## 9. Registro de decisiones del fundador (Herwin, 2026-10-25)

Respuestas dadas una por una en la sesión principal y transmitidas por el coordinador:

- **F1 — FIRMADO tal como se propuso:** una fila `users` por (tenant, login); el cambio de negocio descarta la sesión (rota el token y recarga); la generación lleva el negocio sellado y el worker lo vuelve a comprobar; la confirmación de publicar o enviar nombra el negocio y la @cuenta.
- **F2 = B, cupo común entre los negocios de la suscripción.** Reemplaza la recomendación C. Protecciones para que un negocio no agote el saldo: un tope opcional por negocio, fijado en el Alta, y un aviso cuando un negocio pasa el X % del saldo, con X como parámetro. Las dos como parámetros, no en el código. La función de base de datos que hace falta (`SECURITY DEFINER` o equivalente) se diseña dentro de las reglas de RLS y pasa por `security-review`.
- **F3 = construir ya.** S10 (m-24854773) sube a P1 dentro de la épica y se elimina la fase manual de 60 días. Bianki y Polette arrancan directamente en la suscripción compartida con saldo común. Planes y paquetes (m-24852145) usan la forma de la suscripción.
- **F4 = Básico 2, Plus 3, Pro 5 negocios incluidos;** se pueden comprar extras hasta un techo de 8 por suscripción; vive como parámetro del catálogo de planes y se controla en el Alta.
- **F5 = 60 s de caché** para la revisión de membresía al cargar páginas, nunca caché antes de publicar o enviar. El login único de Bianki y Polette usa el **correo personal del dueño**, sin alias por marca.
