# Discovery — Estados de WhatsApp como lugar donde sale el anuncio

**Fecha:** 2026-11-16 · **Ticket:** m-24789525 (ADS-17 de la épica m-24828970) · **Estado:** `[DISCOVERY · recomendación: ESPERAR a m-24828971, luego SEGUIR]` · nada se construye desde este documento.
**Etiquetas:** `[V]` fuente oficial de Meta o código en disco (URL y fecha de lectura 2026-11-16) · `[S]` fuente secundaria · `[H]` hipótesis · **por confirmar** = no verificado; **m-24828971** = solo se cierra con la prueba en vivo.

## 1. Veredictos (criterios del ticket)

| Rama | Veredicto | Fuente |
|---|---|---|
| **(B) Anuncio que también sale en los Estados** | **Viable con requisitos**: la Marketing API lo admite como posición `whatsapp_positions: ["status"]` dentro de `publisher_platforms` con `"whatsapp"`, **siempre junto con historias de Instagram** (`instagram_positions: ["story"]`), y nunca en un anuncio que declare una categoría especial (Vivienda incluida). Según [2] la cuenta debe tener configurado el clic a WhatsApp; [1] dice que no hace falta cuenta de WhatsApp Business para el destino web. | [1] [2] [3] `[V]` |
| **(A) Publicar un Estado orgánico por API** | **No disponible hoy**: no hay endpoint en la Cloud API; su registro de cambios solo menciona los Estados para anuncios (2025-10-20). Ya cerrado en `docs/whatsapp-estados-opciones.md` §2. | [5] `[V]` (ausencia de evidencia) |

## 2. Qué es para el dueño

Su anuncio aparece entre los Estados de WhatsApp (pestaña «Novedades»), en pantalla completa vertical, como una historia más. Lo ven personas que usan WhatsApp todos los días, no solo quienes abren Instagram. Matiz importante frente a la historia del ticket («llegar a quien ya me tiene en sus contactos»): **Meta no promete eso**. El anuncio en Estados llega al público que se segmentó (lugar, edad, intereses), no a los contactos del número. Lo que sí trae el anuncio es el botón para escribir por WhatsApp, que es como venden Bianki, Polette y la agencia de viajes. Que el dueño lo valore es `[H]`: se valida con las preguntas de §5.1.

## 3. Lo que dice Meta (2026-11-16)

| Tema | Dato | Nivel |
|---|---|---|
| Campos | `targeting.publisher_platforms: ["instagram","whatsapp"]`, `instagram_positions: ["story"]`, `whatsapp_positions: ["status"]`. Valores de `whatsapp_positions`: `status`, `marketing_messages` | `[V]` [1][2] |
| Regla dura | «You cannot select `status` for `whatsapp_positions` by itself»: hay que incluir historias de Instagram. Un anuncio solo en Estados no existe | `[V]` [1][2][3] |
| Países | «Global, salvo UE, Reino Unido, Irán, Cuba, Siria, Rusia y Corea del Norte». **CO, VE y UY no están excluidos.** Venezuela: sin exclusión escrita, pero la entrega real **por confirmar (m-24828971)** | `[V]` [1] |
| Objetivos | `OUTCOME_AWARENESS`, `OUTCOME_TRAFFIC`, `OUTCOME_ENGAGEMENT`, `OUTCOME_LEADS`, `OUTCOME_SALES`, `OUTCOME_APP_PROMOTION`. Los que Qualify usa hoy (`OUTCOME_TRAFFIC` con `LINK_CLICKS`, `OUTCOME_ENGAGEMENT` con `CONVERSATIONS`, `OUTCOME_LEADS` con `LEAD_GENERATION`) están en la lista | `[V]` [1] |
| Destinos | Chat de WhatsApp, web, formulario instantáneo (solo tipo «Más volumen») y app. La página de posiciones dice solo «WhatsApp chat y Website» y pide tener configurado el clic a WhatsApp; [1] dice que el destino web no necesita cuenta de WhatsApp Business → **contradicción entre páginas, por confirmar** | `[V]` [1][2] |
| Formatos | Imagen única y video único, vertical 9:16; los Estados duran 24 h. Carrusel de hasta 10 tarjetas: lo dice [1] y no lo menciona [3] → **por confirmar**. Colección y formatos flexibles no | `[V]` [1][3] |
| Creativo | Ejemplos con `object_story_spec.link_data`. Identidad opcional `wamo_whatsapp_identity_spec{wamo_whatsapp_identity_id \| whatsapp_phone_number}`; sin ella se muestra la Página y «algunos anuncios pueden no entregarse en Estados». No se puede cambiar en un creativo ya creado | `[V]` [3] |
| No compatible | Anuncios que declaran una categoría especial (Finanzas, Empleo, **Vivienda**, Política), salud/farmacia, pruebas A/B, creativo dinámico (DCO), alcance y frecuencia, herramientas de Advantage+ creative | `[V]` [1] |
| Exclusión silenciosa | Si el destino o el evento no sirven para Estados, Meta **crea el conjunto igual y quita los Estados sin avisar**: hay que leer las posiciones efectivas (`effective_whatsapp_positions`) | `[V]` [1][4] |
| Edad desconocida | `targeting.user_age_unknown` (booleano), solo con Estados. [6] dice que por omisión vale `true` desde julio de 2026; [1] dice que omitirlo no equivale a `true` → **enviarlo siempre explícito** | `[V]` [1][6] |
| Atribución | Los mensajes que llegan desde un anuncio en Estados **no traen el identificador de clic** en el webhook (Cloud API, 2025-10-20). Si sigue llegando el `referral` con el id del anuncio: **por confirmar (m-24828971)** | `[V]` [5] |
| Permisos | `ads_management` (o `business_management`): el mismo permiso de ADR 38. No pide una revisión aparte, pero depende de la misma puerta pendiente: el acceso avanzado a `ads_management` (App Review, m-24828986) para negocios que el fundador no administra | `[V]` [3] |
| Presupuesto mínimo | Ninguna página da un mínimo propio de Estados; rige `minimum_budgets` de la cuenta | **por confirmar** |
| Ubicaciones automáticas | Ninguna página oficial dice si Advantage+ placements incluye los Estados cuando se omite `publisher_platforms`. Una nota de prensa dice que sí y que al elegir a mano hay que sumar historias de Instagram | `[S]` [7], **por confirmar (m-24828971)** |

