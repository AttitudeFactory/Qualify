# Conversaciones procedentes de anuncios

Entrega de `m-24828980`. Los chats de WhatsApp e Instagram Direct pueden mostrar
«Vino de un anuncio» cuando un mensaje recibido incluye una referencia publicitaria
admitida y puede relacionarse con una promoción propia y su destino aprobado.
No se deduce la procedencia del texto, una dirección web, el nombre de una campaña
ni el hecho de que el cliente y el anuncio pertenezcan al mismo negocio.

## Qué se relaciona

La unidad de atribución es **el mensaje recibido**. Una referencia válida se guarda
una sola vez para ese mensaje y conserva su promoción, negocio, conexión de origen,
conexión de destino, fecha y versión del proceso. Un reintento no sustituye una
atribución ya guardada. La escritura se ejecuta también cuando el mensaje ya existía:
si el proceso se interrumpe entre guardar el mensaje y guardar su procedencia,
reprocesar la notificación completa el segundo paso sin duplicar mensajes.

Una conversación puede contener mensajes procedentes de distintos anuncios a lo
largo del tiempo. Cada mensaje conserva su referencia; no se cambia retroactivamente
todo el hilo al último anuncio. El detalle de una promoción cuenta **hilos distintos
con al menos un mensaje atribuido visible**. Varios mensajes del mismo anuncio en un
hilo cuentan una conversación. Un hilo puede contar en distintas promociones si
recibió referencias válidas de cada una. Este recuento de Qualify no es el resultado
de atribución de Meta, una venta, un número de clientes únicos ni una ventana de
conversión publicitaria.

La etiqueta utiliza hasta 160 caracteres del texto que Qualify envió al publicar
la pieza original. No utiliza el titular, texto, imágenes ni direcciones que traiga
la referencia remota. Si falta ese texto, muestra una etiqueta genérica. Las lecturas
de los mensajes enriquecen el resultado con una consulta por lote, no una por mensaje.

## Prueba de pertenencia y consentimiento

Instagram utiliza los propietarios congelados por la admisión de notificaciones
con consentimiento. La prueba exige admisión y firma verificadas, una sola conexión
propietaria y la misma época de credenciales. Un evento antiguo sin propietario
demostrable no se asocia a quien conecte la cuenta posteriormente.

WhatsApp conserva su recepción original de bytes; este cambio añade una prueba
**prospectiva** de propiedad publicitaria, separada de ese comportamiento histórico.
Solo al insertar una notificación nueva, una función estrecha fija el número, WABA,
negocio, conexión, versión de credencial y momento de conexión activos. No se rellenan
eventos anteriores ni se vuelve a fijar propietario al recibir un duplicado. Una
notificación recibida sin dueño comprobable no adquiere uno porque el número se
conecte o cambie después. El papel público no lee identidades; el papel de la aplicación
no puede insertar estas pruebas ni ejecutar la función que las resuelve. El procesador
dispone solo de la función de lectura acotada por el identificador del evento.

El servidor comprueba que el identificador del mensaje, remitente y referencia están
en esa notificación concreta, y que corresponden al mensaje y contraparte del hilo.
También comprueba cuenta, negocio, publicación original y destino aprobado exactos.
Una promoción de Instagram y un chat de WhatsApp usan conexiones distintas: compartir
negocio no basta. La solicitud original debe incluir `messaging_snapshot`, con ambas
conexiones y versiones, página y número, y coincidir con los parámetros aprobados.
Las promociones antiguas sin esa información no adquieren un destino supuesto.
Los destinos vacíos conservan el hash original de aprobaciones anteriores.

Las tablas nuevas tienen `tenant_id`, claves compuestas, RLS habilitado y forzado,
política `NULLIF` y permisos acotados, en la migración `0129`, posterior a `0128`.
Purgar o revocar cualquiera de las dos conexiones elimina las atribuciones derivadas.
La retención normal del evento bruto elimina su prueba temporal, pero no borra la
procedencia ya validada del mensaje: queda un identificador estable de evidencia,
sin copiar el contenido bruto. Eliminar el mensaje o la promoción sí elimina la
atribución. No se guardan identificadores personales de clic, direcciones remotas,
textos de referencia ni credenciales en estas tablas.

## Comprobación del destino de WhatsApp

