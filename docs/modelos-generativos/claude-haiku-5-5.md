# Claude Haiku 5.5 — borradores de respuesta a comentarios (QUA-128)

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), llave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-haiku-5-5` · esfuerzo `low` (Haiku 5.5 razona por defecto) |
| Precio | US$0,10 / US$0,50 por millón de tokens de entrada / salida (skill `claude-api`, octubre de 2026) |
| Uso en Qualify | `qualify_api/replies/claude_drafts.py` → `ClaudeReplyDraftProvider`, versión del generador `qua22.2:claude-haiku-5-5` |
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

> Cuando la bitácora central (`docs/modelos-generativos/pruebas.md`, hoy sin commitear en otra rama) llegue a `main`, copiar esta entrada ahí.
