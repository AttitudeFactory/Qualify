# Formularios de Meta y personas interesadas

Ticket: m-24828981. Primera entrega técnica. No acredita acceso efectivo a Meta ni cierra
el recorrido completo de anuncios con formulario.

## Qué incluye

En «Anuncios», «Formularios» permite preparar un formulario con preguntas de contacto y
preguntas personalizadas, español latinoamericano o de España, enlace HTTPS de privacidad
y mensaje de agradecimiento. Guardar un borrador es local. Enviar el formulario a Meta es
una confirmación independiente: se conserva la versión exacta revisada, la persona que la
aprueba y la fecha. No se crea ni activa una campaña publicitaria.

Una vez enviado y comprobado el identificador de Página, la versión no se modifica. Un
resultado incierto queda bloqueado para evitar una segunda creación a ciegas; debe
comprobarse en Meta. Esta entrega no implementa la conciliación de una creación incierta
ni la importación de formularios creados fuera de Qualify.

«Activar recepción de datos» es otra acción explícita. Conserva los campos que la propia
aplicación ya tenía suscritos en la Página y añade `leadgen`. La suscripción de la aplicación
al objeto Página/campo `leadgen` en el panel de Meta sigue siendo un requisito externo.
Los permisos y las asignaciones reales de la aplicación y la Página también deben estar
vigentes; haber marcado una casilla de permisos no constituye esa comprobación.

La recepción reutiliza el webhook firmado, su cola y la propiedad congelada del evento.
Solo un formulario asociado al negocio y a una de esas conexiones puede recibir sus datos.
Se comprueban Página, formulario, identificación del lead, acceso actual y, cuando existe,
el anuncio remoto. La promoción se atribuye únicamente si existe una relación local
comprobable; los leads orgánicos o de prueba pueden no tener anuncio ni promoción.

Cada `leadgen_id` produce como máximo una respuesta por negocio, aunque llegue por webhook
y por respaldo a la vez. La clave no mezcla personas de diferentes negocios. El contacto
se presenta en «Interesados», con su procedencia y preguntas, y puede marcarse como atendido.

## Respaldo y privacidad

«Comprobar datos recibidos» realiza consultas de lectura a `/FORM_ID/leads` por
`time_created`, con cinco minutos de solapamiento. Cada petición procesa hasta veinte
páginas de cien elementos; conserva el cursor y la ventana para continuar sin saltar la
cola. La marca de la última ventana completa solo avanza cuando todas sus páginas fueron
procesadas. Un fallo o respuesta malformada no se presenta como consulta completa.
El respaldo es manual en esta entrega; no existe un proceso periódico nuevo.

Nunca se sigue una dirección `paging.next`: se utiliza exclusivamente el cursor acotado
sobre la ruta fija de Graph. Las operaciones de Página usan un cliente autenticado de esa
Página, derivado dentro del resolvedor de credenciales; el permiso USER principal se
conserva y se usa por separado para comprobar anuncios. Ningún token sale en las vistas,
los registros de actividad o los enlaces.

Una respuesta de formulario con correo o teléfono **no acredita consentimiento para
WhatsApp**. Las respuestas Meta tienen su propia tabla, admiten contactos sin teléfono y
no pasan por la entrada web que exige consentimiento. No se importan a los permisos de
WhatsApp ni muestran un botón para escribir por ese canal. Esta entrega no ofrece captar
ese consentimiento: hace falta implementar y verificar por separado el texto versionado,
la casilla y su respuesta positiva. El borrado de una conexión incluye estas respuestas,
respetando el aislamiento de los demás negocios.

## Qué falta del ticket completo

- Implementar y probar un recorrido específico de campaña `OUTCOME_LEADS`, destino
  `ON_AD` y creativo con `lead_gen_form_id`, sin debilitar las garantías de gasto del
  recorrido actual de visitas al sitio web. Esto es trabajo de implementación pendiente,
  no una consecuencia de carecer de una cuenta de pruebas.
- Si se necesita WhatsApp, completar el consentimiento explícito descrito arriba.
- Comprobar permisos efectivos, suscripción de aplicación y Página, y un lead de prueba
  real que llegue en menos de cinco minutos. El App Review de `leads_retrieval` queda fuera
  de este ticket, según su descripción.

## Prueba manual pendiente con una Página autorizada

1. Entrar con una persona que administre el negocio y su Página. Verificar los permisos
   efectivos y el acceso a leads, sin compartir tokens en el chat.
2. Preparar un formulario con política real y datos sintéticos. Revisar los cinco pasos,
   guardar y enviar la versión confirmada. Comprobar en Meta que pertenece a la Página
   elegida. No crear ni activar anuncios para esta prueba.
3. Confirmar que la aplicación está suscrita al objeto Página/campo `leadgen` y activar
   explícitamente la recepción de datos desde el formulario de Qualify.
4. Crear un lead sintético con la herramienta de pruebas de leads de Meta y medir desde
   su creación hasta que aparece en «Interesados». Registrar la duración y el resultado.
5. Ejecutar el respaldo manual y comprobar que el mismo lead sigue siendo una sola fila,
   que conserva su marca de contacto y que no se habilitó ningún permiso de WhatsApp.
6. Guardar la evidencia sin datos personales reales ni credenciales. Si falla acceso,
   suscripción o entrega, registrar el paso concreto; no cerrar el ticket por las
   simulaciones aprobadas.

## Evidencia técnica y fuentes

El 9 de noviembre de 2026 se consultó el ticket vivo: continuaba en Backlog, asignado a
Raul y con el alcance E3. Esta entrega se construyó desde `main` en `7ec60f34` y añade
la migración reversible `0142`. Las pruebas locales usan únicamente datos sintéticos,
PostgreSQL de pruebas, transporte HTTP simulado y Redis 15; no son pruebas de Meta.

Las guías de creación y recepción de Meta respondieron 429 durante la investigación.
Se contrastaron las estructuras con estas fuentes primarias disponibles:

- [SDK oficial: Página](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py).
- [SDK oficial: formulario](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/leadgenform.py).
- [SDK oficial: lead](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/lead.py).
- [Comprobación de recepción de Meta Incubator](https://github.com/facebookincubator/catalogue-of-api-solutions/blob/main/solutions/leads/leads-retrieval-set-up-checker.md).
- [Ejemplo oficial de webhook de leads](https://github.com/fbsamples/lead-ads-webhook-sample).

El SDK y los ejemplos acreditan estructuras de integración, no que la configuración real
de Qualify tenga acceso ni que Meta acepte cada combinación de anuncio.
