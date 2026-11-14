# Claude Sonnet 5: rubro y etiquetas del asistente de identidad de marca y de la precarga del Alta

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), clave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-sonnet-5`, con razonamiento. Rubro: esfuerzo `low` (`hashtags/from_profile.py`, `max_tokens` 4.000). Elección de etiquetas del catálogo: esfuerzo `medium`, hasta 8 turnos con herramientas (`hashtags/ai.py` `select_hashtags`, `max_tokens` 16.000 por turno) |
| Precio | US$2 de entrada / US$10 de salida por millón; escritura de caché (5 min) US$2,50, lectura US$0,20. Verificado el 2026-10-25 en [platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing): el precio introductorio quedó como estándar. Coincide con `claude_tools.PRICES` |
| Uso en Qualify | `qualify_api.creative.brand_prefill` (precarga del Alta, PB-3/PB-4) y el paso de rubro del asistente web. Versiones de prompt `from_profile:6c769545282d` y `select_hashtags:16a6035cc6d1` (ver `rubro_prompt_version` y `catalog_prompt_version`) |
| Por qué Sonnet y no Haiku | En `packages/api/evals/hashtag_ai`, Haiku cayó en la trampa del nicho vecino (`#comidacallejera` para una hamburguesería smash) y Sonnet no |
| Datos | Texto público de la cuenta de Instagram (biografía, categoría, hasta 12 pies de foto, etiquetas usadas) y el catálogo de etiquetas |

## Uso PB6-001: costo de la precarga del Alta (m-24852200), 2026-10-25

