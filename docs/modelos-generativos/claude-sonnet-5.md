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

- `qualify_api.creative.parts_ai.propose_parts`: esfuerzo `medium`, herramienta estricta `proponer_partes_video`, prompt `proponer-partes-v1`, luego `proponer-partes-v2` `proponer-partes-v3` (2026-11-06, solo medida) y `proponer-partes-v3.1` (2026-11-07, la vigente), tope USD 0,12 por propuesta y guarda contra la tabla `v7`.
- 20 temas reales de Nibbles, dos corridas: **40/40 respuestas sin fallo**, siempre 4 o 5 partes distintas, sin precios. Usables 17/20 y 19/20.
- **US$0,0068 por propuesta** de media (máx. US$0,0104); latencia media 8,3 s, p95 18,3 s. Gasto de las dos corridas v1: US$0,2741.
- **Pendiente antes de activarlo (v1):** inventa ingredientes en 5 de 20 propuestas, el cierre casi nunca muestra la acción de pedir y se pasa unos 3 s de la duración pedida.
- **v2 (`proponer-partes-v2`), mismos 20 casos:** la duración queda en 19–20 s en las 20 (lo asegura el código, `fit_to_target`). Los cierres que piden o reciben el producto suben de 1 a 7 de 20. Pero los componentes agregados **empeoran** (de 5 a 9 de 20; el queso, que el catálogo no menciona, aparece en 18 de 20 en ambas versiones) y el comienzo con la plancha sube de 9 a 11 de 20. US$0,0070 por propuesta. Causa probable: Claude no ve las fotos y el catálogo es escueto. Una regla en el prompt no alcanza.
- **v3 (`proponer-partes-v3`, m-24973463), mismos 20 casos:** reemplaza a v2 (aprobado por el fundador el 2026-11-06). Describe las partes con palabras de todos los días y, si aparece vocabulario de cine, el código la devuelve en el único turno de corrección (`film_words`). Propuestas con palabras de cine: de 20/20 a 1/20. Usables 20/20. Usó el turno de corrección en 4 de 20. US$0,0087 por propuesta. El cierre empeora: 4 de 20 piden o reciben (v2: 7). Gasto de la corrida: US$0,1742.
- **v3.1 (`proponer-partes-v3.1`, 2026-11-07), mismos 20 casos:** el cierre muestra cómo el cliente consigue el producto (15 de 20 piden, reciben o se lo llevan, leído a mano; v3: 4), cada descripción es una frase de 25 palabras como máximo (lo revisa el código; mediana 110 caracteres) y no describe sonidos (quedan 4 de 20 con «chisporroteo»). Sin palabras de cine. US$0,0069 por propuesta; gasto de la corrida US$0,1371.
- Gasto total de la prueba: US$0,7260 (cinco corridas).
