# Plan — Superadmin de Qualify: alta de clientes de punta a punta

**Fecha:** 2026-10-07 · **Estado:** `[PLAN — pendiente de las decisiones del fundador (§9)]`
**Origen:** pedido del fundador (2026-10-07): *«desde mi superadmin que administra los tenants puedo disparar nuevos tenants y adelantar configuración y scraping para que su Brand Kit sea más eficiente, ya precargado con su nicho de mercado (mientras hablo)»*, y *«invitar con plantilla de correo a clientes específicos; ahí no se precisa tanta seguridad porque en el boca a boca yo me aseguro de que son los dueños del emprendimiento»*.
**Construye sobre:** el login endurecido + código compartido + invitaciones por correo de la rama `claude/login-auth-improvements-6658d6` (migración `0050_signup_invites`, `qualify_api.auth.invites`, `qualify_api.mail` sobre Resend), el Brand Kit antes del login (migración `0037`, `qualify_api.auth.drafts`) y el worker embebido del Planificador (QUA-111).

---

## 1. La idea en una frase

> **Mientras hablas con un cliente, escribes su negocio, su correo, su @ y su rubro en tu panel; Qualify prepara su Brand Kit en segundo plano y, cuando le mandas la invitación, entra a una cuenta que ya lo conoce.**

Hoy un cliente nuevo llega a `/brand/start` en frío: escribe su correo, su @, espera la lectura del perfil, elige rubro, espera los hashtags, espera a los referentes. Todo eso cuesta tiempo frente a la pantalla, y es justo el momento en que más se pierde gente. El panel mueve ese trabajo **antes** de que el cliente llegue, a la conversación de venta.

## 2. Qué es y qué no es

| Es | No es |
|---|---|
| El panel de **operación de la plataforma**: el equipo de Qualify ve y administra todos los negocios | La «vista de cartera» de un cliente que maneja varios negocios. Esa la descartaste el 2026-08-16 (§6.1 de [modelo de negocio](modelo-negocio-operador-multi-emprendimiento.md): *1 login = 1 negocio, sin switch*) y sigue descartada |
| Una identidad aparte (`superadmin`) que **no es** un negocio | Un switch para entrar a los negocios de los clientes |
| Lecturas entre negocios **auditadas**, por una sola puerta de código | Acceso libre a `admin_session` desde la UI |

**Fuera de la v1, a propósito:** «entrar como» un negocio (suplantar la sesión de un cliente para darle soporte) y borrar negocios. Son las dos acciones más peligrosas del panel; se evalúan con un ADR propio cuando haya una necesidad real (§8, Fase A4).

**Corrección de lectura del plan de Supabase.** [`plan-integracion-supabase-auth-tenant.md`](plan-integracion-supabase-auth-tenant.md) §fuera de alcance dice que una «vista de operador global» contradiría el ruling firmado. Eso se refería a un **cliente** viendo varios negocios. Este panel es del **personal de la plataforma** y no cambia nada de lo que ve un cliente.

---

## 3. El recorrido de punta a punta

```
 Llamada de venta                Panel (tú)                         Segundo plano                     Cliente
 ───────────────                 ──────────                         ─────────────                     ───────
 «¿cuál es tu @?»   ──►  Nueva alta: negocio, correo,
                         @IG/@TikTok, rubro, ciudad      ──►  crea el negocio en espera (0037)
                         [Preparar]                           lee el perfil (ScrapeCreators)
                                                              colores del logo, rubro, hashtags
                         Ficha del alta: progreso en vivo ◄── guarda el Brand Kit precargado
                         vista previa del Brand Kit           (referentes: según presupuesto §6.3)
                         nota personal  [Enviar invitación] ──────────────────────────────►  correo «Crear mi cuenta»
                                                                                              /signup?invite=…
                         estado: aceptada ◄───────────────────────────────────────────────── se registra → adopta
                                                                                              el negocio preparado
                                                                                              → /brand/kit listo
```

### 3.1 Estados de un alta

```
 borrador ──► preparando ──► lista ──► invitada ──► aceptada ──► activa
                  │            │          │
                  ▼            │          ├──► vencida  (la invitación expiró sin usarse)
               con_fallas      │          └──► anulada  (la anulaste tú)
              (reintentable)   └──────────────► anulada
```