## 4. Qué hace hoy el código (leído en `main` a87c4ee6)

- `qualify_api/ads/audience.py` `PLACEMENTS`: solo `instagram_feed/story/reels/explore` y `facebook_feed`. No hay WhatsApp.
- «Que Meta elija» (`placement_mode=automatic`) **no** deja elegir a Meta del todo: `targeting()` envía siempre `publisher_platforms: ["facebook","instagram"]` (`audience.py:304`, igual en `wizard_workflow.py:179`). **Hoy ningún anuncio de Qualify puede salir en Estados, ni con «automáticas».** `docs/anuncios-publico-ubicaciones.md` ya lo dice («no permite incorporar WhatsApp ni Threads por omisión»).
- La pieza sin publicar fija su segmentación solo en Instagram (`unpublished_service.py:473`: `publisher_platforms: ["instagram"]`; WS-3 tiene que cambiarla también) y su creativo (`unpublished.py:330`) usa `asset_feed_spec` con reglas por ubicación solo para Instagram; si Meta lo trata como «formato flexible / DCO», Estados no lo admite → **por confirmar**.
- La promoción de una publicación existente usa `source_instagram_media_id`; Meta solo documenta Estados con `object_story_spec.link_data` → **si una publicación de Instagram ya existente puede salir en Estados, por confirmar (m-24828971)**.
- La lectura de comprobación del conjunto bloquea cualquier clave de `targeting` no prevista (`anuncios-publico-ubicaciones.md`): sumar Estados exige aceptar `whatsapp_positions` y `user_age_unknown` en esa lista.

## 5. Qué cambia en nuestros flujos

| Opción | Qué es | Para el dueño | Esfuerzo | Riesgo |
|---|---|---|---|---|
| A. Dejar como está | Facebook + Instagram solamente | Nada nuevo | 0 | Pierde un lugar barato y visto a diario `[H]` |
| **B. Estados dentro de «Que Meta elija» + casilla manual** (recomendada tras la prueba) | Con «Que Meta elija», Qualify suma los Estados cuando la promoción puede salir ahí (destino chat o web según Meta lo admita, sin Vivienda declarada, foto o video vertical), **apagado por omisión hasta que WS-2 confirme que los chats que vienen de Estados se pueden atribuir**. Con «Elegirlos yo», una casilla que marca y bloquea «Instagram: historias». Se envían las claves de §3 + `user_age_unknown` explícito; las posiciones efectivas se leen con el anuncio en pausa, antes de aprobar | No tiene que pensar en eso; quien quiere elegir, elige. Que prefiera dejarlo siempre marcado es `[H]` (§5.1) | S–M | Bajo; casilla desactivada con motivo si declara Vivienda |
| C. Ubicaciones automáticas de verdad | Omitir `publisher_platforms` en «Que Meta elija» | Meta reparte también en Messenger, Audience Network, Threads… | S de código, M de revisión | Gasto en lugares que el dueño no ve ni entiende; rompe la lista de comprobación; pertenece a ADS-14 (m-24828984), que espera a m-24828971 |

