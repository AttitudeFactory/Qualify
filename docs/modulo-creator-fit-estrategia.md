# Módulo Creator Fit — estrategia híbrida (compra el pool, construye el fit)

**Fecha:** 2026-08-10 · **Autor:** sesión con el fundador · **Estado:** estrategia propuesta. **Frontera dictaminada por el arquitecto 2026-08-10** (§«Dictamen del arquitecto», al final): no es un módulo sino una oferta compuesta; la decisión queda registrada en **ADR 33 `[APROBADO]`** (`docs/arquitectura.md` §6), **firmado por el fundador el 2026-08-10** con la aclaración que elimina E3 (outreach = demanda del tenant por intención de compra, no contacto con creadores). Este doc sigue sin ser un ADR.
**Insumos:** `docs/idea-clusters-influencers-presupuestos.md` (QUA-70), `docs/research-discovery-influencers-co-ve.md`, `docs/oportunidades-mercado-discovery-co-ve.md`, medición en vivo Business Suite 2026-08-10.

## 1. Qué es el módulo

Un módulo de Qualify que responde, para cada cliente: **¿qué creador le queda a este negocio, con qué evidencia, y cómo vigilo la colaboración una vez contratada?** Tres funciones: discovery (candidatos), fit (matching por contenido real) y vigilancia de campaña (listening del creador contratado — deber regulatorio del anunciante según la guía SIC).

Principio rector, salido de la investigación 2026-08-10: **el pool se compra, el fit se construye.** Meta cerró la mitad aburrida del problema (quién está disponible + demografía autenticada, IG, gratis en Business Suite); la celda «matching por contenido» está verificada vacía en los 7 vendors del teardown, y TikTok/Venezuela no tienen pool comprable.

## 2. Las tres capas

| Capa | Estrategia | Qué la compone | Estado |
|---|---|---|---|
| **Pool (candidatos)** | **COMPRAR** | Meta Creator Marketplace (gratis vía Business Suite; API tras verification+review) para IG · trial Modash/Heepsy (~$89–199/mes) como suplemento · harvester propio ($0) SOLO donde no hay pool comprable: TikTok CO/VE, no-opt-in, Venezuela | Gateado por Business Verification (permiso de creadores ya asignado 2026-08-10) |
| **Fit (diferenciador)** | **CONSTRUIR** | (a) decisión «influencer vs. solo diseño» sobre hook intelligence (QUA-70-A); (b) matching negocio→creador sobre embeddings de contenido (QUA-27 + extensión brand-to-creator de QUA-70-B); (c) evidencia por candidato: hooks que usa, qué le funciona, sentiment de sus comentarios | (a) espera Fase D con datos; (b) Fase 4, bloqueada por Parte 3 |
| **Vigilancia de campaña** | **CONSTRUIR (es el core)** | Listening del creador contratado durante la colaboración — subset del listening de marca de Fases 1–2, apuntado a las cuentas del creador. Argumento de venta regulatorio (SIC) | Bloqueada por Parte 3, igual que todo el listening |

**Fuera del módulo (sin cambios):** negociación/registro/pagos de influencers (QUA-70-C — marketplace de dos lados, descartado por ahora); outreach (QUA-34, comprar en Fase 5); diseñadores como categoría (sin fuente de ingesta — research aparte).

## 3. Etapas con gates

