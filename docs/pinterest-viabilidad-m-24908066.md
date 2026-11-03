# Pinterest como inspiración para Clip: validación previa

Fecha: 2026-11-02. Ticket: m-24908066, «Catálogo: conectar Pinterest y usar ideas por nicho como referencia en Clip».

Estado: primera base de lectura implementada y probada sin conexión; integración de cuentas y pantallas pendiente. Este documento no resuelve el ticket. La consulta de tableros mediante OAuth es técnicamente posible, pero el uso propuesto de sus imágenes como entrada de generación tiene restricciones explícitas del proveedor. Falta elegir un alcance permitido y confirmar ese uso con Pinterest antes de desarrollar el recorrido completo.

## Avance preparatorio — 2026-11-03

`packages/api/src/qualify_api/pinterest/client.py` ofrece un cliente tipado de lectura y un doble en memoria por instancia. Recibe un token explícito, sin leer una credencial global del entorno, y permite consultar tableros, sus Pines y, de forma independiente, el perfil. Los permisos de lectura de tableros/Pines son `boards:read` y `pins:read`; el perfil requiere `user_accounts:read`.

La base valida identificadores y paginación, conserva el cursor opaco, representa variantes de imágenes sin presuponer `originals` y clasifica errores sin incluir cuerpos, cabeceras ni credenciales. No descarga medios ni añade persistencia, OAuth, interfaz, conexión entre negocios o llamadas a generación. Los consumidores futuros deberán resolver una credencial del negocio autenticado antes de construir cada cliente. El doble usa datos sintéticos y cursores propios por instancia/recurso; no demuestra aislamiento RLS, todavía pendiente de implementar.