La opción C no se decide aquí: es la discusión de Advantage+ en m-24828984.

Que los Estados salgan junto con **todas** las posiciones de Instagram (no solo historias) cuando Meta elige: **por confirmar en WS-1**.

### 5.1 Pregunta para la investigación con dueños (propuesta; no edita `perfil-cliente-pyme.md`)

Preguntar primero a Bianki y Polette: «¿Mira los estados de WhatsApp de otros negocios? ¿Le ha escrito a alguno por un estado? Si su anuncio saliera ahí, ¿quién cree que lo vería: sus contactos o cualquier persona de su ciudad? ¿Lo dejaría marcado siempre o lo elegiría cada vez?»

## 6. Textos propuestos (`qualify-copy-es`)

- Título del bloque (hoy «Espacios en Facebook e Instagram», `promotion_audience_ui.py:220`): **«Dónde aparece»**; opciones **«Que Meta elija»** / **«Elegirlos yo»**.
- Resumen automático (hoy «Meta elige dónde mostrarlo en Facebook e Instagram», `promotion_audience_ui.py:244` y `promotion_audience_vm.py:47`): **«Meta elige dónde mostrarlo en Facebook, Instagram y, si se puede, en los estados de WhatsApp.»**
- Casilla (dentro de «Elegirlos yo» / «Más opciones»): **«WhatsApp: estados»**. Ayuda: «Tu anuncio sale entre los estados de WhatsApp, en pantalla completa, y trae un botón para que te escriban. Lo ven las personas del público que elegiste, no solo tus contactos. Va siempre junto con las historias de Instagram.»
- Pieza que no es vertical: casilla desactivada con «Necesita una foto o un video vertical.»
- Al marcarla: aviso breve «Marcamos también Instagram: historias. Meta lo pide así.»; la casilla de historias queda bloqueada con el motivo visible «Va junto con WhatsApp: estados. Meta no deja uno sin el otro.» Al desmarcar WhatsApp, historias se desbloquea pero sigue marcada.
- Vivienda declarada: casilla visible y desactivada con «Los anuncios de vivienda no pueden salir en los estados de WhatsApp: es una regla de Meta.» Si ya estaba marcada: «Quitamos los estados de WhatsApp porque es un anuncio de vivienda. Instagram: historias sigue marcado y ya puedes quitarlo.»
- Revisión: «Dónde puede salir» antes de la comprobación de Meta; «Dónde sale» después.
- Si Meta quitó los Estados (leído con el anuncio en pausa, **antes** de aprobar; también en el detalle del anuncio): «Meta no lo mostrará en los estados de WhatsApp. Tu presupuesto se usa en Instagram (historias). Puedes aprobarlo así o volver a elegir dónde aparece.» Botones **«Aprobar así»** / **«Volver»**. Sin adivinar la causa hasta WS-1.
- Si WS-1 muestra que no se entrega en Venezuela: casilla desactivada por país con «Los estados de WhatsApp todavía no están disponibles para anuncios en Venezuela.» (rama de WS-3).

## 7. Riesgos

1. **Exclusión silenciosa** (§3): sin leer las posiciones efectivas con el anuncio en pausa y antes de aprobar, la pantalla prometería algo que no ocurre.
2. **Atribución**: si el `referral` tampoco llega, los chats que vengan de Estados no se marcarán «vino del anuncio» (ADS-10) y los resultados se verían peor de lo que son.
3. **Venezuela**: sin exclusión escrita, pero ni la entrega ni el cobro están probados allí.
4. **La inmobiliaria no puede usarlo si declara Vivienda** (categoría especial). Si anuncia solo en Colombia puede mandar `special_ad_categories: []` (`epica-anuncios-meta.md`, ADR 38) y entonces sí.
5. **Contradicciones en la documentación** (destinos, carrusel, edad desconocida): se resuelven con `validate_only` y lecturas, no leyendo más.

## 8. Historias candidatas (sin ticket)

