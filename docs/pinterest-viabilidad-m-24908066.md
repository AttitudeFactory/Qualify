# Pinterest: conexión por negocio e ideas para Clip

Ticket m-24908066. Actualizado el 2026-11-09. Implementación local del recorrido de conexión, exploración y selección; falta la configuración externa y comprobar OAuth completo con una cuenta real antes de habilitarlo en producción.

## Recorrido

El Catálogo ofrece Pinterest separado de los productos. Cada negocio conecta su cuenta, elige uno de los tableros accesibles, recorre sus Pines con paginación y previsualiza una idea. No hay búsqueda global por nicho: el cliente organiza las ideas por tableros. Se solicitan `boards:read`, `pins:read` y `user_accounts:read` para identificar la cuenta; no se piden permisos de publicación ni de tableros secretos.

Solo después de elegir explícitamente usar una idea se vuelve a consultar su página de tablero con la credencial del negocio. El servidor exige que el Pin siga allí; no confía en una URL enviada por el navegador. La imagen se valida, normaliza y guarda como referencia del negocio en R2. El importador admite únicamente JPEG/PNG/WebP de `https://i.pinimg.com`, sin redirecciones, con límites de 10 MiB, 20 millones de píxeles y tiempo de lectura. Un error conserva la selección anterior.

Clip es el generador de video de Crear. La imagen entra como referencia de estilo y no crea un producto. La procedencia incluye identificador y enlace del Pin, tablero, propietario del tablero cuando esté disponible, clave de imagen y versión de importación. El propietario del tablero no se presenta como autor original. La procedencia acompaña solo las referencias aún seleccionadas. Importar la referencia no inicia generación ni publica: crear la pieza y aprobar su publicación siguen siendo acciones posteriores.

## Conexión y custodia

- OAuth Authorization Code. El `PINTEREST_ACCESS_TOKEN` local se limita a pruebas manuales; el servicio de clientes nunca lo lee.
- Estado firmado con vencimiento de diez minutos y un solo uso, ligado al usuario, negocio y prueba del navegador. Reflex coloca una prueba temporal en la cookie de conexión. `/api/connections/pinterest/handoff` exige esa prueba y la reemplaza, en el mismo nombre y ruta, por una cookie `HttpOnly`, `Secure` y `SameSite=Lax` antes de abrir Pinterest. El enlace de salto solo no permite conectar otra cuenta.
- Solo el propietario o un administrador del negocio puede conectar o desconectar. Salir o cambiar de negocio cancela el flujo pendiente, también durante las consultas externas. Antes de intercambiar el código y antes de guardar se comprueba el rol actual; se reclama el flujo de forma atómica justo antes de guardar. Cancelar o fallar una reconexión conserva el acceso anterior que aún funcione.
- `0144_pinterest_connections` añade metadatos por negocio y credenciales cifradas por versión, después de `0143_ad_lead_forms` de main. Ambas tablas tienen `tenant_id`, RLS habilitado y forzado y política con `NULLIF`. La cuenta de aplicación puede insertar credenciales cifradas, pero no leerlas; la lectura y el borrado pasan por el módulo custodio y `credential_session`.
- Renovación bajo demanda al acercarse el vencimiento: bloqueo distribuido, segunda lectura dentro del bloqueo y escritura atómica por versión. Los vencimientos proceden de la respuesta de Pinterest. Un cambio concurrente de cuenta no se sobrescribe.
- Desconectar invalida versiones y devoluciones pendientes y borra credenciales anteriores. Un límite de versión evita borrar una reconexión ocurrida entre ambas operaciones. Es desconexión local; no se afirma revocar remotamente el permiso en Pinterest.
- Errores sin cuerpos del proveedor, tokens o cabeceras. Los registros HTTP ocultan la consulta del salto y devolución. Ambos recorridos usan `no-store` y `no-referrer`.

Archivos principales: `qualify_api/pinterest/{client,oauth,repository,service,settings,routes,composition}.py`, `connections/credential_reader.py`, `Qualify/pinterest_{provider,state,ui,vm}.py`, `creative/pinterest_reference.py` y `qualify_creative/schemas.py` (`SourcePinProvenance`).

## Configuración y activación

Registrar exactamente la devolución del entorno. Producción: `https://app.qualify.la/api/connections/pinterest/callback`. Desarrollo: `http://localhost:8000/api/connections/pinterest/callback`; si el navegador no acepta cookies seguras locales, usar un origen HTTPS registrado y servir aplicación y devolución en el mismo host.

