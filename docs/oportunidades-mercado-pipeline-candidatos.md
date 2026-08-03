# Pipeline de candidatos de nicho — pasada de screening

> **Analista de mercado externo (market-opportunity-analyst) · 2026-07-30**
> **Estado: PASADA CERRADA.** Escrito incrementalmente y en disco. Contiene **dos pases independientes** que confluyeron en el mismo archivo (§0-§2 y §3), más su cruce (§5). Lo que está escrito está verificado al nivel de tiering que declara y nada más.
>
> **Ruta de lectura si solo tienes cinco minutos:** **§8 (E4 / hallazgo Zernio — reordena todo lo demás)** → §7 (ranking) → §5 (el cruce de los dos pases) → §4 (lo que esta pasada NO establece). El §4 no es una formalidad: hay un paso cero obligatorio (fijar jurisdicción del comprador) sin el cual el ranking no debe usarse.
>
> **Si solo lees una cosa:** el foso de Qualify existe **únicamente sobre earned media en TikTok/Instagram**. Contenido en YouTube lo adquiere cualquiera por ~$0,001/vídeo (API de Gemini); contenido en cuentas propias del cliente lo adquiere cualquiera por $1-6/cuenta/mes (Zernio). Eso elimina dos candidatos que estaban en cabeza. Ver §8.

## 0. Qué es este documento y qué NO es

Esto es una **pasada de triage**, no un conjunto de tesis de oportunidad. Ninguna fila de abajo cumple el formato de tesis completo (`El cambio / El dolor / Sustitutos / Señal de urgencia / Adyacencia / Fase / Qué la falsifica / Validación más barata`). El objetivo es **ordenar la cola** de deep-dives, no cerrarlos.

### El filtro de entrada (heredado del post-mortem inmobiliario)

La investigación inmobiliaria (`docs/oportunidades-mercado-inmobiliario.md`, `docs/demanda-ventas-inmobiliario.md`) terminó con un hallazgo que es la lente de esta pasada:

- **T-3 tenía demanda pero no foso** (cualquiera puede construirlo).
- **R6 tenía foso pero demanda cero observada** en todas las fuentes que el squad reunió.

La causa raíz del fracaso no fue "el nicho es pequeño". Fue que el comprador inmobiliario quiere información **sobre su propia actividad** (sus leads, sus propiedades, sus publicaciones, su CRM) y **no** sobre el mundo exterior. Social listening es, por construcción, un producto sobre el mundo exterior: qué dicen terceros, qué hacen los competidores, qué conversación existe fuera de tu cuenta.

**Por lo tanto, el filtro de entrada de esta pasada es una sola pregunta:**

> ¿Hay indicio de que este comprador ya paga, ya trabaja, o ya se queja por saber algo del **MUNDO EXTERIOR** — competidores, conversación de mercado, contenido de terceros, creadores ajenos — y no solo de sí mismo?

Un nicho que solo quiere métricas de su propia cuenta es un nicho de analytics/CRM, no de listening. Puede ser un buen negocio; **no es este negocio**, y llevarlo a deep-dive repite el error inmobiliario.

### Tiers

| Tier | Significado |
|---|---|
| **A — investigar primero** | Pasa el filtro de mundo exterior con evidencia, no con corazonada. |
| **B — investigar si hay tiempo** | Plausible pero el indicio de mundo exterior es `[H]`. |
| **C — descartar por ahora** | Falla el filtro, o el dolor es sobre sí mismo, o ya está servido. |
| **RE-AUDITORÍA** | Ya investigado, pero con un sesgo conocido sin corregir. No es candidato nuevo. |

### Tiering de evidencia

`[P]` fuente primaria (URL + fecha de acceso) · `[S]` secundaria · `[H]` hipótesis mía, sin verificar.

> **Nota de adyacencia:** todas las marcas de adyacencia en este documento son **PRELIMINARES Y SIN VERIFICAR CONTRA DISCO**. Se asignan por razonamiento sobre los activos diferenciados declarados (cascada multimodal sobre contenido primario, señales con procedencia, ingesta first-party por cuentas conectadas, plano dual Postgres/ClickHouse), no por inspección del filesystem. La verificación contra disco es trabajo de la fase de deep-dive.

### El segundo filtro, que el inmobiliario reveló y es más duro que el primero

De la ronda adversarial (`docs/oportunidades-mercado-inmobiliario.md` §6.0), un hallazgo que endurece el screening y que aplico a todo lo de abajo:

> El techo de software del comprador LATAM (**$50-185/mes para toda la empresa**, verificado por `gtm`) está por debajo de **un solo asiento** de cualquier herramienta de listening comparable (**$249-950/mes**). Cuando existe una explicación estructural suficiente de por qué una categoría no existe en un mercado, inferir whitespace es injustificado.

Y la formulación que sobrevivió a esa sesión, que reutilizo como pregunta de screening:

> No es *"¿este nicho quiere escuchar?"*. Es: **"¿pagaría este comprador un *delta* por listening de grado-contenido sobre el listening de grado-palabra-clave que ya compra?"**

Más una sospecha del propio analista que quedó registrada allí y que aquí se convierte en criterio: puede que el comprador inmobiliario **no esté en el mercado de productos de información a ningún grado ni precio** — compra herramientas de **ejecución** (publicar, contactar, cerrar). Por eso en la tabla de abajo cada candidato lleva una lectura explícita de **información vs. ejecución**.

**Consecuencia operativa del filtro de precio:** los nichos donde el listening tiene un **obligado legal o contractual** (no es "nice to have", es exposición a multa, a takedown o a responsabilidad solidaria) son estructuralmente superiores, porque el presupuesto no sale de la línea "software de marketing" sino de la línea "compliance/riesgo", que tiene otro techo. Esto ordena el ranking más que cualquier estimación de TAM que no podría sostener con fuente.

---

## 1. Candidatos — Tier A (investigar primero)

Los tres de este tier comparten una propiedad que el inmobiliario no tenía: **el comprador es responsable de contenido que él no produjo**. Eso es literalmente la definición de un producto de listening sobre el mundo exterior, y hace que el gasto sea defensivo, no discrecional.

### A-1 — Marcas con programa de afiliados/creators en TikTok Shop

