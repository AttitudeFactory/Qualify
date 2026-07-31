# Oferta de mercado — nicho inmobiliario (real estate)

**Eje:** oferta / estado del campo. Qué existe HOY, con fuente y fecha de acceso.
**Autor:** `gtm-specialist` · **Sesión:** 2026-07-29
**Alcance:** herramientas que ya sirven a real estate en social/video; techo de gasto observado; quejas documentadas; existencia (o no) de listening sobre contenido primario; estructura de decisión de compra.

> **Qué NO contiene este documento (por diseño).** No hay conclusiones prospectivas ("hacia dónde va el mercado") ni requisitos de producto. Eso lo escriben `market-opportunity-analyst` (`docs/oportunidades-mercado-*.md`) y `sales-consultant` (`docs/demanda-ventas-*.md`) leyendo este documento. Aquí solo se documenta el campo tal como está, con fuente.

> **Convención de confianza.** Cada afirmación va marcada:
> `[V]` verificado contra fuente primaria (página de precios, doc oficial, reseña textual) con URL y fecha;
> `[S]` secundaria (agregador, comparativa de terceros);
> `[H]` hipótesis / inferencia del autor, no verificada.

## Estado de secciones

**Redactado 2026-07-29 · revisado y ampliado 2026-07-30** (tres correcciones entrantes + dos rondas adversariales). Todo lo añadido el 30 va fechado en su encabezado.

| # | Sección | Estado |
|---|---|---|
| 5 | Estructura de decisión (quién decide, quién paga) | **LISTA** — resuelta primero, calibra 1-4 |
| 1 | Inventario de oferta | **LISTA** · **+§1.1-bis** Lofty AOS (30-jul) |
| 2 | Techo de gasto observado | **LISTA** · **+§2.5** resolución ADV3 (30-jul) |
| 3 | Quejas documentadas (textuales) | **LISTA** |
| 4 | ¿Existe listening sobre contenido primario? | **LISTA** · **+§4.6** LATAM vs EE. UU. · **+§4.7** frontera de capacidad · **+§4.8** posición ADV1 (30-jul). **§4.5 lleva una retractación parcial** |

**Rondas adversariales resueltas:** **ADV1** (vs `opportunity`, whitespace vs no-demanda) → §4.8, *acuerdo*. **ADV3** (vs `sales`, techo vs coste de construir) → §2.5, *parcial*.

---

## 5. Estructura de decisión — quién decide y quién paga

> **Se resuelve primero, a propósito.** El brief lo listaba como tarea 5 pero advertía que determina cómo leer todo lo demás. Es correcto, y de forma más fuerte de lo previsto: **hay dos mercados inmobiliarios distintos aquí, no uno**, y confundirlos invalida cualquier cifra de precio. Las secciones 1-4 van etiquetadas por régimen.

### 5.0 El hallazgo que reordena el documento: el comprador de Qualify es LATAM, no EE. UU.

Casi toda la oferta inventariable y **todo el pricing público** de software inmobiliario es **estadounidense**. Pero el cliente uno de Qualify no lo es. Del propio repo:

- `docs/backlog-crm-workflows.md:22` — cliente uno = **«Agencia inmobiliaria en Uruguay (amigo del fundador)»**; cliente cero = tienda **PuntoServis** (Cúcuta, Colombia).
- `docs/refinamiento-sprint1.md:52` — el seed codifica `country` como **`'UY'` (inmobiliaria)** y `'CO'` (PuntoServis).
- `docs/refinamiento-sprint1.md:588` — el tenant inmobiliaria es **«1 `owner` + N `agent`»**, y es literalmente *«la razón de que exista el modelo de asientos»*.

**Consecuencia metodológica, y hay que decirla sin suavizar:** si este documento presentara precios de Follow Up Boss, kvCORE o Zillow Premier Agent como «el techo de gasto del nicho», estaría midiendo un mercado que no es el del cliente que paga. Los dos regímenes se documentan por separado y **la sección 2 da dos techos, no uno**.

### 5.1 Los dos regímenes

| Dimensión | **Régimen A — EE. UU./Canadá** | **Régimen B — LATAM (UY/CO)** ← *donde está cliente uno* |
|---|---|---|
| Figura del agente | *Independent contractor* afiliado a un broker; licencia propia | **Asesor** adscrito a una inmobiliaria/oficina; la marca comercial es la de la oficina |
| Quién compra la generación de leads | **El agente, de su bolsillo** (Zillow Premier Agent se contrata a título individual) | **La oficina**: el plan de portal es *por inmobiliaria*, no por asesor |
| Quién compra el CRM | Mixto: el brokerage/franquicia suele incluir uno (KW Command, BoldTrail vía RE/MAX, Moxi vía Anywhere); el agente añade el suyo si no le sirve | **La oficina**, si compra alguno |
| Existe MLS (base cooperativa de fichas) | **Sí** — y es la infraestructura sobre la que se monta media industria de software | **No hay equivalente funcional.** Los portales privados (InfoCasas, Gallito, Fincaraíz, Metrocuadrado, MercadoLibre) ocupan ese hueco, pero son medios de pago por exposición, no cooperativas de datos |
| Presupuesto de marketing por cabeza | Alto y muy disperso (ver §2) | Concentrado en la suscripción al portal |
| Confianza | `[V]` estructura documentada; `[S]` en las cifras que solo tienen fuente secundaria | `[V]` para el modelo de franquicia; `[S]` para precios de portal (ver §2) |

### 5.2 La franquicia NO es un comprador central con presupuesto propio

La hipótesis del brief —*«un agente individual paga $50/mes pero una franquicia decide con presupuesto de $50k»*— **no se sostiene en LATAM, y solo parcialmente en EE. UU.** Evidencia directa sobre RE/MAX Argentina & Uruguay (>225 oficinas):

> «Cada oficina es un emprendimiento independiente que adopta la marca, los estándares y la tecnología de RE/MAX, pero gestiona su propia estructura. **El franquiciado asume los costos**»
> — Forbes Uruguay, *«RE/MAX fue vendida por US$880 millones: qué cambia en Uruguay…»*, https://www.forbesuruguay.com/negocios/remax-fue-vendida-us880-millones-cambia-uruguay-cuanto-cuesta-hoy-tener-una-franquicia-marca-n92072 · acceso 2026-07-29 `[S]` (medio de negocios, no fuente corporativa)

La franquicia **impone estándares y stack, no lo paga**. Lo que hace es dos cosas, y ambas importan para vender:

1. **Puede bloquear** una compra que no encaje con su stack obligatorio — es un poder de veto, no de compra.
2. **Concentra la venta si el vendedor llega arriba**, pero el desembolso sigue bajando a la oficina.

`[H]` **Hipótesis explícita, no verificada:** el mismo patrón «franquiciado asume costos» aplica a Century 21 y Coldwell Banker en LATAM. No lo he comprobado; no construir sobre ello.

### 5.3 Cuántas cabezas hay que convencer

| Régimen | Decisor real | Pagador | Usuario | ¿Coinciden? |
|---|---|---|---|---|
| A — EE. UU., herramienta de lead-gen | Agente | Agente | Agente | **Sí** — venta de un solo paso, autoservicio viable |
| A — EE. UU., CRM/stack | Broker-owner o franquicia | Brokerage (o agente vía *desk fee*) | Agente | **No** — el usuario no paga y el pagador no usa |
| B — LATAM | **Titular/dueño de la inmobiliaria** | **La inmobiliaria** | **N asesores** | **No** — un decisor, N usuarios |

**Lo operativamente decisivo para Qualify en el régimen B:** el decisor es **una sola persona** (el titular), pero el valor se demuestra sobre **N asesores**. Esto es exactamente la forma que el repo ya asumió sin llamarla así — el tenant inmobiliaria es `1 owner + N agent` (`docs/refinamiento-sprint1.md:588`) y la bandeja compartida multi-agente es *«la razón de esta subsección»* en `docs/backlog-crm-workflows.md:535`. **La estructura de compra del nicho y el modelo de asientos ya construido coinciden.** Eso es un hecho del campo, no una recomendación.

### 5.4 Cómo hay que leer las secciones 1-4 a partir de aquí

1. **Todo precio en USD de tres o cuatro cifras al mes viene del régimen A y NO es el techo del cliente uno.** Se documenta porque es donde está la oferta, no porque sea el presupuesto disponible.
2. **El comprador por defecto asumido en §1-§4 es la oficina/inmobiliaria (régimen B), no el asesor individual.** Donde una fila solo tenga sentido para un agente individual estadounidense, va marcada `[A]`.
3. **La ausencia de MLS en LATAM invalida por diseño una categoría entera de la oferta A** (todo lo que se alimenta de la ficha MLS: listing-to-video automático, sindicación, IDX). Esto se detalla en §1 y es material para el eje de `opportunity`.

---

## 1. Inventario de oferta — qué existe hoy para real estate en social/video

Fechas de acceso: **2026-07-29** salvo indicación. Etiquetas de régimen: **[A]** = EE. UU./Canadá · **[B]** = LATAM (el comprador de Qualify).

### 1.1 CRMs inmobiliarios — régimen A (EE. UU.)

