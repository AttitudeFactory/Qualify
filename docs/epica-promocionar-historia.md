# Épica — Terminar el flujo de promocionar una historia

**Fecha:** 2026-11-26 · **Estado:** `[BORRADOR · sin tickets · espera la decisión del fundador]` · **Meegle:** sin crear (se crea solo con el sí del fundador) · **Épica madre:** anuncios de Meta, [m-24828970](https://project.larksuite.com/5h2wsx/story/detail/24828970)

Etiquetas de evidencia: `[V]` código o documento leído en `main` (9894d611) · `[S]` documentación de Meta leída el 2026-11-26, sin probar · `[H]` inferido.

## 1. Qué gana el dueño

Hoy el dueño ve «Promocionar» en una historia de «Aprobados», lo toca y llega a «No encontramos una publicación de Instagram que puedas promocionar…». Al terminar esta épica, ese mismo toque lo lleva a un anuncio en historias con su pieza, su botón con enlace y, si lo quiere y Meta lo permite, con música. Si la historia no sirve como anuncio, se le dice por qué y qué hacer.

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

1. **El enlace de la tarjeta no distingue historias.** La condición `post.kind != "story"` nunca se cumple: `kind` solo vale `image`, `video`, `carousel` o `pack`. El campo correcto es `is_story`. `[V]` `Qualify/creative_pages.py:1106-1109`, `Qualify/post_card.py:387-389`, `Qualify/planner_vm.py:1239,2245-2262`
2. **Callejón sin salida.** Una historia publicada por Qualify no entra como fuente publicada (se excluye) y, si solo tiene archivo 9:16, tampoco como pieza sin publicar (pide 4:5 y 9:16). Resultado: el vacío `EMPTY_SOURCES`. `[V]` `Qualify/promotion_provider.py:192-217`, `Qualify/promotion_unpublished_provider.py:176-179`
3. **«Anunciar sin publicar» puede salir en una pieza que ya se publicó.** El filtro mira `content_drafts.published_media_id`, y ningún código de producción escribe esa columna (solo una prueba). Afecta a todas las piezas, no solo a las historias. `[V]` `Qualify/promotion_unpublished_provider.py:55`, `ads/unpublished_repository.py:62`
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
| D4 | ¿Cómo se porta el enlace de la tarjeta en una historia? | Abre el anuncio en historias con el texto «Promocionar como anuncio». Mientras sale HIS-1 no hace falta esconderlo: HIS-1 es de un día | Esconderlo y volver a mostrarlo son dos cambios para el mismo resultado |
| D5 | ¿Cambia la regla de mejoras por marca que rechaza la música? | **No cambiar la regla de marca.** La música es una elección de cada anuncio, registrada en la confirmación de cobro. Lo que sí cambia, y necesita tu firma, es que el resumen del anuncio deje de decir siempre «Ajustes por su cuenta: No» cuando el dueño encendió la música | La regla protege la pieza aprobada. Una casilla por anuncio respeta eso; un permiso de marca encendería la música en todos los anuncios sin que el dueño lo vea cada vez |

**Necesito que decidas:** (1) opción A, B, C o D; (2) si aceptas D1–D5 como están o cuál cambias; (3) si autorizas la prueba HIS-0 en la cuenta publicitaria de Bianki; (4) si creo los tickets en Meegle.

## 6. Historias

Cada una será un Issue bajo una Feature «Épica — Promocionar una historia», enlazada a m-24828970. Dueño sugerido: Raul (backend e interfaz de anuncios), salvo HIS-0.

### HIS-0 · Anuncios: prueba en vivo de historia y música (30 minutos, todo en pausa)

**Prioridad** P1 · **Tamaño** S · **Área** datos/arquitectura + fundador · **Depende de** tu visto bueno expreso antes de cualquier llamada a Meta.

Como equipo de Qualify queremos saber qué acepta Meta de verdad antes de prometerle música o «tu misma historia» a un dueño.

Con la cuenta publicitaria de Bianki, desde el Explorador de la API Graph o un script fuera del producto (no existe ninguna receta para esto y no se crea código de producto):

1. Publicar una historia de prueba en el Instagram de Bianki desde Qualify (necesita tu sí: es una publicación real) y, aparte, tener a mano una historia subida a mano con una canción de Instagram.
2. Leer `boost_eligibility_info` de las dos historias (solo lectura).
3. Crear en `PAUSED` un anuncio con `source_instagram_media_id` = la historia de Qualify, solo en historias. Anotar la respuesta.
4. Crear en `PAUSED` el anuncio en historias tal como lo arma Qualify hoy, con un video 9:16 que tenga sonido. Mirar la vista previa: ¿conserva el sonido?
5. Repetir con una imagen 9:16 y `asset_feed_spec.audios: [{"type":"random"}]`. Anotar si Meta lo acepta con `object_story_spec`, qué devuelve al leer el creativo y si la vista previa avisa de la música.
6. Leer `creative_features_spec` del creativo: ¿qué valor trae `music_generation` cuando no se envía? Probar enviarlo en `OPT_OUT`.
7. Borrar todo lo creado y confirmar en el Administrador de anuncios que el gasto es cero.

**Criterios de aceptación**
- [ ] Cada punto tiene su respuesta real (sin tokens) en `docs/epica-anuncios-meta.md` §3 y en este documento §4.
- [ ] El «ABIERTO» de `docs/epica-anuncios-meta.md:328-331` queda cerrado con un sí o un no y su fuente.
- [ ] Nada se activa: todo queda en `PAUSED`, se borra, y el gasto de la cuenta no cambia.
- [ ] Queda dicho cuáles de HIS-4, HIS-5 y HIS-6 siguen, cambian o se cierran.

**Fuera de alcance:** el resto de la lista de m-24828971 (presupuesto mínimo, objetivos, Venezuela, Estados de WhatsApp). Si las dos pruebas se hacen el mismo día, se corren juntas.

### HIS-1 · Galería: «Promocionar» en una historia abre el anuncio en historias

**Prioridad** P1 · **Tamaño** S · **Área** interfaz · **Depende de** nada.

Como dueña de un local de comida quiero que, al tocar «Promocionar» en una historia aprobada, se abra el anuncio con mi historia, para no quedarme frente a un mensaje de error.

**Criterios de aceptación**
- [ ] En «Aprobados» y en la tarjeta de publicación, una pieza con `is_story` muestra «Promocionar como anuncio» y abre `/drafts/<id>/promote?formato=historia` (prueba de la pantalla en `creative_pages.py` y `post_card.py`).
- [ ] La condición muerta `kind != "story"` desaparece de los dos archivos.
- [ ] Una publicación que no es historia se comporta igual que hoy.
- [ ] Bajo el título del asistente se lee: «Esto crea un anuncio pagado en historias. No cambia la historia que ya publicaste.»
- [ ] `just ci-test` en verde.

**Fuera de alcance:** música, promocionar por id.

### HIS-2 · Anuncios: cuando la historia no sirve, decir por qué y qué hacer

**Prioridad** P2 · **Tamaño** S · **Área** interfaz + backend · **Depende de** HIS-1.

Como dueño quiero entender por qué mi historia no se puede anunciar, para arreglarlo o seguir con otra.

**Criterios de aceptación** (un texto por causa; cada uno con prueba)
- [ ] Sin archivo vertical: «Esta historia no tiene un archivo vertical (9:16). Créala de nuevo en formato de historia.»
- [ ] Video sin portada: «A este video le falta la portada. Elige una portada y vuelve a intentar.»
- [ ] Video de más de 60 segundos o de más de 100 MB: «El video es muy largo o muy pesado para un anuncio en historias. Usa uno de hasta 60 segundos.»
- [ ] Cuenta publicitaria en una moneda que este anuncio aún no admite: «Por ahora este anuncio solo funciona con cuentas publicitarias en pesos colombianos.»
- [ ] Marca con mejoras de Meta encendidas: «Tu marca permite que Meta ajuste los anuncios. Este anuncio sale tal cual lo aprobaste: apaga esos ajustes en "Tu marca" o usa otra pieza.»
- [ ] El texto genérico «No encontramos una publicación de Instagram…» no vuelve a salir en el camino de historia.
- [ ] Los textos pasan la revisión de `qualify-copy-es` y de UX antes del PR.

**Fuera de alcance:** quitar el límite de pesos colombianos.

### HIS-3 · Anuncios: «Anunciar sin publicar» no se ofrece en una pieza que ya se publicó

**Prioridad** P2 · **Tamaño** M · **Área** backend · **Depende de** nada (es un defecto de toda la pieza sin publicar, no solo de historias).

Como dueño quiero que Qualify no me diga «sin publicar» de algo que ya está en mi Instagram, para saber qué estoy pagando.

**Criterios de aceptación**
- [ ] «Publicada» se calcula desde `publish_attempts` (intento publicado con id de Meta), no desde `content_drafts.published_media_id`, que nadie escribe (prueba con base de datos, dos negocios para comprobar el aislamiento).
- [ ] Una pieza publicada por Qualify muestra «Promocionar» o «Promocionar como anuncio», nunca «Anunciar sin publicar».
- [ ] Queda documentado en `docs/anuncios-pieza-sin-publicar.md` que una historia subida a mano con «Abrir en Instagram» no deja rastro y por eso se trata como no publicada.
- [ ] Sin migración, o con migración reversible y RLS si hace falta una columna.

**Fuera de alcance:** registrar las historias subidas a mano.

### HIS-4 · Anuncios: el video de la historia sale con su sonido, y se dice

**Prioridad** P2 · **Tamaño** S · **Área** backend + interfaz · **Depende de** HIS-0 punto 4.

Como dueña quiero saber si mi anuncio va a sonar, para no llevarme una sorpresa.

**Criterios de aceptación**
- [ ] Si HIS-0 confirma que el sonido se conserva: el resumen del anuncio dice «Tu video saldrá con su sonido.» o «Tu video no tiene sonido.» según el archivo (prueba con un video con pista de audio y otro sin ella).
- [ ] La presencia de sonido se lee del archivo ya guardado, sin proveedor nuevo.
- [ ] Si HIS-0 muestra que Meta quita el sonido, la historia se cierra con el veredicto escrito.

### HIS-5 · Anuncios: música elegida por Meta, casilla por anuncio

**Prioridad** P2 · **Tamaño** M · **Área** backend + interfaz · **Depende de** HIS-0 puntos 5 y 6, y de las decisiones D3 y D5.

Como dueño de una heladería quiero que mi anuncio en historias tenga música aunque mi imagen no la traiga, sabiendo que la elige Meta.

**Criterios de aceptación**
- [ ] En el resumen del anuncio en historias hay una casilla apagada por defecto: «Agregar música elegida por Meta». Debajo: «Meta elige la canción de su biblioteca y puede cambiarla. No puedes escogerla ni escucharla antes.»
- [ ] Con la casilla encendida, el creativo lleva el campo de audio que HIS-0 confirmó; apagada, no lo lleva (prueba contra el fake).
- [ ] El resumen dice «Ajustes por su cuenta: solo la música» cuando está encendida.
- [ ] La casilla forma parte de lo que se confirma al cobrar: cambiarla después de la vista previa obliga a preparar otra.
- [ ] La lectura posterior a crear comprueba que Meta guardó lo pedido; si no coincide, no se activa.
- [ ] La versión del proceso cambia (`ad-story-image-v2` / `ad-story-video-v2`) y queda en el registro de la promoción.
- [ ] La regla de marca (`ads/enhancements.py`) no cambia y sigue rechazando campos desconocidos.
- [ ] Si HIS-0 muestra que Meta no lo admite en historias, la historia se cierra con el veredicto escrito.

**Fuera de alcance:** elegir la canción, música en anuncios del feed, permiso de música por marca.

### HIS-6 · Anuncios: promocionar la historia que sigue activa (solo si HIS-0 dice que sí)

**Prioridad** P3 · **Tamaño** M · **Área** backend + interfaz · **Depende de** HIS-0 puntos 2 y 3, y de D1.

Como dueño quiero anunciar la misma historia que publiqué hoy desde Qualify, para no armar otra.

**Criterios de aceptación**
- [ ] Solo se ofrece para historias publicadas por Qualify hace menos de 24 horas; se guarda el vencimiento.
- [ ] Antes de ofrecerla se lee `boost_eligibility_info`; si Meta dice que no, se muestra: «Instagram no permite anunciar esta historia. Puedes crear el anuncio con el archivo de la pieza.» y se ofrece ese camino.
- [ ] Pasa por las mismas puertas: `PAUSED`, vista previa, confirmación de cobro.
- [ ] Si HIS-0 dice que no se puede, la historia se cierra y el veredicto queda en `docs/epica-anuncios-meta.md`.

## 7. Fuera de alcance de la épica

- Música en anuncios de reels o del feed (primero se mide en historias).
- Elegir una canción concreta o usar canciones de moda: la API no lo permite `[S]`.
- Registrar las historias que el dueño sube a mano.
- Enlace, encuesta o música en historias orgánicas (la API de publicación no publica stickers).
- Estados de WhatsApp como ubicación (m-24789525).
- Cuentas publicitarias que no sean en pesos colombianos para este anuncio.

## 8. Orden sugerido

HIS-1 (no depende de nada) → HIS-0 (cuando el fundador dé la fecha) → HIS-2 y HIS-3 en paralelo → HIS-4 y HIS-5 según lo que diga HIS-0 → HIS-6 solo si aplica. Al cerrar HIS-0, pasar m-25026350 a Done: su único criterio pendiente es el veredicto escrito.
