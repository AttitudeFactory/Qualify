# Borrado de datos de cuentas conectadas

La implementación de `m-24789547` cubre Instagram y Facebook. **WhatsApp queda
pendiente**: una solicitud de ese canal se rechaza antes de revocar o crear un trabajo.
No se realiza ninguna llamada de borrado a Meta ni se eliminan publicaciones externas.

## Solicitud y plazos

La desconexión explícita que realiza una persona guarda la revocación y una solicitud
duradera en la misma transacción. Conserva los datos sincronizados durante 29 días y
fija una fecha límite de 30 días desde la solicitud. Una reconexión durante ese período
cancela únicamente la solicitud automática que todavía no comenzó. Un error de acceso,
una credencial vencida o un estado degradado nunca solicita borrado.

Una solicitud manual recibida por soporte se registra con el comando siguiente. Su
ejecución comienza de inmediato y mantiene el límite de 30 días; la finalización puede
requerir reintentos o esperar la expiración de entradas antiguas sin atribución segura.
La repetición conserva el mismo identificador
y la misma fecha límite; acelerar una desconexión pendiente tampoco extiende el plazo.
Una reconexión no cancela una solicitud manual ni un borrado que ya comenzó.

```bash
# Vista previa: no escribe en Postgres ni modifica R2.
just connection-purge --tenant <uuid> --connection <uuid> --request

# Solicitud manual y primer intento de ejecución.
just connection-purge --tenant <uuid> --connection <uuid> --request --execute

# Vista previa del trabajo pendiente del negocio.
just connection-purge --tenant <uuid>

# Ejecutar solicitudes vencidas y reintentar las que fallaron.
just connection-purge --tenant <uuid> --execute
```

`--tenant` es obligatorio. `--connection` limita la operación a una cuenta y `--limit`
acota las solicitudes examinadas (100 por defecto, entre 1 y 1000). No existe una opción
para forzar el borrado de datos cuya pertenencia sea dudosa. Las cuentas desconectadas
antes de esta implementación no reciben solicitudes retroactivas por una migración:
requieren una solicitud explícita y revisada por soporte.

## Operación y recuperación

El operador debe programar la ejecución **cada 15 minutos por negocio**, con el DSN del
rol de borrado y acceso a R2. La mera instalación del código no programa este comando.
Debe supervisar `status`, `deadline_at`, `attempts` y `last_error_code` de
`connection_purge_requests`; un error del comando produce salida distinta de cero.
Una solicitud `scheduled` espera su fecha, `running` admite reintentos, `completed`
confirma que terminó y `cancelled` identifica una reconexión a tiempo. Cualquier trabajo
sin completar cerca de su fecha límite exige intervención operativa; los reintentos no
extienden el plazo. La cadencia y la atención a fallos son necesarias para cumplirlo.

Antes de borrar filas se confirma en Postgres un inventario de claves de R2. Un fallo
del almacén conserva ese inventario aunque las filas originales ya hayan desaparecido.
Reintentar vuelve a borrar las mismas claves de forma idempotente; no marca éxito si
R2 informa un error. Las escrituras tardías se bloquean en Postgres y las subidas de
medios de la cuenta se coordinan con el inventario mediante un bloqueo de la conexión.

Los webhooks conservan la atribución comprobada en el momento de entrada. Un evento
anterior no se reasigna a otro negocio que conectó la misma cuenta posteriormente. La
limpieza elimina solamente los eventos atribuibles a la conexión solicitada y retira
el cuerpo crudo compartido sin borrar los eventos normalizados de otras conexiones.

Para entradas antiguas cuya pertenencia no puede demostrarse, el trabajo informa
`raw_ownership_unverified` y queda pendiente. Esas entradas afectadas pueden expirar a
los 29 días de su **recepción original**, incluso si siguen pendientes o en procesamiento;
este límite específico de privacidad evita retenerlas indefinidamente. El reintento
posterior confirma la limpieza antes del límite de 30 días de la solicitud. Una nueva
entrega o un reintento no reinician el reloj original. Los detalles de admisión y de
redacción de webhooks se implementan en la migración `0107` y su módulo de purga.

## Datos eliminados y conservados

Se eliminan credenciales, perfiles de interlocutores, conversaciones y mensajes,
publicaciones sincronizadas, comentarios, menciones, respuestas y análisis derivados,
cursores de sincronización y cuerpos crudos atribuibles. El inventario comprende las
carpetas exactas de la conexión, incluidas subidas sin una fila vigente; valida tanto el
negocio como la conexión antes de tocar el almacén.

Se conservan las piezas creadas por el negocio, catálogo, recursos de marca, archivos
guardados y publicaciones/planificación propias. Una miniatura sincronizada puede
reutilizar un archivo publicado por Qualify: esa referencia no autoriza a borrar el
archivo propio. También se protegen claves referenciadas por otra conexión. Los
identificadores externos de publicaciones propias permanecen como información de esas
publicaciones, fuera de los datos adquiridos por sincronización.

La conexión terminada queda como referencia técnica para las claves foráneas de esas
publicaciones. Se borran su identidad de plataforma, nombre, permisos y datos de salud;
no aparece en la lista de cuentas ni se ofrece como destino de reconexión. Conserva la
clave del usuario que concedió el consentimiento porque el esquema la exige como no
nula. El registro separado de borrado conserva únicamente identificadores internos,
motivo, fechas, contadores y códigos de error; al completar no conserva claves de R2,
contenido de usuarios ni identificadores de plataforma.

## Preparación de producción

La migración `0106` crea `qualify_connection_purge`, sujeto a RLS y sin permiso de leer
credenciales cifradas. La aplicación normal puede registrar una solicitud, pero no
recibe permisos para borrar credenciales. El proceso de borrado usa exclusivamente
`QUALIFY_CONNECTION_PURGE_DSN`, con el mismo negocio en cada transacción.

Antes de desplegar o habilitar la tarea en producción se requiere la aprobación
operativa habitual y configurar `QUALIFY_DB_CONNECTION_PURGE_PASSWORD`, el DSN del rol,
R2 y la programación por negocio. El bootstrap deja el rol sin acceso (`NOLOGIN`) mientras
no se configure esa contraseña; nunca habilita en producción la contraseña de desarrollo.
La configuración de Compose vacía tanto esa contraseña como el DSN de borrado en API,
Reflex y los demás procesos. Solo el servicio opcional de operación `connection-purge`
recibe el DSN dedicado; no arranca con un `up` normal y su comando por defecto muestra
ayuda. Con la función `dc` del manual de despliegue, el operador ejecuta, por ejemplo,
`dc run --rm -T connection-purge --tenant <uuid> --execute`. La programación cada 15
minutos debe invocar ese comando para cada negocio autorizado y vigilar su resultado.
No se han ejecutado purgas de producción como parte de esta implementación.
