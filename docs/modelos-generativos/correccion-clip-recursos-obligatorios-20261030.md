# Corrección del clip y contrato de recursos obligatorios — 30 de octubre de 2026

El fallo de `fb5f21ae-7285-4c9a-bae5-a49cc10bd43f` se reproduce con datos reales mediante compilación offline. Las notas de ambos logos estaban vacías. El tema de1326 caracteres incluía contexto y JSON de replicación añadidos por la aplicación. El compilador anterior protegía todos esos datos como indicaciones del operador, dejando un mínimo2518 frente a su presupuesto interno2500. El fallo apareció después de dos llamadas Anthropic por USD0,056893; ese es gasto histórico, no de esta corrección.

## Cambio aplicado

- Presupuesto interno completo de2950 caracteres, incluidos diálogo y sufijo de video de referencia de diapositivas. La guardia local3000 del adaptador no cambia. La documentación oficial [Create video generation task](https://docs.byteplus.com/en/docs/ModelArk/create-video-generation-task-api) recomienda500 caracteres chinos o1000 palabras inglesas; no demuestra que2500/3000 sean límites duros del servicio.
- Selector versión2 y bloque de referencias7. Solo variantes de logo son alternativas; con logos elegidos queda al menos uno, normalmente uno. Se permiten varias variantes integradas si el operador lo solicita; una firma usa una. Todas las fotos, guías y elementos elegidos son obligatorios. El validador y el transporte mantienen roles de producto, guía y lugar. Un fallo de acceso a referencias ya no activa una alternativa que las descarte silenciosamente en la versión2.
- Capacidad y texto obligatorios se comprueban antes de pagar copia/selector; las variantes de logo se consideran individualmente para este diagnóstico. Una combinación imposible falla con explicación de capacidad o número de caracteres. El resultado semántico se revalida antes del proveedor visual, conservando el coste del selector si falla.
- El nuevo compilador separa texto del operador y prosa de replicación sin resumir ninguno. Solo retira el JSON redundante del reel si su URL, identificador y red coinciden con la procedencia almacenada; conserva todo ante discrepancia. La prosa y los datos originales siguen almacenados en el brief.
- Limpieza Unicode17 de secuencias con presentación emoji, modificadores, uniones, banderas y etiquetas. Conserva acentos, español, chino, números, horarios y referencias @Image/@Video; las teclas pictográficas conservan su dígito. No se elimina texto por ser noASCII.
- Firma explícita: se valida la oración completa con petición afirmativa y se rechazan negación posterior, prohibición, «evita» y preguntas. Sigue admitida cuando el selector fundamenta ausencia de superficie o la plantilla tiene ranura fija. No se inventan logos cuando no se eligieron.
- Instantáneas1–6 mantienen su selección histórica; las nuevas usan7 y decisión2. Los pasos pagados y la decisión congelada se reutilizan mediante el router/checkpoints existentes. La versión8 sigue rechazada. La ruta de texto sin imágenes no exige preflight visual.

## Comparación offline del caso real

Se ejecutó `.states/clip_error_postfix_offline.py` con snapshots locales del brief, identidad y referencias recuperados por puertas de BD autorizadas. No hubo llamadas de modelo/proveedor, lectura de R2 ni modificación de borradores. Resultado local `.states/clip-error-postfix-offline.json`:

| Categoría guardada | Compilador anterior | Nuevo |
|---|---:|---:|
| isologo |2490|2601|
| imagotipo |rechazo: mínimo2518|2629|

Ambas variantes quedan dentro2950. Para ambas se comprobaron texto del operador, prosa completa de replicación, identidad completa de marca, referencia de producto, video fuente y retirada únicamente del JSON duplicado verificado. El compilador nuevo conserva más información útil que el anterior: no reduce intención para obtener el ajuste.

La fixture de regresión anonimiza identificadores de la referencia manteniendo1326 caracteres y la estructura real del caso: `packages/api/tests/fixtures/clip_prompt_budget_real_anonymized.json`. Se conserva una variante que falla con el compilador histórico y funciona con el nuevo.

## Verificación y límites

Las pruebas deterministas cubren transporte de mascota+logos, conservación de todas las fotos, roles, peticiones de firma, incompatibilidad de plantilla, preflight sin llamada pagada, límites2949/2950/2951, diálogo y sufijo completos, Unicode, rechazo de alternativa que pierde fotos y compatibilidad de snapshots. Resultado ampliado final: **375 pruebas aprobadas en85,91segundos**. Ruff focal y formato aprobados; git diff --check sin errores. La regresión focal anterior aprobó172 pruebas en52,80segundos. No se repitieron pruebas pagadas.

Es una auditoría offline de contratos de prompts y regresiones de código, no una evaluación estadística del selector ni calidad visual de Seedance/Seedream. No se corrió pixie con un modelo real: la autorización de esta fase excluye llamadas pagadas. No hay evidencia nueva para afirmar mejor calidad de imágenes/video. El modelo visual configurado continúa siendo `dreamina-seedance-2-5-260628`. No se generaron clips nuevos, no se activaron trabajadores y no se hizo PR ni commit.

La revisión independiente local está en `.claude/clip-review-medium-20261030.md`; sus observaciones de firmas, roles y alternativa que perdía referencias quedaron cubiertas. La comprobación READ ONLY de preparación para reinicio registró0jobs activos y0borradores en generación, sin modificar filas.

