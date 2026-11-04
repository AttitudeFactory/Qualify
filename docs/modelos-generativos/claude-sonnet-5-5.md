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

## Uso WA-IMP-001: «Cargar mi menú desde una foto o desde mi página» (m-24936840), 2026-11-04

| Campo | Valor |
|---|---|
| Módulo | `qualify_api.whatsapp.menus.import_ai` (`propose_menu_facts`) |
| Modelo | `claude-sonnet-5-5`, esfuerzo `low`, herramienta estricta `proponer_datos_menu`, `max_tokens` 8.000 |
| Prompt | `wa-import-2` (`PROMPT_VERSION`, va en `ImportProposal` y en el log). `wa-import-1` → `wa-import-2` (m-24945867, 2026-11-04): cada dato trae `kind` (`value` = lo más corto que llena el hueco de la plantilla, «Llevamos tu pedido a [zona]»; `sentence` = una explicación literal, «se confirma por WhatsApp», que reemplaza todo el texto de la respuesta), y el código lo corrige solo (`fact_kind`: más de 40 caracteres —60 en horario, 120 en dirección—, punto final, verbo conjugado, o un tiempo de entrega que no es número ni rango → `sentence`). Sin llamada real nueva: medido offline |
| Entrada | Una foto (JPG, PNG, WEBP) o un PDF de hasta 10 MB, o el texto de una página web pública (máximo 12.000 caracteres) |
| Salida | Datos (`hours`, `address`, `delivery_zone`, `delivery_cost`, `delivery_time`, `payment_methods`, `reservations`) y productos con precio, cada uno con su cita literal. Nada se guarda: el dueño acepta dato por dato |

**Sin llamada real todavía.** Lo medido es offline (`packages/api/tests/test_whatsapp_menu_import_ai.py`,
cliente falso y el medidor en dólares de `claude_tools`).

- **Tope duro por importación: US$0,30** (`IMPORT_BUDGET_USD`, un `DollarMeter` por importación),
  pinado por `test_the_budget_pays_two_worst_turns_of_the_largest_input`. Cubre el primer turno y
  el único reintento (rechazo, truncado o sin herramienta) en su peor caso:
  - foto o PDF: se mide antes con `messages.count_tokens` (gratis; los bytes en base64 no sirven
    de cota). Por encima de 24.000 tokens se rechaza sin llamada pagada («Sube solo las páginas de
    tu menú»). Techo reservado 27.400 tokens (conteo +10 % y margen) → peor turno **US$0,1485**,
    peor importación **US$0,297**;
  - página web: texto tope 12.000 caracteres y 16.000 bytes ya escapados → techo 20.012 tokens →
    peor turno **US$0,130**, peor importación **US$0,26**.
- **Costo esperado** (un solo turno, sin reintento): una foto de menú ronda 1.500–3.000 tokens de
  imagen más ~2.000 de instrucciones; con 1.000–2.500 de salida, **US$0,02–0,045 por importación**.
  Una página típica (4.000–6.000 tokens) cae en el mismo rango.

Qué se comprueba en código, después del modelo:

- Toda propuesta trae su cita (`evidence`). En una **página web** la cita tiene que estar en el
  texto (`brief_ai.quote_in_text`, y coincidencia de palabras completas para citas cortas como
  «Nequi»); si no, se descarta y se cuenta en `warnings`.
- **Límite conocido:** en una **foto o un PDF** no hay capa de texto contra la cual comprobar (el
  mismo límite de `brief_ai`, `verified=None`): la cita es la lectura del propio modelo. Se aplica lo
  que sí se puede comprobar (cada número del valor está en la cita; el nombre y el precio del
  producto están en su cita) y la propuesta lleva el aviso «Revisa cada dato con tu foto antes de
  usarlo».
- Precios: `price_text` literal → `Decimal` conservador (un rango o dos números no dan monto); la
  moneda solo con una marca explícita (COP, Bs., US$, U$S, $U…). Un «$» solo es ambiguo entre
  Colombia, Venezuela y Uruguay: moneda vacía, nunca adivinada.

Fuera de alcance: enlaces de Instagram, Facebook y TikTok (`SourceUnsupported` con motivo en
español). Leerlos exige el lector de ScrapeCreators de `creative/brand_prefill.py`, que necesita la
caché de perfiles del tenant (base de datos) y créditos fuera de este medidor.

**Pendiente:** una muestra real con la carta impresa de Bianki (foto y PDF) y una página web real,
para confirmar tokens, que `count_tokens` acepta el mismo pedido y cuántas citas de foto acierta el
modelo letra por letra; anotarla aquí y en `pruebas.md`.
