# Anuncios desde imágenes de una pieza sin publicar

Entrega backend de m-24828982. Implementa el recorrido para **dos imágenes finales ya
existentes**, una de 4:5 y otra de 9:16, de una pieza aprobada que todavía no se publicó.
No modifica el generador, `CopyPayload`, las opciones de botón ni el trabajo de m-24828975.
El texto, título y enlace se reciben explícitamente en la solicitud de anuncios. No se
escriben de regreso en la pieza.

## Entrada para la integración

`UnpublishedImageService(ObjectGate(...))`, en `qualify_api.ads.unpublished_service`,
expone `prepare` y `confirm`. Las dependencias por defecto son los repositorios reales
de PostgreSQL y el cliente de Marketing autenticado por el resolvedor existente. No hay
un cliente simulado de reserva ni una variable que salte comprobaciones.

La integración debe proporcionar negocio, pieza, cuenta seleccionada y los identificadores
de las dos imágenes existentes. Nunca admite una URL, clave de R2 ni identificador de
imagen publicitaria suministrados por el cliente. Requiere la sesión real y el usuario
interno que aprueba. La selección tiene que pertenecer a la versión activa y aprobada
de esa misma pieza y marca. Rechaza videos, carruseles, piezas purgadas y partes de video.

La solicitud `ImageAdForm` lleva mensaje, título, enlace HTTPS, presupuesto total interno,
fechas y país. En esta primera entrega admite COP, visitas al sitio web, «Más información»,
Instagram y un país explícito. No selecciona un país por defecto. Los límites locales de
Qualify son 8 MiB por imagen, 2.200 caracteres de mensaje y 100 de título. No son una
afirmación sobre los límites de Meta. Meta debe aceptar la validación exacta de la solicitud.

## Preparación y confirmación

1. La preparación exige `confirm_preparation=True`, comprueba cuenta, acceso y pagos, y
   conserva una solicitud inmutable con pieza, versión, revisión, cuenta y credencial.
2. Abre los archivos mediante `ObjectGate`, mide bytes, MIME y dimensiones, y calcula su
   resumen SHA-256. No cambia los archivos ni fabrica recortes.
3. Guarda y confirma en PostgreSQL la intención de cada carga **antes** del POST a
   `/act_<id>/adimages`. La carga queda ligada a negocio, cuenta, versión de credencial,
   imagen y contenido. Una carga incierta o interrumpida no se vuelve a enviar.
4. Compila `object_story_spec` y `asset_feed_spec` con reglas de 4:5 para publicaciones y
   9:16 para historias y reels. Los cuatro cambios creativos de marca deben estar apagados.
   Valida campaña, conjunto, creatividad y anuncio con `validate_only`.
5. Reutiliza `PromotionService` y su registro de creación para crear los objetos en pausa.
   Obtiene vistas previas de publicación e historia y guarda una revisión de cinco minutos.
6. La activación requiere `confirm_charge=True` en otra llamada, misma persona, revisión
   vigente y contenido idéntico. Comprueba otra vez cuenta, fuente, permisos y objetos
   remotos. Confirma el reclamo de activación antes de las escrituras y activa primero los
   hijos y al final la campaña. No permite reintentar una activación incierta.

Las comprobaciones finales vuelven a leer la pieza y los resúmenes del archivo. Las lecturas
remotas dentro del control previo de escritura usan otro cliente autenticado para no
reentrar en el bloqueo del cliente que va a escribir. No se mantiene una transacción de
fuente abierta mientras espera a Meta; no se promete atomicidad frente a otro operador.

La propiedad de resultados y pausa tiene una ruta específica que une promoción, receta,
negocio, pieza, marca, cuenta, conexión y credencial. No afloja las uniones del recorrido de
publicación existente. Una edición posterior de la pieza no impide consultar o pausar el
anuncio que ya se autorizó. Cambiar presupuesto, fecha o reanudar por el gestor anterior
queda expresamente fuera de esta entrega: ese gestor todavía requiere una publicación.

Las vistas previas son contenido remoto sin confianza. La futura interfaz debe usar el
saneamiento de vistas previas existente; no debe insertar ese HTML directamente.

## Evidencia y límites reales

Se consultó el SDK oficial de Meta fijado en 26.0.0 el 12 de noviembre de 2026:

- [Cuenta publicitaria](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adaccount.py): carga `adimages` con `bytes` y solicitudes de validación.
- [Historia de creatividad](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativeobjectstoryspec.py): `page_id` e `instagram_user_id`.
- [Contenido por ubicación](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adassetfeedspec.py): imágenes, textos, enlaces y botones.
- [Reglas por ubicación](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adassetfeedspecassetcustomizationrule.py) y [posiciones](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adassetcustomizationrulecustomizationspec.py): etiquetas y selección de plataformas y posiciones.
- [Vistas previas](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adpreview.py): formatos de Instagram.

Estos archivos acreditan nombres y tipos, **no compatibilidad ni permisos de una cuenta
real**. Cada preparación debe superar las validaciones reales antes de crear los objetos;
la confirmación exige identidad y contenido remotos iguales a los aprobados. Si Meta
normaliza o enriquece el contenido de una forma que no coincide, se rechaza la confirmación
en vez de asumir equivalencia. Debe medirse esa respuesta antes de anunciar disponibilidad.

No se hicieron cargas, campañas, activaciones ni gasto reales durante el desarrollo.
Las pruebas de transporte y servicio usan datos sintéticos y clientes explícitos sin red.

## Pendiente del ticket completo

- Integración en una pantalla de anuncios con selección de imágenes, revisión y confirmación.
- Carga y procesamiento asíncrono de videos, miniaturas y sus comprobaciones.
- Prueba real autorizada, con publicación de vista previa, formatos y presupuesto concretos.
- Gestión posterior de cambios pagados para esta nueva clase de fuente.

Este backend no añade un botón a la pieza ni completa por sí solo m-24828982. No requiere
un token nuevo ni activa procesos periódicos al desplegarse. La migración 0150 añade los
registros de fuente y carga con RLS forzado, procedencia e invariantes reversibles. El lector
periódico de resultados conserva su configuración y preparación operativa existentes.
