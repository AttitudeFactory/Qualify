# ADR 46 — Lectura de Google Ads por la cuenta administradora de Attitude Factory

`[FIRMADO 2026-11-05 por el fundador · propuesto por principal-architect 2026-11-04 · Meegle m-24945024 · condicionado a la prueba P1]`

Origen: decisión del fundador del 2026-11-05 en `docs/decision-google-ads-seguimiento.md` §8
(opción C: API de Google Ads de solo lectura, piloto con un negocio, MCC de Attitude Factory,
proyecto de Google Cloud con acceso Explorer). Este ADR responde lo que el §8 dejó pendiente:
cómo se guarda la credencial de la MCC y cómo se acotan las lecturas por negocio. No reabre la
elección de C.

Niveles de evidencia como en `qualify-business-decisions`: `[V]` código en disco o página
oficial consultada (fecha y URL), `[S]` terceros o búsqueda sin página oficial abierta, `[H]`
inferencia nuestra.

## 1. Decisión (resumen)

1. **Una sola credencial de plataforma, no una por negocio:** una **cuenta de servicio** de
   Google Cloud agregada como usuario **de solo lectura** de la MCC de Attitude Factory. Sin
   OAuth del dueño, sin pantalla de consentimiento, sin token que caduque a los 7 días.
2. **El aislamiento entre negocios no vive en la credencial (que ve todas las cuentas
   vinculadas) sino en una tabla de vínculos con RLS** (`google_ads_links`): el worker solo
   consulta un `customer_id` que leyó de un vínculo **activo** de ese negocio por
   `tenant_session`, y comprueba en la respuesta que los datos son de ese `customer_id` antes
   de guardarlos.
3. **Un `customer_id` pertenece a un solo negocio a la vez** (índice único global sobre los
   vínculos vivos), y en el piloto **solo el operador crea vínculos** (no hay pantalla para
   escribir un id).
4. **Módulo nuevo `qualify_api.google_ads`**, separado de `qualify_api.ads` (Meta). Cliente REST
   con `httpx` (como el de Meta), sin el SDK `google-ads` (gRPC). Tabla
   `google_ads_daily_metrics` con RLS, procedencia y clave natural para `ON CONFLICT`.
5. **Sin servicio nuevo:** la lectura diaria es una tarea del `calendar-worker` (como las
   alertas de costo), con tiempo máximo y fallo aislado; también se puede correr a mano con
   `--once --tenant <uuid>`.

## 2. Hechos de Google en los que se apoya (verificados 2026-11-04)

