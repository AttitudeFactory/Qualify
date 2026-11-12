# Botón y enlace guardados en la pieza

Entrega m-24828975. La marca puede guardar un enlace predeterminado y cada variante
de una pieza para anuncio puede conservar un enlace y botón propios. Son datos del
contenido: guardarlos no crea anuncios, activa campañas ni autoriza gasto.

## Datos y versiones

- `BrandKit.ads_destination_url` guarda el enlace HTTPS declarado por el dueño.
  Un guardado antiguo que no envía este campo conserva el valor existente; enviarlo
  explícitamente vacío lo elimina.
- `CopyPayload.ads_destination_url` vive en el contenido y en la edición de la
  variante, con las versiones ya existentes. Una pieza nueva para anuncio toma una
  copia del enlace predeterminado al generarse. Cambiar después la marca no modifica
  las piezas guardadas. Al generar otra versión se conserva el enlace de la variante
  anterior, incluida una eliminación explícita.
- Una pieza antigua sin enlace sigue sin enlace. La pantalla puede ofrecer el enlace
  de marca para que el dueño lo guarde expresamente; nunca lo presenta como aprobado.
- La edición pasa por `ContentService.edit_variant`: compara la revisión esperada
  bajo bloqueo, guarda contenido y transición juntos e incrementa la revisión. Una
  pieza aprobada vuelve a revisión. Una pestaña antigua no puede sobrescribirla.
- No se actualizan por SQL las variantes ni las aprobaciones históricas.

## Botones

`AdCTA` restringe los valores al subconjunto acordado: más información, mensaje por
WhatsApp, mensaje, pedir, reservar viaje, reservar, cotización, contacto, llamada,
registro y compra. Las etiquetas se definen una sola vez en `AD_CTA_LABELS`.

Los valores libres antiguos se proyectan al valor conocido más cercano; lo desconocido
se muestra como `LEARN_MORE`. Esa proyección no modifica el texto original guardado.
Las entradas nuevas del editor y de generación usan validación estricta y rechazan
valores desconocidos. Cuando una generación publicitaria no elige botón, se usa
`LEARN_MORE`.

El subconjunto está contrastado con el
[SDK oficial de Meta 26.0.0](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativelinkdatacalltoaction.py).
La existencia de un nombre no garantiza que una combinación de objetivo y cuenta sea
válida. El asistente productivo actual de visitas web solo admite `LEARN_MORE`: si la
pieza guarda otro botón, pide cambiarlo expresamente, sin sustituirlo ni activar otro
tipo de anuncio. Un valor histórico ambiguo debe guardarse de nuevo antes de anunciar.

## URL y generación

Se valida el enlace completo HTTPS, su host, longitud y ausencia de credenciales,
espacios o caracteres de control. La validación no abre ni resuelve el destino.
WhatsApp puede expresarse como un enlace `https://wa.me/...`.

El enlace no se pide al modelo: se retira de su esquema de respuesta y las instrucciones
no lo incluyen. El servicio sustituye incluso una respuesta no conforme por el enlace
declarado por el dueño, antes de guardar la variante. El botón sí se pide como enum.
La procedencia de las generaciones publicitarias registra el contrato
`piece-ad-destination-v1` y si el enlace venía de marca o de pieza.

Las pruebas de esta entrega usan datos sintéticos sin red. El contrato del modelo se
documenta en `modelos-generativos/botones-anuncios-20261112.md`; no se afirma una mejora
de calidad del modelo ni compatibilidad de una cuenta real sin medirla.