- **E0 — ahora, ~$0, sin código.** (1) Shortlist de 10 creadores del vertical viajes con evidencia de contenido, dentro de la propuesta de 90 días del cliente Cúcuta — primer dato de disposición a pagar. (2) Fundador completa Business Verification (doble retorno: marketplace + App Review) y se corre el test de densidad CO/VE. (3) Trial Modash 14 días: ¿existe «Cúcuta» como filtro con densidad? **Gate de salida: alguien paga por una shortlist (aunque sea dentro del fee de agencia) y conocemos la densidad de los pools comprables.**
- **E1 — al aterrizar Parte 3.** Los harvest por vertical (inmobiliario, viajes) se materializan en el plano analítico como corpus de creadores con provenance. Sin UI nueva: el output sigue siendo shortlist servida por el modelo agencia. **Gate: corpus consultable por vertical.**
- **E2 — Fase 4.** El matching por contenido de verdad (QUA-27 + brand-to-creator) + integración de la Marketplace API como capa de enriquecimiento (demografía autenticada de los candidatos que sí estén en el pool de Meta). Primera versión con UI (~~la `creators_page.py` del demo es el placeholder~~ **corregido 2026-08-10, dictamen §D3-C6: ese fichero NO está en `HEAD` ni en `main` — vive solo en la rama sin mergear `feat/2026-08-07-investor-demo-mvp` y es sintético; sirve como referencia visual, no como placeholder existente**). **Gate: las 4 AC de QUA-27 + densidad de Meta medida.**
- ~~**E3 — Fase 5.** Activación: shortlist → outreach comprado (QUA-34). Nada del lado transaccional propio.~~ **ELIMINADA — corrección del fundador, 2026-08-10.** El outreach comprado de Fase 5 (QUA-34) apunta a la **demanda del tenant**: los clientes finales del cliente, **detectados por señales de intención de compra** — la cadena Fase 3 → Fase 5 que ya existe en el backlog (QUA-24, clasificador zero-shot de topic/intent/stance, es la primitiva que detecta el intent; QUA-25, comentaristas como eje mapeable, es de dónde salen los candidatos; QUA-34 es el riel de contacto). **No** apunta al contacto con los creadores de la shortlist. El contacto con influencers no es parte de esta oferta como software: se hace **manual, dentro del servicio de agencia** (negociación del fundador — que además es la fuente de evidencia para el descartado QUA-70-C). Esto resuelve por vía distinta el «supuesto roto» del dictamen §contra-(iv): el riel DM/WhatsApp hacia micro-creadores no hay que verificarlo porque no se automatiza; la oferta termina en la shortlist con evidencia. QUA-34 y QUA-30 quedan fuera de esta oferta y siguen su curso normal de Fase 4/5 para leads.

## 4. Por qué esto respeta la disciplina de fase

E0 es servicio + trámites + trials — cero código. E1 no añade alcance a Parte 3: usa lo que Parte 3 ya debe construir. E2 es exactamente la Fase 4 comprometida, con la extensión brand-to-creator ya documentada en QUA-70. Lo único genuinamente nuevo que este doc propone es **el orden y las fronteras** (qué se compra, qué se construye, qué se descarta) — y eso es lo que debe revisar el arquitecto antes de que nada entre a un sprint.

## 5. Siguientes pasos

1. Fundador: Business Verification (`business.facebook.com/settings/security?business_id=2469045020174127`) y decisión sobre incluir la shortlist en la propuesta Cúcuta.
2. ~~Sesión corta con `principal-architect`: bendecir la frontera del módulo (¿es un módulo del monolito modular per ADR 1, o una feature del módulo listening?) y decidir si merece ADR.~~ **HECHO 2026-08-10 — ver el §«Dictamen del arquitecto» al final de este doc. Veredicto: no es un módulo, es una oferta compuesta; sí merece ADR → ADR 33, FIRMADO por el fundador el mismo 2026-08-10 (con la aclaración que elimina E3).**
3. `product-owner`: cuando E0 pase su gate, convertir E1/E2 en historias con AC. **Restricciones heredadas del dictamen: los ítems se titulan por su módulo dueño (nunca «Creator Fit»); los artefactos a nivel de creador van con `source_id` per ADR 16/S2; G-JOIN se corre antes de planificar la integración de E2.**

---

# Dictamen del arquitecto, 2026-08-10