El contrato se contrastó con el [OpenAPI oficial de Pinterest](https://github.com/pinterest/api-description/blob/main/v5/openapi.yaml), versión 5.28.0 consultada el 2026-11-03. Las pruebas sin conexión están en `packages/api/tests/test_pinterest_client.py` y cubren paginación, respuestas inválidas, medios sin imagen y errores de acceso, transporte y límites. La validación autenticada permanece pendiente: la prueba local de solo lectura de `/v5/user_account` devolvió HTTP 401/código 3 y se detuvo sin consultar tableros o Pines. Ese resultado no permite concluir que la aprobación de la aplicación sea la causa.

## Lo comprobado en Pinterest

| Tema | Evidencia y consecuencia |
|---|---|
| OAuth | Authorization Code: autorización en `https://www.pinterest.com/oauth/`, intercambio en `POST https://api.pinterest.com/v5/oauth/token`. El servidor conserva el secreto; el navegador solo recibe la autorización y el resultado del recorrido. |
| Permisos | `boards:read` y `pins:read` para explorar tableros y Pines autorizados. `user_accounts:read` solo si se necesita consultar el perfil. Los tableros secretos requieren verificar los permisos específicos correspondientes; no prometer su acceso con los dos permisos básicos. |
| Vencimiento | La documentación de OAuth indica acceso de 30 días y renovación continua de 60 días. Los tokens de prueba de Trial duran 24 horas. Guardar los vencimientos devueltos por la API y reemplazar ambos tokens cuando roten; no programar una suposición de 24 horas para todos los accesos. |
| Acceso de la aplicación | Trial también requiere revisión. Standard requiere aprobación y demostración de la integración funcionando, incluido OAuth; no asumir acceso inmediato al crear la aplicación. |
| Tableros | `GET /v5/boards`, después `GET /v5/boards/{board_id}/pins`, con paginación. Esta ruta puede agrupar ideas por tableros elegidos por el cliente. No equivale a descubrir todo Pinterest por nicho. |
| Imágenes | La respuesta de Pines incluye variantes como `150x150`, `400x300`, `600x` y `1200x`; no asumir que siempre existe `media.images.originals.url`. Manejar Pines sin imagen utilizable y formatos distintos de una imagen simple. |
| Búsqueda por nicho | No se ha validado una búsqueda global disponible para esta aplicación. La alternativa técnica investigada es elegir entre los tableros accesibles del usuario. El nombre del tablero no certifica automáticamente su nicho. |

Fuentes oficiales: [autenticación y autorización](https://developer.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/), [niveles de acceso](https://developers.pinterest.com/docs/key-concepts/access-tiers/), [lista de Pines](https://developers.pinterest.com/docs/api/v5/pins-list/).

Las [directrices para desarrolladores](https://policy.pinterest.com/en/developer-guidelines) limitan almacenar datos obtenidos por API, compartirlos con terceros y crear contenido a partir de Pines para distribuirlo desde la aplicación. La excepción de almacenamiento indicada para analítica de campañas no cubre una biblioteca de referencias creativas.

**Implicación de diseño:** conectar una cuenta no concede permiso para copiar sus Pines a R2, conservar sus metadatos en los borradores o enviarlos a Anthropic/BytePlus. La selección explícita del usuario tampoco sustituye las condiciones de la API. No se ha obtenido una autorización particular de Pinterest para este uso. La consulta dentro de Qualify también debe presentarse y aprobarse como caso de uso de la aplicación; no se declara aprobada aquí.

## Qué significa Clip en el código actual

Verificado contra `origin/main` en `b5d5b524`, después de actualizar la referencia remota. Clip es el generador de video de la pantalla Crear, conectado a Seedance; no es el modelo de embeddings CLIP.

| Archivo | Contrato existente |
|---|---|
| `Qualify/creative_state.py`, `CreativeState._clip_media` | Convierte las selecciones a `clip_image_keys`, `clip_image_roles`, `clip_video_keys`, fotogramas y audio. Las referencias son archivos del negocio, no URLs externas arbitrarias. |
| `packages/creative/src/qualify_creative/schemas.py`, `MediaInputs` | Recibe claves de archivos y, para réplicas de reels, `source_reel`. No existe un contrato específico para un Pin como inspiración externa sin uso generativo. |
| `packages/api/src/qualify_api/creative/composition.py` | Conecta `SeedanceVideoAdapter`; `PublicReferenceLinks` pone archivos en el prefijo R2 del negocio y permite que el proveedor los descargue. |
| `Qualify/reel_replication.py`, `import_reference` | Descarga y prepara una referencia de video en el directorio de cargas; `source_reel_provenance` conserva su origen. Reutilizar esta importación para Pinterest copiaría medios, contrario al alcance del ticket. |

Por tanto, pasar directamente una imagen del Pin a `clip_image_keys` requeriría importarla y utilizarla en un proveedor externo. Tampoco basta añadir URL, título o autor a `source_reel` o al contexto enviado al modelo: seguiría transmitiendo información de Pinterest y guardándola en el borrador. No se implementó ninguna de estas variantes.

## Decisiones que faltan

1. Confirmar si «referencia» significa consulta humana y apertura del Pin original, o entrada de imagen/metadatos a la generación de Clip.
2. Si se busca generación, obtener de Pinterest una autorización que cubra el recorrido exacto, almacenamiento, terceros y conservación, además de verificar los derechos del medio. Si no se obtiene, seleccionar una fuente cuyos permisos cubran ese uso.
3. Si se elige consulta humana, acordar un contrato separado de inspiración externa y su retención. No reutilizar `MediaInputs`, el Catálogo ni el contexto de los modelos para transportar los datos de la API. La navegación de tableros se presenta como un alcance diferente, no como cumplimiento de la entrega a Clip pedida por el ticket.

## Implementación propuesta tras validar el alcance

La siguiente secuencia es una propuesta pendiente, no funcionalidad existente:

- Backend: cliente tipado de Pinterest con dobles en memoria; OAuth con `state` de un solo uso, vencimiento y enlace a usuario, negocio y sesión; comprobación del negocio activo al iniciar y al terminar. Credenciales cifradas y accesibles únicamente por la puerta de credenciales autorizada. No ampliar la conexión Meta suponiendo que sus capacidades y permisos son equivalentes.
- Renovación: guardar la respuesta vigente de credenciales, serializar renovaciones concurrentes y sustituir tokens de manera atómica. Cancelación o error OAuth consume el estado; revocación/invalidez conduce a reconectar, sin bucles de reintento ni secretos en registros.
- Desconexión: invalidar acceso local y estado pendiente; verificar el mecanismo oficial de revocación antes de prometer revocación remota. Destruir los datos efímeros del usuario al salir o cambiar de negocio.
- Exploración, solo si el caso de uso queda permitido: leer tableros y Pines bajo demanda, paginar y mostrar atribución/enlace original. No crear productos, archivos R2, caché persistente o registros de contenido de Pinterest.
- Entrega: definir primero un contrato de inspiración separado, con la política aprobada de campos, duración y consumidores. El contrato de URL/id/autor/procedencia del ticket sigue pendiente porque guardarlo en un borrador o enviarlo a generación no está validado.

Pruebas necesarias cuando exista código: autorización cancelada; `state` vencido, repetido o de otro negocio; aislamiento de credenciales y tableros entre negocios; paginación; permisos insuficientes; 401/revocación; renovación concurrente; desconexión; selección exacta; y ausencia de descargas, persistencia y llamadas a generación desde la exploración. El recorrido de entrada a Clip se prueba únicamente con un contrato cuyo uso haya sido autorizado.

## Verificación realizada y límites

Se leyó el ticket mediante `meegle workitem get`, se contrastaron fuentes oficiales públicas y se revisaron los contratos del código. La investigación inicial del 2026-11-02 no incluyó consultas autenticadas; el 2026-11-03 se hizo la consulta de perfil descrita arriba, que devolvió HTTP 401. No se conectaron cuentas mediante OAuth, no se descargaron Pines ni se ejecutaron proveedores de generación. Tampoco se comprobó la aprobación de una aplicación concreta o la disponibilidad efectiva de búsqueda para ella. El cliente preparatorio se verificó con 42 pruebas sin conexión y revisión de formato/lint; la integración en vivo sigue pendiente.