El asistente hace una lectura autenticada de la página para comprobar
`has_whatsapp_number` y `whatsapp_number`, y los compara con el único número vigente
del negocio. Revalida sesión, pertenencia, página, conexión, credenciales y números
después de la respuesta, sin mantener una transacción mientras espera a Meta.
Un resultado explícito de número ausente o diferente muestra cómo vincular el número
del negocio a la página en Meta Business Suite. Un campo ausente, error de permisos
o fallo de lectura muestra que **no se pudo comprobar**, nunca que está desvinculado.
Si hay varios números, queda pendiente elegir y comprobar uno.

Solo una coincidencia explícita y exacta entre página y número ofrece WhatsApp, y la
tarjeta lleva entonces el destino exacto (`MessagingTarget`) que la promoción congela.
Instagram Direct usa la misma cuenta de la publicación. Las preguntas y menús
existentes de los chats conservan su comportamiento.

## Crear y activar anuncios que abren un chat

Tercer objetivo del asistente de promoción, junto al enlace y al formulario
(`WizardForm.messaging` + `WizardForm.greeting`). Reutiliza el mismo camino: público,
presupuesto, fechas y permisos de la marca; `validate_only` exacto de los cuatro
objetos; creación **en pausa** con la recuperación de reclamos existente; vista previa;
activación solo con la aprobación y el consentimiento explícitos; lectura remota de
cada campo comparado antes de activar. La comprobación de página y número se repite
en vivo en la preparación y otra vez al activar: si el número cambió o dejó de estar
vinculado, no se activa.

| Objeto | Campo y valor | Fuente |
|---|---|---|
| Campaña | `objective=OUTCOME_ENGAGEMENT` | SDK 26.0.0 `campaign.py` (`Objective.outcome_engagement`); guías de Meta para WhatsApp e Instagram |
| Conjunto | `optimization_goal=CONVERSATIONS`, `billing_event=IMPRESSIONS` | SDK 26.0.0 `adset.py`; ambas guías exigen `IMPRESSIONS` |
| Conjunto | `destination_type=WHATSAPP` / `INSTAGRAM_DIRECT` | SDK 26.0.0 `adset.py` (`DestinationType`) |
| Conjunto | `promoted_object{page_id, whatsapp_phone_number}` (Instagram: solo `page_id`) | SDK 26.0.0 `adpromotedobject.py`; guías |
| Creatividad | `object_id` (página), `instagram_user_id`, `source_instagram_media_id`, `call_to_action` | SDK 26.0.0 `adcreative.py`; ejemplo «publicación existente» de ambas guías |
| Creatividad | WhatsApp: `{"type":"WHATSAPP_MESSAGE","value":{"link":"https://api.whatsapp.com/send","app_destination":"WHATSAPP"}}` | Guía click-to-WhatsApp; `WHATSAPP_MESSAGE` en el enum del SDK |
| Creatividad | Instagram: `{"type":"INSTAGRAM_MESSAGE","value":{"link":"https://www.instagram.com"}}` | Guía click-to-Instagram (todos sus ejemplos de creatividad) |
| Creatividad | `page_welcome_message`: texto JSON `VISUAL_EDITOR`, `version=2`, `landing_screen_type=welcome_message`, `media_type=text`, `customer_action_type=ice_breakers`, `message{text, ice_breakers[{title}]}` | Campo y tipo `string`: SDK 26.0.0 `adcreative.py`; estructura: guías de Meta, variante «ice breakers» |

