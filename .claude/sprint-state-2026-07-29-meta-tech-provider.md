# Sprint state — Meta Tech Provider / variantes A-B-C / ruling R1

**Agente:** architect-techprovider (principal-architect)
**Fecha:** 2026-07-29
**Estado:** EN CURSO — este fichero se escribe por secciones (durable-findings Regla 1).

Este fichero es el buffer durable de la entrega. El destino final es un ADR nuevo
en `docs/arquitectura.md` §6 en estado **PROPUESTO**. Si esta sesión muere, lo
escrito aquí es lo que sobrevive.

## 0. Hecho nuevo aportado por el fundador (2026-07-29) — AÚN NO EN DOCS

El fundador es **también constructor y administrador del SaaS inmobiliario** que
usa el cliente uno (la inmobiliaria). La relación con el cliente uno **no es de
brazo extendido**: él administra el stack de software de ese cliente. Los docs
describen hoy al cliente uno como cliente externo, y eso ya no es exacto.

Impacto declarado por el lead (a verificar en esta entrega):
- análisis de acceso a Meta (cadena de exención de App Review / Business Verification)
- modelo de tenancy
- frontera estratégica de `docs/integracion-cuentas-conectadas-meta.md` (línea
  Development Mode / Advanced Access como frontera técnica + legal + estratégica)

## 1. Estado de lectura de contexto

- [x] CLAUDE.md
- [x] docs/arquitectura.md §6 (ADR 24/25/26/27/28 + rulings R1–R7; **próxima ADR libre = 29**)
- [x] docs/integracion-cuentas-conectadas-meta.md §3.1, §3.4(c), §3.7, §3.8, §6.5, §7
- [x] migrations/postgres/versions/0002_connections.py (ruling R1 + DDL de `platform_apps`)
- [ ] docs/backlog-crm-workflows.md (contrapunto de roles)

## 2. HALLAZGO 1 — "Tech Provider" ES una figura formal de Meta, y la definición mata la variante C tal como se planteó

**Fuente [P] en disco, cosechada 2026-07-24:**
`reference/meta-instagram-platform/documentation/resp-plat-initiatives/data-access-renewal/content/data-protection-section.md:298-301` y `:378-382`

> **Tech Provider definition:** *"An individual or business that has been granted access to Meta
> APIs for the purpose of creating, maintaining and removing integrations **on behalf of other
> individuals or businesses. This includes individuals or businesses that create a single
> integration on behalf of an individual client or multiple clients.**"*

> *"Tech Providers: Developers of apps whose primary purpose is to manage Platform integrations on
> behalf of customers or clients so they can access and manage their data on Meta products.
> **Examples of Tech Providers include SaaS (software as a service) providers and agencies.**"*

> *"Because this app allows people or businesses (clients) to access and use Platform Data, it
> means that you are a Tech Provider."*

**Consecuencia demoledora para la variante C:** la definición cubre explícitamente *"a **single**
integration on behalf of an **individual** client"*. No hay umbral de N. Un solo cliente ya
constituye Tech Provider. La intuición de que "app por tenant" evita la figura es **falsa por la
letra de la definición**.

Y `documentation/instagram-platform/app-review.md:11-16` liga la figura al nivel de acceso:

| Development scenario | Login type | Access level | App Review |
|---|---|---|---|
| My app is only for a business **I own or manage** | No login / Instagram Login | Standard | Not required |
| My app is only for a business **I own or manage** | No login / Facebook Login | Standard | Not required |
| **I am a Tech Provider and my app serves multiple businesses** | Instagram Login | Advanced | **Required** |
| **I am a Tech Provider and my app serves multiple businesses** | Facebook Login | Advanced | **Required** |

**El gozne exacto, y es la aportación de esta sesión:** la fila exenta no dice "a business I own".
Dice **"a business I own OR MANAGE"**. `instagram-platform/overview.md:37`: *"If your app only
serves your Instagram professional account **or an account you manage**, Standard Access is all
your app needs."*

Y la fila que exige Advanced Access no dice "Tech Provider". Dice **"Tech Provider AND my app
serves MULTIPLE businesses"** — es una conjunción, no una disyunción.

**Aquí es donde el hecho nuevo del fundador (§0) muerde de verdad**, y muerde en la dirección
favorable: si el fundador **administra** los activos del cliente uno, la inmobiliaria cae
potencialmente en *"an account you manage"*, no en *"other businesses"*. Pero esto es una lectura
sobre una tabla de escenarios de desarrollo, no sobre las Platform Terms → ver §3 para el
veredicto, que NO es un sí limpio.

**Nota de método:** `data-protection-section.md` es el cuestionario del **Data Access Renewal**, no
las Platform Terms. Es fuente primaria de Meta y es donde vive la definición operativa que Meta
aplica, pero la asignación de responsabilidad contractual hay que buscarla en las Platform Terms.

## 3. HALLAZGO 2 — Las Platform Terms tienen una sección dedicada al Technology Provider, y asignan la responsabilidad al proveedor

