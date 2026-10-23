# Plan — QUA-66: login real con Supabase Auth conectado a `tenant_id`

**Fecha:** 2026-08-17 · **Estado:** `[PLAN — alcance confirmado por el fundador 2026-08-18]` — tres rulings del fundador incorporados: (1) **el primer negocio es Polet (hoy Polette, helados de yogur)** (`https://polet.attitudefactory.co/`); (2) **al registrar se asigna un `tenant_id` automáticamente** — el alta es autoservicio (`/signup` crea el tenant), no un CLI; (3) **los datos viven siempre en el Postgres propio** — no se migra nada a Supabase; Supabase es solo para registros/identidad.
**Objetivo en una frase:** reemplazar el selector de tenant de desarrollo por un login real (Supabase Auth) donde **cada credencial resuelve determinísticamente a un `tenant_id`**, de modo que el fundador pueda registrar **un** negocio propio, entrar logueado como ese negocio, y desarrollar el resto del módulo alrededor de ese nicho.
**Hereda, sin renegociar:** el ruling firmado del fundador (2026-08-16) en [`modelo-negocio-operador-multi-emprendimiento.md`](modelo-negocio-operador-multi-emprendimiento.md) §6.1 — **`1 login = 1 tenant = 1 negocio`, sin switch**, cambio de negocio = logout + login con credenciales guardadas en el navegador, y los **6 criterios de higiene de logout** de ese doc. También la nota cross-historia de [`arquitectura.md`](arquitectura.md) §6 (~línea 336): la resolución «qué tenant posee este email» no puede ir por `tenant_session`.

---

## 0. Decisión de alcance: qué es Supabase aquí (y qué NO)

**Supabase entra como proveedor de identidad (Supabase Auth / GoTrue), no como base de datos.** `[CONFIRMADO por el fundador 2026-08-18: «siempre los datos en mi postgres, no se migra a supabase, supabase solo para registros»]`

- Los datos siguen en el Postgres propio (compose local hoy; Hetzner/Railway según [`prioridad-despliegue-subdominio.md`](prioridad-despliegue-subdominio.md) §4). Las tres puertas sancionadas (`tenant_session` / `admin_session` / `credential_session`), el RLS de la migración 0001 y la custodia de credenciales con cifrado de sobre **no se tocan** `[V]`.
- Migrar el Postgres entero a Supabase es una decisión distinta (afecta roles custom, BYPASSRLS, la llave maestra fuera del host, Redis/Celery de Parte 3) y **queda explícitamente fuera de este plan**. Si el fundador quiere evaluarla, es un ADR aparte.
- Lo que Supabase resuelve gratis y hoy: alta de usuarios, hash/custodia de contraseñas, emisión y revocación de sesiones (refresh tokens), y un panel para administrar cuentas — exactamente la parte de QUA-66 que no es diferenciadora y no vale la pena construir.

**Por qué encaja con el modelo firmado:** la estrategia de alias del fundador (`hlrd1993+puntoservis@gmail.com`, `hlrd1993+inmobiliaria@…`) crea **un usuario Supabase distinto por negocio** — Supabase compara emails literales, así que el criterio 6 de higiene (comparación literal, prohibido normalizar el `+…`) se cumple por construcción.

## 1. Arquitectura de la integración

```
Navegador ── /login (email+password) ──▶ Reflex backend (AuthState)
                                            │ sign_in_with_password (supabase-py, server-side)
                                            ▼
                                      Supabase Auth ──▶ user.app_metadata.tenant_id  ← estampado en el aprovisionamiento
                                            │
                                            ▼
                              AuthState.session_tenant_id = tenant_id verificado
                                            │
                                            ▼
                        tenant_session(tenant_id)  →  RLS (sin cambios)
```

Piezas clave:

1. **El mapeo `credencial → tenant` vive en Supabase**, en `app_metadata.tenant_id` (solo escribible con la service-role key, nunca por el usuario). Esto resuelve el problema de `arquitectura.md` §6: el login **no consulta** ninguna tabla cross-tenant — recibe el `tenant_id` del token y recién entonces abre `tenant_session(tenant_id)` para cargar la fila `users` local y validar membresía. Cero lecturas admin en el camino de login.
2. **El login es server-side.** El navegador nunca habla con Supabase: envía email+password al backend Reflex por el websocket, y es el backend quien llama `sign_in_with_password`. La respuesta de esa llamada directa por TLS es autoritativa — no hace falta verificar el JWT por evento, porque el `tenant_id` queda custodiado en el estado Reflex del lado servidor (igual que hoy custodia `session_tenant_id`).
3. **Vínculo local:** `users.auth_user_id UUID UNIQUE NULL` (nueva revisión Alembic 0005) apunta al usuario de Supabase. El aprovisionamiento escribe ambos lados; el login valida que la fila exista y esté viva dentro del tenant.
4. **Logout = revocación real:** `sign_out` revoca el refresh token en Supabase (criterio 1: «token de sesión rotado/invalidado»), el estado Reflex se resetea con `reset()` en cadena, y la app redirige a `/login` — no «limpia» la UI en sitio.
5. **Seam testeable:** un protocolo `AuthProvider` (métodos `sign_in`, `sign_out`, `get_user`) con dos implementaciones — `SupabaseAuthProvider` (real) y `FakeAuthProvider` (tests, offline). El gate `-m "not integration"` nunca toca la red, como hoy.

## 2. Fases y entregables

### F0 — Aprovisionamiento del proyecto Supabase (fundador + agente, ~1 sesión corta)

- Crear el proyecto Supabase (free tier alcanza). Recoger `QUALIFY_SUPABASE_URL`, `QUALIFY_SUPABASE_ANON_KEY`, `QUALIFY_SUPABASE_SERVICE_ROLE_KEY` (naming consistente con `QUALIFY_META_*`).
- Configuración del proyecto: **desactivar signups públicos del lado Supabase** (Auth → deshabilitar sign-ups directos). El registro pasa siempre por el `/signup` de Qualify (F2), que crea el usuario vía **admin API** con la service-role key — así nadie puede crearse un usuario Supabase por fuera del flujo que crea el tenant, y los usuarios nacen con email confirmado (ningún mail de confirmación estorba a los alias `+`).
- Sobre la service-role key: la usa **solo el backend Reflex/API del lado servidor** (el módulo de registro) — nunca se serializa al cliente ni sale del entorno del servidor. Es el mismo perímetro de confianza que hoy ya ejerce `admin_session` (BYPASSRLS) desde ese mismo proceso.

### F1 — Backend: seam de auth + servicio de registro (`packages/api`)

- `uv add supabase` en `packages/api` (respetando la regla de siempre-`uv` y la trampa del venv compartido: sync con `--group ml`).
- Nuevo módulo `qualify_api/auth/`: `provider.py` (protocolo + DTO `AuthenticatedIdentity{auth_user_id, email, tenant_id}`), `supabase_provider.py`, `fake.py` (para tests), `config.py` (settings desde env, patrón `MetaOAuthSettings`).
- **Alembic 0005** (`auth_identity`): `users.auth_user_id UUID UNIQUE NULL`. Downgrade limpio (la reversibilidad es gate). No se edita 0001: es un cambio lógico nuevo.
- **Servicio de registro `register_business(...)`** — el corazón del ruling «al registrar se asigna un `tenant_id` automáticamente». Entrada: nombre del negocio, email (alias), password, país/tz/moneda. Secuencia:
  1. Genera el `tenant_id` (uuid4) **antes** de tocar nada.
  2. Crea el usuario en Supabase (admin API: email confirmado, `app_metadata.tenant_id` estampado).
  3. En una sola transacción `admin_session` (crear un tenant es inherentemente cross-tenant, igual que el seed): `tenants` + `users` (con `auth_user_id`) + `tenant_members` owner + `brands` inicial con el nombre del negocio.
  4. **Idempotente por email:** si el paso 3 falla después del 2, queda un usuario Supabase sin tenant local; el login lo detecta (fila `users` ausente) y rechaza con «registro incompleto», y re-ejecutar el registro con el mismo email completa el lado faltante en vez de duplicar. Mismo patrón upsert-por-existencia del seed.
