# Claude Haiku 5.5 — borradores de respuesta a comentarios (QUA-128)

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), llave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-haiku-5-5` · esfuerzo `low` (Haiku 5.5 razona por defecto) |
| Precio | US$0,10 / US$0,50 por millón de tokens de entrada / salida (skill `claude-api`, octubre de 2026) |
| Uso en Qualify | `qualify_api/replies/claude_drafts.py` → `ClaudeReplyDraftProvider`, versión del generador `qua22.2:claude-haiku-5-5` (agradecimientos). Desde 2026-10-23 también las respuestas públicas comerciales de Fase B, `m24789645.1:claude-haiku-5-5` (entrada FASEB-001) |
| Reemplaza a | `Qwen/Qwen3-VL-4B-Instruct` vía HF `featherless-ai` (`qua22.1`): en producción nunca tuvo `HF_TOKEN` |
| Datos | Solo el texto del comentario y el nombre del negocio. Siempre con aprobación humana antes de publicar (ADR 21) |

## Prueba PR-HAIKU-001 — 2026-10-08

- **Quién:** Claude Code, a pedido del fundador.
- **Clave:** `QUALIFY_ANTHROPIC_API_KEY` del `.env` local.
- **Material:** 5 comentarios **sintéticos** (no de clientes), negocio «PuntoServis».

| Comentario | Borrador | Tokens (entrada/salida) | Costo | Latencia |
|---|---|---|---|---|
| Me encantó el servicio, llegaron súper rápido a arreglar la nevera 🙌 | ¡Qué alegría leer esto! Gracias por confiar en PuntoServis y por tus palabras, nos encanta saber que llegamos rápido cuando más lo necesitabas. 🙌 | 254 / 69 | $0,000060 | 1,6 s |
| Qué buen video jajaja, ya los sigo | ¡Qué bueno que te haya gustado, gracias por la buena onda! Bienvenido a PuntoServis, te esperamos por aquí. | 239 / 52 | $0,000050 | 0,8 s |
| El mejor taller de Cúcuta sin duda, 100% recomendados | ¡Muchas gracias por tu recomendación! Nos alegra muchísimo que hayas tenido una buena experiencia en PuntoServis. ¡Será un gusto seguir atendiéndote! | 247 / 71 | $0,000060 | 1,1 s |
| Excelente atención, ¿tienen sede en Bogotá? | ¡Muchas gracias por tus palabras! Lamentablemente no tengo la información sobre sus sedes en este momento, pero te invitamos a escribirnos por mensaje directo para ayudarte con eso. | 244 / 74 | $0,000061 | 0,8 s |
| 😍😍😍 | ¡Muchas gracias por tu cariño, nos alegra muchísimo leerte! 😊 | 228 / 35 | $0,000040 | 1,0 s |

**Resultado:** 5/5 borradores utilizables, unos **US$0,05 por cada 1000 borradores**.

- Respetó la regla de no inventar datos: no afirmó tener sede en Bogotá.
- **Hallazgo:** en esa misma respuesta habló como un tercero («no tengo la información sobre *sus* sedes») en vez de como el negocio. Conviene ajustar el prompt para que una pregunta sin respuesta en el comentario derive a mensaje directo **en primera persona del negocio**. No bloquea: cada borrador pasa por revisión humana.

## Uso FASEB-001 — respuestas públicas a comentarios con intención comercial (m-24789645) — 2026-10-23

- **Quién:** Claude Code y Raul, prueba local real de Interacciones · Fase B. Documento de la fase: [interacciones-fase-b-respuestas-comerciales.md](../interacciones-fase-b-respuestas-comerciales.md).
- **Uso en Qualify:** `ClaudeDraftGenerator` (`conversations/suggest.py`) con el prompt público `PUBLIC_SYSTEM_PROMPT` (`replies/public_drafts.py`), versión del generador **`m24789645.1:claude-haiku-5-5`**. Esfuerzo `low`, herramienta estricta `propose_reply`, `tool_choice: auto`, `max_tokens` 2048.
- **Datos que recibe:** nombre de la marca, productos activos del catálogo **sin precios** (decisión D1), el texto del comentario sin nombre ni usuario del autor y lo que pregunta (clases de Fase A).
- **Material:** comentarios reales de una cuenta de prueba (`@rauldevgames`, tester `@raul._.rangel`), entre ellos «Cuanto cuesta?».

| Medida | Valor (log `conversations.draft`) |
|---|---|
| Tokens de entrada | 263–283 |
| Tokens de salida (con razonamiento) | 128–181 |
| Costo por borrador | US$0,000090–0,000118 |
| Estimación, 300 comentarios comerciales/mes | ≈ US$0,027–0,035 por cliente al mes (el doble si cada borrador se regenera una vez) |

**Resultado:** el borrador final, «¡Hola! Te escribimos por DM con el precio 😊», no dio precio, se aprobó y se publicó en Meta (`sent`, `external_reply_id` 17931155721421749, ≈ 6 s de Meta). Con el catálogo vacío el mismo comentario pidió revisión (`empty_catalog` + `price_unknown`), como corresponde.

- **Hallazgo:** a veces el modelo reporta su propia derivación a DM («te escribimos por DM…») como afirmación no respaldada. Eso añade `model_unsupported` y pide revisión a un borrador correcto. Se puede corregir en el prompt (con nueva versión `m24789645.2`) o filtrar en código.
- **Límite del control local:** el detector de precios no ve «15 mil», «15k» ni «quince mil» (falta la moneda). D1 sigue cubierto porque el modelo no recibe precios.
- **No es un golden set:** no hay medición de calidad por clase; el control de calidad es la revisión humana de cada borrador y los motivos de revisión que calcula el código.

> Cuando la bitácora central (`docs/modelos-generativos/pruebas.md`, hoy sin commitear en otra rama) llegue a `main`, copiar esta entrada ahí.

## Prueba ATENDER4A-001 — clasificar cualquier comentario y responderlo (m-24848532) — 2026-10-23

- **Quién:** el agente data-scientist-fde (Claude Code), dentro de la épica UX m-24842956. El fundador no estaba. Clave: `QUALIFY_ANTHROPIC_API_KEY` del `.env` local.
- **Qué se probó:**
  - El clasificador `replies/triage.py` (`ClaudeCommentTriager`): una sola llamada devuelve sentimiento (`pos`/`neu`/`neg`), tipo (`praise`/`question`/`complaint`/`other`) y si necesita respuesta. Prompt **`atender4a.1`**, esfuerzo `low`, herramienta estricta `registrar_comentarios`, `tool_choice: auto`, lotes de 25. Es el candidato para reemplazar a robertuito.
  - Los borradores `replies/any_comment_drafts.py`, con el prompt **`atender4a.1:claude-haiku-5-5`** sobre `ClaudeDraftGenerator`.
  - La línea base fue el clasificador de intención `intent-claude-v2`.
- **Material:** 80 comentarios **sintéticos** (`packages/api/evals/replies_ai/synthetic_smoke.jsonl`, 40 en `dev` y 40 en `test`) de tres negocios ficticios de CO/VE/UY. Un solo etiquetador, el mismo agente que escribió el prompt, así que sirve para probar las herramientas y **no mide calidad**.
- **Resultado en `test`:**
  - Todas las clases pasaron sus umbrales: precisión ≥ 0,88; cobertura de `neg` 1,00; «necesita respuesta» con cobertura 1,00 y precisión 0,95.
  - La línea base solo llegó a una cobertura de 0,55 en «necesita respuesta»: no detectó 9 de las 10 quejas.
  - Borradores: 0 precios fuera del catálogo, 0 marcas de tercera persona, 0 errores. La revisión humana sigue pendiente.
- **Costo:** US$0,000019 por comentario clasificado y US$0,00017 por borrador; unos US$0,04 por cliente al mes con 300 comentarios. La prueba completa costó ≈ US$0,010.
- **Hallazgos:**
  - No conviene preparar borrador para el tipo `other`: el modelo le respondió al spam y a etiquetas entre amigos.
  - Derivar a mensaje privado vuelve a disparar `model_unsupported` (igual que en FASEB-001).
  - Los borradores repiten «Gracias por escribirnos» y no usan la voz de la marca.
- **Estado:** **PENDIENTE de datos reales**. El procedimiento, los umbrales y lo que tiene que dar el fundador están en [respuestas-comentarios-medicion.md](../respuestas-comentarios-medicion.md).

## Prueba ATENDER4A-002 — borradores `atender4a.2` tras la revisión de UX (m-24848532) — 2026-10-23

- **Quién:** el agente data-scientist-fde (Claude Code), dentro de la épica UX m-24842956. El fundador no estaba. Clave: `QUALIFY_ANTHROPIC_API_KEY` del `.env` local.
- **Qué cambió:** el prompt de borradores `replies/any_comment_drafts.py` pasó a **`atender4a.2:claude-haiku-5-5`** (mismo modelo, mismo generador `ClaudeDraftGenerator`, mismos ajustes). Cambios pedidos por la revisión de UX: en las quejas, invitar a la persona a escribir («escríbenos por mensaje privado») en lugar de prometer que el negocio le escribe; no decir «tienes razón», «resolverlo» ni «solucionarlo»; no decir en público que falta un dato; sin emojis en las quejas; no empezar siempre con la misma frase ni usar «gracias por escribirnos». El clasificador no cambió (`atender4a.1`) y no se volvió a correr.
- **Material:** los mismos 40 comentarios sintéticos de `test` de ATENDER4A-001 (`synthetic_smoke.jsonl`). Sigue siendo una prueba de las herramientas, **no una medición de calidad**.
- **Informe:** `packages/api/evals/replies_ai/results/20261023-143235.json` y su hoja `20261023-143235-revision.csv` (con la columna nueva `promete_o_admite`).
- **Resultado (controles automáticos, `atender4a.1` → `atender4a.2`):**

| Control | `atender4a.1` | `atender4a.2` |
|---|---|---|
| Errores / precios fuera del catálogo / tercera persona | 0 / 0 / 0 | 0 / 0 / 0 |
| Borradores con «te escribimos» (promesa) | 10 | **0** |
| Quejas con «tienes razón» | 1 | **0** |
| Quejas con «resolverlo»/«solucionarlo» | 7 | **0** |
| Quejas con emoji | 8 de 10 | **0** |
| Apertura más repetida (3 primeras palabras) | «gracias por escribirnos», 27,5 % | «qué bueno que», 20,0 % (justo en el límite de 20 %) |
| Marcas `model_unsupported` | 12 | 10 |

- **Costo:** US$0,0066 por los 40 borradores (US$0,00016 por borrador), igual que la versión anterior.
- **Hallazgos:**
  - Las 10 quejas terminan casi igual: «Escríbenos por mensaje privado y lo revisamos contigo», copiado del ejemplo del prompt. Debajo de una misma publicación con varias quejas se notaría. El control de aperturas no lo detecta porque mira el comienzo.
  - Los `other` siguen recibiendo borrador (spam, amigos que se etiquetan); eso se corta en la compuerta de ATENDER-4b, no aquí.
  - La revisión humana sigue pendiente.
- **Estado:** **PENDIENTE de datos reales**, igual que ATENDER4A-001.

## Prueba SENT-HAIKU-001 — sentimiento con confianza, contra robertuito (m-24854495) — 2026-10-25 · PENDIENTE

- **Qué se va a medir:** si `ClaudeCommentTriager` con el prompt **`atender4a.1-conf`** (el de `atender4a.1` más un campo `confidence` de 0 a 1) puede reemplazar a robertuito en el sentimiento de comentarios y menciones (decisión del fundador del 2026-10-25, opción C). El prompt `atender4a.1` sigue disponible y es el valor por defecto hasta que esto se mida. No se llama `atender4a.2` porque ese nombre ya es del prompt de borradores.
- **Ajustes:** `claude-haiku-5-5`, esfuerzo `low`, herramienta estricta `registrar_comentarios` (sin `minimum`/`maximum`: la herramienta estricta no los admite, así que el código recorta la confianza a 0..1), `tool_choice: auto`, lotes de 25, prompt de sistema cacheado.
- **Material:** solo los 408 comentarios públicos del golden set de intención (misma división), etiquetados a ciegas por Raul y Yesika. Los comentarios reales de los negocios del fundador quedaron fuera (decisión del fundador, 2026-10-25), así que el recall de `neg` descansa solo en datos públicos.
- **Prueba de humo (2026-10-25, corrida con el nombre provisional `atender4a.2`, mismo texto que `atender4a.1-conf`):** 10 comentarios públicos sin etiquetar, 2 lotes de 5. US$0,000591; la caché se leyó en el segundo lote (1.498 tokens); confianza en 10 de 10, entre 0,35 y 0,90; latencia por lote de 5 de 1,74 s (p50) y 4,69 s (p95).
- **Estado:** pendiente de etiquetas. Detalle, umbrales y pasos en la [entrada SENT-HAIKU-001 de la bitácora](pruebas.md#sent-haiku-001).

## Uso REELSHEET-001 — ficha por planos de reels de Referentes (m-24955652) — 2026-11-05

`referentes/reel_analysis_ai.py` (`ANALYSIS_VERSION = 8`, prompt `reel-sheet-prompt-9`, esquema `reel-sheet-schema-5`): una llamada por reel, ≤ 12 grupos de planos y un tope de salida que crece con los fotogramas, de 9.000 a 16.000 tokens (antes 9.000 fijo; m-24993025, [analisis-reel-tope-salida-20261112.md](analisis-reel-tope-salida-20261112.md)); una respuesta cortada por ese tope falla como `model_output_cut` y no se reintenta. Personas y rostros se contestan por fotograma y se deciden por plano con la regla de cobertura de 0,5 s (`presence-frames-gap0.5-3`). Peor pedido: USD 0,015045 (antes 0,011545). En vivo (2026-11-06): 19/19 `ok` con video disponible, USD 0,0041 de media por reel; ninguna persona ni cara perdida en 195 planos anotados. Detalle: [pruebas.md#reelsheet-001](pruebas.md#reelsheet-001).

## Uso NIVELES-001 — juez de los niveles de consciencia (m-25026482) — 2026-11-13

Detalle en la [bitácora, NIVELES-001](pruebas.md#niveles-001). `claude-haiku-5-5` @ `low`, rúbrica `juez-niveles-v2` (`qualify_api.evals.awareness_levels.JUDGE_RUBRIC`), dos lecturas por juego: a ciegas (nivel inferido, calidad 1–5, datos inventados, ventajas usadas) e informada (¿cumple su nivel declarado?).

- **Costo:** US$0,001–0,0015 por lectura de un juego de 10 ideas.
- **Lo que se ajustó en dev:** la v1 contaba atributos del producto («dos sabores») como datos inventados; la v2 limita el conteo a las siete clases de dato.
- **Límites conocidos:** no está validado contra etiquetas humanas. En partes pide cifras para product_aware, que el prompt de partes prohíbe (desajuste de la rúbrica). Además dio un falso positivo de domicilio porque no recibió el CTA del ángulo. Un `APITimeoutError` cortó una corrida: el ejecutor ahora registra el error y cuenta la llamada a su techo.

## Uso NIVELES-002 — juez, segunda pasada (m-25026482) — 2026-11-13

Detalle en la [bitácora, NIVELES-002](pruebas.md#niveles-002).

- Rúbrica de ángulos y copy sin cambios (`juez-niveles-v2`), para comparar con NIVELES-001.
- Para planes de video, el agregado `juez-niveles-v2+partes-v1` (sin cifras por diseño; el ángulo pasa como dato dado). Con él, product_aware en partes pasa de 0/6 a 6/6.
- Las ofertas inventadas ya no dependen solo del juez: `invented_offers` (determinista) cuenta gratis, regalo, incluido, descuento, promoción y servicios como reservas, apartar, domicilio o «para llevar».
- Otro `APITimeoutError`, esta vez del copy, quedó registrado y contado a su techo.

## Uso NIVELES-003 — juez, tercera pasada (m-25026482) — 2026-11-13

Detalle en la [bitácora, NIVELES-003](pruebas.md#niveles-003). Rúbrica sin cambios (`juez-niveles-v2`).

- El «2/6 nombra el horario» de NIVELES-002 no fue del juez: lo dio la expresión regular determinista, que leyó la calle «de la 57» como hora. Está corregida.
- Junto al juez van ahora dos chequeos deterministas en solution_aware: `concrete_fact` y `generic_claims`.

## Uso NIVELES-004 — juez de clips y partes con nivel (m-25026509) — 2026-11-13

Detalle en la [bitácora, NIVELES-004](pruebas.md#niveles-004).

- Agregado de clips (`juez-niveles-v2+clip-v1`), escrito antes de correr: un clip no tiene guion hablado, así que se juzgan gancho, texto, CTA y las 3 tomas; en most_aware el texto largo cuenta en contra.
- Partes con el agregado de NIVELES-002.
- Sigue sin validar contra etiquetas humanas.
- En 2 de 66 copias faltó la lectura informada.

## Uso NIVELES-005 — rúbrica v3 alineada con las medidas de most_aware (m-25026509) — 2026-11-13

Detalle en la [bitácora, NIVELES-005](pruebas.md#niveles-005).

- `juez-niveles-v3`: la regla de most_aware lleva las medidas de la consigna (gancho de unas 6 palabras, CTA de unas 5, texto de unas 25 palabras, el mínimo de la marca permitido). El agregado de clips (`clip-v2`) ya no castiga el texto largo por sí solo.
- Las salidas guardadas de NIVELES-003/004 se volvieron a juzgar con la v3 para comparar con la misma vara: US$0,010 por 20 copias.

## Uso NIVELES-006 — rúbrica v4 de most_aware y fuentes del juez (m-25027151) — 2026-11-14

Detalle en la [bitácora, NIVELES-006](pruebas.md#niveles-006).

- **Rúbrica v4:** para most_aware, el horario y el lugar cuentan como parte de «cómo comprar». La v3 los marcaba como falla, en contra del ejemplo del fundador.
- **Fuentes:** el juez ahora recibe lo de «Debe mencionar» y los ejemplos del kit como datos dados. Sin ellos marcó «al amanecer» como inventado en 6 de 7 clips de viajes.
- Las salidas guardadas se volvieron a juzgar con la misma vara (US$0,049 por 81 copias, en dos tandas).

## Uso LUGAR-001 — lugar del texto y del logo según lo que muestra el video (m-25026599, EF-20) — 2026-11-23 · MEDIDO

Decisión de Deivid (2026-11-23, vía «creacion de tickets»): IA con visión, igual que el análisis de reels, con Claude Haiku 5.5.

- **Modelo:** `claude-haiku-5-5`, esfuerzo `low`, pensamiento adaptativo por defecto (sus tokens cuentan dentro de `max_tokens` = 2048).
- **Precio:** US$0,10 por millón de tokens de entrada y US$0,50 de salida (prompts de hasta 100K tokens). Fuente: el skill `claude-api` (tabla en caché del 2026-11-03) y `qualify_creative/pricing_data/v10.json`, que ya tenía la entrada; no hace falta una versión nueva de la tabla.
- **Módulo:** `packages/api/src/qualify_api/creative/placement_ai.py`, prompt `placement-prompt-1`. Envía de 1 a 3 cuadros del video preparado (720×1280 como máximo) y devuelve la franja (`top`, `middle`, `bottom`) para el texto y para el logo, con un motivo y las franjas que ocupa el sujeto. Ante cualquier falla vuelve al lugar de hoy: texto abajo, logo arriba.
- **Tope por llamada:** US$0,001943 con 3 cuadros (cada imagen contada a 1.600 tokens, prefijo como escritura de caché, 2.048 de salida); fijado en `MAX_REQUEST_USD` = US$0,0021.
- **Costo esperado por pieza** (estimado, sin medir): unos 5.900 tokens de entrada (3 cuadros de ~1.229 tokens más ~2.200 de prompt) = US$0,0006, y de 300 a 800 de salida = US$0,00015–0,0004. Total: **US$0,0007–0,001 por pieza** con 3 cuadros; unos US$0,0005 con 1 cuadro.
- **Guardas:** el tope por llamada; hasta 2 llamadas por pieza; 1.500 llamadas al día para todos los negocios (`QUALIFY_VIDEO_PLACEMENT_FLEET_DAILY`), o sea, como mucho US$3,15 al día.
- **Prueba en seco (2026-11-23):** `just eval-lugar` con el material del repo (2 fotos de muestra y 2 videos de efectos) y con un archivo de casos de prueba fuera del repo. Se armaron todas las solicitudes con el módulo real, se cotizaron y no se envió nada: 0 llamadas a Anthropic, US$0 gastado.
- **Material (2026-11-23):** 10 videos de comida tomados de la base de desarrollo, solo lectura. No hay videos que el dueño haya subido de su propio producto, así que se usaron:
  - 4 videos que Qualify generó para una hamburguesería cliente: una hamburguesa smash, unas manos armando una hamburguesa, una mascota con una hamburguesa y un video de presentador con la foto del plato;
  - 5 reels de otras cuentas, que el dueño subió como referencia: sándwich de pollo, hamburguesa con papas, pollo frito, papas con queso y un local con bocados;
  - 1 video de banco de imágenes: una hamburguesa.
- **Cuadros:** 3 por video, al 20, 50 y 80 % de su duración (`sample_placement_frames`). Son 30 en total.
- **Etiquetado:** lo hizo un agente (creative-engineer), mirando cada cuadro y marcando las franjas que ocupa el sujeto. Una franja cuenta cuando el sujeto ocupa una parte visible de ella, no cuando solo toca el borde. Deivid aprobó la muestra de 8 cuadros el 2026-11-23: «está perfecto, las posiciones y la detección de los sujetos».
- **Criterio, cambiado por decisión de Deivid del 2026-11-23:**
  - En 13 de los 30 cuadros el sujeto ocupa las tres franjas.
  - Como el texto mantiene su franja durante todo el video, el máximo posible es 17 de 30.
  - El criterio principal pasa a ser: **el texto no tapa el sujeto en ≥ 90 % de los cuadros con alguna franja libre** (17 cuadros).
  - Se informan también los 30 cuadros, el máximo posible y la línea base de hoy: texto abajo, 10 de 30 (10 de 17 con franja libre); logo arriba, 13 de 30.
- **Método:** `just eval-lugar --cases <archivo fuera del repo> --i-have-spend-authorization --max-usd 2`, con 2 variantes (`3f`, los 3 cuadros; `1f`, solo el del medio), 3 repeticiones cada una. Son 60 llamadas, cotizadas al tope en US$0,107.
- **Resultados (corrida pagada del 2026-11-23, autorizada por Deivid en la sesión):** 60 llamadas, 0 fallas, **US$0,0396 gastados** (cotizado US$0,107), 441 s en total (unos 7 s por llamada).

  | Variante | Texto sin tapar, cuadros con franja libre (meta ≥ 90 %) | Texto sin tapar, los 30 cuadros | Logo sin tapar | Costo por llamada |
  |---|---|---|---|---|
  | Hoy (texto abajo, logo arriba) | 10/17 (58,8 %), no cumple | 10/30 (33,3 %) | 13/30 (43,3 %) | US$0 |
  | `3f` (3 cuadros) | **48/51 (94,1 %), cumple** | 48/90 (53,3 %) | 42/90 (46,7 %) | US$0,00081 |
  | `1f` (cuadro del medio) | **47/51 (92,2 %), cumple** | 47/90 (52,2 %) | 44/90 (48,9 %) | US$0,00051 |

  - Las 3 repeticiones dieron 16, 16 y 16 aciertos (`3f`) y 15, 16 y 16 (`1f`) sobre 17, así que el resultado es estable.
  - El máximo posible sobre los 30 cuadros es 17 (56,7 %); las dos variantes quedan a menos de un cuadro de ese techo.
  - El logo mejora poco sobre hoy (de 43 % a 47–49 %): el modelo suele mandar el logo a la franja contraria al texto aunque el sujeto también esté ahí.
- **Veredicto: apto para encenderse como aviso del texto**, con la variante `3f`. Empata con `1f` dentro del ruido (1 cuadro de 51), mira el video entero, que es lo que dura el texto, y cuesta menos de US$0,001 por pieza. La recomendación del logo se muestra solo como sugerencia secundaria, porque apenas supera el lugar de hoy.
- **Uso en la fase 2, decidido por Deivid el 2026-11-23:** «no quiero que bloquee si se pone el texto, sino que haya una advertencia de que puede tapar el producto y que muestre la mejor posición».
  - El servidor **nunca mueve** el texto ni el logo por su cuenta.
  - Devuelve las franjas del producto, la posición recomendada para el texto y para el logo, si la posición elegida por el dueño tapa el producto, y el motivo en español.
  - La pantalla muestra el aviso con «Usar esta posición».
- **Fase 2 construida (2026-11-24, sin llamadas reales, todo con dobles):** `packages/api/src/qualify_api/creative/placement_advice.py`.
  - Se calcula una vez por video que el dueño sube al generador, sobre su copia liviana de 480p (ED-09), justo después de que el `media-worker` la termina. Va detrás de `QUALIFY_VIDEO_PLACEMENT_AI` (apagado). Si falla, no hay aviso y la pieza sigue igual.
  - El aviso queda en el `result` del trabajo `upload_preview` de ese video (`placement_advice`), sin migración. La pantalla lo lee con `placement_advice_for(tenant_id, claves)` y decide sola si la franja elegida tapa el producto (`covers_product`).
  - Guardas en Postgres: cada llamada se reserva en `creative_usage_events` (unidad `video_placement_token`) antes de hacerse, al tope de US$0,0021, bajo un candado de aviso. Hasta 2 llamadas por video y 1.500 al día para toda la flota (el conteo de la flota es un solo número leído por `admin_session` en el `media-worker`).
  - Después de la llamada, la reserva se ajusta a lo cobrado solo si hubo uso medido. Si la llamada falló en la red (`request_error`) o no midió nada, la reserva queda en el tope: se cuenta de más, nunca de menos.
  - La paga la plataforma (`paid_by=platform`): no toca `budget_spent_usd` de la marca. El costo queda solo en `creative_usage_events` (`Numeric(12,6)`) y, como toda llamada a Claude, en el `consumption_ledger`. Ningún reporte suma las dos tablas.
  - El cliente de Anthropic del `media-worker` espera como mucho 60 s y reintenta una vez, para no frenar la cola de un solo trabajo a la vez.
  - El `media-worker` lee el mismo archivo de entorno que la app (`QUALIFY_ANTHROPIC_API_KEY`); sin la llave no hay aviso (`no_key`). Para encenderlo basta con `QUALIFY_VIDEO_PLACEMENT_AI=on` y reiniciar el `media-worker`. Tope de la flota: `QUALIFY_VIDEO_PLACEMENT_FLEET_DAILY` (1500).
  - **Memoria medida (2026-11-24):** `deploy/measure/upload-preview-memory.sh run k5_hevc10_112.mp4 advice` en Docker con el tope del `media-worker` (768 MiB, 1 CPU), con el aviso encendido y un cliente de Anthropic falso, sin red. La copia de 480p llegó a 410 MiB de memoria anónima. El aviso, después, llegó a 102 MiB (138 MiB de RSS del proceso) y tardó 12,5 s, casi todo en leer los 3 cuadros de un video de 112 s. Sin eventos de falta de memoria (`oom` 0).
  - **Pendiente:** el conteo de la flota filtra `creative_usage_events` por `unit` y `occurred_at` sin un índice propio. Con el volumen de hoy no pesa; si crece, hace falta un índice parcial `(occurred_at) WHERE unit = 'video_placement_token'`, que sería una migración.
