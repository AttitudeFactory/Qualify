# Épica — Varios negocios en una sola sesión

**Fecha:** 2026-10-23, revisada 2026-10-25 · **Estado:** `[HISTORIAS · sin implementar · ADR 43 FIRMADO por el fundador 2026-10-25]` · **Meegle:** épica [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186) (mapa de tickets en §4)
**Decisión del fundador (Herwin, 2026-10-23, explícita):** se **revierte** la regla firmada «1 login = 1 tenant = 1 negocio, sin switch» ([`modelo-negocio-operador-multi-emprendimiento.md`](modelo-negocio-operador-multi-emprendimiento.md) §6.1, 2026-08-16). Objetivo nuevo: un dueño maneja varios negocios (tenants separados) desde **una** sesión, con un selector para cambiar. Primer caso real: un mismo dueño con **Bianki** (shawarma y ensaladas) y **Polette** (helados de yogur), que se manejan por separado.
**Producción hoy (chequeo de solo lectura, 2026-10-23):** existen 8 tenants, cada uno con 1 marca y 1 dueño. Bianki no existe; POLETTE es su propio tenant con su login `+polette`. Las únicas 2 conexiones de IG están en tenants distintos. No hay datos que separar: S8 se cerró como «no aplica». **Limpieza decidida y pendiente:** el 2026-10-23 el fundador decidió dejar solo «Zapatería» (IG qualifymkt.co) y «Raul Dev Games» y borrar POLETTE y los 5 «Mi marca» con sus logins de Supabase. Todavía **no se ejecutó**: falta el respaldo y la confirmación del fundador.
**Restricción — única puerta de entrada (fundador, 2026-10-23):** un cliente entra a Qualify **solo** por el ítem «Alta de cliente» de Lark/Meegle (skill `meegle-altas`). Agregar un negocio a un login existente también se dispara solo desde ese ítem (S7). Nunca autoservicio, nunca una invitación desde la app.
**ADR (S0):** [`adr-43-un-login-varios-negocios.md`](adr-43-un-login-varios-negocios.md) `[FIRMADO 2026-10-25]` — el ticket decía «ADR 41», pero el 41 ya es la cola de generación.
**Pedido nuevo del fundador (2026-10-25):** (1) cambiar de negocio es abrir una **instancia limpia**: nunca publicar ni **crear piezas** para el otro negocio; (2) **la suscripción se comparte** entre los negocios del dueño (antes fuera de alcance); (3) el máximo de negocios por suscripción queda abierto, como parámetro. Todo eso entra en ADR 43 y en las historias S9 y S10.
**Revisión técnica:** principal-architect, 2026-10-23; líneas re-verificadas el 2026-10-25 (§1). Las historias de §3 son su corte, revisado contra el código en `main`. Las líneas de código citadas abajo se comprobaron en disco el mismo día.

---

## 0. Resumen en cinco líneas

1. Cada negocio **sigue siendo un tenant** con RLS. Lo que cambia es que un login puede pertenecer a varios.
2. Hoy el 1:1 lo impone el esquema (`UNIQUE(auth_user_id)` global en `users`). Se cambia por `UNIQUE(tenant_id, auth_user_id)`: una fila `users` por negocio y login.
3. Tras el login, si hay más de un negocio, el dueño elige con cuál trabajar. Desde el encabezado puede cambiar sin salir; el cambio destruye el estado de la sesión y recarga la página, igual que el logout.
4. El riesgo número uno es **que se cruce un dato** entre negocios. Por eso hay criterios de aceptación con tests de cobertura y un Playwright con dos tenants en la misma pestaña.
5. Agregar un negocio a un login existente **nunca** es autoservicio ni sale de la app: solo desde un «Alta de cliente» del fundador en Lark, con el campo «Inicio de sesión existente» y la contraseña del dueño (S7).
6. **Cambiar de negocio rota el token de sesión de Reflex:** el estado del negocio anterior queda huérfano y lo que siga corriendo para él termina en su propio negocio (ADR 43 §2.2). Toda generación lleva el negocio sellado y el worker lo vuelve a comprobar (S9).
7. **Una suscripción para varios negocios con un solo saldo de generación** (S10, P1, se construye ya): tope opcional por negocio y aviso por porcentaje; Básico 2, Plus 3 y Pro 5 negocios incluidos, extras hasta 8. Bianki y Polette arrancan directamente en ella.

