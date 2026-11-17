# Claude Sonnet 5.5: «Sugerir con IA» del menú de WhatsApp

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), clave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-sonnet-5-5`, esfuerzo `low`, una herramienta estricta (`propose_text`), `max_tokens` 3.072 |
| Precio | US$2 de entrada / US$10 de salida por millón; escritura de caché (5 min) US$2,50, lectura US$0,10 (`claude_tools.PRICES` y `CACHE_READ_PRICES`) |
| Uso en Qualify | `qualify_api.whatsapp.menus.suggest_ai` (m-24936838): propone el saludo o una «respuesta de siempre» con la voz de la marca y solo con los datos que escribió el dueño. Versión de prompt `wa-suggest-1` (`PROMPT_VERSION`, va en el log de cada llamada). También lo usa «Mejorar mi texto» del generador (`creative/context_ai.py`, tres versiones desde `context-v4-three-versions`, escena sin texto desde `context-v5-scene-no-text`; ver «Uso MEJORAR-TEXTO-001» y «-002» abajo) |
| Datos | Lo que el dueño escribió en la pantalla (datos del negocio, otras respuestas, el texto del campo) y la identidad de marca. Nada se guarda: la propuesta reemplaza el campo y el dueño la revisa |

## Uso WA-SUG-001: costo por sugerencia (m-24936838), 2026-11-04

**Costos medidos solo offline** (el uso real del 2026-11-05 está al final de esta sección, sin
tokens registrados). Lo medido es offline, con el cliente falso de
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

**Probado por el fundador el 2026-11-05 en producción, con Bianki; sin medición de llamadas, tokens,
costo ni respeto de los huecos** ([`pruebas.md` WA-VIVO-001](pruebas.md#wa-vivo-001)). La propuesta
no se guarda y el registro de consumo está vacío en toda la base (`consumption_ledger`, 0 filas: no
hay `consumption_scope` abierto en ningún camino); los logs con `usd=` se perdieron al recrear los
contenedores. Ningún cambio del menú publicado se puede atribuir con certeza a `wa-suggest-1`. Los
costos de arriba siguen siendo estimaciones offline. Falta repetir la muestra con el registro activo.

## Uso WA-IMP-001: «Cargar mi menú desde una foto o desde mi página» (m-24936840), 2026-11-04

| Campo | Valor |
|---|---|
| Módulo | `qualify_api.whatsapp.menus.import_ai` (`propose_menu_facts`) |
| Modelo | `claude-sonnet-5-5`, esfuerzo `low`, herramienta estricta `proponer_datos_menu`, `max_tokens` 8.000 |
| Prompt | `wa-import-3` (`PROMPT_VERSION`, va en `ImportProposal` y en el log). `wa-import-2` → `wa-import-3` (m-24955838, 2026-11-06): cada producto trae `category` (el título de sección del documento con `category_heading` verdadero, o un grupo corto por tipo, en plural, máx. 24 caracteres; vacío si duda) y el código la limpia (`tidy_categories`: mayúscula inicial, una sola grafía por categoría, fuera frases y nombres largos, y una categoría de un solo producto solo si es título del documento). Sin llamada real nueva: medido offline; falta medirlo con un menú real. `wa-import-1` → `wa-import-2` (m-24945867, 2026-11-04): cada dato trae `kind` (`value` = lo más corto que llena el hueco de la plantilla, «Llevamos tu pedido a [zona]»; `sentence` = una explicación literal, «se confirma por WhatsApp», que reemplaza todo el texto de la respuesta), y el código lo corrige solo (`fact_kind`: más de 40 caracteres —60 en horario, 120 en dirección—, punto final, verbo conjugado, o un tiempo de entrega que no es número ni rango → `sentence`). Sin llamada real nueva: medido offline |
| Entrada | Una foto (JPG, PNG, WEBP) o un PDF de hasta 10 MB, o el texto de una página web pública (máximo 12.000 caracteres) |
| Salida | Datos (`hours`, `address`, `delivery_zone`, `delivery_cost`, `delivery_time`, `payment_methods`, `reservations`) y productos con precio, cada uno con su cita literal. Nada se guarda: el dueño acepta dato por dato |

**Costos medidos solo offline** (el uso real del 2026-11-04 está al final de esta sección, sin
tokens registrados). Lo medido es offline (`packages/api/tests/test_whatsapp_menu_import_ai.py`,
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

**Uso real del 2026-11-04, con `wa-import-1`, en producción con Bianki** ([`pruebas.md`
WA-VIVO-001](pruebas.md#wa-vivo-001)): una importación (según el commit de la corrección, desde la
página web) llenó **7 de los 9 huecos** del menú inicial en 4 respuestas y creó **22 productos** con
precio en el mismo minuto. Es la importación que mostró el error de frases como valores corregido en
`wa-import-2` (merge una hora después), y **ese texto roto sigue en la respuesta «Domicilio» del
menú publicado**: `definition_gaps` da 0 porque no queda ningún `[hueco]`. También «San Cristóbal»
sale repetido en «Ubicación».

**Sin medición:** llamadas, tokens y costo (registro de consumo vacío, logs perdidos, Langfuse no
consultado), datos descartados (`dropped`), aciertos de las citas y precios frente a la carta.
**`wa-import-2` no tiene ninguna llamada real registrada.** Pendiente: la carta impresa (foto y PDF)
y la página de Bianki con `wa-import-2` y el registro de consumo activo, para confirmar tokens, que
`count_tokens` acepta el pedido y la clasificación `value`/`sentence`.

## Uso MEJORAR-TEXTO-001: «Mejorar mi texto» del generador con tres versiones (m-25017274), 2026-11-13

| Campo | Valor |
|---|---|
| Código | `qualify_api.creative.context_ai.enhance_context`, función de consumo `potenciar-contexto` |
| Versión de prompt | `context-v4-three-versions` (antes `context-v3-compact-300`) |
| Configuración | `claude-sonnet-5-5`, esfuerzo `low`, herramienta estricta `propose_context` con una propiedad por enfoque (`directa`, `descriptiva`, `cercana`; escena: `producto`, `lugar`, `momento`) + `added_facts`; `max_tokens` 6.144; tope de 300 caracteres por versión |
| Entrada nueva | tipo de publicación, formato y, en «Otra versión», hasta 9 versiones ya mostradas |
| Costo medido | **US$0,0068 por pulsación** (12 llamadas reales, 6 textos ficticios de comida); antes US$0,0032 |
| Calidad medida | ninguna versión repetida; similitud entre pulsaciones 0,625 (antes 0,995); sin números inventados |
| Creaciones | no gasta ninguna; el costo solo queda en el registro de consumo en dólares |

Detalle, tabla completa y lo que queda sin medir: [`pruebas.md` § MEJORAR-TEXTO-001](pruebas.md#mejorar-texto-001).

## Uso MEJORAR-TEXTO-002: la escena de una imagen sin precio ni letreros (m-25017274), 2026-11-13

| Campo | Valor |
|---|---|
| Versión de prompt | `context-v5-scene-no-text` (antes `context-v4-three-versions`) |
| Cambio | en una ESCENA solo se describe lo que se ve; «Datos clave» orientan, nunca se escriben; filtro determinista `scene_text_request` descarta la versión que pide precio, letrero, etiqueta, texto, «$» o una cifra de «Datos clave» (las negaciones y las palabras del propio dueño pasan) |
| Resultado medido | escenas con precio que piden texto en la imagen, según un juez de la evaluación independiente del filtro y más estricto: 24 de 36 → 0 de 36; textos de publicación sin regresión (similitud entre pulsaciones 0,683 → 0,548, el precio se conserva) |
| Costo medido | US$0,0058 por pulsación en escena, US$0,0068 en texto |

Detalle: [`pruebas.md` § MEJORAR-TEXTO-002](pruebas.md#mejorar-texto-002).

## Uso CAPA-001, CAPA-002 y CAPA-003: la capa de texto de imagen y carrusel (m-25017283, m-25017292), 2026-11-14/15

| Campo | Valor |
|---|---|
| Código | `qualify_api.creative.image_pipeline.layer.write_layers`, función de consumo `capa-de-texto` |
| Versión de prompt | `capa-v4` en el código (revisión de redacción de `capa-v3`: sin el ejemplo «nuevo horario», «escribe corto», máximo de bloques de `info_card` según la foto): **sin medir**. `capa-v3` (tabla por pieza con solo sus diseños, largo ideal y máximo de cada texto; sin bloques de datos donde ningún diseño los lleva; `price_product_id` cerrado a los productos con precio; `info_card` para «Información de tu negocio»): medido en CAPA-003. `capa-v2` en CAPA-002, `capa-v1` en CAPA-001 |
| Configuración | `claude-sonnet-5-5`, esfuerzo `low`, herramienta estricta `escribir_capa` (una entrada por imagen), `max_tokens` 4.000, tope de US$0,25 por pieza para todas sus llamadas (regeneración incluida); la foto va en base64 y se enmascara en Langfuse; el tope previo de cada turno cuenta las fotos con la regla de visión de Anthropic (≈ ancho × alto / 750 tras reducir a ≤ 1.568 px y ≈ 1,15 MP: ~1.530 tokens por base de Seedream) |
| Reintentos | en la cola, cada llamada es un paso guardado: un reintento lee la respuesta y no vuelve a pagarla |
| Interruptor | `QUALIFY_IMAGE_LAYER=on` (todos los negocios) o `QUALIFY_IMAGE_LAYER_TENANTS` (piloto); encendido para todos en producción desde 2026-11-17 (fundador) |
| Costo medido | `capa-v3` (CAPA-003): media US$0,015 por foto, ninguna con reparación; carrusel de 6 diap. US$0,101 (con reparación). `capa-v2` (CAPA-002): media US$0,013 por foto (US$0,010 sin reparación, US$0,022 con ella); carrusel entero en una llamada US$0,053 (6 diap.), US$0,080 (5) y US$0,131 (8). `capa-v1` (CAPA-001): media US$0,016 por foto |
| Latencia medida | `capa-v3`: mediana 4,2 s por foto (máx. 7,4 s); carrusel de 6 diap. 25,2 s; render `layer_still` local 2,1 s por imagen. `capa-v2`: mediana 3,2 s y p95 6,3 s por foto; carrusel 14,0 s (6 diap.), 17,2 s (5) y 30,7 s (8) |
| Calidad medida | `capa-v3`: 10/10 fotos y 6/6 diapositivas válidas; 0/10 fotos reparadas (las tres causas de CAPA-002 desaparecieron), el carrusel 1 vez (otras causas); `info_card` en las dos piezas de datos; 12 de 40 textos sobre dos tercios del límite; el render dibujó 16/16 sin rechazos ni deriva de catálogo (2 cambios de diseño, 1 texto quitado); `base_has_invented_text` 11/14. `capa-v2`: 30/30 fotos y 19/19 diapositivas con capa válida, ninguna perdida; reparación en 27 % de las fotos (parámetros de `band`) y en 2 de 3 carruseles (`price_ref` a un producto sin precio); ningún precio inventado; `unsupported_claims` 0 marcas y 2 fugas pequeñas; 60 de 127 textos pasan de dos tercios del límite; `base_has_invented_text` 42/45 con la etiqueta humana. `capa-v1`: 10/10 válidas, 9/10 |

**Primera pieza real en producción (CAPA-004, 2026-11-17):** Bianki, una «Imagen» 4:5 con `capa-v4`: la llamada tardó ~9 s y el render 3,0 s; la pieza salió bien, con dos caídas del compositor (foto achicada en `band`, palabra de acento sin contraste). Su costo no quedó en el registro de la pieza (error m-25042157, arreglado en su rama: cada llamada que consumió tokens queda como una línea de la pieza, también una que falló después de pagar, cuyos tokens se guardan con el error del paso y los anota la pasada que termina). Por lectura del código, el registro de consumo de Claude (`_book_consumption`) anota la llamada; la fila en producción no se revisó. Una sola imagen: no es una medición.

Detalle: [`pruebas.md` § CAPA-004](pruebas.md#capa-004), [§ CAPA-003](pruebas.md#capa-003), [§ CAPA-002](pruebas.md#capa-002) y [§ CAPA-001](pruebas.md#capa-001).