- **borrador**: se guardó el formulario, no se lanzó nada.
- **preparando**: hay tareas en cola o corriendo (§6).
- **con_fallas**: alguna tarea agotó sus reintentos. La ficha dice cuál y por qué, con un botón para reintentar. No bloquea invitar: el cliente completará en el asistente lo que falte.
- **lista**: las tareas obligatorias terminaron.
- **invitada / vencida / anulada**: el estado de la invitación ligada.
- **aceptada**: el cliente se registró y adoptó el negocio.
- **activa**: terminó o confirmó su Brand Kit (`tenant_kit_status().completed`). Es la métrica que importa.

Las transiciones viven en una función pura con tabla de transiciones, el mismo patrón que la FSM de conexiones (`qualify_api.connections.fsm`). Ningún `UPDATE` de estado sale de otro lado.

---

## 4. Arquitectura

### 4.1 Identidad y acceso

**Una identidad de plataforma, separada de los negocios.** Tu cuenta de superadmin (por ejemplo `herwin_rey@attitudefactory.co`) es un usuario de Supabase **sin** `tenant_id`, con `app_metadata.platform_role = "superadmin"`.

- **Quién marca el rol:** solo un comando del servidor con la llave secreta (`just grant-superadmin <email>`), igual que hoy se marca `app_metadata.tenant_id`. GoTrue no deja que un usuario escriba su propio `app_metadata`, así que nadie puede dárselo a sí mismo. Es la misma propiedad de seguridad en la que ya descansa el login.
- **Login:** el mismo `/login`. `resolve_login` hoy rechaza una identidad sin `tenant_id` (`IncompleteRegistration`). Con el cambio, una identidad sin tenant **y** con `platform_role` abre una **sesión de plataforma**: `AuthState.platform_role = "superadmin"`, `session_tenant_id` vacío, y aterriza en `/admin`.
- **Por qué separada y no «tu negocio + un permiso extra»:** una sesión de plataforma nunca tiene un tenant activo, así que ningún estado de negocio (bandeja, Brand Kit, planificador) puede cargar datos en ella por accidente. Y tus negocios propios (Bianki, Polette) siguen entrando con sus alias, como siempre.
- **Verificación en cada evento, no solo al cargar la página.** Todo handler del panel empieza con `require_platform_admin()`, que vuelve a leer el rol del estado del servidor. Un `on_load` solo es UX: los eventos de Reflex viajan por el websocket y se pueden disparar sin pasar por la página.
- **Segundo factor obligatorio (TOTP)** antes de usar el panel en producción con datos de clientes. Supabase lo trae gratis: inscribir un factor, desafío y verificación sobre la API REST de GoTrue (`/factors`). La sesión de plataforma exige nivel `aal2`. Ver la decisión D3.

### 4.2 Una sola puerta para leer entre negocios

Nuevo módulo **`qualify_api.platform`**: el único código de la UI que usa `admin_session` para el panel. Expone funciones con nombre de negocio (`list_tenants`, `tenant_detail`, `create_onboarding`, `onboarding_detail`…) y **cada acción que modifica algo escribe una fila de auditoría en la misma transacción**.

Se protege con un test estático, igual que `test_auth_sanctity.py`: ningún módulo `Qualify/admin_*` importa `admin_session` ni `tenant_session` directamente; todo pasa por `qualify_api.platform`.

### 4.3 Modelo de datos (migraciones nuevas)

Todas son **globales** (sin `tenant_id` propio, como `platform_apps` y `signup_invites`), solo con `GRANT` a `qualify_admin`; `qualify_app` no las ve.

