# Auditoría de selección semántica — 30 de octubre de 2026

Se corrigió el checkout que sirve los enlaces del usuario: `C:/Users/deivi/AppData/Local/Temp/qualify-m24820842`. El proceso local apuntaba a ese árbol, no al checkout de OneDrive. Se conservó el diff anterior en `.claude/audit-resource-selection-baseline-20261030.diff`; no se descartaron cambios previos.

## Evidencia de los dos borradores

Los borradores `aa566522-3ed6-4c02-992a-b54c10ae0478` y `011156be-4e23-4127-882b-ad539f3d72a4` guardaban compilador v4, una firma y dos variantes adicionales de logo, sin petición textual de firma. La imagen mezclaba stock como guía de composición y foto real del catálogo bajo el mismo rol de producto. El resultado contenía tres marcas y convertía «guantes negros» en titular. La referencia de video sí estaba guardada y el resultado seguía parte de ella, pero conservaba marcas de Chubbies en sus envases. No se conserva el prompt original de esas generaciones, por lo que no se atribuye un cuerpo de solicitud histórico que no puede recuperarse.

El V5 previo solo pedía elegir en las instrucciones: seguía enviando todos los recursos al generador. Eso no satisfacía la poda física pedida.

## Corrección local

Una etapa de selección con visión usa el adaptador de Anthropic, el router, las credenciales y la guarda de presupuesto existentes. Examina versiones reducidas a 768 píxeles de las fotos, recursos y fotograma fuente disponibles. Devuelve índices estructurados de los recursos y fotos necesarios, roles de guía/producto, ubicación del logo y explicación. El generador visual recibe exclusivamente el subconjunto elegido, con índices recompuestos. Las variantes de logo son alternativas y los elementos adicionales pueden omitirse todos.

Las firmas requieren una petición textual positiva comprobable, una escena sin superficie adecuada explicada por el selector o la ranura fija de una plantilla. Los booleanos antiguos no autorizan por sí solos una firma nueva. El selector no elimina las referencias de video de movimiento o edición. Los roles de lugar/estilo que ya tenía un clip se conservan.

La decisión validada se congela en el paso -3 por revisión; el paso -2 conserva las imágenes originales disponibles. Los reintentos vuelven a pasar por el mismo ordinal del router con su resultado guardado, sin saltar pasos pagados. Las instantáneas v1–v5 conservan sus instrucciones anteriores. Los resultados nuevos usan bloque6: solo los recursos ya elegidos son instrucciones de integración. La decisión, modelo, versión, explicación y costo quedan en procedencia incluso si se eligen cero recursos. Se guardan además los prompts de imagen/clip nuevos en sus parámetros.

Los índices desconocidos, referencias inválidas o una selección que elimina toda identidad real del producto fallan antes del proveedor visual; nunca se reabren todos los candidatos como alternativa. Se registra el costo del selector aunque una comprobación posterior falle. El conteo y la generación de Anthropic reciben las mismas imágenes; los tokens de entrada, salida y caché se convierten en eventos de uso. Se separaron las indicaciones visuales del texto publicitario para todos los tipos de pieza.

## Evaluación real acotada

Se ejecutó únicamente el selector sobre los dos briefs y sus medios reales, sin generar imágenes o videos, modificar borradores, publicar ni activar trabajadores. Los archivos `uploads/...` se recuperaron por la puerta local correcta (`uploaded_files/` más la clave completa); un fallo al buscarlos en R2 no demostraba que faltaran.

| Caso | Recursos disponibles antes | Recursos elegidos | Firma | Resultado de selección | Costo USD |
|---|---:|---:|---|---|---:|
| Réplica aa566522 | 3 | 1 | No | Imagotipo integrado en envases y superficies existentes; conserva producto y secuencia | 0,028647 |
| Imagen 011156be | 3 | 1 | No | Imagotipo integrado; stock como composición y catálogo como identidad del producto | 0,0295294 |

Modelo: `claude-opus-5-5`; revisión informada igual; selector versión1. Total **0,0581764 USD**. El primer caso registró 4348 tokens de entrada y 271 de salida; el segundo 3899 y 685. El costo incluye la contabilización de caché del proveedor. Este gasto adicional es por selección y varía con las imágenes, instrucciones y caché; no cambia precios de proveedores ni introduce un modelo nuevo.

La explicación del caso de imagen identifica las manos con guantes negros, ingredientes separados flotando y efecto luminoso como composición, sin convertirlos en beneficio comercial. La del clip identifica vaso, envase de papas y papel de bandeja como superficies existentes para sustituir la marca ajena. Evidencia reproducible local: `.states/eval_semantic_selection_20261030.py` y `.states/eval-semantic-selection-20261030.json`.

## Verificación y límites

La suite focal ampliada aprobó **304 pruebas en 44,44 s**: productores, router, selección física, copias, referencias múltiples, límites, plantillas, congelación, reanudación y adaptador Anthropic. Las últimas defensas de roles y firmas aprobaron **27 pruebas en 5,56 s**. Se corrigieron dos expectativas antiguas incompatibles con el contrato nuevo: rechazar candidatas de plantilla antes del selector y tratar la versión6 como futura desconocida; la versión7 sigue siendo rechazada.

Las pruebas con proveedores simulados comprueban el transporte físico, las guardas y la procedencia. La evaluación viva comprueba la decisión semántica sobre los dos casos. No son una medición estadística ni una nueva evaluación visual de Seedream/Seedance: no se generaron medios nuevos y los dos resultados originales permanecen intactos. No se creó PR ni commit.

Verificación final de la instrucción del bloque6: **70 pruebas aprobadas en 9,47 s** (selector y matriz). Ruff aprobó los doce archivos revisados, su formato y `git diff --check`; no se repitieron las suites verdes sin cambios nuevos.
