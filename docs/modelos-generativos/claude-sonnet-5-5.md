# Claude Sonnet 5.5: «Sugerir con IA» del menú de WhatsApp

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), clave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-sonnet-5-5`, esfuerzo `low`, una herramienta estricta (`propose_text`), `max_tokens` 3.072 |
| Precio | US$2 de entrada / US$10 de salida por millón; escritura de caché (5 min) US$2,50, lectura US$0,10 (`claude_tools.PRICES` y `CACHE_READ_PRICES`) |
| Uso en Qualify | `qualify_api.whatsapp.menus.suggest_ai` (m-24936838): propone el saludo o una «respuesta de siempre» con la voz de la marca y solo con los datos que escribió el dueño. Versión de prompt `wa-suggest-1` (`PROMPT_VERSION`, va en el log de cada llamada). También lo usa «Potenciar con IA» del generador (`creative/context_ai.py`), con el mismo patrón |
| Datos | Lo que el dueño escribió en la pantalla (datos del negocio, otras respuestas, el texto del campo) y la identidad de marca. Nada se guarda: la propuesta reemplaza el campo y el dueño la revisa |

## Uso WA-SUG-001: costo por sugerencia (m-24936838), 2026-11-04

**Sin llamada real todavía.** Lo medido es offline, con el cliente falso de
`packages/api/tests/test_whatsapp_menu_suggest_ai.py` y el medidor en dólares de `claude_tools`.

- **Tope duro por sugerencia: US$0,17** (`SUGGEST_BUDGET_USD`, un `DollarMeter` por toque). Cubre
  el primer turno y el único reintento en su peor caso con la entrada más grande que permiten los
  límites del módulo (20 datos de 160 caracteres, 12 respuestas de 300, campo de 1.024): peor turno
  US$0,0836, pinado por `test_the_budget_pays_two_worst_turns_of_the_largest_input`.
- **Peor caso de una sugerencia normal** (respuesta «Horario» con dos datos, una respuesta vecina y
  una identidad de marca corta): 3.956 bytes de pedido, techo de 4.956 tokens → **US$0,043 por turno**
  con toda la salida gastada.
- **Costo esperado:** con unos 1.200–1.500 tokens de entrada y 300–600 de salida (el texto pide a lo
  sumo 400 caracteres), **US$0,005–0,016 por sugerencia**; el doble si hay reintento (versión repetida,
  palabra prohibida o hechos añadidos).

Qué se probó (offline): saludo y respuesta, huecos que se conservan o se reponen y salen en
`missing`, huecos que solo se completan con un dato real, hechos añadidos (un reintento y después
aviso), palabra o afirmación prohibida (un reintento y después `SuggestUnavailable`), sin identidad
de marca (`neutral_voice`, sin emojis), «Otra versión» repetida, recorte por largo, rechazo, sin
herramienta, sin clave y presupuesto agotado (no se envía nada).

**Pendiente:** una muestra real con el menú de Bianki para confirmar tokens y que el modelo respeta
los huecos; anotarla aquí y en `pruebas.md` cuando se haga.
