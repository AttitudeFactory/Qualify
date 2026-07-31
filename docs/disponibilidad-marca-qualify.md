# Disponibilidad de marca «Qualify» — dominios, handles y conflictos existentes

**Eje:** oferta / estado del campo. Qué existe HOY, con fuente y fecha de acceso.
**Autor:** `gtm-specialist` · **Sesión:** 2026-07-31
**Pregunta del fundador:** ¿es viable salir al mercado público con el nombre **«Qualify»** tal cual? Chequeo de dominios, handles sociales y conflictos de marca/producto en el espacio SaaS/CRM/GTM.

> **Alcance.** Esto NO es un renombrado de código. «Qualify» ya es el nombre interno en todo el repo (`README.md`, `CLAUDE.md`, `packages/*`). La pregunta es de **salida al mercado**, no de refactor.

> **Convención de confianza.** `[V]` verificado contra fuente primaria (WHOIS, DNS, la propia web del producto) · `[S]` secundaria (agregador, directorio) · `[H]` hipótesis/inferencia del autor.

> **AVISO LEGAL.** La sección 4 (marcas registradas) es una búsqueda **razonable pero no exhaustiva**. **NO sustituye una búsqueda de marca formal hecha por un abogado de propiedad industrial.** Un registro de marca puede existir en clases y jurisdicciones que esta búsqueda no cubre.

## Estado de secciones

| # | Sección | Estado |
|---|---|---|
| 1 | Dominios | **LISTA** — los 10 candidatos están registrados. Cero disponibles. |
| 2 | Handles en redes sociales | **LISTA** — X y LinkedIn ocupados; YouTube libre; IG/TikTok/FB no verificables sin login |
| 3 | Conflictos de producto/empresa en CRM/GTM/sales-tech | **LISTA** — 🔴 **5 actores; el mayor es «Qualified», de Salesforce, en la MISMA categoría agentiva de GTM** |
| 4 | Marca registrada (nivel básico, no legal) | **LISTA** — 🔴 **«QUALIFIED» está REGISTRADA en clase 42 (software) por Qualified, Inc.** |
| 5 | Tabla de síntesis + recomendación | **LISTA** — recomendación: **«Qualify» tal cual NO es viable para salida pública en GTM** |

---

## 1. Dominios

**Método** `[V]`: consulta WHOIS directa contra el registro autoritativo (`whois.verisign-grs.com` para `.com`, registro de cada TLD para el resto), más resolución DNS (`dig` A/NS/MX) y `curl` sobre HTTPS siguiendo redirecciones. **Todo ejecutado el 2026-07-31.** No se usó ningún agregador de terceros: el WHOIS del registro y el DNS público **son** la fuente primaria.

### 1.1 Resultado en una línea

> **Los 10 dominios candidatos están registrados. Ninguno está disponible para compra directa en registrador.** Tres están explícitamente **a la venta en mercado secundario** (Afternic/Dan/Spaceship), lo que los hace adquiribles pero a precio de reventa, no a precio de registro (~US$10-15/año).

### 1.2 Tabla de dominios

| Dominio | Estado | Creado | Registrador | Qué hay hoy en esa URL (2026-07-31) | Confianza |
|---|---|---|---|---|---|
| **qualify.com** | **Registrado y EN USO ACTIVO** | 1999-09-27 | Spaceship, Inc. | Sitio vivo. `<title>` = **«Qualify.com — Do You Qualify for Business Financing?»**. Redirige a `www.qualify.com`, HTTP 200. Es un sitio de **financiación empresarial / calificación de préstamos**. NS Cloudflare, A-records de Vercel (64.29.17.65 / 216.198.79.65) → sitio moderno mantenido, no un parking. | `[V]` |
| **qualify.io** | **Registrado — A LA VENTA** | 2013-08-20 | GoDaddy (registrante oculto: Domains By Proxy) | Página lander de **Afternic** (NS `ns3/ns4.afternic.com`, IP de parking 13.248.169.48/76.223.54.146). El HTML es literalmente `window.location.href="/lander"` — el patrón canónico de dominio en venta. Expira 2026-11-19. | `[V]` |
| **qualify.ai** | **Registrado — sin web, PERO con email activo** | 2017-12-16 | Namecheap (privacidad WHOIS: Withheld for Privacy ehf) | **Sin registro A ni AAAA** → no carga ninguna web. Pero tiene **MX de Google Workspace** (`aspmx.l.google.com`), SPF (`include:_spf.google.com`) y un `google-site-verification`. NS de Cloudflare. → Alguien lo usa **para correo corporativo**, no lo tiene aparcado. Expira 2027-10-21. | `[V]` |
| **qualify.co** | **Registrado — A LA VENTA** | 2010-07-21 | Spaceship, Inc. | `<title>` = **«qualify.co for sale \| Spaceship.com»**. Página de venta del propio registrador. Expira 2027-07-20. | `[V]` |
| **qualify.app** | **Registrado — A LA VENTA** | — (registro no publicó fecha vía WHOIS) | — | NS `ns1/ns2.dan.com` + IP de parking Dan/Afternic. Mismo lander `window.location.href="/lander"`. **Dan.com es el marketplace de dominios de GoDaddy** → está listado en venta. | `[V]` |
| **getqualify.com** | **Registrado — sin web funcional** | 2005-04-23 | HOSTINGER operations, UAB | NS `ns17/ns18.domaincontrol.com` (GoDaddy) pero **no resuelve ningún A record** desde resolvers públicos (probado con resolver local y 1.1.1.1). Sin web. Dominio retenido, no publicado. Expira 2027-04-23. | `[V]` |
| **usequalify.com** | **Registrado — muy reciente** | **2026-01-30** | **Unstoppable Domains Inc.** | Redirige a `unstoppabledomains.com/d/usequalify.com` (ficha del dominio en Unstoppable Domains). Registrado hace ~6 meses. Expira 2027-01-30. | `[V]` |
| **tryqualify.com** | **Registrado — A LA VENTA** | 2024-02-24 | GoDaddy (Domains By Proxy) | NS `ns3/ns4.afternic.com` + IP de parking + lander de Afternic. Expira 2027-02-24. | `[V]` |
| **qualifyapp.com** | **Registrado — origen caído/cerrado** | 2014-03-28 | GoDaddy (Domains By Proxy) | NS Cloudflare en modo DNS-only, A = 35.183.140.54 (AWS ca-central-1). **No responde ni en 80 ni en 443** (timeout en 3 intentos). Registrado y renovado hasta 2027-03-28 pero sin servicio público. | `[V]` |
| **qualifyhq.com** | **Registrado y EN USO ACTIVO — ⚠️ VER §3** | **2024-09-27** | HOSTINGER operations, UAB | Sitio vivo. Redirige a `www.qualifyhq.com/ie-en`, HTTP 200. `<title>` = **«QualifyHQ - The Easiest Way to Do B2B Sales»**. NS Cloudflare. **Esto no es un dominio ocupado por un tercero irrelevante: es una herramienta de ventas B2B activa.** Análisis completo en §3. | `[V]` |

