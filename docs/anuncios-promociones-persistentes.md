# Promociones persistentes — m-24828974

`ads.promotions` y `ads.promotion_repository` guardan la aprobación y la creación
por pasos de una promoción. La migración 0114 añade `ad_promotions` y
`ad_promotion_steps`, con aislamiento por negocio mediante RLS habilitada y forzada.
Esta entrega no conecta rutas, pantallas ni trabajadores, ni realiza llamadas reales.

## Datos y límites

La promoción conserva marca, procedencia, objetivo, categorías especiales, botón,
enlace, presupuesto, moneda, fechas, público, aprobación e identificadores de campaña,
conjunto, creativo y anuncio. El presupuesto usa unidades menores enteras; no se
interpreta la moneda ni se convierten importes. La cuenta vinculada debe confirmar
la misma moneda antes de cada operación.

El campo `meta_ad_account_id` es el identificador remoto numérico, sin `act_`.
Representa la cuenta publicitaria solicitada en ADS-04. No es una clave a una tabla
local: `ad_accounts` todavía no existe. ADS-02 / m-24828972 deberá proporcionar
`AccountBinding` a partir de una selección autorizada y persistida, y podrá añadir
una clave local separada. No debe cambiar el significado ni el tipo de este campo.
No existe una implementación permisiva de ese vínculo en producción. El servicio
comprueba negocio, marca, cuenta y moneda devueltos por el vínculo en cada paso.
La autenticación del cliente y la autorización del usuario son responsabilidad de
ese componente confiable, no se deducen de un identificador enviado por el navegador.

Las claves compuestas impiden referencias a marcas, piezas, publicaciones y usuarios
de otro negocio. Al guardar se comprueba además la marca de la publicación y, cuando
se indican ambos, que el intento publicado corresponde a la pieza del calendario y
al identificador de publicación de origen. Los orígenes sin intento de publicación
pueden representar piezas nuevas o identificadores externos: esta capa no certifica
su elegibilidad publicitaria. Esa comprobación pertenece a ADS-00 y al servicio futuro.

## Aprobación y solicitudes repetidas

La combinación negocio + `request_key` identifica una aprobación. Repetir exactamente
esa solicitud devuelve la misma promoción. Cambiar presupuesto, fechas, cuenta,
contenido o aprobación con la misma clave se rechaza. Una solicitud distinta requiere
otra clave y aprobación. El registro conserva una instantánea completa y su huella;
el esquema impide modificar esa instantánea o reemplazar un identificador remoto ya
guardado. Botón, enlace e identificador de origen indicados en el creativo no pueden
contradecir los metadatos aprobados. Esta capa no construye el asistente ni valida
que el objetivo o el formato sean admitidos por Meta.

## Escritura previa y recuperación

Antes de cada creación se confirma una intención con carga inmutable y un identificador
único de ejecución. Esa transacción es independiente de cualquier transacción exterior,
mediante la puerta autorizada `tenant_session(..., independent=True)`. Los orígenes y
la aprobación deben existir previamente; el consumidor no debe mantener bloqueos
exteriores sobre esos registros. Las campañas, conjuntos y anuncios se envían en pausa;
este servicio no ofrece activación ni aumento de presupuesto.

Los pasos son campaña → conjunto → creativo → anuncio. La confirmación de un paso y
el identificador de la promoción se guardan juntos, comparando el identificador de
ejecución. Los bloqueos del registro padre y la unicidad del paso impiden dos creadores
concurrentes. Una respuesta tardía no puede reemplazar el resultado ya confirmado.

Si el proceso cae o Meta no confirma la respuesta, la intención sigue en curso. No
caduca ni vuelve automáticamente al estado que permite crear. Al reanudar se consulta
la lista de objetos de la misma cuenta, recorriendo todas las páginas; se acepta un
único objeto con el nombre de correlación esperado y, para conjuntos y anuncios, la
misma cadena de padres. Campañas, conjuntos y anuncios recuperados deben estar en
pausa. Si no hay coincidencias, hay varias, faltan datos o el objeto fue activado fuera
de Qualify, se conserva la intención sin crear otra. Los errores de consulta tampoco
autorizan recreación.

El nombre de correlación incluye la promoción, el paso y la huella de la solicitud.
Es una ayuda para conciliar; no es una clave de idempotencia garantizada por Meta ni
una prueba de que Meta conserva sin cambios los campos consultados. La conciliación
contra la API real sigue pendiente de ADS-00. Si no puede verificarse la coincidencia,
la promoción queda detenida para revisión operativa: esta entrega no incluye un
botón para forzar recreación o adoptar identificadores arbitrarios. Incluso un error
que parezca un rechazo definitivo mantiene esa política conservadora. Disponibilidad
tardía de los listados puede requerir una nueva consulta, nunca una creación ciega.

## Verificación

`test_ad_promotions.py` simula interrupciones antes y después de cada creación,
fallos al guardar la respuesta, reanudación con una nueva instancia, concurrencia,
cuentas incompatibles, cambios de aprobación, referencias remotas incompatibles y
paginación. `test_ad_promotions_db.py` comprueba RLS, claves compuestas, instantáneas
inmutables, confirmación con identificador de ejecución y supervivencia de la intención
cuando la transacción exterior revierte. Las pruebas de recuperación no afirman haber
demostrado idempotencia de Meta: usan exclusivamente el simulador en memoria.

La migración debe verificarse en una base desechable cuyo nombre termine en `_test`:
subir a 0114, bajar a 0113, volver a subir, bajar a base y subir a cabeza. No ejecutar
esa secuencia sobre desarrollo, datos compartidos o producción.