## 1. Qué existe hoy (medido en el código)

| Pieza | Estado | Dónde |
|---|---|---|
| Un login = un negocio | `users.tenant_id NOT NULL` + `UNIQUE(auth_user_id)` global | `packages/api/src/qualify_api/tenancy/models.py:57-75` |
| Negocio del login en Supabase | Un solo `app_metadata.tenant_id` | `packages/api/src/qualify_api/auth/supabase.py:20,63,150` |
| Mismo email en otro negocio | Se rechaza: «Ese email ya pertenece a otro negocio; usa un alias distinto por negocio.» | `packages/api/src/qualify_api/auth/service.py:359-362` (era `:333-335`) |
| Membresías con rol | `tenant_members` ya existe (owner/admin/agent/viewer) | `packages/api/src/qualify_api/tenancy/models.py:78-97` |
| Destrucción de estado al salir | `logout` limpia el estado Reflex | `Qualify/auth_state.py:852-985` (era `:784-888`) |
| Test de cobertura del logout | Existe; hay que ampliarlo | `Qualify/test_auth_state.py:319` (lista) y `:350` (inverso) |
| Caches de módulo | **Auditados el 2026-10-25: ninguno guarda datos de un negocio con clave sin negocio** (inventario en ADR 43 §2.7). Las líneas citadas antes ya no tienen cache; los actuales son `planner_state.py:150`, `planner_vm.py:520` (husos horarios, estáticos) y `catalog_provider.py:45` (servicio sin estado) | ADR 43 §2.7 |
| Conexiones IG/FB | Únicas **solo por tenant**: `UNIQUE(tenant_id, platform, external_account_id)` | `migrations/postgres/versions/0002_connections.py:143-145` |
| Publicar en la cuenta de otro negocio | Imposible por esquema: FK compuesta `(connection_id, tenant_id)` | `0003_publishing.py:111-115`, `:187-191` |
| Generación | `(tenant_id, draft_id)` y relectura por `tenant_session`; falta el motivo `tenant_mismatch` y el control de claves de R2 en todo el camino (S9) | `creative/dispatch.py:92-138`, `creative/service.py:1617-1647` |
| Plan y cupo | Cupo por `(tenant_id, brand_id)` construido (`0088`); planes por negocio (D15) **diseñados, sin construir** | `0088_creation_charges.py:163-174` |
| WhatsApp | Ya es único globalmente | `migrations/postgres/versions/0057_whatsapp.py:157` |

## 2. Diseño (principal-architect, 2026-10-23)

- **Identidad:** una fila `users` por (tenant, login), con `UNIQUE(tenant_id, auth_user_id)`. `memberships_for(auth_user_id)` en `qualify_api.auth`, vía `admin_session`.
- **Supabase:** `app_metadata.tenant_id` pasa a ser solo el negocio **por defecto**.
- **Selector:** después del login, si hay más de una membresía.
- **Cambio de negocio:** `switch_tenant` validado en el servidor (el `auth_user_id` sale de la sesión, nunca del cliente). **Revisado en ADR 43 §2.2:** no reutiliza el reset del logout sobre el mismo estado; emite un pase de un solo uso, **borra el token de Reflex** y recarga, para que un evento en segundo plano del negocio anterior no escriba en el nuevo.
- **Revisión de membresía:** en `require_login` con caché de 60 s (firmado, F5), y sin caché antes de publicar o enviar.
- **Auditoría:** cada cambio queda registrado en el tenant de destino.
- **Generación sellada (S9):** el `tenant_id` sale de la sesión del servidor al encolar y el worker lo vuelve a comprobar antes de leer y de escribir (ADR 43 §2.4).
- **Suscripción (S10):** `subscriptions` encima de los tenants, aislada por GRANT; un solo saldo de generación para todos sus negocios, leído y movido por funciones `SECURITY DEFINER` que devuelven solo números (ADR 43 §2.8).
- **No cambia:** RLS, workers, webhooks, una sola Postgres (ADR 31), tenant = frontera de aislamiento (ADR 24).
- **Fuera:** el superadmin del equipo (staff) es otra épica.

