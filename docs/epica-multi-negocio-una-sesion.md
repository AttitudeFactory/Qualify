# Épica — Varios negocios en una sola sesión

**Fecha:** 2026-10-23 · **Estado:** `[HISTORIAS · sin implementar · pendiente del ADR de S0]` · **Meegle:** épica [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186) (mapa de tickets en §4)
**Decisión del fundador (Herwin, 2026-10-23, explícita):** se **revierte** la regla firmada «1 login = 1 tenant = 1 negocio, sin switch» ([`modelo-negocio-operador-multi-emprendimiento.md`](modelo-negocio-operador-multi-emprendimiento.md) §6.1, 2026-08-16). Objetivo nuevo: un dueño maneja varios negocios (tenants separados) desde **una** sesión, con un selector para cambiar. Primer caso real: un mismo dueño con **Bianki** (shawarma y ensaladas) y **Polette** (helados de yogur), que se manejan por separado.
**Producción hoy (chequeo de solo lectura, 2026-10-23):** **Bianki no existe como tenant.** Polette es su propio tenant («POLETTE», 1 marca, 1 login dueño, 0 conexiones de Meta/IG/WhatsApp). Los 8 tenants de producción tienen exactamente 1 marca y 1 dueño. Las únicas 2 conexiones de IG están en tenants distintos. No hay datos que separar: S8 se cerró como «no aplica».
**Revisión técnica:** principal-architect, 2026-10-23. Las historias de §3 son su corte, revisado contra el código en `main`. Las líneas de código citadas abajo se comprobaron en disco el mismo día.

---

## 0. Resumen en cinco líneas

1. Cada negocio **sigue siendo un tenant** con RLS. Lo que cambia es que un login puede pertenecer a varios.
2. Hoy el 1:1 lo impone el esquema (`UNIQUE(auth_user_id)` global en `users`). Se cambia por `UNIQUE(tenant_id, auth_user_id)`: una fila `users` por negocio y login.
3. Tras el login, si hay más de un negocio, el dueño elige con cuál trabajar. Desde el encabezado puede cambiar sin salir; el cambio destruye el estado de la sesión y recarga la página, igual que el logout.
4. El riesgo número uno es **que se cruce un dato** entre negocios. Por eso hay criterios de aceptación con tests de cobertura y un Playwright con dos tenants en la misma pestaña.
5. Agregar un negocio a un login existente **nunca** es autoservicio: solo con invitación del fundador más la contraseña.

## 1. Qué existe hoy (medido en el código)

| Pieza | Estado | Dónde |
|---|---|---|
| Un login = un negocio | `users.tenant_id NOT NULL` + `UNIQUE(auth_user_id)` global | `packages/api/src/qualify_api/tenancy/models.py:57-75` |
| Negocio del login en Supabase | Un solo `app_metadata.tenant_id` | `packages/api/src/qualify_api/auth/supabase.py:20,63,150` |
| Mismo email en otro negocio | Se rechaza: «Ese email ya pertenece a otro negocio; usa un alias distinto por negocio.» | `packages/api/src/qualify_api/auth/service.py:333-335` |
| Membresías con rol | `tenant_members` ya existe (owner/admin/agent/viewer) | `packages/api/src/qualify_api/tenancy/models.py:78-97` |
| Destrucción de estado al salir | `logout` limpia el estado Reflex | `Qualify/auth_state.py:784-888` |
| Test de cobertura del logout | Existe; hay que ampliarlo | `Qualify/test_auth_state.py:318-325` |
| Caches de módulo | Por revisar en el cambio de negocio | `planner_state.py:125`, `planner_vm.py:414`, `catalog_provider.py:41` |
| Conexiones IG/FB | Únicas **solo por tenant**: `UNIQUE(tenant_id, platform, external_account_id)` | `migrations/postgres/versions/0002_connections.py:143` |
| WhatsApp | Ya es único globalmente | `migrations/postgres/versions/0057_whatsapp.py:157` |

## 2. Diseño (principal-architect, 2026-10-23)

- **Identidad:** una fila `users` por (tenant, login), con `UNIQUE(tenant_id, auth_user_id)`. `memberships_for(auth_user_id)` en `qualify_api.auth`, vía `admin_session`.
- **Supabase:** `app_metadata.tenant_id` pasa a ser solo el negocio **por defecto**.
- **Selector:** después del login, si hay más de una membresía.
- **Cambio de negocio:** `switch_tenant` validado en el servidor (el `auth_user_id` sale de la sesión, nunca del cliente). Reutiliza la destrucción de estado del logout (se extrae un helper de `auth_state.py:784-888`) y hace recarga completa.
- **Revisión de membresía:** en `require_login` con TTL corto, y sin caché antes de publicar o enviar.
- **Auditoría:** cada cambio queda registrado en el tenant de destino.
- **No cambia:** RLS, workers, webhooks, una sola Postgres (ADR 31), tenant = frontera de aislamiento (ADR 24).
- **Fuera:** el superadmin del equipo (staff) es otra épica.

### Riesgos que se vuelven criterios de aceptación

