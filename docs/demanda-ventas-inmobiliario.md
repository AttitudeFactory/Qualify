# Demanda de compra — segmento inmobiliario (ensayo de ventas)

> ⚠ **AVISO DE NIVEL DE EVIDENCIA — LEER ANTES DE CITAR ESTE DOCUMENTO.**
> Este documento contiene **conversaciones de venta ensayadas** y **hipótesis de demanda**, no evidencia de mercado validada.
> - Las secciones §1-§3 son **cosecha pública cruda**: citas literales con URL y fecha de acceso. Eso sí es material verificable de terceros, pero es *voz de usuario de otras herramientas*, no de un prospecto de Qualify.
> - Las secciones §4-§7 son **simulación**. Ningún prospecto real dijo lo que ahí aparece.
> - Toda afirmación está etiquetada `[H]` (hipótesis) salvo que lleve `[V]`, que **solo el fundador puede asignar** tras confirmar que un prospecto real lo dijo.
> - Este documento **no** es un backlog. `product-owner` es el único que escribe `docs/backlog-*.md`. Lo que aquí hay es una **cola de qué validar**, no de qué construir.
>
> Autor: `sales-consultant` (consultor externo, eje demanda). Sesión 2026-07-29, **recalibrado 2026-07-30**.
> Ejes hermanos de la misma sesión: `gtm-specialist` (oferta / herramientas que ya sirven al nicho), `market-opportunity-analyst` (vector de mercado).

---

## §0 — RECALIBRACIÓN 2026-07-30: el comprador es LATAM, la cosecha es estadounidense

**Léelo antes que cualquier otra sección. Cambia cómo hay que leer §1-§3 enteras.**

Cuando escribí §1-§3 asumí implícitamente un comprador estadounidense, porque es de donde viene todo el corpus público de reseñas. **Es el mercado equivocado.** `gtm` verificó y el lead confirmó:

- **El cliente que paga es una agencia inmobiliaria en URUGUAY** (tenant `country='UY'`). El tenant hermano es una tienda en **Cúcuta, Colombia**. Fuente: `docs/oferta-mercado-inmobiliario.md` §5 y `docs/backlog-crm-workflows.md` §0.
- **La franquicia NO paga el software centralmente.** *"El franquiciado asume los costos"* (Forbes Uruguay sobre RE/MAX AR&UY, vía `docs/oferta-mercado-inmobiliario.md` §5). Cada oficina es económicamente independiente.
- **El techo de gasto es de otro orden de magnitud.** El cliente uno gasta **$50-185/mes en software de toda la empresa**, ~5 asientos (`docs/oferta-mercado-inmobiliario.md` §2.1). Para comparar: el precio de lista de BoldTrail (~$5.988/año) equivale al ~63% del gasto anual **total** de negocio del agente mediano estadounidense ($9.530, NAR 2025, §2.3 del mismo doc).

### Tres consecuencias, y ninguna es cosmética

**1. Toda §1-§3 queda reetiquetada como `[H-US]` — "análogo estadounidense, equivalente LATAM sin confirmar".** No la borro: sigue siendo la mejor evidencia disponible sobre **la forma general de la categoría** (qué se rompe en un CRM inmobiliario, qué pide un coordinador de marketing, qué queman las herramientas de contenido automático). Pero **ninguna cita de §1-§3 es evidencia sobre el comprador real de Qualify**, y ninguna debe usarse en una llamada como si lo fuera.

**2. No existe atajo de cosecha para LATAM, y esto está confirmado por dos vías independientes.** Yo no encontré corpus LATAM; `gtm` llegó a lo mismo por su cuenta: **Tokko** — que se describe a sí mismo como *"el CRM #1 de América Latina"* — **tiene exactamente dos reseñas públicas**; InfoCasas, Wasi y Metrocuadrado no publican precios ni reseñas. Por mi propia regla constitucional, **la fuente falta y me detengo**: no voy a fabricar dolor uruguayo. Lo que sí cambia es el método — ver la consecuencia 3.

**3. "Validar con un prospecto real" deja de ser el último recurso y pasa a ser la ÚNICA vía.** En el régimen estadounidense se puede minar reseñas antes de hablar con nadie. **Para este comprador no se puede.** Eso reordena §6 entera: las filas dejan de rankearse por "baratura de minar" y pasan a rankearse por **cuánta incertidumbre elimina una sola pregunta al cliente uno**. La cola revisada está en §6.

### La pregunta que ahora domina todo lo demás

`gtm` la formuló y no la puede responder; me la pasa el lead como pregunta central del eje demanda:

> **La escucha social vertical para inmobiliario no existe en LATAM/España** — no es que exista y sea mala, es que **la categoría está ausente** (las fuentes en español que dicen "escucha social inmobiliaria" describen scheduling tipo Buffer/Hootsuite). ¿Es whitespace, o **es que no cabe bajo el techo**? Un solo asiento de una herramienta de listening genérica (Exolyt $400-950/mes, Sprout $249+/asiento) **cuesta más que el presupuesto de software de toda la empresa del cliente uno**.

Mi respuesta, con el razonamiento en §6.2: **`[H]` es principalmente lo segundo, y el hecho de que las dos explicaciones sean indistinguibles desde fuera es en sí mismo el hallazgo.** Ver §6.2, que es la sección que hay que leer si solo se lee una.

---

## Índice

- §1 — Cosecha cruda: reseñas de 3 estrellas y "ojalá hiciera X" *(hecho)*
- §2 — Hilos de comunidad de agentes y posts de migración *(hecho, con un hueco de fuente declarado)*
- §3 — Changelogs de competidores y ofertas de empleo *(hecho — contiene el hallazgo más urgente del eje)*
- §4 — Tres conversaciones de lead ensayadas *(hecho)*
- §5 — Biblioteca de objeciones *(hecho)*
- §6 — Cola de requisitos rankeada *(hecho — entregable principal)*
- §7 — Criterios de calificación y descalificación *(hecho)*

---

## §1 — Cosecha pública cruda: reseñas de 3 estrellas y "ojalá hiciera X"

**Método declarado:** minado de reseñas (skill `customer-research`, Modo 2 — "digital watering holes"), sesgado deliberadamente hacia reseñas de 1-3 estrellas y hacia el campo "Cons", porque ahí es donde el comprador escribe el requisito insatisfecho. Las reseñas de 5 estrellas se ignoran salvo cuando su campo "Cons" contradice la nota.

**Sesgo de muestra conocido (declararlo antes de usar esto):** los sitios de reseñas sobre-representan al usuario furioso y al power user. Nada aquí prueba prevalencia. Prueba **existencia** de un requisito y aporta **el lenguaje literal del comprador**, que es para lo que se cosecha.

**Todo esto es material de terceros, no evidencia sobre Qualify.** Etiqueta: cosecha verificable (URL + fecha), interpretación `[H]`.

> ⚠ **REETIQUETADO POR §0 (2026-07-30): toda §1 es `[H-US]` — "análogo estadounidense, equivalente LATAM sin confirmar".** Las herramientas cosechadas (Roomvu, Follow Up Boss, BoldTrail, Lofty, Back At You) son del régimen estadounidense y sus reseñistas son agentes estadounidenses. El comprador real de Qualify es uruguayo. Estas citas describen **la forma de la categoría**, no a nuestro comprador. Ninguna es utilizable en una llamada como evidencia sobre él.

### 1.1 — Roomvu (contenido/vídeo automatizado + publicación para agentes inmobiliarios)

Categoría: exactamente el vecino más cercano a lo que Qualify haría si publicara contenido por el agente. **2,5/5 en Capterra** — la nota más baja de todo lo cosechado, y es la categoría más adyacente a nosotros. Eso es una señal, no ruido.

Fuente: https://www.capterra.com/p/218588/roomvu/reviews/ — accedido 2026-07-29.

| Cita literal | Quién / cuándo | Requisito que revela |
|---|---|---|
| "It is a low quality, repetitve, automated IA system postinf the same info with a lot of mistakes, low quality visuals." | VR, CEO, 1,0 — abril 2026 | El contenido autogenerado genérico **destruye** la percepción de valor |
| "it is very generic information and some times not very accurate and you do not have much control of it." | Wisam Askar, Broker, 1,0 — abril 2026 | Exigen **control** sobre lo que sale a su nombre + exactitud |
| "Some videos that all agents are using at the same time." | Kamyab G., Broker, 1,0 — abril 2023 | El contenido de plantilla compartida es **anti-diferenciación**: el agente compite con sus vecinos con el mismo vídeo |
| "the posts in my social media are with typos, and I upgraded to be able to link to my YouTube channel but it does not work." | Kathia P., Realtor, 1,0 — noviembre 2023 | La publicación multicanal se vende y no funciona |
| "if I list a house on weekend I can't advertise it till working day" | Ana M., Realtor, 5,0 (contra en reseña positiva) — mayo 2024 | El trabajo inmobiliario ocurre **en fin de semana**; la herramienta asume horario de oficina |
| "The platinum/branding/diamond subscription is a scam. They don't do any effort for design or add up only a few templates." | Ava K., 2,0 — junio 2025 | El upsell por tiers de plantillas no sostiene precio |
| "Roomvu's support has been incredibly frustrating…broken promises and a dropped call." / "It is impossible to reach a live person unless you set up a Zoom call" | Harold B., Realtor, 1,0 — junio 2026 / Filomena C., Realtor, 2,0 — agosto 2025 | Soporte humano accesible es parte del producto en este nicho |

**Lectura `[H]`:** la categoría "IA que publica por ti en inmobiliario" ya existe, ya se vendió, y **ya quemó a los compradores**. El agente inmobiliario que se encuentre a Qualify va a traer esta cicatriz puesta. Dos consecuencias directas: (a) "generamos y publicamos contenido por ti" es un pitch **desprestigiado** en este nicho, no un pitch nuevo; (b) el requisito literal que emerge — *control, exactitud, no-genérico* — encaja con la postura de Qualify de respuestas **asistidas** (borrador + aprobación humana) y con el principio "leer el contenido, no el perfil". Es la coincidencia más fuerte encontrada entre una queja documentada y una decisión ya firmada.

### 1.2 — Follow Up Boss (CRM inmobiliario, el más querido de la categoría)

Fuente: https://www.capterra.com/p/130020/Follow-Up-Boss/reviews/ — accedido 2026-07-29. G2: https://www.g2.com/products/follow-up-boss/reviews — accedido 2026-07-29.

| Cita literal | Quién / cuándo | Requisito que revela |
|---|---|---|
| "I wish it had more automations and allowed to send batch text messages." / "I wish it could include auto create newsletters/relevant emails" | Jodi L., Broker Associate — febrero 2026 | Demanda de **saliente masivo**, no de escucha |
| "Not a way to capture leads within the software" | Monica Y., Realtor — abril 2020 | La captación vive fuera del CRM |
| "only good for overseeing…We have had to make our own external reporting system" | Menucha S., Head of IT — julio 2023 | El reporting agregado (nivel brokerage) es un hueco real |
| "It's a little pricey, especially if you want to add more users" / "The price. It's very expensive" | Linda G., Broker Associate — julio 2026 / Lisa L., Owner — diciembre 2025 | **Techo de precio por asiento** en el segmento (cruzar con el eje `gtm`) |
| "would be great if they integrated with social media and WhatsApp for communication" | reseña G2 (vía índice de búsqueda, no verificada literalmente en página) — 2026 | Demanda de canal social/WhatsApp *dentro* del CRM |
| Constatación estructural: FUB **no tiene** scheduling, creación ni gestión de contenido social nativa | — | El CRM líder deja el hueco social **abierto** |

**Aviso de trazabilidad:** la fila de WhatsApp/social viene del resumen del índice de búsqueda de G2, **no** la verifiqué palabra por palabra en la página de reseñas (G2 sirve las reseñas tras JS/paywall parcial). La marco como **cita de segunda mano** — no debe usarse como quote literal en un pitch hasta verificarla.

### 1.3 — BoldTrail (ex kvCORE, Inside Real Estate) — la suite todo-en-uno del brokerage

Fuente: https://www.capterra.com/p/176447/BoldTrail/reviews/ — accedido 2026-07-29.

| Cita literal | Quién / cuándo | Requisito que revela |
|---|---|---|
| "DO NOT pay for their Lead 350 program as it bogs down you email and text messages with bogus leads" | Liana N., Broker-Associate, 1,0 — enero 2026 | **Calidad de lead > volumen de lead.** El comprador ya está saturado de leads basura |
| "Support is extremely slow, often unresponsive, and tickets can remain open for months" | Jessica G., Sales & Marketing Manager, 1,0 — octubre 2025 | |
| "Many key features don't work as advertised, including basic site functionality" | Jessica G., 1,0 — octubre 2025 | |
| "The CMS is terrible and buggy…videos not even matching the current layout" | Will S., Realtor, 1,0 — mayo 2024 | |
| "When I tried to [cancel], I was left in limbo and my cancellation request was denied" | Sara G., Sales Associate, 2,0 — enero 2026 | **Fricción contractual** es un motivo de cambio activo — y por tanto una puerta de entrada |
| "The support is horrendous, they may up answers, a solution that should take 10 minutes is an all day event" | Raymond K., Realtor, 1,0 — septiembre 2025 | |

**Lectura `[H]`:** el dolor dominante en la suite todo-en-uno **no es funcional, es de servicio y de contrato**. Eso es incómodo para nosotros: no se cierra con features. Ver §5 (objeción "¿y si desaparecéis?").

### 1.4 — Lofty (ex Chime) — el que más se parece a "CRM con IA"

