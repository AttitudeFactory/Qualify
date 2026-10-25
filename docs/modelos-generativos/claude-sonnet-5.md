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
