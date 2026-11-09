# Cliente de anuncios de Meta — m-24828973

`qualify_api.ads.client.MarketingClient` es el límite HTTP de anuncios. No está conectado
a rutas, pantallas ni trabajadores. No crea campañas al iniciar la aplicación. Las
pruebas usan exclusivamente memoria y `httpx.MockTransport`.

La versión se configura con `QUALIFY_META_ADS_API_VERSION` (predeterminada `v26.0`).
`QUALIFY_META_API_VERSION`, OAuth y la publicación orgánica conservan su configuración.
El constructor recibe el cliente ya autenticado de `CredentialResolver`, nunca una
credencial. El consumidor conserva la responsabilidad de cerrar ese cliente, verificar
que la cuenta pertenece al negocio y obtener la aprobación de gasto.

## Contrato

`MarketingAPI` define las operaciones. `create(resource, params=...)` y `list(resource,
params=...)` aceptan `campaigns`, `adsets`, `adcreatives` y `ads`. Las escrituras codifican
los objetos anidados como JSON en campos de formulario; no envían credenciales por URL.
`update(id, params=...)` modifica un objeto; `status(id)` lee su estado. Las políticas de
activación, presupuesto y aprobación corresponden al servicio futuro, no a este cliente.

Las lecturas adicionales son `adpreviews(ad_id, params=...)` (ruta `/{id}/previews`),
`minimum_budgets`, `reachestimate(targeting_spec=...)`, `targetingsearch(params=...)`,
`search_locations(query=...)`, `search_interests(query=...)` e `insights(id?, params=...)`.
No se hardcodean objetivos, permisos, mínimos monetarios o categorías permitidas.

Los listados devuelven `MarketingPage(data, after)`: una sola página y un cursor para
la siguiente. El consumidor pasa `after` en la siguiente petición. Se descarta la URL
`paging.next`, que puede contener una credencial. No se siguen URL remotas ni redirecciones
desde el código del cliente. Las filas se conservan como diccionarios porque sus campos
dependen del recurso, la versión y los campos solicitados.

`FakeMarketingClient` implementa el mismo contrato: guarda objetos creados y sus cambios;
las otras lecturas requieren una respuesta explícita en `responses[(verbo, ruta)]`.
`failures` permite simular errores. No valida políticas ni simula resultados de entrega.

## Errores, credenciales y espera

Los errores conservan solamente código, subcódigo, estado HTTP, espera sugerida y si la
escritura pudo haber ocurrido sin confirmación. Nunca incorporan el mensaje localizado,
el cuerpo, la petición ni la excepción HTTP original. Los códigos principales y los
subcódigos se consultan en tablas separadas; el subcódigo conocido tiene prioridad.
Se rechazan credenciales en los parámetros y la combinación de `instagram_user_id` e
`instagram_actor_id`, incluso dentro de objetos, listas y JSON ya serializado.

**No hay reintentos automáticos.** Un tiempo de espera, respuesta ilegible o confirmación
de creación incompleta marca `outcome_unknown=True`. El servicio de m-24828974 deberá
conciliar antes de repetir una escritura; este cliente no promete creación idempotente.

Las llamadas de una instancia se serializan. Después de leer `X-Business-Use-Case-Usage`
(también se acepta `X-Business-Use-Case`), `X-Ad-Account-Usage` y `Retry-After` numérico,
la próxima llamada espera. Se interpretan los estimados BUC en minutos y la duración de
restablecimiento de cuenta en segundos; ADS-00 debe contrastar esos datos con las
cabeceras reales. Como política local conservadora, uso de al menos 90% espera un mínimo
de 60 segundos; los códigos 17/613/80004 y HTTP 429 también esperan al menos 60 segundos,
y el subcódigo 4841018 al menos 30. Cabeceras ausentes o malformadas no inventan cuotas.
La espera se mantiene por instancia: el futuro servicio debe reutilizar una instancia
por cuenta o coordinar procesos si necesita un límite compartido. No se implementa un
límite distribuido aquí.

## Evidencia y pendientes de validación

Consulta documental del 2026-11-02, sin llamadas autenticadas ni gasto:

- El [SDK oficial de Meta, configuración](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py)
  declara `API_VERSION=v26.0` y `SDK_VERSION=v26.0.2`.
- [AdAccount del SDK oficial](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py)
  declara las rutas de campañas, conjuntos, creativos, anuncios, `minimum_budgets`,
  `reachestimate`, `targetingsearch` e `insights`.
- [Ad del SDK oficial](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/ad.py)
  declara `/{id}/previews`; [TargetingSearch](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/targetingsearch.py)
  declara `/search` con `adgeolocation` y `adinterest`.
- Las referencias oficiales de [errores](https://developers.facebook.com/docs/marketing-api/error-reference/),
  [límites](https://developers.facebook.com/docs/graph-api/overview/rate-limiting/) y
  [versiones](https://developers.facebook.com/docs/graph-api/changelog/versions/) devolvieron
  HTTP 429 durante la consulta. No se usaron fuentes secundarias como confirmación.

La lista numérica inicial viene de ADS-03. Las causas detalladas de los subcódigos no
se pudieron confirmar de forma independiente. 1885183, 1815199, 4841018, 1373054 y
2446383 usan la explicación prudente de la épica. 2238055, 2446149, 1885272, 1885650,
1885621, 1885029, 1885557, 1713092 y el código 2654 reciben un mensaje genérico que pide
revisar la configuración, sin atribuir una causa no verificada. Los códigos 294 y 190
orientan a revisar permisos y conexión. ADS-00 debe confirmar las causas, permisos,
objetivos, cabeceras, formato real de respuesta y elegibilidad antes de conectar el
flujo de gasto. La aprobación de la versión del SDK no prueba acceso a una cuenta real.

## Verificación

`uv run --no-sync pytest packages/api/tests/test_ads_client.py -q` cubre el ciclo de
objetos, cada lectura, codificación HTTP, separación de versiones, cada código y
subcódigo, conflictos de identidad, protección de credenciales, paginación, respuestas
inválidas y espera antes de la siguiente solicitud. `just ci-lint` y `just ci-test`
comprueban el conjunto offline del repositorio. No hay cambios de esquema.