### 1.3 Lecturas

1. **«Qualify» es una palabra de diccionario en inglés de altísimo tráfico comercial.** Ningún TLD de primera línea quedó libre, y el `.com` lleva ocupado desde 1999. Esto era esperable y no es en sí una mala noticia — es el coste normal de elegir un nombre genérico.
2. **Tres dominios son comprables ya mismo** (`qualify.io`, `qualify.app`, `qualify.co`) porque están listados en mercado secundario. **Precio no verificado** — los landers de Afternic/Dan requieren interacción de navegador para mostrar el precio, y no lo obtuve. `[H]` Por comparables de mercado, un `.io`/`.co` de una palabra común de diccionario suele situarse en el rango de **cuatro a cinco cifras USD**, no en decenas de dólares. **Hipótesis, no dato: hay que pedir el precio en el lander antes de presupuestar nada.**
3. **`qualify.ai` es el caso más engañoso.** Parece libre (no carga ninguna web) pero tiene Google Workspace configurado: **está en uso para correo por alguien con privacidad WHOIS y renovado hasta 2027**. No es adquirible ni está abandonado.
4. **`getqualify.com` y `qualifyapp.com` son los menos "defendidos"**: registrados y renovados pero sin servicio público ni, aparentemente, uso. `[H]` Son los dos candidatos más plausibles para un intento de compra privada al titular, y ambos están tras privacidad de registrador o registradores de bajo coste (Hostinger/GoDaddy), lo que sugiere tenencia especulativa más que uso corporativo. **Hipótesis: no verifiqué titularidad real.**
5. **`usequalify.com` registrado en enero de 2026** en Unstoppable Domains. `[H]` No hay evidencia de para qué; el patrón `use<marca>.com` es el prefijo estándar de una startup SaaS, lo que hace pensar (sin probarlo) que alguien más consideró el mismo nombre recientemente.

---

## 2. Handles en redes sociales

**Método** `[V]`: petición HTTP directa a la URL canónica del perfil en cada plataforma, con user-agent de navegador, siguiendo redirecciones; se leyó el código HTTP, el `<title>` y la `meta description` del HTML servido. **Ejecutado el 2026-07-31.**

> **Calibración del método (importante — sin esto los resultados de X no significan nada).** Para X/Twitter probé primero un handle inventado (`zzqqxxnonexistent99231`): devuelve **HTTP 404** con `<title>` = «User Profile Not Found - X». Un handle existente devuelve **HTTP 200**. Por tanto, en la tabla, **200 en X ⇒ handle ocupado**, sin ambigüedad. Lo mismo para YouTube: `@handle` inexistente → **404**.

### 2.1 Tabla de handles

| Plataforma | `qualify` | `qualifyapp` | `getqualify` | `qualifyhq` | Confianza |
|---|---|---|---|---|---|
| **X / Twitter** | **OCUPADO** — HTTP 200, perfil sin bio pública (`<title>` «Profile / X»). Existe, pero está vacío, protegido o inactivo. | **OCUPADO** — «**Qualify App** (@QualifyApp)», bio: *«Your way to a successful career»* | **OCUPADO** — «**Need Qualified Staff?** (@GetQualify)», empresa de selección de personal (GBCSL); bio incluye teléfono nigeriano y `globalbackgroundcheck@gmail.com` | **OCUPADO** — «**QualifyHQ** (@QualifyHQ)», **el competidor de §3.2**. Se unió en **feb-2025**, **0 seguidores / 1 siguiendo** | `[V]` |
| **YouTube** (`/@handle`) | **LIBRE** (404) | **LIBRE** (404) | **LIBRE** (404) | **OCUPADO** — canal «QualifyHQ» (HTTP 200) | `[V]` |
| **LinkedIn** (`/company/`) | **LIBRE** (404) | **OCUPADO** — «**Qualify.ai**», 3 seguidores (ver §3.3) | **OCUPADO** — «**Qualify**», 30 seguidores, alemán (ver §3.4) | **OCUPADO** — «**QualifyHQ**», 222 seguidores | `[V]` |
| **Instagram** | **NO VERIFICABLE** | **NO VERIFICABLE** | **NO VERIFICABLE** | `qualify.hq` **OCUPADO** por QualifyHQ (enlazado desde su propio footer) | `[V]` solo el último |
| **TikTok** | **NO VERIFICABLE** | **NO VERIFICABLE** | **NO VERIFICABLE** | **NO VERIFICABLE** | — |
| **Facebook** | **NO VERIFICABLE** | **NO VERIFICABLE** | **NO VERIFICABLE** | Página existente **sin vanity URL** (`facebook.com/profile.php?id=61573229626776`) → el handle `/qualifyhq` probablemente **sigue libre** `[H]` | `[V]` la página; `[H]` el handle |

### 2.2 Por qué tres plataformas quedan sin verificar — y por qué eso es en sí un dato

No es que no lo intentara; es que **las tres plataformas bloquean activamente la comprobación anónima**, cada una a su manera:

- **Instagram**: `instagram.com/<handle>` devuelve **HTTP 200 para todo**, sirviendo un shell de JavaScript de ~609 KB **idéntico byte a byte** para handles existentes e inexistentes. Sin `meta description`, sin `og:title`. El endpoint interno `api/v1/users/web_profile_info/` responde `{"require_login":true}`. **Un 200 de Instagram no significa que el handle exista.**
- **TikTok**: `tiktok.com/@<handle>` devuelve **HTTP 200 con un cuerpo de 1.462 bytes idéntico para todos** — página de detección de bots, sin `<title>` ni `description`. `api/user/detail/` devuelve cuerpo vacío sin firma criptográfica.
- **Facebook**: **HTTP 400** para toda petición anónima de perfil.

> **Nota lateral relevante para el producto, no para la marca.** Que un chequeo de existencia de handle — la operación de lectura más trivial que existe en estas plataformas — sea imposible sin sesión autenticada o proxy residencial es **exactamente la razón por la que la Fase 1 de Qualify compra Zyte en lugar de hacer `requests.get`**. Refuerza, no debilita, la decisión de arquitectura ya tomada en `docs/alternativas-fase1.md`.

**Cómo cerrar los tres huecos, si el fundador quiere certeza:** son 12 comprobaciones manuales de 30 segundos cada una, hechas desde un navegador con sesión iniciada. No requieren herramienta. **Deliberadamente NO las marco como verificadas aquí** — un handle reportado como «libre» sin comprobar es la clase de dato que provoca que alguien compre un dominio y descubra después que el handle no estaba.

### 2.3 Lecturas

