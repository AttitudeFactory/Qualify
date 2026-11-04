# Auditoría m-24820842 — selección y referencias (2026-10-30)

## Confirmado

- `brand/render.py::_chosen_resources` ordenaba usar cada recurso y describía cada logo secundario como integrado. La selección era una obligación visual antes de llegar al generador.
- Compilador v3 ordenaba `Show every chosen resource`; v4 asignaba a todos `integrate naturally`. No existía una instrucción para elegir candidatos pertinentes.
- `_budgeted` podía recortar las instrucciones originales del operador para dejar intacta la plantilla de marca. Auditoría independiente encontró instrucciones finales perdidas; el caso manual real tiene 1319 caracteres.
- Los archivos seleccionados sí se encaminan al proveedor; no se ha demostrado que el proveedor visual atienda todos. El kit real tiene cero `reference_image_keys`: su canal histórico que sólo muestra el conteo no explica este caso.

## Cambio local V5

Los recursos seleccionados son candidatos: considerar todos, usar sólo los necesarios, incluso ninguno salvo pedidos explícitos y notas de uso. Las variantes de logo son alternativas; no se deben inventar planos ni objetos para mostrarlas todas. Se conservan todos los bytes, índices, notas, categorías y huellas. No se podan imágenes ni se alteran límites del proveedor.

La edición de video preserva estructura/acciones/manos/objetos de la fuente por defecto; sólo instrucciones del operador pueden pedir cambios. Las fotos del producto definen apariencia y etiquetas, no fondo o accesorios. Se conserva separación de roles, composición interna de los logos y prohibición de añadir logos a comida/piel.

Las instrucciones originales de edición y las escenas/temas del operador en V5 son protegidas del recorte silencioso. Si no caben tras eliminar contexto flexible, falla antes de pagar. Se compactó texto fijo redundante para recuperar espacio.

Animación conserva los recursos presentes en el fotograma compuesto, sin reintroducir candidatos omitidos. Esto mantiene el presupuesto de 1000 caracteres de OmniHuman sin convertir las alternativas en obligaciones.

Resolver nuevo congela versión5. Reintentos de la MISMA revisión conservan1–4; nueva generación/regeneración con nueva revisión vuelve a resolver5. Se mantienen historial y reanudación sin pagos duplicados.

## Verificación

En curso: pruebas offline de productores reales con proveedores simulados, taxonomía, congelación/reanudación, regeneración, copia y presupuestos. No son evaluación visual de calidad. No llamadas pagadas, PR, commit ni reinicio del servidor.

## Resultado offline

222 pruebas aprobadas en 18,00 s, sin fallos: `test_selective_brand_resources`, `test_brand_references`, `test_multi_brand_resources`, `test_brand_reference_matrix`, `test_creative_reel_edit`, `test_default_integrated_logo` y `packages/creative/tests/test_render_prompt.py`. Se actualizaron expectativas antiguas que exigían aparición de todos los recursos y nombres de archivos visibles; se preservan pruebas de índices, bytes, notas, categorías, propiedad, límites, fallo antes de pagar y congelación de versiones1–4. Ruff y formato de ocho archivos limpios; `git diff --check` limpio.

Auditoría independiente con el brief manual real de 1319 caracteres: preflight productivo V5 y prompt final de 2491 caracteres, instrucciones completas y los dos candidatos de escena intactos (el principal de esa selección histórica es una firma, no una tercera referencia de escena). Prueba adicional de estrés con tres candidatos: 2500 caracteres exactos, conserva los 1319 del operador. Caso1342 caracteres con tres candidatos no cabe y rechaza explícitamente antes de pagar. Evidencia: `.states/prompt-quality-v5-offline-evidence-2026-10-30.json`, auditoría/preflight independiente. Las instrucciones de marca y notas no se recortan.

Los errores de la primera corrida no se publican como resultado final ni se atribuyen sin evidencia a una ejecución anterior: treinta expectativas y presupuestos fallaron durante desarrollo; el presupuesto de animación fue corregido y las expectativas se ajustaron al comportamiento V5. Resultado final cero fallos.

Sin prueba visual pagada: estos resultados prueban transporte, selección expresada y conservación de indicaciones; no garantizan que Seedance/Seedream respeten todo visualmente. Los resultados existentes permanecen sin cambios. Root coordina reinicio del proceso de interfaz de producción para que las nuevas generaciones usen V5.


## Alcance de esta revisi?n

Cuatro archivos de producci?n modificados por esta revisi?n: `packages/api/src/qualify_api/creative/brand_references.py` (V5 candidatos), `media.py` (edici?n V5, prioridad de indicaciones y continuidad de animaci?n), `pipeline.py` (admisi?n de instant?neas1?5) y `packages/creative/src/qualify_creative/brand/render.py` (candidatos en instrucciones de copia). Se conservaron los cambios V4 y dem?s modificaciones que ya exist?an al iniciar.

Pruebas propias: archivo nuevo `packages/api/tests/test_selective_brand_resources.py`; expectativas actualizadas en `test_brand_references.py`, `test_brand_reference_matrix.py` y `test_default_integrated_logo.py`. No se modificaron interfaz, esquema, proveedor, modelos, precios ni l?mites. No se crea ni actualiza PR.
