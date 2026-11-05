# Estado y resultados de promociones

Implementación de `m-24828979`. La pantalla **Anuncios** muestra únicamente promociones
guardadas por Qualify para el negocio de la sesión. No importa campañas ajenas ni crea
anuncios. La vista consulta los datos guardados; **Actualizar estado y resultados** hace
lecturas autenticadas de Meta con la credencial separada de anuncios.

## Estado y resultados diarios

El estado observado procede del anuncio y conserva las pausas heredadas de la campaña
o del conjunto. Un estado nuevo, ausente o desconocido se presenta como pendiente de
comprobación. La cuenta, el anuncio y ambos padres deben coincidir exactamente con la
promoción persistida. No se interpreta un objeto ajeno como prueba de propiedad.

Los resultados cubren los 28 días completos anteriores a la fecha de la cuenta
publicitaria. «Ayer» usa su zona horaria comprobada, no la del servidor ni la del navegador.
Se guardan gasto, alcance, impresiones, clics, CTR, CPC, CPM y acciones disponibles por día.
El gasto de Insights es un decimal en la moneda de la cuenta; no se divide por cien como
el presupuesto expresado en unidades menores. Un dato ausente o inválido permanece
desconocido. No se suman alcances diarios como si fueran personas únicas del período.

La consulta pagina con límites y rechaza fechas repetidas, agregados de varios días,
identidades, moneda o períodos diferentes. Cada actualización tiene un identificador:
una respuesta anterior no puede sobreescribir otra consulta más reciente. Un cambio de
credencial, selección, pertenencia o conexión invalida la observación en curso.

El estado y los resultados tienen fechas de comprobación separadas. Un fallo de Insights
conserva el estado recién comprobado y marca los resultados previos como desactualizados.
Una consulta vacía no se convierte en una fila de ceros ni conserva resultados anteriores
como si pertenecieran a la nueva consulta. Los datos pueden cambiar posteriormente; no se
promete un plazo universal de estabilización de 28 días ni se equiparan clics con ventas.

## Pausar y registrar cambios

La pausa requiere sesión y pertenencia vigentes, credencial publicitaria vigente y una
lectura nueva que compruebe el anuncio, su cuenta, campaña y conjunto. Después de la
confirmación explícita se escribe un registro durable con el actor local, la fecha, el
identificador de la solicitud y el cambio exacto antes de enviar `status=PAUSED` al anuncio.
No se activa ningún padre ni se reanuda la promoción por este camino.

Solo puede existir una operación pendiente por promoción. La separación entre cambios
es de treinta segundos, también después de fallos. Repetir una confirmación no repite
la escritura. El cliente vuelve a comprobar el contexto y la operación justo después
de esperar cualquier enfriamiento, antes del envío. Las confirmaciones vencen a los
cinco minutos; una operación reconciliada no puede despertarse y escribir después.

Un tiempo de espera o resultado ambiguo deja la operación en estado desconocido y
bloquea nuevos cambios. Una lectura posterior puede reconciliar una pausa con
`status=PAUSED` del propio anuncio; `CAMPAIGN_PAUSED` o `ADSET_PAUSED` no bastan.
La reconciliación espera noventa segundos y debe proceder de una consulta iniciada
al menos noventa segundos después del envío, aunque la confirmación lleve más tiempo
esperando por el enfriamiento del cliente. No se reintenta automáticamente una escritura ambigua.

La solicitud y la aprobación originales de `ad_promotions` permanecen intactas.
El presupuesto y la fecha visibles se identifican como los **aprobados originalmente**.

`results_management.apply_verified_edit` permite probar con adaptadores inyectados las
operaciones de reanudar, cambiar presupuesto y cambiar fecha. Exige consentimiento para
el cambio exacto, actor, contexto completo, credencial, vencimiento, pagos y elegibilidad
comprobados. El presupuesto debe respetar el mínimo y, si es total, lo gastado. Guarda
el cambio y la evidencia en la misma bitácora durable. Las pruebas usan datos simulados;
**no existe un adaptador de producción que habilite esas tres operaciones**. La función
que usa la pantalla las rechaza y conserva los bloqueos del asistente de promociones.

## Consulta periódica y despliegue

Comando disponible, de solo lectura y con negocio obligatorio:

```powershell
uv run --no-sync python -m qualify_api.ads.results_cli --tenant <uuid>
```

Cada ejecución toma promociones consultables cuya última tentativa tiene al menos treinta
minutos, hasta el límite indicado. No escribe en Meta. Imprime solo cantidades de
promociones consultadas o no disponibles. **Este PR no instala un temporizador en
producción**: Herwin debe programar la ejecución por los negocios autorizados y verificar
el intervalo y las credenciales antes de afirmar la garantía de treinta minutos.

Migración `0127`, posterior a `0126`: observaciones, resultados diarios y bitácora de
operaciones con `tenant_id`, claves foráneas compuestas, RLS habilitado y forzado,
política `NULLIF`, permisos y reversión. Las observaciones y sus datos no contienen
credenciales ni respuestas remotas completas.

Al purgar una conexión se eliminan sus cuentas publicitarias, las observaciones y los
resultados diarios por cascada. La bitácora de cambios se conserva junto a la aprobación
original como constancia de las órdenes de pausa o gasto ya autorizadas; no conserva
credenciales ni datos de Insights. Al eliminar la promoción también se elimina esa bitácora.

## Evidencia y límites del ticket

Campos y operaciones contrastados con el SDK oficial de Meta fijado en 26.0.0:

- [Anuncio: identidad, padres, estados y revisión](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/ad.py).
- [Resultados: fechas, moneda y métricas](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adsinsights.py).

El SDK confirma los nombres y tipos, pero no prueba permisos reales, entrega efectiva,
facturación ni el formato localizado de los motivos de rechazo. No se hicieron llamadas
de escritura ni anuncios reales durante el desarrollo.

| Criterio | Entrega | Pendiente |
|---|---|---|
| Rechazo con motivo en 15 min por webhook o 30 min por sondeo | Estado de rechazo, consulta manual y sondeo preparado | Webhook de cuenta publicitaria con contrato y suscripción comprobados; temporizador desplegado; motivo específico localizado |
| Gasto y clics de ayer | Persistencia y pruebas con fixture de Insights, moneda y fecha de la cuenta | Validar una cuenta real con anuncios autorizados |
| Pausa y cambio de presupuesto con actor y fecha | Pausa autenticada y bitácora; presupuesto con adaptador inyectado y pruebas de consentimiento | Adaptador real de elegibilidad para presupuesto, fecha y reanudación |

La bandeja actual de webhooks admite Instagram, páginas y Facebook. No se añadió una
entrada de cuenta publicitaria inventando el objeto del evento o atribuyéndolo al
propietario que aparezca al procesarlo. La futura integración debe conservar la
propiedad congelada al recibir la notificación y usarla como señal para una lectura
autenticada, no como autoridad para sobrescribir el estado. Mientras no se pruebe ese
contrato, la ruta de quince minutos y «Editar y volver a enviar» quedan pendientes.

Ante un rechazo se muestra una explicación segura en español y se remite al
Administrador de anuncios para el motivo concreto. No se expone texto arbitrario de
Meta, identificadores internos, secretos ni una traducción inventada.
