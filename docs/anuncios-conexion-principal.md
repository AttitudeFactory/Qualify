# Anuncios con la conexión principal de Meta

La conexión normal de Instagram ahora conserva también el token de **usuario** cuando
`/me/permissions` confirma `ads_management`. No hace falta otra configuración de Meta ni
`QUALIFY_META_ADS_CONFIG_ID`: esa variable queda como opción para instalaciones que sí
quieran una configuración separada mediante una llamada explícita al flujo de anuncios.
La acción «Actualizar acceso con Meta» de Tus redes usa siempre la configuración
principal, incluso si `QUALIFY_META_ADS_CONFIG_ID` sigue presente en el entorno.

La publicación y los mensajes conservan su credencial de Página. Los anuncios utilizan
el token de usuario de la misma autorización, cifrado en `ad_oauth_credentials`, con la
misma versión de conexión. Esto no copia ni expone secretos en la interfaz.

## Conexiones que ya existían

- Si hay un token de anuncios vigente para la versión actual, se utiliza directamente.
- Si la credencial principal está identificada expresamente como `user` y tiene el
  permiso concedido, puede utilizarse sin una segunda configuración.
- Si solo quedó guardado el token de Página, o una credencial antigua marcada como
  `bearer`, hay que actualizar el acceso con Meta una vez. `bearer` describe el método
  de autenticación y no demuestra que el token sea de usuario. El flujo anterior podía
  descartar el token de usuario después de obtener el de Página; no es recuperable a
  partir de este último.

Después se actualiza la lista de cuentas y se elige la cuenta publicitaria de la marca.
La lectura consulta otra vez los permisos realmente concedidos antes de enumerar
cuentas. Una reconexión, revocación, vencimiento o cambio de versión invalida los datos
anteriores; no se cambia a un token antiguo para ocultar ese problema.

## Comprobaciones y activación

Este cambio elimina la dependencia de una **configuración de anuncios separada** para
conectar y consultar las cuentas publicitarias. Conserva el aislamiento de negocio,
los permisos de acceso, la selección de marca, la vigencia y las comprobaciones de Meta.

El asistente ahora compone comprobaciones reales de Meta para publicaciones propias de
Instagram, cuenta COP y destino web, sin Vivienda ni público ampliado y con los cuatro
cambios automáticos desactivados. Los lugares con radio o intereses añadidos todavía
no están incluidos. La interfaz presenta cada comprobación y conserva el formulario
si alguna falla. Los permisos por sí solos no sustituyen estas comprobaciones.

Se comprueban permisos, acceso, asignación de Instagram, propiedad de la publicación,
estado y datos de pago, moneda y zona horaria. Meta valida los cuerpos concretos con
`validate_only`, sin crear objetos. Después de la aprobación inicial se crean los
objetos en pausa y se comparan sus campos remotos con la aprobación, incluido el botón
y enlace reales. La segunda confirmación permite solicitar la activación, con campaña
al final y comprobaciones repetidas tras las esperas. Un resultado positivo no promete
cobro ni entrega: Meta conserva la revisión final. No se inventa un mínimo total a
partir de los mínimos diarios.

La tabla oficial de Meta especifica **COP con subdivisión mínima 1**: un entero de la
API representa un peso colombiano. Qualify conserva su importe interno en centésimas,
pero guarda la conversión verificada en las aprobaciones nuevas: 10.000 COP se guardan
como 1.000.000 y se envían a Meta como 10.000. Se rechazan fracciones no representables.
Las aprobaciones anteriores no se reinterpretan ni se activan automáticamente.

No se ejecutaron escrituras contra Meta ni se activaron anuncios para verificar este
cambio. Los tickets con pruebas reales de creación, entrega o recepción de contactos
siguen requiriendo su propia verificación antes de cerrarse.

Fuentes y límites técnicos: [Comprobaciones de promociones](anuncios-comprobaciones-meta.md).