**Autor:** `principal-architect`. **Encargo:** frontera de módulo, ¿merece ADR?, consistencia con decisiones vigentes, y el supuesto más frágil. **No abre trabajo de sprint ni escribe código.**
**Verificado contra el disco** (no contra los docs) el 2026-08-10: `packages/api/src/qualify_api/connections/`, `packages/models/src/qualify_models/permission_capability.py`, `packages/models/src/qualify_models/hooks/`, `packages/scraper/src/qualify_scraper/research/harvest.py`, `Qualify/*.py`, `docs/corpus-candidatos-*.md`.

## D1. Frontera de módulo — veredicto

**Ninguna de las tres opciones planteadas es correcta. La respuesta es (d): «Creator Fit» no es un módulo, es una *oferta* — una composición de tres módulos que ya existen en el mapa, cada uno con su propio dueño, su propio schema y su propio reloj.** Argumento contra las tres antes de defender la cuarta, como pide el encargo.

### Contra (a) — «módulo propio del monolito modular per ADR 1»

ADR 1 dice: *«los límites de módulo por eventos permiten extraer servicios después sin reescribir»*. El criterio de módulo en este repo, leído en §3, es **estado propio + eventos emitidos**, no nombre de producto. Un módulo `creator_fit` fallaría las dos mitades:

- **No tendría schema propio.** Sus tres funciones escriben en schemas de otros: el pool son credenciales OAuth (`public`, tablas de `connections`), el fit son embeddings y centroides (`crm.creator_centroids_text`, `search.embeddings_text_*` — ADR 11/9-A2), la vigilancia son señales tipadas (`signals.events` — ADR 16/S2). Bajo ADR 31 la separación de planos *«ya no es imposibilidad física, es disciplina de módulo (cada módulo escribe su propio schema)»* — un módulo que escribe en tres schemas ajenos y en ninguno propio no es un módulo, es una fachada.
- **Duplicaría maquinaria de custodia ya construida.** El «pool comprado» de la §2 exige, verbatim de `research-discovery-influencers-co-ve.md` §1.1(4): *«5 permisos vía Facebook Login (`instagram_creator_marketplace_discovery`, `instagram_basic`, `pages_manage_metadata`, `pages_show_list`, `business_management`)»*. Eso es exactamente la forma de `packages/api/src/qualify_api/connections/` (custodia, FSM, `qualify_credential`, resolver de scopes) más una entrada nueva en la matriz C-05 (`permission_capability.py`, que ya modela `ScopeKey`→`Capability` con el problema de las grafías múltiples). Un módulo nuevo tendría que reimplementar o importar todo eso.

**La única objeción honesta a favor de (a)**, y hay que decirla porque es la que volverá: sí existe **un** pedazo de estado genuinamente nuevo y sin casa — **la shortlist** (conjunto curado y versionado de candidatos para un negocio, con la evidencia que justificó cada pick). No es una saved query, no es una credencial y no es un embedding. Pero es una entidad CRM: una lista de creadores colgada de un `brand_id`/campaña, y `crm` ya es el dueño de las entidades de creador (§4, `crm.creators`). Es **una tabla en un módulo existente, no un módulo**.

### Contra (b) — «feature del módulo de listening/señales»

Un tercio sí lo es —la vigilancia de campaña es literalmente el listening de §3.3 apuntado a N handles— pero los otros dos no, y meterlos ahí rompe dos cosas:

- **Importaría el reloj administrativo de Meta a un módulo que hoy no tiene superficie de credenciales.** El listening de media ganada es scraping: `ingestion.raw_payloads` es *brand-agnostic by design* (ADR 18), sin OAuth, sin App Review, sin tenant en la fila. Colgarle el pool comprado le mete Business Verification + App Review + ToS de marketplace a un módulo cuyo coste de arranque hoy es cero.
- **Pondría la maquinaria de Fase 4 bajo un módulo de Fase 2.** El matching negocio→creador lee centroides de contenido y no escribe nada en `signals`; su lado query es un *perfil de negocio*, no una mención de marca. ADR 11 aísla deliberadamente los embeddings por `(modalidad, modelo, dim)`; subordinarlos al índice de listening es el error que ADR 30/A6 ya corrigió una vez.

