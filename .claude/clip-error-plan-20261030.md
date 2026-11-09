# Diagnóstico y plan del error de clip — 2026-10-30

Worktree activo: `C:/Users/deivi/AppData/Local/Temp/qualify-m24820842`, rama `feat/m-24820842-brand-resource-references`. Alcance: diagnóstico y plan; sin editar producto, generar medios, reiniciar, ejecutar suites o pagar proveedores. Se aplicaron creative-engineer y sus skills requeridos, graphify y durable-findings. Graphify no está disponible en PATH y el worktree carece de graph.json; el intérprete guardado corresponde a macOS. Se consultó código directamente; no se afirma revisión independiente.

## Evidencia comprobada

Borrador `fb5f21ae-7285-4c9a-bae5-a49cc10bd43f`, tenant `9cd9637c-8bd0-4293-9d68-40a71c140c00`. Log `.states/ui-placement-runtime.stderr.log:1041`: 2026-10-30 16:05:05, `invalid brand reference` por presupuesto. Líneas1042–1044: dos llamadas Anthropic ya realizadas, USD0,056893, resultado invalid_parameters; fallo anterior al proveedor visual.

Consulta mediante `tenant_session`, transacción READ ONLY: brief.topic mide1326 caracteres. La separación por marcador de replicación produce prefijo de15, marcador de21 y contexto de1290. Ambos logos candidatos tienen notas de uso vacías. No hay filas de creative_pipeline_steps para este draft: la decisión concreta del selector no está recuperable por checkpoints. No se presenta la reconstrucción como solicitud histórica exacta.

Reconstrucción offline con los datos guardados y cada variante individual, resource_plan_version1 e instruction_version6:

| Bloque | Caracteres |
|---|---:|
| Edición/estructura |170|
| Foto/identidad producto |195|
| Sustitución marcas ajenas |226|
| Identidad marca, flexible |400|
| Paleta |94|
| Operador, protegido |1339|
| Referencia imagotipo |461|
| Referencia isologo |489|

Con isologo, los seis bloques protegidos y cinco espacios suman2518: exceden MEDIA_PROMPT_BUDGET2500 incluso eliminando el bloque flexible completo. Con imagotipo suman2490 y la función cabe. El error genérico pide acortar recursos pese a que las notas miden0; el problema es el contexto interno protegido y el coste fijo del compilador. Archivos locales de medición: `.states/clip_error_measure_readonly.py`, `.states/clip-error-measurements.json`. El JSON de datos fuente es local y no debe publicarse.

## Plan ordenado

1. **Contrato primero.** En `resource_selection.py`, `ResourcePlan` y validate_plan: solo logo/logo_version son alternativas; si el usuario eligió logos debe conservarse al menos uno, normalmente exactamente el más adecuado. Todos los demás recursos y fotos seleccionados deben estar presentes en decisión y transporte físico. Prohibir pérdida silenciosa por capacidad o presupuesto; conservar las referencias de movimiento/audio y roles guía/producto.
2. **Compilar correctamente.** En `media.py` separar texto real del operador de contexto añadido por replicación desde el origen, sin depender permanentemente de un split frágil. Conservar literalmente instrucciones explícitas; convertir contexto repetido en datos estructurados y emitir una vez las reglas ya representadas. Medir bloques obligatorios y candidatos de logo antes de las llamadas pagadas. No elevar arbitrariamente2500 ni elegir logo solo porque su descripción ocupa menos. Si la combinación obligatoria no cabe tras quitar duplicación interna, dar error que identifique el bloque y acción posible, preservando selección y borrador anterior. Revalidar el resultado semántico antes del proveedor visual.
3. **Versionar y congelar.** Actualizar versión de selección/compilador/procedencia y `brand_references.py`; no reinterpretar instantáneas antiguas. En `pipeline.py`, congelar para nuevas revisiones decisión validada, roles, versión y medidas; reutilizar en reintentos sin cobrar selector de nuevo. Registrar coste incluso si falla después. Conservar firma solo por petición afirmativa comprobada o falta de superficie sustentada; ranura fija de plantilla conserva excepción existente. Plantilla incapaz de representar un extra obligatorio devuelve incompatibilidad, nunca lo elimina.
4. **Verificación propuesta, no ejecutada.** Pruebas offline con fakes: caso real con notas0 y contexto1326, cada variante, límites2499/2500/2501, seis extras, omisión de cada extra/foto, cero logos tras elegirlos, guía vs producto, firma negada/afirmativa/sin superficie, capacidad Seedance9 imágenes/3 videos/3 audios y Seedream14, fallo sin llamada pagada, procedencia/coste y replay sin duplicación. Eval futura con datos reales anonimizados, dev/test separado, baseline y clases por tipo de recurso, sin medios nuevos en esta fase; medir cobertura100% de obligatorios, al menos1 logo cuando aplica, fidelidad semántica, texto técnico no publicitario y coste por pieza. Una evaluación visual pagada posterior requiere alcance y gasto acordados y registro en docs/modelos-generativos/.

## Aceptación