1. **`@qualify` está ocupado en X pero libre en YouTube y LinkedIn.** El de X es el peor caso posible: existe, no publica nada y no tiene bio → no hay ni con quién negociar identificable, y X **no libera handles inactivos** por política pública desde hace años.
2. **`qualifyhq` es el más ocupado de los cuatro**: X, YouTube, LinkedIn, Instagram y Facebook, todos por el mismo actor (§3.2). **Esta variante de escape está cerrada en todos los frentes simultáneamente**, que es el patrón que produce un actor que está construyendo marca en serio, no un okupa de dominios.
3. **`getqualify` está ocupado en X por una empresa de selección de personal nigeriana y en LinkedIn por un producto alemán de automatización de ventas** — dos actores distintos, ninguno relacionado, ambos usando la palabra en su sentido literal. Es la ilustración más limpia del problema de §3.3.
4. **Ninguna de las cuatro variantes está limpia en todas las plataformas.** No existe una donde se pueda tomar el conjunto completo de handles.

---

## 3. Conflictos de producto/empresa en CRM / GTM / sales-tech

> **Esta es la sección grave del documento, y no la voy a suavizar.** Encontré **cinco** actores distintos usando la raíz «Qualify» comercialmente, de los cuales **cuatro están en el espacio de ventas/GTM**. Van ordenados por severidad descendente.

### 3.1 CONFLICTO CRÍTICO — **Qualified** (`qualified.com`), **propiedad de Salesforce**

**Fuente:** `https://www.qualified.com/` y `https://www.linkedin.com/company/qualified-com/`, **accedidos 2026-07-31**, HTTP 200. `[V]`

**Lo que dice literalmente su propia home:** *«Welcome to the era of **agentic marketing**»*.
**Lo que dice literalmente su ficha de LinkedIn:** *«**Qualified (Acquired by Salesforce)** | 20.144 seguidores en LinkedIn. Qualified, alongside Salesforce, is helping usher B2B marketers into the era of **agentic marketing** with Piper the AI SDR Agent.»*

| Dato | Valor | Fuente |
|---|---|---|
| Propietario | **Salesforce** (adquirida) | `[V]` su propia ficha de LinkedIn, 2026-07-31 |
| Seguidores LinkedIn | **20.144** | `[V]` ídem |
| Empleados | **232** (rango declarado 201-500) | `[V]` ídem |
| Clientes nominales | **8x8, AMD, Asana, Box, LogicMonitor, SUSE** | `[V]` ídem |
| Producto | **Piper, el AI SDR Agent**: Piper Conversations (web), Piper Email, Piper Meetings, Piper Offers, Piper for Slack | `[V]` `qualified.com` |
| Categoría declarada | *Agentic Marketing* / *Agentic Nurture* / *Agentic Product-Led Growth* / generación de pipeline inbound, integrado con Salesforce CRM | `[V]` ídem |
| Marketing de categoría | Organizan el **«Agentic Marketing Summit»** y **«Piperfest '26»**; publican una serie web llamada **«The AI SDR Movement»** | `[V]` ídem |
| Pricing | **Sales-gated** — la página `/pricing` existe (HTTP 200) pero no publica cifras | `[V]` ídem |
| Sus propios handles | `twitter.com/**try**qualified`, `instagram.com/**try**qualified` | `[V]` footer de su web |

#### Por qué esto es severidad CRÍTICA — cuatro razones acumulativas

1. **Es la misma categoría, descrita con la misma palabra.** `README.md` y `CLAUDE.md` describen Qualify como *«plataforma agentiva de CRM/GTM»*. Qualified se autodenomina *«agentic marketing platform»* y **está gastando dinero en ser dueña de esa categoría** (un summit propio, una conferencia propia, una serie web propia). No es una coincidencia de nicho: es exactamente el mismo terreno semántico.
2. **«Qualify» y «Qualified» son la misma marca a efectos prácticos.** No son dos palabras parecidas: son **el infinitivo y el participio del mismo verbo**. En un análisis de confusión marcaria — que valora similitud fonética, visual y conceptual **más** la proximidad de los productos — esto es el peor cuadrante posible: nombres casi idénticos vendiendo casi lo mismo a casi el mismo comprador.
3. **El titular es Salesforce.** Esto convierte un riesgo teórico en un riesgo operativo. Salesforce tiene una función de propiedad intelectual dedicada y un historial público de defensa agresiva de su cartera de marcas. **La asimetría de costes en una disputa es total**: para ellos es trabajo rutinario de un departamento existente; para Qualify sería existencial. Y el riesgo no es solo el litigio — es el bloqueo en **App Store, Google Play, Meta App Review, Google Ads y AWS/Salesforce Marketplace**, donde una reclamación de marca de un titular grande se resuelve típicamente suspendiendo primero y preguntando después.
4. **Ellos mismos ya no pudieron tomar el handle.** Usan `@tryqualified` en X e Instagram, no `@qualified`. Una compañía respaldada por Salesforce tuvo que recurrir al prefijo `try`. Es la señal más limpia de cuán saturado está este espacio de nombres.

#### Lo que NO afirmo

`[H]` **No he verificado si Qualified tiene marca registrada, en qué clases, ni en qué jurisdicciones** — ver §4 y su aviso legal. Tampoco afirmo que una demanda sea probable ni inminente: una startup pre-lanzamiento sin ingresos rara vez atrae acción legal. **Lo que sí afirmo, y es un hecho verificado, no una opinión: existe un producto llamado «Qualified», propiedad de Salesforce, que vende una plataforma agentiva de GTM y está construyendo activamente esa categoría bajo ese nombre.** La decisión sobre qué hacer con ese hecho es del fundador; ocultárselo no lo sería.

### 3.2 CONFLICTO COMPETITIVO DIRECTO — **QualifyHQ** (`qualifyhq.com`)

**Fuente:** `https://www.qualifyhq.com/ie-en/` + `/pricing` + `/features` + `/use-cases`, **accedido 2026-07-31**, HTTP 200, contenido extraído del HTML servido. WHOIS del registro: creado **2024-09-27**, registrador HOSTINGER operations UAB. `[V]`

**Qué es, en sus propias palabras** (`<title>` y meta description literales del sitio):

> «**QualifyHQ — The Easiest Way to Do B2B Sales**»
> «Our AI finds exactly who you're looking for — decision makers with real emails, LinkedIn profiles, and phone numbers.»

**Qué hace exactamente** `[V]`:

| Capacidad de QualifyHQ | Descripción según su propio sitio |
|---|---|
| **Lookalike desde una URL** | *«Give us one great URL, and we'll find hundreds more just like them»*. Pegas la web de tu mejor cliente (ejemplo que usan: `stripe.com`), describes el ICP en lenguaje natural, y devuelve 100+ empresas similares con contactos. |
| **Cualificación de listas (list qualification)** | Subes un CSV, defines hasta 5 criterios, y el sistema devuelve **SÍ/NO por empresa con prueba**. Ejemplos suyos: *«¿está esta empresa en Alemania?»*, *«¿tienen 50-200 empleados?»*. |
| **Enriquecimiento de contactos** | Emails verificados, teléfonos y perfiles de LinkedIn de decisores. Reclaman **95%+ de precisión de email**. |
| **Base de datos** | *«verified data from 60M+ companies»*, *«we check 100+ data points»*. |
| **Casos de uso publicados** | Seguimiento post-conferencia, reactivación de listas muertas en el CRM, planificación de territorio/ABM. |