### Contra (c) — «dos cosas mal pegadas»

Es el instinto correcto con el corte equivocado y la cuenta equivocada. **No son dos, son tres, y la costura no es «fit vs. vigilancia»: son tres relojes distintos**, y esa es la partición que importa porque decide qué puede avanzar sin esperar a qué:

| Pieza | Módulo dueño | Reloj que la gobierna | Puede avanzar hoy |
|---|---|---|---|
| Pool comprado (Marketplace API) | `connections` (+ matriz C-05) | **Administrativo** — Business Verification + App Review, meses, fuera de nuestro control (mismo reloj de ADR 21/29) | Solo el trámite y el test de densidad |
| Fit / matching negocio→creador | `crm` + `search` (QUA-27/P4-1, Fase 4) | **De fase** — bloqueado por Parte 3, luego Fase 4 | No |
| Vigilancia de campaña | listening/`signals` (Fases 1–2) | **De fase** — bloqueado por Parte 3 | No |
| *(Shortlist servida a mano — E0)* | Ninguno: es **servicio**, no software | **Comercial** — esta semana | Sí, y es lo único que puede |

Diagnosticarlo como «dos cosas mal pegadas» sugeriría partirlo en dos ítems de backlog. La conclusión correcta es más fuerte: **dejar de tratarlo como una unidad construible** y enrutar cada tercio a su dueño.

### El veredicto (d), y por qué importa la palabra

**«Creator Fit» es una oferta comercial que compone tres módulos existentes — la misma categoría que los *plays* empaquetados de Fase 5** (`CLAUDE.md`, mapa de fases: *«packaged "plays" (signal → enrich → AI-drafted action → push)»*). Un play no es un módulo; es un recorrido nombrado sobre módulos.

Consecuencia práctica, que es todo lo que este dictamen quiere cambiar en el comportamiento de la próxima sesión de backlog: **no se crea `packages/*/creator_fit`, no se crea un schema `creator_fit`, y ningún ítem de sprint se titula «Creator Fit».** Los ítems se titulan por su módulo dueño: *«scope keys del marketplace en la matriz C-05»*, *«extensión brand-to-creator de QUA-27»*, *«saved query de vigilancia sobre handles de creador»*. El nombre «Creator Fit» vive en la propuesta comercial y en Linear como proyecto/etiqueta, no en el árbol de paquetes.

El doc que se dictamina **no pide un módulo explícitamente** — su §4 dice que lo único nuevo que propone es *«el orden y las fronteras»*. Este dictamen confirma esa lectura y la endurece: las fronteras que propone son correctas hacia afuera (qué se compra, qué se descarta) y están sin resolver hacia adentro (dónde aterriza cada pieza). Lo de arriba las resuelve.

## D2. ¿Merece ADR? — Sí, pero no la ADR que el doc insinúa

**Sí, y queda redactada como ADR 33 `[PROPUESTO]` en `docs/arquitectura.md` §6** (firma del fundador pendiente, como todas).

Lo que **no** debe registrar es «Creator Fit es un módulo» — eso es precisamente lo que D1 rechaza, y una ADR que bendiga un módulo es más cara de revertir que una que lo niegue. Lo que la hace merecer ADR son dos cosas que sí son decisiones de arquitectura, no de producto:

1. **Añade una segunda superficie de credenciales de Meta, con una segunda sumisión a App Review.** Hoy la app tiene una superficie (publicación + mensajería, ADR 21/25). El pool comprado añade `instagram_creator_marketplace_discovery` en Advanced Access, y por la precisión de ADR 29(3) —*«App Review se concede **por permiso**»*— eso es una sumisión adicional e independiente, con su propio riesgo de rechazo y su propio calendario. Comprometerse a eso sin registrarlo es exactamente el tipo de deuda que ADR 21/29 existen para hacer visible.
2. **Clasifica buy-vs-build en una superficie nueva**, que es el registro que ADR 23 mantiene. La clasificación propuesta («el pool se compra, el fit se construye») es correcta y coherente con `CLAUDE.md`, pero hay un hueco de método que la ADR debe dejar abierto: ver D3-C5.

