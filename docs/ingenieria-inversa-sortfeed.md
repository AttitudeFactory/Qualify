# Ingeniería inversa de Sort Feed — qué robar para Qualify

**Pregunta que responde:** Sort Feed (`sortfeed.com`) es una **extensión de Chrome** que se monta
sobre Instagram / TikTok / YouTube / Facebook y convierte el feed público de cualquier perfil en
datos ordenables, exportables, descargables y transcribibles. ¿Qué de eso es implementable en
Qualify, en qué fase cae, y qué relación tiene su *mecanismo de acceso a datos* (sesión del
navegador del propio usuario) con el plano de datos de Qualify (scraping server-side vía Zyte)?

**Método:** investigación de escritorio con web en vivo, **2026-07-24**. Fechas de acceso indicadas
por fila/sección. Autor: agente `gtm-specialist`.

**Qué NO es Sort Feed (verificado, no asumido):** no es un scheduler de publicación, no es un
social inbox, no es una herramienta de DM automation ni de outreach. No tiene API pública. No es un
SaaS server-side con dashboards persistentes. Es una **capa de investigación client-side**: todo
ocurre en el navegador del usuario, sobre las páginas que ese usuario ya está mirando, usando su
propia sesión iniciada. Esto lo sitúa en la **mitad de escucha/research** del producto (no en la de
activación), y por eso el contraste con el teardown de ManyChat es casi perfecto: ManyChat era
activación (casi todo 🔴 para Qualify); Sort Feed es research sobre medios ganados (casi todo 🟢).

**Tesis que este documento intenta *refutar*, no confirmar:** que Sort Feed valida y solapa con el
núcleo de Qualify hasta el punto de ser competencia relevante. Ver §4 (campo competitivo) y §5
(screen owned-vs-earned) — los hallazgos que socavan tanto "esto es competencia" como "esto es
robable tal cual" van marcados explícitamente.

## Nota de calidad de fuentes

Mismo esquema que `docs/ingenieria-inversa-manychat.md` y `docs/fase0-zernio-mercado.md`:

- **[P] Primaria** — el sitio oficial de Sort Feed (`sortfeed.com`, su listing en Chrome Web Store,
  sus páginas de precios/términos). Única evidencia con la que se hacen afirmaciones fuertes.
- **[S] Secundaria interesada** — reviews de directorios de herramientas (coldiq, pulsrev,
  funblocks, Product Hunt). Pista, nunca prueba; a menudo desactualizadas.
- **[T] Terciaria neutral** — comparativas sin producto en juego.

**Aviso de acceso:** a diferencia de ManyChat, `sortfeed.com` y el Chrome Web Store **sí responden**
a cliente no-navegador, así que las §1 y §3 salen de fuente primaria directa. La discrepancia de
pricing entre la página oficial y los directorios (§3.3) es real y está documentada, no es error de
lectura.

---

## 1. Inventario de features (G1)

**Fuente base:** página oficial `sortfeed.com` [P] y listing oficial en Chrome Web Store [P],
ambos accedidos **2026-07-24**. Métricas del listing: **~80.000 usuarios**, **rating 3,3/5**
(278 valoraciones), **versión 13.1**, tamaño 1,13 MiB.

### 1.1 Plataformas soportadas [P]

| Plataforma | Alcance declarado |
|---|---|
| Instagram | Reels, Posts, Stories; perfiles, resultados de búsqueda, colecciones, guardados, favoritos, "me gusta" |
| TikTok | Vídeos de perfil, búsqueda |
| YouTube | Contenido de canal (añadido en versiones recientes) |
| Facebook | Facebook Reels |

Las dos plataformas centrales de la tesis de Qualify (TikTok e Instagram Reels) están cubiertas por
Sort Feed **y encima le añade YouTube**, un canal que Qualify hoy no contempla en Fase 1.

### 1.2 Funciones núcleo [P] (acceso 2026-07-24)