### Riesgos que se vuelven criterios de aceptación

| Riesgo | Dónde se cubre |
|---|---|
| Al cambiar de negocio queda pintado algo del anterior | S4: test de cobertura ampliado, caches de módulo, Playwright con dos tenants en la misma pestaña |
| Dos pestañas con negocios distintos: publicar en el equivocado | S3: negocio activo siempre visible arriba · S4: la confirmación de publicar/enviar nombra el negocio |
| Quitar a alguien de un negocio no surte efecto con la sesión abierta | S5: revisión con caché de 60 s al cargar y sin caché antes de publicar/enviar |
| La misma cuenta de IG/FB activa en dos tenants: el webhook no sabe a cuál va | S6: chequeo al conectar + índice único global parcial + test de enrutamiento |
| Alguien se agrega por su cuenta a un negocio ajeno | S7: solo desde un «Alta de cliente» del fundador, con contraseña |
| Crear una pieza para el otro negocio (miedo explícito del fundador, 2026-10-25) | S9: negocio sellado al encolar, relectura en el worker, control de claves de R2 |
| Un trabajo de A termina después de cambiar a B y se pinta en B | S4: rotación del token (ADR 43 §2.2) + Playwright · S9: el trabajo termina en A |
| Publicar en la cuenta equivocada | S4: la confirmación nombra el negocio **y** la cuenta de destino, releída al confirmar |
| Un negocio agota el saldo común de los otros de la misma suscripción | S10: tope opcional por negocio (en el Alta) y aviso al pasar un porcentaje del saldo, los dos como parámetros (ADR 43 §2.9.2) |
| Hoy un segundo Alta con un correo ya registrado mete la marca nueva en el negocio anterior (`_resolve_identity_for_signup`, `auth/service.py:96-123`, devuelve el `tenant_id` existente) | S7: con «Inicio de sesión existente» se crea un tenant nuevo; sin él, el Alta falla a la vista |

## 3. Historias

Owner = área que lo construye; Assignee en Meegle: Herwin hasta que se reparta en `/qualify-team-dev`.

| # | Historia | Owner | Depende de | Prioridad · tamaño |
|---|---|---|---|---|
| **S0** | ADR que reabre §6.1, firmado por el fundador | principal-architect | — | P1 · S |
| **S1** | Migración `UNIQUE(tenant_id, auth_user_id)` + `memberships_for` + `resolve_login` devuelve membresías + tests RLS; los usuarios de un solo negocio no notan nada | backend-engineer | S0 | P1 · M |
| **S2** | Dar de alta Polette y Bianki desde Lark («Alta de cliente») con el mismo inicio de sesión: Polette como alta normal, Bianki con «Inicio de sesión existente» | backend-engineer (operación y verificación; el fundador crea los Altas) | S1, S7 | P1 · S |
| **S3** | Pantalla «¿Con qué negocio quieres trabajar?» tras el login + chip con el negocio activo en el encabezado | reflex-ui-engineer | S1 | P1 · M |
| **S4** | Cambiar de negocio desde el encabezado: pase de un solo uso + **rotación del token de Reflex** + recarga; dos pestañas; confirmaciones con negocio y cuenta de destino; test de cobertura por enumeración de estados; Playwright sin fugas (criterios A5–A14 de ADR 43) | reflex-ui-engineer (+ backend; `security-review` del pase) | S3 | P1 · L |
| **S5** | Revisión de membresía al cargar la página y antes de publicar/enviar + auditoría de cada cambio | backend-engineer | S4 | P1 · M |
| **S6** | Una cuenta de IG/FB no puede estar activa en dos negocios + revisión del enrutamiento de webhooks | backend-engineer | — (en paralelo) | P2 · M |
| **S7** | Campo «Inicio de sesión existente» en el «Alta de cliente»: invitación de tipo «agregar negocio» → tenant nuevo con el mismo login como owner; sin el campo y con correo ya registrado, el Alta falla a la vista. Campos «Suscripción» (nueva / la de {correo}), «Tope de este negocio» (opcional) y «Negocio extra comprado»; máximo efectivo con `FOR UPDATE`, nunca más de 8; confirmación de que el negocio es del mismo dueño (A18, A19) | backend + reflex-ui | S1, S10 | P1 · M |
| **S9** | Generación con el negocio sellado: `tenant_id` de la sesión al encolar, relectura por `tenant_session` en el worker, `tenant_mismatch` sin llamar al proveedor, `require_tenant_prefix` en toda clave de R2; trabajos en curso terminan en su negocio (A1–A4) | creative-engineer | — (en paralelo; con la cola de ADR 41 cuando exista) | P1 · M |
| **S10** | Suscripción compartida con saldo común: `subscriptions` + `subscription_plan_assignments` (solo `qualify_admin`), `tenants.subscription_id`, contador del saldo y funciones `SECURITY DEFINER` `pool_reserve` / `pool_release` / `pool_balance` (rol `qualify_pool`, sin `BYPASSRLS`), tope por negocio y aviso por porcentaje como parámetros, negocios incluidos y techo en el catálogo de planes, conciliación diaria (A16, A17, A20–A27). **`security-review` obligatorio** | backend-engineer | S0 | P1 · L |
| ~~**S8**~~ | ~~Separar los datos de Bianki y Polette si hoy comparten tenant~~ — **cerrada, no aplica**: Bianki no existe en producción y POLETTE ya es su propio tenant (chequeo del 2026-10-23) | — | — | — |

