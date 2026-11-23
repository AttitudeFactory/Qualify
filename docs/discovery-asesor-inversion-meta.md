[DISCOVERY 2026-11-22 · épica m-25091361 · sin código de producto]

# Asesor de inversión en anuncios Meta — qué dice la documentación oficial (2026-11-22)

Autor: principal-architect (investigación de solo lectura; sin código, sin PR, sin ticket).
Etiquetas: **[V]** verificado con URL oficial (acceso 2026-11-22) · **[H]** hipótesis · **no documentado**.
Código contrastado: `packages/api/src/qualify_api/ads/` (client.py, results.py, live_management.py,
messaging_attribution.py, audience_service.py, live_wizard.py).

Estado: completo. Limitación: los artículos del Servicio de ayuda de Meta (facebook.com/business/help)
se renderizan con JavaScript y no se pudieron leer; sus citas quedan como [S] (vía buscador).

## 1. Tamaño de mercado: reachestimate vs delivery_estimate

**Hallazgo principal: la curva gasto→resultados ya no existe.** [V] El changelog de Marketing API
v26.0 dice que `daily_outcomes_curve`, `budget_guardrail` y `estimate_dau` se eliminan de
`GET /{ad-account-id}/delivery_estimate` y `GET /{adset-id}/delivery_estimate`; «These fields
currently return hardcoded `0` or empty data», dependían de un backend ya retirado, aplica a v26+
desde 2026-07-29 y **a todas las versiones desde 2026-10-27**, sin reemplazo.
https://developers.facebook.com/documentation/ads-commerce/marketing-api/marketing-api-changelog/version26.0
y https://developers.facebook.com/blog/post/2026/07/29/introducing-graph-api-v26-and-marketing-api-v26/

- **`act_<id>/reachestimate`** [V] — `targeting_spec` obligatorio («`countries` is required»),
  `object_store_url` opcional. Devuelve un rango: `users_lower_bound` y `users_upper_bound`;
  «When unavailable, the endpoint returns -1». Sin campo de gasto ni de resultados.
  https://developers.facebook.com/docs/marketing-api/reference/ad-account/reachestimate/
  Ya lo usamos: `ads/audience_service.py:147` y el parseo en `ads/audience.py:344`.
- **`act_<id>/delivery_estimate`** [V] — `optimization_goal` y `targeting_spec` obligatorios,
  `promoted_object` opcional. https://developers.facebook.com/docs/marketing-api/reference/ad-account/delivery_estimate/
- **`<adset_id>/delivery_estimate`** [V] — todos los parámetros opcionales (toma los del conjunto).
  https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/delivery_estimate/
  El nodo `AdCampaignDeliveryEstimate` hoy documenta solo `estimate_mau_lower_bound`,
  `estimate_mau_upper_bound`, `estimate_ready` y `targeting_optimization_types`.
  https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-delivery-estimate/
- **Qué queda útil:** un **tamaño de audiencia (rango de personas activas al mes)** para la
  segmentación elegida, y `estimate_ready` para audiencias que aún se están llenando. Sirve para
  «tu zona tiene entre X y Y personas», **no** para «con $N llegarás a Z personas/día».
- **Permisos:** ninguna de las dos páginas nombra el permiso; solo el error 200 [V]. Por el resto de
  Marketing API, una lectura de cuenta publicitaria pide `ads_read` o `ads_management` [H, ver §12].
- **Código:** nada en el repo lee `daily_outcomes_curve` ni `estimate_dau` (grep 2026-11-22) — no
  hay nada que romper, pero **ningún diseño debe apoyarse en esa curva**.

## 2. Presupuestos mínimos (minimum_budgets)

- [V] `GET act_<id>/minimum_budgets`, único parámetro `bid_amount` («if you want to get values for
  manual bid»). Descripción: «The minimum daily budget value for an ad set in an Auction campaign».
  https://developers.facebook.com/docs/marketing-api/reference/ad-account/minimum_budgets/
- [V] Nodo `MinimumBudget`: `currency`, `min_daily_budget_imp` (optimizado a impresiones),
  `min_daily_budget_high_freq` («high frequency actions like clicks and likes»),
  `min_daily_budget_low_freq` («low frequency actions like mobile app installs…»),
  `min_daily_budget_video_views`. Todos int32. https://developers.facebook.com/docs/marketing-api/reference/minimum-budget/