| # | Feature | Qué hace | Free/Pro |
|---|---|---|---|
| 1 | **Ordenar feed por métrica** | Ordena Reels/Posts/TikToks de un perfil por views, likes, comentarios, shares, fecha | Free (limitado) |
| 2 | **Outlier score** | Ordena por "outlier score": detecta el contenido que rompió la línea base del creador ("top 1% outliers in any niche", "surface winners", "actual breakout videos") | Free/Pro |
| 3 | **Filtro por rango/conteo** | Filtra por rango de fechas o por número de posts personalizado | Rango custom = **Pro** |
| 4 | **Pull structured data** | Extrae métricas de engagement estructuradas, listas para análisis | Free/Pro |
| 5 | **Read viral hooks** | Identifica "stopping points" / ganchos de los vídeos | Pro |
| 6 | **Track performance trends** | Monitoriza la evolución del rendimiento del contenido en el tiempo | Pro |
| 7 | **Export a hoja de cálculo** | Exporta a Google Sheets (1 clic), Excel, CSV o JSON | Free (export básico) |
| 8 | **Descarga sin marca de agua** | Descarga Reels, Posts, TikToks y Stories sin watermark, en bloque ("bulk download in one action") | Free (descargas ilimitadas declaradas) |
| 9 | **Transcripción en bloque** | Transcribe vídeos a texto en una pasada y exporta transcripts junto a los datos | **Pro**, tope **500 min/mes** |

**Lectura de G1 (lo que el inventario revela sobre la forma del producto):**

1. **Sort Feed es exactamente el trozo de Qualify que va de "leer el feed de un creador" a
   "ordenarlo por rendimiento y transcribirlo" — pero hecho a mano, perfil a perfil, sin corpus
   persistente.** Ordenar por outlier + exportar métricas + transcribir es, casi literalmente, el
   valor de la Fase 1 (ingesta + transcripción) más un pedazo de la Fase 4 (scoring de creators).
   La diferencia no está en *qué* datos toca, sino en *cómo*: el operador abre un perfil, pulsa un
   botón, obtiene el resultado y se lo lleva a una hoja. No hay monitorización continua, ni
   alertas, ni escucha cross-cuenta, ni sentiment, ni análisis del comentario.
2. **El "outlier score" es la mejor idea de producto del catálogo.** No es "ordena por views"; es
   "ordena por cuánto se salió este post de la línea base *de este creador*". Es una normalización
   por baseline que convierte un número absoluto (views) en una señal comparable entre creators de
   distinto tamaño. Es una primitiva de señal, no una feature de UI (ver §5.3).
3. **No hay una sola feature de activación, ni de comentario, ni de sentiment.** Sort Feed lee el
   *post* (métricas + vídeo + transcript), no la *conversación* (comentarios). No mira dentro del
   comentario ni clasifica intención ni sentiment. Su "visual/audio listening" se limita a
   transcribir; no describe el vídeo (nada de VLM). Es un análisis de **rendimiento del contenido**,
   no de **la conversación sobre la marca**. Esa es la línea que lo separa de Qualify.
4. **La transcripción está gateada y medida** (500 min/mes en Pro): es la única función con coste
   marginal real (ASR de terceros), y Sort Feed lo trata como cupo, no como crédito. Dato para
   Fase 5 (§3).

## 2. Matriz de acceso a datos (G2)

En el teardown de ManyChat, la §2 preguntaba por el *gating de las APIs de mensajería* (App Review,
Business Verification, ventana de 24 h). Para Sort Feed la pregunta equivalente es distinta y más
directamente relevante para la Fase 1 de Qualify: **¿cómo accede Sort Feed a los datos, y qué dice
ese mecanismo sobre la elección de arquitectura de ingesta de Qualify (extensión client-side vs
scraping server-side vía Zyte)?**

### 2.1 Cómo accede Sort Feed a los datos [P] (acceso 2026-07-24)

