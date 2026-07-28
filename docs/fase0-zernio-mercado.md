# Fase 0 (modelo Zernio) — Investigación de mercado y viabilidad

**Estado:** investigación de soporte para **ADR 19 (PROPUESTO)** — ver `docs/arquitectura.md` §"Nota de soporte de ADR 19".
**Pregunta que responde:** ¿es viable, y en qué plazo real, un MVP de API de publicación/scheduling social (auth unificada + un solo request sobre 15+ plataformas, MCP server, precio por cuenta conectada) como fuente de ingreso rápido antes de completar la Fase 1?
**Método:** investigación de escritorio con web en vivo, 2026-07-20/21. Todas las fechas de acceso son 2026-07-21 salvo indicación contraria.
**Autor:** agente `gtm`.

## Nota de calidad de fuentes (leer antes que las tablas)

La mayor parte del contenido indexable sobre "APIs de publicación social" en 2026 es **marketing de contenidos de los propios competidores** (Blotato, Postproxy, PostPeer, Netrows, SocialCrawl y el propio Zernio publican guías de "API pricing 2026"). Tienen incentivo directo en exagerar la fricción de la integración nativa, porque su producto es precisamente evitarla. Clasifico las fuentes:

- **[P] Primaria** — documentación oficial de la plataforma o página de precios del vendor. Es la única evidencia con la que hago afirmaciones fuertes.
- **[S] Secundaria interesada** — blog de un competidor/agregador. Útil para pistas y para saber qué buscar; **nunca** suficiente por sí sola. Toda cifra que sólo aparezca en [S] va etiquetada como hipótesis.
- **[T] Terciaria neutral** — comparativas o reportes de desarrolladores sin producto en juego.

Donde una cifra crítica sólo tiene respaldo [S], lo digo explícitamente en la fila.

---

## 1. Realidad del acceso a APIs de publicación (Tarea 1 — la que decide la estrategia)

### 1.1 Tabla plataforma → vía de acceso → tiempo hasta producción → requisito bloqueante