| Riesgo | Dónde se cubre |
|---|---|
| Al cambiar de negocio queda pintado algo del anterior | S4: test de cobertura ampliado, caches de módulo, Playwright con dos tenants en la misma pestaña |
| Dos pestañas con negocios distintos: publicar en el equivocado | S3: negocio activo siempre visible arriba · S4: la confirmación de publicar/enviar nombra el negocio |
| Quitar a alguien de un negocio no surte efecto con la sesión abierta | S5: revisión con TTL corto y antes de publicar/enviar |
| La misma cuenta de IG/FB activa en dos tenants: el webhook no sabe a cuál va | S6: chequeo al conectar + índice único global parcial + test de enrutamiento |
| Alguien se agrega por su cuenta a un negocio ajeno | S2/S7: solo enlace o invitación del fundador, con contraseña |

## 3. Historias

Owner = área que lo construye; Assignee en Meegle: Herwin hasta que se reparta en `/qualify-team-dev`.

| # | Historia | Owner | Depende de | Prioridad · tamaño |
|---|---|---|---|---|
| **S0** | ADR que reabre §6.1, firmado por el fundador | principal-architect | — | P1 · S |
| **S1** | Migración `UNIQUE(tenant_id, auth_user_id)` + `memberships_for` + `resolve_login` devuelve membresías + tests RLS; los usuarios de un solo negocio no notan nada | backend-engineer | S0 | P1 · M |
| **S2** | Dar de alta Bianki como tenant nuevo (flujo «Alta de cliente», skill `meegle-altas`) y vincularle como owner el login que ya es dueño de Polette; el enlace de alta acepta un login existente | backend-engineer | S1 | P1 · S |
| **S3** | Pantalla «¿Con qué negocio quieres trabajar?» tras el login + chip con el negocio activo en el encabezado | reflex-ui-engineer | S1 | P1 · M |
| **S4** | Cambiar de negocio desde el encabezado: destrucción de estado compartida + recarga + test de cobertura + Playwright sin fugas | reflex-ui-engineer (+ backend) | S3 | P1 · L |
| **S5** | Revisión de membresía al cargar la página y antes de publicar/enviar + auditoría de cada cambio | backend-engineer | S4 | P1 · M |
| **S6** | Una cuenta de IG/FB no puede estar activa en dos negocios + revisión del enrutamiento de webhooks | backend-engineer | — (en paralelo) | P2 · M |
| **S7** | Invitación «Agrega otro negocio a tu cuenta» para un login existente | backend + reflex-ui | S2 | P2 · M |
| ~~**S8**~~ | ~~Separar los datos de Bianki y Polette si hoy comparten tenant~~ — **cerrada, no aplica**: en producción Bianki no existe y Polette es su propio tenant (2026-10-23) | — | — | — |

S3, S4 y S7 llevan la nota «Sugerencias de UX»: se corre el subagente `ux-designer` sobre el diff antes de abrir el PR (`qualify-pr` paso 5).

### Textos que verá el cliente (exactos, en los criterios de aceptación)

| Dónde | Texto |
|---|---|
| S3 · título del selector | «¿Con qué negocio quieres trabajar?» |
| S3 · ayuda del selector | «Puedes cambiar de negocio cuando quieras desde la parte de arriba.» |
| S3 · chip del encabezado | «Estás en {nombre del negocio}» |
| S4 · menú | «Cambiar de negocio» |
| S4 · mientras cambia | «Abriendo {negocio}…» |
| S4 · confirmar publicación | «Vas a publicar en {negocio}. ¿Seguimos?» |
| S4 · confirmar respuesta | «Vas a responder como {negocio}. ¿Seguimos?» |
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
| S8 | [m-24849195](https://project.larksuite.com/5h2wsx/issue/detail/24849195) (cerrada: no aplica) |
| Este doc | [m-24849196](https://project.larksuite.com/5h2wsx/issue/detail/24849196) |

Los enlaces «Bloqueado por» de Meegle siguen la columna «Depende de» de §3.

## 5. Orden de construcción

1. **S0** (firma) y, en paralelo, **S6** y el alta de Bianki como cliente nuevo (`meegle-altas`; no necesita código).
2. **S1** → **S2** (el login de Polette pasa a ser también dueño de Bianki) y **S3**.
3. **S4** → **S5**. Con S5 cerrado, el cambio de negocio es seguro para clientes.
4. **S7** cuando haya un segundo cliente con varios negocios.

## 6. Preguntas abiertas para el fundador

1. **TTL de la revisión de membresía (S5):** propuesta 60 s al cargar páginas; publicar y enviar siempre se revisan sin caché. ¿Te sirve?
2. ~~Alias por negocio: ¿fusionar alias?~~ **Respondida por producción (2026-10-23):** no hay otros alias que fusionar. Bianki no existe; se da de alta y se le vincula como owner el login que ya es dueño de Polette (S2).
3. **Quién más puede tener varios negocios:** ¿solo tú por ahora, o S7 entra ya para algún cliente concreto? Si no hay cliente, S7 se puede aparcar.
4. ~~Cuenta de IG/FB ya activa en dos negocios: ¿cuál se la queda?~~ **Respondida por producción (2026-10-23):** ninguna cuenta está en dos tenants hoy (las 2 conexiones de IG están en tenants distintos), así que el índice único global de S6 se puede crear sin limpiar datos.

## 7. Fuera de alcance

- Vista unificada de varios negocios (cartera) y facturación por operador (`modelo-negocio-operador-multi-emprendimiento.md` §4 sigue en hipótesis).
- Superadmin del equipo (staff): épica aparte.
- Que el dueño invite a otras personas a su negocio.