Sort Feed **no usa ninguna API oficial de plataforma y no pide OAuth**. Se describe como una
"enhancement layer directly on top of Instagram and TikTok": corre como content-script en el
navegador del usuario, sobre las páginas que ese usuario ya está viendo, **con la sesión iniciada
del propio usuario**. Lee la hidratación/DOM de perfiles públicos, ordena en cliente y ofrece
export/descarga/transcripción. Puntos verificados en sus Términos [P, `sortfeed.com/terms`,
acceso 2026-07-24]:

- **"Some features of Sort Feed require account registration"** (`account.sortfeed.com`) — la
  transcripción y el tope de 500 min/mes exigen cuenta Sort Feed, lo que implica **infraestructura
  server-side propia** para esa parte (no todo es local).
- Advertencia explícita de fragilidad: **"Platform functionality, page structures, or API
  behaviors may change without notice, which can affect how Sort Feed operates"** — confirma que el
  acceso depende de la estructura de página de la plataforma (scraping de DOM/hidratación), no de un
  contrato de API estable.
- Cláusula que traslada el riesgo de ToS al usuario: prohíbe usar Sort Feed para **"scrape, harvest,
  or systematically collect data from Instagram or TikTok at a scale or in a manner that violates
  their respective Terms of Service"**. Es decir: el vendor sabe que lo que hace roza la línea de
  ToS de la plataforma y la sortea contractualmente empujando la responsabilidad al operador.

### 2.2 El hallazgo central: Sort Feed es "scraping con las manos del usuario"

| Dimensión | Sort Feed (extensión client-side) | Qualify (scraping server-side vía Zyte) |
|---|---|---|
| Sesión usada | La sesión logueada del **propio operador** | Sesiones/proxies gestionados por Zyte |
| Coste de acceso | **~0 marginal** (usa el ancho de banda y la IP del usuario) | Coste por request de Zyte + proxies |
| Anti-bot / bloqueo | Lo absorbe el navegador real del usuario (huella legítima) | Zyte gestiona rotación + CAPTCHAs |
| Escala | **Manual, por perfil, por sesión.** No hay monitorización continua | Continua, programada, N cuentas/hashtags |
| Persistencia | Efímera: exporta a una hoja y se acaba. No hay corpus | ClickHouse persistente, re-consultable, con FTS y embeddings |
| Riesgo de ToS | **Sobre el usuario** (bloqueo/baneo de *su* cuenta) | Sobre Qualify/Zyte (bloqueo de IP, no de cuenta de cliente) |
| Multimodal | Solo transcripción (ASR) | Filtro CLIP + VLM (descripción visual) + ASR + sentiment |

**Lectura para Qualify, y es la más importante de la sección:** Sort Feed demuestra que existe una
**tercera vía de acceso a medios ganados** que la `docs/alternativas-fase1.md` no evalúa —
**la extensión de navegador que usa la sesión del propio operador** — y que esa vía tiene una
propiedad económica notable: **coste de acceso ~0 y huella anti-bot legítima**, porque es un humano
real navegando. Pero tiene tres límites estructurales que la descalifican como *columna vertebral*
de la ingesta de Qualify:

1. **No escala a monitorización continua.** El modelo entero de Qualify (Fase 2: queries guardadas +
   scheduler; Fase 3: alertas) exige ingesta desatendida 24/7. Una extensión requiere que un humano
   tenga el navegador abierto en la página correcta. Es research puntual, no listening.
2. **No construye corpus.** Sin ClickHouse persistente no hay share of voice, ni evolución temporal,
   ni embeddings, ni re-consulta. Sort Feed entrega un CSV y olvida.
3. **Traslada el riesgo de baneo a la cuenta del operador.** Aceptable para una herramienta de
   research individual; inaceptable como infraestructura de un SaaS multi-tenant.

