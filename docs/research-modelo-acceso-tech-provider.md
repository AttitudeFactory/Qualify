# Modelo de acceso a cuentas de cliente: ¿app única revisada o BYO app?

**Estado:** completo. §1–§8 (patrones de acceso, 2026-07-29) + §9 (programas de partner, 2026-07-30). 11 pendientes abiertos: §8 y §9.8. Agente `gtm-specialist`.
**Veredicto en una línea:** el Patrón 1 (app única revisada) es el único que se observa en SaaS comercial (5/5 verificados); el Patrón 2 (BYO app) solo aparece en self-hosted/open-source, y **no elimina el App Review — lo reubica en el cliente** en cuanto hay un tercero servido.
**Veredicto de §9, en una línea:** ningún programa de partner de Meta o TikTok concede acceso técnico; el único que sí lo hace (Meta Tech Provider) **exige App Review + Business Verification como prerrequisitos literales**. El status de partner es **consecuencia de haber escalado, no atajo para escalar**.
**Pregunta que responde:** ¿cómo obtienen acceso a las cuentas de Instagram/Facebook de sus clientes los productos comerciales que ya resolvieron este problema? ¿Patrón 1 (una app del vendor, revisada por Meta, a la que cada cliente hace OAuth) o Patrón 2 (cada cliente registra su propia app de Meta y el producto la consume con credenciales del cliente)?
**Método:** investigación de escritorio con web en vivo, 2026-07-29. Todas las fechas de acceso son 2026-07-29 salvo indicación contraria.
**Autor:** agente `gtm-specialist`.

> **Nota de alcance / propiedad.** Este doc **documenta el campo tal como es**, con fuente y fecha. No emite la lectura legal de las Platform Terms de Meta ni el ADR: `principal-architect` trabaja en paralelo sobre esa misma pregunta y esa interpretación es suya. Donde encuentro texto de Meta que toca el Patrón 2, lo transcribo literal y lo marco como **dato sin interpretar**.

## Nota de calidad de fuentes (leer antes que las tablas)

Hereda el sesgo documentado en `docs/fase0-zernio-mercado.md`: el contenido indexable sobre "APIs de publicación social" es en gran parte marketing de los propios competidores, con incentivo directo en exagerar la fricción de la integración nativa. Por tanto, **el blog de un vendor no es evidencia suficiente sobre su propio modelo de acceso**; su documentación técnica, su flujo de onboarding y su centro de ayuda sí.

- **[P] Primaria** — documentación oficial de la plataforma, docs de API del vendor, su centro de ayuda, su página de precios, o el listado oficial de partners de Meta/TikTok.
- **[S] Secundaria interesada** — blog de un competidor/agregador. Pista, nunca prueba.
- **[T] Terciaria neutral** — comparativas o reportes de desarrolladores sin producto en juego.

---

## 1. Los dos patrones, y qué evidencia decide cuál usa un producto

> **Aviso de lectura, añadido 2026-07-29 tras revisión del `principal-architect`.** La columna del Patrón 2 de la tabla siguiente enuncia **la promesa del patrón tal como lo plantea el encargo**, no una afirmación verificada por mí. La fila del App Review es precisamente la que esta investigación **desmiente** — ver §4.2 y §6. Y su premisa (*"basta con que los usuarios tengan un rol en la app"*) es **falsa por la letra de Meta** según el ruling del architect en ADR 29: la definición de Tech Provider cubre *"a **single** integration on behalf of an **individual** client"*, **sin umbral de N**. Esa lectura de las Platform Terms es suya, no mía; la reproduzco como puntero para que nadie use la tabla suelta.

| | **Patrón 1 — app única revisada** | **Patrón 2 — BYO app (una app de Meta por cliente)** — *promesa del patrón* |
|---|---|---|
| Quién registra la app de Meta | El vendor, una vez | Cada cliente, para sí mismo |
| ¿App Review + Business Verification? | Sí, del vendor. 2–4 meses, rechazable | **La promesa es "no".** ⚠️ **Desmentido en §4.2**: el trámite no desaparece, se reubica en el cliente en cuanto hay un tercero servido. La premisa de exención por "rol en la app" además no se sostiene a nivel de Platform Terms (ADR 29) |
| Qué hace el cliente en el alta | OAuth: "conecta tu cuenta", 3 clics | Registrar una app en `developers.facebook.com`, configurar productos y redirect URI, copiar App ID + App Secret al producto |
| Quién es responsable ante Meta | El vendor | El cliente (es su app) |
| Escalabilidad self-serve | Alta | Baja — la fricción de alta es el techo de conversión |

**Evidencia que decide, en orden de fuerza.** Que un producto se declare "partner de Meta" en su marketing no prueba el Patrón 1 (es la clase de afirmación que un [S] infla). Lo que prueba es el **flujo de onboarding documentado**:

- Si el centro de ayuda dice *"revisa los permisos que le estás otorgando a \<vendor\> y guarda"* → el consentimiento va **a una app del vendor** → Patrón 1, sin ambigüedad. Una app del cliente no puede pedir permisos "para el vendor".
- Si la doc de API expone un endpoint tipo `GET /connect/{platform}` que **devuelve la URL de autorización ya construida**, y dice explícitamente que el integrador no intercambia el `code` → las credenciales de plataforma son del vendor → Patrón 1.
- Si el onboarding incluye un paso *"crea una app en developers.facebook.com y pega tu App ID / App Secret"* → Patrón 2.

Aplico este test a los tres productos siguientes.

---

## 2. ManyChat — Patrón 1, sin ambigüedad

`docs/ingenieria-inversa-manychat.md` §2.2 ya estableció el **coste de dos pisos** (piso 1: App Review + Business Verification + partner status, pagado por ManyChat una vez; piso 2: OAuth de la cuenta, pagado por el cliente en 3 clics). Lo que aquel doc no verificó es **el flujo que ve el usuario**, que es la evidencia que decide entre los dos patrones. Verificado ahora.

### 2.1 El flujo de conexión: tres métodos, los tres OAuth contra la app de ManyChat

