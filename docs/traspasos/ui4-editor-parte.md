# UI-4: contrato interno del editor de una parte

Ticket: m-24921078. Decisiones de implementación acordadas en la sesión del
2026-11-11; no constituyen una nueva decisión de producto ni un ADR firmado.

## Datos y herencia

`_PartSource` comparte estos campos entre `VideoPartPlan` y `PartRef`:

| Campo | Valor inicial | Semántica |
|---|---|---|
| `clip_image_keys` | `None` | Hereda las fotos efectivas del padre; `()` las vacía expresamente. |
| `clip_image_roles` | `()` | Sin roles explícitos, todas las fotos son del producto. |
| `clip_video_keys` | `()` | Videos propios de esta parte; nunca hereda videos del padre. |
| `clip_audio_keys` | `()` | Audios propios de esta parte; nunca hereda audios del padre. |

Se conservan los límites existentes de Clip: 9 imágenes, 3 videos y 3 audios.
Los roles explícitos deben coincidir en cantidad y pertenecer al vocabulario
existente. La lectura de JSON antiguo conserva el comportamiento anterior.
Las fotos efectivas del padre incluyen todas las seleccionadas para sus partes,
también las que el formulario de Clip habría colocado en los extremos: el padre
por partes no conserva esos campos de fotograma.

## Modos y medios

`reference` admite los medios propios seleccionados. `edit` exige fotos y una
fuente: exactamente un video propio o una ventana del reel analizado; no admite
audio de referencia. Un video propio sustituye la fuente pública y evita su
recortador. Su duración real debe coincidir con `max(seconds, 4)` con tolerancia
de 0,5 s; no se inventan recortes, rellenos ni cambios de duración.

Para editar la fuente pública se comprueban su disponibilidad, elegibilidad,
formato vertical y todos los cortes cubiertos: ninguna persona ni rostro observado
o incierto, según F6. La fuente propia sigue las reglas actuales de Clip; la
presencia de personas en el reel sustituido no describe el archivo propio.

`extend` se muestra desactivado mientras faltan VE-13 y m-24880328. Los planes
existentes conservan su modo; no se traducen silenciosamente a otro. Se conserva
la restauración que UI-3 ya permite para una entrada nacida como continuación.
Avatar y la regeneración de UI-8 quedan fuera de alcance.
Si una parte activa conserva `extend`, UI-6 bloquea tanto la creación completa
como la primera vista previa y ofrece cambiar esa parte explícitamente. La misma
guarda actúa antes de crear el padre y antes de preparar o cobrar nuevas hijas;
una lectura idempotente de hijas ya existentes no crea trabajo nuevo.

Una entrada nacida como continuación puede pasar explícitamente a `reference`
o a `edit` con video propio, conservando `original_mode="extend"`, duración,
análisis y cortes. **No puede editar la fuente pública**: el plan no guarda el
desplazamiento del tramo dentro del corte largo y el recortador empezaría otra vez
en su inicio. No se inventan desplazamientos ni recortes para resolverlo.

La continuación convertida es independiente y puede moverse antes de la cabecera
del corte largo. La excepción de cortes repetidos debe ser independiente del
orden: para cada análisis y corte se admite como máximo un origen ordinario; las
repeticiones adicionales deben ser continuaciones reales válidas o entradas
convertidas con el marcador canónico, un único corte y un modo independiente
admitido. Solo el modo `extend` real exige seguir a la entrada anterior. El
backend comprueba contra el análisis que el corte dure más de 10 s y no se use
más veces que las divisiones de `_split`; el guardado conserva las firmas
canónicas de duración y origen. El esquema sin análisis no certifica por sí solo
que el marcador venga del planificador.

## Guardado, identidad y seguridad

Guardar confirma el borrador local por la clave estable de la fila y transmite
estos campos en el plan que UI-6 persiste. La ruta de guardado del padre mantiene
`tenant_session`, bloqueo del padre, rechazo si existen hijos y actualización
atómica de su JSON. No crea trabajos, cargos ni llamadas a proveedores.