**Corolario, y contradice cualquier impulso de "hagamos una extensión en vez de pagar Zyte":** la
extensión client-side **no sustituye** a la ingesta server-side de Fase 1; resuelve un caso de uso
*distinto* (research asistido puntual con la sesión del propio usuario). Podría, eso sí, ser un
**complemento** de bajo coste para el operador de medios propios (dogfooding, Parte 4) o una
superficie de captación (§6). No es un plan B de Zyte.

### 2.3 Matriz feature → mecanismo → gate

| Feature de Sort Feed | Mecanismo real | ¿Gate de plataforma? | Nota |
|---|---|---|---|
| Ordenar por métrica / outlier | Lee hidratación pública del feed en cliente | No (contenido público) | Frágil ante cambios de DOM |
| Export estructurado | Serializa lo leído a Sheets/CSV/JSON | No | Trivial una vez tienes el dato |
| Descarga sin watermark | Resuelve la URL del media y la baja | Zona gris de ToS del media | Riesgo trasladado al usuario |
| Transcripción en bloque | Sube audio a **backend propio de Sort Feed** → ASR | No de plataforma, sí cuenta Sort Feed | Coste marginal real (500 min/mes) |
| Read viral hooks | Heurística sobre el vídeo/transcript | No | Poco especificado; probable derivado del transcript |

## 3. Pricing y packaging (G3)

### 3.1 Tabla de planes (página oficial, acceso 2026-07-24) [P]

| Plan | Precio | Qué incluye |
|---|---|---|
| **Free** | $0 | Ordenar los **últimos 25 posts o 1 semana**; export de datos; descargas ilimitadas |
| **Pro (mensual)** | **$14/mes** | Ordenación ilimitada, rangos custom, export completo, transcripción (500 min/mes) |
| **Pro (anual)** | **$9/mes** facturado al año (~$108/año) | Mismas features que Pro mensual |

Fuente: `sortfeed.com` [P, acceso 2026-07-24]. El tope de transcripción (500 min/mes) es el único
límite medido del plan Pro; el resto es "ilimitado".

### 3.2 Qué copiar del packaging — el patrón "el research básico es gratis, el volumen se paga"

El gate del Free de Sort Feed es **inteligente y directamente robable**: el corte no es por feature
sino por **profundidad de ventana** — "los últimos 25 posts o 1 semana". Deja probar el valor real
(ordenar, ver el outlier, exportar) sobre una muestra pequeña, y cobra por **quitar el límite de
ventana** y por **la transcripción** (lo único con coste marginal). Tres propiedades trasladables:

| Propiedad de Sort Feed | Qué resuelve | Correspondencia con Qualify |
|---|---|---|
| Free limitado por **ventana** (25 posts / 1 semana), no por feature | El usuario ve el valor completo sobre una muestra antes de pagar | Encaja con un free/trial de listening: "analiza 1 perfil, últimos 25 posts" sin tocar el motor |
| Lo **ilimitado** (ordenar/exportar) es lo de **coste ~0**; lo **medido** (transcripción) es lo de **coste marginal real** | El pricing sigue el coste, no la percepción | Regla directa para P5-1: medir solo lo que cuesta ASR/VLM/enrichment; no medir lo barato |
| Transcripción como **cupo mensual** (500 min), no como crédito consumible con excedente | Predecibilidad total; sin "credit burn" | Alternativa al modelo de crédito de Clay que P5-1 teme (§3.3) |

### 3.3 Contradicción de pricing detectada (dato, no error)

La fuente [S] `coldiq.com/tools/sort-feed` (acceso 2026-07-24) afirma que Pro es **"$39.99 pago
único, acceso de por vida"**. La página oficial [P] dice **suscripción $14/mes o $9/mes anual**.
No cuadran. Interpretación: los directorios de herramientas van desactualizados o mezclan una
oferta lifetime antigua (típica en extensiones en su fase de lanzamiento) con el modelo de
suscripción actual. **Tomo el sitio oficial [P] como verdad** y registro la cifra de coldiq como
[S] no verificada. Lección de método: en herramientas indie de ciclo rápido, los reviews de
directorio caducan en meses; solo la página del vendor cuenta.