| Hecho | Nivel | Fuente |
|---|---|---|
| Los developer tokens se retiraron el 2026-09-09; el nivel de acceso es del proyecto de Cloud | `[V]` | [Access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels) |
| Explorer: 2.880 operaciones/día contra cuentas reales (15.000 en prueba), ventana móvil de 24 h; revisión automática; sin creación de cuentas, gestión de usuarios, planificación ni facturación | `[V]` | misma |
| Basic exige verificación de marca del proyecto; Standard, auditoría manual ~10 días hábiles | `[V]` | misma |
| Una consulta (`Search` paginado o `SearchStream`) cuenta **una** operación, sin importar filas ni páginas | `[V]` | [Rate sheet](https://developers.google.com/google-ads/api/docs/api-policy/rate-sheet) |
| Las peticiones rechazadas con `GoogleAdsFailure` también consumen cupo | `[S]` | resumen de búsqueda de [Quotas](https://developers.google.com/google-ads/api/docs/best-practices/quotas); la página no se abrió entera |
| Entrando por una MCC, cada llamada lleva `login-customer-id` = id de la MCC; sin ella, `USER_PERMISSION_DENIED` | `[V]` | [Call structure](https://developers.google.com/google-ads/api/docs/concepts/call-structure) |
| Una cuenta de servicio se agrega como usuario en *Admin > Acceso y seguridad*, también en una MCC; «no requiere autorización humana»; debe estar en el mismo proyecto de Cloud con el nivel de acceso | `[V]` | [Service accounts](https://developers.google.com/google-ads/api/docs/oauth/service-accounts) |
| Ese flujo no exige Google Workspace ni delegación de dominio (desde nov-2024) | `[S]` | [Blog de Google Ads Developers, 2024-11-27](https://ads-developers.googleblog.com/2024/11/improved-support-for-service-accounts.html) (solo título legible) |
| Con la pantalla de consentimiento en «Testing», el refresh token caduca a los 7 días; el alcance `adwords` es sensible (app sin verificar: aviso y tope de 100 usuarios) | `[S]` | foros de la API y documentación de OAuth de Google |
| Proyectos que suben a Explorer/Basic después del cambio reciben a veces `AUTHORIZATION_ERROR` en cuentas reales | `[S]` | citado en el §3 del documento de decisión |
| El rol «Solo lectura» en la MCC impide cambios en las cuentas cliente | `[H]` | práctica conocida de Google Ads; se confirma en la prueba P1 |
| Explorer permite **aceptar** o **crear** la invitación de vínculo por API (`CustomerClientLinkService`) | `[H]` | no confirmado; podría contar como «gestión de usuarios». En el piloto se hace a mano |

## 3. Pregunta 1 — la credencial y el aislamiento por negocio

### Opciones

| Opción | Qué es | Aislamiento | Para el dueño | Trámites | Si se filtra el secreto |
|---|---|---|---|---|---|
| **A. Cuenta de servicio en la MCC, solo lectura** (recomendada) | Un JSON de cuenta de servicio como secreto de plataforma; la MCC ve las cuentas que aceptaron el vínculo | En nuestra tabla `google_ads_links` (RLS) + comprobación del `customer_id` en la respuesta | Acepta una invitación en su Google Ads; nada más | Ninguno de OAuth | Lectura de las métricas de **todas** las cuentas vinculadas, sin poder cambiarlas. Se revoca borrando la clave en Cloud |
| B. OAuth humano interno (el fundador autoriza una vez por la MCC) | Un refresh token del fundador | Igual que A | Igual que A | Pantalla en «In production» sin verificar (aviso, tope 100 usuarios — no aplica a un solo usuario) | El token hereda los permisos del fundador (**administrador**: puede cambiar campañas). Caduca si se deja en «Testing» |
| C. OAuth por cliente | Cada dueño autoriza su Google; token cifrado en `oauth_credentials`, leído por `credential_session` | En la credencial misma: un token solo ve lo de ese dueño | Pantalla de Google con aviso de «app no verificada» hasta verificar el alcance sensible | Verificación del alcance `adwords` (video, semanas) | Solo ese negocio |

### Recomendación: A

- **Por qué no `credential_session`:** esa puerta existe para secretos **de un negocio**
  (`oauth_credentials`, RLS por `app.tenant_id`, `qualify_credential` como único lector de
  `ciphertext`). La clave de la MCC no es de ningún negocio: es de Attitude Factory, como
  `SCRAPECREATORS_API_KEY`. Guardarla en una tabla con `tenant_id` obligaría a inventar un
  tenant «plataforma» o a saltarse RLS. Va en el entorno de producción
  (`QUALIFY_GOOGLE_ADS_SA_JSON` en `.env.prod`, cargado con `just env-push`; lo hace el fundador)
  y la lee solo `qualify_api.google_ads.auth`, que firma el JWT y devuelve un
  `AuthenticatedClient` (el mismo protocolo de `connections/resolver.py`), nunca el token.
- **Dónde queda el aislamiento:** la regla dura de `CLAUDE.md` es «RLS en toda tabla y acceso solo
  por las puertas». A la cumple: las métricas y los vínculos son tablas con RLS escritas por
  `tenant_session`; lo único global es el secreto, que no es una fila. Pero A **traslada el riesgo
  al código del worker**: una credencial capaz de leer a todos los clientes, guiada por un
  `customer_id`. Tres controles lo cierran:
  1. **El cliente no acepta un id suelto.** `GoogleAdsReader.daily_metrics(link: ActiveLink, …)`
     recibe un `ActiveLink`, valor que solo construye el repositorio desde una fila
     `status='active'` leída con `tenant_session(tenant_id)`. Una prueba estática impide
     construir `ActiveLink` fuera del repositorio (patrón de `test_creative_worker_door_sanctity.py`).
  2. **Comprobación en la respuesta.** La GAQL selecciona `customer.id`; si una fila trae un id
     distinto al del vínculo, se descarta la corrida entera y se alerta (no debería pasar nunca:
     la URL lleva el id; es un seguro contra un error nuestro).
  3. **Un `customer_id` vivo pertenece a un solo negocio.** Índice único parcial
     `(customer_id) WHERE status IN ('pending','active')`. Si el negocio B intentara vincular la
     cuenta de A, falla (la violación revela que «ya está vinculada», aceptable). En el piloto el
     vínculo lo crea el operador tras comprobar fuera de Qualify que la cuenta es del dueño; el
     día que haya pantalla, el vínculo pasa a `active` **solo cuando la invitación que creó
     Qualify para ese negocio** (`manager_link_id` guardado) figura aceptada en Google — escribir
     un id ajeno nunca basta.
- **Solo lectura en la MCC** convierte una filtración en una fuga de métricas, no en gasto en
  campañas ajenas. El fundador es administrador de la MCC con su usuario; la cuenta de servicio no.
- **C se reabre** si un cliente no acepta vincular su cuenta a una MCC ajena (una agencia que ya
  la gestiona, una exigencia contractual) o si los clientes con Google Ads pasan de ~20: la
  verificación del alcance sensible ya se justificaría y el radio de una filtración crece. B no
  se recomienda: mismo radio que A y con permisos de administrador.

## 4. Pregunta 2 — esquema

Numerar contra `origin/main` al escribirla (hoy la cabeza es `0124`; puede haber otra antes).
Una revisión, dos tablas, RLS en la misma revisión (`qualify-migration`).

**`google_ads_links`** — qué cuenta de Google Ads lee cada negocio.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid NOT NULL | FK `tenants`; RLS |
| `brand_id` | uuid NOT NULL | FK compuesta `(brand_id, tenant_id) → brands(id, tenant_id)` (ADR 24: `brand_id` ≠ `tenant_id`) |
| `customer_id` | text NOT NULL | 10 dígitos sin guiones, `CHECK (customer_id ~ '^[0-9]{10}$')` |
| `manager_customer_id` | text NOT NULL | id de la MCC usada (va en `login-customer-id`) |
| `manager_link_id` | text NULL | id de la invitación en Google, cuando se cree por API |
| `currency_code`, `time_zone` | text NULL | leídos de `customer` en la verificación; las fechas de métricas son en la zona de la cuenta |
| `status` | text NOT NULL | `CHECK IN ('pending','active','revoked','error')` |
| `verified_at`, `last_synced_at`, `revoked_at` | timestamptz NULL | |
| `last_error_code` | text NULL | código, nunca el mensaje de Google |
| `created_by` | uuid NULL | quién lo creó (operador) |
| `created_at`, `updated_at` | timestamptz NOT NULL | |

Restricciones: `UNIQUE (id, tenant_id)` (para la FK compuesta de las métricas); índice único
parcial `ON (customer_id) WHERE status IN ('pending','active')`; índice `(tenant_id)`.

**`google_ads_daily_metrics`** — una fila por (vínculo, campaña, día).

| Columna | Tipo | Nota |
|---|---|---|
| `id` | bigint identity PK | |
| `tenant_id`, `brand_id` | uuid NOT NULL | RLS |
| `link_id` | uuid NOT NULL | FK compuesta `(link_id, tenant_id) → google_ads_links(id, tenant_id)`: una métrica nunca apunta a un vínculo de otro negocio |
| `customer_id`, `campaign_id` | text NOT NULL | ids de Google (procedencia: de dónde salió) |
| `campaign_name`, `campaign_status`, `channel_type` | text | foto del día |
| `metric_date` | date NOT NULL | `segments.date`, zona de la cuenta |
| `impressions`, `clicks` | bigint NOT NULL | |
| `cost_micros` | bigint NOT NULL | sin flotantes; `currency_code` text NOT NULL al lado |
| `conversions`, `conversions_value` | numeric NOT NULL | Google los da con decimales |
| `api_version` | text NOT NULL | p. ej. `v22`; procedencia |
| `pipeline_version` | text NOT NULL | versión de nuestra consulta GAQL |
| `fetched_at` | timestamptz NOT NULL | |
| `raw` | jsonb NOT NULL | la fila tal como vino (regla: guardar lo crudo para re-parsear); ~1 KB |

- **Idempotencia:** `UNIQUE (tenant_id, link_id, campaign_id, metric_date)` y
  `INSERT … ON CONFLICT DO UPDATE … WHERE EXCLUDED.fetched_at > google_ads_daily_metrics.fetched_at`
  (un reintento tardío no pisa una lectura más nueva). Google corrige conversiones días después:
  cada corrida relee los **últimos 7 días** en **una** consulta (una operación).
- **RLS** en las dos: `ENABLE` + `FORCE` + la política
  `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` en `USING` y
  `WITH CHECK`. **Grants:** `qualify_app` `SELECT, INSERT, UPDATE` en ambas (sin `DELETE` en
  métricas: al revocar se conservan; la purga de datos de un negocio que se va entra en el flujo
  de purga de conexiones existente como historia aparte); `qualify_admin` `SELECT` en
  `google_ads_links` (lo necesita el descubrimiento de negocios, solo ids).
- **Reversible:** `downgrade()` borra índices, políticas y las dos tablas (son nuevas; no hay datos
  de otra tabla que restaurar). CI corre `upgrade → downgrade base → upgrade`.
- **Prueba `-m db`:** el negocio A no ve ni los vínculos ni las métricas de B por
  `tenant_session`; una métrica con `link_id` de otro negocio falla por la FK compuesta; el
  índice único parcial rechaza el mismo `customer_id` vivo en dos negocios.
- **Volumen:** piloto 1 cuenta × ~10 campañas × 365 = ~3.650 filas/año (~4 MB con `raw`). Con 100
  negocios, ~365.000 filas/año. Muy lejos del umbral de ADR 31.

**Puertas que usa el worker:** `admin_session` **solo** para listar los `tenant_id` con vínculo
`active` (ids, como `planner/discovery.DiscoveredTenants`); todo lo demás —leer el vínculo,
escribir métricas, marcar `last_synced_at` o `error`— por `tenant_session(tenant_id)`. Ninguna
puerta nueva, ningún rol nuevo. Con `--tenant <uuid>` no se toca `admin_session`.

## 5. Pregunta 3 — módulo, cliente, errores y cupo

**Dónde:** `packages/api/src/qualify_api/google_ads/` (nuevo). `ads/` es la Marketing API de
Meta: su autenticación pasa por `connections` y `CredentialResolver`, sus errores son códigos de
Graph y su cliente es de escritura con aprobación. Compartir carpeta mezclaría dos proveedores
sin código común. Lo que sí se comparte es la **pantalla**: Resultados lee las dos fuentes.

```
google_ads/
  auth.py        # lee QUALIFY_GOOGLE_ADS_SA_JSON, firma el JWT (google-auth), devuelve AuthenticatedClient
  client.py      # GoogleAdsReader (Protocol) + GoogleAdsRestReader (httpx, searchStream)
  fake.py        # FakeGoogleAdsReader: filas sembradas, fallos en cola, registro de llamadas
  errors.py      # GoogleAdsError: solo códigos (enum de error de Google), nunca el mensaje
  links.py       # repositorio de google_ads_links; único constructor de ActiveLink
  metrics.py     # upsert idempotente de google_ads_daily_metrics
  sync.py        # una corrida: vínculos activos → consulta → comprobación → upsert
  worker.py      # CLI --once / --tenant / --all-tenants; tarea diaria del calendar-worker
```

- **Patrón a copiar de Meta** (`ads/client.py`, `ads/fake.py`): un `Protocol` estrecho
  (`daily_metrics(link, since, until) -> tuple[MetricRow, ...]` y `verify(link) -> AccountInfo`),
  una implementación real que recibe un `AuthenticatedClient` ya autenticado y nunca un token, un
  doble en memoria para las pruebas sin red, y la regla de no conservar ni encadenar excepciones
  de transporte (pueden llevar cabeceras). Versión de la API en
  `QUALIFY_GOOGLE_ADS_API_VERSION` validada con regex, como `MarketingSettings`.
- **REST, no SDK:** `POST https://googleads.googleapis.com/{version}/customers/{customer_id}/googleAds:searchStream`
  con cabecera `login-customer-id`. El SDK oficial trae gRPC y protobuf al venv por un `SELECT`;
  `httpx` ya está. Dependencia nueva pequeña: `google-auth` para firmar el JWT de la cuenta de
  servicio (mejor que firmar a mano con `cryptography`). Es una librería, no un runtime ni un
  proveedor de datos.
- **GAQL única por cuenta y corrida:** `SELECT customer.id, campaign.id, campaign.name,
  campaign.status, campaign.advertising_channel_type, segments.date, metrics.impressions,
  metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value FROM
  campaign WHERE segments.date BETWEEN '<hoy-7>' AND '<ayer>'`.
- **Errores:** se clasifican por el enum de Google, no por el texto. `AUTHENTICATION_ERROR` /
  `AUTHORIZATION_ERROR` / `USER_PERMISSION_DENIED` → vínculo a `error` con el código (el dueño
  quitó a la MCC, o el fallo conocido del cambio de niveles) y aviso al equipo en Lark; no se
  reintenta hasta que el operador lo reactive. `QUOTA_ERROR` / `RESOURCE_EXHAUSTED` / 429 → se
  detiene la corrida entera (el cupo es del proyecto, no de la cuenta) y sigue mañana; 5xx o red →
  un reintento con espera y luego al día siguiente (la ventana de 7 días recupera lo perdido).
  Nada se le muestra al dueño salvo «Tus datos de Google se actualizaron el <fecha>» y, en
  `error`, «Ya no podemos ver tu cuenta de Google Ads. Escríbenos para volver a conectarla».
- **Cupo Explorer (2.880/día):** por cuenta y día, 1 consulta de métricas + 1 de verificación
  (`customer.currency_code, customer.time_zone`, solo al activar y una vez por semana) ≈ 1,2
  operaciones. **Guardia:** contador diario por proyecto en el propio worker (filas de la corrida),
  que se detiene al 50 % (1.440) y avisa: deja margen a reintentos y a pruebas manuales, y los
  errores también cuentan. Alcanza para ~1.000 cuentas; se pide Basic (verificación de marca)
  al pasar de 300 cuentas o al primer `QUOTA_ERROR`.
- **Costo:** US$0 por llamada `[S]`; el «precio» es el cupo. No hay llamada de pago, así que no
  aplica la guardia de precio de la regla 7; aplica la del cupo.
- **Fuera de la petición:** Resultados lee solo Postgres. El dueño nunca dispara una llamada a Google.

## 6. Pregunta 4 — riesgos y puertas

| Riesgo | Tipo | Mitigación |
|---|---|---|
| Una credencial lee a todos los clientes vinculados | Seguridad, dos vías | Solo lectura en la MCC; secreto solo en `.env.prod`; `ActiveLink` + comprobación de `customer.id`; rotación de la clave en Cloud documentada; `security-review` obligatorio sobre la historia del worker |
| Un negocio ve la cuenta de otro (id equivocado) | Seguridad | Índice único parcial; vínculo creado por el operador en el piloto; activación atada a la invitación propia cuando haya pantalla |
| Google niega el acceso por el fallo de niveles (`AUTHORIZATION_ERROR`) | Bloqueo | Prueba P1 antes de escribir código; si falla, verificación de marca y Basic; mientras, opción B del documento de decisión |
| Política de la organización de Cloud bloquea crear claves de cuenta de servicio | Bloqueo `[S]` | Aplica a organizaciones de Cloud nuevas, no a un proyecto de una cuenta personal. Si aparece, B (OAuth del fundador en «In production») como puente, con su riesgo de permisos anotado |
| El dueño lee «conversiones» de Google como clientes reales | Producto | Copia en Resultados: «Lo que Google cuenta como resultado»; la atribución real (`gclid`) es la historia 5 |
| Cambio anual de versión de la API (cada versión vive ~1 año) | Mantenimiento | Versión en variable de entorno + `api_version` en cada fila; recordatorio en el calendario del equipo |
| **Puerta de una vía:** anunciar «Google Ads» como parte del plan | Negocio | Se queda en piloto con un negocio hasta que el fundador decida lo contrario (§5 del documento de decisión) |
| **Puerta de una vía:** datos publicitarios del cliente en nuestra base | Datos | Son métricas agregadas, sin datos de personas; se purgan con el negocio. Se nombra en la política de privacidad antes de pasar de piloto |

**Nuevo ADR:** sí, este (46). Introduce el primer secreto de plataforma que puede leer datos
**privados** de varios negocios (ScrapeCreators solo lee datos públicos), un proveedor nuevo
(Google Ads API) y una forma de aislamiento que no es la de las conexiones de Meta.

## 7. Pruebas antes de archivar historias

- **P1 (fundador + `principal-architect`, 1 h):** crear proyecto de Cloud, habilitar la API,
  pedir Explorer, crear la cuenta de servicio y su clave, crear la MCC, agregar la cuenta de
  servicio a la MCC con rol de solo lectura, vincular una cuenta de Google Ads propia, y correr la
  GAQL del §5 con `curl`. Prueba: devuelve filas; un `mutate` de prueba devuelve error de permiso.
  Registrar el comando (sin secretos) en este documento.
- **P2:** con el piloto vinculado, la misma consulta sobre su `customer_id`.

## 8. Historias revisadas (reemplazan el borrador del §7 del documento de decisión)

En orden; cada una con su ticket Meegle y su PR. Dueño entre paréntesis.

1. **GA-1 Plataforma: proyecto, MCC y secreto** (fundador + platform). Proyecto de Cloud con
   Explorer, MCC de Attitude Factory, cuenta de servicio con rol de solo lectura en la MCC,
   `QUALIFY_GOOGLE_ADS_SA_JSON` y `QUALIFY_GOOGLE_ADS_MANAGER_ID` en `.env.prod` y en
   `.env.example` (sin valor). *Aceptación:* P1 pasa; el secreto no aparece en el repo
   (gitleaks verde); `docs/despliegue-hetzner.md` dice dónde vive y cómo se rota.
2. **GA-2 Migración de vínculos y métricas** (backend). Las dos tablas del §4. *Aceptación:*
   `just test-db` con las tres pruebas del §4; CI pasa `upgrade → downgrade base → upgrade`.
3. **GA-3 Cliente de solo lectura** (backend). `auth.py`, `client.py`, `fake.py`, `errors.py`.
   *Aceptación:* pruebas sin red con el doble; la clase real no expone el token (`repr`
   redactado, prueba); una respuesta con otro `customer.id` lanza error; los errores guardan
   código y nunca el mensaje de Google.
4. **GA-4 Lectura diaria** (backend). `links.py`, `metrics.py`, `sync.py`, `worker.py`, tarea
   diaria en el `calendar-worker`, `just google-ads-tick --tenant <uuid>`. *Aceptación:* correr
   dos veces el mismo día no duplica filas; una corrección de conversiones del día −3 actualiza
   la fila; `QUOTA_ERROR` detiene la corrida; `AUTHORIZATION_ERROR` pone el vínculo en `error` y
   avisa en Lark; la guardia del 50 % se prueba con el doble; `security-review` y `review-agent`
   sin hallazgos abiertos.
5. **GA-5 Alta del vínculo por el operador** (backend). Comando `just google-ads-link
   <tenant> <brand> <customer_id>` que crea el vínculo `pending`, lo verifica con la consulta de
   `customer` y lo pasa a `active`. *Aceptación:* rechaza un id ya vivo en otro negocio; rechaza
   un id que la MCC no ve; queda registrado quién lo creó.
6. **GA-6 Pestaña de anuncios en Resultados** (ui, con `ux-designer`). Pestaña «Anuncios» con
   Google ahora y lugar para Meta (`MetaAdsClient.insights` sigue sin uso: historia aparte,
   recomendada en el §6 del documento de decisión). Cifras de los últimos 7 y 30 días en palabras
   del dueño («Lo que invertiste», «Veces que se vio tu anuncio», «Clics», «Lo que Google cuenta
   como resultado», «Cuánto te costó cada resultado») y fecha de la última actualización.
   *Aceptación:* sin vínculo, la pestaña explica qué hacer y lleva al equipo; con datos, cuadra con
   el panel de Google para la misma fecha y moneda; móvil a 375 px; revisión UX local. Nota: hoy
   hay 4 pestañas y `results_vm.py` dice que 4 es el máximo en un teléfono sin deslizar (N12):
   la quinta pestaña es una decisión de UX que `ux-designer` debe resolver (p. ej. «Anuncios»
   solo visible si hay vínculo).
7. **GA-7 `gclid` en leads** (backend, alcance 2, después del piloto). Columna `gclid` en `leads`
   junto a los `utm_*`, capturada del enlace. *Aceptación:* migración reversible; se guarda si
   viene en la URL; ninguna llamada a Google (la atribución con la API de conversiones es otro ADR).

Fuera de alcance: crear o editar campañas de Google; OAuth por cliente (opción C del §3, con su
criterio de reapertura).

## 9. Qué la reabre

- P1 falla y Google pide Basic o Standard para leer por MCC.
- Un cliente no puede o no quiere vincular su cuenta a la MCC de Attitude Factory → OAuth por
  cliente (opción C del §3).
- Más de ~20 negocios con Google Ads vinculados → reevaluar el radio de una sola credencial.
- Más de 1.440 operaciones/día o el primer `QUOTA_ERROR` → pedir Basic.
- Google retira el acceso de cuentas de servicio a la API de Google Ads.
