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

Para anuncios rechazados o con problemas se consulta `issues_info`. El SDK oficial
[AdgroupIssuesInfo 26.0.0](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adgroupissuesinfo.py)
declara `error_summary` y `error_message` como texto. Se prefiere el resumen y se presenta
como **Motivo informado por Meta**, siempre como texto escapado. Se rechazan listas
extensas, textos largos, HTML, controles invisibles, direcciones web y señales de
credenciales; el objeto completo y sus identificadores internos nunca se guardan.
La causa saneada conserva origen, credencial, fecha y versión de procesamiento y sólo
se muestra junto con la observación correspondiente. Una respuesta de otra cuenta
no puede almacenarla. Si falta una causa segura se conserva el aviso general.

No se traducen ni se deducen infracciones a partir de códigos: `error_code` no se
interpreta como `error_subcode` de Graph. No se verificó una garantía de idioma de Meta;
los títulos y avisos de Qualify son españoles, pero la cita del motivo podría venir en
otro idioma. El caso específico en español se prueba con una respuesta simulada y
queda pendiente comprobarlo con una lectura real autorizada.

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

La solicitud y la aprobación originales de `ad_promotions` permanecen intactas. El
presupuesto y la fecha actuales se proyectan exclusivamente desde cambios confirmados
o reconciliados de la bitácora; una modificación externa o una operación incierta no
se convierte en una nueva aprobación.

`prepare_promotion_edit` comprueba la cadena remota completa y valida el cambio exacto
con `execution_options=["validate_only"]`. Devuelve una revisión firmada válida durante
cinco minutos. La firma utiliza el secreto OAuth existente, un propósito criptográfico
distinto y JSON canónico; vincula negocio, sesión, actor, solicitud, credencial, cuenta,
aprobación original, historial, estado previo e intención. El secreto de desarrollo no
habilita este camino. La revisión no equivale a consentimiento: `confirm_promotion_edit`
exige confirmación explícita y vuelve a comprobar actor, permisos, pagos y cadena.

El alcance inicial es COP con subdivisión Meta comprobada de uno, presupuesto total y
activación original aprobada y terminada. Se permite aumentar o reducir el presupuesto en
pesos completos y cambiar la fecha de fin, con el mismo consentimiento exacto, la misma
bitácora (quién, cuándo, antes y después) y la misma separación de treinta segundos.

**Reducción del presupuesto (m-24828979).** Antes de la revisión y otra vez justo antes de
reservar la operación se lee del propio conjunto de anuncios `lifetime_budget` y
`budget_remaining` (lo gastado es la diferencia; nunca se suman resultados diarios), y de
`act_<id>/minimum_budgets` el mayor `min_daily_budget*` en COP. El nuevo presupuesto no
puede bajar de `max(gastado + mínimo diario × días que faltan, mínimo diario × días
programados)`; si baja, se rechaza sin enviar nada a Meta y se muestra el importe mínimo.
El límite calculado queda en la evidencia de la operación. Esta regla es de Qualify y más
conservadora que la de Meta; la palabra final sigue siendo `validate_only` sobre el
importe exacto. **Pendiente de medir en vivo:** las unidades de `minimum_budgets` y
`budget_remaining` para COP (se asumen en pesos enteros, como `lifetime_budget` con
subdivisión 1) y qué campo mínimo aplica a cada objetivo.
La reanudación exige que campaña y conjunto tengan exclusivamente los objetos propios,
activa sólo los niveles pausados y deja la campaña para el final.

La reserva compara el historial bajo bloqueo de la promoción, conserva actor, fecha e
intención antes del envío y rechaza revisiones anteriores aunque alguien restaure en
Meta un presupuesto viejo. Cada escritura vuelve a comprobar la cadena con otro cliente
y termina con controles locales después de las esperas y del cierre de las lecturas.
Cualquier fallo posterior a la reserva produce un resultado incierto y nunca reenvía
la escritura. La reconciliación de estos cambios sólo hace lecturas y exige la cadena
completa resultante, el historial aprobado y la política vigente. Un resultado parcial
mantiene el bloqueo.

Fuentes primarias consultadas el 8 de noviembre de 2026: `api_update`,
`execution_options` y `validate_only` en el SDK oficial de
[AdSet](https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adset.py),
[Ad](https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/adobjects/ad.py) y
[Campaign](https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/adobjects/campaign.py).
Se probaron mediante HTTP simulado y PostgreSQL real; no se enviaron cambios a Meta real.

## Avisos de la cuenta publicitaria (webhooks)

Desde la migración `0154`, `admit_meta_webhook` admite `object = "ad_account"`: una
entrada cuyo id (con o sin `act_`) es una cuenta publicitaria **elegida y disponible** de
una conexión viva. Los dueños se congelan al recibir, igual que con Páginas e Instagram;
una cuenta desconocida o no elegida se descarta sin guardar el cuerpo.

