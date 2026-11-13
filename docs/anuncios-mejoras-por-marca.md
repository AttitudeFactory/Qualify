# Permisos de cambios publicitarios por marca

Entrega de `m-24828984`. Cada marca puede guardar si permite cuatro cambios de Meta:
retoques de imagen, ajustes de texto, cambios del botón y animación de imágenes.
Los cuatro están apagados cuando no hay una decisión guardada. Son permisos para
futuras promociones; guardarlos no modifica anuncios existentes, no activa anuncios
ni prueba que Meta acepte esos cambios en una publicación ya publicada.

## Decisión e intención aprobada

`ad_brand_enhancements` guarda negocio, marca, versión, las cuatro decisiones exactas,
identidad de quien las guardó, fecha y versión del proceso. La lectura y escritura de
la pantalla requieren una sesión con pertenencia vigente al negocio. Una marca de otro
negocio no se puede consultar ni modificar. El guardado compara la versión leída;
si otra persona la cambió, exige volver a cargar. Guardar exactamente lo mismo no
cambia la versión. La primera escritura y las siguientes se serializan con la aprobación
mediante un bloqueo de marca, también cuando todavía no hay fila de preferencias.

Cada solicitud nueva conserva una copia canónica e inmutable en
`enhancements_snapshot`. Su creatividad contiene
`degrees_of_freedom_spec.creative_features_spec`: cada uno de los cuatro campos lleva
`enroll_status=OPT_OUT` o `OPT_IN` explícito. No se interpreta la ausencia como permiso.
La estructura rechaza campos desconocidos y valores que no sean booleanos; no admite
música, otras mejoras ni paquetes de opciones añadidos arbitrariamente.

El repositorio comprueba versión y decisiones actuales antes de insertar una nueva
promoción. Cambiar la marca, las decisiones o su versión cambia el hash de aprobación.
Una solicitud nueva sin esta decisión canónica se rechaza. Una repetición exacta de una
aprobación anterior conserva su hash y contenido, sin añadirle cambios retroactivamente.
Las promociones antiguas ya creadas siguen intactas; una creación antigua incompleta
requiere una nueva aprobación antes de continuar escribiendo en Meta.

La configuración de una marca no se aplica a otras marcas del mismo negocio. Cambiarla
no reescribe promociones anteriores ni sus consentimientos. Una vista previa preparada
con una versión distinta deja de autorizar la activación y debe prepararse de nuevo.

## Comprobación y vista previa

El flujo actual parte de publicaciones de Instagram ya publicadas. No se pudo comprobar
con Meta qué mejoras son compatibles con ese formato. Por eso permitir un cambio en
la marca **no habilita usarlo en producción**. El bloqueo previo de creación y activación
real del asistente permanece. No se instala ningún temporizador ni regla de gasto.

El orquestador inyectado exige, para cualquier opción encendida, evidencia medida de
compatibilidad ligada a política, pieza, cuenta, conexión y versión de credencial.
Un booleano de elegibilidad o texto HTML no bastan. También exige un adaptador explícito
que compruebe la identidad remota del anuncio y de su creatividad y el contenido
creativo efectivo frente a la solicitud exacta. No hay un adaptador real compuesto en
producción: si falta, la opción encendida no puede pasar esa comprobación.

La vista previa conserva hash del contenido, solicitud, política y versión, anuncio,
creatividad, publicación, conexión, credencial y persona que la preparó. El momento de
observación se fija en el servidor y su vigencia máxima es cinco minutos, incluso si
la comprobación general anuncia una duración mayor. Al confirmar se vuelve a exigir
una prueba remota fresca que coincida con esa identidad y creatividad. Antes de cada
escritura, incluido después de esperar el cliente, se vuelven a comprobar pertenencia,
configuración actual, identidad, plazos de la evidencia de compatibilidad y de la prueba
remota. Un vencimiento durante esa espera no permite enviar la activación.

Estas pruebas tienen una vigencia acotada; no se promete atomicidad frente a cambios
hechos simultáneamente por otro operador directamente en Meta. La conciliación de una
activación de resultado desconocido sigue siendo solo de lectura y puede observarse
después del vencimiento sin volver a enviar una activación.

## Evidencia y límites

Los nombres y tipos se contrastaron con el SDK oficial de Meta 26.0.0:

- [Estructura de grados de libertad](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativedegreesoffreedomspec.py).
- [Campos de mejoras creativas](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativefeaturesspec.py).
- [Detalle de inscripción](https://github.com/facebook/facebook-python-business-sdk/blob/26.0.0/facebook_business/adobjects/adcreativefeaturedetails.py).

Los cuatro campos son `image_touchups`, `text_optimizations`, `enhance_cta` e
`image_animation`. El SDK describe `enroll_status` como cadena. El corpus oficial guardado
contiene ejemplos históricos de `OPT_OUT`; no acredita que las cuatro combinaciones
sean aceptadas hoy para piezas existentes. La documentación actual no estuvo accesible.
No se deduce compatibilidad de que un campo aparezca en el SDK.

Apagar estos cuatro permisos no promete que toda transformación posible o futura de
Meta esté desactivada. La interfaz explica el conjunto concreto que se está guardando.
No se hicieron llamadas publicitarias reales, no se activaron anuncios ni se gastó
dinero durante esta implementación. Los casos de compatibilidad y vistas previas se
prueban con adaptadores explícitos y datos simulados, sin sustitutos automáticos reales.

| Criterio | Entregado | Pendiente |
|---|---|---|
| Todo apagado envía inscripción negativa explícita | Compilador exacto para las cuatro opciones y pruebas de la solicitud y carga creativa | Aceptación real de Meta para el formato de publicación existente |
| La configuración de marca se aplica a cada promoción nueva | Preferencias con versión, instantánea aprobada, validación del repositorio y pruebas de aislamiento y concurrencia | Componer y medir los adaptadores reales antes de habilitar ejecución |
| Una opción encendida exige vista previa antes de activar | Contratos estrictos de compatibilidad y vista previa remota, identidad exacta y vencimientos comprobados antes de cada escritura | Compatibilidad, permisos y vista previa reales de una cuenta autorizada |
| Pausa automática por costo alto | No implementada; continúa como trabajo posterior | Definir y aprobar reglas, datos, límites y operación productiva |

Migración `0130`, posterior a `0129`, con claves compuestas de marca y negocio,
RLS habilitado y forzado, política `NULLIF`, permisos de aplicación acotados y reversión.
Eliminar una marca elimina sus preferencias; las decisiones forman parte de la marca,
no de una cuenta social concreta. La revisión visual móvil y la validación de extremo
a extremo real no se sustituyen por las pruebas de componentes y datos simulados.