[P] [Cómo vincular Instagram a Manychat](https://help.manychat.com/hc/es/articles/14281290924444) — artículo oficial, `updated_at` **2026-07-29**, accedido 2026-07-29 vía la API de Zendesk del propio help center (la web devuelve **403** a clientes no-navegador; mismo obstáculo que registró `ingenieria-inversa-manychat.md` §3 para la página de precios).

Precondición única: *"tu cuenta de Instagram debe estar configurada como una cuenta profesional (Empresa o Creador). Las cuentas personales no se pueden usar"*. **No hay ninguna otra precondición técnica.**

| Método | Pasos que ve el usuario | Requisito |
|---|---|---|
| **Connect Via Meta** (recomendado por ManyChat) | *"selecciona la cuenta empresarial de Instagram que deseas vincular"* → *"**Revisa los permisos que le estás otorgando a Manychat** y haz clic en Save"* | Cuenta IG vinculada a un Portfolio empresarial de Meta. Habilita Follow-to-DM y CAPI |
| **Connect Via Instagram** | *"comprueba los permisos que concedes a Manychat y haz clic en Allow"* | *"la forma más rápida y fácil… **No requiere una cuenta de Meta Business**"*. Algunas funciones avanzadas quedan limitadas |
| **Connect Via Meta Business Suite** | Login FB → seleccionar cuenta IG → seleccionar/crear Página de FB → *"confirma que aceptas que **Manychat tenga acceso a tu página de Facebook**"* → elegir si ManyChat accede a todas las cuentas IG de esa Página o solo a la seleccionada → revisar permisos → Save | Ser **administrador con control total** de la Página de FB vinculada. Recomendado para agencias y acceso a Meta Ads Manager |

**Cero menciones a crear una app de Meta, a `developers.facebook.com`, a un App ID o a un App Secret** en todo el artículo — que es un how-to exhaustivo de tres rutas distintas más el alta desde cero. La frase *"los permisos que le estás otorgando a Manychat"* es literalmente el consentimiento a una app de tercero: **es la app de ManyChat**.

### 2.2 El caso agencia — donde el Patrón 2 aparecería si existiera, y no aparece

El mismo artículo [P] tiene una sección *"Vincular la cuenta de Instagram de un cliente (para agencias)"*. Es el escenario exacto de Qualify (un operador gestionando cuentas de terceros), y las tres opciones que ofrece son:

1. Pedir acceso a la cuenta de IG del cliente y vincularla a **tu** cuenta de ManyChat.
2. Que el cliente vincule su cuenta a **su** cuenta de ManyChat y luego te dé acceso de admin con un link de invitación.
3. Vincular vía Meta Business Suite.

Las tres se resuelven con **permisos de cuenta y de Página**, ninguna con credenciales de desarrollador. Si ManyChat quisiera trasladar el coste de cumplimiento al cliente, éste era el sitio natural para hacerlo, y no lo hace.

### 2.3 Estatus formal declarado

[P] [¿Manychat está oficialmente aprobado por Meta?](https://help.manychat.com/hc/es/articles/18624810395932), `updated_at` **2026-07-21**, accedido 2026-07-29:

> *"Manychat es la plataforma de automatización de mensajes directos de Instagram más grande del mundo, que permite que ocurran conversaciones significativas en **más de 100 000 cuentas de Instagram**"* · *"Como **Meta Business Partner** oficiales, nos reunimos con su equipo de productos semanalmente"* · *"Nuestra asociación con Meta significa que trabajamos directamente con las **API oficiales de Instagram**"*.

Y el límite de esa posición, en el mismo artículo — relevante porque acota qué compra realmente el Patrón 1: *"no controlamos las reglas de Meta ni tenemos una línea directa para restablecer cuentas"*, *"No podemos revertir suspensiones ni restricciones de cuentas"*, *"No podemos anular el sistema de detección de spam"*.

**Matiz sobre "Meta Business Partner":** es una **autodeclaración en su help center**, no una verificación en un directorio oficial de Meta. Es coherente con el resto de la evidencia y no la contradigo, pero la etiqueta concreta queda como **no verificada de forma independiente** — ver §8. La misma cautela ya se aplicó en `ingenieria-inversa-manychat.md` §2.4 al descubrir que ManyChat **no aparece** en la lista oficial de *Messaging Partners* de TikTok pese a integrar TikTok DM. Lo que sí está probado por el flujo de onboarding, y no depende de ninguna etiqueta, es que **ManyChat opera bajo apps propias**.

**Los >100.000 cuentas de IG son el dato que cierra el caso económicamente:** no existe una versión del Patrón 2 en la que 100.000 clientes registren cada uno su app de Meta. El Patrón 1 no es una preferencia de ManyChat, es la única forma en que su escala es posible.

---

## 3. Zernio — Patrón 1, y lo dice su propia doc de API en una frase

`docs/fase0-zernio-mercado.md` §1 analizó los **plazos** de acceso de cada plataforma; nunca analizó cómo Zernio resuelve su propio cumplimiento. Respondido ahora, con la doc técnica (no con su marketing, por la regla de fuentes de arriba).

### 3.1 La frase que decide

[P] [Zernio · llms.txt](https://zernio.com/llms.txt) (volcado literal de su doc de API, descargado 2026-07-29) y [P] [docs.zernio.com](https://docs.zernio.com) (accedido 2026-07-29). Sobre el endpoint `GET /v1/connect/{platform}`:

> ⚠ **CORRECCIÓN DE FUENTE (2026-07-30, hallazgo del `architect`).** `zernio.com/llms.txt` (25 KB) es un volcado **parcial y desactualizado** — enumera ~40 endpoints y hace parecer a Zernio un simple scheduler. **No volver a citarlo como referencia de capacidades.** La fuente correcta es **`https://docs.zernio.com/llms-full.txt`** (3,6 MB, generado de su OpenAPI) + `docs.zernio.com/sitemap.xml` (~600 páginas). **La cita literal de abajo y todo el razonamiento de §3 siguen siendo válidos** — la frase existe en ambas versiones y la conclusión sobre el Patrón 1 no depende del inventario. Lo que quedó corto es el **inventario de capacidades** (§3.4 y la tabla de §7). Detalle completo en `docs/arquitectura.md` §6 *"Revisión 2026-07-30"* y en `docs/fase0-zernio-mercado.md` §2.1-bis.

> *"There is **NO separate completion step** and **NO `code` to exchange on your side**. **We complete the OAuth on our own callback**, then redirect the browser to your `redirect_url`."*

Esto es concluyente y no requiere inferencia: si Zernio completa el OAuth en **su propio callback** y el integrador nunca ve el `code`, entonces el `client_id` que aparece en la pantalla de consentimiento es **de Zernio**. Un modelo BYO app es técnicamente incompatible con esa frase — el `code` se emite contra la redirect URI registrada en la app, y en una app del cliente el intercambio tendría que ocurrir del lado del cliente.

Confirmación del lado del usuario, misma doc: *"Open the URL in a browser to **authorize Zernio to access your \<platform\> account**"*. El sujeto autorizado es Zernio.

### 3.2 Qué scopes pide su app — el dato más transferible a Qualify

[P] [docs.zernio.com/platforms/instagram](https://docs.zernio.com/platforms/instagram) (accedido 2026-07-29). Zernio conecta Instagram vía **Instagram Login for Business** y pide **toda la familia `instagram_business_*` en un único flujo de OAuth**:

| Scope | Para qué |
|---|---|
| `instagram_business_basic` | identidad y perfil |
| `instagram_business_content_publish` | publicación |
| `instagram_business_manage_insights` | analítica |
| `instagram_business_manage_comments` | gestión de comentarios |
| `instagram_business_manage_messages` | DMs |

> *"Zernio requests all scopes in a single OAuth flow when the account is connected; **scopes cannot be requested individually**."* · *"Instagram requires a Business or Creator account. Personal accounts cannot post via API."*

Dos hechos que hay que registrar sin interpretarlos aquí:

1. **Zernio pide en producción exactamente la familia de permisos que Qualify necesita**, incluidos publicación y mensajería — que son Advanced Access y por tanto exigen App Review. Un producto comercial vivo pidiéndolos es evidencia de que ese trámite se pasa; **no** es evidencia de cuánto tardó.
2. **Zernio usa Instagram Login, no Facebook Login for Business.** Qualify decidió la bifurcación contraria en ADR 25 (firmada 2026-07-26, con `linked_page_id NOT NULL` ya en DDL aplicado). Lo dejo como **dato de campo**: existe un producto comercial de publicación+mensajería operando bajo la otra rama. La lectura de si eso afecta a ADR 25 es del `principal-architect`, no mía. Nota factual adyacente de su propia doc: *"Ad permissions cannot be granted through Instagram Login — those require a separate Facebook account connection for Meta Ads functionality"*, es decir, la rama Instagram Login le cuesta a Zernio una conexión de Facebook **adicional** para ads.

### 3.3 TikTok — Zernio pasó la auditoría

[P] [docs.zernio.com/platforms/tiktok](https://docs.zernio.com/platforms/tiktok) (accedido 2026-07-29). Pide `video.publish` y su propio quick-start usa `privacy_level: 'PUBLIC_TO_EVERYONE'`. Sus advertencias operativas son *"TikTok has a strict daily posting limit for posts created via third-party APIs"* y *"the privacy levels available via API depend on each creator's TikTok account settings — you must fetch the creator's allowed levels"*, pero **no** el `SELF_ONLY` forzado ni el "la cuenta entera debe estar en privado" que `fase0-zernio-mercado.md` §1.1-bis documentó.

Esto **no contradice** a §1.1-bis: aquella restricción es la de un cliente API **no auditado**. Que Zernio no la sufra es la prueba de que **sí pasó la auditoría de TikTok** bajo su propio cliente API. La restricción es real y sigue aplicando a Qualify hoy; lo que Zernio demuestra es que tiene salida, pagando el trámite.

### 3.4 La excepción: dos plataformas donde Zernio sí pide credenciales del usuario

No todo su modelo es OAuth propio, y el patrón de la excepción es informativo:

- **Bluesky**: `POST /v1/connect/bluesky/credentials`, con body `{ identifier, appPassword }` [P] llms.txt. El usuario trae una **app password** propia.
- **Telegram**: la guía de conexión indica que Zernio maneja credenciales directamente en vez de OAuth [P] [docs.zernio.com/guides/connecting-accounts](https://docs.zernio.com/guides/connecting-accounts), accedido 2026-07-29.

**La regularidad:** Zernio usa credenciales del usuario **exactamente en las plataformas que no tienen un programa de revisión de apps** (Bluesky/AT Protocol es abierto; Telegram entrega tokens de bot al instante). Donde hay un gate de plataforma que cuesta meses — Meta, TikTok — Zernio lo paga él y opera app propia. Dicho al revés: **el BYO credential aparece donde no ahorra nada, y desaparece donde ahorraría meses.** Es la observación más útil de esta sección.

### 3.5 El modelo de precio encaja con el Patrón 1

Su tarifa por **cuenta conectada** — 2 primeras gratis, cuentas 3–10 a **$6/mes**, 11–100 a **$3/mes**, 101+ a **$1/mes** [P] [zernio.com/pricing](https://zernio.com/pricing), tal como lo registró `fase0-zernio-mercado.md` §2.2 el 2026-07-21 — es coherente con el Patrón 1 y difícilmente explicable en el Patrón 2: en BYO app la cuenta conectada consume cuota de la app **del cliente**, y cobrar por ella sería cobrar por un recurso que el vendor no aporta. Cobrar por cuenta conectada es cobrar por el acceso, y el acceso es lo que el vendor posee.

> **Pendiente sin resolver — `BYOK`.** En la tabla de códigos de error de su API aparece literalmente `403: Forbidden (quota exceeded, BYOK required)` [P] llms.txt, 2026-07-29. Es la **única** aparición de "BYOK" en toda su documentación: ni la guía de conexión, ni la página de X/Twitter, ni la de Instagram lo explican, y `docs.zernio.com/guides/pricing` se renderiza por JS y devuelve un shell vacío a `curl`. **Hipótesis no verificada** (la marco como tal): sería el caso de X/Twitter, cuya API es pay-per-use y donde un vendor no puede absorber el coste unitario indefinidamente — un BYOK **económico**, no de cumplimiento. No lo afirmo. Cerrar esto requiere cuenta en el dashboard de Zernio.

---

## 4. Tercer punto de comparación — donde el Patrón 2 sí existe: Mixpost y Postiz (self-hosted)

Elegí **dos** en vez de uno, porque son los dos productos de la categoría cuya documentación es inequívoca (open-source / self-hosted, sin incentivo de marketing en ocultar la fricción) y porque coinciden. Aquí el Patrón 2 no es una hipótesis: es el modelo documentado, paso a paso.

### 4.1 Mixpost — BYO app explícita, con formulario para pegar el App Secret

[P] [Facebook & Instagram Integration | Mixpost Documentation](https://docs.mixpost.app/services/social/facebook/) (accedido 2026-07-29). El procedimiento que documenta para el operador:

1. Tener una **cuenta de desarrollador de Facebook**.
2. En el Developer Dashboard, **Create App**; filtro de caso de uso **Content management**; casos de uso *"Manage everything on your Page"* y *"Manage messaging & content on Instagram"*.
3. En **Facebook Login for Business → Settings**, registrar el redirect URI: `https://example.com/<MIXPOST_CORE_PATH>/callback/facebook_page`.
4. En **App Settings → Basic**, copiar **App ID** y **App Secret**.
5. *"pegarlos en el formulario de servicio de terceros de Facebook"* del propio dashboard de Mixpost (Admin Console → Services).

El paso 5 es la firma del Patrón 2: **el producto tiene un campo de UI para las credenciales de la app de Meta del operador.** Ningún producto del Patrón 1 tiene ese campo.

### 4.2 El hallazgo de Mixpost que decide el veredicto entero

Mixpost tiene una página de documentación **titulada "Facebook App Review"** — es decir, un producto del Patrón 2 documentando cómo su propio usuario pasa el App Review. Y dice cuándo aplica:

> *"This step is **mandatory for users providing Software as a Service (SaaS)** through Mixpost Enterprise. However, **if you are using Mixpost internally, this step is not required**."*
> — [P] [Facebook App Review | Mixpost Documentation](https://docs.mixpost.app/services/social/facebook/app-review/), accedido 2026-07-29

En la misma página: *"Facebook Business Verification is required"* para el proceso, hay que *"request advanced permissions"* (`business_management`, `pages_show_list`, `read_insights`, `pages_manage_posts`, entre otros), y sobre las demostraciones de prueba: *"While the app is unverified, Facebook only returns data … for profiles that **have a role in the app**"*.

**Esto es el resultado más importante de toda la investigación, y va contra la esperanza que motivó el encargo.** El Patrón 2 **no elimina el App Review: lo reubica.** Se lo salta exactamente en el caso de uso interno — que es el mismo caso en que el Patrón 1 también se lo salta, por la exención de "rol en la app" que `docs/integracion-cuentas-conectadas-meta.md` §3.1 ya había verificado. En el momento en que hay un tercero servido, el trámite reaparece, y ahora lo tiene que pasar **el cliente**, que es quien menos capacidad tiene de pasarlo.

### 4.3 Postiz — mismo modelo, y una corroboración independiente de la regla del "rol en la app"

[P] [Instagram | Postiz Documentation](https://docs.postiz.com/providers/instagram) y [P] [Facebook | Postiz Documentation](https://docs.postiz.com/providers/facebook) (ambos accedidos 2026-07-29). Nueve pasos, de los que importan cuatro:

- *"Create a new app in Facebook developers"* — *"please be advised that **for public applications, you will need to verify your business**"*.
- Registrar el redirect URI `https://your-postiz-domain.com/integrations/social/facebook`.
- Pedir acceso avanzado a `pages_show_list`, `business_management`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_engagement`, `read_insights` — con la coletilla: *"**If your Postiz install is for personal use only these advanced permissions are not required** for Postiz to function."*
- *"Copy your App ID and App Secret and paste them in your `.env` file"* → `FACEBOOK_APP_ID` / `FACEBOOK_APP_SECRET` (y `INSTAGRAM_APP_ID` / `INSTAGRAM_APP_SECRET` en la variante Instagram standalone).

Y la frase que corrobora, desde un tercero sin relación con Qualify, la regla que sostiene todo el plan de cliente cero:

> *"The advanced permissions on the Meta app must be approved (**or your account must be a developer/tester on the app**). Submit the app for review with the required scopes — **until then, only roles you've added can publish**."*
> — [P] docs.postiz.com/providers/instagram, 2026-07-29

Es la misma regla que `docs/integracion-cuentas-conectadas-meta.md` §3.1 leyó de la doc de Meta el 2026-07-24, ahora confirmada por cómo la implementa un producto real. **Corroboración útil: la exención de "rol en la app" no es una lectura creativa de la doc de Meta — es cómo la categoría opera.** Es la tercera fuente independiente del mecanismo (Meta, Mixpost, Postiz).

> **Límite de esta corroboración — no la estire nadie.** Valida el **mecanismo de la exención de rol** (quién puede publicar sin App Review). **No** rescata la afirmación sobre *visibilidad de media* que el architect retiró de su §3.1 el 2026-07-29 a raíz de §7.2 de este doc, que vive en el eje App Mode. Las dos conviven sin contradicción: la exención de rol es real **y** publicar con la app en Development Mode no produce un post público normal.

### 4.4 El detalle operativo que Postiz documenta y nadie más

Postiz añade un paso 8 que ningún otro doc de la categoría menciona, y es material para el dogfooding de Qualify — ver §7.2, donde lo registro como dato para el architect en vez de interpretarlo aquí:

> *"**Set app mode to Live.** Change the App Mode from 'Development' to 'Live'. **If you do not do this then posts made via the API will display for yourself but will not be visible for other users.**"* · *"posts with media are only visible to app developers/testers — everyone else sees the post without the image."*
> — [P] docs.postiz.com/providers/facebook, 2026-07-29

### 4.5 El contraste interno que cierra la lectura

Tanto Mixpost como Postiz tienen **oferta cloud además de self-hosted** (Postiz: *"Register to the cloud"*, con secciones de doc propias *Billing (Cloud)* y *Channel Limits (Cloud)*; Mixpost: *Mixpost Enterprise* como el producto con el que se sirve SaaS). El mismo código base se distribuye en los dos patrones: **BYO app cuando lo instalas tú, app del vendor cuando el vendor lo aloja.** Esa bifurcación dentro de un solo producto es la evidencia más limpia de que los dos patrones no son alternativas de diseño en competencia, sino **consecuencias de quién sirve a quién**.

### 4.6 Caso frontera comprobado: Ayrshare — Patrón 1 con pantalla de conexión white-label

Comprobé si algún SaaS comercial ofrece BYO app como **opción**, porque sería el contraejemplo que rompe el veredicto. El más cercano es Ayrshare (que `fase0-zernio-mercado.md` §2.3 marcó como **prohibida por sus propios términos** para el caso de Qualify — eso no cambia, aquí solo lo uso como evidencia de modelo de acceso).

[P] [Ayrshare · API Integration for Business](https://ayrshare.mintlify.app/multiple-users/api-integration-business) (accedido 2026-07-29): el cliente final conecta por una **URL JWT white-label** (token válido 5 minutos) y *"authenticates directly with each social network's official login page"*. **Se usan las apps OAuth de Ayrshare.** La doc **no menciona** que el cliente registre app propia de Meta. El white-label llega hasta *"add your logo and custom headers … with the Max Pack, apply a full custom CSS file, favicon, page title, and footer"* — es decir, **se personaliza la página de conexión, no la app de Meta**.

Y la excepción, que repite exactamente la regularidad de §3.4 — [P] [ayrshare/social-post-api-python · README](https://github.com/ayrshare/social-post-api-python/blob/main/README.md) (accedido 2026-07-29):

> *"As of **March 31, 2026**, posting and other X/Twitter actions through Ayrshare **require your own X Developer App consumer key and secret** in the outbound API request — Ayrshare enforces this on every X-bound call"*, vía las cabeceras `X-Twitter-OAuth1-Api-Key` / `X-Twitter-OAuth1-Api-Secret`.

**BYOK en X. No en Meta.** Esto sube la hipótesis de §3.4 sobre el `BYOK required` de Zernio de "especulación" a "hipótesis con precedente en un competidor" — sigue sin verificar para Zernio, pero ahora sé que el patrón existe y **dónde** existe: en la plataforma cuya API se paga por request, no en las que se gatean por revisión. La causa del BYOK es **económica, no de cumplimiento**.

---

## 5. Tabla comparativa — qué patrón usa cada producto y con qué evidencia

| Producto | Tipo | Patrón | Evidencia decisiva | Fuerza |
|---|---|---|---|---|
| **ManyChat** | SaaS comercial (DM automation) | **1 — app propia** | *"Revisa **los permisos que le estás otorgando a Manychat**"*; tres rutas de conexión, cero mención de crear app; sección de agencias resuelta con permisos de cuenta/Página | [P] help center, 2026-07-29 |
| **Zernio** | SaaS comercial (API de publicación) | **1 — app propia** | *"**We complete the OAuth on our own callback**"*, *"NO `code` to exchange on your side"*; pide `instagram_business_content_publish` + `manage_messages` en un flujo | [P] doc de API, 2026-07-29 |
| **Ayrshare** | SaaS comercial (API de publicación) | **1 — app propia**, página de conexión white-label. **BYOK solo en X** | *"Ayrshare's OAuth applications are used"*; white-label = logo/CSS/favicon. BYOK X obligatorio desde 2026-03-31 | [P] docs + SDK oficial, 2026-07-29 |
| **upload-post** | SaaS comercial (API white-label) | **1 — app propia** (indicativo) | JWT URL con OAuth branded; sin mención de credenciales del cliente | [S] su propia página de white-label, 2026-07-29 — **no verificado en doc técnica** |
| **Blotato** | SaaS comercial | **1 — app propia** (indicativo) | *"users simply log in, pick the account ID"* | [S], 2026-07-29 — **no verificado** |
| **Mixpost** | Self-hosted / open-source | **2 — BYO app** | Formulario en Admin Console para pegar **App ID + App Secret**; página propia titulada *"Facebook App Review"* | [P] docs.mixpost.app, 2026-07-29 |
| **Postiz** | Self-hosted / open-source | **2 — BYO app** | *"Copy your App ID and App Secret and paste them in your `.env`"* → `FACEBOOK_APP_ID`/`FACEBOOK_APP_SECRET` | [P] docs.postiz.com, 2026-07-29 |
| **Mixpost Enterprise · Postiz Cloud** | Oferta alojada de los anteriores | **1** cuando lo aloja el vendor | Mismo código, patrón distinto según quién sirve | [P] docs de ambos, 2026-07-29 |

### Tradeoffs, tal como los revela la evidencia (no como los presenta el marketing)

| Dimensión | Patrón 1 (app única revisada) | Patrón 2 (BYO app) |
|---|---|---|
| Coste de arranque para el vendor | **Alto**: entidad legal verificada + App Review 2–4 semanas por envío, rechazable (`fase0-zernio-mercado.md` §1.2: 2–4 meses realistas) | **Cero** |
| Coste de alta para el cliente | 3 clics de OAuth | Cuenta de desarrollador + crear app + configurar casos de uso + redirect URI + copiar secret. **Y App Review propio si sirve a terceros** |
| ¿Elimina el App Review? | No — lo paga el vendor una vez | **No — lo reubica en el cliente.** Solo lo elimina en uso interno, que es donde el Patrón 1 también está exento |
| Techo de escala | Los >100.000 IG de ManyChat | La paciencia del cliente. No hay ejemplo de escala self-serve |
| Quién responde ante Meta | El vendor | El cliente (es su app) |
| Superficie de marca | Personalizable en la página de conexión, **no** en el diálogo de OAuth de Meta (que muestra el nombre de la app) | Es la app del cliente |
| Dónde se observa | **Todo SaaS comercial verificado** (5/5) | **Solo self-hosted/open-source** (2/2), más BYOK puntual en X por motivo económico |

---

## 6. Veredicto de categoría

**El patrón dominante es el 1, y el margen no es estrecho: es 5–0 entre productos SaaS comerciales verificados y 2–0 a favor del 2 entre self-hosted.** La separación es limpia y la respuesta a la pregunta 4 del encargo es la versión fuerte:

> **El Patrón 2 aparece exclusivamente en herramientas self-hosted / open-source, y en ningún SaaS comercial de esta categoría.** Cuando el mismo producto se ofrece en las dos modalidades (Mixpost, Postiz), usa el Patrón 2 en la self-hosted y el Patrón 1 en la alojada.

Y la razón por la que no se hace en SaaS **no es inercia ni desconocimiento** — es que **el Patrón 2 no compra lo que parece comprar**. La frase de Mixpost (§4.2) lo dice en la doc del único tipo de producto que lo practica: el App Review es *"mandatory for users providing SaaS … if you are using Mixpost internally, this step is not required"*. El ahorro del Patrón 2 se concentra en el caso de uso interno, y **ese caso ya está exento en el Patrón 1** por la regla de "rol en la app" (`docs/integracion-cuentas-conectadas-meta.md` §3.1, corroborada independientemente por Postiz en §4.3 de este doc).

Formulado como la regla que hay que recordar: **el Patrón 2 no traslada el coste de cumplimiento del vendor al cliente; lo duplica.** El vendor deja de pagarlo una vez y el cliente empieza a pagarlo cada vez. En un producto self-hosted eso es aceptable porque el operador y el cliente son la misma persona y hay un único trámite. En un SaaS con N clientes son N trámites, cada uno con un cliente que no tiene entidad verificada ante Meta ni razón para conseguirla.

**Excepción real y acotada, para no dejarla implícita:** el BYO credential sí existe en producto comercial, y con dos formas distintas, ambas con la misma causa:
- **Plataformas sin programa de revisión** (Bluesky app password, Telegram) — donde BYO no ahorra trámite porque no hay trámite.
- **Plataformas con coste unitario por request** (X/Twitter: BYOK obligatorio en Ayrshare desde 2026-03-31; probablemente el `BYOK required` de Zernio) — donde BYO traslada un coste **económico**, no de cumplimiento.

**Ninguna de las dos excepciones toca Meta.** En Meta, los cinco productos comerciales examinados operan app propia revisada, sin excepción y sin opción.

### Mapeo al roadmap (obligatorio antes de que esto se convierta en propuesta)

Esta decisión pertenece a **Fase 1 Parte 4** (ingesta first-party por cuenta conectada) y a los cortes de dogfooding **Parte 4-A/4-B**, no a Fase 5. Sirve la **moción de activación** (publicación, inbox, respuestas asistidas), no la de listening: el listening de medios ganados no necesita OAuth del cliente en absoluto. Es exactamente el módulo `connections` que ya existe en `packages/api/` con la custodia y la FSM de C-03/C-04 — y **el Patrón 1 es el que ese código ya asume** (una app de plataforma en `platform_apps`, credenciales del cliente en `oauth_credentials`). El hallazgo de este doc **no pide reescribir nada**; lo que hace es retirar la esperanza de que el Patrón 2 fuera un atajo disponible.

---

## 7. Datos sobre términos y documentación de Meta — **sin interpretar** (para `principal-architect`)

Recogidos porque el encargo los pide y porque `principal-architect` está leyendo las Platform Terms en paralelo. **Transcritos, no leídos.** La interpretación de si Meta permite o prohíbe el Patrón 2 es suya y no la emito aquí.

### 7.1 Sobre el Patrón 2 en la documentación de Meta

No encontré en esta pasada ningún texto de Meta que **prohíba expresamente** que un tercero opere software sobre la app de Meta de un cliente, ni ninguno que lo **autorice expresamente**. Lo que hay es evidencia indirecta y de terceros: dos productos (Mixpost, Postiz) documentan públicamente el Patrón 2 desde hace años sin, por lo que se ve, consecuencia visible. **Eso es ausencia de evidencia, no evidencia de permiso**, y lo dejo como tal. Búsqueda no exhaustiva — ver §8.

### 7.2 Dato de campo con doble fuente: el eje **App Mode** (Development/Live)

Registrado también en `.claude/sprint-state-2026-07-29-modelo-acceso.md` y enviado por mensaje al architect el 2026-07-29.

> [P] Meta, [App Modes](https://developers.facebook.com/docs/development/build-and-test/app-modes), accedido 2026-07-29: *"Any data generated while an app is in Development mode, such as test posts, **can only be seen by role users**."* Y: *"data generated while in Development mode such as test posts **will become visible to all app users once you switch**."*
>
> [P] [docs.postiz.com/providers/facebook](https://docs.postiz.com/providers/facebook), accedido 2026-07-29, paso 8 de su guía: *"Change the App Mode from 'Development' to 'Live'. **If you do not do this then posts made via the API will display for yourself but will not be visible for other users**."* Y: *"posts with media are only visible to app developers/testers — everyone else sees the post without the image."*

**Por qué lo separo y no lo concluyo:** `docs/fase0-zernio-mercado.md` §1.1-bis (architect, 2026-07-24) afirma que *"no existe en la doc de Meta ningún mecanismo por el que el nivel de acceso degrade la visibilidad"*. Esa afirmación es sobre el eje **nivel de acceso** (Standard/Advanced) y no la contradigo. **App Mode es un eje distinto**, y en ese eje la doc de Meta sí describe degradación de visibilidad. No es una contradicción: es un segundo eje que §1.1-bis no cubrió. Es material para Parte 4-A porque lo que Parte 4-A publica es **media** (reels), que es precisamente el caso que la doc de Postiz señala.

**La pregunta que decide, y que no pude cerrar:** si pasar a Live mode exige App Review y/o Business Verification, o es un toggle self-serve. Postiz dice *"for public applications, you will need to verify your business"* sin precisar a qué de los dos se refiere. Del architect.

### 7.3 Otros datos transcritos

- [P] Mixpost, App Review: *"Facebook Business Verification is required"*; *"While the app is unverified, Facebook only returns data … for profiles that **have a role in the app**"* (2026-07-29).
- [P] Postiz, Instagram: *"The advanced permissions on the Meta app must be approved (**or your account must be a developer/tester on the app**) … until then, **only roles you've added can publish**"* (2026-07-29). Corrobora el **mecanismo de la exención de rol** de `integracion-cuentas-conectadas-meta.md` §3.1 desde una fuente sin relación con Qualify — y **solo** ese mecanismo, no el eje de visibilidad de §7.2. Ver el aviso de límite en §4.3.
- [P] Zernio, Instagram: opera publicación **y** mensajería de IG vía **Instagram Login for Business**, no Facebook Login for Business — la rama contraria a ADR 25. Coste documentado de esa rama: *"Ad permissions cannot be granted through Instagram Login — those require a separate Facebook account connection for Meta Ads functionality"* (2026-07-29). **Dato de campo; el impacto sobre ADR 25 lo decide el architect.**
  - **Resuelto por el architect 2026-07-29 (ruling ADR 25):** el dato **confirma** ADR 25 en vez de amenazarla. Zernio es un **publicador** — no necesita `mentioned_media`, `mentioned_comment` ni hashtag search, que son las dos únicas superficies *earned* del camino OAuth y la razón entera de ADR 25. Para un publicador, Instagram Login es la rama correcta y más barata; Qualify no es un publicador y esa rama borraría la cascada multimodal del camino de cuentas conectadas. Que el competidor-publicador elija la rama del publicador es evidencia de que **las ramas están bien caracterizadas**. Su limitación de `ads_management` corrobora además el punto (c) del ruling original.

---

## 8. Pendientes explícitos — lo que NO verifiqué

Ninguno de estos se convierte en inferencia. Quedan abiertos.

| # | Pendiente | Por qué no se cerró | Cómo se cierra |
|---|---|---|---|
| 1 | Si pasar a **Live mode** exige App Review / Business Verification o es self-serve. **Promovido por el architect a la verificación más bloqueante del expediente Meta (A5-5 / V-TP-2), asignada al fundador**, fusionada con la prueba empírica de su §7.6 y ampliada a tres preguntas: (a) trámite del toggle, (b) si un permiso Standard sobrevive al paso para un titular de rol, (c) visibilidad real de un reel publicado en Development. Motivo del (b): el architect encontró `graph-api/changelog/version3.0.md:128` — *"Apps in public mode no longer allow their admins, developers, or testers to access permissions or features that normally require app review"*; si sigue vigente, pasar a Live podría **apagar** los permisos que el fundador usa hoy | La doc de Meta describe el efecto del modo, no el requisito del toggle. Es empírica, no documental | Crear una app de prueba e intentar el cambio con una cuenta propia |
| 2 | Qué es el `403 BYOK required` de **Zernio** y en qué plataformas aplica | Única mención en toda su doc; `docs.zernio.com/guides/pricing` se renderiza por JS y devuelve shell vacío a `curl` | Cuenta en el dashboard de Zernio, o preguntar a soporte |
| 3 | ~~Si **"Meta Business Partner"** de ManyChat es una designación verificable~~ → **CERRADO 2026-07-30 en §9.5**, con el obstáculo nombrado: el directorio de Meta **exige login**, así que la afirmación queda *no confirmada ni desmentida*. Lo sustituye el pendiente #8 | — | — |
| 4 | Si Meta **prohíbe o permite** expresamente el Patrón 2 en Platform Terms | Fuera de mi alcance por diseño: es del architect | Lectura de Platform Terms, en curso por `principal-architect` |
| 5 | Modelo de acceso de **upload-post** y **Blotato** | Solo tengo su propia página de marketing [S]; su doc técnica no se consultó | Leer su doc de API / probar el onboarding |
| 6 | Si algún SaaS comercial ofrece BYO app como **opción enterprise** | Comprobé el caso frontera más probable (Ayrshare) y es Patrón 1. No es una búsqueda exhaustiva del mercado | Revisar términos enterprise de 3–4 vendors más |
| 7 | Cuánto **tardó** realmente el App Review de Zernio/ManyChat | Ningún vendor publica su calendario de revisión | Solo por contacto directo. La estimación de 2–4 meses de `fase0-zernio-mercado.md` §1.2 sigue siendo la mejor disponible, y es [S] |

---

## 9. ¿Qué significa "somos partner de Meta / de TikTok"? — badge vs. acceso técnico

**Encargo (fundador, 2026-07-29):** Zernio se declara partner de Meta y de TikTok. Separar **programa de badge/marketing** (directorio, logo, soporte, co-marketing) de **status de acceso técnico** (que cambie el régimen de App Review, niveles de acceso, cuotas o tipos de token). Cierra el pendiente #3 de §8.

### 9.1 Primer hallazgo: la premisa del encargo no se sostiene tal cual — Zernio casi no se declara partner

El encargo parte de que *"Zernio se declara partner de Meta y de TikTok"*. Verifiqué las superficies primarias de Zernio y **el resultado es más estrecho que eso**, lo cual cambia la pregunta:

| Superficie de Zernio | Ocurrencias de "partner" / "badge" / "certified" / "Tech Provider" | Fuente |
|---|---|---|
| Home (`zernio.com`) | **0 de cada uno** (texto completo extraído, 7.926 caracteres) | [P] 2026-07-30 |
| `zernio.com/social-media-api` | **0** | [P] 2026-07-30 |
| ~~Doc de API completa~~ **Doc de API PARCIAL** (`zernio.com/llms.txt`, 25 KB) | **0** — la única palabra de esa familia es *"official Cloud API"* referido a WhatsApp | [P] 2026-07-30, **superseded por la fila de abajo** |
| **Doc de API COMPLETA** (`docs.zernio.com/llms-full.txt`, **3.627.443 bytes**) | **0** de `Tech Provider`, `Solution Partner`, `Business Partner`, `Marketing Partner`, `approved Meta`, `official partner`. Los 77 hits de `partner` **no son ninguna declaración de partnership de plataforma** — ver desglose abajo | **[P] 2026-07-30, re-ejecutado y verificado independientemente por mí sobre el corpus** |
| `docs.zernio.com/platforms/whatsapp` | **0**. No se declara Tech Provider ni BSP; solo pide al usuario *"A Meta Business account"* + *"WhatsApp Business Account"* | [P] 2026-07-30 |

> **CICLO DE CORRECCIÓN CERRADO (2026-07-30) — la afirmación se restaura MÁS FUERTE de lo que estaba.** Se registra el ciclo completo, no solo el resultado, porque el método es el que da confianza en el número.
>
> **(1) Lo que estaba mal.** La fila original contaba ocurrencias sobre `zernio.com/llms.txt` (25 KB) y lo etiquetaba *"doc de API completa"*. La doc real es de **3,6 MB**: conté ceros sobre **menos del 1 % del corpus** y lo presenté como exhaustivo. Error mío de etiquetado. Lo detecté yo al integrar la corrección de fuente del `architect` y lo retiré antes de que nadie lo citara.
>
> **(2) Re-ejecución.** El `architect` conservaba el corpus y re-corrió el conteo; yo lo **verifiqué independientemente sobre el mismo fichero** en vez de aceptar sus cifras, porque la afirmación va en mi documento. Coincidencia exacta en los tres conteos crudos (`partner` 77, `badge` 17, `certified` 3) y en el tamaño (3.627.443 bytes). **Los seis términos de partnership dan 0.**
>
> **(3) Desglose de los 77 hits — con DOS errores de método corregidos por el camino, ambos de la misma clase.** Se registran los dos, porque el patrón es más instructivo que el número.
>
> - **Error 1 (mío):** contar sobre 25 KB y etiquetarlo *"doc completa"*.
> - **Error 2 (del `architect`, que él mismo nombró):** al re-contar, usó `grep -oiE ".{70}partner.{70}"`. Ese regex **exige 70 caracteres de contexto a ambos lados**, así que **descartó en silencio** toda ocurrencia cerca de un salto de línea o dentro de un enum compacto — sin error, sin aviso. Sobrevivieron 2, y los reportó como *"colapsan en exactamente 2 contextos únicos"*. **Es exactamente mi mismo fallo —concluir sobre un subconjunto filtrado en silencio y describirlo como exhaustivo— cometido mientras corregía el mío.**
>
> **La forma robusta no es un grep de contexto sino un censo de tokens**, sin ventana que pueda recortar:
>
> ```
> grep -oiE "[A-Za-z_.]*partner[A-Za-z_.]*" llms-full.txt | sort | uniq -c | sort -rn
> ```
>
> **Censo verificado por mí sobre el corpus (suma exacta: 77):**
>
> | Nº | Token | Familia |
> |---|---|---|
> | 16 | `partnership` | etiqueta de contenido pagado |
> | 16 | `partner` (suelto) | programa de afiliados propio + prosa de scopes de Meta |
> | 10 | `brandPartnerPromote` | **campo de API de Meta/IG** |
> | **8** | **`VETTED_PARTNER`** | **enum de Google — ver aviso abajo** |
> | 6 | `Partner` | programa de afiliados (término definido de su acuerdo) |
> | 5 | `paidPartnership` | etiqueta de contenido de marca de IG |
> | 4 | `Partners` | programa de afiliados propio |
> | 3 | `llaPartnerConversion` | **campo de API de Meta** |
> | 2 | `brandpartner` | campo de Meta/IG |
> | **2** | **`GOOGLE_SEARCH_AND_PARTNERS`** | **enum de Google Ads** |
> | 1 c/u | `platformSpecificData.paidPartnership`, `partners.dub.co`, `partners`, `partnerApiLeadGenFormResponse`, `brand_partner_promote` | mixto |
>
> **Las cuatro familias se sostienen, con una corrección de tamaño: la familia de identificadores ajenos es de ~24 de 77, no ~14** — ni él ni yo habíamos contado `VETTED_PARTNER` (8) ni `GOOGLE_SEARCH_AND_PARTNERS` (2).
>
> > ⚠ **AVISO AL AUDITOR — `VETTED_PARTNER` parece una declaración de partnership y NO lo es.** Es un valor del enum de **método de verificación** de Google Business Profile. Verificado por mí en el corpus: aparece en campos `method` y `verificationMethod` con la firma literal **`one of: ADDRESS, EMAIL, PHONE_CALL, SMS, AUTO, VETTED_PARTNER`** (líneas 37931, 39206, 40357, 40412 y otras — 8 esquemas). Es **vocabulario de Google** para cómo se verifica la ficha de un negocio. Igualmente `GOOGLE_SEARCH_AND_PARTNERS` es un enum de **red de segmentación** de Google Ads (`one of: GOOGLE_SEARCH, GOOGLE_SEARCH_AND_PARTNERS`). **Ninguno es Zernio diciendo nada sobre sí mismo.** Se nombran y se desactivan aquí para que un lector que los encuentre no concluya que la fila se hizo a la ligera.
>
> **Afirmación restaurada, ahora sí airtight:** **cero declaraciones de partnership de plataforma en los 3.627.443 bytes de documentación técnica de Zernio.** Los seis términos de partnership dan 0, y **los 77 hits de `partner` están íntegramente contabilizados por familia**, incluidos los dos tokens de aspecto más alarmante, que son valores de enum de Google.
>
> **(4) La frontera de alcance que hace esto interesante, y es del `architect`.** Este corpus es su **documentación de API**, no su blog ni su marketing. El hallazgo `[S]` de §9.2 —el blog diciendo *"Zernio is an approved Meta Marketing Partner"*— **vive fuera de este corpus, así que los dos no se contradicen.** El patrón es la asimetría: **la afirmación fuerte de partnership aparece solo en marketing y ni una vez en la documentación técnica.** Bajo mi propia regla de fuentes (el blog de un vendor no es evidencia sobre su propio modelo de acceso; su doc técnica sí), **esa asimetría es el hallazgo**, y es más fuerte que un cero pelado.
>
> **(5) Reproducibilidad — y no uses un grep de contexto, que es la trampa en la que caímos.** El corpus vivía en un scratchpad de sesión y **es efímero: no asumir que existe**. Para re-verificar desde cero:
>
> ```bash
> curl -s https://docs.zernio.com/llms-full.txt -o z.txt
> wc -c z.txt   # esperado 3.627.443 bytes al 2026-07-30
> for t in "Tech Provider" "Solution Partner" "Business Partner" \
>          "Marketing Partner" "approved Meta" "official partner"; do
>   printf '%-20s %s\n' "$t" "$(grep -oi "$t" z.txt | wc -l)"   # los seis deben dar 0
> done
> grep -oiE "[A-Za-z_.]*partner[A-Za-z_.]*" z.txt | sort | uniq -c | sort -rn  # censo; suma 77
> ```
>
> **No sustituir el censo por `grep -oE ".{N}partner.{N}"`**: esa forma descarta en silencio las ocurrencias sin N caracteres de contexto a ambos lados y produce un subconjunto que *parece* exhaustivo. Es literalmente el defecto que generó los errores 1 y 2 de arriba.

**La única declaración de partner que existe** *(en las superficies que sí revisé)* está en una FAQ **de su propio blog**, y es de ads:

> *"Can you run social ads through an API without creating a Meta app? Yes. **Zernio is an approved Meta Marketing Partner**, so its Ads API lets you create, pause, edit, and delete Meta campaigns."*
> — [S] [zernio.com/blog/top-12-social-media-apis-for-developers](https://zernio.com/blog/top-12-social-media-apis-for-developers), accedido 2026-07-30

Tres precisiones que hacen esa frase menos relevante de lo que parece:

1. Es **[S] por la regla de fuentes de este doc** (blog propio, en un artículo de comparación donde Zernio se posiciona contra las APIs nativas). No es prueba de pertenencia.
2. Dice **Meta *Marketing* Partner**, que es el programa de **publicidad**. No dice Tech Provider, ni Business Partner con especialidad de plataforma, y **no cubre publicación ni mensajería** — que es el régimen que interesa a Qualify.
3. La afirmación que la acompaña (*"without creating a Meta app"*) es sobre el **Patrón 1** ya establecido en §3, no sobre partnership.

**La lista amplia — *"partner oficial de Meta, TikTok, LinkedIn, Pinterest y X"*, con 532.000 posts/semana, 11.000 cuentas conectadas y ClickUp / RE-MAX / Warner Music como clientes — no sale de Zernio.** Aparece en una reseña de tercero ([S] [mintavocado.com](https://mintavocado.com/en/zernio-api-reseaux-sociaux-solopreneur-en/), accedida 2026-07-30, formato afiliado/review). **No la traslado como afirmación de Zernio** y no la verifiqué. Es el mecanismo de amplificación que la nota de fuentes de `fase0-zernio-mercado.md` ya advertía: la afirmación fuerte no la hace el vendor, la hace quien lo reseña.

**Dato adyacente del mismo blog, relevante para §6 y que sí es coherente con todo lo demás:** Zernio describe su propio onboarding como *"**No app review, no approval process, no demo call.** First 2 accounts are free immediately"* [S, 2026-07-30]. Es decir, lo que Zernio vende explícitamente **es la ausencia de trámite para su cliente** — el piso 2 de `ingenieria-inversa-manychat.md` §2.2 — no un status de partner.

### 9.2 Meta: qué programas existen y qué conceden

#### Meta Business Partners (antes Facebook Marketing Partners)

Fuente primaria del programa: [P] [Meta Business Partner Program Policies](https://www.facebook.com/business/marketing-partners/become-a-partner/fmp-product-policies), accedida 2026-07-30.

Lo que la página de políticas **sí** dice:

- **Requisito de entrada explícito, y es el único que enuncia:** *"Todos los participantes del Programa deben tener un **negocio verificado**"*.
- El cuerpo del documento es de **obligaciones y restricciones**, no de beneficios: cumplimiento de políticas y leyes locales, **restricciones de uso del badge y del logo**, confidencialidad, mantenimiento de la verificación de negocio.
- El **único beneficio tangible** que enumera son los *Advertiser Rewards* (créditos de publicidad, que caducan a los 90 días y **pertenecen al cliente final, no al partner**).
- Existe un **directorio** (Meta Business Partner Directory) donde los partners con badge quedan listados y son localizables por región.

Lo que la página de políticas **no** menciona, en absoluto: **App Review, niveles de acceso, permisos, cuotas de API, o tipos de token.** Registro esta ausencia como ausencia, no como prohibición — la lectura es del architect (§9.6).

**Requisitos numéricos: solo [S], y los marco como hipótesis.** Varias guías de agencias citan ~**$1M+ de gasto publicitario anual gestionado**, **2+ especialistas certificados en Blueprint**, Business Manager en buen estado, y **4–12 semanas de revisión**, con re-evaluación cada ~6 meses ([S] [seo-stuff](https://www.seo-stuff.com/blog/how-to-get-meta-business-partner-badge-2026-guide), [S] [graphed.com](https://www.graphed.com/blog/how-to-become-a-meta-business-partner), accedidas 2026-07-30). **La doc primaria de Meta que consulté no publica ninguna cifra**, así que el umbral concreto es **hipótesis [S] no verificada**. Lo que sí es primario es la dirección: hay un requisito de negocio verificado, y el programa se orienta a gasto publicitario.

> **Obstáculo de verificación, y es un hallazgo en sí mismo.** El directorio de partners de Meta (`facebook.com/business/partner-directory/search`) **exige iniciar sesión**: devuelve HTTP 200 con *"Debes iniciar sesión para continuar"* (verificado 2026-07-30 con user-agent de navegador). **Consecuencia práctica: un comprador no puede verificar de forma independiente y anónima la afirmación de partner de ningún vendor.** Eso explica estructuralmente por qué la autodeclaración funciona en esta categoría — y por qué §9.4 y §9.5 quedan parcialmente abiertas.

#### Meta Tech Provider (WhatsApp) — el único programa de los examinados que **sí** es técnico

Y precisamente por serlo, es el que responde la pregunta del fundador. Fuente primaria: [P] [Meta: Get Started for Tech Providers](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers), accedida 2026-07-30.

**Qué concede — capacidad técnica real, no un logo:**

- *"**Advanced access to `whatsapp_business_messaging`**"* — *"required to send messages on behalf of your clients"*.
- *"**Advanced access to `whatsapp_business_management`**"* — *"required to access your clients' WABAs"*.
- Un Tech Provider *"can independently provide all WhatsApp messaging services to clients who you have onboarded"*.

**Qué exige para entrar — y aquí está el punto entero:**

1. *"A Meta app with the WhatsApp use case and a connected business portfolio"*.
2. *"**Verify your business with Meta**"*.
3. Pasar **App Review** con aprobación de permisos avanzados.

Y la frase que ordena la secuencia, literal: *"**Your business must be verified before you can start the app review process.**"*

**Lectura factual, no interpretativa: el status de Tech Provider es el resultado de haber pasado App Review + Business Verification, no un sustituto de ellos.** No los reemplaza, no los acelera y no exime de ellos — los **presupone**. Es el output del trámite, no un atajo hacia él.

### 9.3 TikTok: qué programas existen

TikTok tiene **al menos dos programas distintos y solapados**, y la distinción importa porque solo uno tiene lista pública:

| Programa | Qué es | Verificable | Qué concede |
|---|---|---|---|
| **TikTok Marketing Partners** | Programa de **badge**, orientado a publicidad. Categoría *Agency* confirmada en fuente primaria; [S] añade Campaign Management, Creative, Measurement, Commerce, Effects y Sound | Hay web de Marketing Partners, pero `ads.tiktok.com/marketing-partners/en` redirige (301) a `partners.tiktok.com/en`, que devuelve **404** (2026-07-30) | *"Badged **Agency** partners are able to leverage both media and creative solutions to maximize advertiser success on TikTok"*; *"proven TikTok expertise"*. **Nada sobre acceso a API, niveles de acceso ni auditorías** |
| **TikTok Messaging Partners** | Programa **cerrado** de mensajería, con lista nominal publicada | **Sí — lista pública** | La página no explica cómo se entra ni qué concede; solo que *"The use of any Messaging Partners is governed by its respective Terms and Policies"* |

Fuentes: [P] [TikTok For Business: Introducing Our Badged TikTok Agency Partners](https://ads.tiktok.com/business/en/blog/badged-agency-marketing-partners) y [P] [About message management tools](https://ads.tiktok.com/help/article/about-message-management-tools), ambas accedidas 2026-07-30. Requisitos numéricos de entrada: **TikTok no los publica en la fuente primaria**; las guías [S] ([stackmatix](https://www.stackmatix.com/blog/tiktok-partner-program-guide), 2026-07-30) hablan de "performance and competency thresholds" sin cifras. **Queda pendiente.**

Nótese que las categorías del programa de badge son **todas de publicidad y creatividad**. Ninguna corresponde a publicación orgánica ni a la Content Posting API — que es lo que gatea la auditoría que a Qualify le afecta.

### 9.4 Verificación de pertenencia: Zernio

| Directorio | Resultado | Fecha |
|---|---|---|
| **TikTok Messaging Partners** (lista pública nominal) | **Zernio NO aparece.** Los nueve nombres son Blip.ai, Halosis, Haravan, Pancake, Qiscus, respond.io, Zwiz, Gupshup, Infobip | [P] 2026-07-30 |
| **Meta Business Partner Directory** | **No verificable** — exige login | [P] 2026-07-30 |
| **TikTok Marketing Partners** (directorio) | **No verificable** — `partners.tiktok.com/en` devuelve 404 | [P] 2026-07-30 |

**Conclusión honesta y acotada:** la única afirmación de partner que Zernio hace es *"approved Meta Marketing Partner"*, en su propio blog, referida a **ads** — y **no la pude confirmar ni desmentir**, porque el directorio que la confirmaría está tras login. Lo que **sí** está verificado es lo que Zernio **no** afirma: no se declara Tech Provider, ni partner de mensajería, ni partner de publicación, en ninguna de sus superficies técnicas. Y no está en la única lista pública de TikTok que existe.

**Y esto es lo relevante para Qualify:** el acceso de Zernio a publicación y mensajería de IG (§3.2) y a `video.publish` con `PUBLIC_TO_EVERYONE` en TikTok (§3.3) está probado por su documentación técnica **sin depender de ningún status de partner**. Es coherente con la §9.2: pasó App Review y la auditoría de TikTok. El partnership de ads, exista o no, es ortogonal.

### 9.5 Verificación de pertenencia: ManyChat — cierra el pendiente #3

| Directorio | Resultado | Fecha |
|---|---|---|
| **TikTok Messaging Partners** | **ManyChat NO aparece** — re-verificado hoy, misma lista de nueve nombres que el 2026-07-23 | [P] 2026-07-30 |
| **Meta Business Partner Directory** | **No verificable** — exige login | [P] 2026-07-30 |

Su afirmación *"Como **Meta Business Partner** oficiales, nos reunimos con su equipo de productos semanalmente"* sigue siendo **autodeclaración en su propio help center** [P para el hecho de que lo afirma; **no** para el hecho de que sea cierto]. **Pendiente #3 se cierra así: no confirmado ni desmentido, con el obstáculo identificado y nombrado** (directorio tras login), que es un resultado distinto y mejor que "no verificado".

**La anomalía de TikTok persiste y ahora está re-confirmada:** ManyChat **integra TikTok DM en producción** (documentado en su help center, `ingenieria-inversa-manychat.md` §2.4) y **no está en la lista de Messaging Partners de TikTok**, una semana después de la primera comprobación. Lecturas posibles, sin decidir entre ellas: la lista está incompleta o desactualizada, o hay más de un programa de mensajería en TikTok, o el acceso de ManyChat viene por otra vía. **No lo resuelvo — requiere contacto directo con TikTok.** Lo que sí concluyo es de método: **la ausencia de un vendor en una lista oficial no prueba que no tenga el acceso**, igual que su presencia en un blog propio no prueba que lo tenga. Los directorios de esta categoría son evidencia débil en las dos direcciones.

### 9.6 ¿Altera algún programa el régimen de acceso? — transcripción para `principal-architect`

**Sin interpretar**, por la misma regla de §7. Los tres textos que tocan la pregunta:

> [P] **Meta, Tech Provider** (2026-07-30): *"Your business must be verified before you can start the app review process."* Y las capacidades concedidas: *"Advanced access to `whatsapp_business_messaging`"*, *"Advanced access to `whatsapp_business_management`"*.
>
> [P] **Meta, Business Partner Program Policies** (2026-07-30): *"Todos los participantes del Programa deben tener un negocio verificado."* El documento **no menciona** App Review, niveles de acceso, permisos, cuotas ni tipos de token; su contenido son obligaciones, restricciones de uso de badge/logo, confidencialidad y *Advertiser Rewards*.
>
> [P] **TikTok, badged Agency partners** (2026-07-30): *"Badged Agency partners are able to leverage both media and creative solutions to maximize advertiser success on TikTok."* **Ninguna mención de acceso a API, niveles de acceso ni auditorías.**

**Registro de ausencias como ausencias:** en ninguna de las tres fuentes primarias encontré texto que conceda, sustituya, acelere o exima App Review, Business Verification o niveles de acceso **en virtud del status de partner**. Eso es lo que las fuentes no dicen; qué se sigue de ello es del architect.

### 9.7 La pregunta del fundador: ¿el requisito de entrada es más caro que el App Review que evitaría?

**Sí, y en el caso de Tech Provider la relación no es "más caro" sino de contención: el requisito de entrada *incluye* el App Review.**

| Programa | Requisito de entrada | ¿Podría ser un atajo al App Review? |
|---|---|---|
| **Meta Tech Provider** (WhatsApp) | Business Verification **+ App Review con permisos avanzados**, en ese orden obligatorio | **No — lo contiene.** Es imposible usarlo para evitar lo que exige tener hecho |
| **Meta Business Partners** | Negocio verificado [P]. Además, hipótesis [S] no verificada: ~$1M+ de gasto publicitario anual, 2+ certificados Blueprint, 4–12 semanas de revisión, re-evaluación cada ~6 meses | **No.** Exige Business Verification, que es la mitad del trámite que se querría evitar. Y su beneficio documentado es badge/directorio/créditos, no acceso |
| **TikTok Marketing Partners** | No publicado en fuente primaria; [S] habla de umbrales de rendimiento | **No, por objeto:** las categorías son de publicidad/creatividad, no de la Content Posting API que impone la auditoría |
| **TikTok Messaging Partners** | No publicado. Programa cerrado, 9 nombres | **Indeterminado, e inaccesible:** sin proceso público de solicitud, no es una vía que Qualify pueda intentar |

**La respuesta al fundador, en la forma que pidió el encargo — sin suavizar:**

**Ser partner no desbloquea nada técnico, con una única excepción que no ayuda.** De los cuatro programas examinados, tres son **badge/marketing**: conceden un logo, una ficha en un directorio y, en Meta, créditos publicitarios que además pertenecen al cliente final. Ninguno menciona acceso, permisos ni cuotas. El cuarto — **Meta Tech Provider** — sí concede acceso avanzado real a los scopes de WhatsApp, y por eso mismo **exige App Review y Business Verification como prerrequisitos literales**.

Formulado como la regla que cierra la pregunta de raíz: **el status de partner es una consecuencia de haber escalado, no un atajo para escalar.** Los requisitos que se conocen (entidad verificada, gasto publicitario, historial, App Review aprobado) son todos cosas que solo existen *después* del trámite. No hay ningún programa cuyo camino sea "hazte partner y así te ahorras la revisión"; el camino real es el inverso: **pasa la revisión y entonces podrás optar al badge.**

**Corolario operativo para el expediente:** cualquier plan de Qualify que incluyera "solicitar partnership" como paso previo a obtener acceso está mal ordenado y hay que reordenarlo, no reprogramarlo. Y el marketing de partner de un competidor **no es evidencia de que tenga un acceso que Qualify no pueda obtener** — es evidencia de que ya pasó el mismo trámite que Qualify tiene por delante. Eso encaja con §6 y no la modifica.

### 9.8 Pendientes nuevos de §9

| # | Pendiente | Por qué no se cerró | Cómo se cierra |
|---|---|---|---|
| 8 | Pertenencia real de **Zernio** y **ManyChat** al Meta Business Partner Directory | El directorio **exige login** (verificado 2026-07-30) | Buscar en el directorio con una cuenta de Facebook. Es una comprobación de minutos para el fundador |

**Precisión sobre el estado del #8, acordada con el `principal-architect` 2026-07-30.** La etiqueta exacta no es "no verificable" a secas, sino **"no verificable anónimamente; comprobable con cuenta autenticada, y nadie lo ha hecho todavía"**. Y hay que separar dos cosas que se confunden fácil:

- **Para nosotros** es un pendiente trivial: el fundador lo cierra en minutos con su cuenta.
- **Para un comprador es un hallazgo de mercado por derecho propio, y es el que importa.** Que la afirmación de partner de un proveedor **no se pueda comprobar sin loguearse en Facebook** significa que, en la práctica, en esta categoría el badge funciona como una afirmación de marketing no auditada: quien evalúa vendors —el perfil que compraría Qualify— no tiene forma anónima de distinguir un partner real de una autodeclaración. Eso es independiente de que nosotros sí podamos comprobarlo, y es la razón estructural por la que §9.1 encontró que la afirmación fuerte la amplifica el reseñador y no el vendor.
| 9 | Requisitos numéricos de entrada al **Meta Business Partner** program | La doc primaria de políticas no publica cifras; el ~$1M+ de gasto es **[S] no verificado** | Formulario de solicitud del programa, o contacto con Meta |
| 10 | Requisitos y directorio de **TikTok Marketing Partners** | `partners.tiktok.com/en` devuelve **404** y `ads.tiktok.com/marketing-partners/en` redirige ahí (2026-07-30) | Localizar la URL vigente del directorio; puede haber cambiado de dominio |
| 11 | Por qué **ManyChat integra TikTok DM sin estar en Messaging Partners** | Anomalía re-confirmada a una semana. Tres explicaciones posibles, ninguna verificable por desktop research | Contacto directo con TikTok o con ManyChat |
| 12 | Si existe un programa de partner de Meta para **publicación/mensajería orgánica** (no ads, no WhatsApp) | No encontré ninguno en esta pasada. **Ausencia de evidencia, no evidencia de ausencia** | Barrido del árbol de programas de partner de Meta |

---

## 10. Evidencia documental para V-TP-7 — **transcripción, no resolución**

**Contexto:** el `principal-architect` abrió **V-TP-7** al recibir §9: si *"Tech Providers only"* (la restricción de la fila BISU en `reference/meta-instagram-platform/documentation/facebook-login/facebook-login-for-business.md:153`) designa una titularidad que solo se concede tras App Review + Business Verification, su *etapa 0-bis* de ADR 29 §10.3 no existe. Señaló, con razón, que mi fuente de §9.2 es del vertical **WhatsApp** y la suya de **Facebook Login for Business**, y que no se contradicen literalmente.

Buscando en el corpus local de doc de Meta (`reference/meta-instagram-platform/`) encontré **dos textos que tiran en direcciones opuestas** sobre exactamente esa pregunta. Los transcribo y **no elijo entre ellos** — la lectura es del architect. Ninguno es una fuente nueva que yo haya traído de la web: son del corpus que ya está en el repo, y por lo que veo no se habían cruzado entre sí.

### 10.1 Texto que apunta a "categoría autodeclarada", no a status concedido

De `reference/meta-instagram-platform/documentation/resp-plat-initiatives/data-access-renewal/content/data-protection-section.md` — el cuestionario de **Data Protection Assessment / Data Access Renewal**, líneas 293-301 y 378-382:

> *"**Tech Provider definition:** An individual or business that has been granted access to Meta APIs for the purpose of creating, maintaining and removing integrations on behalf of other individuals or businesses. This includes individuals or businesses that create **a single integration on behalf of an individual client** or multiple clients."*
>
> *"Because this app allows people or businesses (clients) to access and use Platform Data, **it means that you are a Tech Provider**."* (línea 301)
>
> *"**You indicated above** that this app allows people or businesses (clients) to access and use Platform Data. **This means that you are a Tech Provider**."* (línea 382)
>
> *"Developers of apps whose primary purpose is to manage Platform integrations on behalf of customers or clients… Examples of Tech Providers include **SaaS providers and agencies**."*

**Lo que es factualmente observable en estas tres frases, sin interpretarlas:** la determinación de que alguien "es Tech Provider" se **deriva de la respuesta que el propio desarrollador dio** en un cuestionario de cumplimiento (*"you indicated above… this means that you are"*), y el contexto es un **assessment de protección de datos**, no una solicitud de programa ni una revisión con aprobación. La forma gramatical es declarativa, no concesiva.

### 10.2 Texto que apunta a que el gate depende del **escenario**, y que deja un hueco justo donde está el cliente uno

De `reference/meta-instagram-platform/documentation/instagram-platform/app-review.md`, líneas 11-16 — la tabla completa de *"Development scenarios"*, sin filas omitidas:

| Development scenario | Login type | Access level | App Review |
|---|---|---|---|
| My app is only for a business I own or manage. | No login **or Instagram Login** | Standard Access | **Not required** |
| My app is only for a business I own or manage. | No login **or Facebook Login** | Standard Access | **Not required** |
| I am a Tech Provider and my app serves **multiple businesses**. | Instagram Login | Advanced Access | **Required** |
| I am a Tech Provider and my app serves **multiple businesses**. | Facebook Login | Advanced Access | **Required** |

Tres observaciones factuales sobre esta tabla:

1. **La exención de App Review aparece para las dos ramas de login** (Instagram Login y Facebook Login), no solo para una. Es decir, la asimetría entre ramas de ADR 25 no se manifiesta en esta tabla.
2. **El gate de App Review está redactado sobre el escenario — *"serves multiple businesses"* — no sobre la etiqueta *Tech Provider* a secas.** La etiqueta y el plural aparecen juntos en la misma fila.
3. **No existe fila para "soy Tech Provider y mi app sirve a un solo cliente".** La taxonomía de Meta en este documento es binaria: *"un negocio que poseo o gestiono"* frente a *"Tech Provider con múltiples negocios"*. **El cliente uno de Qualify no encaja en ninguna de las dos**: es un negocio que el fundador **no** posee ni gestiona, y es **un** cliente, no varios.

**Y aquí está la tensión que no resuelvo:** la *definición* de Tech Provider (§10.1) incluye explícitamente *"a single integration on behalf of an individual client"*, mientras que la *tabla de escenarios* (§10.2) solo dispara `App Review: Required` para *"multiple businesses"*. Los dos textos son de Meta, están los dos en el corpus, y **no dicen lo mismo sobre el caso de un cliente único**. Cuál gobierna es precisamente V-TP-7 y es del architect.

### 10.3 Dato colateral que apoya que el acceso estándar funciona antes de la revisión

`app-review.md:85`, entre los requisitos para *enviar* a App Review:

> *"To request Advanced Access to certain permissions, you need to make **at least 1 successful API call**."*

**Observación factual:** el flujo de App Review presupone que la app ya hizo llamadas API con éxito **antes** de la revisión. No deduzco de aquí nada sobre BISU.

### 10.4 Aviso operativo: la trampa de las cuatro grafías del scope de publicación, con un caso concreto

`CLAUDE.md` advierte que el scope de publicación tiene **cuatro grafías en circulación** y que nunca hay que hardcodear una desde documentación. Encontré un caso concreto que conviene tener registrado, porque las dos fuentes son buenas:

| Fuente | Grafía |
|---|---|
| Corpus local de Meta, `app-review.md:49` | `instagram_business_content_publishing` |
| Doc de Zernio (producto en producción), §3.2 de este doc | `instagram_business_content_publish` |

**No sé cuál es la vigente y no lo resuelvo aquí** — es exactamente el caso que `CLAUDE.md` manda resolver empíricamente contra el endpoint de autorización, no contra documentación. Lo registro para que la discrepancia no se descubra en runtime. Nótese que el corpus local usa además `instagram_content_publishing` (rama Facebook Login, línea 35), lo que hace **tres** grafías observadas entre estas dos fuentes.

---

## Anexo — trazabilidad

- Docs relacionados: `docs/ingenieria-inversa-manychat.md` §2.2 (coste de dos pisos), `docs/fase0-zernio-mercado.md` §1.1-bis y §2.2 (plazos y precio de Zernio), `docs/integracion-cuentas-conectadas-meta.md` §3.1 (la exención de "rol en la app").
- Hallazgo enviado a `principal-architect` y persistido en `.claude/sprint-state-2026-07-29-modelo-acceso.md` (2026-07-29).
- Este doc **no** modifica `docs/arquitectura.md` ni `CLAUDE.md`; el ADR sobre esta pregunta es del `principal-architect`.

