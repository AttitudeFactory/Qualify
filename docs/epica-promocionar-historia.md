# Épica — Terminar el flujo de promocionar una historia

**Fecha:** 2026-11-26 · refinada 2026-11-27 · **Estado:** `[FIRMADO 2026-11-26 · opción C · en construcción]` · **Meegle:** épica [m-25130273](https://project.larksuite.com/5h2wsx/story/detail/25130273) (tickets en §6) · **Épica madre:** anuncios de Meta, [m-24828970](https://project.larksuite.com/5h2wsx/story/detail/24828970)

Etiquetas de evidencia: `[V]` código o documento leído en `main` (9894d611; revisión del 2026-11-27 sobre 7ea4f0e1) · `[S]` documentación de Meta leída el 2026-11-26, sin probar · `[H]` inferido.

## Decisión del fundador (2026-11-26)

Manda sobre el análisis de abajo.

- **Opción C:** llevar la historia al anuncio en historias que ya existe y sumar música por etapas. `[FIRMADO]`
- **D1–D5 aceptadas como están** (tabla de §5). `[FIRMADO]`
- **Tickets creados** en Meegle (§6).
- **Pendiente del fundador:** el visto bueno y la fecha de la prueba en vivo HIS-0 (m-25130278), incluida la historia de prueba en el Instagram de Bianki. Sin ese sí no se hace ninguna llamada a Meta.
- **Pendiente antes de construir:** la revisión de arquitectura y de UX que pide `qualify-backlog` no se corrió antes de crear los tickets.
- **Se reabre si** HIS-0 muestra que el anuncio en historias no se puede crear como está, o si a los 30 días de salir HIS-1 ningún negocio lo usó.

## Decisiones del 2026-11-27 (después de la revisión independiente)

Mandan sobre lo de abajo. `[FIRMADO]`

1. **Historia de video sin imagen 9:16:** portada automática (N1, tamaño M: sacar un cuadro 9:16 del video). Mientras tanto el enlace queda oculto en esas historias.
2. **HIS-1 y HIS-2 salen juntas el mismo día.** No se anuncia nada a los clientes hasta cerrar HIS-0 y N2.
3. **Texto bajo el título del asistente, camino de historia:** «Esto crea un anuncio pagado que se muestra entre las historias de otras cuentas. Tu historia no cambia.»
4. **La acción se llama «Promocionar como anuncio» en todas partes**, también en el cajón de «Tu semana» (reemplaza «Hacer anuncio pagado»).
5. **«Publicada» es publicada en Instagram.** Una pieza solo en Facebook conserva «Anunciar sin publicar». Una pieza publicada por Qualify cuenta como publicada aunque el id de Meta sea NULL (QUA-111).
6. **HIS-0 lo coordina Herwin:** confirma que la cuenta publicitaria de Bianki está en COP y con permiso de anuncios, y pone la fecha. Ninguna llamada a Meta hasta entonces.

**Correcciones de hecho a este documento** (evidencia en la revisión del 2026-11-27):

- El enlace de «Promocionar» ya se ocultó en las historias con #853 (`Qualify/creative_pages.py:1087`, `Qualify/post_card.py:389`): la condición muerta `kind != "story"` ya no existe y D4 quedó superada por ese cambio.
- El vacío en el camino de historia es `STORY_EMPTY` (`Qualify/promotion_page.py:1100`), no `EMPTY_SOURCES`.
- El enlace en `main` dependía de `used_count > 0` (veces publicada por Qualify, `Qualify/planner_vm.py:1871`), no de «aprobada»; HIS-1 cambia esa regla.
- El defecto de «Anunciar sin publicar» solo ocurre si no hay fuente publicada en Instagram (`Qualify/promotion_provider.py:207-209`), no en todas las piezas.
- `m-25026350` no se cierra solo con HIS-0: también falta N2.
- El resumen dice «No: el anuncio sale tal como lo apruebas» (`Qualify/promotion_vm.py:80-81`), no «Ajustes por su cuenta: No».

## 1. Qué gana el dueño

Hasta el 2026-11-26 el dueño veía «Promocionar» en una historia, lo tocaba y llegaba a «No encontramos una publicación de Instagram que puedas promocionar…»; #853 escondió el enlace. Al terminar esta épica, «Promocionar como anuncio» en una historia aprobada lo lleva a un anuncio en historias con su pieza, su botón con enlace y, si lo quiere y Meta lo permite, con música. Si la historia no sirve como anuncio, se le dice por qué y qué hacer.

**Qué buscamos esta vez:** más negocios usando anuncios (que nadie se quede en un callejón sin salida), sin gastar un peso de más y sin que Meta cambie la pieza a espaldas del dueño.

## 2. Lo que ya existe (no se repite)

| Tema | Estado | Fuente |
|---|---|---|
| Anuncio solo en historias desde el archivo 9:16 de una pieza, con botón de enlace (`?formato=historia`, «Agregar un botón con enlace», entrada en «Tu semana») | Construido y en `main`; nunca probado contra Meta | `[V]` `ads/unpublished.py:294-308`, `ads/unpublished_service.py:490-491`, `docs/anuncios-pieza-sin-publicar.md:137-179`, m-25026350 (sigue en Backlog en Meegle) |
| Promocionar una publicación ya publicada por su id | Construido para publicaciones y reels; las historias quedan fuera a propósito | `[V]` `ads/wizard.py:320-321` |
| «¿Se puede promocionar una historia ya publicada por su id?» | **ABIERTO**, se decide en la prueba en vivo | `[V]` `docs/epica-anuncios-meta.md:328-331` |
| Prueba en vivo de anuncios (m-24828971, cuenta de Bianki por decisión del 2026-10-23) | Sin correr. No hay ninguna llamada real de anuncios a Meta hasta hoy | `[V]` `docs/anuncios-mvp-validacion.md:5`, comentarios del ticket |
| Mejoras de Meta por marca (cuatro permisos, apagados por defecto) | Construido. La música no está ni permitida ni prohibida: el esquema solo admite cuatro campos y rechaza el resto | `[V]` `ads/enhancements.py:10,28-35`, `docs/anuncios-mejoras-por-marca.md:23-24`; m-24828984 deja la música «fuera de alcance» |
| Puertas de gasto: todo nace en `PAUSED`, vista previa obligatoria, activación con confirmación de cobro, salud de la cuenta | Construido | `[V]` `ads/unpublished_service.py:400,427,687-715,760` |

**Trabajo reciente de Raul** (116 commits en anuncios desde el 2026-11-05): el anuncio en historias, la pieza sin publicar, el carrusel del Catálogo, el asesor de inversión. Solo tiene un PR abierto, el #849 (semáforo, m-25091390), que no toca fuentes, historias, ubicaciones ni la tarjeta de la galería. No hay choque. Archivos que esta épica comparte con él: `Qualify/promotion_state.py`, `Qualify/promotion_unpublished_provider.py`, `ads/unpublished*.py`. Conviene que estas historias las tome Raul o se coordinen con él una por una.

## 3. Lo que encontramos en el código

1. **El enlace de la tarjeta.** `kind` solo vale `image`, `video`, `carousel` o `pack`; el campo correcto es `is_story`. #853 ya escondió el enlace en historias (`~post.is_story`); HIS-1 lo vuelve a mostrar, y solo cuando habrá fuente. `[V]` `Qualify/creative_pages.py:1087`, `Qualify/post_card.py:389`, `Qualify/planner_vm.py:1239,2245-2262`
2. **Callejón sin salida.** Una historia publicada por Qualify no entra como fuente publicada (se excluye) y, si solo tiene archivo 9:16, tampoco como pieza sin publicar por la vía de parejas (pide 4:5 y 9:16). Con `?formato=historia` el vacío es `STORY_EMPTY`; sin el parámetro, `EMPTY_SOURCES`. `[V]` `Qualify/promotion_provider.py:192-217`, `Qualify/promotion_unpublished_provider.py:176-179`
3. **«Anunciar sin publicar» puede salir en una pieza que ya se publicó.** El filtro mira `content_drafts.published_media_id`, y ningún código de producción escribe esa columna (solo una prueba). Solo corre cuando no hay fuente publicada en Instagram: historias, piezas solo en Facebook, conexión purgada o reconectada, id no numérico. `[V]` `Qualify/promotion_unpublished_provider.py:55`, `Qualify/promotion_provider.py:207-209`, `ads/unpublished_repository.py:62`
4. **Las historias publicadas por Qualify sí guardan su id de Meta** (`publish_attempts.published_media_id`, tipo `STORIES`), pero no se guarda cuándo vencen (24 horas). Las que el dueño sube a mano con «Abrir en Instagram» no dejan ningún rastro. `[V]` `publishing/service.py:625,739`, `Qualify/gallery_state.py:431-438`
5. **No hay nada de audio en el código de anuncios**, y `boost_eligibility_info` no se lee en ninguna parte. `[V]`
6. **El anuncio en historias se niega si la marca tiene alguna mejora encendida** y hoy le dice al dueño «Ajustes por su cuenta: No». Ofrecer música de Meta cambia esa promesa. `[V]` `ads/unpublished_service.py:521-525`

## 4. Lo que dice Meta y lo que no sabemos

- `[S]` Una historia activa se puede promocionar pasando su id en `source_instagram_media_id`, después de leer `boost_eligibility_info`.
- `[S]` Publicaciones o reels con música con derechos de autor no se pueden usar como anuncio. `[H]` Una historia terminada a mano con una canción de moda probablemente no sea elegible.
- `[S]` La música automática se pide con `asset_feed_spec.audios: [{"type":"random"}]`. `[H]` Que Meta elija la canción y que aplique a historias y reels.
- `[S]` `music_generation` aparece en `creative_features_spec` sin descripción. No sabemos qué hace ni cuál es su valor por defecto cuando no se envía.
- `[S]` Un video con su propia pista de audio se acepta.
- **No sabemos:** si el anuncio en historias de hoy (`object_story_spec`, sin `asset_feed_spec`) admite `audios`; si la vista previa deja oír o al menos avisa de la música; las reglas de la biblioteca de sonidos por país (CO, VE, UY); la regla del sticker de enlace. Todo esto lo cierra la historia HIS-0.
- Un anuncio no es una historia orgánica: se paga, no aparece a los seguidores como la historia del perfil y termina con la campaña.

## 5. Decisiones para el fundador

### Decisión: ¿cómo terminamos «promocionar una historia»?

**Para el dueño del negocio:** deja de chocar con un mensaje de error y puede pagar para que su historia llegue a más gente con un botón que abre su enlace.

| Opción | Qué es | Para el dueño | Costo | Esfuerzo | ¿Se puede deshacer? | Riesgo principal | Evidencia |
|---|---|---|---|---|---|---|---|
| A. Dejar como está | El enlace sigue llevando al mensaje de error | Se frustra y no anuncia | $0 | Ninguno | Sí | Pierde confianza en «Promocionar» | `[V]` |
| B. Esconder el enlace en las historias | La tarjeta de una historia no ofrece promocionar | No choca, pero no descubre que puede anunciar su historia | $0 | Muy chico (una línea, dos archivos) | Sí | Esconde algo que ya está construido | `[V]` |
| **C. Llevar la historia al anuncio que ya existe, y sumar música por etapas (recomendada)** | El enlace abre el anuncio en historias con el archivo 9:16. Los casos que no sirven dicen por qué. La música entra solo después de la prueba en vivo | Un toque y llega al anuncio; sabe qué esperar | $0 de proveedor; el gasto del anuncio es del dueño en Meta | Chico primero (HIS-1 y HIS-2), medio después | Sí, cada paso | El anuncio en historias nunca se probó contra Meta | `[V]` + `[S]` |
| D. C + promocionar la historia publicada por su id | Además, usar la historia que ya está en Instagram | Conserva las reacciones de la historia original `[H]` | $0 | Medio, más guardar el vencimiento | Sí | Ventana de 24 horas; no sirve si la terminó a mano con una canción; solo sirve para las publicadas por Qualify | `[S]` sin probar |

**Recomendación:** C. Usa lo que ya está construido, cierra el callejón sin salida esta misma semana y no promete música hasta medirla. **La reabrimos si** la prueba HIS-0 muestra que el anuncio en historias no se puede crear como está, o si a los 30 días de salir ningún negocio lo usó.

### Las cinco preguntas, con recomendación

| # | Pregunta | Recomendación | Por qué |
|---|---|---|---|
| D1 | ¿Historia publicada por su id, o siempre un creativo nuevo 9:16? | **Siempre creativo nuevo 9:16** como camino base. Por id solo si HIS-0 lo confirma, y como historia aparte (HIS-6) | El archivo siempre está, no vence a las 24 horas y no arrastra una canción con derechos. Por id solo cubre historias publicadas desde Qualify y todavía activas |
| D2 | ¿Qué ve el dueño si la historia no sirve? | Un mensaje por cada causa, con el paso siguiente (textos en HIS-2). Nunca el vacío genérico | Hoy son cinco causas distintas con un solo texto |
| D3 | ¿Ofrecemos la música automática de Meta? | **Sí, pero apagada por defecto, anuncio por anuncio, y solo si HIS-0 confirma que funciona.** El video que ya trae sonido sale con su sonido sin tocar nada | Es la única música que la API permite agregar `[S]`. Hay que decirlo sin adornos: «Meta elige la canción. No puedes escogerla ni escucharla antes.» |
| D4 | ¿Cómo se porta el enlace de la tarjeta en una historia? | Abre el anuncio en historias con el texto «Promocionar como anuncio». *Superada:* #853 lo escondió el 2026-11-26 y HIS-1 + HIS-2 lo vuelven a mostrar juntas | Esconderlo y volver a mostrarlo son dos cambios para el mismo resultado |
| D5 | ¿Cambia la regla de mejoras por marca que rechaza la música? | **No cambiar la regla de marca.** La música es una elección de cada anuncio, registrada en la confirmación de cobro. Lo que sí cambia, y necesita tu firma, es que el resumen del anuncio deje de decir siempre «No: el anuncio sale tal como lo apruebas» cuando el dueño encendió la música | La regla protege la pieza aprobada. Una casilla por anuncio respeta eso; un permiso de marca encendería la música en todos los anuncios sin que el dueño lo vea cada vez |

**Decidido el 2026-11-26:** opción C, D1–D5 como están, tickets creados. Falta autorizar la prueba HIS-0.

## 6. Historias

Cada una es un Issue bajo la Feature «Épica — Promocionar una historia» (m-25130273). El ticket de Meegle es la versión viva; el texto de abajo es el refinado el 2026-11-27. Responsable: Raul, salvo HIS-0 (Herwin coordina).

| Historia | Ticket | Prioridad | Tamaño | Depende de |
|---|---|---|---|---|
| HIS-0 prueba en vivo | [m-25130278](https://project.larksuite.com/5h2wsx/issue/detail/25130278) | P1 | S | visto bueno del fundador; Herwin confirma la cuenta de Bianki y da la fecha |
| HIS-1 enlace de la tarjeta | [m-25130281](https://project.larksuite.com/5h2wsx/issue/detail/25130281) | P1 | S | — (sale junto con HIS-2) |
| HIS-2 mensajes cuando no sirve | [m-25130282](https://project.larksuite.com/5h2wsx/issue/detail/25130282) | P2 | M | HIS-1 (sale el mismo día) |
| HIS-3 «Anunciar sin publicar» en pieza publicada | [m-25130283](https://project.larksuite.com/5h2wsx/issue/detail/25130283) | P2 | S | — |
| HIS-4 sonido del video | [m-25130285](https://project.larksuite.com/5h2wsx/issue/detail/25130285) | P2 | S | HIS-0 |
| HIS-5 música elegida por Meta | [m-25130287](https://project.larksuite.com/5h2wsx/issue/detail/25130287) | P2 | L | HIS-0 |
| HIS-6 historia activa por su id | [m-25130290](https://project.larksuite.com/5h2wsx/issue/detail/25130290) | P3 | L | HIS-0 |
| N1 portada automática del video | [m-25142900](https://project.larksuite.com/5h2wsx/issue/detail/25142900) | P2 | M | — |
| N2 leer de vuelta el anuncio de historia en pausa | [m-25142901](https://project.larksuite.com/5h2wsx/issue/detail/25142901) | P2 | S | HIS-0 |
| N3 la historia se ve como anuncio y aviso de duplicado | [m-25142902](https://project.larksuite.com/5h2wsx/issue/detail/25142902) | P2 | M | HIS-1 |

### HIS-0 · Anuncios: prueba en vivo de historia y música (30 minutos, todo en pausa)

**Prioridad** P1 · **Tamaño** S · **Área** datos/arquitectura + fundador · **Coordina** Herwin · **Depende de** tu visto bueno expreso antes de cualquier llamada a Meta.

Como equipo de Qualify queremos saber qué acepta Meta de verdad antes de prometerle música o «tu misma historia» a un dueño.

**Antes de agendar** (Herwin; sin ninguna llamada a Meta hasta entonces) `[V]` `unpublished_service.py`, `unpublished_repository.py:70,150`
- La cuenta publicitaria de Bianki está en pesos colombianos (si no, todo el camino se niega: `_require_cop`). Se mira en la base.
- La conexión de Bianki tiene el permiso de anuncios concedido y la credencial vigente (`_permission_reason`).
- Herwin pone la fecha. El sí del fundador cubre que el paso 1 publica una historia real durante 24 horas en el perfil de Bianki.

**Pasos**, con la cuenta de Bianki, desde el Explorador de la API Graph o un script fuera del producto, salvo el paso 8:

1. Publicar una historia de prueba en el Instagram de Bianki desde Qualify y, aparte, tener a mano una historia subida a mano con una canción de Instagram.
2. Leer `boost_eligibility_info` de las dos historias (solo lectura).
3. Crear en `PAUSED` un anuncio con `source_instagram_media_id` = la historia de Qualify, solo en historias. Anotar la respuesta.
4. Crear en `PAUSED` el anuncio en historias tal como lo arma Qualify hoy, con un video 9:16 que tenga sonido. Mirar la vista previa: ¿conserva el sonido? Revisar la vista previa `INSTAGRAM_STORY` en iPhone (Safari) y en Android: es lo único que ve el dueño antes de pagar.
5. Repetir con una imagen 9:16 y `asset_feed_spec.audios: [{"type":"random"}]`. Anotar si Meta lo acepta con `object_story_spec`, qué devuelve al leer el creativo y si la vista previa avisa de la música.
6. Leer `creative_features_spec` del creativo: ¿qué valor trae `music_generation` cuando no se envía? Probar enviarlo en `OPT_OUT`.
7. Anotar qué devuelve `ad_review_feedback` mientras el anuncio sigue en pausa (`ads/client.py:491-492`).
8. Correr `UnpublishedImageService.prepare` real con `--tenant` de Bianki hasta la vista previa, sin confirmar, y leer de vuelta el anuncio en pausa con el código de Qualify. Eso prueba la ruta que se va a activar; lo que no coincida lo corrige N2.
9. Borrar todo lo creado y confirmar en el Administrador de anuncios que el gasto es cero.

**Criterios de aceptación**
- [ ] Antes de agendar quedan comprobados: cuenta de Bianki en COP, permiso de anuncios y credencial vigente, y Herwin puso la fecha.
- [ ] Cada punto tiene su respuesta real (sin tokens) en `docs/epica-anuncios-meta.md` §3 y en este documento §4.
- [ ] El «ABIERTO» de `docs/epica-anuncios-meta.md:328-331` queda cerrado con un sí o un no y su fuente.
- [ ] La lectura de vuelta con el código de Qualify queda probada y lo que difiere se pasa a N2.
- [ ] Nada se activa: todo queda en `PAUSED`, se borra, y el gasto de la cuenta no cambia.
- [ ] Queda dicho cuáles de HIS-4, HIS-5 y HIS-6 siguen, cambian o se cierran.

**Fuera de alcance:** el resto de la lista de m-24828971 (presupuesto mínimo, objetivos, Venezuela, Estados de WhatsApp). Si las dos pruebas se hacen el mismo día, se corren juntas.

### HIS-1 · Galería: «Promocionar como anuncio» en una historia abre el anuncio en historias

**Prioridad** P1 · **Tamaño** S · **Área** interfaz · **Sale junto con** HIS-2 el mismo día.

Como dueña de un local de comida quiero que, al tocar «Promocionar como anuncio» en una historia aprobada, se abra el anuncio con mi historia, para no quedarme frente a un mensaje de error.

**Criterios de aceptación**
- [ ] En «Aprobados» y en la tarjeta de publicación, una historia aprobada muestra «Promocionar como anuncio» y abre `/drafts/<id>/promote?formato=historia`, solo cuando el anuncio tendría fuente (`story_ad_ready`, calculado al cargar la galería, no por tarjeta). Una historia de video sin imagen 9:16 no muestra el enlace hasta que salga N1.
- [ ] Una publicación que no es historia se comporta igual que hoy.
- [ ] Entrar desde la tarjeta no quita nada de «Tu semana»; solo la entrada desde «Tu semana» lo hace.
- [ ] Bajo el título del asistente, en el camino de historia, se lee: «Esto crea un anuncio pagado que se muestra entre las historias de otras cuentas. Tu historia no cambia.»
- [ ] El asistente de historia se revisa en un teléfono de 360 px.
- [ ] `just ci-test` en verde.

**Fuera de alcance:** música, promocionar por id.

### HIS-2 · Anuncios: cuando la historia no sirve, decir por qué y qué hacer

**Prioridad** P2 · **Tamaño** M · **Área** interfaz + backend · **Depende de** HIS-1 (salen el mismo día).

Como dueño quiero entender por qué mi historia no se puede anunciar, para arreglarlo o seguir con otra.

Hoy el proveedor devuelve una lista vacía sin causa: un mensaje por causa exige que devuelva un motivo tipado (backend) y que la interfaz lo muestre. Algunos textos ya existen y están mal (`UNPUBLISHED_COP_ONLY`, `ENHANCEMENTS_ON`); se reescriben, no se crean otros.

**Criterios de aceptación** (un texto por causa, cada uno con prueba; el paso siguiente siempre se dice)
- [ ] Sin archivo vertical: «Esta historia no tiene un archivo vertical, de pantalla completa. Créala de nuevo en formato de historia.»
- [ ] Pieza editada después de aprobar, o archivos que ya no están guardados (retención) o aún se están moviendo: un texto para cada una.
- [ ] Sin cuenta publicitaria elegida, conexión inactiva, credencial vencida o sin permiso de anuncios: un texto para cada una, no el genérico.
- [ ] Enlace o botón guardado no válido (por ejemplo «Llamar» o botón de chat): dice cuál cambiar.
- [ ] Cuenta publicitaria en otra moneda: «Por ahora este anuncio solo funciona con cuentas publicitarias en pesos colombianos.» más el paso siguiente (hoy el texto dice «Publica primero la publicación», imposible para una historia).
- [ ] Marca con mejoras de Meta encendidas: «Tu marca permite que Meta ajuste los anuncios. Este anuncio sale tal cual lo aprobaste: apaga esos ajustes en "Tu marca" o usa otra pieza.»
- [ ] Salud de la cuenta (sin medio de pago, cuenta deshabilitada, zona horaria cambiada), rechazo de Meta en la validación, video aún en proceso o carga incierta, y vista previa vencida: un texto para cada una.
- [ ] El video de más de 60 segundos o 100 MB, el de menos de 1 segundo y la imagen de más de 8 MB se avisan al tocar «Ver cómo queda» (ahí se miden; la lista no guarda duración ni peso). El texto lo dice.
- [ ] Ningún texto de este camino dice «sin publicar» y el genérico «No encontramos una publicación de Instagram…» no sale en el camino de historia (`STORY_EMPTY` y los textos de arriba).
- [ ] Los textos pasan la revisión de `qualify-copy-es` y de UX antes del PR.

**Fuera de alcance:** quitar el límite de pesos colombianos; la portada del video (N1).

### HIS-3 · Anuncios: «Anunciar sin publicar» no se ofrece en una pieza que ya se publicó en Instagram

**Prioridad** P2 · **Tamaño** S · **Área** backend · **Depende de** nada.

Como dueño quiero que Qualify no me diga «sin publicar» de algo que ya está en mi Instagram, para saber qué estoy pagando.

Alcance real: el respaldo a «sin publicar» solo corre cuando no hay ninguna fuente publicada en Instagram. Los casos son la pieza publicada como historia, solo en Facebook, con la conexión purgada o reconectada, o con id no numérico. `content_drafts.published_media_id` queda sin uso: se deja y se comenta.

**Criterios de aceptación**
- [ ] «Publicada» se calcula desde `publish_attempts` y significa publicada **en Instagram** (se une con la conexión y se filtra `platform='instagram'`). Un intento publicado por Qualify cuenta aunque el id de Meta sea NULL (QUA-111). Una pieza solo publicada en Facebook sigue ofreciendo «Anunciar sin publicar».
- [ ] El filtro vale solo para el camino de parejas (4:5 y 9:16). El anuncio en historias sube siempre el archivo (D1) y no lo lleva: una historia con intento `STORIES` publicado sigue teniendo fuente en `?formato=historia` (prueba con base de datos).
- [ ] Una pieza publicada en Instagram por Qualify muestra «Promocionar como anuncio» o «Promocionar», nunca «Anunciar sin publicar».
- [ ] Pruebas con base de datos, con dos negocios para el aislamiento.
- [ ] Queda documentado en `docs/anuncios-pieza-sin-publicar.md` que una historia subida a mano con «Abrir en Instagram» no deja rastro y se trata como no publicada.
- [ ] Sin migración.

**Fuera de alcance:** registrar las historias subidas a mano; retirar la columna `published_media_id`.

### HIS-4 · Anuncios: el video de la historia sale con su sonido, y se dice

**Prioridad** P2 · **Tamaño** S · **Área** backend + interfaz · **Depende de** HIS-0 punto 4.

Como dueña quiero saber si mi anuncio va a sonar, para no llevarme una sorpresa.

**Criterios de aceptación**
- [ ] Si HIS-0 confirma que el sonido se conserva: el resumen del anuncio dice «Tu video saldrá con su sonido.» o «Tu video no tiene sonido.» según el archivo (prueba con un video con pista de audio y otro sin ella).
- [ ] La presencia de sonido se lee del archivo ya guardado (pista `soun` con `mp4_facts`), al preparar y no al listar, sin proveedor nuevo. Los clips del Catálogo salen sin sonido: el aviso «no tiene sonido» será frecuente.
- [ ] Si HIS-0 muestra que Meta quita el sonido, la historia se cierra con el veredicto escrito.

### HIS-5 · Anuncios: música elegida por Meta, casilla por anuncio

**Prioridad** P2 · **Tamaño** L (receta, consentimiento, lectura de vuelta, resumen y resultados) · **Área** backend + interfaz · **Depende de** HIS-0 puntos 5 y 6, y de las decisiones D3 y D5.

Como dueño de una heladería quiero que mi anuncio en historias tenga música aunque mi imagen no la traiga, sabiendo que la elige Meta.

**Criterios de aceptación**
- [ ] En el resumen del anuncio en historias hay una casilla apagada por defecto: «Agregar música elegida por Meta». Debajo: «Meta elige la canción de su biblioteca y puede cambiarla. No puedes escogerla ni escucharla antes.»
- [ ] Con la casilla encendida, el creativo lleva el campo de audio que HIS-0 confirmó; apagada, no lo lleva (prueba contra el fake).
- [ ] El resumen dice «Ajustes por su cuenta: solo la música» cuando está encendida.
- [ ] La casilla forma parte de lo que se confirma al cobrar: cambiarla después de la vista previa obliga a preparar otra.
- [ ] La lectura posterior a crear comprueba que Meta guardó lo pedido; si no coincide, no se activa.
- [ ] La versión del proceso cambia (`ad-story-image-v2` / `ad-story-video-v2`) y queda en el registro de la promoción.
- [ ] Las parejas conservan su huella (`docs/anuncios-pieza-sin-publicar.md:165-167`) y los resultados dicen qué pasa si Meta cambia la canción después de activar.
- [ ] La regla de marca (`ads/enhancements.py`) no cambia y sigue rechazando campos desconocidos.
- [ ] Si HIS-0 muestra que Meta no lo admite en historias, la historia se cierra con el veredicto escrito.

**Fuera de alcance:** elegir la canción, música en anuncios del feed, permiso de música por marca.

### HIS-6 · Anuncios: promocionar la historia que sigue activa (solo si HIS-0 dice que sí)

**Prioridad** P3 · **Tamaño** L (migración del vencimiento, tercer tipo de fuente, rama nueva en `load_sources`, resultados que unen `source_media_id` con el intento `STORIES`) · **Área** backend + interfaz · **Depende de** HIS-0 puntos 2 y 3, y de D1.

Como dueño quiero anunciar la misma historia que publiqué hoy desde Qualify, para no armar otra.

**Criterios de aceptación**
- [ ] Solo se ofrece para historias publicadas por Qualify hace menos de 24 horas; se guarda el vencimiento.
- [ ] Antes de ofrecerla se lee `boost_eligibility_info`; si Meta dice que no, se muestra: «Instagram no permite anunciar esta historia. Puedes crear el anuncio con el archivo de la pieza.» y se ofrece ese camino.
- [ ] Pasa por las mismas puertas: `PAUSED`, vista previa, confirmación de cobro.
- [ ] Dice qué pasa si el dueño borra la historia en Instagram antes de 24 horas, o si vence con el asistente abierto o entre la vista previa y la activación.
- [ ] Si HIS-0 dice que no se puede, la historia se cierra y el veredicto queda en `docs/epica-anuncios-meta.md`.

### N1 · Creativo: portada automática para la historia de video ([m-25142900](https://project.larksuite.com/5h2wsx/issue/detail/25142900))

**Prioridad** P2 · **Tamaño** M · **Área** creativo · **Depende de** nada.

Como dueña de un local con historias en video quiero promocionar mi historia sin subir una portada, para que el anuncio salga con la imagen de mi video.

**Criterios de aceptación**
- [ ] Una historia de video sin imagen 9:16 en su versión recibe una portada sacada del propio video (prueba con un MP4 de ejemplo).
- [ ] La portada queda ligada a la misma versión aprobada y guarda su procedencia (archivo de origen y versión del proceso).
- [ ] Una historia de video con portada automática cumple `story_ad_ready` y muestra «Promocionar como anuncio».
- [ ] Una historia que ya trae imagen 9:16 no cambia.
- [ ] Prueba con base de datos y dos negocios; respeta la retención (ADR 39).

**Fuera de alcance:** elegir o subir una portada a mano.

**Cómo quedó (2026-11-27):** la portada la hace el `creative-worker` en su pasada de mantenimiento (cada minuto, hasta 5 por pasada): cualquier historia aprobada cuya versión actual tiene un MP4 9:16 y ninguna imagen 9:16 recibe un cuadro del video (ffmpeg, 1 s adentro, tamaño completo). Así sirve para las historias que se aprueben y para las que ya estaban aprobadas, sin tocar la aprobación ni la carga de la galería. Se guarda en su propia tabla `piece_story_covers` (0191), no en `image_assets`, para que ninguna otra pantalla la vea como un archivo más de la pieza; solo la leen el anuncio en historias y su preparación (`creative/story_covers.py`, `PIECE_FILES`). El objeto vive junto al video (misma retención). Si el video no da un cuadro, queda `failed` y la historia sigue con «video_without_cover».

### N2 · Anuncios: leer de vuelta el anuncio de historia real en pausa ([m-25142901](https://project.larksuite.com/5h2wsx/issue/detail/25142901))

**Prioridad** P2 · **Tamaño** S · **Área** backend · **Depende de** HIS-0.

Como dueño quiero que, tras la vista previa y la confirmación de cobro, mi anuncio en historias se active, para no quedarme con una campaña en pausa que no avanza.

**Criterios de aceptación**
- [ ] La lectura de vuelta de un anuncio de historia real en pausa coincide con lo pedido y no niega la activación por una diferencia de forma (prueba con la respuesta real de Meta anotada en HIS-0).
- [ ] Si algo difiere de verdad, sigue negando y lo dice.
- [ ] Todo queda en `PAUSED`; esta historia no activa nada.
- [ ] `docs/anuncios-pieza-sin-publicar.md` y m-25026350 reflejan el resultado; con N2 y HIS-0 cerrados, m-25026350 pasa a Done.

### N3 · Anuncios: la historia se ve como anuncio y se avisa antes de crear un duplicado ([m-25142902](https://project.larksuite.com/5h2wsx/issue/detail/25142902))

**Prioridad** P2 · **Tamaño** M · **Área** interfaz + backend · **Depende de** HIS-1.

Como dueña quiero ver mi anuncio de historia como tal en «Anuncios» y que me avisen si ya tengo uno de esa historia, para no pagar dos veces lo mismo. Hoy la clave de pedido vive en la sesión (`Qualify/promotion_state.py:1496`): recargar o abrir otro teléfono crea otra campaña en pausa.

**Criterios de aceptación**
- [ ] En «Anuncios», el anuncio de historia muestra la miniatura vertical, la etiqueta «Anuncio en historias» y un enlace a la pieza.
- [ ] La pieza dice que ya tiene un anuncio en historias.
- [ ] Antes de crear otro de la misma historia, un aviso lo dice y deja elegir seguir o ir al existente; vale al recargar y desde otro dispositivo (prueba con dos sesiones).
- [ ] Textos revisados con `qualify-copy-es` y UX; el aviso se ve bien en 360 px.

**Fuera de alcance:** medir el origen del anuncio (tarjeta o «Tu semana»); para el criterio de reapertura de los 30 días se usa `ad_promotions` con `kind` `unpublished-story-*`.

## 7. Fuera de alcance de la épica

- Música en anuncios de reels o del feed (primero se mide en historias).
- Elegir una canción concreta o usar canciones de moda: la API no lo permite `[S]`.
- Registrar las historias que el dueño sube a mano.
- Enlace, encuesta o música en historias orgánicas (la API de publicación no publica stickers).
- Estados de WhatsApp como ubicación (m-24789525).
- Cuentas publicitarias que no sean en pesos colombianos para este anuncio.

## 8. Orden sugerido

HIS-1 y HIS-2 juntas, el mismo día (el enlace solo sale con fuente; HIS-1 sola dejaría el vacío en producción) · HIS-3 en paralelo · N1 para que las historias de video entren · HIS-0 cuando Herwin dé la fecha, tras las comprobaciones previas · N2 después de HIS-0 · N3 tras HIS-1 · HIS-4 y HIS-5 según lo que diga HIS-0 · HIS-6 solo si aplica. Nada se anuncia a los clientes hasta cerrar HIS-0 y N2. **m-25026350 pasa a Done cuando se cierran HIS-0 y N2**, no solo HIS-0.
