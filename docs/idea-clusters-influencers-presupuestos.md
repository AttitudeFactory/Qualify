# Idea de backlog — Del hook a la activación: clusters de fit influencer/diseñador, presupuestos multi-influencer y registro en plataforma

**Fecha:** 2026-08-08 · **Fuente:** el fundador (verbal, sesión de trabajo) · **Estado:** idea sin refinar — parking lot, pendiente de seed en Linear (proyecto «Parking lot — features analizadas (no planificadas)»).
**Contexto inmediato:** nace del flujo del cliente agencia de viajes Cúcuta (`docs/cliente-agencia-viajes-cucuta-prioridades-mvp.md` §P1 — banco de hooks asignables «a CM o influencers»).

## La idea, tal como se enunció

Una vez Qualify entrega el análisis de hooks y el cliente decide **cómo** producir (contratar un influencer vs. generar publicidad solo con diseño gráfico), la plataforma:

1. Gestiona **presupuestos de varios influencers** en paralelo y la **negociación de términos y condiciones**, con los influencers **registrándose en la plataforma** de Qualify.
2. **(La parte central para el fundador):** según el **carácter y la naturaleza del negocio** del cliente, Qualify perfila el **cluster de influencers o diseñadores que hacen fit** con ese negocio.

## Descomposición y mapeo de fase

La idea son en realidad **tres features de madurez muy distinta**. Separarlas es lo que la hace accionable:

### A. Decisión asistida «influencer vs. solo diseño» (capa de recomendación sobre hooks)

- **Qué es:** el output del hook intelligence deja de ser solo «estos ganchos funcionan» y pasa a recomendar el vehículo de producción: si los hooks ganadores del vertical dependen de rostro/voz/credibilidad personal → influencer; si dependen de texto-en-pantalla/oferta/visual → diseño gráfico basta.
- **Fase:** frontera Fase 2/3 (insights sobre el corpus de hooks). Es la pieza **más barata y más cercana**: el spike de hooks (Fases A/B) ya extrae los tres canales (hablado/mostrado/texto-en-pantalla) por separado — la recomendación es una lectura agregada de esa descomposición que ya existe.
- **Dependencia:** Fase D del spike con datos reales (hoy diseñada, sin datos; el vertical viajes se los daría).

### B. Clusters de fit negocio → influencer/diseñador (la parte central)

- **Qué es:** perfilar al negocio del cliente (carácter, naturaleza, vertical, tono) y devolver el cluster de creadores cuyo **contenido real** hace fit — no su bio autodeclarada.
- **Fase:** **Fase 4** — esto es en esencia P4-1 (lookalike sobre embeddings de contenido multimodal) con una vuelta genuinamente nueva: **el lado query del matching es el perfil del negocio, no un creador semilla**. P4-1 responde «dame creadores parecidos a este»; esta idea responde «dame creadores que le quedan a *este negocio*» — brand-to-creator matching, no creator-to-creator. Es una extensión de P4-1, no un ítem nuevo independiente, y hereda sus 4 AC obligatorias (challenged & survived, datasci).
- **Alineación con el moat:** encaja de lleno con el principio «read the content, not the profile» — el fit se computa sobre lo que el creador publica de verdad, que es exactamente la ventaja de confianza documentada frente a Modash/Upfluence.
- **Hueco abierto que la idea introduce:** los **diseñadores** como categoría de oferta. Todo el pipeline ingesta video social; el trabajo de un diseñador gráfico vive en portfolios (Behance, IG estático). No hay fuente de ingesta ni embedding comprometido para eso — si los diseñadores entran, es research nuevo, no una extensión.

### C. Presupuestos multi-influencer + negociación T&C + registro de influencers