| Tabla | Para qué | Columnas clave |
|---|---|---|
| `platform_audit_log` | Quién hizo qué en el panel | `actor_auth_user_id`, `action`, `target_tenant_id` (nullable), `target_ref`, `payload` JSONB (sin secretos), `created_at` |
| `tenant_onboardings` | Un alta | `tenant_id` (el negocio en espera, FK), `owner_email`, `business_name`, `network` + `handle`, `rubro_text`, `sector`, `country_code`, `city`, `status`, `revision`, `credit_budget`, `credits_spent`, `cost_usd`, `note`, `created_by`, timestamps |
| `onboarding_tasks` | Las tareas de preparación | `onboarding_id`, `kind`, `status` (`queued/running/done/failed/skipped`), `revision`, `attempts`, `next_attempt_at`, `last_error`, `input_hash`, `credits`, `cost_usd`, `started_at`, `finished_at`; `UNIQUE(onboarding_id, kind, input_hash)` |
| `signup_invites` (cambia) | Ligarla al alta | + `onboarding_id` (nullable), `business_name`, `note`, `revoked_at`, `sent_count`, `last_sent_at` |

`input_hash` hace las tareas idempotentes: relanzar «Preparar» con los mismos datos no repite trabajo ni gasta créditos; cambiar el @ sí genera tareas nuevas.

### 4.4 El negocio en espera

Se reutiliza el mecanismo del Brand Kit antes del login (`0037`): `start_brand_kit_draft(email)` ya crea, en una sola transacción, el tenant, el dueño sin login, su asiento, la marca y la fila de `brand_kit_drafts`, y `register_business` **ya adopta** ese negocio cuando alguien se registra con ese correo. El alta agrega solo:

- el nombre real del negocio desde el principio (hoy el borrador nace como «Mi marca»);
- la ligadura alta → invitación → borrador, para que el registro por invitación adopte **ese** negocio y no otro;
- un rechazo claro si el correo ya tiene cuenta: no se prepara un negocio sobre un cliente existente.

### 4.5 La preparación en segundo plano

**Refactor previo (obligatorio): sacar la orquestación del asistente a un servicio.** Hoy la lectura del perfil y el guardado del kit están encadenados dentro de `BrandConnectState.analyze` (`Qualify/creative_wizard_pages.py:5120`) y de `snapshot_states`, que dependen del estado de Reflex. Las piezas de abajo sí son funciones normales:

| Paso | Función existente | Vendor / modelo |
|---|---|---|
| Reservar la cuenta | `account_claims_provider.claim` → `qualify_api.creative.account_claims.claim` | — |
| Leer el perfil | `creator_cache_provider.cached_snapshot` → `scrapecreators_client.fetch_profile_and_posts` | ScrapeCreators |
| Registrar lectura y semilla | `growth_provider.record_profile_read`, `creator_discovery.seed_from_profile` | — |
| Colores del logo | `avatar_proxy.resolve_avatar`, `logo_palette.extract_palette` / `merge_into_palette` | local, $0 |
| Rubro sugerido | `qualify_api.hashtags.from_profile.generate` | Claude Sonnet 5 (esfuerzo bajo) |
| Hashtags | `hashtag_catalog.ensure_seeded` + `suggest_hashtags` | Claude Sonnet 5 |
| Referentes | `referentes_provider.run_phases` + `save_phase` | ScrapeCreators + revisor Claude |
| Guardar el kit | `brand_finish.persist_brand_kit` | — |

El servicio nuevo, **`qualify_api.creative.brand_prefill`**, compone esas funciones con entradas explícitas (tenant, marca, red, @, rubro, ciudad) y construye él mismo los documentos `connect`/`profile` que hoy arma `snapshot_states`. **El asistente pasa a llamarlo también**, así no hay dos copias de la lógica que se desincronicen. Es el trabajo más delicado del plan y va con tests de equivalencia: el kit que guarda el servicio para un perfil de fixture es igual al que guarda el asistente.

**Cómo queda el kit precargado.** Se guarda con `progress = {"flow": "connect", "completed": false, "step": <paso de revisión>}`. Así `tenant_kit_status` manda al cliente a **revisar y confirmar** dentro del asistente, en vez de darle por terminado algo que él no vio (§4 de `brand_finish`). Decisión D6.

**El worker: embebido, sin servicio nuevo.** Igual que el Planificador (QUA-111): un hilo con su propio loop que arranca en el `lifespan` del backend de Reflex (`Qualify/Qualify.py`). Toma tareas con el mismo patrón ya probado:

- reclamo con un `UPDATE … WHERE status='queued' AND revision=:esperada AND next_attempt_at <= now() RETURNING`;
- candado `pg_try_advisory_xact_lock` por alta (`qualify_api.planner.locks`);
- reintentos con espera exponencial, máximo 3, y luego `failed` visible en la ficha.

Varias réplicas del backend, o el backend más un CLI, conviven sin pisarse. No se agrega Celery ni otro contenedor (Parte 3 sigue siendo otra discusión).

### 4.6 Progreso en vivo

La ficha del alta corre una tarea de fondo de Reflex que lee el estado de las tareas cada 2 s mientras la ficha está abierta, y se detiene al salir. Nada se empuja desde el worker al navegador. Es simple y aguanta reinicios.

---

## 5. Pantallas

Todas bajo `/admin`, construidas con el sistema de diseño (`app_shell(page_header(...), page_body(...))`, estados por **tono**). El formulario de alta tiene que **funcionar bien en el celular**: es la pantalla que vas a usar con el cliente al teléfono.

| Ruta | Pantalla | Qué tiene |
|---|---|---|
| `/admin` | Inicio | Embudo de altas (preparando → invitadas → aceptadas → activas), altas con fallas, gasto del mes en créditos y en dólares |
| `/admin/tenants` | Negocios | Tabla paginada: nombre, correo dueño, fecha de alta, estado del Brand Kit, cuentas conectadas, origen (registro propio / invitación / alta). Búsqueda por nombre o correo |
| `/admin/tenants/<id>` | Ficha de negocio | Datos, marcas, estado del Brand Kit, conexiones, invitaciones, historial de auditoría de ese negocio. **Solo lectura** en la v1 |
| `/admin/onboardings/new` | Nueva alta | Negocio, correo, red + @, rubro (con la sugerencia de `from_profile` apenas hay @), ciudad, país/zona/moneda con valores por defecto. Botones *Guardar* y *Preparar* |
| `/admin/onboardings/<id>` | Ficha del alta | Progreso por tarea (con costo), vista previa del Brand Kit (logo, colores, hashtags, referentes), nota personal, *Enviar invitación* / *Reenviar* / *Anular*, *Reintentar* por tarea |
| `/admin/invites` | Invitaciones | Todas las invitaciones (con o sin alta): estado, enviada, reenvíos, vencimiento. *Invitar a un correo* sin preparar nada, y *Pegar una lista* para invitar a varios |
| `/admin/audit` | Auditoría | Registro filtrable por actor, acción y negocio |

El estado de Reflex del panel (`AdminState` y sus subestados) se **resetea en el logout**, como exige la higiene de §6.1; `test_every_tenant_reading_state_is_covered_by_logout` lo cubre si se agrega a la lista.

---

## 6. Costos y presupuesto

### 6.1 Lo que cuesta preparar un alta (estimado con los precios documentados)

| Tarea | Consumo | Costo aproximado |
|---|---|---|
| Lectura de perfil | ≤ 6 créditos ScrapeCreators (1 perfil + ≤ 5 páginas de posts); 0 si está en caché (7 días) | ≤ $0.012 |
| Colores del logo | local | $0 |
| Rubro sugerido | 1 llamada Sonnet 5, esfuerzo bajo | ~$0.005 |
| Hashtags | agente Sonnet 5 con el catálogo | $0.01–0.024 |
| Referentes, **por fase** (sector / nacional / local) | hasta ~2 páginas TikTok por consulta + 8–12 lecturas de perfil por red, más el revisor Claude (~$0.02) | ~$0.05–0.10 por fase |
| **Total con las tres fases de referentes** | | **~$0.20–0.35 por alta** |

Precios: ScrapeCreators ≈ $0.0019/crédito en el plan Freelance ($47 = 25.000), ≈ $0.001 en Business ([doc de ScrapeCreators](scrapecreators-crecimiento-organico-y-contenido-ia.md)); Claude según `qualify_api.claude_tools.PRICES`; consumos medidos del asistente en [ui-brandkit-wizard.md](ui-brandkit-wizard.md). Son estimados, no medidos sobre este flujo: la Fase A2 registra el costo real por tarea (`onboarding_tasks.credits` / `cost_usd`).