S3, S4 y S7 llevan la nota «Sugerencias de UX»: se corre el subagente `ux-designer` sobre el diff antes de abrir el PR (`qualify-pr` paso 5).

### Textos que verá el cliente (exactos, en los criterios de aceptación)

| Dónde | Texto |
|---|---|
| S3 · título del selector | «¿Con qué negocio quieres trabajar?» |
| S3 · ayuda del selector | «Puedes cambiar de negocio cuando quieras desde la parte de arriba.» |
| S3 · chip del encabezado | «Estás en {nombre del negocio}» |
| S4 · menú | «Cambiar de negocio» |
| S4 · mientras cambia | «Abriendo {negocio}…» |
| S3 · título de la pestaña | «{negocio} · Qualify» |
| S4 · confirmar publicación | «Vas a publicar en {negocio}, en Instagram @{usuario}. ¿Seguimos?» (en Facebook: «en la página {nombre}») — cambiado el 2026-10-25 |
| S4 · confirmar respuesta | «Vas a responder como {negocio} (@{usuario}). ¿Seguimos?»; en WhatsApp, «Vas a responder como {negocio} desde el {número}. ¿Seguimos?» — cambiado el 2026-10-25 |
| S5 · acceso retirado | «Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro.» |
| S6 · cuenta ya usada | «Esta cuenta ya está conectada a otro de tus negocios en Qualify. Desconéctala allí primero y vuelve a conectarla aquí.» |
| S7 · asunto del correo | «Agrega otro negocio a tu cuenta» |
| S7 · pantalla | «Te invitaron a manejar {negocio} con tu misma cuenta. Escribe tu contraseña para confirmarlo.» |
| S7 · botón / éxito | «Agregar negocio» / «Listo. Ya puedes elegir {negocio} desde la parte de arriba.» |
| S7 · contraseña incorrecta | «Esa contraseña no coincide. Inténtalo otra vez.» |

## 4. Tickets en Meegle