La decisión de frontera de D1 queda registrada **dentro de esa misma ADR** (es su parte (a)), no en un doc suelto. Razón: la frontera y la clasificación buy/build son la misma decisión vista por dos caras — el pool se compra *porque* es una superficie de credenciales de `connections`, y es una superficie de `connections` *porque* se compra.

## D3. Consistencia con decisiones vigentes

Cinco verificaciones. Dos limpias, dos conflictos reales, una corrección de hecho.

### C1 — ADR 21 (organic-first, autonomía fuera): **sin conflicto**, y conviene decir por qué parece haberlo

ADR 21(d) fija *«Publicación programada en **TikTok: bloqueada, no planificada**»*. La estrategia es TikTok-céntrica (el hueco estructural de `oportunidades-mercado-discovery-co-ve.md` §1 corregido). Parece choque y no lo es: **ADR 21(d) bloquea el lado *write* de TikTok; toda esta estrategia es *read*** (harvester sobre media ajena). La asimetría verificada que ADR 21(3) cita —*«All user accounts using the API client to post must be set to private at the time of posting»*— es una restricción sobre publicar, y no toca la ingesta. Coherente.

ADR 21(c) —*«Respuestas asistidas (borrador + aprobación humana) dentro; autónomas fuera»*— tampoco se toca en E0–E2. Sí la roza E3; ver C4.

### C2 — Tensión Zernio (2026-07-30, founder-gated): **sin conflicto, y la estrategia queda del lado correcto**

La tensión abierta amenaza `packages/api/src/qualify_api/connections/` y `publishing/` — media propia. El propio texto que la abre acota su alcance: *«Lo que no desplaza nada de: Partes 1-3. Ningún agregador vende lecturas de earned media en TikTok o Instagram — cero endpoints, a cualquier precio»*. La estrategia Creator Fit vive **entera del lado de media ajena** (harvester + cascada + Fase 4), es decir en la mitad que la tensión declara intocable. **No la agrava y no depende de su resolución.**

Matiz que sí hay que registrar: si el fundador resolviera la tensión *a favor de comprar* y `connections/` fuese desplazado por un agregador, el pool comprado del Creator Fit **perdería su casa** (D1 lo aloja precisamente ahí). No es motivo para cambiar la frontera —es la casa correcta hoy— pero sí una dependencia que la ADR debe nombrar en vez de descubrirla después.

### C3 — Descarte de QUA-70-C (marketplace de dos lados): **sin conflicto; el descarte se sostiene y se refuerza**

La §2 del doc lo deja fuera explícitamente, coherente con `idea-clusters-influencers-presupuestos.md` §C y con `oportunidades-mercado-discovery-co-ve.md` §5, que lo puntúa como adyacencia **nula**: *«el lado transaccional — registro de creadores, negociación, pagos/escrow (en VE, con qué riel siquiera), contratos… Este doc no lo reabre: el hueco de Meta no cambia la economía del cold start de dos lados»*. Nada en E0–E3 lo reabre por la puerta de atrás. Limpio.

### C4 — CONFLICTO REAL: E3 asume un riel de contacto con creadores que ningún doc de evidencia verificó

E3 dice: *«Activación: shortlist → outreach comprado (QUA-34). Nada del lado transaccional propio.»* El descarte del lado transaccional es correcto (C3). El problema es la palabra **«comprado»**: el vendor de outreach que Fase 1 dejó decidido (Instantly/HeyReach o Smartlead+Zapmail, `CLAUDE.md` mapa de fases) es **infraestructura de email B2B**. El contacto con micro-creadores en el corredor Cúcuta–Táchira no es email B2B — es DM y WhatsApp.