Guías consultadas el 2026-11-13:
[click-to-WhatsApp](https://developers.facebook.com/docs/marketing-api/ad-creative/messaging-ads/click-to-whatsapp)
y [click-to-Instagram](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-instagram).
SDK: [facebook-python-business-sdk 26.0.0](https://github.com/facebook/facebook-python-business-sdk/tree/26.0.0/facebook_business/adobjects).

**Saludo.** El dueño escribe, por marca, un saludo (hasta 300 caracteres) y de 1 a 4
preguntas sugeridas (hasta 80 caracteres cada una). Cada guardado es una versión nueva
e inmutable en `ad_message_greetings` (migración `0164`, RLS forzado, sin `UPDATE`),
con quién lo escribió, cuándo y la versión del proceso. Guardar el mismo texto no crea
otra versión; editar sobre una versión vieja se rechaza. La promoción congela la
versión elegida en `greeting_snapshot`, que entra en el hash de la aprobación; la
base de datos comprueba que esa versión exista con ese texto exacto. Las promociones
sin objetivo de chat conservan su instantánea y su hash (prueba fijada). No se envía
la respuesta automática opcional de cada pregunta: las respuestas siguen siendo
asistidas.

**Brechas medidas, no supuestas.**

- `INSTAGRAM_MESSAGE` no está en el enum del SDK 26.0.0 (sí `MESSAGE_PAGE`); la guía
  actual lo usa en todas las creatividades. Lo decide el `validate_only` exacto.
- Los ejemplos de Meta para **publicaciones existentes** no muestran
  `page_welcome_message`; el SDK lo admite como campo de nivel superior de la
  creatividad. Si Meta no lo acepta, el `validate_only` falla y no se crea nada; si lo
  devuelve distinto al leerlo, no se activa. En el formulario HTTP, un texto JSON y un
  objeto viajan igual, así que la discrepancia de la guía (objeto o texto) no cambia
  lo enviado.
- Los límites de longitud del saludo y las preguntas son de Qualify: Meta no los
  publica para anuncios (el máximo de 4 preguntas viene de la API de Ice Breakers de
  Instagram).
- **Antes de habilitar la pantalla**, confirmar en una cuenta de pruebas cómo devuelve
  Meta `page_welcome_message` y `promoted_object.whatsapp_phone_number` al leerlos. Hoy
  la lectura acepta el JSON como texto u objeto, en cualquier orden de claves, y el
  número con «+» o espacios; cualquier otra diferencia bloquea la activación.
  Las promociones con enlace o formulario no piden ni comparan `page_welcome_message`.
- Nada de esto se ha probado contra una cuenta real: no hubo escrituras en Meta.

**Botón de la pieza.** Un anuncio de chat arma su propio botón con el chat elegido, así
que una pieza guardada con botón de chat o de llamada sí puede abrir un chat; los
anuncios con enlace o formulario siguen rechazándola, cada uno con su mensaje.

**Pantalla.** Mientras `CHAT_GOAL_ON_SCREEN` sea falso, las tarjetas de destino
conservan el aviso actual («todavía no está habilitada») y `available=False`, aunque
el servidor ya tenga el destino exacto. La pantalla que añada el objetivo debe cambiar
esa constante. Cada destino lleva `reason_code` (`ready`, `unlinked`, `unknown`,
`no_number`, `several_numbers`) para que la pantalla muestre «Unir mi WhatsApp» y lleve
a Tus redes.

## Evidencia y límites

El subconjunto de Instagram deriva del corpus oficial de Meta conservado en
`reference/meta-instagram-platform/documentation/business-messaging/instagram-messaging/webhooks.md`,
apartado de mensajes, y `documentation/instagram-platform/webhooks/examples.md`:
`message.referral` contiene `ad_id`, `source=ADS` y `type=OPEN_THREAD`.
[Referencia original de Meta](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/webhooks).
Un enlace `ig.me` con `ref` o una referencia a una tienda no se interpreta como anuncio.

El subconjunto de WhatsApp (`referral.source_type=ad` y `source_id`) está declarado
en el [SDK oficial de WhatsApp](https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/types/webhooks.ts)
y sus [enumeraciones](https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/types/enums.ts).
Ese repositorio está archivado desde 2023: acredita un contrato histórico, **no una
observación de un mensaje publicitario en 2026**. La documentación actual no estuvo
accesible durante esta sesión. Los casos desconocidos quedan sin atribución.

Los campos de la página proceden del
[SDK de Marketing de Meta 26.0.0](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/page.py).
Los tipos no prueban que una cuenta real conceda los permisos o que la combinación
de anuncio sea aceptada. No se crearon anuncios, se enviaron mensajes ni se hicieron
escrituras en Meta durante el desarrollo.

| Criterio | Entregado | Pendiente |
|---|---|---|
| Un mensaje con referencia se relaciona con su promoción | Procesadores reales, prueba de propiedad, destino aprobado, persistencia y pruebas de base de datos | Verificación con mensajes publicitarios reales y cuenta autorizada |
| Avisar si el número no está vinculado a la página | Lectura de la página, comparación exacta y guía; desconocido separado de desvinculado | Validación de permisos y respuesta real de la cuenta del negocio |
| Mostrar el anuncio de origen en los chats | Procedencia junto al mensaje, texto original y vínculo interno a la promoción; recuento de hilos en resultados | Revisión visual móvil con navegador y prueba de extremo a extremo |
| Crear anuncios que abren chats | Objetivo de chat en el asistente: validación exacta, creación en pausa, activación con consentimiento, saludo versionado en la aprobación; probado con HTTP simulado | Prueba con cuenta real, pantalla del objetivo y del editor del saludo |