Fuente: https://www.capterra.com/p/157457/Lofty/reviews/ — accedido 2026-07-29.

| Cita literal | Quién / cuándo | Requisito que revela |
|---|---|---|
| "AI assistant is robotic, unable to be instructed and unreliable" | Meghan R., Realtor (5 años) — 16 enero 2026 | **La barra de la IA conversacional ya se falló públicamente en este nicho.** "Instruible" y "fiable" son los dos adjetivos que el comprador pide |
| "not super crazy about the AI contact feature" | Heidi C., Agent — 28 enero 2026 | |
| "AI Assistant? Extra. CMA tool? Extra. Home values? Extra" | Meghan R. — 16 enero 2026 | Rechazo al desglose por add-ons |
| "accounts don't sync well from computer to phone, which causes me to miss messages" | Jenn E., Realtor — 5 febrero 2026 | **Móvil no es opcional**: el agente trabaja desde el coche |
| "texting never worked properly" | Bob J., Team Lead — 1 abril 2026 | |
| "insanely convoluted to use and not at all intuitive, app and desktop" | Rebecca D., Realtor — 24 febrero 2024 | **Umbral de complejidad**: este comprador abandona ante una UI densa |
| "SEO features…challenging and do not function the way they are advertised" | Tavarus M., Realtor — 30 enero 2026 | |

### 1.5 — Back At You / Zentap (social media verticalizado para inmobiliario)

Fuentes: https://www.capterra.com/p/131534/Back-At-You/reviews/ · https://unifyrealestate.com/social-media/back-at-you-media/ · https://hooquest.com/social-media/back-at-you-media/ — accedidos 2026-07-29.

Hallazgos (de agregadores/comparadores, **no** todos verificados como cita literal de reseña — marcados como tal):

- Contenido **template-driven** en vez de gráficos locales personalizados; sin edición de vídeo profesional, sin **workflow de aprobación de contenido**, sin coaching. *(fuente: comparador unifyrealestate, no reseña de usuario — segunda mano)*
- Reseñas negativas centradas en **falta de leads generados**, sobre todo en planes bajos que "no están diseñados para lead gen". *(segunda mano)*
- Zentap: valoración alta (≈4,9) con quejas poco visibles públicamente → **no puedo cosechar dolor aquí**; lo digo en vez de inventarlo.

**Fuente que falta y no voy a fabricar:** no encontré un corpus público de reseñas de 3 estrellas con volumen suficiente para "listing-to-video" puro (Highnote, Coffee & Contracts, Luxury Presence tienen poca o ninguna cobertura en G2/Capterra). Si el eje `gtm` inventaria herramientas de esa sub-categoría, **su demanda queda sin anclar** en este documento y debe tratarse como hueco, no como ausencia de dolor.

### 1.6 — Los cuatro requisitos que se repiten en 3+ fuentes independientes (confianza Alta, en el sentido de `customer-research`)

Nótese que "confianza Alta" aquí significa *el tema aparece consistentemente en la cosecha*, **no** que sea un requisito validado para Qualify.

1. **Control y exactitud sobre lo que se publica en mi nombre** — Roomvu ×4, Back At You (aprobación de contenido ausente), Lofty ("unable to be instructed"). Es el tema más denso de toda la cosecha.
2. **Calidad de lead, no volumen** — BoldTrail ("bogus leads"), Back At You ("lack of leads"), FUB ("no way to capture leads").
3. **No-genérico / diferenciación local** — Roomvu ×3 (mismo vídeo para todos los agentes, información genérica), Back At You (plantillas vs. gráficos locales).
4. **Simplicidad y móvil** — Lofty ×3, BoldTrail ("cumbersome"), FUB (calendario móvil).

Y un quinto que no es un requisito de software y conviene no olvidar: **soporte humano alcanzable** aparece en las cuatro herramientas cosechadas. Un producto de un solo fundador compite mal ahí y bien ahí a la vez — ver §5.

### 1.7 — Cosecha LATAM: lo poco que existe, y lo que confirma (añadido 2026-07-30)

Tras la recalibración de §0 hice una pasada específica buscando fuentes uruguayas/colombianas/mexicanas. **Confirmo de forma independiente el hallazgo de `gtm`: no hay corpus.** Las búsquedas en español devuelven casi en exclusiva **blogs de los propios proveedores** (blog.wasi.co, blog.tokkobroker.com, propio.com.uy, inmogesco, nocnok) — contenido de marketing con forma de consejo, **cero voz de cliente**. Declaro el hueco por mi propia regla y no lo relleno.

**Excepción — la única fuente LATAM de primera mano que encontré**, y merece la pena por dos motivos:

Fuente: https://www.comparasoftware.com/tokko-broker — accedida 2026-07-30. **Tokko Broker** se autodenomina *"el CRM #1 en América Latina"*, +4.200 profesionales.

| Hallazgo | Detalle |
|---|---|
| **Reseña negativa, literal** | *"Mala experiencia, no recomendado a ningún asesor inmobiliario."* — Herbert Suiney (Suiney Realty Inmobiliaria), **2/5, 07-01-2025**. Motivo citado: problemas con la entrega de información de clientes. |
| **Patrón de quejas** | El punto débil declarado es **la consistencia del soporte**: demoras de días en responder correos, llamadas o mensajes; clientes que describen tener que *"rogar"* para que se resuelvan problemas técnicos. |
| **⭐ Precios reales LATAM (México)** | Personal (1 usuario) **$480 MXN/mes** · Duo (2) **$990** · **Equipo (3-5) $1.999 MXN/mes** · Enterprise (6-10) $3.499 |

**Dos conclusiones, y la segunda es la importante:**

1. **`[H]` La queja LATAM de primera mano que existe es la misma que domina la cosecha estadounidense: el soporte.** §1.6 punto 5 se sostiene en los dos regímenes — es el único requisito de todo el documento con anclaje **a ambos lados**. Y es **R7**, la fila que cuesta cero código.
2. **⭐ El precio confirma el techo desde una dirección independiente.** El plan Equipo (3-5 usuarios) son **$1.999 MXN/mes ≈ $100-110 USD/mes** — cae **dentro** del rango $50-185/mes que `gtm` observó en el cliente uno, y lo hace por una vía distinta (lista de precios pública del líder de categoría LATAM, no gasto declarado de un cliente). **Dos mediciones independientes convergen en el mismo orden de magnitud**, lo que refuerza notablemente el argumento de §6.2: el techo es real y es estructural del mercado, no una peculiaridad de este cliente.

---

## §2 — Comunidad de agentes y posts de migración

### 2.0 — HUECO DE FUENTE, DECLARADO ANTES QUE NADA

**No pude cosechar Reddit.** `r/realtors`, `r/RealEstate` y similares están **bloqueados para el user-agent de esta herramienta** (la API de búsqueda devuelve error explícito: *"The following domains are not accessible to our user agent: ['reddit.com']"*, y `WebFetch` sobre `old.reddit.com` falla igual). Verificado 2026-07-29.

Esto importa porque el brief pedía precisamente ese material, y porque Reddit es donde el lenguaje del agente inmobiliario es más crudo. **No lo he sustituido por invención.** Consecuencias que hay que asumir:

- Cualquier cita de Reddit en este documento sería fabricada. **No hay ninguna.**
- El material de §2 viene de un sustituto estructurado (abajo) que es más pobre en lenguaje pero igual de trazable.
- **Acción para un humano, no para un agente:** una hora de lectura manual de `r/realtors` filtrando por "social media", "CRM", "leads" y ordenando por top/año produciría el corpus que falta. Es la pieza de investigación más barata pendiente en todo este eje.

Lo mismo aplica a Trustpilot (HTTP 403) y a la página de reseñas de G2 (bloqueada tras JS). **G2 no está cosechado literalmente en este documento**, solo vía resúmenes de índice de búsqueda, y eso lo he marcado en cada fila donde ocurre.

### 2.1 — Sustituto: el campo "Switched From / Reasons for Switching" de Capterra

Es el equivalente estructurado del post de migración: el reseñista declara **de qué producto venía y por qué se cambió**. Menos lenguaje, misma información de requisito insatisfecho.

Fuentes: https://www.capterra.com/p/130020/Follow-Up-Boss/reviews/?page=2 · https://www.capterra.com/p/176447/BoldTrail/reviews/?page=2 — accedidos 2026-07-29.

**Hacia Follow Up Boss (el CRM "querido"):**

| Venía de | Motivo declarado (literal) | Quién / cuándo |
|---|---|---|
| BoomTown | "it had more customizable features" | Yola S., Concierge Manager — nov 2023 |
| LionDesk | "My company uses Follow up boss" | Dustin C., Advisor — oct 2023 |
| Lofty | competidor con capacidades "way better" y "IDX connection" | Sandra O., Consultant — dic 2022 |
| Zoho Mail | "ease of use" | Sales Rep — jul 2021 |

**Hacia BoldTrail:** venían de CINC (×2), MoxiEngage, DELTA, IXACT Contact, Sage CRM, LionDesk, **Follow Up Boss**, y hasta Google Cloud Storage. Motivos declarados:

- "I did a lot of research beforehand and I really liked what I saw with kcCORE." — Charles G., Broker
- **"False promises from KvCore about customer support and account management during sales pitch"** — Gabi M., Director of Business Development *(reseñista que se cambió y se arrepintió)*
- "Switched to eXp; kvCore came as standard CRM offering." — Matthew G., Agent

### 2.2 — Las tres cosas que estos movimientos dicen, y que van en contra del pitch obvio

**`[H]` Hallazgo 1 — el CRM no se elige: se hereda del brokerage.** Dos de las migraciones documentadas no son decisiones de compra en absoluto: *"My company uses Follow up boss"* y *"Switched to eXp; kvCore came as standard CRM offering"*. El agente individual **no compra CRM, lo recibe**. Si Qualify apunta al agente individual, no compite con Follow Up Boss — compite con el presupuesto discrecional que le queda al agente **después** de la herramienta que su brokerage ya le impuso. Es una conclusión aburrida y cambia el tamaño del cheque.

**`[H]` Hallazgo 2 — nadie se cambia por "escuchar la conversación".** En cero de las migraciones cosechadas el motivo declarado es analítica, listening, sentimiento o descubrimiento de creadores. Los motivos son: personalización, facilidad de uso, conexión IDX, y **el mandato del brokerage**. La propuesta de valor nuclear de Qualify (*leer el contenido primario, no el perfil*) **no aparece como razón de cambio en ninguna fuente cosechada**. Esto no la invalida; dice que **no es el motivo de compra**, y que si lidera el pitch, el pitch falla. Es el input directo para la ronda adversarial con `opportunity`.

**`[H]` Hallazgo 3 — el mayor motor de cambio es el agravio de servicio y contrato, no la feature.** "False promises during sales pitch", "cancellation request was denied", "tickets open for months". El evento disparador de compra en esta categoría es **estar enfadado con el proveedor actual**, no descubrir una capacidad nueva. Implicación de venta: el mejor momento para entrar es la renovación anual del brokerage, y la mejor pregunta de discovery no es "¿qué te falta?" sino **"¿qué te prometieron que no cumplieron?"**.

### 2.3 — Watering holes alternativos evaluados (y por qué rinden poco)