Esto no está verificado en ninguno de los dos docs de evidencia: `research-discovery-influencers-co-ve.md` cataloga siete vendors de *datos* y ninguno de *contacto* con creadores; `oportunidades-mercado-discovery-co-ve.md` §5 clasifica el lado transaccional como fuera de adyacencia pero no examina el riel de contacto. Y la vía «DM desde la cuenta propia del tenant» no es equivalente a la bandeja de Parte 4-B: esa es superficie de **respuesta** dentro de ventana, no de **outbound en frío**.

**Estado: supuesto no verificado, heredado sin examen.** No invalida E0–E2. Sí invalida tratar E3 como «ya resuelto por compra». Gate propuesto en D4-G3.

### C5 — CONFLICTO DE MÉTODO: la estrategia da por hecho que el pool comprado se compra con *nuestra* App Review

E2 propone *«integración de la Marketplace API como capa de enriquecimiento»* asumiendo la ruta directa: nuestra app, nuestro App Review, nuestro Advanced Access. Pero la disciplina que ADR 23 fijó para la superficie análoga dice otra cosa, verbatim: *«lo que compra un agregador hospedado es operar bajo su app ya aprobada, no el código de sus adapters»*. En Parte 4-A esa disciplina concluyó **build**, porque ADR 21(2) demostró que *«en Meta, para cliente cero, no hay ninguna aprobación que saltarse»*. **Aquí la premisa se invierte:** `instagram_creator_marketplace_discovery` **sí** exige Advanced Access + App Review (gtm §1.1(4)), es decir sí hay una aprobación que saltarse, que es justo el driver de valor que ADR 23 valoró en cero para publicación y que aquí valdría lo máximo.

No afirmo que exista un partner revendible operando bajo app aprobada para esta API — no lo he verificado y el teardown de gtm tampoco lo cubre (Manus construye sobre la API, pero es producto final, no riel). **Lo que sí afirmo es que la pregunta no se hizo**, y que ADR 23 obliga a hacerla antes de comprometer un App Review propio. Queda como ítem abierto dentro de ADR 33.

### C6 — Corrección de hecho (regla de la casa: el disco manda)