### 3.4 Lo que el pricing revela sobre el negocio

Es un producto **PLG de bajo ticket** (self-serve, $9–14/mes, 80.000 usuarios, sin tocar ventas).
No compite en el mercado que persigue Qualify (marketing/growth teams con presupuesto de SaaS de
listening); compite en el de **creators individuales y editores de contenido** que quieren ideas
virales. Eso importa para §4: **Sort Feed no es competidor de Qualify, es competidor del cuaderno
de research manual de un creator.** El solapamiento es de *capacidad* (leer+ordenar+transcribir un
feed), no de *mercado*.

## 4. Campo competitivo (G4)

### 4.1 Dónde se sitúa Sort Feed

| Eje | Sort Feed | Qualify |
|---|---|---|
| Forma | Extensión Chrome, client-side | SaaS server-side + pipeline propio |
| Motion | Research manual asistido | Listening continuo → activación GTM |
| Unidad de análisis | El **post/creador** (rendimiento del contenido) | La **conversación de marca** (post + comentario + vídeo + audio) |
| Comprador | Creator individual / editor de contenido | Marketing/growth/community de marca |
| Ticket | $9–14/mes | (Fase 5) SaaS con crédito/asiento |
| Persistencia | Nula (CSV y olvida) | ClickHouse + FTS + embeddings |
| Multimodal | Solo ASR | CLIP + VLM + ASR + sentiment |
| Cross-cuenta | No (perfil a perfil) | Sí (share of voice, competencia) |
| Sentiment / comentarios | No | Sí (robertuito + zero-shot) |
| Alertas / crisis | No | Sí (Fase 3) |

### 4.2 Competidores adyacentes de Sort Feed [S] (acceso 2026-07-24)

Los directorios listan como alternativas a Taplio ($39, LinkedIn), Scripe ($19,99), BuzzSumo ($199)
y "I Love My CRM" ($97) — un conjunto **incoherente** que confirma que ningún agregador sabe bien
en qué categoría meter a Sort Feed. El vecindario real de Sort Feed son otras **extensiones de
research de contenido**: herramientas que ordenan el feed de un competidor por outlier y descargan
el vídeo. Es una categoría de utilidades ligeras, no de plataformas.

### 4.3 Dónde gana Sort Feed — y por qué Qualify no debe atacarlo ahí

Gana en **fricción cero y coste cero de acceso**: cero infra, cero proxy, cero OAuth; el operador
ya está logueado, pulsa un botón sobre el perfil que está mirando y tiene el CSV. Para el caso de
uso "estoy investigando a ESTE creador AHORA", Sort Feed es imbatible en time-to-value, y Qualify
—con su pipeline server-side— nunca será tan inmediato para ese uso puntual. **No hay que competir
en ese terreno.** Qualify gana en lo que Sort Feed estructuralmente no puede: continuidad, corpus,
cross-cuenta, comentario/sentiment, multimodal profundo y activación.

### 4.4 Lo que un listening-first sí debe tomar de Sort Feed

Sort Feed comparte el punto ciego de casi todo el mercado (no mira el comentario ni el sentiment ni
activa), pero ha resuelto **excepcionalmente bien dos cosas que Qualify va a necesitar igual**:

1. **La normalización por baseline (outlier score).** Ordenar por views absolutas es ruido; ordenar
   por "cuánto se salió este post de la mediana del creador" es señal. Qualify necesita exactamente
   esta primitiva para scoring de creators (Fase 4) y para detección de picos/breakouts (Fase 3).
2. **La transcripción como feature de research de primera clase, no como paso interno.** Sort Feed
   pone el transcript en manos del usuario (exportable, buscable). Qualify ya transcribe en Fase 1;
   lo que Sort Feed enseña es que **exponer el transcript al usuario final es en sí una feature de
   valor**, no solo un insumo del índice FTS.