- **CLI fino sobre el mismo servicio**: `just register-business "<nombre>" <país> <tz> <moneda> <email-alias>` — útil para dar de alta un login sobre los tenants ya sembrados (PuntoServis/Inmobiliaria) sin pasar por la UI, y como herramienta de recuperación. No es un camino distinto: llama exactamente a `register_business`/una variante `link_login` para tenants existentes.

### F2 — Reflex: signup, login, guardas y muerte del selector de dev (`Qualify/`)

- **Página `/signup`** (nueva, primera del flujo): nombre del negocio, email (alias `hlrd1993+<negocio>@gmail.com`), password, y país/tz/moneda con defaults sensatos editables. Al enviar, el evento server-side llama `register_business(...)` (F1), y con el registro exitoso hace sign-in automático y aterriza en la app **ya logueado como el tenant recién creado** — eso es «al registrar se asigna un `tenant_id` automáticamente» visto desde el navegador. Mientras no haya despliegue público el signup queda abierto; antes de desplegar se le antepone un invite-code por env var (`QUALIFY_SIGNUP_CODE`) para que nadie más se cree tenants.

- **`AuthState`** (sustituye la custodia repetida): hoy `connections_state`, `leads_state`, `clarity_state` (y pares) duplican `tenant_options` / `session_tenant_id` / `switch_tenant` `[V]`. Pasa a haber **una** fuente: `AuthState.session_tenant_id`, poblada solo por login exitoso. Los substates la leen; `switch_tenant` y el roster `available_tenants()` **se eliminan** del camino de la app (el ruling de §6.1 elimina el switch; `qualify_shared.dev` queda solo para tests/seed o se retira).
- **Página `/login`**: email + password, mensaje de error genérico (sin distinguir «no existe» de «password mal»), compatible con el autocompletado del gestor de contraseñas del navegador (eso ES el switcher del operador).
- **Guardas de ruta**: todas las páginas actuales (`/`, `/connections`, `/publish`, `/inbox`, `/leads`, `/clarity`, `/vitrina`) exigen sesión; sin sesión → redirect a `/login`.
- **Logout con la higiene completa** (criterios 1-4 del doc firmado): `sign_out` en Supabase → `reset()` de todos los estados → purge de claves cliente → redirect. Persistencia de sesión en el cliente: **v1 no persiste nada** (el estado Reflex del lado servidor sobrevive al reload vía client token; tras reinicio del server se re-loguea con credenciales guardadas — es el flujo que el fundador ya eligió). Si luego se quiere sesión durable, será una cookie con refresh token, purgada en logout y restaurada vía `get_user` — hardening opcional, no bloquea nada.

### F3 — Tests y enforcement (gates verdes antes de registrar a nadie)

- **Test estático de namespacing** (criterio 2): grep/AST sobre usos de `rx.LocalStorage`/`rx.Cookie` en `Qualify/` — toda clave persistida de datos de negocio debe llevar prefijo de `tenant_id`. Hoy debería pasar en vacío; el test existe para que siga pasando.
- **Test del ciclo logout** (criterios 1, 5 a nivel estado): login A (fake provider) → poblar estados → logout → login B → aserción de que nada de A es visible ni recuperable. El E2E de navegador real queda como seguimiento cuando haya despliegue.
- **Test de resolución determinista** (criterio 6): dos usuarios fake con emails alias distintos → tenants distintos; un token sin `app_metadata.tenant_id` → login rechazado, nunca adivinado.
- Adaptar los tests existentes de estados (hoy asumen el selector de dev) y dejar el gate raíz verde (base actual: 398 offline + 40 db).

### F4 — Registro real de Polette y validación manual