| Herramienta | Qué hace | Módulo social real | Precio | Fuente |
|---|---|---|---|---|
| **Follow Up Boss** | CRM puro de seguimiento de leads; el más recomendado del sector | **No.** Es CRM de lead follow-up; lo social entra por integraciones | Desde **$69/usuario/mes** `[S]` | [luxurypresence.com/blogs/follow-up-boss-pricing](https://www.luxurypresence.com/blogs/follow-up-boss-pricing/) |
| **BoldTrail (ex-kvCORE)** | All-in-one: CRM + web IDX + lead gen. Uno de los más desplegados; se distribuye **vía brokerage/franquicia** | Marketing automation y *social/ad* incluidos en el bundle; no listening | **~$499/asiento/mes** `[S]`. **No publica precio** — es *quote-based* `[V]` (la propia página no lista tarifas) | [theprotoolkit.com/kvcore-pricing-2026-real-estate-agents](https://theprotoolkit.com/kvcore-pricing-2026-real-estate-agents/) |
| **Lofty (ex-Chime)** | All-in-one CRM + IDX + lead gen + **AOS agéntico** — ver §1.1-bis, es la entrada más importante de esta tabla | Suite social agéntica completa (4 líneas de producto) | Desde **~$449/mes** `[S]`, *request-based*. El comunicado del AOS **no menciona precio** `[V]` | [bounti.ai/blog/tools/best-follow-up-boss-alternatives-2026](https://bounti.ai/blog/tools/best-follow-up-boss-alternatives-2026) |

### 1.1-bis Lofty AOS — el incumbente que se movió a terreno agéntico (actualización 2026-07-30)

> **Incorporado a petición del lead; hallazgo original de `sales-consultant`** (`docs/demanda-ventas-inmobiliario.md` §3.1), verificado por mí contra fuente primaria. **Cambia cómo se ve el conjunto competitivo de este documento** y por eso no va como una fila más.

Lofty no es «un CRM con módulo social». Es, por su propia descripción, **un sistema operativo agéntico para real estate** — el mismo encuadre que usa Qualify.

- **2026-02-02 — lanzamiento de Lofty AOS**, presentado como *«the first agentic AI operating system for real estate»*. Componentes iniciales: **Social Agent** (*«Creates a social media strategy, designs, schedules, and posts content»*), **Homeowner Agent** (*«Enriches the database and automates home valuation marketing campaigns that identify high-propensity seller opportunities»*), **Website Builder**, **SEO/AEO Manager**. `[V]` — [globenewswire, 2026-02-02](https://www.globenewswire.com/news-release/2026/02/02/3230303/0/en/lofty-launches-the-real-estate-industry-s-first-agentic-ai-operating-system.html)
- **2026-07-28 — expansión del AOS con Lofty Cowork**, *«AI-powered workspace that automatically prioritizes the most important tasks each day»*, con bloques **«Your Morning Read»** y **«What Needs You Now»** (human-in-the-loop). Descrito como una reconstrucción de la plataforma *«from the ground up around AI»*. `[V]` — [globenewswire, 2026-07-28](https://www.globenewswire.com/news-release/2026/07/28/3334236/0/en/Lofty-Expands-AOS-Its-Agentic-AI-Operating-System-for-Real-Estate-Anchored-by-New-Cowork-Experience.html) · [RISMedia](https://www.rismedia.com/2026/07/28/lofty-expands-agentic-ai-os-real-estate-cowork/)
- **Social Studio**: *«fully automated social media marketing tool that creates and posts real estate content to your social accounts on a consistent schedule»* `[V]` — [lofty.com/feature/social-studio](https://lofty.com/feature/social-studio)
- **Lofty Blast**: ficha → anuncios en FB/IG + email `[S]` (vía `sales`).

**Verificación que me tocaba hacer, y su resultado:** revisé el comunicado del 2026-07-28 buscando específicamente si algún agente analiza **contenido de terceros**. **No.** Cowork opera sobre *«leads, send mass texts, build Smart Plans»*; Sales Agent sobre *«lead engagement»*; Social Agent sobre el contenido social **del propio agente**; Homeowner Agent sobre **la propia base de datos**. El único componente que mira hacia fuera es **House.ai**, *«financial intelligence platform for homeownership»* sobre la capacidad de compra del consumidor — datos financieros, **no contenido social**. `[V]`

> **Cómo hay que leer esto, y es una corrección al tono de mi §4 original:** Lofty ocupa la misma **categoría** que Qualify dice ocupar (agéntico, social, real estate) **sin ocupar la misma capacidad** (no lee contenido primario de terceros). El campo de §4 sigue vacío, **pero no es un campo desierto: es un campo con un incumbente bien financiado construyendo justo al lado.** Registrar «nadie hace listening de contenido primario» sin registrar a Lofty daría una imagen falsa de vía libre.

> **Patrón de la categoría A que hay que registrar:** los dos productos caros (**BoldTrail**, **Lofty**) **no publican precio**. `[V]` — verificado en el sentido de que la ausencia es observable en sus páginas. Es el patrón *sales-gated* clásico. Solo el CRM barato y de compra individual (Follow Up Boss) publica tarifa. Eso es coherente con §5.3: **cuando el comprador es el brokerage, el precio se esconde; cuando es el agente, se publica.**

### 1.2 CRMs inmobiliarios — régimen B (LATAM) ← *la categoría del cliente uno*

| Herramienta | Qué hace | Módulo social real | Precio | Fuente |
|---|---|---|---|---|
| **Tokko Broker** (AR, se autodenomina «el CRM #1 de América Latina») | CRM inmobiliario + sindicación a portales + web | **No hay módulo social.** Su eje es la ficha y su distribución a portales | **MXN 480/mes** (Personal, 1 usuario) · **MXN 990** (Duo, 2) · **MXN 1.999** (Equipo, 3-5) · **MXN 3.499** (Enterprise, 6-10). Propiedades y contactos ilimitados en todos `[S]` | [comparasoftware.com/tokko-broker](https://www.comparasoftware.com/tokko-broker) · su propia página de precios devolvió **HTTP 403** a la consulta automatizada `[V]` |
| **Tokko Broker — Colombia** | ídem | ídem | **COP 300.000–400.000/mes** `[S]` | via búsqueda; sin fuente primaria |
| **Wasi** (CO) | CRM inmobiliario + conexión a **«más de 30 portales inmobiliarios»** que reciben los anuncios *«automáticamente»* | **No.** Lo social es un **botón de compartir**: *«Compartir propiedades (Whatsapp/Email/Redes Sociales)»* — presente en los tres planes `[V]` | **Plan Pro desde US$30/mes**, **+US$5/mes por usuario adicional** `[S]`. Plan Inicio: 1 usuario / 30 propiedades; Pro: 1 usuario / ilimitadas; Enterprise: 10 usuarios / ilimitadas `[V]` | [wasi.co/app-planes_precios.htm](https://wasi.co/app-planes_precios.htm) (estructura `[V]`; la página **no muestra importes**) · precio en [blog.wasi.co/precios-de-wasi](https://blog.wasi.co/precios-de-wasi/) `[S]` |
| **Vitrina Raíz** (CO) | CRM inmobiliario con tier gratuito | No verificado | Tiene plan gratis `[S]` | [vitrinaraiz.com/precios](https://vitrinaraiz.com/precios) |

> **Dos hechos duros de esta tabla, y son los que más pesan en todo el documento:**
>
> **(a) El orden de magnitud entre regímenes es de ~10×-20×.** Un CRM inmobiliario LATAM para **6-10 usuarios** cuesta MXN 3.499/mes (≈ **US$185/mes** a ~19 MXN/USD, conversión aproximada del autor `[H]`). Un asiento de BoldTrail en EE. UU. cuesta ~US$499/mes. **La agencia entera de cliente uno cabe en un tercio de un solo asiento estadounidense.**
>
> **(b) Ningún CRM inmobiliario LATAM inventariado tiene módulo social más allá de un botón de compartir.** `[V]` para Wasi (literal en su propia página de planes). El eje de producto de la categoría es **la ficha y su sindicación a portales**, no la conversación social. Esto es un hecho de la oferta; la lectura de si es hueco o desinterés no me corresponde (§4 aporta la evidencia de búsqueda, `opportunity` saca la conclusión).

### 1.3 Contenido social «hecho para ti» y schedulers verticalizados — régimen A

Esta es una categoría que **sí** existe específicamente para social en real estate — la de **precio bajo y compra individual**. Toda ella es estadounidense y toda ella es **producción de contenido, no escucha**.

> **Matiz añadido el 2026-07-30:** la primera redacción decía *«LA categoría que sí existe»*. Es inexacto desde que §1.1-bis entró al documento: **Lofty también es oferta social específica de real estate**, y mucho mayor. La diferencia no es la existencia sino el estrato — **§1.3 es el estrato barato vendido al agente ($29-74/mes); Lofty es el estrato de suite vendido al brokerage.** Ambos producen contenido; ninguno escucha.

| Herramienta | Qué hace | Precio | Fuente |
|---|---|---|---|
| **Coffee & Contracts** | Plantillas sociales *done-for-you*, captions pre-escritos, «Reel trends», lead magnets, newsletters, gráficas de promoción de ficha, flyers, planificador drag-and-drop | **$74/mes** o **$740/año** (plan Individual), prueba 7 días `[S]` | [todaytesting.com/coffee-and-contracts-promo-codes-and-review](https://todaytesting.com/coffee-and-contracts-promo-codes-and-review/) |
| **Agent Crate** | Equivalente más barato; su diferencial declarado frente a C&C es la **publicación automatizada** (los competidores «no ofrecen la conveniencia de publicación automatizada que Agent Crate provee») | Desde **$29/mes** ($24/mes anual) `[S]` | [theclose.com/agent-crate-review](https://theclose.com/agent-crate-review/) |
| **Lab Coat Agents Marketing Center** | Mismo espacio (plantillas/diseño) | No verificado en esta pasada | citado en [robinflow.com](https://www.robinflow.com/blog/agent-crate-vs-coffee-contracts-social-media-tools) `[S]` |

> **Lectura de categoría:** el precio de referencia de «social para agentes inmobiliarios» en EE. UU. es **US$29-74/mes**, y lo que se compra a ese precio es **material gráfico y programación**. Es un mercado de *supply de contenido*, no de inteligencia. **[A]** — vendido al agente individual, coherente con §5.3 fila 1 (decisor = pagador = usuario, autoservicio).

### 1.4 Listing-to-video (foto de ficha → reel) — régimen A, categoría saturada

Categoría muy poblada y de aparición reciente. Todas hacen esencialmente lo mismo: **fotos de la ficha → vídeo vertical con música y transiciones**.

| Herramienta | Qué hace | Fuente |
|---|---|---|
| **Reel-E** | Fotos → vídeo cinemático en <2 min; export a YouTube/Instagram/TikTok/**MLS** «con un clic» | [reel-e.ai](https://www.reel-e.ai/) |
| **BetterSpace** | Se le pega un **enlace de Zillow / Rightmove / web** y extrae las imágenes solo | [betterspace.ai/ai-real-estate-video](https://www.betterspace.ai/ai-real-estate-video) |
| **VideoTour.AI** | Captions por habitación auto-generados, música sincronizada a beat | [videotour.ai/real-estate-reel-maker](https://videotour.ai/real-estate-reel-maker) |
| **Stager AI** | Vertical para Reels + horizontal para MLS | [stagerai.com/ai-video-templates/ai-real-estate-video-generator](https://stagerai.com/ai-video-templates/ai-real-estate-video-generator) |
| **Luma AI** | Texto de ficha + fotos → vídeo cinemático | [lumalabs.ai/create/ai-video-generator-for-real-estate-listings](https://lumalabs.ai/create/ai-video-generator-for-real-estate-listings) |

> **Dos observaciones estructurales, no opinión:**
>
> **(a) Toda la categoría está enganchada al MLS o a un portal anglosajón.** Reel-E y Stager AI exportan **a MLS**; BetterSpace ingiere **enlaces de Zillow/Rightmove**. Por §5.1, en LATAM **no hay MLS** y esos portales no operan allí. La categoría **no es trasplantable tal cual** al comprador de Qualify sin un integrador de portal local (InfoCasas/Gallito/Fincaraíz/Metrocuadrado).
>
> **(b) El flujo de datos va en dirección contraria a Qualify.** Estas herramientas **producen** vídeo desde datos estructurados de la ficha. Qualify **lee** vídeo para extraer datos. No son competidores: ocupan el extremo opuesto de la misma tubería. Registrado como hecho del campo; la implicación es de otro eje.

### 1.5 Portales — el gasto que sí es obligatorio

| Portal | Mercado | Modelo | Precio publicado | Fuente |
|---|---|---|---|---|
| **InfoCasas** | UY (se declara «Portal Inmobiliario N° 1 de Uruguay»: +120.000 propiedades, **+700 inmobiliarias**, alcance declarado +900.000 personas) | Planes por inmobiliaria + planes sueltos para particulares | **US$92–196/mes** para inmobiliarias (hasta 4 planes) `[S]`. Particulares venta: **UYU 975–3.500** `[S]` | secundaria: [urufacil.uy/alquileres/infocasas](https://urufacil.uy/alquileres/infocasas/) · **la página oficial [infocasas.com.uy/soyinmobiliaria](https://www.infocasas.com.uy/soyinmobiliaria) NO publica precios** — remite a WhatsApp/teléfono comercial `[V]` |
| **Gallito** | UY | Portal clasificados histórico, sección inmuebles | No verificado en esta pasada | [gallito.com.uy/inmuebles](https://www.gallito.com.uy/inmuebles) |
| **MercadoLibre Inmuebles** | UY/AR/CO/MX | Clasificados masivos | No verificado | [listado.mercadolibre.com.uy](https://listado.mercadolibre.com.uy/el-gallito-inmuebles) |
| **Metrocuadrado** | CO | **Paquetes por publicación, no suscripción**: Plan X5 (5 inmuebles/90 días), X3 (3/90 días), Básico (1/90 días), Gratuito (solo fuera de Bogotá y Medellín, 30 días) | **Plan X3 = COP 140.600, pago único** `[S]` | [metrocuadrado.com/noticias/actualidad/nuevos-paquetes-de-publicacion-en-metrocuadrado-4729](https://www.metrocuadrado.com/noticias/actualidad/nuevos-paquetes-de-publicacion-en-metrocuadrado-4729) |
| **Fincaraíz** | CO | Portal líder por SEO | **Precios no localizados** en esta pasada — pendiente | [fincaraiz.com.co](https://www.fincaraiz.com.co/) |
| **Zillow Premier Agent** | EE. UU. **[A]** | Publicidad por ZIP, compra **individual del agente** | Ver §2 — es el gasto dominante del régimen A | ver §2 |

> **Hallazgo de método que conviene no perder:** en LATAM el precio inmobiliario está **sistemáticamente sales-gated**. InfoCasas remite a WhatsApp `[V]`; Tokko devuelve **403** a peticiones automatizadas `[V]`; Wasi publica la estructura de planes pero **no los importes** `[V]`. Las cifras LATAM de este documento son en su mayoría `[S]` **no por descuido, sino porque la fuente primaria no existe públicamente.** Cualquier agente que pida «verifica esto contra la página oficial» debe saber que la página oficial, deliberadamente, no lo dice.

### 1.6 Qué NO aparece en ningún inventario

Buscado y **no encontrado** en las categorías anteriores: cualquier herramienta inmobiliaria que **analice el contenido de un vídeo** (transcripción, audio, lo que se dice o se muestra) en vez de producirlo o programarlo. Se trata en §4 con la evidencia de búsqueda completa.

---

## 2. Techo de gasto observado

> **Sección escrita para resistir cross-examination.** `sales-consultant` cuestionará si este techo soporta lo que sus compradores dicen necesitar. Por eso: cada cifra lleva fuente y etiqueta, se dan **dos techos** (uno por régimen), y —lo más importante— se separa el **presupuesto de software** del **presupuesto de medios**, porque **son dos bolsillos distintos con dos órdenes de magnitud distintos** y confundirlos es la forma más fácil de sacar una conclusión falsa de esta sección.

### 2.0 La distinción que gobierna toda la sección: software ≠ medios

Una inmobiliaria tiene **dos líneas de gasto** que este documento no debe mezclar:

| Línea | Qué compra | Orden de magnitud observado (LATAM) | Naturaleza |
|---|---|---|---|
| **Software / SaaS** | CRM, herramientas | **US$25–185/mes** *(US$25 = Tokko Personal, 1 usuario; el techo de una inmobiliaria de ~5 asesores arranca en US$50 — ver §2.1)* | Recurrente, discrecional, se negocia a la baja |
| **Medios / exposición** | Planes de portal, Meta Ads, Google Ads | **US$92–2.500/mes** | Se percibe como **coste de operar**, no como software |

> **Nota de conciliación de cifras** (para que no se lean como contradicción): **US$25–185** es el rango de la categoría **completa**, del agente solo hasta la agencia de 10 usuarios. **US$50–185** es el rango de la empresa tipo de cliente uno (**~5 asesores**, §2.1), y es el que se cita en §2.4 y en las rondas adversariales. Distinta unidad de análisis, no distinto dato.

**Por qué importa para el cross-exam:** si `sales` encuentra que el comprador necesita algo, la pregunta decisiva no es *«¿cuánto está dispuesto a pagar?»* sino **«¿de qué línea sale?»**. Lo que se factura contra la línea de medios tolera **~10× más presupuesto** que lo que se factura contra la línea de software. Esta observación es un hecho del campo (las dos líneas existen con esas magnitudes, con fuente abajo); **la decisión de cómo posicionarse entre ellas no es mía**.

### 2.1 Régimen B — LATAM · **el techo que aplica al cliente uno**

Reconstrucción del gasto mensual de una inmobiliaria tipo (UY/CO, ~5 asesores):

| Concepto | Coste mensual | Etiqueta | Fuente |
|---|---|---|---|
| Plan de portal (InfoCasas, inmobiliarias, UY) | **US$92 – 196** | `[S]` | [urufacil.uy](https://urufacil.uy/alquileres/infocasas/) · oficial sales-gated |
| Paquetes de portal (Metrocuadrado, CO) | **COP 140.600 pago único** por 3 inmuebles/90 días (≈ US$33 ÷ 3 meses ≈ **US$11/mes**, conversión aprox. del autor a ~4.250 COP/USD `[H]`) | `[S]` | [metrocuadrado.com](https://www.metrocuadrado.com/noticias/actualidad/nuevos-paquetes-de-publicacion-en-metrocuadrado-4729) |
| CRM inmobiliario (Tokko, plan Equipo 3-5 usuarios) | **MXN 1.999** ≈ **US$105** (a ~19 MXN/USD `[H]`) | `[S]` | [comparasoftware.com](https://www.comparasoftware.com/tokko-broker) |
| CRM inmobiliario (Wasi Pro + 4 usuarios extra) | **US$30 + 4×US$5 = US$50** | `[S]` | [blog.wasi.co](https://blog.wasi.co/precios-de-wasi/) |
| Publicidad digital (Meta+Google) — inmobiliaria mediana, AR | **US$800 – 2.500** *más honorarios de agencia* | `[S]` **fuente interesada** (agencia de marketing que vende ese servicio) | [mktmarketingdigital.com](https://mktmarketingdigital.com/marketing-inmobiliario-argentina-guia-inmobiliarias/) |
| Coste por lead cualificado declarado en el sector, AR | **US$10 – 50** | `[S]` misma fuente interesada | ídem |

**EL TECHO, dicho sin ambigüedad:**

> **Línea de software de una inmobiliaria LATAM de ~5 asesores: US$50 – 185/mes por toda la empresa. Equivale a US$10 – 37 por asiento y mes.**
>
> **Línea de medios de la misma empresa: US$92 – 2.500/mes**, con la parte de portal (US$92–196) percibida como obligatoria.

**Cotas de esta afirmación, declaradas por adelantado para que el cross-exam no las descubra:**
1. Todas las cifras LATAM son `[S]`. **No por falta de rigor sino porque la fuente primaria no se publica** — InfoCasas remite a WhatsApp `[V]`, Tokko devuelve 403 `[V]`, Wasi omite importes en su propia tabla de planes `[V]` (§1.5).
2. El rango US$800-2.500 de publicidad viene de **una agencia que vende gestión de publicidad**, y es Argentina, no Uruguay. Es el dato más débil de la tabla. **No lo uso para sostener el techo de software**, solo para establecer que la línea de medios existe y es ~10× mayor.
3. No he localizado ninguna encuesta sectorial LATAM equivalente al NAR Member Profile. **Ese hueco es real** y cualquiera que necesite una cifra LATAM defendible al 100% no la va a encontrar en fuentes públicas.

### 2.2 Régimen A — EE. UU. · referencia, **NO** el presupuesto del cliente uno

| Concepto | Coste | Etiqueta | Fuente |
|---|---|---|---|
| **Gasto de negocio TOTAL, mediana del agente** | **$9.530/año** (2025), subiendo desde **$8.010** (2024). Mayor partida: **vehículo $1.580**; administración $870 | `[S]` sobre dato NAR | [nar.realtor — Income Steady, Even as Market Slows](https://www.nar.realtor/magazine/real-estate-news/sales-marketing/income-steady-even-as-market-slows-2025-member-trends) |
| Zillow Premier Agent, zona no-metro | **$300 – 500/mes** | `[S]` | [theclose.com/zillow-premier-agent-worth-cost](https://theclose.com/zillow-premier-agent-worth-cost/) |
| Zillow Premier Agent, zona metro | **$1.000+/mes** | `[S]` | ídem |
| Zillow Premier Agent, mercado muy competido (Orange County) | **$3.000 – 8.000/mes** | `[S]` | ídem |
| Coste por conexión declarado por la propia Zillow | **$223** (metro grande) / **$139** (no-metro) | `[S]` cita de cifra de Zillow | [primepixeldigital.com](https://primepixeldigital.com/blog/zillow-premier-agent-review) |
| CRM | **$69/asiento/mes** (Follow Up Boss) → **~$449–499/asiento/mes** (Lofty, BoldTrail) | `[S]` | §1.1 |
| Contenido social vertical | **$29 – 74/mes** | `[S]` | §1.3 |

### 2.3 El dato más accionable de todo mi eje

Los dos números de la tabla anterior que hay que poner uno al lado del otro:

- Gasto de negocio **total** de la **mediana** del agente estadounidense: **$9.530/año** ≈ **$794/mes**, **incluido el coche**.
- Precio de lista de la plataforma all-in-one más desplegada del sector (BoldTrail): **~$499/asiento/mes** ≈ **$5.988/año**.

> **Conclusión de campo: el precio de lista de la categoría premium consume el ~63 % del gasto de negocio anual de la mediana del agente, coche incluido. La mediana del mercado no puede comprar el producto de referencia de su propio mercado.**
>
> De donde se siguen dos correcciones a cómo suelen citarse estas cifras:
> 1. **Las cifras grandes de Zillow ($3.000-8.000/mes) NO son «lo que paga un agente inmobiliario».** Son el decil superior en mercados concretos. Multiplicadas por 12 dan $36.000-96.000/año, entre 4× y 10× el gasto total de la mediana. Citarlas como techo del nicho es un error de casi un orden de magnitud.
> 2. **Los precios sales-gated de §1.1 son consistentes con esto.** BoldTrail y Lofty no publican tarifa porque su precio de lista no resiste el contraste con el presupuesto del comprador mediano; se vende con descuento negociado a través del brokerage. La opacidad **es** el dato.

### 2.4 Resumen ejecutable del techo (la fila que citarán los otros dos ejes)

| Segmento | Software, por empresa/mes | Software, por asiento/mes | Medios, por empresa/mes |
|---|---|---|---|
| **Inmobiliaria LATAM ~5 asesores (cliente uno)** | **US$50 – 185** | **US$10 – 37** | US$92 – 2.500 |
| Agente individual EE. UU., **mediana** | — | ~$794/mes de gasto de negocio **total** (coche incluido) | incluido en esa cifra |
| Agente individual EE. UU., **decil superior** | $69 – 499 | $69 – 499 | $1.000 – 8.000 |

**Advertencia de uso obligatoria:** cualquier razonamiento de producto o precio para Qualify que cite la fila 2 o 3 como presupuesto de cliente uno **está midiendo el mercado equivocado** (§5.0). El techo de cliente uno es la fila 1.

### 2.5 Ronda adversarial ADV3 — ¿el techo paga R1+R2+R5? (2026-07-30)

Pregunta del lead, contra la cola de requisitos de `sales` (`docs/demanda-ventas-inmobiliario.md` §6). **Respuesta: PARCIAL — y la división no cae donde la pregunta supone.**

#### Corrección previa, y es la que resuelve ADV3

**Mi techo es un GASTO TOTAL, no un presupuesto incremental disponible.** Una inmobiliaria que gasta US$50–185/mes en software **ya se lo está gastando** — en Tokko o Wasi, más el portal. Qualify no recibe US$185 frescos: recibe **lo que consiga desplazar o añadir al margen**. La pregunta correcta no es *«¿cabe R1+R2+R5 bajo el techo?»* sino:

> **¿Qualify sustituye la línea de CRM que ya se paga, o se suma a ella?**
> - **Si sustituye:** los US$50–185/mes completos son direccionables. R1+R2+R5 caben.
> - **Si se suma:** el incremento realista es mucho menor, y **nada de mi investigación establece cuál es**. Es un hueco declarado, no una cifra que pueda inventar.

Y hay una asimetría de unidades que la pregunta también esconde: **el techo es recurrente y por cliente; el coste de construir es único y se amortiza entre N clientes.** El test correcto es `precio × N vs coste amortizado`, y **nadie en esta sesión ha estimado N**. Sin N, ninguna de las tres filas se puede declarar rentable ni ruinosa — solo se puede rankear.

#### Fila por fila, con el ancla de precio que aporta mi eje

| | Veredicto | Razón desde la oferta |
|---|---|---|
| **R2** — multi-cuenta, marca por agente, un solo operador | **SÍ, la más clara de las tres** | **Es la única con precio de mercado demostrado en régimen B.** Tokko Enterprise (6-10 usuarios) = MXN 3.499 ≈ **US$185/mes** (§1.2): el mercado LATAM **ya paga mi techo entero, exactamente, por gestión multi-usuario**. Además encaja con §5.3 (un decisor, N asesores) y con §1.2(b) (ningún CRM LATAM pasa del botón de compartir). `sales` lo estima **bajo-medio** de construir. Cosa barata, cosa con precio establecido, cosa alineada con cómo compra este comprador. **Y es precisamente la fila que permitiría SUSTITUIR en vez de sumar** — porque gestión multi-cuenta *es* lo que Tokko y Wasi venden. |
| **R5** — el ciclo de vida del listing gobierna el calendario | **NO — y no por coste, sino porque no es tarifable** | BoldTrail lo entregó **como corrección de bug** en sus notas de versión, no como producto. Es un requisito **de clase defecto**: su ausencia pierde tratos, su presencia no gana ninguno. **No se puede poner en una tarjeta de precios.** Coste medio con poder de fijación de precio cero es la peor ratio de la cola. *(Esto no dice «no lo construyas»; dice «no lo cuentes como justificación de ingreso».)* |
| **R1** — log auditable de aprobación | **DESCONOCIDO, y es el interesante** | No hay comparable de precio **porque nadie lo vende** — hallazgo del propio `sales`, coherente con mi §4.3 (nadie lo ofrece) y con mi §3.2 (**ninguna de mis 16 quejas textuales lo pide**), lo cual es exactamente el perfil de una necesidad latente: no se pide lo que no se ha visto. Los artefactos de cumplimiento **sí** sostienen precio premium en otras verticales, pero **no tengo comparable inmobiliario**. Y hay un condicionante que mata o salva la fila entera: **su ancla es la ley de fair housing estadounidense**, y por los propios avisos de `sales` en R0/R4 **puede no aplicar en Uruguay**. Su valor depende de una pregunta jurisdiccional que nadie ha respondido. |

#### Lo que esto significa, en una línea

**R2 sí; R5 no como línea de ingreso; R1 indeterminado por jurisdicción.** Y las tres caben bajo el techo **solo si Qualify desplaza la línea de CRM existente en vez de añadirse a ella** — siendo R2, justamente, el requisito que haría posible ese desplazamiento.

> **Frontera de eje:** aporto anclas de precio observadas y la corrección total-vs-incremental. **No decido qué se construye.** Que R2 encabece esta lectura desde la oferta no es una recomendación de roadmap: es una observación de que el mercado LATAM ya tiene un precio establecido para esa capacidad.

---

## 3. Quejas documentadas — citas textuales

> **Regla de esta sección:** todo entre comillas es **literal**, en el idioma original, con reseñador, fecha y plataforma cuando constan. Nada está parafraseado. Donde solo tengo paráfrasis de una fuente secundaria, lo digo y **no** lo pongo entre comillas.
>
> `sales-consultant` tiene prohibido inventarse un dolor; esta sección es parte de su materia prima. Por eso separo explícitamente **lo citable** de **lo meramente reportado**.

### 3.1 BoldTrail / kvCORE (Inside Real Estate) — la fuente más rica que encontré

Puntuación media **4,4/5 sobre 564 reseñas** en Software Advice `[V]` — es decir, **el producto no está mal valorado en agregado**; lo que sigue es la cola negativa, y es informativa precisamente porque convive con una nota alta.

**Software Advice** — [softwareadvice.com/crm/kvcore-profile](https://www.softwareadvice.com/crm/kvcore-profile/) · acceso 2026-07-29 `[V]`

| Reseñador | Fecha | ★ | Cita textual |
|---|---|---|---|
| Liana N. (autónoma) | ene 2026 | 2/5 | «**Don't do it - it is Kvcore disguised as BoldTrail and just as cumbersome to operate**» |
| Liana N. | ene 2026 | 2/5 | «**You do not get support. You call in and wait for up to an hour**» |
| Jarrett S. (2-10 empleados) | may 2026 | 2/5 | «**INCREDIBLY disappointed**» / «**It's very expensive and for this price it should be amazing**» |
| Jarrett S. | may 2026 | 2/5 | «**it will send over 100 properties at a time if there's that many**» |
| Gabi M. (51-200 empleados) | abr 2025 | 1/5 | «**The absolute worst company I have ever worked with**» |
| Gabi M. | abr 2025 | 1/5 | «**we paid over 200k in fees and had an ROI of zero**» |
| Gabi M. | abr 2025 | 1/5 | «**They renew your contract without notifying you and refuse to let you out**» |
| «VR» (2-10 empleados) | mar 2026 | 1/5 | «**I agreed to an expansion for leads...was charged twice what my contract states**» |
| «VR» | mar 2026 | 1/5 | «**customer service and management are a bit of a joke**» |

**Capterra** — citas recogidas vía [adamationai.com/blog/boldtrail-reviews-small-brokerage-2026](https://adamationai.com/blog/boldtrail-reviews-small-brokerage-2026) · acceso 2026-07-29 `[S]` *(secundaria: la cita es literal pero no la he verificado contra Capterra directamente)*

| Reseñador | Fecha | Cita textual |
|---|---|---|
| Sajida P. | jun 2024 | «**trying to find a phone number is impossible and my emails to support do unanswered**» *(sic)* |
| Joyce J. | 2024 | «**It takes forever to get things resolved. They don't seem to follow up.**» |
| Sara G. | ene 2026 | «**I was left in limbo and my cancellation request was denied**» |
| Jachelle S. | mar 2026 | «**many agents don't realize how much setup and optimization is required to unlock**» |
| Jessica G. | oct 2025 | «**has been unstable, glitchy, and poorly supported from the start**» |
| Joshua R. | ene 2026 | «**The mobile app is horrible**» |
| Shannon G. | feb 2025 | «**force everyone over to their new products or you can watch your business die**» |
| BBB (anónimo) | oct 2025 | «**mis-lead to actually sign a contract with Inside Real Estate even though I was told I was signing up for Boomtown**» |

**Reportado, NO citable** (paráfrasis de fuente secundaria, sin cita literal disponible): Inside Real Estate acumula **90 reclamaciones en el BBB en tres años**, varias describiendo cláusulas de auto-renovación que bloquearon la cancelación por no avisar dentro de una ventana estrecha un año antes `[S]` — [adamationai.com](https://adamationai.com/blog/boldtrail-reviews-small-brokerage-2026).

### 3.2 Lectura del patrón (agrupación, no interpretación prospectiva)

Las quejas de §3.1 caen en **cuatro cubos**, y conviene notar cuál domina:

| Cubo | Nº de citas | Ejemplos |
|---|---|---|
| **Contrato / facturación / cancelación** | 5 | auto-renovación, cargo doble, cancelación denegada, contrato con la empresa equivocada |
| **Soporte** | 4 | una hora al teléfono, emails sin responder, «forever to get things resolved» |
| **Precio vs. valor** | 3 | «$200k en fees y ROI cero», «very expensive and for this price it should be amazing» |
| **Producto (bugs/UX/carga de setup)** | 4 | «unstable, glitchy», app móvil, 100 propiedades de golpe, setup no asumido por nadie |

> **Observación de campo, sin conclusión de producto:** el cubo más poblado **no es de funcionalidad, es comercial** (contrato/facturación/cancelación). Es decir: en la categoría más cara del régimen A, **la queja modal del comprador no es «le falta una feature» sino «me han atado»**. Registro esto porque contradice el reflejo natural de leer una lista de quejas como un backlog de features. Qué hacer con ello no es mi eje.

### 3.3 Zillow Premier Agent — parcialmente bloqueado, lo digo en vez de rellenarlo

**No conseguí citas textuales.** G2 devolvió **HTTP 403** a la consulta automatizada `[V]`, y el review de The Close, al inspeccionarlo, **no contiene testimonios verbatim** — solo la valoración editorial propia del medio `[V]`.

Lo que sí tengo, todo `[S]` y sin comillas por no ser literal:
- Puntuación **2,2/5 en G2** `[S]` (citada por búsqueda, no verificada en la propia G2 por el bloqueo).
- The Close le asigna **«Customer Rating: 3.0 / 5»** — métrica editorial propia, **no** de una plataforma de reseñas `[V]`.
- Contras que la publicación enumera por su cuenta (paráfrasis, no queja de usuario): falta de transparencia de precio, coste fijo con independencia del volumen de leads, soporte débil, CRM básico `[V]` — [theclose.com/zillow-premier-agent-worth-cost](https://theclose.com/zillow-premier-agent-worth-cost/).

**Hueco declarado:** la queja de mayor valor del régimen A —la del agente que paga $1.000-8.000/mes por leads— **es exactamente la que no pude documentar textualmente**. Quien quiera cerrarlo necesita acceso a G2/Reddit desde un cliente no bloqueado.

### 3.4 Mundo hispanohablante — poco material, y el que hay apunta a un solo dolor

**Cita textual** — [inmogesco.com/blog/problemas-de-los-agentes-inmobiliarios-con-la-captacion-de-leads](https://inmogesco.com/blog/problemas-de-los-agentes-inmobiliarios-con-la-captacion-de-leads/) · acceso 2026-07-29 `[S]` *(blog de un proveedor de software inmobiliario — **fuente interesada**, describe el dolor que su producto vende resolver)*

> «**No todos los leads generados son igual de valiosos. Muchos agentes se encuentran con contactos que no tienen intención real de comprar o invertir, lo que lleva a una pérdida de tiempo y recursos.**»

> «**Las pequeñas empresas o agentes independientes a menudo tienen recursos limitados, tanto en términos de presupuesto como de personal, lo que dificulta la implementación de estrategias de captación de leads eficaces.**»

**Tokko Broker** — [comparasoftware.com/tokko-broker](https://www.comparasoftware.com/tokko-broker) · acceso 2026-07-29 `[S]`. Media **3,5/5 sobre solo 2 reseñas** (muestra irrelevante estadísticamente, se registra por ser lo único que hay):

| Reseñador | ★ | Cita textual |
|---|---|---|
| Herbert Suiney (Suiney Realty) | 2/5 | «**Mala experiencia, no recomendado**» — desventaja principal citada: entrega de información del cliente |
| Miguel Aranda | 5/5 | «**Una herramienta efectiva y accesible para diferentes presupuestos**» · «**interfaz amigable e intuitivo**» |

**Reportado, NO citable** (paráfrasis de secundarias, varias de ellas interesadas): que los portales cobran cuotas mensuales a cambio de leads de baja calidad; que muchas agencias reciben gran cantidad de consultas pero pocas convierten en visita; que **varias agencias publican la misma propiedad, de modo que un mismo comprador deja sus datos en decenas de formularios para el mismo inmueble** `[S]`; y que la OCU, comparando 8 portales, **pudo publicar un anuncio falso en todos ellos** `[S]` — [ocu.org](https://www.ocu.org/vivienda-y-energia/comprar-vender-alquilar/informe/portales-inmobiliarios-online).

> **Asimetría de evidencia que hay que declarar, no disimular.** El régimen A (EE. UU.) tiene reseñas firmadas, fechadas y con estrellas; el régimen B (LATAM) **casi no tiene corpus público de reseñas de software inmobiliario**. Tokko, el «CRM #1 de América Latina» por su propia descripción, tiene **dos** reseñas en el comparador donde lo encontré. **Esto significa que el dolor del comprador de cliente uno NO está documentado públicamente**, y que cualquier afirmación fuerte sobre él tendrá que venir de entrevista directa —lo cual es terreno de `sales-consultant`, no mío. Yo puedo decir con confianza qué duele en EE. UU.; **no puedo decirlo de Uruguay a partir de fuentes públicas, y no lo voy a fingir.**

---

## 4. ¿Alguien ofrece hoy listening sobre contenido primario al nicho inmobiliario?

> **Definición operativa, fijada antes de buscar** (para que la respuesta no dependa de mover la portería). «**Listening sobre contenido primario**» = el sistema **abre el vídeo**: transcribe el audio, analiza los fotogramas, y razona sobre **lo que se dice y se muestra**. **NO** cuenta como contenido primario: keywords, hashtags, geotags, el caption, los comentarios de texto, ni métricas de engagement. Esa es la distinción de la tesis de Qualify (`README.md`, `CLAUDE.md`: *«leer el contenido, no el perfil»*) y es la que se somete a prueba aquí.

### 4.1 RESPUESTA

> ## **NO. Nadie ofrece listening sobre contenido primario al nicho inmobiliario.**
>
> Más preciso, en tres afirmaciones separables, porque cada una se puede falsar por su cuenta:
>
> 1. **Existe listening vertical inmobiliario, y es 100 % texto/keywords.** `[V]`
> 2. **Existe análisis de vídeo de formato corto horizontal, y es 99 % metadatos, no contenido.** `[V]`
> 3. **La intersección — vídeo analizado por contenido, verticalizado a real estate — está vacía en todo lo que pude buscar.** `[V]` en cuanto a «no encontrado»; **necesariamente `[H]` en cuanto a «no existe»**, porque una búsqueda no prueba una negativa universal.
>
> **La ausencia se afirma explícitamente. No queda implícita por omisión.**
>
> **PERO — y esto NO es un campo desierto (revisión 2026-07-30).** Dos matices que cambian la lectura y que no estaban en la primera versión:
> - **Hay un incumbente bien financiado construyendo justo al lado.** Lofty lanzó en feb-2026 *«the first agentic AI operating system for real estate»* y lo expandió el **2026-07-28**, un día antes de esta investigación (§1.1-bis). Ocupa **la misma categoría declarada que Qualify** sin ocupar la misma capacidad: verificado contra su comunicado, **todos sus agentes operan sobre datos de primera parte** y ninguno lee contenido de terceros `[V]`. «Nadie hace listening de contenido primario» es cierto; «el campo está libre» **no lo es**.
> - **El «nadie» no es igual en los dos regímenes.** En EE. UU. existe la categoría vertical y le falta la capacidad; en LATAM **no existe ni la categoría** (§4.6). Eso profundiza la ausencia y **a la vez** la vuelve más ambigua de interpretar.

### 4.2 Qué busqué (traza auditable)

Consultas ejecutadas el **2026-07-29**, literales:

| # | Consulta | Qué devolvió |
|---|---|---|
| 1 | `real estate social listening tool monitor competitor agents Instagram TikTok video content analysis` | Herramientas horizontales (Virlo, Exolyt, Pentos, Socialinsider) + Hootsuite/Talkwalker con página vertical de real estate. **Ninguna vertical con análisis de contenido** |
| 2 | `real estate video transcript analysis AI listen what agents say reels audio proptech` | **Todo generadores de vídeo** (Reel-E, VideoTour.AI, AutoReel), TTS (ElevenLabs), scripts con IA. **Cero analizadores** |
| 3 | `"real estate" brokerage social listening reputation monitoring platform vertical brand mentions tool` | Birdeye, Sked, Hootsuite, BizAI, Pipeline ROI — **todos keyword/texto** |
| 4 | (§1.4) `listing to video generator real estate AI automatically create reels from listing pricing` | Confirma que el vector IA+vídeo del nicho es **producción**, no lectura |
| 5 | **(añadida 2026-07-30, en español)** `escucha social inmobiliaria herramienta monitoreo redes sociales agentes inmobiliarios España LATAM análisis video` | **Cero productos.** Solo blogs de consejo que remiten a **Buffer y Hootsuite**. Ver §4.6 |
| 6 | **(añadida 2026-07-30)** `Lofty Social Agent Social Studio Lofty Blast Cowork launch 2026 real estate AI` | El incumbente agéntico. Verificado: **first-party, no lee contenido de terceros** (§1.1-bis) |

Además, inspección directa de **cinco** páginas candidatas (las que más se parecían a un contraejemplo), incluidos los dos comunicados de Lofty.

### 4.3 Capa por capa: qué sí existe

**Capa 1 — Listening horizontal clásico (texto).** Brandwatch, Brand24, Mention, Sprout Social, Hootsuite Listening (powered by Talkwalker). Ya documentado en `docs/alternativas-fase1.md` §2d: *«Brandwatch y Brand24 son texto-céntricos»*. Sin cambios.

**Capa 2 — «Short-form video intelligence» horizontal.** Aquí está la sorpresa útil: **la categoría que suena a contenido primario, no lo es.** Del propio artículo comparativo de Vellum — [vellum.ai/blog/best-short-form-video-intelligence-tools](https://www.vellum.ai/blog/best-short-form-video-intelligence-tools) · acceso 2026-07-29 `[V]`:

| Herramienta | Qué analiza **de verdad** | Precio | ¿Vertical inmobiliaria? |
|---|---|---|---|
| **Virlo** | Metadatos / búsqueda por keywords | **$49–199/mes** | No |
| **Exolyt** | Metadatos + sentimiento | **$400–950/mes** | No |
| **Kalodata** | Metadatos (enfoque e-commerce) | Privado | No |
| **Socialinsider** | Metadatos multiplataforma | **$82–199/mes** | No |
| **Pentos** | Análisis de música/sonidos *(lo más cercano al audio, pero es identificación de pista, no habla)* | Privado | No |
| **Shortimize** | Metadatos básicos | Privado | No |
| **Sprout Social** | Metadatos + escucha social | **$249+/asiento/mes** | No |

> Conclusión del propio comparativo, no mía: *«Todas parecen enfocarse en búsquedas por keywords, monitoreo de nicho, análisis de sentimiento basado en metadatos, hashtags y engagement»*, y **ninguna** está verticalizada para real estate — las verticales que cubre la categoría son **música, e-commerce (TikTok Shop), IA/productividad** `[V]`.

**Capa 3 — Listening vendido *específicamente* a inmobiliarias.** Existe, y es donde había que apretar. Los tres contraejemplos más fuertes, inspeccionados uno a uno:

| Candidato | Cómo se vende | Qué analiza **realmente** (verificado) | ¿Contenido primario? |
|---|---|---|---|
| **BizAI** — *«AI Social Listening for Real Estate Brokerages»* — [bizaigpt.com](https://bizaigpt.com/blog/ai-social-listening-for-real-estate-brokerages) | Detecta señales de alta intención («moving to [City]», «selling my home») | Fuentes literales: *«Facebook (groups/pages), Twitter/X (hashtags/geotags), Instagram (stories/posts), LinkedIn (professional moves), plus forums like Nextdoor, Reddit r/[City]RealEstate, BiggerPockets»*. Inspección: **«No hay mención» de análisis de vídeo, audio, transcripción ni fotogramas.** La única aparición de «listing video» es en contexto de campañas, no de algo que el sistema analice | **NO** `[V]` |
| **Pipeline ROI** — *«3 best social listening tools for monitoring your real estate business»* — [pipelineroi.com](https://www.pipelineroi.com/blog/the-3-best-social-listening-tools-for-monitoring-your-real-estate-business/) | Guía vertical inmobiliaria | Recomienda **Mention** (*«scours the web for whatever keyword alert you create»*), **Buffer** (curación/programación) y **Hootsuite** (*«keyword mentions… by setting up 'Streams'»*). Las tres por keyword. **«No hay referencia alguna a análisis de contenido multimedia»** | **NO** `[V]` |
| **Birdeye / Sked / Hootsuite (páginas verticales real estate)** | Birdeye: *«track brand mentions and specific keywords»*. Sked: *«reveal which home features create the most buzz»* | Birdeye es **gestión de reputación** (reseñas + menciones de texto). Sked y Hootsuite son **gestión/programación social** con listening por keyword encima. Ninguno abre el vídeo | **NO** `[S]` |

### 4.4 Lo más cerca que llega el mercado, en dos direcciones distintas

Registro los dos «casi», porque son la munición honesta del contraargumento:

1. **Análisis de contenido de vídeo real, pero horizontal y sin vertical inmobiliaria.** **Twelve Labs** (búsqueda semántica y embeddings sobre vídeo) ya está documentado en `docs/alternativas-fase1.md` §2c como *«la alternativa ya desarrollada más completa»*. Y la categoría genérica existe: *«Video Analytics combines keyframe analysis with speech-to-text transcription for platforms like YouTube, TikTok, and Instagram, allowing for a searchable archive of video content»* `[S]`. **Existe la capacidad; no existe el producto inmobiliario montado sobre ella.**
2. **Transcripción vendida a inmobiliarias, pero de la conversación propia, no de la escucha del mercado.** **Infinityy**: *«Agents can receive a transcript of what a consumer asked, allowing them to follow up with context»* `[S]`. Es transcripción de **la interacción del comprador con el agente en la propia plataforma** — first-party, no listening de medios ajenos. **Es la categoría contigua más cercana que encontré, y no es lo mismo.**

### 4.5 Preparación explícita para el cross-exam de `opportunity`

`market-opportunity-analyst` va a preguntar si esto es **whitespace** o **evidencia de que el nicho no lo quiere**. Delimito lo que mi eje puede y no puede sostener, para que la discusión no se pierda:

**Lo que mi evidencia SÍ sostiene** (y defiendo):
- La ausencia es **real y no un artefacto de búsqueda superficial**: busqué por **seis** ángulos (§4.2), inspeccioné **cinco** páginas candidatas una a una, y los tres contraejemplos vertical-inmobiliarios más fuertes resultaron ser keyword/texto **por su propia descripción**, no por interpretación mía.
- La ausencia **no se debe a falta de tecnología**: la capacidad existe y está comprable hoy (capa 2 + Twelve Labs).
- La ausencia **no se debe a que el nicho rechace el vídeo**: el nicho está invirtiendo fuerte en vídeo, pero **todo en el lado de producción** (§1.4, categoría saturada; Zillow reporta *«listings with video receive over 160% more inquiries»* `[S]`).

> ⚠ **RETRACTACIÓN PARCIAL (2026-07-30) — leer §4.8(a) antes de citar el punto anterior.** La primera versión de esta viñeta remataba con *«el nicho ama el vídeo y solo lo emite; nadie lo escucha»*. **Retiro la fuerza retórica de esa frase, que escribí yo.** El gasto en producción demuestra demanda de **vídeo como canal de difusión**, no demanda de **leer vídeo ajeno** — son *jobs* distintos. Lo único que §1.4 sostiene legítimamente es que **el nicho paga por IA aplicada a vídeo**, lo cual descarta «tecnofobia» como explicación de la ausencia y nada más. La frase se conserva aquí tachada, y no borrada, porque circuló en la ronda ADV1 y el acta debe poder rastrearla.

**Lo que mi evidencia NO sostiene** (y no voy a defender):
- **No puedo probar que no exista.** Una búsqueda no demuestra una negativa universal. Afirmación 3 de §4.1 queda `[H]`.
- **No puedo distinguir «hueco» de «cementerio».** Si alguien lo intentó y murió sin dejar huella indexable, mi método no lo ve. **No busqué startups muertas ni rondas de financiación** — eso es literalmente el eje de `opportunity` (su tarea O5, señales de innovación/funding), no el mío.
- **No tengo ninguna evidencia de demanda.** Cero. Que nadie lo ofrezca no dice nada sobre si alguien lo compraría. Esa pregunta es de `sales-consultant`, y **§3.4 documenta que el dolor del comprador LATAM no está en fuentes públicas** — con lo cual `sales` tendrá que obtenerlo por entrevista, no de mí.

**Falsadores concretos de mi «nadie»** — lo que bastaría para tumbar esta sección, dicho por adelantado:
1. Un producto vertical inmobiliario cuya doc/marketing mencione **transcripción de audio o análisis de fotogramas** sobre contenido de terceros (no sobre la propia ficha ni sobre la propia llamada).
2. Un módulo real estate de Talkwalker/Brandwatch con análisis de vídeo real — **no lo verifiqué contra su documentación de producto**, solo contra la página vertical de Hootsuite. **Es el hueco más plausible de mi búsqueda** y quien quiera romper §4 debería empezar por ahí.
3. Un portal (Zillow, InfoCasas, Idealista) que analice el vídeo de las fichas de su propio inventario. No lo busqué.

### 4.6 ¿El «nadie» es el mismo en EE. UU. que en UY/CO? (añadido 2026-07-30)

> Pregunta planteada por el lead tras el split de dos techos de §2: *un «nadie ofrece listening real» estadounidense y uno uruguayo podrían diferir*. **Es una objeción correcta y mi §4 original no la cubría** — 4 de mis 5 consultas eran en inglés y orientadas a EE. UU. Ejecuté una búsqueda en español (consulta 5) para cerrarla.

**Resultado: la ausencia es MÁS profunda en LATAM/España, no menos.** Los dos regímenes fallan en escalones distintos:

| | **Régimen A — EE. UU.** | **Régimen B — LATAM/España** |
|---|---|---|
| ¿Hay producto de listening **verticalizado** a inmobiliaria? | **Sí** — BizAI, Pipeline ROI, Birdeye, Sked, páginas verticales de Hootsuite | **No encontré ninguno** `[V]` |
| ¿Qué se le recomienda al agente? | Un producto vertical (basado en keywords) | **Herramientas horizontales genéricas**: la literatura en español remite a **Buffer y Hootsuite**, y define el social listening conceptualmente sin nombrar ningún producto del sector `[V]` |
| ¿Alguien analiza contenido primario? | No | No |
| Escalón donde falla | Existe la categoría, le falta la capacidad | **Ni siquiera existe la categoría verticalizada** |

Evidencia de la fila 2: la literatura hispanohablante sobre «escucha social inmobiliaria» ([blog.wasi.co](https://blog.wasi.co/tendencias-en-redes-sociales-para-ventas-inmobiliarias/), [inmogesco.com](https://inmogesco.com/blog/redes-sociales-para-inmobiliarias/), [clinmoo.com](https://clinmoo.com/redes-sociales-para-agentes-inmobiliarios/), [adaix.es](https://adaix.es/las-mejores-redes-sociales-para-inmobiliarias-en-2025/)) **define el concepto** —*«el monitoreo y análisis de las conversaciones y menciones en las redes sociales sobre tu marca»*— y a la hora de nombrar herramientas cita *«plataformas como Buffer o Hootsuite»*, es decir **programación y analítica de publicaciones propias**, no escucha. Acceso 2026-07-29/30.

> **Consecuencia para el cross-exam, y corta en las dos direcciones — la registro entera:**
> - **A favor del hueco:** en LATAM ni siquiera hay una categoría vertical que llenar; nadie ha intentado el escalón anterior.
> - **En contra del hueco:** *«nadie ha intentado siquiera lo fácil»* es una lectura tan compatible con **mercado inmaduro/no dispuesto a pagar** como con **whitespace**. Y encaja incómodamente bien con mi §2: el techo de software LATAM es **US$50–185/mes por empresa**, por debajo del precio de una sola licencia de Exolyt ($400–950/mes) o Sprout ($249+/asiento). **Puede que en LATAM no haya listening vertical simplemente porque a ese techo no cabe.** No puedo distinguir las dos hipótesis con datos de oferta; hace falta el eje de demanda.

### 4.7 Frontera de capacidad — qué NO tiene Qualify hoy (añadido 2026-07-30)

> Incorporado tras el hallazgo de `opportunity` (`docs/oportunidades-mercado-inmobiliario.md` §1, verificado contra filesystem). **Es una advertencia de uso de mi propio documento**, y el lead pidió explícitamente que la hiciera.

Nada de §4 debe leerse como que Qualify **ya tiene** una capacidad de listening siempre-activa con la que competir contra los productos de §4.3. **No la tiene.** Según la due-diligence de `opportunity` contra el filesystem:

- **No existe orquestación (Celery/scheduler).** La restricción vinculante no es analítica sino de orquestación: **hoy no hay producto de monitorización continua, solo algo que una persona lanza a mano.** Para cualquier fila de mis tablas que implique vigilancia desatendida, la respuesta honesta sobre Qualify es **«todavía no, y no parcialmente: cero orquestación»**.
- **La cascada multimodal —el activo diferenciado— tiene todos sus tests marcados `integration`**, o sea que **no se ejecuta en CI ninguna vez**.

**¿Alguno de mis hallazgos de §1-§3 asumió lo contrario?** Los revisé: **no.** §1 inventaría oferta de terceros, §2 son precios de terceros, §3 son quejas sobre terceros — ninguna sección afirma ni presupone capacidad de Qualify. **El riesgo estaba concentrado en el tono de §4**, que podía leerse como «hueco listo para ocupar». Queda acotado aquí y en §1.1-bis.

> **Frontera de eje, respetada a propósito:** no escribo aquí si esto es una oportunidad. Documento que **el campo está vacío en esa intersección, con la traza de búsqueda para que se pueda auditar y refutar.** La conclusión prospectiva la escribe `opportunity` en `docs/oportunidades-mercado-inmobiliario.md`.

### 4.8 Ronda adversarial ADV1 — mi posición, para el acta (2026-07-30)

`market-opportunity-analyst` declara que **no** tratará §4 como whitespace: la ausencia de oferta es al menos tan compatible con ausencia de demanda como con oportunidad abierta, y por eso construye un experimento de tasa base para distinguirlas. El lead me pregunta si eso es la cautela correcta o si algo en mis §1-§4 inclina la balanza.

**Veredicto: la cautela de `opportunity` está justificada, y voy más lejos que ellos — tres cosas de mi propio material inclinan LEVEMENTE EN CONTRA del whitespace.** Defender mi hallazgo como oportunidad sería exactamente el exceso que mi rol prohíbe.

**(a) El argumento aparentemente más fuerte a favor del whitespace es débil, y soy yo quien lo introdujo.** Escribí en §4.5 que *«el nicho ama el vídeo y solo lo emite; nadie lo escucha»*, apoyado en la categoría saturada de §1.4. **Ese argumento no prueba lo que parece.** El gasto en producción demuestra demanda de **vídeo como canal de difusión**, no demanda de **leer vídeo ajeno**. Son *jobs* distintos: el agente publica un reel para captar; nada en esa conducta implica que quiera saber qué dicen los reels de otros. Lo único que §1.4 sí establece —y no es nada— es que **el nicho paga por IA aplicada a vídeo**, lo cual elimina «tecnofobia» como explicación de la ausencia. Nada más.

**(b) Mi corpus de quejas (§3) NO contiene ni una sola queja con forma de listening.** Revisadas las 16 citas textuales una a una: cero menciones de *«no sé qué se dice de mí»*, *«no sé qué hace mi competencia»*, *«no encuentro leads en el vídeo»*. El 100 % se reparte entre relación comercial (contrato/facturación/cancelación) y fiabilidad de producto. **El dolor mejor documentado del nicho no es informacional.**
> **Contra-matiz metodológico que me obliga a no sobreleer (b):** un corpus de reseñas de CRM es **el instrumento equivocado** para detectar demanda latente. La gente se queja de productos que compró; nadie se queja de la ausencia de una categoría que nunca ha visto. Así que (b) es evidencia **débil** en contra, no fuerte. Pero es lo que hay, y apunta en contra, no a favor.

**(c) Existe una explicación económica SUFICIENTE de la ausencia en LATAM que no necesita invocar la demanda en absoluto.** Techo de software LATAM: **US$50–185/mes por empresa** (§2.4). Precio de una sola licencia de listening horizontal: Exolyt **$400–950/mes**, Sprout **$249+/asiento** (§4.3). Si la estructura de coste del listening de contenido (scraping + inferencia) no baja de ese techo, **la ausencia en LATAM queda explicada sin referencia alguna a lo que el comprador quiera**. Regla epistémica: cuando existe una explicación alternativa suficiente, la inferencia a whitespace es injustificada.

**(c-bis) Hay una SEGUNDA explicación suficiente, y no la encontré yo — hallazgo de `opportunity` (T-6), incorporado 2026-07-30.** Uruguay tiene protección de datos de grado GDPR: **Ley 18.331**, decisión de adecuación de la UE reaffirmada el **2024-01-15**, y primer estado de América en ratificar el **Convenio 108+**. El producto de Qualify lee vídeo, audio y comentarios de personas que **no son clientes del tenant y no han consentido nada**. `[S]`, y con **descargo explícito de no-abogado** — es la etiqueta que le puso su autor y la respeto.

> **Por qué lo registro en mi eje aunque no sea mío:** convierte §4.8(c) en un par. Ahora hay **dos** explicaciones suficientes de la ausencia en LATAM que **no necesitan invocar la demanda en absoluto** — *no cabe bajo el techo de precio* (c) y *procesar ese contenido sale legalmente caro* (c-bis). Dos explicaciones suficientes e independientes debilitan la inferencia a whitespace **más que el doble** que una: ya no basta con refutar el argumento del techo.
>
> **Y una autocrítica que corresponde a mi eje, no al suyo:** el coste regulatorio es un determinante de **oferta** — es una razón por la que un vendor no construye. Que lo haya encontrado el eje de oportunidad y no yo es un **hueco de mi método**: busqué productos, precios y quejas, y **no busqué en ningún momento el régimen legal que condiciona si un producto puede existir**. Queda anotado para quien retome este documento.

**(d) Lofty es evidencia débil en contra, y es mía porque yo la verifiqué.** Un incumbente bien financiado, con conocimiento de dominio, reconstruyó su plataforma *«from the ground up around AI»* en 2026 y **eligió no construir lectura de contenido de terceros** (§1.1-bis): Social Agent produce, Homeowner Agent explota la base propia, Cowork prioriza tareas propias. Su juicio de producto revelado es que **el valor está en primera parte**. No es dispositivo —los incumbentes se equivocan, ése es el dilema del innovador entero— pero es señal real y apunta en contra.

#### Lo único que sí aporto a favor, y que estrecha la pregunta de verdad

**En el régimen A existe y se vende listening verticalizado a inmobiliarias** (BizAI, Pipeline ROI, Birdeye, Sked — §4.3, capa 3). Es decir: **el nicho SÍ compra «listening». Lo que compra es la variante keyword/texto.** Por tanto la pregunta abierta **no** es la genérica «¿quiere este nicho escuchar?» —que tiene respuesta afirmativa demostrada por revealed preference en A— sino la mucho más estrecha:

> **¿Pagaría este comprador un delta por listening de grado-contenido sobre el listening de grado-keyword que ya compra?**

Eso es una pregunta **testable, acotada y con un comparable de precio existente**, y es mejor terreno que «whitespace sí/no». Se la entrego a `sales` y a `opportunity` como reformulación, no como respuesta: **yo no tengo ninguna evidencia de demanda y no la voy a fabricar.**

#### Advertencia sobre el experimento de tasa base de `opportunity`

Su experimento se diseña explícitamente *«sin preguntar a nadie»*. Dos límites que mi eje puede señalar y su eje no verá:
1. **§3.4: no existe corpus público de reseñas del comprador LATAM.** Tokko, autodeclarado «CRM #1 de América Latina», tiene **dos** reseñas. Cualquier experimento de tasa base sobre datos públicos está, de hecho, **midiendo el régimen A**.
2. **Por §5.0, generalizar del régimen A al comprador de UY es un error de categoría.** Si el experimento corre sobre datos estadounidenses y la conclusión se aplica a cliente uno, hereda exactamente el defecto que este documento existe para corregir.

**Resultado para el acta: acuerdo, no disputa** — con la puntualización de que la balanza, con mi material sobre la mesa, se inclina algo más en contra del whitespace de lo que `opportunity` necesita para su posición.

---

## Cierre — hechos del campo, sin recomendación

Los **ocho** que sobreviven a esta pasada (5 de la primera redacción + 3 de las revisiones y rondas adversariales del 2026-07-30), con su etiqueta:

1. **El comprador de Qualify es LATAM (UY/CO), no EE. UU.**, mientras que la oferta y el pricing inventariables son casi todos estadounidenses. `[V]` desde el repo. **Es la corrección más importante del documento** (§5.0).
2. **Techo de software del cliente uno: US$50–185/mes por empresa (~US$10–37/asiento).** La línea de medios es ~10× mayor y se percibe como coste de operar. `[S]` en las cifras, por sales-gating sistemático de la fuente primaria (§2.1, §2.4).
3. **El precio de lista de la plataforma de referencia del régimen A (~$499/asiento/mes) consume el ~63 % del gasto de negocio anual TOTAL de la mediana del agente estadounidense ($9.530/año, coche incluido).** La mediana del mercado no puede comprar el producto de referencia de su mercado. `[S]` sobre dato NAR (§2.3).
4. **La queja modal en la categoría cara del régimen A es comercial (contrato/facturación/cancelación), no funcional.** 5 de 16 citas textuales, por encima de soporte (4), producto (4) y precio/valor (3) (§3.2). **Y no hay corpus público de quejas del comprador LATAM** (§3.4) — hueco que solo cierra una entrevista.
5. **Nadie ofrece listening sobre contenido primario al nicho inmobiliario.** El listening vertical que existe es texto/keywords `[V]`; el análisis de vídeo horizontal es metadatos, no contenido `[V]`; la intersección está vacía `[H]` en cuanto a inexistencia. El nicho invierte fuerte en vídeo, **pero enteramente en producirlo** (§4).
6. **Pero el campo no está desierto: Lofty lanzó un «agentic AI operating system for real estate» (feb-2026, expandido 2026-07-28)** que ocupa la categoría declarada de Qualify sin ocupar su capacidad — **todo primera parte, nada de contenido de terceros**, verificado contra el comunicado `[V]` (§1.1-bis).
7. **El «nadie» es más profundo en LATAM y por eso más ambiguo:** en EE. UU. existe la categoría vertical y le falta capacidad; en LATAM **no existe ni la categoría** — la literatura en español remite a Buffer y Hootsuite `[V]`. Compatible con whitespace **y** con explicaciones que no invocan la demanda (§4.6, §4.8). **Con datos de oferta no puedo distinguirlas.**
8. **Existen DOS explicaciones suficientes e independientes de la ausencia en LATAM que no mencionan la demanda:** (i) **no cabe bajo el techo** — US$50–185/mes por empresa frente a Exolyt $400–950/mes o Sprout $249+/asiento `[S]`; (ii) **procesar contenido de terceros sale legalmente caro** — Uruguay tiene protección de datos de grado GDPR (Ley 18.331, adecuación UE reaffirmada 2024-01-15, Convenio 108+) y el producto lee a personas que no consintieron `[S]`, hallazgo de `opportunity` (T-6), con descargo de no-abogado. **Dos explicaciones suficientes hacen la inferencia a whitespace bastante más débil que una** (§4.8 c y c-bis).

> **Advertencia de capacidad (§4.7):** nada de este documento implica que Qualify tenga hoy listening siempre-activo. **No hay orquestación (cero Celery/scheduler)**, luego no hay producto de monitorización continua, solo ejecución manual. Revisé §1-§3 y ninguna sección presuponía lo contrario.
