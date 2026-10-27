# Cuenta desconectada: contrato para pantallas y workers

Contrato inicial de `m-24854864`, coordinado con `m-24854865`. El servidor decide el
estado; las pantallas muestran lo guardado y ofrecen la acción que corresponde. No
se deduce la causa de una excepción del navegador ni se borra información al fallar
una credencial. La purga solicitada por la persona pertenece a `m-24789547`.

## Datos disponibles para Deivid

`connections.list_connections(tenant_id)` conserva todas las cuentas del negocio,
incluidas las desconectadas, y añade estos campos sin credenciales:

| Campo | Valores / significado |
|---|---|
| `status` | Estado existente: `pending`, `active`, `degraded`, `revoked` |
| `reconnect_reason` | `missing_credential`, `auth_expired`, `permission_missing` o `None` |
| `temporary_failure_count` | Fallos temporales consecutivos; cero después del primer éxito |
| `recovery_refresh_pending` | Hay una búsqueda de recuperación pendiente |

Los valores internos `degraded` y `revoked` se presentan como «Desconectada» o
«necesita volver a conectar», nunca como códigos técnicos. Una cuenta desconectada
sigue siendo seleccionable para consultar lo guardado. Solo `active` admite sondeo
o envío. `pending` no equivale a una conexión sana.

Para una cuenta concreta, `get_connection_runtime_state(tenant_id=...,
connection_id=...)` devuelve además `credential_version` y las propiedades
`can_poll`, `needs_reconnect` y `temporary_warning`. Una cuenta inexistente o de
otro negocio devuelve `None`. Un error de base de datos debe impedir el acceso al
proveedor: no se interpreta como permiso para seguir.

`temporary_warning` es verdadero desde tres fallos temporales mientras la cuenta
sigue activa. Es un nivel persistido para mostrar un único aviso en pantalla, no
un evento repetido ni un disparador de notificaciones. El primer éxito lo apaga.

## Escrituras compartidas

- `mark_connection_unavailable(..., cause=...)` registra una causa permanente y
  pasa por la máquina de estados existente. Conserva la primera causa de la caída.
- `record_connection_temporary_failure(...)` incrementa la racha de una cuenta
  activa. No la desconecta por un fallo de red o un límite temporal.
- `record_connection_success(...)` pone la racha a cero; no reactiva una cuenta
  con causa permanente.
- Los tres aceptan `expected_credential_version`, capturado antes de llamar al
  proveedor. Una respuesta atrasada de una credencial antigua no cambia la cuenta
  recién reconectada.
- Al verificar un nuevo acceso como `active`, el repositorio limpia la causa y la
  racha y deja pendiente una búsqueda si antes estaba desconectada.
- `consume_recovery_refresh(...)` reclama esa búsqueda una sola vez, de forma
  atómica; el llamador la ejecuta antes de volver al sondeo periódico normal.

Cada mutación está limitada por `tenant_id` y RLS. La escritura de la caída bloquea
la fila y guarda el evento de auditoría en la misma transacción: diez fallos
repetidos o concurrentes no producen diez caídas. El evento de dominio incluye
`from`, `to`, `trigger` y `cause`; se publica después de confirmar la transacción.
El publicador actual es local al proceso, no una outbox duradera: no se promete
entrega exactamente una vez si el proceso cae entre el commit y la publicación.

El informe de salud usa una transacción independiente, siempre con el mismo rol y
RLS del negocio, para que el rollback de la operación fallida no borre el diagnóstico.
Debe llamarse después de liberar cualquier bloqueo de fila de la operación exterior.

## Reconexión y datos de prueba

La acción compartida de `m-24854865` recibe cuenta, causa y ruta de origen; reutiliza
el flujo de Facebook y el pedido de permisos existente. Solo acepta destinos
internos validados. Debe volver a la pantalla original con un aviso dentro de la
página para éxito, cancelación, permiso faltante o Facebook que no administra la
cuenta; los textos literales están en el ticket.

### Integración mínima para Deivid

Desde `Qualify.reconnect_panel`, reutilizar la acción y el resultado compartidos:

```python
from .reconnect_panel import reconnect_button, reconnect_result_panel

# Dentro del aviso de la cuenta seleccionada:
reconnect_button(connection_id, cause, "/inbox")
# En Conversaciones, usar el origen lógico "/conversations".

# Una sola vez dentro del contenido de la pestaña visible:
reconnect_result_panel()
```

El panel ya ejecuta `ReconnectState.read_result` al montarse. No montarlo en dos
pestañas simultáneamente: comparten el estado del resultado. Si la pantalla arma
su propio contenedor, debe leer el resultado al llegar y mantener un único panel.

Los orígenes lógicos son `/inbox` para Comentarios y `/conversations` para Mensajes.
La pantalla real de atención usa `/responder?tab=comentarios` o
`/responder?tab=mensajes`; `reconnect_origin` normaliza esas pestañas al origen
lógico. No pasar la URL con su query a `safe_return_path`: rechaza queries sin
normalizar, destinos externos y rutas no permitidas. El backend valida y firma el
origen lógico junto a la cuenta, y el callback reconstruye el destino.

La base entrega acción, resultado y contrato. Sigue siendo trabajo de los tickets
de UI de Deivid conservar cuentas desconectadas en sus selectores, mostrar los datos
guardados, colocar un aviso por cuenta y conectar el contador de fallos temporales.
Los avisos de menú, Tu semana y WhatsApp no se incorporan por duplicación en este
componente; WhatsApp conserva la recuperación asistida por el equipo.

Un fallo de autenticación no autoriza ningún mensaje. La recuperación tampoco
crea nuevas aprobaciones: todo envío conserva las comprobaciones de aprobación,
ventana, capacidad e idempotencia de su módulo.

## Comportamiento de mensajes y webhooks observado en el código

- Los mensajes aprobados que siguen `pending` quedan fuera de los candidatos del
  worker mientras su cuenta no está activa. Al reconectar vuelven a ser elegibles,
  sujetos a la aprobación, ventana y capacidad que el sender vuelve a comprobar.
  No se reviven filas `dead`, `failed` ni `sent`. La recuperación de filas antiguas
  `sending` conserva sus protecciones contra resultados ambiguos y duplicados.
- `mentions/resolve.py` resuelve eventos entrantes por plataforma e identificador
  externo, sin filtrar el estado de conexión. `conversations/webhook.py` ingiere
  esos eventos sin usar una credencial de envío. Por tanto, un webhook que Meta
  ya entregó puede seguir guardándose aunque el estado local sea `degraded` o
  `revoked`; no dispara una respuesta automática.
- Lo anterior es una lectura del código, no una prueba de que Meta continúe
  **entregando** eventos después de revocar permisos. Ese comportamiento del
  proveedor queda pendiente de las pruebas reales en producción y de su evidencia.

## Validación

La migración `0102_connection_runtime_health` añade tres columnas y restricciones a
la tabla existente, manteniendo sus políticas y permisos. Su reversión elimina
solo esas columnas y restricciones.

Los tests de contrato cubren notificación posterior al commit, causa inválida y
respuesta de una versión de credencial antigua. Los tests `db` cubren RLS entre
negocios, diez fallos y fallos concurrentes, racha 3→0, recuperación reclamada una
sola vez y diagnóstico que sobrevive al rollback de la operación de negocio.

Las pruebas reales se hacen en producción con cuentas de prueba. Cada evidencia
debe indicar versión, entorno, hora, pasos y resultado, sin tokens ni datos de
clientes. La observación de código sobre webhooks y envíos pendientes descrita
arriba debe contrastarse con las pruebas reales; no equivale a evidencia en vivo.