**Su pricing** `[V]` (página `/pricing`, 2026-07-31) — **y es un modelo de créditos, igual que el que Qualify planea para Fase 5**:

| Plan | Precio/mes | Créditos | €/crédito | Usuarios |
|---|---|---|---|---|
| Starter | **49 €** | 500 | 0,098 | 1 |
| Scale *(«Most Popular»)* | **99 €** | 1.000 (opciones 2.000 / 3.000) | 0,099 | Ilimitados |
| Growth *(«Highest Value»)* | **299 €** | 4.000 (opciones 8.000 / 16.000) | 0,075 | Ilimitados |
| Custom | Sales-gated | Ilimitado | Varía | Ilimitados |

- Anual con **20 % de descuento**. Free trial de 7 días / 100 cualificaciones gratis. Créditos con *rollover*.
- **Unidad de consumo:** 1 cualificación de empresa = **1 crédito**; 1 lookalike cualificado = **10 créditos** («pagas solo por resultados»).

**Tamaño y tracción** `[V]`: el propio sitio muestra **«212+ Active users»** en el hero. Testimonios nominales de **iDenfy** (Viktor Vostrikov, CMO) y **Vilimed** (Kornelija Danieliūtė) — ambas compañías lituanas, coherente con el registrador Hostinger (Lituania). El sitio está localizado a **~30 locales de la UE**. Tiene programa de **afiliados**.

**Sus handles sociales** (enlazados desde su propio footer, por tanto `[V]`):
- Instagram: `instagram.com/qualify.hq/`
- X/Twitter: `x.com/QualifyHQ`
- Facebook: `facebook.com/profile.php?id=61573229626776`

#### Por qué esto es severidad ALTA y no cosmética

1. **Está en la misma categoría de producto, no en una adyacente.** No es «una empresa cualquiera que se llama Qualify». Es **una herramienta de cualificación de leads y sales intelligence** — exactamente la categoría en la que compite la Fase 4 (descubrimiento de creadores/leads, scoring, cascada de enriquecimiento de contacto) y la Fase 5 (activación GTM) de Qualify según el mapa de fases de `CLAUDE.md`.
2. **El mecanismo central se solapa conceptualmente.** El *«dame una URL y te encuentro cientos parecidas»* de QualifyHQ es la misma primitiva de producto que el **lookalike de creadores sobre embeddings de contenido** de la Fase 4 de Qualify. El input es distinto (web corporativa vs. contenido de vídeo) — **y ahí está justamente la diferenciación real de Qualify** — pero el *job to be done* que vende al comprador es el mismo y se describe con las mismas palabras.
3. **El modelo de negocio se solapa.** Créditos mensuales, rollover, usuarios ilimitados, tramo enterprise sales-gated. Es el modelo que `CLAUDE.md` marca para Fase 5 (`billing.usage_events`).
4. **Usa el nombre como marca, no como palabra.** «QualifyHQ» con logotipo, dominio propio, redes propias con el handle `QualifyHQ`, programa de afiliados y clientes nominales. Hay uso comercial demostrable desde al menos finales de 2024.
5. **`QualifyHQ` era una de las variantes de escape del propio fundador.** El brief pedía evaluar «Qualify HQ» como alternativa si «Qualify» a secas no era viable. **Esa salida está cerrada**: es literalmente el nombre de un competidor de categoría con producto en producción, dominio, X y Facebook.

#### Lo que NO afirmo

`[H]` No he verificado ingresos, financiación, ni si tienen marca registrada (ver §4). **212 usuarios activos es una tracción pequeña** — esto es una startup temprana, no un incumbente. Eso reduce el riesgo comercial inmediato pero **no reduce el riesgo de marca**: un tercero con uso comercial previo en la misma clase es un problema legal y de SEO con independencia de su tamaño. Y crece: presencia en 30 locales de la UE sugiere intención de expandir, no de cerrar.

### 3.3 CONFLICTO DE CATEGORÍA ADYACENTE — **Qualify.ai** (agente de voz IA para verificación)

**Fuente:** `https://www.linkedin.com/company/qualifyapp/`, accedido **2026-07-31**, HTTP 200. `[V]`

- Nombre de la compañía en LinkedIn: **«Qualify.ai»**. Lema: *«Verify. Automate. Scale»*.
- Descripción propia: *«**The AI Voice Agent for Automated Verification and Inquiry Handling.** We provide a SaaS-based AI voice agent solution […] initiating human-like outbound calls to verify details (e.g., applications, orders, appointments) and instantly resolving inbound queries 24/7.»*
- **Tamaño: 3 seguidores en LinkedIn.** Es un proyecto embrionario o recién lanzado.

> **Esto cierra el misterio de §1.2.** El dominio `qualify.ai` no tenía web pero sí Google Workspace activo y renovación hasta 2027. Encaja: `[H]` **es casi con certeza el dominio de esta compañía**, que aún no ha publicado sitio pero ya opera el correo. **Inferencia, no verificada** — la privacidad WHOIS impide confirmar la titularidad, y el vínculo se apoya en la coincidencia de nombre más el slug `qualifyapp` de LinkedIn.

**Severidad: media.** Agente de voz IA que hace llamadas salientes para *verificar/cualificar* es sales-tech adyacente, no idéntico a listening social. Pero **ocupa el `.ai`**, el TLD por defecto para un producto de IA en 2026, y **ocupa `linkedin.com/company/qualifyapp`**, cerrando esa variante. Con 3 seguidores el riesgo comercial es nulo hoy; el riesgo es de **colisión de nombre en el mismo mercado de compradores**.

### 3.4 CONFLICTO COMPETITIVO DIRECTO, mercado alemán — **Qualify** (automatización de ventas)

**Fuente:** `https://www.linkedin.com/company/getqualify/`, accedido **2026-07-31**, HTTP 200. `[V]`

- Nombre en LinkedIn: **«Qualify»** — el nombre exacto, sin sufijo.
- Descripción propia (alemán): *«Automatisiere deinen Vertrieb im Handumdrehen und weiß zu jeder Zeit, wer Leistung bringt und wo Umsatz steckt.»* → **«Automatiza tu departamento comercial en un momento y sabe en todo momento quién rinde y dónde está la facturación.»**
- **Tamaño: 30 seguidores en LinkedIn.**

**Severidad: media-alta por el nombre, baja por el tamaño.** Es **automatización de ventas y seguimiento de rendimiento comercial** — categoría GTM, el nombre exacto «Qualify», con presencia en un mercado europeo grande. `[H]` No pude localizar su producto ni su web: la búsqueda web devolvió únicamente contenido genérico sobre automatización de ventas (ver §3.6 — este es literalmente el problema del nombre manifestándose durante esta propia investigación). **No verifiqué si el producto está vivo o abandonado.**

### 3.5 CONFLICTO DE NOMBRE EXACTO, categoría distinta — **Qualify.com** (financiación empresarial)

