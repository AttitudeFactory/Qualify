# Revisión de épicas — 2026-10-26

**Autor:** product owner (agente) · **Base:** `main` en `c682e12` (después de #363, #366 y #367) · **Estado:** `[PROPUESTO — el fundador decide]`
**Para qué:** elegir las épicas que más importan ahora y dejar listas 3 historias para construir desde una sesión de Claude Code en la nube (sin límites de uso locales), sin escribir código en esta revisión.

**Cómo se verificó (2026-10-26):**

- **Disco:** `git log --oneline -150`, migraciones en `migrations/postgres/versions/` (cabeza `0097_alta_plan`), lectura del código citado en cada fila.
- **GitHub (MCP):** un solo PR abierto, **#368** `feat/m-24852163-creative-worker`.
- **Meegle (MCP, solo lectura):** las 26 Features «Épica — …» y los Issues de cada épica revisada por el campo «Feature» (`field_00304b`). No se creó, editó ni movió nada.
- **Entorno de la nube (medido en este contenedor):** no hay `gh`, no hay `just`, no hay `.venv`; el cliente de Docker existe pero **el demonio no corre**; hay binarios de Postgres 16 en `/usr/lib/postgresql/16/bin`, sin un clúster levantado. CI (`.github/workflows/ci.yml`) sí corre las pruebas de base (`-m db`) contra un Postgres 16 de servicio y la compuerta `upgrade head → downgrade base → upgrade head`.

**Deriva encontrada (doc o Meegle contra disco):**

| Qué dice | Qué hay | Acción propuesta |
|---|---|---|
| m-24852163 (`creative-worker`) en **RESOLVED** | El código no está en `main`; es el PR #368, abierto | Volver a «In Progress» hasta el merge (§3) |
| La épica m-24854862 apunta a `docs/epica-cuenta-desconectada.md` | El archivo **no existe** | Escribirlo (product owner, PR de docs) |
| `qualify-context` dice «el schema impone un login por negocio» | Sigue cierto: `uq_users_auth_user_id` (`tenancy/models.py:57`, migración 0008) | — |
| `epica-multi-negocio` §1: «planes por negocio diseñados, sin construir» | Construidos sobre la suscripción: `0093_subscription_plans` (#360, m-24852145 Done), paquetes `0095` (#364), plan desde el Alta `0097` (#367). **Falta el saldo común** (`subscription_pool_*`, rol `qualify_pool`): 0093 lo deja explícitamente para S10 | Actualizar §1 de esa épica |
| `epica-escalar-generacion` lista m-24852154 / m-24852156 como pendientes P0 | Done en Meegle; recuperación por id (m-24852492, m-24852495), tiempos (0094), enviar/consultar (#365) y cola `creative_jobs` (0096, #366) en `main` | Actualizar la tabla de esa épica |
| La épica de Suscripciones m-24828931 | Su único hijo (m-24828915) está Done, reemplazado por m-24852145 | Cerrarla o colgar de ella los tickets de planes (§3) |

---

## 1. Ranking de épicas

Criterio (regla 4 del product owner): primero lo que destraba a un cliente real de hoy o la revisión de Meta; después lo que protege dinero ya cobrado; el resto, aparcado con su razón.

### 1. Varios negocios en una sola sesión — [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186) · P1

- **Para el cliente:** el dueño de Bianki (shawarma y ensaladas) y Polette (helados de yogur) maneja los dos negocios con un solo correo y una sola suscripción, sin salir y volver a entrar, y sin riesgo de publicar o crear una pieza en el negocio equivocado.
- **Evidencia:** decisión del fundador 2026-10-23 que revierte §6.1 del modelo de negocio; ADR 43 firmado 2026-10-25 (`docs/adr-43-un-login-varios-negocios.md`); primer caso real nombrado (`docs/epica-multi-negocio-una-sesion.md`, encabezado).
- **Estado real:**
  - Construido: ADR 43 (m-24849187, Done); suscripciones y planes Básico/Plus/Pro sobre la suscripción (`0093`, #360, m-24852145 Done); paquetes de 90 días (`0095`, #364, m-24852129 Done); plan y paquete desde el Alta (`0097`, #367, m-24852131 Done); auditoría de caches de módulo (ADR 43 §2.7); `require_tenant_prefix` en la puerta de R2 (`qualify_shared/objects/gate.py`).
  - Pendiente (todo en Backlog): S1 m-24849188, S10 m-24854773, S9 m-24854772, S6 m-24849193, S7 m-24849194, S3 m-24849190, S4 m-24849191, S5 m-24849192, S2 m-24849189.
- **Lo que falta, en orden:** S1 (identidad) y S10 (saldo común) → S7 (agregar negocio desde el Alta) y S3 (selector) → S2 (altas reales) → S4 → S5. S9 y S6 van en paralelo.
- **Bloqueos y decisiones:** la limpieza de producción decidida el 2026-10-23 (dejar «Zapatería» y «Raul Dev Games», borrar POLETTE y los 5 «Mi marca») **sigue sin ejecutarse**: falta el respaldo y el visto bueno del fundador. No bloquea S1, sí S2.
- **Próxima historia:** **S1 m-24849188 — lista para la nube, con CI como puerta de base de datos** (necesita migración y pruebas `-m db`; ver §2).

### 2. Meta App Review (permisos, videos y Tech Provider) — [m-24786384](https://project.larksuite.com/5h2wsx/story/detail/24786384) · P0

- **Para el cliente:** que cualquier negocio, no solo los que administra el fundador, pueda conectar su Instagram y publicar, responder y (después) anunciar desde Qualify.
- **Evidencia:** prioridad P0 en Meegle; acceso estándar limitado a activos del fundador (ADR 29); portafolio verificado el 2026-10-05 y app en modo Live (`qualify-context` §1).
- **Estado real:** hecho — conexión guiada (m-24789619), suscripción de la Página a webhooks (m-24789549), callback OAuth (m-24789543), respuestas sin modelo local (m-24789548). Pendiente — 8 videos por permiso (Backlog), cuenta de prueba e instrucciones (m-24789546, Todo), configurar la app para producción (m-24789542, Todo, P0), limpiar la cola a 7 permisos (m-24789544, Todo), **borrado de datos de cuentas conectadas (m-24789547, Todo, asignado a Raul)**, envío 1 (m-24789556).
- **Lo que falta:** casi todo es trabajo del fundador en la consola de Meta y grabaciones. La única pieza de código que bloquea el envío 1 es **m-24789547**: la política publicada (`attitudefactory.co/en/privacy` §6 y `/en/data-deletion`) promete borrar en ≤ 30 días y hoy `connections/revoke.py` solo revoca. Ninguna función de purga de conexiones existe en `packages/api` (búsqueda del 2026-10-26).
- **Bloqueos y decisiones:** quién hace m-24789547 (hoy Raul, en Todo, sin rama ni commits); cuántos días esperar tras desconectar antes de borrar (siempre ≤ 30).
- **Próxima historia:** **m-24789547 — lista para la nube con CI como puerta de base de datos**, una vez confirmado el dueño (§2).

### 3. Cuenta desconectada: avisar y volver a conectar en 3 toques — [m-24854862](https://project.larksuite.com/5h2wsx/story/detail/24854862) · P1

- **Para el cliente:** cuando Instagram o Facebook pide volver a conectar, el dueño lo sabe, no pierde de vista sus comentarios ni sus chats y lo arregla en 3 toques; el equipo se entera aunque el dueño no abra Qualify.
- **Evidencia:** análisis de `ux-designer` del 2026-10-24 y decisiones del fundador 2026-10-24/25 (descripción de la épica en Meegle). Medido en código: Comentarios esconde la cuenta degradada (`Qualify/inbox_provider.py:169`, solo `status == "active"`); solo el 401/190 degrada (`connections/composition.py:147`); `CredentialNotFound` no cambia el estado.
- **Estado real:** nada construido de la épica; sus 10 Issues en Backlog (m-24854864 … m-24854873). Existe la base: estados `active/degraded/revoked` (`connections/fsm.py:19`), `degrade_connection_on_auth_error`, `connection_events` con `platform_error_code`.
- **Lo que falta:** primero el estado único en el servidor (m-24854864), que bloquea todas las pantallas, el aviso a Lark (m-24854869) y el correo (m-24854873).
- **Bloqueos y decisiones:** ninguno; todas las decisiones están tomadas. Falta el documento de la épica.
- **Próxima historia:** **m-24854864 — lista para la nube** (pruebas sin red; migración solo si la racha de fallos no cabe en lo que ya existe).

### 4. Escalar la generación: cola, límite de BytePlus y prioridad — [m-24852152](https://project.larksuite.com/5h2wsx/story/detail/24852152) · P1

- **Para el cliente:** ningún video cobrado se pierde y nadie espera horas sin saber por qué cuando hay más negocios generando a la vez.
- **Evidencia:** pedido del fundador 2026-10-24; `docs/escalar-generacion-concurrencia.md`; ADR 41 aprobado (m-24852157).
- **Estado real:** en `main` — recuperación por id de videos y del presentador (m-24852154, m-24852492, m-24852495), reaper de carruseles (m-24852156), tiempos por tarea (`0094`, #362), adaptador enviar/consultar con 429 como «ocupado» (#365), cola `creative_jobs` + semáforo `vendor_slots` (`0096`, #366), llaves aparte para evaluaciones (m-24852161), simulación de concurrencia (m-24855154). **En vuelo:** `creative-worker` (PR #368). Hasta que se despliegue, la generación sigue en hilos de `InlineDispatcher` (`creative/dispatch.py:112`).
- **Lo que falta:** encolar en lugar de lanzar hilos (m-24852166), plazo del final (m-24852168), final de noche (m-24852169), aviso «en fila» y cancelar (m-24852170), avisos a Lark (m-24852167), correo de la mañana (m-24852235). Fases 2 y 3 (m-24852171 … m-24852174) siguen aparcadas con su disparador medido.
- **Bloqueos y decisiones:** merge y despliegue de #368 (rol `qualify_creative_worker` con contraseña en producción: `env-push`, visto bueno del fundador). Precio de «Generar ya» solo al activar la Fase 2.
- **Próxima historia:** m-24852166 — **no ahora**: depende de #368 y toca los mismos archivos (`creative/dispatch.py`, `job_queue.py`). Lista para la nube en cuanto #368 entre.

### 5. Moverse dentro de cada módulo (PASOS) — [m-24852238](https://project.larksuite.com/5h2wsx/story/detail/24852238) · P1

- **Para el cliente:** en el celular, «Siguiente» y «Atrás» siempre a la vista y saber en qué paso va, sobre todo al crear su primera publicación.
- **Evidencia:** pedido del fundador 2026-10-24; `docs/ux-navegacion-pasos-2026-10-24.md` H1–H9; decisiones del 2026-10-25 en `docs/epica-ux-pasos-navegacion-interna.md` §4.
- **Estado real:** Done — PASOS-1 (m-24852240), PASOS-2 el marco (`Qualify/ui/steps.py`, m-24852241), PASOS-4 Tu marca (#363, m-24852243), PASOS-13 menú activo (m-24852260), m-24854881. Backlog — PASOS-5 Crear (m-24852244, **P0**), PASOS-3, 6, 7, 8, 9, 10, 11 y el spike de Motion (PASOS-12).
- **Lo que falta:** PASOS-5 es el recorrido principal (`/create` → `create_index` en `Qualify/creative_pages.py:851`, más `content_generator.py` y `variations_view.py`).
- **Bloqueos y decisiones:** ninguno de producto. De entorno: cada historia exige probar a 360 px en el navegador con captura (N12), y eso pide la app corriendo con su base y su login.
- **Próxima historia:** PASOS-5 — **parcialmente lista para la nube**: código, pruebas del view-model y revisión de `ux-designer` sí; la captura a 360 px necesita una sesión local o al fundador antes del merge.

### 6. Anuncios de Meta desde Qualify — [m-24828970](https://project.larksuite.com/5h2wsx/story/detail/24828970) · P2

- **Para el cliente:** convertir una publicación que ya funcionó en un anuncio con «Más información», pagado desde su propia cuenta publicitaria, sin salir de Qualify.
- **Evidencia:** pedido del fundador 2026-10-21; ADR 38 (m-24789462, Done); `docs/epica-anuncios-meta.md`.
- **Estado real:** nada construido (sin cuenta publicitaria, sin cliente de la Marketing API, sin tablas `ad_*`). Los textos de anuncio ya viven en la pieza (`CopyPayload.ads_*`).
- **Lo que falta:** ADS-00 prueba en vivo (m-24828971) antes de todo; luego ADS-02 … ADS-06 para el MVP.
- **Bloqueos y decisiones:** ADS-00 necesita al fundador con una cuenta publicitaria real y un gasto mínimo; el acceso avanzado a `ads_management` depende del App Review (m-24828986). Sin ADS-00, construir el resto es apostar sobre lo `[NO VERIFICADO]` de la épica.
- **Próxima historia:** ADS-03 cliente de la Marketing API (m-24828973) — **lista para la nube** (todo con respuestas simuladas, sin red ni secretos), pero **se recomienda esperar a ADS-00**. Queda como reserva si sobra capacidad.

**Fuera del top 6, con razón:** identidad de marca precargada desde el Alta (m-24852192) ya está construida y encendida en producción; su segunda ola (m-24854325/326/328/329/330) depende de medir B1 con 30 cuentas reales (m-24854330, `data-scientist-fde`). WhatsApp, Langfuse, ideas para reels y entornos siguen en su ritmo sin bloquear a un cliente hoy.

---

## 2. Próximas historias listas para la nube

### 2.0 Lo que la nube puede y no puede hacer (medido el 2026-10-26)

| Necesidad | En la nube |
|---|---|
| `just` | **No instalado.** Opciones: `uv tool install rust-just`, o correr los comandos de la receta a mano (abajo) |
| Entorno de Python | **Sin `.venv`.** Primer paso: `uv sync` en la raíz (no verificado que el proxy deje bajar todo) |
| Lint como CI | `uv run --no-sync ruff check . && uv run --no-sync ruff format --check .` |
| Pruebas sin red como CI | `uv run --no-sync pytest -m "not integration and not db and not slow"` |
| Pruebas `-m db` (`just test-db`) | **Sin Docker.** Hay binarios de Postgres 16; se puede intentar un clúster desechable en el directorio temporal, pero no está garantizado. **La puerta real es el job de CI** (Postgres 16 + compuerta de reversibilidad) |
| Abrir el PR | Por el MCP de GitHub (no hay `gh`) |
| Merge | `just merge` usa `gh` y no corre aquí. Ver decisión F4 en §4 |
| Workers, envíos, secretos | **Prohibido** correr un worker o tick contra datos reales; sin secretos de producción; sin llamadas a Meta, BytePlus ni ScrapeCreators |
| Mover tickets en Meegle | Hoy solo lectura (instrucción de esta sesión); lo hace el hilo principal o el fundador |

Las tres historias tocan rutas **disjuntas** y pueden ir en paralelo. Única costura: si H2 o H3 necesitan migración, S1 se queda con la `0098` y la otra toma la siguiente al rebasar sobre `main` (`qualify-migration`).

### H1 · S1 — Un mismo login en varios negocios — [m-24849188](https://project.larksuite.com/5h2wsx/issue/detail/24849188) (existe, Backlog, P1 · M)

- **Historia:** como dueño de Bianki y de Polette, quiero que mi único inicio de sesión pertenezca a mis dos negocios, para elegir con cuál trabajar sin otro usuario ni otra contraseña.
- **Evidencia:** ADR 43 §2 (firmado 2026-10-25); `docs/epica-multi-negocio-una-sesion.md` §3 S1.
- **Dueño:** `backend-engineer`. **Nube:** lista, con CI como puerta de base de datos.
- **Rutas (solo estas):** `migrations/postgres/versions/0098_*.py` (nueva), `packages/api/src/qualify_api/tenancy/`, `packages/api/src/qualify_api/auth/` y sus pruebas. **No toca** `Qualify/` (la UI es S3/S4), `plans/`, `connections/`.
- **Criterios de aceptación:**
  1. La migración quita `uq_users_auth_user_id` y crea `UNIQUE(tenant_id, auth_user_id)`; el downgrade falla con un mensaje claro si ya hay un login en dos negocios. `alembic upgrade head → downgrade base → upgrade head` en verde en CI.
  2. `memberships_for(auth_user_id) -> list[Membership]` (id del negocio, nombre, rol) en `qualify_api.auth`, vía `admin_session`; prueba `-m db`: un login con filas en dos negocios devuelve los dos y nada de un tercero.
  3. Prueba de RLS: con `tenant_session(A)` no se lee ninguna fila de `users` ni `tenant_members` de B aunque compartan `auth_user_id`.
  4. `resolve_login` (`auth/service.py:409`) devuelve las membresías; `app_metadata.tenant_id` de Supabase queda como negocio por defecto.
  5. Un dueño con un solo negocio entra, se registra y acepta su invitación igual que hoy: las pruebas existentes pasan **sin tocarlas**. El texto «Ese email ya pertenece a otro negocio; usa un alias distinto por negocio.» no cambia (lo reemplaza S7).
  6. Lint y pruebas sin red en verde.
- **Fuera de alcance:** selector y cambio de negocio (S3/S4), «Inicio de sesión existente» en el Alta (S7), saldo común (S10), vincular logins reales (S2).
- **Dependencias:** S0 (Done). Desbloquea S3, S7 y S2.

### H2 · Un solo estado «necesita volver a conectar» — [m-24854864](https://project.larksuite.com/5h2wsx/issue/detail/24854864) (existe, Backlog, P1 · M)

- **Historia:** como dueña de un local de comida, quiero que Qualify sepa en todas sus pantallas que mi Instagram necesita volver a conectarse, sea cual sea la causa, para que no me insista ni me esconda lo que ya tenía.
- **Evidencia:** decisiones del fundador 2026-10-24/25 en la épica m-24854862; código citado en el ticket (`connections/composition.py:147`, `connections/credential_reader.py:57`, `Qualify/inbox_state.py:887, 913`).
- **Dueño:** `backend-engineer`. **Nube:** lista (pruebas sin red; migración solo si hace falta, y entonces con CI como puerta).
- **Rutas (solo estas):** `packages/api/src/qualify_api/connections/` (salvo `revoke.py`), el sondeo de comentarios (`packages/api/src/qualify_api/inbox/` y el guardián del sondeo en `Qualify/inbox_state.py`), `packages/api/src/qualify_api/conversations/worker.py`, `packages/api/src/qualify_api/whatsapp/worker.py`, sus pruebas. **No toca** pantallas ni textos (`Qualify/inbox_provider.py`, `conversations_page.py`, `whatsapp_vm.py`: son las otras historias de la épica), ni `privacy/`, ni `auth/`.
- **Criterios de aceptación:**
  1. `CredentialNotFound` y el permiso quitado dejan la cuenta en el estado roto con su causa (`missing_credential` / `auth_expired` / `permission_missing`), igual que hoy el 401/190 (pruebas).
  2. Un solo evento de dominio por **caída** (paso a roto), aunque el sondeo falle 10 veces (prueba de idempotencia).
  3. El sondeo de Comentarios y los workers de Conversaciones y WhatsApp no llaman a Instagram con una cuenta rota (prueba con un cliente falso que falla si se lo llama).
  4. Fallos temporales: la racha por cuenta llega a 3, se expone para que la pantalla avise una sola vez y vuelve a 0 con el primer éxito (prueba).
  5. Al volver a «activa» se busca una vez (prueba).
  6. Aislamiento por negocio (prueba con dos negocios); lint y pruebas sin red en verde.
  7. El PR anota, verificado en el código: si los envíos aprobados se reintentan tras reconectar y si los webhooks siguen entrando con la conexión rota.
- **Sin textos nuevos para el cliente** (los textos son de las historias de pantalla de la épica).
- **Fuera de alcance:** pantallas, aviso a Lark (m-24854869), correo (m-24854873).
- **Dependencias:** ninguna. Desbloquea m-24854865 … m-24854873.

### H3 · Borrado de datos de cuentas conectadas (promesa de 30 días) — [m-24789547](https://project.larksuite.com/5h2wsx/issue/detail/24789547) (existe, Todo, P1, **asignado a Raul**)

- **Historia:** como dueño de una inmobiliaria que desconecta su Instagram de Qualify, quiero que sus comentarios, mensajes y credenciales se borren dentro del plazo que promete la política, para confiar en a quién le doy acceso; y como equipo, cumplir lo publicado antes de mandar el envío 1 a Meta.
- **Evidencia:** política `attitudefactory.co/en/privacy` §6 y `/en/data-deletion` (citadas en el ticket); el ticket bloquea m-24789556 (envío 1); búsqueda en `packages/api` del 2026-10-26: no existe ninguna purga de conexiones.
- **Dueño:** `backend-engineer` (con `platform-engineer` para el comando y el disparo diario si hace falta). **Nube:** lista con CI como puerta de base de datos, **después de que el fundador confirme el dueño y el plazo** (F2, §4).
- **Rutas (solo estas):** `packages/api/src/qualify_api/privacy/connection_purge.py` (nuevo) y sus pruebas, una receta en `justfile`, el enganche diario en `packages/api/src/qualify_api/planner/worker.py` (donde ya corre la purga de piezas), y una migración solo si hace falta (número después de S1). **Solo importa, no edita,** `connections/` (lo está tocando H2) y `webhooks/repository.py` (reusa `purge_by_entry_id`).
- **Criterios de aceptación:**
  1. `purge_connection(tenant_id, connection_id, *, execute: bool)` borra, para esa conexión, credenciales (`oauth_credentials`), hilos y mensajes, comentarios, menciones, borradores de respuesta, resultados de sentimiento e intención, eventos de webhook y sus artefactos en R2 (claves pasadas por `require_tenant_prefix`). El inventario de tablas sale de las FK a `social_connections` y queda en el docstring.
  2. Deja un registro de auditoría **sin datos personales** (qué conexión, cuándo, cuántas filas por tabla).
  3. Simulación por defecto, como `--purge`: sin `--execute` imprime lo que borraría y no borra nada.
  4. Purga automática de conexiones revocadas hace más de N días, con N como parámetro (valor que decide el fundador, siempre ≤ 30); idempotente: una conexión ya purgada no se vuelve a tocar.
  5. Prueba `-m db`: después de purgar quedan **cero** filas de esa conexión en las tablas afectadas y las de otra conexión del mismo negocio y de otro negocio siguen intactas.
  6. Nada de esto corre contra producción desde la nube; lint y pruebas sin red en verde.
- **Sin textos nuevos para el cliente.**
- **Fuera de alcance:** el callback «Data Deletion Request» de Meta con `signed_request` (necesita el secreto de la app: otra historia); cambiar la pantalla de desconectar.
- **Dependencias:** confirmación del fundador (F2). No depende de H1 ni de H2.

### Siguientes en la fila (no ahora)

| Historia | Por qué espera |
|---|---|
| PASOS-5 m-24852244 (`reflex-ui-engineer`) | Exige la captura a 360 px con la app corriendo: sesión local o fundador |
| m-24852166 encolar en lugar de hilos (`creative-engineer`) | Depende de #368 y comparte archivos |
| S10 m-24854773 saldo común (`backend-engineer`, `security-review`) | Lista para la nube con CI, pero choca con H1 en la migración y en el diseño de identidad; va justo después de H1 |
| S9 m-24854772 negocio sellado (`creative-engineer`) | Comparte `creative/dispatch.py` y la cola con #368 |
| ADS-03 m-24828973 (`backend-engineer`) | Lista para la nube, pero conviene esperar a ADS-00 |

### Encargos listos para pegar

Cada uno es autosuficiente. El hilo principal los lanza como subagentes en paralelo.

#### Encargo H1 → `backend-engineer`

```text
Tarea: S1 de la épica «Varios negocios en una sola sesión» — Meegle m-24849188.
Repo: /home/user/Qualify. Base: main (c682e12 o más nuevo). Rama: feat/m-24849188-un-login-varios-negocios.
Lee primero: docs/adr-43-un-login-varios-negocios.md (§2), docs/epica-multi-negocio-una-sesion.md (§1, §3 S1), skills qualify-migration y qualify-dev-env.

Qué construir:
1. Migración 0098 (down_revision = cabeza de main en ese momento; hoy 0097): quitar uq_users_auth_user_id (creado en 0008), crear UNIQUE(tenant_id, auth_user_id). Downgrade reversible que falla con un mensaje claro si ya hay un auth_user_id en dos tenants.
2. qualify_api.auth.memberships_for(auth_user_id) -> list[Membership] (tenant_id, nombre del negocio, rol de tenant_members), vía admin_session; nunca devuelve filas de otros logins.
3. resolve_login (auth/service.py:409) devuelve también las membresías; app_metadata.tenant_id de Supabase queda como negocio por defecto. Ajusta el modelo en tenancy/models.py:57.

Criterios de aceptación (todos con prueba):
- upgrade head -> downgrade base -> upgrade head limpio (lo comprueba CI).
- Prueba -m db: un login con filas en dos negocios -> memberships_for devuelve los dos y nada de un tercero.
- Prueba -m db de RLS: con tenant_session(A) no se lee ninguna fila users/tenant_members de B aunque compartan auth_user_id.
- Un dueño con un solo negocio: login, registro e invitación iguales que hoy; las pruebas existentes pasan SIN modificarlas. El texto «Ese email ya pertenece a otro negocio; usa un alias distinto por negocio.» no cambia.
- ruff y pruebas sin red en verde.

Rutas permitidas: migrations/postgres/versions/0098_*.py, packages/api/src/qualify_api/tenancy/, packages/api/src/qualify_api/auth/ y sus pruebas. NO toques Qualify/, plans/, connections/, privacy/, planner/ (otros encargos trabajan ahí en paralelo).
Fuera de alcance: selector/cambio de negocio en la UI, Alta con «Inicio de sesión existente», saldo común.

Entorno de la nube: no hay just, ni gh, ni Docker. Paso 0: `uv sync`. Lint: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check .`. Pruebas: `uv run --no-sync pytest -m "not integration and not db and not slow"`. Las pruebas -m db: intenta un Postgres 16 desechable con /usr/lib/postgresql/16/bin en el directorio temporal si es simple; si no, escríbelas igual y deja que CI las corra (job con Postgres 16). Nunca corras workers ni uses secretos de producción.
Entrega: commits Conventional en inglés, PR por el MCP de GitHub con título «feat(auth): one login in several businesses (m-24849188)» y «Resolves m-24849188» en la descripción, siguiendo qualify-pr. No hagas merge. No muevas el ticket. Devuelve: URL del PR, estado de CI, y qué pruebas -m db corriste localmente y cuáles quedaron solo para CI.
```

#### Encargo H2 → `backend-engineer`

```text
Tarea: estado único «necesita volver a conectar» — Meegle m-24854864 (épica m-24854862, «Cuenta desconectada»).
Repo: /home/user/Qualify. Base: main. Rama: feat/m-24854864-estado-volver-a-conectar.
Lee primero: la descripción del ticket (abajo), packages/api/src/qualify_api/connections/{fsm.py,auth_error.py,composition.py,credential_reader.py}, Qualify/inbox_state.py (sondeo, líneas ~887 y ~913), conversations/worker.py, whatsapp/worker.py. Skills qualify-dev-env y, si hace falta columna, qualify-migration.

Qué construir:
- Toda causa permanente (CredentialNotFound, 401/190, permiso quitado) deja la conexión en el estado roto EN EL SERVIDOR, extendiendo degrade_connection_on_auth_error (o un gemelo), con la causa guardada: missing_credential / auth_expired / permission_missing. Prefiere guardarla en connection_events.platform_error_code (ya existe) antes que una columna nueva.
- Un evento de dominio por caída (transición a roto), no por intento.
- El sondeo de Comentarios y los workers de Conversaciones y WhatsApp se saltan las cuentas rotas: no llaman a Instagram ni limpian el error.
- Fallos temporales: racha de fallos seguidos por cuenta; expone «racha >= 3»; vuelve a 0 con el primer éxito. Al volver a activa se busca una vez.

Criterios de aceptación (todos con prueba sin red, clientes falsos que fallan si se los llama):
- CredentialNotFound y permiso quitado -> cuenta rota con su causa, igual que el 401.
- Cuenta rota -> cero llamadas del sondeo y de los workers.
- Una sola emisión del evento por caída aunque el sondeo falle 10 veces.
- Racha llega a 3 y vuelve a 0 con un éxito.
- Aislamiento por negocio (dos negocios).
- En la descripción del PR: si los envíos aprobados se reintentan tras reconectar y si los webhooks siguen entrando con la conexión rota (verificado leyendo el código, con archivo:línea).
- ruff y pruebas sin red en verde.

Rutas permitidas: packages/api/src/qualify_api/connections/ (NO revoke.py), packages/api/src/qualify_api/inbox/, el guardián del sondeo en Qualify/inbox_state.py, conversations/worker.py, whatsapp/worker.py, sus pruebas. NO toques pantallas ni textos (inbox_provider.py, conversations_page.py, whatsapp_vm.py), ni auth/, tenancy/, privacy/, planner/, migraciones 0098 (otro encargo la usa). Si de verdad necesitas una columna, la migración toma el número siguiente a la cabeza de main al abrir el PR y se rebasa si la 0098 entra antes.
Fuera de alcance: pantallas y textos, aviso a Lark (m-24854869), correo (m-24854873).

Entorno de la nube: no hay just, ni gh, ni Docker. Paso 0: `uv sync`. Lint: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check .`. Pruebas: `uv run --no-sync pytest -m "not integration and not db and not slow"`. Nunca corras un worker ni un tick (publican y envían de verdad); sin secretos.
Entrega: PR por el MCP de GitHub, título «feat(connections): one needs-reconnect state for every permanent cause (m-24854864)», «Resolves m-24854864», según qualify-pr. No hagas merge ni muevas el ticket. Devuelve la URL del PR, el estado de CI y si hubo migración.
```

#### Encargo H3 → `backend-engineer` (solo después de la decisión F2 del fundador)

```text
Tarea: borrado de datos de cuentas conectadas (promesa de 30 días) — Meegle m-24789547 (épica Meta App Review m-24786384; bloquea el envío 1, m-24789556).
Repo: /home/user/Qualify. Base: main. Rama: feat/m-24789547-borrado-cuentas-conectadas.
Contexto: la política publicada (attitudefactory.co/en/privacy §6 y /en/data-deletion) promete borrar perfiles, publicaciones sincronizadas, comentarios, mensajes y credenciales de una cuenta conectada en <= 30 días tras la desconexión o la solicitud. Hoy connections/revoke.py solo revoca. Plazo antes de borrar decidido por el fundador: <N> días (completar con F2).
Lee primero: connections/revoke.py y repository.py (solo lectura), webhooks/repository.py (purge_by_entry_id), creative/retention.py (purge_expired_pieces, patrón de simulación por defecto), planner/worker.py (donde la purga diaria de piezas ya corre), qualify_shared/objects/keys.py (require_tenant_prefix). Skills qualify-dev-env y qualify-migration.

Qué construir:
1. packages/api/src/qualify_api/privacy/connection_purge.py: purge_connection(tenant_id, connection_id, *, execute: bool) -> informe por tabla. Inventario de tablas a partir de las FK a social_connections (migraciones 0002, 0003, 0004, 0005, 0006, 0010-0014, 0024, 0050, 0057, 0060, 0065, 0069, 0071, 0079, 0083): credenciales, hilos y mensajes, comentarios, menciones, borradores de respuesta, sentimiento, intención, seguimientos, eventos de webhook, artefactos en R2 (claves por require_tenant_prefix). Deja el inventario en el docstring.
2. Registro de auditoría sin datos personales (conexión, fecha, filas por tabla).
3. Purga automática de conexiones revocadas hace más de N días (parámetro QUALIFY_CONNECTION_PURGE_AFTER_DAYS, máximo 30), idempotente, enganchada a la pasada diaria del calendar worker; simulación por defecto igual que la purga de piezas.
4. Receta en justfile: `just purge-connection <connection_id> [--execute]` (simulación sin --execute).
Prefiere no migrar (marca de purga en connection_events o similar); si hace falta una tabla, la migración toma el número siguiente a la cabeza de main y se rebasa si la 0098 entra antes; RLS en la misma revisión.

Criterios de aceptación:
- Prueba -m db: tras purgar quedan cero filas de esa conexión en cada tabla afectada; otra conexión del mismo negocio y las de otro negocio quedan intactas.
- Sin --execute no se borra nada (prueba).
- Una conexión ya purgada no se vuelve a tocar (prueba de idempotencia).
- Auditoría sin datos personales (prueba que la revisa).
- ruff y pruebas sin red en verde.

Rutas permitidas: privacy/connection_purge.py (nuevo) y pruebas, justfile (una receta), planner/worker.py (solo el enganche), una migración si hace falta. NO edites connections/ (otro encargo lo está cambiando), auth/, tenancy/, Qualify/.
Fuera de alcance: el callback de Meta con signed_request (necesita el secreto de la app), cambiar la pantalla de desconectar.

Entorno de la nube: no hay just, ni gh, ni Docker. Paso 0: `uv sync`. Lint y pruebas sin red como CI: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check .` y `uv run --no-sync pytest -m "not integration and not db and not slow"`. Las pruebas -m db las corre CI. Nunca ejecutes la purga ni el calendar worker contra datos reales; sin secretos.
Entrega: PR por el MCP de GitHub, «feat(privacy): purge a disconnected account's data within 30 days (m-24789547)», «Resolves m-24789547», según qualify-pr. No hagas merge ni muevas el ticket. Devuelve URL del PR, estado de CI y el inventario de tablas.
```

---

## 3. Cambios propuestos en Meegle (para aprobar)

Nada de esto se hizo: Meegle quedó en solo lectura en esta revisión.

| # | Ítem | Cambio | Por qué |
|---|---|---|---|
| 1 | m-24852163 `creative-worker` | RESOLVED → In Progress hasta el merge de #368 | El código no está en `main` |
| 2 | m-24849188 (S1), m-24854864 | Backlog → In Progress al lanzar los encargos H1 y H2 | Empieza el trabajo |
| 3 | m-24789547 borrado de datos | Prioridad P1 → **P0**; Assignee: confirmar Raul o pasar a Herwin para la sesión en la nube | Bloquea el envío 1 de una épica P0; está en Todo sin rama ni commits |
| 4 | Crear Issue «Docs: épica cuenta desconectada (`docs/epica-cuenta-desconectada.md`)» bajo m-24854862 · P1 · Documentación · product-owner | El documento citado no existe |
| 5 | Crear Issue «Docs: revisión de épicas 2026-10-26» · P2 · Documentación · product-owner | Ticket para el PR de este documento |
| 6 | Crear Issue «Plataforma: preparar las sesiones en la nube (uv sync, just, sin gh; puerta de merge)» · P2 · Infraestructura · platform-engineer | Hoy cada encargo tiene que improvisar el entorno (§2.0); skill `session-start-hook` |
| 7 | ADS-02/03/04/05 (m-24828972 … m-24828975) | P1 → P2 hasta que ADS-00 (m-24828971) termine | P1 dentro de una épica P2 y sin la prueba en vivo |
| 8 | Épica de Suscripciones m-24828931 | Cerrar como reemplazada por m-24852145, o colgarle m-24852145, m-24852129 y m-24852131 | Su único hijo está Done y superado |
| 9 | Épica «Generación: pruebas de modelos, costos y cobro» m-24848869 | Revisar a mano si le quedan hijos abiertos (la consulta filtrada no devolvió ninguno) y cerrarla | Evitar épicas zombis |
| 10 | S10 m-24854773 | Agregar en «Bloqueado por» a S1 m-24849188 | Ver «Siguientes en la fila» |

---

## 4. Decisiones del fundador

| # | Pregunta | Recomendación |
|---|---|---|
| F1 | ¿Apruebas este ranking y lanzar H1 y H2 ya, en paralelo, desde la nube? | Sí: los dos son P1, sin decisiones abiertas y con rutas disjuntas |
| F2 | Borrado de datos (H3): ¿quién lo hace (Raul lo tiene en Todo) y cuántos días esperar tras desconectar antes de borrar? | Pasarlo a la sesión en la nube salvo que Raul ya haya empezado; esperar **7 días** (permite reconectar sin perder nada) y nunca más de 30; parámetro, se puede cambiar |
| F3 | Limpieza de producción (borrar POLETTE y los 5 «Mi marca» con sus logins), decidida el 2026-10-23 y sin ejecutar | Respaldo + tu visto bueno antes de S2 (no bloquea S1) |
| F4 | En la nube no corre `just merge` (usa `gh`). ¿Quién hace el merge? | Los agentes abren el PR y esperan CI en verde; el merge lo haces tú o una sesión local con `just merge`. Alternativa: autorizar merge por el MCP de GitHub solo con CI en verde comprobado |
| F5 | Anuncios: ¿aparcamos hasta que hagas la prueba en vivo ADS-00 con tu cuenta publicitaria? | Sí; ADS-03 queda de reserva |
| F6 | PASOS-5: ¿quién hace la captura a 360 px? | La próxima sesión local; el código puede adelantarse en la nube |

---

## 5. Prompt para `/qualify-team-dev`

```text
/qualify-team-dev Construir desde la nube, en paralelo, dos historias de docs/revision-epicas-2026-10-26.md §2:
- H1 · m-24849188 (S1 multi-negocio) → backend-engineer. Rutas: migración 0098, qualify_api/tenancy/, qualify_api/auth/.
- H2 · m-24854864 (estado «necesita volver a conectar») → backend-engineer. Rutas: qualify_api/connections/ (sin revoke.py), qualify_api/inbox/, guardián del sondeo en Qualify/inbox_state.py, conversations/worker.py, whatsapp/worker.py.
- H3 · m-24789547 (borrado de datos, 30 días) → backend-engineer, SOLO tras la decisión F2 del fundador. Rutas: qualify_api/privacy/connection_purge.py, una receta en justfile, enganche en planner/worker.py.
Usa los encargos literales de §2. Sin just, gh ni Docker: `uv sync`, ruff y pytest sin red como CI; las pruebas -m db las corre CI. Ningún worker contra datos reales, sin secretos. PR por el MCP de GitHub con «Resolves m-<id>»; sin merge (F4).
Después, en este orden: S10 m-24854773 (backend, security-review) tras H1; m-24852166 (creative) tras #368; PASOS-5 m-24852244 (reflex-ui) en una sesión local.
```