### 6.2 Lectura

Incluso preparando todo, un alta cuesta centavos. El riesgo no es el costo unitario, es **preparar en volumen a gente que nunca entra**. Por eso:

### 6.3 Presupuesto por alta

- Cada alta nace con un `credit_budget` (por defecto **100 créditos**) y el worker no lanza una tarea que lo excedería.
- **Obligatorias** (siempre al «Preparar»): perfil, colores, rubro, hashtags.
- **Referentes**: decisión D5. Recomendación: la fase **local** al preparar (es la que más impresiona al cliente en la llamada: «mira, estos son los creadores de tu ciudad») y **sector/nacional cuando acepta la invitación**.
- El panel muestra el gasto acumulado del mes.

---

## 7. Seguridad, privacidad y robustez

1. **El superadmin es la llave de todos los negocios.** De ahí el segundo factor, la verificación por evento, la auditoría en la misma transacción y la puerta única de código (§4.1–4.2).
2. **Las invitaciones del panel saltan las verificaciones extra.** Es tu regla: si tú invitas, ya validaste al dueño de palabra. Turnstile, el código de 6 dígitos y la conexión obligatoria por Meta aplican solo a quien llega sin invitación (con el código compartido, o si algún día se abre el registro); son trabajo aparte, pendiente antes de abrir `/signup` al público. El enlace, además, prueba que el correo es suyo.
3. **No dejar cuentas de Instagram secuestradas.** La reserva de `social_account_claims` (`0044`) no se libera hoy en ningún caso salvo error. Un alta que vence o se anula **libera la reserva** (`account_claims.release`) en la misma transacción que cambia el estado. Si no, un prospecto que no entró dejaría su @ bloqueado para su propio dueño.
4. **Limpieza de negocios en espera abandonados.** Un alta vencida hace más de **30 días** (decisión D7) se purga: tenant en espera, marca, kit precargado, assets en R2 y lecturas guardadas. Solo se borra lo que **nunca fue reclamado** (`brand_kit_drafts.claimed_at IS NULL`). Es lo que corresponde con datos de alguien que no aceptó: aunque el perfil sea público, no tenemos por qué guardarlo.
5. **Idempotencia y reintentos** en todas las tareas (§4.5). Un reinicio del backend a mitad de una preparación no la corrompe ni la duplica.
6. **Sin secretos ni tokens en la auditoría ni en los logs:** los payloads guardan ids y nombres de campo, no valores sensibles.
7. **Correo con remitente honesto:** `Qualify <no-reply@send.attitudefactory.co>` con *Responder a* tu correo de Zoho, para que la respuesta del cliente te llegue a ti.

---

## 8. Plan por fases

Cada fase se puede desplegar sola y deja algo usable.

### Fase A0 — Cimientos (sin pantallas de negocio todavía)

- Identidad de plataforma: `platform_role` en `app_metadata`, `just grant-superadmin`, sesión de plataforma en `AuthState`, redirección a `/admin`, `require_platform_admin()`.
- `qualify_api.platform` + `platform_audit_log` + test estático de puerta única.
- `/admin` vacío con el shell del panel; `AdminState` en el reset del logout.
- **Aceptación:** una identidad sin rol que entra a `/admin` o dispara un evento del panel recibe un rechazo y una fila de auditoría `denied`; una sesión de plataforma no puede abrir ninguna página de negocio (`require_login` la rechaza porque no hay tenant).

### Fase A1 — Negocios e invitaciones

- `/admin/tenants` y su ficha (solo lectura), `/admin/invites` sobre el backend de invitaciones que ya existe.
- Invitación con nombre del negocio, nota personal y *Responder a*; reenviar y anular (`revoked_at`); invitar a una lista.
- **Aceptación:** invitas desde el panel, el correo llega con tu nota, el cliente se registra, la invitación pasa a *aceptada* y todo queda en la auditoría. Anular una invitación la vuelve inservible al instante.

### Fase A2 — Alta en la llamada