**Fuente:** `https://www.qualify.com/`, accedido **2026-07-31**, HTTP 200. `[V]`

- `<title>`: «Qualify.com — Do You Qualify for Business Financing?»
- Meta description: *«Compare small business loan options from multiple lenders with one simple application. No impact to your credit score. Built for limo, transportation, and small business owners.»*
- Producto: comparador de préstamos SBA / business loans / equipment financing / startup loans, con **«AI Advisors»** conversacionales en 30+ idiomas (personajes Sam, Bianca, Eddie, Tess, Riley). Reclama *«Trusted by 1,000+ small business owners»*.
- Dominio creado **1999-09-27**, activo y mantenido (stack Vercel + Cloudflare).

**Severidad: media.** No es competencia de producto (es fintech de préstamos, no sales-tech). Pero **ocupa el `.com` exacto, es un negocio real y vivo, y usa «Qualify» como marca comercial pura**, con un juego de palabras («¿calificas?») que refuerza su derecho de uso. El `.com` no se recupera: no está en venta y tiene 27 años de antigüedad. **Además, envenena el SEO de marca**: buscar «Qualify» posiciona un comparador de préstamos con 1.000+ clientes.

### 3.6 El problema estructural del nombre, por encima de cualquier conflicto concreto

«Qualify» es un **verbo del vocabulario nuclear de la propia categoría** en la que Qualify quiere vender: *qualify a lead*, *lead qualification*, *sales qualified lead (SQL)*, *marketing qualified lead (MQL)*, *BANT qualification*. Consecuencias, todas verificables sin más búsqueda:

- **Es prácticamente inbuscable.** Una consulta de «qualify» + cualquier término de ventas devuelve contenido educativo sobre *cómo cualificar leads*, no la marca. Ninguna cantidad de SEO gana contra el uso genérico de un verbo por parte de toda la industria.
- **Es débil como marca registrable.** En derecho marcario, un término **descriptivo del propio servicio** es la categoría más débil de marca. Un software que cualifica leads llamado «Qualify» es descriptivo casi por definición (ver §4).
- **Es ambiguo al oído.** «Estamos usando Qualify» ≡ «estamos cualificando» en una conversación de ventas en inglés.

> **Matiz honesto, en la otra dirección:** exactamente el mismo problema tienen marcas que funcionaron — Slack, Notion, Stripe, Clay. La genericidad se supera con dinero de marketing y tiempo. Lo que la determina es cuánto presupuesto de marca hay para comprar el significado de la palabra. **Ese es el juicio del fundador, no mío.** Lo que sí es un dato duro y no una opinión es §3.1: **Salesforce ya está gastando ese presupuesto sobre esa misma palabra en esa misma categoría**, con summit y conferencia propios.

### 3.7 Otros usos del término encontrados (severidad baja)

| Nombre | Qué es | Severidad | Fuente |
|---|---|---|---|
| **Qualify App** (`x.com/QualifyApp`) | Cuenta de X, bio *«Your way to a successful career»* → orientación profesional/empleo, no GTM | Baja — solo ocupa el handle | `[V]` 2026-07-31 |
| **Need Qualified Staff?** (`x.com/GetQualify`) | Empresa de selección de personal / verificación de antecedentes (GBCSL), contacto nigeriano | Baja — solo ocupa el handle | `[V]` 2026-07-31 |
| `qualify.io`, `qualify.app`, `qualify.co` | Dominios aparcados **en venta**, sin producto asociado | Ninguna (solo coste de adquisición) | `[V]` §1.2 |
| `qualifyapp.com`, `getqualify.com` | Registrados, sin servicio público | Ninguna | `[V]` §1.2 |

### 3.8 Resumen de §3 — el mapa de actores

| Actor | Categoría | Solapamiento con Qualify | Tamaño | Severidad |
|---|---|---|---|---|
| **Qualified** (Salesforce) | Plataforma **agentiva** de marketing/GTM, AI SDR | **Idéntico al posicionamiento declarado de Qualify** | 232 empleados, 20.144 seguidores, clientes Fortune | 🔴 **CRÍTICA** |
| **QualifyHQ** | Cualificación de leads B2B, lookalikes, enriquecimiento | **Fase 4 y Fase 5 de Qualify** | 212 usuarios, 222 seguidores | 🔴 **ALTA** |
| **Qualify** (DE) | Automatización de ventas | Categoría GTM, nombre exacto | 30 seguidores | 🟠 **MEDIA** |
| **Qualify.ai** | Agente de voz IA, verificación/cualificación | Sales-tech adyacente; ocupa el `.ai` | 3 seguidores | 🟠 **MEDIA** |
| **Qualify.com** | Comparador de préstamos a pymes | Ninguno de producto; ocupa el `.com` y el SEO | 1.000+ clientes, dominio de 1999 | 🟡 **MEDIA (SEO/dominio)** |

> **La observación que importa:** no hay **un** conflicto que esquivar. Hay **un espacio de nombres saturado** en el que cinco actores ya operan, cuatro de ellos en ventas/GTM, y el mayor es propiedad de Salesforce y está comprando la misma categoría con la misma palabra. Esto no se resuelve eligiendo otro TLD.

---

## 4. Marca registrada — búsqueda de nivel básico

> ## ⚠️ AVISO LEGAL, REPETIDO PORQUE IMPORTA
> **Esto NO es una búsqueda de marca legal y NO sustituye a un abogado de propiedad industrial.** Es una consulta a un registro público. Un despacho especializado evaluaría **marcas fonéticamente similares** (no solo idénticas), **marcas no registradas con derechos de uso previo** (*common law*), la **similitud de productos y servicios** dentro y entre clases, y jurisdicciones que aquí no se cubren. **Cualquier decisión de inversión en marca requiere esa búsqueda formal.** Lo de abajo sirve para una cosa: decidir si merece la pena pagarla.

**Método** `[V]`: consulta a la **API de búsqueda de TMview** (`www.tmdn.org/tmview/api/search/results`), el buscador oficial operado por la **EUIPO / TMDN** que agrega los registros de las oficinas nacionales de marcas, incluida la **USPTO** y la **EUIPO**. **Ejecutado el 2026-07-31**, oficinas `US` + `EM` (marca de la UE), filtrando resultados a las clases de Niza relevantes para software y servicios de negocio (**9, 35, 41, 42, 45**).

> **Por qué TMview y no la web de la USPTO:** el buscador nuevo de la USPTO (`tmsearch.uspto.gov`) es una SPA cuyo backend no es accesible sin navegador, la API TSDR exige clave (devuelve `401`), y las páginas de detalle de TMview están tras protección anti-bot. TMview **sí** expone su API de búsqueda, y es fuente oficial. Los campos citados abajo (nombre, oficina, estado, clases, titular, número de solicitud/registro, fechas) vienen de esa respuesta. **No pude recuperar los textos completos de productos y servicios de cada registro** — esa es una limitación real de este chequeo y otra razón por la que no sustituye a la búsqueda formal.

**Volumen bruto:** «qualify» → **153 resultados** en US+EM. «qualified» → **470 resultados**. «qualifyhq» → **0 resultados**.

