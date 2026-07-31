
## Findings recorded by agents (append-only)

### [2026-07-29 23:26] gtm-specialist — App Mode (Development/Live) degrada la visibilidad del contenido publicado — eje distinto al nivel de acceso

Hallazgo de campo con doble fuente, relevante para el ADR de modelo de acceso en curso y para el dogfooding de Parte 4-A. NO interpretado: la lectura es del principal-architect.

[P] Meta, App Modes (https://developers.facebook.com/docs/development/build-and-test/app-modes, acceso 2026-07-29): 'Any data generated while an app is in Development mode, such as test posts, can only be seen by role users.' Y: 'data generated while in Development mode such as test posts will become visible to all app users once you switch [to Live].'

[P] Postiz, doc de proveedor Facebook (https://docs.postiz.com/providers/facebook, acceso 2026-07-29), paso 8 de su guia de instalacion: 'Set app mode to Live. Change the App Mode from Development to Live. If you do not do this then posts made via the API will display for yourself but will not be visible for other users.' Y: 'posts with media are only visible to app developers/testers - everyone else sees the post without the image.'

POR QUE IMPORTA: docs/fase0-zernio-mercado.md 1.1-bis (escrito por el architect, 2026-07-24) afirma 'no existe en la doc de Meta ningun mecanismo por el que el nivel de acceso degrade la visibilidad'. Esa afirmacion es sobre el NIVEL DE ACCESO (Standard/Advanced) y sigue en pie. App Mode (Development/Live) es un eje SEPARADO, y en ese eje la doc de Meta si describe degradacion de visibilidad. No es una contradiccion, es un segundo eje que 1.1-bis no cubrio. Si el plan de cliente cero (Parte 4-A, publicar reels en cuentas propias) asume que una app en Development publica contenido publico normal, ese supuesto necesita verificacion en el eje App Mode, no solo en el eje access level. Es especifico de media, que es exactamente lo que Parte 4-A publica.

PENDIENTE que no pude cerrar por desktop research: si pasar a Live mode exige App Review y/o Business Verification, o es un toggle self-serve. Postiz dice 'for public applications, you will need to verify your business', sin precisar si eso es requisito del toggle Live o del acceso avanzado. Esa es la pregunta que decide si el eje App Mode es un bloqueo real para cliente cero o solo un paso de configuracion.

### [2026-07-30 08:29] gtm-specialist — Meta Tech Provider EXIGE App Review + Business Verification: es el output del tramite, no un atajo

Relevante para ADR 29, que cita la definicion de Tech Provider de las Platform Terms. Este es el lado del ONBOARDING de ese mismo status, con doc primaria. NO interpretado.

[P] Meta, Get Started for Tech Providers (https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers, acceso 2026-07-30):

QUE CONCEDE (capacidad tecnica real, no un badge):
- 'Advanced access to whatsapp_business_messaging' - 'required to send messages on behalf of your clients'
- 'Advanced access to whatsapp_business_management' - 'required to access your clients WABAs'
- 'can independently provide all WhatsApp messaging services to clients who you have onboarded'

QUE EXIGE PARA ENTRAR:
1. 'A Meta app with the WhatsApp use case and a connected business portfolio'
2. 'Verify your business with Meta'
3. App Review con permisos avanzados aprobados
Y la frase que ordena la secuencia: 'Your business must be verified before you can start the app review process.'

CONSECUENCIA (factual): el status de Tech Provider es el RESULTADO de pasar App Review + Business Verification, no un sustituto. No los reemplaza, no los acelera, no exime. Los presupone. Luego no existe ninguna ruta 'hazte Tech Provider para ahorrarte la revision'.

CONTRASTE con el otro programa de Meta - [P] Meta Business Partner Program Policies (https://www.facebook.com/business/marketing-partners/become-a-partner/fmp-product-policies, acceso 2026-07-30): unico requisito explicito 'Todos los participantes del Programa deben tener un negocio verificado'. El documento NO menciona App Review, niveles de acceso, permisos, cuotas ni tipos de token. Su contenido son obligaciones, restricciones de uso de badge/logo, confidencialidad y Advertiser Rewards (creditos que pertenecen al cliente final, no al partner). Es un programa de badge/marketing.

OBSTACULO DE VERIFICACION que es hallazgo en si: el Meta Business Partner Directory (facebook.com/business/partner-directory/search) EXIGE LOGIN - devuelve 'Debes iniciar sesion para continuar' (verificado 2026-07-30 con user-agent de navegador). Un comprador no puede verificar de forma anonima la afirmacion de partner de ningun vendor. Eso explica estructuralmente por que la autodeclaracion funciona en esta categoria.

### [2026-07-30 08:40] gtm-specialist — V-TP-7: dos textos del corpus local de Meta se contradicen sobre el caso de cliente unico

Para V-TP-7 (architect). NO resuelto - transcripcion. Los dos textos ya estan en el repo, en reference/meta-instagram-platform/, y por lo que veo no se habian cruzado entre si. Detalle completo en docs/research-modelo-acceso-tech-provider.md seccion 10.

TEXTO A - apunta a categoria autodeclarada, no a status concedido.
reference/meta-instagram-platform/documentation/resp-plat-initiatives/data-access-renewal/content/data-protection-section.md, lineas 293-301 y 378-382 (cuestionario de Data Protection Assessment):
- 'Tech Provider definition: An individual or business that has been granted access to Meta APIs for the purpose of creating, maintaining and removing integrations on behalf of other individuals or businesses. This includes individuals or businesses that create a single integration on behalf of an individual client or multiple clients.'
- linea 301: 'Because this app allows people or businesses (clients) to access and use Platform Data, it means that you are a Tech Provider.'
- linea 382: 'You indicated above that this app allows people or businesses (clients) to access and use Platform Data. This means that you are a Tech Provider.'
Observacion factual: la determinacion se DERIVA de la respuesta que el propio desarrollador dio en un cuestionario de cumplimiento. Forma gramatical declarativa, no concesiva. El contexto es un assessment de proteccion de datos, no una solicitud de programa con aprobacion.

TEXTO B - apunta a que el gate depende del ESCENARIO, y deja un hueco donde esta el cliente uno.
reference/meta-instagram-platform/documentation/instagram-platform/app-review.md, lineas 11-16, tabla 'Development scenarios' completa:
- 'My app is only for a business I own or manage' + No login o Instagram Login -> Standard Access -> Not required
- 'My app is only for a business I own or manage' + No login o Facebook Login -> Standard Access -> Not required
- 'I am a Tech Provider and my app serves MULTIPLE businesses' + Instagram Login -> Advanced -> Required
- 'I am a Tech Provider and my app serves MULTIPLE businesses' + Facebook Login -> Advanced -> Required
Tres observaciones factuales: (1) la exencion aparece para LAS DOS ramas de login, no solo una; (2) el gate esta redactado sobre el escenario 'serves multiple businesses', no sobre la etiqueta Tech Provider a secas; (3) NO EXISTE fila para 'soy Tech Provider y mi app sirve a un solo cliente'. La taxonomia es binaria y el cliente uno de Qualify no encaja en ninguna de las dos: es un negocio que el fundador NO posee ni gestiona, y es UN cliente, no varios.

LA TENSION: la definicion (texto A) incluye explicitamente 'a single integration on behalf of an individual client'; la tabla de escenarios (texto B) solo dispara App Review Required para 'multiple businesses'. Los dos son de Meta y no dicen lo mismo sobre el caso de un cliente unico. Cual gobierna es V-TP-7.

DATO COLATERAL: app-review.md:85 - 'To request Advanced Access to certain permissions, you need to make at least 1 successful API call.' El flujo de App Review presupone llamadas API con exito ANTES de la revision. No deduzco nada sobre BISU de aqui.

AVISO APARTE - trampa de grafias del scope de publicacion (CLAUDE.md la advierte; aqui va un caso concreto): corpus local app-review.md:49 dice 'instagram_business_content_publishing'; la doc de Zernio (producto en produccion) dice 'instagram_business_content_publish'; y app-review.md:35 usa 'instagram_content_publishing' en la rama Facebook Login. Tres grafias observadas entre dos fuentes buenas. Resolver empiricamente contra el endpoint de autorizacion, nunca contra doc.