**Fuente [P]:** [Meta Platform Terms](https://developers.facebook.com/terms/dfc_platform_terms/),
accedida **2026-07-29**.

| Cláusula | Contenido |
|---|---|
| **§1.d** | *"If you accept these Conditions or access the Platform… **on behalf of a legal entity**, you declare and warrant that you have authority to bind that legal entity… whenever 'you' is mentioned in these Conditions, it will refer to that legal entity"* |
| **§5.b.ii.1** | *"You, as a Technology Provider, understand and agree [to use] the Platform and Process Platform Data **on behalf of your Client and at the Client's request, in whose representation you access them**, to assist the Client to use the Platform or Process the Platform Data in compliance with these Conditions"* |
| **§5.b.ii** | *"You guarantee that **Platform Data you retain on behalf of one Client remains independent of that of other Clients**"* |
| **§5.b.ii.6** | *"You will **promptly terminate a Client's use** of our Products, the Platform or Platform Data through your App if we request [due to violation concerns]"* |
| **§6.a.iv** | *"You must protect and **not transfer, share or request** Meta user identifiers, **access tokens or app secret keys**, but you may share them with the **Service Provider** that helps you develop, run or operate your App"* |
| **§3.a.vii** | prohíbe *"significantly change the scope of Platform Data Processing previously collected, except [after App Review resubmission and approval]"* |

Definiciones de glosario (resumidas por el fetch, **no verbatim** — el fetcher rehusó reproducir
en bloque; marcar como **[P] parafraseado**, re-verificar antes de citar en contrato):
- **Technology Provider**: developer cuyo propósito principal es permitir a *users* acceder y usar
  la Platform o Platform Data.
- **Client**: el usuario final de la app de un Technology Provider.
- **App**: cualquier integración técnica con la Platform a la que se asigna un **app ID**.

**Tres consecuencias que deciden las preguntas 2 y 3:**

1. **§5.b.ii.6 responde "quién responde ante Meta": el Technology Provider.** Meta le ordena al
   proveedor cortar al Client. La relación de enforcement es Meta → proveedor → cliente. Que la
   app esté registrada bajo el Business Portfolio del cliente **no traslada la responsabilidad al
   cliente**: §1.d dice que "you" es quien acepta los términos, y quien opera la integración y
   custodia los tokens es Qualify. **La variante C no externaliza el riesgo, sólo lo fragmenta.**
2. **§5.b.ii ("Platform Data de un Client independiente del de otros Clients") es, literalmente, la
   obligación contractual que ADR 24 implementa con RLS.** No es una analogía: el aislamiento
   estructural de tenants es una obligación de las Platform Terms, no sólo higiene interna. Esto
   es un refuerzo *nuevo* de ADR 24 que conviene registrar.
3. **§6.a.iv es la cláusula que decide el modelo de custodia de la pregunta 6.** Prohíbe
   transferir/compartir **app secret keys**, con una única excepción: el *Service Provider* que te
   ayuda a desarrollar/operar tu App. En la variante C el `app secret` es del tenant y lo
   custodiaría Qualify → sólo es lícito si Qualify es el **Service Provider** del tenant, lo que
   exige el **acuerdo escrito de §5.a.i** (*"You will not use a Service Provider… unless that
   Service Provider first accepts in writing…"*). Es decir: **la variante C es representable
   contractualmente, pero requiere papel firmado por tenant, no sólo una fila en una tabla.**

## 4. HALLAZGO 3 — Pregunta 5 (convivencia de niveles de acceso): SÍ, y es por permiso

**Fuente [P]:** [Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels),
accedida **2026-07-29**.

- *"Los administradores de apps pueden cambiar los niveles de acceso de **permisos y funciones
  individuales**"* → **el nivel de acceso es propiedad del permiso, no de la app.** Una misma app
  puede tener un permiso en Standard y otro en Advanced.
- *"el acceso avanzado se debe **aprobar individualmente para cada permiso y función**"* → App
  Review es **por permiso**, no por app.
- Advanced Access **no excluye** a los titulares de rol: amplía el conjunto de usuarios a los que
  se puede pedir el permiso (*"se puede solicitar con acceso avanzado a cualquier usuario de la
  app"*), no lo sustituye.
- **No aparece ningún tope numérico de usuarios de prueba** → confirma por segunda vez, y en vivo,
  la corrección de §3.1 de `integracion-cuentas-conectadas-meta.md` (el "tope de 25" no existe).

**Ruling derivado:** *"cruzar la línea"* Development/Advanced **no es un interruptor global**. La
frontera de §424 de `integracion-cuentas-conectadas-meta.md` sigue siendo una frontera real, pero
es **por permiso y por usuario**, no por app. Consecuencia de producto: se puede llevar
`instagram_manage_messages` a Advanced para el cliente uno mientras `instagram_content_publishing`
sigue en Standard, o al revés. **Esto es una palanca de secuenciación que los docs no registran.**

⚠ **Matiz que corta en la otra dirección y no hay que perder:** el *App Mode* (Development vs Live)
**sí** es global a la app. Un permiso en Advanced Access no sirve de nada si la app sigue en
Development Mode (*"Apps in Development mode can only request permissions from role users"*,
§3.1 cita 2). Luego la convivencia por permiso es real **dentro** de una app en Live Mode; no
permite tener "media app en development". Y `facebook-login-for-business.md:398` añade un gate
adicional a la vía elegida por ADR 25: *"**advanced access to the `public_profile` permission is
required** for Facebook Login for Business apps before they go live… to ensure that the app can
support authorization from users who do not have an app role"* → **la propia bifurcación de ADR 25
obliga a pasar por App Review de `public_profile` en cuanto haya un usuario sin rol.**

## 5. HALLAZGO 4 — EL DECISIVO. Existe una VARIANTE D que el brief no listaba, es el patrón sancionado por Meta, y refuta la variante C con cita literal

**Fuente [P] en disco:**
`reference/meta-instagram-platform/documentation/facebook-login/facebook-login-for-business.md`,
cosechada 2026-07-24. Sección *Business Integration System User access tokens* (BISU), líneas
~120-200.

**Variante D = Facebook Login for Business + Business Integration System User access tokens.**
Una sola app de Qualify, bajo el portfolio de Qualify; cada cliente **delega explícitamente**
activos concretos a esa app desde SU propio Business Portfolio; el token resultante está asociado
al **portfolio del cliente**, no a una persona.

### 5.1 La cita que refuta la variante C (line ~139)

> *"Your app must be associated with a business portfolio, which you have full control. **This
> needs to be separate from the business portfolio owned by your business client.**"*

**Meta EXIGE que la app viva bajo el portfolio del PROVEEDOR y que ese portfolio sea DISTINTO del
portfolio del cliente.** La variante C —cada negocio registra su propia app bajo su propio
Business Portfolio y el proveedor la administra— es exactamente la configuración que esta frase
excluye para el flujo diseñado para servir a clientes. No es que C sea "circunvención": es que
**C es la configuración contraria a la que Meta especifica**, y al adoptarla se pierde el tipo de
token diseñado para el caso (BISU), quedando sólo el *user access token* de vida corta atado a una
persona física — que es precisamente el defecto de la variante B.

### 5.2 Por qué D resuelve el problema de custodia que hunde a B

| Propiedad (cita literal, tabla *Comparison*, línea ~153-158) | BISU token (variante D) | User access token (variante B) |
|---|---|---|
| Designación de acceso | *"Access is **explicitly delegated** at the time of authorization. Your app can only access the assets that were designated by your business client… **Tech Providers only.**"* | *"Access is **inherited** from your app user's current account access"* |
| Asociación de cuenta | *"Associated with your **business client's business portfolio** rather than a specific user. Any admin in your business client's admin group can grant your app a system user access token."* | *"Associated with your app user's **personal Facebook account**."* |
| Expiración | *"Defaults to **never expire**"* | *"A **short-lived** token"* |
| Grant OAuth | *"**Authorization Code** grant only"* | Implicit por defecto |
| Revocación por el cliente | Business Settings → Integrations → **Connected apps** → remove | Settings & privacy → Business Integrations → remove |

**Esto disuelve la objeción del lead a la variante B en el sentido correcto: la objeción es válida
—B ata todas las credenciales a una persona física— y D es el mecanismo que Meta provee para no
tener que hacerlo.** Bajo D, `oauth_credentials` **sí** mapea a tenants, porque el token *es* del
portfolio del cliente. El aislamiento de ADR 24 deja de ser decorativo: es estructural en Meta
**y** en Postgres.

### 5.3 `client_business_id` — el discriminante de tenant que Meta ya emite

> *"the token includes a **client business ID**. This ID represents the client business and is used
> by your app to make API calls."*
> `GET /me?fields=client_business_id&access_token=<BISU_TOKEN>`

**Hallazgo con consecuencia de esquema:** Meta emite un identificador estable del negocio-cliente,
recuperable del propio token. Es el candidato natural para la columna que ancla un
`social_connections` a un tenant **verificable contra Meta**, en vez de sólo contra nuestra propia
fila. Hoy no existe en el DDL de `0002_connections.py`.

### 5.4 Tokens granulares — Meta implementa el aislamiento por cliente, y lo motiva igual que nosotros

> *"you can use **multiple granular** business integration system user access tokens per client
> business… Granular access tokens are still **specific to a client business portfolio. They are
> not shareable and accessible across different client businesses.** … To isolate potential
> security incidents in the event of a compromised token, **only that specific client business will
> be impacted, instead of impacting all business portfolios across all client businesses.**"*

Endpoint: `POST /<CLIENT_BUSINESS_ID>/system_user_access_tokens`, requiere permiso
`business_management` + `appsecret_proof`. Parámetros: `asset`, `scope`, `fetch_only`,
`set_token_expires_in_60_days`.

**El razonamiento de Meta es palabra por palabra el de ADR 24/R2/R3.** Refuerzo externo del diseño
ya construido; no obliga a cambiar nada de C-03.

### 5.5 Y AQUÍ CIERRA EL HECHO NUEVO DEL FUNDADOR (§0) — la cita que lo convierte en ventaja operativa

> *"To test the business integration system user access token flow, **the tester must have a role on
> the app and full control of the client business.**"*

El fundador cumple **exactamente** esa doble condición respecto del cliente uno: es admin de la app
de Qualify **y** —hecho nuevo de 2026-07-29— administra el stack y los activos de la inmobiliaria.

**Consecuencia, y es la más accionable de la sesión: el flujo multi-cliente completo de la variante
D es TESTEABLE de punta a punta, bajo Standard Access, SIN App Review, usando al cliente uno como
el "client business" del ejemplo.** El reloj administrativo de 2-4 meses deja de bloquear el
*desarrollo* del camino multi-tenant; sólo bloquea el **cliente dos** (el primero cuyos activos el
fundador NO administre). La frontera de §424 no se mueve, pero **el lado barato de la frontera es
mucho más ancho de lo que los docs registran**: incluye construir y probar el camino Tech Provider
entero.

### 5.6 Dependencia con ADR 25 que no estaba registrada

BISU **sólo existe bajo Facebook Login for Business** (es una sección de ese documento) y exige
*"Your Meta app must be a **business type app**"* (línea 11). Luego **ADR 25 (Facebook Login for
Business) es precondición del camino Tech Provider**, no sólo del acceso a `mentioned_media`. ADR 25
se firmó por las superficies earned; resulta que compró también el único modelo de token viable para
multi-tenant. **Registrar como refuerzo retroactivo de ADR 25.**

Restricción adicional a registrar: *"Your app can only request logins from **web surfaces**"* — sin
consecuencia para Qualify (la UI es Reflex, web), pero cierra cualquier futuro flujo nativo móvil.

## 6. HALLAZGO 5 — La cadena de exención de §3.1 está INCOMPLETA en disco: hay una SEGUNDA vía, más ancha, y cambia el coste de la variante A

`docs/integracion-cuentas-conectadas-meta.md` §3.1 cita la exención como *"app users who have a
role on the app itself"*. **La redacción real de Meta es una DISYUNCIÓN con un segundo término que
no está registrado en ningún doc del repo.** Dos ficheros del corpus en disco (cosechado
2026-07-24, luego disponible desde entonces y no leído):

> `documentation/resp-plat-initiatives/individual-processes/app-review.md:7` — *"If your app will be
> used by anyone without a **Role on the app** **or a role in a Business that has claimed the app**,
> it must first undergo App Review. If your app will only be used by app users who have a role on
> the app itself, App Review is not required."*

> `documentation/instagram-platform/overview.md:107` — *"You must complete Business Verification if
> your app requires Advanced Access; if your app will be used by app users who do not have a **Role
> on the app itself, or a Role in a Business that has claimed the app**."*

**Segundo término: "un rol en un Business que ha reclamado la app".** No es lo mismo que un rol en
la app.

**Consecuencia sobre la variante A, y corrige la lectura del lead:** el brief descarta A porque
*"no escala, es operación manual por persona en la consola de desarrollador"*. Ese coste es real
para el término 1 (app roles: admin/developer/tester, gestionados en App Dashboard → App Roles).
**Pero el término 2 no pasa por la consola de desarrollador**: si el Business Portfolio del fundador
**reclama** la app de Qualify, la exención alcanza a cualquiera con **rol en ese Business
Portfolio** — que se gestiona en Business Settings → People, una superficie de administración de
negocio normal.

**Ruling sobre A: la lectura del lead se CORRIGE en el mecanismo y se CONFIRMA en la conclusión.**
- Se corrige: A no exige "una fila por persona en la consola de desarrollador". Vía término 2 es
  gestión de personas en Business Manager, notablemente menos fricción.
- Se confirma: **sigue sin escalar a self-serve y sigue siendo inaceptable para GA**, por una razón
  distinta y peor que la del lead — **dar a los agentes de un cliente un rol en el Business
  Portfolio de Qualify les da acceso a los activos de ese portfolio**, no sólo a la app. Es una
  concesión de permisos hacia dentro de nuestra propia casa a cambio de saltarse un trámite. Como
  piloto con design partner es **viable y ahora más barato de lo que creíamos**; como modelo de GA
  es una fuga de perímetro, no sólo un problema de escala.

⚠ **Cabo suelto declarado como tal:** *"a Business that has **claimed** the app"* — el verbo
*claim* es un acto concreto en Business Manager (reclamar la app como activo del portfolio) y **no
he verificado sus precondiciones** (¿exige Business Verification para reclamar? ¿exige que la app
sea business-type?). Si reclamar la app exigiese Business Verification, el término 2 dejaría de ser
un atajo y colapsaría sobre el trámite que pretende evitar. **Es la verificación más barata y de
mayor valor que queda abierta** (V-TP-1 en §10).

## 7. HALLAZGO 6 — Una contradicción de Meta consigo misma que ATACA el hallazgo 3 (convivencia). Se declara como ambigüedad, NO se resuelve por inferencia

`docs/graph-api/changelog/version3.0.md:127-128`, en disco:

> *"**Development Mode** — Apps in development mode are now rate-limited to 200 calls per hour, per
> page-app pair, and can only access Users who have a role on the app (admin, developer, or tester)."*
>
> *"**Public Mode** — Apps in public mode **no longer allow their admins, developers, or testers to
> access permissions or features that normally require app review**. This affects all apps built
> after May 1st, 2018…"*

La segunda frase, leída literalmente, dice que **al pasar a Live/Public Mode los titulares de rol
DEJAN de poder usar permisos no aprobados** — lo contrario del modelo de convivencia del §4.

**Lectura reconciliadora (hipótesis [S], NO afirmada):** el changelog es de 2018 y describe el
modelo binario *"requiere App Review / no lo requiere"* anterior a la introducción de los niveles de
acceso (~2021). Bajo el modelo actual, un permiso en **Standard Access está auto-aprobado**, luego
no es un permiso *"that normally requires app review"* y la frase no le aplica. Si esa lectura es
correcta, la convivencia del §4 se sostiene.

**No la resuelvo por inferencia, por instrucción y porque el riesgo es asimétrico.** Si la frase de
2018 sigue vigente, entonces el día que Qualify pase la app a Live Mode para atender al cliente uno,
**todo permiso que no haya pasado App Review deja de funcionar incluso para el fundador** — es decir,
el camino "cliente cero sigue operando mientras el trámite del cliente uno corre" se rompe, y con él
la secuenciación favorable de §3.5/ADR 21.

**Qué lo resolvería (V-TP-2 en §10):** es empíricamente testeable y barato — pasar una app de prueba
a Live Mode con un permiso en Standard y comprobar si el admin sigue pudiendo ejercerlo. **Es la
misma clase de prueba empírica que §7.6 ya reclama para "Standard Access no está probado como
funcionalmente completo".** Se recomienda fusionarlas en una sola sesión de verificación.

## 8. Pregunta 4 — partner/agency access vs Advanced Access: HIPÓTESIS DEL LEAD CONFIRMADA (son ortogonales)

**Confirmada sobre fuente primaria del lado developer.** La cadena:

1. El nivel de acceso gobierna **a qué usuarios** puede la app pedir permisos:
   *"Permissions with Standard Access can only be requested from app users who have a **role** on
   the requesting app"* (Access Levels; corroborado en el corpus por
   `business-messaging/instagram-messaging/overview.md:122` — *"Apps with Standard Access can only
   interact with people who have a role on the app"*, y `features/send-message.md:31`,
   `features/private-replies.md:32`).
2. Las exenciones se definen **exclusivamente** sobre *role on the app* / *role in a Business that
   has claimed the app* (§6). **Ninguna fuente menciona la concesión de activos como término de la
   exención.**
3. La delegación de activos en la vía FLB ocurre **en el momento de la autorización OAuth**, no en
   Business Manager: *"Access is explicitly delegated at the time of authorization. Your app can
   only access the assets that were designated by your business client when they completed the
   Facebook Login for Business flow"* (§5.2). Es decir, el activo se designa **dentro del grant**,
   y el grant sigue sujeto al nivel de acceso.

**Ruling: ortogonales, como el lead planteaba.** El *asset access* gobierna **sobre qué activos**
operas; el *access level* gobierna **a qué usuarios** puedes pedir permisos. **Conceder activos no
convierte a nadie en titular de rol.** Corolario operativo: que un cliente te dé acceso de partner
a su Página/cuenta IG **no evita** el App Review, y un producto que asuma lo contrario descubrirá el
error en el primer cliente sin rol.

**Limitación de evidencia, declarada:** el lado **Business Manager** de la afirmación (qué recibe
exactamente un *partner* al que se le conceden activos) **no lo he podido citar en primaria** — las
páginas del Business Help Center (`facebook.com/business/help/1717412048538897`,
`/708679622611131`) se sirven renderizadas por JS y devuelven sólo el encabezado al fetch. La
conclusión no depende de ellas (se sostiene sobre las exenciones del lado developer, que son las
que definen el gate), pero **la afirmación "el partner access no toca apps" queda [S], no [P]**.

## 9. Pregunta 1 — ¿existe una figura formal de Tech Provider? SÍ, y es de las dos cosas

**Respuesta: Tech Provider es simultáneamente (a) una figura de las Platform Terms y (b) una
designación operativa que gatea capacidades en la App Dashboard.** No es sólo vocabulario de
marketing.

| Plano | Evidencia | Qué implica |
|---|---|---|
| **Platform Terms** | §5.b.ii completa, dedicada al *Technology Provider* [P] | Obligaciones contractuales: procesar sólo por cuenta y a instancia del Client (§5.b.ii.1), independencia de datos entre Clients (§5.b.ii), cortar a un Client si Meta lo pide (§5.b.ii.6) |
| **App Dashboard / producto** | *"Tech Providers only"* como restricción del tipo de token BISU (`facebook-login-for-business.md:153`) [P]; *"Facebook Login for Business is the preferred… solution **for tech providers**"* (`:5`) [P] | La figura **habilita** un mecanismo (BISU) que de otro modo no existe |
| **Data Access Renewal** | Definición operativa + *"Because this app allows people or businesses (clients) to access and use Platform Data, it means that you are a Tech Provider"* (`data-protection-section.md:301`) [P] | Meta te **clasifica** como Tech Provider a partir de tus propias respuestas del cuestionario; no es autoadscripción |
| **App Review** | Fila *"I am a Tech Provider and my app serves multiple businesses"* → Advanced Access **Required** (`app-review.md:15-16`) [P] | Es un escenario de desarrollo reconocido con consecuencia administrativa |

**Distinción frente a Agency / Solution Provider:** la única fuente primaria que contrasta las
figuras explícitamente que he encontrado está en la documentación de **WhatsApp Solution Partners**
([developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/overview),
vía búsqueda 2026-07-29): la diferencia es de **facturación y línea de crédito** — *si no necesitas
línea de crédito ni facturar a tus clientes el uso de la API directamente, conviene ser Tech
Provider en vez de Solution Partner*. **Marcado [S]**: la distinción viene del corpus de WhatsApp y
no he verificado que se generalice a Instagram/Graph. *Agency* es una figura de **Business Manager**
(añadir un partner y compartirle activos), no de las Platform Terms, y por tanto **no es una
alternativa a Tech Provider — vive en el otro eje del §8.**

**Lo que Qualify es, sin ambigüedad:** en el momento en que un negocio que no es el fundador usa
Qualify para gestionar sus activos de Meta, Qualify **es un Tech Provider** por la definición
literal (*"a single integration on behalf of an individual client"*). No hay configuración de
esquema que lo evite. La pregunta útil no es *cómo evitarlo* sino *cómo cumplirlo al menor coste*, y
la respuesta de Meta a esa pregunta es la variante D.

## 10. VEREDICTOS

### 10.1 Variante B (el fundador como único app user, proxy de N clientes) — **RECHAZADA**

**La lectura del lead es correcta y se confirma, con dos cláusulas concretas.**

Sobre la LETRA de las tres citas de §3.1, B parece pasar: el único app user tiene rol. **Pero falla
en las Platform Terms, no en las citas de access level** — y ése es el punto que evita que la
pregunta vuelva cada tres sesiones:

1. **§5.b.ii.1 exige que el proceso de Platform Data sea *"on behalf of your Client and at the
   Client's request, **in whose representation you access them**"*.** Bajo B, Meta ve un único
   individuo accediendo a activos como si fueran suyos. **No hay ningún Client representado ante
   Meta.** La representación no es opcional en el texto: es el objeto de la cláusula. B no
   "aprovecha una laguna" — omite el requisito.
2. **§5.b.ii exige que *"Platform Data you retain on behalf of one Client remains independent of that
   of other Clients"*.** Bajo B, los tokens de todos los clientes son del mismo usuario de Meta y
   comparten el mismo grant. La independencia se puede simular en nuestra base de datos, **pero no
   existe en el plano de Meta**, que es donde la cláusula la exige. Ésta es exactamente la
   observación del lead de que *"el aislamiento estructural de ADR 24 se vuelve decorativo"* —
   elevada de intuición a incumplimiento contractual nominado.
3. **Consecuencia técnica que además la hace frágil**, y no depende del juicio legal: el token de B
   es un *user access token*, *"short-lived"* y *"associated with your app user's personal Facebook
   account"* (§5.2). **Todo el negocio de N clientes cuelga de una cuenta personal de Facebook.**
   Si esa cuenta se bloquea, se pierde el 2FA, o el fundador simplemente deja de ser admin de un
   activo, caen N clientes a la vez. Es un punto único de fallo con forma de persona.

**Veredicto: B se rechaza, y por la razón menos discutible de las tres — la (3).** Aunque un abogado
sostuviese que (1) y (2) son ambiguas, (3) es un defecto de ingeniería que no requiere interpretar
nada. **No es necesario ganar la discusión legal para descartar B.**

**Lo que sí es ambiguo, dicho como tal:** ¿es B *sancionable*, o simplemente *no soportada*? No he
encontrado una cláusula que diga *"no actuarás por cuenta de terceros usando tu propio grant"*. Lo
que hay es un régimen positivo (§5.b) que describe cómo se hace, y B no lo satisface. **Eso lo hace
incumplimiento por omisión, no por prohibición expresa.** Lo que lo resolvería: nada de
documentación — sólo una consulta a Meta o a asesoría legal. **Y no hace falta resolverlo, porque B
se cae por (3) de todos modos.** Registrado para que nadie lo re-abra creyendo que quedó pendiente.

### 10.2 Variante C (app por tenant, BYO app administrada por el proveedor) — **RECHAZADA, y por una cita, no por una intuición**

**No es circunvención. Es la configuración que Meta excluye explícitamente:** *"Your app must be
associated with a business portfolio, which you have full control. **This needs to be separate from
the business portfolio owned by your business client.**"* (§5.1).

**Y la premisa que hacía atractiva a C es falsa:** el brief razona que *"la cadena de exención
aplicaría nativamente: app usada solo por titulares de rol, operando sobre activos que ese mismo
negocio posee"*. La definición de Tech Provider **no tiene umbral de N** — *"a **single**
integration on behalf of an **individual** client"* (§2). Registrar la app bajo el portfolio del
cliente no cambia quién opera la integración. **C no disuelve el reloj de 2-4 meses; sólo lo
multiplica por N.**

**Contrapartidas de C, completas, como el brief exige (siguen siendo reales aunque C se rechace —
son el coste que se evita):**

| Coste | Detalle |
|---|---|
| N configuraciones derivando | N filas de `platform_apps` con `api_version` y `config_version` independientes. La deriva de versión de API deja de ser una migración y pasa a ser N migraciones coordinadas con N clientes |
| N secretos custodiados sin poseerlos | Lícito **sólo** si Qualify es Service Provider del tenant, lo que exige **acuerdo escrito por tenant** (§5.a.i + §6.a.iv). Papel firmado, no una fila en una tabla |
| **Radio de daño de un evento de credencial cambia de escala** | Éste es el coste arquitectónico que el brief pide y que no es obvio: hoy la FSM de C-03 es **por conexión**. Si el tenant rota o revoca el secreto de SU app, **caen de golpe TODAS las conexiones de ese tenant**, y nos enteramos por fallo de API, no por notificación. Haría falta una **FSM padre a nivel de app** sobre la FSM de conexión — una máquina de estados nueva, no un campo nuevo |
| Fricción de alta | Cada cliente crea y verifica una app de Meta. **Incompatible con self-serve**, y el paso más difícil se lo pedimos al cliente justo antes de que vea valor |
| Responsabilidad ante Meta | **No se transfiere.** §5.b.ii.6 (*"You will promptly terminate a Client's use… if we request"*) y §1.d ponen el deber sobre quien opera la integración. C fragmenta el riesgo sin externalizarlo |

**Lo que NO se ve afectado por nada de esto, como el brief pide declarar explícitamente:** la
economía de scrape compartido de **ADR 18** vive entera en el plano **earned** (envelope
brand-agnóstico, keyed por `(platform, url)`, N marcas comparten un scrape). Las variantes A/B/C/D
son todas del plano **owned/first-party**. **Ninguna toca ADR 18**, y `brand_id` sigue sin
fusionarse con `tenant_id` (ADR 24(b)).

### 10.3 Recomendación: **variante D**, y el cliente uno es su banco de pruebas

**Una sola app de Qualify bajo el Business Portfolio del fundador, Facebook Login for Business
(ADR 25), Business Integration System User access tokens, un `client_business_id` por tenant.**

Secuenciación derivada del §5.5, y es la aportación práctica:

| Etapa | Quién | Nivel de acceso | Trámite |
|---|---|---|---|
| 0 | Fundador, cuentas propias (cliente cero) | Standard | Ninguno |
| **0-bis (NUEVO)** | **Fundador probando el flujo BISU completo contra el negocio del cliente uno, que él administra** | **Standard** | **Ninguno** — *"the tester must have a role on the app and full control of the client business"* |
| 1 | Cliente uno en producción | Advanced (por permiso) | App Review + Business Verification + `public_profile` Advanced |
| 2 | Cliente dos (activos que el fundador NO administra) | Advanced | Igual que 1, ya pagado |

**El hecho nuevo del fundador (§0) crea la etapa 0-bis, que antes no existía.** El camino
multi-tenant entero —delegación de activos, `client_business_id`, tokens granulares, revocación
desde Business Settings del cliente— se construye y se prueba **sin trámite**. Lo que el reloj
administrativo bloquea es sólo el paso a **producción** con el cliente uno.

### 10.4 Pregunta 6 — ¿debe cambiar R1? **NO. R1 se CONFIRMA, y se refuerza.**

`platform_apps` sigue **GLOBAL, sin `tenant_id`, sin RLS**. Motivos, en orden de fuerza:

1. **La variante D lo exige positivamente.** Meta requiere que la app viva bajo un portfolio del
   proveedor *separado del del cliente* (§5.1). Una `platform_apps` tenant-scoped modelaría
   precisamente la configuración que Meta excluye. R1 no es "una simplificación que aguanta": es
   **la forma correcta**, y ahora hay cita para decirlo.
2. **La justificación original de R1 sobrevive intacta y mejorada.** R1 dice *"el secreto es de
   Qualify, no del tenant; todo tenant conecta a través de la misma fila de app"*. Bajo D eso es
   exactamente cierto, y el discriminante de tenant no es la app: es el **`client_business_id`** que
   Meta emite en el propio token (§5.3).
3. **La fontanería multi-app que ya existe sigue teniendo objeto, sin tenant-scoping.** N filas de
   `platform_apps` siguen siendo necesarias por **plataforma** (Meta, y una futura de TikTok) y por
   **postura de acceso** — no por tenant. `platform_app_id` como provenance sigue siendo correcto.

**Cambio de esquema que SÍ recomiendo, y es pequeño:**

- `social_connections` gana **`client_business_id text NULL`** — el ID del negocio-cliente que Meta
  emite en el token BISU, recuperable con `GET /me?fields=client_business_id`. Valor: es la única
  forma de **verificar contra Meta** a qué negocio pertenece una conexión, en vez de confiar sólo en
  nuestra propia fila. Nullable porque el cliente cero (user access token) no lo tiene.
- **Nada más.** Verificado contra el DDL aplicado: `oauth_credentials.expires_at` **ya es
  nullable** → un token BISU *"defaults to never expire"* es representable hoy sin migración, y
  `token_type` es `text` libre → admite `'business_integration_system_user'`. **La custodia de C-03
  soporta la variante D sin tocar una línea.** Esto no era obvio y merece registrarse.

### 10.5 Pregunta 7 — el argumento de timing: **ES UNA ANALOGÍA FORZADA. Se desmonta.**

El brief pide evaluarlo explícitamente. Lo hago, y la respuesta es que **no aplica**.

ADR 24 se firmó sobre un argumento de ventana que era decisivo por una razón **específica y no
transferible**: *"el identificador termina en un prefijo de `ORDER BY` de ClickHouse, que es
inmutable"*. Ahí no había vuelta atrás a ningún precio.

Nada de eso vale aquí:

| Propiedad | ADR 24 (`tenant_id`) | Esta decisión (`platform_apps`) |
|---|---|---|
| Plano afectado | **ClickHouse** — `ORDER BY` inmutable | **Postgres** — `ALTER TABLE ADD COLUMN` + `CREATE POLICY`, online y barato |
| Coste de revertir | Recrear tablas y re-ingerir | Una revisión de Alembic nueva |
| ¿Entra en un `ORDER BY`? | **Sí, es el argumento entero** | **No.** Verificado: ni `platform_app_id` ni la identidad de app aparecen en el esquema analítico; la clave de raw de primera parte (R5) es `t/{tenant_id}/fp/{platform}/{connection_id}/{object_id}` |

Y hay una inversión que conviene decir en voz alta: **ADR 27 R8a (editar migraciones en sitio) es
un argumento CONTRA la urgencia, no a favor.** Si las migraciones se editan en sitio porque nada
está desplegado, entonces **se podrán seguir editando en sitio la semana que viene**. La ventana no
se está cerrando; R8a es precisamente lo que la mantiene abierta.

**Ruling: el argumento de timing se rechaza.** Y conviene rechazarlo con claridad porque el patrón
"esto es la última ventana barata" es persuasivo y **se degrada si se usa donde no aplica**: ADR 24
lo usó bien, y reutilizarlo aquí lo gastaría. Lo caro-más-tarde en esta decisión **no es el
esquema** — es el **acuerdo escrito de Service Provider** (§5.a.i) y el reloj de App Review, y
ninguno de los dos se compra escribiendo una columna hoy.

### 10.6 Gate explícito (por instrucción del lead)

**El ruling de §10.4 sobre R1 queda CONDICIONADO** a la evidencia de `gtm-specialist` sobre qué
patrón es estándar en la categoría: *single reviewed app* (multi-tenant) vs *BYO-app-per-customer*.

- Si gtm halla que los competidores operan con **una app revisada** → §10.4 se confirma sin cambios
  y la variante D es también el patrón de mercado.
- Si gtm halla **BYO-app-per-customer como patrón real y extendido** en la categoría → hay un
  conflicto entre la práctica del mercado y la cita de §5.1, y **debe resolverse antes de firmar**:
  o los competidores usan un mecanismo que no he encontrado, o operan en incumplimiento tolerado.
  Cualquiera de las dos cosas es información que cambia la decisión.

Marcado como gated en la ADR, igual que ADR 19 se gateó sobre hallazgos de gtm.

### 10.7 Verificaciones abiertas

| # | Cuestión | Coste | Bloquea |
|---|---|---|---|
| **V-TP-1** | Precondiciones de *claim* de una app por un Business Portfolio (¿exige Business Verification?). Si las exige, el segundo término de la exención (§6) colapsa sobre el trámite que evita | Bajo (consola) | El coste real de la variante A como piloto |
| **V-TP-2** | ¿Sobrevive un permiso en Standard Access al paso a **Live Mode** para un titular de rol? (§7). **Fusionar con la prueba empírica que §7.6 ya reclama** | Bajo (empírico, cuenta real) | La secuenciación de §3.5 / ADR 21: si no sobrevive, cliente cero deja de operar el día que arranque el trámite del cliente uno |
| **V-TP-3** | Verbatim de las definiciones de glosario de las Platform Terms (*Technology Provider*, *Client*, *Service Provider*) — el fetch las parafraseó | Bajo | Citarlas en un contrato o en el acuerdo de Service Provider |
| **V-TP-4** | Lado Business Manager de la pregunta 4 (§8): qué recibe exactamente un *partner* con activos concedidos. Páginas del Business Help Center no fetchables | Medio | Nada — el ruling no depende de ello; sólo eleva [S] → [P] |
| **V-TP-5** | ¿Exige BISU que el portfolio del proveedor esté **verificado**? Es distinto de "la app requiere Business Verification" y no lo he verificado | Bajo | El calendario de la etapa 0-bis de §10.3 |

## 11. EL GATE SE RESUELVE, y con él llega el hallazgo más grave de la sesión

`docs/research-modelo-acceso-tech-provider.md` (`gtm-specialist`, 2026-07-29) aterrizó en paralelo.
Tres cosas.

### 11.1 El gate de §10.6 se resuelve EN DIRECCIÓN CONFIRMATORIA

Veredicto de gtm: *"el Patrón 1 (app única revisada) es el único que se observa en SaaS comercial
(5/5 verificados); el Patrón 2 (BYO app) solo aparece en self-hosted/open-source, y **no elimina el
App Review — lo reubica en el cliente**"*. Casos: ManyChat, Zernio, Ayrshare → Patrón 1; Mixpost,
Postiz (self-hosted) → Patrón 2.

**El gate queda satisfecho: la práctica de mercado coincide con la cita de §5.1.** No hay conflicto
que resolver antes de firmar. ADR 29 pasa de *gated* a *listo para firma*. Y la frase de gtm *"no
elimina el App Review — lo reubica en el cliente"* es la misma conclusión que §2 alcanzó por la vía
de la definición de Tech Provider, llegada por un camino independiente.

**Corrección menor a la tabla de gtm (§1), que ellos mismos marcan como no-interpretada:** su fila
*"¿App Review + Business Verification?"* dice, para el Patrón 2, *"No — la app la usan solo
titulares de un rol en ella"*. Eso es la premisa que §2 refuta: **la definición de Tech Provider no
tiene umbral de N**. Su propio veredicto de una línea ya lo corrige; la fila de la tabla es la
versión sin interpretar. No hay conflicto de fondo.

### 11.2 ⚠ HALLAZGO GRAVE — el §3.1 de `integracion-cuentas-conectadas-meta.md` afirma algo que ahora está CONTESTADO por [P] + campo independiente, y es la premisa de ADR 21

§3.1 afirma, y es mío: *"en la doc de Content Publishing **no existe ningún mecanismo por el que el
nivel de acceso o el estado de revisión degraden la visibilidad del post**. No es que no lo hayamos
encontrado: es que Meta no tiene esa palanca. **Un reel publicado por una app en Development Mode es
un reel público normal.**"*

**Las dos fuentes que gtm aporta contradicen la última frase:**

> [P] Meta, [App Modes](https://developers.facebook.com/docs/development/build-and-test/app-modes),
> accedido 2026-07-29: *"Any data generated while an app is in Development mode, such as test posts,
> **can only be seen by role users**."* / *"data generated while in Development mode such as test
> posts **will become visible to all app users once you switch**."*

> [P] campo independiente, [docs.postiz.com/providers/facebook](https://docs.postiz.com/providers/facebook),
> accedido 2026-07-29, paso 8: *"Change the App Mode from 'Development' to 'Live'. **If you do not do
> this then posts made via the API will display for yourself but will not be visible for other
> users**."* / *"**posts with media are only visible to app developers/testers** — everyone else sees
> the post without the image."*

**gtm tiene razón en el diagnóstico del eje y es una distinción excelente: App Mode ≠ nivel de
acceso.** Mi §1.1-bis hablaba del eje *nivel de acceso* y sobre ese eje sigue en pie. **Pero mi §3.1
dijo literalmente "Development Mode", y sobre ese eje la afirmación no se sostiene.** Es mi error, y
es el segundo de la misma familia: concluir *"Meta no tiene esa palanca"* a partir de no haberla
encontrado **en la doc de Content Publishing**, cuando vivía en la doc de App Modes.

**Consecuencia, y es de ruta crítica, no cosmética:**

1. **Para que cliente cero publique un reel público real, la app tiene que estar en LIVE MODE.** El
   camino "Development Mode y no hay trámite" **deja de ser funcionalmente suficiente para
   publicar**. Es exactamente el límite que §7.6 declaró de forma inespecífica (*"el acceso estándar
   no está probado como funcionalmente completo"*) — ahora tiene **mecanismo concreto y nombre**: no
   es el nivel de acceso, es el App Mode, y degrada **la media**, que es justo lo que la Parte 4-A
   publica.
2. **Y encadena con la ambigüedad de §7 convirtiéndola en la pregunta que decide ADR 21.** Si hay que
   pasar a Live Mode para publicar, entonces la frase de `version3.0.md:128` (*"Apps in public mode
   no longer allow their admins, developers, or testers to access permissions or features that
   normally require app review"*) deja de ser un cabo suelto histórico y pasa a estar **en la ruta
   crítica**: no se puede evitar Live Mode, luego hay que saber qué sobrevive al pasar.
3. **Se convierte en pregunta de trámite:** ¿pasar a Live Mode exige App Review y/o Business
   Verification, o es un toggle self-serve? gtm lo deja abierto (su pendiente #1); Postiz dice *"for
   public applications, you will need to verify your business"* sin precisar. **Si pasar a Live Mode
   exigiera Business Verification, entonces el reloj administrativo SÍ bloquea a cliente cero, y el
   ruling central de §3.1/ADR 21 se cae.** Es la pregunta más valiosa que quedaba abierta en todo el
   expediente Meta.

**Lo digo con la calibración correcta: la afirmación no está refutada, está CONTESTADA — y la carga
de la prueba se ha invertido.** Ya no se puede apoyar ADR 21 en ella sin la prueba empírica. Dos
fuentes [P] independientes (una de Meta, una de campo sin relación con Qualify) apuntando al mismo
sitio es suficiente para retirarle el estatus de hecho establecido, aunque no para declarar lo
contrario probado. **V-TP-2 se promueve de "verificación barata" a BLOQUEANTE de ADR 21**, fusionada
con la prueba de §7.6 y con el pendiente #1 de gtm.

### 11.1-bis Corroboración de campo del rechazo de C — la mejor que hay, y viene de un producto BYO-app

Aportada por `gtm-accessmodel` por mensaje el 2026-07-29 (ya en su doc y en
`.claude/sprint-state-2026-07-29-modelo-acceso.md`; no depende del mensaje).

> [P] [Mixpost · Facebook App Review](https://docs.mixpost.app/services/social/facebook/app-review/),
> accedido 2026-07-29: *"This step is **mandatory for users providing Software as a Service (SaaS)**
> through Mixpost Enterprise. However, **if you are using Mixpost internally, this step is not
> required**."*

**Por qué es la corroboración más fuerte de todo el expediente para la razón (2) de ADR 29:** no es
Meta hablando de sí misma ni un competidor Patrón-1 defendiendo su modelo. Es **un producto que SÍ
implementa BYO app**, documentando a sus propios usuarios que el trámite es obligatorio en cuanto
sirven a un tercero. Sin incentivo alguno en decirlo.

**Lectura: el Patrón 2 se salta el App Review exactamente en el caso interno — el MISMO caso en que
el Patrón 1 también se lo salta.** Es decir, en el único caso en que BYO app parece ganar algo, no
gana nada, porque la exención de rol-en-la-app ya cubría ese caso. Servido un tercero, el trámite
reaparece en los dos patrones, y **lo único que BYO app cambia es quién lo paga.**

**Y eso añade una razón nueva contra la variante C que no estaba en §10.2: C no compra exención,
compra la *transferencia* de un trámite al cliente — lo peor de los dos mundos.** Mantiene el reloj
de 2-4 meses y además lo pone en la ruta crítica de **alta**, exigiéndoselo a alguien que todavía no
ha visto valor en el producto. La fricción de alta de la tabla de §10.2 deja de ser "un paso más" y
pasa a ser "un ciclo de App Review de Meta antes del primer valor entregado".

### 11.1-ter Tercera fuente independiente de la exención de rol-en-la-app

> [P] [Postiz · Instagram](https://docs.postiz.com/providers/instagram), accedido 2026-07-29: *"The
> advanced permissions on the Meta app must be approved (**or your account must be a developer/tester
> on the app**) … **until then, only roles you've added can publish**."*

Ya son **tres fuentes sin relación entre sí** (Meta, Mixpost, Postiz) sobre el mismo mecanismo. La
exención de §3.1 es **cómo opera la categoría**, no una lectura creativa nuestra. Nota de calibración
que conviene no perder: esto valida el **mecanismo de la exención**, y no rescata la frase retirada
en §11.2 — que era sobre **visibilidad de la media**, un eje distinto. Las dos cosas conviven: la
exención de rol es real *y* publicar en Development Mode no produce un post público normal.

### 11.2-bis TENSIÓN sobre la etapa 0-bis (2026-07-30) — lo que más celebré es lo más frágil

`gtm-accessmodel` aporta [P] [Get Started for Tech Providers](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers)
(2026-07-30): el status de Tech Provider **concede** Advanced Access a `whatsapp_business_messaging`
/ `whatsapp_business_management` y **exige** verificación de negocio + App Review, con
*"**Your business must be verified before you can start the app review process.**"*

**Refuerza B y C rechazadas:** el status es el **output** del trámite, no un sustituto. No existe
*"hazte Tech Provider para ahorrarte la revisión"*.

**Amenaza la etapa 0-bis de §10.3, que es mía.** Si *"Tech Providers only"* (la restricción de la
fila BISU, `facebook-login-for-business.md:153`) designa una titularidad que sólo se obtiene tras
App Review, entonces BISU no está disponible antes del trámite y **la etapa 0-bis no existe**.

**No lo resuelvo.** Las dos fuentes son [P] y **no se contradicen literalmente**: la de gtm es del
vertical **WhatsApp** (concede permisos `whatsapp_*`) y la mía es de **Facebook Login for Business**
(`:139`, que contempla explícitamente probar el flujo BISU siendo titular de rol con control total
del negocio cliente). Que el onboarding de WhatsApp exija revisión no prueba que el token BISU esté
gateado igual en Instagram/Graph, ni lo descarta.

**Lo que NO se mueve:** el ruling de ADR 29 es de **arquitectura** (D es el modelo correcto, R1
sigue global); la etapa 0-bis es de **calendario**. Si la lectura pesimista gana, ADR 29 sigue en
pie y lo que se pierde es la ventaja de secuenciación que el hecho nuevo del fundador parecía
regalar. **Lo registro al mismo volumen con que celebré la ventaja, porque fue lo más llamativo de
la entrega y su fragilidad debe viajar con ella.**

→ **V-TP-7**, cuarta pregunta del mismo banco de pruebas empírico de V-TP-2.

### 11.2-quater (2026-07-30) La contradicción A/B se resuelve, y destapa un fallo MÍO más grave que la tensión

Citas de `gtm-accessmodel`, **las cuatro verificadas contra el corpus en disco** (`app-review.md:11-16`,
`:35`, `:49`, `:85`; `data-protection-section.md:301`, `:382`).

**(1) La contradicción se resuelve con la distinción de dos regímenes que ya estaba en §8.6.**
Texto A (Data Protection Assessment) dice que **basta un cliente** para ser Tech Provider; Texto B
(App Review) sólo exige Advanced Access con *"multiple businesses"* y **no tiene fila para el cliente
único**. No se contradicen: A clasifica para **obligaciones**, B para el **trámite**. Se puede ser
Tech Provider a efectos contractuales sin disparar Advanced Access. **Interpretación, no hecho** —
pero apoyada en la estructura documental, no en conveniencia. Es la tercera vez que la distinción
trámite/obligaciones aparece por un camino independiente, lo que la refuerza.

**(2) Argumento estructural que empuja la etapa 0-bis a sobrevivir.** `app-review.md:85`: *"To
request Advanced Access to certain permissions, you need to make **at least 1 successful API
call**."* Si para *pedir* Advanced Access hay que haber llamado con éxito, el permiso es ejercitable
**antes** de la revisión. Aplicado a BISU: si exigiese status concedido tras App Review, no habría
forma de hacer la llamada que la propia revisión exige → circularidad que el proceso no tendría.
**Inferencia estructural, etiquetada como argumento fuerte y no como cierre. V-TP-7 sigue abierta.**

**(3) ⚠ Y EL FALLO ES MÍO.** gtm observa que el cliente uno **no encaja en ninguna** de las dos filas
de B. Al comprobar por qué, aparece el defecto: escribí que el fundador cumple *"full control of the
client business"* apoyándome en que **construye y administra el SaaS inmobiliario**. **Eso es el
stack de software, no el Business Portfolio de Meta.** Administrar el software de alguien no te hace
admin de sus activos de Meta. **Toda la ventaja de secuenciación que celebré descansa sobre esa
equivalencia no verificada** — y es la misma pregunta que §3.7 punto 2 dejó abierta para la tienda y
que nadie hizo para la inmobiliaria.

→ **V-TP-8: ¿es el fundador admin del Business Portfolio de Meta de la inmobiliaria, o sólo de su
software?** Una pregunta al fundador, cero investigación. **Va ANTES de V-TP-7 en el orden de
resolución: si V-TP-8 sale mal, V-TP-7 es irrelevante.** Si sale mal, el cliente uno no está en el
lado barato de la frontera y la etapa 0-bis se cae por una razón anterior y distinta.

**(4) Dos colaterales.** (i) La exención de B aparece en **las dos ramas de login** → la asimetría de
ADR 25 **no se manifiesta en el gate de revisión**, y no tenía por qué: su argumento fue de
**amplitud de permisos**, nunca de trámite. ADR 25 no se debilita, se precisa. (ii) Tres grafías del
scope de publicación entre dos fuentes buenas, verificadas: `instagram_content_publishing` (`:35`),
`instagram_business_content_publishing` (`:49`), `instagram_business_content_publish` (Zernio en
producción). Es el caso que CLAUDE.md manda resolver contra el endpoint de autorización.

### 11.2-ter Los programas de partner: confirmado que no mueven nada, y la premisa del fundador era inexacta

- [P] Meta Business Partner Program Policies: único requisito explícito, negocio verificado. **No
  menciona** App Review, niveles de acceso, permisos, cuotas ni tipos de token. Ausencia registrada
  como ausencia → confirma §8.5 punto 1.
- **El Partner Directory exige login** → la afirmación de partner de un proveedor **no es
  verificable de forma anónima por un comprador**. Pendiente cerrado como **NO VERIFICABLE**, no
  como no verificado. Límite del método, no hecho en ninguna dirección.
- **Corrección de premisa:** Zernio **casi no se declara partner** — cero ocurrencias en home, doc
  de API (25 KB) y página de WhatsApp; su única declaración está en su propio blog [S] y es de
  **ads** (*"approved Meta Marketing Partner"*). La lista amplia que circula viene de una **reseña
  de tercero**. Y el remate: **su acceso a publicación y mensajería de IG está probado por su doc
  técnica sin depender de ningún partnership.** Es la mejor evidencia posible de que el partnership
  no es la llave del acceso — si lo fuera, ahí se vería.

### 11.3 Zernio usa Instagram Login, no Facebook Login — y eso CONFIRMA ADR 25, no la amenaza

Dato de campo de gtm [P]: Zernio opera publicación **y** mensajería de IG vía **Instagram Login for
Business** — la rama que ADR 25 descartó. Coste que su propia doc registra: *"Ad permissions cannot
be granted through Instagram Login — those require a separate Facebook account connection for Meta
Ads functionality"*.

**Ruling: no amenaza ADR 25; la refuerza, y explica por qué.** Zernio es una **herramienta de
publicación**: no necesita `mentioned_media`, `mentioned_comment` ni hashtag search, que son las dos
únicas superficies *earned* del camino OAuth y la razón entera de ADR 25 (§7.1). Para un publicador,
Instagram Login es la elección correcta y más barata. **Qualify no es un publicador**, y elegir su
rama borraría la cascada multimodal del camino de cuentas conectadas. Que el competidor-publicador
elija la rama del publicador es **evidencia de que las ramas están bien caracterizadas**, no de que
hayamos elegido mal. Y su limitación de `ads_management` corrobora independientemente §7.1(c).
