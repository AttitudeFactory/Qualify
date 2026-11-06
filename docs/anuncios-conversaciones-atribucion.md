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

Las tarjetas son informativas. **No habilitan crear ni activar anuncios para chats**.
El contrato normalizado del servidor y la aprobación persistente se prueban con datos
simulados. Todavía deben comprobarse con Meta los parámetros completos de creación,
compatibilidad de piezas, permisos, pagos y elegibilidad. Tampoco se añade un editor
del saludo o de preguntas iniciales del anuncio. Las preguntas y menús existentes
de los chats conservan su comportamiento.

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
| Crear anuncios que abren chats | Contrato de destino y aprobación inmutable preparados y comprobados con datos simulados | Creación/activación real, compatibilidad, saludo y preguntas iniciales |
