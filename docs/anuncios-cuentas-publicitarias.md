# Conectar una cuenta publicitaria (m-24828972)

La conexión orgánica sigue usando el permiso y la credencial de Página que ya tenía.
«Autorizar anuncios» inicia un consentimiento adicional para una conexión de Instagram
existente. La intención viaja dentro del estado firmado, con vencimiento, un solo uso y
la misma protección de navegador del flujo orgánico. Se comprueba de nuevo la pertenencia
del usuario al negocio al empezar y al regresar del consentimiento.

El resultado guarda **el token de usuario**, cifrado y separado del token de Página.
`ad_oauth_credentials` es de solo inserción para la aplicación; únicamente el rol de
credenciales puede leer el cifrado. Cada fila corresponde a una versión exacta de la
conexión. Una reconexión sin anuncios invalida la autorización anterior para anuncios;
una revocación, eliminación o vencimiento también la bloquea. La eliminación de datos de
Conexiones borra estas credenciales y los metadatos de cuentas mediante su rol limitado.

## Operación y configuración en Meta

El código **no cambia el panel de Meta**. Antes de probar el consentimiento real, un
administrador debe configurar Facebook Login for Business para permitir elegir cuentas
publicitarias, además de los activos orgánicos, y los permisos `ads_management`, `ads_read`,
`pages_manage_ads` y `business_management`. Se puede indicar una configuración separada en
`QUALIFY_META_ADS_CONFIG_ID`. La configuración orgánica `QUALIFY_META_CONFIG_ID` permanece
separada; sin una configuración adicional, el diálogo de anuncios envía la lista de permisos
por `scope`. La concesión real se lee de `/me/permissions`; pedir un permiso no lo concede.

No se ha ejecutado consentimiento real ni se ha verificado el acceso de la aplicación a
estos permisos en esta entrega. La revisión de permisos de Meta queda en m-24828986.
La lista de permisos sigue siendo provisional hasta observar el consentimiento de esta
aplicación; un permiso ausente deja «Anunciar» deshabilitado con una explicación.

Fuentes primarias consultadas el 3 de noviembre de 2026:

- [Colección de Marketing API publicada por Meta](https://www.postman.com/meta/facebook-marketing-api/collection/0zr4mes/facebook-marketing-api-mapi): admite tokens de usuario o usuario del sistema y documenta `ads_read`/`ads_management` y los niveles de acceso.
- [SDK oficial de Meta: User](https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/adobjects/user.py): `GET /{user}/adaccounts`.
- [SDK oficial de Meta: AdAccount](https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py): campos `account_id`, `currency`, `timezone_name`, `account_status`, `disable_reason`, `funding_source`, `business`, y `GET /{account}/connected_instagram_accounts`.

Las páginas de referencia de developers.facebook.com no estuvieron accesibles mediante
la herramienta de consulta. El SDK confirma las formas de campos y rutas, pero no prueba
que esta aplicación tenga acceso ni establece por sí solo los permisos de cada lectura.

## Lectura, elección y autorización

`refresh_ad_accounts` consulta todas las páginas de `/me/adaccounts` y de
`act_<id>/connected_instagram_accounts`, con la versión independiente
`QUALIFY_META_ADS_API_VERSION`. Solo utiliza cursores; no sigue enlaces `next` que puedan
contener tokens o un destino inesperado. Una respuesta incompleta o fallida no sustituye
el último resultado por una lista aparentemente vacía. Los valores desconocidos conservan
su estado desconocido y bloquean la autorización de anuncios.

La cuenta elegida corresponde a una marca y una conexión del mismo negocio. El índice
parcial permite una sola elección por marca. La elección explícita puede conservar una
cuenta bloqueada para mostrar su estado, pero no autoriza una promoción. Los metadatos
incluyen cuenta origen, versión de API y de procesamiento. La actualización compara la
versión de credenciales observada con la actual bajo bloqueo: si hubo una reconexión,
revocación o cambio de marca mientras Meta respondía, descarta el resultado.

Las conexiones orgánicas antiguas pueden no tener marca. En ese caso se elige una de las
marcas existentes del negocio antes de autorizar anuncios. No se asigna una por defecto.
Esta acción solo completa una conexión sin marca: una marca ya asignada no se puede
cambiar mediante este flujo. Al asignarla se invalidan las cuentas y elecciones previas;
es necesario actualizarlas para esa marca.

`PostgresAccountBinding` implementa la frontera del ticket m-24828974: antes de resolver
una promoción vuelve a consultar Meta y exige la cuenta elegida para esa marca, una
credencial actual con `ads_management`, cuenta activa, Instagram asignado y presencia de
un origen de fondos. Desconocer esos datos bloquea la operación. Detectar un origen de
fondos **no certifica saldo ni salud de pagos**; esas comprobaciones pertenecen a
m-24828978. El cliente se resuelve con la misma versión verificada, sin sustituirla por
una reconexión más reciente. Una revocación posterior no puede cancelar una solicitud
ya iniciada; cada nueva resolución repite los controles.

Esta entrega no crea, activa ni financia anuncios. No incluye el asistente de campañas.

## Comprobación

La migración `0115` agrega dos tablas con aislamiento por negocio y acceso limitado al
cifrado. Las pruebas cubren consentimiento opcional, separación de tokens, lecturas
paginadas, permisos parciales, aislamiento, elección por marca y cambios concurrentes.
Los resultados concretos de ejecución se registran en el PR.