| Variable | Uso |
|---|---|
| `PINTEREST_CLIENT_ID` | Identificador de la aplicación. |
| `PINTEREST_CLIENT_SECRET` | Secreto de aplicación, solo servidor. |
| `PINTEREST_REDIRECT_URI` | Devolución registrada, coincidencia exacta. |
| `PINTEREST_STATE_SECRET` | Secreto aleatorio de al menos 32 caracteres; alternativamente `QUALIFY_OAUTH_STATE_SECRET` explícito. |
| `PINTEREST_FERNET_KEY` | Clave Fernet específica. Si falta, solo se admite una clave compartida explícita; nunca la clave de desarrollo incluida en el código. |
| `PINTEREST_FERNET_KEY_ID` | Identificador de clave, por defecto `pinterest-1`. No cambiar sin conservar capacidad de descifrar credenciales existentes. |

También se requieren las puertas de Postgres, Redis y R2 ya existentes. No cambiar la clave compartida de otros proveedores para activar Pinterest. `.env.example` documenta las variables. Transferir secretos a producción por el procedimiento de `env-push`, sin imprimirlos. Aplicar la migración por el flujo habitual y verificar `just migration-guard`; antes de fusionar se exige CI correcto. Trial permite pruebas con cuentas habilitadas; Standard para clientes externos requiere la revisión correspondiente.

En la preparación local del 2026-11-09 se completaron únicamente valores ausentes del identificador, devolución y secretos de estado/cifrado específicos. El secreto real de aplicación continuaba pendiente. Esa preparación no demuestra configuración del servidor.

## Evidencia y pendientes

El 2026-11-09 se hicieron tres lecturas con el token personal de prueba en producción: perfil **200**, tableros **200** con dos resultados y sin continuación, y Pines del primer tablero **200** con cuatro resultados y sin continuación. La imagen inspeccionada ofreció `150x150`, `400x300`, `600x` y `1200x` y URL HTTPS. No se descargó ningún medio ni se llamó a generación. Esto demuestra lectura con ese token; no sustituye OAuth ni demuestra acceso de todos los clientes.

Las pruebas sin conexión cubren respuestas inválidas, permisos, revocación, paginación, separación por negocio, selección exacta, cancelación, repetición, vencimiento, prueba del navegador, invalidación al salir/cambiar de negocio y renovación. La importación y procedencia se prueban con imágenes sintéticas. Las pruebas Postgres verifican RLS real, denegación de lectura del cifrado a la aplicación, actor de otro negocio, membresía retirada y la carrera entre desconexión y reconexión. En un contenedor aislado se comprobó `upgrade head → downgrade base → upgrade head` sin tocar bases existentes. Los resultados finales de lint, pruebas y compilación quedan en el PR.

Pendiente manual: consentimiento real con secreto y devolución registrados; cancelar, reconectar y desconectar desde esa cuenta; renovación con tokens reales; y una creación pagada de Clip si el responsable decide probarla. No se ejecutó generación, publicación o envío real durante la implementación.

## Condiciones del proveedor

El usuario decidió el 2026-11-09 implementar la selección explícita como referencia de Clip tras la investigación inicial. Esa decisión no se presenta como autorización particular de Pinterest. Las [directrices para desarrolladores](https://policy.pinterest.com/en/developer-guidelines) restringen almacenamiento, transferencia a terceros y creación de contenido a partir de Pines. OAuth, Trial y la selección del cliente no conceden por sí solos permisos adicionales sobre el medio. No se ha verificado una excepción otorgada por Pinterest.

Fuentes oficiales: [OpenAPI, v5.28.0](https://github.com/pinterest/api-description/blob/main/v5/openapi.yaml), [OAuth](https://developer.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/) y [niveles de acceso](https://developers.pinterest.com/docs/key-concepts/access-tiers/). Las imágenes se eligen entre variantes devueltas; no se presupone `originals`.

## Referencias en los selectores compartidos

La ampliación solicitada el 2026-11-09 conserva el mismo importador acotado y la selección
explícita. La procedencia de un Pin puede acompañar una foto seleccionada de producto,
fondo o referencia/fotograma de Clip, sin que su selección tenga que cambiar el formato
actual a Clip. En carruseles, la foto se vincula a la diapositiva elegida mediante su
entrada de producto; un Pin importado no se convierte por ello en un producto del
Catálogo ni en una pieza o fila de Galería existente.

El contrato de media rechaza procedencias duplicadas, sin una imagen seleccionada o
asociadas únicamente a videos, audio, logotipos o retratos. Quitar una imagen o descartarla
en el plan de recursos elimina su procedencia de ese recorrido. Cada salida registra
solo los Pines usados por sus referencias; una diapositiva final sin foto no hereda las
fuentes de otras diapositivas y una diapositiva conservada mantiene las de su ejecución.
Los metadatos de procedencia no se añaden a las instrucciones enviadas al modelo.

Esta ampliación no modifica proveedores, modelos o permisos de Pinterest ni acredita una
excepción a las condiciones del proveedor descritas arriba. No agrega importaciones
automáticas, una búsqueda global o nuevos tipos de archivos.
