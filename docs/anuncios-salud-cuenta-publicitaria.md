# Salud de la cuenta publicitaria (m-24828978)

Conexiones muestra la última observación de la cuenta y permite actualizarla. Antes
de preparar una promoción se solicita una lectura nueva. Una restricción confirmada
o un anuncio propio con `PENDING_BILLING_INFO` bloquea el formulario y ofrece una acción
en Meta. Una lectura desconocida o sin permisos no se presenta como un método de pago
ausente; permite preparar datos localmente y bloquea las operaciones remotas.

Esta entrega no crea ni activa anuncios, no cambia métodos de pago y no habilita el
adaptador de ejecución real de m-24828976. `can_promote` expresa que no se observó un
bloqueo de salud de cuenta; **no equivale a `VerifiedChecks.billing_ready`** ni prueba
que Meta vaya a aceptar un cargo, aprobar el anuncio o entregar resultados.

## Qué consulta y qué guarda

La lectura autenticada usa el token de usuario vigente de la conexión, separado del
token de Página. Consulta únicamente `account_id`, `currency`, `account_status`,
`disable_reason`, `funding_source`, `amount_spent` y `spend_cap` en `act_<id>`.
Los identificadores remotos proceden de cuentas previamente enumeradas para esa
conexión y tenant, no de un parámetro libre del navegador.

También puede leer `id`, `account_id` y `effective_status` de hasta cien anuncios cuyos
identificadores ya están persistidos en promociones de esa cuenta. La consulta local
exige la misma marca, cuenta publicitaria, intento publicado de Instagram y evento
publicado de origen. No busca anuncios de otras cuentas ni acepta identificadores
arbitrarios. Si hay más de cien identificadores, la ausencia de alertas no se da por
completamente comprobada. El estado de entrega se usa como señal de atención, no como
diagnóstico de una tarjeta ausente.

No se solicitan `funding_source_details`, tarjetas, titulares, números, vencimientos ni
códigos de seguridad. El identificador de origen de fondos se convierte a presencia
observada y se descarta. Sólo se guardan campos normalizados permitidos, su origen,
versión de API y versión del procesamiento; nunca la respuesta completa de Meta.

El SDK confirma los campos monetarios como cadenas, pero no fue posible comprobar
contra la referencia actual sus unidades ni la relación entre el contador de gasto y
el límite. Se conservan sólo cadenas numéricas normalizadas, separadas de datos de
instrumentos de pago. **No se dividen entre cien ni se muestran como dinero, no se
calculan saldos disponibles y no se declara agotado un límite por comparar esos
contadores.** La pantalla conserva el importe como pendiente de comprobar.

## Evidencia y límites de interpretación

Fuentes primarias consultadas el 4 de noviembre de 2026, fijadas a SDK 26.0.0:

- [Campos de AdAccount](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adaccount.py).
- [Constantes de estado de cuenta](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/helpers/adaccountmixin.py).
- [Estados efectivos del anuncio](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/ad.py).

Se reconocen las constantes publicadas por el helper: 1 activa, 2 deshabilitada, 3 pago
pendiente, 7 revisión, 9 período de gracia, 100 cierre pendiente y 101 no disponible.
El helper denomina 101 `temporarily_unavailable`; por eso no se afirma un cierre
permanente. Otros códigos se muestran en español como pendientes de comprobar.

No se obtuvo una enumeración primaria actual completa de `disable_reason`: cero se
presenta como ninguna restricción informada y los valores distintos de cero como una
restricción que debe consultarse en Meta, sin inventar una infracción o un compromiso
de seguridad específico. La referencia de developers.facebook.com devolvió 429.

Un identificador numérico positivo en `funding_source` sólo demuestra que se observó
un origen de fondos. Un campo omitido, nulo, cero o mal formado queda **desconocido**:
no fue posible verificar que esos valores demuestren ausencia real de método de pago.
El simulador normalizado puede suministrar una ausencia confirmada para probar el
bloqueo; eso no convierte la interpretación en una comprobación real. El criterio de
una cuenta real sin método de pago sigue necesitando una prueba autorizada o evidencia
adicional que permita identificarla sin ambigüedad. No se ha hecho ninguna llamada
real a Meta en esta entrega.

## Aislamiento, frescura y concurrencia

La migración 0120 amplía `ad_accounts`: la misma política RLS habilitada y forzada,
roles y borrado de Conexiones cubren las observaciones nuevas. Un CHECK limita las
claves permitidas; la normalización tipada valida los valores primitivos y evita
copiar datos de tarjetas o respuestas arbitrarias por el servicio. Se distinguen
la última lectura correcta y el último intento; un error no renueva la fecha de éxito.
La salud queda ligada a la versión de credencial, cuenta, moneda y selección observadas.

Cada intento reclama un identificador distinto. Una respuesta antigua no puede
sobrescribir una comprobación más reciente. Antes de guardar se vuelve a comprobar
la pertenencia del actor, conexión, marca, moneda y versión. Reconectar, revocar,
depurar, cambiar la selección o retirar acceso invalida el resultado tardío.

La caché de salud dura como máximo 24 horas. La actualización manual y la entrada al
asistente fuerzan una lectura nueva. La presencia de datos antiguos no autoriza una
operación remota. La lectura de metadatos de cuentas de m-24828972 no sustituye ni
renueva esta observación de salud.

## Lectura diaria y operación

El módulo de lectura permite un pase diario explícito por tenant:

```bash
uv run --no-sync python -m qualify_api.ads.health_cli --tenant <uuid>
```

No tiene opción de recorrer todos los tenants ni llama métodos de escritura de Meta.
Utiliza la caché de 24 horas y sólo considera cuentas elegidas y disponibles. Su salida
operativa contiene cantidades de cuentas, sin identificadores, instrumentos de pago ni
credenciales. El pase puede ejecutarse con un temporizador del servidor por tenant;
**esta entrega no instala ni afirma haber desplegado ese temporizador**. Configurarlo
en producción debe seguir el procedimiento operativo habitual. Conexiones también
puede actualizar oportunísticamente las observaciones vencidas cuando se abre.

Las pruebas de `test_ad_account_health.py` y `test_ad_account_health_db.py` cubren
normalización desconocida, privacidad, lectura de anuncios propios, RLS, rechazo de
respuestas antiguas, cambios de moneda y credenciales, errores de actualización y
conservación del bloqueo de ejecución real.
