# Preparar la promoción de una publicación de Instagram (m-24828976)

Esta entrega permite preparar el anuncio desde una pieza publicada o desde su evento
del Planificador. El cliente elige la publicación exacta, revisa el destino y el botón
«Más información», prepara el público y fija un presupuesto **total** en COP y fechas
con zona horaria. Preparar esos datos no crea anuncios ni genera cobros.

## Estado y límites de la entrega

La preparación de pantalla es funcional con los datos de publicaciones de Qualify.
Las funciones públicas que crearían una vista previa remota o activarían una promoción
permanecen **bloqueadas**. Configurar `QUALIFY_META_ADS_CONFIG_ID` por sí solo no levanta
este bloqueo. No hay una variable que habilite un simulador para clientes reales.

Falta implementar y verificar con evidencia de Meta la lectura de elegibilidad de la
publicación, la comprobación completa de pagos, la búsqueda y validación de la ciudad,
las reglas del público de vivienda y Advantage+, y la conversión del mínimo aplicable
a moneda, objetivo y duración. Tener un origen de fondos registrado no demuestra que
Meta vaya a aceptar un cargo. Tampoco se ha comprobado el permiso real de la aplicación.
Estas dependencias están relacionadas con m-24828971, m-24828975, m-24828977 y m-24828978.

El mínimo y el alcance desconocidos se muestran como pendientes; no se sustituyen por
valores de prueba. El enlace queda vacío cuando la pieza no tiene uno: la persistencia
de enlace y botón de m-24828975 no se da por terminada en este trabajo.

El criterio de prueba real de m-24828976 **sigue pendiente**. Requiere autorización
explícita del fundador en Bianki o Polette, configuración y verificaciones previas.
Esta entrega no ha creado, activado ni financiado anuncios reales y no permite cerrar
el ticket como una integración comprobada de punta a punta contra Meta.

## Publicación y pertenencia

`ads.wizard.list_promotion_sources` lee intentos publicados de Instagram vinculados al
evento y a la pieza por tenant, marca y conexión. Excluye historias, intentos no publicados
y conexiones en eliminación. Cuando se indica un evento concreto, un evento inexistente
no se sustituye por otra publicación. Varias publicaciones de una pieza se eligen
explícitamente; su cuenta, texto publicado y fecha proceden del intento, no de un borrador
que pudo cambiar después. Por ahora sólo se reconoce la procedencia persistida mediante
eventos del Planificador; otros orígenes sin ese vínculo no se infieren por similitud.

La pantalla usa la identidad de la sesión y descarta resultados tardíos al cambiar de
negocio. La aprobación no debe aceptar una identidad elegida por el navegador. Los caminos
de ejecución inyectados exigen un autorizador de pertenencia y lo repiten antes de cada
cambio remoto de estado. La composición pública continúa bloqueada mientras falta el
adaptador real verificado.

## Flujo comprobado mediante doble de pruebas

`ads.wizard_workflow.PromotionWizard` recibe explícitamente repositorios, una fuente
autorizada de publicaciones, el enlace de cuenta, un comprobador de requisitos y el
autorizador. Las pruebas inyectan `FakeMarketingClient`; la aplicación no lo elige
automáticamente. `VerifiedChecks` contiene evidencia normalizada para el negocio: no es
una afirmación sobre la forma de una respuesta de Meta. El mínimo es total para las fechas
solicitadas; un futuro adaptador real debe calcularlo con la regla vigente, nunca usar
sin conversión un mínimo diario. La evidencia desconocida, vencida o negativa bloquea.

El flujo simulado comprueba `OUTCOME_TRAFFIC`, destino `WEBSITE`, `LINK_CLICKS`, creativo
con `source_instagram_media_id` e `instagram_user_id`, botón `LEARN_MORE` y presupuesto
`lifetime_budget`. Son vocabulario y supuestos del contrato a validar en la prueba real,
no una prueba de que Meta acepte esa combinación para cualquier publicación o país.

La creación reutiliza la persistencia de m-24828974 y mantiene campaña, conjunto y anuncio
en `PAUSED`. Una vista previa identificada por UUID guarda el hash de la solicitud,
el contenido de la vista, el comprobante normalizado, su vencimiento y el usuario que
la preparó. El cliente debe ver la vista y el presupuesto total antes de autorizar el cargo.
El código de pantalla trata el HTML de vista previa como contenido no confiable y admite
únicamente un marco restringido, sin insertar HTML arbitrario en la página.

## Confirmación, idempotencia y resultado desconocido

La migración `0117` añade `ad_promotion_activations` con tenant, RLS habilitado y forzado,
política `NULLIF` explícita, claves compuestas y comprobaciones de estado. La solicitud,
la vista y la evidencia son inmutables. Sólo quien preparó esa revisión puede confirmar
su presupuesto mediante una confirmación explícita; la solicitud no se puede cambiar
reutilizando su clave. La revisión vencida exige preparar una solicitud nueva.

La confirmación se guarda y confirma en una transacción independiente antes de llamar
a la plataforma. Una única reclamación de ejecución gana aunque lleguen dos peticiones.
Se actualizan anuncio, conjunto y finalmente campaña; cada llamada vuelve a comprobar
la pertenencia, el vencimiento de la revisión y de su evidencia, y que la fecha de inicio
no haya pasado. Esa comprobación se repite dentro del cliente **después** de esperar
el bloqueo o límite de solicitudes de la cuenta, inmediatamente antes de enviar el cambio.
Si venció durante la espera, no se envía el cambio y se conserva la reclamación: repetir
la confirmación sólo permite consultar qué ocurrió, no vuelve a activar recursos.
El estado local pasa a `active` sólo tras leer que los tres recursos
existentes figuran como `ACTIVE`. Esto indica el estado solicitado a Meta; no demuestra
aprobación, entrega ni resultados.

Un fallo o una respuesta perdida conserva la reclamación y produce estado desconocido.
La repetición sólo consulta los identificadores ya guardados; no recrea recursos, no
restablece la reclamación y no reactiva un recurso pausado por un operador. Una devolución
de error o una revocación durante el proceso tampoco justifican volver a gastar a ciegas.

La bajada de la migración conserva los recursos de Meta sin tocarlos; sólo elimina las
estructuras locales nuevas y adapta los estados a los admitidos por `0114`. No constituye
un procedimiento para pausar anuncios remotos. El despliegue de esta entrega mantiene
bloqueadas las escrituras reales.

## Verificación

Pruebas sin red: `packages/api/tests/test_promotion_wizard.py`. Cubren creación pausada,
vista y consentimiento, rechazo previo del presupuesto insuficiente, caducidad,
solicitud inmutable, cambio de fuente y retirada de pertenencia durante la activación.

Pruebas de Postgres: `packages/api/tests/test_promotion_wizard_db.py`. Comprueban RLS,
inmutabilidad, vencimiento, reclamación concurrente, supervivencia ante rollback exterior
y procedencia exacta de las publicaciones. La reversibilidad se comprueba en una base
aislada, antes de escribir datos de las pruebas.