El caso real compila dentro2500 preservando intención explícita y selección obligatoria, o explica una incompatibilidad real antes de gastar. Ningún elemento no-logo elegido desaparece; siempre queda un logo si se eligieron; no queda marca ajena ni firma no autorizada. Reintentos conservan decisión y coste contabilizado sin repetir pasos completados. Sin PR ni commit en esta fase.

## Aclaración del presupuesto — verificación posterior solicitada por el usuario

`MEDIA_PROMPT_BUDGET=2500` (`media.py:4685`) es un presupuesto interno compartido por imágenes y videos, no un límite comprobado del proveedor. El comentario precedente lo atribuye a una decisión del fundador del2026-10-23 y reserva margen para diálogo e instrucciones de diapositivas. El clip editado de este caso no añade diálogo en `request_for`; no corresponde justificar su rechazo específico con esa reserva.

El adaptador tiene otra guardia local: `MAX_PROMPT_CHARS=3000` (`packages/creative/src/qualify_creative/adapters/byteplus_ark.py:152`), validada por `_capped` (`:636`), `_prompt` (`:613`) y `_VideoSpec.from_params` (`:738`, nuevamente después de añadir diálogo). Los comentarios internos se contradicen sobre si3000 es límite externo o un límite conservador del adaptador: no constituyen verificación oficial del proveedor. La fuente oficial externa la consulta el hilo principal. Debe revisarse el plan para permitir aprovechar el presupuesto de transporte disponible por tipo de tarea tras verificar dicha fuente, reservando solo los sufijos realmente añadidos; mantener2500 como obligación sin ese análisis sería incorrecto.

La configuración `.env` leída sin imprimir secretos fija tanto `QUALIFY_SEEDANCE_MODEL` como `QUALIFY_SEEDANCE_REFERENCE_MODEL` en `dreamina-seedance-2-5-260628`. El runner carga ese archivo (`.states/run_ui_m24820842.py:18`), composition selecciona referencia en `composition.py:444` y el clip con referencias lo usa en `media.py:3088`. Certeza alta de la configuración actual; atribución histórica inferida. El borrador falló antes de construir/enviar la solicitud Seedance, y no existen checkpoints: no hay un modelo visual ejecutado que pueda verificarse para este intento. No se pagó ni se cambió código en esta comprobación.

### Fuente oficial y corrección del plan

El hilo principal verificó la documentación oficial: [Create video generation task](https://docs.byteplus.com/en/docs/ModelArk/create-video-generation-task-api), campo `content.text`, recomienda no superar500 caracteres chinos o1000 palabras inglesas; no confirma un límite duro de2500 ni3000 caracteres. Por ello,3000 se describe exclusivamente como guardia del adaptador actual, y2500 como política interna anterior.

**Corrección de los pasos2 y aceptación anteriores:** presupuestar la solicitud completa después de todos los anexos y usar la capacidad permitida por la guardia local actual de3000 para un clip editado sin diálogo. Reservar solo los anexos reales de cada ruta. La reserva histórica genérica de500 no aplica automáticamente a este caso. Mantener la separación contexto/operador y quitar duplicación; el criterio es que la solicitud final íntegra quepa en su presupuesto efectivo y en la guardia del adaptador, sin perder recursos obligatorios. El mínimo medido2518 por sí solo ya no constituye incompatibilidad bajo3000; el bloque flexible de400 puede ajustarse dentro del presupuesto completo. Esta es una propuesta, no un cambio aplicado ni una prueba contra el servicio. No se afirma que BytePlus acepte cualquier texto de3000 caracteres por su contrato externo.

## Implementación concluida y verificada

Se implementó selector2/bloque7, presupuesto interno completo2950 con50 de margen respecto a guardlocal3000, limpieza precisa de emojis Unicode17, separación operador/contexto sin resumir prosa, eliminación de JSON redundante solo si su procedencia coincide, obligatoriedad de todos los no-logo/fotos/guías, mínimo1logo elegido y alternativa multilogos por petición. Firma requiere oración afirmativa o ausencia de superficie fundamentada. Instantáneas antiguas conservan sus políticas. La alternativa de clip que descartaba referencias queda prohibida en versión2. Las incompatibilidades previsibles fallan antes de pagar.

Verificación final:375 pruebas aprobadas85,91s; Ruff focal/formato y git diff --check limpios. Auditoría offline real: isologo2490→2601; imagotipoerror2518→2629, ambas<=2950 con operador/prosa/identidad/referencias conservadas. No hubo llamadas nuevas a modelos, generación de medios ni trabajadores. Revisión independiente: `.claude/clip-review-medium-20261030.md`. Conteos READONLY de preparación para reinicio:0jobs activos globales,0borradores generándose. El hilo UI coordina reinicio autorizado del runner existente.

Informe final: `docs/modelos-generativos/correccion-clip-recursos-obligatorios-20261030.md`. Evidencia local reproducible: `.states/clip_error_postfix_offline.py` y `.states/clip-error-postfix-offline.json`. No se evaluó calidad visual ni comportamiento del selector con llamadas nuevas; pruebas deterministas no equivalen a calidad semántica medida. No PR ni commit.
