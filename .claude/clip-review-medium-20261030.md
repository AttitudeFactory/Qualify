# Revisión independiente del clip — 2026-10-30

Worktree: C:/Users/deivi/AppData/Local/Temp/qualify-m24820842. Rol: data-scientist-fde. Solo lectura del producto y probes offline; no proveedores, generación, DB, PR ni reinicios.

## Criterios fijados antes de revisar

- Solo variantes logo alternativas podables; al menos una cuando elegidas. Todo recurso no-logo elegido obligatorio, incluidos producto, guía, video y audio.
- Normalización conserva acentos, chino, @Image1/@Video1 y tiempos; no elimina Unicode indiscriminadamente.
- Solicitud final completa <= presupuesto efectivo (pendiente 2950 o 2550), con anexos/diálogo incluidos; guardia adaptador 3000 intacta.
- Error útil antes de gasto en incompatibilidad determinista, sin truncar instrucciones o descartar obligatorios.
- Firma requiere evidencia afirmativa o ausencia de superficie apropiada; selección/revisiones/snapshot/replay y costes coherentes.
- Separar propiedades deterministas de calidad semántica/visual: esta revisión no mide calidad nueva del modelo.

## Estado

Lectura causa/contrato completada. Esperando diff de autores. Graphify CLI no disponible y worktree sin grafo utilizable según diagnóstico previo; revisión directa de fuentes. No se ejecutó Pixie ni evaluación LLM: alcance explícito prohíbe llamadas pagadas.

## Baseline y alcance de comparación

El diagnóstico guardado registra dos reconstrucciones del mismo brief real de 1326 caracteres y notas logo vacías: mínimos protegidos 2490 y 2518; esta última falló frente a 2500. No hay checkpoint del intento fallido; no equivalen a la solicitud histórica exacta. Se compararán compilaciones offline, sin afirmar fidelidad visual ni calidad semántica medida. Presupuesto confirmado por el hilo principal: 2950 caracteres TOTALES, incluidos anexos; reserva de 50 frente a guardia 3000.

## Hallazgo R1 — autorización de firma (pendiente del autor)

Probe independiente `.states/clip_review_probes.py`, ejecutado con `uv run --no-sync --project C:/Users/deivi/OneDrive/Escritorio/work/Qualify python .states/clip_review_probes.py`. El validador explicit acepta «Evita usar el logo como firma», «Logo como firma: prohibido», «Usa el logo como firma nunca» y una pregunta «¿logo como firma?», citando solo «como firma». Esto no prueba una petición afirmativa. Regex revisa únicamente 80 caracteres previos y finaliza en la cita; falta negación posterior y vocabulario español adicional. Comunicado al autor para corrección antes del veredicto.

Normalización independiente: «cámara acción 中文 @Image1 @Video1 @Audio1 00:01–00:03 1.5s © →» permanece íntegro; secuencias 🍔😍👉🔥👨🏽‍🍳🇻🇪1️⃣#️⃣*️⃣❤️ se convierten en «1#*» (bases de keycaps preservadas). Verificación determinista; no es una medición semántica.

Limitación resuelta: `.venv` del worktree no contiene pydantic. Se reutilizó el entorno existente OneDrive mediante uv sin sync; fuentes importadas explícitamente desde el worktree. No se instalaron paquetes ni alteró entorno compartido.

## Comparación independiente con datos reales, sin generación

Autorización posterior explícita del hilo principal para tenant_session READ ONLY. Snapshot local `.states/clip-review-real-input-local.json` (no publicar): BrandKit actual con identidad de 382 caracteres y dos recursos con notas vacías. Sin lecturas R2, sin modificación DB. Compilador baseline congelado antes de edición en `%TEMP%/qualify-clip-review-medium-baseline`; probe `.states/clip_review_compare.py` importa ambos compiladores y los bloques correspondientes.

- Variante de categoría isologo: baseline 2490 caracteres; actual 2601.
- Variante de categoría imagotipo (archivo llamado isologo.png): baseline falla frente a 2500, mínimo protegido previo 2518; actual 2629.
- Ambos actuales <=2950; conserva operador, prosa íntegra de contexto replicación y la identidad completa de marca; @Image1 y @Video1 siguen presentes. Solo se elimina JSON del reel cuando URL/id/plataforma coinciden con source_reel y emojis; no se recorta prosa del operador/contexto. No se eliminan recursos del caso (un producto, un video y una de las alternativas logo).