E2 dice *«(la `creators_page.py` del demo es el placeholder)»`*. **Verificado 2026-08-10: `Qualify/creators_page.py` no existe en `HEAD` ni en `main`.** Solo hay un `.pyc` huérfano en `Qualify/__pycache__/`. El fichero vive únicamente en la rama sin mergear `feat/2026-08-07-investor-demo-mvp` (commit `3d7ac81`, *«investor demo MVP — 8 synthetic screens»*), y su contenido es **sintético por construcción** (`demo_data.py`). Citarlo como placeholder de una UI futura está bien; citarlo como algo que existe en el producto, no. Corregir la frase.

### Provenance — la regla se respeta en la letra y queda sub-especificada en un punto

E1 pide *«corpus de creadores con provenance»*, lo cual cumple la regla. El hueco: **un artefacto a nivel de creador es un agregado sobre N posts, y la regla de provenance está definida a nivel de fragmento** (`source_id` + `detector_version`/`pipeline_version`; clave de `signals.events` extendida a `(source_id, label, detector_version)` por el ruling S2). Una fila «creador X usa el gancho Y» con un `creator_id` y sin fuentes **viola la regla aunque parezca cumplirla**. La forma correcta ya está decidida por ADR 16 (*N filas, nunca `Array`*) y no necesita ADR nueva — necesita que quien escriba las historias de E1 no invente una tabla de perfil de creador con campos derivados y sin fuentes. Se registra aquí para que el `product-owner` lo herede como restricción, no como sorpresa de review.

## D4. El punto más débil

### Primero: el candidato propuesto no es el punto más débil, y una de sus mitades es falsa

El encargo propone *«que la Marketplace API de Meta sea integrable como capa de enriquecimiento en E2 — nadie ha verificado qué permisos/access level exige esa API ni si el pool CO tendrá densidad»*. Desafiado como pide el encargo:

- **«Nadie ha verificado qué permisos/access level exige» es falso** — está verificado, en fuente primaria, en el doc que el propio encargo manda leer: `research-discovery-influencers-co-ve.md` §1.1(4) lista los cinco permisos, el Advanced Access de `instagram_creator_marketplace_discovery`, y que *«con Standard Access solo se obtienen datos de prueba»*. La consecuencia arquitectónica de ese hecho sí estaba sin extraer (es D1: no es enriquecimiento, es superficie de credenciales), pero el hecho está.
- **«Ni si el pool CO tendrá densidad» es cierto y ya está gateado** — es H2 de gtm, y E0.2 lo prueba con el test de Business Suite. Un riesgo con gate no es el punto más débil de una estrategia; es un riesgo gestionado.

### El punto más débil real: **la estrategia asume que el pool comprado y el fit construido se refieren a los mismos creadores. Son disjuntos por construcción.**

El principio rector de la §1 —*«el pool se compra, el fit se construye»*— solo funciona si ambas mitades se pueden unir sobre la misma entidad. Los dos lados están definidos sobre poblaciones que no se solapan por diseño:

| | Pool comprado (Meta Marketplace) | Fit construido (corpus propio) |
|---|---|---|
| Plataforma | **Instagram** | **TikTok** (harvester, corpus, spike de hooks — todo TikTok-first) |
| Población | Solo **opt-in**: *«18+, cuenta profesional pública, ≥1.000 seguidores, aceptar Partner Monetization Policies»* (gtm §1.1); *«el no-onboardeado sigue invisible incluso con la política abierta»* (oport. §4) | Cualquier cuenta pública observable, sin consentimiento ni umbral |
| Por qué la otra plataforma no está | TikTok **no tiene marketplace** en CO/VE — ése es precisamente el hueco estructural de la tesis | Instagram Reels está en el plan de ingesta, pero el corpus real y el spike son TikTok |

E2 dice, literalmente, *«demografía autenticada de los candidatos que sí estén en el pool de Meta»*. Esa frase esconde una operación que **no existe en ningún sitio del repo: resolución de identidad de creador entre plataformas** — decidir que el handle de TikTok que el harvester cosechó y la cuenta de Instagram que el marketplace ofrece son la misma persona. §4 de `arquitectura.md` une los planos por `creator_id`, pero **quién acuña ese `creator_id` a través de dos plataformas está sin definir**, y no hay código que lo haga.

Por qué esto es más grave que la densidad, y por qué es el punto más débil y no un detalle de implementación:

1. **Es la junta que sostiene toda la arquitectura híbrida.** La forma «contenido propio (moat) + marketplace como capa de enriquecimiento» —que el doc de la idea llama *«la arquitectura correcta probable»*— *es* esa junta. Si la tasa de resolución es baja, no queda una arquitectura híbrida degradada: quedan **dos productos desconectados**, uno de fit sobre TikTok sin demografía y otro de demografía sobre IG sin fit.
2. **Es invisible en E0–E3.** Ningún gate lo mide. E0 mide disposición a pagar y densidad; E1 mide corpus consultable; E2 mide las 4 AC de QUA-27 y la densidad de Meta. **Se puede pasar los cuatro gates y descubrir el problema al integrar** — que es el orden más caro posible, porque para entonces ya se gastaron la Business Verification y el App Review.
3. **El corredor es el peor sitio posible para intentarlo.** H4 de gtm, verbatim: *«El público binacional Cúcuta–Táchira es estructuralmente invisible para la inferencia de ubicación de los vendors globales (población desplazada, bios sin ciudad, audiencia repartida entre dos países…)»*. La misma propiedad que hace valioso el nicho hace difícil la resolución de identidad en él.
4. **Medido en el disco, hoy: los corpus existentes no llevan identidad cruzada.** `docs/corpus-candidatos-inmobiliario-tachira-cucuta.md` y `docs/corpus-candidatos-viajes-cucuta-santa-marta.md` mencionan Instagram 11 y 3 veces respectivamente, de forma incidental — no como columna, no como identificador. El spine no existe ni siquiera en la forma manual.

### G-JOIN — el gate que falta (entre E1 y E2)

**Gate de tasa de resolución cruzada.** Sobre los corpus verticales que **ya existen en disco**, contar a mano qué fracción de creadores de TikTok cosechados puede resolverse a una cuenta de Instagram, y con qué evidencia (link en bio, mismo handle, marca de agua de cross-post, coincidencia de nombre + confirmación visual). Es una tarde de trabajo manual, cero código, y se puede correr **antes** de E1 — no después.

- **Qué decide.** Si la fracción resoluble es alta, la arquitectura híbrida de E2 se sostiene y la Business Verification compra algo real. Si es baja, **la mitad Meta de E2 muere** y la estrategia se convierte en fit-solo-TikTok — que sigue siendo un buen producto (es la celda vacía verificada) pero es **otro producto**, con otro pitch y sin necesidad del trámite.
- **Por qué antes y no después.** Es el único gate que puede ahorrar el reloj administrativo entero. Nótese que **no lo bloquea**: la Business Verification tiene doble retorno (marketplace + App Review de ADR 21/29) y debe arrancar igual en semana 0. Lo que G-JOIN decide es si la *integración* de E2 se planifica, no si el trámite se hace.
- **Umbral.** Lo fija el fundador, no el arquitecto — depende de cuánto vale la demografía autenticada en el pitch. Lo que sí es ruling: **el umbral se escribe antes de mirar el resultado**, o el gate no gatea nada.

### Dos gates menores que la etapa E0 tampoco tiene

- **G-EVID (dentro de E0).** La shortlist que se venda en E0 debe llevar **cita a nivel de post** en cada afirmación de evidencia («usa este gancho», «esto le funciona»). Motivo: el argumento de venta regulatorio es la guía de la SIC, que pide al anunciante *«revisar periódicamente los comentarios y valoraciones de los consumidores que constituyen la audiencia del influenciador»* — una shortlist sin trazabilidad al post vende diligencia que no puede demostrar. Coste: cero, si se hace desde el primer entregable. Coste si se retrofitea en E1: rehacer el corpus. Es además el ensayo manual de la regla de provenance de D3.
- **G-RIEL (antes de comprometer E3).** Verificar que existe un riel de contacto con micro-creadores CO/VE compatible con lo comprado en Fase 5, o registrar E3 como no resuelto. Ver C4.

## D5. Resumen ejecutable

1. **No es un módulo.** Es una oferta compuesta por tres módulos existentes con tres relojes distintos. Nada se llama «Creator Fit» en el árbol de paquetes ni en un schema. → **ADR 33 (a)**.
2. **El pool comprado aterriza en `connections` + matriz C-05**, no en un módulo nuevo ni en listening — porque es una superficie de credenciales OAuth con App Review propio, no una capa de datos. → **ADR 33 (b)**.
3. **Sí merece ADR**, redactada como ADR 33 `[PROPUESTO]` en `arquitectura.md` §6, pendiente de firma del fundador.
4. **Conflictos:** C4 (riel de outreach a creadores, supuesto heredado sin verificar) y C5 (no se hizo la pregunta de ADR 23: ¿se puede comprar la aprobación en vez de tramitarla?). Más la corrección de hecho C6 (`creators_page.py` no está en disco).
5. **Gate que faltaba: G-JOIN**, la tasa de resolución de identidad TikTok↔Instagram sobre los corpus que ya existen. Es el único riesgo capaz de vaciar E2 y ninguna etapa lo mira.