- Refactor `brand_prefill` (§4.5) con tests de equivalencia contra el asistente; el asistente pasa a usarlo.
- `tenant_onboardings` + `onboarding_tasks` + worker embebido; tareas obligatorias; progreso en vivo; vista previa; invitación ligada al alta.
- **Aceptación:** desde el celular, en menos de un minuto de llenado, el alta llega a *lista* con perfil, colores, rubro y hashtags; el cliente invitado se registra y cae en la revisión de **su** Brand Kit, sin volver a escribir su @. Un reinicio del backend a mitad del proceso termina igual, sin créditos duplicados.

### Fase A3 — Referentes, presupuesto y limpieza

- Referentes según D5 con presupuesto por alta; costo real por tarea; gasto del mes en el inicio.
- Liberación de reservas al vencer o anular; purga de abandonados (D7).
- **Aceptación:** ninguna alta supera su presupuesto; un alta vencida libera el @; la purga no toca nada reclamado (test con un negocio reclamado y otro abandonado).

### Fase A4 — Endurecimiento y extras

- Segundo factor si no entró antes (D3).
- Webhooks de Resend (entregado / rebotado / abierto) en la ficha de la invitación (gratis en el plan de Resend).
- Métricas del embudo por semana.
- **Solo con ADR propio:** «entrar como» un negocio para soporte (con registro, aviso al cliente y tiempo límite) y la baja de negocios.

### Tests transversales

- Unitarios offline de la FSM del alta, del presupuesto, del armado de documentos del kit y de la plantilla del correo.
- `db`: ciclo completo alta → tareas → invitación → registro → adopción, liberación de reservas, purga.
- Estáticos: puerta única, verificación de rol en cada handler del panel (por inspección de fuente, como los de `test_auth_state.py`), reset del `AdminState` en el logout.
- E2E (suite de `tests/e2e`): el recorrido del §3 en el nicho «locales de comida».

---

## 9. Decisiones del fundador

| # | Decisión | Recomendación |
|---|---|---|
| **D1** | ¿El panel vive en la misma app (`/admin`) o en una app aparte en otro subdominio? | **Misma app, `/admin`.** Un solo despliegue, el mismo login, y el aislamiento real lo dan el rol, la verificación por evento y la puerta única. Una app aparte duplica el despliegue (vas a cuestionarla, con razón) |
| **D2** | ¿Superadmin como identidad aparte sin negocio, o tu login de un negocio con permiso extra? | **Identidad aparte** (§4.1) |
| **D3** | ¿Segundo factor (TOTP) desde la Fase A0, o en A4? | **Antes del primer uso con datos de clientes reales en producción.** Se puede construir A0–A2 en staging sin él |
| **D4** | ¿Quién más será superadmin? (Darwin, Deivid, Raul, Yesika) | Al principio solo tú. El rol admite más personas sin cambiar el diseño; la auditoría registra quién hizo qué |
| **D5** | Referentes: ¿al preparar, al aceptar, o a mano? | **Fase local al preparar; sector y nacional al aceptar** (§6.3) |
| **D6** | El kit precargado: ¿el cliente lo revisa en el asistente o aterriza con el kit dado por terminado? | **Revisa y confirma.** Tú no viste lo que él cambiaría, y confirmar es lo que lo hace suyo |
| **D7** | ¿Cuántos días antes de purgar un alta vencida? | **30 días** |
| **D8** | ¿El remitente firma como Qualify o como tú («Herwin de Qualify»)? | **«Herwin de Qualify»** con *Responder a* tu correo: en un boca a boca, el correo tiene que sonar a ti |

## 10. Riesgos

- **Refactor del asistente (A2).** Es código grande y vivo (`creative_wizard_pages.py`); otras ramas lo tocan seguido. Mitigación: los tests de equivalencia van primero, y el refactor entra en un PR propio antes de las pantallas.
- **Numeración de migraciones.** Este plan agrega al menos dos migraciones después de `0050`; si `main` avanza en paralelo, se renumera como ya pasó con `0043`.
- **Costo de vendors.** Los precios del §6 son estimados; la Fase A2 los mide. Si ScrapeCreators sube precio, el presupuesto por alta lo contiene.
- **Lectura de §6.1.** Este plan asume que el ruling firmado se refiere a lo que ve un **cliente** (§2). Si el fundador lo lee distinto, el plan se detiene en A0.
