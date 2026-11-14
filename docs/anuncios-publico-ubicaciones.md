# Público y lugares del anuncio — m-24828977

Esta entrega completa la preparación local del público del asistente y sus consultas de solo lectura a Meta. No habilita crear ni activar anuncios reales. Los controles de permisos, pagos, elegibilidad, presupuesto y políticas verificados siguen siendo obligatorios e independientes.

## Selección y guardado

Se busca un país, región o ciudad y se guarda su identificador, nombre y país, junto con edades, género, intereses, selección de ampliación del público, categoría Vivienda y lugares donde se muestra el anuncio. Los nombres sirven para reconstruir la pantalla; los identificadores alimentan la segmentación.

«Automáticas» significa posiciones automáticas dentro de Facebook e Instagram: se envían ambas plataformas y se omiten sus listas de posiciones. No permite incorporar WhatsApp ni Threads por omisión. La alternativa manual admite inicio, historias, reels y explorar de Instagram, e inicio de Facebook. Que una posición exista en el esquema del SDK no garantiza su disponibilidad para una publicación concreta; su validación de ejecución permanece pendiente.

El borrador preparatorio se guarda en `ad_audience_drafts`, separado de la aprobación de gasto. La clave incluye publicación, pieza, cuenta publicitaria y versión de credencial; también se valida la marca y el negocio. Hay RLS forzado, referencias compuestas y control de versión para impedir que una sesión sobrescriba cambios de otra. La eliminación de la cuenta a través del procedimiento existente elimina estos borradores por cascada.

Al preparar una promoción aprobada mediante la composición explícita de pruebas, la segmentación compilada se guarda en `ad_promotions.targeting` y la selección exacta en `request_snapshot.audience_snapshot`. Se comprueba que ambas coincidan. La solicitud de promoción continúa siendo inmutable: guardar un público no inventa aprobación, fechas ni presupuesto. Las pruebas de PostgreSQL cubren el guardado y la reconstrucción exactos.

## Vivienda, radios y verificación

El compilador de Vivienda construye la segmentación desde una lista permitida. Nunca incluye edades, género, intereses ni exclusiones aunque existan valores antiguos en el borrador. La interfaz limpia las opciones que oculta. Siempre se envía explícitamente `targeting_automation.advantage_audience`.

El intervalo local de radio de 1 a 80 km es solamente un límite del formulario preparatorio. **No es una afirmación sobre los radios que Meta acepta.** No se pudo verificar una regla actual aplicable a cada país para ciudades o Vivienda. Por eso un público de Vivienda (y, desde la actualización de abajo, un radio de ciudad menor de 17 km) muestra estimación no disponible y no consulta alcance con una política inventada. El formulario nuevo exige una comprobación independiente de políticas y la huella exacta del público antes de ejecutar, aun si Meta devuelve una estimación.

Los puntos personalizados en mapa quedan pendientes. No se añade un control que prometa una regla geográfica aún no verificada.

### Promoción real con radio e intereses (actualización del 14 de noviembre de 2026)

La promoción real ya admite un radio alrededor de un punto (`AudienceDraft.point`: latitud, longitud y una etiqueta que nunca se envía a Meta), un radio alrededor de una ciudad e intereses. Vivienda, el público ampliado, las mejoras automáticas y los públicos personalizados siguen rechazados como antes.

Campos y límites, tomados de la [referencia de segmentación básica de Meta](https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting) consultada ese día:

- Punto: `geo_locations.custom_locations[{latitude, longitude, radius, distance_unit: "kilometer"}]`, radio «de 1 a 80 kilómetros». Se envía solo el punto; añadir su país ampliaría la zona al país entero. El país elegido queda como contexto de la pantalla. No se envía `location_types`: Meta lo da por `["home", "recent"]` cuando falta.
- Ciudad con radio: `cities[{key, radius, distance_unit}]`, radio «de 17 a 80 kilómetros». El borrador local conserva su rango antiguo (1 a 80) para no romper borradores guardados; la promoción real y la pantalla exigen 17.
- Intereses: `flexible_spec[{interests: [{id}]}]`, ids obtenidos solo de `search?type=adinterest`.
- Vigencia de intereses: `act_<id>/targetingvalidation` (`valid`) y `search?type=targetingoptionstatus` (`current_status`; la [referencia de búsqueda](https://developers.facebook.com/docs/marketing-api/audiences/reference/targeting-search) dice que `DEPRECATING` no puede usarse en conjuntos nuevos). Solo `valid=true` + `NORMAL` cuenta como disponible. La promoción real vuelve a preguntar justo antes de validar y antes de crear; cualquier otra respuesta, incluida la ausencia del id, bloquea con un mensaje que nombra los intereses. Meta no documenta reemplazos, así que no se proponen; la pantalla ofrece «intereses parecidos» con `adinterestsuggestion`.

Lectura de comprobación del conjunto de anuncios: se pide `targeting` y cada clave aprobada debe volver igual. Se aceptan únicamente estas normalizaciones y cualquier otra clave extra bloquea la activación: `geo_locations.location_types == ["home", "recent"]` (el valor por omisión documentado) y etiquetas descriptivas junto a un id o un punto (`name` en intereses; `name`, `region`, `region_id`, `country` en ciudades; `name`, `country`, `primary_city_id`, `region_id` en puntos). Los intereses se comparan como conjunto de ids. Las coordenadas admiten una diferencia de 0,000001 grados, la precisión que se aprueba: Meta no documenta redondeo y la tolerancia solo absorbe la serialización. Otro punto, otro radio u otra unidad bloquean.

No verificado con Meta real: la forma exacta en que Meta devuelve `targeting` (claves añadidas, redondeo de coordenadas, radio en otra unidad), la respuesta de `targetingoptionstatus` con una cuenta de cliente y los códigos de error de intereses retirados durante `validate_only`. Si Meta añade una clave no listada, la activación falla cerrada y queda en pausa hasta revisar esta lista.

## Consultas y estimación

Las búsquedas usan `search` con `adgeolocation`, `adinterest` o `adinterestsuggestion`. Los intereses se contrastan mediante la lectura `targetingvalidation`: solo un `valid` booleano asociado al identificador establece disponibilidad actual. Un valor ausente, una respuesta desconocida o un fallo dejan la vigencia sin confirmar. Un interés no disponible no puede compilarse en un público ordinario. No se infiere una fecha de retiro ni se interpreta otro nombre de campo como equivalente.

La estimación usa `reachestimate` con la segmentación completa. Solo se muestra un intervalo cuando `estimate_ready` es verdadero y `users_lower_bound` y `users_upper_bound` son enteros no negativos y ordenados. Una respuesta pendiente, desconocida, incompleta o un error no produce una cifra de muestra. La huella del público acompaña el resultado para rechazar respuestas que ya no correspondan a la selección actual.

Todas las consultas y guardados exigen una sesión real de usuario, membresía vigente y la relación exacta entre pieza, publicación, conexión, marca y cuenta seleccionada. Se revisa esa relación antes y después de las consultas remotas y después de cargar un borrador. Los permisos o credenciales de publicación orgánica no sustituyen la credencial de anuncios. No se persisten tokens, respuestas completas de Meta ni información de tarjetas.

## Evidencia y límites

Revisión del SDK oficial de Meta, etiqueta `26.0.0`, el 4 de noviembre de 2026:

- [Segmentación](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/targeting.py): campos geográficos y posiciones.
- [Ampliación del público](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/targetingautomation.py): `advantage_audience` explícito.
- [Cuenta publicitaria](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adaccount.py): contratos de consulta de alcance y validación.
- [Alcance estimado](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adaccountreachestimate.py): intervalo y disponibilidad.
- [Validación de segmentación](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adaccounttargetingunified.py): `valid` booleano.
- [Comunicado histórico de equidad de Meta](https://about.fb.com/news/2022/06/expanding-our-work-on-ads-fairness/): restricciones de edad y género en vivienda; no demuestra un radio actual universal para Colombia, Venezuela o Uruguay.

La documentación de desarrolladores respondió con límites de acceso durante esta revisión. El SDK acredita nombres y tipos, no la elegibilidad actual de una cuenta o publicación. No se hicieron llamadas con credenciales de clientes. Las pruebas usan clientes simulados explícitos y PostgreSQL aislado.

Estado de los criterios del ticket: la persistencia/reconstrucción y la omisión de campos restringidos cuentan con pruebas. La actualización del alcance está conectada a consultas de lectura, con resultados no disponibles cuando falta evidencia. Antes de considerar el ticket validado con Meta faltan comprobar radios por país/categoría, Vivienda, posiciones por publicación y anuncios, puntos en mapa, y avisos de fechas de retiro. La integración de públicos personalizados, similares y estados de WhatsApp sigue fuera de alcance.