## 5. Screen owned-vs-earned (G5)

**Criterio del screen.** Para cada feature de Sort Feed: ¿se puede construir sobre el plano de datos
de Qualify (contenido público scrapeado de cuentas ajenas → ClickHouse), o exige OAuth/propiedad de
la cuenta?

- **🟢 Alcanzable** — no depende de poseer ninguna cuenta.
- **🟡 Alcanzable solo con OAuth del cliente** — requiere la cuenta del cliente.
- **🔴 Estructuralmente inalcanzable** — requiere propiedad de cuenta o gate de plataforma.

### 5.1 La tabla

| # | Feature de Sort Feed | Veredicto | Por qué |
|---|---|---|---|
| 1 | Ordenar feed por views/likes/comments/shares/fecha | 🟢 | Métricas públicas del feed; Qualify ya las ingiere a ClickHouse. Ordenar es SQL |
| 2 | **Outlier score** (normalización por baseline del creador) | 🟢 | Se computa sobre el histórico scrapeado del creador. **Es más potente en Qualify**: baseline sobre corpus persistente, no sobre la ventana que el usuario alcanzó a cargar |
| 3 | Filtro por rango de fechas / conteo | 🟢 | `WHERE posted_date BETWEEN ...`. Trivial sobre `ingestion.*` |
| 4 | Pull structured data (métricas de engagement) | 🟢 | Es el output nativo del parser de Fase 1 |
| 5 | Read viral hooks | 🟢 | Derivable de transcript + primeros segundos; encaja con VLM/ASR de Fase 1 |
| 6 | Track performance trends (evolución temporal) | 🟢 | ClickHouse es una base de series temporales; es su terreno |
| 7 | Export a Google Sheets / CSV / JSON | 🟢 | Serialización de una query. Sin gate |
| 8 | **Descarga de vídeo sin watermark, en bloque** | 🟡 | Técnicamente 🟢 (Qualify ya guarda artefactos en R2), pero es **zona gris de ToS del media** y de dudoso encaje en un SaaS de marca. Exponerlo como feature tiene riesgo reputacional/legal que Sort Feed traslada al usuario y Qualify no podría |
| 9 | **Transcripción en bloque + export de transcript** | 🟢 | Fase 1 ya lo hace (`whisper-large-v3-turbo`). Exponer el transcript al usuario es la parte robable |
| 10 | Trabajar sobre "saved / favorites / liked" del propio usuario | 🔴 | Esos contextos son la **sesión privada del usuario**; requieren su login. Fuera del plano de medios ganados de Qualify |

**Recuento: 8 🟢 · 1 🟡 · 1 🔴 sobre 10.** El espejo exacto de ManyChat (que era 11 🔴 · 5 🟡 · 7 🟢).

### 5.2 El hallazgo — la tesis del brief se **confirma por inversión**

Se pidió intentar refutar que Sort Feed sea competencia relevante y que sus features sean robables.
El resultado es doble y limpio:

> **Sort Feed vive dentro del plano de datos de Qualify (casi todo 🟢), justo al revés que ManyChat
> (casi todo 🔴). Pero eso mismo prueba que Sort Feed *no es competencia de plataforma*: es un
> subconjunto client-side de la Fase 1 + un pedazo de la Fase 4, sin corpus, sin continuidad y sin
> la mitad de activación.**

Dicho de otra forma: **lo que Sort Feed hace, Qualify lo hará como efecto colateral de tener la
Fase 1 + Fase 4 construidas.** No hay que "robar" a Sort Feed casi nada nuevo; hay que constatar
que su producto entero es una *vista* sobre datos que Qualify va a tener de todos modos. El único
aprendizaje genuinamente nuevo es el **outlier score** (una fórmula de normalización) y la decisión
de **exponer transcript/export al usuario final** como feature, no como plomería.