- **Unidades: no documentadas** en la página del nodo. [H] Siguen el *offset* de la moneda como
  el resto de importes de Marketing API (COP offset 1 = pesos enteros; USD/UYU/VES offset 100 =
  centavos) — https://developers.facebook.com/docs/marketing-api/currencies/ . Ya figura como
  «Pendiente de medir en vivo» en `docs/anuncios-estado-resultados.md:96`. Sigue pendiente.
- **Diario vs total:** el endpoint solo da mínimos **diarios**. Para presupuesto total (lifetime)
  la regla de «mínimo diario × días» no aparece en la referencia de API [no documentado en la
  referencia]; la página de ayuda «Prácticas recomendadas para los presupuestos mínimos»
  (https://www.facebook.com/business/help/203183363050448) no se pudo leer (se renderiza con JS).
  Nuestro `live_management._budget_floor` ya aplica `max(min_daily*) × días` y deja a
  `validate_only` como última palabra — es la forma correcta mientras no haya tabla oficial legible.
- **Por objetivo de optimización:** sí, por las cuatro familias de arriba (impresiones / acciones
  frecuentes / acciones poco frecuentes / reproducciones). Un mensaje («conversación iniciada») no
  tiene campo propio; [H] cae en `high_freq` o `low_freq` — medir con `validate_only`.
- **Por moneda:** el endpoint devuelve filas con `currency`; el código filtra COP. Los valores USD
  que circulan (US$1/día impresiones, US$5/día eventos de baja frecuencia) son de fuentes
  secundarias [S], no verificados en página oficial legible. **No hay tabla oficial COP/UYU/VES
  accesible: la fuente de verdad es la llamada en vivo por cuenta.**

## 3. Fase de aprendizaje

- **Campo de API — existe** [V]: `learning_stage_info` en el conjunto de anuncios («Info about
  whether the ranking or delivery system is still learning for this ad set»),
  https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/ . Nodo
  `AdCampaignLearningStageInfo` (https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-learning-stage-info/):
  - `status`: `LEARNING` / `SUCCESS` («exited the learning phase») / `FAIL` («isn't generating
    enough results to exit the learning phase»).
  - `conversions`: eventos desde la última edición significativa durante el aprendizaje (0 si ya salió).
  - `last_sig_edit_ts`: fecha de la última edición significativa que lo devolvió al aprendizaje.
  - `attribution_windows`.
  - **Nuevo y clave:** `dynamic_lp_status`, `dynamic_lp_conversions_threshold` («New conversions
    threshold for dynamic learning phase status») y `dynamic_lp_days_threshold` («Day to exit»).
    Es decir, **Meta ya no usa un umbral fijo publicado: devuelve el umbral por conjunto**.
  - Límites: «Only returned for active ad sets»; los conjuntos con creativo dinámico (DCO) no lo
    devuelven.
- **La regla «~50 eventos en 7 días»** — **no verificada en página oficial legible**: el artículo
  del Servicio de ayuda (https://www.facebook.com/business/help/112167992830700) se renderiza con
  JS y WebFetch solo obtuvo el título. Fuentes secundarias [S] (Jon Loomer, AdManage, WordStream)
  siguen citando ~50 en 7 días y reportan periodos en que Ads Manager mostró 10. Con los campos
  `dynamic_lp_*` la conclusión de diseño es: **no codificar 50/7; leer el umbral del conjunto**.
- **Qué lo reinicia (edición significativa):** la lista oficial está en el mismo artículo no
  legible. [S] cambios de segmentación, ubicaciones, evento de optimización, estrategia de puja,
  creativo nuevo o editado, pausa > 7 días y cambios «grandes» de presupuesto/puja. **El tamaño
  de «grande» no está documentado oficialmente** [no documentado]; el 20 % que circula es
  folclore de agencias [S]. Medible en vivo: `last_sig_edit_ts` cambia o no tras nuestra edición.
- **Para el semáforo:** `status=LEARNING` → «esperar»; `FAIL` → «cambiar algo» (creativo/zona/
  objetivo); `SUCCESS` → habilita «subir» o «mantener». `last_sig_edit_ts` permite decir «tu cambio
  del martes reinició el aprendizaje». Lectura con `ads_read` [H, §12].

## 4. Cómo escalar el presupuesto

- **Límite al bajar** [V]: «When updating a set's lifetime or daily budget to a lower value, the
  new value must be at least 10% greater than the current amount spent already»; y «Since v2.4,
  ad sets have a minimum required budget. Any update must take that into consideration» —
  https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/ (sección Updating).
- **Cuánto y cada cuánto subir: no documentado** en Marketing API (la guía de presupuestos no lo
  trata: https://developers.facebook.com/documentation/ads-commerce/marketing-api/bidding/overview/budgets.md).
  El «sube ~20 % cada 3–4 días» es práctica de agencias [S], no regla de Meta.
- **Límite técnico de frecuencia** [V]: «You can only change your ad set budget 4 times per hour»
  (error 613, subcódigo 1487632; bloquea una hora) y el límite de gasto de la cuenta solo se cambia
  10 veces al día (error 17, subcódigo 1885172) —
  https://developers.facebook.com/docs/marketing-api/overview/rate-limiting . Irrelevante para un
  dueño que aprueba un cambio cada varios días, pero el adaptador debe mapear esos errores.
- **Variación diaria** [V]: el changelog v24.0 dice «Daily budget flexibility is increasing from
  25% to 75%» y «Your weekly spend will not change, and will not be greater than 7 times your daily
  budget» — https://developers.facebook.com/documentation/ads-commerce/marketing-api/marketing-api-changelog/version24.0
  (la guía de presupuestos aún dice 25 %: está desactualizada). Para presupuesto total da igual:
  «You won't be charged more than your lifetime budget».
- **Reparto entre conjuntos** [V, mismo changelog v24]: «Ad set budget sharing allows you to share
  up to 20% of your budget with other ad sets in the same campaign» y «the
  `is_adset_budget_sharing_enabled` field is now required if you are planning to set a budget at
  the ad set level» (`POST act_/campaigns`). **Posible deriva en código** [H]: `promotions.py:276-281`
  crea la campaña sin ese campo y pone el presupuesto en el conjunto. Si la prueba real en vivo ya
  creó campañas, Meta lo acepta en la práctica; si no, es el primer error que verá. Verificar con
  `validate_only` (no es parte de esta investigación).
- **Consecuencia:** el «subir ~20 %» del semáforo es **regla nuestra**, versionada y medida con
  `last_sig_edit_ts` (¿reinició el aprendizaje?) sobre nuestros propios cambios aprobados.

## 5. Programación por horario (dayparting)

- [V] «Only use ad scheduling with lifetime budgets.» `pacing_type=["day_parting"]` +
  `adset_schedule` (lista de `{start_minute, end_minute, days[0-6, 0=domingo], timezone_type}`;
  `timezone_type` = `user` (hora del espectador) o `advertiser`). «`start_minute` and `end_minute`
  must be on the hour and must be at least one hour apart.» «Ad scheduling applies to a target
  audience's time zone … not an ad account's time zone» (por defecto).
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/bidding/overview/pacing-and-scheduling
- Con presupuesto de campaña (CBO/Advantage+) «budget pacing is at the campaign level»; la
  interacción exacta con `adset_schedule` no está documentada en esa página [no documentado].
- **Encaja con lo que ya hacemos:** el asistente solo acepta presupuesto total (lifetime) en COP,
  justo la condición que exige Meta. Hoy no enviamos `adset_schedule`; habilitarlo es un campo más
  en la creación con `ads_management` (ya pedido en App Review, ADR 38).
- **Horarios ideales:** Meta no los recomienda por API. Saldrían de nuestra atribución de
  conversaciones por hora (`messaging_attribution.py`) o del desglose `hourly_stats_aggregated_by_audience_time_zone` de Insights [H — verificar el nombre del breakdown en la referencia de Insights].

## 6. Señales de fatiga y saturación en Insights

Fuente principal [V]: https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference/ad-campaign/insights.md
(ejemplos en v25/v27).

| Señal | Campo | Qué dice Meta | ¿Lo leemos hoy? |
|---|---|---|---|
| Frecuencia | `frequency` | «average number of times each person saw your ad. This metric is estimated.» [V] | **No** (`results_service.py:546` pide `spend,reach,impressions,clicks,ctr,cpc,cpm,actions`) |
| Alcance | `reach` | «number of Accounts Center accounts that saw your ads at least once… estimated» [V] | Sí, pero **por día** (`time_increment=1`): el alcance diario **no se suma**; la frecuencia acumulada exige una consulta del periodo completo (sin `time_increment`) |
| CPM / CTR | `cpm`, `ctr` | «average cost for 1,000 impressions»; «percentage … performed a click (all)» [V] | Sí |
| Resultados y costo | `results`, `cost_per_result`, `cost_per_action_type` | «times your ad achieved an outcome, based on the objective»; «average cost per result» [V] | No (`actions` sí) |
| Conversaciones de mensajería | `actions[action_type=onsite_conversion.messaging_conversation_started_7d]` | Nombre del tipo de acción solo en fuentes secundarias [S] (Adverity); **verificar en vivo** con una promoción de mensajes | Indirecto vía `actions` |
| Diagnóstico de relevancia | `quality_ranking`, `engagement_rate_ranking`, `conversion_rate_ranking` | Página oficial no legible (404 en la referencia `ads-insights`). [S] valores Below/Average/Above, **no disponibles con < 500 impresiones**, no aplican a creativo dinámico; conectores (Rivery/Boomi, ene-2024) reportan su retiro de ciertos reportes en v18, pero la referencia de `ad-report-run/insights` aún lista dos de ellos → **estado incierto, verificar en vivo** | No |
| Por hora | breakdowns `hourly_stats_aggregated_by_audience_time_zone` / `…advertiser_time_zone` | Listados en la referencia [V], sin descripción | No |

- **Frescura** [V]: «Insights refresh every 15 minutes and do not change after 28 days» y siguen
  actualizándose «for a couple of days after an ad has completed» —
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/best-practices.md .
  Consecuencia: el semáforo no debe juzgar el día en curso; usar días cerrados (ya lo hacemos:
  `until = ayer`).
- **Mínimos de volumen:** el único umbral oficial-ish es el de 500 impresiones de los rankings [S].
  Para frecuencia/CTR/costo no hay mínimo documentado → **el mínimo estadístico es regla nuestra**.
- **Fatiga (definición):** Meta no publica un umbral de frecuencia por API [no documentado]. La
  regla «frecuencia > X y CTR cayendo Y % frente a la primera semana» es nuestra.

## 7. Recomendaciones de Meta (Opportunity Score)

**Existe y cubre parte del semáforo.** [V] https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/performance-recommendations
(ejemplos v27.0); anuncio: https://developers.facebook.com/blog/post/2025/11/10/unlock-peak-performance-with-new-opportunity-score-features-in-the-marketing-api/

- `GET act_<id>/recommendations` (por cuenta) y `GET <BUSINESS_ID>/recommendations` (por
  portafolio; este añade `opportunity_score` 0–100 y `ad_account_id`, máx. 100 cuentas por página).
- `POST act_<id>/recommendations` con `recommendation_signature` **aplica** la recomendación —
  nosotros **no** la usaríamos sin consentimiento explícito del dueño (asistido, nunca autónomo).
- Campos: `recommendation_signature`, `recommendation_stage` (`pre_create_guidance`,
  `pre_flight_recommendation`, `mid_flight_recommendation`), `type`, `object_ids`, `url`,
  `recommendation_content` (con `lift_estimate`, p. ej. «Up to 8% lower cost per result»),
  `opportunity_score_lift`.
- Tipos que mapean al semáforo: `BUDGET_LIMITED` («budget may be limiting… could get more results
  by increasing the budget» — **no aplicable por API**), `SCALE_GOOD_CAMPAIGN` («Increase their
  budgets» — aplicable con `extra_data.additional_budget` en centavos por conjunto o campaña),
  `CREATIVE_FATIGUE` («Cost per result… may be higher than ads you ran in the past…»; aplicar
  genera variaciones con IA de Meta — **no lo aplicaríamos**: el creativo es nuestro núcleo).
  Otros: `ADVANTAGE_PLUS_AUDIENCE`, `AUTOMATIC_PLACEMENTS`, `UNIFIED_INBOX`, etc.
- **Historial:** `act_<id>/opportunity_score_history` (serie diaria) — citado por la búsqueda y en
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/performance-recommendations-history-api ;
  no leído en detalle [H en su forma exacta].
- **Webhook** `ad_recommendations` en el objeto ad_account [S, no leído].
- **Límites** [V]: «the API may return fewer recommendations than Ads Manager»; lista vacía =
  Meta no ve cambios. El anuncio del blog dice que la puntuación «is in development and may
  evolve». **Disponibilidad para cuentas pequeñas: no documentada.** `additional_budget` en
  centavos — choca con COP offset 1 [H: verificar unidad con COP].
- **Conclusión:** sí conviene **mostrarlas** (fuente «Meta sugiere…») como una entrada más del
  semáforo, con nuestra traducción a lenguaje de dueño y consentimiento antes de cualquier POST.
  **No reemplaza** nuestras reglas: no cubre «esperar (aprendizaje)», «ampliar zona» con nuestra
  atribución de conversaciones, ni el costo por cliente interesado. Permiso de lectura: no
  indicado en la página [no documentado]; [H] `ads_read` para GET, `ads_management` para POST.

## 8. Reglas automatizadas (adrules_library)

[V] https://developers.facebook.com/docs/marketing-api/ad-rules/ y
https://developers.facebook.com/docs/marketing-api/ad-rules/overview/execution-spec

- Regla = `name` + `evaluation_spec` (qué objetos, filtros sobre metadatos o Insights) +
  `execution_spec` (qué hacer). `POST act_<id>/adrules_library`. Dos modos: **TRIGGER** (evalúa
  cuando cambian metadatos o datos de Insights) y **SCHEDULE** (cada intervalo).
- Tipos de ejecución: `NOTIFICATION` (aviso «jeweled» en Facebook al creador o `user_ids`;
  SCHEDULE y TRIGGER), `PING_ENDPOINT` (**manda un ping al webhook de la app**; solo TRIGGER),
  `PAUSE`, `UNPAUSE`, `CHANGE_BUDGET`, `CHANGE_CAMPAIGN_BUDGET`, `CHANGE_BID`, `ROTATE`,
  `REBALANCE_BUDGET` (los de cambio, solo SCHEDULE). Opciones `execution_count_limit` y
  `action_frequency` (minutos entre acciones sobre el mismo objeto).
- **¿Se puede usar solo para avisar/evaluar? Sí.** `PING_ENDPOINT` con regla TRIGGER permite que
  Meta evalúe la condición y nos avise por webhook sin ejecutar nada; luego nosotros proponemos y el
  dueño aprueba. `NOTIFICATION` avisa al usuario de Facebook, no al dueño en Qualify — inútil para
  nuestro flujo.
- **Pero:** crear la regla es una **escritura** en la cuenta del cliente (`ads_management` [H]),
  queda visible en su Administrador de anuncios, y la evaluación por TRIGGER solo cubre métricas de
  Insights/metadatos — no nuestra atribución de conversaciones. La suscripción del webhook de la app
  para estos pings no está detallada en esas páginas [no documentado].
- **Recomendación:** no usarlas en la primera versión. Nuestro propio *tick* sobre Insights (ya lo
  tenemos en `results_service.py`) da lo mismo sin escribir en la cuenta del cliente ni depender de
  otra suscripción de webhooks. Reabrir si el número de cuentas hace que la lectura periódica choque
  con los límites de uso (§12).

## 9. Monedas: COP, VES, UYU, USD

- [V] «The Marketing API supports all of the currencies supported by ad accounts». Offsets:
  **COP 1**, **VES 100** (Bolívar Soberano), **VEF 100** (Bolívar antiguo, aún listado),
  **UYU 100**, **USD 100**. https://developers.facebook.com/docs/marketing-api/currencies/
  (tabla marcada como actualizada 2024-04-16 según la búsqueda).
- [V] «The amount you set for bid and budget is at ad account currencies minimum denomination
  level, such as cents for USD» — https://developers.facebook.com/documentation/ads-commerce/marketing-api/bidding/overview/budgets.md .
  Es decir, `lifetime_budget=100000` es 1.000 USD o 100.000 COP. El código ya lo modela
  (`meta_currency_offset`, hoy solo COP=1: `live_wizard.production_currency_offset`).
- **Mínimos por moneda: no hay tabla oficial legible**; `act_/minimum_budgets` los da por cuenta
  (§2). Es la única fuente fiable para UYU/VES/USD.
- **Venezuela** [H]: que VES exista como moneda no dice nada de cómo pagar. Medios de pago por país
  no documentados en las páginas leídas; la práctica conocida (tarjetas internacionales, cuentas en
  USD) es [S]/[H]. Para clientes venezolanos lo prudente es **asumir cuenta en USD** y que el
  asistente admita USD (offset 100) antes que VES (inflación: un presupuesto en VES queda viejo en
  semanas, y nuestras tablas de referencia en VES serían inútiles). Uruguay: UYU soportado, sin
  particularidad documentada.
- **Implicación:** ampliar el asistente de «solo COP» a COP/USD/UYU es cambiar la tabla de offsets
  y los rótulos de dinero (`health_models.money_label` reconoce solo las monedas de `money.META_CURRENCY_OFFSETS`, hoy COP/USD/UYU, m-25099912); la cuenta
  publicitaria fija la moneda y no se cambia (una cuenta = una moneda) [S].

## 10. Presupuesto de campaña Advantage+ vs presupuesto por conjunto

- [V] Advantage campaign budget (antes CBO): «optimizing the distribution of a campaign budget
  across your campaign's ad sets». Con él, `pacing_type` (incl. `day_parting`) va en la campaña;
  `daily_min_spend_target`/`daily_spend_cap` por conjunto exigen presupuesto **diario** de campaña.
  La página **no dice cuándo Meta lo recomienda**.
  https://developers.facebook.com/docs/marketing-api/bidding/guides/advantage-campaign-budget
- [V] Unificación Advantage+ (2025–2026): `advantage_state_info` (desde v23) es de solo lectura y
  vale `ADVANTAGE_PLUS_SALES/APP/LEADS` solo si los tres «levers» (presupuesto de campaña,
  público Advantage+, ubicaciones Advantage+) están activos; ASC/AAC antiguos no se pueden crear ni
  editar desde 2026-05-19 (v25). https://developers.facebook.com/docs/marketing-api/advantage-campaigns ,
  https://developers.facebook.com/blog/post/2025/10/08/upcoming-asc-and-aac-mapi-deprecation-migration-options-to-advantage-plus/ ,
  https://developers.facebook.com/blog/post/2026/02/13/asc-and-aac-deprecation-mapi-v25/
  La unificación cubre **ventas, apps y clientes potenciales**; nuestros objetivos son
  `OUTCOME_ENGAGEMENT`+`CONVERSATIONS` (mensajes), `OUTCOME_TRAFFIC` y `OUTCOME_LEADS` — solo
  LEADS entra en esa estructura.
- [V] Alternativa intermedia v24: presupuesto por conjunto + `is_adset_budget_sharing_enabled`
  (hasta 20 % compartido) — ver §4.
- **Qué recomendar para 2–3 creativos con presupuesto chico: Meta no lo documenta por API**
  [no documentado]. Razonamiento [H]: con un solo conjunto y 2–3 anuncios dentro, la distribución
  la hace Meta a nivel de anuncio de todos modos; CBO solo importa con varios conjuntos. Para un
  dueño pequeño, **un conjunto, presupuesto total en el conjunto, 2–3 anuncios** es lo más simple y
  es lo que ya construimos. Pasar a presupuesto de campaña solo si un día probamos varias zonas o
  públicos a la vez.

## 11. Guía oficial de cuánto invertir para pequeños negocios

- **Meta no publica una cifra por tamaño de negocio, nicho ni margen** [no documentado en ninguna
  página oficial encontrada]. Lo que dice, según la búsqueda sobre sus propias páginas (los
  artículos del Servicio de ayuda se renderizan con JS y WebFetch no lee su cuerpo):
  - «there is no minimum budget» / presupuestos diarios recomendados distintos por objetivo
    (https://en-gb.facebook.com/business/ads) [S — texto vía buscador].
  - «start with at least $5» y duración de más de seis días; el anuncio debe correr «at least seven
    days, so our system has time to learn» (https://www.facebook.com/business/ads/pricing,
    página antigua) [S — vía buscador].
  - «most advertisers who are charged for impressions should allocate at least USD 1 per day»;
    los mínimos «vary by business vertical, bid strategy, and schedule»
    (https://en-gb.facebook.com/business/help/203183363050448) [S — vía buscador].
  - «Cuánto cuesta anunciarse en Facebook» (https://es-la.facebook.com/business/help/201828586525529):
    el costo depende de la subasta, público, calidad y época del año [S].
- **Blueprint:** no se encontró un curso con tabla de presupuesto por tipo de negocio [no
  verificado; Blueprint exige sesión].
- **Consecuencia:** la recomendación de presupuesto inicial (nicho × tamaño de mercado × ticket ×
  margen) es **100 % regla nuestra**. Meta solo aporta dos pisos: el mínimo diario de la cuenta
  (`minimum_budgets`) y «≥ 7 días» para aprender. Pendiente: leer los tres artículos del Servicio
  de ayuda con Claude in Chrome (sesión del fundador) para pasar estas citas de [S] a [V].

## 12. Límites de uso y permisos

- **Permisos** [V] (https://developers.facebook.com/docs/marketing-api/get-started/authorization):
  `ads_read` = «read ad reports for ad accounts you own or have been granted access to»;
  `ads_management` = «read and manage ads». Acceso avanzado por permiso vía App Review.
- **Mapa por lectura** (las páginas de referencia no nombran el permiso; inferencia por la regla
  general [H]):

| Lectura / acción | Permiso mínimo |
|---|---|
| `reachestimate`, `delivery_estimate`, `minimum_budgets` | `ads_read` [H] (lecturas de cuenta) |
| `learning_stage_info`, campos del conjunto | `ads_read` [H] |
| `/insights` (frecuencia, costo por resultado, desgloses por hora) | `ads_read` [V por definición «read ad reports»] |
| `GET act_/recommendations`, `opportunity_score_history` | `ads_read` [H] |
| `POST act_/recommendations`, `adrules_library`, cambio de presupuesto, `adset_schedule` | `ads_management` [H/V por definición «manage»] |

  **No hace falta ningún permiso nuevo**: ADR 38 ya pide `ads_management`/`ads_read` en App Review
  (m-24828986). Sin acceso avanzado solo funciona con cuentas del fundador (ADR 29).
- **Niveles de Marketing API** [V]: *Limited access* (por defecto; «Heavily rate-limited… For
  development only… Not for production apps running for live advertisers») y *Full access*
  (requiere «at least 500 Marketing API calls in the last 15 days» y < 15 % de errores).
- **Cupos por cuenta publicitaria por hora** [V] (https://developers.facebook.com/docs/marketing-api/overview/rate-limiting):
  gestión = `100000 (Full) | 300 (Dev) + 40 × anuncios activos`; Insights = `190000 (Full) | 600
  (Dev) + 400 × anuncios activos − 0.001 × errores`. Cabeceras `X-Business-Use-Case`,
  `X-Ad-Account-Usage`, `x-fb-ads-insights-throttle`; errores 80000/80003/80004/80014, 17, 613.
  **Cálculo** [calculado]: un *tick* diario por promoción con ~5 llamadas (insights del periodo +
  insights diario + conjunto + recomendaciones + mínimos) → 150 llamadas/mes por promoción;
  incluso en Dev (600/h de Insights por cuenta) sobra por 3 órdenes de magnitud. **El límite no es
  restricción de diseño**; sí lo es llegar a 500 llamadas/15 días para mantener Full access, que el
  propio *tick* ayuda a cumplir.

## Implicaciones para el diseño

### Qué cambia frente a la idea

1. **El presupuesto inicial no puede salir de Meta.** La curva gasto→alcance/resultados
   (`daily_outcomes_curve`) devuelve ceros y quedó eliminada en todas las versiones desde
   2026-10-27, sin reemplazo. Meta solo da: tamaño de audiencia (`reachestimate`, rango) y mínimo
   diario por cuenta (`minimum_budgets`). La recomendación «empieza con $X» es **una tabla nuestra**
   (nicho × tamaño de zona × ticket × margen), versionada y con procedencia, calibrada luego con
   nuestros propios resultados (costo por cliente interesado de `messaging_attribution.py`) y con
   los comparativos entre negocios.
2. **La fase «probar» se lee de Meta, no se supone.** `learning_stage_info.status`
   (`LEARNING`/`SUCCESS`/`FAIL`) y los umbrales por conjunto `dynamic_lp_conversions_threshold` /
   `dynamic_lp_days_threshold` reemplazan la regla fija «50 en 7 días» (que además ya no es fija).
   `last_sig_edit_ts` dice si nuestro cambio aprobado reinició el aprendizaje — así medimos nuestra
   propia regla de «subir ~20 %».
3. **«Subir ~20 %», «cambiar creativo», «ampliar zona» son reglas nuestras.** Meta no documenta
   cuánto ni cada cuánto subir; solo los límites técnicos (4 cambios/hora por conjunto; al bajar, ≥
   gastado + 10 %; mínimo diario). Fatiga: no hay umbral oficial; usar `frequency` (hoy **no la
   pedimos**) + caída de CTR/costo por resultado, con el mínimo de volumen como regla nuestra.
4. **Una parte del semáforo se puede tomar de Meta tal cual:** `act_/recommendations`
   (`BUDGET_LIMITED`, `SCALE_GOOD_CAMPAIGN`, `CREATIVE_FATIGUE`) como «Meta sugiere…», con
   `lift_estimate`. Solo lectura y mostrar; aplicar = POST con consentimiento exacto (y nunca
   `CREATIVE_FATIGUE`, que genera creativos con IA de Meta). No reemplaza nuestras reglas (no cubre
   esperar, ampliar zona ni costo por conversación atribuida).
5. **Reglas automatizadas: no en la v1.** Podrían solo avisar (`PING_ENDPOINT`), pero escriben en
   la cuenta del cliente y no ven nuestra atribución. El *tick* propio sobre Insights alcanza.
6. **Programar horarios es compatible con lo que ya hay:** exige presupuesto total (lifetime), que
   es lo único que acepta el asistente. Horas en punto, mínimo una hora, hora del público.
7. **Monedas:** COP offset 1; USD/UYU/VES offset 100. Venezuela → recomendar cuenta en USD
   [H]. Sin tabla oficial de mínimos por moneda: siempre leer `minimum_budgets` en vivo.
8. **Estructura:** un conjunto con presupuesto total y 2–3 anuncios (lo que ya existe). La
   unificación Advantage+ solo toca ventas/apps/clientes potenciales; nuestros mensajes y tráfico
   no. **Posible deriva:** v24 exige `is_adset_budget_sharing_enabled` al crear campañas con
   presupuesto por conjunto y `promotions.py` no lo envía — verificar con `validate_only`.

### De dónde sale cada número

| Número del asesor | Fuente |
|---|---|
| Tamaño de mercado (personas en la zona) | Meta — `reachestimate` [V] |
| Presupuesto inicial recomendado | **Nuestra tabla** (sin curva de Meta) |
| Piso de presupuesto | Meta — `minimum_budgets` × días [V; unidades por medir] |
| Duración mínima de prueba | Meta dice ≥ 7 días [S]; regla nuestra |
| Estado probar/validar | Meta — `learning_stage_info` + umbrales dinámicos [V] |
| Cuánto subir y cada cuánto | **Regla nuestra**; límite técnico Meta 4/h [V] |
| Fatiga / cambiar creativo | Insights (`frequency`, CTR, costo) [V] + umbral nuestro; o `CREATIVE_FATIGUE` de Meta [V] |
| «Presupuesto limitado» | Meta — `BUDGET_LIMITED` [V] |
| Costo por cliente interesado | **Nuestra atribución** + `spend` de Insights |
| Horas buenas | Breakdowns horarios de Insights [V] o nuestra atribución por hora |
| Temporada (quincenas, fechas) | **Nuestro** — Meta no expone estacionalidad por API |
| Comparativos entre negocios | **Nuestro** (agregados anónimos; RLS: necesita una vista agregada sancionada, no lectura cruzada) |

### Imposible o no documentado

- Curva oficial gasto→resultados (eliminada). Cifra oficial de inversión por tamaño o nicho.
- Umbral oficial de «cambio grande» de presupuesto que reinicia el aprendizaje.
- Unidades de `minimum_budgets` (medir en vivo, pendiente desde `anuncios-estado-resultados.md`).
- Estado actual de los rankings de relevancia en la API (verificar en vivo).

### Permisos

Nada nuevo: todo lo de lectura cabe en `ads_read`; recomendar/aplicar/programar en
`ads_management` — ambos ya en el App Review de ADR 38. Para producción con clientes ajenos hace
falta **Full access** de Marketing API (Limited es «For development only»).

### Siguientes pasos sugeridos (sin ticket todavía)

1. Leer con Claude in Chrome los artículos del Servicio de ayuda (aprendizaje, mínimos, costo)
   para pasar sus citas a [V].
2. Una prueba en vivo de solo lectura sobre la cuenta del fundador: `minimum_budgets` (unidades),
   `learning_stage_info`, `recommendations`, `frequency` y rankings de una promoción real.
3. ADR corto `[PROPUESTO]` del asesor: «números de Meta vs tabla nuestra», con la tabla de arriba.

Estado: **completo** (2026-11-22).