- **BiggerPockets** (https://www.biggerpockets.com/forums/21-real-estate-agents, accedido 2026-07-29): audiencia sesgada a **inversor**, no a agente-como-marketer. Poco material sobre dolor de herramientas de contenido.
- **ActiveRain**: mayoritariamente blogging SEO de agentes, no discusión de herramientas.
- **Contenido de comparación tipo "X vs Y"** (relaxedagent, theprotoolkit, socialrealtr, unifyrealestate): **es marketing de afiliación**, no voz de cliente. Lo he usado solo para hechos estructurales verificables (p. ej. "Follow Up Boss fue adquirido por Zillow"), nunca como cita de dolor.

---

## §3 — Changelogs de competidores y ofertas de empleo

Premisa del método: **una feature enviada es una demanda de mercado hecha visible** — alguien empujó lo bastante fuerte como para ganársela. Y **la lista de responsabilidades de una oferta de empleo es una lista de requisitos** para el software que reemplazaría (o asistiría) a ese puesto.

### 3.1 — ⚠ HALLAZGO URGENTE: Lofty envió un "AI OS" con un **Social Agent** el 28 de julio de 2026 — hace un día

Esto invalida cualquier suposición de que el espacio "IA agentiva sobre social para inmobiliario" está vacío. Lo escribo aquí en disco además de avisar al lead, porque afecta a los tres ejes de esta sesión.

Fuentes: https://www.rismedia.com/2026/07/28/lofty-expands-agentic-ai-os-real-estate-cowork/ (28 julio 2026) · https://lofty.com/feature/news-and-updates (accedido 2026-07-29) · https://www.realestatenews.com/2026/02/03/lofty-breezy-unveil-ai-operating-systems (3 febrero 2026) · https://www.housingwire.com/articles/lofty-expands-ai-platform-launches-house-ai-for-homebuyers/.

Lo que Lofty **ya vende hoy**, con el lenguaje de su propia web:

| Producto Lofty | Descripción literal de Lofty | Solapamiento con Qualify |
|---|---|---|
| **Social Agent** | "Your always-on digital marketing assistant, to amplify your brand across social media" | Directo con Parte 4-A/4-B |
| **Social Studio** | "Put social on autopilot with a fully automated social media marketing tool"; scheduling nativo + "Quick Post block…content can be shuffled to generate new ideas" | Directo con publicación programada |
| **Lofty Blast** | Convierte "a new listing into Facebook & Instagram ads and email" | Listing→contenido, más pauta (fuera de nuestro alcance) |
| **Lofty AOS / Cowork** (jul 2026) | Chat que "replaces a dashboard full of widgets with prioritized, ready-to-execute tasks"; bloques **"Your Morning Read"** y **"What Needs You Now"**, que "identifies activities **requiring human action**" | Directo con la tesis agentiva de LangGraph |
| Copilots especializados | "sales agent, social agent, and homeowner agent" + agentes personalizados | |

**Dos lecturas, y la segunda es la buena:**

1. La mala: el incumbente vertical con distribución ya ocupa el terreno. "IA que te ayuda con lo social" **no es un pitch diferenciado en inmobiliario a partir de hoy**.
2. **La útil `[H]`: "What Needs You Now — identifies activities requiring human action" es el incumbente validando la postura de Qualify de humano-en-el-bucle.** El líder de IA del nicho no está vendiendo autonomía; está vendiendo priorización + acción humana. Eso convierte la restricción permanente de Qualify (respuestas **asistidas**, nunca autónomas — ADR 21) de *limitación que hay que justificar* en *consenso de categoría*. Es la mejor noticia de esta sección.

**Lo que Lofty sigue sin hacer, y donde queda hueco `[H]`:** todo su corpus es **contenido propio y base de datos propia** (mis listings, mis contactos, mi marca). No hay señal en ninguna fuente cosechada de que Lofty **lea contenido primario ajeno** — vídeo/audio/comentarios de terceros — que es exactamente la definición de Qualify. El hueco existe; **§2.2 hallazgo 2 dice que nadie lo pide todavía.** Ambas cosas son ciertas a la vez y esa tensión es el corazón de la ronda adversarial.

### 3.2 — BoldTrail: qué revelan las notas de versión

Fuentes: https://help.insiderealestate.com/en/articles/6301303-boldtrail-product-release-notes · https://help.insiderealestate.com/en/collections/2600840-product-release-notes · https://www.prnewswire.com/news-releases/inside-real-estate-announces-boldtrails-new-homesearch-ai-a-transformational-ai-powered-search-and-engagement-experience-302532566.html — accedidos 2026-07-29.

- **"Fixed an issue where inactive listings were continuing to be queued and posted to social media through Legacy CLM's scheduled post system."** → Confirma, desde el bug tracker del propio proveedor, que **la publicación programada de listings a redes es funcionalidad esperada y ya existente** en la suite del brokerage. Y revela el requisito de fondo: **el ciclo de vida del listing debe gobernar el calendario de publicación** (un listing que se cae debe despublicarse/desprogramarse solo). Ese detalle es más específico que "programar posts" y es el tipo de cosa que solo se aprende leyendo changelogs.
- **HomeSearch AI**: búsqueda en lenguaje natural + reconocimiento de imagen sobre el inventario, con "5–10x increases in lead engagement" reportado por early adopters (cifra **del proveedor**, no auditada — tratarla como marketing).
- **"Behavioral nurturing and AI-powered lead scoring are now expected features in enterprise platforms, not premium add-ons"** (https://boldtrail.com/blog/real-estate-technology-platform/, accedido 2026-07-29 — **fuente del propio vendedor**, sesgada, pero significativa precisamente por eso: el vendedor está declarando su propia commoditización). → **Lead scoring no es vendible como diferenciador en este nicho.** Impacto directo sobre la Fase 4 de Qualify.

### 3.3 — Ofertas de empleo: la lista de responsabilidades ES la lista de requisitos

Fuentes: https://wizehire.com/real-estate-marketing-coordinator-job-description (plantilla estándar del sector, accedida 2026-07-29) · https://www.ziprecruiter.com/career/Real-Estate-Marketing-Coordinator/What-Is-How-to-Become · https://bebee.com/us/jobs/marketing-social-media-coordinator-keller-williams-realty-eagan-mn--theirstack-669396249 — accedidos 2026-07-29.

Responsabilidades literales, y el requisito de software que cada una implica:

| Responsabilidad (literal de la oferta) | Requisito implícito |
|---|---|
| **"Update all Facebook, Twitter, Instagram, and other social media posts and respond to followers"** | **Publicar Y responder** son *el mismo puesto*. La bandeja de comentarios/DM asistida (Parte 4-B) no es un extra: es la mitad del trabajo que se está contratando. **Es el anclaje más limpio que existe en este documento para Parte 4-B.** |
| "Support the company **and agent** by tracking incoming leads/prospects so marketing campaigns can be adjusted" | Atribución de lead a campaña/post, **con desglose por agente** |
| "Streamline company materials and campaigns to ensure a **consistent and concise message**" | Control de marca sobre lo que publican N agentes → **workflow de aprobación** |
| "Plan and organize all team events, take photos, and then market on social media" | Ingesta de contenido propio, no solo listings |
| "Manage website design, content, SEO development and tracking analytics" | El puesto **no es** un puesto de social: social es una fracción de él |

Del corpus más amplio de ofertas (agregado por la búsqueda, no citado literalmente de una sola oferta — **segunda mano, marcado**):

- *"Develop and provide high-value marketing packages **for agents** including social media management, video/photo listing bundles, and personal branding exposure"* → el coordinador del brokerage es un **operador multi-cuenta**: gestiona las redes de *muchos agentes*, cada uno con su marca. Requisito: **N cuentas conectadas por tenant, con ámbito y branding por agente**.
- *"Utilize social media accounts to increase exposure and **attract top real estate agents to join the brokerage**"* → **JTBD no obvio y probablemente el más infravalorado de todo este documento:** una parte del social media del brokerage no existe para vender casas, existe para **reclutar agentes**. La métrica de éxito no es lead de comprador, es agente fichado. Ninguna herramienta cosechada mide eso.
- "Coordinate and lead training sessions for agents on social media best practices" → el comprador en el brokerage tiene un problema de **adopción por parte de los agentes**, no solo de herramienta.

### 3.4 — La capa vertical que ningún generalista lleva: cumplimiento

Descubierta persiguiendo los changelogs; es la razón de más peso que he encontrado para que exista un producto **verticalizado** en vez de Hootsuite.

- **Responsabilidad del broker por lo que publica el agente:** en Texas, "a complaint filed against a sponsored sales agent is **also a complaint against the broker**… and whether the broker properly supervised the sales agent" (TREC — https://www.trec.texas.gov/article/what-you-need-know-comply-our-social-media-rules; ⚠ **la página rechazó la conexión al intentar leerla directamente el 2026-07-29** (`ECONNREFUSED`); el texto proviene del extracto del índice de búsqueda → **cita de segunda mano, verificar antes de usarla ante un cliente**).
- **Identificación del broker en cada post** que trate de comprar/vender/alquilar/gestionar inmuebles (misma fuente, misma advertencia). → Requisito de producto muy concreto: **inyección obligatoria de disclosure/licencia en cada publicación**, no como plantilla opcional.
- **Archivado**: la recomendación sectorial es archivar toda la actividad social; el marco estricto de tres años que aparece en las fuentes es el de **broker-dealer financiero**, **no** el inmobiliario — no confundirlos (https://wolf.financial/blog/broker-dealer-social-media-supervision-compliance-guide, accedido 2026-07-29). El inmobiliario hereda la expectativa, no necesariamente la regla.
- **Fair Housing sobre contenido generado por IA:** "AI-generated content is subject to the same fair housing standards as human-written content — there is no exemption for automated tools"; "brokerages and agents — not AI companies — bear liability for content they publish"; la mitigación recomendada es **"AI should generate the first draft, and a trained professional should approve the final one"**. Fuentes: https://www.housingwire.com/articles/ai-fair-housing-remarks-checklist/ (⚠ **HTTP 403 al leerla; extracto de índice — segunda mano**) · https://www.nar.realtor/artificial-intelligence-real-estate (leída directamente 2026-07-29: **es mucho más delgada de lo que sugieren los blogs** — solo remite al Artículo 2 del código ético y a plantillas de política de IA tras login; **no** publica una regla operativa de revisión humana).
- **Reguladores estatales con reloj:** California AB 723 (efectiva enero 2026, divulgación de imágenes alteradas digitalmente) y Colorado AI Act (efectivo junio 2026, evaluaciones de impacto obligatorias para IA usada en decisiones de vivienda). ⚠ Ambos vía fuentes secundarias — **verificar en el texto legal antes de citarlos a un prospecto.**

**`[H]` Lo que esto significa para Qualify, dicho con precisión:** la decisión ya firmada de **respuestas asistidas (borrador + aprobación humana)** no es una concesión que haya que defender en este vertical — **es literalmente la mitigación de riesgo que el sector recomienda**. Es el único caso encontrado en toda la cosecha donde una restricción de Qualify se convierte en argumento de venta. Y a la vez levanta un requisito que **no tenemos**: si la aprobación humana es el control de cumplimiento, entonces **hace falta el registro auditable de quién aprobó qué y cuándo** — o el control no vale nada ante una reclamación. Ver §6.

⚠ **Advertencia de rigor sobre §3.4 entera:** las tres fuentes primarias (TREC, HousingWire, el texto de AB 723) **no pudieron leerse directamente**; la única leída de primera mano (NAR) resultó **más débil** que su reputación de segunda mano. Este apartado es la hipótesis mejor apoyada del documento y, aun así, **su verificación primaria está pendiente**. No lo lleves a una llamada de venta sin cerrarla.

---

## §3.5 — Estado real en disco, verificado antes de ensayar

Verificado por inspección del filesystem el **2026-07-29**, no leído de los docs. Todo lo que se prometa en §4 debe caber aquí.

**Existe y corre:**

- `packages/api/src/qualify_api/connections/` — flujo OAuth de Meta completo, FSM, custodia cifrada de credenciales, `revoke.py`, `verifier.py`, `resolver.py`. **Conectar una cuenta de Instagram funciona.**
- `packages/models/` — cascada multimodal (`filter.py`, `vision.py`, `transcription.py`, `sentiment.py`, `cascade.py`), matriz scope→capacidad (`permission_capability.py`), `filter_decision.py`, `eval/calibration.py`. **Analizar un vídeo funciona, contra fixtures.**
- `packages/scraper/` — cliente Zyte + parsers TikTok/IG + envelope v2. **Scrapear funciona a nivel de librería.**
- `migrations/postgres/versions/` — `0001_tenancy_foundation` (tenants, users, `tenant_members` con roles **`owner`/`admin`/`agent`/`viewer`**, brands, RLS), `0002_connections`, **`0003_publishing`** (`scheduled_posts`, `publish_attempts` con `idempotency_key`, `creation_id`, `raw_response_r2_key`, `published_media_id`), **`0004_inbox`** (`threads`, `messages` con `direction`, `author_username`, `text`, `posted_at`).
- `Qualify/` — UI Reflex con la pantalla de cuentas conectadas cableada al backend real.

**NO existe:**

- **Ninguna tabla ClickHouse. Ningún servicio ClickHouse en `docker-compose.yml`** (verificado: 0 coincidencias). `migrations/` solo contiene `postgres/`.
- **Ningún paquete `pipeline`** — `packages/` contiene solo `api`, `docs-harvester`, `models`, `scraper`, `shared`. **No hay Celery, no hay workers, no hay orquestación.** La cascada existe como funciones; **nada la ejecuta sobre contenido real de forma continua**.
- `publishing/` contiene **un solo archivo**, `client.py`, y su propio docstring lo dice: *"Nobody in this repo has run this flow against Meta yet, so every response shape is a reading of the corpus rather than an observation."* **No hay servicio de publicación, no hay scheduler, no hay UI.**
- **Cero primitivas de aprobación o auditoría.** `grep` de `approv|audit_log|reviewed_by` sobre `packages/` y `Qualify/`: sin resultados. La tabla `messages` **no tiene columna de borrador, ni de aprobador, ni de estado de revisión.** No hay dónde guardar un borrador asistido ni quién lo aprobó.

### Ampliación 2026-07-30, cruzada con la auditoría independiente de `opportunity`

`opportunity` hizo la misma verificación por su cuenta (`docs/oportunidades-mercado-inmobiliario.md` §1) y encontró **más de lo que yo registré, y a la vez peor**. Lo he re-verificado punto por punto:

- **Existe más de lo que documenta `CLAUDE.md`**: módulo de object-store/R2 en `packages/shared/src/qualify_shared/objects/`, `connections/revoke.py`, y **298 tests offline**, no 147.
- **Pero el cliente R2 nunca se ha ejercitado contra un S3 real** — solo un doble en memoria, y **`boto3` no es dependencia declarada** (verificado por mí el 2026-07-30: `grep boto3` sobre todos los `pyproject.toml` → **cero resultados**). Diseñado, nunca ejecutado.
- **⚠ Corrección a lo que escribí arriba, y es la que más duele:** dije *"analizar un vídeo funciona, contra fixtures"*. Es más frágil que eso. **Los ocho tests que ejercitan modelos reales están marcados `@pytest.mark.integration`** — `test_cascade`, `test_filter`, `test_vision`, `test_transcription`, `test_sentiment`, `test_ig_comments`, `test_filter_calibration`, `test_eval_integration` (verificado por `grep` el 2026-07-30). El marcador `integration` está excluido de CI por configuración. **Por tanto no hay ni una sola pasada verificada de forma continua del activo diferenciado.** El código existe; nada comprueba que siga funcionando.
- **La restricción vinculante es la orquestación, no la analítica.** Sin Celery ni scheduler **no hay producto de monitorización continua**, solo un script que alguien lanza a mano.

**Consecuencia dura para el ensayo, endurecida:**

1. Hoy **no existe una demo end-to-end que enseñar a un prospecto inmobiliario**.
2. **La frase "vigilamos tus menciones de forma continua" es falsa hoy**, y lo seguirá siendo mientras no exista `packages/pipeline`. Ninguna conversación de §4 la usa.
3. Lo único demostrable es: conectar una cuenta de Instagram (real, cableado), y **correr a mano** la cascada sobre un vídeo. Incluso eso exige instalar el grupo `ml` y ejecutar los tests `integration` deliberadamente. **Es una demo que hay que preparar, no una que esté lista.** Esto degrada la validación de R6 en §6 de "barata" a "barata pero requiere una tarde de preparación previa".

---

## §4 — Tres conversaciones de lead ensayadas

> **ESTO ES SIMULACIÓN.** Ningún prospecto real dijo nada de lo que sigue. Cada **dolor** que pongo en boca del lead lleva su ancla a §1-§3; los dolores sin ancla **no aparecen** y están listados explícitamente en §4.4 como fuentes que faltan. Lo que Qualify responde está limitado por §3.5.
>
> **Marco declarado** (no hay skill instalada de metodología de venta — ver la nota de hueco COMPASS en mi rol): uso **JTBD para el descubrimiento** (trabajo funcional / emocional / social, disparador, alternativas) y **MEDDIC recortado a M-E-D-Ch** (Metric, Economic buyer, Decision criteria, Champion) para la calificación, porque en un ciclo de PYME el resto de MEDDIC es sobre-instrumentación. Si esto funciona dos veces, se destila en procedimiento.

### 4.1 — Lead A: agente individual · **RESULTADO: DESCALIFICADO**

*Perfil: agente con licencia, 6 años, opera solo, ~14 operaciones/año. Publica en Instagram porque "hay que estar". Su brokerage le da BoldTrail incluido.*

**Yo:** Antes de contarte nada — ¿qué herramienta usas hoy y cómo llegaste a ella?

**Lead:** La que me da la oficina. BoldTrail. No la elegí yo.
> ⚓ Anclado en §2.1: *"Switched to eXp; kvCore came as standard CRM offering"* — Matthew G., Agent, Capterra BoldTrail, accedido 2026-07-29. **El agente individual hereda el CRM, no lo compra.**

**Yo:** ¿Y qué te prometieron que no cumplió? *(la pregunta de descubrimiento de §2.2 hallazgo 3)*

**Lead:** Pagué el programa de leads. Me llenó el correo y el móvil de basura.
> ⚓ Anclado en §1.3: *"DO NOT pay for their Lead 350 program as it bogs down you email and text messages with bogus leads"* — Liana N., Broker-Associate, 1,0, enero 2026.

**Yo:** ¿Y en redes?

**Lead:** Probé una de esas de vídeos automáticos. Salía la misma información genérica que a todos los agentes de la zona, con faltas de ortografía.
> ⚓ Anclado en §1.1: *"Some videos that all agents are using at the same time"* (Kamyab G., Broker) y *"the posts in my social media are with typos"* (Kathia P., Realtor) — Capterra Roomvu.

**Lead:** ¿Vosotros qué hacéis, exactamente? ¿Me publicáis los listings en TikTok y en Instagram programado?

**Yo — y aquí es donde la conversación se rompe, honestamente:** Programar a TikTok **no lo podemos hacer, y no es cuestión de tiempo.** La política de TikTok obliga a que la cuenta que publica vía un cliente de API no auditado esté **en privado**. No hay mitigación de ingeniería. *(Lista dura de `CLAUDE.md`: "scheduled publishing to TikTok is **blocked, not scheduled**".)* En Instagram sí está el camino, pero hoy es un **seam sin ejecutar contra Meta** (§3.5) y depende de una revisión de app de Meta con su propio calendario.

**Lead:** Entonces ¿qué me das hoy, por lo que pagaría yo?

**Yo:** Hoy, honestamente: conectar tu cuenta de Instagram y analizar contenido en vídeo — lo que se dice, lo que se ve, el sentimiento de los comentarios. No hay pipeline que lo corra en continuo todavía (§3.5).

**Lead:** Yo no tengo un problema de análisis. Tengo un problema de tiempo.

**Diagnóstico `[H]`:** **Descalificado, y correctamente.** Tres motivos independientes, cualquiera basta:
1. **No es el comprador económico** — el software se lo da el brokerage (§2.1).
2. **Su necesidad declarada es scheduling a TikTok** → señal de descalificación explícita en la lista dura.
3. **Su trabajo (JTBD) es "que esto me ocupe menos tiempo"**, y Qualify hoy añade una herramienta más, no quita una.

**Lo que enseña la pérdida:** el agente individual es un mercado **inalcanzable económicamente y mal atendido por nuestra hoja de ruta a la vez**. Es la descalificación más barata de aplicar y debe estar arriba del script de discovery, no abajo.

### 4.2 — Lead B: brokerage mediano (~35 agentes), habla la Marketing Coordinator · **RESULTADO: LA CONVERSACIÓN MÁS VIVA — y expone tres requisitos que no tenemos**

*Perfil: la persona de la oferta de empleo de §3.3. Un solo puesto que lleva web, SEO, eventos, materiales, y las redes del brokerage **más** las de los agentes que pagan el paquete.*

**Yo:** Descríbeme tu semana.

**Lead:** Publico en las redes de la oficina y de 12 agentes, **y respondo a los seguidores**. Y hago la web. Y los eventos.
> ⚓ Anclado en §3.3, literal de la descripción del puesto: *"Update all Facebook, Twitter, Instagram, and other social media posts **and respond to followers**"* — https://wizehire.com/real-estate-marketing-coordinator-job-description, accedido 2026-07-29.

**Yo:** ¿Lo de responder cuánto te ocupa?

**Lead:** Es lo que no cabe. Publicar lo tengo programado. Responder no se puede programar, y es donde está el cliente.

**Yo:** Eso es exactamente la mitad del producto: una bandeja de comentarios y DMs de **vuestras** cuentas conectadas, con un **borrador redactado por IA que tú apruebas antes de que salga**. Nunca automático.

**Lead:** ¿Por qué no automático? Lofty me acaba de enseñar un "Social Agent".
> ⚓ Anclado en §3.1 — Lofty AOS/Cowork, RISMedia 28 julio 2026.

**Yo:** Dos razones y las dos son a tu favor. La técnica: a la precisión que da hoy la generación, **uno de cada tres borradores estaría mal**; a nombre de tu broker, eso no es un ahorro, es un incidente. La legal: en vivienda, el contenido generado por IA **no tiene exención de Fair Housing**, y quien responde es el brokerage, no el proveedor de IA. La mitigación que recomienda el propio sector es *"AI genera el borrador, un profesional aprueba el final"*. Fíjate en que el propio Lofty vende "**What Needs You Now** — actividades que requieren acción humana".
> ⚓ Anclado en §3.4 y §3.1. ⚠ Con la advertencia de §3.4: las fuentes primarias de Fair Housing **no están verificadas de primera mano**.

**Lead:** Vale. Tres cosas entonces. Una: si la aprobación humana es el control, **necesito poder demostrar quién aprobó qué**. Si mi broker recibe una reclamación, el log es mi defensa.

**Yo — no puedo responder que sí.** No existe. Cero primitivas de aprobación o auditoría en el repositorio; la tabla `messages` no tiene columna de borrador, ni de aprobador, ni de estado de revisión (§3.5, verificado).

**Lead:** Dos: **cada post de venta lleva la identificación del broker por normativa.** ¿Se inyecta sola o la pongo yo 12 veces al día?

**Yo — tampoco.** No hay servicio de publicación en absoluto (§3.5). Es un requisito nuevo.
> ⚓ Anclado en §3.4 (TREC, ⚠ segunda mano).

**Lead:** Tres: son **12 marcas distintas**, no una. Si me obligas a un login por agente, no lo uso.

**Yo:** Aquí sí. El modelo de datos es multi-cuenta por tenant desde el diseño, y los roles incluyen literalmente `agent` y `viewer` (§3.5). Lo que no está probado es la UI a esa escala.

**Diagnóstico `[H]`:** **Calificado, y es el ICP.** Comprador económico identificable (el broker/owner firma, la coordinadora es campeona), métrica clara (horas de la coordinadora + consistencia de marca), disparador real (el volumen de agentes crece y el puesto no). Y **la conversación produjo tres requisitos concretos que no tenemos**, que es exactamente para lo que sirve el ejercicio → §6, filas R1, R2, R4.

### 4.3 — Lead C: franquicia regional · ⚠ **PERSONA CONSTRUIDA SOBRE UNA PREMISA FALSA — se conserva como error documentado**

> **No la borro; la marco.** La escribí asumiendo una franquicia con **presupuesto central** que compra software para sus oficinas. `gtm` verificó que en este mercado **eso no existe**: *"el franquiciado asume los costos"* (Forbes Uruguay sobre RE/MAX AR&UY, vía `docs/oferta-mercado-inmobiliario.md` §5). Cada oficina es económicamente independiente.
>
> **El error es informativo y por eso se queda:** un lead que *parece* una franquicia grande **no es un comprador con presupuesto central**, y confundirlos hace perder semanas persiguiendo a quien no puede firmar. Esa confusión entra en §7.2 como señal de descalificación por derecho propio.
>
> **Qué sobrevive:** las objeciones O-2, O-4 y O-6 (reloj de Meta, SSO/DPA/residencia, referencias) siguen siendo reales para cualquier comprador que se perciba grande. **Qué no sobrevive:** el tamaño del cheque, y con él la premisa de que la franquicia sea "el segmento tardío pero grande". No es grande. La persona corregida está en **§4.3-bis** y es la que hay que usar.

**Lead (Director de Marketing regional):** ¿Cuántos clientes como nosotros tenéis?

**Yo:** Ninguno. Sois nuestro cliente uno.

**Lead:** Entendido, seguimos igual. Necesito tres cosas antes de mirar features. ¿Cuándo podemos publicar en producción a las cuentas de Instagram de las nueve oficinas?

**Yo — y esta es la respuesta que hay que dar y que suele perder el trato:** Publicar a cuentas de terceros a escala requiere de Meta **Advanced Access + App Review + Business Verification**. Esos tres relojes son administrativos y **vinculan precisamente en el cliente uno** — es decir, en vosotros. No puedo darte una fecha; puedo darte el estado del expediente cada semana.
> ⚓ `CLAUDE.md`, enmienda a ADR 21: *"Advanced Access + App Review + Business Verification still bind at customer one, and that administrative clock should start week 0."*

**Lead:** ¿Y una bandeja única con Facebook, Instagram, WhatsApp y el correo?

**Yo:** No. Hoy es **un canal**, sobre vuestras cuentas conectadas. La bandeja unificada cross-canal es Fase 6. *(Lista dura de `CLAUDE.md`.)* Y la bandeja actual es esquema, no producto (§3.5).

**Lead:** ¿SSO? ¿Dónde residen los datos? ¿Quién firma el DPA? ¿Qué pasa con el contrato si desaparecéis? Lo pregunto porque nos ha pasado: nos denegaron una cancelación.
> ⚓ Anclado en §1.3 / §2.1: *"my cancellation request was denied"* (Sara G., Sales Associate, enero 2026) y *"False promises from KvCore about customer support and account management during sales pitch"* (Gabi M.).

**Yo:** No hay SSO. No hay política de residencia de datos publicada. No hay DPA redactado. **Nada de eso existe** y ninguna está en la hoja de ruta firmada.

**Diagnóstico `[H]`:** **Perdido, y la pérdida es informativa.** No se pierde por falta de features de producto — se pierde por **los requisitos que no son features**: acceso a plataforma con reloj administrativo, SSO, residencia de datos, DPA, garantías contractuales, referencias de clientes. Es la clase de requisito que, según mi rol, "mata tratos en silencio". Y la franquicia es el segmento donde **todos** aplican a la vez.

**Corolario de secuenciación `[H]`:** la franquicia **no es un segmento tardío por tamaño de cheque, sino por el reloj de Meta**. Si en algún momento se persigue, el expediente de Advanced Access/App Review/Business Verification debe abrirse **meses antes** de la primera conversación comercial. Es la recomendación más accionable de §4 y no cuesta código.

### 4.3-bis — Lead C corregido: **titular de agencia independiente (Uruguay), decide y paga, ~6 agentes debajo** · **RESULTADO: NO SÉ, Y ESO ES EL RESULTADO**

*Perfil corregido según `gtm` §5 y la forma de asientos que ya está en el esquema: 1 `owner` + N `agent` (`tenant_members`, verificado §3.5). Gasta $50-185/mes en software de toda la empresa.*

> ⚠ **Esta conversación es la más honesta y la menos anclada del documento.** Los dolores de §1-§3 son `[H-US]`; **no tengo ni una fuente uruguaya**, y `gtm` confirmó de forma independiente que no existe corpus público que minar (Tokko, "el CRM #1 de América Latina", tiene **dos** reseñas). Por mi regla constitucional: **la fuente falta.** Así que no le pongo dolores en la boca. Lo que ensayo es únicamente **qué preguntaría yo**, y dónde se rompe la conversación por lo que *nosotros* no podemos hacer — que sí está verificado.

**Yo:** Sois seis. ¿Quién publica y quién responde?

**Lead:** *(no lo sé — fuente ausente. No lo invento.)*

**Yo — la pregunta que domina toda la sesión, cortesía de `opportunity`:** ¿**puedes** conseguir que tus agentes conecten sus cuentas de Instagram, y **querrías** hacerlo?

> ⚓ Anclado en `docs/oportunidades-mercado-inmobiliario.md`: tres de las cinco tesis de `opportunity` comparten un mismo falsador — **los agentes inmobiliarios suelen ser autónomos, la cuenta de Instagram es suya y se la llevan al cambiar de agencia.** Si el titular no puede o no quiere exigir la conexión, **todo el camino "instalar en la agencia" se derrumba y se vuelve venta agente por agente.**

**Por qué esta pregunta es distinta de las demás:** no pregunta por una feature. Pregunta si **la unidad de instalación existe**. Si la respuesta es "no puedo obligarles", entonces R2 (multi-cuenta con marca por agente) no es un requisito de producto sino un **problema de gobernanza del cliente**, y el ICP del §4.2 —una persona operando 12 marcas— **no existe en este mercado**. Es la única pregunta del documento que puede invalidar tres secciones de golpe.

**Yo (siguiente):** ¿Cuánto pagáis hoy por software, todo junto?

**Lead:** *(dato conocido por `gtm`, no por mí: **$50-185/mes, ~5 asientos, toda la empresa**.)*

**Aquí la conversación se rompe, y no por una feature.** A ese techo:
- Un asiento de listening genérico (Exolyt $400-950/mes, Sprout $249+/asiento) **cuesta más que todo su presupuesto de software**.
- BoldTrail (~$5.988/año ≈ $499/mes) es **entre 2,7× y 10× su gasto total actual**.
- Lo que Qualify puede aspirar a cobrar aquí es, como mucho, **una fracción de $50-185/mes** — porque compite contra las otras herramientas que ya ocupan ese presupuesto, no contra el vacío.

**Diagnóstico `[H]`:** **No calificado ni descalificado — indeterminado, y la indeterminación es el hallazgo.** No puedo cerrar esta conversación porque me faltan las dos entradas que la deciden: (a) si el titular puede exigir la conexión de cuentas, y (b) si algo de lo que construiríamos cabe bajo su techo. Ambas se resuelven con **dos preguntas al cliente uno**, no con más investigación. Están al principio de §6.

### 4.4 — Dolores que sé que existen y **no ensayé porque no encontré fuente**

Los listo en vez de dramatizarlos. Cada uno es una tarea de investigación, no un hallazgo:

1. **Cuánto paga realmente un brokerage mediano por social/contenido** — la cosecha da señales de techo ("It's very expensive", rechazo a add-ons) pero **ningún número**. Es de `gtm` (tarea S2); mi §6 depende de ello para la comparación coste/cierre.
2. **Si el agente inmobiliario latinoamericano tiene los mismos dolores** — toda la cosecha es de EE. UU. (Capterra/TREC/NAR). ⚠ **Y esto es peor de lo que parecía al empezar:** `docs/backlog-crm-workflows.md` §0 documenta que el cliente uno es una **agencia inmobiliaria en Uruguay**, y su §494 sostiene que *"el inmobiliario latinoamericano funciona sobre WhatsApp. Para el cliente uno, WhatsApp probablemente **es** el canal, no un canal más."* Ninguna de mis fuentes cubre WhatsApp ni Uruguay. **Es la mayor debilidad de validez externa de este documento y hay que leerlo con ese descuento: cosecha estadounidense, cliente uruguayo.** Ver §6, fila R0.
3. **El dolor de "reclutar agentes vía redes"** (§3.3) — aparece en descripciones de puesto, **no** en ninguna reseña ni queja. Sé que el trabajo existe; no tengo evidencia de que duela.
4. **Escucha sobre competidores locales** — es la propuesta nuclear de Qualify y **no encontré una sola fuente de un agente pidiéndola.** Ver §2.2 hallazgo 2. No la puse en boca de ningún lead precisamente por eso.

---

## §5 — Biblioteca de objeciones

Tres columnas importan: la **demanda con fuente** que hay detrás de la objeción, la **respuesta honesta**, y si esa respuesta es *"todavía no, Fase N"* o **no hay respuesta**. Las filas sin respuesta honesta van primero: **son requisitos con fecha de vencimiento**, no objeciones.

### 5.A — Objeciones que **NO podemos responder honestamente** (las valiosas)

| # | Objeción, en palabras del comprador | Demanda con fuente detrás | Respuesta honesta hoy | ¿"Todavía no, Fase N"? |
|---|---|---|---|---|
| **O-1** | *"Si la aprobación humana es el control de cumplimiento, enséñame el registro de quién aprobó qué y cuándo."* | §3.4 Fair Housing: la responsabilidad recae en el brokerage, no en el proveedor de IA; la mitigación es revisión humana. §1.3/§2.1: supervisión del broker. | **Especificado, no construido.** ✅ Corrección tras leer el backlog: **`docs/backlog-crm-workflows.md` C-10 (§846) y el paso 8 del bucle W4 (§527, §544) ya lo especifican** — registro de aceptado/editado/descartado con diff, `source_id` de fundamentación, y atribución `(tenant_id, user_id, thread_id, timestamp)`. **Pero en código no existe nada** (§3.5, verificado): `messages` no tiene borrador, aprobador ni estado de revisión. | **Sí hay ítem de roadmap — con un matiz que importa.** C-10 lo justifica como **telemetría de calidad del modelo** ("la única señal real de calidad"), no como **artefacto de cumplimiento exportable** ante una reclamación. Son requisitos distintos con el mismo dato: el segundo exige inmutabilidad y exportación, el primero no. **Vencimiento: el día del primer envío asistido.** |
| **O-2** | *"¿Cuándo puedo publicar de verdad, a mis cuentas, en producción?"* | §3.2: la publicación programada de listings es funcionalidad esperada en la suite del brokerage. §4.3. | **No puedo dar fecha.** Advanced Access + App Review + Business Verification vinculan en el cliente uno y el reloj es de Meta, no nuestro. Y `publishing/` es un seam nunca ejecutado contra Meta (§3.5). | **No es una fase, es un trámite.** Único mitigante: **abrir el expediente en la semana 0** y reportar estado semanal. Cuesta cero código. |
| **O-3** | *"Cada post lleva la identificación del broker por normativa. ¿Se inyecta sola?"* | §3.4 TREC (⚠ segunda mano): identificación del broker en cada post sobre compra/venta/alquiler. | **No.** No hay servicio de publicación (§3.5). Requisito nuevo, sin dueño. | **No.** Se puede colar en Parte 4-A si Parte 4-A se construye; hoy no está especificado. |
| **O-4** | *"¿SSO? ¿Residencia de datos? ¿DPA? ¿Qué pasa con mi contrato si desaparecéis?"* | §1.3/§2.1: agravio contractual documentado (*"my cancellation request was denied"*, *"False promises… during sales pitch"*) → este comprador **ya fue quemado** y por eso pregunta. | **Nada de eso existe** ni está en la hoja de ruta firmada. | **No.** Mata franquicia y brokerage grande **en silencio**, antes de hablar de producto. |
| **O-5** | *"Necesito programar a TikTok."* | §1.1 (Roomvu publica a TikTok entre otras). Demanda real y extendida. | **Bloqueado, no aplazado.** La política de TikTok fuerza a que la cuenta que publica vía cliente de API no auditado esté en privado. **Sin mitigación de ingeniería.** | **Nunca, con el diseño actual.** Es una **señal de descalificación**, no un ítem de roadmap. Ver §7. |
| **O-6** | *"Enséñame un cliente como yo."* | §4.3. Requisito estándar de compra empresarial. | **No hay ninguno.** Somos pre-cliente-uno. | **No.** Solo se resuelve con el tiempo; determina que la franquicia sea tardía. |
| **O-7** | *"Cuando esto se rompa un sábado, ¿quién me coge el teléfono?"* | §1.1 ×2, §1.3 ×3, §1.4 ×1 — **soporte inalcanzable es la queja más transversal de toda la cosecha**, presente en las cuatro herramientas. | Un fundador. Sin SLA, sin guardia, sin cobertura de fin de semana — y §1.1 documenta que **el trabajo inmobiliario ocurre en fin de semana** (*"if I list a house on weekend I can't advertise it till working day"*). | **No es una fase, y es la objeción que más subestimamos.** Un fundador puede ganar aquí frente a un incumbente con soporte horrendo — hasta el cliente número cinco. Después, no. |
| **O-15** ⭐ | *"¿Cuánto cuesta?"* — la objeción más simple y la que no tiene respuesta | §0: el cliente uno gasta **$50-185/mes en software de toda la empresa**, ~5 asientos (`docs/oferta-mercado-inmobiliario.md` §2.1). Un asiento de listening genérico cuesta más que eso entero. | **No hay precio que podamos nombrar que sea a la vez pagable por él y sostenible para nosotros**, y no lo sé porque no se haya decidido: lo sé porque el techo y el coste de R6 no se tocan (§6.2). | **No es una fase. Es la objeción estructural del segmento** y la razón por la que la categoría podría estar ausente en LATAM en vez de vacía. |
| **O-16** ⭐ | *"Mis agentes son autónomos. La cuenta de Instagram es suya y se la llevan si se van. No puedo obligarles a conectarla."* | `docs/oportunidades-mercado-inmobiliario.md` — falsador compartido de tres de las cinco tesis de `opportunity`. | **No tenemos respuesta y ni siquiera sabemos si la objeción se dará.** Si se da, el producto no se instala en la agencia: se vende agente por agente — al comprador que §4.1 ya descalificó por no ser comprador económico. | **No.** Es la objeción que puede invalidar el ICP entero. **Convertirla en pregunta de discovery antes de que llegue como objeción** es la única jugada. |

### 5.B — Objeciones con respuesta honesta

| # | Objeción | Demanda con fuente | Respuesta honesta | Fase |
|---|---|---|---|---|
| **O-8** | *"¿Por qué no autónomo? Lofty vende un Social Agent."* | §3.1 (Lofty AOS, 28-jul-2026). | Precisión: ~65% significa que **1 de cada 3 borradores está mal**, a nombre del broker. Legal: §3.4, sin exención de Fair Housing, responde el brokerage. Y **el propio Lofty vende "What Needs You Now — actividades que requieren acción humana"**: el líder del nicho tampoco vende autonomía. | Permanente. **Es postura, no carencia.** La mejor respuesta de todo el documento. |
| **O-9** | *"Ya probé una IA que publicaba y era genérica y con faltas."* | §1.1 ×5 (Roomvu, 2,5/5). | Correcto, y por eso no hacemos eso. La diferencia declarable: **tú apruebas antes de publicar** y el análisis parte de **contenido primario real** (lo que se dice y se ve en el vídeo), no de plantillas compartidas por todos los agentes de la zona. ⚠ **Declarable, no demostrable**: no hay demo end-to-end (§3.5). | Hoy en concepto, Parte 4-A/4-B en producto. |
| **O-10** | *"No quiero más leads, quiero mejores."* | §1.3 (*"bogus leads"*), §1.5 (falta de leads en planes bajos). | Qualify no vende volumen de leads; puntúa sobre contenido primario. **Pero:** el propio BoldTrail declara que "AI-powered lead scoring" ya es *expected, not a premium add-on* (§3.2) → **scoring no es diferenciador vendible en este nicho.** | Fase 4. Y hay que dejar de venderlo como diferenciador. |
| **O-11** | *"Bandeja única con IG, Facebook, WhatsApp y correo."* | §4.3; §1.2 (petición de WhatsApp en G2, ⚠ segunda mano). | No. **Un canal**, sobre vuestras cuentas conectadas. | **Sí: Fase 6** para cross-canal. Parte 4-B para un canal. |
| **O-12** | *"Es caro / no quiero pagar add-on por cada cosa."* | §1.2 (*"The price. It's very expensive"*), §1.4 (*"AI Assistant? Extra. CMA tool? Extra."*). | El rechazo documentado es al **desglose en add-ons**, más que al importe. Argumenta precio único. ⚠ **Sin número que oponer** — depende de `gtm` S2. | N/A. Es posicionamiento de precio. |
| **O-13** | *"Mis agentes no van a usar otra herramienta."* | §1.4 (*"insanely convoluted… app and desktop"*), §3.3 ("training sessions for agents on social media best practices"). | Real y es el riesgo dominante de la venta al brokerage. Mitigante honesto: el comprador es **la coordinadora**, no los 35 agentes — se diseña para un operador, no para adopción masiva. | N/A. Es diseño de segmento. |
| **O-14** | *"¿Funciona en el móvil? Estoy en el coche."* | §1.4 (*"accounts don't sync well from computer to phone, which causes me to miss messages"*). | Reflex es web; no hay app nativa ni se ha probado en móvil (§3.5). Para la coordinadora de escritorio es aceptable; **para el agente no lo es** — y refuerza que el agente individual no sea el ICP. | Sin fase. |

---

## §6 — Cola de requisitos, rankeada

**Esto no es un backlog.** Es una cola de **qué validar con un prospecto real**, ordenada por (tratos plausiblemente bloqueados × baratura de validar). `product-owner` es quien decide si algo de aquí entra a `docs/backlog-*.md`, y **solo después de que un prospecto real lo confirme**. Todo `[H]`.

**Nota de coste para la ronda adversarial con `gtm`:** la columna "Qué costaría" está verificada contra el filesystem el 2026-07-29 (§3.5) precisamente para que `gtm` pueda contrastar su techo de precio observado contra el esfuerzo real. Donde no puedo estimar, lo digo.

### 6.0 — Las cinco preguntas que preceden a toda la cola

**Reordenación 2026-07-30.** Cuando escribí esta cola, el criterio de ranking era *(tratos bloqueados × baratura de validar)*, y "barato de validar" significaba en la práctica "barato de minar en reseñas". **Ese criterio ya no vale**: para este comprador no hay reseñas que minar (§0, confirmado independientemente por `gtm`). El criterio pasa a ser **cuánta incertidumbre elimina una sola pregunta al cliente uno**, y por ese criterio tres preguntas dominan a todo lo demás por un margen enorme. Ninguna cuesta código. Las tres caben en una llamada.

| # | La pregunta, literal | Qué se derrumba si la respuesta es "no" | Coste |
|---|---|---|---|
| **V1** ⭐ | **"¿Puedes conseguir que tus agentes conecten sus cuentas de Instagram, y querrías hacerlo?"** | **El ICP entero.** Los agentes suelen ser autónomos y la cuenta es suya (`docs/oportunidades-mercado-inmobiliario.md`; falsador compartido de 3 de las 5 tesis de `opportunity`). Si no puede exigirlo, no hay "instalar en la agencia": hay venta agente por agente, al comprador que §4.1 ya descalificó. Caen R2, R1 parcialmente, y el §4.2 completo. | Una pregunta |
| **V2** ⭐ | **"¿Cuánto pagáis hoy por software, todo junto, y qué tendría que hacer algo para que pagarais más que eso?"** | **La viabilidad económica.** Techo conocido: $50-185/mes para toda la empresa (`docs/oferta-mercado-inmobiliario.md` §2.1). Ver §6.2 — es la pregunta de la que depende si merece la pena construir R6. | Una pregunta |
| **V3** | **"Recórreme R1-R7: ¿cuáles reconoces como problema tuyo?"** | **La validez externa de §1-§3.** Toda mi cosecha es estadounidense (§0). Si reconoce ≤2 de 7, este documento describe el mercado equivocado y la cola se reordena entera. | 45 minutos |
| **V4** ⭐ | **"Si Qualify hiciera esto, ¿darías de baja Tokko/Wasi — o lo pagarías además?"** | **Añadida 2026-07-30 tras ADV3.** `gtm` detectó una premisa oculta que ni mi encuadre ni el del lead vieron: el techo de $50-185/mes **no es presupuesto libre, es gasto ya comprometido** (CRM + portal). Si Qualify **desplaza** la línea de CRM, el techo entero es direccionable; si **se suma encima**, el incremento realista es desconocido y `gtm` se negó —con razón— a inventar un número. **Cambia si el negocio existe, no solo su tamaño.** | Una pregunta |
| **V5** | **"¿Bajo qué régimen de protección de datos operáis hoy, y quién os lo lleva?"** | **Añadida 2026-07-30 tras ADV2.** Uruguay tiene la **Ley 18.331**, de grado RGPD, con adecuación UE desde 2012 y reafirmada en 2024 (`docs/oportunidades-mercado-inmobiliario.md` T-6). Aplica al cliente uno **exista o no Qualify**. Determina el ancla real de R1 y si procesar contenido de terceros es caro allí. | Una pregunta |

> **V1, V2 y V4 cuestan tres preguntas y determinan si existe ICP, si existe negocio y si el negocio es desplazamiento o adición.** Todo lo que sigue está condicionado a ellas. Recomendación explícita: **no construir nada de R1-R7 antes de tenerlas respondidas.** Las cinco caben en la misma llamada de 45 minutos.
>
> ⚠ **Y una carencia que ninguna de las cinco resuelve, señalada por `gtm` y que asumo:** **nadie en esta sesión ha estimado N (número de clientes).** Sin N, `precio × N vs. coste de construcción amortizado` **no se puede evaluar**. Todo lo que hace esta cola es **ordenar filas; no demuestra rentabilidad de ninguna.** Que quede dicho antes de que alguien la lea como un plan.

### R1 — Registro auditable y exportable de aprobación de respuestas

| Campo | |
|---|---|
| **Demanda, en palabras del comprador** | *"Si mi broker recibe una reclamación, el log es mi defensa."* (§4.2, ensayado — anclado, no observado) |
| **Fuente ancla** | §3.4: *"AI-generated content is subject to the same fair housing standards… there is no exemption for automated tools"*; *"brokerages and agents — not AI companies — bear liability"*; mitigación = *"AI should generate the first draft, and a trained professional should approve the final one"* — https://www.housingwire.com/articles/ai-fair-housing-remarks-checklist/ (⚠ 403, extracto de índice, **segunda mano**) + https://www.nar.realtor/artificial-intelligence-real-estate (leída directamente 2026-07-29, **más delgada** de lo que sugieren los blogs) |
| **⚠ Ancla en revisión (2026-07-30)** | **El ancla estadounidense probablemente no alcanza a Uruguay** (`gtm`, ADV3: fair housing es régimen de EE. UU.). Pero **R1 no desaparece: se re-fundamenta.** `opportunity` (T-6) documenta que Uruguay tiene la **Ley 18.331** de protección de datos, grado RGPD, con adecuación UE desde 2012 reafirmada en 2024 — que **sí aplica al cliente uno**, con o sin Qualify. Un registro de quién aprobó qué y sobre qué datos es un artefacto de cumplimiento **tan válido bajo 18.331 como bajo fair housing**, solo que responde a otra pregunta legal. **Acción: resolverlo en la misma llamada, con V5.** No dar R1 por muerta porque su ancla original no viaje. |
| **Segmento** | Brokerage y franquicia. **No** el agente individual. |
| **Quién ya lo sirve** | **Nadie de los cosechados lo vende como artefacto de cumplimiento.** Lofty vende priorización humana ("What Needs You Now") pero sin log defensivo. Es el hueco más limpio encontrado. ⚠ `gtm` añade que **ninguna de sus 16 quejas documentadas lo pide** — consistente con una necesidad latente (nadie pide lo que nunca ha visto), pero también consistente con que no exista. No distinguible sin V5. |
| **Qué costaría (verificado en disco)** | **Medio.** El esquema `0004_inbox` existe pero `messages` no tiene borrador/aprobador/estado. Hace falta: columnas o tabla `reply_drafts` (borrador, autor-modelo, aprobador `user_id`, decisión aceptado/editado/descartado, diff, timestamp), append-only, + exportación. **El patrón ya existe en el repo**: `connection_events` es append-only (`docs/backlog-crm-workflows.md` L6) → se replica, no se inventa. |
| **¿Cubierto por roadmap?** | **Parcialmente, y el matiz decide.** C-10 (§846) y el paso 8 de W4 (§527, §544) ya lo especifican **como telemetría de calidad del modelo**. Un artefacto de cumplimiento exige además **inmutabilidad y exportación**, que la justificación actual no pide. **Recomendación: no es un ítem nuevo, es una ampliación de C-10** — ruta a `product-owner`, no a arquitectura. |
| **Fase** | Parte 4-B, junto a C-10. Es más barato ahora que después. |
| **Qué lo validaría** | Preguntar al cliente uno: *"si un cliente se queja de una respuesta, ¿qué le enseñas a tu abogado hoy?"* Si no tiene respuesta, el requisito es real. Coste: una pregunta. |

### R2 — Multi-cuenta con marca por agente, operado por una sola persona

| Campo | |
|---|---|
| **Demanda** | *"Son 12 marcas distintas, no una. Si me obligas a un login por agente, no lo uso."* (§4.2, ensayado) |
| **Fuente ancla** | §3.3, ofertas de empleo: *"Develop and provide high-value marketing packages **for agents** including social media management… and personal branding exposure"* y *"Design and develop custom marketing packages for **individual brokers**"* (https://wizehire.com/real-estate-marketing-coordinator-job-description y agregados de ziprecruiter/bebee, accedidos 2026-07-29) |
| **Segmento** | Brokerage (el ICP). Amplificado en franquicia. |
| **Quién ya lo sirve** | BoldTrail y Lofty, como suite de brokerage. Ese es su terreno fuerte. |
| **⭐ Promovida a fila #1 construible (2026-07-30, ADV3)** | `gtm` aporta el dato que la mueve: **Tokko Enterprise (6-10 usuarios) ya cuesta ≈$185/mes** — es decir, **el mercado LATAM paga hoy mi techo entero exactamente por esta capacidad**. Doble consecuencia: (a) hay disposición a pagar **demostrada**, no inferida; (b) **es la fila que habilita el desplazamiento en vez de la adición** (V4), porque es justo lo que Tokko/Wasi venden. Si Qualify solo puede sumarse encima del CRM, el incremento es desconocido; si puede sustituirlo, el techo entero es direccionable — **y R2 es la única fila que abre esa puerta.** |
| **Qué costaría (verificado)** | **Bajo-medio en datos, desconocido en UI.** El modelo ya es multi-tenant con N conexiones y roles `owner/admin/agent/viewer` (§3.5). Lo que **no** está probado es la UI de `Qualify/connections_page.py` con 12+ cuentas, ni el conmutador de contexto por agente. |
| **¿Cubierto?** | Sí en fundación (ADR 24, W1). **No** como experiencia de operador multi-marca. Y `docs/backlog-crm-workflows.md` §547 marca *"gestión de asientos multi-agente"* como **"sigue sin fase — es cliente uno, fuera de este sprint por instrucción explícita"** → **el requisito está diferido a propósito y este documento aporta la razón de demanda para reconsiderarlo.** |
| **Fase** | Parking lot §5.4 hoy. |
| **Qué lo validaría** | *"¿Cuántas cuentas gestiona la misma persona?"* Si la respuesta es 1, R2 desaparece. Coste: una pregunta. **Barata y potencialmente elimina la fila entera** — por eso está alta. |

### R3 — Arrancar el reloj administrativo de Meta (Advanced Access + App Review + Business Verification)

| Campo | |
|---|---|
| **Demanda** | *"¿Cuándo puedo publicar en producción a las cuentas de mis nueve oficinas?"* (§4.3, ensayado) |
| **Fuente ancla** | `CLAUDE.md`, enmienda a ADR 21; `docs/backlog-crm-workflows.md` **B0-1b**, que ya lo clasifica *"el item de mayor plazo del proyecto… **MÁXIMA por plazo, no por esfuerzo. Coste de ingeniería cero**"* y añade un disparador que yo no conocía: **los webhooks exigen Business Verification incluso sobre cuentas propias**. |
| **Segmento** | Brokerage y franquicia. Bloquea el trato entero, no una feature. |
| **Qué costaría** | **Cero ingeniería.** Precondición: entidad legal con NIF/domicilio/web coincidentes. Dueño: el fundador. |
| **¿Cubierto?** | **Sí, y ya está marcado como máxima prioridad por plazo.** Mi aportación es solo la confirmación desde el lado demanda: en §4.3 **es literalmente la primera pregunta del comprador grande**, antes de features. |
| **Qué lo validaría** | Ya está validado por la arquitectura. **No necesita validación de prospecto: necesita que alguien lo empiece.** |

### R4 — Inyección obligatoria de identificación del broker en cada publicación

| Campo | |
|---|---|
| **Demanda** | *"Cada post lleva la identificación del broker por normativa. ¿Se inyecta sola o la pongo yo 12 veces al día?"* (§4.2, ensayado) |
| **Fuente ancla** | TREC, reglas de redes sociales — https://www.trec.texas.gov/article/what-you-need-know-comply-our-social-media-rules ⚠ **`ECONNREFUSED` al leerla el 2026-07-29; extracto de índice, segunda mano, sin verificar.** |
| **Segmento** | Brokerage/franquicia **en EE. UU.** ⚠ **Puede no aplicar en Uruguay** — depende enteramente de R0. |
| **Quién ya lo sirve** | Desconocido. No lo comprobé en Lofty/BoldTrail. |
| **Qué costaría** | **Bajo** — un campo por marca + composición en el caption, *si* existiera el servicio de publicación. **Hoy `publishing/` es un solo `client.py` sin servicio (§3.5)**, así que el coste real está dominado por construir Parte 4-A, no por este requisito. |
| **¿Cubierto?** | No aparece en W3 (`docs/backlog-crm-workflows.md` §3). |
| **Qué lo validaría** | Preguntar al cliente uno qué exige su regulador nacional. Coste: una pregunta. **Alto riesgo de que esta fila sea puro artefacto estadounidense.** |

### R5 — El ciclo de vida del listing gobierna el calendario de publicación

| Campo | |
|---|---|
| **Demanda** | Formulada por el propio bug de un competidor, que es la mejor evidencia que hay de que a alguien le dolió. |
| **Fuente ancla** | Notas de versión de BoldTrail: *"Fixed an issue where **inactive listings were continuing to be queued and posted** to social media through Legacy CLM's scheduled post system"* — https://help.insiderealestate.com/en/articles/6301303-boldtrail-product-release-notes, accedido 2026-07-29 |
| **Segmento** | Todos los que publiquen listings. |
| **Quién ya lo sirve** | BoldTrail — **después de haberlo roto en producción**. |
| **⚠ Reclasificada (2026-07-30, ADV3)** | `gtm` tiene razón y acepto la corrección: **BoldTrail lo envió como corrección de defecto, no como producto.** Es un **requisito de clase defecto** — su ausencia pierde tratos, su presencia no gana ninguno. **No es facturable** y tiene la peor relación coste/poder-de-precio de toda la cola. **Esto no dice "no construirlo"; dice "no contarlo como justificación de ingresos".** Baja en el ranking de §6.1 por ese motivo, no por dejar de importar. |
| **Qué costaría** | **Medio y arquitectónicamente interesante:** `scheduled_posts` (0003) ya existe con `status` y `scheduled_for`, pero **no hay noción de listing en el modelo de datos** (§3.5). Requiere una entidad de listing y un enganche de invalidación. **No lo abordaría hasta que Parte 4-A exista.** |
| **¿Cubierto?** | No. |
| **Qué lo validaría** | *"¿Alguna vez habéis publicado una propiedad que ya estaba vendida?"* Si sí, cuánto costó. Coste: una pregunta, y produce una anécdota vendible. |

### R6 — Contenido no genérico y diferenciado localmente

| Campo | |
|---|---|
| **Demanda** | *"Some videos that all agents are using at the same time"* · *"it is very generic information… you do not have much control of it"* |
| **Fuente ancla** | §1.1, Capterra Roomvu (2,5/5): Kamyab G. (abr 2023), Wisam Askar (abr 2026), VR (abr 2026) — https://www.capterra.com/p/218588/roomvu/reviews/, accedido 2026-07-29 |
| **Segmento** | Todos. Es el tema **más denso** de toda la cosecha. |
| **Quién ya lo sirve** | **Nadie bien.** Roomvu lo intentó y tiene 2,5/5 por ello. Es a la vez el hueco más grande y el cementerio más grande. |
| **Qué costaría** | **Alto y no acotado.** Es la tesis nuclear de Qualify (leer contenido primario), pero **exige el pipeline que no existe**: sin ClickHouse, sin `packages/pipeline`, sin Celery (§3.5, verificado). No es una feature: es la Parte 3 entera. |
| **¿Cubierto?** | Sí — es la Fase 1 Parte 3 más la Fase 2. |
| **Qué lo validaría** | Enseñar al cliente uno el análisis de **un** vídeo real suyo, salido de la cascada que ya corre, y preguntar si eso le diría algo que no sabía. **Esta sí es demostrable hoy** y es la única demo real que tenemos (§3.5). **La validación más barata de la fila más cara** — por eso vale la pena hacerla pronto aunque la construcción sea tardía. |

### R7 — Soporte humano con cobertura de fin de semana

| Campo | |
|---|---|
| **Demanda** | *"It is impossible to reach a live person"* · *"if I list a house on weekend I can't advertise it till working day"* |
| **Fuente ancla** | §1.1 (Filomena C., ago 2025; Ana M., may 2024), §1.3 (Jessica G., oct 2025; Raymond K., sep 2025), §1.4 (Alexander R., ago 2025). **Presente en las cuatro herramientas cosechadas** — el tema más transversal. |
| **Segmento** | Todos. |
| **Quién ya lo sirve** | **Ninguno de los cuatro.** Es el fallo universal de la categoría. |
| **Qué costaría** | **Cero código y todo el tiempo del fundador.** No es un requisito de software; es un requisito de modelo operativo, y limita cuántos clientes se pueden atender antes de contratar. |
| **¿Cubierto?** | No, y no debería estar en un backlog de software. Va aquí porque **es una condición de cierre**. |
| **Qué lo validaría** | Ya validado por la cosecha (5 fuentes independientes). Lo que falta decidir es **si se promete**. |

### 6.1 — Orden final

**Reordenada 2026-07-30 tras ADV3.** La columna nueva —**poder de precio**— es la que cambia el orden: `gtm` demostró que "cabe bajo el techo" y "se puede cobrar por ello" no son la misma pregunta, y yo las había tratado como si lo fueran.

| # | Requisito | Tratos bloqueados | Coste de validar | Coste de construir | ¿Cabe bajo el techo? | **¿Poder de precio?** |
|---|---|---|---|---|---|---|
| **V1** ⭐ | ¿Pueden conectarse las cuentas de los agentes? | *Determina si hay ICP* | 1 pregunta | — | n/a | n/a |
| **V2 + V4** ⭐ | Techo real · ¿desplaza o se suma? | *Determina si hay negocio y de qué tipo* | 2 preguntas | — | n/a | n/a |
| **R3** | Arrancar el reloj de Meta | Alto | Nulo (ya decidido) | **Cero ingeniería** | Sí | n/a — es un trámite |
| **R2** ⭐ | Multi-cuenta, marca por agente | Alto — **condicionado a V1** | 1 pregunta | Bajo-medio | **Sí, demostrado** | **La más alta de la cola.** Tokko Enterprise ≈$185/mes se cobra hoy por esto. **Única fila que habilita desplazamiento.** |
| **R7** | Soporte con fin de semana | Alto, transversal | Ya validado **en ambos regímenes** (§1.7) | Cero código / caro en tiempo del fundador | Sí | Media — diferencia, pero rara vez se factura aparte |
| **V3 + V5** | Revalidar §1-§3 contra Uruguay · régimen legal | *Todos, indirectamente* | 45 min | — | n/a | n/a |
| **R1** | Log auditable de aprobación | **DESCONOCIDO** — ancla en revisión, ver V5 | 1 pregunta | Medio | Probablemente | Desconocido hasta saber qué ley aplica |
| **R4** | Identificación del broker | ⚠ **probablemente solo EE. UU.** | 1 pregunta | Bajo | Sí | Baja |
| **R5** | Listing gobierna el calendario | Medio | 1 pregunta | Medio | Sí | **Nula — clase defecto.** Construir sí; contar como ingreso no. |
| **R6** | Escucha de contenido primario de terceros | Alto a largo plazo, **cero hoy** | Demo, pero hay que prepararla (§3.5) | **Muy alto — Parte 3 entera** | **No. Ver §6.2.** | Desconocida — es un **delta sin precio**, ver §6.3 |

### 6.2 — ADV3: ¿cabe algo de esto bajo el techo? — la sección que hay que leer si solo se lee una

La pregunta que me pasa el lead vía `gtm`: la escucha social vertical inmobiliaria **no existe en LATAM/España**. ¿Es whitespace, o es que no cabe bajo el techo?

**Mi respuesta `[H]`: es principalmente que no cabe, y las dos explicaciones son indistinguibles desde fuera — que es precisamente lo que hace peligrosa la lectura optimista.**

El razonamiento, con los números sobre la mesa:

| Concepto | Cifra | Fuente |
|---|---|---|
| Presupuesto de software **de toda la empresa** del cliente uno | **$50-185/mes**, ~5 asientos | `docs/oferta-mercado-inmobiliario.md` §2.1 |
| Un asiento de listening genérico | Exolyt $400-950/mes · Sprout $249+/asiento | ídem §4.6 |
| BoldTrail, suite inmobiliaria de referencia (EE. UU.) | ~$5.988/año ≈ **$499/mes** | ídem §2.3 |
| ⭐ **Tokko Broker, líder LATAM — plan Equipo (3-5 usuarios)** | **$1.999 MXN/mes ≈ $100-110 USD/mes** | §1.7, precio de lista público, accedido 2026-07-30 |

**El dato de Tokko es el que cierra el argumento**, porque llega por una vía independiente: no es el gasto declarado de un cliente (que podría ser un cliente tacaño), es **la lista de precios pública del líder de la categoría en la región**. El CRM inmobiliario #1 de América Latina, con toda su funcionalidad, cuesta ~$100/mes para un equipo de 3-5. **Ese es el precio de mercado de un producto vertical completo en esta región** — no un techo psicológico del cliente uno. Cualquier cosa que Qualify quiera cobrar se mide contra eso.

Un solo asiento de la herramienta **más barata** de la categoría adyacente cuesta **entre 2× y 19×** el presupuesto **total** de software de la empresa. Y esa herramienta no lleva la parte cara de Qualify: **el análisis multimodal por vídeo** (VLM + ASR sobre GPU) tiene coste marginal por unidad de contenido, no coste marginal cero como el software. **Un producto de escucha multimodal no es solo caro de construir: es caro de operar por cada vídeo analizado**, contra un cliente cuyo techo entero es $50-185/mes.

**Tres conclusiones, en orden de dureza:**

1. **R6 —la tesis nuclear de Qualify— no cabe bajo este techo, y no es cuestión de eficiencia.** Aunque el coste de inferencia bajara 10×, el problema es que el comprador nunca ha pagado ese orden de magnitud por software y no hay evidencia de que empiece. Vender R6 a este segmento exige **un comprador distinto**, no un precio distinto.
2. **Lo que sí cabe bajo el techo es exactamente lo aburrido**: R3 (trámite, cero coste), R7 (soporte humano, cero código), R2/R4/R5 (funcionalidad de operación, coste marginal ~cero). **Todas son features de coste marginal nulo por unidad de uso** — que es la única forma de servir a un cliente de $50-185/mes.
3. **La ausencia de la categoría en LATAM es, con más probabilidad que no, información sobre la demanda y no sobre la oferta.** Whitespace y no-mercado se ven idénticos hasta que alguien intenta cobrar. Y hay una prueba barata que los distingue, que es V2: preguntar **qué tendría que hacer algo para que pagaran por encima de su techo actual**. Si no hay respuesta a esa pregunta, es no-mercado.

**Lo que esto NO dice:** no dice que Qualify deba abandonar R6. Dice que **R6 no cierra este trato**, y que si R6 se construye, su justificación tiene que venir de otro segmento (el brief menciona tres nichos más) o de otro comprador, no de la inmobiliaria uruguaya. Presentar R6 como el camino al cliente uno sería el error caro de esta sesión.

#### 6.2-bis — La premisa oculta que `gtm` encontró en mi propio argumento (2026-07-30)

**Acepto la corrección y es más importante que el argumento que corrige.** Yo traté el techo de $50-185/mes como **presupuesto disponible**. No lo es: es **gasto ya comprometido** — CRM (Tokko/Wasi) más portal. Nadie tiene $100/mes esperando a que aparezca Qualify.

Eso reformula la pregunta entera. No es *"¿cabe R1+R2+R5 bajo $50-185/mes?"* sino:

> **¿Qualify DESPLAZA la línea de CRM que ya pagan, o se SUMA encima de ella?**

- **Si desplaza** → el techo entero es direccionable, y **R2 es la fila que lo hace posible**, porque es exactamente lo que Tokko/Wasi venden hoy por ese dinero.
- **Si se suma** → el incremento realista sobre un gasto ya comprometido es **desconocido**, y `gtm` se negó explícitamente a inventar la cifra. Yo tampoco la voy a inventar. Se resuelve con **V4**, una pregunta.

**Y una carencia que hay que decir en voz alta porque afecta a la lectura de todo §6:** **nadie ha estimado N (número de clientes)** en esta sesión. Sin N, `precio × N vs. coste amortizado de construcción` **no se puede evaluar**. Esta cola **ordena filas; no demuestra que ninguna sea rentable.** Mi §6.2 original decía "R6 no cabe bajo el techo" con más aplomo del que los datos sostienen — la conclusión aguanta (el orden de magnitud es demasiado grande para cerrarse con volumen), pero el resto de las filas **no están probadas rentables, solo ordenadas**.

### 6.3 — La lectura incómoda

De las diez filas, **cinco no son código** (V1, V2, V3, R3, R7 son preguntas, trámite y modelo operativo), y **la única que es la tesis nuclear de Qualify — R6 — es la más cara, la que ningún comprador cosechado pidió** (§2.2 hallazgo 2) **y la que no cabe bajo el techo del único cliente que paga** (§6.2).

Lo que este mercado pide es aburrido: *que funcione, que pueda demostrar que lo aprobé, que me cojan el teléfono el sábado, que no me hagan gestionar doce logins, y que cueste menos que lo que ya pago.* Si el brief esperaba la respuesta aburrida, aquí está, y no la estoy suavizando.

**Y un matiz que sí es a favor del proyecto, para no dejar la lectura sesgada:** el hueco que `opportunity` señala —**escuchar contenido primario de terceros**, no contenido propio— sigue siendo real y sigue sin ocuparlo nadie, ni Lofty ni BoldTrail ni el régimen LATAM. Lo que este eje añade es **la restricción, no la refutación**: existe, nadie lo pide, y no cabe en el bolsillo de este comprador. Las tres cosas a la vez. Que la distinción primera-parte / tercera-parte sea la carga del argumento la mantengo intacta — es lo único que separa a Qualify de un Social Studio.

### 6.4 — "Nadie lo pide": ¿categoría no deseada, o delta sin precio? (añadido 2026-07-30)

`gtm` reformuló mi hallazgo de forma que lo mejora, y el lead me pidió comprobarlo contra mis propios datos. Lo he hecho, y **mi corpus no puede resolverlo — pero puede acotarlo, y eso ya es útil.**

**La reformulación:** el régimen A demuestra que los agentes **sí compran escucha** — de tipo keyword/texto (BizAI, Pipeline ROI, Birdeye, Sked lo venden hoy). Entonces la pregunta no es *"¿quiere este nicho escuchar?"* sino la más estrecha: **"¿pagaría este comprador un delta por escucha de grado-contenido sobre la escucha de grado-keyword que ya compra?"** Un delta sin precio no es lo mismo que una categoría no deseada.

**Lo que dice mi corpus (§2.2), comprobado honestamente:**

- En **cero** de las migraciones documentadas aparece escucha como motivo — **ni de grado-keyword ni de grado-contenido**. Los motivos son personalización, facilidad de uso, IDX y mandato del brokerage.
- **Eso acota algo real:** si la escucha keyword fuera un motor de cambio, debería asomar en un corpus de razones de cambio, y **no asoma en ninguna forma**.
- **Pero no puede resolver la pregunta del delta**, y decirlo importa: mi corpus es de **cambios de CRM**, y la escucha keyword se vende por **proveedores distintos que se compran en paralelo**, no como sustitución. Nadie "cambia de CRM por Birdeye" porque Birdeye no es un CRM. **Mi corpus está estructuralmente ciego a esa compra.**

**Conclusión honesta `[H]`:** mi hallazgo original debe leerse **más estrecho de lo que lo escribí**. Lo que probé es *"la escucha no impulsa el cambio de CRM"*. Lo que **no** probé —y sugerí sin querer— es *"la escucha no se desea"*. `gtm` tiene razón: **es un delta sin precio, no una categoría demostradamente no deseada.** Corrijo mi propio marco.

**Y hay una tercera explicación del silencio, que no requiere que la categoría sea indeseada** — la aporta `opportunity` (T-6) y encaja incómodamente bien: Uruguay opera bajo la **Ley 18.331**, protección de datos de grado RGPD con adecuación UE desde 2012, reafirmada en 2024. **Procesar vídeo, audio y comentarios de terceros que nunca consintieron puede ser legalmente caro allí de un modo que no lo es en EE. UU.** Si es así, el silencio del corpus no significa "no lo quieren": significa que **el producto que lo entregaría puede no ser vendible en esa jurisdicción**, que es un problema distinto y peor.

**Tres explicaciones del mismo silencio, ninguna descartada:** (a) no lo quieren, (b) lo querrían pero nadie les ha enseñado qué compra el delta, (c) su régimen legal lo encarece. **V5 distingue (c). Una demo con un vídeo suyo distingue (b) de (a).** Ambas caben en la misma llamada, y hasta entonces **nadie debería afirmar cuál es** — yo el primero.

### 6.5 — La hipótesis nula de `opportunity`, y la evidencia POSITIVA que le encontré en mi propio corpus (2026-07-30)

`opportunity` respondió a ADV2 con un desdoblamiento que acepto, y con un tercer punto que **es mejor que lo que ninguno de los dos había dicho**. Lo registro porque es el argumento más fuerte que ha salido de la sesión, y va en contra del proyecto.

**Lo que conceden y lo que no** — y en ambas tienen razón:
- **No conceden en "nadie lo pide"**, y hacen bien: *"los compradores nombran sustitutos, no categorías; nadie pide por su nombre una categoría para la que no tiene referente"*. Y el instrumento está mal elegido: **un corpus de reseñas de CRM mide insatisfacción con CRMs, no demanda latente de una categoría que no existe.** Es exactamente lo que yo mismo concluí en §6.4 por otra vía. Convergemos.
- **Conceden del todo en el techo de precio**: no dice "nadie lo pide", dice que **existe una explicación estructural suficiente de la ausencia**.

**El punto nuevo, y es el que importa:** estamos tratando *"nadie lo pide"* y *"no cabe en el presupuesto"* como **dos evidencias independientes que convergen**. Probablemente **no son independientes**. Ambas son consistentes con una sola explicación más simple:

> **Hipótesis nula: este comprador no está en el mercado de productos de información, a ningún grado ni a ningún precio. Compra herramientas de ejecución — publicar, contactar, cerrar.**

Si eso es cierto, la pregunta reformulada de `gtm` no solo se responde "no": **está mal formulada.** No hay delta que pagar porque **no hay categoría base**.

#### Lo que aporto: la hipótesis nula tiene evidencia POSITIVA en mi cosecha, no solo ausencia

`opportunity` la archiva como hipótesis que nadie ha intentado matar. **Sí se puede contrastar, y con mis datos**, porque no hace falta argumentar desde la ausencia: puedo enseñar **qué sí pidieron**. Recorrí cada "ojalá hiciera X" de §1-§3:

| Petición literal | Fuente | ¿Ejecución o información? |
|---|---|---|
| *"I wish it had more automations and allowed to send batch text messages"* | §1.2 FUB | **Ejecución** |
| *"I wish it could include auto create newsletters/relevant emails"* | §1.2 FUB | **Ejecución** |
| *"Not a way to capture leads within the software"* | §1.2 FUB | **Ejecución** |
| *"would be great if they integrated with social media and WhatsApp for communication"* | §1.2 FUB | **Ejecución** |
| Recordatorios de cumpleaños / aniversarios de compra | §2.1 FUB | **Ejecución** |
| *"you do not have much control of it"* (sobre lo que se publica) | §1.1 Roomvu | **Ejecución** |
| *"if I list a house on weekend I can't advertise it till working day"* | §1.1 Roomvu | **Ejecución** |
| *"AI assistant is robotic, unable to be instructed"* | §1.4 Lofty | **Ejecución** |
| *"texting never worked properly"* | §1.4 Lofty | **Ejecución** |
| *"Update all… posts **and respond to followers**"* | §3.3 oferta de empleo | **Ejecución** |

**De todas las peticiones cosechadas, prácticamente todas son de ejecución.** No es que falte la petición de información: es que **está presente la petición de ejecución, de forma abrumadora y unánime, en cuatro herramientas y tres países**. Eso es evidencia positiva, no un argumento desde el silencio, y **refuerza la hipótesis nula de `opportunity` más de lo que ellos mismos afirmaron.**

#### Las dos excepciones, y son las que refinan la hipótesis en vez de romperla

Encontré exactamente dos peticiones de información en toda la cosecha:

1. *"only good for overseeing… **We have had to make our own external reporting system**"* — Menucha S., Head of IT, §1.2.
2. *"Support the company and agent by **tracking incoming leads/prospects so marketing campaigns can be adjusted**"* — §3.3, oferta de empleo.

**Las dos son información sobre su propia actividad — reporting y atribución — no sobre el mundo.** Eso afina la hipótesis nula hasta algo más preciso y más útil que la versión original:

> **`[H]` Este comprador sí compra información, pero solo información sobre lo que él mismo hizo (atribución, reporting, "¿qué campaña funcionó?"). No hay una sola petición de información sobre el mundo exterior — competidores, conversación de mercado, contenido ajeno.**

**Y esa frontera cae exactamente encima de la línea que separa a Qualify de sus competidores.** R6 —escuchar contenido primario de **terceros**— está del lado que **nadie pidió en ninguna de mis fuentes**. La tesis T-3 de `opportunity` (*"¿qué Reel funcionó?"*) está del lado que **sí** se pide, y es la única de sus tesis de información que mi corpus respalda con evidencia positiva. **Si algo de la línea de información se construye para este nicho, T-3 es la que tiene demanda observable detrás y R6 la que no.** Es el hallazgo más accionable de esta ronda y no lo tenía antes de que `opportunity` empujara.

#### Cómo se mata la hipótesis nula

No con más investigación de escritorio: **enseñándole al cliente uno el análisis de un vídeo suyo y viendo si pregunta por el precio.** Si ante contenido primario real y concreto sigue sin haber tracción, la hipótesis nula sobrevive y **R6 no debería construirse para este nicho a ningún precio** — que es una conclusión más fuerte que "no cabe en el presupuesto", y peor.

---

## §7 — Criterios de calificación y descalificación

Marco: **M-E-D-Ch** (Metric, Economic buyer, Decision criteria, Champion), recortado de MEDDIC porque en ciclo PYME el resto sobra. Declarado en §4.

### 7.1 — Señales de encaje (calificar)

| Señal | Por qué, con su ancla |
|---|---|
| **Existe una persona cuyo trabajo es publicar Y responder** | §3.3: *"Update all Facebook… posts **and respond to followers**"*. Es el campeón y el usuario a la vez. Sin ese puesto, no hay dolor concentrado. |
| **Esa persona gestiona ≥5 cuentas de agentes distintos** | §3.3. Multiplica el valor y justifica precio (R2). |
| **El brokerage firma su propio software** (no lo hereda de la franquicia) | §2.1: *"kvCore came as standard CRM offering"*. Si lo hereda, **no hay comprador económico**. |
| **Están enfadados con su proveedor actual y saben decir por qué** | §2.2 hallazgo 3: el disparador real es el agravio, no la feature. |
| **Instagram es el canal principal declarado** | §3.5: es lo único donde hay camino técnico. |
| **Aceptan que ellos aprueban antes de publicar** | §3.4 + O-8. Si lo ven como *ventaja*, encajan; si como *fricción*, no. |

### 7.2 — Señales de descalificación (matan un lead que se ve bien)

| Señal | Por qué mata |
|---|---|
| **Su necesidad central es programar a TikTok** | **Bloqueado, no aplazado.** Política de TikTok, sin mitigación de ingeniería. Descalificar **en la primera llamada**, no en la tercera. |
| **Quiere respuestas autónomas y no le convence el humano-en-el-bucle** | Permanentemente fuera. A ~65% de precisión, 1 de cada 3 borradores está mal. No se desbloquea con una fase. |
| **Quiere bandeja única cross-canal (IG + FB + WhatsApp + email)** | Fase 6. Si es condición de compra, no hay trato en 2026. ⚠ **Y ojo: si es un cliente latinoamericano, WhatsApp puede no ser un "extra" sino EL canal** (`backlog-crm-workflows.md` §494) → esta descalificación podría estar eliminando **precisamente el mercado del cliente uno**. Es la contradicción más peligrosa de este documento y no la puedo resolver sin R0. |
| **Su presupuesto de marketing es pauta, no orgánico** | Marketing API fuera del alcance de ADR 21. |
| **Es un agente individual cuyo CRM lo paga el brokerage** | §2.1, §4.1. No es el comprador económico y su JTBD es "menos tiempo", no "más datos". |
| **Exige SSO, residencia de datos o DPA firmado para arrancar** | Nada existe ni está en roadmap (§4.3). |
| **Exige referencias de clientes comparables** | Somos pre-cliente-uno. Honestidad, no rodeo. |
| **Necesita fecha comprometida de publicación en producción** | El reloj es de Meta, no nuestro (R3). Prometer fecha aquí es la forma más rápida de perder el trato **después** de firmarlo. |
| ⭐ **Parece una franquicia grande, pero cada oficina paga su propio software** | **Añadido 2026-07-30.** *"El franquiciado asume los costos"* (Forbes Uruguay sobre RE/MAX AR&UY, vía `docs/oferta-mercado-inmobiliario.md` §5). El logotipo sugiere un comprador de presupuesto central que **no existe**. Es el lead que mejor se ve y peor cierra: semanas de ciclo para descubrir que quien decide es el titular de una sola oficina con techo de $50-185/mes. **Pregunta que lo detecta en 30 segundos: "¿la central os impone o paga alguna herramienta?"** |
| ⭐ **Los agentes son autónomos y no conectarán sus cuentas** | **Añadido 2026-07-30.** Falsador compartido de 3 tesis de `opportunity`. Si la cuenta es del agente y se la lleva al irse, no hay unidad de instalación en la agencia. Detectar con **V1**, en la primera llamada, no en la demo. |
| ⭐ **Su gasto total en software es inferior a lo que costaría operarle** | **Añadido 2026-07-30.** Si el núcleo de su necesidad es análisis multimodal de vídeo (coste marginal real por unidad) y su techo es $50-185/mes para toda la empresa, **el trato es negativo aunque se firme** (§6.2). Descalificar por economía unitaria, no por encaje. |

### 7.3 — La descalificación que más deals ahorraría

**Preguntar en el minuto tres: *"¿el software que usáis hoy lo elegisteis vosotros o os lo da la franquicia?"*** Si es lo segundo, el trato es un no independientemente de todo lo demás — y todo lo cosechado en §2.1 dice que **lo segundo es lo habitual**. Ninguna herramienta de venta ahorra tanto tiempo como esa pregunta.

---

## §8 — Qué haría yo con la siguiente hora de investigación

**Reescrito 2026-07-30 tras la recalibración de §0.** En orden, y ninguna cuesta código:

1. **V1 + V2 — dos preguntas al cliente uno, en la misma llamada** (§6.0). *"¿Puedes conseguir que tus agentes conecten sus cuentas de Instagram, y querrías?"* y *"¿cuánto pagáis por software en total, y qué tendría que hacer algo para pagar más?"*. Determinan, respectivamente, **si existe ICP** y **si existe negocio**. Nada más de esta lista importa hasta tenerlas.
2. ⭐ **Matar (o no) la hipótesis nula: enseñarle al cliente uno el análisis de UN vídeo suyo y ver si pregunta por el precio.** Es la única prueba que distingue *"no cabe en el presupuesto"* de *"no está en el mercado de productos de información en absoluto"* (§6.5). Si ante contenido primario real y concreto no hay tracción, **R6 no debería construirse para este nicho a ningún precio** — conclusión más fuerte y peor que la del techo. Requiere una tarde de preparación previa (§3.5: la cascada solo corre a mano, con el grupo `ml` instalado y los tests `integration` lanzados a propósito).
3. **V3 + V5 — recorrer R1-R7 con el cliente uno y preguntar por su régimen de protección de datos** (45 min). Toda §1-§3 es `[H-US]`; esto es lo único que la convierte en evidencia sobre el comprador real, y V5 decide dónde se ancla R1.
3. **Buscar el equivalente uruguayo del *watering hole*** — grupos de Facebook y WhatsApp de agentes uruguayos/colombianos. **No son accesibles a un agente automático** y `comparasoftware` fue la única fuente LATAM de primera mano que encontré en toda la sesión (§1.7). Requiere una persona.
4. **Verificar de primera mano las fuentes de cumplimiento** (TREC, HousingWire, AB 723) **solo si V3 indica que el ángulo regulatorio aplica en Uruguay**. Si no aplica, §3.4 y las filas R1/R4 pierden gran parte de su peso y no merece la pena el esfuerzo. Ojo: NAR ya resultó más delgada que su fama.
5. **Leer Reddit a mano** — bajó de prioridad: `r/realtors` sigue bloqueado para agentes automáticos (§2.0), pero **ahora sabemos que es el mercado equivocado**. Solo vale la pena si se persigue el segmento estadounidense.
6. **Perfilar Lofty con `competitor-profiling`** — su Social Agent se lanzó el 28-jul-2026 y solo lo conozco por notas de prensa.