Y el contrapeso honesto: **Sort Feed gana en un eje donde Qualify perderá siempre — el research
puntual de fricción cero.** Si el buyer solo quiere "mira este perfil ahora mismo", la extensión es
superior. Qualify no debe intentar ser una extensión; debe asegurarse de que su valor (continuidad,
corpus, comentario, activación) sea lo bastante grande para justificar el salto de una utilidad de
$9/mes a un SaaS.

### 5.3 Dónde la primitiva de Sort Feed se vuelve *más* potente con el plano de Qualify

1. **Outlier score sobre corpus persistente, no sobre ventana cargada.** Sort Feed calcula el
   outlier sobre los posts que el usuario alcanzó a scrollear en esa sesión — una muestra sesgada
   por lo que la página cargó. Qualify lo calcularía sobre el **histórico completo** del creador en
   ClickHouse: baseline estable, comparabilidad entre creators, y detección de breakout *en el
   momento en que ocurre* (Fase 3), no cuando alguien abre el perfil. → **Fase 3/4**.
2. **Transcript como activo consultable, no como export de una sesión.** Sort Feed te da el
   transcript de los vídeos que miraste. Qualify indexa el transcript de **toda la categoría** en
   `search.content_index` con FTS: "búscame la frase X dentro de cualquier vídeo de cualquier
   competidor". Mismo insumo (ASR), dos órdenes de magnitud más de alcance. → **Fase 1/2**.
3. **"Viral hooks" sobre corpus de categoría → biblioteca de hooks que funcionan.** En vez de leer
   el hook de un vídeo, agregar los hooks de los outliers de un nicho entero es un insight de
   estrategia de contenido que ninguna extensión puede dar. → **Fase 3** (señales) / **Fase 2**
   (insights).

## 6. Recomendación (G6)

### 6.1 Veredicto general

**Sort Feed NO es un competidor de plataforma de Qualify ni una amenaza de mercado** — es un
producto PLG de bajo ticket para creators individuales cuyo alcance de capacidad es un subconjunto
client-side de la Fase 1 + Fase 4 de Qualify. **No cambia ninguna decisión de vendor ni de
arquitectura de Fase 1.**

**Tres cosas concretas sí valen la pena:**

1. **Robar el `outlier score`** como primitiva de scoring/señal (no depende del canal, es una
   fórmula, encaja en Fase 3/4).
2. **Exponer transcript + export** al usuario final como feature de research, no solo como plomería
   del índice (Fase 1/2).
3. **Registrar la "extensión de navegador con sesión del operador" como vía de acceso conocida** —
   no como columna vertebral de ingesta (no escala, no persiste, traslada el baneo al usuario), sino
   como posible complemento de dogfooding (Parte 4) o superficie de captación PLG. Decisión de
   arquitecto, no de GTM.

**NO-GO claros:** descarga de vídeo sin watermark como feature de producto (riesgo ToS/reputacional
que un SaaS de marca no puede trasladar al usuario como hace Sort Feed); y sustituir Zyte por una
extensión (categoría de error, §2.2).

### 6.2 Rutas de conflicto para el architect

1. **No toca ninguna ADR de Fase 1.** Zyte, EnsembleData, Groq, los checkpoints multimodales —
   nada se mueve. Sort Feed solo añade un dato de contexto: existe una tercera vía de acceso
   (extensión client-side) que `docs/alternativas-fase1.md` no evaluó, con perfil de coste distinto
   pero no apta como backbone.
2. **Aporta insumo a Fase 3/4.** El `outlier score` (normalización por baseline) debería entrar en
   el diseño de scoring de creators y de detección de breakouts como primitiva concreta.
3. **Aporta matiz de packaging a P5-1.** El corte Free-por-ventana y "mide solo lo que cuesta
   (ASR/VLM), deja ilimitado lo barato" es un patrón limpio, coherente con las conclusiones de la
   §3.2 del teardown de ManyChat.

