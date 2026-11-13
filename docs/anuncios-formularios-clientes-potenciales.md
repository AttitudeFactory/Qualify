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

## Campaña de clientes potenciales (segunda entrega, backend)

El asistente de promoción admite ahora un anuncio de clientes potenciales que usa un
formulario **ya enviado** a Meta. No es un recorrido paralelo: reutiliza `WizardForm`,
`PromotionWizard`, `LiveWizardGateway`, la aprobación inmutable, la creación en pausa con
reclamo/`unknown`, la vista previa y la activación solo con confirmación explícita.

- `WizardForm.lead_form` (`ads/lead_ads.py`, `LeadFormTarget`) + `lead_cta`
  (`SIGN_UP`, `LEARN_MORE` o `GET_QUOTE`); el enlace queda vacío. La pantalla obtiene el
  destino con `published_lead_form(tenant_id, form_id)`, que solo devuelve formularios en
  estado `published` cuya conexión sigue activa, con la misma Página y versión de acceso.
- Petición aprobada: campaña `OUTCOME_LEADS`; conjunto `optimization_goal=LEAD_GENERATION`,
  `billing_event=IMPRESSIONS`, `destination_type=ON_AD`, `promoted_object={page_id}`;
  creativo de la publicación de Instagram existente con `object_id` = Página y
  `call_to_action={type, value:{lead_gen_form_id}}`. El formulario queda congelado en
  `request_snapshot.lead_form_snapshot` y forma parte del hash de la aprobación; las
  promociones sin formulario conservan exactamente su forma y su hash.
- Solo se acepta un formulario de la misma conexión, marca, Página y versión de acceso que
  la publicación promocionada (comprobado al validar, antes de crear y en la inserción,
  con `FOR SHARE` sobre formulario, conexión y publicación).
- La recepción atribuye el lead a la promoción por
  `request_snapshot->'lead_form_snapshot'->>'meta_form_id'` y ahora también acepta el
  creativo de publicación existente (CTA y Página en el propio creativo, sin
  `object_story_spec`).
- Sin migración nueva: `ad_promotions` ya admite el objetivo y un enlace vacío.

**No medido en vivo.** Que Meta acepte `OUTCOME_LEADS` + `ON_AD` con
`source_instagram_media_id` y `lead_gen_form_id`, y la forma exacta en que devuelve ese
creativo al leerlo, no se ha comprobado contra la API real. La validación `validate_only`
previa a crear y la verificación remota antes de activar fallan cerradas si Meta responde
distinto. `QUALITY_LEAD` no se ofrece todavía.

Limitación conocida: una pieza cuyo botón guardado no es «Más información» sigue sin poder
promocionarse por este asistente, también como anuncio de clientes potenciales.

## Qué falta del ticket completo

- Pantalla Reflex para elegir el formulario y el botón en el asistente.
- Medir en vivo el recorrido de campaña descrito arriba con una Página autorizada.
- Si se necesita WhatsApp, completar el consentimiento explícito descrito arriba. Hoy no
  existe ninguna marca de «autoriza WhatsApp» en el formulario, así que el tercer criterio
  del ticket sigue abierto.
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
la migración reversible `0143`, posterior a la `0142` de actualización de enlaces de reels.
La numeración se corrigió tras la colisión de revisiones al integrar ambos cambios;
la `0142` de reels ya aplicada se conserva. Las pruebas locales usan únicamente datos sintéticos,
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