Resultados en `.states/clip-review-compare-results.json`; prompts íntegros locales en `.states/clip-review-{old,new}-{isologo,imagotipo}-prompt-local.txt`. No constituyen la solicitud histórica exacta: el intento original carece de checkpoint. No miden fidelidad visual ni efectividad del prompt nuevo.

## Veredicto final independiente — sin bloqueantes en el alcance revisado

R1 corregido: afirmativa «Usa el logo como firma» aceptada; negativas previas/posteriores, «Evita», «prohibido» y pregunta rechazadas al repetir el mismo probe. Revisión concluida sobre la primera pasada estable del autor, antes de sus pruebas adicionales/formato. No se repitió su suite ni se reclama su resultado como propio.

Probes independientes (`clip_review_probes.py`, ejecución exitosa):

- Presupuesto fijo protegido 2949 y 2950 aceptado, 2951 rechazado.
- Solicitud real del adaptador `_VideoSpec.from_params`, movimiento más diálogo: 2950. Guardia MAX_PROMPT_CHARS sigue en 3000 y archivo adaptador sin diff.
- Movimiento de diapositiva más sufijo de referencia: 2950; 2951 rechazado.
- Plan válido con mascota/logo/foto aceptado; omitir mascota, todos los logos o foto rechazado.
- Guía/style, producto y lugar mantienen instrucciones diferenciadas en prompt; sin logo elegido se prohíbe inventarlo.
- Preflight con caso real aceptado; recurso de 4000 caracteres rechazado con medida 6209 vs2950 y mensaje accionable; treinta fotos rechazadas por capacidad. Probes llaman solo funciones locales sin router/proveedor.

Fuentes verificadas: `resource_selection.py:139` valida obligatoriedad y firma; `media.py:2225` preflight candidatos antes de copy/selector, `:3251` bloquea fallback que descartaría referencias con planv2, `:4744` total2950, `:4803` presupuesto protegido, `:4862` diálogo, `:5098` sufijo, `:5465` roles y separación; `prompt_text.py:265/278` Unicode/replicación. `Qualify/content_generator.py:2363` comunica que todos los elementos elegidos se incluyen y logos son variantes alternativas.

Replay/coste revisados por lectura: `pipeline.py:321` admite block7 conservando versiones anteriores; `:581` congela elección por revisión sin saltar el ordinal del router; `_select_resources` conserva versión y rechaza mezcla, añade coste antes de validar resultado y guarda modelo/revisión/coste/presupuesto. Router recupera resultado ya guardado antes de llamar proveedor. No se ejecutó replay contra DB ni se probó recuperación ante interrupción real.

Límites: calidad semántica y visual nueva no medida; «no_surface» depende de evidencia visual del selector y no se demuestra mediante estos probes deterministas. Cero llamadas nuevas pagadas, cero generación de medios, sin cambios producto/tests autor, sin PR/restart. Snapshot local privado no debe publicarse. DB solo lectura autorizada posterior, sin mutaciones.

## Adenda — revisión breve del delta de cierre

Sin nuevos bloqueantes. Se inspeccionaron `fix_clip_regressions.py`, los cambios de pruebas afectados y las funciones de contrato, sin repetir suites. El delta funcional reportado en `_budgeted` conserva rechazo, cifras y acción; únicamente restituye «demasiado largas» para compatibilidad del mensaje. División de literales del sistema antiguo verificada con AST contra baseline congelado: igualdad exacta, 1612 caracteres; no cambia su contenido ni huella.

Los tres casos de `test_creative_clip.py` que añaden `brand_logo_in_scene=False` prueban explícitamente la superposición histórica; no convierten la selección semántica actual en firma ni eliminan las pruebas de autorización. El cambio de versión futura rechazada a8 conserva cobertura1–7 válidas, sin consultar BrandKit actual en replay. Los ajustes del límite usan MEDIA_PROMPT_BUDGET actual y todavía exigen rechazo estricto al añadir el sufijo. La aserción de operador sin espacio final concuerda con `_quoted.strip()` y conserva el contenido.

No se ocultó la obligatoriedad nueva: permanecen pruebas específicas de omitir extra/todos los logos/foto, recursos incompatibles en plantilla y fallback sin referencias que no debe descartar foto obligatoria. La nueva prueba v2 exige un solo intento al proveedor y fallo, impidiendo un segundo intento sin la foto.

No se verifican aquí resultados finales de suite: los ejecuta y comunica el autor. Veredicto independiente permanece sin bloqueantes; límites anteriores vigentes (calidad visual no medida, cero llamadas pagadas nuevas).