### 6.3 Preguntas abiertas que esta investigación no cerró

- **Motor de transcripción de Sort Feed:** no verificado qué ASR usa ni a qué coste; solo consta el
  cupo de 500 min/mes y que exige cuenta (backend propio).
- **Fórmula exacta del outlier score:** el sitio la describe cualitativamente ("top 1% outliers",
  "breakout relative to baseline") pero no publica la fórmula. Se asume normalización por mediana
  del creador; **no verificado**.
- **Historia del pricing lifetime ($39,99):** discrepancia [S] coldiq vs [P] sitio oficial sin
  resolver; probablemente oferta antigua caducada.
- **Alcance real en YouTube y Facebook:** listado como soportado pero no probado en esta pasada.
- **Riesgo de baneo real para el usuario:** los Términos lo insinúan al prohibir "systematic
  collection at scale"; no hay dato de tasa de baneo real de cuentas de usuarios de Sort Feed.

## Notas de metodología

Investigación de escritorio con web en vivo, **2026-07-24**. A diferencia de ManyChat,
`sortfeed.com` y el Chrome Web Store respondieron a cliente no-navegador, así que §1 y §3 salen de
fuente primaria directa. Las quejas/alternativas de §4.2 vienen de directorios de herramientas [S]
con incentivo en el SEO de comparación y a menudo desactualizados (ver la discrepancia de pricing
§3.3): van etiquetadas [S]. Ningún precio ha sido validado con el vendor. La descripción del
mecanismo técnico (§2) se infiere de los Términos oficiales y de la descripción del producto [P],
no de ingeniería inversa del código de la extensión.

---

## Candidatos a parking lot

Features de Sort Feed que valen como candidatas de roadmap para Qualify. Para cargar a Linear.

| # | Nombre corto | Fase | Veredicto | Justificación (1 línea) |
|---|---|---|---|---|
| 1 | **Outlier score** (normalización de rendimiento por baseline del creador) | 4 | **GO** | Convierte views absolutas en señal comparable entre creators; primitiva directa para scoring de creators. |
| 2 | **Breakout/outlier alert** (alerta cuando un post de un creador rompe su baseline) | 3 | **GO** | El outlier score computado en continuo sobre el corpus es una alerta de Fase 3 que ninguna extensión puede dar. |
| 3 | **Transcript export/search para el usuario** (transcript como feature, no plomería) | 2 | **GO** | Fase 1 ya transcribe; exponerlo buscable/exportable al usuario es valor extra a coste casi nulo. |
| 4 | **Feed sort/export de un perfil** (ordenar+exportar métricas de un creador) | 4 | **GO** | Cae solo al tener Fase 1 + CRM de creators; vista sobre datos que Qualify ya tendrá. |
| 5 | **Viral hooks library** (agregar hooks de los outliers de un nicho) | 3 | **GO-WITH-CHANGES** | Insight de estrategia de contenido potente, pero exige definir "hook" y validar utilidad; no es Fase 1. |
| 6 | **Free gate por ventana** (25 posts / 1 semana en el tier gratis) | 5 | **GO-WITH-CHANGES** | Buen patrón de packaging PLG; el ajuste es alinear la ventana con el coste real de ingesta multimodal. |
| 7 | **Extensión client-side con sesión del operador** (vía de acceso a datos) | 1 | **GO-WITH-CHANGES** | Válida como complemento de dogfooding/captación, NO como backbone de ingesta; decisión de arquitecto. |
| 8 | **Descarga de vídeo sin watermark** como feature de producto | — | **NO-GO** | Zona gris de ToS que Sort Feed traslada al usuario; un SaaS de marca no puede asumir ese riesgo. |
| 9 | **Soporte YouTube** en la ingesta | 4 | **GO-WITH-CHANGES** | Sort Feed cubre YouTube; adyacencia razonable pero fuera del alcance TikTok/IG de Fase 1. |