| Plataforma | Vía de acceso a publicación | Tiempo realista hasta poder publicar **público** para clientes terceros | Requisito bloqueante | Fuente |
|---|---|---|---|---|
| **TikTok** | Content Posting API, scope `video.publish` (Direct Post). Requiere añadir el producto a la app y **auditoría del cliente API** | **Semanas.** Reportes de desarrolladores: 5–10 días hábiles la auditoría *si* se aprueba a la primera; re-envío tras rechazo alarga [S]. La fase pre-auditoría es inmediata pero **inútil comercialmente** | **Hasta pasar auditoría, todo contenido se publica en `SELF_ONLY` (privado) y sólo 5 usuarios pueden publicar por ventana de 24 h.** La restricción es **server-side**: `privacy_level` debe coincidir con lo que devuelve `/v2/post/publish/creator_info/query/`, y a un cliente no auditado TikTok simplemente no le devuelve las opciones públicas. No hay forma de rodearlo | [P] [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) · [P] [Get Started](https://developers.tiktok.com/doc/content-posting-api-get-started) · [S] [PostPeer](https://www.postpeer.dev/blog/best-tiktok-posting-api) |
| **Instagram** (Business/Creator) | Graph API: contenedor `POST /{ig-user-id}/media` → `POST /{ig-user-id}/media_publish`. Scopes `instagram_basic` + `instagram_content_publish` | **4–8 semanas** en el caso realista (App Review 2–4 semanas *por envío* [S], más Business Verification en paralelo, más un ciclo de rechazo probable en el primer intento) | **Advanced Access exige App Review + Business Verification.** ~~Sin ellas, el tope es **25 usuarios de prueba**.~~ **[CORREGIDO 2026-07-24 — ver §1.1-bis]: la cifra de 25 no tiene respaldo primario; el límite real es cualitativo (*tener un rol en la app*), y la exención cambia la conclusión para cuentas propias.** Business Verification exige documentación de entidad legal (licencia de actividad / escritura / registro fiscal) con nombre legal, dirección y **NIF/CIF/VAT** coincidentes, más web activa que muestre el nombre legal. Además: sólo cuentas Business/Creator, vinculadas a una Página de Facebook | [P] [Meta: Instagram Platform Overview](https://developers.facebook.com/docs/instagram-platform/overview/) · [S] [Elfsight](https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/) · [S] [Meta verification docs](https://singhamandeep.com/meta-business-verification-documents-required/) |
| **Facebook Pages** | Misma app de Meta, mismo App Review + Business Verification | Igual que Instagram (mismo trámite, mismo envío) | Idéntico a Instagram | [P] Meta Developers |
| **Threads** | Threads API (Meta), gated por App Review | Igual que Instagram | Igual que Instagram | [S] [Blotato](https://www.blotato.com/blog/social-media-api) — **hipótesis**, no verificado contra doc primaria |
| **YouTube** | Data API v3, `videos.insert` | **Publicar: inmediato. Escalar: 1–2 semanas a meses.** Incrementos simples (50K–100K unidades) 1–2 semanas; peticiones grandes (1M+) 4–6 semanas y a veces videollamada; muchas se deniegan [S] | Cuota por defecto **10.000 unidades/día** y **100 `videos.insert`/día por proyecto** (no por usuario). Ampliar exige **auditoría de cumplimiento**. Nota importante: Google **bajó `videos.insert` de ~1.600 a ~100 unidades** el 2025-12-04 [S] — el techo real hoy lo marca el límite duro de 100 inserts/día, no las unidades | [P] [Quota and Compliance Audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) · [S] [Análisis de la auditoría](https://singhamandeep.com/youtube-data-api-quota-increase-audit/) |
| **LinkedIn — perfil personal** | `w_member_social` vía *Share on LinkedIn* | **Días.** Self-serve | Ninguno relevante. Ésta es la única vía LinkedIn realmente abierta | [P] [Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06) |
| **LinkedIn — páginas de empresa** | `w_organization_social` vía **Community Management API** | **Semanas-meses, y rechazable.** Dos tiers: toda app empieza en *Development*; hay que solicitar aparte el upgrade a *Standard* con **grabación de pantalla** de la app | Aprobación del programa Community Management **+ rol de admin de la página de empresa**. Además `r_member_social` (lectura) está **cerrado**: "no aceptamos solicitudes de acceso por restricciones de recursos" | [P] [Community Management Overview](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-06) · [P] Increasing Access |
| **X / Twitter** | API v2, modelo **pay-per-use por créditos** (confirmado en doc primaria: "pay only for what you use", créditos descontados por request) | **Inmediato**, sin revisión | **Sin bloqueo de aprobación, pero con bloqueo económico.** El tier gratuito está discontinuado. Precio reportado [S]: **$0,015 por post creado** ($0,20 si contiene enlace) y $0,005 por lectura. Los tiers legacy Basic ($200/mes) y Pro ($5.000/mes) están **cerrados a nuevas altas**. Enterprise ~$42.000/mes | [P] [About X API](https://docs.x.com/x-api/getting-started/about-x-api) · [S] precio exacto: [Postproxy](https://postproxy.dev/blog/x-api-pricing-2026/), [WeAreFounders](https://www.wearefounders.uk/the-x-api-price-hike-a-blow-to-indie-hackers/) — **el importe unitario es hipótesis [S]; la doc primaria confirma el modelo pero no publica la tarifa** |
| **Pinterest** | API v5, dos tiers: Trial → Standard | Standard requiere aprobación de Pinterest; plazo no publicado | Aprobación para Standard. Además, aviso operativo [S]: cuentas nuevas necesitan ~2 semanas de "warm-up" manual antes de conectarlas a herramientas de terceros o se dispara la detección de spam | [S] [Blotato Pinterest](https://www.blotato.com/blog/pinterest-api-pricing) · [S] [PostPeer](https://www.postpeer.dev/blog/how-to-post-on-pinterest-with-api) — **hipótesis** |
| **Bluesky** | AT Protocol, abierto | **Inmediato** | Ninguno. Límite ~5.000 puntos/hora [S] | [S] [Blotato Bluesky](https://www.blotato.com/blog/bluesky-api-pricing) |
| **Reddit / Telegram / Discord** | APIs abiertas con registro | **Inmediato** | Ninguno bloqueante para publicar (Reddit tiene tarifas para lectura a escala; publicar es otro caso) | No verificado en esta pasada — **pendiente** |
| **WhatsApp Business** | Cloud API vía Meta | Semanas | Business Verification de Meta **+** verificación del número + plantillas aprobadas. Modelo de precio por conversación | No verificado en esta pasada — **pendiente** |
| **Snapchat / Google Business Profile** | Programas de partner | No verificado | Probablemente partner-gated | **Pendiente** |

### 1.1-bis Corrección de la tabla §1.1 (architect, 2026-07-24) — fuente primaria

Dos filas de la tabla anterior se corrigen contra la documentación oficial, verificada en vivo el 2026-07-24. **Ninguna de las dos correcciones invalida el veredicto de §1.2 para el caso que §1.2 analiza** (vender publicación a **terceros**); ambas cambian la respuesta para un caso que §1.1 nunca costeó: **publicar en cuentas que el propio fundador administra**. El análisis completo está en `docs/integracion-cuentas-conectadas-meta.md` §3.

**(a) Instagram — el "tope de 25 usuarios de prueba" no está respaldado.** La doc de [Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels) **no menciona ningún límite numérico**. El límite real es cualitativo: *"Los permisos con acceso estándar solo se pueden solicitar a usuarios de la app que tengan **un rol en la app solicitante**"*, y *"se **aprueba automáticamente** el acceso estándar para todos los permisos"*. Encadenado con [App Modes](https://developers.facebook.com/docs/development/build-and-test/app-modes) y con [Business Verification](https://developers.facebook.com/docs/development/release/business-verification) — *"**If your app will only be used by app users who have a role on the app itself you do not need to complete verification**"* — resulta que una app usada sólo por titulares de rol **no necesita App Review ni Business Verification en absoluto**, y lo que publica son posts **públicos normales** (no existe en la doc de Meta ningún mecanismo por el que el nivel de acceso degrade la visibilidad). El reloj de 2–4 meses de §1.2 **no bloquea al fundador publicando en sus propias cuentas**; sigue bloqueando la venta a terceros.

**(b) TikTok — la restricción es peor de lo que registró §1.1, y falta la frase que decide.** Además del `SELF_ONLY` ya recogido, [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) dice: *"**All user accounts using the API client to post must be set to private at the time of posting.**"* No es que el post salga privado: **la cuenta entera debe estar en privado para publicar**. Y aplica *"regardless of account ownership"* — administrar la cuenta uno mismo **no** levanta la restricción. Para una cuenta de tienda eso significa apagar el escaparate para publicar en él. La conclusión de §1.2 sobre TikTok se refuerza, no se debilita.

**Matiz que hay que preservar:** lo bloqueado es **TikTok vía API**, no TikTok como canal. Publicar a mano sigue siendo posible. Cualquier roadmap debe decir *"publicación programada en TikTok"*, nunca *"TikTok"*.

### 1.2 Lectura estratégica — la respuesta a la pregunta que importa

**El architect tiene razón, y el dato de TikTok es peor de lo que la ADR 19 suponía.**

La ADR 19 formuló el riesgo #1 como "varias plataformas restringen la publicación a cuentas propiedad del desarrollador hasta pasar auditoría". La realidad verificada es más dura en dos aspectos concretos:

1. **TikTok no restringe a "cuentas propias" — restringe la *visibilidad del contenido publicado*.** Un cliente PYME conectaría su cuenta, programaría un post, la API devolvería éxito, y el post aparecería **en privado**, visible sólo para él. Desde el punto de vista del cliente eso no es "acceso limitado": es **el producto no funcionando**, con un fallo silencioso y confuso. Y el tope de **5 usuarios por 24 h** significa que ni siquiera se puede hacer una beta con 10 clientes.

2. **Meta es un trámite de entidad legal, no de código.** Business Verification exige documentación registral con nombre legal, dirección y número fiscal coincidentes, y web activa. Para un fundador en solitario sin sociedad constituida, **esto es un bloqueo previo al bloqueo**: hay que constituir/verificar la entidad antes de siquiera empezar el reloj de App Review.

**Consecuencia sobre la tesis "revenue rápido":**

Las plataformas que una PYME/B2C hispanohablante realmente pide son, en este orden: **Instagram, TikTok, Facebook**, y luego WhatsApp. Las tres primeras (más WhatsApp) son exactamente las que están detrás de App Review, Business Verification o auditoría. Las plataformas de acceso inmediato — **Bluesky, Telegram, Discord, LinkedIn personal, X (previo pago)** — son casi la lista exacta de plataformas que a una PYME local **no le importan**.

Formulado como regla: **la dificultad de acceso a la API correlaciona con el valor comercial de la plataforma.** No es coincidencia — el gating existe precisamente porque la plataforma es valiosa. Esto no admite una vía rápida por ingenio de ingeniería.

**Estimación de calendario hasta el primer euro cobrable** (posibilidad de publicar contenido **público** en IG + TikTok para un cliente que no sea el fundador):

| Hito | Plazo | Nota |
|---|---|---|
| Constituir/verificar entidad legal ante Meta | 1–4 semanas | Cero si ya existe sociedad con web y NIF; es el paso que más varía |
| Construir integración suficiente para grabar el screencast de App Review | 2–4 semanas | Meta exige demo funcional del caso de uso |
| App Review Meta (IG + FB + Threads en un envío) | 2–4 semanas por envío, **asumir 1 rechazo** → 4–8 semanas | [S] |
| Auditoría TikTok (en paralelo) | 1–3 semanas | [S] |
| **Total realista hasta vender a un tercero** | **~2–4 meses**, con riesgo de cola larga | Fuera de nuestro control y **rechazable** |

**Veredicto de la Tarea 1:** *"launch fast"* con IG/TikTok/FB es **estructuralmente falso**. Fase 0 no es un MVP de semanas: su ruta crítica es un **trámite administrativo de 2–4 meses** que no se acelera trabajando más horas, y cuyo resultado es binario y revocable. Cualquier plan financiero que asuma ingresos en el mes 1–2 con estas plataformas es inválido.

**Matiz importante que juega A FAVOR del pivote (y que la Tarea 2 debe resolver):** este calendario aplica a **construir los adapters nativos**. Si se compra un agregador, se opera **bajo la app ya auditada del agregador** y el reloj de aprobación desaparece casi por completo. Es decir: la Tarea 1 no mata Fase 0 — **mata la versión de Fase 0 que construye integraciones propias**, y convierte la decisión "comprar el fan-out" de preferencia arquitectónica (como la planteó el architect) en **condición de existencia del producto**. Todo depende entonces de si los términos del agregador permiten reventa, que es la Tarea 2.

---

## 2. Agregadores: precio, cobertura y — lo decisivo — derechos de reventa (Tarea 2)

### 2.1 Hallazgo previo que cambia el encuadre: **Zernio ES Late (getlate.dev)**

Múltiples fuentes [S/T] indican que **getlate.dev se renombró a Zernio y migró de dominio** ([Stackademic, mayo 2026](https://blog.stackademic.com/top-5-social-media-apis-for-developers-in-2026-aa8aa2981b28), [Postproxy](https://postproxy.dev/blog/best-social-media-scheduling-apis-compared/)). La página de precios actual de Zernio no menciona el nombre anterior (verificado 2026-07-21), así que lo trato como **muy probable pero no confirmado por fuente primaria**.

Importa por dos razones: (1) el "modelo a copiar" no es una empresa consolidada sino un **producto indie reciente que ya ha rebrandeado una vez**; (2) su precio (abajo) sugiere una guerra de precios a la baja, no un mercado con margen holgado.

### 2.2 Tabla comparativa

Precios verificados 2026-07-21 salvo indicación. "Reventa" = ¿los términos permiten vender el servicio a terceros bajo marca propia?

| Vendor | Precio | Cobertura | Open source | MCP | **Reventa / white-label** | Fuente |
|---|---|---|---|---|---|---|
| **Zernio** (el modelo) | **2 primeras cuentas gratis**; cuentas 3–10 **$6/mes** c/u; 11–100 **$3/mes**; 101+ **$1/mes**. Enterprise >2.000 cuentas | 12 redes (X, IG, TikTok, LinkedIn, FB, YouTube, Threads, Reddit, Pinterest, Bluesky, Snapchat, Google Business) + 3 mensajería (WhatsApp, Telegram, Discord) + 6 redes de Ads | No | **Sí** (mcp.zernio.com) | No verificado | [P] [zernio.com/pricing](https://zernio.com/pricing) |
| **Ayrshare** | Premium **$149/mes** (1 perfil) · Launch **$299/mes** (hasta 10) · Business **$599/mes** (30 incl.); overage 31–100 **$8,99**, 101–500 **$3,49**, 500+ **$2,49**/perfil/mes. Anual −17% ($7,99/$2,99/$1,99). Plan multi-usuario "desde $499/mes" | 13+ redes | No | No verificado | **⚠️ PROHIBIDA por los términos publicados** — ver §2.3 | [P] [pricing](https://www.ayrshare.com/pricing/) · [P] [terms](https://www.ayrshare.com/terms/) |
| **bundle.social** | **$100/mes, cuentas ilimitadas** + API | Unificada, orientada a devs | No | No verificado | **Permitida explícitamente** — se comercializa para "your own SaaS, client portal, AI tool, **reseller platform**, or internal system" | [S/P] [bundle.social](https://bundle.social/) |
| **Blotato** | Desde **$29/mes** (API sólo en planes de pago) | 9 plataformas | No | **Sí** (MCP hosted) | No verificado | [S] [Blotato blog](https://www.blotato.com/blog/best-social-media-api-tools) — **hipótesis** |
| **upload-post** | Free $0 (10 uploads/mes); pago desde **~$16/mes** (anual) | No verificado | No | No verificado | No verificado. Página de precios devolvió 404 en el intento directo | [S] [LinkStartAI](https://www.linkstartai.com/en/agents/upload-post) — **hipótesis** |
| **Publer** | $12/mes (3 cuentas); **API sólo desde el plan Business (~$21/mes)**; cuenta extra $4 (Professional) / $7 (Business) por mes | Amplia | No | No verificado | Producto de usuario final con API añadida; no orientado a reventa | [P] [Publer Help](https://publer.com/help/en/article/what-are-publers-plans-and-pricing-15h4yqh/) |
| **Postiz** (self-host) | **$0** de licencia; sólo coste de infra | Amplia | **Sí, AGPL-3.0** | No verificado | **Permitida por licencia**, con obligación fuerte: si modificas y lo ofreces por red como SaaS, **debes publicar tus modificaciones bajo AGPL-3.0** | [T] [FOSSA sobre AGPL](https://fossa.com/blog/open-source-software-licenses-101-agpl-license/) · [S] [autor de Postiz](https://dev.to/nevodavid/i-am-making-700-monthly-with-my-open-source-scheduling-tool-you-can-do-it-too-33o7) |

### 2.3 El hallazgo que el architect anticipó, confirmado: Ayrshare prohíbe exactamente lo que Fase 0 haría

Los Terms of Use de Ayrshare (verificado 2026-07-21) incluyen, bajo *"Access to the Site — Certain Restrictions"*, dos cláusulas literales:

> "no accessing the site to build a similar or competitive product"

> "no licensing, selling, renting, leasing, transferring, assigning, distributing, hosting, or otherwise commercially exploiting the site or its content"

**Lectura honesta, distinguiendo dos usos que no son iguales:**

- **Uso A — embeber Ayrshare dentro de un SaaS vertical** (p. ej. un CRM que además publica). Esto es **el caso de uso que Ayrshare comercializa activamente** ("Your SaaS platform has tons of great content ideal to be shared on social", plan Business para multi-usuario). Aquí las cláusulas son boilerplate anti-scraping/anti-clonado y no aplican en espíritu.
- **Uso B — vender una API de publicación a desarrolladores, con Ayrshare por debajo.** Esto **es** literalmente "build a similar or competitive product" y "commercially exploiting the site". No hay lectura benévola: la mitad del producto que propone el fundador (*vender a desarrolladores y a constructores de agentes*) es, sobre Ayrshare, una violación directa de sus términos.

**Consecuencia:** el fundador propuso **dos** motores de venta — (1) developers/agentes vía API+MCP y (2) PYMES/B2C vía UI. Sobre un agregador restrictivo, **sólo el motor (2) sobrevive**. El motor (1), que era el que justificaba el ángulo "API + MCP + Skills", queda inviable salvo que se elija un proveedor permisivo.

**Proveedores donde el motor (1) sí es viable:** `bundle.social` (comercializa explícitamente "reseller platform") y `Postiz` self-host (AGPL lo permite, con obligación de publicar modificaciones).

### 2.4 Advertencia crítica: Postiz self-host **no** resuelve el problema de la Tarea 1

Es el error de razonamiento más caro disponible aquí, y conviene decirlo explícito: **un agregador open-source auto-hospedado no te presta su aprobación de plataforma.** Postiz es código; las credenciales de app las pones tú. Al auto-hospedar, **vuelves a necesitar tu propia App Review de Meta, tu propia auditoría de TikTok y tu propia cuota de YouTube** — todo el calendario de 2–4 meses de la §1.2 regresa intacto.

El valor real que compra un agregador **hospedado** (Ayrshare, Zernio, bundle.social, Blotato) no es principalmente el código de los adapters: es **operar bajo su app ya auditada**. Ayrshare lo confirma — sus clientes no necesitan claves ni aprobaciones propias de las redes; los usuarios finales conectan sus cuentas por una página de conexión white-label con JWT ([Ayrshare docs](https://www.ayrshare.com/docs/apis/overview), [multi-user linking](https://www.ayrshare.com/implementing-multi-user-social-account-linking-with-ayrshare/)). Excepción documentada: **X/Twitter sí exige app propia** por cuenta de Ayrshare.

Esto ordena las opciones por lo que realmente importa:

| Opción | ¿Evita el gate de aprobación? | ¿Permite reventa a devs? | Veredicto |
|---|---|---|---|
| Adapters nativos propios | ❌ No — 2–4 meses | ✅ Sí | Inviable como "revenue rápido" |
| Postiz self-host | ❌ **No** — mismo gate | ✅ Sí (AGPL) | Ahorra código, **no ahorra tiempo**. Trampa |
| Ayrshare | ✅ Sí | ❌ **No** (términos) | Sólo válido para el motor PYMES |
| **bundle.social** | ✅ Sí | ✅ Sí (marketing explícito) | **La única casilla que satisface ambas** |
| Blotato / Zernio | ✅ Sí | ❓ Sin verificar | Verificar antes de decidir |

### 2.5 Margen bruto implícito — el problema económico

Escenario: revender al precio del propio Zernio, que es el techo de mercado observable (si Zernio cobra $3/cuenta, cobrar $10 exige una diferenciación que la Tarea 3 debe demostrar).

| Coste (proveedor) | Precio de reventa | Margen bruto a 100 cuentas conectadas | Margen a 500 cuentas |
|---|---|---|---|
| Ayrshare Business ($599 + $8,99/perfil sobre 30) | $3/cuenta = **$300/mes** | **−$928/mes (negativo)** | Sigue negativo hasta ~volúmenes altos con tarifa $2,49 |
| Ayrshare a $2,49/perfil (500+, requiere ya tener 500) | $3/cuenta | +$0,51/cuenta = **17% bruto** | ~$255/mes bruto |
| **bundle.social ($100/mes plano, ilimitado)** | $3/cuenta = $300/mes | **+$200/mes (67% bruto)** | **+$1.400/mes (93% bruto)** |
| **bundle.social** | $6/cuenta = $600/mes | +$500/mes (83%) | +$2.900/mes (97%) |
| Postiz self-host (~$20–50/mes infra) | $3/cuenta | ~+$255/mes (85%) | ~+$1.450/mes | 

**Conclusiones económicas:**

1. **Revender Ayrshare al precio de mercado da margen negativo o marginal.** Su modelo per-perfil está diseñado para que el revendedor cobre bastante más, no para competir con un vendor a $1–3/cuenta. Doblemente descartado (términos + economía).
2. **Sólo el precio plano (bundle.social) o el self-host producen márgenes de SaaS.** Con coste fijo y precio variable, el margen mejora con la escala; con coste variable ≈ precio variable, no hay negocio.
3. **El techo de precio del mercado es brutalmente bajo.** Zernio regala 2 cuentas y cobra $1–6. Un cliente PYME con 4 redes conectadas paga **$24/mes**, del que quedan ~$20 de bruto. **Se necesitan ~50 clientes PYME para $1.000/mes de bruto** — y esos 50 clientes hay que venderlos uno a uno (ver Tarea 5). Esto no es un negocio de "revenue rápido"; es un negocio de volumen con CAC alto y ticket bajo.

---

## 3. ¿El MCP es todavía un diferenciador? (Tarea 3)

**Respuesta corta: no frente a los competidores contra los que Fase 0 competiría de verdad. Sí frente a los incumbentes de PYME — pero ésos no son el mismo mercado.**

### 3.1 Ya commoditizado — el segmento API-first

Recuentos publicados en abril de 2026 [S] listan como servidores MCP **en producción**: **PostPlanify, Ayrshare, Postiz, Buffer, Publora, Oktopost, Simplified, Blotato, OpenTweet y Fast.io** ([SocialPilot](https://www.socialpilot.co/best-social-media-mcp-tools), [Socialync](https://www.socialync.io/blog/best-social-media-mcp-servers-2026), [Blotato](https://www.blotato.com/blog/best-social-media-mcp-servers)). A ellos se suman **bundle.social** (MCP oficial, 14+ plataformas) y el propio **Zernio** (mcp.zernio.com).

Es decir: **de los siete agregadores de la tabla §2.2, al menos cinco ya tienen MCP.** Blotato lo ofrece por **$29/mes planos**, con endpoint público (`mcp.blotato.com/mcp`).

**Veredicto para el segmento developers/agentes: el MCP no es un diferenciador, es tabla de apuestas.** Es exactamente la "casilla en la página de precios de un competidor" que temía el brief. Peor: llegar en el 12.º puesto a una lista de 12 significa competir sólo por precio, y el precio de referencia ya es $29/mes planos o $1/cuenta.

### 3.2 Todavía NO commoditizado — el segmento SMB/gestión social

Sin MCP oficial a fecha de abril 2026 [S]: **Hootsuite, Later, Sprout Social, Sendible, SocialBee, Metricool, Loomly, Agorapulse, CoSchedule y Vista Social**. Con MCP de primera parte: sólo **Buffer** (lanzado a finales de 2025, 18 operaciones sobre su GraphQL API; beta pública en marzo de 2026) y **SocialPilot** ([Buffer](https://buffer.com/resources/best-mcp-servers/), [Socialync sobre Hootsuite](https://www.socialync.io/mcp-server/hootsuite)).

**Esto importa mucho para el caso PYMES**: **Metricool — el incumbente clave en el mercado hispanohablante (ver §5) — no tiene MCP.** Hay ahí una ventana real.

### 3.3 La conclusión honesta, y por qué es incómoda

Hay una **contradicción interna en la propuesta del fundador** que este dato saca a la luz:

- El **MCP como diferenciador** sólo funciona en el segmento **PYME/agencia**, donde los incumbentes no lo tienen… pero ese segmento **no compra por MCP**. Una peluquería o una tienda local no sabe qué es MCP ni lo pedirá jamás. Vender "somos MCP-native" a una PYME es vender una característica que el comprador no puede evaluar.
- El **MCP sí es demandado** en el segmento **developers/agentes**… donde ya lo tienen 12 competidores, varios más baratos, y donde además los términos de Ayrshare (§2.3) prohíben revender.

Formulado sin adornos: **el diferenciador propuesto está en el mercado equivocado.** El único encaje coherente sería un producto MCP-native dirigido a **agencias y freelancers hispanohablantes que ya usan agentes LLM en su flujo de trabajo** — un nicho estrecho pero real, y ninguno de los 12 competidores está posicionado en español para él.

**Lo que sí queda como novedoso vs. lo ya commoditizado:**

| Elemento de la propuesta | ¿Novedoso en julio 2026? |
|---|---|
| Servidor MCP sobre API de publicación | ❌ **Commoditizado** — 12+ implementaciones |
| API REST unificada multiplataforma | ❌ **Commoditizado** — es la categoría entera |
| Precio por cuenta conectada | ❌ Commoditizado — es el modelo estándar (Ayrshare, Zernio, Publer) |
| Agent Skills empaquetadas sobre el MCP | ⚠️ **Parcialmente novedoso** — no encontré agregador que distribuya Skills; ventaja pequeña y copiable en semanas |
| MCP + posicionamiento en **español** para PYME/agencia | ✅ **Hueco real** — Metricool (líder en ES) no tiene MCP; ningún MCP-native está localizado |
| Fusión publicación ↔ *listening de medios ganados* | ✅ **Genuinamente diferenciado** — pero eso es Fase 1, no Fase 0 (ver §4) |

---

## 4. Alcance real de *lectura* de las cuentas conectadas (Tarea 4)

Ésta es la tarea que confirma o mata la tesis de composición Fase 0 ↔ Fase 1. **Confirma la conclusión del architect, con un matiz relevante que la ADR 19 no recogió.**

### 4.1 Qué se puede leer con OAuth de cuenta conectada

| Plataforma | Analytics propios | Comentarios en contenido propio | **Menciones de terceros** | Profundidad histórica | Fuente |
|---|---|---|---|---|---|
| **Instagram** | ✅ Insights API: reach, impresiones, visitas de perfil — **sólo cuentas propias y media propio** | ✅ `GET /{ig-media-id}/comments` | ⚠️ **Parcial y real**: `GET /{ig-user-id}/mentioned_media` y `/mentioned_comment` devuelven posts y comentarios donde **te @-mencionaron**; `GET /{ig-user-id}/tags` devuelve media donde te etiquetaron. **No incluye menciones en Stories**, ni menciones sin @, ni nada sobre competidores | No documentada con claridad en fuentes accesibles; búsqueda por hashtag limitada a **30 hashtags únicos por usuario / 7 días rodantes** | [P] Meta Graph API · [S] [Elfsight](https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/) |
| **TikTok** | ✅ Sólo cuenta propia autenticada | ⚠️ Limitado; a escala requiere acceso más amplio del que la API concede normalmente | ❌ **No.** El Display API "no tiene endpoint para consultar datos públicos de cuentas arbitrarias". El **Research API** sí lo tiene (búsqueda por keyword/hashtag, perfiles públicos, comentarios) pero está **restringido a investigadores académicos/sin ánimo de lucro aprobados, y las solicitudes comerciales se rechazan típicamente** | No aplica | [P] [developers.tiktok.com](https://developers.tiktok.com/) · [S] [Cotera](https://cotera.co/articles/tiktok-api-integration-guide), [Scrapfly](https://scrapfly.io/blog/posts/guide-to-tiktok-api) |
| **YouTube** | ✅ Analytics de canal propio | ✅ `commentThreads` (también en vídeos ajenos, con coste de cuota) | ⚠️ `search.list` existe pero cuesta **100 unidades/llamada** → 100 búsquedas agotan la cuota diaria completa | Limitada por cuota, no por retención | [P] [Quota docs](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) |
| **LinkedIn** | ✅ Analytics de página propia | ⚠️ Vía Community Management (gated) | ❌ `r_member_social` **cerrado a nuevas solicitudes** | — | [P] [Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06) |

### 4.2 Veredicto: el architect acierta en el eje de datos, y hay que decirlo sin suavizar

**OAuth de cuenta conectada da medios PROPIOS. El producto de Qualify son medios GANADOS.** Ningún volumen de cuentas conectadas produce el dataset de la Fase 1, porque:

1. **La unidad de análisis de Qualify es el creador o competidor no afiliado** — precisamente quien nunca conectará su cuenta a nuestra app. La cobertura de un producto basado en OAuth es exactamente el conjunto de cuentas que nos han dado permiso, que es el conjunto complementario del que queremos analizar.
2. **TikTok, la plataforma central de la tesis multimodal, cierra la puerta por diseño**: el acceso que permitiría listening comercial (Research API) rechaza explícitamente casos de uso comerciales. No es una limitación que se resuelva escalando ni pagando.
3. **La Fase 1 existe porque el scraping es la única vía a estos datos.** Fase 0 no scrapea (que es su ventaja de riesgo legal, y es real) — pero por eso mismo **no puede alimentar a Fase 1**. La ventaja y la incapacidad son la misma propiedad vista desde dos lados.

### 4.3 El matiz que sí sostiene una composición parcial (y que la ADR 19 subestimó)

La ADR 19 afirma que OAuth da "sólo medios propios". **Es casi exacto, pero deja fuera dos superficies que sí son medios ganados:**

- **`mentioned_media` / `mentioned_comment` / `tags` de Instagram**: son contenido de **terceros** sobre **nuestro cliente**. Eso es medio ganado, en primera parte, con consentimiento y sin scraping. Es el caso de uso "alertas de mención de marca" del README (Fase 3), servido legítimamente vía OAuth — para la marca propia del cliente, nunca para competidores.
- **Comentarios en el contenido propio del cliente**: son voz de audiencia de terceros. Es exactamente el punto de composición que el architect ya identificó: `packages/models/sentiment.py` (robertuito) y el clasificador zero-shot propuesto **son aplicables de inmediato** sobre este corpus, sin pipeline de scraping, sin ClickHouse, sin VLM.

**Reformulación precisa de la tesis de composición:**

| Capacidad de Qualify | ¿Alcanzable con OAuth (Fase 0)? |
|---|---|
| Sentiment/temas sobre comentarios de la marca propia | ✅ **Sí** — composición real e inmediata |
| Alertas de mención de la marca propia (IG, texto) | ✅ Sí, parcial (no Stories, no menciones sin @) |
| Menciones **dentro de vídeo/audio** (visual listening) | ❌ No — requiere el pipeline multimodal |
| Monitoreo de **competidores** | ❌ **No, estructuralmente** |
| Discovery/scoring de **creators no afiliados** | ❌ **No, estructuralmente** — es el núcleo de Fase 4 |
| Share of voice, mapa de conversación de categoría | ❌ No |

**Conclusión:** existe un puente estrecho y verdadero (sentiment sobre comentarios propios), suficiente para justificar que Fase 0 no sea trabajo tirado. **No es suficiente para llamarla "Fase 0 de Qualify"**: es un producto distinto que comparte infraestructura y un modelo de sentiment, exactamente como concluyó el architect. Debe declararse así en la ADR.

---

## 5. Disposición a pagar de PYMES/B2C en mercado hispanohablante (Tarea 5)

### 5.1 Metricool — el incumbente que fija el suelo de precio (verificado 2026-07-21)

Metricool es español, es el líder de facto en gestión social para PYME/freelance en el mercado hispanohablante, y su estructura de precios es el obstáculo más concreto para monetizar Fase 0 en ese segmento ([P] [metricool.com/pricing](https://metricool.com/pricing/)):

| Plan | Precio | Marcas | Incluye |
|---|---|---|---|
| **Free** | **€0** | 1 | 20 posts/mes, 5 perfiles de competidor, 30 días de analytics, asistente IA |
| Starter | €16–29/mes (€20–37 anual) | 5–10 | Publicación ilimitada, hasta 100 competidores, LinkedIn, informes PDF/PPT |
| Advanced | €43–130/mes | 15–50 | Equipos, aprobación de posts, analytics X completo, Looker Studio, **API** |
| Custom | A consultar | Custom | **White label**, gestor dedicado, créditos IA |

**Tres implicaciones duras:**

1. **El plan gratuito de Metricool cubre a la PYME típica.** Un negocio local con una marca y ~5 posts/semana **cabe en el tramo de €0**. Para desplazarlo hay que ser gratis y además mejor, o resolver un problema que Metricool no resuelve.
2. **Metricool ya hace análisis de competidores** (5 perfiles gratis, 100 en Starter) — lo cual, nótese, es *listening ligero* que su producto ofrece **sin OAuth de esas cuentas**. Es un recordatorio de que el hueco de Qualify no es "monitorizar competidores" a secas, sino **multimodal/vídeo**.
3. **Metricool no tiene MCP** (§3.2) → única ventaja de producto defendible en este segmento, y como se argumentó, es una ventaja que el comprador PYME no sabe valorar.

### 5.2 Dónde está realmente el dinero en el mercado hispanohablante: el servicio, no la herramienta

Tarifas de gestión de redes sociales en España, 2026 [S, consenso entre múltiples fuentes del sector]:

| Modalidad | Precio | Fuente |
|---|---|---|
| Freelance, gestión básica | **€250–400/mes por cliente** | [venderporinternet](https://www.venderporinternet.org/precios-y-tarifas-de-un-community-manager/), [Propulsia](https://propulsia.es/precios-community-manager/) |
| Freelance, con estrategia + análisis | **€400–700/mes por cliente** | [Olga Comunicación](https://olgacomunicacion.com/tarifas-redes-sociales/) |
| Rango amplio agencia/freelance | **€200–1.500/mes por cliente** | [Los Monos Creativos](https://losmonoscreativos.com/precios-para-gestion-de-redes-sociales-espana/) |
| Tarifa horaria freelance | €20–40/h (media ~€30/h); profesional senior €35–60/h | [tarifaautonomo](https://tarifaautonomo.com/tarifa-community-manager) |

**El contraste es el hallazgo de esta sección:**

- La **herramienta** que una PYME usa para publicar vale **€0–29/mes** (y a menudo €0).
- El **servicio** de que alguien publique por ella vale **€250–700/mes**.

Hay un factor **~20×** entre lo que el mercado paga por software de publicación y lo que paga por el trabajo de publicar. Un fundador en solitario que vende software a PYMES compite contra un producto gratuito de un competidor local establecido, con un ticket de €20/mes y venta uno-a-uno. El mismo fundador vendiendo servicio (apalancado en su propia herramienta y en agentes LLM) factura 20× por cliente.

### 5.3 Revenue realista por cliente para un fundador en solitario

| Escenario | Ticket/cliente/mes | Clientes para €3.000/mes | Viabilidad |
|---|---|---|---|
| Vender la API a devs (precio Zernio, ~4 cuentas/cliente) | ~$12–24 | **125–250 clientes** | ❌ Inviable en solitario; CAC > LTV con venta self-serve sin marca |
| Vender SaaS a PYME (precio Metricool Starter) | €16–29 | **100–190 clientes** | ❌ Inviable; además compite con un Free creíble |
| **Servicio gestionado a PYME, apalancado en la herramienta propia** | **€300–600** | **5–10 clientes** | ✅ **Viable en solitario**, y alcanzable en semanas |
| Herramienta white-label vendida a agencias/freelances que revenden servicio | €50–150 | 20–60 agencias | ⚠️ Intermedio; venta B2B más lenta pero ticket mejor |

**Conclusión de la Tarea 5:** el modelo de negocio que hace rentable a Fase 0 para un fundador en solitario **no es vender la API**. Es **usar la API como palanca de margen sobre un servicio**, o vendérsela a quien ya presta ese servicio (agencias y freelances), no al negocio final.

---

## 6. Recomendación

### 6.1 Veredicto: **GO-WITH-CHANGES**, con dos cambios que no son opcionales

No es NO-GO: existe un camino real a ingresos, y es más rápido que la Fase 1. Pero **no es el camino que describe la propuesta**, y la versión literal de la propuesta —construir integraciones propias y vender una API+MCP a desarrolladores— es **NO-GO por tres razones independientes**, cada una suficiente por sí sola:

1. **Calendario** (§1): IG/TikTok/FB exigen 2–4 meses de revisión administrativa antes de poder publicar público para un tercero. "Revenue rápido" con adapters propios es falso.
2. **Términos** (§2.3): sobre Ayrshare la reventa a desarrolladores está prohibida literalmente. Sobre Postiz self-host es legal pero reintroduce el gate de aprobación completo.
3. **Diferenciación** (§3): el MCP ya lo tienen 12+ competidores en el segmento de desarrolladores, con precios de $29/mes planos o $1/cuenta.

**Cambio 1 — comprar el fan-out a un proveedor con derechos de reventa explícitos.** Confirma la recomendación del architect y la endurece: no es preferencia arquitectónica, es **condición de existencia**. El agregador no vende código, vende **su aprobación de plataforma**, que es el activo escaso. Candidato principal: **bundle.social** ($100/mes plano, cuentas ilimitadas, MCP oficial, comercializado explícitamente para "reseller platform"). Verificar sus términos por escrito antes de comprometerse. **Descartar Ayrshare** (términos + margen negativo) y **descartar el self-host como atajo** (no ahorra tiempo, sólo código).

> Corolario para la ADR 19: la recomendación del architect de "in-sourcing selectivo de las 3–5 plataformas de más volumen" es correcta **como plan a medio plazo**, pero debe llevar una etiqueta de coste que la nota no incluye: internalizar IG o TikTok **es** pagar el peaje de 2–4 meses de revisión. Sólo tiene sentido cuando el ahorro anual de fees supere ese coste; a los precios de bundle.social ($1.200/año), ese punto está muy lejos.

**Cambio 2 — cambiar el comprador: vender servicio o vender a quien presta servicio, no software a la PYME final.** El mercado hispanohablante paga €250–700/mes por gestión de redes y €0–29/mes por la herramienta (§5.2). Con 5–10 clientes de servicio se llega a €3.000/mes; con software haría falta 100–250 clientes. El producto técnico (API+MCP+Skills) pasa de ser *lo que se vende* a ser *la ventaja de coste que permite atender 10 clientes en el tiempo de 2*.

### 6.2 Los 3 riesgos principales, ordenados

**Riesgo 1 — Dependencia de la revisión/aprobación de plataforma como ruta crítica (severidad: crítica; probabilidad: cierta si se construye nativo).**
Es una dependencia de calendario de 2–4 meses, fuera de control, rechazable y **revocable después de concedida**. TikTok publica en `SELF_ONLY` hasta pasar auditoría — un fallo que el cliente percibe como producto roto. *Mitigación:* comprar el fan-out (elimina el riesgo casi por completo al operar bajo la app del agregador). *Riesgo residual:* si el agregador pierde su aprobación, nuestro producto se cae entero — concentración sobre un acceso ajeno y revocable. **Corolario sobre la tesis "Fase 0 pre-construye la superficie de activación de Fase 5":** en la vía comprada (la única viable, §2.4), el usuario final concede OAuth **a la app del agregador, no a la nuestra** — los tokens viven bajo su plataforma. El grant es por tanto un activo **cautivo del proveedor**, no propio: no se transfiere si se cambia de agregador y se evapora si el agregador cae. La superficie de activación de Fase 5 se apoyaría sobre **consentimiento alquilado**. Además ese grant sólo pre-construye el carril de activación *sobre canal propio del cliente* (smart replies a comentarios/DMs propios, publicación de campañas en canales propios), **no** el carril de outbound a creators no afiliados — que es email/LinkedIn vía Instantly/HeyReach, un stack distinto que OAuth de publicación no toca.

**Riesgo 2 — Compresión de precio hasta la no-viabilidad (severidad: alta; probabilidad: alta).**
Zernio regala 2 cuentas y cobra $1–6; Blotato cobra $29 planos; Metricool tiene un Free creíble. El precio de mercado no cubre un CAC de venta uno-a-uno. Revender Ayrshare da margen **negativo** (§2.5). *Mitigación:* precio plano por proveedor + ticket de servicio, no de licencia. *Señal de alarma:* si a las 8 semanas no hay ≥3 clientes pagando >€200/mes, el modelo de precios está mal y hay que parar.

**Riesgo 3 — Coste de oportunidad y putrefacción del activo de Fase 1 (severidad: media-alta; probabilidad: alta).**
El architect ya lo documentó y la evidencia de mercado lo agrava: la composición Fase 0 → Fase 1 es **más débil de lo que la propuesta asume** (§4.2), porque OAuth no alcanza medios ganados y TikTok rechaza usos comerciales de su Research API. Lo que se pausa no es "la fase anterior del mismo producto", es un producto distinto. Y `packages/scraper` **caduca solo**: sus fixtures congelan una foto de 2026-07 y el hydration JSON cambia. *Mitigación:* mantener la condición de ADR 19 de **completar la Parte 3 antes de pausar** — es lo que convierte trabajo de valor-cero en valor demostrable. Y explotar el puente real que sí existe: sentiment (`packages/models/sentiment.py`) sobre comentarios de cuentas conectadas.

### 6.3 Prueba más barata antes de comprometer nada

Antes de escribir código de Fase 0, dos verificaciones de días, no semanas:

1. **Confirmar por escrito con bundle.social** (o el proveedor que se elija) que la reventa/white-label está permitida, y si su aprobación de plataforma cubre a nuestros clientes finales. Un email. Si la respuesta es no, Fase 0 en su forma de producto muere ahí.
2. **Vender el servicio antes de construir la herramienta**: conseguir 2–3 PYMES pagando €300/mes por gestión de redes, atendidas al principio manualmente. Valida disposición a pagar (§5) con coste de ingeniería cero, y **cada cliente conseguido así es cliente también del producto** si luego se construye.

### 6.4 Preguntas abiertas que esta investigación no cerró

- Términos de reventa de **Blotato, Zernio y upload-post** (no verificados; la página de precios de upload-post devolvió 404).
- Requisitos de entidad empresarial de la **auditoría de TikTok** — la documentación pública no los detalla; hay que abrir el formulario de solicitud.
- Tarifa unitaria oficial de la **API de X**: la doc primaria confirma el modelo pay-per-use pero no publica el importe; $0,015/post procede sólo de fuentes [S].
- Confirmación primaria de que **Zernio = Late/getlate.dev**.
- Profundidad histórica exacta de **Insights y Mentions de Instagram** (retención documentada, no encontrada en fuentes accesibles).
- Snapchat, Google Business Profile, Reddit y WhatsApp Business: vías de acceso no verificadas en esta pasada.

## Notas de metodología

Investigación de escritorio con web en vivo, 20–21 de julio de 2026. Precios públicos verificados contra páginas de precios oficiales donde fue posible ([P]); donde sólo existen fuentes de competidores ([S]) la cifra va etiquetada como hipótesis en la propia fila. Ningún precio ha sido validado con el proveedor ni negociado. Los plazos de aprobación de plataforma proceden de reportes de desarrolladores, no de SLAs publicados: **ninguna plataforma publica un SLA de revisión**, lo que es en sí mismo el dato relevante.


