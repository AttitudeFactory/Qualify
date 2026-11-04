# Logos integrados y continuidad en réplicas

Fecha: 30 de octubre de 2026. Comparación: `56746531` → `d048a5b8` →
`3db64355`, más esta corrección. Se revisó código, datos locales de un cliente y
pruebas con proveedores simulados. No se hicieron generaciones pagadas ni se
cambiaron modelos, proveedores, parámetros de calidad o límites del proveedor.

## Qué cambió y qué se encontró

El texto general de generación de textos no fue reemplazado. En
`qualify_creative/brand/render.py`, `_chosen_resources` añadió la ubicación integrada
y los nombres/notas de recursos secundarios. En `creative/media.py` sí cambiaron
instrucciones: referencias, categorías e índices, letras permitidas del logo,
continuidad, reemplazo de marcas del dueño del video y controles previos de tamaño.

El compilador compacto usado con logos secundarios en `3db64355` debilitó dos
órdenes anteriores: reemplazar el producto consistentemente durante las acciones y
no cortar a una foto de catálogo. Además, una referencia sin notas recibió
«preserve identity» en vez de una instrucción de integración natural. Son diferencias
confirmadas; no demuestran por sí solas la causa de un resultado visual.

La réplica local `fb2d9a5c-436b-47e5-952b-037ccbd413ca`, revisión 2, conservaba modo
integrado y tres referencias en ambas instantáneas: imagotipo principal, isotipo e
isologo secundarios, sin firma local. No había solicitudes capturadas en
`creative_pipeline_steps` para verificar el cuerpo exacto enviado al proveedor.
Por ello no se atribuye el fallo visual a una selección perdida ni se afirma que
esas instantáneas prueben la recepción de todos los bytes. El orden estático real es
fotogramas, fotos del producto y recursos; edición no acepta fotogramas separados.

La regeneración desde la interfaz usa el borrador guardado y un motivo fijo de
auditoría; no dispone de entrada de texto correctivo. Este comportamiento precede
estos cambios. No se añadió un nuevo canal de comentarios.

## Corrección

Las solicitudes nuevas usan integración por defecto. Sin selección no se añade
automáticamente ningún recurso ni firma del kit. La firma requiere `False`
explícito. Plantillas con logo integrado seleccionado se rechazan antes de pagar;
el usuario puede quitarlo o elegir firma explícitamente.

Los briefs guardados y reintentos sin el campo histórico conservan `False`, incluso
si falta todo `media`. Los valores ya guardados se respetan. La versión 3 de
instrucciones restaura reemplazo del producto desde su primera aparición y en todos
los planos pertinentes, prohíbe fotos pegadas/cortes de catálogo/tarjetas finales,
y exige integración y presencia de los recursos, aun sin notas. Se conservan las
categorías asignadas, notas completas, autoridad de un logo principal y etiquetas
legítimas del producto. Permanecen los límites de 2500/1000 caracteres.

Las instantáneas v1/v2 conservan sus compiladores originales; los reintentos no
adoptan estas nuevas instrucciones ni vuelven a consultar recursos vivos. Una
generación nueva valida la selección actual: una clave eliminada o sustituida
requiere volver a elegir el recurso. No se remapean selecciones históricas.

## Verificación y límites

La combinación afectada pasó **298 pruebas**, con 2 de base de datos excluidas,
en 49,16 s. Incluye productores reales con proveedores simulados para todos los
formatos, límites, categorías, recursos múltiples, servicio de regeneración y
reanudación de tareas. El archivo nuevo pasó después **14 pruebas** en 4,70 s,
incluida la defensa adicional de briefs sin `media`. Ruff quedó limpio.

Un caso v2 cercano a 2500 caracteres reanuda el mismo `cgt-1` sin nueva creación,
aunque las instrucciones v3 excederían ese presupuesto. Otro verifica producto y
tres logos sin notas en la solicitud real construida por el productor. Estas pruebas
verifican contratos e instrucciones; no miden fidelidad visual del modelo. No hubo
una nueva evaluación visual pagada ni evidencia estadística multimarcas. La consulta
local previa a la entrega no encontró generaciones ni tareas pendientes en Nibbles.