Detalle completo en la [bitácora, PB6-001](pruebas.md#pb6-001).

- Una precarga con contenido hace **2 corridas** (rubro y etiquetas del catálogo).
- Cuesta **US$0,015–0,034 de Claude**. Con los 2 créditos de ScrapeCreators, **US$0,019–0,038 por Alta** (media US$0,0275).
- Una cuenta vacía no llama a Claude: US$0,0038.
- El catálogo se lleva el 75–90 % del costo de Claude.
- **Riesgo:** `CallCaps` limita corridas, no tokens. El techo teórico con `max_tokens` lleno ronda US$1,7 por Alta.

## Uso PARTES-001: «Proponerme las partes» sin reel (VE-14, m-24921071), 2026-11-06

Detalle completo en la [bitácora, PARTES-001](pruebas.md#partes-001).

- `qualify_api.creative.parts_ai.propose_parts`: esfuerzo `medium`, herramienta estricta `proponer_partes_video`, prompt `proponer-partes-v1`, luego `proponer-partes-v2`, `proponer-partes-v3` (2026-11-06, solo medida) y `proponer-partes-v3.1` (2026-11-07, la vigente), tope USD 0,12 por propuesta y guarda contra la tabla `v7`.
- 20 temas reales de Nibbles, dos corridas: **40/40 respuestas sin fallo**, siempre 4 o 5 partes distintas, sin precios. Usables 17/20 y 19/20.
- **US$0,0068 por propuesta** de media (máx. US$0,0104); latencia media 8,3 s, p95 18,3 s. Gasto de las dos corridas v1: US$0,2741.
- **Pendiente antes de activarlo (v1):** inventa ingredientes en 5 de 20 propuestas, el cierre casi nunca muestra la acción de pedir y se pasa unos 3 s de la duración pedida.
- **v2 (`proponer-partes-v2`), mismos 20 casos:** la duración queda en 19–20 s en las 20 (lo asegura el código, `fit_to_target`). Los cierres que piden o reciben el producto suben de 1 a 7 de 20. Pero los componentes agregados **empeoran** (de 5 a 9 de 20; el queso, que el catálogo no menciona, aparece en 18 de 20 en ambas versiones) y el comienzo con la plancha sube de 9 a 11 de 20. US$0,0070 por propuesta. Causa probable: Claude no ve las fotos y el catálogo es escueto. Una regla en el prompt no alcanza.
- **v3 (`proponer-partes-v3`, m-24973463), mismos 20 casos:** reemplaza a v2 (aprobado por el fundador el 2026-11-06). Describe las partes con palabras de todos los días y, si aparece vocabulario de cine, el código la devuelve en el único turno de corrección (`film_words`). Propuestas con palabras de cine: de 20/20 a 1/20. Usables 20/20. Usó el turno de corrección en 4 de 20. US$0,0087 por propuesta. El cierre empeora: 4 de 20 piden o reciben (v2: 7). Gasto de la corrida: US$0,1742.
- **v3.1 (`proponer-partes-v3.1`, 2026-11-07), mismos 20 casos:** el cierre muestra cómo el cliente consigue el producto (15 de 20 piden, reciben o se lo llevan, leído a mano; v3: 4), cada descripción es una frase de 25 palabras como máximo (el largo lo revisa el código; mediana 110 caracteres) y no describe sonidos (quedan 4 de 20 con «chisporroteo»). Sin palabras de cine. US$0,0069 por propuesta; gasto de la corrida US$0,1371.
- Gasto total de la prueba: US$0,7260 (cinco corridas).

## Uso NIVELES-001: niveles de consciencia y ventajas del negocio en «10 variaciones» y en las partes (m-25026482), 2026-11-13

Detalle completo en la [bitácora, NIVELES-001](pruebas.md#niveles-001). Ajustes de producción: esfuerzo `medium`; ángulos `max_tokens` 6.000, partes `proponer-partes-v3.2`. Línea base: `a6667370`.

- **Ángulos:** 14/14 juegos con 2 ángulos por nivel exactos, 0 etiquetas inválidas; 0 datos inventados por la extracción determinista (140 ideas). Calidad del juez sin cambio (test 3,52 → 3,57). En test, solution_aware cumple su nivel solo 0,50 y most_aware inventa una reserva en 1/6: quedan «no fiable». US$0,0250 → US$0,029 por juego (+15 %).
- **Partes:** v3.2 sin ventajas ni nivel es idéntico byte a byte a v3.1. Con nivel y ventajas usa una ventaja en 0,87 de los planes, pero most_aware no acorta el plan (4 partes en ambos brazos). US$0,006–0,008 por propuesta.
- Gasto de la medición completa: US$1,83, en la bitácora.

## Uso NIVELES-002: arreglos de los niveles, segunda pasada (m-25026482), 2026-11-13

Detalle en la [bitácora, NIVELES-002](pruebas.md#niveles-002). Mismos ajustes; prompt de partes `proponer-partes-v3.3`.

- **Ángulos con ventajas (test):** solution_aware 0,50 → 0,70, todavía «no fiable». Ofertas o servicios inventados (determinista) 0,20 → 0,08; en most_aware 0,67 → 0,30, por «reserva» y «para llevar». Sin regresiones en test; reparto exacto 15/15. US$0,031 por juego.
- **Partes:** v3.3 sin ventajas ni nivel es idéntica byte a byte a v3.1. product_aware pasa 6/6 con la rúbrica corregida.

## Uso NIVELES-003: tercera vuelta de redacción de los niveles (m-25026482), 2026-11-13

Detalle en la [bitácora, NIVELES-003](pruebas.md#niveles-003). Prompt de ángulos de `fcd2e8c0`, mismos ajustes.

- **Ángulos con ventajas (test, n 30 por nivel):** solution_aware pasa de 0,70 a 0,83 (fiable). Ofertas o servicios inventados en most_aware bajan de 0,30 a 0,10, y en total de 0,08 a 0,047.
- **Regresión:** product_aware baja de 0,90 (n 10) a 0,77, «no fiable». US$0,031 por juego.
- **Partes:** los números de NIVELES-001/002 se tomaron sobre la v3.1 de main y ya no describen `proponer-partes-v3.4`.

## Uso NIVELES-004: el nivel en el video por partes (m-25026509), 2026-11-13

Detalle en la [bitácora, NIVELES-004](pruebas.md#niveles-004). `proponer-partes-v3.4` sobre la v3.2 de main, con el nivel por `PartsBrief.awareness_level`. Reemplaza los números de partes de NIVELES-001/002, que se tomaron sobre la v3.1.

- **Validez:** 36/36 propuestas sin rechazos ni precios, 4–5 partes, 17–20 s.
- **Cumple su nivel (juez, n 6):** unaware 6/6, product_aware 6/6, solution_aware 5/6, problem_aware 3/6 (no muestra el dilema). most_aware 0/6: es la base por diseño, con la misma huella de prompt.
- US$0,006–0,008 por propuesta.
