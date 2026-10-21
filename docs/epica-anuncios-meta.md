# Épica — Anuncios de Meta desde Qualify

**Fecha:** 2026-10-21 · **Estado:** `[INVESTIGACIÓN + HISTORIAS · sin implementar · 6 decisiones del fundador pendientes]` · **Meegle:** épica [m-24828970](https://project.larksuite.com/5h2wsx/story/detail/24828970) (mapa de tickets en §5)
**Pedido del fundador (2026-10-21):** las publicaciones que genera Qualify ya son aceptables; ahora hay que poder **convertirlas en anuncios de Meta** por la Marketing API, con el botón «Más información» y las demás capacidades de anuncios que ofrece Meta, todo configurado desde Qualify.
**Reemplaza** el ticket aparcado m-24789462 «Publicidad pagada / Marketing API» (parking lot desde 2026-07-24) y absorbe la rama (B) del discovery m-24789525 (anuncios en los Estados de WhatsApp como ubicación).
**Fuentes:** documentación oficial de Meta leída el 2026-10-21 (enlaces en §8) y lectura del código en `main` (`8aa9a06`). Lo que no se pudo confirmar va marcado `[NO VERIFICADO]` y aparece como prueba en ADS-00.

---

## 0. Resumen en cinco líneas

1. **Sí se puede**: una publicación de Instagram que ya existe se convierte en anuncio con `source_instagram_media_id` y admite el botón `LEARN_MORE` («Más información») con enlace. El MVP es justamente eso.
2. **El bloqueo no es de ingeniería, es administrativo.** Para manejar cuentas publicitarias de clientes hace falta **acceso avanzado** a `ads_management`/`ads_read`, una ronda más de App Review. Ese ticket vive en la épica de Meta App Review, no en esta. La verificación del negocio está hecha desde el 2026-10-05 y **la app ya está en modo Live** (fundador, 2026-10-21). Por eso el subcódigo 1885183, «post creado por una app en modo desarrollo», no debería aparecer; ADS-00 lo confirma igual.
3. **El dinero lo pone el cliente**: el anuncio se cobra en la cuenta publicitaria del cliente con su propio método de pago. Qualify nunca toca tarjetas, solo lee si la cuenta puede pagar.
4. **El código actual ayuda más de lo que parece.** Las piezas ya guardan `ads_primary_text`, `ads_headline`, `ads_description` y `ads_cta_type`, y el generador ya tiene «Destino: Orgánico / Anuncio / Ambos». Faltan el **enlace de destino**, un **botón cerrado** (enum) y la **cuenta publicitaria**.
5. **Hay que tomar una decisión antes de construir**: ADR 21 dejó los anuncios fuera («orgánico primero»), y Zernio ya vende anuncios por API. Ver §6.

---

## 1. Qué existe hoy (medido en el código)

| Pieza | Estado | Dónde |
|---|---|---|
| Publicar en Instagram (imagen, carrusel, reel, historia) | ✅ Content Publishing API. Se guarda el **id de la publicación de IG** (`publish_attempts.published_media_id`) | `qualify_api/publishing/client.py`, migración 0003 |
| Publicar en una Página de Facebook | ❌ No existe. Tampoco se guarda el id de un post de FB ni el permalink | — |
| Textos de anuncio en la pieza | ✅ `CopyPayload.ads_primary_text`, `ads_headline` (≤40), `ads_description` (≤30), `ads_cta_type` (**texto libre, no enum**). El LLM los llena si `brief.intent.includes_ads` | `qualify_creative/schemas.py:285-317`, `brand/render.py` |
| Destino Orgánico/Anuncio/Ambos | ✅ En `/create`. El detalle del borrador muestra un bloque «Anuncio» | `Qualify/creative_pages.py:744-768, 1870-1876` |
| Enlace de destino (web, catálogo, WhatsApp) | ❌ No existe en la pieza ni en la marca | — |
| Formatos | ✅ `feed_4_5`, `feed_1_1`, `reels_9_16`, `story_9_16`: son las proporciones que pide la personalización por ubicación de Meta | `qualify_creative/enums.py:100` |
| Conexión Meta | ✅ Facebook Login for Business. Guarda el token de **Página**, `linked_page_id` y el id de IG. Los scopes salen de `QUALIFY_META_SCOPES` (env) | `connections/meta_oauth.py`, `service.py` |
| Cuenta publicitaria (`act_…`) | ❌ No se pide ni se guarda en ninguna tabla | — |
| Scopes de anuncios | ❌ Solo hay comentarios («deferred; out of ADR 21's organic-first scope») | `qualify_shared/social/ig_shapes.py:666` |
| Versión de Graph | `v21.0` por defecto. **La Marketing API va por v26.0** (2026-07-29) y sus versiones caducan antes que las de Graph | `qualify_api/config.py:28` |
| Webhook `leadgen` | ❌ `qualify_api/leads/` es el formulario propio de Qualify, no los anuncios de clientes potenciales | — |
| Chats de WhatsApp y de Instagram | ✅ Construidos: son el destino natural de los anuncios «clic a WhatsApp / Direct» | `qualify_api/whatsapp/`, `conversations/` |
| Botón «Promocionar» | ❌ Lugares naturales: detalle de una pieza publicada, `post_card.py` y el panel del evento en el Planificador | `Qualify/creative_pages.py`, `planner_drawer.py` |

**Choque de nombres:** la tabla `campaigns` (migración 0045) agrupa contenido internamente y no tiene que ver con las campañas de Meta. Las tablas nuevas deben llamarse `ad_*` / «promociones» para no confundirlas.

---

## 2. Cómo funciona un anuncio en Meta (lo que Qualify tiene que crear)

```
Cuenta publicitaria (act_<id>, del cliente: moneda, zona horaria, método de pago)
 └─ Campaña      objetivo (OUTCOME_TRAFFIC / _LEADS / _ENGAGEMENT / _AWARENESS / _SALES)
 │               special_ad_categories (obligatorio; [] o HOUSING…)
 └─ Conjunto     presupuesto (diario o total, en unidades menores de la moneda), fechas,
 │               segmentación (lugar, edad, intereses, Advantage+ audience),
 │               ubicaciones, optimization_goal, destination_type (WEBSITE, WHATSAPP,
 │               INSTAGRAM_DIRECT, ON_AD…)
 └─ Creativo     (a) publicación existente: source_instagram_media_id + instagram_user_id
 │               (b) nuevo: object_story_spec con imagen/video subido + texto + título
 │               + call_to_action {type: LEARN_MORE, value: {link}}
 └─ Anuncio      se crea en PAUSED → revisión de Meta (PENDING_REVIEW) → ACTIVE / DISAPPROVED
```

**Botones (CTA) útiles para nuestros clientes:**

| Botón en Qualify | `type` en Meta | Para quién |
|---|---|---|
| Más información | `LEARN_MORE` | todos (el pedido del fundador) |
| Enviar mensaje por WhatsApp | `WHATSAPP_MESSAGE` | comida, viajes, inmobiliaria |
| Enviar mensaje (Instagram/Messenger) | `MESSAGE_PAGE` / `INSTAGRAM_MESSAGE` | todos |
| Pedir ahora | `ORDER_NOW` | comida |
| Reservar viaje / Reservar | `BOOK_TRAVEL` / `BOOK_NOW` | agencia de viajes |
| Solicitar cotización | `GET_QUOTE` | inmobiliaria, viajes |
| Contáctanos | `CONTACT_US` | todos |
| Llamar | `CALL_NOW` | todos (no funciona en historias) |
| Registrarte | `SIGN_UP` | anuncios de clientes potenciales |
| Comprar | `SHOP_NOW` | tiendas |

Qué botón vale para qué objetivo no está en la referencia del enum: ADS-00 lo mide. Los errores 1373054 y 2446383 son los que avisan de una combinación inválida.

---

## 3. Permisos, acceso y lo que bloquea

| Requisito | Estado | Nota |
|---|---|---|
| Verificación del negocio (portfolio Qualify.co) | ✅ 2026-10-05 | Requisito de todo acceso avanzado |
| `ads_management`, `ads_read`, `pages_manage_ads`, `business_management` | ❌ no pedidos | `ads_management` depende de `pages_read_engagement` + `pages_show_list` |
| `leads_retrieval` (+ `pages_manage_metadata`) | ❌ | Solo para anuncios de clientes potenciales |
| **Acceso avanzado** a los permisos de anuncios | ❌ | **Sin él solo se manejan cuentas publicitarias de quien tenga rol en la app.** Con ADR 29 eso cubre a los clientes que administra el fundador (Bianki, Polette, la inmobiliaria). El cliente dos necesita App Review |
| **Nivel de acceso de la Marketing API** (Limited → Full) | Limited por defecto | Full exige ≥500 llamadas en 15 días con <15 % de errores. Limited: tope de 60 puntos (escritura = 3), bloqueo de 300 s, 300 + 40×anuncios activos por hora |
| **App en modo Live** | ✅ (fundador, 2026-10-21) | Evita el subcódigo 1885183 («post creado por una app en modo desarrollo»). ADS-00 confirma que una publicación de Qualify se puede promocionar |
| Cuenta publicitaria con método de pago | ❌ en la de prueba | «Qualify.co - Meta Ads Test» no tiene método de pago (`plan-modulo-whatsapp-cloud-api.md`) |
| Cuenta de IG asignada a la cuenta publicitaria | ❓ por cliente | Si no, error 1815199. Se comprueba con `act_<id>/connected_instagram_accounts` |
| Términos | ❌ | Las Self-Serve Ad Terms dicen que quien anuncia por otro «necesita su permiso» y responde por las infracciones. Hace falta una cláusula en los términos de Qualify y un consentimiento explícito antes de gastar |

**Categoría especial «Vivienda» (inmobiliaria).** Declararla solo es obligatorio para anunciantes de EE. UU. o que lleguen a EE. UU., Canadá o partes de Europa. Una inmobiliaria colombiana que anuncia solo en Colombia puede mandar `[]`. Al declararla, la edad queda fija en 18-65+, no se elige género, el radio mínimo es de 15-25 km y no hay intereses demográficos ni públicos similares. Propuesta: un interruptor «Es un anuncio de vivienda», apagado por defecto en CO y obligatorio si la segmentación toca EE. UU., Canadá o la UE.

**Venezuela.** No encontramos fuente actual de Meta sobre si una cuenta publicitaria venezolana puede pagar y publicar. `[NO VERIFICADO]`: tratarlo como prueba (ADS-00) y prever cobro en cuenta colombiana o en USD.

---

## 4. Entregas

| Entrega | Qué puede hacer el cliente al terminarla | Historias |
|---|---|---|
| **E0 — Puertas** | Nada visible: sabemos que el camino funciona y tenemos la decisión firmada | ADS-00, ADS-01 |
| **E1 — «Promocionar» una publicación** (MVP) | Elegir una publicación ya publicada en Instagram, ponerle «Más información» con su web, presupuesto, fechas y ciudad, revisar y lanzar. Ver si Meta la aprobó y cuánto gastó | ADS-02…ADS-09 |
| **E2 — Anuncios que abren una conversación** | El anuncio abre un chat de WhatsApp o de Instagram, y la conversación llega a los Chats de Qualify marcada como «vino del anuncio» | ADS-10 |
| **E3 — Anuncios de clientes potenciales** | Formulario de Meta, los datos entran al CRM de Qualify | ADS-11 |
| **E4 — Anuncio nuevo desde una pieza** | Anunciar una pieza sin publicarla antes, con 4:5 en el feed y 9:16 en historias y reels | ADS-12 |
| **E5 — Afinar** | Públicos de quienes interactuaron, similares, mejoras de Advantage+ y reglas de presupuesto | ADS-13, ADS-14 |
| **Transversal** | Clientes que no administra el fundador; consentimiento de gasto; WhatsApp Estados como ubicación | ADS-15 (en la épica de Meta App Review), ADS-16, ADS-17 |

---

## 5. Historias

Formato de `docs/formato-tickets-meegle.md`. Cada historia es un Issue de Meegle bajo la Feature «Épica — Anuncios de Meta desde Qualify» ([m-24828970](https://project.larksuite.com/5h2wsx/story/detail/24828970)), salvo ADS-15. El ticket de Meegle es la versión viva: el texto de abajo es el de su creación.

| Historia | Ticket | Prioridad | Nota |
|---|---|---|---|
| ADS-00 prueba en vivo | m-24828971 | P1 | |
| ADS-01 decisión y ADR | m-24789462 | P1 | Reutiliza «Publicidad pagada / Marketing API» (parking lot desde 2026-07-24) |
| ADS-02 cuenta publicitaria | m-24828972 | P1 | |
| ADS-03 cliente Marketing API | m-24828973 | P1 | |
| ADS-04 modelo de datos | m-24828974 | P1 | |
| ADS-05 enlace y botón en la pieza | m-24828975 | P1 | |
| ADS-06 «Promocionar» (MVP) | m-24828976 | P1 | |
| ADS-07 público y ubicación | m-24828977 | P2 | |
| ADS-08 salud de la cuenta | m-24828978 | P1 | |
| ADS-09 estado y resultados | m-24828979 | P1 | |
| ADS-10 clic a WhatsApp / Direct | m-24828980 | P2 | |
| ADS-11 leads al CRM | m-24828981 | P2 | |
| ADS-12 anuncio desde pieza | m-24828982 | P2 | |
| ADS-13 públicos | m-24828983 | P3 | |
| ADS-14 Advantage+ y reglas | m-24828984 | P3 | |
| ADS-15 App Review de anuncios | m-24828986 | P1 | **En «Épica — Meta App Review (permisos, videos y Tech Provider)»** |
| ADS-16 términos y consentimiento | m-24828985 | P1 | |
| ADS-17 WhatsApp Estados como ubicación | m-24789525 | P2 | Reutiliza el discovery de WhatsApp Estados, reenfocado en la rama (B) |

### ADS-00 · Anuncios: prueba en vivo de promocionar una publicación de Qualify (discovery)
**Tipo:** tarea técnica · **Etiqueta:** Infraestructura · **P1**

**Contexto.** La documentación deja abiertas preguntas que pueden cambiar el MVP. La app ya está en modo Live, así que el 1885183 no debería aparecer; esta prueba lo confirma.

**Qué hay que hacer.** Con una cuenta publicitaria propia (Qualify.co o la de Bianki) que tenga método de pago, y usando Graph Explorer o un script en `scratchpad`, sin código de producto:
- Promocionar una publicación de IG **publicada por Qualify** (`source_instagram_media_id`) con `LEARN_MORE` y enlace, en `PAUSED`. Anotar si sale el 1885183.
- Leer `boost_eligibility_info` de esa publicación y de una con música con derechos de autor.
- Leer `act_<id>/minimum_budgets` y `min_daily_budget` en **COP**.
- Probar qué objetivos aceptan `LEARN_MORE` sobre una publicación existente (TRAFFIC, ENGAGEMENT, AWARENESS).
- Comprobar si la configuración actual de Facebook Login for Business (`QUALIFY_META_CONFIG_ID`) admite el activo «cuentas publicitarias» y si el cliente tiene que volver a iniciar sesión.
- Si hay una cuenta venezolana a mano: ¿puede pagar y publicar?

**Criterios de aceptación**
- [ ] Cada punto anotado en `docs/epica-anuncios-meta.md` §3 con su respuesta real (respuesta de la API, sin tokens).
- [ ] Si alguna respuesta cambia el MVP (ADS-06), queda dicho cómo.
- [ ] Nada se activa: todo anuncio de prueba queda en `PAUSED` y luego se borra.

### ADS-01 · Anuncios: decisión del fundador y ADR (levantar el «orgánico primero»)
**Tipo:** tarea técnica · **Etiqueta:** Documentación · **P1**

**Contexto.** ADR 21 dejó los anuncios fuera y `arquitectura.md` §6 los registra como «PROPUESTO, necesita su propia investigación y ADR». Además, la tensión abierta del 2026-07-30 con Zernio aplica aquí: Zernio vende «6 redes de Ads» por API.

**Qué hay que hacer.** Redactar el ADR con las decisiones de §6, que el fundador lo firme y dejarlo en `arquitectura.md` §6.

**Criterios de aceptación**
- [ ] ADR `[APROBADO]` en `arquitectura.md` §6 con D1-D6 respondidas.
- [ ] La nota de ADR 21 sobre anuncios apunta al nuevo ADR.

### ADS-02 · Conexiones: pedir y guardar la cuenta publicitaria del cliente
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P1** · **Depende de:** ADS-00

**Qué se quiere.** Como dueño de un negocio quiero conectar mi cuenta publicitaria de Meta a Qualify para poder anunciar sin salir de Qualify.

**Propuesta**
- Sumar `ads_management`, `ads_read`, `pages_manage_ads` y `business_management` a la configuración de Facebook Login for Business (activo «cuentas publicitarias»), sin tocar el flujo de quien no quiera anuncios.
- Migración `ad_accounts`: `tenant_id`, `connection_id`, `ad_account_id` (`act_…`), `name`, `currency`, `timezone_name`, `account_status`, `disable_reason`, `has_funding_source`, `instagram_assigned` (bool), `business_id`, `last_checked_at`. Con RLS, siguiendo el patrón de 0001.
- Leer `/me/adaccounts` y `act_<id>/connected_instagram_accounts`. Si hay varias cuentas, el cliente elige una por marca.
- `ScopeKey.ADS` en la matriz de capacidades (`permission_capability.py`) y la capacidad «Anunciar» en `/connections`.

**Criterios de aceptación**
- [ ] Un tenant con la cuenta conectada ve en `/connections` el nombre, la moneda y el estado de su cuenta publicitaria.
- [ ] Sin el scope, la capacidad «Anunciar» aparece como no disponible, con el motivo en español.
- [ ] Tests de la migración (subir/bajar) y de RLS.

### ADS-03 · Anuncios: cliente de la Marketing API
**Tipo:** tarea técnica · **Etiqueta:** Infraestructura · **P1**

**Qué hay que hacer**
- `qualify_api/ads/client.py` (`MarketingClient`), con **versión propia** `QUALIFY_META_ADS_API_VERSION=v26.0`, separada de `QUALIFY_META_API_VERSION`, porque las versiones de la Marketing API caducan antes.
- Métodos: campañas, conjuntos, creativos, anuncios, `adpreviews`, `minimum_budgets`, `reachestimate`, `targetingsearch`/`search?type=adgeolocation`, estados y `insights`.
- Errores traducidos **por `error_subcode`, nunca por el texto**, porque Meta responde en el idioma del dueño de la cuenta. Tabla inicial: 1885183, 1815199, 2238055/2446149, 1885272/1885650, 1885621, 1885029, 1885557, 294, 2654/1713092, 17/613/80004, 4841018 (una edición cada 30 s), 1373054, 2446383. Cada uno con un mensaje para el cliente sin jerga.
- Leer `X-Business-Use-Case` / `X-Ad-Account-Usage` y esperar antes de saturar la API.
- Fake en memoria para los tests, siguiendo el patrón de `publishing/`.

**Criterios de aceptación**
- [ ] Tests offline de cada método contra el fake, y del mapeo de errores.
- [ ] Ningún token en logs.

### ADS-04 · Anuncios: modelo de datos de las promociones
**Tipo:** tarea técnica · **Etiqueta:** Infraestructura · **P1** · **Depende de:** ADS-02

**Qué hay que hacer.** Migración `ad_promotions`. Una fila es una promoción de Qualify, que equivale al trío campaña + conjunto + anuncio en Meta:
- `tenant_id`, `brand_id`, `ad_account_id`, procedencia (`content_draft_id`, `publish_attempt_id`, `source_media_id`).
- `objective`, `special_ad_categories`, `cta_type`, `link_url`, presupuesto (`budget_kind`, `budget_minor`, `currency`), `start_time`/`end_time` y `targeting` (jsonb).
- Ids de Meta (`meta_campaign_id`, `meta_adset_id`, `meta_creative_id`, `meta_ad_id`), `status` interno y `effective_status` de Meta, `review_feedback`.
- `approved_by` / `approved_at` para el consentimiento de gasto.

Se escribe primero en Qualify y después en Meta (write-ahead). Si falla a mitad de camino, la conciliación retoma desde el último id guardado y nunca crea dos campañas. Es el mismo patrón que `publish_attempts`. RLS en la misma revisión.

**Criterios de aceptación**
- [ ] Reintentar una creación interrumpida no duplica objetos en Meta (test con el fake).
- [ ] Subir/bajar la migración limpio y aislamiento por tenant probado (`-m db`).

### ADS-05 · Generador: enlace de destino y botón del anuncio en la pieza
**Tipo:** mejora · **Etiquetas:** Improvement, UI · **P1**

**Qué se quiere.** Como dueño quiero que mis piezas sepan a dónde lleva el anuncio y qué dice el botón para no escribirlo cada vez.

**Propuesta**
- Enlace por defecto en la marca (web, catálogo o `wa.me`), que la pieza puede cambiar.
- `ads_cta_type` pasa de texto libre a un enum con la tabla de §2 y etiquetas en español. El LLM elige del enum según rubro y objetivo, con «Más información» por defecto.
- Validación de URL (https, sin acortadores raros).

**Criterios de aceptación**
- [ ] Una pieza con Destino «Anuncio» o «Ambos» muestra botón y enlace editables en su detalle.
- [ ] Las piezas viejas con `ads_cta_type` libre se migran al valor del enum más cercano o a `LEARN_MORE`.

### ADS-06 · Anuncios: «Promocionar» una publicación de Instagram (MVP)
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P1** · **Depende de:** ADS-02…05

**Qué se quiere.** Como dueño de un negocio quiero promocionar una publicación que ya funciona en Instagram, con el botón «Más información», para que llegue a más gente de mi ciudad sin abrir el Administrador de anuncios.

**Propuesta.** Botón «Promocionar» en el detalle de una pieza publicada, en `post_card` y en el panel del evento publicado del Planificador. El asistente tiene cuatro pasos:
1. **Objetivo:** «Visitas a tu web» (TRAFFIC + `LINK_CLICKS`/`LANDING_PAGE_VIEWS`, `destination_type=WEBSITE`). Los demás objetivos llegan en E2/E3.
2. **Botón y enlace:** precargados de la pieza (ADS-05).
3. **Público:** ciudad + radio, edad y Advantage+ audience encendido (detalle en ADS-07). Interruptor «Es un anuncio de vivienda».
4. **Presupuesto y fechas:** presupuesto total en COP, inicio y fin. Debajo, el mínimo leído de `minimum_budgets` (nunca fijo en el código) y el alcance estimado.

Antes de mostrar el asistente se comprueba: la cuenta puede pagar (ADS-08), la IG está asignada a la cuenta y la publicación es elegible (`boost_eligibility_info`). Si algo falla, se dice qué hacer, en español.

Al terminar se crea todo en `PAUSED`, se muestra la vista previa de Meta (`adpreviews`) y el cliente confirma con un aviso claro: «Meta cobrará hasta $X a tu método de pago». Solo entonces se pasa a `ACTIVE`.

**Criterios de aceptación**
- [ ] De punta a punta contra el fake: la promoción queda `ACTIVE` con creativo `source_instagram_media_id` + `instagram_user_id` (nunca `instagram_actor_id`) y CTA `LEARN_MORE`.
- [ ] Sin confirmación explícita no se activa nada.
- [ ] Un presupuesto por debajo del mínimo se rechaza antes de llamar a Meta.
- [ ] Una prueba real en la cuenta de Bianki o Polette con un presupuesto mínimo, autorizada por el fundador.

**Fuera de alcance:** publicaciones de Página de Facebook (`object_story_id`), porque Qualify no publica en FB; anuncios de colaboración con creadores.

### ADS-07 · Anuncios: público y ubicación
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P2** · **Depende de:** ADS-03

**Propuesta**
- Buscador de lugares (`search?type=adgeolocation`): país, región o ciudad. Radio de 17-80 km en ciudades y punto en el mapa de 1-80 km con `custom_locations`.
- Edad, género, intereses (`adinterest`, sugerencias con `adinterestsuggestion`) y aviso de intereses que Meta va a retirar (`targetingoptionstatus`).
- Advantage+ audience (`targeting_automation.advantage_audience`), siempre enviado explícitamente (obligatorio desde v23).
- Alcance estimado (`reachestimate`).
- Con «Vivienda» activado, la UI esconde lo que la categoría no permite.
- Ubicaciones: «Automáticas» por defecto, o elegir Instagram feed/historias/reels/explorar, Facebook y WhatsApp Estados (rama B de m-24789525: confirmar en ADS-00 que `publisher_platforms` lo admite).

**Criterios de aceptación**
- [ ] El público elegido se guarda en `ad_promotions.targeting` y se reconstruye igual al editar.
- [ ] Una promoción de Vivienda nunca envía edad, género ni exclusiones (test).

### ADS-08 · Anuncios: salud de la cuenta publicitaria y del método de pago
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P1** · **Depende de:** ADS-02

**Propuesta**
- Lectura periódica (diaria y antes de cada promoción) de `account_status`, `disable_reason`, `funding_source`, `amount_spent` y `spend_cap`.
- Estados en español con tono del sistema de diseño: activa (`ok`), sin método de pago (`warn`, con enlace a la configuración de pagos de Meta), deshabilitada (`error`, con el motivo de `disable_reason`) y en revisión de riesgo (`warn`).
- Un anuncio en `PENDING_BILLING_INFO` se muestra como «Falta el método de pago».
- Opcional: tope de gasto de la cuenta (`spend_cap`).

**Criterios de aceptación**
- [ ] Una cuenta sin método de pago no deja abrir el asistente de ADS-06 y explica cómo resolverlo.
- [ ] Ningún dato de tarjeta pasa por Qualify (solo el tipo de fuente, si Meta lo da).

### ADS-09 · Anuncios: estado, revisión y resultados
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P1** · **Depende de:** ADS-04, ADS-06

**Propuesta**
- Webhooks de la cuenta publicitaria (`with_issues_ad_objects`, `in_process_ad_objects`, `effective_status`), suscritos por `act_<id>/subscribed_apps` y procesados por la bandeja de `webhooks/processor.py`. Respaldo: consulta cada 30 min de las promociones vivas.
- Rechazo: `ad_review_feedback` en español y botón «Editar y volver a enviar».
- Acciones: pausar, reanudar, cambiar presupuesto o fecha de fin (respetando una edición cada 30 s).
- Resultados diarios desde `insights` a la tabla `ad_promotion_insights` (día, gasto, alcance, impresiones, clics, CTR, CPC, CPM, `actions`) y un panel por promoción en COP. Avisar que los datos se asientan en 28 días y que, desde 2026-01-12, no hay ventanas de 7 y 28 días por visualización.

**Criterios de aceptación**
- [ ] Un anuncio rechazado aparece como «Rechazado por Meta» con el motivo en menos de 15 min (webhook) o 30 min (sondeo).
- [ ] El panel de una promoción muestra gasto y clics de ayer (test con fixture de `insights`).

### ADS-10 · Anuncios: clic a WhatsApp y a Instagram Direct
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P2** · **Depende de:** E1

**Qué se quiere.** Como restaurante, agencia o inmobiliaria quiero que el anuncio abra un chat conmigo, para vender por mensaje como ya lo hago.

**Propuesta**
- Objetivo ENGAGEMENT o LEADS, `destination_type=WHATSAPP` (`promoted_object{page_id, whatsapp_phone_number}`, CTA `WHATSAPP_MESSAGE`) o `INSTAGRAM_DIRECT` (CTA `INSTAGRAM_MESSAGE`), y `optimization_goal=CONVERSATIONS`.
- Mensaje de bienvenida y preguntas rápidas (`page_welcome_message`, ice breakers).
- Funciona también sobre una publicación existente.
- **Atribución:** guardar el `referral` del anuncio que traen los webhooks de WhatsApp e Instagram en el hilo, para que los Chats de Qualify marquen «vino del anuncio X» y ADS-09 cuente conversaciones por promoción.

**Criterios de aceptación**
- [ ] Un mensaje entrante con `referral` de un anuncio queda enlazado a su `ad_promotions.id`.
- [ ] Requisito validado: el número de WhatsApp está vinculado a la Página; si no, se explica cómo hacerlo.

### ADS-11 · Anuncios: anuncios de clientes potenciales (formulario de Meta → CRM)
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P2** · **Depende de:** E1, ADS-15 (`leads_retrieval`)

**Propuesta**
- Editor de formularios (`/<page>/leadgen_forms`): preguntas, política de privacidad (siempre enviada), mensaje de agradecimiento y `locale` en español.
- Objetivo `OUTCOME_LEADS` + `LEAD_GENERATION`/`QUALITY_LEAD` + `ON_AD`.
- Webhook `leadgen` de la Página (`pages_manage_metadata`). Con el `leadgen_id` se lee el lead y entra en `qualify_api/leads` con procedencia (formulario, anuncio, promoción). Respaldo: lectura de `/<form>/leads` por `time_created`.

**Criterios de aceptación**
- [ ] Un lead de prueba (herramienta de pruebas de leads de Meta) llega al CRM de Qualify en menos de 5 min.
- [ ] El texto de consentimiento del formulario cubre recibir mensajes de WhatsApp si se va a usar como opt-in (pendiente 3 del módulo WhatsApp).

### ADS-12 · Anuncios: anuncio nuevo desde una pieza no publicada
**Tipo:** Feature · **Etiquetas:** Feature, UI · **P2** · **Depende de:** E1

**Propuesta**
- Subir imagen a `act_<id>/adimages` (se obtiene un hash) o video a `advideos`, desde los archivos de la pieza en R2.
- Creativo con `object_story_spec` (`link_data`/`video_data`/carrusel con `child_attachments`), con los textos `ads_primary_text`/`ads_headline`/`ads_description` y la CTA.
- **Personalización por ubicación:** la salida 4:5 al feed y la 9:16 a historias y reels (`asset_feed_spec` + `asset_customization_rules`). El motor de plantillas ya produce varias salidas por corrida.

**Criterios de aceptación**
- [ ] Una pieza con salida feed + historia genera un solo anuncio con dos reglas de ubicación.
- [ ] Los textos que pasan los límites de Meta se cortan o se rechazan antes de llamar a la API.

### ADS-13 · Anuncios: públicos personalizados y similares
**Tipo:** Feature · **Etiqueta:** Feature · **P3**

**Propuesta.** Público de «quienes interactuaron con tu Instagram» (`event_sources{type: ig_business}`, hasta 730 días) y de «quienes te escribieron». Públicos similares a partir de ellos. Antes, comprobar que la cuenta aceptó los términos de públicos personalizados.

**Criterios de aceptación**
- [ ] Crear y usar un público de interacción en una promoción; queda bloqueado con Vivienda (similares no permitidos).

### ADS-14 · Anuncios: mejoras automáticas de Advantage+ y reglas
**Tipo:** mejora · **Etiqueta:** Improvement · **P3**

**Propuesta**
- Por marca, encender o apagar cada mejora de `creative_features_spec` (retoques de imagen, variantes de texto, `enhance_cta`, animación…), con «apagadas» por defecto, porque cambian la pieza que el cliente aprobó.
- Si se encienden, el anuncio pasa siempre por la vista previa.
- Más adelante: reglas automáticas (pausar si el CPC pasa de X).

**Criterios de aceptación**
- [ ] Con todas apagadas, cada `enroll_status` se envía `OPT_OUT` explícito.

### ADS-15 · App Review · ads_management, ads_read y pages_manage_ads — video «Promocionar una publicación» + Marketing API en Full access
**Tipo:** tarea técnica · **Etiqueta:** Infraestructura · **P1 (el reloj empieza en la semana 0)** · **Vive en «Épica — Meta App Review (permisos, videos y Tech Provider)»**, no en esta épica

**Qué hay que hacer**
- Envío de App Review para `ads_management`, `ads_read` y `pages_manage_ads` (y, en E3, `leads_retrieval`, con su propio video), con el video del flujo de ADS-06, instrucciones para revisores y cuenta de prueba con cuenta publicitaria. Va aparte del envío de mensajes: el App Review se concede por permiso.
- Subir el nivel de la Marketing API a Full (≥500 llamadas en 15 días, <15 % de errores) con uso real de los clientes del fundador.

**Criterios de aceptación**
- [ ] Permisos con acceso avanzado aprobado, visibles en el panel de la app.
- [ ] Nivel Full medido.

### ADS-16 · Anuncios: términos, consentimiento y registro de gasto
**Tipo:** tarea técnica · **Etiqueta:** Documentación · **P1**

**Qué hay que hacer**
- Cláusula en los términos de Qualify: el cliente autoriza a Qualify a crear anuncios en su cuenta, el gasto es suyo y debe cumplir las normas publicitarias de Meta.
- Consentimiento por promoción (`approved_by`/`approved_at`, ADS-04) y registro de cada cambio de presupuesto o estado con quién y cuándo.
- Revisar con abogado: categorías especiales, anuncios políticos (excluidos) y Venezuela.

**Criterios de aceptación**
- [ ] Ninguna llamada que gasta dinero (activar, subir presupuesto) se hace sin un `approved_by` registrado (test).

### ADS-17 · Anuncios: WhatsApp Estados como ubicación de los anuncios (discovery)
**Tipo:** Feature (discovery) · **Etiqueta:** Feature · **P2** · reutiliza m-24789525

**Contexto.** El discovery original separaba (A) publicar contenido orgánico en el Estado de WhatsApp por API y (B) anuncios cuya ubicación incluye los Estados. Con esta épica, (B) es una casilla más de ADS-07.

**Propuesta.** Confirmar en la Marketing API v26.0 si los Estados de WhatsApp son una ubicación seleccionable (`publisher_platforms` + posición), con qué objetivos y formatos, y probarlo en `PAUSED` junto con ADS-00. Para (A), un veredicto de una línea con fuente: si no hay API, se cierra; si la hay, se abre un ticket fuera de esta épica.

**Criterios de aceptación**
- [ ] Veredicto con fuente oficial para (B) y, si es viable, la posición anotada en ADS-07.
- [ ] Veredicto de una línea, con fuente, para (A).

---

## 6. Decisiones del fundador (antes de E1)

| # | Pregunta | Recomendación |
|---|---|---|
| **D1** | ¿Se levanta el «orgánico primero» de ADR 21 para anuncios? | Sí: es tu pedido de hoy. Va en el ADR de ADS-01 |
| **D2** | ¿Construir sobre la Marketing API o comprar a un agregador (Zernio vende «6 redes de Ads»)? | **Construir** el MVP: tocamos la cuenta publicitaria del cliente con nuestras propias piezas y Chats, y Zernio no quita el App Review del cliente. Pero conviene leer su API de anuncios antes de firmar, como se hizo con la publicación |
| **D3** | ¿Quién se ve primero: los clientes que administras (Bianki, Polette, inmobiliaria) por acceso estándar, o esperar App Review? | Empezar con los tuyos (ADR 29) e iniciar App Review en paralelo |
| **D4** | ¿Primer objetivo: visitas a la web (`LEARN_MORE`) o clic a WhatsApp? | El pedido es `LEARN_MORE` → E1 tal cual. Para comida y viajes, WhatsApp probablemente vende más: E2 justo después |
| **D5** | ¿Inmobiliaria con «Vivienda» encendido por defecto? | Apagado en CO/VE, con aviso; obligatorio si se apunta a EE. UU., Canadá o la UE |
| **D6** | ¿Qualify cobra por anuncio gestionado (créditos, `billing.usage_events`) o va incluido? | Incluido en el MVP. Decidir el modelo al medir el uso |

---

## 7. Riesgos

- **App Review de anuncios (ADS-15):** sin él, solo los clientes que administra el fundador. Hay que empezarlo en paralelo a E1.
- **Versiones:** Graph `v21.0` en el código frente a Marketing API v26.0. Si se mezclan, fallan los campos renombrados (`instagram_actor_id` → `instagram_user_id`).
- **Dinero real:** cualquier error de presupuesto lo paga el cliente. Por eso todo se crea en `PAUSED`, hay consentimiento explícito y los mínimos y topes se leen de la API.
- **Revisión de Meta:** «normalmente en 24 h». Las cuentas publicitarias nuevas suelen tardar más y rechazar más.
- **Límites del nivel Limited:** 60 puntos y 300 s de bloqueo dan para pocos clientes. Hay que llegar a Full.

---

## 8. Fuentes (Meta, leídas el 2026-10-21)

- Changelog y versiones: https://developers.facebook.com/docs/graph-api/changelog
- Publicaciones existentes como anuncios: https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/use-posts-as-ads
- Renombre de campos de IG (v22): https://developers.facebook.com/blog/post/2025/08/11/instagram-marketing-api-update/
- Campaña / conjunto / anuncio / creativo: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/ · …/ad-campaign/ · …/adgroup/ · …/ad-creative/
- CTA: https://developers.facebook.com/docs/marketing-api/reference/ad-creative-link-data-call-to-action/
- Presupuestos y mínimos: https://developers.facebook.com/documentation/ads-commerce/marketing-api/bidding/overview/budgets.md · https://developers.facebook.com/docs/marketing-api/reference/ad-account/minimum_budgets/
- Personalización por ubicación: https://developers.facebook.com/documentation/ads-commerce/marketing-api/dynamic-creative/placement-asset-customization.md
- Advantage+ creative: https://developers.facebook.com/documentation/ads-commerce/marketing-api/creative/advantage-creative/get-started.md
- Clientes potenciales: https://developers.facebook.com/docs/marketing-api/guides/lead-ads/create · …/retrieving
- Clic a WhatsApp / Instagram: https://developers.facebook.com/docs/marketing-api/ad-creative/messaging-ads/click-to-whatsapp · https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-instagram.md
- Segmentación y categorías especiales: https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting · https://developers.facebook.com/docs/marketing-api/audiences/special-ad-category
- Insights: https://developers.facebook.com/docs/marketing-api/insights · https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- Webhooks de cuenta publicitaria: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-ad-accounts
- Permisos y acceso: https://developers.facebook.com/docs/permissions/ · https://developers.facebook.com/docs/marketing-api/overview/authorization · https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
- Cuenta publicitaria (estado, pago): https://developers.facebook.com/docs/marketing-api/reference/ad-account/
- Errores: https://developers.facebook.com/docs/marketing-api/error-reference/
- Facebook Login for Business: https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business
- Términos y normas: https://www.facebook.com/legal/self_service_ads_terms · https://transparency.meta.com/policies/ad-standards/