1. Registrar el primer negocio **por la propia página `/signup`** (dogfooding del flujo completo, no por CLI): **Polette** con `hlrd1993+polet@gmail.com`. Datos del negocio según lo ya verificado en [`estrategia-contenido-bianki-polet.md`](estrategia-contenido-bianki-polet.md) §1: helados de yogur (fundador, 2026-10-23) en Korner, San Cristóbal, Táchira (VE) — sitio `https://polet.attitudefactory.co/`; propuesta de defaults: país `VE`, tz `America/Caracas`, moneda `USD` (los precios del sitio están en dólares).
2. Verificar que el signup dejó: fila en `tenants` (uuid nuevo auto-asignado), `users` con `auth_user_id`, `tenant_members` owner, `brands` «Polette», y el usuario Supabase con `app_metadata.tenant_id` correcto.
3. Login manual en la app corriendo local: verificar que **solo** se pintan datos de ese tenant (conexiones, leads, clarity — nacerá vacío, que es lo correcto), guardar la credencial en el navegador.
4. Logout → login como uno de los tenants sembrados (vía `just register-business` sobre PuntoServis): verificar en vivo el criterio «la sesión A nunca pinta datos del tenant B».
5. A partir de aquí, todo el desarrollo del módulo se hace logueado como Polet — el selector de dev deja de existir, y el nicho de trabajo es el local de helados de yogur (contenido, sellos/cupones, vitrina, Clarity del sitio `polet.attitudefactory.co`).

## 3. Decisiones del fundador — resueltas (2026-08-18)

| Pregunta | Ruling |
|---|---|
| ¿Qué negocio primero? | **Polette** (`https://polet.attitudefactory.co/`) — el módulo se desarrolla alrededor de este negocio/nicho |
| ¿Alta por CLI o autoservicio? | **Autoservicio: al registrar se asigna un `tenant_id` automáticamente** (el `/signup` crea el tenant). El CLI queda como herramienta fina sobre el mismo servicio |
| ¿Supabase como DB? | **No, nunca** — los datos siempre en el Postgres propio; Supabase solo para registros/identidad |

## 4. Riesgos y cómo el plan los neutraliza

| Riesgo | Mitigación |
|---|---|
| Dependencia de red en el gate de tests | `FakeAuthProvider` + `-m "not integration"`; la llamada real a Supabase solo ocurre en login humano y en un test marcado `integration` |
| Service-role key filtrada al cliente | Vive solo en el env del servidor y la lee únicamente el módulo de registro (server-side); jamás entra en un estado Reflex serializable ni en el navegador. Test estático: ningún import del provider admin fuera de `qualify_api/auth/` |
| Signup público abierto = cualquiera crea tenants | Aceptable mientras solo corre local; **gate obligatorio antes de desplegar**: invite-code por env var (`QUALIFY_SIGNUP_CODE`) |
| Estado rancio entre tenants en el mismo navegador | Criterios 1-5 del doc firmado, con enforcement por test, no por convención |
| Supabase caído = no se puede entrar | Aceptado para v1 (es el mismo trade-off que cualquier IdP). El dev local puede seguir entrando vía un fake provider habilitado por env var explícita (`QUALIFY_AUTH_FAKE=1`, prohibido en despliegue) |
| Tentación de «normalizar» el email alias | Prohibido por el criterio 6 firmado; test lo cubre |

## 5. Qué NO entra en este plan

- Migrar Postgres a Supabase (ADR aparte, si algún día).
- Autenticar la API HTTP (`qualify_api.http.deps.Principal`) con estos JWT — el hook queda natural (verificar el access token de Supabase en `build_dev_principal_dependency`'s sucesor), pero es historia separada; la UI Reflex no pasa por ahí.
- Multi-asiento (invitar agentes de la inmobiliaria), reset de contraseña self-service, vista de cartera/operador global — todo posterior, y lo último contradiría el ruling firmado. (El signup **sí** entra — ruling del 2026-08-18 — pero con invite-code antes de cualquier despliegue.)