| # | Historia | Depende de |
|---|---|---|
| WS-1 | Dentro de m-24828971 y con el visto bueno del dueño: un conjunto que **se queda en `PAUSED`, nunca se activa y no gasta nada**, con Estados + historias de Instagram (`validate_only` y luego creado), en Bianki o Polette, con los tres creativos de Qualify (publicación existente, pieza sin publicar con `asset_feed_spec`, `link_data` simple); leer `effective_*_positions`, `targeting` devuelto y un `adpreviews` con `ad_format=WHATSAPP_STATUS_MEDIA`; probar también «Que Meta elija» con todas las posiciones de Instagram | m-24828971 |
| WS-2 | Prueba de atribución: un mensaje real desde un anuncio en Estados llega con o sin `referral` | WS-1, ADS-10 (m-24828980) |
| WS-3 | Opción B: Estados en `PLACEMENTS` y en «Que Meta elija» (apagado hasta WS-2), casilla manual con la regla de historias, Vivienda, pieza vertical, `user_age_unknown` explícito, lista de comprobación ampliada, la segmentación fija de `unpublished_service.py:473` y los textos de §6 (incluidos `promotion_audience_ui.py:220`, `:244` y `promotion_audience_vm.py:47`) | WS-1 verde, ADS-07 (m-24828977) |
| WS-4 | Lectura de `effective_whatsapp_positions` con el anuncio en pausa, antes de aprobar; aviso «Aprobar así» / «Volver» en la revisión y en el detalle del anuncio | WS-3 |
| WS-5 | Resultados por ubicación (`publisher_platform`, `platform_position`) en ADS-09 | WS-3, ADS-09 (m-24828979) |

## 9. Recomendación: **ESPERAR** a m-24828971; luego **SEGUIR** con WS-3/WS-4

La API ya lo permite, los tres países no están excluidos y el cambio es una casilla. Pero tres cosas de las que depende el diseño (si sale con nuestros creativos, si Meta lo quita en silencio, si se puede atribuir el chat) solo se cierran con la prueba en vivo, que ya está planificada y no cuesta un ticket aparte: basta con sumar WS-1 a su guion. **Reabrir como PARAR** si WS-1 muestra que Meta excluye los Estados con todos nuestros creativos. **Pasar a SEGUIR antes** si un dueño lo pide con presupuesto.

## 10. Por confirmar

1. Entrega real en CO, VE y UY (m-24828971).
2. Si «Ubicaciones automáticas» de Meta (sin `publisher_platforms`) incluye los Estados (m-24828971 / m-24828984).
3. Si una publicación de Instagram existente (`source_instagram_media_id`) y la pieza con `asset_feed_spec` pueden salir en Estados (m-24828971).
4. Destinos válidos (formulario instantáneo y app, además de chat y web) y carrusel (contradicción entre [1], [2] y [3]).
5. Valor por omisión de `user_age_unknown`.
6. Si llega el `referral` en mensajes desde Estados (m-24828971).
7. Presupuesto mínimo propio de Estados.
8. A medias: [1] dice que el destino web no necesita cuenta de WhatsApp Business; falta saber si lo de [2] (clic a WhatsApp configurado) se exige igual a la cuenta (m-24828971).

## 11. Fuentes (leídas el 2026-11-16)

1. Meta, Ads in WhatsApp Status: https://developers.facebook.com/documentation/ads-commerce/marketing-api/ads-in-whatsapp-status
2. Meta, Placement targeting: https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/placement-targeting (también `/docs/marketing-api/audiences/reference/placement-targeting`)
3. Meta, WhatsApp identity: https://developers.facebook.com/documentation/ads-commerce/marketing-api/ads-in-whatsapp-status/whatsapp-identity
4. Campos `whatsapp_positions` / `effective_whatsapp_positions`: referencia Targeting v25.0 en `reference/meta-instagram-platform/docs/graph-api/reference/targeting.md` (cosechada) y SDK oficial https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/targeting.py; `WHATSAPP_STATUS_MEDIA` en `reference/meta-instagram-platform/documentation/ads-commerce/graph-api/reference/adgroup/previews.md`
5. Meta, registro de cambios de la Cloud API (entrada 2025-10-20): https://developers.facebook.com/docs/whatsapp/cloud-api/changelog
6. Meta, Unknown age on WhatsApp: https://developers.facebook.com/documentation/ads-commerce/marketing-api/ads-in-whatsapp-status/user-age-unknown
7. `[S]` Social Samosa, «Meta introduces ads in WhatsApp status»: https://www.socialsamosa.com/news-2/ads-in-whatsapp-status-10468891
8. Centro de ayuda de Meta para empresas (no se pudo leer el cuerpo con el lector automático; revisar en navegador): https://www.facebook.com/business/help/723817683917948?id=805840565113559