El procesador (`ads/status_webhook.py`) atiende `ad_account:with_issues_ad_objects` y
`ad_account:in_process_ad_objects`. Del valor sólo usa `id` como señal: bajo la sesión RLS
de cada dueño congelado busca sus promociones de esa cuenta cuyo anuncio, conjunto o
campaña coincide y ejecuta la **misma lectura autenticada** del sondeo
(`refresh_promotion_from_signal`). El aviso nunca sobrescribe el estado por sí mismo;
el estado «Rechazado por Meta» y el motivo saneado salen de esa lectura. Un anuncio que
Qualify no creó queda `unsupported` sin leer nada; una lectura fallida se reintenta con
la espera de la bandeja y el sondeo sigue de respaldo. Repetir el aviso sólo repite la
lectura.

La suscripción es explícita y asistida: `subscribe_ad_account_webhooks` exige sesión,
pertenencia y confirmación del dueño, comprueba la cuenta elegida y la credencial antes
de escribir, consulta `act_<id>/subscribed_apps` y sólo hace un `POST` con `app_id` si la
app no estaba suscrita. Nunca se llama de forma automática ni se reintenta.

Varios avisos de una misma revisión (los dos campos, para anuncio, conjunto y campaña) no
multiplican las lecturas: si ya hubo una lectura correcta iniciada después de que Meta
enviara el aviso y dentro del último minuto, el aviso se cierra como `recently_read` sin
volver a consultar Meta.

> **Hoy la vía de avisos está inactiva.** Ninguna pantalla llama todavía a
> `subscribe_ad_account_webhooks`, y los campos del objeto «Ad Account» deben activarse en
> la configuración de webhooks de la app en Meta. Mientras falte cualquiera de las dos
> cosas no llega ningún aviso y el plazo depende sólo del sondeo de treinta minutos.

**Sin comprobar en vivo** (no se hicieron llamadas reales): la forma exacta del valor de
cada campo, el id de la entrada (`act_` o número), los parámetros de
`act_<id>/subscribed_apps` y que los campos estén activados en la configuración de
webhooks de la app (objeto «Ad Account»). Falta también la pantalla que ofrezca la
suscripción al dueño.

## Consulta periódica y despliegue

Comando disponible, de solo lectura y con negocio obligatorio:

```powershell
uv run --no-sync python -m qualify_api.ads.results_cli --tenant <uuid>
```

Cada ejecución toma promociones consultables cuya última tentativa tiene al menos veinticinco
minutos, hasta el límite indicado. No escribe en Meta. Imprime solo cantidades de
promociones consultadas o no disponibles. **Este PR no instala un temporizador en
producción por defecto**: el proceso combinado `qualify_api.ads.reads_cli` tiene un
servicio configurado con cero réplicas, documentado en `deploy/ads-reads-worker.md`.
Herwin debe comprobar la memoria disponible antes de activar una réplica y verificar
el intervalo, la duración de los lotes y las credenciales de los negocios autorizados
antes de afirmar la garantía de treinta minutos. Un intervalo configurado no demuestra
por sí solo ese plazo en producción.

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
| Rechazo con motivo en 15 min por webhook o 30 min por sondeo | Estado, motivo específico saneado y atribuido a Meta cuando existe; consulta manual, sondeo y avisos de la cuenta publicitaria con dueño congelado que disparan la lectura autenticada; suscripción explícita | Activar y medir el sondeo y el aviso en producción (campos activados en la app, suscripción de cada cuenta); validar una respuesta real y su idioma; pantalla para suscribirse |
| Gasto y clics de ayer | Persistencia y pruebas con fixture de Insights, moneda y fecha de la cuenta | Validar una cuenta real con anuncios autorizados |
| Pausa y cambio de presupuesto con actor y fecha | Pausa y adaptador real de preparación y confirmación para aumentar o reducir presupuesto, cambiar fecha y reanudar, con consentimiento exacto, bitácora y controles de concurrencia | Validación real autorizada en Meta; medir unidades de `minimum_budgets`; volver a enviar un anuncio rechazado |

«Editar y volver a enviar» un anuncio rechazado sigue pendiente: corregirlo exige crear
una creatividad nueva (o cambiar el enlace) y sustituirla en el anuncio, una escritura
que la bitácora actual (presupuesto, fecha, pausa, reanudación) no modela ni la
comprobación `remote_guard` admite, porque fija la creatividad aprobada. Necesita su
propio diseño de consentimiento.

Ante un rechazo se muestra el motivo específico de `issues_info` únicamente cuando
supera el filtro estricto, atribuido mediante **Motivo informado por Meta** y renderizado
como texto escapado. Su idioma procede de Meta y no se garantiza español. Si falta un
texto seguro, se muestra el aviso general en español y se remite al Administrador de
anuncios. No se exponen objetos completos, identificadores internos, secretos ni una
traducción inventada. Estas pruebas locales no bastan para cerrar `m-24828979`: siguen
pendientes la comprobación real autorizada y el sondeo activo y medido en producción.