### 4.1 EL HALLAZGO — «QUALIFIED» está registrada en clase 42 por Qualified, Inc.

| Campo | Valor |
|---|---|
| Marca | **QUALIFIED** |
| Titular | **Qualified, Inc.** |
| Oficina | USPTO (US) |
| **Estado** | **REGISTRADA** |
| **Clase de Niza** | **42** — servicios científicos y tecnológicos, **desarrollo de software y SaaS** |
| Nº de solicitud | **88587733** |
| **Nº de registro** | **6182886** |
| Fecha de solicitud | **2019-08-21** |

**Registros y solicitudes adicionales de la misma familia:**

| Marca | Titular | Clases | Estado | Nº |
|---|---|---|---|---|
| QUALIFIED AI | Qualified.com, Inc. | 35 | **Solicitada** (2024-01-25) | 98374712 |
| QUALIFIED AI | Qualified.com, Inc. | 42 | Finalizada | 98374715 |
| QUALIFIED | Qualified.com, Inc. | 42 | Finalizada (2020-09-29) | 90220304 |
| QUALIFIED | Qualified.com, Inc. | 35 | Finalizada (2020-09-29) | 90220297 |
| QUALIFIED | Qualified.com, Inc. | 35, 42 | Finalizada — **intento en la UE** (2021-03-29) | EM 018440850 |

> **Lectura.** El registro vivo que importa es **US 6182886, clase 42, «QUALIFIED», de Qualified, Inc.** — es decir, **la compañía de §3.1, la que Salesforce compró, tiene marca registrada concedida en Estados Unidos en la clase exacta del software como servicio.** El resto de la familia (los intentos de 2020-2021 y el `QUALIFIED AI` de 2024) muestra además que **defienden y amplían la cartera activamente**, incluyendo un intento de extenderla a la UE.
>
> Que «Qualify» y «Qualified» sean formas del mismo verbo es precisamente lo que un examinador o un abogado contrario evaluaría bajo el estándar de **probabilidad de confusión**. `[H]` **No estoy emitiendo un juicio legal** — no puedo y no debo. Estoy diciendo que **este es exactamente el escenario que un abogado de marcas señalaría como problemático**, y que quien decida ignorarlo debe hacerlo sabiéndolo, no por no haberlo mirado.

### 4.2 «QUALIFY» a secas en clases de software — el hueco existe, pero se está cerrando

| Marca | Titular | Clases | Estado | Nº solicitud | Fecha |
|---|---|---|---|---|---|
| **QUALIFY** | **ALPHASIX, LLC** | **9 + 42** | **SOLICITADA (pendiente)** | 99222183 | **2025-06-06** |
| **QUALIFY** | **TELESTREAM 2 LLC** | **42** | **SOLICITADA (pendiente)** | 99009932 | **2025-01-17** |
| QUALIFY | «Qualify» (titular homónimo) | **41** (educación/formación) | **REGISTRADA** — reg. 7723214 | 98632783 | 2024-07-03 |
| QUALIFY DIGITAL LABS | QUALIFY DIGITAL LABS LLC | **42** | **REGISTRADA** — reg. 6708570 | 90505681 | 2021-02-02 |
| QUALIFY DIGITAL LABS | QUALIFY DIGITAL LABS LLC | **35** | **REGISTRADA** — reg. 6708569 | 90505504 | 2021-02-02 |
| QUALIFY | Kaplan, Inc. | 38, 42 | Finalizada | 85773404 | 2012-11-07 |
| QUALIFY | 3D Systems, Inc. | 9 | Finalizada | 85058506 | 2010-06-09 |
| EMOVIS QUALIFY / emovis QUALIFY | EMOVIS S.A.S. | 9, 35 | **REGISTRADAS (UE)** | EM 018976454/5 | 2024-01-19 |
| Q-Qualify | NOVELLUS Marken GmbH | 35, 41, 42 | **REGISTRADA (UE)** | EM 019133781 | 2025-01-21 |

**Lecturas:**

1. **No encontré ningún registro vivo de «QUALIFY» a secas en clase 42 en EE. UU.** Los antiguos (Kaplan, 3D Systems) están finalizados. Ese hueco **es real** y es lo único favorable de esta sección.
2. **Pero hay dos solicitudes pendientes sobre ese mismo hueco, ambas de 2025** — ALPHASIX (clases 9 **y** 42) y Telestream (clase 42). `[H]` Si cualquiera de las dos se concede, el hueco se cierra. **No verifiqué el estado procesal actual de ninguna** (TMview solo dice «Filed»).
3. **La clase 41 ya está registrada** por un titular llamado literalmente «Qualify» (reg. 7723214, 2024). Formación, no software — pero ocupa la palabra desnuda en el registro estadounidense.
4. **QUALIFY DIGITAL LABS tiene registros concedidos en clases 42 y 35** desde 2021. Marca compuesta, no idéntica — pero es otro titular con derechos sobre la raíz en las clases de negocio.
5. **En la UE, marcas próximas ya concedidas**: `Q-Qualify` (clases 35/41/42), `EMOVIS QUALIFY` (9/35), `Qualifyze` (9/35/42, ChemSquare/Qualifyze GmbH), `Squalify` (9/35/36/42, de **Munich Re**). El espacio europeo está más poblado que el estadounidense.
6. **«QUALIFYHQ» no aparece en ningún registro (0 resultados).** QualifyHQ (§3.2) opera **sin marca registrada** en US ni EU. `[H]` Eso significa que no podrían bloquear formalmente por vía registral — pero sí podrían alegar uso previo, y en cualquier caso el conflicto comercial y de SEO existiría igual.

### 4.3 España y LATAM — donde el fundador opera hoy, y donde está PEOR que en EE. UU.

Consulta separada a TMview, oficinas **ES, MX, BR, CL, CO, AR, PE, UY**, término «qualify», **2026-07-31**. **58 resultados.** `[V]`

Esto importa más que US/EU para este proyecto concreto: según `docs/oferta-mercado-agencia-gestionada.md`, los clientes reales de hoy (inmobiliaria, PuntoServis) están en LATAM, no en Estados Unidos.