| Campo | Contenido |
|---|---|
| **Gancho** | `[S]` La responsabilidad se trasladó al vendedor: *"las marcas son ahora directamente responsables del contenido creado por sus afiliados; la violación de un creador puede dañar el rating de la tienda"*, y la FTC espera que el vendedor **documente sus esfuerzos de monitorización**. Además TikTok Shop US ejecutó un *account health reset* en julio 2026. Fuentes (acceso 2026-07-30): [Darkroom — TikTok Shop Risks 2026](https://www.darkroomagency.com/observatory/tiktok-shop-risks-in-2026-what-every-brand-needs-to-know), [AuditSocials — TikTok Shop Ad Compliance 2026](https://www.auditsocials.com/blog/tiktok-shop-ad-compliance-guide-product-claims-influencer-disclosures-cross-border-2026), [ListerRank — Affiliate Violation Points](https://listerrank.com/blog/how-to-protect-your-shop-from-affiliate-policy-violations), [Calywire — July 2026 Account Health Reset](https://calywire.com/tiktok-shop-us-july-2026-account-health-reset/). **Todas son `[S]` secundaria interesada** (agencias y vendors de brand protection venden precisamente esto) — el gancho requiere confirmación contra la policy primaria de TikTok Shop antes de cualquier deep-dive. |
| **Mundo exterior vs. propia actividad** | **MUNDO EXTERIOR, y de la variedad más fuerte que hay.** El objeto a vigilar es contenido de video que la marca **no produjo, no aprobó y no controla**, publicado por cientos de afiliados. No es analytics de su propia cuenta. El claim prohibido ("cura el insomnio" en vez de "apoya el sueño") vive **hablado dentro del video**, no en el caption — es exactamente el punto ciego que el listening de texto no ve. |
| **Información vs. ejecución** | **Información con consecuencia ejecutable** (takedown, desactivar afiliado). El mejor de los dos mundos: el output es un hecho, no un dashboard. |
| **Adyacencia preliminar** | **ALTA — SIN VERIFICAR CONTRA DISCO.** Razonamiento: reusa la cascada multimodal sobre contenido primario (transcripción + visión) tal como está concebida, y "señal con procedencia" es *exactamente* lo que un expediente de compliance necesita (qué se dijo, en qué segundo, en qué post, con qué versión de detector). El activo diferenciado no se estira: se usa para lo que fue diseñado. **A confirmar contra disco**: la cascada existe en `packages/models/` pero el plano analítico (ClickHouse, workers) no. |
| **Prioridad** | **AVANZAR PRIMERO.** Único candidato donde el dolor es (a) sobre terceros, (b) legalmente obligatorio, (c) invisible al listening de texto, y (d) el comprador ya es el ICP declarado de Qualify (marcas con equipo de marketing), no un pivote de público. |

### A-2 — Servicios financieros / cripto con programa de afiliados o finfluencers

| Campo | Contenido |
|---|---|
| **Gancho** | `[S]` Régimen de enforcement coordinado y con dientes penales: nueve reguladores (FCA, ASIC, SFC de Hong Kong entre otros) ejecutaron una semana de acción simultánea contra promociones financieras ilegales de finfluencers → **3 detenciones, cargos penales contra 9 personas, +650 solicitudes de takedown, +50 webs cerradas**. La FCA identificó **1.267 anuncios financieros ilegales** que alcanzaron ≥2,3 millones de cuentas UK. Regla clave: *"la firma es responsable de cualquier promoción hecha en su nombre, sin importar quién pulsó publicar"*, y debe **cribar a cada afiliado antes de contratarlo y conservar evidencia de esas comprobaciones**. Fuentes (acceso 2026-07-30): [Hoopoz — The Finfluencer Crackdown 2026](https://www.hoopoz.com/articles/finfluencer-crackdown-2026-fca-global-enforcement-finance-affiliate-compliance), [Sedric — Influencer & Finfluencer Compliance Guide 2026](https://www.sedric.ai/blog/influencer-compliance), [InnReg — FINRA and SEC Increase Focus](https://www.innreg.com/resources/regulatory-updates/finra-and-sec-increase-focus-on-social-media-finfluencers). **Tier `[S]`**: son vendors de compliance y agencias; las cifras deben verificarse contra los comunicados primarios de FCA/ASIC/SFC antes del deep-dive. |
| **Mundo exterior vs. propia actividad** | **MUNDO EXTERIOR.** La obligación es sobre lo que dice un tercero contratado, en su propio canal. Y "conservar evidencia de las comprobaciones" es una demanda de **archivo con procedencia**, verbalizada por el regulador, no inferida por mí. |
| **Información vs. ejecución** | **Información pura, comprada desde el presupuesto de compliance/riesgo** — el único presupuesto que no compite con el de marketing. Esto es lo que rompe el techo de $50-185/mes que mató al inmobiliario. |
| **Adyacencia preliminar** | **MEDIA — SIN VERIFICAR CONTRA DISCO.** Reusa la cascada multimodal y la procedencia, pero añade trabajo nuevo acotado y no trivial: un detector de *claim regulado* (promesa de rentabilidad, ausencia de disclaimer, producto no autorizado) que la cascada actual no tiene, y que probablemente cae en el mismo hueco que `NOTES_pain_signal_feasibility.md` ya documentó — el modelo de sentimiento de 3 clases no lo cubre. Adicionalmente exige un régimen de retención/exportación de evidencia que hoy no existe. |
| **Fase preliminar** | Fase 3 (señales tipadas con procedencia). No adelantable sin el plano analítico. |
| **Prioridad** | **AVANZAR — segundo.** Mayor willingness-to-pay del tablero, pero también el ciclo de venta más largo y el comprador más exigente (auditoría, retención, SLA). Riesgo real: **la categoría ya tiene vendors nativos** (Sedric y similares aparecen escribiendo el contenido de esta búsqueda, lo que es señal de mercado servido). El deep-dive debe empezar por `competitor-profiling`, no por dolor. |

### A-3 — Suplementos / nutracéutica / CPG de salud y bienestar

| Campo | Contenido |
|---|---|
| **Gancho** | `[P]`/`[S]` mezclado, y la parte `[P]` es la mejor fuente de todo el documento porque es el propio regulador: la FTC mantiene una página de tópico viva sobre [Health Claims](https://www.ftc.gov/news-events/topics/truth-advertising/health-claims) (acceso 2026-07-30) y su *Health Products Compliance Guidance* exige respaldo científico competente y fiable calibrado a la fuerza del claim. La pieza decisiva, `[S]` y pendiente de verificar contra los expedientes primarios: **la FTC ha actuado contra empresas de suplementos específicamente por no monitorizar ni corregir claims no sustentados hechos por sus redes de afiliados**, y la marca responde *"con independencia de si lo guionizó, lo revisó, o siquiera supo que existía"*. Además la FTC finalizó la regla contra reseñas y testimonios falsos y señaló sanciones civiles en 2026. Fuentes `[S]` (acceso 2026-07-30): [Truli — FTC Influencer Compliance for CPG](https://trytruli.com/blog/ftc-influencer-compliance-supplement-brands), [Truli — FTC Health Claims 2026](https://trytruli.com/blog/ftc-health-claims-what-supplement-brands-need-to-know), [Armstrong Teasdale — Food, Beverage & Consumer Products Issues to Watch 2026](https://www.armstrongteasdale.com/thought-leadership/food-beverage-and-consumer-products-issues-to-watch-for-2026/). |
| **Mundo exterior vs. propia actividad** | **MUNDO EXTERIOR.** *"...ni siquiera supo que existía"* es, textualmente, la descripción de un problema de listening: el comprador es responsable de contenido cuya **existencia desconoce**. No hay forma de resolverlo mirando su propia cuenta. |
| **Información vs. ejecución** | **Información**, con presupuesto de riesgo legal. |
| **Adyacencia preliminar** | **ALTA — SIN VERIFICAR CONTRA DISCO.** Misma lectura que A-1: el claim de salud se pronuncia **hablado en el video** ("esto me curó el insomnio"), que es el punto ciego declarado del listening de texto y el caso de uso natural de la transcripción + procedencia. Salvedad honesta, la misma de A-2: *detectar un claim sustanciable* es un detector nuevo, no el clasificador de sentimiento de 3 clases ya comprometido — `packages/models/NOTES_pain_signal_feasibility.md` ya documentó ese hueco para otra familia de señales y la conclusión traslada. |
| **Prioridad** | **AVANZAR — junto con A-1, no después.** Ver la nota inmediatamente siguiente: probablemente no son dos deep-dives, sino uno. |

### ⚠ Hallazgo transversal de esta pasada: A-1, A-2 y A-3 no son tres nichos

Los tres candidatos de Tier A comparten **el mismo mecanismo de mercado**, y creo que tratarlos como tres verticales sería un error de segmentación que costaría tres deep-dives donde hace falta uno:

> **Una marca es legalmente responsable de afirmaciones hechas en video, por creators que ella no controla, cuya existencia frecuentemente desconoce.**

TikTok Shop, servicios financieros y suplementos son solo tres **regímenes regulatorios** que instancian el mismo patrón. El segmento real no es una vertical — es una **postura**: *marca regulada con ejército de creators*. Lo que varía entre ellas es qué constituye una infracción (claim de salud / promesa de rentabilidad / disclosure ausente), y eso es **configuración del detector, no arquitectura distinta**.

Esto importa por tres razones:

1. **Cambia el orden de trabajo.** Un solo deep-dive sobre la postura, con las tres regulaciones como variantes, en vez de tres.
2. **Cambia la lectura de adyacencia al alza.** Un detector configurable de "claim prohibido en contenido de tercero, con procedencia" sirve a las tres. La procedencia deja de ser una virtud arquitectónica declarada en los docs y pasa a ser **el entregable que el comprador compra** — el expediente de que vigiló.
3. **Es la primera vez en este corpus que un dolor pide, literalmente, el activo diferenciado.** "Read the content, not the profile" no es aquí una preferencia de diseño: leer el perfil es **inútil** para este comprador, porque la infracción está en el minuto 0:47 del video.

Lo registro como hallazgo transversal y no como tesis porque **no lo he verificado con dolor verbalizado por compradores reales** — todo el Tier A descansa en fuentes de vendors y despachos que venden compliance, que es exactamente la clase de fuente interesada que este proyecto ya aprendió a descontar. Es la primera tarea del deep-dive, no una conclusión de esta pasada.

**Y el contraargumento que hay que buscar antes de entusiasmarse, no después:** la abundancia de vendors escribiendo sobre esto (Sedric, Truli, BrandShield, AuditSocials) es señal de mercado **ya servido**, no de whitespace. Aplica aquí la misma disciplina que `gtm` impuso en el inmobiliario: la presencia de oferta es evidencia más fuerte que la ausencia de oferta, y aquí hay oferta.

---

## 2. Candidatos — Tier B (investigar si hay tiempo)

Tier B se distingue de Tier A en una cosa: **el indicio de mundo exterior es `[H]` o indirecto.** No están descartados; están sin evidencia de que el comprador verbalice el dolor.

### El instrumento que usé para el Tier B: dónde ya hay un humano contratado para hacerlo

Un principio de screening que aplico aquí y que recomiendo mantener: **el sustituto más informativo no es un software, es un empleado.** Si una empresa paga un salario por "social listening analyst", ha revelado willingness-to-pay por la función en la moneda menos ambigua posible, y el techo de precio del software es una fracción legible de ese salario.

`[S]` Búsqueda de ofertas de empleo (acceso 2026-07-30): existen puestos activos de *social listening analyst* con rango declarado **$27k-$144k**, y las verticales que aparecen contratando son **telecomunicaciones** (Spectrum, Customer Operations, publicado 2026-05-19), **entertainment/media** (Warner Bros. Discovery), **consultoría/public affairs** (Rational 360) y **gaming** (Mutiny, la agencia de Trailer Park Group dedicada solo a gaming). Fuentes: [ZipRecruiter — Social Listening jobs](https://www.ziprecruiter.com/Jobs/Social-Listening?version=next), [Spectrum — Social Media Listening Analyst](https://jobs.spectrum.com/job/buffalo/social-media-listening-analyst/4673/95299611312), [Glassdoor — social listening analyst NY](https://www.glassdoor.com/Job/new-york-social-listening-analyst-jobs-SRCH_IL.0,8_IC1132348_KO9,33.htm).

Advertencia de método sobre este instrumento: **es enteramente estadounidense**, que es precisamente el sesgo que T-7 identificó en el research previo de este proyecto. No lo presento como neutro. Lo presento como lo que es: evidencia de que la función existe y se paga **en EE. UU.**, muda sobre si se paga en el mercado donde Qualify tiene su único cliente.

| # | Nicho | Gancho | ¿Mundo exterior? | Info vs. ejecución | Adyacencia prelim. (sin verificar) | Prioridad |
|---|---|---|---|---|---|---|
| **B-1** | **Gaming (estudios y publishers)** | `[S]` Agencia dedicada solo a gaming contratando analista de social analytics; la conversación de un título vive casi entera en video (streams, clips, reacciones) y no en texto | **Sí, fuerte.** Un publisher necesita saber qué dicen streamers y comunidad sobre su título — es literalmente contenido de terceros en video | **Información**, y con crisis-management asociado (un lanzamiento fallido es un evento de días) | **ALTA** — el corpus es video/audio nativo; es el caso donde el listening de texto pierde más señal | **Investigar.** El mejor candidato no-regulado del tablero |
| **B-2** | **Public affairs / comunicación política e institucional** | `[S]` Rational 360 contratando un *Social Listening Fellow* para un enfoque de datos integrado para clientes | **Sí.** Todo el objeto es discurso de terceros | **Información pura**, presupuesto alto y poco sensible al precio | **MEDIA** — reusa la cascada, pero exige velocidad casi real-time y una tolerancia a falsos positivos muy baja | **Investigar si hay tiempo.** Ciclo de venta por relación, mal encaje para un fundador en solitario |
| **B-3** | **Telecomunicaciones / utilities (atención al cliente)** | `[S]` Spectrum contrata el rol dentro de *Customer Operations*, no de marketing | **Sí**, pero la conversación es sobre uno mismo (quejas de su servicio) — mundo exterior solo en el sentido de que ocurre fuera de sus canales | **Ejecución** disfrazada de información: el output es un ticket | **BAJA** — el valor está en el routing/inbox, no en la cascada multimodal | **Descartar por ahora.** Es un producto de customer service, no de listening. Compite con Sprinklr/Salesforce |
| **B-4** | **Entertainment / media (estudios, streaming, música)** | `[S]` Warner Bros. Discovery contratando con requisito de herramientas de social analytics de terceros | **Sí.** Reacción de audiencia a estrenos, tracking de UGC | **Información** | **MEDIA-ALTA** — encaja bien con el corpus de video, pero el comprador es enterprise con incumbentes atrincherados | **Investigar si hay tiempo.** Buen encaje técnico, pésimo encaje con la capacidad comercial actual |
| **B-5** | **Agencias de social media y freelances (revendedores)** | `[P]` El propio corpus ya lo identificó: *"el modelo que hace rentable a Fase 0 no es vender la API. Es usar la API como palanca de margen sobre un servicio, o vendérsela a quien ya presta ese servicio (agencias y freelances)"* — `docs/fase0-zernio-mercado.md` §Tarea 5. Rango de precio agencia/freelance ya documentado allí: **€200-1.500/mes por cliente** | **Indirecto, y esa es su debilidad.** La agencia quiere saber del mundo exterior **de su cliente**, no del suyo. Compra si eso le permite cobrar más o servir a más clientes | **Ambos** — es un multiplicador, no un comprador final | **MEDIA** | **Investigar — pero como CANAL, no como nicho.** Es la única entrada del tablero que ya tiene validación en el corpus propio y que **rompe el techo de precio del comprador final** (la agencia reparte el coste entre N clientes). Merece deep-dive con `gtm` |

---

## 3. Segundo pase de cribado (escrito en paralelo — leer la nota de reconciliación)

> ### ⚠ NOTA DE RECONCILIACIÓN (2026-07-30)
>
> **Todo lo que sigue se escribió en paralelo con las §0-§2 de arriba, por otra instancia del mismo rol y sin verlo.**
> Al confluir en el mismo archivo, la numeración chocó. **No he borrado nada del primer pase** — está mejor
> abastecido que el mío en varias filas y su hallazgo transversal (§1, "A-1/A-2/A-3 no son tres nichos") es la mejor
> pieza de análisis del documento. He renumerado lo mío a partir de §3 y **eliminado mis filas duplicadas**.
> **✅ RESUELTO (2026-07-30) — la colisión de identificadores ya no existe.** Las etiquetas están unificadas en todo
> el documento y **no hace falta cruzar referencias para saber de qué pase viene una fila**:
>
> | Prefijo | Origen | Dónde se definen |
> |---|---|---|
> | **`A-n`** | Tier A del **primer** pase | §1 (A-1 TikTok Shop, A-2 finfluencers, A-3 suplementos) |
> | **`B-n`** | Tier B del **primer** pase | §2 (B-1…B-8) |
> | **`C-n`** | Descartes del **primer** pase | §3.6 y la tabla de descartes |
> | **`N-n`** | Candidatos **nuevos** del segundo pase | §3.3 (N-1…N-8) |
>
> **Un candidato del segundo pase desapareció al deduplicar, y conviene saberlo porque el §5.2 le atribuye un
> hallazgo:** su fila *"sectores regulados (alcohol, apuestas, finanzas) — compliance de influencers contratados"*,
> etiquetada `A-4` en el borrador, **se eliminó como duplicado** de la `A-2` (finfluencers) del primer pase y de la
> postura común de §1. No se perdió nada sustantivo: su contenido vive en §1 y en el hallazgo transversal. **La
> etiqueta `A-4` ya no designa nada en este documento** — donde el §5.2 habla de ella, se refiere a esa fila
> eliminada, y el hallazgo que produjo se ha reasignado a la postura de §1.
>
> **Convergencia, y el descuento que le corresponde.** Los dos pases llegaron por separado a la misma postura de
> comprador: **marca regulada que responde por contenido de creadores que no controla.** Es señal, pero **no son dos
> observaciones independientes**: compartimos brief, rol y el mismo documento inmobiliario como lente. Aplíquese el
> mismo descuento que el doc inmobiliario §6.0-2bis: **coincidencia entre analistas con inputs comunes no es
> replicación.** Lo genuinamente independiente es que las **fuentes** son distintas (ellos: TikTok Shop/FCA/FTC;
> yo: EMA-GVP/FDA/Nielsen-KORE) y aun así el mecanismo es el mismo. Eso sí cuenta.
>
> **Y una discrepancia real que NO conviene suavizar: el gaming.** El primer pase lo puntúa **B-1, adyacencia ALTA,
> "el mejor candidato no-regulado del tablero"**. Mi criterio **E2 lo descarta a C**. Ver §3.4 — la discrepancia es
> el punto más útil de este documento y debe resolverse antes de cualquier deep-dive de gaming.

### 3.1 Corrección al alcance de la nota de adyacencia

La nota de arriba dice que la verificación contra disco es trabajo del deep-dive. **Se corrige: esa verificación ya
existe y no hay razón para diferirla.** `docs/oportunidades-mercado-inmobiliario.md` §1 la hizo el 2026-07-29 contra
el filesystem. Resumen vinculante para todo este documento:

| Existe y funciona | No existe (verificado por ausencia) |
|---|---|
| Cascada multimodal (`filter → vision → transcription → sentiment`) con `source_id` + `pipeline_version` propagados | **ClickHouse** — cero imports; las 6 coincidencias son docstrings |
| `connections`/OAuth Meta — 18 archivos, lo más maduro del repo, incl. `revoke.py` | **Celery / workers / scheduler** — cero coincidencias en todo el repo |
| Scraper Zyte + parsers TikTok/IG + envelope v2 | `scripts/`, `infra/`, `packages/pipeline/`, `packages/gpu-service/` |
| Multi-tenant: `tenants`/`tenant_members`/`brands`, RLS por `tenant_id`, 3 roles | |
| Migraciones `0003_publishing` y `0004_inbox` (publish_attempts, scheduled_posts, threads, messages) | |
| `packages/models/.../social/ig_comments.py` — comentarios de IG de cuentas conectadas | |

**Tres salvedades que acotan cualquier score de adyacencia** (§1.3 del doc inmobiliario): el cliente R2 existe pero
`boto3` **no está declarado** y solo se ha probado contra un doble en memoria; el cliente de publicación de Meta
**nunca se ha ejecutado contra Meta** (lo dice su propio docstring); y **toda la cascada está marcada `integration`,
así que no corre en CI** — los 298 tests verdes no contienen ni una pasada real de la cascada. Además el filtro F2
**no tiene regla de decisión cableada en ninguna dirección** (QUA-23 abierta, golden set de **un ítem**).

> **Consecuencia operativa que domina el resto del documento:** **sin Celery/scheduler no existe producto de
> monitoreo continuo**, solo un script que alguien ejecuta a mano. Todo nicho que exija vigilancia permanente —y casi
> todos los de abajo la exigen— **paga ese coste antes que ningún otro**. Es más limitante que la ausencia de ClickHouse.

---

### 3.2 Criterios eliminatorios (además del filtro de mundo exterior)

El filtro de mundo exterior de §0 es el primero. Estos tres son los siguientes, y también eliminan.

| # | Criterio | Por qué elimina | Origen |
|---|---|---|---|
| **E1 — ¿existe la categoría base?** | ¿El comprador ya paga por *algún* producto de información sobre el exterior? | Si no compra la categoría, no hay delta que vender. Preguntar por la prima antes de confirmar la base fue el error diagnosticado en la sesión inmobiliaria. | Doc inmobiliario §6.0-2c y §6.0-bis |
| **E2 — ¿el contenido vive FUERA de YouTube?** | **El criterio menos obvio y probablemente el más decisivo.** La API de Gemini ingiere **URLs de YouTube directamente** `[P]` (https://ai.google.dev/gemini-api/docs/video-understanding, consultado 2026-07-29). Donde el contenido es YouTube, **Qualify no tiene ninguna ventaja de adquisición**: cualquier competidor hace la misma llamada por ~$0,001. El foso existe **solo en TikTok/Instagram**, donde hay que conseguir los bytes legítimamente. | Doc inmobiliario §4.1/§4.3 |
| **E3 — ¿el techo de gasto supera el coste de servir?** | El techo LATAM ($50-185/mes por empresa) quedó por debajo de un solo asiento de listening ($249-950/mes) — explicación suficiente de la ausencia de oferta, sin necesidad de invocar whitespace. | ADV1 (`gtm`) + pricing de Tokko (`sales`) |

**Puntuación (0-2 cada uno), solo para los que sobreviven:**
**P1** tirón por información exterior · **P2** valor de la procedencia (¿hay que *demostrar* de dónde salió la señal?) ·
**P3** resistencia a la commoditización (¿basta una llamada a un modelo frontera?).

---

### 3.3 Candidatos que el primer pase no cubre

**Solo filas nuevas.** Las que el primer pase ya trata mejor (TikTok Shop, finfluencers, suplementos, gaming,
public affairs, telco, entertainment, agencias) **no se duplican aquí** — véanse §1 y §2.
`[H]` salvo donde se indique. **Los scores ordenan la cola; no deciden construir.**

| # | Nicho candidato (nuevo) | ¿Mundo exterior? | E1 base | E2 no-YouTube | E3 techo | P1 | P2 | P3 | Tier |
|---|---|---|---|---|---|---|---|---|---|
| **N-1** | **Farma/OTC — farmacovigilancia sobre comentarios en canales propios** | Sí (comenta un tercero) | **Sí** `[S]` | Sí (IG/FB) | Alto | 2 | **2** | 2 | **A** |
| **N-2** | **Valoración de patrocinio dentro de contenido de creadores** | Sí | **Sí** `[S]` | Parcial | Alto | 2 | **2** | 2 | **A** |
| **N-3** | **Franquicias / marcas multi-local — compliance de marca en contenido del franquiciado** | Sí | Débil | Sí | Medio-alto | 1 | 2 | 2 | **A** |
| **N-4** | **Sellos musicales / A&R — detección temprana de artistas y sonidos** | Sí | Sí `[S]` | **Sí** (TikTok nativo) | Alto | 2 | 0 | 2 | **B** |
| **N-5** | **Protección de marca / falsificaciones vendidas dentro del vídeo** | Sí | Sí `[S]` | Sí | Alto | 2 | 2 | 1 | **B** |
| **N-6** | **Turismo / entes de promoción de destino** | Sí | Débil | Sí | Bajo-medio | 1 | 0 | 1 | **C** |
| **N-7** | **Retail media / marketplaces — vigilancia de vendedores** | Sí | Sí | Parcial | Alto | 1 | 1 | 1 | **C** |
| **N-8** | **Educación / edtech** | **No** — quiere métricas propias | — | — | Bajo | 0 | 0 | 0 | **C** |
| — | **Inmobiliario LATAM** | **No** (frontera medida) | — | — | **Falla E3** | 0 | — | — | **CERRADO** |
| — | **Creadores / podcasters / e-commerce** | Mixto | ? | ? | ? | ? | ? | ? | **RE-AUDITORÍA** (sesgo T-7 sin corregir) |

---

### 3.4 Notas sobre los candidatos nuevos de Tier A

### N-1 · Farma/OTC — farmacovigilancia sobre comentarios en canales propios *(el candidato nuevo más fuerte)*

Es el único candidato donde **la ley obliga a mirar**, y eso resuelve de un golpe el problema que hundió al
inmobiliario: no hace falta que el comprador *quiera* la información.

`[S]` La GVP de la EMA exige a los titulares de autorización de comercialización *"regularly screen the internet or
digital media **under their management or responsibility**"* buscando sospechas de reacciones adversas, con una
definición amplia de medio digital (webs, blogs, **redes sociales**, foros). `[S]` Bajo la guía ICH/FDA las empresas
**no** están obligadas a monitorizar proactivamente sitios de terceros, **pero sí a actuar sobre eventos adversos de
los que tengan conocimiento**; y en **mayo de 2025** la FDA emitió una carta de advertencia a Sprout Pharmaceuticals
señalando que **un comentario de un cliente bajo una publicación de la compañía describiendo una reacción adversa
dispara la obligación de reporte** (21 CFR Part 314). Ventanas de reporte de 24 horas.
(https://www.resolver.com/solutions/pharma-social-media-monitoring/, https://www.datashake.com/blog/adverse-event-monitoring-on-social-media-what-pharma-teams-need-to-know, consultados 2026-07-30.)

**Por qué encaja con lo que existe en disco, y es el encaje más limpio de todo el pipeline:** el alcance obligatorio
es **contenido de terceros sobre superficie propia** — exactamente comentarios en cuentas conectadas. Eso es
`connections`/OAuth (el módulo más maduro) + `social/ig_comments.py` (**ya existe**), **sin scraping**, **sin
ClickHouse** (el volumen de comentarios de una marca cabe en Postgres) y **sin GPU**. La procedencia deja de ser
higiene: con ventanas de 24 h y auditoría regulatoria, *demostrar* de qué comentario salió la señal **es** el producto.

**Los tres costes reales, dichos por delante:** (i) exige **scheduler**, que no existe — una ventana de 24 h no se
sirve con un script manual; (ii) el clasificador de evento adverso no existe y **el listón de recall es brutal**, un
falso negativo es un incumplimiento regulatorio, no un informe flojo; (iii) es venta **enterprise** con ciclos largos
y validación de proveedor, un modelo comercial que Qualify no ha ejercitado nunca.
**Comprobación más barata:** leer una guía GVP Módulo VI real y contar cuántas de sus exigencias se cubren con lo que
ya hay. Horas, sin hablar con nadie, y **sobre normativa publicada, no sobre una población sesgada** — el error que
esta metodología ya cometió una vez.

### N-2 · Valoración de patrocinio dentro de contenido de creadores

`[S]` Categoría pagada, establecida y con incumbentes serios: Nielsen Sports vende *media valuation*; **KORE adquirió
Hookit en febrero de 2022** (https://koresoftware.com/, https://nielsensports.com/media-valuation/, consultados 2026-07-30).
La mecánica es exactamente "leer el contenido, no el perfil": detectar el logo en el vídeo, medir tiempo en pantalla,
tamaño y claridad, y convertirlo en valor de medios.

**Lo atractivo:** P2 = 2 porque **la procedencia es la factura**. Un patrocinador que paga contra exposición medida
exige poder auditar de qué frame salió cada dólar. Eso es `source_id` + `pipeline_version`, que ya están.
**Lo desfavorable, y no es menor:** los incumbentes están capitalizados y el grueso del valor está en **retransmisión
televisiva**, que no es TikTok/IG — ahí E2 solo pasa **parcialmente**. La franja donde Qualify tendría ventaja es
específicamente **patrocinio dentro de contenido de creadores en TikTok/IG**, no el patrocinio deportivo en general.
Detección de logos, además, **no está construida** (la cascada describe, no detecta marcas).

### N-3 · Franquicias / marcas multi-local — compliance de marca en contenido de franquiciados

**Está en Tier A por una razón concreta: repara el falsador que mató a T-5.** En inmobiliario, el broker no podía
exigir a agentes —contratistas independientes, dueños de sus cuentas— que conectaran nada. **Un franquiciador sí tiene
autoridad contractual sobre el uso de marca del franquiciado.** El mismo producto, con la palanca de instalación que
allí faltaba.
`[H]` **Lo que no sé y decide el nicho:** si esa autoridad se ejerce hoy sobre redes sociales o solo sobre rotulación
y publicidad tradicional. **Comprobación más barata:** leer 3 contratos o manuales de marca de franquicia públicos y
buscar cláusulas de redes sociales. E1 está marcado **débil** a propósito: no tengo evidencia de que hoy paguen por esto.

### 3.5 ⚠ DISCREPANCIA ENTRE LOS DOS PASES: el gaming

**No la suavizo, porque es el desacuerdo más útil del documento y se resuelve con una comprobación de una hora.**

- **Primer pase (§2, B-1):** gaming es *"el mejor candidato no-regulado del tablero"*, adyacencia **ALTA**, con el
  argumento —correcto— de que la conversación de un título vive en **vídeo** (streams, clips, reacciones) y no en texto.
- **Mi criterio E2:** gaming se descarta a **C**, porque ese vídeo vive en **YouTube y Twitch**, y la API de Gemini
  **ingiere URLs de YouTube directamente** por ~$0,001 el vídeo. Donde el contenido es YouTube, **Qualify no aporta
  ninguna ventaja de adquisición**: el competidor hace la misma llamada sin scraper, sin OAuth y sin infraestructura.

**Ambos podemos estar en lo cierto sobre cosas distintas, y ahí está la salida:** el primer pase acierta en el
**tirón** (P1 alto: hay demanda real de información exterior); yo acierto en el **foso** (P3 nulo si el corpus es
YouTube). Y esa combinación —mucho tirón, cero foso— **es exactamente la forma de T-3 en la sesión inmobiliaria**,
la tesis que tuvo demanda observada y ninguna defensa. **Sería el mismo error a mayor escala.**

**Lo que decide la discrepancia, y es barato:** determinar **qué fracción de la conversación relevante de un título
vive en TikTok/Instagram frente a YouTube/Twitch**. Si es mayoritariamente TikTok, el primer pase gana y gaming sube
a A. Si es YouTube/Twitch, gano yo y baja a C. **Es una medición, no una opinión**, y **debe hacerse antes de
cualquier deep-dive de gaming.**

**Generalización que vale más que el caso:** E2 debe aplicarse a **todas** las filas de ambos pases, incluidas las
del primero, que no lo tenía disponible. **Un nicho con contenido mayoritariamente en YouTube no es un nicho para
Qualify por muy alto que puntúe en todo lo demás** — es un nicho para cualquiera con una clave de API.

---

### 3.6 Descartados, y por qué (para que no vuelvan sin motivo nuevo)

- **Gaming (B-1 del primer pase) — yo lo bajo a C por E2.** Ver §3.5: es una discrepancia abierta, no un descarte
  cerrado, y se resuelve midiendo dónde vive la conversación del título.
- **N-8 Educación** — falla el filtro de mundo exterior: quiere métricas de sus propios canales.
- **N-6 Turismo, N-7 marketplaces** — no fallan de forma limpia; simplemente no destacan en nada. Se aparcan.
- **CPG/belleza (brand health genérico) queda en B, no en C, y la distinción importa:** es el nicho con la
  **categoría base más sólida** de todos — Brandwatch, Talkwalker y similares llevan años vendiéndose ahí, así que E1
  es un sí rotundo, cosa que **ningún** candidato de Tier A puede decir. Baja a B porque P3 es flojo: contra un
  incumbente con corpus histórico y contratos enterprise, la ventaja de adquisición se diluye. **Es el candidato
  correcto si la pregunta cambia de "¿dónde hay foso?" a "¿dónde hay presupuesto probado?".** `gtm` declaró no haber
  comprobado si Talkwalker/Brandwatch tienen módulo de vídeo — ese hueco decide esta fila.

---

### 3.7 Respuesta del autor de N-1/N-3 a E4: **acepto las dos degradaciones**, y afino los residuos

Escrito tras leer §8. **N-1 y N-3 caen. No las defiendo** — el argumento es correcto y una de sus dos cuchillas la
puse yo mismo en §3.4.

**N-1 (farmacovigilancia): la pinza es real y es mía.** Cité que la obligación de la GVP cubre medios
*"under their management or responsibility"* —superficie **propia**— y también que bajo ICH/FDA **no hay deber
proactivo de vigilar sitios de terceros**. Puestas juntas con el hallazgo Zernio: **la superficie obligada es
comprable a $1-6/cuenta/mes y la superficie defendible no está obligada.** El motor económico que la hacía atractiva
—"la ley obliga a mirar, así que la demanda da igual"— apunta exactamente donde no tenemos ventaja.

> **El residuo, nombrado con precisión para que nadie lo reinfle después:** Zernio entrega **el comentario**, no el
> **dictamen**. Lo que la farmacovigilancia necesita encima es el *expediente*: clasificación de evento adverso,
> retención, trazabilidad y versión del detector. Eso **no lo vende Zernio y no lo da una llamada a un modelo**.
> Pero seamos honestos sobre qué clase de producto es: es **workflow y archivo regulatorio**, no inteligencia de
> contenido — y **Qualify no tiene ninguna ventaja construyendo eso** frente a cualquier otro. Residuo real,
> insuficiente para sostener un nicho. **N-1 degradada, correctamente.**

**N-3 (franquicias): la inversión es elegante y la acepto.** La autoridad contractual que reparaba el falsador de T-5
es la misma que vuelve conectables las cuentas del franquiciado, y por tanto convierte el problema en *owned media*
comprable. **La palanca que arregla la instalación es la que destruye el foso.**

> **Y aquí el residuo sí tiene una propiedad que merece registrarse, porque es un foso por construcción:** lo que
> sobrevive son las cuentas que **no quieren ser encontradas** — franquiciados que se niegan a conectar, y cuentas
> locales no autorizadas o *rogue* operando bajo la marca. **En ese caso el OAuth es imposible por definición**: no
> se puede pedir consentimiento a quien está precisamente evadiendo el control. La adquisición por *earned media*
> (scraping) no es ahí una alternativa más barata, es **la única vía física**, y ningún competidor la esquiva
> comprando Zernio. Es un nicho **mucho más estrecho** que N-3 tal como la escribí —y probablemente sea una
> *feature* de brand protection antes que un nicho— pero es el único sitio del documento donde el foso es
> **estructural y no coyuntural**. Vale más como criterio de diseño que como candidato.

#### El error de método, que es mío y ya va por la tercera vez con la misma forma

`opportunity-2` señala que *"encaje limpio con lo que existe en disco"* mide **coste de construcción**, no
**defendibilidad**, y que aquí los dos se movían en direcciones opuestas: N-1 encajaba limpiamente **porque** usaba el
único módulo que acababa de confirmarse comprable. Lo acepto sin reservas. Y conviene generalizarlo, porque **es la
tercera instancia del mismo error en esta familia de sesiones**:

| # | Artefacto de nuestro propio proceso | Leído erróneamente como | Dónde |
|---|---|---|---|
| 1 | El esquema multi-tenant encaja con la forma del cliente uno | Product-market fit | Doc inmobiliario, T-5 (es tautología: se construyó para ese tenant) |
| 2 | Tres agentes convergen en la misma conclusión | Replicación independiente | Doc inmobiliario §6.0-2bis (brief y lente compartidos) |
| 3 | El candidato encaja limpiamente con lo que hay en disco | Foso | **Aquí, N-1** |

> **La forma común: un artefacto de nuestro propio método leído como evidencia sobre el mundo.** Los tres son
> agradables de encontrar, los tres se sienten como confirmación, y **los tres apuntan hacia dentro.** Candidato a
> regla permanente: *ninguna propiedad de nuestro código, nuestro esquema o nuestro proceso de análisis es evidencia
> de mercado.* La evidencia de mercado vive fuera y hay que ir a buscarla.

#### Sobre el hueco que `opportunity-2` deja abierto en §8.4 — y el único candidato que puede que lo salve

> ⚠ **PARCIALMENTE REFUTADO — leer junto a §9.2/§9.3 antes de actuar sobre esta subsección.**
> *(Nota añadida por `opportunity-2`; no he alterado el argumento de abajo, solo señalo dónde se responde.)*
> El marco **E-FOSO ∧ E1 se acepta entero** — es la mejor aportación de esta subsección y cierra el hueco de §8.4.
> **Lo que no sobrevive es "N-2 es el único que pasa los dos": pasan cuatro** (A-1, A-2, A-3 y N-2), porque los
> vendors de compliance que cobran hoy (BrandShield, Truli, Sedric) satisfacen E1 igual que Nielsen y KORE.
> Pareció único porque **el mismo hecho —existe un vendor establecido— se puntuó con signo negativo para los
> candidatos de un pase y positivo para los del otro** (§9.3). **N-2 sube igualmente, al puesto 2 de §7, pero por
> la razón corregida de §9.4, no por unicidad.**

Correcto y es el hueco decisivo: **E-FOSO puntúa defendibilidad, no demanda.** Pasarlo no produce un comprador; así
murió R6. Pero el documento **sí tiene un criterio de demanda**, solo que no está etiquetado como tal: **E1
(¿existe la categoría base?)**, que es lo único que contó como evidencia de demanda en toda la sesión inmobiliaria.
Leídos juntos, el cribado es **E-FOSO ∧ E1**, y eso reduce mucho la lista:

- **N-2 (valoración de patrocinio) parece el único candidato que pasa los dos.** Foso: contenido de creadores es
  *earned media* en TikTok/IG, no comprable vía Zernio ni ingerible vía URL de YouTube. Demanda: **categoría pagada y
  establecida** — Nielsen Sports vende *media valuation* y KORE compró Hookit en febrero de 2022. **No es una
  categoría que haya que crear.**
- **Con dos salvedades que no oculto:** el grueso del valor del patrocinio está en **retransmisión**, no en TikTok/IG,
  así que su paso por E2 es **parcial** y el nicho real es la franja de patrocinio *dentro de contenido de creadores*;
  y **la detección de logos/marcas no está construida** — la cascada describe escenas, no detecta marcas.
- **Aun así merece subir**, porque es el único sitio donde no hay que apostar simultáneamente a que existe foso **y** a
  que existe presupuesto. **Ése, y no la abundancia de compliance, es el argumento más fuerte que queda en el documento.**

#### 3.7-bis RECTIFICACIÓN: «el único que pasa los dos» era falso, y debajo hay DOS errores

`opportunity-2` comprobó la afirmación y **no sobrevive**. Aplicando E1 por su definición literal de §3.2 —*"¿el
comprador ya paga por **algún** producto de información sobre el exterior?"*— pasan al menos cuatro: **A-1**
(BrandShield, AuditSocials, ListerRank cobran hoy por monitorización de afiliados), **A-3** (Truli cobra por
compliance de claims de salud), **A-2** (Sedric cobra exactamente esto) y **N-2**. **Retiro la afirmación.**

Debajo hay **dos** errores distintos, y el segundo no está en su diagnóstico:

**Error 1 — asimetría de signo (el suyo, y es el sutil).** Ellos puntuaron la presencia de vendors establecidos como
argumento **en contra** de sus candidatos ("mercado ya servido"); yo la puntué como argumento **a favor** del mío
("categoría probada que no habría que crear"). Misma clase de evidencia, signo opuesto, **y la variable que
determinaba el signo era de quién era el candidato.** Lo acepto entero, y también la resolución: un vendor que cobra
responde *"¿hay presupuesto para esta clase de información?"* con **sí** (E1) y *"¿hay hueco por donde entrar?"*
**desfavorablemente** (P3), **siempre**. Separadas, sube E1 y baja P3 **para los cuatro**.

**Error 2 — afirmé unicidad sin enumerar (el mío, y es el barato).** *"El único candidato que pasa los dos"* es una
afirmación **comparativa** y no hice la comparación: nunca corrí E1 sobre A-1, A-2 ni A-3. Examiné un caso y concluí
sobre el conjunto.
**Importa porque su defensa propuesta es cara y ésta no.** Ellos concluyen que lo único que funcionó fue que dos
analistas con candidatos propios se auditaran mutuamente. Cierto, pero es un recurso escaso y situacional.
**Este error concreto lo habría atrapado una comprobación mecánica y gratuita:** *toda afirmación de la forma "X es el
único que…" exige enumerar los demás antes de escribirla.* Sin segundo analista, sin ronda adversarial, sin coste.
**Regla operativa propuesta, complementaria a la suya: enumerar antes de afirmar unicidad.**

**Un matiz que corrige a la baja mi propio candidato, y por eso lo escribo yo.** Dicen que la presencia de vendors
sube E1 y baja P3 *"por igual"* para los cuatro. **No es por igual, y la desigualdad me perjudica.** Nielsen y
KORE/Hookit son incumbentes **enterprise, grandes y atrincherados**, con contratos a escala de retransmisión; Sedric
y Truli son SaaS de compliance pequeños. Para un fundador en solitario **desplazar a Nielsen es prácticamente
imposible, mientras que competir con un SaaS pequeño es concebible**. El castigo de P3 es por tanto **mayor en N-2 que
en A-1/A-3**. La contrapartida —incumbente grande = presupuesto probado más grande— es real, pero no compensa a esta
escala de equipo. **N-2 baja algo más de lo que su propia corrección ya la bajaba.**

**Acepto los otros dos puntos sin reservas:** (i) **E-FOSO⁺** —consentimiento inobtenible en principio— es el criterio
correcto, y su observación de que **A-1/A-3 lo satisfacen parcialmente y N-2 no** es acertada: un afiliado que hace un
claim prohibido **no coopera con su propia detección**, mientras que un creador patrocinado cooperaría encantado.
**El foso de N-2 es menos estructural que el de la postura.** (ii) N-2 es **el candidato más lejano del disco** de todo
el Tier A —la detección de logos no existe y es capacidad de visión nueva con su propio golden set, no configuración
de detector—, **inverso exacto de N-1, que era el más cercano y murió precisamente por serlo.** A-1/A-3 en el #1 por
coste de construcción es correcto: es la variable que ata a un fundador en solitario.

> **Y lo que no cambia por más secciones que añadamos: cero compradores entrevistados.** E1 se satisface con
> *"un vendor cobra por esto"*, que evidencia **que la categoría existe** — no que **este** comprador, en **esta**
> geografía, a **este** precio, la compre. El paso 0 sigue siendo lo único que desbloquea algo.

---

## 4. Cierre conjunto de los dos pases: qué NO hacen y qué falta corregir

1. **Todo se buscó en inglés.** El mismo sesgo que produjo el error de T-1. Cada nicho de arriba está descrito en su
   forma **estadounidense/europea**. Si el comprador objetivo vuelve a ser LATAM, **E3 (techo de gasto) es el criterio
   que más probablemente cambie de signo**, y podría vaciar el Tier A entero.
2. **Paso cero obligatorio antes de cualquier deep-dive, y es la lección cara de la sesión anterior:**
   **fijar la jurisdicción y el país del comprador ANTES de puntuar nada.** La mejor tesis de la ronda inmobiliaria
   descansaba sobre el régimen regulatorio del país equivocado. **Esto amenaza a casi todo el Tier A de AMBOS pases**,
   porque su valor entero es regulatorio: FTC, FCA, EMA y FDA **no vinculan a un comprador uruguayo**. Si el comprador
   objetivo sigue siendo LATAM, **el Tier A conjunto puede vaciarse por la misma vía que mató a T-1** — y eso es la
   advertencia más importante de este documento.
3. **No hay ronda adversarial en ninguno de los dos pases.** Estos scores no han sido atacados por nadie. En la sesión
   anterior la ronda adversarial **cambió conclusiones, no matices**: mi tesis mejor puntuada acabó cerrada. Trátense
   estos números como cola de trabajo, **no como ranking de confianza**.
4. **Sesgo estructural, declarado, y es el mismo en los dos pases: casi todo el Tier A conjunto es compliance.**
   Puede ser una lectura correcta de dónde tiene apalancamiento el activo —la información obligatoria se compra aunque
   no se desee, y ése es justamente el presupuesto que rompe el techo que mató al inmobiliario— o puede ser
   **sobreajuste a la última sesión**, donde un hallazgo de compliance fue lo más brillante que encontré antes de morir
   por jurisdicción. **Que dos instancias en paralelo cayeran en el mismo patrón no lo confirma: si el sesgo viene del
   brief y de la lente compartida, es exactamente lo que se esperaría de ambas.** No puedo distinguirlo desde dentro.
5. **Todo el Tier A de ambos pases descansa en fuentes interesadas.** Vendors de compliance y despachos que venden
   precisamente el servicio (Sedric, Truli, Resolver, Datashake, BrandShield, AuditSocials). El primer pase ya lo
   declaró y lo repito porque aplica a mis filas igual: **la abundancia de vendors escribiendo sobre esto es señal de
   mercado servido, no de whitespace.** Primera tarea de cualquier deep-dive: `competitor-profiling`, antes de dolor.
6. **Aplicar E2 retroactivamente a las filas del primer pase**, que no disponía del criterio. Ver §3.5. Un nicho cuyo
   contenido vive mayoritariamente en YouTube no es un nicho para Qualify, por alto que puntúe en todo lo demás.
7. **Coste transversal que ninguna fila puede esquivar:** **no hay Celery ni scheduler** (§3.1). Todo candidato de
   compliance implica vigilancia continua —y N-1 implica ventanas de 24 h—, así que **todos pagan esa construcción
   antes que cualquier otra cosa.** Es más limitante que la ausencia de ClickHouse.

---

## 5. Cruce de las dos pasadas — lo que solo se ve al compararlas

Escrito **después** de que ambos pases estuvieran en disco, leyendo uno contra el otro. Aporta tres cosas que ninguna de las dos pasadas podía producir sola. **Lo firma el autor del primer pase**, que es relevante para leer §5.3.

### 5.1 — Convergencia no coordinada sobre el mismo mecanismo

Las dos pasadas, por caminos que no se tocan, pusieron en primer lugar la misma estructura:

> **Una marca responde legalmente por afirmaciones que hace un tercero en video, sobre el que no tiene control y cuya existencia a menudo desconoce.**

El primer pase llegó ahí desde enforcement de FTC / FCA / TikTok Shop. El segundo llegó desde farmacovigilancia EMA/FDA y valoración de patrocinio. Dos analistas sin comunicación entre sí seleccionaron el mismo mecanismo por encima de todo lo demás.

Qué prueba y qué no, dicho con precisión porque es fácil sobrevender esto: prueba que **el mecanismo es robusto al camino de búsqueda**, lo cual descarta que sea un accidente de una consulta concreta. **No prueba demanda.** Ambas pasadas heredaron el mismo filtro de partida (mundo exterior, del post-mortem inmobiliario) y buscaron en la misma lengua. La convergencia descarta el accidente; no descarta el sesgo común. Dos instrumentos idénticos apuntando al mismo sitio coinciden aunque estén mal calibrados los dos.

### 5.2 — El primer pase ya ejecutó, sin saberlo, la validación que el segundo pedía para «sectores regulados»

> **Nota de etiquetado:** el candidato al que se refiere esta sección es la fila *"sectores regulados (alcohol,
> apuestas, finanzas) — compliance de influencers contratados"*, que el segundo pase había etiquetado `A-4` y que
> **se eliminó al deduplicar** contra la `A-2` (finfluencers) de §1. **La etiqueta `A-4` ya no designa nada.** El
> hallazgo de esta sección **se reasigna a la postura de §1** (A-1 + A-2 + A-3), que es donde vive ahora ese
> candidato. Ver la tabla de prefijos en la nota de reconciliación de §3.

En su borrador, ese candidato tenía **E1 en "débil"** y proponía como comprobación más barata:

> *"buscar acciones sancionadoras recientes de un regulador (FTC, FCA, autoridad de juego) contra una marca por contenido de un influencer contratado. Si existen y son públicas, hay un dolor con nombre y fecha; si no, el nicho es una idea bonita."*

**Existen, son públicas y tienen fecha.** La §1 las documenta: acción coordinada de nueve reguladores en abril de 2026 con 3 detenciones, cargos penales contra 9 personas y +650 solicitudes de takedown; y la FTC actuando contra suplementeras **específicamente por no monitorizar** a sus redes de afiliados.

**E1 de la postura de §1 (sectores regulados incluidos) sube de "débil" a "sí".** Es el único cambio de puntuación que produce este cruce, no costó investigación nueva, y consolida la postura de §1 en cabeza del Tier A. Salvedad que no se elimina: las fuentes de §1 son `[S]` de vendors de compliance; siguen necesitando verificación contra los comunicados primarios de FCA/FTC/ASIC. Lo que sube es E1 (¿existe la categoría?), no la confianza en las cifras concretas.

### 5.3 — Gaming: el autor de B-1 concede el método, y acepta la resolución por medición de §3.5

**Escribo esto como el autor del pase que puso gaming en Tier B**, así que no es un arbitraje entre terceros.

§3.5 plantea la discrepancia y la deja **abierta**, resoluble midiendo qué fracción de la conversación de un título vive en TikTok/IG frente a YouTube/Twitch. **Acepto esa resolución y no la sustituyo por una concesión total**, porque §3.5 tiene razón en que es una medición y no una opinión.

Lo que sí concedo, que es distinto y más importante que el veredicto sobre gaming: **puntué B-1 sin aplicar E2 en absoluto.** Medí tirón de demanda (hay contratación, hay presupuesto) e ignoré **dónde vive el contenido**, que es precisamente donde reside el foso de Qualify. Eso es la forma exacta del error T-3 del inmobiliario —demanda real, foso ausente— que este mismo rol documentó la sesión anterior y repitió aquí a los pocos minutos. **La carga de la prueba pasa a gaming:** hasta que la medición se haga, la fila se lee como **C provisional**, no como B.

La fila B-1 se conserva en §2 sin editar, con esta anotación encima. Borrarla ocultaría que el error ocurrió, y el registro del error vale más que la limpieza del documento.

**Corolario, que es el resultado más accionable de todo el cruce y coincide con la generalización de §3.5:** **E2 es el criterio más discriminante del documento, y los candidatos de §1-§2 se puntuaron sin él.** Aplicándolo ahora, cosa que §3.5 pide y que nadie había hecho todavía sobre las filas del primer pase:

| Candidato §1-§2 | ¿Pasa E2? | Lectura |
|---|---|---|
| **A-1 TikTok Shop** | **Sí, con holgura** | TikTok nativo. Es el mejor caso posible del criterio: el contenido está donde Qualify tiene ventaja de adquisición y los modelos frontera no |
| **A-3 Suplementos / CPG salud** | **Sí** | El claim se pronuncia en TikTok/IG. Reels y shorts verticales, no long-form de YouTube |
| **A-2 Finfluencers** | **Solo parcialmente** | Hay mucho finfluencer en YouTube long-form, y **esa porción no tiene foso**. Acota el candidato a la franja TikTok/IG, que es real pero más pequeña de lo que sugería su ficha |
| **B-4 Entertainment/media** | **Dudoso** | Buena parte del UGC de reacción a estrenos es YouTube. Degradar hasta comprobarlo |
| **B-5 Agencias (canal)** | **N/A** | No es un nicho de contenido; E2 no le aplica. Sigue siendo el candidato de canal más sólido |

---

## 6. RE-AUDITORÍA — los tres segmentos ya investigados

**No son candidatos nuevos y no propongo rehacer su research.** Están aquí porque el hallazgo T-7 de la sesión anterior (`docs/oportunidades-mercado-inmobiliario.md` §T-7) encontró que los tres se investigaron con **encuadre implícitamente estadounidense**, y ninguno se auditó nunca con esa pregunta. **Hasta que lo sean, no deben tratarse como validados.**

El coste es de horas y consiste en una sola pregunta por hallazgo: *¿esto sería cierto para una PYME uruguaya?* La propuesta original no era corregir los hallazgos sino **anotarles el ámbito geográfico**, que hace el sesgo visible en lugar de eliminarlo.

| Segmento | Corpus | Qué exige la re-auditoría | Estado |
|---|---|---|---|
| **Creadores / influencer marketing** | `docs/dolores-creadores-podcasters.md`, `docs/research-features-gtm.md` | Sus cifras vienen de CreatorIQ, Gigapay e Influencer Marketing Hub — **todas encuestas de mercado angloparlante**. El doc ya se autoetiqueta como "no validados de forma independiente"; falta añadirle el ámbito geográfico | **PENDIENTE.** No es mi archivo (`gtm-specialist`) |
| **Podcasters** | `docs/dolores-creadores-podcasters.md` | Mismo problema, agravado: las cifras de DAI (93,6% del revenue, IAB) y los umbrales de sponsorship (5.000-10.000 descargas) son del mercado **estadounidense de podcast advertising**, que no tiene equivalente estructural en Uruguay o Colombia | **PENDIENTE.** No es mi archivo |
| **E-commerce / social commerce** | `docs/fase0-zernio-mercado.md` y adyacentes | El que **peor** resiste: el propio doc ya contiene el material que lo pone en duda (techo de precio PYME; *"una peluquería no sabe qué es MCP"*) pero nunca cerró el círculo con el resto del corpus | **PENDIENTE.** No es mi archivo |

**Y el mismo sesgo, aplicado a este documento, en esta misma pasada:** el instrumento de ofertas de empleo del §2 es **enteramente estadounidense**, y las fuentes regulatorias del §1 son FTC/FCA/SEC — **ninguna vincula a un comprador uruguayo**. Está declarado en cada sección en vez de quedar implícito, que es la única defensa disponible cuando no se puede eliminar.

---

## 7. Ranking final de la pasada (con el cruce y **E4** ya aplicados)

> ⚠ **Reordenado dos veces el 2026-07-30. Leer §8 y §9 antes de usarlo.**
> - **§8 (Zernio / E-FOSO):** farmacovigilancia (N-1) cae del puesto 2 a C provisional, y la razón por la que estaba en el puesto 2 —encaje limpio con el disco— resultó ser el síntoma, no la virtud.
> - **§9 (E-FOSO ∧ E1):** el criterio de demanda ya existía (E1) sin etiquetar. Al aplicarlo simétricamente se descubrió que **la existencia de vendors establecidos se había puntuado con signos opuestos según de quién fuera el candidato** (§9.3). Corregido, cuatro candidatos pasan ambos filtros, no uno. **N-2 sube al puesto 2.**

| Orden | Candidato | Tier | Acción recomendada |
|---|---|---|---|
| **0** | **Fijar jurisdicción y país del comprador** | — | **Precondición, no candidato.** Horas. El Tier A entero es regulatorio, y un régimen del país equivocado ya destruyó la mejor tesis de la sesión anterior. Puntuar antes de esto es repetir el error a sabiendas |
| **1** | **La postura "marca regulada responsable de contenido ajeno en video"** — fusiona **A-1** TikTok Shop + **A-3** suplementos + **A-2** finfluencers/sectores regulados | A | **Un solo deep-dive**, no tres. Es donde convergieron dos pasadas independientes (§5.1) y donde el cruce produjo el único upgrade de evidencia (§5.2). Empezar por `competitor-profiling`: hay oferta visible (Sedric, Truli, BrandShield), y la oferta presente pesa más que la ausencia |
| **2** | **Agencias y freelances como CANAL** (B-5) | B | Único candidato con validación en el corpus propio y el único que **rompe el techo de precio** repartiendo el coste entre N clientes. Deep-dive con `gtm` |
| **3** | **Valoración de patrocinio dentro de contenido de creadores** (N-2) | A | **Subió al 2 en §9.7 y bajó al 3 en §9.8.2**, esto último por corrección de su propio autor. **Mejor demanda probada del documento** (Nielsen Sports, KORE/Hookit cobran por su output exacto) y la procedencia le sirve de **factura auditable**. Pero carga **tres lastres**: es el candidato más lejano al disco (detección de logos = capacidad de visión nueva), **no cumple E-FOSO⁺** (el creator patrocinado coopera con su propia medición), y su penalización de P3 es la mayor del Tier A (incumbente enterprise, no SaaS pequeño). **Demanda probada de una categoría que no puedes servir a este tamaño de equipo es una observación de mercado, no una oportunidad** |
| **4** | **RE-AUDITORÍA geográfica de los tres segmentos** (§6) | — | Horas, no días. Bloquea la fiabilidad de todo el corpus previo. Por riesgo evitado por hora invertida probablemente debería ir en el puesto 1 |
| — | **Farmacovigilancia sobre comentarios de canales propios** (N-1 / §3.4) | **C provisional (era el puesto 2)** | **Degradado por E4 en §8.2.** Su superficie obligatoria son comentarios en cuentas **propias**, que es exactamente el producto de inbox que Zernio vende por $1-6/cuenta/mes. Estaba en el puesto 2 por "encaje limpio con lo que existe en disco" — y eso resultó ser el síntoma del problema, no la virtud |
| — | **Franquicias** (N-3 / B-6) | **C provisional** | **Degradado por E4 en §8.3.** La autoridad contractual que reparaba el falsador de T-5 empuja el contenido hacia el lado *owned*, o sea hacia lo comprable |
| 6 | CPG/belleza (#9) | B | El de **categoría base más probada** de la lista. Es el candidato correcto si la pregunta cambia de *"¿dónde hay foso?"* a *"¿dónde hay presupuesto demostrado?"* |
| 7 | B-2 public affairs, B-4 entertainment (degradado por E2), B-7 turismo | B/C | Buen encaje técnico, mal encaje con la capacidad comercial de un fundador en solitario |
| — | **B-1 gaming** | **C provisional** | Degradado en §5.3 por no haberse puntuado contra E2. **Discrepancia abierta**: la decide la medición de §3.5 (¿qué fracción de la conversación de un título vive en TikTok/IG y no en YouTube/Twitch?) |
| — | B-8 mass tort | — | Comodín. Solo con decisión explícita del fundador: máximo presupuesto, peor encaje ético, y fenómeno específicamente estadounidense |
| — | C-1 … C-6, telecom (B-3), educación (#12) | C | Descartados con razón registrada y reversible |

### Implicación fuera de mi alcance, entregada al fundador en una línea

Si el puesto 1 sobrevive al deep-dive, **el comprador deja de ser el equipo de marketing y pasa a ser compliance/legal**, lo que mueve mensaje, canal y ancla de precio. Nombrado y entregado: el mix de canal, el CAC y el precio de Qualify están **explícitamente fuera de mi alcance** (decisión del fundador, 2026-07-29) y ningún agente los posee hoy.

### La objeción que haría yo si me contrataran para atacar este documento

Que **seis de las ocho primeras filas son compliance**, y que eso es sospechoso. La §4.4 ya lo declara para una pasada; el cruce lo empeora, porque **las dos pasadas compartían el sesgo**, así que su convergencia (§5.1) puede estar midiendo el sesgo común y no el mercado. La lectura benigna es que la información obligatoria se compra aunque no se desee, lo que resuelve limpiamente el problema de techo de precio que hundió al inmobiliario. La lectura maligna es sobreajuste al último hallazgo brillante de la sesión anterior. **No puedo distinguirlas desde dentro del método que las produjo**, y ninguna cantidad de investigación adicional del mismo tipo lo resolvería — hace falta una ronda adversarial o hablar con un comprador.

---

## 8. ⚠ E4 — el criterio que introduce el hallazgo Zernio, y que reordena el ranking

**Añadido 2026-07-30, después de cerrar §7.** Llega del arquitecto vía el lead, verificado contra la **referencia real de la API de Zernio** (volcado OpenAPI de 3,6 MB, no su web de marketing). Lo trato como el hallazgo más consecuente de la sesión porque **degrada un candidato de Tier A que dos analistas habíamos puesto en cabeza**.

### 8.1 — El hallazgo, y por qué no es una nota a pie de página

`[P]` Zernio es **owned-media únicamente**: publicación, gestión de DM/inbox y analítica sobre las cuentas conectadas del propio cliente. **Cero endpoints que lean contenido de terceros en TikTok o Instagram.** Precio **$1-6 por cuenta/mes**, e incluye el App Review de plataforma, que era la parte difícil.

Dos lecturas, y hay que sostener las dos a la vez:

1. **Buena noticia para la tesis del producto:** Zernio **no resuelve** listening de earned media a ningún precio. La tesis central de Qualify no está comprada por nadie.
2. **Mala noticia, y es la que reordena este documento:** **la adquisición de owned media ya no es un foso — es una compra de $1-6/cuenta/mes.** Lo que queda sin comprar es específicamente la **adquisición de earned media**: leer contenido de terceros en TikTok/IG.

**Consecuencia incómoda que registro porque este rol existe para decirla:** el módulo `connections`/OAuth —18 archivos, *lo más maduro del repositorio* según la verificación en disco de §3.1, el grueso del Sprint 1— es ahora **el activo menos diferenciado de Qualify**. Sigue siendo necesario (es precondición de cualquier línea de publicación o inbox, y de la ingesta first-party), pero **ha dejado de ser defendible**. No es una crítica del trabajo hecho: es un cambio en el mercado que ocurrió alrededor de él, y el error sería seguir puntuando adyacencia como si ese módulo aportara foso.

### 8.2 — E4 y E2 son el mismo criterio, y conviene fusionarlos

E2 (§3.2) preguntaba si el contenido vive fuera de YouTube. E4 pregunta si vive fuera de las cuentas propias. **Son dos instancias de una sola pregunta**, y unificarlas es más útil que mantener dos criterios:

> **E-FOSO: ¿puede un competidor adquirir este contenido sin construir lo que Qualify construye?**

Hay tres vías de escape conocidas, y cualquiera de ellas anula el foso:

| Vía de escape | Coste para el competidor | Fuente |
|---|---|---|
| El contenido está en **YouTube** | ~$0,001/vídeo — la API de Gemini ingiere URLs de YouTube directamente | `[P]` https://ai.google.dev/gemini-api/docs/video-understanding (consultado 2026-07-29) |
| El contenido está en **cuentas propias del cliente** (owned) | **$1-6/cuenta/mes** — Zernio y equivalentes, App Review incluido | `[P]` referencia OpenAPI de Zernio, verificada por el arquitecto 2026-07-30 |
| El contenido son **reseñas o web pública** | Comoditizado (Google Business Profile, TripAdvisor, Birdeye) | ya aplicado en C-6 |

**El foso solo existe en earned media sobre TikTok/Instagram.** Es una franja más estrecha de lo que este documento asumía en §1-§3, y todo candidato debe puntuarse contra ella.

### 8.3 — Aplicación: qué se cae y qué se refuerza

| Candidato | ¿Pasa E-FOSO? | Efecto |
|---|---|---|
| **A-1 TikTok Shop / afiliados** | **Sí, limpio** | Vídeos de afiliados = earned, en TikTok. No alcanzable por Zernio, no es YouTube. **Se refuerza como puesto 1** — ahora por eliminación además de por mérito |
| **A-3 Suplementos / CPG salud** | **Sí** | Vídeos de creators = earned, TikTok/IG. Se refuerza |
| **A-2 Finfluencers** | **Parcial** | Earned, pero mucho YouTube long-form (ya acotado en §5.3). Sin cambio |
| **N-2 Valoración de patrocinio** | **Sí** | Contenido de creators = earned. **Sube**, al vaciarse los puestos por encima |
| **N-1 Farmacovigilancia** | **NO** | Ver abajo. **Baja de puesto 2 a C provisional** |
| **N-3 Franquicias** | **Probablemente no** | Ver abajo. **Baja a C provisional** |

**N-1 farmacovigilancia — la caída, y es instructiva.** Su atractivo declarado era que la obligación de la EMA cubre medios digitales *"under their management or responsibility"* — contenido de terceros sobre **superficie propia**, resoluble con `connections` + `ig_comments.py`, sin scraping. Eso es, palabra por palabra, la descripción del producto de inbox que Zernio vende por $1-6/cuenta/mes.

Y hay una **tijera** que lo empeora, porque los dos filos vienen de la misma normativa: bajo la guía ICH/FDA **no existe deber de monitorización proactiva de sitios de terceros** (§3.4). Es decir: **la parte obligatoria es la comprable, y la parte defendible no es obligatoria.** El motor económico del candidato —"la ley obliga a mirar, así que no hace falta que el comprador quiera"— apunta exactamente a la superficie donde Qualify no tiene ventaja.

Lo que hay que aprender de esto va más allá del candidato: **"encaje limpio con lo que existe en disco" se usó como señal positiva y era engañoso.** N-1 encajaba limpiamente porque usaba el módulo `connections`, que es justo la pieza que acaba de confirmarse comprable. Un criterio de "qué está construido" mide **coste de construcción**, no **defendibilidad**, y los dos se movieron en direcciones opuestas aquí. No propongo retirar el criterio de verificación contra disco de §3.1 —sigue siendo correcto y necesario— sino **dejar de leerlo como evidencia de foso**.

**N-3 franquicias — la inversión.** N-3 se celebró porque la autoridad contractual del franquiciador sobre el uso de marca **repara el falsador que mató a T-5** (el broker no podía obligar a agentes independientes a conectar nada). Pero esa misma autoridad **convierte las cuentas de los franquiciados en cuentas conectables**, y por tanto el problema en uno de owned media — comprable por $1-6/cuenta/mes. **La palanca que arreglaba la instalación es la que destruye el foso.** Sobrevive solo la variante en la que el franquiciador vigila a franquiciados que **se niegan a conectar** o a cuentas locales no autorizadas: earned media, real, pero mucho más estrecha que lo que N-3 planteaba.

### 8.4 — Lo que este hallazgo NO dice

- **No dice que Zernio compita con Qualify.** Dice lo contrario: confirma que la tesis de earned media está desatendida.
- **No dice que `connections` fuera trabajo desperdiciado.** Es precondición de la ingesta first-party y de cualquier producto de publicación o inbox. Dice que **no debe contarse como foso al puntuar adyacencia**.
- **No resuelve la demanda.** E-FOSO es un criterio de defendibilidad, no de mercado. Un candidato puede pasarlo y seguir sin comprador — que es precisamente cómo R6 murió en el inmobiliario. **E-FOSO y el filtro de mundo exterior deben pasarse los dos**; este documento ahora puntúa el foso mejor que la demanda, y esa asimetría es el próximo hueco a cerrar. **→ Parcialmente cerrado en §9.1: el criterio de demanda ya existía (E1) y no estaba etiquetado como tal.**

---

## 9. Cierre del hueco de §8.4 — **E-FOSO ∧ E1**, y una asimetría que invalidaba la comparación

**Añadido 2026-07-30**, respondiendo a §3.7. Contiene el único error de puntuación que este documento se detecta a sí mismo, y su corrección **no** es la que §3.7 propone.

### 9.1 — Acepto el marco: el criterio de demanda ya existía y no estaba etiquetado

§3.7 tiene razón y esto cierra buena parte de lo que §8.4 dejaba abierto: **E1 (¿existe la categoría base?) ES el criterio de demanda.** No hacía falta inventarlo, hacía falta nombrarlo. La lectura correcta del documento es la conjunción:

> **E-FOSO ∧ E1** — ¿el contenido es difícil de adquirir? **Y** ¿el comprador ya paga por *algún* producto de información sobre el exterior?

E-FOSO sin E1 es R6 (foso sin comprador). E1 sin E-FOSO es T-3 (comprador sin foso). **Las dos muertes del inmobiliario son los dos fallos de la conjunción**, y verlo así es mejor que cualquier criterio nuevo que yo pudiera añadir.

### 9.2 — Pero la conclusión de §3.7 no sobrevive: N-2 **no** es el único que pasa ambos

§3.7 concluye que N-2 es *"el único candidato que pasa los dos"*. **Es incorrecto, y el motivo del error es más importante que el error.**

Aplicando E1 tal como está definido en §3.2 —*"¿el comprador ya paga por algún producto de información sobre el exterior?"*— a los candidatos de §1:

| Candidato | E-FOSO | E1 (según su definición literal) | Evidencia de E1 |
|---|---|---|---|
| **A-1 TikTok Shop / afiliados** | **Pasa** (earned, TikTok) | **PASA** | BrandShield, AuditSocials, ListerRank venden monitorización de afiliados **hoy, cobrando** |
| **A-3 Suplementos / CPG salud** | **Pasa** (earned, TikTok/IG) | **PASA** | Truli vende cumplimiento FTC de claims de salud e influencers **hoy, cobrando** |
| **A-2 Finfluencers** | Parcial (YouTube) | **PASA** | Sedric vende compliance de finfluencers **hoy, cobrando** |
| **N-2 Patrocinio** | **Pasa** | **PASA** | Nielsen Sports, KORE/Hookit |

**Los cuatro pasan ambos.** N-2 no es único; es uno de al menos cuatro.

### 9.3 — La causa: el mismo hecho puntuado con signos opuestos según de quién fuera el candidato

Esto es lo que hay que registrar, porque es un fallo de método y no de dato.

- En §1 y en §5.2 **yo** traté la existencia de vendors establecidos (Sedric, Truli, BrandShield, AuditSocials) como **argumento EN CONTRA** — *"mercado ya servido, y la oferta presente es evidencia más fuerte que la ausencia de oferta"*.
- En §3.4 y §3.7 **el segundo pase** trató la existencia de vendors establecidos (Nielsen, KORE) como **argumento A FAVOR** — *"categoría pagada y establecida; no es una categoría que tendríamos que crear"*.

**Es la misma clase de evidencia con el signo invertido, y la variable que determinó el signo fue de quién era el candidato.** Ninguno de los dos lo hizo de mala fe; ninguno de los dos lo vio hasta comparar.

**La resolución no es elegir un signo, es separar dos preguntas que estábamos colapsando en una:**

| Pregunta | Qué contesta un vendor establecido | Nombre |
|---|---|---|
| ¿Existe presupuesto para esta clase de información? | **Sí** — alguien cobra por ella | **E1 (demanda)** |
| ¿Queda un hueco por el que entrar? | **Empeora** — hay que desplazar a alguien | **Intensidad competitiva** (≈ P3) |

Un vendor establecido responde **afirmativamente a la primera y desfavorablemente a la segunda, siempre y en todos los casos.** Al no distinguirlas, cada analista usó la lectura que favorecía a su propio candidato. **Corregido: la existencia de vendors sube E1 y baja P3 para A-1, A-2, A-3 y N-2 por igual.** Eso deja la comparación empatada en demanda, y la decisión se traslada a P3 y a coste de construcción — donde sí se separan.

### 9.4 — Dónde sí se separan, y por qué N-2 aun así sube (por una razón distinta a la de §3.7)

Empatados en E-FOSO ∧ E1, los candidatos se ordenan por lo que **no** comparten:

- **A-1 / A-3 tienen mejor adyacencia.** El claim prohibido se **dice** en el audio → transcripción + procedencia, que existen en disco. Detectar *"esto me curó el insomnio"* es la cascada actual más un clasificador de texto.
- **N-2 tiene peor adyacencia de lo que su ficha sugiere, y §3.7 lo concede: la detección de logos NO está construida.** La cascada **describe escenas, no detecta marcas**. Eso no es configuración de detector: es una capacidad nueva de visión, con su propio golden set y su propia validación. **N-2 es el candidato con mayor distancia a lo que existe en disco de todo el Tier A** — exactamente el inverso de N-1, que era el más cercano y murió por ello.
- **N-2 tiene mejor P3 en un aspecto concreto:** su comprador (patrocinador que paga contra exposición medida) **necesita la procedencia como factura auditable**, no como higiene. Eso es más difícil de replicar con una llamada a un modelo frontera que un clasificador de claims.

**Conclusión, y difiere de §3.7:** N-2 sube, pero **no** porque sea el único que pasa ambos filtros —no lo es— sino porque **su demanda está probada con incumbentes que cobran por exactamente su output**, y porque la procedencia le da defensa donde a A-1/A-3 solo les da higiene. Sigue detrás de A-1/A-3 en coste de construcción, y esa es la variable que decide para un fundador en solitario. **Queda en el puesto 2, no en el 1.**

### 9.5 — La regla propuesta por §3.7: la respaldo, y añado la cuarta instancia

§3.7 tabula tres casos en que **un artefacto de nuestro propio método se leyó como evidencia sobre el mundo** (el esquema multi-tenant encaja con el cliente uno → PMF; tres agentes convergen → replicación; un candidato encaja con el disco → foso). La regla propuesta:

> *Ninguna propiedad de nuestro código, nuestro esquema o nuestro proceso de análisis es evidencia de mercado.*

**La respaldo sin reservas y aporto la cuarta instancia, que es la de §9.3:** *el signo que le dimos a un hecho externo quedó determinado por la autoría del candidato.* Es la misma forma —una propiedad de nuestro proceso (quién escribió qué) filtrándose en una conclusión sobre el mundo— y es la más difícil de detectar de las cuatro, porque **cada mitad era defendible en aislamiento**: solo aparece al comparar. **Corolario operativo: la única defensa observada que funcionó fue el cruce de dos analistas con candidatos propios en juego.** Ni el rigor individual ni el tiering de evidencia lo habrían pillado.

**Enrutado, no ejecutado:** esto pertenece a `.claude/compass-sage/ledger.md` como patrón de fallo de proceso con cuatro instancias, y **no es mi archivo**. Queda escrito aquí y señalado a quien lo posea.

### 9.6 — El residuo de N-3 es el mejor subproducto de la sesión, y no es un candidato

§3.7 rescata de N-3 la variante de franquiciados que **se niegan a conectar** y cuentas locales no autorizadas, y observa que ahí **OAuth es imposible por construcción**: no se obtiene consentimiento de quien está evadiendo activamente el control.

Coincido, y lo elevo por encima de su propio candidato: **es el criterio que le faltaba a E-FOSO.** E-FOSO pregunta si el contenido es difícil de adquirir. El caso más fuerte no es que sea *caro* de adquirir, sino que **el consentimiento sea inobtenible en principio** — porque entonces ninguna de las tres vías de escape (Gemini/YouTube, Zernio/owned, reseñas) existe, y no por precio sino por lógica.

> **E-FOSO⁺ (marcador de foso estructural): el foso es máximo donde el sujeto observado tiene un incentivo activo a no ser observado.** Ahí el consentimiento no es una vía más barata, es una vía inexistente, y la adquisición de earned media es la única ruta física.

Esto reordena el Tier A por una razón nueva: **A-1 y A-3 lo cumplen parcialmente y nadie lo había notado.** Un afiliado que hace un claim de salud prohibido, o un vendedor que infringe la política de TikTok Shop, **no coopera con su propia detección**. Es un foso más estructural que el de N-2, cuyo sujeto (un creator patrocinado) sí cooperaría de buen grado. **Como criterio de diseño vale más que como nicho** — es lo que §3.7 dijo, y tiene razón.

### 9.7 — Efecto neto en el ranking de §7

| Puesto | Antes | Ahora | Motivo |
|---|---|---|---|
| **1** | Postura regulada (A-1 + A-3 + A-2) | **Sin cambio** | Pasa E-FOSO ∧ E1 (§9.2), mejor adyacencia (§9.4), y cumple E-FOSO⁺ (§9.6) |
| **2** | Agencias como canal (B-5) | **N-2** → *revertido a agencias en §9.8.2* | N-2 subió aquí y volvió a bajar una sección más tarde. **El puesto 2 final es B-5** |
| **3** | RE-AUDITORÍA | **N-2 valoración de patrocinio** | Mejor demanda probada, pero tres lastres (§9.8.2). Neto: sube un puesto respecto al original, no dos |
| **4** | N-2 | **RE-AUDITORÍA geográfica** | Sin cambio de mérito, desplazado |

**Lo que NO cambia, y conviene decirlo porque cuatro secciones nuevas pueden dar sensación de progreso:** sigue sin haber **un solo comprador entrevistado**. E1 se satisface con *"existe un vendor que cobra"*, que es evidencia de que la categoría existe — **no** de que este comprador, en esta geografía, a este precio, la compre. El paso 0 de §7 (fijar jurisdicción) sigue siendo la precondición de todo, y FTC/FCA/EMA/FDA siguen sin vincular a un comprador uruguayo.

### 9.8 — Dos correcciones aceptadas de §3.7-bis, y el cierre analítico

**Última sección sustantiva de esta pasada. El motivo está en 9.8.3 y es deliberado.**

#### 9.8.1 — Había dos errores apilados, y el segundo es más barato de evitar que el primero

§3.7-bis acepta mi diagnóstico de asimetría de signo (§9.3) y **añade uno que yo no vi**: *"el único candidato que pasa los dos"* es una afirmación **comparativa**, y su autor **nunca hizo la comparación** — no corrió E1 contra A-1, A-2 ni A-3. Examinó un caso y concluyó sobre el conjunto.

**Y la crítica que hace a mi propuesta de defensa es correcta, así que la retiro como defensa principal.** Yo concluí (§9.5) que lo único que funcionó fue *el cruce de dos analistas con candidatos propios en juego*. Es cierto pero **caro y situacional**: exige dos analistas, dos candidatos rivales y una ronda de comparación. El error 2 se habría cazado con un chequeo mecánico y gratuito:

> **Regla propuesta por §3.7-bis, adoptada:** toda afirmación de la forma *"X es el único que…"* exige **enumerar los demás antes de escribirla**. Sin segundo analista, sin ronda adversarial, sin coste.

Las dos reglas son complementarias y conviene no confundir sus alcances: **la mía caza lo que la suya no puede** (el sesgo de signo, que es sustantivo y solo aparece al comparar), **pero la suya está siempre disponible y la mía no.** En una lista de comprobación, la barata va primero.

#### 9.8.2 — La corrección que §3.7-bis hace contra su propio candidato: la acepto, y baja N-2

Escribí en §9.3 que la presencia de vendors sube E1 y baja P3 **"por igual"** para los cuatro candidatos. **Es falso, y la desigualdad perjudica a N-2** — lo señala su propio autor, que es lo que le da peso:

- **N-2:** Nielsen Sports y KORE/Hookit son incumbentes **enterprise, grandes y atrincherados**, con contratos a escala de retransmisión.
- **A-1 / A-3:** BrandShield, Truli, AuditSocials son **SaaS de compliance pequeños**.

**Para un fundador en solitario, desplazar a Nielsen es prácticamente imposible; competir con un SaaS pequeño es concebible.** El contrapunto —incumbente mayor implica presupuesto probado mayor— es real pero **no compensa a este tamaño de equipo**. Corregido: **la penalización de P3 es mayor para N-2 que para A-1/A-3.**

**Efecto acumulado sobre N-2, que ahora carga tres lastres y no uno:**

| Lastre | Origen |
|---|---|
| Es el candidato **más lejano al disco** de todo el Tier A (detección de logos = capacidad de visión nueva, con su propio golden set) | §9.4 |
| **No cumple E-FOSO⁺**: un creator patrocinado **coopera** con su propia medición; su foso es circunstancial, no estructural | §9.6 |
| **Mayor penalización de P3** que A-1/A-3: incumbente enterprise, no SaaS pequeño | §9.8.2 |

**N-2 baja del puesto 2 al 3**, por detrás de agencias-como-canal (B-5). Su demanda sigue siendo la mejor probada del documento — eso no se retira — pero **la demanda probada de una categoría que no puedes servir con tu tamaño de equipo no es una oportunidad, es una observación de mercado.**

#### 9.8.3 — Cierre analítico: a partir de aquí, más análisis tiene valor esperado negativo

§3.7-bis lo plantea y **estoy de acuerdo sin reservas, así que lo hago vinculante para mi parte del documento.**

Las últimas rondas entre los dos pases han producido correcciones cada vez más finas —signo de la evidencia, unicidad de una afirmación, gradación de P3— **sobre una base que no ha cambiado en toda la sesión: cero compradores entrevistados.** E1 se satisface con *"existe un vendor que cobra"*. Eso evidencia que **la categoría** existe; no que **este** comprador, en **esta** geografía, a **este** precio, la compre.

**El siguiente incremento de información no está en este documento ni en otra ronda entre analistas. Está en una conversación con el cliente que ya paga**, y en fijar la jurisdicción (paso 0 de §7). Cualquier sección adicional que escribamos aquí refina el orden de una cola cuya premisa sigue sin verificar — que es, en versión más elegante, el mismo error que este documento lleva nueve secciones diagnosticando: **preferir el artefacto que controlamos a la evidencia que hay que ir a buscar fuera.**

**Recomendación explícita: congelar el análisis en este punto.** El documento está en un estado utilizable para decidir a qué nicho dedicar el próximo deep-dive; no mejorará por escritura adicional.