Las firmas inmutables de origen se comparan como un multiconjunto, consumiendo
cada entrada guardada una vez; se emparejan primero las coincidencias exactas.
El editor cambia descripción, modo permitido y medios, sin falsificar análisis,
cortes, duración, recortes ni `original_mode`. «Añadir parte» coloca al final una
entrada manual `reference`, sin origen público; después puede reordenarse, quitarse
y restaurarse en UI-3 antes de persistir el plan. El servidor admite esa posición
final y su historial, conservando cada origen canónico exactamente una vez.
Una descripción completa permite retirar `describe_it`.

El límite es de **6 partes activas**. Las retiradas se conservan y no consumen
plazas; restaurar una cuando ya hay seis debe rechazarse expresamente.
La elegibilidad de ejecución y las fotos requeridas se comprueban en las partes
activas. Un origen vencido o la falta de fotos en una parte retirada no bloquean
los demás cambios; restaurarla vuelve a exigir esas condiciones. La forma, la
identidad del origen y la propiedad de sus claves se validan también en el historial.

### Juntar una parte corta con la siguiente

El botón prometido por UX §3c usa una función pura compartida por UI y backend.
Solo junta una parte pública de menos de 4 s con su siguiente parte activa cuando
ambas tienen el mismo análisis y rangos de cortes consecutivos, disjuntos y sin
divisiones de un corte largo. Ninguna puede ser continuación, tener recortes,
videos o audios propios; sus selecciones explícitas de fotos y roles deben ser
iguales. La fuente debe seguir disponible, ser vertical y elegible según F6 en
todos los cortes. La suma real de los cortes, redondeada a segundos enteros como
en el planificador existente, debe quedar entre 4 y 10 s.

El resultado contiene exactamente la unión de cortes y conserva la descripción
de ambas partes, permitiendo unir frases repetidas. Si excede el máximo existente
se rechaza con una indicación para abreviar; nunca se trunca lo escrito por el
dueño. Los avisos se reúnen y se retira `describe_it` si hay descripción. El modo
y `original_mode` se calculan desde las fuentes canónicas elegibles, no desde
valores que declare el cliente.

Al guardar en el servidor se consumen una vez las dos entradas canónicas de
origen y se recalcula la unión; cualquier otra alteración de procedencia se
rechaza. El historial de partes retiradas no cambia. En la hoja, la unión queda
pendiente hasta Guardar, que sustituye ambas filas de forma atómica; Cancelar las
conserva. Si la unión no es posible se muestra el motivo. No lee archivos ni
llama a proveedores.

Se validan las claves de todos los medios anidados, tanto activos como retirados,
antes de persistir o leer: formato válido y propiedad del negocio. Las lecturas
usan las puertas existentes. Se prefiere conservar la duración del normalizador
en los datos de la subida y en una caché por clave; una consulta de respaldo debe
validar la clave antes de una lectura acotada, sin normalizar ni codificar.
El proceso generador vuelve a comprobar duración, claves, modelo y enlaces antes
de pagar. Los medios elegidos nunca se omiten para permitir una alternativa.

## Responsabilidad y comprobación

Creative: esquemas, transformación de hija, guardado, guardas, medios y pruebas
de backend. UI: estado, proveedor, presentación, navegación y pruebas de interfaz.
Arquitectura: este contrato y su revisión.

Pruebas sin red: JSON antiguo; heredar/vaciar; claves ajenas antes de leer; F6;
combinaciones incompatibles; duración; identidad; unión válida y adulterada,
descripción demasiado larga; añadido y restauración con seis;
bloqueo al existir hijos; medios en la petición y presupuesto; guardar sin pagar.
En navegador: 375 px y escritorio, URL `parte`, atrás, Escape, foco, cancelar y
guardar. La fidelidad de los nuevos conjuntos de referencias no se mide contra
proveedores en esta sesión: solo se comprueban estructura y guardas localmente.