| Marca | Oficina | Clases | Estado | Titular | Nº registro |
|---|---|---|---|---|---|
| **QUALIFY** | **México** | **9** (software) | **REGISTRADA** | DAVIDE STIVOLI | **1677033** (2016) |
| **QUALIFY** | **Brasil** | **42** (SaaS) | **REGISTRADA** | BIOFARMA | **907901255** (2014) |
| **Qualify Informatica Ltda** | **Brasil** | **42** | **REGISTRADA** | T. STEFANINI INFORMÁTICA LTDA | 907488889 (2014) |
| QUALIFY ENGENHARIA E CONSULTORIA | Brasil | 42 | REGISTRADA | Qualify Engenharia e Consultoria EIRELI | 914629883 (2018) |
| QUALIFY | Brasil | 35 | REGISTRADA | TOMIX Comercio | 826467318 (2004) |
| Qualify | Brasil | 41 | REGISTRADA | Femptec (Río de Janeiro) | 909525730 (2015) |
| requalify | Brasil | 42 | REGISTRADA | Leonardo Fernandes Martins | 932587887 (2023) |
| Qualifyze | Brasil | 9, 35, 42 | Solicitada (2025-01-28) | Qualifyze GmbH | 501847720 |
| QUALIFY 9000 | Argentina | 9 | REGISTRADA | ANALYTE S.R.L. | 2571263 (2012) |
| QUALIFYMYDOCTOR / QMD | Argentina | 9, 35, 41 | REGISTRADAS | Claudia Cristina Acosta | 2822445-8 (2015) |
| EMOVIS QUALIFY | Chile | 9, 35 | REGISTRADA | EMOVIS S.A.S. | 1457495 (2024) |
| QUALIFY U | Colombia | 41 | Solicitada (2017) | QUALIFY U S.A.S. | SD2017/0085908 |
| **QUALIFY ATELOCIN** | **España** | **41** | REGISTRADA | Nicoleta Mirela Ionescu | M4264723 (2024) |

**Lecturas — y esto invierte el único dato favorable de §4.2:**

1. 🔴 **En México, «QUALIFY» a secas está REGISTRADA en clase 9 (software), viva desde 2016.**
2. 🔴 **En Brasil, «QUALIFY» a secas está REGISTRADA en clase 42 (SaaS), viva desde 2014** — más otras dos marcas «Qualify…» concedidas en la misma clase 42. **Brasil es la jurisdicción más cerrada de todas las examinadas.**
3. 🟢 **España es, con diferencia, la más limpia**: un único resultado, `QUALIFY ATELOCIN`, clase 41 (formación), compuesto y ajeno al software. `[H]` Si el mercado inicial fuera exclusivamente España, el riesgo registral sería bajo — pero no cubrí la marca de la UE aplicada a España vía EUIPO (§4.2 sí muestra `Q-Qualify` en clases 35/41/42 con efecto en toda la UE, **España incluida**), así que ni siquiera ahí está limpio del todo.
4. **Conclusión desagradable:** el hueco de clase 42 que existe en EE. UU. **no existe en Brasil ni en México**. Expandir el producto a los dos mercados hispano/lusohablantes más grandes bajo el nombre «Qualify» chocaría con registros ya concedidos.

### 4.4 Lo que esta sección permite concluir, y lo que no

**Permite concluir** `[V]`:
- Existe una marca **registrada y viva** en la clase del software (42) para **«QUALIFIED»**, propiedad de la empresa que Salesforce adquirió y que vende en la misma categoría.
- **«QUALIFY» a secas en clase 42 está libre de registros vivos en EE. UU. hoy**, con **dos solicitudes pendientes de 2025 apuntando a ese hueco**.

**NO permite concluir**:
- Si una marca «Qualify» para Qualify sería concedida o rechazada. Eso depende del texto exacto de productos y servicios, del examinador, y de las oposiciones — **ninguno de los tres cosa que yo pueda determinar**.
- Si Qualified/Salesforce actuaría. Es una decisión comercial suya, no un hecho consultable.
- El **texto exacto de productos y servicios** de ningún registro — las páginas de detalle de TMview están tras protección anti-bot. Sin ese texto, no se puede evaluar el solapamiento real de servicios, que es la mitad del análisis de confusión.
- El **estado procesal actual** de las solicitudes marcadas «Filed» (ALPHASIX, Telestream). Podrían haber sido concedidas, denegadas u opuestas desde entonces.
- Nada sobre **derechos de uso previo no registrados** (*common law*), que en EE. UU. pueden ser tan vinculantes como un registro.

---

## 5. Síntesis y recomendación

### 5.1 Tabla única de candidatos

Severidad: **ninguna** (no afecta) · **cosmética** (molesta, se rodea) · **competitiva directa** (mismo espacio de producto o marca registrada en la clase del software).

| Candidato | Estado | Fuente + fecha | Severidad |
|---|---|---|---|
| **Marca «Qualify» en el espacio GTM** | 🔴 **«QUALIFIED» registrada en clase 42 por Qualified, Inc. (reg. US 6182886), empresa adquirida por Salesforce, que se posiciona como *«agentic marketing platform»*** | TMview API (EUIPO/TMDN) + `qualified.com` + LinkedIn · 2026-07-31 | **COMPETITIVA DIRECTA** |
| **Marca «Qualify» en el espacio GTM** | 🔴 **QualifyHQ: cualificación de leads B2B, lookalikes desde URL, enriquecimiento de contactos, pricing por créditos 49-299 €/mes** | `qualifyhq.com` (home/pricing/features/use-cases) · 2026-07-31 | **COMPETITIVA DIRECTA** |
| **Marca «Qualify» en BR / MX** | 🔴 «QUALIFY» a secas **registrada**: Brasil cl. 42 (reg. 907901255), México cl. 9 (reg. 1677033) | TMview API · 2026-07-31 | **COMPETITIVA DIRECTA** |
| **Marca «Qualify» en el espacio GTM** | 🟠 «Qualify» (DE), automatización de ventas, 30 seguidores LinkedIn | `linkedin.com/company/getqualify` · 2026-07-31 | Competitiva (menor) |
| **Marca «Qualify» en sales-tech** | 🟠 «Qualify.ai», agente de voz IA para verificación/cualificación, 3 seguidores | `linkedin.com/company/qualifyapp` · 2026-07-31 | Competitiva (menor) |
| **Marca «Qualify» en clase 42 US** | 🟡 Sin registro vivo, **pero 2 solicitudes pendientes de 2025** (ALPHASIX cl. 9+42; Telestream cl. 42) | TMview API · 2026-07-31 | Cosmética hoy, riesgo abierto |
| `qualify.com` | 🟡 Registrado 1999, **en uso**: comparador de préstamos a pymes, 1.000+ clientes | WHOIS Verisign + `www.qualify.com` · 2026-07-31 | Cosmética (SEO) |
| `qualify.io` | 🟡 Registrado, **a la venta** (Afternic). Precio no obtenido | WHOIS + DNS + lander · 2026-07-31 | Cosmética (coste) |
| `qualify.app` | 🟡 Registrado, **a la venta** (Dan.com). Precio no obtenido | DNS + lander · 2026-07-31 | Cosmética (coste) |
| `qualify.co` | 🟡 Registrado, **a la venta** (Spaceship) | WHOIS + `<title>` de la página de venta · 2026-07-31 | Cosmética (coste) |
| `qualify.ai` | 🟠 Registrado, sin web, **Google Workspace activo** → en uso. `[H]` probablemente de Qualify.ai (§3.3) | WHOIS Namecheap + `dig MX/TXT` · 2026-07-31 | Cosmética/competitiva |
| `getqualify.com` | 🟡 Registrado 2005, sin resolución DNS, sin web | WHOIS Verisign + `dig` · 2026-07-31 | Cosmética |
| `qualifyapp.com` | 🟡 Registrado 2014, origen sin responder | WHOIS Verisign + `curl` · 2026-07-31 | Cosmética |
| `qualifyhq.com` | 🔴 Registrado 2024, **es el sitio del competidor** | WHOIS + web · 2026-07-31 | **COMPETITIVA DIRECTA** |
| `usequalify.com` | 🟡 Registrado **2026-01-30**, Unstoppable Domains | WHOIS Verisign · 2026-07-31 | Cosmética |
| `tryqualify.com` | 🟡 Registrado 2024, **a la venta** (Afternic) | WHOIS + lander · 2026-07-31 | Cosmética (coste) |
| Handle **X** `@qualify` | 🟡 **Ocupado** (HTTP 200 vs. 404 calibrado), perfil vacío | `x.com/qualify` · 2026-07-31 | Cosmética |
| Handle **X** `@qualifyhq` / `@qualifyapp` / `@getqualify` | 🟡 **Los tres ocupados** (QualifyHQ; «Qualify App»; empresa de selección de personal) | `x.com/*` · 2026-07-31 | Cosmética |
| Handle **YouTube** `@qualify` | 🟢 **LIBRE** (404) | `youtube.com/@qualify` · 2026-07-31 | Ninguna |
| Handle **LinkedIn** `/company/qualify` | 🟢 **LIBRE** (404) | `linkedin.com/company/qualify` · 2026-07-31 | Ninguna |
| Handles **IG / TikTok / Facebook** | ⚪ **NO VERIFICADOS** — las tres plataformas bloquean la comprobación anónima | intentos documentados en §2.2 · 2026-07-31 | Desconocida |

