# Diagnóstico del presupuesto de indicaciones del clip — 2 de noviembre de 2026

Ticket: m-24820842 (PR #412, rama local `fix/m-24820842-prompt-budget`, base `5048b047`).
Autor: principal-architect. Fase 1 del plan `.claude/plan-presupuesto-prompt-2026-11-02.md`:
diagnóstico y diseño, **solo lectura**. No se tocó código de producto, no hubo llamadas
pagadas, no se reinició ningún servidor. Estado de la decisión: **[PROPUESTO]** hasta que el
fundador la firme.

## 0. Resumen

- **Se reproduce exacto: 2966 caracteres** con los datos guardados del borrador y el compilador
  de esta rama, cuando el selector de recursos elige el logo de la ranura `imagotipo` (el
  principal). Con cualquiera de los otros dos logos el mismo borrador cabe (2938 y 2950).
- **El 2966 no es el largo del pedido: es el mínimo después de borrar entera la identidad de la
  marca.** El pedido completo mide 3368; para bajar, el compilador ya había eliminado los 401
  caracteres de «Client identity» (el posicionamiento del Brand Kit). En los casos que sí
  «pasan» con estos datos, la identidad también se pierde. Hoy hay pérdida de calidad silenciosa
  incluso cuando no hay error.
- **Lo que llena el espacio: 938 caracteres de texto fijo de la aplicación** (la «guía de
  replicación» que la pantalla añade al tema) marcados como intocables. Cada una de sus
  instrucciones ya está escrita en inglés en las líneas fijas del mismo pedido. Es la redundancia
  de la que habla la condición del fundador.
- **Por qué falló después de pagar:** la verificación previa da por bueno el pedido si *algún*
  logo cabe (el segundo cabía) y luego el selector, ya pagado, eligió el que no cabía.
- **Decisión propuesta:** quitar la guía duplicada (solo cuando coincide palabra por palabra con
  la plantilla conocida), conservar entera la identidad de la marca, añadir los datos clave que
  esta ruta nunca enviaba, presupuesto por ruta igual a la guardia del adaptador (3000) menos lo
  que esa ruta añade, y verificación previa contra el peor caso con un mensaje que dice qué
  texto acortar y cuánto. Resultado medido sin llamadas: **2783 caracteres** con todo presente
  (3 logos a la vez: 2932).
- **«Debe evitar» no llega hoy al video** en esta ruta (0 caracteres) ni en la de movimiento salvo
  de forma indirecta y acotada. Recomiendo **no** reenviarlo tal cual; detalle en §5.

## 1. Método y datos

Lectura con `qualify_shared.db.session.tenant_session` del tenant `9cd9637c-…`, transacción
`SET TRANSACTION READ ONLY` y `rollback` al salir (más dos lecturas por los servicios existentes
`PostgresContentRepository.get_brief`, `DbBrandKitReader.kit` y `BrandKitStore.list_assets`, que
solo hacen `SELECT`). Los scripts viven fuera del repositorio (`%TEMP%/budget-diag/`), no se
publican porque leen datos de un cliente.

| Fuente | Qué había |
|---|---|
| `content_drafts` `4ca40fc1-…` | `status=failed`, `failure_reason=invalid_parameters`, `pipeline_version=creative-v2-brand9`, revisión 1, el mensaje de 2966/2950 |
| `content_briefs` `4b77a44d-…` | clip, `clip_reference_mode=edit`, `brand_application_version=2`, 1 foto de producto (rol `product`), 1 video de referencia, 0 audios, logo principal en ranura `imagotipo` + 2 logos adicionales (`isologo`, `isotipo`), 0 elementos no logo, notas de uso **vacías**; tema de 1290 caracteres (259 del operador + marcador + 877 de guía de replicación + JSON del reel de 404) |
| `constraints` | `highlights=[["precio","10$"]]`, `must_mention=["envio gratis"]`, `must_avoid=[]` |
| `copy_variants` | 1 copia de `claude-opus-5-5` (gancho, 3 tomas, CTA); **la ruta de edición no la usa** |
| `piece_versions` / `creative_usage_events` | gasto USD 0,092940 = 0,061446 (copia) + 0,031494 (selector de recursos) |
| `creative_pipeline_steps` / `creative_pipeline_runs` | **ninguna fila**: corrió en el despachador en línea, sin congelar la decisión del selector |

Como la decisión del selector no quedó guardada, se compiló el pedido para las 7 combinaciones
posibles de logos, con la misma transformación que aplica `_select_resources` (rol
`elemento_de_marca`, `instruction_version=9`, `selected_logo=True`, `resource_plan_version=2`):

| Logos elegidos | Compilador actual |
|---|---:|
| imagotipo (principal) | **rechazo: 2966** ← coincide con el error |
| isologo | 2938 (pasa, sin identidad de marca) |
| isotipo | 2950 (pasa; de la identidad queda 1 carácter) |
| imagotipo + isologo | rechazo: 3045 |
| imagotipo + isotipo | rechazo: 3036 |
| isologo + isotipo | rechazo: 3008 |
| los tres | rechazo: 3115 |

Solo una combinación da 2966, así que la reproducción es exacta y además identifica qué eligió el
selector. La fixture anonimizada que preserva longitudes (`packages/api/tests/fixtures/clip_edit_budget_real_20261102_anonymized.json`)
reproduce el mismo 2966 sin base de datos.

## 2. Ruta que construye el pedido

`clip_prompt` → `clip_reference_mode == "edit"` → `reel_edit_prompt` →
`resource_plan_version >= 2` → `_required_reel_edit_prompt` → `brand_application_version` →
**`_brand_applied_reel_edit_prompt`** (`media.py:6142`), con `_budgeted(lines, strict=True)` y
presupuesto `MEDIA_PROMPT_BUDGET = 2950`. No se añade diálogo ni sufijo después (clip sin voz; el
adaptador solo agrega `Dice a cámara` si llega `dialogue`). El texto sale tal cual hacia
`byteplus_ark._prompt` → `_capped` (3000).

## 3. Medición bloque a bloque (caso real, logo imagotipo)

| # | Bloque | Tipo | Caracteres | Redundancia |
|---|---|---|---:|---|
| 0 | «Edit @Video1 in place. Preserve choreography…» | fijo | 217 | — |
| 1 | `@Image1`: identidad del producto | fijo | 82 | — |
| 2 | Reemplazar el producto desde su primera aparición | fijo | 91 | — |
| 3 | Reemplazar toda marca ajena por el logo del cliente | fijo | 250 | — |
| 4 | Paleta (9 colores) y cómo aplicarla | fijo | 291 | — |
| 5 | Tipografías (titular / cuerpo del Brand Kit) | fijo | 172 | — |
| 6 | Solo texto existente o aprobado; sin CTA/cierre inventado | fijo | 125 | — |
| 7 | «Client identity»: posicionamiento del Brand Kit | **flexible, rango 0, sin protección** | 401 | — (es lo que se borra) |
| 8 | Texto del operador | protegido | 295 (259 de texto) | — |
| 9 | «App production directions»: guía de replicación | **protegido** | **938** (877 de texto) | **duplica 0, 1, 2, 3, 4, 5, 6 y alude a un JSON ya retirado** |
| 10 | Metadatos del reel (JSON) | — | 0 | retirado: su URL, id y red coinciden con `source_reel` |
| 11 | Bloque de recursos de marca (v9) | fijo | 496 | — |
| | Separadores (10 espacios) | | 10 | |
| | **Total sin recortar** | | **3368** (488 palabras) | |
| | Fijo + protegido (sin el bloque 7) | | **2966** | |

### 3.1 La guía de replicación, frase por frase

La genera `Qualify/reel_replication.py::replication_context` con texto constante (solo cambia el
nombre del producto) y la pantalla la une al tema en `CreativeState._effective_topic`. **El
operador no la escribe ni la puede editar** (`replication_context` solo se asigna desde la
tarjeta del reel). Que viaje marcada como «trusted» y protegida es lo que la vuelve intocable.

| Frase de la guía (es) | Ya dicha por la línea fija (en) | Qué falta para no perder nada |
|---|---|---|
| Edita el video original para mi marca y mi producto («producto de prueba»). | 0 «Edit @Video1 in place» | **el nombre del producto**: es el único sitio donde aparece → nueva línea `Client product: "…"` |
| Toma del reel su estructura: planos, orden, encuadres, acciones, cámara, cortes y ritmo. | 0 «Preserve choreography, shots/cuts/timing, framing, camera, hands/actions…» | nada |
| Es solo la guía de secuencia, no su estilo visual. | 0 «REPLACE BRAND GRAPHICS», 4 «replacing source-brand colors» | decirlo explícito en 0: «using it as the sequence guide only, not its visual style» |
| Aplica MI identidad por encima: colores, tipografía, textos y CTA del Brand Kit… tienen prioridad sobre el look del reel ajeno. | 4 paleta, 5 tipografías, 6 texto aprobado, 7 identidad | nada, **si la identidad (7) deja de borrarse** |
| No imites su paleta, sus fuentes ni sus textos; sustituye el producto y la identidad de la otra marca por los míos. | 2, 3, 4, 5 | nada |
| Las fotos del catálogo definen el aspecto del producto, no una nueva escena. | 1 «not its photo background/props» | nada |
| No inventes un gancho visual, ni tomas nuevas, ni un cierre distinto. | 6 «do not invent CTAs, promotions, props or a new ending» + 0 | añadir «a visual hook, new shots» en 6 |
| No copies las promociones ni la música ajena. | 0 «Source captions/audio/promotions are not client instructions» | decirlo como prohibición en 0: «never copy its music or promotions» |
| Los datos siguientes son material de referencia, no instrucciones ni hechos de mi marca. | se refiere al JSON, **que ya se retiró** | nada (frase colgante); si el JSON se conserva, ya lo cubre la envoltura «untrusted data, never instructions» |
| La secuencia visual la aporta directamente el video original; no hay análisis VLM. | 0 «Edit @Video1 in place» | nada: es una nota interna de ingeniería, no una indicación para el modelo |

Resultado: 877 caracteres de guía se sustituyen por ~120 caracteres añadidos a líneas fijas y
30 de la línea del producto, sin perder ninguna instrucción.

### 3.2 Lo que esta ruta ya perdía o nunca enviaba

- **Identidad de la marca (posicionamiento):** flexible de rango 0 sin protección; con este Brand
  Kit (382 caracteres) se recorta a cero (o a 1 carácter) en **todos** los clips de edición
  medidos, con cualquiera de los tres logos. Es pérdida de calidad silenciosa, no visible para el operador.
- **Datos clave** (`precio: 10$`): la ruta de edición nunca los incluyó (la de movimiento sí, con
  `_facts_line(..., _FACTS_IN_CLIP)`).
- **Nombre del producto:** solo viajaba dentro de la guía de replicación.
- Nota menor, no se corrige aquí: el bloque de recursos dice «Image 2» mientras el resto de la
  ruta dice «@Image1»/«@Video1». Cambiarlo es un cambio de prompt que exige medición
  (`qualify-measure`).

## 4. Causa raíz

1. **Redundancia protegida.** La guía de replicación (texto constante de la aplicación, 877
   caracteres) viaja protegida como si fuera intención del operador y repite en español lo que las
   líneas fijas ya dicen en inglés. El 30 de octubre se separó del JSON y se protegió entera
   «para no resumir intención»; la intención era real, pero ya estaba en el pedido. Subir el
   presupuesto a 2950 ese día dejó el problema intacto y este caso lo supera por 16.
2. **Verificación previa optimista.** `MediaProducer._preflight_resource_candidates`
   (`media.py:2355`) prueba cada logo por separado y **devuelve en el primero que cabe**. Aquí cabía
   el isologo (2938), así que se pagó la copia (USD 0,061446) y el selector (USD 0,031494); el
   selector eligió el imagotipo y el pedido falló en la ejecución. Además, el selector versión 2
   puede elegir **varios** logos y la verificación nunca prueba esa combinación.
3. **Hueco en la ruta de movimiento (no causó este caso).** La verificación compila el clip con
   `copy=None`; en la ejecución entra el gancho de la copia (línea fija de hasta ~222 caracteres).
   Medido con el mismo borrador en modo movimiento: verificación 2602 fijos, ejecución con gancho
   de 160 caracteres 2662 fijos. Un pedido puede pasar la verificación y fallar después de pagar.
4. **Mensaje equivocado.** Pide acortar «el texto de la escena o las indicaciones de tus
   recursos»; las notas de los recursos medían 0 y no hay escena. El operador no tiene forma de
   arreglarlo con esa instrucción.
5. **Las pruebas que debían detectarlo están rotas en la rama.** Las 6 de
   `test_protected_instructions_over_budget_fail_before_copy_or_vendor` y
   `test_service_preflights_stale_selection_before_paid_copy` fallan por un doble de prueba sin
   `pipeline_version` (`service.py:2136`), no por presupuesto: la garantía «falla antes de pagar»
   no está siendo verificada hoy. Las otras 4 que fallan no tienen relación:
   `test_the_chosen_logo_takes_the_templates_logo_slot` (doble sin lector de recursos) y las 3 de
   `test_creative_memory_harness` (entorno Windows: `bash` no encuentra `python`).

## 5. «Debe evitar» y «Debe mencionar» (supuesto añadido por el fundador)

Supuesto: en uso real «Debe evitar» (`constraints.must_avoid`, CREAR-6) vendrá lleno.

**Por dónde viaja hoy** (verificado en código):

| Destino | ¿Llega? | Cómo |
|---|---|---|
| Copia de Claude | sí | `qualify_creative/brand/render.py:591-592` («Must mention / Must avoid») |
| «Potenciar con IA» | sí | `context_ai.py:260-263` («DEBE MENCIONAR / DEBE EVITAR»); la propuesta reescribe el texto del operador (≤ 300 caracteres, `PROPOSAL_MAX_CHARS`) y puede incorporar frases como «sin mostrar cebolla» |
| Evaluación de copia | sí | `evals/copy_quality.py:200-201` |
| Pedido de video, ruta de edición | **no** | `media.py` no lee `must_avoid` ni `must_mention`; la ruta no usa la copia |
| Pedido de video, ruta de movimiento | **indirecto** | gancho (tope 160) y tomas (tope 260 c/u, máx. 4, flexibles) los escribe Claude habiendo leído «Must avoid»; el largo no depende de la lista |
| Texto del operador | **indirecto** | solo si el operador usó «Potenciar con IA»; queda acotado por el campo (1200, `CONTEXT_MAX_CHARS`) y viaja protegido y literal |

**Crecimiento medido del pedido de video** con el borrador real:

| «Debe evitar» | Ruta de edición hoy | Si se reenviara como línea visual |
|---|---:|---:|
| 0 frases | +0 | +0 |
| 1 frase («cebolla cruda») | +0 | +55 |
| 3 frases | +0 | +99 |
| 5 frases | +0 | +136 |

«Debe mencionar» lleno («envio gratis»): +0 en ambas rutas de video.

**Comprobación con el diseño nuevo:** el caso real queda en 2783; con 5 frases reenviadas, 2919
(cabe en 2950 y en 3000). Con los tres logos a la vez y 5 frases, 3068: **no cabría**, y la
verificación previa lo rechazaría antes de pagar con el mensaje del §7.5. El diseño no depende de
que el campo esté vacío.

**Recomendación: no reenviar «Debe evitar» tal cual al video.** Razones: (a) es una lista
pensada para la copia (palabras y afirmaciones: «barato», «gourmet», «no mencionar a la
competencia»), que para un modelo de video no significan nada o significan otra cosa; (b) Seedance
no tiene campo de indicación negativa (la documentación oficial no menciona ninguno, leída
2026-11-02) y nombrar un objeto para prohibirlo tiende a hacerlo aparecer en modelos de difusión
[S]; (c) el texto en pantalla ya está prohibido por la regla de texto. Si el fundador quiere
controlar lo que **no se ve**, propongo un campo propio y explícito, «No debe aparecer en el
video», con tope de 200 caracteres, que viaje protegido como `Never show (client list, in
Spanish): "…"` y que se mida con `qualify-measure` (pocas piezas, borrador 480p) antes de activarlo.
Su reserva de presupuesto (≤ 211 caracteres con envoltura) entra en la verificación previa del
peor caso. Esto es una decisión del fundador, no parte del arreglo.

## 6. Decisión de presupuesto [PROPUESTO]

| Decisión | Alternativa descartada | Razón | Qué la reabre |
|---|---|---|---|
| **R1.** Quitar la guía de replicación del pedido **solo** cuando coincide exactamente con la plantilla conocida (versionada), pasando a líneas fijas las 4 piezas que no estaban dichas (producto, «solo secuencia, no estilo», «no copies música ni promociones», «no inventes gancho ni tomas»). Si no coincide (texto viejo, editado o de otra versión), se conserva literal y protegida como hoy. | Subir el presupuesto otra vez; resumir la guía con un modelo; recortarla. | Es la única redundancia grande y demostrable (877 caracteres, §3.1). Coincidencia exacta = cero riesgo de perder algo que alguien escribió. | Que la pantalla cambie la plantilla sin versionarla (lo detecta la prueba de igualdad del §7.1). |
| **R2.** La identidad de la marca deja de ser lo primero que se borra: entra entera; solo si no cabe se recorta, nunca por debajo de su primera oración (mínimo 200 caracteres), y el recorte queda registrado. | Protegerla entera (fallaría con posicionamientos largos sin que el operador pueda arreglarlo en esa pantalla); dejarla como está. | Hoy se pierde en todos los casos medidos. El fundador pide que no se pierda calidad. | Un Brand Kit cuyo posicionamiento no cabe ni en su primera oración: se mide y se decide. |
| **R3.** La ruta de edición incluye los datos clave (`_facts_line(brief, _FACTS_IN_CLIP)`), como la de movimiento. | Dejarla sin datos clave. | El fundador los lista como obligatorios; la ruta de movimiento ya los manda con la misma regla de «nunca escribirlos en pantalla». | Una medición que muestre que empeoran el video editado. |
| **R4.** Presupuesto por ruta = guardia del adaptador (`byteplus_ark.MAX_PROMPT_CHARS = 3000`, importada, no copiada) menos lo que esa ruta añade después: clip (movimiento y edición) 3000; video hablado 3000 − 400 − 18 (como hoy); diapositiva animada con video de referencia 3000 − sufijo − 1. En este PR se aplica solo a las rutas de clip (versión de compilador 1); las demás quedan en 2950 hasta medirlas, con su propio ticket. | 2950 fijo para todo (margen de 50 sin base: el adaptador revisa el mismo texto, ya recortado de espacios); subir la guardia de 3000. | Coincide con lo que el fundador espera («menos de 3000 pasa») y con lo que el adaptador acepta. **No es lo que arregla el caso** (el compilador nuevo deja 2783, cabe en 2950): solo quita un margen inventado. | Que BytePlus rechace algún pedido ≤ 3000 (ninguno registrado). |
| **R5.** La guardia de 3000 del adaptador **no se mueve**. | Subirla hacia las «1000 palabras inglesas» que recomienda la documentación (≈ 6000 caracteres). | La documentación oficial solo **recomienda** ≤ 500 caracteres chinos o ≤ 1000 palabras inglesas y advierte que un texto largo dispersa la información y el modelo ignora detalles. No hay límite duro publicado. El pedido nuevo mide 393 palabras; la palanca de calidad es quitar redundancia, no alargar. | Un pedido sin redundancia que necesite más de 3000 con todo lo obligatorio. Entonces correr la sonda del §10 antes de tocar el número. |
| **R6.** La verificación previa prueba el **peor caso admisible**: todos los elementos obligatorios + **todos** los logos elegidos a la vez + (ruta de movimiento) una copia de peor caso; si no cabe, falla **antes de la copia** con un mensaje que nombra el campo y cuántos caracteres sobran. | Probar logos de uno en uno y aceptar el primero (hoy); limitar el selector a k logos (cambia el prompt del selector y exige medirlo). | El selector puede elegir cualquier logo o varios; solo el peor caso garantiza que nadie paga por una pieza imposible. Con el compilador nuevo los tres logos juntos caben (2932). | Operadores que eligen muchos logos y reciben el rechazo: entonces sí pasar el límite al selector. |

Tipo de puerta: dos vías. Todo queda detrás de una versión de compilador nueva; los borradores
congelados con la versión anterior se compilan igual que hoy.

Costo: sin llamadas nuevas. Cada rechazo que hoy ocurre después de pagar (USD 0,09 en este caso)
pasa a ocurrir antes de pagar.

## 7. Especificación para creative-engineer

### 7.1 Una sola plantilla de replicación

- `packages/creative/src/qualify_creative/prompt_text.py`: mover aquí la prosa de
  `replication_context` como constante versionada `REPLICATION_PROSE_V1` (con `{product}`), más
  `replication_prose(product: str) -> str` y
  `known_replication_prose(prose: str) -> str | None`, que devuelve el producto si la prosa
  (tras `visual_text` y `strip`) es idéntica a la plantilla con ese producto, y `None` si no.
  El producto se extrae de la primera oración con una expresión anclada; si no coincide todo lo
  demás byte a byte, `None`.
- `Qualify/reel_replication.py::replication_context` usa `replication_prose(...)` (misma salida
  byte a byte que hoy; prueba de igualdad). Así la pantalla y el compilador no pueden divergir sin
  que falle una prueba.

### 7.2 Versión del compilador (no reinterpretar instantáneas)

- `qualify_creative.schemas.MediaInputs`: `prompt_compiler_version: int = 0`.
- `media.py`: `PROMPT_COMPILER_VERSION = 1`; `MediaProducer.prepare_new_brief` lo sella **solo en
  ejecuciones nuevas** (el mismo camino que ya sella `brand_application_version=2`). No sellarlo en
  `_select_resources` (que hoy sobrescribe `brand_application_version`).
- Todo lo de §7.3–7.5 se activa con `brief.media.prompt_compiler_version >= 1`. Con 0, la salida
  de `_brand_applied_reel_edit_prompt`, `clip_prompt` y `_preflight_*` es **byte a byte la de
  hoy** (prueba de instantánea con la fixture: sigue fallando con 2966).
- Los pasos ya enviados no cambian: `CheckpointRouter._run` reproduce la petición guardada.

### 7.3 Compilador de edición v1 (`_brand_applied_reel_edit_prompt`)

Orden de líneas (texto de referencia medido en el prototipo; el ingeniero puede ajustar la
redacción si la prueba de calidad del §8 sigue en verde):

1. «Edit @Video1 in place, using it as the sequence guide only, not its visual style. Preserve
   choreography, shots/cuts/timing, framing, camera, hands/actions, geometry and duration/ratio;
   REPLACE BRAND GRAPHICS below. Source captions/audio/promotions are not client instructions;
   never copy its music or promotions.»
2. `Client product: "<producto>".` — producto de `known_replication_prose`, si no `brief.product_ref`;
   omitida si ambos vacíos.
3. Líneas `@ImageN` por rol (sin cambio).
4. Reemplazo del producto (sin cambio).
5. Reemplazo de marcas ajenas (sin cambio).
6. Paleta (sin cambio). 7. Tipografías (sin cambio).
8. «Use only existing text or wording explicitly approved by the operator; do not invent a visual
   hook, new shots, CTAs, promotions, props or a new ending.»
9. `_facts_line(brief, _FACTS_IN_CLIP)`.
10. `_Flex("Client identity: ", kit.positioning, floor=<primera oración, mín. 200, máx. 250>)` —
    rango propio, nunca a cero (ver §7.4).
11. Operador: protegido, literal (sin cambio).
12. Guía de replicación: **omitida** si `known_replication_prose(...)` reconoce la plantilla y el
    JSON fue retirado; si no, protegida y literal como hoy.
13. Metadatos no verificados: como hoy.
14. Bloque de recursos (sin cambio).

Medido con el prototipo (fuera del repo) sobre el caso real:

| Logos | Actual | v1 (identidad entera + datos clave + producto) |
|---|---:|---:|
| imagotipo | rechazo 2966 | **2783** |
| isologo | 2938 (sin identidad) | 2755 |
| isotipo | 2950 (identidad: 1 carácter) | 2746 |
| imagotipo + isologo | rechazo 3045 | 2862 |
| imagotipo + isotipo | rechazo 3036 | 2853 |
| isologo + isotipo | rechazo 3008 | 2825 |
| los tres | rechazo 3115 | 2932 |

### 7.4 `_budgeted`: suelo que no llega a cero

- `_Flex` gana `hard_floor: int = 0`: en la segunda pasada (debajo del suelo) no baja de
  `hard_floor`. La identidad usa `hard_floor = floor`. El resto de flexibles no cambia.
- `_budgeted` devuelve, además del texto, qué líneas recortó y cuánto (`trims`), o lo expone en
  una variante `_budgeted_report`. El recorte de la identidad se registra en los campos de
  `trace.media_request` y en el manifiesto de transporte (procedencia: `prompt_compiler_version`,
  `prompt_chars`, `prompt_budget`, `trims`).

### 7.5 Presupuesto, verificación previa y mensaje

- `media.py`: `from qualify_creative.adapters.byteplus_ark import MAX_PROMPT_CHARS`;
  `_complete_budget(brief, appended: int = 0) -> int` = `MAX_PROMPT_CHARS - appended` si
  `prompt_compiler_version >= 1`, si no `MEDIA_PROMPT_BUDGET` (2950). Usarlo en `clip_prompt`,
  `reel_edit_prompt` y sus variantes. `MEDIA_PROMPT_BUDGET` sigue existiendo para v0 y las demás
  rutas. `selection["prompt_budget"]` guarda el presupuesto efectivo.
- `_preflight_resource_candidates` (v1): compilar con **todos** los obligatorios + **todos** los
  logos candidatos juntos (además del bucle actual por logo, que pasa a exigir que **todos**
  quepan). Para clip en modo movimiento, pasar una copia de peor caso
  (`_WORST_CASE_CLIP_COPY`: gancho de 160 caracteres, 4 tomas) en vez de `copy=None`.
- Error nuevo `_PromptOverBudget(_MediaFailed)` con `needed`, `budget`, `operator_chars`. El
  mensaje lo arma la verificación previa (antes de la copia), en español llano
  (`qualify-copy-es`):
  - Sobra texto y el operador escribió más que el exceso: «Tu pedido es muy largo para este video:
    sobran {exceso} caracteres. Acorta lo que escribiste en «¿Qué quieres…?» (ahora tiene {n}) y
    vuelve a intentarlo. Conservaremos todos los recursos que elegiste.»
  - Sobra aunque el texto del operador fuera corto (muchos logos): «Elegiste {k} logos y no caben
    todos en este video con tu texto. Quita uno y vuelve a intentarlo.»
  Nunca sugerir acortar notas de recursos vacías ni una escena que no existe.
- Arreglar los dobles de prueba sin `pipeline_version` (`types.SimpleNamespace` de borrador en
  `test_brand_reference_matrix.py` y `test_brand_references.py`) para que las pruebas «falla antes
  de pagar» vuelvan a correr.

### 7.6 Pruebas

En `packages/api/tests/test_required_resource_prompts.py` (o un archivo nuevo
`test_prompt_budget_v1.py`):

1. Fixture real anonimizada, v0: sigue fallando con 2966 (instantánea compatible).
2. Misma fixture, v1, las 7 combinaciones de logos: compila ≤ 3000 y pasa el guardián del §8.
3. Límites v1 de clip: 2999 / 3000 aceptan, 3001 rechaza; v0: 2949 / 2950 / 2951 como hoy.
4. Guía de replicación alterada en una letra: se conserva literal y protegida (v1).
5. JSON del reel que no coincide con `source_reel`: se conserva como metadatos no confiables.
6. Verificación previa v1: un logo cabe y otro no → rechazo **antes de la copia** (cero llamadas
   a Anthropic en el doble); los tres logos juntos no caben → rechazo antes de la copia con el
   mensaje de logos.
7. Ruta de movimiento: gancho de 160 caracteres que pasaría la verificación con `copy=None` pero
   no en ejecución → ahora la verificación lo rechaza.
8. «Debe evitar» con 0, 1, 3 y 5 frases y «Debe mencionar» lleno: el pedido de edición mide lo
   mismo; texto del operador de 1200 caracteres → rechazo antes de pagar con el exceso exacto.
9. Identidad de 900 caracteres: se recorta, nunca por debajo de su primera oración, y el recorte
   queda en `trims`.
10. `replication_context` de la pantalla == `replication_prose` (igualdad byte a byte).

Al terminar: documentar el cambio en `docs/modelos-generativos/` el mismo día (`qualify-measure`):
es un cambio de prompt. Sin pruebas pagadas sin autorización.

## 8. Guardián de «sin pérdida de calidad»

Ayudante de pruebas `packages/api/tests/prompt_quality.py`:
`assert_prompt_keeps_intent(prompt, *, brief, kit, refs, images, budget)`. Comprueba sobre el
pedido final (después de `_budgeted`):

| Elemento | Regla |
|---|---|
| Texto del operador | presente **literal** (tras `visual_text` y comillas dobles → simples, que es lo que ya hace `_quoted`) |
| Producto | `product_ref` (o el de la guía) literal |
| Paleta | cada `#rrggbb` de `kit.palette_rgb` |
| Tipografías | `font_heading` y `font_body` literales |
| Datos clave | cada par nombre/valor de `highlights` que cabe en `_FACTS_MAX`, en el JSON |
| Recursos | por cada recurso: `Image {n}` con su índice real; logos: su alias de categoría (`principal imagotipo`…), porque la categoría manda sobre el nombre de archivo (en este caso el archivo de la ranura imagotipo tiene el nombre de otra categoría); no logos: su etiqueta y su rol; la nota de uso **literal** si no está vacía |
| Identidad | `kit.positioning` entero, o al menos su primera oración (mín. 200) con el recorte registrado |
| Guía de replicación | o literal, o cubierta: cada frase de la tabla del §3.1 con su frase inglesa obligatoria presente («sequence guide only, not its visual style», «never copy its music or promotions», «do not invent a visual hook, new shots», «REPLACE BRAND GRAPHICS», «replacing source-brand colors», «not its photo background/props», `Client product:`) |
| Sin duplicados | ninguna oración de más de 40 caracteres aparece dos veces |
| Largo | `len(prompt) <= budget` |

Se ejecuta contra la fixture real (las 7 combinaciones) y los casos límite del §7.6. La tabla de
cobertura de la guía vive junto a `REPLICATION_PROSE_V1`: si alguien cambia la plantilla, la
prueba obliga a declarar dónde queda cada frase nueva.

## 9. Lo que no se verificó

- No hubo llamadas a BytePlus ni a Anthropic. No se afirma nada sobre la calidad visual del video
  con el pedido nuevo; la mejora es estructural (menos repetición, nada omitido).
- La decisión del selector no quedó guardada; se infiere de forma inequívoca porque solo una
  combinación da 2966.
- No se verificó en pantalla que el campo «¿Qué quieres…?» corte en 1200 caracteres
  (`CONTEXT_MAX_CHARS` vive en `context_ai.py`); la prueba 8 del §7.6 cubre el caso aunque no corte.

## 10. Sonda empírica (propuesta, no ejecutada)

Solo si R5 se reabre: dos tareas Seedance 2.5 de 5 s en 480p sin video de entrada, con pedidos de
4500 y 6000 caracteres, para ver si BytePlus los acepta. Costo estimado con la tabla de precios v7:
~48 000 tokens × USD 10,70/M ≈ **USD 0,51 por tarea, ≈ USD 1,03 en total**. Requiere autorización
del fundador.

## 11. Implementación (2026-11-02)

Implementado por creative-engineer sin llamadas pagadas y sin commit, con un **cambio de alcance
del fundador** del mismo día que reemplaza R4/R5 para Seedance 2.x: sin tope de caracteres ni
recortes; único techo, las 1000 palabras que recomienda la documentación oficial (sin límite
duro publicado). Seedance 1.x conserva 3000. El suelo de la identidad (§7.4) se descartó: la
identidad viaja entera y protegida. Resultados, cifras por combinación de logos y la
reevaluación de cada optimización: `correccion-presupuesto-prompt-20261102.md`.