| # | Ticket |
|---|---|
| Épica | [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186) |
| S0 | [m-24849187](https://project.larksuite.com/5h2wsx/issue/detail/24849187) |
| S1 | [m-24849188](https://project.larksuite.com/5h2wsx/issue/detail/24849188) |
| S2 | [m-24849189](https://project.larksuite.com/5h2wsx/issue/detail/24849189) |
| S3 | [m-24849190](https://project.larksuite.com/5h2wsx/issue/detail/24849190) |
| S4 | [m-24849191](https://project.larksuite.com/5h2wsx/issue/detail/24849191) |
| S5 | [m-24849192](https://project.larksuite.com/5h2wsx/issue/detail/24849192) |
| S6 | [m-24849193](https://project.larksuite.com/5h2wsx/issue/detail/24849193) |
| S7 | [m-24849194](https://project.larksuite.com/5h2wsx/issue/detail/24849194) |
| S9 | [m-24854772](https://project.larksuite.com/5h2wsx/issue/detail/24854772) |
| S10 | [m-24854773](https://project.larksuite.com/5h2wsx/issue/detail/24854773) |
| S8 | [m-24849195](https://project.larksuite.com/5h2wsx/issue/detail/24849195) (cerrada: no aplica) |
| Este doc | [m-24849196](https://project.larksuite.com/5h2wsx/issue/detail/24849196) |

Los enlaces «Bloqueado por» de Meegle siguen la columna «Depende de» de §3.

## 5. Orden de construcción

1. **S0** firmado (ADR 43, 2026-10-25).
2. En paralelo: **S1** (P1), **S10** (P1, con `security-review`), **S9** (P1) y **S6** (P2). Planes y paquetes (m-24852145) se construyen sobre S10, con la forma de la suscripción.
3. **S7** (necesita S1 y S10) y **S3** (necesita S1), en paralelo.
4. **S2**: Altas de Polette y Bianki en Lark con el mismo inicio de sesión y la misma suscripción, saldo común desde el primer día (necesita S1, S7 y S10).
5. **S4** → **S5**. Con S5 cerrado, el cambio de negocio sin salir es seguro para clientes. Hasta S4, el dueño cambia de negocio con el selector de S3 al entrar.

Sin fase manual de 60 días (F3).

## 6. Preguntas abiertas para el fundador

1. ~~TTL de la revisión de membresía (S5)~~ **Respondida (2026-10-25, F5):** 60 s al cargar páginas; nunca caché antes de publicar o enviar.
2. ~~¿Qué inicio de sesión usa el dueño de Polette y Bianki? (S2)~~ **Respondida (2026-10-25, F5):** el correo personal del dueño, sin alias por marca. Se crea en el primer Alta y el segundo se le vincula.
3. ~~¿Aparcar S7?~~ **Respondida (2026-10-23):** no. El Alta es la única puerta de entrada, así que S7 es el mecanismo del primer caso (S2) y sube a P1.
4. ~~Cuenta de IG/FB ya activa en dos negocios: ¿cuál se la queda?~~ **Respondida por producción (2026-10-23):** ninguna cuenta está en dos tenants hoy (las 2 conexiones de IG están en tenants distintos), así que el índice único global de S6 se puede crear sin limpiar datos.

5. ~~Cupo, momento de construir la suscripción y máximo de negocios~~ **Respondidas (2026-10-25, ADR 43 §9):** saldo común con tope opcional por negocio y aviso por porcentaje (F2 = B); construir ya (F3); Básico 2, Plus 3, Pro 5, extras hasta 8 (F4).

## 7. Fuera de alcance

- Vista unificada de varios negocios (cartera). **La facturación compartida entró al alcance el 2026-10-25** (S10, ADR 43 §2.8); sigue fuera el cobro automático con un proveedor de pago (D19).
- Superadmin del equipo (staff): épica aparte.
- Que el dueño invite a otras personas a su negocio.

## 8. Contrato del backend para la UI (S1, m-24849188 · 2026-11-02)

Lo que la pantalla «¿Con qué negocio quieres trabajar?» (S3) y el cambio de negocio (S4) llaman. Todo se importa de `qualify_api.auth`; todas son funciones bloqueantes (la UI las llama con `asyncio.to_thread`, como el resto de `AuthState`).

| Función / tipo | Firma | Qué hace |
|---|---|---|
| `resolve_login` | `(provider, email, password) -> LoginResult` | Igual que antes; ahora `LoginResult.memberships: tuple[UserMembership, ...]` trae **todos** los negocios del login, ordenados por nombre, y `LoginResult.needs_business_choice: bool` es `True` con 2 o más. `tenant_id` es el negocio por defecto (`app_metadata.tenant_id` de Supabase, el del primer Alta, mientras siga siendo una membresía; si no, la primera) y solo sirve para ordenar o marcar. Sin ninguna membresía lanza `NoBusinessAccess` |
| `UserMembership` | `tenant_id, tenant_name, name, role, user_id, email, display_name` | Una fila por negocio; `name` = `tenant_name` |
| `memberships_for` | `(auth_user_id: UUID) -> list[UserMembership]` | Lo mismo que `memberships`, para releer la lista (por ejemplo, el menú «Cambiar de negocio» de S4). Única lectura cruzada, por `admin_session` |
| `open_business` | `(auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness` | Comprueba **sin caché**, por `tenant_session(tenant_id)`, que el login es miembro (`users` + `tenant_members`) y devuelve `ActiveBusiness(tenant_id, business_name, user_id, email, display_name, role)`. Si no lo es: `NotAMember` |
| `NotAMember` / `NoBusinessAccess` | `.message == NOT_A_MEMBER_MESSAGE` | «Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro.» Es el mismo texto de «S5 · acceso retirado» de la tabla de textos: no se escribe una segunda versión. La UI lo muestra y manda a `/login` |

**Dónde vive el negocio activo.** En el servidor, en `AuthState.session_tenant_id` (estado de Reflex de esa pestaña), como hoy. No hay cookie, `localStorage` ni columna de «negocio activo» en la base (ADR 43 §3). Cada página llega a `tenant_session(UUID(session_tenant_id))` exactamente como ahora; nada cambia en los módulos.

**Cómo lo usa la UI (S3):**

1. Al entrar, `resolve_login` como siempre. Guardar `result.auth_user_id` en una variable **solo del servidor** (`_auth_user_id`, con guion bajo, como `_access_token`): hoy `AuthState` guarda `_session_user_id` (el `users.id` local, que cambia por negocio) pero no el `auth_user_id`, y S3/S4/S5 lo necesitan.
2. Si `needs_business_choice` es `False`: abrir la sesión como hoy (`_open_session`).
3. Si es `True`: mostrar el selector con `memberships` (**solo el nombre del negocio**; `role` viene en inglés, `owner`/`admin`/`agent`/`viewer`, y no se muestra tal cual), **sin escribir `session_tenant_id` todavía**. Al elegir, `open_business(self._auth_user_id, UUID(elegido))` y escribir en `session_tenant_id`, `_session_user_id`, `business_name` y `user_email` lo que devuelve `ActiveBusiness`. El `tenant_id` del clic es justo lo que se verifica; el `auth_user_id` nunca sale del navegador.
4. S4 (cambiar sin salir) usa la misma `open_business` al canjear el pase en `/cambiar`, en el estado nuevo (ADR 43 §2.2). El pase de un solo uso y su revisión de seguridad son de S4.

Las revisiones de S5 (al cargar con 60 s de caché y fresca antes de publicar o enviar) y la auditoría de cada cambio se agregan en m-24849192 sobre estas mismas funciones.

**Casos que S3 tiene que cubrir** (revisión de UX del 2026-11-02, sugerencias, no bloquean):

- Elegir es **un toque**: cada negocio es un botón de ancho completo (al menos 44 px) que abre ese negocio; sin lista de opciones más «Continuar». Mientras corre `open_business`, «Abriendo {negocio}…».
- Con un toque por fila no hay nada que preseleccionar: el negocio por defecto, si se usa, solo ordena la lista o se marca con texto, nunca solo con color. Recordar el último negocio usado no existe hoy (ADR 43 §3): pregunta abierta para el fundador.
- La pantalla del selector todavía no tiene negocio: título de la pestaña «Elige tu negocio · Qualify», el título del selector como `h1`, un enlace «Salir» a `/login`, y el botón atrás del teléfono vuelve a `/login`.
- `app_metadata.tenant_id` vale solo mientras sea una de las membresías: si se quitó el asiento en ese negocio, `resolve_login` toma como defecto la primera membresía que queda. Sin ningún asiento, `resolve_login` lanza `NoBusinessAccess` (subclase de `IncompleteRegistration`, así la pantalla de entrada de hoy ya la rechaza; S3 la atrapa antes y muestra su `message`, el mismo texto de «S5 · acceso retirado»). La UI nunca muestra un selector vacío.

## 9. Contrato del backend para la UI (S5, m-24849192 · 2026-11-02)

Revisión de membresía y auditoría de cada apertura de negocio. Todo se importa de `qualify_api.auth` (o `qualify_api.tenancy.acting` para el contexto); funciones bloqueantes, que la UI llama con `asyncio.to_thread`. TTL: **60 s** (ADR 43 F5, firmado el 2026-10-25; el ticket decía 5 minutos, del 2026-10-24, y lo reemplaza la decisión posterior).

| Función | Firma | Cuándo la llama la UI |
|---|---|---|
| `check_membership` | `(auth_user_id, tenant_id) -> ActiveBusiness` | **Al cargar cada página protegida**: en `AuthState.require_login`, después de comprobar `session_tenant_id`. Caché de 60 s por proceso y por (login, negocio). Si quitan el asiento, la página puede seguir cargando hasta 60 s; la siguiente carga lanza `NotAMember`. Una negativa nunca se guarda como acceso |
| `acting_login` | `with acting_login(auth_user_id): ...` | **Alrededor de cada llamada que publica o envía** (incluida la llamada a `asyncio.to_thread`, que copia el contexto). Marca quién actúa; los servicios revisan solos |
| `require_acting_member` | `(tenant_id) -> None` | No la llama la UI: la llaman los servicios. Revisión **sin caché** del login marcado; sin login marcado (workers, webhooks, CLI) no hace nada |
| `require_membership_now` | `(auth_user_id, tenant_id) -> ActiveBusiness` | Revisión sin caché directa, para casos fuera de los servicios (por ejemplo, llamadas a Graph que hoy viven en proveedores de Reflex, ver abajo) |
| `open_business_audited` | `(auth_user_id, tenant_id, *, via: "login" \| "switch", from_tenant_id=None) -> ActiveBusiness` | **En lugar de `open_business`** en el selector (S3, `via="login"`) y al canjear el pase del cambio (S4, `via="switch"`, `from_tenant_id` = negocio anterior). Misma revisión, más una fila en `business_open_audit` del negocio destino, en la misma transacción |

Con `NotAMember` (cualquiera de las anteriores) la UI muestra `exc.message` («Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro.»), limpia la sesión y manda a `/login`, como en §8.

**Puertas que revisan solas** cuando hay un login marcado (test estático `test_every_publish_or_send_door_calls_the_gate`): `publishing.composition.stage_and_start_publish` y `stage_and_start_many_publish`; `PlannerService._plan` (programar una, varias o semanal) y `reschedule`; `ReplyService.send` (respuesta pública); `PostgresConversationOutboxRepository.enqueue` (Direct, respuesta privada, seguimientos); `PostgresOutboxRepository.enqueue` de WhatsApp; `ChatService.send` y `TemplateReplyService.send` (antes de pausar la automatización); `CampaignService.launch`; `TemplateService.create` / `delete`; `PostgresMenuRepository.publish_version`; `IceBreakerService.publish` / `remove`.

**Lo que no cubre este backend y queda para quien lo tiene** (los lugares publican o envían sin pasar por una puerta del backend):

- Llamadas a Graph que viven en proveedores de Reflex: perfil, foto y QR de WhatsApp (`Qualify/whatsapp_provider.py`) y el `set_conversational_automation` del menú (`Qualify/whatsapp_menu_provider.py`). reflex-ui-engineer: llamar `require_membership_now` antes, o mover la llamada a un servicio.
- Aprobaciones del generador (`creative`: `ContentService.approve`, `approve_version`, `AngleSetService.approve_angle`, `confirm_final`) y el envío a Canva (`canva`): son de creative-engineer. Programar en el planificador ya revisa, así que una pieza aprobada por alguien sin acceso no se publica sin otra acción de un miembro.
- Hoy la UI no guarda `auth_user_id` ni marca `acting_login`: hasta que S3/S4 lo hagan, la revisión no se dispara (las puertas no rompen nada mientras tanto).

**Auditoría.** Tabla `business_open_audit` (migración `0114`): `tenant_id` (destino), `auth_user_id`, `user_id` local, `from_tenant_id` (sin FK; `NULL` al entrar), `via`, `opened_at`. RLS como todas; el rol de la app solo `SELECT` e `INSERT`. No hay pantalla para verla (fuera de alcance).