### 5.2 Recomendación

> ## **«Qualify», tal cual, NO es viable para salir al mercado público en la categoría CRM/GTM.**
>
> Y lo digo con todas las letras, como se me pidió: **el conflicto más grave es competitivo directo, no cosmético.**

**Las cuatro razones, en orden de peso:**

1. **Existe «Qualified», propiedad de Salesforce, con marca REGISTRADA en la clase 42 (software/SaaS) en EE. UU., que se autodenomina plataforma de *agentic marketing* — la misma frase con la que Qualify se describe a sí misma en su propio `README.md`.** «Qualify» y «Qualified» son el infinitivo y el participio del mismo verbo. Esto no es «un nombre parecido en otro sector»: es casi el mismo nombre, en la misma categoría, con el titular de marca más capaz de defenderlo que existe en el software empresarial. **Este solo punto ya cierra la pregunta.**
2. **Existe «QualifyHQ», un producto vivo de cualificación de leads B2B** con lookalikes desde una URL, enriquecimiento de contactos y **pricing por créditos** — solapando la Fase 4 y la Fase 5 del roadmap y **el mismo modelo de monetización planeado**. Y su existencia **cierra también la variante de escape «Qualify HQ»** que el propio brief planteaba.
3. **Los diez dominios candidatos están tomados.** Los tres adquiribles lo son a precio de mercado secundario, no de registro. No hay una salida barata por la vía del dominio.
4. **En Brasil y México, «QUALIFY» a secas ya está registrada en las clases del software.** Los dos mercados hispano/lusohablantes más grandes están cerrados por vía registral, no solo por saturación comercial.

**Y una razón de fondo, independiente de los conflictos:** «qualify» es el verbo nuclear del vocabulario de la propia categoría (*qualify a lead*, *qualified lead*, *MQL/SQL*). Es descriptivo del servicio, lo que lo hace **débil como marca y prácticamente inbuscable**. Lo comprobé sin querer durante esta misma investigación: al buscar los competidores por nombre, el buscador devolvió artículos genéricos sobre cómo cualificar leads. **Si yo, buscándolo a propósito, no encuentro el producto, un cliente tampoco.**

### 5.3 Qué hacer con esto — opciones, sin decidir por el fundador

**Lo que NO hay que hacer:** tocar el código. «Qualify» como nombre interno de repositorio, paquetes y módulos **no tiene ningún problema** y renombrarlo sería trabajo puro sin valor. Esto es exclusivamente una decisión de marca de cara al mercado, y puede tomarse el día del lanzamiento público sin coste técnico acumulado.

Tres caminos, con lo que cada uno realmente cuesta:

| Camino | Qué implica | Coste real |
|---|---|---|
| **A. Nombre nuevo para el mercado** | El repo sigue llamándose Qualify; el producto sale con otro nombre | El más seguro. Cuesta una ronda de naming y **repetir este chequeo** sobre los nuevos candidatos — barato ahora, carísimo después de tener clientes y SEO |
| **B. «Qualify» + calificador fuerte** | No `Qualify HQ` (ocupado). Requeriría un segundo término distintivo y no descriptivo | Reduce el riesgo registral pero **no resuelve la colisión con Qualified/Salesforce ni el problema de inbuscabilidad** |
| **C. Seguir con «Qualify»** | Aceptar el riesgo | Defendible **solo** mientras sea preproducto y sin ingresos. El riesgo no se materializa por demanda sino por **suspensión en App Review de Meta, Google Ads, App Store o marketplaces** ante una reclamación de marca — donde se suspende primero y se pregunta después |

**Lo que sí recomiendo sin reservas, sea cual sea el camino:** si se va a invertir dinero de marca en cualquier nombre, **pagar una búsqueda formal a un abogado de propiedad industrial antes**. Este documento sirve para decidir si merece la pena pagarla. Dado el hallazgo de §4.1, merece la pena.

**Si se elige un nombre alternativo, este es el chequeo mínimo a repetir** (todo reproducible con lo hecho aquí): WHOIS de registro para los TLD objetivo · `dig` A/MX (el caso `qualify.ai` demuestra que «no carga web» ≠ «libre») · códigos HTTP en X y YouTube **con la calibración de §2.1** · `linkedin.com/company/<slug>` · TMview API en US, EM, ES, MX, BR filtrando clases 9/35/42 · y la comprobación manual de Instagram, TikTok y Facebook, que **no es automatizable** (§2.2).

### 5.4 Qué queda sin cerrar

| Hueco | Por qué | Cómo cerrarlo |
|---|---|---|
| Handles en **Instagram, TikTok y Facebook** | Las tres bloquean la verificación anónima (§2.2) | 12 comprobaciones manuales en navegador con sesión iniciada, ~30 s cada una |
| **Precio** de `qualify.io`, `.app`, `.co` | Los landers de Afternic/Dan/Spaceship exigen interacción de navegador | Abrir cada lander y pedir precio |
| Textos de **productos y servicios** de los registros de marca | Páginas de detalle de TMview con protección anti-bot | Búsqueda formal de abogado (necesaria de todos modos) |
| Estado procesal de **ALPHASIX 99222183** y **Telestream 99009932** | TMview solo dice «Filed» | USPTO TSDR con clave de API, o el abogado |
| Titularidad real de `qualify.ai`, `getqualify.com`, `qualifyapp.com` | Privacidad de registrador | Broker de dominios, si alguno interesara |
