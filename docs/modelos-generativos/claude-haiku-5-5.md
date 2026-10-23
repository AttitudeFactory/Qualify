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