- **Qué es:** el lado transaccional — comparar presupuestos de N influencers, negociar términos dentro de la plataforma, y que los influencers tengan cuenta propia en Qualify.
- **Fase:** Fase 5+ o **sin fase**. Esto convierte a Qualify de SaaS de un solo lado en **marketplace de dos lados**, y ese es un cambio de categoría estratégico, no una feature:
  - **Cold start de dos lados:** ningún influencer se registra en una plataforma sin marcas, ninguna marca paga por un marketplace vacío. Con 3 clientes del modelo agencia, el lado oferta hoy es cero.
  - **Carga operativa nueva:** contratos, pagos/escrow, disputas, fiscalidad transfronteriza (el público objetivo es binacional Cúcuta–Táchira) — nada de esto existe ni está adyacente al stack.
  - **Ya se vende hecho:** Upfluence/Modash tienen módulos de campaña+pagos, y — verificado en el corpus harvesteado de Meta (`reference/meta-instagram-platform/.../creator-marketplace.md`) — **Meta expone una Instagram Creator Marketplace API** (discovery de creadores señalando interés en branded content, brand information, Creator Insights). Por disciplina buy-don't-build, antes de construir registro/negociación propios hay que hacer el teardown de esa API y de los módulos de campaña de los vendors (tarea natural del `gtm-specialist`).
  - **Validación barata disponible:** el modelo agencia gestionada ES el laboratorio. El fundador va a negociar con influencers manualmente para el cliente de viajes (req. 3.3: reels asignables a influencers). Documentar ese proceso manual 2-3 veces revela si la fricción real está en encontrar (→ B), en presupuestar (→ tabla comparativa, feature chica) o en negociar (→ la parte cara). No escribir código de marketplace antes de eso.

## Opinión registrada (asistente, 2026-08-08)

- **B es la parte valiosa y ya está ~80 % comprometida como el diferenciador de Fase 4.** La contribución genuina de la idea es (1) la dirección del matching (negocio como query) y (2) enmarcar la salida como decisión de producción (A). Ambas merecen quedar adjuntas a P4-1 como extensión, no como ítem rival.
- **C es la parte arriesgada.** Marketplace de dos lados con oferta cero, competidores que ya lo venden y una API de Meta que cubre parte del discovery: el patrón del repo (tensión Zernio, ADR 23) dice *evaluar comprar antes de construir*, y la validación manual vía el modelo agencia es gratis y ya está en curso.
- **Nada de esto toca código ahora:** B depende duro de Fase 1 Parte 3 (plano analítico, no arrancado) + embeddings de Fase 4; A depende de Fase D del spike con datos. La única acción de fase actual es research (teardown Creator Marketplace API + observación del proceso manual de negociación con el cliente de viajes).

## Evidencia nueva (2026-08-08): conector de Manus sobre la Instagram Creator Marketplace API

> ⚠ **CORRECCIÓN 2026-08-10 — la forma fuerte de esta sección está DESACTUALIZADA.** El teardown del `gtm-specialist` (`docs/research-discovery-influencers-co-ve.md` §1.1, fuentes primarias de Meta) encontró que Meta expandió el lado empresa a global el 2026-01-30 y que su help center describe hoy el lado **creador** como «worldwide donde opere Meta advertising», con solo 6 exclusiones sancionadas — **ni Colombia ni Venezuela excluidas**. El blog de Manus (marzo 2026) describía el estado pre-expansión. La incógnita en Instagram ya no es de política sino de **densidad** (cuántos creadores CO/VE están onboardeados — test barato: filtrar Colombia en Business Suite con la cuenta del fundador). El hueco que **sí sobrevive y es estructural** es **TikTok** (TTCM/TikTok One ≈24 países, LATAM solo BR/MX, sin vía de entrada para creadores CO/VE) — que es exactamente la plataforma donde Qualify ya ingesta a $0 — más el sub-hueco Venezuela y la celda vacía de matching por contenido multimodal (el discovery scrapeado de creadores CO es commodity desde ~$89–199/mes). Las conclusiones de la sección siguiente se mantienen solo en la parte que no dependía del hueco IG; el sustento de «refuerza el build de B» cambia de «Meta no llega» a «Meta llega en IG con densidad incierta y no llega en TikTok».

Fuente aportada por el fundador: https://manus.im/es/blog/manus-instagram-creator-marketplace (beta del conector de Manus). Confirma y cuantifica lo que el corpus harvesteado ya insinuaba, y añade el dato que decide el mapa:

- **Cobertura del lado creador: 18 mercados, y ni Colombia ni Venezuela están.** LATAM cubierto: Argentina, Brasil, México (más España en habla hispana). Las *empresas* pueden usar el marketplace desde casi cualquier país (solo excluye 6 sancionados), pero los *creadores* descubribles son solo de esos 18 mercados. **Consecuencia directa para Qualify: la API de Meta no puede suplir el pool de creadores del nicho geográfico core (Cúcuta–Táchira, binacional Colombia–Venezuela).** El discovery propio sobre contenido scrapeado (Fase 4 / pieza B) no compite contra Meta en ese territorio — lo cubre donde Meta no llega. Esto **refuerza el build de B** y degrada la opción "comprar discovery a Meta" a complemento para mercados grandes.
- **Elegibilidad del lado empresa:** portafolio comercial verificado + cuenta IG business vinculada a página de Facebook. Es la misma Business Verification que ya está en el reloj administrativo de ADR 21/29 — si ese reloj arranca, la elegibilidad para esta API viene casi gratis.
- **Qué sí vende Meta que el scraping no da:** datos *autenticados* de primera mano — demografía de audiencia (edad/género/ubicación), métricas de rendimiento reales, colaboraciones previas, y creadores que ya **optaron por colaborar**. Para los mercados cubiertos, eso es un dato de intención y de audiencia que ningún scraper puede replicar legítimamente. La arquitectura correcta probable es híbrida: contenido propio (moat) + marketplace API como capa de enriquecimiento/contacto donde exista.
- **Señal competitiva:** Manus (plataforma de agentes generalista) ya empaqueta discovery → tabla comparativa → outreach → campaña por invitación con oferta fija para dos Reels, en un solo flujo. La parte C de esta idea (presupuestos/negociación) ya la está comoditizando el ecosistema de agentes sobre la API oficial. Un teardown del conector (qué endpoints usa, qué deja fuera) es tarea natural del `gtm-specialist`.

**Ajuste al veredicto:** B (clusters propios) sale *fortalecida* — es la única vía para el nicho geográfico real. C sale aún más claramente como **buy/esperar**: Meta + agentes ya cubren la mecánica transaccional en los mercados donde el marketplace opera, y en Colombia/Venezuela la negociación seguirá siendo manual (modelo agencia) hasta que Meta expanda cobertura o el volumen justifique otra cosa.

## Test de densidad H2 — primer intento (2026-08-10, medido en vivo)

Intentado desde Business Suite con la cuenta `qualifymkt.co` (`business.facebook.com/latest/creator_marketplace`):

- **El lado empresa está abierto desde Colombia sin verificación** — la Plataforma de creadores carga para el portafolio Qualify.co, en español, sin bloqueo por país. Confirma en vivo el hallazgo del teardown (§1.1 de `research-discovery-influencers-co-ve.md`): la restricción geográfica del lado empresa ya no existe.
- **El buscador (y por tanto el test de densidad) está gateado por Business Verification:** «Not verified — Verifica tu portfolio comercial Qualify.co para acceder a colaboraciones con creadores usando nuestras estadísticas exclusivas», con botón «Verify business». Sin portafolio verificado no se puede filtrar creadores por país.
- Banner adicional: desde el 4 de octubre se exigirá el «permiso de administración de creadores» para crear campañas o guardar listas.

**Consecuencia:** el test de densidad H2 queda **pendiente de la Business Verification** — la misma que la enmienda a ADR 21 recomendaba arrancar en semana 0 para el App Review. Ahora ese reloj administrativo desbloquea dos cosas a la vez (visibilidad pública vía API + acceso al marketplace), lo que refuerza arrancarlo ya.

## Siguiente paso propuesto

1. Seed en Linear (parking lot): un issue por A, una nota de extensión sobre el issue existente de P4-1 para B, un issue «research: teardown marketplace/negociación (buy-vs-build)» para C.
2. Al cerrar el primer ciclo de reels con influencers del cliente de viajes, capturar el proceso manual de presupuesto/negociación como evidencia para C.
